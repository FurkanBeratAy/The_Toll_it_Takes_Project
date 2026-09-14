import json
from pathlib import Path

root = Path(__file__).parent.parent
its = json.loads((root/'data/processed/its_results.json').read_text())
div = json.loads((root/'data/processed/traffic_diversion.json').read_text())
canyon = json.loads((root/'data/processed/canyon_analysis.json').read_text())

print("=== ITS RESULTS ===")
for site, data in its['sites'].items():
    for spec_name, spec in [('full', data.get('full')), ('long', data.get('long'))]:
        if spec:
            qc = spec.get('beta_qc', '?')
            vw = spec.get('beta_vw', '?')
            print(f"{site} [{spec_name}]: beta={spec['beta_post']:+.4f}, p={spec['beta_post_p']:.4f}, "
                  f"sig={spec['significant']}, R2={spec['r2']:.4f}, n={spec['n']}, "
                  f"CI=[{spec['ci95_low']:.3f},{spec['ci95_high']:.3f}], "
                  f"gamma_QC={qc}, gamma_VW={vw}")

print()
print("=== TRAFFIC DIVERSION (sorted by residual) ===")
facs = [(k, v) for k, v in div['facilities'].items() if v.get('diversion_residual') is not None]
facs.sort(key=lambda x: x[1]['diversion_residual'], reverse=True)
for fac, d in facs:
    print(f"{fac}: {d['diversion_residual']:+.0f} veh/day ({d['diversion_pct']:+.2f}%), bronx={d['bronx_relevant']}, pre={d.get('pre_toll_daily_avg','?'):.0f}, post={d.get('post_toll_daily_avg','?'):.0f}")

print()
print("=== CANYON ===")
print(f"Site: {canyon['site']}, H/W={canyon['hw_ratio']}, discount={canyon['canyon_discount']}")
print(f"Bldg height: {canyon['mean_building_height_ft']} ft, Street width: {canyon['street_width_ft']} ft")
print(f"Canopy: {canyon['canopy']['estimated_canopy_pct']}% existing, {canyon['canopy']['citywide_canopy_pct']}% citywide, gap={canyon['canopy']['canopy_gap_pct']} pp")
print(f"Existing trees in corridor: {canyon['canopy']['n_trees_existing']}, {canyon['canopy']['trees_per_mile']}/mile vs {canyon['canopy']['citywide_trees_per_mile']}/mile citywide")
for k, v in canyon['typologies'].items():
    print(f"  {k}: naive={v['removal_naive_kg_yr']:.2f} kg/yr, adj={v['removal_adjusted_kg_yr']:.2f} kg/yr, discount={v['canyon_discount']:.0%}, yr1={v['projection']['1']:.1f}, yr10={v['projection']['10']:.1f}, yr20={v['projection']['20']:.1f}")
