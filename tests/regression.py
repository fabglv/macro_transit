"""The public-transport model's regression check: rebuild the reference designs, simulate them,
and compare what comes out with what it was.

    python tests/regression.py            # check: PASS, or what changed
    python tests/regression.py --update   # after a change meant to move the results: save them

The reference designs are the baseline and the notebook's two scenarios (designs/quito/
l1_double.json, new_line_l2.json) - not designs made in the editor, which come and go. Each is
built (design.py: its feed, operations) and simulated into a scratch folder, so the results pages
are left as they are. What is compared, against tests/expected_quito.json:

    the feed        its files' row counts: calendar services, trips, frequencies, stations
    operations      vehicles needed by mode, vehicle-km and vehicle-hours a weekday
    simulation      trips served and boarded, boardings, passenger-hours, the journey's parts

A number may move by RELATIVE (1e-6) of itself - rounding, not modelling. Anything more is a
change: expected if you meant it (then --update), a regression if not. About three minutes.
"""
import argparse
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CITY = "quito"
DESIGNS = ["baseline", "l1_double", "new_line_l2"]
EXPECTED = os.path.join(ROOT, "tests", f"expected_{CITY}.json")
RELATIVE = 1e-6
TOTALS = ["served", "boarded", "walk_only", "boardings", "passenger_hours", "journey_min",
          "riding_min", "waiting_min", "walking_min", "transfers"]


def run(args, log):
    """A command of the project's, with its output kept in `log`; raises if it fails."""
    with open(log, "w", encoding="utf-8") as f:
        done = subprocess.run([sys.executable] + args, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    if done.returncode:
        kept = os.path.join(ROOT, "tests", "last_failure.log")
        shutil.copyfile(log, kept)                     # the scratch folder goes; this stays
        raise RuntimeError(f"{' '.join(args)} failed - its output is in {kept}")


def feed_counts(path):
    """Row counts of the feed's files, and its calendar's services and stations."""
    with zipfile.ZipFile(path) as z:
        def rows(name):
            with z.open(name) as f:
                return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))
        out = {name[:-4]: len(rows(name)) for name in sorted(z.namelist())}
        out["services"] = sorted(c["service_id"] for c in rows("calendar.txt"))
        out["stations"] = sorted(s["stop_id"] for s in rows("stops.txt") if s.get("location_type") == "1")
    return out


def measure(scratch):
    """Everything compared, for every reference design."""
    from transit.paths import DesignPaths
    out = {}
    for name in DESIGNS:
        print(f"  {name}: building", flush=True)
        run(["design.py", CITY, name], os.path.join(scratch, f"design_{name}.log"))
        pages = DesignPaths(CITY, name)
        with open(pages.summary, encoding="utf-8") as f:
            design = json.load(f)
        with open(os.path.join(pages.exports, "operations.csv"), encoding="utf-8") as f:
            ops = list(csv.DictReader(f))
        print(f"  {name}: simulating", flush=True)
        sim = os.path.join(scratch, f"sim_{name}")
        args = ["run.py", CITY, "--transit", "--out", sim]
        if name != "baseline":
            args += ["--design", name]
        run(args, os.path.join(scratch, f"sim_{name}.log"))
        with open(os.path.join(sim, "summary.json"), encoding="utf-8") as f:
            simulated = json.load(f)
        out[name] = {
            "feed": feed_counts(pages.gtfs),
            "headline": dict(design["headline"]),
            "operations": {r["route"]: {k: float(r[k]) for k in
                                        ("vehicles_weekday", "vehicle_km_weekday",
                                         "vehicle_hours_weekday", "round_trip_min")}
                           for r in ops},
            "simulation": {k: simulated["totals"][k] for k in TOTALS},
            "operations_simulated": simulated.get("operations", {}),
        }
    return out


def differences(expected, got, path=""):
    """Every place where `got` is not `expected` - numbers within RELATIVE of each other agree."""
    out = []
    if isinstance(expected, dict) and isinstance(got, dict):
        for key in sorted(set(expected) | set(got)):
            if key not in got:
                out.append(f"{path}{key}: missing (was {expected[key]!r})")
            elif key not in expected:
                out.append(f"{path}{key}: new ({got[key]!r})")
            else:
                out += differences(expected[key], got[key], f"{path}{key}.")
    elif isinstance(expected, (int, float)) and isinstance(got, (int, float)):
        if abs(got - expected) > RELATIVE * max(abs(expected), 1):
            change = f" ({100 * (got - expected) / expected:+.2f}%)" if expected else ""
            out.append(f"{path[:-1]}: {expected!r} -> {got!r}{change}")
    elif expected != got:
        out.append(f"{path[:-1]}: {expected!r} -> {got!r}")
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--update", action="store_true",
                        help="save the results as the expected ones, instead of checking them")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="regression_") as scratch:
        print(f"Building and simulating {', '.join(DESIGNS)} (logs in a scratch folder)...")
        try:
            got = measure(scratch)
        except RuntimeError as problem:
            print(f"FAIL: {problem}")
            return 1
    if args.update or not os.path.exists(EXPECTED):
        with open(EXPECTED, "w", encoding="utf-8") as f:
            json.dump(got, f, indent=1, ensure_ascii=False, sort_keys=True)
        print(f"Saved as the expected results: {EXPECTED}")
        return 0
    with open(EXPECTED, encoding="utf-8") as f:
        expected = json.load(f)
    changed = differences(expected, got)
    if not changed:
        print("PASS: every reference design builds and simulates as expected.")
        return 0
    print(f"CHANGED - {len(changed)} thing(s) differ from {os.path.basename(EXPECTED)}:")
    for line in changed:
        print(f"  {line}")
    print("If the change was meant, save the new results: python tests/regression.py --update")
    return 1


if __name__ == "__main__":
    sys.exit(main())
