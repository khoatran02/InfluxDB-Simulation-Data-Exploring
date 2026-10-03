"""Benchmark 500 concurrent HTTP write requests to InfluxDB 2.x.

Simulates 500 distinct IoT clients/sensors sending write requests at the exact same time.
Usage:
    uv run --env-file .env python benchmarks/concurrent_requests.py --concurrency 500
"""
from __future__ import annotations

import argparse
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]


def send_write_request(url: str, org: str, bucket: str, token: str, client_id: int) -> tuple[int, float, str]:
    """Send 1 HTTP write request using standard library (minimal overhead)."""
    ts = time.time_ns()
    # InfluxDB line protocol
    payload = f"agriculture,client=sensor_{client_id:04d},mode=concurrent temperature=28.5,humidity=70.0 {ts}\n"
    data = payload.encode("utf-8")
    
    endpoint = f"{url.rstrip('/')}/api/v2/write?org={urllib.parse.quote(org)}&bucket={urllib.parse.quote(bucket)}&precision=ns"
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "Authorization": f"Token {token}",
            "Content-Type": "text/plain; charset=utf-8",
        },
        method="POST"
    )

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            return (resp.status, elapsed_ms, "OK")
    except urllib.error.HTTPError as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return (e.code, elapsed_ms, str(e.reason))
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return (0, elapsed_ms, str(e))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.getenv("INFLUXDB_URL", "http://localhost:8086"))
    ap.add_argument("--org", default=os.getenv("INFLUXDB_ORG", "my-org"))
    ap.add_argument("--token", default=os.getenv("INFLUXDB_TOKEN", "my-token"))
    ap.add_argument("--bucket", default=os.getenv("INFLUXDB_BUCKET", "agriculture"))
    ap.add_argument("--concurrency", type=int, default=500, help="Number of concurrent requests")
    args = ap.parse_args()

    print(f"=== BẮT ĐẦU TEST {args.concurrency} REQUEST ĐỒNG THỜI VÀO INFLUXDB ===")
    print(f"URL: {args.url} | Bucket: {args.bucket} | Org: {args.org}")
    print(f"Đang chuẩn bị {args.concurrency} luồng (threads)...")

    start_wall = time.perf_counter()
    latencies = []
    statuses = {}
    
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(send_write_request, args.url, args.org, args.bucket, args.token, i)
            for i in range(args.concurrency)
        ]
        for f in as_completed(futures):
            status, dt_ms, reason = f.result()
            latencies.append(dt_ms)
            statuses[status] = statuses.get(status, 0) + 1

    total_wall = time.perf_counter() - start_wall
    latencies.sort()

    def p(vals, pct):
        k = (len(vals) - 1) * pct / 100
        lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
        return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)

    success_count = statuses.get(204, 0)
    print("\n=== KẾT QUẢ THỰC NGHIỆM ĐỒNG THỜI (CONCURRENCY) ===")
    print(f"Tổng số request:       {args.concurrency}")
    print(f"Thành công (HTTP 204): {success_count}/{args.concurrency} ({success_count / args.concurrency * 100:.1f}%)")
    print(f"Mã phản hồi chi tiết:  {statuses}")
    print(f"Tổng thời gian:        {total_wall:.3f} s")
    print(f"Thông lượng đạt được:  {args.concurrency / total_wall:.1f} requests/s")
    print("--- Độ trễ (Response Latency) ---")
    print(f"Min latency:           {min(latencies):.2f} ms")
    print(f"Median (p50):          {statistics.median(latencies):.2f} ms")
    print(f"p95 latency:           {p(latencies, 95):.2f} ms")
    print(f"p99 latency:           {p(latencies, 99):.2f} ms")
    print(f"Max latency:           {max(latencies):.2f} ms")


if __name__ == "__main__":
    main()

