/**
 * Member 3 Adapter - Bridges Mock and Real Member 3 implementations
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
import { MockMember3Service } from './mock/mockMember3Service'
import { RealMember3Service } from './realMember3Service'

export interface IMember3Service {
  listRFIDReaders(): Promise<RFIDReader[]>
  getRFIDReader(readerId: string): Promise<RFIDReader>
  setReaderActive(readerId: string, active: boolean): Promise<RFIDReader>

  listTagDetections(vehicleId?: string, limit?: number): Promise<RFIDTagDetection[]>
  subscribeToTagDetections(
    callback: (detection: RFIDTagDetection) => void
  ): () => void

  getFusedPosition(vehicleId: string): Promise<FusedPosition | null>
  getFusedPositionHistory(vehicleId: string, duration_seconds: number): Promise<FusedPosition[]>

  getTrajectory(vehicleId: string, start_time?: string, end_time?: string): Promise<VehicleTrajectory>
  compareTrajectories(vehicleId1: string, vehicleId2: string): Promise<number>

  detectAnomalies(vehicleId: string): Promise<BehaviorAnomaly[]>
  getAnomaly(anomalyId: string): Promise<BehaviorAnomaly>

  predictTrajectory(vehicleId: string, horizon_seconds: number): Promise<PredictedTrajectory>
  subscribeToAnomalies(
    callback: (anomaly: BehaviorAnomaly) => void
  ): () => void

  healthCheck(): Promise<Member3HealthCheck>
}

export class Member3Adapter {
  private static instance: IMember3Service | null = null

  static getInstance(): IMember3Service {
    if (!this.instance) {
      const useMock = import.meta.env.VITE_ENABLE_MOCK_DATA !== 'false'
      if (useMock) {
        this.instance = new MockMember3Service()
      } else {
        const baseUrl = import.meta.env.VITE_MEMBER_3_BASE_URL || 'http://localhost:9003'
        this.instance = new RealMember3Service(baseUrl)
      }
    }
    return this.instance
  }

  static reset(): void {
    this.instance = null
  }
}

export function getMember3Service(): IMember3Service {
  return Member3Adapter.getInstance()
}
