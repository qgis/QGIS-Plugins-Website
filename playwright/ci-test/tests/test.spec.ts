import { test, expect } from '@playwright/test';

test.use({
  storageState: 'auth.json'
});

test('test', async ({ page }) => {
  await page.goto('http://0.0.0.0:62202/');
  await expect(page.locator('body')).toContainText('Click here to access plugins ready to be used. These plugins can also be installed directly from the QGIS Plugin Manager within the QGIS application.');
  await expect(page.getByRole('link', { name: 'here', exact: true })).toBeVisible();
  await expect(page.locator('body')).toContainText('Notes for plugin users');
  await expect(page.locator('body')).toContainText('Resources for plugin authors');
});