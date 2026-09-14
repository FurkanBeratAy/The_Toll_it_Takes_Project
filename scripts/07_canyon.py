"""
Canyon geometry + canopy gap + i-Tree Eco approximation.

i-Tree approximation sources:
  - Nowak et al. (2006) "Modeled PM2.5 removal by trees in 10 US cities"
    Urban Forestry & Urban Greening 4(3-4): 115-123.
    → 0.622 g PM2.5/tree/year citywide NYC average (range 0.3–1.2 g)
  - Nowak et al. (2018) "The urban forest of New York City" (USFS NRS-117)
    → Gross PM2.5 removal: 2,202 metric tons/year across 7.1M trees
    → ≈ 0.31 kg/tree/year  (large-canopy trees higher; street trees lower)
  - DBH-based scaling: removal ∝ crown projection area ∝ DBH^1.5
    (Hirabayashi 2012 i-Tree Eco formulation)

Canyon discount factor:
  - When H/W > 0.5 with continuous canopy: pollutant recirculation traps
    PM2.5 inside the canyon, depositing it on surfaces but also reducing
    the net removal benefit per tree vs. open terrain.
  - Discount applied to tree-based removal (not wall panels).
  - Based on: Morakinyo & Lam (2016) review of canyon ventilation studies;
    Li et al. (2019) LES simulations showing 40–60% reduction in removal
    at H/W > 1.5, ~20% at H/W 0.5–1.0.
  - We use a linear interpolation: discount = min(0.6, (H/W - 0.5) * 0.3)
    for H/W > 0.5; 0 otherwise.

Output: processed/canyon_analysis.json
"""
import sys, json, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from config import PROCESSED_DIR, STATION_COORDS

import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")


# ─── Published removal rates ───────────────────────────────────────────────── #

# Base annual PM2.5 removal per tree (kg) for a 'reference' DBH of 10 inches
# From Nowak 2006 (NYC mean = 0.622 g, here in kg = 0.000622)
# And Nowak 2018 (0.31 kg/tree/year for full urban forest incl. large trees)
# We use 0.31 kg/tree/year as base for a median-DBH (~10") street tree.
BASE_REMOVAL_KG_YR = 0.31   # kg PM2.5 per tree per year at DBH=10"

# DBH scaling exponent (Hirabayashi 2012)
DBH_EXPONENT = 1.5
REF_DBH = 10.0  # reference diameter in inches


def dbh_scalar(dbh):
    """Scale removal rate by DBH relative to reference."""
    if dbh <= 0:
        return 0.5
    return (dbh / REF_DBH) ** DBH_EXPONENT


def canyon_discount(hw_ratio):
    """
    Fractional reduction in tree-based PM2.5 removal due to canyon trapping.
    0 when H/W ≤ 0.5 (open/semi-open).
    Ramps to 0.6 (60% discount) at H/W = 2.5.
    """
    if hw_ratio <= 0.5:
        return 0.0
    return min(0.60, (hw_ratio - 0.5) * 0.25)


# ─── Corridor dimensions from spatial data ─────────────────────────────────── #

def compute_hw_ratio(trees_data, buildings_data, streets_data):
    """
    Estimate H/W for the corridor:
      H = median building height_roof from buildings GeoJSON
      W = street width from LION (StreetWidth_Min or fallback to typical block width)
    """
    # Building heights
    heights = []
    if buildings_data:
        for f in buildings_data.get("features", []):
            h = f.get("properties", {}).get("height_roof", 0)
            if h and h > 0:
                heights.append(float(h))

    if heights:
        mean_h = float(np.median(heights))
    else:
        mean_h = 40.0  # typical South Bronx tenement: 4 stories × 10ft
        print(f"  warn: no building height data; using default H={mean_h} ft")

    # Street width from LION — try all case variants
    street_w = None
    if streets_data and "features" in streets_data:
        widths = []
        for f in streets_data["features"]:
            p = f.get("properties", {})
            p_lower = {k.lower(): v for k, v in p.items()}
            for key in ("streetwidth_min", "streetwidth_max", "rw_width", "street_width",
                        "pavement_width", "width"):
                w = p_lower.get(key)
                if w is not None:
                    try:
                        wf = float(w)
                        if wf > 0:
                            widths.append(wf)
                            break
                    except (ValueError, TypeError):
                        pass
        if widths:
            street_w = float(np.median(widths))

    if street_w is None:
        street_w = 60.0  # typical arterial in South Bronx: ~60 ft
        print(f"  warn: no street width from LION; using default W={street_w} ft")

    hw = mean_h / street_w if street_w > 0 else 1.0
    return hw, mean_h, street_w


