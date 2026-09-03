import React, { useState, useEffect } from 'react'
import { useCameraStore } from '@stores/cameraStore'
import { Card, Badge, StatusIndicator, Select } from '@components/ui'

export const LiveMonitoring: React.FC = () => {
  const { junctions, selectedJunctionId, selectJunction, fetchCameras } = useCameraStore()
  const [selectedLayout, setSelectedLayout] = useState<'4' | '6' | '1'>('4')

  useEffect(() => {
    fetchCameras()
  }, [fetchCameras])

  const currentJunction =
    junctions.find((j) => j.junctionId === selectedJunctionId) || junctions[0]

  const mockFeeds = [
    { id: 'CAM-01', name: 'North Gantry (Town04 Entry)', fps: 30, bitrate: '4.2 Mbps' },
    { id: 'CAM-02', name: 'South Mast (Town04 Exit)', fps: 30, bitrate: '4.1 Mbps' },
    { id: 'CAM-03', name: 'Eastbound High-Speed Corridor', fps: 60, bitrate: '8.4 Mbps' },
    { id: 'CAM-04', name: 'Westbound Left-Turn Approach', fps: 30, bitrate: '3.9 Mbps' },
  ]

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-cyan-400 uppercase">TACTICAL MULTI-FEED RADAR</span>
            <Badge variant="brand" size="sm" dot>
              STREAM LIVE
            </Badge>
          </div>
          <h2 className="text-xl font-bold font-mono text-white mt-1">Live Junction & Camera Surveillance</h2>
        </div>

        <div className="flex items-center gap-3">
          <Select
            value={selectedJunctionId}
            onChange={(e) => selectJunction(e.target.value)}
            options={junctions.map((j) => ({ value: j.junctionId, label: j.name }))}
            className="w-72"
          />

          <div className="flex border border-slate-700 rounded overflow-hidden">
            {(['4', '6', '1'] as const).map((l) => (
              <button
                key={l}
                onClick={() => setSelectedLayout(l)}
                className={`px-3 py-1.5 text-xs font-mono transition-colors ${
                  selectedLayout === l
                    ? 'bg-aghat-blue text-white font-bold'
                    : 'bg-[#121820] text-slate-400 hover:text-white'
                }`}
              >
                {l} Grid
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Camera Video Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {mockFeeds.map((feed) => (
          <Card key={feed.id} className="p-2 relative bg-black border border-slate-800" glow>
            <div className="relative aspect-video rounded overflow-hidden bg-black flex items-center justify-center">
              <img
                src="https://images.unsplash.com/photo-1549317661-bd32c8ce0db2?auto=format&fit=crop&w=800&q=80"
                alt={feed.name}
                className="w-full h-full object-cover"
              />
              {/* Telemetry Overlays */}
              <div className="absolute top-2 left-2 bg-black/80 backdrop-blur-sm px-2 py-0.5 rounded text-[10px] font-mono text-cyan-400 border border-cyan-500/40">
                {feed.id} · {feed.name}
              </div>
              <div className="absolute top-2 right-2 bg-black/80 backdrop-blur-sm px-2 py-0.5 rounded text-[10px] font-mono text-emerald-400">
                {feed.fps} FPS · {feed.bitrate}
              </div>
              <div className="absolute bottom-2 left-2">
                <StatusIndicator status="active" label="CARLA SIM ENGINE" />
              </div>
            </div>
          </Card>
        ))}
      </div>

      {/* Junction Telemetry Bar */}
      <div className="p-4 bg-[#121820] rounded-lg border border-slate-800 flex flex-wrap items-center justify-between gap-4 text-xs font-mono">
        <div>
          <span className="text-slate-500 block">MONITORED CORRIDOR</span>
          <span className="text-white font-semibold">{currentJunction.corridor}</span>
        </div>
        <div>
          <span className="text-slate-500 block">THROUGHPUT VOLUME</span>
          <span className="text-cyan-400 font-bold">{currentJunction.throughputPerHour} veh/hr</span>
        </div>
        <div>
          <span className="text-slate-500 block">ANPR INFERENCE LATENCY</span>
          <span className="text-emerald-400 font-bold">14.2 ms / frame</span>
        </div>
        <div>
          <span className="text-slate-500 block">KALMAN FUSION STATE</span>
          <span className="text-cyan-300 font-bold">LOCKED & SYNCED</span>
        </div>
      </div>
    </div>
  )
}
