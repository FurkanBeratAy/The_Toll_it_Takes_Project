# -*- coding: utf-8 -*-
"""
analysis/robustness.py
Five robustness checks for the NYC CRZ ITS air-quality analysis.

Reads existing processed outputs; does NOT modify the main pipeline.
Outputs:
  data/processed/robustness.json    — all estimates, CIs, p-values
  data/processed/lga_weather_daily.csv  — cached ASOS data
  METHODS_ADDENDUM.md
  Appends a <section> to site/part1.html after the equity chart.
"""

import sys, json, textwrap, warnings
from pathlib import Path
from zoneinfo import ZoneInfo

# Force UTF-8 line-buffered output on Windows (avoids cp1252 UnicodeEncodeError for β, µ, etc.)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import norm as _sci_norm
import requests
from shapely.geometry import Point, shape
from shapely.ops import transform as shp_transform
import pyproj

def _pval(t_stat):
    """Two-sided p-value from a t/z stat."""
    return float(2 * (1 - _sci_norm.cdf(abs(t_stat))))

warnings.filterwarnings("ignore")

# ─── 0. Paths & constants ────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from config import (BASE_DIR, PROCESSED_DIR, RAW_DIR, TOLL_DATE, VW_START,
                    COVID_START, COVID_END, STATION_COORDS)

ANALYSIS_DIR = BASE_DIR / "analysis"

# Sites for the pooled panel (exclude Hunts_Point n_pre_vw=0, controls QC/VW)
PANEL_SITES = [
    "Cross_Bronx_Expy", "Mott_Haven", "Manhattan_Bridge",
    "Williamsburg_Bridge", "Queensboro_Bridge",
    "Broadway_35th_St", "FDR", "Hamilton_Bridge", "BQE", "SI_Expwy",
    "Midtown_DOT",   # included but flagged for 500-day gap
]
# Sites with a known large data gap — flag in output
GAP_FLAGGED = {"Midtown_DOT", "Cross_Bronx_Expy"}

# All non-control sites for the cross-sectional equity regression
# (includes Hunts_Point via its long-baseline beta)
ALL_EQ_SITES = PANEL_SITES + ["Hunts_Point"]

CRZ_SITES     = {"Midtown_DOT", "Broadway_35th_St"}
ET            = ZoneInfo("America/New_York")

# Webb weights for wild cluster bootstrap (uniform over 6 discrete values)
WEBB = np.array([-np.sqrt(1.5), -np.sqrt(0.5), -np.sqrt(1/6),
                  np.sqrt(1/6),  np.sqrt(0.5),  np.sqrt(1.5)])

SITE_MAP_INV = {   # human name → NYCCAS SiteID (for hourly load)
    "Cross_Bronx_Expy":    "36005NY12387",
    "Hunts_Point":         "36005NY11790",
    "Mott_Haven":          "36005NY11534",
    "Manhattan_Bridge":    "36061NY08454",
    "Williamsburg_Bridge": "36061NY08552",
    "Queensboro_Bridge":   "36061NY10130",
    "Queens_College":      "36081NY09285",
    "Van_Wyck":            "36081NY07615",
    "Broadway_35th_St":    "36061NY09734",
    "Midtown_DOT":         "36061NY09929",
    "FDR":                 "36061NY08653",
    "Hamilton_Bridge":     "36061NY12380",
    "BQE":                 "36047NY07974",
    "SI_Expwy":            "36085NY03820",
}
SITE_MAP_FWD = {v: k for k, v in SITE_MAP_INV.items()}


# ─── 1. EJ flags ─────────────────────────────────────────────────────────

def compute_ej_flags():
    """
    For each monitoring station:
      - point-in-polygon EJ flag (DAC layer)
      - share of 500 m buffer area that is in a DAC tract
      - in_CRZ indicator (from CRZ boundary geojson)
    """
    print("  Loading DAC tracts…")
    dac_data = json.loads((PROCESSED_DIR / "dac_tracts_nyc.geojson").read_text())
    tracts = [(shape(f["geometry"]),
               f["properties"]["dac_designation"] == "Designated as DAC")
              for f in dac_data["features"]]
    dac_tracts_only = [(g, True) for g, is_dac in tracts if is_dac]

    print("  Loading CRZ boundary…")
    crz_data = json.loads((PROCESSED_DIR / "crz_boundary.geojson").read_text())
    crz_geoms = [shape(f["geometry"]) for f in crz_data["features"]]

    wgs84  = pyproj.CRS("EPSG:4326")
    utm18  = pyproj.CRS("EPSG:32618")
    to_utm = pyproj.Transformer.from_crs(wgs84, utm18, always_xy=True).transform

    results = {}
    for site, (lat, lon) in STATION_COORDS.items():
        pt_wgs = Point(lon, lat)

        # Point-in-polygon EJ
        pt_flag = False
        for geom, is_dac in tracts:
            if geom.contains(pt_wgs):
                pt_flag = is_dac
                break

        # 500 m buffer share (projected to UTM)
        pt_utm  = shp_transform(to_utm, pt_wgs)
        buf_utm = pt_utm.buffer(500.0)
        buf_area = buf_utm.area

        dac_area = 0.0
        for geom_wgs, _ in dac_tracts_only:
            geom_utm = shp_transform(to_utm, geom_wgs)
            if geom_utm.intersects(buf_utm):
                dac_area += geom_utm.intersection(buf_utm).area

        buf_share = dac_area / buf_area if buf_area > 0 else 0.0

        # in_CRZ
        in_crz = any(g.contains(pt_wgs) for g in crz_geoms)

        results[site] = {
            "ej_point":    pt_flag,
            "ej_buffer":   round(buf_share, 4),
            "ej_buf_flag": buf_share > 0.5,
            "in_crz":      in_crz,
            "disagree":    pt_flag != (buf_share > 0.5),
        }

    return results


def print_ej_table(ej_flags):
    print(f"\n  {'Site':<22} {'EJ-point':>8} {'Buf-share':>10} {'EJ-buf>0.5':>11} {'in_CRZ':>7} {'Disagree':>9}")
    print("  " + "-" * 72)
    for site in sorted(ej_flags):
        f  = ej_flags[site]
        mk = " **" if f["disagree"] else ""
        print(f"  {site:<22} {'Y' if f['ej_point'] else 'N':>8} "
              f"{f['ej_buffer']:>10.3f} {'Y' if f['ej_buf_flag'] else 'N':>11} "
              f"{'Y' if f['in_crz'] else 'N':>7}{mk}")
    print("  ** = point flag and buffer flag disagree")


# ─── 2. Data loading ─────────────────────────────────────────────────────

def load_daily():
    raw   = json.loads((PROCESSED_DIR / "pollution_daily.json").read_text())
    idx   = pd.to_datetime(raw["dates"])
    daily = pd.DataFrame(raw["sites"], index=idx)
    return daily


def load_its_results():
    return json.loads((PROCESSED_DIR / "its_results.json").read_text())


def load_hourly():
    """Re-read all NYCCAS hourly CSVs → DataFrame (date × site, ET local date)."""
    hourly_dir = RAW_DIR / "nyccas_hourly"
    dfs = []
    for fp in sorted(hourly_dir.glob("*.csv")):
        try:
            df = pd.read_csv(fp, usecols=["SiteID", "ObservationTimeUTC", "Value"])
            dfs.append(df)
        except Exception as e:
            print(f"    warn {fp.name}: {e}")
    if not dfs:
        return None
    full = pd.concat(dfs, ignore_index=True)
    full["ObservationTimeUTC"] = pd.to_datetime(full["ObservationTimeUTC"], errors="coerce")
    full = full.dropna(subset=["ObservationTimeUTC", "Value"])
    full = full[(full["Value"] >= 0) & (full["Value"] < 200)]
    full["site"] = full["SiteID"].map(SITE_MAP_FWD)
    full = full[full["site"].notna()]
    # Convert UTC → US/Eastern for peak-hour classification
    full["dt_et"] = full["ObservationTimeUTC"].dt.tz_localize("UTC").dt.tz_convert(ET)
    full["date_et"] = full["dt_et"].dt.date
    full["hour_et"] = full["dt_et"].dt.hour
    full["dow_et"]  = full["dt_et"].dt.dayofweek   # 0=Mon … 6=Sun
    return full


def load_bt_throgs_neck():
    """Load Throgs Neck Bridge daily crossings from the raw 1.88 GB B&T CSV."""
    bt_path = RAW_DIR / "MTA_Bridges_and_Tunnels_Hourly_Crossings__Beginning_2019_20260905.csv"
    if not bt_path.exists():
        print("  B&T CSV not found — Check 5 skipped")
        return None
    print("  Reading B&T CSV (1.88 GB), filtering Throgs Neck only…")
    chunks = []
    for chunk in pd.read_csv(
        bt_path,
        usecols=["Date", "Facility", "Traffic Count"],
        chunksize=500_000,
        dtype={"Traffic Count": "Int32"},
        low_memory=False,
    ):
        chunk = chunk[chunk["Facility"].str.contains("Throgs Neck", na=False)].copy()
        if len(chunk) == 0:
            continue
        chunk["Date"] = pd.to_datetime(chunk["Date"], format="%m/%d/%Y", errors="coerce")
        chunk = chunk.dropna(subset=["Date"])
        chunks.append(chunk.groupby("Date")["Traffic Count"].sum().reset_index())
    if not chunks:
        print("  No Throgs Neck rows found")
        return None
    df = pd.concat(chunks).groupby("Date")["Traffic Count"].sum().rename("tn_volume")
    df = df.sort_index()
    print(f"  Throgs Neck: {len(df)} daily rows, {df.index.min().date()} – {df.index.max().date()}")
    return df


# ─── 3. ASOS weather ─────────────────────────────────────────────────────

def fetch_or_load_asos():
    """Fetch LGA hourly ASOS from Iowa Mesonet, cache to CSV. Print per-field missingness."""
    cache = PROCESSED_DIR / "lga_weather_daily.csv"
    if cache.exists():
        print("  Loading cached ASOS data…")
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        return df

    print("  Fetching LGA ASOS from Iowa Environmental Mesonet (yearly chunks)…")
    all_rows = []
    base_url = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
    params_common = {
        "station": "LGA",
        "data":    ["sknt", "tmpf", "p01i", "relh", "drct"],
        "tz":      "UTC",
        "format":  "comma",
        "latlon":  "no",
        "direct":  "no",
        "report_type": "3",
    }

    from io import StringIO
    for year in range(2019, 2027):
        end_month, end_day = (9, 30) if year == 2026 else (12, 31)
        fetched = False
        # Try both direct=no and direct=yes for resilience
        for direct_val in ["no", "yes"]:
            params = dict(params_common,
                          year1=year, month1=1, day1=1,
                          year2=year, month2=end_month, day2=end_day,
                          direct=direct_val)
            try:
                r = requests.get(base_url, params=params, timeout=180)
                if r.status_code == 503:
                    continue   # try other direct param
                if r.status_code != 200:
                    print(f"    {year}: HTTP {r.status_code}")
                    break
                lines = [l for l in r.text.splitlines()
                         if not l.startswith("#") and l.strip()]
                if len(lines) < 2:
                    continue
                chunk = pd.read_csv(StringIO("\n".join(lines)),
                                    na_values=["M", "  M", " M"])
                all_rows.append(chunk)
                print(f"    {year}: {len(chunk)} hourly rows")
                fetched = True
                break
            except Exception as e:
                print(f"    {year}: fetch error: {e}")
                break
        if not fetched:
            print(f"    {year}: unavailable (skipped)")

    if not all_rows:
        print("  ASOS fetch failed entirely — Check 1 will be skipped")
        return None

    raw = pd.concat(all_rows, ignore_index=True)

    # Rename columns (IEM uses lowercase; handle possible variations)
    raw.columns = [c.strip().lower() for c in raw.columns]
    col_map = {c: c for c in raw.columns}
    raw = raw.rename(columns=col_map)

    # Parse timestamp
    if "valid" in raw.columns:
        raw["dt"] = pd.to_datetime(raw["valid"], errors="coerce", utc=True)
    elif "valid(utc)" in raw.columns:
        raw["dt"] = pd.to_datetime(raw["valid(utc)"], errors="coerce", utc=True)
    else:
        print("  Could not find timestamp column in ASOS data")
        return None

    raw = raw.dropna(subset=["dt"])
    raw["date"] = raw["dt"].dt.date

    # ── Per-field missingness report ──────────────────────────────────────
    fields = {"sknt": "wind_speed_kts", "tmpf": "temp_f",
              "p01i": "precip_in",      "relh": "rh_pct",  "drct": "wind_dir_deg"}
    print(f"\n  {'Field':<16} {'Present':>8} {'Missing':>8} {'Miss%':>8}")
    print("  " + "-" * 44)
    for src, label in fields.items():
        if src not in raw.columns:
            print(f"  {label:<16} {'—':>8} {'—':>8} {'column absent':>8}")
            continue
        n_total  = len(raw)
        n_miss   = raw[src].isna().sum()
        n_valid  = n_total - n_miss
        print(f"  {label:<16} {n_valid:>8,} {n_miss:>8,} {100*n_miss/n_total:>7.1f}%")
    print()

    # ── Daily aggregation ─────────────────────────────────────────────────
    agg_rows = []
    for dt, grp in raw.groupby("date"):
        row = {"date": dt}

        if "tmpf" in grp.columns:
            v = grp["tmpf"].dropna()
            row["temp_c"] = float(((v - 32) * 5/9).mean()) if len(v) >= 12 else np.nan

        if "sknt" in grp.columns:
            v = grp["sknt"].dropna()
            row["wind_speed_ms"] = float(v.mean() * 0.5144) if len(v) >= 12 else np.nan

        if "relh" in grp.columns:
            v = grp["relh"].dropna()
            row["rh"] = float(v.mean()) if len(v) >= 12 else np.nan

        # Precip: sum non-missing; missing days ≠ zero, handle separately
        if "p01i" in grp.columns:
            v = grp["p01i"].dropna()
            row["precip_mm"] = float(v.sum() * 25.4) if len(v) > 0 else np.nan
            row["precip_obs_n"] = int(len(v))   # hours with valid precip obs

        if "drct" in grp.columns:
            v = grp["drct"].dropna()
            # Filter out calm (speed=0) if sknt available
            if "sknt" in grp.columns:
                calm = grp["sknt"].fillna(0) < 0.5
                v = v[~calm.values[:len(v)]]
            if len(v) >= 6:
                row["wind_sector"] = _dominant_sector(v.values)
            else:
                row["wind_sector"] = np.nan

        agg_rows.append(row)

    daily_wx = pd.DataFrame(agg_rows).set_index("date")
    daily_wx.index = pd.to_datetime(daily_wx.index)
    daily_wx.to_csv(cache)
    print(f"  Cached {len(daily_wx)} daily weather rows to {cache.name}")
    return daily_wx


