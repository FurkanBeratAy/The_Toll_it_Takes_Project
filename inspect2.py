import json, statistics

# Monitor stations
with open("data/processed/monitor_stations.geojson") as f:
    st = json.load(f)
print("STATIONS:")
for feat in st["features"]:
    p = feat["properties"]
    print("  name=%s significant=%s beta_post=%s p_value=%s ej=%s" % (
        p.get("name"), p.get("significant"), p.get("beta_post"), p.get("p_value"), p.get("ej_designated")))

# Traffic diversion structure
with open("data/processed/traffic_diversion.json") as f:
    td = json.load(f)
print("\nTRAFFIC FACILITIES:")
for name, fac in td["facilities"].items():
    keys = list(fac.keys())
    fc = fac.get("forecast")
    forecast_avg = round(statistics.mean(fc)) if fc else None
    print("  %s: pre=%s post=%s pct=%.2f forecast_n=%s forecast_avg=%s" % (
        name, round(fac.get("pre_avg",0)), round(fac.get("post_avg",0)),
        fac.get("diversion_pct",0), len(fc) if fc else 0, forecast_avg))

# CRZ data for computing 2025 mean
with open("data/processed/crz_daily.json") as f:
    crz = json.load(f)
dates = crz["dates"]
total = crz["total"]
vals_2025 = [total[i] for i,d in enumerate(dates) if d.startswith("2025")]
mean_2025 = round(statistics.mean(vals_2025)) if vals_2025 else 0
print("\nCRZ 2025 mean daily entries:", mean_2025)
print("MTA baseline (2025 mean + 73000):", mean_2025 + 73000)
print("Reduction pct:", round(73000/(mean_2025+73000)*100, 1))

# Check which CRZ days are >30% below 7-day rolling average
print("\nDays >30% below 7-day avg (first 10):")
count = 0
for i, (d, v) in enumerate(zip(dates, total)):
    if i < 6: continue
    w = total[max(0,i-6):i+1]
    avg7 = sum(w)/len(w)
    if v < avg7 * 0.70:
        print("  %s: %d (avg7=%d, pct=%.0f%%)" % (d, v, avg7, v/avg7*100))
        count += 1
        if count >= 10: break
