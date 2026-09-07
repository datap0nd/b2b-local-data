import {useEffect, useRef, useState} from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import {X} from 'lucide-react';
import {api} from '@/api';
import {Button} from '@/components/ui/button';
import {ResultCard} from '@/components/ResultCard';
import {CHECKS, type Harness, type Observation} from './checks';
import {SYNTHETIC} from './synthetic';
import {measureText, MEASURE_LABELS} from './independent';
import type {AnswerText, AnswerPayload, PresentationName, TablePayload, ViewName} from '@/types';

interface RunStatus { run: {id: string; status: string; snapshot: {source_name: string; opportunities: number; canonical_parity: boolean}; unqualified_reasons?: string[]; steps: StepRecord[]}; counts: Record<string, number>; next_step: number | null; total_steps: number; full_pass: boolean }
interface StepRecord { id: string; title: string; status: string; prompt: string | null; browser_checks: number[]; interpretation: {ok: boolean; problems: string[]} | null; data_ok: boolean | null; clarification: string | null; returned_plan: unknown; effective_plan: unknown; error: string | null; recovered?: boolean }
interface Rendered { table: TablePayload; answer: AnswerPayload; question: string }

/** Acceptance panel: drives the server-owned suite, renders each result with the production
 *  ResultCard (expanded, so the full table is present), runs the browser checks with independent expectations, and
 *  records observations. Synthetic checks are labelled and never sent to the server. */
