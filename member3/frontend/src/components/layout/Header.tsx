import React from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAuthStore } from '@stores/authStore'
import { Button } from '@components/ui'

export const Header: React.FC = () => {
  const location = useLocation()
  const { isAuthenticated, user, logout } = useAuthStore()

  const navLinks = [
    { name: 'Home', path: '/' },
    { name: 'About Platform', path: '/about' },
  ]

  return (
    <header className="glass-header border-b border-slate-800">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand Logo */}
        <Link to="/" className="flex items-center gap-3 group">
          <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-aghat-blue to-indigo-700 flex items-center justify-center shadow-glow border border-blue-400/30 group-hover:scale-105 transition-transform">
            <svg className="w-5 h-5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono font-bold text-base text-white tracking-widest uppercase">AGHAT SETHU</span>
              <span className="px-1.5 py-0.2 rounded text-[10px] font-mono bg-blue-500/20 text-cyan-300 border border-blue-500/30">
                v0.1
              </span>
            </div>
            <p className="text-[10px] text-slate-400 font-mono tracking-wider">AI TRAFFIC SAFETY & INCIDENT RADAR</p>
          </div>
        </Link>

        {/* Navigation Links */}
        <nav className="hidden md:flex items-center gap-6">
          {navLinks.map((link) => (
            <Link
              key={link.path}
              to={link.path}
              className={`text-xs font-mono uppercase tracking-wider transition-colors ${
                location.pathname === link.path ? 'text-cyan-400 font-semibold' : 'text-slate-300 hover:text-white'
              }`}
            >
              {link.name}
            </Link>
          ))}
        </nav>

        {/* Portal Access Buttons */}
        <div className="flex items-center gap-3">
          {isAuthenticated && user ? (
            <div className="flex items-center gap-3">
              <Link to={user.role === 'citizen' ? '/citizen/dashboard' : '/authority/dashboard'}>
                <Button variant="outline" size="sm">
                  {user.role === 'citizen' ? 'Citizen Portal' : 'TOC Command Center'}
                </Button>
              </Link>
              <Button variant="ghost" size="sm" onClick={logout}>
                Sign Out
              </Button>
            </div>
          ) : (
            <div className="flex items-center gap-2.5">
              <Link to="/citizen/login">
                <Button variant="outline" size="sm">
                  Citizen Login
                </Button>
              </Link>
              <Link to="/authority/login">
                <Button variant="primary" size="sm">
                  Authority Portal
                </Button>
              </Link>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
