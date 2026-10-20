import React, { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Button, Card, Spinner } from '@components/ui'
import { ResolveIncidentModal } from '@components/authority/ResolveIncidentModal'
import { BoardIncident, RadarBoard, errorMessage, fetchRadar, formatIst } from '@api/portal'

// New crashes are created by the backend as they happen; the list refreshes on this interval.
const REFRESH_MS = 15000

/**
 * Crash Incident Radar: today's active (unresolved) crashes only, newest
 * first. A crash leaves the radar when it is resolved or when the day ends
 * (00:00 IST, applied by the backend); every crash, with its Resolved /
 * Unresolved status, stays in Evidence Records.
 */
export const IncidentDashboard: React.FC = () => {
  const [board, setBoard] = useState<RadarBoard | null>(null)
  const [error, setError] = useState('')
  const [resolving, setResolving] = useState<BoardIncident | null>(null)

  const load = useCallback(async () => {
    try {
      setBoard(await fetchRadar())
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load incidents.'))
    }
  }, [])

  useEffect(() => {
    load()
    const timer = window.setInterval(load, REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [load])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold text-blue-950">Crash Incident Radar</h2>
          <p className="text-sm text-slate-600">
            Today's active crashes. Resolved crashes and crashes from earlier days are in{' '}
            <Link to="/authority/evidence" className="text-blue-900 underline">
              Evidence Records
            </Link>
            .
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={load}>
          Refresh
        </Button>
      </div>

      {error && <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded">{error}</div>}

      {!board && !error ? (
        <Spinner />
      ) : board ? (
        <Card title={`Active incidents today (${board.active.length})`}>
          {board.active.length === 0 ? (
            <p className="text-sm text-slate-600 py-6 text-center">No active crashes today.</p>
          ) : (
            <ul className="divide-y divide-slate-200">
              {board.active.map((incident) => (
                <IncidentRow key={incident.id} incident={incident} onResolve={() => setResolving(incident)} />
              ))}
            </ul>
          )}
        </Card>
      ) : null}

      <ResolveIncidentModal incident={resolving} onClose={() => setResolving(null)} onResolved={load} />
    </div>
  )
}

const IncidentRow: React.FC<{ incident: BoardIncident; onResolve?: () => void }> = ({ incident, onResolve }) => {
  const plates = incident.involved_plates_display.filter(Boolean) as string[]
  return (
    <li className="py-3 flex flex-col lg:flex-row lg:items-center gap-3 lg:justify-between">
      <div className="min-w-0 space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-mono font-semibold text-sm text-red-700">{incident.reference}</span>
          <Badge variant={incident.resolved ? 'success' : 'danger'} size="sm">
            {incident.resolved ? 'Resolved' : 'Unresolved'}
          </Badge>
          <span className="text-xs text-slate-700">{incident.location}</span>
        </div>
        <p className="text-sm text-slate-600">
          Detected {formatIst(incident.created_at)}
          {plates.length > 0 ? ` · Vehicles: ${plates.join(', ')}` : ' · Vehicles not yet identified'}
        </p>
        {incident.resolved && (
          <p className="text-xs text-emerald-700 font-mono">
            Resolved {formatIst(incident.resolved_at)} by {incident.resolved_by_name ?? 'unknown officer'}
            {incident.resolution_note ? ` — “${incident.resolution_note}”` : ''}
          </p>
        )}
      </div>
      <div className="flex flex-wrap gap-2 lg:justify-end flex-shrink-0">
        <Link to={`/authority/evidence/${incident.id}`}>
          <Button variant="secondary" size="sm">
            Incident evidence
          </Button>
        </Link>
        {incident.live_feed && incident.crash_junction && (
          <Link to={`/authority/live?junction=${encodeURIComponent(incident.crash_junction)}`}>
            <Button variant="outline" size="sm">
              View live feed
            </Button>
          </Link>
        )}
        {onResolve && (
          <Button variant="success" size="sm" onClick={onResolve}>
            Mark as resolved
          </Button>
        )}
      </div>
    </li>
  )
}
