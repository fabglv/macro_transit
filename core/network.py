"""The road network: downloaded from OSM once, kept, and cleaned.

The network is **downloaded once and kept** in `data/<city>/cache/road_network/`. Delete that
folder, or run with `--rebuild-network`, for a fresh copy.

Two bugs in AequilibraE's OSM importer are worked around rather than hidden: link ids that arrive
as tuples, and an Overpass endpoint that now refuses plain HTTP.
"""
import logging
import os
import shutil
import time

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

OVERPASS_ENDPOINTS = ["https://overpass-api.de/api/interpreter",
                      "https://overpass.kumi.systems/api/interpreter"]
LINK_CLASSES = ["motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"]
ONE_WAY = {"yes": 1, "true": 1, "1": 1, "-1": -1, "reverse": -1, "no": 0, "false": 0, "0": 0}


def overpass(query, timeout=900, attempts=4):
    """Elements of an Overpass query. A busy server answers 429 or 504; wait and try again,
    alternating between two public endpoints, before giving up."""
    for k in range(attempts):
        url = OVERPASS_ENDPOINTS[k % len(OVERPASS_ENDPOINTS)]
        try:
            # Overpass answers a request without a User-Agent with "406 Not Acceptable".
            reply = requests.post(url, data={"data": query}, timeout=timeout,
                                  headers={"User-Agent": "taz-od-macro-program/1.0"})
            if reply.status_code not in (429, 502, 503, 504):
                reply.raise_for_status()
                return reply.json()["elements"]
            why = f"{reply.status_code}"
        except requests.exceptions.Timeout:
            why = "timed out"
        if k + 1 < attempts:
            print(f"  Overpass at {url} {why}; trying again in {30 * (k + 1)} s")
            time.sleep(30 * (k + 1))
    raise RuntimeError(f"Overpass did not answer after {attempts} attempts")


def _patch_osm_importer():
    """Make AequilibraE's OSM importer survive a city-sized download.

    Its importer casts node ids to int64 but leaves link ids alone, and those can arrive as
    tuples. That breaks the parquet cache it writes as a safety net, and then the SQLite insert.
    `osm_id` is not used for anything modelled, so coercing it is safe.

    Returns the two originals so the patches can be lifted again afterwards.
    """
    real_parquet, real_records = pd.DataFrame.to_parquet, pd.DataFrame.to_records

    def safe_parquet(self, *args, **kwargs):
        frame = self
        if frame.index.name == "osm_id" or "osm_id" in frame.columns:
            frame = frame.copy()
            if frame.index.name == "osm_id":
                frame.index = pd.to_numeric(frame.index, errors="coerce").fillna(0).astype("int64")
                frame.index.name = "osm_id"
            if "osm_id" in frame.columns:
                frame["osm_id"] = pd.to_numeric(frame["osm_id"],
                                                errors="coerce").fillna(0).astype("int64")
        return real_parquet(frame, *args, **kwargs)

    def safe_records(self, *args, **kwargs):
        frame = self
        holds = [c for c in frame.columns if frame[c].dtype == object
                 and frame[c].map(lambda v: isinstance(v, (list, tuple, set, dict))).any()]
        if holds:
            frame = frame.copy()
            for col in holds:
                frame[col] = frame[col].map(
                    lambda v: ";".join(map(str, v)) if isinstance(v, (list, tuple, set))
                    else (str(v) if isinstance(v, dict) else v))
        return real_records(frame, *args, **kwargs)

    pd.DataFrame.to_parquet, pd.DataFrame.to_records = safe_parquet, safe_records
    return real_parquet, real_records


def release_log_files(folder):
    """Let go of aequilibrae.log so the folder holding it can be removed.

    Closing a project does not detach its logger, and Windows will not unlink an open file. The
    logger is named after the project path rather than anything predictable, so the handlers are
    found by the file they write to.
    """
    target = os.path.abspath(folder)
    for logger in [logging.getLogger()] + [logging.getLogger(name) for name
                                           in list(logging.Logger.manager.loggerDict)]:
        for handler in list(getattr(logger, "handlers", [])):
            written = getattr(handler, "baseFilename", None)
            if written and os.path.abspath(written).startswith(target):
                handler.close()
                logger.removeHandler(handler)


