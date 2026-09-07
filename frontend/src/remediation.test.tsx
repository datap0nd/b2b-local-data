import {afterEach, describe, expect, it, vi} from 'vitest';
import {act, cleanup, fireEvent, render, renderHook, screen} from '@testing-library/react';
import {ResultCard} from './components/ResultCard';
import {Freshness, freshnessState, FRESH_FOR} from './components/Freshness';
import {QualityPanel, qualityRows} from './components/QualityPanel';
import {TooltipProvider} from './components/ui/tooltip';
import {fixtureAnswer, fixtureTable} from './testFixtures';
import {useFreshness} from './useFreshness';
import {api} from './api';
import type {Freshness as FreshnessInfo, QualityWarning} from './types';

vi.mock('./components/ResultChart', () => ({ResultChart: () => <div data-testid="result-chart" />}));
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });
const verified = (timestamp: string): FreshnessInfo => ({status: 'verified', updated_at: timestamp, timezone: 'UTC', method: 'freshness_view', reason: null});
const wrap = ({children}: {children: React.ReactNode}) => <TooltipProvider>{children}</TooltipProvider>;

describe('one answer presentation', () => {
  it('shows all five explicitly requested scalar measures without dropping the last two', () => {
    const answer = fixtureAnswer();
    answer.table.columns = ['amount', 'quantity', 'sku_count', 'opportunity_count', 'deal_size'];
    answer.answer.metrics = [
      {label: 'Amount', value: '100.00 USD', raw: '100'}, {label: 'Quantity', value: '23', raw: 23}, {label: 'Products', value: '7', raw: 7}, {label: 'Opportunities', value: '5', raw: 5}, {label: 'Deal size', value: '220.00 USD', raw: '220'},
    ];
    render(<ResultCard answer={answer} shown={answer.table} view="summary" presentation="cards" onView={vi.fn()} onPresentation={vi.fn()} onExplore={vi.fn()} onSuggestion={vi.fn()} />, {wrapper: wrap});
    expect(screen.getByTestId('metrics').querySelectorAll('dd')).toHaveLength(5);
    expect(screen.getByText('220.00 USD')).toBeTruthy();
  });
  it('renders the requested count once, one context and no repeated scope, values or freshness', () => {
    const answer = fixtureAnswer();
    render(<ResultCard answer={answer} shown={answer.table} view="summary" presentation="cards" onView={vi.fn()} onPresentation={vi.fn()} onExplore={vi.fn()} onSuggestion={vi.fn()} />, {wrapper: wrap});
    expect(screen.getAllByText('545')).toHaveLength(1);
    expect(screen.getAllByText('Closing in 2026')).toHaveLength(2); // visible context + initially collapsed query detail
    expect(screen.getByTestId('query-details').hasAttribute('open')).toBe(false);
    expect(screen.queryByTestId('value-cards')).toBeNull();
    expect(screen.queryByTestId('scope')).toBeNull();
    expect(screen.queryByTestId('freshness')).toBeNull();
    expect(screen.queryByTestId('answer-sentence')).toBeNull();
    expect(screen.getByLabelText('What does Open mean?')).toBeTruthy();
  });
  it('renders Chart or Data exclusively, including expanded analysis', () => {
    const table = fixtureTable({columns: ['stage_group', 'amount'], rows: [{stage_group: 'Open', amount: '100'}], chart: {type: 'bar', dimensions: ['stage_group'], measures: ['amount']}, column_types: {stage_group: 'text', amount: 'number'}});
    const answer = fixtureAnswer(table); answer.answer.metrics = [];
    const props = {answer, shown: table, view: 'summary' as const, expanded: true, onView: vi.fn(), onPresentation: vi.fn(), onExplore: vi.fn(), onSuggestion: vi.fn()};
    const {rerender} = render(<ResultCard {...props} presentation="chart" />, {wrapper: wrap});
    expect(screen.queryByTestId('result-table')).toBeNull();
    expect(screen.getByTestId('result-chart')).toBeTruthy();
    rerender(<ResultCard {...props} presentation="table" />);
    expect(screen.queryByTestId('result-chart')).toBeNull();
    expect(screen.getByTestId('result-table').dataset.mode).toBe('full');
  });
});

