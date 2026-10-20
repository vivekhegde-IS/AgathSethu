import { SelectHTMLAttributes, forwardRef, ReactNode } from 'react'

export interface SelectOption {
  value: string | number
  label: string
}

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string
  error?: string
  options?: SelectOption[]
  leftIcon?: ReactNode
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, error, options = [], children, leftIcon, className = '', id, ...props }, ref) => {
    const selectId = id || (label ? label.toLowerCase().replace(/\s+/g, '-') : undefined)

    return (
      <div className="w-full space-y-1.5">
        {label && (
          <label htmlFor={selectId} className="block text-sm font-medium text-slate-800">
            {label}
          </label>
        )}
        <div className="relative flex items-center">
          {leftIcon && <div className="absolute left-3 text-slate-400 pointer-events-none">{leftIcon}</div>}
          <select
            ref={ref}
            id={selectId}
            className={`w-full bg-white border ${
              error ? 'border-red-500' : 'border-slate-300'
            } rounded-md text-sm text-slate-900 py-2 ${
              leftIcon ? 'pl-9' : 'pl-3.5'
            } pr-8 transition-colors focus:outline-none focus:border-blue-800 focus:ring-1 focus:ring-blue-800 appearance-none cursor-pointer ${className}`}
            {...props}
          >
            {children ||
              options.map((opt) => (
                <option key={opt.value} value={opt.value} className="bg-white text-slate-900">
                  {opt.label}
                </option>
              ))}
          </select>
          <div className="absolute right-3 text-slate-400 pointer-events-none">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        </div>
        {error && <p className="text-xs text-red-700">{error}</p>}
      </div>
    )
  }
)

Select.displayName = 'Select'
