import React, { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuthStore } from '@stores/authStore'
import { Card, Input, Button } from '@components/ui'

const IS_REAL_AUTH = import.meta.env.VITE_ENABLE_REAL_AUTH === 'true'

export const CitizenLogin: React.FC = () => {
  const navigate = useNavigate()
  const { login, loginWithCredentials, isLoading, error, clearError } = useAuthStore()

  const [email, setEmail] = useState(IS_REAL_AUTH ? '' : 'aarav.sharma@example.com')
  const [password, setPassword] = useState(IS_REAL_AUTH ? '' : 'password123')
  const [localError, setLocalError] = useState('')

  const displayError = localError || error || ''

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLocalError('')
    clearError()

    if (!email || !password) {
      setLocalError('Please provide your email and password')
      return
    }

    if (IS_REAL_AUTH) {
      const success = await loginWithCredentials(email, password)
      if (success) {
        navigate('/citizen/dashboard')
      }
      // error is set in authStore.error — displayed below
    } else {
      // Mock mode — existing behavior
      login('citizen', email, 'Aarav Sharma')
      navigate('/citizen/dashboard')
    }
  }

  return (
    <div className="min-h-[80vh] flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <Card
          title="Citizen Access Portal"
          subtitle="Sign in to view vehicle challans, manage FASTag, and settle fines"
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

            <Input
              label="Registered Email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="e.g. aarav.sharma@example.com"
              required
            />

            <Input
              label="Password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
            />

            <div className="pt-2">
              <Button
                type="submit"
                variant="primary"
                className="w-full"
                size="md"
                disabled={isLoading}
              >
                {isLoading ? 'Authenticating…' : 'Authenticate & Access Dashboard'}
              </Button>
            </div>

            <div className="text-center pt-2">
              <p className="text-xs text-slate-400 font-mono">
                Don't have an account?{' '}
                <Link to="/citizen/signup" className="text-cyan-400 hover:underline">
                  Register vehicle
                </Link>
              </p>
            </div>
          </form>
        </Card>
      </div>
    </div>
  )
}
