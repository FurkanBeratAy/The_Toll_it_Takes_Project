"""
Aggregate NYCCAS hourly PM2.5 monitor data → daily means per site.
Also extracts raster point values for the spatial map.

Output: processed/pollution_daily.json
        processed/nyccas_raster_points.geojson
"""
import sys, json, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from config import RAW_DIR, PROCESSED_DIR, SITE_MAP, STATION_COORDS

import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")


def load_hourly_monitor_data():
    """Read all monthly NYCCAS CSVs and return one wide daily DataFrame."""
    hourly_dir = RAW_DIR / "nyccas_hourly"
    if not hourly_dir.exists():
        raise FileNotFoundError("Run 01_fetch.py first to download NYCCAS hourly CSVs")

    dfs = []
    for fpath in sorted(hourly_dir.glob("*.csv")):
        try:
            df = pd.read_csv(fpath, usecols=["SiteID", "ObservationTimeUTC", "Value"])
            dfs.append(df)
        except Exception as e:
            print(f"  warn: {fpath.name}: {e}")

    if not dfs:
        raise RuntimeError("No NYCCAS hourly CSVs found in data/raw/nyccas_hourly/")

    full = pd.concat(dfs, ignore_index=True)
    full["ObservationTimeUTC"] = pd.to_datetime(full["ObservationTimeUTC"], errors="coerce")
    full = full.dropna(subset=["ObservationTimeUTC", "Value"])

    # Map SiteID → friendly name
    full["site"] = full["SiteID"].map(SITE_MAP)
    full = full[full["site"].notna()]

    # Remove physically implausible values
    full = full[(full["Value"] >= 0) & (full["Value"] < 200)]

    print(f"  Loaded {len(full):,} hourly observations, sites: {sorted(full['site'].unique())}")
    return full


def to_daily(full):
    """Aggregate hourly → daily mean, require ≥ 18 valid hours."""
    full["date"] = full["ObservationTimeUTC"].dt.date

    agg = (
        full.groupby(["date", "site"])["Value"]
        .agg(mean="mean", count="count")
        .reset_index()
    )
    # Only keep days with ≥ 18 hourly readings (75% coverage)
    agg = agg[agg["count"] >= 18].drop(columns="count")

    wide = agg.pivot(index="date", columns="site", values="mean")
    wide.index = pd.to_datetime(wide.index)
    wide = wide.sort_index()
    return wide


