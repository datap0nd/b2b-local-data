import {lazy, Suspense, useEffect, useRef, useState} from 'react';
import {api} from '@/api';
import {changeAnswerView, changeAnswerPresentation} from '@/answerActions';
import {TestScope} from '@/TestScope';
import {Button} from '@/components/ui/button';
import {Composer} from '@/components/Composer';
import {Conversation} from '@/components/Conversation';
import {ExpandedAnalysis} from '@/components/ExpandedAnalysis';
import {Sidebar} from '@/components/Sidebar';
import {useFreshness} from '@/useFreshness';
import {CHECKS, type Harness, type Observation} from './checks';
import {captureElement, scenarioPng} from './evidence';
import {TestVerdict} from './TestVerdict';
import type {AskResponse, ConversationTurn, PresentationName, TablePayload, ViewName} from '@/types';

interface Step {id: string; scenario_id: string; turn_number: number; prompt: string | null; title: string; status: string; error: string | null; browser_checks: number[]; ui_actions: string[]; data_ok?: boolean; data?: {ok: boolean; differences?: unknown[]}; result?: {total_rows: number; rows: unknown[]; expected?: {total_rows: number; rows: unknown[]}}; interpretation?: {ok: boolean; problems: string[]}; expected: string}
interface Scenario {id: string; number: number; title: string; step_ids: string[]; actions: string[]; png: unknown; ui: Observation | null}
interface Status {run: {id: string; status: string; steps: Step[]; scenarios: Scenario[]}; next_step: number | null; total_steps: number; counts: Record<string, number>; full_pass: boolean}
interface Suite {scenario_count: number; suite_version: string; steps: Step[]}
const sleep = (ms: number) => new Promise<void>(r => setTimeout(r, ms));
const frame = () => new Promise<void>(r => requestAnimationFrame(() => requestAnimationFrame(() => r())));
const SyntheticPanel = lazy(() => import('./SyntheticPanel'));

function responseTurn(step: Step, reply: AskResponse | null): ConversationTurn {
  if (!reply) return {id: step.id, question: step.prompt ?? step.title, assistant: {status: 'error', message: `${step.status}: ${step.error ?? 'No model response was produced.'}`, retry: () => {}}};
  if (reply.kind === 'clarify') return {id: step.id, question: step.prompt ?? step.title, assistant: {status: 'clarify', text: reply.question, suggestions: reply.suggestions}};
  return {id: step.id, question: step.prompt ?? step.title, assistant: {status: 'answer', answer: reply, shown: reply.table, view: reply.table.view, presentation: reply.table.presentation}};
}

