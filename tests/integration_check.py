"""Explicit integration check: creates and deletes ONLY its own temporary buckets."""
import json
import math
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from influxdb_explore.dataset import DEFAULT_CSV, load_dataset

ROOT = Path(__file__).resolve().parents[1]


def main():
    name = "course-check-" + uuid.uuid4().hex[:12]
    org = os.getenv("INFLUXDB_ORG", "my-org")
    url = os.getenv("INFLUXDB_URL", "http://localhost:8086")
    token = os.getenv("INFLUXDB_TOKEN", "my-token")
    evidence = {"server_version": None, "checks": {}}
    with InfluxDBClient(url=url, token=token, org=org, timeout=60_000) as client:
        evidence["server_version"] = client.health().version
        api = client.buckets_api()
        bucket = api.create_bucket(bucket_name=name, org=org, retention_rules=[])
        target = None
        try:
            query = client.query_api()
            env = {**os.environ, "INFLUXDB_BUCKET": name}

            def run_replay(*args):
                start = time.perf_counter()
                subprocess.run([sys.executable, "-c", "from influxdb_explore.replay import main; raise SystemExit(main())", *args],
                               cwd=ROOT, env=env, check=True)
                return round(time.perf_counter() - start, 3)

            def records(script):
                return [r for table in query.query(script, org=org) for r in table.records]

            def count(mode):
                return sum(r.get_value() for r in records(
                    f'from(bucket: "{name}") |> range(start: 0) '
                    f'|> filter(fn: (r) => r._measurement == "agriculture" and r.mode == "{mode}" and r._field == "temperature") |> count()'))

            run_replay("--interval", "0", "--max-rows", "13", "--batch-size", "5")
            assert count("live") == 13, "Rapid replay or final partial batch lost points"
            evidence["checks"]["fast_live_and_partial_batch_count"] = 13
            duration = run_replay("--preserve-time", "--interval", "0", "--batch-size", "500")
            rows, profile = load_dataset(DEFAULT_CSV)
            assert count("historical") == len(rows)
            evidence["checks"]["historical_count"] = count("historical")
            evidence["historical_import_process_seconds"] = duration
            run_replay("--preserve-time", "--interval", "0", "--batch-size", "500")
            assert count("historical") == len(rows), "Repeated historical import was not idempotent"
            evidence["checks"]["historical_reimport_count"] = count("historical")
            result = records(f'from(bucket: "{name}") |> range(start: 0) '
                             '|> filter(fn: (r) => r._measurement == "agriculture" and r.mode == "historical" and r._field == "temperature") |> mean()')
            expected = sum(r.fields["temperature"] for r in rows) / len(rows)
            assert math.isclose(result[0].get_value(), expected, rel_tol=1e-12)
            evidence["checks"]["temperature_mean_matches_csv"] = result[0].get_value()
            sizes = {}
            for path in sorted((ROOT / "queries").glob("0[1-6]*.flux")):
                script = path.read_text().replace('bucket = "agriculture"', f'bucket = "{name}"')
                result = records(script)
                assert result, f"Empty query result: {path.name}"
                sizes[path.name] = len(result)
            evidence["checks"]["query_result_rows"] = sizes
            # Exercise the actual query CLI, including a non-default bucket.
            result = subprocess.run([sys.executable, "-c", "from influxdb_explore.query import main; raise SystemExit(main())",
                                     "queries/02_historical_count.flux"], cwd=ROOT, env=env, check=True, capture_output=True, text=True)
            assert str(len(rows)) in result.stdout
            evidence["checks"]["query_cli"] = "passed"
            # Demonstrate server duplicate semantics independently of the importer.
            with client.write_api(write_options=SYNCHRONOUS) as writer:
                writer.write(name, org, [Point("duplicate_demo").field("value", 1.0).time(1704067200000000000),
                                         Point("duplicate_demo").field("value", 2.0).time(1704067200000000000)])
            result = records(f'from(bucket: "{name}") |> range(start: 2024-01-01T00:00:00Z, stop: 2024-01-02T00:00:00Z) '
                             '|> filter(fn: (r) => r._measurement == "duplicate_demo")')
            assert len(result) == 1 and result[0].get_value() == 2.0
            evidence["checks"]["same_timestamp_overwrite"] = "2 writes -> 1 stored point, value=2.0"
            # Validate the task on a completed historical hour using a controlled now().
            target = api.create_bucket(bucket_name=name + "-hourly", org=org, retention_rules=[])
            script = (ROOT / "queries/07_downsample_task.flux").read_text()
            script = script.replace('bucket = "agriculture"', f'bucket = "{name}"')
            script = script.replace('"agriculture_hourly"', f'"{name}-hourly"').replace('org: "my-org"', f'org: {json.dumps(org)}')
            script = script.replace('r.mode == "live"', 'r.mode == "historical"')
            script = script.replace('bucket = ', 'option now = () => 2024-01-01T02:05:00Z\nbucket = ', 1)
            records(script)
            result = records(f'from(bucket: "{name}-hourly") |> range(start: 2024-01-01T00:00:00Z, stop: 2024-01-01T03:00:00Z)')
            assert result, "Downsample query did not persist aggregates"
            evidence["checks"]["downsample_write_rows"] = len(result)
            evidence["dataset_sha256"] = profile["sha256"]
        finally:
            if target:
                api.delete_bucket(target)
            api.delete_bucket(bucket)
    destination = ROOT / "reports/integration-results.json"
    destination.write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"Integration checks passed; temporary buckets deleted. Evidence: {destination}")


if __name__ == "__main__":
    main()
