import json, csv, statistics

# bt_facilities.geojson
with open("data/processed/bt_facilities.geojson") as f:
    bt = json.load(f)
print("BT FACILITIES:")
for feat in bt["features"][:3]:
    p = feat["properties"]
    print("  name=%s pre=%.0f post=%.0f pct=%.2f resid=%.0f" % (
        p.get("name","?"), p.get("pre_avg",0), p.get("post_avg",0),
        p.get("diversion_pct",0), p.get("diversion_residual",0)))

# traffic_diversion.json - check if any facility has forecast
with open("data/processed/traffic_diversion.json") as f:
    td = json.load(f)
print("\nTRAFFIC DIVERSION facilities with data:")
for name, fac in td["facilities"].items():
    pre = fac.get("pre_avg", 0)
    post = fac.get("post_avg", 0)
    fc = fac.get("forecast", [])
    fa = round(statistics.mean(fc)) if fc else None
    print("  %s: pre=%.0f post=%.0f forecast_n=%d forecast_avg=%s" % (
        name, pre, post, len(fc), fa))

# lga_weather_daily.csv - check structure and storm days
print("\nWEATHER CSV structure (first 3 rows):")
with open("data/processed/lga_weather_daily.csv") as f:
    reader = csv.DictReader(f)
    headers = reader.fieldnames
    print("  headers:", headers)
    rows = list(reader)
    for r in rows[:3]:
        print("  ", {k:v for k,v in r.items()})

# Check storm dates (precip > 0 and temp < 0)
print("\nStorm dates (precip>0 and mean_temp<0 C):")
with open("data/processed/lga_weather_daily.csv") as f:
    reader = csv.DictReader(f)
    for r in reader:
        date = r.get("date", r.get("DATE", ""))
        # Try various column names for temp and precip
        temp_cols = [k for k in headers if "temp" in k.lower() or "tmp" in k.lower()]
        precip_cols = [k for k in headers if "prcp" in k.lower() or "precip" in k.lower()]
        if temp_cols and precip_cols:
            try:
                temp = float(r[temp_cols[0]])
                precip = float(r[precip_cols[0]])
                if precip > 0 and temp < 0 and date >= "2025-01":
                    print("  %s: temp=%.1f precip=%.2f" % (date, temp, precip))
            except (ValueError, TypeError):
                pass
