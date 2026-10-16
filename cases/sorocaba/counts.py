"""Sorocaba section F: the model against ARTESP's traffic counts on the highways.

- **toll gantries and plazas, by the hour** - lot L33, Rota Sorocabana
- **SAT stations, by the day** - ARTESP's automatic counters

Only light vehicles are compared (the gantries' *leve* classes and SAT's *passeio*), each the
**median weekday** of January to August 2026. A SAT daily count is turned into the peak hour with
the share of the day the gantries count in COUNT_HOUR.

F7 finds the REGIONAL_TRIP_FACTOR and THROUGH_TRIPS the edge counts ask for, given THROUGH_SHARE.
They are **not applied**: they are printed next to the settings, to be copied there by hand. The
edge counts (EDGE_COUNTS) calibrate them, so they match by construction: the other counts are the
check, and F3 says the two apart.
"""
import os
import re

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import shapely

from core import report
from core.maps import link_frame
from core.network import overpass

from . import maps as smaps

# road -> (OSM ref, the road's name in the network, the direction in which its km increase)
COUNT_ROADS = {"SP270": ("SP-270", "Rodovia Raposo Tavares", "OESTE"),
               "SP075": ("SP-075", "Rodovia Senador José Ermírio de Moraes", "NORTE"),
               "SP264": ("SP-264", "Rodovia João Leme dos Santos", "SUL"),
               "SP280": ("SP-280", "Rodovia Presidente Castelo Branco", "OESTE")}
# Where the gantries are. ARTESP's files name them, not where they stand. The SP-270 kms are the
# concessionaire's: charging at km 48+980, 82+600 and 111+850, counting only at 37, 58, 72, 95 and
# 101 (Sem Parar, "Free Flow Raposo Tavares"; Portal Olá, 2025). The SP-075 plaza is at km
# 13+325. Gantry 16, on the SP-264 south of the city, has no published km but lends its road's
# peak-hour share.
GANTRY_AT = {"PÓRTICO 23 - COTIA": ("SP270", 37.0), "PÓRTICO 06 - SÃO ROQUE": ("SP270", 48.98),
             "PÓRTICO 07 - SÃO ROQUE": ("SP270", 58.0), "PÓRTICO 08 - MAIRIQUE": ("SP270", 72.0),
             "PÓRTICO 09 - SOROCABA": ("SP270", 82.6), "PÓRTICO 10 - SOROCABA": ("SP270", 95.0),
             "PÓRTICO 11 - SOROCABA": ("SP270", 101.0),
             "PÓRTICO 12 - ARAÇOIABA": ("SP270", 111.85),
             "SOROCABA": ("SP075", 13.325),
             "PÓRTICO 16 - PIRAPORA": ("SP264", np.nan)}
MIN_SAT_DAYS = 30          # a SAT direction counted on fewer weekdays is not used
SAME_SITE_KM = 0.04        # detectors this close, renumbered over the year, are one station
LOPSIDED = 0.3             # a direction under this share of the other is a faulty detector
NEAR_GANTRY_KM = 0.2       # a SAT station this close to a gantry repeats its count
POST_SNAP_M = 80           # how far a post may stand from its road's centre line in the network
EDGE_INTERNAL_SHARE = 0.25     # internal trips' share of the model's flow at an edge count, at most
UNIT_THROUGH = 1000            # through trips: F7's numbers are per this many
# The edge rule's choice at the start, with commuting only; F3's sites and directions. Listed, so
# that setting the edges cannot move the edges.
EDGE_COUNTS = {("PÓRTICO 09 - SOROCABA", "LESTE"), ("PÓRTICO 09 - SOROCABA", "OESTE"),
               ("SAT SP-075 km 8.8", "NORTE"), ("SAT SP-075 km 8.8", "SUL"),
               ("SAT SP-264 km 104.9", "NORTE"), ("SAT SP-264 km 111.0", "SUL"),
               ("SAT SP-270 km 85.7", "LESTE"), ("SAT SP-270 km 85.7", "OESTE"),
               ("SAT SP-270 km 102.0", "LESTE"), ("SAT SP-270 km 104.2", "LESTE"),
               ("SAT SP-270 km 105.2", "LESTE")}


