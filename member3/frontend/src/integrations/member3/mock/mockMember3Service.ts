/**
 * Mock Member 3 Service - RFID & Multi-Sensor Fusion
 */

import type {
  RFIDReader,
  RFIDTagDetection,
  FusedPosition,
  VehicleTrajectory,
  BehaviorAnomaly,
  PredictedTrajectory,
  Member3HealthCheck,
} from '../member3Types'
import type { IMember3Service } from '../member3Adapter'

const MOCK_READERS: RFIDReader[] = [
  {
    reader_id: 'RFID-KOR-01-N',
    location: { x: 12.9352, y: 77.6245, z: 5.5, description: 'Sony World North Approach' },
    frequency: 'UHF 865-867MHz',
    read_range_m: 12.0,
    status: 'active',
    last_heartbeat: new Date().toISOString(),
  },
  {
    reader_id: 'RFID-KOR-01-S',
    location: { x: 12.9355, y: 77.6241, z: 5.5, description: 'Sony World South Approach' },
    frequency: 'UHF 865-867MHz',
    read_range_m: 12.0,
    status: 'active',
    last_heartbeat: new Date().toISOString(),
  },
  {
    reader_id: 'RFID-IND-01-E',
    location: { x: 12.9716, y: 77.6412, z: 5.5, description: '100ft Road East Approach' },
    frequency: 'UHF 865-867MHz',
    read_range_m: 15.0,
    status: 'active',
    last_heartbeat: new Date().toISOString(),
  },
]

const MOCK_TAG_DETECTIONS: RFIDTagDetection[] = [
  {
    detection_id: 'TAG-DET-01',
    reader_id: 'RFID-KOR-01-N',
    tag_id: 'EPC-3416FA-KA01MJ4582',
    vehicle_id: 'VEH-KA01MJ4582',
    timestamp: '2026-08-30T10:12:04Z',
    signal_strength: -58.4,
    confidence: 0.99,
  },
  {
    detection_id: 'TAG-DET-02',
    reader_id: 'RFID-KOR-01-S',
    tag_id: 'EPC-7711KL-KA05XY7711',
    vehicle_id: 'VEH-KA05XY7711',
    timestamp: '2026-08-30T10:12:05Z',
    signal_strength: -62.1,
    confidence: 0.98,
  },
]

export class MockMember3Service implements IMember3Service {
  async listRFIDReaders(): Promise<RFIDReader[]> {
    return MOCK_READERS
  }

  async getRFIDReader(readerId: string): Promise<RFIDReader> {
    const reader = MOCK_READERS.find((r) => r.reader_id === readerId)
    if (!reader) throw new Error(`RFID Reader ${readerId} not found`)
    return reader
  }

  async setReaderActive(readerId: string, active: boolean): Promise<RFIDReader> {
    const reader = await this.getRFIDReader(readerId)
    reader.status = active ? 'active' : 'inactive'
    return reader
  }

  async listTagDetections(vehicleId?: string, limit?: number): Promise<RFIDTagDetection[]> {
    let list = MOCK_TAG_DETECTIONS
    if (vehicleId) {
      list = list.filter((t) => t.vehicle_id === vehicleId)
    }
    return limit ? list.slice(0, limit) : list
  }

  subscribeToTagDetections(callback: (detection: RFIDTagDetection) => void): () => void {
    const timer = setInterval(() => {
      callback({
        detection_id: `TAG-LIVE-${Date.now()}`,
        reader_id: 'RFID-KOR-01-N',
        tag_id: 'EPC-3416FA-KA01MJ4582',
        vehicle_id: 'VEH-KA01MJ4582',
        timestamp: new Date().toISOString(),
        signal_strength: -55.0 - Math.random() * 10,
        confidence: 0.98,
      })
    }, 8000)

    return () => clearInterval(timer)
  }

  async getFusedPosition(vehicleId: string): Promise<FusedPosition | null> {
    return {
      fusion_id: `FUS-${vehicleId}-${Date.now()}`,
      vehicle_id: vehicleId,
      timestamp: new Date().toISOString(),
      position: { x: 12.9352, y: 77.6245, z: 0.5 },
      sensors_used: ['member1_gps', 'member2_vision', 'member3_rfid', 'member3_imu'],
      uncertainty: { horizontal_m: 0.2, vertical_m: 0.1 },
      velocity: { vx: 12.4, vy: 8.2, vz: 0.0 },
      confidence: 0.985,
    }
  }

  async getFusedPositionHistory(vehicleId: string, duration_seconds: number): Promise<FusedPosition[]> {
    const base = (await this.getFusedPosition(vehicleId))!
    return Array.from({ length: Math.min(duration_seconds, 10) }, (_, i) => ({
      ...base,
      timestamp: new Date(Date.now() - (10 - i) * 1000).toISOString(),
      position: {
        x: base.position.x - (10 - i) * 0.0001,
        y: base.position.y - (10 - i) * 0.0001,
        z: base.position.z,
      },
      confidence: 0.95 + Math.random() * 0.04,
    }))
  }

