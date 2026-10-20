import { create } from 'zustand'
import { getMember1Service } from '@integrations/member1/member1Adapter'

export interface CrashAlertState {
  alert_id: string
  vehicle: string
  plate: string
  epc: string
  status: string
  crash_probability: number | null
  latitude: number | null
  longitude: number | null
  world_x: number | null
  world_y: number | null
  world_z: number | null
  collision_partner: string | null
  pair_distance: number | null
  relative_speed: number | null
  closing_distance: number | null
  association_score: number | null
  /** Wall-clock time the alert arrived at the viewer (ISO string). */
  timestamp: string
  /** CARLA simulation elapsed seconds at the moment of the crash. */
  timestamp_sim: number | null
  /** Wall-clock time the backend received the alert (ISO string), if provided. */
  received_at: string | null
  frame: number | null
  junction_id: string | null
  junction: string | null
  gps?: { latitude?: number | null; longitude?: number | null; altitude?: number | null } | null
  world_location?: { x?: number | null; y?: number | null; z?: number | null } | null
  raw?: Record<string, unknown>
}

export interface ActiveIncidentState {
  alert: CrashAlertState | null
  latestImu: Record<string, unknown> | null
  latestImuDetection: Record<string, unknown> | null
  latestGps: Record<string, unknown> | null
  latestRfid: Record<string, unknown> | null
  latestVehicleState: Record<string, unknown> | null
  cameraContext: Record<string, unknown> | null
  updatedAt: string | null
}
export interface CandidateVehicle {
  vehicleId: string
  licensePlate: string
  vehicleType: string
  proximityMeters: number
  speedBeforeImpact: number
  speedAfterImpact: number
  anomalyScore: number // 0-100
  identityMatch: 'MATCHED' | 'MISMATCH' | 'UNVERIFIED'
  rfidConfirmed: boolean
  visualConfirmed: boolean
  role: 'PRIMARY_COLLIDER' | 'VICTIM' | 'FLEEING_SUSPECT' | 'WITNESS'
}

export interface CrashIncident {
  incidentId: string
  title: string
  severity: 'CRITICAL' | 'MAJOR' | 'MODERATE'
  status: 'INVESTIGATING' | 'DISPATCHED' | 'RESOLVED' | 'ARCHIVED'
  timestamp: string
  location: {
    junctionId: string
    junctionName: string
    coordinates: { lat: number; lng: number }
  }
  impactSpeedKmh: number
  vehiclesInvolved: string[]
  evidenceImages: string[]
  candidateVehicles: CandidateVehicle[]
  reconstructionTrajectoryId: string
  investigatingOfficer: string
  summary: string
}

interface IncidentState {
  incidents: CrashIncident[]
  selectedIncidentId: string | null
  crashAlerts: CrashAlertState[]
  activeCrashAlertId: string | null
  /** The active alert OBJECT — popup renders this directly, no ID lookup. */
  activeCrashAlert: CrashAlertState | null
  activeIncident: ActiveIncidentState | null
  /** Monotonic gate for high-frequency telemetry writes (ms). */
  lastTelemetryUpdate: number
  isLoading: boolean
  error: string | null

  fetchIncidents: () => Promise<void>
  selectIncident: (id: string) => void
  updateIncidentStatus: (id: string, status: CrashIncident['status']) => void
  registerCrashAlert: (payload: Record<string, unknown>) => CrashAlertState | null
  registerLiveIncidentMessage: (payload: Record<string, unknown>) => void
  dismissCrashAlert: (alertId?: string) => void
}

const TELEMETRY_THROTTLE_MS = 250

const createEmptyActiveIncident = (): ActiveIncidentState => ({
  alert: null,
  latestImu: null,
  latestImuDetection: null,
  latestGps: null,
  latestRfid: null,
  latestVehicleState: null,
  cameraContext: null,
  updatedAt: null,
})

const toNullableNumber = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') return null
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

const toTimestampString = (value: unknown): string => {
  if (typeof value === 'string' && value.trim()) {
    return value
  }

  // Numeric values are CARLA simulation elapsed seconds, not Unix epochs —
  // converting them produced bogus 1970 dates. Wall-clock time is taken
  // when the alert arrives instead.
  return new Date().toISOString()
}

