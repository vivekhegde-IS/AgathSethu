import React, { useCallback, useEffect, useState } from 'react'
import { Badge, Button, Card, Column, MetricCard, Select, Table } from '@components/ui'
import { FineRow, FinesRevenue, errorMessage, fetchFinesRevenue, formatIst, formatIstDate, rupees } from '@api/portal'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const PAGE_SIZE = 25

/** Today's date in IST as YYYY-MM-DD (the latest date that can be picked). */
const todayIst = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date())

/**
 * Fines & Revenue: every figure is summed from the stored fines and fine
 * payments (months and years in IST), so it survives refreshes and restarts.
 */
export const FineManagement: React.FC = () => {
  const [status, setStatus] = useState('all')
  const [page, setPage] = useState(1)
  const [day, setDay] = useState('') // YYYY-MM-DD issue date, '' = all dates
  const [plateInput, setPlateInput] = useState('')
  const [plate, setPlate] = useState('') // applied a moment after typing stops
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setPlate(plateInput.trim())
      setPage(1)
    }, 350)
    return () => window.clearTimeout(timer)
  }, [plateInput])
  const [year, setYear] = useState<number | undefined>(undefined)
  const [data, setData] = useState<FinesRevenue | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setData(await fetchFinesRevenue(status, page, year, day, plate))
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Could not load fines.'))
    }
  }, [status, page, year, day, plate])

  useEffect(() => {
    load()
  }, [load])

  const columns: Column<FineRow>[] = [
    { header: 'CHALLAN #', cell: (row) => <span className="font-mono font-semibold text-blue-800">{row.id}</span> },
    { header: 'VEHICLE', cell: (row) => <span className="font-mono font-bold text-slate-900">{row.number_plate}</span> },
    { header: 'VIOLATION', cell: (row) => <span className="text-slate-800 font-mono text-xs">{row.violation_type}</span> },
    { header: 'AMOUNT', cell: (row) => <span className="font-mono font-bold text-slate-900">{rupees(row.fine_amount)}</span> },
    { header: 'ISSUED', cell: (row) => <span className="text-sm text-slate-600">{formatIstDate(row.detected_at)}</span> },
    {
      header: 'STATUS',
      cell: (row) => (
        <div>
          <Badge variant={row.status === 'Paid' ? 'success' : 'danger'} size="sm">
            {row.status}
          </Badge>
          {row.reference && (
            <p className="text-[10px] text-slate-600 font-mono mt-1">
              {row.reference} · {formatIst(row.paid_at)}
            </p>
          )}
        </div>
      ),
    },
  ]

  const totals = data?.totals
  const months = data?.monthly_revenue.months ?? []
  const maxMonth = Math.max(1, ...months.map((m) => m.collected))
  const pages = data ? Math.max(1, Math.ceil(data.fines.total / PAGE_SIZE)) : 1
  const yearOptions = Array.from(new Set([new Date().getFullYear(), ...(data?.annual.map((a) => a.year) ?? [])]))
    .sort((a, b) => b - a)
    .map((y) => ({ value: y, label: String(y) }))

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-blue-950">Fines &amp; Revenue</h2>
        <p className="text-sm text-slate-600">Fines issued, pending and paid, with revenue collected.</p>
      </div>

      {error && <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded">{error}</div>}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <MetricCard
          label="Fines issued"
          value={totals ? rupees(totals.issued_amount) : '…'}
          subValue={totals ? `${totals.issued_count} challans` : undefined}
          status="normal"
        />
        <MetricCard
          label="Pending"
          value={totals ? rupees(totals.pending_amount) : '…'}
          subValue={totals ? `${totals.pending_count} unpaid` : undefined}
          status={totals && totals.pending_count > 0 ? 'warning' : 'normal'}
        />
        <MetricCard
          label="Revenue collected"
          value={totals ? rupees(totals.collected_amount) : '…'}
          subValue={totals ? `${totals.paid_count} payments` : undefined}
          status="success"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card
          title={`Monthly revenue collected · ${data?.monthly_revenue.year ?? ''}`}
          actions={
            <div className="w-28">
              <Select
                aria-label="Year"
                value={year ?? data?.monthly_revenue.year ?? ''}
                onChange={(e) => setYear(Number(e.target.value))}
                options={yearOptions}
              />
            </div>
          }
        >
          <table className="w-full text-xs font-mono">
            <caption className="sr-only">Revenue collected per month</caption>
            <thead className="text-slate-500 text-left">
              <tr>
                <th className="py-1 font-normal w-12">Month</th>
                <th className="py-1 font-normal">Collected</th>
                <th className="py-1 font-normal text-right w-28">Amount</th>
              </tr>
            </thead>
            <tbody>
              {months.map((m) => (
                <tr key={m.month} title={`${MONTHS[m.month - 1]}: ${rupees(m.collected)} from ${m.payments} payment(s)`}>
                  <td className="py-1 text-slate-700">{MONTHS[m.month - 1]}</td>
                  <td className="py-1 pr-3">
                    <div className="h-2.5 w-full" aria-hidden="true">
                      {m.collected > 0 && (
                        <div className="h-full bg-cyan-500 rounded-r" style={{ width: `${(m.collected / maxMonth) * 100}%` }} />
                      )}
                    </div>
                  </td>
                  <td className="py-1 text-right text-slate-800">
                    {rupees(m.collected)} <span className="text-slate-500">({m.payments})</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card title="Annual fines">
          {!data || data.annual.length === 0 ? (
            <p className="text-sm text-slate-600 py-6 text-center">No fines recorded.</p>
          ) : (
            <table className="w-full text-xs font-mono">
              <thead className="text-slate-500 text-left">
                <tr>
                  <th className="py-1 font-normal">Year</th>
                  <th className="py-1 font-normal text-right">Issued</th>
                  <th className="py-1 font-normal text-right">Collected</th>
                  <th className="py-1 font-normal text-right">Pending</th>
                </tr>
              </thead>
              <tbody className="text-slate-800">
                {data.annual.map((a) => (
                  <tr key={a.year} className="border-t border-slate-200">
                    <td className="py-1.5">{a.year}</td>
                    <td className="py-1.5 text-right">
                      {rupees(a.issued_amount)} <span className="text-slate-500">({a.issued_count})</span>
                    </td>
                    <td className="py-1.5 text-right">
                      {rupees(a.collected_amount)} <span className="text-slate-500">({a.collected_count})</span>
                    </td>
                    <td className="py-1.5 text-right">
                      {rupees(a.pending_amount)} <span className="text-slate-500">({a.pending_count})</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="text-[10px] text-slate-500 font-mono mt-3">
            Issued and pending are counted by the year the fine was issued; collected by the year it was paid.
          </p>
        </Card>
      </div>

      <Card
        title={
          data
            ? `${plate ? `Challans for ${plate}` : 'Challans'}${day ? ` issued on ${formatIstDate(`${day}T12:00:00+05:30`)}` : ''} (${data.fines.total})`
            : 'Challans'
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
          <input
            type="search"
            aria-label="Search number plate"
            placeholder="Search number plate"
            value={plateInput}
            onChange={(e) => setPlateInput(e.target.value.toUpperCase())}
            maxLength={20}
            className="w-48 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-mono text-slate-900 placeholder:font-sans placeholder-slate-400 focus:border-blue-800 focus:outline-none focus:ring-1 focus:ring-blue-800"
          />
          <input
            type="date"
            aria-label="Challans issued on date"
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
          <div className="w-36">
            <Select
              aria-label="Filter by status"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value)
                setPage(1)
              }}
              options={[
                { value: 'all', label: 'All' },
                { value: 'Unpaid', label: 'Unpaid' },
                { value: 'Paid', label: 'Paid' },
              ]}
            />
          </div>
          </div>
        }
      >
        <Table
          columns={columns}
          data={data?.fines.items ?? []}
          keyExtractor={(row) => row.id}
          isLoading={!data && !error}
          emptyMessage={
            plate
              ? `No challans for "${plate}"${day ? ' on this date' : ''}.`
              : day
                ? 'No challans issued on this date.'
                : 'No challans.'
          }
        />
        {data && data.fines.total > PAGE_SIZE && (
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
    </div>
  )
}
