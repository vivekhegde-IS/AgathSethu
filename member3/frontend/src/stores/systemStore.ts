import { create } from 'zustand'
import { getMember1Service } from '@integrations/member1/member1Adapter'
import { getMember2Service } from '@integrations/member2/member2Adapter'
import { getMember3Service } from '@integrations/member3/member3Adapter'
import type { Member1HealthCheck } from '@integrations/member1/member1Types'
import type { Member2HealthCheck } from '@integrations/member2/member2Types'
import type { Member3HealthCheck } from '@integrations/member3/member3Types'

export interface SystemHealthState {
  member1: Member1HealthCheck | null
  member2: Member2HealthCheck | null
  member3: Member3HealthCheck | null
  overallStatus: 'OPTIMAL' | 'DEGRADED' | 'CRITICAL'
  lastSyncTimestamp: string
  activeSimulation: boolean
  isChecking: boolean

  checkHealth: () => Promise<void>
}

export const useSystemStore = create<SystemHealthState>((set) => ({
  member1: null,
  member2: null,
  member3: null,
  overallStatus: 'OPTIMAL',
  lastSyncTimestamp: new Date().toISOString(),
  activeSimulation: true,
  isChecking: false,

  checkHealth: async () => {
    set({ isChecking: true })
    try {
      const [h1, h2, h3] = await Promise.all([
        getMember1Service().healthCheck(),
        getMember2Service().healthCheck(),
        getMember3Service().healthCheck(),
      ])

      const isAllHealthy =
        h1.status === 'healthy' && h2.status === 'healthy' && h3.status === 'healthy'

      set({
        member1: h1,
        member2: h2,
        member3: h3,
        overallStatus: isAllHealthy ? 'OPTIMAL' : 'DEGRADED',
        lastSyncTimestamp: new Date().toISOString(),
        isChecking: false,
      })
    } catch {
      set({
        overallStatus: 'DEGRADED',
        lastSyncTimestamp: new Date().toISOString(),
        isChecking: false,
      })
    }
  },
}))
