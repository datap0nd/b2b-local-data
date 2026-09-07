import {useEffect, useMemo, useRef, useState} from 'react';
import * as echarts from 'echarts';
import {Download} from 'lucide-react';
import {Button} from './ui/button';
import {DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger} from './ui/dropdown-menu';
import {axisLabel, formatNumber, label, measureText, MEASURE_LABELS} from '@/format';
import {download} from '@/lib/utils';
import type {Cell, TablePayload} from '@/types';

export const TOP_N = 10;
const COLORS = ['#047857', '#1d4ed8', '#b45309', '#7c3aed', '#be123c'];

/** Chart rows are the returned groups in server order; they never follow table sorting. */
export function chartRows(table: TablePayload): Record<string, Cell>[] { return table.rows; }

interface Props { table: TablePayload; measure: string; onMeasure: (m: string) => void; height?: number; id?: string }

/** ECharts presentation of a grouped result: horizontal bars for categories (top ten with access to the rest),
 *  chronological lines/areas for dates with zoom over the whole returned range, scatter for two measures.
 *  SVG rendering, exact-value tooltips, currency-labelled axes, an accessible description, no decoration. */
export function ResultChart({table, measure, onMeasure, height = 320, id}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const spec = table.chart!;
  const dimension = spec.dimensions[0];
  const isDate = table.column_types[dimension] === 'date';
  const scatter = spec.type === 'scatter';
  const rows = chartRows(table);
  const [showAll, setShowAll] = useState(false);
  const categorical = !isDate && !scatter;
  const shownRows = categorical && !showAll && rows.length > TOP_N ? rows.slice(0, TOP_N) : rows;
  const yMeasure = scatter ? spec.measures[1] : measure;

  const option = useMemo<echarts.EChartsOption>(() => {
    const labels = shownRows.map(r => axisLabel(table, dimension, r[dimension]));
    const num = (v: Cell) => (v == null ? null : Number(v));
    const fmt = (m: string, v: Cell) => measureText(table, m, v);
    const base: echarts.EChartsOption = {
      color: COLORS,
      animationDuration: 200,
      textStyle: {fontFamily: 'Inter, system-ui, sans-serif', color: '#374151'},
      grid: {left: 12, right: 24, top: 12, bottom: isDate ? 56 : 28, containLabel: true},
      tooltip: {trigger: scatter ? 'item' : 'axis', confine: true, borderColor: '#e5e7eb', textStyle: {fontSize: 12}},
      aria: {enabled: true, decal: {show: false}},
    };
    if (scatter) {
      const xm = spec.measures[0];
      const points = rows.filter(r => r[xm] != null && r[yMeasure] != null).map(r => ({value: [num(r[xm]), num(r[yMeasure])], name: axisLabel(table, dimension, r[dimension]), raw: [r[xm], r[yMeasure]]}));
      return {...base,
        xAxis: {type: 'value', name: MEASURE_LABELS[xm] ?? label(xm), nameLocation: 'middle', nameGap: 28, splitLine: {lineStyle: {color: '#eef0f2'}}, axisLabel: {formatter: (v: number) => compact(v)}},
        yAxis: {type: 'value', name: MEASURE_LABELS[yMeasure] ?? label(yMeasure), splitLine: {lineStyle: {color: '#eef0f2'}}, axisLabel: {formatter: (v: number) => compact(v)}},
        tooltip: {...base.tooltip, formatter: (p: unknown) => { const d = (p as {data: {name: string; raw: Cell[]}}).data; return `<b>${escape(d.name)}</b><br/>${label(xm)}: ${fmt(xm, d.raw[0])}<br/>${label(yMeasure)}: ${fmt(yMeasure, d.raw[1])}`; }},
        series: [{type: 'scatter', data: points, symbolSize: 10}]};
    }
    if (isDate) {
      const data = rows.map(r => (r[measure] == null ? null : num(r[measure])));
      return {...base,
        dataZoom: rows.length > 12 ? [{type: 'slider', height: 18, bottom: 8, brushSelect: false}] : undefined,
        xAxis: {type: 'category', data: rows.map(r => axisLabel(table, dimension, r[dimension])), boundaryGap: spec.type !== 'line', axisLabel: {hideOverlap: true}},
        yAxis: {type: 'value', name: currencyName(table, measure), splitLine: {lineStyle: {color: '#eef0f2'}}, axisLabel: {formatter: (v: number) => compact(v)}},
        tooltip: {...base.tooltip, formatter: (params: unknown) => { const p = (params as {dataIndex: number; name: string}[])[0]; const r = rows[p.dataIndex]; return `<b>${escape(p.name)}</b><br/>${MEASURE_LABELS[measure] ?? label(measure)}: ${r ? fmt(measure, r[measure]) : '—'}`; }},
        series: [{type: 'line', data, connectNulls: false, showSymbol: true, symbolSize: 6, smooth: false, areaStyle: spec.type === 'area' ? {opacity: 0.15} : undefined, lineStyle: {width: 2}}]};
    }
    const values = shownRows.map(r => (r[measure] == null ? null : num(r[measure])));
    return {...base,
      grid: {...base.grid, left: 8, bottom: 24, right: 96},
      yAxis: {type: 'category', data: labels, inverse: true, axisTick: {show: false}, axisLine: {show: false}, axisLabel: {width: 220, overflow: 'truncate', fontSize: 12}},
      xAxis: {type: 'value', name: currencyName(table, measure), nameLocation: 'end', splitLine: {lineStyle: {color: '#eef0f2'}}, axisLabel: {formatter: (v: number) => compact(v)}},
      tooltip: {...base.tooltip, formatter: (params: unknown) => { const p = (params as {dataIndex: number; name: string}[])[0]; const r = shownRows[p.dataIndex]; return `<b>${escape(p.name)}</b><br/>${MEASURE_LABELS[measure] ?? label(measure)}: ${r ? fmt(measure, r[measure]) : '—'}`; }},
      series: [{type: 'bar', data: values, barMaxWidth: 26, label: {show: true, position: 'right', fontSize: 12, color: '#374151', formatter: (p: {dataIndex: number}) => { const r = shownRows[p.dataIndex]; return r ? fmt(measure, r[measure]) : ''; }}}]};
  }, [table, shownRows, rows, measure, yMeasure, dimension, isDate, scatter, spec]);

  useEffect(() => {
    if (!host.current) return;
    const chart = chartRef.current ?? echarts.init(host.current, undefined, {renderer: 'svg'});
    chartRef.current = chart;
    chart.setOption(option, true);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(host.current);
    return () => observer.disconnect();
  }, [option]);
  useEffect(() => () => { chartRef.current?.dispose(); chartRef.current = null; }, []);

  const rowHeight = categorical ? Math.max(height, Math.min(520, 40 + shownRows.length * 30)) : height;
  const description = scatter ? `${label(spec.measures[0])} versus ${label(spec.measures[1])} by ${label(dimension)}, ${rows.length} points.`
    : `${MEASURE_LABELS[measure] ?? label(measure)} by ${label(dimension)}: ${shownRows.length} of ${rows.length} groups shown${categorical && rows.length > TOP_N && !showAll ? ' (top ten)' : ''}. Exact values are in the data table.`;

  function exportImage(type: 'png' | 'svg') {
    const chart = chartRef.current; if (!chart) return;
    if (type === 'svg') {
      // The SVG renderer's data URL is "data:image/svg+xml;charset=UTF-8,<url-encoded markup>": the vector chart as drawn.
      const encoded = chart.getDataURL({type: 'svg'}).split(',').slice(1).join(',');
      download('chart.svg', decodeURIComponent(encoded), 'image/svg+xml');
      return;
    }
    const box = document.createElement('div'); box.style.cssText = `position:fixed;left:-10000px;top:0;width:${host.current?.clientWidth ?? 900}px;height:${rowHeight}px;`; document.body.append(box);
    const raster = echarts.init(box, undefined, {renderer: 'canvas', devicePixelRatio: 2}); raster.setOption({...option, backgroundColor: '#ffffff', animation: false});
    const url = raster.getDataURL({type: 'png', pixelRatio: 2, backgroundColor: '#ffffff'}); raster.dispose(); box.remove();
    const link = document.createElement('a'); link.href = url; link.download = 'chart.png'; document.body.append(link); link.click(); link.remove();
  }

  return (
    <div data-testid="result-chart" data-chart-type={spec.type} data-shown={shownRows.length} data-total={rows.length}>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
        {!scatter && spec.measures.length > 1 && (
          <label className="flex items-center gap-2 text-ink-2">Measure
            <select value={measure} onChange={e => onMeasure(e.target.value)} aria-label="Chart measure" className="h-8 rounded-md border border-line bg-canvas px-2 text-sm text-ink">
              {spec.measures.map(m => <option key={m} value={m}>{MEASURE_LABELS[m] ?? label(m)}</option>)}
            </select>
          </label>
        )}
        {categorical && rows.length > TOP_N && (
          <span className="inline-flex items-center gap-2 text-ink-2">
            <span className="rounded-md bg-surface px-2 py-0.5 text-xs" data-testid="chart-limit">{showAll ? `All ${rows.length} groups` : `Top ${TOP_N} of ${rows.length} groups`}</span>
            <Button variant="link" size="xs" onClick={() => setShowAll(v => !v)}>{showAll ? `Show top ${TOP_N}` : `Show all ${rows.length}`}</Button>
          </span>
        )}
        <span className="ml-auto">
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="ghost" size="xs" aria-label="Download chart"><Download />Download</Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => exportImage('png')}>PNG image</DropdownMenuItem><DropdownMenuItem onSelect={() => exportImage('svg')}>SVG vector</DropdownMenuItem></DropdownMenuContent>
          </DropdownMenu>
        </span>
      </div>
      <div ref={host} role="img" aria-label={description} id={id} style={{height: rowHeight}} className="w-full" />
      <p className="mt-1 text-xs text-ink-3">{description}</p>
    </div>
  );
}

function compact(v: number) { return new Intl.NumberFormat(undefined, {notation: 'compact', maximumFractionDigits: 1}).format(v); }
function escape(text: string) { return text.replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c] as string); }
function currencyName(table: TablePayload, measure: string) {
  const unit = measure === 'deal_size' ? 'USD' : measure === 'amount' ? table.metadata?.currency?.code ?? '' : '';
  const name = MEASURE_LABELS[measure] ?? label(measure);
  return unit ? `${name} (${unit})` : name;
}
export function exactValue(value: Cell) { return formatNumber(value, null); }
