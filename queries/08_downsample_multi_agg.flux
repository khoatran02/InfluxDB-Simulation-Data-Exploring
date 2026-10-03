// Downsampling with several aggregate functions: raw (5 min) -> 1 hour, mean/max/min/sum.
// Each aggregate is stored as a separate field, e.g. temperature_mean, temperature_max.
// The raw bucket keeps data 7 days (short TTL); the summary bucket keeps 365 days.
// Usable as a scheduled task (Tasks > Create) or via `uv run ... influx-query`-style execution;
// benchmarks/retention_downsampling_demo.py runs it end-to-end against temporary buckets.
option task = {name: "agriculture-downsample-1h", every: 1h, offset: 5m}

rawBucket = "agriculture_raw_7d"
destBucket = "agriculture_1h_365d"
destOrg = "my-org"

raw = from(bucket: rawBucket)
  |> range(start: -2h)
  |> filter(fn: (r) => r._measurement == "agriculture")
  |> filter(fn: (r) => r._field == "temperature" or r._field == "humidity" or r._field == "water_level")

downsample = (tables=<-, fn, suffix) => tables
  |> aggregateWindow(every: 1h, fn: fn, createEmpty: false)
  |> map(fn: (r) => ({r with _field: r._field + "_" + suffix}))
  |> to(bucket: destBucket, org: destOrg)

raw |> downsample(fn: mean, suffix: "mean")
raw |> downsample(fn: max, suffix: "max")
raw |> downsample(fn: min, suffix: "min")
raw |> downsample(fn: sum, suffix: "sum")