def weekdays(frame):
    frame["DATA"] = pd.to_datetime(frame["DATA"])
    return frame[frame["DATA"].dt.dayofweek < 5]


def read_counts(m):
    """F1. The counts: gantries by the hour, SAT stations by the day made hourly."""
    report.section("F1. The counts")
    hour = m.s.COUNT_HOUR
    toll = weekdays(pd.read_csv(m.files["toll_hourly"], low_memory=False))
    toll["light"] = toll[[c for c in toll.columns if c.startswith("LEVE")]].sum(axis=1)
    day = toll.groupby(["PRACA", "SENTIDO", "DATA"])["light"].sum()
    in_hour = toll[toll["HORA"] == hour].groupby(["PRACA", "SENTIDO", "DATA"])["light"].sum()
    gantry = pd.DataFrame({
        "count": in_hour.groupby(["PRACA", "SENTIDO"]).median(),
        "daily": day.groupby(["PRACA", "SENTIDO"]).median(),
        "hour_share": (in_hour / day).groupby(["PRACA", "SENTIDO"]).median(),
        "days": in_hour.groupby(["PRACA", "SENTIDO"]).size()}).reset_index()
    gantry = gantry[gantry["PRACA"].isin(GANTRY_AT)].rename(
        columns={"PRACA": "site", "SENTIDO": "dir"})
    gantry["road"] = gantry["site"].map(lambda p: GANTRY_AT[p][0])
    gantry["km"] = gantry["site"].map(lambda p: GANTRY_AT[p][1])
    gantry["source"] = "gantry"
    print(f"gantries and plazas, weekdays, light vehicles, {hour:02d}:00-{hour + 1:02d}:00:")
    print(gantry[["site", "road", "km", "dir", "days", "daily", "count", "hour_share"]]
          .round({"daily": 0, "count": 0, "hour_share": 3}).to_string(index=False))

    sat = weekdays(pd.read_csv(m.files["sat_daily"]))
    sat = sat[sat["CONCESSIONARIA"].str.startswith("L33") & sat["RODOVIA"].isin(COUNT_ROADS)
              & (sat["MARGINAL"] == "NÃO")].copy()
    sat["km"] = sat["KM"] + sat["COMPLEMENTO"] / 1000
    sat = sat.sort_values(["RODOVIA", "km"])
    sat["station"] = (sat.groupby("RODOVIA")["km"].diff().fillna(1) > SAME_SITE_KM).cumsum()
    # one median per detector, then one figure per station: the mean of its detectors
    det = (sat.groupby(["RODOVIA", "station", "KM", "COMPLEMENTO", "SENTIDO"])
           .agg(km=("km", "first"), daily=("QTD_PASSEIO", "median"), days=("QTD_PASSEIO", "size"))
           .reset_index())
    det = det[det["days"] >= MIN_SAT_DAYS]
    sat_counts = (det.groupby(["RODOVIA", "station", "SENTIDO"])
                  .agg(km=("km", "mean"), daily=("daily", "mean"), days=("days", "sum"))
                  .reset_index().rename(columns={"RODOVIA": "road", "SENTIDO": "dir"}))
    other = sat_counts.groupby(["road", "station"])["daily"].transform("max")
    sat_counts["suspect"] = sat_counts["daily"] < LOPSIDED * other
    # The share of the day in the counted hour: the gantries' on the same road and direction,
    # else the road's, else all gantries'.
    share = gantry.groupby(["road", "dir"])["hour_share"].median()
    share_road = gantry.groupby("road")["hour_share"].median()
    share_all = gantry["hour_share"].median()
    sat_counts["hour_share"] = [share.get((r, d), share_road.get(r, share_all))
                                for r, d in zip(sat_counts["road"], sat_counts["dir"])]
    sat_counts["count"] = sat_counts["daily"] * sat_counts["hour_share"]
    sat_counts["site"] = [f"SAT {r[:2]}-{r[2:]} km {k:.1f}"
                          for r, k in zip(sat_counts["road"], sat_counts["km"])]
    sat_counts["source"] = "SAT"
    dup = np.zeros(len(sat_counts), bool)
    for g in gantry.dropna(subset=["km"]).itertuples():
        dup |= ((sat_counts["road"] == g.road)
                & ((sat_counts["km"] - g.km).abs() < NEAR_GANTRY_KM)).to_numpy()
    sat_counts = sat_counts[~dup]
    print(f"\nSAT stations on these roads: {sat_counts['station'].nunique()} "
          f"({dup.sum()} directions dropped as repeating a gantry's count)")
    for r in sat_counts[sat_counts["suspect"]].itertuples():
        print(f"  not used, a faulty detector: {r.site} {r.dir}, {r.daily:,.0f} a day against "
              f"{other[r.Index]:,.0f} the other way")
    return pd.concat([gantry.dropna(subset=["km"]), sat_counts[~sat_counts["suspect"]]],
                     ignore_index=True)