def _has_junction(folder):
    from aequilibrae.project import Project
    project = Project()
    project.open(folder)
    with project.db_connection as conn:
        found = "junction" in pd.read_sql("PRAGMA table_info(links)", conn)["name"].tolist()
    return project, found


def build_road_network(folder, outline_m, metre_crs, label, rebuild=False):
    """Open the saved car network, downloading it from OSM only if it is not there yet.

    `outline_m` is the area to download, in metres; Overpass is asked for that polygon.
    A download that was interrupted leaves no IMPORT_COMPLETE marker and is started again. A tag
    is only captured at import time, so a cache built before `junction` was asked for cannot
    acquire it, and is fetched again too.
    """
    from aequilibrae import Parameters
    from aequilibrae.project import Project

    if rebuild and os.path.isdir(folder):
        release_log_files(folder)
        shutil.rmtree(folder)

    complete = os.path.join(folder, "IMPORT_COMPLETE")
    if os.path.exists(os.path.join(folder, "project_database.sqlite")):
        if os.path.exists(complete) or not os.path.exists(os.path.join(folder, "osm_data")):
            # A network from before the marker existed has no osm_data/ to show it was a
            # download in progress; the marker is written for it now.
            open(complete, "w").close()
            project, has_junction = _has_junction(folder)
            if has_junction:
                print(f"Reopened the saved network from {folder}")
                return project
            project.close()
            print("The saved network predates the junction tag; downloading again")
        else:
            print("The saved network has no completion marker - a download was interrupted; "
                  "starting again")
        release_log_files(folder)
        try:
            shutil.rmtree(folder)
        except PermissionError as locked:
            raise PermissionError(
                f"{folder} has to be rebuilt, but something still holds it open. Close it, or "
                f"delete the folder by hand, and run again.") from locked

    outline = gpd.GeoSeries([outline_m], crs=metre_crs).to_crs("EPSG:4326").iloc[0]
    os.makedirs(os.path.dirname(folder), exist_ok=True)
    project = Project()
    project.new(folder)
    par = Parameters()

    # OSM marks roundabouts with junction=roundabout, and the importer keeps only the tags named
    # in this list. The links table is built from the default list when the project is created,
    # so the column has to be added too.
    fields = par.parameters["network"]["links"]["fields"]["one-way"]
    if not any(list(f)[0] == "junction" for f in fields if isinstance(f, dict)):
        fields.append({"junction": {"description": "OSM junction tag, e.g. roundabout",
                                    "osm_source": "junction", "type": "text"}})
    project.network.links.fields.add("junction", "OSM junction tag, e.g. roundabout", "TEXT")
    project.network.links.fields.save()
    par.write_back()

    osm = par.parameters["osm"]
    if osm["overpass_endpoint"].startswith("http://"):
        # The default endpoint is plain HTTP and the server answers those with "406 Not
        # Acceptable". The same query over HTTPS is answered normally.
        osm["overpass_endpoint"] = "https://overpass-api.de/api"
        par.write_back()

    print(f"Downloading {label}'s car network from OSM into {folder}")
    print("  first run only; it can take several minutes")
    real_parquet, real_records = _patch_osm_importer()
    try:
        project.network.create_from_osm(model_area=outline, modes=["car"])
    finally:
        pd.DataFrame.to_parquet, pd.DataFrame.to_records = real_parquet, real_records
    open(complete, "w").close()
    return project


def describe_network(road, top=12):
    print(f"\n{road.network.count_links():,} links, {road.network.count_nodes():,} nodes")
    with road.db_connection as conn:
        by_type = pd.read_sql(
            "SELECT link_type, count(*) links, round(sum(distance) / 1000) km "
            "FROM links GROUP BY link_type ORDER BY links DESC", conn)
        rb = pd.read_sql(
            "SELECT count(*) links, round(sum(distance)) m, sum(direction = 0) two_way "
            "FROM links WHERE junction = 'roundabout'", conn).iloc[0]
    print(f"{by_type['km'].sum():,.0f} km of road in total")
    print(f"roundabouts: {rb['links']:,.0f} links over {(rb['m'] or 0) / 1000:,.1f} km, "
          f"{rb['two_way'] or 0:,.0f} of them two-way as imported\n")
    print(by_type.head(top).to_string(index=False))


