import React, { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useViolationStore } from '@stores/violationStore'
import { Card, Button, Input } from '@components/ui'

export const CitizenPaymentDetail: React.FC = () => {
  const { paymentId } = useParams<{ paymentId: string }>()
  const { violations, payViolationFine } = useViolationStore()

  const violation = violations.find((v) => v.violation_id === paymentId) || violations[0]
  const [method, setMethod] = useState<'upi' | 'card' | 'netbanking'>('upi')
  const [upiId, setUpiId] = useState('aarav@okaxis')
  const [isProcessing, setIsProcessing] = useState(false)
  const [successTxId, setSuccessTxId] = useState<string | null>(null)

  const handlePay = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsProcessing(true)
    setTimeout(async () => {
      const txId = await payViolationFine(violation.violation_id, method)
      setIsProcessing(false)
      setSuccessTxId(txId)
    }, 1200)
  }

  if (successTxId) {
    return (
      <div className="max-w-md mx-auto py-12">
        <Card glow className="text-center space-y-4">
          <div className="w-16 h-16 rounded-full bg-emerald-950 border border-emerald-500 text-emerald-400 text-3xl flex items-center justify-center mx-auto shadow-glow">
            ✓
          </div>
          <h2 className="text-xl font-bold font-mono text-white">Payment Successful</h2>
          <p className="text-xs text-slate-300 font-mono">
            Transaction ID: <strong className="text-cyan-300">{successTxId}</strong>
          </p>
          <div className="p-4 bg-[#121820] rounded border border-slate-800 text-xs font-mono text-left space-y-1">
            <div className="flex justify-between">
              <span className="text-slate-400">Challan ID:</span>
              <span className="text-white">{violation.violation_id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Amount Paid:</span>
              <span className="text-emerald-400 font-bold">₹{violation.fineAmount}.00</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Time:</span>
              <span className="text-slate-300">{new Date().toLocaleString()}</span>
            </div>
          </div>
          <div className="pt-3 flex items-center justify-center gap-3">
            <Link to="/citizen/receipts">
              <Button variant="primary" size="sm">
                View Receipt
              </Button>
            </Link>
            <Link to="/citizen/dashboard">
              <Button variant="secondary" size="sm">
                Dashboard
              </Button>
            </Link>
          </div>
        </Card>
      </div>
    )
  }

  return (
    <div className="max-w-xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold font-mono text-white">Electronic Fine Settlement</h2>
          <p className="text-xs text-slate-400 font-mono">Secured e-Challan Payment Gateway</p>
        </div>
        <Link to="/citizen/payments">
          <Button variant="secondary" size="sm">
            ← Back
          </Button>
        </Link>
      </div>

      <Card title="Challan Summary" glow>
        <div className="space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div>
              <span className="text-xs font-mono text-cyan-400 font-semibold">{violation.violation_id}</span>
              <p className="text-sm font-bold text-white mt-0.5">{violation.violation_type}</p>
              <p className="text-xs text-slate-400">{violation.location}</p>
            </div>
            <div className="text-right">
              <span className="text-xs font-mono text-slate-400 block">Total Due</span>
              <span className="text-2xl font-mono font-bold text-red-400">₹{violation.fineAmount}</span>
            </div>
          </div>

          <form onSubmit={handlePay} className="space-y-4 pt-2">
            <label className="block text-xs font-mono font-semibold text-slate-300 uppercase">
              Select Payment Method
            </label>
            <div className="grid grid-cols-3 gap-3">
              {[
                { id: 'upi', label: 'UPI / QR', icon: '📱' },
                { id: 'card', label: 'Debit / Credit', icon: '💳' },
                { id: 'netbanking', label: 'NetBanking', icon: '🏦' },
              ].map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => setMethod(m.id as 'upi' | 'card' | 'netbanking')}
                  className={`p-3 rounded border text-center font-mono text-xs transition-all ${
                    method === m.id
                      ? 'border-aghat-blue bg-blue-950/40 text-cyan-300 font-bold shadow-glow'
                      : 'border-slate-800 bg-[#121820] text-slate-400 hover:border-slate-700'
                  }`}
                >
                  <span className="text-lg block mb-1">{m.icon}</span>
                  {m.label}
                </button>
              ))}
            </div>

            {method === 'upi' && (
              <Input
                label="Virtual Payment Address (VPA / UPI ID)"
                value={upiId}
                onChange={(e) => setUpiId(e.target.value)}
                placeholder="username@bank"
                required
              />
            )}

            {method === 'card' && (
              <div className="space-y-3">
                <Input label="Card Number" placeholder="4532 •••• •••• 8821" required />
                <div className="grid grid-cols-2 gap-3">
                  <Input label="Expiry (MM/YY)" placeholder="08/29" required />
                  <Input label="CVV" placeholder="•••" type="password" required />
                </div>
              </div>
            )}

            <Button
              type="submit"
              variant="danger"
              size="lg"
              className="w-full mt-4"
              isLoading={isProcessing}
            >
              Pay ₹{violation.fineAmount} Now
            </Button>
          </form>
        </div>
      </Card>
    </div>
  )
}
