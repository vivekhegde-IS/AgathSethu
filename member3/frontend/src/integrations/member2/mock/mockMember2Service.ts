/**
 * Mock Member 2 Service - Computer Vision, ANPR & Violation Detection
 */

import type {
  Detection,
  PlateRecognition,
  ViolationDetection,
  VehicleAttributes,
  Member2HealthCheck,
} from '../member2Types'
import type { IMember2Service } from '../member2Adapter'

const MOCK_DETECTIONS: Detection[] = [
  {
    detection_id: 'DET-2026-0830-101',
    camera_id: 'CAM-KOR-01',
    frame_number: 4821,
    scenario_id: 'SCN-BLR-KOR-01',
    timestamp: '2026-08-30T10:12:04Z',
    vehicle_id: 'VEH-KA01MJ4582',
    bounding_box: { x: 340, y: 520, width: 280, height: 190 },
    confidence: 0.96,
    vehicle_class: 'car',
    color: 'white',
  },
  {
    detection_id: 'DET-2026-0830-102',
    camera_id: 'CAM-KOR-01',
    frame_number: 4822,
    scenario_id: 'SCN-BLR-KOR-01',
    timestamp: '2026-08-30T10:12:05Z',
    vehicle_id: 'VEH-KA05XY7711',
    bounding_box: { x: 710, y: 480, width: 140, height: 160 },
    confidence: 0.94,
    vehicle_class: 'motorcycle',
    color: 'black',
  },
  {
    detection_id: 'DET-2026-0830-103',
    camera_id: 'CAM-KOR-02',
    frame_number: 4900,
    scenario_id: 'SCN-BLR-KOR-01',
    timestamp: '2026-08-30T10:14:20Z',
    vehicle_id: 'VEH-DL03CB9912',
    bounding_box: { x: 420, y: 390, width: 310, height: 210 },
    confidence: 0.98,
    vehicle_class: 'car',
    color: 'silver',
  },
]

const MOCK_PLATES: PlateRecognition[] = [
  {
    recognition_id: 'ANPR-2026-0830-01',
    detection_id: 'DET-2026-0830-101',
    camera_id: 'CAM-KOR-01',
    timestamp: '2026-08-30T10:12:04Z',
    license_plate: 'KA01MJ4582',
    confidence: 0.97,
    plate_region: 'KA',
    is_valid: true,
  },
  {
    recognition_id: 'ANPR-2026-0830-02',
    detection_id: 'DET-2026-0830-102',
    camera_id: 'CAM-KOR-01',
    timestamp: '2026-08-30T10:12:05Z',
    license_plate: 'KA05XY7711',
    confidence: 0.93,
    plate_region: 'KA',
    is_valid: true,
  },
  {
    recognition_id: 'ANPR-2026-0830-03',
    detection_id: 'DET-2026-0830-103',
    camera_id: 'CAM-KOR-02',
    timestamp: '2026-08-30T10:14:20Z',
    license_plate: 'DL03CB9912',
    confidence: 0.99,
    plate_region: 'DL',
    is_valid: true,
  },
]

const MOCK_VIOLATIONS: ViolationDetection[] = [
  {
    violation_id: 'VIO-2026-0830-001',
    camera_id: 'CAM-KOR-01',
    scenario_id: 'SCN-BLR-KOR-01',
    timestamp: '2026-08-30T09:42:15Z',
    license_plate: 'KA05XY7711',
    vehicle_id: 'VEH-KA05XY7711',
    violation_type: 'SPEEDING',
    severity: 'severe',
    confidence: 0.98,
    details: {
      measured_speed: 84,
      speed_limit: 50,
      lane: 'Fast Lane 1',
    },
    evidence_image_url: 'https://images.unsplash.com/photo-1544620347-c4fd4a3d5957?w=1200&auto=format&fit=crop&q=80',
  },
  {
    violation_id: 'VIO-2026-0830-002',
    camera_id: 'CAM-IND-01',
    scenario_id: 'SCN-BLR-IND-02',
    timestamp: '2026-08-30T10:05:11Z',
    license_plate: 'KA01MJ4582',
    vehicle_id: 'VEH-KA01MJ4582',
    violation_type: 'RED_LIGHT',
    severity: 'moderate',
    confidence: 0.95,
    details: {
      signal_color: 'red',
      time_into_red_seconds: 2.4,
    },
    evidence_image_url: 'https://images.unsplash.com/photo-1506521781263-d8422e82f27a?w=1200&auto=format&fit=crop&q=80',
  },
]

