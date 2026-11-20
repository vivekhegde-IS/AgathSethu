/**
 * Incident Evidence (detail page) — /authority/evidence/:evidenceId
 *
 * Opened only from an incident on the Crash Incident Radar or a row in
 * Evidence Records (not in the sidebar). Shows the crash, the involved
 * vehicles, the crash-zone RFID snapshot (the route map is on its own
 * page, opened by the Multi-junction tracking button),
 * next-junction sightings with the camera plate verdict (and the strict
 * partial plate where the camera could not confirm it), and the stored
 * evidence images. Refreshes live on the
 * portal events incident_created / watchlist_rfid_hit / vision_match_result.
 */

import React, { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AuthImage, Badge, Button, Card, Spinner } from '@components/ui'
import { ResolveIncidentModal } from '@components/authority/ResolveIncidentModal'
import { CrashTypeBadge } from '@components/authority/CrashTypeBadge'
import { CaseBadge, OwnerAnswers } from '@components/authority/OwnerAnswers'
import type { CaseView, CrashResponseView } from '@api/live'
import { subscribeToLiveCameraMessages } from '@services/websocket/liveCamerasSocket'
import { errorMessage, formatIst } from '@api/portal'
import {
  EvidenceFileRef,
  INCIDENT_EVIDENCE_EVENTS,
  IncidentDetail,
  JunctionEvidence,
  PartialPlate,
  SightingView,
  VisionStatus,
  getIncident,
} from '@api/incidentEvidence'

type BadgeVariant = 'success' | 'warning' | 'danger' | 'info' | 'muted' | 'brand'

const STATUS_VARIANT: Record<VisionStatus, BadgeVariant> = {
  VISION_CONFIRMED: 'success',
  PROBABLE_MATCH: 'warning',
  NOT_CONFIRMED: 'danger',
  NO_PLATE_VISIBLE: 'muted',
  PLATE_TOO_SMALL: 'muted',
}

const STATUS_LABEL: Record<VisionStatus, string> = {
  VISION_CONFIRMED: 'CONFIRMED',
  PROBABLE_MATCH: 'PROBABLE (UNCONFIRMED)',
  NOT_CONFIRMED: 'NOT CONFIRMED',
  NO_PLATE_VISIBLE: 'NO PLATE VISIBLE',
  PLATE_TOO_SMALL: 'PLATE TOO SMALL',
}

const t = (value: number | null | undefined) => (value == null ? '—' : `${value.toFixed(2)}s`)
const epcTail = (epc: string) => `…${epc.slice(-6)}`

