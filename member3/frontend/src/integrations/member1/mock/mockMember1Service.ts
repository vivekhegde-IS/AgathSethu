/**
 * Mock Member 1 Service - CARLA Simulation, Cameras & IMU Telemetry
 */

import type {
  Scenario,
  Vehicle,
  Camera,
  IMUObservation,
  CameraFrame,
  CrashDetectedEvent,
  Member1HealthCheck,
} from '../member1Types'
import type { IMember1Service } from '../member1Adapter'

const MOCK_SCENARIOS: Scenario[] = [
  {
    scenario_id: 'SCN-BLR-KOR-01',
    random_seed: 42,
    map: 'Town04_Bengaluru_Koramangala',
    weather: 'clear',
    traffic_density: 'high',
    vehicle_configuration: {
      number_of_vehicles: 48,
      vehicle_types: ['car', 'motorcycle', 'bus', 'truck'],
    },
    camera_configuration: {
      number_of_cameras: 6,
      camera_placement: 'intersection',
    },
    created_at: '2026-08-30T10:00:00Z',
    description: 'High-density multi-lane intersection with mixed traffic and pedestrian crosswalks',
  },
  {
    scenario_id: 'SCN-BLR-IND-02',
    random_seed: 108,
    map: 'Town03_Indiranagar_100ft',
    weather: 'rainy',
    traffic_density: 'medium',
    vehicle_configuration: {
      number_of_vehicles: 32,
      vehicle_types: ['car', 'motorcycle'],
    },
    camera_configuration: {
      number_of_cameras: 4,
      camera_placement: 'mixed',
    },
    created_at: '2026-08-30T11:30:00Z',
    description: 'Arterial corridor with rapid speed fluctuations and wet surface conditions',
  },
]

const MOCK_CAMERAS: Camera[] = [
  {
    camera_id: 'CAM-KOR-01',
    scenario_id: 'SCN-BLR-KOR-01',
    junction_id: 'JNC-KOR-80FT',
    location: { x: 12.9352, y: 77.6245, z: 6.5, description: 'Sony World North-East Approach' },
    orientation: { pitch: -25, yaw: 180, roll: 0 },
    specifications: {
      resolution: '1920x1080',
      frame_rate: 30,
      fov: 90,
      sensor_width_mm: 6.4,
      focal_length_mm: 4.2,
    },
    status: 'active',
    last_heartbeat: new Date().toISOString(),
  },
  {
    camera_id: 'CAM-KOR-02',
    scenario_id: 'SCN-BLR-KOR-01',
    junction_id: 'JNC-KOR-80FT',
    location: { x: 12.9355, y: 77.6241, z: 6.5, description: 'Sony World South-West Approach' },
    orientation: { pitch: -20, yaw: 0, roll: 0 },
    specifications: {
      resolution: '1920x1080',
      frame_rate: 30,
      fov: 85,
      sensor_width_mm: 6.4,
      focal_length_mm: 4.8,
    },
    status: 'active',
    last_heartbeat: new Date().toISOString(),
  },
  {
    camera_id: 'CAM-IND-01',
    scenario_id: 'SCN-BLR-IND-02',
    junction_id: 'JNC-IND-100FT',
    location: { x: 12.9716, y: 77.6412, z: 7.0, description: '12th Main Indiranagar Overhead' },
    orientation: { pitch: -30, yaw: 90, roll: 0 },
    specifications: {
      resolution: '1920x1080',
      frame_rate: 30,
      fov: 95,
      sensor_width_mm: 6.4,
      focal_length_mm: 3.6,
    },
    status: 'active',
    last_heartbeat: new Date().toISOString(),
  },
]

const MOCK_VEHICLES: Vehicle[] = [
  {
    vehicle_id: 'VEH-KA01MJ4582',
    vehicle_type: 'car',
    number_plate: 'KA01MJ4582',
    scenario_id: 'SCN-BLR-KOR-01',
    status: 'active',
    position: { x: 12.9352, y: 77.6245, z: 0.5 },
    velocity: { vx: 12.4, vy: 8.2, vz: 0.0 },
    acceleration: { ax: 0.8, ay: 0.2, az: -0.1 },
    orientation: { roll: 0, pitch: 0, yaw: 0.54 },
    speed_kmh: 53.5,
    heading: 31.0,
    last_updated: new Date().toISOString(),
  },
  {
    vehicle_id: 'VEH-KA05XY7711',
    vehicle_type: 'motorcycle',
    number_plate: 'KA05XY7711',
    scenario_id: 'SCN-BLR-KOR-01',
    status: 'active',
    position: { x: 12.9359, y: 77.6249, z: 0.2 },
    velocity: { vx: 18.5, vy: 14.1, vz: 0.0 },
    acceleration: { ax: 2.1, ay: 1.2, az: -0.2 },
    orientation: { roll: 0.05, pitch: 0.01, yaw: 0.65 },
    speed_kmh: 83.7,
    heading: 37.3,
    last_updated: new Date().toISOString(),
  },
  {
    vehicle_id: 'VEH-DL03CB9912',
    vehicle_type: 'car',
    number_plate: 'DL03CB9912',
    scenario_id: 'SCN-BLR-KOR-01',
    status: 'accident',
    position: { x: 12.9354, y: 77.6244, z: 0.6 },
    velocity: { vx: 0.0, vy: 0.0, vz: 0.0 },
    acceleration: { ax: -14.2, ay: -8.5, az: 3.1 },
    orientation: { roll: 0.12, pitch: -0.04, yaw: 1.22 },
    speed_kmh: 0.0,
    heading: 70.0,
    last_updated: new Date().toISOString(),
  },
]

export class MockMember1Service implements IMember1Service {
  async listScenarios(): Promise<Scenario[]> {
    return MOCK_SCENARIOS
  }