/** Same production components and answer actions, with an explicitly isolated API scope. */
export default function AcceptancePanel({onClose}: {onClose: () => void}) {
  const [suite, setSuite] = useState<Suite | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const turnsRef = useRef<ConversationTurn[]>([]);
  const [expanded, setExpanded] = useState<string | number | null>(null);
  const [draft, setDraft] = useState('');
  const [verdict, setVerdict] = useState<Step | null>(null);
  const [running, setRunning] = useState(false);
  const [paused, setPaused] = useState(false);
  const pauseRef = useRef(false), stopRef = useRef(false), active = useRef(false);
  const [hold, setHold] = useState(2);
  const [message, setMessage] = useState('Ready. Runs use the configured data and local model.');
  const [current, setCurrent] = useState('Not started');
  const [syntheticOpen, setSyntheticOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [narrow, setNarrow] = useState(() => window.innerWidth < 900);
  const [batch, setBatch] = useState(0);
  const [copyText, setCopyText] = useState('');
  const [captureRetry, setCaptureRetry] = useState(false);
  const retryRef = useRef<(() => Promise<void>) | null>(null);
  const surface = useRef<HTMLDivElement>(null), errors = useRef(0);
  const freshness = useFreshness(true);
  const runRef = useRef('');
  const actionInFlight = useRef<Promise<void>>(Promise.resolve());
  const setConversation = (next: ConversationTurn[]) => { turnsRef.current = next; setTurns(next); };

  useEffect(() => {
    api.raw<Suite>('/api/test/suite').then(setSuite).catch(e => setMessage(String(e)));
    const retained = localStorage.getItem('b2b-test-run');
    if (retained) api.raw<Status>(`/api/test/runs/${retained}`).then(value => {
      setStatus(value); runRef.current = value.run.id;
      setMessage(value.run.status === 'running' ? 'Saved test run found. Resume continues without repeating completed model calls.' : `Previous test run: ${value.run.status}. Reports remain available.`);
    }).catch(() => localStorage.removeItem('b2b-test-run'));
  }, []);
  useEffect(() => { const resized = () => setNarrow(window.innerWidth < 900); window.addEventListener('resize', resized); return () => window.removeEventListener('resize', resized); }, []);
  useEffect(() => {
    const error = () => { errors.current++; };
    const leave = (e: BeforeUnloadEvent) => { if (active.current) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('error', error); window.addEventListener('unhandledrejection', error); window.addEventListener('beforeunload', leave);
    return () => { window.removeEventListener('error', error); window.removeEventListener('unhandledrejection', error); window.removeEventListener('beforeunload', leave); };
  }, []);

  async function checkpoint(delay = 0) {
    let elapsed = 0;
    while (elapsed < delay || pauseRef.current) {
      if (stopRef.current) throw new Error('Stopped by user.');
      await sleep(100); if (!pauseRef.current) elapsed += 100;
    }
    if (stopRef.current) throw new Error('Stopped by user.');
  }
  async function settled() { await document.fonts.ready; await frame(); await sleep(300); }
  function updateTurn(id: string | number, update: (t: ConversationTurn) => ConversationTurn) { setConversation(turnsRef.current.map(t => t.id === id ? update(t) : t)); }
  const onView = (t: ConversationTurn, v: ViewName) => {
    if (t.assistant.status !== 'answer') return;
    const a = t.assistant.answer;
    actionInFlight.current = changeAnswerView(t, v, next => updateTurn(t.id, () => next), () => api.raw<{table: TablePayload}>(`/api/test/runs/${runRef.current}/sessions/${a.session_id}/turns/${a.turn_id}/actions`, {action: 'view', view: v}));
  };
  const onPresentation = (t: ConversationTurn, p: PresentationName) => updateTurn(t.id, old => changeAnswerPresentation(old, p));
  function button(root: ParentNode, name: string) { return Array.from(root.querySelectorAll<HTMLButtonElement>('button')).find(b => b.textContent?.trim() === name || b.getAttribute('aria-label') === name); }

  async function check(step: Step, turn: ConversationTurn, id: number): Promise<Observation> {
    if (turn.assistant.status !== 'answer') return {status: 'blocked', notes: 'No data answer to inspect.'};
    const table = turn.assistant.shown;
    setExpanded(turn.id); await settled();
    const host = surface.current!;
    const harness: Harness = {root: host, table, original: structuredClone(table), errors: () => errors.current, frame: async () => { await frame(); await actionInFlight.current; await frame(); },
      setWidth: width => { host.style.width = width ? `${width}px` : ''; }};
    let observation: Observation;
    try { observation = await CHECKS[id](harness); }
    catch (e) { observation = {status: 'fail', notes: String(e)}; }
    finally { host.style.width = ''; }
    if (step.browser_checks.includes(id)) await api.raw(`/api/test/runs/${runRef.current}/browser`, {check: id, ...observation});
    return observation;
  }

  async function showActions(step: Step, turn: ConversationTurn, tiles: HTMLCanvasElement[], notes: string[]) {
    if (turn.assistant.status !== 'answer') {
      for (const id of step.browser_checks) await api.raw(`/api/test/runs/${runRef.current}/browser`, {check: id, status: 'blocked', notes: 'No data answer.'});
      return;
    }
    const table = turn.assistant.shown;
    const chartCheck = table.chart ? ({bar: 6, line: 7, area: 8, scatter: 9} as Record<string, number>)[table.chart.type] : undefined;
    const ids = new Set(step.browser_checks);
    if (chartCheck && table.presentation === 'chart') ids.add(chartCheck);
    if (step.ui_actions?.includes('sort')) { ids.add(3); ids.add(4); }
    if (step.ui_actions?.includes('paginate')) ids.add(table.view === 'summary' ? 1 : 2);
    if (step.ui_actions?.includes('export')) ids.add(5);
    for (const id of ids) {
      await checkpoint();
      const observation = await check(step, turn, id);
      notes.push(`Check ${id}: ${observation.status} ${observation.notes ?? ''}`);
      tiles.push(...await captureElement(surface.current!));
      await checkpoint(hold * 1000);
    }
    setExpanded(null); await settled();
    for (const name of step.ui_actions ?? []) {
      await checkpoint();
      const root = surface.current!;
      if (name === 'chart-data' && table.chart) {
        const data = button(root, 'Data'); if (!data) throw new Error('Data control is missing.');
        data.click(); await settled();
        if (!root.querySelector('[data-testid="primary-result"] [data-testid="result-table"]')) notes.push('fail: Data view did not render a table.');
        tiles.push(...await captureElement(root)); await checkpoint(hold * 1000);
        button(root, 'Chart')?.click(); await settled();
      } else if (name === 'explore') {
        const explore = button(root, 'Explore results');
        if (explore) { explore.click(); await settled(); tiles.push(...await captureElement(root)); await checkpoint(hold * 1000); setExpanded(null); await settled(); }
        else notes.push('blocked: no Explore results control for this answer.');
      } else if (name === 'resize') {
        root.style.width = '390px'; window.dispatchEvent(new Event('resize')); await settled();
        const chart = root.querySelector('[data-testid="result-chart"]');
        if (chart && chart.getBoundingClientRect().width > 392) notes.push('fail: chart overflows narrow viewport.');
        tiles.push(...await captureElement(root)); await checkpoint(hold * 1000); root.style.width = ''; window.dispatchEvent(new Event('resize')); await settled();
      } else if (name === 'reopen') {
        const payload = await api.raw<AskResponse>(`/api/test/runs/${runRef.current}/payloads/${step.id}`);
        if (payload.kind !== 'table' || payload.table.result_digest !== table.result_digest) notes.push('fail: reopened answer changed its result digest.');
        updateTurn(turn.id, () => responseTurn(step, payload)); await settled();
      } else if (name === 'supporting') {
        const open = root.querySelector<HTMLButtonElement>('[data-testid="supporting-explore"]');
        if (open) {
          open.click(); await settled();
          for (let n = 0; n < 100 && document.querySelector('[data-testid="supporting-panel"]')?.textContent?.includes('Loading'); n++) await sleep(100);
          const full = document.querySelector<HTMLElement>('[data-testid="supporting-panel"]');
          if (full) { tiles.push(...await captureElement(full)); await checkpoint(hold * 1000); }
          else notes.push('fail: supporting records did not open.');
          document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await settled();
        } else notes.push('blocked: supporting records control unavailable.');
      } else if (name === 'quality') {
        const quality = root.querySelector<HTMLButtonElement>('[data-testid="quality"]');
        if (quality) { quality.click(); await settled(); const dialog = document.querySelector<HTMLElement>('[role="dialog"]'); if (dialog) tiles.push(...await captureElement(dialog)); document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); }
        else notes.push('blocked: no quality review for this snapshot.');
      }
    }
    notes.push(`Browser errors: ${errors.current}`);
    if (errors.current) notes.push('fail: browser error observed.');
  }

  async function upload(run: string, scenario: string, blob: Blob) {
    const result = await fetch(`/api/test/runs/${run}/scenarios/${scenario}/png`, {method: 'POST', headers: {'Content-Type': 'image/png'}, body: blob});
    if (!result.ok) throw new Error((await result.json()).error ?? 'PNG save failed.');
    setStatus(await result.json());
  }

  async function execute(existing?: Status) {
    if (active.current) return;
    active.current = true; setRunning(true); stopRef.current = false; pauseRef.current = false; setPaused(false); setCaptureRetry(false);
    try {
      let state = existing ?? await api.raw<Status>('/api/test/runs', {});
      runRef.current = state.run.id; localStorage.setItem('b2b-test-run', state.run.id); setStatus(state);
      for (const scenario of state.run.scenarios) {
        if (scenario.png) continue;
        await checkpoint(); setConversation([]); setExpanded(null); errors.current = 0;
        setCurrent(`${scenario.number}/200 · ${scenario.id} · ${scenario.title}`);
        const tiles: HTMLCanvasElement[] = [], notes: string[] = [];
        for (const stepId of scenario.step_ids) {
          const index = state.run.steps.findIndex(s => s.id === stepId);
          let step = state.run.steps[index];
          await checkpoint(); setVerdict(null); setDraft(step.prompt ?? ''); setMessage(`${scenario.id} · turn ${step.turn_number}: ${step.prompt ?? step.title}`); await settled();
          setConversation([...turnsRef.current, {id: step.id, question: step.prompt ?? step.title, assistant: {status: 'pending'}}]); setDraft(''); await frame();
          let payload: AskResponse | null;
          if (state.next_step !== null && index >= state.next_step) {
            const result = await api.raw<{step: Step; status: Status; payload: AskResponse | null}>(`/api/test/runs/${state.run.id}/step`, {step: index});
            state = result.status; step = result.step; payload = result.payload;
          } else payload = await api.raw<AskResponse | null>(`/api/test/runs/${state.run.id}/payloads/${step.id}`);
          let readingPosition: number | null = null;
          if (step.ui_actions?.includes('scrollback') && step.turn_number > 1) {
            // Stay in the real loading state while exercising the reader's scroll position.
            await sleep(1000);
            const scroller = surface.current!.querySelector<HTMLElement>('[data-testid="conversation"]');
            if (scroller && scroller.scrollHeight - scroller.clientHeight > 80) {
              scroller.scrollTop = 0;
              scroller.dispatchEvent(new Event('scroll', {bubbles: true}));
              await settled(); readingPosition = scroller.scrollTop;
            } else notes.push('blocked: scrollback requires an overflowing conversation.');
          }
          const completed = responseTurn(step, payload);
          updateTurn(step.id, () => completed); setVerdict(step); setStatus(state); await settled();
          if (readingPosition !== null) {
            const scroller = surface.current!.querySelector<HTMLElement>('[data-testid="conversation"]')!;
            const latest = surface.current!.querySelector<HTMLButtonElement>('[data-testid="new-answer"]');
            if (Math.abs(scroller.scrollTop - readingPosition) > 2) notes.push('fail: new response displaced the reader while scrolled back.');
            if (!latest) notes.push('fail: New answer control missing while scrolled back.');
            tiles.push(...await captureElement(surface.current!)); await checkpoint(hold * 1000);
            latest?.click(); await sleep(1000); await settled();
          }
          notes.push(`${step.id}: ${step.status}; interpretation=${step.interpretation?.ok ?? 'unavailable'}; data=${step.data_ok ?? step.data?.ok ?? 'see report'}; ${(step.interpretation?.problems ?? []).join('; ')} ${step.error ?? ''}`);
          if (step.result?.expected) notes.push(`Matching rows: expected ${step.result.expected.total_rows}; observed ${step.result.total_rows}.`);
          if (step.data?.differences?.length) notes.push('Differences: ' + JSON.stringify(step.data.differences.slice(0, 3)).slice(0, 1400));
          if (payload?.kind === 'table' && payload.table.result_kind === 'aggregate' && step.result?.expected) notes.push('Expected values (first 3 groups): ' + JSON.stringify(step.result.expected.rows.slice(0, 3)).slice(0, 1200));
          // Check natural headline visibility before scrolling for evidence.
          const article = surface.current!.querySelector<HTMLElement>('[data-testid="turn"]:last-child');
          if (article) {
            const headline = article.querySelector('[data-testid="answer-title"]');
            const viewport = surface.current!.getBoundingClientRect();
            if (headline && (headline.getBoundingClientRect().top < viewport.top || headline.getBoundingClientRect().bottom > viewport.bottom)) notes.push('fail: answer headline not visible after completion.');
            tiles.push(...await captureElement(article));
            await checkpoint(hold * 1000);
            // Additional readable views for the live recording, after natural scroll assertions.
            for (let y = viewport.height; y < article.scrollHeight; y += viewport.height * .8) {
              const scroller = surface.current!.querySelector<HTMLElement>('[data-testid="conversation"]');
              if (scroller) { scroller.scrollTop += viewport.height * .8; await settled(); await checkpoint(hold * 1000); }
            }
          }
          try { await showActions(step, completed, tiles, notes); }
          catch (e) { if (stopRef.current) throw e; notes.push('fail: ' + String(e)); setExpanded(null); }
        }
        const observation = {status: notes.some(n => /\bfail\b/i.test(n)) ? 'fail' : notes.some(n => /\bblocked\b/i.test(n)) ? 'blocked' : 'pass', notes: notes.join('\n').slice(0, 12000)};
        state = await api.raw<Status>(`/api/test/runs/${state.run.id}/scenarios/${scenario.id}/observation`, observation);
        const blob = await scenarioPng(`${scenario.id} · ${scenario.title}`, notes, tiles);
        const save = async () => { await upload(state.run.id, scenario.id, blob); };
        retryRef.current = save;
        try { await save(); retryRef.current = null; } catch (e) { setCaptureRetry(true); throw e; }
        state = await api.raw<Status>(`/api/test/runs/${state.run.id}`); setStatus(state);
      }
      setMessage('Finished: 200 scenario PNGs saved. Copy the report for accuracy review; visual review remains pending.');
    } catch (e) {
      setMessage(String(e));
      if (stopRef.current && runRef.current) setStatus(await api.raw<Status>(`/api/test/runs/${runRef.current}/cancel`, {}));
    } finally { active.current = false; setRunning(false); setDraft(''); }
  }

  async function copy() {
    if (!status) return;
    const text = JSON.stringify(await api.raw(`/api/test/runs/${status.run.id}/review?start=${batch * 10}&size=10`), null, 2);
    setCopyText(text);
    try { await navigator.clipboard.writeText(text); setMessage(`Copied scenarios ${batch * 10 + 1}–${Math.min(200, batch * 10 + 10)} with overall summary.`); }
    catch { setMessage('Select and copy the report text below.'); }
  }
  const expandedTurn = turns.find(t => t.id === expanded);
  const noop = () => {};
  if (syntheticOpen) return <Suspense fallback={null}><SyntheticPanel onClose={() => setSyntheticOpen(false)} /></Suspense>;
  return <TestScope.Provider value={status?.run.id}><div className="fixed inset-0 z-50 flex bg-page" data-testid="test-panel">
    <Sidebar sessions={[]} currentId={null} collapsed={collapsed} overlay={narrow} open={false} onToggle={() => setCollapsed(v => !v)} onClose={noop} onNew={noop} onSelect={noop} onRename={noop} onDelete={noop} freshness={freshness} devEntry={<span className="px-3 text-sm">Test · isolated conversations</span>} />
    <main className="flex min-w-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-canvas p-2 text-xs">
        <span data-testid="test-suite">{suite ? `${suite.scenario_count} scenarios · ${suite.steps.length} prompts` : 'Loading suite…'}</span>
        <Button size="sm" disabled={running || !suite || status?.run.status === 'running'} onClick={() => void execute()} data-testid="test-start">Run tests</Button>
        <Button size="sm" variant="ghost" disabled={running} data-testid="test-synthetic" onClick={() => setSyntheticOpen(true)}>Synthetic checks</Button>
        {!running && status?.run.status === 'running' && <Button size="sm" onClick={() => void execute(status)}>Resume run</Button>}
        <Button size="sm" variant="outline" disabled={!running} onClick={() => { pauseRef.current = !pauseRef.current; setPaused(pauseRef.current); }}>{paused ? 'Resume' : 'Pause'}</Button>
        <Button size="sm" variant="outline" disabled={!running} onClick={() => { stopRef.current = true; pauseRef.current = false; setMessage('Stopping after the current model request returns…'); }}>Stop</Button>
        <label>Hold <input aria-label="Display hold seconds" className="w-12 rounded border p-1" type="number" min="0" max="30" value={hold} disabled={running} onChange={e => setHold(Math.max(0, Math.min(30, Number(e.target.value) || 0)))} /> s</label>
        <Button size="sm" variant="ghost" disabled={running} onClick={onClose}>Exit test</Button>
        {captureRetry && <Button size="sm" onClick={() => void retryRef.current?.().then(() => { setCaptureRetry(false); retryRef.current = null; setMessage('PNG saved. Resume run to continue.'); }).catch(e => setMessage(String(e)))}>Retry PNG save</Button>}
      </div>
      <div className="border-b border-line bg-canvas px-3 py-2 text-xs"><strong data-testid="test-case">{current}</strong><p role="status">{message}</p><p data-testid="test-progress">{status ? `Passed ${status.counts.passed} · Failed ${status.counts.failed} · Review ${status.counts.review ?? 0} · Blocked ${status.counts.blocked} · PNGs ${status.run.scenarios.filter(s => s.png).length}/200` : 'Normal saved chats are untouched.'}</p></div>
      {verdict && <TestVerdict step={verdict} />}
      <div ref={surface} className="flex min-h-0 flex-1 flex-col" data-testid="test-result">
        {expandedTurn?.assistant.status === 'answer' ? <ExpandedAnalysis answer={expandedTurn.assistant.answer} shown={expandedTurn.assistant.shown} view={expandedTurn.assistant.view} presentation={expandedTurn.assistant.presentation} onView={v => onView(expandedTurn, v)} onPresentation={p => onPresentation(expandedTurn, p)} onExplore={noop} onSuggestion={noop} onClose={() => setExpanded(null)} /> :
          <Conversation turns={turns} empty={!turns.length} onView={onView} onPresentation={onPresentation} onExplore={t => setExpanded(t.id)} onSuggestion={text => setMessage(`Suggestion: ${text}. Authored tests control the next prompt.`)} onRunWithCurrent={noop} />}
      </div>
      <div className="border-t border-line bg-canvas px-4 pb-4 pt-3 md:px-6"><Composer busy draft={draft} onDraftChange={noop} onSubmit={noop} placeholder="The test runner submits each authored prompt" /></div>
      {status && !running && <div className="border-t p-2 text-xs"><label>Report batch <select value={batch} onChange={e => setBatch(Number(e.target.value))}>{Array.from({length: 20}, (_, i) => <option key={i} value={i}>{i * 10 + 1}–{i * 10 + 10}</option>)}</select></label><Button size="sm" onClick={() => void copy()}>Copy results for review</Button><a href={`/api/test/runs/${status.run.id}/report`} download>Download report</a>{copyText && <textarea className="block h-28 w-full" aria-label="Review report text" value={copyText} readOnly />}</div>}
    </main>
  </div></TestScope.Provider>;
}
