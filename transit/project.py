"""The AequilibraE project a public-transport run stands on: streets, zones, period, feed.

A transit project is two databases in one folder: `project_database.sqlite` (streets, zones)
and `public_transport.sqlite` (the imported timetable and the transit graph).

The streets are used for three things that have nothing to do with cars: map matching (a bus
corridor drawn on the avenue it runs along), the zoning (a cell with no street in it is not
city), and the walking transfers between stops. Bus run times come from the timetable and every
access walk is a straight line, so the assignment barely depends on them.

They are **downloaded once and kept** in `data/<city>/cache/transit_road_network/`, by the same
code the road model uses (core/network.py: the HTTPS Overpass endpoint, the importer's link-id
repair, a marker for a finished download). Each run copies the cache into its own project and
builds everything else there afresh.
"""
import os
import re
import shutil

import geopandas as gpd
import numpy as np
from shapely.geometry import Point, Polygon

from core.network import build_road_network, release_log_files


def box_polygon(bbox):
    """The study box (min_lat, min_lon, max_lat, max_lon) as a lon/lat polygon."""
    min_lat, min_lon, max_lat, max_lon = bbox
    return Polygon([(min_lon, min_lat), (max_lon, min_lat), (max_lon, max_lat),
                    (min_lon, max_lat), (min_lon, min_lat)])


def ensure_street_cache(cache_dir, bbox, label):
    """The city's street network for its study box, downloaded from OSM the first time it is
    needed - by a design's build or the OSM lines' conversion, before any simulation has."""
    if os.path.isdir(cache_dir):
        return
    print(f"Downloading {label}'s streets for the study box (once) ...")
    project = build_road_network(cache_dir, box_polygon(bbox), "EPSG:4326",
                                 f"{label} (transit study box)")
    project.close()
    release_log_files(cache_dir)


def _numeric_speeds(database):
    """OSM's speed tags as numbers: a way merged from several keeps them all ("30; 20; 20"), and
    the map matcher cannot compare text with numbers - the first is kept."""
    import sqlite3
    with sqlite3.connect(database) as db:
        for column in ("speed_ab", "speed_ba"):
            rows = db.execute(f"SELECT link_id, {column} FROM links "
                              f"WHERE typeof({column}) = 'text'").fetchall()
            for link_id, text in rows:
                found = re.match(r"\s*(\d+(?:\.\d+)?)", text)
                db.execute(f"UPDATE links SET {column} = ? WHERE link_id = ?",
                           (float(found.group(1)) if found else None, link_id))
            if rows:
                print(f"{len(rows)} links' {column} read as a number (OSM gave text)")


def open_street_project(cache_dir, project_dir, bbox, label, rebuild=False):
    """Open a copy of the cached street network as this run's project, downloading it first if
    the cache is not there yet.

    `build_road_network` takes the area in a metric CRS and projects it to lat/lon for Overpass;
    the box is already in lat/lon, so it is handed over as EPSG:4326 and the projection does
    nothing.
    """
    from aequilibrae import Project

    cached = build_road_network(cache_dir, box_polygon(bbox), "EPSG:4326", label, rebuild=rebuild)
    print(f"{cached.network.count_links():,} links, {cached.network.count_nodes():,} nodes in "
          f"the study box")
    cached.close()                       # release the cache before copying it
    release_log_files(cache_dir)

    if os.path.isdir(project_dir):
        release_log_files(project_dir)
        try:
            shutil.rmtree(project_dir)
        except PermissionError as locked:
            raise PermissionError(
                f"{project_dir} is held open by another process - usually a notebook or QGIS "
                f"with the project open. Close it and run again.") from locked
    shutil.copytree(cache_dir, project_dir)
    _numeric_speeds(os.path.join(project_dir, "project_database.sqlite"))
    project = Project()
    project.open(project_dir)
    print(f"Working project: {project_dir}")
    return project


