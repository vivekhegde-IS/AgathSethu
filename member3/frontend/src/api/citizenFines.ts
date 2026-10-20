/**
 * AGHAT SETHU — Citizen Fines API
 *
 * Fines issued from routine-violation videos to the logged-in citizen, read
 * from the same `fines` table the authority video pipeline writes to.
 * Uses the shared apiClient, so the existing citizen JWT is attached.
 *
 * Endpoints:
 *   GET /citizen/fines                   → own fines + vehicles + total unpaid
 *   GET /citizen/fines/{id}/snapshot     → captured violation frame (jpeg)
 *   GET /citizen/fines/{id}/clip         → proof clip (webm)
 */

import apiClient from './apiClient'

export interface CitizenFine {
  id: number
  detected_at: string | null
  number_plate: string
  violation_type: string
  video_name: string | null
  fine_amount: number
  status: 'Unpaid' | 'Paid' | string
  plate_status: string | null
  evidence_time_s: number | null
  image_path: string | null
  image_url: string | null
  clip_url: string | null
  /** Set once the fine is paid (receipt from fine_payments). */
  payment: { id: number; fine_id: number; amount: number; method: string; reference: string; paid_at: string | null } | null
}

export interface CitizenVehicle {
  id: string
  plate_number: string
  vehicle_type: string | null
  unpaid_count: number
}

export interface CitizenFinesResponse {
  total_unpaid: number
  unpaid_count: number
  vehicles: CitizenVehicle[]
  fines: CitizenFine[]
}

export async function fetchMyFines(): Promise<CitizenFinesResponse> {
  // The backend sends Cache-Control: no-store; the timestamp also defeats any proxy cache.
  const response = await apiClient.get<CitizenFinesResponse>('/citizen/fines', { params: { _: Date.now() } })
  return response.data
}

/**
 * Evidence needs the bearer token, which <img>/<video> cannot send, so it is
 * fetched as a blob. The caller revokes the returned object URL.
 */
export async function fetchFineEvidenceUrl(fineId: number, kind: 'snapshot' | 'clip'): Promise<string> {
  const response = await apiClient.get(`/citizen/fines/${fineId}/${kind}`, {
    responseType: 'blob',
    timeout: 60_000,
  })
  return URL.createObjectURL(response.data)
}
