import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useViolationStore } from '@stores/violationStore'
import { Card, Table, Badge, Button, Select, Column } from '@components/ui'

export const CitizenViolations: React.FC = () => {
  const { violations } = useViolationStore()
  const [filterType, setFilterType] = useState<string>('ALL')

  const filtered = violations.filter((v) => {
    if (filterType === 'ALL') return true
    if (filterType === 'PENDING') return v.status !== 'PAID'
    if (filterType === 'PAID') return v.status === 'PAID'
    return v.violation_type === filterType
  })

  const columns: Column<(typeof violations)[0]>[] = [
    {
      header: 'CHALLAN ID',
      cell: (row) => (
        <span className="font-mono font-semibold text-cyan-400">{row.violation_id}</span>
      ),
    },
    {
      header: 'VEHICLE',
      cell: (row) => <span className="font-mono font-bold text-white">{row.license_plate}</span>,
    },
    {
      header: 'VIOLATION TYPE',
      cell: (row) => (
        <Badge variant={row.severity === 'severe' ? 'danger' : 'warning'} size="sm">
          {row.violation_type}
        </Badge>
      ),
    },
    {
      header: 'LOCATION & DATE',
      cell: (row) => (
        <div>
          <p className="text-white">{row.location}</p>
          <p className="text-[10px] text-slate-400 font-mono">
            {new Date(row.timestamp).toLocaleString()}
          </p>
        </div>
      ),
    },
    {
      header: 'FINE AMOUNT',
      cell: (row) => <span className="font-mono font-bold text-white">₹{row.fineAmount}</span>,
    },
    {
      header: 'STATUS',
      cell: (row) => (
        <Badge variant={row.status === 'PAID' ? 'success' : 'danger'} size="sm">
          {row.status}
        </Badge>
      ),
    },
    {
      header: 'ACTIONS',
      className: 'text-right',
      cell: (row) => (
        <div className="flex items-center justify-end gap-2">
          <Link to={`/citizen/violations/${row.violation_id}`}>
            <Button variant="secondary" size="sm">
              Evidence
            </Button>
          </Link>
          {row.status !== 'PAID' && (
            <Link to={`/citizen/payments/${row.violation_id}`}>
              <Button variant="danger" size="sm">
                Pay Now
              </Button>
            </Link>
          )}
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold font-mono text-white">Traffic e-Challan History</h2>
          <p className="text-xs text-slate-400 font-mono">
            Automated computer vision violation records logged across monitored junctions.
          </p>
        </div>

        <div className="w-48">
          <Select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            options={[
              { value: 'ALL', label: 'All Violations' },
              { value: 'PENDING', label: 'Pending Payment' },
              { value: 'PAID', label: 'Paid / Settled' },
              { value: 'SPEEDING', label: 'Speeding Only' },
              { value: 'RED_LIGHT', label: 'Red Light Only' },
            ]}
          />
        </div>
      </div>

      <Card>
        <Table
          columns={columns}
          data={filtered}
          keyExtractor={(row) => row.violation_id}
          emptyMessage="No violation records found matching the filter."
        />
      </Card>
    </div>
  )
}