def place_counts(m, counts):
    """F2. Where they are: a count is placed by walking the carriageway in its direction between
    the OSM km posts on either side and going the right fraction of the way."""
    report.section("F2. Where they are")
    crs = m.metre_crs
    posts_path = m.paths.cached("osm_km_posts.parquet")
    if os.path.exists(posts_path):
        km_posts = pd.read_parquet(posts_path)
    else:
        w, s, e, n = link_frame(m.model, "link_id").total_bounds
        pad = 0.1          # degrees: the posts either side of a count near the network's edge
        found = overpass(f'[out:json][timeout:300];node["highway"="milestone"]'
                         f'({s - pad:.4f},{w - pad:.4f},{n + pad:.4f},{e + pad:.4f});out;')
        rows = []
        for el in found:
            num = re.search(r"\d+(?:[.,]\d+)?", el.get("tags", {}).get("distance", ""))
            ref = el.get("tags", {}).get("ref")
            if num and ref:
                rows.append({"ref": ref.split(";")[0].strip(),
                             "km": float(num.group().replace(",", ".")),
                             "lon": el["lon"], "lat": el["lat"]})
        km_posts = pd.DataFrame(rows)
        km_posts.to_parquet(posts_path)
    p = gpd.GeoSeries(gpd.points_from_xy(km_posts["lon"], km_posts["lat"]),
                      crs="EPSG:4326").to_crs(crs)
    km_posts["x"], km_posts["y"] = p.x.to_numpy(), p.y.to_numpy()
    # A post often stands on each carriageway; their mean is the road's.
    post_at = km_posts.groupby(["ref", "km"])[["x", "y"]].mean()
    for road, (ref, _, _) in COUNT_ROADS.items():
        ks = post_at.loc[ref].index if ref in post_at.index.get_level_values(0) else []
        print(f"{road}: {len(ks)} km posts" + (f", km {min(ks):.0f} to {max(ks):.0f}, widest gap "
                                               f"{np.diff(sorted(ks)).max():.0f} km"
                                               if len(ks) else ""))

    # The carriageways as a directed graph, each edge a link in one direction with its flow.
    net = link_frame(m.model, "link_id, a_node, b_node, direction, link_type, name").to_crs(crs)
    net = net.merge(m.flows[["link_id", "car_ab", "car_ba"]], on="link_id", how="left")
    net = net[net["link_type"].isin(["motorway", "trunk", "primary", "motorway_link",
                                     "trunk_link", "primary_link"])]
    road_names = {v[1] for v in COUNT_ROADS.values()}
    carriageways = nx.DiGraph()
    for lk in net.itertuples():
        # Off the road's own name a metre costs three, so the walk keeps to the road.
        cost = lk.geometry.length * (1 if lk.name in road_names else 3)
        if lk.direction >= 0:
            carriageways.add_edge(lk.a_node, lk.b_node, w=cost, link_id=lk.link_id, name=lk.name,
                                  flow=lk.car_ab, side="ab", geom=lk.geometry)
        if lk.direction <= 0:
            carriageways.add_edge(lk.b_node, lk.a_node, w=cost, link_id=lk.link_id, name=lk.name,
                                  flow=lk.car_ba, side="ba", geom=lk.geometry.reverse())
    edges = list(carriageways.edges(data=True))

    def edges_by(post, road_name):
        pt = shapely.Point(post)
        return [(u, v, e, e["geom"].project(pt)) for u, v, e in edges
                if e["name"] == road_name and e["geom"].distance(pt) < POST_SNAP_M]

    def place(road, km, increasing):
        ref, name, _ = COUNT_ROADS[road]
        if ref not in post_at.index.get_level_values(0):
            return None
        posts = post_at.loc[ref]
        ks = posts.index.to_numpy()
        if not (ks <= km).any() or not (ks > km).any():
            return None
        lo, hi = ks[ks <= km].max(), ks[ks > km].min()
        start, end = (lo, hi) if increasing else (hi, lo)
        leave, reach = edges_by(posts.loc[start], name), edges_by(posts.loc[end], name)
        if not leave or not reach:
            return None
        walk = None
        for _, _, e, s in leave:              # both posts on one edge
            for _, _, e2, s2 in reach:
                if e2 is e and s2 > s:
                    walk = [(e, s, s2)]
        if walk is None:
            g = carriageways.copy()
            first, last = {}, {}
            for u, v, e, s in leave:
                if v not in first or e["geom"].length - s < first[v][2] - first[v][1]:
                    first[v] = (e, s, e["geom"].length)
                    g.add_edge("from", v, w=e["geom"].length - s)
            for u, v, e, s in reach:
                if u not in last or s < last[u][2]:
                    last[u] = (e, 0.0, s)
                    g.add_edge(u, "to", w=s)
            try:
                path = nx.shortest_path(g, "from", "to", weight="w")
            except nx.NetworkXNoPath:
                return None
            walk = ([first[path[1]]]
                    + [(carriageways.edges[a, b], 0.0, carriageways.edges[a, b]["geom"].length)
                       for a, b in zip(path[1:-2], path[2:-1])]
                    + [last[path[-2]]])
        length = sum(t - f for _, f, t in walk)
        target = length * (km - start) / (end - start)
        for e, f, t in walk:
            if target <= t - f:
                return {"edge": e, "point": e["geom"].interpolate(f + target),
                        "posts_km": hi - lo, "walk_m": length}
            target -= t - f
        return None

    def heading(line, point, half=15):
        s = line.project(point)
        a, b = line.interpolate(max(s - half, 0)), line.interpolate(min(s + half, line.length))
        v = np.array([b.x - a.x, b.y - a.y])
        return v / (np.linalg.norm(v) or 1)

    def side_lanes(point, road_name, along, radius=150):
        """Cars on the road's marginais alongside, going the same way: the counts are of the
        main carriageway, but the model may have put the same traffic on the side lanes."""
        return max([e["flow"] for _, _, e in edges
                    if str(e["name"]).startswith(road_name) and "Marginal" in str(e["name"])
                    and e["geom"].distance(point) < radius
                    and heading(e["geom"], point) @ along > 0.5] + [0.0])

    placed = []
    for c in counts.itertuples():
        inc = c.dir == COUNT_ROADS[c.road][2]
        hit = place(c.road, c.km, inc)
        if hit is None or hit["edge"]["name"] != COUNT_ROADS[c.road][1]:
            continue
        e, pt = hit["edge"], hit["point"]
        placed.append({"site": c.site, "source": c.source, "road": c.road, "km": c.km,
                       "dir": c.dir, "count": c.count, "daily": c.daily,
                       "hour_share": c.hour_share, "model": e["flow"],
                       "model_side_lanes": side_lanes(pt, e["name"], heading(e["geom"], pt)),
                       "link_id": e["link_id"], "side": e["side"], "posts_km": hit["posts_km"],
                       "in_city": m.city.contains(pt), "x": pt.x, "y": pt.y})
    compared = pd.DataFrame(placed)
    compared["model"] = compared["model"].fillna(0)
    print(f"{len(compared)} of {len(counts)} counted directions fall on the modelled network; the "
          f"rest are beyond it")
    # Past a gateway, in the strip of network outside the city limit, the model carries nothing.
    beyond = ~compared["in_city"] & (compared["model"] == 0)
    for r in compared[beyond].itertuples():
        print(f"  not compared, beyond the gateway: {r.site} {r.dir}")
    return compared[~beyond].reset_index(drop=True)


