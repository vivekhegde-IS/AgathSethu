/**
 * AGHAT SETHU — Centralized Axios API Client
 *
 * Base URL: VITE_API_BASE_URL (e.g., http://localhost:8001/api)
 *
 * Attaches the JWT to every authenticated request as a Bearer header.
 *
 * PER-TAB SESSIONS: the token lives in sessionStorage, which every browser tab
 * has its own copy of. So /authority (authority login) and /me (an owner
 * login) can be open side by side in the same browser without one login
 * replacing the other - a shared cookie or localStorage would. The same token
 * authenticates the /ws/events socket. A new tab starts logged out.
 *
 * Uses a plain sessionStorage read — no import from authStore —
 * to avoid circular dependency: apiClient ↔ authStore ↔ auth API.
 *
 * On 401: dispatches a custom window event so authStore can react
 * without a direct import cycle.
 */

import axios, { AxiosInstance, InternalAxiosRequestConfig } from 'axios'

const TOKEN_KEY = 'aghat_access_token'

// Older builds kept the token in localStorage (shared by all tabs): drop it.
try {
  localStorage.removeItem(TOKEN_KEY)
} catch {
  /* storage unavailable */
}

// ── Create Axios instance ───────────────────────────────────────────────────────
const apiClient: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api',
  timeout: 15_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ── Request interceptor — attach JWT ────────────────────────────────────────────
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = getToken()
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// ── Response interceptor — handle 401 ───────────────────────────────────────────
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Dispatch event — authStore listens for this to trigger logout
      window.dispatchEvent(new CustomEvent('aghat:unauthorized'))
    }
    return Promise.reject(error)
  }
)

// ── Token helpers ────────────────────────────────────────────────────────────────
export function saveToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY)
}

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

/** ws(s)://host[:port]/ws/events, derived from the API base URL. */
export function getEventsSocketUrl(): string {
  const api = new URL(getApiBaseUrl(), window.location.href)
  const protocol = api.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${api.host}/ws/events`
}

export function getApiBaseUrl(): string {
  return import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'
}

export default apiClient
