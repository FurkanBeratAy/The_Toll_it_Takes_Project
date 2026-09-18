import requests, json
from pathlib import Path
BF_URL = 'https://data.cityofnewyork.us/resource/5zhs-2jue.json'
bb = dict(min_lon=-73.945, max_lon=-73.870, min_lat=40.795, max_lat=40.870)
where = 'within_box(the_geom,{min_lat},{min_lon},{max_lat},{max_lon})'.format(**bb)
params = {chr(36)+'limit': 50000, chr(36)+'select': 'bin,height_roof,ground_elevation,the_geom', chr(36)+'where': where}
r = requests.get(BF_URL, params=params, timeout=120)
print('Status:', r.status_code, 'Records:', len(r.json()) if r.ok else 0)
if r.ok:
    out = Path(__file__).resolve().parent.parent / 'building_footprints_sbx.json'
    out.write_text(json.dumps(r.json(), indent=2))
    print('Saved to', out)
