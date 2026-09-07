import {lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {FlaskConical, Menu} from 'lucide-react';
import {api, ApiError} from './api';
import {Button} from './components/ui/button';
import {Composer} from './components/Composer';
import {Conversation} from './components/Conversation';
import {ExpandedAnalysis} from './components/ExpandedAnalysis';
import {Login} from './components/Login';
import {Sidebar} from './components/Sidebar';
import type {AnswerPayload, Bootstrap, ConversationTurn, PresentationName, SessionSummary, TablePayload, ViewName} from './types';

const AcceptancePanel = lazy(() => import('./dev/AcceptancePanel'));
const SESSION_KEY = 'b2b-session';

function answerTurn(id: number | string, question: string, payload: AnswerPayload, createdAt?: string): ConversationTurn {
  return {id, question, createdAt, assistant: {status: 'answer', answer: payload, shown: payload.table, view: payload.table.view, presentation: payload.table.presentation}};
}

export function App() {
  const [boot, setBoot] = useState<Bootstrap | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(() => localStorage.getItem(SESSION_KEY));
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('b2b-sidebar') === 'collapsed');
  const [overlayOpen, setOverlayOpen] = useState(false);
  const [narrow, setNarrow] = useState(() => window.innerWidth < 900);
  const [expandedId, setExpandedId] = useState<number | string | null>(null);
  const [devOpen, setDevOpen] = useState(false);
  const scrollBefore = useRef(0);
  const collapsedBefore = useRef(false);
  const counter = useRef(0);

  useEffect(() => { const onResize = () => setNarrow(window.innerWidth < 900); window.addEventListener('resize', onResize); return () => window.removeEventListener('resize', onResize); }, []);
  useEffect(() => { localStorage.setItem('b2b-sidebar', collapsed ? 'collapsed' : 'open'); }, [collapsed]);

  const refreshSessions = useCallback(async () => { try { setSessions((await api.sessions()).sessions); } catch { /* keep the previous list */ } }, []);

  const loadSession = useCallback(async (id: string) => {
    const saved = await api.session(id);
    setSessionId(id); localStorage.setItem(SESSION_KEY, id);
    const list: ConversationTurn[] = [];
    for (const turn of saved.turns) {
      if (turn.kind === 'clarify' || !turn.plan) { list.push({id: turn.id, question: turn.question, createdAt: turn.created_at, assistant: {status: 'clarify', text: turn.response, suggestions: []}}); continue; }
      if (turn.has_result) list.push({id: turn.id, question: turn.question, createdAt: turn.created_at, assistant: {status: 'answer', answer: {kind: 'table', turn_id: turn.id, session_id: id, table: placeholder(), variants: {}, answer: {title: '', sentence: '', metrics: []}, suggestions: []}, shown: placeholder(), view: 'summary', presentation: 'table', loading: true}});
      else list.push({id: turn.id, question: turn.question, createdAt: turn.created_at, assistant: {status: 'missing', message: 'This answer predates saved results, so its original tables are not available. Running it again uses the current data and creates a new dated answer.', canRerun: true}});
    }
    setTurns(list);
    // Restore the original tables and charts from the saved answers; no SQL or model call.
    for (const turn of saved.turns) {
      if (!turn.has_result) continue;
      try {
        const result = await api.result(id, turn.id);
        if (result.available) {
          const payload: AnswerPayload = {kind: 'table', turn_id: turn.id, session_id: id, table: result.table, variants: result.variants, answer: result.answer, suggestions: result.suggestions ?? []};
          setTurns(prev => prev.map(t => (t.id === turn.id ? answerTurn(turn.id, turn.question, payload, turn.created_at) : t)));
        } else setTurns(prev => prev.map(t => (t.id === turn.id ? {...t, assistant: {status: 'missing', message: result.message, canRerun: result.can_rerun}} : t)));
      } catch (error) {
        setTurns(prev => prev.map(t => (t.id === turn.id ? {...t, assistant: {status: 'missing', message: error instanceof Error ? error.message : 'The saved answer could not be read.', canRerun: true}} : t)));
      }
    }
  }, []);

  const newSession = useCallback(async () => {
    const created = await api.newSession();
    setSessionId(created.session_id); localStorage.setItem(SESSION_KEY, created.session_id);
    setTurns([]); setExpandedId(null); setDraft('');
    await refreshSessions();
  }, [refreshSessions]);

  useEffect(() => {
    (async () => {
      try {
        const b = await api.bootstrap(); setBoot(b);
        if (b.identity.login_required) return;
        await refreshSessions();
        const stored = localStorage.getItem(SESSION_KEY);
        if (stored) { try { await loadSession(stored); return; } catch { localStorage.removeItem(SESSION_KEY); } }
        setSessionId(null); setTurns([]);
      } catch (error) { setFatal(error instanceof Error ? error.message : 'The application could not start.'); }
    })();
  }, [loadSession, refreshSessions]);

  const ask = useCallback(async (question: string) => {
    if (busy) return;
    const tempId = `pending-${++counter.current}`;
    setBusy(true);
    setTurns(prev => [...prev, {id: tempId, question, assistant: {status: 'pending'}}]);
    const draftBefore = draft; setDraft('');
    try {
      const reply = await api.ask(question, sessionId);
      if (reply.session_id !== sessionId) { setSessionId(reply.session_id); localStorage.setItem(SESSION_KEY, reply.session_id); }
      if (reply.kind === 'clarify') setTurns(prev => prev.map(t => (t.id === tempId ? {id: reply.turn_id, question, assistant: {status: 'clarify', text: reply.question, suggestions: reply.suggestions}} : t)));
      else setTurns(prev => prev.map(t => (t.id === tempId ? answerTurn(reply.turn_id, question, reply) : t)));
      void refreshSessions();
    } catch (error) {
      const message = error instanceof ApiError && error.loginRequired ? 'Your session expired. Reload the page to sign in again.' : error instanceof Error ? error.message : 'The question could not be answered.';
      // Keep earlier answers and the draft; offer a retry of the same question.
      setDraft(draftBefore);
      setTurns(prev => prev.map(t => (t.id === tempId ? {...t, assistant: {status: 'error', message, retry: () => { setTurns(p => p.filter(x => x.id !== tempId)); void ask(question); }}} : t)));
    } finally { setBusy(false); }
  }, [busy, draft, sessionId, refreshSessions]);

  const runSample = useCallback(async (view: 'summary' | 'detail', intent: 'table' | 'metric' | 'chart', question: string) => {
    if (busy) return; const tempId = `pending-${++counter.current}`; setBusy(true);
    setTurns(prev => [...prev, {id: tempId, question, assistant: {status: 'pending'}}]);
    try {
      const reply = await api.sample(view, intent, sessionId);
      if (reply.session_id !== sessionId) { setSessionId(reply.session_id); localStorage.setItem(SESSION_KEY, reply.session_id); }
      setTurns(prev => prev.map(t => (t.id === tempId ? answerTurn(reply.turn_id, question, reply) : t)));
      void refreshSessions();
    } catch (error) { setTurns(prev => prev.map(t => (t.id === tempId ? {...t, assistant: {status: 'error', message: error instanceof Error ? error.message : 'The sample failed.', retry: () => { setTurns(p => p.filter(x => x.id !== tempId)); void runSample(view, intent, question); }}} : t))); }
    finally { setBusy(false); }
  }, [busy, sessionId, refreshSessions]);

  const update = (id: number | string, patch: (turn: ConversationTurn) => ConversationTurn) => setTurns(prev => prev.map(t => (t.id === id ? patch(t) : t)));

  const onView = useCallback(async (turn: ConversationTurn, view: ViewName) => {
    if (turn.assistant.status !== 'answer' || !sessionId || typeof turn.id !== 'number') return;
    const current = turn.assistant;
    if (current.view === view) return;
    const local = current.answer.variants?.[view];
    if (local && 'rows' in local) { update(turn.id, t => ({...t, assistant: {...current, shown: local as TablePayload, view, presentation: 'table'}})); return; }
    update(turn.id, t => ({...t, assistant: {...current, loading: true}}));
    try {
      const reply = await api.view(sessionId, turn.id, view);
      update(turn.id, t => ({...t, assistant: {...current, shown: reply.table, view, loading: false, answer: {...current.answer, variants: {...current.answer.variants, [view]: reply.table}}}}));
    } catch (error) { update(turn.id, t => ({...t, assistant: {...current, loading: false, notice: error instanceof Error ? error.message : 'That view is not available.'}})); }
  }, [sessionId]);

  const onPresentation = useCallback((turn: ConversationTurn, presentation: PresentationName) => {
    if (turn.assistant.status !== 'answer') return;
    const current = turn.assistant;
    update(turn.id, t => ({...t, assistant: {...current, presentation}}));
  }, []);

  const onRunWithCurrent = useCallback(async (turn: ConversationTurn) => {
    if (!sessionId || typeof turn.id !== 'number' || busy) return;
    const turnId = turn.id; const tempId = `pending-${++counter.current}`; setBusy(true);
    setTurns(prev => [...prev, {id: tempId, question: turn.question, runOf: turnId, assistant: {status: 'pending'}}]);
    try { const reply = await api.runTurn(sessionId, turnId); setTurns(prev => prev.map(t => (t.id === tempId ? answerTurn(reply.turn_id, turn.question, reply) : t))); void refreshSessions(); }
    catch (error) { setTurns(prev => prev.map(t => (t.id === tempId ? {...t, assistant: {status: 'error', message: error instanceof Error ? error.message : 'The rerun failed.', retry: () => { setTurns(p => p.filter(x => x.id !== tempId)); void onRunWithCurrent(turn); }}} : t))); }
    finally { setBusy(false); }
  }, [sessionId, busy, refreshSessions]);

  const expanded = useMemo(() => turns.find(t => t.id === expandedId), [turns, expandedId]);
  const openExpanded = useCallback((turn: ConversationTurn) => { scrollBefore.current = document.querySelector('[data-testid="conversation"]')?.scrollTop ?? 0; collapsedBefore.current = collapsed; setExpandedId(turn.id); if (!narrow) setCollapsed(true); }, [collapsed, narrow]);
  const onSuggestion = useCallback((text: string) => setDraft(text), []);
  const closeExpanded = useCallback(() => { setExpandedId(null); setCollapsed(collapsedBefore.current); requestAnimationFrame(() => { const el = document.querySelector('[data-testid="conversation"]'); if (el) el.scrollTop = scrollBefore.current; }); }, []);

  if (fatal) return <div className="grid min-h-screen place-items-center p-6 text-sm text-danger" role="alert">{fatal}</div>;
  if (!boot) return <div className="grid min-h-screen place-items-center text-sm text-ink-3">Loading</div>;
  if (boot.identity.login_required) return <Login onLogin={async name => { await api.login(name); const b = await api.bootstrap(); setBoot(b); localStorage.removeItem(SESSION_KEY); setSessionId(null); setTurns([]); await refreshSessions(); }} />;

  const samples = boot.capabilities.samples ? (
    <div className="flex flex-wrap justify-center gap-2" data-testid="samples">
      <span className="w-full text-xs text-ink-3">Fictional sample data: try a fixed example without the model</span>
      <Button variant="outline" size="sm" onClick={() => runSample('summary', 'table', 'Show every opportunity')}>Opportunity summary</Button>
      <Button variant="outline" size="sm" onClick={() => runSample('detail', 'table', 'Show every product row')}>Product detail</Button>
      <Button variant="outline" size="sm" onClick={() => runSample('summary', 'chart', 'Chart the amount by stage group')}>Amount by stage group</Button>
    </div>
  ) : null;

  const devEntry = boot.capabilities.acceptance_ui ? <Button variant="ghost" size="sm" className="w-full justify-start text-ink-3" onClick={() => setDevOpen(true)} data-testid="test-open"><FlaskConical />Test</Button> : null;

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-canvas">
      <Sidebar sessions={sessions} currentId={sessionId} collapsed={collapsed} overlay={narrow} open={overlayOpen}
        onToggle={() => setCollapsed(v => !v)} onClose={() => setOverlayOpen(false)} onNew={() => { void newSession(); setOverlayOpen(false); }}
        onSelect={id => { setExpandedId(null); setOverlayOpen(false); void loadSession(id).catch(() => {}); }}
        onRename={(id, title) => { void api.rename(id, title).then(refreshSessions); }}
        onDelete={id => { if (!confirm('Delete this conversation?')) return; void api.remove(id).then(async () => { if (id === sessionId) await newSession(); else await refreshSessions(); }); }}
        devEntry={devEntry} />
      <main className="flex min-w-0 flex-1 flex-col">
        {narrow && (
          <div className="flex items-center gap-2 border-b border-line px-3 py-2">
            <Button variant="ghost" size="icon-sm" aria-label="Open history" onClick={() => setOverlayOpen(true)}><Menu /></Button>
            <span className="text-sm font-semibold">B2B</span>
          </div>
        )}
        {expanded && expanded.assistant.status === 'answer' ? (
          <ExpandedAnalysis answer={expanded.assistant.answer} shown={expanded.assistant.shown} view={expanded.assistant.view} presentation={expanded.assistant.presentation} loading={expanded.assistant.loading} notice={expanded.assistant.notice}
            onView={v => onView(expanded, v)} onPresentation={p => onPresentation(expanded, p)} onExplore={() => {}} onSuggestion={onSuggestion} onClose={closeExpanded}>
            <Composer compact busy={busy} draft={draft} onDraftChange={setDraft} onSubmit={async text => { await ask(text); closeExpanded(); }} placeholder="Ask a follow-up" />
          </ExpandedAnalysis>
        ) : (
          <>
            <Conversation key={sessionId ?? "none"} turns={turns} empty={turns.length === 0} samples={samples} onView={onView} onPresentation={onPresentation} onExplore={openExpanded} onSuggestion={onSuggestion} onRunWithCurrent={onRunWithCurrent} />
            <div className="border-t border-line bg-canvas px-4 pb-4 pt-3 md:px-6">
              <Composer busy={busy} draft={draft} onDraftChange={setDraft} onSubmit={ask} autoFocus />
            </div>
          </>
        )}
      </main>
      {devOpen && boot.capabilities.acceptance_ui && <Suspense fallback={null}><AcceptancePanel onClose={() => setDevOpen(false)} /></Suspense>}
    </div>
  );
}

function placeholder(): TablePayload {
  return {columns: [], column_types: {}, rows: [], total_rows: 0, source_rows: 0, truncated: false, result_digest: '', totals: null, grain: 'opportunity', intent: 'table', view: 'summary', result_kind: 'rows', presentation: 'table', columns_mode: 'default', filters: [], source: '', source_name: '', warnings: [], scope: '', chart: null, plan_version: 2, views: {current: 'summary', available: [], scope: null, scope_label: null, product_filtered: false}, metadata: {version: 2, currency: {code: null, mixed: false, codes: {}, source: 'none'}, complete: {rows: 0}, warnings: [], freshness: null, fingerprint: null, explicit_columns: false}};
}
