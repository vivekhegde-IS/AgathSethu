import React from 'react'
import { Link } from 'react-router-dom'
import { Card, Button, Spinner } from '@components/ui'
import { FinesTable, rupees, useMyFines } from '@components/citizen/FinesTable'

export const CitizenViolations: React.FC = () => {
  // Real fines of the logged-in citizen (same rows as the dashboard), newest first.
  const { data, error, reload } = useMyFines()

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold text-blue-950">Traffic e-Challan History</h2>
          <p className="text-sm text-slate-600">
            Violations detected by traffic-camera video analysis on your registered vehicles.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {data && data.unpaid_count > 0 && (
            <Link to="/citizen/payments">
              <Button variant="danger" size="sm">
                Pay unpaid fines ({rupees(data.total_unpaid)})
              </Button>
            </Link>
          )}
          <Button variant="secondary" size="sm" onClick={reload}>
            Refresh
          </Button>
        </div>
      </div>

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded">{error}</div>
      )}

      <Card>{!data && !error ? <Spinner /> : <FinesTable fines={data?.fines ?? []} />}</Card>
    </div>
  )
}
