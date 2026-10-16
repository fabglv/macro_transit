"""The zones inside the model: centroids, connectors, and the zones that need help reaching it.

The network is cached; the zoning is not, because it changes whenever the zones do. Each run
copies the saved network and loads the current zones into the copy.

A zone is usable only if traffic can get **both ways**. That needs a directed check: an
undirected one passes a zone sitting downstream of one-way streets, which cars can leave but
never enter.

The zones go in through one `executemany` rather than `Zone.save()`, which opens a spatialite
connection per call.
"""
import os
import shutil

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely.geometry import LineString

from .network import node_frame, release_log_files, strong_components


def rescue_stranded(project, rescue_roads, metre_crs):
    """Join any centroid that cannot both reach and be reached to the nearest significant road.

    `connect_mode` only joins a centroid to a node inside its own zone, which leaves a few
    stranded on islands or in one-way traps. A zone in a one-way trap is worse than useless:
    nothing can reach it, so a gravity model has to satisfy its attractions from the zone itself.
    """
    with project.db_connection as conn:
        links = pd.read_sql("SELECT link_id, a_node, b_node, direction, link_type FROM links", conn)
    nodes = node_frame(project)
    # Components of the ROADS alone. Counting connectors as roads would let one zone's island
    # reach the network through another zone's centroid - a path the router forbids, since no
    # trip may pass through a centroid.
    roads = links[links["link_type"] != "centroid_connector"]
    nodes["component"], main = strong_components(roads, nodes)
    in_main = set(nodes.loc[nodes["component"] == main, "node_id"])

    conns = links[links["link_type"] == "centroid_connector"]
    centroid_ids = set(nodes.loc[nodes["is_centroid"] == 1, "node_id"])
    reaches = {c: False for c in centroid_ids}
    for a, b in zip(conns["a_node"], conns["b_node"]):
        c, far = (a, b) if a in centroid_ids else (b, a)
        reaches[c] = reaches.get(c, False) or far in in_main
    centroids = nodes[nodes["is_centroid"] == 1]
    stranded = centroids[~centroids["node_id"].map(reaches).fillna(False).astype(bool)]
    if not len(stranded):
        print("every centroid already reaches the network")
        return 0

    on_real_roads = set(links.loc[links["link_type"].isin(rescue_roads), "a_node"]) | \
        set(links.loc[links["link_type"].isin(rescue_roads), "b_node"])
    landing = nodes[(nodes["component"] == main) & (nodes["node_id"].isin(on_real_roads))
                    & (nodes["is_centroid"] != 1)]
    landing_m = gpd.GeoSeries(gpd.points_from_xy(landing["lon"], landing["lat"]),
                              crs="EPSG:4326").to_crs(metre_crs)
    landing_xy = np.column_stack([landing_m.x, landing_m.y])

    made, next_id = [], int(links["link_id"].max()) + 1
    print(f"{len(stranded)} centroids cannot both reach and be reached; joining them to "
          f"{'/'.join(rescue_roads)}:")
    for row in stranded.itertuples():
        here = gpd.GeoSeries(gpd.points_from_xy([row.lon], [row.lat]),
                             crs="EPSG:4326").to_crs(metre_crs)
        away = np.hypot(landing_xy[:, 0] - here.x.iloc[0], landing_xy[:, 1] - here.y.iloc[0])
        pick = landing.iloc[int(np.argmin(away))]
        line = LineString([(row.lon, row.lat), (pick["lon"], pick["lat"])])
        made.append((next_id, int(row.node_id), int(pick["node_id"]), float(away.min()), line.wkb))
        print(f"  zone {int(row.node_id):>4} joined {away.min():>6,.0f} m away")
        next_id += 1
    with project.db_connection_spatial as conn:
        conn.executemany(
            "INSERT INTO links (link_id, a_node, b_node, direction, distance, modes, link_type, "
            "geometry) VALUES (?, ?, ?, 0, ?, 'c', 'centroid_connector', GeomFromWKB(?, 4326))",
            made)
        conn.commit()
    return len(made)


