'use strict';
// Answer-first analysis workspace. The backend contract (QueryPlanV1, /api/*) is unchanged; this file only
// presents results. Formatting rules live in one place (the field catalog below) so headings, filter
// chips, tables, and charts describe fields with the same business terms.
const $ = id => document.getElementById(id);
const SVG = 'http://www.w3.org/2000/svg';
const reducedMotion = () => !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
function node(tag, className, text) { const el = document.createElement(tag); if (className) el.className = className; if (text != null) el.textContent = text; return el; }
function icon(name) { const svg = document.createElementNS(SVG, 'svg'); svg.setAttribute('class', 'icon'); svg.setAttribute('aria-hidden', 'true'); const use = document.createElementNS(SVG, 'use'); use.setAttribute('href', '#' + name); svg.append(use); return svg; }
function button(className, label, iconName) { const el = node('button', className); el.type = 'button'; if (iconName) el.append(icon(iconName)); el.append(node('span', '', label)); return el; }

// ----- field catalog: business labels and formatting rules -----
const LABELS = {
  opportunity_no: 'Opportunity no.', opportunity_name: 'Opportunity', end_customer: 'Customer', opportunity_owner: 'Owner', stage: 'Stage', stage_group: 'Stage group',
  close_date: 'Close date', close_month: 'Close month', created_date: 'Created', last_modified_date: 'Last modified', product_code: 'Product code', pet_name: 'Product',
  product_codes: 'Product codes', product_names: 'Product names', quantity: 'Quantity', opportunity_amount: 'Amount', sku_amount: 'Amount', amount: 'Amount',
  deal_size: 'Deal size (USD)', deal_size_on_pricing_date_usd: 'Deal size (USD)', sku_count: 'Product count', opportunity_count: 'Opportunity count',
  opp_amount_converted_currency: 'Currency', amount_converted_currency: 'Currency', has_amount_discrepancy: 'Amount check', has_quality_warning: 'Data quality',
  probability: 'Probability', age: 'Age', first_channel: 'First channel', comment: 'Comment', subsidiary_subsidiary_code: 'Subsidiary', gscm_product_group_new: 'Product group',
  biz_focus: 'Business focus', business_location: 'Location', division: 'Division', sales_type_detail: 'Sales type', type: 'Type', rollout_period_from: 'Rollout from',
  rollout_period_to: 'Rollout to', source_row_count: 'Source rows', exported_opp_amount_min: 'Exported amount (min)', exported_opp_amount_max: 'Exported amount (max)',
  exported_opp_amount_value_count: 'Exported amount values'
};
const MEASURE_LABELS = {amount: 'Amount', quantity: 'Quantity', sku_count: 'Product count', opportunity_count: 'Opportunity count', deal_size: 'Deal size (USD)'};
const MEASURE_TITLES = {amount: 'Total amount', quantity: 'Total quantity', sku_count: 'Product count', opportunity_count: 'Opportunity count', deal_size: 'Total deal size (USD)'};
const MEASURES = new Set(Object.keys(MEASURE_LABELS));
const MONEY = new Set(['amount', 'opportunity_amount', 'sku_amount', 'deal_size', 'deal_size_on_pricing_date_usd', 'exported_opp_amount_min', 'exported_opp_amount_max']);
const USD = new Set(['deal_size', 'deal_size_on_pricing_date_usd']);
const CURRENCY_FIELDS = ['opp_amount_converted_currency', 'amount_converted_currency'];
const MONTH_FIELDS = new Set(['close_month']);
const PERCENT_FIELDS = new Set(['probability']);
const WRAP_FIELDS = new Set(['comment', 'product_names', 'product_codes', 'opportunity_name']);
const STAGE_GROUPS = {Won: ['Won', 'Rollout Started', 'Rollout Finished'], Open: ['Identified', 'Qualified', 'Negotiation'], Lost: ['Dropped', 'Lost']};
const BOOL_BADGES = {has_quality_warning: {true: ['Warning', 'warn'], false: ['OK', 'ok']}, has_amount_discrepancy: {true: ['Mismatch', 'warn'], false: ['Matches', 'ok']}};
const OPS = {eq: 'is', ne: 'is not', gt: 'more than', ge: 'at least', lt: 'less than', le: 'at most', contains: 'contains', in: 'is one of', between: 'between'};
// Compact column sets for the default table layouts; everything else stays reachable through Columns and row details.
const COMPACT = {opportunity: ['opportunity_name', 'end_customer', 'opportunity_amount', 'stage', 'opportunity_owner', 'close_date'], opportunity_sku: ['opportunity_no', 'pet_name', 'sku_amount', 'quantity', 'stage', 'opportunity_owner']};
const MERGE = {opportunity_name: 'opportunity_no', pet_name: 'product_code'};
const label = field => LABELS[field] || String(field).replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
const stageGroup = value => Object.keys(STAGE_GROUPS).find(group => STAGE_GROUPS[group].includes(value)) || (value in STAGE_GROUPS ? value : null);

