"""The assignment and what it says: one frequency-based hyperpath solve, and its read-out.

Three properties decide how every number here should be read:

- **There is no timetable at solve time.** The trips running inside the period are counted and
  turned into a frequency; a 5-minute headway becomes 0.0033 vehicles per second. So the model
  answers "how good is the service on average during the period?", not "can I make the 07:42?".
- **Waiting time is derived, not assumed.** A passenger willing to take any of several services
  waits, on average, WAIT_TIME_FACTOR / (the sum of their frequencies): half their combined
  headway at the default.
- **There is no crowding.** The assignment is uncapacitated: a vehicle takes the same time with
  5 passengers or 500, and a segment carrying more people than the service has places is
  reported without complaint. `onboard_by_segment` works out the places so the check the model
  skips can be made by hand.

The **transfer penalty** (TRANSFER_PENALTY_S, 480 s) is paid at each change of vehicle, not at
the first boarding nor the last alighting (transit/graph.py). It is not a claim that changing
takes eight minutes - it stands for the inconvenience, and stops the algorithm inventing
strategies where a passenger hops off and straight back on. It is in the generalised cost
(`trav_time`) only: the journey time is built from the real parts - the walks, the wait, the
ride - and the averages are over the trips that board; those that walk the whole way are counted
on their own.
"""
import geopandas as gpd
import numpy as np
import pandas as pd

# AequilibraE's own skims, and transit/graph.py's columns (add_skim_columns).
SKIM_FIELDS = ["trav_time", "in_vehicle_trav_time", "access_trav_time", "egress_trav_time",
               "edge_time", "penalty_time", "transfer_walk_time", "boards", "ride_end"]


class SimulationResult:
    """One assignment's output and the headline metrics derived from it.

    `edges` is the per-edge volume table joined to the graph's edge attributes, so every row knows
    whether it is a boarding, a ride, a transfer or a walk. `skims` is the zone-by-zone side of the
    same answer. `segments` and `stops` are the mapped forms of both, taken at solve time.
    """

    # Getting onto a vehicle happens on three kinds of edge, not one: `boarding` from the street,
    # and `inner_transfer` / `outer_transfer` when changing from another service. Counting only
    # the first would miss every transfer boarding.
    BOARDING_EDGES = ["boarding", "inner_transfer", "outer_transfer"]
    # A pair's share of trips that board (`ride_end`) below this walks, in the averages.
    BOARDS = 1e-6

    def __init__(self, label, edges, skims, demand, zone_ids, segments=None, stops=None):
        self.label = label
        self.edges = edges                     # per-edge volumes + attributes
        self.skims = skims                     # AequilibraeMatrix of zone-to-zone outcomes
        self.demand = demand                   # the matrix actually fed to the solver
        self.zone_ids = zone_ids               # the zone of each row and column of both
        self.segments = segments               # per-segment volumes
        self.stops = stops                     # boardings and alightings per stop

    def _volume(self, link_type):
        return float(self.edges.loc[self.edges.link_type == link_type, "pt_volume"].sum())

    def skim(self, name):
        return np.asarray(self.skims.matrix[name])

    # --- each pair's parts, in seconds, over its whole strategy ------------------------------
    @property
    def boarding_share(self):
        """Each pair's share of trips that board: those that end on a line's way off to the
        destination. A strategy can split, part boarding, part walking."""
        return np.clip(self.skim("ride_end"), 0.0, 1.0)

    def pair_wait(self):
        """The waiting: the trip's time less the time on its edges - the wait sits on none."""
        return np.maximum(self.skim("trav_time") - self.skim("edge_time"), 0.0)

    def pair_walk(self):
        """The walking: to the stop, from it, and between stops on a change."""
        return (self.skim("access_trav_time") + self.skim("egress_trav_time")
                + self.skim("transfer_walk_time"))

    def pair_journey(self):
        """Door to door, without the transfer penalty: the walks, the wait, the ride."""
        return self.skim("in_vehicle_trav_time") + self.pair_wait() + self.pair_walk()

    def pair_transfers(self):
        """Changes of vehicle - at a stop, inside a station or on foot between stops: the
        boardings less the first."""
        return np.maximum(self.skim("boards") - self.boarding_share, 0.0)

    @property
    def boardings(self):
        """Total vehicle boardings. A trip with one transfer counts twice - the usual convention."""
        return sum(self._volume(kind) for kind in self.BOARDING_EDGES)

    @property
    def boards(self):
        """Mask of the pairs that carry demand, can travel and board - the averages' pairs."""
        return self.reached & (self.boarding_share > self.BOARDS)

    @property
    def reached(self):
        """Mask of O-D pairs that carry demand AND are reachable by transit.

        An unreachable pair comes back with a skim of zero rather than infinity, so testing the
        skim for zero is how "no transit journey exists" is told from "a very short one".
        """
        return (self.skim("trav_time") > 0) & (self.demand > 0)

    def _per_boarder(self, values):
        """The mean over the trips that board of a pair's part (`values`, seconds over its whole
        strategy): its trips times it, over its trips that board. A pair whose strategy splits
        has its walkers' part in it too - there are few, and the error is theirs alone."""
        mask = self.boards
        riders = (self.demand * self.boarding_share)[mask].sum()
        if riders <= 0:
            return float("nan")
        return float((self.demand[mask] * values[mask]).sum() / riders)

    @property
    def served_demand(self):
        """Trips the network can carry: both ends within reach of a stop."""
        return float(self.demand[self.reached].sum())

    @property
    def boarded_demand(self):
        """Trips that use a vehicle - the honest measure of transit ridership.

        Not every reachable trip does. A passenger can walk to a stop, cross to another platform
        and walk out again to the destination zone without ever boarding; the graph is happy to
        route that way, and it is a reasonable answer for two zones whose catchments overlap.

        A hyperpath can **split**: part of a pair's flow boards, part walks the whole way. So each
        pair is weighted by its share of trips that board (`boarding_share`) rather than counted
        all-or-nothing.
        """
        return float((self.demand * self.boarding_share)[self.reached].sum())

    @property
    def walk_only_demand(self):
        """Trips the network 'serves' without carrying anyone: reachable, but on foot."""
        return self.served_demand - self.boarded_demand

    @property
    def journey_time(self):
        """Mean journey time in minutes of the trips that board, from its real parts.

        Deliberately NOT the raw `trav_time` skim: that is the generalised cost the algorithm
        minimises, and it includes the transfer penalty. Riding, waiting and walking give a
        number that can be quoted. (AequilibraE's own `waiting_time` skim is the cost less the
        ride and the walks to and from the stops, so it holds the penalty too: not used.)
        """
        return self._per_boarder(self.pair_journey()) / 60.0

    @property
    def waiting_time(self):
        return self._per_boarder(self.pair_wait()) / 60.0

    @property
    def in_vehicle_time(self):
        return self._per_boarder(self.skim("in_vehicle_trav_time")) / 60.0

    @property
    def walking_time(self):
        return self._per_boarder(self.pair_walk()) / 60.0

    @property
    def transfers(self):
        """Changes of vehicle per trip that boards."""
        return self._per_boarder(self.pair_transfers())

    @property
    def passenger_hours(self):
        """Total time the passengers who board spend making their journeys: the transit
        counterpart of vehicle-hours in a road assignment, and read the same way."""
        return self.boarded_demand * self.journey_time / 60.0


