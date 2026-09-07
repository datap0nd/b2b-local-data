// The sixteen browser checks, run against the production result card (same components, options, and handlers as
// ordinary answers). Expected values come from dev/independent.ts; ECharts SVG geometry is read from the DOM.
import * as echarts from 'echarts';
import type {Cell, TablePayload} from '@/types';
import {axisLabel, csvExpected, currency, decimalCompare, expectedCell, expectedChip, expectedHeader, expectedRowText, expectedVisible, LABELS, MEASURE_LABELS, MERGE, measureText, MONEY, STAGE_GROUP} from './independent';

export interface Observation { status: 'pass' | 'fail' | 'blocked'; expected?: unknown; observed?: unknown; notes?: string }
export interface Harness { root: HTMLElement; table: TablePayload; original: TablePayload; errors: () => number; frame: () => Promise<void>; setWidth: (px: number | null) => void; synthetic?: boolean }

const q = <T extends Element = HTMLElement>(root: ParentNode, selector: string) => root.querySelector(selector) as T | null;
const qa = <T extends Element = HTMLElement>(root: ParentNode, selector: string) => Array.from(root.querySelectorAll(selector)) as T[];
const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));
const result = (ok: boolean, expected: unknown, observed: unknown, notes: string): Observation => ({status: ok ? 'pass' : 'fail', expected, observed, notes});

function fullTable(h: Harness): HTMLElement | null { return q(h.root, '[data-testid="expanded-table"] [data-testid="result-table"]') ?? q(h.root, '[data-testid="result-table"][data-mode="full"]'); }
function headers(t: HTMLElement) { return qa<HTMLTableCellElement>(t, 'thead th[data-column]').map(th => ({column: th.dataset.column!, text: th.querySelector('button')?.textContent?.trim() ?? th.textContent!.trim(), sort: th.getAttribute('aria-sort')})); }
function rows(t: HTMLElement) { return qa<HTMLTableRowElement>(t, 'tbody tr').filter(r => r.cells.length > 1).map(r => Array.from(r.cells).filter(c => !c.querySelector('button[aria-label="Row details"]')).map(c => c.textContent!.trim())); }
async function allPages(h: Harness, t: HTMLElement): Promise<string[][]> {
  const out: string[][] = [];
  for (let page = 0; page < 200; page++) {
    out.push(...rows(t));
    const next = q<HTMLButtonElement>(t, 'button[aria-label="Next page"]');
    if (!next || next.disabled) break;
    next.click(); await h.frame();
  }
  return out;
}
async function setPageSize(h: Harness, t: HTMLElement, size: number) { const select = q<HTMLSelectElement>(t, 'select[aria-label="Rows per page"]'); if (!select) return; select.value = String(size); select.dispatchEvent(new Event('change', {bubbles: true})); await h.frame(); }
async function openMenu(trigger: HTMLElement, h: Harness) { trigger.focus(); trigger.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true})); await h.frame(); await sleep(30); }
function menuItems() { return qa<HTMLElement>(document, '[role="menuitemcheckbox"]'); }
async function closeMenu(h: Harness) { document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await h.frame(); }
function chart(h: Harness) { return q(h.root, '[data-testid="result-chart"]'); }
function svgOf(h: Harness) { return chart(h)?.querySelector('[role="img"] svg') ?? null; }
function fills(svg: SVGSVGElement, color: string) { return Array.from(svg.querySelectorAll('path,rect,circle')).filter(el => (el.getAttribute('fill') ?? '').toLowerCase() === color) as SVGGraphicsElement[]; }
/** Small marks (filled or hollow) drawn in the series colour: line and scatter symbols. */
function marks(svg: SVGSVGElement, color: string, max = 16) { return (Array.from(svg.querySelectorAll('path,circle')) as SVGGraphicsElement[]).filter(el => { const fill = (el.getAttribute('fill') ?? '').toLowerCase(), stroke = (el.getAttribute('stroke') ?? '').toLowerCase(); if (fill !== color && stroke !== color) return false; const b = el.getBBox(); return b.width > 0 && b.width < max && b.height < max; }); }
function texts(svg: SVGSVGElement) { return Array.from(svg.querySelectorAll('text')).map(t => t.textContent?.trim() ?? ''); }
async function hoverAt(h: Harness, x: number, y: number, dataIndex?: number) {
  const svg = svgOf(h); if (!svg) return '';
  const r = svg.getBoundingClientRect(); const target = document.elementFromPoint(r.left + x, r.top + y) ?? svg;
  for (const type of ['mousemove', 'pointermove']) target.dispatchEvent(new MouseEvent(type, {clientX: r.left + x, clientY: r.top + y, bubbles: true}));
  await sleep(120);
  const tip = qa<HTMLElement>(chart(h)!, 'div').find(d => d.style.position === 'absolute' && d.textContent && d.style.visibility !== 'hidden' && d.style.display !== 'none' && (d.style.opacity === '' || Number(d.style.opacity) > 0));
  let text = tip?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
  for (const type of ['mouseleave', 'mouseout', 'pointerleave']) target.dispatchEvent(new MouseEvent(type, {bubbles: true}));
  if (!text && dataIndex != null) {
    // Hover did not reach the mark: ask the renderer to show the tooltip for that point (its own formatter and DOM), recorded as such.
    const host = chart(h)?.querySelector<HTMLElement>('[role="img"]'); const instance = host ? echarts.getInstanceByDom(host) : undefined;
    if (instance) { instance.dispatchAction({type: 'showTip', seriesIndex: 0, dataIndex}); await sleep(150); const shown = qa<HTMLElement>(chart(h)!, 'div').find(d => d.style.position === 'absolute' && d.textContent && d.style.visibility !== 'hidden' && d.style.display !== 'none'); text = shown ? '[showTip] ' + shown.textContent!.replace(/\s+/g, ' ').trim() : ''; instance.dispatchAction({type: 'hideTip'}); }
  }
  return text;
}
const FIRST = '#315bd6';

