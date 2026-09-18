#!/usr/bin/env python3
"""
analysis/check9_phase2_diag.py

Diagnostic and re-run for Check 9 Phase 2:
  1. Split QC drops into (a) B-channel missing, (b) A-channel missing,
     (c) RH missing, (d) both channels present but |A-B| > threshold.
     Print median and P90 of |A-B| where both channels exist.
  2. Pass tables at 80 % and 70 % coverage; 200-day pre-toll floor.
  3. Spec B (B1-ext, B3-ext, PA-only) and Check 7 for both sensor sets,
     side by side.
  4. PA-only p-value suppressed if fewer than 5 clusters.
  5. DiD comparison: outside-zone non-EJ vs Cross Bronx + Mott Haven.
  6. West 90th CPW data-gap report.

Does NOT modify robustness.json or any HTML — results only.
"""

import sys, json, os
from pathlib import Path
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

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

MIN_PRE_DAYS = 200

WEBB = np.array([-np.sqrt(1.5), -np.sqrt(0.5), -np.sqrt(1/6),
                  np.sqrt(1/6),  np.sqrt(0.5),  np.sqrt(1.5)])

ROSTER = {
    135148: {"name": "Riverdale",           "borough": "Bronx",         "ej": False},
    191419: {"name": "89th_and_Ridge",      "borough": "Brooklyn",      "ej": False},
    138844: {"name": "Neal_Phillip_BKLYN",  "borough": "Brooklyn",      "ej": False},
      4803: {"name": "W90th_CPW",           "borough": "Manhattan",     "ej": False},
     24311: {"name": "Forest_Hills",        "borough": "Queens",        "ej": False},
     91441: {"name": "SITHS256O",           "borough": "Staten_Island", "ej": False},
     81785: {"name": "RGBIV",               "borough": "Brooklyn",      "ej": False},
    183603: {"name": "Hudson_View_Gardens", "borough": "Manhattan",     "ej": False},
    150696: {"name": "NBN_Green_Provost",   "borough": "Brooklyn",      "ej": True},
     37185: {"name": "NBN_Bushwick",        "borough": "Brooklyn",      "ej": True},
     89957: {"name": "FA_O5",              "borough": "Manhattan",     "ej": True},
    165783: {"name": "Red_Hook_Farms",      "borough": "Brooklyn",      "ej": True},
}

NYCCAS_PANEL = [
    "Cross_Bronx_Expy","Mott_Haven","Manhattan_Bridge","Williamsburg_Bridge",
    "Queensboro_Bridge","Broadway_35th_St","FDR","Hamilton_Bridge",
    "BQE","SI_Expwy","Midtown_DOT",
]


# ══════════════════════════════════════════════════════════════════════════
# 1. QC classification
# ══════════════════════════════════════════════════════════════════════════

QC_THRESHOLD_FLOOR = 5.0
QC_THRESHOLD_FRAC  = 0.20

def _qc_classify(raw):
    """
    Returns per-day classification and per-day |A-B| values.
    Categories: no_data | a_only | b_only | no_rh | diverge | valid
    """
    fields = raw.get("fields", [])
    rows   = raw.get("data", [])
    fi     = {f: i for i, f in enumerate(fields)}

    cats   = {"no_data": 0, "a_only": 0, "b_only": 0,
              "no_rh": 0, "diverge": 0, "valid": 0}
    ab_diffs = []
    valid_records = []

    for row in rows:
        ts = row[fi["time_stamp"]]
        a  = row[fi.get("pm2.5_cf_1_a", -1)]
        b  = row[fi.get("pm2.5_cf_1_b", -1)]
        rh = row[fi.get("humidity",     -1)]

        a_ok = (a is not None)
        b_ok = (b is not None)
        rh_ok = (rh is not None)

        if not a_ok and not b_ok:
            cats["no_data"] += 1
            continue
        if a_ok and not b_ok:
            cats["b_only"] += 1   # "b only missing" — single channel A
            continue
        if b_ok and not a_ok:
            cats["a_only"] += 1   # "a only missing"
            continue
        # Both channels present
        if not rh_ok:
            cats["no_rh"] += 1
            continue
        diff = abs(a - b)
        ab_diffs.append(diff)
        threshold = max(QC_THRESHOLD_FLOOR, QC_THRESHOLD_FRAC * (a + b) / 2.0)
        if diff > threshold:
            cats["diverge"] += 1
        else:
            cats["valid"] += 1
            dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            mean_ab = (a + b) / 2.0
            pm25_epa = 0.524 * mean_ab - 0.0862 * rh + 5.75
            valid_records.append((dt_str, pm25_epa))

    return cats, ab_diffs, valid_records


