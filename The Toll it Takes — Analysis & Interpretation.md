# The Toll It Takes — Full Analysis & Interpretation
**NYC Congestion Relief Zone · Air Quality & Green Infrastructure**
*Analysis by Furkan Beray · NYC Congestion Pricing Datathon 2026*

---

## Overview: What This Report Is Asking

New York City launched the Central Business District Tolling Program on **January 5, 2025** — the first congestion pricing scheme in the United States. Vehicles entering lower Manhattan below 60th Street now pay a toll. The stated goals: reduce traffic, cut emissions, and fund MTA capital improvements.

This report asks a harder question than "did traffic fall?" It asks: **did the air actually get cleaner, and if so, for whom?** Congestion pricing can reduce emissions inside the toll zone while simultaneously pushing traffic onto alternate routes — routes that run directly through the South Bronx neighborhoods that already bear the highest asthma burden in New York State. The report tests that possibility with real monitoring data and a causal inference model.

The two-part structure follows the evidence. Part I measures what happened. Part II responds to the worst finding with a specific, site-scaled intervention.

---

## Part I: Air Quality Analysis

### The Statistical Method: Interrupted Time Series

Before interpreting any chart, it helps to understand what the model is doing. This analysis uses **Interrupted Time Series (ITS) regression** — a standard method in public health and policy evaluation for situations where a well-defined policy change happened on a known date and you have observations before and after it.

The core idea: fit a model to the pre-toll period that captures the normal trend and seasonal pattern, project what *would have happened* if the toll had never launched, then measure the actual post-toll outcome against that projection. The gap between the projection and reality is the estimated effect of the toll.

The model for each monitoring site is:

```
PM₂.₅ = β₀ + β₁·t + β₂·cos(2πt/365) + β₃·sin(2πt/365)
        + β₄·post + β₅·post·t
        + γ_QC·QC(t) + γ_VW·VW(t) + δ_covid·COVID(t) + ε
```

The terms that matter for interpretation:

- **β₄ (β_post)** — the key coefficient. This is the estimated *step change* in daily PM₂.₅ (µg/m³) at the moment the toll launched, after controlling for everything else. Negative = improvement. Positive = worsening. **This is the number on every chart.**
- **t** (linear trend) and **cos/sin** terms — these remove the normal upward/downward drift and winter/summer seasonality from PM₂.₅ so they don't contaminate the toll estimate.
- **QC(t)** — daily PM₂.₅ at Queens College, a regional background monitor. When wildfire smoke arrives or regional weather stagnates, PM₂.₅ rises everywhere simultaneously. Including QC strips out that regional signal, isolating the toll's local effect.
- **VW(t)** — daily PM₂.₅ at the Van Wyck Expressway, an untolled highway in Queens. If a treatment site moves *with* the Van Wyck after the toll, the change is probably regional or highway-systemic, not toll-specific. If it *diverges*, that's a diversion signal.
- **HAC standard errors** (Newey-West, maxlags=30) — daily pollution data is autocorrelated: a high-pollution day tends to be followed by another high-pollution day. Ordinary regression understates uncertainty in that situation. HAC standard errors correct for this, which is why some p-values here are larger than they would be with naive OLS.

Two specifications are run per site:
- **Full model** (QC + VW, starting Feb 22, 2024 when the Van Wyck monitor came online) — shorter pre-toll window (~10.5 months), but the better causal test.
- **Long-baseline model** (QC only, full history back to 2019) — more pre-toll data, wider confidence intervals, but no diversion test.

---

### Figure 1: PM₂.₅ by Monitoring Corridor (Map)

**What it shows:** A map of New York City with five ITS treatment sites colored by their ITS β_post coefficient. Green dots indicate corridors where air quality improved after the toll. Brick-red dots indicate corridors where it worsened. The Congestion Relief Zone boundary is shown in purple. State-designated Disadvantaged Community (DAC) tracts are outlined.

**How to read it:** The color carries all the information about direction. The dot size stays constant — this is not a bubble chart where size encodes magnitude. To read magnitude, consult the ITS table (Figure 3) or click a dot for the popup.

**What it shows spatially:** The most-improved sites (Manhattan Bridge, Williamsburg Bridge) sit on the Manhattan landings of the East River bridges, approximately 800 m inside the Congestion Relief Zone. The worsened site (Mott Haven) sits in the South Bronx, north and west of the zone boundary — on the same corridor that diverted traffic would use. That spatial pattern is not a coincidence; it is the core finding.

**The DAC overlay:** When you enable the Disadvantaged Community layer, you can see that the two Bronx monitoring sites — the ones that showed worsening or the weakest improvement — sit inside state-designated disadvantaged tracts, as does Manhattan Bridge (per the corrected spatial-join flags). Queensboro Bridge and SI Expressway are the main non-EJ sites in the analysis.

---

### Figures 2a–2f: Observed vs. Counterfactual, Site by Site

**What they show:** For each ITS treatment site, a time series of daily PM₂.₅ from the start of the monitoring record through mid-2026. Two traces:
- **Black line (Observed):** Actual daily PM₂.₅ readings at the monitor, smoothed to show the signal.
- **Grey dashed line (Counterfactual):** What the ITS model predicts would have happened if the toll had never launched, projected forward from the pre-toll trend.
- **Grey band:** 95% confidence interval around the counterfactual.
- **Purple vertical line:** January 5, 2025 — toll launch.

**How to read them:** After the purple line, look at whether the observed (black) trace runs above or below the counterfactual (grey dashed). If observed is below the counterfactual, the toll improved air quality at that site. If it's above, air quality worsened relative to what would have happened.

**Site-by-site interpretation:**

