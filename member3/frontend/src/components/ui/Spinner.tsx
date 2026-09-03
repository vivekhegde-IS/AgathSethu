import React from 'react'

export interface SpinnerProps {
  size?: 'sm' | 'md' | 'lg'
  color?: 'primary' | 'cyan' | 'white'
  className?: string
  label?: string
}

export const Spinner: React.FC<SpinnerProps> = ({
  size = 'md',
  color = 'primary',
  className = '',
  label,
}) => {
  const sizeClasses = {
    sm: 'w-4 h-4',
    md: 'w-6 h-6',
    lg: 'w-10 h-10',
  }[size]

  const colorClasses = {
    primary: 'text-aghat-blue',
    cyan: 'text-cyan-400',
    white: 'text-white',
  }[color]

  return (
    <div className={`inline-flex flex-col items-center justify-center gap-2 ${className}`}>
      <svg
        className={`animate-spin ${sizeClasses} ${colorClasses}`}
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path
          className="opacity-90"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
        />
      </svg>
      {label && <span className="text-xs font-mono text-slate-400 uppercase tracking-wider">{label}</span>}
    </div>
  )
}