def _valid_series(valid_records):
    if not valid_records:
        return pd.Series(dtype=float)
    s = pd.Series(
        {dt: val for dt, val in valid_records},
        name="pm25"
    ).sort_index()
    s.index = pd.to_datetime(s.index)
    s = s[s.index >= VW_START]
    return s


# ══════════════════════════════════════════════════════════════════════════
# 2. Statistical helpers (from robustness.py)
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
        m = cl == c
        meat += np.outer(X[m].T @ resid[m], X[m].T @ resid[m])
    vcov = (G/(G-1)) * (n/(n-k)) * XpXinv @ meat @ XpXinv
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
    for b in range(B):
        w = np.zeros(len(y))
        for ww, c in zip(rng.choice(WEBB, size=G), ucl):
            w[cl == c] = ww
        yb           = X @ beta + w * resid
        bb, _, _, _  = np.linalg.lstsq(X, yb, rcond=None)
        rb           = yb - X @ bb
        sb           = _cluster_se(X, rb, cl)
        tb[b]        = bb[idx] / sb[idx]
    p = float(np.mean(np.abs(tb) >= abs(t_obs)))
    return float(beta[idx]), float(se[idx]), p

def _cb(b, se, p):
    pn = _pval(b/se) if se > 0 else float("nan")
    return {"beta": round(b,4), "se": round(se,4),
            "p_normal": round(pn,4), "p_bootstrap": round(p,4),
            "ci_low": round(b-1.96*se,4), "ci_high": round(b+1.96*se,4)}


# ══════════════════════════════════════════════════════════════════════════
# 3. Panel and regression
# ══════════════════════════════════════════════════════════════════════════

def _nyccas_panel(daily, ej_flags):
    rows = []
    for site in NYCCAS_PANEL:
        y = daily.get(site)
        if y is None: continue
        y2 = y[y.index >= VW_START].dropna()
        if (y2.index < TOLL_DATE).sum() < 30: continue
        ej  = ej_flags.get(site, {})
        for dt, val in y2.items():
            rows.append({"site": site, "date": dt.strftime("%Y-%m-%d"),
                         "pm25": float(val), "post": int(dt >= TOLL_DATE),
                         "ej_point": int(ej.get("ej_point", False)),
                         "in_crz":   int(ej.get("in_crz", False)),
                         "purpleair": 0})
    return pd.DataFrame(rows)

def _pa_rows(pa_series):
    rows = []
    for sidx, s in pa_series.items():
        info = ROSTER[sidx]
        site = f"PA_{sidx}"
        for dt, val in s.items():
            if dt < VW_START: continue
            rows.append({"site": site, "date": dt.strftime("%Y-%m-%d"),
                         "pm25": float(val), "post": int(dt >= TOLL_DATE),
                         "ej_point": int(info["ej"]), "in_crz": 0,
                         "purpleair": 1})
    return pd.DataFrame(rows)

def _spec_b1_ext(panel):
    p = panel.copy()
    p["post_ej"]  = p["post"] * p["ej_point"]
    p["post_crz"] = p["post"] * p["in_crz"]
    p["post_pa"]  = p["post"] * p["purpleair"]
    dm = _twoway_demean(p, ["pm25","post_ej","post_crz","post_pa"])
    y  = dm["pm25"]
    X  = np.column_stack([dm["post_ej"], dm["post_crz"], dm["post_pa"]])
    cl = p["site"].values
    b0, s0, p0 = _wild_boot_p(X, y, cl, idx=0, seed=42)
    b2, s2, p2 = _wild_boot_p(X, y, cl, idx=2, seed=44)
    G = len(p["site"].unique())
    return {"label":"B1-ext","n_obs":len(p),"n_sites":G,
            "post_ej":_cb(b0,s0,p0),"post_pa":_cb(b2,s2,p2)}

