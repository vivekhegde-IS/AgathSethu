import React, { useEffect } from 'react'
import { Outlet } from 'react-router-dom'
import { CrashAlertPopup } from '@components/authority/CrashAlertPopup'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'
import { connectLiveCameraSocket, subscribeToLiveCameraMessages } from '@services/websocket/liveCamerasSocket'
import { useIncidentStore } from '@stores/incidentStore'

export const AuthorityLayout: React.FC = () => {
  useEffect(() => {
    const socket = connectLiveCameraSocket()
    if (!socket) return

    const unsubscribe = subscribeToLiveCameraMessages((message) => {
      const payload = message as Record<string, unknown>

      // Register every message; the store routes it by type. Crash alerts
      // activate the global CrashAlertPopup which renders over ANY authority
      // page — no navigation, the operator keeps their current context.
      if (payload.type === 'crash_alert') {
        console.log(
          '[AUTHORITY] crash_alert received — popup activated:',
          payload
        )
        useIncidentStore.getState().registerCrashAlert(payload)
        useIncidentStore.getState().registerLiveIncidentMessage(payload)
        return
      }

      useIncidentStore.getState().registerLiveIncidentMessage(payload)
    })

    return () => {
      unsubscribe()
    }
  }, [])

  return (
    <div className="flex min-h-screen bg-slate-100 text-slate-900">
      <Sidebar portal="authority" />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar portal="authority" />
        <main className="flex-1 p-6 w-full overflow-y-auto">
          <Outlet />
        </main>
      </div>
      <CrashAlertPopup />
    </div>
  )
}
