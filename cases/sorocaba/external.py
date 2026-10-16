"""Sorocaba's traffic across the city limit: gateways, cordon zones, the regional roads, and the
external zones that replace the cordon zones.

A **gateway** is one road at one place where it crosses the city limit, with everything that lets
traffic through there in both directions. External traffic enters and leaves the model there.
"""
import json
import os
from collections import deque

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import breadth_first_order, connected_components, dijkstra
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point

from core import report
from core.connectors import insert_connectors
from core.maps import link_frame
from core.network import node_frame, overpass
from core.skim import skim_zones

from .inputs import VOTORANTIM

TRACE_LINKS = 15               # how many unnamed links the trace to a named road may follow
CORDON_OFFSET_M = 150          # how far outside its road nodes a cordon centroid is placed
REGIONAL_CLASSES = ["motorway", "motorway_link", "trunk", "trunk_link", "primary",
                    "primary_link", "secondary", "secondary_link"]
RING_BANDS = ["inner", "outer"]
SLIVER_SHARE = 0.01            # a piece of a drawn outline under this share of it is a sliver
MUNI_KINDS = ["municipality", "Votorantim", "pooled"]
BORDER_TOLERANCE_M = 1         # the census mesh tiles exactly; this only absorbs rounding
MIN_SHARED_BORDER_M = 5        # the least common border that makes two places neighbours
COMPASS = ["east", "north-east", "north", "north-west", "west", "south-west", "south",
           "south-east"]