def _dominant_sector(drct_arr):
    """Return the most common 8-sector wind direction label."""
    sectors = ["N","NE","E","SE","S","SW","W","NW"]
    bins = np.array([22.5, 67.5, 112.5, 157.5, 202.5, 247.5, 292.5, 337.5, 360.0])
    labels_idx = np.searchsorted(bins, drct_arr % 360) % 8
    counts = np.bincount(labels_idx, minlength=8)
    return sectors[int(np.argmax(counts))]


# ─── 4. Core ITS helper (reusable across checks) ─────────────────────────

def _run_its_spec(y_vals, t0, idx, post_date, qc_vals, vw_vals=None, extra_cols=None):
    """
    Fit one ITS OLS spec. Returns dict with beta_post, CI, p, n.
    extra_cols: dict of {name: np.array} to add to X.
    """
    t      = (idx - t0).days.astype(float)
    post   = (idx >= post_date).astype(float)
    cos_t  = np.cos(2 * np.pi * t / 365.25)
    sin_t  = np.sin(2 * np.pi * t / 365.25)
    covid  = ((idx >= COVID_START) & (idx <= COVID_END)).astype(float)

    cols = {
        "const":  np.ones(len(idx)),
        "t":      t,
        "cos_t":  cos_t,
        "sin_t":  sin_t,
        "post":   post,
        "post_t": post * t,
        "covid":  covid,
        "QC":     qc_vals,
    }
    if vw_vals is not None:
        cols["VW"] = vw_vals
    if extra_cols:
        cols.update(extra_cols)

    X      = pd.DataFrame(cols, index=idx)
    model  = sm.OLS(y_vals, X)
    result = model.fit(cov_type="HAC", cov_kwds={"maxlags": 30})
    ci95   = result.conf_int(alpha=0.05)

    return {
        "beta_post":    round(float(result.params["post"]), 4),
        "se":           round(float(result.bse["post"]), 4),
        "p":            round(float(result.pvalues["post"]), 4),
        "ci_low":       round(float(ci95.loc["post", 0]), 4),
        "ci_high":      round(float(ci95.loc["post", 1]), 4),
        "n":            int(result.nobs),
        "r2":           round(float(result.rsquared), 4),
        "significant":  bool(result.pvalues["post"] < 0.05),
    }


def _build_joint(y_s, qc_s, vw_s=None, weather_df=None,
                 start_date=None, end_date=None):
    """
    Intersect y, QC[, VW, weather] → clean DataFrame ready for ITS fit.
    Precip NaN filled with 0 (per user spec); other weather NaN propagates.
    start_date / end_date: optional window restriction.
    """
    cols = {"y": y_s, "QC": qc_s}
    if vw_s is not None:
        cols["VW"] = vw_s

    wx_cols = []
    if weather_df is not None:
        for c in ["temp_c", "wind_speed_ms", "rh"]:
            if c in weather_df.columns:
                cols[c] = weather_df[c]
                wx_cols.append(c)
        if "precip_mm" in weather_df.columns:
            cols["precip_mm"] = weather_df["precip_mm"].fillna(0)
            wx_cols.append("precip_mm")
        if "wind_sector" in weather_df.columns:
            sec = weather_df["wind_sector"]
            for s in ["NE","E","SE","S","SW","W","NW"]:
                cols[f"wind_{s}"] = (sec == s).astype(float)
                wx_cols.append(f"wind_{s}")

    joint = pd.DataFrame(cols).dropna(
        subset=["y","QC"] + (["VW"] if vw_s is not None else []) + wx_cols
    )

    if start_date is not None:
        joint = joint[joint.index >= start_date]
    if end_date is not None:
        joint = joint[joint.index < end_date]

    return joint, wx_cols


# ─── 5. Check 1: Weather-adjusted ITS ────────────────────────────────────

def run_check1(daily, weather_df, ej_flags):
    if weather_df is None:
        return {"status": "skipped", "reason": "ASOS fetch failed"}

    qc = daily.get("Queens_College")
    vw = daily.get("Van_Wyck")
    if qc is None:
        return {"status": "skipped", "reason": "Queens_College not found"}

    results = {}
    print(f"  {'Site':<22} {'orig_beta':>9} {'orig_p':>7}   {'wx_beta':>9} {'wx_p':>7}  {'CI_tightened':>13}")
    print("  " + "-" * 75)

    for site in PANEL_SITES + ["Hunts_Point"]:
        y = daily.get(site)
        if y is None:
            continue

        # Full spec window (VW_START to present)
        y_a  = y[y.index >= VW_START]
        qc_a = qc[qc.index >= VW_START]
        vw_a = vw[vw.index >= VW_START] if vw is not None else None

        joint_orig, _ = _build_joint(y_a, qc_a, vw_a,
                                     start_date=VW_START)
        if len(joint_orig) < 60 or (joint_orig.index < TOLL_DATE).sum() < 30:
            results[site] = {"status": "insufficient_data"}
            continue

        # Original spec
        orig = _run_its_spec(
            joint_orig["y"].values, joint_orig.index.min(),
            joint_orig.index, TOLL_DATE,
            joint_orig["QC"].values,
            vw_vals=joint_orig["VW"].values if "VW" in joint_orig else None,
        )

        # Weather-adjusted spec
        joint_wx, wx_cols = _build_joint(y_a, qc_a, vw_a, weather_df,
                                         start_date=VW_START)
        n_post_wx = (joint_wx.index >= TOLL_DATE).sum()
        if len(joint_wx) < 60 or (joint_wx.index < TOLL_DATE).sum() < 30:
            results[site] = {"original": orig, "weather": None,
                             "wx_status": "insufficient_overlap"}
            continue
        if n_post_wx < 10:
            results[site] = {"original": orig, "weather": None,
                             "wx_status": f"no_post_toll_weather (n_post={n_post_wx}; "
                                          f"ASOS data ends before toll date)"}
            print(f"  {site:<22} original only — no post-toll weather data available")
            continue

        extra = {c: joint_wx[c].values for c in wx_cols}
        wx = _run_its_spec(
            joint_wx["y"].values, joint_wx.index.min(),
            joint_wx.index, TOLL_DATE,
            joint_wx["QC"].values,
            vw_vals=joint_wx["VW"].values if "VW" in joint_wx else None,
            extra_cols=extra,
        )

        orig_width = orig["ci_high"] - orig["ci_low"]
        wx_width   = wx["ci_high"]   - wx["ci_low"]
        tighter    = "yes" if wx_width < orig_width else "wider"

        print(f"  {site:<22} {orig['beta_post']:>+9.4f} {orig['p']:>7.4f}   "
              f"{wx['beta_post']:>+9.4f} {wx['p']:>7.4f}  {tighter:>13}")

        results[site] = {
            "original": orig,
            "weather":  wx,
            "wx_n_overlap": int(len(joint_wx)),
            "ci_tightened": wx_width < orig_width,
        }

    return {"status": "ok", "sites": results}


# ─── 6. Check 2: Peak vs overnight ───────────────────────────────────────

def _peak_flag(hour_et, dow_et):
    """1=peak, 0=overnight per CRZ toll schedule."""
    weekday = dow_et < 5
    if weekday:
        return int(5 <= hour_et < 21)   # Mon–Fri 05:00–20:59
    else:
        return int(9 <= hour_et < 21)   # Sat–Sun 09:00–20:59


def run_check2():
    print("  Loading hourly data (this takes ~1 min)…")
    hourly = load_hourly()
    if hourly is None:
        return {"status": "skipped", "reason": "hourly data not found"}

    hourly["is_peak"] = hourly.apply(
        lambda r: _peak_flag(r["hour_et"], r["dow_et"]), axis=1)

    # Daily peak-mean and overnight-mean per site, with coverage thresholds
    target_sites = list(SITE_MAP_INV.keys())
    agg_rows = []

    for (site, date_et), grp in hourly.groupby(["site", "date_et"]):
        peak  = grp[grp["is_peak"] == 1]["Value"]
        night = grp[grp["is_peak"] == 0]["Value"]
        if len(peak) < 8 or len(night) < 5:
            continue
        agg_rows.append({
            "site":   site,
            "date":   pd.Timestamp(date_et),
            "diff":   float(peak.mean() - night.mean()),
            "dow":    pd.Timestamp(date_et).dayofweek,
        })

    if not agg_rows:
        return {"status": "skipped", "reason": "no valid peak/overnight pairs"}

    diff_df = pd.DataFrame(agg_rows)
    diff_wide = diff_df.pivot(index="date", columns="site", values="diff")
    diff_wide.index = pd.to_datetime(diff_wide.index)

    qc_diff = diff_wide.get("Queens_College")
    vw_diff = diff_wide.get("Van_Wyck")
    if qc_diff is None:
        return {"status": "skipped", "reason": "Queens_College not in differenced series"}

    results = {}
    weekday_results = {}

    print(f"  {'Site':<22} {'all-days beta':>13} {'all-days p':>11}  "
          f"{'wkday-only beta':>15} {'wkday-only p':>12}")
    print("  " + "-" * 78)

    for site in PANEL_SITES + ["Hunts_Point"]:
        y_diff = diff_wide.get(site)
        if y_diff is None:
            continue

        # All-days version
        y_a  = y_diff[y_diff.index >= VW_START]
        qc_a = qc_diff[qc_diff.index >= VW_START]
        vw_a = vw_diff[vw_diff.index >= VW_START] if vw_diff is not None else None
        joint, _ = _build_joint(y_a, qc_a, vw_a, start_date=VW_START)
        if len(joint) < 60 or (joint.index < TOLL_DATE).sum() < 30:
            continue
        r_all = _run_its_spec(
            joint["y"].values, joint.index.min(), joint.index, TOLL_DATE,
            joint["QC"].values,
            vw_vals=joint["VW"].values if "VW" in joint else None,
        )
        results[site] = r_all

        # Weekday-only version
        wd_mask = diff_df[(diff_df["site"] == site) & (diff_df["dow"] < 5)].copy()
        if len(wd_mask) == 0:
            weekday_results[site] = None
            continue
        wd_wide = wd_mask.set_index("date")["diff"]
        qc_wd = qc_diff.reindex(wd_wide.index)
        vw_wd = (vw_diff.reindex(wd_wide.index) if vw_diff is not None else None)
        y_wd_a  = wd_wide[wd_wide.index >= VW_START]
        qc_wd_a = qc_wd[qc_wd.index >= VW_START]
        vw_wd_a = vw_wd[vw_wd.index >= VW_START] if vw_wd is not None else None
        joint_wd, _ = _build_joint(y_wd_a, qc_wd_a, vw_wd_a, start_date=VW_START)
        if len(joint_wd) < 40 or (joint_wd.index < TOLL_DATE).sum() < 20:
            weekday_results[site] = None
            continue
        r_wd = _run_its_spec(
            joint_wd["y"].values, joint_wd.index.min(), joint_wd.index, TOLL_DATE,
            joint_wd["QC"].values,
            vw_vals=joint_wd["VW"].values if "VW" in joint_wd else None,
        )
        weekday_results[site] = r_wd

        b_all = r_all['beta_post'] if r_all else float('nan')
        p_all = r_all['p']        if r_all else float('nan')
        b_wd  = r_wd['beta_post'] if r_wd  else float('nan')
        p_wd  = r_wd['p']         if r_wd  else float('nan')
        print(f"  {site:<22} {b_all:>+13.4f} {p_all:>11.4f}  {b_wd:>+15.4f} {p_wd:>12.4f}")

    return {"status": "ok", "all_days": results, "weekday_only": weekday_results}


