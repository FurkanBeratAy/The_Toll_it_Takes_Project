#!/usr/bin/env python3
"""
analysis/check9_phase2.py

Check 9 Phase 2:
  1. Pull + cache PurpleAir daily-average history (average=1440).
  2. QC: drop days where |A-B| > max(5, 0.20 * mean_AB).
  3. EPA correction (Barkjohn 2021): 0.524*cf1 - 0.0862*RH + 5.75.
  4. Coverage gating: ≥80% daily coverage, ≥200 pre-toll days.
  5. Extended spec B1 + B3 (NYCCAS + PA, post×EJ + post×CRZ + post×PA).
  6. PurpleAir-only spec B (post×EJ, site+date FE, wild bootstrap).
  7. Check 7 matched-day DiD for each PA sensor (raw, −VW, −QC).
  8. Save results to robustness.json under check9.
  9. Print results table; do NOT modify site HTML.
"""

import sys, json, os, time
from pathlib import Path
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from dotenv import load_dotenv
_ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(_ENV_PATH)
_KEY = os.environ.get("PURPLEAIR_READ_KEY", "")
if not _KEY:
    sys.exit("ERROR: PURPLEAIR_READ_KEY not set in .env")

import numpy as np
import pandas as pd
import requests
from scipy.stats import norm as _sci_norm

_PROJECT      = Path(__file__).parent.parent
PROCESSED_DIR = _PROJECT / "data" / "processed"
RAW_PA_DIR    = _PROJECT / "data" / "raw" / "purpleair"
RAW_PA_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://api.purpleair.com/v1"
_HDR     = {"X-API-Key": _KEY}

TOLL_DATE   = pd.Timestamp("2025-01-05")
VW_START    = pd.Timestamp("2024-02-22")
TODAY       = datetime(2026, 9, 17, tzinfo=timezone.utc)
TODAY_PD    = pd.Timestamp("2026-09-17")

START_TS = int(datetime(2024, 2, 22, tzinfo=timezone.utc).timestamp())
END_TS   = int(TODAY.timestamp())

MIN_COV_FRAC = 0.80
MIN_PRE_DAYS = 200

# Total days in panel window (2024-02-22 → 2026-09-17)
PANEL_DAYS = (TODAY_PD - VW_START).days + 1   # ~939

WEBB = np.array([-np.sqrt(1.5), -np.sqrt(0.5), -np.sqrt(1/6),
                  np.sqrt(1/6),  np.sqrt(0.5),  np.sqrt(1.5)])

# ── Final roster (user-approved, borough from polygon check) ──────────────
# ej from dac_tracts_nyc.geojson point-in-polygon (computed in Phase 1)
ROSTER = {
    135148: {"name": "Riverdale",              "borough": "Bronx",         "ej": False},
    191419: {"name": "89th_and_Ridge",         "borough": "Brooklyn",      "ej": False},
    138844: {"name": "Neal_Phillip_BKLYN",     "borough": "Brooklyn",      "ej": False},
      4803: {"name": "W90th_CPW",              "borough": "Manhattan",     "ej": False},
     24311: {"name": "Forest_Hills",           "borough": "Queens",        "ej": False},
     91441: {"name": "SITHS256O",              "borough": "Staten_Island", "ej": False},
     81785: {"name": "RGBIV",                  "borough": "Brooklyn",      "ej": False},
    183603: {"name": "Hudson_View_Gardens",    "borough": "Manhattan",     "ej": False},
    150696: {"name": "NBN_Green_Provost",      "borough": "Brooklyn",      "ej": True},
     37185: {"name": "NBN_Bushwick_McKibbin",  "borough": "Brooklyn",      "ej": True},
     89957: {"name": "FA_O5",                  "borough": "Manhattan",     "ej": True},
    165783: {"name": "Red_Hook_Farms",         "borough": "Brooklyn",      "ej": True},
}

# NYCCAS panel sites and their flags (from existing robustness.json)
NYCCAS_PANEL = [
    "Cross_Bronx_Expy", "Mott_Haven", "Manhattan_Bridge",
    "Williamsburg_Bridge", "Queensboro_Bridge",
    "Broadway_35th_St", "FDR", "Hamilton_Bridge", "BQE", "SI_Expwy",
    "Midtown_DOT",
]


