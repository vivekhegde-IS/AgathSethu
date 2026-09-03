import React, { useState } from 'react'
import { Card, Badge, Select } from '@components/ui'

export const TrackingDashboard: React.FC = () => {
  const [selectedVehicle, setSelectedVehicle] = useState('KA03AB9012')

  const waypoints = [
    {
      seq: 1,
      junction: 'JUNC-INDIRA-100FT',
      name: 'Indiranagar 100ft Gantry',
      time: '17:28:44',
      sensors: ['Optical ANPR CAM-J02-NW'],
      speed: '49 km/h',
      status: 'NORMAL',
    },
    {
      seq: 2,
      junction: 'JUNC-SONY-WORLD',
      name: 'Sony World Signal East',
      time: '17:35:12',
      sensors: ['FASTag RFID UHF Reader #2', 'Optical CAM-J01-E'],
      speed: '54 km/h',
      status: 'NORMAL',
    },
    {
      seq: 3,
      junction: 'JUNC-KORM-80FT',
      name: 'Koramangala 80ft Signal North',
      time: '17:42:10',
      sensors: ['CARLA IMU Telemetry', 'Optical ANPR CAM-J01-N', 'RFID Reader #1'],
      speed: '66.8 km/h',
      status: 'COLLISION_IMPACT_EVENT',
    },
  ]

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-cyan-400">MEMBER 3 EXTENDED KALMAN FUSION</span>
            <Badge variant="brand" size="sm" dot>
              TRAJECTORY RECONSTRUCTION
            </Badge>
          </div>
          <h2 className="text-xl font-bold font-mono text-white mt-1">
            Cross-Junction Multi-Sensor Tracking
          </h2>
        </div>

        <div className="flex items-center gap-3">
          <Select
            value={selectedVehicle}
            onChange={(e) => setSelectedVehicle(e.target.value)}
            options={[
              { value: 'KA03AB9012', label: 'KA03AB9012 (Collision Suspect)' },
              { value: 'KA04MN9912', label: 'KA04MN9912 (Commercial Truck)' },
              { value: 'KA01MJ4582', label: 'KA01MJ4582 (SUV Witness)' },
            ]}
            className="w-72"
          />
        </div>
      </div>

      {/* Trajectory Reconstruction Map Canvas */}
      <Card title="Horizontal Multi-Junction Vector Map" glow>
        <div className="space-y-6">
          <div className="relative h-48 bg-[#0a0e14] rounded-lg border border-slate-800 p-6 flex items-center justify-between overflow-x-auto">
            {/* Connecting corridor line */}
            <div className="absolute left-16 right-16 top-1/2 h-1 bg-gradient-to-r from-blue-600 via-cyan-500 to-red-600 -translate-y-1/2" />

            {waypoints.map((wp) => (
              <div key={wp.seq} className="relative z-10 flex flex-col items-center text-center">
                <div
                  className={`w-10 h-10 rounded-full border-2 flex items-center justify-center font-mono font-bold text-xs shadow-glow ${
                    wp.status === 'COLLISION_IMPACT_EVENT'
                      ? 'bg-red-950 border-red-500 text-red-300 ring-4 ring-red-900/50 animate-pulse'
                      : 'bg-blue-950 border-cyan-400 text-cyan-300 ring-4 ring-blue-900/30'
                  }`}
                >
                  J{wp.seq}
                </div>
                <span className="font-mono text-xs font-semibold text-white mt-2 block">{wp.name}</span>
                <span className="text-[10px] font-mono text-slate-400 block">{wp.time}</span>
                <Badge
                  variant={wp.status === 'COLLISION_IMPACT_EVENT' ? 'danger' : 'info'}
                  size="sm"
                  className="mt-1"
                >
                  {wp.speed}
                </Badge>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs font-mono">
            {waypoints.map((wp) => (
              <div key={wp.seq} className="p-3 bg-[#121820] rounded border border-slate-800 space-y-1">
                <div className="flex justify-between items-center">
                  <span className="text-white font-semibold">Waypoint #{wp.seq}: {wp.name}</span>
                  <span className="text-[10px] text-cyan-400">{wp.time}</span>
                </div>
                <p className="text-slate-400 text-[11px]">Recorded Speed: {wp.speed}</p>
                <div className="text-[10px] text-slate-500 space-y-0.5 pt-1">
                  {wp.sensors.map((s, idx) => (
                    <div key={idx}>✓ {s}</div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </Card>
    </div>
  )
}
