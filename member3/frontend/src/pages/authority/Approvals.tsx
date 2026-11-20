/**
 * /authority/approvals — Officer Approvals (admins only).
 * Officer sign-ups wait as "pending_approval" and cannot sign in until an admin
 * approves them. Reject blocks the account from ever signing in. Both send the
 * officer an email. The mobile app's "Officer Approvals" tab uses the same API.
 */

import React, { useCallback, useEffect, useState } from 'react'
import { decideOfficer, getPendingOfficers, OfficerAccount, OFFICERS_CHANGED } from '@api/live'
import { extractAuthError } from '@api/auth'
import { useAuthStore } from '@stores/authStore'
import { isAdmin } from '@services/auth/roleGuard'
import { ToastStack, useToasts, when } from '@components/live/LiveWidgets'

const REFRESH_MS = 30_000

export const OfficerApprovals: React.FC = () => {
  const { user } = useAuthStore()
  const [items, setItems] = useState<OfficerAccount[] | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const { toasts, push, dismiss } = useToasts()
  const admin = user ? isAdmin(user.role) : false

  const load = useCallback(() => {
    getPendingOfficers()
      .then((r) => { setItems(r.items); setError('') })
      .catch((e) => setError(extractAuthError(e)))
  }, [])

  useEffect(() => {
    if (!admin) return undefined
    load()
    const timer = window.setInterval(load, REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [admin, load])

  if (!admin) {
    return (
      <div className="max-w-xl p-6 bg-white border rounded-lg">
        <h1 className="text-xl font-semibold text-slate-900">Officer Approvals</h1>
        <p className="mt-2 text-sm text-slate-600">Only a system administrator can approve officer sign-ups.</p>
      </div>
    )
  }

  const decide = async (officer: OfficerAccount, approve: boolean) => {
    if (!approve && !window.confirm(`Reject ${officer.name}? They will not be able to sign in.`)) return
    setBusy(officer.id)
    try {
      await decideOfficer(officer.id, approve)
      push({ type: approve ? 'success' : 'warning', title: `${officer.name} ${approve ? 'approved' : 'rejected'}`,
             message: approve ? 'They can sign in now; an email was sent.' : 'They cannot sign in; an email was sent.' })
      setItems((all) => all?.filter((o) => o.id !== officer.id) ?? all)
      window.dispatchEvent(new Event(OFFICERS_CHANGED))
    } catch (e) {
      push({ type: 'danger', title: 'Action failed', message: extractAuthError(e) })
      load()
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-6">
      <ToastStack toasts={toasts} onClose={dismiss} />
      <header>
        <h1 className="text-2xl font-bold text-slate-900">Officer Approvals</h1>
        <p className="text-sm text-slate-600">
          Traffic-authority sign-ups waiting for an administrator. Approved officers can sign in on the website
          and in the mobile app; rejected ones cannot sign in. Each officer is emailed the decision.
        </p>
      </header>
      {error && <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded">{error}</div>}
      <section className="bg-white rounded-lg border">
        <h2 className="px-4 py-3 border-b font-semibold text-slate-900">
          Waiting for approval{' '}
          {items && items.length > 0 && (
            <span className="ml-1 px-2 py-0.5 rounded-full bg-amber-600 text-white text-xs">{items.length}</span>
          )}
        </h2>
        {!items && !error ? (
          <p className="px-4 py-6 text-sm text-slate-600">Loading…</p>
        ) : items && items.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-slate-500">No officer sign-ups are waiting.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-2">Name</th><th className="px-4 py-2">Email</th>
                  <th className="px-4 py-2">Badge no.</th><th className="px-4 py-2">Jurisdiction</th>
                  <th className="px-4 py-2">Signed up</th><th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {items?.map((o) => (
                  <tr key={o.id} className="border-t">
                    <td className="px-4 py-2 font-semibold text-slate-900">{o.name}</td>
                    <td className="px-4 py-2 break-all">{o.email}</td>
                    <td className="px-4 py-2 font-mono">{o.badge_number ?? '—'}</td>
                    <td className="px-4 py-2">{o.jurisdiction ?? '—'}</td>
                    <td className="px-4 py-2 text-xs text-slate-600 whitespace-nowrap">{when(o.created_at)}</td>
                    <td className="px-4 py-2 whitespace-nowrap space-x-2 text-right">
                      <button type="button" disabled={busy !== null} onClick={() => decide(o, true)}
                              className="px-3 py-1 rounded bg-green-700 text-white text-xs font-semibold disabled:opacity-60">
                        {busy === o.id ? '…' : 'Approve'}
                      </button>
                      <button type="button" disabled={busy !== null} onClick={() => decide(o, false)}
                              className="px-3 py-1 rounded border border-red-600 text-red-700 text-xs font-semibold disabled:opacity-60">
                        Reject
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