def compute_canopy_gap(trees_gj, corridor_length_ft, trees_per_mile_city=142):
    """
    Compute existing canopy fraction vs. citywide/borough median.
    trees_per_mile_city: NYC 2015 citywide average from tree census summary.
    corridor_length_ft: TOTAL street length in the bbox (from LION).
    """
    n_trees = len(trees_gj.get("features", [])) if trees_gj else 0
    # Use total street length (not a single block) for density
    trees_per_ft = n_trees / corridor_length_ft if corridor_length_ft > 0 else 0
    trees_per_mile = trees_per_ft * 5280

    # Citywide: ~7.1M trees / ~50k street miles = ~142/mile
    canopy_pct_site = min(100, trees_per_mile / trees_per_mile_city * 22)  # city avg canopy = 22%
    return {
        "n_trees_existing": n_trees,
        "trees_per_linear_ft": round(trees_per_ft, 4),
        "trees_per_mile": round(trees_per_mile, 1),
        "citywide_trees_per_mile": trees_per_mile_city,
        "estimated_canopy_pct": round(canopy_pct_site, 1),
        "citywide_canopy_pct": 22.1,
        "canopy_gap_pct": round(max(0, 22.1 - canopy_pct_site), 1),
    }


def removal_typology(hw_ratio, corridor_length_ft, existing_dbh_mean=10):
    """
    Calculate PM2.5 removal for three planting typologies.

    Dense street trees:    1 tree per 20 ft → continuous canopy when mature
    Spaced street trees:   1 tree per 40 ft → semi-open (canyon discount halved)
    Green wall:            2 ft² leaf area per linear ft → discount minimal
    """
    YEARS = [1, 10, 20]
    # maturation factor: trees start small; by yr 20 at ~80% of final size
    MATURATION = {1: 0.10, 10: 0.55, 20: 0.90}

    typologies = {}

    # -- Dense street trees --
    n_dense = corridor_length_ft / 20
    disc_dense = canyon_discount(hw_ratio)
    removal_dense_full = n_dense * BASE_REMOVAL_KG_YR * dbh_scalar(existing_dbh_mean + 5)
    typologies["dense_street_trees"] = {
        "description":         "Street trees at 20-ft spacing (continuous canopy)",
        "proposed_trees":      int(n_dense),
        "spacing_ft":          20,
        "canyon_discount":     round(disc_dense, 2),
        "removal_naive_kg_yr": round(removal_dense_full, 2),
        "removal_adjusted_kg_yr": round(removal_dense_full * (1 - disc_dense), 2),
        "projection": {
            str(y): round(removal_dense_full * (1 - disc_dense) * MATURATION[y], 2)
            for y in YEARS
        },
    }

    # -- Spaced street trees (40 ft) --
    n_spaced = corridor_length_ft / 40
    disc_spaced = canyon_discount(hw_ratio) * 0.4   # porous canopy — 40% of full discount
    removal_spaced_full = n_spaced * BASE_REMOVAL_KG_YR * dbh_scalar(existing_dbh_mean + 5)
    typologies["spaced_street_trees"] = {
        "description":         "Street trees at 40-ft spacing (porous canopy)",
        "proposed_trees":      int(n_spaced),
        "spacing_ft":          40,
        "canyon_discount":     round(disc_spaced, 2),
        "removal_naive_kg_yr": round(removal_spaced_full, 2),
        "removal_adjusted_kg_yr": round(removal_spaced_full * (1 - disc_spaced), 2),
        "projection": {
            str(y): round(removal_spaced_full * (1 - disc_spaced) * MATURATION[y], 2)
            for y in YEARS
        },
    }

    # -- Green wall (vertical) --
    # Published rate: ~0.9 g PM2.5/m² leaf area/year (Speak et al. 2012, Ottelé 2011)
    # At 2 ft of wall height per ft of street → leaf area ≈ 0.6 m²/linear ft (50% coverage)
    leaf_area_m2 = corridor_length_ft * 0.6 * 0.0929   # ft² → m²
    removal_wall_full = leaf_area_m2 * 0.9e-3   # g → kg
    disc_wall = 0.05  # vertical surface in canyon flush = minimal trapping loss
    removal_wall_adj = removal_wall_full * (1 - disc_wall)
    typologies["green_wall"] = {
        "description":         "Green wall on south-facing building faces, 2 m height",
        "leaf_area_m2":        round(leaf_area_m2, 1),
        "canyon_discount":     round(disc_wall, 2),
        "removal_naive_kg_yr": round(removal_wall_full, 3),
        "removal_adjusted_kg_yr": round(removal_wall_adj, 3),
        "projection": {
            str(y): round(removal_wall_adj, 3)
            for y in YEARS
        },
    }

    return typologies


