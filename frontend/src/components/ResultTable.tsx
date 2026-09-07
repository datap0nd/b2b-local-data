import {useEffect, useMemo, useState} from 'react';
import {columnPinningFeature, columnSizingFeature, columnVisibilityFeature, createColumnHelper, createPaginatedRowModel, createSortedRowModel, rowPaginationFeature, rowSortingFeature, tableFeatures, useTable, type ColumnVisibilityState, type SortingState} from '@tanstack/react-table';
import {ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Columns3, Info} from 'lucide-react';
import {Button} from './ui/button';
import {DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuLabel, DropdownMenuTrigger} from './ui/dropdown-menu';
import {cellText, compareValues, headerLabel, MERGE, STAGE_GROUPS, visibleColumns} from '@/format';
import {cn} from '@/lib/utils';
import type {Cell, Row, TablePayload} from '@/types';

const features = tableFeatures({rowSortingFeature, columnPinningFeature, columnSizingFeature, columnVisibilityFeature, rowPaginationFeature, sortedRowModel: createSortedRowModel(), paginatedRowModel: createPaginatedRowModel()});
const helper = createColumnHelper<typeof features, Row>();
const EMPTY: Row[] = [];

// Deliberate widths for the usual summary columns so the defaults fit at 1440px with the sidebar collapsed.
const WIDTHS: Record<string, number> = {opportunity_name: 300, opportunity_no: 120, end_customer: 200, opportunity_amount: 140, sku_amount: 130, stage: 128, opportunity_owner: 160, close_date: 110,
  quantity: 96, pet_name: 240, product_code: 120, stage_group: 120, close_month: 110, amount: 140, deal_size: 140, opportunity_count: 110, sku_count: 100};

export interface ResultTableProps {
  table: TablePayload;
  rows?: Row[];               // rows to display (defaults to the payload's rows)
  mode: 'preview' | 'full';   // preview: eight fixed rows, no pagination, no internal scrolling; full: paginated
  pageSize?: number;
  onPageSize?: (size: number) => void;
  onDetails?: (row: Row) => void;
  onSortChange?: (sorted: boolean) => void;
  onSortedRows?: (rows: Row[]) => void;
  sorting?: SortingState;
  onSorting?: (sorting: SortingState) => void;
  columns?: string[];         // visible columns override
}

