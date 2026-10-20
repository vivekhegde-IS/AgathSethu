/**
 * Live CARLA plate detections, read with the strict rule-based partial ANPR:
 * unread characters stay marked (_ one, * 0-2, + 0-1), nothing is guessed.
 *
 * Loads GET /anpr/live/detections on open, then applies live_plate_detection
 * events from the live-camera socket (one card per tracked plate).
 */

import { useEffect, useState } from 'react'
import apiClient, { getApiBaseUrl } from '@api/apiClient'
import { subscribeToLiveCameraMessages } from '@services/websocket/liveCamerasSocket'

interface Candidate {
  plate: string
  score: number
  source: 'rfid_registry' | 'vehicles' | string
  epc?: string
}

interface PartialPlate {
  partial_pattern: string
  alternative_patterns: string[]
  regex: string
  is_complete: boolean
  confidence: number | null
  conflicts: unknown[]
  frames_used: (number | null)[]
  raw_ocr_text: string
}

interface LivePlateDetection {
  type: 'live_plate_detection'
  detection_id: string
  vehicle_id: number
  junction_id: string
  frames_seen: number
  evidence_time_s: number | null
  image: string | null
  partial_pattern: string | null
  partial_plate: PartialPlate | null
  candidates: Candidate[]
  updated_at: string
}

const API_ORIGIN = getApiBaseUrl().replace(/\/api\/?$/, '')

const isUnknown = (ch: string) => '_*+'.includes(ch)

function Pattern({ value }: { value: string }) {
  return (
    <span style={{ fontFamily: 'monospace', fontSize: '18px', fontWeight: 700, letterSpacing: '0.12em' }}>
      {value.split('').map((ch, i) => (
        <span key={i} style={{ color: isUnknown(ch) ? '#fbbf24' : '#f9fafb' }}>
          {ch}
        </span>
      ))}
    </span>
  )
}

const chip = (background: string, color: string, border: string) => ({
  display: 'inline-block',
  padding: '2px 8px',
  borderRadius: '6px',
  background,
  color,
  border: `1px solid ${border}`,
  fontSize: '11px',
  fontFamily: 'monospace',
})

export function LivePlateDetections() {
  const [items, setItems] = useState<Record<string, LivePlateDetection>>({})
  const [error, setError] = useState('')
  const [fullImage, setFullImage] = useState<string | null>(null)

  useEffect(() => {
    apiClient
      .get<{ detections: LivePlateDetection[] }>('/anpr/live/detections', { params: { _: Date.now() } })
      .then((response) =>
        setItems((previous) => {
          const next = { ...previous }
          response.data.detections.forEach((d) => {
            if (!next[d.detection_id] || next[d.detection_id].updated_at < d.updated_at) next[d.detection_id] = d
          })
          return next
        }),
      )
      .catch(() => setError('Could not load live plate detections.'))

    return subscribeToLiveCameraMessages((message) => {
      if (message.type !== 'live_plate_detection') return
      const detection = message as unknown as LivePlateDetection
      setItems((previous) => ({ ...previous, [detection.detection_id]: detection }))
    })
  }, [])

  const detections = Object.values(items).sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))

  return (
    <div style={{ marginTop: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '10px' }}>
        <h3 style={{ margin: 0, color: '#f9fafb', fontSize: '16px', fontWeight: 700 }}>Live Plate Detections</h3>
        <span style={{ color: '#6b7280', fontSize: '12px' }}>
          Strict rule-based reading — <span style={{ color: '#fbbf24' }}>_</span> one unknown ·{' '}
          <span style={{ color: '#fbbf24' }}>*</span> 0–2 unknown · <span style={{ color: '#fbbf24' }}>+</span> 0–1
          unknown · never guessed
        </span>
      </div>

      {error && <div style={{ color: '#fca5a5', fontSize: '12px', marginBottom: '8px' }}>{error}</div>}
      {detections.length === 0 && !error && (
        <div style={{ color: '#6b7280', fontSize: '13px', padding: '12px', border: '1px dashed #374151', borderRadius: '10px' }}>
          No plates detected yet on the live feed.
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: '14px' }}>
        {detections.map((d) => {
          const p = d.partial_plate
          const image = d.image ? `${API_ORIGIN}${d.image}` : null
          return (
            <div key={d.detection_id} style={{ background: '#111827', border: '1px solid #374151', borderRadius: '12px', overflow: 'hidden' }}>
              {image && (
                <img
                  src={image}
                  alt={`${d.junction_id} vehicle ${d.vehicle_id}`}
                  onClick={() => setFullImage(image)}
                  style={{ width: '100%', display: 'block', cursor: 'zoom-in' }}
                />
              )}
              <div style={{ padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                  {d.partial_pattern ? <Pattern value={d.partial_pattern} /> : <span style={{ color: '#9ca3af' }}>—</span>}
                  {p &&
                    (p.is_complete ? (
                      <span style={chip('rgba(16,185,129,0.12)', '#6ee7b7', '#065f46')}>COMPLETE · {p.frames_used.length} read(s)</span>
                    ) : (
                      <span style={chip('rgba(251,191,36,0.10)', '#fcd34d', '#92400e')}>PARTIAL · {p.frames_used.length} read(s)</span>
                    ))}
                  {p && p.conflicts.length > 0 && (
                    <span style={chip('rgba(239,68,68,0.10)', '#fca5a5', '#7f1d1d')}>{p.conflicts.length} frame conflict(s)</span>
                  )}
                </div>
                <div style={{ color: '#9ca3af', fontSize: '11px', fontFamily: 'monospace' }}>
                  {d.junction_id} · vehicle {d.vehicle_id} · seen in {d.frames_seen} frames
                  {d.evidence_time_s != null && ` · t=${d.evidence_time_s}s`}
                  {p?.raw_ocr_text && ` · raw OCR "${p.raw_ocr_text}"`}
                </div>
                {p && p.alternative_patterns.length > 0 && (
                  <div style={{ color: '#9ca3af', fontSize: '11px', fontFamily: 'monospace' }}>
                    also possible: {p.alternative_patterns.join(' · ')}
                  </div>
                )}
                {p && (
                  <div style={{ color: '#6b7280', fontSize: '10px', fontFamily: 'monospace', wordBreak: 'break-all' }}>
                    regex {p.regex}
                  </div>
                )}
                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
                  <span style={{ color: '#9ca3af', fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                    Matches ({d.candidates.length})
                  </span>
                  {d.candidates.length === 0 && <span style={{ color: '#6b7280', fontSize: '11px' }}>none registered</span>}
                  {d.candidates.slice(0, 8).map((c) => (
                    <span key={`${c.source}-${c.plate}`} style={chip('#0b1220', '#67e8f9', '#164e63')} title={c.epc ? `EPC ${c.epc}` : c.source}>
                      {c.plate} {c.source === 'rfid_registry' ? 'RFID' : 'REG'} {c.score.toFixed(2)}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {fullImage && (
        <div
          onClick={() => setFullImage(null)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 60, cursor: 'zoom-out' }}
        >
          <img src={fullImage} alt="Live plate evidence (full size)" style={{ maxWidth: '92vw', maxHeight: '92vh', borderRadius: '8px' }} />
        </div>
      )}
    </div>
  )
}