# ══════════════════════════════════════════════════════════════════════════
# 1. PurpleAir history pull
# ══════════════════════════════════════════════════════════════════════════

def _pull_history(sensor_index, cache_path):
    """Pull daily-average history in yearly chunks; return raw combined data."""
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    fields = "pm2.5_cf_1_a,pm2.5_cf_1_b,humidity"
    # Chunk into calendar years to respect any per-request limits
    chunks = [
        (int(datetime(2024,  2, 22, tzinfo=timezone.utc).timestamp()),
         int(datetime(2024, 12, 31, tzinfo=timezone.utc).timestamp())),
        (int(datetime(2025,  1,  1, tzinfo=timezone.utc).timestamp()),
         int(datetime(2025, 12, 31, tzinfo=timezone.utc).timestamp())),
        (int(datetime(2026,  1,  1, tzinfo=timezone.utc).timestamp()),
         END_TS),
    ]
    all_rows = []
    resp_fields = None

    for s_ts, e_ts in chunks:
        params = {
            "average":         1440,
            "fields":          fields,
            "start_timestamp": s_ts,
            "end_timestamp":   e_ts,
        }
        r = requests.get(
            f"{BASE_URL}/sensors/{sensor_index}/history",
            headers=_HDR, params=params, timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        if resp_fields is None:
            resp_fields = data.get("fields", [])
        all_rows.extend(data.get("data", []))
        time.sleep(0.4)   # polite spacing; key not logged

    combined = {"fields": resp_fields, "data": all_rows}
    cache_path.write_text(json.dumps(combined), encoding="utf-8")
    return combined


# ══════════════════════════════════════════════════════════════════════════
# 2. QC and EPA correction
# ══════════════════════════════════════════════════════════════════════════

def _process_sensor(raw):
    """
    Parse raw history, apply A/B divergence QC, apply EPA correction.
    Returns a pd.Series indexed by date (string YYYY-MM-DD), or empty.
    """
    fields = raw.get("fields", [])
    rows   = raw.get("data", [])
    if not rows or not fields:
        return pd.Series(dtype=float), {}

    # Identify column positions (time_stamp is always prepended by API)
    fi = {f: i for i, f in enumerate(fields)}

    records = []
    n_total = n_qc_drop = 0
    for row in rows:
        ts  = row[fi["time_stamp"]]
        a   = row[fi.get("pm2.5_cf_1_a", -1)]
        b   = row[fi.get("pm2.5_cf_1_b", -1)]
        rh  = row[fi.get("humidity",     -1)]

        if a is None or b is None or rh is None:
            n_total += 1
            n_qc_drop += 1
            continue

        n_total += 1
        mean_ab = (a + b) / 2.0
        threshold = max(5.0, 0.20 * mean_ab)
        if abs(a - b) > threshold:
            n_qc_drop += 1
            continue

        dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        pm25_cf1 = mean_ab
        # Barkjohn 2021 EPA correction
        pm25_epa = 0.524 * pm25_cf1 - 0.0862 * rh + 5.75
        records.append((dt_str, pm25_epa))

    if not records:
        return pd.Series(dtype=float), {"n_total": n_total, "n_qc_drop": n_qc_drop}

    s = pd.Series(
        {dt: val for dt, val in records},
        name="pm25"
    ).sort_index()
    s.index = pd.to_datetime(s.index)
    stats = {"n_total": n_total, "n_qc_drop": n_qc_drop,
             "n_after_qc": len(s)}
    return s, stats


# ══════════════════════════════════════════════════════════════════════════
# 3. Statistical helpers (verbatim from analysis/robustness.py)
# ══════════════════════════════════════════════════════════════════════════

def _pval(t_stat):
    return float(2 * (1 - _sci_norm.cdf(abs(t_stat))))


def _twoway_demean(df, cols, site_col="site", date_col="date",
                   max_iter=50, tol=1e-9):
    out = {}
    for col in cols:
        x = df[col].astype(float).values.copy()
        for _ in range(max_iter):
            x_prev = x.copy()
            s  = pd.Series(x, index=df.index)
            x -= s.groupby(df[site_col].values).transform("mean").values
            s  = pd.Series(x, index=df.index)
            x -= s.groupby(df[date_col].values).transform("mean").values
            if np.max(np.abs(x - x_prev)) < tol:
                break
        out[col] = x
    return out


def _cluster_se(X_dm, resid, clusters):
    n, k   = X_dm.shape
    XpXinv = np.linalg.pinv(X_dm.T @ X_dm)
    G      = len(np.unique(clusters))
    meat   = np.zeros((k, k))
    for cl in np.unique(clusters):
        mask      = clusters == cl
        score_g   = X_dm[mask].T @ resid[mask]
        meat     += np.outer(score_g, score_g)
    scale = (G / (G - 1)) * (n / (n - k))
    vcov  = scale * XpXinv @ meat @ XpXinv
    return np.sqrt(np.diag(vcov))


def _wild_boot_p(X_dm, y_dm, clusters, coef_idx=0, B=9999, seed=42):
    rng  = np.random.default_rng(seed)
    beta, _, _, _ = np.linalg.lstsq(X_dm, y_dm, rcond=None)
    resid = y_dm - X_dm @ beta
    se    = _cluster_se(X_dm, resid, clusters)
    t_obs = beta[coef_idx] / se[coef_idx]
    unique_cl = np.unique(clusters)
    G         = len(unique_cl)
    t_boots   = np.empty(B)
    for b in range(B):
        w_g   = rng.choice(WEBB, size=G)
        w_all = np.zeros(len(y_dm))
        for w, cl in zip(w_g, unique_cl):
            w_all[clusters == cl] = w
        y_b             = X_dm @ beta + w_all * resid
        beta_b, _, _, _ = np.linalg.lstsq(X_dm, y_b, rcond=None)
        resid_b         = y_b - X_dm @ beta_b
        se_b            = _cluster_se(X_dm, resid_b, clusters)
        t_boots[b]      = beta_b[coef_idx] / se_b[coef_idx]
    p_val = float(np.mean(np.abs(t_boots) >= abs(t_obs)))
    return float(beta[coef_idx]), float(se[coef_idx]), float(t_obs), p_val


def _coef_block(beta, se, p_boot):
    p_norm = _pval(beta / se) if se > 0 else float("nan")
    return {
        "beta":        round(beta, 4),
        "se":          round(se, 4),
        "p_normal":    round(p_norm, 4),
        "p_bootstrap": round(p_boot, 4),
        "ci_low":      round(beta - 1.96 * se, 4),
        "ci_high":     round(beta + 1.96 * se, 4),
    }


# ══════════════════════════════════════════════════════════════════════════
# 4. Panel helpers
# ══════════════════════════════════════════════════════════════════════════

def _load_nyccas_panel(daily, ej_flags):
    """Build NYCCAS panel rows (same selection as run_check4)."""
    rows, included, excluded = [], [], []
    for site in NYCCAS_PANEL:
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
                "in_crz":    int(ej.get("in_crz", False)),
                "purpleair": 0,
            })
    return pd.DataFrame(rows), included, excluded


