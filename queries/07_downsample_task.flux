// Optional task: create agriculture_hourly first, then paste into Tasks > Create.
// This processes LIVE data only. It does not backfill the 2023/2024 history.
import "date"

option task = {name: "agriculture-hourly", every: 1h, offset: 5m}
bucket = "agriculture"
from(bucket: bucket)
  |> range(start: date.sub(d: 2h, from: date.truncate(t: now(), unit: 1h)), stop: date.truncate(t: now(), unit: 1h))
  |> filter(fn: (r) => r._measurement == "agriculture" and r.mode == "live")
  |> filter(fn: (r) => r._field == "temperature" or r._field == "humidity" or r._field == "water_level")
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
  |> to(bucket: "agriculture_hourly", org: "my-org")
