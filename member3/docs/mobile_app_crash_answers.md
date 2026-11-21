# Mobile app ↔ website: crash answers ("Are you safe?")

The app (github.com/KaustubhGumaste/AgathsetuAPP) and the website now share one
backend and one database: the website's FastAPI + PostgreSQL (`aghat_sethu`) on
the AWS server, `https://aghatsethu.duckdns.org`. The app's "portal" mode
(`src/adapters.ts`) already speaks this backend; only the pieces below change.

## Backend contract (live on the website's backend)

| What | Request | Notes |
|---|---|---|
| Answer a crash | `POST /api/citizen/incidents/{id}/confirm` body `{"accident_occurred": bool}` **or** `{"response": "accident" \| "not_serious" \| "false_alarm", "note": "..."}` | Citizen JWT. `{id}` = the crash notification's `incident_id` (`CR-XXXXXXXXXX` or a UUID). 404 if it is not the caller's crash. Answering again replaces the answer. Also marks that crash notification read. |
| Answer reply | `{"id", "incident_id", "response", "accident_occurred", "label", "note", "channel", "responded_at", "review_status", "review_note", "reviewed_at"}` | `accident_occurred` is `false` only for `false_alarm`. `review_status`: `pending` (false alarm / minor wait for the authority), `accepted`, `rejected`, or `null` for an accident. |
| Crash detail | `GET /api/citizen/incidents/{id}` | Now includes `"response"` (same shape, or `null`). `status`: `Under review` / `False alarm` / `Resolved`. |
| Notifications | `GET /api/citizen/notifications` | Crash notifications have `kind: "crash"` and `incident_id: "CR-..."`; each crash note carries `"response"` (`null` = unanswered). `kind: "review_outcome"` = the authority decided on an answer (no alarm). |
| Live events | `wss://<host>/ws/events` | First message: `{"type":"auth","token":"<JWT>"}` → `{"type":"ready"}`. Then `{"type":"crash.detected","data":{"report":{"incident_key":"CR-...","vehicle":{"plate":"..."},"location":"...","created_at":"..."}}}`, `crash.response_reviewed`, `notification.created`, and `{"type":"ping"}` every 25 s. The token is never put in the URL. |

## Prompt for the app side

Paste this into Claude Code (or follow it by hand) in the AgathsetuAPP repo:

```text
Our app must use the website's backend (https://aghatsethu.duckdns.org) as its
only backend, so that a citizen's crash answer ("accident" / "not serious" /
"false alarm") reaches the authority portal and both show the same data. The
app's "portal" dialect in src/adapters.ts already talks to this backend. Make
these changes:

1. Send crash answers to the server in portal mode too.
   In App.tsx `answerIncident`, remove the `if (portalServer) { ... savedOnServer = false ... }`
   branch so that BOTH dialects call
     POST /api/citizen/incidents/{incidentId}/confirm  {"accident_occurred": <bool>}
   and read `accident_occurred` from the reply. Drop the "This server cannot
   receive crash answers" / "Marked as a false alarm on this phone" messages.
   The server marks the crash notification read itself, so there is no need to
   call /notifications/{id}/read any more.

2. Add a third answer, "Minor, not serious".
   Next to the existing accident / false-alarm buttons on the crash alarm screen,
   add a button that sends {"response": "not_serious"} to the same endpoint
   (treat it like an accident locally: stop the alarm, keep sharing location).
   The reply has `response` ("accident" | "not_serious" | "false_alarm"),
   `label` (human text) and `review_status` ("pending" | "accepted" | "rejected" | null).
   On the Crash Incident Report screen show `label` and, when `review_status` is
   "pending", "Waiting for the traffic authority to check it". Read the saved
   answer from GET /api/citizen/incidents/{id} -> "response" (null = unanswered).
   Keep the mainapp dialect working: it only knows {"accident_occurred"}, so send
   "not_serious" only when the dialect is "portal".

3. Instant crash alarm in portal mode over /ws/events.
   The website backend has no /ws/citizen/alerts. In portal mode, open
     wss://<host>/ws/events
   (build it from the API base URL; do NOT put the token in the URL), send
     {"type":"auth","token":"<JWT>"}
   as the first message, wait for {"type":"ready"}, then on
     {"type":"crash.detected","data":{"report":{"incident_key":"CR-..."}}}
   call raiseCitizenAlarm(report.incident_key). Ignore {"type":"ping"}.
   Reconnect with backoff like the existing socket; on close code 1008 sign out.
   Keep the 5-second notification poll as the fallback (crash notifications
   have kind "crash" and incident_id "CR-..."; the Kotlin CrashMonitorService
   check `kind.contains("crash") && incident_id` already matches them).
   Do not treat kind "review_outcome" as a crash.

4. Point release builds at the website backend.
   In eas.json set EXPO_PUBLIC_API_URL to https://aghatsethu.duckdns.org for
   the preview and production profiles (and in .env for local runs). The app's
   own backend/ folder is no longer used for real data; leave it in the repo
   for the mainapp dialect but do not deploy it for the demo.

5. Accounts: users must sign up / log in on the website backend. Existing
   accounts on the old app server do not carry over.

Run `npx tsc --noEmit` and `npx expo lint` before finishing, and test:
log in as a citizen whose vehicle is in a crash -> the alarm rings within a
second -> press "False alarm" -> the website's Crash Incident Radar
(/authority) shows "Owner: false alarm" live without a refresh.
```

