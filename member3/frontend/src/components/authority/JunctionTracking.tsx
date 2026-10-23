/**
 * Junction tracking map — every involved vehicle of one crash.
 *
 * Draws the junctions at their world positions and, per vehicle, its route:
 * the crash junction, then every junction where its RFID tag was read after
 * the crash, in time order. Each vehicle's last read is its current position.
 * Built only from the incident payload, so it moves whenever the page
 * refreshes the incident. Times shown are real (IST) wall-clock times recorded
 * by the backend: the crash when it was recorded, a junction when its tag was
 * first read there. Sim time runs slower than real time and is only a tooltip.
 */

import React, { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AuthImage, Badge, Card } from '@components/ui'
import { IncidentDetail, JunctionPosition, VisionStatus } from '@api/incidentEvidence'
import { formatIstTime } from '@api/portal'

const W = 720
const H = 300
const PAD = 56
// room right of the nodes for the owner names
const NAME_ROOM = 150

// one colour per vehicle (route, marker, legend)
const COLOURS = ['#1d4ed8', '#d97706', '#047857', '#7c3aed', '#db2777', '#0e7490']

const VERDICT_LABEL: Record<VisionStatus, string> = {
  VISION_CONFIRMED: 'Camera confirmed',
  PROBABLE_MATCH: 'Camera probable',
  NOT_CONFIRMED: 'Camera not confirmed',
  NO_PLATE_VISIBLE: 'No plate visible',
  PLATE_TOO_SMALL: 'Plate too small',
}

export interface TrackStep {
  junction: string
  kind: 'crash' | 'sighting'
  /** wall clock (ISO) */
  at: string | null
  /** sim seconds, for the tooltip only */
  simFirst: number | null
  simLast: number | null
  reports: number | null
  verdict: VisionStatus | null
  verifying: boolean
}

export interface TrackedVehicle {
  key: string
  plate: string
  epc: string | null
  fled: boolean
  /** registered owner, null when nobody has registered the plate */
  ownerName: string | null
  colour: string
  steps: TrackStep[]
}

const simTip = (step: TrackStep) =>
  step.simFirst == null ? undefined
    : `simulation t=${step.simFirst.toFixed(1)}s${step.simLast != null && step.simLast !== step.simFirst ? ` – ${step.simLast.toFixed(1)}s` : ''}`

/** Every involved vehicle with its route; the fleeing one first. */
export function trackedVehicles(detail: IncidentDetail): TrackedVehicle[] {
  const crash = detail.incident.crash_junction
  const vehicles = detail.involved_vehicles.map((vehicle) => {
    const atCrash = detail.crash_zone_rfid.find((row) => vehicle.epc && row.epc === vehicle.epc)
    const sightings = detail.sightings
      .filter((s) => vehicle.epc && s.epc === vehicle.epc)
      .sort((a, b) => a.first_seen_ts - b.first_seen_ts)
    const steps: TrackStep[] = [
      ...(crash
        ? [{
            junction: crash,
            kind: 'crash' as const,
            at: detail.incident.created_at,
            simFirst: detail.incident.crash_ts_sim,
            simLast: null,
            reports: atCrash?.report_count ?? null,
            verdict: null,
            verifying: false,
          }]
        : []),
      ...sightings.map((s) => ({
        junction: s.junction_id,
        kind: 'sighting' as const,
        at: s.seen_at ?? null,
        simFirst: s.first_seen_ts,
        simLast: s.last_seen_ts,
        reports: s.report_count,
        verdict: s.vision?.status ?? null,
        verifying: !s.vision && !s.closed,
      })),
    ]
    return {
      key: vehicle.plate_norm,
      plate: vehicle.plate_display ?? vehicle.plate_norm,
      epc: vehicle.epc,
      fled: Boolean(vehicle.fled),
      ownerName: vehicle.owner_name ?? null,
      colour: '',
      steps,
    }
  })
  return vehicles
    .sort((a, b) => Number(b.fled) - Number(a.fled) || b.steps.length - a.steps.length)
    .map((v, i) => ({ ...v, colour: COLOURS[i % COLOURS.length] }))
}

const TODAY = new Intl.DateTimeFormat('en-IN', {
  timeZone: 'Asia/Kolkata', weekday: 'long', day: '2-digit', month: 'short', year: 'numeric',
})

/** Today's date in IST, re-checked every minute so it rolls over at midnight. */
function useToday(): string {
  const [today, setToday] = useState(() => TODAY.format(new Date()))
  useEffect(() => {
    const timer = window.setInterval(() => setToday(TODAY.format(new Date())), 60_000)
    return () => window.clearInterval(timer)
  }, [])
  return today
}

