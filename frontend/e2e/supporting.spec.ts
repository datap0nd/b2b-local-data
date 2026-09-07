import {expect, test} from './fixtures';
import type {Page} from '@playwright/test';
import {fixtureAnswer, fixtureTable, supportingFixtureAnswer, supportingFixtureTable} from '../src/testFixtures';
import type {AnswerPayload, ViewName} from '../src/types';

async function mockSavedAnswer(page: Page, answer: AnswerPayload, saved = true) {
  const requests: URL[] = []; let queryCalls = 0;
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname;
    if (/\/(ask|sample|rerun)$/.test(path)) queryCalls++;
    if (path.includes('/supporting')) {
      requests.push(url);
      const view = (url.searchParams.get('view') ?? 'summary') as ViewName;
      const full = supportingFixtureTable(view);
      if (url.searchParams.get('direction') === 'desc') full.rows.reverse();
      if (path.endsWith('.csv')) {
        const csv = [full.columns, ...full.rows.map(row => full.columns.map(column => row[column]))].map(row => row.map(value => `"${String(value ?? '').replaceAll('"', '""')}"`).join(',')).join('\r\n');
        await route.fulfill({contentType: 'text/csv;charset=utf-8', body: csv}); return;
      }
      const index = Number(url.searchParams.get('page')), size = Number(url.searchParams.get('page_size'));
      await route.fulfill({json: {available: true, view, page: index, page_size: size, total_rows: full.total_rows, table: {...full, rows: full.rows.slice(index * size, (index + 1) * size), truncated: true}}}); return;
    }
    const data = path === '/api/bootstrap' ? {identity: {login_required: false, name: 'Fixture reviewer', mode: 'demo'}, capabilities: {acceptance_ui: true, samples: true, saved_results: true, contract_version: 3, views: ['summary', 'detail'], presentations: ['cards', 'chart', 'table']}}
      : path === '/api/freshness' ? {freshness: {status: 'verified', updated_at: new Date(Date.now() - 60_000).toISOString(), timezone: 'UTC', method: 'freshness_view', reason: null}}
      : path === '/api/sessions' ? {sessions: []}
      : path === '/api/sample' ? answer
      : path === '/api/sessions/synthetic' ? {id: 'synthetic', title: 'Invented opportunity review', active_plan: {}, turns: [{id: 1, question: 'How many open opportunities close in 2026 with amount over 100,000 USD?', kind: 'data', plan: {}, has_result: true, created_at: '2026-01-01T12:00:00Z'}]}
      : path.endsWith('/result') ? {available: true, ...answer}
      : {};
    await route.fulfill({json: data});
  });
  if (saved) await page.addInitScript(() => localStorage.setItem('b2b-session', 'synthetic'));
  await page.goto('/');
  if (!saved) await page.getByRole('button', {name: 'Opportunity summary', exact: true}).click();
  await expect(page.getByTestId('result-card')).toBeVisible();
  return {requests, queryCalls: () => queryCalls};
}

test('a count immediately includes its saved opportunities, products and complete row details', async ({page}, info) => {
  const {requests, queryCalls} = await mockSavedAnswer(page, supportingFixtureAnswer());
  const card = page.getByTestId('result-card'), support = page.getByTestId('supporting-records');
  await expect(card.getByText('1,005', {exact: true})).toHaveCount(1);
  await expect(card.getByTestId('answer-title')).toBeInViewport({ratio: 1});
  await expect(card.getByTestId('answer-context')).toBeInViewport({ratio: 1});
  await expect(card.getByTestId('metrics')).toBeInViewport({ratio: 1});
  await expect(support.getByRole('heading', {name: 'Supporting opportunities', exact: true})).toBeVisible();
  await expect(support.locator('tbody tr')).toHaveCount(8);
  await expect(support.getByText('DEMO-0001', {exact: true})).toBeVisible();
  expect(requests).toHaveLength(0); expect(queryCalls()).toBe(0);
  await page.screenshot({path: info.outputPath('supporting-scalar.png'), fullPage: true});
  await support.getByLabel('Row details').first().click();
  await expect(page.getByTestId('row-details')).toContainText('Saved evidence note 1');
  await expect(page.getByTestId('row-details')).toContainText('DISPLAY-A; DISPLAY-B');
  await page.screenshot({path: info.outputPath('supporting-details.png'), fullPage: true});
  await page.keyboard.press('Escape');
  await support.getByRole('button', {name: 'Products', exact: true}).click();
  await expect(support.getByRole('heading', {name: 'Supporting product rows', exact: true})).toBeVisible();
  await expect(support.getByTestId('supporting-scope')).toHaveText('All products in matching opportunities');
  await expect(support.getByText('Example display', {exact: true})).toHaveCount(8);
  expect(requests).toHaveLength(0); expect(queryCalls()).toBe(0);
});

