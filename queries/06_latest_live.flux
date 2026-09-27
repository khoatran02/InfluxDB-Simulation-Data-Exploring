bucket = "agriculture"
from(bucket: bucket)
  |> range(start: -30m)
  |> filter(fn: (r) => r._measurement == "agriculture" and r.mode == "live")
  |> filter(fn: (r) => r._field == "temperature" or r._field == "humidity" or r._field == "water_level")
  |> last()
  |> yield(name: "latest_per_field")
