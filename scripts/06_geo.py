"""
Process geospatial data for both Part 1 and Part 2.

Part 1 outputs:
  processed/dac_tracts_nyc.geojson   — EJ/DAC tract polygons
  processed/monitor_stations.geojson — NYCCAS station points with ITS results

Part 2 outputs:
  processed/corridor_streets.geojson  — LION segments in corridor bbox
  processed/corridor_trees.geojson    — Street trees in corridor bbox
  processed/corridor_buildings.geojson— Building footprints in corridor bbox

Updates: processed/its_results.json with true EJ designations from DAC data.
"""
import sys, json, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from config import RAW_DIR, PROCESSED_DIR, STATION_COORDS, TREATMENT_SITES

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, box
import warnings
warnings.filterwarnings("ignore")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


# ─── DAC tracts ────────────────────────────────────────────────────────────── #

def process_dac():
    src = RAW_DIR / "dac_ny_state.json"
    if not src.exists():
        print("  dac_ny_state.json not found — run 01_fetch.py first")
        return None

    records = json.loads(src.read_text())
    features = []
    for r in records:
        geom = r.get("the_geom")
        if not geom:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "geoid":           r.get("geoid", ""),
                "county":          r.get("county", ""),
                "dac_designation": r.get("dac_designation", "N"),
                "burden_pct":      float(r.get("burden_score_percentile", 0) or 0),
                "vuln_pct":        float(r.get("vulnerability_score_percentile", 0) or 0),
                "combined_score":  float(r.get("combined_score", 0) or 0),
            },
            "geometry": geom,
        })

    fc = {"type": "FeatureCollection", "features": features}
    out = PROCESSED_DIR / "dac_tracts_nyc.geojson"
    out.write_text(json.dumps(fc, indent=2))
    print(f"  DAC tracts: {len(features)} features → {out.name}")
    return gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")


def assign_ej_to_stations(dac_gdf):
    """Return dict: site_name → bool (True if in DAC-designated tract)."""
    if dac_gdf is None:
        return {}
    dac_designated = dac_gdf[dac_gdf["dac_designation"] == "Designated as DAC"].copy()

    result = {}
    for name, (lat, lon) in STATION_COORDS.items():
        pt = Point(lon, lat)
        in_ej = dac_designated.geometry.contains(pt).any()
        result[name] = bool(in_ej)
        print(f"  {name}: EJ={in_ej}")
    return result


# ─── Monitor station GeoJSON ───────────────────────────────────────────────── #

def build_station_geojson(its_results, ej_lookup):
    features = []
    for site, res in its_results.get("sites", {}).items():
        lat, lon = res["lat"], res["lon"]
        spec = res.get("full") or res.get("long")
        props = {
            "name":         site,
            "ej_designated": ej_lookup.get(site, res.get("ej_designated", False)),
            "lat": lat, "lon": lon,
        }
        if spec:
            props.update({
                "beta_post":  spec["beta_post"],
                "p_value":    spec["beta_post_p"],
                "significant": spec["significant"],
                "direction":   spec["direction"],
                "pre_mean":    spec["pre_mean"],
                "post_mean":   spec["post_mean"],
                "label":       spec["label"],
            })
        features.append({
            "type": "Feature",
            "properties": props,
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
        })
    fc = {"type": "FeatureCollection", "features": features}
    out = PROCESSED_DIR / "monitor_stations.geojson"
    out.write_text(json.dumps(fc, indent=2))
    print(f"  Monitor stations GeoJSON: {len(features)} stations → {out.name}")


# ─── Corridor bbox from worst site ─────────────────────────────────────────── #

def get_corridor_bbox(its_results):
    site = its_results.get("headline", {}).get("part2_site")
    if not site or site not in STATION_COORDS:
        site = "Cross_Bronx_Expy"
    lat, lon = STATION_COORDS[site]
    # ~800m buffer in degrees
    buf = 0.008
    return site, {
        "min_lon": lon - buf, "max_lon": lon + buf,
        "min_lat": lat - buf, "max_lat": lat + buf,
    }


# ─── Monitor-to-expressway and monitor-to-CRZ distances ───────────────────── #

