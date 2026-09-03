import React from 'react'
import { Outlet } from 'react-router-dom'
import { Header } from './Header'
import { Footer } from './Footer'

export const PublicLayout: React.FC = () => {
  return (
    <div className="min-h-screen flex flex-col bg-aghat-navy text-white selection:bg-aghat-blue selection:text-white">
      <Header />
      <main className="flex-1 w-full">
        <Outlet />
      </main>
      <Footer />
    </div>
  )
}
