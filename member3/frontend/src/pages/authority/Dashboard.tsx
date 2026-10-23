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
          title="Helmet violations per day"
          subtitle={`Last ${violations.by_day.length} days (IST)`}
          className="lg:col-span-1"
          actions={
            <Link to="/authority/fines">
              <Button variant="ghost" size="sm">
                Fines →
              </Button>
            </Link>
          }
        >
          <ViolationsByDay days={violations.by_day} />
        </Card>
      </div>
    </div>
  )
}


const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-10-23" -> "23 Oct" (the date is already an IST day; no timezone shift). */
const dayLabel = (date: string) => {
  const [, month, day] = date.split('-').map(Number)
  return `${day} ${MONTHS[month - 1]}`
}

/** One bar per IST day; the count sits above each bar. */
const ViolationsByDay: React.FC<{ days: AuthoritySummary['violations']['by_day'] }> = ({ days }) => {
  const total = days.reduce((sum, d) => sum + d.count, 0)
  if (total === 0) {
    return <p className="text-sm text-slate-600 py-6 text-center">No helmet violations in this period.</p>
  }
  const peak = Math.max(...days.map((d) => d.count))
  return (
    <div className="space-y-2">
      <p className="text-xs font-mono text-slate-600">
        <span className="font-bold text-slate-900">{total}</span> helmet violation{total === 1 ? '' : 's'}
      </p>
      <div className="flex items-end gap-1 h-36" role="img" aria-label="Helmet violations per day">
        {days.map((d) => (
          <div
            key={d.date}
            className="flex-1 min-w-0 h-full flex flex-col justify-end items-center"
            title={`${dayLabel(d.date)}: ${d.count}`}
          >
            {d.count > 0 && <span className="text-[10px] font-mono text-slate-900">{d.count}</span>}
            <div
              className={`w-full rounded-t ${d.count > 0 ? 'bg-cyan-500' : 'bg-slate-200'}`}
              style={{ height: d.count > 0 ? `${(d.count / peak) * 80}%` : '2px' }}
            />
          </div>
        ))}
      </div>
      <div className="flex gap-1 text-[9px] font-mono text-slate-500">
        {days.map((d, i) => (
          <span key={d.date} className="flex-1 min-w-0 text-center truncate">
            {i % 2 === days.length % 2 ? '' : dayLabel(d.date).split(' ')[0]}
          </span>
        ))}
      </div>
      <p className="text-[10px] font-mono text-slate-500 text-center">
        {dayLabel(days[0].date)} – {dayLabel(days[days.length - 1].date)}
      </p>
    </div>
  )
}
