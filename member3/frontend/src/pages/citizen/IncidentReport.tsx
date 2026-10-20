import React, { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Badge, Card, Spinner } from '@components/ui'
import { CitizenIncident, errorMessage, fetchCitizenIncident, formatIst } from '@api/portal'

/**
 * What a citizen may see about a crash their vehicle was involved in:
 * reference, time, place, status and the vehicles involved. Camera frames and
 * RFID data stay with the authority.
 */
export const CitizenIncidentReport: React.FC = () => {
  const { incidentId } = useParams<{ incidentId: string }>()
  const [data, setData] = useState<CitizenIncident | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!incidentId) return
    fetchCitizenIncident(incidentId)
      .then(setData)
      .catch((err) => setError(errorMessage(err, 'This incident report is not available.')))
  }, [incidentId])

  return (
    <div className="max-w-2xl space-y-6">
      <Link to="/citizen/notifications" className="text-xs font-mono text-blue-800 hover:underline">
        ← Notifications
      </Link>
      {error ? (
        <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded">{error}</div>
      ) : !data ? (
        <Spinner />
      ) : (
        <Card
          title={`Crash incident ${data.reference}`}
          actions={
            <Badge variant={data.status === 'Resolved' ? 'success' : 'warning'} size="sm">
              {data.status}
            </Badge>
          }
        >
          <dl className="grid grid-cols-1 sm:grid-cols-3 gap-y-3 text-sm">
            <dt className="text-slate-600">Date &amp; time</dt>
            <dd className="sm:col-span-2 text-slate-900">{formatIst(data.crash_at)}</dd>
            <dt className="text-slate-600">Location</dt>
            <dd className="sm:col-span-2 text-slate-900">{data.location}</dd>
            <dt className="text-slate-600">Your vehicle</dt>
            <dd className="sm:col-span-2 font-mono font-semibold text-slate-900">{data.your_vehicles.join(', ')}</dd>
            <dt className="text-slate-600">Vehicles involved</dt>
            <dd className="sm:col-span-2 font-mono text-slate-900">{data.involved_vehicles.join(', ')}</dd>
            <dt className="text-slate-600">Your vehicle's role</dt>
            <dd className="sm:col-span-2 text-slate-900">
              {data.role_determined ? '—' : 'Involved (the system does not determine which vehicle caused the crash)'}
            </dd>
            {data.resolved_at && (
              <>
                <dt className="text-slate-600">Resolved</dt>
                <dd className="sm:col-span-2 text-slate-900">{formatIst(data.resolved_at)}</dd>
              </>
            )}
          </dl>
          <p className="mt-4 text-xs text-slate-600">
            Quote the reference {data.reference} when contacting the traffic authority about this incident.
          </p>
        </Card>
      )}
    </div>
  )
}