def drop_non_car_links(project, not_roads):
    """Delete links no car can use. Safe to run again: on a cleaned network it finds nothing.

    The importer marks every link car-accessible, steps and footways included. Each would
    otherwise take a default speed and capacity - an import artefact, not a claim about the city.
    """
    before_links, before_nodes = project.network.count_links(), project.network.count_nodes()
    marks = ",".join("?" * len(not_roads))
    with project.db_connection as conn:
        found = pd.read_sql(
            f"SELECT link_type, count(*) links, round(sum(distance) / 1000) km FROM links "
            f"WHERE link_type IN ({marks}) GROUP BY link_type ORDER BY links DESC",
            conn, params=not_roads)
        if len(found):
            conn.execute(f"DELETE FROM links WHERE link_type IN ({marks})", not_roads)
            conn.commit()
    if len(found):
        print(found.to_string(index=False))
        print(f"\nremoved {found['links'].sum():,} links ({found['km'].sum():,.0f} km)")
    else:
        print("nothing to remove - the saved network is already car-only")
    print(f"\ncar network: {project.network.count_links():,} links (from {before_links:,}), "
          f"{project.network.count_nodes():,} nodes (from {before_nodes:,})")
    with project.db_connection as conn:
        left = pd.read_sql("SELECT DISTINCT link_type FROM links ORDER BY link_type", conn)
    print(f"link types remaining: {', '.join(left['link_type'].astype(str))}")
    return found


def osm_tags(project, folder):
    """highway, oneway and junction for every OSM way in the network, fetched once and cached."""
    path = os.path.join(folder, "osm_tags.parquet")
    if os.path.exists(path):
        return pd.read_parquet(path)
    with project.db_connection_spatial as conn:
        s_, w_, n_, e_ = conn.execute("SELECT min(Y(geometry)), min(X(geometry)), "
                                      "max(Y(geometry)), max(X(geometry)) FROM nodes").fetchone()
    query = (f'[out:json][timeout:300];way["highway"]({s_:.5f},{w_:.5f},{n_:.5f},{e_:.5f});'
             f'out tags;')
    tags = pd.DataFrame([{"osm_id": e["id"], **{k: e["tags"].get(k)
                                               for k in ("highway", "oneway", "junction")}}
                         for e in overpass(query, timeout=600) if e["type"] == "way"])
    tags.to_parquet(path)
    return tags


