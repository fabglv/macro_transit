"""The transit graph, and the imported network read back out of the project.

The graph is **not** a map of the network: its vertices are not stations and its edges are not
track. Every edge is one thing a passenger does:

| edge type | what the passenger is doing | frequency |
|---|---|---|
| `access_connector` | walking from home to a stop | infinite (no waiting) |
| `boarding` | waiting for, and getting on, a service | the line's frequency |
| `on-board` | riding between two stops | infinite (already aboard) |
| `dwell` | sitting on the vehicle while it serves a stop | infinite |
| `alighting` | getting off, to change to another line | infinite |
| `inner_transfer` | changing to another service at the same stop | the new line's frequency |
| `outer_transfer` | changing lines by walking within a station | the new line's frequency |
| `walking` | walking between platforms of a station, or between nearby stops | infinite |
| `egress_connector` | walking from a stop to the destination - or getting off and walking there | infinite |

What a passenger's time is made of, here:

- **The ride holds each stop's dwell.** AequilibraE's GTFS import keeps a stop's departure as its
  arrival too, so a ride is timed from one stop's departure to the next's: the dwell at the stop
  it reaches, each line's own from its timetable, is in it. The graph adds none of its own
  (`uniform_dwell_time` 0): boarding, alighting and riding through a stop cost nothing more.
- **The transfer penalty is paid at a change of vehicle only.** AequilibraE charges it on every
  alighting edge, the trip's last included; here the last alighting goes straight to the
  destination on an edge of its own (`add_direct_egress`), so a trip with no change pays none.
- **The wait is WAIT_TIME_FACTOR of the headway** - of 1 / the combined frequency of the lines a
  passenger will take. AequilibraE's default, 1, is the wait for vehicles arriving at random; it
  codes the factor by scaling the boarding edges' frequencies (the real frequency is theirs times
  the factor).

Transfers come from two sources. `outer_transfer` edges and some `walking` edges are built by
AequilibraE from the feed's `parent_station` groups. The rest of the `walking` edges are added
here, between stops close enough to walk between that are not one station - routed on the
streets, so the walk is charged at its real length.
"""
import itertools

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely.wkb
from shapely.geometry import LineString
from shapely.ops import substring

from .gtfs import route_of


def _gap(a, b):
    """Straight-line distance between two (lon, lat) tuples, in degrees - for ordering only."""
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


def add_walk_transfers(graph, pairs, stops, walking_speed):
    """Append `walking` edges between the stop vertices of each pair, in both directions.

    A `walking` edge joins two `stop` vertices, and the alighting and boarding edges both meet the
    graph at a stop vertex - so this alone lets a passenger change service here. It costs what
    the `outer_transfer` edge AequilibraE builds inside a station does - the transfer penalty, on
    the alighting edge, and the walk.

    The walk is charged at the **routed** distance over the walking speed, where AequilibraE would
    charge the straight line - so these transfers are costed more honestly than those in a station.
    """
    stop_vertices = graph.vertices[graph.vertices["node_type"] == "stop"]
    node_of_id = dict(zip(stop_vertices["stop_id"].astype(str), stop_vertices["node_id"]))
    node_of_code = {code: node_of_id[sid]
                    for code, sid in zip(stops["stop"].astype(str), stops["stop_id"].astype(str))
                    if sid in node_of_id}

    rows = []
    for pair in pairs.itertuples():
        if pair.stop_a not in node_of_code or pair.stop_b not in node_of_code:
            continue
        seconds = pair.walk_m / walking_speed
        for origin, destination in ((pair.stop_a, pair.stop_b), (pair.stop_b, pair.stop_a)):
            # Travel runs b_node -> a_node, which is why the coverage reads the zone off b_node
            # on an access connector.
            rows.append({"link_type": "walking", "line_id": "", "stop_id": "", "line_seg_idx": -1,
                         "b_node": node_of_code[origin], "a_node": node_of_code[destination],
                         "trav_time": seconds, "freq": np.inf,
                         "o_line_id": "", "d_line_id": "", "direction": 1})
    if not rows:
        return graph
    added = pd.DataFrame(rows).astype({"line_seg_idx": "int64", "direction": "int8"})
    graph.edges = pd.concat([graph.edges.drop(columns="link_id"), added], ignore_index=True)
    graph.edges.insert(0, "link_id", np.arange(1, len(graph.edges) + 1))
    return graph


