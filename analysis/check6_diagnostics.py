"""
Check 6 diagnostics — NO2 from EPA AQS hourly bulk files.
Outputs:
  1. Site metadata for all sites used
  2. POC / method-code inventory by year
  3. Raw daily NO2 time series HTML plot
  4. Simple 2024-vs-2025 pre/post comparison
  5. Regional check: Westchester, Nassau, Manhattan
  6. ITS from 2022-01-01 with placebo test
"""
import sys, os, warnings, json
import numpy as np
import pandas as pd
import statsmodels.api as sm
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
warnings.filterwarnings('ignore')

BASE   = Path(__file__).parent.parent
RAW    = BASE / 'data' / 'raw'
SITE_  = BASE / 'site'

TOLL   = pd.Timestamp('2025-01-05')
VW_S   = pd.Timestamp('2024-02-22')
ITS_S  = pd.Timestamp('2022-01-01')
COVID_S= pd.Timestamp('2020-03-22')
COVID_E= pd.Timestamp('2021-06-15')

YEARS  = [2022, 2023, 2024, 2025]

# Counties of interest
BRONX      = 5
QUEENS     = 81
WESTCH     = 119
NASSAU     = 59
MANHATTAN  = 61

TARGET_CNTY = [BRONX, QUEENS, WESTCH, NASSAU, MANHATTAN]

# ── 0. Load and cache NY data ────────────────────────────────────────────────
ny_cache = RAW / 'ny_no2_2022_2025.csv'
COLS = ['State Code','County Code','Site Num','POC','Parameter Code',
        'Latitude','Longitude','Date Local','Time Local',
        'Sample Measurement','Units of Measure','Method Code','Method Name',
        'County Name','State Name']

if ny_cache.exists():
    print('Loading cached NY NO2 data...', flush=True)
    ny = pd.read_csv(ny_cache, low_memory=False)
else:
    print('Building NY-filtered cache from bulk files...', flush=True)
    chunks = []
    for yr in YEARS:
        fp = RAW / f'hourly_no2_{yr}.csv'
        print(f'  {yr}...', flush=True)
        for ch in pd.read_csv(fp, usecols=COLS, chunksize=500_000, low_memory=False):
            sub = ch[ch['State Code'] == 36]
            if len(sub):
                chunks.append(sub.copy())
    ny = pd.concat(chunks, ignore_index=True)
    ny.to_csv(ny_cache, index=False)
    print(f'  Cached {len(ny):,} rows to {ny_cache.name}', flush=True)

ny['dt']  = pd.to_datetime(ny['Date Local'])
ny['val'] = pd.to_numeric(ny['Sample Measurement'], errors='coerce')
ny['year']= ny['dt'].dt.year
print(f'NY rows: {len(ny):,}, counties: {sorted(ny["County Code"].unique())}')
print()

# ── 1. Site metadata ─────────────────────────────────────────────────────────
print('='*70)
print('DIAGNOSTIC 1 — SITE METADATA (from AQS bulk CSV, not memory)')
print('='*70)

# Extract one representative row per (county, site)
meta = (ny[ny['County Code'].isin(TARGET_CNTY)]
        .groupby(['County Code','County Name','Site Num'])
        .agg(Latitude=('Latitude','first'),
             Longitude=('Longitude','first'),
             Years=('year', lambda x: sorted(x.unique())))
        .reset_index())
print(meta.to_string(index=False))
print()

# Local site names known from AQS API call earlier
LOCAL_NAMES = {
    (5, 110): 'IS 52',
    (5, 133): 'PFIZER LAB SITE',
    (81, 124): '(name not fetched from API)',
    (81, 125): '(name not fetched from API)',
}
# Try to fetch Queens names from AQS API
try:
    import urllib.request, json as jjson
    url = ('https://aqs.epa.gov/data/api/monitors/byCounty'
           '?email=test@aqs.api&key=test&param=42602'
           '&bdate=20240101&edate=20241231&state=36&county=081')
    with urllib.request.urlopen(url, timeout=15) as r:
        data = jjson.loads(r.read())
    for rec in data.get('Data', []):
        key = (int(rec['county_code']), int(rec['site_number']))
        LOCAL_NAMES[key] = rec.get('local_site_name','?')
    print('Queens local site names from AQS API:')
    for k,v in LOCAL_NAMES.items():
        if k[0]==81: print(f'  County {k[0]} Site {k[1]}: {v}')
