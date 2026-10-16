"""The run, step by step. What every city does is here; what only one city does is a hook.

    A-D  inputs and zones                  prepare()                    the city's own
    E0   road network, downloaded once     network_outline()            shared, outline from city
    E1   non-roads dropped, OSM tags fixed after_network()              shared, hook after
    E2   zones into the model              reserved_centroids()         shared
    E3   speed, capacity, roundabouts      travel_share()               shared
    E4   skim                              zone_system()                shared default; a city
                                                                        may add external zones
    E5   demand                            build_demand()               the city's own; the
                                                                        gravity model is shared
    E6   assignment and its reading        after_assignment()           shared, hook after
    E7   maps after the assignment         extra_maps()                 the city's own
    E8   delay                                                          shared
    E9   exports                           export()                     shared files + city's
    F    checks against observations       validate()                   the city's own
    -    summary.json, the main maps,                                   shared
         the results page

A city subclasses `CityModel` and fills in the hooks; `run()` calls them in this order.

**Internal and external zones.** A city's own zones - inside its limit - are numbered 1..n
(`n_internal`); a city with traffic from beyond the limit adds external zones after them, each
standing for where a road crosses the limit (Sorocaba: cases/sorocaba/external.py; Quito has
none). Everything shared works with none or any number of them: `is_internal` says which zone is
which, and every trip falls in one of four groups (summary.TRIP_GROUPS) - within the city, from
it out, from outside in, or through. Figures over the whole network (vehicle-hours, delay) count
every trip; figures about trips (travel times, distances) count those within the city, and say so.
"""
import os
import sys
import time

import numpy as np
import pandas as pd

from . import report, steps, summary, timeofday, viewer
from .assignment import Assigner, conservation, delay_report, describe_load, flow_table
from .connectors import add_connectors_where_needed, load_zones
from .costs import set_link_costs, set_roundabout_capacity
from .export import Exporter
from .maps import MapKit, draw_main_maps
from .network import (build_road_network, describe_network, drop_non_car_links,
                      repair_from_osm_tags)
from .skim import skim_zones


