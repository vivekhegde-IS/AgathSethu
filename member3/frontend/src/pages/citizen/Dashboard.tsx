import React from 'react'
import { Link } from 'react-router-dom'
import { useAuthStore } from '@stores/authStore'
import { useVehicleStore } from '@stores/vehicleStore'
import { useViolationStore } from '@stores/violationStore'
import { Card, MetricCard, Badge, Button } from '@components/ui'

export const CitizenDashboard: React.FC = () => {
  const { user } = useAuthStore()
  const { citizenVehicles } = useVehicleStore()
  const { violations } = useViolationStore()

  const pendingViolations = violations.filter((v) => v.status !== 'PAID')
  const totalDue = pendingViolations.reduce((acc, curr) => acc + curr.fineAmount, 0)

  return (
    <div className="space-y-6">
      {/* Welcome Banner */}
      <div className="p-6 rounded-lg bg-gradient-to-r from-aghat-navy-light to-blue-950/40 border border-slate-800 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-cyan-400 uppercase tracking-widest">CITIZEN PORTAL</span>
            <Badge variant="success" size="sm">
              FASTAG ACTIVE
            </Badge>
          </div>
          <h2 className="text-2xl font-bold font-mono text-white mt-1">Welcome back, {user?.name}</h2>
          <p className="text-xs text-slate-400 font-mono mt-1">
            Registered Vehicles: {citizenVehicles.length} · Live Enforcement Sync Active
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Link to="/citizen/violations">
            <Button variant="danger" size="sm">
              Pay Pending Fines (₹{totalDue})
            </Button>
          </Link>
          <Link to="/citizen/vehicles">
            <Button variant="secondary" size="sm">
              Manage Vehicles
            </Button>
          </Link>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Registered Vehicles"
          value={citizenVehicles.length}
          subValue="All FASTag Linked"
          status="normal"
        />
        <MetricCard
          label="Pending Challans"
          value={pendingViolations.length}
          subValue={`Total ₹${totalDue} Due`}
          status={pendingViolations.length > 0 ? 'warning' : 'success'}
        />
        <MetricCard
          label="Compliance Score"
          value="92 / 100"
          subValue="Tier 1 Safe Driver"
          status="success"
          trend={{ direction: 'up', value: '+4 pts', positive: true }}
        />
        <MetricCard
          label="Recent Detections"
          value="4 Junctions"
          subValue="Cross-junction pass logged"
          status="normal"
        />
      </div>

      {/* Two Column Layout: Vehicles & Pending Challans */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Vehicles Section */}
        <Card
          title="My Registered Vehicles"
          actions={
            <Link to="/citizen/vehicles">
              <Button variant="ghost" size="sm">
                View All →
              </Button>
            </Link>
          }
        >
          <div className="space-y-3">
            {citizenVehicles.map((veh) => (
              <div
                key={veh.vehicleId}
                className="p-3 bg-[#121820] rounded border border-slate-800 flex items-center justify-between"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-white text-sm">{veh.registrationNumber}</span>
                    <Badge variant="info" size="sm">
                      {veh.vehicleType}
                    </Badge>
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5">{veh.model}</p>
                  <p className="text-[10px] font-mono text-cyan-400 mt-1">FASTag ID: {veh.rfidTag}</p>
                </div>
                <div className="text-right">
                  <span
                    className={`text-xs font-mono font-semibold ${
                      veh.activeViolationsCount > 0 ? 'text-amber-400' : 'text-emerald-400'
                    }`}
                  >
                    {veh.activeViolationsCount > 0
                      ? `${veh.activeViolationsCount} Pending Challan`
                      : 'Clean Record'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Violations Section */}
        <Card
          title="Active e-Challans & Violations"
          actions={
            <Link to="/citizen/violations">
              <Button variant="ghost" size="sm">
                Full Records →
              </Button>
            </Link>
          }
        >
          {pendingViolations.length === 0 ? (
            <div className="p-8 text-center text-slate-400 font-mono text-xs">
              ✓ No pending violations on your registered vehicles.
            </div>
          ) : (
            <div className="space-y-3">
              {pendingViolations.map((v) => (
                <div
                  key={v.violation_id}
                  className="p-3 bg-[#161214] rounded border border-red-900/60 flex items-center justify-between"
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <Badge variant="danger" size="sm">
                        {v.violation_type}
                      </Badge>
                      <span className="font-mono text-xs font-semibold text-white">{v.license_plate}</span>
                    </div>
                    <p className="text-[11px] text-slate-400 mt-1">{v.location}</p>
                    <p className="text-[10px] font-mono text-slate-500">
                      {new Date(v.timestamp).toLocaleString()}
                    </p>
                  </div>
                  <div className="text-right space-y-1">
                    <p className="font-mono font-bold text-sm text-red-400">₹{v.fineAmount}</p>
                    <Link to={`/citizen/payments/${v.violation_id}`}>
                      <Button variant="danger" size="sm">
                        Pay Fine
                      </Button>
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
