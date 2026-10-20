import React, { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Button, Card, Select, Spinner } from '@components/ui'
import { rupees, useMyFines } from '@components/citizen/FinesTable'
import { errorMessage, formatIst, formatIstDate, payFine } from '@api/portal'

type Method = 'upi' | 'card' | 'netbanking'

/**
 * Pay one fine. The payment gateway is simulated; the backend records the
 * payment and marks the fine Paid, so it shows as paid everywhere.
 */
export const CitizenPaymentDetail: React.FC = () => {
  const { paymentId } = useParams<{ paymentId: string }>()
  const { data, error: loadError, reload } = useMyFines()
  const [method, setMethod] = useState<Method>('upi')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [receipt, setReceipt] = useState<{ reference: string; paid_at: string | null; amount: number } | null>(null)

  const fine = data?.fines.find((f) => String(f.id) === paymentId)

  const pay = async () => {
    if (!fine) return
    setBusy(true)
    setError('')
    try {
      const result = await payFine(fine.id, method)
      setReceipt(result.payment)
      reload()
    } catch (err) {
      setError(errorMessage(err, 'The payment could not be recorded.'))
    } finally {
      setBusy(false)
    }
  }

  if (loadError) return <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded">{loadError}</div>
  if (!data) return <Spinner />
  if (!fine) {
    return (
      <Card title="Challan not found">
        <p className="text-sm text-slate-600">This challan does not exist on your account.</p>
        <Link to="/citizen/payments" className="text-xs text-blue-800 hover:underline">
          ← Back to Pay Fines
        </Link>
      </Card>
    )
  }

  const paid = receipt ?? fine.payment

  return (
    <div className="max-w-xl space-y-6">
      <Link to="/citizen/payments" className="text-xs font-mono text-blue-800 hover:underline">
        ← Back to Pay Fines
      </Link>

      <Card title={`Challan #${fine.id}`}>
        <dl className="grid grid-cols-2 gap-y-2 text-sm">
          <dt className="text-slate-600">Vehicle</dt>
          <dd className="font-mono font-semibold text-slate-900">{fine.number_plate}</dd>
          <dt className="text-slate-600">Violation</dt>
          <dd className="text-slate-900">{fine.violation_type}</dd>
          <dt className="text-slate-600">Issued</dt>
          <dd className="text-slate-900">{formatIstDate(fine.detected_at)}</dd>
          <dt className="text-slate-600">Amount</dt>
          <dd className="font-mono font-bold text-slate-900">{rupees(fine.fine_amount)}</dd>
          <dt className="text-slate-600">Status</dt>
          <dd className={fine.status === 'Paid' || receipt ? 'text-emerald-700' : 'text-red-700'}>
            {receipt ? 'Paid' : fine.status}
          </dd>
        </dl>
      </Card>

      {paid ? (
        <Card title="Payment receipt">
          <div role="status" className="space-y-1 text-sm">
            <p className="text-emerald-700 font-semibold">Payment recorded.</p>
            <p className="text-slate-700">
              Receipt no. <span className="font-mono text-slate-900">{paid.reference}</span>
            </p>
            <p className="text-slate-600 text-xs">
              {rupees(paid.amount)} paid on {formatIst(paid.paid_at)}
            </p>
            <Link to="/citizen/receipts" className="text-xs text-blue-800 hover:underline">
              View payment history →
            </Link>
          </div>
        </Card>
      ) : (
        <Card title="Pay this fine">
          <div className="space-y-4">
            {error && (
              <div role="alert" className="p-2 rounded border border-red-200 bg-red-50 text-xs text-red-700">
                {error}
              </div>
            )}
            <Select
              label="Payment method"
              value={method}
              onChange={(e) => setMethod(e.target.value as Method)}
              options={[
                { value: 'upi', label: 'UPI' },
                { value: 'card', label: 'Debit / credit card' },
                { value: 'netbanking', label: 'Net banking' },
              ]}
            />
            <p className="text-[11px] text-slate-500">
              Payment gateway is simulated in this version; the payment and its receipt are recorded on your account.
            </p>
            <Button variant="primary" onClick={pay} isLoading={busy} className="w-full">
              Pay {rupees(fine.fine_amount)}
            </Button>
          </div>
        </Card>
      )}
    </div>
  )
}
