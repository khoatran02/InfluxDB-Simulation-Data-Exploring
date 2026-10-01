"""Extend IoT agriculture dataset to 80k+ rows (Option A: forward timeline extension).

Strategy: clean -> fit hourly profiles + sensor correlations -> extend 5-min
cadence past max(date) -> rule-based actuators w/ flip noise -> validate -> CSV.
Stdlib + numpy only.
"""
import csv
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np

SRC = "/home/workspace/works/projects/school/Master/AI-IoT/influxdb-explore/datasets/iot-agriculture-2024/IoTProcessed_Data.csv"
DST = "/home/workspace/works/projects/school/Master/AI-IoT/influxdb-explore/datasets/iot-agriculture-2024/IoTProcessed_Data_80k.csv"
TARGET_ROWS = 82_000  # margin above 80k
STEP = timedelta(minutes=5)
FLIP_P = 0.05
SEED = 42

rng = np.random.default_rng(SEED)
FMT = "%Y-%m-%d %H:%M:%S"

# ---------- 1. Load + clean ----------
rows = []
with open(SRC, newline="") as f:
    for r in csv.DictReader(f):
        if not r["date"] or not r["date"].strip():
            continue  # drop empty timestamps
        try:
            ts = datetime.strptime(r["date"].strip(), FMT)
        except ValueError:
            continue
        rows.append({
            "date": ts,
            "tempreature": float(r["tempreature"]),
            "humidity": min(max(float(r["humidity"]), 0.0), 100.0),
            "water_level": min(max(float(r["water_level"]), 0.0), 100.0),
            "N": min(float(r["N"]), 255.0),  # clip sensor glitch (K=259 seen)
            "P": min(float(r["P"]), 255.0),
            "K": min(float(r["K"]), 255.0),
            "fan_on": int(float(r["Fan_actuator_ON"]) > 0.5),
            "watering_on": int(float(r["Watering_plant_pump_ON"]) > 0.5),
            "pump_on": int(float(r["Water_pump_actuator_ON"]) > 0.5),
        })
# dedupe + sort
seen, clean = set(), []
for r in rows:
    if r["date"] not in seen:
        seen.add(r["date"])
        clean.append(r)
clean.sort(key=lambda r: r["date"])
print(f"clean rows: {len(clean)} (dropped {len(rows) - len(clean)} dup/empty)")

# ---------- 2. Fit profiles ----------
# hourly mean/std for temp & humidity (captures daily cycle)
hour_temp = defaultdict(list)
hour_hum = defaultdict(list)
for r in clean:
    hour_temp[r["date"].hour].append(r["tempreature"])
    hour_hum[r["date"].hour].append(r["humidity"])
h_mean = {h: statistics.mean(v) for h, v in hour_temp.items()}
h_std = {h: statistics.stdev(v) if len(v) > 1 else 1.0 for h, v in hour_temp.items()}
m_mean = {h: statistics.mean(v) for h, v in hour_hum.items()}
m_std = {h: statistics.stdev(v) if len(v) > 1 else 2.0 for h, v in hour_hum.items()}

# temp->humidity linear coupling (temp up => humidity down)
temps = np.array([r["tempreature"] for r in clean])
hums = np.array([r["humidity"] for r in clean])
slope, intercept = np.polyfit(temps, hums, 1)
temp_mean = float(np.mean(temps))
hum_mean = float(np.mean(hums))
hum_resid = hums - (slope * temps + intercept)
resid_std = float(np.std(hum_resid))
print(f"humidity|temp: slope={slope:.2f} intercept={intercept:.1f} resid_std={resid_std:.2f}")

# water_level: mean-reverting walk around the pump threshold so the pump
# cycles; pump ON drains, OFF refills slowly
wl_vals = np.array([r["water_level"] for r in clean])
WL_TARGET = 70.0  # near pump_t so level oscillates across it

# NPK discrete pools + rare-change behaviour
npk_pools = {k: sorted({r[k] for r in clean}) for k in ("N", "P", "K")}
print("NPK pools:", {k: v for k, v in npk_pools.items()})

# actuator thresholds: P(actuator ON | sensor decile) -> pick threshold maximizing Youden J
def best_threshold(sensor_vals, on_vals):
    s, o = np.array(sensor_vals), np.array(on_vals)
    best, best_j = None, -1
    for t in np.quantile(s, np.linspace(0.05, 0.95, 19)):
        pred = s > t
        tp = np.sum(pred & (o == 1)); fn = np.sum(~pred & (o == 1))
        tn = np.sum(~pred & (o == 0)); fp = np.sum(pred & (o == 0))
        j = (tp / max(tp + fn, 1)) - (fp / max(fp + tn, 1))
        if j > best_j:
            best, best_j = float(t), j
    return best

fan_t = best_threshold([r["tempreature"] for r in clean], [r["fan_on"] for r in clean])
pump_t = best_threshold([-r["water_level"] for r in clean], [r["pump_on"] for r in clean])
pump_t = -pump_t
# watering pump tied to humidity (dry -> water); use low-humidity side
wat_t = best_threshold([-r["humidity"] for r in clean], [r["watering_on"] for r in clean])
wat_t = -wat_t
print(f"thresholds: fan ON if temp>{fan_t:.1f} | pump ON if wl<{pump_t:.1f} | watering ON if hum<{wat_t:.1f}")

