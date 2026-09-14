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
  - Broadway_35th_St: point=Y, buffer=0.219

**Correction note** — The original `05_its_model.py` hard-coded Manhattan Bridge as non-EJ.
`06_geo.py` had the correct flag (True) from the spatial join, and `its_results.json`
already reflects this. The correction in `robustness.py` fixed the `dac_defaults` dict to
match; Hamilton Bridge, FDR, and Broadway 35th St are also corrected to EJ=True.
Non-EJ sites under corrected flags: Queensboro Bridge, Midtown DOT, SI Expressway (3 sites).

**in_CRZ indicator** — Derived from the geofence (`crz_boundary.geojson`), not hard-coded.
Five sites are inside the CRZ: Manhattan Bridge, Williamsburg Bridge, Queensboro Bridge
(14 m inside), Midtown DOT, and Broadway 35th St. This corrects the earlier hard-coding
of only Midtown DOT and Broadway 35th. Spec B3 ("outside-CRZ only") now excludes all five
in-zone sites, leaving 6 outside-CRZ sites.

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
(2024-02-22 to 2025-01-04), i.e. BQE, Broadway_35th_St, Cross_Bronx_Expy, FDR, Hamilton_Bridge, Manhattan_Bridge, Midtown_DOT, Mott_Haven, Queensboro_Bridge, SI_Expwy, Williamsburg_Bridge.
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
{−√(3/2), −√(1/2), −√(1/6), +√(1/6), +√(1/2), +√(3/2)}, B=9,999 replicates,
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
The comparison to the observed ITS β_post=0.2957 tests whether the diversion
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
- Hunts Point is **excluded** from all tables, charts, and regression analyses. It is
  omitted entirely, not asterisked, because no valid step-change at the toll date can be
  estimated.

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

**Check 7 raw Δ revision (Cross Bronx Expy):** Initial implementation used post-toll 2025 days only (Jan 5 onward), giving −0.10 µg/m³; finalised method includes all calendar-2025 days (Jan 1–Dec 31) matched to 2024 by (month, day), giving −0.16 µg/m³ (279 matched pairs, including Jan 1–4 which are pre-toll but counted as 2025 calendar days).

---

## Post-Fix Spec B Results (after in_crz geofence correction)

Fixing `in_crz` from hard-coded {Midtown DOT, Broadway 35th} to the five-site geofence
changed Spec B substantially:

| Spec | β_EJ | p (wild bootstrap) | Notes |
|---|---|---|---|
| B1 (point flag, all 11 sites) | −0.07 | 0.77 | Changed sign vs. pre-fix +0.25 |
| B2 (buffer > 0.5, all 11 sites) | −0.38 | 0.65 | |
| B3 (point flag, outside-CRZ only, 6 sites) | +0.02 | 0.96 | |

**Interpretation:** EJ status is confounded with zone status. The panel cannot separate
the zone effect from an EJ effect. The pre-fix result (+0.25 to +0.34, p = 0.54–0.62)
should not be cited; the corrected range (−0.38 to +0.02) is the current result.

**Cross-sectional CS1 caveat:** The five-site cross-sectional OLS (4 EJ, 1 non-EJ)
has three regressors on five points, giving R² = 0.99 and a spuriously small p-value.
The CS1 beta and p are not reported as findings anywhere in the publication.
