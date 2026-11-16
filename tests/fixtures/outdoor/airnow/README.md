# AirNow fixtures (constructed)

These two responses are **constructed** from the field list and example in AirNow's
API documentation (`observation/latLong/current`), not recorded: no `AIRNOW_API_KEY`
was available when `scripts/ingest_airnow.py` was written. They exercise a Saharan-dust
PM10 reading, a repeat of the same area from a second query point, a USVI row and an
unavailable (`AQI: -1`) row. Replace them with a recorded response once the key exists.
