// Display formatting with exact decimal string arithmetic (values are never converted to floating point) and the
// field catalog that gives every column its business label.
import type {Cell, ColumnType, Grain, TablePayload} from './types';

export const LABELS: Record<string, string> = {
  opportunity_no: 'Opportunity no.', opportunity_name: 'Opportunity', end_customer: 'Customer', opportunity_owner: 'Owner', stage: 'Stage', stage_group: 'Stage group',
  close_date: 'Close date', close_month: 'Close month', created_date: 'Created', last_modified_date: 'Last modified', product_code: 'Product code', pet_name: 'Product',
  product_codes: 'Product codes', product_names: 'Product names', quantity: 'Quantity', opportunity_amount: 'Amount', sku_amount: 'Amount', amount: 'Amount',
  deal_size: 'Deal size (USD)', deal_size_on_pricing_date_usd: 'Deal size (USD)', sku_count: 'Product count', opportunity_count: 'Opportunity count',
  opp_amount_converted_currency: 'Currency', amount_converted_currency: 'Currency', has_amount_discrepancy: 'Amount check', has_quality_warning: 'Data quality',
  probability: 'Probability', age: 'Age', first_channel: 'First channel', comment: 'Comment', subsidiary_subsidiary_code: 'Subsidiary', gscm_product_group_new: 'Product group',
  biz_focus: 'Business focus', business_location: 'Location', division: 'Division', sales_type_detail: 'Sales type', type: 'Type', rollout_period_from: 'Rollout from',
  rollout_period_to: 'Rollout to', source_row_count: 'Source rows', exported_opp_amount_min: 'Exported amount (min)', exported_opp_amount_max: 'Exported amount (max)',
  exported_opp_amount_value_count: 'Exported amount values',
};
export const MEASURE_LABELS: Record<string, string> = {amount: 'Amount', quantity: 'Quantity', sku_count: 'Product count', opportunity_count: 'Opportunity count', deal_size: 'Deal size (USD)'};
export const MONEY = new Set(['amount', 'opportunity_amount', 'sku_amount', 'deal_size', 'deal_size_on_pricing_date_usd', 'exported_opp_amount_min', 'exported_opp_amount_max']);
export const USD = new Set(['deal_size', 'deal_size_on_pricing_date_usd']);
export const CURRENCY_FIELD: Record<Grain, string> = {opportunity: 'opp_amount_converted_currency', opportunity_sku: 'amount_converted_currency'};
export const MONTH_FIELDS = new Set(['close_month']);
export const PERCENT_FIELDS = new Set(['probability']);
export const STAGE_GROUPS: Record<string, 'won' | 'open' | 'lost'> = {Won: 'won', 'Rollout Started': 'won', 'Rollout Finished': 'won', Identified: 'open', Qualified: 'open', Negotiation: 'open', Dropped: 'lost', Lost: 'lost'};
export const OPS: Record<string, string> = {eq: 'is', ne: 'is not', gt: 'more than', ge: 'at least', lt: 'less than', le: 'at most', contains: 'contains', in: 'is one of', between: 'between'};
// Compact default column sets for conversation previews and expanded tables.
export const COMPACT: Record<Grain, string[]> = {opportunity: ['opportunity_name', 'end_customer', 'opportunity_amount', 'stage', 'opportunity_owner', 'close_date'], opportunity_sku: ['opportunity_no', 'pet_name', 'sku_amount', 'quantity', 'stage', 'opportunity_owner']};
export const MERGE: Record<string, string> = {opportunity_name: 'opportunity_no', pet_name: 'product_code'};

export const label = (field: string) => LABELS[field] ?? field.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());

const NUMERIC = /^[+-]?\d+(\.\d+)?([eE][+-]?\d+)?$/;
const parts = (() => { const p = new Intl.NumberFormat().formatToParts(1234567.5); return {group: p.find(x => x.type === 'group')?.value ?? ',', decimal: p.find(x => x.type === 'decimal')?.value ?? '.'}; })();

