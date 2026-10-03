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

## Synthetic 80k dataset

[extend_to_80k.py](datasets/iot-agriculture-2024/extend_to_80k.py) extends the cleaned source (**28,682** unique-timestamp rows) to **82,000 rows** in [IoTProcessed_Data_80k.csv](datasets/iot-agriculture-2024/IoTProcessed_Data_80k.csv) by continuing the 5-minute cadence forward from `2024-03-30` to `2024-10-01`. Same columns and one-hot actuator encoding (`_ON` + `_OFF` = 1) as the source. Stdlib + numpy only, seeded (`SEED = 42`) for reproducibility.

```bash
python3 datasets/iot-agriculture-2024/extend_to_80k.py
```

Strategy, in order:

1. **Clean** — drop empty/unparseable dates, clip `humidity`/`water_level` to 0–100 and `N`/`P`/`K` to ≤ 255 (the source contains a `K = 259` sensor glitch), deduplicate timestamps, sort. Keeps the original `tempreature` column spelling.
<!-- 2. **Fit profiles on real data** — per-hour-of-day mean/std for temperature and humidity (daily cycle), a temperature→humidity linear coupling with residual noise, and the observed discrete `N`/`P`/`K` value pools (8–9 values each). -->
3. **Extend the timeline** — generate one row per 5 minutes past the last real timestamp. Temperature = hourly mean + AR(1) smooth noise; humidity = mean-anchored temp coupling + hourly deviation; water level = mean-reverting walk around 70 with asymmetric pump dynamics (drains −4.0/step when the pump is ON, refills +1.5/step when OFF) so the level oscillates across the pump threshold; `N`/`P`/`K` hold constant for ~1–7 days then jump to another observed discrete value.
4. **Rule-based actuators with noise** — thresholds are learned from the real data by maximizing Youden's J (currently: fan ON if temp > ~21, pump ON if water level < ~75, watering ON if humidity < ~52), then ~5% of decisions are flipped so behaviour is not perfectly deterministic.
5. **Validate** — the script prints real-vs-synthetic mean/std for temperature, humidity mean, the fraction of water levels below the pump threshold, and ON-rates for all three actuators.

Use this file for scale, ingestion, and query-performance experiments. It is synthetic continuations data, not measured ground truth — do not use it for agronomic or sensor-accuracy claims.

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

## Retention and downsampling

| Mechanism | What it does | Where |
| --- | --- | --- |
| Bucket retention (TTL) | Each bucket has a time-to-live. Points older than the TTL are rejected on write (HTTP 422) and expired data is deleted automatically by the retention enforcer (about every 30 min). Example: raw bucket 7 days, summary bucket 365 days. | `BucketRetentionRules` in the demo; `DOCKER_INFLUXDB_INIT_RETENTION: "0"` in `docker-compose.yml` keeps the main `agriculture` bucket unlimited |
| Downsampling | A Flux task aggregates high-frequency raw data into larger windows (here 5 min to 1 h) with `mean`, `max`, `min`, `sum` via `aggregateWindow`, and writes to the long-TTL bucket with `to()`. | `queries/08_downsample_multi_agg.flux` |

```bash
# Creates temporary 7-day/365-day buckets, shows TTL rejection and runs the downsample (cleans up afterwards).
uv run --env-file .env python benchmarks/retention_downsampling_demo.py
```

Measured output: 1,008 raw 5-minute points become 85 hourly rows per aggregate (about 12x fewer); a point 10 days old is rejected by the 7-day bucket. `sum` only makes sense for additive quantities (for example counting fan-on samples), not for temperature; it is included to show the function. Do not put a short TTL on the `agriculture` bucket: it holds the courses

## Retention and downsampling

| Mechanism | What it does | Where |
| --- | --- | --- |
| Bucket retention (TTL) | Each bucket has a time-to-live. Points older than the TTL are rejected on write (HTTP 422) and expired data is deleted automatically by the retention enforcer (about every 30 min). Example: raw bucket 7 days, summary bucket 365 days. | `BucketRetentionRules` in the demo; `DOCKER_INFLUXDB_INIT_RETENTION: "0"` in `docker-compose.yml` keeps the main `agriculture` bucket unlimited |
| Downsampling | A Flux task aggregates high-frequency raw data into larger windows (here 5 min to 1 h) with `mean`, `max`, `min`, `sum` via `aggregateWindow`, and writes to the long-TTL bucket with `to()`. | `queries/08_downsample_multi_agg.flux` |

```bash
# Creates temporary 7-day/365-day buckets, shows TTL rejection and runs the downsample (cleans up afterwards).
uv run --env-file .env python benchmarks/retention_downsampling_demo.py
```

Measured output: 1,008 raw 5-minute points become 85 hourly rows per aggregate (about 12x fewer); a point 10 days old is rejected by the 7-day bucket. `sum` only makes sense for additive quantities (for example counting fan-on samples), not for temperature; it is included to show the function. Do not put a short TTL on the `agriculture` bucket: it holds the course's historical evidence.
