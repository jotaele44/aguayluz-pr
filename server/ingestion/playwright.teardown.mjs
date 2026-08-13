// Playwright globalTeardown shim: runs the Python teardown that removes the
// review-queue fixture seed_demo.py created. Kept as a thin wrapper so the
// deletion rule (and its marker-file guard) lives in one place, next to the
// script that writes the fixture, rather than being restated in JavaScript.
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

export default function globalTeardown() {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const result = spawnSync("python", [path.join(here, "gui_parity_teardown.py")], {
    stdio: "inherit",
  });
  // Never fail the run on teardown — the tests have already reported.
  if (result.error) {
    console.warn(`gui-parity teardown could not run: ${result.error.message}`);
  }
}