def load_zones(network_dir, model_dir, zones_frame, n_reserved, settings, metre_crs):
    """Copy the saved network and put the current zones into the copy.

    A centroid is a node, and the zone number is its node id - the matrix index relies on that.
    `n_reserved` node ids are kept free for centroids: the internal zones and any external zones
    added after them.
    """
    from aequilibrae.project import Project

    if os.path.isdir(model_dir):
        release_log_files(model_dir)
        try:
            shutil.rmtree(model_dir)
        except PermissionError as locked:
            raise PermissionError(
                f"{model_dir} is held open by another process, so it cannot be rebuilt. "
                f"Close any other session using the project.") from locked
    shutil.copytree(network_dir, model_dir)

    project = Project()
    project.open(model_dir)

    with project.db_connection as conn:
        lowest = conn.execute("SELECT min(node_id) FROM nodes").fetchone()[0]
    if lowest <= n_reserved:
        raise ValueError(f"the network already uses node id {lowest}, inside the {n_reserved} "
                         f"reserved for centroids")

    zone_rows = [(int(r.zone_number), r.geometry.wkb) for r in zones_frame.itertuples()]
    node_rows = [(int(r.zone_number), r.centroid.wkb) for r in zones_frame.itertuples()]
    with project.db_connection_spatial as conn:
        conn.executemany(
            "INSERT INTO zones (zone_id, geometry) VALUES (?, ST_Multi(GeomFromWKB(?, 4326)))",
            zone_rows)
        conn.executemany(
            "INSERT INTO nodes (node_id, is_centroid, geometry) "
            "VALUES (?, 1, GeomFromWKB(?, 4326))", node_rows)
        conn.commit()
    print(f"{len(zone_rows):,} zones and centroids written (network node ids start at {lowest:,})")

    print("Building centroid connectors to the car network...")
    project.zoning.connect_mode(mode_id="c", connectors=settings.CONNECTORS_PER_ZONE, bulk=True)
    rescue_stranded(project, settings.RESCUE_ROADS, metre_crs)

    with project.db_connection as conn:
        connectors = pd.read_sql(
            "SELECT count(*) n, round(avg(distance)) m FROM links "
            "WHERE link_type = 'centroid_connector'", conn).iloc[0]
        has = pd.read_sql(
            "SELECT a_node id FROM links WHERE link_type = 'centroid_connector' "
            "UNION SELECT b_node FROM links WHERE link_type = 'centroid_connector'", conn)["id"]
    print(f"\ncentroids: {project.network.count_centroids():,} of {len(zones_frame):,} zones")
    print(f"connectors: {connectors['n']:,.0f} links, {connectors['m']:,.0f} m long on average")
    lost = zones_frame[~zones_frame["zone_number"].isin(set(has))]
    print(f"zones with no connector: {len(lost)}"
          + (f", holding {lost['pop'].sum():,.0f} people" if len(lost) else ""))
    return project


def insert_connectors(project, rows, settings, link_type="centroid_connector"):
    """rows: (link_id, a_node, b_node, metres, geometry wkb). Costed as they go in."""
    speed, capacity = settings.CONNECTOR_SPEED, settings.CONNECTOR_CAPACITY
    full = [(i, a, b, m, speed, speed, capacity, capacity,
             (m / 1000.0) / speed * 60.0, (m / 1000.0) / speed * 60.0, g)
            for i, a, b, m, g in rows]
    with project.db_connection_spatial as conn:
        conn.executemany(
            "INSERT INTO links (link_id, a_node, b_node, direction, distance, modes, link_type, "
            "speed_ab, speed_ba, capacity_ab, capacity_ba, travel_time_ab, travel_time_ba, "
            f"geometry) VALUES (?, ?, ?, 0, ?, 'c', '{link_type}', ?, ?, ?, ?, ?, ?, "
            "GeomFromWKB(?, 4326))", full)
        conn.commit()


