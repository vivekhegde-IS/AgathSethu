import { ReactNode } from 'react'

export interface Column<T> {
  header: ReactNode
  accessor?: keyof T | ((row: T) => ReactNode)
  className?: string
  cell?: (row: T, index: number) => ReactNode
}

export interface TableProps<T> {
  columns: Column<T>[]
  data: T[]
  keyExtractor: (row: T, index: number) => string | number
  onRowClick?: (row: T) => void
  emptyMessage?: string
  isLoading?: boolean
  className?: string
}

export function Table<T>({
  columns,
  data,
  keyExtractor,
  onRowClick,
  emptyMessage = 'No telemetry records found',
  isLoading = false,
  className = '',
}: TableProps<T>) {
  return (
    <div className={`overflow-x-auto rounded-lg border border-slate-800/80 bg-aghat-navy-light/60 ${className}`}>
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="border-b border-slate-800 bg-[#121820]/90 text-[11px] font-mono font-semibold uppercase tracking-wider text-slate-400">
            {columns.map((col, idx) => (
              <th key={idx} className={`py-3 px-4 ${col.className || ''}`}>
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/60 text-xs">
          {isLoading ? (
            <tr>
              <td colSpan={columns.length} className="py-8 text-center text-slate-400">
                <div className="inline-flex items-center gap-2 font-mono">
                  <span className="w-2 h-2 rounded-full bg-aghat-blue animate-ping" />
                  Streaming data...
                </div>
              </td>
            </tr>
          ) : data.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="py-8 text-center text-slate-500 font-mono">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            data.map((row, index) => (
              <tr
                key={keyExtractor(row, index)}
                onClick={() => onRowClick && onRowClick(row)}
                className={`transition-colors ${
                  onRowClick ? 'cursor-pointer hover:bg-slate-800/60' : 'hover:bg-slate-800/30'
                }`}
              >
                {columns.map((col, colIdx) => (
                  <td key={colIdx} className={`py-3 px-4 ${col.className || ''}`}>
                    {col.cell
                      ? col.cell(row, index)
                      : typeof col.accessor === 'function'
                      ? col.accessor(row)
                      : col.accessor
                      ? (row[col.accessor] as ReactNode)
                      : null}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
