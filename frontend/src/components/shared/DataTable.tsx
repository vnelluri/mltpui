import type { ReactNode } from 'react';
import { LoadingSpinner } from './LoadingSpinner';
import { EmptyState } from './EmptyState';

export interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => ReactNode;
  accessor?: (row: T) => string | number;
  sortable?: boolean;
  align?: 'left' | 'right' | 'center';
  className?: string;
  headerClassName?: string;
}

export interface SortState {
  key: string;
  dir: 'asc' | 'desc';
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  error?: string | null;
  emptyTitle?: string;
  emptyDescription?: string;
  emptyAction?: ReactNode;
  onRowClick?: (row: T) => void;
  // Pagination (consumes {total, page, pageSize} from the API)
  total?: number;
  page?: number;
  pageSize?: number;
  onPageChange?: (page: number) => void;
  // Sorting
  sort?: SortState | null;
  onSortChange?: (sort: SortState) => void;
  onRetry?: () => void;
}

function SortIcon({ dir }: { dir: 'asc' | 'desc' | null }) {
  return (
    <span className="ml-1 inline-flex flex-col leading-none text-[8px]">
      <span className={dir === 'asc' ? 'text-brand-purple' : 'text-text-muted'}>▲</span>
      <span className={dir === 'desc' ? 'text-brand-purple' : 'text-text-muted'}>▼</span>
    </span>
  );
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading = false,
  error = null,
  emptyTitle = 'No records found',
  emptyDescription,
  emptyAction,
  onRowClick,
  total,
  page = 1,
  pageSize = 20,
  onPageChange,
  sort = null,
  onSortChange,
  onRetry,
}: DataTableProps<T>) {
  const alignClass = (align?: 'left' | 'right' | 'center') =>
    align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left';

  const handleHeaderClick = (col: Column<T>) => {
    if (!col.sortable || !onSortChange) return;
    const nextDir: 'asc' | 'desc' = sort?.key === col.key && sort.dir === 'asc' ? 'desc' : 'asc';
    onSortChange({ key: col.key, dir: nextDir });
  };

  const totalPages = total !== undefined ? Math.max(1, Math.ceil(total / pageSize)) : 1;
  const showPagination = total !== undefined && onPageChange && total > pageSize;
  const rangeStart = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const rangeEnd = Math.min(page * pageSize, total ?? rows.length);

  if (error) {
    return (
      <div className="rounded-xl border border-red-500/30 bg-bg-card p-10 text-center">
        <p className="text-sm text-red-600">{error}</p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="mt-4 rounded-lg border border-bg-elevated px-4 py-2 text-sm font-medium text-text-secondary transition hover:bg-bg-elevated"
          >
            Retry
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-bg-elevated bg-bg-card">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-bg-elevated bg-bg-elevated/40">
              {columns.map((col) => (
                <th
                  key={col.key}
                  onClick={() => handleHeaderClick(col)}
                  className={`px-4 py-3 text-xs font-semibold uppercase tracking-wide text-text-secondary ${alignClass(
                    col.align,
                  )} ${col.sortable ? 'cursor-pointer select-none hover:text-text-primary' : ''} ${
                    col.headerClassName ?? ''
                  }`}
                >
                  <span className="inline-flex items-center">
                    {col.header}
                    {col.sortable && <SortIcon dir={sort?.key === col.key ? sort.dir : null} />}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-16">
                  <LoadingSpinner label="Loading…" />
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-6">
                  <EmptyState title={emptyTitle} description={emptyDescription} action={emptyAction} />
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr
                  key={rowKey(row)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={`border-b border-bg-elevated/60 transition last:border-0 ${
                    onRowClick ? 'cursor-pointer hover:bg-bg-elevated/40' : ''
                  }`}
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={`px-4 py-3 text-text-primary ${alignClass(col.align)} ${col.className ?? ''}`}
                    >
                      {col.render ? col.render(row) : col.accessor ? col.accessor(row) : null}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {showPagination && (
        <div className="flex items-center justify-between border-t border-bg-elevated px-4 py-3 text-sm text-text-secondary">
          <span>
            Showing <span className="text-text-primary">{rangeStart}</span>–
            <span className="text-text-primary">{rangeEnd}</span> of{' '}
            <span className="text-text-primary">{total}</span>
          </span>
          <div className="flex items-center gap-2">
            <button
              disabled={page <= 1}
              onClick={() => onPageChange?.(page - 1)}
              className="rounded-lg border border-bg-elevated px-3 py-1.5 text-xs font-medium transition enabled:hover:bg-bg-elevated disabled:opacity-40"
            >
              Previous
            </button>
            <span className="px-2 text-xs">
              Page {page} of {totalPages}
            </span>
            <button
              disabled={page >= totalPages}
              onClick={() => onPageChange?.(page + 1)}
              className="rounded-lg border border-bg-elevated px-3 py-1.5 text-xs font-medium transition enabled:hover:bg-bg-elevated disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