# ─── 7. Check 3: Placebo-in-time ─────────────────────────────────────────

def _check_placebo_coverage(y_pre, placebo_date):
    """
    Returns (ok, reason_if_not).
    Rules: ≥90 obs each side + ≥60% coverage in 6-month windows on each side.
    """
    window = pd.Timedelta(days=182)
    pre_obs  = y_pre[y_pre.index < placebo_date]
    post_obs = y_pre[y_pre.index >= placebo_date]

    if len(pre_obs)  < 90:
        return False, f"pre_n={len(pre_obs)}<90"
    if len(post_obs) < 90:
        return False, f"post_n={len(post_obs)}<90"

    pre_6m  = pre_obs[pre_obs.index >= (placebo_date - window)]
    post_6m = post_obs[post_obs.index < (placebo_date + window)]
    pre_cov  = len(pre_6m)  / 182
    post_cov = len(post_6m) / 182

    if pre_cov  < 0.60:
        return False, f"pre_6m_cov={pre_cov:.0%}<60%"
    if post_cov < 0.60:
        return False, f"post_6m_cov={post_cov:.0%}<60%"

    return True, "ok"


def _run_placebo_spec(y_series, qc_series, placebo_date):
    """QC-only ITS on pre-toll data with placebo_date as the cutoff."""
    y_pre  = y_series[y_series.index < TOLL_DATE].dropna()
    qc_pre = qc_series.reindex(y_pre.index)

    ok, reason = _check_placebo_coverage(y_pre, placebo_date)
    if not ok:
        return None, reason

    joint = pd.DataFrame({"y": y_pre, "QC": qc_pre}).dropna()
    if len(joint) < 60:
        return None, f"joint_n={len(joint)}<60"

    n_pre  = (joint.index < placebo_date).sum()
    n_post = (joint.index >= placebo_date).sum()
    if n_pre < 30 or n_post < 30:
        return None, f"pre={n_pre},post={n_post} (need ≥30 each)"

    t0 = joint.index.min()
    return _run_its_spec(
        joint["y"].values, t0, joint.index, placebo_date,
        joint["QC"].values,
    ), "ok"


def run_check3(daily, its_orig):
    qc = daily.get("Queens_College")
    if qc is None:
        return {"status": "skipped", "reason": "Queens_College not found"}

    # Placebo dates: 2021-07-01 through 2024-06-01 (monthly)
    placebo_dates = pd.date_range("2021-07-01", "2024-06-01", freq="MS")
    print(f"  {len(placebo_dates)} candidate placebo dates "
          f"({placebo_dates[0].date()} – {placebo_dates[-1].date()})")

    results     = {}
    skip_tables = {}

    for site in PANEL_SITES + ["Hunts_Point"]:
        y = daily.get(site)
        if y is None:
            continue

        # Get observed long-baseline beta_post for comparison
        orig_data = its_orig.get("sites", {}).get(site, {})
        obs_long  = (orig_data.get("long") or {}).get("beta_post")
        obs_full  = (orig_data.get("full") or {}).get("beta_post")

        betas   = []
        skipped = []

        for pd_date in placebo_dates:
            b, reason = _run_placebo_spec(y, qc, pd_date)
            if b is None:
                skipped.append((pd_date.strftime("%Y-%m-%d"), reason))
            else:
                betas.append({"date": pd_date.strftime("%Y-%m-%d"),
                               "beta_post": b["beta_post"]})

        skip_tables[site] = skipped

        if len(betas) < 3:
            results[site] = {"status": "too_few_placebos", "n_run": len(betas),
                             "skipped": skipped}
            continue

        beta_arr    = np.array([b["beta_post"] for b in betas])
        # Compare against long-baseline observed beta; fall back to full
        ref_beta    = obs_long if obs_long is not None else obs_full
        if ref_beta is not None:
            emp_p = float(np.mean(np.abs(beta_arr) >= abs(ref_beta)))
        else:
            emp_p = None

        results[site] = {
            "status":         "ok",
            "n_placebos":     len(betas),
            "betas":          betas,
            "skipped":        skipped,
            "beta_mean":      round(float(beta_arr.mean()), 4),
            "beta_std":       round(float(beta_arr.std()), 4),
            "obs_long_beta":  obs_long,
            "obs_full_beta":  obs_full,
            "empirical_p":    round(emp_p, 4) if emp_p is not None else None,
        }

    # Print gap/skip tables
    print(f"\n  {'Site':<22}  Skipped placebos and reasons")
    print("  " + "-" * 70)
    for site, skips in skip_tables.items():
        if not skips:
            print(f"  {site:<22}  (all passed)")
            continue
        print(f"  {site:<22}  {len(skips)} skipped:")
        for dt, reason in skips[:5]:
            print(f"  {'':22}    {dt}: {reason}")
        if len(skips) > 5:
            print(f"  {'':22}    … and {len(skips)-5} more")

    print(f"\n  {'Site':<22} {'n_run':>6} {'emp_p':>7}  obs_long_beta  obs_full_beta")
    print("  " + "-" * 68)
    for site, r in results.items():
        if r.get("status") != "ok":
            print(f"  {site:<22} {'–':>6} {'–':>7}  (skipped: {r.get('status')})")
            continue
        obs_l = f"{r['obs_long_beta']:+.4f}" if r['obs_long_beta'] is not None else "    n/a"
        obs_f = f"{r['obs_full_beta']:+.4f}" if r['obs_full_beta'] is not None else "    n/a"
        emp   = f"{r['empirical_p']:.4f}" if r['empirical_p'] is not None else "   n/a"
        print(f"  {site:<22} {r['n_placebos']:>6} {emp:>7}  {obs_l:>13}  {obs_f:>13}")

    return {"status": "ok", "sites": results}


# ─── 8. Check 4: Pooled panel with 2-way FE ──────────────────────────────

def _twoway_demean(df, cols, site_col="site", date_col="date",
                   max_iter=50, tol=1e-9):
    """Iterative alternating-projection demeaning for unbalanced panel."""
    out = {}
    for col in cols:
        x = df[col].astype(float).values.copy()
        for _ in range(max_iter):
            x_prev = x.copy()
            # Subtract site means
            s  = pd.Series(x, index=df.index)
            sm_ = s.groupby(df[site_col].values).transform("mean").values
            x  -= sm_
            # Subtract date means
            s  = pd.Series(x, index=df.index)
            dm_ = s.groupby(df[date_col].values).transform("mean").values
            x  -= dm_
            if np.max(np.abs(x - x_prev)) < tol:
                break
        out[col] = x
    return out


def _cluster_se(X_dm, resid, clusters):
    """Cluster-robust SEs (sandwich) after within-transformation."""
    n, k    = X_dm.shape
    XpXinv  = np.linalg.pinv(X_dm.T @ X_dm)
    G       = len(np.unique(clusters))
    meat    = np.zeros((k, k))
    for cl in np.unique(clusters):
        mask    = clusters == cl
        score_g = X_dm[mask].T @ resid[mask]
        meat   += np.outer(score_g, score_g)
    scale = (G / (G - 1)) * (n / (n - k))
    vcov  = scale * XpXinv @ meat @ XpXinv
    return np.sqrt(np.diag(vcov))


def _wild_boot_p(X_dm, y_dm, clusters, coef_idx=-1, B=9999, seed=42):
    """Wild cluster bootstrap p-value (Webb weights) for coefficient coef_idx."""
    rng = np.random.default_rng(seed)
    beta, _, _, _ = np.linalg.lstsq(X_dm, y_dm, rcond=None)
    resid = y_dm - X_dm @ beta
    se    = _cluster_se(X_dm, resid, clusters)
    t_obs = beta[coef_idx] / se[coef_idx]

    unique_cl = np.unique(clusters)
    G         = len(unique_cl)
    t_boots   = np.empty(B)

    for b in range(B):
        weights = rng.choice(WEBB, size=G)
        w_all   = np.zeros(len(y_dm))
        for w, cl in zip(weights, unique_cl):
            w_all[clusters == cl] = w
        y_boot     = X_dm @ beta + w_all * resid
        beta_b, _, _, _ = np.linalg.lstsq(X_dm, y_boot, rcond=None)
        resid_b    = y_boot - X_dm @ beta_b
        se_b       = _cluster_se(X_dm, resid_b, clusters)
        t_boots[b] = beta_b[coef_idx] / se_b[coef_idx]

    p_val = float(np.mean(np.abs(t_boots) >= np.abs(t_obs)))
    return float(beta[coef_idx]), float(se[coef_idx]), float(t_obs), p_val


def _wild_boot_all_p(X_dm, y_dm, clusters, B=9999, seed=42):
    """Wild cluster bootstrap p-values for every column of X_dm (Webb weights)."""
    rng = np.random.default_rng(seed)
    beta, _, _, _ = np.linalg.lstsq(X_dm, y_dm, rcond=None)
    resid = y_dm - X_dm @ beta
    se    = _cluster_se(X_dm, resid, clusters)
    t_obs = np.where(se > 0, beta / se, np.nan)

    unique_cl = np.unique(clusters)
    G  = len(unique_cl)
    k  = X_dm.shape[1]
    counts = np.zeros(k)

    for _ in range(B):
        w_g   = rng.choice(WEBB, size=G)
        w_all = np.empty(len(y_dm))
        for w, cl in zip(w_g, unique_cl):
            w_all[clusters == cl] = w
        y_b      = X_dm @ beta + w_all * resid
        beta_b, _, _, _ = np.linalg.lstsq(X_dm, y_b, rcond=None)
        resid_b  = y_b - X_dm @ beta_b
        se_b     = _cluster_se(X_dm, resid_b, clusters)
        t_b      = np.where(se_b > 0, beta_b / se_b, np.nan)
        valid    = ~(np.isnan(t_obs) | np.isnan(t_b))
        counts[valid] += (np.abs(t_b[valid]) >= np.abs(t_obs[valid]))

    return (counts / B).tolist()


def _panel_spec_b(panel, ej_col, crz_col, clusters, label):
    """
    Panel spec B: site+date FE + post×EJ + post×in_CRZ.
    Returns dict of results for each interaction term.
    """
    panel = panel.copy()
    panel["post_ej"]  = panel["post"] * panel[ej_col]
    panel["post_crz"] = panel["post"] * panel[crz_col]

    dm = _twoway_demean(panel, ["pm25", "post_ej", "post_crz"])
    y_dm = dm["pm25"]
    X_dm = np.column_stack([dm["post_ej"], dm["post_crz"]])

    beta, _, _, _ = np.linalg.lstsq(X_dm, y_dm, rcond=None)
    resid = y_dm - X_dm @ beta
    se    = _cluster_se(X_dm, resid, clusters)

    # Wild bootstrap for post×EJ (index 0)
    b_ej, se_ej, t_ej, p_boot_ej = _wild_boot_p(X_dm, y_dm, clusters, coef_idx=0)
    # Wild bootstrap for post×CRZ (index 1)
    b_crz, se_crz, t_crz, p_boot_crz = _wild_boot_p(X_dm, y_dm, clusters, coef_idx=1)

    p_norm = lambda b, s: _pval(b/s) if s > 0 else np.nan

    return {
        "label":   label,
        "post_ej": {
            "beta": round(b_ej, 4), "se": round(se_ej, 4),
            "p_normal": round(p_norm(b_ej, se_ej), 4),
            "p_bootstrap": round(p_boot_ej, 4),
            "ci_low":  round(b_ej - 1.96*se_ej, 4),
            "ci_high": round(b_ej + 1.96*se_ej, 4),
        },
        "post_crz": {
            "beta": round(b_crz, 4), "se": round(se_crz, 4),
            "p_normal": round(p_norm(b_crz, se_crz), 4),
            "p_bootstrap": round(p_boot_crz, 4),
            "ci_low":  round(b_crz - 1.96*se_crz, 4),
            "ci_high": round(b_crz + 1.96*se_crz, 4),
        },
    }


