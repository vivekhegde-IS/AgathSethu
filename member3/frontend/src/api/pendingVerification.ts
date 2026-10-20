/**
 * AGHAT SETHU — Partial-plate violations (authority only)
 *
 *   GET /authority/pending-verifications            → partial plates awaiting verification
 *   GET /authority/pending-verifications/{id}/snapshot → captured violation frame (jpeg)
 */

import apiClient from './apiClient'

export interface PartialSegment {
  pattern: string
  value: string | null
  length: [number, number]
  known_length: boolean
  char_type: 'letter' | 'digit'
  allowed_chars: string
  allowed_values?: string[]
  chars?: { char: string | null; raw: string; conf: number }[]
}

export interface PendingVerificationItem {
  id: number
  detected_at: string | null
  video_name: string | null
  track_id: string | null
  violation_type: string
  partial_pattern: string
  alternative_patterns: string[]
  regex: string
  is_complete: boolean
  confidence: number | null
  pipeline_plate_status: string | null
  segments: Record<string, PartialSegment> | null
  raw_ocr_text: string | null
  corrections: string[]
  candidates: { plate: string; score: number; vehicle_id: string }[]
  evidence_time_s: number | null
  status: string
  image_url: string | null
}

export async function fetchPendingVerifications(status = 'pending'): Promise<PendingVerificationItem[]> {
  const response = await apiClient.get<{ items: PendingVerificationItem[] }>('/authority/pending-verifications', {
    params: { status, _: Date.now() },
  })
  return response.data.items
}

export async function fetchPendingSnapshotUrl(id: number): Promise<string> {
  const response = await apiClient.get(`/authority/pending-verifications/${id}/snapshot`, {
    responseType: 'blob',
    timeout: 60_000,
  })
  return URL.createObjectURL(response.data)
}
