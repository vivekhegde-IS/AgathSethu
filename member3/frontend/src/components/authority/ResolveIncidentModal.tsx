/**
 * "Mark as resolved" with verification:
 *  - the officer re-enters their own password (checked against the stored hash), and
 *  - enters the resolution code of every owner alerted about the crash (the
 *    owner reads it out from their SMS / app / owner portal), or
 *  - when an owner cannot be reached, asks the super admin for a code and
 *    enters that one instead.
 * Who resolved it, when, how and the optional note are recorded on the incident.
 */

import React, { useCallback, useEffect, useState } from 'react'
import { Button, Input, Modal } from '@components/ui'
import {
  BoardIncident, errorMessage, formatIst, getResolutionStatus, requestResolutionCode, resolveIncident,
  ResolutionStatus,
} from '@api/portal'
import { useAuthStore } from '@stores/authStore'
import { useLiveEvents } from '@hooks/useLiveEvents'

export interface ResolveIncidentModalProps {
  incident: { id: string; reference: string; location: string } | null
  onClose: () => void
  onResolved: (incident: BoardIncident) => void
}

const digits = (v: string) => v.replace(/\D/g, '').slice(0, 6)

const codeInput =
  'w-full rounded-md border border-slate-300 bg-white px-3 py-2 font-mono text-lg tracking-[0.3em] text-slate-900 ' +
  'focus:border-cyan-500 focus:outline-none'