export function ResultTable({table, rows = table.rows, mode, pageSize = 50, onPageSize, onDetails, onSortChange, onSortedRows, sorting: controlledSorting, onSorting, columns}: ResultTableProps) {
  const visible = columns ?? visibleColumns(table);
  const [localSorting, setLocalSorting] = useState<SortingState>([]);
  const sorting = controlledSorting ?? localSorting;
  const setSorting = onSorting ?? setLocalSorting;
  const [visibility, setVisibility] = useState<ColumnVisibilityState>({});
  const [pageIndex, setPageIndex] = useState(0);
  const merged = useMemo(() => Object.fromEntries(visible.map(c => [c, MERGE[c] && table.columns.includes(MERGE[c]) && !visible.includes(MERGE[c]) ? MERGE[c] : null])), [visible, table.columns]);
  const allColumns = useMemo(() => [...visible, ...table.columns.filter(c => !visible.includes(c) && !Object.values(merged).includes(c))], [visible, table.columns, merged]);
  const columnDefs = useMemo(() => helper.columns(allColumns.map(column => helper.accessor(row => (row[column] ?? undefined) as Cell, {
    id: column,
    header: headerLabel(table, column),
    size: WIDTHS[column] ?? (table.column_types[column] === 'number' ? 120 : 160),
    enableSorting: true,
    sortFn: (a, b) => compareValues(a.getValue(column) as Cell, b.getValue(column) as Cell, table.column_types[column] ?? 'text'),
    sortUndefined: 'last',
    cell: ctx => {
      const row = ctx.row.original;
      const partner = merged[column];
      const text = cellText(table, row, column);
      if (partner) return <span className="flex min-w-0 flex-col"><span className="line-clamp-2 break-words">{text}</span>{row[partner] != null && <span className="truncate font-mono text-[11px] text-ink-3">{String(row[partner])}</span>}</span>;
      if (column === 'stage' || column === 'stage_group') { const group = STAGE_GROUPS[String(row[column])] ?? (String(row[column]).toLowerCase() as 'won' | 'open' | 'lost'); return row[column] == null ? <span className="text-ink-3">—</span> : <span className={cn('inline-block rounded-md px-1.5 py-0.5 text-xs font-medium', group === 'won' ? 'bg-won-soft text-won' : group === 'open' ? 'bg-open-soft text-open' : group === 'lost' ? 'bg-lost-soft text-lost' : 'bg-surface-2 text-ink-2')}>{text}</span>; }
      if (column === 'has_quality_warning' || column === 'has_amount_discrepancy') return row[column] == null ? <span className="text-ink-3">—</span> : <span className={cn('inline-block rounded-md px-1.5 py-0.5 text-xs font-medium', row[column] ? 'bg-warn-soft text-warn' : 'bg-surface-2 text-ink-2')}>{text}</span>;
      return <span className={cn(row[column] == null && 'text-ink-3', table.column_types[column] === 'number' && 'tabular')}>{text}</span>;
    },
  }))), [allColumns, merged, table]);

  const hidden = useMemo(() => Object.fromEntries(allColumns.map(c => [c, visibility[c] ?? visible.includes(c)])), [allColumns, visibility, visible]);
  const t = useTable({
    features, columns: columnDefs, data: rows.length ? rows : EMPTY,
    state: {sorting, columnVisibility: hidden, columnPinning: {start: [visible[0]], end: []}, pagination: {pageIndex: mode === 'preview' ? 0 : pageIndex, pageSize: mode === 'preview' ? 8 : pageSize}},
    onSortingChange: updater => { const next = typeof updater === 'function' ? updater(sorting) : updater; setSorting(next); onSortChange?.(next.length > 0); },
    onColumnVisibilityChange: updater => setVisibility((prev: ColumnVisibilityState) => (typeof updater === 'function' ? updater(prev) : updater)),
    onPaginationChange: updater => { const next = typeof updater === 'function' ? updater({pageIndex, pageSize}) : updater; setPageIndex(next.pageIndex); if (next.pageSize !== pageSize) onPageSize?.(next.pageSize); },
    enableColumnPinning: true,
  });
  const pageRows = t.getRowModel().rows;
  const pageCount = Math.max(1, Math.ceil(rows.length / (mode === 'preview' ? 8 : pageSize)));
  const shownColumns = t.getVisibleLeafColumns();
  const sortedRows = t.getSortedRowModel().rows;
  useEffect(() => { onSortedRows?.(sortedRows.map(row => row.original)); }, [sortedRows, onSortedRows]);

  return (
    <div className="flex flex-col gap-2" data-testid="result-table" data-mode={mode}>
      {mode === 'full' && (
        <div className="flex flex-wrap items-center gap-2 text-sm text-ink-2">
          <span data-testid="page-summary">Page {pageIndex + 1} of {pageCount}</span>
          <label className="ml-auto flex items-center gap-2">Rows per page
            <select value={pageSize} onChange={e => { onPageSize?.(Number(e.target.value)); setPageIndex(0); }} aria-label="Rows per page" className="h-8 rounded-md border border-line bg-canvas px-2 text-sm text-ink">
              {[25, 50, 100].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="outline" size="sm"><Columns3 />Columns</Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="max-h-80 overflow-auto">
              <DropdownMenuLabel>Visible columns</DropdownMenuLabel>
              {allColumns.map(c => <DropdownMenuCheckboxItem key={c} checked={hidden[c]} onCheckedChange={v => setVisibility((prev: ColumnVisibilityState) => ({...prev, [c]: !!v}))} disabled={c === visible[0]}>{headerLabel(table, c)}</DropdownMenuCheckboxItem>)}
            </DropdownMenuContent>
          </DropdownMenu>
          <Button variant="outline" size="icon-sm" aria-label="Previous page" disabled={pageIndex === 0} onClick={() => setPageIndex(i => i - 1)}><ChevronLeft /></Button>
          <Button variant="outline" size="icon-sm" aria-label="Next page" disabled={pageIndex >= pageCount - 1} onClick={() => setPageIndex(i => i + 1)}><ChevronRight /></Button>
        </div>
      )}
      <div className={cn('rounded-lg border border-line', mode === 'full' ? 'overflow-auto scroll-thin' : 'overflow-x-auto overflow-y-hidden')}>
        <table className="w-max min-w-full border-separate border-spacing-0 text-[13px]" style={{width: t.getTotalSize()}}>
          <thead>
            {t.getHeaderGroups().map(group => (
              <tr key={group.id}>
                {group.headers.map(header => {
                  const pinned = header.column.getIsPinned() === 'start';
                  const sort = header.column.getIsSorted();
                  const numeric = table.column_types[header.column.id] === 'number' && !merged[header.column.id];
                  return (
                    <th key={header.id} scope="col" aria-sort={sort === 'asc' ? 'ascending' : sort === 'desc' ? 'descending' : 'none'} data-column={header.column.id}
                      style={{width: header.getSize(), minWidth: header.getSize(), left: pinned ? 0 : undefined}}
                      className={cn('sticky top-0 z-10 border-b border-line bg-surface px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-ink-2', pinned && 'left-0 z-20 shadow-[1px_0_0_var(--color-line)]', numeric && 'text-right')}>
                      <button type="button" onClick={header.column.getToggleSortingHandler()} className={cn('inline-flex max-w-full items-center gap-1 whitespace-nowrap hover:text-ink', numeric && 'justify-end')}>
                        <span className="truncate">{header.isPlaceholder ? null : <t.FlexRender header={header} />}</span>
                        {sort === 'asc' ? <ArrowUp className="size-3" /> : sort === 'desc' ? <ArrowDown className="size-3" /> : <ArrowUpDown className="size-3 opacity-40" />}
                      </button>
                    </th>
                  );
                })}
                {onDetails && <th scope="col" className="sticky top-0 z-10 w-10 border-b border-line bg-surface" aria-label="Details" />}
              </tr>
            ))}
          </thead>
          <tbody>
            {pageRows.map(row => (
              <tr key={row.id} className={cn('h-11 hover:bg-surface/70', row.original.has_quality_warning === true && 'shadow-[inset_3px_0_0_var(--color-warn-line)]')}>
                {row.getVisibleCells().map(cell => {
                  const pinned = cell.column.getIsPinned() === 'start';
                  const numeric = table.column_types[cell.column.id] === 'number' && !merged[cell.column.id];
                  return (
                    <td key={cell.id} style={{width: cell.column.getSize(), minWidth: cell.column.getSize(), left: pinned ? 0 : undefined}}
                      className={cn('border-b border-line bg-canvas px-3 py-1.5 align-middle', pinned && 'sticky left-0 z-10 shadow-[1px_0_0_var(--color-line)]', numeric ? 'text-right tabular' : 'truncate')}>
                      <t.FlexRender cell={cell} />
                    </td>
                  );
                })}
                {onDetails && <td className="border-b border-line bg-canvas px-1 text-center"><button type="button" aria-label="Row details" onClick={() => onDetails(row.original)} className="rounded p-1 text-ink-3 hover:bg-surface hover:text-ink"><Info className="size-4" /></button></td>}
              </tr>
            ))}
            {pageRows.length === 0 && <tr><td colSpan={shownColumns.length + (onDetails ? 1 : 0)} className="px-3 py-6 text-center text-ink-3">No rows.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export const PREVIEW_ROWS = 8;