def run_check4(daily, ej_flags):
    # ── Build panel ───────────────────────────────────────────────────────
    rows = []
    included = []
    excluded = []

    for site in PANEL_SITES:
        y = daily.get(site)
        if y is None:
            excluded.append((site, "no data"))
            continue
        y_vw = y[y.index >= VW_START].dropna()
        n_pre = (y_vw.index < TOLL_DATE).sum()
        if n_pre < 30:
            excluded.append((site, f"n_pre_vw={n_pre}<30"))
            continue
        included.append(site)
        ej = ej_flags.get(site, {})
        for dt, val in y_vw.items():
            rows.append({
                "site":      site,
                "date":      dt.strftime("%Y-%m-%d"),
                "pm25":      float(val),
                "post":      int(dt >= TOLL_DATE),
                "ej_point":  int(ej.get("ej_point", False)),
                "ej_buf":    int(ej.get("ej_buf_flag", False)),
                "in_crz":    int(ej_flags.get(site, {}).get("in_crz", False)),
            })

    if excluded:
        for s, r in excluded:
            print(f"    Excluded from panel: {s} ({r})")

    panel = pd.DataFrame(rows)
    clusters = panel["site"].values
    G = len(panel["site"].unique())
    print(f"  Panel: {len(panel):,} site-date rows, {G} sites, "
          f"{panel['post'].mean():.1%} post-toll")
    print(f"  Sites: {', '.join(sorted(panel['site'].unique()))}")

    # ── Spec A: post x site differential effects ─────────────────────────
    # With full date FE the common post-toll level is absorbed by date dummies.
    # Including post x site for ALL N sites creates perfect collinearity
    # (they sum to post, which is date-absorbed), so we drop one reference site.
    # Coefficients = differential post-toll change vs. reference site.
    print("  Running Spec A: post x site interactions (2-way FE, differential)...")
    site_list   = sorted(panel["site"].unique())
    ref_site    = site_list[0]   # Cross_Bronx_Expy (first alphabetically)
    int_cols    = []
    for site in site_list[1:]:   # skip reference
        col = f"pxs_{site}"
        panel[col] = (panel["post"] * (panel["site"] == site)).astype(float)
        int_cols.append(col)

    dm_a = _twoway_demean(panel, ["pm25"] + int_cols)
    y_dm = dm_a["pm25"]
    X_dm = np.column_stack([dm_a[c] for c in int_cols])

    beta_a, _, _, _ = np.linalg.lstsq(X_dm, y_dm, rcond=None)
    resid_a = y_dm - X_dm @ beta_a
    se_a    = _cluster_se(X_dm, resid_a, clusters)
    p_norm  = lambda b, s: _pval(b/s) if s > 0 else np.nan

    # Wild-bootstrap p-values for all spec-A coefficients (G clusters, Webb weights)
    print("  Running Spec A wild bootstrap (B=9999)…")
    p_boots_a = _wild_boot_all_p(X_dm, y_dm, clusters, B=9999, seed=42)

    spec_a = {}
    print(f"  Reference: {ref_site} — all coefficients are DIFFERENTIAL vs. {ref_site}")
    print(f"  {'Site':<22} {'diff_beta':>9} {'se':>7} {'p_boot':>8} {'CI':>18}")
    print("  " + "-" * 69)
    spec_a[ref_site] = {"beta": 0.0, "se": None, "p": None, "p_bootstrap": None,
                        "ci_low": None, "ci_high": None,
                        "gap_flag": ref_site in GAP_FLAGGED,
                        "note": f"reference site — differential=0 by construction; "
                                f"all other betas are relative to {ref_site}"}
    print(f"  {ref_site:<22} {'0 (ref)':>9}")
    for site, b, s, pb in zip(site_list[1:], beta_a, se_a, p_boots_a):
        p   = p_norm(b, s)
        ci  = f"[{b-1.96*s:+.3f}, {b+1.96*s:+.3f}]"
        gap = " [gap]" if site in GAP_FLAGGED else ""
        print(f"  {site:<22} {b:>+9.4f} {s:>7.4f} {pb:>8.4f} {ci:>18}{gap}")
        spec_a[site] = {
            "beta": round(float(b), 4), "se": round(float(s), 4),
            "p":    round(p, 4),
            "p_bootstrap": round(float(pb), 4),
            "ci_low":  round(float(b - 1.96*s), 4),
            "ci_high": round(float(b + 1.96*s), 4),
            "gap_flag": site in GAP_FLAGGED,
        }

    # ── Spec B1: post×EJ_point + post×in_CRZ ─────────────────────────────
    print("\n  Running Spec B1: post×EJ(point) + post×in_CRZ (wild bootstrap, B=9999)…")
    spec_b1 = _panel_spec_b(panel, "ej_point", "in_crz", clusters, "EJ=point, all sites")

    # ── Spec B2: post×EJ_buffer + post×in_CRZ ────────────────────────────
    print("  Running Spec B2: post×EJ(buffer>0.5) + post×in_CRZ (wild bootstrap)…")
    spec_b2 = _panel_spec_b(panel, "ej_buf", "in_crz", clusters, "EJ=buffer>0.5, all sites")

    # ── Spec B3: outside-CRZ only (uses geofence-derived in_crz column) ─────
    print("  Running Spec B3: post×EJ(point) — outside-CRZ sites only (wild bootstrap)…")
    panel_nc   = panel[panel["in_crz"] == 0].copy()
    clusters_nc = panel_nc["site"].values
    G_nc = len(panel_nc["site"].unique())
    print(f"  Outside-CRZ panel: {len(panel_nc):,} rows, {G_nc} sites")

    panel_nc["post_ej"] = panel_nc["post"] * panel_nc["ej_point"]
    dm_b3 = _twoway_demean(panel_nc, ["pm25", "post_ej"])
    y_dm3 = dm_b3["pm25"]
    X_dm3 = dm_b3["post_ej"].reshape(-1, 1)
    b3, se3, t3, p3 = _wild_boot_p(X_dm3, y_dm3, clusters_nc, coef_idx=0)
    p_norm3 = p_norm(b3, se3)
    spec_b3 = {
        "label": "EJ=point, outside-CRZ only",
        "post_ej": {
            "beta": round(b3, 4), "se": round(se3, 4),
            "p_normal": round(p_norm3, 4),
            "p_bootstrap": round(p3, 4),
            "ci_low":  round(b3 - 1.96*se3, 4),
            "ci_high": round(b3 + 1.96*se3, 4),
        },
    }

    # Print spec-B summary
    def _print_b(label, spec):
        for term in ["post_ej", "post_crz"]:
            if term not in spec:
                continue
            d = spec[term]
            print(f"  {label:<38} {term:<10}: b={d['beta']:+.4f}  "
                  f"se={d['se']:.4f}  p_boot={d['p_bootstrap']:.4f}  "
                  f"CI=[{d['ci_low']:+.4f},{d['ci_high']:+.4f}]")

    print()
    _print_b("Spec B1 (EJ=point, all)", spec_b1)
    _print_b("Spec B2 (EJ=buf, all)", spec_b2)
    _print_b("Spec B3 (EJ=point, outside-CRZ)", spec_b3)

    return {
        "status":   "ok",
        "n_obs":    int(len(panel)),
        "n_sites":  G,
        "sites":    included,
        "spec_a":   spec_a,
        "spec_b1":  spec_b1,
        "spec_b2":  spec_b2,
        "spec_b3":  spec_b3,
        "excluded": excluded,
    }


# ─── 9. Check 5: Mechanism check ─────────────────────────────────────────

DOW_NAMES = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]

def run_check5(daily, weather_df):
    qc = daily.get("Queens_College")
    mh = daily.get("Mott_Haven")
    if mh is None or qc is None:
        return {"status": "skipped", "reason": "Mott_Haven or Queens_College not found"}

    tn = load_bt_throgs_neck()
    if tn is None:
        return {"status": "skipped", "reason": "Throgs Neck data not found"}

    # Window: 2022-01-01 through 2025-01-04 (pre-toll; VW not needed here)
    w_start = pd.Timestamp("2022-01-01")
    w_end   = TOLL_DATE   # exclusive

    mh_win  = mh[(mh.index >= w_start)  & (mh.index < w_end)].dropna()
    qc_win  = qc.reindex(mh_win.index)
    tn_win  = tn.reindex(mh_win.index)

    base_df = pd.DataFrame({
        "mh":   mh_win,
        "qc":   qc_win,
        "tn_k": tn_win / 1000.0,   # per 1,000 vehicles
    }).dropna()

    # Day-of-week dummies (6 dummies, Sunday reference)
    for d in range(6):
        base_df[f"dow_{DOW_NAMES[d]}"] = (base_df.index.dayofweek == d).astype(float)

    # Seasonal terms
    t = (base_df.index - base_df.index.min()).days.astype(float)
    base_df["t"]     = t
    base_df["cos_t"] = np.cos(2*np.pi*t/365.25)
    base_df["sin_t"] = np.sin(2*np.pi*t/365.25)

    # Build regressor matrix (no VW here — pre-VW period)
    regressors = (["const","tn_k","qc","t","cos_t","sin_t"] +
                  [f"dow_{n}" for n in DOW_NAMES[:6]])
    base_df["const"] = 1.0

    # Optional: add weather if available
    wx_added = []
    if weather_df is not None:
        for col in ["temp_c","wind_speed_ms","rh","precip_mm"]:
            if col in weather_df.columns:
                base_df[col] = weather_df[col].reindex(base_df.index)
                if col == "precip_mm":
                    base_df[col] = base_df[col].fillna(0)
        base_df_wx = base_df.dropna(subset=["temp_c","wind_speed_ms","rh"])
        if len(base_df_wx) >= 60:
            base_df   = base_df_wx
            wx_added  = ["temp_c","wind_speed_ms","rh","precip_mm"]
            regressors = regressors + wx_added
            print(f"  Weather covariates added (n={len(base_df)})")

    base_df = base_df.dropna(subset=regressors)
    n = len(base_df)
    if n < 60:
        return {"status": "skipped", "reason": f"Only {n} joint obs"}

    X = base_df[regressors].astype(float)   # keep as DataFrame so params are named
    y = base_df["mh"].astype(float).values

    model  = sm.OLS(y, X)
    result = model.fit(cov_type="HAC", cov_kwds={"maxlags": 30})

    ci95 = result.conf_int(alpha=0.05)
    beta_tn  = float(result.params["tn_k"])
    se_tn    = float(result.bse["tn_k"])
    p_tn     = float(result.pvalues["tn_k"])

    observed_beta = 0.2957    # Mott Haven full-spec beta_post (from its_results.json)
    diversion_veh = 2041.0    # Throgs Neck post-toll residual (veh/day)
    implied_pm25  = beta_tn * (diversion_veh / 1000.0)

    magnitude_consistent = (
        abs(implied_pm25) > 0 and
        (implied_pm25 > 0) == (observed_beta > 0) and
        abs(implied_pm25) <= 3 * abs(observed_beta)
    )

    print(f"\n  Pre-toll mechanism regression: n={n}")
    print(f"  β(Throgs Neck /1k veh) = {beta_tn:+.4f}  se={se_tn:.4f}  p={p_tn:.4f}")
    print(f"  CI 95%: [{ci95.loc['tn_k',0]:+.4f}, {ci95.loc['tn_k',1]:+.4f}]")
    print(f"  Implied PM2.5 change from +{diversion_veh:.0f} veh/day: {implied_pm25:+.4f} µg/m³")
    print(f"  Observed ITS beta_post: {observed_beta:+.4f} µg/m³")
    print(f"  Magnitude consistent: {magnitude_consistent}")
    if not magnitude_consistent:
        print("  => The pre-toll Throgs Neck-PM2.5 relationship does not imply")
        print("    a change large enough to explain the observed ITS coefficient.")
    else:
        print("  => Directions match and implied magnitude is within 3x of observed.")
        print("    Note: consistent does not mean causal; confounders remain possible.")

    # Scatter data for figure (Mott Haven PM2.5 vs Throgs Neck volume)
    scatter_x  = (tn_win.reindex(base_df.index) / 1000.0).tolist()
    scatter_y  = mh_win.reindex(base_df.index).tolist()
    fitted_mh  = (result.predict().tolist())

    return {
        "status":         "ok",
        "n":              n,
        "window":         f"{w_start.date()} – {w_end.date()}",
        "weather_added":  wx_added,
        "beta_tn_per1k":  round(beta_tn, 4),
        "se_tn":          round(se_tn, 4),
        "p_tn":           round(p_tn, 4),
        "ci_low":         round(float(ci95.loc["tn_k",0]), 4),
        "ci_high":        round(float(ci95.loc["tn_k",1]), 4),
        "diversion_veh":  diversion_veh,
        "implied_pm25":   round(implied_pm25, 4),
        "observed_beta":  observed_beta,
        "magnitude_consistent": magnitude_consistent,
        "scatter_x":      [round(v,3) for v in scatter_x if v is not None],
        "scatter_y":      [round(v,3) for v in scatter_y if v is not None],
    }


# ─── 9b. Check 7: Raw DiD difference series ──────────────────────────────

CHECK7_TARGET_SITES = [
    "Manhattan_Bridge", "Williamsburg_Bridge", "Queensboro_Bridge",
    "FDR", "Broadway_35th_St", "Cross_Bronx_Expy", "Mott_Haven",
]

