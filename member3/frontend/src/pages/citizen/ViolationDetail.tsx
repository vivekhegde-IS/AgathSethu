import React from 'react'
import { useParams, Link } from 'react-router-dom'
import { useViolationStore } from '@stores/violationStore'
import { Card, Badge, Button } from '@components/ui'

export const CitizenViolationDetail: React.FC = () => {
  const { violationId } = useParams<{ violationId: string }>()
  const { violations } = useViolationStore()

  const violation = violations.find((v) => v.violation_id === violationId) || violations[0]

  if (!violation) {
    return (
      <div className="p-12 text-center">
        <p className="text-slate-400 font-mono">Challan record not found.</p>
        <Link to="/citizen/violations" className="text-cyan-400 mt-4 inline-block font-mono text-sm">
          ← Return to Violations List
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-cyan-400">CHALLAN EVIDENCE DOSSIER</span>
            <Badge variant={violation.status === 'PAID' ? 'success' : 'danger'} size="sm">
              {violation.status}
            </Badge>
          </div>
          <h2 className="text-xl font-bold font-mono text-white mt-1">
            {violation.violation_id} — {violation.license_plate}
          </h2>
        </div>
        <div className="flex items-center gap-3">
          <Link to="/citizen/violations">
            <Button variant="secondary" size="sm">
              ← Back
            </Button>
          </Link>
          {violation.status !== 'PAID' && (
            <Link to={`/citizen/payments/${violation.violation_id}`}>
              <Button variant="danger" size="sm">
                Pay Fine (₹{violation.fineAmount})
              </Button>
            </Link>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Evidence Image Panel */}
        <Card title="Photographic Evidence (ANPR Capture Frame)" glow>
          <div className="space-y-3">
            <div className="relative aspect-video rounded-lg overflow-hidden bg-black border border-slate-700 flex items-center justify-center">
              <img
                src={violation.evidence_image_url}
                alt="Violation Frame"
                className="w-full h-full object-cover"
              />
              <div className="absolute top-3 left-3 bg-black/80 backdrop-blur-sm px-2.5 py-1 rounded text-[11px] font-mono text-cyan-300 border border-cyan-500/40">
                CAM: {violation.camera_id} · CONFIDENCE: {(violation.confidence * 100).toFixed(1)}%
              </div>
              <div className="absolute bottom-3 right-3 bg-black/80 backdrop-blur-sm px-2.5 py-1 rounded text-[11px] font-mono text-amber-300 border border-amber-500/40">
                {violation.violation_type} DETECTED
              </div>
            </div>
            <p className="text-[11px] text-slate-400 font-mono">
              Timestamp: {new Date(violation.timestamp).toISOString()} · Cryptographic Hash: 8fbc4e2...a19d
            </p>
          </div>
        </Card>

        {/* Telemetry & Violation Details */}
        <Card title="Violation Telemetry & Section Breakdown">
          <div className="space-y-4 text-xs font-mono">
            <div className="grid grid-cols-2 gap-3">
              <div className="p-3 bg-[#121820] rounded border border-slate-800">
                <span className="text-[10px] text-slate-500 uppercase block">Violation Category</span>
                <span className="text-white font-bold text-sm">{violation.violation_type}</span>
              </div>
              <div className="p-3 bg-[#121820] rounded border border-slate-800">
                <span className="text-[10px] text-slate-500 uppercase block">Severity Tier</span>
                <span className="text-amber-400 font-bold uppercase">{violation.severity}</span>
              </div>
              <div className="p-3 bg-[#121820] rounded border border-slate-800">
                <span className="text-[10px] text-slate-500 uppercase block">Intersection / Mast</span>
                <span className="text-slate-300">{violation.location}</span>
              </div>
              <div className="p-3 bg-[#121820] rounded border border-slate-800">
                <span className="text-[10px] text-slate-500 uppercase block">Penalty Fine</span>
                <span className="text-red-400 font-bold text-sm">₹{violation.fineAmount}</span>
              </div>
            </div>

            {violation.details && (
              <div className="p-3.5 bg-[#141b24] rounded border border-slate-700/80 space-y-1.5">
                <span className="text-[11px] text-cyan-300 font-semibold uppercase block">
                  Measured Diagnostics
                </span>
                {violation.details.measured_speed && (
                  <p className="text-slate-300">
                    Recorded Speed: <strong className="text-white">{violation.details.measured_speed} km/h</strong> (Speed Limit: {String(violation.details.speed_limit ?? '')} km/h)
                  </p>
                )}
                {violation.details.signal_color && (
                  <p className="text-slate-300">
                    Signal State: <strong className="text-red-400 uppercase">{violation.details.signal_color}</strong> (Elapsed in Red: {String(violation.details.red_elapsed_seconds ?? '')}s)
                  </p>
                )}
              </div>
            )}

            <div className="p-3 bg-blue-950/30 border border-blue-800/40 rounded text-[11px] text-slate-300 space-y-1">
              <strong className="text-cyan-300 block">Section 183 / 184 Motor Vehicles Act 1988</strong>
              <p>
                Notice generated automatically via Section 136A electronic monitoring. You can settle the penalty online
                or file a formal dispute with traffic headquarters within 30 days.
              </p>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}
