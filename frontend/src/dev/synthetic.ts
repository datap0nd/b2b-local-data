// Synthetic edge cases for conditions absent from live data. Development evidence only; never live-source coverage.
import type {Row, TablePayload} from '@/types';

function synthetic(columns: string[], rows: Row[], extra: Partial<TablePayload> = {}): TablePayload {
  const types: Record<string, 'number' | 'date' | 'bool' | 'text'> = {};
  columns.forEach(c => { types[c] = ['quantity', 'opportunity_amount', 'sku_amount', 'amount', 'sku_count', 'opportunity_count', 'probability', 'deal_size'].includes(c) ? 'number' : ['close_date', 'close_month'].includes(c) ? 'date' : c.startsWith('has_') ? 'bool' : 'text'; });
  const codes: Record<string, number> = {};
  rows.forEach(r => { const code = r.opp_amount_converted_currency ?? r.amount_converted_currency; if (code != null) codes[String(code)] = (codes[String(code)] ?? 0) + 1; });
  const currencyCode = Object.keys(codes).length === 1 ? Object.keys(codes)[0] : (extra.filters ?? []).find(f => f.field.includes('currency'))?.value as string | undefined ?? null;
  return {columns, column_types: types, rows, total_rows: rows.length, source_rows: rows.length, truncated: false, result_digest: 'digest2:synthetic-' + Math.random().toString(16).slice(2), totals: null, grain: 'opportunity', intent: 'table', view: 'summary',
    result_kind: 'rows', presentation: 'table', columns_mode: 'default', filters: [], source: 'synthetic', source_name: 'synthetic fixture', warnings: [], scope: 'synthetic', chart: null, plan_version: 2,
    views: {current: 'summary', available: ['summary', 'detail'], scope: null, scope_label: null, product_filtered: false},
    metadata: {version: 2, currency: {code: Object.keys(codes).length > 1 ? null : currencyCode, mixed: Object.keys(codes).length > 1, codes, source: 'synthetic'}, complete: {rows: rows.length}, warnings: [], freshness: null, fingerprint: null, explicit_columns: false}, ...extra};
}

export const SYNTHETIC: {id: string; title: string; checks: number[]; table: () => TablePayload}[] = [
  {id: 'S1', title: 'Mixed currencies, exact negative CSV amounts and nulls last', checks: [1, 3, 4, 5, 15], table: () => synthetic(
    ['opportunity_no', 'opportunity_name', 'end_customer', 'opportunity_owner', 'stage', 'close_date', 'quantity', 'opportunity_amount', 'sku_count', 'opp_amount_converted_currency', 'has_amount_discrepancy', 'has_quality_warning'],
    [{opportunity_no: '000123', opportunity_name: 'Alpha programme with an unusually long descriptive name that wraps', end_customer: 'Zoë Ångström GmbH', opportunity_owner: 'Ann', stage: 'Won', close_date: '2026-01-02', quantity: '3', opportunity_amount: '12345678901.55', sku_count: 2, opp_amount_converted_currency: 'EUR', has_amount_discrepancy: false, has_quality_warning: true},
     {opportunity_no: '-00124', opportunity_name: 'Beta', end_customer: 'Contoso', opportunity_owner: 'Bo', stage: 'Lost', close_date: null, quantity: '1', opportunity_amount: '-12.50', sku_count: 1, opp_amount_converted_currency: 'USD', has_amount_discrepancy: true, has_quality_warning: false},
     {opportunity_no: '000125', opportunity_name: 'Gamma', end_customer: null, opportunity_owner: 'Cy', stage: 'Qualified', close_date: '2026-12-31', quantity: null, opportunity_amount: null, sku_count: 0, opp_amount_converted_currency: 'EUR', has_amount_discrepancy: false, has_quality_warning: false}],
    {metadata: {version: 2, currency: {code: null, mixed: true, codes: {EUR: 2, USD: 1}, source: 'mixed'}, complete: {rows: 3, opportunities: 3}, warnings: [{code: 'quality_warning', count: 1, message: '1 opportunity has conflicting source fields.', records: [{opportunity_no: '000123', issues: [{code: 'field_conflict', field: 'opportunity_owner', message: 'Source rows have different owners.', values: ['Ann', 'Bo']}]}]}], freshness: null, fingerprint: null, explicit_columns: false}})},
  {id: 'S2', title: 'Sixty-six monthly groups: whole range kept with zoom, chart stable under table sorting', checks: [7, 11], table: () => synthetic(['close_month', 'amount'],
    Array.from({length: 66}, (_, i) => { const year = 2021 + Math.floor(i / 12), month = (i % 12) + 1; return {close_month: `${year}-${String(month).padStart(2, '0')}-01`, amount: i % 9 === 4 ? null : `${(i + 1) * 1500}.00`}; }),
    {result_kind: 'aggregate', intent: 'chart', presentation: 'chart', chart: {type: 'line', dimensions: ['close_month'], measures: ['amount']}, filters: [{field: 'opp_amount_converted_currency', operator: 'eq', value: 'EUR'}], views: {current: 'summary', available: [], scope: null, scope_label: null, product_filtered: false},
      metadata: {version: 2, currency: {code: 'EUR', mixed: false, codes: {}, source: 'filter'}, complete: {rows: 66, groups: 66}, warnings: [], freshness: null, fingerprint: null, explicit_columns: false}})},
  {id: 'S3', title: 'Forty owners: top ten bars with access to the rest, long labels', checks: [6, 10, 11], table: () => synthetic(['opportunity_owner', 'amount', 'quantity'],
    Array.from({length: 40}, (_, i) => ({opportunity_owner: `Owner ${String(i + 1).padStart(2, '0')} with a very long descriptive name that needs truncation`, amount: `${(40 - i) * 1000 + 0.25}`, quantity: String(i + 1)})),
    {result_kind: 'aggregate', intent: 'chart', presentation: 'chart', chart: {type: 'bar', dimensions: ['opportunity_owner'], measures: ['amount', 'quantity']}, views: {current: 'summary', available: [], scope: null, scope_label: null, product_filtered: false},
      metadata: {version: 2, currency: {code: 'EUR', mixed: false, codes: {}, source: 'filter'}, complete: {rows: 40, groups: 40}, warnings: [], freshness: null, fingerprint: null, explicit_columns: false}})},
  {id: 'S4', title: 'Empty result with filters', checks: [14], table: () => synthetic(['opportunity_no', 'opportunity_name', 'opportunity_amount'], [], {filters: [{field: 'stage', operator: 'in', value: ['Open']}, {field: 'opportunity_amount', operator: 'gt', value: 5000000000}]})},
  {id: 'S5', title: 'Large USD values as cards', checks: [13], table: () => synthetic(['amount', 'quantity', 'opportunity_count'], [{amount: '9876543210.99', quantity: '120394', opportunity_count: 545}],
    {result_kind: 'aggregate', intent: 'metric', presentation: 'cards', views: {current: 'summary', available: [], scope: null, scope_label: null, product_filtered: false},
      metadata: {version: 2, currency: {code: 'USD', mixed: false, codes: {USD: 545}, source: 'column'}, complete: {rows: 1, opportunities: 545}, warnings: [], freshness: null, fingerprint: null, explicit_columns: false}})},
];
