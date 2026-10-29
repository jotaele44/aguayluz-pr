import base from './electricity-review.playwright.config.mjs'
export default { ...base, testMatch: 'electricity-registry.spec.mjs', outputDir: 'test-results/electricity-registry',
  webServer: base.webServer.map((entry, index) => index === 0 ? { ...entry, command: 'python tests/fixtures/electricity_registry_server.py' } : entry),
}
