"""A design's simulation against the baseline's: the headline numbers side by side, and the
change in every segment's load - in the simulation's log.

The baseline is read from what its run wrote - summary.json and exports/segments.csv - so a
simulation can be compared without solving the baseline again. Segments are matched on their
`segment` key ("L1_Solanda -> L1_El_Calzado"), which comes from the feed's stop ids and so
survives the design's re-import of the feed. A segment that exists on one side only - a line
added or removed - is kept, with zero passengers on the other side.
"""
import json
import os

import geopandas as gpd
import numpy as np
import pandas as pd

# The rows the page's Comparison view shows too, defined once there.
from core.transit_stats import COMPARISON as ROWS


def baseline_totals(baseline_dir):
    with open(os.path.join(baseline_dir, "summary.json"), encoding="utf-8") as f:
        return json.load(f)["totals"]


def print_comparison(baseline_dir, result):
    """The headline numbers, the baseline against this design, with the change."""
    base = baseline_totals(baseline_dir)
    print(f"{'':<34}{'baseline':>12}{'design':>12}{'change':>10}")
    for label, key, attr, fmt in ROWS:
        b, s = base[key], float(getattr(result, attr))
        # A percentage of something shown as zero says nothing: 0.000 -> 0.071 is not "+17,000%".
        shown_zero = float(fmt.format(b).replace(",", "")) == 0.0
        change = "n/a" if shown_zero else f"{100 * (s - b) / b:+.1f}%"
        print(f"{label:<34}{fmt.format(b):>12}{fmt.format(s):>12}{change:>10}")


def segment_changes(baseline_dir, result):
    """Every segment's load in both runs and the change; geometry from the design's segments
    (a removed line's segments have none, and are listed but not drawn)."""
    keep = ["segment", "route", "from_name", "to_name"]
    base = pd.read_csv(os.path.join(baseline_dir, "exports", "segments.csv"))
    base = base[keep + ["pt_volume"]].rename(columns={"pt_volume": "vol_base"})
    scen = result.segments[keep + ["pt_volume", "geometry"]].rename(
        columns={"pt_volume": "vol_scen"})
    changes = pd.DataFrame(base).merge(pd.DataFrame(scen), on="segment", how="outer",
                                       suffixes=("", "_scen"))
    for col in ("route", "from_name", "to_name"):
        changes[col] = changes[col].fillna(changes[f"{col}_scen"])
    changes = changes.drop(columns=[f"{c}_scen" for c in ("route", "from_name", "to_name")])
    changes[["vol_base", "vol_scen"]] = changes[["vol_base", "vol_scen"]].fillna(0.0)
    changes["change"] = changes["vol_scen"] - changes["vol_base"]
    changes["change_pct"] = np.where(changes["vol_base"] > 0,
                                     100 * changes["change"] / changes["vol_base"].replace(0, 1),
                                     np.nan)
    return gpd.GeoDataFrame(changes, geometry="geometry", crs="EPSG:4326")


def print_top_changes(changes, n=8):
    for title, picked in (("gaining the most passengers", changes.nlargest(n, "change")),
                          ("losing the most passengers", changes.nsmallest(n, "change"))):
        picked = picked[picked["change"].abs() >= 1]
        if not len(picked):
            continue
        print(f"\nRides {title}:")
        out = picked[["route", "from_name", "to_name", "vol_base", "vol_scen", "change"]].copy()
        out["ride"] = out["from_name"] + "  ->  " + out["to_name"]
        print(out[["route", "ride", "vol_base", "vol_scen", "change"]].round(0)
              .rename(columns={"vol_base": "baseline", "vol_scen": "design"})
              .to_string(index=False))