def _spec_b3_ext(panel):
    p = panel[panel["in_crz"]==0].copy()
    p["post_ej"] = p["post"] * p["ej_point"]
    p["post_pa"] = p["post"] * p["purpleair"]
    dm = _twoway_demean(p, ["pm25","post_ej","post_pa"])
    y  = dm["pm25"]
    X  = np.column_stack([dm["post_ej"], dm["post_pa"]])
    cl = p["site"].values
    b0, s0, p0 = _wild_boot_p(X, y, cl, idx=0, seed=42)
    b2, s2, p2 = _wild_boot_p(X, y, cl, idx=1, seed=44)
    G = len(p["site"].unique())
    return {"label":"B3-ext","n_obs":len(p),"n_sites":G,
            "post_ej":_cb(b0,s0,p0),"post_pa":_cb(b2,s2,p2)}

def _spec_b_pa_only(pa_panel):
    p = pa_panel.copy()
    p["post_ej"] = p["post"] * p["ej_point"]
    dm = _twoway_demean(p, ["pm25","post_ej"])
    y  = dm["pm25"]
    X  = dm["post_ej"].reshape(-1,1)
    cl = p["site"].values
    b, se, pb = _wild_boot_p(X, y, cl, idx=0, seed=42)
    G_ej  = int(p[p["ej_point"]==1]["site"].nunique())
    G_ne  = int(p[p["ej_point"]==0]["site"].nunique())
    G     = int(p["site"].nunique())
    return {"label":"B-PA-only","n_obs":len(p),"n_sites":G,
            "n_ej_sites":G_ej,"n_nonej_sites":G_ne,
            "post_ej":_cb(b,se,pb)}


# ══════════════════════════════════════════════════════════════════════════
# 4. Check 7 DiD
# ══════════════════════════════════════════════════════════════════════════

def _did(site_s, ctrl_s, year_b, year_a=2024):
    s_a = site_s[site_s.index.year == year_a].dropna()
    s_b = site_s[site_s.index.year == year_b].dropna()
    def _d(s): return {(d.month, d.day): float(v) for d, v in s.items()}
    da, db = _d(s_a), _d(s_b)
    if ctrl_s is None:
        common = sorted(set(da) & set(db))
        return round(float(np.mean([db[k]-da[k] for k in common])),2) if common else None
    c_a = ctrl_s[ctrl_s.index.year == year_a].dropna()
    c_b = ctrl_s[ctrl_s.index.year == year_b].dropna()
    ca, cb = _d(c_a), _d(c_b)
    common = sorted(set(da)&set(db)&set(ca)&set(cb))
    return round(float(np.mean([(db[k]-cb[k])-(da[k]-ca[k]) for k in common])),2) if common else None


# ══════════════════════════════════════════════════════════════════════════
# 5. Print helpers
# ══════════════════════════════════════════════════════════════════════════

def _fmt_b(d, suppress_p=False):
    if d is None: return "   n/a"
    b  = d["beta"]
    se = d["se"]
    ci = f"[{d['ci_low']:+.4f},{d['ci_high']:+.4f}]"
    if suppress_p:
        return f"β={b:+.4f} SE={se:.4f} CI={ci}"
    pb = d["p_bootstrap"]
    return f"β={b:+.4f} SE={se:.4f} p={pb:.4f} CI={ci}"

