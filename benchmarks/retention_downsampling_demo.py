"""End-to-end demo of bucket retention (TTL) and downsampling on temporary buckets.

    uv run --env-file .env python benchmarks/retention_downsampling_demo.py

1. Retention: raw bucket with 7-day TTL, summary bucket with 365-day TTL; show that a point
   older than the TTL is rejected, and that in-range data is accepted.
2. Downsampling: 5-minute raw data -> 1-hour mean/max/min/sum via queries/08_downsample_multi_agg.flux.
Buckets are named with a unique suffix and deleted at the end.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from influxdb_client import BucketRetentionRules, InfluxDBClient, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.rest import ApiException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from influxdb_explore.dataset import load_dataset  # noqa: E402
from influxdb_explore.replay import make_point  # noqa: E402

DAY = 86400
CSV = ROOT / "datasets/iot-agriculture-2024/IoTProcessed_Data_80k.csv"  # regular 5-min tail
FLUX = ROOT / "queries/08_downsample_multi_agg.flux"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.getenv("INFLUXDB_URL", "http://localhost:8086"))
    ap.add_argument("--org", default=os.getenv("INFLUXDB_ORG", "my-org"))
    ap.add_argument("--token", default=os.getenv("INFLUXDB_TOKEN", "my-token"))
    ap.add_argument("--rows", type=int, default=1008, help="5-minute rows (1008 = 3.5 days)")
    args = ap.parse_args()

    suffix = str(time.time_ns())
    raw_name, sum_name = f"demo_raw_7d_{suffix}", f"demo_1h_365d_{suffix}"
    rows, _ = load_dataset(CSV, "UTC", False)
    rows = sorted(rows, key=lambda r: r.timestamp_ns)[-args.rows:]  # CSV order is not chronological
    span_days = (rows[-1].timestamp_ns - rows[0].timestamp_ns) / 1e9 / DAY
    if span_days >= 6:
        sys.exit("--rows must span under 6 days to fit inside the 7-day TTL")

    with InfluxDBClient(url=args.url, token=args.token, org=args.org, timeout=60_000) as client:
        buckets = client.buckets_api()
        raw = buckets.create_bucket(bucket_name=raw_name, org=args.org,
                                    retention_rules=BucketRetentionRules(type="expire", every_seconds=7 * DAY))
        summ = buckets.create_bucket(bucket_name=sum_name, org=args.org,
                                     retention_rules=BucketRetentionRules(type="expire", every_seconds=365 * DAY))
        try:
            print("== 1. Retention")
            for b in (raw, summ):
                got = buckets.find_bucket_by_id(b.id)
                print(f"  {got.name}: TTL = {got.retention_rules[0].every_seconds / DAY:g} days")

            with client.write_api(write_options=SYNCHRONOUS) as w:
                # Shift history so it ends "now": last row -> now - 1 minute, spacing preserved.
                shift = time.time_ns() - 60_000_000_000 - rows[-1].timestamp_ns
                points = [make_point(r, "agriculture", r.timestamp_ns + shift, "demo") for r in rows]
                w.write(bucket=raw_name, org=args.org, record=points, write_precision=WritePrecision.NS)
                print(f"  wrote {len(points)} points inside TTL (accepted)")
                old = make_point(rows[0], "agriculture", time.time_ns() - 10 * DAY * 10**9, "demo")
                try:
                    w.write(bucket=raw_name, org=args.org, record=old, write_precision=WritePrecision.NS)
                    print("  UNEXPECTED: 10-day-old point was accepted")
                except ApiException as e:
                    print(f"  10-day-old point rejected by 7-day TTL: HTTP {e.status} (expected 422)")
            print("  Expired data is physically removed by the retention enforcer (checks ~every 30 min).")

            print("== 2. Downsampling 5 min -> 1 h")
            script = FLUX.read_text(encoding="utf-8")
            script = (script.replace('rawBucket = "agriculture_raw_7d"', f'rawBucket = "{raw_name}"')
                      .replace('destBucket = "agriculture_1h_365d"', f'destBucket = "{sum_name}"')
                      .replace('destOrg = "my-org"', f'destOrg = "{args.org}"')
                      .replace("range(start: -2h)", "range(start: -7d)"))  # demo: whole raw window
            client.query_api().query(script, org=args.org)

            q = client.query_api()
            raw_n = q.query(f'from(bucket:"{raw_name}") |> range(start:-7d) |> filter(fn:(r)=>r._field=="temperature") |> count()',
                            org=args.org)[0].records[0].get_value()
            print(f"  raw temperature points: {raw_n}")
            for field in ("mean", "max", "min", "sum"):
                t = q.query(f'from(bucket:"{sum_name}") |> range(start:-7d) |> filter(fn:(r)=>r._field=="temperature_{field}")',
                            org=args.org)
                vals = [r.get_value() for tb in t for r in tb.records]
                if vals:
                    print(f"  temperature_{field}: {len(vals)} hourly rows, first={vals[0]:.2f}, "
                          f"min={min(vals):.2f}, max={max(vals):.2f}")
                else:
                    print(f"  temperature_{field}: no rows")
            print(f"  reduction: {raw_n} raw points -> ~{raw_n // 12} hourly rows per aggregate")
        finally:
            buckets.delete_bucket(raw)
            buckets.delete_bucket(summ)
            print("temporary buckets deleted")


if __name__ == "__main__":
    main()
