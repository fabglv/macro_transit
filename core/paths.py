"""Where a city's inputs, caches and outputs live.

    data/<city>/input/      official data, as copied from the original projects
    data/<city>/cache/      downloads kept between runs: the OSM network, regional roads, ...
    data/<city>/reference/  the exports the original notebook wrote, for comparing against
    output/macro/<city>/    what a road run writes: maps, exports, the working AequilibraE
                            model, log (output/transit/<city>/ holds the public-transport runs)

`out_dir` sends a run's outputs elsewhere, so a test run - a sensitivity check, say - cannot
overwrite the real ones. The caches stay shared.
"""
import os
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(ROOT, "output")                 # the start page, index.html, is here
MACRO_OUTPUT = os.path.join(OUTPUT, "macro")          # one folder per road (macrosimulation) run
TRANSIT_OUTPUT = os.path.join(OUTPUT, "transit")      # one folder per public-transport run


@dataclass
class CityPaths:
    city: str
    out_dir: str = None

    def __post_init__(self):
        self.data = os.path.join(ROOT, "data", self.city)
        # The inputs as the model reads them: cut from the originals (data/<city>/input/, not in
        # the repository) by tools/trim_inputs.py.
        self.input = os.path.join(self.data, "input_min")
        self.cache = os.path.join(self.data, "cache")
        self.reference = os.path.join(self.data, "reference", "taz_od_exports")
        self.output = self.out_dir or os.path.join(MACRO_OUTPUT, self.city)
        self.maps = os.path.join(self.output, "maps")
        self.exports = os.path.join(self.output, "exports")
        self.road_network = os.path.join(self.cache, "road_network")
        self.road_model = os.path.join(self.output, "aequilibrae", "road_model")
        self.log = os.path.join(self.output, "run_log.txt")

    def inp(self, *parts):
        return os.path.join(self.input, *parts)

    def cached(self, *parts):
        return os.path.join(self.cache, *parts)

    def require(self, *files):
        for needed in files:
            if not os.path.exists(needed):
                raise FileNotFoundError(f"Missing input: {needed}")

    def prepare_outputs(self):
        """Maps and exports are emptied on each run, so they only ever hold the current set.

        A GeoPackage written over an existing one keeps the old pages and only grows, and a file
        left by an earlier run would be read as part of this one's output.
        """
        for folder in (self.maps, self.exports, os.path.join(self.output, "map_data")):
            os.makedirs(folder, exist_ok=True)
            for stale in os.listdir(folder):
                path = os.path.join(folder, stale)
                if os.path.isfile(path):
                    os.remove(path)
        # An earlier run's summary and results page would describe this run if it stopped
        # half way; they are written again at the end.
        for stale in ("summary.json", "index.html"):
            path = os.path.join(self.output, stale)
            if os.path.exists(path):
                os.remove(path)
        os.makedirs(self.cache, exist_ok=True)
