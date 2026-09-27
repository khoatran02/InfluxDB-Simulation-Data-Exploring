"""Replay agriculture observations into InfluxDB 2.x."""
from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from .config import add_connection_args
from .dataset import DEFAULT_CSV, load_dataset


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_connection_args(parser)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--measurement", default="agriculture")
    parser.add_argument("--interval", type=float, default=1.0, help="Delay between rows in seconds")
    parser.add_argument("--max-rows", type=int)
    parser.add_argument("--batch-size", type=int, default=1, help="Synchronous write size; >1 requires interval 0")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--preserve-time", action="store_true", help="Historical time with deterministic ns offsets for duplicates")
    parser.add_argument("--source-timezone", default="UTC", help="Timezone assumed for naive CSV dates")
    parser.add_argument("--strict", action="store_true", help="Fail before writing if any row is invalid")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print line protocol without connecting")
    args = parser.parse_args(argv)
    if not math.isfinite(args.interval) or args.interval < 0:
        parser.error("--interval must be finite and nonnegative")
    if args.max_rows is not None and args.max_rows <= 0:
        parser.error("--max-rows must be positive")
    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    if args.batch_size > 1 and args.interval != 0:
        parser.error("--batch-size > 1 requires --interval 0")
    if args.loop and args.preserve_time:
        parser.error("--loop with --preserve-time would overwrite the same history")
    if args.dry_run and args.loop:
        parser.error("--dry-run cannot be combined with --loop")
    return args


def make_point(row, measurement, timestamp_ns, mode):
    point = (Point(measurement).tag("source", "iot-agriculture-2024").tag("mode", mode)
             .time(timestamp_ns, WritePrecision.NS))
    for name, value in row.fields.items():
        point.field(name, value)
    # Provenance is stored in fields, not high-cardinality tags.
    return point.field("source_row", row.source_row).field("source_time_ns", row.source_time_ns)


def iter_points(rows, args, clock=time.time_ns):
    count = 0
    last_live = 0
    while True:
        for row in rows:
            if args.max_rows is not None and count >= args.max_rows:
                return
            if count and args.interval:
                time.sleep(args.interval)
            if args.preserve_time:
                timestamp = row.timestamp_ns
            else:
                timestamp = max(clock(), last_live + 1)
                last_live = timestamp
            yield make_point(row, args.measurement, timestamp, "historical" if args.preserve_time else "live")
            count += 1
        if not args.loop:
            return


def replay(args):
    rows, report = load_dataset(args.csv, args.source_timezone, args.strict)
    print(f"Validated {report['valid_rows']}/{report['raw_rows']} rows; "
          f"skipped {len(report['invalid_rows'])}; "
          f"duplicate timestamp extra rows={report['extra_rows_at_duplicate_timestamps']}. "
          f"Source timezone assumption: {args.source_timezone}.", file=sys.stderr)
    for issue in report["invalid_rows"][:5]:
        print(f"Skipped CSV line {issue['csv_line']}: {issue['reason']}", file=sys.stderr)
    if args.dry_run:
        for point in iter_points(rows, args):
            print(point.to_line_protocol())
        return 0
    written = 0
    started = time.perf_counter()
    with InfluxDBClient(url=args.url, token=args.token, org=args.org, timeout=30_000) as client:
        if client.health().status != "pass":
            raise RuntimeError("InfluxDB is not healthy")
        with client.write_api(write_options=SYNCHRONOUS) as writer:
            batch = []
            for point in iter_points(rows, args):
                batch.append(point)
                if len(batch) >= args.batch_size:
                    writer.write(bucket=args.bucket, org=args.org, record=batch, write_precision=WritePrecision.NS)
                    written += len(batch)
                    batch.clear()
                    if written <= 10 or written % 1000 == 0:
                        print(f"Written {written} points", flush=True)
            if batch:
                writer.write(bucket=args.bucket, org=args.org, record=batch, write_precision=WritePrecision.NS)
                written += len(batch)
    elapsed = time.perf_counter() - started
    print(f"Completed: {written} points acknowledged in {elapsed:.3f}s ({written / max(elapsed, 1e-9):.1f} points/s).")
    return written


def main(argv=None):
    args = parse_args(argv)
    try:
        replay(args)
    except KeyboardInterrupt:
        print("\nReplay interrupted; query InfluxDB for the persisted count.", file=sys.stderr)
        return 130
    except Exception as error:
        # Do not print HTTP request headers or API tokens.
        print(f"Replay failed ({type(error).__name__}). Check CSV, server, bucket, token and retention. "
              "Earlier acknowledged batches may remain stored.", file=sys.stderr)
        if isinstance(error, (ValueError, OSError, KeyError)):
            print(str(error), file=sys.stderr)
        return 1
    return 0
