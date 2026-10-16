"""The public-transport run, step by step.

    A1  the project, on a copy of the cached OSM streets   project.open_street_project
    A3  zones: the road model's, inside the study box         project.road_zones
    A4  the modelled period                                  project.declare_period
    A5  the GTFS feed, written from the city's LINES          gtfs.write_gtfs, wide_stations
    A6  the import, map-matched; its audits                  project.import_feed, gtfs audits
    A7  the demand: uniform, TARGET_PEAK_TRIPS shared evenly  uniform_demand
    B2  the transit graph and the walking transfers          graph.TransitNetwork
    B3  who can reach the network                            assignment.transit_coverage
    B4  the baseline assignment                              assignment.solve_transit
    B5  the maps                                             maps
    B6  where the network is busy regardless of demand       assignment.structural_check
    B7  exports and summary.json                             export

A city brings its inputs (study box, feed, unserved corridor, line colours) and its settings;
nothing here knows which city it is running.

A design (transit/scenario.py) is simulated by the same steps on the city's lines with its
changes made:
a frequency changed, a line added or removed. It does not build its own demand - it reads the
baseline's, which the baseline run saved as exports/demand.npy - and its log compares it with the
baseline (transit/compare.py). Any two runs of a city are compared on the results pages'
Compare page, from what each run exported (segments.geojson among it).
"""
import logging
import os
import time

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString

from core import report
from core.export import Exporter
from core.maps import MapKit

from . import compare, export, maps
from . import scenario as scenarios
from .assignment import (assignable_share, busiest_rides, solve_transit, structural_check,
                         summarise, transit_coverage)
from .graph import TransitNetwork
from .paths import BASELINE
from .gtfs import (declared_station_names, one_way_stops, unmatchable_stops, wide_stations,
                   write_gtfs)
from .options import Options
from .project import declare_period, import_feed, open_street_project, road_zones


def uniform_demand(n_zones, trips):
    """The demand: `trips` shared evenly among every pair of different zones. The road model's
    matrices are not reused - their gravity model's deterrence is the car's free-flow time,
    where public transport's would be its own impedance (walk, wait, ride, transfers)."""
    demand = np.full((n_zones, n_zones), trips / (n_zones * (n_zones - 1)))
    np.fill_diagonal(demand, 0.0)
    return demand

# Period 1 is the whole-day default AequilibraE creates, so the modelled one is 2.
PERIOD_ID = 2


