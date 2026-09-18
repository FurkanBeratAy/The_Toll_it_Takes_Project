#!/usr/bin/env python3
"""
analysis/check9_phase1_revised.py

Phase 1 (revised) per user decisions:
  - Drop NJ sensors; restrict to the five NYC boroughs via point-in-polygon
    against official NYC borough boundaries.
  - Correct FA-O5 borough (East Harlem, Manhattan).
  - Keep user-specified sensors; fill non-EJ cell using priority rules.
  - Report point cost per sensor, total, and API balance.
"""

import sys, json, os
from pathlib import Path
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from dotenv import load_dotenv
_ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(_ENV_PATH)
PURPLEAIR_KEY = os.environ.get("PURPLEAIR_READ_KEY", "")
if not PURPLEAIR_KEY:
    sys.exit("ERROR: PURPLEAIR_READ_KEY not set in .env")

import requests
from shapely.geometry import Point, shape

_PROJECT      = Path(__file__).parent.parent
PROCESSED_DIR = _PROJECT / "data" / "processed"
RAW_PA_DIR    = _PROJECT / "data" / "raw" / "purpleair"
RAW_PA_DIR.mkdir(parents=True, exist_ok=True)

TODAY          = datetime(2026, 9, 17, tzinfo=timezone.utc)
HISTORY_START  = datetime(2024, 2, 22, tzinfo=timezone.utc)
HISTORY_DAYS   = (TODAY - HISTORY_START).days          # 938
HISTORY_FIELDS = 3   # pm2.5_cf_1_a, pm2.5_cf_1_b, humidity
COST_PER_SENSOR = HISTORY_FIELDS * HISTORY_DAYS

BASE_URL = "https://api.purpleair.com/v1"
HEADERS  = {"X-API-Key": PURPLEAIR_KEY}

# NYC borough boundary — try ArcGIS Feature Service first (most stable),
# then NYC Open Data Socrata GeoJSON as fallback.
BORO_URLS = [
    # ArcGIS REST (NYC Planning, WGS84 out) — outFields=* required; property is BoroName
    ("https://services5.arcgis.com/GfwWNkhOj9bNBqoJ/arcgis/rest/services"
     "/NYC_Borough_Boundary/FeatureServer/0/query"
     "?where=1%3D1&outFields=*&outSR=4326&f=geojson"),
]
BORO_CACHE = RAW_PA_DIR / "nyc_boroughs.geojson"

# Sensors the user said to keep (by sensor_index)
KEEP_NON_EJ = {191419, 138844, 135148}    # 89th+Ridge, Neal Phillip BKLYN, Riverdale
KEEP_EJ     = {165783, 89957, 150696, 37185}  # Red Hook Farms, FA-O5, NBN-Green, NBN-Bushwick

# Prefer first_seen on or before this date when breaking ties
PREFER_CUTOFF = datetime(2023, 6, 1)

# Manhattan: north of 60th St ≈ lat > 40.768
MANHATTAN_60TH_LAT = 40.768


# ── Borough geometry helpers ───────────────────────────────────────────────

def _rings_to_geom(geom_dict):
    """
    Build a valid shapely geometry from a GeoJSON geometry dict.

    ArcGIS REST exports pack all rings into a single Polygon regardless of
    winding order, so the standard shapely shape() call produces invalid
    geometry (the tiny ring[0] becomes the exterior).  Instead, we treat
    every ring as a filled polygon and return the unary_union — effectively
    the footprint of land that belongs to the borough.  Sensor locations are
    on land, so this is geometrically equivalent to a proper point-in-borough
    test.
    """
    from shapely.geometry import Polygon as SPoly
    from shapely.ops import unary_union

    def _collect_rings(coords_list):
        polys = []
        for ring in coords_list:
            if len(ring) < 4:
                continue
            try:
                p = SPoly(ring)
                if p.area > 0:
                    polys.append(p)
            except Exception:
                pass
        return polys

    gtype = geom_dict["type"]
    if gtype == "Polygon":
        polys = _collect_rings(geom_dict["coordinates"])
    elif gtype == "MultiPolygon":
        polys = []
        for part in geom_dict["coordinates"]:
            polys.extend(_collect_rings(part))
    else:
        return shape(geom_dict)

    if not polys:
        return shape(geom_dict)
    result = unary_union(polys)
    return result.buffer(0) if not result.is_valid else result


