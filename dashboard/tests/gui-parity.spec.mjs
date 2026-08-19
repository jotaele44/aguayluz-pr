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

// ── Severity rendering on /review ────────────────────────────────────────────
//
// Everything above is generated from the manifest and asserts reachability: the
// route resolves, #root renders, nothing threw. It never looks at what the page
// says. That gap is why the review-queue severity indicator could be dead for
// every record in the dataset while this suite stayed green — block and warn
// both fell through to the same slate class, and no gate anywhere noticed.
//
// This block is the first per-capability assertion in the file. It is stubbed
// rather than seeded on purpose: a working checkout's export is thousands of
// records that are all `warn`, so a data-dependent assertion would pass in CI
// and fail on a developer's machine. Stubbing makes it identical in both.
//
// The complementary half is server/ingestion/seed_demo.py, which gives the real
// backend records to serve so the reachability tests above stop passing over an
// empty page. Between them: the seed proves the stack, this proves the rendering.
//
// Note this exercises ReviewPage's own inline markup — /review does not mount
// ReviewRecordCard, which has its own component test. They are two independent
// call sites of severityTone().

const REVIEW_STUB = {
  total: 2,
  offset: 0,
  items: [
    {
      record_ref: "STUB-BLOCK-0001",
      reason: "stubbed blocking record",
      severity: "block",
      evidence_tier: "T1",
    },
    {
      record_ref: "STUB-WARN-0001",
      reason: "stubbed warning record",
      severity: "warn",
      evidence_tier: "T2",
    },
  ],
};

test("review queue serves real records to the page, unstubbed", async ({ page }) => {
  // Codex was right that the stubbed test below cannot prove the backend reaches
  // the GUI — page.route replaces the response, and the generated reachability
  // test only checks that #root rendered and nothing threw. So an empty 200 from
  // /review-queue would leave both green while /review showed nothing.
  //
  // This one deliberately does NOT intercept. It asserts the page displays at
  // least one record that came off the wire, which is what the seed exists to
  // guarantee in CI. It is written against record *count*, not against SEED-*
  // ids, because a developer's checkout has a real export and the seed no-ops
  // there — asserting on fixture ids would pass in CI and fail locally.
  const payloads = [];
  page.on("response", async (response) => {
    if (!response.url().includes("/review-queue")) return;
    try {
      payloads.push(await response.json());
    } catch {
      // Non-JSON or already-consumed body; the assertions below still apply.
    }
  });

  await page.goto("/review", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(750);

  const served = payloads.find((p) => Array.isArray(p?.items));
  expect(served, "GET /review-queue returned nothing usable").toBeTruthy();
  expect(
    served.items.length,
    "the backend served an empty review queue — the seed did not run, or it wrote nothing",
  ).toBeGreaterThan(0);

  // And the records reached the DOM, not just the network tab. The first record
  // is on page one, since ReviewPage renders backend order sliced to PAGE_SIZE.
  await expect(page.getByText(served.items[0].record_ref)).toBeVisible();
});

test("review queue renders block and warn with different severity tones", async ({ page }) => {
  // The page is served from :5173 and the API from :8000, so a fulfilled
  // response without CORS headers is blocked by the browser — and getJSON's bare
  // `catch` swallows that into an empty list, which would surface as a
  // confusing "no records" failure rather than a network one.
  await page.route("**/review-queue**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "access-control-allow-origin": "*" },
      body: JSON.stringify(REVIEW_STUB),
    });
  });

  await page.goto("/review", { waitUntil: "domcontentloaded" });

  const blockRow = page.getByText("STUB-BLOCK-0001");
  await expect(blockRow, "stubbed records did not reach the page").toBeVisible();

  // The severity label carries the tone class; read it rather than asserting a
  // class is merely present, since the element always has one.
  const toneOf = async (severity) =>
    page.locator(`span.uppercase`, { hasText: new RegExp(`^${severity}$`) }).first().getAttribute("class");

  const blockTone = await toneOf("block");
  const warnTone = await toneOf("warn");

  expect(blockTone, "no severity label rendered for block").toBeTruthy();
  expect(warnTone, "no severity label rendered for warn").toBeTruthy();

  // The assertion that matters: these must not be the same class string. When
  // SEVERITY lacked block/warn/info both were `text-slate-400`.
  expect(blockTone).not.toBe(warnTone);

  // And neither may be the fallback — equal-but-both-wrong would pass the check
  // above only if the two happened to differ, so pin the fallback out explicitly.
  expect(blockTone).not.toContain("text-slate-400");
});
