import React, { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuthStore } from '@stores/authStore'
import { OfficialAlert, OfficialField, OfficialFormCard, OfficialSubmit } from '@components/public/OfficialForm'

export const CitizenLogin: React.FC = () => {
  const navigate = useNavigate()
  const { loginWithCredentials, logout, isLoading, error, clearError } = useAuthStore()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [localError, setLocalError] = useState('')

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
    navigate('/citizen/dashboard')
  }

  return (
    <OfficialFormCard
      title="Citizen Login"
      subtitle="Sign in with the email and password of your citizen account."
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
          label="Email address"
          type="email"
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
    </OfficialFormCard>
  )
}
