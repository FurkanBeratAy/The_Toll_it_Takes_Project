"""
Sensitivity analysis: restrict Checks 2 and 4 to sites with >=200 pre-toll
observations in the VW window (2024-02-22 to 2025-01-05).

Restricted roster: Cross_Bronx_Expy, Mott_Haven, Manhattan_Bridge,
                   Williamsburg_Bridge, Queensboro_Bridge, Broadway_35th_St, FDR
Excluded (<200):   Hamilton_Bridge (170), BQE (143), SI_Expwy (126), Midtown_DOT (148)

Outputs:
  - Check 2 restricted: peak-overnight ITS per site; BQE comparison
  - Check 4 restricted: pooled panel Spec B (wild bootstrap); beta_EJ comparison
"""
import sys, json, glob, warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import statsmodels.api as sm
from zoneinfo import ZoneInfo

BASE        = Path(__file__).parent.parent
TOLL_DATE   = pd.Timestamp("2025-01-05")
VW_START    = pd.Timestamp("2024-02-22")
COVID_START = pd.Timestamp("2020-03-22")
COVID_END   = pd.Timestamp("2021-06-15")

RESTRICTED = [
    "Cross_Bronx_Expy", "Mott_Haven", "Manhattan_Bridge",
    "Williamsburg_Bridge", "Queensboro_Bridge", "Broadway_35th_St", "FDR",
]
EJ = {
    "Cross_Bronx_Expy": True, "Mott_Haven": True,
    "Manhattan_Bridge": True, "Williamsburg_Bridge": True,
    "Queensboro_Bridge": False, "Broadway_35th_St": True, "FDR": True,
}

# ─── Load daily data ─────────────────────────────────────────────────────── #
raw  = json.loads((BASE / "data/processed/pollution_daily.json").read_text(encoding="utf-8"))
didx = pd.to_datetime(raw["dates"])
daily = pd.DataFrame(raw["sites"], index=didx)
qc_d = daily.get("Queens_College")
vw_d = daily.get("Van_Wyck")


# ─── ITS helper ──────────────────────────────────────────────────────────── #
def make_X(idx, t0, qc_vals, vw_vals=None):
    t     = (idx - t0).days.astype(float)
    post  = (idx >= TOLL_DATE).astype(float)
    covid = ((idx >= COVID_START) & (idx <= COVID_END)).astype(float)
    cols  = {"const": 1., "t": t,
             "cos_t": np.cos(2*np.pi*t/365.25),
             "sin_t": np.sin(2*np.pi*t/365.25),
             "post": post, "post_t": post*t, "covid": covid, "QC": qc_vals}
    if vw_vals is not None:
        cols["VW"] = vw_vals
    return pd.DataFrame(cols, index=idx)


def run_its(y, qc_s, vw_s=None):
    cols = {"y": y, "QC": qc_s}
    if vw_s is not None:
        cols["VW"] = vw_s
    joint = pd.DataFrame(cols).dropna()
    n_pre = int((joint.index < TOLL_DATE).sum())
    if len(joint) < 60 or n_pre < 30:
        return None
    t0 = joint.index.min()
    X  = make_X(joint.index, t0, joint["QC"].values,
                joint["VW"].values if vw_s is not None else None)
    res = sm.OLS(joint["y"].values, X).fit(cov_type="HAC", cov_kwds={"maxlags": 30})
    return {
        "beta": round(float(res.params["post"]), 4),
        "se":   round(float(res.bse["post"]),    4),
        "p":    round(float(res.pvalues["post"]), 4),
        "n":    int(res.nobs), "n_pre": n_pre,
        "pre_mean": round(float(joint["y"][joint.index < TOLL_DATE].mean()), 3),
    }


# ═══════════════════════════════════════════════════════════════════════════ #
# CHECK 2 RESTRICTED – peak-overnight ITS                                    #
# ═══════════════════════════════════════════════════════════════════════════ #
print("\n" + "="*70)
print("CHECK 2 RESTRICTED (>=200 pre-toll VW-window days)")
print("="*70)

ET = ZoneInfo("America/New_York")

# Load hourly CSVs
print("Loading hourly CSVs …", flush=True)
frames = []
for fp in sorted(glob.glob(str(BASE / "nyccas_hourly" / "*.csv"))):
    yr_mo = Path(fp).stem   # e.g. 2024_02
    yr = int(yr_mo[:4])
    if yr < 2024:           # only need VW window onward + some post-toll
        continue
    try:
        ch = pd.read_csv(fp, low_memory=False)
        frames.append(ch)
    except Exception:
        pass

