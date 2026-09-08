import {useEffect, useRef, useState} from 'react';
import {Button} from '@/components/ui/button';
import {ResultCard} from '@/components/ResultCard';
import {CHECKS, type Harness} from './checks';
import {SYNTHETIC} from './synthetic';
import {measureText, MEASURE_LABELS} from './independent';
import type {AnswerPayload, PresentationName, TablePayload, ViewName} from '@/types';

/** Explicit synthetic-only regression surface. Never calls the backend or model. */
export default function SyntheticPanel({onClose}: {onClose: () => void}) {
  const [table, setTable] = useState<TablePayload | null>(null);
  const [view, setView] = useState<ViewName>('summary');
  const [presentation, setPresentation] = useState<PresentationName>('table');
  const [key, setKey] = useState(0), [running, setRunning] = useState(true);
  const [message, setMessage] = useState('Synthetic checks running…');
  const [log, setLog] = useState<string[]>([]);
  const host = useRef<HTMLDivElement>(null);
  const begun = useRef(false), errors = useRef(0);
  const frame = () => new Promise<void>(r => requestAnimationFrame(() => requestAnimationFrame(() => r())));
  const settle = async () => { await frame(); await new Promise(r => setTimeout(r, 300)); };
  useEffect(() => {
    if (begun.current) return; begun.current = true;
    const onError = () => errors.current++;
    window.addEventListener('error', onError);
    void (async () => {
      try {
        for (const fixture of SYNTHETIC) {
          const original = fixture.table();
          for (const id of fixture.checks) {
            const scalar = original.result_kind === 'aggregate' && original.columns.every(c => MEASURE_LABELS[c]);
            setTable(original); setView(original.view); setPresentation(scalar ? 'cards' : id >= 6 && id <= 12 ? 'chart' : 'table'); setKey(k => k + 1); await settle();
            const harness: Harness = {root: host.current!, table: original, original: structuredClone(original), frame, errors: () => errors.current, setWidth: width => { host.current!.style.width = width ? `${width}px` : ''; }, synthetic: true};
            try { const result = await CHECKS[id](harness); setLog(prev => [...prev, `Synthetic check ${id}: ${result.status} · ${fixture.title} · ${result.notes ?? ''}`]); }
            catch (e) { setLog(prev => [...prev, `Synthetic check ${id}: fail · ${String(e)}`]); }
          }
        }
        setMessage('Synthetic checks finished; development evidence only.');
      } finally { setRunning(false); window.removeEventListener('error', onError); }
    })();
  }, []);
  const answer: AnswerPayload | null = table && {kind: 'table', turn_id: 0, session_id: '', table, variants: {}, suggestions: [], answer: {title: 'Synthetic fixture', sentence: '', metrics: table.result_kind === 'aggregate' && table.columns.every(c => MEASURE_LABELS[c]) ? table.columns.map(c => ({label: MEASURE_LABELS[c], raw: table.rows[0]?.[c] ?? null, value: measureText(table, c, table.rows[0]?.[c] ?? null)})) : []}};
  return <div className="fixed inset-0 z-50 flex flex-col overflow-auto bg-page p-4" data-testid="test-panel"><div className="flex gap-3"><strong data-testid="test-case">{message}</strong><Button disabled={running} onClick={onClose}>Back to live tests</Button></div><div className="max-h-44 overflow-auto text-xs" data-testid="test-browser-log">{log.map((line, i) => <p key={i}>{line}</p>)}</div><div ref={host} className="mx-auto w-full max-w-[1120px]">{table && answer && <ResultCard key={key} answer={answer} shown={{...table, presentation}} view={view} presentation={presentation} expanded onView={setView} onPresentation={setPresentation} onExplore={() => {}} onSuggestion={() => {}} />}</div></div>;
}
