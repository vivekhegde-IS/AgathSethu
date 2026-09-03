import { create } from 'zustand'
import { getMember1Service } from '@integrations/member1/member1Adapter'

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
  isLoading: boolean
  error: string | null

  fetchIncidents: () => Promise<void>
  selectIncident: (id: string) => void
  updateIncidentStatus: (id: string, status: CrashIncident['status']) => void
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
}))
