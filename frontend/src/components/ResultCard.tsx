import {useState} from 'react';
import {AlertTriangle, ChevronDown, Download, Maximize2} from 'lucide-react';
import {Button} from './ui/button';
import {Hint} from './ui/tooltip';
import {Freshness} from './Freshness';
import {ResultChart} from './ResultChart';
import {PREVIEW_ROWS, ResultTable} from './ResultTable';
import {DetailsPanel} from './DetailsPanel';
import {csvText, filterText, formatNumber, label, MEASURE_LABELS} from '@/format';
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
}

/** Scope of a row result in plain words: complete match count, preview limit, and view scope. */
const MEASURE_SET = new Set(['amount', 'quantity', 'sku_count', 'opportunity_count', 'deal_size']);

export function scopeText(table: TablePayload): string {
  if (table.result_kind === 'aggregate' && !table.columns.some(c => !MEASURE_SET.has(c))) { const n = table.metadata?.complete?.opportunities; return n == null ? 'Overall total' : `Across ${n.toLocaleString()} matching opportunities`; }
  const unit = table.result_kind === 'aggregate' ? (table.total_rows === 1 ? 'group' : 'groups') : table.grain === 'opportunity_sku' ? 'product rows' : 'opportunities';
  const total = table.total_rows.toLocaleString();
  if (table.total_rows === 0) return `No matching ${unit}`;
  return table.truncated ? `${total} matching ${unit} · first ${table.rows.length.toLocaleString()} returned` : `All ${total} matching ${unit}`;
}

