"""
Process MTA B&T Hourly Crossings + CRZ Vehicle Entries.

Outputs:
  processed/traffic_diversion.json   — daily actuals + OLS forecast + residuals per facility
  processed/crz_daily.json           — daily CRZ entries by detection group
  processed/bt_facilities.geojson    — facility points with diversion stats
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from config import RAW_DIR, PROCESSED_DIR, TOLL_DATE

import numpy as np
import pandas as pd
import statsmodels.api as sm
import warnings
warnings.filterwarnings("ignore")


# Known approximate coordinates for B&T facilities
BT_COORDS = {
    "Robert F. Kennedy Bridge Bronx":       (40.7979, -73.9225),
    "Robert F. Kennedy Bridge Queens":       (40.7728, -73.9435),
    "Triborough Bridge":                     (40.7776, -73.9183),
    "Throgs Neck Bridge":                    (40.8044, -73.7963),
    "Bronx-Whitestone Bridge":              (40.8075, -73.8270),
    "Verrazzano - Narrows Bridge":           (40.6067, -74.0444),
    "Hugh L. Carey Tunnel":                  (40.6943, -74.0112),
    "Queens Midtown Tunnel":                 (40.7452, -73.9688),
    "Henry Hudson Bridge":                   (40.8770, -73.9299),
    "Marine Parkway Bridge":                 (40.5727, -73.8947),
    "Cross Bay Veterans Memorial Bridge":    (40.6175, -73.8442),
    "Goethals Bridge":                       (40.6406, -74.2007),
    "Outerbridge Crossing":                  (40.5183, -74.2547),
    "Bayonne Bridge":                        (40.6497, -74.1399),
}

# Facilities with direct Bronx connection — key diversion candidates
BRONX_RELEVANT = {
    "Robert F. Kennedy Bridge Bronx", "Robert F. Kennedy Bridge Queens",
    "Triborough Bridge", "Throgs Neck Bridge", "Bronx-Whitestone Bridge",
}


def load_bt_daily():
    """Load B&T crossings, aggregate to daily totals per facility."""
    print("  Reading B&T crossings (1.88 GB)…")
    dtype = {"Traffic Count": int, "Facility": str, "Date": str}
    chunks = []
    for chunk in pd.read_csv(
        RAW_DIR / "MTA_Bridges_and_Tunnels_Hourly_Crossings__Beginning_2019_20260905.csv",
        usecols=["Date", "Facility", "Vehicle Class Category", "Traffic Count"],
        chunksize=500_000,
        dtype={"Traffic Count": "Int32"},
        low_memory=False,
    ):
        chunk["Date"] = pd.to_datetime(chunk["Date"], format="%m/%d/%Y", errors="coerce")
        chunk = chunk.dropna(subset=["Date"])
        chunks.append(chunk.groupby(["Date", "Facility"])["Traffic Count"].sum().reset_index())

    df = pd.concat(chunks).groupby(["Date", "Facility"])["Traffic Count"].sum().reset_index()
    df = df.rename(columns={"Traffic Count": "volume"})
    df = df.sort_values(["Facility", "Date"])
    print(f"  B&T daily: {len(df)} facility-day rows, {df['Date'].min()} – {df['Date'].max()}")
    return df


def ols_forecast(series, train_end, forecast_start, forecast_end):
    """
    Fit OLS with time trend + month FE + DOW FE on pre-toll training data.
    Return a DataFrame with 'actual', 'forecast', 'residual'.
    """
    full = series.copy()
    train = full[full.index <= train_end].copy()
    t_min = train.index.min()

    def make_features(idx):
        t = (idx - t_min).days.astype(float)
        months = pd.get_dummies(idx.month, prefix="m", drop_first=True)
        dows   = pd.get_dummies(idx.dayofweek, prefix="d", drop_first=True)
        X = pd.concat([
            pd.Series(1.0, index=idx, name="const"),
            pd.Series(t,   index=idx, name="t"),
            months.set_index(idx),
            dows.set_index(idx),
        ], axis=1).fillna(0)
        return X

    X_train = make_features(train.index)
    model = sm.OLS(train.values, X_train).fit()

    forecast_idx = pd.date_range(forecast_start, forecast_end, freq="D")
    forecast_idx = forecast_idx.intersection(full.index)
    X_fc = make_features(forecast_idx)
    # Align columns
    for c in X_train.columns:
        if c not in X_fc.columns:
            X_fc[c] = 0.0
    X_fc = X_fc[X_train.columns]

    yhat = model.predict(X_fc)
    out = pd.DataFrame({
        "actual":   full.reindex(forecast_idx).values,
        "forecast": yhat,
    }, index=forecast_idx)
    out["residual"] = out["actual"] - out["forecast"]
    return out, model


def process_bt(bt_daily):
    results = {}
    facilities = bt_daily["Facility"].unique()
    train_end = TOLL_DATE - pd.Timedelta(days=1)   # 2025-01-04
    fc_start  = TOLL_DATE
    fc_end    = bt_daily["Date"].max()

    for fac in sorted(facilities):
        sub = bt_daily[bt_daily["Facility"] == fac].set_index("Date")["volume"]
        sub = sub.resample("D").sum()

        pre_avg  = float(sub[sub.index <= train_end].mean())
        post_avg = float(sub[sub.index >= fc_start].mean())

        try:
            fc_df, _ = ols_forecast(sub, train_end, fc_start, fc_end)
            fc_df = fc_df.dropna()
            diversion_residual = float(fc_df["residual"].mean())
            diversion_pct      = (diversion_residual / pre_avg * 100) if pre_avg else 0
            series = {
                "dates":    fc_df.index.strftime("%Y-%m-%d").tolist(),
                "actual":   [round(v, 1) for v in fc_df["actual"].tolist()],
                "forecast": [round(v, 1) for v in fc_df["forecast"].tolist()],
                "residual": [round(v, 1) for v in fc_df["residual"].tolist()],
            }
        except Exception as e:
            print(f"    OLS failed for {fac}: {e}")
            fc_df = pd.DataFrame()
            diversion_residual = post_avg - pre_avg
            diversion_pct = (diversion_residual / pre_avg * 100) if pre_avg else 0
            series = {}

        lat, lon = BT_COORDS.get(fac, (None, None))
        results[fac] = {
            "lat": lat, "lon": lon,
            "bronx_relevant": fac in BRONX_RELEVANT,
            "pre_toll_daily_avg":  round(pre_avg, 1),
            "post_toll_daily_avg": round(post_avg, 1),
            "diversion_residual":  round(diversion_residual, 1),
            "diversion_pct":       round(diversion_pct, 2),
            "series": series,
        }
        print(f"  {fac}: d={diversion_residual:+.0f}/day ({diversion_pct:+.1f}%)")

    return results


def load_crz_daily():
    """Aggregate CRZ entries to daily totals per detection group."""
    print("  Reading CRZ entries (1 GB)…")
    chunks = []
    for chunk in pd.read_csv(
        RAW_DIR / "MTA_Congestion_Relief_Zone_Vehicle_Entries__Beginning_2025_20260905.csv",
        usecols=["Toll Date", "Detection Group", "CRZ Entries"],
        chunksize=500_000,
        dtype={"CRZ Entries": "Int32"},
        low_memory=False,
    ):
        chunk["Date"] = pd.to_datetime(chunk["Toll Date"], format="%m/%d/%Y", errors="coerce")
        chunk = chunk.dropna(subset=["Date"])
        chunks.append(
            chunk.groupby(["Date", "Detection Group"])["CRZ Entries"].sum().reset_index()
        )

    df = pd.concat(chunks).groupby(["Date", "Detection Group"])["CRZ Entries"].sum().reset_index()
    df = df.sort_values(["Detection Group", "Date"])

    # Also compute citywide daily total
    total = df.groupby("Date")["CRZ Entries"].sum().reset_index()
    total = total.sort_values("Date")

    # Pivot to wide format for chart
    wide = df.pivot(index="Date", columns="Detection Group", values="CRZ Entries").fillna(0)
    wide.index = wide.index.strftime("%Y-%m-%d")

    print(f"  CRZ daily: {len(total)} days, {total['Date'].min()} – {total['Date'].max()}")
    return total, wide


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    print("\n=== B&T Traffic Diversion ===")
    bt_daily = load_bt_daily()
    bt_results = process_bt(bt_daily)

    print("\n=== CRZ Entries ===")
    crz_total, crz_wide = load_crz_daily()

    crz_out = {
        "dates":   crz_total["Date"].dt.strftime("%Y-%m-%d").tolist(),
        "total":   crz_total["CRZ Entries"].tolist(),
        "by_group": {
            col: crz_wide[col].tolist()
            for col in crz_wide.columns
        },
        "group_dates": crz_wide.index.tolist(),
    }

    (PROCESSED_DIR / "traffic_diversion.json").write_text(
        json.dumps({"facilities": bt_results}, indent=2)
    )
    (PROCESSED_DIR / "crz_daily.json").write_text(json.dumps(crz_out, indent=2))

    # GeoJSON for map
    features = []
    for fac, info in bt_results.items():
        if info["lat"] is None:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "name": fac,
                "diversion_pct": info["diversion_pct"],
                "diversion_residual": info["diversion_residual"],
                "pre_avg": info["pre_toll_daily_avg"],
                "post_avg": info["post_toll_daily_avg"],
                "bronx_relevant": info["bronx_relevant"],
            },
            "geometry": {"type": "Point", "coordinates": [info["lon"], info["lat"]]},
        })
    (PROCESSED_DIR / "bt_facilities.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=2)
    )
    print("\nTraffic outputs saved.")


if __name__ == "__main__":
    main()
