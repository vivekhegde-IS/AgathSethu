import React from 'react'
import { useViolationStore } from '@stores/violationStore'
import { Card, Table, Badge, MetricCard, Column } from '@components/ui'

export const FineManagement: React.FC = () => {
  const { violations } = useViolationStore()

  const totalCollected = violations
    .filter((v) => v.status === 'PAID')
    .reduce((sum, v) => sum + v.fineAmount, 0)
  const totalOutstanding = violations
    .filter((v) => v.status !== 'PAID')
    .reduce((sum, v) => sum + v.fineAmount, 0)

  const columns: Column<(typeof violations)[0]>[] = [
    {
      header: 'CHALLAN #',
      cell: (row) => <span className="font-mono font-semibold text-cyan-400">{row.violation_id}</span>,
    },
    {
      header: 'VEHICLE REG',
      cell: (row) => <span className="font-mono font-bold text-white">{row.license_plate}</span>,
    },
    {
      header: 'OFFENCE TYPE',
      cell: (row) => <span className="text-slate-200 font-mono text-xs">{row.violation_type}</span>,
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
      header: 'DATE ISSUED',
      cell: (row) => (
        <span className="text-xs text-slate-400 font-mono">
          {new Date(row.timestamp).toLocaleDateString()}
        </span>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold font-mono text-white">Fine & Revenue Management</h2>
        <p className="text-xs text-slate-400 font-mono">
          Track revenue collections, outstanding fine dues, and recovery rates across municipal zones.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <MetricCard
          label="Total Collected"
          value={`₹${totalCollected}`}
          subValue="Settled via Gateway"
          status="success"
        />
        <MetricCard
          label="Outstanding Dues"
          value={`₹${totalOutstanding}`}
          subValue="Pending Citizen Payment"
          status="warning"
        />
        <MetricCard
          label="Collection Efficiency"
          value="76.4%"
          subValue="MoRTH Benchmark: 65%"
          status="normal"
        />
      </div>

      <Card title="Challan Ledger">
        <Table
          columns={columns}
          data={violations}
          keyExtractor={(row) => row.violation_id}
        />
      </Card>
    </div>
  )
}
