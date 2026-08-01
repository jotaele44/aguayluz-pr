import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

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

const here = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = findRepositoryRoot(here);
const manifest = JSON.parse(
  fs.readFileSync(
    path.join(repositoryRoot, ".federation", "gui-capabilities.json"),
    "utf8",
  ),
);

const routes = [
  ...new Set(
    manifest.capabilities
      .filter(
        (capability) =>
          capability.status === "active" && capability.classification !== "internal",
      )
      .flatMap((capability) => capability.frontend?.e2e_routes ?? []),
  ),
].sort();

test("manifest exposes at least one active GUI route", () => {
  expect(routes.length).toBeGreaterThan(0);
});

for (const route of routes) {
  test(`GUI route ${route} is rendered and discoverable`, async ({ page }) => {
    const runtimeFailures = [];
    page.on("pageerror", (error) => {
      runtimeFailures.push(`page error: ${error.message}`);
    });
    page.on("response", (response) => {
      if (response.status() >= 500) {
        runtimeFailures.push(`${response.status()} ${response.url()}`);
      }
    });

    if (route !== "/") {
      await page.goto("/", { waitUntil: "domcontentloaded" });
      const link = page.locator(`a[href="${route}"]`).first();
      await expect(
        link,
        `No clickable GUI navigation reaches ${route}`,
      ).toBeVisible();
      await link.click();
      await expect(page).toHaveURL(new RegExp(`${route.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/?$`));
    } else {
      await page.goto(route, { waitUntil: "domcontentloaded" });
    }

    await expect(page.locator("#root")).toBeVisible();
    await page.waitForTimeout(750);
    await expect(page.locator("body")).not.toContainText(
      /(?:something broke while rendering|page\s+not\s+found|route\s+not\s+found|404\s*—?\s*not\s+found)/i,
    );
    expect(runtimeFailures, runtimeFailures.join("\n")).toEqual([]);
  });
}

test("assets route exposes the impact switchboard safety boundary", async ({ page }) => {
  const responsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/assets" && url.searchParams.get("impact") === "true";
  });
  await page.goto("/assets", { waitUntil: "domcontentloaded" });
  const response = await responsePromise;
  expect(response.ok()).toBe(true);
  expect(response.headers()["content-type"]).toContain("application/json");

  // The real corpus response is several megabytes. Reading it again through
  // Chromium's inspector can evict the body after the application has already
  // consumed it. Assert the live response and the fields rendered from that
  // response instead of duplicating the body in the inspector cache.
  await expect(page.getByText("Asset Impact Switchboard", { exact: true })).toBeVisible();
  await expect(page.getByText("Canonical assets", { exact: true })).toBeVisible();
  await expect(page.getByText(/baseline\s+AYLAG_[a-f0-9]{24}/i)).toBeVisible();
  await expect(page.getByText(/no automatic control actions/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Switchboard" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Inventory" })).toBeVisible();
});
