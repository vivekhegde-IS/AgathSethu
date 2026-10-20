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
    normal: 'border-l-blue-900',
    warning: 'border-l-amber-500',
    critical: 'border-l-red-700',
    success: 'border-l-green-700',
  }[status]

  return (
    <div
      className={`bg-white border border-slate-200 border-l-4 rounded-lg p-4 shadow-sm ${statusBorder} ${className}`}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-slate-600">{label}</span>
        {icon && <div className="text-slate-500">{icon}</div>}
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-2xl font-bold tracking-tight text-blue-950">{value}</span>
        {subValue && <span className="text-xs text-slate-600">{subValue}</span>}
      </div>
      {trend && (
        <div className="mt-2 flex items-center gap-1.5 text-xs font-mono">
          <span
            className={
              trend.positive
                ? 'text-green-700'
                : trend.direction === 'neutral'
                ? 'text-slate-600'
                : 'text-red-700'
            }
          >
            {trend.direction === 'up' ? '▲' : trend.direction === 'down' ? '▼' : '●'} {trend.value}
          </span>
          
        </div>
      )}
    </div>
  )
}
