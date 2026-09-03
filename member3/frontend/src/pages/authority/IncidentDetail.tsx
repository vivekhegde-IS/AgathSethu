import React from 'react'
import { useParams, Link } from 'react-router-dom'
import { useIncidentStore } from '@stores/incidentStore'
import { Card, Badge, Button, Table, Column } from '@components/ui'

export const IncidentDetailPage: React.FC = () => {
  const { incidentId } = useParams<{ incidentId: string }>()
  const { incidents, updateIncidentStatus } = useIncidentStore()

  const incident = incidents.find((i) => i.incidentId === incidentId) || incidents[0]

  if (!incident) {
    return (
      <div className="p-12 text-center font-mono text-slate-400">
        Incident record not found.
        <Link to="/authority/incidents" className="text-cyan-400 block mt-2">
          ← Back to Incidents
        </Link>
      </div>
    )
  }

  const candidateColumns: Column<(typeof incident.candidateVehicles)[0]>[] = [
    {
      header: 'CANDIDATE VEHICLE',
      cell: (row) => (
        <div>
          <span className="font-mono font-bold text-white text-xs">{row.licensePlate}</span>
          <p className="text-[10px] text-slate-400 font-mono">{row.vehicleType}</p>
        </div>
      ),
    },
    {
      header: 'ASSIGNED ROLE',
      cell: (row) => {
        const variant =
          row.role === 'PRIMARY_COLLIDER' || row.role === 'FLEEING_SUSPECT'
            ? 'danger'
            : row.role === 'VICTIM'
            ? 'warning'
            : 'info'
        return (
          <Badge variant={variant} size="sm">
            {row.role.replace('_', ' ')}
          </Badge>
        )
      },
    },
    {
      header: 'IMPACT DYNAMICS',
      cell: (row) => (
        <span className="font-mono text-xs text-slate-200">
          {row.speedBeforeImpact} → {row.speedAfterImpact} km/h (Prox: {row.proximityMeters}m)
        </span>
      ),
    },
    {
      header: 'ANOMALY SCORE',
      cell: (row) => (
        <div className="flex items-center gap-2">
          <div className="w-16 bg-slate-800 rounded-full h-1.5 overflow-hidden">
            <div
              className={`h-full ${
                row.anomalyScore > 80 ? 'bg-red-500' : row.anomalyScore > 50 ? 'bg-amber-500' : 'bg-emerald-500'
              }`}
              style={{ width: `${row.anomalyScore}%` }}
            />
          </div>
          <span className="font-mono text-xs font-bold text-white">{row.anomalyScore}%</span>
        </div>
      ),
    },
    {
      header: 'IDENTITY FUSION',
      cell: (row) => (
        <Badge variant={row.identityMatch === 'MATCHED' ? 'success' : 'danger'} size="sm">
          {row.identityMatch}
        </Badge>
      ),
    },
    {
      header: 'ACTION',
      className: 'text-right',
      cell: (row) => (
        <Link to={`/authority/vehicles/${row.vehicleId}`}>
          <Button variant="secondary" size="sm">
            Vehicle Profile →
          </Button>
        </Link>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Badge variant="danger" size="md" dot>
              LEVEL 2 CRASH INVESTIGATION
            </Badge>
            <span className="text-xs font-mono text-cyan-400">{incident.incidentId}</span>
          </div>
          <h2 className="text-xl font-bold font-mono text-white mt-1">{incident.title}</h2>
          <p className="text-xs text-slate-400 font-mono mt-0.5">
            Junction: {incident.location.junctionName} · Investigating Officer: {incident.investigatingOfficer}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Link to="/authority/incidents">
            <Button variant="secondary" size="sm">
              ← Incident Radar
            </Button>
          </Link>
          {incident.status === 'INVESTIGATING' ? (
            <Button
              variant="danger"
              size="sm"
              onClick={() => updateIncidentStatus(incident.incidentId, 'DISPATCHED')}
            >
              Dispatch Emergency & Tow Units
            </Button>
          ) : (
            <Button
              variant="success"
              size="sm"
              onClick={() => updateIncidentStatus(incident.incidentId, 'RESOLVED')}
            >
              Mark Investigation Resolved
            </Button>
          )}
        </div>
      </div>

      {/* Collision Physics & Evidence Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Optical Evidence Frame */}
        <Card title="Impact Frame Optical Evidence" glow className="lg:col-span-1">
          <div className="space-y-3">
            <div className="relative aspect-video rounded overflow-hidden bg-black border border-slate-700">
              <img
                src={incident.evidenceImages[0]}
                alt="Impact Capture"
                className="w-full h-full object-cover"
              />
              <div className="absolute top-2 left-2 bg-black/80 backdrop-blur-sm px-2 py-0.5 rounded text-[10px] font-mono text-red-400 border border-red-500/40">
                IMPACT DETECTED · {incident.impactSpeedKmh} KM/H
              </div>
            </div>
            <p className="text-[11px] text-slate-400 font-mono">
              Timestamp: {new Date(incident.timestamp).toISOString()}
            </p>
          </div>
        </Card>

        {/* Impact Physics & Sensor Fusion Diagnostics */}
        <Card title="Extended Kalman Multi-Sensor Reconstruction" glow className="lg:col-span-2">
          <div className="space-y-4 text-xs font-mono">
            <p className="text-slate-300 leading-relaxed">{incident.summary}</p>

            <div className="grid grid-cols-3 gap-3">
              <div className="p-3 bg-[#121820] rounded border border-slate-800">
                <span className="text-[10px] text-slate-500 uppercase block">Impact Velocity</span>
                <span className="text-red-400 font-bold text-base">{incident.impactSpeedKmh} km/h</span>
              </div>
              <div className="p-3 bg-[#121820] rounded border border-slate-800">
                <span className="text-[10px] text-slate-500 uppercase block">IMU Deceleration</span>
                <span className="text-amber-400 font-bold text-base">-12.8 m/s²</span>
              </div>
              <div className="p-3 bg-[#121820] rounded border border-slate-800">
                <span className="text-[10px] text-slate-500 uppercase block">Reconstructed Path</span>
                <span className="text-cyan-400 font-bold text-base">LOCKED</span>
              </div>
            </div>
          </div>
        </Card>
      </div>

      {/* Candidate Vehicles Table */}
      <Card title="Candidate Vehicles & Suspect Scoring">
        <Table
          columns={candidateColumns}
          data={incident.candidateVehicles}
          keyExtractor={(row) => row.vehicleId}
        />
      </Card>
    </div>
  )
}
