import React, { useEffect, useRef, useState } from 'react'
import { AuthImage, Card, Badge, Button } from '@components/ui'
import { getApiBaseUrl, getToken } from '@api/apiClient'
import { fetchProtectedBlobUrl } from '@api/portal'

// The routine-violation API is authority-only: every request carries the login token.
const authHeaders = (): HeadersInit => {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** Protected files cannot be opened by a plain link; fetch with the token, then open or save. */
async function openProtected(path: string, downloadName?: string) {
  const url = await fetchProtectedBlobUrl(path)
  if (downloadName) {
    const a = document.createElement('a')
    a.href = url
    a.download = downloadName
    a.click()
  } else {
    window.open(url, '_blank', 'noopener')
  }
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

interface ViolatingVehicle {
  vehicle_id: number
  violations: string[]
  plate_number: string
  state_code: string | null
  state_name: string | null
  plate_status: 'confirmed' | 'low_confidence' | 'unreadable'
  first_violation_frame: number
  first_violation_time_s: number
  evidence_frame: number
  evidence_time_s: number
  image: string
}

interface RoutineResult {
  violation_detected: boolean
  violation_type: string | null
  number_plate: string | null
  state_name: string | null
  violation_image: string | null
  vehicles: ViolatingVehicle[]
  summary_csv: string | null
}

interface RoutineJobResponse {
  job_id: string
  status: 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled'
  result?: RoutineResult | null
  violation_detected?: boolean
  violation_type?: string | null
  number_plate?: string | null
  state_name?: string | null
  violation_image?: string | null
  vehicles?: ViolatingVehicle[]
  summary_csv?: string | null
  progress?: JobProgress | null
}

interface JobProgress {
  percent: number
  stage: string
  vehicles_found: number
}

const PLATE_STATUS_LABEL: Record<ViolatingVehicle['plate_status'], string> = {
  confirmed: 'Plate confirmed (multi-frame)',
  low_confidence: 'Plate low confidence',
  unreadable: 'Plate unreadable',
}

export const Level1Dashboard: React.FC = () => {
  const [selectedVideo, setSelectedVideo] = useState<File | null>(null)
  const [result, setResult] = useState<RoutineResult | null>(null)
  const [isProcessing, setIsProcessing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState<JobProgress | null>(null)
  const pollTimer = useRef<number | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => () => {
    if (pollTimer.current !== null) window.clearTimeout(pollTimer.current)
  }, [])

  const evidenceUrl = result?.violation_image ?? null

  const detectViolation = async () => {
    if (!selectedVideo) return
    setIsProcessing(true)
    setError(null)
    setResult(null)
    setProgress({ percent: 0, stage: 'uploading video', vehicles_found: 0 })
    const formData = new FormData()
    formData.append('video', selectedVideo)

    try {
      const response = await fetch(`${getApiBaseUrl()}/routine-violations/detect`, {
        method: 'POST',
        body: formData,
        headers: authHeaders(),
      })
      const payload: RoutineJobResponse = await response.json()
      if (!response.ok) throw new Error((payload as unknown as { detail?: string }).detail || 'Unable to start processing.')

      let job = payload
      while (job.status === 'queued' || job.status === 'processing') {
        await new Promise<void>((resolve) => {
          pollTimer.current = window.setTimeout(resolve, 1000)
        })
        const statusResponse = await fetch(`${getApiBaseUrl()}/routine-violations/jobs/${payload.job_id}`, { headers: authHeaders() })
        const statusPayload: RoutineJobResponse & { detail?: string } = await statusResponse.json()
        if (!statusResponse.ok) throw new Error(statusPayload.detail || 'Unable to read processing status.')
        if (statusPayload.status === 'failed' || statusPayload.status === 'cancelled') {
          throw new Error(statusPayload.detail || 'Video processing failed.')
        }
        job = statusPayload
        if (statusPayload.progress) setProgress(statusPayload.progress)
      }

      if (job.status !== 'completed') throw new Error('Video processing did not complete.')
      const completedResult = job.result || job

      setResult({
        violation_detected: Boolean(completedResult.violation_detected),
        violation_type: completedResult.violation_type || null,
        number_plate: completedResult.number_plate || null,
        state_name: completedResult.state_name || null,
        violation_image: completedResult.violation_image || null,
        vehicles: completedResult.vehicles || [],
        summary_csv: completedResult.summary_csv || null,
      })

      setSelectedVideo(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Unable to process the video.')
    } finally {
      if (pollTimer.current !== null) {
        window.clearTimeout(pollTimer.current)
        pollTimer.current = null
      }
      setIsProcessing(false)
      setProgress(null)
    }
  }

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] || null
    setSelectedVideo(file)
    if (file) {
      setError(null)
      setResult(null)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-blue-950">Level 1 Routine Traffic Enforcement</h2>
        <p className="text-sm text-slate-600">Upload a traffic video to detect and review a routine violation.</p>
      </div>

      <Card title="Upload Traffic Video">
        <div className="space-y-4">
          <input ref={fileInputRef} type="file" accept="video/*" onChange={handleFileChange} className="block w-full text-sm text-slate-700 file:mr-4 file:rounded-md file:border-0 file:bg-aghat-blue file:px-4 file:py-2 file:text-sm file:font-medium file:text-white" />
          {selectedVideo && <p className="text-xs font-mono text-slate-600">Selected: {selectedVideo.name}</p>}
          <Button onClick={detectViolation} disabled={!selectedVideo} isLoading={isProcessing}>Detect Violation</Button>
          {isProcessing && progress && (
            <div className="space-y-1">
              <div className="h-2 w-full overflow-hidden rounded bg-slate-200">
                <div className="h-full bg-aghat-blue transition-all" style={{ width: `${Math.max(2, progress.percent)}%` }} />
              </div>
              <p className="font-mono text-xs text-slate-600">
                {progress.percent}% · {progress.stage} · {progress.vehicles_found} vehicle{progress.vehicles_found === 1 ? '' : 's'} flagged so far
              </p>
            </div>
          )}
          {error && <p className="text-sm text-red-700">{error}</p>}
        </div>
      </Card>

      {result && (
        <Card title={result.violation_detected ? 'Violation Detected' : 'No Violation Detected'}>
          {result.violation_detected && result.vehicles.length > 0 ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm text-slate-700">
                  {result.vehicles.length} violating vehicle{result.vehicles.length === 1 ? '' : 's'} found
                </p>
                {result.summary_csv && (
                  <button type="button" onClick={() => openProtected(result.summary_csv!, 'violation_summary.csv').catch(() => setError('Could not download the summary.'))} className="text-xs font-mono text-aghat-blue hover:underline">Download summary (CSV)</button>
                )}
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                {result.vehicles.map((vehicle) => (
                  <div key={vehicle.vehicle_id} className="space-y-3 rounded-md border border-slate-300 bg-slate-50 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs text-slate-600">Vehicle {vehicle.vehicle_id}</span>
                      {vehicle.violations.map((violation) => (
                        <Badge key={violation} variant="danger" size="sm">{violation}</Badge>
                      ))}
                    </div>
                    <div>
                      <p className="text-xs uppercase text-slate-500">Number Plate</p>
                      <p className={`mt-1 font-mono text-xl font-bold ${vehicle.plate_number ? 'text-slate-900' : 'text-red-700'}`}>
                        {vehicle.plate_number || 'Plate unreadable'}
                      </p>
                      <p className="text-xs text-slate-600">
                        {vehicle.state_name ? `${vehicle.state_name} (${vehicle.state_code})` : 'State unknown'}
                        {' · '}{PLATE_STATUS_LABEL[vehicle.plate_status]}
                      </p>
                    </div>
                    <p className="font-mono text-xs text-slate-500">
                      First violation: frame {vehicle.first_violation_frame} ({vehicle.first_violation_time_s.toFixed(2)}s)
                      {' · '}Evidence: frame {vehicle.evidence_frame} ({vehicle.evidence_time_s.toFixed(2)}s)
                    </p>
                    <button type="button" className="block w-full" title="Open full size" onClick={() => openProtected(vehicle.image).catch(() => setError('Could not open the evidence image.'))}>
                      <AuthImage src={vehicle.image} alt={`Vehicle ${vehicle.vehicle_id} violation evidence`} className="max-h-[30rem] w-full rounded-md border border-slate-300 object-contain" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ) : result.violation_detected ? (
            <div className="space-y-5">
              <Badge variant="danger" size="sm">{result.violation_type}</Badge>
              <div><p className="text-xs uppercase text-slate-500">Number Plate</p><p className="mt-1 font-mono text-xl font-bold text-slate-900">{result.number_plate || 'Not readable'}</p>{result.state_name && <p className="text-xs text-slate-600">{result.state_name}</p>}</div>
              {evidenceUrl && <div><p className="mb-2 text-xs uppercase text-slate-500">Violation Evidence</p><AuthImage src={evidenceUrl} alt="Detected violation evidence" className="max-h-[34rem] w-full rounded-md border border-slate-300 object-contain" /></div>}
            </div>
          ) : <p className="text-sm text-emerald-700">No violation was detected in the uploaded video.</p>}
        </Card>
      )}
    </div>
  )
}
