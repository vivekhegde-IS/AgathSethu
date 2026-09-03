import React from 'react'
import { Link } from 'react-router-dom'
import { useCameraStore } from '@stores/cameraStore'
import { Card, Table, Badge, Button, Column } from '@components/ui'

export const JunctionManagement: React.FC = () => {
  const { junctions } = useCameraStore()

  const columns: Column<(typeof junctions)[0]>[] = [
    {
      header: 'JUNCTION ID',
      cell: (row) => <span className="font-mono font-semibold text-cyan-400">{row.junctionId}</span>,
    },
    {
      header: 'JUNCTION NAME & CORRIDOR',
      cell: (row) => (
        <div>
          <p className="font-bold text-white text-xs">{row.name}</p>
          <p className="text-[10px] text-slate-400 font-mono">{row.corridor}</p>
        </div>
      ),
    },
    {
      header: 'CAMERAS / RFID',
      cell: (row) => (
        <span className="font-mono text-slate-300">
          {row.camerasCount} Cams · {row.rfidReadersCount} RFID
        </span>
      ),
    },
    {
      header: 'THROUGHPUT',
      cell: (row) => <span className="font-mono font-bold text-cyan-300">{row.throughputPerHour} veh/hr</span>,
    },
    {
      header: 'STATUS',
      cell: (row) => {
        const variant =
          row.status === 'OPTIMAL' ? 'success' : row.status === 'INCIDENT' ? 'danger' : 'warning'
        return (
          <Badge variant={variant} size="sm">
            {row.status}
          </Badge>
        )
      },
    },
    {
      header: 'ACTION',
      className: 'text-right',
      cell: () => (
        <Link to="/authority/live">
          <Button variant="secondary" size="sm">
            Live Feeds →
          </Button>
        </Link>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold font-mono text-white">Monitored Junction Infrastructure</h2>
        <p className="text-xs text-slate-400 font-mono">
          Overview of sensor telemetry coverage, camera masts, and RFID transponder readers.
        </p>
      </div>

      <Card title="Active Junction Nodes">
        <Table
          columns={columns}
          data={junctions}
          keyExtractor={(row) => row.junctionId}
        />
      </Card>
    </div>
  )
}
