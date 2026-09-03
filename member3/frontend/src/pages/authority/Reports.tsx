import React from 'react'
import { Card, MetricCard, Button } from '@components/ui'

export const ReportsPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold font-mono text-white">Traffic Analytics & Safety Reports</h2>
          <p className="text-xs text-slate-400 font-mono">
            Longitudinal safety KPIs, violation density maps, and crash probability trends.
          </p>
        </div>
        <Button variant="primary" size="sm" onClick={() => alert('Monthly Traffic Safety PDF generated.')}>
          Export PDF Report
        </Button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <MetricCard
          label="Total Violations Logged (30d)"
          value="1,842"
          subValue="-14% vs Previous Month"
          status="success"
          trend={{ direction: 'down', value: '14% drop', positive: true }}
        />
        <MetricCard
          label="Crash Incidence Rate"
          value="0.12 / 10k veh"
          subValue="Lowest in 6 Months"
          status="success"
          trend={{ direction: 'down', value: '0.04 drop', positive: true }}
        />
        <MetricCard
          label="Enforcement Resolution Time"
          value="4.2 hours"
          subValue="Target: < 24 hours"
          status="normal"
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card title="Violation Distribution by Category" glow>
          <div className="space-y-3 text-xs font-mono">
            <div>
              <div className="flex justify-between text-slate-300 pb-1">
                <span>Speeding (MV Act §183)</span>
                <span className="font-bold text-white">48% (884)</span>
              </div>
              <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                <div className="bg-amber-500 h-full w-[48%]" />
              </div>
            </div>

            <div>
              <div className="flex justify-between text-slate-300 pb-1">
                <span>Red Light Jumps (§184)</span>
                <span className="font-bold text-white">28% (516)</span>
              </div>
              <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                <div className="bg-red-500 h-full w-[28%]" />
              </div>
            </div>

            <div>
              <div className="flex justify-between text-slate-300 pb-1">
                <span>No Helmet / Seatbelt (§194D)</span>
                <span className="font-bold text-white">16% (295)</span>
              </div>
              <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                <div className="bg-cyan-500 h-full w-[16%]" />
              </div>
            </div>

            <div>
              <div className="flex justify-between text-slate-300 pb-1">
                <span>Wrong Lane / Rash Driving (§184)</span>
                <span className="font-bold text-white">8% (147)</span>
              </div>
              <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                <div className="bg-indigo-500 h-full w-[8%]" />
              </div>
            </div>
          </div>
        </Card>

        <Card title="High-Risk Hotspot Corridors" glow>
          <div className="space-y-3 text-xs font-mono">
            <div className="p-3 bg-[#121820] rounded border border-slate-800 flex justify-between items-center">
              <div>
                <p className="font-bold text-white">Koramangala 80ft Road 4-Way</p>
                <p className="text-[10px] text-slate-400">High speed on eastbound approach</p>
              </div>
              <span className="text-red-400 font-bold">Risk: HIGH (84/100)</span>
            </div>

            <div className="p-3 bg-[#121820] rounded border border-slate-800 flex justify-between items-center">
              <div>
                <p className="font-bold text-white">100ft Road Indiranagar 12th Main</p>
                <p className="text-[10px] text-slate-400">Lane weave during peak evening hours</p>
              </div>
              <span className="text-amber-400 font-bold">Risk: MED (58/100)</span>
            </div>

            <div className="p-3 bg-[#121820] rounded border border-slate-800 flex justify-between items-center">
              <div>
                <p className="font-bold text-white">Central Silk Board Flyover Entry</p>
                <p className="text-[10px] text-slate-400">Heavy mixed commercial traffic</p>
              </div>
              <span className="text-cyan-400 font-bold">Risk: LOW (32/100)</span>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}
