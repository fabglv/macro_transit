"""Invariant checks: answers known without knowing the city - what must not change, which way a
change must go, what must add up. They run scenarios and simulations of their own on a city's
computed baselines, check them, report, and delete what they made.

    python tests/invariants.py                  # Sorocaba, road and public transport (~30 min)
    python tests/invariants.py --only road      # or --only transit
    python tests/invariants.py --keep           # leave the runs made, to look at them

Road (the scenarios are the model's own, run with run.py):
    neutral edits     capacity x 1.0, closing links no one uses, a new road at 1 km/h, 0.01 trips
                      added: the base's results, within the solver's noise
    direction         a closure raises vehicle-hours; doubling congested roads' capacity lowers
                      their V/C; a slow stretch loses traffic; added trips add exactly that many
    conservation      every run: the vehicles leaving and reaching the zones are the matrix's
    staged = one go   the baseline run at once, into a scratch folder, is the staged one exactly
Public transport (simulations of the baseline design, and a design of its own):
    accounting        trips that reach the network = those boarding + those walking all the way
    uniform matrix    the share reaching the network = the share of pairs of served zones
    linearity         twice the trips: twice the boardings, the same average journey
    direction         no transfer penalty: no fewer transfers; a wider walk to a stop: more zones
                      reached; a line twice as frequent: more boardings, no more waiting

A check fails when the answer is not what it must be; the report gives its numbers either way.
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import closing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PREFIX = "zzt_"                    # every run these checks make is named so, and deleted after
NOISE = 0.005                      # 0.5%: what an equilibrium at the model's gap target may move
REPORT = os.path.join(ROOT, "tests", "invariants_report.txt")

results = []                       # (area, name, passed, detail)


def check(area, name, passed, detail):
    results.append((area, name, bool(passed), detail))
    print(f"  {'PASS' if passed else 'FAIL'}  {name}: {detail}", flush=True)


def run(*args, timeout=1800):
    """run.py with these arguments: its whole output (raises if it fails)."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    done = subprocess.run([sys.executable, os.path.join(ROOT, "run.py"), *args], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=env, timeout=timeout)
    if done.returncode:
        raise RuntimeError(f"run.py {' '.join(args)} failed:\n{done.stderr[-2500:]}")
    return done.stdout


def run_log(output_dir):
    """A run's log as it wrote it: its run_log.txt - where a staged run's steps' prints go."""
    with open(os.path.join(output_dir, "run_log.txt"), encoding="utf-8", errors="replace") as f:
        return f.read()


def conservation_of(log):
    """The worst difference the run's conservation line reports, as a share; 1 (all of it) if
    the line is absent - a run that does not check itself fails the check."""
    found = re.findall(r"conservation: .* largest difference ([\d.]+)%", log)
    return max(float(x) for x in found) / 100 if found else 1.0