def add_access_radius(graph, radius_m, walking_speed):
    """Join every zone to every stop within `radius_m` of its middle, in a straight line, where
    AequilibraE has not already: an access connector from the zone's origin to the stop and an
    egress one from the stop to its destination, at the walk's time. Returns how many zones it
    joined to a stop they had none to.

    AequilibraE's overlapping_regions reaches the stops within the distance to the next zone's
    middle - about a grid cell on a regular grid, but only a block or two among a city's small
    census zones, most of which then reach no stop at all."""
    from aequilibrae.utils.geo_utils import metre_crs_for_gdf
    from scipy.spatial import KDTree

    v = graph.vertices
    mapping = graph.od_node_mapping
    origin_key = "o_node_id" if "o_node_id" in mapping else "node_id"
    dest_key = "d_node_id" if "d_node_id" in mapping else "node_id"
    stops = v[v["node_type"] == "stop"]
    origins = v[v["node_id"].isin(mapping[origin_key])]
    if stops.empty or origins.empty:
        return 0
    places = gpd.GeoSeries.from_wkb(pd.concat([stops["geometry"], origins["geometry"]]),
                                    crs="EPSG:4326")
    metric = places.to_crs(metre_crs_for_gdf(gpd.GeoDataFrame(geometry=places)))
    xy = np.column_stack([metric.x.to_numpy(), metric.y.to_numpy()])
    stop_xy, origin_xy = xy[:len(stops)], xy[len(stops):]
    edges = graph.edges
    access = edges[edges["link_type"] == "access_connector"]
    joined = set(zip(access["a_node"], access["b_node"]))          # (stop, origin) already
    had = set(access["b_node"])
    dest_of = dict(zip(mapping[origin_key], mapping[dest_key]))
    stop_nodes, origin_nodes = stops["node_id"].to_numpy(), origins["node_id"].to_numpy()
    rows, newly = [], set()
    for k, near in enumerate(KDTree(stop_xy).query_ball_point(origin_xy, radius_m)):
        o = origin_nodes[k]
        for j in near:
            s = stop_nodes[j]
            if (s, o) in joined:
                continue
            seconds = float(np.hypot(*(stop_xy[j] - origin_xy[k]))) / walking_speed
            # Travel runs b_node -> a_node: access from the origin to the stop, egress from the
            # stop to the destination.
            for kind, a, b, factor in (("access_connector", s, o, graph.access_time_factor),
                                       ("egress_connector", dest_of[o], s, graph.egress_time_factor)):
                rows.append({"link_type": kind, "line_id": "", "stop_id": "", "line_seg_idx": -1,
                             "a_node": a, "b_node": b, "trav_time": seconds * factor,
                             "freq": np.inf, "o_line_id": "", "d_line_id": "", "direction": 1})
            if o not in had:
                newly.add(o)
    if rows:
        added = pd.DataFrame(rows).astype({"line_seg_idx": "int64", "direction": "int8"})
        graph.edges = pd.concat([graph.edges.drop(columns="link_id"), added], ignore_index=True)
        graph.edges.insert(0, "link_id", np.arange(1, len(graph.edges) + 1))
    print(f"zones joined to every stop within {radius_m:g} m of their middle: {len(rows) // 2:,} "
          f"connectors added, {len(newly):,} zones reaching a stop that reached none")
    return len(newly)


def add_direct_egress(graph):
    """Getting off and walking to the destination as one edge: from a line's alighting vertex at
    a stop to every destination the stop's egress connectors reach, at the walk's time. The
    alighting edge carries the transfer penalty - it leads to the stop, where a passenger may
    board another line - so the last alighting of a trip takes this edge instead and pays none.
    Each keeps its line and stop, for the alightings counted at the stop. Returns how many it
    added."""
    edges = graph.edges
    alight = edges[edges["link_type"] == "alighting"][["a_node", "b_node", "line_id", "stop_id",
                                                        "line_seg_idx"]]
    egress = edges[(edges["link_type"] == "egress_connector")][["a_node", "b_node", "trav_time"]]
    # Travel runs b_node -> a_node: alighting from the line (b) to the stop (a), egress from the
    # stop (b) to the destination (a).
    joined = alight.merge(egress, left_on="a_node", right_on="b_node", suffixes=("", "_egress"))
    if joined.empty:
        return 0
    added = pd.DataFrame({
        "link_type": "egress_connector", "line_id": joined["line_id"], "stop_id": joined["stop_id"],
        "line_seg_idx": joined["line_seg_idx"].astype("int64"), "b_node": joined["b_node"],
        "a_node": joined["a_node_egress"],
        "trav_time": joined["trav_time"] + graph.a_tiny_time_duration, "freq": np.inf,
        "o_line_id": "", "d_line_id": "", "direction": np.int8(1)})
    graph.edges = pd.concat([edges.drop(columns="link_id"), added], ignore_index=True)
    graph.edges.insert(0, "link_id", np.arange(1, len(graph.edges) + 1))
    return len(added)


