/**
 * Small shared pieces of the live dashboards: toasts, connection pill,
 * status badges and the "Sign in with Google" button.
 */

import React, { useCallback, useEffect, useState } from 'react'
import { Toast } from '@components/ui/Toast'
import type { LiveStatus } from '@hooks/useLiveEvents'
import { getGoogleConfig, startGoogle } from '@api/live'
import { extractAuthError } from '@api/auth'

// ── toasts ────────────────────────────────────────────────────────────────────────
export interface ToastItem {
  id: number
  type: 'success' | 'warning' | 'danger' | 'info'
  title: string
  message?: string
}

let toastSeq = 0

export function useToasts() {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), [])
  const push = useCallback((toast: Omit<ToastItem, 'id'>) => {
    const id = ++toastSeq
    setToasts((all) => [...all.slice(-3), { ...toast, id }])
    setTimeout(() => dismiss(id), toast.type === 'danger' ? 12_000 : 7_000)
  }, [dismiss])
  return { toasts, push, dismiss }
}

export const ToastStack: React.FC<{ toasts: ToastItem[]; onClose: (id: number) => void }> = ({ toasts, onClose }) => (
  <div className="fixed top-4 right-4 z-50 flex flex-col gap-2" role="status" aria-live="polite">
    {toasts.map((t) => (
      <Toast key={t.id} type={t.type} title={t.title} message={t.message} onClose={() => onClose(t.id)} />
    ))}
  </div>
)

// ── connection pill ──────────────────────────────────────────────────────────────
export const LivePill: React.FC<{ status: LiveStatus }> = ({ status }) => {
  const style = {
    live: 'bg-green-100 text-green-800 border-green-300',
    connecting: 'bg-amber-100 text-amber-800 border-amber-300',
    offline: 'bg-slate-200 text-slate-700 border-slate-300',
  }[status]
  const label = { live: 'Live', connecting: 'Connecting…', offline: 'Offline – retrying' }[status]
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-semibold ${style}`}>
      <span className={`w-2 h-2 rounded-full ${status === 'live' ? 'bg-green-600 animate-pulse' : 'bg-current'}`} />
      {label}
    </span>
  )
}

export const FineStatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const style = {
    issued: 'bg-amber-100 text-amber-900',
    paid: 'bg-green-100 text-green-900',
    disputed: 'bg-purple-100 text-purple-900',
  }[status] ?? 'bg-slate-100 text-slate-800'
  return <span className={`px-2 py-0.5 rounded text-xs font-semibold uppercase ${style}`}>{status}</span>
}

export const rupees = (n: number) => `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

export const when = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—'

// ── Sign in with Google (owners only) ────────────────────────────────────────────
export function useGoogleEnabled(): boolean {
  const [enabled, setEnabled] = useState(false)
  useEffect(() => {
    getGoogleConfig().then((c) => setEnabled(c.enabled)).catch(() => setEnabled(false))
  }, [])
  return enabled
}

export const GoogleButton: React.FC<{ purpose: 'login' | 'link'; label?: string; onError?: (m: string) => void }> = ({
  purpose, label, onError,
}) => {
  const [busy, setBusy] = useState(false)
  return (
    <button
      type="button"
      disabled={busy}
      onClick={async () => {
        setBusy(true)
        try {
          await startGoogle(purpose)          // navigates this tab to Google
        } catch (error) {
          setBusy(false)
          onError?.(extractAuthError(error))
        }
      }}
      className="w-full flex items-center justify-center gap-2 border border-slate-300 rounded-md py-2 px-4 bg-white hover:bg-slate-50 text-sm font-medium text-slate-800 disabled:opacity-60"
    >
      <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
        <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.6 5.4 2.7 13.3l7.9 6.1C12.5 13.6 17.8 9.5 24 9.5z" />
        <path fill="#4285F4" d="M46.1 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.4c-.5 2.9-2.2 5.3-4.6 6.9l7.4 5.7c4.3-4 6.9-9.9 6.9-17.1z" />
        <path fill="#FBBC05" d="M10.6 28.6c-.5-1.4-.8-3-.8-4.6s.3-3.2.8-4.6l-7.9-6.1C1 16.6 0 20.2 0 24s1 7.4 2.7 10.7l7.9-6.1z" />
        <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.4-5.7c-2.1 1.4-4.8 2.2-8.5 2.2-6.2 0-11.5-4.1-13.4-9.9l-7.9 6.1C6.6 42.6 14.6 48 24 48z" />
      </svg>
      {busy ? 'Opening Google…' : label ?? 'Sign in with Google'}
    </button>
  )
}
