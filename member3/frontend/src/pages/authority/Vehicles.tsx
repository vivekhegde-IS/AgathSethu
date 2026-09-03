import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useVehicleStore } from '@stores/vehicleStore'
import { Card, Table, Badge, Button, Input, Column } from '@components/ui'

export const VehicleSearch: React.FC = () => {
  const { citizenVehicles } = useVehicleStore()
  const [searchTerm, setSearchTerm] = useState('')

  const allVehicles = [
    ...citizenVehicles,
    {
      vehicleId: 'VEH-KA03AB9012',
      registrationNumber: 'KA03AB9012',
      model: 'Honda City ZX (Black)',
      vehicleType: 'car' as const,
      rfidTag: 'EPC-8871BC-KA03AB9012',
      chassisNumber: 'MAK123EALM829103',
      pucExpiry: '2026-11-20',
      insuranceExpiry: '2026-12-10',
      activeViolationsCount: 2,
    },
    {
      vehicleId: 'VEH-KA04MN9912',
      registrationNumber: 'KA04MN9912',
      model: 'Tata 407 Commercial (Yellow)',
      vehicleType: 'truck' as const,
      rfidTag: 'EPC-9912TT-KA04MN9912',
      chassisNumber: 'MAT141EALM991244',
      pucExpiry: '2026-09-15',
      insuranceExpiry: '2026-10-01',
      activeViolationsCount: 1,
    },
  ]

  const filtered = allVehicles.filter(
    (v) =>
      v.registrationNumber.toLowerCase().includes(searchTerm.toLowerCase()) ||
      v.rfidTag.toLowerCase().includes(searchTerm.toLowerCase())
  )

  const columns: Column<(typeof allVehicles)[0]>[] = [
    {
      header: 'REGISTRATION #',
      cell: (row) => <span className="font-mono font-bold text-white text-xs">{row.registrationNumber}</span>,
    },
    {
      header: 'MODEL & TYPE',
      cell: (row) => (
        <div>
          <p className="text-white text-xs">{row.model}</p>
          <Badge variant="info" size="sm">
            {row.vehicleType.toUpperCase()}
          </Badge>
        </div>
      ),
    },
    {
      header: 'FASTAG RFID TRANSPONDER',
      cell: (row) => <span className="font-mono text-cyan-300 text-xs">{row.rfidTag}</span>,
    },
    {
      header: 'ACTIVE VIOLATIONS',
      cell: (row) => (
        <span
          className={`font-mono text-xs font-bold ${
            row.activeViolationsCount > 0 ? 'text-red-400' : 'text-emerald-400'
          }`}
        >
          {row.activeViolationsCount} Violations
        </span>
      ),
    },
    {
      header: 'ACTION',
      className: 'text-right',
      cell: (row) => (
        <Link to={`/authority/vehicles/${row.vehicleId}`}>
          <Button variant="secondary" size="sm">
            Inspect Profile →
          </Button>
        </Link>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold font-mono text-white">Vehicle Intelligence Registry</h2>
          <p className="text-xs text-slate-400 font-mono">
            Query vehicles by number plate, FASTag EPC RFID tag, or chassis identification.
          </p>
        </div>

        <div className="w-72">
          <Input
            placeholder="Search Plate # or FASTag..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
      </div>

      <Card title="Matched Vehicle Profiles">
        <Table
          columns={columns}
          data={filtered}
          keyExtractor={(row) => row.vehicleId}
        />
      </Card>
    </div>
  )
}
