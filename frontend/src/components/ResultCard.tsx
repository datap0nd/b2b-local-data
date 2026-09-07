import {useEffect, useState} from 'react';
import type {SortingState} from '@tanstack/react-table';
import {AlertTriangle, Download, Maximize2} from 'lucide-react';
import {Button} from './ui/button';
import {Hint} from './ui/tooltip';
import {ResultChart} from './ResultChart';
import {PREVIEW_ROWS, ResultTable} from './ResultTable';
import {DetailsPanel} from './DetailsPanel';
import {QualityPanel} from './QualityPanel';
import {OpenDefinition} from './OpenDefinition';
import {SupportingRecords} from './SupportingRecords';
import {csvText, filterText, formatUpdated, MEASURE_LABELS} from '@/format';
import {cn, download} from '@/lib/utils';
import type {AnswerPayload, PresentationName, Row, TablePayload, ViewName} from '@/types';

export interface ResultCardProps {
  answer: AnswerPayload;
  shown: TablePayload;
  view: ViewName;
  presentation: PresentationName;
  loading?: boolean;
  notice?: string;
  onView: (view: ViewName) => void;
  onPresentation: (presentation: PresentationName) => void;
  onExplore: () => void;
  onSuggestion: (text: string) => void;
  expanded?: boolean;
  onRerun?: () => void;
}

export function scopeText(table: TablePayload, expanded = false): string {
  const unit = table.result_kind === 'aggregate' ? 'groups' : table.grain === 'opportunity_sku' ? 'product rows' : 'opportunities';
  if (table.total_rows === 0) return `No matching ${unit}`;
  if (expanded) return table.truncated ? `${table.rows.length.toLocaleString()} of ${table.total_rows.toLocaleString()} matching ${unit} returned. Sorting and CSV cover these returned rows.` : `${table.total_rows.toLocaleString()} matching ${unit}`;
  const visible = Math.min(PREVIEW_ROWS, table.rows.length);
  return visible < table.total_rows ? `Preview: ${visible.toLocaleString()} of ${table.total_rows.toLocaleString()} matching ${unit}${table.truncated ? ` · ${table.rows.length.toLocaleString()} returned for sorting and CSV` : ''}` : `${table.total_rows.toLocaleString()} matching ${unit}`;
}

