"""The baseline assignment and what the network looks like carrying it.

Drivers take the quickest route, their choices slow those routes down, and the solver iterates
until no one can do better by switching. The delay comes from **BPR**.

Volume over capacity is a **per-direction** figure - adding both flows and dividing by one
direction's capacity would roughly double it on every two-way street - and a street is filed
under its busier direction.
"""
import numpy as np
import pandas as pd

CAR_AB, CAR_BA = "car_ab", "car_ba"      # result columns are named after the traffic class
NOT_STREETS = ["centroid_connector", "external_access"]


class Assigner:
    """User-equilibrium assignment over one zone system (`zones`, the skim's order)."""

    def __init__(self, project, zones, s, closed=()):
        """`closed`: links a scenario closes (core/edits.py) - out of this graph and the loaded
        skim's, so nothing routes over them."""
        self.project, self.zones, self.s = project, np.asarray(zones), s
        self.closed = list(closed)
        project.network.build_graphs(modes=["c"])
        self.graph = project.network.graphs["c"]
        self._prepare(self.graph)
        self.graph.set_graph("travel_time")
        self.graph.set_skimming(["travel_time"])

    def _prepare(self, graph):
        graph.prepare_graph(self.zones)
        graph.set_blocked_centroid_flows(True)        # no routing *through* a zone's connector
        if self.closed:
            graph.exclude_links(self.closed)          # prepares the graph again, without them

    def as_matrix(self, array, name="car"):
        """Wrap a zone-by-zone array as the demand matrix the solver reads."""
        from aequilibrae.matrix import AequilibraeMatrix
        holder = AequilibraeMatrix()
        holder.create_empty(zones=array.shape[0], matrix_names=[name], memory_only=True)
        holder.index[:] = self.zones
        holder.matrices[:, :, 0] = array
        holder.computational_view([name])
        return holder

    def solve(self, array, label="baseline", capacity_factor=1.0):
        """One user-equilibrium assignment; the link results table. `capacity_factor` F turns a
        link's hourly capacity into the period's - a whole day's matrix is assigned against
        capacity x F (core/timeofday.py); the network itself is not changed."""
        from aequilibrae.paths import TrafficAssignment, TrafficClass
        s = self.s
        capacity = "capacity"
        if capacity_factor != 1:
            capacity = "capacity_period"
            self.graph.graph[capacity] = self.graph.graph["capacity"] * capacity_factor
            print(f"capacity x {capacity_factor:.2f}: a day's matrix against its busiest hour "
                  f"repeated all day")
        job = TrafficAssignment()
        job.add_class(TrafficClass(name="car", graph=self.graph, matrix=self.as_matrix(array)))
        job.set_vdf("BPR")
        job.set_vdf_parameters({"alpha": s.BPR_ALPHA, "beta": s.BPR_BETA})
        job.set_capacity_field(capacity)
        job.set_time_field("travel_time")
        job.set_algorithm("bfw")
        job.max_iter = s.MAX_ITER
        job.rgap_target = s.RGAP_TARGET
        job.execute()
        gap, rounds = job.assignment.rgap, job.assignment.iter
        print(f"{label}: relative gap {gap:.2e} after {rounds} iterations")
        # An equilibrium solver slows down as it approaches the answer, so the gap alone does
        # not say whether more iterations would help. The curve does.
        curve = job.report()
        for mark in (1, 5, 10, 25, 50, 100, 200, 250, 400, 700, 1000):
            row = curve.loc[curve["iteration"] == mark, "rgap"]
            if len(row):
                print(f"    after {mark:>4} iterations: {float(row.iloc[0]):.2e}")
        if "warnings" in curve:
            trouble = curve[curve["warnings"].astype(bool) & (curve["warnings"] != "")]
            if len(trouble):
                print(f"  {len(trouble)} iterations reported a problem, first at "
                      f"{int(trouble['iteration'].iloc[0])}: {trouble['warnings'].iloc[0]}")
        if gap > s.RGAP_TARGET:
            print(f"  ** did not reach the {s.RGAP_TARGET:.0e} target; link flows are indicative."
                  f" Raise MAX_ITER to tighten it.")
        return job.results()

    def solve_classes(self, arrays, label):
        """One user-equilibrium assignment of the matrices of `arrays` ({name: zone-by-zone
        array}) together, each a class of its own: the link table with each one's flow
        (`<name>_ab`, `_ba`). Their sum is `solve` of their sum - the same equilibrium - so each
        class's flow is its part of it: where its trips go among everyone else's, not on roads
        it had to itself."""
        from aequilibrae.paths import TrafficAssignment, TrafficClass
        s = self.s
        job = TrafficAssignment()
        for name, array in arrays.items():
            job.add_class(TrafficClass(name=name, graph=self.graph,
                                       matrix=self.as_matrix(array, name)))
        job.set_vdf("BPR")
        job.set_vdf_parameters({"alpha": s.BPR_ALPHA, "beta": s.BPR_BETA})
        job.set_capacity_field("capacity")
        job.set_time_field("travel_time")
        job.set_algorithm("bfw")
        job.max_iter = s.MAX_ITER
        job.rgap_target = s.RGAP_TARGET
        job.execute()
        print(f"{label}: relative gap {job.assignment.rgap:.2e} after {job.assignment.iter} "
              f"iterations")
        return job.results()

    def congested_minutes(self, free_flow, results, internal, faster_allowed=False):
        """Minutes between every pair of zones on the loaded network, after `solve`: each pair's
        quickest route at the final congested link times (`results`, the solver's link table),
        those times summed along it.

        The times go into a graph of their own as a link field, `congested_time_ab` and `_ba`
        beside `travel_time_ab` and `_ba`, before it is prepared: preparing builds the graph from
        those columns and sums them over the compressed network, so a field added afterwards
        would never reach the skim. AequilibraE's own `skim_congested` is not used:
        in 1.6.2 it lays the compressed network's times onto the full one, which puts each
        link's time on another link.

        The diagonal - trips that stay in their zone, which never reach the network - keeps its
        free-flow value from `free_flow`, the skim the demand was built on."""
        self.project.network.build_graphs(modes=["c"])
        g = self.project.network.graphs["c"]
        for side in ("ab", "ba"):
            times = g.network["link_id"].map(results[f"Congested_Time_{side.upper()}"])
            g.network[f"congested_time_{side}"] = times.fillna(g.network[f"travel_time_{side}"])
        self._prepare(g)                     # as in the assignment: no routing through a zone,
        g.set_graph("congested_time")        # nor over a closed link
        g.set_skimming(["congested_time"])
        skims = g.compute_skims().results.skims
        minutes = np.array(skims.matrix["congested_time"], dtype=float).copy()
        order = np.array(skims.index).astype(int)
        # Same check as the free-flow skim: a matrix out of zone order pairs every zone's trips
        # with another zone's times.
        if not np.array_equal(order, self.zones):
            raise ValueError("the congested skim is not in zone order")
        np.fill_diagonal(minutes, np.diag(free_flow))
        # No link is quicker loaded than empty, so no pair inside the city can be either. (An
        # external zone's free-flow time may carry driving the network does not hold.)
        inside = np.ix_(internal, internal)
        faster = int((minutes[inside] < free_flow[inside] - 0.01).sum())
        if faster_allowed:
            # A scenario that raises speeds can make a loaded trip quicker than the base's empty
            # streets, which `free_flow` is: not a sign of times on the wrong links.
            print(f"congested skim: {faster} pairs in the city quicker than on the base's empty "
                  f"streets (the scenario raises speeds)")
            return minutes
        print(f"congested skim: {faster} pairs in the city quicker than on empty streets "
              f"(should be 0)")
        if faster:
            raise ValueError("congested times below free flow: the times are on the wrong links")
        return minutes