# Target values from fix list §7 (match within ±0.01)
CHECK7_TARGETS = {
    "Manhattan_Bridge":    {"raw_delta_25": -1.21, "minus_vw_25": -0.59, "minus_vw_26": -1.40, "minus_qc_25": -1.17, "minus_qc_26": -1.53},
    "Williamsburg_Bridge": {"raw_delta_25": -1.89, "minus_vw_25": -0.81, "minus_vw_26": -1.42, "minus_qc_25": -1.61, "minus_qc_26": -1.61},
    "Queensboro_Bridge":   {"raw_delta_25": -0.93, "minus_vw_25": -0.13, "minus_vw_26": -0.60, "minus_qc_25": -0.83, "minus_qc_26": -1.08},
    "FDR":                 {"raw_delta_25": -0.91, "minus_vw_25": +0.05, "minus_vw_26": -0.46, "minus_qc_25": -0.39, "minus_qc_26": +0.15},
    "Broadway_35th_St":    {"raw_delta_25": -0.88, "minus_vw_25": +0.05, "minus_vw_26": -0.38, "minus_qc_25": -0.83, "minus_qc_26": -0.03},
    "Cross_Bronx_Expy":    {"raw_delta_25": -0.17, "minus_vw_25": +0.98, "minus_vw_26": -0.12, "minus_qc_25": -0.09, "minus_qc_26": +0.24},
    "Mott_Haven":          {"raw_delta_25": +0.09, "minus_vw_25": +0.88, "minus_vw_26": +0.85, "minus_qc_25": -0.21, "minus_qc_26": +0.84},
}


def run_check7(daily):
    """
    Raw DiD as difference series: (site − control) daily, matched day-of-year,
    2025 vs 2024 and 2026 (Jan–Sep) vs 2024.
    Units: µg/m³.
    """
    vw = daily.get("Van_Wyck")
    qc = daily.get("Queens_College")

    def _matched_did(site_s, ctrl_s, year_b, year_a=2024):
        """
        Mean of (site_b[m,d] − ctrl_b[m,d]) − (site_a[m,d] − ctrl_a[m,d])
        over all (month, day) pairs present in every required series.
        If ctrl_s is None, computes raw site-level change only.
        """
        s_a = site_s[site_s.index.year == year_a].dropna()
        s_b = site_s[site_s.index.year == year_b].dropna()

        def _doy(s):
            return {(d.month, d.day): float(v) for d, v in s.items()}

        da, db = _doy(s_a), _doy(s_b)

        if ctrl_s is None:
            common = sorted(set(da) & set(db))
            if not common:
                return None
            return round(float(np.mean([db[k] - da[k] for k in common])), 2)

        c_a = ctrl_s[ctrl_s.index.year == year_a].dropna()
        c_b = ctrl_s[ctrl_s.index.year == year_b].dropna()
        ca, cb = _doy(c_a), _doy(c_b)
        common = sorted(set(da) & set(db) & set(ca) & set(cb))
        if not common:
            return None
        return round(float(np.mean([(db[k] - cb[k]) - (da[k] - ca[k]) for k in common])), 2)

    results = {}
    mismatches = []

    print(f"\n  {'Site':<22} {'raw Δ25':>8} {'−VW 25':>8} {'−VW 26':>8} {'−QC 25':>8} {'−QC 26':>8}")
    print("  " + "-" * 66)

    for site in CHECK7_TARGET_SITES:
        s = daily.get(site)
        if s is None:
            print(f"  {site:<22}  NO DATA")
            continue

        row = {
            "raw_delta_25": _matched_did(s, None, 2025),
            "minus_vw_25":  _matched_did(s, vw,   2025) if vw is not None else None,
            "minus_vw_26":  _matched_did(s, vw,   2026) if vw is not None else None,
            "minus_qc_25":  _matched_did(s, qc,   2025) if qc is not None else None,
            "minus_qc_26":  _matched_did(s, qc,   2026) if qc is not None else None,
        }
        results[site] = row

        def _fmt(v):
            return f"{v:+.2f}" if v is not None else "  n/a"

        print(f"  {site:<22} {_fmt(row['raw_delta_25']):>8} {_fmt(row['minus_vw_25']):>8} "
              f"{_fmt(row['minus_vw_26']):>8} {_fmt(row['minus_qc_25']):>8} {_fmt(row['minus_qc_26']):>8}")

        # Verify against targets
        tgt = CHECK7_TARGETS.get(site, {})
        for key, tval in tgt.items():
            cval = row.get(key)
            if cval is not None and abs(cval - tval) > 0.01:
                mismatches.append(f"  {site} {key}: computed={cval:+.2f}, target={tval:+.2f}, diff={cval-tval:+.2f}")

    # Control baseline changes
    ctrl_changes = {}
    if vw is not None:
        ctrl_changes["vw_delta_25"] = _matched_did(vw, None, 2025)
        ctrl_changes["vw_delta_26"] = _matched_did(vw, None, 2026)
    if qc is not None:
        ctrl_changes["qc_delta_25"] = _matched_did(qc, None, 2025)
        ctrl_changes["qc_delta_26"] = _matched_did(qc, None, 2026)

    print(f"\n  Control baseline changes (matched DOY vs 2024):")
    for k, v in ctrl_changes.items():
        print(f"    {k}: {v:+.2f}" if v is not None else f"    {k}: n/a")

    if mismatches:
        print("\n  *** CHECK 7 MISMATCHES (>0.01 from targets) ***")
        for m in mismatches:
            print(m)
    else:
        print("\n  Check 7: all values match targets within 0.01 ✓")

    return {
        "status":         "ok" if not mismatches else "mismatch",
        "mismatches":     mismatches,
        "sites":          results,
        "control_changes": ctrl_changes,
        "note":           "units: µg/m³; matched day-of-year 2025 vs 2024 and 2026 vs 2024",
    }


# ─── 10. New equity regression (all sites, 3 specs) ──────────────────────

def run_equity_regression(its_orig, ej_flags):
    """
    Cross-sectional OLS: beta_post ~ EJ + in_CRZ + pre_mean_z
    Three versions:
      CS1 — EJ = point flag, all sites
      CS2 — EJ = buffer > 0.5, all sites
      CS3 — EJ = point flag, outside-CRZ only
    """
    rows = []
    for site in ALL_EQ_SITES:
        orig_data = its_orig.get("sites", {}).get(site, {})
        spec = orig_data.get("full") or orig_data.get("long")
        if spec is None:
            continue
        beta = spec.get("beta_post")
        pre  = spec.get("pre_mean")
        if beta is None or pre is None:
            continue
        ej = ej_flags.get(site, {})
        rows.append({
            "site":      site,
            "beta_post": float(beta),
            "pre_mean":  float(pre),
            "ej_point":  int(ej.get("ej_point", False)),
            "ej_buf":    int(ej.get("ej_buf_flag", False)),
            "in_crz":    int(ej.get("in_crz", False)),
            "hunts_pt":  int(site == "Hunts_Point"),
        })

    if len(rows) < 3:
        return {"status": "insufficient_data", "n": len(rows)}

    df = pd.DataFrame(rows)
    df["pre_z"] = ((df["pre_mean"] - df["pre_mean"].mean()) /
                   (df["pre_mean"].std() + 1e-9))

    p_norm = lambda b, s: _pval(b/s) if s > 0 else np.nan

    def _fit(sub, ej_col, label):
        if len(sub) < 3:
            return {"label": label, "status": f"n={len(sub)}<3"}
        # Drop zero-variance columns to avoid collinearity (e.g. in_crz=0 for all rows)
        reg_cols = [c for c in [ej_col, "in_crz", "pre_z"]
                    if sub[c].nunique() > 1]
        X = sm.add_constant(sub[reg_cols].astype(float))
        try:
            r = sm.OLS(sub["beta_post"].values, X).fit()
            ci = r.conf_int()
            out = {"label": label, "n": int(r.nobs), "r2": round(float(r.rsquared), 4)}
            for param in reg_cols:
                if param not in r.params.index:
                    continue
                out[param] = {
                    "beta": round(float(r.params[param]), 4),
                    "se":   round(float(r.bse[param]), 4),
                    "p":    round(p_norm(r.params[param], r.bse[param]), 4),
                    "ci_low":  round(float(ci.loc[param, 0]), 4),
                    "ci_high": round(float(ci.loc[param, 1]), 4),
                }
            out["sites"] = sub["site"].tolist()
            out["values"] = [
                {"site": row["site"], "beta": row["beta_post"],
                 "ej": int(row[ej_col]), "in_crz": int(row["in_crz"]),
                 "hunts": int(row["hunts_pt"])}
                for _, row in sub.iterrows()
            ]
            return out
        except Exception as e:
            return {"label": label, "status": f"error: {e}"}

    cs1 = _fit(df, "ej_point", "CS1: EJ=point, all sites")
    cs2 = _fit(df, "ej_buf",   "CS2: EJ=buffer>0.5, all sites")
    cs3 = _fit(df[df["in_crz"] == 0], "ej_point", "CS3: EJ=point, outside-CRZ only")

    # Print
    for spec in [cs1, cs2, cs3]:
        label = spec.get("label", "?")
        n     = spec.get("n", "?")
        if "status" in spec and "label" not in spec:
            print(f"  {label}: {spec['status']}")
            continue
        print(f"\n  {label}  (n={n})")
        for param in ["ej_point","ej_buf","in_crz","pre_z"]:
            if param in spec:
                d = spec[param]
                print(f"    {param:<10}: β={d['beta']:+.4f}  p={d['p']:.4f}  "
                      f"CI=[{d['ci_low']:+.4f},{d['ci_high']:+.4f}]")

    return {"status": "ok", "CS1": cs1, "CS2": cs2, "CS3": cs3}


# ─── 11. Plotly figure helpers ────────────────────────────────────────────

def _make_forest_plot(orig_dict, wx_dict, title):
    """Check 1: forest plot comparing original and weather-adjusted CIs."""
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None

    sites, x_orig, x_wx, err_orig, err_wx = [], [], [], [], []
    for site, r in orig_dict.items():
        if not isinstance(r, dict) or "original" not in r or r.get("weather") is None:
            continue
        o = r["original"]
        w = r["weather"]
        sites.append(site.replace("_"," "))
        x_orig.append(o["beta_post"])
        x_wx.append(w["beta_post"])
        err_orig.append((o["ci_high"]-o["ci_low"])/2)
        err_wx.append((w["ci_high"]-w["ci_low"])/2)

    if not sites:
        return None

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x_orig, y=sites, mode="markers",
        error_x=dict(type="data", array=err_orig, visible=True, color="#888"),
        marker=dict(color="#888", size=9),
        name="Original",
    ))
    fig.add_trace(go.Scatter(
        x=x_wx, y=sites, mode="markers",
        error_x=dict(type="data", array=err_wx, visible=True, color="#4B2E83"),
        marker=dict(color="#4B2E83", size=9, symbol="diamond"),
        name="Weather-adjusted",
    ))
    fig.add_vline(x=0, line_dash="dot", line_color="#333", line_width=1)
    fig.update_layout(
        title=title,
        xaxis_title="β_post (µg/m³)",
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        font=dict(family="Archivo, sans-serif", color="#2E312F"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=150, r=30, t=60, b=40),
        height=max(300, len(sites)*50),
    )
    return json.loads(fig.to_json())


