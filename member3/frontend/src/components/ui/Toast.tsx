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
    success: 'border-green-600 bg-green-50 text-green-800',
    warning: 'border-amber-500 bg-amber-50 text-amber-800',
    danger: 'border-red-600 bg-red-50 text-red-800',
    info: 'border-blue-800 bg-blue-50 text-blue-900',
  }[type]

  return (
    <div className={`flex items-start justify-between p-4 rounded-lg border shadow-xl backdrop-blur-md max-w-sm ${typeBorder}`}>
      <div>
        <p className="text-xs font-mono font-semibold uppercase tracking-wide">{title}</p>
        {message && <p className="text-xs text-slate-700 mt-1">{message}</p>}
      </div>
      {onClose && (
        <button onClick={onClose} className="ml-3 text-slate-500 hover:text-slate-900 p-1">
          ✕
        </button>
      )}
    </div>
  )
}
