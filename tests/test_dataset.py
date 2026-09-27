import csv
import tempfile
import unittest
from pathlib import Path

from influxdb_explore.dataset import NUMERIC_COLUMNS, load_dataset
from influxdb_explore.replay import iter_points, parse_args


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "input.csv"

    def write(self, records):
        with self.path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["date", *NUMERIC_COLUMNS])
            writer.writeheader()
            for date, overrides in records:
                row = {key: "1" if key.endswith("_ON") else "0" for key in NUMERIC_COLUMNS}
                row.update(date=date, **overrides)
                writer.writerow(row)

    def test_conflicting_duplicates_preserved_and_repeatable(self):
        self.write([("2024-01-01 00:00:01", {}), ("2024-01-01 00:00:00", {"tempreature": "20"}),
                    ("2024-01-01 00:00:00", {"tempreature": "30"})])
        rows, report = load_dataset(self.path)
        again, _ = load_dataset(self.path)
        self.assertEqual(rows, again)
        self.assertEqual([r.fields["temperature"] for r in rows], [20, 30, 0])
        self.assertEqual(rows[1].timestamp_ns - rows[0].timestamp_ns, 1)
        self.assertEqual(rows[1].source_time_ns, rows[0].source_time_ns)
        self.assertEqual(report["conflicting_timestamp_groups"], 1)

    def test_invalid_rows_reported_and_strict_fails(self):
        self.write([("", {}), ("2024-01-01 00:00:00", {"humidity": "NaN"}),
                    ("2024-01-01 00:00:01", {})])
        rows, report = load_dataset(self.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual([r["csv_line"] for r in report["invalid_rows"]], [2, 3])
        with self.assertRaises(ValueError):
            load_dataset(self.path, strict=True)

    def test_missing_schema_empty_and_bad_actuator(self):
        self.path.write_text("date\n2024-01-01 00:00:00\n")
        with self.assertRaisesRegex(ValueError, "Missing CSV columns"):
            load_dataset(self.path)
        self.write([])
        with self.assertRaisesRegex(ValueError, "no valid"):
            load_dataset(self.path)
        self.write([("2024-01-01 00:00:00", {"Fan_actuator_OFF": "1"})])
        with self.assertRaisesRegex(ValueError, "invalid fan"):
            load_dataset(self.path, strict=True)

    def test_timezone_conversion(self):
        self.write([("2024-01-01 07:00:00", {})])
        utc, _ = load_dataset(self.path)
        local, _ = load_dataset(self.path, "Asia/Ho_Chi_Minh")
        self.assertEqual(utc[0].source_time_ns - local[0].source_time_ns, 7 * 3600 * 10**9)

    def test_live_points_unique_when_clock_stalls_or_moves_backwards(self):
        self.write([("2024-01-01 00:00:00", {})] * 3)
        rows, _ = load_dataset(self.path)
        clock = iter([100, 100, 90])
        args = parse_args(["--interval", "0"])
        lines = [p.to_line_protocol() for p in iter_points(rows, args, clock=lambda: next(clock))]
        self.assertEqual([int(line.rsplit(" ", 1)[1]) for line in lines], [100, 101, 102])
        self.assertIn("mode=live", lines[0])
        self.assertIn("source_row=2i", lines[0])

    def test_limit_and_loop(self):
        self.write([("2024-01-01 00:00:00", {})])
        rows, _ = load_dataset(self.path)
        args = parse_args(["--interval", "0", "--loop", "--max-rows", "3"])
        self.assertEqual(len(list(iter_points(rows, args))), 3)

    def test_cli_invalid_combinations(self):
        import contextlib
        import io
        for flags in (["--interval", "nan"], ["--interval", "-1"], ["--max-rows", "0"],
                      ["--batch-size", "0"], ["--batch-size", "10"],
                      ["--loop", "--preserve-time"], ["--loop", "--dry-run"]):
            with self.subTest(flags=flags), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    parse_args(flags)
                self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
