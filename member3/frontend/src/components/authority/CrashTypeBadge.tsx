/**
 * Crash type, from Member 1's crash_alert status (NETRA v1.8) and escape
 * reports: two-car / multi-vehicle (chain) / single-vehicle, plus
 * hit-and-run (a car of a multi-vehicle crash left the scene) or "left the
 * scene" (a single-vehicle crash whose car drove off).
 */

import React from 'react'
import { Badge } from '@components/ui'

export interface CrashKind {
  crash_type?: 'two_car' | 'multi_vehicle' | 'single_vehicle' | 'unknown' | string
  crashed_vehicle_count?: number
  hit_and_run?: boolean
  left_scene_plates?: string[]
}

export const CrashTypeBadge: React.FC<{ kind: CrashKind }> = ({ kind }) => {
  const left = (kind.left_scene_plates ?? []).length > 0
  const type =
    kind.crash_type === 'two_car' ? <Badge variant="brand" size="sm">Two-car crash</Badge>
    : kind.crash_type === 'multi_vehicle' ? (
      <Badge variant="brand" size="sm">{kind.crashed_vehicle_count ?? 3}-car chain crash</Badge>
    )
    : kind.crash_type === 'single_vehicle' ? <Badge variant="info" size="sm">Single-vehicle crash</Badge>
    : null
  return (
    <>
      {type}
      {kind.hit_and_run ? (
        <Badge variant="danger" size="sm">Hit-and-run</Badge>
      ) : left && kind.crash_type === 'single_vehicle' ? (
        <Badge variant="warning" size="sm">Left the scene</Badge>
      ) : null}
    </>
  )
}
