"""The feed: written from a dictionary of lines, and audited before and after its import.

`write_gtfs()` turns a city's `LINES` into a standards-compliant GTFS zip - the same thing a
transit agency would publish. The timetable is generated, not copied: a headway, a commercial
speed and a dwell time per line. It is written the way GTFS writes a headway-based service: one
template trip per direction in `stop_times.txt` and its headway in `frequencies.txt`.

The audits catch the three quiet errors a hand-built feed makes:

| audit | what it finds |
|---|---|
| `wide_stations` | a station whose platforms are a walk apart, not a platform change |
| `one_way_stops` | stops served in one direction only, from which the return trip cannot be made |
| `unmatchable_stops` | stops too far from a street to be map-matched: every pattern there breaks |
"""
import csv
import io
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd

# GTFS column orders AequilibraE expects. Extra columns are ignored, missing required ones are not.
GTFS_COLUMNS = {
    "agency": ["agency_id", "agency_name", "agency_url", "agency_timezone", "agency_lang"],
    "routes": ["route_id", "route_short_name", "route_long_name", "route_desc", "route_type",
               "route_color"],
    "trips": ["route_id", "service_id", "trip_id", "trip_headsign", "shape_id", "direction_id"],
    "stops": ["stop_id", "stop_name", "stop_desc", "stop_lat", "stop_lon", "stop_street",
              "zone_id", "location_type", "parent_station"],
    "stop_times": ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
    "frequencies": ["trip_id", "start_time", "end_time", "headway_secs", "exact_times"],
    "calendar": ["service_id", "monday", "tuesday", "wednesday", "thursday", "friday",
                 "saturday", "sunday", "start_date", "end_date"],
    "shapes": ["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"],
}


def km(a, b):
    """Straight-line km between two (lat, lon) pairs. Fine over a city near the equator."""
    (lat1, lon1), (lat2, lon2) = a, b
    mid = np.radians((lat1 + lat2) / 2)
    return float(np.hypot((lon2 - lon1) * 111.32 * np.cos(mid), (lat2 - lat1) * 110.57))


def hhmmss(seconds):
    """GTFS clock time. May legitimately exceed 24:00:00 for trips that run past midnight."""
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def route_of(stop_name):
    """The route short name a stop belongs to, from the 'L1 - El Recreo' naming write_gtfs uses."""
    return str(stop_name).split(" - ")[0] if " - " in str(stop_name) else ""


def directions(line):
    """The stop lists a line runs, one per direction.

    Out and back: its stops, and back along `stops_back` or the same stops reversed. A loop
    (`loop`): its stops and on to the first again - "one_way" runs it one way round,
    "both_ways" the other way round too."""
    stops = list(line["stops"])
    if line.get("loop"):
        ring = stops + [stops[0]]
        return [ring] if line["loop"] == "one_way" else [ring, ring[::-1]]
    return [stops, list(line.get("stops_back") or stops[::-1])]


# The types of day a line's timetable is set for: GTFS service_id, and the days of the week.
DAY_TYPES = [("weekday", "WEEKDAY", (1, 1, 1, 1, 1, 0, 0)),
             ("saturday", "SATURDAY", (0, 0, 0, 0, 0, 1, 0)),
             ("sunday", "SUNDAY", (0, 0, 0, 0, 0, 0, 1))]
WEEK = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def day_timetables(line):
    """[(day type, timetable)]: the line's timetable on each type of day it runs.

    On weekdays its own; on Saturday and Sunday the weekdays' unless `days` says otherwise -
    another timetable (`headway_s`, and `hours_s`, `bands_s` if it has them) or None, no
    service that day. A timetable is the line with those fields replaced."""
    out = [("weekday", line)]
    for day in ("saturday", "sunday"):
        days = line.get("days") or {}
        if day not in days:
            out.append((day, line))
        elif days[day] is not None:
            own = days[day]
            out.append((day, dict(line, headway_s=own["headway_s"], hours_s=own.get("hours_s"),
                                  bands_s=own.get("bands_s"))))
    return out


def headsign(stops):
    """What a trip runs towards: its last stop - or for a loop, which ends where it starts, the
    stop it goes round by first."""
    return f"{stops[1][0]} (a loop)" if stops[0] == stops[-1] and len(stops) > 2 else stops[-1][0]


