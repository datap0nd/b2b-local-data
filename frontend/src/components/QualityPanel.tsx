import {useMemo, useState} from 'react';
import {ChevronLeft, ChevronRight, Download, Search} from 'lucide-react';
import {Dialog, DialogContent} from './ui/dialog';
import {Button} from './ui/button';
import {csvText, formatNumber, label} from '@/format';
import {download} from '@/lib/utils';
import type {QualityIssue, QualityWarning, Row} from '@/types';

const PAGE_SIZE = 20;
const valuesText = (values: unknown): string => values == null ? '' : typeof values === 'object' ? JSON.stringify(values) : String(values);

/** Evidence comes exclusively from the saved answer. No live query can replace it. */
export function qualityRows(warning: QualityWarning): Row[] {
  return warning.records.flatMap(record => (record.issues?.length ? record.issues : [{code: 'legacy', message: 'Detailed reasons were not saved with this answer.'}]).map(issue => ({
    opportunity_no: record.opportunity_no,
    opportunity_name: record.opportunity_name ?? null,
    product_code: record.product_code ?? null,
    reason: issue.message,
    field: issue.field ?? null,
    values: valuesText(issue.values),
    product_total: issue.product_total ?? null,
    exported_total: issue.exported_total ?? null,
    difference: issue.difference ?? null,
    currency: issue.currency ?? null,
    inclusion: 'Included in this answer',
  })));
}

function Issue({issue}: {issue: QualityIssue}) {
  const hasAmounts = issue.product_total != null || issue.exported_total != null || issue.difference != null;
  return <div className="space-y-1">
    <p className="font-medium text-ink">{issue.message}</p>
    {issue.field && <p className="text-xs text-ink-3">Field: {label(issue.field)}</p>}
    {hasAmounts && <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs tabular">
      <dt className="text-ink-3">Product total</dt><dd>{formatNumber(issue.product_total ?? null)} {issue.currency}</dd>
      <dt className="text-ink-3">Exported total</dt><dd>{formatNumber(issue.exported_total ?? null)} {issue.currency}</dd>
      <dt className="text-ink-3">Difference</dt><dd>{formatNumber(issue.difference ?? null)} {issue.currency}</dd>
    </dl>}
    {issue.values != null && <p className="break-words text-xs text-ink-2">Values: {valuesText(issue.values)}</p>}
  </div>;
}

export function QualityPanel({warning, open, onClose}: {warning: QualityWarning; open: boolean; onClose: () => void}) {
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);
  const records = useMemo(() => {
    const search = query.trim().toLocaleLowerCase();
    return warning.records.filter(record => !search || JSON.stringify(record).toLocaleLowerCase().includes(search));
  }, [warning, query]);
  const totalPages = Math.max(1, Math.ceil(records.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages - 1);
  const rows = records.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);
  const complete = warning.records.length >= warning.count;
  function exportReview() {
    const columns = ['opportunity_no', 'opportunity_name', 'product_code', 'reason', 'field', 'values', 'product_total', 'exported_total', 'difference', 'currency', 'inclusion'];
    download('b2b-quality-review.csv', csvText({columns, column_types: {product_total: 'number', exported_total: 'number', difference: 'number'}}, qualityRows(warning)), 'text/csv;charset=utf-8');
  }
  return <Dialog open={open} onOpenChange={value => { if (!value) onClose(); }}>
    <DialogContent side="right" title="Opportunity review" className="w-[min(920px,100vw)]" aria-describedby="quality-intro">
      <div data-testid="quality-panel" className="space-y-5">
        <div id="quality-intro" className="space-y-2 text-sm text-ink-2">
          <p>{warning.message}</p>
          <p>These opportunities remain included in this answer. A flag identifies something to review; it does not establish which source value is correct.</p>
          {!complete && <p className="rounded-lg bg-warn-soft p-3 text-warn" data-testid="quality-incomplete">This saved answer contains details for {warning.records.length.toLocaleString()} of {warning.count.toLocaleString()} affected records. Run the question again to obtain a current review.</p>}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="relative min-w-48 flex-1"><Search aria-hidden="true" className="absolute left-3 top-2.5 size-4 text-ink-3" /><input aria-label="Search quality review" value={query} onChange={event => { setQuery(event.target.value); setPage(0); }} placeholder="Search opportunity, field or reason" className="h-9 w-full rounded-lg border border-line bg-canvas pl-9 pr-3 text-sm" /></label>
          <Button size="sm" variant="outline" disabled={!warning.records.length} onClick={exportReview}><Download />Download review</Button>
        </div>
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[560px] text-left text-sm" data-testid="quality-table">
            <thead className="bg-surface text-xs text-ink-3"><tr><th className="w-[32%] px-4 py-3 font-medium">Opportunity</th><th className="px-4 py-3 font-medium">Review reason and evidence</th></tr></thead>
            <tbody>{rows.map((record, index) => <tr key={`${record.opportunity_no}:${record.product_code ?? ''}:${index}`} className="border-t border-line align-top">
              <td className="px-4 py-4"><p className="font-medium">{record.opportunity_name}</p><p className="font-mono text-xs text-ink-2">{String(record.opportunity_no ?? 'Unknown opportunity')}</p>{record.product_code != null && <p className="mt-1 text-xs text-ink-3">SKU: {String(record.product_code)}</p>}<span className="mt-2 inline-block text-xs text-ink-3">Included in answer</span></td>
              <td className="space-y-4 px-4 py-4">{record.issues?.length ? record.issues.map((issue, i) => <Issue key={i} issue={issue} />) : <p className="text-ink-3">Detailed reasons were not saved with this answer.</p>}</td>
            </tr>)}</tbody>
          </table>
          {rows.length === 0 && <p className="p-8 text-center text-sm text-ink-3">{warning.records.length ? 'No review records match this search.' : 'No detailed evidence was saved with this answer.'}</p>}
        </div>
        <div className="flex items-center gap-2 text-xs text-ink-3"><span aria-live="polite">{records.length.toLocaleString()} records · Page {currentPage + 1} of {totalPages}</span><Button className="ml-auto" variant="outline" size="icon-sm" aria-label="Previous review page" disabled={currentPage === 0} onClick={() => setPage(value => value - 1)}><ChevronLeft /></Button><Button variant="outline" size="icon-sm" aria-label="Next review page" disabled={currentPage + 1 >= totalPages} onClick={() => setPage(value => value + 1)}><ChevronRight /></Button></div>
      </div>
    </DialogContent>
  </Dialog>;
}
