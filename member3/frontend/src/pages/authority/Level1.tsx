import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useViolationStore } from '@stores/violationStore'
import { Card, Table, Badge, Button, Select, Column } from '@components/ui'

export const Level1Dashboard: React.FC = () => {
  const { violations, updateViolationStatus } = useViolationStore()
  const [filter, setFilter] = useState<string>('ALL')

  const filtered = violations.filter((v) => {
    if (filter === 'ALL') return true
    return v.violation_type === filter
  })

  const columns: Column<(typeof violations)[0]>[] = [
    {
      header: 'CHALLAN #',
      cell: (row) => <span className="font-mono font-semibold text-cyan-400">{row.violation_id}</span>,
    },
    {
      header: 'LICENSE PLATE',
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
      header: 'CONFIDENCE',
      cell: (row) => (
        <span className="font-mono text-emerald-400">{(row.confidence * 100).toFixed(1)}%</span>
      ),
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
          <Link to={`/authority/violations/${row.violation_id}`}>
            <Button variant="secondary" size="sm">
              Review Dossier
            </Button>
          </Link>
          {row.status !== 'CHALLAN_ISSUED' && row.status !== 'PAID' && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => updateViolationStatus(row.violation_id, 'CHALLAN_ISSUED')}
            >
              Approve e-Challan
            </Button>
          )}
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold font-mono text-white">Level 1 Routine Traffic Enforcement</h2>
          <p className="text-xs text-slate-400 font-mono">
            Review and certify AI-detected speeding, red light running, and helmet violations before issuance.
          </p>
        </div>

        <div className="w-56">
          <Select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            options={[
              { value: 'ALL', label: 'All Violations' },
              { value: 'SPEEDING', label: 'Speeding Violations' },
              { value: 'RED_LIGHT', label: 'Red Light Violations' },
              { value: 'NO_HELMET', label: 'No Helmet Violations' },
            ]}
          />
        </div>
      </div>

      <Card title="Violation Intake Queue">
        <Table
          columns={columns}
          data={filtered}
          keyExtractor={(row) => row.violation_id}
        />
      </Card>
    </div>
  )
}