function decimalParts(text: string) {
  const [base, exp = '0'] = text.toLowerCase().split('e');
  const [integer, fraction = ''] = base.replace(/^[+-]/, '').split('.');
  return {digits: BigInt((base.startsWith('-') ? '-' : '') + integer + fraction), scale: fraction.length - Number(exp)};
}

function decimalText(digits: bigint, scale: number, decimals: number | null) {
  const negative = digits < 0n; if (negative) digits = -digits;
  if (scale < 0) { digits *= 10n ** BigInt(-scale); scale = 0; }
  if (decimals != null && scale > decimals) { const drop = 10n ** BigInt(scale - decimals); const rest = digits % drop; digits = digits / drop + (rest * 2n >= drop ? 1n : 0n); scale = decimals; }
  if (decimals != null && scale < decimals) { digits *= 10n ** BigInt(decimals - scale); scale = decimals; }
  let text = digits.toString(), integer = text, fraction = '';
  if (scale > 0) { text = text.padStart(scale + 1, '0'); integer = text.slice(0, -scale); fraction = text.slice(-scale); }
  if (decimals == null) fraction = fraction.replace(/0+$/, '');
  integer = integer.replace(/\B(?=(\d{3})+(?!\d))/g, parts.group);
  return (negative && digits > 0n ? '-' : '') + integer + (fraction ? parts.decimal + fraction : '');
}

