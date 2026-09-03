import React from 'react'
import { useParams, Link } from 'react-router-dom'
import { Card, Badge, Button } from '@components/ui'

export const VehicleProfilePage: React.FC = () => {
  const { vehicleId } = useParams<{ vehicleId: string }>()

  const plate = vehicleId ? vehicleId.replace('VEH-', '') : 'KA03AB9012'

  const historyEvents = [
    {
      time: '2026-09-01 17:42:10',
      junction: 'Koramangala 80ft Signal (Mast North)',
      event: 'Optical ANPR & RFID Fused Crossing',
      speed: '66.8 km/h',
      status: 'RED_LIGHT_VIOLATION',
    },
    {
      time: '2026-09-01 17:35:12',
      junction: 'Sony World Junction East Mast',
      event: 'FASTag RFID Gantry Read (EPC-8871BC)',
      speed: '54.1 km/h',
      status: 'NORMAL',
    },
    {
      time: '2026-09-01 17:28:44',
      junction: '100ft Road Indiranagar Signal',
      event: 'ANPR Visual Sighting (CAM-J02-NW)',
      speed: '49.0 km/h',
      status: 'NORMAL',
    },
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-cyan-400">VEHICLE PROFILE & SENSOR TIMELINE</span>
            <Badge variant="danger" size="sm">
              SUSPECT IN INVESTIGATION
            </Badge>
          </div>
          <h2 className="text-xl font-bold font-mono text-white mt-1">{plate}</h2>
        </div>

        <div className="flex items-center gap-3">
          <Link to="/authority/vehicles">
            <Button variant="secondary" size="sm">
              ← Back to Search
            </Button>
          </Link>
          <Link to={`/authority/tracking`}>
            <Button variant="primary" size="sm">
              Cross-Junction Trajectory Map →
            </Button>
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card title="Vehicle Attributes & Identity" glow className="md:col-span-1">
          <div className="space-y-3 text-xs font-mono">
            <div className="p-2.5 bg-[#121820] rounded border border-slate-800">
              <span className="text-[10px] text-slate-500 uppercase block">Registration Plate</span>
              <span className="text-white font-bold text-sm">{plate}</span>
            </div>
            <div className="p-2.5 bg-[#121820] rounded border border-slate-800">
              <span className="text-[10px] text-slate-500 uppercase block">FASTag EPC Code</span>
              <span className="text-cyan-300 font-semibold">EPC-8871BC-{plate}</span>
            </div>
            <div className="p-2.5 bg-[#121820] rounded border border-slate-800">
              <span className="text-[10px] text-slate-500 uppercase block">Vehicle Class & Color</span>
              <span className="text-slate-200">Sedan · Dark Blue / Black</span>
            </div>
            <div className="p-2.5 bg-[#121820] rounded border border-slate-800">
              <span className="text-[10px] text-slate-500 uppercase block">Identity Confidence</span>
              <span className="text-emerald-400 font-bold">98.2% (Visual + RFID Match)</span>
            </div>
          </div>
        </Card>

        <Card title="Cross-Junction Sighting Timeline" glow className="md:col-span-2">
          <div className="space-y-4 text-xs font-mono">
            <div className="relative pl-6 space-y-6 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-800">
              {historyEvents.map((ev, idx) => (
                <div key={idx} className="relative">
                  <span
                    className={`absolute -left-6 top-1 w-2.5 h-2.5 rounded-full ${
                      ev.status !== 'NORMAL' ? 'bg-red-500 ring-4 ring-red-950' : 'bg-aghat-blue ring-4 ring-blue-950'
                    }`}
                  />
                  <div className="p-3 bg-[#121820] rounded border border-slate-800 space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-white font-semibold">{ev.junction}</span>
                      <span className="text-[10px] text-slate-400">{ev.time}</span>
                    </div>
                    <p className="text-slate-300">{ev.event}</p>
                    <div className="flex items-center gap-3 pt-1 text-[11px]">
                      <span className="text-cyan-300">Speed: {ev.speed}</span>
                      <span className={ev.status !== 'NORMAL' ? 'text-red-400 font-bold' : 'text-emerald-400'}>
                        {ev.status}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}
