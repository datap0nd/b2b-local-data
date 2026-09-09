import {useEffect, useMemo, useRef, useState} from 'react';
import * as echarts from 'echarts';
import {Download} from 'lucide-react';
import {Button} from './ui/button';
import {DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger} from './ui/dropdown-menu';
import {axisLabel, compareValues, formatNumber, label, measureText, MEASURE_LABELS} from '@/format';
import {download} from '@/lib/utils';
import type {Cell, Row, TablePayload} from '@/types';

export const TOP_N = 10;
const COLORS = ['#315bd6', '#0891b2', '#b45309', '#7c3aed', '#be123c'];
export function preservesRequestedOrder(table: TablePayload, measure: string): boolean {
  const sort = table.metadata?.sort ?? [];
  return sort.length > 0 && (sort[0].field !== measure || sort[0].direction !== 'desc');
}

/** Date series are chronological. Ranking is explicit, exact, and independent of table order. */
export function chartRows(table: TablePayload, measure = table.chart?.measures[0] ?? '', ranked = false): Row[] {
  const dimension = table.chart?.dimensions[0] ?? '';
  const rows = [...table.rows];
  if (table.column_types[dimension] === 'date') return rows.filter(row => row[dimension] != null && Number.isFinite(Date.parse(String(row[dimension])))).sort((a, b) => compareValues(a[dimension], b[dimension], 'date'));
  // The server already applied every explicit sort term, including tie directions.
  if (!ranked || table.metadata?.sort?.length) return rows;
  return rows.sort((a, b) => {
    if (a[measure] == null) return b[measure] == null ? compareValues(a[dimension], b[dimension], 'text') : 1;
    if (b[measure] == null) return -1;
    return -compareValues(a[measure], b[measure], 'number') || compareValues(a[dimension], b[dimension], 'text');
  });
}