def compute_mott_haven_distances():
    """Return {dist_deegan_m, dist_bruckner_m, dist_crz_m} in integer metres.

    Uses Haversine nearest-vertex on LION mainline segments so the figures
    reproduce the values cited in the boulevard section of part1.html:
    44 m (Deegan), 633 m (Bruckner), 6079 m (CRZ).
    """
    lat0, lon0 = STATION_COORDS['Mott_Haven']

    def hav(lat1, lon1, lat2, lon2):
        R = 6371008.8
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        a = (math.sin(math.radians(lat2-lat1)/2)**2
             + math.cos(phi1)*math.cos(phi2)*math.sin(math.radians(lon2-lon1)/2)**2)
        return 2*R*math.atan2(math.sqrt(a), math.sqrt(1-a))

    result = {}

    streets_path = PROCESSED_DIR / 'corridor_streets.geojson'
    if streets_path.exists():
        feats = json.loads(streets_path.read_text())['features']
        for key, name in (('dist_deegan_m', 'MAJOR DEEGAN EXPRESSWAY'),
                          ('dist_bruckner_m', 'BRUCKNER EXPRESSWAY')):
            matched = [f for f in feats
                       if f['properties'].get('Street', '').upper() == name]
            if matched:
                d = min(hav(lat0, lon0, cy, cx)
                        for f in matched
                        for ring in f['geometry']['coordinates']
                        for cx, cy in ring)
                result[key] = int(d)

    crz_path = PROCESSED_DIR / 'crz_boundary.geojson'
    if crz_path.exists():
        pts = []
        for f in json.loads(crz_path.read_text())['features']:
            g = f['geometry']
            rings = (g['coordinates'] if g['type'] == 'Polygon'
                     else [r for poly in g['coordinates'] for r in poly])
            for ring in rings:
                pts.extend(ring)
        if pts:
            result['dist_crz_m'] = int(min(hav(lat0, lon0, cy, cx) for cx, cy in pts))

    return result


# ─── LION street segments ──────────────────────────────────────────────────── #

def process_lion(bbox):
    lion_zip = RAW_DIR / "nyclion.zip"
    if not lion_zip.exists():
        print("  nyclion.zip not found")
        return None

    import zipfile, tempfile, shutil
    tmpdir = Path(tempfile.mkdtemp())
    try:
        with zipfile.ZipFile(lion_zip) as zf:
            zf.extractall(tmpdir)

        gdb_path = tmpdir / "lion" / "lion.gdb"
        if not gdb_path.exists():
            # Some extractions land differently
            gdbs = list(tmpdir.rglob("*.gdb"))
            gdb_path = gdbs[0] if gdbs else None

        if gdb_path is None:
            print("  Could not locate lion.gdb")
            return None

        print(f"  Reading LION GDB from {gdb_path}")
        import pyogrio
        layer_info = pyogrio.list_layers(str(gdb_path))
        layers = [info[0] for info in layer_info]
        print(f"  LION layers: {layers}")
        # Prefer the 'lion' layer (street centerlines); fall back to last layer
        lion_layer = "lion" if "lion" in layers else layers[-1]

        lion = gpd.read_file(str(gdb_path), layer=lion_layer, engine="pyogrio")
        lion = lion.to_crs("EPSG:4326")

        # Clip to corridor bbox
        mask = box(bbox["min_lon"], bbox["min_lat"], bbox["max_lon"], bbox["max_lat"])
        lion_clip = lion[lion.geometry.intersects(mask)].copy()
        print(f"  LION clipped: {len(lion_clip)} segments")

        print(f"  LION columns: {list(lion_clip.columns)}")
        # Keep width, name, traffic, and planting-relevant columns
        keep_lower = {
            "streetwidth_min", "streetwidth_max", "rw_width", "street_width",
            "streetname", "street", "full_stree", "segmentid", "physicalid",
            "featuretyp", "nonped", "trafdir", "truck_route_type",
            "number_travel_lanes", "number_park_lanes", "snow_priority",
        }
        useful_cols = [c for c in lion_clip.columns if c.lower() in keep_lower]
        if not useful_cols:
            useful_cols = [c for c in lion_clip.columns if c != "geometry"][:12]
        lion_clip = lion_clip[useful_cols + ["geometry"]]

        out = PROCESSED_DIR / "corridor_streets.geojson"
        lion_clip.to_file(str(out), driver="GeoJSON")
        print(f"  Saved corridor_streets.geojson")
        return lion_clip
    except Exception as e:
        print(f"  LION error: {e}")
        return None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ─── Street trees ──────────────────────────────────────────────────────────── #