from config import SITE_MAP
if frames:
    hourly_raw = pd.concat(frames, ignore_index=True)
    # Normalise columns
    date_col = next((c for c in hourly_raw.columns if "date" in c.lower() or "time" in c.lower() or "observation" in c.lower()), None)
    id_col   = next((c for c in hourly_raw.columns if c.upper() in ("SITEID","SITE_ID","SITE","STATION")), None)
    val_col  = next((c for c in hourly_raw.columns if "pm2" in c.lower() or c.lower() == "value"), None)
    print(f"  hourly cols sample: {list(hourly_raw.columns[:8])}")
    print(f"  date_col={date_col}, id_col={id_col}, val_col={val_col}")
    if date_col and id_col and val_col:
        hourly_raw[date_col] = pd.to_datetime(hourly_raw[date_col], errors="coerce")
        hourly_raw[val_col]  = pd.to_numeric(hourly_raw[val_col],   errors="coerce")
        # Map site IDs to names
        hourly_raw["site_name"] = hourly_raw[id_col].map(SITE_MAP)
        hourly_raw = hourly_raw.dropna(subset=["site_name", date_col])
        hourly_raw = hourly_raw.set_index(date_col).sort_index()
        have_hourly = True
        print(f"  Loaded {len(hourly_raw):,} hourly rows, sites: {hourly_raw['site_name'].unique()[:6]}")
    else:
        have_hourly = False
else:
    have_hourly = False
    print("  No hourly rows loaded (year filter too narrow?)")


def peak_overnight_diff(site_name, hourly_df):
    sh = hourly_df[hourly_df["site_name"] == site_name][val_col].copy()
    sh = sh.replace(-999, np.nan).dropna()
    if len(sh) == 0:
        return None
    sh.index = sh.index.tz_localize("UTC").tz_convert(ET)
    hour     = np.array(sh.index.hour)
    dow      = np.array(sh.index.dayofweek)
    is_wkend = (dow >= 5)
    is_peak  = ((~is_wkend) & (hour >= 5)  & (hour <= 20)) | \
               (is_wkend  & (hour >= 9) & (hour <= 20))

    tmp = pd.DataFrame({"val": sh.values, "peak": is_peak,
                         "date": sh.index.normalize()}, index=sh.index)
    tmp.index = tmp.index.tz_convert(None)
    tmp["date"] = pd.to_datetime(tmp["date"].dt.date)
    rows = []
    for d, grp in tmp.groupby("date"):
        pk = grp.loc[grp["peak"], "val"].dropna()
        ov = grp.loc[~grp["peak"], "val"].dropna()
        if len(pk) >= 8 and len(ov) >= 5:
            rows.append({"date": d, "diff": pk.mean() - ov.mean()})
    if not rows:
        return None
    out = pd.DataFrame(rows).set_index("date")["diff"]
    out.index = pd.to_datetime(out.index)
    return out


# Full-roster Check 2 betas from robustness.json
rob = json.loads((BASE / "data/processed/robustness.json").read_text(encoding="utf-8"))
c2_full = rob["check2"]["all_days"]

if have_hourly:
    # Build QC and VW diff series
    qc_diff_all = peak_overnight_diff("Queens_College", hourly_raw)
    vw_diff_all = peak_overnight_diff("Van_Wyck",       hourly_raw)

    results_c2 = {}
    for site in RESTRICTED:
        diff = peak_overnight_diff(site, hourly_raw)
        if diff is None:
            print(f"  {site}: no hourly data for peak-overnight")
            continue
        # Restrict to VW window
        diff_r = diff[diff.index >= VW_START]
        qc_r   = qc_diff_all[qc_diff_all.index >= VW_START] if qc_diff_all is not None else None
        vw_r   = vw_diff_all[vw_diff_all.index >= VW_START] if vw_diff_all is not None else None
        res = run_its(diff_r, qc_r, vw_r)
        if res:
            results_c2[site] = res

    # Print comparison
    print(f"\n{'Site':<25} {'Full beta':>10} {'Restr beta':>11} {'p (restr)':>10} {'n_pre':>7}")
    print("-" * 67)
    for site in RESTRICTED:
        full  = c2_full.get(site, {})
        restr = results_c2.get(site)
        fb    = f"{full.get('beta', 'n/a'):+.4f}" if full.get("beta") is not None else "n/a"
        if restr:
            print(f"  {site:<23} {fb:>10} {restr['beta']:>+11.4f} {restr['p']:>10.3f} {restr['n_pre']:>7}")
        else:
            print(f"  {site:<23} {fb:>10} {'INSUF':>11} {'—':>10}")
    # BQE comparison note
    bqe_full = c2_full.get("BQE", {})
    print(f"\n  BQE (excluded from restricted, n_pre_vw=143):")
    print(f"    Full-roster beta = {bqe_full.get('beta','n/a')}, p = {bqe_full.get('p','n/a')}")
else:
    print("  Hourly data not available with needed columns.")


# ═══════════════════════════════════════════════════════════════════════════ #
# CHECK 4 RESTRICTED – pooled panel Spec B, wild bootstrap                   #
# ═══════════════════════════════════════════════════════════════════════════ #
print("\n" + "="*70)
print("CHECK 4 RESTRICTED – Spec B (EJ=point, wild bootstrap B=999)")
print("="*70)