def _build_pa_rows(pa_series_dict):
    """PA sensor daily rows for panel."""
    rows = []
    for sidx, s in pa_series_dict.items():
        info = ROSTER[sidx]
        site = f"PA_{sidx}"
        for dt, val in s.items():
            if dt < VW_START:
                continue
            rows.append({
                "site":      site,
                "date":      dt.strftime("%Y-%m-%d"),
                "pm25":      float(val),
                "post":      int(dt >= TOLL_DATE),
                "ej_point":  int(info["ej"]),
                "in_crz":    0,
                "purpleair": 1,
            })
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════
# 5. Spec B regressions
# ══════════════════════════════════════════════════════════════════════════

def _run_spec_b1_extended(panel):
    """
    Spec B1 extended: post×EJ + post×CRZ + post×PA (all sites).
    Returns dict with post_ej and post_pa blocks.
    """
    p = panel.copy()
    p["post_ej"]  = p["post"] * p["ej_point"]
    p["post_crz"] = p["post"] * p["in_crz"]
    p["post_pa"]  = p["post"] * p["purpleair"]

    dm = _twoway_demean(p, ["pm25", "post_ej", "post_crz", "post_pa"])
    y  = dm["pm25"]
    X  = np.column_stack([dm["post_ej"], dm["post_crz"], dm["post_pa"]])
    cl = p["site"].values

    b_ej,  se_ej,  _, p_ej  = _wild_boot_p(X, y, cl, coef_idx=0, seed=42)
    b_crz, se_crz, _, p_crz = _wild_boot_p(X, y, cl, coef_idx=1, seed=43)
    b_pa,  se_pa,  _, p_pa  = _wild_boot_p(X, y, cl, coef_idx=2, seed=44)

    G = len(p["site"].unique())
    return {
        "label":    "B1-ext: EJ=point, all sites, +post×PA",
        "n_obs":    len(p),
        "n_sites":  G,
        "post_ej":  _coef_block(b_ej,  se_ej,  p_ej),
        "post_crz": _coef_block(b_crz, se_crz, p_crz),
        "post_pa":  _coef_block(b_pa,  se_pa,  p_pa),
    }


