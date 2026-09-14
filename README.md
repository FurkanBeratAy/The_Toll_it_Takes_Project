# The Toll It Takes

**Did New York's congestion toll clean the air across the city, or push the problem onto South Bronx neighborhoods already living in Asthma Alley?**

Submitted to the NYC Congestion Pricing Datathon 2026. Analysis by Furkan Beray.

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

The method is interrupted time series (ITS) regression with HAC standard errors, using Queens College and Van Wyck as control monitors. Five robustness checks are reported (weather adjustment, peak/overnight differencing, placebo-in-time, pooled panel, and a mechanism check).

---

## Repo structure

| Path | Contents |
|------|----------|
| `docs/` | Published site — open `docs/index.html` locally or visit the live URL above |
| `scripts/` | Analysis pipeline: `01_fetch.py` → `08_assemble.py`, then `bundle_data.py` |
| `analysis/` | Robustness checks (Checks 1–8) and NO₂ diagnostics |
| `data/processed/` | All model outputs and GeoJSON used by the site |
| `METHODS_ADDENDUM.md` | Full robustness specification, EJ flag methodology, data-gap notes |
| `The Toll it Takes — Analysis & Interpretation.md` | Narrative guide to every figure |
| `PRODUCT.md` | Data sources and project structure overview |
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
python scripts/01_fetch.py       # download NYCCAS hourly PM2.5
python scripts/02_crz_geofence.py
python scripts/03_traffic.py     # MTA bridge/tunnel crossings
python scripts/04_pollution.py   # aggregate to daily
python scripts/05_its_model.py   # ITS regression
python scripts/06_geo.py         # spatial joins, EJ flags
python scripts/07_canyon.py      # street-canyon analysis
python scripts/08_assemble.py    # compile outputs
python analysis/robustness.py    # robustness checks 1–8
python scripts/bundle_data.py    # build site/data_bundle.js
```

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

`scripts/01_fetch.py` handles the NYCCAS download automatically. The MTA and other large CSVs need to be downloaded manually and placed in `data/raw/`.
