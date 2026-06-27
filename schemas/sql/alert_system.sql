-- AguaYLuz-PR Alert System — SQLite/PostGIS-ready DDL (harmonized v0.2).
-- Portable SQLite for analysis; the geometry-friendly column layout maps onto
-- PostGIS for the production dependency graph (add a geometry(Point,4326) column
-- and a GIST index on the alert_events / dependency nodes in PostGIS).
--
-- Harmonized to repo idioms: confidence 0-100, evidence_tier T1-T4, AYL_ ids,
-- review_status. The workbook's operational fields (severity 0-5, gap_status,
-- covert_flags) are preserved. Arrays are stored as JSON text in SQLite.

CREATE TABLE IF NOT EXISTS alert_modules (
  module_id TEXT PRIMARY KEY,
  module_name TEXT NOT NULL,
  sector TEXT NOT NULL,
  activation_status TEXT NOT NULL CHECK (activation_status IN ('active','dormant')),
  priority TEXT NOT NULL CHECK (priority IN ('critical','high','medium','low')),
  hydro_dependency_relevance TEXT NOT NULL CHECK (hydro_dependency_relevance IN ('direct','indirect','evidence')),
  default_severity_floor INTEGER NOT NULL CHECK (default_severity_floor BETWEEN 0 AND 5),
  primary_sources TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS alert_events (
  alert_id TEXT PRIMARY KEY,
  module_id TEXT NOT NULL REFERENCES alert_modules(module_id),
  event_type TEXT NOT NULL CHECK (event_type IN ('maintenance','outage','failure','quality','hazard','inspection','unknown')),
  status TEXT NOT NULL CHECK (status IN ('draft','validated','active','closed','rejected')),
  source_title TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  source_hash TEXT,
  published_at TEXT,
  start_at TEXT NOT NULL,
  end_at TEXT,
  estimated_duration_hr REAL,
  asset_name TEXT NOT NULL,
  asset_id TEXT,
  operator TEXT,
  municipalities TEXT NOT NULL,             -- JSON array
  sectors_impacted TEXT,                     -- JSON array
  latitude REAL,
  longitude REAL,
  coord_confidence TEXT NOT NULL CHECK (coord_confidence IN ('exact','approximate','unknown')),
  severity INTEGER NOT NULL CHECK (severity BETWEEN 0 AND 5),
  confidence INTEGER NOT NULL CHECK (confidence BETWEEN 0 AND 100),
  ilap_score INTEGER CHECK (ilap_score BETWEEN 0 AND 5),
  covert_flags TEXT,                         -- JSON array
  gap_status TEXT NOT NULL CHECK (gap_status IN ('none','minor','major','blocking')),
  review_status TEXT NOT NULL CHECK (review_status IN ('accepted','needs_review','rejected','blocked')),
  evidence_tier TEXT NOT NULL CHECK (evidence_tier IN ('T1','T2','T3','T4')),
  linked_asset_ids TEXT,                     -- JSON array
  validation_notes TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  CHECK ((latitude IS NULL) = (longitude IS NULL))   -- VAL-005: both or neither
);

CREATE INDEX IF NOT EXISTS idx_alert_events_module ON alert_events(module_id);
CREATE INDEX IF NOT EXISTS idx_alert_events_status ON alert_events(status, review_status);

CREATE TABLE IF NOT EXISTS alert_dependency_edges (
  edge_id TEXT PRIMARY KEY,
  from_node_type TEXT NOT NULL,
  from_node_id TEXT,
  to_node_type TEXT NOT NULL,
  to_node_id TEXT,
  dependency_type TEXT NOT NULL,
  confidence INTEGER NOT NULL CHECK (confidence BETWEEN 0 AND 100),
  evidence_required INTEGER NOT NULL DEFAULT 1,   -- boolean 0/1
  notes TEXT
);

CREATE TABLE IF NOT EXISTS alert_gaps (
  gap_id TEXT PRIMARY KEY,
  alert_id TEXT REFERENCES alert_events(alert_id),
  module_id TEXT NOT NULL,
  gap_type TEXT NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('minor','major','blocking')),
  blocking INTEGER NOT NULL DEFAULT 0,            -- boolean 0/1
  description TEXT NOT NULL,
  next_action TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed'))
);

-- Evidence layer: every alert must trace to a preserved source object.
CREATE TABLE IF NOT EXISTS alert_source_evidence (
  evidence_id TEXT PRIMARY KEY,
  alert_id TEXT REFERENCES alert_events(alert_id),
  source_type TEXT,                          -- image|pdf|html|text|csv
  source_ref TEXT NOT NULL,
  source_hash TEXT,
  captured_at TEXT DEFAULT CURRENT_TIMESTAMP,
  notes TEXT
);