class CityModel:
    label = "the city"
    # Maps a city draws in step 1 (prepare), kept with it when a run takes the baseline's step 1,
    # and the one showing what attracts trips, beside the attraction rates on the run page.
    step1_maps = []
    attraction_map = None

    def __init__(self, settings, paths):
        self.s = settings
        self.paths = paths
        self.metre_crs = None
        self.zones = None          # one row per internal zone: zone, zone_number, centroid, pop
        self.boundary = None       # the city outline, as a GeoDataFrame
        self.maps = None
        # A named run (core/runs.py): its name, label, description and {parameter: the value it
        # replaced}; run.py sets it. None is the baseline, the settings as they are.
        self.run_info = None
        # Files a run loads instead of computing (core/runs.py): {"zoning": {"path", "name",
        # "id_column"}, "od_matrix": {"path", "name"}}; run.py sets it.
        self.inputs = {}
        self.staged = False          # one step of a run, in a process of its own
        self.demand_loaded = False
        self.demand_transformed = False   # another day or hour than the base matrix
        # A scenario (core/runs.py): the run it is made from, and its edits to the network
        # (core/edits.py); run.py sets them. None and [] for a run.
        self.base_run = None
        self.unrouted = None          # a closure's O-D pairs with no route left: not assigned
        self.unrouted_said = None     # ... how many trips, and the zones cut off
        self.edits = []

    # --- hooks ---------------------------------------------------------------------------------
    def prepare(self):
        """Read the inputs and build the zones: set metre_crs, zones, boundary and maps."""
        raise NotImplementedError

    def network_outline(self):
        """The area to download the network for, as a polygon in metres."""
        raise NotImplementedError

    def after_network(self, road):
        """Anything read from the cached network before the zones go in."""

    def reserved_centroids(self):
        """Node ids kept free for centroids: the internal zones, and any external ones."""
        return len(self.zones)

    def travel_share(self):
        """Each zone's share of the city's travel, by zone number, for the extra connectors."""
        raise NotImplementedError

    def zone_system(self):
        """The skim the demand is built on: minutes, km and the zone order.

        By default the internal zones alone; a city with external zones adds them here."""
        zone_list = np.array(sorted(self.zones["zone_number"]))
        return skim_zones(self.model, zone_list, self.n_internal, self.s.INTRAZONAL_SHARE,
                          strict=self.s.STRICT_SKIM)

    def build_demand(self):
        """The full vehicle-trip matrix, in the order of `self.all_zones`."""
        raise NotImplementedError

    def after_assignment(self):
        """City checks on the assigned network."""

    def extra_maps(self):
        """Maps only this city draws after the assignment."""

    def caveats(self):
        """What the model does and does not capture, printed near the end."""

    def export(self, ex):
        """The zones file and any file only this city writes."""
        raise NotImplementedError

    def validate(self, ex):
        """Checks against observations, after the exports."""

    def describe_trip_groups(self):
        """The matrix by where its trips go against the city limit."""
        groups = summary.trip_groups(self.demand, self.is_internal)
        total = sum(groups.values()) or 1.0
        n_external = int((~self.is_internal).sum())
        print(f"\nThe trips against the city limit ({self.n_internal} zones inside"
              + (f", {n_external} external):" if n_external else
                 ", no external zones - traffic from beyond the limit is not modelled):"))
        for key, label, _, _ in summary.TRIP_GROUPS:
            if groups[key] or key == "within":
                print(f"  {label:<28} {groups[key]:>10,.0f}  {100 * groups[key] / total:5.1f}%")

    # --- the run -------------------------------------------------------------------------------
    def run(self, rebuild_network=False, step=None):
        """The three steps (core/steps.py) in one go, or `step` alone - after the steps before it,
        done with what the run says now, which it reads back."""
        values, groups = steps.registry_values(self.s)
        self.fingerprints = {k: steps.fingerprint(values, groups, k, self.inputs, self.edits)
                             for k in steps.STEPS}
        if step:
            steps.require(self, step, self.fingerprints)
        self.staged = step is not None
        self.describe_run()
        # A step computed in another process - or taken from another run - is read back before
        # the next one.
        read_back = self.staged
        for name in ([step] if step else steps.STEPS):
            started = time.time()
            if name != "assignment" and (self.staged or self.edits) and self.reuse(name):
                read_back = True
                continue
            if read_back and name != "zones":
                steps.load_state(self, steps.STEPS[steps.STEPS.index(name) - 1])
            read_back = False
            preview = getattr(self, f"step_{name}")(rebuild_network)
            if name != "assignment":
                steps.save_state(self, name)
            steps.finish(self, name, started, self.fingerprints, preview)
            if name == "assignment":
                self.publish()

    def describe_run(self):
        s, paths, info = self.s, self.paths, self.run_info
        print(f"Data:    {paths.input}\nCache:   {paths.cache}\nOutput:  {paths.output}")
        if info and info["name"] != "baseline":
            print(f"Run:     {info['label']} ({info['name']})"
                  + (f" - {info['description']}" if info["description"] else ""))
            if self.base_run:
                print(f"         a scenario of {self.base_run}: its parameters and files, "
                      f"{len(self.edits)} edit(s) to the network")
            for name, was in info["changes"].items():
                entry = s.ASSUMED.entries.get(name) or s.ASSUMED.settings.get(name) or {}
                print(f"         {name} = {entry.get('value')}   (settings.py: {was})")
        for key, what in (("zoning", "zoning file"), ("od_matrix", "O-D matrix")):
            if (self.inputs or {}).get(key):
                print(f"Loaded:  {what} {self.inputs[key]['name']}")

    def reuse(self, step):
        """`step` copied from a run that computed it exactly as this run would - a scenario's
        base, or the city's baseline - instead of computed again (core/steps.reuse)."""
        from .runs import BASELINE, output_dir
        donors = ([self.base_run] if self.base_run else []) + [BASELINE]
        if step == "zones":
            self.paths.prepare_outputs()
        self.forget_results()
        for donor in dict.fromkeys(donors):
            if steps.reuse(self, step, output_dir(self.paths.city, donor), self.fingerprints):
                report.section("E0-E4. The zones and the network" if step == "zones"
                               else "E5. The demand")
                print(f"Taken as {donor} computed it - the same "
                      f"{'zones and network' if step == 'zones' else 'parameters and files'} - "
                      f"not computed again.")
                return True
        return False

    def forget_results(self):
        """The results of an earlier run, gone before a step computes what they came from."""
        for stale in ["summary.json", "index.html"] + (["run_log.txt"] if self.staged else []):
            path = os.path.join(self.paths.output, stale)
            if os.path.exists(path):
                os.remove(path)

    # --- step 1: the zones and the network ------------------------------------------------------
    def step_zones(self, rebuild_network=False):
        s, paths = self.s, self.paths
        paths.prepare_outputs()
        self.forget_results()

        self.prepare()
        self.n_internal = len(self.zones)

        report.section("E0. The road network")
        road = build_road_network(paths.road_network, self.network_outline(), self.metre_crs,
                                  self.label, rebuild=rebuild_network)
        describe_network(road)

        report.section("E1. Links that are not roads")
        drop_non_car_links(road, s.NOT_ROADS)
        if s.REPAIR_OSM_TAGS:
            report.section("E1b. What the importer leaves out")
            repair_from_osm_tags(road, paths.road_network)
        self.after_network(road)
        road.close()          # release the cached project before copying it

        report.section("E2. The zones inside the model")
        self.model = load_zones(paths.road_network, paths.road_model, self.zones,
                                self.reserved_centroids(), s, self.metre_crs)

        report.section("E3. Speed, capacity and free-flow time")
        set_link_costs(self.model, s)
        print("\nRoundabouts:")
        set_roundabout_capacity(self.model)
        print("\nAn extra way in for the zones that need one:")
        add_connectors_where_needed(self.model, self.travel_share(), s, self.metre_crs)

        report.section("E4. How far every zone is from every other")
        self.cost, self.distance_km, self.all_zones = self.zone_system()
        self.is_internal = self.all_zones <= self.n_internal
        self.model.close()
        steps.snapshot_project(paths)         # what the assignment starts from
        return self.preview_zones()

    def preview_zones(self):
        """Step 1's preview: the zones map, the list of zones a matrix is written against, and
        the numbers a zoning is judged by."""
        kit = MapKit(self.metre_crs, self.paths.maps)
        kit.map_zones(self.zones)
        zone_list = self.zone_list()
        os.makedirs(self.paths.exports, exist_ok=True)
        zone_list.to_csv(os.path.join(self.paths.exports, "zone_list.csv"), index=False)
        inside = self.is_internal
        free = self.cost[np.ix_(inside, inside)]
        free = free[np.isfinite(free) & ~np.eye(len(free), dtype=bool)]
        pop = self.zones["pop"]
        lines = [["zones", f"{self.n_internal:,}" + (f" + {int((~inside).sum())} external"
                                                     if (~inside).any() else "")],
                 ["people", f"{pop.sum():,.0f}"]]
        if "jobs" in self.zones:
            lines.append(["jobs", f"{self.zones['jobs'].sum():,.0f}"])
        lines += [["people per zone", f"median {pop.median():,.0f}, from {pop.min():,.0f} to "
                                      f"{pop.max():,.0f}"],
                  ["zones without people", f"{int((pop <= 0).sum())}"],
                  ["between two zones, on empty streets", f"median {np.median(free):.1f} min, "
                                                          f"90% under {np.quantile(free, 0.9):.1f}"]]
        if getattr(self, "zoning_report", None):
            lines += self.zoning_report
        # Plain numbers for the demand step's summary: what trip generation multiplies.
        values = {"zones": int(self.n_internal), "external": int((~inside).sum()),
                  "people": float(pop.sum())}
        for col in ("jobs", "households"):
            if col in self.zones:
                values[col] = float(self.zones[col].sum())
        return {"lines": lines, "maps": ["zones.html"], "files": ["exports/zone_list.csv"],
                "values": values}

    def zone_list(self):
        """Every zone of the matrix: its number, code, and for a loaded zoning the id it had in
        the file - what a loaded matrix may name it by - with its kind and people."""
        z = self.zones
        out = pd.DataFrame({"zone_number": z["zone_number"].to_numpy(), "zone": z["zone"].to_numpy(),
                            "file_id": z["file_id"].to_numpy() if "file_id" in z else "",
                            "kind": "internal", "pop": z["pop"].round(0).to_numpy()})
        ext = getattr(self, "external_zones", None)
        if ext is not None and len(ext):
            out = pd.concat([out, pd.DataFrame({
                "zone_number": ext["zone_number"].to_numpy(),
                "zone": ext["label"].to_numpy() if "label" in ext else "",
                "file_id": "", "kind": "external", "pop": np.nan})], ignore_index=True)
        return out.sort_values("zone_number")

    # --- step 2: the demand ----------------------------------------------------------------------
    def step_demand(self, rebuild_network=False):
        self.forget_results()
        report.section("E5. Trips: generation and distribution")
        # A zone's time to itself is the gravity model's choice: set here, not in step 1's skim.
        from .skim import with_intrazonal
        self.cost = with_intrazonal(self.cost, self.s.INTRAZONAL_SHARE)
        print(f"intrazonal time: {self.s.INTRAZONAL_SHARE} of the time to the nearest zone")
        loaded = (self.inputs or {}).get("od_matrix")
        self.demand_transformed = False
        if loaded:
            from .odfile import read_matrix
            print(f"The matrix is loaded, not modelled: {loaded['name']}")
            self.demand = read_matrix(loaded["path"], self.zone_list(), self.all_zones)
            self.demand_loaded = True
        else:
            self.demand = self.build_demand()
            self.demand_loaded = False
        self.day_and_hour()
        if self.demand_loaded and not self.demand_transformed:
            self.demand_replaced()
        self.describe_trip_groups()
        return self.preview_demand()

    def weights(self, name):
        """A pull weight for the day modelled: on a weekend day WEEKEND_<name> where the city
        has one (shops and leisure pull harder, workplaces and schools less), else <name>. The
        gravity model then finds the beta for them that gives MEAN_TRIP_MIN, as on a weekday."""
        if self.s.DAY == "weekend" and hasattr(self.s, f"WEEKEND_{name}"):
            return getattr(self.s, f"WEEKEND_{name}")
        return getattr(self.s, name)

    def day_and_hour(self):
        """E5b. The day and the time of day (core/timeofday.py): the run's matrix from the
        morning peak just built - the model's, with the day's weights, or a loaded one."""
        s = self.s
        timeofday.check(s)
        report.section(f"E5b. From the morning peak to {timeofday.label(s)}")
        base = self.demand
        self.demand = timeofday.apply(base, s)
        timeofday.describe(s, base, self.demand)
        self.demand_transformed = not timeofday.is_base(s)
        if self.demand_transformed:
            self.demand_replaced()

    def demand_replaced(self):
        """Anything later steps read from a city's own demand model, worked out again from the
        matrix the run assigns - a loaded one, or another day's or hour's."""

    def preview_demand(self):
        """Step 2's preview: the trips, where they go against the city limit, how long they are
        on empty streets, and the trip ends map."""
        demand, inside = self.demand, self.is_internal
        groups = summary.trip_groups(demand, inside)
        total = sum(groups.values()) or 1.0
        within = demand[np.ix_(inside, inside)]
        cost = self.cost[np.ix_(inside, inside)]
        ok = np.isfinite(cost)
        mean = (within[ok] * cost[ok]).sum() / max(within[ok].sum(), 1e-9)
        lines = [["modelled", summary.modelled(self)],
                 [f"vehicle trips in {timeofday.unit(self.s)}",
                  f"{total:,.0f}"]]
        lines += [[label, f"{groups[key]:,.0f} ({100 * groups[key] / total:.1f}%)"]
                  for key, label, _, _ in summary.TRIP_GROUPS if groups[key] or key == "within"]
        lines.append(["average trip within the city, empty streets", f"{mean:.1f} min"])
        rows, cols = np.nonzero(demand)
        od = pd.DataFrame({"origin": self.all_zones[rows], "destination": self.all_zones[cols],
                           "trips": demand[rows, cols]})
        MapKit(self.metre_crs, self.paths.maps).map_trip_ends(self.zones, od)
        return {"lines": lines, "maps": ["trip_ends.html"], "groups": groups}

    # --- step 3: the assignment ------------------------------------------------------------------
    def step_assignment(self, rebuild_network=False):
        s, paths = self.s, self.paths
        self.forget_results()
        self.model = steps.restore_project(paths)
        # The day or hour the matrix holds (core/timeofday.py) - a loaded matrix's too: it is a
        # morning peak hour's, turned into the run's day and period like the model's.
        factor = timeofday.capacity_factor(s)
        period = f"{timeofday.unit(s)} ({timeofday.label(s)})"
        closed = []
        from .demand_edits import KINDS as DEMAND_KINDS
        on_network = [e for e in self.edits if e["kind"] not in DEMAND_KINDS]
        on_demand = [e for e in self.edits if e["kind"] in DEMAND_KINDS]
        if on_network:
            from . import edits as network_edits
            report.section(f"E5c. The scenario's edits to the network (made from {self.base_run})")
            network_edits.describe(self.model, on_network)
            closed = network_edits.apply(self.model, on_network)
            print("The demand is the base's, as it is: the edits change routes, not destinations.")
        if on_demand:
            from . import demand_edits
            report.section(f"E5c. The scenario's edits to the demand (made on {self.base_run}'s)")
            demand_edits.apply(self, on_demand)
            self.demand_replaced()              # what the gateway check reads, from the new matrix
            print("The network is the base's, as it is: the edits change the trips.")
        report.section(f"E6. The assignment: {period}")
        self.assigner = Assigner(self.model, self.all_zones, s, closed=closed)
        if closed:
            from .edits import cut_off
            lost, stranded, self.unrouted = cut_off(self.assigner, self.demand, self.all_zones)
            self.unrouted_said = {"trips": lost, "zones": stranded}
            if lost:
                print(f"WARNING: the closures leave {lost:,.0f} trips without a route - not "
                      f"assigned, so missing from the results"
                      + (f"; zones cut off: {', '.join(map(str, stranded[:12]))}" if stranded
                         else ""))
            else:
                print("Every trip still has a route with the closures.")
        self.results = self.assigner.solve(self.demand, capacity_factor=factor)
        self.congested = self.assigner.congested_minutes(
            self.cost, self.results, self.is_internal,
            faster_allowed=any(e["kind"] in ("speed", "capacity", "road") for e in self.edits))
        inside = np.ix_(self.is_internal, self.is_internal)
        trips = self.demand[inside]
        ok = np.isfinite(self.congested[inside])
        print(f"average trip within the city: {(trips * self.cost[inside]).sum() / trips.sum():.1f}"
              f" min on empty streets, {(trips[ok] * self.congested[inside][ok]).sum() / trips[ok].sum():.1f}"
              f" min on the loaded network")
        self.flows, self.links = flow_table(self.model, self.results, factor)
        conservation(self.flows, self.demand, self.all_zones, self.unrouted)
        self.load = describe_load(self.flows, period=period)
        self.after_assignment()

        report.section("E7. Maps after the assignment")
        self.extra_maps()

        report.section("E8. Delay, and what it comes to over a year")
        delay_report(self.load, self.demand.sum(), s, period=period,
                     yearly=not self.demand_transformed)
        self.caveats()

        report.section("E9. What the run writes out")
        ex = Exporter(paths.exports)
        self.export(ex)
        ex.link_volumes(self.model, self.load["loaded"])
        ex.layer(self.boundary.to_crs("EPSG:4326"), "city_limit.gpkg", "city_limit")
        ex.assumptions(s.ASSUMED)
        ex.total()

        self.validate(ex)

        report.section("The assumptions")
        s.ASSUMED.print()
        self.model.close()
        return {"lines": [], "maps": []}

    def publish(self):
        """After the assignment: the summary, the main maps, the run's log whole, and its page."""
        paths = self.paths
        status = steps.read_status(paths.output)
        summary.write(self, sum(status[k]["minutes"] for k in steps.STEPS if k in status))
        report.section("The zones and simulation maps, from the exports")
        draw_main_maps(paths.output)
        if self.staged:
            sys.stdout.flush()
            steps.join_logs(paths)
        page = viewer.build(paths.output)
        print(f"\nDone. Maps in {paths.maps}, exports in {paths.exports}")
        print(f"Results page: {page}")
        status["assignment"]["preview"] = {
            "lines": [list(line) for line in (summary.read(paths.output) or {}).get("headline", [])],
            "maps": ["simulation.html"], "page": "index.html"}
        steps.write_status(paths.output, status)