## Crash case outcome (automatic)

"Minor" = `not_serious` or `false_alarm` (no need to involve the authority).

| Situation | Outcome |
|---|---|
| Single-vehicle crash, the owner answers minor | **resolved** at once (incident status `resolved`) |
| Two-vehicle crash, **both** owners answer minor | **resolved** |
| Two-vehicle crash, one minor + the other answers accident | **not resolved** |
| Two-vehicle crash, one minor + the other does not answer within **30 s** | **not resolved** (a late answer does not undo it) |
| Any owner answers accident (also later) | **not resolved**; an auto-resolved case reopens |

A vehicle whose owner cannot answer (unregistered, or only named as a partner)
never answers, so such a crash is never auto-resolved. Not-resolved cases keep the
minor answers `review_status: "pending"`; the authority then clicks
**Resolve as false alarm / minor crash** (`POST /api/authority/crash-responses/{id}/accept`,
false alarm -> incident `false_positive`, `resolved_at` / `resolved_by` set) or
**Keep open** (`/reject`).

Fields for the app (citizen and officer screens):
- `POST .../confirm` reply: `review_status` is `"accepted"` straight away when the case auto-resolves.
- `GET /api/citizen/incidents/{id}` and authority `GET /api/incidents/board`, `GET /api/incidents/{id}`
  (under `incident`): `"case": {"outcome": "waiting"|"resolved"|"not_resolved", "reason_code":
  "all_minor"|"accident"|"no_answer"|"authority", "reason", "automatic", "deadline_at",
  "vehicles": [{"plate", "answer"}]}`.
- Authority incident endpoints also carry `citizen_responses` (newest first, each with `id`,
  `response`, `review_status`, `plate`, `owner_name`) and `latest_citizen_response`; `resolved`
  is true for `resolved` and `false_positive`, and `false_alarm` marks the latter.
- `/ws/events`: `{"type": "crash.case_updated", "data": {"case": {...}}}` to the authority and the
  owners of that crash, besides `crash.response` / `crash.response_reviewed`.

## Who is alerted, and the 30-second rule

