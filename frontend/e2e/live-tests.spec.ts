import {expect, test} from './fixtures';
import {fixtureAnswer} from '../src/testFixtures';
import {writeFile} from 'node:fs/promises';

test('live test uses real conversation rendering, keeps history isolated, and retries PNG without model calls', async ({page}, info) => {
  const answer = fixtureAnswer();
  answer.answer.title = 'Actual response title';
  answer.answer.context = 'Long evidence context. '.repeat(120);
  const steps = [1, 2, 3].map(n => ({id: `S001T${n}`, scenario_id: 'S001', turn_number: n, prompt: `Authored prompt ${n}`, title: `Turn ${n}`, status: 'pending', browser_checks: [], ui_actions: n === 2 ? ['scrollback'] : [], expected: '545 opportunities'}));
  const scenario = {id: 'S001', number: 1, title: 'Three-turn continuity', step_ids: steps.map(s => s.id), actions: [], png: null as null | object, ui: null as null | object};
  const state = {run: {id: 'a'.repeat(32), status: 'running', steps, scenarios: [scenario]}, next_step: 0 as number | null, total_steps: 3, counts: {passed: 0, failed: 0, blocked: 0}, full_pass: false};
  let calls = 0, saves = 0, historyWrites = 0;
  const uploaded: Buffer[] = [];
  await page.addInitScript(() => localStorage.setItem('b2b-sidebar', 'collapsed'));
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const body = route.request().postData();
    if (/\/api\/(ask|sessions|sample)/.test(path) && route.request().method() === 'POST') historyWrites++;
    let data: unknown = {};
    if (path === '/api/bootstrap') data = {identity: {login_required: false, name: 'Test'}, capabilities: {acceptance_ui: true, samples: true, saved_results: true}};
    else if (path === '/api/sessions') data = {sessions: []};
    else if (path === '/api/freshness') data = {freshness: null};
    else if (path === '/api/test/suite') data = {scenario_count: 200, suite_version: '4', steps};
    else if (path.endsWith('/step')) {
      const index = JSON.parse(body!).step; calls++; steps[index].status = 'pass'; state.next_step = index === 2 ? null : index + 1; state.counts.passed++;
      data = {step: steps[index], status: state, payload: {...answer, turn_id: index + 1}};
    } else if (path.endsWith('/observation')) { scenario.ui = JSON.parse(body!); data = state; }
    else if (path.endsWith('/png')) {
      saves++; if (saves === 1) return route.fulfill({status: 503, json: {error: 'Temporary disk failure'}});
      uploaded.push(route.request().postDataBuffer()!); scenario.png = {file: '001-S001.png'}; state.run.status = 'complete'; data = state;
    } else if (path.endsWith('/review')) data = {scenario: 'S001', expected: 545, observed: 545};
    else data = state;
    await route.fulfill({json: data});
  });
  await page.goto('/'); await page.getByRole('button', {name: 'Test', exact: true}).click();
  const panel = page.getByTestId('test-panel');
  await panel.getByLabel('Display hold seconds').fill('0');
  await panel.getByRole('button', {name: 'Run tests', exact: true}).click();
  await expect(panel.getByRole('button', {name: 'Retry PNG save'})).toBeVisible({timeout: 30000});
  await expect(panel.getByTestId('user-turn')).toHaveCount(3);
  await expect(panel.getByTestId('answer-title').first()).toHaveText('Actual response title');
  await panel.getByRole('button', {name: 'Retry PNG save'}).click();
  await expect(panel.getByTestId('test-progress')).toContainText('PNGs 1/200');
  expect(calls).toBe(3); expect(historyWrites).toBe(0); expect(uploaded).toHaveLength(1);
  expect(scenario.ui).toMatchObject({status: 'pass'});
  expect(uploaded[0].subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
  const image = uploaded[0];
  await writeFile(info.outputPath('three-turn-evidence.png'), image);
  const pixels = await page.evaluate(async base64 => {
    const img = new Image(); img.src = `data:image/png;base64,${base64}`; await img.decode();
    const canvas = document.createElement('canvas'); canvas.width = img.width; canvas.height = img.height;
    const ctx = canvas.getContext('2d')!; ctx.drawImage(img, 0, 0);
    const data = ctx.getImageData(0, 200, img.width, img.height - 200).data;
    let painted = 0; for (let n = 0; n < data.length; n += 4) if (data[n] < 200 && data[n + 1] < 200 && data[n + 2] < 200) painted++;
    const tail = ctx.getImageData(0, Math.floor(img.height * .8), img.width, Math.floor(img.height * .2)).data;
    let tailPainted = 0; for (let n = 0; n < tail.length; n += 4) if (tail[n] < 200 && tail[n + 1] < 200 && tail[n + 2] < 200) tailPainted++;
    return {width: img.width, height: img.height, painted, tailPainted};
  }, image.toString('base64'));
  expect(pixels.height).toBeGreaterThan(600); expect(pixels.painted).toBeGreaterThan(2000);
  expect(pixels.tailPainted).toBeGreaterThan(500);
  await info.attach('three-turn-evidence.png', {body: image, contentType: 'image/png'});
  await panel.getByRole('button', {name: 'Copy results for review'}).click();
  await expect(panel.getByLabel('Review report text')).toContainText('545');
  await panel.getByRole('button', {name: 'Exit test'}).click();
  expect(await page.evaluate(() => localStorage.getItem('b2b-sidebar'))).toBe('collapsed');
  expect(await page.evaluate(() => localStorage.getItem('b2b-session'))).toBeNull();
});
