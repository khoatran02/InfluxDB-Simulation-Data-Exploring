# Exploring InfluxDB with agriculture IoT data

A course project using **InfluxDB OSS 2.7.12**, Python, and Flux to explore time-series ingestion, schema design, historical queries, live dashboards, duplicate points, and downsampling. The CSV is replayed sensor data; this project does not connect to physical sensors or train an AI model.

Start with [GUIDE.md](GUIDE.md) for the lab, dashboard instructions, report outline, and presentation script. See [the review](reports/REVIEW.md) for findings and verification evidence.

## Quick start

Requirements: Docker with Compose v2+, and [uv](https://docs.astral.sh/uv/). Run from this directory. `uv` uses Python 3.12 from `.python-version`.

```bash
# Populate the currently empty/missing local configuration, preserving any existing values.
if [ ! -s .env ]; then cp .env.example .env; fi
uv sync --locked
docker compose up -d --build --wait

# Inspect data quality without a database connection.
uv run influx-profile --output reports/dataset-profile.json

# Import all 37,920 valid observations with historical timestamps.
uv run --env-file .env influx-replay --preserve-time --interval 0 --batch-size 500
uv run --env-file .env influx-query queries/02_historical_count.flux

# Replay one observation per second for a live dashboard.
uv run --env-file .env influx-replay --interval 1 --max-rows 120
```

Open <http://localhost:8086>. Local demo login: `admin` / `admin-password-123`. Connection defaults match `.env.example`. Existing database volumes retain their original credentials; editing `.env` does not reset them.

The source has **37,922 rows**, two missing dates, and **9,238 extra observations at repeated timestamps**. Valid dates span **2023-11-27 to 2024-03-30**, assuming UTC. Historical duplicate timestamps receive deterministic offsets of up to **9 nanoseconds** so all valid readings survive. Original timestamps and CSV line numbers remain in fields. This offset is a storage convention, not sensor timing accuracy.

## Project map

| Path | Purpose |
| --- | --- |
| `src/influxdb_explore/dataset.py` | Validation, data profile, timestamp disambiguation |
| `src/influxdb_explore/replay.py` | Live replay and batched historical import |
| `src/influxdb_explore/query.py` | Run Flux files and export annotated CSV |
| `queries/01`–`06` | Read-only analysis and dashboard queries |
| `queries/07_downsample_task.flux` | Optional scheduled aggregation, writes to a separate bucket |
| `tests/` | Offline regression checks and explicit database integration check |
| `reports/` | Dataset profile, verification evidence, source review |
| `GUIDE.md` | Course lab and presentation guidance |

## Verification

```bash
uv run python -m unittest discover -s tests -v
uv build
docker compose config --quiet
# Requires a running server and a token allowed to create/delete buckets.
# Creates unique temporary buckets and deletes only those buckets afterward.
uv run --env-file .env python tests/integration_check.py
```

The stack deliberately pins InfluxDB v2 because these exercises use its Flux API and built-in UI. Do not replace the image with `influxdb:latest`; consult the [official v2 installation documentation](https://docs.influxdata.com/influxdb/v2/install/) when changing versions.