/** Rounded display text of an exact decimal string; null becomes an em dash. */
export function formatNumber(value: Cell, decimals: number | null = null): string {
  if (value == null) return '—';
  const text = String(value); if (!NUMERIC.test(text)) return text;
  const {digits, scale} = decimalParts(text); return decimalText(digits, scale, decimals);
}
export function formatPercent(value: Cell): string {
  if (value == null) return '—';
  const text = String(value); if (!NUMERIC.test(text)) return text;
  const {digits, scale} = decimalParts(text); return decimalText(digits, scale - 2, null) + '%';
}
export function formatDate(value: Cell, monthOnly = false): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value ?? '')); if (!m) return value == null ? '—' : String(value);
  const date = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return new Intl.DateTimeFormat(undefined, monthOnly ? {month: 'short', year: 'numeric', timeZone: 'UTC'} : {day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC'}).format(date);
}
/** "7 Sep, 19:20" in the viewer's local time; the full timestamp with zone is available for a tooltip. */
export function formatUpdated(iso: string | null | undefined): {short: string; full: string} | null {
  if (!iso) return null;
  const date = new Date(iso); if (Number.isNaN(date.getTime())) return {short: iso, full: iso};
  const short = new Intl.DateTimeFormat(undefined, {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'}).format(date);
  const full = new Intl.DateTimeFormat(undefined, {day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZoneName: 'short'}).format(date);
  return {short, full};
}
export function compareValues(a: Cell, b: Cell, type: ColumnType): number {
  if (a == null) return b == null ? 0 : 1; if (b == null) return -1;
  if (type === 'number') {
    const x = decimalParts(String(a)), y = decimalParts(String(b)), scale = Math.max(x.scale, y.scale);
    const left = x.digits * 10n ** BigInt(scale - x.scale), right = y.digits * 10n ** BigInt(scale - y.scale);
    return left < right ? -1 : left > right ? 1 : 0;
  }
  return String(a).localeCompare(String(b));
}
/** Currency of a result: established by the complete population (metadata), never assumed. */
export function currencyOf(table: TablePayload): {code: string | null; mixed: boolean} {
  const c = table.metadata?.currency; if (!c) return {code: null, mixed: false};
  return {code: c.code, mixed: c.mixed};
}
export function headerLabel(table: TablePayload, column: string): string {
  let text = label(column);
  if (MONEY.has(column) && !USD.has(column)) { const {code} = currencyOf(table); if (code) text += ` (${code})`; }   // USD labels already name their currency
  return text;
}
export function cellText(table: TablePayload, row: Record<string, Cell>, column: string): string {
  const value = row[column]; if (value == null) return '—';
  const type = table.column_types[column] ?? 'text';
  if (type === 'number') {
    if (PERCENT_FIELDS.has(column)) return formatPercent(value);
    let text = formatNumber(value, MONEY.has(column) ? 2 : null);
    if (MONEY.has(column) && !USD.has(column) && currencyOf(table).mixed) { const code = row[CURRENCY_FIELD[table.grain]]; if (code != null) text += ' ' + String(code); }
    return text;
  }
  if (type === 'date') return formatDate(value, MONTH_FIELDS.has(column));
  if (type === 'bool') { if (column === 'has_quality_warning') return value ? 'Check' : 'OK'; if (column === 'has_amount_discrepancy') return value ? 'Mismatch' : 'Matches'; return value ? 'Yes' : 'No'; }
  return String(value);
}
export function measureText(table: TablePayload, measure: string, value: Cell): string {
  if (value == null) return '—';
  const text = formatNumber(value, MONEY.has(measure) ? 2 : null);
  const {code} = currencyOf(table);
  const unit = USD.has(measure) ? 'USD' : MONEY.has(measure) && code ? code : '';
  return unit ? `${text} ${unit}` : text;
}
export function axisLabel(table: TablePayload, dimension: string, value: Cell): string {
  if (value == null) return 'Unknown';
  const type = table.column_types[dimension];
  return type === 'date' ? formatDate(value, MONTH_FIELDS.has(dimension)) : type === 'bool' ? (value ? 'Yes' : 'No') : String(value);
}
/** Visible columns: compact defaults for ordinary results, every returned column for explicit selections and aggregates. */
export function visibleColumns(table: TablePayload): string[] {
  if (table.result_kind !== 'rows' || table.columns_mode === 'only') return table.columns.slice();
  const compact = COMPACT[table.grain].filter(c => table.columns.includes(c));
  if (table.columns_mode === 'include') { const defaults = new Set(['opportunity_no', 'product_code', ...compact, ...Object.values(MERGE)]); table.columns.forEach(c => { if (!defaults.has(c) && !isDefaultColumn(table.grain, c)) compact.push(c); }); }
  return compact.length >= 2 ? compact : table.columns.slice();
}
const DEFAULTS: Record<Grain, string[]> = {
  opportunity: ['opportunity_no', 'opportunity_name', 'end_customer', 'opportunity_owner', 'stage', 'close_date', 'product_codes', 'product_names', 'quantity', 'opportunity_amount', 'sku_count', 'opp_amount_converted_currency', 'has_amount_discrepancy', 'has_quality_warning'],
  opportunity_sku: ['opportunity_no', 'product_code', 'pet_name', 'end_customer', 'opportunity_owner', 'stage', 'quantity', 'sku_amount', 'amount_converted_currency', 'has_quality_warning'],
};
export const isDefaultColumn = (grain: Grain, column: string) => DEFAULTS[grain].includes(column);
export function filterText(f: {field: string; operator: string; value: Cell | Cell[]}, types: Record<string, ColumnType>): string {
  const type = types[f.field] ?? (MONEY.has(f.field) || f.field === 'quantity' ? 'number' : /date|month/.test(f.field) ? 'date' : /^has_/.test(f.field) ? 'bool' : 'text');
  const one = (v: Cell) => v == null ? 'empty' : type === 'date' ? formatDate(v, MONTH_FIELDS.has(f.field)) : type === 'number' ? (PERCENT_FIELDS.has(f.field) ? formatPercent(v) : formatNumber(v, null)) : type === 'bool' ? (v ? 'yes' : 'no') : String(v);
  const value = Array.isArray(f.value) ? f.value.map(one).join(f.operator === 'between' ? ' and ' : ', ') : one(f.value);
  return `${label(f.field)} ${OPS[f.operator] ?? f.operator} ${value}`;
}
export function csvText(table: TablePayload, rows: Record<string, Cell>[]): string {
  // Every returned column, the given rows in their order; formula prefixes guarded; values exact.
  const cell = (value: Cell) => { let text = value == null ? '' : String(value); if (/^[\s]*[=+\-@\t\r]/.test(text)) text = "'" + text; return '"' + text.replaceAll('"', '""') + '"'; };
  const lines = [table.columns, ...rows.map(row => table.columns.map(c => row[c]))];
  return '﻿' + lines.map(line => line.map(cell).join(',')).join('\r\n');
}
