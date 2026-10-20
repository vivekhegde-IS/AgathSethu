/**
 * "Mark as resolved" with verification: the officer re-enters their own
 * password, which the backend checks against the stored hash. Who resolved
 * it, when and the optional note are recorded on the incident.
 */

import React, { useEffect, useState } from 'react'
import { Button, Input, Modal } from '@components/ui'
import { BoardIncident, errorMessage, resolveIncident } from '@api/portal'
import { useAuthStore } from '@stores/authStore'

export interface ResolveIncidentModalProps {
  incident: { id: string; reference: string; location: string } | null
  onClose: () => void
  onResolved: (incident: BoardIncident) => void
}

export const ResolveIncidentModal: React.FC<ResolveIncidentModalProps> = ({ incident, onClose, onResolved }) => {
  const { user } = useAuthStore()
  const [password, setPassword] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setPassword('')
    setNote('')
    setError('')
  }, [incident?.id])

  if (!incident) return null

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      onResolved(await resolveIncident(incident.id, password, note.trim()))
      onClose()
    } catch (err) {
      setError(errorMessage(err, 'Could not resolve the incident.'))
    } finally {
      setBusy(false)
    }
  }

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
        <Input
          label="Re-enter your password to confirm"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoFocus
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
          <Button type="submit" variant="success" size="sm" isLoading={busy} disabled={!password}>
            Mark as resolved
          </Button>
        </div>
      </form>
    </Modal>
  )
}
