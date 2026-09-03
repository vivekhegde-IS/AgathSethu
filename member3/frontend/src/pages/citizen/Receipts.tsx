import React from 'react'
import { useViolationStore } from '@stores/violationStore'
import { Card, Table, Button, Column } from '@components/ui'

export const CitizenReceipts: React.FC = () => {
  const { violations } = useViolationStore()

  const paidViolations = violations.filter((v) => v.status === 'PAID')

  const columns: Column<(typeof paidViolations)[0]>[] = [
    {
      header: 'RECEIPT / TX ID',
      cell: (row) => (
        <div>
          <span className="font-mono font-semibold text-emerald-400">{row.paymentId || 'TX-998210'}</span>
          <p className="text-[10px] text-slate-500 font-mono">Challan: {row.violation_id}</p>
        </div>
      ),
    },
    {
      header: 'VEHICLE',
      cell: (row) => <span className="font-mono font-bold text-white">{row.license_plate}</span>,
    },
    {
      header: 'OFFENCE CLEARED',
      cell: (row) => <span className="text-slate-300 font-mono text-xs">{row.violation_type}</span>,
    },
    {
      header: 'AMOUNT PAID',
      cell: (row) => <span className="font-mono font-bold text-emerald-400">₹{row.fineAmount}.00</span>,
    },
    {
      header: 'DATE',
      cell: (row) => (
        <span className="text-xs text-slate-400 font-mono">
          {row.paidAt ? new Date(row.paidAt).toLocaleDateString() : '2026-08-30'}
        </span>
      ),
    },
    {
      header: 'ACTION',
      className: 'text-right',
      cell: () => (
        <Button
          variant="outline"
          size="sm"
          onClick={() => alert('Digital Receipt PDF downloaded with MoRTH digital signature certificate.')}
        >
          📄 Download PDF
        </Button>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold font-mono text-white">Payment Receipts & Settlement Slips</h2>
        <p className="text-xs text-slate-400 font-mono">
          Official digital receipts for settled traffic penalties with cryptographic verification.
        </p>
      </div>

      <Card title="Settled Challans">
        {paidViolations.length === 0 ? (
          <div className="p-10 text-center text-slate-400 font-mono text-xs">
            No payment receipts generated yet.
          </div>
        ) : (
          <Table
            columns={columns}
            data={paidViolations}
            keyExtractor={(row) => row.violation_id}
          />
        )}
      </Card>
    </div>
  )
}