const getCrashAlertKey = (alert: Partial<CrashAlertState>) => {
  if (alert.alert_id) return `alert:${alert.alert_id}`

  return `fallback:${alert.vehicle ?? 'unknown'}:${alert.collision_partner ?? 'unknown'}:${alert.timestamp ?? 'na'}:${String(alert.frame ?? 'na')}`
}

const normalizeCrashAlert = (payload: Record<string, unknown>): CrashAlertState => {
  const gps = (payload.gps as Record<string, unknown> | undefined) ?? null
  const worldLocation = (payload.world_location as Record<string, unknown> | undefined) ?? null
  const latitude = toNullableNumber(gps?.latitude ?? payload.latitude)
  const longitude = toNullableNumber(gps?.longitude ?? payload.longitude)
  const worldX = toNullableNumber(worldLocation?.x ?? payload.world_x)
  const worldY = toNullableNumber(worldLocation?.y ?? payload.world_y)
  const worldZ = toNullableNumber(worldLocation?.z ?? payload.world_z)

  const alertId = String(payload.alert_id ?? payload.id ?? 'unknown')
  const timestamp = toTimestampString(payload.timestamp_sim ?? payload.timestamp)

  const normalized: CrashAlertState = {
    alert_id: alertId,
    vehicle: String(payload.vehicle_id ?? payload.vehicle ?? payload.name ?? 'Unknown'),
    plate: String(payload.plate_number ?? payload.plate ?? payload.license_plate ?? 'N/A'),
    epc: String(payload.epc ?? 'N/A'),
    status: String(payload.status ?? 'Crash Confirmed'),
    crash_probability: toNullableNumber(payload.crash_probability),
    latitude,
    longitude,
    world_x: worldX,
    world_y: worldY,
    world_z: worldZ,
    collision_partner: payload.collision_partner ? String(payload.collision_partner) : null,
    pair_distance: toNullableNumber(payload.pair_distance_m ?? payload.pair_distance),
    relative_speed: toNullableNumber(payload.relative_speed_kmh ?? payload.relative_speed),
    closing_distance: toNullableNumber(payload.closing_distance_m ?? payload.closing_distance),
    association_score: toNullableNumber(payload.association_score),
    timestamp,
    timestamp_sim: toNullableNumber(payload.timestamp_sim),
    received_at: typeof payload.received_at === 'string' ? payload.received_at : null,
    frame: toNullableNumber(payload.frame),
    junction_id: typeof payload.junction_id === 'string' ? payload.junction_id : null,
    junction: typeof payload.junction === 'string' ? payload.junction : null,
    gps: gps ? { latitude: latitude ?? null, longitude: longitude ?? null, altitude: toNullableNumber(gps.altitude) } : null,
    world_location: worldLocation
      ? { x: worldX ?? null, y: worldY ?? null, z: worldZ ?? null }
      : null,
    raw: payload,
  }

  return normalized
}

