import React from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@stores/authStore'
import { Button } from '@components/ui'

export interface TopbarProps {
  portal: 'citizen' | 'authority'
  title?: string
  subtitle?: string
}

export const Topbar: React.FC<TopbarProps> = ({ portal, title, subtitle }) => {
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/')
  }

  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-30 flex-shrink-0">
      <div className="h-1 w-full bg-gradient-to-r from-orange-500 via-white to-green-600" aria-hidden="true" />
      <div className="h-16 px-6 flex items-center justify-between">
      <div className="flex items-center gap-4">
        <div>
          {title ? (
            <h1 className="text-lg font-semibold text-blue-950">{title}</h1>
          ) : (
            <h1 className="text-lg font-semibold text-blue-950">
              {portal === 'citizen' ? 'Citizen Portal' : 'Traffic Operations'}
            </h1>
          )}
          {subtitle && <p className="text-xs text-slate-600">{subtitle}</p>}
        </div>
      </div>

      <div className="flex items-center gap-4">
        {/* Action controls */}
        <div className="flex items-center gap-3">
          <Button variant="secondary" size="sm" onClick={handleLogout}>
            Sign out ({user?.name})
          </Button>
        </div>
      </div>
      </div>
    </header>
  )
}
