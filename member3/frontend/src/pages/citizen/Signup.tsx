import React, { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuthStore } from '@stores/authStore'
import { Card, Input, Button } from '@components/ui'

const IS_REAL_AUTH = import.meta.env.VITE_ENABLE_REAL_AUTH === 'true'

export const CitizenSignup: React.FC = () => {
  const navigate = useNavigate()
  const { login, registerCitizen, isLoading, error, clearError } = useAuthStore()

  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [vehiclePlate, setVehiclePlate] = useState('')
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

      const result = await registerCitizen({
        full_name: fullName,
        email,
        password,
        phone: phone || undefined,
        vehicle_plate: vehiclePlate || undefined,
      })

      if (result.success) {
        setSuccessMessage(result.message + ' Redirecting to login…')
        setTimeout(() => navigate('/citizen/login'), 2000)
      }
    } else {
      // Mock mode — existing behavior
      login('citizen', email || 'citizen@example.com', fullName || 'Citizen User')
      navigate('/citizen/dashboard')
    }
  }

  return (
    <div className="min-h-[80vh] flex items-center justify-center px-4 py-8">
      <div className="w-full max-w-md">
        <Card
          title="Citizen Vehicle Registration"
          subtitle="Create an account to link your FASTag and receive instant e-challan alerts"
          glow
        >
          <form onSubmit={handleSubmit} className="space-y-4">
            {displayError && (
              <div className="p-3 bg-red-950/60 border border-red-800 text-red-300 text-xs rounded">
                {displayError}
              </div>
            )}

            {successMessage && (
              <div className="p-3 bg-green-950/60 border border-green-800 text-green-300 text-xs rounded">
                {successMessage}
              </div>
            )}

            {!IS_REAL_AUTH && (
              <div className="p-2 bg-amber-950/40 border border-amber-800/50 text-amber-400 text-[10px] font-mono rounded">
                MOCK MODE — real authentication disabled
              </div>
            )}

            <Input
              label="Full Name"
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="e.g. Aarav Sharma"
              required
            />

            <Input
              label="Email Address"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="aarav@example.com"
              required
            />

            <Input
              label="Mobile Number"
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+91 98450 XXXXX"
            />

            <Input
              label="Primary Vehicle Registration (Plate #)"
              type="text"
              value={vehiclePlate}
              onChange={(e) => setVehiclePlate(e.target.value.toUpperCase())}
              placeholder="KA01MJ4582"
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
                {isLoading ? 'Registering…' : 'Complete Registration'}
              </Button>
            </div>

            <div className="text-center pt-2">
              <p className="text-xs text-slate-400 font-mono">
                Already registered?{' '}
                <Link to="/citizen/login" className="text-cyan-400 hover:underline">
                  Sign in here
                </Link>
              </p>
            </div>
          </form>
        </Card>
      </div>
    </div>
  )
}
