// Independent expectations for the browser checks: the documented display rules re-implemented here without
// importing the application's formatting code, so a defect in the renderer cannot hide inside its own helpers.
import type {Cell, TablePayload} from '@/types';

export const LABELS: Record<string, string> = {opportunity_no: 'Opportunity no.', opportunity_name: 'Opportunity', end_customer: 'Customer', opportunity_owner: 'Owner', stage: 'Stage', stage_group: 'Stage group', close_date: 'Close date', close_month: 'Close month',
  created_date: 'Created', last_modified_date: 'Last modified', product_code: 'Product code', pet_name: 'Product', product_codes: 'Product codes', product_names: 'Product names', quantity: 'Quantity', opportunity_amount: 'Amount', sku_amount: 'Amount', amount: 'Amount',
  deal_size: 'Deal size (USD)', sku_count: 'Product count', opportunity_count: 'Opportunity count', opp_amount_converted_currency: 'Currency', amount_converted_currency: 'Currency', has_amount_discrepancy: 'Amount check', has_quality_warning: 'Data quality', probability: 'Probability',
  type: 'Type', first_channel: 'First channel', comment: 'Comment', age: 'Age', subsidiary_subsidiary_code: 'Subsidiary', gscm_product_group_new: 'Product group', biz_focus: 'Business focus', business_location: 'Location', division: 'Division', sales_type_detail: 'Sales type',
  rollout_period_from: 'Rollout from', rollout_period_to: 'Rollout to', source_row_count: 'Source rows', exported_opp_amount_min: 'Exported amount (min)', exported_opp_amount_max: 'Exported amount (max)', exported_opp_amount_value_count: 'Exported amount values', deal_size_on_pricing_date_usd: 'Deal size (USD)'};
export const MEASURE_LABELS: Record<string, string> = {amount: 'Amount', quantity: 'Quantity', sku_count: 'Product count', opportunity_count: 'Opportunity count', deal_size: 'Deal size (USD)'};
export const MONEY = new Set(['amount', 'opportunity_amount', 'sku_amount', 'exported_opp_amount_min', 'exported_opp_amount_max']);
export const STAGE_GROUP: Record<string, string> = {Won: 'won', 'Rollout Started': 'won', 'Rollout Finished': 'won', Identified: 'open', Qualified: 'open', Negotiation: 'open', Dropped: 'lost', Lost: 'lost'};
export const COMPACT: Record<string, string[]> = {opportunity: ['opportunity_name', 'end_customer', 'opportunity_amount', 'stage', 'opportunity_owner', 'close_date'], opportunity_sku: ['opportunity_no', 'pet_name', 'sku_amount', 'quantity', 'stage', 'opportunity_owner']};
export const CURRENCY_FIELD: Record<string, string> = {opportunity: 'opp_amount_converted_currency', opportunity_sku: 'amount_converted_currency'};
export const MERGE: Record<string, string> = {opportunity_name: 'opportunity_no', pet_name: 'product_code'};
const sep = (() => { const parts = new Intl.NumberFormat().formatToParts(1234567.5); return {group: parts.find(p => p.type === 'group')?.value ?? ',', decimal: parts.find(p => p.type === 'decimal')?.value ?? '.'}; })();

