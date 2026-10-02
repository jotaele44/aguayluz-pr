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

  // Cleanup is part of the gate: a successful browser run cannot leave
  // unverified fixture data behind and still report complete success.
  if (result.error) {
    throw new Error(`gui-parity teardown could not run: ${result.error.message}`);
  } else if (result.status !== 0) {
    throw new Error(
      `gui-parity teardown exited ${result.status}${
        result.signal ? ` (signal ${result.signal})` : ""
      } — the seeded fixture may still be on disk.`,
    );
  }
}
