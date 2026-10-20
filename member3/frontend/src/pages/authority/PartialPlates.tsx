import React, { useCallback, useEffect, useState } from 'react'
import { Card, Badge, Button, Modal, Spinner } from '@components/ui'
import {
  PendingVerificationItem,
  fetchPendingSnapshotUrl,
  fetchPendingVerifications,
} from '@api/pendingVerification'

/** Captured frame, loaded with the authority JWT. */
const Snapshot: React.FC<{ id: number; onOpen: (url: string) => void }> = ({ id, onOpen }) => {
  const [url, setUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let objectUrl: string | null = null
    let cancelled = false
    fetchPendingSnapshotUrl(id)
      .then((u) => {
        objectUrl = u
        if (cancelled) URL.revokeObjectURL(u)
        else setUrl(u)
      })
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [id])

  if (failed) return <span className="text-[10px] text-slate-500 font-mono">UNAVAILABLE</span>
  if (!url) return <Spinner />
  return (
    <button type="button" onClick={() => onOpen(url)} title="Click to enlarge">
      <img src={url} alt="Captured violation frame" className="w-56 rounded border border-slate-300 hover:border-cyan-400" />
    </button>
  )
}

/** The pattern with unknown tokens highlighted: _ (one), * (0-2), + (0-1). */
const Pattern: React.FC<{ value: string }> = ({ value }) => (
  <span className="font-mono text-lg font-bold tracking-widest">
    {value.split('').map((ch, i) => (
      <span key={i} className={'_*+'.includes(ch) ? 'text-amber-700' : 'text-slate-900'}>
        {ch}
      </span>
    ))}
  </span>
)

export const PartialPlatesPage: React.FC = () => {
  const [items, setItems] = useState<PendingVerificationItem[] | null>(null)
  const [error, setError] = useState('')
  const [fullImage, setFullImage] = useState<string | null>(null)

  const load = useCallback(() => {
    setError('')
    fetchPendingVerifications()
      .then(setItems)
      .catch(() => setError('Could not load partial-plate violations.'))
  }, [])

  useEffect(load, [load])

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold text-blue-950">Partial Plates — Pending Verification</h2>
          <p className="text-sm text-slate-600 mt-1">
            Violations whose number plate was only partly readable. Nobody has been fined; unread characters are
            marked, never guessed: <span className="text-amber-700">_</span> one unknown,{' '}
            <span className="text-amber-700">*</span> 0–2 unknown, <span className="text-amber-700">+</span> 0–1
            unknown. Awaiting RFID fusion or manual review.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={load}>
          Refresh
        </Button>
      </div>

      {error && <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded">{error}</div>}
      {!items && !error && <Spinner />}
      {items && items.length === 0 && (
        <Card>
          <p className="text-sm text-slate-600">No partial-plate violations are pending.</p>
        </Card>
      )}

      {items?.map((item) => (
        <Card key={item.id}>
          <div className="flex flex-col lg:flex-row gap-5">
            {item.image_url ? <Snapshot id={item.id} onOpen={setFullImage} /> : null}
            <div className="flex-1 space-y-3 min-w-0">
              <div className="flex flex-wrap items-center gap-3">
                <Pattern value={item.partial_pattern} />
                <Badge variant="danger" size="sm">{item.violation_type}</Badge>
                <Badge variant="warning" size="sm">PENDING VERIFICATION</Badge>
                {item.confidence != null && (
                  <span className="text-[11px] font-mono text-slate-600">confidence {item.confidence.toFixed(2)}</span>
                )}
              </div>
              <p className="text-xs font-mono text-slate-600">
                {item.detected_at ? new Date(item.detected_at).toLocaleString() : '—'} · {item.video_name ?? '—'}
                {item.evidence_time_s != null && ` @ ${item.evidence_time_s}s`} · track {item.track_id ?? '—'} · raw
                OCR "{item.raw_ocr_text ?? ''}"
              </p>
              {item.segments && (
                <div className="flex flex-wrap gap-2">
                  {Object.entries(item.segments).map(([name, seg]) => (
                    <div key={name} className="px-2 py-1 bg-slate-50 border border-slate-200 rounded text-[11px] font-mono">
                      <span className="text-slate-500 uppercase">{name}</span>{' '}
                      <span className="text-slate-900">{seg.pattern || '∅'}</span>{' '}
                      <span className="text-slate-500">
                        {seg.char_type} · {seg.length[0] === seg.length[1] ? seg.length[0] : `${seg.length[0]}-${seg.length[1]}`}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {item.alternative_patterns.length > 0 && (
                <p className="text-[11px] font-mono text-slate-500">
                  Other possible layouts: {item.alternative_patterns.join(' · ')}
                </p>
              )}
              <p className="text-[11px] font-mono text-slate-500 break-all">regex {item.regex}</p>
              {item.corrections.length > 0 && (
                <p className="text-[11px] font-mono text-slate-500">Rule notes: {item.corrections.join(' | ')}</p>
              )}
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-600 mb-1">
                  Registered plates matching the pattern ({item.candidates.length})
                </p>
                {item.candidates.length === 0 ? (
                  <p className="text-xs text-slate-500 font-mono">No registered vehicle matches.</p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {item.candidates.slice(0, 30).map((c) => (
                      <span key={c.plate} className="px-2 py-1 bg-slate-50 border border-cyan-200 rounded text-xs font-mono text-blue-800">
                        {c.plate} <span className="text-slate-500">{c.score.toFixed(2)}</span>
                      </span>
                    ))}
                    {item.candidates.length > 30 && (
                      <span className="text-xs text-slate-500 font-mono">+{item.candidates.length - 30} more</span>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        </Card>
      ))}

      <Modal isOpen={fullImage !== null} onClose={() => setFullImage(null)} title="Captured Violation Frame" maxWidth="4xl">
        {fullImage && <img src={fullImage} alt="Captured violation frame (full size)" className="w-full h-auto rounded" />}
      </Modal>
    </div>
  )
}
