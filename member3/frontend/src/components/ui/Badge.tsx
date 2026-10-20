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
    success: 'bg-green-50 text-green-800 border-green-300',
    warning: 'bg-amber-50 text-amber-800 border-amber-300',
    danger: 'bg-red-50 text-red-800 border-red-300',
    info: 'bg-blue-50 text-blue-800 border-blue-300',
    muted: 'bg-slate-100 text-slate-700 border-slate-300',
    brand: 'bg-indigo-50 text-indigo-800 border-indigo-300',
  }[variant]

  const dotColors = {
    success: 'bg-green-600',
    warning: 'bg-amber-500',
    danger: 'bg-red-600',
    info: 'bg-blue-600',
    muted: 'bg-slate-400',
    brand: 'bg-indigo-400',
  }[variant]

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-medium border tracking-wide ${sizeClasses} ${variantClasses} ${className}`}
    >
      {dot && <span className={`w-1.5 h-1.5 rounded-full animate-pulse ${dotColors}`} />}
      {children}
    </span>
  )
}