**Mott Haven** — β_post = **+0.296 µg/m³**, p = 0.608
The observed trace after January 2025 runs above the counterfactual. Air quality is slightly *worse* than the model predicts it would have been without the toll. The pre-toll mean at this site was 7.45 µg/m³; the post-toll mean is 7.88 µg/m³. The +0.296 µg/m³ step-change estimate represents the toll's estimated contribution to that rise, controlling for seasonal patterns and regional events.

The p-value of 0.608 means this result is not statistically significant. Under the null hypothesis of no toll effect, there is a 61% chance of observing a step-change this large or larger purely by random variation. The confidence interval runs from −0.834 to +1.425 µg/m³ — it includes zero. The worsening is real in the data but cannot be attributed to the toll with statistical confidence. This is a *direction*, not a verdict. Under a step-only specification the estimate is −0.65 (p = 0.012); the raw same-season change is +0.09, or +0.87 relative to Van Wyck and −0.22 relative to Queens College. The direction at Mott Haven depends on specification and control choice; the data do not support a stable claim that it worsened.

**Cross Bronx Expressway** — β_post = **−0.523 µg/m³**, p = 0.210, [CI: −1.340, +0.295]
The observed trace runs slightly below the counterfactual — an apparent improvement. But p = 0.21, and the confidence interval straddles zero. The long-baseline specification gives β_post = −0.968 µg/m³ (p = 0.767) — directionally the same but noisier. This site's R² = 0.956 means the model explains 95.6% of the pre-toll variance; the remaining 4.4% of variation is substantial enough at daily resolution to swamp the toll's modest estimated effect.

**Hunts Point** — excluded from ITS (monitor offline Sept 2023–March 2025)
The Hunts Point monitor was offline for the 547 days spanning the toll-start date, so there are zero pre-toll observations in the VW window. Because the pre-toll trend and post-toll step cannot both be estimated at the toll date, Hunts Point is excluded from all ITS, equity, and school-zone analyses. It is omitted from all charts and tables, not asterisked. Hunts Point is in the middle of the Bronx industrial waterfront and its PM₂.₅ is driven by a complex mix of sources (the food distribution hub, the Hunts Point meat market, marine traffic) that the QC covariate may not fully capture.

**Manhattan Bridge** — β_post = **−1.328 µg/m³**, p = 0.027, [CI: −2.508, −0.147]
The most robust result in the dataset: −1.33 in the full model, −0.86 (p = 0.003) in a step-only model, and a matched-day decline of −1.24 µg/m³ (−0.60 relative to Van Wyck on matched days). The observed trace drops clearly below the counterfactual after January 2025. The 95% confidence interval does not include zero: [−2.508, −0.147]. 2024 mean 9.35 µg/m³, 2025 mean 7.89 µg/m³.

The γ_VW coefficient here is 0.671 — a strong positive loading on the Van Wyck covariate. This means Manhattan Bridge PM₂.₅ tracks significantly with the Van Wyck highway corridor, which makes sense: both sites are near high-volume approach roads. The fact that Manhattan Bridge improved *despite* this shared loading suggests the toll created a real local effect beyond regional fluctuations.

**Williamsburg Bridge** — β_post = **−1.035 µg/m³**, p = 0.026, [CI: −1.949, −0.122]
Significant in the full model (p = 0.026) and borderline in a step-only specification (−0.47, p = 0.065); the long baseline gives +1.78 (p = 0.59). The matched-day decline (−1.86; −0.81 relative to Van Wyck on matched days) supports an improvement, but its size is specification-dependent. The full model is preferred because it includes the Van Wyck covariate.

**Queensboro Bridge** — β_post = **−1.098 µg/m³**, p = 0.205, [CI: −2.798, +0.601]
The estimated improvement is large in magnitude — comparable to the two significant sites — but the confidence interval is wide and straddles zero. This site is the only non-EJ-designated monitor in the analysis. The long-baseline gives −3.709 µg/m³ (p = 0.195), consistent in direction but not narrowing the uncertainty. The Queensboro corridor bridges Queens and upper Manhattan; traffic patterns there are more complex (multiple alternate routes) than for the East River bridge crossings directly at the CRZ boundary.

---

### Figure 3: ITS Regression Results Table

**What it shows:** A summary table of β_post, 95% confidence intervals, p-values, control-site coefficients (γ_QC, γ_VW), R², and sample size for every site-specification combination.

**How to read it:**
- Sites are ordered by β_post, worst to best.
- A result marked "Significant" has p < 0.05 and a confidence interval that does not cross zero. Significance refers to the full model. Section 5 shows which results hold under a step-only specification.
- R² values are all above 0.90 except the Queensboro Bridge long-baseline (R² = 0.704) — a reminder that long histories with more structural breaks are harder to model.
- γ_QC is consistently large (0.57–1.37) across all sites, confirming that regional air quality is the dominant driver of daily PM₂.₅ at every monitor. The toll's estimated effect is what remains after removing that regional component.
- γ_VW values (0.05–0.67) are smaller and more variable — the Van Wyck covariate adds precision at bridge-adjacent sites (Manhattan Bridge 0.67, Williamsburg Bridge 0.43) but contributes less at interior Bronx sites (Cross Bronx 0.05, Mott Haven 0.15).

**The uncomfortable arithmetic:** The two most robust improvements are both at the Manhattan landings of East River bridges inside the CRZ (approximately 800 m from the zone edge), with Queensboro Bridge showing a similar improvement under the step-only specification. The three Bronx EJ sites show no reliable change in either direction. With five ITS sites, the analysis lacks the power to settle the equity question — but the pattern is worth taking seriously.

---

