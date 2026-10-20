import React, { useEffect, useState } from 'react'
import { mapApiUser, useAuthStore } from '@stores/authStore'
import { getMeApi } from '@api/auth'
import { Card, Input, Button, Spinner } from '@components/ui'
import { errorMessage, updateProfile } from '@api/portal'

const PHONE_RE = /^(?:\+91|91|0)?[6-9]\d{9}$/

/** Profile Settings: loaded from and saved to the user's record (PATCH /auth/me). */
export const CitizenProfile: React.FC = () => {
  const { setUser } = useAuthStore()
  const [loaded, setLoaded] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [errors, setErrors] = useState<{ name?: string; email?: string; phone?: string }>({})
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    // Always read the stored record, never a cached copy.
    getMeApi()
      .then((me) => {
        setName(me.full_name)
        setEmail(me.email)
        setPhone(me.phone ?? '')
        setLoaded(true)
      })
      .catch((err) => setMessage({ kind: 'error', text: errorMessage(err, 'Could not load your profile.') }))
  }, [])

  const validate = () => {
    const next: typeof errors = {}
    const cleanName = name.trim().replace(/\s+/g, ' ')
    if (cleanName.length < 2 || cleanName.length > 100) next.name = 'Enter your full name (2–100 characters).'
    else if (!/^[A-Za-z][A-Za-z .'-]*$/.test(cleanName)) next.name = "Use letters, spaces and . ' - only."
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) next.email = 'Enter a valid email address.'
    if (phone.trim() && !PHONE_RE.test(phone.replace(/[\s-]/g, ''))) next.phone = 'Enter a valid 10-digit Indian mobile number.'
    setErrors(next)
    return Object.keys(next).length === 0
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setMessage(null)
    if (!validate()) return
    setBusy(true)
    try {
      const saved = await updateProfile({ full_name: name, email: email.trim(), phone: phone.trim() || null })
      setName(saved.full_name)
      setEmail(saved.email)
      setPhone(saved.phone ?? '')
      setUser(mapApiUser(saved))
      setMessage({ kind: 'ok', text: 'Profile saved.' })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err, 'Could not save your profile.') })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-blue-950">Profile Settings</h2>
        <p className="text-sm text-slate-600">Your contact details on record.</p>
      </div>

      <Card title="Account details">
        {!loaded && !message ? (
          <Spinner />
        ) : (
          <form onSubmit={handleSave} className="space-y-4" noValidate>
            {message && (
              <div
                role={message.kind === 'ok' ? 'status' : 'alert'}
                className={`p-3 text-xs rounded font-mono border ${
                  message.kind === 'ok'
                    ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                    : 'bg-red-50 border-red-200 text-red-700'
                }`}
              >
                {message.text}
              </div>
            )}
            <Input label="Full name" value={name} onChange={(e) => setName(e.target.value)} error={errors.name} required />
            <Input
              label="Email address"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              error={errors.email}
              required
            />
            <Input
              label="Mobile number"
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              error={errors.phone}
              helperText="10-digit Indian mobile number; leave empty to remove"
            />
            <div className="pt-2">
              <Button type="submit" variant="primary" size="md" isLoading={busy} disabled={!loaded}>
                Save changes
              </Button>
            </div>
          </form>
        )}
      </Card>
    </div>
  )
}