def _load_borough_geoms():
    if not BORO_CACHE.exists():
        last_exc = None
        for url in BORO_URLS:
            try:
                print(f"  Trying: {url[:80]}…")
                r = requests.get(url, timeout=60)
                r.raise_for_status()
                body = r.content
                if b"FeatureCollection" in body or b"Feature" in body:
                    BORO_CACHE.write_bytes(body)
                    print(f"  Cached → {BORO_CACHE.name}")
                    break
                last_exc = ValueError(f"Response does not look like GeoJSON ({len(body)} bytes)")
            except Exception as exc:
                last_exc = exc
                print(f"    failed: {exc}")
        else:
            raise RuntimeError(
                f"Could not download NYC borough boundaries. Last error: {last_exc}"
            )
    data = json.loads(BORO_CACHE.read_text(encoding="utf-8"))
    geoms = {}
    for f in data["features"]:
        p = f["properties"]
        name = (p.get("BoroName") or p.get("boro_name") or p.get("boroname") or
                p.get("BORO_NAME") or p.get("name") or "Unknown")
        name = name.strip().title()
        geom = _rings_to_geom(f["geometry"])
        if name in geoms:
            from shapely.ops import unary_union
            geoms[name] = unary_union([geoms[name], geom])
        else:
            geoms[name] = geom
    return geoms


def _assign_borough(lat, lon, boro_geoms):
    pt = Point(lon, lat)
    for name, geom in boro_geoms.items():
        if geom.contains(pt):
            return name
    return None   # outside all five boroughs → NJ / outside NYC


# ── Balance helper ─────────────────────────────────────────────────────────

def _check_balance():
    try:
        r = requests.get(f"{BASE_URL}/keys", headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"_error": str(exc)}


# ── Selection helpers ──────────────────────────────────────────────────────

def _fs_dt(s):
    return datetime.strptime(s["first_seen"], "%Y-%m-%d")