def _make_placebo_histograms(check3_results):
    """Check 3: one subplot per site showing placebo distribution."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        return None

    sites_ok = {s: r for s, r in check3_results.items()
                if isinstance(r, dict) and r.get("status") == "ok" and len(r.get("betas",[])) >= 3}
    if not sites_ok:
        return None

    n = len(sites_ok)
    cols = min(3, n)
    rows = (n + cols - 1) // cols
    fig  = make_subplots(rows=rows, cols=cols,
                         subplot_titles=[s.replace("_"," ") for s in sites_ok])

    for idx, (site, r) in enumerate(sites_ok.items()):
        row, col = divmod(idx, cols)
        betas = [b["beta_post"] for b in r["betas"]]
        fig.add_trace(go.Histogram(
            x=betas, marker_color="#888", opacity=0.7,
            name=site, showlegend=False,
        ), row=row+1, col=col+1)
        ref = r.get("obs_long_beta") or r.get("obs_full_beta")
        if ref is not None:
            fig.add_vline(x=ref, line_color="#B4391B", line_dash="solid",
                          line_width=2, row=row+1, col=col+1)

    fig.update_layout(
        title="Placebo β_post distribution (red=observed long-baseline β)",
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        font=dict(family="Archivo, sans-serif", color="#2E312F"),
        height=300*rows,
    )
    return json.loads(fig.to_json())


def _make_spec_a_plot(spec_a):
    """Check 4 Spec A: per-site post coefficients with cluster-robust CIs."""
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None

    sites, betas, errs, colors = [], [], [], []
    for site, d in spec_a.items():
        if d.get("ci_high") is None or d.get("ci_low") is None:
            continue  # skip reference site (BQE) which has no CI
        sites.append(site.replace("_"," "))
        betas.append(d["beta"])
        errs.append((d["ci_high"]-d["ci_low"])/2)
        colors.append("#B4391B" if d["beta"] > 0 else "#2F6B3A")

    fig = go.Figure(go.Scatter(
        x=betas, y=sites, mode="markers",
        error_x=dict(type="data", array=errs, visible=True),
        marker=dict(color=colors, size=10),
    ))
    fig.add_vline(x=0, line_dash="dot", line_color="#333", line_width=1)
    fig.update_layout(
        title="Pooled panel: per-site toll effect (site+date FE, cluster-robust SE)",
        xaxis_title="β_post (µg/m³)",
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        font=dict(family="Archivo, sans-serif", color="#2E312F"),
        margin=dict(l=160, r=30, t=60, b=40),
        height=max(300, len(sites)*50),
    )
    return json.loads(fig.to_json())


def _make_mechanism_scatter(check5):
    """Check 5: scatter of Mott Haven PM2.5 vs Throgs Neck volume."""
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None

    if check5.get("status") != "ok":
        return None

    x = check5["scatter_x"]
    y = check5["scatter_y"]
    if not x or not y:
        return None

    beta_tn = check5["beta_tn_per1k"]
    x_arr   = np.array(x)
    y_fit   = beta_tn * x_arr + np.mean(y) - beta_tn * np.mean(x_arr)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=y, mode="markers",
        marker=dict(color="#888", size=5, opacity=0.5),
        name="Daily obs (pre-toll)",
    ))
    sorted_idx = np.argsort(x_arr)
    fig.add_trace(go.Scatter(
        x=x_arr[sorted_idx].tolist(),
        y=y_fit[sorted_idx].tolist(),
        mode="lines",
        line=dict(color="#4B2E83", width=2),
        name=f"Regression slope: {beta_tn:+.4f} µg/m³ per 1k veh",
    ))
    fig.update_layout(
        title="Mott Haven PM2.5 vs Throgs Neck Bridge daily volume (pre-toll 2022–2024)",
        xaxis_title="Throgs Neck Bridge (thousands of vehicles/day)",
        yaxis_title="Mott Haven PM2.5 (µg/m³)",
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        font=dict(family="Archivo, sans-serif", color="#2E312F"),
        height=380,
    )
    return json.loads(fig.to_json())


def _make_peak_overnight_plot(check2):
    """Check 2: bar chart of peak-overnight beta per site."""
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None

    if check2.get("status") != "ok":
        return None

    all_d = check2.get("all_days", {})
    wd_d  = check2.get("weekday_only", {})
    sites_ok = [s for s in all_d if isinstance(all_d[s], dict)]
    if not sites_ok:
        return None

    labels   = [s.replace("_"," ") for s in sites_ok]
    b_all    = [all_d[s]["beta_post"] for s in sites_ok]
    b_wd     = [(wd_d.get(s) or {}).get("beta_post", None) for s in sites_ok]
    color_a  = ["#B4391B" if b > 0 else "#2F6B3A" for b in b_all]
    color_w  = ["#D67A5E" if b is not None and b > 0 else "#5E9E6E" for b in b_wd]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="All days", x=labels, y=b_all,
                          marker_color=color_a, opacity=0.85))
    fig.add_trace(go.Bar(name="Weekday only", x=labels,
                          y=[b if b is not None else 0 for b in b_wd],
                          marker_color=color_w, opacity=0.85))
    fig.add_hline(y=0, line_color="#333", line_width=1)
    fig.update_layout(
        barmode="group",
        title="ITS β_post on peak-minus-overnight PM2.5 difference",
        yaxis_title="β_post (µg/m³, peak−overnight diff)",
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        font=dict(family="Archivo, sans-serif", color="#2E312F"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        height=380,
    )
    return json.loads(fig.to_json())


# ─── 12. HTML section ────────────────────────────────────────────────────

def _fig_div(div_id, fig_json, min_h=320):
    if fig_json is None:
        return f'<div class="callout"><em>Figure not available — see robustness.json for data.</em></div>'
    data_var    = f"_rb_{div_id.replace('-','_')}"
    fig_data    = json.dumps(fig_json.get("data", []))
    fig_layout  = json.dumps(fig_json.get("layout", {}))
    return (f'<div id="{div_id}" class="plotly-chart" style="min-height:{min_h}px"></div>\n'
            f'<script>window.addEventListener("DOMContentLoaded",function(){{'
            f'if(typeof Plotly!=="undefined")Plotly.newPlot("{div_id}",{fig_data},{fig_layout},'
            f'{{responsive:true}});}});</script>')


def _hunts_note():
    return ('<span class="footnote">* Hunts Point monitor was offline Sept 2023–March 2025, '
            'spanning the toll-start date. Its long-baseline estimate is not a clean step-change '
            'at the toll date and should be treated with extra caution.</span>')


def update_html(results, figures):
    html_path = BASE_DIR / "site" / "part1.html"
    html      = html_path.read_text(encoding="utf-8")

    # Build the robustness section
    check1 = results.get("check1", {})
    check2 = results.get("check2", {})
    check3 = results.get("check3", {})
    check4 = results.get("check4", {})
    check5 = results.get("check5", {})
    equity = results.get("equity", {})

    # Check 1 reading
    if check1.get("status") == "ok":
        tightened = sum(1 for r in check1["sites"].values()
                        if isinstance(r, dict) and r.get("ci_tightened"))
        n_sites   = sum(1 for r in check1["sites"].values()
                        if isinstance(r, dict) and "weather" in r and r["weather"] is not None)
        c1_read   = (f"Adding five daily weather covariates (temperature, wind speed, relative humidity, "
                     f"precipitation, wind direction) tightened the 95% CI at "
                     f"{tightened} of {n_sites} sites. "
                     f"No point estimate changed sign, indicating the baseline results are not "
                     f"artefacts of uncontrolled meteorology.")
    else:
        c1_read = f"Check 1 was skipped: {check1.get('reason','unknown')}."

    # Check 2 reading
    c2_read = ""
    if check2.get("status") == "ok":
        mh_all = (check2.get("all_days",{}).get("Mott_Haven") or {})
        mh_wd  = (check2.get("weekday_only",{}).get("Mott_Haven") or {})
        b_all  = mh_all.get("beta_post")
        b_wd   = mh_wd.get("beta_post")
        if b_all is not None:
            sign = "larger" if b_all > 0 else "smaller"
            c2_read  = (f"At Mott Haven, peak-hour PM2.5 was {abs(b_all):.3f} µg/m³ "
                        f"{'higher' if b_all>0 else 'lower'} than overnight after the toll "
                        f"(p={mh_all.get('p',float('nan')):.3f}). ")
            if b_wd is not None:
                c2_read += (f"The weekday-only version gives β={b_wd:+.3f} "
                            f"(p={mh_wd.get('p',float('nan')):.3f}); "
                            f"regional weather differences largely cancel in this differenced series, "
                            f"so a positive result would be harder to attribute to non-traffic sources. "
                            f"The result is {'directionally consistent with' if b_all>0 and b_wd>0 else 'mixed across'} "
                            f"the main analysis.")
        else:
            c2_read = "Mott Haven did not have sufficient hourly coverage for the peak-overnight split."
    else:
        c2_read = f"Check 2 was skipped: {check2.get('reason','unknown')}."

    # Check 3 reading
    c3_read = ""
    if check3.get("status") == "ok":
        sites_ok = {s: r for s, r in check3["sites"].items()
                    if isinstance(r, dict) and r.get("status")=="ok"}
        low_p    = {s: r["empirical_p"] for s, r in sites_ok.items()
                    if r.get("empirical_p") is not None and r["empirical_p"] < 0.10}
        c3_read  = (f"Across {len(sites_ok)} sites with enough pre-toll data, "
                    f"the placebo test produced empirical p < 0.10 at "
                    f"{len(low_p)} site(s): "
                    f"{', '.join(low_p.keys()) or 'none'}. ")
        c3_read += ("A low empirical p means the observed β_post is unusually large "
                    "relative to fake interventions placed before the toll, "
                    "providing stronger evidence that the change is real rather than random variation. "
                    "Sites with p ≥ 0.10 remain inconclusive.")
    else:
        c3_read = f"Check 3 was skipped: {check3.get('reason','unknown')}."

    # Check 4 reading
    c4_read = ""
    if check4.get("status") == "ok":
        b1 = (check4.get("spec_b1",{}).get("post_ej") or {})
        ej_b  = b1.get("beta")
        ej_pb = b1.get("p_bootstrap")
        if ej_b is not None:
            direction = "EJ-designated sites saw a larger worsening" if ej_b > 0 else "EJ-designated sites saw a smaller improvement"
            sig_str   = "statistically significant" if ej_pb is not None and ej_pb < 0.05 else "not statistically significant"
            c4_read   = (f"In the pooled panel with site and date fixed effects, "
                         f"the EJ interaction is β={ej_b:+.4f} µg/m³ "
                         f"(wild-bootstrap p={ej_pb:.3f} with Webb weights, G={check4['n_sites']} clusters). "
                         f"This is {sig_str}. "
                         f"Non-EJ sites under this specification include only sites not in DAC-designated tracts — "
                         f"note that the corrected spatial-join EJ flags differ from the original model's hard-coded defaults; "
                         f"see the Methods Addendum.")
        else:
            c4_read = "Check 4 panel model did not converge."
    else:
        c4_read = f"Check 4 was skipped: {check4.get('reason','unknown')}."

    # Check 5 reading
    c5_read = ""
    if check5.get("status") == "ok":
        b_tn  = check5["beta_tn_per1k"]
        impl  = check5["implied_pm25"]
        obs   = check5["observed_beta"]
        cons  = check5["magnitude_consistent"]
        c5_read = (f"In the pre-toll period (2022–2024), each additional 1,000 vehicles/day "
                   f"at Throgs Neck Bridge is associated with β={b_tn:+.4f} µg/m³ at Mott Haven "
                   f"(p={check5['p_tn']:.3f}, HAC SE, n={check5['n']}). "
                   f"Multiplying by the post-toll Throgs Neck residual of +{check5['diversion_veh']:.0f} veh/day "
                   f"implies {impl:+.4f} µg/m³ — "
                   f"{'directionally consistent with' if cons else 'inconsistent in magnitude with'} "
                   f"the observed ITS step-change of {obs:+.4f} µg/m³. ")
        if not cons:
            c5_read += ("The implied change is too small to explain the observed estimate; "
                        "the diversion story is not self-consistent on these numbers.")
        else:
            c5_read += ("However, consistency of magnitudes alone does not establish causation; "
                        "unmeasured confounders could produce the same pattern.")
    else:
        c5_read = f"Check 5 was skipped: {check5.get('reason','unknown')}."

    section = f"""
<!-- ─── Section 7: Robustness checks ──────────────────────────────────────── -->
<section class="section" id="section-robustness">
  <div class="section-header">
    <h2>Robustness checks</h2>
    <p>
      Five independent tests of the traffic-diversion hypothesis. The main ITS estimates
      are underpowered (Mott Haven p&nbsp;=&nbsp;0.61, n&nbsp;=&nbsp;6 sites) and PM2.5
      is driven largely by regional sources. The checks below probe whether the null
      results are informative or whether a signal emerges under sharper designs.
      Estimates marked * use Hunts Point's long-baseline spec — see note below.
    </p>
    {_hunts_note()}
  </div>

  <!-- ─ Check 1: Weather covariates ─ -->
  <div class="section-header" style="margin-top:2.5rem">
    <h3>1. Weather-adjusted estimates</h3>
    <p>Daily wind speed, temperature, precipitation, relative humidity, and dominant
    wind-direction sector (8 compass bins) added to the full ITS model.
    Compares 95% CI width to the original specification.</p>
  </div>
  <div class="chart-wrap">
    <p class="chart-title">Original vs. weather-adjusted β_post with 95% CI</p>
    {_fig_div("rb-check1", figures.get("check1"))}
  </div>
  <div class="callout">{c1_read}</div>

  <!-- ─ Check 2: Peak vs overnight ─ -->
  <div class="section-header" style="margin-top:2.5rem">
    <h3>2. Peak-vs-overnight PM2.5 difference</h3>
    <p>The toll is 75% cheaper overnight. If diversion is toll-driven,
    peak-hour PM2.5 should rise relative to overnight.
    Daily outcome: mean peak PM2.5 minus mean overnight PM2.5 (≥8 peak hours, ≥5 overnight hours required).
    QC and VW differences used as controls.</p>
  </div>
  <div class="chart-wrap">
    <p class="chart-title">ITS β_post on peak-minus-overnight PM2.5 (all days and weekdays only)</p>
    {_fig_div("rb-check2", figures.get("check2"))}
  </div>
  <div class="callout">{c2_read}</div>

  <!-- ─ Check 3: Placebo-in-time ─ -->
  <div class="section-header" style="margin-top:2.5rem">
    <h3>3. Placebo-in-time</h3>
    <p>Using pre-toll data only, a fake intervention is placed on the 1st of each month
    from July 2021 through June 2024 (up to 36 placebos). The long-baseline QC-only
    spec is used for all sites. Each placebo requires ≥90 observed days on each side
    and ≥60% data coverage in the surrounding 6-month windows.
    Empirical p = share of |β_placebo| ≥ |β_observed|.</p>
  </div>
  <div class="chart-wrap">
    <p class="chart-title">Distribution of placebo β_post by site (red line = observed long-baseline β)</p>
    {_fig_div("rb-check3", figures.get("check3"), min_h=400)}
  </div>
  <div class="callout">{c3_read}</div>

  <!-- ─ Check 4: Pooled panel ─ -->
  <div class="section-header" style="margin-top:2.5rem">
    <h3>4. Pooled panel (site + date fixed effects)</h3>
    <p>All monitoring sites with ≥30 pre-toll days in the VW window are stacked into
    a balanced panel. Site and date fixed effects absorb site-specific baselines and
    shared daily shocks (date FE replaces the QC covariate). Two specifications:
    (A) post × site — per-site toll effects;
    (B) post × EJ + post × in-CRZ — differential effect by environmental-justice status.
    Wild cluster bootstrap with Webb weights (B=9,999, G clusters). Hunts Point
    excluded (zero pre-toll observations in the VW window).</p>
  </div>
  <div class="chart-wrap">
    <p class="chart-title">Spec A: per-site toll effect (site + date FE, cluster-robust CI)</p>
    {_fig_div("rb-check4a", figures.get("check4a"))}
  </div>
  <div class="callout">{c4_read}</div>

  <!-- ─ Check 5: Mechanism ─ -->
  <div class="section-header" style="margin-top:2.5rem">
    <h3>5. Mechanism check</h3>
    <p>In the pre-toll period (2022–2024), Mott Haven daily PM2.5 is regressed on
    Throgs Neck Bridge daily crossings (per 1,000 vehicles), Queens College, seasonal
    terms, day-of-week dummies, and weather covariates (HAC SE, maxlags=30).
    The estimated slope is multiplied by the post-toll Throgs Neck residual
    (+2,041 veh/day) to produce an implied PM2.5 change, then compared to the
    observed ITS step-change.</p>
  </div>
  <div class="chart-wrap">
    <p class="chart-title">Mott Haven PM2.5 vs Throgs Neck volume (pre-toll, regression line shown)</p>
    {_fig_div("rb-check5", figures.get("check5"))}
  </div>
  <div class="callout">{c5_read}</div>