### Figure 4 (Section 3.5): Schools in the Corridor That Got Worse

**What it shows:** A two-part section. First, a table showing how many DOE schools fall within 400 m of each monitor, alongside that site's β_post. Second, for Mott Haven specifically, a named list of every school with its address and distance from the monitoring sensor.

**What it means:**

The table exposes a geometric fact that the corridor-level analysis obscures: the distribution of schools across monitored sites is not even, and it correlates with outcomes in the worst possible way.

| Corridor | β_post | Schools within 400 m |
|---|---|---|
| Mott Haven | +0.30 µg/m³ | **9** |
| Williamsburg Bridge | −1.04 µg/m³ | 5 |
| Cross Bronx Expy | −0.52 µg/m³ | 2 |
| Hunts Point | −0.19 µg/m³ | 2 |
| Manhattan Bridge | −1.33 µg/m³ | 2 |
| Queensboro Bridge | −1.10 µg/m³ | 0 |

The corridor with the worst post-toll outcome has more than twice as many schools as any other corridor. The corridor with the best outcome (Queensboro Bridge, the only non-EJ site) has none.

Within Mott Haven, the two closest schools — **P.S. 043 Jonas Bronck** (76 m) and **Mott Haven Academy Charter School** (114 m) — are effectively adjacent to the air quality sensor on Brown Place. These are elementary schools. Their proximity to the monitor means that what the monitor reports is approximately what children at those schools are breathing during recess, at drop-off, and during any outdoor activity.

**The NYC Admin Code §24-163 angle:** This law limits vehicle idling to one minute in school zones (vs. three minutes citywide) and is enforceable by any citizen through DEP's Idling Complaint System under Local Law 58 (2018). The corridor-level ITS analysis cannot distinguish school frontages from the rest of the block — both contribute to the monitor's readings equally. The school-zone framing makes that distinction concrete: these specific addresses are where the 1-minute rule applies, where community enforcement is legal and incentivized, and where the green screen typology is targeted.

---

### Figure 5: Monthly Idling Complaints Near Mott Haven Schools (311 Chart)

**What it shows:** A bar chart of 311 complaint counts per month, filtered to *Noise - Vehicle / Engine Idling* reports filed within 400 m of the Mott Haven monitor. Bars before January 2025 are grey (pre-toll); bars after are brick-colored (post-toll). The purple vertical line marks the toll launch.

**How to read it:** This is a community-reported signal, not a pollution measurement. A rising bar means more complaints were filed, not necessarily that more idling occurred.

**What it means — carefully:** There are two valid interpretations of any post-toll rise in complaints:
1. **More idling:** Traffic rerouted to avoid the toll increased heavy vehicle volumes near these schools, leading to more actual idling events.
2. **More awareness:** Local Law 58 (2018) entitles complainants to a share of any fine. If post-toll media coverage increased awareness of the Citizens Air Complaint Program, more residents would file — regardless of whether actual violations increased.

Both interpretations can be true simultaneously. The chart is presented as independent corroboration from the community, not as evidence that the toll caused more idling. The distinction matters: the ITS model uses calibrated instruments; the 311 data uses self-selected reporters. Use the ITS result for causal inference; use the 311 chart as a community-level signal that residents near these schools are responding to something.

---

### Figure 6: Did EJ-Designated Sites Fare Worse? (Equity Chart)

**What it shows:** A scatter plot with each ITS treatment site as a point. The x-axis is the site's pre-toll mean PM₂.₅ (a proxy for baseline pollution load); the y-axis is β_post (the ITS step-change). Points are colored by EJ designation (corrected spatial-join flags): brick for EJ-designated sites, green for non-EJ. Symbol indicates CRZ membership: circles for outside-zone sites, squares for inside. No site-level regression line is shown — the estimate is read from the panel model.

**The equity estimate:** Panel estimates (site + date FE, 11 sites) of an EJ gap run from −0.38 to +0.02 µg/m³ depending on flag definition (B1: −0.07, p=0.77; B2: −0.38, p=0.65; B3: +0.02, p=0.96), none significant. EJ status is confounded with zone status: every in-zone monitor except Queensboro sits in a designated tract, and so does every outside-zone monitor with a full pre-toll record.

**What the data supports:** Geography, not a measured EJ gap. Inside the zone improved; no outside-zone site did — EJ or not, Bronx or not (see Check 9). The panel cannot separate the zone effect from the EJ effect with the current monitoring network. **This result does not prove that the toll disproportionately harmed EJ communities — nor does it rule it out.**

The cross-sectional comparison (five ITS sites) is shown for geographic context only. With four EJ sites and one non-EJ site (Queensboro), a three-parameter OLS has essentially no degrees of freedom; any resulting coefficient and p-value are uninformative and should not be cited as a finding.

**What the geometry tells us:** The two most-improved sites (Manhattan and Williamsburg Bridges) sit approximately 800 m inside the toll zone — where CRZ entry-reduction has its most direct impact on local traffic. The two Bronx EJ sites (Cross Bronx, Mott Haven) sit several miles north, where diverted traffic arrives rather than departs. Geography, not discrimination, is the most parsimonious explanation for the pattern — which makes it no less urgent to address.

---

### Figure 7: Traffic Diversion by Bridge and Tunnel (Map + Bar Chart)

**What they show:** A map of MTA Bridge and Tunnel facilities colored by their post-toll traffic residual (actual volume minus the pre-toll OLS forecast). The companion bar chart ranks all facilities by residual in vehicles per day. Positive residuals (brick) = more traffic than expected; negative (green) = less.

