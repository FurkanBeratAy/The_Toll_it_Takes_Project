#!/usr/bin/env python3
"""
analysis/check9_phase1.py

Check 9 — Phase 1: Find candidate PurpleAir sensors for the missing cell.

Goal: identify outside-CRZ sensors (EJ and non-EJ) with a continuous record
from at most 2024-04-01 and still active within 30 days of today (2026-09-17).
Reports point cost per sensor and current API balance, then prints the
candidate table.  Does NOT pull any history.

Saves data/raw/purpleair/phase1_candidates.json for Phase 2.
"""

import sys, json, math, os
from pathlib import Path
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# ── API key: loaded from .env, never printed ──────────────────────────────
from dotenv import load_dotenv

_ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(_ENV_PATH)
PURPLEAIR_KEY = os.environ.get("PURPLEAIR_READ_KEY", "")
if not PURPLEAIR_KEY:
    sys.exit("ERROR: PURPLEAIR_READ_KEY not set in .env")

import requests
from shapely.geometry import Point, shape

# ── Paths (relative to this script — avoids config.py BASE_DIR mismatch) ──
_PROJECT = Path(__file__).parent.parent
PROCESSED_DIR = _PROJECT / "data" / "processed"
RAW_PA_DIR    = _PROJECT / "data" / "raw" / "purpleair"

# ── Date constants ─────────────────────────────────────────────────────────
TODAY              = datetime(2026, 9, 17, tzinfo=timezone.utc)
FIRST_SEEN_CUTOFF  = datetime(2024, 4,  1, tzinfo=timezone.utc)  # on or before
LAST_SEEN_CUTOFF   = datetime(2026, 8, 18, tzinfo=timezone.utc)  # within 30 days
HISTORY_START      = datetime(2024, 2, 22, tzinfo=timezone.utc)
HISTORY_DAYS       = (TODAY - HISTORY_START).days                 # ~938

# Cost estimate: average=1440 → 1 reading/day; 3 fields (pm25_a, pm25_b, RH)
HISTORY_FIELDS     = 3
COST_PER_SENSOR    = HISTORY_FIELDS * HISTORY_DAYS

# ── PurpleAir API ──────────────────────────────────────────────────────────
BASE_URL = "https://api.purpleair.com/v1"
HEADERS  = {"X-API-Key": PURPLEAIR_KEY}

# NYC outer bounding box (PurpleAir nw/se corners)
NYC_BBOX = {
    "nwlng": -74.2591,
    "nwlat":  40.9176,
    "selng": -73.7004,
    "selat":  40.4774,
}

# Target selection counts
N_NON_EJ_TARGET = 8
N_EJ_TARGET     = 4


# ── Geometry helpers ───────────────────────────────────────────────────────

def _load_crz():
    data = json.loads((PROCESSED_DIR / "crz_boundary.geojson").read_text(encoding="utf-8"))
    return [shape(f["geometry"]) for f in data["features"]]


def _load_dac():
    data = json.loads((PROCESSED_DIR / "dac_tracts_nyc.geojson").read_text(encoding="utf-8"))
    result = []
    for f in data["features"]:
        is_dac = f["properties"].get("dac_designation") == "Designated as DAC"
        result.append((shape(f["geometry"]), is_dac))
    return result


def _in_crz(pt, crz_geoms):
    return any(g.contains(pt) for g in crz_geoms)


def _is_ej(pt, dac_tracts):
    for geom, is_dac in dac_tracts:
        if geom.contains(pt):
            return is_dac
    return False


def _borough(lat, lon):
    # Ordered so Manhattan/Bronx narrow bands are checked first
    if -74.26 <= lon <= -74.03 and 40.48 <= lat <= 40.65:
        return "Staten Island"
    if lon >= -73.93 and lat >= 40.79:
        return "Bronx"
    if lon <= -73.97 and lat >= 40.69:
        return "Manhattan"
    if lon <= -73.84 and lat <= 40.74:
        return "Brooklyn"
    if lon <= -73.70 and lat <= 40.80:
        return "Queens"
    return "NYC"


# ── Spread-maximising selection ────────────────────────────────────────────

def _haversine_deg(a, b):
    """Approximate distance in degrees (good enough for spread selection)."""
    return math.sqrt((a["lat"] - b["lat"]) ** 2 + (a["lon"] - b["lon"]) ** 2)