interface NodePreview {
  url: string | null
  caption: string
  seenAt: string | null
}

/** What hovering a junction shows: the fled vehicle's sighting frame there (crash frame at the crash junction). */
function nodePreview(detail: IncidentDetail, junction: string): NodePreview {
  if (junction === detail.incident.crash_junction) {
    const frame = detail.crash_frames?.[0]
    return { url: frame?.url ?? null, caption: 'Crash frame', seenAt: frame?.created_at ?? detail.incident.created_at }
  }
  const fled = new Set((detail.fleeing_vehicles ?? []).map((f) => f.epc).filter(Boolean))
  const ours = (epc: string) => fled.size === 0 || fled.has(epc)
  const cards = (detail.best_evidence_by_junction ?? []).filter((c) => c.junction_id === junction)
  const card = cards.find((c) => ours(c.epc)) ?? cards[0]
  const image = card?.primary?.image ?? card?.supporting.images[0] ?? null
  const seenAt = detail.sightings
    .filter((s) => s.junction_id === junction && ours(s.epc))
    .map((s) => s.seen_at)
    .filter((t): t is string => Boolean(t))
    .sort()[0] ?? null
  return { url: image?.url ?? null, caption: fled.size ? 'Fled vehicle sighting' : 'Vehicle sighting', seenAt }
}

/** World (x, y) -> SVG point, fitted to the box with the aspect kept. */
function projector(positions: Record<string, JunctionPosition>) {
  const points = Object.values(positions)
  const span = (f: (p: JunctionPosition) => number) =>
    Math.max(...points.map(f)) - Math.min(...points.map(f))
  // the longer world axis runs left to right
  const wide = span((p) => p.y) >= span((p) => p.x)
  const along = (p: JunctionPosition) => (wide ? p.y : p.x)
  const across = (p: JunctionPosition) => (wide ? p.x : p.y)
  const a0 = Math.min(...points.map(along))
  const c0 = Math.min(...points.map(across))
  const scale = Math.min((W - 2 * PAD - NAME_ROOM) / Math.max(1, span(along)), (H - 2 * PAD) / Math.max(1, span(across)))
  const offX = (W - NAME_ROOM - span(along) * scale) / 2
  const offY = (H - span(across) * scale) / 2
  return (p: JunctionPosition) => ({ x: offX + (along(p) - a0) * scale, y: offY + (across(p) - c0) * scale })
}

