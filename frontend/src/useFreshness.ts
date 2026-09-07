import {useEffect, useRef, useState} from 'react';
import {api} from './api';
import type {Freshness} from './types';

/** Current dataset only. History and result snapshots never update this state. */
export function useFreshness(authenticated: boolean) {
  const [freshness, setFreshness] = useState<Freshness | null>(null);
  const pending = useRef<Promise<Freshness | null> | null>(null);
  const lastRead = useRef(0);
  useEffect(() => {
    if (!authenticated) { setFreshness(null); lastRead.current = 0; return; }
    let active = true;
    const refresh = async () => {
      if (!pending.current) {
        if (Date.now() - lastRead.current < 60_000) return;
        lastRead.current = Date.now();
        pending.current = api.freshness().then(result => result.freshness).catch(() => null).finally(() => { pending.current = null; });
      }
      const result = await pending.current;
      if (active) setFreshness(result);
    };
    void refresh();
    window.addEventListener('focus', refresh);
    const interval = window.setInterval(refresh, 5 * 60_000);
    return () => { active = false; window.removeEventListener('focus', refresh); window.clearInterval(interval); };
  }, [authenticated]);
  return freshness;
}