# --- E2. Where the roads leave the city ---------------------------------------------------------
def find_gateways(m, project):
    """One gateway per road per place it crosses the city limit: carriageways and slip roads.

    The crossings are grouped by **what they are**, not by how far apart they lie:
    1. a two-way crossing is a gateway on its own
    2. a one-way crossing is paired with the carriageway of the same road running the other way,
       when each is the other's nearest
    3. an unnamed crossing is traced along the network to the named road it belongs to
    4. a carriageway left without a partner joins the nearest gateway of its own road
    5. gateways leaving the city through the same node outside it become one
    Every gateway is then checked against the network: traffic must be able to enter and leave
    through it into the part where everywhere reaches everywhere. A gateway failing the check
    joins the nearest working gateway of its road, or is dropped.
    """
    crs, city, roads_kept = m.metre_crs, m.city, m.s.GATEWAY_ROADS
    links = link_frame(project).to_crs(crs).reset_index(drop=True)
    nodes = node_frame(project)
    nodes_m = gpd.GeoSeries(gpd.points_from_xy(nodes["lon"], nodes["lat"]), crs="EPSG:4326",
                            index=nodes["node_id"]).to_crs(crs)
    inside = nodes_m.within(city)
    links["name"] = links["name"].where(links["name"].astype(str).str.strip() != "")
    base = links["link_type"].str.replace("_link", "", regex=False)

    crossing = links[base.isin(roads_kept) & links.geometry.crosses(city)].copy()
    crossing = crossing[crossing["a_node"].map(inside) != crossing["b_node"].map(inside)]
    a_in = crossing["a_node"].map(inside).astype(bool)
    crossing["outer"] = np.where(a_in, crossing["b_node"], crossing["a_node"])
    # direction 1 runs a->b, -1 runs b->a, 0 both ways; inbound means towards the inside node.
    crossing["sense"] = np.where(crossing["direction"] == 0, "both",
                                 np.where((crossing["direction"] == 1) != a_in, "in", "out"))
    points = [g.intersection(city.boundary) for g in crossing.geometry]
    crossing["x"] = [p.centroid.x for p in points]
    crossing["y"] = [p.centroid.y for p in points]

    # Rule 3: an unnamed crossing belongs to the named road it leads onto. Among the named roads
    # within reach that themselves cross the city limit, one of the crossing's own class is
    # preferred, then the nearest; a road that does not cross the limit is the last resort.
    at_node = {}
    for i, a, b in zip(links.index, links["a_node"], links["b_node"]):
        at_node.setdefault(a, []).append(i)
        at_node.setdefault(b, []).append(i)
    crossing_roads = set(crossing["name"].dropna())
    significant = set(roads_kept) | {"tertiary"}

    def owner(i):
        own_class = base.at[i]
        seen, queue, first, found = {i}, deque([(i, 0)]), None, []
        while queue:
            k, hops = queue.popleft()
            for n in (links.at[k, "a_node"], links.at[k, "b_node"]):
                for j in at_node[n]:
                    if j in seen:
                        continue
                    seen.add(j)
                    name = links.at[j, "name"]
                    if pd.notna(name) and name in crossing_roads:
                        found.append((base.at[j] != own_class, hops, name))
                    elif pd.notna(name) and first is None:
                        first = name
                    if hops < TRACE_LINKS and base.at[j] in significant:
                        queue.append((j, hops + 1))
        return min(found)[2] if found else first

    crossing["road"] = crossing["name"]
    crossing["traced"] = crossing["road"].isna()
    for i in crossing.index[crossing["traced"]]:
        crossing.loc[i, "road"] = owner(i)
    crossing["road"] = crossing["road"].fillna("unnamed")

    # Rules 1, 2 and 4, road by road.
    crossing["gateway"] = -1
    crossing["pair_m"] = np.nan
    crossing["joined_m"] = np.nan
    next_gate = 0
    for road_name, part in crossing.groupby("road"):
        for i in part.index[part["sense"] == "both"]:
            crossing.loc[i, "gateway"] = next_gate
            next_gate += 1
        ins, outs = part[part["sense"] == "in"], part[part["sense"] == "out"]
        if len(ins) and len(outs):
            gap = np.hypot(ins["x"].to_numpy()[:, None] - outs["x"].to_numpy()[None, :],
                           ins["y"].to_numpy()[:, None] - outs["y"].to_numpy()[None, :])
            for a in range(len(ins)):
                b = int(gap[a].argmin())
                if int(gap[:, b].argmin()) == a:        # each is the other's nearest
                    crossing.loc[[ins.index[a], outs.index[b]], "gateway"] = next_gate
                    crossing.loc[[ins.index[a], outs.index[b]], "pair_m"] = gap[a, b]
                    next_gate += 1
        for i in part.index[crossing.loc[part.index, "gateway"] < 0]:
            same = crossing[(crossing["road"] == road_name) & (crossing["gateway"] >= 0)]
            if len(same):
                away = np.hypot(same["x"] - crossing.at[i, "x"], same["y"] - crossing.at[i, "y"])
                crossing.loc[i, "gateway"] = same["gateway"].loc[away.idxmin()]
                crossing.loc[i, "joined_m"] = away.min()
            else:
                crossing.loc[i, "gateway"] = next_gate
                next_gate += 1

    # Rule 5: one node outside, one way out.
    ids = sorted(crossing["gateway"].unique())
    seat = {g: i for i, g in enumerate(ids)}
    shared = crossing.groupby("outer")["gateway"].unique()
    pairs = [(seat[a], seat[b]) for gs in shared for a, b in zip(gs[:-1], gs[1:])]
    if pairs:
        pairs = np.array(pairs)
        _, joined = connected_components(
            coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])),
                       shape=(len(ids), len(ids))), directed=False)
        crossing["gateway"] = crossing["gateway"].map(dict(zip(ids, joined)))

    # The check, on the network rather than the tags. Traffic can ENTER if an inbound (or
    # two-way) crossing leads to a node that can reach the main strongly connected part, and
    # LEAVE if an outbound (or two-way) crossing starts from a node that part can reach.
    seat_n = {n: i for i, n in enumerate(nodes["node_id"])}
    la, lb = links["a_node"].map(seat_n).to_numpy(), links["b_node"].map(seat_n).to_numpy()
    way = links["direction"].to_numpy()
    road_graph = coo_matrix((np.ones(int((way >= 0).sum() + (way <= 0).sum())),
                             (np.concatenate([la[way >= 0], lb[way <= 0]]),
                              np.concatenate([lb[way >= 0], la[way <= 0]]))),
                            shape=(len(nodes), len(nodes))).tocsr()
    _, part_of = connected_components(road_graph, directed=True, connection="strong")
    anchor = int(np.flatnonzero(part_of == np.bincount(part_of).argmax())[0])
    ids_n = nodes["node_id"].to_numpy()
    reached_from_main = set(ids_n[breadth_first_order(road_graph, anchor, directed=True,
                                                      return_predecessors=False)])
    reaching_main = set(ids_n[breadth_first_order(road_graph.T.tocsr(), anchor, directed=True,
                                                  return_predecessors=False)])
    crossing["inner"] = np.where(a_in.loc[crossing.index], crossing["a_node"], crossing["b_node"])
    crossing["lets_in"] = (crossing["sense"].isin(["in", "both"])
                           & crossing["inner"].isin(reaching_main))
    crossing["lets_out"] = (crossing["sense"].isin(["out", "both"])
                            & crossing["inner"].isin(reached_from_main))
    works = crossing.groupby("gateway")[["lets_in", "lets_out"]].any()
    working = set(works.index[works["lets_in"] & works["lets_out"]])
    print(f"  gateways passing the in-and-out check: {len(working)} of {len(works)}")
    crossing["absorbed"] = False
    for g in sorted(set(works.index) - working):
        idx = crossing.index[crossing["gateway"] == g]
        road_name = crossing.at[idx[0], "road"]
        good = crossing[(crossing["road"] == road_name) & crossing["gateway"].isin(working)]
        if len(good):
            mid = crossing.loc[idx, ["x", "y"]].mean()
            k = np.hypot(good["x"] - mid["x"], good["y"] - mid["y"]).idxmin()
            crossing.loc[idx, "gateway"] = good.at[k, "gateway"]
            crossing.loc[idx, "absorbed"] = True
            print(f"  a {road_name} fragment ({len(idx)} crossings) cannot let traffic both in "
                  f"and out; it joins the nearest working {road_name} gateway")
        else:
            crossing = crossing.drop(idx)
            print(f"  {road_name} ({len(idx)} crossings) cannot let traffic both in and out, and "
                  f"the road has no working gateway; dropped")

    rows = []
    for g, part in crossing.groupby("gateway"):
        mid = part[["x", "y"]].mean().to_numpy()
        here = part.iloc[int(np.argmin(np.hypot(part["x"] - mid[0], part["y"] - mid[1])))]
        rows.append({"gateway": g, "road": part["road"].mode().iloc[0],
                     "kind": part["link_type"].str.replace("_link", "").mode().iloc[0],
                     "crossings": len(part), "traced": int(part["traced"].sum()),
                     "outer_nodes": sorted(set(part["outer"])),
                     "in_and_out": bool(part["lets_in"].any() and part["lets_out"].any()),
                     "absorbed": int(part["absorbed"].sum()),
                     "pair_m": part["pair_m"].max(), "joined_m": part["joined_m"].max(),
                     "x": here["x"], "y": here["y"]})
    gates = pd.DataFrame(rows)
    order = {k: i for i, k in enumerate(roads_kept)}
    gates = gates.sort_values(["kind", "road"], key=lambda s: s.map(order) if s.name == "kind"
                              else s).reset_index(drop=True)
    gates = gpd.GeoDataFrame(gates, geometry=gpd.points_from_xy(gates["x"], gates["y"]), crs=crs)

    print(f"{len(crossing)} links of {'/'.join(roads_kept)} cross the city limit: "
          f"{(crossing['sense'] == 'both').sum()} two-way, {(crossing['sense'] != 'both').sum()} "
          f"one-way; {crossing['traced'].sum()} unnamed, traced to their road")
    print(f"grouped into {len(gates)} gateways\n")
    print(gates[["road", "kind", "crossings", "traced", "absorbed", "pair_m", "joined_m",
                 "in_and_out"]].round(0).to_string())
    # Every gateway left is a working one or has absorbed fragments into one; the assertion
    # guards against a change to the rules above breaking that.
    assert gates["in_and_out"].all(), "a gateway that cannot let traffic both in and out survived"
    m.gateways, m.crossings = gates, crossing


