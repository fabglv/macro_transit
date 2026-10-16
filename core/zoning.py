"""Grouping census sectors into traffic analysis zones.

Every city builds its zones from the same few rules - a coarser layer as a hard edge, one
connected piece per zone, large zones split into compact pieces, small zones merged into a
neighbour - but composes them in its own order and with its own sizes. The rules are here; the
recipe is in each case's zoning step.

Everything runs on one adjacency list of sectors rather than on geometry.
"""
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from sklearn.cluster import AgglomerativeClustering


def adjacency(sectors_m, min_shared_m=0.0):
    """Pairs of sector rows (positions) that share a border, both ways round.

    With `min_shared_m` above zero, sectors meeting only at a corner - a common border shorter
    than that - are not neighbours: a zone joined through a point is two zones.
    Returns the edges and the number of corner-only pairs left out.
    """
    frame = gpd.GeoDataFrame({"row": np.arange(len(sectors_m))},
                             geometry=sectors_m.geometry.values, crs=sectors_m.crs)
    pairs = gpd.sjoin(frame, frame, predicate="touches", how="inner")
    pairs = pairs[pairs["row_left"] != pairs["row_right"]]
    edges = pairs[["row_left", "row_right"]].to_numpy()
    if min_shared_m <= 0:
        return edges, 0
    common = shapely.intersection(frame.geometry.values[edges[:, 0]],
                                  frame.geometry.values[edges[:, 1]])
    corner_only = shapely.length(common) < min_shared_m
    return edges[~corner_only], int(corner_only.sum())


def pieces(base, edges, n):
    """Connected pieces of each group: `base` is a group code per sector."""
    base = np.asarray(base)
    within = edges[base[edges[:, 0]] == base[edges[:, 1]]]
    _, part = connected_components(
        coo_matrix((np.ones(len(within)), (within[:, 0], within[:, 1])), shape=(n, n)),
        directed=False)
    return part


def sizes(zone_of, size):
    return pd.Series(size).groupby(zone_of).sum()


def split_large(zone_of, size, edges, xy, max_size, passes=1, too_few="skip", sep="."):
    """Split zones over `max_size` into compact contiguous pieces.

    Ward clustering on the sector centres, with the adjacency as `connectivity`, only ever merges
    neighbours - so every piece is contiguous. Each zone becomes ceil(size / max_size) pieces.

    `passes` above one repeats the split until nothing is over the maximum (sectors hold similar
    numbers of people but not of jobs, so one pass is not always enough). `too_few` says what a
    zone with fewer sectors than pieces does: "skip" leaves it whole, "all" gives every sector a
    piece of its own. Returns the new labels and the number of passes that split anything.
    """
    zone_of = np.array(zone_of, dtype=object)
    size = np.asarray(size, dtype=float)
    used = 0
    for _ in range(passes):
        big = sizes(zone_of, size)
        big = big[big > max_size]
        big = [z for z in big.index if (zone_of == z).sum() > 1]
        if not big:
            break
        used += 1
        for zone in big:
            idx = np.where(zone_of == zone)[0]
            k = int(np.ceil(size[idx].sum() / max_size))
            if len(idx) < k:
                if too_few == "skip":
                    continue
                k = len(idx)
            pos = {r: i for i, r in enumerate(idx)}
            sub = edges[np.isin(edges[:, 0], idx) & np.isin(edges[:, 1], idx)]
            conn = coo_matrix((np.ones(len(sub)), ([pos[a] for a in sub[:, 0]],
                                                   [pos[b] for b in sub[:, 1]])),
                              shape=(len(idx), len(idx)))
            labels = AgglomerativeClustering(n_clusters=max(k, 2), connectivity=conn,
                                             linkage="ward").fit_predict(xy[idx])
            zone_of[idx] = [f"{zone}{sep}{v}" for v in labels]
    return zone_of, used


def merge_small(zone_of, size, edges, group, min_size, max_size=None):
    """Merge zones under `min_size` into a neighbour of the same group, smallest first.

    The neighbour is the one sharing most sector borders. With `max_size`, a neighbour it can join
    without going over the maximum is preferred; only if none can take it does it join the one
    that ends up smallest. A zone with no neighbour in its group is kept as it is.
    Returns the labels and counts: merged, kept, and merges that went over the maximum.
    """
    zone_of = np.array(zone_of, dtype=object)
    size = np.asarray(size, dtype=float)
    group = np.asarray(group)
    same_group = group[edges[:, 0]] == group[edges[:, 1]]
    locked, merged, overflow = set(), 0, 0
    while True:
        s = sizes(zone_of, size)
        small = s[(s < min_size) & ~s.index.isin(locked)]
        if small.empty:
            break
        target = small.idxmin()
        left, right = zone_of[edges[:, 0]], zone_of[edges[:, 1]]
        hit = (left == target) & (right != target) & same_group
        cand = pd.Series(right[hit]).value_counts()
        if cand.empty:
            locked.add(target)          # alone in its group; nothing to join
            continue
        if max_size is None:
            into = cand.index[0]
        else:
            fits = cand[(s.reindex(cand.index) + s[target]) <= max_size]
            if len(fits):
                into = fits.index[0]
            else:
                # Every neighbour is near the limit: join the one that ends up smallest.
                into = (s.reindex(cand.index) + s[target]).idxmin()
                overflow += 1
        zone_of[zone_of == target] = into
        merged += 1
    return zone_of, {"merged": merged, "kept": len(locked), "overflow": overflow}


