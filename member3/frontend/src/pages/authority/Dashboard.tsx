import React, { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useViolationStore } from '@stores/violationStore'
import { useIncidentStore } from '@stores/incidentStore'
import { useCameraStore } from '@stores/cameraStore'
import { useSystemStore } from '@stores/systemStore'
import { Card, MetricCard, Badge, StatusIndicator, Button, Table, Column } from '@components/ui'

export const AuthorityDashboard: React.FC = () => {
  const { violations } = useViolationStore()
  const { incidents } = useIncidentStore()
  const { junctions, fetchCameras } = useCameraStore()
  const { member1, checkHealth } = useSystemStore()

  useEffect(() => {
    fetchCameras()
    checkHealth()
  }, [fetchCameras, checkHealth])

  const pendingViolations = violations.filter((v) => v.status !== 'PAID')
  const criticalIncident = incidents.find((i) => i.severity === 'CRITICAL')

  const violationColumns: Column<(typeof violations)[0]>[] = [
    {
      header: 'CHALLAN #',
      cell: (row) => <span className="font-mono font-semibold text-cyan-400">{row.violation_id}</span>,
    },
    {
      header: 'PLATE',
      cell: (row) => <span className="font-mono font-bold text-white">{row.license_plate}</span>,
    },
    {
      header: 'TYPE',
      cell: (row) => (
        <Badge variant={row.severity === 'severe' ? 'danger' : 'warning'} size="sm">
          {row.violation_type}
        </Badge>
      ),
    },
    {
      header: 'LOCATION',
      cell: (row) => <span className="text-slate-300 font-mono text-xs">{row.location}</span>,
    },
    {
      header: 'FINE',
      cell: (row) => <span className="font-mono text-white font-bold">₹{row.fineAmount}</span>,
    },
    {
      header: 'ACTION',
      className: 'text-right',
      cell: (row) => (
        <Link to={`/authority/violations/${row.violation_id}`}>
          <Button variant="secondary" size="sm">
            Review Evidence →
          </Button>
        </Link>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      {/* Top Banner Alert if Critical Crash Detected */}
      {criticalIncident && (
        <div className="p-4 rounded-lg bg-red-950/80 border-2 border-red-600 shadow-glowRed flex flex-col md:flex-row items-start md:items-center justify-between gap-4 animate-pulse-slow">
          <div className="flex items-center gap-3">
            <span className="text-2xl">🚨</span>
            <div>
              <div className="flex items-center gap-2">
                <Badge variant="danger" size="md">
                  LEVEL 2 CRITICAL COLLISION
                </Badge>
                <span className="text-xs font-mono text-red-300">INCIDENT ID: {criticalIncident.incidentId}</span>
              </div>
              <h3 className="text-sm font-bold font-mono text-white mt-0.5">
                {criticalIncident.title} ({criticalIncident.location.junctionName})
              </h3>
              <p className="text-xs text-red-200 font-mono mt-0.5">
                Impact Speed: {criticalIncident.impactSpeedKmh} km/h · Candidate Suspects: {criticalIncident.candidateVehicles.length} Flagged
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Link to={`/authority/incidents/${criticalIncident.incidentId}`}>
              <Button variant="danger" size="sm">
                Open Investigation Radar →
              </Button>
            </Link>
          </div>
        </div>
      )}

      {/* Operational KPI Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Active Junctions"
          value={`${junctions.length} Online`}
          subValue="100% Sensor Stream Health"
          status="normal"
        />
        <MetricCard
          label="Routine Violations"
          value={pendingViolations.length}
          subValue="Level 1 Pending Review"
          status={pendingViolations.length > 0 ? 'warning' : 'normal'}
        />
        <MetricCard
          label="ANPR Stream Rate"
          value="98.8% Fused"
          subValue="Vision + FASTag RFID Match"
          status="success"
          trend={{ direction: 'up', value: '3,420 veh/hr', positive: true }}
        />
        <MetricCard
          label="CARLA Sim Telemetry"
          value={member1?.scenarios_active ? `${member1.scenarios_active} Active` : 'Online'}
          subValue="48 Simulated Vehicles"
          status="normal"
        />
      </div>

      {/* Central Command Split View: Live Junction Telemetry + Routine Queue */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Live Multi-Camera Preview */}
        <Card
          title="Monitored Junction Grid"
          actions={
            <Link to="/authority/live">
              <Button variant="ghost" size="sm">
                Full Screen Grid →
              </Button>
            </Link>
          }
          className="lg:col-span-1"
        >
          <div className="space-y-3">
            <div className="relative aspect-video rounded bg-black border border-slate-700 overflow-hidden flex items-center justify-center">
              <img
                src="https://images.unsplash.com/photo-1549317661-bd32c8ce0db2?auto=format&fit=crop&w=800&q=80"
                alt="Junction Cam Feed"
                className="w-full h-full object-cover"
              />
              <div className="absolute top-2 left-2 bg-black/80 backdrop-blur-sm px-2 py-0.5 rounded text-[10px] font-mono text-cyan-400 border border-cyan-500/40">
                CAM-J01-N · LIVE 30 FPS
              </div>
              <div className="absolute bottom-2 left-2">
                <StatusIndicator status="active" label="CARLA STREAM" />
              </div>
            </div>

            <div className="p-3 bg-[#121820] rounded border border-slate-800 space-y-2 text-xs font-mono">
              <div className="flex justify-between">
                <span className="text-slate-400">Junction:</span>
                <span className="text-white font-semibold">Koramangala 80ft Signal</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Active Cameras:</span>
                <span className="text-cyan-300">8 / 8 Streaming</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">RFID Gantries:</span>
                <span className="text-emerald-400">4 / 4 Sync</span>
              </div>
            </div>
          </div>
        </Card>

        {/* Level 1 Routine Violation Queue */}
        <Card
          title="Level 1 Routine Enforcement Queue"
          actions={
            <Link to="/authority/level1">
              <Button variant="ghost" size="sm">
                Enforcement Desk →
              </Button>
            </Link>
          }
          className="lg:col-span-2"
        >
          <Table
            columns={violationColumns}
            data={violations.slice(0, 4)}
            keyExtractor={(row) => row.violation_id}
          />
        </Card>
      </div>
    </div>
  )
}