def geh(model, count):
    return np.sqrt(2 * (model - count) ** 2 / (model + count))


def compare(m, compared):
    """F3-F4. Model against count: GEH under 5 is a good match, over 10 a poor one."""
    report.section("F3. Model against count")
    compared["geh"] = np.sqrt(2 * (compared["model"] - compared["count"]) ** 2
                              / (compared["model"] + compared["count"]).replace(0, np.nan))
    compared["ratio"] = compared["model"] / compared["count"]
    # The edge counts set the region's traffic (F7): those match by construction, the rest check.
    compared["calibrates"] = [(site, d) in EDGE_COUNTS for site, d in zip(compared["site"],
                                                                          compared["dir"])]
    print(f"{'site':<24}{'dir':<7}{'counted':>8}{'model':>8}{'+side':>7}{'ratio':>7}{'GEH':>6}  where")
    for r in compared.sort_values(["road", "km", "dir"]).itertuples():
        print(f"{r.site[:23]:<24}{r.dir:<7}{r.count:>8,.0f}{r.model:>8,.0f}"
              f"{r.model_side_lanes:>7,.0f}{r.ratio:>7.2f}{r.geh:>6.1f}  "
              f"{'city' if r.in_city else 'margin'}")
    print(f"\nGEH under 5: {(compared['geh'] < 5).mean():.0%} of {len(compared)} counts; "
          f"under 10: {(compared['geh'] < 10).mean():.0%}")
    for used, said in ((True, "the edge counts, which calibrate the region's traffic (F7) - "
                              "matched by construction"),
                       (False, "the others, the check")):
        g = compared[compared["calibrates"] == used]
        if len(g):
            print(f"  {said}: {len(g)} counts, model/count {g['model'].sum() / g['count'].sum():.2f}, "
                  f"GEH under 5 {(g['geh'] < 5).mean():.0%}, median GEH {g['geh'].median():.0f}")
    print(f"model over count, summed: {compared['model'].sum() / compared['count'].sum():.2f}  "
          f"(with the side lanes alongside: "
          f"{(compared['model'] + compared['model_side_lanes']).sum() / compared['count'].sum():.2f})")
    for road, g in compared.groupby("road"):
        print(f"  {road}: {len(g):>2} counts, model/count {g['model'].sum() / g['count'].sum():.2f}, "
              f"median GEH {g['geh'].median():.0f}")
    for where, g in compared.groupby("in_city"):
        print(f"  {'inside the city limit' if where else 'in the margin beyond it'}: {len(g)} "
              f"counts, model/count {g['model'].sum() / g['count'].sum():.2f}")
    report.section("F4. The counts on the map")
    smaps.map_counts(m.maps, compared, m.boundary, m.s.COUNT_HOUR)