except Exception as e:
    print(f'  (Queens name API lookup failed: {e})')
print()

# ── 2. POC / method code by year ─────────────────────────────────────────────
print('='*70)
print('DIAGNOSTIC 2 — POC & METHOD CODE BY YEAR (Bronx + control sites)')
print('='*70)

DIAG2_SITES = [(5,110),(5,133),(81,124),(81,125)]
for (cty,site) in DIAG2_SITES:
    sub = ny[(ny['County Code']==cty) & (ny['Site Num']==site)]
    if len(sub)==0:
        print(f'County {cty} Site {site}: NO DATA')
        continue
    name = LOCAL_NAMES.get((cty,site),'?')
    print(f'County {cty} Site {site} ({name}):')
    tbl = (sub.groupby(['year','POC','Method Code','Method Name'])
              .size().reset_index(name='n_hours'))
    print(tbl.to_string(index=False))
    # Flag changes
    mc_by_year = sub.groupby('year')['Method Code'].apply(lambda x: set(x.dropna().unique()))
    codes = list(mc_by_year)
    if len(set(map(frozenset, codes))) > 1:
        print('  *** METHOD CODE CHANGED ACROSS YEARS ***')
        for yr, cs in mc_by_year.items():
            print(f'    {yr}: {cs}')
    pocs = sub.groupby('year')['POC'].apply(lambda x: set(x.unique()))
    multi = {yr: ps for yr, ps in pocs.items() if len(ps)>1}
    if multi:
        print(f'  *** MULTIPLE POCs in years: {list(multi.keys())} ***')
        print(f'  Combination method: daily mean averages across POCs before any other step')
    print()

# ── Build daily series (mean across POCs, then mean hourly → daily) ──────────
# For each (county, site): daily mean of val, count valid hours
def daily_series(county, site, min_date=None):
    sub = ny[(ny['County Code']==county) & (ny['Site Num']==site)].copy()
    if min_date: sub = sub[sub['dt'] >= min_date]
    if len(sub)==0: return pd.Series(dtype=float), pd.Series(dtype=int)
    d = sub.groupby('dt')['val'].agg(mean='mean', n='count')
    return d['mean'], d['n']

# Control: daily mean across both Queens sites 124 and 125
def control_daily(min_date=None):
    sub = ny[(ny['County Code']==QUEENS) & (ny['Site Num'].isin([124,125]))].copy()
    if min_date: sub = sub[sub['dt'] >= min_date]
    d = sub.groupby('dt')['val'].mean()
    return d

# ── 3. Raw daily NO2 time series ─────────────────────────────────────────────
print('='*70)
print('DIAGNOSTIC 3 — RAW DAILY NO2 TIME SERIES')
print('='*70)

series_110, _ = daily_series(5, 110, ITS_S)
series_133, _ = daily_series(5, 133, ITS_S)
ctrl          = control_daily(ITS_S)
qs124, _      = daily_series(81, 124, ITS_S)
qs125, _      = daily_series(81, 125, ITS_S)

# Print summary statistics by quarter to give a sense of the time series
for label, s in [('IS 52 (110)', series_110), ('Pfizer (133)', series_133),
                 ('Queens 124', qs124), ('Queens 125', qs125), ('Control (avg)', ctrl)]:
    if len(s)==0: continue
    q = s.resample('QE').mean().round(2)
    # Show 2023 Q4, 2024 Q1–Q4, 2025 Q1–Q4
    recent = q[(q.index >= '2023-10-01') & (q.index <= '2026-01-01')]
    parts = [f"{str(x)[:7]}:{v:.2f}" for x, v in recent.items()]
    print(f'{label}: {" | ".join(parts)}')

