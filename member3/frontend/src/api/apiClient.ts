/**
 * AGHAT SETHU — Centralized Axios API Client
 *
 * Base URL: VITE_API_BASE_URL (e.g., http://localhost:8000/api)
 *
 * Attaches JWT from localStorage to every authenticated request.
 * Uses a plain localStorage read — no import from authStore —
 * to avoid circular dependency: apiClient ↔ authStore ↔ auth API.
 *
 * On 401: dispatches a custom window event so authStore can react
 * without a direct import cycle.
 */

import axios, { AxiosInstance, InternalAxiosRequestConfig } from 'axios'

const TOKEN_KEY = 'aghat_access_token'

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
    const token = localStorage.getItem(TOKEN_KEY)
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
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export default apiClient
