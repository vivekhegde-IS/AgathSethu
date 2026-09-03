/**
 * Integration Contracts Documentation & Member Separation
 * 
 * This file documents how Member 1, 2, and 3 concerns are separated and how
 * the frontend interacts with each member's services.
 */

/**
 * MEMBER SEPARATION ARCHITECTURE
 * 
 * Member 1 (CARLA Simulator & Cameras)
 * ├── Responsibility: Scenario simulation, vehicle positioning, camera feeds
 * ├── Types: src/integrations/member1/member1Types.ts
 * ├── Adapter: src/integrations/member1/member1Adapter.ts
 * ├── Mock: src/integrations/member1/mock/mockMember1Service.ts
 * └── Real: src/integrations/member1/realMember1Service.ts (future)
 * 
 * Member 2 (CV & ANPR)
 * ├── Responsibility: Vehicle detection, license plate recognition, violation detection
 * ├── Types: src/integrations/member2/member2Types.ts
 * ├── Adapter: src/integrations/member2/member2Adapter.ts
 * ├── Mock: src/integrations/member2/mock/mockMember2Service.ts
 * └── Real: src/integrations/member2/realMember2Service.ts (future)
 * 
 * Member 3 (RFID & Fusion)
 * ├── Responsibility: RFID tracking, position fusion, trajectory prediction, anomaly detection
 * ├── Types: src/integrations/member3/member3Types.ts
 * ├── Adapter: src/integrations/member3/member3Adapter.ts
 * ├── Mock: src/integrations/member3/mock/mockMember3Service.ts
 * └── Real: src/integrations/member3/realMember3Service.ts (future)
 * 
 * CRITICAL: React Components MUST NOT contain Member 1, 2, or 3 algorithms.
 * All algorithms stay in backend services.
 */

/**
 * DATA FLOW ARCHITECTURE
 * 
 * [Member 1/2/3 Backend Services]
 *        ↓
 * [Adapter Layer (member*Adapter.ts)]
 *        ↓
 * [Common Data Contracts (member*Types.ts)]
 *        ↓
 * [HTTP Client / WebSocket (axios + custom provider)]
 *        ↓
 * [Zustand Stores (vehicleStore, incidentStore, etc.)]
 *        ↓
 * [React Components (NO algorithms here)]
 *        ↓
 * [User Interface]
 * 
 * This ensures:
 * - Mock and real services use identical contracts
 * - Swapping mock for real requires only adapter change
 * - React never contains domain algorithms
 * - Clear separation of concerns
 */

/**
 * USAGE PATTERN IN COMPONENTS
 * 
 * ✅ CORRECT:
 * ```typescript
 * import { getMember1Service } from '@integrations/member1/member1Adapter'
 * 
 * const vehicles = await getMember1Service().listVehicles(scenarioId)
 * ```
 * 
 * ❌ WRONG:
 * ```typescript
 * import { MockMember1Service } from '@integrations/member1/mock/mockMember1Service'
 * const service = new MockMember1Service() // Bypasses adapter!
 * ```
 * 
 * ❌ WRONG:
 * ```typescript
 * // Implementing detection algorithm in component
 * const detectVehicle = (frame: Image) => {
 *   // ML/CV code here - NO! This belongs in Member 2
 * }
 * ```
 */

/**
 * ENVIRONMENT-BASED BEHAVIOR
 * 
 * VITE_ENABLE_MOCK_DATA=true (Development)
 * └── All adapters return mock services
 *     └── No backend required
 *     └── Fast iteration
 *     └── Consistent test data
 * 
 * VITE_ENABLE_MOCK_DATA=false (Production/Integration)
 * └── All adapters return real FastAPI services
 *     └── Member 1: http://localhost:9001
 *     └── Member 2: http://localhost:9002
 *     └── Member 3: http://localhost:9003
 *     └── URLs configurable via VITE_MEMBER_*_BASE_URL
 */

export const INTEGRATION_DOCS = {
  member1: {
    name: 'CARLA Simulator & Cameras',
    path: '@integrations/member1',
    adapter: 'getMember1Service()',
    exports: [
      'IMember1Service interface',
      'member1Types (Scenario, Vehicle, Camera, etc.)',
      'Member1Adapter factory',
    ],
    mockPath: 'member1/mock/',
    realPath: 'member1/realMember1Service.ts',
  },
  member2: {
    name: 'Computer Vision & ANPR',
    path: '@integrations/member2',
    adapter: 'getMember2Service()',
    exports: [
      'IMember2Service interface',
      'member2Types (Detection, PlateRecognition, ViolationDetection, etc.)',
      'Member2Adapter factory',
    ],
    mockPath: 'member2/mock/',
    realPath: 'member2/realMember2Service.ts',
  },
  member3: {
    name: 'RFID & Sensor Fusion',
    path: '@integrations/member3',
    adapter: 'getMember3Service()',
    exports: [
      'IMember3Service interface',
      'member3Types (RFIDReader, FusedPosition, VehicleTrajectory, etc.)',
      'Member3Adapter factory',
    ],
    mockPath: 'member3/mock/',
    realPath: 'member3/realMember3Service.ts',
  },
}
