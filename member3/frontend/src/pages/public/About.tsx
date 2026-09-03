import React from 'react'
import { Card, Badge, Button } from '@components/ui'
import { Link } from 'react-router-dom'

export const About: React.FC = () => {
  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12 space-y-12">
      {/* Title */}
      <div className="text-center max-w-3xl mx-auto space-y-3">
        <Badge variant="brand" size="md">
          TECHNICAL ARCHITECTURE SPECIFICATION
        </Badge>
        <h1 className="text-3xl sm:text-4xl font-bold font-mono text-white uppercase tracking-wider">
          About AGHAT SETHU
        </h1>
        <p className="text-sm text-slate-300">
          An AI-powered multi-sensor urban traffic surveillance, automated enforcement, and crash investigation system.
        </p>
      </div>

      {/* Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <Card title="Problem Statement & Mission" glow>
          <div className="space-y-4 text-xs sm:text-sm text-slate-300 leading-relaxed">
            <p>
              Urban road junctions experience high violation rates, delayed emergency response during collisions, and
              hit-and-run incidents where offender identification is hindered by occluded license plates or weather conditions.
            </p>
            <p>
              <strong className="text-white">AGHAT SETHU</strong> bridges this gap by combining visual surveillance with
              RFID tag data (FASTag / vehicle transponders) to achieve redundant, tamper-resistant vehicle identity verification,
              instantaneous crash impact alerting, and cross-junction suspect trajectory reconstruction.
            </p>
          </div>
        </Card>

        <Card title="System Architecture & Isolation" glow>
          <div className="space-y-3 text-xs sm:text-sm text-slate-300">
            <p>
              The platform is architected around the strict <strong className="text-cyan-400">Adapter Pattern</strong> to
              isolate team modules:
            </p>
            <ul className="space-y-2 list-disc list-inside font-mono text-xs text-slate-400">
              <li>
                <strong className="text-slate-200">Member 1 (CARLA & Sensors):</strong> Generates 3D simulation telemetry,
                camera views, and IMU data feeds.
              </li>
              <li>
                <strong className="text-slate-200">Member 2 (Computer Vision):</strong> Bounding-box detection, ANPR license
                plate reading, and Level-1 traffic violation inference.
              </li>
              <li>
                <strong className="text-slate-200">Member 3 (Sensor Fusion):</strong> Multi-sensor Kalman filter combining
                ANPR with RFID readings for trajectory tracking & anomaly detection.
              </li>
            </ul>
          </div>
        </Card>
      </div>

      {/* Call to action */}
      <div className="text-center pt-6">
        <Link to="/authority/dashboard">
          <Button variant="primary" size="lg">
            Access Tactical Command Center (TOC)
          </Button>
        </Link>
      </div>
    </div>
  )
}