# For restricted panel: only sites in RESTRICTED with EJ flags
# Use daily data in VW window (VW_START to present)

panel_rows = []
for site in RESTRICTED:
    y_s  = daily.get(site)
    qc_s = qc_d
    vw_s = vw_d
    if y_s is None or qc_s is None or vw_s is None:
        print(f"  {site}: missing daily data")
        continue
    tmp = pd.DataFrame({"y": y_s, "QC": qc_s, "VW": vw_s}).dropna()
    tmp = tmp[tmp.index >= VW_START].copy()
    n_pre = int((tmp.index < TOLL_DATE).sum())
    if n_pre < 30:
        print(f"  {site}: n_pre={n_pre} < 30, skip")
        continue
    tmp["site"]   = site
    tmp["post"]   = (tmp.index >= TOLL_DATE).astype(float)
    tmp["date"]   = tmp.index
    tmp["ej"]     = float(EJ.get(site, False))
    tmp["n_pre_vw"] = n_pre
    panel_rows.append(tmp)

panel = pd.concat(panel_rows)
sites_in = panel["site"].unique().tolist()
G = len(sites_in)
N = len(panel)
print(f"  Panel: {G} sites, {N} obs")
print(f"  Sites: {sites_in}")

# Two-way FE via alternating projection
def demean_panel(panel_df, y_col, max_iter=50, tol=1e-9):
    y  = panel_df[y_col].values.copy()
    s  = panel_df["site"].values
    d  = panel_df["date"].values
    for _ in range(max_iter):
        y_old = y.copy()
        for g in np.unique(s):
            mask = s == g; y[mask] -= y[mask].mean()
        for t in np.unique(d):
            mask = d == t; y[mask] -= y[mask].mean()
        if np.max(np.abs(y - y_old)) < tol:
            break
    return y

# Demean y, post*ej
panel = panel.sort_values(["site","date"]).reset_index(drop=True)
panel["y_dm"]     = demean_panel(panel, "y")
panel["post_ej"]  = panel["post"] * panel["ej"]
panel["pej_dm"]   = demean_panel(panel, "post_ej")

# OLS on demeaned
X_reg = panel[["pej_dm"]].copy()
X_reg.insert(0, "const", 0.)   # no constant after FE demeaning; but need intercept for SE
res_ols = sm.OLS(panel["y_dm"], X_reg[["pej_dm"]]).fit()
beta_ej_restr = float(res_ols.params["pej_dm"])
se_cr = None  # cluster-robust

# Wild bootstrap with Webb weights (reduced B=999 for speed)
rng = np.random.default_rng(42)
WEBB = np.array([-np.sqrt(3/2), -np.sqrt(1/2), -np.sqrt(1/6),
                  np.sqrt(1/6),  np.sqrt(1/2),  np.sqrt(3/2)])
B = 999
y_dm    = panel["y_dm"].values
pej_dm  = panel["pej_dm"].values
grp_arr = panel["site"].values

site_list = np.unique(grp_arr)
# residuals
resid = y_dm - beta_ej_restr * pej_dm

boot_betas = []
for _ in range(B):
    w = np.ones(N)
    for g in site_list:
        wg = rng.choice(WEBB)
        w[grp_arr == g] = wg
    y_boot = beta_ej_restr * pej_dm + resid * w
    b_hat  = np.dot(pej_dm, y_boot) / np.dot(pej_dm, pej_dm)
    boot_betas.append(b_hat)

boot_betas = np.array(boot_betas)
p_boot_restr = float(np.mean(np.abs(boot_betas) >= np.abs(beta_ej_restr)))

# Full-roster results from robustness.json
c4_full_b1 = rob["check4"].get("spec_b1", {})
full_beta_ej = c4_full_b1.get("post_ej", {}).get("beta")
full_p_boot  = c4_full_b1.get("post_ej", {}).get("p_bootstrap")

print(f"\n  Spec B — post × EJ interaction (EJ = DAC spatial-join point flag)")
print(f"  {'Roster':<20} {'beta_EJ':>9} {'p_boot':>8} {'n_sites':>8} {'n_obs':>7}")
print(f"  {'-'*55}")
print(f"  {'Full (11 sites)':<20} {full_beta_ej:>+9.4f} {full_p_boot:>8.4f} {11:>8} {'(full)':>7}")
print(f"  {'Restricted (7)':<20} {beta_ej_restr:>+9.4f} {p_boot_restr:>8.4f} {G:>8} {N:>7}")
print(f"\n  Note: BQE and SI Expwy have ~4 months pre-toll data in a single season;")
print(f"  seasonal terms are weakly identified for them. Excluding them (restricted)")
print(f"  tests whether the EJ result depends on these short-series sites.")