/** Title, context, metrics and optional insight have separate owners in the answer contract. */
export function ResultCard({answer, shown: table, view, presentation, loading, notice, onView, onPresentation, onExplore, onSuggestion, expanded, onRerun}: ResultCardProps) {
  const [measure, setMeasure] = useState(table.chart?.measures[0] ?? '');
  const [details, setDetails] = useState<Row | null>(null);
  const [warningsOpen, setWarningsOpen] = useState(false);
  const [pageSize, setPageSize] = useState(50);
  const [exportRows, setExportRows] = useState(table.rows);
  const [sorting, setSorting] = useState<SortingState>([]);
  useEffect(() => { setExportRows(table.rows); setSorting([]); }, [table.result_digest, table.view]);
  const text = answer.answer;
  const rows = table.result_kind === 'rows';
  const scalar = table.result_kind === 'aggregate' && table.columns.every(column => MEASURE_LABELS[column]);
  const canChart = table.result_kind === 'aggregate' && !!table.chart;
  const showChart = canChart && presentation === 'chart';
  const warnings = table.metadata?.warnings ?? [];
  const quality = warnings.find(warning => warning.code === 'quality_warning');
  const measureKey = table.chart?.measures.includes(measure) ? measure : table.chart?.measures[0] ?? '';
  const singleMetric = scalar && text.metrics.length === 1;
  const openFilter = table.filters.some(filter => filter.field === 'stage_group' && (filter.value === 'Open' || (Array.isArray(filter.value) && filter.value.includes('Open'))));

  return (
    <section aria-label={text.title} data-testid="result-card" data-view={table.view} data-presentation={presentation} className={cn('rounded-card border border-line border-t-[3px] border-t-accent bg-canvas shadow-card', loading && 'opacity-60')}>
      <header className="px-5 pt-6 sm:px-7">
        <div className="flex items-center gap-2">
          <h2 className={cn('font-semibold leading-tight tracking-tight', scalar ? 'text-xl' : 'text-2xl')} data-testid="answer-title">{text.title}</h2>
          {openFilter && <OpenDefinition />}
        </div>
        {text.context && <p className="mt-2 text-sm text-ink-3" data-testid="answer-context">{text.context}</p>}
        {text.metrics.length > 0 && <dl className={cn('mt-5 grid gap-5', !singleMetric && 'sm:grid-cols-3')} data-testid="metrics">
          {text.metrics.map(metric => <div key={metric.label}>
            <dt className={singleMetric ? 'sr-only' : 'text-xs font-medium text-ink-3'}>{metric.label}</dt>
            <dd className={cn('break-words font-semibold leading-tight tracking-tight tabular', singleMetric ? 'text-[clamp(44px,6vw,68px)] text-accent' : 'mt-1 text-[32px]')}>{metric.value}</dd>
            {metric.note && <p className="mt-1 text-xs text-ink-3">{metric.note}</p>}
          </div>)}
        </dl>}
        {text.sentence && <p className="mt-3 max-w-3xl text-sm leading-relaxed text-ink-2" data-testid="answer-sentence">{text.sentence}</p>}
        {table.metadata?.currency?.mixed && <p className="mt-2 text-xs text-ink-3" data-testid="currency-note">Amounts are separated by currency; no combined total is calculated.</p>}
        {table.views?.scope_label && <p className="mt-2 text-xs text-ink-3" data-testid="scope-label">{table.views.scope_label}</p>}
        {quality && <button type="button" className="mt-4 inline-flex items-center gap-2 rounded-lg bg-warn-soft px-3 py-2 text-left text-xs font-medium text-warn hover:bg-warn-line/40" onClick={() => setWarningsOpen(true)} data-testid="quality" aria-haspopup="dialog"><AlertTriangle className="size-3.5 shrink-0" />{quality.count.toLocaleString()} {table.grain === 'opportunity_sku' ? (quality.count === 1 ? 'product row needs' : 'product rows need') : (quality.count === 1 ? 'opportunity needs' : 'opportunities need')} review<span aria-hidden="true">→</span></button>}
        {warnings.filter(warning => warning.code !== 'quality_warning').map(warning => <p key={warning.code} className="mt-2 text-xs text-ink-3">{warning.message}</p>)}
      </header>
      <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-line px-5 py-3 sm:px-7" data-testid="result-controls">
        {rows && table.views?.available?.length > 1 && <div role="group" aria-label="Detail level" className="inline-flex rounded-lg bg-surface p-1">
          {(['summary', 'detail'] as ViewName[]).map(value => <button key={value} type="button" onClick={() => onView(value)} aria-pressed={view === value} disabled={loading} className={cn('rounded-md px-3 py-1 text-[13px] font-medium transition-colors', view === value ? 'bg-canvas text-accent shadow-sm' : 'text-ink-2 hover:text-ink')}>{value === 'summary' ? 'Summary' : 'Detailed'}</button>)}
        </div>}
        {canChart && <div role="group" aria-label="Presentation" className="inline-flex rounded-lg bg-surface p-1">
          {(['chart', 'table'] as PresentationName[]).map(value => <button key={value} type="button" onClick={() => onPresentation(value)} aria-pressed={presentation === value} className={cn('rounded-md px-3 py-1 text-[13px] font-medium transition-colors', presentation === value ? 'bg-canvas text-accent shadow-sm' : 'text-ink-2 hover:text-ink')}>{value === 'chart' ? 'Chart' : 'Data'}</button>)}
        </div>}
        {notice && <span className="text-xs text-ink-3">{notice}</span>}
        <span className="ml-auto flex items-center gap-1">
          <Hint text={table.truncated ? 'Exports the returned rows and all columns in the displayed table order, with exact values.' : 'Exports every returned row and column in the displayed table order, with exact values.'}><Button variant="ghost" size="xs" onClick={() => download(`b2b-${table.grain}.csv`, csvText(table, exportRows), 'text/csv;charset=utf-8')} data-testid="export"><Download />{rows ? 'CSV' : 'Result CSV'}</Button></Hint>
          {!expanded && table.total_rows > 0 && !scalar && <Button variant="outline" size="sm" onClick={onExplore} data-testid="explore"><Maximize2 />Explore results</Button>}
        </span>
      </div>
      {!scalar && <div className="px-5 pb-5 sm:px-7" data-testid="primary-result">
        {showChart ? <ResultChart table={table} measure={measureKey} onMeasure={setMeasure} /> : <>
          <p className="mb-3 text-xs text-ink-3" data-testid="scope">{scopeText(table, expanded)}</p>
          {table.total_rows === 0 ? <p className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-sm text-ink-3" data-testid="empty">No rows match this question.</p> : <ResultTable table={table} mode={expanded ? 'full' : 'preview'} pageSize={pageSize} onPageSize={setPageSize} onDetails={setDetails} onSortedRows={setExportRows} sorting={sorting} onSorting={setSorting} key={table.view + table.result_digest} />}
        </>}
      </div>}
      {!rows && <SupportingRecords answer={answer} onRerun={onRerun} />}
      <details className="border-t border-line px-5 py-3 text-xs text-ink-3 sm:px-7" data-testid="query-details">
        <summary className="w-fit cursor-pointer rounded font-medium hover:text-ink">Query details</summary>
        <div className="mt-3 space-y-3">
          {table.filters.length > 0 ? <ul className="flex flex-wrap gap-2" aria-label="Active filters" data-testid="filters">{table.filters.map((filter, index) => <li key={index} className="rounded-md bg-surface px-2 py-1 text-ink-2">{filterText(filter, table.column_types)}</li>)}</ul> : <p>No filters applied.</p>}
          {table.metadata?.freshness?.status === 'verified' && <p>Answer snapshot: {formatUpdated(table.metadata.freshness.updated_at)?.full}</p>}
          {table.metadata?.calculation_version != null && <p>Calculation version {table.metadata.calculation_version}</p>}
        </div>
      </details>
      {answer.suggestions.length > 0 && !expanded && <footer className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3 sm:px-7" data-testid="suggestions">{answer.suggestions.map(suggestion => <button key={suggestion} type="button" onClick={() => onSuggestion(suggestion)} className="rounded-md px-2 py-1 text-[13px] text-accent hover:bg-accent-soft">{suggestion}<span aria-hidden="true" className="ml-2">↗</span></button>)}</footer>}
      <DetailsPanel table={table} row={details} onClose={() => setDetails(null)} />
      {quality && <QualityPanel warning={quality} open={warningsOpen} onClose={() => setWarningsOpen(false)} />}
    </section>
  );
}