def levers(m, compared):
    """F6. Which lever can close the gap: the matrix re-assigned a few ways."""
    report.section("F6. Which lever can close the gap")
    free = m.links.set_index("link_id")[["travel_time_ab", "travel_time_ba", "link_type"]]
    count = compared["count"].to_numpy()
    city_c = compared["in_city"].to_numpy()

    def against_counts(matrix, label):
        res = m.assigner.solve(matrix, label)
        flow = np.nan_to_num(np.array([res[f"car_{s}"].get(lk, 0.0)
                                       for lk, s in zip(compared["link_id"], compared["side"])],
                                      float))
        r = res.join(free, how="left")
        r = r[r["link_type"] != "external_access"]
        busy = (r["car_ab"].fillna(0) * r["Congested_Time_AB"].fillna(0)
                + r["car_ba"].fillna(0) * r["Congested_Time_BA"].fillna(0)).sum()
        empty = (r["car_ab"].fillna(0) * r["travel_time_ab"].fillna(0)
                 + r["car_ba"].fillna(0) * r["travel_time_ba"].fillna(0)).sum()
        return flow, {"matrix": label, "car trips": matrix.sum(),
                      "model/count": flow.sum() / count.sum(),
                      "in the city": flow[city_c].sum() / count[city_c].sum(),
                      "GEH<5": (geh(flow, count) < 5).mean(), "congestion": busy / empty - 1}

    inside = m.is_internal
    internal_part = m.demand - m.external - m.through
    longest = m.external + m.through
    longest[np.ix_(inside, inside)] = m.gravity.matrix(m.s.BETA_FLOOR)
    longest_min = m.gravity.mean_trip_minutes(longest[np.ix_(inside, inside)])
    rows = []
    for label, matrix in [("baseline", m.demand), ("internal trips only", internal_part),
                          ("external trips only", m.external + m.through),
                          ("internal trips x2", m.demand + internal_part),
                          ("internal trips x3", m.demand + 2 * internal_part),
                          (f"internal trips at {longest_min:.1f} min", longest)]:
        _, row = against_counts(matrix, label)
        rows.append(row)
    print()
    print(pd.DataFrame(rows).to_string(index=False, formatters={
        "car trips": "{:,.0f}".format, "model/count": "{:.2f}".format,
        "in the city": "{:.2f}".format, "GEH<5": "{:.0%}".format, "congestion": "{:.0%}".format}))