// ----- exact decimal handling: strings are never converted to floating point -----
const NUMERIC = /^[+-]?\d+(\.\d+)?([eE][+-]?\d+)?$/;
const numberParts = (() => { const parts = new Intl.NumberFormat().formatToParts(1234567.5); return {group: parts.find(p => p.type === 'group')?.value ?? ',', decimal: parts.find(p => p.type === 'decimal')?.value ?? '.'}; })();
function decimalParts(value) {
  const [base, exp = '0'] = String(value).toLowerCase().split('e');
  const [integer, fraction = ''] = base.replace(/^[+-]/, '').split('.');
  return {digits: BigInt((base.startsWith('-') ? '-' : '') + (integer + fraction)), scale: fraction.length - Number(exp)};
}
function decimalText(digits, scale, decimals) {
  // decimals: fixed number of places (rounded half up) or null to trim trailing zeros.
  const negative = digits < 0n; if (negative) digits = -digits;
  if (scale < 0) { digits *= 10n ** BigInt(-scale); scale = 0; }
  if (decimals != null && scale > decimals) { const drop = 10n ** BigInt(scale - decimals); const rest = digits % drop; digits = digits / drop + (rest * 2n >= drop ? 1n : 0n); scale = decimals; }
  if (decimals != null && scale < decimals) { digits *= 10n ** BigInt(decimals - scale); scale = decimals; }
  let text = digits.toString(), integer = text, fraction = '';
  if (scale > 0) { text = text.padStart(scale + 1, '0'); integer = text.slice(0, -scale); fraction = text.slice(-scale); }
  if (decimals == null) fraction = fraction.replace(/0+$/, '');
  integer = integer.replace(/\B(?=(\d{3})+(?!\d))/g, numberParts.group);
  return (negative && (digits > 0n) ? '-' : '') + integer + (fraction ? numberParts.decimal + fraction : '');
}
function formatNumber(value, decimals = null) {
  if (value == null) return '—'; const text = String(value); if (!NUMERIC.test(text)) return text;
  const {digits, scale} = decimalParts(text); return decimalText(digits, scale, decimals);
}
function formatPercent(value) {
  if (value == null) return '—'; const text = String(value); if (!NUMERIC.test(text)) return text;
  const {digits, scale} = decimalParts(text); return decimalText(digits, scale - 2, null) + '%';
}
function formatDate(value, monthOnly) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value ?? '')); if (!match) return String(value ?? '—');
  const date = new Date(Date.UTC(+match[1], +match[2] - 1, +match[3]));
  return new Intl.DateTimeFormat(undefined, monthOnly ? {month: 'short', year: 'numeric', timeZone: 'UTC'} : {day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC'}).format(date);
}
function formatStamp(iso) { if (!iso) return 'unknown time'; const date = new Date(iso); return Number.isNaN(date.getTime()) ? String(iso) : new Intl.DateTimeFormat(undefined, {day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'}).format(date); }
function compareValues(a, b, type) {
  if (a == null) return b == null ? 0 : 1; if (b == null) return -1;
  if (type === 'number') {
    const x = decimalParts(a), y = decimalParts(b), scale = Math.max(x.scale, y.scale);
    const left = x.digits * 10n ** BigInt(scale - x.scale), right = y.digits * 10n ** BigInt(scale - y.scale);
    return left < right ? -1 : left > right ? 1 : 0;
  }
  return String(a).localeCompare(String(b));
}
function csvText(table) {
  // Every returned column and every displayed row in the current sort order; formula prefixes are guarded.
  const cell = value => { let text = value == null ? '' : String(value); if (/^[\s]*[=+\-@\t\r]/.test(text)) text = "'" + text; return '"' + text.replaceAll('"', '""') + '"'; };
  const rows = [table.columns, ...table.rows.map(row => table.columns.map(c => row[c]))];
  return '﻿' + rows.map(row => row.map(cell).join(',')).join('\r\n');
}
function resolveCurrency(table) {
  // A currency is stated only when the payload establishes it: a returned currency column or an unambiguous filter.
  const field = CURRENCY_FIELDS.find(name => table.columns.includes(name));
  if (field) { const codes = new Set(table.rows.map(row => row[field]).filter(value => value != null)); if (codes.size === 1) return {mode: 'uniform', code: [...codes][0], field}; if (codes.size > 1) return {mode: 'row', field}; }
  const filter = (table.filters || []).find(f => CURRENCY_FIELDS.includes(f.field) && f.value != null && (f.operator === 'eq' || (f.operator === 'in' && Array.isArray(f.value) && f.value.length === 1)));
  if (filter) return {mode: 'uniform', code: String(Array.isArray(filter.value) ? filter.value[0] : filter.value)};
  return {mode: 'none'};
}
function filterValueText(field, value, type) {
  if (value == null) return 'empty';
  if (Array.isArray(value)) return value.map(v => filterValueText(field, v, type)).join(', ');
  if (type === 'date') return formatDate(value, MONTH_FIELDS.has(field));
  if (type === 'number') return PERCENT_FIELDS.has(field) ? formatPercent(value) : formatNumber(value, null);
  if (type === 'bool') return value ? 'yes' : 'no';
  return String(value);
}
function filterChip(filter, types) {
  const type = types[filter.field] || (MEASURES.has(filter.field) ? 'number' : /date|month/.test(filter.field) ? 'date' : /^has_/.test(filter.field) ? 'bool' : 'text');
  const chip = node('span', 'filter-chip'); chip.append(node('span', 'f', label(filter.field) + ' '));
  const value = filter.operator === 'between' && Array.isArray(filter.value) ? filter.value.map(v => filterValueText(filter.field, v, type)).join(' and ') : filterValueText(filter.field, filter.value, type);
  chip.append(document.createTextNode(`${OPS[filter.operator] || filter.operator} ${value}`)); return chip;
}
function resultTitle(table) {
  if (table.intent === 'table') return table.grain === 'opportunity' ? 'Opportunities' : 'Opportunity products';
  const measures = table.columns.filter(c => MEASURES.has(c)), dimensions = table.columns.filter(c => !MEASURES.has(c));
  const joined = (items, map) => items.map(name => map[name] || label(name)).join(' and ');
  if (!dimensions.length) return measures.length === 1 ? MEASURE_TITLES[measures[0]] : 'Totals';
  return `${joined(measures, MEASURE_LABELS) || 'Results'} by ${joined(dimensions, {})}`;
}
function unitFor(table) { return table.intent === 'table' ? (table.grain === 'opportunity' ? 'opportunities' : 'product rows') : 'groups'; }

// Chart layout constants; the acceptance suite recomputes coordinates from these independently.
const CHART = {height: 300, left: 75, right: 25, top: 25, bottom: 65, minWidth: 400, maxGroups: 30};
const PALETTE = {ink: '#203B34', muted: '#53665B', grid: '#D8E0DA', bar: '#234A3D', line: '#234A3D'};
function recording(ctx, ops) {
  return new Proxy(ctx, {get(target, prop) { const value = target[prop]; if (typeof value !== 'function') return value; return (...args) => { ops.push([prop, args.map(a => typeof a === 'number' ? a : String(a))]); return value.apply(target, args); }; },
    set(target, prop, value) { target[prop] = value; return true; }});
}

class ResultView {
  // One rendered result: heading, filters, metric cards, chart, table, details, follow-ups.
  // Plain mode (the acceptance panel) shows every column with raw text so the suite can compare cell by cell.
  constructor(root) {
    this.root = root; this.plain = root.dataset.plain === 'true'; this.table = null; this.sortState = {}; this.plot = null; this.ops = null; this.recordOps = false;
    this.visible = []; this.chartRows = []; this.currency = {mode: 'none'}; this.options = {};
    this.q = selector => root.querySelector(selector);
    this.q('.chart-measure').addEventListener('change', () => this.drawChart());
    this.q('.export').addEventListener('click', () => this.export());
    this.onResize = () => requestAnimationFrame(() => this.drawChart()); window.addEventListener('resize', this.onResize);
    const canvas = this.q('.chart'); canvas.addEventListener('pointermove', event => this.hover(event)); canvas.addEventListener('pointerleave', () => this.hideTip());
    if (this.plain) { this.q('.columns-menu').hidden = true; this.q('.result-question').hidden = true; }
  }
  destroy() { window.removeEventListener('resize', this.onResize); }
  clear() { this.root.hidden = true; this.table = null; this.plot = null; }
  typeOf(column) { return (this.table && this.table.column_types && this.table.column_types[column]) || (MEASURES.has(column) ? 'number' : 'text'); }
  headerLabel(column) {
    if (this.plain) return column.replaceAll('_', ' ');
    let text = label(column);
    if (MONEY.has(column)) text += USD.has(column) ? ' (USD)' : this.currency.mode === 'uniform' ? ` (${this.currency.code})` : '';
    return text;
  }
  hiddenColumns() { const merged = this.visible.map(c => MERGE[c]).filter(partner => partner && this.table.columns.includes(partner) && !this.visible.includes(partner)); return this.table.columns.filter(c => !this.visible.includes(c) && !merged.includes(c)); }
  defaultColumns() {
    const table = this.table, plan = this.options.plan;
    if (this.plain || table.intent !== 'table' || (plan && plan.dimensions && plan.dimensions.length)) return table.columns.slice();
    const compact = (COMPACT[table.grain] || []).filter(c => table.columns.includes(c));
    (plan && plan.measures ? plan.measures : []).forEach(m => { if (table.columns.includes(m) && !compact.includes(m)) compact.push(m); });
    return compact.length >= 2 ? compact : table.columns.slice();
  }
  cellNode(column, value, record) {
    // Returns [node or text, css class]. Null stays visibly unavailable; nothing is coerced to zero.
    if (value == null) return ['—', 'null'];
    const type = this.typeOf(column);
    if (type === 'bool' && BOOL_BADGES[column]) { const [text, cls] = BOOL_BADGES[column][value ? 'true' : 'false']; return [node('span', 'badge ' + cls, text), '']; }
    if (type === 'bool') return [value ? 'Yes' : 'No', ''];
    if (type === 'number') {
      if (PERCENT_FIELDS.has(column)) return [formatPercent(value), 'num'];
      let text = formatNumber(value, MONEY.has(column) ? 2 : null);
      if (MONEY.has(column) && !USD.has(column) && this.currency.mode === 'row' && record && record[this.currency.field] != null) text += ' ' + record[this.currency.field];
      return [text, 'num'];
    }
    if (type === 'date') return [formatDate(value, MONTH_FIELDS.has(column)), ''];
    if (column === 'stage' || column === 'stage_group') { const group = stageGroup(value); return [node('span', 'badge' + (group ? ' ' + group.toLowerCase() : ''), String(value)), '']; }
    return [String(value), WRAP_FIELDS.has(column) ? 'wrap' : ''];
  }
  fillCell(cell, column, record) {
    if (this.plain) { cell.textContent = record[column] ?? '—'; return; }
    const partner = MERGE[column];
    if (partner && this.table.columns.includes(partner) && !this.visible.includes(partner)) {
      const wrap = node('div', 'id-cell'); const [content, cls] = this.cellNode(column, record[column], record);
      const main = node('span', cls === 'null' ? 'null' : ''); main.append(content); wrap.append(main);
      if (record[partner] != null) wrap.append(node('span', 'id', String(record[partner])));
      cell.append(wrap); return;
    }
    const [content, cls] = this.cellNode(column, record[column], record); if (cls) cell.classList.add(cls); cell.append(content);
  }
  drawRows() {
    const body = this.q('.table').tBodies[0]; body.replaceChildren();
    const hidden = this.plain ? [] : this.hiddenColumns();
    this.table.rows.forEach(record => {
      const row = body.insertRow(); if (!this.plain && record.has_quality_warning === true) row.classList.add('flagged');
      this.visible.forEach((column, index) => {
        const cell = row.insertCell(); if (!this.plain && index === 0) cell.classList.add('pin');
        if (!this.plain && index === 0 && hidden.length) {
          const toggle = button('row-toggle', '', 'i-chevron'); toggle.setAttribute('aria-expanded', 'false'); toggle.setAttribute('aria-label', 'Show all fields for this row');
          toggle.addEventListener('click', () => this.toggleDetails(row, toggle, record)); cell.append(toggle);
        }
        this.fillCell(cell, column, record);
      });
    });
  }
  toggleDetails(row, toggle, record) {
    const open = toggle.getAttribute('aria-expanded') === 'true';
    if (open) { toggle.setAttribute('aria-expanded', 'false'); if (row.nextElementSibling?.classList.contains('detail-row')) row.nextElementSibling.remove(); return; }
    toggle.setAttribute('aria-expanded', 'true');
    const detail = document.createElement('tr'); detail.className = 'detail-row'; const cell = detail.insertCell(); cell.colSpan = this.visible.length;
    const list = node('dl', 'detail-grid');
    this.hiddenColumns().forEach(column => { const item = node('div'); item.append(node('dt', '', this.headerLabel(column))); const value = node('dd'); const [content, cls] = this.cellNode(column, record[column], record); if (cls === 'null') value.classList.add('null'); value.append(content); item.append(value); list.append(item); });
    cell.append(list); row.after(detail);
  }
  drawHead() {
    const table = this.q('.table'); if (table.tHead) table.tHead.remove(); const head = table.createTHead().insertRow();
    this.visible.forEach((column, index) => {
      const th = document.createElement('th'); th.scope = 'col'; th.dataset.column = column;
      if (!this.plain) { if (index === 0) th.classList.add('pin'); if (this.typeOf(column) === 'number' && !MERGE[column]) th.classList.add('num'); }
      const control = node('button', 'column-sort', this.headerLabel(column) + ' ↕'); control.type = 'button'; control.title = 'Sort displayed rows';
      control.addEventListener('click', () => this.sortBy(column)); th.append(control); head.append(th);
      if (this.sortState[column]) { th.setAttribute('aria-sort', this.sortState[column] === 1 ? 'ascending' : 'descending'); control.textContent = this.headerLabel(column) + (this.sortState[column] === 1 ? ' ↑' : ' ↓'); }
    });
    if (!table.tBodies.length) table.createTBody();
  }
  drawColumnsMenu() {
    const list = this.q('.columns-list'); list.replaceChildren(); if (this.plain) return;
    this.table.columns.forEach(column => {
      const item = node('label'); const box = document.createElement('input'); box.type = 'checkbox'; box.checked = this.visible.includes(column);
      box.addEventListener('change', () => {
        if (box.checked) { const index = this.table.columns.indexOf(column), next = this.visible.findIndex(c => this.table.columns.indexOf(c) > index); this.visible = next === -1 ? [...this.visible, column] : [...this.visible.slice(0, next), column, ...this.visible.slice(next)]; }
        else if (this.visible.length > 1) { this.visible = this.visible.filter(c => c !== column); }
        else { box.checked = true; return; }
        this.drawHead(); this.drawRows();
      });
      item.append(box, document.createTextNode(this.headerLabel(column))); list.append(item);
    });
  }
  render(table, options = {}) {
    const q = this.q; this.table = table; this.options = options; this.sortState = {}; this.root.hidden = false; this.root.classList.remove('previous'); this.hideTip();
    this.currency = resolveCurrency(table); this.visible = this.defaultColumns(); this.chartRows = table.rows.slice(0, CHART.maxGroups);
    const grouped = table.intent !== 'table', measures = table.columns.filter(c => MEASURES.has(c)), ungrouped = grouped && measures.length === table.columns.length;
    const total = table.total_rows, shown = table.rows.length, unit = unitFor(table);
    q('.result-question').textContent = options.question || '';
    q('.result-title').textContent = resultTitle(table);
    const meta = q('.result-meta'); meta.replaceChildren();
    const scope = ungrouped ? (total ? 'Totals across every matching row' : 'No matching rows') : total === 0 ? `No matching ${unit}` : table.truncated ? `Showing the first ${shown.toLocaleString()} of ${total.toLocaleString()} ${unit} (limited preview)` : `All ${total.toLocaleString()} ${unit}`;
    meta.append(node('span', 'strong', scope), node('span', '', `Data loaded ${formatStamp(table.snapshot_at)}`));
    if (table.columns.some(c => MONEY.has(c) && !USD.has(c)) && this.currency.mode === 'none') meta.append(node('span', '', 'Currency not provided'));
    const filters = q('.filters'); filters.replaceChildren(); (table.filters || []).forEach(f => filters.append(filterChip(f, table.column_types || {})));
    q('.warnings').replaceChildren(); (table.warnings || []).forEach(text => q('.warnings').append(node('p', 'warning', text)));
    q('.stale').hidden = true; q('.stale').replaceChildren();
    q('.export-label').textContent = this.plain ? 'CSV' : `Export displayed rows (${table.truncated ? `${shown.toLocaleString()} of ${total.toLocaleString()}` : shown.toLocaleString()})`;
    // Metric cards for an ungrouped metric; otherwise the table (and chart) carry the answer.
    const metrics = q('.metrics'); metrics.replaceChildren(); metrics.hidden = !(ungrouped && !this.plain && table.rows.length);
    if (!metrics.hidden) measures.forEach(name => { const card = node('div', 'metric'); card.append(node('div', 'metric-label', MEASURE_LABELS[name] || label(name))); const value = node('div', 'metric-value', formatNumber(table.rows[0][name], MONEY.has(name) ? 2 : null)); const code = this.measureUnit(name); if (code) value.append(node('span', 'metric-unit', code)); card.append(value); metrics.append(card); });
    q('.table').replaceChildren(); this.drawHead(); this.drawRows(); this.drawColumnsMenu();
    q('.table-wrap').hidden = !metrics.hidden || total === 0;
    // Empty state: keep the filters visible and offer to edit the question.
    const empty = q('.empty-result'); empty.replaceChildren(); empty.hidden = total !== 0 || this.plain;
    if (!empty.hidden) { empty.append(node('h3', '', 'No results match this question')); const chips = node('div', 'filters'); (table.filters || []).forEach(f => chips.append(filterChip(f, table.column_types || {}))); if (chips.children.length) empty.append(chips); else empty.append(node('p', '', 'No filters were applied; the data source returned no rows.'));
      if (options.onEdit) { const edit = button('ghost small', 'Edit question'); edit.addEventListener('click', () => options.onEdit(options.question || '')); empty.append(edit); } }
    // Query details: technical scope stays available without competing with the answer.
    const facts = q('.query-details .facts'); facts.replaceChildren();
    [['Source', table.source_name ? `${table.source_name} (${table.source})` : table.source], ['Layout', table.grain === 'opportunity' ? 'One row per opportunity' : 'One row per opportunity and product'], ['Result type', table.intent], ['Source rows', table.source_rows != null ? table.source_rows.toLocaleString() : null], ['Result digest', table.result_digest], ['Scope', table.scope]]
      .forEach(([term, value]) => { if (value == null || value === '') return; facts.append(node('dt', '', term)); facts.append(node('dd', '', String(value))); });
    q('.filters-json').textContent = table.filters && table.filters.length ? JSON.stringify(table.filters, null, 2) : '';
    const follow = q('.followups'); follow.replaceChildren();
    if (!this.plain && options.suggestions && options.suggestions.length) { follow.append(node('span', 'followups-label', 'Ask next')); options.suggestions.forEach(text => { const chip = node('button', 'chip', text); chip.type = 'button'; chip.addEventListener('click', () => options.onFollowup && options.onFollowup(text)); follow.append(chip); }); }
    // Chart above the table; its rows are frozen now so later table sorting never changes what the chart shows.
    q('.chart-panel').hidden = !table.chart || total === 0; q('.chart-measure').replaceChildren(); this.plot = null;
    if (table.chart) { table.chart.measures.forEach(name => q('.chart-measure').add(new Option(this.plain ? name.replaceAll('_', ' ') : (MEASURE_LABELS[name] || label(name)), name))); q('.chart-measure-label').hidden = table.chart.type === 'scatter' || table.chart.measures.length < 2; if (this.root.isConnected) this.drawChart(); else requestAnimationFrame(() => this.drawChart()); }
  }
  measureUnit(name) { if (!MONEY.has(name)) return ''; if (USD.has(name)) return 'USD'; return this.currency.mode === 'uniform' ? this.currency.code : ''; }
  formatMeasure(name, value) { if (value == null) return '—'; const text = MEASURES.has(name) || this.typeOf(name) === 'number' ? formatNumber(value, MONEY.has(name) ? 2 : null) : String(value); const unit = this.measureUnit(name); return unit ? `${text} ${unit}` : text; }
  axisLabel(dimension, value) { if (value == null) return 'Unknown'; if (this.plain) return String(value); const type = this.typeOf(dimension); return type === 'date' ? formatDate(value, MONTH_FIELDS.has(dimension)) : type === 'bool' ? (value ? 'Yes' : 'No') : String(value); }
  markStale(text, action) { const box = this.q('.stale'); box.replaceChildren(); box.classList.remove('error'); box.append(node('span', '', text)); if (action) { const run = button('primary small', action.label); run.addEventListener('click', action.run); box.append(run); } box.hidden = false; }
  markRefreshFailed(text) { const box = this.q('.stale'); box.replaceChildren(); box.classList.add('error'); box.append(node('span', '', text)); box.hidden = false; }
  sortBy(name) {
    const table = this.table, direction = this.sortState[name] === 1 ? -1 : 1; this.sortState = {[name]: direction};
    const head = this.q('.table').tHead.rows[0];
    head.querySelectorAll('th').forEach(cell => { cell.removeAttribute('aria-sort'); const control = cell.querySelector('button'); control.textContent = this.headerLabel(cell.dataset.column) + ' ↕'; });
    const th = [...head.cells].find(cell => cell.dataset.column === name); th.setAttribute('aria-sort', direction === 1 ? 'ascending' : 'descending'); th.querySelector('button').textContent = this.headerLabel(name) + (direction === 1 ? ' ↑' : ' ↓');
    table.rows.sort((a, b) => a[name] == null || b[name] == null ? compareValues(a[name], b[name], this.typeOf(name)) : direction * compareValues(a[name], b[name], this.typeOf(name))); this.drawRows();
    if (this.plain) this.drawChart();
  }
  sortColumn(name, direction) {
    // Programmatic sort used by the acceptance checks: same code path as a header click.
    if (direction === -1 && this.sortState[name] !== 1) this.sortState = {[name]: 1};
    if (direction === 1) this.sortState = {};
    this.sortBy(name);
  }
  export() {
    if (!this.table) return;
    const url = URL.createObjectURL(new Blob([csvText(this.table)], {type: 'text/csv;charset=utf-8'}));
    const link = document.createElement('a'); link.href = url; link.download = `b2b-${this.table.grain}.csv`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  prepareCanvas(canvas, width, height) {
    const dpr = window.devicePixelRatio || 1; canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr); canvas.style.width = width + 'px'; canvas.style.height = height + 'px';
    const ops = []; const ctx = this.recordOps ? recording(canvas.getContext('2d'), ops) : canvas.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); return {ctx, ops};
  }
  drawChart() {
    const table = this.table; if (!table?.chart || this.root.hidden || !this.root.isConnected) return;
    const spec = table.chart, canvas = this.q('.chart'), rows = this.plain ? table.rows.slice(0, CHART.maxGroups) : this.chartRows;
    const width = Math.max(CHART.minWidth, canvas.parentElement.clientWidth), measure = this.q('.chart-measure').value, dimension = spec.dimensions[0], scatter = spec.type === 'scatter';
    const limited = table.rows.length > CHART.maxGroups;
    let plot, ops;
    if (!this.plain && spec.type === 'bar') ({plot, ops} = this.drawBars(canvas, rows, width, measure, dimension));
    else ({plot, ops} = this.drawVertical(canvas, rows, width, measure, dimension, scatter, spec));
    plot.displayed = rows.length; plot.limited = limited;
    const rawName = scatter ? spec.measures.join(' vs ') : measure + ' by ' + dimension;
    const caption = this.plain ? `${rawName} · ${rows.length} displayed groups${limited ? ` (chart limited to first ${CHART.maxGroups}; table contains the rest)` : ''}. Exact values are in the table.`
      : `${scatter ? spec.measures.map(m => MEASURE_LABELS[m] || label(m)).join(' versus ') : `${MEASURE_LABELS[measure] || label(measure)} by ${label(dimension)}`} · ${rows.length.toLocaleString()} ${rows.length === 1 ? 'group' : 'groups'} shown. Exact values are in the table below.`;
    this.q('.chart-caption').textContent = caption; canvas.setAttribute('aria-label', caption);
    const limit = this.q('.chart-limit'); limit.hidden = !limited; limit.textContent = limited ? `Chart limited to the first ${CHART.maxGroups} of ${table.rows.length.toLocaleString()} groups; the table contains the rest.` : '';
    plot.caption = caption; this.plot = plot; this.ops = this.recordOps ? ops : null;
  }
  drawVertical(canvas, rows, width, measure, dimension, scatter, spec) {
    // Vertical bars (plain mode), lines, areas, and scatter plots share the legacy layout constants.
    const height = CHART.height, {ctx, ops} = this.prepareCanvas(canvas, width, height);
    const {left, right, top, bottom} = CHART, w = width - left - right, h = height - top - bottom;
    ctx.clearRect(0, 0, width, height); ctx.font = '11px Segoe UI, system-ui, sans-serif'; ctx.fillStyle = PALETTE.muted; ctx.strokeStyle = PALETTE.grid; ctx.lineWidth = 1;
    const values = rows.map(row => row[scatter ? spec.measures[1] : measure]).filter(value => value != null).map(Number).filter(Number.isFinite);
    let min = Math.min(0, ...values), max = Math.max(0, ...values); if (min === max) max = min + 1;
    const y = value => top + h - (value - min) / (max - min) * h;
    const plot = {type: spec.type, width, height, left, right, top, bottom, min, max, measure: scatter ? spec.measures[1] : measure, dimension, bars: [], points: [], scatter: null, zero: y(0)};
    for (let i = 0; i <= 4; i++) { const value = min + (max - min) * i / 4, position = y(value); ctx.beginPath(); ctx.moveTo(left, position); ctx.lineTo(width - right, position); ctx.stroke(); ctx.fillText(new Intl.NumberFormat(undefined, {notation: 'compact'}).format(value), 5, position + 4); }
    ctx.save(); ctx.fillStyle = PALETTE.line; ctx.strokeStyle = PALETTE.line; ctx.lineWidth = 2;
    if (scatter) {
      const xs = rows.map(r => r[spec.measures[0]] == null ? null : Number(r[spec.measures[0]])), finite = xs.filter(value => value != null && Number.isFinite(value)); let lo = finite.length ? Math.min(...finite) : 0, hi = finite.length ? Math.max(...finite) : 1; if (lo === hi) hi = lo + 1;
      plot.scatter = {lo, hi, xMeasure: spec.measures[0], points: []};
      rows.forEach((row, i) => { if (row[spec.measures[0]] == null || row[spec.measures[1]] == null) return; const x = left + (xs[i] - lo) / (hi - lo) * w, py = y(Number(row[spec.measures[1]])); plot.scatter.points.push({x, y: py, xValue: row[spec.measures[0]], yValue: row[spec.measures[1]], label: this.axisLabel(dimension, row[dimension])}); ctx.beginPath(); ctx.arc(x, py, 5, 0, Math.PI * 2); ctx.fill(); });
      ctx.fillStyle = PALETTE.muted; ctx.fillText((this.plain ? spec.measures[0] : (MEASURE_LABELS[spec.measures[0]] || label(spec.measures[0]))) + ': ' + (this.plain ? lo + ' → ' + hi : `${new Intl.NumberFormat().format(lo)} to ${new Intl.NumberFormat().format(hi)}`), left, height - 22);
    } else {
      const step = w / Math.max(1, rows.length), points = []; plot.step = step;
      rows.forEach((row, i) => { const x = left + step * (i + .5), value = row[measure], text = this.axisLabel(dimension, row[dimension]); ctx.save(); ctx.fillStyle = PALETTE.muted; ctx.translate(x, height - bottom + 15); ctx.rotate(-.35); ctx.fillText(text.slice(0, 20), -10, 0); ctx.restore();
        if (value == null) { points.push(null); plot.points.push(null); return; } const point = [x, y(Number(value))]; points.push(point); plot.points.push({x: point[0], y: point[1], value, label: text});
        if (spec.type === 'bar') { const zero = y(0); const bar = {x: x - step * .3, y: Math.min(zero, point[1]), w: step * .6, h: Math.max(1, Math.abs(zero - point[1])), value, label: text}; plot.bars.push(bar); ctx.fillRect(bar.x, bar.y, bar.w, bar.h); } });
      if (spec.type !== 'bar') {
        let segment = []; const flush = () => { if (!segment.length) return; ctx.beginPath(); ctx.moveTo(...segment[0]); segment.slice(1).forEach(p => ctx.lineTo(...p)); ctx.stroke();
          if (spec.type === 'area') { ctx.lineTo(segment.at(-1)[0], y(0)); ctx.lineTo(segment[0][0], y(0)); ctx.closePath(); ctx.globalAlpha = .15; ctx.fill(); ctx.globalAlpha = 1; } segment.forEach(p => { ctx.beginPath(); ctx.arc(...p, 3, 0, Math.PI * 2); ctx.fill(); }); segment = []; };
        points.forEach(p => p ? segment.push(p) : flush()); flush();
      }
    }
    ctx.restore(); return {plot, ops};
  }
  drawBars(canvas, rows, width, measure, dimension) {
    // Horizontal bars: readable category names on the left, direct value labels at the bar end.
    const rowStep = 30, top = 10, bottom = 30, right = 120;
    const probe = canvas.getContext('2d'); probe.font = '13px Segoe UI, system-ui, sans-serif';
    const labels = rows.map(row => this.axisLabel(dimension, row[dimension]));
    const left = Math.min(240, Math.max(70, ...labels.map(text => probe.measureText(text).width))) + 16;
    const height = top + Math.max(1, rows.length) * rowStep + bottom, {ctx, ops} = this.prepareCanvas(canvas, width, height);
    ctx.clearRect(0, 0, width, height); ctx.font = '11px Segoe UI, system-ui, sans-serif';
    const values = rows.map(row => row[measure]).filter(value => value != null).map(Number).filter(Number.isFinite);
    let min = Math.min(0, ...values), max = Math.max(0, ...values); if (min === max) max = min + 1;
    const w = width - left - right, x = value => left + (value - min) / (max - min) * w, zero = x(0);
    const plot = {type: 'bar', orientation: 'horizontal', width, height, left, right, top, bottom, min, max, measure, dimension, bars: [], points: [], scatter: null, zero, step: rowStep};
    ctx.strokeStyle = PALETTE.grid; ctx.fillStyle = PALETTE.muted; ctx.lineWidth = 1; ctx.textAlign = 'center';
    for (let i = 0; i <= 4; i++) { const value = min + (max - min) * i / 4, position = x(value); ctx.beginPath(); ctx.moveTo(position, top); ctx.lineTo(position, height - bottom); ctx.stroke(); ctx.fillText(new Intl.NumberFormat(undefined, {notation: 'compact'}).format(value), position, height - bottom + 16); }
    ctx.save(); ctx.font = '13px Segoe UI, system-ui, sans-serif';
    rows.forEach((row, i) => {
      const y = top + i * rowStep, mid = y + rowStep / 2, value = row[measure];
      let text = labels[i]; while (text.length > 3 && ctx.measureText(text).width > left - 16) text = text.slice(0, -2).trimEnd() + '…';
      ctx.textAlign = 'right'; ctx.textBaseline = 'middle'; ctx.fillStyle = PALETTE.ink; ctx.fillText(text, left - 8, mid);
      if (value == null || !Number.isFinite(Number(value))) { ctx.textAlign = 'left'; ctx.fillStyle = PALETTE.muted; ctx.fillText('Not available', zero + 6, mid); return; }
      const end = x(Number(value)), bar = {x: Math.min(zero, end), y: y + 6, w: Math.max(1, Math.abs(end - zero)), h: rowStep - 12, value, label: labels[i]}; plot.bars.push(bar);
      ctx.fillStyle = PALETTE.bar; ctx.fillRect(bar.x, bar.y, bar.w, bar.h);
      ctx.fillStyle = PALETTE.ink; ctx.textAlign = end >= zero ? 'left' : 'right'; ctx.fillText(this.formatMeasure(measure, value), end + (end >= zero ? 6 : -6), mid);
    });
    ctx.restore(); return {plot, ops};
  }
  hover(event) {
    const plot = this.plot; if (!plot || this.plain) return this.hideTip();
    const canvas = this.q('.chart'), rect = canvas.getBoundingClientRect(), px = event.clientX - rect.left, py = event.clientY - rect.top;
    let hit = null;
    if (plot.bars.length) hit = plot.bars.find(bar => px >= bar.x - 2 && px <= bar.x + bar.w + 2 && py >= bar.y - 2 && py <= bar.y + bar.h + 2);
    else if (plot.scatter) hit = plot.scatter.points.find(point => Math.hypot(point.x - px, point.y - py) <= 10);
    else hit = plot.points.filter(Boolean).find(point => Math.hypot(point.x - px, point.y - py) <= 10);
    if (!hit) return this.hideTip();
    const tip = this.q('.chart-tip'); tip.replaceChildren();
    if (plot.scatter) tip.append(node('strong', '', hit.label), document.createElement('br'), document.createTextNode(`${MEASURE_LABELS[plot.scatter.xMeasure] || label(plot.scatter.xMeasure)}: ${this.formatMeasure(plot.scatter.xMeasure, hit.xValue)}`), document.createElement('br'), document.createTextNode(`${MEASURE_LABELS[plot.measure] || label(plot.measure)}: ${this.formatMeasure(plot.measure, hit.yValue)}`));
    else tip.append(node('strong', '', hit.label), document.createElement('br'), document.createTextNode(`${MEASURE_LABELS[plot.measure] || label(plot.measure)}: ${this.formatMeasure(plot.measure, hit.value)}`));
    const host = canvas.parentElement; tip.hidden = false;
    const x = Math.min(px + 14, host.clientWidth - tip.offsetWidth - 4), y = Math.max(4, py - tip.offsetHeight - 10);
    tip.style.left = Math.max(4, x) + 'px'; tip.style.top = y + 'px';
  }
  hideTip() { const tip = this.q('.chart-tip'); if (tip) tip.hidden = true; }
}

// ----- transport -----
async function api(path, body, method) {
  const options = body === undefined && !method ? {} : {method: method || 'POST', headers: {'Content-Type': 'application/json'}, body: body === undefined ? undefined : JSON.stringify(body)};
  const response = await fetch(path, options), result = await response.json();
  if (response.status === 401 && result.login_required) { showLogin(); throw new Error(result.error || 'Enter your name to continue.'); }
  if (!response.ok) throw new Error(result.error || 'Request failed.'); return result;
}

// ----- workspace state -----
const state = {sessionId: localStorage.getItem('b2b-session'), busy: false, me: null, status: null, latest: null, lastRequest: null, drawerTrigger: null};
function message(text, type = 'system') {
  // Transient notices (also used by the acceptance-test panel).
  let host = $('toasts'); if (!host) { host = node('div', 'toasts'); host.id = 'toasts'; host.setAttribute('role', 'status'); document.body.append(host); }
  const el = node('div', `toast ${type}`, text); host.append(el); setTimeout(() => el.remove(), type === 'error' ? 12000 : 6000); return el;
}
function setBusy(value) { state.busy = value; $('ask').disabled = value; document.querySelectorAll('.data-action').forEach(b => b.disabled = value); $('progress').hidden = !value; }
function grow() { const t = $('question'); if (!t.value) { t.style.height = ''; return; } t.style.height = 'auto'; t.style.height = Math.min(200, Math.max(44, t.scrollHeight)) + 'px'; }
function fillComposer(text) { $('question').value = text; grow(); $('question').focus(); }
function clearNotice() { const box = $('notice'); box.hidden = true; box.replaceChildren(); box.className = 'notice'; }
function showNotice(kind, title, text, actions = [], suggestions = []) {
  const box = $('notice'); box.replaceChildren(); box.className = 'notice ' + kind; box.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  const body = node('p'); if (title) body.append(node('strong', '', title)); body.append(document.createTextNode(text)); box.append(body);
  if (actions.length || suggestions.length) { const row = node('div', 'notice-row'); actions.forEach(([labelText, run]) => { const b = button('ghost small', labelText); b.addEventListener('click', run); row.append(b); });
    suggestions.forEach(s => { const chip = node('button', 'chip', s); chip.type = 'button'; chip.addEventListener('click', () => fillComposer(s)); row.append(chip); }); box.append(row); }
  box.hidden = false;
}
function markPrevious() { const view = state.latest?.view; if (!view || view.root.hidden) return; view.root.classList.add('previous'); if (!view.root.querySelector('.result-badge')) { const badge = node('p', 'result-badge', 'Previous result'); view.root.querySelector('.result-heading').prepend(badge); } }
function unmarkPrevious() { const view = state.latest?.view; if (!view) return; view.root.classList.remove('previous'); view.root.querySelector('.result-badge')?.remove(); }
function showAnswer(result, question) {
  // Replace the answer area with the new result; focus its heading and bring it into view without animation.
  const root = $('result-template').content.firstElementChild.cloneNode(true); const view = new ResultView(root);
  if (state.latest?.view) state.latest.view.destroy();
  view.render(result.table, {question, plan: result.plan, suggestions: result.suggestions || [], onFollowup: fillComposer, onEdit: fillComposer});
  $('answer').replaceChildren(root); document.body.classList.add('answered'); view.drawChart();
  state.latest = {view, table: result.table, plan: result.plan, question, sessionId: result.session_id};
  const heading = root.querySelector('.result-title'); heading.tabIndex = -1; heading.focus({preventScroll: true});
  root.scrollIntoView({block: 'start', behavior: 'auto'});
}
function showSavedCard(saved) {
  const card = node('section', 'saved-card'); card.setAttribute('aria-label', 'Saved conversation');
  const last = saved.turns.at(-1), withPlan = [...saved.turns].reverse().find(turn => turn.plan);
  card.append(node('h2', '', saved.title || 'Saved conversation'));
  card.append(node('p', '', last ? `Last question: ${last.question}` : 'This conversation has no questions yet.'));
  if (withPlan) { card.append(node('p', '', 'The saved query runs against the current data when you choose to run it.')); const row = node('div', 'row'); const run = button('primary', 'Run saved query', 'i-play'); run.addEventListener('click', () => runTurn(saved.id || state.sessionId, withPlan).catch(e => message(e.message, 'error'))); row.append(run); card.append(row); }
  if (state.latest?.view) state.latest.view.destroy(); state.latest = null;
  $('answer').replaceChildren(card); document.body.classList.add('answered');
}
function resetAnswer() { if (state.latest?.view) state.latest.view.destroy(); state.latest = null; $('answer').replaceChildren(); document.body.classList.remove('answered'); clearNotice(); }
async function handleResult(result, question) {
  state.sessionId = result.session_id; localStorage.setItem('b2b-session', state.sessionId);
  if (result.kind === 'clarify') { unmarkPrevious(); showNotice('clarify', 'One more detail is needed', result.question, [], result.suggestions || []); }
  else { clearNotice(); showAnswer(result, question); $('question').value = ''; grow(); }
  await refreshHistory();
}
async function submit(sample) {
  if (state.busy) return; const question = $('question').value.trim(); if (!sample && !question) { $('question').focus(); return; }
  const request = sample ? {path: '/api/sample', body: {view: sample.view, intent: sample.intent, session_id: state.sessionId}, question: sample.label} : {path: '/api/ask', body: {question, session_id: state.sessionId, view: $('view').value}, question};
  state.lastRequest = request; setBusy(true); clearNotice(); markPrevious();
  try { await handleResult(await api(request.path, request.body), request.question); }
  catch (error) { unmarkPrevious(); showNotice('error', 'The question could not be answered', error.message, [['Retry', () => retry()]]); }
  finally { setBusy(false); }
}
async function retry() {
  const request = state.lastRequest; if (!request || state.busy) return;
  setBusy(true); clearNotice(); markPrevious();
  try { await handleResult(await api(request.path, {...request.body, session_id: state.sessionId}), request.question); }
  catch (error) { unmarkPrevious(); showNotice('error', 'The question could not be answered', error.message, [['Retry', () => retry()]]); }
  finally { setBusy(false); }
}
async function runTurn(sessionId, turn) {
  if (state.busy) return; setBusy(true); markPrevious();
  try { const result = await api(`/api/sessions/${encodeURIComponent(sessionId)}/turns/${turn.id}/run`, {}); closeDrawer(); showAnswer(result, turn.question); }
  catch (error) { unmarkPrevious(); throw error; }
  finally { setBusy(false); }
}
async function rerunLatest() {
  const latest = state.latest; if (!latest || state.busy) return; setBusy(true); markPrevious();
  try { const result = await api('/api/rerun', {session_id: latest.sessionId || state.sessionId}); showAnswer(result, latest.question); }
  catch (error) { unmarkPrevious(); message(error.message, 'error'); }
  finally { setBusy(false); }
}

// ----- history drawer -----
function drawerFocusables() { return [...$('history').querySelectorAll('button:not(:disabled), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')].filter(el => !el.hidden && el.offsetParent !== null); }
function openDrawer() {
  state.drawerTrigger = document.activeElement; $('history').hidden = false; $('backdrop').hidden = false; $('history-open').setAttribute('aria-expanded', 'true');
  refreshHistory().catch(e => message(e.message, 'error')); (drawerFocusables()[0] || $('history-close')).focus();
}
function closeDrawer() {
  if ($('history').hidden) return; $('history').hidden = true; $('backdrop').hidden = true; $('history-open').setAttribute('aria-expanded', 'false');
  const target = state.drawerTrigger && document.contains(state.drawerTrigger) ? state.drawerTrigger : $('history-open'); target.focus(); state.drawerTrigger = null;
}
$('history').addEventListener('keydown', event => {
  if (event.key === 'Escape') { event.preventDefault(); closeDrawer(); return; }
  if (event.key !== 'Tab') return; const items = drawerFocusables(); if (!items.length) return;
  const first = items[0], last = items.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});
async function listSessions() {
  const data = await api('/api/sessions'); const list = $('chat-list'); list.replaceChildren();
  if (!data.sessions.length) list.append(node('p', 'drawer-empty', 'No saved conversations yet.'));
  data.sessions.forEach(session => {
    const item = node('div', 'chat-item'); const open = node('button', 'title', session.title); open.type = 'button'; if (session.id === state.sessionId) { item.setAttribute('aria-current', 'true'); open.setAttribute('aria-current', 'true'); }
    open.addEventListener('click', () => loadSession(session.id).catch(e => message(e.message, 'error')));
    const remove = button('remove', '', 'i-trash'); remove.setAttribute('aria-label', `Delete conversation ${session.title}`); remove.title = 'Delete conversation';
    remove.addEventListener('click', async () => { if (!confirm('Delete this conversation?')) return; try { await api('/api/sessions/' + encodeURIComponent(session.id), undefined, 'DELETE'); if (session.id === state.sessionId) await newSession(); else await listSessions(); } catch (e) { message(e.message, 'error'); } });
    item.append(open, remove); list.append(item);
  });
}
function renderTurns(turns) {
  const list = $('turns'); list.replaceChildren();
  if (!turns.length) { list.append(node('li', 'drawer-empty', 'No questions in this conversation yet.')); return; }
  turns.forEach((turn, index) => {
    const item = node('li', 'turn' + (index === turns.length - 1 ? ' current' : '')); item.append(node('p', 'q', turn.question)); if (turn.response) item.append(node('p', 'a', turn.response));
    if (turn.created_at) item.append(node('p', 'a', formatStamp(turn.created_at)));
    if (turn.plan) { const run = button('ghost small run', 'Run saved query', 'i-play'); run.addEventListener('click', () => runTurn(state.sessionId, turn).catch(e => message(e.message, 'error'))); item.append(run); }
    list.append(item);
  });
}
async function refreshHistory() {
  await listSessions();
  if (!state.sessionId) { renderTurns([]); return; }
  try { const saved = await api('/api/sessions/' + encodeURIComponent(state.sessionId)); renderTurns(saved.turns || []); } catch { renderTurns([]); }
}
async function newSession() {
  const result = await api('/api/sessions', {}); state.sessionId = result.session_id; localStorage.setItem('b2b-session', state.sessionId);
  resetAnswer(); $('question').value = ''; grow(); await refreshHistory(); closeDrawer(); $('question').focus({preventScroll: true});
}
async function loadSession(id) {
  const saved = await api('/api/sessions/' + encodeURIComponent(id));
  state.sessionId = id; localStorage.setItem('b2b-session', id); clearNotice();
  if (saved.turns && saved.turns.length) showSavedCard({...saved, id}); else resetAnswer();
  await refreshHistory();
}

// ----- identity -----
function showLogin() { $('login').hidden = false; $('login-name').value = state.me?.name || ''; $('login-name').focus(); }
$('login-form').addEventListener('submit', async e => {
  e.preventDefault();
  try { state.me = await api('/api/login', {name: $('login-name').value}); $('login').hidden = true; state.sessionId = null; localStorage.removeItem('b2b-session'); await start(); }
  catch (error) { message(error.message, 'error'); }
});
$('change-name').addEventListener('click', async () => { try { await api('/api/logout', {}); } catch {} state.me = null; showLogin(); });
function showQualification(q) {
  const badge = $('readiness'); if (!q) { badge.hidden = true; return; }
  badge.hidden = !q.ready && !q.streak; badge.textContent = q.ready ? 'Ready for review' : `${q.streak}/${q.required} passes`; badge.className = 'readiness' + (q.ready ? ' ready' : ''); badge.title = q.reason || '';
}

// ----- events -----
$('ask-form').addEventListener('submit', e => { e.preventDefault(); submit(); });
$('question').addEventListener('input', grow);
$('question').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } });
document.querySelectorAll('.starter').forEach(b => b.addEventListener('click', () => fillComposer(b.textContent)));
document.querySelectorAll('.sample').forEach(b => b.addEventListener('click', () => submit({view: b.dataset.view, intent: b.dataset.intent || 'table', label: b.textContent})));
$('history-open').addEventListener('click', () => $('history').hidden ? openDrawer() : closeDrawer());
$('history-close').addEventListener('click', closeDrawer);
$('backdrop').addEventListener('click', closeDrawer);
$('new-chat').addEventListener('click', () => newSession().catch(e => message(e.message, 'error')));
$('refresh').addEventListener('click', async () => {
  if (state.busy) return; setBusy(true); const shown = state.latest;
  try {
    const result = await api('/api/refresh', {});
    message(`Data refreshed: ${result.opportunities.toLocaleString()} opportunities, ${result.skus.toLocaleString()} products.`);
    if (state.status) { state.status.snapshot_at = result.snapshot_at; showFacts(state.status); }
    if (shown?.view && !shown.view.root.hidden) shown.view.markStale(`Data was refreshed at ${formatStamp(result.snapshot_at)}. This answer still shows data loaded ${formatStamp(shown.table.snapshot_at)} and awaits a rerun.`, {label: 'Update this answer', run: rerunLatest});
  } catch (e) { message(e.message, 'error'); if (shown?.view && !shown.view.root.hidden) shown.view.markRefreshFailed(`Refresh failed: ${e.message} This answer still shows data loaded ${formatStamp(shown.table.snapshot_at)}.`); }
  finally { setBusy(false); }
});
document.addEventListener('click', event => { document.querySelectorAll('.columns-menu[open]').forEach(menu => { if (!menu.contains(event.target)) menu.removeAttribute('open'); }); });
window.B2B = {ResultView, csvText, compareValues, formatNumber, formatDate, api, CHART, showQualification, message};
// The acceptance panel renders with the same template in plain mode.
$('test-result').append(...$('result-template').content.firstElementChild.cloneNode(true).children);

