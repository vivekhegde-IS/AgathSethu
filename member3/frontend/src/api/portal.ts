/**
 * AGHAT SETHU — Portal API (authority operations + citizen account)
 *
 * Authority:
 *   GET  /authority/summary                home dashboard counts + latest crash frame
 *   GET  /authority/fines                  fines list + revenue views
 *   GET  /cameras/status                   camera server health (frames arriving)
 *   GET  /incidents/board?view=radar|records
 *   POST /incidents/{id}/resolve           {password, note}
 * Citizen:
 *   POST /citizen/fines/{id}/pay           {method}
 *   GET  /citizen/payments
 *   GET  /citizen/notifications            (+ /read-all, /{id}/read)
 *   GET  /citizen/incidents/{id}
 * Both:
 *   PATCH /auth/me                         {full_name, email, phone}
 */

import type { CaseView, CrashResponseView } from './live'
import apiClient from './apiClient'
import type { UserResponse } from './auth'

// ── shared ───────────────────────────────────────────────────────────────────────
/** Evidence URLs from the API start with /api; apiClient's base already ends in /api. */
export function apiPath(url: string): string {
  return url.replace(/^\/api(?=\/)/, '')
}

/** Protected images cannot be loaded by <img src>; fetch them with the token. */
export async function fetchProtectedBlobUrl(url: string): Promise<string> {
  const response = await apiClient.get(apiPath(url), { responseType: 'blob', timeout: 60_000 })
  return URL.createObjectURL(response.data)
}

export function errorMessage(err: unknown, fallback = 'Something went wrong. Please try again.'): string {
  const e = err as { response?: { data?: { detail?: unknown } }; message?: string }
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { msg?: string }
    if (first?.msg) return first.msg.replace(/^Value error, /, '')
  }
  return fallback
}

const IST_FORMAT = new Intl.DateTimeFormat('en-IN', {
  timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric',
  hour: '2-digit', minute: '2-digit', hour12: true,
})
const IST_TIME = new Intl.DateTimeFormat('en-IN', {
  timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true,
})
const IST_DATE = new Intl.DateTimeFormat('en-IN', {
  timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric',
})

/** Wall-clock date and time in IST, e.g. "18 Oct 2026, 11:42 pm". */
export function formatIst(iso: string | null | undefined): string {
  return iso ? IST_FORMAT.format(new Date(iso)) : '—'
}

/** Wall-clock time of day in IST with seconds, e.g. "11:42:07 pm". */
export function formatIstTime(iso: string | null | undefined): string {
  return iso ? IST_TIME.format(new Date(iso)) : '—'
}

export function formatIstDate(iso: string | null | undefined): string {
  return iso ? IST_DATE.format(new Date(iso)) : '—'
}