  async getTrajectory(vehicleId: string, _startTime?: string, _endTime?: string): Promise<VehicleTrajectory> {
    return {
      trajectory_id: `TRAJ-${vehicleId}-20260830`,
      vehicle_id: vehicleId,
      start_timestamp: '2026-08-30T10:00:00Z',
      end_timestamp: new Date().toISOString(),
      points: [
        {
          timestamp: '2026-08-30T10:00:00Z',
          position: { x: 12.9352, y: 77.6245, z: 0.5 },
          velocity: { vx: 12.5, vy: 0.0, vz: 0.0 },
          confidence: 0.98,
        },
        {
          timestamp: '2026-08-30T10:05:00Z',
          position: { x: 12.9412, y: 77.6301, z: 0.5 },
          velocity: { vx: 14.4, vy: 0.0, vz: 0.0 },
          confidence: 0.96,
        },
        {
          timestamp: '2026-08-30T10:12:00Z',
          position: { x: 12.9716, y: 77.6412, z: 0.5 },
          velocity: { vx: 13.3, vy: 0.0, vz: 0.0 },
          confidence: 0.99,
        },
      ],
      total_distance_m: 4800,
      average_speed_kmh: 48.3,
    }
  }

  async compareTrajectories(_vehicleId1: string, _vehicleId2: string): Promise<number> {
    return 0.87
  }

  async detectAnomalies(vehicleId: string): Promise<BehaviorAnomaly[]> {
    if (vehicleId === 'VEH-DL03CB9912') {
      return [
        {
          anomaly_id: 'ANOM-2026-0830-991',
          vehicle_id: vehicleId,
          timestamp: '2026-08-30T10:14:21Z',
          anomaly_type: 'SUDDEN_DECELERATION',
          severity: 'high',
          confidence: 0.98,
          description: 'Instantaneous deceleration of 14.2 m/s² detected via sensor fusion',
          location: { x: 12.9354, y: 77.6244, z: 0.6 },
        },
      ]
    }
    return []
  }

  async getAnomaly(anomalyId: string): Promise<BehaviorAnomaly> {
    return {
      anomaly_id: anomalyId,
      vehicle_id: 'VEH-DL03CB9912',
      timestamp: '2026-08-30T10:14:21Z',
      anomaly_type: 'SUDDEN_DECELERATION',
      severity: 'high',
      confidence: 0.98,
      description: 'Instantaneous deceleration of 14.2 m/s² detected via sensor fusion',
      location: { x: 12.9354, y: 77.6244, z: 0.6 },
    }
  }

  async predictTrajectory(vehicleId: string, horizon_seconds: number): Promise<PredictedTrajectory> {
    return {
      prediction_id: `PRED-${vehicleId}-${Date.now()}`,
      vehicle_id: vehicleId,
      prediction_timestamp: new Date().toISOString(),
      horizon_seconds,
      predicted_points: [
        {
          timestamp: new Date(Date.now() + 5000).toISOString(),
          position: { x: 12.975, y: 77.645, z: 0.5 },
          velocity: { vx: 13.0, vy: 0.0, vz: 0.0 },
          confidence: 0.92,
        },
        {
          timestamp: new Date(Date.now() + 10000).toISOString(),
          position: { x: 12.98, y: 77.65, z: 0.5 },
          velocity: { vx: 12.0, vy: 0.0, vz: 0.0 },
          confidence: 0.84,
        },
      ],
      confidence: 0.88,
    }
  }

  subscribeToAnomalies(callback: (anomaly: BehaviorAnomaly) => void): () => void {
    const timer = setInterval(() => {
      callback({
        anomaly_id: `ANOM-PULSE-${Date.now()}`,
        vehicle_id: 'VEH-KA05XY7711',
        timestamp: new Date().toISOString(),
        anomaly_type: 'ERRATIC_SPEED',
        severity: 'medium',
        confidence: 0.93,
        description: 'Speed exceedance of +34 km/h above corridor baseline',
        location: { x: 12.9355, y: 77.6241, z: 0.5 },
      })
    }, 40000)

    return () => clearInterval(timer)
  }

  async healthCheck(): Promise<Member3HealthCheck> {
    return {
      status: 'healthy',
      timestamp: new Date().toISOString(),
      rfid_readers_active: MOCK_READERS.length,
      tags_tracked: 38,
      fusion_pipeline_lag_ms: 18.2,
      message: 'Kalman Multi-Sensor Fusion Engine active and converged',
    }
  }
}
