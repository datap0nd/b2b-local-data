import {chromium, test as base, type Browser} from '@playwright/test';

/** Playwright's own browsers are used by default. On machines where they cannot launch, set B2B_E2E_CDP to the
 *  DevTools URL of an already-running Chrome (for example http://127.0.0.1:9333) and the tests attach to it. */
export const test = base.extend<object, {browser: Browser}>({
  browser: [async ({}, use) => {
    const endpoint = process.env.B2B_E2E_CDP;
    if (!endpoint) { const browser = await chromium.launch(); await use(browser); await browser.close(); return; }
    const browser = await chromium.connectOverCDP(endpoint);
    await use(browser);
    await browser.close();
  }, {scope: 'worker'}],
});

export {expect} from '@playwright/test';
