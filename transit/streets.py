"""The streets a bus can be matched onto: how far a point is from them, and the path along them
through a line's stops - for the line design editor, the design's pages and its feed.

A bus route is map-matched onto the streets, and a stop further than MATCH_RADIUS_M (50 m) from
any transit-mode link breaks every pattern calling at it (gtfs.unmatchable_stops explains why).
The editor checks a new line's stops as they are placed, and can move a stop onto the street.

The path is a preview of what the map matching will do: the shortest way along the streets,
respecting one-way streets, through the stops in order. A stop is not tied to the one street
nearest it: on a divided avenue that is as often the carriageway running the other way, and the
bus would go round a block to reach the stop and round another to leave it. Every street within
CANDIDATE_RADIUS_M of a stop is a candidate, and the path takes the candidates - one per stop -
that make the whole route shortest (a Viterbi pass over the stops), a candidate's distance from
its stop counting against it so the nearest still wins where it does not matter. The path is also the feed's shape, which AequilibraE's matcher follows when a simulation imports
it, so the two mostly agree; where they differ, the simulation's log says by how much.

The streets are read once from the city's cached street network, and the project is closed
straight away: the cache is what every run copies, and a project left open would keep its log
file locked in it.
"""
import threading

import geopandas as gpd
import numpy as np
import shapely
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from shapely.geometry import LineString, Point
from shapely.ops import substring

from core.network import release_log_files

_LOADED, _LOCK = {}, threading.Lock()
CANDIDATE_RADIUS_M = 50       # the streets a stop may be on: as far as the map matching looks
MAX_CANDIDATES = 15           # the nearest of them: an avenue is cut into many short links
OFF_STREET_WEIGHT = 2.0       # a metre between a stop and its street counts as this much route
SEARCH_LIMIT = (4.0, 2000.0)  # a leg's way is looked for up to 4 x the straight line + 2 km