const INITIAL_INCIDENTS: CrashIncident[] = [
  {
    incidentId: 'INC-20260901-01',
    title: 'High-Impact Intersection Collision & Suspect Evacuation',
    severity: 'CRITICAL',
    status: 'INVESTIGATING',
    timestamp: new Date(Date.now() - 1800000).toISOString(),
    location: {
      junctionId: 'JUNC-KORM-80FT',
      junctionName: 'Koramangala 80ft Road & 4th Block Signal',
      coordinates: { lat: 12.9352, lng: 77.6245 },
    },
    impactSpeedKmh: 64.2,
    vehiclesInvolved: ['KA03AB9012', 'KA05XY7711'],
    evidenceImages: [
      'https://images.unsplash.com/photo-1549317661-bd32c8ce0db2?auto=format&fit=crop&w=800&q=80',
      'https://images.unsplash.com/photo-1508974239320-0a029497e820?auto=format&fit=crop&w=800&q=80',
    ],
    candidateVehicles: [
      {
        vehicleId: 'VEH-KA03AB9012',
        licensePlate: 'KA03AB9012',
        vehicleType: 'Sedan (Black)',
        proximityMeters: 0.4,
        speedBeforeImpact: 66.8,
        speedAfterImpact: 14.2,
        anomalyScore: 94,
        identityMatch: 'MATCHED',
        rfidConfirmed: true,
        visualConfirmed: true,
        role: 'PRIMARY_COLLIDER',
      },
      {
        vehicleId: 'VEH-KA05XY7711',
        licensePlate: 'KA05XY7711',
        vehicleType: 'Motorcycle',
        proximityMeters: 0.1,
        speedBeforeImpact: 28.0,
        speedAfterImpact: 0.0,
        anomalyScore: 78,
        identityMatch: 'MATCHED',
        rfidConfirmed: true,
        visualConfirmed: true,
        role: 'VICTIM',
      },
      {
        vehicleId: 'VEH-KA01MJ4582',
        licensePlate: 'KA01MJ4582',
        vehicleType: 'SUV (White)',
        proximityMeters: 14.8,
        speedBeforeImpact: 51.2,
        speedAfterImpact: 50.8,
        anomalyScore: 12,
        identityMatch: 'MATCHED',
        rfidConfirmed: true,
        visualConfirmed: true,
        role: 'WITNESS',
      },
    ],
    reconstructionTrajectoryId: 'TRAJ-RECON-9921',
    investigatingOfficer: 'Insp. Vikram Sen (Command Unit 4)',
    summary:
      'Vehicle KA03AB9012 entered intersection 3.2s after red phase onset at 66.8 km/h, impacting motorcycle KA05XY7711 at junction center. RFID and ANPR fused trajectory confirms erratic acceleration.',
  },
  {
    incidentId: 'INC-20260831-04',
    title: 'Sideswipe & Failure to Stop Near Indiranagar 100ft',
    severity: 'MAJOR',
    status: 'DISPATCHED',
    timestamp: new Date(Date.now() - 86400000).toISOString(),
    location: {
      junctionId: 'JUNC-INDIRA-100FT',
      junctionName: '100ft Road Indiranagar 12th Main',
      coordinates: { lat: 12.9719, lng: 77.6412 },
    },
    impactSpeedKmh: 42.0,
    vehiclesInvolved: ['KA04MN9912', 'KA01HH3321'],
    evidenceImages: [
      'https://images.unsplash.com/photo-1558981403-c5f9899a28bc?auto=format&fit=crop&w=800&q=80',
    ],
    candidateVehicles: [
      {
        vehicleId: 'VEH-KA04MN9912',
        licensePlate: 'KA04MN9912',
        vehicleType: 'Commercial Truck',
        proximityMeters: 1.2,
        speedBeforeImpact: 44.5,
        speedAfterImpact: 41.0,
        anomalyScore: 89,
        identityMatch: 'MATCHED',
        rfidConfirmed: true,
        visualConfirmed: true,
        role: 'FLEEING_SUSPECT',
      },
    ],
    reconstructionTrajectoryId: 'TRAJ-RECON-8841',
    investigatingOfficer: 'Sub-Insp. Priya Nair',
    summary:
      'Commercial vehicle KA04MN9912 initiated unsafe lane change causing contact with auto-rickshaw, then failed to stop. Multi-junction tracking engaged toward Old Madras Road.',
  },
]