export function fmtNumber(value: Cell, decimals: number | null): string {
  if (value == null) return '—'; let s = String(value); if (!/^[+-]?\d+(\.\d+)?$/.test(s)) return s;
  const neg = s.startsWith('-'); s = s.replace(/^[+-]/, ''); let [int, frac = ''] = s.split('.');
  if (decimals != null) {
    if (frac.length > decimals) { const keep = frac.slice(0, decimals), next = frac[decimals]; const digits = (int + keep).split('').map(Number);
      if (next >= '5') { let i = digits.length - 1; while (i >= 0) { if (digits[i] === 9) { digits[i] = 0; i--; } else { digits[i]++; break; } } if (i < 0) digits.unshift(1); }
      const all = digits.join(''); int = all.slice(0, all.length - decimals) || '0'; frac = all.slice(all.length - decimals); }
    else frac = frac.padEnd(decimals, '0');
  } else frac = frac.replace(/0+$/, '');
  int = int.replace(/^0+(?=\d)/, '').replace(/\B(?=(\d{3})+(?!\d))/g, sep.group);
  const zero = /^0*$/.test(int.replace(/\D/g, '')) && /^0*$/.test(frac);
  return (neg && !zero ? '-' : '') + int + (frac ? sep.decimal + frac : '');
}
export function fmtDate(iso: Cell, monthOnly: boolean): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso ?? '')); if (!m) return iso == null ? '—' : String(iso);
  return new Intl.DateTimeFormat(undefined, monthOnly ? {month: 'short', year: 'numeric', timeZone: 'UTC'} : {day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC'}).format(new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])));
}
export function fmtPercent(value: Cell): string {
  if (value == null) return '—'; const s = String(value); if (!/^[+-]?\d+(\.\d+)?$/.test(s)) return s;
  const [int, frac = ''] = s.split('.'); const padded = frac.padEnd(2, '0'); const shifted = int + padded.slice(0, 2) + (padded.length > 2 ? '.' + padded.slice(2) : '');
  return fmtNumber(shifted.replace(/\.$/, ''), null) + '%';
}
export function decimalCompare(a: Cell, b: Cell): number {
  const parse = (v: Cell) => { let s = String(v); const neg = s.startsWith('-'); s = s.replace(/^[+-]/, ''); let [int, frac = ''] = s.split('.'); frac = frac.replace(/0+$/, ''); return {neg, int: int.replace(/^0+(?=\d)/, ''), frac}; };
  const x = parse(a), y = parse(b); const zero = (v: {int: string; frac: string}) => v.int === '0' && v.frac === '';
  if (zero(x) && zero(y)) return 0; if (x.neg !== y.neg) return x.neg ? -1 : 1;
  const mag = (p: typeof x, q: typeof y) => p.int.length !== q.int.length ? (p.int.length < q.int.length ? -1 : 1) : p.int !== q.int ? (p.int < q.int ? -1 : 1) : p.frac === q.frac ? 0 : (p.frac.padEnd(Math.max(p.frac.length, q.frac.length), '0') < q.frac.padEnd(Math.max(p.frac.length, q.frac.length), '0') ? -1 : 1);
  const m = mag(x, y); return x.neg ? -m : m;
}
/** Currency established by the complete population: the metadata says so; the visible cells never decide it. */
export function currency(t: TablePayload): string | null | 'mixed' { const c = t.metadata?.currency; if (!c) return null; return c.mixed ? 'mixed' : c.code; }
export function expectedHeader(t: TablePayload, column: string): string { let text = LABELS[column] ?? column; if (MONEY.has(column)) { const cur = currency(t); if (cur && cur !== 'mixed') text += ` (${cur})`; } if (column === 'deal_size' || column === 'deal_size_on_pricing_date_usd') { /* label already carries USD */ } return text; }
export function expectedCell(t: TablePayload, row: Record<string, Cell>, column: string): string {
  const v = row[column]; const type = t.column_types[column]; if (v == null) return '—';
  if (type === 'number') { if (column === 'probability') return fmtPercent(v); let s = fmtNumber(v, MONEY.has(column) ? 2 : null); if (MONEY.has(column) && currency(t) === 'mixed' && row[CURRENCY_FIELD[t.grain]] != null) s += ' ' + row[CURRENCY_FIELD[t.grain]]; return s; }
  if (type === 'date') return fmtDate(v, column === 'close_month');
  if (type === 'bool') { if (column === 'has_quality_warning') return v ? 'Check' : 'OK'; if (column === 'has_amount_discrepancy') return v ? 'Mismatch' : 'Matches'; return v ? 'Yes' : 'No'; }
  return String(v);
}
export function expectedVisible(t: TablePayload): string[] {
  if (t.result_kind !== 'rows' || t.columns_mode === 'only') return t.columns.slice();
  const compact = COMPACT[t.grain].filter(c => t.columns.includes(c));
  const defaults = new Set(['opportunity_no', 'product_code', ...compact, ...Object.values(MERGE), ...DEFAULTS[t.grain]]);
  if (t.columns_mode === 'include') t.columns.forEach(c => { if (!defaults.has(c)) compact.push(c); });
  return compact.length >= 2 ? compact : t.columns.slice();
}
const DEFAULTS: Record<string, string[]> = {opportunity: ['opportunity_no', 'opportunity_name', 'end_customer', 'opportunity_owner', 'stage', 'close_date', 'product_codes', 'product_names', 'quantity', 'opportunity_amount', 'sku_count', 'opp_amount_converted_currency', 'has_amount_discrepancy', 'has_quality_warning'], opportunity_sku: ['opportunity_no', 'product_code', 'pet_name', 'end_customer', 'opportunity_owner', 'stage', 'quantity', 'sku_amount', 'amount_converted_currency', 'has_quality_warning']};
export function expectedRowText(t: TablePayload, visible: string[], row: Record<string, Cell>): string[] {
  return visible.map(c => { const partner = MERGE[c]; if (partner && t.columns.includes(partner) && !visible.includes(partner)) return expectedCell(t, row, c) + (row[partner] == null ? '' : String(row[partner])); return expectedCell(t, row, c); });
}
export function measureText(t: TablePayload, m: string, v: Cell): string { if (v == null) return '—'; const s = fmtNumber(v, MONEY.has(m) ? 2 : null); const cur = m === 'deal_size' ? 'USD' : MONEY.has(m) ? currency(t) : null; return cur && cur !== 'mixed' ? `${s} ${cur}` : s; }
export function axisLabel(t: TablePayload, dimension: string, v: Cell): string { if (v == null) return 'Unknown'; return t.column_types[dimension] === 'date' ? fmtDate(v, dimension === 'close_month') : String(v); }
export function csvExpected(t: TablePayload, rows: Record<string, Cell>[]): string {
  const quote = (v: Cell) => { let s = v == null ? '' : String(v); if (/^[\s]*[=+\-@\t\r]/.test(s)) s = "'" + s; return '"' + s.replaceAll('"', '""') + '"'; };
  return '﻿' + [t.columns.map(quote).join(','), ...rows.map(r => t.columns.map(c => quote(r[c])).join(','))].join('\r\n');
}
export const OPS: Record<string, string> = {eq: 'is', ne: 'is not', gt: 'more than', ge: 'at least', lt: 'less than', le: 'at most', contains: 'contains', in: 'is one of', between: 'between'};
export function expectedChip(t: TablePayload, f: {field: string; operator: string; value: Cell | Cell[]}): string {
  const type = t.column_types[f.field] ?? (MONEY.has(f.field) || f.field === 'quantity' ? 'number' : /date|month/.test(f.field) ? 'date' : /^has_/.test(f.field) ? 'bool' : 'text');
  const one = (v: Cell) => v == null ? 'empty' : type === 'date' ? fmtDate(v, f.field === 'close_month') : type === 'number' ? (f.field === 'probability' ? fmtPercent(v) : fmtNumber(v, null)) : type === 'bool' ? (v ? 'yes' : 'no') : String(v);
  const value = Array.isArray(f.value) ? f.value.map(one).join(f.operator === 'between' ? ' and ' : ', ') : one(f.value);
  return `${LABELS[f.field] ?? f.field} ${OPS[f.operator] ?? f.operator} ${value}`;
}
