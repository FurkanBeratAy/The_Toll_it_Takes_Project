"""
Assemble final headline_stats.json from all processed outputs.
Also validates that all expected files exist before the HTML loads them.
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from config import PROCESSED_DIR

import numpy as np


EXPECTED_FILES = [
    "crz_boundary.geojson",
    "monitor_stations.geojson",
    "bt_facilities.geojson",
    "dac_tracts_nyc.geojson",
    "pollution_daily.json",
    "its_results.json",
    "traffic_diversion.json",
    "crz_daily.json",
    "canyon_analysis.json",
    "corridor_trees.geojson",
    "corridor_buildings.geojson",
]

OPTIONAL_FILES = [
    "nyccas_raster_points.geojson",
    "corridor_streets.geojson",
]


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    print("=== Checking expected outputs ===")
    missing = []
    for fname in EXPECTED_FILES:
        p = PROCESSED_DIR / fname
        if p.exists():
            size_kb = p.stat().st_size // 1024
            print(f"  ✓ {fname} ({size_kb} KB)")
        else:
            print(f"  ✗ MISSING: {fname}")
            missing.append(fname)

    for fname in OPTIONAL_FILES:
        p = PROCESSED_DIR / fname
        status = "✓" if p.exists() else "○ (optional, skip)"
        print(f"  {status} {fname}")

    # ─── Headline stats ─────────────────────────────────────────────────── #
    its_path = PROCESSED_DIR / "its_results.json"
    if its_path.exists():
        its = json.loads(its_path.read_text())
        hl  = its.get("headline", {})
    else:
        hl = {}

    # Traffic diversion summary
    td_path = PROCESSED_DIR / "traffic_diversion.json"
    if td_path.exists():
        td = json.loads(td_path.read_text())
        facs = td.get("facilities", {})
        # RFK Bridge / Throgs Neck / Whitestone: Bronx-relevant
        bronx_facs = {k: v for k, v in facs.items() if v.get("bronx_relevant")}
        if bronx_facs:
            bronx_avg_change = np.mean([v["diversion_pct"] for v in bronx_facs.values()])
        else:
            bronx_avg_change = 0.0
        # Facility with largest positive residual = most diverted traffic
        ranked = sorted(facs.items(), key=lambda x: x[1].get("diversion_residual", 0),
                        reverse=True)
        worst_td = ranked[0] if ranked else (None, {})
        best_td  = ranked[-1] if ranked else (None, {})
    else:
        bronx_avg_change = 0.0
        worst_td = (None, {})
        best_td  = (None, {})

    # CRZ daily totals summary
    crz_path = PROCESSED_DIR / "crz_daily.json"
    if crz_path.exists():
        crz = json.loads(crz_path.read_text())
        crz_totals = crz.get("total", [])
        crz_avg_daily = int(np.mean(crz_totals)) if crz_totals else 0
    else:
        crz_avg_daily = 0

    headline = {
        "citywide_pm25_change_pct": hl.get("citywide_pm25_change_pct", 0),
        "worst_corridor": {
            "name":   hl.get("worst_site", "—"),
            "beta_post_ug_m3": hl.get("worst_beta", 0),
        },
        "best_corridor": {
            "name":   hl.get("best_site", "—"),
            "beta_post_ug_m3": hl.get("best_beta", 0),
        },
        "part2_site":  hl.get("part2_site", "Cross_Bronx_Expy"),
        "bronx_bridges_avg_change_pct": round(float(bronx_avg_change), 2),
        "most_diverted_facility": {
            "name": worst_td[0],
            "diversion_residual": worst_td[1].get("diversion_residual", 0),
            "diversion_pct":      worst_td[1].get("diversion_pct", 0),
        },
        "crz_avg_daily_entries": crz_avg_daily,
        "toll_date": "2025-01-05",
    }

    # ─── Canyon summary ─────────────────────────────────────────────────── #
    canyon_path = PROCESSED_DIR / "canyon_analysis.json"
    if canyon_path.exists():
        canyon = json.loads(canyon_path.read_text())
        canyon_summary = {
            "site":      canyon["site"],
            "hw_ratio":  canyon["hw_ratio"],
            "discount":  canyon["canyon_discount"],
            "best_typology": max(
                canyon["typologies"].items(),
                key=lambda x: x[1]["removal_adjusted_kg_yr"]
            )[0],
        }
    else:
        canyon_summary = {}

    final = {
        "headline":       headline,
        "canyon_summary": canyon_summary,
        "data_files":     EXPECTED_FILES + OPTIONAL_FILES,
        "missing_files":  missing,
    }

    out = PROCESSED_DIR / "headline_stats.json"
    out.write_text(json.dumps(final, indent=2))
    print(f"\nSaved headline_stats.json")

    if missing:
        print(f"\n⚠ {len(missing)} expected file(s) missing — HTML will have partial data.")
    else:
        print(f"\n✓ All expected outputs present — ready to serve site/.")


if __name__ == "__main__":
    main()
