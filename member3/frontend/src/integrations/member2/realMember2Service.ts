/**
 * Stub for Real Member 2 Service - FastAPI implementation
 */

import type {
  Detection,
  PlateRecognition,
  ViolationDetection,
  VehicleAttributes,
  Member2HealthCheck,
} from './member2Types'
import type { IMember2Service } from './member2Adapter'

export class RealMember2Service implements IMember2Service {
  protected baseUrl: string

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl
  }

  async listDetections(_cameraId?: string, _limit?: number): Promise<Detection[]> {
    console.warn(`RealMember2Service using ${this.baseUrl}`)
    return []
  }

  async getDetection(_detectionId: string): Promise<Detection> {
    throw new Error('RealMember2Service not implemented.')
  }

  async recognizePlate(_detectionId: string): Promise<PlateRecognition | null> {
    return null
  }

  async listPlateRecognitions(_cameraId?: string, _limit?: number): Promise<PlateRecognition[]> {
    return []
  }

  async detectViolations(_cameraId?: string): Promise<ViolationDetection[]> {
    return []
  }

  async getViolation(_violationId: string): Promise<ViolationDetection> {
    throw new Error('RealMember2Service not implemented.')
  }

  async matchViolationToVehicle(_violationId: string, _vehicleId: string): Promise<void> {
    // No-op for stub
  }

  async extractAttributes(_detectionId: string): Promise<VehicleAttributes> {
    throw new Error('RealMember2Service not implemented.')
  }

  async listVehicleHistory(_licensePlate: string): Promise<Detection[]> {
    return []
  }

  subscribeToDetections(_cameraId: string, _callback: (detection: Detection) => void): () => void {
    return () => {}
  }

  subscribeToViolations(_cameraId: string, _callback: (violation: ViolationDetection) => void): () => void {
    return () => {}
  }

  async healthCheck(): Promise<Member2HealthCheck> {
    return {
      status: 'healthy',
      timestamp: new Date().toISOString(),
      detections_processed: 0,
      plates_recognized: 0,
      violations_detected: 0,
      message: 'FastAPI Member 2 Real Endpoint',
    }
  }
}