export const CHECKS: Record<number, (h: Harness) => Promise<Observation>> = {
  1: h => tableCheck(h, 'summary'),
  2: h => tableCheck(h, 'detail'),
  3: h => sortCheck(h, 1),
  4: h => sortCheck(h, -1),
  5: csvCheck,
  6: barCheck,
  7: h => lineCheck(h, false),
  8: h => lineCheck(h, true),
  9: scatterCheck,
  10: measureCheck,
  11: limitCheck,
  12: resizeCheck,
  13: metricCheck,
  14: emptyCheck,
  15: chipsCheck,
  16: currencyCheck,
};

async function tableCheck(h: Harness, kind: 'summary' | 'detail'): Promise<Observation> {
  const t = fullTable(h); if (!t) return {status: 'fail', notes: 'No table rendered.'};
  await setPageSize(h, t, 100);
  const table = h.table, visible = expectedVisible(table);
  const wantHeaders = visible.map(c => expectedHeader(table, c));
  const observedHeaders = headers(t).map(x => x.text);
  const observedRows = await allPages(h, t);
  const mismatches: unknown[] = [];
  table.rows.forEach((row, i) => { const want = expectedRowText(table, visible, row); want.forEach((cell, j) => { if (observedRows[i]?.[j] !== cell && mismatches.length < 20) mismatches.push({row: i, column: visible[j], expected: cell, observed: observedRows[i]?.[j]}); }); });
  // Row details: every returned column with its formatted value, in an accessible dialog.
  for (let n = 0; n < 200; n++) { const prev = q<HTMLButtonElement>(t, 'button[aria-label="Previous page"]'); if (!prev || prev.disabled) break; prev.click(); await h.frame(); }
  const detailsButton = q<HTMLButtonElement>(t, 'button[aria-label="Row details"]');
  let detailsOk = true, details: unknown = null;
  if (detailsButton) {
    detailsButton.click(); await h.frame(); await sleep(50);
    const dialog = q<HTMLElement>(document, '[role="dialog"] [data-testid="row-details"]');
    const terms = dialog ? qa(dialog, 'dt').map(d => d.textContent!.trim()) : [], values = dialog ? qa(dialog, 'dd').map(d => d.textContent!.trim()) : [];
    const wantTerms = table.columns.map(c => expectedHeader(table, c)), wantValues = table.columns.map(c => expectedCell(table, table.rows[0], c));
    detailsOk = JSON.stringify(terms) === JSON.stringify(wantTerms) && JSON.stringify(values) === JSON.stringify(wantValues);
    details = {terms: terms.length, values: values.length, wantTerms: wantTerms.length, mismatches: wantTerms.map((term, i) => ({term, value: values[i], expected: wantValues[i], observedTerm: terms[i]})).filter(m => m.term !== m.observedTerm || m.value !== m.expected).slice(0, 8)};
    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await h.frame();
  }
  // Column menu lists every returned column with its business label.
  const trigger = qa<HTMLButtonElement>(t, 'button').find(b => b.textContent?.trim() === 'Columns') ?? null;
  let menuOk = true, menu: string[] = [];
  if (trigger) { await openMenu(trigger, h); menu = menuItems().map(i => i.textContent!.trim()); const partners = Object.entries(MERGE).filter(([c, p]) => visible.includes(c) && table.columns.includes(p) && !visible.includes(p)).map(([, p]) => p); const wantMenu = table.columns.filter(c => !partners.includes(c)).map(c => expectedHeader(table, c)); menuOk = [...menu].sort().join('|') === [...wantMenu].sort().join('|') && menu.slice(0, visible.length).join('|') === visible.map(c => expectedHeader(table, c)).join('|'); await closeMenu(h); }
  const keyOk = kind === 'detail' ? observedHeaders[0] === 'Opportunity no.' && observedHeaders[1] === 'Product' : observedHeaders[0] === 'Opportunity';
  const ok = JSON.stringify(observedHeaders) === JSON.stringify(wantHeaders) && observedRows.length === table.rows.length && mismatches.length === 0 && detailsOk && menuOk && keyOk;
  return result(ok, {headers: wantHeaders, rows: table.rows.length, menu: table.columns.length}, {headers: observedHeaders, rows: observedRows.length, mismatches, detailsOk, details, menuOk, menu, keyOk}, `${table.rows.length} returned rows compared cell by cell across pages against independently formatted values; row details and the column menu checked.`);
}