def process_trees(bbox):
    src = RAW_DIR / "2015_Street_Tree_Census_-_Tree_Data_20260905.csv"
    if not src.exists():
        print("  Street tree CSV not found")
        return None

    print("  Reading Street Tree Census (271 MB, filtering to corridor)…")
    chunks = []
    usecols = [
        "tree_id", "tree_dbh", "status", "health",
        "spc_latin", "spc_common", "latitude", "longitude",
        "borough", "nta", "census tract",
    ]
    for chunk in pd.read_csv(src, usecols=usecols, chunksize=100_000, low_memory=False):
        chunk = chunk[
            (chunk["latitude"].between(bbox["min_lat"], bbox["max_lat"])) &
            (chunk["longitude"].between(bbox["min_lon"], bbox["max_lon"]))
        ]
        if len(chunk):
            chunks.append(chunk)

    if not chunks:
        print("  No trees in corridor bbox")
        return None

    df = pd.concat(chunks)
    df = df[df["status"] == "Alive"].copy()
    print(f"  Trees in corridor: {len(df)}")

    features = []
    for _, row in df.iterrows():
        if pd.isna(row["latitude"]) or pd.isna(row["longitude"]):
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "tree_id":    int(row["tree_id"]),
                "dbh":        float(row["tree_dbh"]) if pd.notna(row["tree_dbh"]) else 0,
                "health":     str(row["health"]) if pd.notna(row["health"]) else "Unknown",
                "species":    str(row["spc_common"]) if pd.notna(row["spc_common"]) else "Unknown",
                "spc_latin":  str(row["spc_latin"]) if pd.notna(row["spc_latin"]) else "",
                "borough":    str(row["borough"]) if pd.notna(row["borough"]) else "",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [round(float(row["longitude"]), 6),
                                round(float(row["latitude"]), 6)],
            },
        })

    fc = {"type": "FeatureCollection", "features": features}
    out = PROCESSED_DIR / "corridor_trees.geojson"
    out.write_text(json.dumps(fc, indent=2))
    print(f"  Saved corridor_trees.geojson ({len(features)} trees)")
    return df


# ─── Building footprints ───────────────────────────────────────────────────── #

def process_buildings(bbox):
    src = RAW_DIR / "building_footprints_sbx.json"
    if not src.exists():
        print("  building_footprints_sbx.json not found — run 01_fetch.py first")
        return None

    records = json.loads(src.read_text())
    features = []
    for r in records:
        geom = r.get("the_geom")
        if not geom or not isinstance(geom, dict):
            continue
        h = r.get("height_roof")
        if h is None:
            continue
        try:
            h_ft = float(h)
        except (ValueError, TypeError):
            continue

        # Filter to corridor bbox using first exterior ring coordinate as a proxy
        try:
            coords = geom.get("coordinates", [])
            # For Polygon: coords[0] is exterior ring; for MultiPolygon: coords[0][0]
            if geom.get("type") == "MultiPolygon":
                ring = coords[0][0] if coords and coords[0] else []
            else:
                ring = coords[0] if coords else []
            if ring:
                first_pt = ring[0]
                cx, cy = float(first_pt[0]), float(first_pt[1])
                if not (bbox["min_lon"] <= cx <= bbox["max_lon"] and
                        bbox["min_lat"] <= cy <= bbox["max_lat"]):
                    continue
        except (IndexError, TypeError, ValueError):
            continue

        features.append({
            "type": "Feature",
            "properties": {
                "bin":         r.get("bin", ""),
                "height_roof": round(h_ft, 1),
                "ground_elev": float(r.get("ground_elevation", 0) or 0),
            },
            "geometry": geom,
        })

    fc = {"type": "FeatureCollection", "features": features}
    out = PROCESSED_DIR / "corridor_buildings.geojson"
    out.write_text(json.dumps(fc, indent=2))
    print(f"  Saved corridor_buildings.geojson ({len(features)} buildings)")
    return features


# ─── Main ─────────────────────────────────────────────────────────────────── #

