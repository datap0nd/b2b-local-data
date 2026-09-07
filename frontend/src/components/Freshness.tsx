import {Clock} from 'lucide-react';
import {Hint} from './ui/tooltip';
import {formatUpdated} from '@/format';
import type {Freshness as FreshnessInfo} from '@/types';

/** "Data updated 7 Sep, 19:20" from the verified snapshot time; never the load time or a record's modification date. */
export function Freshness({freshness}: {freshness: FreshnessInfo | null | undefined}) {
  if (!freshness || freshness.status !== 'verified' || !freshness.updated_at) {
    return (
      <Hint text={freshness?.reason ?? 'No verified data-update time exists for this snapshot.'}>
        <span className="inline-flex items-center gap-1 text-xs text-ink-3" data-testid="freshness" data-status="unavailable"><Clock className="size-3.5" />Data update time unavailable</span>
      </Hint>
    );
  }
  const shown = formatUpdated(freshness.updated_at);
  return (
    <Hint text={`${shown?.full} (source: ${freshness.method === 'commit_timestamp' ? 'database commit time' : 'load record'}${freshness.reused ? ', verified earlier for the same dataset' : ''})`}>
      <span className="inline-flex items-center gap-1 text-xs text-ink-3" data-testid="freshness" data-status="verified"><Clock className="size-3.5" />Data updated {shown?.short}</span>
    </Hint>
  );
}
