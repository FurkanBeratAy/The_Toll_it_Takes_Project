# The Toll It Takes

**Did New York's congestion toll clean the air across the city, or push the problem onto South Bronx neighborhoods already living in Asthma Alley?**

Submitted to the NYC Congestion Pricing Datathon 2026. Analysis by Furkan Beray.

**Live site: https://furkanberatay.github.io/The_Toll_it_Takes_Project/**

---

## Start here

**[→ Read the full analysis and findings](The%20Toll%20it%20Takes%20%E2%80%94%20Analysis%20%26%20Interpretation.md)**

That document walks through every figure and table in the site — what it shows, how to read it, and what it means. Start there if you want to understand the project.

For the statistical methodology behind the robustness checks, see **[METHODS_ADDENDUM.md](METHODS_ADDENDUM.md)**.

---

## What this project does

NYC's congestion toll went live on January 5, 2025. This project uses hourly PM₂.₅ readings from eleven NYCCAS air quality monitors (2019–2026) and MTA bridge/tunnel crossing counts to ask:

- Did air quality improve inside the Congestion Relief Zone after the toll?
- Did it get worse in the South Bronx (Mott Haven, Cross Bronx), where diverted traffic would go?
- Did environmental-justice-designated neighborhoods fare differently than non-EJ sites?

The method is interrupted time series (ITS) regression with HAC standard errors, using Queens College and Van Wyck as control monitors. Nine robustness checks are reported: weather adjustment, peak/overnight differencing, placebo-in-time, pooled panel, mechanism check, Bronx NO₂ trend, matched-day DiD, step-only ITS, and outside-zone PurpleAir sensors. Part I also compares these results with the South Bronx Unite community study and reasons through an expressway-to-boulevard scenario; Part II reports stormwater interception alongside PM₂.₅ removal.

---

## Findings

**−0.6 to −1.6 µg/m³ — Inside the zone, the air got cleaner**

At the Manhattan landings of the Manhattan and Williamsburg Bridges — both inside the CRZ — PM₂.₅ fell 0.6–1.6 µg/m³ relative to control monitors in 2025 and kept falling in 2026. Manhattan Bridge is significant in every specification tested.

**+0.87 µg/m³ vs. VW — Outside the zone, it didn't**

Relative to Van Wyck, Mott Haven and Cross Bronx ran about 0.9–1.0 µg/m³ higher in 2025 than before the toll — and so did volunteer sensors in Bay Ridge, Brooklyn Heights, and East Harlem. Relative to Queens College, all of them were flat to slightly up.

**−0.38 to +0.02 µg/m³ — The EJ question can't be separated from the zone question**

Every monitor inside the zone except Queensboro sits in a designated tract, and so does every outside-zone monitor with a full pre-toll record. Panel estimates of an EJ gap range from −0.38 to +0.02 µg/m³ depending on how the flag is defined, none significant. What the data shows is geography: inside the zone improved; no outside-zone site did, EJ or not (Section 9). One peak-hour diversion test (Cross Bronx, weekdays) is significant; Mott Haven's is not; regulatory NO₂ in the Bronx shows no change beyond the regional trend.

---

## Repo structure

| Path | Contents |
|------|----------|
| `docs/` | Published site — open `docs/index.html` locally or visit the live URL above |
| `scripts/` | Analysis pipeline: `01_fetch.py` → `08_assemble.py`, then `bundle_data.py` |
| `analysis/` | Robustness checks 1–9 (robustness.py, check9_phase*.py) and NO₂ diagnostics |
| `data/processed/` | All model outputs and GeoJSON used by the site |
| `METHODS_ADDENDUM.md` | Full robustness specification, EJ flag methodology, data-gap notes |
| `The Toll it Takes — Analysis & Interpretation.md` | Narrative guide to every figure |
| `nyccas_station_meta.csv` | Monitor station metadata |

---

## Running the analysis

**Install dependencies:**

```bash
pip install -r requirements.txt
```

**Run the full pipeline** (requires raw data — see below):

```bash
python scripts/run_all.py
```

