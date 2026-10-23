/**
 * Multi-Junction Tracking — /authority/evidence/:evidenceId/tracking
 *
 * Opened only from the incident evidence page (not in the sidebar). For one
 * crash: where each involved vehicle was read, in what order, and where it
 * was read last. Refreshes live on incident_created / watchlist_rfid_hit /
 * vision_match_result, and polls while the crash is unresolved in case a
 * push is missed.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Badge, Spinner } from '@components/ui'
import { JunctionTrackingMap, VehicleTimeline, trackedVehicles } from '@components/authority/JunctionTracking'
import { CrashTypeBadge } from '@components/authority/CrashTypeBadge'
import { subscribeToLiveCameraMessages } from '@services/websocket/liveCamerasSocket'
import { errorMessage, formatIst } from '@api/portal'
import { INCIDENT_EVIDENCE_EVENTS, IncidentDetail, getIncident } from '@api/incidentEvidence'

const POLL_MS = 5000

export const TrackingDashboard: React.FC = () => {
  const { evidenceId } = useParams<{ evidenceId: string }>()
  const [detail, setDetail] = useState<IncidentDetail | null>(null)
  const [error, setError] = useState('')
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)

  const refresh = useCallback(async () => {
    if (!evidenceId) return
    try {
      setDetail(await getIncident(evidenceId))
      setUpdatedAt(new Date())
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load this incident.'))
    }
  }, [evidenceId])

  useEffect(() => {
    setDetail(null)
    refresh()
  }, [refresh])

  useEffect(() => {
    return subscribeToLiveCameraMessages((message) => {
      const type = (message as Record<string, unknown>).type as string | undefined
      if (type && (INCIDENT_EVIDENCE_EVENTS as readonly string[]).includes(type)) refresh()
    })
  }, [refresh])

  const incident = detail?.incident as (IncidentDetail['incident'] & Record<string, unknown>) | undefined
  const resolved = Boolean(incident?.resolved)

  const loaded = Boolean(incident)
  useEffect(() => {
    if (!loaded || resolved) return
    const timer = window.setInterval(refresh, POLL_MS)
    return () => window.clearInterval(timer)
  }, [loaded, resolved, refresh])

  const vehicles = useMemo(() => (detail ? trackedVehicles(detail) : []), [detail])
  const reference = (incident?.reference as string | undefined) ?? 'Incident'

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/authority/evidence/${evidenceId}`} className="text-xs font-mono text-blue-800 hover:underline">
          ← Incident evidence
        </Link>
        <div className="flex flex-wrap items-center gap-2 mt-2">
          <h2 className="text-2xl font-semibold text-blue-950">Multi-Junction Tracking · {reference}</h2>
          {incident &&
            (resolved ? (
              <Badge variant="success" size="sm">Resolved</Badge>
            ) : (
              <Badge variant="danger" size="sm" dot>LIVE</Badge>
            ))}
          {incident && <CrashTypeBadge kind={incident} />}
        </div>
        {incident && (
          <p className="text-sm text-slate-600 mt-1">
            Crash at {String(incident.location ?? incident.crash_junction ?? '—')} · {formatIst(incident.created_at)}
            {updatedAt && ` · updated ${updatedAt.toLocaleTimeString()}`}
          </p>
        )}
      </div>

      {error && <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded">{error}</div>}

      {!detail ? (
        !error && <Spinner />
      ) : (
        <>
          <JunctionTrackingMap detail={detail} vehicles={vehicles} />
          {vehicles.length === 0 ? (
            <p className="text-sm text-slate-600">No involved vehicle was identified for this crash.</p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {vehicles.map((vehicle) => (
                <VehicleTimeline key={vehicle.key} vehicle={vehicle} positions={detail.junction_positions ?? {}} incidentId={String(detail.incident.id)} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
