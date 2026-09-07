import type {AnswerPayload, Row, TablePayload, ViewName} from './types';

export function fixtureTable(overrides: Partial<TablePayload> = {}): TablePayload {
  return {columns: ['opportunity_count'], column_types: {opportunity_count: 'number'}, rows: [{opportunity_count: 545}], total_rows: 1, source_rows: 900, truncated: false, result_digest: 'synthetic', totals: null,
    grain: 'opportunity', intent: 'metric', view: 'summary', result_kind: 'aggregate', presentation: 'cards', columns_mode: 'default', filters: [{field: 'stage_group', operator: 'eq', value: 'Open'}, {field: 'close_month', operator: 'between', value: ['2026-01-01', '2026-12-31']}], source: 'synthetic', source_name: 'Invented test fixture', warnings: [], scope: '', chart: null, plan_version: 2,
    views: {current: 'summary', available: ['summary', 'detail'], scope: null, scope_label: null, product_filtered: false},
    metadata: {version: 2, calculation_version: 3, currency: {code: 'USD', mixed: false, codes: {USD: 545}, source: 'column'}, complete: {rows: 1, opportunities: 545}, warnings: [], freshness: null, fingerprint: 'synthetic', explicit_columns: false}, ...overrides};
}
export function fixtureAnswer(table = fixtureTable()): AnswerPayload {
  return {kind: 'table', turn_id: 1, session_id: 'synthetic', table, variants: {}, answer: {title: 'Open opportunities', context: 'Closing in 2026', sentence: '', metrics: [{label: 'Opportunity count', value: '545', raw: 545}]}, suggestions: []};
}

/** Invented evidence deliberately extends beyond the old 1,000-row result limit. */
export function supportingFixtureTable(view: ViewName = 'summary', count = 1005): TablePayload {
  const detail = view === 'detail';
  const columns = detail
    ? ['opportunity_no', 'product_code', 'pet_name', 'sku_amount', 'quantity', 'stage', 'opportunity_owner', 'amount_converted_currency', 'comment']
    : ['opportunity_name', 'opportunity_no', 'end_customer', 'opportunity_amount', 'stage', 'opportunity_owner', 'close_date', 'opp_amount_converted_currency', 'product_codes', 'comment'];
  const rows: Row[] = Array.from({length: detail ? count * 2 : count}, (_, position) => {
    const index = detail ? Math.floor(position / 2) : position;
    const total = index === count - 1 ? 9007199254740992030n : BigInt(100001 + index) * 1000n + 15n;
    const productAmount = total / 2n + (position % 2 ? total % 2n : 0n);
    return {opportunity_no: `DEMO-${String(index + 1).padStart(4, '0')}`, opportunity_name: `Invented opportunity ${index + 1}`, end_customer: `Example customer ${index % 5 + 1}`, opportunity_amount: `${total / 1000n}.${String(total % 1000n).padStart(3, '0')}`, stage: index % 2 ? 'Negotiation' : 'Qualified', opportunity_owner: 'Example owner', close_date: '2026-11-01', opp_amount_converted_currency: 'USD', product_codes: 'DISPLAY-A; DISPLAY-B', comment: `Saved evidence note ${index + 1}`, product_code: position % 2 ? 'DISPLAY-B' : 'DISPLAY-A', pet_name: 'Example display', sku_amount: `${productAmount / 1000n}.${String(productAmount % 1000n).padStart(3, '0')}`, quantity: detail ? '1' : '2', amount_converted_currency: 'USD'};
  });
  const table = fixtureTable({columns, rows, column_types: Object.fromEntries(columns.map(column => [column, ['opportunity_amount', 'sku_amount', 'quantity'].includes(column) ? 'number' : column === 'close_date' ? 'date' : 'text'])), total_rows: rows.length, source_rows: count * 2, result_kind: 'rows', intent: 'rows', presentation: 'table', grain: detail ? 'opportunity_sku' : 'opportunity', view});
  table.metadata.complete = {rows: rows.length, opportunities: count, sku_pairs: count * 2};
  table.metadata.currency.codes = {USD: rows.length};
  table.filters.push({field: 'opportunity_amount', operator: 'gt', value: '100000'});
  table.views = {current: view, available: ['summary', 'detail'], scope: 'all_products', scope_label: 'All products in matching opportunities', product_filtered: false};
  table.metadata.evidence = {role: 'supporting', source_result_digest: 'synthetic', source_grain: 'opportunity', data_scope: 'all_products', default_columns: columns.slice(0, 7)};
  return table;
}

export function supportingFixtureAnswer(): AnswerPayload {
  const table = fixtureTable({rows: [{opportunity_count: 1005}]});
  table.metadata.complete = {rows: 1, opportunities: 1005, sku_pairs: 2010};
  table.metadata.currency.codes = {USD: 1005};
  const answer = fixtureAnswer(table);
  answer.answer.metrics = [{label: 'Opportunity count', value: '1,005', raw: 1005}];
  answer.answer.context = 'Closing in 2026 · Amount over 100,000 USD';
  answer.table.filters.push({field: 'opportunity_amount', operator: 'gt', value: '100000'});
  answer.supporting = {version: 1, available: true, default_view: 'summary', views: Object.fromEntries((['summary', 'detail'] as const).map(view => {
    const evidence = supportingFixtureTable(view); return [view, {...evidence, rows: evidence.rows.slice(0, 25), truncated: true}];
  }))};
  return answer;
}
