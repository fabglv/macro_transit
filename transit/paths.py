"""Where a city's public-transport designs, simulations and caches live.

    designs/<city>/<name>.json                 a design: changes to the city's lines
    data/<city>/cache/transit_road_network/    the OSM streets for the study box, downloaded once
    output/transit/designs/<city>-<name>/      a design's pages: its lines, maps and feed, no
                                               assignment (transit/design.py)
    output/transit/simulations/<city>-<name>/  a simulation of a design (transit/pipeline.py):
        run_log.txt, summary.json
        maps/, exports/, map_data/
        aequilibrae/transit_project/          the working AequilibraE project

The baseline is a design too - the city's lines as its inputs give them - named "baseline", with
no file. Its simulation holds the demand every other simulation of the city reuses.

`out_dir` sends a simulation's outputs elsewhere, so a test run cannot overwrite the real ones.
The cache stays shared.
"""
import os
from dataclasses import dataclass

from core.paths import ROOT, TRANSIT_OUTPUT

BASELINE = "baseline"
DESIGNS = os.path.join(ROOT, "designs")
DESIGN_OUTPUT = os.path.join(TRANSIT_OUTPUT, "designs")
SIMULATION_OUTPUT = os.path.join(TRANSIT_OUTPUT, "simulations")


def design_file(city, name):
    return os.path.join(DESIGNS, city, f"{name}.json")


def street_cache(city):
    return os.path.join(ROOT, "data", city, "cache", "transit_road_network")


def _empty(folders, *files):
    """Maps, exports and map data are emptied on each run, so they only ever hold the current
    set: a GeoPackage written over an old one keeps its pages and only grows, and a file left by
    an earlier run would be read as part of this one. The summary goes too, so a run that stops
    half way cannot leave the last run's numbers describing it."""
    for folder in folders:
        os.makedirs(folder, exist_ok=True)
        for stale in os.listdir(folder):
            path = os.path.join(folder, stale)
            if os.path.isfile(path):
                os.remove(path)
    for path in files:
        if os.path.exists(path):
            os.remove(path)


@dataclass
class TransitPaths:
    """A simulation's folders: of the design `design`, the baseline by default - named `name`
    when its options are not the defaults (transit/options.py), else as its design."""
    city: str
    out_dir: str = None
    design: str = BASELINE
    name: str = None

    def __post_init__(self):
        self.street_network = street_cache(self.city)
        self.name = self.name or self.design
        self.output = self.out_dir or os.path.join(SIMULATION_OUTPUT,
                                                   f"{self.city}-{self.name}")
        self.maps = os.path.join(self.output, "maps")
        self.exports = os.path.join(self.output, "exports")
        self.map_data = os.path.join(self.output, "map_data")
        self.project = os.path.join(self.output, "aequilibrae", "transit_project")
        self.project_db = os.path.join(self.project, "project_database.sqlite")
        self.transit_db = os.path.join(self.project, "public_transport.sqlite")
        self.gtfs = os.path.join(self.exports, "gtfs_feed.zip")
        self.summary = os.path.join(self.output, "summary.json")
        self.log = os.path.join(self.output, "run_log.txt")

    def prepare_outputs(self):
        _empty((self.maps, self.exports, self.map_data), self.summary)


@dataclass
class DesignPaths:
    """A design's folders: its pages, maps and feed - nothing assigned."""
    city: str
    design: str = BASELINE

    def __post_init__(self):
        self.street_network = street_cache(self.city)
        self.output = os.path.join(DESIGN_OUTPUT, f"{self.city}-{self.design}")
        self.maps = os.path.join(self.output, "maps")
        self.exports = os.path.join(self.output, "exports")
        self.map_data = os.path.join(self.output, "map_data")
        self.gtfs = os.path.join(self.exports, "gtfs_feed.zip")
        self.lines = os.path.join(self.exports, "lines.geojson")
        self.summary = os.path.join(self.output, "summary.json")
        self.log = os.path.join(self.output, "run_log.txt")

    def prepare_outputs(self):
        _empty((self.maps, self.exports, self.map_data), self.summary)