# --- road -------------------------------------------------------------------------------------------
def road_checks(city):
    import geopandas as gpd

    from core import runs, summary
    base_dir = runs.output_dir(city, runs.BASELINE)
    base = summary.read(base_dir)
    if base is None:
        raise SystemExit(f"{city}'s road baseline has no results: run python run.py {city}")
    flows_of = lambda d: (lambda g: dict(zip(g["link_id"], g["car_ab"].fillna(0) + g["car_ba"]  # noqa: E731
                                              .fillna(0))))(gpd.read_file(
                                                  os.path.join(d, "exports", "link_volumes.gpkg"),
                                                  ignore_geometry=True))
    links = gpd.read_file(os.path.join(base_dir, "exports", "link_volumes.gpkg"),
                          ignore_geometry=True)
    links["flow"] = links["car_ab"].fillna(0) + links["car_ba"].fillna(0)
    main = links[links["link_type"].isin(["primary", "secondary", "tertiary", "trunk"])]
    base_flow = dict(zip(links["link_id"], links["flow"]))
    vh = lambda s: s["totals"]["veh_hours"]                                    # noqa: E731

    def stretch(name, n):
        """n links of a street, the busiest first and its neighbours along it."""
        mine = main[main["name"] == name].sort_values("flow", ascending=False)
        return [int(i) for i in mine["link_id"].head(n)]

    def scenario(name, kind, edits):
        body = {"label": name, "description": "invariant check (deleted after)",
                "base": runs.BASELINE, "type": kind, "edits": edits}
        runs.save(city, PREFIX + name, body)
        run(city, "--run", PREFIX + name)
        out = runs.output_dir(city, PREFIX + name)
        return summary.read(out), run_log(out), out

    def flow_change(out):
        mine = flows_of(out)
        ids = set(main["link_id"])
        moved = sum(abs(mine.get(i, 0) - base_flow.get(i, 0)) for i in ids)
        return moved / max(sum(base_flow.get(i, 0) for i in ids), 1)

    busiest = main.groupby("name")["flow"].sum().sort_values(ascending=False).index[0]
    unused = [int(i) for i in main.loc[main["flow"] == 0, "link_id"].head(10)]
    print(f"\nroad checks on {city}: busiest street {busiest}; base {vh(base):,.1f} veh-h, "
          f"{base['totals']['trips']:,.1f} trips")

    def neutral(label, kind, edits):
        s, log, out = scenario(label, kind, edits)
        dv = abs(vh(s) - vh(base)) / vh(base)
        dflow = flow_change(out)
        check("road", f"neutral: {label}", dv <= NOISE and dflow <= 4 * NOISE,
              f"vehicle-hours {vh(base):,.1f} -> {vh(s):,.1f} ({100 * dv:.3f}%), main-road flows "
              f"moved {100 * dflow:.2f}% of their total")
        check("road", f"conservation: {label}", conservation_of(log) < 1e-3,
              f"largest difference {100 * conservation_of(log):.4f}%")
        return s, out

    neutral("capacity_x1", "capacity",
            [{"kind": "capacity", "links": stretch(busiest, 20), "factor": 1.0}])
    if unused:
        neutral("close_unused", "closure", [{"kind": "close", "links": unused}])
    neutral("tiny_trips", "demand", [{"kind": "trips", "pairs": [[12, 200, 0.01]], "both": False}])
    # A new road nobody would take: 1 km/h between two junctions of the busiest street.
    s, out = neutral("slow_road", "newroad", [{
        "kind": "road", "label": "slow", "from_node": _ends(base_dir, stretch(busiest, 1)[0])[0],
        "to_node": _far_node(base_dir, stretch(busiest, 1)[0]), "points": [],
        "link_type": "tertiary", "lanes": 1, "kmh": 1, "lane_capacity": 100, "oneway": False}])

    # Which way a change must go.
    s, log, out = scenario("close_busy", "closure",
                           [{"kind": "close", "links": stretch(busiest, 10)}])
    closed = flows_of(out)
    check("road", "closure raises vehicle-hours", vh(s) > vh(base),
          f"{vh(base):,.1f} -> {vh(s):,.1f} veh-h")
    check("road", "closed links carry nothing",
          all(closed.get(i, 0) == 0 for i in stretch(busiest, 10)),
          f"largest flow on a closed link {max(closed.get(i, 0) for i in stretch(busiest, 10)):.3f}")
    check("road", "conservation: closure", conservation_of(log) < 1e-3,
          f"largest difference {100 * conservation_of(log):.4f}% (trips with no route "
          f"taken out)")

    congested = main.sort_values("voc", ascending=False)
    widen = [int(i) for i in congested["link_id"].head(15)]
    s, log, out = scenario("widen", "capacity", [{"kind": "capacity", "links": widen, "factor": 2.0}])
    after = gpd.read_file(os.path.join(out, "exports", "link_volumes.gpkg"), ignore_geometry=True)
    voc_after = after.set_index("link_id")["voc"].reindex(widen).fillna(0)
    voc_before = links.set_index("link_id")["voc"].reindex(widen).fillna(0)
    check("road", "doubled capacity lowers V/C on the widened links",
          voc_after.max() < voc_before.max() and voc_after.mean() < voc_before.mean(),
          f"worst V/C {voc_before.max():.2f} -> {voc_after.max():.2f}, mean "
          f"{voc_before.mean():.2f} -> {voc_after.mean():.2f}")
    check("road", "widening does not add vehicle-hours", vh(s) <= vh(base) * (1 + NOISE),
          f"{vh(base):,.1f} -> {vh(s):,.1f}")

    slow = stretch(busiest, 10)
    s, log, out = scenario("slow_stretch", "capacity", [{"kind": "speed", "links": slow, "kmh": 5}])
    now = flows_of(out)
    before_sum, after_sum = sum(base_flow[i] for i in slow), sum(now.get(i, 0) for i in slow)
    check("road", "a stretch at 5 km/h loses traffic", after_sum < before_sum,
          f"{before_sum:,.0f} -> {after_sum:,.0f} vehicles on its links")

    s, log, out = scenario("add_trips", "demand",
                           [{"kind": "trips", "pairs": [[12, 200, 1000]], "both": True}])
    added = s["totals"]["trips"] - base["totals"]["trips"]
    check("road", "2,000 trips added are 2,000 more trips", abs(added - 2000) < 1e-6,
          f"{base['totals']['trips']:,.3f} -> {s['totals']['trips']:,.3f} (+{added:,.6f})")
    check("road", "conservation: added trips", conservation_of(log) < 1e-3,
          f"largest difference {100 * conservation_of(log):.4f}%")

    # The baseline run in one go, into a scratch folder: the staged baseline exactly.
    scratch = tempfile.mkdtemp(prefix="zzt_onego_")
    try:
        run(city, "--out", scratch)
        log = run_log(scratch)
        once = summary.read(scratch)
        same = all(math.isclose(once["totals"][k], base["totals"][k], rel_tol=1e-6)
                   for k in ("trips", "veh_hours"))
        check("road", "staged baseline = one-go baseline", same,
              f"trips {base['totals']['trips']:,.3f} / {once['totals']['trips']:,.3f}, veh-h "
              f"{vh(base):,.3f} / {once['totals']['veh_hours']:,.3f}")
        check("road", "conservation: baseline", conservation_of(log) < 1e-3,
              f"largest difference {100 * conservation_of(log):.4f}%")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _ends(base_dir, link_id):
    import sqlite3
    db = os.path.join(base_dir, "aequilibrae", "road_model", "project_database.sqlite")
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute("SELECT a_node, b_node FROM links WHERE link_id = ?",
                            (link_id,)).fetchone()