# Find where the drop actually occurs
print()
print('Monthly mean NO2 (6 months each side of toll date):')
for label, s in [('IS 52 (110)', series_110), ('Pfizer (133)', series_133), ('Control avg', ctrl)]:
    if len(s)==0: continue
    mo = s.resample('ME').mean()
    window = mo[(mo.index >= '2024-07-01') & (mo.index <= '2025-07-01')]
    print(f'  {label}:')
    for d, v in window.items():
        marker = ' <-- TOLL' if d.month==1 and d.year==2025 else ''
        print(f'    {d.strftime("%Y-%m")}: {v:.2f} ppb{marker}')
print()

# Save Plotly HTML
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
        subplot_titles=['IS 52 (South Bronx, Site 110)',
                        'Pfizer Lab Site (N. Bronx, Site 133)',
                        'Control: Queens Sites 124+125 mean'])
    CLR = {'110':'#B4391B','133':'#8B1E7A','ctrl':'#2F6B3A'}
    for row, (lbl, s) in enumerate([('IS 52',series_110),('Pfizer',series_133),('Control',ctrl)],1):
        if len(s)==0: continue
        fig.add_trace(go.Scatter(x=s.index, y=s.values, mode='lines',
            line=dict(width=1), name=lbl,
            line_color=list(CLR.values())[row-1]), row=row, col=1)
        fig.add_vline(x=TOLL.timestamp()*1000, line_width=2,
                      line_dash='dash', line_color='black', row=row, col=1)
    fig.update_layout(height=700, title='Raw daily-mean NO2 (ppb) — toll date dashed',
        font=dict(family='Archivo, sans-serif'), paper_bgcolor='#fff', showlegend=True)
    fig.update_yaxes(title_text='NO2 (ppb)')
    out = SITE_ / 'check6_raw_no2.html'
    fig.write_html(str(out))
    print(f'Plot saved to {out}')
except Exception as e:
    print(f'Plot skipped ({e})')
print()

# ── 4. Simple 2024 vs 2025 pre/post ─────────────────────────────────────────
print('='*70)
print('DIAGNOSTIC 4 — 2024 VS 2025 CALENDAR-YEAR COMPARISON')
print('='*70)

for (cty,site) in [(5,110),(5,133),(81,124),(81,125)]:
    sub = ny[(ny['County Code']==cty) & (ny['Site Num']==site)].copy()
    if len(sub)==0: continue
    name = LOCAL_NAMES.get((cty,site),'?')
    for yr in [2024, 2025]:
        s = sub[sub['year']==yr]
        expected = 8784 if yr==2024 else 8760   # 2024 leap year
        n_valid = s['val'].notna().sum()
        daily_n = s.groupby('dt')['val'].agg(n='count')['n']
        print(f'  Cty {cty} Site {site} ({name}) {yr}: '
              f'valid_hours={n_valid}/{expected} ({100*n_valid/expected:.1f}%), '
              f'mean={s["val"].mean():.2f} ppb, '
              f'median_hrs_per_day={daily_n.median():.0f}')
print()

# ── 5. Regional check ────────────────────────────────────────────────────────
print('='*70)
print('DIAGNOSTIC 5 — REGIONAL NO2 2024 vs 2025 (Westchester, Nassau, Manhattan)')
print('='*70)

region = ny[ny['County Code'].isin([WESTCH, NASSAU, MANHATTAN])].copy()
if len(region)==0:
    print('  No data for these counties in NY bulk file — check county codes')