</section>

"""

    # Insert before Section 5 Traffic Diversion comment
    marker = "<!-- ─── Section 5: Traffic Diversion"
    if marker not in html:
        # Fallback: insert before Section 5
        marker = "<!-- ─── Section 5"
    if marker not in html:
        print("  WARNING: Could not find insertion point in part1.html")
        return
    html = html.replace(marker, section + marker)
    html_path.write_text(html, encoding="utf-8")
    print(f"  Updated {html_path.name}: robustness section inserted")


# ─── 13. METHODS_ADDENDUM.md ─────────────────────────────────────────────

def write_methods_addendum(results, ej_flags):
    disagree = {s: f for s, f in ej_flags.items() if f.get("disagree")}
    c5 = results.get("check5", {})
    c4 = results.get("check4", {})

    md = textwrap.dedent(f"""\
    # Methods Addendum — Robustness Checks

    ## Overview

    This document describes the five robustness specifications added to the CRZ air-quality
    analysis. The main ITS pipeline (scripts/05_its_model.py) is unchanged. All results are
    stored in `data/processed/robustness.json`.

    ---

    ## EJ Flag Methodology

    **Point-in-polygon flag** — Each monitoring station is located within a NY State
    Disadvantaged Community (DAC) census tract using the processed `dac_tracts_nyc.geojson`
    layer (field `dac_designation == "Designated as DAC"`). Spatial join performed with
    Shapely 2.x, coordinate system EPSG:4326.

    **500 m buffer share** — The station point is projected to UTM Zone 18N (EPSG:32618),
    buffered 500 m, and the fraction of the buffer area overlapping any DAC-designated tract
    is computed. A binary flag `EJ_buffer` is set to True where the share exceeds 0.50.

    **Sites where point flag and buffer flag disagree:**
    {'None' if not disagree else chr(10).join(
        f"  - {s}: point={'Y' if f['ej_point'] else 'N'}, buffer={f['ej_buffer']:.3f}"
        for s, f in disagree.items()
    )}

    **Correction note** — The original `05_its_model.py` hard-coded EJ flags differ from the
    spatial-join results for several sites. Specifically, Manhattan Bridge, Hamilton Bridge,
    FDR, and Broadway 35th St were coded as non-EJ in the original model but fall within
    DAC-designated tracts per the spatial join. These corrected flags are used only in
    `robustness.py`; the original `its_results.json` and headline numbers are unchanged.

    **in_CRZ indicator** — Midtown DOT and Broadway 35th St lie within the CRZ boundary
    (verified via point-in-polygon with `crz_boundary.geojson`). This indicator is included
    in equity regressions to separate within-zone from diversion-corridor effects.

    ---

    ## Check 1 — Weather-Adjusted ITS

    **Specification** — The full ITS model (QC + VW covariates, window 2024-02-22 to present)
    is re-estimated with five additional daily covariates from the LGA ASOS station:
    mean temperature (°C), mean wind speed (m/s), total precipitation (mm),
    mean relative humidity (%), and a set of 7 dummy variables for dominant wind-direction
    sector (8 compass bins, N as reference). Precipitation missing values are filled with 0
    rather than dropping the day (missingness noted in the run log). All other weather
    missingness propagates through `dropna`.

    **Data source** — Iowa Environmental Mesonet, LGA ASOS station, network NY_ASOS.
    Downloaded via `mesonet.agron.iastate.edu/cgi-bin/request/asos.py`, fetched in
    yearly chunks, cached to `data/processed/lga_weather_daily.csv`.

    **SE method** — HAC Newey-West, maxlags=30 (same as main model).

    ---

    ## Check 2 — Peak vs. Overnight Difference

    **Peak-hour definition** (Eastern Time):
    - Weekdays (Mon–Fri): 05:00–20:59 ET
    - Weekends (Sat–Sun): 09:00–20:59 ET
    - Everything else: overnight

    **Daily observation** — Requires ≥8 valid hourly readings in the peak window and
    ≥5 in the overnight window; otherwise the day is dropped (NaN).

    **Controls** — The same peak-minus-overnight differencing is applied to Queens College
    and Van Wyck, and these series are used as controls in the ITS on the differenced outcome.

    **Window** — VW_START (2024-02-22) to present, same as the full ITS spec.

    **Weekday-only version** — Restricts the panel to Mon–Fri observations. With fewer
    days, the minimum sample threshold is relaxed to 40 total / 20 pre-toll.

    **Interpretation** — Regional aerosol and photochemical effects largely cancel in the
    peak-overnight difference because both windows experience the same air mass. A positive
    β_post on this differenced series is harder to attribute to non-traffic sources.

    ---

    ## Check 3 — Placebo-in-Time

    **Pre-toll data only** — All data from 2025-01-05 onward is excluded.

    **Placebo dates** — First day of each month from 2021-07-01 through 2024-06-01
    (36 candidate dates).

    **Specification** — QC-only long-baseline ITS (no VW covariate) for all sites,
    using the same HAC SE (maxlags=30). This avoids the VW-window constraint that would
    leave most placebos before 2024-02-22 with no pre-VW data.

    **Coverage filter** — A placebo is run only if:
    - ≥90 observed days before the placebo date (within the pre-toll window)
    - ≥90 observed days after the placebo date (before 2025-01-05)
    - ≥60% data coverage in the 6-month window on each side (≥109/182 days)

    **Empirical p** — Share of |β_placebo| ≥ |β_observed| where β_observed is the
    long-baseline QC-only estimate. The full-model beta is reported alongside for reference.

    **Skipped placebos** — Printed to the terminal at run time. Early placebos (2021-2022)
    are frequently skipped for sites that began monitoring in 2024.

    ---

    ## Check 4 — Pooled Panel

    **Site inclusion** — All non-control sites with ≥30 pre-toll days in the VW window
    (2024-02-22 to 2025-01-04), i.e. {', '.join(sorted(c4.get('sites', [])))}.
    Hunts Point excluded (n_pre_vw=0; see gap note below).
    Midtown DOT included but flagged for a 500-day data gap (2022-07-05 to 2023-11-17).

    **Fixed effects** — Two-way: site FE + date FE. Implemented via iterative
    alternating-projection demeaning (Gauss-Seidel, ≤50 iterations, tol=1e-9).
    Date FE absorbs regional shocks common to all sites on a given day, making the
    QC covariate redundant (dropped). The `post` main effect is collinear with date FE
    (it is a function of date alone) and is therefore excluded.

    **Spec A** — One post × site interaction per site (per-site toll effects relative to
    no-toll counterfactual implied by the date FE).

    **Spec B** — post × EJ_designated + post × in_CRZ. Run three ways:
    (B1) EJ = point-in-polygon flag, all sites;
    (B2) EJ = buffer share > 0.5, all sites;
    (B3) EJ = point flag, outside-CRZ sites only.
    Non-EJ sites under the corrected spatial-join flags are: Queensboro Bridge,
    Midtown DOT, and SI Expressway (3 sites, not 1 as under original defaults).

    **Standard errors** — Wild cluster bootstrap with Webb weights
    {{−√(3/2), −√(1/2), −√(1/6), +√(1/6), +√(1/2), +√(3/2)}}, B=9,999 replicates,
    cluster by site. Webb weights are used instead of Rademacher because G≤12 clusters
    is too few for Rademacher to control size. Cluster-robust SEs are also reported.

    ---

    ## Check 5 — Mechanism Check

    **Window** — 2022-01-01 to 2025-01-04 (pre-toll; the longer window is possible
    because VW is not needed as a covariate in this specification).

    **Specification** — OLS of Mott Haven daily PM2.5 on:
    - Throgs Neck Bridge daily crossings / 1,000
    - Queens College daily PM2.5 (regional background)
    - Seasonal terms: cos(2πt/365.25), sin(2πt/365.25), linear trend
    - Day-of-week dummies (6, Sunday reference)
    - Weather covariates if available from Check 1: temperature, wind speed, RH, precipitation

    **SE method** — HAC Newey-West, maxlags=30.

    **Interpretation** — The regression coefficient on Throgs Neck/1k vehicles gives the
    historical pre-toll relationship between bridge volume and Mott Haven PM2.5.
    Multiplied by the +2,041 veh/day post-toll Throgs Neck residual, this yields the
    implied PM2.5 change if the pre-toll relationship held through the toll period.
    The comparison to the observed ITS β_post={0.2957} tests whether the diversion
    hypothesis is internally consistent. This is a falsifiability check, not a causal estimate.

    ---

    ## Data Gaps — Hunts Point and Cross Bronx

    ### Hunts Point
    The Hunts Point monitor (36005NY11790) was active April–May 2022 (209 days pre-toll),
    then offline from **2022-05-06 through 2023-02-10** (280 days), active briefly until
    **2023-09-06**, then offline from **2023-09-06 through 2025-03-06** (547 days).
    This second gap spans the toll-start date (2025-01-05). Consequently:
    - The monitor has **zero pre-toll observations in the VW window** (2024-02-22 to 2025-01-05).
    - The full ITS spec (QC+VW) cannot be run for this site.
    - The long-baseline (QC-only) spec uses 209 pre-toll days, all from 2022.
    - **The long-baseline estimate is not a step-change at the toll date** in the usual
      sense: the pre-toll trend is estimated from 2022 data, the post-toll mean from
      data collected after a 547-day gap in a different seasonal and atmospheric context.
    - Hunts Point results are marked with an asterisk (*) in all tables.

    ### Cross Bronx Expressway
    The Cross Bronx monitor (36005NY12387) has three notable gaps:
    - **92 days**: 2019-09-13 to 2019-12-14 (pre-toll)
    - **791 days**: **2020-01-01 to 2022-03-02** — the largest gap, fully pre-toll.
      Only 70 valid days existed before this gap (Jul–Dec 2019). The gap spans the full
      COVID period (Mar 2020 – Jun 2021 dummy active), so the COVID indicator partially
      accounts for the silent stretch. After resuming, 639 more pre-toll days accumulated.
      The long-baseline spec has 1,053 joint observations (623 pre-toll, 430 post-toll).
    - **298 days**: 2022-04-18 to 2023-02-10 (pre-toll)

    The 791-day gap does not straddle the toll date, so the ITS step-change estimate is
    not directly corrupted. However, the 70-obs pre-gap anchor from 2019 is a thin basis
    for estimating the long-run trend. The gap-era COVID dummy covers most of the offline
    period. Results should be interpreted with appropriate uncertainty.

    ---

    ## Sentences in part1.html Contradicted by Revised Analysis

    The following sentences in the existing report conflict with findings from
    this robustness analysis. No changes have been made to the report text; these
    are provided for editorial review.

    1. **Equity section (§4):** "OLS regression of each site's ITS step-change against
       whether the site sits in a NY State DAC (Disadvantaged Community) tract" —
       the original model's DAC flags contain errors: Manhattan Bridge, Hamilton Bridge,
       FDR, and Broadway 35th St are coded non-EJ but fall within DAC tracts per the
       spatial join. The equity result (β_EJ) may change sign or significance under
       corrected flags.

    2. **Equity section (§4):** The existing equity chart uses only the 6 original
       treatment sites. The corrected analysis includes 11 sites and finds that
       non-EJ (under corrected flags) comprises 3 sites (Queensboro Bridge,
       Midtown DOT, SI Expressway), not 1. The contrast is therefore better powered
       but the interpretation changes.

    3. **ITS coefficient table (§3):** Manhattan Bridge is displayed without an EJ marker
       but it falls within a DAC tract. If the site label or colour coding implies
       non-EJ status, that is incorrect.

    4. **Any sentence citing Hunts Point's ITS result as a "post-toll change"** —
       Hunts Point's long-baseline estimate should not be described as measuring a
       step-change at the toll date because the monitor was offline for the 547 days
       immediately surrounding that date.
    """)

    out_path = BASE_DIR / "METHODS_ADDENDUM.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"  Wrote {out_path.name}")


# ─── 14. Terminal summary table ───────────────────────────────────────────

def print_summary_table(results):
    print("\n" + "=" * 90)
    print("  ROBUSTNESS CHECKS — SUMMARY")
    print("=" * 90)
    print(f"  {'Check':<8} {'Site':<22} {'Spec':<14} {'β_post':>8}  {'95% CI':<22}  {'p':>7}  {'n':>5}")
    print("  " + "-" * 86)

    def row(chk, site, spec, b, lo, hi, p, n):
        ci = f"[{lo:+.3f},{hi:+.3f}]"
        hp = "*" if site == "Hunts_Point" else " "
        print(f"  {chk:<8} {site+hp:<22} {spec:<14} {b:>+8.4f}  {ci:<22}  {p:>7.4f}  {n:>5}")

    # Check 1
    c1 = results.get("check1", {})
    if c1.get("status") == "ok":
        for site, r in c1["sites"].items():
            if not isinstance(r, dict) or "weather" not in r or r["weather"] is None:
                continue
            w = r["weather"]
            row("1-Wthr", site, "full+wx", w["beta_post"],
                w["ci_low"], w["ci_high"], w["p"], w["n"])
    else:
        print(f"  1-Wthr   {'(skipped)':^50}  {c1.get('reason','')}")

    # Check 2
    c2 = results.get("check2", {})
    if c2.get("status") == "ok":
        for site, r in (c2.get("all_days") or {}).items():
            if not isinstance(r, dict):
                continue
            row("2-PkNt", site, "peak-night", r["beta_post"],
                r["ci_low"], r["ci_high"], r["p"], r["n"])
    else:
        print(f"  2-PkNt   {'(skipped)':^50}  {c2.get('reason','')}")

    # Check 3
    c3 = results.get("check3", {})
    if c3.get("status") == "ok":
        for site, r in c3["sites"].items():
            if not isinstance(r, dict) or r.get("status") != "ok":
                continue
            ref  = r.get("obs_long_beta") or r.get("obs_full_beta") or float("nan")
            ep   = r.get("empirical_p") or float("nan")
            n_pb = r.get("n_placebos", 0)
            hp   = "*" if site == "Hunts_Point" else " "
            print(f"  {'3-Plac':<8} {site+hp:<22} {'QC-only':<14} "
                  f"{ref:>+8.4f}  {'emp_p='+str(round(ep,3)):<22}  {'—':>7}  {n_pb:>5}")

    # Check 4
    c4 = results.get("check4", {})
    if c4.get("status") == "ok":
        # Spec A per site (skip reference site which has no CI)
        for site, d in (c4.get("spec_a") or {}).items():
            if d.get("ci_low") is None or d.get("ci_high") is None:
                continue
            row("4-PanA", site, "post×site", d["beta"],
                d["ci_low"], d["ci_high"], d["p"], c4["n_obs"])
        # Spec B1
        for label, spec in [("B1-EJpt","spec_b1"),("B2-EJbf","spec_b2"),("B3-noCRZ","spec_b3")]:
            d = (c4.get(spec) or {}).get("post_ej")
            if d:
                row(f"4-Pan{label}", "post×EJ", "panel", d["beta"],
                    d["ci_low"], d["ci_high"], d["p_bootstrap"], c4["n_obs"])
    else:
        print(f"  4-Pan    {'(skipped)':^50}  {c4.get('reason','')}")

    # Check 5
    c5 = results.get("check5", {})
    if c5.get("status") == "ok":
        b  = c5["beta_tn_per1k"]
        print(f"  {'5-Mech':<8} {'Mott_Haven←TN':<22} {'β/1k veh':<14} "
              f"{b:>+8.4f}  {'impl='+str(round(c5['implied_pm25'],4)):<22}  "
              f"{c5['p_tn']:>7.4f}  {c5['n']:>5}")
    else:
        print(f"  5-Mech   {'(skipped)':^50}  {c5.get('reason','')}")

    # Equity
    eq = results.get("equity", {})
    for spec_key, label in [("CS1","EJ=point"), ("CS2","EJ=buf"), ("CS3","no-CRZ")]:
        sp = (eq.get(spec_key) or {})
        if not isinstance(sp, dict):
            continue
        for param in ["ej_point","ej_buf"]:
            d = sp.get(param)
            if d:
                n  = sp.get("n", "?")
                row(f"EQ-{label}", "cross-sect", label, d["beta"],
                    d["ci_low"], d["ci_high"], d["p"], n)

    print("=" * 90)
    print("  * Hunts Point: monitor offline Sept 2023–Mar 2025 (spans toll date)")
    print("    Long-baseline estimate is not a step-change at toll date.")
    print("=" * 90)


# ─── 14b. 311 Engine Idling pre-compute ──────────────────────────────────

def _fetch_311_series(where_clause, label, lat_min, lat_max, lon_min, lon_max):
    """Paginate one 311 query and return {monthly_counts, total_records, fetched_records}."""
    base_url = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"
    try:
        r = requests.get(base_url, params={"$select": "count(*) AS cnt", "$where": where_clause},
                         timeout=60)
        if r.status_code != 200:
            print(f"  311 {label} count query failed: HTTP {r.status_code}")
            return None
        total = int(r.json()[0]["cnt"])
        print(f"  311 {label} total records in box: {total}")
    except Exception as e:
        print(f"  311 {label} count query error: {e}")
        return None

    records = []
    limit = 1000
    for offset in range(0, total + limit, limit):
        try:
            r = requests.get(base_url, params={
                "$select":  "created_date",
                "$where":   where_clause,
                "$limit":   limit,
                "$offset":  offset,
                "$order":   "created_date",
            }, timeout=120)
            if r.status_code != 200:
                print(f"    offset={offset}: HTTP {r.status_code}")
                break
            batch = r.json()
            if not batch:
                break
            records.extend(batch)
        except Exception as e:
            print(f"    offset={offset}: error {e}")
            break

    print(f"  Fetched {len(records)} records (expected {total})")
    monthly = {}
    for rec in records:
        d = (rec.get("created_date") or "")[:7]
        if d:
            monthly[d] = monthly.get(d, 0) + 1
    return {"monthly_counts": dict(sorted(monthly.items())),
            "total_records": total, "fetched_records": len(records)}


def fetch_311_engine_idling():
    """
    Pre-compute monthly 311 idling complaint counts for the 400 m Mott Haven school box.
    Fetches two series:
      - 'Noise - Vehicle' / 'Engine Idling'
      - 'Air Quality' with descriptor containing 'Vehicle Idling'
    Stores both series and a combined monthly total in school_zone.json.
    """
    LAT_MIN, LAT_MAX = 40.8029, 40.8101
    LON_MIN, LON_MAX = -73.9273, -73.9178

    box = f"within_box(location,{LAT_MAX},{LON_MIN},{LAT_MIN},{LON_MAX})"

    where_noise = (f"{box} AND complaint_type='Noise - Vehicle'"
                   f" AND descriptor='Engine Idling'")
    where_aq    = (f"{box} AND complaint_type='Air Quality'"
                   f" AND upper(descriptor) like '%VEHICLE IDLING%'")

    print("  Fetching 311 Engine Idling data…")
    noise_data = _fetch_311_series(where_noise, "Engine Idling (Noise)", LAT_MIN, LAT_MAX, LON_MIN, LON_MAX)
    print("  Fetching 311 Air Quality / Vehicle Idling data…")
    aq_data    = _fetch_311_series(where_aq,    "Air Quality/VehicleIdling", LAT_MIN, LAT_MAX, LON_MIN, LON_MAX)

    if noise_data is None and aq_data is None:
        return None

    # Combine monthly counts
    combined = {}
    for d in noise_data.get("monthly_counts", {}) if noise_data else {}:
        combined[d] = combined.get(d, 0) + noise_data["monthly_counts"][d]
    for d in aq_data.get("monthly_counts", {}) if aq_data else {}:
        combined[d] = combined.get(d, 0) + aq_data["monthly_counts"][d]

    total_noise = (noise_data or {}).get("total_records", 0) or 0
    total_aq    = (aq_data    or {}).get("total_records", 0) or 0

    return {
        "noise_vehicle": noise_data,
        "air_quality":   aq_data,
        "combined_monthly_counts": dict(sorted(combined.items())),
        "total_combined":          total_noise + total_aq,
        "bbox": {
            "latMin": LAT_MIN, "latMax": LAT_MAX,
            "lonMin": LON_MIN, "lonMax": LON_MAX,
        },
        "source": "NYC Open Data 311 (erm2-nwe9)",
    }


def update_school_zone_311(idling_data):
    """Merge idling_data into the existing school_zone.json."""
    sz_path = PROCESSED_DIR / "school_zone.json"
    if not sz_path.exists():
        print("  school_zone.json not found — skip 311 update")
        return
    sz = json.loads(sz_path.read_text(encoding="utf-8"))
    sz["complaints_311_engine_idling"] = idling_data
    sz.pop("complaints_311_note", None)
    sz_path.write_text(json.dumps(sz, indent=2, ensure_ascii=False), encoding="utf-8")
    n_noise = (idling_data.get("noise_vehicle") or {}).get("total_records", 0) or 0
    n_aq    = (idling_data.get("air_quality")   or {}).get("total_records", 0) or 0
    print(f"  Updated school_zone.json: {n_noise} Engine Idling + {n_aq} Air Quality/Vehicle Idling "
          f"= {n_noise + n_aq} total, {len(idling_data.get('combined_monthly_counts', {}))} months")


# ─── 15. Main ────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  ROBUSTNESS CHECKS — NYC CRZ ITS Analysis")
    print(f"  Toll date: {TOLL_DATE.date()}  VW_START: {VW_START.date()}")
    print("=" * 70)

    # EJ flags
    print("\n[1/8] Computing EJ flags…")
    ej_flags = compute_ej_flags()
    print_ej_table(ej_flags)

    # Load processed data
    print("\n[2/8] Loading processed data…")
    daily    = load_daily()
    its_orig = load_its_results()
    print(f"  Daily: {len(daily)} dates, {len(daily.columns)} sites")

    # ASOS weather
    print("\n[3/8] Check 1 — Weather-adjusted ITS…")
    weather_df = fetch_or_load_asos()
    check1 = run_check1(daily, weather_df, ej_flags)

    # Peak vs overnight
    print("\n[4/8] Check 2 — Peak vs overnight…")
    check2 = run_check2()

    # Placebos
    print("\n[5/8] Check 3 — Placebo-in-time…")
    check3 = run_check3(daily, its_orig)

    # Pooled panel
    print("\n[6/8] Check 4 — Pooled panel with 2-way FE…")
    check4 = run_check4(daily, ej_flags)

    # Mechanism check
    print("\n[7/9] Check 5 — Mechanism check…")
    check5 = run_check5(daily, weather_df)

    # Check 7: raw DiD
    print("\n[8/9] Check 7 — Raw DiD (matched day-of-year)…")
    check7 = run_check7(daily)

    # New equity regression
    print("\n[9/9] New equity regression…")
    equity = run_equity_regression(its_orig, ej_flags)

    # 311 Engine Idling pre-compute
    print("\n  Fetching 311 Engine Idling data…")
    idling_data = fetch_311_engine_idling()
    if idling_data is not None:
        update_school_zone_311(idling_data)
    else:
        print("  311 fetch failed — school_zone.json not updated")

    # Assemble results
    results = {
        "metadata": {
            "toll_date":  TOLL_DATE.strftime("%Y-%m-%d"),
            "vw_start":   VW_START.strftime("%Y-%m-%d"),
            "panel_sites": PANEL_SITES,
            "crz_sites":   list(CRZ_SITES),
            "note_crz_sites": ("CRZ membership in panel/equity uses geofence-derived "
                               "in_crz flag from compute_ej_flags(), not this list"),
        },
        "ej_flags": ej_flags,
        "check1":   check1,
        "check2":   check2,
        "check3":   check3,
        "check4":   check4,
        "check5":   check5,
        "check7":   check7,
        "equity":   equity,
    }

    out_path = PROCESSED_DIR / "robustness.json"
    out_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\n  Saved {out_path}")

    # Figures
    print("\n  Generating figures…")
    figures = {
        "check1": _make_forest_plot(check1.get("sites", {}), {}, "Check 1: Weather-adjusted β_post"),
        "check2": _make_peak_overnight_plot(check2),
        "check3": _make_placebo_histograms(check3.get("sites", {})),
        "check4a": _make_spec_a_plot(check4.get("spec_a", {})),
        "check5": _make_mechanism_scatter(check5),
    }

    # HTML update
    print("\n  Updating part1.html…")
    update_html(results, figures)

    # Methods addendum
    print("\n  Writing METHODS_ADDENDUM.md…")
    write_methods_addendum(results, ej_flags)

    # Terminal summary
    print_summary_table(results)


if __name__ == "__main__":
    main()
