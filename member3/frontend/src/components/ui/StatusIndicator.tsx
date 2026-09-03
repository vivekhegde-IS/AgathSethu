import React from 'react'

export interface StatusIndicatorProps {
  status: 'online' | 'active' | 'warning' | 'error' | 'offline' | 'incident'
  label?: string
  ping?: boolean
  className?: string
}

export const StatusIndicator: React.FC<StatusIndicatorProps> = ({
  status,
  label,
  ping = true,
  className = '',
}) => {
  const statusColors = {
    online: 'bg-emerald-400',
    active: 'bg-emerald-400',
    warning: 'bg-amber-400',
    error: 'bg-red-400',
    offline: 'bg-slate-500',
    incident: 'bg-red-500',
  }[status]

  return (
    <div className={`inline-flex items-center gap-2 font-mono text-xs ${className}`}>
      <span className="relative flex h-2.5 w-2.5">
        {ping && status !== 'offline' && (
          <span
            className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${statusColors}`}
          />
        )}
        <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${statusColors}`} />
      </span>
      {label && <span className="text-slate-300 uppercase tracking-wider">{label}</span>}
    </div>
  )
}
