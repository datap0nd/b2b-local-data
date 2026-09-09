import {expect, test} from './fixtures';
import {fixtureAnswer, fixtureTable} from '../src/testFixtures';
import type {Page} from '@playwright/test';
import type {AnswerPayload} from '../src/types';

async function mockApp(page: Page, payload: AnswerPayload, acceptance = true, saved = false) {
  const fresh = {status: 'verified', updated_at: new Date(Date.now() - 60 * 60_000).toISOString(), timezone: 'UTC', method: 'freshness_view', reason: null};
  let calls = 0;
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const data = path === '/api/bootstrap' ? {identity: {login_required: false, name: 'Fixture reviewer', mode: 'demo'}, capabilities: {acceptance_ui: acceptance, samples: true, saved_results: true, contract_version: 3, views: ['summary', 'detail'], presentations: ['cards', 'chart', 'table']}}
      : path === '/api/freshness' ? (calls++, {freshness: fresh})
      : path === '/api/sessions' ? {sessions: []}
      : path === '/api/sample' ? payload
      : path === '/api/sessions/synthetic' ? {id: 'synthetic', title: 'Saved fixture', active_plan: {}, turns: [{id: 1, question: 'Count open opportunities closing in 2026', kind: 'data', plan: {}, has_result: true, created_at: '2026-01-01T12:00:00Z'}]}
      : path.endsWith('/result') ? {available: true, ...payload}
      : {};
    await route.fulfill({json: data});
  });
  if (saved) await page.addInitScript(() => localStorage.setItem('b2b-session', 'synthetic'));
  await page.goto('/');
  await expect(page.getByLabel('Your question')).toBeVisible();
  if (!saved) await page.getByRole('button', {name: 'Opportunity summary', exact: true}).click();
  return () => calls;
}

test('one scalar, readable status help, global freshness, and saved history isolation', async ({page}, info) => {
  const payload = fixtureAnswer();
  payload.table.metadata.freshness = {status: 'verified', updated_at: '2020-01-01T00:00:00Z', timezone: 'UTC', method: 'freshness_view', reason: null};
  const freshnessCalls = await mockApp(page, payload, true, true);
  const card = page.getByTestId('result-card');
  await expect(card.getByText('545', {exact: true})).toHaveCount(1);
  await expect(card.getByTestId('answer-context')).toHaveText('Closing in 2026');
  await expect(card.getByTestId('scope')).toHaveCount(0);
  await expect(card.getByTestId('value-cards')).toHaveCount(0);
  await expect(card.getByTestId('freshness')).toHaveCount(0);
  const freshness = page.getByTestId('freshness').filter({visible: true}).first();
  await expect(freshness).toHaveAttribute('data-status', 'fresh');
  await freshness.focus();
  await expect(page.getByRole('tooltip')).toContainText('Data updated');
  await page.keyboard.press('Escape');
  await card.getByLabel('What does Open mean?').focus();
  await expect(page.getByRole('tooltip')).toContainText('Identified, Qualified or Negotiation');
  await page.keyboard.press('Escape');
  expect(freshnessCalls()).toBe(1);
  await page.screenshot({path: info.outputPath('scalar.png'), fullPage: true});
});

test('complete quality evidence stays searchable beyond 50 rows and exports exact amounts', async ({page}, info) => {
  const payload = fixtureAnswer();
  payload.table.metadata.warnings = [{code: 'quality_warning', count: 61, message: '61 opportunities have different product and exported totals.', records: Array.from({length: 61}, (_, index) => ({opportunity_no: `INVENTED-${index}`, opportunity_name: `Invented opportunity ${index}`, issues: [{code: 'amount_mismatch', message: 'Product total differs from exported total.', product_total: '1100.015', exported_total: '1100', difference: '0.015', currency: 'USD'}]}))}];
  await mockApp(page, payload);
  await page.getByTestId('quality').click();
  await expect(page.getByTestId('quality-table').locator('tbody tr')).toHaveCount(20);
  await page.getByLabel('Next review page').click();
  await expect(page.getByText('INVENTED-20', {exact: true})).toBeVisible();
  await page.getByLabel('Search quality review').fill('INVENTED-60');
  await expect(page.getByText('INVENTED-60', {exact: true})).toBeVisible();
  await expect(page.getByTestId('quality-table').locator('tbody tr')).toHaveCount(1);
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('button', {name: 'Download review'}).click();
  const download = await downloadEvent;
  const stream = await download.createReadStream();
  let csv = ''; for await (const part of stream!) csv += part.toString();
  expect(csv).toContain('INVENTED-60');
  expect(csv).toContain('"1100.015","1100","0.015","USD"');
  expect(csv.split('\r\n')).toHaveLength(62);
  await page.screenshot({path: info.outputPath('quality-review.png'), fullPage: true});
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('quality-panel')).toHaveCount(0);
});

