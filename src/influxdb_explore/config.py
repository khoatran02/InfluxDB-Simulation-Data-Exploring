"""Shared CLI connection settings (CLI > environment > local demo defaults)."""
import os


def add_connection_args(parser):
    for name, default in (
        ("url", "http://localhost:8086"),
        ("org", "my-org"),
        ("bucket", "agriculture"),
        ("token", "my-token"),
    ):
        parser.add_argument(f"--{name}", default=os.getenv(f"INFLUXDB_{name.upper()}", default))
