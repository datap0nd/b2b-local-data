import {describe, expect, it} from 'vitest';
import {chartOption, chartRows} from './components/ResultChart';
import {fixtureTable} from './testFixtures';

const grouped = () => fixtureTable({columns: ['opportunity_owner', 'amount', 'quantity'], column_types: {opportunity_owner: 'text', amount: 'number', quantity: 'number'}, chart: {type: 'bar', dimensions: ['opportunity_owner'], measures: ['amount', 'quantity']}, rows: [
  {opportunity_owner: 'Ada', amount: '9007199254740992.01', quantity: '3'}, {opportunity_owner: 'Ben', amount: '9007199254740992.02', quantity: '1'}, {opportunity_owner: 'Cy', amount: null, quantity: '4'}, {opportunity_owner: 'Dee', amount: '9007199254740992.02', quantity: '2'},
], total_rows: 4});

describe('chart semantics', () => {
  it('ranks the selected measure using exact decimals, deterministic ties and nulls last', () => {
    const table = grouped();
    expect(chartRows(table, 'amount', true).map(row => row.opportunity_owner)).toEqual(['Ben', 'Dee', 'Ada', 'Cy']);
    expect(chartRows(table, 'quantity', true).map(row => row.opportunity_owner)).toEqual(['Cy', 'Ada', 'Dee', 'Ben']);
    expect(table.rows.map(row => row.opportunity_owner)).toEqual(['Ada', 'Ben', 'Cy', 'Dee']);
    expect(chartRows(table, 'amount', false)).toEqual(table.rows);
  });
  it('preserves explicit query ordering when it differs from descending selected measure', () => {
    const table = grouped(); table.metadata.sort = [{field: 'opportunity_owner', direction: 'asc'}];
    expect(chartRows(table, 'amount', true)).toEqual(table.rows);
    table.metadata.sort = [{field: 'amount', direction: 'asc'}];
    expect(chartRows(table, 'amount', true)).toEqual(table.rows);
    table.metadata.sort = [{field: 'amount', direction: 'desc'}, {field: 'opportunity_owner', direction: 'desc'}];
    table.rows = [table.rows[3], table.rows[1], table.rows[0], table.rows[2]];
    expect(chartRows(table, 'amount', true).map(row => row.opportunity_owner)).toEqual(['Dee', 'Ben', 'Ada', 'Cy']);
  });
  it.each(['bar', 'line', 'area'] as const)('renders requested %s on a chronological date axis', type => {
    const table = fixtureTable({columns: ['close_month', 'amount'], column_types: {close_month: 'date', amount: 'number'}, rows: [{close_month: '2026-03-01', amount: '3'}, {close_month: null, amount: '9'}, {close_month: 'invalid', amount: '8'}, {close_month: '2026-01-01', amount: '1'}, {close_month: '2026-02-01', amount: null}], chart: {type, dimensions: ['close_month'], measures: ['amount']}});
    const rows = chartRows(table);
    expect(rows.map(row => row.close_month)).toEqual(['2026-01-01', '2026-02-01', '2026-03-01']);
    const option = chartOption(table, 'amount', rows);
    const series = (option.series as {type: string; data: unknown[]; areaStyle?: unknown}[])[0];
    expect(series.type).toBe(type === 'bar' ? 'bar' : 'line');
    expect(series.data).toEqual([1, null, 3]);
    expect(!!series.areaStyle).toBe(type === 'area');
  });
  it.each(['line', 'area'] as const)('respects categorical %s and preserves query order', type => {
    const table = grouped(); table.chart!.type = type;
    const option = chartOption(table, 'quantity', chartRows(table));
    expect((option.xAxis as {data: string[]}).data).toEqual(['Ada', 'Ben', 'Cy', 'Dee']);
    expect((option.series as {type: string}[])[0].type).toBe('line');
  });
});