def renumber(sectors, zone_col, group_col, code_col, width):
    """Zone ids that are stable between runs and readable in a tooltip: Z001, Z002, ...

    The keys a build leaves are artefacts; zones are numbered by group, then by their lowest
    sector code."""
    order = (sectors.groupby(zone_col).agg(group=(group_col, "first"), code=(code_col, "min"))
             .sort_values(["group", "code"]))
    return sectors[zone_col].map({z: f"Z{i:0{width}d}" for i, z in enumerate(order.index, 1)})


def weighted_centroids(sectors_m, zone_labels, weights, zones_m):
    """Weighted centre of each zone's sectors, moved inside the zone where it falls outside.

    A geometric centroid puts a rural zone's connector on an empty hillside; weighting by people
    (or people and jobs) puts it where the trips start. Where the weighted point falls outside a
    concave zone, it is moved to a point inside. `zones_m` is indexed by zone label.
    Returns the centroids in lat/lon, indexed by zone, and how many were moved.
    """
    pts = sectors_m.geometry.representative_point()
    frame = pd.DataFrame({"zone": np.asarray(zone_labels), "x": pts.x.to_numpy(),
                          "y": pts.y.to_numpy(), "w": np.clip(np.asarray(weights, float),
                                                              1e-9, None)})
    wc = frame.groupby("zone").apply(
        lambda g: pd.Series({"cx": np.average(g["x"], weights=g["w"]),
                             "cy": np.average(g["y"], weights=g["w"])}), include_groups=False)
    centroids = gpd.GeoSeries(gpd.points_from_xy(wc["cx"], wc["cy"]), index=wc.index,
                              crs=sectors_m.crs)
    outside = ~centroids.within(zones_m.geometry.reindex(centroids.index))
    if outside.any():
        centroids.loc[outside] = zones_m.geometry.reindex(centroids.index)[outside] \
            .representative_point()
    return centroids.to_crs("EPSG:4326"), int(outside.sum())


def read_zoning_file(path):
    """A zoning file's polygons, in lat/lon: a GeoPackage, GeoJSON or zipped Shapefile. Raises
    ValueError on anything else - no polygons, no coordinate system."""
    source = f"zip://{path}" if path.lower().endswith(".zip") else path
    try:
        zones = gpd.read_file(source)
    except Exception as problem:                              # noqa: BLE001 - said, not hidden
        raise ValueError(f"cannot read the zoning file: {problem}") from None
    if zones.crs is None:
        if path.lower().endswith((".geojson", ".json")):
            zones = zones.set_crs("EPSG:4326")                 # GeoJSON is lat/lon by definition
        else:
            raise ValueError("the zoning file has no coordinate system (a .prj, for a Shapefile)")
    zones = zones[zones.geometry.notna() & zones.geom_type.isin(["Polygon", "MultiPolygon"])]
    if zones.empty:
        raise ValueError("the zoning file has no polygons")
    return zones.to_crs("EPSG:4326").reset_index(drop=True)


def from_file(sectors_m, path, id_column=""):
    """Zones from a file instead of the rules: each census sector goes to the file's zone that
    holds its representative point, so a zone's people and jobs are still the census's, summed
    over its sectors - and its shape is theirs, the file's polygon followed sector by sector.

    Returns a label per sector (the zone's id in the file, or its row number from 1; None for a
    sector inside no zone) and the lines that say how the file fitted, for the step's preview."""
    zones = read_zoning_file(path)
    if id_column:
        if id_column not in zones:
            raise ValueError(f"the zoning file has no column {id_column!r}; it has "
                             f"{', '.join(c for c in zones.columns if c != 'geometry')}")
        ids = zones[id_column].astype(str).str.strip()
        if ids.duplicated().any() or (ids == "").any():
            raise ValueError(f"{id_column} must name each zone once: "
                             f"{', '.join(ids[ids.duplicated()].unique()[:5])} repeat")
    else:
        ids = pd.Series([str(i) for i in range(1, len(zones) + 1)])
    zones = gpd.GeoDataFrame({"file_id": ids.to_numpy()}, geometry=zones.geometry.values,
                             crs="EPSG:4326").to_crs(sectors_m.crs)
    points = gpd.GeoDataFrame({"row": np.arange(len(sectors_m))},
                              geometry=sectors_m.geometry.representative_point().values,
                              crs=sectors_m.crs)
    hit = gpd.sjoin(points, zones, predicate="within", how="left")
    hit = hit[~hit.index.duplicated()]                    # overlapping zones: the first holds it
    labels = hit["file_id"].reindex(range(len(sectors_m))).to_numpy(dtype=object)
    labels = np.where(pd.isna(labels), None, labels)
    used = set(labels[labels != None])                     # noqa: E711 - an array comparison
    empty = [z for z in zones["file_id"] if z not in used]
    outside = int((labels == None).sum())                  # noqa: E711
    lines = [["zoning file", f"{len(zones):,} zones read, {len(used):,} with census sectors in "
                             f"them"]]
    if empty:
        lines.append(["zones left out", f"{len(empty)} hold no sector's centre: "
                                        f"{', '.join(empty[:8])}{' ...' if len(empty) > 8 else ''}"])
    if outside:
        lines.append(["sectors outside every zone", f"{outside:,} of {len(sectors_m):,} - "
                                                    f"their people are not in the model"])
    if not used:
        raise ValueError("no census sector falls inside the zoning file's zones: is it this "
                         "city's?")
    return labels, lines


def pieces_per_zone(zone_row, edges, n):
    """How many connected pieces each zone is, through shared borders (not corners)."""
    zone_row = np.asarray(zone_row)
    inside = edges[zone_row[edges[:, 0]] == zone_row[edges[:, 1]]]
    _, piece = connected_components(
        coo_matrix((np.ones(len(inside)), (inside[:, 0], inside[:, 1])), shape=(n, n)),
        directed=False)
    return pd.Series(piece).groupby(zone_row).nunique()