def make_demand(graph, array):
    """Turn a (zones x zones) array - zone 1's row first - into the matrix the transit assignment
    reads, and the graph it is solved on.

    The matrix is indexed by zone id (`taz_id`): AequilibraE looks each one up in the graph's
    `od_node_mapping` for its origin vertex and - with centroid flows blocked, a vertex of its
    own - its destination vertex.
    """
    from aequilibrae.matrix import AequilibraeMatrix

    zones = np.sort(graph.od_node_mapping["taz_id"].astype(int).unique())
    dense = np.asarray(array, dtype=float)[np.ix_(zones - 1, zones - 1)]
    transit_graph = graph.to_transit_graph()
    matrix = AequilibraeMatrix()
    matrix.create_empty(zones=len(zones), matrix_names=["pt"], memory_only=True)
    matrix.index[:] = zones
    matrix.matrices[:, :, 0] = dense
    matrix.computational_view(["pt"])
    return transit_graph, matrix


def solve_transit(network, graph, array, period_hours, label):
    """Run one hyperpath assignment and return its SimulationResult, with the per-segment and
    per-stop volumes taken while the database still describes the network it was solved on."""
    from aequilibrae.paths import TransitAssignment, TransitClass

    transit_graph, matrix = make_demand(graph, array)
    assig = TransitAssignment()
    assig.add_class(TransitClass(name="pt", graph=transit_graph, matrix=matrix))
    assig.set_time_field("trav_time")          # cost of traversing an edge, in seconds
    assig.set_frequency_field("freq")          # vehicles per second - the service level
    assig.set_algorithm(network.s.TRANSIT_ALGORITHM)
    assig.set_skimming_fields(SKIM_FIELDS)
    assig.execute()

    # The matrix's rows and columns are zones, by id (make_demand).
    zone_ids = np.asarray(matrix.index[:]).astype(int)
    edges = assig.results().join(graph.edges.set_index("link_id"), how="left")
    result = SimulationResult(label, edges, assig.get_skim_results()["pt"],
                            np.asarray(matrix.matrix_view), zone_ids)
    result.segments = onboard_by_segment(network, result, period_hours)
    result.stops = boardings_by_stop(network, result)
    return result


