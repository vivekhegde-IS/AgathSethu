/**
 * AGHAT SETHU — Auth API Functions
 *
 * Thin wrappers around the centralized apiClient.
 * All auth HTTP calls go through here — NOT scattered in components.
 *
 * Backend base: VITE_API_BASE_URL = http://localhost:8000/api
 * Endpoints:
 *   POST /auth/register/citizen
 *   POST /auth/register/authority
 *   POST /auth/login
 *   GET  /auth/me
 *   POST /auth/logout
 */

import apiClient from './apiClient'

// ── Request / Response types ────────────────────────────────────────────────────

export interface LoginRequest {
  email: string
  password: string
}

export interface CitizenRegisterRequest {
  full_name: string
  email: string
  password: string
  phone?: string
  vehicle_plate?: string
}

export interface AuthorityRegisterRequest {
  full_name: string
  email: string
  password: string
  badge_number: string
  jurisdiction?: string
  phone?: string
}

export interface UserResponse {
  id: string
  email: string
  full_name: string
  role: 'citizen' | 'authority' | 'admin'
  status: 'active' | 'pending_approval' | 'suspended'
  badge_number?: string
  phone?: string
  jurisdiction?: string
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user: UserResponse
}

export interface RegisterResponse {
  message: string
  user_id: string
  status: string
}

// ── API Functions ────────────────────────────────────────────────────────────────

/**
 * POST /auth/login
 * Returns JWT token + user info.
 */
export async function loginApi(data: LoginRequest): Promise<TokenResponse> {
  const response = await apiClient.post<TokenResponse>('/auth/login', data)
  return response.data
}

/**
 * POST /auth/register/citizen
 * Registers a citizen account (status=active immediately).
 */
export async function registerCitizenApi(data: CitizenRegisterRequest): Promise<RegisterResponse> {
  const response = await apiClient.post<RegisterResponse>('/auth/register/citizen', data)
  return response.data
}

/**
 * POST /auth/register/authority
 * Submits an authority account request (status=pending_approval).
 */
export async function registerAuthorityApi(data: AuthorityRegisterRequest): Promise<RegisterResponse> {
  const response = await apiClient.post<RegisterResponse>('/auth/register/authority', data)
  return response.data
}

/**
 * GET /auth/me
 * Returns the profile of the currently authenticated user.
 * Used to validate token on app startup.
 */
export async function getMeApi(): Promise<UserResponse> {
  const response = await apiClient.get<UserResponse>('/auth/me')
  return response.data
}

/**
 * POST /auth/logout
 * Stateless — token is NOT server-side revoked in Phase 1.
 * Frontend should clear token and state regardless of response.
 */
export async function logoutApi(): Promise<void> {
  try {
    await apiClient.post('/auth/logout')
  } catch {
    // Ignore — logout is best-effort on the backend
  }
}

/**
 * Extract a readable error message from an Axios error.
 */
export function extractAuthError(error: unknown): string {
  if (error && typeof error === 'object' && 'response' in error) {
    const axiosError = error as { response?: { data?: { detail?: string } } }
    if (axiosError.response?.data?.detail) {
      return axiosError.response.data.detail
    }
  }
  if (error instanceof Error) {
    return error.message
  }
  return 'An unexpected error occurred. Please try again.'
}
