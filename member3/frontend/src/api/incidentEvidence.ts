/**
 * RFID -> camera plate cross-verification: incident evidence API.
 *
 * GET /api/incidents                                   newest incidents first
 * GET /api/incidents/{id}                              timeline (alerts, crash-zone RFID,
 *                                                      sightings + vision matches)
 * GET /api/incidents/{id}/evidence/{evidence_id}       streams one evidence JPEG
 */

import apiClient, { getApiBaseUrl } from './apiClient'

export type VisionStatus =
  | 'VISION_CONFIRMED'
  | 'PROBABLE_MATCH'
  | 'NOT_CONFIRMED'
  | 'NO_PLATE_VISIBLE'
  | 'PLATE_TOO_SMALL'

export interface IncidentSummary {
  id: string
  run_id: string | null
  status: string
  severity: string
  crash_ts_sim: number | null
  crash_frame: number | null
  crash_junction: string | null
  created_at: string | null
  plates: string[]
  vehicle_count: number
  sighting_count: number
  vision_confirmed: number
  crash_type?: string
  crashed_vehicle_count?: number
  hit_and_run?: boolean
  left_scene_plates?: string[]
}

export interface EvidenceFileRef {
  id: string
  kind: 'annotated_frame' | 'plate_crop' | 'crash_frame' | string
  url: string
  sha256: string
  width: number | null
  height: number | null
  score: number | null
  frame_ts?: number | null
  junction_id?: string | null
  /** wall clock (ISO) when the image was saved */
  created_at?: string | null
}

export interface VisionMatchView {
  id: string
  status: VisionStatus
  rfid_plate: string | null
  anpr_plate: string | null
  anpr_confidence: number | null
  edit_distance: number | null
  camera_id: string | null
  best_frame_ts: number | null
  time_delta_s: number | null
  frames_used: number | null
  all_plates_seen: string[] | null
  anpr_model: string | null
  evidence: EvidenceFileRef[]
}

export interface SightingView {
  id: string
  epc: string
  plate_norm: string | null
  junction_id: string
  reader_id: string | null
  first_seen_ts: number
  last_seen_ts: number
  /** wall clock (ISO) when the tag was first read at this junction */
  seen_at?: string | null
  report_count: number
  tag_seen_count: number
  peak_rssi_dbm: number | null
  closed: boolean
  vision: VisionMatchView | null
}

export interface IncidentDetail {
  incident: IncidentSummary & Record<string, unknown>
  evidence_url_template: string
  alerts: {
    alert_id: string
    source: string
    status: string | null
    timestamp_sim: number | null
    frame: number | null
  }[]
  involved_vehicles: {
    plate_norm: string
    plate_display: string | null
    epc: string | null
    role: string
    registry: string
    /** Member 1 reported this vehicle escaping the crash */
    fled?: boolean
    /** citizen who registered the plate (null when nobody has) */
    owner_name?: string | null
  }[]
  crash_zone_rfid: {
    epc: string
    plate_norm: string | null
    junction_id: string
    reader_id: string | null
    first_seen_ts: number
    last_seen_ts: number
    report_count: number
    tag_seen_count: number
    peak_rssi_dbm: number | null
    role: string
  }[]
  sightings: SightingView[]
  crash_frames?: EvidenceFileRef[]
  /** ONE primary evidence card per junction on the suspect's route (newer backends). */
  best_evidence_by_junction?: JunctionEvidence[]
  /** The vehicle(s) that fled the crash, with the overall plate verdict. */
  fleeing_vehicles?: FleeingVehicle[]
  /** World (x, y) of every junction, for the tracking map. */
  junction_positions?: Record<string, JunctionPosition>
}

export interface JunctionPosition {
  x: number
  y: number
  label: string
}

/** Strict partial plate of the suspect at a junction where the camera did not
 *  confirm the RFID plate. Unread characters: _ one, * 0-2, + 0-1. */
export interface PartialPlate {
  pattern: string
  alternative_patterns: string[]
  is_complete: boolean
  confidence: number | null
  frames_used: number | null
  candidates: { plate: string; score: number; epc?: string; source: string }[]
}

