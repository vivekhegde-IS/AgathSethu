import React, { ButtonHTMLAttributes, ReactNode } from 'react'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'success' | 'outline' | 'ghost'
  size?: 'sm' | 'md' | 'lg'
  isLoading?: boolean
  leftIcon?: ReactNode
  rightIcon?: ReactNode
}

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'primary',
  size = 'md',
  isLoading = false,
  leftIcon,
  rightIcon,
  className = '',
  disabled,
  ...props
}) => {
  const baseClasses =
    'inline-flex items-center justify-center font-medium rounded-md transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-aghat-navy disabled:opacity-50 disabled:cursor-not-allowed select-none'

  const sizeClasses = {
    sm: 'px-2.5 py-1 text-xs gap-1.5',
    md: 'px-4 py-2 text-sm gap-2',
    lg: 'px-6 py-2.5 text-base gap-2.5',
  }[size]

  const variantClasses = {
    primary: 'bg-aghat-blue hover:bg-aghat-blue-dark text-white shadow-md hover:shadow-glow focus:ring-aghat-blue',
    secondary: 'bg-aghat-navy-lighter hover:bg-slate-700 text-slate-200 border border-slate-700 focus:ring-slate-500',
    danger: 'bg-red-600 hover:bg-red-700 text-white shadow-md focus:ring-red-500',
    success: 'bg-emerald-600 hover:bg-emerald-700 text-white shadow-md focus:ring-emerald-500',
    outline: 'bg-transparent border border-aghat-blue/60 text-blue-400 hover:bg-blue-950/40 focus:ring-aghat-blue',
    ghost: 'bg-transparent text-slate-300 hover:bg-slate-800/60 hover:text-white focus:ring-slate-600',
  }[variant]

  return (
    <button
      className={`${baseClasses} ${sizeClasses} ${variantClasses} ${className}`}
      disabled={disabled || isLoading}
      {...props}
    >
      {isLoading ? (
        <svg className="animate-spin -ml-0.5 mr-2 h-4 w-4 text-current" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
      ) : (
        leftIcon
      )}
      <span>{children}</span>
      {!isLoading && rightIcon}
    </button>
  )
}
