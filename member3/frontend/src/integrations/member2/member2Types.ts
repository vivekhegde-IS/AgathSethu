/**
 * Member 2 Integration - Computer Vision & ANPR Data Contracts
 * 
 * Member 2 is responsible for:
 * - Vehicle detection in camera feeds
 * - License plate recognition (ANPR)
 * - Violation detection (speeding, signal jumping, etc.)
 * - Vehicle classification and attributes
 * 
 * All types are shared between mock and real implementations via adapter pattern.
 * Mock implementation: src/integrations/member2/mock/
 * Real implementation: Will use same contracts via adapter
 */

/**
 * Detection Result - Vehicle detected in a camera frame
 */
export interface Detection {
  detection_id: string;
  camera_id: string;
  frame_number: number;
  scenario_id: string;
  timestamp: string; // ISO 8601
  vehicle_id: string; // May be unknown initially

  // Bounding box in image coordinates
  bounding_box: {
    x: number; // top-left x
    y: number; // top-left y
    width: number;
    height: number;
  };

  // Detection confidence
  confidence: number; // 0.0 to 1.0

  // Vehicle attributes detected
  vehicle_class: 'car' | 'truck' | 'bus' | 'motorcycle' | 'unknown';
  color?: string; // e.g., 'red', 'white', 'black'
}

/**
 * License Plate Recognition Result
 */
export interface PlateRecognition {
  recognition_id: string;
  detection_id: string;
  camera_id: string;
  timestamp: string; // ISO 8601
  license_plate: string;
  confidence: number; // 0.0 to 1.0
  plate_region?: string; // e.g., state code
  is_valid: boolean; // Passes format validation
}

/**
 * Violation Detection Result - Traffic rule violation detected
 */
export interface ViolationDetection {
  violation_id: string;
  camera_id: string;
  scenario_id?: string;
  timestamp: string; // ISO 8601
  license_plate: string;
  vehicle_id?: string;

  // Violation type
  violation_type:
    | 'SPEEDING'
    | 'RED_LIGHT'
    | 'WRONG_LANE'
    | 'NO_HELMET'
    | 'PHONE_USE'
    | 'PARKING_VIOLATION'
    | 'RASH_DRIVING';

  // Violation details
  severity: 'minor' | 'moderate' | 'severe';
  confidence: number; // 0.0 to 1.0
  details: {
    measured_speed?: number; // km/h
    speed_limit?: number; // km/h
    signal_color?: 'red' | 'yellow' | 'green';
    [key: string]: string | number | boolean | undefined | unknown; // Other violation-specific details
  };

  // Evidence
  evidence_image_url: string;
  evidence_video_url?: string;
}

/**
 * Vehicle Attributes - Characteristics detected by CV
 */
export interface VehicleAttributes {
  vehicle_id: string;
  detection_id: string;
  timestamp: string; // ISO 8601
  license_plate: string;

  physical_attributes: {
    make?: string; // e.g., 'Toyota'
    model?: string; // e.g., 'Corolla'
    color: string;
    body_type: 'sedan' | 'suv' | 'truck' | 'van' | 'motorcycle' | 'other';
  };

  condition: {
    has_damage: boolean;
    damage_description?: string;
    is_commercial: boolean;
    has_hazmat_markings: boolean;
  };
}

/**
 * Health Check Response - Member 2 service status
 */
export interface Member2HealthCheck {
  status: 'healthy' | 'degraded' | 'unhealthy';
  timestamp: string; // ISO 8601
  detections_processed: number;
  plates_recognized: number;
  violations_detected: number;
  message?: string;
}
