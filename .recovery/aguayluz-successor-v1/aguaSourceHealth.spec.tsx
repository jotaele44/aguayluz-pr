import {
  buildCurrentMetricSet,
  classifyCurrentEligibility,
  validateSourceManifestation,
  type MetricObservation,
  type SourceManifestation,
} from "./aguaSourceHealth";

const src = (overrides: Partial<SourceManifestation> = {}): SourceManifestation => ({
  sourceId: "usgs-1",
  sourceSha256: "a".repeat(64),
  retrievedAt: "2026-10-01T00:00:00Z",
  rowCount: 1,
  state: "CURRENT",
  ...overrides,
});
const obs = (overrides: Partial<MetricObservation> = {}): MetricObservation => ({
  metricId: "lagoon_stage",
  sourceId: "usgs-1",
  observedAt: "2026-10-01T00:00:00Z",
  value: 1.2,
  currentEligible: true,
  ...overrides,
});

describe("AguaYLuz source health and current-condition eligibility", () => {
  it("accepts a hash-bound current manifestation", () => {
    expect(validateSourceManifestation(src())).toEqual([]);
  });

  it("represents an empty source explicitly instead of as an error", () => {
    expect(validateSourceManifestation(src({ state: "EMPTY", rowCount: 0 }))).toEqual([]);
  });

  it("rejects EMPTY with nonzero rows", () => {
    expect(validateSourceManifestation(src({ state: "EMPTY", rowCount: 3 }))).toContain("EMPTY_ROW_COUNT_MUST_BE_ZERO");
  });

  it("requires hashes for current, stale and empty manifestations", () => {
    expect(validateSourceManifestation(src({ sourceSha256: null }))).toContain("SOURCE_HASH_MISSING");
  });

  it("does not promote stale source observations into current condition", () => {
    expect(classifyCurrentEligibility(src({ state: "STALE" }), obs())).toBe("NOT_ELIGIBLE");
  });

  it("does not promote historical-only observations into current condition", () => {
    expect(classifyCurrentEligibility(src(), obs({ currentEligible: false }))).toBe("HISTORICAL_ONLY");
  });

  it("does not substitute an empty source with another historical observation", () => {
    const result = buildCurrentMetricSet(
      [src({ state: "EMPTY", rowCount: 0 })],
      [obs({ currentEligible: false })],
      ["lagoon_stage"]
    );
    expect(result.currentObservations.length).toBe(0);
    expect(result.missingRequiredMetrics).toContain("lagoon_stage");
  });

  it("preserves missing required metrics explicitly", () => {
    const result = buildCurrentMetricSet([src()], [obs()], ["lagoon_stage", "groundwater_level"]);
    expect(result.currentConditionComplete).toBeFalse();
    expect(result.missingRequiredMetrics).toEqual(["groundwater_level"]);
  });

  it("closes current condition only when every required metric has current evidence", () => {
    const result = buildCurrentMetricSet(
      [src(), src({ sourceId: "usgs-2", sourceSha256: "b".repeat(64) })],
      [obs(), obs({ metricId: "groundwater_level", sourceId: "usgs-2", value: 2.3 })],
      ["lagoon_stage", "groundwater_level"]
    );
    expect(result.currentConditionComplete).toBeTrue();
  });
});
