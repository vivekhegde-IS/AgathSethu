/**
 * AGHAT SETHU — ProtectedRoute
 *
 * Guards protected pages based on authentication state and user role.
 *
 * Handles three cases:
 *  1. isInitializing = true → show loading spinner (prevents flash-redirect
 *     on refresh while real-auth token validation is in progress)
 *  2. Not authenticated → redirect to login
 *  3. Wrong role → redirect to appropriate dashboard
 */

import React, { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuthStore, UserRole } from '@stores/authStore'

export interface ProtectedRouteProps {
  children: ReactNode
  roles?: UserRole[]
  redirectTo?: string
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({
  children,
  roles,
  redirectTo,
}) => {
  const { isAuthenticated, isInitializing, user } = useAuthStore()

  // ── Wait for auth initialization before making redirect decisions ──────────────
  // Without this, a valid user would be flash-redirected to /login on refresh
  // while the token is being validated against the backend.
  if (isInitializing) {
    return (
      <div className="min-h-screen bg-[#0a0e14] flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="w-10 h-10 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
          <p className="text-slate-400 text-sm font-mono tracking-wider">
            AUTHENTICATING…
          </p>
        </div>
      </div>
    )
  }

  // ── Not authenticated ─────────────────────────────────────────────────────────
  if (!isAuthenticated || !user) {
    const defaultRedirect =
      roles?.includes('citizen') ? '/citizen/login' : '/authority/login'
    return <Navigate to={redirectTo || defaultRedirect} replace />
  }

  // ── Role check ────────────────────────────────────────────────────────────────
  if (roles && roles.length > 0 && !roles.includes(user.role)) {
    // Redirect to appropriate portal rather than showing 403
    if (user.role === 'citizen') {
      return <Navigate to="/citizen/dashboard" replace />
    } else {
      return <Navigate to="/authority/dashboard" replace />
    }
  }

  return <>{children}</>
}
