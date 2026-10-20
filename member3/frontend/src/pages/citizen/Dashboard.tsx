import React from 'react'
import { Link } from 'react-router-dom'
import { useAuthStore } from '@stores/authStore'
import { Card, MetricCard, Badge, Button, Spinner } from '@components/ui'
import { FinesTable, rupees, useMyFines } from '@components/citizen/FinesTable'

export const CitizenDashboard: React.FC = () => {
  const { user } = useAuthStore()
  // Real data only: vehicles and fines of the logged-in citizen from the backend.
  const { data, error, reload } = useMyFines()

  const vehicles = data?.vehicles ?? []
  const fines = data?.fines ?? []

  return (
    <div className="space-y-6">
      {/* Welcome Banner */}
      <div className="p-6 rounded-lg bg-gradient-to-r from-white to-blue-50 border border-slate-200 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <span className="text-xs font-mono text-blue-800 uppercase tracking-widest">CITIZEN PORTAL</span>
          <h2 className="text-2xl font-bold font-mono text-slate-900 mt-1">Welcome back, {user?.name}</h2>
          <p className="text-sm text-slate-600 mt-1">
            Registered Vehicles: {vehicles.map((v) => v.plate_number).join(', ') || '—'}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="secondary" size="sm" onClick={reload}>
            Refresh
          </Button>
          {data && data.unpaid_count > 0 && (
            <Link to="/citizen/payments">
              <Button variant="danger" size="sm">
                Pay unpaid fines ({rupees(data.total_unpaid)})
              </Button>
            </Link>
          )}
        </div>
      </div>

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded">{error}</div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard label="Registered Vehicles" value={data ? vehicles.length : '…'} status="normal" />
        <MetricCard
          label="Unpaid Fines"
          value={data ? data.unpaid_count : '…'}
          status={data && data.unpaid_count > 0 ? 'warning' : 'success'}
        />
        <MetricCard
          label="Total Unpaid"
          value={data ? rupees(data.total_unpaid) : '…'}
          status={data && data.total_unpaid > 0 ? 'critical' : 'success'}
        />
        <MetricCard label="Fines Issued" value={data ? fines.length : '…'} status="normal" />
      </div>

      {/* Registered vehicles (from the vehicles table) */}
      <Card title="My Registered Vehicles">
        {!data ? (
          <Spinner />
        ) : vehicles.length === 0 ? (
          <p className="text-sm text-slate-600">No vehicles are registered to your account.</p>
        ) : (
          <div className="flex flex-wrap gap-3">
            {vehicles.map((veh) => (
              <div key={veh.id} className="p-3 bg-slate-50 rounded border border-slate-200 flex items-center gap-3">
                <span className="font-mono font-bold text-slate-900 text-sm">{veh.plate_number}</span>
                {veh.vehicle_type && <Badge variant="info" size="sm">{veh.vehicle_type}</Badge>}
                <span
                  className={`text-xs font-mono font-semibold ${
                    veh.unpaid_count > 0 ? 'text-amber-700' : 'text-emerald-700'
                  }`}
                >
                  {veh.unpaid_count > 0 ? `${veh.unpaid_count} Unpaid` : 'No unpaid fines'}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Fines (newest first) with the frames captured from the uploaded video */}
      <Card title="My Violations / Fines">{!data && !error ? <Spinner /> : <FinesTable fines={fines} />}</Card>
    </div>
  )
}