# --- E5. The cordon zones -----------------------------------------------------------------------
def add_cordon_zones(m, project):
    """One centroid per gateway, joined to the outer end of every road crossing there.

    The centroid sits CORDON_OFFSET_M beyond the road's outer nodes, away from the centre, so a
    trip from Votorantim enters the city on the road, not through a connector dropped into the
    middle of a neighbourhood.
    """
    report.section("E5. The cordon zones")
    gates, crossings, crs = m.gateways, m.crossings, m.metre_crs
    first_zone = m.n_internal + 1
    nodes = node_frame(project).set_index("node_id")
    with project.db_connection as conn:
        next_id = int(conn.execute("SELECT max(link_id) FROM links").fetchone()[0]) + 1
        caps = pd.read_sql("SELECT link_id, capacity_ab, capacity_ba FROM links", conn)
    caps = caps.set_index("link_id")

    centre = m.city.centroid
    node_rows, conn_rows, numbers = [], [], []
    for k, g in enumerate(gates.itertuples()):
        number = first_zone + k
        outer = nodes.loc[g.outer_nodes]
        mid = gpd.GeoSeries(gpd.points_from_xy([outer["lon"].mean()], [outer["lat"].mean()]),
                            crs="EPSG:4326").to_crs(crs).iloc[0]
        away = np.array([mid.x - centre.x, mid.y - centre.y])
        spot = Point(*(np.array([mid.x, mid.y]) + CORDON_OFFSET_M * away / np.hypot(*away)))
        spot = gpd.GeoSeries([spot], crs=crs).to_crs("EPSG:4326").iloc[0]
        lon, lat = spot.x, spot.y
        node_rows.append((number, Point(lon, lat).wkb))
        for node_id, o in outer.iterrows():
            here = gpd.GeoSeries([Point(lon, lat), Point(o["lon"], o["lat"])],
                                 crs="EPSG:4326").to_crs(crs)
            metres = max(float(here.iloc[0].distance(here.iloc[1])), 1.0)
            conn_rows.append((next_id, number, int(node_id), metres,
                              LineString([(lon, lat), (o["lon"], o["lat"])]).wkb))
            next_id += 1
        numbers.append(number)
    with project.db_connection_spatial as conn:
        conn.executemany("INSERT INTO nodes (node_id, is_centroid, geometry) "
                         "VALUES (?, 1, GeomFromWKB(?, 4326))", node_rows)
        conn.commit()
    insert_connectors(project, conn_rows, m.s)

    out = gates.copy()
    out["zone_number"] = numbers
    out["capacity"] = [float(caps.loc[crossings.loc[crossings["gateway"] == g, "link_id"],
                                      ["capacity_ab", "capacity_ba"]].to_numpy().sum())
                       for g in gates["gateway"]]
    out["label"] = [f"G{n}" for n in out["zone_number"]]
    print(f"{len(out)} cordon zones, numbered {out['zone_number'].min()} to "
          f"{out['zone_number'].max()}, {sum(len(o) for o in out['outer_nodes'])} connectors")
    m.gateways = out


# --- E7. Which gateway each municipality uses ---------------------------------------------------
def regional_roads(m, rebuild=False):
    """Nodes and edges of the regional network, downloaded once and cached."""
    folder = m.paths.cached("regional_roads")
    nodes_path = os.path.join(folder, "nodes.parquet")
    edges_path = os.path.join(folder, "edges.parquet")
    spec_path = os.path.join(folder, "downloaded_for.json")
    spec = {"reach_km": m.s.REACH_KM, "classes": REGIONAL_CLASSES}
    if not rebuild and os.path.exists(nodes_path) and os.path.exists(edges_path):
        saved = json.load(open(spec_path)) if os.path.exists(spec_path) else spec
        if saved == spec:
            json.dump(spec, open(spec_path, "w"))
            print(f"Reopened the saved regional network from {folder}")
            return pd.read_parquet(nodes_path), pd.read_parquet(edges_path)
        print(f"The saved regional network was made for {saved}, not {spec}; downloading again")

    reach = gpd.GeoSeries([m.city.buffer(m.s.REACH_KM * 1000)], crs=m.metre_crs) \
        .to_crs("EPSG:4326")
    w, s, e, n = reach.total_bounds
    query = (f'[out:json][timeout:900];way["highway"~"^({"|".join(REGIONAL_CLASSES)})$"]'
             f'({s:.4f},{w:.4f},{n:.4f},{e:.4f});out body;>;out skel qt;')
    print(f"Downloading the regional road network ({m.s.REACH_KM} km around the city) from OSM")
    elements = overpass(query, timeout=1200)
    nodes = pd.DataFrame([(el["id"], el["lon"], el["lat"]) for el in elements
                          if el["type"] == "node"], columns=["osm_node", "lon", "lat"])
    rows = []
    for el in elements:
        if el["type"] != "way":
            continue
        refs = el["nodes"]
        rows += [(a, b, el["tags"]["highway"]) for a, b in zip(refs[:-1], refs[1:])]
    edges = pd.DataFrame(rows, columns=["a", "b", "highway"])
    xy = gpd.GeoSeries(gpd.points_from_xy(nodes["lon"], nodes["lat"]), crs="EPSG:4326") \
        .to_crs(m.metre_crs)
    nodes["x"], nodes["y"] = xy.x.to_numpy(), xy.y.to_numpy()
    at = nodes.set_index("osm_node")[["x", "y"]]
    pa, pb = at.loc[edges["a"]].to_numpy(), at.loc[edges["b"]].to_numpy()
    edges["metres"] = np.hypot(*(pa - pb).T)
    os.makedirs(folder, exist_ok=True)
    nodes.to_parquet(nodes_path)
    edges.to_parquet(edges_path)
    json.dump(spec, open(spec_path, "w"))
    return nodes, edges