def _pick(candidates, n=1):
    """Up to n sensors; prefer first_seen ≤ PREFER_CUTOFF, then oldest first."""
    pref   = sorted([c for c in candidates if _fs_dt(c) <= PREFER_CUTOFF], key=_fs_dt)
    others = sorted([c for c in candidates if _fs_dt(c) >  PREFER_CUTOFF], key=_fs_dt)
    return (pref + others)[:n]


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 76)
    print("Check 9 Phase 1 (revised): correct borough assignment + priority fill")
    print("=" * 76)

    # ── Point cost & balance ───────────────────────────────────────────────
    print(f"\n{'─'*76}")
    print("  POINT COST SUMMARY")
    print(f"  History window   : {HISTORY_START.date()} → {TODAY.date()} ({HISTORY_DAYS} days)")
    print(f"  Fields requested : {HISTORY_FIELDS}  (pm2.5_cf_1_a · pm2.5_cf_1_b · humidity)")
    print(f"  Points/sensor    : {HISTORY_FIELDS} fields × {HISTORY_DAYS} days = {COST_PER_SENSOR:,}")
    print(f"  11 sensors total : {11 * COST_PER_SENSOR:,} points")
    print(f"  12 sensors total : {12 * COST_PER_SENSOR:,} points")

    print("\n  API key / balance check (GET /v1/keys):")
    bal = _check_balance()
    for line in json.dumps(bal, indent=4).splitlines():
        print("    " + line)
    # PurpleAir read keys do not expose a numeric balance in /v1/keys.
    # The field would appear as 'request_remaining' or 'points_remaining' if
    # the plan exposed it.  Since it doesn't, direct the user to their account.
    if not any(k in bal for k in ("request_remaining", "points_remaining")):
        print("\n  NOTE: /v1/keys did not return a numeric balance for this key type.")
        print("        Check your remaining points at: purpleair.com → Account → API")
    print(f"{'─'*76}")

    # ── Load eligible pool ─────────────────────────────────────────────────
    cand_path = RAW_PA_DIR / "phase1_candidates.json"
    pool      = json.loads(cand_path.read_text(encoding="utf-8"))
    raw_non_ej = pool["all_eligible"]["non_ej"]
    raw_ej     = pool["all_eligible"]["ej"]
    print(f"\n  Eligible pool from Phase 1: {len(raw_non_ej)} non-EJ, {len(raw_ej)} EJ")

    # ── Borough point-in-polygon ───────────────────────────────────────────
    print("\n  Loading NYC borough boundaries…")
    boro_geoms = _load_borough_geoms()
    print(f"  Boroughs loaded: {', '.join(sorted(boro_geoms))}")

    def _reclassify(sensors, label):
        nyc, dropped = [], []
        for s in sensors:
            b = _assign_borough(s["lat"], s["lon"], boro_geoms)
            if b is None:
                dropped.append(s)
                continue
            nyc.append({**s, "borough": b})
        print(f"  {label}: {len(nyc)} in NYC, {len(dropped)} outside "
              f"(NJ/other) → dropped: {[d['name'] for d in dropped]}")
        return nyc

    print()
    non_ej_nyc = _reclassify(raw_non_ej, "non-EJ")
    ej_nyc     = _reclassify(raw_ej,     "EJ")

    # ── Verify + resolve keep-list ─────────────────────────────────────────
    all_nyc_by_id = {s["sensor_index"]: s for s in non_ej_nyc + ej_nyc}

    def _fetch_keep(ids, label):
        found, missing = [], []
        for sid in ids:
            if sid in all_nyc_by_id:
                found.append(all_nyc_by_id[sid])
            else:
                missing.append(sid)
        if missing:
            print(f"  WARNING: {label} sensor IDs not found in NYC pool: {missing}")
        return found

    print("\n  Resolving user-specified keeps…")
    sel_non_ej = _fetch_keep(KEEP_NON_EJ, "non-EJ")
    sel_ej     = _fetch_keep(KEEP_EJ,     "EJ")

    print(f"  Kept non-EJ ({len(sel_non_ej)}): "
          f"{[(s['sensor_index'], s['name'], s['borough']) for s in sel_non_ej]}")
    print(f"  Kept EJ ({len(sel_ej)}): "
          f"{[(s['sensor_index'], s['name'], s['borough']) for s in sel_ej]}")

    # ── Priority fill for non-EJ cell ──────────────────────────────────────
    used = {s["sensor_index"] for s in sel_non_ej + sel_ej}
    avail = [s for s in non_ej_nyc if s["sensor_index"] not in used]

    print("\n  Filling non-EJ cell by priority…")

    # Priority a: Manhattan north of 60th St, non-EJ — up to 2
    man_n60 = [s for s in avail
               if s["borough"] == "Manhattan" and s["lat"] > MANHATTAN_60TH_LAT]
    picks_a = _pick(man_n60, 2)
    sel_non_ej.extend(picks_a)
    used |= {s["sensor_index"] for s in picks_a}
    avail = [s for s in avail if s["sensor_index"] not in used]
    print(f"  a) Manhattan north of 60th: {len(man_n60)} candidates → picked {len(picks_a)}: "
          f"{[(s['name'], s['first_seen']) for s in picks_a]}")

    # Priority b: one Queens
    qns = [s for s in avail if s["borough"] == "Queens"]
    picks_q = _pick(qns, 1)
    sel_non_ej.extend(picks_q)
    used |= {s["sensor_index"] for s in picks_q}
    avail = [s for s in avail if s["sensor_index"] not in used]
    print(f"  b) Queens: {len(qns)} candidates → picked {len(picks_q)}: "
          f"{[(s['name'], s['first_seen']) for s in picks_q]}")

    # Priority b: one Staten Island
    # Check if already covered by the keep-list
    si_kept = [s for s in sel_non_ej if s["borough"] == "Staten Island"]
    if si_kept:
        print(f"  b) Staten Island: already covered by '{si_kept[0]['name']}'")
        picks_si = []
    else:
        si = [s for s in avail if s["borough"] == "Staten Island"]
        picks_si = _pick(si, 1)
        sel_non_ej.extend(picks_si)
        used |= {s["sensor_index"] for s in picks_si}
        avail = [s for s in avail if s["sensor_index"] not in used]
        print(f"  b) Staten Island: {len(si)} candidates → picked {len(picks_si)}: "
              f"{[(s['name'], s['first_seen']) for s in picks_si]}")

    # Priority b: one more Brooklyn (beyond the 2 already kept from KEEP_NON_EJ)
    bk = [s for s in avail if s["borough"] == "Brooklyn"]
    picks_bk = _pick(bk, 1)
    sel_non_ej.extend(picks_bk)
    used |= {s["sensor_index"] for s in picks_bk}
    print(f"  b) Brooklyn +1: {len(bk)} candidates → picked {len(picks_bk)}: "
          f"{[(s['name'], s['first_seen']) for s in picks_bk]}")

    # ── Revised candidate table ────────────────────────────────────────────
    n_sel      = len(sel_non_ej) + len(sel_ej)
    total_cost = n_sel * COST_PER_SENSOR

    SEP = "─" * 108
    print(f"\n{SEP}")
    print(f"  REVISED CANDIDATE TABLE  "
          f"({len(sel_non_ej)} non-EJ + {len(sel_ej)} EJ = {n_sel} sensors)")
    print(f"  Per-sensor cost: {COST_PER_SENSOR:,} pts  |  Total: {total_cost:,} pts")
    print(SEP)
    HDR = (f"{'#':<3} {'Cell':<8} {'Name':<38} {'ID':>7}  "
           f"{'Borough':<14} {'Lat':>9} {'Lon':>10}  "
           f"{'First seen':>11} {'Last seen':>11}")
    print(HDR)
    print("─" * len(HDR))

    n = 0
    print("  ——  Outside-zone NON-EJ  ——")
    for s in sel_non_ej:
        n += 1
        tag = " [keep]" if s["sensor_index"] in KEEP_NON_EJ else ""
        print(
            f"{n:<3} {'non-EJ':<8} {s['name'][:37]:<38} {s['sensor_index']:>7}  "
            f"{s['borough']:<14} {s['lat']:>9.5f} {s['lon']:>10.5f}  "
            f"{s['first_seen']:>11} {s['last_seen']:>11}{tag}"
        )

    print("  ——  Outside-zone EJ  ——")
    for s in sel_ej:
        n += 1
        tag = " [keep]" if s["sensor_index"] in KEEP_EJ else ""
        print(
            f"{n:<3} {'EJ':<8} {s['name'][:37]:<38} {s['sensor_index']:>7}  "
            f"{s['borough']:<14} {s['lat']:>9.5f} {s['lon']:>10.5f}  "
            f"{s['first_seen']:>11} {s['last_seen']:>11}{tag}"
        )

    print(SEP)
    print("  [keep] = user-specified sensor")
    print(f"\n  NYC-only eligible pool: {len(non_ej_nyc)} non-EJ, {len(ej_nyc)} EJ")

    # ── Save revised candidate list ────────────────────────────────────────
    out = {
        "generated":           TODAY.strftime("%Y-%m-%d"),
        "history_start":       HISTORY_START.strftime("%Y-%m-%d"),
        "history_end":         TODAY.strftime("%Y-%m-%d"),
        "history_days":        HISTORY_DAYS,
        "cost_per_sensor":     COST_PER_SENSOR,
        "total_cost_selected": total_cost,
        "n_selected":          n_sel,
        "selected": {
            "non_ej": sel_non_ej,
            "ej":     sel_ej,
        },
        "nyc_pool": {
            "non_ej_count": len(non_ej_nyc),
            "ej_count":     len(ej_nyc),
        },
    }
    out_path = RAW_PA_DIR / "phase1_candidates_v2.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n  Saved → {out_path.relative_to(_PROJECT)}")
    print("\nPhase 1 revised complete. Approve to proceed to Phase 2.")


if __name__ == "__main__":
    main()