describe('dataset freshness', () => {
  const now = Date.parse('2026-09-07T12:00:00Z');
  it('uses exact age boundaries and rejects unknown, invalid and future timestamps', () => {
    expect(freshnessState(verified(new Date(now - FRESH_FOR + 1).toISOString()), now)).toBe('fresh');
    expect(freshnessState(verified(new Date(now - FRESH_FOR).toISOString()), now)).toBe('stale');
    expect(freshnessState(verified(new Date(now + 1).toISOString()), now)).toBe('unknown');
    expect(freshnessState(verified('invalid'), now)).toBe('unknown');
    expect(freshnessState(null, now)).toBe('unknown');
  });
  it('crosses 24 hours while open and exposes a focusable timestamp', () => {
    vi.useFakeTimers(); vi.setSystemTime(now);
    render(<Freshness freshness={verified(new Date(now - FRESH_FOR + 1000).toISOString())} />, {wrapper: wrap});
    expect(screen.getByTestId('freshness').dataset.status).toBe('fresh');
    act(() => { vi.advanceTimersByTime(1000); });
    expect(screen.getByTestId('freshness').dataset.status).toBe('stale');
    expect(screen.getByRole('button').getAttribute('aria-label')).toContain('Data updated');
  });
  it('reads only after login, reuses recent reads, refreshes on focus, and clears on failure', async () => {
    vi.useFakeTimers(); vi.setSystemTime(now);
    const call = vi.spyOn(api, 'freshness').mockResolvedValue({freshness: verified('2026-09-07T11:00:00Z')});
    const {result, rerender} = renderHook(({auth}) => useFreshness(auth), {initialProps: {auth: false}});
    expect(call).not.toHaveBeenCalled();
    await act(async () => { rerender({auth: true}); });
    expect(result.current?.updated_at).toBe('2026-09-07T11:00:00Z');
    await act(async () => { window.dispatchEvent(new Event('focus')); });
    expect(call).toHaveBeenCalledTimes(1);
    call.mockRejectedValueOnce(new Error('offline'));
    await act(async () => { vi.advanceTimersByTime(60_000); window.dispatchEvent(new Event('focus')); });
    expect(call).toHaveBeenCalledTimes(2);
    expect(result.current).toBeNull();
  });
});

describe('saved quality evidence', () => {
  const warning: QualityWarning = {code: 'quality_warning', count: 61, message: '61 opportunities have differences requiring review.', records: Array.from({length: 61}, (_, index) => ({opportunity_no: `FAKE${index}`, opportunity_name: `Invented opportunity ${index}`, issues: [{code: 'amount_mismatch', message: 'Product amounts do not match the exported total.', product_total: '100.015', exported_total: '100', difference: '0.015', currency: 'USD'}]}))};
  it('provides every saved record through pagination and search beyond the first 50', () => {
    render(<QualityPanel warning={warning} open onClose={vi.fn()} />);
    expect(screen.getByTestId('quality-table').querySelectorAll('tbody tr')).toHaveLength(20);
    fireEvent.click(screen.getByLabelText('Next review page'));
    expect(screen.getByText('FAKE20')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Search quality review'), {target: {value: 'FAKE60'}});
    expect(screen.getByText('FAKE60')).toBeTruthy();
    expect(screen.getByTestId('quality-table').querySelectorAll('tbody tr')).toHaveLength(1);
    const rows = qualityRows(warning);
    expect(rows).toHaveLength(61);
    expect(rows[60]).toMatchObject({opportunity_no: 'FAKE60', product_total: '100.015', exported_total: '100', difference: '0.015', currency: 'USD'});
  });
  it('does not invent reasons or completeness for legacy saved evidence', () => {
    const legacy = {...warning, records: [{opportunity_no: 'OLD1'}]};
    render(<QualityPanel warning={legacy} open onClose={vi.fn()} />);
    expect(screen.getByTestId('quality-incomplete').textContent).toContain('1 of 61');
    expect(screen.getByText('Detailed reasons were not saved with this answer.')).toBeTruthy();
    expect(qualityRows(legacy)[0].product_total).toBeNull();
  });
});