async function sortCheck(h: Harness, direction: 1 | -1): Promise<Observation> {
  const t = fullTable(h); if (!t) return {status: 'fail', notes: 'No table rendered.'};
  await setPageSize(h, t, 100);
  const table = h.table, visible = expectedVisible(table);
  const numeric = visible.filter(c => table.column_types[c] === 'number' && !MERGE[c]);
  const column = numeric.find(c => h.original.rows.some(r => r[c] == null)) ?? numeric[0];
  if (!column) return {status: 'blocked', notes: 'No numeric column is visible to sort.'};
  const th = q<HTMLElement>(t, `thead th[data-column="${column}"]`)!; const button = th.querySelector('button')!;
  const wanted = direction === 1 ? 'ascending' : 'descending';
  for (let n = 0; n < 3 && th.getAttribute('aria-sort') !== wanted; n++) { button.click(); await h.frame(); }
  const index = headers(t).findIndex(x => x.column === column);
  const expected = [...h.original.rows].sort((a, b) => { if (a[column] == null) return b[column] == null ? 0 : 1; if (b[column] == null) return -1; return direction * decimalCompare(a[column], b[column]); });
  const observed = (await allPages(h, t)).map(r => r[index]);
  const want = expected.map(r => expectedCell(table, r, column));
  const withNulls = h.original.rows.some(r => r[column] == null);
  const nullsLast = !withNulls || observed.slice(observed.length - observed.filter(v => v === '—').length).every(v => v === '—');
  let columnSelection: unknown = null;
  if (direction === -1) {
    const hiddenColumn = table.columns.find(c => !visible.includes(c) && !Object.values(MERGE).includes(c));
    const trigger = qa<HTMLButtonElement>(t, 'button').find(b => b.textContent?.trim() === 'Columns');
    if (hiddenColumn && trigger) {
      await openMenu(trigger, h);
      const item = menuItems().find(i => i.textContent!.trim() === expectedHeader(table, hiddenColumn));
      item?.click(); await h.frame(); await closeMenu(h);
      const now = headers(t); const added = now.some(x => x.column === hiddenColumn);
      const stillSorted = q<HTMLElement>(t, `thead th[data-column="${column}"]`)?.getAttribute('aria-sort') === wanted;
      const newIndex = now.findIndex(x => x.column === hiddenColumn);
      const cells = (await allPages(h, t)).map(r => r[newIndex]); const wantCells = expected.map(r => expectedCell(table, r, hiddenColumn));
      await openMenu(trigger, h); menuItems().find(i => i.textContent!.trim() === expectedHeader(table, hiddenColumn))?.click(); await h.frame(); await closeMenu(h);
      const removed = !headers(t).some(x => x.column === hiddenColumn);
      columnSelection = {column: hiddenColumn, added, stillSorted, cellsOk: JSON.stringify(cells) === JSON.stringify(wantCells), removed};
    }
  }
  const selectionOk = columnSelection === null || (Object.values(columnSelection as Record<string, unknown>).every(v => v === true || typeof v === 'string'));
  const ok = JSON.stringify(observed) === JSON.stringify(want) && nullsLast && selectionOk;
  return result(ok, {column, direction, first: want.slice(0, 10), nulls: withNulls}, {first: observed.slice(0, 10), nullsLast, columnSelection}, withNulls ? 'Null witness present; nulls must sort last.' : 'No null value in the returned rows; nulls-last is covered by synthetic checks.');
}

