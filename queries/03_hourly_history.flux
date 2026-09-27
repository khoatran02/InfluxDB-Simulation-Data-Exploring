bucket = "agriculture"
from(bucket: bucket)
  |> range(start: 2023-11-27T00:00:00Z, stop: 2024-03-31T00:00:00Z)
  |> filter(fn: (r) => r._measurement == "agriculture" and r.mode == "historical")
  |> filter(fn: (r) => r._field == "temperature" or r._field == "humidity" or r._field == "water_level")
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
  |> yield(name: "hourly_mean")
