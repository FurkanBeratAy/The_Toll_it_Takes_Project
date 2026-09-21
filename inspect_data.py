import json

with open("data/processed/robustness.json") as f:
    r = json.load(f)

spec_a = r["check4"]["spec_a"]
print("=== SPEC_A ===")
for site, v in spec_a.items():
    pb = v.get("p_bootstrap")
    print("  %s: beta=%s p_cluster=%s p_bootstrap=%s ci=[%s,%s]" % (
        site, v.get("beta"), v.get("p"), pb, v.get("ci_low"), v.get("ci_high")))

c2 = r["check2"]
print("\n=== CHECK2 weekday ===")
for site, v in c2["weekday_only"].items():
    print("  %s: p=%s sig=%s ci=[%s,%s]" % (site, v.get("p"), v.get("significant"), v.get("ci_low"), v.get("ci_high")))

c1 = r["check1"]
print("\n=== CHECK1 n values ===")
for site, v in c1["sites"].items():
    orig = v.get("original", {})
    print("  %s: n=%s" % (site, orig.get("n")))

c7 = r["check7"]
print("\n=== CHECK7 sites ===")
for site, v in c7["sites"].items():
    print("  %s: raw25=%s vw25=%s qc25=%s vw26=%s qc26=%s" % (
        site, v.get("raw_delta_25"), v.get("minus_vw_25"), v.get("minus_qc_25"),
        v.get("minus_vw_26"), v.get("minus_qc_26")))

c5 = r["check5"]
keys5 = {k: v for k, v in c5.items() if k not in ("scatter_data", "weather_betas")}
print("\n=== CHECK5 ===")
for k, v in keys5.items():
    print("  %s: %s" % (k, v))

# ITS results - check pre-toll n
with open("data/processed/its_results.json") as f:
    its = json.load(f)
print("\n=== ITS full model n ===")
for site, v in its["sites"].items():
    full = v.get("full", {})
    print("  %s: n=%s" % (site, full.get("n")))

# Check robustness check2 all_days for each site significance
c2a = r["check2"]["all_days"]
print("\n=== CHECK2 all_days CI ===")
for site, v in c2a.items():
    sig = v.get("significant")
    ci = "[%s,%s]" % (v.get("ci_low"), v.get("ci_high"))
    print("  %s: sig=%s ci=%s p=%s" % (site, sig, ci, v.get("p")))