async function csvCheck(h: Harness): Promise<Observation> {
  const t = fullTable(h); if (!t) return {status: 'fail', notes: 'No table rendered.'};
  await setPageSize(h, t, 100);
  const table = h.table, visible = expectedVisible(table);
  const captured: Blob[] = []; const create = URL.createObjectURL, revoke = URL.revokeObjectURL;
  URL.createObjectURL = (blob: Blob) => { captured.push(blob); return 'blob:captured'; }; URL.revokeObjectURL = () => {};
  const stop = (e: Event) => { const a = e.target as HTMLElement; if (a.tagName === 'A' && (a as HTMLAnchorElement).href === 'blob:captured') e.preventDefault(); };
  document.addEventListener('click', stop, true);
  try {
    const sortable = visible.find(c => table.column_types[c] === 'number' && !MERGE[c]);
    if (sortable) { const button = q<HTMLElement>(t, `thead th[data-column="${sortable}"] button`); button?.click(); await h.frame(); button?.click(); await h.frame(); }
    const domRows = await allPages(h, t);
    const exportButton = qa<HTMLButtonElement>(h.root, '[data-testid="export"]').pop();
    exportButton?.click(); await sleep(50);
    if (!captured.length) return {status: 'fail', notes: 'The export control produced no file.'};
    const bytes = new Uint8Array(await captured[0].arrayBuffer()); const observed = new TextDecoder('utf-8', {ignoreBOM: true}).decode(bytes);
    // Expected rows follow the sorted DOM order, mapped back to the untouched payload by their visible cell texts.
    const key = (cells: string[]) => cells.join(''); const byKey = new Map(h.original.rows.map(r => [key(expectedRowText(table, visible, r)), r]));
    const ordered = domRows.map(r => byKey.get(key(r)));
    const csvRows = observed.split('\r\n').slice(1);
    const expectedSorted = csvExpected(table, ordered.filter(Boolean) as Record<string, Cell>[]);

    const ok = observed === expectedSorted && observed.charCodeAt(0) === 0xfeff && ordered.every(Boolean);
    return result(ok, {rows: table.rows.length, columns: table.columns.length, firstLine: expectedSorted.split('\r\n')[1]?.slice(0, 160)}, {rows: csvRows.length, bom: observed.charCodeAt(0) === 0xfeff, firstLine: csvRows[0]?.slice(0, 160), matchesSortedOrder: observed === expectedSorted, type: captured[0].type}, 'Export triggered through the CSV control: every returned column and row, exact values, every cell quoted, quotes doubled, formula prefixes guarded; the file follows the displayed order.');
  } finally { URL.createObjectURL = create; URL.revokeObjectURL = revoke; document.removeEventListener('click', stop, true); }
}

