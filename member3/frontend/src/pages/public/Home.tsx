import React from 'react'
import { Link } from 'react-router-dom'
import { Button, Badge, MetricCard } from '@components/ui'

export const Home: React.FC = () => {
  return (
    <div className="w-full">
      {/* Hero Section */}
      <section className="relative overflow-hidden py-20 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
        <div className="text-center max-w-3xl mx-auto space-y-6">
          <div className="inline-flex items-center gap-2">
            <Badge variant="brand" size="md" dot>
              LIVE DEMO DEPLOYED
            </Badge>
            <span className="text-xs font-mono text-cyan-400">CARLA · CV/ANPR · FASTag RFID FUSION</span>
          </div>

          <h1 className="text-4xl sm:text-6xl font-extrabold tracking-tight text-white leading-tight font-sans">
            AI-Powered Traffic Safety &amp; Autonomous Incident Radar
          </h1>

          <p className="text-base sm:text-lg text-slate-300 max-w-2xl mx-auto leading-relaxed">
            AGHAT SETHU integrates high-fidelity CARLA simulation telemetry, deep learning computer vision, and
            multi-sensor RFID tracking into a unified tactical command center and citizen transparency platform.
          </p>

          <div className="flex flex-wrap items-center justify-center gap-4 pt-4">
            <Link to="/authority/dashboard">
              <Button variant="primary" size="lg" leftIcon={<span className="text-base">⚡</span>}>
                Launch Authority TOC
              </Button>
            </Link>
            <Link to="/citizen/login">
              <Button variant="outline" size="lg" leftIcon={<span className="text-base">👤</span>}>
                Citizen Challan Portal
              </Button>
            </Link>
          </div>
        </div>

        {/* Live Metrics Ribbon */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-16">
          <MetricCard
            label="Monitored Junctions"
            value="14 Active"
            subValue="Koramangala &amp; Indiranagar"
            status="normal"
            trend={{ direction: 'neutral', value: '100% Online', positive: true }}
          />
          <MetricCard
            label="Vision ANPR Accuracy"
            value="98.4%"
            subValue="Real-time Indian Plates"
            status="success"
            trend={{ direction: 'up', value: '+1.2%', positive: true }}
          />
          <MetricCard
            label="Sensor Fusion Latency"
            value="18 ms"
            subValue="Kalman Multi-Sensor Filter"
            status="normal"
            trend={{ direction: 'down', value: '-4ms lag', positive: true }}
          />
          <MetricCard
            label="Active Crash Detection"
            value="1 Critical"
            subValue="T-Bone Intersection Alert"
            status="critical"
            trend={{ direction: 'up', value: 'Auto-Dispatched', positive: false }}
          />
        </div>
      </section>
    </div>
  )
}
