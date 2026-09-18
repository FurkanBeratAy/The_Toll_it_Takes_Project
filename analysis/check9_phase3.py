#!/usr/bin/env python3
"""
analysis/check9_phase3.py

Check 9 Phase 3 — plausibility filter → QC table → pass sets → spec B + DiD.

Usage:
  python analysis/check9_phase3.py --step 1   # QC table only; stop for review
  python analysis/check9_phase3.py --step 2   # + pass tables
  python analysis/check9_phase3.py            # full run (default --step 3);
                                               # writes robustness.json check9

Plausibility rule (matches scripts/04_pollution.py):
  Drop any daily row where pm2.5_cf_1_a >= 200 OR pm2.5_cf_1_b >= 200 OR
  EPA-corrected >= 200. Applied after the single-channel checks, before the
  A/B divergence check.

API key is never accessed; all data read from data/raw/purpleair/*.json.
"""

import sys
import json
import math
import argparse
from pathlib import Path
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import numpy as np
import pandas as pd
from scipy.stats import norm as _sci_norm

_PROJECT      = Path(__file__).parent.parent
PROCESSED_DIR = _PROJECT / "data" / "processed"
RAW_PA_DIR    = _PROJECT / "data" / "raw" / "purpleair"

TOLL_DATE  = pd.Timestamp("2025-01-05")
VW_START   = pd.Timestamp("2024-02-22")
TODAY_PD   = pd.Timestamp("2026-09-17")
PANEL_DAYS = (TODAY_PD - VW_START).days + 1   # 939

MIN_PRE_DAYS   = 200
PLAUS_RAW_MAX  = 200.0    # drop if either cf_1 channel >= this (µg/m³)
PLAUS_EPA_MAX  = 200.0    # drop if EPA-corrected value >= this

QC_FLOOR  = 5.0
QC_FRAC   = 0.20

WEBB = np.array([-np.sqrt(1.5), -np.sqrt(0.5), -np.sqrt(1 / 6),
                  np.sqrt(1 / 6),  np.sqrt(0.5),  np.sqrt(1.5)])

# Sensor roster — EJ flag from dac_tracts_nyc.geojson point-in-polygon
ROSTER = {
    191419: {"name": "89th_and_Ridge",      "borough": "Brooklyn",      "ej": False},
     81785: {"name": "RGBIV",               "borough": "Brooklyn",      "ej": False},
     89957: {"name": "FA_O5",              "borough": "Manhattan",     "ej": True},
    165783: {"name": "Red_Hook_Farms",      "borough": "Brooklyn",      "ej": True},
    150696: {"name": "NBN_Green_Provost",   "borough": "Brooklyn",      "ej": True},
     37185: {"name": "NBN_Bushwick",        "borough": "Brooklyn",      "ej": True},
    135148: {"name": "Riverdale",           "borough": "Bronx",         "ej": False},
    138844: {"name": "Neal_Phillip_BKLYN",  "borough": "Brooklyn",      "ej": False},
      4803: {"name": "W90th_CPW",           "borough": "Manhattan",     "ej": False},
     24311: {"name": "Forest_Hills",        "borough": "Queens",        "ej": False},
     91441: {"name": "SITHS256O",           "borough": "Staten_Island", "ej": False},
    183603: {"name": "Hudson_View_Gardens", "borough": "Manhattan",     "ej": False},
}

NYCCAS_PANEL = [
    "Cross_Bronx_Expy", "Mott_Haven", "Manhattan_Bridge",
    "Williamsburg_Bridge", "Queensboro_Bridge",
    "Broadway_35th_St", "FDR", "Hamilton_Bridge", "BQE", "SI_Expwy",
    "Midtown_DOT",
]


# ══════════════════════════════════════════════════════════════════════════
# QC classification (with plausibility filter)
# ══════════════════════════════════════════════════════════════════════════