**The diversion model:** For each facility, an OLS baseline was trained on 2019–2024 daily crossing volumes with controls for linear time trend, month fixed effects, and day-of-week fixed effects. The residual = actual post-toll volume − model forecast. This captures changes in volume *beyond* what the normal seasonal and weekly cycle would predict.

**Actual results:**

| Facility | Residual (veh/day) | % vs forecast | Bronx-relevant |
|---|---|---|---|
| Throgs Neck Bridge | **+2,041** | +1.82% | **Yes** |
| Cross Bay Bridge | +450 | +2.07% | No |
| Marine Parkway Bridge | +304 | +1.42% | No |
| Henry Hudson Bridge | −1,594 | −2.44% | No |
| RFK Bridge (Manhattan) | −1,646 | −4.02% | No |
| RFK Bridge (Bronx) | −2,380 | −1.78% | **Yes** |
| Bronx-Whitestone Bridge | −4,093 | −3.11% | No |
| Queens Midtown Tunnel | −5,227 | −6.83% | No |
| Hugh L. Carey Tunnel | −7,882 | −14.22% | No |
| Verrazzano-Narrows Bridge | **−62,571** | **−35.25%** | No |

**How to read this — carefully:** The Verrazzano-Narrows residual (−62,571 veh/day, −35%) looks alarming but is most likely a data artifact: the toll zone made Staten Island crossings more expensive relative to non-tolled alternatives, causing a structural break in volume that the pre-toll trend model wasn't calibrated for. Large residuals at facilities far from the zone boundary should be treated with skepticism.

The finding that matters for this report: **Throgs Neck Bridge** shows the largest positive residual of any Bronx-relevant facility: +2,041 vehicles/day above forecast. The Throgs Neck connects Queens and the Bronx and is used by drivers routing around lower Manhattan via the Bruckner Expressway — a route that passes directly through Mott Haven and Hunts Point. A +1.82% volume increase might sound small, but 2,041 additional vehicles per day on a corridor that already carries ~112,000/day represents a meaningful emissions increment, especially if those vehicles skew toward heavy trucks.

**What this does and doesn't prove:** The diversion model is a correlation, not a causal chain. We observe that Throgs Neck volume increased beyond its seasonal forecast; we do not directly observe that those vehicles were avoiding the toll or that they drove through Mott Haven. The alignment between a positive diversion residual at a Bronx-relevant bridge and a positive β_post at the Mott Haven monitor is suggestive, not conclusive. The pre-toll traffic–PM₂.₅ relationship implies only +0.04 µg/m³ from the Throgs Neck residual — about one-eighth of the observed Mott Haven step — so diversion cannot account for most of the increase.

---

### Figure 8: CRZ Vehicle Entries Since Toll Launch

