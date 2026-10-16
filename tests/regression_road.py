"""The road model's regression check, and Sorocaba's public transport: run the reference runs
again and compare what comes out with what it was.

    python tests/regression_road.py --quick     # Sorocaba only: about a quarter of an hour
    python tests/regression_road.py             # Sorocaba and Quito
    python tests/regression_road.py --update    # after a change meant to move the results

For each city: its road baseline, run in one go into a scratch folder, and one scenario of each
kind on its computed baseline - a closure, a capacity change, a new road, trips added - and for
Sorocaba its public-transport baseline simulation (Quito's public transport has
tests/regression.py). What is compared, against tests/expected_road.json:

    the baseline     trips, vehicle-hours, the trip groups, the 20 busiest streets' vehicle-km
    each scenario    trips, vehicle-hours, the streets that changed most and by how much, its
                     edits' vehicles and V/C
    public transport the simulation's totals

A number may move by RELATIVE (1e-6) of itself - rounding, not modelling. Anything more is a
change: expected if you meant it (then --update), a regression if not. The scenarios are made on
the city's computed baselines (output/macro/<city>/) and deleted after.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from invariants import _ends, _far_node, run   # noqa: E402 - the same helpers
from regression import differences             # noqa: E402

EXPECTED = os.path.join(ROOT, "tests", "expected_road.json")
PREFIX = "zzr_"


def streets(output_dir, n=20):
    """The n busiest named streets' vehicle-km, both ways."""
    import geopandas as gpd
    links = gpd.read_file(os.path.join(output_dir, "exports", "link_volumes.gpkg"),
                          ignore_geometry=True)
    links = links[links["name"].fillna("") != ""]
    vkm = ((links["car_ab"].fillna(0) + links["car_ba"].fillna(0)) * links["distance"] / 1000)
    top = vkm.groupby(links["name"]).sum().sort_values(ascending=False).head(n)
    return {name: round(float(v), 3) for name, v in top.items()}


def baseline(city, scratch):
    from core import summary
    out = os.path.join(scratch, f"{city}_baseline")
    run(city, "--out", out)
    s = summary.read(out)
    return {"totals": s["totals"], "trip_groups": s["trip_groups"], "streets": streets(out)}


def scenarios(city):
    """One scenario of each kind on the city's computed baseline, made by a fixed rule from it."""
    import geopandas as gpd

    from core import runs, summary
    base_dir = runs.output_dir(city, runs.BASELINE)
    if summary.read(base_dir) is None:
        raise RuntimeError(f"{city}'s road baseline has no results: run python run.py {city}")
    links = gpd.read_file(os.path.join(base_dir, "exports", "link_volumes.gpkg"),
                          ignore_geometry=True)
    links["flow"] = links["car_ab"].fillna(0) + links["car_ba"].fillna(0)
    main = links[links["link_type"].isin(["primary", "secondary", "tertiary", "trunk"])]
    busiest = main.groupby("name")["flow"].sum().sort_values(ascending=False).index[0]
    stretch = [int(i) for i in main[main["name"] == busiest].sort_values(
        "flow", ascending=False)["link_id"].head(10)]
    congested = [int(i) for i in main.sort_values("voc", ascending=False)["link_id"].head(15)]
    zones = gpd.read_file(os.path.join(base_dir, "exports", "zones.gpkg"), ignore_geometry=True)
    a, b = sorted(zones["zone_number"])[11], sorted(zones["zone_number"])[len(zones) // 2]
    kinds = {
        "closure": ("closure", [{"kind": "close", "links": stretch}]),
        "capacity": ("capacity", [{"kind": "capacity", "links": congested, "factor": 2.0}]),
        "newroad": ("newroad", [{
            "kind": "road", "label": "regression road", "from_node": int(_ends(base_dir, stretch[0])[0]),
            "to_node": _far_node(base_dir, stretch[0]), "points": [], "link_type": "primary",
            "lanes": 2, "kmh": 60, "lane_capacity": 1300, "oneway": False}]),
        "demand": ("demand", [{"kind": "trips", "pairs": [[int(a), int(b), 1000]], "both": True}]),
    }
    out = {}
    try:
        for name, (kind, edits) in kinds.items():
            print(f"  {city} scenario {name}", flush=True)
            runs.save(city, PREFIX + name, {"label": name, "description": "regression (deleted after)",
                                            "base": runs.BASELINE, "type": kind, "edits": edits})
            run(city, "--run", PREFIX + name)
            folder = runs.output_dir(city, PREFIX + name)
            with open(os.path.join(folder, "scenario.json"), encoding="utf-8") as f:
                said = json.load(f)
            out[name] = {"totals": summary.read(folder)["totals"], "unrouted": said.get("unrouted"),
                         "more": {r[0]: r[1:] for r in said["more"][:5]},
                         "less": {r[0]: r[1:] for r in said["less"][:5]},
                         "edits": [{k: e.get(k) for k in ("flow", "voc")} for e in said["edits"]]}
    finally:
        for name in kinds:
            shutil.rmtree(runs.output_dir(city, PREFIX + name), ignore_errors=True)
            path = runs.path(city, PREFIX + name)
            if os.path.isfile(path):
                os.remove(path)
    return out


def transit(city, scratch):
    out = os.path.join(scratch, f"{city}_transit")
    run(city, "--transit", "--out", out)
    with open(os.path.join(out, "summary.json"), encoding="utf-8") as f:
        return json.load(f)["totals"]


def measure(cities, scratch):
    got = {}
    for city in cities:
        print(f"{city}: the road baseline, in one go", flush=True)
        got[city] = {"baseline": baseline(city, scratch), "scenarios": scenarios(city)}
        if city == "sorocaba":
            print(f"{city}: the public-transport baseline", flush=True)
            got[city]["transit"] = transit(city, scratch)
    return got


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="Sorocaba only")
    parser.add_argument("--update", action="store_true",
                        help="save the results as the expected ones, instead of checking them")
    args = parser.parse_args()
    cities = ["sorocaba"] if args.quick else ["sorocaba", "quito"]
    with tempfile.TemporaryDirectory(prefix="regression_road_") as scratch:
        try:
            got = measure(cities, scratch)
        except RuntimeError as problem:
            print(f"FAIL: {problem}")
            return 1
    expected = {}
    if os.path.exists(EXPECTED):
        with open(EXPECTED, encoding="utf-8") as f:
            expected = json.load(f)
    if args.update or not all(c in expected for c in cities):
        expected.update(got)
        with open(EXPECTED, "w", encoding="utf-8") as f:
            json.dump(expected, f, indent=1, ensure_ascii=False, sort_keys=True)
        print(f"Saved as the expected results ({', '.join(cities)}): {EXPECTED}")
        return 0
    changed = differences({c: expected[c] for c in cities}, got)
    if not changed:
        print(f"PASS: {', '.join(cities)} run as expected.")
        return 0
    print(f"FAIL: {len(changed)} difference(s):")
    for line in changed[:60]:
        print(f"  {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
