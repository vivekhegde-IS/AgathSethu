/**
 * AGHAT SETHU — Authentication Store
 *
 * Central Zustand authentication state.
 *
 * Two modes controlled by VITE_ENABLE_REAL_AUTH:
 *
 *   VITE_ENABLE_REAL_AUTH=false (default)
 *   → Mock mode: pre-authenticated authority demo user. Existing behavior preserved.
 *
 *   VITE_ENABLE_REAL_AUTH=true
 *   → Real mode: all auth comes from FastAPI + PostgreSQL.
 *     - Starts unauthenticated.
 *     - On app startup, calls initializeAuth() to restore session from localStorage JWT.
 *     - loginWithCredentials() hits real API.
 *     - logout() clears localStorage token.
 *
 * NOTE: VITE_ENABLE_REAL_AUTH is intentionally SEPARATE from VITE_ENABLE_MOCK_DATA.
 * This allows: real auth + mock CARLA/ANPR/RFID sensor data simultaneously.
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

  // Mock mode functions (preserved for VITE_ENABLE_REAL_AUTH=false)
  login: (role: UserRole, email: string, name?: string) => void

  // Real auth functions (used when VITE_ENABLE_REAL_AUTH=true)
  loginWithCredentials: (email: string, password: string) => Promise<boolean>
  registerCitizen: (data: CitizenRegisterRequest) => Promise<{ success: boolean; message: string }>
  registerAuthority: (data: AuthorityRegisterRequest) => Promise<{ success: boolean; message: string }>
  initializeAuth: () => Promise<void>

  // Universal
  logout: () => void
  clearError: () => void
}

// ── Feature flag ──────────────────────────────────────────────────────────────────
const IS_REAL_AUTH = import.meta.env.VITE_ENABLE_REAL_AUTH === 'true'

// ── Mock pre-authenticated authority user ─────────────────────────────────────────
// Preserved for VITE_ENABLE_REAL_AUTH=false (existing demo behavior)
const MOCK_AUTHORITY_USER: User = {
  id: 'USR-AUTH-001',
  name: 'Inspector Vikram Sen',
  email: 'v.sen@trafficops.blr.gov.in',
  role: 'authority',
  badgeNumber: 'KA-TP-8841',
  phone: '+91 98450 12345',
}

// ── Helper: map API UserResponse → authStore User ─────────────────────────────────
function mapApiUser(apiUser: UserResponse): User {
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
  // ── Initial State ──────────────────────────────────────────────────────────────
  // In mock mode: pre-authenticated authority demo user (existing behavior)
  // In real mode: unauthenticated until initializeAuth() completes
  user: IS_REAL_AUTH ? null : MOCK_AUTHORITY_USER,
  token: IS_REAL_AUTH ? null : 'mock-jwt-token-aghat-sethu',
  isAuthenticated: !IS_REAL_AUTH,
  isLoading: false,
  isInitializing: IS_REAL_AUTH, // real mode: true until initializeAuth() finishes
  error: null,

  // ── Mock login (preserved for demo mode) ──────────────────────────────────────
  login: (role: UserRole, email: string, name?: string) => {
    if (IS_REAL_AUTH) {
      console.warn('[authStore] login() called in real-auth mode — use loginWithCredentials() instead')
      return
    }
    set({
      user: {
        id: `USR-${Date.now()}`,
        name: name || (role === 'citizen' ? 'Aarav Sharma' : 'Officer Vikram Sen'),
        email,
        role,
        badgeNumber: role !== 'citizen' ? 'KA-TP-9901' : undefined,
      },
      token: `jwt-session-${Date.now()}`,
      isAuthenticated: true,
      error: null,
    })
  },

  // ── Real login ─────────────────────────────────────────────────────────────────
  loginWithCredentials: async (email: string, password: string): Promise<boolean> => {
    set({ isLoading: true, error: null })
    try {
      const response = await loginApi({ email, password })
      saveToken(response.access_token)
      set({
        user: mapApiUser(response.user),
        token: response.access_token,
        isAuthenticated: true,
        isLoading: false,
        error: null,
      })
      return true
    } catch (err) {
      const message = extractAuthError(err)
      set({ isLoading: false, isAuthenticated: false, error: message })
      return false
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
    if (!IS_REAL_AUTH) {
      // Mock mode — no initialization needed
      set({ isInitializing: false })
      return
    }

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
    if (IS_REAL_AUTH) {
      // Fire-and-forget backend logout (stateless JWT — best effort)
      logoutApi().catch(() => {})
      clearToken()
    }
    set({
      user: null,
      token: null,
      isAuthenticated: false,
      error: null,
    })
  },

  // ── Clear error ────────────────────────────────────────────────────────────────
  clearError: () => set({ error: null }),
}))

// ── 401 listener — triggers logout when API returns unauthorized ──────────────────
// Avoids circular import: apiClient → authStore → apiClient
if (IS_REAL_AUTH) {
  window.addEventListener('aghat:unauthorized', () => {
    const { logout } = useAuthStore.getState()
    logout()
  })
}
