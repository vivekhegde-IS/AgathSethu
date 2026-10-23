/**
 * Junction sighting — /authority/evidence/:evidenceId/tracking/:junctionId
 *
 * Opened by clicking a junction on the Multi-Junction Tracking map. For the
 * fled vehicle at that junction: the ANPR screenshot recorded there, the
 * vehicle cut out of the frame, the plate read, the RFID reads (real IST time)
 * and the registered owner's name and phone number. Refreshes live like the
 * tracking page.
 */

import React, { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AuthImage, Badge, Card, Spinner } from '@components/ui'
import { subscribeToLiveCameraMessages } from '@services/websocket/liveCamerasSocket'
import { errorMessage, formatIst, formatIstDate, formatIstTime } from '@api/portal'
import {
  EvidenceFileRef,
  INCIDENT_EVIDENCE_EVENTS,
  JunctionDetail,
  JunctionVehicle,
  VisionStatus,
  getJunction,
} from '@api/incidentEvidence'

const POLL_MS = 5000
const JUNCTIONS = ['J01', 'J02', 'J03']

const VERDICT: Record<VisionStatus, { label: string; variant: 'success' | 'warning' | 'danger' | 'muted' }> = {
  VISION_CONFIRMED: { label: 'Camera confirmed the plate', variant: 'success' },
  PROBABLE_MATCH: { label: 'Probable match (unconfirmed)', variant: 'warning' },
  NOT_CONFIRMED: { label: 'Camera read a different plate', variant: 'danger' },
  NO_PLATE_VISIBLE: { label: 'No plate visible', variant: 'muted' },
  PLATE_TOO_SMALL: { label: 'Plate too small to read', variant: 'muted' },
}

export const JunctionDetailPage: React.FC = () => {
  const { evidenceId, junctionId } = useParams<{ evidenceId: string; junctionId: string }>()
  const [data, setData] = useState<JunctionDetail | null>(null)
  const [error, setError] = useState('')
  const [zoom, setZoom] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!evidenceId || !junctionId) return
    try {
      setData(await getJunction(evidenceId, junctionId))
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load this junction.'))
    }
  }, [evidenceId, junctionId])

  useEffect(() => {
    setData(null)
    refresh()
  }, [refresh])

  useEffect(() => {
    return subscribeToLiveCameraMessages((message) => {
      const type = (message as Record<string, unknown>).type as string | undefined
      if (type && (INCIDENT_EVIDENCE_EVENTS as readonly string[]).includes(type)) refresh()
    })
  }, [refresh])

  const resolved = Boolean(data?.incident.resolved)
  const loaded = data !== null
  useEffect(() => {
    if (!loaded || resolved) return
    const timer = window.setInterval(refresh, POLL_MS)
    return () => window.clearInterval(timer)
  }, [loaded, resolved, refresh])

  const base = `/authority/evidence/${evidenceId}/tracking`
  const reference = (data?.incident.reference as string | undefined) ?? 'Incident'

  return (
    <div className="space-y-6">
      <div>
        <Link to={base} className="text-xs font-mono text-blue-800 hover:underline">
          ← Multi-Junction Tracking
        </Link>
        <div className="flex flex-wrap items-center gap-2 mt-2">
          <h2 className="text-2xl font-semibold text-blue-950">
            {data?.junction.label ?? junctionId} · {reference}
          </h2>
          {data?.junction.is_crash && <Badge variant="danger" size="sm">CRASH JUNCTION</Badge>}
          {data && !resolved && <Badge variant="danger" size="sm" dot>LIVE</Badge>}
        </div>
        <nav className="flex gap-2 mt-3" aria-label="Other junctions">
          {JUNCTIONS.map((id) => (
            <Link
              key={id}
              to={`${base}/${id}`}
              aria-current={id === junctionId?.toUpperCase() ? 'page' : undefined}
              className={`px-2.5 py-1 rounded border text-xs font-mono ${
                id === junctionId?.toUpperCase()
                  ? 'bg-blue-900 border-blue-900 text-white'
                  : 'bg-white border-slate-300 text-slate-700 hover:border-blue-800'
              }`}
            >
              {id}
            </Link>
          ))}
        </nav>
      </div>

      {error && <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded">{error}</div>}

      {!data ? (
        !error && <Spinner />
      ) : (
        <>
          {data.junction.is_crash && (
            <Card title="Crash frames" subtitle={`Recorded ${formatIst(data.incident.created_at)}`}>
              <Gallery files={data.crash_frames} onZoom={setZoom} empty="No camera frame was saved at the crash." />
            </Card>
          )}
          {data.vehicles.length === 0 ? (
            <Card>
              <p className="text-sm text-slate-600">
                The fled vehicle has not been read at {data.junction.label}.
                {!resolved && ' This page updates as soon as it is.'}
              </p>
            </Card>
          ) : (
            data.vehicles.map((vehicle) => (
              <VehicleAtJunction key={vehicle.plate_norm} vehicle={vehicle} isCrash={data.junction.is_crash} onZoom={setZoom} />
            ))
          )}
        </>
      )}

      {zoom && (
        <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-6" onClick={() => setZoom(null)}>
          <AuthImage src={zoom} alt="Evidence image (full size)" className="max-h-full max-w-full rounded" />
        </div>
      )}
    </div>
  )
}

