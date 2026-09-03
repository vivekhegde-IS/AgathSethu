import React from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

export const AuthorityLayout: React.FC = () => {
  return (
    <div className="flex min-h-screen bg-[#0a0e14] text-white">
      <Sidebar portal="authority" />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar portal="authority" />
        <main className="flex-1 p-6 w-full overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
