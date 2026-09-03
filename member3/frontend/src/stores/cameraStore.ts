import { create } from 'zustand'
import { getMember1Service } from '@integrations/member1/member1Adapter'
import type { Camera } from '@integrations/member1/member1Types'

export interface Junction {
  junctionId: string
  name: string
  corridor: string
  camerasCount: number
  rfidReadersCount: number
  activeIncidentsCount: number
  throughputPerHour: number
  status: 'OPTIMAL' | 'CONGESTED' | 'INCIDENT' | 'MAINTENANCE'
}

interface CameraState {
  cameras: Camera[]
  junctions: Junction[]
  selectedJunctionId: string
  selectedCameraId: string
  isLoading: boolean
  error: string | null

  fetchCameras: () => Promise<void>
  selectJunction: (junctionId: string) => void
  selectCamera: (cameraId: string) => void
  toggleCameraStatus: (cameraId: string) => Promise<void>
}

const INITIAL_JUNCTIONS: Junction[] = [
  {
    junctionId: 'JUNC-KORM-80FT',
    name: 'Koramangala 80ft Road 4-Way Signal',
    corridor: 'Koramangala - Hosur Road Corridor',
    camerasCount: 8,
    rfidReadersCount: 4,
    activeIncidentsCount: 1,
    throughputPerHour: 3420,
    status: 'INCIDENT',
  },
  {
    junctionId: 'JUNC-INDIRA-100FT',
    name: '100ft Road Indiranagar Junction',
    corridor: 'Indiranagar - Old Airport Arterial',
    camerasCount: 6,
    rfidReadersCount: 3,
    activeIncidentsCount: 0,
    throughputPerHour: 2890,
    status: 'OPTIMAL',
  },
  {
    junctionId: 'JUNC-MG-BRIGADE',
    name: 'MG Road - Brigade Road Cross',
    corridor: 'CBD Central Corridor',
    camerasCount: 10,
    rfidReadersCount: 6,
    activeIncidentsCount: 0,
    throughputPerHour: 4120,
    status: 'CONGESTED',
  },
  {
    junctionId: 'JUNC-SILK-BOARD',
    name: 'Central Silk Board Flyover Junction',
    corridor: 'Outer Ring Road - Electronic City',
    camerasCount: 12,
    rfidReadersCount: 8,
    activeIncidentsCount: 0,
    throughputPerHour: 6240,
    status: 'CONGESTED',
  },
]

export const useCameraStore = create<CameraState>((set, get) => ({
  cameras: [],
  junctions: INITIAL_JUNCTIONS,
  selectedJunctionId: 'JUNC-KORM-80FT',
  selectedCameraId: 'CAM-J01-N',
  isLoading: false,
  error: null,

  fetchCameras: async () => {
    set({ isLoading: true, error: null })
    try {
      const member1 = getMember1Service()
      const cams = await member1.listCameras()
      set({
        cameras: cams,
        selectedCameraId: cams[0]?.camera_id || 'CAM-J01-N',
        isLoading: false,
      })
    } catch (err) {
      set({ error: (err as Error).message, isLoading: false })
    }
  },

  selectJunction: (junctionId: string) => {
    set({ selectedJunctionId: junctionId })
  },

  selectCamera: (cameraId: string) => {
    set({ selectedCameraId: cameraId })
  },

  toggleCameraStatus: async (cameraId: string) => {
    const cam = get().cameras.find((c) => c.camera_id === cameraId)
    if (!cam) return
    const newStatus = cam.status === 'active' ? false : true
    const member1 = getMember1Service()
    await member1.setCameraActive(cameraId, newStatus)
    set((state) => ({
      cameras: state.cameras.map((c) =>
        c.camera_id === cameraId ? { ...c, status: newStatus ? 'active' : 'inactive' } : c
      ),
    }))
  },
}))