def flow_table(project, results, capacity_factor=1.0):
    """The assignment's results joined to the links, with volume over capacity per direction -
    over the period's capacity: the hourly one times `capacity_factor` (a whole day's F)."""
    with project.db_connection as conn:
        links = pd.read_sql(
            "SELECT link_id, a_node, b_node, name, link_type, distance, capacity_ab, capacity_ba, "
            "travel_time_ab, travel_time_ba, lanes_ab, speed_ab, junction FROM links", conn)
    flows = results.rename_axis("link_id").reset_index().merge(links, on="link_id", how="left")
    for side, cap in (("ab", "capacity_ab"), ("ba", "capacity_ba")):
        flows[f"voc_{side}"] = flows[f"car_{side}"].fillna(0) / (
            capacity_factor * flows[cap].replace(0, np.nan))
    flows["voc"] = flows[["voc_ab", "voc_ba"]].max(axis=1)
    flows["flow"] = flows[CAR_AB].fillna(0) + flows[CAR_BA].fillna(0)
    # AequilibraE reports the same ratio itself, so the two must agree.
    gap = np.nanmax(np.abs(flows[["voc_ab", "voc_ba"]].to_numpy()
                           - flows[["VOC_AB", "VOC_BA"]].to_numpy()))
    print(f"our per-direction volume/capacity vs the solver's own: largest difference {gap:.2e}")
    return flows, links


