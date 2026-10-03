"""Benchmark InfluxDB 2.x: write throughput, storage size, and mean/max query latency.

Usage (from repo root, server running):
    uv run --env-file .env python benchmarks/benchmark.py --runs 5 --query-runs 50

Every write run uses a fresh temporary bucket that is deleted afterwards.
Only line-protocol generation is excluded from the write timer; HTTP + server ack is included.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from influxdb_client import InfluxDBClient, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from influxdb_explore.dataset import load_dataset  # noqa: E402
from influxdb_explore.replay import make_point  # noqa: E402

DATASETS = {
    "original": ROOT / "datasets/iot-agriculture-2024/IoTProcessed_Data.csv",
    "extended_80k": ROOT / "datasets/iot-agriculture-2024/IoTProcessed_Data_80k.csv",
}
CONTAINER = "influxdb"


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def percentile(values, p):
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarize(ms):
    return {"n": len(ms), "median_ms": statistics.median(ms), "p95_ms": percentile(ms, 95),
            "min_ms": min(ms), "max_ms": max(ms), "mean_ms": statistics.fmean(ms)}


def build_lines(path):
    rows, report = load_dataset(path, "UTC", False)
    lines = [make_point(r, "agriculture", r.timestamp_ns, "historical").to_line_protocol() for r in rows]
    return lines, report, rows


def bucket_bytes(bucket_id):
    """On-disk bytes for one bucket inside the container (TSM data + WAL)."""
    out = {}
    for part in ("data", "wal"):
        v = sh(f"docker exec {CONTAINER} du -sb /var/lib/influxdb2/engine/{part}/{bucket_id} 2>/dev/null | cut -f1")
        out[part] = int(v) if v.isdigit() else 0
    out["total"] = out["data"] + out["wal"]
    return out


def write_run(client, org, lines, batch, tag):
    buckets = client.buckets_api()
    b = buckets.create_bucket(bucket_name=f"bench_{tag}_{time.time_ns()}", org=org, retention_rules=None)
    try:
        with client.write_api(write_options=SYNCHRONOUS) as w:
            t0 = time.perf_counter()
            for i in range(0, len(lines), batch):
                w.write(bucket=b.name, org=org, record=lines[i:i + batch], write_precision=WritePrecision.NS)
            elapsed = time.perf_counter() - t0
        time.sleep(2)  # let the engine settle before measuring disk
        return {"seconds": elapsed, "points_per_s": len(lines) / elapsed, "disk": bucket_bytes(b.id)}
    finally:
        buckets.delete_bucket(b)


def query_flux(bucket, start, stop, every, fn):
    return (f'from(bucket: "{bucket}") |> range(start: {start}, stop: {stop}) '
            f'|> filter(fn: (r) => r._measurement == "agriculture" and r._field == "temperature") '
            f'|> aggregateWindow(every: {every}, fn: {fn}, createEmpty: false)')


def time_query(client, org, flux, runs, warmup):
    api = client.query_api()
    lat, rows = [], 0
    for i in range(warmup + runs):
        t0 = time.perf_counter()
        tables = api.query(flux, org=org)
        n = sum(len(t.records) for t in tables)  # fully materialise result
        dt = (time.perf_counter() - t0) * 1000
        if i >= warmup:
            lat.append(dt)
        rows = n
    return lat, rows


def snapshot_stats():
    return sh(f"docker stats --no-stream --format '{{{{.CPUPerc}}}} | {{{{.MemUsage}}}}' {CONTAINER}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.getenv("INFLUXDB_URL", "http://localhost:8086"))
    ap.add_argument("--org", default=os.getenv("INFLUXDB_ORG", "my-org"))
    ap.add_argument("--token", default=os.getenv("INFLUXDB_TOKEN", "my-token"))
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--batch-sizes", type=int, nargs="+", default=[100, 500, 1000, 5000])
    ap.add_argument("--query-runs", type=int, default=50)
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--windows", nargs="+", default=["1h", "1d"])
    ap.add_argument("--out", type=Path, default=ROOT / "reports/benchmark-results.json")
    args = ap.parse_args()

    env = {
        "date": datetime.now(timezone.utc).isoformat(),
        "host": platform.platform(),
        "cpu": sh("grep -m1 'model name' /proc/cpuinfo | cut -d: -f2").strip(),
        "cpu_threads": os.cpu_count(),
        "ram_total_mb": sh("free -m | awk '/Mem:/{print $2}'"),
        "influxdb": sh(f"docker exec {CONTAINER} influxd version"),
        "docker_image": sh(f"docker inspect {CONTAINER} --format '{{{{.Config.Image}}}}'"),
        "docker_limits": sh(f"docker inspect {CONTAINER} --format 'mem={{{{.HostConfig.Memory}}}} nanocpus={{{{.HostConfig.NanoCpus}}}}'") +
                         " (0 = unlimited)",
        "container_idle_before": snapshot_stats(),
        "loadavg_before": os.getloadavg(),
        "python_client": "influxdb-client (synchronous write, localhost, same host)",
    }
    results = {"environment": env, "write": [], "query": []}

    with InfluxDBClient(url=args.url, token=args.token, org=args.org, timeout=120_000) as client:
        for name, path in DATASETS.items():
            lines, report, rows = build_lines(path)
            line_bytes = sum(len(x) + 1 for x in lines)
            print(f"== {name}: {len(lines)} points, {line_bytes} B line protocol", flush=True)
            info = {"dataset": name, "csv": str(path.relative_to(ROOT)), "raw_rows": report["raw_rows"],
                    "points": len(lines), "csv_bytes": path.stat().st_size, "line_protocol_bytes": line_bytes}
            for batch in args.batch_sizes:
                runs = []
                for r in range(args.runs):
                    res = write_run(client, args.org, lines, batch, f"{name}_{batch}")
                    runs.append(res)
                    print(f"  batch={batch} run={r + 1}: {res['points_per_s']:.0f} pts/s, "
                          f"disk={res['disk']['total']} B", flush=True)
                pps = [x["points_per_s"] for x in runs]
                results["write"].append({**info, "batch_size": batch, "runs": runs,
                                         "median_points_per_s": statistics.median(pps),
                                         "min_points_per_s": min(pps), "max_points_per_s": max(pps),
                                         "median_disk_bytes": statistics.median(x["disk"]["total"] for x in runs)})

            # Query benchmark on one persistent temp bucket per dataset.
            b = client.buckets_api().create_bucket(bucket_name=f"bench_query_{name}_{time.time_ns()}", org=args.org)
            try:
                with client.write_api(write_options=SYNCHRONOUS) as w:
                    for i in range(0, len(lines), 5000):
                        w.write(bucket=b.name, org=args.org, record=lines[i:i + 5000], write_precision=WritePrecision.NS)
                first = min(r.timestamp_ns for r in rows)
                last = max(r.timestamp_ns for r in rows)
                start = datetime.fromtimestamp(first / 1e9, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                stop = datetime.fromtimestamp(last / 1e9 + 1, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                for every in args.windows:
                    for fn in ("mean", "max"):
                        flux = query_flux(b.name, start, stop, every, fn)
                        lat, nrows = time_query(client, args.org, flux, args.query_runs, args.warmup)
                        s = summarize(lat)
                        results["query"].append({"dataset": name, "points": len(lines), "range": [start, stop],
                                                 "window": every, "fn": fn, "result_rows": nrows,
                                                 "verdict_under_100ms": s["p95_ms"] < 100, **s})
                        print(f"  query {name} {fn}/{every}: median={s['median_ms']:.1f} ms "
                              f"p95={s['p95_ms']:.1f} ms rows={nrows}", flush=True)
                results.setdefault("query_container_stats", {})[name] = snapshot_stats()
            finally:
                client.buckets_api().delete_bucket(b)

    env["container_idle_after"] = snapshot_stats()
    env["loadavg_after"] = os.getloadavg()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2))
    print(f"Saved {args.out}")


if __name__ == "__main__":
    main()

