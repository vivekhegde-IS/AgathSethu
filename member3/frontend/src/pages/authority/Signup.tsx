import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuthStore } from '@stores/authStore'
import { OfficialAlert, OfficialField, OfficialFormCard, OfficialSubmit } from '@components/public/OfficialForm'

export const AuthoritySignup: React.FC = () => {
  const { registerAuthority, isLoading, error, clearError } = useAuthStore()

  const [name, setName] = useState('')
  const [badgeNo, setBadgeNo] = useState('')
  const [jurisdiction, setJurisdiction] = useState('')
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
      jurisdiction: jurisdiction || undefined,
    })
    // The account is created as pending approval; it is never signed in here.
    if (result.success) setSuccessMessage(result.message)
  }

  if (successMessage) {
    return (
      <OfficialFormCard title="Request submitted" subtitle="Your officer account is awaiting approval.">
        <div className="space-y-4">
          <OfficialAlert kind="success">{successMessage}</OfficialAlert>
          <p className="text-sm text-slate-600">You can sign in once an administrator approves the account.</p>
          <Link to="/authority/login" className="text-sm text-blue-900 hover:underline">
            Go to Authority Login
          </Link>
        </div>
      </OfficialFormCard>
    )
  }

  return (
    <OfficialFormCard
      title="Request an officer account"
      subtitle="Accounts are activated only after an administrator verifies the badge number."
      footer={
        <span>
          Already approved?{' '}
          <Link to="/authority/login" className="text-blue-900 hover:underline">
            Authority Login
          </Link>
        </span>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {displayError && <OfficialAlert>{displayError}</OfficialAlert>}
        <OfficialField label="Full name" value={name} onChange={(e) => setName(e.target.value)} required />
        <OfficialField
          label="Badge / service number"
          value={badgeNo}
          onChange={(e) => setBadgeNo(e.target.value.toUpperCase())}
          required
        />
        <OfficialField
          label="Jurisdiction / unit"
          value={jurisdiction}
          onChange={(e) => setJurisdiction(e.target.value)}
        />
        <OfficialField
          label="Official email address"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <OfficialField
          label="Password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          hint="At least 8 characters"
          required
        />
        <OfficialField
          label="Confirm password"
          type="password"
          autoComplete="new-password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          required
        />
        <OfficialSubmit busy={isLoading} busyText="Submitting…">
          Submit request
        </OfficialSubmit>
      </form>
    </OfficialFormCard>
  )
}
