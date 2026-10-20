/**
 * AGHAT SETHU — Official public layout
 *
 * Used by the landing page, both login/registration pages and the footer
 * information pages. Light, plain government-portal style: emblem/logo area
 * and portal name in the header, standard footer links, nothing else.
 */

import React from 'react'
import { Link, Outlet } from 'react-router-dom'

export const PortalEmblem: React.FC<{ size?: number }> = ({ size = 52 }) => (
  // The portal's own logo mark (not a government emblem).
  <svg width={size} height={size} viewBox="0 0 64 64" role="img" aria-label="AGHAT SETHU logo">
    <circle cx="32" cy="32" r="30" fill="#ffffff" stroke="#1e3a8a" strokeWidth="3" />
    <circle cx="32" cy="32" r="22" fill="none" stroke="#1e3a8a" strokeWidth="1.5" strokeDasharray="2 3" />
    <path d="M14 40 Q32 18 50 40" fill="none" stroke="#1e3a8a" strokeWidth="3" strokeLinecap="round" />
    <path d="M20 40 V46 M32 30 V46 M44 40 V46" stroke="#1e3a8a" strokeWidth="2.5" strokeLinecap="round" />
    <path d="M12 46 H52" stroke="#c2410c" strokeWidth="3" strokeLinecap="round" />
  </svg>
)

export const OfficialHeader: React.FC = () => (
  <header className="bg-white border-b border-slate-200">
    <a
      href="#main-content"
      className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:bg-white focus:px-3 focus:py-2 focus:text-blue-900 focus:ring-2 focus:ring-blue-800"
    >
      Skip to main content
    </a>
    <div className="h-1 w-full bg-gradient-to-r from-orange-500 via-white to-green-600" aria-hidden="true" />
    <div className="max-w-6xl mx-auto px-4 sm:px-6 py-4 flex items-center gap-4">
      <Link to="/" className="flex items-center gap-4" aria-label="AGHAT SETHU home">
        <PortalEmblem />
        <div className="leading-tight">
          <p className="text-xl sm:text-2xl font-bold tracking-wide text-blue-950">AGHAT SETHU</p>
          <p className="text-xs sm:text-sm text-slate-600">Traffic Safety &amp; Incident Response Portal</p>
        </div>
      </Link>
    </div>
    <div className="h-9 bg-blue-900" aria-hidden="true" />
  </header>
)

const FOOTER_LINKS = [
  { to: '/privacy', label: 'Privacy Policy' },
  { to: '/terms', label: 'Terms of Use' },
  { to: '/accessibility', label: 'Accessibility Statement' },
  { to: '/help', label: 'Help & Contact' },
]

export const OfficialFooter: React.FC = () => (
  <footer className="bg-blue-950 text-blue-100 text-sm">
    <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6 space-y-3">
      <nav aria-label="Footer" className="flex flex-wrap gap-x-6 gap-y-2">
        {FOOTER_LINKS.map((link) => (
          <Link key={link.to} to={link.to} className="hover:text-white hover:underline">
            {link.label}
          </Link>
        ))}
      </nav>
      <div className="flex flex-col sm:flex-row sm:justify-between gap-1 text-xs text-blue-200">
        <p>© {new Date().getFullYear()} AGHAT SETHU. All rights reserved.</p>
        <p>Last updated: {__APP_LAST_UPDATED__}</p>
      </div>
    </div>
  </footer>
)

export const OfficialLayout: React.FC = () => (
  <div className="min-h-screen flex flex-col bg-slate-100 text-slate-900">
    <OfficialHeader />
    <main id="main-content" className="flex-1 w-full">
      <Outlet />
    </main>
    <OfficialFooter />
  </div>
)