test('explicitly disabled Test stays discoverable with the exact setup instruction', async ({page, isMobile}) => {
  await mockApp(page, fixtureAnswer(), false);
  if (isMobile) await page.getByTestId('test-open-mobile').click();
  else { await page.getByRole('button', {name: 'Hide history'}).click(); await page.getByTestId('test-open').click(); }
  await expect(page.getByRole('dialog')).toContainText('Test is disabled');
  await expect(page.getByRole('dialog')).toContainText('B2B_ENABLE_ACCEPTANCE_UI=true');
  await expect(page.getByRole('dialog')).toContainText('restart B2B');
});

test('top groups re-rank by the selected measure and disclose incomplete results', async ({page}) => {
  const table = fixtureTable({result_kind: 'aggregate', presentation: 'chart', columns: ['opportunity_owner', 'amount', 'quantity'], column_types: {opportunity_owner: 'text', amount: 'number', quantity: 'number'}, total_rows: 30, truncated: true,
    rows: Array.from({length: 12}, (_, index) => ({opportunity_owner: `Owner ${String(index + 1).padStart(2, '0')}`, amount: String(index + 1), quantity: String(12 - index)})),
    chart: {type: 'bar', dimensions: ['opportunity_owner'], measures: ['amount', 'quantity']}});
  const payload = fixtureAnswer(table); payload.answer = {title: 'Amount by owner', sentence: '', metrics: []};
  await mockApp(page, payload);
  const chart = page.getByTestId('result-chart');
  await expect(chart.getByTestId('chart-limit')).toHaveText('Top 10 within 12 returned groups');
  await expect(chart.locator('svg text').filter({hasText: /^Owner 12$/})).toHaveCount(1);
  await expect(chart.locator('svg text').filter({hasText: /^Owner 01$/})).toHaveCount(0);
  await page.getByLabel('Chart measure').selectOption('quantity');
  await expect(chart.locator('svg text').filter({hasText: /^Owner 01$/})).toHaveCount(1);
  await expect(chart.locator('svg text').filter({hasText: /^Owner 12$/})).toHaveCount(0);
  await expect(chart).toContainText('Rankings apply only to this returned subset.');
  await chart.getByRole('button', {name: 'Show all 12'}).click();
  await expect(chart).toHaveAttribute('data-shown', '12');
  await page.getByRole('button', {name: 'Data', exact: true}).click();
  const amountHeader = page.getByTestId('result-table').locator('th[data-column="amount"]');
  await amountHeader.getByRole('button').click();
  if (await amountHeader.getAttribute('aria-sort') !== 'descending') await amountHeader.getByRole('button').click();
  await page.getByRole('button', {name: 'Chart', exact: true}).click();
  await page.getByRole('button', {name: 'Data', exact: true}).click();
  await expect(amountHeader).toHaveAttribute('aria-sort', 'descending');
  await expect(page.getByTestId('result-table').locator('tbody tr').first()).toContainText('Owner 12');
});