def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    print("=== Processing DAC tracts ===")
    dac_gdf = process_dac()
    ej_lookup = assign_ej_to_stations(dac_gdf) if dac_gdf is not None else {}

    print("\n=== Loading ITS results ===")
    its_path = PROCESSED_DIR / "its_results.json"
    if not its_path.exists():
        print("  its_results.json not found — run 05_its_model.py first")
        its_results = {"sites": {}, "headline": {}}
    else:
        its_results = json.loads(its_path.read_text())

    # Update EJ designations with real spatial data and re-run equity regression
    if ej_lookup:
        for site in its_results.get("sites", {}):
            its_results["sites"][site]["ej_designated"] = ej_lookup.get(site, False)

        # Re-run equity regression with corrected EJ flags
        import statsmodels.api as sm
        rows_eq = []
        for site, res in its_results.get("sites", {}).items():
            spec = res.get("full") or res.get("long")
            if spec is None:
                continue
            beta = spec.get("beta_post")
            pre  = spec.get("pre_mean")
            if beta is None or pre is None:
                continue
            rows_eq.append({
                "site":      site,
                "beta_post": float(beta),
                "ej":        int(ej_lookup.get(site, False)),
                "pre_mean":  float(pre),
            })
        if len(rows_eq) >= 3:
            df_eq = pd.DataFrame(rows_eq).dropna()
            if len(df_eq) >= 3 and df_eq["ej"].nunique() > 1:
                df_eq["pre_mean_z"] = (df_eq["pre_mean"] - df_eq["pre_mean"].mean()) / (df_eq["pre_mean"].std() + 1e-9)
                X_eq = pd.DataFrame({"const": 1.0, "ej": df_eq["ej"].values,
                                     "pre_mean_z": df_eq["pre_mean_z"].values})
                try:
                    res_eq = sm.OLS(df_eq["beta_post"].values, X_eq).fit()
                    its_results["equity"] = {
                        "beta_ej":    round(float(res_eq.params["ej"]), 4),
                        "se_ej":      round(float(res_eq.bse["ej"]), 4),
                        "p_ej":       round(float(res_eq.pvalues["ej"]), 4),
                        "n":          int(res_eq.nobs),
                        "r2":         round(float(res_eq.rsquared), 4),
                        "sites_used": df_eq["site"].tolist(),
                        "all_sites":  [{"site": r["site"], "beta": r["beta_post"],
                                        "ej": bool(r["ej"]), "pre_mean": r["pre_mean"]}
                                       for _, r in df_eq.iterrows()],
                    }
                    print(f"  Equity regression (spatial EJ): β_EJ={its_results['equity']['beta_ej']:.4f} (p={its_results['equity']['p_ej']:.4f})")
                except Exception as e:
                    print(f"  Equity regression error: {e}")

        its_path.write_text(json.dumps(its_results, indent=2, default=str))
        print("  Updated its_results.json with spatial EJ designations")

    print("\n=== Building monitor station GeoJSON ===")
    build_station_geojson(its_results, ej_lookup)

    print("\n=== Getting Part 2 corridor bbox ===")
    site, bbox = get_corridor_bbox(its_results)
    print(f"  Corridor site: {site}")
    print(f"  Bbox: {bbox}")

    # Save bbox for use by 07_canyon.py
    (PROCESSED_DIR / "corridor_meta.json").write_text(json.dumps({
        "site": site,
        "bbox": bbox,
        "lat":  STATION_COORDS[site][0],
        "lon":  STATION_COORDS[site][1],
    }))

    print("\n=== Processing LION street segments ===")
    process_lion(bbox)

    print("\n=== Computing monitor-to-expressway distances ===")
    dists = compute_mott_haven_distances()
    if dists:
        meta = json.loads((PROCESSED_DIR / "corridor_meta.json").read_text())
        meta.update(dists)
        (PROCESSED_DIR / "corridor_meta.json").write_text(json.dumps(meta, indent=2))
        print(f"  dist_deegan_m={dists.get('dist_deegan_m')}  "
              f"dist_bruckner_m={dists.get('dist_bruckner_m')}  "
              f"dist_crz_m={dists.get('dist_crz_m')}")

    print("\n=== Processing street trees ===")
    process_trees(bbox)

    print("\n=== Processing building footprints ===")
    process_buildings(bbox)

    print("\nGeo processing complete.")


if __name__ == "__main__":
    main()