def leg_times(line, stops, leg_km=None, direction=None):
    """Seconds between consecutive stops: each leg's length at the line's commercial speed,
    floored at 30 s so two nearly-coincident stops stay ordered. The length is `leg_km`'s - a
    bus's way along the streets (streets.line_paths) - or without it the straight line: the
    metro's, in a tunnel. A leg whose time the design set by hand (`leg_s`, by `direction` and
    leg) takes that time instead."""
    points = [(lat, lon) for _, lat, lon, _ in stops]
    lengths = leg_km or [km(points[i], points[i + 1]) for i in range(len(points) - 1)]
    set_by_hand = line.get("leg_s") or {}
    return [set_by_hand.get((direction, k)) or max(30, int(round(d / line["speed_kmh"] * 3600)))
            for k, d in enumerate(lengths)]


def run_time_s(line, stops, leg_km=None, direction=None):
    """A trip's running time, first stop to last: its legs and a dwell at every stop between -
    none at the termini, where it starts and ends."""
    return sum(leg_times(line, stops, leg_km, direction)) \
        + line["dwell_s"] * max(0, len(stops) - 2)


def service_pieces(line, start_s, end_s):
    """[(from_s, to_s, headway_s)]: when the line runs, split where its headway changes.

    Its own hours (`hours_s`) if it has them, else `start_s`-`end_s`; its headway (`headway_s`)
    except inside a band (`bands_s`: (from_s, to_s, headway_s)), which runs its own. A band
    outside the hours is cut to them. Neighbours with the same headway are one piece."""
    start_s, end_s = line.get("hours_s") or (start_s, end_s)
    bands = line.get("bands_s") or []
    cuts = sorted({start_s, end_s} | {t for a, b, _ in bands for t in (a, b) if start_s < t < end_s})
    pieces = []
    for a, b in zip(cuts, cuts[1:]):
        headway = next((h for x, y, h in bands if x <= a and b <= y), line["headway_s"])
        if pieces and pieces[-1][2] == headway:
            pieces[-1] = (pieces[-1][0], b, headway)
        else:
            pieces.append((a, b, headway))
    return pieces


def departures(line, start_s, end_s):
    """Every departure from the first stop, one direction: each piece from its start, every
    headway, none at or after its end - what frequencies.txt says."""
    return [t for a, b, h in service_pieces(line, start_s, end_s) for t in range(a, b, h)]


def said_service(line):
    """The line's service in words: "every 8 min, 05:30-23:00; every 4 min 07:00-09:00"."""
    def clock(s):
        return f"{s // 3600:02d}:{s % 3600 // 60:02d}"
    out = f"every {line['headway_s'] / 60:g} min"
    if line.get("hours_s"):
        out += f", {clock(line['hours_s'][0])}-{clock(line['hours_s'][1])}"
    for a, b, h in line.get("bands_s") or []:
        out += f"; every {h / 60:g} min {clock(a)}-{clock(b)}"
    return out


