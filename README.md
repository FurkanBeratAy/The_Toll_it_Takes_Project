# The Toll It Takes

NYC congestion pricing and air quality — submitted to the NYC Congestion Pricing Datathon 2026.

**Live site:** `site/index.html` → open locally or deploy via GitHub Pages.

## What's here

| Path | Contents |
|------|----------|
| `site/` | Published site (HTML, CSS, images, data bundle) |
| `scripts/` | Analysis pipeline (`01_fetch.py` → `08_assemble.py`, `bundle_data.py`) |
| `analysis/` | Robustness checks (Check 1–8), diagnostics |
| `data/processed/` | All model outputs and processed GeoJSON used by the site |
| `METHODS_ADDENDUM.md` | Robustness specification details and data-gap notes |
| `The Toll it Takes — Analysis & Interpretation.md` | Full narrative and figure guide |
| `PRODUCT.md` | Project structure and data sources |
| `nyccas_station_meta.csv` | Monitor station metadata |

## Raw data

Raw input files are not in this repo (multi-GB). Sources are listed in `PRODUCT.md` and in the Data table on `site/index.html`. Run `scripts/01_fetch.py` to re-download the NYCCAS hourly PM₂.₅ data.

## Regenerating the data bundle

```bash
python scripts/bundle_data.py
```

This reads `data/processed/` and writes `site/data_bundle.js` (~7 MB).

## Analysis by


