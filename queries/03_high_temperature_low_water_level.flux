from(bucket: "agriculture")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) =>
    r._measurement == "agriculture" and
    r.mode == "historical" and
    (r._field == "temperature" or
     r._field == "water_level" or
     r._field == "fan_on" or
     r._field == "watering_pump_on" or
     r._field == "source_row")
  )
  |> pivot(
    rowKey: ["_time"],
    columnKey: ["_field"],
    valueColumn: "_value"
  )
  |> filter(fn: (r) =>
    exists r.temperature and exists r.water_level and
    r.temperature > 35.0 and r.water_level < 20.0
  )
  |> keep(columns: [
    "_time", "source_row", "temperature", "water_level",
    "fan_on", "watering_pump_on"
  ])
  |> sort(columns: ["_time"])
  |> limit(n: 100)