export function ResultCard({answer, shown, view, presentation, loading, notice, onView, onPresentation, onExplore, onSuggestion, expanded}: ResultCardProps) {
  const table = shown;
  const [measure, setMeasure] = useState(table.chart?.measures[0] ?? '');
  const [details, setDetails] = useState<Row | null>(null);
  const [warningsOpen, setWarningsOpen] = useState(false);
  const text = answer.answer;
  const rows = table.result_kind === 'rows';
  const aggregate = table.result_kind === 'aggregate';
  const ungrouped = aggregate && table.columns.every(c => MEASURE_LABELS[c]);
  const canChart = aggregate && !!table.chart;
  const showChart = canChart && presentation === 'chart';
  const showCards = ungrouped && presentation !== 'table';
  const warnings = table.metadata?.warnings ?? [];
  const quality = warnings.find(w => w.code === 'quality_warning');
  const measureKey = table.chart?.measures.includes(measure) ? measure : table.chart?.measures[0] ?? '';

  return (
    <section aria-label={text.title} data-testid="result-card" data-view={table.view} data-presentation={presentation} className={cn('rounded-card border border-line bg-canvas shadow-card', loading && 'opacity-60')}>
      <header className="px-5 pt-4">
        <h2 className="text-2xl font-semibold leading-tight tracking-tight" data-testid="answer-title">{text.title}</h2>
        <p className="mt-1.5 text-[15px] text-ink" data-testid="answer-sentence">{text.sentence}</p>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-3">
          <span data-testid="scope">{scopeText(table)}</span>
          {table.views?.scope_label && <span className="rounded-md bg-surface px-1.5 py-0.5 text-ink-2" data-testid="scope-label">{table.views.scope_label}</span>}
          <Freshness freshness={table.metadata?.freshness} />
          {table.metadata?.currency?.mixed && <span data-testid="currency-note">Several currencies match; amounts are shown with their codes.</span>}
        </div>
        {table.filters.length > 0 && (
          <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Active filters" data-testid="filters">
            {table.filters.map((f, i) => <li key={i} className="rounded-md border border-line bg-surface px-2 py-0.5 text-xs text-ink-2">{filterText(f, table.column_types)}</li>)}
          </ul>
        )}
        {text.metrics.length > 0 && (
          <dl className="mt-4 grid gap-3 sm:grid-cols-3" data-testid="metrics">
            {text.metrics.map(m => (
              <div key={m.label} className="rounded-lg bg-surface px-4 py-3">
                <dt className="text-xs font-medium uppercase tracking-wide text-ink-3">{m.label}</dt>
                <dd className="mt-0.5 text-[28px] font-semibold leading-tight tabular sm:text-[32px]">{m.value}</dd>
                {m.note && <p className="mt-1 text-xs text-ink-3">{m.note}</p>}
              </div>
            ))}
          </dl>
        )}
        {quality && (
          <div className="mt-3 rounded-lg border border-warn-line bg-warn-soft px-3 py-2 text-sm text-warn" data-testid="quality">
            <button type="button" className="flex w-full items-center gap-2 text-left" onClick={() => setWarningsOpen(v => !v)} aria-expanded={warningsOpen}>
              <AlertTriangle className="size-4 shrink-0" />
              <span className="flex-1">{quality.count.toLocaleString()} {table.grain === 'opportunity_sku' ? 'product rows' : 'opportunities'} have data checks</span>
              <ChevronDown className={cn('size-4 transition-transform', warningsOpen && 'rotate-180')} />
            </button>
            {warningsOpen && (
              <div className="mt-2 text-[13px]">
                <p>{quality.message}</p>
                {quality.records.length > 0 && <p className="mt-1 text-warn/80">Affected: {quality.records.map(r => [r.opportunity_no, r.product_code].filter(Boolean).join(' · ')).join(', ')}{quality.count > quality.records.length ? ` and ${(quality.count - quality.records.length).toLocaleString()} more` : ''}.</p>}
              </div>
            )}
          </div>
        )}
        {warnings.filter(w => w.code !== 'quality_warning').map(w => <p key={w.code} className="mt-2 text-xs text-ink-3">{w.message}</p>)}
      </header>

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line px-5 py-2.5" data-testid="result-controls">
        {rows && table.views?.available?.length > 1 && (
          <div role="group" aria-label="Detail level" className="inline-flex rounded-lg border border-line p-0.5">
            {(['summary', 'detail'] as ViewName[]).map(v => (
              <button key={v} type="button" onClick={() => onView(v)} aria-pressed={view === v} disabled={loading}
                className={cn('rounded-md px-3 py-1 text-[13px] font-medium transition-colors', view === v ? 'bg-ink text-white' : 'text-ink-2 hover:bg-surface')}>{v === 'summary' ? 'Summary' : 'Detailed'}</button>
            ))}
          </div>
        )}
        {canChart && (
          <div role="group" aria-label="Presentation" className="inline-flex rounded-lg border border-line p-0.5">
            {(['chart', 'table'] as PresentationName[]).map(p => (
              <button key={p} type="button" onClick={() => onPresentation(p)} aria-pressed={presentation === p}
                className={cn('rounded-md px-3 py-1 text-[13px] font-medium transition-colors', presentation === p ? 'bg-ink text-white' : 'text-ink-2 hover:bg-surface')}>{p === 'chart' ? 'Chart' : 'Data'}</button>
            ))}
          </div>
        )}
        {notice && <span className="text-xs text-ink-3">{notice}</span>}
        <span className="ml-auto flex items-center gap-1">
          <Hint text={table.truncated ? `Exports the ${table.rows.length.toLocaleString()} returned rows (of ${table.total_rows.toLocaleString()} matching), all columns, current order.` : 'Exports every returned row and column, exact values, current order.'}>
            <Button variant="ghost" size="xs" onClick={() => download(`b2b-${table.grain}.csv`, csvText(table, table.rows), 'text/csv;charset=utf-8')} data-testid="export"><Download />CSV{table.truncated ? ` (${table.rows.length.toLocaleString()} of ${table.total_rows.toLocaleString()})` : ''}</Button>
          </Hint>
          {!expanded && table.total_rows > 0 && !showCards && <Button variant="outline" size="sm" onClick={onExplore} data-testid="explore"><Maximize2 />Explore results</Button>}
        </span>
      </div>

      <div className="relative px-5 pb-4">
        {showCards ? (
          <dl className="grid gap-3 sm:grid-cols-3" data-testid="value-cards">
            {table.columns.map(c => <div key={c} className="rounded-lg border border-line px-4 py-3"><dt className="text-xs font-medium uppercase tracking-wide text-ink-3">{MEASURE_LABELS[c] ?? label(c)}</dt><dd className="mt-0.5 text-[32px] font-semibold tabular">{formatNumber(table.rows[0]?.[c] ?? null, c === 'amount' || c === 'deal_size' ? 2 : null)}</dd></div>)}
          </dl>
        ) : table.total_rows === 0 ? (
          <p className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-sm text-ink-3" data-testid="empty">No rows match this question.</p>
        ) : (
          <>
            {/* The chart stays mounted at full width while Data is shown (invisible, out of flow), so Chart/Data is a paint change, not an ECharts re-layout. */}
            {canChart && <div className={cn('mb-4', !showChart && 'invisible absolute inset-x-5 top-0 h-0 overflow-hidden')} aria-hidden={!showChart}><ResultChart table={table} measure={measureKey} onMeasure={setMeasure} /></div>}
            {!expanded && <ResultTable table={table} mode="preview" onDetails={setDetails} key={table.view + presentation + table.result_digest} />}
            {!expanded && table.rows.length > PREVIEW_ROWS && <p className="mt-2 text-xs text-ink-3">Showing {PREVIEW_ROWS} of {table.rows.length.toLocaleString()} returned rows{table.truncated ? ` (${table.total_rows.toLocaleString()} match in total)` : ''}. Sorting and export apply to the returned rows.</p>}
          </>
        )}
      </div>
      {answer.suggestions.length > 0 && !expanded && (
        <footer className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3" data-testid="suggestions">
          <span className="text-xs text-ink-3">Ask next</span>
          {answer.suggestions.map(s => <button key={s} type="button" onClick={() => onSuggestion(s)} className="rounded-full border border-line px-3 py-1 text-[13px] text-ink-2 hover:bg-surface hover:text-ink">{s}</button>)}
        </footer>
      )}
      <DetailsPanel table={table} row={details} onClose={() => setDetails(null)} />
    </section>
  );
}
