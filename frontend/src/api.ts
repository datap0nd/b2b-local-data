import type {AnswerPayload, AskResponse, Bootstrap, PresentationName, ResultResponse, SessionDetail, SessionSummary, TablePayload, ViewName, AnswerText, Freshness} from './types';

export class ApiError extends Error { constructor(message: string, public status: number, public loginRequired = false) { super(message); } }

async function request<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const options: RequestInit = body === undefined && !method ? {} : {method: method ?? 'POST', headers: {'Content-Type': 'application/json'}, body: body === undefined ? undefined : JSON.stringify(body)};
  const response = await fetch(path, options);
  let payload: {error?: string; login_required?: boolean} & Record<string, unknown> = {};
  try { payload = await response.json(); } catch { /* non-JSON */ }
  if (!response.ok) throw new ApiError(payload.error ?? (response.status === 429 ? 'A question is already running.' : 'The request failed.'), response.status, !!payload.login_required);
  return payload as T;
}

export const api = {
  bootstrap: () => request<Bootstrap>('/api/bootstrap'),
  freshness: () => request<{freshness: Freshness | null}>('/api/freshness'),
  login: (name: string) => request<{name: string}>('/api/login', {name}),
  sessions: (q?: string) => request<{sessions: SessionSummary[]}>('/api/sessions' + (q ? `?q=${encodeURIComponent(q)}` : '')),
  newSession: () => request<{session_id: string}>('/api/sessions', {}),
  session: (id: string) => request<SessionDetail>(`/api/sessions/${encodeURIComponent(id)}`),
  rename: (id: string, title: string) => request<{ok: true}>(`/api/sessions/${encodeURIComponent(id)}/title`, {title}),
  remove: (id: string) => request<{ok: true}>(`/api/sessions/${encodeURIComponent(id)}`, undefined, 'DELETE'),
  ask: (question: string, session_id: string | null) => request<AskResponse>('/api/ask', {question, session_id}),
  sample: (view: 'summary' | 'detail', intent: 'table' | 'metric' | 'chart', session_id: string | null) => request<AnswerPayload>('/api/sample', {view, intent, session_id}),
  result: (session: string, turn: number) => request<ResultResponse>(`/api/sessions/${encodeURIComponent(session)}/turns/${turn}/result`),
  view: (session: string, turn: number, view: ViewName) => request<{turn_id: number; table: TablePayload; answer: AnswerText; variants_available: ViewName[]}>(`/api/sessions/${encodeURIComponent(session)}/turns/${turn}/actions`, {action: 'view', view}),
  presentation: (session: string, turn: number, presentation: PresentationName) => request<{turn_id: number; table: TablePayload; answer: AnswerText}>(`/api/sessions/${encodeURIComponent(session)}/turns/${turn}/actions`, {action: 'presentation', presentation}),
  runTurn: (session: string, turn: number) => request<AnswerPayload>(`/api/sessions/${encodeURIComponent(session)}/turns/${turn}/run`, {}),
  raw: request,
};
