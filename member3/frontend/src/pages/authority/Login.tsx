import React, { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuthStore } from '@stores/authStore'
import { OfficialAlert, OfficialField, OfficialFormCard, OfficialSubmit } from '@components/public/OfficialForm'

export const AuthorityLogin: React.FC = () => {
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
    if (user.role === 'citizen') {
      // Each role signs in through its own portal.
      logout()
      setLocalError('This account is a citizen account. Please use Citizen Login.')
      return
    }
    navigate('/authority/dashboard')
  }

  return (
    <OfficialFormCard
      title="Authority Login"
      subtitle="For authorised traffic police and control-room officers only. Access is logged."
      footer={
        <div className="flex flex-col gap-1">
          <span>
            Need access?{' '}
            <Link to="/authority/signup" className="text-blue-900 hover:underline">
              Request an officer account
            </Link>{' '}
            (approved by an administrator)
          </span>
          <span>
            Citizen?{' '}
            <Link to="/citizen/login" className="text-blue-900 hover:underline">
              Citizen Login
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
    </OfficialFormCard>
  )
}
