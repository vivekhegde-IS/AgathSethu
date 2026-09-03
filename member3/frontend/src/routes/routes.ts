/**
 * AGHAT SETHU Routing Architecture
 * 
 * Route Structure:
 * - Public Routes: Accessible without authentication
 * - Citizen Routes: Accessible by authenticated citizens
 * - Authority Routes: Accessible by authenticated authority users
 * 
 * All routes use role-based access control guards defined in roleGuard.ts
 */

import { ReactNode } from 'react'

// Public pages
// TODO: Create pages
// import Home from '@pages/public/Home'
// import About from '@pages/public/About'

// Citizen pages
// TODO: Create pages
// import CitizenLogin from '@pages/citizen/Login'
// import CitizenSignup from '@pages/citizen/Signup'
// import CitizenDashboard from '@pages/citizen/Dashboard'
// import VehicleList from '@pages/citizen/Vehicles'
// import ViolationList from '@pages/citizen/Violations'
// import ViolationDetail from '@pages/citizen/ViolationDetail'
// import PaymentList from '@pages/citizen/Payments'
// import PaymentDetail from '@pages/citizen/PaymentDetail'
// import ReceiptList from '@pages/citizen/Receipts'
// import NotificationCenter from '@pages/citizen/Notifications'
// import ProfilePage from '@pages/citizen/Profile'

// Authority pages
// TODO: Create pages
// import AuthorityLogin from '@pages/authority/Login'
// import AuthoritySignup from '@pages/authority/Signup'
// import AuthorityDashboard from '@pages/authority/Dashboard'
// import Level1Dashboard from '@pages/authority/Level1'
// import ViolationDetailPage from '@pages/authority/ViolationDetail'
// import FineManagement from '@pages/authority/Fines'
// import LiveMonitoring from '@pages/authority/Live'
// import JunctionManagement from '@pages/authority/Junctions'
// import CameraManagement from '@pages/authority/Cameras'
// import IncidentDashboard from '@pages/authority/Incidents'
// import IncidentDetailPage from '@pages/authority/IncidentDetail'
// import VehicleSearch from '@pages/authority/Vehicles'
// import VehicleProfilePage from '@pages/authority/VehicleProfile'
// import TrackingDashboard from '@pages/authority/Tracking'
// import EvidenceManager from '@pages/authority/Evidence'
// import ReportsPage from '@pages/authority/Reports'
// import SystemSettings from '@pages/authority/System'
// import SystemAdminSettings from '@pages/authority/Settings'

// Layouts
// TODO: Create layouts
// import PublicLayout from '@components/layout/PublicLayout'
// import CitizenLayout from '@components/layout/CitizenLayout'
// import AuthorityLayout from '@components/layout/AuthorityLayout'

/**
 * Route Types
 */
export interface RouteConfig {
  path: string
  name: string
  component?: ReactNode
  layout?: ReactNode
  requiresAuth?: boolean
  roles?: Array<'citizen' | 'authority' | 'admin'>
  children?: RouteConfig[]
}

/**
 * PUBLIC ROUTES - No authentication required
 * Path: /
 */
export const publicRoutes: RouteConfig[] = [
  {
    path: '/',
    name: 'Home',
    // component: Home,
    // layout: PublicLayout,
  },
  {
    path: '/about',
    name: 'About',
    // component: About,
    // layout: PublicLayout,
  },
]

/**
 * CITIZEN ROUTES - Requires citizen authentication
 * Path: /citizen/*
 * Role: citizen
 */