def repair_from_osm_tags(project, folder):
    """Put back slip-road classes, one-way directions and one-way roundabouts.

    AequilibraE's OSM importer simplifies three tags in ways that matter:

    | what the importer does | what it should be |
    |---|---|
    | files a slip road under its road: motorway_link becomes motorway | its own class |
    | reads oneway=yes only | also 1, true, and -1 (one-way against the drawing) |
    | ignores that a roundabout is one-way | junction=roundabout/circular one-way as drawn |

    Only the tags are fetched, for the ways already in the network, and cached in
    `osm_tags.parquet` next to it. Where a link becomes one-way, the lanes the importer had split
    between two directions are given back to the one that exists. Safe to run again.
    """
    tags = osm_tags(project, folder).set_index("osm_id")
    with project.db_connection as conn:
        links = pd.read_sql("SELECT link_id, osm_id, link_type, direction, lanes_ab, lanes_ba "
                            "FROM links", conn)
        known = set(pd.read_sql("SELECT link_type FROM link_types", conn)["link_type"])
        used = set(pd.read_sql("SELECT link_type_id FROM link_types", conn)["link_type_id"])
    # A way's id is a number, or - in a network imported before September 2026 (Quito's) - text
    # such as "24210661;nan": the way, then a second id the importer left empty.
    way = pd.to_numeric(links["osm_id"].astype(str).str.split(";").str[0], errors="coerce")
    found = way.isin(tags.index)
    print(f"OSM tags found for {found.mean():.1%} of the network's links")
    if found.mean() < 0.9:
        raise RuntimeError(f"OSM tags match only {found.mean():.1%} of the links: the cached "
                           f"osm_tags.parquet in {folder} is incomplete, or the ids do not match")
    highway = way.map(tags["highway"]).fillna("").str.lower()
    oneway = way.map(tags["oneway"]).fillna("").str.lower()
    junction = way.map(tags["junction"]).fillna("").str.lower()

    # Slip roads back into their own classes, registering any class the project lacks.
    ramp = highway.isin(LINK_CLASSES) & (links["link_type"] != highway)
    new_types = sorted(set(highway[ramp]) - known)
    free = iter(c for c in "abdefghijknoqvwABCDEFGHIJKLMNOQUVWXY" if c not in used)
    with project.db_connection as conn:
        for t in new_types:
            conn.execute("INSERT INTO link_types (link_type, link_type_id, description) "
                         "VALUES (?, ?, ?)",
                         (t, next(free), f"OSM highway={t}, kept as its own class"))
        conn.commit()

    # One-way direction from the tag, and roundabouts one-way unless tagged otherwise.
    wanted = links["direction"].copy()
    tagged = oneway.isin(list(ONE_WAY))
    wanted[tagged] = oneway[tagged].map(ONE_WAY)
    ring = junction.isin(["roundabout", "circular"]) & ~oneway.isin(["no", "false", "0"])
    wanted[ring & (wanted == 0)] = 1
    redirect = wanted != links["direction"]
    # A link that becomes one-way gets back the lanes the importer split between two directions.
    lanes = pd.to_numeric(links["lanes_ab"], errors="coerce").fillna(0) + \
        pd.to_numeric(links["lanes_ba"], errors="coerce").fillna(0)
    to_one = redirect & (links["direction"] == 0) & (wanted != 0) & (lanes > 0)

    with project.db_connection as conn:
        conn.executemany("UPDATE links SET link_type = ? WHERE link_id = ?",
                         list(zip(highway[ramp], links.loc[ramp, "link_id"].astype(int))))
        conn.executemany("UPDATE links SET direction = ? WHERE link_id = ?",
                         list(zip(wanted[redirect].astype(int),
                                  links.loc[redirect, "link_id"].astype(int))))
        conn.executemany("UPDATE links SET lanes_ab = ?, lanes_ba = ? WHERE link_id = ?",
                         [(float(n) if w == 1 else 0.0, float(n) if w == -1 else 0.0, int(i))
                          for n, w, i in zip(lanes[to_one], wanted[to_one],
                                             links.loc[to_one, "link_id"])])
        conn.commit()

    shown = ", ".join(f"{t} {(highway[ramp] == t).sum()}" for t in LINK_CLASSES
                      if (highway[ramp] == t).any())
    print(f"slip roads given back their own class: {ramp.sum():,} links ({shown})")
    print(f"directions corrected: {redirect.sum():,} links - "
          f"{(redirect & ring).sum():,} on roundabouts, "
          f"{(redirect & ~ring & (wanted == -1)).sum():,} one-way against the drawing, "
          f"{(redirect & ~ring & (wanted == 1)).sum():,} one-way tagged other than 'yes', "
          f"{(redirect & (wanted == 0)).sum():,} made two-way")
    if not ramp.any() and not redirect.any():
        print("  nothing to repair - the saved network already carries the OSM tags")
    with project.db_connection as conn:
        rb = pd.read_sql("SELECT count(*) links, sum(direction = 0) two_way FROM links "
                         "WHERE junction IN ('roundabout', 'circular')", conn).iloc[0]
        left = pd.read_sql("SELECT DISTINCT link_type FROM links ORDER BY link_type", conn)
    print(f"roundabout links now two-way: {rb['two_way'] or 0:,.0f} of {rb['links']:,.0f}")
    print(f"link types: {', '.join(left['link_type'].astype(str))}")


def node_frame(project):
    with project.db_connection_spatial as conn:
        return pd.read_sql("SELECT node_id, is_centroid, X(geometry) lon, Y(geometry) lat "
                           "FROM nodes", conn)


def strong_components(links, nodes):
    """Strongly connected components of the directed road graph, and the largest one.

    Direction 0 is both ways, 1 is a->b, -1 is b->a.
    """
    order = {n: i for i, n in enumerate(nodes["node_id"])}
    a = links["a_node"].map(order).to_numpy()
    b = links["b_node"].map(order).to_numpy()
    way = links["direction"].to_numpy()
    src = np.concatenate([a[way >= 0], b[way <= 0]])
    dst = np.concatenate([b[way >= 0], a[way <= 0]])
    _, part = connected_components(
        coo_matrix((np.ones(len(src)), (src, dst)), shape=(len(nodes), len(nodes))),
        directed=True, connection="strong")
    return part, pd.Series(part).value_counts().index[0]
