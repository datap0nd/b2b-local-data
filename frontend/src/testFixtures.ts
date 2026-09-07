import type {AnswerPayload, TablePayload} from './types';

export function fixtureTable(overrides: Partial<TablePayload> = {}): TablePayload {
  return {columns: ['opportunity_count'], column_types: {opportunity_count: 'number'}, rows: [{opportunity_count: 545}], total_rows: 1, source_rows: 900, truncated: false, result_digest: 'synthetic', totals: null,
    grain: 'opportunity', intent: 'metric', view: 'summary', result_kind: 'aggregate', presentation: 'cards', columns_mode: 'default', filters: [{field: 'stage_group', operator: 'eq', value: 'Open'}, {field: 'close_month', operator: 'between', value: ['2026-01-01', '2026-12-31']}], source: 'synthetic', source_name: 'Invented test fixture', warnings: [], scope: '', chart: null, plan_version: 2,
    views: {current: 'summary', available: ['summary', 'detail'], scope: null, scope_label: null, product_filtered: false},
    metadata: {version: 2, calculation_version: 3, currency: {code: 'USD', mixed: false, codes: {USD: 545}, source: 'column'}, complete: {rows: 1, opportunities: 545}, warnings: [], freshness: null, fingerprint: 'synthetic', explicit_columns: false}, ...overrides};
}
export function fixtureAnswer(table = fixtureTable()): AnswerPayload {
  return {kind: 'table', turn_id: 1, session_id: 'synthetic', table, variants: {}, answer: {title: 'Open opportunities', context: 'Closing in 2026', sentence: '', metrics: [{label: 'Opportunity count', value: '545', raw: 545}]}, suggestions: []};
}
