# Upstream change runbook

When CI fires a drift alert, this is how to roll the change forward. The
loop is: **detect → notify → operator accepts via PR**. Three CI jobs feed
this runbook, each with its own committed baseline + acceptance command.

## Detection matrix

| Signal | Where it fires | What it means | Severity |
|---|---|---|---|
| `live-corpus` workflow fails (`--baseline-check`) | `.github/workflows/live-corpus.yml` (daily 12:00 UTC) | Headline asset/event/watershed counts moved >10%, OR a federation gate flipped to FAIL, OR the live ingest itself crashed | critical |
| `oas-monitor / check-oas-shape` fails | `.github/workflows/oas-monitor.yml` (daily 13:00 UTC) | EPA changed the WATERS OpenAPI surface (new path, removed path, response ref shifted) | critical |
| `oas-monitor / check-classifier` fails | Same workflow, separate job | FRS classifier utility-detect rate moved outside tolerance, OR facility-total swung >25% — EPA likely changed naming/coverage | warn |
| `G01_SCHEMA` gate fails on any push | `validate.yml` (every push) | An entity output ended up with an unexpected field — adapter regressed | critical |

Slack notifications post to `$SLACK_WEBHOOK_URL` if the repo secret is set;
absence is treated as a quiet no-op (workflow still fails, just no ping).

## Accepting a change

The pattern is the same for all three monitors: **investigate the diff,
decide it's safe, regenerate the baseline, commit + open a PR.**

### Live-corpus drift (`live-corpus.yml` failed)

```bash
# 1. Reproduce locally
EPA_WATERS_API_KEY=$(cat '/path/to/key') \
  python scripts/run_full_chain.py --live --use-waters \
  --cities BAYAMON,SAN_JUAN,PONCE,CAGUAS,MAYAGUEZ \
  --damage-codes D,F --max-fema-records 50

# 2. Inspect the diff
python scripts/diff_runs.py   # auto-picks the last two snapshots
cat outputs/run_diff.json | jq '.summary'

# 3. If the change is legitimate (e.g. EPA added new facilities), refresh
#    the baseline. If it's broken (e.g. a city now returns 500s), open an
#    issue + skip the city in the CLI instead.
EPA_WATERS_API_KEY=… python scripts/run_full_chain.py --live --use-waters \
  --cities BAYAMON,SAN_JUAN,PONCE,CAGUAS,MAYAGUEZ \
  --damage-codes D,F --max-fema-records 50 --baseline-write

# 4. Commit
git add tests/baseline/live_corpus_summary.json
git commit -m "ops: refresh live-corpus baseline — <reason>"
```

### WATERS OAS shape drift (`oas-monitor / check-oas-shape` failed)

The workflow log shows a per-finding diff like:
```
path added: /v5/newendpoint
  /v1/pointindexing GET: response shape changed '#/components/responses/x414' → '#/components/responses/x900'
```

For each finding:

| Finding kind | Likely impact | Action |
|---|---|---|
| `path added: …` | New endpoint we might want to wrap | Decide if it's relevant to the federation contract. If yes, add a wrapper in `src/aguayluz/waters/endpoints.py`. If no, accept the snapshot. |
| `path removed: …` | An endpoint we use is gone | **Critical**. If our adapters depend on it (see `docs/architecture.md`), the producer breaks. Migrate to the closest replacement before regenerating. |
| `method added: post` | EPA added POST to a GET-only path | Usually a non-event for us. Accept. |
| `method removed: get` | EPA removed our access pattern | **Critical**. Migrate before accepting. |
| `response shape changed` | EPA changed the response component reference | Look at the new component schema. If field names match what we use (`comid`, `reachcode`, `nhdplus_region`, etc.), accept. If they renamed fields, patch the adapter first. |
| `server_url changed` | EPA moved the base URL | Update the `DEFAULT_BASE_URL` constant in `src/aguayluz/waters/client.py`, run M2 verification, then accept. |
| `info.version changed` | EPA bumped the OAS version | Usually informational. Re-verify all of the above, then accept. |

After patching code (if needed), accept the new shape:

```bash
# Refresh the snapshot from the live OAS
python scripts/check_oas_shape.py --write-snapshot

# Verify acceptance
python scripts/check_oas_shape.py --check
# → "oas shape: in sync (<new-sig>…)"

# Commit
git add tests/baseline/waters_oas_shape.json src/aguayluz/waters/  # any code changes
git commit -m "ops: accept WATERS OAS shape change — <summary of diff>"
```

### Classifier rate drift (`oas-monitor / check-classifier` failed)

The workflow log shows what moved:
```
utility_pct 0.40% < minimum 0.50% — classifier likely degraded
facility_total 750 drifted 27.0% from reference 648 — EPA may have added records
```

Two distinct paths:

**If EPA added/removed records** (facility_total moved): accept with a fresh
reference. The classifier still works, EPA's just got a different dataset:

```bash
python scripts/audit_classifier.py --write-reference
git add tests/baseline/classifier_rate.json
git commit -m "ops: refresh classifier reference — EPA dataset moved"
```

**If utility_pct degraded but record count is stable**: the classifier is
genuinely missing facilities now. Check `src/aguayluz/ingest/frs.py:infer_asset_type`:

```bash
# Grab a current sample
.venv/bin/python -c "
from aguayluz.ingest.frs_client import fetch_facilities
from aguayluz.ingest.frs import parse_frs_response, infer_asset_type
env = fetch_facilities(state_abbr='PR', city_name='BAYAMON')
for f in env['Results']['FRSFacility']:
    name = f['FacilityName']
    cls = infer_asset_type(name)
    if not cls[2]:
        print(f'  skip: {name}')   # not classified as utility
" | sort | uniq -c | sort -rn | head -20
```

Look for utility-shaped names that aren't classified. Add Spanish keywords
or new abbreviations to `infer_asset_type`. Add a unit test in
`tests/test_ingest_frs.py::test_classifier`. THEN refresh the reference:

```bash
python scripts/audit_classifier.py --write-reference
git add src/aguayluz/ingest/frs.py tests/test_ingest_frs.py tests/baseline/classifier_rate.json
git commit -m "ops: extend FRS classifier — <list of new keywords>"
```

### G01 schema drift (validate.yml failed on push)

This is the "EPA added a field we don't know about" path. `additionalProperties:
false` on every schema means any unexpected field in an entity output fails
the gate.

```bash
# Reproduce
.venv/bin/python scripts/validate_repo.py

# The error message names the offending field, e.g.:
#   utility_assets.json[0]: ValidationError:
#     'Additional properties are not allowed ('new_epa_field' was unexpected)'

# Two paths:
# (a) Adopt the field: edit schemas/<entity>.schema.json + src/aguayluz/models.py
#     + adapter to surface it. Add a test. Commit.
# (b) Drop the field at the adapter: edit src/aguayluz/ingest/<adapter>.py to
#     strip it before the entity is constructed. Document why in the commit.
```

## Quick reference: every baseline + how to refresh it

| File | What it baselines | Refresh command |
|---|---|---|
| `tests/baseline/live_corpus_summary.json` | M18 headline counts for the 5-city live run | `python scripts/run_full_chain.py --live --use-waters --baseline-write` |
| `tests/baseline/waters_oas_shape.json` | M23 EPA WATERS OpenAPI path × method × response-ref | `python scripts/check_oas_shape.py --write-snapshot` |
| `tests/baseline/classifier_rate.json` | M23 FRS classifier utility-detect rate (BAYAMON) | `python scripts/audit_classifier.py --write-reference` |
| `docs/gap_analysis.md` (inventory counts) | M17 file/test counts | `python scripts/gap_audit.py` |

Every refresh is "operator runs the command + commits the file + opens a
PR." Nothing happens automatically — drift detection is automated, drift
acceptance is human.

## Why no auto-PR

We deliberately don't auto-open PRs from CI when drift is detected. The
acceptance decision needs a human looking at the diff. Auto-accepting an
EPA endpoint removal would silently break the producer for downstream
receivers; auto-accepting a classifier regression would mask a real bug.

The trade-off is: operator gets pinged daily if EPA is churning. The
alternative — quietly absorbing every change — costs federation reliability.