def conservation(flows, demand, zones, unrouted=None):
    """The assignment's own check: the vehicles leaving the zones on their connectors, and those
    reaching them, against the matrix's trips between different zones - less any a closure left
    with no route. Prints both and a WARNING past a thousandth; returns the larger difference,
    as a share of the trips."""
    zones = np.asarray(zones)
    expected = np.array(demand, dtype=float)
    np.fill_diagonal(expected, 0.0)                    # a trip within its zone is not assigned
    if unrouted is not None:
        expected[np.asarray(unrouted)] = 0.0
    ab, ba = flows[CAR_AB].fillna(0), flows[CAR_BA].fillna(0)
    a_zone, b_zone = flows["a_node"].isin(zones), flows["b_node"].isin(zones)
    leaving = float(ab[a_zone].sum() + ba[b_zone].sum())
    reaching = float(ba[a_zone].sum() + ab[b_zone].sum())
    total = float(expected.sum())
    worst = max(abs(leaving - total), abs(reaching - total)) / total if total else 0.0
    print(f"conservation: {leaving:,.1f} vehicles leave the zones and {reaching:,.1f} reach them, "
          f"against {total:,.1f} trips between zones in the matrix - largest difference "
          f"{100 * worst:.4f}%")
    if worst > 1e-3:
        print("WARNING: the assignment does not carry the matrix's trips: "
              f"{100 * worst:.2f}% apart")
    return worst


def vehicle_hours(flows):
    """Congested and free-flow vehicle-hours inside the modelled network.

    External access links stand for the regional drive to a gateway, which is not congested
    here and would only dilute the figure."""
    modelled = flows[flows["link_type"] != "external_access"]
    busy = float((modelled[CAR_AB].fillna(0) * modelled["Congested_Time_AB"].fillna(0)
                  + modelled[CAR_BA].fillna(0) * modelled["Congested_Time_BA"].fillna(0))
                 .sum() / 60)
    free = float((modelled[CAR_AB].fillna(0) * modelled["travel_time_ab"].fillna(0)
                  + modelled[CAR_BA].fillna(0) * modelled["travel_time_ba"].fillna(0))
                 .sum() / 60)
    return busy, free


