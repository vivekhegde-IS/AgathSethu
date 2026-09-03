import { create } from 'zustand'
import { getMember1Service } from '@integrations/member1/member1Adapter'
import { getMember3Service } from '@integrations/member3/member3Adapter'
import type { Vehicle } from '@integrations/member1/member1Types'
import type { FusedPosition, VehicleTrajectory } from '@integrations/member3/member3Types'

export interface CitizenVehicle {
  vehicleId: string
  registrationNumber: string
  model: string
  vehicleType: 'car' | 'motorcycle' | 'truck' | 'bus'
  rfidTag: string
  chassisNumber: string
  pucExpiry: string
  insuranceExpiry: string
  activeViolationsCount: number
}

interface VehicleState {
  vehicles: Vehicle[]
  citizenVehicles: CitizenVehicle[]
  selectedVehicleId: string | null
  activeTrajectory: VehicleTrajectory | null
  fusedPosition: FusedPosition | null
  isLoading: boolean
  error: string | null

  fetchLiveVehicles: () => Promise<void>
  selectVehicle: (vehicleId: string) => Promise<void>
  addCitizenVehicle: (vehicle: CitizenVehicle) => void
}

export const useVehicleStore = create<VehicleState>((set) => ({
  vehicles: [],
  citizenVehicles: [
    {
      vehicleId: 'VEH-KA01MJ4582',
      registrationNumber: 'KA01MJ4582',
      model: 'Hyundai Creta SX (O) Diesel',
      vehicleType: 'car',
      rfidTag: 'EPC-3416FA-KA01MJ4582',
      chassisNumber: 'MALC141EALM829103',
      pucExpiry: '2027-03-15',
      insuranceExpiry: '2027-01-20',
      activeViolationsCount: 1,
    },
    {
      vehicleId: 'VEH-KA05XY7711',
      registrationNumber: 'KA05XY7711',
      model: 'Royal Enfield Hunter 350',
      vehicleType: 'motorcycle',
      rfidTag: 'EPC-7711KL-KA05XY7711',
      chassisNumber: 'ME3B142ENNM992144',
      pucExpiry: '2026-12-10',
      insuranceExpiry: '2026-11-05',
      activeViolationsCount: 1,
    },
  ],
  selectedVehicleId: 'VEH-KA01MJ4582',
  activeTrajectory: null,
  fusedPosition: null,
  isLoading: false,
  error: null,

  fetchLiveVehicles: async () => {
    set({ isLoading: true, error: null })
    try {
      const member1 = getMember1Service()
      const data = await member1.listVehicles()
      set({ vehicles: data, isLoading: false })
    } catch (err) {
      set({ error: (err as Error).message, isLoading: false })
    }
  },

  selectVehicle: async (vehicleId: string) => {
    set({ selectedVehicleId: vehicleId, isLoading: true })
    try {
      const member3 = getMember3Service()
      const [traj, fused] = await Promise.all([
        member3.getTrajectory(vehicleId),
        member3.getFusedPosition(vehicleId),
      ])
      set({ activeTrajectory: traj, fusedPosition: fused, isLoading: false })
    } catch (err) {
      set({ error: (err as Error).message, isLoading: false })
    }
  },

  addCitizenVehicle: (vehicle: CitizenVehicle) => {
    set((state) => ({
      citizenVehicles: [vehicle, ...state.citizenVehicles],
    }))
  },
}))
