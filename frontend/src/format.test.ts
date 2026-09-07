import {describe, expect, it} from 'vitest';
import {cellText, compareValues, csvText, filterText, formatDate, formatNumber, formatPercent, headerLabel, measureText, visibleColumns} from './format';
import type {TablePayload} from './types';

function table(overrides: Partial<TablePayload> = {}): TablePayload {
  return {columns: ['opportunity_no', 'opportunity_name', 'end_customer', 'opportunity_owner', 'stage', 'close_date', 'quantity', 'opportunity_amount', 'sku_count', 'opp_amount_converted_currency', 'has_amount_discrepancy', 'has_quality_warning'],
    column_types: {opportunity_no: 'text', opportunity_name: 'text', end_customer: 'text', opportunity_owner: 'text', stage: 'text', close_date: 'date', quantity: 'number', opportunity_amount: 'number', sku_count: 'number', opp_amount_converted_currency: 'text', has_amount_discrepancy: 'bool', has_quality_warning: 'bool'},
    rows: [], total_rows: 0, source_rows: 0, truncated: false, result_digest: 'digest2:test', totals: null, grain: 'opportunity', intent: 'table', view: 'summary', result_kind: 'rows', presentation: 'table', columns_mode: 'default',
    filters: [], source: 'test', source_name: 'test', warnings: [], scope: '', chart: null, plan_version: 2, views: {current: 'summary', available: ['summary', 'detail'], scope: null, scope_label: null, product_filtered: false},
    metadata: {version: 2, currency: {code: 'EUR', mixed: false, codes: {EUR: 3}, source: 'column'}, complete: {rows: 0}, warnings: [], freshness: null, fingerprint: null, explicit_columns: false}, ...overrides};
}

describe('exact number formatting', () => {
  it('keeps every digit of large decimals and rounds half up to the requested places', () => {
    expect(formatNumber('12345678901.555', 2)).toBe('12,345,678,901.56');
    expect(formatNumber('12345678901234567.125', 2)).toBe('12,345,678,901,234,567.13');
    expect(formatNumber('0.5', 2)).toBe('0.50');
    expect(formatNumber('-1234.5')).toBe('-1,234.5');
    expect(formatNumber('1E3')).toBe('1,000');
    expect(formatNumber('000123')).toBe('123');
    expect(formatNumber(null)).toBe('—');
    expect(formatNumber('not a number')).toBe('not a number');
  });
  it('shows probabilities as whole percentages of the stored fraction', () => {
    expect(formatPercent('0.75')).toBe('75%');
    expect(formatPercent('0.5')).toBe('50%');
    expect(formatPercent('0.125')).toBe('12.5%');
  });
  it('formats ISO dates without time-zone drift', () => {
    expect(formatDate('2026-02-02')).toMatch(/2.*Feb.*2026|Feb.*2.*2026/);
    expect(formatDate('2024-01-01', true)).toMatch(/Jan.*2024/);
    expect(formatDate(null)).toBe('—');
  });
});

describe('sorting', () => {
  it('compares numbers by exact decimal value and text by locale', () => {
    expect(compareValues('9', '10', 'number')).toBeLessThan(0);
    expect(compareValues('12345678901234567890.01', '12345678901234567890.02', 'number')).toBeLessThan(0);
    expect(compareValues('0.50', '0.5', 'number')).toBe(0);
    expect(compareValues('b', 'a', 'text')).toBeGreaterThan(0);
  });
  it('places nulls after every value in either direction of the comparator', () => {
    expect(compareValues(null, '1', 'number')).toBeGreaterThan(0);
    expect(compareValues('1', null, 'number')).toBeLessThan(0);
    expect(compareValues(null, null, 'number')).toBe(0);
  });
});

