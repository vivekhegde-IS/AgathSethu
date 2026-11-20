/**
 * AGHAT SETHU — Live dashboards (/me, /authority) and Google sign-in API.
 */

import apiClient from './apiClient'
import type { UserResponse } from './auth'

export interface VehicleView {
  id: string
  letter: string | null
  plate: string
  plate_norm: string
  state: string | null
  rfid_epc: string | null
  owner_name?: string
  owner_user_id?: string
}

export type FineState = 'issued' | 'paid' | 'disputed'

export interface FineView {
  id: number
  vehicle_id: string | null
  letter: string | null
  plate: string
  amount: number
  reason: string
  location: string | null
  timestamp: string | null
  status: FineState
  dispute_reason: string | null
  disputed_at: string | null
  owner_name?: string
}

export interface NotificationView {
  id: string
  kind: string
  type: string
  title: string
  message: string
  plate_norm: string | null
  data: Record<string, unknown>
  read: boolean
  created_at: string | null
}

export interface SmsView {
  id: number
  body: string
  to_number: string | null
  provider: string
  status: string
  read: boolean
  created_at: string | null
}

export type CrashAnswer = 'accident' | 'not_serious' | 'false_alarm'

/** An owner's answer to "are you safe?" (mobile app or website). */
export interface CrashResponseView {
  id: number
  incident_id: string
  incident_ref: string
  ref_kind: 'crash' | 'incident'
  response: CrashAnswer
  accident_occurred: boolean
  label: string
  note: string | null
  channel: 'app' | 'web'
  responded_at: string | null
  review_status: 'pending' | 'accepted' | 'rejected' | null
  review_note: string | null
  reviewed_at: string | null
  // authority only
  owner_name?: string | null
  owner_phone?: string | null
  plate?: string | null
  letter?: string | null
  case?: CaseView | null
}

/** A crash's outcome from its owners' answers (null until someone answers). */
export interface CaseView {
  incident_ref: string
  outcome: 'waiting' | 'resolved' | 'not_resolved'
  reason_code: 'all_minor' | 'accident' | 'no_answer' | 'authority' | null
  reason: string | null
  automatic: boolean
  deadline_at: string | null
  decided_at: string | null
  vehicles: { plate: string; answer: CrashAnswer | null }[]
}

export interface CrashReportView {
  id: number
  incident_key: string
  status: string | null
  source: string
  location: string | null
  timestamp_sim: string | null
  created_at: string | null
  vehicle: VehicleView | null
  owner_response?: CrashResponseView | null
  case?: CaseView | null
  // authority only
  alert_id?: string | null
  decision_route?: string | null
  decision_route_label?: string | null
  partner?: VehicleView | null
}

export interface ReviewView {
  id: number
  incident_key: string
  kind: 'partner' | 'hit_and_run'
  status: 'pending' | 'confirmed' | 'rejected'
  decision_route: string | null
  decision_route_label: string | null
  accused: VehicleView | null
  struck: VehicleView | null
  evidence: Record<string, unknown>
  decision_note: string | null
  decided_at: string | null
  created_at: string | null
}

export interface OwnerOverview {
  user: { id: string; username: string | null; full_name: string; phone: string | null
    google_linked: boolean; google_email: string | null }
  vehicles: VehicleView[]
  fines: FineView[]
  notifications: NotificationView[]
  unread: number
  sms: SmsView[]
  sms_unread: number
  crashes: CrashReportView[]
}

export interface AuthorityLive {
  fleet: VehicleView[]
  fines: FineView[]
  crashes: CrashReportView[]
  reviews: ReviewView[]
  pending_reviews: number
  responses: CrashResponseView[]
  pending_responses: number
}

export type LiveEventType =
  | 'fine.issued' | 'fine.updated' | 'crash.detected' | 'crash.partner_named'
  | 'hit_and_run.detected' | 'notification.created' | 'review.updated'
  | 'crash.response' | 'crash.response_reviewed' | 'crash.case_updated'

export interface LiveEvent {
  type: LiveEventType
  at: string
  data: {
    fine?: FineView
    report?: CrashReportView
    review?: ReviewView
    notification?: NotificationView
    sms?: SmsView
    response?: CrashResponseView
    case?: CaseView | null
  }
}

// ── owner ─────────────────────────────────────────────────────────────────────────
export const getOwnerOverview = async () => (await apiClient.get<OwnerOverview>('/me/overview')).data
export const disputeFine = async (fineId: number, reason: string) =>
  (await apiClient.post<FineView>(`/me/fines/${fineId}/dispute`, { reason })).data
export const payFine = async (fineId: number) =>
  (await apiClient.post(`/citizen/fines/${fineId}/pay`, { method: 'upi' })).data
export const markSmsRead = async () => (await apiClient.post('/me/sms/read-all')).data
export const markNotificationsRead = async () => (await apiClient.post('/citizen/notifications/read-all')).data
/** Same endpoint the mobile app uses; `ref` is the notification's incident_id (CR-... or a UUID). */
export const answerCrash = async (ref: string, response: CrashAnswer, note?: string) =>
  (await apiClient.post<CrashResponseView>(`/citizen/incidents/${encodeURIComponent(ref)}/confirm`,
    { response, note: note || null, channel: 'web' })).data

// ── authority ─────────────────────────────────────────────────────────────────────
export const getAuthorityLive = async () => (await apiClient.get<AuthorityLive>('/authority/live')).data
export const issueFine = async (body: { vehicle: string; amount: number; reason: string; location?: string }) =>
  (await apiClient.post<FineView>('/authority/fines', body)).data
export const upholdFine = async (fineId: number) =>
  (await apiClient.post<FineView>(`/authority/fines/${fineId}/uphold`)).data
export const decideReview = async (reviewId: number, confirm: boolean, note?: string) =>
  (await apiClient.post<ReviewView>(`/authority/review/${reviewId}/${confirm ? 'confirm' : 'reject'}`,
    { note: note || null })).data

export const decideCrashAnswer = async (responseId: number, accept: boolean, note?: string) =>
  (await apiClient.post<CrashResponseView>(
    `/authority/crash-responses/${responseId}/${accept ? 'accept' : 'reject'}`, { note: note || null })).data

// ── Google sign-in (owners only) ──────────────────────────────────────────────────
const TAB_KEY = 'aghat_google_tab_nonce'

function newTabNonce(): string {
  const bytes = new Uint8Array(24)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

export const getGoogleConfig = async () =>
  (await apiClient.get<{ enabled: boolean }>('/auth/google/config')).data

/** Starts Google sign-in / linking IN THIS TAB. The tab nonce stays in this
 *  tab's sessionStorage, so only this tab can redeem the result. */
export async function startGoogle(purpose: 'login' | 'link'): Promise<void> {
  const tabNonce = newTabNonce()
  sessionStorage.setItem(TAB_KEY, tabNonce)
  const { data } = await apiClient.post<{ authorization_url: string }>('/auth/google/start',
    { purpose, tab_nonce: tabNonce })
  window.location.assign(data.authorization_url)
}

export async function exchangeGoogleHandoff(handoff: string) {
  const tabNonce = sessionStorage.getItem(TAB_KEY) ?? ''
  sessionStorage.removeItem(TAB_KEY)
  const { data } = await apiClient.post<
    { access_token: string; token_type: string; user: UserResponse } | { linked: true; google_email: string }
  >('/auth/google/exchange', { handoff, tab_nonce: tabNonce.padEnd(16, '-') })
  return data
}

export const unlinkGoogle = async () => (await apiClient.post('/auth/google/unlink')).data
