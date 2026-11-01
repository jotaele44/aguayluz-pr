import base from './electricity-review.playwright.config.mjs'
export default { ...base, testMatch: 'electricity-jobs.spec.mjs', outputDir: 'test-results/electricity-jobs' }