def route_to_gateways(m):
    """Every census sector of the region is sent to the city by its **fastest** gateway.

    The time through gateway g from sector s is: straight line to the regional roads (at
    ACCESS_KMH within the area read, FAR_ACCESS_KMH beyond it) + the regional drive to the
    gateway (shortest path, undirected) + the free-flow time from the gateway's cordon zone to
    Sorocaba's zones, averaged by jobs. A municipality's commuters are split over the gateways
    in proportion to how many of its people each serves best.
    """
    report.section("E7. Which gateway each municipality uses")
    s, gateways = m.s, m.gateways
    reg_nodes, reg_edges = regional_roads(m)
    print(f"{len(reg_edges):,} regional road segments, {reg_edges['metres'].sum() / 1000:,.0f} km, "
          f"{len(reg_nodes):,} nodes")
    kind = reg_edges["highway"].where(~reg_edges["highway"].str.endswith("_link"), "link")
    reg_edges["minutes"] = reg_edges["metres"] / 1000 / kind.map(s.REGIONAL_SPEED_KMH) * 60

    # Inside Sorocaba the model's own network takes over, so the regional graph stops at the
    # city limit: no route may cut through the city to reach a gateway on its far side.
    seat = pd.Series(np.arange(len(reg_nodes)), index=reg_nodes["osm_node"])
    inside = gpd.GeoSeries(gpd.points_from_xy(reg_nodes["x"], reg_nodes["y"]),
                           crs=m.metre_crs).within(m.city).to_numpy()
    ia, ib = seat.loc[reg_edges["a"]].to_numpy(), seat.loc[reg_edges["b"]].to_numpy()
    keep = ~(inside[ia] | inside[ib])
    graph = coo_matrix((reg_edges["minutes"].to_numpy()[keep], (ia[keep], ib[keep])),
                       shape=(len(reg_nodes), len(reg_nodes))).tocsr()
    _, comp = connected_components(graph, directed=False)
    main = np.bincount(comp).argmax()
    usable = np.where((comp == main) & ~inside)[0]
    print(f"regional graph outside the city: {keep.sum():,} segments; the largest connected "
          f"piece holds {100 * len(usable) / (~inside).sum():.0f}% of the nodes outside the city")
    tree = cKDTree(reg_nodes[["x", "y"]].to_numpy()[usable])

    def snap(points):
        metres, k = tree.query(np.column_stack([points.x, points.y]))
        return usable[k], metres

    g_node, g_off = snap(gateways.geometry)
    gateways["regional_snap_m"] = g_off
    print(f"gateways joined to the regional roads: median {np.median(g_off):,.0f} m, furthest "
          f"{g_off.max():,.0f} m ({gateways.loc[np.argmax(g_off), 'road']})")
    from_gate = dijkstra(graph, directed=False, indices=g_node)
    # The gap between a gateway and its regional node runs along the gateway's own road.
    from_gate += (g_off / 1000 / s.REGIONAL_SPEED_KMH["secondary"] * 60)[:, None]

    internal_c = m.zones_cordon <= m.n_internal
    jobs_w = m.zones.set_index("zone_number").loc[m.zones_cordon[internal_c], "jobs"].to_numpy()
    row_of = {z: i for i, z in enumerate(m.zones_cordon)}
    into_city = np.array([np.average(m.cost_cordon[row_of[z], internal_c], weights=jobs_w)
                          for z in gateways["zone_number"]])
    gateways["minutes_into_city"] = into_city

    # The sectors to route: everything read in D1, plus every municipality with commuters that
    # lies beyond the area read or that its edge cuts through, read whole here.
    region_people, by_municipio, municipios = m.region_people, m.by_municipio, m.municipios
    read_pop = region_people.groupby("code")["pop"].sum()
    missing = [c for c in by_municipio.index if c not in read_pop.index]
    cut = [c for c in by_municipio.index if c in read_pop.index
           and read_pop[c] < 0.995 * municipios["pop_2022"].get(c, 0)]
    area_read = gpd.GeoSeries([shapely.box(*m.bbox.total_bounds)], crs="EPSG:4674") \
        .to_crs(m.metre_crs).iloc[0]
    people = region_people[~region_people["code"].isin(cut)].assign(in_region=True)
    if missing or cut:
        from .inputs import unzipped_mesh
        whole = gpd.read_file(unzipped_mesh(m, "commuting_mesh"), columns=["CD_MUN", "v0001"],
                              where=f"CD_MUN IN ({','.join(repr(c) for c in missing + cut)})")
        whole = gpd.GeoDataFrame({"code": whole["CD_MUN"], "pop": whole["v0001"].fillna(0),
                                  "shape": whole.to_crs(m.metre_crs).geometry.to_numpy()},
                                 geometry=whole.to_crs(m.metre_crs).representative_point(),
                                 crs=m.metre_crs)
        whole["in_region"] = whole.geometry.within(area_read)
        people = pd.concat([people, whole[(whole["pop"] > 0) | whole["in_region"]]],
                           ignore_index=True)
    print(f"read whole: {len(missing)} municipalities beyond the area read, {len(cut)} cut by "
          f"its edge")
    unfound = sorted(set(by_municipio.index) - set(people["code"]))
    if unfound:
        raise ValueError(f"no census sectors found for {len(unfound)} municipalities: {unfound}")
    print(f"{len(people):,} sectors in {people['code'].nunique()} municipalities to route")

    s_node, s_off = snap(people.geometry)
    s_access_min = (s_off / 1000 * 60
                    / np.where(people["in_region"].to_numpy(), s.ACCESS_KMH, s.FAR_ACCESS_KMH))
    total = from_gate[:, s_node] + s_access_min[None, :] + into_city[:, None]
    if not np.isfinite(total).any(axis=0).all():
        raise ValueError(f"{(~np.isfinite(total).any(axis=0)).sum()} sectors reach no gateway "
                         f"over the regional roads")
    people = people.assign(gateway=gateways["zone_number"].to_numpy()[np.argmin(total, axis=0)],
                           minutes=np.min(total, axis=0))

    # A municipality's commuters are shared by where its people live; one whose routed sectors
    # hold nobody shares them equally over its sectors instead of 0/0.
    weight = people["pop"].where(people.groupby("code")["pop"].transform("sum") > 0, 1.0)
    split = people.assign(weight=weight).groupby(["code", "gateway"])["weight"].sum()
    split = split / split.groupby(level=0).transform("sum")
    gateway_share = {code: part.droplevel(0).to_dict() for code, part in split.groupby(level=0)
                     if code in by_municipio.index}
    print(f"municipalities given gateways: {len(gateway_share)} of {len(by_municipio)}")
    served = pd.DataFrame([(g, c, sh * by_municipio.loc[c, "total"])
                           for c, d in gateway_share.items() for g, sh in d.items()],
                          columns=["zone_number", "code", "commuters"])
    gateways["commuters"] = gateways["zone_number"].map(
        served.groupby("zone_number")["commuters"].sum()).fillna(0)
    gateways["serves"] = gateways["zone_number"].map(
        served.sort_values("commuters", ascending=False).groupby("zone_number")["code"]
        .apply(lambda c: ", ".join(municipios["name"].reindex(c.head(3)).fillna(c.head(3))))
    ).fillna("")
    print("\nthe municipalities exchanging most commuters, and how they come in:")
    label = dict(zip(gateways["zone_number"], gateways["label"] + " " + gateways["road"].str[:24]))
    for code in by_municipio.index[:12]:
        parts = sorted(gateway_share[code].items(), key=lambda kv: -kv[1])
        shown = "; ".join(f"{label[g]} {100 * sh:.0f}%" for g, sh in parts[:3] if sh >= 0.05)
        print(f"  {by_municipio.loc[code, 'name']:<22} {shown}")
    print("\n" + gateways[["label", "road", "kind", "minutes_into_city", "commuters", "serves"]]
          .round(1).to_string(index=False))
    idle = gateways[gateways["commuters"] < 1]
    if len(idle):
        print(f"\n{len(idle)} gateways are nobody's fastest way in: "
              f"{', '.join(idle['label'] + ' ' + idle['road'])}")
    m.from_gate, m.people, m.s_node, m.s_access_min = from_gate, people, s_node, s_access_min
    m.gateway_share = gateway_share


