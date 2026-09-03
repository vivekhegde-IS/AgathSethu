/**
 * Stub for Real Member 3 Service - FastAPI implementation
 */

import type {
  RFIDReader,
  RFIDTagDetection,
  FusedPosition,
  VehicleTrajectory,
  BehaviorAnomaly,
  PredictedTrajectory,
  Member3HealthCheck,
} from './member3Types'
import type { IMember3Service } from './member3Adapter'

export class RealMember3Service implements IMember3Service {
  protected baseUrl: string

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl
  }

  async listRFIDReaders(): Promise<RFIDReader[]> {
    console.warn(`RealMember3Service using ${this.baseUrl}`)
    return []
  }

  async getRFIDReader(_readerId: string): Promise<RFIDReader> {
    throw new Error('RealMember3Service not implemented.')
  }

  async setReaderActive(_readerId: string, _active: boolean): Promise<RFIDReader> {
    throw new Error('RealMember3Service not implemented.')
  }

  async listTagDetections(_vehicleId?: string, _limit?: number): Promise<RFIDTagDetection[]> {
    return []
  }

  subscribeToTagDetections(_callback: (detection: RFIDTagDetection) => void): () => void {
    return () => {}
  }

  async getFusedPosition(_vehicleId: string): Promise<FusedPosition | null> {
    return null
  }

  async getFusedPositionHistory(_vehicleId: string, _duration_seconds: number): Promise<FusedPosition[]> {
    return []
  }

  async getTrajectory(_vehicleId: string, _start_time?: string, _end_time?: string): Promise<VehicleTrajectory> {
    throw new Error('RealMember3Service not implemented.')
  }

  async compareTrajectories(_vehicleId1: string, _vehicleId2: string): Promise<number> {
    return 0
  }

  async detectAnomalies(_vehicleId: string): Promise<BehaviorAnomaly[]> {
    return []
  }

  async getAnomaly(_anomalyId: string): Promise<BehaviorAnomaly> {
    throw new Error('RealMember3Service not implemented.')
  }

  async predictTrajectory(_vehicleId: string, _horizon_seconds: number): Promise<PredictedTrajectory> {
    throw new Error('RealMember3Service not implemented.')
  }

  subscribeToAnomalies(_callback: (anomaly: BehaviorAnomaly) => void): () => void {
    return () => {}
  }

  async healthCheck(): Promise<Member3HealthCheck> {
    return {
      status: 'healthy',
      timestamp: new Date().toISOString(),
      rfid_readers_active: 0,
      tags_tracked: 0,
      fusion_pipeline_lag_ms: 0,
      message: 'FastAPI Member 3 Real Endpoint',
    }
  }
}
