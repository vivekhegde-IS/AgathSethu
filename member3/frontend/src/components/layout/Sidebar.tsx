import React from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAuthStore } from '@stores/authStore'
import { Badge } from '@components/ui'

export interface SidebarProps {
  portal: 'citizen' | 'authority'
}

export const Sidebar: React.FC<SidebarProps> = ({ portal }) => {
  const location = useLocation()
  const { user } = useAuthStore()

  const citizenNav = [
    { name: 'Dashboard', path: '/citizen/dashboard', icon: '📊' },
    { name: 'My Vehicles', path: '/citizen/vehicles', icon: '🚗' },
    { name: 'My Violations', path: '/citizen/violations', icon: '⚠️' },
    { name: 'Payments & Fines', path: '/citizen/payments', icon: '💳' },
    { name: 'Payment Receipts', path: '/citizen/receipts', icon: '📄' },
    { name: 'Notifications', path: '/citizen/notifications', icon: '🔔' },
    { name: 'Profile Settings', path: '/citizen/profile', icon: '👤' },
  ]

  const authorityNav = [
    { section: 'OPERATIONS TOC' },
    { name: 'Tactical Dashboard', path: '/authority/dashboard', icon: '⚡' },
    { name: 'Live Camera Feeds', path: '/authority/live', icon: '📹' },
    { name: 'Junction Overview', path: '/authority/junctions', icon: '🚦' },
    { name: 'Camera Inventory', path: '/authority/cameras', icon: '🎥' },

    { section: 'LEVEL 1 ENFORCEMENT' },
    { name: 'Routine Violations', path: '/authority/level1', icon: '🛑' },
    { name: 'Fine Management', path: '/authority/fines', icon: '💵' },

    { section: 'LEVEL 2 CRASH INVESTIGATION' },
    { name: 'Crash Incident Radar', path: '/authority/incidents', icon: '🚨', badge: '1 CRITICAL' },
    { name: 'Evidence Vault', path: '/authority/evidence', icon: '🔒' },

    { section: 'VEHICLE INTELLIGENCE' },
    { name: 'Vehicle Registry & Search', path: '/authority/vehicles', icon: '🔍' },
    { name: 'Multi-Junction Tracking', path: '/authority/tracking', icon: '🛰️' },

    { section: 'GOVERNANCE & PLATFORM' },
    { name: 'Analytics & Reports', path: '/authority/reports', icon: '📈' },
    { name: 'System Telemetry', path: '/authority/system', icon: '💻' },
    { name: 'Platform Settings', path: '/authority/settings', icon: '⚙️' },
  ]

  return (
    <aside className="w-64 bg-[#0d1218] border-r border-slate-800/80 flex flex-col flex-shrink-0 min-h-screen">
      {/* Brand Header */}
      <div className="h-16 px-5 border-b border-slate-800/80 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-md bg-aghat-blue flex items-center justify-center shadow-glow font-mono font-bold text-white text-xs">
            AS
          </div>
          <div>
            <span className="font-mono font-bold text-xs text-white uppercase tracking-widest block">AGHAT SETHU</span>
            <span className="text-[10px] font-mono text-cyan-400 tracking-wider">
              {portal === 'citizen' ? 'CITIZEN PORTAL' : 'TACTICAL TOC'}
            </span>
          </div>
        </Link>
      </div>

      {/* Navigation List */}
      <div className="flex-1 overflow-y-auto px-3 py-4 space-y-1">
        {portal === 'citizen'
          ? citizenNav.map((item) => {
              const isActive = location.pathname === item.path
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`flex items-center gap-3 px-3 py-2 rounded-md text-xs font-mono transition-colors ${
                    isActive
                      ? 'bg-aghat-blue text-white font-semibold shadow-md'
                      : 'text-slate-300 hover:bg-slate-800/60 hover:text-white'
                  }`}
                >
                  <span className="text-sm">{item.icon}</span>
                  <span>{item.name}</span>
                </Link>
              )
            })
          : authorityNav.map((item, idx) => {
              if (item.section) {
                return (
                  <div
                    key={`sec-${idx}`}
                    className="pt-4 pb-1 px-3 text-[10px] font-mono font-semibold uppercase tracking-wider text-slate-500"
                  >
                    {item.section}
                  </div>
                )
              }
              const isActive = location.pathname === item.path
              return (
                <Link
                  key={item.path}
                  to={item.path!}
                  className={`flex items-center justify-between px-3 py-2 rounded-md text-xs font-mono transition-colors ${
                    isActive
                      ? 'bg-aghat-blue text-white font-semibold shadow-md'
                      : 'text-slate-300 hover:bg-slate-800/60 hover:text-white'
                  }`}
                >
                  <div className="flex items-center gap-2.5">
                    <span className="text-sm">{item.icon}</span>
                    <span>{item.name}</span>
                  </div>
                  {item.badge && (
                    <Badge variant="danger" size="sm">
                      {item.badge}
                    </Badge>
                  )}
                </Link>
              )
            })}
      </div>

      {/* User Footer Profile Card */}
      {user && (
        <div className="p-3 border-t border-slate-800/80 bg-[#101620]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-full bg-slate-700 flex items-center justify-center text-xs font-mono font-bold text-white border border-slate-600">
              {user.name.charAt(0)}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-mono font-semibold text-white truncate">{user.name}</p>
              <p className="text-[10px] font-mono text-slate-400 truncate">
                {user.badgeNumber || user.role.toUpperCase()}
              </p>
            </div>
          </div>
        </div>
      )}
    </aside>
  )
}
