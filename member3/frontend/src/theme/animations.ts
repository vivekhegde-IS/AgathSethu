/**
 * AGHAT SETHU Animation Tokens
 */

export const animations = {
  transition: {
    fast: '150ms cubic-bezier(0.4, 0, 0.2, 1)',
    normal: '200ms cubic-bezier(0.4, 0, 0.2, 1)',
    slow: '300ms cubic-bezier(0.4, 0, 0.2, 1)',
  },
  keyframes: {
    pulseSlow: 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
    radarSweep: 'radarSweep 4s linear infinite',
    blink: 'blink 1.5s ease-in-out infinite',
  },
} as const
