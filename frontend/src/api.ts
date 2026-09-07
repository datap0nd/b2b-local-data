import type {AnswerPayload, AskResponse, Bootstrap, PresentationName, ResultResponse, SessionDetail, SessionSummary, TablePayload, ViewName, AnswerText, Freshness, SupportingPage} from './types';

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
  supporting: (session: string, turn: number, view: ViewName, page: number, pageSize: number, sort?: {field: string; direction: 'asc' | 'desc'}) => request<SupportingPage>(supportingUrl(session, turn, view, false, page, pageSize, sort)),
  supportingCsv: async (session: string, turn: number, view: ViewName, sort?: {field: string; direction: 'asc' | 'desc'}) => {
    const response = await fetch(supportingUrl(session, turn, view, true, undefined, undefined, sort));
    if (!response.ok || !response.headers.get('content-type')?.includes('text/csv')) {
      let message = 'The saved supporting records could not be downloaded.';
      try { const payload = await response.json(); message = payload.message ?? payload.error ?? message; } catch { /* no JSON */ }
      throw new ApiError(message, response.status);
    }
    return response.blob();
  },
  raw: request,
};

function supportingUrl(session: string, turn: number, view: ViewName, csv: boolean, page?: number, pageSize?: number, sort?: {field: string; direction: 'asc' | 'desc'}) {
  const query = new URLSearchParams({view});
  if (page != null) query.set('page', String(page));
  if (pageSize != null) query.set('page_size', String(pageSize));
  if (sort) { query.set('sort', sort.field); query.set('direction', sort.direction); }
  return `/api/sessions/${encodeURIComponent(session)}/turns/${turn}/supporting${csv ? '.csv' : ''}?${query}`;
}
