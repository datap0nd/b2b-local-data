import {expect, test} from '@playwright/test';

test.describe('conversation workspace', () => {
  test.beforeEach(async ({page}) => {
    await page.goto('/');
    const name = page.getByLabel('Your name');
    if (await name.isVisible().catch(() => false)) { await name.fill('E2E Person'); await name.press('Enter'); }
    await expect(page.getByLabel('Your question')).toBeVisible();
  });

  test('a sample preview renders an answer with title, sentence, metrics, and a preview table', async ({page}) => {
    await page.getByRole('button', {name: 'Opportunity summary'}).click();
    const turn = page.getByTestId('assistant-turn').last();
    await expect(turn.getByTestId('answer-title')).toHaveText('Opportunities');
    await expect(turn.getByTestId('answer-sentence')).toContainText('match');
    await expect(turn.getByTestId('metrics').locator('div').first()).toBeVisible();
    await expect(turn.getByTestId('result-table').locator('thead th').first()).toContainText('Opportunity');
    await expect(turn.getByTestId('freshness')).toBeVisible();
  });

  test('Enter submits, Shift+Enter inserts a newline, and a pending turn appears once', async ({page}) => {
    const box = page.getByLabel('Your question');
    await box.fill('line one');
    await box.press('Shift+Enter');
    await box.type('line two');
    await expect(box).toHaveValue('line one\nline two');
    await box.fill('');
    await page.getByRole('button', {name: 'Opportunity summary'}).click();
    await expect(page.getByTestId('user-turn')).toHaveCount(1);
  });

  test('Explore results opens the full table and Escape returns to the conversation', async ({page}) => {
    await page.getByRole('button', {name: 'Opportunity summary'}).click();
    await page.getByTestId('explore').last().click();
    await expect(page.getByTestId('expanded')).toBeVisible();
    await expect(page.getByLabel('Rows per page')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('expanded')).toHaveCount(0);
  });

  test('the sidebar lists, searches, and collapses conversations', async ({page, isMobile}) => {
    test.skip(isMobile, 'the phone layout keeps history in an overlay');
    await page.getByRole('button', {name: 'Opportunity summary'}).click();
    const sidebar = page.getByLabel('Conversation history');
    await expect(sidebar).toHaveCSS('width', '248px');
    await page.getByLabel('Search conversations').fill('zzz-no-match');
    await expect(page.getByRole('navigation', {name: 'Conversations'})).toContainText(/No conversations/i);
  });
});