def _run_spec_b3_extended(panel):
    """
    Spec B3 extended: outside-CRZ only, post×EJ + post×PA.
    """
    p = panel[panel["in_crz"] == 0].copy()
    p["post_ej"] = p["post"] * p["ej_point"]
    p["post_pa"] = p["post"] * p["purpleair"]

    dm = _twoway_demean(p, ["pm25", "post_ej", "post_pa"])
    y  = dm["pm25"]
    X  = np.column_stack([dm["post_ej"], dm["post_pa"]])
    cl = p["site"].values

    b_ej, se_ej, _, p_ej = _wild_boot_p(X, y, cl, coef_idx=0, seed=42)
    b_pa, se_pa, _, p_pa = _wild_boot_p(X, y, cl, coef_idx=1, seed=44)

    G = len(p["site"].unique())
    return {
        "label":   "B3-ext: EJ=point, outside-CRZ, +post×PA",
        "n_obs":   len(p),
        "n_sites": G,
        "post_ej": _coef_block(b_ej, se_ej, p_ej),
        "post_pa": _coef_block(b_pa, se_pa, p_pa),
    }


def _run_spec_b_pa_only(pa_panel):
    """
    PA-only spec B: post×EJ, site+date FE, wild bootstrap.
    Like-for-like EJ test within PurpleAir sensors only.
    """
    p = pa_panel.copy()
    p["post_ej"] = p["post"] * p["ej_point"]

    dm = _twoway_demean(p, ["pm25", "post_ej"])
    y  = dm["pm25"]
    X  = dm["post_ej"].reshape(-1, 1)
    cl = p["site"].values

    b_ej, se_ej, _, p_ej = _wild_boot_p(X, y, cl, coef_idx=0, seed=42)

    G_ej    = len(p[p["ej_point"] == 1]["site"].unique())
    G_nonej = len(p[p["ej_point"] == 0]["site"].unique())
    return {
        "label":       "B-PA-only: post×EJ, PA sensors only",
        "n_obs":       len(p),
        "n_sites":     len(p["site"].unique()),
        "n_ej_sites":  G_ej,
        "n_nonej_sites": G_nonej,
        "post_ej":     _coef_block(b_ej, se_ej, p_ej),
        "note_clusters": (f"{len(p['site'].unique())} clusters total "
                          f"({G_nonej} non-EJ, {G_ej} EJ) — small-sample bootstrap"),
    }


# ══════════════════════════════════════════════════════════════════════════
# 6. Check 7 DiD for PA sensors
# ══════════════════════════════════════════════════════════════════════════

def _matched_did(site_s, ctrl_s, year_b, year_a=2024):
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


def _run_check7_pa(pa_series_dict, vw_series, qc_series):
    results = {}
    print(f"\n  {'Sensor':<28} {'raw Δ25':>8} {'−VW 25':>8} {'−VW 26':>8} "
          f"{'−QC 25':>8} {'−QC 26':>8}")
    print("  " + "-" * 72)
    for sidx, s in pa_series_dict.items():
        name = ROSTER[sidx]["name"]
        row = {
            "raw_delta_25": _matched_did(s, None, 2025),
            "minus_vw_25":  _matched_did(s, vw_series,  2025) if vw_series  is not None else None,
            "minus_vw_26":  _matched_did(s, vw_series,  2026) if vw_series  is not None else None,
            "minus_qc_25":  _matched_did(s, qc_series, 2025) if qc_series is not None else None,
            "minus_qc_26":  _matched_did(s, qc_series, 2026) if qc_series is not None else None,
        }
        results[name] = row

        def _f(v):
            return f"{v:+.2f}" if v is not None else "   n/a"

        print(f"  {name:<28} {_f(row['raw_delta_25']):>8} {_f(row['minus_vw_25']):>8} "
              f"{_f(row['minus_vw_26']):>8} {_f(row['minus_qc_25']):>8} "
              f"{_f(row['minus_qc_26']):>8}")
    return results


