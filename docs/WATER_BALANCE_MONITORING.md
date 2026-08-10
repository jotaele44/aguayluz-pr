# Water Balance Monitoring

AguaYLuz water-balance monitoring uses the same evidence posture as PRII
authority-record ingestion: preserve raw lineage, require explicit confidence,
and fail closed when an interval cannot be calculated without inference.

The current implementation is backend/internal. It does not expose a GUI workflow
until the backend gate is stable and site-specific Agua Ilos role maps are
available.

## Admission Rules

Every input reading must have:

- `reading_id`
- `asset_id`
- `observed_date`
- numeric `value`
- `unit`
- `source_ref`
- 64-character lowercase SHA256 `source_hash`
- valid `confidence`
- an explicit balance role supplied by role map

Roles are never inferred from metric names alone. A role map can key by
`reading_id` or by `asset_id|metric|parameter_code`.

## Fail-Closed Cases

The builder quarantines inputs for:

- missing source hash
- missing or invalid confidence
- missing asset or reading id
- invalid observed date
- no explicit balance role
- units that cannot be converted to million gallons for the declared role
- synthetic or fixture-only records in production mode

Intervals with missing inflow or outflow are blocked. Intervals with inflow and
outflow but no storage delta are degraded, not accepted.

## Outputs

`scripts/build_water_balance.py` writes:

- `data/water_balance_intervals.jsonl`
- `data/water_balance_quarantine.jsonl`

These are not canonical production balance claims unless all interval rows are
accepted and quarantine output is empty for the scope being certified.
