
bucket = "agriculture"
from(bucket: bucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "agriculture" and r.mode == "history")
  |> filter(fn: (r) => r._field == "temperature" or r._field == "humidity")
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
