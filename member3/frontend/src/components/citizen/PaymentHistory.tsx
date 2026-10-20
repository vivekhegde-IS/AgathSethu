/**
 * Payment history of the logged-in citizen, from GET /citizen/payments
 * (stored fine_payments rows, so it survives logout and closing the browser).
 */

import React, { useEffect, useState } from 'react'
import { Spinner } from '@components/ui'
import { PaymentRecord, errorMessage, fetchPayments, formatIst, rupees } from '@api/portal'

const METHOD_LABEL: Record<string, string> = { upi: 'UPI', card: 'Card', netbanking: 'Net banking' }

export const PaymentHistory: React.FC<{ limit?: number }> = ({ limit }) => {
  const [rows, setRows] = useState<PaymentRecord[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    fetchPayments()
      .then((data) => setRows(data.payments))
      .catch((err) => setError(errorMessage(err, 'Could not load your payment history.')))
  }, [])

  if (error) return <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded">{error}</div>
  if (!rows) return <Spinner />
  if (rows.length === 0) {
    return <p className="p-6 text-center text-slate-600 font-mono text-xs">No payments made yet.</p>
  }
  const shown = limit ? rows.slice(0, limit) : rows

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm text-left">
        <thead className="text-[10px] uppercase tracking-wider text-slate-600 border-b border-slate-300">
          <tr>
            <th className="py-2 pr-4">Date paid</th>
            <th className="py-2 pr-4">Challan #</th>
            <th className="py-2 pr-4">Violation</th>
            <th className="py-2 pr-4">Vehicle</th>
            <th className="py-2 pr-4">Amount</th>
            <th className="py-2 pr-4">Method</th>
            <th className="py-2">Receipt no.</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((p) => (
            <tr key={p.id} className="border-b border-slate-200 text-slate-800">
              <td className="py-2 pr-4 text-xs font-mono whitespace-nowrap">{formatIst(p.paid_at)}</td>
              <td className="py-2 pr-4 font-mono text-blue-800">{p.fine_id}</td>
              <td className="py-2 pr-4 text-xs">{p.violation_type}</td>
              <td className="py-2 pr-4 font-mono font-semibold text-slate-900">{p.number_plate}</td>
              <td className="py-2 pr-4 font-mono font-bold text-slate-900">{rupees(p.amount)}</td>
              <td className="py-2 pr-4 text-xs">{METHOD_LABEL[p.method] ?? p.method}</td>
              <td className="py-2 font-mono text-xs text-emerald-700">{p.reference}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