def write_gtfs(path, lines, agency, calendar, service_start_s, service_end_s, colors=None,
               shapes=None, leg_km=None):
    """Write `lines` out as a GTFS zip and return a row count per file.

    For each direction (`directions`) we walk its stop list, turn the distance between
    consecutive stops - along the streets for a bus (`leg_km`) - into a running time at the line's
    commercial speed, or take the time the design set by hand, and add a dwell at every
    intermediate stop: one template trip, departing when the line's service starts.
    `frequencies.txt` then repeats it - one row per stretch of one headway (`service_pieces`):
    the line's own hours if it has them, else `service_start_s`-`service_end_s`, and a band of
    other hours with its own headway. `exact_times = 1`: a timetable, not "about every five
    minutes" - exactly what spelling every trip out in `stop_times.txt` would say, in a fraction
    of the rows. Both directions are written, which is what makes a line usable in both
    directions - a GTFS route with only `direction_id = 0` is a one-way service, which is what a
    loop run one way round is.

    `end_time` is the GTFS one: no trip departs at or after it. AequilibraE 1.6.2 cannot import
    `frequencies.txt` (see `expand_frequencies`), so a simulation imports an expanded copy.

    A line may set `stops_back` to give the return journey its own stop list, which is how a
    one-way couplet is expressed: out along one avenue, back along another. Left unset, the
    return is the outward list reversed. Two stops of a line with one name and two positions -
    the two sides of a street - get two stop ids.

    Every type of day (`DAY_TYPES`) is a service of `calendar.txt`, over `calendar`'s dates: the
    weekdays' is `calendar`'s own service_id. A line runs on each as `day_timetables` says, its
    weekday trips keeping the ids they always had (`<line>_<direction>`), the others suffixed
    with the day. Each trip carries its headsign (`headsign`).

    `colors` (route short name -> "#rrggbb") fills GTFS's own `route_color`, so the line looks
    the same on the maps, in the results page's feed views and in any other GTFS reader.

    `shapes` ((line key, direction) -> [(lat, lon), ...]) gives `shapes.txt` a line's way along
    the streets; a direction without one - the metro, in a tunnel - gets the stop-to-stop
    polyline. `leg_km` (same keys -> each leg's km along it) times its trips along that way; a
    direction without it, along the straight line between its stops. A simulation's import map-matches the buses onto the streets guided by them.

    A station - the `parent_station` platforms share - gets its own row (`location_type` 1) at
    the middle of its platforms, named as most of them are, as GTFS requires.
    """
    rows = {name: [] for name in GTFS_COLUMNS}
    rows["agency"].append(dict(agency))
    service_ids = {}
    for day, service_id, week in DAY_TYPES:
        service_id = calendar["service_id"] if day == "weekday" else service_id
        service_ids[day] = service_id
        rows["calendar"].append(dict(calendar, service_id=service_id, **dict(zip(WEEK, week))))

    stops_seen = {}
    for key, line in lines.items():
        rows["routes"].append(dict(
            route_id=line["route_id"], route_short_name=line["short"],
            route_long_name=line["long"], route_desc="", route_type=line["route_type"],
            route_color=(colors or {}).get(line["short"], "").lstrip("#").upper()))
        timetables = [(day, service_pieces(t, service_start_s, service_end_s))
                      for day, t in day_timetables(line)]

        for direction, calls in enumerate(directions(line)):
            stop_ids = []
            for name, lat, lon, station in calls:
                sid = plain = f"{key}_{name.replace(' ', '_')}"
                n = 2
                while sid in stops_seen and (stops_seen[sid]["stop_lat"],
                                             stops_seen[sid]["stop_lon"]) != (lat, lon):
                    sid, n = f"{plain}_{n}", n + 1
                stops_seen[sid] = dict(
                    stop_id=sid, stop_name=f"{line['short']} - {name}", stop_desc="",
                    stop_lat=lat, stop_lon=lon, stop_street="", zone_id="", location_type=0,
                    parent_station=station)
                stop_ids.append(sid)

            points = [(lat, lon) for _, lat, lon, _ in calls]
            legs = leg_times(line, calls, (leg_km or {}).get((key, direction)), direction)

            shape_id = f"{key}_{direction}"
            for seq, point in enumerate((shapes or {}).get((key, direction)) or points):
                rows["shapes"].append(dict(
                    shape_id=shape_id, shape_pt_lat=point[0], shape_pt_lon=point[1],
                    shape_pt_sequence=seq + 1))

            for day, pieces in timetables:
                trip_id = f"{key}_{direction}" + ("" if day == "weekday" else f"_{day}")
                rows["trips"].append(dict(
                    route_id=line["route_id"], service_id=service_ids[day], trip_id=trip_id,
                    trip_headsign=headsign(calls), shape_id=shape_id, direction_id=direction))
                clock = pieces[0][0]
                for seq, sid in enumerate(stop_ids):
                    # No dwell at the two termini: the vehicle is starting or finishing.
                    dwell = 0 if seq in (0, len(stop_ids) - 1) else line["dwell_s"]
                    rows["stop_times"].append(dict(
                        trip_id=trip_id, arrival_time=hhmmss(clock),
                        departure_time=hhmmss(clock + dwell), stop_id=sid, stop_sequence=seq + 1))
                    if seq < len(stop_ids) - 1:
                        clock += dwell + legs[seq]
                for a, b, headway in pieces:
                    rows["frequencies"].append(dict(
                        trip_id=trip_id, start_time=hhmmss(a), end_time=hhmmss(b),
                        headway_secs=headway, exact_times=1))

    rows["stops"] = list(stops_seen.values()) + _stations(stops_seen.values())
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, columns in GTFS_COLUMNS.items():
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows[name])
            bundle.writestr(f"{name}.txt", buffer.getvalue())
    return {f"{name}.txt": len(values) for name, values in rows.items()}