# ══════════════════════════════════════════════════════════════════════════
# 7. Results printing
# ══════════════════════════════════════════════════════════════════════════

def _fmt_coef(d, label="beta_EJ"):
    if d is None:
        return f"  {label}: n/a"
    b  = d["beta"]
    se = d["se"]
    pb = d["p_bootstrap"]
    ci = f"[{d['ci_low']:+.4f}, {d['ci_high']:+.4f}]"
    return f"  {label}: β={b:+.4f}  SE={se:.4f}  p_boot={pb:.4f}  CI={ci}"


def _print_results(b1_base, b3_base, b1_ext, b3_ext, pa_only,
                   pa_qc_log, did_results):
    SEP = "═" * 80
    sep = "─" * 80
    print(f"\n{SEP}")
    print("  CHECK 9 RESULTS — PurpleAir outside-zone sensors")
    print(SEP)

    # Sensor QC log
    print(f"\n{'─'*80}")
    print("  SENSOR QC / COVERAGE LOG")
    print(f"{'─'*80}")
    print(f"  {'Sensor':<28} {'n_days':>7} {'n_qc_drop':>10} {'n_usable':>9} "
          f"{'pre_days':>9} {'cov%':>6} {'pass':>5}")
    print("  " + "-" * 76)
    for name, info in pa_qc_log.items():
        cov = info.get("coverage_frac", 0) * 100
        ok  = "YES" if info.get("pass") else "NO"
        print(f"  {name:<28} {info.get('n_total',0):>7} {info.get('n_qc_drop',0):>10} "
              f"{info.get('n_after_qc',0):>9} {info.get('n_pre',0):>9} "
              f"{cov:>5.1f}% {ok:>5}")

    # Spec B comparison
    print(f"\n{sep}")
    print("  SPEC B COMPARISON — β_EJ  (wild bootstrap, B=9999)")
    print(f"{'─'*80}")
    print(f"  {'Spec':<42} {'β_EJ':>8} {'SE':>7} {'p_boot':>8} {'CI 95%':>22}")
    print("  " + "-" * 74)

    def _row(label, d):
        if d is None:
            print(f"  {label:<42}  (n/a)")
            return
        b  = d["beta"]
        se = d["se"]
        pb = d["p_bootstrap"]
        ci = f"[{d['ci_low']:+.5f},{d['ci_high']:+.5f}]"
        print(f"  {label:<42} {b:>+8.4f} {se:>7.4f} {pb:>8.4f}  {ci}")

    _row("B1 baseline (NYCCAS only)",
         (b1_base.get("spec_b1") or {}).get("post_ej"))
    _row("B1 extended (+PA sites, +post×PA)",
         b1_ext.get("post_ej"))
    _row("B3 baseline (NYCCAS, outside-CRZ)",
         (b3_base.get("spec_b3") or {}).get("post_ej") if b3_base else None)
    _row("B3 extended (+PA sites, +post×PA)",
         b3_ext.get("post_ej"))
    print("  " + "-" * 74)
    _row("B-PA-only (PurpleAir sensors only)",
         pa_only.get("post_ej"))

    print(f"\n  post×PA instrument term (B1-ext):")
    _row("    post×PA",  b1_ext.get("post_pa"))
    print(f"  post×PA instrument term (B3-ext):")
    _row("    post×PA",  b3_ext.get("post_pa"))
    print(f"\n  PA-only: {pa_only.get('note_clusters','')}")

    # Check 7 DiD
    print(f"\n{sep}")
    print("  CHECK 7 MATCHED-DAY DiD — PurpleAir sensors (µg/m³)")
    print(f"  (EPA-corrected PM2.5; control series are NYCCAS Van Wyck and Queens College)")
    print(f"{'─'*80}")
    print(f"  {'Sensor':<28} {'EJ':>3} {'raw Δ25':>8} {'−VW 25':>8} "
          f"{'−VW 26':>8} {'−QC 25':>8} {'−QC 26':>8}")
    print("  " + "-" * 72)
    for sidx, info in ROSTER.items():
        name = info["name"]
        row  = did_results.get(name, {})
        ej   = "Y" if info["ej"] else "N"

        def _f(v):
            return f"{v:+.2f}" if v is not None else "   n/a"

        print(f"  {name:<28} {ej:>3} {_f(row.get('raw_delta_25')):>8} "
              f"{_f(row.get('minus_vw_25')):>8} {_f(row.get('minus_vw_26')):>8} "
              f"{_f(row.get('minus_qc_25')):>8} {_f(row.get('minus_qc_26')):>8}")

    print(f"\n{SEP}")
    print("  Review the table above.  Approve to write to site (Phase 3).")
    print(SEP)


