/**
 * Member 1 Integration - CARLA Simulator & Camera Feed Data Contracts
 * 
 * Member 1 is responsible for:
 * - CARLA simulator scenario management
 * - Vehicle telemetry and positioning
 * - Camera feed capture and streaming
 * - Basic crash detection from physics
 * - IMU data collection
 * 
 * All types are shared between mock and real implementations via adapter pattern.
 * Mock implementation: src/integrations/member1/mock/
 * Real implementation: Will use same contracts via adapter
 */

/**
 * Scenario Configuration - Defines simulation/real-world scenario parameters
 */
export interface Scenario {
  scenario_id: string;
  random_seed: number;
  map: string; // Map name or identifier
  weather: 'clear' | 'rainy' | 'cloudy' | 'fog' | 'night';
  traffic_density: 'low' | 'medium' | 'high';
  vehicle_configuration: {
    number_of_vehicles: number;
    vehicle_types: Array<'car' | 'truck' | 'bus' | 'motorcycle'>;
  };
  camera_configuration: {
    number_of_cameras: number;
    camera_placement: 'intersection' | 'highway' | 'mixed';
  };
  created_at: string; // ISO 8601 timestamp
  description?: string;
}

/**
 * Vehicle Data - Vehicle telemetry and status
 */
export interface Vehicle {
  vehicle_id: string;
  vehicle_type: 'car' | 'truck' | 'bus' | 'motorcycle';
  number_plate: string;
  scenario_id: string;
  status: 'active' | 'parked' | 'accident' | 'stopped';
  position: {
    x: number;
    y: number;
    z: number;
  };
  velocity: {
    vx: number; // velocity x
    vy: number; // velocity y
    vz: number; // velocity z
  };
  acceleration: {
    ax: number; // acceleration x
    ay: number; // acceleration y
    az: number; // acceleration z
  };
  orientation: {
    roll: number; // radians
    pitch: number; // radians
    yaw: number; // radians
  };
  speed_kmh: number;
  heading: number; // degrees 0-360
  last_updated: string; // ISO 8601 timestamp
}

/**
 * Camera Configuration and Status
 */
export interface Camera {
  camera_id: string;
  scenario_id?: string;
  junction_id?: string;
  location: {
    x: number;
    y: number;
    z: number;
    description: string; // e.g., "North-East corner"
  };
  orientation: {
    pitch: number; // degrees, looking down
    yaw: number; // degrees, 0-360
    roll: number; // degrees
  };
  specifications: {
    resolution: string; // e.g., "1920x1080"
    frame_rate: number; // Hz
    fov: number; // Field of view in degrees
    sensor_width_mm: number;
    focal_length_mm: number;
  };
  status: 'active' | 'inactive' | 'error';
  last_heartbeat: string; // ISO 8601 timestamp
  error_message?: string;
}

/**
 * IMU Observation - Inertial Measurement Unit data from a vehicle
 * Used for detecting acceleration/deceleration patterns
 */
export interface IMUObservation {
  timestamp: string; // ISO 8601
  sensor_vehicle_id: string;
  scenario_id: string;
  acceleration: {
    ax: number; // m/s²
    ay: number; // m/s²
    az: number; // m/s²
  };
  angular_velocity: {
    gx: number; // rad/s
    gy: number; // rad/s
    gz: number; // rad/s
  };
  sequence_number: number;
}

/**
 * Camera Frame Metadata - Points to actual image data
 */
export interface CameraFrame {
  scenario_id: string;
  camera_id: string;
  frame_number: number;
  simulation_time: number; // seconds in simulation
  real_timestamp: string; // ISO 8601
  image_url: string; // URL or path to image file
  image_size: {
    width: number;
    height: number;
  };
  checksum?: string; // MD5 or SHA256 for validation
}

/**
 * Crash Detection Event - Physics-based crash detection from Member 1
 */
export interface CrashDetectedEvent {
  schema_version: '1.0';
  event_id: string;
  event_type: 'CRASH_DETECTED';
  scenario_id: string;
  simulation_time: number; // seconds
  producer: 'member1_carla'; // producer identifier
  timestamp: string; // ISO 8601
  payload: {
    vehicles_involved: string[]; // vehicle_ids
    location: {
      x: number;
      y: number;
      z: number;
    };
    severity: 'minor' | 'moderate' | 'severe';
    impact_velocity: number; // km/h
    description: string;
  };
}

/**
 * Health Check Response - Member 1 service status
 */
export interface Member1HealthCheck {
  status: 'healthy' | 'degraded' | 'unhealthy';
  timestamp: string; // ISO 8601
  scenarios_active: number;
  cameras_active: number;
  message?: string;
}
