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
          <label htmlFor={selectId} className="block text-xs font-medium text-slate-300 tracking-wide uppercase">
            {label}
          </label>
        )}
        <div className="relative flex items-center">
          {leftIcon && <div className="absolute left-3 text-slate-400 pointer-events-none">{leftIcon}</div>}
          <select
            ref={ref}
            id={selectId}
            className={`w-full bg-[#121820] border ${
              error ? 'border-red-500' : 'border-slate-700'
            } rounded-md text-sm text-slate-100 py-2 ${
              leftIcon ? 'pl-9' : 'pl-3.5'
            } pr-8 transition-colors focus:outline-none focus:border-aghat-blue focus:ring-1 focus:ring-aghat-blue appearance-none cursor-pointer ${className}`}
            {...props}
          >
            {children ||
              options.map((opt) => (
                <option key={opt.value} value={opt.value} className="bg-aghat-navy-light text-slate-200">
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
        {error && <p className="text-xs text-red-400">{error}</p>}
      </div>
    )
  }
)

Select.displayName = 'Select'