def _qc_classify(raw):
    """
    Classify every row in a PurpleAir daily-average history JSON.

    Categories (in pipeline order):
      no_data   — both channels null
      b_only    — B channel null; only A present (single-channel)
      a_only    — A channel null; only B present (single-channel)
      implausible — both channels present, but cf_1_a>=200 or cf_1_b>=200
                    or EPA-corrected>=200 (filter applied before RH check
                    for raw-channel branch; after RH for EPA branch)
      no_rh     — both channels present and plausible, RH null
      diverge   — |A-B| > max(5, 0.20*mean_AB)
      valid     — passes all checks; EPA-corrected value kept

    Returns:
      cats          dict of category → count
      ab_diffs      list of |A-B| for rows that reached the diverge check
      valid_records dict of date_str → EPA_value (last value wins for dup dates)
    """
    fields = raw.get("fields", [])
    rows   = raw.get("data", [])
    fi     = {f: i for i, f in enumerate(fields)}

    cats = {
        "no_data": 0, "b_only": 0, "a_only": 0,
        "implausible": 0, "no_rh": 0, "diverge": 0, "valid": 0,
    }
    ab_diffs      = []
    valid_records = {}   # date_str → epa_value (last row for each date)

    for row in rows:
        ts  = row[fi["time_stamp"]]
        a   = row[fi.get("pm2.5_cf_1_a", -1)]
        b   = row[fi.get("pm2.5_cf_1_b", -1)]
        rh  = row[fi.get("humidity",     -1)]

        a_ok  = a is not None
        b_ok  = b is not None
        rh_ok = rh is not None

        if not a_ok and not b_ok:
            cats["no_data"] += 1
            continue
        if a_ok and not b_ok:
            cats["b_only"] += 1     # B channel absent; single-channel A only
            continue
        if b_ok and not a_ok:
            cats["a_only"] += 1     # A channel absent; single-channel B only
            continue

        # Both channels present — raw-channel plausibility check
        if a >= PLAUS_RAW_MAX or b >= PLAUS_RAW_MAX:
            cats["implausible"] += 1
            continue

        if not rh_ok:
            cats["no_rh"] += 1
            continue

        mean_ab  = (a + b) / 2.0
        pm25_epa = 0.524 * mean_ab - 0.0862 * rh + 5.75

        # EPA-corrected plausibility (logically redundant if cf_1 < 200,
        # included for completeness per spec)
        if pm25_epa >= PLAUS_EPA_MAX:
            cats["implausible"] += 1
            continue

        diff      = abs(a - b)
        ab_diffs.append(diff)
        threshold = max(QC_FLOOR, QC_FRAC * mean_ab)
        if diff > threshold:
            cats["diverge"] += 1
        else:
            dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            cats["valid"] += 1
            valid_records[dt_str] = pm25_epa

    return cats, ab_diffs, valid_records


def _valid_series(valid_records):
    if not valid_records:
        return pd.Series(dtype=float)
    s = pd.Series(valid_records, name="pm25").sort_index()
    s.index = pd.to_datetime(s.index)
    return s[s.index >= VW_START]


# ══════════════════════════════════════════════════════════════════════════
# Statistical helpers (verbatim from robustness.py / check9_phase2_diag.py)
# ══════════════════════════════════════════════════════════════════════════

def _pval(t):
    return float(2 * (1 - _sci_norm.cdf(abs(t))))


def _twoway_demean(df, cols, max_iter=50, tol=1e-9):
    out = {}
    for col in cols:
        x = df[col].astype(float).values.copy()
        for _ in range(max_iter):
            xp = x.copy()
            s  = pd.Series(x, index=df.index)
            x -= s.groupby(df["site"].values).transform("mean").values
            s  = pd.Series(x, index=df.index)
            x -= s.groupby(df["date"].values).transform("mean").values
            if np.max(np.abs(x - xp)) < tol:
                break
        out[col] = x
    return out


def _cluster_se(X, resid, cl):
    n, k   = X.shape
    XpXinv = np.linalg.pinv(X.T @ X)
    G      = len(np.unique(cl))
    meat   = np.zeros((k, k))
    for c in np.unique(cl):
        m    = cl == c
        sg   = X[m].T @ resid[m]
        meat += np.outer(sg, sg)
    vcov = (G / (G - 1)) * (n / (n - k)) * XpXinv @ meat @ XpXinv
    return np.sqrt(np.diag(vcov))


def _wild_boot_p(X, y, cl, idx=0, B=9999, seed=42):
    rng  = np.random.default_rng(seed)
    beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    se    = _cluster_se(X, resid, cl)
    t_obs = beta[idx] / se[idx]
    ucl   = np.unique(cl)
    G     = len(ucl)
    tb    = np.empty(B)
    for i in range(B):
        w = np.zeros(len(y))
        for ww, c in zip(rng.choice(WEBB, size=G), ucl):
            w[cl == c] = ww
        yb          = X @ beta + w * resid
        bb, _, _, _ = np.linalg.lstsq(X, yb, rcond=None)
        rb          = yb - X @ bb
        sb          = _cluster_se(X, rb, cl)
        tb[i]       = bb[idx] / sb[idx]
    return float(beta[idx]), float(se[idx]), float(np.mean(np.abs(tb) >= abs(t_obs)))


