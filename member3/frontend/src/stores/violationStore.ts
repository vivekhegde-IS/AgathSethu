import { create } from 'zustand'
import { getMember2Service } from '@integrations/member2/member2Adapter'
import type { ViolationDetection } from '@integrations/member2/member2Types'

export interface EnrichedViolation extends ViolationDetection {
  status: 'PENDING' | 'CHALLAN_ISSUED' | 'PAID' | 'DISPUTED' | 'DISMISSED'
  location: string
  fineAmount: number
  paymentId?: string
  paidAt?: string
}

interface ViolationState {
  violations: EnrichedViolation[]
  selectedViolationId: string | null
  isLoading: boolean
  error: string | null

  fetchViolations: () => Promise<void>
  selectViolation: (id: string) => void
  payViolationFine: (violationId: string, paymentMethod: string) => Promise<string>
  updateViolationStatus: (violationId: string, status: EnrichedViolation['status']) => void
}

const INITIAL_VIOLATIONS: EnrichedViolation[] = [
  {
    violation_id: 'VIOL-2026-8910',
    camera_id: 'CAM-J01-N',
    scenario_id: 'SCEN-KORAMANGALA-01',
    timestamp: new Date(Date.now() - 3600000 * 4).toISOString(),
    license_plate: 'KA01MJ4582',
    vehicle_id: 'VEH-KA01MJ4582',
    violation_type: 'SPEEDING',
    severity: 'moderate',
    confidence: 0.95,
    details: {
      measured_speed: 68.5,
      speed_limit: 50.0,
      excess_speed: 18.5,
      fine_amount: 1000,
    },
    evidence_image_url: 'https://images.unsplash.com/photo-1549317661-bd32c8ce0db2?auto=format&fit=crop&w=800&q=80',
    status: 'PENDING',
    location: 'Koramangala 80ft Road Northbound',
    fineAmount: 1000,
  },
  {
    violation_id: 'VIOL-2026-8911',
    camera_id: 'CAM-J01-N',
    scenario_id: 'SCEN-KORAMANGALA-01',
    timestamp: new Date(Date.now() - 3600000 * 24).toISOString(),
    license_plate: 'KA03AB9012',
    vehicle_id: 'VEH-KA03AB9012',
    violation_type: 'RED_LIGHT',
    severity: 'severe',
    confidence: 0.98,
    details: {
      signal_color: 'red',
      red_elapsed_seconds: 3.2,
      fine_amount: 1000,
    },
    evidence_image_url: 'https://images.unsplash.com/photo-1508974239320-0a029497e820?auto=format&fit=crop&w=800&q=80',
    status: 'CHALLAN_ISSUED',
    location: 'Sony World Signal Koramangala',
    fineAmount: 1000,
  },
  {
    violation_id: 'VIOL-2026-8912',
    camera_id: 'CAM-J01-S',
    scenario_id: 'SCEN-KORAMANGALA-01',
    timestamp: new Date(Date.now() - 3600000 * 48).toISOString(),
    license_plate: 'KA05XY7711',
    vehicle_id: 'VEH-KA05XY7711',
    violation_type: 'NO_HELMET',
    severity: 'moderate',
    confidence: 0.92,
    details: {
      riders_detected: 2,
      helmets_detected: 0,
      fine_amount: 500,
    },
    evidence_image_url: 'https://images.unsplash.com/photo-1558981403-c5f9899a28bc?auto=format&fit=crop&w=800&q=80',
    status: 'PENDING',
    location: '100ft Road Indiranagar Signal',
    fineAmount: 500,
  },
]

export const useViolationStore = create<ViolationState>((set) => ({
  violations: INITIAL_VIOLATIONS,
  selectedViolationId: INITIAL_VIOLATIONS[0].violation_id,
  isLoading: false,
  error: null,

  fetchViolations: async () => {
    set({ isLoading: true, error: null })
    try {
      const member2 = getMember2Service()
      const raw = await member2.detectViolations()
      if (raw.length > 0) {
        const enriched = raw.map((r) => ({
          ...r,
          status: 'PENDING' as const,
          location: 'Koramangala 80ft Intersection',
          fineAmount: Number(r.details?.fine_amount) || 1000,
        }))
        set({ violations: enriched, isLoading: false })
      } else {
        set({ isLoading: false })
      }
    } catch (err) {
      set({ error: (err as Error).message, isLoading: false })
    }
  },

  selectViolation: (id: string) => {
    set({ selectedViolationId: id })
  },

  payViolationFine: async (violationId: string, _paymentMethod: string) => {
    const paymentId = `PAY-${Math.floor(100000 + Math.random() * 900000)}`
    set((state) => ({
      violations: state.violations.map((v) =>
        v.violation_id === violationId
          ? { ...v, status: 'PAID', paymentId, paidAt: new Date().toISOString() }
          : v
      ),
    }))
    return paymentId
  },

  updateViolationStatus: (violationId: string, status: EnrichedViolation['status']) => {
    set((state) => ({
      violations: state.violations.map((v) =>
        v.violation_id === violationId ? { ...v, status } : v
      ),
    }))
  },
}))
