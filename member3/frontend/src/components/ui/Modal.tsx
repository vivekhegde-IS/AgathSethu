import React, { ReactNode, useEffect } from 'react'

export interface ModalProps {
  isOpen: boolean
  onClose: () => void
  title?: ReactNode
  children: ReactNode
  footer?: ReactNode
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl' | '2xl' | '4xl'
}

export const Modal: React.FC<ModalProps> = ({
  isOpen,
  onClose,
  title,
  children,
  footer,
  maxWidth = 'lg',
}) => {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  if (!isOpen) return null

  const maxWidthClasses = {
    sm: 'max-w-sm',
    md: 'max-w-md',
    lg: 'max-w-lg',
    xl: 'max-w-xl',
    '2xl': 'max-w-2xl',
    '4xl': 'max-w-4xl',
  }[maxWidth]

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/75 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      {/* Modal Dialog */}
      <div className="flex min-h-full items-center justify-center p-4 text-center">
        <div
          className={`w-full ${maxWidthClasses} transform overflow-hidden rounded-lg bg-aghat-navy-light border border-slate-700 p-6 text-left align-middle shadow-2xl transition-all`}
          onClick={(e) => e.stopPropagation()}
        >
          {title && (
            <div className="flex items-center justify-between border-b border-slate-800 pb-4 mb-4">
              <h3 className="text-base font-semibold text-white tracking-wide uppercase">{title}</h3>
              <button
                type="button"
                className="text-slate-400 hover:text-slate-200 transition-colors p-1"
                onClick={onClose}
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          )}

          <div className="text-sm text-slate-300">{children}</div>

          {footer && <div className="mt-6 flex items-center justify-end gap-3 border-t border-slate-800 pt-4">{footer}</div>}
        </div>
      </div>
    </div>
  )
}