export const JunctionTrackingMap: React.FC<{ detail: IncidentDetail; vehicles: TrackedVehicle[] }> = ({
  detail,
  vehicles,
}) => {
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const [hovered, setHovered] = useState<string | null>(null)
  const today = useToday()
  const navigate = useNavigate()
  const positions = detail.junction_positions ?? {}
  const junctionPage = (id: string) => `/authority/evidence/${detail.incident.id}/tracking/${id}`
  const project = useMemo(() => projector(positions), [positions])
  if (Object.keys(positions).length === 0) return null

  const junctions = Object.entries(positions).sort(([a], [b]) => a.localeCompare(b))
  const crash = detail.incident.crash_junction
  const shown = vehicles.filter((v) => !hidden.has(v.key))
  const toggle = (key: string) =>
    setHidden((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  return (
    <Card
      title="Route map"
      subtitle="Arrows: the order each vehicle's RFID tag was read · ● where it was read last (IST) · click a junction to open its sighting"
    >
      {vehicles.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3" role="group" aria-label="Vehicles shown on the map">
          {vehicles.map((v) => (
            <button
              key={v.key}
              type="button"
              onClick={() => toggle(v.key)}
              aria-pressed={!hidden.has(v.key)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded border text-xs font-mono ${
                hidden.has(v.key) ? 'bg-white border-slate-200 text-slate-400' : 'bg-white border-slate-300 text-slate-800'
              }`}
            >
              <span className="w-3 h-3 rounded-full" style={{ background: hidden.has(v.key) ? '#cbd5e1' : v.colour }} />
              {v.plate}
              {v.fled && <span className="text-red-700 font-bold">FLED</span>}
            </button>
          ))}
        </div>
      )}

      <div className="relative bg-slate-50 border border-slate-200 rounded">
        <p className="absolute top-2 left-3 text-xs font-mono text-slate-700" aria-live="polite">
          <span className="text-slate-500">Today</span> {today}
        </p>
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img"
             aria-label={shown.map((v) => `${v.plate}: ${v.steps.map((s) => s.junction).join(' to ')}`).join('; ')}>
          <defs>
            {vehicles.map((v) => (
              <marker key={v.key} id={`arrow-${v.key}`} viewBox="0 0 10 10" refX="9" refY="5"
                      markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" fill={v.colour} />
              </marker>
            ))}
          </defs>

          {/* the road between neighbouring junctions */}
          {junctions.slice(1).map(([id, pos], i) => {
            const a = project(junctions[i][1])
            const b = project(pos)
            return <line key={`road-${id}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                         stroke="#cbd5e1" strokeWidth={14} strokeLinecap="round" />
          })}

          {/* routes: each vehicle offset sideways so overlapping routes stay visible */}
          {shown.map((v) => {
            const lane = (vehicles.indexOf(v) - (vehicles.length - 1) / 2) * 6
            const route = v.steps.filter((s) => positions[s.junction])
            return route.slice(1).map((step, i) => {
              const a = project(positions[route[i].junction])
              const b = project(positions[step.junction])
              const len = Math.hypot(b.x - a.x, b.y - a.y) || 1
              const [ux, uy] = [(b.x - a.x) / len, (b.y - a.y) / len]
              const [nx, ny] = [-uy * lane, ux * lane]
              const r = 26   // stop at the node edge
              return (
                <line key={`${v.key}-${i}`}
                      x1={a.x + ux * r + nx} y1={a.y + uy * r + ny}
                      x2={b.x - ux * r + nx} y2={b.y - uy * r + ny}
                      stroke={v.colour} strokeWidth={3} markerEnd={`url(#arrow-${v.key})`} />
              )
            })
          })}

          {junctions.map(([id, pos]) => {
            const { x, y } = project(pos)
            const isCrash = id === crash
            const visited = shown.some((v) => v.steps.some((s) => s.junction === id))
            return (
              <g key={id} role="link" tabIndex={0} className="cursor-pointer focus:outline-none [&:focus>circle:last-of-type]:stroke-cyan-500"
                 aria-label={`Open ${pos.label}: ANPR screenshot and owner of the fled vehicle`}
                 onClick={() => navigate(junctionPage(id))}
                 onMouseEnter={() => setHovered(id)} onMouseLeave={() => setHovered(null)}
                 onFocus={() => setHovered(id)} onBlur={() => setHovered(null)}
                 onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate(junctionPage(id)) } }}>
                <title>Open {pos.label}</title>
                {isCrash && <circle cx={x} cy={y} r={30} fill="#fee2e2" stroke="#fca5a5" />}
                <circle cx={x} cy={y} r={20}
                        fill={isCrash ? '#dc2626' : visited ? '#1e3a8a' : '#ffffff'}
                        stroke={isCrash || visited ? 'none' : '#94a3b8'} strokeWidth={2} />
                <text x={x} y={y + 4} textAnchor="middle" fontSize={11} fontWeight={700}
                      fontFamily="ui-monospace, monospace" fill={isCrash || visited ? '#ffffff' : '#64748b'}>
                  {id}
                </text>
                <text x={x} y={y - 38} textAnchor="middle" fontSize={11}
                      fontFamily="ui-monospace, monospace" fill="#0f172a">
                  {pos.label}{isCrash ? ' · CRASH' : ''}
                </text>
                {/* to the right of the node: the crashed and fled vehicles' owners here (plate when unregistered) */}
                {(() => {
                  const here = shown.filter((v) => v.steps.some((s) => s.junction === id))
                  const lines = here.map((v) => ({
                    key: v.key,
                    colour: v.colour,
                    text: `${v.fled ? 'Fled' : 'Crashed'}: ${v.ownerName ?? v.plate}`,
                  }))
                  return lines.map((line, n) => (
                    <text key={line.key} x={x + (isCrash ? 36 : 28)} y={y + 4 - ((lines.length - 1) * 14) / 2 + n * 14}
                          textAnchor="start" fontSize={11} fontWeight={600}
                          fontFamily="ui-sans-serif, system-ui, sans-serif" fill={line.colour}>
                      {line.text}
                    </text>
                  ))
                })()}
              </g>
            )
          })}

          {/* current position: a marker beside the junction of each vehicle's last read */}
          {shown.map((v) => {
            const last = [...v.steps].reverse().find((s) => positions[s.junction])
            if (!last) return null
            const { x, y } = project(positions[last.junction])
            const here = shown.filter((o) => [...o.steps].reverse().find((s) => positions[s.junction])?.junction === last.junction)
            const slot = here.indexOf(v)
            const py = y + 44 + slot * 16
            return (
              <g key={`now-${v.key}`}>
                <circle cx={x - 34} cy={py - 4} r={5} fill={v.colour} />
                <text x={x - 25} y={py} fontSize={10} fontFamily="ui-monospace, monospace" fill="#0f172a">
                  {v.plate} {formatIstTime(last.at)}
                </text>
              </g>
            )
          })}
        </svg>
        {hovered && positions[hovered] && (
          <JunctionPreview
            preview={nodePreview(detail, hovered)}
            label={positions[hovered].label}
            point={project(positions[hovered])}
          />
        )}
      </div>
    </Card>
  )
}

/** Floating card next to a hovered junction: its sighting frame and real time. */
const JunctionPreview: React.FC<{ preview: NodePreview; label: string; point: { x: number; y: number } }> = ({
  preview,
  label,
  point,
}) => {
  const fx = point.x / W
  const below = point.y / H < 0.5
  const shiftX = fx < 0.25 ? '0%' : fx > 0.75 ? '-100%' : '-50%'
  return (
    <div
      className="pointer-events-none absolute z-10 w-60 rounded-md border border-slate-300 bg-white p-2 shadow-lg"
      style={{
        left: `${fx * 100}%`,
        top: `${(point.y / H) * 100}%`,
        transform: `translate(${shiftX}, ${below ? '36px' : 'calc(-100% - 36px)'})`,
      }}
      role="tooltip"
    >
      {preview.url ? (
        <AuthImage src={preview.url} alt={`${label} sighting`} className="w-full rounded border border-slate-200" />
      ) : (
        <p className="py-4 text-center text-[11px] font-mono text-slate-500">No image recorded here</p>
      )}
      <p className="mt-1 text-xs font-mono font-semibold text-slate-900">{label}</p>
      <p className="text-[11px] font-mono text-slate-600">
        {preview.caption} · {preview.seenAt ? formatIstTime(preview.seenAt) : 'not read here yet'}
      </p>
      <p className="text-[10px] font-mono text-blue-800">Click to open the sighting</p>
    </div>
  )
}

/** Per vehicle: every junction it was read at, in order, with the camera verdict. */
export const VehicleTimeline: React.FC<{
  vehicle: TrackedVehicle
  positions: Record<string, JunctionPosition>
  incidentId: string
}> = ({
  vehicle,
  positions,
  incidentId,
}) => {
  const last = vehicle.steps[vehicle.steps.length - 1]
  return (
    <Card>
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-full" style={{ background: vehicle.colour }} />
          <span className="font-mono font-bold text-slate-900">{vehicle.plate}</span>
          {vehicle.fled && <Badge variant="danger" size="sm">FLED</Badge>}
        </div>
        {last && (
          <span className="text-[11px] font-mono text-slate-600">
            last read: {positions[last.junction]?.label ?? last.junction}
          </span>
        )}
      </div>
      <ol className="relative pl-5 space-y-2 text-xs font-mono before:absolute before:left-1.5 before:top-1 before:bottom-1 before:w-0.5 before:bg-slate-200">
        {vehicle.steps.map((step, i) => (
          <li key={`${step.junction}-${i}`} className="relative">
            <span className="absolute -left-[18px] top-1 w-2.5 h-2.5 rounded-full"
                  style={{ background: step.kind === 'crash' ? '#dc2626' : vehicle.colour }} />
            <div className="flex items-center justify-between gap-2">
              <span className="text-slate-900 font-semibold">
                {i + 1}.{' '}
                <Link to={`/authority/evidence/${incidentId}/tracking/${step.junction}`} className="hover:underline">
                  {positions[step.junction]?.label ?? step.junction} →
                </Link>
              </span>
              <span className="text-slate-600" title={simTip(step)}>
                {formatIstTime(step.at)}
              </span>
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-2">
              {step.kind === 'crash' ? (
                <Badge variant="danger" size="sm">CRASH RECORDED</Badge>
              ) : step.verdict ? (
                <Badge variant={step.verdict === 'VISION_CONFIRMED' ? 'success' : 'warning'} size="sm">
                  {VERDICT_LABEL[step.verdict] ?? step.verdict}
                </Badge>
              ) : (
                <Badge variant="info" size="sm" dot>{step.verifying ? 'Camera verifying…' : 'No camera result'}</Badge>
              )}
              {step.reports != null && <span className="text-slate-500">{step.reports} RFID report(s)</span>}
            </div>
          </li>
        ))}
      </ol>
      {vehicle.steps.length <= 1 && (
        <p className="mt-2 text-[11px] font-mono text-slate-500">
          {vehicle.epc ? 'Not read at another junction yet.' : 'No RFID tag registered: this vehicle cannot be tracked by RFID.'}
        </p>
      )}
    </Card>
  )
}
