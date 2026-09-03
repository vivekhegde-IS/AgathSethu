import React from 'react'
import { Link } from 'react-router-dom'

export const Footer: React.FC = () => {
  return (
    <footer className="border-t border-slate-800/80 bg-aghat-navy/95 text-slate-400 py-10 mt-auto">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 grid grid-cols-1 md:grid-cols-4 gap-8">
        <div className="space-y-3 md:col-span-2">
          <div className="flex items-center gap-2">
            <span className="font-mono font-bold text-white tracking-widest uppercase text-sm">AGHAT SETHU</span>
            <span className="text-xs px-2 py-0.5 rounded bg-blue-950 text-cyan-300 font-mono border border-blue-800">
              MEMBER 1 · 2 · 3 FUSED
            </span>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed max-w-md">
            Next-generation autonomous urban traffic safety intelligence system. Fusing CARLA physics simulation,
            deep computer vision ANPR pipelines, and FASTag RFID multi-sensor Kalman localization for instantaneous crash
            reconstruction and automated violation enforcement.
          </p>
          <div className="pt-2 text-[11px] font-mono text-slate-500">
            SECURED ACCORDING TO TRAFFIC ENFORCEMENT STANDARD IS-1249 / MoRTH
          </div>
        </div>

        <div>
          <h4 className="text-xs font-mono font-semibold text-white uppercase tracking-wider mb-3">Citizen Services</h4>
          <ul className="space-y-2 text-xs font-mono">
            <li><Link to="/citizen/login" className="hover:text-cyan-400 transition-colors">Check Vehicle Challans</Link></li>
            <li><Link to="/citizen/vehicles" className="hover:text-cyan-400 transition-colors">Registered FASTag Tracking</Link></li>
            <li><Link to="/citizen/payments" className="hover:text-cyan-400 transition-colors">Instant Fine Settlement</Link></li>
            <li><Link to="/citizen/receipts" className="hover:text-cyan-400 transition-colors">Digital Payment Receipts</Link></li>
          </ul>
        </div>

        <div>
          <h4 className="text-xs font-mono font-semibold text-white uppercase tracking-wider mb-3">Operations TOC</h4>
          <ul className="space-y-2 text-xs font-mono">
            <li><Link to="/authority/live" className="hover:text-cyan-400 transition-colors">Multi-Camera Live Grid</Link></li>
            <li><Link to="/authority/incidents" className="hover:text-cyan-400 transition-colors">Crash Investigation Radar</Link></li>
            <li><Link to="/authority/tracking" className="hover:text-cyan-400 transition-colors">Cross-Junction Trajectories</Link></li>
            <li><Link to="/authority/system" className="hover:text-cyan-400 transition-colors">System Health Monitor</Link></li>
          </ul>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-8 mt-8 border-t border-slate-800/60 flex flex-col sm:flex-row items-center justify-between text-xs text-slate-500 font-mono">
        <p>© 2026 AGHAT SETHU Intelligent Traffic Safety Platform. All rights reserved.</p>
        <p className="mt-2 sm:mt-0">Command Center Node: BLR-CENTRAL-01</p>
      </div>
    </footer>
  )
}
