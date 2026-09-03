/**
 * Member 1 Adapter - Bridges Mock and Real Member 1 implementations
 */

import type {
  Scenario,
  Vehicle,
  Camera,
  IMUObservation,
  CameraFrame,
  CrashDetectedEvent,
  Member1HealthCheck,
} from './member1Types'
import { MockMember1Service } from './mock/mockMember1Service'
import { RealMember1Service } from './realMember1Service'

export interface IMember1Service {
  listScenarios(): Promise<Scenario[]>
  getScenario(scenarioId: string): Promise<Scenario>
  createScenario(scenario: Scenario): Promise<Scenario>

  listVehicles(scenarioId?: string): Promise<Vehicle[]>
  getVehicle(vehicleId: string): Promise<Vehicle>
  trackVehicle(vehicleId: string, duration: number): Promise<Vehicle[]>

  listCameras(scenarioId?: string): Promise<Camera[]>
  getCamera(cameraId: string): Promise<Camera>
  setCameraActive(cameraId: string, active: boolean): Promise<Camera>

  streamCameraFrame(cameraId: string): Promise<CameraFrame>
  streamIMUData(vehicleId: string): Promise<IMUObservation[]>

  detectCrashes(scenarioId: string): Promise<CrashDetectedEvent[]>
  subscribeToEvents(
    scenarioId: string,
    callback: (event: CrashDetectedEvent) => void
  ): () => void

  healthCheck(): Promise<Member1HealthCheck>
}

export class Member1Adapter {
  private static instance: IMember1Service | null = null

  static getInstance(): IMember1Service {
    if (!this.instance) {
      const useMock = import.meta.env.VITE_ENABLE_MOCK_DATA !== 'false'
      if (useMock) {
        this.instance = new MockMember1Service()
      } else {
        const baseUrl = import.meta.env.VITE_MEMBER_1_BASE_URL || 'http://localhost:9001'
        this.instance = new RealMember1Service(baseUrl)
      }
    }
    return this.instance
  }

  static reset(): void {
    this.instance = null
  }
}

export function getMember1Service(): IMember1Service {
  return Member1Adapter.getInstance()
}
