import React, { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuthStore } from '@stores/authStore'
import { OfficialAlert, OfficialField, OfficialFormCard, OfficialSubmit } from '@components/public/OfficialForm'
import { GoogleButton, useGoogleEnabled } from '@components/live/LiveWidgets'

export const CitizenLogin: React.FC = () => {
  const navigate = useNavigate()
  const { loginWithCredentials, logout, isLoading, error, clearError } = useAuthStore()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [localError, setLocalError] = useState('')
  // Vehicle owners only: the authority login page never shows this button
  const googleEnabled = useGoogleEnabled()

  const displayError = localError || error || ''

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLocalError('')
    clearError()
    const user = await loginWithCredentials(email.trim(), password)
    if (!user) return
    if (user.role !== 'citizen') {
      // Each role signs in through its own portal.
      logout()
      setLocalError('This account is an authority account. Please use Authority Login.')
      return
    }
    navigate('/me')
  }

  return (
    <OfficialFormCard
      title="Citizen Login"
      subtitle="Vehicle owners: sign in with your username (or email) and password."
      footer={
        <div className="flex flex-col gap-1">
          <span>
            New user?{' '}
            <Link to="/citizen/signup" className="text-blue-900 hover:underline">
              Create a citizen account
            </Link>
          </span>
          <span>
            Traffic authority officer?{' '}
            <Link to="/authority/login" className="text-blue-900 hover:underline">
              Authority Login
            </Link>
          </span>
        </div>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4" autoComplete="off">
        {displayError && <OfficialAlert>{displayError}</OfficialAlert>}
        <OfficialField
          label="Username or email"
          type="text"
          noAutofill
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <OfficialField
          label="Password"
          type="password"
          noAutofill
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <OfficialSubmit busy={isLoading} busyText="Signing in…">
          Sign in
        </OfficialSubmit>
      </form>
      {googleEnabled && (
        <div className="mt-4 space-y-2">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <span className="flex-1 border-t" />or<span className="flex-1 border-t" />
          </div>
          <GoogleButton purpose="login" onError={setLocalError} />
          <p className="text-xs text-slate-500">
            Works only for a Google account linked to your vehicle (link it on your /me page).
          </p>
        </div>
      )}
    </OfficialFormCard>
  )
}
