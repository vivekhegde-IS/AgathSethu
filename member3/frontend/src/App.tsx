/**
 * AGHAT SETHU — Root Application Component
 * Wires all routes to their page components using React Router v6 layout pattern.
 */

import { useEffect } from 'react'
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'

// ─── Auth Store ────────────────────────────────────────────────────────────────
import { useAuthStore } from '@stores/authStore'

// ─── Public Pages ────────────────────────────────────────────────────────────────
import { Home } from '@pages/public/Home'
import { About } from '@pages/public/About'

// ─── Layouts ─────────────────────────────────────────────────────────────────────
import { PublicLayout } from '@components/layout/PublicLayout'
import { CitizenLayout } from '@components/layout/CitizenLayout'
import { AuthorityLayout } from '@components/layout/AuthorityLayout'
import { ProtectedRoute } from '@components/auth/ProtectedRoute'

// ─── Citizen Pages ────────────────────────────────────────────────────────────────
import { CitizenLogin } from '@pages/citizen/Login'
import { CitizenSignup } from '@pages/citizen/Signup'
import { CitizenDashboard } from '@pages/citizen/Dashboard'
import { CitizenVehicles } from '@pages/citizen/Vehicles'
import { CitizenViolations } from '@pages/citizen/Violations'
import { CitizenViolationDetail } from '@pages/citizen/ViolationDetail'
import { CitizenPayments } from '@pages/citizen/Payments'
import { CitizenPaymentDetail } from '@pages/citizen/PaymentDetail'
import { CitizenReceipts } from '@pages/citizen/Receipts'
import { CitizenNotifications } from '@pages/citizen/Notifications'
import { CitizenProfile } from '@pages/citizen/Profile'

// ─── Authority Pages ───────────────────────────────────────────────────────────
import { AuthorityLogin } from '@pages/authority/Login'
import { AuthoritySignup } from '@pages/authority/Signup'
import { AuthorityDashboard } from '@pages/authority/Dashboard'
import { Level1Dashboard } from '@pages/authority/Level1'
import { AuthorityViolationDetail } from '@pages/authority/ViolationDetail'
import { FineManagement } from '@pages/authority/Fines'
import { LiveMonitoring } from '@pages/authority/Live'
import { JunctionManagement } from '@pages/authority/Junctions'
import { CameraManagement } from '@pages/authority/Cameras'
import { IncidentDashboard } from '@pages/authority/Incidents'
import { IncidentDetailPage } from '@pages/authority/IncidentDetail'
import { VehicleSearch } from '@pages/authority/Vehicles'
import { VehicleProfilePage } from '@pages/authority/VehicleProfile'
import { TrackingDashboard } from '@pages/authority/Tracking'
import { EvidenceManager } from '@pages/authority/Evidence'
import { ReportsPage } from '@pages/authority/Reports'
import { SystemSettings } from '@pages/authority/System'
import { SystemAdminSettings } from '@pages/authority/Settings'

/**
 * AuthInitializer
 *
 * Calls initializeAuth() once on app startup.
 * In mock mode (VITE_ENABLE_REAL_AUTH=false) this is a no-op.
 * In real mode it checks localStorage for a JWT and validates it against
 * the backend /auth/me endpoint before any ProtectedRoute decisions are made.
 */
function AuthInitializer({ children }: { children: React.ReactNode }) {
  const initializeAuth = useAuthStore((s) => s.initializeAuth)

  useEffect(() => {
    initializeAuth()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return <>{children}</>
}

export default function App() {
  return (
    <Router>
      <AuthInitializer>
        <Routes>

          {/* ── PUBLIC ROUTES ── */}
          <Route element={<PublicLayout />}>
            <Route path="/" element={<Home />} />
            <Route path="/about" element={<About />} />
          </Route>

          {/* ── CITIZEN AUTH (no layout) ── */}
          <Route path="/citizen/login" element={<CitizenLogin />} />
          <Route path="/citizen/signup" element={<CitizenSignup />} />

          {/* ── CITIZEN PORTAL ── */}
          <Route path="/citizen" element={<CitizenLayout />}>
            <Route index element={<Navigate to="/citizen/dashboard" replace />} />
            <Route path="dashboard" element={<CitizenDashboard />} />
            <Route path="vehicles" element={<CitizenVehicles />} />
            <Route path="violations" element={<CitizenViolations />} />
            <Route path="violations/:violationId" element={<CitizenViolationDetail />} />
            <Route path="payments" element={<CitizenPayments />} />
            <Route path="payments/:paymentId" element={<CitizenPaymentDetail />} />
            <Route path="receipts" element={<CitizenReceipts />} />
            <Route path="notifications" element={<CitizenNotifications />} />
            <Route path="profile" element={<CitizenProfile />} />
          </Route>

          {/* ── AUTHORITY AUTH (no layout) ── */}
          <Route path="/authority/login" element={<AuthorityLogin />} />
          <Route path="/authority/signup" element={<AuthoritySignup />} />

          {/* ── AUTHORITY TACTICAL TOC ── */}
          <Route
            path="/authority"
            element={
              <ProtectedRoute roles={['authority', 'admin']}>
                <AuthorityLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="/authority/dashboard" replace />} />
            <Route path="dashboard" element={<AuthorityDashboard />} />
            <Route path="level1" element={<Level1Dashboard />} />
            <Route path="violations/:violationId" element={<AuthorityViolationDetail />} />
            <Route path="fines" element={<FineManagement />} />
            <Route path="live" element={<LiveMonitoring />} />
            <Route path="junctions" element={<JunctionManagement />} />
            <Route path="cameras" element={<CameraManagement />} />
            <Route path="incidents" element={<IncidentDashboard />} />
            <Route path="incidents/:incidentId" element={<IncidentDetailPage />} />
            <Route path="vehicles" element={<VehicleSearch />} />
            <Route path="vehicles/:vehicleId" element={<VehicleProfilePage />} />
            <Route path="tracking" element={<TrackingDashboard />} />
            <Route path="evidence" element={<EvidenceManager />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="system" element={<SystemSettings />} />
            <Route path="settings" element={<SystemAdminSettings />} />
          </Route>

          {/* ── CATCH-ALL ── */}
          <Route path="*" element={<Navigate to="/" replace />} />

        </Routes>
      </AuthInitializer>
    </Router>
  )
}