test('full saved evidence reaches rows beyond 1000, sorts across every row and exports exact full CSV', async ({page, isMobile}, info) => {
  const {requests, queryCalls} = await mockSavedAnswer(page, supportingFixtureAnswer());
  await page.getByTestId('supporting-explore').click();
  const panel = page.getByTestId('supporting-panel');
  await expect(panel.locator('tbody tr')).toHaveCount(50);
  await expect(panel.getByTestId('supporting-filters').locator('li')).toHaveText(['Open opportunities', 'Closing in 2026', 'Amount more than 100,000']);
  await panel.getByLabel('Last page').click();
  await expect(panel.getByTestId('page-summary')).toHaveText('Page 21 of 21');
  await expect(panel.locator('tbody tr')).toHaveCount(5);
  await expect(panel.getByText('DEMO-1005', {exact: true})).toBeVisible();
  expect(requests.at(-1)?.searchParams.get('page')).toBe('20');
  const header = panel.locator('th[data-column="opportunity_amount"]');
  await header.getByRole('button').click();
  await expect(panel.getByRole('status')).toHaveCount(0);
  if (await header.getAttribute('aria-sort') !== 'descending') await header.getByRole('button').click();
  await expect(panel.locator('tbody tr').first()).toContainText('DEMO-1005');
  await expect(panel.getByTestId('page-summary')).toHaveText('Page 1 of 21');
  expect(requests.at(-1)?.searchParams.get('sort')).toBe('opportunity_amount');
  expect(requests.at(-1)?.searchParams.get('direction')).toBe('desc');
  const longAmount = panel.getByText('9,007,199,254,740,992.03', {exact: true});
  await longAmount.scrollIntoViewIfNeeded();
  await expect(longAmount).toBeVisible();
  if (isMobile) {
    await expect(panel.locator('tbody tr').first().locator('td').first()).toHaveCSS('position', 'static');
    expect(await longAmount.evaluate(element => {
      const rect = element.getBoundingClientRect();
      const tableViewport = element.closest('table')!.parentElement!.getBoundingClientRect();
      return rect.left >= tableViewport.left && rect.right <= tableViewport.right && [rect.left + 1, (rect.left + rect.right) / 2, rect.right - 1].every(x => element.contains(document.elementFromPoint(x, rect.top + rect.height / 2)));
    })).toBe(true);
  } else await expect(panel.locator('tbody tr').first().locator('td').first()).toHaveCSS('position', 'sticky');
  await page.screenshot({path: info.outputPath('supporting-full.png'), fullPage: true});
  const downloadEvent = page.waitForEvent('download');
  await panel.getByTestId('supporting-export').click();
  const downloaded = await downloadEvent;
  expect(downloaded.suggestedFilename()).toBe('b2b-supporting-opportunities.csv');
  const stream = await downloaded.createReadStream(); let csv = ''; for await (const part of stream!) csv += part.toString();
  expect(csv.split('\r\n')).toHaveLength(1006);
  expect(csv.split('\r\n')[1]).toContain('DEMO-1005');
  expect(csv).toContain('9007199254740992.030');
  expect(csv).toContain('Saved evidence note 1005');
  expect(requests.at(-1)?.searchParams.get('sort')).toBe('opportunity_amount');
  expect(requests.at(-1)?.searchParams.has('page')).toBe(false);
  await panel.getByRole('button', {name: 'Columns', exact: true}).click();
  await page.getByRole('menuitemcheckbox', {name: 'Opportunity no.', exact: true}).click();
  if (await page.getByRole('menu').isVisible()) await page.keyboard.press('Escape');
  await panel.locator('th[data-column="opportunity_no"]').getByRole('button').click();
  await expect.poll(() => requests.at(-1)?.searchParams.get('sort')).toBe('opportunity_no');
  await panel.getByRole('button', {name: 'Products', exact: true}).click();
  await expect(panel.locator('th[data-column="pet_name"]')).toBeVisible();
  expect(requests.at(-1)?.searchParams.get('view')).toBe('detail');
  expect(queryCalls()).toBe(0);
});