def make_zones(project, bbox, s):
    """A synthetic grid of zones, kept where there is city, written into the project.

    1. Trim bands off a coarse grid over the study box, leaving the block the network runs
       through.
    2. Split every surviving cell into SPLIT x SPLIT zones.
    3. Drop the cells with less than MIN_ROAD_KM of street inside them - open country.

    Zone ids are handed out only to the survivors, so they stay contiguous 1..n. Returns the
    zones' polygons, in zone-id order, and the size of a cell in km.
    """
    from aequilibrae.utils.geo_utils import metre_crs_for_gdf

    min_lat, min_lon, max_lat, max_lon = bbox
    coarse_lat = np.linspace(min_lat, max_lat, s.COARSE_ROWS + 1)
    coarse_lon = np.linspace(min_lon, max_lon, s.COARSE_COLS + 1)
    lat_lo, lat_hi = coarse_lat[s.TRIM_SOUTH], coarse_lat[s.COARSE_ROWS - s.TRIM_NORTH]
    lon_lo, lon_hi = coarse_lon[0], coarse_lon[s.COARSE_COLS - s.TRIM_EAST]
    n_rows = (s.COARSE_ROWS - s.TRIM_SOUTH - s.TRIM_NORTH) * s.SPLIT
    n_cols = (s.COARSE_COLS - s.TRIM_EAST) * s.SPLIT
    lat_edges = np.linspace(lat_lo, lat_hi, n_rows + 1)
    lon_edges = np.linspace(lon_lo, lon_hi, n_cols + 1)

    cells = [Polygon([(lon_edges[j], lat_edges[i]), (lon_edges[j + 1], lat_edges[i]),
                      (lon_edges[j + 1], lat_edges[i + 1]), (lon_edges[j], lat_edges[i + 1]),
                      (lon_edges[j], lat_edges[i])])
             for i in range(n_rows) for j in range(n_cols)]
    candidates = gpd.GeoDataFrame({"cell": range(len(cells))}, geometry=cells, crs="EPSG:4326")

    # Street length inside each cell. A link touching a cell counts in full, which slightly
    # over-credits boundary cells - immaterial against a 2 km threshold.
    links = project.network.links.data
    streets = gpd.GeoDataFrame(links[["link_type"]], geometry=links.geometry, crs="EPSG:4326")
    streets = streets[streets["link_type"] != "centroid_connector"]
    metre_crs = metre_crs_for_gdf(streets)
    streets = streets.to_crs(metre_crs)
    inside = gpd.sjoin(streets.assign(km=streets.length / 1000.0),
                       candidates.to_crs(metre_crs)[["cell", "geometry"]],
                       predicate="intersects", how="inner")
    candidates["road_km"] = (inside.groupby("cell")["km"].sum()
                             .reindex(candidates["cell"]).fillna(0.0).to_numpy())

    polygons = list(candidates.loc[candidates["road_km"] >= s.MIN_ROAD_KM, "geometry"])
    zoning = project.zoning
    for zone_id, poly in enumerate(polygons, start=1):
        zone = zoning.new(zone_id)
        zone.geometry = poly
        zone.add_centroid(Point(poly.centroid.x, poly.centroid.y))
        zone.save()

    # Centroid connectors on the car network. The transit graph does not use them - it builds
    # its own straight-line connectors to the stops - but they make this a complete project,
    # usable for a road assignment on the same zones.
    zoning.connect_mode(mode_id="c", bulk=True)
    # The GTFS import assigns every stop to a zone through this index. Zones created in this
    # session are not in it until it is rebuilt: skip this and the import fails inside
    # save_to_disk() with "min() iterable argument is empty".
    zoning.refresh_geo_index()

    cell_km = ((lat_edges[1] - lat_edges[0]) * 110.57, (lon_edges[1] - lon_edges[0]) * 111.32)
    print(f"Grid {n_rows} x {n_cols} = {len(cells)} candidate cells of "
          f"{cell_km[0]:.2f} x {cell_km[1]:.2f} km.")
    print(f"Dropped {len(cells) - len(polygons)} with under {s.MIN_ROAD_KM:g} km of street "
          f"inside (open country, slopes, water).")
    print(f"Created {len(polygons)} zones and {project.network.count_centroids()} centroids.")
    print(f"Zoned area: lat {lat_lo:.4f} to {lat_hi:.4f}, lon {lon_lo:.4f} to {lon_hi:.4f} "
          f"(the street network still covers the full study box).")
    return polygons, cell_km


def zone_sources(city):
    """Where the city's zones are read from, first found: the road baseline's export, or the
    copy kept in the city's cache once built from its inputs."""
    import os

    from core.paths import MACRO_OUTPUT, ROOT
    return [os.path.join(MACRO_OUTPUT, city, "exports", "zones.gpkg"),
            os.path.join(ROOT, "data", city, "cache", "city_zones.gpkg")]


def city_zones(city):
    """The city's own zones - the road model's: built from its inputs (census sectors, people,
    jobs), not from a road simulation - in lat/lon, by zone number, with each one's middle
    (centroid_lat, centroid_lon), people and area. Read from the road baseline's export if it
    has been run; else from the city's cache; else built from the inputs (the road model's
    `prepare`, about half a minute, its maps in a scratch folder) and kept in the cache."""
    import contextlib
    import io
    import os
    import tempfile

    found = next((p for p in zone_sources(city) if os.path.isfile(p)), None)
    if found:
        zones = gpd.read_file(found)
    else:
        from cases import load
        from core.paths import CityPaths
        print("The city's zones, built from its inputs (census sectors, people, jobs) - kept in "
              "its cache for next time ...")
        model_cls, settings = load(city)
        model = model_cls(settings, CityPaths(city, tempfile.mkdtemp(prefix="zones_")))
        with contextlib.redirect_stdout(io.StringIO()):         # its own report: not this run's
            model.paths.prepare_outputs()
            model.prepare()
        built = model.zones.to_crs("EPSG:4326")
        middle = gpd.GeoSeries(built["centroid"], crs=model.zones.crs).to_crs("EPSG:4326")
        zones = gpd.GeoDataFrame({"zone_number": built["zone_number"].astype(int),
                                  "zone": built["zone"].astype(str), "pop": built["pop"],
                                  "area_km2": built["area_km2"], "centroid_lat": middle.y,
                                  "centroid_lon": middle.x}, geometry=built.geometry,
                                 crs="EPSG:4326")
        cache = zone_sources(city)[1]
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        zones.to_file(cache, driver="GPKG")
    return zones.to_crs("EPSG:4326").sort_values("zone_number")


