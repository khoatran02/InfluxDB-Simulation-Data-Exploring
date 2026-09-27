// Demonstration thresholds in dataset units; not agronomic recommendations.
bucket = "agriculture"
from(bucket: bucket)
  |> range(start: 2023-11-27T00:00:00Z, stop: 2024-03-31T00:00:00Z)
  |> filter(fn: (r) => r._measurement == "agriculture" and r.mode == "historical")
  |> filter(fn: (r) => r._field == "temperature" or r._field == "water_level" or r._field == "fan_on")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> filter(fn: (r) => r.temperature > 35.0 or r.water_level < 20.0)
  |> sort(columns: ["_time"])
  |> limit(n: 20)