test('grouped Chart and Data keep supporting records underneath', async ({page}, info) => {
  const answer = supportingFixtureAnswer();
  answer.table = fixtureTable({columns: ['stage', 'opportunity_count'], column_types: {stage: 'text', opportunity_count: 'number'}, rows: [{stage: 'Qualified', opportunity_count: 503}, {stage: 'Negotiation', opportunity_count: 502}], total_rows: 2, presentation: 'chart', chart: {type: 'bar', dimensions: ['stage'], measures: ['opportunity_count']}});
  answer.answer = {title: 'Opportunities by stage', context: 'Closing in 2026 · Amount over 100,000 USD', sentence: '', metrics: []};
  await mockSavedAnswer(page, answer);
  await expect(page.getByTestId('result-chart')).toBeVisible();
  await expect(page.getByTestId('supporting-preview').locator('tbody tr')).toHaveCount(8);
  await expect(page.getByTestId('primary-result').getByTestId('result-table')).toHaveCount(0);
  await expect(page.getByTestId('answer-title')).toBeInViewport({ratio: 1});
  await page.screenshot({path: info.outputPath('supporting-chart.png'), fullPage: true});
  await page.getByRole('button', {name: 'Data', exact: true}).click();
  await expect(page.getByTestId('result-chart')).toHaveCount(0);
  await expect(page.getByTestId('primary-result').locator('tbody tr')).toHaveCount(2);
  await expect(page.getByTestId('supporting-preview').locator('tbody tr')).toHaveCount(8);
});

test('a newly completed long answer opens at its headline and context', async ({page}) => {
  const {requests, queryCalls} = await mockSavedAnswer(page, supportingFixtureAnswer(), false);
  await expect(page.getByTestId('answer-title')).toBeInViewport({ratio: 1});
  await expect(page.getByTestId('answer-context')).toBeInViewport({ratio: 1});
  await expect(page.getByTestId('metrics')).toBeInViewport({ratio: 1});
  expect(queryCalls()).toBe(1); expect(requests).toHaveLength(0);
});

test('finishing a long answer preserves scrollback until New answer is chosen', async ({page}) => {
  await mockSavedAnswer(page, supportingFixtureAnswer());
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/ask', async route => { await pending; await route.fulfill({json: {...supportingFixtureAnswer(), turn_id: 2}}); });
  try {
    await page.getByLabel('Your question').fill('Show the next saved analysis');
    await page.getByLabel('Your question').press('Enter');
    await expect(page.getByTestId('assistant-turn').last()).toHaveAttribute('data-status', 'pending');
    // Let the deliberate smooth-scroll grace period finish, then generate a native scroll event on either device.
    await page.waitForTimeout(1000);
    const scroller = page.getByTestId('conversation');
    await scroller.evaluate(element => element.scrollTo({top: 0, behavior: 'instant'}));
    await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBe(0);
    release();
    await expect(page.getByTestId('result-card')).toHaveCount(2);
    await expect(page.getByTestId('new-answer')).toBeVisible();
    expect(await scroller.evaluate(element => element.scrollTop)).toBe(0);
    await page.getByTestId('new-answer').click();
    await expect(page.getByTestId('answer-title').last()).toBeInViewport({ratio: 1});
    await expect(page.getByTestId('answer-context').last()).toBeInViewport({ratio: 1});
  } finally { release(); }
});

test('a saved aggregate without supporting records offers an explicit rerun and does not fetch new evidence', async ({page}) => {
  const {requests, queryCalls} = await mockSavedAnswer(page, fixtureAnswer());
  await expect(page.getByTestId('supporting-unavailable')).toContainText('Supporting records were not saved');
  await expect(page.getByTestId('supporting-unavailable').getByRole('button', {name: 'Run with current data'})).toBeVisible();
  await expect(page.getByTestId('supporting-preview')).toHaveCount(0);
  expect(requests).toHaveLength(0); expect(queryCalls()).toBe(0);
});
