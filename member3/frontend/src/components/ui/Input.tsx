import { InputHTMLAttributes, forwardRef, ReactNode } from 'react'

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  helperText?: string
  leftIcon?: ReactNode
  rightIcon?: ReactNode
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, helperText, leftIcon, rightIcon, className = '', id, ...props }, ref) => {
    const inputId = id || (label ? label.toLowerCase().replace(/\s+/g, '-') : undefined)

    return (
      <div className="w-full space-y-1.5">
        {label && (
          <label htmlFor={inputId} className="block text-xs font-medium text-slate-300 tracking-wide uppercase">
            {label}
          </label>
        )}
        <div className="relative flex items-center">
          {leftIcon && <div className="absolute left-3 text-slate-400 pointer-events-none">{leftIcon}</div>}
          <input
            ref={ref}
            id={inputId}
            className={`w-full bg-[#121820] border ${
              error ? 'border-red-500 focus:border-red-400 focus:ring-red-400/20' : 'border-slate-700 focus:border-aghat-blue focus:ring-aghat-blue/20'
            } rounded-md text-sm text-slate-100 placeholder-slate-500 py-2 ${
              leftIcon ? 'pl-9' : 'pl-3.5'
            } ${rightIcon ? 'pr-9' : 'pr-3.5'} transition-all focus:outline-none focus:ring-2 disabled:opacity-50 disabled:bg-slate-900 ${className}`}
            {...props}
          />
          {rightIcon && <div className="absolute right-3 text-slate-400 pointer-events-none">{rightIcon}</div>}
        </div>
        {error && <p className="text-xs text-red-400 mt-1">{error}</p>}
        {helperText && !error && <p className="text-xs text-slate-400 mt-1">{helperText}</p>}
      </div>
    )
  }
)

Input.displayName = 'Input'
