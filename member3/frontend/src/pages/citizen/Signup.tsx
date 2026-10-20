import React, { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuthStore } from '@stores/authStore'
import { OfficialAlert, OfficialField, OfficialFormCard, OfficialSubmit } from '@components/public/OfficialForm'

export const CitizenSignup: React.FC = () => {
  const navigate = useNavigate()
  const { registerCitizen, isLoading, error, clearError } = useAuthStore()

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
  }

  return (
    <OfficialFormCard
      title="Create a citizen account"
      subtitle="Register to see e-challans for your vehicles and pay them online."
      footer={
        <span>
          Already registered?{' '}
          <Link to="/citizen/login" className="text-blue-900 hover:underline">
            Citizen Login
          </Link>
        </span>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {displayError && <OfficialAlert>{displayError}</OfficialAlert>}
        {successMessage && <OfficialAlert kind="success">{successMessage}</OfficialAlert>}
        <OfficialField label="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
        <OfficialField
          label="Email address"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <OfficialField
          label="Mobile number"
          type="tel"
          autoComplete="tel"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          hint="10-digit Indian mobile number"
        />
        <OfficialField
          label="Vehicle registration number"
          value={vehiclePlate}
          onChange={(e) => setVehiclePlate(e.target.value.toUpperCase())}
          hint="As printed on the number plate, e.g. KA01AB1234"
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
        <OfficialSubmit busy={isLoading} busyText="Registering…">
          Register
        </OfficialSubmit>
      </form>
    </OfficialFormCard>
  )
}