def _far_node(base_dir, link_id):
    """A main-road junction 1-3 km from the link's start: the other end of a new road."""
    import sqlite3
    db = os.path.join(base_dir, "aequilibrae", "road_model", "project_database.sqlite")
    a = _ends(base_dir, link_id)[0]
    with closing(sqlite3.connect(db)) as conn:
        rows = conn.execute("SELECT a_node FROM links WHERE link_type IN ('primary', 'secondary') "
                            "AND a_node != ? LIMIT 2000", (a,)).fetchall()
    from aequilibrae import Project

    from core.network import release_log_files
    folder = os.path.join(base_dir, "aequilibrae", "road_model")
    project = Project()
    project.open(folder)
    try:
        here = project.network.nodes.get(a).geometry
        for (n,) in rows:
            p = project.network.nodes.get(n).geometry
            km = math.hypot((p.x - here.x) * 102, (p.y - here.y) * 111)
            if 1 < km < 3:
                return int(n)
    finally:
        project.close()
        release_log_files(folder)
    raise RuntimeError("no junction 1-3 km away for the new road")


# --- public transport -------------------------------------------------------------------------------
def transit_checks(city):
    import pandas as pd

    from transit.paths import TransitPaths
    base_paths = TransitPaths(city)
    with open(base_paths.summary, encoding="utf-8") as f:
        base = json.load(f)
    t = base["totals"]
    print(f"\npublic-transport checks on {city}: base {t['trips']:,.0f} trips, {t['boarded']:,.1f} "
          f"boarding, {t['boardings']:,.1f} boardings")

    check("transit", "accounting: reaching = boarding + walking all the way",
          math.isclose(t["served"], t["boarded"] + t["walk_only"], rel_tol=1e-6),
          f"{t['served']:,.3f} = {t['boarded']:,.3f} + {t['walk_only']:,.3f}")
    check("transit", "boardings at least the trips that board", t["boardings"] >= t["boarded"],
          f"{t['boardings']:,.1f} boardings, {t['boarded']:,.1f} trips")
    with open(base_paths.log, encoding="utf-8", errors="replace") as f:
        found = re.search(r"(\d+) of (\d+) zones are within walking distance", f.read())
    if found:
        s, n = int(found.group(1)), int(found.group(2))
        share = s * (s - 1) / (n * (n - 1))
        # At most: a pair of zones each with a stop in reach may still have no way between them
        # on the network - walks do not pass through zones (blocking_centroid_flows).
        check("transit", "uniform matrix: reaching share at most the share of served pairs",
              t["served"] / t["trips"] <= share * (1 + 1e-6) and t["served"] / t["trips"] > 0.9 * share,
              f"{100 * t['served'] / t['trips']:.3f}% of the trips, {100 * share:.3f}% of the pairs "
              f"({s} of {n} zones served)")

    made = []

    def simulate(*args, name):
        paths = TransitPaths(city, design=args[args.index("--design") + 1]
                             if "--design" in args else "baseline", name=name)
        made.append(paths.output)                # deleted after, even if the run fails
        run(city, "--transit", *args)
        with open(paths.summary, encoding="utf-8") as f:
            return json.load(f)["totals"], paths

    try:
        double, _ = simulate("--trips", f"{2 * t['trips']:g}", name=f"baseline-t{2 * t['trips']:g}")
        check("transit", "twice the trips: twice the boardings",
              math.isclose(double["boardings"], 2 * t["boardings"], rel_tol=1e-6),
              f"{t['boardings']:,.3f} -> {double['boardings']:,.3f}")
        check("transit", "twice the trips: the same average journey",
              math.isclose(double["journey_min"], t["journey_min"], rel_tol=1e-6),
              f"{t['journey_min']:.4f} -> {double['journey_min']:.4f} min")

        free, _ = simulate("--transfer-penalty", "0", name="baseline-penalty0")
        check("transit", "no transfer penalty: no fewer transfers",
              free["transfers"] >= t["transfers"] - 1e-9,
              f"{t['transfers']:.4f} -> {free['transfers']:.4f} a trip")

        wide, _ = simulate("--access", "1000", name="baseline-access1000")
        check("transit", "a wider walk to a stop: more trips reach the network",
              wide["served"] > t["served"], f"{t['served']:,.1f} -> {wide['served']:,.1f}")

        stops = pd.read_csv(os.path.join(base_paths.exports, "stops.csv"))
        route = str(stops.groupby("route")["boardings"].sum().idxmax())
        import transit
        settings, inputs = transit.load(city)
        key = next(k for k, line in inputs.LINES.items() if str(line["short"]) == route)
        from transit.paths import DESIGNS
        design = os.path.join(DESIGNS, city, f"{PREFIX}freq.json")
        os.makedirs(os.path.dirname(design), exist_ok=True)
        with open(design, "w", encoding="utf-8") as f:
            json.dump({"label": "frequency x2 (invariant check)", "description": "",
                       "changes": [{"type": "frequency", "route": inputs.LINES[key]["short"],
                                    "factor": 2}]}, f)
        made.append(design)
        freq, paths = simulate("--design", f"{PREFIX}freq", name=f"{PREFIX}freq")
        after = pd.read_csv(os.path.join(paths.exports, "stops.csv"))
        b0 = stops.loc[stops["route"].astype(str) == route, "boardings"].sum()
        b1 = after.loc[after["route"].astype(str) == route, "boardings"].sum()
        check("transit", f"line {route} twice as frequent: more boardings on it", b1 > b0,
              f"{b0:,.1f} -> {b1:,.1f}")
        check("transit", f"line {route} twice as frequent: no more waiting",
              freq["waiting_min"] <= t["waiting_min"] + 1e-9,
              f"{t['waiting_min']:.3f} -> {freq['waiting_min']:.3f} min a trip")
    finally:
        if not KEEP:
            for path in made:
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                elif os.path.isfile(path):
                    os.remove(path)