# ══════════════════════════════════════════════════════════════════════════
# 8. Save to robustness.json
# ══════════════════════════════════════════════════════════════════════════

def _save_check9(b1_ext, b3_ext, pa_only, pa_qc_log, did_results,
                 pa_sensor_meta):
    rob_path = PROCESSED_DIR / "robustness.json"
    rob      = json.loads(rob_path.read_text(encoding="utf-8"))

    rob["check9"] = {
        "status":    "ok",
        "generated": TODAY.strftime("%Y-%m-%d"),
        "sensors":   pa_sensor_meta,
        "qc_log":    pa_qc_log,
        "spec_b1_extended": b1_ext,
        "spec_b3_extended": b3_ext,
        "spec_b_pa_only":   pa_only,
        "check7_did":       did_results,
        "note": (
            "EPA correction: 0.524*pm2.5_cf_1 − 0.0862*RH + 5.75 (Barkjohn 2021). "
            "A/B QC: drop if |A−B|>max(5,0.20*mean_AB). "
            "Coverage gate: ≥80% daily, ≥200 pre-toll days. "
            "post×purpleair term absorbs any instrument-level post-toll drift. "
            "PurpleAir reads on a different scale than NYCCAS; site FE absorb the "
            "level offset but not humidity-driven seasonal bias, hence the correction."
        ),
    }
    rob_path.write_text(json.dumps(rob, indent=2), encoding="utf-8")
    print(f"\n  Saved check9 → {rob_path.relative_to(_PROJECT)}")