async function barCheck(h: Harness): Promise<Observation> {
  const svg = svgOf(h) as SVGSVGElement | null; if (!svg) return {status: 'fail', notes: 'No chart rendered.'};
  const table = h.table, spec = table.chart!, dim = spec.dimensions[0];
  const measure = (q<HTMLSelectElement>(h.root, 'select[aria-label="Chart measure"]')?.value) ?? spec.measures[0];
  const shown = Number(chart(h)!.dataset.shown);
  const groups = independentlyOrderedChart(h.original, measure, shown < h.original.rows.length).slice(0, shown).map(r => ({label: axisLabel(table, dim, r[dim]), value: r[measure]})).filter(g => g.value != null && Number.isFinite(Number(g.value)));
  const bars = fills(svg, FIRST).map(el => el.getBBox()).filter(b => b.height > 4 && b.height < 40).sort((a, b) => a.y - b.y);
  const max = Math.max(...groups.map(g => Math.abs(Number(g.value))));
  const widest = Math.max(...bars.map(b => b.width));
  const lengthsOk = bars.length === groups.length && groups.every((g, i) => Math.abs(bars[i].width / widest - Math.abs(Number(g.value)) / max) < 0.02);
  const labels = texts(svg);
  const valueLabelsOk = groups.every(g => labels.includes(measureText(table, measure, g.value)));
  const categoryOk = groups.every(g => labels.some(x => x === g.label || (x.endsWith('…') && g.label.startsWith(x.slice(0, -1))) || (x.endsWith('...') && g.label.startsWith(x.slice(0, -3)))));
  const orderOk = bars.every((b, i) => i === 0 || b.y > bars[i - 1].y);
  const tip = bars.length ? await hoverAt(h, bars[0].x + bars[0].width / 2, bars[0].y + bars[0].height / 2, 0) : '';
  const tipOk = tip.includes(groups[0]?.label ?? '') && tip.includes(measureText(table, measure, groups[0]?.value ?? null));
  return result(lengthsOk && valueLabelsOk && categoryOk && orderOk && tipOk, {groups: groups.slice(0, 10)}, {bars: bars.slice(0, 10).map(b => ({y: Math.round(b.y), width: Math.round(b.width)})), lengthsOk, valueLabelsOk, categoryOk, orderOk, tooltip: tip.slice(0, 200)}, `${groups.length} horizontal bars in displayed ranking order; widths measured from the SVG and compared with the values; value labels and tooltip compared with independently formatted text.`);
}

async function lineCheck(h: Harness, area: boolean): Promise<Observation> {
  const svg = svgOf(h) as SVGSVGElement | null; if (!svg) return {status: 'fail', notes: 'No chart rendered.'};
  const table = h.table, spec = table.chart!, dim = spec.dimensions[0], measure = spec.measures[0];
  const rows = independentlyOrderedChart(h.original, measure);
  const chronological = rows.every((r, i) => i === 0 || r[dim] == null || rows[i - 1][dim] == null || String(rows[i - 1][dim]) <= String(r[dim]));
  const segments: number[] = []; let seg = 0; rows.forEach(r => { if (r[measure] == null) { if (seg) segments.push(seg); seg = 0; } else seg++; }); if (seg) segments.push(seg);
  const linePaths = Array.from(svg.querySelectorAll('path')).filter(p => (p.getAttribute('stroke') ?? '').toLowerCase() === FIRST && ['none', 'transparent', ''].includes((p.getAttribute('fill') ?? '').toLowerCase()) && (p.getAttribute('d') ?? '').includes('L') && p.getBBox().width > 40);
  const moves = linePaths.reduce((n, p) => n + ((p.getAttribute('d') ?? '').match(/M/g)?.length ?? 0), 0);
  const symbols = marks(svg, FIRST, 14);
  const points = rows.filter(r => r[measure] != null).length;
  const areaPaths = Array.from(svg.querySelectorAll('path')).filter(p => (p.getAttribute('fill') ?? '').toLowerCase() === FIRST && Number(p.getAttribute('fill-opacity') ?? 1) < 0.5);
  const first = symbols.map(s => s.getBBox()).sort((a, b) => a.x - b.x)[0];
  const firstRow = rows.find(r => r[measure] != null);
  const tip = first ? await hoverAt(h, first.x + first.width / 2, first.y + first.height / 2, rows.findIndex(r => r[measure] != null)) : '';
  const tipOk = !firstRow || (tip.includes(measureText(table, measure, firstRow[measure])) && tip.includes(axisLabel(table, dim, firstRow[dim])));
  const ok = chronological && moves === segments.length && symbols.length === points && (!area || areaPaths.length >= 1) && tipOk;
  return result(ok, {segments: segments.length, points, chronological: true, area}, {moves, symbols: symbols.length, chronological, areaPaths: areaPaths.length, tooltip: tip.slice(0, 200)}, `${segments.length} segment(s) and ${rows.length - points} gap(s) read from the SVG path; symbols counted; tooltip compared.`);
}

