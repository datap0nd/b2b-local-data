import {useEffect, useState} from 'react';
import {Tooltip, TooltipContent, TooltipTrigger} from './ui/tooltip';
import {formatUpdated} from '@/format';
import type {Freshness as FreshnessInfo} from '@/types';

export const FRESH_FOR = 24 * 60 * 60_000;
export function freshnessState(freshness: FreshnessInfo | null | undefined, now: number): 'fresh' | 'stale' | 'unknown' {
  if (freshness?.status !== 'verified' || !freshness.updated_at) return 'unknown';
  const age = now - Date.parse(freshness.updated_at);
  return !Number.isFinite(age) || age < 0 ? 'unknown' : age < FRESH_FOR ? 'fresh' : 'stale';
}

/** One focusable dot by the brand, based only on the verified dataset timestamp. */
export function Freshness({freshness}: {freshness: FreshnessInfo | null | undefined}) {
  const [now, setNow] = useState(Date.now);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const updated = Date.parse(freshness?.updated_at ?? '');
    const tick = () => setNow(Date.now());
    tick();
    const remaining = updated + FRESH_FOR - Date.now();
    const timeout = remaining > 0 && remaining <= FRESH_FOR ? window.setTimeout(tick, remaining) : undefined;
    const interval = window.setInterval(tick, 60_000);
    window.addEventListener('focus', tick);
    return () => { window.clearTimeout(timeout); window.clearInterval(interval); window.removeEventListener('focus', tick); };
  }, [freshness?.updated_at]);
  const status = freshnessState(freshness, now);
  const text = status === 'unknown' ? 'Data update time unavailable.' : `Data updated ${formatUpdated(freshness!.updated_at)?.full}.`;
  return <Tooltip open={open} onOpenChange={setOpen}><TooltipTrigger asChild><button type="button" aria-label={text} onClick={event => { event.preventDefault(); setOpen(value => !value); }} data-testid="freshness" data-status={status} className="grid size-7 shrink-0 place-items-center rounded-full hover:bg-surface-2">
    <span aria-hidden="true" className={`size-2 rounded-full ${status === 'fresh' ? 'bg-emerald-600' : status === 'stale' ? 'bg-red-600' : 'bg-slate-400'}`} />
  </button></TooltipTrigger><TooltipContent>{text}</TooltipContent></Tooltip>;
}