def road_zones(project, city, bbox):
    """The city's zones - the road model's (city_zones) - whose middle is inside the study box,
    written into the project as zones 1..n (in the road model's order). Returns their polygons,
    in zone-id order, and their numbers in the road model."""
    zones = city_zones(city)
    min_lat, min_lon, max_lat, max_lon = bbox
    inside = zones[zones["centroid_lat"].between(min_lat, max_lat)
                   & zones["centroid_lon"].between(min_lon, max_lon)]
    polygons = [g.buffer(0) for g in inside.geometry]
    zoning = project.zoning
    for zone_id, (poly, row) in enumerate(zip(polygons, inside.itertuples()), start=1):
        zone = zoning.new(zone_id)
        zone.geometry = poly
        zone.add_centroid(Point(row.centroid_lon, row.centroid_lat))
        zone.save()
    zoning.connect_mode(mode_id="c", bulk=True)      # as make_zones: a complete project
    zoning.refresh_geo_index()                       # the GTFS import reads it
    print(f"The road model's zones: {len(inside)} of its {len(zones)} have their middle in the "
          f"study box, and are this simulation's zones 1 to {len(inside)}.")
    print(f"{inside['pop'].sum():,.0f} people live in them; a zone is "
          f"{inside['area_km2'].median():.2f} km² in the middle of the range "
          f"({inside['area_km2'].min():.2f} to {inside['area_km2'].max():.2f}).")
    return polygons, inside["zone_number"].astype(int).tolist()


def declare_period(project, period_id, start_h, end_h):
    """Write the modelled period and return its length in hours.

    A transit model says its period explicitly, because the service level is read from the
    timetable: the trips running inside it are counted and turned into a frequency. Period 1 is
    the whole-day default AequilibraE creates. `new_period()` builds the object but does not
    write it; without the `.save()` the graph builder later fails with `IndexError` looking up a
    period that was never stored.
    """
    periods = project.network.periods
    periods.new_period(period_id, start_h * 3600, end_h * 3600,
                       f"{start_h:02d}:00-{end_h:02d}:00 modelled period").save()
    row = periods.data.set_index("period_id").loc[period_id]
    hours = (row["period_end"] - row["period_start"]) / 3600.0
    print(periods.data[["period_id", "period_start", "period_end", "period_description"]]
          .to_string(index=False))
    print(f"\nModelled period is {hours:g} hours long. The demand matrix holds the trips made in "
          f"it, and every\nsegment load is the passengers carried during it.")
    return hours


def import_feed(project, gtfs_path, agency, description, service_day, route_types):
    """Import the feed for one service day, map-matching the chosen route types.

    `map_match(route_types=[3])` snaps buses onto the real streets; the metro (route type 1) runs
    in a tunnel and is left alone. Matching is best-effort: a pattern it cannot rebuild keeps its
    straight-line shape with only a warning, which names the pattern and never the stop at fault -
    `unmatchable_stops()` names it. Nothing assigned depends on the matching: the graph comes
    from stop sequences and times; the matched geometry only feeds the log's detour figure.
    """
    from aequilibrae.transit import Transit

    from .gtfs import expand_frequencies

    # The feed's frequencies.txt spelt out trip by trip: AequilibraE 1.6.2 cannot read it.
    expanded = os.path.join(project.project_base_path, "gtfs_feed_expanded.zip")
    expand_frequencies(gtfs_path, expanded)
    transit = Transit(project)
    feed = transit.new_gtfs_builder(agency=agency, file_path=expanded, description=description)
    print(f"Feed covers {len(feed.dates_available()):,} service dates; importing {service_day}.")
    feed.load_date(service_day)
    feed.set_allow_map_match(True)
    # feed.map_match's loop, one pattern at a time: AequilibraE 1.6.2 fails outright on a pattern
    # whose broken-link path it cannot find (a TypeError deep in the matcher), which would stop
    # the whole import; that pattern keeps its shape from the feed, with a warning.
    for pattern in feed.select_patterns.values():
        if pattern.route_type not in route_types:
            continue
        try:
            pattern.map_match()
        except Exception as problem:
            print(f"WARNING: pattern {pattern.pattern_id} (route {pattern.route}) could not be "
                  f"map-matched ({type(problem).__name__}): it keeps the feed's shape")
    feed.save_to_disk()

    routes = transit.get_table("routes")
    print(f"\nImported {len(routes)} patterns ({routes.shortname.nunique()} routes), "
          f"{len(transit.get_table('stops'))} stops, {len(transit.get_table('trips')):,} trips.")
    print("\nPatterns (one per route and direction):")
    print(routes[["pattern_id", "shortname", "longname", "route_type"]].to_string(index=False))
    return transit
