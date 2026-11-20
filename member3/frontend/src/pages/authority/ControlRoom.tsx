/**
 * /authority — Control room: issue fines, watch fines / crashes live, owners'
 * "are you safe?" answers (mobile app + website), and the Review queue. Partner namings and hit-and-runs from the crash pipeline wait
 * here; nothing reaches the accused owner (or becomes a fine) until Confirm.
 */

import React, { useCallback, useState } from 'react'
import {
  AuthorityLive, CrashResponseView, decideCrashAnswer, decideReview, getAuthorityLive, issueFine, LiveEvent,
  ReviewView, upholdFine,
} from '@api/live'
import { extractAuthError } from '@api/auth'
import { useLiveEvents } from '@hooks/useLiveEvents'
import { FineStatusBadge, LivePill, rupees, ToastStack, useToasts, when } from '@components/live/LiveWidgets'

const REASONS = ['Red-light violation', 'Over-speeding', 'No seat belt', 'Wrong-way driving', 'Using phone while driving']

const ReviewCard: React.FC<{ item: ReviewView; onDecide: (confirm: boolean, note: string) => void }> = ({ item, onDecide }) => {
  const [note, setNote] = useState('')
  const pending = item.status === 'pending'
  const ev = item.evidence as Record<string, string | number | null>
  return (
    <li className={`p-4 ${pending ? 'bg-amber-50' : ''}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={`px-2 py-0.5 rounded text-xs font-bold uppercase ${
          item.kind === 'hit_and_run' ? 'bg-red-700 text-white' : 'bg-orange-200 text-orange-900'}`}>
          {item.kind === 'hit_and_run' ? 'Hit-and-run' : 'Partner named'}
        </span>
        <span className="font-mono text-xs text-slate-600">{item.incident_key}</span>
        <span className={`ml-auto text-xs font-semibold uppercase ${
          pending ? 'text-amber-800' : item.status === 'confirmed' ? 'text-green-800' : 'text-slate-500'}`}>
          {item.status}
        </span>
      </div>
      <p className="mt-2 text-sm text-slate-900">
        <strong>{item.accused?.plate}</strong> (car {item.accused?.letter}, {item.accused?.owner_name})
        {item.kind === 'hit_and_run' ? ' left the scene' : ' named as collision partner'}
        {item.struck && <> of <strong>{item.struck.plate}</strong> (car {item.struck.letter}, {item.struck.owner_name})</>}
      </p>
      <p className="text-xs text-slate-600 mt-1">
        Decision route: {item.decision_route_label ?? 'Single-vehicle'}
        {ev.pair_distance_m != null && <> · distance {Number(ev.pair_distance_m).toFixed(1)} m</>}
        {ev.relative_speed_kmh != null && <> · rel. speed {Number(ev.relative_speed_kmh).toFixed(1)} km/h</>}
        {ev.speed_kmh != null && <> · leaving at {Number(ev.speed_kmh).toFixed(1)} km/h, {Number(ev.distance_from_crash_m ?? 0).toFixed(1)} m away</>}
        {' · '}{when(item.created_at)}
      </p>
      {pending ? (
        <div className="mt-3 flex flex-wrap gap-2 items-center">
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)"
                 className="flex-1 min-w-[160px] border rounded px-2 py-1 text-sm" />
          <button onClick={() => onDecide(true, note)} className="px-3 py-1 rounded bg-green-700 text-white text-sm">Confirm</button>
          <button onClick={() => onDecide(false, note)} className="px-3 py-1 rounded border border-slate-400 text-sm">Reject</button>
        </div>
      ) : item.decision_note && <p className="text-xs text-slate-600 mt-1">Note: {item.decision_note}</p>}
    </li>
  )
}

const ANSWER_STYLE: Record<string, string> = {
  accident: 'bg-red-700 text-white',
  not_serious: 'bg-amber-200 text-amber-950',
  false_alarm: 'bg-slate-200 text-slate-900',
}

const AnswerBadge: React.FC<{ answer: CrashResponseView }> = ({ answer }) => (
  <span className={`px-2 py-0.5 rounded text-xs font-bold ${ANSWER_STYLE[answer.response] ?? ''}`}>
    {answer.response === 'accident' ? 'Owner: accident' : answer.response === 'not_serious' ? 'Owner: minor' : 'Owner: false alarm'}
    {answer.review_status && answer.review_status !== 'pending' && ` · ${answer.review_status}`}
  </span>
)

const AnswerCard: React.FC<{ item: CrashResponseView; onDecide: (accept: boolean, note: string) => void }> = ({ item, onDecide }) => {
  const [note, setNote] = useState('')
  const pending = item.review_status === 'pending'
  return (
    <li className={`p-4 ${pending ? 'bg-amber-50' : item.response === 'accident' ? 'bg-red-50' : ''}`}>
      <div className="flex flex-wrap items-center gap-2">
        <AnswerBadge answer={item} />
        <span className="font-mono text-xs text-slate-600">{item.incident_ref}</span>
        <span className="ml-auto text-xs text-slate-600">via {item.channel === 'app' ? 'mobile app' : 'website'} · {when(item.responded_at)}</span>
      </div>
      <p className="mt-2 text-sm text-slate-900">
        <strong>{item.plate ?? '—'}</strong>{item.letter && <> (car {item.letter})</>} · {item.owner_name}
        {item.owner_phone && <> · <a className="text-blue-800 underline" href={`tel:${item.owner_phone}`}>{item.owner_phone}</a></>}
      </p>
      {item.note && <p className="text-xs text-slate-700 mt-1">Owner's note: {item.note}</p>}
      {pending ? (
        <div className="mt-3 flex flex-wrap gap-2 items-center">
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note to the owner (optional)"
                 className="flex-1 min-w-[160px] border rounded px-2 py-1 text-sm" />
          <button onClick={() => onDecide(true, note)} className="px-3 py-1 rounded bg-green-700 text-white text-sm">
            Accept: {item.response === 'false_alarm' ? 'false alarm' : 'minor'}
          </button>
          <button onClick={() => onDecide(false, note)} className="px-3 py-1 rounded border border-slate-400 text-sm">
            Reject: keep as crash
          </button>
        </div>
      ) : item.review_note && <p className="text-xs text-slate-600 mt-1">Note: {item.review_note}</p>}
    </li>
  )
}

export const ControlRoom: React.FC = () => {
  const [data, setData] = useState<AuthorityLive | null>(null)
  const [error, setError] = useState('')
  const [form, setForm] = useState({ vehicle: 'C', amount: '1500', reason: REASONS[0], location: 'Junction 1, Town10HD' })
  const [busy, setBusy] = useState(false)
  const { toasts, push, dismiss } = useToasts()

  const load = useCallback(() => {
    getAuthorityLive().then((d) => { setData(d); setError('') }).catch((e) => setError(extractAuthError(e)))
  }, [])

  const onEvent = useCallback((event: LiveEvent) => {
    const { fine, report, review, response } = event.data
    if (event.type === 'fine.updated' && fine) {
      push({ type: fine.status === 'paid' ? 'success' : 'warning', title: `Fine #${fine.id} ${fine.status}`,
             message: `${fine.plate} · ${fine.owner_name ?? ''}` })
    } else if (event.type === 'crash.detected' && report) {
      push({ type: 'danger', title: 'Crash detected', message: `${report.vehicle?.plate} · ${report.location ?? ''}` })
    } else if (event.type === 'crash.partner_named' && review) {
      push({ type: 'warning', title: 'Partner named: review needed', message: `${review.accused?.plate} ↔ ${review.struck?.plate}` })
    } else if (event.type === 'crash.response' && response) {
      push({ type: response.response === 'accident' ? 'danger' : 'warning',
             title: response.response === 'accident' ? 'Owner confirms accident' : 'Owner answered: check needed',
             message: `${response.plate ?? ''} · ${response.owner_name ?? ''} · ${response.label}` })
    } else if (event.type === 'hit_and_run.detected' && review) {
      push({ type: 'danger', title: 'Hit-and-run: review needed', message: `${review.accused?.plate} left the scene` })
    }
    load()
  }, [load, push])

  const status = useLiveEvents(onEvent, load)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try {
      const fine = await issueFine({ vehicle: form.vehicle, amount: Number(form.amount), reason: form.reason,
                                     location: form.location || undefined })
      push({ type: 'success', title: `Fine #${fine.id} issued`, message: `${fine.plate} · ${rupees(fine.amount)}` })
      load()
    } catch (err) {
      push({ type: 'danger', title: 'Could not issue fine', message: extractAuthError(err) })
    } finally {
      setBusy(false)
    }
  }

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn()
      push({ type: 'success', title: ok })
      load()
    } catch (err) {
      push({ type: 'danger', title: 'Action failed', message: extractAuthError(err) })
    }
  }

  if (error) return <div className="p-6 text-red-700">{error}</div>
  if (!data) return <div className="p-6 text-slate-600">Loading…</div>

  return (
    <div className="space-y-6">
      <ToastStack toasts={toasts} onClose={dismiss} />
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Control room</h1>
          <p className="text-sm text-slate-600">Fines, crash alerts and the review queue, live.</p>
        </div>
        <LivePill status={status} />
      </header>

      <section className="bg-white rounded-lg border">
        <h2 className="px-4 py-3 border-b font-semibold text-slate-900">
          Owner answers{' '}
          {data.pending_responses > 0 && <span className="ml-1 px-2 py-0.5 rounded-full bg-amber-600 text-white text-xs">{data.pending_responses}</span>}
        </h2>
        <p className="px-4 pt-2 text-xs text-slate-600">
          What owners answered to "Are you safe?" in the mobile app or on the website. A false alarm or minor
          crash only closes the incident once you accept it.
        </p>
        <ul className="divide-y mt-2 max-h-96 overflow-y-auto">
          {data.responses.length === 0 && <li className="px-4 py-6 text-center text-slate-500 text-sm">No answers yet</li>}
          {data.responses.map((item) => (
            <AnswerCard key={item.id} item={item}
                        onDecide={(accept, note) => act(() => decideCrashAnswer(item.id, accept, note),
                          `${item.plate ?? item.incident_ref}: answer ${accept ? 'accepted' : 'rejected'}`)} />
          ))}
        </ul>
      </section>

      <div className="grid gap-6 xl:grid-cols-2">
        <section className="bg-white rounded-lg border">
          <h2 className="px-4 py-3 border-b font-semibold text-slate-900">
            Review queue{' '}
            {data.pending_reviews > 0 && <span className="ml-1 px-2 py-0.5 rounded-full bg-amber-600 text-white text-xs">{data.pending_reviews}</span>}
          </h2>
          <p className="px-4 pt-2 text-xs text-slate-600">
            Partner namings and hit-and-runs are not shown to the accused owner and are never fined automatically.
            The struck car's owner only sees "under review" until you decide.
          </p>
          <ul className="divide-y mt-2">
            {data.reviews.length === 0 && <li className="px-4 py-6 text-center text-slate-500 text-sm">Nothing to review</li>}
            {data.reviews.map((item) => (
              <ReviewCard key={item.id} item={item}
                          onDecide={(confirm, note) => act(() => decideReview(item.id, confirm, note),
                            `Review ${item.incident_key} ${confirm ? 'confirmed' : 'rejected'}`)} />
            ))}
          </ul>
        </section>

        <section className="bg-white rounded-lg border">
          <h2 className="px-4 py-3 border-b font-semibold text-slate-900">Issue a fine</h2>
          <form onSubmit={submit} className="p-4 grid sm:grid-cols-2 gap-3 text-sm">
            <label className="flex flex-col gap-1">Vehicle
              <select value={form.vehicle} onChange={(e) => setForm({ ...form, vehicle: e.target.value })}
                      className="border rounded px-2 py-1.5">
                {data.fleet.map((v) => (
                  <option key={v.id} value={v.letter ?? v.plate}>{v.letter} · {v.plate} · {v.owner_name}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1">Amount (₹)
              <input type="number" min={1} max={100000} required value={form.amount}
                     onChange={(e) => setForm({ ...form, amount: e.target.value })} className="border rounded px-2 py-1.5" />
            </label>
            <label className="flex flex-col gap-1">Reason
              <input list="fine-reasons" required minLength={3} value={form.reason}
                     onChange={(e) => setForm({ ...form, reason: e.target.value })} className="border rounded px-2 py-1.5" />
              <datalist id="fine-reasons">{REASONS.map((r) => <option key={r} value={r} />)}</datalist>
            </label>
            <label className="flex flex-col gap-1">Location
              <input value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })}
                     className="border rounded px-2 py-1.5" />
            </label>
            <button disabled={busy} className="sm:col-span-2 py-2 rounded bg-blue-900 text-white font-semibold disabled:opacity-60">
              {busy ? 'Issuing…' : 'Issue fine'}
            </button>
          </form>

          <h2 className="px-4 py-3 border-y font-semibold text-slate-900">Crash alerts</h2>
          <ul className="divide-y max-h-80 overflow-y-auto">
            {data.crashes.length === 0 && <li className="px-4 py-6 text-center text-slate-500 text-sm">No crashes</li>}
            {data.crashes.map((c) => (
              <li key={c.id} className="px-4 py-2 text-sm">
                <span className="font-semibold">{c.vehicle?.plate}</span> (car {c.vehicle?.letter}, {c.vehicle?.owner_name})
                {c.source === 'partner' && <span className="ml-1 text-xs text-orange-800">[named as partner]</span>}
                {c.partner && <> · with {c.partner.plate}</>}
                {c.owner_response && <span className="ml-2"><AnswerBadge answer={c.owner_response} /></span>}
                <p className="text-xs text-slate-600">
                  {c.incident_key} · {c.status} · {c.decision_route_label ?? 'single vehicle'} · {c.location} · {when(c.created_at)}
                </p>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="bg-white rounded-lg border">
        <h2 className="px-4 py-3 border-b font-semibold text-slate-900">Fines (live)</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr><th className="px-4 py-2">#</th><th className="px-4 py-2">Vehicle</th><th className="px-4 py-2">Owner</th>
                <th className="px-4 py-2">Reason</th><th className="px-4 py-2">Amount</th><th className="px-4 py-2">Issued</th>
                <th className="px-4 py-2">Status</th><th className="px-4 py-2" /></tr>
            </thead>
            <tbody>
              {data.fines.map((f) => (
                <tr key={f.id} className="border-t">
                  <td className="px-4 py-2 font-mono">{f.id}</td>
                  <td className="px-4 py-2 font-mono">{f.plate}</td>
                  <td className="px-4 py-2">{f.owner_name}</td>
                  <td className="px-4 py-2">{f.reason}{f.dispute_reason && <p className="text-xs text-purple-800">Dispute: {f.dispute_reason}</p>}</td>
                  <td className="px-4 py-2">{rupees(f.amount)}</td>
                  <td className="px-4 py-2 text-xs text-slate-600">{when(f.timestamp)}</td>
                  <td className="px-4 py-2"><FineStatusBadge status={f.status} /></td>
                  <td className="px-4 py-2">
                    {f.status === 'disputed' && (
                      <button className="text-xs px-2 py-1 rounded border border-slate-400"
                              onClick={() => act(() => upholdFine(f.id), `Fine #${f.id} upheld`)}>Uphold</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
