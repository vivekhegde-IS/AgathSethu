import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuthStore } from '@stores/authStore'
import { Card, Input, Select, Button } from '@components/ui'

const IS_REAL_AUTH = import.meta.env.VITE_ENABLE_REAL_AUTH === 'true'

export const AuthoritySignup: React.FC = () => {
  const { registerAuthority, login, isLoading, error, clearError } = useAuthStore()

  const [name, setName] = useState('')
  const [badgeNo, setBadgeNo] = useState('')
  const [jurisdiction, setJurisdiction] = useState('Bangalore East Traffic Division')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [localError, setLocalError] = useState('')
  const [successMessage, setSuccessMessage] = useState('')

  const displayError = localError || error || ''

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLocalError('')
    setSuccessMessage('')
    clearError()

    if (IS_REAL_AUTH) {
      if (password !== confirmPassword) {
        setLocalError('Passwords do not match')
        return
      }
      if (password.length < 8) {
        setLocalError('Password must be at least 8 characters')
        return
      }

      const result = await registerAuthority({
        full_name: name,
        email,
        password,
        badge_number: badgeNo,
        jurisdiction,
      })

      if (result.success) {
        // Show pending message — do NOT auto-authenticate
        setSuccessMessage(result.message)
      }
    } else {
      // Mock mode — existing behavior
      login('authority', email || 'officer@trafficops.blr.gov.in', name || 'Enforcement Officer')
      // In mock mode, navigate to dashboard (existing demo behavior)
      window.location.href = '/authority/dashboard'
    }
  }

  // Success state — account submitted for review
  if (IS_REAL_AUTH && successMessage) {
    return (
      <div className="min-h-[80vh] flex items-center justify-center px-4 py-8">
        <div className="w-full max-w-md">
          <Card title="Request Submitted" glow>
            <div className="space-y-4 text-center">
              <div className="w-12 h-12 mx-auto rounded-full bg-cyan-500/20 border border-cyan-500/40 flex items-center justify-center">
                <span className="text-2xl">✅</span>
              </div>
              <p className="text-sm text-slate-300 leading-relaxed">{successMessage}</p>
              <p className="text-xs text-slate-500 font-mono">
                Once your account is approved, you will be able to log in at the TOC terminal.
              </p>
              <Link to="/authority/login">
                <Button variant="secondary" size="sm" className="w-full mt-2">
                  Return to Login
                </Button>
              </Link>
            </div>
          </Card>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-[80vh] flex items-center justify-center px-4 py-8">
      <div className="w-full max-w-md">
        <Card
          title="Officer Credential Verification"
          subtitle="Request secure access credentials for AGHAT SETHU Operations Platform"
          glow
        >
          <form onSubmit={handleSubmit} className="space-y-4">
            {displayError && (
              <div className="p-3 bg-red-950/60 border border-red-800 text-red-300 text-xs rounded">
                {displayError}
              </div>
            )}

            {!IS_REAL_AUTH && (
              <div className="p-2 bg-amber-950/40 border border-amber-800/50 text-amber-400 text-[10px] font-mono rounded">
                MOCK MODE — real authentication disabled
              </div>
            )}

            {IS_REAL_AUTH && (
              <div className="p-2 bg-slate-800/60 border border-slate-700 text-slate-400 text-[10px] font-mono rounded">
                ⚠ Authority accounts require admin approval before login is permitted.
              </div>
            )}

            <Input
              label="Full Name & Rank"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Sub-Inspector K. Ramesh"
              required
            />

            <Input
              label="Police / Traffic Badge Number"
              value={badgeNo}
              onChange={(e) => setBadgeNo(e.target.value.toUpperCase())}
              placeholder="e.g. KA-TP-9921"
              required
            />

            <Select
              label="Assigned Jurisdiction / Circle"
              value={jurisdiction}
              onChange={(e) => setJurisdiction(e.target.value)}
              options={[
                { value: 'Bangalore East Traffic Division', label: 'Bangalore East Traffic Division' },
                { value: 'Bangalore Central CBD', label: 'Bangalore Central CBD' },
                { value: 'Bangalore South (Koramangala/HSR)', label: 'Bangalore South (Koramangala/HSR)' },
                { value: 'Outer Ring Road Special Corridor', label: 'Outer Ring Road Special Corridor' },
              ]}
            />

            <Input
              label="Official Police Email ID"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="officer@trafficops.blr.gov.in"
              required
            />

            {IS_REAL_AUTH && (
              <>
                <Input
                  label="Password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Min. 8 characters"
                  required
                />
                <Input
                  label="Confirm Password"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Re-enter password"
                  required
                />
              </>
            )}

            <div className="pt-2">
              <Button
                type="submit"
                variant="primary"
                className="w-full"
                size="md"
                disabled={isLoading}
              >
                {isLoading ? 'Submitting…' : 'Submit Clearance Request'}
              </Button>
            </div>

            <div className="text-center pt-2">
              <p className="text-xs text-slate-400 font-mono">
                Already registered?{' '}
                <Link to="/authority/login" className="text-cyan-400 hover:underline">
                  Log in to TOC
                </Link>
              </p>
            </div>
          </form>
        </Card>
      </div>
    </div>
  )
}
