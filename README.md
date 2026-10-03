# Exploring InfluxDB with Agriculture IoT Data

A course project using **InfluxDB OSS 2.7.12**, Python (via `uv`), and Flux to explore time-series ingestion, schema design, historical queries, live dashboards, concurrency handling, and downsampling. 

This project simulates IoT sensor environments using recorded agriculture data. It does not connect to physical sensors or train AI models. The goal is to master InfluxDB operations for an AI-IoT curriculum.

See [GUIDE.md](GUIDE.md) for lab tutorials, dashboard setup instructions, report outlines, and presentation scripts. See [reports/REVIEW.md](reports/REVIEW.md) for initial dataset review findings.

---

## 🚀 Quick Start

**Requirements:** Docker with Compose v2+, and [uv](https://docs.astral.sh/uv/) (Python package manager). `uv` will use Python 3.12 defined in `.python-version`.

Run all commands from the root directory:

```bash
# 1. Populate the local environment configuration (preserves existing if present)
if [ ! -s .env ]; then cp .env.example .env; fi

# 2. Install dependencies via uv
uv sync --locked

# 3. Start the InfluxDB container in the background
docker compose up -d --build --wait

# 4. Profile the raw CSV dataset without hitting the database
uv run influx-profile --output reports/dataset-profile.json
```

Open InfluxDB UI at **<http://localhost:8086>**.
- **Username:** `admin`
- **Password:** `admin-password-123`
*(Connections match `.env.example` defaults)*.

---

## 📊 Dataset Information

### The Original Dataset
The source CSV contains **37,922 rows** with observations for temperature, humidity, water level, soil nutrients (N, P, K), and binary actuator states (fans, pumps).
- **Valid Rows:** 37,920 (spanning `2023-11-27` to `2024-03-30` in UTC).
- **Handling Duplicate Timestamps:** The dataset contains ~9,238 observations that share the exact same timestamp. In InfluxDB, duplicate timestamps within the same series will overwrite data. This project avoids data loss by deterministically offsetting duplicates by up to **9 nanoseconds**.

### The Synthetic 80k Extension
To test InfluxDB at scale, we provide a tool to extend the timeline from March 2024 to October 2024.
- **Run it:** `python3 datasets/iot-agriculture-2024/extend_to_80k.py`
- **Result:** Drops anomalies, models daily temperature/humidity cycles, models asymmetric pump dynamics, and writes an 82,000-row continuation to `IoTProcessed_Data_80k.csv`. 

> [!NOTE]
> The 80k dataset is synthetic and uses a fixed `SEED = 42` for reproducibility. It is meant for performance benchmarking, not agronomic accuracy claims.

---

## 📥 Data Ingestion Strategies

We use `influxdb-client` with `SYNCHRONOUS` batching to write data efficiently. 

### 1. Batch Historical Import
Ideal for massive data backfills. We disable artificial intervals (`--interval 0`) and use large batches.
```bash
# Insert all 37,920 rows. 
uv run --env-file .env influx-replay --preserve-time --interval 0 --batch-size 500

# Verify the count
uv run --env-file .env influx-query queries/02_historical_count.flux
```

### 2. Live Replay (Stream Simulation)
Ideal for testing live dashboards and dashboards updates.
```bash
# Ingest 1 observation per second for 120 seconds.
uv run --env-file .env influx-replay --interval 1 --max-rows 120
```

---

## ⚡ Concurrency Load Testing

To prove InfluxDB's capability in a real-world multi-sensor IoT network, we test high concurrency using **500 simultaneous POST requests** (simulating 500 devices hitting the database at the exact same millisecond). 

The load test specifically bypasses the standard InfluxDB Python client (avoiding GIL/thread-lock overheads) and uses standard library `urllib` to hit the API concurrently.

```bash
uv run --env-file .env python benchmarks/concurrent_requests.py --concurrency 500
```
**Results observed:**
| Metric | Result |
| --- | --- |
| Success Rate (HTTP 204) | 500/500 (100.0%) |
| Total Execution Time | 0.272 seconds |
| API Throughput | 1837.9 requests/s |
| Min Latency | 7.27 ms |
| Median Latency (p50) | 13.16 ms |
| 95th Percentile (p95) | 20.54 ms |
| Max Latency | 26.30 ms |

**Conclusion:** InfluxDB handled the simultaneous burst of 500 requests flawlessly, achieving sub-30ms latency even for the slowest requests under high concurrent load.

---

## 🕰️ Retention & Downsampling

Time-series databases use retention limits and continuous queries (Tasks) to manage disk space. 
We provide a standalone demonstration of this:

```bash
uv run --env-file .env python benchmarks/retention_downsampling_demo.py
```

**What this demo does:**
1. **Bucket TTL (Time-To-Live):** Creates a 7-day raw data bucket and proves that points 10 days old are actively rejected (HTTP 422) by the server.
2. **Downsampling:** Runs a Flux task (`queries/08_downsample_multi_agg.flux`) that takes 1,008 raw 5-minute points and aggregates them into 1-hour windows (using `mean`, `max`, `min`, `sum`).
3. **Storage Reduction:** Output rows are reduced by ~12x and routed to a 365-day retention bucket.

---

## 📈 Benchmark Results

Extensive benchmarks were run natively (see `reports/BENCHMARK.md`). Below are the detailed findings regarding write throughput, storage sizes, and query latency:

### 1. Write Throughput & Storage Footprint
Writes were executed synchronously into a temporary bucket. The times reflect the client sending the request and receiving the server's ACK. 

| Dataset | Total Points | Batch Size | Median (points/s) | Min–Max (points/s) | Storage Size (Bytes) |
| --- | --- | --- | --- | --- | --- |
| **Original CSV** | 37,920 | 100 | 7,124 | 6,948 – 7,994 | 36,721,673 |
| | | 500 | 14,027 | 14,007 – 14,344 | 37,078,764 |
| | | 1000 | 16,529 | 16,294 – 16,632 | 37,454,044 |
| | | 5000 | 28,161 | 25,774 – 29,032 | 37,920,491 |
| **Synthetic 80k**| 82,000 | 100 | 6,900 | 6,883 – 6,978 | 41,346,708 |
| | | 500 | 14,001 | 13,901 – 14,109 | 42,112,677 |
| | | 1000 | 16,526 | 16,306 – 17,565 | 42,806,715 |
| | | 5000 | 27,129 | 26,408 – 27,716 | 43,990,168 |

**Key Takeaways:**
- **Batch Size impact:** Increasing the batch size from 100 to 5,000 yields a ~4x speed increase. We achieved a maximum throughput of **~28,000 points per second** at a batch size of 5,000.
- **Storage Oddities (`du -sb`):** Because WAL (Write-Ahead Logs) pre-allocates size before TSM compaction runs, disk size checks immediately post-write do not reflect true compressed footprints. Storing 37k rows vs 82k rows only increased disk size by ~12%, proving most of the footprint is fixed overhead.

### 2. Query Latency (`mean` vs `max`)
Queries were run using `aggregateWindow(createEmpty: false)` over the entire dataset's time range on the `temperature` field. We targeted a strict `< 100ms` SLA.

| Dataset | Time Window | Aggregation | Result Rows | Median (ms) | 95th Percentile (ms) | Max (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| **Original** | 1h | mean | 2,163 | 27.5 | 46.6 | 52.1 |
| **Original** | 1h | max | 2,163 | 26.6 | 39.1 | 49.2 |
| **Original** | 1d | mean | 101 | 16.7 | 18.6 | 29.2 |
| **Original** | 1d | max | 101 | 16.7 | 17.9 | 25.3 |
| **Synthetic 80k**| 1h | mean | 6,606 | 55.2 | 89.5 | 91.4 |
| **Synthetic 80k**| 1h | max | 6,606 | 52.9 | 87.6 | 89.1 |
| **Synthetic 80k**| 1d | mean | 286 | 24.3 | 25.3 | 45.4 |
| **Synthetic 80k**| 1d | max | 286 | 24.1 | 25.4 | 40.0 |

**Key Takeaways:**
- All queries passed the `< 100ms` target successfully.
- Querying a 1-hour `mean` window over 80,000 rows resolved with a median of **55.2 ms** (Max: 91.4 ms).
- The execution time difference between calculating `mean` and `max` over these sets was statistically negligible.

---

## 🗺️ Project Map

| Path | Purpose |
| --- | --- |
| `src/influxdb_explore/dataset.py` | Validation, data profile, timestamp disambiguation |
| `src/influxdb_explore/replay.py` | Live replay and batched historical import |
| `src/influxdb_explore/query.py` | Run Flux files and export annotated CSV |
| `queries/01`–`06` | Read-only analysis and dashboard queries |
| `queries/07_downsample_task.flux` | Optional scheduled aggregation, writes to a separate bucket |
| `tests/` | Offline regression checks and explicit database integration check |
| `benchmarks/` | Scripts for throughput, query latency, concurrency, and downsampling |
| `reports/` | Output logs, verification evidence, and benchmark analysis |
| `GUIDE.md` | Course lab and presentation guidance |

---

## ✅ Verification & Tests

To ensure your environment behaves exactly as designed:

```bash
uv run python -m unittest discover -s tests -v
uv build
docker compose config --quiet

# Runs a full integration loop using temporary buckets
uv run --env-file .env python tests/integration_check.py
```

