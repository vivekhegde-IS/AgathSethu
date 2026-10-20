import React from 'react'
import { Link, Navigate } from 'react-router-dom'
import { useAuthStore } from '@stores/authStore'

/**
 * Landing page: the two entry points and nothing else.
 * A signed-in user goes straight to their own portal.
 */
export const Home: React.FC = () => {
  const { isAuthenticated, user } = useAuthStore()
  if (isAuthenticated && user) {
    return <Navigate to={user.role === 'citizen' ? '/citizen/dashboard' : '/authority/dashboard'} replace />
  }

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 py-12">
      <h1 className="text-2xl sm:text-3xl font-semibold text-blue-950 text-center">Sign in to continue</h1>
      <p className="mt-2 text-center text-slate-600 text-sm">Choose the portal that applies to you.</p>

      <div className="mt-10 grid gap-6 md:grid-cols-2">
        <EntryCard
          to="/citizen/login"
          title="Citizen Login"
          description="View e-challans issued to your registered vehicles, pay fines, download payment receipts and read notifications."
          action="Citizen Login"
          icon={
            <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8a7 7 0 0 1 14 0" strokeLinecap="round" strokeLinejoin="round" />
          }
        />
        <EntryCard
          to="/authority/login"
          title="Authority Login"
          description="For authorised traffic police and control-room officers: live camera monitoring, crash incidents, evidence records and fines."
          action="Authority Login"
          icon={
            <path d="M12 3 4 6v6c0 4.5 3.4 8.3 8 9 4.6-.7 8-4.5 8-9V6l-8-3Zm-3 9 2 2 4-4" strokeLinecap="round" strokeLinejoin="round" />
          }
        />
      </div>
    </div>
  )
}

const EntryCard: React.FC<{
  to: string
  title: string
  description: string
  action: string
  icon: React.ReactNode
}> = ({ to, title, description, action, icon }) => (
  <section className="bg-white border border-slate-200 rounded-lg shadow-sm p-6 flex flex-col">
    <div className="flex items-center gap-3">
      <span className="w-11 h-11 rounded-full bg-blue-50 text-blue-900 flex items-center justify-center" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="1.8">
          {icon}
        </svg>
      </span>
      <h2 className="text-lg font-semibold text-blue-950">{title}</h2>
    </div>
    <p className="mt-3 text-sm text-slate-600 flex-1">{description}</p>
    <Link
      to={to}
      className="mt-6 inline-flex justify-center rounded-md bg-blue-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-800 focus:ring-offset-2"
    >
      {action}
    </Link>
  </section>
)