def clean_road(city):
    from core import runs
    for name in [n for n in os.listdir(os.path.join(runs.RUNS, city))
                 if n.startswith(PREFIX) and n.endswith(".json")] if os.path.isdir(
                     os.path.join(runs.RUNS, city)) else []:
        shutil.rmtree(runs.output_dir(city, name[:-5]), ignore_errors=True)
        os.remove(os.path.join(runs.RUNS, city, name))


KEEP = False


def main():
    global KEEP
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", default="sorocaba")
    parser.add_argument("--only", choices=["road", "transit"])
    parser.add_argument("--keep", action="store_true", help="leave the runs made")
    args = parser.parse_args()
    KEEP = args.keep
    started = time.time()
    try:
        for area, checks in (("road", road_checks), ("transit", transit_checks)):
            if args.only in (None, area):
                try:
                    checks(args.city)
                except Exception as problem:                     # noqa: BLE001 - reported
                    check(area, "the checks ran to the end", False, f"{type(problem).__name__}: "
                          f"{str(problem)[:2000]}")
    finally:
        if not KEEP:
            clean_road(args.city)
    failed = [r for r in results if not r[2]]
    lines = [f"{'PASS' if ok else 'FAIL'}  [{area}] {name}: {detail}"
             for area, name, ok, detail in results]
    head = (f"invariant checks on {args.city}, {time.strftime('%Y-%m-%d %H:%M')}, "
            f"{(time.time() - started) / 60:.0f} min: {len(results) - len(failed)} passed, "
            f"{len(failed)} failed")
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(head + "\n\n" + "\n".join(lines) + "\n")
    print("\n" + head)
    for line in lines:
        if line.startswith("FAIL"):
            print(line)
    print(f"report: {REPORT}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