describe('cells, headers, and measures', () => {
  const t = table();
  it('labels amounts with the population currency once, in the header', () => {
    expect(headerLabel(t, 'opportunity_amount')).toBe('Amount (EUR)');
    expect(headerLabel(t, 'deal_size')).toBe('Deal size (USD)');
    expect(cellText(t, {opportunity_amount: '1234.5'}, 'opportunity_amount')).toBe('1,234.50');
    expect(measureText(t, 'amount', '10')).toBe('10.00 EUR');
    expect(measureText(t, 'quantity', '10')).toBe('10');
  });
  it('repeats the code per cell only when the population mixes currencies', () => {
    const mixed = table({metadata: {...t.metadata, currency: {code: null, mixed: true, codes: {EUR: 2, USD: 1}, source: 'mixed'}}});
    expect(headerLabel(mixed, 'opportunity_amount')).toBe('Amount');
    expect(cellText(mixed, {opportunity_amount: '5', opp_amount_converted_currency: 'USD'}, 'opportunity_amount')).toBe('5.00 USD');
    expect(measureText(mixed, 'amount', '5')).toBe('5.00');
  });
  it('renders booleans and dates in business words', () => {
    expect(cellText(t, {has_quality_warning: true}, 'has_quality_warning')).toBe('Check');
    expect(cellText(t, {has_amount_discrepancy: false}, 'has_amount_discrepancy')).toBe('Matches');
    expect(cellText(t, {close_date: null}, 'close_date')).toBe('—');
  });
});

describe('column selection', () => {
  it('shows compact defaults for ordinary results and every column for explicit selections', () => {
    expect(visibleColumns(table())).toEqual(['opportunity_name', 'end_customer', 'opportunity_amount', 'stage', 'opportunity_owner', 'close_date']);
    const only = table({columns_mode: 'only', columns: ['opportunity_no', 'opportunity_owner', 'stage', 'opportunity_amount']});
    expect(visibleColumns(only)).toEqual(['opportunity_no', 'opportunity_owner', 'stage', 'opportunity_amount']);
    const include = table({columns_mode: 'include', columns: [...table().columns, 'deal_size_on_pricing_date_usd']});
    expect(visibleColumns(include)).toEqual(['opportunity_name', 'end_customer', 'opportunity_amount', 'stage', 'opportunity_owner', 'close_date', 'deal_size_on_pricing_date_usd']);
    expect(visibleColumns(table({result_kind: 'aggregate', columns: ['opportunity_owner', 'amount']}))).toEqual(['opportunity_owner', 'amount']);
  });
});

describe('filter chips and CSV export', () => {
  it('describes filters with business labels and formatted values', () => {
    const types = table().column_types;
    expect(filterText({field: 'stage', operator: 'in', value: ['Won', 'Lost']}, types)).toBe('Stage is one of Won, Lost');
    expect(filterText({field: 'opportunity_amount', operator: 'gt', value: 5000}, types)).toBe('Amount more than 5,000');
    expect(filterText({field: 'close_date', operator: 'between', value: ['2026-01-01', '2026-12-31']}, types)).toBe('Closing in 2026');
  });
  it('exports every column with exact values, quoting, and formula guards', () => {
    const t = table({columns: ['opportunity_no', 'comment', 'opportunity_amount'], column_types: {opportunity_no: 'text', comment: 'text', opportunity_amount: 'number'}});
    const csv = csvText(t, [{opportunity_no: '000123', comment: '=SUM(A1) "quoted"', opportunity_amount: '12345678901.55'}, {opportunity_no: '000124', comment: null, opportunity_amount: null}]);
    expect(csv.charCodeAt(0)).toBe(0xfeff);
    expect(csv.slice(1).split('\r\n')).toEqual(['"opportunity_no","comment","opportunity_amount"', '"000123","\'=SUM(A1) ""quoted""","12345678901.55"', '"000124","",""']);
  });
  it('preserves signed numeric literals exactly while guarding text, IDs, headers and invalid expressions', () => {
    const numeric = ['-12.50', '+12.50', '-.50', '-12.', '-1.25e-8', '-1+2', ' -12', '-Infinity', '=SUM(A1)', '@VALUE'];
    const csv = csvText({columns: ['opportunity_no', 'comment', 'amount', '-12.5'], column_types: {opportunity_no: 'text', comment: 'text', amount: 'number', '-12.5': 'number'}}, numeric.map(amount => ({opportunity_no: '-0012', comment: '-CMD', amount, '-12.5': null})));
    const lines = csv.slice(1).split('\r\n');
    expect(lines[0]).toBe('"opportunity_no","comment","amount","\'-12.5"');
    expect(lines.slice(1, 6)).toEqual(numeric.slice(0, 5).map(value => `"'-0012","'-CMD","${value}",""`));
    expect(lines.slice(6)).toEqual(numeric.slice(5).map(value => `"'-0012","'-CMD","'${value}",""`));
  });
});