export function chartOption(table: TablePayload, measure: string, shownRows: Row[]): echarts.EChartsOption {
  const spec = table.chart!;
  const dimension = spec.dimensions[0];
  const isDate = table.column_types[dimension] === 'date';
  const scatter = spec.type === 'scatter';
  const horizontal = spec.type === 'bar' && !isDate;
  const labels = shownRows.map(row => axisLabel(table, dimension, row[dimension]));
  const numeric = (value: Cell) => value == null ? null : Number(value);
  const format = (key: string, value: Cell) => escape(measureText(table, key, value));
  const base: echarts.EChartsOption = {
    color: COLORS, animationDuration: 200,
    textStyle: {fontFamily: 'Inter, system-ui, sans-serif', color: '#4b5871'},
    grid: {left: 24, right: 48, top: 52, bottom: 28, containLabel: true},
    tooltip: {trigger: scatter ? 'item' : 'axis', confine: true, borderColor: '#dde2ed', textStyle: {fontSize: 12}},
    aria: {enabled: true, decal: {show: false}},
  };
  if (scatter) {
    const [xMeasure, yMeasure] = spec.measures;
    const points = shownRows.filter(row => row[xMeasure] != null && row[yMeasure] != null).map(row => ({value: [numeric(row[xMeasure]), numeric(row[yMeasure])], name: axisLabel(table, dimension, row[dimension]), raw: [row[xMeasure], row[yMeasure]]}));
    return {...base,
      xAxis: {type: 'value', splitNumber: 3, name: currencyName(table, xMeasure), nameLocation: 'middle', nameGap: 28, splitLine: {lineStyle: {color: '#eef0f5'}}, axisLabel: {formatter: compact, hideOverlap: true}},
      yAxis: {type: 'value', name: currencyName(table, yMeasure), nameTextStyle: {align: 'left'}, splitLine: {lineStyle: {color: '#eef0f5'}}, axisLabel: {formatter: compact, hideOverlap: true}},
      tooltip: {...base.tooltip, formatter: (params: unknown) => { const data = (params as {data: {name: string; raw: Cell[]}}).data; return `<b>${escape(data.name)}</b><br/>${escape(label(xMeasure))}: ${format(xMeasure, data.raw[0])}<br/>${escape(label(yMeasure))}: ${format(yMeasure, data.raw[1])}`; }},
      series: [{type: 'scatter', data: points, symbolSize: 10}]};
  }
  const tooltip = {...base.tooltip, formatter: (params: unknown) => { const point = (params as {dataIndex: number; name: string}[])[0]; const row = shownRows[point.dataIndex]; return `<b>${escape(point.name)}</b><br/>${escape(MEASURE_LABELS[measure] ?? label(measure))}: ${row ? format(measure, row[measure]) : '—'}`; }};
  const values = shownRows.map(row => numeric(row[measure]));
  if (horizontal) return {...base, tooltip,
    grid: {...base.grid, left: 8, bottom: 24, right: 116},
    yAxis: {type: 'category', data: labels, inverse: true, axisTick: {show: false}, axisLine: {show: false}, axisLabel: {width: 220, overflow: 'truncate', fontSize: 12}},
    xAxis: {type: 'value', splitNumber: 3, name: currencyName(table, measure), nameLocation: 'middle', nameGap: 28, splitLine: {lineStyle: {color: '#eef0f5'}}, axisLabel: {formatter: compact, hideOverlap: true}},
    series: [{type: 'bar', data: values, barMaxWidth: 24, itemStyle: {borderRadius: [0, 3, 3, 0]}, label: {show: true, position: 'right', fontSize: 12, color: '#4b5871', formatter: (point: {dataIndex: number}) => measureText(table, measure, shownRows[point.dataIndex]?.[measure] ?? null)}}]};
  return {...base, tooltip,
    grid: {...base.grid, bottom: shownRows.length > 12 ? 60 : 28},
    dataZoom: shownRows.length > 12 ? [{type: 'slider', height: 18, bottom: 8, brushSelect: false}] : undefined,
    xAxis: {type: 'category', data: labels, boundaryGap: spec.type === 'bar', axisLabel: {hideOverlap: true}},
    yAxis: {type: 'value', name: currencyName(table, measure), nameLocation: 'end', nameTextStyle: {align: 'left'}, splitLine: {lineStyle: {color: '#eef0f5'}}, axisLabel: {formatter: compact, hideOverlap: true}},
    series: spec.type === 'bar' ? [{type: 'bar', data: values, barMaxWidth: 32}] : [{type: 'line', data: values, connectNulls: false, showSymbol: true, symbolSize: 6, smooth: false, areaStyle: spec.type === 'area' ? {opacity: 0.15} : undefined, lineStyle: {width: 2.5}}]};
}

interface Props { table: TablePayload; measure: string; onMeasure: (measure: string) => void; height?: number; id?: string }