export const IncidentEvidencePage: React.FC = () => {
  const { evidenceId } = useParams<{ evidenceId: string }>()
  const [detail, setDetail] = useState<IncidentDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [zoom, setZoom] = useState<EvidenceFileRef | null>(null)
  const [resolving, setResolving] = useState(false)

  const refresh = useCallback(async () => {
    if (!evidenceId) return
    try {
      setDetail(await getIncident(evidenceId))
      setError(null)
    } catch (err) {
      setError(errorMessage(err, 'Could not load this incident.'))
    }
  }, [evidenceId])

  useEffect(() => {
    setDetail(null)
    refresh()
  }, [refresh])

  // Live: a feature event for any incident refreshes the open one.
  useEffect(() => {
    return subscribeToLiveCameraMessages((message) => {
      const type = (message as Record<string, unknown>).type as string | undefined
      if (type && (INCIDENT_EVIDENCE_EVENTS as readonly string[]).includes(type)) refresh()
    })
  }, [refresh])

  const incident = detail?.incident as (IncidentDetail['incident'] & Record<string, unknown>) | undefined
  const reference = (incident?.reference as string | undefined) ?? 'Incident'
  const resolved = Boolean(incident?.resolved)

  return (
    <div className="space-y-6">
      <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
        <div>
          <div className="flex gap-3 text-xs font-mono">
            <Link to="/authority/incidents" className="text-blue-800 hover:underline">
              ← Crash Incident Radar
            </Link>
            <Link to="/authority/evidence" className="text-blue-800 hover:underline">
              Evidence Records
            </Link>
          </div>
          <div className="flex items-center gap-2 mt-2">
            <h2 className="text-2xl font-semibold text-blue-950">Incident Evidence · {reference}</h2>
            {incident && (
              <>
                <Badge variant={resolved ? 'success' : 'danger'} size="sm">
                  {resolved ? 'Resolved' : 'Unresolved'}
                </Badge>
                <CrashTypeBadge kind={incident} />
                <CaseBadge value={incident.case as CaseView | null | undefined} />
              </>
            )}
          </div>
          {incident && (
            <p className="text-sm text-slate-600 mt-1">
              {String(incident.location ?? '')} · detected {formatIst(incident.created_at)}
              {resolved &&
                ` · resolved ${formatIst(incident.resolved_at as string | null)} by ${String(incident.resolved_by_name ?? '—')}`}
            </p>
          )}
          {resolved && typeof incident?.resolution_note === 'string' && (
            <p className="text-xs text-emerald-700 font-mono mt-1">Note: {incident.resolution_note}</p>
          )}
          {incident && (
            <OwnerAnswers answers={incident.citizen_responses as CrashResponseView[] | undefined}
                          value={incident.case as CaseView | null | undefined} onChanged={refresh} />
          )}
        </div>
        {incident && (
          <div className="flex gap-2">
            <Link to={`/authority/evidence/${encodeURIComponent(String(incident.id))}/tracking`}>
              <Button variant="primary" size="sm">
                Multi-junction tracking →
              </Button>
            </Link>
            {!resolved && Boolean(incident.live_feed) && incident.crash_junction && (
              <Link to={`/authority/live?junction=${encodeURIComponent(incident.crash_junction)}`}>
                <Button variant="outline" size="sm">
                  View live feed
                </Button>
              </Link>
            )}
            {!resolved && (
              <Button variant="success" size="sm" onClick={() => setResolving(true)}>
                Mark as resolved
              </Button>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="text-xs font-mono text-red-700 border border-red-200 rounded p-3">{error}</div>
      )}

      {!detail && !error ? <Spinner /> : detail ? <IncidentTimeline detail={detail} onZoom={setZoom} /> : null}

      {zoom && (
        <div
          className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-6"
          onClick={() => setZoom(null)}
        >
          <AuthImage src={zoom.url} alt={zoom.kind} className="max-h-full max-w-full rounded" />
        </div>
      )}

      <ResolveIncidentModal
        incident={resolving && incident ? { id: incident.id, reference, location: String(incident.location ?? '') } : null}
        onClose={() => setResolving(false)}
        onResolved={refresh}
      />
    </div>
  )
}

/** Does the incident have any stored image at all (crash frames, snapshots, sightings)? */
function hasAnyImage(detail: IncidentDetail): boolean {
  const d = detail as IncidentDetail & {
    snapshots?: { frames?: unknown[] }[]
    best_evidence_by_junction?: { primary?: unknown }[]
  }
  return Boolean(
    detail.crash_frames?.length ||
      d.snapshots?.some((s) => s.frames?.length) ||
      d.best_evidence_by_junction?.some((c) => c.primary) ||
      detail.sightings?.some((s) => s.vision?.evidence?.length),
  )
}

const IncidentTimeline: React.FC<{ detail: IncidentDetail; onZoom: (file: EvidenceFileRef) => void }> = ({
  detail,
  onZoom,
}) => {
  const { incident } = detail
  return (
    <>
      <Card
        title={`Crash at ${incident.crash_junction ?? '?'} · t=${t(incident.crash_ts_sim)}`}
        subtitle={`run ${incident.run_id ?? '—'} · frame ${incident.crash_frame ?? '—'}`}
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs font-mono">
          <div>
            <p className="text-slate-500 uppercase mb-1">Crash alerts ({detail.alerts.length})</p>
            {detail.alerts.map((alert) => (
              <p key={alert.alert_id} className="text-slate-700">
                {t(alert.timestamp_sim)} <span className="text-slate-900">{alert.alert_id}</span>{' '}
                <span className="text-slate-500">{alert.source}</span>
              </p>
            ))}
          </div>
          <div>
            <p className="text-slate-500 uppercase mb-1">Watchlist (involved)</p>
            {detail.involved_vehicles.map((vehicle) => (
              <p key={vehicle.plate_norm} className="text-slate-700">
                <span className="text-slate-900 font-bold">{vehicle.plate_display ?? vehicle.plate_norm}</span>{' '}
                {vehicle.epc ? epcTail(vehicle.epc) : <Badge variant="warning" size="sm">{vehicle.registry}</Badge>}
                {vehicle.fled && (
                  <Badge variant="danger" size="sm">
                    FLED
                  </Badge>
                )}
              </p>
            ))}
          </div>
        </div>
        {detail.crash_frames && detail.crash_frames.length > 0 ? (
          <div className="mt-4">
            <p className="text-slate-500 uppercase text-xs font-mono mb-2">Crash-junction frames (±1 s)</p>
            <Gallery files={detail.crash_frames} onZoom={onZoom} />
          </div>
        ) : (
          <p className="mt-4 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            {hasAnyImage(detail)
              ? 'No camera frame was saved at the crash junction itself; the images recorded for this incident are below.'
              : 'No camera images were saved for this incident. The camera feed was not available to the backend when the crash was recorded.'}
          </p>
        )}
      </Card>

      <Card title={`Crash-zone RFID snapshot · ${incident.crash_junction ?? '?'}`} subtitle="t_crash ± 30 s">
        <table className="w-full text-xs font-mono">
          <thead className="text-slate-500 text-left">
            <tr>
              <th className="py-1">PLATE (REGISTRY)</th>
              <th>EPC</th>
              <th>ROLE</th>
              <th>SEEN</th>
              <th>REPORTS</th>
              <th>PEAK RSSI</th>
            </tr>
          </thead>
          <tbody>
            {detail.crash_zone_rfid.map((row) => (
              <tr key={row.epc} className="border-t border-slate-200 text-slate-700">
                <td className="py-1 text-slate-900">
                  {row.plate_norm ?? <Badge variant="warning" size="sm">UNREGISTERED_TAG</Badge>}
                </td>
                <td>{epcTail(row.epc)}</td>
                <td>
                  <Badge variant={row.role === 'involved' ? 'danger' : 'muted'} size="sm">
                    {row.role}
                  </Badge>
                </td>
                <td>
                  {t(row.first_seen_ts)} – {t(row.last_seen_ts)}
                </td>
                <td>{row.report_count}</td>
                <td>{row.peak_rssi_dbm == null ? '—' : `${row.peak_rssi_dbm.toFixed(1)} dBm`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {(detail.fleeing_vehicles ?? []).map((suspect) => (
        <Card
          key={suspect.plate_norm}
          title={`Fleeing vehicle · ${suspect.sim_vehicle_id ?? '?'}`}
          subtitle={suspect.basis}
        >
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 text-xs font-mono">
            <div>
              <p className="text-slate-500 uppercase">Final plate read (ANPR)</p>
              <p className={`text-lg font-bold ${suspect.final_plate_read ? 'text-slate-900' : 'text-red-700'}`}>
                {suspect.final_plate_read_display ?? suspect.final_plate_read ?? 'Not read'}
              </p>
            </div>
            <div>
              <p className="text-slate-500 uppercase">Registry plate (RFID)</p>
              <p className="text-lg font-bold text-slate-900">{suspect.plate_display ?? suspect.plate_norm}</p>
              <p className="text-slate-600">
                {suspect.state_name ?? ''} {suspect.epc ? `· ${epcTail(suspect.epc)}` : ''}
              </p>
            </div>
            <div>
              <p className="text-slate-500 uppercase">Overall status</p>
              {suspect.overall_status ? (
                <Badge variant={STATUS_VARIANT[suspect.overall_status] ?? 'muted'} size="md">
                  {STATUS_LABEL[suspect.overall_status] ?? suspect.overall_status}
                </Badge>
              ) : (
                <Badge variant="info" size="md" dot>
                  AWAITING SIGHTING
                </Badge>
              )}
              {suspect.overall_reason && <p className="mt-1 text-slate-600">{suspect.overall_reason}</p>}
            </div>
            <div>
              <p className="text-slate-500 uppercase">Seen at</p>
              <p className="text-slate-900">
                {[incident.crash_junction ?? '?', ...suspect.junctions].join(' → ')}
              </p>
            </div>
          </div>
        </Card>
      ))}

      <Card title="Next-junction sightings" subtitle="RFID watchlist hits after the crash, verified by the blind ANPR">
        {detail.sightings.length === 0 ? (
          <p className="text-xs font-mono text-slate-600">
            No watchlisted tag has been read at another junction yet.
          </p>
        ) : detail.best_evidence_by_junction ? (
          <div className="space-y-4">
            <p className="text-[11px] font-mono text-slate-600">
              Route:{' '}
              <span className="text-slate-900">
                {[incident.crash_junction ?? '?', ...detail.best_evidence_by_junction.map((card) => card.junction_id)].join(' → ')}
              </span>{' '}
              · one best frame per junction
            </p>
            {detail.best_evidence_by_junction.map((card) => (
              <JunctionEvidenceCard
                key={`${card.epc}-${card.junction_id}`}
                card={card}
                sightings={detail.sightings.filter((s) => card.sighting_ids.includes(s.id))}
                onZoom={onZoom}
              />
            ))}
          </div>
        ) : (
          <div className="space-y-4">
            {detail.sightings.map((sighting) => (
              <SightingRow key={sighting.id} sighting={sighting} onZoom={onZoom} />
            ))}
          </div>
        )}
      </Card>
    </>
  )
}

/** ONE card per junction: the best-scoring frame of the suspect there. */
const JunctionEvidenceCard: React.FC<{
  card: JunctionEvidence
  sightings: SightingView[]
  onZoom: (file: EvidenceFileRef) => void
}> = ({ card, sightings, onZoom }) => {
  const [showAll, setShowAll] = useState(false)
  const primary = card.primary
  const total = card.supporting.frames
  return (
    <div className="border border-slate-200 rounded-md p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs font-mono">
        <span className="text-slate-900 font-bold">{card.junction_id}</span>
        <span className="text-slate-600">
          {t(card.first_seen_ts)} – {t(card.last_seen_ts)}
        </span>
        <span className="text-slate-600">
          suspect <span className="text-slate-900">{card.suspect_vehicle_id ?? '?'}</span> · RFID {epcTail(card.epc)} →{' '}
          <span className="text-slate-900">{card.rfid_plate_display ?? card.rfid_plate ?? '—'}</span>
        </span>
        {card.status ? (
          <Badge variant={STATUS_VARIANT[card.status] ?? 'muted'} size="sm">
            {STATUS_LABEL[card.status] ?? card.status}
            {card.rule_assisted ? ' · RULE-ASSISTED' : ''}
          </Badge>
        ) : (
          <Badge variant="info" size="sm" dot>
            VERIFYING…
          </Badge>
        )}
      </div>

      <div className="mt-3 grid grid-cols-1 lg:grid-cols-3 gap-3">
        <div className="lg:col-span-2">
          {primary ? (
            <button onClick={() => onZoom(primary.image)} className="block w-full text-left">
              <AuthImage
                src={primary.image.url}
                alt={`${card.junction_id} best evidence frame`}
                className="w-full rounded border border-slate-300 hover:border-aghat-blue"
              />
            </button>
          ) : (
            <p className="text-[11px] font-mono text-slate-500">
              No frame of the suspect yet{card.match_reason ? ` — ${card.match_reason}` : ''}.
            </p>
          )}
        </div>
        <div className="text-[11px] font-mono text-slate-700 space-y-2">
          {primary?.plate_crop && (
            <button onClick={() => onZoom(primary.plate_crop!)} className="block">
              <AuthImage
                src={primary.plate_crop.url}
                alt="plate crop"
                className="h-16 rounded border border-slate-300 hover:border-aghat-blue"
              />
            </button>
          )}
          <div>
            <p className="text-slate-500 uppercase">Read in this frame</p>
            <p className={`text-base font-bold ${primary?.read_valid ? 'text-slate-900' : 'text-red-700'}`}>
              {primary?.read_text_display ?? 'Plate not read'}
            </p>
            {primary?.read_confidence != null && (
              <p>OCR confidence {(primary.read_confidence * 100).toFixed(0)}%</p>
            )}
          </div>
          <div>
            <p className="text-slate-500 uppercase">Junction verdict</p>
            <p>
              ANPR <span className="text-slate-900 font-bold">{card.anpr_plate_display ?? card.anpr_plate ?? 'none'}</span>
              {card.anpr_confidence != null && ` (${(card.anpr_confidence * 100).toFixed(0)}%)`}
            </p>
            {card.match_reason && <p className="text-slate-600">{card.match_reason}</p>}
          </div>
          <p className="text-slate-600">
            frame t={t(primary?.frame_ts)}
            {primary?.score != null && ` · evidence score ${primary.score.toFixed(2)}`}
            {primary?.legacy && ' · (older record)'}
          </p>
          <p className="text-slate-500">
            {card.supporting.candidate_reads} candidate read(s) of the suspect at this junction
          </p>
          {card.partial_plate && <PartialPlateBox partial={card.partial_plate} />}
          {(total > 0 || sightings.length > 0) && (
            <button
              onClick={() => setShowAll((value) => !value)}
              className="text-aghat-blue hover:underline"
            >
              {showAll ? 'Hide other frames' : `Show all ${total} frame(s)`}
            </button>
          )}
        </div>
      </div>

      {showAll && (
        <div className="mt-3 space-y-3 border-t border-slate-200 pt-3">
          <Gallery files={card.supporting.images} onZoom={onZoom} />
          {card.supporting.candidates.length > 0 && (
            <table className="w-full text-[11px] font-mono">
              <thead className="text-slate-500 text-left">
                <tr>
                  <th className="py-1">T</th>
                  <th>READ</th>
                  <th>RAW OCR</th>
                  <th>OCR CONF</th>
                  <th>PLATE PX</th>
                </tr>
              </thead>
              <tbody>
                {card.supporting.candidates.map((read, index) => (
                  <tr key={index} className="border-t border-slate-200 text-slate-700">
                    <td className="py-0.5">{t(read.ts)}</td>
                    <td className={read.valid ? 'text-slate-900' : 'text-red-700'}>{read.corrected ?? '—'}</td>
                    <td>{read.raw ?? '—'}</td>
                    <td>{read.mean_conf == null ? '—' : read.mean_conf.toFixed(2)}</td>
                    <td>{read.width_px == null ? '—' : read.width_px.toFixed(0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {sightings.map((sighting) => (
            <SightingRow key={sighting.id} sighting={sighting} onZoom={onZoom} showGallery={false} />
          ))}
        </div>
      )}
    </div>
  )
}

/** The pattern with unread characters highlighted: _ (one), * (0-2), + (0-1). */
const Pattern: React.FC<{ value: string }> = ({ value }) => (
  <span className="font-mono text-base font-bold tracking-widest">
    {value.split('').map((ch, i) => (
      <span key={i} className={'_*+'.includes(ch) ? 'text-amber-700' : 'text-slate-900'}>
        {ch}
      </span>
    ))}
  </span>
)

/** Camera could not confirm the RFID plate here: what it partly read, and the registered plates that fit. */
const PartialPlateBox: React.FC<{ partial: PartialPlate }> = ({ partial }) => (
  <div className="rounded border border-amber-300 bg-amber-50 p-2 space-y-1">
    <p className="text-slate-500 uppercase">Partial plate (camera)</p>
    <Pattern value={partial.pattern} />
    <p className="text-slate-600">
      unread: <span className="text-amber-700">_</span> one, <span className="text-amber-700">*</span> 0–2,{' '}
      <span className="text-amber-700">+</span> 0–1
      {partial.frames_used != null && ` · ${partial.frames_used} frame(s)`}
    </p>
    {partial.alternative_patterns.length > 0 && (
      <p className="text-slate-500">Other layouts: {partial.alternative_patterns.join(' · ')}</p>
    )}
    <p className="text-slate-500 uppercase pt-1">Registered plates that fit ({partial.candidates.length})</p>
    {partial.candidates.length === 0 ? (
      <p className="text-slate-500">No registered vehicle matches.</p>
    ) : (
      <div className="flex flex-wrap gap-1">
        {partial.candidates.map((c) => (
          <span key={`${c.source}-${c.plate}`} className="px-1.5 py-0.5 bg-white border border-cyan-200 rounded text-blue-800"
                title={c.epc ? `RFID ${c.epc}` : 'citizen vehicle registry'}>
            {c.plate} <span className="text-slate-500">{c.score.toFixed(2)}</span>
          </span>
        ))}
      </div>
    )}
  </div>
)

const SightingRow: React.FC<{
  sighting: SightingView
  onZoom: (file: EvidenceFileRef) => void
  showGallery?: boolean
}> = ({
  sighting,
  onZoom,
  showGallery = true,
}) => {
  const vision = sighting.vision
  return (
    <div className="border border-slate-200 rounded-md p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs font-mono">
        <span className="text-slate-900 font-bold">{sighting.junction_id}</span>
        <span className="text-slate-600">
          {t(sighting.first_seen_ts)} – {t(sighting.last_seen_ts)}
        </span>
        <span className="text-slate-600">
          RFID {epcTail(sighting.epc)} → <span className="text-slate-900">{sighting.plate_norm ?? '—'}</span>
        </span>
        <span className="text-slate-500">
          {sighting.report_count} report(s)
          {sighting.peak_rssi_dbm != null && ` · ${sighting.peak_rssi_dbm.toFixed(1)} dBm`}
        </span>
        {vision ? (
          <Badge variant={STATUS_VARIANT[vision.status]} size="sm">
            {STATUS_LABEL[vision.status] ?? vision.status}
          </Badge>
        ) : (
          <Badge variant="info" size="sm" dot>
            {sighting.closed ? 'NO VISION RESULT' : 'VERIFYING…'}
          </Badge>
        )}
      </div>
      {vision && (
        <div className="mt-2 grid grid-cols-1 lg:grid-cols-3 gap-3">
          <div className="text-[11px] font-mono text-slate-700 space-y-0.5">
            <p>
              ANPR <span className="text-slate-900 font-bold">{vision.anpr_plate ?? 'none'}</span>
              {vision.anpr_confidence != null && ` (${(vision.anpr_confidence * 100).toFixed(0)}%)`}
              {vision.edit_distance != null && ` · edit distance ${vision.edit_distance}`}
            </p>
            <p>
              {vision.camera_id ?? '—'} · {vision.frames_used ?? 0} frame(s) · Δt {t(vision.time_delta_s)}
            </p>
            <p className="text-slate-600">plates seen: {vision.all_plates_seen?.join(', ') || '—'}</p>
            <p className="text-slate-600 break-all">{vision.anpr_model}</p>
          </div>
          {showGallery && (
            <div className="lg:col-span-2">
              <Gallery files={vision.evidence} onZoom={onZoom} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const Gallery: React.FC<{ files: EvidenceFileRef[]; onZoom: (file: EvidenceFileRef) => void }> = ({
  files,
  onZoom,
}) => {
  if (files.length === 0) return <p className="text-[11px] font-mono text-slate-500">No evidence files.</p>
  return (
    <div className="flex flex-wrap gap-2">
      {files.map((file) => (
        <button key={file.id} onClick={() => onZoom(file)} className="text-left" title={`sha256 ${file.sha256}`}>
          <AuthImage
            src={file.url}
            alt={file.kind}
            loading="lazy"
            className={`rounded border border-slate-300 hover:border-aghat-blue ${
              file.kind === 'plate_crop' ? 'h-16' : 'h-32'
            }`}
          />
          <span className="block text-[10px] font-mono text-slate-500">{file.kind}</span>
        </button>
      ))}
    </div>
  )
}