**What it shows:** A bar chart of daily total vehicle entries into the Congestion Relief Zone from January 5, 2025 through mid-2026, with a 7-day rolling average line. The toll date is marked. Daily bars are colored by the toll purple (#4B2E83).

**Key numbers:**
- Average daily entries: **484,283 vehicles/day**
- Clear weekday/weekend seasonality: weekday peaks substantially exceed weekend averages
- Modest upward trend through spring 2025 — consistent with behavioral adaptation (initial avoidance fading as drivers price in the toll)

**What it means:** The toll did reduce CRZ entries — total volumes are materially below the 2019–2024 pre-toll baseline. This is confirmation that the toll's primary mechanism (reducing entries) worked. The question the ITS analysis addresses is: *where did those vehicles go, and what happened to air quality in their wake?*

The upward trend in entries through 2025 is worth watching. If drivers continue adapting and entries trend back toward pre-toll levels, the air quality benefits at bridge-adjacent sites could erode. If a behavioral equilibrium has been reached around ~480,000 entries/day, the effects are likely to remain stable.

---

### Check 9: Outside-Zone PurpleAir Sensors — Filling the Missing Cell

The NYCCAS panel has no outside-CRZ, non-EJ sites. To test whether the EJ estimate changes when such sites are added, twelve community-operated PurpleAir sensors were evaluated; six passed a minimum quality bar (≥70% daily coverage, ≥200 pre-toll days). Three met the primary 80% threshold.

**Primary set (≥80% coverage, ≥200 pre-toll days):**

| Sensor | Neighborhood | EJ | Borough | Coverage |
|---|---|---|---|---|
| 89th & Ridge Ave | Bay Ridge | No | Brooklyn | 90.6% |
| RGBIV | Sunset Park | No | Brooklyn | 96.2% |
| FA_O5 | Washington Heights | Yes | Manhattan | 90.0% |

**Sensitivity set (adds three sensors at ≥70%):** Red Hook Farms (EJ, Brooklyn, 73.3%), SITHS256O (non-EJ, Staten Island, 77.0%), Hudson View Gardens (non-EJ, Manhattan, 72.0%). Hudson View had 229 days of physically impossible readings (~6,000 µg/m³) removed by a plausibility filter; it appears only in the sensitivity set.

**Spec B EJ estimates (β_EJ, wild bootstrap 95% CI):**

| Specification | β_EJ | 95% CI |
|---|---|---|
| B1 baseline — NYCCAS only | −0.07 | [−0.56, +0.41] |
| B1 extended — 80% primary (3 PA sensors) | −0.21 | [−0.59, +0.17] |
| B1 extended — 70% sensitivity (6 PA sensors) | −0.47 | [−1.00, +0.05] |
| B3 baseline — outside-CRZ NYCCAS only | +0.02 | [−0.77, +0.81] |
| B3 extended — 80% primary | −0.19 | [−0.58, +0.20] |
| B3 extended — 70% sensitivity | −0.52 | [−1.15, +0.12] |
| PA-only — 80% primary (3 clusters) | −0.14 | [−0.66, +0.38] |
| PA-only — 70% sensitivity (6 clusters) | −0.53 | [−1.24, +0.19] |

All intervals span zero. The 70% estimates shift slightly toward EJ sites doing better (more negative β_EJ), not worse.

**Check 7 matched-day DiD (2025 vs. 2024, µg/m³):**

| Sensor | Type | Raw Δ25 | −VW 2025 | −VW 2026 | −QC 2025 | −QC 2026 |
|---|---|---|---|---|---|---|
| Cross Bronx Expy | NYCCAS/EJ | −0.16 | +0.97 | −0.15 | −0.11 | +0.21 |
| Mott Haven | NYCCAS/EJ | +0.08 | +0.87 | +0.85 | −0.22 | +0.86 |
| FA_O5 | PA/EJ | +0.74 | +1.19 | +1.41 | +0.66 | +1.29 |
| Red Hook Farms | PA/EJ | −1.38 | +0.51 | −1.48 | +0.35 | −1.59 |
| 89th & Ridge | PA/non-EJ | +0.25 | +0.85 | +0.10 | +0.34 | −0.09 |
| Hudson View | PA/non-EJ | +0.52 | +0.71 | +1.03 | +0.07 | +0.85 |
| RGBIV | PA/non-EJ | +0.48 | +1.26 | +1.69 | +0.81 | +1.21 |
| SITHS256O | PA/non-EJ | −0.16 | +0.55 | +0.03 | −0.46 | −0.70 |

Adding volunteer sensors outside the zone does not change the EJ estimate. With the three sensors that meet the 80% coverage standard, β_EJ ranges from −0.14 to −0.21 across specifications, and every confidence interval spans zero. Adding three lower-quality sensors at a 70% threshold moves the estimate to −0.47 to −0.53, still spanning zero, in the direction of EJ sites doing slightly better. Relative to Van Wyck, every outside-zone sensor rose by 0.5–1.3 µg/m³ in 2025, EJ and non-EJ alike; relative to Queens College, changes are smaller and mixed (−0.5 to +0.8) with no EJ pattern. The distinction that holds is inside-zone versus outside-zone, not EJ versus non-EJ, and not Bronx versus elsewhere.

**Limitation:** Both Queens control monitors fell from 2024 to 2025 while most outside-zone sites rose relative to them, so part of the outside-zone "increase" may be control drift rather than site worsening. The inside-zone decrease is robust to either control.

---

## Part II: Green Corridor Design for Mott Haven

### Why Mott Haven Was Selected

Mott Haven was selected based on its pre-existing environmental conditions: among the highest pediatric asthma rates in New York State, a 4.0% tree canopy against a 22.1% citywide average, nine school entries (six physical buildings) within 400 m of the monitor, and direct adjacency to major truck routes and the Major Deegan and Cross Bronx expressways.

The toll's signal at this site is directionally uncertain: β_post = +0.296 µg/m³ in the full model (p = 0.608, not significant), −0.65 µg/m³ under a step-only specification (p = 0.012, significant). The step-only result is significant; the direction depends on whether a post-toll drift term is included. The case for intervention does not rest on any of them — it rests on the pre-existing conditions, which are independently verifiable and would warrant a green infrastructure response regardless of what the toll did.

---

### Figure 1 (Part II): Corridor Conditions Map

**What it shows:** A close-up map of the Mott Haven corridor (approximately 800m × 800m around the NYCCAS monitor at 40.806°N, 73.922°W). Three layers:
- **Green circles:** Street trees from the 2015 NYC Street Tree Census, sized proportionally to trunk diameter (DBH). Larger circles = bigger, older, more effective trees.
- **Grey buildings:** Building footprints from NYC Open Data, shaded by height. Taller buildings appear darker.
- **Black cross:** The NYCCAS monitoring station location.
- **Purple dashed lines:** NYC truck routes (if enabled).
- **H/W annotation:** The computed canyon height-to-width ratio.

**How to read it:** Look at how sparse the green circles are relative to the street grid. The 2015 census found 1,445 trees in this corridor — 25.7 trees per mile of street — against a citywide average of 142 trees per mile. That is a density gap of 5.5×. Most streets visible on the map have no tree circles at all on the south-facing (truck route) side, which is precisely where the green screen typology targets its intervention.

The building height pattern shows a mix of 2–4 story rowhouses (32–40 ft) and occasional taller structures. The median building height of **32.7 ft** against a median street width of **32.0 ft** gives H/W = 1.022 — the cornerstone of the typology selection.

---

### The Canyon Geometry: Why H/W Matters

**The computed values:**
- Mean building height: **32.7 ft** (≈ 10 m)
- Median street width: **32.0 ft** (≈ 9.8 m)
- H/W ratio: **1.022**
- Canyon discount: **13.1%**

An H/W of 1.022 means buildings are approximately as tall as streets are wide. This places Mott Haven in the *moderate canyon* range. The canyon discount formula (Li et al. 2019, Morakinyo & Lam 2016) applies a continuous efficiency penalty to on-street vegetation once H/W exceeds 0.5:

```
canyon_discount = min(0.60, max(0, (H/W − 0.5) × 0.25))
```

At H/W = 1.022: discount = (1.022 − 0.50) × 0.25 = **13.1%**

What this means physically: in a moderate street canyon, pollution emitted at street level recirculates before dispersing upward. Some of the PM₂.₅ that trees would otherwise capture gets trapped in the recirculation zone and re-exposits onto leaf surfaces from below rather than being swept away. The net result is a 13% reduction in effective removal compared to the same trees planted in an open setting.

This 13% discount is not trivial — it is the reason the analysis shows both naïve and adjusted removal estimates, and it directly informs the choice of tree spacing. Dense trees (20 ft apart) create a more continuous canopy that deepens the recirculation zone; spaced trees (40 ft apart) allow more lateral air exchange. At H/W = 1.022, dense trees still deliver more total removal in adjusted terms, but the gap between dense and spaced narrows compared to an open setting.

---

### Figure 2: Naïve vs. Canyon-Adjusted Annual Removal

**What it shows:** A horizontal bar chart comparing three (now four) green infrastructure typologies on annual PM₂.₅ removal (kg/year). Each typology shows two bars: the naïve estimate (what removal would be with no canyon effect) and the canyon-adjusted estimate (the realistic figure after the 13.1% discount for tree typologies).

**The actual numbers:**

| Typology | Scope | Naïve (kg/yr) | Canyon-adjusted (kg/yr) | Discount |
|---|---|---|---|---|
| Dense street trees (20 ft) | 14,864 trees, full corridor | 6,934 | **6,030** | 13% |
| Spaced street trees (40 ft) | 7,432 trees, full corridor | 3,467 | **3,286** | 5% |
| Green wall (south-facing facades) | 16,570 m² leaf area, structural | 14.9 | **14.2** | 5% |
| Green screen (school frontage) | 2 school frontages, 180 ft × 20 ft | 13.4 | **12.3** | 8% |

**How to read it:** The gap between naïve and adjusted bars is the visual argument for typology selection. The wider the gap, the more the canyon penalty hurts that typology. Dense trees take the largest absolute hit (−905 kg/yr) but still outperform all alternatives because of their sheer number of trees and leaf area.

**What it means:**
- **Dense street trees** deliver 6,030 kg/yr of PM₂.₅ removal at full maturity. To contextualize: EPA modeling suggests that reducing PM₂.₅ by 1 µg/m³ over the 0.64 km² corridor area for one year requires approximately 2,000–5,000 kg of removal. Dense tree planting could therefore reduce corridor-average PM₂.₅ by **1.2–3.0 µg/m³** — a meaningful fraction of the 7.45 µg/m³ pre-toll baseline and a substantial offset against the +0.30 µg/m³ toll-associated worsening.
- **Spaced street trees** deliver 3,286 kg/yr — about half the dense estimate — but their smaller canyon penalty per tree (5% vs. 13%) makes them the better choice in corridors with deeper canyons (H/W > 1.5). At H/W = 1.022, dense trees win.
- **Green wall** at 14.2 kg/yr is approximately 425× less effective than dense tree planting in total mass removal. It is not a substitute; it is a complement for locations where below-grade soil volume prevents tree planting. Its stable removal rate (unlike trees, a wall does not grow) and thermal insulation benefits justify it in constrained locations.
- **Green screen** at 12.3 kg/yr is similar in scale to the green wall. Its value proposition is not mass removal but *location* — it intercepts PM₂.₅ at the breathing level of children at the two schools closest to the monitor. A small intervention targeted at the right place.

---

### Figure 3: Canyon Discount by H/W Ratio

**What it shows:** The discount curve as a function of H/W ratio — a line that starts at 0% discount (H/W = 0.5), rises linearly to 60% at H/W = 2.5, and stays there. A vertical dashed line marks Mott Haven's H/W = 1.022, showing where this corridor falls on the curve.

**Why this figure exists:** The discount is not an assumption; it is a computed output of the site geometry. Showing the curve makes the methodology falsifiable: if a reader believes the actual H/W ratio is different (e.g., because building heights or street widths were measured differently), they can read the resulting discount off the curve and recalculate.

At H/W = 1.022, the discount is 13.1% — far below the 60% maximum that would apply in the deepest canyons (e.g., Midtown Manhattan side streets, H/W ≈ 3+). Mott Haven's canyon is moderate, not extreme. Dense tree planting here is still highly effective.

---

### Figure 4: Projected PM₂.₅ Removal Over Time

**What it shows:** A line chart with three time points (Year 1, Year 10, Year 20) for each typology. Each line shows how much PM₂.₅ removal (kg/yr) the typology delivers as trees grow and canopy expands.

**The maturation model:** Based on USFS NRS-117 DBH growth rates for NYC street trees:
- Year 1: 10% of mature removal (small saplings, minimal leaf area)
- Year 10: 55% of mature removal (established trees, substantial canopy)
- Year 20: 90% of mature removal (approaching full size)

**The actual trajectories:**

| Typology | Year 1 | Year 10 | Year 20 |
|---|---|---|---|
| Dense street trees | 603 kg/yr | 3,316 kg/yr | 5,427 kg/yr |
| Spaced street trees | 329 kg/yr | 1,807 kg/yr | 2,958 kg/yr |
| Green wall | 14.2 kg/yr | 14.2 kg/yr | 14.2 kg/yr |
| Green screen | 12.3 kg/yr | 12.3 kg/yr | 12.3 kg/yr |

**How to read it:** The steep upward slope of the tree typologies is the key message. Year 1 removal from dense trees (603 kg/yr) is nearly identical to the green wall's permanent ceiling (14.2 kg/yr ×40 = 568 kg/yr, scaled for coverage) — trees quickly overtake any wall-based approach. By Year 10 the gap is enormous. By Year 20, dense tree planting delivers ~424× more removal than the green screen or wall.

The flat lines for green wall and green screen are structural: vegetative surfaces reach their effective area at planting and do not grow beyond it. Their value is in the short term (immediate deployment, immediate benefit) and in constrained locations. The school frontage green screen begins working on day one; the trees that would eventually shade those same students won't reach their full effectiveness for two decades.

**The long-term argument:** If NYC were to plant dense street trees in Mott Haven today, by 2045 the corridor would be removing 5,427 kg/yr of PM₂.₅ — roughly a 0.5–1.5 µg/m³ reduction in corridor-average concentration, sustained indefinitely as long as the trees are maintained. This is not a response to the toll; it is a permanent infrastructure investment that addresses the corridor's pre-existing 18.1 percentage-point canopy deficit.

---

### The Species Table

**What it shows:** Four species recommended for Mott Haven's specific site conditions: canyon H/W = 1.022, heavy truck routes, road salt exposure, compacted soil, and elevated PM₂.₅.

**Species and rationale:**

**1. Thornless Honeylocust** (*Gleditsia triacanthos f. inermis*) — DBH at 20yr: 12"
NYC's most widely planted street tree. Its open, fine-textured canopy dapples shade without closing the canyon — important at H/W = 1.022 where a dense canopy roof could worsen recirculation. Very high pollution and salt tolerance. Fast early growth means this species contributes meaningfully by Year 10 even from a small planting DBH.

**2. Swamp White Oak** (*Quercus bicolor*) — DBH at 20yr: 14"
At 14 inches after 20 years, this species has the largest projected crown of the four — which directly translates to the highest per-tree PM₂.₅ removal via DBH scaling (removal ∝ DBH^1.5). Long-lived (200+ years) — a single planting round creates a permanent PM₂.₅ sink. Moderate salt tolerance means it should be used on interior blocks away from the most-salted truck arterials.

**3. Lacebark Elm** (*Ulmus parvifolia*) — DBH at 20yr: 11"
Very high pollution tolerance and high salt tolerance. Vase-shaped form maintains truck clearance underneath while spreading laterally above — useful on the narrower cross-streets where truck route clearance matters. Disease-resistant (unlike American Elm). Recommended as a diversity pairing alongside Honeylocust to avoid single-species vulnerability.

**4. Maidenhair Tree** (*Ginkgo biloba*, male cultivars only) — DBH at 20yr: 8"
The most pollution-tolerant tree in the NYC palette by empirical evidence. Columnar-conical form at young age minimizes the wind shadow on street-level truck lanes, potentially allowing the upper canopy to intercept PM₂.₅ from the regional airshed while minimizing contribution to canyon recirculation. **Male cultivars only** — female trees produce malodorous fruit that creates maintenance problems and community complaints. The 'Autumn Gold' and 'Princeton Sentry' cultivars are safe choices.

---

### The Green Screen Typology: Section 5 (Part II)

**What it shows:** A fourth typology alongside dense trees, spaced trees, and green wall: a dense vegetative barrier — living wall panels or a wire-and-vine trellis — installed specifically at the playground and entrance frontages of the two closest schools on Brown Place.

**The numbers:**
- Frontage: 180 ft (55 m) — covering the street-facing walls of PS 043 Jonas Bronck and Mott Haven Academy Charter School
- Height: 20 ft (6 m) — standard for modular living wall or trellis system
- Surface area: 334 m² (vs. 372 m² for the 200-ft green wall in the base analysis)
- Removal rate: 0.04 g PM₂.₅/m²/year (Speak et al. 2012 — conservative, direct surface deposition only)
- Naïve removal: 13.4 kg/yr
- Canyon-adjusted: 12.3 kg/yr (8% discount — lower than tree discount because vertical surfaces flush more directly with mean airflow rather than sitting in the recirculation zone)

**Why this is the right scale:** The green screen does not compete with corridor-wide tree planting. It removes 12.3 kg/yr against 6,030 kg/yr for dense trees — a factor of 490× less. Its purpose is different: it targets the specific surfaces where children breathe during outdoor time, concentrating an intervention at the locations the monitor cannot distinguish from the rest of the block. It is analogous to a surgical intervention alongside a systemic treatment — both are needed; they operate at different scales.

---

### Methodology & Limitations: What the Numbers Don't Prove

**i-Tree approximation (±30–50% on removal estimates):** The PM₂.₅ removal estimates use published per-tree rates from Nowak et al. (2006, 2018) scaled by DBH. The i-Tree Eco desktop model would produce site-specific results at the individual-tree level using actual local meteorology and hourly pollution concentrations. The approximation used here is adequate for typology comparison (the relative differences between typologies are robust even if the absolute numbers shift) but should not be cited as a precise forecast.

**2015 Street Tree Census:** The canopy gap estimate uses 11-year-old data. Some trees have died, been removed, or been planted since. South Bronx neighborhoods have historically maintained the lowest canopy cover in NYC, so the direction of the gap (Mott Haven well below citywide average) is almost certainly still valid. The exact 18.1 percentage-point gap might be smaller or larger today.

**Canyon discount is 2D:** The H/W-based discount is derived from 2D LES simulations of idealized street canyon geometry. Real corridors have intersections (which flush the canyon), building setbacks, gaps between buildings, and varying heights. The actual discount is likely somewhere between the naïve and adjusted estimates.

**Mott Haven β_post is not significant:** The Part II intervention is motivated by the directional signal and pre-existing conditions, not by a proven causal toll impact. This is stated explicitly throughout. The tree planting argument does not require the toll to have caused the worsening — Mott Haven's canopy gap is a pre-existing problem worth addressing regardless.

**Control-site drift:** On matched days, Van Wyck fell 0.48 µg/m³ and Queens College fell 0.24 µg/m³ from 2024 to 2025, so site-minus-control estimates shift by about 0.2 µg/m³ depending on which control is used.

**Complaint counts are not pollution counts:** The 311 idling complaint chart reflects reporting behavior as much as actual violations. Do not interpret it as a direct measure of PM₂.₅ or idling frequency.

---

## Putting It All Together: The Core Argument

The data tells a coherent story, even in the presence of statistical uncertainty:

**1. The toll's primary mechanism worked.** CRZ entries fell to ~484,000/day from pre-toll baselines. The three East River bridge sites — all inside or on the boundary of the CRZ — showed improvements of roughly 0.5–1.3 µg/m³ relative to control. Manhattan Bridge is significant under both specifications tested; Williamsburg and Queensboro are each significant in one specification and borderline in the other. The air genuinely got cleaner where the toll's effect was most direct.

**2. The Bronx EJ corridors did not share equally in the benefit.** The two Bronx monitoring sites with valid ITS results — both in state-designated disadvantaged community tracts — showed either uncertain improvement or directional worsening. Mott Haven's β_post = +0.296 µg/m³ is not statistically distinguishable from zero. Under a step-only specification the estimate is −0.65 (p = 0.012); the raw same-season change is +0.09, or +0.87 relative to Van Wyck and −0.22 relative to Queens College. The direction at Mott Haven depends on specification and control choice; the data do not support a stable claim that it worsened.

**3. Traffic diversion provides a plausible mechanism.** The Throgs Neck Bridge, which serves routes through the South Bronx, showed +2,041 vehicles/day above its seasonal forecast — the largest positive residual at any Bronx-relevant facility. This is consistent with drivers rerouting through the Mott Haven corridor to avoid the toll, though it does not prove causation.

**4. The school-zone layer makes the equity question concrete.** Nine schools within 400 m of the Mott Haven monitor — more than any other corridor. P.S. 043 Jonas Bronck sits 76 m from the air quality sensor. The monitor's reading is approximately what children breathe at recess. The §24-163 school-zone idling limit gives community members a direct enforcement tool that the corridor-level analysis does not surface.

**5. Dense street tree planting addresses the underlying deficit.** Mott Haven's canopy gap (4.0% vs. 22.1% citywide) is a pre-existing environmental justice issue that the toll made more urgent but did not create. Planting 14,864 trees at 20 ft spacing could deliver 6,030 kg/yr of PM₂.₅ removal at full maturity — a meaningful local intervention. It does not solve the equity problem in the toll; it addresses the parallel problem of systematic underinvestment in green infrastructure in EJ communities.

**The honest uncertainty:** Neither the Mott Haven worsening nor the EJ equity gap can be attributed to the toll with statistical confidence. The analysis is transparent about this throughout. But statistical insignificance does not mean the finding is unimportant — it means more data is needed. With more monitoring sites, a longer post-toll window, and expanded community air monitoring (e.g., PurpleAir sensors at school frontages), these questions could be answered definitively within two to three years.

Until then, the directional evidence is sufficient to warrant action. The green infrastructure gap at Mott Haven is real and independently verifiable. The school-zone exposure is a geometric fact, not a statistical inference. And the enforcement tool — §24-163 and Local Law 58 — already exists, waiting for community members with smartphones to use it.

---

## Data Sources

| Dataset | Source | Coverage |
|---|---|---|
| NYCCAS hourly PM₂.₅ monitors | NYC Community Air Survey | 2019–2026 |
| NYCCAS annual PM₂.₅ rasters | NYCCAS data portal | 2008–2024 |
| MTA CRZ vehicle entries | MTA Open Data | Jan 2025–Aug 2026 |
| MTA B&T hourly crossings | MTA Bridges & Tunnels | 2019–2026 |
| NY State DAC designations | Socrata `2e6c-s6fp` | 2022 (current) |
| NYC Street Tree Census | NYC Parks / Open Data | 2015 |
| LION street centerlines, v24B | NYC Planning | — |
| NYC Building Footprints | NYC DoITT / Socrata | Current |
| MapPLUTO 26v2 | NYC Planning | — |
| NYC Truck Routes | NYC DOT | Current |
| NYC DOE School Point Locations | NYC Open Data `a3nt-yts4` | Current |
| 311 Engine Idling Complaints | NYC Open Data `erm2-nwe9` | 2010–2026 |
| LGA ASOS weather (temp, wind, RH, precip) | Iowa Environmental Mesonet | 2019–2026 |
| Hourly NO₂ monitors (IS 52, Pfizer Lab) | US EPA AQS | 2022–2025 |
| PurpleAir outdoor sensors, EPA-corrected | PurpleAir API | 2024–2026 |

---

## References

- Nowak, D.J. et al. (2006). Air pollution removal by urban trees and shrubs in the United States. *Urban Forestry & Urban Greening* 4(3–4), 115–123.
- Nowak, D.J. et al. (2018). Leaf area and leaf biomass of individual trees in cities across the globe. *Forest Ecology and Management* 424, 374–381.
- Hirabayashi, S. (2012). *i-Tree Eco Hourly Air Quality Analysis*. USDA Forest Service.
- Li, X.-X. et al. (2019). CFD simulations of urban street canyon trees in urban boundary layer. *Urban Climate* 29, 100494.
- Morakinyo, T.E. & Lam, Y.F. (2016). Simulation study on the impact of tree-configuration on pedestrian thermal comfort and energy use. *Building and Environment* 103, 65–76.
- Speak, A.F. et al. (2012). Urban particulate pollution reduction by four species of green roof vegetation. *Atmospheric Environment* 61, 283–293.
- USFS Northern Research Station. (NRS-117). Urban Tree Growth and Carbon Storage.
- EPA (2023). *BenMAP-CE User Manual*. Environmental Benefits Mapping and Analysis Program.
- NYC Admin Code §24-163: Idling of motor vehicle engines. Local Law 58 of 2018 (Citizens Air Complaint Program).