export const citizenRoutes: RouteConfig[] = [
  {
    path: 'login',
    name: 'Citizen Login',
    // component: CitizenLogin,
    // layout: PublicLayout,
    requiresAuth: false,
  },
  {
    path: 'signup',
    name: 'Citizen Signup',
    // component: CitizenSignup,
    // layout: PublicLayout,
    requiresAuth: false,
  },
  {
    path: 'dashboard',
    name: 'Citizen Dashboard',
    // component: CitizenDashboard,
    // layout: CitizenLayout,
    requiresAuth: true,
    roles: ['citizen'],
  },
  {
    path: 'vehicles',
    name: 'My Vehicles',
    // component: VehicleList,
    // layout: CitizenLayout,
    requiresAuth: true,
    roles: ['citizen'],
  },
  {
    path: 'violations',
    name: 'My Violations',
    // component: ViolationList,
    // layout: CitizenLayout,
    requiresAuth: true,
    roles: ['citizen'],
  },
  {
    path: 'violations/:violationId',
    name: 'Violation Detail',
    // component: ViolationDetail,
    // layout: CitizenLayout,
    requiresAuth: true,
    roles: ['citizen'],
  },
  {
    path: 'payments',
    name: 'My Payments',
    // component: PaymentList,
    // layout: CitizenLayout,
    requiresAuth: true,
    roles: ['citizen'],
  },
  {
    path: 'payments/:paymentId',
    name: 'Payment Detail',
    // component: PaymentDetail,
    // layout: CitizenLayout,
    requiresAuth: true,
    roles: ['citizen'],
  },
  {
    path: 'receipts',
    name: 'My Receipts',
    // component: ReceiptList,
    // layout: CitizenLayout,
    requiresAuth: true,
    roles: ['citizen'],
  },
  {
    path: 'notifications',
    name: 'Notifications',
    // component: NotificationCenter,
    // layout: CitizenLayout,
    requiresAuth: true,
    roles: ['citizen'],
  },
  {
    path: 'profile',
    name: 'My Profile',
    // component: ProfilePage,
    // layout: CitizenLayout,
    requiresAuth: true,
    roles: ['citizen'],
  },
]

/**
 * AUTHORITY ROUTES - Requires authority authentication
 * Path: /authority/*
 * Role: authority, admin
 */
export const authorityRoutes: RouteConfig[] = [
  {
    path: 'login',
    name: 'Authority Login',
    // component: AuthorityLogin,
    // layout: PublicLayout,
    requiresAuth: false,
  },
  {
    path: 'signup',
    name: 'Authority Signup',
    // component: AuthoritySignup,
    // layout: PublicLayout,
    requiresAuth: false,
  },
  {
    path: 'dashboard',
    name: 'Authority Dashboard',
    // component: AuthorityDashboard,
    // layout: AuthorityLayout,
    requiresAuth: true,
    roles: ['authority', 'admin'],
  },
  {
    path: 'level1',
    name: 'Level 1 - Routine Violations',
    // component: Level1Dashboard,
    // layout: AuthorityLayout,
    requiresAuth: true,
    roles: ['authority', 'admin'],
  },
  {
    path: 'violations/:violationId',
    name: 'Violation Detail',
    // component: ViolationDetailPage,
    // layout: AuthorityLayout,
    requiresAuth: true,
    roles: ['authority', 'admin'],
  },
  {
    path: 'fines',
    name: 'Fine Management',
    // component: FineManagement,
    // layout: AuthorityLayout,
    requiresAuth: true,
    roles: ['authority', 'admin'],
  },
  {
    path: 'live',
    name: 'Live Monitoring',
    // component: LiveMonitoring,
    // layout: AuthorityLayout,
    requiresAuth: true,
    roles: ['authority', 'admin'],
  },
  {
    path: 'junctions',
    name: 'Junction Management',
    // component: JunctionManagement,
    // layout: AuthorityLayout,
    requiresAuth: true,
    roles: ['authority', 'admin'],
  },
  {
    path: 'cameras',
    name: 'Camera Management',
    // component: CameraManagement,
    // layout: AuthorityLayout,
    requiresAuth: true,
    roles: ['authority', 'admin'],
  },
  {
    path: 'incidents',
    name: 'Level 2 - Incidents',
    // component: IncidentDashboard,
    // layout: AuthorityLayout,
    requiresAuth: true,
    roles: ['authority', 'admin'],
  },
  {
    path: 'incidents/:incidentId',
    name: 'Incident Detail',
    // component: IncidentDetailPage,
    // layout: AuthorityLayout,
    requiresAuth: true,
    roles: ['authority', 'admin'],
  },
  {
    path: 'vehicles',
    name: 'Vehicle Search',
    // component: VehicleSearch,
    // layout: AuthorityLayout,
    requiresAuth: true,
    roles: ['authority', 'admin'],
  },
  {
    path: 'vehicles/:vehicleId',
    name: 'Vehicle Profile',
    // component: VehicleProfilePage,
    // layout: AuthorityLayout,
    requiresAuth: true,
    roles: ['authority', 'admin'],
  },
  {
    path: 'tracking',
    name: 'Vehicle Tracking',
    // component: TrackingDashboard,
    // layout: AuthorityLayout,
    requiresAuth: true,
    roles: ['authority', 'admin'],
  },
  {
    path: 'evidence',
    name: 'Evidence Management',
    // component: EvidenceManager,
    // layout: AuthorityLayout,
    requiresAuth: true,
    roles: ['authority', 'admin'],
  },
  {
    path: 'reports',
    name: 'Reports & Analytics',
    // component: ReportsPage,
    // layout: AuthorityLayout,
    requiresAuth: true,
    roles: ['authority', 'admin'],
  },
  {
    path: 'system',
    name: 'System Monitoring',
    // component: SystemSettings,
    // layout: AuthorityLayout,
    requiresAuth: true,
    roles: ['admin'],
  },
  {
    path: 'settings',
    name: 'Settings',
    // component: SystemAdminSettings,
    // layout: AuthorityLayout,
    requiresAuth: true,
    roles: ['admin'],
  },
]

