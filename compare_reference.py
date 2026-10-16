"""Set a run's exports against the ones the original notebook wrote (data/<city>/reference/).

    python compare_reference.py sorocaba
    python compare_reference.py quito

Prints, for the zones, the O-D matrix and the loaded links, how far the two agree. Differences are
expected where the program deliberately differs from a notebook (see README.md); anything else is
worth a look.
"""
import os
import sys

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.paths import CityPaths      # noqa: E402


def main(city):
    p = CityPaths(city)
    ref, new = p.reference, p.exports
    print(f"reference: {ref}\nthis run:  {new}\n")

    zr = gpd.read_file(os.path.join(ref, "zones.gpkg"))
    zn = gpd.read_file(os.path.join(new, "zones.gpkg"))
    print(f"zones: {len(zr)} in the reference, {len(zn)} in this run")
    common = sorted(set(zr.columns) & set(zn.columns) - {"geometry"})
    if len(zr) == len(zn) and (zr["zone"].to_numpy() == zn["zone"].to_numpy()).all():
        for col in common:
            a, b = zr[col], zn[col]
            if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
                diff = np.nanmax(np.abs(a.to_numpy(float) - b.to_numpy(float)))
                scale = np.nanmax(np.abs(a.to_numpy(float))) or 1
                flag = "" if diff <= 1e-6 * scale else "   <- differs"
                print(f"  {col:<26} largest difference {diff:12.6g}{flag}")
            else:
                same = (a.astype(str) == b.astype(str)).mean()
                print(f"  {col:<26} identical in {same:.1%} of zones")

    odr = pd.read_csv(os.path.join(ref, "od_matrix.csv.gz"))
    odn = pd.read_csv(os.path.join(new, "od_matrix.csv.gz"))
    both = odr.merge(odn, on=["origin", "destination"], how="outer", suffixes=("_ref", "_new"))
    both = both.fillna(0)
    print(f"\nO-D pairs: {len(odr):,} in the reference, {len(odn):,} in this run")
    print(f"  trips: {odr['trips'].sum():,.1f} against {odn['trips'].sum():,.1f}")
    print(f"  largest difference in one pair: {np.abs(both['trips_ref'] - both['trips_new']).max():.4f}")
    print(f"  correlation of the cells: {np.corrcoef(both['trips_ref'], both['trips_new'])[0, 1]:.6f}")
    # Minutes only where both files have the pair: the csv leaves out pairs with almost no
    # trips, and a pair missing from one side would count its whole travel time as a difference.
    shared = odr.merge(odn, on=["origin", "destination"], suffixes=("_ref", "_new"))
    print(f"  minutes, largest difference: "
          f"{np.abs(shared['minutes_ref'] - shared['minutes_new']).max():.3f} "
          f"(over the {len(shared):,} pairs in both)")

    lr = gpd.read_file(os.path.join(ref, "link_volumes.gpkg"), ignore_geometry=True)
    ln = gpd.read_file(os.path.join(new, "link_volumes.gpkg"), ignore_geometry=True)
    links = lr.merge(ln, on="link_id", how="outer", suffixes=("_ref", "_new")).fillna(0)
    print(f"\nloaded links: {len(lr):,} in the reference, {len(ln):,} in this run")
    print(f"  vehicle-km: {(lr['flow'] * lr['distance']).sum() / 1000:,.0f} against "
          f"{(ln['flow'] * ln['distance']).sum() / 1000:,.0f}")
    print(f"  correlation of link flows: {np.corrcoef(links['flow_ref'], links['flow_new'])[0, 1]:.4f}")
    print(f"  links over capacity: {(lr['voc'] >= 1).sum():,} against {(ln['voc'] >= 1).sum():,}")

    if os.path.exists(os.path.join(ref, "count_comparison.csv")) and \
            os.path.exists(os.path.join(new, "count_comparison.csv")):
        cr = pd.read_csv(os.path.join(ref, "count_comparison.csv"))
        cn = pd.read_csv(os.path.join(new, "count_comparison.csv"))
        print(f"\ncounts compared: {len(cr)} against {len(cn)}; model/count "
              f"{cr['model'].sum() / cr['count'].sum():.3f} against "
              f"{cn['model'].sum() / cn['count'].sum():.3f}")


if __name__ == "__main__":
    main(sys.argv[1])
