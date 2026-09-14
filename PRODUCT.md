# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: Datathon judges — civic data experts, urban planners, and environmental justice researchers evaluating submissions to the NYC Congestion Pricing Datathon 2026. They assess analytical rigour and narrative clarity in a competitive review setting; they scan quickly and reward credibility.

Secondary: Civic data practitioners and journalists who may encounter the report shared after the competition.

## Product Purpose

"The Toll It Takes" is a two-part interactive data journalism report examining whether NYC's Congestion Relief Zone toll (launched January 5, 2025) improved air quality citywide or displaced PM₂.₅ pollution onto Environmental Justice communities already burdened in the South Bronx ("Asthma Alley").

Part I uses an Interrupted Time Series model across six NYCCAS PM₂.₅ monitoring sites, bridge/tunnel traffic diversion residuals, and an equity regression separating EJ-designated from non-EJ corridors. Part II proposes a data-selected green corridor typology for Mott Haven (the worst EJ corridor) using canyon H/W geometry, canopy gap analysis, and a 20-year PM₂.₅ sequestration projection across three planting typologies.

Success means a judge reads the argument, trusts the method, and understands both the citywide improvement and the localised equity gap — in one sitting.

## Positioning

The only datathon submission that pairs a rigorous causal inference model (ITS with DiD equity term) with a quantified, site-specific green infrastructure remedy — making the evidence actionable rather than merely descriptive.

## Operating Context

- Report is opened directly from the file system (file:// protocol) with no local HTTP server; all data is bundled into `site/data_bundle.js` as `window.DATA_BUNDLE`.
- Interactive maps (MapLibre GL JS v5 + OpenFreeMap liberty style) and charts (Plotly.js) load inline in each HTML page.
- Three HTML surfaces: `index.html` (editorial landing), `part1.html` (Air Quality Analysis), `part2.html` (Green Corridor Design).
- No build system; plain HTML/CSS/JS served as static files.
- Data pipeline: Python scripts (`scripts/01_fetch.py` → `scripts/08_assemble.py`) produce GeoJSON/JSON in `data/processed/`; `scripts/bundle_data.py` packages them.

## Capabilities and Constraints

- **No red, green, or yellow anywhere** — not in CSS, charts, map layers, or legends. Design constraint is hard and non-negotiable.
- Diverging color scale: orange spectrum (#f97316 family) = worse/higher pollution; sky-to-deep blue (#38bdf8 / #0ea5e9) = better/lower; violet (#a78bfa) = EJ-tract accent.
- MapLibre base tile style (OpenFreeMap liberty — light tiles) is fixed; map backgrounds must not be changed.
- Plotly chart color constants (PLOT_BG `#0d1526`, GRID_CLR `#1a2d47`, TICK_CLR `#8ba0bc`) are fixed; only surrounding chrome may change.
- File must be openable from the desktop folder with no internet dependency for data (fonts and map tiles require network).
- No framework, no bundler, no Node runtime required.

## Brand Commitments

- Name: **The Toll It Takes** — not to be shortened or altered.
- Byline: Analysis by Furkan Beray — NYC Congestion Pricing Datathon 2026.
- Typography: Bricolage Grotesque (display, wt 800) · Epilogue (body) · Fira Code (mono). Stack is fixed.
- Dark ground: `#070d19`. This is not negotiable; the report is dark-mode only.
- Accent: `#38bdf8` (sky blue). Used for "better" direction, active nav states, and calls to action.

## Evidence on Hand

- `data/processed/its_results.json` — ITS model coefficients for six corridors (~1 MB)
- `data/processed/monitor_stations.geojson` — NYCCAS PM₂.₅ monitor locations
- `data/processed/crz_boundary.geojson` — CRZ toll zone boundary
- `data/processed/dac_tracts_nyc.geojson` — NY State Disadvantaged Community tract designations
- `data/processed/traffic_diversion.json` — B&T crossing diversion residuals
- `data/processed/crz_daily.json` — Daily CRZ vehicle entries (2025–2026)
- `data/processed/nyccas_raster_points.geojson` — Annual NYCCAS PM₂.₅ raster point cloud
- `data/processed/headline_stats.json` — Computed headline numbers
- `data/processed/bt_facilities.geojson` — Bridge and tunnel facility geometries
- `data/processed/canyon_analysis.json` — Mott Haven corridor canyon geometry (H/W ratio, discount)
- `data/processed/corridor_trees.geojson` — Street tree inventory for the green corridor
- `data/processed/corridor_buildings.geojson` — Building footprints for the 3D canyon view
- `data/processed/corridor_streets.geojson` — Street centerlines for the corridor
- `data/processed/corridor_meta.json` — Corridor metadata (canopy coverage, species, projections)
- Key findings: Citywide −4.4% PM₂.₅; Mott Haven β_post = +0.296 µg/m³ (p=0.608); equity β_EJ = +0.457 µg/m³ (p=0.628)

## Product Principles

1. **Evidence before argument.** Every claim traces to a specific model output or data file; no assertion is made without a statistic behind it.
2. **Equity is not a footnote.** The EJ corridor analysis is structurally equal to the citywide finding — it appears in the hero strip, not buried in a table.
3. **Comprehension over decoration.** Visual design exists to make the data legible, not to distract from it. Mode is Read/Experience.
4. **Restraint with color.** The diverging scale carries all semantic weight; neutral surfaces stay near-black with no competing hues.
5. **File-first portability.** The report works identically from a folder on a judge's desktop as from a web server.

## Accessibility & Inclusion

WCAG AA contrast required for all body text and data labels. The no-red/green/yellow constraint also serves colorblind readers (deuteranopia / protanopia). No additional accessibility requirements have been specified beyond these.
