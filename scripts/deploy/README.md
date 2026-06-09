# Scheduled refresh (macOS launchd)

Keeps the AguaYLuz corpus live: USGS reservoir levels daily, USGS site network +
EPA SDWIS violations weekly, each followed by a federation/outputs rebuild.

> **Network:** the ingests call `waterservices.usgs.gov` and `data.epa.gov`. Run
> on a networked Mac — NOT inside the sandbox (its proxy blocks both). EPA needs a
> free `EPA_WATERS_API_KEY` / `API_DATA_GOV_KEY` for higher rate limits (the
> SDWIS efservice endpoints work key-less but are throttled).

## Manual run (verify before scheduling)

```bash
cd /path/to/aguayluz-pr
python scripts/refresh.py --all --dry-run   # show the plan
python scripts/refresh.py --daily           # fast: levels + export
python scripts/refresh.py --weekly          # full: assets + levels + SDWIS + export
```

## Install the launchd jobs

1. Edit both plists in this folder — replace every `__ABSOLUTE_PATH_TO_REPO__`
   with the repo's absolute path (e.g. `/Users/jotaele/Documents/GitHub/aguayluz-pr`)
   and set `EPA_WATERS_API_KEY` if you have one.
2. Create the log dir and install:

   ```bash
   mkdir -p logs
   cp scripts/deploy/com.aguayluz.refresh-*.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.aguayluz.refresh-daily.plist
   launchctl load ~/Library/LaunchAgents/com.aguayluz.refresh-weekly.plist
   ```

3. Verify / inspect:

   ```bash
   launchctl list | grep aguayluz
   launchctl start com.aguayluz.refresh-daily   # run once now
   tail -f logs/refresh-daily.out
   ```

   Unload with `launchctl unload ~/Library/LaunchAgents/com.aguayluz.refresh-*.plist`.

- Daily job: every day 06:15 local. Weekly job: Mondays 06:30 local.
- Each ingest MERGES (idempotent); the exporter validates against the schema gates
  and exits non-zero on failure, so a bad pull surfaces in `logs/*.err`.

## cron alternative

```cron
15 6 * * *  cd /path/to/aguayluz-pr && .venv/bin/python scripts/refresh.py --daily  >> logs/refresh-daily.out 2>&1
30 6 * * 1  cd /path/to/aguayluz-pr && .venv/bin/python scripts/refresh.py --weekly >> logs/refresh-weekly.out 2>&1
```
