"""Build a public-transport design's pages - its lines, maps and feed - without a simulation.

    python design.py quito                  the baseline: the city's lines as its inputs give them
    python design.py quito l1_double        designs/quito/l1_double.json
    python design.py quito --all            the baseline and every design of the city

Seconds per design. A design's simulation is `python run.py quito --transit --design <name>`.
Everything printed is also written to the design's run_log.txt.
"""
import argparse
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import viewer                            # noqa: E402
from core.report import Tee                        # noqa: E402
from transit import TRANSIT_CASES                  # noqa: E402
from transit.design import build                   # noqa: E402
from transit.paths import BASELINE, DESIGNS, DesignPaths  # noqa: E402


def build_logged(city, name):
    paths = DesignPaths(city, name)
    tee = Tee(paths.log)
    sys.stdout = tee
    started = time.time()
    try:
        build(city, name)
    finally:
        print(f"\n[{city} design {name}: {time.time() - started:.0f} s]")
        sys.stdout = tee.console
        tee.close()
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("city", choices=sorted(TRANSIT_CASES))
    parser.add_argument("design", nargs="?", default=BASELINE,
                        help="a design in designs/<city>/, or 'baseline' (the default)")
    parser.add_argument("--all", action="store_true",
                        help="the baseline and every design of the city")
    args = parser.parse_args()

    names = [args.design]
    if args.all:
        names = [BASELINE] + sorted(os.path.basename(p)[:-5] for p in
                                    glob.glob(os.path.join(DESIGNS, args.city, "*.json")))
    built = []
    for name in names:
        try:
            built.append(build_logged(args.city, name))
        except (OSError, ValueError) as problem:
            print(f"{name}: {problem}")
    if built:
        page = viewer.build(built[-1].output)       # builds every design's page and the lists
        print(f"Design page: {page}")


if __name__ == "__main__":
    main()
