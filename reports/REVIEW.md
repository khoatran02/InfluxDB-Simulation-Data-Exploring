# Project review and verification

Reviewed 2026-09-27. Scope: every project source/configuration/documentation file, dependency manifest/lockfile, the complete CSV, and the dataset archive. Generated virtual-environment files and bytecode were inspected as environment artifacts, not treated as authored project source. The archive contains the same CSV bytes as the extracted file.

## Findings and changes

| Priority | Original finding | Resolution |
| --- | --- | --- |
| High | `uv build` failed because `src/influxdb_explore/__init__.py` was missing. An existing environment let `uv sync` appear successful. | Added the actual package and three installed CLI commands; built source and wheel distributions successfully. |
| High | README/guide invoked a root script that did not exist; the script in `src/` resolved its CSV under the wrong directory. | Corrected source-relative dataset path, documented installed commands, kept `src/real-time-simulate.py` as a compatibility launcher. |
| High | Second-resolution point timestamps silently merged rapid live observations. | Nanosecond writes with strictly increasing live timestamps within one process. |
| High | Historical duplicate dates could overwrite differing sensor readings. | Deterministic timestamp offsets with original source time and CSV line as provenance fields. No valid observations are discarded. |
| High | Guide claimed February–August 2024; its historical range omitted real observations. | Full-file profile established November 2023–March 2024; query windows and documentation corrected. |
| Medium | Validation only checked date-column presence and skipped empty dates; NaN, bad numbers, and malformed actuator pairs were not checked before writing. | Whole-file validation before ingestion, explicit skipped-row reporting, optional strict mode, tested error handling. |
| Medium | `--max-rows` accepted zero/negative values and interval allowed non-finite numbers. | Argument validation and invalid-combination tests. |
| Medium | Docker image credentials were baked into a custom image; README used `latest`; readiness was assumed after a short sleep. | Pinned 2.7.12 image, runtime configuration, ignored `.env`, localhost binding, health check, `compose --wait`. |
| Medium | Guide recommended selecting an unrelated active virtual environment and implied fixes had been committed. | Project-based `uv run`, actual package build verification, removed unsupported commit claims. |
| Medium | “Count points” and “last points” examples ignored Flux per-field tables and ordering. | Count one complete field; explicit `last()` query and explained table behavior. |
| Medium | Project lacked reproducible analysis exercises, data-quality evidence, or checks of stored results. | Six read-only Flux files, optional task, offline tests, temporary-bucket integration test and JSON evidence. |
| Low | Unsupported universal throughput claim and misleading fixed five-minute cadence. | Documented local measurement limits and actual irregular timestamp gaps. |

The checkout had no commits and all authored files were untracked at review time. Changes were made in place without creating a commit or replacing the Git repository. Existing database data and source CSV/archive were preserved.

## Implemented behavior

- `influx-profile`: validates the CSV and exports a reproducible profile, including its SHA-256.
- `influx-replay`: live replay, historical import, synchronous batching, dry-run preview, strict validation, timezone selection, and source provenance.
- `influx-query`: runs the supplied Flux files against the configured bucket and exports actual annotated CSV.
- Compose: version-pinned InfluxDB, persistent volumes, environment-based initialization, and health check.
- Guide: schema rationale, complete lab, dashboard creation, optional task/retention lab, report outline, experiments, and presentation timing.

Historical imports are idempotent for an unchanged file and configuration. Live replay is intentionally append-only across runs. Timestamp uniqueness is coordinated only within one live process. Nanosecond offsets are an explicit storage policy, not recovered device identities or sensor accuracy.

## Verified results

See [dataset-profile.json](dataset-profile.json) and [integration-results.json](integration-results.json) for machine-readable evidence.

| Check | Result |
| --- | --- |
| Python package | `uv build` produced source distribution and wheel |
| Dependency lock | `uv sync --locked` and `uv lock --check` passed |
| Offline regression suite | 7 tests passed |
| Compose validation | `docker compose config --quiet` passed |
| Fresh initialization | Separate Compose project on localhost:18086 reached healthy state using new volumes |
| Server | InfluxDB v2.7.12 |
| Fast replay/final batch | 13 requested rows, batch size 5, 13 stored observations |
| Complete historical import | 37,920 stored observations |
| Reimport | Still 37,920 observations |
| Temperature mean | 18.76004746835443, matches direct CSV calculation |
| Read-only Flux examples | All six returned data |
| Query CLI | Correctly exported the historical count as CSV |
| Native duplicate-point experiment | Two same-identity writes yielded one point with the second value |
| Optional downsample query | Six aggregates written under controlled test time |
| Archive integrity | Extracted CSV exactly matches its ZIP member |

Integration checks ran against the existing server using new disposable buckets and against the isolated fresh instance. The fresh instance used the same Compose definition with only the container name and host port overridden. Temporary buckets, test container, test network, and test volumes were removed after verification. The original `influxdb` container and its volumes were retained.

During validation, the installed Python client's `query_raw()` returned an HTTP response object despite its string-oriented docstring. The query CLI was corrected to read/decode the response, and the actual CLI output was checked in integration tests.

Import time in the JSON is the local subprocess wall time, including validation/startup; it is not a portable throughput benchmark. Dashboard interaction and an actual scheduled hourly task execution were not automated. The downsampling Flux expression and persistence path were tested with controlled time and a temporary target bucket.

## Remaining submission work

1. Supply the exact course version/deliverables/rubric so this implementation can be checked against them. The current scope follows the existing InfluxDB v2 project.
2. Add the original dataset citation, license, units, and timezone if available from its provider. These facts cannot be established from the CSV alone.
3. Follow the dashboard instructions and capture screenshots; record a short live demo if required.
4. Turn the report outline into the course's required format and prepare slides if assigned. Insert actual observations and label assumptions.

No AI prediction, physical-sensor connection, external notification delivery, dataset provenance verification, or comparative benchmark is claimed by this implementation.

## Official technical references

- [InfluxDB v2 installation](https://docs.influxdata.com/influxdb/v2/install/)
- [Point identity and duplicates](https://docs.influxdata.com/influxdb/v2/write-data/best-practices/duplicate-points/)
- [InfluxDB v2 schema design](https://docs.influxdata.com/influxdb/v2/write-data/best-practices/schema-design/)
- [Flux aggregateWindow](https://docs.influxdata.com/flux/v0/stdlib/universe/aggregatewindow/)
- [InfluxDB tasks](https://docs.influxdata.com/influxdb/v2/process-data/get-started/)