# The skims the read-out needs beyond AequilibraE's own (transit/assignment.py SKIM_FIELDS): an
# edge column is summed along a passenger's strategy as its time is.
def add_skim_columns(graph, penalty_s):
    """`edge_time` every edge's time - the trip's time less it is the wait, the one part that
    sits on no edge; `penalty_time` the transfer penalty; `transfer_walk_time` the walks between
    stops; `boards` 1 on every edge that gets on a vehicle; `ride_end` 1 on the edges that get off
    to the destination - a pair's share of trips that board at all."""
    e = graph.edges
    kind = e["link_type"]
    e["edge_time"] = e["trav_time"]
    paid = kind.isin(["alighting", "inner_transfer", "outer_transfer"])
    e["penalty_time"] = np.where(paid, np.minimum(penalty_s, e["trav_time"]), 0.0)
    e["transfer_walk_time"] = np.where(kind == "walking", e["trav_time"],
                                       np.where(kind == "outer_transfer",
                                                np.maximum(e["trav_time"] - penalty_s, 0.0), 0.0))
    e["boards"] = kind.isin(["boarding", "inner_transfer", "outer_transfer"]).astype(float)
    e["ride_end"] = ((kind == "egress_connector") & (e["line_id"].astype(str) != "")).astype(float)


class TransitNetwork:
    """The imported feed in one project: its stops and segments, its walking transfers and the
    graph built from it."""

    def __init__(self, project, transit, paths, settings, period_id):
        self.project = project
        self.transit = transit
        self.paths = paths
        self.s = settings
        self.period_id = period_id
        self.walk_pairs = None            # routed once per run: `prepare_walk_transfers`

    # --- reading the project back ----------------------------------------------------------
    def read_geo(self, table, columns, database=None):
        """A project layer with its geometry, without needing a GDAL engine: SpatiaLite hands
        the geometry over as WKB and geopandas builds the frame in memory. `database` is the
        project database by default, or the public-transport one when given."""
        from aequilibrae.utils.spatialite_utils import connect_spatialite

        conn = connect_spatialite(database or self.paths.project_db)
        try:
            df = pd.read_sql(f"SELECT {columns}, ST_AsBinary(geometry) AS _wkb FROM {table}", conn)
        finally:
            conn.close()
        geom = [shapely.wkb.loads(bytes(b)) if b is not None else None for b in df["_wkb"]]
        return gpd.GeoDataFrame(df.drop(columns="_wkb"), geometry=geom, crs="EPSG:4326")

    def zones(self):
        """The zoning, as the graph builder wants it: a zone_id column and a geometry."""
        return self.read_geo("zones", "zone_id")

    def stops(self):
        """Stops with their geometry, names and parent station."""
        return self.read_geo("stops", "stop_id, stop, name, parent_station, route_type",
                             database=self.paths.transit_db)

    def routes(self):
        return self.transit.get_table("routes")

    def pattern_lines(self):
        """One continuous polyline per map-matched pattern, assembled from `pattern_mapping`.

        `pattern_mapping` is what `map_match` writes: one row per road link the pattern travels,
        in travel order. Only the matched route types appear, so the metro is absent.

        The links are chained by proximity rather than by the stored `dir` flag: each link is
        flipped if its far end is nearer the running end of the chain than its near end is. That
        needs no assumption about how `dir` is encoded and self-corrects a link digitised against
        the flow.
        """
        pm = self.read_geo("pattern_mapping", "pattern_id, seq", database=self.paths.transit_db)
        pm = pm.sort_values(["pattern_id", "seq"])
        lines = {}
        for pattern_id, group in pm.groupby("pattern_id"):
            shapes = [g for g in group.geometry if g is not None and g.geom_type == "LineString"]
            if len(shapes) < 2:
                continue
            coords = list(shapes[0].coords)
            # Orient the first link so that its far end is the one meeting the second link.
            nxt = shapes[1].coords
            if min(_gap(coords[0], e) for e in (nxt[0], nxt[-1])) < \
               min(_gap(coords[-1], e) for e in (nxt[0], nxt[-1])):
                coords.reverse()
            for shape in shapes[1:]:
                c = list(shape.coords)
                if _gap(coords[-1], c[-1]) < _gap(coords[-1], c[0]):
                    c.reverse()
                coords.extend(c[1:] if c[0] == coords[-1] else c)
            lines[pattern_id] = LineString(coords)
        return lines

    def segments(self, matched=False):
        """Every stop-to-stop segment, with a stable identity.

        `route_links` gives one row per segment, its geometry a straight line between the two
        stops. That is the default, and what every load map uses: a schematic line is easier to
        read when the point is the number attached to it. `matched=True` swaps in the map-matched
        street path instead, by projecting the segment's two stops onto their pattern's matched
        polyline and cutting out the piece between them. The metro is not matched - it is in a
        tunnel - so it keeps its straight line, as does any bus segment whose stops fail to
        project in order.

        `distance` is the length of whatever geometry ends up being used, so a hover panel's
        length always describes the line on screen.

        The `segment` column is built from the GTFS stop codes - ours, and stable - because
        AequilibraE hands out new numeric pattern and stop ids on every import:
        ``"L1_El_Recreo -> L1_La_Magdalena"``.
        """
        from aequilibrae.utils.geo_utils import metre_crs_for_gdf

        seg = self.read_geo("route_links", "pattern_id, seq, from_stop, to_stop, distance",
                            database=self.paths.transit_db).rename(columns={"seq": "line_seg_idx"})
        stops = self.stops()
        # SQLite stores these columns without a fixed type, and they come back as int64 in one
        # table and as text in the other. Cast both sides before matching: left alone the join
        # silently produces NaN for every row.
        stop_key = stops["stop_id"].astype(str)
        code = pd.Series(stops["stop"].astype(str).to_numpy(), index=stop_key)
        name = pd.Series(stops["name"].astype(str).to_numpy(), index=stop_key)
        from_key = seg["from_stop"].astype(str)
        to_key = seg["to_stop"].astype(str)
        seg["from_name"] = from_key.map(name)
        seg["to_name"] = to_key.map(name)
        seg["segment"] = from_key.map(code) + " -> " + to_key.map(code)
        if seg["segment"].isna().any():
            raise RuntimeError("Could not name every segment - route_links and stops did not "
                               "match. Check the stop id dtypes.")

        n_matched = 0
        if matched:
            point_of = pd.Series(stops.geometry.to_numpy(), index=stop_key)
            lines = self.pattern_lines()
            geometry = []
            for row, a, b in zip(seg.itertuples(), from_key, to_key):
                line = lines.get(row.pattern_id)
                piece = None
                if line is not None:
                    start, end = line.project(point_of[a]), line.project(point_of[b])
                    if end > start:
                        piece = substring(line, start, end)
                if piece is not None and piece.geom_type == "LineString" and len(piece.coords) > 1:
                    geometry.append(piece)
                    n_matched += 1
                else:
                    geometry.append(row.geometry)
            seg = seg.set_geometry(geometry, crs="EPSG:4326")
        seg["distance"] = seg.to_crs(metre_crs_for_gdf(seg)).length.to_numpy()
        seg.attrs["matched_segments"] = n_matched
        return seg

    # --- interchanges ----------------------------------------------------------------------
    def walking_distances(self):
        """Walking distance between every pair of stops on different routes, in metres.

        Routed on the street network, taken as **undirected** - a pedestrian ignores one-way
        restrictions - with `distance` as the weight. Each stop is snapped to the nearest network
        node and the snap distance at both ends is added back, so the figure is stop to stop, and
        it is floored at the straight line.

        Not AequilibraE's own walk graph: that one respects one-way direction, and a pedestrian
        is not bound by it - routed directionally, two El Recreo platforms 47 m apart come out
        unreachable. So the links and their `distance` come from AequilibraE and the shortest
        path is taken undirected here.

        It is the road network, so it has no footpaths, plazas or crossings: where a real route
        cuts through a park this goes around it. Read it as an indicator of detour, reliable for
        "is there something in the way" and not to the nearest hundred metres.

        Pairs further apart than WALK_ROUTE_MAX_STRAIGHT_M in a straight line are not routed.
        """
        from aequilibrae.utils.geo_utils import metre_crs_for_gdf
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import dijkstra

        links = self.project.network.links.data
        walkable = links[links["modes"].astype(str).str.contains("w")]
        ids = np.unique(np.concatenate([walkable["a_node"].to_numpy(),
                                        walkable["b_node"].to_numpy()]))
        position = pd.Series(np.arange(len(ids)), index=ids)
        matrix = coo_matrix(
            (walkable["distance"].to_numpy(dtype=float),
             (position[walkable["a_node"]].to_numpy(), position[walkable["b_node"]].to_numpy())),
            shape=(len(ids), len(ids))).tocsr()

        nodes = self.project.network.nodes.data
        net = gpd.GeoDataFrame(nodes[["node_id"]], geometry=nodes.geometry, crs="EPSG:4326")
        net = net[net["node_id"].isin(ids)]
        stops = self.stops()
        metre_crs = metre_crs_for_gdf(stops)
        net_m, stops_m = net.to_crs(metre_crs), stops.to_crs(metre_crs)

        snapped, snap_m, point = {}, {}, {}
        for stop in stops_m.itertuples():
            gap = net_m.distance(stop.geometry)
            snapped[stop.stop] = int(net_m.loc[gap.idxmin(), "node_id"])
            snap_m[stop.stop] = float(gap.min())
            point[stop.stop] = stop.geometry

        codes = sorted(point)
        served = self._routes_at_stops()
        reach = dijkstra(matrix, directed=False, indices=[position[snapped[c]] for c in codes])
        rows = []
        for i, a in enumerate(codes):
            for b in codes[i + 1:]:
                if served.get(a) and served.get(a) == served.get(b):
                    continue                       # the same routes: not an interchange
                straight = point[a].distance(point[b])
                if straight > self.s.WALK_ROUTE_MAX_STRAIGHT_M:
                    continue
                routed = reach[i][position[snapped[b]]] + snap_m[a] + snap_m[b]
                rows.append((a, b, straight, max(straight, routed)))
        out = pd.DataFrame(rows, columns=["stop_a", "stop_b", "straight_m", "walk_m"])
        return out.sort_values("walk_m").reset_index(drop=True)

    def declared_stations(self):
        """Each declared station and the stops it groups, from the feed's `parent_station`."""
        stops = self.stops()
        grouped = stops[stops["parent_station"].astype(str).str.len() > 0]
        return (grouped.groupby("parent_station")["stop"]
                .apply(lambda s: set(s.astype(str))).to_dict())

    def _same_station(self):
        return {frozenset(pair) for members in self.declared_stations().values()
                for pair in itertools.combinations(members, 2)}

    def walk_transfer_pairs(self, distances):
        """Stop pairs to join with a walking transfer: on two different routes, within
        TRANSFER_WALK_M on foot, and **not already inside one declared station** - those
        platforms are joined by AequilibraE itself.

        Grouping two stops 400 m apart under one station asserts they are the same place;
        joining them with a walking edge says only that somebody could walk between them, which
        is what is actually true."""
        inside = self._same_station()
        keep = [frozenset((r.stop_a, r.stop_b)) not in inside and r.walk_m <= self.s.TRANSFER_WALK_M
                for r in distances.itertuples()]
        return distances[keep].reset_index(drop=True)

    def audit_interchanges(self, distances):
        """Print both sides of the interchange assumption.

        `wide_stations()` checks the declarations against the straight-line spread. This uses
        the routed walk, so it also catches a pair close on the map but a long way round on foot,
        and it lists the pairs that are walkable but *not* joined at all."""
        inside = self._same_station()
        declared = distances[[frozenset((r.stop_a, r.stop_b)) in inside
                              for r in distances.itertuples()]]
        far = declared[declared["walk_m"] > self.s.SAME_STATION_M]
        if len(far):
            print(f"{len(far)} declared platform pair(s) are more than {self.s.SAME_STATION_M} m "
                  f"apart on foot - one station on paper, a walk on the ground:")
            for r in far.itertuples():
                print(f"    {r.walk_m:5.0f} m walk ({r.straight_m:4.0f} m straight)  "
                      f"{r.stop_a} <-> {r.stop_b}")
        else:
            print(f"Every declared station keeps its platforms within {self.s.SAME_STATION_M} m "
                  f"on foot.")

        linked = self.walk_transfer_pairs(distances)
        print(f"\n{len(linked)} pair(s) on different routes are within {self.s.TRANSFER_WALK_M} m "
              f"on foot and are joined by a walking transfer:")
        for r in linked.itertuples():
            # Two stops on one spot (a new line stopping at another's stop): no detour.
            detour = r.walk_m / r.straight_m if r.straight_m > 0 else 1.0
            note = "   (a detour: something in the way)" if detour >= 1.8 else ""
            print(f"    {r.walk_m:5.0f} m walk ({r.straight_m:4.0f} m straight, x{detour:.2f})  "
                  f"{r.stop_a} <-> {r.stop_b}{note}")
        beyond = distances[distances["walk_m"] > self.s.TRANSFER_WALK_M]
        print(f"\n{len(beyond)} pair(s) within {self.s.WALK_ROUTE_MAX_STRAIGHT_M} m straight-line "
              f"are further than {self.s.TRANSFER_WALK_M} m on foot and stay unconnected.")

    def prepare_walk_transfers(self):
        """Route the walks between stops once, audit them, and keep the pairs to join."""
        distances = self.walking_distances()
        self.audit_interchanges(distances)
        self.walk_pairs = self.walk_transfer_pairs(distances)
        return self.walk_pairs

    def _routes_at_stops(self):
        """{stop code: the routes calling there}, from the feed's patterns."""
        links = self.transit.get_table("route_links")[["pattern_id", "from_stop", "to_stop"]]
        routes = self.transit.get_table("routes").set_index("pattern_id")["shortname"]
        stops = self.transit.get_table("stops")
        # route_links holds the stop ids as numbers, the stops table as text: one kind for both.
        codes = pd.Series(stops["stop"].astype(str).to_numpy(),
                          index=stops["stop_id"].astype("int64").to_numpy())
        out = {}
        for r in links.itertuples():
            for stop in (r.from_stop, r.to_stop):
                out.setdefault(codes.get(int(stop)), set()).add(routes.get(r.pattern_id))
        return {code: frozenset(rs) for code, rs in out.items()}

    def save_graph_configuration(self):
        """Build the graph once with the method's settings - CONNECTOR_METHOD, GRAPH_TRANSFERS -
        and save it: that stores its configuration in the project for the period, which
        `build_graph` reads back (TransitGraphBuilder.from_db) to build afresh every time."""
        graph = self.transit.create_graph(period_id=self.period_id,
                                          connector_method=self.s.CONNECTOR_METHOD,
                                          **self.s.GRAPH_TRANSFERS)
        graph.create_line_geometry(method="direct")
        self.transit.save_graphs()

    def build_graph(self):
        """A fresh transit graph from the imported feed, with the walking transfers.
        The walking speed is not stored in the saved configuration, so it is set here, on every
        rebuild.
        """
        from aequilibrae.transit import TransitGraphBuilder

        graph = TransitGraphBuilder.from_db(self.project, self.period_id)
        graph.walking_speed = self.s.WALKING_SPEED
        # The assignment's parameters (the module's notes): no dwell of the graph's own - the
        # rides hold each line's - the penalty at each change, the share of the headway waited.
        graph.uniform_dwell_time = 0.0
        graph.alighting_penalty = float(self.s.TRANSFER_PENALTY_S)
        graph.wait_time_factor = float(self.s.WAIT_TIME_FACTOR)
        graph.add_zones(self.zones(), from_crs="EPSG:4326")
        graph.create_graph()
        graph.create_od_node_mapping()
        add_access_radius(graph, float(self.s.ACCESS_RADIUS_M), self.s.WALKING_SPEED)
        add_walk_transfers(graph, self.walk_pairs, self.stops(), self.s.WALKING_SPEED)
        n = add_direct_egress(graph)
        print(f"the last alighting of a trip pays no transfer penalty: {n:,} edges straight to "
              f"the destination")
        # No edge free: the assignment refuses one that costs nothing - a transfer between two
        # platforms at one spot, with no transfer penalty, would.
        free = graph.edges["trav_time"] <= 0
        graph.edges.loc[free, "trav_time"] = graph.a_tiny_time_duration
        add_skim_columns(graph, graph.alighting_penalty)
        return graph