export class MockMember2Service implements IMember2Service {
  async listDetections(cameraId?: string, limit?: number): Promise<Detection[]> {
    let list = MOCK_DETECTIONS
    if (cameraId) {
      list = list.filter((d) => d.camera_id === cameraId)
    }
    return limit ? list.slice(0, limit) : list
  }

  async getDetection(detectionId: string): Promise<Detection> {
    const d = MOCK_DETECTIONS.find((item) => item.detection_id === detectionId)
    if (!d) throw new Error(`Detection ${detectionId} not found`)
    return d
  }

  async recognizePlate(detectionId: string): Promise<PlateRecognition | null> {
    const plate = MOCK_PLATES.find((p) => p.detection_id === detectionId)
    return plate || null
  }

  async listPlateRecognitions(cameraId?: string, limit?: number): Promise<PlateRecognition[]> {
    let list = MOCK_PLATES
    if (cameraId) {
      list = list.filter((p) => p.camera_id === cameraId)
    }
    return limit ? list.slice(0, limit) : list
  }

  async detectViolations(cameraId?: string): Promise<ViolationDetection[]> {
    if (cameraId) {
      return MOCK_VIOLATIONS.filter((v) => v.camera_id === cameraId)
    }
    return MOCK_VIOLATIONS
  }

  async getViolation(violationId: string): Promise<ViolationDetection> {
    const v = MOCK_VIOLATIONS.find((item) => item.violation_id === violationId)
    if (!v) throw new Error(`Violation ${violationId} not found`)
    return v
  }

  async matchViolationToVehicle(_violationId: string, _vehicleId: string): Promise<void> {
    // Association confirmed
  }

  async extractAttributes(detectionId: string): Promise<VehicleAttributes> {
    const d = await this.getDetection(detectionId)
    return {
      vehicle_id: d.vehicle_id,
      detection_id: d.detection_id,
      timestamp: d.timestamp,
      license_plate: MOCK_PLATES.find((p) => p.detection_id === detectionId)?.license_plate || 'KA01MJ4582',
      physical_attributes: {
        make: d.vehicle_class === 'car' ? 'Hyundai' : 'Royal Enfield',
        model: d.vehicle_class === 'car' ? 'Creta SX' : 'Hunter 350',
        color: d.color || 'white',
        body_type: d.vehicle_class === 'motorcycle' ? 'motorcycle' : 'suv',
      },
      condition: {
        has_damage: false,
        is_commercial: false,
        has_hazmat_markings: false,
      },
    }
  }

  async listVehicleHistory(licensePlate: string): Promise<Detection[]> {
    return MOCK_DETECTIONS.filter((d) => {
      const match = MOCK_PLATES.find((p) => p.detection_id === d.detection_id)
      return match?.license_plate === licensePlate
    })
  }

  subscribeToDetections(
    _cameraId: string,
    callback: (detection: Detection) => void
  ): () => void {
    const timer = setInterval(() => {
      callback({
        detection_id: `DET-STREAM-${Date.now()}`,
        camera_id: _cameraId,
        frame_number: Math.floor(Date.now() / 33),
        scenario_id: 'SCN-BLR-KOR-01',
        timestamp: new Date().toISOString(),
        vehicle_id: 'VEH-KA01MJ4582',
        bounding_box: { x: 350 + Math.random() * 20, y: 500, width: 280, height: 190 },
        confidence: 0.97,
        vehicle_class: 'car',
        color: 'white',
      })
    }, 5000)

    return () => clearInterval(timer)
  }

  subscribeToViolations(
    _cameraId: string,
    callback: (violation: ViolationDetection) => void
  ): () => void {
    const timer = setInterval(() => {
      callback({
        violation_id: `VIO-LIVE-${Date.now()}`,
        camera_id: _cameraId,
        scenario_id: 'SCN-BLR-KOR-01',
        timestamp: new Date().toISOString(),
        license_plate: 'HR26DQ5541',
        vehicle_id: 'VEH-HR26DQ5541',
        violation_type: 'WRONG_LANE',
        severity: 'minor',
        confidence: 0.94,
        details: { lane: 'Bus Priority Lane' },
        evidence_image_url: 'https://images.unsplash.com/photo-1544620347-c4fd4a3d5957?w=1200&auto=format&fit=crop&q=80',
      })
    }, 60000)

    return () => clearInterval(timer)
  }

  async healthCheck(): Promise<Member2HealthCheck> {
    return {
      status: 'healthy',
      timestamp: new Date().toISOString(),
      detections_processed: 142080,
      plates_recognized: 139800,
      violations_detected: 412,
      message: 'Computer Vision YOLOv8 + ANPR inference engine active (42 FPS)',
    }
  }
}