class Streets:
    """The transit-mode links of a street network, in a metre CRS, with a spatial index."""

    def __init__(self, cache_dir):
        from aequilibrae import Project
        from aequilibrae.utils.geo_utils import metre_crs_for_gdf

        project = Project()
        project.open(cache_dir)
        try:
            links = project.network.links.data
        finally:
            project.close()
            release_log_files(cache_dir)
        net = gpd.GeoDataFrame(links[["link_id", "name", "modes", "a_node", "b_node",
                                      "direction"]], geometry=links.geometry, crs="EPSG:4326")
        net = net[net["modes"].astype(str).str.contains("t")].reset_index(drop=True)
        self.crs = metre_crs_for_gdf(net)
        self.lines = net.to_crs(self.crs).geometry.to_numpy()
        self.names = net["name"].fillna("").astype(str).to_numpy()
        self.tree = shapely.STRtree(self.lines)
        self._graph(net)

    def _graph(self, net):
        """The street graph: a link runs a -> b, and b -> a too unless it is one-way
        (direction 1). Its geometry runs from a to b. Lengths are measured in the metre CRS, so
        they match the distances along a link the path uses at its two ends."""
        nodes = np.unique(np.concatenate([net["a_node"], net["b_node"]]))
        index = {int(n): i for i, n in enumerate(nodes)}
        a = np.array([index[int(n)] for n in net["a_node"]])
        b = np.array([index[int(n)] for n in net["b_node"]])
        self.a, self.b = a, b
        self.two_way = net["direction"].to_numpy() == 0
        self.length = shapely.length(self.lines)
        # The shortest link between two nodes, and which way along it.
        best = {}
        for i in range(len(net)):
            for u, v, forward in ((a[i], b[i], True), (b[i], a[i], False)):
                if not forward and not self.two_way[i]:
                    continue
                if (u, v) not in best or self.length[i] < self.length[best[(u, v)][0]]:
                    best[(u, v)] = (i, forward)
        self.edge = best
        rows, cols = zip(*best)
        weights = [self.length[i] for i, _ in best.values()]
        self.matrix = csr_matrix((weights, (rows, cols)), shape=(len(nodes), len(nodes)))

    def _connected(self):
        """The links of the network's largest strongly connected part, and their index: a bus
        can come and go along them. OSM leaves islands - a car park's lanes, a gated estate - a
        stop on one of which no route reaches or leaves."""
        if not hasattr(self, "_main"):
            _, part = connected_components(self.matrix, directed=True, connection="strong")
            main = np.bincount(part).argmax()
            keep = np.flatnonzero((part[self.a] == main) & (part[self.b] == main))
            self._main = (keep, shapely.STRtree(self.lines[keep]))
            self._in_main = np.zeros(len(self.lines), bool)
            self._in_main[keep] = True
        return self._main

    def nearest(self, points, connected=False):
        """For each (lat, lon): metres to the nearest street, the closest point on it as
        (lat, lon), the street's name, and whether it is `cut_off` - on an island of streets no
        bus gets into or out of. `connected`: only the streets a bus can come and go along."""
        if not points:
            return []
        lonlat = gpd.GeoSeries([Point(lon, lat) for lat, lon in points], crs="EPSG:4326")
        metric = lonlat.to_crs(self.crs).to_numpy()
        keep, tree = self._connected()
        if connected:
            which = keep[np.atleast_1d(tree.nearest(metric))]
        else:
            which = self.tree.nearest(metric)
        out = []
        for point, i in zip(metric, np.atleast_1d(which)):
            line = self.lines[i]
            snapped = line.interpolate(line.project(point))
            out.append((float(point.distance(line)), snapped, self.names[i],
                        not self._in_main[i]))
        snaps = gpd.GeoSeries([s for _, s, _, _ in out], crs=self.crs).to_crs("EPSG:4326")
        return [{"metres": round(d, 1), "snap": [round(p.y, 6), round(p.x, 6)], "street": name,
                 "cut_off": bool(cut)} for (d, _, name, cut), p in zip(out, snaps)]

    def path(self, points):
        """The way along the streets through `points` [(lat, lon), ...] in order: a list of
        [lat, lon] and its length in km. A leg with no way along the streets is a straight
        line, and counted in `unrouted`."""
        metric = gpd.GeoSeries([Point(lon, lat) for lat, lon in points],
                               crs="EPSG:4326").to_crs(self.crs).to_numpy()
        candidates = [self._candidates(pt) for pt in metric]
        # Viterbi: for each candidate of each stop, the cheapest route to it so far, and from
        # which candidate of the stop before.
        cost = [[OFF_STREET_WEIGHT * d for _, _, d in candidates[0]]]
        back, legs = [[None] * len(candidates[0])], [None]
        for k in range(1, len(metric)):
            limit = SEARCH_LIMIT[0] * metric[k - 1].distance(metric[k]) + SEARCH_LIMIT[1]
            searches = [self._search(i, s, limit) for i, s, _ in candidates[k - 1]]
            row, row_back, row_legs = [], [], {}
            for b, (j, t, d) in enumerate(candidates[k]):
                best = (np.inf, None)
                for a, (i, s, _) in enumerate(candidates[k - 1]):
                    length = self._reach(searches[a], i, s, j, t)
                    if np.isfinite(length) and cost[k - 1][a] + length < best[0]:
                        best = (cost[k - 1][a] + length, a)
                row.append(best[0] + OFF_STREET_WEIGHT * d)
                row_back.append(best[1])
            cost.append(row)
            back.append(row_back)
            legs.append(searches)
        # The candidates chosen, from the last stop back - a stop no candidate of which can be
        # reached from the stop before falls back on its nearest, and that leg on a straight line.
        chosen = [int(np.argmin(cost[-1]))]
        for k in range(len(metric) - 1, 0, -1):
            prev = back[k][chosen[-1]]
            chosen.append(prev if prev is not None else 0)
        chosen.reverse()
        pieces, unrouted = [], 0
        for k in range(1, len(metric)):
            (i, s, _), (j, t, _) = candidates[k - 1][chosen[k - 1]], candidates[k][chosen[k]]
            leg = self._way(legs[k][chosen[k - 1]], i, s, j, t)
            if leg is None:
                leg, unrouted = LineString([metric[k - 1], metric[k]]), unrouted + 1
            pieces.append(leg)
        coords = []
        for piece in pieces:
            xy = list(piece.coords)
            coords += xy if not coords else xy[1:]
        line = gpd.GeoSeries([LineString(coords)], crs=self.crs)
        km = float(line.length.iloc[0]) / 1000
        lonlat = line.to_crs("EPSG:4326").iloc[0]
        return {"path": [[round(y, 6), round(x, 6)] for x, y in lonlat.coords],
                "km": round(km, 2), "unrouted": unrouted,
                # Between each point and the next: what a leg's running time is measured on.
                "pieces_km": [round(piece.length / 1000, 4) for piece in pieces]}

    def _candidates(self, point):
        """[(link, position along it, metres from the stop)]: the streets within
        CANDIDATE_RADIUS_M, nearest first, at most MAX_CANDIDATES - the nearest one if none is."""
        near = self.tree.query(point, predicate="dwithin", distance=CANDIDATE_RADIUS_M)
        if len(near) == 0:
            near = [self.tree.nearest(point)]
        found = sorted(((int(i), float(self.lines[i].project(point)),
                         float(self.lines[i].distance(point))) for i in near), key=lambda c: c[2])
        return found[:MAX_CANDIDATES]

    def _search(self, i, s, limit):
        """The shortest ways out from position `s` along link `i`: leave it at its b end (always)
        or its a end (two-way only); one Dijkstra search for every candidate of the next stop."""
        starts = [(self.b[i], self.length[i] - s, True)]
        if self.two_way[i]:
            starts.append((self.a[i], s, False))
        dist, pred = dijkstra(self.matrix, indices=[u for u, _, _ in starts],
                              return_predecessors=True, limit=limit)
        return starts, dist, pred

    def _ends(self, j, t):
        """Reach position `t` along link `j` at its a end (always) or its b end (two-way only)."""
        ends = [(self.a[j], t, True)]
        if self.two_way[j]:
            ends.append((self.b[j], self.length[j] - t, False))
        return ends

    def _reach(self, search, i, s, j, t):
        """Metres from `s` along link `i` to `t` along link `j` - inf if there is no way."""
        if i == j and (t >= s or self.two_way[i]):
            return abs(t - s)                                # along the one link
        starts, dist, _ = search
        return min((cost_u + dist[k, v] + cost_v for k, (_, cost_u, _) in enumerate(starts)
                    for v, cost_v, _ in self._ends(j, t)), default=np.inf)

    def _way(self, search, i, s, j, t):
        """The line of the way `_reach` measured, or None if there is none."""
        if i == j and (t >= s or self.two_way[i]):
            return substring(self.lines[i], s, t)
        starts, dist, pred = search
        best = None
        for k, (u, cost_u, out_forward) in enumerate(starts):
            for v, cost_v, in_forward in self._ends(j, t):
                total = cost_u + dist[k, v] + cost_v
                if np.isfinite(total) and (best is None or total < best[0]):
                    best = (total, k, u, v, out_forward, in_forward)
        if best is None:
            return None
        _, k, u, v, out_forward, in_forward = best
        nodes = [v]
        while nodes[-1] != u:
            nodes.append(pred[k, nodes[-1]])
        nodes.reverse()
        first, last = self.lines[i], self.lines[j]
        parts = [substring(first, s, first.length if out_forward else 0)]
        for x, y in zip(nodes, nodes[1:]):
            link, forward = self.edge[(x, y)]
            parts.append(self.lines[link] if forward else self.lines[link].reverse())
        parts.append(substring(last, 0 if in_forward else last.length, t))
        coords = []
        for part in parts:
            xy = list(part.coords) if part.length > 0 else []
            coords += xy if not coords else xy[1:]
        return LineString(coords) if len(coords) > 1 else None