def edges(m, compared):
    """F7. The region's traffic, set at the edges.

    At each edge count, the count is the sum of the internal trips' flow, the commuters', the
    region's other trips (REGIONAL_TRIP_FACTOR less one times the commuters') and the through
    trips'. The edge traffic beyond the model's commuting is split by THROUGH_SHARE, and each
    share fixes one number. The values found are printed next to the settings, not applied.

    Each part's flow is its share of the baseline's own equilibrium: the matrix assigned once,
    its internal, external and through trips each a class (Assigner.solve_classes) - where they
    go among each other's traffic. Assigned alone, the through trips would have the roads to
    themselves, and an equilibrium solver finds no gap to close on an empty network.
    """
    report.section("F7. The region's traffic, set at the edges")
    s = m.s
    count = compared["count"].to_numpy()
    # A city with no through trips set still needs where they would go: one vehicle of them.
    through = m.through if m.through.sum() > 0 else m.through_pattern
    res = m.assigner.solve_classes({"internal": m.demand - m.external - m.through,
                                    "external": m.external, "through": through},
                                   "the matrix by its parts")

    def at_counts(name):
        return np.nan_to_num(np.array([res[f"{name}_{side}"].get(lk, 0.0) for lk, side in
                                       zip(compared["link_id"], compared["side"])], float))
    flow_internal = at_counts("internal")
    flow_commuting = at_counts("external") / s.REGIONAL_TRIP_FACTOR
    flow_through = at_counts("through") * UNIT_THROUGH / through.sum()
    edge = np.array([(site, d) in EDGE_COUNTS for site, d in zip(compared["site"], compared["dir"])])
    by_rule = flow_internal < EDGE_INTERNAL_SHARE * (flow_internal + flow_commuting)
    if edge.sum() != len(EDGE_COUNTS):
        raise ValueError("an edge count in the list is no longer among the counts compared")
    for r in compared[by_rule != edge].itertuples():
        print(f"  the rule would now {'add' if by_rule[r.Index] else 'drop'} {r.site} {r.dir} - "
              f"kept as listed")
    beyond = count[edge].sum() - flow_internal[edge].sum() - flow_commuting[edge].sum()
    print(f"\nedge counts: {edge.sum()} directions at {compared.loc[edge, 'site'].nunique()} "
          f"stations")
    for r, i, c in zip(compared[edge].itertuples(), flow_internal[edge], flow_commuting[edge]):
        print(f"  {r.site[:24]:<25}{r.dir:<7} counted {r.count:>6,.0f}   internal {i:>5,.0f}   "
              f"commuting {c:>5,.0f}")
    print(f"counted at the edges beyond the model's commuting: {beyond:,.0f} vehicles an hour")

    def edge_split(share):
        factor = 1 + (1 - share) * beyond / flow_commuting[edge].sum()
        trips = share * beyond / flow_through[edge].sum() * UNIT_THROUGH
        return factor, trips

    factor, trips = edge_split(s.THROUGH_SHARE)
    print(f"\nwith THROUGH_SHARE = {s.THROUGH_SHARE:.0%}, the edge counts ask for:")
    print(f"  REGIONAL_TRIP_FACTOR = {factor:.2f}   (set: {s.REGIONAL_TRIP_FACTOR:.2f})")
    print(f"  THROUGH_TRIPS        = {trips:,.0f}   (set: {s.THROUGH_TRIPS:,.0f})")
    if (abs(factor - s.REGIONAL_TRIP_FACTOR) > 0.05 * factor
            or abs(trips - s.THROUGH_TRIPS) > max(0.05 * trips, 25)):
        print(f"  ** not what the settings hold: set REGIONAL_TRIP_FACTOR = {factor:.2f} and "
              f"THROUGH_TRIPS = {trips:,.0f} in cases/sorocaba/settings.py and run again")
    else:
        print("  - what the settings hold")
    print(f"\n{'through share':<15}{'factor':>8}{'through':>9}{'edges':>8}{'elsewhere':>11}"
          f"{'GEH<5':>7}")
    for sh in sorted({0.0, s.THROUGH_SHARE, 0.6}):
        f, t = edge_split(sh)
        flow = flow_internal + f * flow_commuting + t / UNIT_THROUGH * flow_through
        print(f"{sh:<15.0%}{f:>8.2f}{t:>9,.0f}{flow[edge].sum() / count[edge].sum():>8.2f}"
              f"{flow[~edge].sum() / count[~edge].sum():>11.2f}{(geh(flow, count) < 5).mean():>7.0%}")


def run(m, ex):
    if m.demand_transformed:
        # The counts are a weekday's, at COUNT_HOUR: another day or hour is not theirs.
        print("The run models another day or hour than the counts' weekday morning, so it is not "
              "set against them.")
        return
    counts = read_counts(m)
    compared = place_counts(m, counts)
    compare(m, compared)
    if m.demand_loaded:
        # The levers and the edge calibration take the model's matrix apart (internal, external,
        # through, the gravity model's spread): a loaded matrix has none of those parts.
        print("\nThe matrix is loaded: the levers and the edge calibration (F6-F7), which take "
              "the model's own matrix apart, are left out.")
    elif m.edits:
        # They calibrate the base's settings, with three more assignments: its run's to make.
        print(f"\nA scenario: the levers and the edge calibration (F6-F7) are its base's "
              f"({m.base_run}), and are left out.")
    else:
        levers(m, compared)
        edges(m, compared)
    xy = gpd.GeoSeries(gpd.points_from_xy(compared["x"], compared["y"]),
                       crs=m.metre_crs).to_crs(4326)
    ex.csv(compared.drop(columns=["x", "y"]).assign(lon=xy.x.to_numpy(), lat=xy.y.to_numpy()),
           "count_comparison.csv", index=False)