export function rupees(amount: number | null | undefined): string {
  return `₹${(amount ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

// ── authority: incidents ─────────────────────────────────────────────────────────
export interface BoardIncident {
  id: string
  reference: string
  location: string
  crash_junction: string | null
  created_at: string | null
  status: string
  resolved: boolean
  resolved_at: string | null
  resolved_by_name: string | null
  resolution_note: string | null
  /** how it was closed: the owners' codes, a super-admin code, or null (owners resolved it themselves) */
  resolved_with?: 'owner' | 'override' | null
  /** closed as a false alarm (status false_positive) */
  false_alarm?: boolean
  /** owners' "are you safe?" answers, newest first, and the case outcome from them */
  citizen_responses?: CrashResponseView[]
  latest_citizen_response?: CrashResponseView | null
  case?: CaseView | null
  involved_plates: string[]
  involved_plates_display: (string | null)[]
  camera_stream: string | null
  /** true only for an unresolved crash of the run that is streaming right now */
  live_feed: boolean
  sighting_count: number
  vision_confirmed: number
  /** NETRA v1.8 crash type (see CrashTypeBadge) */
  crash_type?: string
  crashed_vehicle_count?: number
  hit_and_run?: boolean
  left_scene_plates?: string[]
}

export interface RadarBoard {
  day_start: string
  active: BoardIncident[]
  resolved_today: BoardIncident[]
}

export interface RecordsBoard {
  total: number
  page: number
  page_size: number
  items: BoardIncident[]
}

export async function fetchRadar(): Promise<RadarBoard> {
  return (await apiClient.get<RadarBoard>('/incidents/board', { params: { view: 'radar', _: Date.now() } })).data
}

/**
 * `date` (YYYY-MM-DD) limits the list to crashes on that IST calendar day; `q`
 * searches the incident ID (INC-xxxxxxxx, full or part) and the plates of the vehicles.
 */
export async function fetchRecords(
  status: 'all' | 'resolved' | 'unresolved',
  page: number,
  pageSize = 25,
  date?: string,
  q?: string,
) {
  return (await apiClient.get<RecordsBoard>('/incidents/board', {
    params: { view: 'records', status, page, page_size: pageSize, date: date || undefined, q: q || undefined, _: Date.now() },
  })).data
}

/** Resolving needs every alerted owner's 6-digit code, or one super-admin code. */
export async function resolveIncident(id: string, password: string, note: string, codes: string[]): Promise<BoardIncident> {
  return (await apiClient.post<BoardIncident>(`/incidents/${id}/resolve`, { password, note: note || null, codes })).data
}

export interface ResolutionRequest {
  id: number
  incident_ref: string
  status: 'requested' | 'issued' | 'used' | 'declined' | 'expired'
  reason: string | null
  requested_by_name: string | null
  requested_at: string | null
  issued_by_name: string | null
  issued_at: string | null
  expires_at: string | null
  used_at: string | null
  incident_id?: string | null
  reference?: string
  location?: string | null
  crash_at?: string | null
  /** only in the super admin's response when the code is generated */
  code?: string
}

export interface ResolutionStatus {
  incident_ref: string
  owners: { name: string | null; plates: string[]; code_valid: boolean; expires_at: string }[]
  owner_codes_possible: boolean
  request: ResolutionRequest | null
  locked_until: string | null
}

export async function getResolutionStatus(id: string): Promise<ResolutionStatus> {
  return (await apiClient.get<ResolutionStatus>(`/incidents/${id}/resolution-code`, { params: { _: Date.now() } })).data
}

export async function requestResolutionCode(id: string, reason: string): Promise<ResolutionRequest> {
  return (await apiClient.post<ResolutionRequest>(`/incidents/${id}/resolution-code/request`, { reason: reason || null })).data
}

// super admin
export async function getResolutionRequests() {
  return (await apiClient.get<{ items: ResolutionRequest[]; total: number }>('/admin/resolution-requests',
    { params: { _: Date.now() } })).data
}

export async function issueResolutionCode(requestId: number): Promise<ResolutionRequest> {
  return (await apiClient.post<ResolutionRequest>(`/admin/resolution-requests/${requestId}/issue`)).data
}

export async function declineResolutionCode(requestId: number): Promise<ResolutionRequest> {
  return (await apiClient.post<ResolutionRequest>(`/admin/resolution-requests/${requestId}/decline`)).data
}

// ── authority: dashboard, fines, cameras ──────────────────────────────
export interface AuthoritySummary {
  crashes: { total: number; unresolved: number; today: number; resolved_today: number }
  violations: {
    total: number
    today: number
    /** the violation type charted per day (NO HELMET) */
    chart_type: string
    /** IST days, oldest first, empty days included */
    by_day: { date: string; count: number }[]
  }
  fines: { pending_count: number; pending_amount: number; paid_count: number; collected_amount: number }
  latest_crash_frame: {
    incident_id: string; reference: string; location: string; url: string; captured_at: string | null; kind: string
  } | null
  recent_incidents: { id: string; reference: string; location: string; created_at: string | null; resolved: boolean }[]
}

export async function fetchSummary(): Promise<AuthoritySummary> {
  return (await apiClient.get<AuthoritySummary>('/authority/summary', { params: { _: Date.now() } })).data
}

export interface FineRow {
  id: number
  number_plate: string
  violation_type: string
  fine_amount: number
  status: string
  detected_at: string | null
  paid_at: string | null
  reference: string | null
}

export interface FinesRevenue {
  totals: {
    issued_count: number; issued_amount: number; pending_count: number; pending_amount: number
    paid_count: number; collected_amount: number
  }
  monthly_revenue: { year: number; months: { month: number; payments: number; collected: number }[] }
  annual: {
    year: number; issued_count: number; issued_amount: number; collected_count: number
    collected_amount: number; pending_count: number; pending_amount: number
  }[]
  fines: { total: number; page: number; page_size: number; items: FineRow[] }
}

/**
 * `date` (YYYY-MM-DD) limits the challan list to fines issued on that IST day and
 * `plate` to plates containing it (spacing/case ignored); the totals are unaffected.
 */
export async function fetchFinesRevenue(
  status: string,
  page: number,
  year?: number,
  date?: string,
  plate?: string,
): Promise<FinesRevenue> {
  return (await apiClient.get<FinesRevenue>('/authority/fines', {
    params: { status, page, year, date: date || undefined, plate: plate || undefined, _: Date.now() },
  })).data
}

export interface CameraStatus {
  connected: boolean
  sender_attached: boolean
  stale_after_s: number
  cameras: { junction_id: string; camera_id: string | null; last_frame_age_s: number | null; connected: boolean }[]
}

export async function fetchCameraStatus(): Promise<CameraStatus> {
  return (await apiClient.get<CameraStatus>('/cameras/status', { params: { _: Date.now() }, timeout: 5_000 })).data
}

// ── citizen ──────────────────────────────────────────────────────────────────────
export interface PaymentRecord {
  id: number
  reference: string
  paid_at: string | null
  amount: number
  method: string
  fine_id: number
  number_plate: string
  violation_type: string
  detected_at: string | null
}

export async function payFine(fineId: number, method: 'upi' | 'card' | 'netbanking') {
  return (await apiClient.post<{ fine_id: number; status: string; payment: Omit<PaymentRecord, 'number_plate' | 'violation_type' | 'detected_at'> }>(
    `/citizen/fines/${fineId}/pay`, { method },
  )).data
}

export async function fetchPayments(): Promise<{ total_paid: number; payments: PaymentRecord[] }> {
  return (await apiClient.get('/citizen/payments', { params: { _: Date.now() } })).data
}

export interface CitizenNotification {
  id: string
  kind: 'crash_involvement' | 'fine_issued' | string
  title: string
  message: string
  incident_id: string | null
  fine_id: number | null
  plate_norm: string | null
  data: Record<string, unknown>
  read: boolean
  created_at: string | null
  /** crash notifications only: the owner's answer, null while unanswered */
  response?: CrashResponseView | null
}

export async function fetchNotifications(): Promise<{ unread: number; notifications: CitizenNotification[] }> {
  return (await apiClient.get('/citizen/notifications', { params: { _: Date.now() } })).data
}

export async function markNotificationRead(id: string) {
  return (await apiClient.post(`/citizen/notifications/${id}/read`)).data
}

export async function markAllNotificationsRead() {
  return (await apiClient.post('/citizen/notifications/read-all')).data
}

export interface CitizenIncident {
  id: string
  reference: string
  crash_at: string | null
  location: string
  status: string
  resolved_at: string | null
  your_vehicles: string[]
  involved_vehicles: string[]
  role_determined: boolean
  response?: CrashResponseView | null
  case?: CaseView | null
  /** the owner's code for the officer who attends; null once resolved or expired */
  resolution_code?: { code: string; expires_at: string; hint: string } | null
}

export async function fetchCitizenIncident(id: string): Promise<CitizenIncident> {
  return (await apiClient.get<CitizenIncident>(`/citizen/incidents/${id}`)).data
}

export async function updateProfile(data: { full_name: string; email: string; phone: string | null }) {
  return (await apiClient.patch<UserResponse>('/auth/me', data)).data
}