- **Every registered car in a crash** gets its owner a `kind: "crash"` notification (top-level
  `incident_id` = `CR-...`), an SMS and a `crash.detected` event: the car whose sensors raised
  the alert ("Crash detected for your vehicle ...") and its `collision_partner` ("Your vehicle
  ... may have been involved in a crash ..."). The partner text never names the other car or
  who caused it; the accusation still waits for the authority's review. Both owners can answer
  at `POST /api/citizen/incidents/{CR-key}/confirm`.
- Each owner has **30 s from their own alert**. Silent owners get a server-recorded answer
  `response: "no_answer"` (`channel: "system"`, `accident_occurred: true`) and the case becomes
  `not_resolved` with `reason_code: "no_answer"` and `severe: true`. The app's own 30 s
  auto-report `{"accident_occurred": true, "note": "No answer within 30 seconds..."}` is
  treated the same way (accident -> not resolved, severe). A late answer replaces the
  `no_answer` but does not undo the flag; the authority decides.
- `/ws/live-cameras` `crash_alert` messages now carry `incident_id` (the `CR-...` key the
  owners answer) and `location` (e.g. "Junction 2 (GPS ...)").

## How the authority side behaves

- Every answer appears live on the website's **Incident Radar** / **Incident Evidence**
  pages, with the case outcome badge (auto-resolved / not resolved / waiting).
  (The old Control Room page was removed; its API endpoints remain for the app.)
- The Incident Radar now updates live as answers arrive.

## Resolution codes (closing a crash needs proof)

An officer can mark a crash **resolved** only with its resolution code(s), plus
their own password as before. Crashes the owners resolve themselves (every owner
answered "minor") and the authority accepting an owner's answer need no code.

**Who generates the codes:** the server, never a person.

- **Owner codes.** Every owner alerted about a crash has their own 6-digit code.
  It is derived from the server secret, the crash and the owner (HMAC-SHA256), so
  nothing readable is stored. It is already in the crash alert SMS / notification
  text ("Resolution code: 123456 ..."). It works only for that crash and owner,
  for 24 h. A two-car crash needs **both** owners' codes.
- **Super-admin code.** An owner cannot be reached. The officer asks; a super
  admin (role `admin`) generates a random 6-digit code (Python `secrets`). It is
  shown once to the admin, stored as a hash only, single use, and valid for
  30 min. The admin passes it to the officer by phone or radio.
- 5 wrong codes on one crash lock it for 15 min. A new super-admin code lifts the lock.

### Endpoints

| Who | Call | Notes |
|---|---|---|
| Owner | `GET /api/citizen/incidents/{CR-key or id}` | new field `resolution_code: {code, expires_at, hint}`; `null` once resolved or expired |
| Officer | `GET /api/incidents/{incident_id}/resolution-code` | whose codes are needed (never the codes), `request` state, `locked_until` |
| Officer | `POST /api/incidents/{incident_id}/resolution-code/request` `{reason}` | ask the super admin |
| Officer | `POST /api/incidents/{incident_id}/resolve` `{password, note, codes: ["123456","654321"]}` or `{password, note, code: "123456"}` | 422 no code, 403 wrong / missing one, 423 locked; response has `resolved_with: "owner" \| "override"` |
| Super admin | `GET /api/admin/resolution-requests` | waiting requests |
| Super admin | `POST /api/admin/resolution-requests/{id}/issue` | response `code` (shown once) |
| Super admin | `POST /api/admin/resolution-requests/{id}/decline` | |
| Super admin | `POST /api/admin/incidents/{incident_id}/resolution-code` `{reason}` | generate without a request |

Live events on `/ws/events` (authority room): `resolution.code_requested`,
`resolution.code_issued`. Neither ever carries the code.

### Prompt for the app side

> On the owner's crash detail screen (the one that calls
> `GET /api/citizen/incidents/{id}`), when `resolution_code` is not null, show a
> card "Your resolution code" with `resolution_code.code` in large digits, the
> `hint` text and "valid until `expires_at`". Hide it when it is null. If the
> app's officer side resolves crashes, the resolve form must send
> `codes: [...]` (one field per owner, from `GET /api/incidents/{id}/resolution-code`
> `owners`) or a single super-admin `code`, and offer "Ask the super admin"
> (`POST .../resolution-code/request`). Show the 403 / 423 `detail` text to the
> officer. In the super admin's Officer Approvals tab, add a "Resolution-code
> requests" list (`GET /api/admin/resolution-requests`) with **Generate code**
> (show the returned `code` once, large) and **Decline**.
