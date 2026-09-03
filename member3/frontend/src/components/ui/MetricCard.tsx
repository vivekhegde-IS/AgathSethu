import React, { ReactNode } from 'react'

export interface MetricCardProps {
  label: string
  value: string | number
  subValue?: string
  trend?: {
    direction: 'up' | 'down' | 'neutral'
    value: string
    positive?: boolean
  }
  icon?: ReactNode
  status?: 'normal' | 'warning' | 'critical' | 'success'
  className?: string
}

export const MetricCard: React.FC<MetricCardProps> = ({
  label,
  value,
  subValue,
  trend,
  icon,
  status = 'normal',
  className = '',
}) => {
  const statusBorder = {
    normal: 'border-slate-800/80 hover:border-slate-700',
    warning: 'border-amber-700/50 hover:border-amber-600',
    critical: 'border-red-700/60 hover:border-red-500 shadow-glowRed',
    success: 'border-emerald-700/50 hover:border-emerald-600',
  }[status]

  return (
    <div
      className={`bg-aghat-navy-light/90 border rounded-lg p-4 shadow-md transition-all duration-200 backdrop-blur-sm ${statusBorder} ${className}`}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-mono font-medium text-slate-400 uppercase tracking-wider">{label}</span>
        {icon && <div className="text-slate-400">{icon}</div>}
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-2xl font-bold font-mono tracking-tight text-white">{value}</span>
        {subValue && <span className="text-xs text-slate-400 font-mono">{subValue}</span>}
      </div>
      {trend && (
        <div className="mt-2 flex items-center gap-1.5 text-xs font-mono">
          <span
            className={
              trend.positive
                ? 'text-emerald-400'
                : trend.direction === 'neutral'
                ? 'text-slate-400'
                : 'text-red-400'
            }
          >
            {trend.direction === 'up' ? '▲' : trend.direction === 'down' ? '▼' : '●'} {trend.value}
          </span>
          <span className="text-slate-500">vs prev hour</span>
        </div>
      )}
    </div>
  )
}