function showFacts(status) {
  const pill = $('workspace-status'); pill.textContent = `${status.database === 'demo' ? 'Demo workspace' : 'Workspace'} · ${status.source}`; pill.title = status.source; pill.classList.toggle('demo', status.database === 'demo');
  const facts = $('workspace-facts'); facts.replaceChildren();
  [['Data source', status.source], ['Model', status.model], ['Application version', status.version], ['Data loaded', status.snapshot_at ? formatStamp(status.snapshot_at) : 'Not loaded yet'], ['Data cache', `${status.cache_seconds} seconds`], ['Identity', status.name || '']]
    .forEach(([term, value]) => { if (value == null || value === '') return; facts.append(node('dt', '', term)); facts.append(node('dd', '', String(value))); });
}
async function start() {
  const status = await api('/api/status'); state.status = status; showFacts(status);
  $('samples').hidden = !status.previews; showQualification(status.qualification);
  $('me-name').textContent = state.me?.name || status.name || '';
  if (state.sessionId) { try { await loadSession(state.sessionId); } catch { state.sessionId = null; } }
  if (!state.sessionId) await newSession(); else await refreshHistory();
  grow();
}
(async () => {
  try {
    state.me = await api('/api/me');
    if (state.me.login_required) { showLogin(); return; }
    await start();
  } catch (e) { message(e.message, 'error'); }
})();
