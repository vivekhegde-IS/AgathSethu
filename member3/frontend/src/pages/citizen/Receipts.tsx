import React from 'react'
import { Card } from '@components/ui'
import { PaymentHistory } from '@components/citizen/PaymentHistory'

/** Payment History: every fine payment on the account, with its receipt number. */
export const CitizenReceipts: React.FC = () => (
  <div className="space-y-6">
    <div>
      <h2 className="text-2xl font-semibold text-blue-950">Payment History</h2>
      <p className="text-sm text-slate-600">Keep the receipt number for any query about a payment.</p>
    </div>
    <Card>
      <PaymentHistory />
    </Card>
  </div>
)
