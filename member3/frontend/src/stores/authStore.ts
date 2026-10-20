/**
 * AGHAT SETHU — Authentication Store
 *
 * Central Zustand authentication state. All auth comes from FastAPI + PostgreSQL:
 *   - Starts unauthenticated.
 *   - initializeAuth() restores a session from the stored JWT, validated by /auth/me.
 *   - loginWithCredentials() hits the real login API.
 *   - logout() clears the stored token.
 * There is no mock / pre-authenticated mode: every protected page needs a real login,
 * and the backend enforces the role on every protected endpoint.
 */

import { create } from 'zustand'
import { clearToken, saveToken } from '@api/apiClient'
import {
  CitizenRegisterRequest,
  extractAuthError,
  getMeApi,
  loginApi,
  logoutApi,
  registerCitizenApi,
  registerAuthorityApi,
  AuthorityRegisterRequest,
  UserResponse,
} from '@api/auth'

// ── Types ─────────────────────────────────────────────────────────────────────────
export type UserRole = 'citizen' | 'authority' | 'admin'

export interface User {
  id: string
  name: string
  email: string
  role: UserRole
  badgeNumber?: string
  phone?: string
  avatarUrl?: string
  jurisdiction?: string
  status?: string
}

interface AuthState {
  // Core auth state
  user: User | null
  token: string | null
  isAuthenticated: boolean

  // Loading states
  isLoading: boolean       // login/register in progress
  isInitializing: boolean  // app startup session restore in progress
  error: string | null

  /** Resolves to the logged-in user, or null on failure (error is set). */
  loginWithCredentials: (email: string, password: string) => Promise<User | null>
  registerCitizen: (data: CitizenRegisterRequest) => Promise<{ success: boolean; message: string }>
  registerAuthority: (data: AuthorityRegisterRequest) => Promise<{ success: boolean; message: string }>
  initializeAuth: () => Promise<void>

  logout: () => void
  setUser: (user: User) => void
  clearError: () => void
}

// ── Helper: map API UserResponse → authStore User ─────────────────────────────────
export function mapApiUser(apiUser: UserResponse): User {
  return {
    id: apiUser.id,
    name: apiUser.full_name,
    email: apiUser.email,
    role: apiUser.role,
    badgeNumber: apiUser.badge_number,
    phone: apiUser.phone,
    jurisdiction: apiUser.jurisdiction,
    status: apiUser.status,
  }
}

// ── Store ─────────────────────────────────────────────────────────────────────────
export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: null,
  isAuthenticated: false,
  isLoading: false,
  isInitializing: true, // true until initializeAuth() finishes
  error: null,

  // ── Real login ─────────────────────────────────────────────────────────────────
  loginWithCredentials: async (email: string, password: string): Promise<User | null> => {
    set({ isLoading: true, error: null })
    try {
      const response = await loginApi({ email, password })
      saveToken(response.access_token)
      const user = mapApiUser(response.user)
      set({
        user,
        token: response.access_token,
        isAuthenticated: true,
        isLoading: false,
        error: null,
      })
      return user
    } catch (err) {
      const message = extractAuthError(err)
      set({ isLoading: false, isAuthenticated: false, error: message })
      return null
    }
  },

  // ── Citizen registration ───────────────────────────────────────────────────────
  registerCitizen: async (data: CitizenRegisterRequest) => {
    set({ isLoading: true, error: null })
    try {
      const response = await registerCitizenApi(data)
      set({ isLoading: false })
      return { success: true, message: response.message }
    } catch (err) {
      const message = extractAuthError(err)
      set({ isLoading: false, error: message })
      return { success: false, message }
    }
  },

  // ── Authority registration (creates pending_approval account) ─────────────────
  registerAuthority: async (data: AuthorityRegisterRequest) => {
    set({ isLoading: true, error: null })
    try {
      const response = await registerAuthorityApi(data)
      set({ isLoading: false })
      return { success: true, message: response.message }
    } catch (err) {
      const message = extractAuthError(err)
      set({ isLoading: false, error: message })
      return { success: false, message }
    }
  },

  // ── Auth initialization (called once on app startup in real-auth mode) ─────────
  initializeAuth: async () => {
    const { getToken } = await import('@api/apiClient')
    const token = getToken()

    if (!token) {
      // No stored token — remain unauthenticated
      set({ isInitializing: false, isAuthenticated: false })
      return
    }

    try {
      // Validate token with the backend — don't trust localStorage alone
      const apiUser = await getMeApi()
      set({
        user: mapApiUser(apiUser),
        token,
        isAuthenticated: true,
        isInitializing: false,
      })
    } catch {
      // Token expired or invalid — clear it and stay logged out
      clearToken()
      set({
        user: null,
        token: null,
        isAuthenticated: false,
        isInitializing: false,
      })
    }
  },

  // ── Logout ─────────────────────────────────────────────────────────────────────
  logout: () => {
    // Fire-and-forget backend logout (stateless JWT — best effort)
    logoutApi().catch(() => {})
    clearToken()
    set({
      user: null,
      token: null,
      isAuthenticated: false,
      error: null,
    })
  },

  // ── Replace the user after a profile save (value comes from the API) ──────────
  setUser: (user: User) => set({ user }),

  // ── Clear error ────────────────────────────────────────────────────────────────
  clearError: () => set({ error: null }),
}))

// ── 401 listener — triggers logout when API returns unauthorized ──────────────────
// Avoids circular import: apiClient → authStore → apiClient
window.addEventListener('aghat:unauthorized', () => {
  const { isAuthenticated, logout } = useAuthStore.getState()
  if (isAuthenticated) logout()
})