def _stations(stops):
    """A row per station the stops name as their parent_station: at their middle, named as most
    of them are ("La Marin")."""
    grouped = {}
    for stop in stops:
        if stop["parent_station"]:
            grouped.setdefault(stop["parent_station"], []).append(stop)
    out = []
    for station, platforms in sorted(grouped.items()):
        names = [p["stop_name"].split(" - ", 1)[-1] for p in platforms]
        out.append(dict(stop_id=station, stop_name=max(set(names), key=names.count), stop_desc="",
                        stop_lat=round(sum(p["stop_lat"] for p in platforms) / len(platforms), 6),
                        stop_lon=round(sum(p["stop_lon"] for p in platforms) / len(platforms), 6),
                        stop_street="", zone_id="", location_type=1, parent_station=""))
    return out


def expand_frequencies(source, target):
    """Copy the feed at `source` to `target` with `frequencies.txt` spelt out as trips.

    AequilibraE 1.6.2's importer reads `frequencies.txt` but drops every trip in it: it looks
    the template up by `Trip.trip_id`, which is still -1 when it does (the GTFS id is in
    `Trip.trip`), and never renames the copies it makes - so the template's stop times are
    removed and nothing replaces them, and the import finds no trips at all. The copy carries
    the same departures, one trip each, `<template id>_<n>` - the ids the feed had when it was
    written trip by trip. A feed without `frequencies.txt` is copied as it is.
    """
    with zipfile.ZipFile(source) as z:
        def table(name):
            with z.open(name) as f:
                return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))
        names = z.namelist()
        files = {name: z.read(name) for name in names}
        if "frequencies.txt" not in names:
            frequencies = []
        else:
            frequencies = table("frequencies.txt")
            trips, times = table("trips.txt"), table("stop_times.txt")

    def seconds(text):
        h, m, s = (int(x) for x in text.strip().split(":"))
        return 3600 * h + 60 * m + s

    def written(rows, columns):
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue()

    if frequencies:
        repeats = {}
        for f in frequencies:
            repeats.setdefault(f["trip_id"], []).append(
                (seconds(f["start_time"]), seconds(f["end_time"]), int(f["headway_secs"])))
        calls = {}
        for t in times:
            calls.setdefault(t["trip_id"], []).append(t)
        new_trips, new_times = [], []
        for trip in trips:
            template = sorted(calls.get(trip["trip_id"], []), key=lambda t: int(t["stop_sequence"]))
            if trip["trip_id"] not in repeats:
                new_trips.append(trip)
                new_times += template
                continue
            first = seconds(template[0]["departure_time"])
            n = 0
            for start, end, headway in repeats[trip["trip_id"]]:
                for departure in range(start, end, headway):
                    shift = departure - first
                    trip_id = f"{trip['trip_id']}_{n}"
                    new_trips.append(dict(trip, trip_id=trip_id))
                    new_times += [dict(t, trip_id=trip_id,
                                       arrival_time=hhmmss(seconds(t["arrival_time"]) + shift),
                                       departure_time=hhmmss(seconds(t["departure_time"]) + shift))
                                  for t in template]
                    n += 1
        files.pop("frequencies.txt")
        files["trips.txt"] = written(new_trips, list(trips[0])).encode("utf-8")
        files["stop_times.txt"] = written(new_times, list(times[0])).encode("utf-8")

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, data in files.items():
            bundle.writestr(name, data)


def pattern_towards(seg):
    """{pattern_id: where it runs}, from a segments table (`line_seg_idx`, `from_name`,
    `to_name`): the stop it ends at ("El Labrador") - or for a loop, which ends where it starts,
    the stop it goes round by first ("Dos (a loop)")."""
    ordered = seg.sort_values("line_seg_idx").groupby("pattern_id")
    first, last = ordered["from_name"].first(), ordered["to_name"].last()
    second = ordered["to_name"].first()
    plain = lambda names: names.astype(str).str.split(" - ").str[-1]
    loop = first == last
    return plain(last).where(~loop, plain(second) + " (a loop)")


def declared_station_names(lines):
    """Every `parent_station` the feed declares."""
    return sorted({s[3] for line in lines.values()
                   for s in line["stops"] + line.get("stops_back", []) if s[3]})