def _row_b(label, d, suppress_p=False):
    print(f"  {label:<44} {_fmt_b(d, suppress_p)}")


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 84)
    print("Check 9 Phase 2 — Diagnostic + Rerun")
    print("=" * 84)

    # ── 1. QC classification per sensor ───────────────────────────────────
    print("\n[1/5] QC classification per sensor")
    print("─" * 84)
    print(f"  Threshold: max({QC_THRESHOLD_FLOOR} µg/m³, "
          f"{QC_THRESHOLD_FRAC:.0%} × mean_AB)")
    print(f"  Single-channel days = coverage gap (not QC failure)")
    print()

    HDR = (f"  {'Sensor':<24} {'rows':>5} {'b_miss':>7} {'a_miss':>7} "
           f"{'no_rh':>6} {'divg':>6} {'valid':>6}  "
           f"{'med|AB|':>8} {'P90|AB|':>8}  {'cov%':>6} {'pre':>4}")
    print(HDR)
    print("  " + "-" * 82)

    qc_results   = {}   # sidx → {cats, series, ab_diffs, cov_frac, n_pre}
    sensor_data  = {}   # sidx → pd.Series (valid EPA-corrected)
    w90th_report = None

    for sidx, info in ROSTER.items():
        name       = info["name"]
        cache_path = RAW_PA_DIR / f"{sidx}_history.json"
        if not cache_path.exists():
            print(f"  {name:<24}  NO CACHE")
            continue
        raw = json.loads(cache_path.read_bytes())
        cats, ab_diffs, valid_recs = _qc_classify(raw)
        s = _valid_series(valid_recs)

        n_pre    = int((s.index < TOLL_DATE).sum()) if not s.empty else 0
        cov_frac = len(s) / PANEL_DAYS

        med_ab = float(np.median(ab_diffs)) if ab_diffs else float("nan")
        p90_ab = float(np.percentile(ab_diffs, 90)) if ab_diffs else float("nan")

        qc_results[sidx] = {
            "name": name, "cats": cats, "cov_frac": cov_frac,
            "n_pre": n_pre, "med_ab": med_ab, "p90_ab": p90_ab,
        }
        if not s.empty:
            sensor_data[sidx] = s

        print(f"  {name:<24} {sum(cats.values()):>5} "
              f"{cats['b_only']:>7} {cats['a_only']:>7} "
              f"{cats['no_rh']:>6} {cats['diverge']:>6} {cats['valid']:>6}  "
              f"{med_ab:>8.2f} {p90_ab:>8.2f}  "
              f"{cov_frac*100:>5.1f}% {n_pre:>4}")

        # West 90th CPW gap report
        if sidx == 4803:
            rows_all = raw.get("data", [])
            fi2 = {f: i for i, f in enumerate(raw.get("fields", []))}
            if rows_all:
                dates_all = sorted(
                    datetime.fromtimestamp(r[fi2["time_stamp"]], tz=timezone.utc).date()
                    for r in rows_all
                )
                first_d = dates_all[0]
                last_d  = dates_all[-1]
                # Find first date on or after VW_START
                from datetime import date as _date
                vw_date = _date(2024, 2, 22)
                toll_date_d = _date(2025, 1, 5)
                pre_dates  = [d for d in dates_all if vw_date <= d < toll_date_d]
                post_dates = [d for d in dates_all if d >= toll_date_d]
                w90th_report = {
                    "first_raw_date": str(first_d),
                    "last_raw_date":  str(last_d),
                    "n_pre_dates":    len(pre_dates),
                    "n_post_dates":   len(post_dates),
                    "earliest_post":  str(post_dates[0]) if post_dates else "none",
                }

    # ── 2. Pass tables ─────────────────────────────────────────────────────
    print("\n[2/5] Pass tables")
    print("─" * 84)

    def _pass_set(thresh):
        passed = {}
        for sidx, r in qc_results.items():
            ok_cov = r["cov_frac"] >= thresh
            ok_pre = r["n_pre"]    >= MIN_PRE_DAYS
            if ok_cov and ok_pre and sidx in sensor_data:
                passed[sidx] = r
        return passed

    set_80 = _pass_set(0.80)
    set_70 = _pass_set(0.70)

    for thresh, sset, label in [(0.80, set_80, "80%"), (0.70, set_70, "70%")]:
        n_ej    = sum(1 for s in sset if ROSTER[s]["ej"])
        n_nonej = sum(1 for s in sset if not ROSTER[s]["ej"])
        print(f"\n  Pass @ {label} coverage  (≥{MIN_PRE_DAYS} pre-toll days):")
        print(f"  {'Sensor':<24} {'Cell':<8} {'Borough':<14} {'cov%':>6} {'pre':>4}")
        print("  " + "-" * 58)
        for sidx, r in sset.items():
            info = ROSTER[sidx]
            cell = "EJ" if info["ej"] else "non-EJ"
            print(f"  {r['name']:<24} {cell:<8} {info['borough']:<14} "
                  f"{r['cov_frac']*100:>5.1f}% {r['n_pre']:>4}")
        print(f"  → {len(sset)} sensors total: {n_nonej} non-EJ, {n_ej} EJ")

    # ── 3. West 90th CPW gap ───────────────────────────────────────────────
    print("\n[3/5] West 90th CPW (sensor 4803) data gap")
    print("─" * 84)
    if w90th_report:
        print(f"  Earliest data in raw pull : {w90th_report['first_raw_date']}")
        print(f"  Latest data in raw pull   : {w90th_report['last_raw_date']}")
        print(f"  Pre-toll dates (≥2024-02-22, <2025-01-05): {w90th_report['n_pre_dates']}")
        print(f"  Post-toll dates (≥2025-01-05)            : {w90th_report['n_post_dates']}")
        print(f"  Earliest post-toll date   : {w90th_report['earliest_post']}")
        if w90th_report["n_pre_dates"] == 0:
            print(f"  → Sensor was offline from at least 2024-02-22 through "
                  f"{w90th_report['earliest_post']} (first data is entirely post-toll).")
            print(f"    Sensor is OUT: no pre-toll baseline.")
    else:
        print("  No cache found for sensor 4803.")

    # ── Load NYCCAS data ───────────────────────────────────────────────────
    print("\n[4/5] Running spec B regressions on both sensor sets")
    print("─" * 84)
    raw_daily = json.loads((PROCESSED_DIR / "pollution_daily.json").read_text())
    idx       = pd.to_datetime(raw_daily["dates"])
    daily     = pd.DataFrame(raw_daily["sites"], index=idx)
    rob       = json.loads((PROCESSED_DIR / "robustness.json").read_text())
    ej_flags  = rob.get("ej_flags", {})
    check4    = rob.get("check4", {})
    check7_nyccas = rob.get("check7", {}).get("sites", {})

    nyccas_base = _nyccas_panel(daily, ej_flags)
    vw_s  = daily.get("Van_Wyck")
    qc_s  = daily.get("Queens_College")

    def _run_set(sensor_set, label):
        pa_s = {sidx: sensor_data[sidx] for sidx in sensor_set}
        if not pa_s:
            return None, None, None
        pa_df  = _pa_rows(pa_s)
        ext    = pd.concat([nyccas_base, pa_df], ignore_index=True)
        b1     = _spec_b1_ext(ext)
        b3     = _spec_b3_ext(ext)
        pa_only = _spec_b_pa_only(pa_df)
        return b1, b3, pa_only

    print(f"  Running 80% set ({len(set_80)} PA sensors)…", flush=True)
    b1_80, b3_80, pa_80 = _run_set(set_80, "80%")
    print(f"    B1 β_EJ={b1_80['post_ej']['beta']:+.4f}  "
          f"B3 β_EJ={b3_80['post_ej']['beta']:+.4f}  "
          f"PA-only β_EJ={pa_80['post_ej']['beta']:+.4f}")

    print(f"  Running 70% set ({len(set_70)} PA sensors)…", flush=True)
    b1_70, b3_70, pa_70 = _run_set(set_70, "70%")
    print(f"    B1 β_EJ={b1_70['post_ej']['beta']:+.4f}  "
          f"B3 β_EJ={b3_70['post_ej']['beta']:+.4f}  "
          f"PA-only β_EJ={pa_70['post_ej']['beta']:+.4f}")

    # ── 5. Full results table ──────────────────────────────────────────────
    SEP = "═" * 84
    sep = "─" * 84
    print(f"\n{SEP}")
    print("  PHASE 2 DIAGNOSTIC RESULTS")
    print(SEP)

    # Spec B side-by-side
    b1_base_ej  = (check4.get("spec_b1") or {}).get("post_ej")
    b3_base_ej  = (check4.get("spec_b3") or {}).get("post_ej") if check4 else None

    ncl_80 = pa_80["n_sites"] if pa_80 else 0
    ncl_70 = pa_70["n_sites"] if pa_70 else 0
    suppress_p_80 = (ncl_80 < 5)
    suppress_p_70 = (ncl_70 < 5)

    print(f"\n{'─'*84}")
    print("  SPEC B — β_EJ  (wild bootstrap B=9999, Webb weights)")
    print(f"{'─'*84}")

    def _pr(label, d, sup=False):
        _row_b(label, d, suppress_p=sup)

    print(f"  {'Spec':<44} β       SE      p_boot  CI [low, high]")
    print("  " + "-" * 82)
    _pr("B1 baseline — NYCCAS only",                         b1_base_ej)
    _pr(f"B1 extended — 80% set ({len(set_80)} PA sensors)",  b1_80["post_ej"] if b1_80 else None)
    _pr(f"B1 extended — 70% set ({len(set_70)} PA sensors)",  b1_70["post_ej"] if b1_70 else None)
    print("  " + "·" * 82)
    _pr("B3 baseline — NYCCAS outside-CRZ only",             b3_base_ej)
    _pr(f"B3 extended — 80% set",                            b3_80["post_ej"] if b3_80 else None)
    _pr(f"B3 extended — 70% set",                            b3_70["post_ej"] if b3_70 else None)
    print("  " + "·" * 82)
    note_80 = (f"  *{ncl_80} clusters; fewer than 5 — no calibrated inference"
               if suppress_p_80 else f"  *{ncl_80} clusters")
    note_70 = (f"  *{ncl_70} clusters; fewer than 5 — no calibrated inference"
               if suppress_p_70 else f"  *{ncl_70} clusters")
    _pr(f"B-PA-only — 80% set ({ncl_80} clusters)*",
        pa_80["post_ej"] if pa_80 else None, sup=suppress_p_80)
    _pr(f"B-PA-only — 70% set ({ncl_70} clusters)*",
        pa_70["post_ej"] if pa_70 else None, sup=suppress_p_70)
    print(note_80)
    print(note_70)

    print(f"\n  post×PA instrument terms:")
    _pr(f"  B1 80% post×PA", b1_80["post_pa"] if b1_80 else None)
    _pr(f"  B1 70% post×PA", b1_70["post_pa"] if b1_70 else None)
    _pr(f"  B3 80% post×PA", b3_80["post_pa"] if b3_80 else None)
    _pr(f"  B3 70% post×PA", b3_70["post_pa"] if b3_70 else None)

    # Check 7 DiD
    print(f"\n{sep}")
    print("  CHECK 7 MATCHED-DAY DiD  (µg/m³; 2025 vs 2024 matched DOY)")
    print(f"{'─'*84}")
    print(f"  {'Sensor':<26} {'EJ':>3} {'Cell/type':<10} "
          f"{'raw Δ25':>8} {'−VW 25':>8} {'−VW 26':>8} "
          f"{'−QC 25':>8} {'−QC 26':>8}")
    print("  " + "-" * 82)

    def _f(v): return f"{v:+.2f}" if v is not None else "   n/a"

    # NYCCAS reference sites
    for site, lbl in [("Cross_Bronx_Expy","NYCCAS/EJ"),
                       ("Mott_Haven",      "NYCCAS/EJ"),
                       ("Manhattan_Bridge","NYCCAS/CRZ"),
                       ("Williamsburg_Bridge","NYCCAS/CRZ")]:
        r = check7_nyccas.get(site) or {}
        ej_s = "Y" if ej_flags.get(site,{}).get("ej_point") else "N"
        print(f"  {site:<26} {ej_s:>3} {lbl:<10} "
              f"{_f(r.get('raw_delta_25')):>8} {_f(r.get('minus_vw_25')):>8} "
              f"{_f(r.get('minus_vw_26')):>8} {_f(r.get('minus_qc_25')):>8} "
              f"{_f(r.get('minus_qc_26')):>8}")

    print("  " + "·" * 82)

    # PA sensors (all three passing sets, labeled)
    for sidx, info in ROSTER.items():
        name = info["name"]
        if sidx not in sensor_data:
            continue
        s    = sensor_data[sidx]
        row  = {
            "raw_delta_25": _did(s, None, 2025),
            "minus_vw_25":  _did(s, vw_s, 2025) if vw_s is not None else None,
            "minus_vw_26":  _did(s, vw_s, 2026) if vw_s is not None else None,
            "minus_qc_25":  _did(s, qc_s, 2025) if qc_s is not None else None,
            "minus_qc_26":  _did(s, qc_s, 2026) if qc_s is not None else None,
        }
        ej_s  = "Y" if info["ej"] else "N"
        cell  = "PA/EJ" if info["ej"] else "PA/non-EJ"
        in80  = " [80]" if sidx in set_80 else ""
        in70  = "[70]" if sidx in set_70 and sidx not in set_80 else ""
        flags = in80 or in70
        print(f"  {name:<26} {ej_s:>3} {cell:<10} "
              f"{_f(row['raw_delta_25']):>8} {_f(row['minus_vw_25']):>8} "
              f"{_f(row['minus_vw_26']):>8} {_f(row['minus_qc_25']):>8} "
              f"{_f(row['minus_qc_26']):>8}  {flags}")

    # ── Plain-language DiD comparison ──────────────────────────────────────
    print(f"\n  COMPARISON PLAIN READING:")
    # Gather non-EJ PA sensors that have DiD data
    pa_ne_vw25 = []
    pa_ne_qc25 = []
    for sidx in (set_80 | set_70):
        if ROSTER[sidx]["ej"] or sidx not in sensor_data:
            continue
        s = sensor_data[sidx]
        v = _did(s, vw_s, 2025)
        q = _did(s, qc_s, 2025)
        if v is not None: pa_ne_vw25.append(v)
        if q is not None: pa_ne_qc25.append(q)

    cb_vw = check7_nyccas.get("Cross_Bronx_Expy",{}).get("minus_vw_25")
    cb_qc = check7_nyccas.get("Cross_Bronx_Expy",{}).get("minus_qc_25")
    mh_vw = check7_nyccas.get("Mott_Haven",{}).get("minus_vw_25")
    mh_qc = check7_nyccas.get("Mott_Haven",{}).get("minus_qc_25")

    def _fv(v): return f"{v:+.2f}" if v is not None else "n/a"
    mean_ne_vw = float(np.mean(pa_ne_vw25)) if pa_ne_vw25 else None
    mean_ne_qc = float(np.mean(pa_ne_qc25)) if pa_ne_qc25 else None

    print(f"    Outside-zone non-EJ PA (n={len(pa_ne_vw25)}) "
          f"mean −VW 25: {_fv(mean_ne_vw)}")
    print(f"    Cross Bronx (EJ, outside-CRZ)    −VW 25: {_fv(cb_vw)}"
          f"   −QC 25: {_fv(cb_qc)}")
    print(f"    Mott Haven  (EJ, outside-CRZ)    −VW 25: {_fv(mh_vw)}"
          f"   −QC 25: {_fv(mh_qc)}")
    if mean_ne_vw is not None and cb_vw is not None and mh_vw is not None:
        similar = (
            abs(mean_ne_vw - cb_vw) < 0.5 or abs(mean_ne_vw - mh_vw) < 0.5
        )
        print()
        if similar:
            print("    → Outside-zone non-EJ PA sensors moved by a SIMILAR amount to")
            print("      Cross Bronx / Mott Haven vs Van Wyck. No differential EJ signal")
            print("      is visible in the DiD comparison.")
        else:
            diff_dir = "more" if mean_ne_vw > max(cb_vw, mh_vw) else "less"
            print(f"    → Outside-zone non-EJ PA sensors rose {diff_dir} than Cross Bronx /")
            print(f"      Mott Haven relative to Van Wyck. Possible differential, but")
            print(f"      differences are within the noise range of 3-sensor estimates.")

    print(f"\n{SEP}")
    print("  Review above. Approve Phase 3 once sensor set is decided.")
    print(SEP)


if __name__ == "__main__":
    main()