async function scatterCheck(h: Harness): Promise<Observation> {
  const svg = svgOf(h) as SVGSVGElement | null; if (!svg) return {status: 'fail', notes: 'No chart rendered.'};
  const table = h.table, [xm, ym] = table.chart!.measures, dim = table.chart!.dimensions[0];
  const rows = h.original.rows.filter(r => r[xm] != null && r[ym] != null);
  const symbols = marks(svg, FIRST, 16);
  const first = symbols.map(s => s.getBBox()).sort((a, b) => a.x - b.x)[0];
  const xs = rows.map(r => Number(r[xm])); const leftmost = rows[xs.indexOf(Math.min(...xs))];
  const tip = first ? await hoverAt(h, first.x + first.width / 2, first.y + first.height / 2, xs.indexOf(Math.min(...xs))) : '';
  const tipOk = !leftmost || (tip.includes(measureText(table, xm, leftmost[xm])) && tip.includes(measureText(table, ym, leftmost[ym])) && tip.includes(axisLabel(table, dim, leftmost[dim])));
  return result(symbols.length === rows.length && tipOk, {points: rows.length}, {symbols: symbols.length, tooltip: tip.slice(0, 200)}, `${rows.length} points counted in the SVG; the leftmost point's tooltip shows both measures.`);
}

async function measureCheck(h: Harness): Promise<Observation> {
  const select = q<HTMLSelectElement>(h.root, 'select[aria-label="Chart measure"]'); if (!select) return {status: 'blocked', notes: 'Only one measure available.'};
  const other = Array.from(select.options).map(o => o.value).find(v => v !== select.value); if (!other) return {status: 'blocked', notes: 'Only one measure available.'};
  const original = window.fetch; let calls = 0; (window as unknown as {fetch: typeof fetch}).fetch = (...a: Parameters<typeof fetch>) => { calls++; return original(...a); };
  try {
    select.value = other; select.dispatchEvent(new Event('change', {bubbles: true})); await h.frame(); await sleep(250);
    const svg = svgOf(h) as SVGSVGElement; const labels = texts(svg);
    const table = h.table; const want = independentlyOrderedChart(h.original, other, Number(chart(h)!.dataset.shown) < h.original.rows.length).slice(0, Number(chart(h)!.dataset.shown)).filter(r => r[other] != null).map(r => measureText(table, other, r[other]));
    const ok = calls === 0 && want.every(x => labels.includes(x)) && select.value === other;
    return result(ok, {measure: other, fetchCalls: 0, valueLabels: want.slice(0, 10)}, {measure: select.value, fetchCalls: calls, found: want.filter(x => labels.includes(x)).length}, 'Changing the chart measure redraws locally with the other measure\'s values; no request leaves the browser.');
  } finally { (window as unknown as {fetch: typeof fetch}).fetch = original; }
}