else:
    site_stats = []
    for (cty, site), grp in region.groupby(['County Code','Site Num']):
        for yr in [2024, 2025]:
            s = grp[grp['year']==yr]
            expected = 8784 if yr==2024 else 8760
            n = s['val'].notna().sum()
            pct = 100*n/expected
            if pct >= 5:   # at least 5% to show
                site_stats.append({'county':cty,'county_name':grp['County Name'].iloc[0],
                    'site':site,'year':yr,'n_valid':n,'pct':round(pct,1),
                    'mean':round(s['val'].mean(),2)})
    df_r = pd.DataFrame(site_stats)
    if len(df_r):
        # Wide format: site info + 2024 mean + 2025 mean + diff
        wide = df_r.pivot_table(index=['county','county_name','site'],
                                 columns='year', values=['pct','mean'])
        wide.columns = [f'{v}_{yr}' for v,yr in wide.columns]
        wide = wide.reset_index()
        if 'mean_2024' in wide and 'mean_2025' in wide:
            wide['diff'] = (wide['mean_2025'] - wide['mean_2024']).round(2)
        if 'pct_2024' in wide and 'pct_2025' in wide:
            wide['min_cov'] = wide[['pct_2024','pct_2025']].min(axis=1)
        wide = wide.sort_values('county')
        cols_show = [c for c in ['county','county_name','site','pct_2024','mean_2024',
                                  'pct_2025','mean_2025','diff','min_cov'] if c in wide]
        print(wide[cols_show].to_string(index=False))
        # Sites with >= 90% both years
        if 'min_cov' in wide:
            good = wide[wide['min_cov'] >= 90]
            print(f'\n  Sites with >=90% coverage in BOTH 2024 and 2025: {len(good)}')
            if len(good):
                avg_diff = good['diff'].mean()
                print(f'  Mean 2024-to-2025 change at those sites: {avg_diff:+.2f} ppb')
                print(f'  For reference — Bronx IS 52: 2024={df_r[(df_r["county"]==5)&(df_r["site"]==110)&(df_r["year"]==2024)]["mean"].values}')
                print(f'  Bronx Pfizer: 2024={df_r[(df_r["county"]==5)&(df_r["site"]==133)&(df_r["year"]==2024)]["mean"].values}')
    else:
        print('  No data found for these counties.')
print()

# Also add Bronx and Queens for comparison
print('  Bronx + Queens for comparison:')
bq = ny[ny['County Code'].isin([BRONX, QUEENS])].copy()
bq_stats = []
for (cty, site), grp in bq.groupby(['County Code','Site Num']):
    for yr in [2024, 2025]:
        s = grp[grp['year']==yr]
        expected = 8784 if yr==2024 else 8760
        n = s['val'].notna().sum()
        pct = 100*n/expected
        bq_stats.append({'county':cty,'county_name':grp['County Name'].iloc[0],
            'site':site,'year':yr,'pct':round(pct,1),'mean':round(s['val'].mean(),2)})
df_bq = pd.DataFrame(bq_stats)
wide_bq = df_bq.pivot_table(index=['county','county_name','site'],
                              columns='year', values=['pct','mean'])
wide_bq.columns = [f'{v}_{yr}' for v,yr in wide_bq.columns]
wide_bq = wide_bq.reset_index()
if 'mean_2024' in wide_bq and 'mean_2025' in wide_bq:
    wide_bq['diff'] = (wide_bq['mean_2025'] - wide_bq['mean_2024']).round(2)
cols_show = [c for c in ['county','county_name','site','pct_2024','mean_2024',
                          'pct_2025','mean_2025','diff'] if c in wide_bq]
print(wide_bq[cols_show].to_string(index=False))
print()

# ── 6. ITS from 2022-01-01 + placebo test ───────────────────────────────────
print('='*70)
print('DIAGNOSTIC 6 — ITS FROM 2022-01-01 + PLACEBO IN TIME')
print('='*70)

ctrl_full = control_daily(ITS_S)

def make_X_no2(idx, t0, qc_vals):
    t    = (idx - t0).days.astype(float)
    post = (idx >= TOLL).astype(float)
    covid= ((idx >= COVID_S) & (idx <= COVID_E)).astype(float)
    return pd.DataFrame({'const':1., 't':t,
        'cos_t':np.cos(2*np.pi*t/365.25), 'sin_t':np.sin(2*np.pi*t/365.25),
        'post':post, 'post_t':post*t, 'covid':covid, 'QC':qc_vals}, index=idx)