# --- The external zones ---------------------------------------------------------------------------
def sector_frame(m, people, sector_node, sector_access_min):
    """The routed sectors, each with its share of its municipality's commuters."""
    frame = people.copy()
    frame["node"], frame["access"] = sector_node, sector_access_min
    muni_pop = frame.groupby("code")["pop"].transform("sum")
    frame["commuters"] = (frame["pop"] / muni_pop.replace(0, np.nan)
                          * frame["code"].map(m.by_municipio["total"])).fillna(0)
    return frame


def group_centres(frame):
    """Commuter-weighted centre, commuters and kind of every group of sectors."""
    g = frame.groupby("group")
    w = frame["commuters"].clip(lower=1e-9)
    return pd.DataFrame({
        "x": (frame.geometry.x * w).groupby(frame["group"]).sum() / w.groupby(frame["group"]).sum(),
        "y": (frame.geometry.y * w).groupby(frame["group"]).sum() / w.groupby(frame["group"]).sum(),
        "commuters": g["commuters"].sum(), "band": g["band"].first()})


def neighbours_of(shapes):
    """Pairs of places sharing a border, and the length of it, from their exact outlines.

    Widened by BORDER_TOLERANCE_M, two neighbours overlap in a strip about twice that wide along
    their common border, so overlap area / (2 x tolerance) is the border's length; places that
    meet only at a corner overlap in a dot, far under MIN_SHARED_BORDER_M.
    """
    grown = shapely.buffer(np.asarray(shapes, dtype=object), BORDER_TOLERANCE_M)
    tree = shapely.STRtree(grown)
    i, j = tree.query(grown, predicate="intersects")
    keep = i < j
    i, j = i[keep], j[keep]
    shared = shapely.area(shapely.intersection(grown[i], grown[j])) / (2 * BORDER_TOLERANCE_M)
    ok = shared >= MIN_SHARED_BORDER_M
    return i[ok], j[ok], shared[ok]


def make_contiguous(labels, bands, weights, shapes, far, floor_of_band, mergeable, xy=None):
    """Turn groups of places into zones that are each one connected piece.

    1. every group is split into its connected pieces; its largest piece by commuters keeps the
       group's name
    2. the smallest piece or group under its band's floor joins the neighbouring group of the
       same band it shares the longest border with - never a distant one
    3. places beyond the area read (`far`) are not drawn, so contiguity means nothing for them;
       they join the nearest piece of their own group, by straight line
    """
    labels = np.array(labels, dtype=object)
    bands, weights, far = np.asarray(bands), np.asarray(weights, float), np.asarray(far, bool)
    near = np.flatnonzero(~far)
    i, j, shared = neighbours_of(np.asarray(shapes, dtype=object)[near])
    i, j = near[i], near[j]
    n = len(labels)

    same = labels[i] == labels[j]
    _, piece = connected_components(
        coo_matrix((np.ones(int(same.sum())), (i[same], j[same])), shape=(n, n)), directed=False)
    table = pd.DataFrame({"label": labels[near], "piece": piece[near], "w": weights[near]})
    rank = (table.groupby(["label", "piece"])["w"].sum().reset_index()
            .sort_values(["label", "w"], ascending=[True, False]))
    rank["k"] = rank.groupby("label").cumcount()
    name = {(r.label, r.piece): r.label if r.k == 0 else f"{r.label}#{r.k}"
            for r in rank.itertuples()}
    labels[near] = [name[(lab, p)] for lab, p in zip(labels[near], piece[near])]
    split = int((rank["k"] > 0).sum())

    merged, kept = 0, []
    while True:
        w = pd.Series(weights[near]).groupby(labels[near]).sum()
        band = pd.Series(bands[near]).groupby(labels[near]).first()
        under = w[(w < band.map(floor_of_band)) & band.map(mergeable) & ~w.index.isin(kept)]
        if under.empty:
            break
        g = under.sort_values().index[0]
        a, b = labels[i], labels[j]
        touch = (a == g) ^ (b == g)
        other = np.where(a[touch] == g, b[touch], a[touch])
        border = pd.Series(shared[touch]).groupby(other).sum()
        border = border[[band.get(o) == band[g] for o in border.index]]
        if border.empty:
            kept.append(g)           # surrounded by other kinds of zone; it stays as it is
            continue
        labels[labels == g] = border.idxmax()
        merged += 1

    if far.any() and xy is not None:
        xy = np.asarray(xy, float)
        base = np.array([str(lab).split("#")[0] for lab in labels], dtype=object)
        for k in np.flatnonzero(far):
            pool = near[base[near] == labels[k]]
            if not len(pool):
                pool = near[bands[near] == bands[k]]
            if len(pool):
                labels[k] = labels[pool[np.argmin(np.hypot(*(xy[pool] - xy[k]).T))]]
    return labels, {"split": split, "merged": merged, "kept": kept}


