/**
 * Owners' "are you safe?" answers on the authority pages, and the crash case
 * outcome that follows from them:
 *   resolved      every involved owner answered minor / false alarm (or the
 *                 authority accepted an answer)
 *   not resolved  an owner reported an accident, or the other owner did not
 *                 answer within 30 s
 *   waiting       the other owner still has time to answer
 * Pending minor / false-alarm answers can be accepted here ("Resolve as false
 * alarm") or rejected (keep the case open).
 */

import React, { useState } from 'react'
import { CaseView, CrashResponseView, decideCrashAnswer } from '@api/live'
import { extractAuthError } from '@api/auth'

const OUTCOME_STYLE: Record<CaseView['outcome'], string> = {
  resolved: 'bg-emerald-100 text-emerald-900 border-emerald-300',
  not_resolved: 'bg-red-100 text-red-900 border-red-300',
  waiting: 'bg-amber-100 text-amber-900 border-amber-300',
}

export function caseLabel(c: CaseView): string {
  if (c.outcome === 'resolved') return c.automatic ? 'Auto-resolved by owners' : 'Resolved by authority'
  if (c.outcome === 'not_resolved') {
    return c.reason_code === 'no_answer' ? 'Not resolved: no answer in 30 s'
      : c.reason_code === 'accident' ? 'Not resolved: accident reported' : 'Not resolved'
  }
  return 'Waiting for other owner'
}

export const CaseBadge: React.FC<{ value?: CaseView | null }> = ({ value }) =>
  value ? (
    <>
      <span title={value.reason ?? undefined}
            className={`inline-flex px-2 py-0.5 rounded border text-xs font-semibold ${OUTCOME_STYLE[value.outcome]}`}>
        {caseLabel(value)}
      </span>
      {value.severe && (
        <span className="inline-flex ml-1 px-2 py-0.5 rounded bg-red-700 text-white text-xs font-bold">SEVERE</span>
      )}
    </>
  ) : null

const ANSWER_TEXT: Record<string, string> = {
  accident: 'Accident', not_serious: 'Minor, not serious', false_alarm: 'False alarm / no authority needed',
  no_answer: 'No answer within 30 s (severe)',
}

export const OwnerAnswers: React.FC<{
  answers?: CrashResponseView[]
  value?: CaseView | null
  onChanged?: () => void
}> = ({ answers, value, onChanged }) => {
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState('')
  if (!answers?.length && !value) return null

  const decide = async (answer: CrashResponseView, accept: boolean) => {
    setBusy(answer.id)
    setError('')
    try {
      await decideCrashAnswer(answer.id, accept)
      onChanged?.()
    } catch (e) {
      setError(extractAuthError(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="mt-2 p-3 rounded-md border border-slate-200 bg-slate-50 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-600">Owner answers</span>
        <CaseBadge value={value} />
        {value?.reason && <span className="text-xs text-slate-700">{value.reason}</span>}
      </div>
      <ul className="space-y-1.5">
        {(answers ?? []).map((a) => (
          <li key={a.id} className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-mono font-semibold">{a.plate ?? '—'}</span>
            <span className="text-slate-700">{a.owner_name}</span>
            <span className={a.response === 'accident' || a.response === 'no_answer'
              ? 'text-red-700 font-semibold' : 'text-slate-900'}>
              {ANSWER_TEXT[a.response] ?? a.label}
            </span>
            <span className="text-xs text-slate-500">
              {a.channel === 'system' ? 'recorded by the server' : `via ${a.channel === 'app' ? 'app' : 'website'}`}
            </span>
            {a.review_status === 'pending' && (
              <span className="ml-auto flex gap-2">
                <button type="button" disabled={busy !== null} onClick={() => decide(a, true)}
                        className="px-2.5 py-1 rounded bg-emerald-700 text-white text-xs font-semibold disabled:opacity-60">
                  {a.response === 'false_alarm' ? 'Resolve as false alarm' : 'Resolve as minor crash'}
                </button>
                <button type="button" disabled={busy !== null} onClick={() => decide(a, false)}
                        className="px-2.5 py-1 rounded border border-slate-400 text-xs disabled:opacity-60">
                  Keep open
                </button>
              </span>
            )}
          </li>
        ))}
        {value?.vehicles.filter((v) => !v.answer).map((v) => (
          <li key={v.plate} className="text-sm text-slate-500">
            <span className="font-mono">{v.plate}</span> · no answer yet
          </li>
        ))}
      </ul>
      {error && <p className="text-xs text-red-700">{error}</p>}
    </div>
  )
}
