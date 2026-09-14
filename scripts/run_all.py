"""
Run the full data pipeline in dependency order.
Usage: python scripts/run_all.py
"""
import subprocess, sys, time
from pathlib import Path

PY = sys.executable

STEPS = [
    ("01 Fetch remote data",         "01_fetch.py"),
    ("02 CRZ geofence",              "02_crz_geofence.py"),
    ("03 Traffic diversion",         "03_traffic.py"),
    ("04 NYCCAS pollution daily",    "04_pollution.py"),
    ("05 ITS regression",            "05_its_model.py"),
    ("06 Geospatial processing",     "06_geo.py"),
    ("07 Canyon analysis",           "07_canyon.py"),
    ("08 Assemble + validate",       "08_assemble.py"),
]

scripts_dir = Path(__file__).parent

for label, script in STEPS:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    t0 = time.time()
    result = subprocess.run([PY, str(scripts_dir / script)], check=False)
    elapsed = time.time() - t0
    status = "✓ done" if result.returncode == 0 else f"✗ FAILED (exit {result.returncode})"
    print(f"  [{status}] in {elapsed:.1f}s")
    if result.returncode != 0:
        print("  Pipeline stopped — fix the error above and re-run.")
        sys.exit(1)

print("\n" + "="*60)
print("  Pipeline complete. Open site/index.html to view the report.")
print("="*60)
