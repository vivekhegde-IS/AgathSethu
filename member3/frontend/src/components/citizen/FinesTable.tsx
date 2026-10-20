/**
 * Real fines table for the citizen portal: every row comes from GET
 * /citizen/fines, every image/clip is the evidence captured from the
 * uploaded video for that fine.
 */

import React, { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Spinner } from '@components/ui'
import { CitizenFine, CitizenFinesResponse, fetchFineEvidenceUrl, fetchMyFines } from '@api/citizenFines'
import { formatIst } from '@api/portal'

export const rupees = (amount: number) => `₹${amount.toLocaleString('en-IN')}`

/** Loads the citizen's fines on mount (never cached; call reload() to refresh). */
export function useMyFines() {
  const [data, setData] = useState<CitizenFinesResponse | null>(null)
  const [error, setError] = useState('')

  const reload = useCallback(() => {
    setError('')
    fetchMyFines()
      .then(setData)
      .catch(() => setError('Could not load your fines from the server. Please try again.'))
  }, [])

  useEffect(reload, [reload])
  return { data, error, reload }
}

/** Loads one piece of evidence as a blob URL (the endpoint needs the JWT). */
function useEvidenceUrl(fineId: number, kind: 'snapshot' | 'clip', enabled: boolean) {
  const [url, setUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!enabled) return
    let objectUrl: string | null = null
    let cancelled = false
    fetchFineEvidenceUrl(fineId, kind)
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
  }, [fineId, kind, enabled])

  return { url, failed }
}

const FineSnapshot: React.FC<{ fineId: number; onOpen: (url: string) => void }> = ({ fineId, onOpen }) => {
  const { url, failed } = useEvidenceUrl(fineId, 'snapshot', true)
  if (failed) return <span className="text-[10px] text-slate-500 font-mono">UNAVAILABLE</span>
  if (!url) return <Spinner />
  return (
    <button type="button" onClick={() => onOpen(url)} title="Click to view full screen" className="cursor-zoom-in">
      <img
        src={url}
        alt="Captured violation frame"
        className="h-20 w-32 object-cover rounded border border-slate-300 hover:border-blue-800 transition-colors"
      />
    </button>
  )
}

const FineClip: React.FC<{ fineId: number; onOpen: (url: string) => void }> = ({ fineId, onOpen }) => {
  const [requested, setRequested] = useState(false)
  const { url, failed } = useEvidenceUrl(fineId, 'clip', requested)
  // Open the viewer as soon as the clip has loaded after a click.
  useEffect(() => {
    if (requested && url) onOpen(url)
  }, [requested, url, onOpen])
  if (failed) return <span className="text-[10px] text-slate-500 font-mono">UNAVAILABLE</span>
  if (requested && !url) return <Spinner />
  return (
    <button
      type="button"
      onClick={() => (url ? onOpen(url) : setRequested(true))}
      className="text-[11px] font-mono text-blue-800 hover:underline"
    >
      ▶ PLAY CLIP
    </button>
  )
}

/** Full-screen viewer for a violation frame or clip. Esc, ✕ or a click outside closes it. */
const EvidenceViewer: React.FC<{ item: { kind: 'image' | 'video'; url: string }; onClose: () => void }> = ({
  item,
  onClose,
}) => {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
    }
  }, [onClose])

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={item.kind === 'image' ? 'Captured violation frame' : 'Violation video clip'}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 p-4"
      onClick={onClose}
    >
      <button
        type="button"
        onClick={onClose}
        aria-label="Close"
        className="absolute top-4 right-4 rounded-full bg-white/90 px-3 py-1.5 text-sm font-semibold text-slate-900 hover:bg-white"
      >
        ✕ Close
      </button>
      {item.kind === 'image' ? (
        <img
          src={item.url}
          alt="Captured violation frame (full size)"
          className="max-h-[92vh] max-w-[96vw] object-contain rounded"
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <video
          src={item.url}
          controls
          autoPlay
          muted
          className="max-h-[92vh] max-w-[96vw] rounded bg-black"
          onClick={(e) => e.stopPropagation()}
        />
      )}
    </div>
  )
}

const none = <span className="text-[10px] text-slate-500 font-mono">NONE</span>

export const FinesTable: React.FC<{ fines: CitizenFine[] }> = ({ fines }) => {
  const [viewing, setViewing] = useState<{ kind: 'image' | 'video'; url: string } | null>(null)
  const openImage = useCallback((url: string) => setViewing({ kind: 'image', url }), [])
  const openVideo = useCallback((url: string) => setViewing({ kind: 'video', url }), [])
  const closeViewer = useCallback(() => setViewing(null), [])

  if (fines.length === 0) {
    return (
      <div className="p-8 text-center text-slate-600 font-mono text-xs">
        ✓ No fines have been issued to your registered vehicles.
      </div>
    )
  }

  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead className="text-[10px] uppercase tracking-wider text-slate-600 border-b border-slate-300">
            <tr>
              <th className="py-2 pr-4">Captured Frame</th>
              <th className="py-2 pr-4">Date &amp; Time</th>
              <th className="py-2 pr-4">Vehicle</th>
              <th className="py-2 pr-4">Violation Type</th>
              <th className="py-2 pr-4">Video</th>
              <th className="py-2 pr-4">Fine Amount</th>
              <th className="py-2 pr-4">Status</th>
              <th className="py-2 pr-4">Clip</th>
              <th className="py-2">Action</th>
            </tr>
          </thead>
          <tbody>
            {fines.map((fine) => (
              <tr key={fine.id} className="border-b border-slate-200 text-slate-800 align-middle">
                <td className="py-3 pr-4">
                  {fine.image_url ? <FineSnapshot fineId={fine.id} onOpen={openImage} /> : none}
                </td>
                <td className="py-3 pr-4 text-xs font-mono whitespace-nowrap">
                  {formatIst(fine.detected_at)}
                </td>
                <td className="py-3 pr-4 font-mono font-bold text-slate-900">{fine.number_plate}</td>
                <td className="py-3 pr-4">
                  <Badge variant="danger" size="sm">{fine.violation_type}</Badge>
                </td>
                <td className="py-3 pr-4 text-xs">
                  {fine.video_name ?? '—'}
                  {fine.evidence_time_s != null && (
                    <span className="block text-[10px] text-slate-500 font-mono">@ {fine.evidence_time_s}s</span>
                  )}
                </td>
                <td className="py-3 pr-4 font-mono font-bold text-slate-900 whitespace-nowrap">
                  {rupees(fine.fine_amount)}
                </td>
                <td className="py-3 pr-4">
                  <Badge variant={fine.status === 'Paid' ? 'success' : 'danger'} size="sm">{fine.status}</Badge>
                </td>
                <td className="py-3 pr-4">{fine.clip_url ? <FineClip fineId={fine.id} onOpen={openVideo} /> : none}</td>
                <td className="py-3 whitespace-nowrap">
                  {fine.status === 'Paid' ? (
                    <span className="text-[11px] font-mono text-emerald-700">
                      Paid{fine.payment ? ` · ${fine.payment.reference}` : ''}
                    </span>
                  ) : (
                    <Link
                      to={`/citizen/payments/${fine.id}`}
                      className="inline-block rounded bg-aghat-blue px-3 py-1 text-xs font-semibold text-white hover:bg-blue-500"
                    >
                      Pay {rupees(fine.fine_amount)}
                    </Link>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {viewing && <EvidenceViewer item={viewing} onClose={closeViewer} />}
    </>
  )
}
