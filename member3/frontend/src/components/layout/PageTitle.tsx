/**
 * Sets the browser tab title from the current route, so tabs and history
 * entries are distinguishable ("Live Camera Feeds · AGHAT SETHU").
 * The first matching pattern wins, so list specific paths before general ones.
 */

import { useEffect } from 'react'
import { matchPath, useLocation } from 'react-router-dom'

const APP_NAME = 'AGHAT SETHU'
const DEFAULT_TITLE = `${APP_NAME} - Traffic Safety & Incident Response`

const ROUTE_TITLES: Array<[string, string]> = [
  // Public
  ['/', DEFAULT_TITLE],
  ['/citizen/login', 'Citizen Login'],
  ['/citizen/signup', 'Citizen Registration'],
  ['/authority/login', 'Authority Login'],
  ['/authority/signup', 'Authority Registration'],
  ['/privacy', 'Privacy Policy'],
  ['/terms', 'Terms of Use'],
  ['/accessibility', 'Accessibility Statement'],
  ['/help', 'Help & Contact'],

  // Citizen portal
  ['/citizen/dashboard', 'Dashboard'],
  ['/citizen/vehicles', 'My Vehicles'],
  ['/citizen/violations', 'My Violations'],
  ['/citizen/incidents/:incidentId', 'Incident Report'],
  ['/citizen/payments/:paymentId', 'Payment Details'],
  ['/citizen/payments', 'Pay Fines'],
  ['/citizen/receipts', 'Payment History'],
  ['/citizen/notifications', 'Notifications'],
  ['/citizen/profile', 'Profile Settings'],

  // Authority portal
  ['/authority/dashboard', 'Overview'],
  ['/authority/level1', 'Routine Violations'],
  ['/authority/violations/:violationId', 'Violation Details'],
  ['/authority/fines', 'Fines & Revenue'],
  ['/authority/live', 'Live Camera Feeds'],
  ['/authority/incidents', 'Crash Incident Radar'],
  ['/authority/evidence/:evidenceId/tracking/:junctionId', 'Junction Tracking'],
  ['/authority/evidence/:evidenceId/tracking', 'Vehicle Tracking'],
  ['/authority/evidence/:evidenceId', 'Incident Evidence'],
  ['/authority/evidence', 'Evidence Records'],
]

export function titleForPath(pathname: string): string {
  for (const [pattern, title] of ROUTE_TITLES) {
    if (matchPath({ path: pattern, end: true }, pathname)) {
      return title === DEFAULT_TITLE ? title : `${title} · ${APP_NAME}`
    }
  }
  return `Page Not Found · ${APP_NAME}`
}

export function PageTitle() {
  const { pathname } = useLocation()

  useEffect(() => {
    document.title = titleForPath(pathname)
  }, [pathname])

  return null
}