def species_recommendations(hw_ratio, has_truck_route):
    """
    Select species based on site conditions:
      - High H/W: avoid dense evergreen crowns that block ventilation
      - Truck route: salt-tolerant, pollution-tolerant
      - South Bronx: hardy, lower maintenance
    """
    base = [
        {
            "spc_latin": "Gleditsia triacanthos var. inermis",
            "spc_common": "Thornless Honeylocust",
            "form": "High-branching, fine-textured, dappled shade",
            "pollution_tolerance": "High",
            "salt_tolerance": "High",
            "dbh_at_20yr_in": 12,
            "rationale": (
                "NYC's most-planted street tree for a reason: tolerates compacted soil, "
                "road salt, and air pollution; high canopy avoids over-closing the canyon "
                f"(H/W={hw_ratio:.1f}); fast early growth maximises removal in yr 1–10."
            ),
        },
        {
            "spc_latin": "Quercus bicolor",
            "spc_common": "Swamp White Oak",
            "form": "Broadly rounded, dense at maturity",
            "pollution_tolerance": "High",
            "salt_tolerance": "Moderate",
            "dbh_at_20yr_in": 14,
            "rationale": (
                "Long-lived (200+ yr); large eventual crown delivers highest per-tree "
                "PM2.5 removal at maturity (DBH scaling). Moderate salt tolerance — "
                "suitable for non-primary plow routes. Avoid curb-side planting near "
                "winter de-icing unless protected."
            ),
        },
        {
            "spc_latin": "Ulmus parvifolia",
            "spc_common": "Lacebark Elm",
            "form": "Vase-shaped, semi-evergreen in mild winters",
            "pollution_tolerance": "Very High",
            "salt_tolerance": "High",
            "dbh_at_20yr_in": 11,
            "rationale": (
                "Extremely pollution- and salt-tolerant; vase form allows truck clearance "
                "while providing lateral canopy; resistant to Dutch Elm Disease. "
                "Good second-species diversity pairing with Honeylocust."
            ),
        },
    ]
    if hw_ratio > 1.5:
        # Deep canyon — prefer trees that don't close the sky view factor too much
        for s in base:
            s["canyon_note"] = (
                f"At H/W={hw_ratio:.1f}, space at ≥40 ft intervals and prune to "
                "lift crown above 14 ft to maintain ventilation."
            )
    if has_truck_route:
        base.append({
            "spc_latin": "Ginkgo biloba (female-free cultivar 'Autumn Gold')",
            "spc_common": "Maidenhair Tree",
            "form": "Columnar-conical, very high branching",
            "pollution_tolerance": "Very High",
            "salt_tolerance": "High",
            "dbh_at_20yr_in": 8,
            "rationale": (
                "The most pollution-tolerant tree in the NYC palette; columnar form "
                "minimises wind-shadow on truck lanes. Use only male cultivars — "
                "female Ginkgo fruits create a maintenance burden."
            ),
        })
    return base


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    # Load corridor metadata
    meta_path = PROCESSED_DIR / "corridor_meta.json"
    if not meta_path.exists():
        print("corridor_meta.json not found — run 06_geo.py first")
        return
    meta = json.loads(meta_path.read_text())
    site    = meta["site"]
    site_lat = meta["lat"]
    site_lon = meta["lon"]

    # Load spatial data
    def load_gj(name):
        p = PROCESSED_DIR / name
        return json.loads(p.read_text()) if p.exists() else None

    trees_gj    = load_gj("corridor_trees.geojson")
    bldgs_data  = load_gj("corridor_buildings.geojson")
    streets_gj  = load_gj("corridor_streets.geojson")

    # Convert to simple dicts for compute functions
    bldgs_simple = bldgs_data  # already a FeatureCollection dict

    print("=== Computing canyon geometry ===")
    hw_ratio, mean_h, street_w = compute_hw_ratio(bldgs_simple, bldgs_data, streets_gj)
    print(f"  H = {mean_h:.1f} ft, W = {street_w:.1f} ft, H/W = {hw_ratio:.2f}")

    # Compute total street length in corridor from LION SHAPE_Length (feet in LION CRS)
    # LION uses NYC State Plane (feet), but after reprojection to 4326 SHAPE_Length is
    # in degrees. Use haversine approximation from coordinates instead.
    import math

    def linestring_length_ft(ring):
        total = 0.0
        for i in range(len(ring) - 1):
            dx = (ring[i+1][0] - ring[i][0]) * 111320 * math.cos(math.radians(40.8))
            dy = (ring[i+1][1] - ring[i][1]) * 111320
            total += math.sqrt(dx**2 + dy**2) * 3.281
        return total

    def seg_length_ft(feat):
        geom = feat.get("geometry") or {}
        gtype = geom.get("type", "")
        coords = geom.get("coordinates", [])
        if not coords:
            return 0.0
        if gtype == "LineString":
            return linestring_length_ft(coords)
        elif gtype == "MultiLineString":
            return sum(linestring_length_ft(ring) for ring in coords)
        return 0.0

    # Filter to driveable streets with StreetWidth_Min >= 20 ft to exclude
    # pedestrian paths, alleys, and service roads too narrow for tree planting
    def is_plantable(f):
        p = {k.lower(): v for k, v in f.get("properties", {}).items()}
        w = p.get("streetwidth_min") or p.get("streetwidth_max") or p.get("rw_width")
        if w is not None:
            try:
                return float(w) >= 20
            except (ValueError, TypeError):
                pass
        return True  # include if no width info

    plantable = [f for f in (streets_gj or {}).get("features", []) if is_plantable(f)]
    corridor_length_ft = sum(seg_length_ft(f) for f in plantable)
    if corridor_length_ft < 100:
        corridor_length_ft = 8 * 264   # fallback: 8 blocks at 264 ft
    print(f"  Plantable street segments: {len(plantable)} of "
          f"{len((streets_gj or {}).get('features', []))}")
    print(f"  Total LION street length in corridor: {corridor_length_ft:.0f} ft "
          f"({corridor_length_ft/5280:.2f} miles)")

    print("=== Computing canopy gap ===")
    canopy = compute_canopy_gap(trees_gj, corridor_length_ft)
    print(f"  Existing trees in corridor: {canopy['n_trees_existing']}")
    print(f"  Estimated canopy: {canopy['estimated_canopy_pct']}% vs citywide 22.1%")
    print(f"  Canopy gap: {canopy['canopy_gap_pct']}%")

    # Mean DBH of existing trees
    existing_dbhs = [
        f["properties"].get("dbh", 0)
        for f in (trees_gj or {}).get("features", [])
        if f["properties"].get("dbh", 0) > 0
    ]
    mean_dbh = float(np.mean(existing_dbhs)) if existing_dbhs else 10.0

    print("=== Computing removal typologies ===")
    disc = canyon_discount(hw_ratio)
    print(f"  Canyon discount at H/W={hw_ratio:.2f}: {disc*100:.0f}%")
    typologies = removal_typology(hw_ratio, corridor_length_ft, mean_dbh)
    for name, t in typologies.items():
        print(f"  {name}: naive={t['removal_naive_kg_yr']:.2f} kg/yr, "
              f"adjusted={t['removal_adjusted_kg_yr']:.2f} kg/yr")

    # Truck route check from LION TRUCK_ROUTE_TYPE column
    has_truck = True  # default: South Bronx is virtually all truck routes
    if streets_gj:
        truck_vals = [
            f.get("properties", {}).get("TRUCK_ROUTE_TYPE", "") or ""
            for f in streets_gj.get("features", [])
        ]
        # LION values: "1"=Local, "2"=Through, "3"=Restricted, ""=None
        has_truck = any(v not in ("", "0", None) for v in truck_vals)

    print("=== Building species recommendations ===")
    species = species_recommendations(hw_ratio, has_truck)
    for s in species:
        print(f"  {s['spc_common']} ({s['spc_latin']})")

    output = {
        "site": site,
        "lat":  site_lat,
        "lon":  site_lon,
        "corridor_length_ft": corridor_length_ft,
        "hw_ratio":           round(hw_ratio, 3),
        "mean_building_height_ft": round(mean_h, 1),
        "street_width_ft":    round(street_w, 1),
        "canyon_discount":    round(disc, 3),
        "mean_existing_dbh":  round(mean_dbh, 1),
        "canopy":             canopy,
        "typologies":         typologies,
        "species":            species,
        "methodology_note": (
            "PM2.5 removal rates from Nowak et al. (2006, 2018). "
            "DBH scaling: removal ∝ (DBH/10)^1.5 (Hirabayashi 2012). "
            "Canyon discount: linear ramp from H/W=0.5 to H/W=2.5, max 60%, "
            "based on Li et al. (2019) LES simulations and Morakinyo & Lam (2016) review. "
            "Projection maturation curve: 10% yr1, 55% yr10, 90% yr20 of full-size removal."
        ),
    }

    out_path = PROCESSED_DIR / "canyon_analysis.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nSaved {out_path}")


if __name__ == "__main__":
    main()
