"""Open the results pages in the browser, building them again first.

    python view.py                          the start page: macrosimulation or public transport
    python view.py sorocaba                 a city's macrosimulation (output/macro/sorocaba)
    python view.py quito --transit          a city's baseline simulation (output/transit/simulations/quito-baseline)
    python view.py quito-l1_double --transit    another of its simulations
    python view.py output/macro/test_run    any run's output folder
    python view.py sorocaba --no-open       only rebuild the pages
    python view.py sorocaba --maps          redraw every map first
    python view.py --maps                   ... for every run

Every run writes its pages at the end; this is for opening them again, or for building them for
a run made before the pages existed. It only reads the output folders and runs no model - with
--maps it redraws every map from what the run saved (core.maps.redraw_maps), which takes
seconds, so a change to how a map looks needs no new run.
"""
import argparse
import os
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import viewer                              # noqa: E402
from core.maps import redraw_maps                    # noqa: E402
from core.paths import MACRO_OUTPUT                  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run", nargs="?",
                        help="a city, or a run's output folder; leave out for the start page")
    parser.add_argument("--transit", action="store_true",
                        help="the city's public-transport run rather than its macrosimulation")
    parser.add_argument("--no-open", action="store_true", help="build the pages, do not open them")
    parser.add_argument("--maps", action="store_true",
                        help="redraw every map from what the run saved, first")
    args = parser.parse_args()

    if args.run is None:
        if args.maps:
            for folder in (MACRO_OUTPUT, viewer.DESIGN_OUTPUT, viewer.SIMULATION_OUTPUT):
                for run in viewer.find_runs(folder):
                    redraw_maps(run)
        page = viewer.build_all()
        print(f"Start page: {page}")
    else:
        folder = args.run
        if not os.path.isdir(folder):
            if args.transit:          # a city's baseline simulation, or one named city-name
                name = args.run if "-" in args.run else f"{args.run}-baseline"
                folder = os.path.join(viewer.SIMULATION_OUTPUT, name)
            else:
                folder = os.path.join(MACRO_OUTPUT, args.run)
        if not os.path.isdir(folder):
            parser.error(f"no output folder for {args.run!r}: run it first with "
                         f"python run.py {args.run}{' --transit' if args.transit else ''}")
        if args.maps:
            redraw_maps(os.path.abspath(folder))
        page = viewer.build(os.path.abspath(folder))
        print(f"Results page: {page}")
    if not args.no_open:
        webbrowser.open(Path(page).as_uri())


if __name__ == "__main__":
    main()
