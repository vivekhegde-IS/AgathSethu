/**
 * The owner's side of a crash alert, live:
 *  - CitizenLiveBridge: mounted once in the citizen layout. When a crash for
 *    one of the owner's vehicles arrives over /ws/events (or one is still
 *    unanswered when the page opens) it asks "Are you safe?" at once; other
 *    events show as toasts. No refresh needed.
 *  - CrashAnswerPanel: the three answers + current review state, also used on
 *    the incident report page.
 *  - NotificationBell: unread count in the top bar, updated live.
 *
 * Answers go to the same endpoint as the mobile app, so the app, this site
 * and the authority control room always show the same answer.
 */

import React, { useCallback, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { answerCrash, CrashAnswer, CrashResponseView, LiveEvent } from '@api/live'
import { fetchNotifications } from '@api/portal'
import { extractAuthError } from '@api/auth'
import { Modal } from '@components/ui'
import { useLiveEvents } from '@hooks/useLiveEvents'
import { ToastStack, useToasts, when } from './LiveWidgets'

const PROMPT_WINDOW_MS = 6 * 60 * 60 * 1000     // only ask about crashes from the last 6 hours

const REVIEW_TEXT: Record<string, string> = {
  pending: 'Waiting for the traffic authority to check it.',
  accepted: 'The traffic authority accepted your answer.',
  rejected: 'The traffic authority is still treating this as a crash.',
}

// ── answer buttons ───────────────────────────────────────────────────────────────
export const CrashAnswerPanel: React.FC<{
  refId: string
  current?: CrashResponseView | null
  onAnswered?: (answer: CrashResponseView) => void
  compact?: boolean
}> = ({ refId, current, onAnswered, compact }) => {
  const [busy, setBusy] = useState<CrashAnswer | null>(null)
  const [note, setNote] = useState('')
  const [error, setError] = useState('')

  const send = async (response: CrashAnswer) => {
    setBusy(response)
    setError('')
    try {
      const answer = await answerCrash(refId, response, note.trim() || undefined)
      setNote('')
      onAnswered?.(answer)
    } catch (e) {
      setError(extractAuthError(e))
    } finally {
      setBusy(null)
    }
  }

  const button = (response: CrashAnswer, label: string, style: string) => (
    <button
      type="button"
      disabled={busy !== null}
      onClick={() => send(response)}
      aria-pressed={current?.response === response}
      className={`flex-1 min-w-[140px] px-3 py-2.5 rounded-md text-sm font-semibold disabled:opacity-60 ${style} ${
        current?.response === response ? 'ring-2 ring-offset-2 ring-slate-900' : ''}`}
    >
      {busy === response ? 'Sending…' : label}
    </button>
  )

  return (
    <div className="space-y-3">
      {current && (
        <div className="p-3 rounded-md bg-slate-50 border border-slate-200 text-sm">
          <p className="font-semibold text-slate-900">You answered: {current.label}</p>
          <p className="text-xs text-slate-600">
            {when(current.responded_at)} · from the {current.channel === 'app' ? 'mobile app' : 'website'}
            {current.review_status && <> · {REVIEW_TEXT[current.review_status]}</>}
          </p>
          {current.review_note && <p className="text-xs text-slate-600 mt-1">Authority note: {current.review_note}</p>}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {button('accident', 'Yes, accident: I need help', 'bg-red-700 text-white hover:bg-red-800')}
        {button('not_serious', 'Minor, not serious', 'bg-amber-100 text-amber-950 border border-amber-400 hover:bg-amber-200')}
        {button('false_alarm', 'False alarm: no crash', 'bg-white text-slate-900 border border-slate-400 hover:bg-slate-50')}
      </div>
      {!compact && (
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={1000}
          placeholder="Anything the control room should know? (optional)"
          aria-label="Note for the control room"
          className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
        />
      )}
      <p className="text-xs text-slate-600">
        "False alarm" and "Minor" are checked by the traffic authority before the crash is closed.
        If anyone is hurt, call <a href="tel:112" className="font-semibold text-red-700 underline">112</a>.
      </p>
      {error && <p className="text-xs text-red-700">{error}</p>}
    </div>
  )
}

// ── "are you safe?" pop-up + toasts ──────────────────────────────────────────────
interface Prompt {
  ref: string
  title: string
  detail: string
}

export const CitizenLiveBridge: React.FC = () => {
  const [prompt, setPrompt] = useState<Prompt | null>(null)
  const [answered, setAnswered] = useState<CrashResponseView | null>(null)
  const asked = useRef(new Set<string>())       // never re-ask in this tab once shown
  const { toasts, push, dismiss } = useToasts()
  const location = useLocation()
  const onOwnerPage = location.pathname.startsWith('/me')    // that page shows its own toasts

  const ask = useCallback((next: Prompt) => {
    if (asked.current.has(next.ref)) return
    asked.current.add(next.ref)
    setAnswered(null)
    setPrompt(next)
  }, [])

  // Crashes that arrived while this tab was closed or offline.
  const sync = useCallback(() => {
    fetchNotifications()
      .then(({ notifications }) => {
        const pending = notifications.find((n) =>
          n.kind.includes('crash') && n.incident_id && !n.read && !n.response
          && n.created_at && Date.now() - new Date(n.created_at).getTime() < PROMPT_WINDOW_MS)
        if (pending?.incident_id) {
          ask({ ref: pending.incident_id, title: pending.title, detail: pending.message })
        }
      })
      .catch(() => undefined)
  }, [ask])

  const onEvent = useCallback((event: LiveEvent) => {
    const { report, notification, response } = event.data
    if (event.type === 'crash.detected' && report) {
      ask({
        ref: report.incident_key,
        title: `Crash detected: ${report.vehicle?.plate ?? 'your vehicle'}`,
        detail: `${report.location ?? ''} · ${when(report.created_at)}`,
      })
    } else if (onOwnerPage) {
      return
    } else if (event.type === 'crash.response_reviewed' && response) {
      push({ type: response.review_status === 'accepted' ? 'success' : 'warning',
             title: 'Crash report reviewed', message: REVIEW_TEXT[response.review_status ?? ''] })
    } else if (event.type === 'notification.created' && notification && notification.type !== 'crash') {
      push({ type: notification.type === 'fine' ? 'warning' : 'info', title: notification.title,
             message: notification.message })
    } else if (event.type === 'fine.issued' && event.data.fine) {
      push({ type: 'warning', title: 'New e-challan', message: `${event.data.fine.reason} · ${event.data.fine.plate}` })
    }
  }, [ask, push, onOwnerPage])

  useLiveEvents(onEvent, sync)

  return (
    <>
      <ToastStack toasts={toasts} onClose={dismiss} />
      <Modal isOpen={prompt !== null} onClose={() => setPrompt(null)} title="Are you safe?" maxWidth="xl">
        {prompt && (
          <div className="space-y-4" role="alertdialog" aria-label="Crash alert">
            <div className="p-3 rounded-md bg-red-50 border border-red-200">
              <p className="text-sm font-bold text-red-900">{prompt.title}</p>
              <p className="text-xs text-red-900/80 mt-1">{prompt.detail}</p>
            </div>
            {answered ? (
              <>
                <p className="text-sm text-slate-800">
                  Thank you. Your answer (<strong>{answered.label}</strong>) has been sent to the traffic control room.
                  {answered.response === 'accident' && ' Help is being coordinated; call 112 if anyone is injured.'}
                </p>
                <div className="flex gap-2 justify-end">
                  <Link to={`/citizen/incidents/${encodeURIComponent(prompt.ref)}`} onClick={() => setPrompt(null)}
                        className="px-3 py-2 rounded-md text-sm border border-slate-300">View report</Link>
                  <button type="button" onClick={() => setPrompt(null)}
                          className="px-3 py-2 rounded-md text-sm bg-blue-900 text-white">Close</button>
                </div>
              </>
            ) : (
              <>
                <CrashAnswerPanel refId={prompt.ref} onAnswered={setAnswered} />
                <button type="button" onClick={() => setPrompt(null)}
                        className="text-xs text-slate-600 hover:underline">Answer later (from Notifications)</button>
              </>
            )}
          </div>
        )}
      </Modal>
    </>
  )
}

// ── unread bell ──────────────────────────────────────────────────────────────────
export const NotificationBell: React.FC = () => {
  const [unread, setUnread] = useState(0)
  const load = useCallback(() => {
    fetchNotifications().then((r) => setUnread(r.unread)).catch(() => undefined)
  }, [])
  const status = useLiveEvents(load, load)
  return (
    <Link to="/citizen/notifications" className="relative inline-flex items-center gap-1.5 px-2 py-1 rounded-md hover:bg-slate-100"
          aria-label={`Notifications, ${unread} unread`}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"
           className="text-slate-700">
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.73 21a2 2 0 0 1-3.46 0" />
      </svg>
      {unread > 0 && (
        <span className="absolute -top-1 -right-1 min-w-[1.25rem] h-5 px-1 rounded-full bg-red-600 text-white text-[11px] font-bold flex items-center justify-center">
          {unread > 99 ? '99+' : unread}
        </span>
      )}
      <span className={`w-2 h-2 rounded-full ${status === 'live' ? 'bg-green-600' : 'bg-slate-400'}`}
            title={status === 'live' ? 'Live updates on' : 'Reconnecting…'} />
    </Link>
  )
}
