import React from 'react'
import { Link } from 'react-router-dom'
import { Button, Card, Spinner } from '@components/ui'
import { rupees, useMyFines } from '@components/citizen/FinesTable'
import { PaymentHistory } from '@components/citizen/PaymentHistory'
import { formatIstDate } from '@api/portal'

/** Pay Fines: the citizen's unpaid challans (real) and their payment history. */
export const CitizenPayments: React.FC = () => {
  const { data, error, reload } = useMyFines()
  const unpaid = (data?.fines ?? []).filter((f) => f.status !== 'Paid')

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold text-blue-950">Pay Fines</h2>
          <p className="text-sm text-slate-600">Unpaid e-challans on your registered vehicles.</p>
        </div>
        <Button variant="secondary" size="sm" onClick={reload}>
          Refresh
        </Button>
      </div>

      {error && <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded">{error}</div>}

      <Card title={data ? `Unpaid challans (${unpaid.length}) · ${rupees(data.total_unpaid)}` : 'Unpaid challans'}>
        {!data && !error ? (
          <Spinner />
        ) : unpaid.length === 0 ? (
          <p className="p-6 text-center text-slate-600 font-mono text-xs">You have no unpaid fines.</p>
        ) : (
          <ul className="divide-y divide-slate-200">
            {unpaid.map((fine) => (
              <li key={fine.id} className="py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-slate-900">
                    {fine.violation_type} · <span className="font-mono">{fine.number_plate}</span>
                  </p>
                  <p className="text-sm text-slate-600">
                    Challan #{fine.id} · issued {formatIstDate(fine.detected_at)}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-mono font-bold text-slate-900">{rupees(fine.fine_amount)}</span>
                  <Link to={`/citizen/payments/${fine.id}`}>
                    <Button variant="primary" size="sm">
                      Pay now
                    </Button>
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <section id="history">
        <Card title="Payment history">
          <PaymentHistory />
        </Card>
      </section>
    </div>
  )
}