def onboard_by_segment(network, result, period_hours):
    """Per-segment passenger volumes, with the places on offer beside them.

    The graph's `line_id` is "<route short name>_<pattern id>", which is how a segment volume
    finds its way back to its pattern.

    The capacity columns are the point of doing this here: the assignment never reads capacity.
    Both halves are read from the model rather than assumed - the pattern's frequency off its own
    `boarding` edges, and the places per vehicle from the `routes` table (the line's `capacity`,
    written there after the import - TransitModel._import). A pattern is one direction, so
    `places` lines up with a directional load.
    """
    on = result.edges[result.edges.link_type == "on-board"].copy()
    on["pattern_id"] = on["line_id"].astype(str).str.rsplit("_", n=1).str[-1].astype("int64")
    on["route"] = on["line_id"].astype(str).str.rsplit("_", n=1).str[0]
    on = on.groupby(["pattern_id", "line_seg_idx", "route"], as_index=False)["pt_volume"].sum()

    boarding = result.edges[result.edges.link_type == "boarding"].copy()
    boarding["pattern_id"] = (boarding["line_id"].astype(str).str.rsplit("_", n=1)
                              .str[-1].astype("int64"))
    # A boarding edge's frequency is the line's over the wait factor (transit/graph.py).
    vehicles = (boarding.groupby("pattern_id")["freq"].max() * network.s.WAIT_TIME_FACTOR
                * period_hours * 3600.0)
    places_each = network.routes().set_index("pattern_id")["total_capacity"]
    on["places"] = on["pattern_id"].map(vehicles) * on["pattern_id"].map(places_each)
    on["pct_capacity"] = 100.0 * on["pt_volume"] / on["places"]

    merged = network.segments().merge(on, on=["pattern_id", "line_seg_idx"], how="inner")
    return gpd.GeoDataFrame(merged, geometry="geometry", crs="EPSG:4326")


def boardings_by_stop(network, result):
    """Boardings and alightings at every stop, with geometry.

    These are the `boarding` and `alighting` edges, and the ways off a line straight to a
    destination (an `egress_connector` with a line - transit/graph.py add_direct_egress): getting
    on from the street and off to it. A passenger changing service inside a station or at the
    same stop boards on a transfer edge instead, which `SimulationResult.boardings` counts and
    this does not.
    """
    e = result.edges
    off = (e.link_type == "egress_connector") & (e.line_id.astype(str) != "")
    events = e[e.link_type.isin(["boarding", "alighting"]) | off].assign(
        link_type=lambda d: np.where(d.link_type == "egress_connector", "alighting", d.link_type))
    counts = (events.pivot_table(index="stop_id", columns="link_type", values="pt_volume",
                                 aggfunc="sum").fillna(0.0).reset_index())
    for col in ("boarding", "alighting"):
        if col not in counts:
            counts[col] = 0.0
    stops = network.stops()
    stops["stop_id"] = stops["stop_id"].astype(str)
    counts["stop_id"] = counts["stop_id"].astype(str)
    merged = stops.merge(counts, on="stop_id", how="left").fillna({"boarding": 0.0,
                                                                   "alighting": 0.0})
    return gpd.GeoDataFrame(merged, geometry="geometry", crs="EPSG:4326")


def transit_coverage(network, graph, num_zones):
    """Per zone: can it reach the transit network, and how far is the walk?

    Read off the access connectors - the demand-free test: a zone is served if it has at least
    one. Returns a frame indexed by zone_id with the stops in reach and, for every zone, the
    straight-line distance and walk to its nearest stop.

    The distance is measured geometrically for every zone because the connector table cannot
    answer it where it matters most: an unserved zone has no connectors, and "1 km short of a
    stop" and "6 km up a mountain" are very different findings. For served zones the two agree
    to within seconds (AequilibraE projects to EPSG:3857, this to a local metre CRS).

    Both are optimistic: a walk starts somewhere in the zone, not at its middle, and follows
    streets rather than a straight line - typically 20-40% further.
    """
    from aequilibrae.utils.geo_utils import metre_crs_for_gdf

    access = graph.edges[graph.edges.link_type == "access_connector"]
    zone_of_node = graph.vertices.set_index("node_id")["taz_id"]
    reach = pd.DataFrame({"zone_id": [int(zone_of_node.loc[n]) for n in access["b_node"]],
                          "walk_min": access["trav_time"].to_numpy() / 60.0})
    reach = reach[reach["zone_id"] > 0]
    out = pd.DataFrame(index=pd.Index(range(1, num_zones + 1), name="zone_id"))
    out = out.join(reach.groupby("zone_id").agg(stops_in_reach=("walk_min", "size")))
    out["stops_in_reach"] = out["stops_in_reach"].fillna(0).astype(int)
    out["served"] = out["stops_in_reach"] > 0

    stops = network.stops()
    zones = network.zones()
    metre_crs = metre_crs_for_gdf(stops)
    stops_m = stops.to_crs(metre_crs)
    centroids_m = gpd.GeoDataFrame(zones[["zone_id"]], geometry=zones.geometry.centroid,
                                   crs="EPSG:4326").to_crs(metre_crs)
    metres = pd.Series([float(stops_m.distance(point).min()) for point in centroids_m.geometry],
                       index=centroids_m["zone_id"].to_numpy())
    out["nearest_stop_km"] = metres.reindex(out.index) / 1000.0
    out["nearest_stop_min"] = metres.reindex(out.index) / network.s.WALKING_SPEED / 60.0
    return out


