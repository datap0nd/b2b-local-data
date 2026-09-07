import {useEffect, useState} from 'react';
import {X} from 'lucide-react';
import {Button} from './ui/button';
import {ResultCard, type ResultCardProps} from './ResultCard';
import {ResultTable} from './ResultTable';
import {DetailsPanel} from './DetailsPanel';
import type {Row} from '@/types';

/** A result card opened into the main workspace: the full paginated table, a compact follow-up composer below. */
export function ExpandedAnalysis({onClose, children, ...card}: ResultCardProps & {onClose: () => void; children?: React.ReactNode}) {
  const [pageSize, setPageSize] = useState(50);
  const [details, setDetails] = useState<Row | null>(null);
  useEffect(() => { const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); }; window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey); }, [onClose]);
  const table = card.shown;
  const showCards = table.result_kind === 'aggregate' && table.columns.every(c => ['amount', 'quantity', 'sku_count', 'opportunity_count', 'deal_size'].includes(c)) && card.presentation !== 'table';
  return (
    <div className="flex h-full flex-col" data-testid="expanded">
      <div className="flex items-center gap-3 border-b border-line px-4 py-2">
        <span className="text-sm font-medium">Analysis</span>
        <span className="text-xs text-ink-3">Esc closes</span>
        <Button variant="ghost" size="sm" className="ml-auto" onClick={onClose} aria-label="Close analysis"><X />Close</Button>
      </div>
      <div className="flex-1 overflow-auto px-4 py-4 scroll-thin">
        <div className="mx-auto w-full max-w-[1120px]">
          <ResultCard {...card} expanded />
          {!showCards && table.total_rows > 0 && (
            <div className="mt-4 rounded-card border border-line bg-canvas p-4 shadow-card" data-testid="expanded-table">
              <p className="mb-2 text-sm text-ink-2"><strong className="font-medium text-ink">{table.total_rows.toLocaleString()}</strong> {table.result_kind === 'aggregate' ? 'groups' : table.grain === 'opportunity_sku' ? 'product rows' : 'opportunities'} match{table.truncated ? `; the first ${table.rows.length.toLocaleString()} were returned and can be paged, sorted, and exported here` : ''}.</p>
              <ResultTable table={table} mode="full" pageSize={pageSize} onPageSize={setPageSize} onDetails={setDetails} key={table.view + table.result_digest} />
            </div>
          )}
        </div>
      </div>
      {children && <div className="border-t border-line px-4 py-3">{children}</div>}
      <DetailsPanel table={table} row={details} onClose={() => setDetails(null)} />
    </div>
  );
}