def _max_spread(candidates, n_target, anchor_coords):
    """
    Greedy farthest-point selection.
    anchor_coords: list of (lat, lon) already committed (NYCCAS sites).
    Returns up to n_target sensors.
    """
    if len(candidates) <= n_target:
        return list(candidates)

    def min_dist_to_set(c, selected_set):
        d_anchors = [
            _haversine_deg(c, {"lat": la, "lon": lo})
            for la, lo in anchor_coords
        ]
        d_sel = [_haversine_deg(c, s) for s in selected_set] if selected_set else []
        all_d = d_anchors + d_sel
        return min(all_d) if all_d else 9999.0

    selected = []
    remaining = list(candidates)

    # Seed: sensor farthest from all NYCCAS sites
    seed = max(remaining, key=lambda c: min_dist_to_set(c, []))
    selected.append(seed)
    remaining.remove(seed)

    while len(selected) < n_target and remaining:
        pick = max(remaining, key=lambda c: min_dist_to_set(c, selected))
        selected.append(pick)
        remaining.remove(pick)

    return selected


# ── API calls ──────────────────────────────────────────────────────────────

def _check_balance():
    r = requests.get(f"{BASE_URL}/keys", headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def _fetch_sensors():
    params = {
        "fields": ",".join([
            "sensor_index", "name", "latitude", "longitude",
            "date_created", "last_seen", "location_type",
        ]),
        "location_type": 0,
        **NYC_BBOX,
    }
    r = requests.get(f"{BASE_URL}/sensors", headers=HEADERS, params=params, timeout=45)
    r.raise_for_status()
    return r.json()


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 72)
    print("Check 9 Phase 1: PurpleAir candidate sensor search")
    print(f"  Today: {TODAY.date()}   History window: {HISTORY_START.date()} → {TODAY.date()}")
    print(f"  Cost per sensor: {HISTORY_FIELDS} fields × {HISTORY_DAYS} days = {COST_PER_SENSOR:,} points")
    print("=" * 72)

    # ── 1. Balance ─────────────────────────────────────────────────────────
    print("\n[1/4] Checking API point balance…")
    try:
        bal = _check_balance()
        # Print the raw response so we can read balance regardless of schema
        print(json.dumps(bal, indent=2))
    except Exception as exc:
        print(f"  WARNING: balance endpoint failed: {type(exc).__name__}")
        bal = {}

    # ── 2. Fetch sensor list ───────────────────────────────────────────────
    print("\n[2/4] Fetching outdoor sensors in NYC bounding box…")
    raw = _fetch_sensors()
    RAW_PA_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_PA_DIR / "phase1_raw_list.json").write_text(json.dumps(raw), encoding="utf-8")

    fields_order = raw.get("fields", [])
    data_rows    = raw.get("data", [])
    print(f"  API returned {len(data_rows)} sensors")

    # Parse into dicts
    sensors = [dict(zip(fields_order, row)) for row in data_rows]

    # ── 3. Load geometries ─────────────────────────────────────────────────
    print("\n[3/4] Loading CRZ and DAC geojson…")
    crz_geoms  = _load_crz()
    dac_tracts = _load_dac()
    dac_count  = sum(1 for _, is_dac in dac_tracts if is_dac)
    print(f"  CRZ: {len(crz_geoms)} feature(s)  |  DAC tracts: {dac_count} designated")

    # ── 4. Filter and flag ─────────────────────────────────────────────────
    print("\n[4/4] Filtering and flagging…")

    n_no_coords = n_no_ts = n_in_crz = n_too_new = n_stale = 0
    eligible = []

    for s in sensors:
        lat = s.get("latitude")
        lon = s.get("longitude")
        if lat is None or lon is None:
            n_no_coords += 1
            continue

        dc = s.get("date_created")
        ls = s.get("last_seen")
        if dc is None or ls is None:
            n_no_ts += 1
            continue

        try:
            dt_created = datetime.fromtimestamp(int(dc), tz=timezone.utc)
            dt_last    = datetime.fromtimestamp(int(ls), tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            n_no_ts += 1
            continue

        if dt_created > FIRST_SEEN_CUTOFF:
            n_too_new += 1
            continue

        if dt_last < LAST_SEEN_CUTOFF:
            n_stale += 1
            continue

        pt = Point(lon, lat)

        if _in_crz(pt, crz_geoms):
            n_in_crz += 1
            continue

        eligible.append({
            "sensor_index": s.get("sensor_index"),
            "name":         str(s.get("name", "")),
            "lat":          float(lat),
            "lon":          float(lon),
            "first_seen":   dt_created.strftime("%Y-%m-%d"),
            "last_seen":    dt_last.strftime("%Y-%m-%d"),
            "ej":           _is_ej(pt, dac_tracts),
            "borough":      _borough(float(lat), float(lon)),
        })

    print(f"  Dropped: no coords={n_no_coords}, no timestamp={n_no_ts}, "
          f"too new={n_too_new}, stale={n_stale}, in CRZ={n_in_crz}")
    print(f"  Eligible (outside CRZ, active, first_seen ≤ 2024-04-01): {len(eligible)}")

    non_ej = [s for s in eligible if not s["ej"]]
    ej_sns = [s for s in eligible if     s["ej"]]
    print(f"  Outside-zone non-EJ: {len(non_ej)}   |   Outside-zone EJ: {len(ej_sns)}")

    # ── Spread-maximising selection ────────────────────────────────────────
    # NYCCAS station coordinates as anchors
    NYCCAS_ANCHORS = [
        (40.84517, -73.90614), (40.81909, -73.88566), (40.80649, -73.92249),
        (40.70280, -73.96082), (40.71651, -73.99700), (40.71807, -73.98606),
        (40.76123, -73.96389), (40.84654, -73.93302), (40.75069, -73.98783),
        (40.75508, -73.99042), (40.72229, -73.97465), (40.73711, -73.82156),
        (40.69015, -73.80908), (40.60921, -74.15118),
    ]

    sel_non_ej = _max_spread(non_ej, N_NON_EJ_TARGET, NYCCAS_ANCHORS)
    sel_ej     = _max_spread(ej_sns, N_EJ_TARGET,     NYCCAS_ANCHORS)

    n_sel = len(sel_non_ej) + len(sel_ej)
    total_cost = n_sel * COST_PER_SENSOR

    # ── Print candidate table ──────────────────────────────────────────────
    SEP = "─" * 100
    print(f"\n{SEP}")
    print(f"  CANDIDATE TABLE  ({n_sel} selected from {len(eligible)} eligible)")
    print(f"  Point cost per sensor: {COST_PER_SENSOR:,}   |   Total if all approved: {total_cost:,}")
    print(SEP)
    HDR = f"{'#':<3} {'Cell':<8} {'Name':<36} {'ID':>7} {'Borough':<14} {'Lat':>9} {'Lon':>10} {'FirstSeen':>11} {'LastSeen':>11}"
    print(HDR)
    print("─" * len(HDR))

    n = 0
    print("  ——  Outside-zone NON-EJ sensors  ——")
    for s in sel_non_ej:
        n += 1
        print(
            f"{n:<3} {'non-EJ':<8} {s['name'][:35]:<36} {s['sensor_index']:>7} "
            f"{s['borough']:<14} {s['lat']:>9.5f} {s['lon']:>10.5f} "
            f"{s['first_seen']:>11} {s['last_seen']:>11}"
        )

    print("  ——  Outside-zone EJ sensors  ——")
    for s in sel_ej:
        n += 1
        print(
            f"{n:<3} {'EJ':<8} {s['name'][:35]:<36} {s['sensor_index']:>7} "
            f"{s['borough']:<14} {s['lat']:>9.5f} {s['lon']:>10.5f} "
            f"{s['first_seen']:>11} {s['last_seen']:>11}"
        )

    print(SEP)
    print(f"\n  Eligible pool summary:")
    print(f"    Outside-zone non-EJ:  {len(non_ej):>4} eligible  →  {len(sel_non_ej)} selected")
    print(f"    Outside-zone EJ:      {len(ej_sns):>4} eligible  →  {len(sel_ej)} selected")
    print()

    # ── Save candidates JSON ───────────────────────────────────────────────
    output = {
        "generated":          TODAY.strftime("%Y-%m-%d"),
        "history_start":      HISTORY_START.strftime("%Y-%m-%d"),
        "history_end":        TODAY.strftime("%Y-%m-%d"),
        "history_days":       HISTORY_DAYS,
        "cost_per_sensor":    COST_PER_SENSOR,
        "total_cost_selected": total_cost,
        "n_selected":         n_sel,
        "selected": {
            "non_ej": sel_non_ej,
            "ej":     sel_ej,
        },
        "all_eligible": {
            "non_ej": non_ej,
            "ej":     ej_sns,
        },
    }
    out_path = RAW_PA_DIR / "phase1_candidates.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"  Saved → {out_path.relative_to(_PROJECT)}")
    print("\nPhase 1 complete — review the table above, then approve to proceed to Phase 2.")


if __name__ == "__main__":
    main()