def assignable_share(coverage, demand):
    """One line of accounting: how much of the matrix has both ends on the network."""
    served = coverage.index[coverage["served"]].to_numpy() - 1
    total = float(demand.sum())
    reachable = float(demand[np.ix_(served, served)].sum())
    return (f"Assignable demand: {reachable:,.0f} of {total:,.0f} trips "
            f"({100 * reachable / total:.1f}%) - the rest has at least one end in a zone with no "
            f"stop within walking distance.")


def summarise(result):
    """The standard read-out for one result."""
    print(f"{result.label}")
    print(f"  Trips reachable      {result.served_demand:>10,.0f}  of "
          f"{result.demand.sum():,.0f} in the matrix")
    print(f"    board a vehicle    {result.boarded_demand:>10,.0f}  "
          f"({100 * result.boarded_demand / max(result.served_demand, 1):.0f}%)")
    print(f"    walk the whole way {result.walk_only_demand:>10,.0f}  "
          f"({100 * result.walk_only_demand / max(result.served_demand, 1):.0f}%)")
    print(f"  Boardings            {result.boardings:>10,.0f}  "
          f"({result.boardings / max(result.boarded_demand, 1):.2f} per boarding trip)")
    print(f"  Passenger-hours      {result.passenger_hours:>10,.0f}")
    print(f"  Average journey      {result.journey_time:>10.1f}  min")
    print(f"    riding             {result.in_vehicle_time:>10.1f}  min")
    print(f"    waiting            {result.waiting_time:>10.1f}  min")
    print(f"    walking (both ends){result.walking_time:>10.1f}  min")
    print(f"  Transfers per trip   {result.transfers:>10.2f}")


def busiest_rides(segments, n=5):
    """The n segments carrying the most passengers, as a readable table."""
    top = segments.nlargest(n, "pt_volume").copy()
    top["ride"] = top["from_name"] + "  ->  " + top["to_name"]
    return (top[["route", "ride", "pt_volume"]].rename(columns={"pt_volume": "passengers"})
            .round(0))


def structural_check(network, graph, baseline, period_hours, n_zones):
    """Where the network is busy regardless of demand: one trip between every pair of zones.

    Weighting every origin and destination identically removes the demand model from the answer;
    what is left measures how structurally central each segment is - how many zone-to-zone
    journeys have to pass through it. Segments high in both rankings are load-bearing whatever
    the demand does; segments high only in the baseline carry the assumption about where people
    are going. Returns the Spearman rank correlation between the two.
    """
    uniform = np.ones((n_zones, n_zones))
    np.fill_diagonal(uniform, 0)
    structural = solve_transit(network, graph, uniform, period_hours, "Uniform demand")

    top = structural.segments.nlargest(8, "pt_volume").copy()
    top["share"] = 100 * top["pt_volume"] / structural.segments["pt_volume"].max()
    top["ride"] = top["from_name"] + "  ->  " + top["to_name"]
    print("Most structurally central rides (one trip between every zone pair):")
    print(top[["route", "ride", "share"]].round(1)
          .rename(columns={"share": "% of busiest"}).to_string(index=False))

    rank_s = structural.segments.set_index("segment")["pt_volume"].rank(ascending=False)
    rank_b = baseline.segments.set_index("segment")["pt_volume"].rank(ascending=False)
    both = pd.concat([rank_b.rename("baseline_rank"), rank_s.rename("structural_rank")],
                     axis=1).dropna()
    rho = both["baseline_rank"].corr(both["structural_rank"], method="spearman")
    print(f"\nRank correlation between the two: {rho:.3f} (1.0 would mean the demand assumption "
          f"changes nothing).")
    return rho
