import React from 'react'

export interface ToastProps {
  type?: 'success' | 'warning' | 'danger' | 'info'
  title: string
  message?: string
  onClose?: () => void
}

export const Toast: React.FC<ToastProps> = ({
  type = 'info',
  title,
  message,
  onClose,
}) => {
  const typeBorder = {
    success: 'border-emerald-500 bg-emerald-950/90 text-emerald-300',
    warning: 'border-amber-500 bg-amber-950/90 text-amber-300',
    danger: 'border-red-500 bg-red-950/90 text-red-300',
    info: 'border-aghat-blue bg-blue-950/90 text-blue-300',
  }[type]

  return (
    <div className={`flex items-start justify-between p-4 rounded-lg border shadow-xl backdrop-blur-md max-w-sm ${typeBorder}`}>
      <div>
        <p className="text-xs font-mono font-semibold uppercase tracking-wide">{title}</p>
        {message && <p className="text-xs text-slate-300 mt-1">{message}</p>}
      </div>
      {onClose && (
        <button onClick={onClose} className="ml-3 text-slate-400 hover:text-white p-1">
          ✕
        </button>
      )}
    </div>
  )
}
