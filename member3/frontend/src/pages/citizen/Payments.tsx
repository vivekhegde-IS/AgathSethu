import React from 'react'
import { Link } from 'react-router-dom'
import { useViolationStore } from '@stores/violationStore'
import { Card, Table, Button, Column } from '@components/ui'

export const CitizenPayments: React.FC = () => {
  const { violations } = useViolationStore()

  const pending = violations.filter((v) => v.status !== 'PAID')
  const totalPending = pending.reduce((sum, v) => sum + v.fineAmount, 0)

  const columns: Column<(typeof pending)[0]>[] = [
    {
      header: 'CHALLAN #',
      cell: (row) => <span className="font-mono font-semibold text-cyan-400">{row.violation_id}</span>,
    },
    {
      header: 'VEHICLE',
      cell: (row) => <span className="font-mono font-bold text-white">{row.license_plate}</span>,
    },
    {
      header: 'OFFENCE',
      cell: (row) => (
        <div>
          <p className="font-semibold text-white">{row.violation_type}</p>
          <p className="text-[10px] text-slate-400 font-mono">{row.location}</p>
        </div>
      ),
    },
    {
      header: 'FINE AMOUNT',
      cell: (row) => <span className="font-mono font-bold text-red-400 text-sm">₹{row.fineAmount}</span>,
    },
    {
      header: 'ACTION',
      className: 'text-right',
      cell: (row) => (
        <Link to={`/citizen/payments/${row.violation_id}`}>
          <Button variant="danger" size="sm">
            Pay Now →
          </Button>
        </Link>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold font-mono text-white">Challan Payment Gateway</h2>
          <p className="text-xs text-slate-400 font-mono">
            Settle electronic traffic violation penalties instantly via UPI, NetBanking, or Cards.
          </p>
        </div>

        <div className="p-3 bg-red-950/40 border border-red-800 rounded flex items-center gap-3">
          <span className="text-xs font-mono text-slate-300">Total Pending:</span>
          <span className="text-base font-bold font-mono text-red-400">₹{totalPending}</span>
        </div>
      </div>

      <Card title="Unpaid Challans">
        {pending.length === 0 ? (
          <div className="p-10 text-center space-y-2">
            <span className="text-2xl">🎉</span>
            <p className="text-sm font-mono text-emerald-400 font-semibold">All Challans Clear!</p>
            <p className="text-xs text-slate-400 font-mono">
              There are no outstanding traffic penalties registered under your account.
            </p>
          </div>
        ) : (
          <Table
            columns={columns}
            data={pending}
            keyExtractor={(row) => row.violation_id}
          />
        )}
      </Card>
    </div>
  )
}