export interface FleeingVehicle {
  plate_norm: string
  plate_display: string | null
  state_name: string | null
  epc: string | null
  sim_vehicle_id: string | null
  /** why this vehicle is the suspect (escape report, or RFID read elsewhere) */
  basis: string
  junctions: string[]
  final_plate_read: string | null
  final_plate_read_display: string | null
  overall_status: VisionStatus | null
  overall_reason: string | null
}

/** A plate read that sat on the suspect vehicle (a supporting candidate). */
export interface CandidateRead {
  ts: number | null
  raw: string | null
  corrected: string | null
  valid: boolean | null
  mean_conf: number | null
  width_px: number | null
  det_confidence: number | null
}

export interface JunctionEvidence {
  junction_id: string
  epc: string
  suspect_vehicle_id: string | null
  rfid_plate: string | null
  rfid_plate_display: string | null
  sighting_ids: string[]
  first_seen_ts: number
  last_seen_ts: number
  status: VisionStatus | null
  rule_assisted: boolean
  match_reason: string | null
  anpr_plate: string | null
  anpr_plate_display: string | null
  anpr_confidence: number | null
  primary: {
    image: EvidenceFileRef
    raw_frame: EvidenceFileRef | null
    plate_crop: EvidenceFileRef | null
    score: number | null
    frame_ts: number | null
    read_text: string | null
    read_text_display: string | null
    read_valid: boolean
    read_confidence: number | null
    /** true: rows from before primary evidence existed (newest hero shown) */
    legacy: boolean
  } | null
  supporting: {
    frames: number
    images: EvidenceFileRef[]
    candidate_reads: number
    candidates: CandidateRead[]
  }
  partial_plate?: PartialPlate | null
}

export async function listIncidents(limit = 50): Promise<IncidentSummary[]> {
  const { data } = await apiClient.get<{ incidents: IncidentSummary[] }>('/incidents', {
    params: { limit },
  })
  return data.incidents
}

export async function getIncident(incidentId: string): Promise<IncidentDetail> {
  const { data } = await apiClient.get<IncidentDetail>(`/incidents/${incidentId}`)
  return data
}

/** Citizen who registered the plate, with the vehicle details on file. */
export interface RegisteredOwner {
  name: string
  phone: string | null
  email: string | null
  vehicle: {
    make: string | null
    model: string | null
    year: number | null
    color: string | null
    vehicle_type: string | null
    fastag_id: string | null
  }
}

export interface JunctionVehicle {
  plate_norm: string
  plate_display: string | null
  state_name: string | null
  epc: string | null
  fled: boolean
  basis: string | null
  sightings: SightingView[]
  /** the ANPR evidence card of this vehicle at this junction */
  evidence: JunctionEvidence | null
  /** the vehicle cropped from its best frame here (protected URL) */
  vehicle_image: string | null
  owner: RegisteredOwner | null
}

export interface JunctionDetail {
  incident: IncidentSummary & Record<string, unknown>
  junction: { id: string; label: string; is_crash: boolean }
  crash_frames: EvidenceFileRef[]
  vehicles: JunctionVehicle[]
}

/** One junction of the crash route: the fled vehicle's evidence there and its owner. */
export async function getJunction(incidentId: string, junctionId: string): Promise<JunctionDetail> {
  const { data } = await apiClient.get<JunctionDetail>(`/incidents/${incidentId}/junctions/${junctionId}`)
  return data
}

/** Evidence URLs come back as "/api/incidents/..."; resolve them against the API origin. */
export function evidenceSrc(url: string): string {
  if (/^https?:\/\//.test(url)) return url
  const origin = getApiBaseUrl().replace(/\/api\/?$/, '')
  return `${origin}${url}`
}

/** Portal push events for this feature (same channel as crash alerts). */
export const INCIDENT_EVIDENCE_EVENTS = [
  'incident_created',
  'watchlist_rfid_hit',
  'vision_match_result',
  'suspect_identified',
] as const
