import React, { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AuthImage, Badge, Button, Card, MetricCard, Spinner } from '@components/ui'
import { AuthoritySummary, errorMessage, fetchSummary, formatIst, rupees } from '@api/portal'

const REFRESH_MS = 30000

/** Home after login: overall crashes, violations and fines, all from the backend. */
export const AuthorityDashboard: React.FC = () => {
  const [data, setData] = useState<AuthoritySummary | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setData(await fetchSummary())
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load the dashboard.'))
    }
  }, [])

  useEffect(() => {
    load()
    const timer = window.setInterval(load, REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [load])

  if (!data) {
    return error ? (
      <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded">{error}</div>
    ) : (
      <Spinner />
    )
  }

  const { crashes, violations, fines, latest_crash_frame: frame } = data

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-blue-950">Overview</h2>
        <p className="text-sm text-slate-600">Crashes, traffic violations and fines recorded by the system.</p>
      </div>

      {error && <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded">{error}</div>}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Crashes detected"
          value={crashes.total}
          subValue={`${crashes.today} today`}
          status={crashes.unresolved > 0 ? 'critical' : 'normal'}
        />
        <MetricCard
          label="Unresolved crashes"
          value={crashes.unresolved}
          subValue={`${crashes.resolved_today} resolved today`}
          status={crashes.unresolved > 0 ? 'warning' : 'success'}
        />
        <MetricCard
          label="Traffic violations detected"
          value={violations.total}
          subValue={`${violations.today} today`}
          status="normal"
        />
        <MetricCard
          label="Fines pending"
          value={rupees(fines.pending_amount)}
          subValue={`${fines.pending_count} unpaid · ${rupees(fines.collected_amount)} collected`}
          status={fines.pending_count > 0 ? 'warning' : 'normal'}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card
          title="Latest crash frame"
          className="lg:col-span-1"
          actions={
            frame && (
              <Link to={`/authority/evidence/${frame.incident_id}`}>
                <Button variant="ghost" size="sm">
                  Open →
                </Button>
              </Link>
            )
          }
        >
          {frame ? (
            <div className="space-y-2">
              <AuthImage
                src={frame.url}
                alt={`Camera frame of crash ${frame.reference}`}
                className="w-full aspect-video object-cover rounded border border-slate-300"
                fallback={<p className="text-xs text-slate-600">The evidence image is not available.</p>}
              />
              <p className="text-xs font-mono text-slate-700">
                {frame.reference} · {frame.location}
              </p>
              <p className="text-[11px] font-mono text-slate-500">Captured {formatIst(frame.captured_at)}</p>
            </div>
          ) : (
            <p className="text-sm text-slate-600 py-6 text-center">No crash evidence recorded yet.</p>
          )}
        </Card>

        <Card
          title="Recent crashes"
          className="lg:col-span-1"
          actions={
            <Link to="/authority/incidents">
              <Button variant="ghost" size="sm">
                Radar →
              </Button>
            </Link>
          }
        >
          {data.recent_incidents.length === 0 ? (
            <p className="text-sm text-slate-600 py-6 text-center">No crashes recorded.</p>
          ) : (
            <ul className="divide-y divide-slate-200">
              {data.recent_incidents.map((incident) => (
                <li key={incident.id} className="py-2 flex items-center justify-between gap-2">
                  <Link to={`/authority/evidence/${incident.id}`} className="min-w-0">
                    <p className="text-xs font-mono font-semibold text-blue-800 hover:underline">{incident.reference}</p>
                    <p className="text-[11px] font-mono text-slate-600 truncate">
                      {incident.location} · {formatIst(incident.created_at)}
                    </p>
                  </Link>
                  <Badge variant={incident.resolved ? 'success' : 'danger'} size="sm">
                    {incident.resolved ? 'Resolved' : 'Unresolved'}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card
          title="Violations by type"
          className="lg:col-span-1"
          actions={
            <Link to="/authority/fines">
              <Button variant="ghost" size="sm">
                Fines →
              </Button>
            </Link>
          }
        >
          {violations.by_type.length === 0 ? (
            <p className="text-sm text-slate-600 py-6 text-center">No violations recorded.</p>
          ) : (
            <ul className="space-y-3">
              {violations.by_type.map((row) => (
                <li key={row.violation_type} className="text-xs font-mono">
                  <div className="flex justify-between text-slate-700 pb-1">
                    <span>{row.violation_type}</span>
                    <span className="font-bold text-slate-900">{row.count}</span>
                  </div>
                  <div className="w-full bg-slate-200 h-1.5 rounded-full overflow-hidden" aria-hidden="true">
                    <div
                      className="bg-cyan-500 h-full"
                      style={{ width: `${(row.count / Math.max(1, violations.total)) * 100}%` }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}
