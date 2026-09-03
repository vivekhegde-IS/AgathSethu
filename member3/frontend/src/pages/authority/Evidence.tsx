import React, { useState } from 'react'
import { Card, Table, Badge, Button, Select, Column } from '@components/ui'

export const EvidenceManager: React.FC = () => {
  const [filterSource, setFilterSource] = useState('ALL')

  const evidenceItems = [
    {
      id: 'EVID-2026-901',
      incidentId: 'INC-20260901-01',
      plate: 'KA03AB9012',
      source: 'MEMBER_2_ANPR_CAMERA',
      camera: 'CAM-J01-N',
      hash: 'sha256:8fbc4e29bca71092eac44819d08311ab2479f',
      timestamp: '2026-09-01 17:42:10',
      status: 'VERIFIED',
    },
    {
      id: 'EVID-2026-902',
      incidentId: 'INC-20260901-01',
      plate: 'KA03AB9012',
      source: 'MEMBER_3_FASTAG_RFID',
      camera: 'RFID-R01-KORM-N',
      hash: 'sha256:39fa0812bdcc4891a92e1048bc8110029abff',
      timestamp: '2026-09-01 17:42:09',
      status: 'VERIFIED',
    },
    {
      id: 'EVID-2026-903',
      incidentId: 'INC-20260831-04',
      plate: 'KA04MN9912',
      source: 'MEMBER_1_CARLA_IMU',
      camera: 'VEH-KA04MN9912-IMU',
      hash: 'sha256:719ccba1238910028ba491823901bcda90128',
      timestamp: '2026-08-31 14:10:02',
      status: 'VERIFIED',
    },
  ]

  const columns: Column<(typeof evidenceItems)[0]>[] = [
    {
      header: 'EVIDENCE ID',
      cell: (row) => <span className="font-mono font-semibold text-cyan-400">{row.id}</span>,
    },
    {
      header: 'ASSOCIATED INCIDENT',
      cell: (row) => (
        <div>
          <span className="font-mono text-white text-xs">{row.incidentId}</span>
          <p className="text-[10px] text-slate-400 font-mono">Plate: {row.plate}</p>
        </div>
      ),
    },
    {
      header: 'SENSOR SOURCE',
      cell: (row) => (
        <Badge variant="brand" size="sm">
          {row.source}
        </Badge>
      ),
    },
    {
      header: 'CRYPTOGRAPHIC DIGEST',
      cell: (row) => (
        <span className="font-mono text-[10px] text-slate-400 truncate block max-w-xs">{row.hash}</span>
      ),
    },
    {
      header: 'STATUS',
      cell: (row) => (
        <Badge variant="success" size="sm">
          {row.status}
        </Badge>
      ),
    },
    {
      header: 'ACTION',
      className: 'text-right',
      cell: () => (
        <Button variant="secondary" size="sm" onClick={() => alert('Evidence verified with SHA-256 seal.')}>
          Verify Hash
        </Button>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold font-mono text-white">Cryptographic Evidence Vault</h2>
          <p className="text-xs text-slate-400 font-mono">
            Tamper-proof storage of ANPR video snapshots, FASTag transponder events, and physics telemetry.
          </p>
        </div>

        <div className="w-56">
          <Select
            value={filterSource}
            onChange={(e) => setFilterSource(e.target.value)}
            options={[
              { value: 'ALL', label: 'All Sensor Sources' },
              { value: 'MEMBER_2_ANPR_CAMERA', label: 'Optical ANPR Camera' },
              { value: 'MEMBER_3_FASTAG_RFID', label: 'FASTag RFID Gantry' },
              { value: 'MEMBER_1_CARLA_IMU', label: 'CARLA IMU Telemetry' },
            ]}
          />
        </div>
      </div>

      <Card title="Secured Evidence Dossiers">
        <Table
          columns={columns}
          data={evidenceItems}
          keyExtractor={(row) => row.id}
        />
      </Card>
    </div>
  )
}
