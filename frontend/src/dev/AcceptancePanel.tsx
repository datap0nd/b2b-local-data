import {useEffect, useRef, useState} from 'react';
import {X} from 'lucide-react';
import {api} from '@/api';
import {Button} from '@/components/ui/button';
import {ResultCard} from '@/components/ResultCard';
import {CHECKS, type Harness, type Observation} from './checks';
import {SYNTHETIC} from './synthetic';
import type {AnswerPayload, PresentationName, TablePayload, ViewName} from '@/types';

interface RunStatus { run: {id: string; status: string; snapshot: {source_name: string; opportunities: number; canonical_parity: boolean}; unqualified_reasons?: string[]; steps: StepRecord[]}; counts: Record<string, number>; next_step: number | null; total_steps: number; full_pass: boolean }
interface StepRecord { id: string; title: string; status: string; prompt: string | null; browser_checks: number[]; interpretation: {ok: boolean; problems: string[]} | null; data_ok: boolean | null; clarification: string | null; returned_plan: unknown; effective_plan: unknown; error: string | null; recovered?: boolean }
interface Rendered { table: TablePayload; answer: AnswerPayload; question: string }

/** Development-only acceptance panel: drives the server-owned suite, renders each result with the production
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

  useEffect(() => { const onError = () => { errors.current++; }; window.addEventListener('error', onError); return () => window.removeEventListener('error', onError); }, []);
  useEffect(() => { api.raw<{suite_version: string; steps: unknown[]; browser_checks: unknown[]}>('/api/test/suite').then(setSuite).catch(e => setCaseText(e instanceof Error ? e.message : 'suite unavailable')); }, []);

  const frame = () => new Promise<void>(r => requestAnimationFrame(() => requestAnimationFrame(() => r())));

  async function renderStep(question: string, table: TablePayload, answer: AnswerPayload) {
    original.current = JSON.parse(JSON.stringify(table));
    setView(table.view); setPresentation(table.presentation);
    setRendered({table, answer, question}); setRenderKey(k => k + 1);
    await frame(); await new Promise(r => setTimeout(r, 120));
  }

  const append = (line: string) => setLog(prev => [line, ...prev].slice(0, 200));

  async function runChecks(step: StepRecord, table: TablePayload | null, runId: string) {
    for (const [n, id] of (step.browser_checks ?? []).entries()) {
      let observation: Observation;
      if (n > 0 && table && rendered) await renderStep(rendered.question, table, rendered.answer);
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
        const result = await api.raw<{step: StepRecord; status: RunStatus; table: TablePayload | null; answer?: {title: string; sentence: string; metrics: []}}>(`/api/test/runs/${current.run.id}/step`, {step: index});
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
    if (running) return; setRunning(true); setCaseText('Synthetic checks (development evidence only)');
    try {
      for (const fixture of SYNTHETIC) {
        const table = fixture.table();
        await renderStep('synthetic: ' + fixture.title, table, {kind: 'table', turn_id: 0, session_id: '', table, variants: {}, answer: {title: fixture.title, sentence: 'Synthetic fixture', metrics: []}, suggestions: []});
        for (const [n, id] of fixture.checks.entries()) {
          let observation: Observation;
          if (n > 0) await renderStep('synthetic: ' + fixture.title, table, {kind: 'table', turn_id: 0, session_id: '', table, variants: {}, answer: {title: fixture.title, sentence: 'Synthetic fixture', metrics: []}, suggestions: []});
          try { observation = await CHECKS[id](harnessFor(table, true)); } catch (error) { observation = {status: 'fail', notes: 'Check threw: ' + (error instanceof Error ? error.message : String(error))}; }
          append(`Synthetic check ${id}: ${observation.status} — [${fixture.id} ${fixture.title}] ${observation.notes ?? ''}${observation.status === 'fail' ? ' observed=' + JSON.stringify(observation.observed).slice(0, 600) : ''}`);
        }
      }
      setCaseText('Synthetic checks finished; they are not recorded on the server and are not live-source coverage.');
    } finally { setRunning(false); }
  }

  const counts = status?.counts;
  return (
    <div className="fixed inset-0 z-50 flex flex-col overflow-hidden bg-surface" role="dialog" aria-label="Acceptance test" data-testid="test-panel">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-canvas px-4 py-2">
        <span className="font-semibold">Acceptance test</span>
        <span className="text-xs text-ink-3" data-testid="test-suite">{suite ? `Suite ${suite.suite_version}: ${suite.steps.length} prompt turns, ${suite.browser_checks.length} browser checks` : 'Loading the suite'}</span>
        <span className="ml-auto flex gap-2">
          <Button size="sm" onClick={start} disabled={running} data-testid="test-start">Run all checks</Button>
          <Button size="sm" variant="outline" onClick={cancel} disabled={!running}>Cancel</Button>
          <Button size="sm" variant="outline" onClick={synthetic} disabled={running} data-testid="test-synthetic">Run synthetic checks</Button>
          {status && <a className="inline-flex h-8 items-center rounded-lg border border-line px-3 text-[13px]" href={`/api/test/runs/${status.run.id}/report`} download>Download report</a>}
          <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close"><X /></Button>
        </span>
      </div>
      <div className="grid gap-2 border-b border-line bg-canvas px-4 py-2 text-sm md:grid-cols-3">
        <p data-testid="test-case"><span className="text-xs uppercase text-ink-3">Case </span>{caseText}</p>
        <p data-testid="test-progress">{counts ? `Passed ${counts.passed} · Failed ${counts.failed} · Review ${counts.review ?? 0} · Blocked ${counts.blocked} · Remaining ${counts.remaining} · Browser ${counts.browser_passed}/${counts.browser_passed + counts.browser_failed + counts.browser_blocked + counts.browser_remaining}` : '—'}</p>
        <p className="text-ink-2">{status ? `Run ${status.run.id.slice(0, 8)} · ${status.run.status}${status.full_pass ? ' · qualified' : ''} · ${status.run.snapshot.source_name} · ${status.run.snapshot.opportunities.toLocaleString()} opportunities · parity ${status.run.snapshot.canonical_parity ? 'ok' : 'FAILED'}` : ''}</p>
      </div>
      <p className="border-b border-line bg-canvas px-4 py-1.5 text-xs text-ink-3">Live checks render each suite result through the production result card. Synthetic checks exercise conditions absent from live data with invented payloads; they are development evidence only and are never recorded as live coverage.</p>
      <div className="max-h-44 overflow-auto border-b border-line bg-canvas px-4 py-2 text-xs scroll-thin" data-testid="test-browser-log" aria-live="polite">
        {log.map((line, i) => <p key={i} className={line.includes(': pass') ? 'text-won' : line.includes(': fail') ? 'text-danger' : 'text-warn'}>{line}</p>)}
      </div>
      <div className="flex-1 overflow-auto p-4 scroll-thin">
        <div ref={host} className="mx-auto w-full max-w-[1120px]" data-testid="test-result">
          {rendered && (
            <div key={renderKey}>
              <ResultCard answer={rendered.answer} shown={presentationTable(rendered.table, presentation)} view={view} presentation={presentation} expanded
                onView={setView} onPresentation={setPresentation} onExplore={() => {}} onSuggestion={() => {}} />
              {rendered.table.total_rows > 0 && rendered.table.result_kind !== 'aggregate' && <div className="mt-4 rounded-card border border-line bg-canvas p-4" data-testid="expanded-table"><ExpandedTable table={rendered.table} /></div>}
              {rendered.table.total_rows > 0 && rendered.table.result_kind === 'aggregate' && rendered.table.chart && <div className="mt-4 rounded-card border border-line bg-canvas p-4" data-testid="expanded-table"><ExpandedTable table={rendered.table} /></div>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function presentationTable(table: TablePayload, presentation: PresentationName): TablePayload { return table.presentation === presentation ? table : {...table, presentation}; }

import {ResultTable} from '@/components/ResultTable';
import {DetailsPanel} from '@/components/DetailsPanel';
import type {Row} from '@/types';
function ExpandedTable({table}: {table: TablePayload}) {
  const [pageSize, setPageSize] = useState(50);
  const [details, setDetails] = useState<Row | null>(null);
  return <><ResultTable table={table} mode="full" pageSize={pageSize} onPageSize={setPageSize} onDetails={setDetails} key={table.result_digest + table.view} /><DetailsPanel table={table} row={details} onClose={() => setDetails(null)} /></>;
}
