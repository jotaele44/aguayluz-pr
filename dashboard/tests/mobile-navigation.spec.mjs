import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

// gui-parity.spec.mjs runs at desktop width, where the navigation panel is always
// expanded. Below 768px the same routes are reached only through the drawer (open
// button -> group tab -> row or sub-link), so this spec walks that path on a phone.

function findRepositoryRoot(start) {
  let current = start;
  while (current !== path.dirname(current)) {
    if (fs.existsSync(path.join(current, ".federation", "gui-capabilities.json"))) {
      return current;
    }
    current = path.dirname(current);
  }
  throw new Error("Could not locate .federation/gui-capabilities.json");
}

const repositoryRoot = findRepositoryRoot(path.dirname(fileURLToPath(import.meta.url)));
const manifest = JSON.parse(
  fs.readFileSync(path.join(repositoryRoot, ".federation", "gui-capabilities.json"), "utf8"),
);
const manifestRoutes = [
  ...new Set(
    manifest.capabilities
      .filter((c) => c.status === "active" && c.classification !== "internal")
      .flatMap((c) => c.frontend?.e2e_routes ?? []),
  ),
].sort();

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

const drawer = (page) => page.getByRole("complementary", { name: "Navigation" });
const openDrawer = async (page) => {
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(drawer(page)).toBeVisible();
};

test("every manifest route is reachable from a mobile drawer tab", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(drawer(page)).toHaveCount(0);
  await openDrawer(page);

  const tabs = drawer(page).getByRole("tab");
  const reachable = new Set();
  for (let i = 0; i < (await tabs.count()); i += 1) {
    await tabs.nth(i).click();
    await expect(tabs.nth(i)).toHaveAttribute("aria-selected", "true");
    for (const href of await drawer(page).locator("nav a[href]").evaluateAll(
      (links) => links.map((a) => a.getAttribute("href")),
    )) {
      reachable.add(href);
    }
  }

  expect(manifestRoutes.length).toBeGreaterThan(0);
  expect(manifestRoutes.filter((route) => !reachable.has(route))).toEqual([]);
});

test("drawer tab, sub-link, close and reopen behave on a phone", async ({ page }) => {
  const runtimeFailures = [];
  page.on("pageerror", (error) => runtimeFailures.push(`page error: ${error.message}`));

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await openDrawer(page);
  await expect(drawer(page).getByRole("tab", { name: "Monitor" })).toHaveAttribute("aria-selected", "true");

  // Switch group, then follow a sub-link: the drawer closes on navigation.
  await drawer(page).getByRole("tab", { name: "Data" }).click();
  await drawer(page).getByRole("link", { name: /NWS Hydromet/ }).click();
  await expect(page).toHaveURL(/\/hydromet\/?$/);
  await expect(drawer(page)).toHaveCount(0);

  // Reopening starts on the tab that holds the current page.
  await openDrawer(page);
  await expect(drawer(page).getByRole("tab", { name: "Data" })).toHaveAttribute("aria-selected", "true");

  await drawer(page).getByRole("button", { name: "Close navigation" }).click();
  await expect(drawer(page)).toHaveCount(0);

  await openDrawer(page);
  await page.keyboard.press("Escape");
  await expect(drawer(page)).toHaveCount(0);

  expect(runtimeFailures, runtimeFailures.join("\n")).toEqual([]);
});