async function limitCheck(h: Harness): Promise<Observation> {
  const initial = chart(h); if (!initial) return {status: 'fail', notes: 'No chart rendered.'};
  const table = h.table, total = Number(initial.dataset.total);
  const exercised = total > 10 && table.chart!.type === 'bar' && table.column_types[table.chart!.dimensions[0]] !== 'date';
  const before = texts(svgOf(h) as SVGSVGElement);
  const dataButton = qa<HTMLButtonElement>(h.root, '[aria-label="Presentation"] button').find(button => button.textContent === 'Data');
  dataButton?.click(); await h.frame();
  const t = fullTable(h);
  const exclusiveData = !!t && !chart(h);
  const numeric = expectedVisible(table).find(column => table.column_types[column] === 'number');
  const sortButton = numeric && t ? q<HTMLButtonElement>(t, `thead th[data-column="${numeric}"] button`) : null;
  sortButton?.click(); await h.frame();
  const chartButton = qa<HTMLButtonElement>(h.root, '[aria-label="Presentation"] button').find(button => button.textContent === 'Chart');
  chartButton?.click(); await h.frame(); await sleep(250);
  const c = chart(h)!;
  const exclusiveChart = !!c && !fullTable(h);
  const stable = JSON.stringify(before) === JSON.stringify(texts(svgOf(h) as SVGSVGElement));
  const limit = q<HTMLElement>(h.root, '[data-testid="chart-limit"]');
  let limitOk = !exercised ? !limit : Number(c.dataset.shown) === 10 && !!limit && /(Top 10|First 10)/.test(limit.textContent!) && (limit.textContent!.includes('requested order') || limit.textContent!.includes(String(total)));
  if (exercised) {
    const allButton = qa<HTMLButtonElement>(c, 'button').find(button => button.textContent?.startsWith('Show all'));
    allButton?.click(); await h.frame(); await sleep(100);
    limitOk = limitOk && Number(c.dataset.shown) === total;
  }
  return result(stable && exclusiveData && exclusiveChart && limitOk, {exclusiveData: true, exclusiveChart: true, stable: true, total}, {exclusiveData, exclusiveChart, stable, limitOk, disclosure: limit?.textContent}, 'Chart and Data are exclusive. Table sorting does not change the chart; top groups are ranked by the selected measure and every returned group is reachable.');
}

async function resizeCheck(h: Harness): Promise<Observation> {
  const svg = svgOf(h) as SVGSVGElement | null; if (!svg) return {status: 'fail', notes: 'No chart rendered.'};
  const errorsBefore = h.errors(); const widthBefore = svg.getBoundingClientRect().width; const hostBefore = h.root.getBoundingClientRect().width;
  h.setWidth(620); window.dispatchEvent(new Event('resize')); await h.frame(); await sleep(250);
  const after = svgOf(h) as SVGSVGElement; const widthAfter = after.getBoundingClientRect().width;
  const painted = after.querySelectorAll('path,rect,circle,text').length;
  const finite = Array.from(after.querySelectorAll('path')).every(p => !/NaN|Infinity/.test(p.getAttribute('d') ?? ''));
  h.setWidth(null); window.dispatchEvent(new Event('resize')); await h.frame(); await sleep(150);
  const expectedAfter = widthBefore - (hostBefore - 620);
  const ok = Math.abs(widthAfter - expectedAfter) < 4 && widthAfter !== widthBefore && painted > 0 && finite && h.errors() === errorsBefore;
  return result(ok, {hostWidth: 620, svgWidth: expectedAfter, painted: '> 0', finite: true, browserErrors: 0}, {hostBefore, widthBefore, widthAfter, painted, finite, browserErrors: h.errors() - errorsBefore}, 'Resized the chart host to 620px through a real resize, waited for the redraw, checked the SVG follows, contains marks, and has finite coordinates.');
}

async function metricCheck(h: Harness): Promise<Observation> {
  const table = h.table;
  const metrics = qa(h.root, '[data-testid="metrics"] > div');
  const measures = table.columns.filter(column => MEASURE_LABELS[column]);
  const expected = measures.map(measure => measureText(table, measure, table.rows[0]?.[measure] ?? null));
  const observed = metrics.map(metric => metric.querySelector('dd')?.textContent?.trim());
  const singlePresentation = !q(h.root, '[data-testid="value-cards"]') && !q(h.root, '[data-testid="result-table"]') && !q(h.root, '[data-testid="scope"]');
  const ok = JSON.stringify(observed) === JSON.stringify(expected) && singlePresentation;
  return result(ok, {values: expected, presentations: 1}, {values: observed, singlePresentation}, 'The scalar has one metric presentation with independently formatted values and units; there is no repeated total or table.');
}

async function emptyCheck(h: Harness): Promise<Observation> {
  const table = h.table; const empty = q(h.root, '[data-testid="empty"]'); const chips = qa(h.root, '[data-testid="filters"] li').map(c => c.textContent!.trim());
  const scope = q(h.root, '[data-testid="scope"]')?.textContent ?? ''; const want = table.filters.map(f => expectedChip(table, f));
  const ok = table.total_rows === 0 && !!empty && JSON.stringify(chips) === JSON.stringify(want) && scope.startsWith('No matching') && !q(h.root, '[data-testid="result-table"]');
  return result(ok, {chips: want}, {empty: !!empty, chips, scope}, 'Zero rows show the empty state with the active filter chips instead of an empty table.');
}

