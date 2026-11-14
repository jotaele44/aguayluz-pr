// Global teardown must propagate fixture cleanup failures to Playwright.
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

export default function globalTeardown() {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const result = spawnSync("python", [path.join(here, "gui_parity_teardown.py")], {
    stdio: "inherit",
    env: process.env,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(
      "GUI parity teardown failed or refused cleanup (exit=" +
      result.status + ", signal=" + (result.signal || "none") + ")"
    );
  }
}
