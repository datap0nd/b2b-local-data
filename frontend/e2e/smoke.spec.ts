import {expect, test} from './fixtures';

test.describe('conversation workspace against demo backend', () => {
  test.beforeEach(async ({page}, info) => {
    await page.goto('/');
    const name = page.getByLabel('Your name');
    await expect(name.or(page.getByLabel('Your question'))).toBeVisible();
    if (await name.isVisible().catch(() => false)) { await name.fill(`E2E ${info.testId}`); await name.press('Enter'); }
    await expect(page.getByLabel('Your question')).toBeVisible();
  });

  test('a sample shows one row preview and dataset freshness in navigation', async ({page}, info) => {
    await page.getByRole('button', {name: 'Opportunity summary', exact: true}).click();
    const turn = page.getByTestId('assistant-turn').last();
    await expect(turn.getByTestId('answer-title')).toHaveText('Opportunities');
    await expect(turn.getByTestId('metrics')).toHaveCount(0);
    await expect(turn.getByTestId('freshness')).toHaveCount(0);
    await expect(turn.getByTestId('scope')).toHaveCount(1);
    await expect(turn.getByTestId('supporting-records')).toHaveCount(0);
    await expect(turn.getByTestId('result-table').locator('thead th').first()).toContainText('Opportunity');
    await expect(page.getByTestId('freshness').filter({visible: true}).first()).toBeVisible();
    await page.screenshot({path: info.outputPath('row-preview.png'), fullPage: true});
  });

  test('Shift+Enter inserts a newline and an explicit sample creates one user turn', async ({page}) => {
    const box = page.getByLabel('Your question');
    await box.fill('line one'); await box.press('Shift+Enter'); await box.pressSequentially('line two');
    await expect(box).toHaveValue('line one\nline two');
    await box.fill('');
    await page.getByRole('button', {name: 'Opportunity summary', exact: true}).click();
    await expect(page.getByTestId('user-turn')).toHaveCount(1);
  });

  test('Explore results opens one full table and Escape returns to the conversation', async ({page}, info) => {
    await page.getByRole('button', {name: 'Opportunity summary', exact: true}).click();
    await page.getByTestId('explore').last().click();
    await expect(page.getByTestId('expanded')).toBeVisible();
    await expect(page.getByLabel('Rows per page')).toBeVisible();
    await expect(page.getByTestId('result-table')).toHaveCount(1);
    await page.screenshot({path: info.outputPath('expanded-table.png'), fullPage: true});
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('expanded')).toHaveCount(0);
  });

  test('Chart and Data are exclusive and SVG download works', async ({page}, info) => {
    await page.getByRole('button', {name: 'Amount by stage group', exact: true}).click();
    const card = page.getByTestId('result-card').last();
    await expect(card.getByTestId('result-chart').locator('svg').first()).toBeVisible();
    await expect(card.getByTestId('primary-result').getByTestId('result-table')).toHaveCount(0);
    await expect(card.getByTestId('supporting-preview').getByTestId('result-table')).toBeVisible();
    await page.screenshot({path: info.outputPath('chart.png'), fullPage: true});
    await card.getByRole('button', {name: 'Data', exact: true}).click();
    await expect(card.getByTestId('result-chart')).toHaveCount(0);
    await expect(card.getByTestId('primary-result').getByTestId('result-table')).toHaveCount(1);
    await card.getByRole('button', {name: 'Chart', exact: true}).click();
    await card.getByRole('button', {name: 'Download chart'}).click();
    const download = page.waitForEvent('download');
    await page.getByRole('menuitem', {name: 'SVG vector'}).click();
    expect((await download).suggestedFilename()).toBe('chart.svg');
  });

  test('Test remains visible in expanded, collapsed and mobile navigation', async ({page, isMobile}, info) => {
    if (isMobile) await page.getByTestId('test-open-mobile').click();
    else {
      await page.getByRole('button', {name: 'Hide history'}).click();
      await expect(page.getByTestId('test-open')).toBeVisible();
      await expect(page.getByTestId('freshness')).toBeVisible();
      await page.getByTestId('test-open').click();
    }
    await expect(page.getByTestId('test-panel')).toBeVisible();
    await expect(page.getByTestId('test-start')).toHaveText('Run tests');
    await expect(page.getByTestId('test-case')).toContainText('Not started');
    await page.screenshot({path: info.outputPath('test-panel.png'), fullPage: true});
  });

  test('synthetic browser checks pass using the production result controls', async ({page, isMobile}) => {
    test.skip(isMobile, 'Geometry acceptance uses a desktop chart workspace; phone controls have separate tests.');
    await page.getByTestId('test-open').click();
    await page.getByTestId('test-synthetic').click();
    await expect(page.getByTestId('test-case')).toContainText('Synthetic checks finished', {timeout: 60_000});
    await expect(page.getByTestId('test-browser-log')).not.toContainText(': fail');
    await expect(page.getByTestId('test-browser-log')).toContainText('Synthetic check 13: pass');
  });
});