def compass_from_city(m, x, y):
    """The direction of a point as seen from the city centre, in eight sectors."""
    centre = m.city.centroid
    angle = np.degrees(np.arctan2(y - centre.y, x - centre.x)) % 360
    return COMPASS[int(((angle + 22.5) % 360) // 45)]


def build_ring(m):
    """Catchment zones: distance band (bordering or beyond) and fastest gateway."""
    frame = sector_frame(m, m.people, m.s_node, m.s_access_min)
    bordering = set(m.neighbours.loc[m.neighbours["adjacent"], "code"])
    frame["band"] = np.where(frame["code"].isin(bordering), 0, 1)
    frame["group"] = frame["band"].astype(str) + "|" + frame["gateway"].astype(str)
    labels, done = make_contiguous(
        frame["group"], frame["band"], frame["commuters"], frame["shape"], ~frame["in_region"],
        lambda b: m.s.RING_MIN_COMMUTERS[RING_BANDS[b]], lambda b: True,
        xy=np.column_stack([frame.geometry.x, frame.geometry.y]))
    frame["group"] = labels
    print(f"catchments made contiguous: {done['split']} split off as separate pieces, "
          f"{done['merged']} small pieces joined a neighbour"
          + (f", {len(done['kept'])} small ones with no neighbour of their band kept"
             if done["kept"] else ""))
    return frame, group_centres(frame)


def build_municipal(m):
    """Municipalities as zones: the main ones whole, Votorantim by crossing, the rest by corridor.

    - every municipality exchanging at least MUNI_MIN_COMMUTERS a day is a zone of its own
    - Votorantim is split by the gateway each part reaches fastest; a part under
      VOTORANTIM_MIN_COMMUTERS joins its neighbour
    - the rest are pooled by approach corridor; a pool under POOL_MIN_COMMUTERS joins a
      neighbouring pool
    - a municipality of its own that does not border Sorocaba and lies wholly inside one pool
      (Campinas, inside the SP-075 pool) is merged into that pool
    """
    s = m.s
    frame = sector_frame(m, m.people, m.s_node, m.s_access_min)
    total = m.by_municipio["total"]
    own = set(total.index[total >= s.MUNI_MIN_COMMUTERS]) - {VOTORANTIM}
    frame["band"] = np.where(frame["code"].isin(own), 0,
                             np.where(frame["code"] == VOTORANTIM, 1, 2))
    # A pooled municipality's corridor: the road of the gateway most of its people reach fastest.
    road_of = dict(zip(m.gateways["zone_number"], m.gateways["road"]))
    main_gate = (frame.groupby(["code", "gateway"])["pop"].sum().reset_index()
                 .sort_values("pop", ascending=False).drop_duplicates("code")
                 .set_index("code")["gateway"])
    corridor = frame["code"].map(main_gate).map(road_of)
    frame["group"] = np.select(
        [frame["band"] == 0, frame["band"] == 1],
        ["m|" + frame["code"], "v|" + frame["gateway"].astype(str)],
        "p|" + corridor.fillna("unnamed"))
    floors = {0: 0, 1: s.VOTORANTIM_MIN_COMMUTERS, 2: s.POOL_MIN_COMMUTERS}

    # Votorantim, sector by sector: each crossing's catchment made one piece.
    v = frame.index[frame["band"] == 1]
    labels, done_v = make_contiguous(
        frame.loc[v, "group"], frame.loc[v, "band"], frame.loc[v, "commuters"],
        frame.loc[v, "shape"], ~frame.loc[v, "in_region"], floors.get, lambda b: True,
        xy=np.column_stack([frame.loc[v].geometry.x, frame.loc[v].geometry.y]))
    frame.loc[v, "group"] = labels

    # The pools, municipality by municipality: a pool is towns that border one another.
    p = frame[frame["band"] == 2]
    towns = p.groupby("code").agg(group=("group", "first"), commuters=("commuters", "sum"),
                                  near=("in_region", "any"))
    towns["shape"] = p.groupby("code")["shape"].apply(
        lambda g: shapely.union_all(np.array(list(g))))
    pt = p.geometry.groupby(p["code"])
    towns["x"], towns["y"] = pt.apply(lambda g: g.x.mean()), pt.apply(lambda g: g.y.mean())
    labels, done_p = make_contiguous(
        towns["group"], np.full(len(towns), 2), towns["commuters"], towns["shape"],
        ~towns["near"], floors.get, lambda b: True, xy=towns[["x", "y"]].to_numpy())
    frame.loc[p.index, "group"] = p["code"].map(dict(zip(towns.index, labels)))

    # Enclaves: detail far from the city buys nothing, and a zone inside another reads as an
    # error.
    bordering = set(m.neighbours.loc[m.neighbours["adjacent"], "code"])
    near_codes = set(frame.loc[frame["in_region"], "code"])
    t = frame[frame["band"].isin([0, 2]) & frame["code"].isin(near_codes)]
    town = t.groupby("code").agg(group=("group", "first"), band=("band", "first"))
    town["shape"] = t.groupby("code")["shape"].apply(lambda g: shapely.union_all(np.array(list(g))))
    ti, tj, _ = neighbours_of(town["shape"].to_numpy())
    codes = town.index.to_numpy()
    enclaves = []
    for k, code in enumerate(codes):
        if town.at[code, "band"] != 0 or code in bordering:
            continue
        around = {town.at[codes[o], "group"] for o in np.concatenate([tj[ti == k], ti[tj == k]])}
        around.discard(town.at[code, "group"])
        if len(around) == 1:
            (pool,) = around
            if pool.startswith("p|"):
                frame.loc[frame["code"] == code, ["group", "band"]] = [pool, 2]
                enclaves.append(m.municipios["name"].get(code, code))
    if enclaves:
        print(f"merged into the pool that surrounds them: {', '.join(enclaves)}")
    print(f"Votorantim: {done_v['split']} pieces split off, {done_v['merged']} small pieces "
          f"joined a neighbour" + (f", {len(done_v['kept'])} small ones with no neighbour kept"
                                   if done_v["kept"] else ""))
    print(f"pools: {done_p['split']} pieces split off, {done_p['merged']} small pieces joined a "
          f"neighbour" + (f", {len(done_p['kept'])} small ones with no neighbouring pool kept"
                          if done_p["kept"] else ""))
    return frame, group_centres(frame)


def replace_cordon_zones(m, project, sectors_in, centres):
    """Take the gateway centroids out, put the external centroids and their access links in.

    Each zone is joined to every gateway within ACCESS_SLACK_MIN of its fastest regional drive,
    by an `external_access` link whose time is that drive, averaged over the zone's commuters.
    The access links carry no capacity limit: they stand for the regional roads outside the
    model, where congestion is not represented.
    """
    s, crs, gateways = m.s, m.metre_crs, m.gateways
    first_zone = m.n_internal + 1
    with project.db_connection as conn:
        old = [r[0] for r in conn.execute(
            "SELECT node_id FROM nodes WHERE is_centroid = 1 AND node_id > ?", (m.n_internal,))]
        marks = ",".join("?" * len(old))
        if old:
            conn.execute(f"DELETE FROM links WHERE a_node IN ({marks}) OR b_node IN ({marks})",
                         old + old)
            conn.execute(f"DELETE FROM nodes WHERE node_id IN ({marks})", old)
        conn.execute("DELETE FROM links WHERE link_type = 'external_access'")
        conn.commit()
        next_link = int(conn.execute("SELECT max(link_id) FROM links").fetchone()[0]) + 1
    nodes = node_frame(project).set_index("node_id")

    order = centres.sort_values(["band", "x"]).index
    numbers = {g: first_zone + k for k, g in enumerate(order)}
    spots = gpd.GeoSeries(gpd.points_from_xy(centres.loc[order, "x"], centres.loc[order, "y"]),
                          crs=crs, index=order).to_crs("EPSG:4326")
    node_rows = [(numbers[g], spots[g].wkb) for g in order]

    links, offered = [], []
    for g in order:
        part = sectors_in[sectors_in["group"] == g]
        w = part["commuters"].to_numpy()
        if w.sum() <= 0:
            w = part["pop"].to_numpy() + 1e-9
        # Commuter-weighted regional minutes from the zone's sectors to each gateway.
        minutes = (m.from_gate[:, part["node"].to_numpy()]
                   + part["access"].to_numpy()[None, :]) @ w / w.sum()
        keep = np.where(minutes <= minutes.min() + s.ACCESS_SLACK_MIN)[0]
        for k in keep:
            gate = gateways.iloc[k]
            for node_id in gate["outer_nodes"]:
                o = nodes.loc[node_id]
                line = LineString([(spots[g].x, spots[g].y), (o["lon"], o["lat"])])
                metres = float(gpd.GeoSeries([line], crs="EPSG:4326").to_crs(crs).length[0])
                speed = metres / 1000 / (minutes[k] / 60)
                links.append((next_link, numbers[g], int(node_id), metres, speed, speed,
                              s.CONNECTOR_CAPACITY, s.CONNECTOR_CAPACITY, float(minutes[k]),
                              float(minutes[k]), line.wkb))
                next_link += 1
            offered.append((numbers[g], gate["label"], float(minutes[k])))

    # AequilibraE only accepts link types it has registered; the access links need their own.
    with project.db_connection as conn:
        if not conn.execute("SELECT 1 FROM link_types WHERE link_type = 'external_access'") \
                .fetchone():
            used = {r[0] for r in conn.execute("SELECT link_type_id FROM link_types")}
            free = next(c for c in "xXwWvVqQ" if c not in used)
            conn.execute("INSERT INTO link_types (link_type, link_type_id, description) "
                         "VALUES ('external_access', ?, 'regional drive from an external zone "
                         "to a gateway')", (free,))
            conn.commit()
    with project.db_connection_spatial as conn:
        conn.executemany("INSERT INTO nodes (node_id, is_centroid, geometry) "
                         "VALUES (?, 1, GeomFromWKB(?, 4326))", node_rows)
        conn.executemany(
            "INSERT INTO links (link_id, a_node, b_node, direction, distance, modes, link_type, "
            "speed_ab, speed_ba, capacity_ab, capacity_ba, travel_time_ab, travel_time_ba, "
            "geometry) VALUES (?, ?, ?, 0, ?, 'c', 'external_access', ?, ?, ?, ?, ?, ?, "
            "GeomFromWKB(?, 4326))", links)
        conn.commit()
    return numbers, pd.DataFrame(offered, columns=["zone_number", "gateway", "minutes"])


def external_zone_system(m, project):
    """With EXTERNAL_ZONES "municipalities" or "ring", the places the commuters live become the
    zones and the gateways stop being zones; with "gateways", one zone per gateway stays.
    Returns the skim for whichever zone system results."""
    s, gateways = m.s, m.gateways
    report.section(f"E7b. The external zones ({s.EXTERNAL_ZONES})")
    if s.EXTERNAL_ZONES not in ("municipalities", "ring", "gateways"):
        raise ValueError(f"EXTERNAL_ZONES must be 'municipalities', 'ring' or 'gateways', "
                         f"not {s.EXTERNAL_ZONES!r}")
    m.zoned_externals = s.EXTERNAL_ZONES in ("municipalities", "ring")
    if not m.zoned_externals:
        ext = gateways[["zone_number", "label", "road", "commuters", "serves", "geometry"]].copy()
        ext["description"] = ext["road"]
        print(f"EXTERNAL_ZONES = 'gateways': one zone per gateway, {len(ext)} of them")
        m.external_zones = ext
        return m.cost_cordon, m.km_cordon, m.zones_cordon

    if s.EXTERNAL_ZONES == "municipalities":
        ext_sectors, ext_centres = build_municipal(m)
        bands, prefix = MUNI_KINDS, "M"
    else:
        ext_sectors, ext_centres = build_ring(m)
        bands, prefix = RING_BANDS, "R"
    numbers, offer = replace_cordon_zones(m, project, ext_sectors, ext_centres)
    ext_sectors["zone_number"] = ext_sectors["group"].map(numbers)

    # Each municipality's commuters, shared over the external zones by where its people live.
    split = ext_sectors.groupby(["code", "zone_number"])["pop"].sum()
    split = split / split.groupby(level=0).transform("sum")
    m.gateway_share = {code: part.droplevel(0).to_dict() for code, part in split.groupby(level=0)
                       if code in m.by_municipio.index}

    gate_label = dict(zip(gateways["zone_number"], gateways["label"]))
    gate_road = dict(zip(gateways["label"], gateways["road"]))
    bordering = set(m.neighbours.loc[m.neighbours["adjacent"], "code"])
    # Daily commuters of each zone, in each direction.
    direction = {d: pd.Series([m.by_municipio.loc[c, d] * sh
                               for c, part in m.gateway_share.items() for z_, sh in part.items()],
                              index=[z_ for c, part in m.gateway_share.items() for z_ in part])
                 .groupby(level=0).sum() for d in ("in", "out")}
    rows = []
    for g, z in numbers.items():
        part = ext_sectors[ext_sectors["group"] == g]
        top = part.groupby("code")["commuters"].sum().sort_values(ascending=False)
        top = top[top > 0]
        best = part.groupby("gateway")["commuters"].sum().idxmax() if top.sum() > 0 \
            else part.groupby("gateway")["pop"].sum().idxmax()
        band = bands[int(ext_centres.loc[g, "band"])]
        names = m.municipios["name"].reindex(top.index).fillna("").tolist()
        if len(top) and top.index[0] == VOTORANTIM:
            display = "Votorantim"
        elif set(part["code"]) & bordering:
            display = "inner"
        else:
            display = "outer"
        if band == "municipality":
            title = names[0]
        elif band == "Votorantim":
            title = f"Votorantim via {gate_road[gate_label[best]]}"
        elif band == "pooled":
            title = f"other towns via {g.split('|', 1)[1].split('#')[0]}"
        else:
            title = f"{band} band via {gate_road[gate_label[best]]}"
        rows.append({"zone_number": z, "label": f"{prefix}{z}", "band": band, "title": title,
                     "display_band": display,
                     "commuters_in": direction["in"].get(z, 0.0),
                     "commuters_out": direction["out"].get(z, 0.0),
                     "main_gateway": gate_label[best],
                     "gateways_offered": int((offer["zone_number"] == z).sum()),
                     "commuters": float(top.sum()), "sectors": len(part),
                     "municipalities": len(top),
                     "serves": ", ".join(names[:3]) + (f" and {len(names) - 3} more"
                                                        if len(names) > 3 else ""),
                     "x": ext_centres.loc[g, "x"], "y": ext_centres.loc[g, "y"]})
    rows = pd.DataFrame(rows).sort_values("zone_number").reset_index(drop=True)
    # Two zones on the same road are told apart by the direction they lie in.
    dupe = rows["title"].duplicated(keep=False)
    rows.loc[dupe, "title"] = [f"{t} ({compass_from_city(m, x, y)})" for t, x, y in
                               zip(rows.loc[dupe, "title"], rows.loc[dupe, "x"],
                                   rows.loc[dupe, "y"])]
    ext = gpd.GeoDataFrame(rows, crs=m.metre_crs, geometry=gpd.points_from_xy(rows["x"], rows["y"]))
    # Each zone's outline: its sectors dissolved and simplified for drawing. Every town with any
    # sector in the area read is drawn whole; towns further out still belong to a zone but are
    # not drawn, or a zone would be scattered across half the state.
    near_towns = set(ext_sectors.loc[ext_sectors["in_region"], "code"])
    drawn = ext_sectors[ext_sectors["code"].isin(near_towns)]
    outline = drawn.groupby("zone_number")["shape"].apply(
        lambda q: shapely.union_all(np.array(list(q))).buffer(100).buffer(-100).simplify(150))

    def without_slivers(shape):
        parts = list(getattr(shape, "geoms", [shape]))
        if len(parts) < 2:
            return shape, 0
        whole = sum(q.area for q in parts)
        keep = [q for q in parts if q.area >= SLIVER_SHARE * whole]
        return shapely.union_all(keep), len(parts) - len(keep)

    clean = outline.apply(without_slivers)
    ext["shape"] = ext["zone_number"].map(clean.str[0])
    parts = ext["shape"].apply(lambda g: len(getattr(g, "geoms", [g])))
    print(f"zone outlines: {int(clean.str[1].sum())} slivers left out of the drawing; zones in "
          f"one piece: {(parts == 1).sum()} of {len(parts)}")
    far_towns = ext_sectors[~ext_sectors["in_region"]].groupby("zone_number")["code"].nunique()
    ext["distant_towns"] = ext["zone_number"].map(far_towns).fillna(0).astype(int)
    ext["description"] = ext["title"]
    print(f"EXTERNAL_ZONES = '{s.EXTERNAL_ZONES}': {len(ext)} external zones replace the "
          f"{len(gateways)} cordon zones, joined to the gateways by {len(offer)} gateway choices")
    print(ext[["label", "band", "title", "main_gateway", "gateways_offered", "commuters",
               "municipalities"]].round(0).to_string(index=False))
    m.external_zones, m.gateway_offer = ext, offer

    all_zones = np.array(sorted(list(m.zones["zone_number"]) + list(ext["zone_number"])))
    print()
    return skim_zones(project, all_zones, m.n_internal, s.INTRAZONAL_SHARE, "external",
                      strict=s.STRICT_SKIM)
