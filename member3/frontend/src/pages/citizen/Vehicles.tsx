import React from 'react'
import { Badge, Card, Spinner } from '@components/ui'
import { useMyFines } from '@components/citizen/FinesTable'

/** My Vehicles: the vehicles registered to this account (vehicles table), read-only. */
export const CitizenVehicles: React.FC = () => {
  const { data, error } = useMyFines()
  const vehicles = data?.vehicles ?? []

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-blue-950">My Vehicles</h2>
        <p className="text-sm text-slate-600">Vehicles registered to your account.</p>
      </div>

      {error && <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded">{error}</div>}

      <Card>
        {!data && !error ? (
          <Spinner />
        ) : vehicles.length === 0 ? (
          <p className="p-6 text-center text-slate-600 font-mono text-xs">No vehicles are registered to your account.</p>
        ) : (
          <ul className="divide-y divide-slate-200">
            {vehicles.map((v) => (
              <li key={v.id} className="py-3 flex items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span className="font-mono font-bold text-slate-900">{v.plate_number}</span>
                  {v.vehicle_type && (
                    <Badge variant="info" size="sm">
                      {v.vehicle_type}
                    </Badge>
                  )}
                </div>
                <span className={`text-xs font-mono ${v.unpaid_count > 0 ? 'text-amber-700' : 'text-emerald-700'}`}>
                  {v.unpaid_count > 0 ? `${v.unpaid_count} unpaid fine(s)` : 'No unpaid fines'}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
