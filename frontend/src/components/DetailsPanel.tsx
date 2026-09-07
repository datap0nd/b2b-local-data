import {Dialog, DialogContent} from './ui/dialog';
import {cellText, headerLabel} from '@/format';
import type {Row, TablePayload} from '@/types';

/** Full names and every returned field of one row, in an accessible side panel. */
export function DetailsPanel({table, row, onClose}: {table: TablePayload; row: Row | null; onClose: () => void}) {
  const key = row ? String(row.opportunity_no ?? '') + (row.product_code != null ? ` · ${row.product_code}` : '') : '';
  return (
    <Dialog open={row !== null} onOpenChange={open => { if (!open) onClose(); }}>
      {row && (
        <DialogContent side="right" title={key || 'Row details'} aria-describedby={undefined}>
          <dl className="grid grid-cols-[minmax(120px,max-content)_1fr] gap-x-4 gap-y-2 text-sm" data-testid="row-details">
            {table.columns.map(column => (
              <div key={column} className="contents">
                <dt className="text-ink-3">{headerLabel(table, column)}</dt>
                <dd className={row[column] == null ? 'text-ink-3' : 'break-words'}>{cellText(table, row, column)}</dd>
              </div>
            ))}
          </dl>
        </DialogContent>
      )}
    </Dialog>
  );
}
