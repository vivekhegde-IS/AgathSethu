/**
 * AGHAT SETHU — Root Application Component
 * Wires all routes to their page components using React Router v6 layout pattern.
 */

import { useEffect } from 'react'
import { BrowserRouter as Router, Routes, Route, Navigate, useParams } from 'react-router-dom'

// ─── Auth Store ────────────────────────────────────────────────────────────────
import { useAuthStore } from '@stores/authStore'

// ─── Public Pages ────────────────────────────────────────────────────────────────
import { Home } from '@pages/public/Home'
import { InfoPage } from '@pages/public/InfoPage'

// ─── Layouts ─────────────────────────────────────────────────────────────────────
import { OfficialLayout } from '@components/layout/OfficialLayout'
import { CitizenLayout } from '@components/layout/CitizenLayout'
import { AuthorityLayout } from '@components/layout/AuthorityLayout'
import { ProtectedRoute } from '@components/auth/ProtectedRoute'

// ─── Citizen Pages ────────────────────────────────────────────────────────────────
import { CitizenLogin } from '@pages/citizen/Login'
import { CitizenSignup } from '@pages/citizen/Signup'
import { CitizenDashboard } from '@pages/citizen/Dashboard'
import { CitizenVehicles } from '@pages/citizen/Vehicles'
import { CitizenViolations } from '@pages/citizen/Violations'
import { CitizenIncidentReport } from '@pages/citizen/IncidentReport'
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
import { PartialPlatesPage } from '@pages/authority/PartialPlates'
import { LiveMonitoring } from '@pages/authority/Live'
import { IncidentDashboard } from '@pages/authority/Incidents'
import { VehicleSearch } from '@pages/authority/Vehicles'
import { VehicleProfilePage } from '@pages/authority/VehicleProfile'
import { TrackingDashboard } from '@pages/authority/Tracking'
import { EvidenceManager } from '@pages/authority/Evidence'
import { IncidentEvidencePage } from '@pages/authority/IncidentEvidence'

/** Old incident links (/authority/incident-evidence/:id) open the detail page. */
function LegacyIncidentRedirect() {
  const { incidentId } = useParams<{ incidentId: string }>()
  return <Navigate to={incidentId ? `/authority/evidence/${incidentId}` : '/authority/evidence'} replace />
}

/**
 * AuthInitializer
 *
 * Calls initializeAuth() once on app startup.
 * Checks localStorage for a JWT and validates it against the backend
 * /auth/me endpoint before any ProtectedRoute decisions are made.
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
          <Route element={<OfficialLayout />}>
            <Route path="/" element={<Home />} />
            <Route path="/citizen/login" element={<CitizenLogin />} />
            <Route path="/citizen/signup" element={<CitizenSignup />} />
            <Route path="/authority/login" element={<AuthorityLogin />} />
            <Route path="/authority/signup" element={<AuthoritySignup />} />
            <Route path="/privacy" element={<InfoPage page="privacy" />} />
            <Route path="/terms" element={<InfoPage page="terms" />} />
            <Route path="/accessibility" element={<InfoPage page="accessibility" />} />
            <Route path="/help" element={<InfoPage page="help" />} />
          </Route>

          {/* ── CITIZEN PORTAL ── */}
          {/* Protected like the authority TOC: the dashboard shows the logged-in
              citizen's real fines, so it needs a real citizen session. */}
          <Route
            path="/citizen"
            element={
              <ProtectedRoute roles={['citizen']}>
                <CitizenLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="/citizen/dashboard" replace />} />
            <Route path="dashboard" element={<CitizenDashboard />} />
            <Route path="vehicles" element={<CitizenVehicles />} />
            <Route path="violations" element={<CitizenViolations />} />
            <Route path="incidents/:incidentId" element={<CitizenIncidentReport />} />
            <Route path="payments" element={<CitizenPayments />} />
            <Route path="payments/:paymentId" element={<CitizenPaymentDetail />} />
            <Route path="receipts" element={<CitizenReceipts />} />
            <Route path="notifications" element={<CitizenNotifications />} />
            <Route path="profile" element={<CitizenProfile />} />
          </Route>


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
            <Route path="partial-plates" element={<PartialPlatesPage />} />
            <Route path="live" element={<LiveMonitoring />} />
            <Route path="incidents" element={<IncidentDashboard />} />
            <Route path="vehicles" element={<VehicleSearch />} />
            <Route path="vehicles/:vehicleId" element={<VehicleProfilePage />} />
            <Route path="tracking" element={<TrackingDashboard />} />
            <Route path="evidence" element={<EvidenceManager />} />
            <Route path="evidence/:evidenceId" element={<IncidentEvidencePage />} />
            <Route path="incident-evidence" element={<LegacyIncidentRedirect />} />
            <Route path="incident-evidence/:incidentId" element={<LegacyIncidentRedirect />} />
          </Route>

          {/* ── CATCH-ALL ── */}
          <Route path="*" element={<Navigate to="/" replace />} />

        </Routes>
      </AuthInitializer>
    </Router>
  )
}
