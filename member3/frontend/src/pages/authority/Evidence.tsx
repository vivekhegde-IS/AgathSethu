import React, { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Badge, Button, Card, Column, Select, Table } from '@components/ui'
import { CrashTypeBadge } from '@components/authority/CrashTypeBadge'
import { ResolveIncidentModal } from '@components/authority/ResolveIncidentModal'
import { BoardIncident, RecordsBoard, errorMessage, fetchRecords, formatIst, formatIstDate } from '@api/portal'

const PAGE_SIZE = 25

/** Today's date in IST as YYYY-MM-DD (the latest date that can be picked). */
const todayIst = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date())

/**
 * Evidence Records: every crash incident (one row per incident; the evidence
 * ID is the incident reference). Resolved incidents also live here after they
 * leave the radar.
 */
export const EvidenceManager: React.FC = () => {
  const navigate = useNavigate()
  const [status, setStatus] = useState<'all' | 'resolved' | 'unresolved'>('all')
  const [page, setPage] = useState(1)
  const [day, setDay] = useState('') // YYYY-MM-DD, '' = all dates
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('') // applied a moment after typing stops
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(searchInput.trim())
      setPage(1)
    }, 350)
    return () => window.clearTimeout(timer)
  }, [searchInput])
  const [data, setData] = useState<RecordsBoard | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [resolving, setResolving] = useState<BoardIncident | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setData(await fetchRecords(status, page, PAGE_SIZE, day, search))
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load evidence records.'))
    } finally {
      setLoading(false)
    }
  }, [status, page, day, search])

  useEffect(() => {
    load()
  }, [load])

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  const columns: Column<BoardIncident>[] = [
    {
      header: 'EVIDENCE ID',
      cell: (row) => <span className="font-mono font-semibold text-blue-800">{row.reference}</span>,
    },
    {
      header: 'VEHICLES INVOLVED',
      cell: (row) => {
        const plates = row.involved_plates_display.filter(Boolean) as string[]
        return (
          <div className="space-y-1">
            {plates.length ? (
              <span className="font-mono text-slate-900 text-xs">{plates.join(' · ')}</span>
            ) : (
              <span className="text-xs text-slate-500">Not identified</span>
            )}
            <div className="flex flex-wrap gap-1">
              <CrashTypeBadge kind={row} />
            </div>
          </div>
        )
      },
    },
    {
      header: 'DATE & TIME OF CRASH',
      cell: (row) => (
        <div>
          <span className="font-mono text-xs text-slate-800">{formatIst(row.created_at)}</span>
          <p className="text-[10px] text-slate-600 font-mono">{row.location}</p>
        </div>
      ),
    },
    {
      header: 'STATUS',
      cell: (row) => (
        <div>
          <Badge variant={row.resolved ? 'success' : 'danger'} size="sm">
            {row.resolved ? 'Resolved' : 'Unresolved'}
          </Badge>
          {row.resolved && (
            <p className="text-[10px] text-slate-600 font-mono mt-1">
              by {row.resolved_by_name ?? '—'}, {formatIst(row.resolved_at)}
            </p>
          )}
        </div>
      ),
    },
    {
      header: 'ACTION',
      className: 'text-right',
      cell: (row) => (
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => navigate(`/authority/evidence/${row.id}`)}>
            View incident
          </Button>
          {!row.resolved && (
            <Button variant="success" size="sm" onClick={() => setResolving(row)}>
              Mark as resolved
            </Button>
          )}
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold text-blue-950">Evidence Records</h2>
          <p className="text-sm text-slate-600">All recorded crash incidents and their resolution status.</p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor="records-search" className="block text-sm font-medium text-slate-800">
              Search
            </label>
            <input
              id="records-search"
              type="search"
              placeholder="Incident ID or number plate"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value.toUpperCase())}
              maxLength={40}
              className="mt-1.5 w-60 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-mono text-slate-900 placeholder:font-sans placeholder-slate-400 focus:border-blue-800 focus:outline-none focus:ring-1 focus:ring-blue-800"
            />
          </div>
          <div>
            <label htmlFor="records-date" className="block text-sm font-medium text-slate-800">
              Crash date
            </label>
            <div className="mt-1.5 flex items-center gap-2">
              <input
                id="records-date"
                type="date"
                value={day}
                max={todayIst()}
                onChange={(e) => {
                  setDay(e.target.value)
                  setPage(1)
                }}
                className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-blue-800 focus:outline-none focus:ring-1 focus:ring-blue-800"
              />
              {day && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setDay('')
                    setPage(1)
                  }}
                >
                  Clear
                </Button>
              )}
            </div>
          </div>
          <div className="w-48">
          <Select
            aria-label="Filter by status"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as typeof status)
              setPage(1)
            }}
            options={[
              { value: 'all', label: 'All incidents' },
              { value: 'unresolved', label: 'Unresolved' },
              { value: 'resolved', label: 'Resolved' },
            ]}
          />
          </div>
        </div>
      </div>

      {error && <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded">{error}</div>}

      <Card
        title={
          data
            ? `${search ? `Incidents matching ${search}` : 'Incidents'}${day ? ` on ${formatIstDate(`${day}T12:00:00+05:30`)}` : ''} (${data.total})`
            : 'Incidents'
        }
      >
        <Table
          columns={columns}
          data={data?.items ?? []}
          keyExtractor={(row) => row.id}
          isLoading={loading && !data}
          emptyMessage={
            search
              ? `No incidents match "${search}"${day ? ' on this date' : ''}.`
              : day
                ? 'No incidents on this date.'
                : 'No incidents recorded.'
          }
        />
        {data && data.total > PAGE_SIZE && (
          <div className="flex items-center justify-end gap-3 pt-3 text-xs font-mono text-slate-600">
            <Button variant="ghost" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
              ← Previous
            </Button>
            <span>
              Page {page} of {pages}
            </span>
            <Button variant="ghost" size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>
              Next →
            </Button>
          </div>
        )}
      </Card>

      <ResolveIncidentModal incident={resolving} onClose={() => setResolving(null)} onResolved={load} />
    </div>
  )
}
