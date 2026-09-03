/**
 * AGHAT SETHU Color Tokens
 * Command-center deep navy palette with high-contrast tactical accents
 */

export const colors = {
  // Backgrounds & Surface layers
  bg: {
    base: '#0a0e14', // Deepest background
    navy: '#0f1419', // Standard application navy
    surface: '#161d27', // Card & panel surface
    surfaceHover: '#1c2533', // Interactive hover state
    elevated: '#222d3d', // Modals & elevated dropdowns
    border: '#2a3649', // Standard border
    borderSubtle: '#1f2a38', // Subdued divider
  },

  // Brand Accents
  brand: {
    primary: '#2563eb', // AGHAT SETHU Electric Blue
    primaryLight: '#60a5fa', // Bright Blue highlight
    primaryDark: '#1d4ed8', // Deep interactive blue
    lavender: '#818cf8', // Secondary accent (radar/tracking)
    cyan: '#06b6d4', // Telemetry & ANPR accent
  },

  // Operational Status Indicators
  status: {
    success: '#10b981', // System normal / Fastag verified / paid fine
    successBg: 'rgba(16, 185, 129, 0.12)',
    warning: '#f59e0b', // Speed threshold warning / yellow light alert
    warningBg: 'rgba(245, 158, 11, 0.12)',
    danger: '#ef4444', // Red light violation / crash event / critical alert
    dangerBg: 'rgba(239, 68, 68, 0.12)',
    info: '#3b82f6', // General informational note
    infoBg: 'rgba(59, 130, 246, 0.12)',
    muted: '#64748b', // Offline / inactive state
  },

  // Severity tiers
  severity: {
    level1: '#3b82f6', // Routine traffic violation
    level2: '#f97316', // High-risk reckless driving / severe violation
    critical: '#dc2626', // Collision / Hit & Run incident
  },

  // Text colors
  text: {
    primary: '#f8fafc', // High contrast white
    secondary: '#94a3b8', // Technical blue-gray
    muted: '#64748b', // Subdued label text
    accent: '#38bdf8', // Interactive text highlight
    code: '#a5f3fc', // Monospace telemetry reading
  },
} as const

export type ColorPalette = typeof colors