const VehicleAtJunction: React.FC<{ vehicle: JunctionVehicle; isCrash: boolean; onZoom: (url: string) => void }> = ({
  vehicle,
  isCrash,
  onZoom,
}) => {
  const card = vehicle.evidence
  const primary = card?.primary
  const firstRead = vehicle.sightings.map((s) => s.seen_at).filter((t): t is string => Boolean(t)).sort()[0] ?? null
  const otherFrames = card?.supporting.images ?? []

  return (
    <Card
      title={
        <span className="flex flex-wrap items-center gap-2">
          {vehicle.fled ? 'Fled vehicle' : 'Involved vehicle'} · {vehicle.plate_display ?? vehicle.plate_norm}
          {vehicle.fled && <Badge variant="danger" size="sm">FLED</Badge>}
        </span>
      }
      subtitle={vehicle.basis ?? undefined}
    >
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* ANPR screenshot */}
        <div className="lg:col-span-2 space-y-3">
          <p className="text-[11px] font-mono uppercase text-slate-500">ANPR screenshot at this junction</p>
          {primary ? (
            <button type="button" onClick={() => onZoom(primary.image.url)} className="block w-full" title="Open full size">
              <AuthImage
                src={primary.image.url}
                alt={`ANPR frame of ${vehicle.plate_norm}`}
                className="w-full rounded border border-slate-300 hover:border-aghat-blue"
              />
            </button>
          ) : otherFrames.length > 0 ? (
            <Gallery files={otherFrames} onZoom={onZoom} />
          ) : (
            <p className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              {isCrash
                ? 'At the crash junction the vehicle is shown in the crash frames above.'
                : 'The camera recorded no frame of this vehicle here' +
                  (card?.match_reason ? ` (${card.match_reason}).` : '.')}
            </p>
          )}
          {primary && (
            <p className="text-[11px] font-mono text-slate-600">
              Saved {formatIstDate(primary.image.created_at)}, {formatIstTime(primary.image.created_at)}
              {primary.score != null && ` · evidence score ${primary.score.toFixed(2)}`}
            </p>
          )}
          {primary && otherFrames.length > 0 && (
            <details className="text-xs font-mono">
              <summary className="cursor-pointer text-aghat-blue">Other frames ({otherFrames.length})</summary>
              <div className="mt-2">
                <Gallery files={otherFrames} onZoom={onZoom} />
              </div>
            </details>
          )}
        </div>

        <div className="space-y-4 text-xs font-mono">
          {/* sighting time + owner */}
          <div className="rounded border border-slate-200 bg-slate-50 p-3 space-y-2">
            <div>
              <p className="text-[11px] uppercase text-slate-500">Sighted here at</p>
              <p className="text-sm font-semibold text-slate-900">
                {firstRead ? `${formatIstDate(firstRead)}, ${formatIstTime(firstRead)}` : isCrash ? 'At the crash' : 'Not read yet'}
              </p>
            </div>
            <div>
              <p className="text-[11px] uppercase text-slate-500">Owner name</p>
              <p className="text-sm font-semibold text-slate-900 font-sans">
                {vehicle.owner?.name ?? <span className="font-normal text-slate-600">No citizen has registered this plate</span>}
              </p>
            </div>
            <div>
              <p className="text-[11px] uppercase text-slate-500">Phone number</p>
              {vehicle.owner?.phone ? (
                <a href={`tel:${vehicle.owner.phone}`} className="text-sm font-semibold text-blue-800 hover:underline">
                  {vehicle.owner.phone}
                </a>
              ) : (
                <p className="text-slate-600">{vehicle.owner ? 'Not on file' : '—'}</p>
              )}
            </div>
            {vehicle.owner && (
              <p className="text-slate-600 break-all">
                {[vehicle.owner.email,
                  [vehicle.owner.vehicle.color, vehicle.owner.vehicle.make, vehicle.owner.vehicle.model, vehicle.owner.vehicle.year]
                    .filter(Boolean).join(' '),
                  vehicle.owner.vehicle.vehicle_type]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
            )}
          </div>

          {/* vehicle image */}
          <div>
            <p className="text-[11px] uppercase text-slate-500 mb-1">Vehicle</p>
            {vehicle.vehicle_image ? (
              <button type="button" onClick={() => onZoom(vehicle.vehicle_image!)} title="Open full size">
                <AuthImage
                  src={vehicle.vehicle_image}
                  alt={`Vehicle ${vehicle.plate_norm}`}
                  className="max-h-40 rounded border border-slate-300 hover:border-aghat-blue"
                />
              </button>
            ) : (
              <p className="text-slate-500">No vehicle image at this junction.</p>
            )}
          </div>

          {/* plate */}
          <div>
            <p className="text-[11px] uppercase text-slate-500 mb-1">Number plate</p>
            <p className="text-lg font-bold text-slate-900">{vehicle.plate_display ?? vehicle.plate_norm}</p>
            <p className="text-slate-600">
              {vehicle.state_name ?? 'State unknown'} · from RFID tag
              {vehicle.epc && <span title={vehicle.epc}> …{vehicle.epc.slice(-6)}</span>}
            </p>
            {primary?.plate_crop && (
              <button type="button" onClick={() => onZoom(primary.plate_crop!.url)} className="mt-2 block" title="Open full size">
                <AuthImage src={primary.plate_crop.url} alt="Plate crop" className="h-14 rounded border border-slate-300" />
              </button>
            )}
            {card && (
              <div className="mt-2 space-y-1">
                <p>
                  ANPR read:{' '}
                  <span className="font-bold text-slate-900">
                    {primary?.read_text_display ?? card.anpr_plate_display ?? 'not read'}
                  </span>
                  {card.anpr_confidence != null && ` (${(card.anpr_confidence * 100).toFixed(0)}%)`}
                </p>
                {card.status ? (
                  <Badge variant={VERDICT[card.status]?.variant ?? 'muted'} size="sm">
                    {VERDICT[card.status]?.label ?? card.status}
                  </Badge>
                ) : (
                  <Badge variant="info" size="sm" dot>Camera verifying…</Badge>
                )}
              </div>
            )}
          </div>

          {/* RFID reads */}
          <div>
            <p className="text-[11px] uppercase text-slate-500 mb-1">RFID reads here</p>
            {vehicle.sightings.length === 0 ? (
              <p className="text-slate-500">{isCrash ? 'Read in the crash zone at the time of the crash.' : 'None yet.'}</p>
            ) : (
              <ul className="space-y-0.5">
                {vehicle.sightings.map((s) => (
                  <li key={s.id} className="text-slate-700">
                    {formatIstTime(s.seen_at)} · {s.report_count} report(s)
                    {s.peak_rssi_dbm != null && ` · ${s.peak_rssi_dbm.toFixed(1)} dBm`}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </Card>
  )
}

const Gallery: React.FC<{ files: EvidenceFileRef[]; onZoom: (url: string) => void; empty?: string }> = ({
  files,
  onZoom,
  empty = 'No images.',
}) => {
  if (files.length === 0) return <p className="text-xs font-mono text-slate-500">{empty}</p>
  return (
    <div className="flex flex-wrap gap-2">
      {files.map((file) => (
        <button key={file.id} type="button" onClick={() => onZoom(file.url)} title="Open full size">
          <AuthImage src={file.url} alt={file.kind} loading="lazy"
                     className="h-32 rounded border border-slate-300 hover:border-aghat-blue" />
        </button>
      ))}
    </div>
  )
}