def run_its_no2(y, qc, min_date, toll_date):
    joint = pd.DataFrame({'y':y,'QC':qc}).dropna()
    joint = joint[joint.index >= min_date]
    n_pre = int((joint.index < toll_date).sum())
    n_post= int((joint.index >= toll_date).sum())
    if n_pre < 60 or n_post < 10:
        return None
    t0 = joint.index.min()
    X  = make_X_no2(joint.index, t0, joint['QC'].values)
    res = sm.OLS(joint['y'].values, X).fit(cov_type='HAC', cov_kwds={'maxlags':30})
    return {'beta': float(res.params['post']),
            'se':   float(res.bse['post']),
            'p':    float(res.pvalues['post']),
            'n_pre': n_pre, 'n_post': n_post, 'n_obs': int(res.nobs)}

for (cty,site) in [(5,110),(5,133)]:
    s, _ = daily_series(cty, site, ITS_S)
    name = LOCAL_NAMES.get((cty,site),'?')
    print(f'--- {name} (County {cty} Site {site}) ---')
    res = run_its_no2(s, ctrl_full, ITS_S, TOLL)
    if res:
        print(f'  ITS (2022-01-01 start): beta={res["beta"]:+.3f} ppb  SE={res["se"]:.3f}  p={res["p"]:.4f}')
        print(f'  n_pre={res["n_pre"]}, n_post={res["n_post"]}, n_obs={res["n_obs"]}')
        obs_beta = abs(res['beta'])
    else:
        print('  ITS: insufficient data'); continue

    # Placebo: first of each month 2022-07 through 2024-06
    placebos = pd.date_range('2022-07-01', '2024-06-01', freq='MS')
    joint_full = pd.DataFrame({'y':s,'QC':ctrl_full}).dropna()
    joint_full = joint_full[joint_full.index >= ITS_S]
    # exclude post-toll data for placebo
    joint_pre  = joint_full[joint_full.index < TOLL]
    place_betas = []
    skipped = 0
    for pd_ in placebos:
        n_before = int((joint_pre.index < pd_).sum())
        n_after  = int((joint_pre.index >= pd_).sum())
        if n_before < 90 or n_after < 90:
            skipped += 1; continue
        # coverage check: 60% in 6-month windows
        w1 = joint_pre[(joint_pre.index >= pd_ - pd.DateOffset(months=6)) & (joint_pre.index < pd_)]
        w2 = joint_pre[(joint_pre.index >= pd_) & (joint_pre.index < pd_ + pd.DateOffset(months=6))]
        if len(w1) < 109 or len(w2) < 109:
            skipped += 1; continue
        t0  = joint_pre.index.min()
        t   = (joint_pre.index - t0).days.astype(float)
        pp  = (joint_pre.index >= pd_).astype(float)
        cov = ((joint_pre.index >= COVID_S) & (joint_pre.index <= COVID_E)).astype(float)
        X_p = pd.DataFrame({'const':1.,'t':t,
            'cos_t':np.cos(2*np.pi*t/365.25),'sin_t':np.sin(2*np.pi*t/365.25),
            'post':pp,'post_t':pp*t,'covid':cov,'QC':joint_pre['QC'].values},
            index=joint_pre.index)
        try:
            r = sm.OLS(joint_pre['y'].values, X_p).fit(cov_type='HAC',cov_kwds={'maxlags':30})
            place_betas.append(float(r.params['post']))
        except Exception:
            skipped += 1

    if place_betas:
        emp_p = np.mean(np.abs(place_betas) >= obs_beta)
        print(f'  Placebo test: {len(place_betas)} placebos run, {skipped} skipped')
        print(f'  obs |beta| = {obs_beta:.3f}; placebo |beta| range = [{np.min(np.abs(place_betas)):.3f}, {np.max(np.abs(place_betas)):.3f}]')
        print(f'  Empirical p = {emp_p:.3f} ({int(np.sum(np.abs(place_betas) >= obs_beta))}/{len(place_betas)} placebos >= obs)')
    else:
        print(f'  Placebo test: 0 placebos ran ({skipped} skipped)')
    print()

print('=== DONE ===')
