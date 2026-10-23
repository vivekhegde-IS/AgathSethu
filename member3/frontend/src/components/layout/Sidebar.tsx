import React from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAuthStore } from '@stores/authStore'
import { PortalEmblem } from './OfficialLayout'

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
    { name: 'Pay Fines', path: '/citizen/payments', icon: '💳' },
    { name: 'Payment History', path: '/citizen/receipts', icon: '📄' },
    { name: 'Notifications', path: '/citizen/notifications', icon: '🔔' },
    { name: 'Profile Settings', path: '/citizen/profile', icon: '👤' },
  ]

  const authorityNav = [
    { section: 'OPERATIONS' },
    { name: 'Overview', path: '/authority/dashboard', icon: '⚡' },
    { name: 'Live Camera Feeds', path: '/authority/live', icon: '📹' },

    { section: 'LEVEL 1 ENFORCEMENT' },
    { name: 'Routine Violations', path: '/authority/level1', icon: '🛑' },
    { name: 'Fines & Revenue', path: '/authority/fines', icon: '💵' },

    { section: 'LEVEL 2 CRASH INVESTIGATION' },
    { name: 'Crash Incident Radar', path: '/authority/incidents', icon: '🚨' },
    { name: 'Evidence Records', path: '/authority/evidence', icon: '🔒' },

  ]

  return (
    <aside className="w-64 bg-white border-r border-slate-200 flex flex-col flex-shrink-0 min-h-screen">
      {/* Brand Header */}
      <div className="h-16 px-5 border-b border-slate-200 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2.5">
          <PortalEmblem size={36} />
          <div className="leading-tight">
            <span className="font-bold text-sm text-blue-950 tracking-wide block">AGHAT SETHU</span>
            <span className="text-xs text-slate-600">
              {portal === 'citizen' ? 'Citizen Portal' : 'Authority Portal'}
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
                  className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                    isActive
                      ? 'bg-blue-900 text-white font-semibold'
                      : 'text-slate-700 hover:bg-blue-50 hover:text-blue-900'
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
                    className="pt-4 pb-1 px-3 text-xs font-semibold uppercase tracking-wide text-slate-500"
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
                  className={`flex items-center justify-between px-3 py-2 rounded-md text-sm transition-colors ${
                    isActive
                      ? 'bg-blue-900 text-white font-semibold'
                      : 'text-slate-700 hover:bg-blue-50 hover:text-blue-900'
                  }`}
                >
                  <div className="flex items-center gap-2.5">
                    <span className="text-sm">{item.icon}</span>
                    <span>{item.name}</span>
                  </div>

                </Link>
              )
            })}
      </div>

      {/* User Footer Profile Card */}
      {user && (
        <div className="p-3 border-t border-slate-200 bg-slate-50">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-full bg-slate-200 flex items-center justify-center text-xs font-mono font-bold text-slate-900 border border-slate-300">
              {user.name.charAt(0)}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-mono font-semibold text-slate-900 truncate">{user.name}</p>
              <p className="text-[10px] font-mono text-slate-600 truncate">
                {user.badgeNumber || user.role.toUpperCase()}
              </p>
            </div>
          </div>
        </div>
      )}
    </aside>
  )
}
