import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {ResultCard} from './components/ResultCard';
import {TooltipProvider} from './components/ui/tooltip';
import {fixtureAnswer, supportingFixtureAnswer, supportingFixtureTable} from './testFixtures';
import {api} from './api';
import type {AnswerPayload} from './types';

vi.mock('./components/ResultChart', () => ({ResultChart: () => <div data-testid="result-chart" />}));
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function show(answer: AnswerPayload, onRerun = vi.fn()) {
  return render(<TooltipProvider><ResultCard answer={answer} shown={answer.table} view="summary" presentation={answer.table.presentation} onView={vi.fn()} onPresentation={vi.fn()} onExplore={vi.fn()} onSuggestion={vi.fn()} onRerun={onRerun} /></TooltipProvider>);
}

it('immediately shows eight supporting opportunities below one count without a new request', () => {
  const request = vi.spyOn(api, 'supporting');
  show(supportingFixtureAnswer());
  expect(screen.getAllByText('1,005')).toHaveLength(1);
  expect(screen.getByTestId('supporting-preview').querySelectorAll('tbody tr')).toHaveLength(8);
  expect(screen.getByText('Invented opportunity 1')).toBeTruthy();
  expect(screen.getByTestId('supporting-scope').textContent).toBe('All products in matching opportunities');
  expect(request).not.toHaveBeenCalled();
});

it('loads full-snapshot pages and delegates sorting instead of sorting the preview locally', async () => {
  const full = supportingFixtureTable();
  const request = vi.spyOn(api, 'supporting').mockImplementation(async (_session, _turn, view, page, pageSize, sort) => ({available: true, view, page, page_size: pageSize, total_rows: 1005, table: {...full, rows: (sort?.direction === 'desc' ? full.rows.slice().reverse() : full.rows).slice(page * pageSize, (page + 1) * pageSize)}}));
  show(supportingFixtureAnswer());
  fireEvent.click(screen.getByTestId('supporting-explore'));
  const panel = within(screen.getByTestId('supporting-panel'));
  await waitFor(() => expect(panel.getByTestId('result-table').querySelectorAll('tbody tr')).toHaveLength(50));
  fireEvent.click(panel.getByLabelText('Last page'));
  await waitFor(() => expect(panel.getByText('Invented opportunity 1005')).toBeTruthy());
  expect(request).toHaveBeenLastCalledWith('synthetic', 1, 'summary', 20, 50, undefined, undefined);
  fireEvent.click(panel.getByRole('button', {name: 'Amount (USD)'}));
  await waitFor(() => expect(request).toHaveBeenLastCalledWith('synthetic', 1, 'summary', 0, 50, {field: 'opportunity_amount', direction: 'asc'}, undefined));
  await waitFor(() => expect(panel.getByRole('button', {name: 'Amount (USD)'}).hasAttribute('disabled')).toBe(false));
  fireEvent.click(panel.getByRole('button', {name: 'Amount (USD)'}));
  await waitFor(() => expect(request).toHaveBeenLastCalledWith('synthetic', 1, 'summary', 0, 50, {field: 'opportunity_amount', direction: 'desc'}, undefined));
  expect(panel.getByTestId('supporting-filters').textContent).toContain('Amount more than 100,000');
});

it('shows an honest rerun prompt for old evidence and never fetches current records', () => {
  const request = vi.spyOn(api, 'supporting'); const rerun = vi.fn();
  show(fixtureAnswer(), rerun);
  expect(screen.getByTestId('supporting-unavailable').textContent).toContain('were not saved');
  expect(screen.queryByTestId('supporting-explore')).toBeNull();
  expect(request).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', {name: 'Run with current data'}));
  expect(rerun).toHaveBeenCalledOnce();
});

it('keeps a saved preview honest when storage fails, and row answers have no duplicate evidence list', () => {
  const answer = supportingFixtureAnswer();
  answer.supporting!.available = false; answer.supporting!.message = 'The full records could not be saved.';
  const {unmount} = show(answer);
  expect(screen.getByTestId('supporting-preview').querySelectorAll('tbody tr')).toHaveLength(8);
  expect(screen.getByTestId('supporting-unavailable').textContent).toContain('could not be saved');
  expect(screen.queryByTestId('supporting-export')).toBeNull();
  unmount();
  show(fixtureAnswer(supportingFixtureTable()));
  expect(screen.queryByTestId('supporting-records')).toBeNull();
  expect(screen.getAllByTestId('result-table')).toHaveLength(1);
});
