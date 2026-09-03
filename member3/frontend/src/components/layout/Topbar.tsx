import React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuthStore } from '@stores/authStore'
import { StatusIndicator, Button } from '@components/ui'

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
    <header className="h-16 bg-[#0f1419]/90 backdrop-blur-md border-b border-slate-800/80 px-6 flex items-center justify-between sticky top-0 z-30 flex-shrink-0">
      <div className="flex items-center gap-4">
        <div>
          {title ? (
            <h1 className="text-sm font-bold font-mono text-white uppercase tracking-wider">{title}</h1>
          ) : (
            <h1 className="text-sm font-bold font-mono text-white uppercase tracking-wider">
              {portal === 'citizen' ? 'Citizen Operations Portal' : 'Tactical Traffic Operations Center'}
            </h1>
          )}
          {subtitle && <p className="text-[11px] text-slate-400 font-mono">{subtitle}</p>}
        </div>
      </div>

      <div className="flex items-center gap-4">
        {portal === 'authority' && (
          <div className="hidden lg:flex items-center gap-4 px-3 py-1.5 rounded-md bg-[#161d27] border border-slate-800">
            <StatusIndicator status="online" label="CARLA SIM: 30 FPS" />
            <span className="text-slate-600">|</span>
            <StatusIndicator status="online" label="ANPR: ONLINE" />
            <span className="text-slate-600">|</span>
            <StatusIndicator status="online" label="RFID FUSION: SYNC" />
          </div>
        )}

        {/* Action controls */}
        <div className="flex items-center gap-3">
          <Link to="/">
            <Button variant="ghost" size="sm">
              Public Portal
            </Button>
          </Link>
          <Button variant="secondary" size="sm" onClick={handleLogout}>
            Sign Out ({user?.role})
          </Button>
        </div>
      </div>
    </header>
  )
}
