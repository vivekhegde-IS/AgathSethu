/**
 * Form building blocks for the light official pages (login, registration).
 */

import React, { useState } from 'react'
import { Link } from 'react-router-dom'

export const OfficialFormCard: React.FC<{
  title: string
  subtitle: string
  children: React.ReactNode
  footer?: React.ReactNode
}> = ({ title, subtitle, children, footer }) => (
  <div className="max-w-md mx-auto px-4 py-10">
    <Link to="/" className="text-sm text-blue-900 hover:underline">
      ← Back to portal home
    </Link>
    <section className="mt-3 bg-white border border-slate-200 rounded-lg shadow-sm">
      <div className="border-b border-slate-200 px-6 py-4">
        <h1 className="text-xl font-semibold text-blue-950">{title}</h1>
        <p className="mt-1 text-sm text-slate-600">{subtitle}</p>
      </div>
      <div className="px-6 py-5">{children}</div>
      {footer && <div className="border-t border-slate-200 px-6 py-3 text-sm text-slate-600">{footer}</div>}
    </section>
  </div>
)

export const OfficialField: React.FC<
  React.InputHTMLAttributes<HTMLInputElement> & {
    label: string
    hint?: string
    /** Keep the browser's saved logins out of this box: it stays read-only
     * (browsers never autofill read-only fields) until the user focuses it. */
    noAutofill?: boolean
  }
> = ({ label, hint, id, noAutofill = false, onFocus, ...props }) => {
  const fieldId = id || `f-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`
  const [locked, setLocked] = useState(noAutofill)
  const autofillProps = noAutofill
    ? {
        readOnly: locked,
        autoComplete: props.type === 'password' ? 'new-password' : 'off',
        name: `${fieldId}-${props.type === 'password' ? 'pw' : 'id'}`,
      }
    : {}
  return (
    <div>
      <label htmlFor={fieldId} className="block text-sm font-medium text-slate-800">
        {label}
        {props.required && <span className="text-red-700"> *</span>}
      </label>
      <input
        id={fieldId}
        className="mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder-slate-400 focus:border-blue-800 focus:outline-none focus:ring-1 focus:ring-blue-800"
        {...props}
        {...autofillProps}
        onFocus={(e) => {
          if (locked) setLocked(false)
          onFocus?.(e)
        }}
      />
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  )
}

export const OfficialAlert: React.FC<{ kind?: 'error' | 'success'; children: React.ReactNode }> = ({
  kind = 'error',
  children,
}) => (
  <div
    role={kind === 'error' ? 'alert' : 'status'}
    className={`rounded-md border px-3 py-2 text-sm ${
      kind === 'error' ? 'border-red-300 bg-red-50 text-red-800' : 'border-green-300 bg-green-50 text-green-800'
    }`}
  >
    {children}
  </div>
)

export const OfficialSubmit: React.FC<{ busy: boolean; children: React.ReactNode; busyText?: string }> = ({
  busy,
  children,
  busyText = 'Please wait…',
}) => (
  <button
    type="submit"
    disabled={busy}
    className="w-full rounded-md bg-blue-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-800 disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-blue-800 focus:ring-offset-2"
  >
    {busy ? busyText : children}
  </button>
)