def _cb(b, se, p_boot, suppress_p=False):
    pn = _pval(b / se) if se > 0 else float("nan")
    d  = {
        "beta":    round(b,  4),
        "se":      round(se, 4),
        "ci_low":  round(b - 1.96 * se, 4),
        "ci_high": round(b + 1.96 * se, 4),
        "p_normal": round(pn, 4) if not math.isnan(pn) else None,
    }
    if suppress_p:
        d["p_bootstrap"] = None
        d["note"] = "fewer than 5 clusters; no calibrated inference"
    else:
        d["p_bootstrap"] = round(p_boot, 4)
    return d


# ══════════════════════════════════════════════════════════════════════════
# Panel construction
# ══════════════════════════════════════════════════════════════════════════

def _nyccas_panel(daily, ej_flags):
    rows = []
    for site in NYCCAS_PANEL:
        y = daily.get(site)
        if y is None:
            continue
        y2 = y[y.index >= VW_START].dropna()
        if (y2.index < TOLL_DATE).sum() < 30:
            continue
        ej = ej_flags.get(site, {})
        for dt, val in y2.items():
            rows.append({
                "site":      site,
                "date":      dt.strftime("%Y-%m-%d"),
                "pm25":      float(val),
                "post":      int(dt >= TOLL_DATE),
                "ej_point":  int(ej.get("ej_point", False)),
                "in_crz":    int(ej.get("in_crz",   False)),
                "purpleair": 0,
            })
    return pd.DataFrame(rows)


def _pa_rows(pa_series):
    rows = []
    for sidx, s in pa_series.items():
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
# Spec B regressions
# ══════════════════════════════════════════════════════════════════════════

def _spec_b1_ext(panel):
    """B1 extended: post×EJ + post×CRZ + post×PA, all sites, two-way FE."""
    p = panel.copy()
    p["post_ej"]  = p["post"] * p["ej_point"]
    p["post_crz"] = p["post"] * p["in_crz"]
    p["post_pa"]  = p["post"] * p["purpleair"]
    dm = _twoway_demean(p, ["pm25", "post_ej", "post_crz", "post_pa"])
    y  = dm["pm25"]
    X  = np.column_stack([dm["post_ej"], dm["post_crz"], dm["post_pa"]])
    cl = p["site"].values
    b0, s0, p0 = _wild_boot_p(X, y, cl, idx=0, seed=42)
    b1, s1, p1 = _wild_boot_p(X, y, cl, idx=1, seed=43)
    b2, s2, p2 = _wild_boot_p(X, y, cl, idx=2, seed=44)
    G = int(p["site"].nunique())
    return {
        "label":    "B1-ext: EJ=point, all sites, +post×PA",
        "n_obs":    len(p),
        "n_sites":  G,
        "post_ej":  _cb(b0, s0, p0),
        "post_crz": _cb(b1, s1, p1),
        "post_pa":  _cb(b2, s2, p2),
    }


def _spec_b3_ext(panel):
    """B3 extended: post×EJ + post×PA, outside-CRZ only, two-way FE."""
    p = panel[panel["in_crz"] == 0].copy()
    p["post_ej"] = p["post"] * p["ej_point"]
    p["post_pa"] = p["post"] * p["purpleair"]
    dm = _twoway_demean(p, ["pm25", "post_ej", "post_pa"])
    y  = dm["pm25"]
    X  = np.column_stack([dm["post_ej"], dm["post_pa"]])
    cl = p["site"].values
    b0, s0, p0 = _wild_boot_p(X, y, cl, idx=0, seed=42)
    b1, s1, p1 = _wild_boot_p(X, y, cl, idx=1, seed=44)
    G = int(p["site"].nunique())
    return {
        "label":   "B3-ext: EJ=point, outside-CRZ, +post×PA",
        "n_obs":   len(p),
        "n_sites": G,
        "post_ej": _cb(b0, s0, p0),
        "post_pa": _cb(b1, s1, p1),
    }