/**
 * ERROR ROUTES
 */
export const errorRoutes: RouteConfig[] = [
  {
    path: '*',
    name: 'Not Found',
    // component: NotFound,
  },
]

/**
 * ROUTE CONFIGURATION SUMMARY
 *
 * Total Routes: 32 (per master specification)
 *
 * Public Routes (2):
 * - Home, About
 *
 * Citizen Routes (10):
 * - Login, Signup, Dashboard, Vehicles, Violations, ViolationDetail,
 *   Payments, PaymentDetail, Receipts, Notifications, Profile
 *
 * Authority Routes (20):
 * - Login, Signup, Dashboard, Level1, ViolationDetail, Fines, Live,
 *   Junctions, Cameras, Incidents, IncidentDetail, Vehicles, VehicleProfile,
 *   Tracking, Evidence, Reports, System, Settings
 *
 * The routing configuration uses React Router v6 with:
 * - Path-based routing
 * - Layout components for consistent UI
 * - Role-based access control via guards
 * - Nested routes for grouped functionality
 */

/**
 * Usage in App.tsx:
 *
 * ```typescript
 * import { BrowserRouter, Routes, Route } from 'react-router-dom'
 * import { publicRoutes, citizenRoutes, authorityRoutes } from '@routes/routes'
 * import ProtectedRoute from '@routes/ProtectedRoute'
 *
 * export default function App() {
 *   return (
 *     <BrowserRouter>
 *       <Routes>
 *         {publicRoutes.map((route) => (
 *           <Route key={route.path} path={route.path} element={route.component} />
 *         ))}
 *
 *         <Route path="/citizen/*">
 *           {citizenRoutes.map((route) => (
 *             <Route
 *               key={route.path}
 *               path={route.path}
 *               element={
 *                 <ProtectedRoute roles={route.roles}>
 *                   {route.component}
 *                 </ProtectedRoute>
 *               }
 *             />
 *           ))}
 *         </Route>
 *
 *         <Route path="/authority/*">
 *           {authorityRoutes.map((route) => (
 *             <Route
 *               key={route.path}
 *               path={route.path}
 *               element={
 *                 <ProtectedRoute roles={route.roles}>
 *                   {route.component}
 *                 </ProtectedRoute>
 *               }
 *             />
 *           ))}
 *         </Route>
 *       </Routes>
 *     </BrowserRouter>
 *   )
 * }
 * ```
 */
