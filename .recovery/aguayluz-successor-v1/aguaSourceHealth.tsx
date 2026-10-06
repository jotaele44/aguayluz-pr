export type SourceState = "CURRENT" | "STALE" | "EMPTY" | "ERROR" | "UNAVAILABLE";
export type CurrentEligibility = "ELIGIBLE" | "HISTORICAL_ONLY" | "NOT_ELIGIBLE";

export interface SourceManifestation {
  sourceId: string;
  sourceSha256: string | null;
  retrievedAt: string | null;
  rowCount: number | null;
  state: SourceState;
}

export interface MetricObservation {
  metricId: string;
  sourceId: string;
  observedAt: string;
  value: number | null;
  currentEligible: boolean;
}

export function validateSourceManifestation(s: SourceManifestation): string[] {
  const reasons: string[] = [];
  if (!s.sourceId) reasons.push("SOURCE_ID_MISSING");
  if (s.state === "CURRENT" || s.state === "STALE" || s.state === "EMPTY") {
    if (!s.sourceSha256 || !/^[a-f0-9]{64}$/i.test(s.sourceSha256)) reasons.push("SOURCE_HASH_MISSING");
    if (!s.retrievedAt) reasons.push("RETRIEVED_AT_MISSING");
  }
  if (s.state === "EMPTY" && s.rowCount !== 0) reasons.push("EMPTY_ROW_COUNT_MUST_BE_ZERO");
  if ((s.state === "CURRENT" || s.state === "STALE") && (s.rowCount === null || s.rowCount < 0)) reasons.push("ROW_COUNT_MISSING");
  return reasons;
}

export function classifyCurrentEligibility(source: SourceManifestation, observation: MetricObservation): CurrentEligibility {
  if (!observation.currentEligible) return "HISTORICAL_ONLY";
  if (source.state !== "CURRENT") return "NOT_ELIGIBLE";
  if (validateSourceManifestation(source).length) return "NOT_ELIGIBLE";
  return "ELIGIBLE";
}

export function buildCurrentMetricSet(
  sources: SourceManifestation[],
  observations: MetricObservation[],
  requiredMetricIds: string[]
) {
  const bySource = new Map(sources.map(s => [s.sourceId, s]));
  const current = new Map<string, MetricObservation>();
  for (const obs of observations) {
    const source = bySource.get(obs.sourceId);
    if (!source) continue;
    if (classifyCurrentEligibility(source, obs) === "ELIGIBLE") current.set(obs.metricId, obs);
  }
  const missingRequiredMetrics = requiredMetricIds.filter(id => !current.has(id));
  return {
    currentObservations: [...current.values()],
    missingRequiredMetrics,
    currentConditionComplete: missingRequiredMetrics.length === 0,
  };
}
