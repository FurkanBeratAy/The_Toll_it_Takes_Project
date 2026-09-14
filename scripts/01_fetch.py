"""
Fetch missing data from remote sources:
  - NYCCAS hourly PM2.5 CSVs (2019-2026, GitHub hist/csv)
  - NY State DAC tract designations (Socrata)
  - NYC Building Footprints for South Bronx bbox (Socrata)
"""
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from config import RAW_DIR, PROCESSED_DIR

import requests

NYCCAS_BASE = "https://raw.githubusercontent.com/nychealth/nyccas-data/refs/heads/main/hist/csv"
DAC_URL     = "https://data.ny.gov/resource/2e6c-s6fp.json"
BF_URL      = "https://data.cityofnewyork.us/resource/5zhs-2jue.json"

# South Bronx bounding box (generous — covers all CBDTP diversion routes)
SBX_BBOX = dict(min_lon=-73.945, max_lon=-73.870, min_lat=40.795, max_lat=40.870)


def fetch_nyccas_hourly():
    out = RAW_DIR / "nyccas_hourly"
    out.mkdir(exist_ok=True)
    session = requests.Session()
    for year in range(2019, 2027):
        for month in range(1, 13):
            fpath = out / f"{year}_{month:02d}.csv"
            if fpath.exists():
                continue
            url = f"{NYCCAS_BASE}/{year}/{month}.csv"
            r = session.get(url, timeout=30)
            if r.status_code == 200:
                fpath.write_bytes(r.content)
                print(f"  saved {year}/{month:02d} ({len(r.content)//1024}KB)")
            else:
                print(f"  skip  {year}/{month:02d} (HTTP {r.status_code})")
            time.sleep(0.05)
    print("NYCCAS hourly done.")


def fetch_dac(nyc_county_fips=("005","047","061","081","085")):
    """Download all NYC census tracts with DAC designation."""
    out = RAW_DIR / "dac_ny_state.json"
    if out.exists():
        print("DAC already fetched, skip.")
        return

    # FIPS: NY State = 36, NYC counties = 005,047,061,081,085
    # Filter in Socrata by county name (the 'county' field is plain text)
    nyc_names = ("Bronx","Kings","New York","Queens","Richmond")
    limit = 5000
    records = []
    offset = 0
    session = requests.Session()
    while True:
        params = {
            "$limit": limit,
            "$offset": offset,
            "$where": "county IN ('Bronx','Kings','New York','Queens','Richmond')",
        }
        r = session.get(DAC_URL, params=params, timeout=60)
        if r.status_code != 200:
            print(f"  DAC API error: {r.status_code} {r.text[:200]}")
            break
        batch = r.json()
        records.extend(batch)
        print(f"  DAC batch offset={offset}: {len(batch)} records")
        if len(batch) < limit:
            break
        offset += limit
        time.sleep(0.1)

    out.write_text(json.dumps(records, indent=2))
    print(f"DAC done: {len(records)} tracts saved.")


def fetch_building_footprints():
    """Download building footprints for South Bronx corridor."""
    out = RAW_DIR / "building_footprints_sbx.json"
    if out.exists():
        print("Building footprints already fetched, skip.")
        return

    limit = 50000
    all_records = []
    session = requests.Session()

    # Socrata spatial filter: within_box(field, minLat, minLon, maxLat, maxLon)
    bb = SBX_BBOX
    where = (
        f"within_box(the_geom,{bb['min_lat']},{bb['min_lon']},"
        f"{bb['max_lat']},{bb['max_lon']})"
    )
    params = {
        "$limit": limit,
        "$select": "bin,height_roof,ground_elevation,the_geom",
        "$where": where,
    }
    print(f"  Fetching building footprints (South Bronx bbox)…")
    r = session.get(BF_URL, params=params, timeout=120)
    if r.status_code == 200:
        all_records = r.json()
        print(f"    {len(all_records)} records")
    else:
        print(f"    error: {r.status_code} — {r.text[:200]}")
        # Fallback: try GeoJSON endpoint
        geojson_url = "https://data.cityofnewyork.us/api/geospatial/qb5r-6dgf"
        params2 = {
            "method": "exportRecords",
            "type": "GeoJSON",
            "where": f"latitude>{bb['min_lat']} AND latitude<{bb['max_lat']} AND longitude>{bb['min_lon']} AND longitude<{bb['max_lon']}",
        }
        r2 = session.get(geojson_url, params=params2, timeout=120)
        if r2.status_code == 200:
            try:
                fc = r2.json()
                all_records = [
                    {**f.get("properties", {}), "the_geom": f.get("geometry")}
                    for f in fc.get("features", [])
                ]
                print(f"    fallback GeoJSON: {len(all_records)} records")
            except Exception as e:
                print(f"    fallback parse error: {e}")

    out.write_text(json.dumps(all_records, indent=2))
    print(f"Building footprints done: {len(all_records)} features.")


def fetch_nyccas_station_meta():
    """Save station metadata locally."""
    out = RAW_DIR / "nyccas_station_meta.csv"
    if out.exists():
        print("Station meta already fetched, skip.")
        return
    url = "https://raw.githubusercontent.com/nychealth/nyccas-data/refs/heads/main/hist/csv/location.csv"
    r = requests.get(url, timeout=30)
    out.write_text(r.text)
    print("Station metadata saved.")


if __name__ == "__main__":
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    print("=== Fetching NYCCAS station metadata ===")
    fetch_nyccas_station_meta()
    print("\n=== Fetching NYCCAS hourly CSVs (2019-2026) ===")
    fetch_nyccas_hourly()
    print("\n=== Fetching NY State DAC designations ===")
    fetch_dac()
    print("\n=== Fetching Building Footprints (South Bronx) ===")
    fetch_building_footprints()
    print("\nAll fetches complete.")