async function chipsCheck(h: Harness): Promise<Observation> {
  const table = h.table; const chips = qa(h.root, '[data-testid="filters"] li').map(c => c.textContent!.trim()); const want = table.filters.map(f => expectedChip(table, f));
  const t = fullTable(h) ?? q(h.root, '[data-testid="result-table"]'); const visible = expectedVisible(table); const stageIndex = headers(t!).findIndex(x => x.column === 'stage');
  let badgesOk = true;
  if (t && stageIndex >= 0) {
    await setPageSize(h, t, 100);
    const domRows = qa<HTMLTableRowElement>(t, 'tbody tr').filter(r => r.cells.length > 1);
    badgesOk = domRows.every((r, i) => { const stage = h.original.rows[i]?.stage; const cell = r.cells[stageIndex]; const badge = cell.querySelector('span'); return stage == null ? cell.textContent!.trim() === '—' : !!badge && badge.textContent!.trim() === String(stage) && (STAGE_GROUP[String(stage)] ? badge.className.includes(`text-${STAGE_GROUP[String(stage)]}`) : true); });
  }
  const quality = q(h.root, '[data-testid="quality"]'); const qualityWarning = table.metadata.warnings.find(w => w.code === 'quality_warning');
  const qualityOk = qualityWarning ? !!quality && quality.textContent!.includes(qualityWarning.count.toLocaleString()) && /needs? review/.test(quality.textContent!) : !quality;
  const editable = qa(h.root, '[data-testid="filters"] button, [data-testid="filters"] input').length === 0;
  const ok = JSON.stringify(chips) === JSON.stringify(want) && badgesOk && qualityOk && editable && visible.includes('stage');
  return result(ok, {chips: want, quality: qualityWarning?.count ?? 0}, {chips, badgesOk, qualityOk, editable}, 'Read-only filter chips with business labels, exact stage names with their group colour, and the review count with a discoverable evidence panel.');
}

async function currencyCheck(h: Harness): Promise<Observation> {
  const table = h.table; const cur = currency(table); if (!cur || cur === 'mixed') return {status: 'blocked', notes: 'No single currency is established for this population.'};
  const t = fullTable(h) ?? q(h.root, '[data-testid="result-table"]'); if (!t) return {status: 'fail', notes: 'No table rendered.'};
  const visible = expectedVisible(table); const money = visible.find(c => MONEY.has(c)); const header = money ? headers(t).find(x => x.column === money)?.text : null;
  const cells = money ? rows(t).map(r => r[headers(t).findIndex(x => x.column === money)]) : [];
  const metrics = qa(h.root, '[data-testid="metrics"] dd').map(d => d.textContent!.trim());
  const ok = header === `${LABELS[money!]} (${cur})` && cells.every(c => !c.endsWith(' ' + cur)) && !q(h.root, '[data-testid="currency-note"]') && metrics.length === 0;
  return result(ok, {header: `${LABELS[money!]} (${cur})`, currency: cur}, {header, sample: cells.slice(0, 5), metrics}, 'The currency of the complete population labels the amount header once; cells carry no repeated code.');
}

/** Independent ordering expectations: exact decimals, deterministic category ties, date gaps retained. */
function independentlyOrderedChart(table: TablePayload, measure: string, rank = false) {
  const dimension = table.chart!.dimensions[0];
  const rows = table.rows.slice();
  if (table.column_types[dimension] === 'date') return rows.filter(row => row[dimension] != null && Number.isFinite(Date.parse(String(row[dimension])))).sort((a, b) => String(a[dimension]).localeCompare(String(b[dimension])));
  if (!rank || table.metadata?.sort?.length) return rows;
  return rows.sort((a, b) => a[measure] == null ? (b[measure] == null ? String(a[dimension]).localeCompare(String(b[dimension])) : 1) : b[measure] == null ? -1 : -decimalCompare(a[measure], b[measure]) || String(a[dimension]).localeCompare(String(b[dimension])));
}
