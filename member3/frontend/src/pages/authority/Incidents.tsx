import React from 'react'
import { Link } from 'react-router-dom'
import { useIncidentStore } from '@stores/incidentStore'
import { Card, Table, Badge, Button, MetricCard, Column } from '@components/ui'

export const IncidentDashboard: React.FC = () => {
  const { incidents } = useIncidentStore()

  const columns: Column<(typeof incidents)[0]>[] = [
    {
      header: 'INCIDENT ID',
      cell: (row) => <span className="font-mono font-semibold text-red-400">{row.incidentId}</span>,
    },
    {
      header: 'INCIDENT TITLE & JUNCTION',
      cell: (row) => (
        <div>
          <p className="font-bold text-white text-xs">{row.title}</p>
          <p className="text-[10px] text-slate-400 font-mono">{row.location.junctionName}</p>
        </div>
      ),
    },
    {
      header: 'IMPACT SPEED',
      cell: (row) => (
        <span className="font-mono font-bold text-red-400">{row.impactSpeedKmh} km/h</span>
      ),
    },
    {
      header: 'SEVERITY',
      cell: (row) => (
        <Badge variant={row.severity === 'CRITICAL' ? 'danger' : 'warning'} size="sm">
          {row.severity}
        </Badge>
      ),
    },
    {
      header: 'INVESTIGATION STATUS',
      cell: (row) => (
        <Badge variant={row.status === 'INVESTIGATING' ? 'danger' : 'info'} size="sm">
          {row.status}
        </Badge>
      ),
    },
    {
      header: 'ACTION',
      className: 'text-right',
      cell: (row) => (
        <Link to={`/authority/incidents/${row.incidentId}`}>
          <Button variant="danger" size="sm">
            Investigate Radar →
          </Button>
        </Link>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-red-400 uppercase">LEVEL 2 INCIDENT OPERATIONS</span>
          <Badge variant="danger" size="sm" dot>
            PHYSICS CRASH ENGINE ACTIVE
          </Badge>
        </div>
        <h2 className="text-xl font-bold font-mono text-white mt-1">
          Crash Detection & Hit-and-Run Investigation
        </h2>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <MetricCard
          label="Active Crash Alerts"
          value="1 Critical"
          subValue="Town04 Intersection Collision"
          status="critical"
        />
        <MetricCard
          label="Suspect Vehicles Flagged"
          value="2 Identified"
          subValue="Vision + FASTag Anomaly"
          status="warning"
        />
        <MetricCard
          label="Average TOC Dispatch Time"
          value="42 seconds"
          subValue="Target: < 60 seconds"
          status="success"
        />
      </div>

      <Card title="Incident Investigation Docket">
        <Table
          columns={columns}
          data={incidents}
          keyExtractor={(row) => row.incidentId}
        />
      </Card>
    </div>
  )
}
