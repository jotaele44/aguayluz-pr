import path from 'node:path';
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Modelled on centinelas-pr/frontend/vitest.config.js. Deliberately a local
// file rather than a rendered federation template: templating it would make
// every JSX frontend drifted until all five had the harness, which would block
// landing tests one repo at a time.
//
// Deliberately separate from vite.config.js rather than merging it: the build
// config carries offline-export plumbing (vite-plugin-singlefile) and a dev
// server port pinned to the backend's CORS allowlist, none of which a test run
// needs or should depend on.
//
// jsdom rather than node even for the pure-logic tests: src/lib/utils.js
// evaluates `window.self !== window.top` at module scope, and format.js imports
// cn() from it, so a node environment throws at import time.
//
// Tests are co-located with the code they cover (src/**/*.test.{js,jsx}) rather
// than living in a tests/ directory — that directory holds the Playwright
// gui-parity spec, which has its own config and must not be collected here.
//
// `globals: true` is set for parity with the sibling frontends, but the tests
// still import describe/it/expect from 'vitest' explicitly. In centinelas and
// skywatcher that is load-bearing — their lint gate reports the bare globals as
// undefined. Here it is not: this repo's eslint config supplies its own `rules`
// block, which replaces the recommended set, so no-undef never runs. Kept
// explicit anyway so the three suites read the same and so the files stay
// runnable if that config is ever tightened.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.js',
    css: false,
    include: ['src/**/*.test.{js,jsx}'],
  },
});
