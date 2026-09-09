import {afterEach, expect, it} from 'vitest';
import {cleanup, render, screen} from '@testing-library/react';
import {TestVerdict} from './dev/TestVerdict';
afterEach(cleanup);
it('shows supporting digest failures separately from correct primary values with exact differences', () => {
  render(<TestVerdict step={{id: 'example', status: 'fail', interpretation: {ok: true, problems: []}, data: {ok: false, checks: {digest: true, supporting_rows: false}, supporting: {ok: false, views: {detail: {ok: false, checks: {digest: false}, differences: [{expected: 'wanted', actual: 'returned'}]}}}}}} />);
  expect(screen.getByText(/Result checks: pass/).textContent).toContain('Supporting detail: digest');
  expect(screen.getByText(/"expected": "wanted"/)).toBeTruthy();
});
it('does not count review or blocked turns as checked passes', () => {
  const {rerender} = render(<TestVerdict step={{id: 'x', status: 'blocked', error: 'Missing context'}} />);
  expect(screen.getByText(/Result checks: not checked/)).toBeTruthy();
  rerender(<TestVerdict step={{id: 'x', status: 'review', interpretation: {ok: false, problems: ['Read clarification']}}} />);
  expect(screen.getByText(/Interpretation: review/)).toBeTruthy();
});
