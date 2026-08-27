-- AguaYLuz-PR Regulatory Ingestion Framework — SQLite DDL.
-- The PR #120 design-only contract (research/regulatory/contracts.py,
-- docs/regulatory_ingestion_framework_v0_1.md) defines the records this schema
-- stores. JSONL under data/regulatory_*.jsonl remains the source of truth
-- (src/aguayluz/regulatory_db.py); this DDL builds a queryable projection from it,
-- mirroring schemas/sql/alert_system.sql. Arrays/objects are stored as JSON text.

CREATE TABLE IF NOT EXISTS regulatory_source_receipts (
  receipt_id TEXT PRIMARY KEY,
  provider TEXT NOT NULL CHECK (provider IN ('EPA','FDA','USGS','DRNA','PRASA_AAA','PREQB')),
  retrieved_at TEXT NOT NULL,
  request_locator TEXT NOT NULL,
  http_status INTEGER,
  sha256 TEXT NOT NULL,
  byte_count INTEGER NOT NULL,
  media_type TEXT NOT NULL,
  etag TEXT,
  last_modified TEXT,
  retrieval_status TEXT NOT NULL CHECK (retrieval_status IN ('success','not_modified','not_found','rate_limited','failed','rejected')),
  checkpoint_id TEXT,
  redactions TEXT,                           -- JSON array
  error_class TEXT,
  error_message TEXT
);

CREATE TABLE IF NOT EXISTS regulatory_observations (
  observation_id TEXT PRIMARY KEY,
  record_family TEXT NOT NULL CHECK (record_family IN ('entity','permit','inspection','enforcement')),
  provider TEXT NOT NULL CHECK (provider IN ('EPA','FDA','USGS','DRNA','PRASA_AAA','PREQB')),
  provider_record_id TEXT NOT NULL,
  provider_parent_record_id TEXT,
  observed_at TEXT NOT NULL,
  valid_from TEXT,
  valid_until TEXT,
  retrieved_at TEXT NOT NULL,
  source_receipt_id TEXT NOT NULL REFERENCES regulatory_source_receipts(receipt_id),
  normalization_version TEXT NOT NULL,
  evidence_tier TEXT NOT NULL CHECK (evidence_tier IN ('T1','T2','T3','T4')),
  freshness_state TEXT NOT NULL CHECK (freshness_state IN ('current','historical','stale','unknown','conflicting')),
  supersedes_observation_id TEXT REFERENCES regulatory_observations(observation_id),
  source_asserted_status TEXT,
  identifiers TEXT,                          -- JSON array of {scheme,value,issuer}
  payload TEXT NOT NULL,                     -- JSON object
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  -- schemas/regulatory_observation.schema.json: a retracted record must point at
  -- what superseded it.
  CHECK (source_asserted_status <> 'retracted' OR supersedes_observation_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_regulatory_observations_provider ON regulatory_observations(provider, record_family);
CREATE INDEX IF NOT EXISTS idx_regulatory_observations_freshness ON regulatory_observations(freshness_state);

CREATE TABLE IF NOT EXISTS regulatory_entity_links (
  candidate_id TEXT PRIMARY KEY,
  observation_id TEXT NOT NULL REFERENCES regulatory_observations(observation_id),
  candidate_asset_id TEXT NOT NULL,
  decision_state TEXT NOT NULL CHECK (decision_state IN ('proposed','needs_review','approved','rejected','superseded','conflicted')),
  match_strength TEXT CHECK (match_strength IN ('hard_identifier','strong_composite','spatial_composite','weak_lexical')),
  score REAL CHECK (score IS NULL OR (score BETWEEN 0 AND 1)),
  match_features TEXT NOT NULL,              -- JSON array
  contradictions TEXT NOT NULL,              -- JSON array
  created_at TEXT NOT NULL,
  decided_at TEXT,
  decided_by TEXT,
  decision_rationale TEXT,
  supersedes_candidate_id TEXT REFERENCES regulatory_entity_links(candidate_id),
  -- Fail-closed approval, mirroring schemas/regulatory_entity_link.schema.json: an
  -- `approved` row must carry actor, timestamp, and rationale.
  CHECK (decision_state <> 'approved' OR (decided_at IS NOT NULL AND decided_by IS NOT NULL AND decision_rationale IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_regulatory_entity_links_decision ON regulatory_entity_links(decision_state);
CREATE INDEX IF NOT EXISTS idx_regulatory_entity_links_asset ON regulatory_entity_links(candidate_asset_id);

-- One row per approved regulatory_entity_links candidate. Written only by
-- scripts/promote_regulatory_links.py, which consumes decision_state='approved'
-- rows -- it never sets that state itself. decided_at/decided_by/decision_rationale
-- are NOT NULL here (unlike the nullable columns on regulatory_entity_links) because
-- every crosswalk row's own schema requires them: a row only exists because a human
-- already approved it.
CREATE TABLE IF NOT EXISTS regulatory_entity_crosswalk (
  crosswalk_id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES regulatory_entity_links(candidate_id),
  observation_id TEXT NOT NULL REFERENCES regulatory_observations(observation_id),
  asset_id TEXT NOT NULL,
  provider TEXT NOT NULL CHECK (provider IN ('EPA','FDA','USGS','DRNA','PRASA_AAA','PREQB')),
  match_strength TEXT CHECK (match_strength IN ('hard_identifier','strong_composite','spatial_composite','weak_lexical')),
  decided_at TEXT NOT NULL,
  decided_by TEXT NOT NULL,
  decision_rationale TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_regulatory_entity_crosswalk_asset ON regulatory_entity_crosswalk(asset_id);