def describe_load(flows, top=15, period="the peak hour"):
    """How hard the network works: vehicle-hours, V/C bands, busiest and worst streets.

    Returns a dict with what later steps need: streets, loaded, veh_hours, free_hours,
    streets_busy, over."""
    streets = flows[~flows["link_type"].isin(NOT_STREETS)].copy()
    loaded = streets[streets["flow"] > 0]
    busy, free = vehicle_hours(flows)
    print(f"\nvehicle-hours in {period}, inside the modelled network: {busy:,.0f}")
    print(f"  the same trips on empty streets would take {free:,.0f}, "
          f"so congestion adds {100 * (busy / free - 1):.0f}%")
    print(f"streets carrying traffic: {len(loaded):,} of {len(streets):,}")

    print("\nhow hard the loaded streets are working, by their busier direction:")
    km_total = loaded["distance"].sum() / 1000
    for lo, hi, label in [(0, 0.5, "under 50% - free flowing"), (0.5, 0.85, "50-85% - busy"),
                          (0.85, 1.0, "85-100% - at capacity"),
                          (1.0, 1.5, "100-150% - over capacity"),
                          (1.5, 1e9, "over 150% - far beyond capacity")]:
        band = loaded[(loaded["voc"] >= lo) & (loaded["voc"] < hi)]
        km = band["distance"].sum() / 1000
        print(f"  {label:<34} {len(band):>7,} links {km:>7,.0f} km {100 * km / km_total:>5.1f}%")

    print("\nthe ten busiest single links, by the flow in one direction:")
    peak = loaded.assign(peak=loaded[[CAR_AB, CAR_BA]].max(axis=1)).nlargest(10, "peak")
    print(peak[["link_id", "name", "link_type", "peak", "capacity_ab", "voc"]]
          .rename(columns={"peak": "veh/h"}).round(2).to_string(index=False))

    # Streets, not links, are the unit to compare against a published count. Vehicle-km is the
    # total travel on one; the peak is its busiest point in one direction, which is the figure a
    # roadside count would record.
    traffic = loaded[loaded["name"].notna() & (loaded["name"].astype(str) != "")].copy()
    traffic["veh_km"] = traffic["flow"] * traffic["distance"] / 1000
    traffic["one_way"] = traffic[[CAR_AB, CAR_BA]].max(axis=1)
    streets_busy = traffic.groupby("name").agg(
        km=("distance", "sum"), veh_km=("veh_km", "sum"), peak=("one_way", "max"),
        kind=("link_type", lambda c: c.mode().iloc[0]))
    streets_busy["km"] /= 1000
    print("\nthe streets carrying the most traffic:")
    print(f"  {'street':<40}{'kind':<11}{'km':>6}{'veh-km':>10}{'busiest point':>15}")
    for r in streets_busy.nlargest(top, "veh_km").itertuples():
        print(f"  {str(r.Index)[:39]:<40}{r.kind:<11}{r.km:>6.1f}{r.veh_km:>10,.0f}"
              f"{r.peak:>12,.0f} veh/h")

    # Grouped by street name, with what the model assumed about each, so the assumptions can be
    # checked one by one.
    over = loaded[loaded["voc"] >= 1.0]
    named = over[over["name"].notna() & (over["name"].astype(str) != "")]
    worst = named.groupby("name").agg(
        km=("distance", "sum"), worst=("voc", "max"), typical=("voc", "median"),
        lanes=("lanes_ab", "mean"), kmh=("speed_ab", "mean"), veh_h=("capacity_ab", "mean"),
        kind=("link_type", lambda c: c.mode().iloc[0]))
    worst["km"] /= 1000
    anon_km = (over["distance"].sum() - named["distance"].sum()) / 1000
    print(f"\nover-capacity network: {over['distance'].sum() / 1000:,.0f} km, of which "
          f"{anon_km:,.0f} km is on links OSM leaves unnamed")
    print("the streets carrying the most over-capacity length - the ones to check first:")
    print(f"  {'street':<40}{'kind':<11}{'km':>6}{'lanes':>7}{'km/h':>6}{'cap':>7}"
          f"{'typical':>9}{'worst':>7}")
    for r in worst.nlargest(top, "km").itertuples():
        print(f"  {str(r.Index)[:39]:<40}{r.kind:<11}{r.km:>6.1f}{r.lanes:>7.1f}"
              f"{r.kmh:>6.0f}{r.veh_h:>7,.0f}{r.typical:>9.2f}{r.worst:>7.2f}")

    ring = loaded[loaded["junction"].isin(["roundabout", "circular"])]
    if len(ring):
        ring_over = ring[ring["voc"] >= 1.0]
        if len(ring_over):
            print(f"\nroundabouts over capacity: {len(ring_over)} of {len(ring)} loaded links, "
                  f"worst {ring_over['voc'].max():.2f}")
        else:
            print(f"\nnone of the {len(ring):,} loaded roundabout links is over capacity")

    print("\nand the sharpest single points, wherever they are:")
    for r in named.nlargest(8, "voc").itertuples():
        print(f"  {str(r.name)[:33]:<34}{r.link_type:<11}link {r.link_id:<7}"
              f"{r.lanes_ab:>4.0f} lanes {r.speed_ab:>4.0f} km/h  "
              f"cap {r.capacity_ab:>6,.0f}  V/C {r.voc:>5.2f}")
    return {"streets": streets, "loaded": loaded, "veh_hours": busy, "free_hours": free,
            "streets_busy": streets_busy, "over": over}


def delay_report(load, trips, s, alternatives=((2, 220), (2, 250), (2, 280), (3, 250)),
                 period="the peak hour", yearly=True):
    """Delay is the vehicle-hours on the loaded network less what the same trips would take on
    empty streets. Per trip, that is a figure the model earns; per year, it needs a guess about
    how often people make such a trip (PEAK_TRIPS_PER_DAY, WORKING_DAYS)."""
    delay_h = load["veh_hours"] - load["free_hours"]
    per_trip = delay_h / trips * 60
    print(f"delay in {period}: {delay_h:,.0f} vehicle-hours "
          f"({load['veh_hours']:,.0f} congested less {load['free_hours']:,.0f} at free flow)")
    print(f"  over {trips:,.0f} trips, {per_trip:.2f} minutes each")
    if not yearly:
        print("  (a year's delay is worked out from the weekday morning peak alone)")
        return per_trip
    print(f"  at {s.PEAK_TRIPS_PER_DAY} peak trips a day for {s.WORKING_DAYS} days: "
          f"{s.PEAK_TRIPS_PER_DAY * s.WORKING_DAYS * per_trip / 60:.0f} hours a year")
    # The same number whether counted per vehicle or per person: occupancy multiplies the delay
    # and the trips alike, so it cancels.
    print("  at other guesses about how often people travel:")
    for n, d in alternatives:
        print(f"    {n} trips a day for {d} days: {n * d * per_trip / 60:.0f} hours a year")
    return per_trip
