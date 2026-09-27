// Live dashboard: one-minute sensor means. Set the UI range to the last 30m.
bucket = "agriculture"
from(bucket: bucket)
  |> range(start: -30m)
  |> filter(fn: (r) => r._measurement == "agriculture" and r.mode == "live")
  |> filter(fn: (r) => r._field == "temperature" or r._field == "humidity")
  |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)
  |> yield(name: "one_minute_mean")
