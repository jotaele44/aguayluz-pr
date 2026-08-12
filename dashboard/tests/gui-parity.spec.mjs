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
const backendUrl = "http://127.0.0.1:8000";
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
  test(`GUI route ${route} is rendered and discoverable`, async ({ page, request }) => {
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

    if (route === "/cave-karst") {
      await expect(page.getByRole("heading", { name: "Cave & Karst Monitor" })).toBeVisible();
      await expect(page.getByRole("note", { name: "Registry scope limitation" })).toContainText(/pilot/i);
      await expect(page.locator("body")).toContainText(/not a statewide cave census/i);
      await expect(page.locator("body")).toContainText(/precise coordinates are withheld/i);

      const summaryResponse = await request.get(`${backendUrl}/cave-karst/summary`);
      expect(summaryResponse.status()).toBe(200);
      const summary = await summaryResponse.json();
      expect(summary.scope.statewide_complete).toBe(false);
      expect(summary.scope.registry_scope).toEqual({ pilot: 4 });
      expect(summary.validation.ok).toBe(true);

      const assetsResponse = await request.get(`${backendUrl}/cave-karst/assets`);
      expect(assetsResponse.status()).toBe(200);
      const assets = await assetsResponse.json();
      expect(assets.total).toBe(4);
      expect(
        assets.items.every(
          (asset) => asset.coordinates_redacted && asset.lat === null && asset.lon === null,
        ),
      ).toBe(true);

      expect((await request.post(`${backendUrl}/cave-karst/summary`)).status()).toBe(405);
      expect(
        (
          await request.patch(
            `${backendUrl}/cave-karst/assets/AYL_KARST_CAMUY_PARK`,
            { data: { status: "open" } },
          )
        ).status(),
      ).toBe(405);
    }

    expect(runtimeFailures, runtimeFailures.join("\n")).toEqual([]);
  });
}

// ── monitoring vectors ────────────────────────────────────────────────────────
//
// The manifest-driven tests above only prove a route loads. They cannot notice that a
// newly registered reading vector is unselectable, or that selecting it throws — the
// dropdown defaults to `reservoir_elevation` and never touches the rest.
//
// Known limit, stated rather than papered over: the webServer above boots
// `server.backend.main:app` (the legacy app, whose /readings returns a bare array), and
// every data/*_readings.jsonl file is gitignored, so CI serves empty series. These tests
// therefore prove reachability, selectability and no-crash — not that data renders.
// Data correctness lives in tests/test_backend_readings_api.py against the canonical app.
const MONITORING_SERIES_LABELS = [
  "Groundwater depth (discrete)",
  "Annual peak streamflow",
  "Annual peak stage",
];

for (const label of MONITORING_SERIES_LABELS) {
  test(`monitoring series "${label}" is selectable and renders`, async ({ page }) => {
    const runtimeFailures = [];
    page.on("pageerror", (error) => { runtimeFailures.push(`page error: ${error.message}`); });
    page.on("response", (response) => {
      if (response.status() >= 500) { runtimeFailures.push(`${response.status()} ${response.url()}`); }
    });

    await page.goto("/monitoring", { waitUntil: "domcontentloaded" });
    const picker = page.getByLabel("Monitoring series");
    await expect(picker).toBeVisible();
    await picker.click();

    const option = page.getByRole("option", { name: label });
    await expect(option, `"${label}" is not offered in the monitoring series picker`).toBeVisible();
    await option.click();

    // The series header echoes the label once the selection has taken effect.
    await expect(page.locator("#root")).toContainText(label);
    await page.waitForTimeout(500);
    expect(runtimeFailures, runtimeFailures.join("\n")).toEqual([]);
  });
}
