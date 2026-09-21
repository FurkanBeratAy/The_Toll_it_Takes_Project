import json, csv, statistics

with open("data/processed/crz_daily.json") as f:
    crz = json.load(f)
dates = crz["dates"]
total = crz["total"]

# Find days >30% below 7-day average (i.e. < 70% of avg7)
print("CRZ days >30% below 7-day rolling avg:")
storm_dates = []
for i, (d, v) in enumerate(zip(dates, total)):
    if i < 6: continue
    w = total[i-6:i+1]  # 7-day window including current
    avg7 = sum(w)/len(w)
    if v < avg7 * 0.70:
        pct_below = (1 - v/avg7) * 100
        storm_dates.append((d, v, avg7, pct_below))
        print("  %s: %d (7d_avg=%d, %.0f%% below)" % (d, v, avg7, pct_below))

# Load weather for context
weather = {}
with open("data/processed/lga_weather_daily.csv") as f:
    reader = csv.DictReader(f)
    for r in reader:
        weather[r["date"]] = {"temp": float(r["temp_c"]), "precip": float(r["precip_mm"])}

print("\nWith weather context:")
for d, v, avg7, pct in storm_dates:
    w = weather.get(d, {})
    is_storm = w.get("precip", 0) > 2 and w.get("temp", 10) < 0
    label = "WINTER STORM" if is_storm else ("cold day" if w.get("temp", 10) < 0 else "other")
    print("  %s: %.0f%% below | temp=%.1f precip=%.1f | %s" % (
        d, pct, w.get("temp",999), w.get("precip",0), label))

# Traffic diversion - check what's in traffic_diversion.json more carefully
with open("data/processed/traffic_diversion.json") as f:
    td = json.load(f)
fac = td["facilities"]
first_name = list(fac.keys())[0]
print("\nFirst facility all keys:", list(fac[first_name].keys()))
for k, v in fac[first_name].items():
    if not isinstance(v, list):
        print("  %s: %s" % (k, v))
    else:
        print("  %s: list of %d items" % (k, len(v)))

# bt_facilities first feature all properties
with open("data/processed/bt_facilities.geojson") as f:
    bt = json.load(f)
print("\nbt_facilities first feature props:", dict(bt["features"][0]["properties"]))
