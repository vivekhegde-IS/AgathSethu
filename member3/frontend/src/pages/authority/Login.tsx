import React, { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuthStore, UserRole } from '@stores/authStore'
import { Card, Input, Select, Button, Badge } from '@components/ui'

const IS_REAL_AUTH = import.meta.env.VITE_ENABLE_REAL_AUTH === 'true'

export const AuthorityLogin: React.FC = () => {
  const navigate = useNavigate()
  const { login, loginWithCredentials, isLoading, error, clearError } = useAuthStore()

  // Mock mode fields
  const [badgeNo, setBadgeNo] = useState('KA-TP-8841')
  const [role, setRole] = useState<UserRole>('authority')

  // Common fields
  const [email, setEmail] = useState(IS_REAL_AUTH ? '' : 'v.sen@trafficops.blr.gov.in')
  const [password, setPassword] = useState(IS_REAL_AUTH ? '' : 'command2026')
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
        navigate('/authority/dashboard')
      }
      // error displayed from authStore.error
    } else {
      // Mock mode — existing behavior
      login(role, email, 'Inspector Vikram Sen')
      navigate('/authority/dashboard')
    }
  }

  return (
    <div className="min-h-[80vh] flex items-center justify-center px-4 py-8">
      <div className="w-full max-w-md">
        <Card
          title="Tactical Command Center (TOC)"
          subtitle="Authorized Traffic Enforcement & Incident Investigation Terminal"
          glow
        >
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="flex items-center justify-between pb-2 border-b border-slate-800">
              <Badge variant="brand" size="sm" dot>
                SECURE TERMINAL
              </Badge>
              <span className="text-[10px] font-mono text-cyan-400">NODE: BLR-HQ-01</span>
            </div>

            {displayError && (
              <div className="p-3 bg-red-950/60 border border-red-800 text-red-300 text-xs rounded">
                {displayError}
              </div>
            )}

            {!IS_REAL_AUTH && (
              <>
                <div className="p-2 bg-amber-950/40 border border-amber-800/50 text-amber-400 text-[10px] font-mono rounded">
                  MOCK MODE — real authentication disabled
                </div>
                <Select
                  label="Operational Role"
                  value={role}
                  onChange={(e) => setRole(e.target.value as UserRole)}
                  options={[
                    { value: 'authority', label: 'Field Traffic Officer / Inspector' },
                    { value: 'admin', label: 'TOC Administrator / Lead Investigator' },
                  ]}
                />
                <Input
                  label="Officer Badge / Service ID"
                  value={badgeNo}
                  onChange={(e) => setBadgeNo(e.target.value.toUpperCase())}
                  placeholder="e.g. KA-TP-8841"
                />
              </>
            )}

            <Input
              label="Official Email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@trafficops.blr.gov.in"
              required
            />

            <Input
              label="Terminal Password"
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
                {isLoading ? 'Authenticating…' : 'Authenticate & Access TOC'}
              </Button>
            </div>

            <div className="text-center pt-2">
              <p className="text-xs text-slate-400 font-mono">
                Need operational clearance?{' '}
                <Link to="/authority/signup" className="text-cyan-400 hover:underline">
                  Submit badge request
                </Link>
              </p>
            </div>
          </form>
        </Card>
      </div>
    </div>
  )
}
