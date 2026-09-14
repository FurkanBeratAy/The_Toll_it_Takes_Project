from pathlib import Path
import pandas as pd

BASE_DIR = Path(r"C:\Users\Furkan\Desktop\The Toll it Takes")
RAW_DIR = BASE_DIR          # existing downloads are in root
PROCESSED_DIR = BASE_DIR / "data" / "processed"
SITE_DIR = BASE_DIR / "site"

TOLL_DATE = pd.Timestamp("2025-01-05")
VW_START  = pd.Timestamp("2024-02-22")   # Van Wyck monitor start
COVID_START = pd.Timestamp("2020-03-22")
COVID_END   = pd.Timestamp("2021-06-15")

# Monitor SiteIDs → human names (from hist/csv/location.csv)
SITE_MAP = {
    "36005NY12387": "Cross_Bronx_Expy",
    "36005NY11790": "Hunts_Point",
    "36005NY11534": "Mott_Haven",
    "36047NY07974": "BQE",
    "36061NY08454": "Manhattan_Bridge",
    "36061NY08552": "Williamsburg_Bridge",
    "36061NY10130": "Queensboro_Bridge",
    "36061NY12380": "Hamilton_Bridge",
    "36061NY09734": "Broadway_35th_St",
    "36061NY09929": "Midtown_DOT",
    "36061NY08653": "FDR",
    "36081NY09285": "Queens_College",
    "36081NY07615": "Van_Wyck",
    "36085NY03820": "SI_Expwy",
}

STATION_COORDS = {
    "Cross_Bronx_Expy":   (40.84517, -73.90614),
    "Hunts_Point":        (40.81909, -73.88566),
    "Mott_Haven":         (40.80649, -73.92249),
    "BQE":                (40.70280, -73.96082),
    "Manhattan_Bridge":   (40.71651, -73.99700),
    "Williamsburg_Bridge":(40.71807, -73.98606),
    "Queensboro_Bridge":  (40.76123, -73.96389),
    "Hamilton_Bridge":    (40.84654, -73.93302),
    "Broadway_35th_St":   (40.75069, -73.98783),
    "Midtown_DOT":        (40.75508, -73.99042),
    "FDR":                (40.72229, -73.97465),
    "Queens_College":     (40.73711, -73.82156),
    "Van_Wyck":           (40.69015, -73.80908),
    "SI_Expwy":           (40.60921, -74.15118),
}

TREATMENT_SITES = [
    "Cross_Bronx_Expy", "Hunts_Point", "Mott_Haven",
    "Manhattan_Bridge", "Williamsburg_Bridge", "Queensboro_Bridge",
]
CONTROL_SITES = ["Queens_College", "Van_Wyck"]
