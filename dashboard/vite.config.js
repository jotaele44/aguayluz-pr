import react from '@vitejs/plugin-react'
import { build, defineConfig } from 'vite'
import { viteSingleFile } from 'vite-plugin-singlefile'
import path from 'node:path'

// Auth-stripped, local-only scaffold.
// Domain data comes from the repo's FastAPI at VITE_API_BASE (default :8000).
// VITE_OFFLINE=1 produces a single self-contained index.html (data baked in) that
// opens directly via file:// — see `npm run build:export`.
// https://vite.dev/config/
const offline = process.env.VITE_OFFLINE === '1'

// maplibre-gl 6 starts its web worker from a separate script (AssetMap passes
// it the `?worker&url` chunk), and a page opened from file:// may not start a
// worker from a file. For the single-file export, bundle the worker into the
// page and hand maplibre a blob: URL instead — how maplibre-gl 4 shipped it.
// A file:// page can only run that blob as a classic worker, and maplibre
// starts a classic worker for URLs ending in `.cjs`; the `#…cjs` fragment
// selects that path and is ignored when the blob is loaded.
const MAPLIBRE_WORKER = 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'

function inlineMaplibreWorker() {
  // Kept free of the `?worker` query, or vite:worker claims the module too.
  const resolved = '\0inline-maplibre-worker'
  return {
    name: 'inline-maplibre-worker',
    enforce: 'pre',
    resolveId(source) {
      if (source === MAPLIBRE_WORKER) return resolved
    },
    async load(id) {
      if (id !== resolved) return
      const result = await build({
        configFile: false,
        logLevel: 'error',
        build: {
          write: false,
          lib: {
            entry: path.resolve(__dirname, 'node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs'),
            formats: ['iife'],
            name: 'maplibreWorker',
          },
        },
      })
      const [{ output }] = Array.isArray(result) ? result : [result]
      const code = JSON.stringify(output[0].code)
      return `export default URL.createObjectURL(new Blob([${code}], { type: 'text/javascript' })) + '#maplibre-gl-worker.cjs'`
    },
  }
}

export default defineConfig({
  logLevel: 'error',
  base: offline ? './' : '/',
  plugins: [react(), ...(offline ? [inlineMaplibreWorker(), viteSingleFile()] : [])],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  build: offline ? { outDir: 'export-standalone' } : {},
  server: {
    port: 5173, // must match the backend CORS allow_origins
  },
})
