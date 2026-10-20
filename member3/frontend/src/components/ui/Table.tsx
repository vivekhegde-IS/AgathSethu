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
  emptyMessage = 'No records found',
  isLoading = false,
  className = '',
}: TableProps<T>) {
  return (
    <div className={`overflow-x-auto rounded-lg border border-slate-200 bg-white ${className}`}>
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold text-slate-700">
            {columns.map((col, idx) => (
              <th key={idx} className={`py-3 px-4 ${col.className || ''}`}>
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200 text-sm text-slate-800">
          {isLoading ? (
            <tr>
              <td colSpan={columns.length} className="py-8 text-center text-slate-600">
                <div className="inline-flex items-center gap-2 font-mono">
                  <span className="w-2 h-2 rounded-full bg-aghat-blue animate-ping" />
                  Loading…
                </div>
              </td>
            </tr>
          ) : data.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="py-8 text-center text-slate-500">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            data.map((row, index) => (
              <tr
                key={keyExtractor(row, index)}
                onClick={() => onRowClick && onRowClick(row)}
                className={`transition-colors ${
                  onRowClick ? 'cursor-pointer hover:bg-blue-50' : 'hover:bg-slate-50'
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
