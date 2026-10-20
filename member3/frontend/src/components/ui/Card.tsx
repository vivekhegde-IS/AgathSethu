import React, { ReactNode } from 'react'

export interface CardProps {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
  headerClassName?: string
  bodyClassName?: string
  glow?: boolean
  interactive?: boolean
  onClick?: () => void
}

export const Card: React.FC<CardProps> = ({
  title,
  subtitle,
  actions,
  children,
  className = '',
  headerClassName = '',
  bodyClassName = '',
  glow = false,
  interactive = false,
  onClick,
}) => {
  return (
    <div
      onClick={onClick}
      className={`bg-white border border-slate-200 rounded-lg overflow-hidden shadow-sm transition-all duration-200 ${
        interactive ? 'cursor-pointer hover:border-blue-800 hover:shadow-md' : ''
      } ${glow ? '' : ''} ${className}`}
    >
      {(title || actions || subtitle) && (
        <div className={`px-5 py-4 border-b border-slate-200 flex items-center justify-between gap-3 ${headerClassName}`}>
          <div>
            {title && (
              <h3 className="text-base font-semibold text-blue-950 flex items-center gap-2">
                {title}
              </h3>
            )}
            {subtitle && <p className="text-xs text-slate-600 mt-0.5">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={`p-5 ${bodyClassName}`}>{children}</div>
    </div>
  )
}