def _spec_b_pa_only(pa_panel):
    """PA-only: post×EJ, PurpleAir sensors only, two-way FE."""
    p = pa_panel.copy()
    p["post_ej"] = p["post"] * p["ej_point"]
    dm = _twoway_demean(p, ["pm25", "post_ej"])
    y  = dm["pm25"]
    X  = dm["post_ej"].reshape(-1, 1)
    cl = p["site"].values
    G      = int(p["site"].nunique())
    G_ej   = int(p[p["ej_point"] == 1]["site"].nunique())
    G_ne   = int(p[p["ej_point"] == 0]["site"].nunique())
    sup    = G < 5
    b, se, pb = _wild_boot_p(X, y, cl, idx=0, seed=42)
    return {
        "label":        "B-PA-only: post×EJ, PA sensors only",
        "n_obs":        len(p),
        "n_sites":      G,
        "n_ej_sites":   G_ej,
        "n_nonej_sites": G_ne,
        "post_ej":      _cb(b, se, pb, suppress_p=sup),
        "note_clusters": (
            f"{G} clusters total ({G_ne} non-EJ, {G_ej} EJ)"
            + (" — fewer than 5; no calibrated inference" if sup else "")
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Check 7 matched-day DiD
# ══════════════════════════════════════════════════════════════════════════

def _did(site_s, ctrl_s, year_b, year_a=2024):
    """Mean matched-day difference (year_b − year_a), optionally DiD vs ctrl."""
    s_a = site_s[site_s.index.year == year_a].dropna()
    s_b = site_s[site_s.index.year == year_b].dropna()
    def _d(s): return {(d.month, d.day): float(v) for d, v in s.items()}
    da, db = _d(s_a), _d(s_b)
    if ctrl_s is None:
        common = sorted(set(da) & set(db))
        return round(float(np.mean([db[k] - da[k] for k in common])), 2) if common else None
    c_a = ctrl_s[ctrl_s.index.year == year_a].dropna()
    c_b = ctrl_s[ctrl_s.index.year == year_b].dropna()
    ca, cb = _d(c_a), _d(c_b)
    common = sorted(set(da) & set(db) & set(ca) & set(cb))
    return (round(float(np.mean([(db[k] - cb[k]) - (da[k] - ca[k])
                                  for k in common])), 2)
            if common else None)


# ══════════════════════════════════════════════════════════════════════════
# Print helpers
# ══════════════════════════════════════════════════════════════════════════

def _fmt_b(d, suppress_p=False):
    if d is None:
        return "   n/a"
    b  = d["beta"]
    se = d["se"]
    ci = f"[{d['ci_low']:+.4f},{d['ci_high']:+.4f}]"
    if suppress_p or d.get("p_bootstrap") is None:
        return f"β={b:+.4f} SE={se:.4f} CI={ci}"
    return f"β={b:+.4f} SE={se:.4f} p={d['p_bootstrap']:.4f} CI={ci}"


def _row_b(label, d, suppress_p=False):
    print(f"  {label:<46} {_fmt_b(d, suppress_p)}")


# ══════════════════════════════════════════════════════════════════════════
# JSON serialisation (handles numpy types and NaN)
# ══════════════════════════════════════════════════════════════════════════

class _NpEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if math.isnan(float(o)) else float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        return super().default(o)


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Check 9 Phase 3")
    parser.add_argument("--step", type=int, default=3,
                        help="Run through step N: 1=QC only, 2=+pass tables, "
                             "3=+spec B + DiD + write JSON (default)")
    args = parser.parse_args()

    SEP = "═" * 86
    sep = "─" * 86

    print(SEP)
    print("  Check 9 Phase 3 — Plausibility Filter + Full Analysis Pipeline")
    print(f"  Panel window: {VW_START.date()} → {TODAY_PD.date()}  ({PANEL_DAYS} days)")
    print(SEP)

    # ──────────────────────────────────────────────────────────────────
    # STEP 1: QC CLASSIFICATION TABLE
    # ──────────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  STEP 1 — QC CLASSIFICATION (with plausibility filter)")
    print(f"  Plausibility rule: drop if cf_1_a >= {PLAUS_RAW_MAX} OR "
          f"cf_1_b >= {PLAUS_RAW_MAX} OR EPA-corrected >= {PLAUS_EPA_MAX} µg/m³")
    print(f"  A/B divergence:   drop if |A-B| > max({QC_FLOOR}, "
          f"{QC_FRAC:.0%}×mean_AB)")
    print(sep)
    HDR = (f"  {'Sensor':<24} {'rows':>5} {'b_miss':>7} {'a_miss':>7} "
           f"{'no_rh':>6} {'divg':>6} {'impl':>5} {'valid':>6}  "
           f"{'med|AB|':>8} {'P90|AB|':>8}  {'cov%':>6} {'pre':>4}")
    print(HDR)
    print("  " + "-" * 84)

    qc_results  = {}   # sidx → {name, cats, cov_frac, n_pre, med_ab, p90_ab}
    sensor_data = {}   # sidx → pd.Series (valid EPA-corrected daily values)

    for sidx, info in ROSTER.items():
        name       = info["name"]
        cache_path = RAW_PA_DIR / f"{sidx}_history.json"
        if not cache_path.exists():
            print(f"  {name:<24}  CACHE NOT FOUND — skipping")
            continue

        raw = json.loads(cache_path.read_bytes())
        cats, ab_diffs, valid_recs = _qc_classify(raw)
        s = _valid_series(valid_recs)

        n_pre    = int((s.index < TOLL_DATE).sum()) if not s.empty else 0
        cov_frac = len(s) / PANEL_DAYS
        med_ab   = float(np.median(ab_diffs))   if ab_diffs else float("nan")
        p90_ab   = float(np.percentile(ab_diffs, 90)) if ab_diffs else float("nan")
        total    = sum(cats.values())

        qc_results[sidx] = {
            "name": name, "cats": cats,
            "cov_frac": cov_frac, "n_pre": n_pre,
            "med_ab": med_ab, "p90_ab": p90_ab,
        }
        if not s.empty:
            sensor_data[sidx] = s

        med_str = f"{med_ab:8.2f}" if not math.isnan(med_ab) else "     n/a"
        p90_str = f"{p90_ab:8.2f}" if not math.isnan(p90_ab) else "     n/a"
        print(f"  {name:<24} {total:>5} "
              f"{cats['b_only']:>7} {cats['a_only']:>7} "
              f"{cats['no_rh']:>6} {cats['diverge']:>6} "
              f"{cats['implausible']:>5} {cats['valid']:>6}  "
              f"{med_str}  {p90_str}  "
              f"{cov_frac * 100:>5.1f}% {n_pre:>4}")

    if args.step < 2:
        print(f"\n{SEP}")
        print("  STEP 1 COMPLETE — review QC table above, then run --step 2.")
        print(SEP)
        return

    # ──────────────────────────────────────────────────────────────────
    # STEP 2: PASS TABLES
    # ──────────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print(f"  STEP 2 — PASS TABLES  (min coverage threshold, "
          f">= {MIN_PRE_DAYS} pre-toll days)")
    print(sep)

    def _pass_set(thresh):
        return {
            sidx: r for sidx, r in qc_results.items()
            if (r["cov_frac"] >= thresh
                and r["n_pre"] >= MIN_PRE_DAYS
                and sidx in sensor_data)
        }

    set_80 = _pass_set(0.80)
    set_70 = _pass_set(0.70)
    all_passing_ids = set(set_80) | set(set_70)

    for thresh, sset, label in [
        (0.80, set_80, "80% — PRIMARY"),
        (0.70, set_70, "70% — SENSITIVITY"),
    ]:
        n_ej    = sum(1 for s in sset if ROSTER[s]["ej"])
        n_nonej = sum(1 for s in sset if not ROSTER[s]["ej"])
        print(f"\n  Pass @ cov >= {label}  (>= {MIN_PRE_DAYS} pre-toll days):")
        print(f"  {'Sensor':<26} {'Cell':<8} {'Borough':<14} {'cov%':>6} {'pre':>4}")
        print("  " + "-" * 60)
        for sidx, r in sset.items():
            info = ROSTER[sidx]
            cell = "EJ" if info["ej"] else "non-EJ"
            print(f"  {r['name']:<26} {cell:<8} {info['borough']:<14} "
                  f"{r['cov_frac'] * 100:>5.1f}% {r['n_pre']:>4}")
        print(f"  → {len(sset)} sensors total: {n_nonej} non-EJ, {n_ej} EJ")

    print(f"\n  Excluded sensors (with reasons):")
    for sidx, r in qc_results.items():
        if sidx in all_passing_ids:
            continue
        info = ROSTER[sidx]
        cats = r["cats"]
        cov  = r["cov_frac"] * 100
        pre  = r["n_pre"]
        total = sum(cats.values())
        reasons = []
        if total > 0 and cats["b_only"] / total > 0.85:
            reasons.append("channel B absent (sensor logs A only)")
        if cov < 70.0:
            reasons.append(f"coverage {cov:.1f}% < 70%")
        elif cov < 80.0:
            reasons.append(f"coverage {cov:.1f}% < 80%")
        if pre < MIN_PRE_DAYS:
            reasons.append(f"pre-toll days {pre} < {MIN_PRE_DAYS}")
        if cats["implausible"] > 0:
            reasons.append(f"{cats['implausible']} implausible days (cf_1 >= 200)")
        print(f"    {r['name']:<26} — {'; '.join(reasons) or 'coverage/pre-toll failure'}")

    if args.step < 3:
        print(f"\n{SEP}")
        print("  STEP 2 COMPLETE — review pass tables above, then run --step 3.")
        print(SEP)
        return

    # ──────────────────────────────────────────────────────────────────
    # STEP 3: SPEC B + CHECK 7 DiD + WRITE JSON
    # ──────────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  STEP 3 — SPEC B REGRESSIONS + CHECK 7 DiD")
    print(sep)

    # Load NYCCAS panel
    raw_daily = json.loads((PROCESSED_DIR / "pollution_daily.json").read_text(encoding="utf-8"))
    idx_      = pd.to_datetime(raw_daily["dates"])
    daily     = pd.DataFrame(raw_daily["sites"], index=idx_)
    rob       = json.loads((PROCESSED_DIR / "robustness.json").read_text(encoding="utf-8"))
    ej_flags  = rob.get("ej_flags", {})
    check4    = rob.get("check4", {})
    check7_nyccas = rob.get("check7", {}).get("sites", {})

    nyccas_base = _nyccas_panel(daily, ej_flags)
    vw_s = daily.get("Van_Wyck")
    qc_s = daily.get("Queens_College")

    def _run_set(sensor_set, set_label):
        pa_s = {sidx: sensor_data[sidx] for sidx in sensor_set if sidx in sensor_data}
        if not pa_s:
            return None, None, None
        pa_df = _pa_rows(pa_s)
        ext   = pd.concat([nyccas_base, pa_df], ignore_index=True)
        print(f"    [{set_label}] B1-ext  ({ext['site'].nunique()} clusters)…", flush=True)
        b1  = _spec_b1_ext(ext)
        print(f"    [{set_label}] B3-ext  ({ext[ext['in_crz']==0]['site'].nunique()} clusters)…", flush=True)
        b3  = _spec_b3_ext(ext)
        print(f"    [{set_label}] PA-only ({pa_df['site'].nunique()} clusters)…", flush=True)
        pa  = _spec_b_pa_only(pa_df)
        return b1, b3, pa

    print(f"\n  Running 80% set ({len(set_80)} PA sensors)…")
    b1_80, b3_80, pa_80 = _run_set(set_80, "80%")

    print(f"\n  Running 70% set ({len(set_70)} PA sensors)…")
    b1_70, b3_70, pa_70 = _run_set(set_70, "70%")

    # Baseline from check4
    b1_base = (check4.get("spec_b1") or {}).get("post_ej")
    b3_base = (check4.get("spec_b3") or {}).get("post_ej")

    ncl_80 = pa_80["n_sites"] if pa_80 else 0
    ncl_70 = pa_70["n_sites"] if pa_70 else 0
    sup_80 = ncl_80 < 5
    sup_70 = ncl_70 < 5

    print(f"\n{sep}")
    print("  SPEC B — β_EJ  (wild bootstrap B=9999, Webb weights, cluster by site)")
    print(sep)
    print(f"  {'Spec':<46} β       SE       p_boot   CI [low, high]")
    print("  " + "-" * 84)
    _row_b("B1 baseline — NYCCAS only (Check 4)",               b1_base)
    _row_b(f"B1 extended — 80% primary ({len(set_80)} PA sensors)",
           b1_80["post_ej"] if b1_80 else None)
    _row_b(f"B1 extended — 70% sensitivity ({len(set_70)} PA sensors)",
           b1_70["post_ej"] if b1_70 else None)
    print("  " + "·" * 84)
    _row_b("B3 baseline — NYCCAS outside-CRZ only (Check 4)",   b3_base)
    _row_b(f"B3 extended — 80% primary",
           b3_80["post_ej"] if b3_80 else None)
    _row_b(f"B3 extended — 70% sensitivity",
           b3_70["post_ej"] if b3_70 else None)
    print("  " + "·" * 84)
    _row_b(f"B-PA-only — 80% primary ({ncl_80} clusters)",
           pa_80["post_ej"] if pa_80 else None, suppress_p=sup_80)
    if sup_80:
        print(f"      * {ncl_80} clusters — fewer than 5; no calibrated inference")
    _row_b(f"B-PA-only — 70% sensitivity ({ncl_70} clusters)",
           pa_70["post_ej"] if pa_70 else None, suppress_p=sup_70)
    if sup_70:
        print(f"      * {ncl_70} clusters — fewer than 5; no calibrated inference")

    print(f"\n  post×PA instrument terms (instrument-level post-toll drift):")
    if b1_80: _row_b("  B1-ext 80%  post×PA", b1_80["post_pa"])
    if b1_70: _row_b("  B1-ext 70%  post×PA", b1_70["post_pa"])
    if b3_80: _row_b("  B3-ext 80%  post×PA", b3_80["post_pa"])
    if b3_70: _row_b("  B3-ext 70%  post×PA", b3_70["post_pa"])

    # Check 7 DiD
    print(f"\n{sep}")
    print("  CHECK 7 MATCHED-DAY DiD  (µg/m³; year_b vs 2024 matched by DOY)")
    print(f"  raw Δ25 = year 2025 − 2024;  −VW = DiD vs Van Wyck;  "
          f"−QC = DiD vs Queens College")
    print(sep)
    print(f"  {'Sensor':<26} {'EJ':>3} {'Type':<12} "
          f"{'raw Δ25':>8} {'−VW 25':>8} {'−VW 26':>8} "
          f"{'−QC 25':>8} {'−QC 26':>8}")
    print("  " + "-" * 86)

    def _f(v): return f"{v:+.2f}" if v is not None else "   n/a"

    for site, lbl in [
        ("Cross_Bronx_Expy",    "NYCCAS/EJ"),
        ("Mott_Haven",          "NYCCAS/EJ"),
        ("Manhattan_Bridge",    "NYCCAS/CRZ"),
        ("Williamsburg_Bridge", "NYCCAS/CRZ"),
    ]:
        r    = check7_nyccas.get(site) or {}
        ej_s = "Y" if ej_flags.get(site, {}).get("ej_point") else "N"
        print(f"  {site:<26} {ej_s:>3} {lbl:<12} "
              f"{_f(r.get('raw_delta_25')):>8} {_f(r.get('minus_vw_25')):>8} "
              f"{_f(r.get('minus_vw_26')):>8} {_f(r.get('minus_qc_25')):>8} "
              f"{_f(r.get('minus_qc_26')):>8}")
    print("  " + "·" * 86)

    check7_pa = {}
    all_passing_sorted = sorted(
        all_passing_ids,
        key=lambda x: (not ROSTER[x]["ej"], ROSTER[x]["name"]),
    )
    for sidx in all_passing_sorted:
        if sidx not in sensor_data:
            continue
        info = ROSTER[sidx]
        name = info["name"]
        s    = sensor_data[sidx]
        row  = {
            "raw_delta_25": _did(s, None, 2025),
            "minus_vw_25":  _did(s, vw_s, 2025) if vw_s is not None else None,
            "minus_vw_26":  _did(s, vw_s, 2026) if vw_s is not None else None,
            "minus_qc_25":  _did(s, qc_s, 2025) if qc_s is not None else None,
            "minus_qc_26":  _did(s, qc_s, 2026) if qc_s is not None else None,
            "pass_set": (
                "primary+sensitivity" if sidx in set_80 and sidx in set_70
                else ("primary" if sidx in set_80 else "sensitivity")
            ),
        }
        check7_pa[name] = row
        ej_s  = "Y" if info["ej"] else "N"
        cell  = "PA/EJ" if info["ej"] else "PA/non-EJ"
        flags = " [80%]" if sidx in set_80 else " [70%]"
        print(f"  {name:<26} {ej_s:>3} {cell:<12} "
              f"{_f(row['raw_delta_25']):>8} {_f(row['minus_vw_25']):>8} "
              f"{_f(row['minus_vw_26']):>8} {_f(row['minus_qc_25']):>8} "
              f"{_f(row['minus_qc_26']):>8}  {flags}")

    # ── Write robustness.json ──────────────────────────────────────────
    print(f"\n{sep}")
    print("  Writing check9 → data/processed/robustness.json")

    def _qc_entry(sidx):
        r    = qc_results[sidx]
        cats = r["cats"]
        info = ROSTER[sidx]
        d    = {
            "sensor_index": sidx,
            "borough":      info["borough"],
            "ej":           info["ej"],
            "rows":         sum(cats.values()),
            "b_miss":       cats["b_only"],
            "a_miss":       cats["a_only"],
            "no_rh":        cats["no_rh"],
            "diverge":      cats["diverge"],
            "implausible":  cats["implausible"],
            "valid":        cats["valid"],
            "med_ab":       (round(r["med_ab"], 3)
                             if not math.isnan(r["med_ab"]) else None),
            "p90_ab":       (round(r["p90_ab"], 3)
                             if not math.isnan(r["p90_ab"]) else None),
            "cov_pct":      round(r["cov_frac"] * 100, 2),
            "n_pre":        r["n_pre"],
            "pass_80":      sidx in set_80,
            "pass_70":      sidx in set_70,
        }
        if sidx not in all_passing_ids:
            exc = []
            if sum(cats.values()) > 0:
                if cats["b_only"] / sum(cats.values()) > 0.85:
                    exc.append("channel B absent (sensor logs A only)")
            if r["cov_frac"] < 0.70:
                exc.append(f"coverage {r['cov_frac']*100:.1f}% < 70%")
            elif r["cov_frac"] < 0.80:
                exc.append(f"coverage {r['cov_frac']*100:.1f}% < 80%")
            if r["n_pre"] < MIN_PRE_DAYS:
                exc.append(f"pre_days {r['n_pre']} < {MIN_PRE_DAYS}")
            if cats["implausible"] > 0:
                exc.append(f"{cats['implausible']} implausible days (cf_1 >= 200)")
            d["excl_reason"] = "; ".join(exc) or "coverage/pre-toll failure"
        return d

    def _set_meta(sset):
        return [
            {
                "sensor_index": sidx,
                "name":    ROSTER[sidx]["name"],
                "borough": ROSTER[sidx]["borough"],
                "ej":      ROSTER[sidx]["ej"],
            }
            for sidx in sset
        ]

    check9_out = {
        "generated": "2026-09-17",
        "plausibility_filter": (
            "Drop any reading where pm2.5_cf_1_a >= 200 OR pm2.5_cf_1_b >= 200 "
            "OR EPA-corrected >= 200 (same threshold as scripts/04_pollution.py)."
        ),
        "qc_table": {
            ROSTER[s]["name"]: _qc_entry(s) for s in qc_results
        },
        "primary_80pct": {
            "threshold":  "cov >= 80%, pre_days >= 200",
            "sensors":    _set_meta(set_80),
            "n_ej":       sum(1 for s in set_80 if ROSTER[s]["ej"]),
            "n_nonej":    sum(1 for s in set_80 if not ROSTER[s]["ej"]),
            "spec_b1_extended": b1_80,
            "spec_b3_extended": b3_80,
            "spec_b_pa_only":   pa_80,
        },
        "sensitivity_70pct": {
            "threshold":  "cov >= 70%, pre_days >= 200",
            "sensors":    _set_meta(set_70),
            "n_ej":       sum(1 for s in set_70 if ROSTER[s]["ej"]),
            "n_nonej":    sum(1 for s in set_70 if not ROSTER[s]["ej"]),
            "spec_b1_extended": b1_70,
            "spec_b3_extended": b3_70,
            "spec_b_pa_only":   pa_70,
        },
        "check7_did": check7_pa,
        "note": (
            "EPA correction: 0.524*pm2.5_cf_1 − 0.0862*RH + 5.75 (Barkjohn 2021). "
            "A/B QC: drop if |A−B| > max(5, 0.20*mean_AB). "
            "Plausibility filter (matches 04_pollution.py): "
            "drop if cf_1_a >= 200 or cf_1_b >= 200 or EPA-corrected >= 200. "
            "Coverage gate: primary >= 80% (939-day panel); "
            "sensitivity >= 70%; both require >= 200 pre-toll days. "
            "post×purpleair absorbs instrument-level post-toll drift. "
            "Wild bootstrap B=9999, Webb weights, cluster by site."
        ),
    }

    rob["check9"] = check9_out
    rob_path = PROCESSED_DIR / "robustness.json"
    rob_path.write_text(
        json.dumps(rob, indent=2, cls=_NpEncoder, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  Saved → {rob_path}")
    print(f"\n{SEP}")
    print("  STEP 3 COMPLETE — STOP for review.")
    print("  Do NOT proceed to steps 4-6 (HTML / markdown / bundle) until approved.")
    print(SEP)


if __name__ == "__main__":
    main()
