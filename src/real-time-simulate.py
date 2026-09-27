#!/usr/bin/env python3
"""Compatibility entry point; prefer `uv run influx-replay`."""
from influxdb_explore.replay import main

if __name__ == "__main__":
    raise SystemExit(main())