**Or run individual steps:**

```bash
python scripts/01_fetch.py              # download NYCCAS hourly PM2.5
python scripts/02_crz_geofence.py
python scripts/03_traffic.py            # MTA bridge/tunnel crossings
python scripts/04_pollution.py          # aggregate to daily
python scripts/05_its_model.py          # ITS regression
python scripts/06_geo.py                # spatial joins, EJ flags
python scripts/07_canyon.py            # street-canyon analysis
python scripts/08_assemble.py          # compile outputs
python analysis/robustness.py          # robustness checks 1–8
python analysis/check9_phase1.py       # find candidate PurpleAir sensors (API)
python analysis/check9_phase1_revised.py  # revised roster, NYC only (API)
python analysis/check9_phase2.py       # pull sensor history — costs ~2,800 points/sensor (API)
python analysis/check9_phase2_diag.py  # QC diagnosis and pass tables (offline, uses cache)
python analysis/check9_phase3.py       # final regressions, writes check9 to robustness.json (offline)
python scripts/bundle_data.py          # build docs/data_bundle.js
```

With `data/raw/purpleair/` present, only phase2_diag and phase3 need to run.

Check 9 (phases 1–2) requires `PURPLEAIR_READ_KEY` set in a `.env` file.

**Reproducibility note:** To reproduce the headline ITS numbers without the raw data: `data/processed/pollution_daily.json` is in the repo; run `python scripts/05_its_model.py`. `scripts/config.py` derives `BASE_DIR` via `Path(__file__).resolve().parent.parent`, so all paths resolve relative to the repo root regardless of clone location. No hard-coded absolute paths remain in `scripts/` or `analysis/`. All scripts that print β, µ, or other non-ASCII characters call `sys.stdout.reconfigure(encoding="utf-8")` on startup; no `PYTHONIOENCODING` environment variable is needed on Windows. Re-running `scripts/05_its_model.py` from a clean clone reproduces `its_results.json` exactly (verified: Manhattan Bridge β_post = −1.328, Mott Haven β_post = +0.296).

---

## Raw data

Raw input files are not in this repo (most are multi-GB). All sources are public:

| Dataset | Source |
|---------|--------|
| Hourly PM₂.₅ monitors | NYC Community Air Survey (NYCCAS) |
| Bridge and tunnel crossings | MTA Bridges & Tunnels |
| CRZ vehicle entries | MTA |
| Disadvantaged community tracts | New York State |
| Street tree census | NYC Parks (2015) |
| LION street centerlines | NYC Planning |
| Building footprints | NYC Open Data |
| MapPLUTO | NYC Planning |
| LGA ASOS weather | Iowa Environmental Mesonet |
| Hourly NO₂ | US EPA AQS |
| 311 vehicle idling complaints | NYC Open Data |
| School locations | NYC DOE |
| Truck routes | NYC DOT |
| PurpleAir outdoor sensors | PurpleAir API (EPA-corrected, Barkjohn 2021) |

`scripts/01_fetch.py` handles the NYCCAS download automatically. The MTA and other large CSVs need to be downloaded manually and placed in `data/raw/`.

---

## Notes on the data

- **Hunts Point excluded** — the monitor was offline September 2023 to March 2025, spanning the toll-start date. There are zero pre-toll observations in the analysis window; no valid step-change can be estimated. It is omitted from all tables, charts, and regressions.
- **EJ flags** — each monitoring station is flagged by a point-in-polygon spatial join against New York State Disadvantaged Community (DAC) census tracts. A secondary buffer-share flag (500 m radius, >50% overlap) is also computed. Where the two flags disagree, both are noted.
- **In-zone flag** — derived from the MTA CRZ geofence (`crz_boundary.geojson`), not hard-coded. Five sites are inside the CRZ: Manhattan Bridge, Williamsburg Bridge, Queensboro Bridge, Midtown DOT, and Broadway 35th St.
- **Manhattan and Williamsburg Bridge monitors** sit approximately 800 m inside the toll zone, where CRZ entry-reduction has its most direct local traffic impact.
