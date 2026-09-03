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
      className={`bg-aghat-navy-light border border-slate-800/80 rounded-lg overflow-hidden shadow-lg backdrop-blur-sm transition-all duration-200 ${
        interactive ? 'cursor-pointer hover:border-aghat-blue/60 hover:shadow-glow hover:-translate-y-0.5' : ''
      } ${glow ? 'border-aghat-blue/50 shadow-glow' : ''} ${className}`}
    >
      {(title || actions || subtitle) && (
        <div className={`px-5 py-4 border-b border-slate-800/80 flex items-center justify-between ${headerClassName}`}>
          <div>
            {title && (
              <h3 className="text-sm font-semibold text-white tracking-wide uppercase flex items-center gap-2">
                {title}
              </h3>
            )}
            {subtitle && <p className="text-xs text-slate-400 mt-0.5">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={`p-5 ${bodyClassName}`}>{children}</div>
    </div>
  )
}