# ══════════════════════════════════════════════════════════════════════════
# 9. Main
# ══════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 80)
    print("Check 9 Phase 2: PurpleAir history pull, QC, panel extension, regressions")
    print("=" * 80)

    # ── Pull and process PA history ────────────────────────────────────────
    print("\n[1/6] Pulling PurpleAir daily history…")
    pa_series   = {}   # sensor_index → pd.Series (EPA-corrected daily PM2.5)
    pa_qc_log   = {}   # human name → qc stats
    pa_dropped  = []   # sensor names that failed coverage gate

    for sidx, info in ROSTER.items():
        name       = info["name"]
        cache_path = RAW_PA_DIR / f"{sidx}_history.json"
        print(f"  {name} (#{sidx})…", end="", flush=True)

        try:
            raw = _pull_history(sidx, cache_path)
        except Exception as exc:
            print(f" ERROR pulling: {exc}")
            pa_dropped.append(name)
            continue

        s, qc_stats = _process_sensor(raw)

        if s.empty:
            print(f" no data after QC")
            pa_dropped.append(name)
            continue

        s_vw = s[s.index >= VW_START]
        n_pre = int((s_vw.index < TOLL_DATE).sum())
        n_total_window = PANEL_DAYS
        cov_frac = len(s_vw) / n_total_window

        log_entry = {
            **qc_stats,
            "n_pre":          n_pre,
            "coverage_frac":  round(cov_frac, 4),
            "ej":             info["ej"],
            "borough":        info["borough"],
        }

        reasons = []
        if cov_frac < MIN_COV_FRAC:
            reasons.append(f"coverage {cov_frac:.1%}<{MIN_COV_FRAC:.0%}")
        if n_pre < MIN_PRE_DAYS:
            reasons.append(f"pre_days {n_pre}<{MIN_PRE_DAYS}")

        if reasons:
            print(f" DROPPED ({', '.join(reasons)})")
            log_entry["pass"] = False
            log_entry["drop_reason"] = "; ".join(reasons)
            pa_qc_log[name] = log_entry
            pa_dropped.append(name)
        else:
            print(f" ok  (n={len(s_vw)}, pre={n_pre}, cov={cov_frac:.1%})")
            log_entry["pass"] = True
            pa_qc_log[name] = log_entry
            pa_series[sidx] = s_vw

    print(f"\n  Passed: {len(pa_series)} sensors  |  Dropped: {len(pa_dropped)}: {pa_dropped}")

    if len(pa_series) == 0:
        sys.exit("  ERROR: no PA sensors passed QC. Cannot proceed.")

    # ── Load NYCCAS data and EJ flags ──────────────────────────────────────
    print("\n[2/6] Loading NYCCAS daily data and EJ flags…")
    raw_daily = json.loads((PROCESSED_DIR / "pollution_daily.json").read_text())
    idx       = pd.to_datetime(raw_daily["dates"])
    daily     = pd.DataFrame(raw_daily["sites"], index=idx)

    rob       = json.loads((PROCESSED_DIR / "robustness.json").read_text())
    ej_flags  = rob.get("ej_flags", {})

    # ── Load existing check4 baseline for comparison ───────────────────────
    check4_baseline = rob.get("check4", {})

    # ── Build panels ───────────────────────────────────────────────────────
    print("\n[3/6] Building panels…")
    nyccas_panel, incl, excl = _load_nyccas_panel(daily, ej_flags)
    print(f"  NYCCAS: {len(incl)} sites included, {len(excl)} excluded")

    pa_rows  = _build_pa_rows(pa_series)
    print(f"  PurpleAir: {len(pa_rows)} site-day rows, "
          f"{pa_rows['site'].nunique()} sensors")

    # Extended panel (NYCCAS + PA)
    ext_panel = pd.concat([nyccas_panel, pa_rows], ignore_index=True)
    print(f"  Extended panel: {len(ext_panel):,} rows, "
          f"{ext_panel['site'].nunique()} sites")

    # PA-only panel
    pa_panel = pa_rows.copy()

    # NYCCAS Van Wyck and Queens College for Check 7 controls
    vw_series = daily.get("Van_Wyck")
    qc_series = daily.get("Queens_College")

    # ── Spec B regressions ─────────────────────────────────────────────────
    print("\n[4/6] Running spec B regressions (wild bootstrap B=9999)…")

    print("  B1 extended (all sites + post×PA)…")
    b1_ext = _run_spec_b1_extended(ext_panel)
    b1_ej  = b1_ext["post_ej"]
    print(f"    β_EJ={b1_ej['beta']:+.4f}  SE={b1_ej['se']:.4f}  "
          f"p_boot={b1_ej['p_bootstrap']:.4f}")

    print("  B3 extended (outside-CRZ + post×PA)…")
    b3_ext = _run_spec_b3_extended(ext_panel)
    b3_ej  = b3_ext["post_ej"]
    print(f"    β_EJ={b3_ej['beta']:+.4f}  SE={b3_ej['se']:.4f}  "
          f"p_boot={b3_ej['p_bootstrap']:.4f}")

    print("  B-PA-only (PurpleAir sensors only)…")
    pa_only = _run_spec_b_pa_only(pa_panel)
    pa_ej   = pa_only["post_ej"]
    print(f"    β_EJ={pa_ej['beta']:+.4f}  SE={pa_ej['se']:.4f}  "
          f"p_boot={pa_ej['p_bootstrap']:.4f}")

    # ── Check 7 DiD ────────────────────────────────────────────────────────
    print("\n[5/6] Running Check 7 DiD for PA sensors…")
    did_results = _run_check7_pa(pa_series, vw_series, qc_series)

    # ── Save to robustness.json ────────────────────────────────────────────
    print("\n[6/6] Saving check9 to robustness.json…")
    pa_meta = {
        str(sidx): {
            "name":    info["name"],
            "borough": info["borough"],
            "ej":      info["ej"],
            "sensor_index": sidx,
        }
        for sidx, info in ROSTER.items()
        if sidx in pa_series
    }
    _save_check9(b1_ext, b3_ext, pa_only, pa_qc_log, did_results, pa_meta)

    # ── Print full results table ───────────────────────────────────────────
    _print_results(check4_baseline, check4_baseline,
                   b1_ext, b3_ext, pa_only,
                   pa_qc_log, did_results)


if __name__ == "__main__":
    main()
