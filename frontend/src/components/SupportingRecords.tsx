import {useContext, useEffect, useState} from 'react';
import {TestScope} from '@/TestScope';
import type {SortingState} from '@tanstack/react-table';
import {Download, Maximize2, RotateCcw} from 'lucide-react';
import {api} from '@/api';
import {filterText} from '@/format';
import {cn, download} from '@/lib/utils';
import type {AnswerPayload, Row, TablePayload, ViewName} from '@/types';
import {Button} from './ui/button';
import {Dialog, DialogContent} from './ui/dialog';
import {DetailsPanel} from './DetailsPanel';
import {PREVIEW_ROWS, ResultTable} from './ResultTable';

/** The records behind an aggregate, frozen with its answer. Opening or sorting never reruns a query. */
export function SupportingRecords({answer, onRerun}: {answer: AnswerPayload; onRerun?: () => void}) {
  const run = useContext(TestScope);
  const supporting = answer.supporting;
  const [view, setView] = useState<ViewName>(supporting?.default_view ?? 'summary');
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [loaded, setLoaded] = useState<TablePayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [exportError, setExportError] = useState('');
  const [exporting, setExporting] = useState(false);
  const [details, setDetails] = useState<{table: TablePayload; row: Row} | null>(null);
  const preview = supporting?.views?.[view];
  const sortField = sorting[0]?.id;
  const sortDirection = sorting[0]?.desc ? 'desc' : 'asc';
  const availableViews = (['summary', 'detail'] as ViewName[]).filter(value => supporting?.views?.[value]);
  const unit = view === 'summary' ? 'opportunities' : 'product rows';
  const unavailable = supporting?.message ?? 'Supporting records were not saved with this answer. Run it with current data to create a new answer with its records.';

  useEffect(() => {
    if (!open || !supporting?.available) return;
    let active = true;
    setLoading(true); setLoadError('');
    api.supporting(answer.session_id, answer.turn_id, view, page, pageSize, sortField ? {field: sortField, direction: sortDirection} : undefined, run)
      .then(result => {
        if (!active) return;
        if (result.available) setLoaded(result.table);
        else { setLoaded(null); setLoadError(result.message); }
      })
      .catch(error => { if (active) { setLoaded(null); setLoadError(error instanceof Error ? error.message : 'Saved records could not be loaded.'); } })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [open, supporting?.available, answer.session_id, answer.turn_id, view, page, pageSize, sortField, sortDirection, run]);

  function changeView(next: ViewName) { setView(next); setPage(0); setSorting([]); setLoaded(null); setExportError(''); }
  function rerun() { setOpen(false); onRerun?.(); }
  async function exportRecords() {
    if (exporting || !supporting?.available) return;
    setExporting(true); setExportError('');
    try {
      const blob = await api.supportingCsv(answer.session_id, answer.turn_id, view, sortField ? {field: sortField, direction: sortDirection} : undefined, run);
      download(`b2b-supporting-${view === 'summary' ? 'opportunities' : 'products'}.csv`, blob);
    } catch (error) { setExportError(error instanceof Error ? error.message : 'The saved records could not be downloaded.'); }
    finally { setExporting(false); }
  }
  const viewControl = availableViews.length > 1 && <div role="group" aria-label="Supporting view" className="inline-flex rounded-lg bg-surface p-1">
    {availableViews.map(value => <button type="button" key={value} disabled={loading} onClick={() => changeView(value)} aria-pressed={view === value} className={cn('rounded-md px-3 py-1 text-[13px] font-medium', view === value ? 'bg-canvas text-accent shadow-sm' : 'text-ink-2 hover:text-ink')}>{value === 'summary' ? 'Summary' : 'Products'}</button>)}
  </div>;
  const rerunControl = onRerun && <Button variant="outline" size="sm" onClick={rerun}><RotateCcw />Run with current data</Button>;
  const downloadControl = <Button variant="ghost" size="sm" disabled={exporting || !supporting?.available} onClick={exportRecords} data-testid="supporting-export"><Download />{exporting ? 'Preparing CSV…' : 'Supporting CSV'}</Button>;

  return <section className="border-t border-line px-5 py-5 sm:px-7" data-testid="supporting-records" aria-label={`Supporting ${unit}`}>
    <div className="flex flex-wrap items-center gap-3">
      <div className="mr-auto"><h3 className="text-base font-semibold">Supporting {unit}</h3><p className="mt-1 text-xs text-ink-3">The records behind this answer, with the same filters and data snapshot.</p></div>
      {preview && viewControl}
    </div>
    {preview ? <>
      {preview.views?.scope_label && <p className="mt-3 text-xs text-ink-2" data-testid="supporting-scope">{preview.views.scope_label}</p>}
      <div className="mt-3" data-testid="supporting-preview">
        {preview.rows.length ? <ResultTable table={preview} mode="preview" sortable={false} onDetails={row => setDetails({table: preview, row})} /> : <p className="rounded-lg bg-surface px-4 py-5 text-sm text-ink-3">No supporting {unit} match these filters.</p>}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {preview.rows.length > 0 && <p className="mr-auto text-xs text-ink-3">Preview · first {Math.min(PREVIEW_ROWS, preview.rows.length)} rows</p>}
        {supporting?.available && <>{downloadControl}<Button variant="outline" size="sm" onClick={() => setOpen(true)} data-testid="supporting-explore"><Maximize2 />Explore supporting data</Button></>}
      </div>
    </> : null}
    {!supporting?.available && <div className="mt-3 space-y-3 text-sm text-ink-3" data-testid="supporting-unavailable"><p>{unavailable}</p>{rerunControl}</div>}
    {exportError && !open && <p role="alert" className="mt-3 text-sm text-danger">{exportError}</p>}
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent side="right" title={`Supporting ${unit}`} className="w-[min(1280px,100vw)]" aria-describedby="supporting-dialog-context">
        <div className="space-y-4" data-testid="supporting-panel">
          <p id="supporting-dialog-context" className="text-sm text-ink-2">{preview?.views?.scope_label ?? 'Saved records behind this answer'}. Sorting and CSV use every saved matching row.</p>
          <div className="flex flex-wrap items-center gap-2">{viewControl}<span className="ml-auto">{downloadControl}</span></div>
          {preview?.metadata.evidence?.amount_complete === false && <p className="text-xs text-ink-3">Some source amounts are missing, invalid or have conflicting currencies. Amount sorting is unavailable; the saved values remain visible and downloadable.</p>}
          {preview?.filters.length ? <ul className="flex flex-wrap gap-2 text-xs" aria-label="Supporting filters" data-testid="supporting-filters">{preview.filters.map((filter, index) => <li key={index} className="rounded-md bg-surface px-2 py-1 text-ink-2">{filterText(filter, preview.column_types)}</li>)}</ul> : null}
          {loadError ? <div className="space-y-3 text-sm text-danger" role="alert"><p>{loadError}</p>{sorting.length > 0 && <Button variant="outline" size="sm" onClick={() => { setSorting([]); setPage(0); }}>Clear sort</Button>}{rerunControl}</div> : <>
            {loading && <p role="status" className="text-sm text-ink-3">Loading saved records…</p>}
            {loaded && <div className={cn(loading && 'pointer-events-none opacity-50')} aria-busy={loading}>
              <ResultTable table={loaded} mode="full" pageSize={pageSize} onPageSize={size => { setPageSize(size); setPage(0); }} sorting={sorting} onSorting={value => { setSorting(value.slice(-1)); setPage(0); }} busy={loading} remotePage={{index: page, totalRows: loaded.total_rows, onChange: setPage}} onDetails={row => setDetails({table: loaded, row})} />
            </div>}
          </>}
          {exportError && <p role="alert" className="text-sm text-danger">{exportError}</p>}
        </div>
      </DialogContent>
    </Dialog>
    {details && <DetailsPanel table={details.table} row={details.row} onClose={() => setDetails(null)} />}
  </section>;
}
