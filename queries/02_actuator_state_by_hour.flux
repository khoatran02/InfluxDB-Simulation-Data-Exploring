import "date"

bucket = "agriculture"
from(bucket: bucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) =>
    r._measurement == "agriculture" and
    r.mode == "historical" and
    (r._field == "fan_on" or r._field == "water_pump_on")
  )
  |> pivot(
    rowKey: ["_time"],
    columnKey: ["_field"],
    valueColumn: "_value"
  )
  |> map(fn: (r) => ({
    hour: date.hour(t: r._time),
    event: if r.fan_on == 1.0 and r.water_pump_on == 1.0 then
      "Fan ON + Water pump ON"
    else if r.fan_on == 1.0 then
      "Fan ON only"
    else if r.water_pump_on == 1.0 then
      "Water pump ON only"
    else
      "Both OFF",
    _value: 1
  }))
  |> group(columns: ["hour", "event"])
  |> count(column: "_value")
  |> group(columns: ["event"])
  |> sort(columns: ["hour"])