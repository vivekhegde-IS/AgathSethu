/**
 * /auth/google/done — where the backend's Google callback lands THIS tab.
 * Redeems the one-time hand-off code with this tab's nonce (sessionStorage),
 * so the session is created only in the tab that started the sign-in.
 */

import React, { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { exchangeGoogleHandoff } from '@api/live'
import { extractAuthError } from '@api/auth'
import { useAuthStore } from '@stores/authStore'
import { OfficialAlert, OfficialFormCard } from '@components/public/OfficialForm'

const ERRORS: Record<string, string> = {
  invalid_state: 'This sign-in request is invalid or has expired. Please try again.',
  cancelled: 'Google sign-in was cancelled.',
}

export const GoogleDone: React.FC = () => {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const setSession = useAuthStore((s) => s.setSession)
  const [error, setError] = useState('')
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true
    const failure = params.get('error')
    const handoff = params.get('handoff')
    if (failure || !handoff) {
      setError(ERRORS[failure ?? ''] ?? 'Google sign-in failed.')
      return
    }
    exchangeGoogleHandoff(handoff)
      .then((result) => {
        if ('access_token' in result) {
          setSession(result.access_token, result.user)
          navigate('/me', { replace: true })
        } else {
          navigate('/me?linked=1', { replace: true })
        }
      })
      .catch((e) => setError(extractAuthError(e)))
  }, [params, navigate, setSession])

  return (
    <OfficialFormCard title="Sign in with Google" subtitle={error ? '' : 'Completing sign-in…'}
      footer={<Link to="/citizen/login" className="text-blue-900 hover:underline">Back to owner login</Link>}>
      {error && <OfficialAlert>{error}</OfficialAlert>}
    </OfficialFormCard>
  )
}