def add_connectors_where_needed(project, travel_share, settings, metre_crs):
    """Give a second way in to zones whose demand dwarfs the streets they join.

    A zone gets one more connector, to the highest-capacity road within reach, when its share of
    the city's travel (`travel_share`, indexed by zone number) far outweighs the share of road
    capacity where it joins. Both are shares, so no trip rate is needed. Connectors are only
    ever **added**, so no zone can lose its way on.
    """
    with project.db_connection as conn:
        links = pd.read_sql("SELECT link_id, a_node, b_node, link_type, direction, capacity_ab, "
                            "capacity_ba FROM links", conn)
    nodes = node_frame(project)
    roads = links[links["link_type"] != "centroid_connector"]
    conns = links[links["link_type"] == "centroid_connector"]

    meeting = pd.concat([
        roads[["a_node", "capacity_ab"]].set_axis(["node_id", "cap"], axis=1),
        roads[["b_node", "capacity_ba"]].set_axis(["node_id", "cap"], axis=1)])
    nodes["cap"] = nodes["node_id"].map(meeting.groupby("node_id")["cap"].sum()).fillna(0.0)
    # Only offer nodes on a road worth reaching, that traffic can both enter and leave.
    nodes["component"], main = strong_components(roads, nodes)

    on_big = roads[roads["link_type"].isin(settings.RESCUE_ROADS)]
    usable = nodes[(nodes["is_centroid"] != 1) & (nodes["component"] == main)
                   & nodes["node_id"].isin(set(on_big["a_node"]) | set(on_big["b_node"]))]
    metres = gpd.GeoSeries(gpd.points_from_xy(nodes["lon"], nodes["lat"]),
                           crs="EPSG:4326").to_crs(metre_crs)
    nodes["x"], nodes["y"] = metres.x.to_numpy(), metres.y.to_numpy()
    xy = nodes.set_index("node_id")[["x", "y"]]
    cand_ids, cand_cap = usable["node_id"].to_numpy(), usable["cap"].to_numpy()
    cand_xy = xy.loc[cand_ids].to_numpy()
    tree = cKDTree(cand_xy)

    # Where each zone joins the network now, and how much road capacity it reaches there.
    centroids = set(nodes.loc[nodes["is_centroid"] == 1, "node_id"])
    landing = {}
    for r in conns.itertuples():
        c, far = (r.a_node, r.b_node) if r.a_node in centroids else (r.b_node, r.a_node)
        landing.setdefault(c, set()).add(far)
    access = pd.Series({c: float(nodes.loc[nodes["node_id"].isin(f), "cap"].sum())
                        for c, f in landing.items()})

    lopsided = (travel_share.reindex(access.index) / (access / access.sum())).dropna()
    need = lopsided[lopsided >= settings.EXTRA_CONNECTOR_MISMATCH].sort_values(ascending=False)
    print(f"zones whose travel outweighs their access by {settings.EXTRA_CONNECTOR_MISMATCH}x or "
          f"more: {len(need)} of {len(access)}")

    made, report, next_id = [], [], int(links["link_id"].max()) + 1
    for centroid in need.index:
        here = xy.loc[centroid].to_numpy()
        near = [i for i in tree.query_ball_point(here, settings.EXTRA_CONNECTOR_M)
                if cand_ids[i] not in landing[centroid]]
        if not near:
            continue
        best = near[int(np.argmax(cand_cap[near]))]
        far = float(np.hypot(*(cand_xy[best] - here)))
        c = nodes.loc[nodes["node_id"] == centroid].iloc[0]
        n = nodes.loc[nodes["node_id"] == cand_ids[best]].iloc[0]
        made.append((next_id, int(centroid), int(cand_ids[best]), far,
                     LineString([(c["lon"], c["lat"]), (n["lon"], n["lat"])]).wkb))
        report.append((int(centroid), far, float(access[centroid]), float(cand_cap[best]),
                       float(lopsided[centroid])))
        next_id += 1
    if not made:
        if len(need):
            print("  none of them had a bigger road within reach; nothing added")
        return pd.DataFrame()
    insert_connectors(project, made, settings)
    report = pd.DataFrame(report, columns=["zone", "metres", "cap_before", "cap_added",
                                           "mismatch"])
    print(f"  {len(report)} extra connectors added, median {report['metres'].median():,.0f} m")
    for r in report.nlargest(10, "mismatch").itertuples():
        print(f"    zone {r.zone:>4}: {r.mismatch:>5.1f}x, reaches {r.metres:>4,.0f} m to a road "
              f"with {r.cap_added:>6,.0f} veh/h (had {r.cap_before:>6,.0f})")
    return report
