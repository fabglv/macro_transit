"""Build a city's zones, O-D matrix and baseline assignment - or, with --transit, its
public-transport model.

    python run.py sorocaba
    python run.py quito
    python run.py sorocaba --out output/test_run      # a test run that cannot touch output/
    python run.py quito --rebuild-network             # download the OSM network again
    python run.py sorocaba --run car_share_40         # macro_runs/sorocaba/car_share_40.json's
                                                      # parameters: output/macro/sorocaba-car_share_40/
    python run.py sorocaba --run car_share_40 --step zones   # one step: zones, demand, assignment
    python run.py quito --transit                     # a public-transport simulation: the baseline
    python run.py quito --transit --design l1_double  # ... of designs/quito/l1_double.json
    python run.py quito --transit --design l1_double --day saturday --period 10-14 --demand-factor 0.6

A design's own pages - its lines, maps and feed, no simulation - are design.py's.

Settings live in cases/<city>/settings.py (transit_settings.py for --transit): change a value
there and run again. Everything printed is also written to <output>/run_log.txt.
"""
import argparse
import os
import sys
import time

# AequilibraE draws a progress bar for every skim and assignment iteration. It reads this switch
# once, when first imported, so it is set before anything imports it.
os.environ.setdefault("AEQ_SHOW_PROGRESS", "FALSE")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cases import CASES, load                      # noqa: E402
from core.paths import CityPaths                 # noqa: E402
from core.report import Tee                      # noqa: E402
from transit import TRANSIT_CASES                # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("city", choices=sorted(CASES))
    parser.add_argument("--out", help="write maps, exports and the working model here instead "
                                      "of output/macro/<city>/ (output/transit/simulations/<city>-<design>/ with --transit)")
    parser.add_argument("--rebuild-network", action="store_true",
                        help="download the OSM road network again instead of using the cache")
    parser.add_argument("--transit", action="store_true",
                        help="run the public-transport model instead of the road model "
                             f"(cities with one: {', '.join(sorted(TRANSIT_CASES))})")
    parser.add_argument("--design", "--scenario", metavar="NAME", dest="design",
                        help="with --transit: simulate designs/<city>/NAME.json, into "
                             "output/transit/simulations/<city>-NAME/ (the baseline without it)")
    parser.add_argument("--run", metavar="NAME",
                        help="the road model with macro_runs/<city>/NAME.json's parameters "
                             "changed, into output/macro/<city>-NAME/ (core/runs.py)")
    parser.add_argument("--step", choices=["zones", "demand", "assignment"],
                        help="one step of the road model (core/steps.py), after the steps before "
                             "it: 1 zones and network, 2 demand, 3 assignment and results")
    parser.add_argument("--day", choices=["weekday", "saturday", "sunday"], default="weekday",
                        help="with --transit: the type of day simulated (its timetable)")
    parser.add_argument("--period", metavar="H-H",
                        help="with --transit: the hours simulated, e.g. 10-14 (the city's "
                             "PERIOD_HOURS without it)")
    parser.add_argument("--trips", type=float,
                        help="with --transit: the uniform matrix's trips in the period (the "
                             "city's TARGET_PEAK_TRIPS without it)")
    parser.add_argument("--transfer-penalty", type=float, metavar="S",
                        help="with --transit: seconds added at each change of vehicle")
    parser.add_argument("--wait-factor", type=float, metavar="F",
                        help="with --transit: the share of the headway a passenger waits")
    parser.add_argument("--access", type=float, metavar="M",
                        help="with --transit: a zone walks to the stops this far from its middle")
    parser.add_argument("--walking-speed", type=float, help="with --transit: m/s")
    parser.add_argument("--transfer-walk", type=float, metavar="M",
                        help="with --transit: stops this far apart on foot are joined")
    args = parser.parse_args()
    out = os.path.abspath(args.out) if args.out else None
    if args.design and not args.transit:
        parser.error("--design is for the public-transport model: add --transit")
    if args.run and args.transit:
        parser.error("--run is for the road model; a public-transport design is --design")

    if args.transit:
        if args.city not in TRANSIT_CASES:
            parser.error(f"{args.city} has no public-transport case; --transit runs for: "
                         f"{', '.join(sorted(TRANSIT_CASES))}")
        import transit
        from transit.paths import BASELINE, TransitPaths
        from transit.pipeline import TransitModel
        settings, inputs = transit.load(args.city)
        if not getattr(settings, "SIMULATION_READY", True):
            parser.error(settings.NOT_READY)
        from transit.options import Options
        try:
            period = tuple(int(h) for h in args.period.split("-")) if args.period else None
        except ValueError:
            parser.error(f"--period is two whole hours, e.g. 10-14, not {args.period!r}")
        try:
            options = Options(args.day, period, args.trips, args.walking_speed,
                              args.transfer_walk, args.transfer_penalty, args.wait_factor,
                              args.access).check()
        except ValueError as problem:
            parser.error(str(problem))
        design_name = args.design or BASELINE
        name = options.name(design_name, settings)
        # The baseline's simulation, which a design's is compared with; the demand is built by
        # every simulation alike - a uniform matrix of its trips.
        baseline = TransitPaths(args.city) if name != BASELINE else None
        # Its log compares it with the baseline's simulation on the same options, if there is one.
        same = TransitPaths(args.city, name=options.name(BASELINE, settings))
        compare_to = same if name != same.name and os.path.exists(same.summary) else None
        if args.design and args.design != BASELINE:
            from transit import scenario as designs
            try:
                chosen = designs.load(args.city, args.design)
                designs.apply(chosen, inputs.LINES, inputs.LINE_COLORS)     # fail before running
            except (OSError, ValueError) as problem:
                parser.error(str(problem))
            paths = TransitPaths(args.city, out, args.design, name)
            model = TransitModel(settings, inputs, paths, chosen, baseline, options, compare_to)
        else:
            paths = TransitPaths(args.city, out, BASELINE, name)
            model = TransitModel(settings, inputs, paths, None, baseline, options, compare_to)
    else:
        from core import runs
        try:                             # its values reach the settings as they are imported
            run = runs.read(args.city, args.run or runs.BASELINE)
            run["city"] = args.city
            runs.apply(run)
            model_cls, settings = load(args.city)
        except ValueError as problem:
            parser.error(str(problem))
        missing = runs.unknown(run, settings)
        if missing:
            parser.error(f"{runs.path(args.city, run['name'])}: {args.city} has no parameter "
                         f"{', '.join(missing)}")
        paths = CityPaths(args.city, out or runs.output_dir(args.city, run["name"]))
        model = model_cls(settings, paths)
        model.run_info = {k: run[k] for k in ("name", "label", "description")} | {
            "changes": {k: settings.ASSUMED.defaults.get(k) for k in run["parameters"]}}
        model.inputs = runs.inputs_of(args.city, run)
        if run.get("base"):              # a scenario: its base's zones and demand, its edits
            try:
                checked = runs.check_scenario(args.city, run["name"], run)
            except ValueError as problem:
                parser.error(str(problem))
            model.base_run, model.edits = checked["base"], checked["edits"]
            model.run_info |= {k: checked[k] for k in ("base", "type", "edits")}

    if args.step and args.transit:
        parser.error("--step is for the road model")
    if args.step:                        # a step's log is its own; the run's is joined at the end
        from core import steps
        tee = Tee(steps.log_path(paths.output, args.step))
    else:
        tee = Tee(paths.log)
    sys.stdout = tee
    started = time.time()
    try:
        if args.transit:
            model.run(rebuild_network=args.rebuild_network)
        else:
            model.run(rebuild_network=args.rebuild_network, step=args.step)
    except RuntimeError as problem:      # a step whose steps before it are not done
        if not args.step:
            raise
        print(f"\nERROR: {problem}")
        raise SystemExit(2) from None
    finally:
        print(f"\n[{args.city}{' transit' if args.transit else ''}: "
              f"{(time.time() - started) / 60:.1f} minutes]")
        sys.stdout = tee.console
        tee.close()


if __name__ == "__main__":
    main()
