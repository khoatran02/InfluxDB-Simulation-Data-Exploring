"""Validate and profile the supplied CSV without requiring a database."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# Works in the editable checkout; installed wheels can use --csv explicitly.
DEFAULT_CSV = Path(__file__).resolve().parents[2] / "datasets/iot-agriculture-2024/IoTProcessed_Data.csv"
NUMERIC_COLUMNS = {
    "tempreature": "temperature", "humidity": "humidity", "water_level": "water_level",
    "N": "nitrogen", "P": "phosphorus", "K": "potassium",
    "Fan_actuator_OFF": "fan_off", "Fan_actuator_ON": "fan_on",
    "Watering_plant_pump_OFF": "watering_pump_off",
    "Watering_plant_pump_ON": "watering_pump_on",
    "Water_pump_actuator_OFF": "water_pump_off", "Water_pump_actuator_ON": "water_pump_on",
}
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass
class Observation:
    source_row: int
    source_time_ns: int
    timestamp_ns: int
    fields: dict[str, float]


def to_ns(value: datetime) -> int:
    delta = value.astimezone(timezone.utc) - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


def load_dataset(path: Path, source_timezone: str = "UTC", strict: bool = False):
    zone = ZoneInfo(source_timezone)
    observations = []
    invalid = []
    raw_count = 0
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = {"date", *NUMERIC_COLUMNS} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing CSV columns: {', '.join(sorted(missing))}")
        for line, row in enumerate(reader, 2):
            raw_count += 1
            try:
                if None in row:
                    raise ValueError("extra CSV columns")
                # Source timestamps have no timezone. Interpret using the explicit assumption.
                dt = datetime.strptime(row["date"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=zone)
                fields = {target: float(row[source]) for source, target in NUMERIC_COLUMNS.items()}
                if not all(math.isfinite(v) for v in fields.values()):
                    raise ValueError("non-finite numeric value")
                for prefix in ("fan", "watering_pump", "water_pump"):
                    on, off = fields[f"{prefix}_on"], fields[f"{prefix}_off"]
                    if on not in (0, 1) or off not in (0, 1) or on + off != 1:
                        raise ValueError(f"invalid {prefix} ON/OFF pair")
                timestamp = to_ns(dt)
                if not -(2**63) + 2 <= timestamp <= 2**63 - 2:
                    raise ValueError("timestamp outside InfluxDB range")
                observations.append(Observation(line, timestamp, timestamp, fields))
            except (ValueError, TypeError) as error:
                invalid.append({"csv_line": line, "reason": str(error)})
    if strict and invalid:
        raise ValueError(f"{len(invalid)} invalid row(s); first: {invalid[0]}")
    if not observations:
        raise ValueError("CSV contains no valid observations")
    backwards = sum(b.source_time_ns < a.source_time_ns for a, b in zip(observations, observations[1:]))
    # Stable sort preserves source row order for equal dates; repeated imports are idempotent.
    observations.sort(key=lambda row: row.source_time_ns)
    counts = Counter(row.source_time_ns for row in observations)
    conflicts = {}
    for row in observations:
        conflicts.setdefault(row.source_time_ns, set()).add(tuple(row.fields.values()))
    last = -(2**63)
    for row in observations:
        row.timestamp_ns = max(row.source_time_ns, last + 1)
        if row.timestamp_ns > 2**63 - 2:
            raise ValueError("Disambiguated timestamp outside InfluxDB range")
        last = row.timestamp_ns
    unique = sorted(counts)
    gaps = Counter((b - a) // 1_000_000_000 for a, b in zip(unique, unique[1:]))
    report = {
        "file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_timezone_assumption": source_timezone,
        "raw_rows": raw_count, "valid_rows": len(observations), "invalid_rows": invalid,
        "start_utc": datetime.fromtimestamp(unique[0] // 1_000_000_000, timezone.utc).isoformat(),
        "end_utc": datetime.fromtimestamp(unique[-1] // 1_000_000_000, timezone.utc).isoformat(),
        "unique_source_timestamps": len(counts),
        "extra_rows_at_duplicate_timestamps": len(observations) - len(counts),
        "duplicate_timestamp_groups": sum(n > 1 for n in counts.values()),
        "conflicting_timestamp_groups": sum(len(v) > 1 for v in conflicts.values()),
        "backward_steps_in_file": backwards,
        "max_timestamp_adjustment_ns": max(r.timestamp_ns - r.source_time_ns for r in observations),
        "most_common_unique_timestamp_gaps_seconds": gaps.most_common(10),
        "fields": {field: {"min": min(r.fields[field] for r in observations),
                           "max": max(r.fields[field] for r in observations)}
                   for field in NUMERIC_COLUMNS.values()},
    }
    return observations, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--source-timezone", default="UTC")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        _, report = load_dataset(args.csv, args.source_timezone, args.strict)
        result = json.dumps(report, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(result, encoding="utf-8")
        else:
            print(result, end="")
    except (OSError, ValueError, KeyError) as error:
        print(f"Profile failed: {error}", file=sys.stderr)
        return 1
    return 0