  async getScenario(scenarioId: string): Promise<Scenario> {
    const scenario = MOCK_SCENARIOS.find((s) => s.scenario_id === scenarioId)
    if (!scenario) throw new Error(`Scenario ${scenarioId} not found`)
    return scenario
  }

  async createScenario(scenario: Scenario): Promise<Scenario> {
    MOCK_SCENARIOS.push(scenario)
    return scenario
  }

  async listVehicles(scenarioId?: string): Promise<Vehicle[]> {
    if (scenarioId) {
      return MOCK_VEHICLES.filter((v) => v.scenario_id === scenarioId)
    }
    return MOCK_VEHICLES
  }

  async getVehicle(vehicleId: string): Promise<Vehicle> {
    const vehicle = MOCK_VEHICLES.find((v) => v.vehicle_id === vehicleId)
    if (!vehicle) throw new Error(`Vehicle ${vehicleId} not found`)
    return vehicle
  }

  async trackVehicle(vehicleId: string, duration: number): Promise<Vehicle[]> {
    const base = await this.getVehicle(vehicleId)
    const points: Vehicle[] = []
    for (let i = 0; i < Math.min(duration, 10); i++) {
      points.push({
        ...base,
        position: {
          x: base.position.x + i * 0.0001,
          y: base.position.y + i * 0.0001,
          z: base.position.z,
        },
        speed_kmh: Math.max(0, base.speed_kmh - i * 2),
        last_updated: new Date(Date.now() - (10 - i) * 1000).toISOString(),
      })
    }
    return points
  }

  async listCameras(scenarioId?: string): Promise<Camera[]> {
    if (scenarioId) {
      return MOCK_CAMERAS.filter((c) => c.scenario_id === scenarioId)
    }
    return MOCK_CAMERAS
  }

  async getCamera(cameraId: string): Promise<Camera> {
    const camera = MOCK_CAMERAS.find((c) => c.camera_id === cameraId)
    if (!camera) throw new Error(`Camera ${cameraId} not found`)
    return camera
  }

  async setCameraActive(cameraId: string, active: boolean): Promise<Camera> {
    const camera = await this.getCamera(cameraId)
    camera.status = active ? 'active' : 'inactive'
    return camera
  }

  async streamCameraFrame(cameraId: string): Promise<CameraFrame> {
    return {
      scenario_id: 'SCN-BLR-KOR-01',
      camera_id: cameraId,
      frame_number: Math.floor(Date.now() / 33),
      simulation_time: 124.5,
      real_timestamp: new Date().toISOString(),
      image_url: 'https://images.unsplash.com/photo-1506521781263-d8422e82f27a?w=1200&auto=format&fit=crop&q=80',
      image_size: { width: 1920, height: 1080 },
    }
  }

  async streamIMUData(vehicleId: string): Promise<IMUObservation[]> {
    const now = Date.now()
    return Array.from({ length: 15 }, (_, i) => ({
      timestamp: new Date(now - (15 - i) * 100).toISOString(),
      sensor_vehicle_id: vehicleId,
      scenario_id: 'SCN-BLR-KOR-01',
      acceleration: {
        ax: i > 10 ? -12.4 + Math.random() * 2 : 0.8 + Math.random() * 0.2,
        ay: i > 10 ? -6.8 + Math.random() * 1.5 : 0.2 + Math.random() * 0.1,
        az: -9.81 + (Math.random() * 0.4 - 0.2),
      },
      angular_velocity: {
        gx: i > 10 ? 0.42 : 0.01,
        gy: i > 10 ? 0.88 : 0.02,
        gz: i > 10 ? 1.45 : 0.05,
      },
      sequence_number: 1000 + i,
    }))
  }

  async detectCrashes(_scenarioId: string): Promise<CrashDetectedEvent[]> {
    return [
      {
        schema_version: '1.0',
        event_id: 'CRASH-EVT-2026-0830-001',
        event_type: 'CRASH_DETECTED',
        scenario_id: 'SCN-BLR-KOR-01',
        simulation_time: 142.8,
        producer: 'member1_carla',
        timestamp: '2026-08-30T10:14:22Z',
        payload: {
          vehicles_involved: ['VEH-DL03CB9912', 'VEH-MH12PK1008'],
          location: { x: 12.9354, y: 77.6244, z: 0.6 },
          severity: 'severe',
          impact_velocity: 64.2,
          description: 'High-energy T-bone collision detected at Sony World intersection',
        },
      },
    ]
  }

  subscribeToEvents(
    _scenarioId: string,
    callback: (event: CrashDetectedEvent) => void
  ): () => void {
    const timer = setInterval(() => {
      callback({
        schema_version: '1.0',
        event_id: `CRASH-EVT-PULSE-${Date.now()}`,
        event_type: 'CRASH_DETECTED',
        scenario_id: 'SCN-BLR-KOR-01',
        simulation_time: 210.0,
        producer: 'member1_carla',
        timestamp: new Date().toISOString(),
        payload: {
          vehicles_involved: ['VEH-DL03CB9912'],
          location: { x: 12.9354, y: 77.6244, z: 0.6 },
          severity: 'severe',
          impact_velocity: 64.2,
          description: 'Active impact physics verification',
        },
      })
    }, 45000)

    return () => clearInterval(timer)
  }

  async healthCheck(): Promise<Member1HealthCheck> {
    return {
      status: 'healthy',
      timestamp: new Date().toISOString(),
      scenarios_active: MOCK_SCENARIOS.length,
      cameras_active: MOCK_CAMERAS.length,
      message: 'CARLA Simulator Unreal Engine 5.3 bridge operational (60 FPS)',
    }
  }
}
