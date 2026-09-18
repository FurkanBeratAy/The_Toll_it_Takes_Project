"""
Interrupted Time Series (ITS) regression for each treatment site.

Model (per site):
  PM2.5 = β0 + β1·t + β2·cos(2πt/365) + β3·sin(2πt/365)
          + β4·post + β5·post·t
          + γ_QC·QC(t) + γ_VW·VW(t)
          + δ_covid·COVID(t)
          + ε  (HAC standard errors, maxlags=30)

Two specifications per site (when data allows):
  A) Full: QC + VW covariates, sample = VW_START → present
  B) Long: QC only, sample = site_start → present (where site started before VW_START)

Output: processed/its_results.json
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from config import (PROCESSED_DIR, TOLL_DATE, VW_START, COVID_START, COVID_END,
                    TREATMENT_SITES, CONTROL_SITES, STATION_COORDS)

import numpy as np
import pandas as pd
import statsmodels.api as sm
import warnings
warnings.filterwarnings("ignore")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def load_daily():
    fpath = PROCESSED_DIR / "pollution_daily.json"
    if not fpath.exists():
        raise FileNotFoundError("Run 04_pollution.py first")
    raw = json.loads(fpath.read_text())
    idx = pd.to_datetime(raw["dates"])
    df = pd.DataFrame(raw["sites"], index=idx)
    return df


def make_features(idx, t0, include_vw=True, qc_vals=None, vw_vals=None):
    t    = (idx - t0).days.astype(float)
    post = (idx >= TOLL_DATE).astype(float)
    cos_t = np.cos(2 * np.pi * t / 365.25)
    sin_t = np.sin(2 * np.pi * t / 365.25)
    covid = ((idx >= COVID_START) & (idx <= COVID_END)).astype(float)

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
    if include_vw:
        cols["VW"] = vw_vals

    return pd.DataFrame(cols, index=idx)


def run_spec(y_series, qc_series, vw_series=None, label=""):
    """
    Fit one ITS OLS spec.  Returns a result dict.
    vw_series=None → QC-only spec.
    """
    include_vw = vw_series is not None

    # Build joint DataFrame, drop NaN rows
    cols = {"y": y_series, "QC": qc_series}
    if include_vw:
        cols["VW"] = vw_series
    joint = pd.DataFrame(cols).dropna()

    if len(joint) < 60:
        return None  # too few observations

    # Require at least 30 pre-toll observations so the baseline is estimable.
    # If all data is post-toll (e.g. monitor was offline pre-toll), the
    # post/post_t indicators are collinear with t and the ITS is invalid.
    n_pre = (joint.index < TOLL_DATE).sum()
    if n_pre < 30:
        return None  # insufficient pre-toll baseline

    # Require at least one pre-toll observation within 90 days of the toll date.
    # Sites whose most recent pre-toll data precedes this window have a gap spanning
    # the toll date — the estimated step-change would be extrapolation, not measurement.
    toll_window = pd.Timedelta(days=90)
    pre_near_toll = joint[
        (joint.index >= (TOLL_DATE - toll_window)) &
        (joint.index < TOLL_DATE)
    ]
    if len(pre_near_toll) == 0:
        return None  # no pre-toll data within 90 days of toll date

    t0 = joint.index.min()
    X = make_features(
        joint.index, t0,
        include_vw=include_vw,
        qc_vals=joint["QC"].values,
        vw_vals=joint["VW"].values if include_vw else None,
    )

    model  = sm.OLS(joint["y"].values, X)
    result = model.fit(cov_type="HAC", cov_kwds={"maxlags": 30})

    # Counterfactual: suppress post-toll step/slope
    X_cf = X.copy()
    X_cf["post"]   = 0.0
    X_cf["post_t"] = 0.0

    y_obs = joint["y"].values.tolist()
    y_pred = result.predict(X).tolist()
    y_cf   = result.predict(X_cf).tolist()

    # Prediction CI for the counterfactual using analytical formula
    #   se_pred² = σ² * (1 + x'(X'X)^{-1}x)  — individual prediction
    #   we want CI for E[y|X_cf], i.e., the mean response CI
    pred_cf = result.get_prediction(X_cf)
    ci = pred_cf.conf_int(alpha=0.05)
    ci_low  = ci[:, 0].tolist()
    ci_high = ci[:, 1].tolist()

    ci95 = result.conf_int(alpha=0.05)

    return {
        "label":        label,
        "n":            int(result.nobs),
        "r2":           round(float(result.rsquared), 4),
        "beta_post":    round(float(result.params["post"]), 4),
        "beta_post_se": round(float(result.bse["post"]), 4),
        "beta_post_p":  round(float(result.pvalues["post"]), 4),
        "ci95_low":     round(float(ci95.loc["post", 0]), 4),
        "ci95_high":    round(float(ci95.loc["post", 1]), 4),
        "beta_qc":      round(float(result.params["QC"]), 4),
        "beta_vw":      round(float(result.params["VW"]), 4) if include_vw else None,
        "beta_t":       round(float(result.params["t"]), 6),
        "significant":  bool(result.pvalues["post"] < 0.05),
        "direction":    "increase" if result.params["post"] > 0 else "decrease",
        "dates":        joint.index.strftime("%Y-%m-%d").tolist(),
        "observed":     [round(v, 3) for v in y_obs],
        "predicted":    [round(v, 3) for v in y_pred],
        "counterfactual": [round(v, 3) for v in y_cf],
        "cf_ci_low":    [round(v, 3) for v in ci_low],
        "cf_ci_high":   [round(v, 3) for v in ci_high],
        "pre_mean":     round(float(joint["y"][joint.index < TOLL_DATE].mean()), 3),
        "post_mean":    round(float(joint["y"][joint.index >= TOLL_DATE].mean()), 3),
    }


def equity_regression(site_results, dac_lookup):
    """
    Simple OLS: beta_post ~ EJ_designated (+ control: pre_mean).
    Uses all sites with valid data (not filtered by significance).
    """
    rows = []
    for site, specs in site_results.items():
        spec = specs.get("full") or specs.get("long")
        if spec is None:
            continue
        beta = spec.get("beta_post")
        pre  = spec.get("pre_mean")
        if beta is None or pre is None:
            continue
        rows.append({
            "site":      site,
            "beta_post": float(beta),
            "ej":        int(dac_lookup.get(site, False)),
            "pre_mean":  float(pre),
        })
    if len(rows) < 3:
        return {"note": "insufficient data for equity regression", "n": len(rows)}

    df = pd.DataFrame(rows).dropna()
    if len(df) < 3:
        return {"note": "insufficient non-null data", "n": len(df)}

    # Standardise pre_mean to avoid scale issues
    df["pre_mean_z"] = (df["pre_mean"] - df["pre_mean"].mean()) / (df["pre_mean"].std() + 1e-9)
    X = pd.DataFrame({"const": 1.0, "ej": df["ej"].values,
                       "pre_mean_z": df["pre_mean_z"].values})
    try:
        result = sm.OLS(df["beta_post"].values, X).fit()
        return {
            "beta_ej":    round(float(result.params["ej"]), 4),
            "se_ej":      round(float(result.bse["ej"]), 4),
            "p_ej":       round(float(result.pvalues["ej"]), 4),
            "n":          int(result.nobs),
            "r2":         round(float(result.rsquared), 4),
            "sites_used": df["site"].tolist(),
            "all_sites":  [{"site": r["site"], "beta": r["beta_post"],
                            "ej": bool(r["ej"]), "pre_mean": r["pre_mean"]}
                           for _, r in df.iterrows()],
        }
    except Exception as e:
        return {"note": f"regression error: {e}", "n": len(df)}


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    print("=== Loading daily pollution data ===")
    daily = load_daily()

    qc = daily.get("Queens_College")
    vw = daily.get("Van_Wyck")

    if qc is None:
        raise ValueError("Queens_College not found in pollution_daily.json")

    # ------------------------------------------------------------------ #
    # EJ designations: load from processed DAC geojson if available,     #
    # else use hard-coded known values (Bronx sites = EJ, QC/VW = non-EJ)#
    # ------------------------------------------------------------------ #
    # These will be updated by 06_geo.py; use defaults for now
    dac_defaults = {
        "Cross_Bronx_Expy":    True,
        "Hunts_Point":         True,
        "Mott_Haven":          True,
        "BQE":                 True,
        "Manhattan_Bridge":    True,
        "Williamsburg_Bridge": True,
        "Queensboro_Bridge":   False,
        "Hamilton_Bridge":     False,
        "Queens_College":      False,
        "Van_Wyck":            False,
        "FDR":                 False,
        "Midtown_DOT":         False,
        "Broadway_35th_St":    False,
        "SI_Expwy":            False,
    }

    site_results = {}
    print("\n=== Running ITS regressions ===")

    for site in TREATMENT_SITES:
        y = daily.get(site)
        if y is None:
            print(f"  {site}: NO DATA, skip")
            continue

        specs = {}

        # ---- Spec A: full model with QC + VW, VW_START → present ----
        y_a  = y[y.index >= VW_START]
        qc_a = qc[qc.index >= VW_START]
        vw_a = vw[vw.index >= VW_START] if vw is not None else None

        if vw_a is not None:
            spec_a = run_spec(y_a, qc_a, vw_a, label="full (QC+VW, Feb 2024–present)")
            if spec_a:
                specs["full"] = spec_a
                print(f"  {site} [full]: β_post={spec_a['beta_post']:+.3f} "
                      f"(p={spec_a['beta_post_p']:.3f}), "
                      f"γ_QC={spec_a['beta_qc']:.3f}, "
                      f"γ_VW={spec_a['beta_vw']:.3f}, "
                      f"n={spec_a['n']}")

        # ---- Spec B: QC-only on full history (if site started before VW_START) ----
        y_b  = y.dropna()
        qc_b = qc.reindex(y_b.index)
        if y_b.index.min() < VW_START:
            spec_b = run_spec(y_b, qc_b, vw_series=None,
                              label="long-baseline (QC only, full history)")
            if spec_b:
                specs["long"] = spec_b
                print(f"  {site} [long]: β_post={spec_b['beta_post']:+.3f} "
                      f"(p={spec_b['beta_post_p']:.3f}), "
                      f"γ_QC={spec_b['beta_qc']:.3f}, "
                      f"n={spec_b['n']}")

        if specs:
            site_results[site] = {
                **specs,
                "ej_designated": dac_defaults.get(site, False),
                "lat": STATION_COORDS[site][0],
                "lon": STATION_COORDS[site][1],
            }

    # ---- Equity regression ----
    print("\n=== Equity regression ===")
    eq = equity_regression(site_results, dac_defaults)
    print(f"  β_EJ = {eq.get('beta_ej', 'n/a')} (p={eq.get('p_ej', 'n/a')})")

    # ---- Select worst EJ site ----
    # Priority 1: significant + positive beta_post in EJ tract
    # Priority 2: any positive beta_post in EJ tract (regardless of significance)
    # Priority 3: least-negative beta_post in EJ tract (if all improved)
    worst_site = None
    worst_beta = -999

    for priority_filter in [
        lambda sp: sp["significant"] and sp["beta_post"] > 0,
        lambda sp: sp["beta_post"] > 0,
        lambda sp: True,
    ]:
        for site, res in site_results.items():
            if not res.get("ej_designated"):
                continue
            spec = res.get("full") or res.get("long")
            if spec and priority_filter(spec) and spec["beta_post"] > worst_beta:
                worst_beta = spec["beta_post"]
                worst_site = site
        if worst_site is not None:
            break

    print(f"\n  *** Worst EJ site selected for Part 2: {worst_site} "
          f"(β_post={worst_beta:+.3f}) ***")

    # ---- Headline stats ----
    all_specs = []
    for site, res in site_results.items():
        spec = res.get("full") or res.get("long")
        if spec:
            all_specs.append((site, spec))

    if all_specs:
        betas = [(s, sp["beta_post"]) for s, sp in all_specs]
        best_site,  best_beta  = min(betas, key=lambda x: x[1])
        worst_h,    worst_bh   = max(betas, key=lambda x: x[1])
    else:
        best_site = worst_h = "N/A"
        best_beta = worst_bh = 0.0

    headline = {
        "citywide_pm25_change_pct": None,  # removed: raw mean-of-pcts is dominated by Hunts Point wildfire window
        "worst_site": worst_h,
        "worst_beta": round(float(worst_bh), 3),
        "best_site":  best_site,
        "best_beta":  round(float(best_beta), 3),
        "part2_site": worst_site,
    }

    output = {
        "sites":         site_results,
        "equity":        eq,
        "headline":      headline,
        "toll_date":     TOLL_DATE.strftime("%Y-%m-%d"),
        "vw_start":      VW_START.strftime("%Y-%m-%d"),
    }

    out_path = PROCESSED_DIR / "its_results.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nSaved {out_path}")
    print(f"Headline: worst={headline['worst_site']} ({headline['worst_beta']:+.3f} µg/m³) | "
          f"best={headline['best_site']} ({headline['best_beta']:+.3f} µg/m³)")


if __name__ == "__main__":
    main()