def extract_raster_points():
    """
    Extract PM2.5 values from NYCCAS annual rasters (aa15, aa16)
    at a regular grid of ~2000 sample points over NYC.

    Uses rasterio to read the ESRI Grid .adf files from the zip archive.
    """
    try:
        import rasterio
        from rasterio.crs import CRS
        from pyproj import Transformer
    except ImportError:
        print("  rasterio not available; skipping raster extraction")
        return None

    zip_path = RAW_DIR / "AnnAvg_1_16_300m.zip"
    # aa15 = Dec 2022–Dec 2023 (pre-toll baseline)
    # aa16 = Dec 2023–Dec 2024 (nearest to toll launch)
    rasters_to_extract = {
        "pm25_aa15": "AnnAvg_1_15_300m/aa15_pm300m/w001001.adf",
        "pm25_aa16": "aa16_pm300m/w001001.adf",
        "no2_aa15":  "AnnAvg_1_15_300m/aa15_no2300m/w001001.adf",
        "no2_aa16":  "aa16_no2300m/w001001.adf",
    }

    import tempfile, os, shutil
    tmpdir = Path(tempfile.mkdtemp())
    results = {}

    try:
        with zipfile.ZipFile(zip_path) as zf:
            # Extract the four grid folders we need
            for key, inner_path in rasters_to_extract.items():
                folder = inner_path.split("/w001001.adf")[0]
                # Extract all files for this grid folder
                members = [m for m in zf.namelist()
                           if m.startswith(folder) and not m.endswith("/")]
                for member in members:
                    # Compute path relative to the folder itself (strip leading dir)
                    parts = Path(member).parts
                    # Find where the grid folder name appears and strip everything before it
                    folder_name = folder.split("/")[-1]  # e.g. "aa15_pm300m"
                    try:
                        idx = parts.index(folder_name)
                    except ValueError:
                        idx = 0
                    rel = Path(*parts[idx:])
                    dest = tmpdir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(zf.read(member))

                # rasterio path to the .adf
                local_adf = tmpdir / Path(inner_path.split("/", 1)[-1] if "/" in inner_path else inner_path)
                if not local_adf.exists():
                    # Try alternate path structure
                    local_adf = tmpdir / inner_path.lstrip("/")

                # Search for the .adf file under tmpdir
                adf_candidates = list(tmpdir.rglob("w001001.adf"))
                local_adf = None
                for c in adf_candidates:
                    if folder_name in str(c):
                        local_adf = c
                        break
                if local_adf is None and adf_candidates:
                    local_adf = adf_candidates[-1]  # fallback

                try:
                    with rasterio.open(str(local_adf)) as src:
                        data = src.read(1).astype(float)
                        nodata = src.nodata
                        transform = src.transform
                        crs = src.crs
                        results[key] = (data, nodata, transform, crs)
                    print(f"  Raster loaded: {key}, shape={data.shape}")
                    # Remove used .adf to avoid collision in next iteration
                    for f in local_adf.parent.iterdir():
                        f.unlink(missing_ok=True)
                except Exception as e:
                    print(f"  warn raster {key}: {e}")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    if len(results) < 2:
        return None

    # Get the first valid raster's grid to establish sample points
    ref_key = next(iter(results))
    data_ref, nodata_ref, transform_ref, crs_ref = results[ref_key]

    # Transformer from raster CRS → WGS84
    try:
        transformer = Transformer.from_crs(crs_ref, "EPSG:4326", always_xy=True)
    except Exception as e:
        print(f"  CRS transform error: {e}")
        return None

    rows, cols = np.where(
        (data_ref != nodata_ref) & np.isfinite(data_ref) & (data_ref > 0)
    )
    print(f"  Valid raster cells: {len(rows)}")

    # Sample every 3rd cell to keep GeoJSON manageable (~10k–30k points)
    step = max(1, len(rows) // 15000)
    rows, cols = rows[::step], cols[::step]

    features = []
    pm15, _nd15, tf15, _ = results.get("pm25_aa15", (None, None, None, None))
    pm16, _nd16, tf16, _ = results.get("pm25_aa16", (None, None, None, None))

    for r, c in zip(rows, cols):
        # Pixel center in raster CRS
        x = transform_ref.c + (c + 0.5) * transform_ref.a
        y = transform_ref.f + (r + 0.5) * transform_ref.e
        lon, lat = transformer.transform(x, y)

        # Bounds check: NYC rough bbox
        if not (-74.3 < lon < -73.6 and 40.4 < lat < 40.95):
            continue

        props = {"lat": round(lat, 5), "lon": round(lon, 5)}
        if pm15 is not None and 0 <= r < pm15.shape[0] and 0 <= c < pm15.shape[1]:
            v15 = float(pm15[r, c])
            if v15 != _nd15 and np.isfinite(v15) and v15 > 0:
                props["pm25_aa15"] = round(v15, 3)
        if pm16 is not None and 0 <= r < pm16.shape[0] and 0 <= c < pm16.shape[1]:
            v16 = float(pm16[r, c])
            if v16 != _nd16 and np.isfinite(v16) and v16 > 0:
                props["pm25_aa16"] = round(v16, 3)

        if "pm25_aa15" in props and "pm25_aa16" in props:
            props["pm25_delta"] = round(props["pm25_aa16"] - props["pm25_aa15"], 3)

        if "pm25_aa16" in props:
            features.append({
                "type": "Feature",
                "properties": props,
                "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
            })

    print(f"  Raster GeoJSON: {len(features)} points")
    return {"type": "FeatureCollection", "features": features}


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    print("=== Loading NYCCAS hourly data ===")
    full = load_hourly_monitor_data()

    print("=== Aggregating to daily ===")
    wide = to_daily(full)
    print(f"  Daily wide: {wide.shape}, {wide.index.min()} – {wide.index.max()}")

    # Convert to JSON-serialisable dict
    out = {
        "dates": wide.index.strftime("%Y-%m-%d").tolist(),
        "sites": {
            col: [round(v, 4) if not np.isnan(v) else None
                  for v in wide[col].tolist()]
            for col in wide.columns
        },
        "station_coords": STATION_COORDS,
    }
    (PROCESSED_DIR / "pollution_daily.json").write_text(json.dumps(out, indent=2))
    print(f"  Saved pollution_daily.json ({len(out['dates'])} days)")

    print("=== Extracting raster point values ===")
    raster_fc = extract_raster_points()
    if raster_fc:
        (PROCESSED_DIR / "nyccas_raster_points.geojson").write_text(
            json.dumps(raster_fc)
        )
        print(f"  Saved nyccas_raster_points.geojson")
    else:
        print("  Raster extraction skipped (rasterio unavailable or grid mismatch)")


if __name__ == "__main__":
    main()