export const useIncidentStore = create<IncidentState>((set) => ({
  incidents: INITIAL_INCIDENTS,
  selectedIncidentId: INITIAL_INCIDENTS[0].incidentId,
  crashAlerts: [],
  activeCrashAlertId: null,
  activeCrashAlert: null,
  activeIncident: createEmptyActiveIncident(),
  lastTelemetryUpdate: 0,
  isLoading: false,
  error: null,

  fetchIncidents: async () => {
    set({ isLoading: true, error: null })
    try {
      const member1 = getMember1Service()
      const crashes = await member1.detectCrashes('SCEN-KORAMANGALA-01')
      if (crashes.length > 0) {
        set({ isLoading: false })
      } else {
        set({ isLoading: false })
      }
    } catch (err) {
      set({ error: (err as Error).message, isLoading: false })
    }
  },

  selectIncident: (id: string) => {
    set({ selectedIncidentId: id })
  },

  updateIncidentStatus: (id: string, status: CrashIncident['status']) => {
    set((state) => ({
      incidents: state.incidents.map((inc) =>
        inc.incidentId === id ? { ...inc, status } : inc
      ),
    }))
  },

  registerCrashAlert: (payload) => {
    const normalized = normalizeCrashAlert(payload)
    const alertKey = getCrashAlertKey(normalized)

    let createdAlert: CrashAlertState | null = null

    set((state) => {
      const currentIndex = state.crashAlerts.findIndex(
        (alert) => getCrashAlertKey(alert) === alertKey
      )

      const nextAlerts = [...state.crashAlerts]
      if (currentIndex >= 0) {
        nextAlerts[currentIndex] = normalized
      } else {
        nextAlerts.unshift(normalized)
        createdAlert = normalized
      }

      const activeIncident = state.activeIncident ?? createEmptyActiveIncident()

      return {
        crashAlerts: nextAlerts.slice(0, 20),
        activeCrashAlertId: normalized.alert_id || alertKey,
        activeCrashAlert: normalized,
        activeIncident: {
          ...activeIncident,
          alert: normalized,
          updatedAt: new Date().toISOString(),
        },
      }
    })

    return createdAlert
  },

  registerLiveIncidentMessage: (payload) => {
    const type = typeof payload.type === 'string' ? payload.type : null
    if (!type) return

    set((state) => {
      const activeIncident = state.activeIncident ?? createEmptyActiveIncident()

      // Crash alerts are critical events — they must NEVER be throttled or
      // dropped, regardless of how much telemetry is flowing.
      if (type === 'crash_alert') {
        const normalized = normalizeCrashAlert(payload)
        const alertKey = getCrashAlertKey(normalized)

        const currentIndex = state.crashAlerts.findIndex(
          (alert) => getCrashAlertKey(alert) === alertKey
        )

        const nextAlerts = [...state.crashAlerts]
        if (currentIndex >= 0) {
          nextAlerts[currentIndex] = normalized
        } else {
          nextAlerts.unshift(normalized)
        }

        return {
          crashAlerts: nextAlerts.slice(0, 20),
          activeCrashAlertId: normalized.alert_id || alertKey,
          activeCrashAlert: normalized,
          activeIncident: {
            ...activeIncident,
            alert: normalized,
            updatedAt: new Date().toISOString(),
          },
        }
      }

      // Throttle high-frequency telemetry so the UI never re-renders per raw
      // sensor message. Final values within the window are what matter.
      const now = Date.now()
      if (now - (state.lastTelemetryUpdate ?? 0) < TELEMETRY_THROTTLE_MS) return {}

      if (type === 'camera_frame') {
        // Strip the base64 image: Live.tsx already renders frames from its own
        // state, and copying ~100KB per frame into the store is pure overhead.
        const { image: _image, ...cameraMeta } = payload
        return {
          lastTelemetryUpdate: now,
          activeIncident: {
            ...activeIncident,
            cameraContext: cameraMeta,
            updatedAt: new Date().toISOString(),
          },
        }
      }

      if (type === 'imu_reading') {
        return {
          lastTelemetryUpdate: now,
          activeIncident: {
            ...activeIncident,
            latestImu: payload,
            updatedAt: new Date().toISOString(),
          },
        }
      }

      if (type === 'imu_detection') {
        return {
          activeIncident: {
            ...activeIncident,
            latestImuDetection: payload,
            updatedAt: new Date().toISOString(),
          },
        }
      }

      if (type === 'gps_reading') {
        return {
          activeIncident: {
            ...activeIncident,
            latestGps: payload,
            updatedAt: new Date().toISOString(),
          },
        }
      }

      if (type === 'rfid_reading') {
        return {
          activeIncident: {
            ...activeIncident,
            latestRfid: payload,
            updatedAt: new Date().toISOString(),
          },
        }
      }

      if (type === 'vehicle_state') {
        return {
          activeIncident: {
            ...activeIncident,
            latestVehicleState: payload,
            updatedAt: new Date().toISOString(),
          },
        }
      }

      return {}
    })
  },

  dismissCrashAlert: (alertId?: string) => {
    set((state) => {
      if (!alertId) {
        return { activeCrashAlertId: null, activeCrashAlert: null }
      }

      if (state.activeCrashAlertId === alertId) {
        return { activeCrashAlertId: null, activeCrashAlert: null }
      }

      return {}
    })
  },
}))
