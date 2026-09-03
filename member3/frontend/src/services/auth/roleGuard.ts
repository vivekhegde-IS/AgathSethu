/**
 * Role-Based Access Control Guard
 * 
 * Provides utilities for checking user roles and protecting routes
 */

/**
 * User Role Type
 */
export type UserRole = 'citizen' | 'authority' | 'admin'

/**
 * Check if user has required role
 * @param userRole Current user's role
 * @param requiredRoles Array of allowed roles
 * @returns true if user has at least one required role
 */
export function hasRequiredRole(userRole: UserRole, requiredRoles?: UserRole[]): boolean {
  if (!requiredRoles || requiredRoles.length === 0) {
    return true
  }
  return requiredRoles.includes(userRole)
}

/**
 * Get role display name
 */
export function getRoleDisplayName(role: UserRole): string {
  const roleNames: Record<UserRole, string> = {
    citizen: 'Citizen',
    authority: 'Traffic Authority',
    admin: 'System Administrator',
  }
  return roleNames[role]
}

/**
 * Check if role has administrative privileges
 */
export function isAdmin(role: UserRole): boolean {
  return role === 'admin'
}

/**
 * Check if role has authority privileges (authority or admin)
 */
export function isAuthority(role: UserRole): boolean {
  return role === 'authority' || role === 'admin'
}

/**
 * Get accessible routes for a role
 */
export function getAccessibleRoutes(role: UserRole): string[] {
  const routes: Record<UserRole, string[]> = {
    citizen: [
      '/citizen/dashboard',
      '/citizen/vehicles',
      '/citizen/violations',
      '/citizen/payments',
      '/citizen/receipts',
      '/citizen/notifications',
      '/citizen/profile',
    ],
    authority: [
      '/authority/dashboard',
      '/authority/level1',
      '/authority/fines',
      '/authority/live',
      '/authority/junctions',
      '/authority/cameras',
      '/authority/incidents',
      '/authority/vehicles',
      '/authority/tracking',
      '/authority/evidence',
      '/authority/reports',
    ],
    admin: [
      // All authority routes
      '/authority/dashboard',
      '/authority/level1',
      '/authority/fines',
      '/authority/live',
      '/authority/junctions',
      '/authority/cameras',
      '/authority/incidents',
      '/authority/vehicles',
      '/authority/tracking',
      '/authority/evidence',
      '/authority/reports',
      // Plus admin-specific routes
      '/authority/system',
      '/authority/settings',
    ],
  }
  return routes[role]
}
