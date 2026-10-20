import React, { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Button, Card, Spinner } from '@components/ui'
import {
  CitizenNotification,
  errorMessage,
  fetchNotifications,
  formatIst,
  markAllNotificationsRead,
  markNotificationRead,
} from '@api/portal'

const KIND_LABEL: Record<string, { label: string; variant: 'danger' | 'warning' | 'info' }> = {
  crash_involvement: { label: 'Crash', variant: 'danger' },
  fine_issued: { label: 'E-challan', variant: 'warning' },
}

/** Stored notifications (written when the event happened; only the read state changes here). */
export const CitizenNotifications: React.FC = () => {
  const [items, setItems] = useState<CitizenNotification[] | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setItems((await fetchNotifications()).notifications)
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load notifications.'))
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const markRead = async (n: CitizenNotification) => {
    if (n.read) return
    try {
      await markNotificationRead(n.id)
      setItems((prev) => prev?.map((x) => (x.id === n.id ? { ...x, read: true } : x)) ?? prev)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const markAll = async () => {
    try {
      await markAllNotificationsRead()
      await load()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const unread = items?.filter((n) => !n.read).length ?? 0

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold text-blue-950">Notifications</h2>
          <p className="text-sm text-slate-600">
            E-challans issued and crash incidents involving your registered vehicles.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={markAll} disabled={unread === 0}>
          Mark all read
        </Button>
      </div>

      {error && <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded">{error}</div>}

      {!items && !error ? (
        <Spinner />
      ) : items && items.length === 0 ? (
        <Card>
          <p className="p-6 text-center text-slate-600 font-mono text-xs">You have no notifications.</p>
        </Card>
      ) : (
        <ul className="space-y-3">
          {items?.map((n) => {
            const kind = KIND_LABEL[n.kind] ?? { label: n.kind, variant: 'info' as const }
            return (
              <li key={n.id}>
                <Card className={n.read ? '' : 'border-aghat-blue/60 bg-blue-50'}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="space-y-1 min-w-0">
                      <div className="flex items-center gap-2">
                        {!n.read && <span className="w-2 h-2 rounded-full bg-aghat-blue" aria-label="Unread" />}
                        <h3 className="text-sm font-semibold font-mono text-slate-900">{n.title}</h3>
                      </div>
                      <p className="text-xs text-slate-700">{n.message}</p>
                      <div className="flex flex-wrap items-center gap-3 pt-1">
                        <span className="text-[10px] font-mono text-slate-500">{formatIst(n.created_at)}</span>
                        {n.incident_id && (
                          <Link
                            to={`/citizen/incidents/${n.incident_id}`}
                            onClick={() => markRead(n)}
                            className="text-[11px] font-mono text-blue-800 hover:underline"
                          >
                            View incident report →
                          </Link>
                        )}
                        {n.fine_id != null && (
                          <Link
                            to={`/citizen/payments/${n.fine_id}`}
                            onClick={() => markRead(n)}
                            className="text-[11px] font-mono text-blue-800 hover:underline"
                          >
                            View challan →
                          </Link>
                        )}
                        {!n.read && (
                          <button
                            type="button"
                            onClick={() => markRead(n)}
                            className="text-[11px] font-mono text-slate-600 hover:text-blue-900"
                          >
                            Mark read
                          </button>
                        )}
                      </div>
                    </div>
                    <Badge variant={kind.variant} size="sm">
                      {kind.label}
                    </Badge>
                  </div>
                </Card>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
