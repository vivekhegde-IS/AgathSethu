/**
 * Stub for Real Member 1 Service - FastAPI implementation
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
import type { IMember1Service } from './member1Adapter'

export class RealMember1Service implements IMember1Service {
  protected baseUrl: string

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl
  }

  async listScenarios(): Promise<Scenario[]> {
    console.warn(`RealMember1Service listScenarios using ${this.baseUrl}`)
    return []
  }

  async getScenario(_scenarioId: string): Promise<Scenario> {
    throw new Error('RealMember1Service not implemented.')
  }

  async createScenario(_scenario: Scenario): Promise<Scenario> {
    throw new Error('RealMember1Service not implemented.')
  }

  async listVehicles(_scenarioId?: string): Promise<Vehicle[]> {
    return []
  }

  async getVehicle(_vehicleId: string): Promise<Vehicle> {
    throw new Error('RealMember1Service not implemented.')
  }

  async trackVehicle(_vehicleId: string, _duration: number): Promise<Vehicle[]> {
    return []
  }

  async listCameras(_scenarioId?: string): Promise<Camera[]> {
    return []
  }

  async getCamera(_cameraId: string): Promise<Camera> {
    throw new Error('RealMember1Service not implemented.')
  }

  async setCameraActive(_cameraId: string, _active: boolean): Promise<Camera> {
    throw new Error('RealMember1Service not implemented.')
  }

  async streamCameraFrame(_cameraId: string): Promise<CameraFrame> {
    throw new Error('RealMember1Service not implemented.')
  }

  async streamIMUData(_vehicleId: string): Promise<IMUObservation[]> {
    return []
  }

  async detectCrashes(_scenarioId: string): Promise<CrashDetectedEvent[]> {
    return []
  }

  subscribeToEvents(
    _scenarioId: string,
    _callback: (event: CrashDetectedEvent) => void
  ): () => void {
    return () => {}
  }

  async healthCheck(): Promise<Member1HealthCheck> {
    return {
      status: 'healthy',
      timestamp: new Date().toISOString(),
      scenarios_active: 0,
      cameras_active: 0,
      message: 'FastAPI Member 1 Real Endpoint',
    }
  }
}
