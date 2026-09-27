// Count ONE complete field to count observations, rather than all field values.
bucket = "agriculture"
from(bucket: bucket)
  |> range(start: 2023-11-27T00:00:00Z, stop: 2024-03-31T00:00:00Z)
  |> filter(fn: (r) => r._measurement == "agriculture" and r.mode == "historical")
  |> filter(fn: (r) => r._field == "temperature")
  |> group()
  |> count()
  |> yield(name: "observation_count")
