CREATE SCHEMA IF NOT EXISTS evidence_fia_pr;
CREATE SCHEMA IF NOT EXISTS aguayluz_ecology;

CREATE TABLE IF NOT EXISTS evidence_fia_pr.source_manifest (
  manifest_id text PRIMARY KEY,
  source_id text NOT NULL,
  snapshot_sha256 text NOT NULL UNIQUE,
  source_status text NOT NULL,
  retrieved_utc timestamptz,
  source_url text,
  documentation_version text,
  notes text
);

CREATE TABLE IF NOT EXISTS aguayluz_ecology.fia_plot_manifestation (
  source_cn bigint PRIMARY KEY,
  manifest_id text NOT NULL,
  invyr integer,
  statecd integer,
  unitcd integer,
  countycd integer,
  plot integer,
  latitude_public double precision,
  longitude_public double precision,
  spatial_precision_class text NOT NULL DEFAULT 'FIA_PUBLIC_PROTECTED',
  exact_site_identity_allowed boolean NOT NULL DEFAULT false,
  raw_record jsonb NOT NULL,
  CONSTRAINT fia_public_coords_no_exact_identity CHECK (exact_site_identity_allowed = false)
);

CREATE INDEX IF NOT EXISTS fia_plot_public_geom_idx
ON aguayluz_ecology.fia_plot_manifestation USING gist
(ST_SetSRID(ST_MakePoint(longitude_public, latitude_public), 4326));

-- Required downstream materializations must preserve source CN/EVALID/manifest lineage.
-- Population estimates must use FIADB EVALID/stratum/adjustment semantics.
-- No spatial proximity operation may promote an FIA public point to canonical facility/parcel identity.