export default function AcceptancePanel({onClose}: {onClose: () => void}) {
  const [suite, setSuite] = useState<{suite_version: string; steps: unknown[]; browser_checks: unknown[]} | null>(null);
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [caseText, setCaseText] = useState('Not started');
  const [log, setLog] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [rendered, setRendered] = useState<Rendered | null>(null);
  const [renderKey, setRenderKey] = useState(0);
  const [view, setView] = useState<ViewName>('summary');
  const [presentation, setPresentation] = useState<PresentationName>('table');
  const host = useRef<HTMLDivElement>(null);
  const errors = useRef(0);
  const cancelled = useRef(false);
  const original = useRef<TablePayload | null>(null);
  const lastRendered = useRef<Rendered | null>(null);

  useEffect(() => { const onError = () => { errors.current++; }; window.addEventListener('error', onError); return () => window.removeEventListener('error', onError); }, []);
  useEffect(() => { api.raw<{suite_version: string; steps: unknown[]; browser_checks: unknown[]}>('/api/test/suite').then(setSuite).catch(e => setCaseText(e instanceof Error ? e.message : 'suite unavailable')); }, []);

  const frame = () => new Promise<void>(r => requestAnimationFrame(() => requestAnimationFrame(() => r())));

  async function renderStep(question: string, table: TablePayload, answer: AnswerPayload) {
    original.current = JSON.parse(JSON.stringify(table));
    setView(table.view); setPresentation(table.presentation);
    lastRendered.current = {table, answer, question};
    setRendered({table, answer, question}); setRenderKey(k => k + 1);
    await frame(); await new Promise(r => setTimeout(r, 120));
  }

  async function prepareCheck(id: number, table: TablePayload | null) {
    if (!table) return;
    const scalar = table.result_kind === 'aggregate' && table.columns.every(column => MEASURE_LABELS[column]);
    setPresentation(scalar ? 'cards' : id >= 6 && id <= 12 ? 'chart' : 'table');
    await frame(); await new Promise(resolve => setTimeout(resolve, 250));
  }

  const append = (line: string) => setLog(prev => [line, ...prev].slice(0, 200));

  async function runChecks(step: StepRecord, table: TablePayload | null, runId: string) {
    for (const [n, id] of (step.browser_checks ?? []).entries()) {
      if (cancelled.current) break;
      let observation: Observation;
      if (n > 0 && table && lastRendered.current) await renderStep(lastRendered.current.question, table, lastRendered.current.answer);
      await prepareCheck(id, table);
      try {
        if (!table || step.status !== 'pass' && step.status !== 'review' && step.status !== 'fail') observation = {status: 'blocked', notes: `Step ${step.id} produced no rendered result (${step.status}).`};
        else if (id >= 6 && id <= 12 && !table.chart) observation = {status: 'blocked', notes: `Step ${step.id} produced no chart (${step.status}).`};
        else observation = await CHECKS[id](harnessFor(table));
      } catch (error) { observation = {status: 'fail', notes: 'Check threw: ' + (error instanceof Error ? error.message : String(error))}; }
      append(`Live check ${id}: ${observation.status}${observation.notes ? ' — ' + observation.notes : ''}`);
      try { setStatus(await api.raw<RunStatus>(`/api/test/runs/${runId}/browser`, {check: id, status: observation.status, expected: observation.expected ?? null, observed: observation.observed ?? null, notes: observation.notes ?? null})); }
      catch (error) { append(`Could not record check ${id}: ${error instanceof Error ? error.message : error}`); }
    }
  }
  function harnessFor(table: TablePayload, synthetic = false): Harness { return {root: host.current!, table, original: original.current!, errors: () => errors.current, frame, setWidth: px => { if (host.current) host.current.style.width = px ? px + 'px' : ''; }, synthetic}; }

  async function start() {
    if (running) return; setRunning(true); cancelled.current = false; setLog([]); errors.current = 0;
    try {
      let current = await api.raw<RunStatus>('/api/test/runs', {}); setStatus(current);
      while (!cancelled.current && current.run.status === 'running' && current.next_step !== null) {
        const index = current.next_step;
        const result = await api.raw<{step: StepRecord; status: RunStatus; table: TablePayload | null; answer?: AnswerText}>(`/api/test/runs/${current.run.id}/step`, {step: index});
        current = result.status; setStatus(current);
        const step = result.step;
        setCaseText(`${index + 1} of ${current.total_steps} · ${step.id} ${step.title} · ${step.status}${step.recovered ? ' (recovered)' : ''}${step.interpretation && !step.interpretation.ok ? ' — ' + step.interpretation.problems.join('; ') : ''}`);
        if (result.table && !step.clarification) {
          const answer: AnswerPayload = {kind: 'table', turn_id: 0, session_id: '', table: result.table, variants: {}, answer: {title: step.title, sentence: step.prompt ?? '', metrics: []}, suggestions: []};
          if (result.answer) answer.answer = result.answer;
          await renderStep(step.prompt ?? step.title, result.table, answer);
          await runChecks(step, result.table, current.run.id);
        } else { setRendered(null); await runChecks(step, null, current.run.id); }
      }
      if (!cancelled.current) { current = await api.raw<RunStatus>(`/api/test/runs/${current.run.id}`); setStatus(current); setCaseText(current.run.status === 'complete' ? `Finished: ${current.full_pass ? 'qualified full pass' : 'not qualified'}${current.run.unqualified_reasons?.length ? ' — ' + current.run.unqualified_reasons.join('; ') : ''}` : `Run ${current.run.status}`); }
    } catch (error) { setCaseText('Stopped: ' + (error instanceof Error ? error.message : String(error))); }
    finally { setRunning(false); }
  }

  async function cancel() { cancelled.current = true; if (status) { try { setStatus(await api.raw<RunStatus>(`/api/test/runs/${status.run.id}/cancel`, {})); } catch { /* ignore */ } } }

  async function synthetic() {
    if (running) return; setRunning(true); cancelled.current = false; setLog([]); setCaseText('Synthetic checks (development evidence only)');
    try {
      for (const fixture of SYNTHETIC) {
        if (cancelled.current) break;
        const table = fixture.table();
        await renderStep('synthetic: ' + fixture.title, table, {kind: 'table', turn_id: 0, session_id: '', table, variants: {}, answer: syntheticAnswer(fixture.title, table), suggestions: []});
        for (const [n, id] of fixture.checks.entries()) {
          if (cancelled.current) break;
          let observation: Observation;
          if (n > 0) await renderStep('synthetic: ' + fixture.title, table, {kind: 'table', turn_id: 0, session_id: '', table, variants: {}, answer: syntheticAnswer(fixture.title, table), suggestions: []});
          await prepareCheck(id, table);
          try { observation = await CHECKS[id](harnessFor(table, true)); } catch (error) { observation = {status: 'fail', notes: 'Check threw: ' + (error instanceof Error ? error.message : String(error))}; }
          append(`Synthetic check ${id}: ${observation.status} — [${fixture.id} ${fixture.title}] ${observation.notes ?? ''}${observation.status === 'fail' ? ' observed=' + JSON.stringify(observation.observed).slice(0, 600) : ''}`);
        }
      }
      setCaseText(cancelled.current ? 'Synthetic checks cancelled.' : 'Synthetic checks finished; they are not recorded on the server and are not live-source coverage.');
    } finally { setRunning(false); }
  }

  const counts = status?.counts;
  return (
    <DialogPrimitive.Root open onOpenChange={open => { if (!open && !running) onClose(); }}><DialogPrimitive.Portal><DialogPrimitive.Content className="fixed inset-0 z-50 flex flex-col overflow-hidden bg-surface" aria-describedby={undefined} data-testid="test-panel" onEscapeKeyDown={event => { if (running) event.preventDefault(); }}>
      <DialogPrimitive.Title className="sr-only">Acceptance test</DialogPrimitive.Title>
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-canvas px-4 py-2">
        <span className="font-semibold">Acceptance test</span>
        <span className="text-xs text-ink-3" data-testid="test-suite">{suite ? `Suite ${suite.suite_version}: ${suite.steps.length} prompt turns, ${suite.browser_checks.length} browser checks` : 'Loading the suite'}</span>
        <span className="ml-auto flex flex-wrap gap-2">
          <Button size="sm" onClick={start} disabled={running || !suite} data-testid="test-start">Run tests</Button>
          <Button size="sm" variant="outline" onClick={cancel} disabled={!running}>Cancel</Button>
          <Button size="sm" variant="outline" onClick={synthetic} disabled={running} data-testid="test-synthetic">Run synthetic checks</Button>
          {status && <a className="inline-flex h-8 items-center rounded-lg border border-line px-3 text-[13px]" href={`/api/test/runs/${status.run.id}/report`} download>Download report</a>}
          <Button size="sm" variant="ghost" onClick={onClose} disabled={running} aria-label="Close"><X /></Button>
        </span>
      </div>
      <div className="grid gap-2 border-b border-line bg-canvas px-4 py-2 text-sm md:grid-cols-3">
        <p data-testid="test-case"><span className="text-xs uppercase text-ink-3">Case </span>{caseText}</p>
        <p data-testid="test-progress">{counts ? `Passed ${counts.passed} · Failed ${counts.failed} · Review ${counts.review ?? 0} · Blocked ${counts.blocked} · Remaining ${counts.remaining} · Browser ${counts.browser_passed}/${counts.browser_passed + counts.browser_failed + counts.browser_blocked + counts.browser_remaining}` : '—'}</p>
        <p className="text-ink-2">{status ? `Run ${status.run.id.slice(0, 8)} · ${status.run.status}${status.full_pass ? ' · qualified' : ''} · ${status.run.snapshot.source_name} · ${status.run.snapshot.opportunities.toLocaleString()} opportunities · parity ${status.run.snapshot.canonical_parity ? 'ok' : 'FAILED'}` : ''}</p>
      </div>
      <p className="border-b border-line bg-canvas px-4 py-1.5 text-xs text-ink-3">Run tests uses the configured data and model and shows each result here. Synthetic checks exercise conditions absent from live data with invented payloads; they are development evidence only and are never recorded as live coverage.</p>
      <div className="max-h-44 overflow-auto border-b border-line bg-canvas px-4 py-2 text-xs scroll-thin" data-testid="test-browser-log" aria-live="polite">
        {log.map((line, i) => <p key={i} className={line.includes(': pass') ? 'text-won' : line.includes(': fail') ? 'text-danger' : 'text-warn'}>{line}</p>)}
      </div>
      <div className="flex-1 overflow-auto p-4 scroll-thin">
        <div ref={host} className="mx-auto w-full max-w-[1120px]" data-testid="test-result">
          {rendered && (
            <div key={renderKey}>
              <ResultCard answer={rendered.answer} shown={presentationTable(rendered.table, presentation)} view={view} presentation={presentation} expanded
                onView={setView} onPresentation={setPresentation} onExplore={() => {}} onSuggestion={() => {}} />
            </div>
          )}
        </div>
      </div>
    </DialogPrimitive.Content></DialogPrimitive.Portal></DialogPrimitive.Root>
  );
}

function presentationTable(table: TablePayload, presentation: PresentationName): TablePayload { return table.presentation === presentation ? table : {...table, presentation}; }

function syntheticAnswer(title: string, table: TablePayload): AnswerText {
  const scalar = table.result_kind === 'aggregate' && table.columns.every(column => MEASURE_LABELS[column]);
  return {title, sentence: '', metrics: scalar ? table.columns.map(column => ({label: MEASURE_LABELS[column], raw: table.rows[0]?.[column] ?? null, value: measureText(table, column, table.rows[0]?.[column] ?? null)})) : []};
}
