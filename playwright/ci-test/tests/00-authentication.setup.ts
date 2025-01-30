import { test, expect } from '@playwright/test';

let url = '/';
const username = 'admin';
const password = 'admin';
const authFile = 'auth.json';

test('authentication-setup', async ({ page }) => {
  await page.goto(url);

  const initialURL = page.url();

  await expect(page.locator('h1')).toContainText('QGIS plugins web portal');

  await expect(page.locator('body')).toContainText('QGIS plugins add additional functionality to the QGIS application.');

  await expect(page.getByRole('link', { name: ' Login' })).toBeVisible();

  await page.getByRole('link', { name: ' Login' }).click();

  await page.waitForURL('**/accounts/login/');
  
  await expect(page.locator('h3')).toContainText('Login using your OSGEO id.');
  
  await expect(page.locator('body')).toContainText('Please note that you do not need a login to download a plugin.');
  
  await expect(page.locator('body')).toContainText('You can create a new OSGEO id on OSGEO web portal.');

  await expect(page.getByRole('link', { name: 'OSGEO web portal.' })).toBeVisible();

  await page.getByPlaceholder('Username').click();

  await page.getByPlaceholder('Username').fill(username);

  await page.getByPlaceholder('Password').click();

  await page.getByPlaceholder('Password').fill(password);

  await expect(page.getByRole('button', { name: 'login' })).toBeVisible();

  await page.getByRole('button', { name: 'login' }).click();

  const finalURL = page.url();

  await expect(initialURL).toBe(finalURL);

  await expect(page.getByRole('link', { name: ' Logout' })).toBeVisible();

  await page.context().storageState({path: authFile});

});