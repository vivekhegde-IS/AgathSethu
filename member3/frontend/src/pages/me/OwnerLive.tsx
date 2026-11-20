/**
 * /me — a vehicle owner's live page: their vehicle, fines, notifications and
 * text messages, updated live over /ws/events. Only this owner's data ever
 * reaches the page (the server scopes REST and the socket room).
 */

import React, { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  disputeFine, getOwnerOverview, LiveEvent, markNotificationsRead, markSmsRead, OwnerOverview, payFine,
  SmsView, unlinkGoogle,
} from '@api/live'
import { extractAuthError } from '@api/auth'
import { useLiveEvents } from '@hooks/useLiveEvents'
import {
  FineStatusBadge, GoogleButton, LivePill, rupees, ToastStack, useGoogleEnabled, useToasts, when,
} from '@components/live/LiveWidgets'

const PhonePanel: React.FC<{ sms: SmsView[]; unread: number; onOpen: () => void }> = ({ sms, unread, onOpen }) => (
  <section aria-label="Text messages" className="mx-auto w-full max-w-[300px]">
    <div className="rounded-[2.2rem] border-[10px] border-slate-900 bg-slate-900 shadow-2xl">
      <div className="rounded-[1.5rem] bg-slate-50 overflow-hidden">
        <div className="flex items-center justify-between px-4 pt-2 pb-1 text-[10px] text-slate-600">
          <span>{new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}</span>
          <span className="w-16 h-4 rounded-full bg-slate-900" />
          <span>5G ▮▮▮</span>
        </div>
        <button onClick={onOpen} className="w-full flex items-center justify-between px-4 py-2 border-b bg-white">
          <span className="text-sm font-semibold text-slate-900">Messages · AGHAT-SETU</span>
          {unread > 0 && (
            <span className="min-w-[1.25rem] h-5 px-1.5 rounded-full bg-red-600 text-white text-xs font-bold flex items-center justify-center"
                  aria-label={`${unread} unread text messages`}>
              {unread}
            </span>
          )}
        </button>
        <div className="h-[380px] overflow-y-auto px-3 py-3 space-y-2 flex flex-col-reverse" onClick={onOpen}>
          {sms.length === 0 && <p className="text-xs text-slate-500 text-center my-auto">No messages</p>}
          {sms.map((m) => (
            <div key={m.id} className="self-start max-w-[90%]">
              <div className={`rounded-2xl rounded-bl-sm px-3 py-2 text-[13px] leading-snug ${
                m.read ? 'bg-slate-200 text-slate-900' : 'bg-blue-600 text-white'}`}>
                {m.body}
              </div>
              <p className="text-[10px] text-slate-500 mt-0.5 ml-1">
                {when(m.created_at)} · {m.status === 'stored' ? 'simulated SMS' : m.status}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  </section>
)

export const OwnerLive: React.FC = () => {
  const [data, setData] = useState<OwnerOverview | null>(null)
  const [error, setError] = useState('')
  const { toasts, push, dismiss } = useToasts()
  const googleEnabled = useGoogleEnabled()
  const [params, setParams] = useSearchParams()

  const load = useCallback(() => {
    getOwnerOverview().then(setData).catch((e) => setError(extractAuthError(e)))
  }, [])

  useEffect(() => {
    if (params.get('linked')) {
      push({ type: 'success', title: 'Google account linked', message: 'You can now sign in with Google.' })
      setParams({}, { replace: true })
    }
  }, [params, setParams, push])

  const onEvent = useCallback((event: LiveEvent) => {
    const { fine, notification, sms, report } = event.data
    if (event.type === 'fine.issued' && fine) {
      push({ type: 'warning', title: `New fine: ${rupees(fine.amount)}`, message: `${fine.reason} · ${fine.plate}` })
    } else if (event.type === 'crash.detected' && report) {
      push({ type: 'danger', title: 'Crash detected', message: `${report.vehicle?.plate} · ${report.location ?? ''}` })
    } else if (event.type === 'notification.created' && notification && !sms
               && notification.type !== 'fine' && notification.type !== 'crash') {
      push({ type: 'info', title: notification.title, message: notification.message })
    }
    load()       // the server is the source of truth
  }, [load, push])

  const status = useLiveEvents(onEvent, load)

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn()
      push({ type: 'success', title: ok })
      load()
    } catch (e) {
      push({ type: 'danger', title: 'Action failed', message: extractAuthError(e) })
    }
  }

  if (error) return <div className="p-6 text-red-700">{error}</div>
  if (!data) return <div className="p-6 text-slate-600">Loading…</div>

  return (
    <div className="space-y-6">
      <ToastStack toasts={toasts} onClose={dismiss} />
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">My vehicle · {data.user.full_name}</h1>
          <p className="text-sm text-slate-600">Signed in as {data.user.username ?? data.user.full_name} in this tab</p>
        </div>
        <LivePill status={status} />
      </header>

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-6 min-w-0">
          <section className="grid sm:grid-cols-2 gap-4">
            {data.vehicles.map((v) => (
              <div key={v.id} className="bg-white rounded-lg border p-4">
                <p className="text-xs uppercase text-slate-500">Car {v.letter ?? '—'} · {v.state ?? ''}</p>
                <p className="mt-1 inline-block font-mono text-xl font-bold border-2 border-slate-900 rounded px-2 py-0.5 bg-white">
                  {v.plate}
                </p>
                <p className="text-xs text-slate-500 mt-2 font-mono">RFID {v.rfid_epc ?? '—'}</p>
              </div>
            ))}
            <div className="bg-white rounded-lg border p-4 space-y-2">
              <p className="text-xs uppercase text-slate-500">Google sign-in</p>
              {data.user.google_linked ? (
                <>
                  <p className="text-sm text-slate-800">Linked: {data.user.google_email}</p>
                  <button className="text-sm text-red-700 hover:underline"
                          onClick={() => act(unlinkGoogle, 'Google account unlinked')}>
                    Unlink Google
                  </button>
                </>
              ) : googleEnabled ? (
                <GoogleButton purpose="link" label="Link Google account"
                              onError={(m) => push({ type: 'danger', title: 'Google', message: m })} />
              ) : (
                <p className="text-sm text-slate-500">Not configured on this server.</p>
              )}
            </div>
          </section>

          <section className="bg-white rounded-lg border">
            <h2 className="px-4 py-3 border-b font-semibold text-slate-900">Fines</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                  <tr><th className="px-4 py-2">#</th><th className="px-4 py-2">Reason</th><th className="px-4 py-2">Amount</th>
                    <th className="px-4 py-2">When / where</th><th className="px-4 py-2">Status</th><th className="px-4 py-2" /></tr>
                </thead>
                <tbody>
                  {data.fines.length === 0 && (
                    <tr><td colSpan={6} className="px-4 py-6 text-center text-slate-500">No fines</td></tr>
                  )}
                  {data.fines.map((f) => (
                    <tr key={f.id} className="border-t">
                      <td className="px-4 py-2 font-mono">{f.id}</td>
                      <td className="px-4 py-2">{f.reason}</td>
                      <td className="px-4 py-2 font-semibold">{rupees(f.amount)}</td>
                      <td className="px-4 py-2 text-xs text-slate-600">{when(f.timestamp)}<br />{f.location ?? ''}</td>
                      <td className="px-4 py-2"><FineStatusBadge status={f.status} /></td>
                      <td className="px-4 py-2 whitespace-nowrap space-x-2">
                        {f.status !== 'paid' && (
                          <button className="text-xs px-2 py-1 rounded bg-blue-900 text-white"
                                  onClick={() => act(() => payFine(f.id), `Fine #${f.id} paid (simulated UPI)`)}>
                            Pay
                          </button>
                        )}
                        {f.status === 'issued' && (
                          <button className="text-xs px-2 py-1 rounded border border-purple-700 text-purple-800"
                                  onClick={() => {
                                    const reason = window.prompt('Why do you dispute this fine?')
                                    if (reason && reason.trim().length >= 3) {
                                      act(() => disputeFine(f.id, reason.trim()), `Fine #${f.id} disputed`)
                                    }
                                  }}>
                            Dispute
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="bg-white rounded-lg border">
            <div className="px-4 py-3 border-b flex items-center justify-between">
              <h2 className="font-semibold text-slate-900">
                Notifications{' '}
                {data.unread > 0 && <span className="ml-1 px-2 py-0.5 rounded-full bg-red-600 text-white text-xs">{data.unread}</span>}
              </h2>
              {data.unread > 0 && (
                <button className="text-xs text-blue-900 hover:underline"
                        onClick={() => act(markNotificationsRead, 'All notifications read')}>Mark all read</button>
              )}
            </div>
            <ul className="divide-y">
              {data.notifications.length === 0 && <li className="px-4 py-6 text-center text-slate-500 text-sm">Nothing yet</li>}
              {data.notifications.map((n) => (
                <li key={n.id} className={`px-4 py-3 ${n.read ? '' : 'bg-blue-50'}`}>
                  <p className="text-sm font-semibold text-slate-900">{n.title}</p>
                  <p className="text-sm text-slate-700">{n.message}</p>
                  <p className="text-xs text-slate-500 mt-1">{when(n.created_at)}</p>
                </li>
              ))}
            </ul>
          </section>
        </div>

        <PhonePanel sms={data.sms} unread={data.sms_unread}
                    onOpen={() => { if (data.sms_unread) markSmsRead().then(load).catch(() => {}) }} />
      </div>
    </div>
  )
}