# ---------- 3. Extend timeline ----------
need = TARGET_ROWS - len(clean)
start = clean[-1]["date"] + STEP
print(f"generating {need} rows from {start.strftime(FMT)}")

# AR(1) state for smooth noise
ar_temp, ar_wl = 0.0, 0.0
wl = float(np.median(wl_vals))
npk = {k: clean[-1][k] for k in ("N", "P", "K")}
npk_hold = {k: 0 for k in npk}  # countdown until next allowed change

new_rows = []
for i in range(need):
    ts = start + i * STEP
    h = ts.hour
    # temperature: hourly profile + AR(1) smoothness + white noise
    ar_temp = 0.85 * ar_temp + rng.normal(0, h_std.get(h, 1.5) * 0.5)
    temp = h_mean.get(h, 19.0) + ar_temp + rng.normal(0, 0.4)
    temp = float(np.clip(temp, 3.0, 41.0))
    # humidity: mean-anchored coupling to temp + hourly deviation + noise
    hum = (hum_mean + slope * (temp - temp_mean)
           + (m_mean.get(h, hum_mean) - hum_mean) * 0.5
           + rng.normal(0, resid_std * 0.6))
    hum = float(np.clip(hum, 0.0, 100.0))
    # water_level: oscillate around WL_TARGET so pump cycles;
    # pump ON drains, OFF refills
    pump_hint = wl < pump_t
    ar_wl = 0.9 * ar_wl + rng.normal(0, 1.2)
    wl += ((WL_TARGET - wl) * 0.02 + ar_wl * 0.3
           + (-4.0 if pump_hint else 1.5))
    wl = float(np.clip(wl, 0.0, 100.0))
    # NPK: hold long, change rarely to another observed discrete value
    for k in npk:
        if npk_hold[k] <= 0:
            if rng.random() < 0.02:  # ~2% chance per step to change
                npk[k] = float(rng.choice(npk_pools[k]))
                npk_hold[k] = int(rng.integers(200, 2000))  # hold ~1-7 days
        else:
            npk_hold[k] -= 1
    # actuators: rules + flip noise, enforce ON+OFF=1
    fan_on = int(temp > fan_t)
    pump_on = int(wl < pump_t)
    wat_on = int(hum < wat_t)
    for key in ("fan_on", "pump_on", "wat_on"):
        pass
    if rng.random() < FLIP_P:
        fan_on ^= 1
    if rng.random() < FLIP_P:
        pump_on ^= 1
    if rng.random() < FLIP_P:
        wat_on ^= 1
    new_rows.append({
        "date": ts, "tempreature": round(temp, 1), "humidity": round(hum, 1),
        "water_level": round(wl, 1), "N": npk["N"], "P": npk["P"], "K": npk["K"],
        "fan_on": fan_on, "watering_on": wat_on, "pump_on": pump_on,
    })

# ---------- 4. Write merged CSV (original column names kept) ----------
with open(DST, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["date", "tempreature", "humidity", "water_level", "N", "P", "K",
                "Fan_actuator_OFF", "Fan_actuator_ON",
                "Watering_plant_pump_OFF", "Watering_plant_pump_ON",
                "Water_pump_actuator_OFF", "Water_pump_actuator_ON"])
    for r in clean:
        w.writerow([r["date"].strftime(FMT), r["tempreature"], r["humidity"],
                    r["water_level"], r["N"], r["P"], r["K"],
                    1 - r["fan_on"], r["fan_on"],
                    1 - r["watering_on"], r["watering_on"],
                    1 - r["pump_on"], r["pump_on"]])
    for r in new_rows:
        w.writerow([r["date"].strftime(FMT), r["tempreature"], r["humidity"],
                    r["water_level"], r["N"], r["P"], r["K"],
                    1 - r["fan_on"], r["fan_on"],
                    1 - r["watering_on"], r["watering_on"],
                    1 - r["pump_on"], r["pump_on"]])

# ---------- 5. Validate ----------
all_temp = [r["tempreature"] for r in clean] + [r["tempreature"] for r in new_rows]
syn_temp = [r["tempreature"] for r in new_rows]
print(f"\nWROTE {DST}")
print(f"total rows: {len(clean) + len(new_rows)}")
print(f"temp real mean/std {statistics.mean([r['tempreature'] for r in clean]):.2f}/{statistics.stdev([r['tempreature'] for r in clean]):.2f} "
      f"vs synth {statistics.mean(syn_temp):.2f}/{statistics.stdev(syn_temp):.2f}")
print(f"actuator ON-rates real vs synth: fan "
      f"{statistics.mean([r['fan_on'] for r in clean]):.2f}/{statistics.mean([r['fan_on'] for r in new_rows]):.2f}, "
      f"watering {statistics.mean([r['watering_on'] for r in clean]):.2f}/{statistics.mean([r['watering_on'] for r in new_rows]):.2f}, "
      f"pump {statistics.mean([r['pump_on'] for r in clean]):.2f}/{statistics.mean([r['pump_on'] for r in new_rows]):.2f}")
print(f"new date range: {new_rows[0]['date']} -> {new_rows[-1]['date']}")