export function ResultChart({table, measure, onMeasure, height = 340, id}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const [showAll, setShowAll] = useState(false);
  const spec = table.chart!;
  const dimension = spec.dimensions[0];
  const isDate = table.column_types[dimension] === 'date';
  const horizontal = !isDate && spec.type === 'bar';
  const topView = horizontal && table.rows.length > TOP_N && !showAll;
  const requestedOrder = preservesRequestedOrder(table, measure);
  const rows = useMemo(() => chartRows(table, measure, topView), [table, measure, topView]);
  const shownRows = useMemo(() => topView ? rows.slice(0, TOP_N) : rows, [rows, topView]);
  const option = useMemo(() => chartOption(table, measure, shownRows), [table, measure, shownRows]);
  const excludedDates = table.rows.length - rows.length;
  const rankLabel = requestedOrder ? `First ${TOP_N} in requested order` : table.truncated ? `Top ${TOP_N} within ${rows.length} returned groups` : `Top ${TOP_N} of ${rows.length} groups`;
  const scope = topView ? `${rankLabel}${requestedOrder ? '' : `, ranked by ${MEASURE_LABELS[measure] ?? label(measure)}`}.` : table.truncated ? `${rows.length} of ${table.total_rows} matching groups returned.` : `${rows.length} groups.`;
  const description = spec.type === 'scatter' ? `${label(spec.measures[0])} versus ${label(spec.measures[1])} by ${label(dimension)}. ${scope}` : `${MEASURE_LABELS[measure] ?? label(measure)} by ${label(dimension)}. ${scope}`;

  useEffect(() => {
    if (!host.current) return;
    const chart = chartRef.current ?? echarts.init(host.current, undefined, {renderer: 'svg'});
    chartRef.current = chart;
    chart.setOption(option, true);
    const observer = new ResizeObserver(() => chart.resize()); observer.observe(host.current);
    return () => observer.disconnect();
  }, [option]);
  useEffect(() => () => { chartRef.current?.dispose(); chartRef.current = null; }, []);
  const rowHeight = horizontal ? Math.max(180, 70 + shownRows.length * 30) : height;

  function exportImage(type: 'png' | 'svg') {
    const chart = chartRef.current; if (!chart) return;
    if (type === 'svg') { const encoded = chart.getDataURL({type: 'svg'}).split(',').slice(1).join(','); download('chart.svg', decodeURIComponent(encoded), 'image/svg+xml'); return; }
    const box = document.createElement('div'); box.style.cssText = `position:fixed;left:-10000px;top:0;width:${host.current?.clientWidth ?? 900}px;height:${rowHeight}px;`; document.body.append(box);
    const raster = echarts.init(box, undefined, {renderer: 'canvas', devicePixelRatio: 2}); raster.setOption({...option, backgroundColor: '#ffffff', animation: false});
    const url = raster.getDataURL({type: 'png', pixelRatio: 2, backgroundColor: '#ffffff'}); raster.dispose(); box.remove();
    const link = document.createElement('a'); link.href = url; link.download = 'chart.png'; document.body.append(link); link.click(); link.remove();
  }

  return <div data-testid="result-chart" data-chart-type={spec.type} data-shown={shownRows.length} data-total={rows.length}>
    <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
      {spec.type !== 'scatter' && spec.measures.length > 1 && <label className="flex items-center gap-2 text-ink-2">Measure<select value={measure} onChange={event => onMeasure(event.target.value)} aria-label="Chart measure" className="h-8 rounded-md border border-line bg-canvas px-2 text-sm text-ink">{spec.measures.map(key => <option key={key} value={key}>{MEASURE_LABELS[key] ?? label(key)}</option>)}</select></label>}
      {horizontal && rows.length > TOP_N && <span className="inline-flex flex-wrap items-center gap-2 text-ink-2"><span className="rounded-md bg-surface px-2 py-1 text-xs" data-testid="chart-limit">{showAll ? `${rows.length} returned groups · query order` : rankLabel}</span><Button variant="link" size="xs" onClick={() => setShowAll(value => !value)}>{showAll ? `Show ${requestedOrder ? 'first' : 'top'} ${TOP_N}` : `Show all ${rows.length}`}</Button></span>}
      <span className="ml-auto"><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="xs" aria-label="Download chart"><Download />Download</Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => exportImage('png')}>PNG image</DropdownMenuItem><DropdownMenuItem onSelect={() => exportImage('svg')}>SVG vector</DropdownMenuItem></DropdownMenuContent></DropdownMenu></span>
    </div>
    <div className="max-h-[620px] overflow-y-auto scroll-thin"><div ref={host} role="img" aria-label={description} id={id} style={{height: rowHeight}} className="w-full" /></div>
    <p className="mt-2 text-xs text-ink-3">{description}{isDate && ' Dates are chronological.'}{excludedDates > 0 && ` ${excludedDates} groups without a valid date are available in Data.`}{topView && table.truncated && (requestedOrder ? ` ${rows.length} of ${table.total_rows} matching groups were returned.` : ' Rankings apply only to this returned subset.')}</p>
  </div>;
}

function compact(value: number) { return new Intl.NumberFormat(undefined, {notation: 'compact', maximumFractionDigits: 1}).format(value); }
function escape(text: string) { return text.replace(/[&<>"']/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[character] as string); }
function currencyName(table: TablePayload, measure: string) {
  const unit = measure === 'deal_size' ? 'USD' : measure === 'amount' ? table.metadata?.currency?.code ?? '' : '';
  const name = measure === 'deal_size' ? 'Deal size' : MEASURE_LABELS[measure] ?? label(measure);
  return unit ? `${name} (${unit})` : name;
}
export function exactValue(value: Cell) { return formatNumber(value, null); }
