// Mean of 0/1 = fraction of samples ON, not time-weighted duty cycle.
bucket = "agriculture"
from(bucket: bucket)
  |> range(start: 2023-11-27T00:00:00Z, stop: 2024-03-31T00:00:00Z)
  |> filter(fn: (r) => r._measurement == "agriculture" and r.mode == "historical")
  |> filter(fn: (r) => r._field == "fan_on" or r._field == "watering_pump_on" or r._field == "water_pump_on")
  |> aggregateWindow(every: 1d, fn: mean, createEmpty: false)
  |> yield(name: "fraction_of_samples_on")
