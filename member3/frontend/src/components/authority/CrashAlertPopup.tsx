import React from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@components/ui/Button'
import { Modal } from '@components/ui/Modal'
import { useIncidentStore } from '@stores/incidentStore'

const formatTimestamp = (value?: string | null) => {
  if (!value) return 'N/A'

  try {
    const parsed = new Date(value)
    if (Number.isNaN(parsed.getTime())) return value
    return parsed.toLocaleString()
  } catch {
    return value
  }
}

const formatMaybe = (value: string | number | null | undefined, fallback = 'N/A') => {
  if (value === null || value === undefined || value === '') return fallback
  return String(value)
}

export const CrashAlertPopup: React.FC = () => {
  const navigate = useNavigate()
  // The active alert is stored as an OBJECT — no ID lookup that could fail
  // silently. If a crash_alert arrived, activeCrashAlert is always populated.
  const activeAlert = useIncidentStore((state) => state.activeCrashAlert)
  const dismissCrashAlert = useIncidentStore((state) => state.dismissCrashAlert)

  if (!activeAlert) return null

  const handleViewIncident = () => {
    const crashId = activeAlert.alert_id
    const focusJunction = activeAlert.junction_id || activeAlert.junction || 'Crash location'
    const crashState = {
      incidentId: crashId,
      alertId: crashId,
      focusJunction,
      vehicle: activeAlert.vehicle,
      collisionPartner: activeAlert.collision_partner,
      plate: activeAlert.plate,
      timestamp: activeAlert.timestamp,
      crashLocation: activeAlert.latitude !== null && activeAlert.longitude !== null
        ? `${activeAlert.latitude}, ${activeAlert.longitude}`
        : activeAlert.world_location
          ? `${activeAlert.world_x ?? 'N/A'}, ${activeAlert.world_y ?? 'N/A'}`
          : 'Unknown',
      alert: activeAlert,
    }

    dismissCrashAlert(activeAlert.alert_id)

    navigate('/authority/live', {
      replace: true,
      state: crashState,
    })
  }

  const handleDismiss = () => {
    dismissCrashAlert(activeAlert.alert_id)
  }

  const locationLabel = activeAlert.junction_id || activeAlert.junction || 'Crash location'

  return (
    <Modal
      isOpen={Boolean(activeAlert)}
      onClose={handleDismiss}
      maxWidth="md"
      title={
        <div className="flex items-center gap-2 text-red-700">
          <span className="text-xl">🚨</span>
          <span className="tracking-[0.2em] text-xs font-mono">CRASH DETECTED</span>
        </div>
      }
    >
      <div className="space-y-4 text-sm text-slate-800">
        <p className="text-slate-700">
          A vehicle collision has been detected.
        </p>

        <div className="grid gap-2 text-xs font-mono md:grid-cols-2">
          <div className="rounded border border-slate-300 bg-slate-50 p-3">
            <span className="text-slate-600 block uppercase tracking-wide">Vehicles</span>
            <span className="mt-1 block text-base font-semibold text-slate-900">
              {formatMaybe(activeAlert.vehicle, 'Unknown')} ↔ {formatMaybe(activeAlert.collision_partner, 'Unknown')}
            </span>
          </div>
          <div className="rounded border border-slate-300 bg-slate-50 p-3">
            <span className="text-slate-600 block uppercase tracking-wide">Junction</span>
            <span className="mt-1 block text-base font-semibold text-slate-900">{locationLabel}</span>
          </div>
          <div className="rounded border border-slate-300 bg-slate-50 p-3">
            <span className="text-slate-600 block uppercase tracking-wide">Plate</span>
            <span className="mt-1 block text-base font-semibold text-slate-900">{formatMaybe(activeAlert.plate, 'N/A')}</span>
          </div>
          <div className="rounded border border-slate-300 bg-slate-50 p-3">
            <span className="text-slate-600 block uppercase tracking-wide">Position</span>
            <span className="mt-1 block text-base font-semibold text-slate-900">
              {activeAlert.latitude != null && activeAlert.longitude != null
                ? `${activeAlert.latitude}, ${activeAlert.longitude}`
                : activeAlert.world_x != null && activeAlert.world_y != null
                  ? `${activeAlert.world_x}, ${activeAlert.world_y}`
                  : 'N/A'}
            </span>
          </div>
        </div>

        <div className="rounded border border-red-300 bg-red-50 p-3 text-xs text-red-800">
          <div className="flex items-center justify-between gap-3">
            <span className="font-mono text-red-700 uppercase">Received at</span>
            <span className="font-mono text-slate-900">{formatTimestamp(activeAlert.received_at ?? activeAlert.timestamp)}</span>
          </div>
          <div className="mt-2 flex items-center justify-between gap-3">
            <span className="font-mono text-red-700 uppercase">Junction</span>
            <span className="font-mono text-slate-900">{locationLabel}</span>
          </div>
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:justify-end">
          <Button variant="secondary" size="sm" onClick={handleDismiss}>
            DISMISS
          </Button>
          <Button variant="danger" size="sm" onClick={handleViewIncident}>
            VIEW LIVE INCIDENT
          </Button>
        </div>
      </div>
    </Modal>
  )
}

export const registerCrashAlert = (payload: Record<string, unknown>) => {
  const store = useIncidentStore.getState()
  return store.registerCrashAlert(payload)
}
