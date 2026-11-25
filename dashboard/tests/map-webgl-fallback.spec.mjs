import { expect, test } from "@playwright/test";

// /map draws with MapLibre, which needs WebGL2. Where the browser has none (GPU
// blocklisted or disabled, some VMs and remote desktops, headless Firefox) the
// map constructor throws. The page must say why and the rest of the app must
// keep working, instead of /map rendering nothing.

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function getContext(type, ...rest) {
      if (/webgl/i.test(String(type))) return null;
      return original.call(this, type, ...rest);
    };
  });
});

test("without WebGL2, /map explains the failure and navigation keeps working", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("link", { name: "Map", exact: true }).first().click();
  await expect(page).toHaveURL(/\/map$/);

  await expect(page.getByRole("status").filter({ hasText: "Map unavailable" })).toBeVisible();
  await expect(page.locator(".maplibregl-canvas")).toHaveCount(0);

  await page.getByRole("link", { name: "Assets" }).first().click();
  await expect(page).toHaveURL(/\/assets$/);
  await expect(page.getByRole("main")).not.toBeEmpty();

  expect(pageErrors).toEqual([]);
});