def streets_for(cache_dir):
    """The streets of one cache, read the first time they are asked for."""
    with _LOCK:
        if cache_dir not in _LOADED:
            _LOADED[cache_dir] = Streets(cache_dir)
        return _LOADED[cache_dir]


def line_paths(lines, streets, matched_route_types):
    """{(line key, direction): the way along the streets} for every line of a matched route type
    (the buses) - through its via points where the design shaped its route - as streets.path
    gives it, with `leg_km` each stop-to-stop leg's length along it - [(lat, lon), ...] with its km and unrouted legs. The
    design map draws them, and the feed's shapes.txt carries them."""
    from .gtfs import directions
    out = {}
    for key, line in lines.items():
        if line["route_type"] not in matched_route_types:
            continue
        via = line.get("via") or {}
        for direction, stops in enumerate(directions(line)):
            # The stops, and between two the via points the design shaped that leg with.
            points = []
            for k, (_, lat, lon, _) in enumerate(stops):
                points.append((lat, lon))
                if k < len(stops) - 1:
                    points += via.get((direction, k), [])
            found = streets.path(points)
            # Each stop-to-stop leg's km: its pieces, through its via points.
            found["leg_km"], at = [], 0
            for k in range(len(stops) - 1):
                n = len(via.get((direction, k), [])) + 1
                found["leg_km"].append(round(sum(found["pieces_km"][at:at + n]), 4))
                at += n
            out[(key, direction)] = found
    return out
