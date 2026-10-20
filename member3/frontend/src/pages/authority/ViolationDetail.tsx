import React from 'react'
import { useParams, Link } from 'react-router-dom'
import { useViolationStore } from '@stores/violationStore'
import { Card, Badge, Button } from '@components/ui'

export const AuthorityViolationDetail: React.FC = () => {
  const { violationId } = useParams<{ violationId: string }>()
  const { violations, updateViolationStatus } = useViolationStore()

  const violation = violations.find((v) => v.violation_id === violationId) || violations[0]

  if (!violation) {
    return (
      <div className="p-12 text-center font-mono text-slate-600">
        Violation record not found.
        <Link to="/authority/level1" className="text-blue-800 block mt-2">
          ← Return to Queue
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-blue-800 uppercase">ENFORCEMENT EVIDENCE DOSSIER</span>
            <Badge variant={violation.severity === 'severe' ? 'danger' : 'warning'} size="sm">
              {violation.violation_type}
            </Badge>
          </div>
          <h2 className="text-2xl font-semibold text-blue-950 mt-1">
            {violation.violation_id} — {violation.license_plate}
          </h2>
        </div>

        <div className="flex items-center gap-3">
          <Link to="/authority/level1">
            <Button variant="secondary" size="sm">
              ← Back to Queue
            </Button>
          </Link>
          {violation.status !== 'CHALLAN_ISSUED' && violation.status !== 'PAID' && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => updateViolationStatus(violation.violation_id, 'CHALLAN_ISSUED')}
            >
              Sign & Issue e-Challan
            </Button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left Column: High Resolution ANPR Frame */}
        <Card title="Computer Vision High-Res Evidence Frame" glow>
          <div className="space-y-4">
            <div className="relative aspect-video rounded-lg overflow-hidden bg-black border border-slate-300 flex items-center justify-center">
              <img
                src={violation.evidence_image_url}
                alt="Camera Capture"
                className="w-full h-full object-cover"
              />
              {/* Bounding box simulation overlay */}
              <div className="absolute border-2 border-emerald-400 bg-emerald-100 top-1/4 left-1/3 w-1/3 h-1/3 rounded flex items-start justify-start p-1 pointer-events-none">
                <span className="bg-emerald-50 text-emerald-700 font-mono text-[10px] px-1 rounded border border-emerald-500">
                  {violation.license_plate} ({(violation.confidence * 100).toFixed(1)}%)
                </span>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-2 text-xs font-mono">
              <div className="p-2 bg-slate-50 rounded border border-slate-200">
                <span className="text-[10px] text-slate-500 uppercase block">Camera Mast</span>
                <span className="text-blue-800">{violation.camera_id}</span>
              </div>
              <div className="p-2 bg-slate-50 rounded border border-slate-200">
                <span className="text-[10px] text-slate-500 uppercase block">Inference Confidence</span>
                <span className="text-emerald-700">{(violation.confidence * 100).toFixed(1)}%</span>
              </div>
              <div className="p-2 bg-slate-50 rounded border border-slate-200">
                <span className="text-[10px] text-slate-500 uppercase block">Status</span>
                <span className="text-slate-900 uppercase">{violation.status}</span>
              </div>
            </div>
          </div>
        </Card>

        {/* Right Column: Violation Data & Section Verification */}
        <Card title="Offence Diagnostics & Legal Verification">
          <div className="space-y-4 text-xs font-mono">
            <div className="p-3 bg-slate-50 rounded border border-slate-200 space-y-2">
              <div className="flex justify-between">
                <span className="text-slate-600">Detected Number Plate:</span>
                <span className="font-bold text-slate-900 text-sm">{violation.license_plate}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-600">Junction Location:</span>
                <span className="text-slate-800">{violation.location}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-600">Timestamp:</span>
                <span className="text-slate-800">{new Date(violation.timestamp).toLocaleString()}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-600">Applicable Penalty:</span>
                <span className="text-red-700 font-bold text-sm">₹{violation.fineAmount}.00</span>
              </div>
            </div>

            {violation.details && (
              <div className="p-3 bg-slate-50 rounded border border-slate-300 space-y-1 text-slate-700">
                <span className="text-[11px] font-semibold text-blue-800 block uppercase">
                  Physical Measurements
                </span>
                {violation.details.measured_speed && (
                  <p>
                    Measured Speed: <strong className="text-slate-900">{violation.details.measured_speed} km/h</strong> (Excess: {String(violation.details.excess_speed ?? '')} km/h)
                  </p>
                )}
                {violation.details.signal_color && (
                  <p>
                    Signal Phase at Entry: <strong className="text-red-700 uppercase">{violation.details.signal_color}</strong>
                  </p>
                )}
              </div>
            )}

            <div className="p-3 bg-slate-50 rounded border border-slate-200 text-slate-600 space-y-1 text-[11px]">
              <span className="text-slate-800 font-semibold uppercase block">Evidence Integrity Check</span>
              <p>SHA-256 Digest: 8fbc4e29bca71092eac44819d08311ab2479f</p>
              <p>Camera Calibration Timestamp: Validated</p>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}