class TransitModel:
    def __init__(self, settings, inputs, paths, scenario=None, baseline=None, options=None,
                 compare_to=None):
        """`scenario` is a loaded design file and `baseline` the TransitPaths of the baseline's
        simulation, whose demand it reuses - None for the default baseline itself, which builds
        it. `options` what it runs (transit/options.py): the day, the period, the demand's scale,
        the walking. `compare_to` the baseline's simulation on the same options, which its log
        compares it with."""
        self.s = settings
        self.inputs = inputs
        self.paths = paths
        self.scenario, self.baseline, self.compare_to = scenario, baseline, compare_to
        self.options = options or Options()
        self.lines, self.colors, self.changes = inputs.LINES, inputs.LINE_COLORS, []
        if scenario:
            self.lines, self.colors, self.changes = scenarios.apply(
                scenario, inputs.LINES, inputs.LINE_COLORS)

    def run(self, rebuild_network=False):
        s, inp, paths = self.s, self.inputs, self.paths
        started = time.time()
        # What it runs, said against the city's defaults - before they are replaced by it.
        self.simulated = self.options.record(s, inp.SERVICE_DAY, inp.CALENDAR)
        options = self.options.apply(s)
        paths.prepare_outputs()
        # The GTFS importer logs one DEBUG line per trip saved - about 1,600 here. Warnings and
        # errors still come through; the full history is in the project's aequilibrae.log.
        logging.getLogger("aequilibrae").setLevel(logging.WARNING)
        print(f"Cache:   {paths.street_network}\nOutput:  {paths.output}")
        print(f"Simulating: {self.simulated['said']}")
        if self.scenario:
            report.section(f"The design: {self.scenario['label']}")
            if self.scenario["description"]:
                print(self.scenario["description"] + "\n")
            for line in self.changes:
                print(f"  - {line}")
            print(f"\nCompared with the baseline in {self.baseline.output}")

        report.section("A1. The project, on the streets from OpenStreetMap")
        project = open_street_project(paths.street_network, paths.project, inp.BBOX,
                                      f"{inp.LABEL} (transit study box)", rebuild=rebuild_network)

        report.section("A3. The zones")
        # The road model's zones: the city's own, those inside the study box the streets cover.
        polygons, self.road_zone_numbers = road_zones(project, paths.city, inp.BBOX)
        n_zones = len(polygons)

        report.section("A4. The modelled period")
        period_hours = declare_period(project, PERIOD_ID, s.PERIOD_START_H, s.PERIOD_END_H)

        report.section("A5. The GTFS feed")
        start_h, end_h = inp.SERVICE_HOURS
        # The buses' way along the streets, the feed's shapes: the map matching's guide.
        from .streets import line_paths, streets_for
        along = line_paths(self.lines, streets_for(paths.street_network),
                           s.MATCHED_ROUTE_TYPES)
        project.activate()     # reading the streets opens and closes their own project

        counts = write_gtfs(paths.gtfs, self.lines, inp.AGENCY, inp.CALENDAR, start_h * 3600,
                            end_h * 3600, colors=self.colors,
                            shapes={k: v["path"] for k, v in along.items()},
                            leg_km={k: v["leg_km"] for k, v in along.items()})
        print(f"Wrote {paths.gtfs}")
        for name, n in counts.items():
            print(f"  {name:<16} {n:>6,} rows")
        stations = declared_station_names(self.lines)
        print(f"\n{len(stations)} stations declared: {', '.join(stations)}")
        print("Stops that are close but not one station are joined by a walking transfer in B2.")
        wide = wide_stations(self.lines, s.MAX_STATION_SPREAD_M)
        if len(wide):
            print(f"\nWARNING: {len(wide)} station(s) group platforms more than "
                  f"{s.MAX_STATION_SPREAD_M} m apart. That is a walk between corridors, not an "
                  f"interchange:")
            print(wide.to_string(index=False))
        else:
            print(f"Every interchange keeps its platforms within {s.MAX_STATION_SPREAD_M} m, so "
                  f"all are credible station transfers.")

        report.section("A6. The import, map-matched onto the streets")
        transit = self._import(project, paths, inp, s)
        one_way = one_way_stops(transit)
        if len(one_way):
            print(f"\n{len(one_way)} stop(s) are served in one direction only - a passenger cannot "
                  f"make the return trip from them:")
            print(one_way[["shortname", "name", "directions_served", "route_directions"]]
                  .head(15).to_string(index=False))
            if len(one_way) > 15:
                # A real feed's lines stop on each side of the street: every stop is one way.
                print(f"... and {len(one_way) - 15} more")
        else:
            print("\nEvery stop is served in both directions.")
        unmatchable = unmatchable_stops(project, transit, s.MATCH_RADIUS_M, s.MATCHED_ROUTE_TYPES)
        if len(unmatchable):
            print(f"\nWARNING: {len(unmatchable)} stop(s) are more than {s.MATCH_RADIUS_M} m from "
                  f"any transit-mode link, so every pattern calling at them fails to map-match:")
            print(unmatchable.round(1).to_string(index=False))
            print("Move the stop onto its corridor, or accept the straight-line shape for those "
                  "routes.")
        else:
            print(f"\nEvery matched-route stop is within {s.MATCH_RADIUS_M} m of a street - "
                  f"map matching had a usable anchor everywhere.")

        report.section("A7. The demand")
        demand = uniform_demand(n_zones, options.trips)
        print(f"A uniform matrix: {options.trips:,.0f} trips in the period, shared evenly among "
              f"the {n_zones * (n_zones - 1):,} pairs of different zones - "
              f"{demand[0, 1]:.3f} trips each.")
        print("Not the road model's matrix: its gravity model's deterrence is the car's free-flow "
              "time, where public transport's would be its own impedance - walk, wait, ride, "
              "transfers. A demand model for public transport is not implemented yet.")

        report.section("B2. The transit graph")
        net = TransitNetwork(project, transit, paths, s, PERIOD_ID)
        net.save_graph_configuration()
        net.prepare_walk_transfers()          # routes the streets: a moment
        graph = net.build_graph()
        self.describe_graph(net, graph)

        report.section("B3. Who can reach the network")
        coverage = transit_coverage(net, graph, n_zones)
        n_served = int(coverage["served"].sum())
        print(f"{n_served} of {n_zones} zones are within walking distance of a stop "
              f"({100 * n_served / n_zones:.0f}%).")
        print(assignable_share(coverage, demand))
        walks = coverage.loc[coverage["served"], "nearest_stop_min"]
        print(f"\nWalk to the nearest stop, served zones: median {walks.median():.0f} min, "
              f"worst {walks.max():.0f} min.")
        print("The walks start at each zone's middle - the road model's centroid - so a big "
              "zone's are longer than its residents' would be.")
        unserved = list(coverage.index[~coverage["served"]])
        print(f"\n{len(unserved)} zones have no stop within walking distance"
              + (f": {', '.join(str(z) for z in unserved[:15])}, ..." if len(unserved) > 15
                 else f": {', '.join(str(z) for z in unserved)}" if unserved else "."))

        label = self.scenario["label"] if self.scenario else "baseline"
        report.section(f"B4. The assignment{': ' + label if self.scenario else ''}")
        baseline = solve_transit(net, graph, demand, period_hours, label)
        summarise(baseline)
        print("\nBusiest rides (passengers in the modelled period):")
        print(busiest_rides(baseline.segments).to_string(index=False))

        if self.compare_to is not None:
            report.section("B4b. Against the baseline")
            print(f"The baseline's simulation on the same options: {self.compare_to.output}\n")
            compare.print_comparison(self.compare_to.output, baseline)
            compare.print_top_changes(compare.segment_changes(self.compare_to.output, baseline))

        report.section("B5. The maps")
        kit = self.draw_maps(net, coverage, baseline)

        report.section("B6. Where the network is busy regardless of demand")
        structural_check(net, net.build_graph(), baseline, period_hours, n_zones)

        report.section("B7. What the run writes out")
        ex = Exporter(paths.exports)
        export.zones_layer(ex, net.zones(), coverage, demand)
        export.segments_table(ex, baseline.segments)
        export.segments_layer(ex, baseline.segments, kit.metre_crs)
        export.stops_table(ex, baseline.stops)
        export.skims_table(ex, baseline)
        if self.baseline is None:
            # What every other simulation reads back as its demand, exactly - the CSVs are rounded.
            np.save(os.path.join(paths.exports, "demand.npy"), demand)
            ex.written("demand.npy")
        ex.written("gtfs_feed.zip")
        ex.assumptions(s.ASSUMED)
        ex.total()

        report.section("The assumptions")
        s.ASSUMED.print()
        project.close()
        design = self.scenario or {"name": BASELINE, "label": "baseline", "description": ""}
        export.write_summary(paths.summary, inp.LABEL, paths.city, design, self.changes,
                             baseline, started, self.simulated, self.operations(along, options))
        from core import viewer
        page = viewer.build(paths.output)       # its results page, and the list of simulations
        print(f"\nDone. Maps in {paths.maps}, exports in {paths.exports}")
        print(f"Results page: {page}")

    def _import(self, project, paths, inp, s):
        """The feed imported (project.import_feed), then each line's places per vehicle written
        over AequilibraE's default for its route type - what the capacity figures count."""
        import sqlite3
        transit = import_feed(project, paths.gtfs, inp.AGENCY["agency_name"],
                              inp.FEED_DESCRIPTION, self.simulated["date"], s.MATCHED_ROUTE_TYPES)
        default = getattr(inp, "DEFAULT_CAPACITY", {})
        modes = {0: "tram", 1: "metro", 2: "rail", 3: "bus"}
        restored = self._restore_names(paths)
        if restored:
            print(f"{restored} stop and route names given back their accents (the importer "
                  f"keeps ASCII only)")
        with sqlite3.connect(paths.transit_db) as db:
            for line in self.lines.values():
                places = line.get("capacity") or default.get(modes.get(line["route_type"]))
                if places:
                    db.execute("UPDATE routes SET total_capacity = ? WHERE shortname = ?",
                               (int(places), line["short"]))
        print("Places per vehicle: " + ", ".join(
            f"{line['short']} {line.get('capacity') or default.get(modes.get(line['route_type']), 'default')}"
            for line in self.lines.values()))
        return transit

    @staticmethod
    def _restore_names(paths):
        """The feed's names written back over the imported ones: AequilibraE's GTFS reader drops
        every character outside ASCII ("Avenida São Paulo" -> "Avenida So Paulo"). The ids stay
        as imported. Returns how many names changed."""
        import csv
        import io
        import sqlite3
        import zipfile

        def ascii_of(text):
            return text.encode("ascii", errors="ignore").decode().strip()

        names = {"stops": {}, "routes": {}}
        with zipfile.ZipFile(paths.gtfs) as feed:
            for table, columns in (("stops", ["stop_name"]),
                                   ("routes", ["route_short_name", "route_long_name"])):
                rows = csv.DictReader(io.TextIOWrapper(feed.open(f"{table}.txt"),
                                                       encoding="utf-8-sig"))
                for row in rows:
                    for column in columns:
                        text = (row.get(column) or "").strip()
                        if text and ascii_of(text) != text:
                            names[table][ascii_of(text)] = text
        changed = 0
        with sqlite3.connect(paths.transit_db) as db:
            for table, columns in (("stops", ["name"]), ("routes", ["shortname", "longname"])):
                for plain, text in names[table].items():
                    for column in columns:
                        changed += db.execute(f"UPDATE {table} SET {column} = ? WHERE {column} = ?",
                                              (text, plain)).rowcount
        return changed

    def operations(self, along, options):
        """What the design takes to run on the day simulated (transit/fleet.py): vehicles by
        mode, vehicle-km and vehicle-hours - for the comparison of simulations."""
        from .fleet import operations
        from .gtfs import directions
        s, inp = self.s, self.inputs
        start_h, end_h = inp.SERVICE_HOURS
        modes = {0: "tram", 1: "metro", 2: "rail", 3: "bus"}
        out = {"day": options.day, "vehicles": {}, "vehicle_km": 0.0, "vehicle_hours": 0.0}
        for key, line in self.lines.items():
            n = len(directions(line))
            found = all((key, d) in along for d in range(n))
            lengths = [along[(key, d)]["km"] for d in range(n)] if found else None
            leg_km = [along[(key, d)]["leg_km"] for d in range(n)] if found else None
            o = operations(line, start_h * 3600, end_h * 3600, s.LAYOVER_SHARE, s.LAYOVER_MIN_S,
                           lengths, leg_km).get(options.day)
            if not o:
                continue                                # no service that day
            mode = modes.get(line["route_type"], str(line["route_type"]))
            out["vehicles"][mode] = out["vehicles"].get(mode, 0) + o["vehicles"]
            out["vehicle_km"] += o["vehicle_km"]
            out["vehicle_hours"] += o["vehicle_hours"]
        out["vehicle_km"], out["vehicle_hours"] = (round(out["vehicle_km"], 1),
                                                   round(out["vehicle_hours"], 1))
        return out

    @staticmethod
    def describe_graph(net, graph):
        """What the graph is made of, and what the map matching bought."""
        from aequilibrae.utils.geo_utils import metre_crs_for_gdf

        print(f"\nTransit graph: {len(graph.vertices):,} vertices, {len(graph.edges):,} edges.\n")
        summary = graph.edges.groupby("link_type").agg(
            edges=("link_id", "count"),
            mean_seconds=("trav_time", "mean"),
            waits_for_a_vehicle=("freq", lambda f: bool(np.isfinite(f).any())),
        ).round(1)
        print(summary.to_string())
        print("\nVertex types:", graph.vertices.node_type.value_counts().to_dict())

        seg = net.segments(matched=True)
        matched = seg.attrs["matched_segments"]
        straight = gpd.GeoSeries([LineString([g.coords[0], g.coords[-1]]) for g in seg.geometry],
                                 crs="EPSG:4326")
        straight_m = straight.to_crs(metre_crs_for_gdf(seg)).length.to_numpy()
        detour = 100 * (seg["distance"].to_numpy() / straight_m - 1)
        print(f"\n{matched} of {len(seg)} segments drawn on their matched street path "
              f"(the rest are straight lines: the metro is in a tunnel).")
        longer = detour[detour > 0.5]
        if len(longer):
            print(f"Following the streets makes a matched segment {longer.mean():.0f}% "
                  f"longer than the straight line between its stops.")

    def draw_maps(self, net, coverage, baseline):
        """The simulation's maps - its loads, the capacity they use, who can reach the network -
        each drawn from plain frames, which map_data/ keeps for a redraw. The lines themselves
        are the design's maps (transit/design.py). Returns the map kit, whose metre CRS the
        exports use too."""
        from aequilibrae.utils.geo_utils import metre_crs_for_gdf

        stops = net.stops()
        kit = MapKit(metre_crs_for_gdf(stops), self.paths.maps)
        zones = net.zones().merge(coverage.reset_index(), on="zone_id", how="left")
        maps.map_coverage(kit, zones, net.segments(), stops, len(self.lines))

        maps.map_loads(kit, baseline.segments, baseline.stops, baseline.label,
                       baseline.boardings, baseline.boarded_demand, baseline.journey_time,
                       self.colors)
        maps.map_capacity(kit, baseline.segments, baseline.stops)
        return kit