test('an explicit category sort stays in requested order when the selected measure changes', async ({page}) => {
  const table = fixtureTable({result_kind: 'aggregate', presentation: 'chart', columns: ['opportunity_owner', 'amount', 'quantity'], column_types: {opportunity_owner: 'text', amount: 'number', quantity: 'number'}, total_rows: 12,
    rows: Array.from({length: 12}, (_, index) => ({opportunity_owner: `Owner ${String(index + 1).padStart(2, '0')}`, amount: String(index + 1), quantity: String(12 - index)})), chart: {type: 'bar', dimensions: ['opportunity_owner'], measures: ['amount', 'quantity']}});
  table.metadata.sort = [{field: 'opportunity_owner', direction: 'asc'}];
  const payload = fixtureAnswer(table); payload.answer = {title: 'Amount by owner', sentence: '', metrics: []};
  await mockApp(page, payload);
  const chart = page.getByTestId('result-chart');
  await expect(chart.getByTestId('chart-limit')).toHaveText('First 10 in requested order');
  await expect(chart.locator('svg text').filter({hasText: /^Owner 01$/})).toHaveCount(1);
  await expect(chart.locator('svg text').filter({hasText: /^Owner 12$/})).toHaveCount(0);
  await page.getByLabel('Chart measure').selectOption('quantity');
  await expect(chart.getByTestId('chart-limit')).toHaveText('First 10 in requested order');
});

test('CSV keeps exact decimal values and follows the current table sort', async ({page}) => {
  const table = fixtureTable({result_kind: 'rows', presentation: 'table', grain: 'opportunity_sku', columns_mode: 'only', columns: ['opportunity_no', 'quantity', 'sku_amount'], column_types: {opportunity_no: 'text', quantity: 'number', sku_amount: 'number'}, total_rows: 3,
    rows: [{opportunity_no: '001', quantity: '1', sku_amount: '9007199254740992.01'}, {opportunity_no: '003', quantity: '3', sku_amount: '9007199254740992.03'}, {opportunity_no: '002', quantity: '2', sku_amount: '9007199254740992.02'}]});
  const payload = fixtureAnswer(table); payload.answer = {title: 'Product rows', sentence: '', metrics: []};
  await mockApp(page, payload);
  const quantityHeader = page.getByTestId('result-table').locator('th[data-column="quantity"]');
  await quantityHeader.getByRole('button').click();
  if (await quantityHeader.getAttribute('aria-sort') !== 'descending') await quantityHeader.getByRole('button').click();
  const downloadEvent = page.waitForEvent('download');
  await page.getByTestId('export').click();
  const stream = await (await downloadEvent).createReadStream();
  let csv = ''; for await (const part of stream!) csv += part.toString();
  const rows = csv.split('\r\n').slice(1);
  expect(rows).toEqual(['"003","3","9007199254740992.03"', '"002","2","9007199254740992.02"', '"001","1","9007199254740992.01"']);
});

test('complete date chart includes the last group beyond 1000 and survives Data switching', async ({page}, info) => {
  const rows = Array.from({length: 1011}, (_, i) => ({close_date: new Date(Date.UTC(2023, 0, i + 1)).toISOString().slice(0, 10), opportunity_count: i === 1010 ? 85 : 1}));
  const table = fixtureTable({result_kind: 'aggregate', presentation: 'chart', columns: ['close_date', 'opportunity_count'], column_types: {close_date: 'date', opportunity_count: 'number'}, rows, total_rows: 1011, truncated: false, chart: {type: 'line', dimensions: ['close_date'], measures: ['opportunity_count']}});
  const payload = fixtureAnswer(table); payload.answer = {title: 'Opportunity count by close date', sentence: '', metrics: []};
  await mockApp(page, payload);
  const chart = page.getByTestId('result-chart');
  await expect(chart).toHaveAttribute('data-shown', '1011');
  await expect(chart).toContainText('1011 groups.');
  await page.getByRole('button', {name: 'Data', exact: true}).click();
  const downloadEvent = page.waitForEvent('download');
  await page.getByTestId('export').click();
  const stream = await (await downloadEvent).createReadStream();
  let csv = ''; for await (const part of stream!) csv += part.toString();
  expect(csv).toContain(`"${rows[1010].close_date}","85"`);
  expect(csv.split('\r\n')).toHaveLength(1012);
  await page.getByRole('button', {name: 'Chart', exact: true}).click();
  await expect(chart).toHaveAttribute('data-shown', '1011');
  await page.screenshot({path: info.outputPath('complete-date-chart.png'), fullPage: true});
});