def wide_stations(lines, limit_m):
    """Interchanges whose platforms sit too far apart to be one station.

    A shared `parent_station` asserts that a passenger can walk between these platforms as a
    station transfer. AequilibraE takes the claim at face value and charges the straight-line
    walk, so an over-wide group does not corrupt the travel times - it just quietly claims an
    interchange that does not exist, and every map then draws one.

    The easy way to make this mistake is two parallel corridors a few hundred metres apart:
    their stops look adjacent on a map of the whole city and are a ten-minute walk on the ground.

    Returns one row per offending station: platform count, widest gap, and the pair responsible.
    """
    grouped = {}
    for line in lines.values():
        for name, lat, lon, station in line["stops"] + line.get("stops_back", []):
            if station:
                grouped.setdefault(station, []).append((f"{line['short']} {name}", lat, lon))

    rows = []
    for station, platforms in sorted(grouped.items()):
        widest, pair = 0.0, ""
        for a in range(len(platforms)):
            for b in range(a + 1, len(platforms)):
                gap = km((platforms[a][1], platforms[a][2]),
                         (platforms[b][1], platforms[b][2])) * 1000
                if gap > widest:
                    widest, pair = gap, f"{platforms[a][0]} <-> {platforms[b][0]}"
        rows.append((station, len(platforms), round(widest), pair))
    out = pd.DataFrame(rows, columns=["station", "platforms", "widest_gap_m", "furthest_pair"])
    return out[out["widest_gap_m"] > limit_m]


def one_way_stops(transit):
    """Stops served in only one direction, i.e. by fewer patterns than their route runs.

    Ordinary for a real feed and easy to miss: stops on one side of a divided avenue, one-way
    loops, peak-direction expresses. A passenger cannot make the return trip from such a stop,
    and the transit graph models that faithfully - no boarding edge exists for the direction that
    does not call there.

    A pattern calls at every stop appearing at either end of one of its `route_links` rows.
    """
    seg = transit.get_table("route_links")[["pattern_id", "from_stop", "to_stop"]]
    calls = pd.concat([
        seg[["pattern_id", "from_stop"]].rename(columns={"from_stop": "stop_id"}),
        seg[["pattern_id", "to_stop"]].rename(columns={"to_stop": "stop_id"}),
    ]).drop_duplicates()
    calls["stop_id"] = calls["stop_id"].astype(str)

    stops = transit.get_table("stops")[["stop_id", "stop", "name"]].copy()
    stops["stop_id"] = stops["stop_id"].astype(str)
    routes = transit.get_table("routes")[["pattern_id", "shortname"]]
    calls = calls.merge(routes, on="pattern_id").merge(stops, on="stop_id")

    per_stop = (calls.groupby(["shortname", "stop", "name"])["pattern_id"]
                .nunique().rename("directions_served").reset_index())
    per_route = routes.groupby("shortname")["pattern_id"].nunique().rename("route_directions")
    per_stop = per_stop.merge(per_route, on="shortname")
    return per_stop[per_stop["directions_served"] < per_stop["route_directions"]]


def unmatchable_stops(project, transit, radius_m, route_types):
    """Stops the map matcher cannot snap: further than `radius_m` from any transit-mode link.

    This is the usual cause of ``Could not rebuild path for pattern ...``, and AequilibraE reports
    only that a *pattern* failed - never which stop is at fault. The failure is quiet and
    asymmetric in a misleading way: an unsnappable stop breaks **every** pattern that calls at it,
    in both directions, so one bad coordinate takes out a whole route while its neighbours match
    perfectly.

    Two details of AequilibraE's matcher are baked in here. The radius is its
    `distance_to_project` default of 50 m. And matching runs on links carrying the **transit** road
    mode `t`, not the car mode - which for an OSM import is nearly all of them, but not by
    definition.
    """
    from aequilibrae.utils.geo_utils import metre_crs_for_gdf

    columns = ["stop", "name", "metres_to_nearest_road", "nearest_road", "road_class"]
    links = project.network.links.data
    net = gpd.GeoDataFrame(links[["link_id", "name", "link_type", "modes"]],
                           geometry=links.geometry, crs="EPSG:4326")
    net = net[net["modes"].astype(str).str.contains("t")]
    crs = metre_crs_for_gdf(net)              # a local metre CRS, so distances are real metres
    net = net.to_crs(crs)

    stops = transit.get_table("stops")
    stops = stops[stops["route_type"].isin(route_types)]
    if not len(stops) or not len(net):
        return pd.DataFrame(columns=columns)

    sg = gpd.GeoDataFrame(stops[["stop_id", "stop", "name"]], geometry=stops.geometry,
                          crs="EPSG:4326").to_crs(crs)
    rows = []
    for stop in sg.itertuples():
        d = net.distance(stop.geometry)
        nearest = net.loc[d.idxmin()]
        rows.append((stop.stop, stop.name, float(d.min()), nearest["name"], nearest["link_type"]))
    out = pd.DataFrame(rows, columns=columns)
    return out[out["metres_to_nearest_road"] > radius_m].sort_values(
        "metres_to_nearest_road", ascending=False)
