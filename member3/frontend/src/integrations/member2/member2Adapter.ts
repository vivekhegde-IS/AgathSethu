/**
 * Member 2 Adapter - Bridges Mock and Real Member 2 implementations
 */

import type {
  Detection,
  PlateRecognition,
  ViolationDetection,
  VehicleAttributes,
  Member2HealthCheck,
} from './member2Types'
import { MockMember2Service } from './mock/mockMember2Service'
import { RealMember2Service } from './realMember2Service'

export interface IMember2Service {
  listDetections(cameraId?: string, limit?: number): Promise<Detection[]>
  getDetection(detectionId: string): Promise<Detection>

  recognizePlate(detectionId: string): Promise<PlateRecognition | null>
  listPlateRecognitions(cameraId?: string, limit?: number): Promise<PlateRecognition[]>

  detectViolations(cameraId?: string): Promise<ViolationDetection[]>
  getViolation(violationId: string): Promise<ViolationDetection>
  matchViolationToVehicle(violationId: string, vehicleId: string): Promise<void>

  extractAttributes(detectionId: string): Promise<VehicleAttributes>
  listVehicleHistory(licensePlate: string): Promise<Detection[]>

  subscribeToDetections(
    cameraId: string,
    callback: (detection: Detection) => void
  ): () => void

  subscribeToViolations(
    cameraId: string,
    callback: (violation: ViolationDetection) => void
  ): () => void

  healthCheck(): Promise<Member2HealthCheck>
}

export class Member2Adapter {
  private static instance: IMember2Service | null = null

  static getInstance(): IMember2Service {
    if (!this.instance) {
      const useMock = import.meta.env.VITE_ENABLE_MOCK_DATA !== 'false'
      if (useMock) {
        this.instance = new MockMember2Service()
      } else {
        const baseUrl = import.meta.env.VITE_MEMBER_2_BASE_URL || 'http://localhost:9002'
        this.instance = new RealMember2Service(baseUrl)
      }
    }
    return this.instance
  }

  static reset(): void {
    this.instance = null
  }
}

export function getMember2Service(): IMember2Service {
  return Member2Adapter.getInstance()
}
