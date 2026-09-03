import React, { ReactNode } from 'react'

export interface BadgeProps {
  variant?: 'success' | 'warning' | 'danger' | 'info' | 'muted' | 'brand'
  size?: 'sm' | 'md'
  children: ReactNode
  className?: string
  dot?: boolean
}

export const Badge: React.FC<BadgeProps> = ({
  variant = 'info',
  size = 'sm',
  children,
  className = '',
  dot = false,
}) => {
  const sizeClasses = {
    sm: 'px-2 py-0.5 text-[11px]',
    md: 'px-2.5 py-1 text-xs',
  }[size]

  const variantClasses = {
    success: 'bg-emerald-950/70 text-emerald-300 border-emerald-800/60',
    warning: 'bg-amber-950/70 text-amber-300 border-amber-800/60',
    danger: 'bg-red-950/70 text-red-300 border-red-800/60',
    info: 'bg-blue-950/70 text-blue-300 border-blue-800/60',
    muted: 'bg-slate-900/80 text-slate-400 border-slate-700',
    brand: 'bg-indigo-950/70 text-indigo-300 border-indigo-800/60',
  }[variant]

  const dotColors = {
    success: 'bg-emerald-400',
    warning: 'bg-amber-400',
    danger: 'bg-red-400',
    info: 'bg-blue-400',
    muted: 'bg-slate-400',
    brand: 'bg-indigo-400',
  }[variant]

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-mono font-medium border tracking-wider uppercase ${sizeClasses} ${variantClasses} ${className}`}
    >
      {dot && <span className={`w-1.5 h-1.5 rounded-full animate-pulse ${dotColors}`} />}
      {children}
    </span>
  )
}
