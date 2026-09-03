import React, { useState } from 'react'
import { useAuthStore } from '@stores/authStore'
import { Card, Input, Button } from '@components/ui'

export const CitizenProfile: React.FC = () => {
  const { user } = useAuthStore()
  const [name, setName] = useState(user?.name || 'Aarav Sharma')
  const [email, setEmail] = useState(user?.email || 'aarav.sharma@example.com')
  const [phone, setPhone] = useState('+91 98450 12345')
  const [saved, setSaved] = useState(false)

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-xl font-bold font-mono text-white">Citizen Profile & Contact Info</h2>
        <p className="text-xs text-slate-400 font-mono">
          Ensure your contact information is up to date for instantaneous challan SMS and WhatsApp alerts.
        </p>
      </div>

      <Card title="Account Details" glow>
        <form onSubmit={handleSave} className="space-y-4">
          {saved && (
            <div className="p-3 bg-emerald-950/60 border border-emerald-800 text-emerald-300 text-xs rounded font-mono">
              ✓ Profile information updated successfully.
            </div>
          )}

          <Input
            label="Full Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />

          <Input
            label="Registered Email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />

          <Input
            label="Mobile Number (SMS / WhatsApp Delivery)"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            required
          />

          <div className="pt-2">
            <Button type="submit" variant="primary" size="md">
              Save Changes
            </Button>
          </div>
        </form>
      </Card>
    </div>
  )
}
