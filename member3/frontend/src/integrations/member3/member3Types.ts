/**
 * Member 3 Integration - RFID & Sensor Fusion Data Contracts
 * 
 * Member 3 is responsible for:
 * - RFID tag tracking and positioning
 * - Multi-sensor data fusion
 * - Vehicle trajectory reconstruction
 * - Advanced behavior prediction
 * 
 * All types are shared between mock and real implementations via adapter pattern.
 * Mock implementation: src/integrations/member3/mock/
 * Real implementation: Will use same contracts via adapter
 */

/**
 * RFID Reader Configuration
 */
export interface RFIDReader {
  reader_id: string;
  location: {
    x: number;
    y: number;
    z: number;
    description: string;
  };
  frequency: string; // e.g., "UHF", "HF"
  read_range_m: number;
  status: 'active' | 'inactive' | 'error';
  last_heartbeat: string; // ISO 8601
}

/**
 * RFID Tag Detection - When a tag is read by a reader
 */
export interface RFIDTagDetection {
  detection_id: string;
  reader_id: string;
  tag_id: string; // Vehicle's RFID tag
  vehicle_id?: string;
  timestamp: string; // ISO 8601
  signal_strength: number; // RSSI in dBm
  confidence: number; // 0.0 to 1.0
}

/**
 * Fused Position - Combined position from multiple sensors
 */
export interface FusedPosition {
  fusion_id: string;
  vehicle_id: string;
  timestamp: string; // ISO 8601
  scenario_id?: string;

  position: {
    x: number;
    y: number;
    z: number;
  };

  // Sensor sources used in fusion
  sensors_used: Array<'member1_gps' | 'member2_vision' | 'member3_rfid' | 'member3_imu'>;

  // Uncertainty estimate
  uncertainty: {
    horizontal_m: number;
    vertical_m: number;
  };

  velocity: {
    vx: number;
    vy: number;
    vz: number;
  };

  confidence: number; // 0.0 to 1.0
}

/**
 * Trajectory Point - Single point in a vehicle's trajectory
 */
export interface TrajectoryPoint {
  timestamp: string; // ISO 8601
  position: {
    x: number;
    y: number;
    z: number;
  };
  velocity: {
    vx: number;
    vy: number;
    vz: number;
  };
  confidence: number;
}

/**
 * Vehicle Trajectory - Complete path history
 */
export interface VehicleTrajectory {
  trajectory_id: string;
  vehicle_id: string;
  scenario_id?: string;
  start_timestamp: string;
  end_timestamp: string;
  points: TrajectoryPoint[];
  total_distance_m: number;
  average_speed_kmh: number;
}

/**
 * Behavior Anomaly - Unusual driving pattern detected
 */
export interface BehaviorAnomaly {
  anomaly_id: string;
  vehicle_id: string;
  timestamp: string; // ISO 8601
  scenario_id?: string;

  anomaly_type:
    | 'SUDDEN_ACCELERATION'
    | 'SUDDEN_DECELERATION'
    | 'SHARP_TURN'
    | 'ZIGZAG'
    | 'ERRATIC_SPEED'
    | 'STOP_AND_GO'
    | 'ROUTE_DEVIATION';

  severity: 'low' | 'medium' | 'high';
  confidence: number; // 0.0 to 1.0
  description: string;
  location?: {
    x: number;
    y: number;
    z: number;
  };
}

/**
 * Predicted Trajectory - ML-based future position prediction
 */
export interface PredictedTrajectory {
  prediction_id: string;
  vehicle_id: string;
  prediction_timestamp: string; // When prediction was made
  horizon_seconds: number; // How far into future
  predicted_points: TrajectoryPoint[];
  confidence: number; // 0.0 to 1.0
}

/**
 * Health Check Response - Member 3 service status
 */
export interface Member3HealthCheck {
  status: 'healthy' | 'degraded' | 'unhealthy';
  timestamp: string; // ISO 8601
  rfid_readers_active: number;
  tags_tracked: number;
  fusion_pipeline_lag_ms: number;
  message?: string;
}
