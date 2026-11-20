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
second -> press "False alarm" -> the website's authority Control Room
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

## How the authority side behaves

- Every answer appears live in **Control Room -> Owner answers**, on the crash in
  **Crash alerts**, and on the **Incident Radar** / **Incident Evidence** pages, with
  the case outcome badge (auto-resolved / not resolved / waiting).
- The Incident Radar now updates live as answers arrive.