export const ResolveIncidentModal: React.FC<ResolveIncidentModalProps> = ({ incident, onClose, onResolved }) => {
  const { user } = useAuthStore()
  const [password, setPassword] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<ResolutionStatus | null>(null)
  const [mode, setMode] = useState<'owner' | 'admin'>('owner')
  const [ownerCodes, setOwnerCodes] = useState<string[]>([])
  const [adminCode, setAdminCode] = useState('')
  const [reason, setReason] = useState('')
  const [asking, setAsking] = useState(false)

  const load = useCallback(() => {
    if (!incident) return
    getResolutionStatus(incident.id)
      .then((s) => {
        setStatus(s)
        setOwnerCodes((prev) => s.owners.map((_, i) => prev[i] ?? ''))
        if (!s.owner_codes_possible) setMode('admin')
      })
      .catch((e) => setError(errorMessage(e, 'Could not load what this crash needs.')))
  }, [incident])

  useEffect(() => {
    setPassword('')
    setNote('')
    setError('')
    setStatus(null)
    setMode('owner')
    setOwnerCodes([])
    setAdminCode('')
    setReason('')
    load()
  }, [incident?.id, load])

  // the super admin issued / declined our request: show it at once
  useLiveEvents(
    (event) => {
      if (event.type.startsWith('resolution.')) load()
    },
    load,
  )

  if (!incident) return null

  const codes = mode === 'owner' ? ownerCodes : [adminCode]
  const ready = !!password && codes.length > 0 && codes.every((c) => c.length === 6)
  const request = status?.request

  const ask = async () => {
    setAsking(true)
    setError('')
    try {
      await requestResolutionCode(incident.id, reason.trim())
      load()
    } catch (err) {
      setError(errorMessage(err, 'Could not send the request.'))
    } finally {
      setAsking(false)
    }
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      onResolved(await resolveIncident(incident.id, password, note.trim(), codes))
      onClose()
    } catch (err) {
      setError(errorMessage(err, 'Could not resolve the incident.'))
      load()
    } finally {
      setBusy(false)
    }
  }

  const tab = (value: 'owner' | 'admin', label: string, disabled = false) => (
    <button
      type="button"
      disabled={disabled}
      onClick={() => { setMode(value); setError('') }}
      className={`flex-1 px-3 py-1.5 text-xs font-semibold rounded ${
        mode === value ? 'bg-slate-900 text-white' : 'text-slate-700 hover:bg-slate-100'
      } disabled:opacity-40`}
    >
      {label}
    </button>
  )

  return (
    <Modal isOpen onClose={busy ? () => {} : onClose} title={`Mark ${incident.reference} as resolved`} maxWidth="md">
      <form onSubmit={submit} className="space-y-4">
        <p className="text-xs text-slate-700">
          {incident.location}. The incident will be recorded as resolved by{' '}
          <span className="font-semibold text-slate-900">{user?.name ?? 'you'}</span> at the current time.
        </p>
        {error && (
          <div role="alert" className="p-2 rounded border border-red-200 bg-red-50 text-xs text-red-700">
            {error}
          </div>
        )}
        {status?.locked_until && (
          <div role="alert" className="p-2 rounded border border-amber-300 bg-amber-50 text-xs text-amber-800">
            Too many wrong codes. Locked until {formatIst(status.locked_until)}, or ask the super admin for a new code.
          </div>
        )}

        <div className="flex gap-1 p-1 rounded-md bg-slate-100" role="tablist">
          {tab('owner', "Owners' codes", status !== null && !status.owner_codes_possible)}
          {tab('admin', 'Super-admin code')}
        </div>

        {!status ? (
          <p className="text-xs text-slate-600">Loading…</p>
        ) : mode === 'owner' ? (
          <div className="space-y-3">
            <p className="text-xs text-slate-600">
              Ask each owner for the 6-digit resolution code they received with the crash alert.
              {status.owners.length > 1 && ' Every owner’s code is needed.'}
            </p>
            {status.owners.map((o, i) => (
              <div key={i}>
                <label htmlFor={`owner-code-${i}`} className="block text-xs font-mono text-slate-700 mb-1">
                  {o.name ?? 'Owner'} — {o.plates.join(', ')}
                </label>
                <input
                  id={`owner-code-${i}`}
                  inputMode="numeric"
                  autoComplete="off"
                  value={ownerCodes[i] ?? ''}
                  onChange={(e) => setOwnerCodes((all) => all.map((c, j) => (j === i ? digits(e.target.value) : c)))}
                  placeholder="••••••"
                  className={codeInput}
                />
              </div>
            ))}
            <button type="button" className="text-xs font-semibold text-cyan-700 hover:underline"
                    onClick={() => setMode('admin')}>
              An owner can’t give their code? Ask the super admin →
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {!status.owner_codes_possible && (
              <p className="text-xs text-slate-600">
                {status.owners.length === 0
                  ? 'No owner was alerted about this crash, so it needs a code from the super admin.'
                  : 'An owner’s code has expired, so this crash needs a code from the super admin.'}
              </p>
            )}
            {request?.status === 'requested' ? (
              <div className="p-2 rounded border border-cyan-200 bg-cyan-50 text-xs text-cyan-900">
                Request sent {formatIst(request.requested_at)}. Waiting for the super admin. When they generate the
                code, they will give it to you; this updates by itself.
              </div>
            ) : request?.status === 'issued' ? (
              <div className="p-2 rounded border border-green-200 bg-green-50 text-xs text-green-900">
                {request.issued_by_name ?? 'The super admin'} generated a code (valid until{' '}
                {formatIst(request.expires_at)}). Get it from them and enter it below.
              </div>
            ) : (
              <div className="space-y-2">
                {request?.status === 'declined' && (
                  <p className="text-xs text-red-700">The super admin declined the last request.</p>
                )}
                <label htmlFor="code-reason" className="block text-xs font-mono text-slate-700">
                  Why can’t the owner give their code?
                </label>
                <input
                  id="code-reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  maxLength={1000}
                  placeholder="e.g. owner taken to hospital, phone damaged"
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-cyan-500 focus:outline-none"
                />
                <Button type="button" variant="secondary" size="sm" isLoading={asking} onClick={ask}>
                  Ask the super admin for a code
                </Button>
              </div>
            )}
            <div>
              <label htmlFor="admin-code" className="block text-xs font-mono text-slate-700 mb-1">
                Super-admin code
              </label>
              <input
                id="admin-code"
                inputMode="numeric"
                autoComplete="off"
                value={adminCode}
                onChange={(e) => setAdminCode(digits(e.target.value))}
                placeholder="••••••"
                className={codeInput}
              />
            </div>
          </div>
        )}

        <Input
          label="Re-enter your password to confirm"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <div>
          <label htmlFor="resolve-note" className="block text-xs font-mono text-slate-700 mb-1">
            Note (optional)
          </label>
          <textarea
            id="resolve-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={2000}
            rows={3}
            className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-cyan-500 focus:outline-none"
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" variant="success" size="sm" isLoading={busy} disabled={!ready || !!status?.locked_until}>
            Mark as resolved
          </Button>
        </div>
      </form>
    </Modal>
  )
}
