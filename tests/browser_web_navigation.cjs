// Optional browser smoke test: start an HTTP server for web/, then run with Playwright installed.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const base = process.argv[2] || 'http://127.0.0.1:8765';
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.goto(base);
    await page.waitForFunction(() => document.querySelector('#catalog-count').textContent.includes('수록'));
    assert.equal(await page.locator('[data-page]').count(), 6);
    for (const name of ['notice', 'quests', 'maps', 'catalog', 'maintenance', 'links']) {
      await page.locator(`[data-page="${name}"]`).click();
      await page.waitForFunction(n => document.querySelector(`[data-page="${n}"]`).getAttribute('aria-current') === 'page', name);
      assert.equal(await page.locator(`[data-view="${name}"]`).first().isVisible(), true);
      assert.equal(await page.locator('[data-page][aria-current=page]').count(), 1);
    }
    assert.equal(await page.locator('.map-link').count(), 37);
    await page.locator('[data-page="maintenance"]').click();
    await page.waitForFunction(() => !document.querySelector('[data-view=maintenance]').hidden);
    assert((await page.locator('[data-view=maintenance]').innerText()).includes('등록된 다음 점검 일정이 없습니다.'));
    await page.reload();
    await page.waitForFunction(() => !document.querySelector('[data-view=maintenance]').hidden);
    await page.locator('[data-page="quests"]').click();
    await page.locator('#query').fill('아호작전');
    await page.locator('#search-form').evaluate(form => form.requestSubmit());
    await page.waitForFunction(() => document.querySelector('#detail-title').textContent === '아호작전');
    await page.locator('[data-page="notice"]').click();
    await page.locator('[data-page="quests"]').click();
    await page.waitForFunction(() => !document.querySelector('[data-view=quests]').hidden);
    assert.equal(await page.locator('#query').inputValue(), '아호작전');
    assert.equal(await page.locator('#detail-title').innerText(), '아호작전');
    await page.goto(`${base}/#quest=B179`);
    await page.waitForFunction(() => document.querySelector('#detail .eyebrow')?.textContent.includes('B179'));
    assert.equal(await page.locator('[data-page=quests]').getAttribute('aria-current'), 'page');
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.locator('#site-menu').isVisible(), false);
    await page.locator('#menu-toggle').click();
    assert.equal(await page.locator('#menu-toggle').getAttribute('aria-expanded'), 'true');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#site-menu').isVisible(), false);
    await page.locator('#menu-toggle').click();
    await page.locator('[data-page=maps]').click();
    await page.waitForFunction(() => !document.querySelector('[data-view=maps]').hidden);
    assert.equal(await page.locator('#site-menu').isVisible(), false);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: '/tmp/kgbot-menu-mobile.png', fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator('[data-page=quests]').click();
    await page.waitForFunction(() => !document.querySelector('[data-view=quests]').hidden);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: '/tmp/kgbot-menu-desktop.png', fullPage: true });
    assert.deepEqual(errors, []);
    console.log('PASS: six menus, 37 map links, page reload, search state, quest deep link, mobile toggle/Escape, no overflow or JS errors');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
