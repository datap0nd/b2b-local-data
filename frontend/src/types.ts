// Typed contracts of the API (result metadata version 2). Values are never converted to floating point here.
export type ColumnType = 'number' | 'date' | 'bool' | 'text';
export type Cell = string | number | boolean | null;
export type Row = Record<string, Cell>;
export type Grain = 'opportunity' | 'opportunity_sku';
export type ViewName = 'summary' | 'detail';
export type PresentationName = 'table' | 'chart' | 'cards';

export interface FilterClause { field: string; operator: string; value: Cell | Cell[] }

export interface Freshness {
  status: 'verified' | 'unavailable';
  updated_at: string | null;
  timezone: string | null;
  method: 'commit_timestamp' | 'freshness_view' | null;
  reason: string | null;
  reused?: boolean;
}

export interface QualityIssue { code: string; field?: string; message: string; values?: unknown; product_total?: Cell; exported_total?: Cell; difference?: Cell; currency?: string | null }
export interface QualityRecord { opportunity_no: Cell; opportunity_name?: Cell; product_code?: Cell; issues?: QualityIssue[] }
export interface QualityWarning { code: string; count: number; message: string; records: QualityRecord[] }

export interface ResultMetadata {
  version: 2;
  calculation_version?: number;
  sort?: {field: string; direction: 'asc' | 'desc'}[];
  evidence?: {role: 'supporting'; source_result_digest: string; source_grain: Grain; data_scope: 'all_products' | 'matching_products'; default_columns: string[]; amount_complete?: boolean};
  currency: { code: string | null; mixed: boolean; codes: Record<string, number>; source: string };
  complete: { rows: number; opportunities?: number; sku_pairs?: number | null; quantity?: string | null; groups?: number; by_currency?: Record<string, { amount: string | null; quantity: string | null; opportunities: number; rows: number }> };
  warnings: QualityWarning[];
  freshness: Freshness | null;
  fingerprint: string | null;
  loaded_at?: string;
  explicit_columns: boolean;
}

export interface ChartSpec { type: 'bar' | 'line' | 'area' | 'scatter'; dimensions: string[]; measures: string[] }

export interface TablePayload {
  columns: string[];
  column_types: Record<string, ColumnType>;
  rows: Row[];
  total_rows: number;
  source_rows: number;
  truncated: boolean;
  result_digest: string;
  totals: Record<string, Cell> | null;
  grain: Grain;
  intent: string;
  view: ViewName;
  result_kind: 'rows' | 'aggregate';
  presentation: PresentationName;
  columns_mode: 'default' | 'include' | 'only';
  filters: FilterClause[];
  source: string;
  source_name: string;
  warnings: string[];
  scope: string;
  chart: ChartSpec | null;
  plan_version: number;
  views: { current: ViewName; available: ViewName[]; scope: string | null; scope_label: string | null; product_filtered: boolean };
  metadata: ResultMetadata;
  snapshot_at?: string;
}

export interface Metric { label: string; value: string; raw: Cell; currency?: string | null; note?: string }
export interface AnswerText { title: string; context?: string; sentence: string; metrics: Metric[] }
export interface SupportingData { version?: number; available: boolean; default_view?: ViewName; views?: Partial<Record<ViewName, TablePayload>>; message?: string; can_rerun?: boolean }
export type SupportingPage = {available: true; view: ViewName; page: number; page_size: number; total_rows: number; table: TablePayload} | {available: false; message: string};

export interface AnswerPayload {
  kind: 'table';
  turn_id: number;
  session_id: string;
  table: TablePayload;
  variants: Record<string, TablePayload | { error: string }>;
  answer: AnswerText;
  suggestions: string[];
  supporting?: SupportingData;
  plan?: unknown;
  contract_version?: number;
  rerun_of?: number | null;
}

export interface ClarifyPayload { kind: 'clarify'; turn_id: number; session_id: string; question: string; suggestions: string[] }
export type AskResponse = AnswerPayload | ClarifyPayload;

export interface SavedResult extends Omit<AnswerPayload, 'kind'> { available: true; kind: string; fingerprint: string | null; freshness: Freshness | null; saved_at: string }
export interface MissingResult { available: false; turn_id: number; kind: string; can_rerun: boolean; message: string }
export type ResultResponse = SavedResult | MissingResult;

export interface TurnSummary { id: number; question: string; response: string; plan: unknown | null; kind: 'data' | 'clarify' | string; created_at: string; has_result: boolean; freshness: Freshness | null }
export interface SessionDetail { id: string; title: string; created_at?: string; updated_at?: string; turns: TurnSummary[]; active_plan: unknown | null }
export interface SessionSummary { id: string; title: string; updated_at: string; created_at?: string }

export interface Bootstrap {
  identity: { login_required: boolean; name: string; mode: string };
  capabilities: { acceptance_ui: boolean; samples: boolean; saved_results: boolean; contract_version: number; views: ViewName[]; presentations: PresentationName[] };
}

// Conversation state in the browser: real user and assistant turns, with pending and failed assistant turns.
export type AssistantState =
  | { status: 'pending' }
  | { status: 'error'; message: string; retry: () => void }
  | { status: 'clarify'; text: string; suggestions: string[] }
  | { status: 'answer'; answer: AnswerPayload; shown: TablePayload; view: ViewName; presentation: PresentationName; loading?: boolean; notice?: string }
  | { status: 'missing'; message: string; canRerun: boolean };

export interface ConversationTurn { id: number | string; question: string; createdAt?: string; assistant: AssistantState; runOf?: number }
