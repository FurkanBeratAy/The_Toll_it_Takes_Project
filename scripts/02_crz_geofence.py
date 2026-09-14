"""
Convert the CRZ geofence WKT CSV → GeoJSON for the frontend map.
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from config import RAW_DIR, PROCESSED_DIR

import pandas as pd
from shapely import wkt


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    # The raw file has a single column 'polygon' with WKT
    df = pd.read_csv(RAW_DIR / "MTA_Central_Business_District_Geofence__Beginning_June_2024_20260905.csv")

    # Parse WKT → shapely → GeoJSON
    features = []
    for i, row in df.iterrows():
        geom = wkt.loads(row["polygon"])
        features.append({
            "type": "Feature",
            "properties": {"id": i, "label": "CRZ Boundary" if i == 0 else "CRZ Inner"},
            "geometry": geom.__geo_interface__,
        })

    fc = {"type": "FeatureCollection", "features": features}
    out = PROCESSED_DIR / "crz_boundary.geojson"
    out.write_text(json.dumps(fc, indent=2))
    print(f"Saved {out} ({len(features)} polygons).")


if __name__ == "__main__":
    main()
