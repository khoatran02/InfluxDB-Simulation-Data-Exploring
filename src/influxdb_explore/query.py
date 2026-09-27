"""Run a Flux file and print annotated CSV. Files use the configured bucket."""
import argparse
import json
import sys
from pathlib import Path

from influxdb_client import InfluxDBClient

from .config import add_connection_args


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    add_connection_args(parser)
    args = parser.parse_args(argv)
    try:
        # A JSON string safely quotes the bucket as a Flux string literal.
        # Also escape Flux interpolation, which JSON itself does not escape.
        bucket = json.dumps(args.bucket).replace("${", r"\${")
        script = args.file.read_text(encoding="utf-8").replace('bucket = "agriculture"', f"bucket = {bucket}")
        with InfluxDBClient(url=args.url, token=args.token, org=args.org, timeout=60_000) as client:
            result = client.query_api().query_raw(script, org=args.org)
            if isinstance(result, str):
                print(result, end="")
            else:
                with result:
                    print(result.read().decode("utf-8"), end="")
    except Exception as error:
        print(f"Query failed ({type(error).__name__}). Check the Flux file, connection and credentials.", file=sys.stderr)
        return 1
    return 0
