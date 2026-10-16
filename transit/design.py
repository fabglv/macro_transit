"""A design's pages: its lines, maps and feed, built without assigning anybody to them.

    python design.py quito                  the baseline: the city's lines as its inputs give them
    python design.py quito l1_double        designs/quito/l1_double.json

Seconds, not minutes: the feed is written from the lines (gtfs.write_gtfs), and each bus route is
drawn along the shortest way through the streets between its stops (streets.Streets.path) - a
preview of what a simulation's map matching will do, since only a simulation imports the feed
into AequilibraE. The metro runs in a tunnel and is drawn stop to stop.

What it writes, in output/transit/designs/<city>-<name>/:

    exports/gtfs_feed.zip     the design's feed - its timetable, as a simulation will import it
    exports/lines.geojson     every route and direction along the streets and stop to stop
    exports/operations.csv    what each line takes to run: vehicles, vehicle-km, vehicle-hours
    maps/network.html         the lines and stops, along the streets or stop to stop
    summary.json              what the design is and changes, and its headline numbers
"""
import csv
import json
import time

from core import report
from core.maps import MapKit

from . import load as load_case
from . import maps
from . import scenario as designs
from .gtfs import (declared_station_names, departures, directions, headsign, km,
                   run_time_s, said_service, wide_stations, write_gtfs)
from .fleet import DAYS, operations, week
from .paths import BASELINE, DesignPaths
from .streets import line_paths, streets_for

MODES = {0: "tram", 1: "metro", 2: "rail", 3: "bus"}


def _operations(paths, lines, colors, paths_along, settings, start_h, end_h, inputs_capacity=None):
    """Each line's vehicles, vehicle-km and vehicle-hours on each type of day (transit/fleet.py),
    printed and written to exports/operations.csv; returns the rows."""
    rows = []
    for key, line in lines.items():
        lengths = leg_km = None
        if all((key, d) in paths_along for d in range(len(directions(line)))):
            lengths = [paths_along[(key, d)]["km"] for d in range(len(directions(line)))]
            leg_km = [paths_along[(key, d)]["leg_km"] for d in range(len(directions(line)))]
        o = operations(line, start_h * 3600, end_h * 3600, settings.LAYOVER_SHARE,
                       settings.LAYOVER_MIN_S, lengths, leg_km)
        mode = MODES.get(line["route_type"], str(line["route_type"]))
        row = {"route": line["short"], "mode": mode,
               "capacity": line.get("capacity") or (inputs_capacity or {}).get(mode),
               "color": colors.get(line["short"], "#555555"), "km": o["km"],
               "round_trip_min": o["round_trip_min"], "layover_min": o["layover_min"]}
        for day in DAYS:
            for field in ("vehicles", "departures", "vehicle_km", "vehicle_hours"):
                row[f"{field}_{day}"] = o[day][field] if day in o else None
        row["vehicle_km_week"] = round(week(o, "vehicle_km"), 1)
        row["vehicle_hours_week"] = round(week(o, "vehicle_hours"), 1)
        rows.append(row)
        print(f"  {line['short']:<10} round trip {o['round_trip_min']:5.1f} min  "
              + "  ".join(f"{day} {o[day]['vehicles']:>3} vehicles {o[day]['vehicle_km']:>8,.0f} km"
                          if day in o else f"{day} no service" for day in DAYS))
    path = paths.output + "/exports/operations.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def _checks(lines, streets, paths_along, settings):
    """What a design may want to look at before it is simulated, each a "WARNING:" line - the
    editor shows them beside its Save button. Bus stops too far from a street to be map-matched
    or on streets cut off from the rest, legs with no way along the streets, leg times set by
    hand at an implausible speed, stations only one stop belongs to."""
    found = 0
    for key, line in lines.items():
        name = line["short"]
        if line["route_type"] in settings.MATCHED_ROUTE_TYPES:
            stops = {(s[1], s[2]): s[0] for s in line["stops"] + line.get("stops_back", [])}
            for (lat, lon), check in zip(stops, streets.nearest(list(stops))):
                if check["metres"] > settings.MATCH_RADIUS_M:
                    print(f"WARNING: {name}'s stop {stops[(lat, lon)]} is {check['metres']:.0f} m "
                          f"from the nearest street: its route cannot be matched there")
                    found += 1
                elif check["cut_off"]:
                    print(f"WARNING: {name}'s stop {stops[(lat, lon)]} is on "
                          f"{check['street'] or 'an unnamed street'}, cut off from the other "
                          f"streets: no bus gets in or out")
                    found += 1
        for d, journey in enumerate(directions(line)):
            along = paths_along.get((key, d))
            if along and along["unrouted"]:
                print(f"WARNING: {name}, towards {journey[-1][0]}: {along['unrouted']} leg(s) with "
                      f"no way along the streets - drawn and timed as a straight line")
                found += 1
            for (dd, k), seconds in (line.get("leg_s") or {}).items():
                if dd != d or k >= len(journey) - 1:
                    continue
                km = (along["leg_km"][k] if along else None) or _straight(journey[k], journey[k + 1])
                kmh = km / (seconds / 3600)
                if kmh > 2.5 * line["speed_kmh"] or kmh < 0.25 * line["speed_kmh"]:
                    print(f"WARNING: {name}, {journey[k][0]} -> {journey[k + 1][0]}: set to "
                          f"{seconds / 60:.1f} min, {kmh:.0f} km/h over its {km:.2f} km - against "
                          f"the line's {line['speed_kmh']:g} km/h")
                    found += 1
    platforms = {}
    for line in lines.values():
        for s in line["stops"] + line.get("stops_back", []):
            if s[3]:
                platforms.setdefault(s[3], set()).add((line["short"], s[1], s[2]))
    for station, stops in sorted(platforms.items()):
        if len({route for route, _, _ in stops}) < 2:
            print(f"WARNING: station {station} has only {next(iter(stops))[0]}'s stop: no line to "
                  f"change to there")
            found += 1
    if not found:
        print("Nothing: every bus stop is on a street, every leg has a way along them, every time "
              "set by hand is plausible and every station has two lines or more.")


def _straight(a, b):
    return km((a[1], a[2]), (b[1], b[2]))


def _per_hour(times):
    """{hour: departures in it}."""
    out = {}
    for t in times:
        out[t // 3600] = out.get(t // 3600, 0) + 1
    return out


def build(city, name=BASELINE):
    """Build design `name` of `city` into its folder; returns its DesignPaths."""
    started = time.time()
    settings, inputs = load_case(city)
    paths = DesignPaths(city, name)
    paths.prepare_outputs()
    if name == BASELINE:
        design = {"name": BASELINE, "label": "baseline",
                  "description": "The city's lines as they run today: the network every design "
                                 "changes.", "changes": []}
        lines, colors, said = inputs.LINES, inputs.LINE_COLORS, []
    else:
        design = designs.load(city, name)
        lines, colors, said = designs.apply(design, inputs.LINES, inputs.LINE_COLORS)

    report.section(f"The design: {design['label']}")
    if design["description"]:
        print(design["description"] + "\n")
    for line in said or ["no changes: the baseline"]:
        print(f"  - {line}")

    # The buses' way along the streets: for the map, and for the feed's shapes.
    from .project import ensure_street_cache
    ensure_street_cache(paths.street_network, inputs.BBOX, inputs.LABEL)
    streets = streets_for(paths.street_network)
    paths_along = line_paths(lines, streets, settings.MATCHED_ROUTE_TYPES)

    report.section("The feed")
    start_h, end_h = inputs.SERVICE_HOURS
    counts = write_gtfs(paths.gtfs, lines, inputs.AGENCY, inputs.CALENDAR, start_h * 3600,
                        end_h * 3600, colors=colors,
                        shapes={k: v["path"] for k, v in paths_along.items()},
                        leg_km={k: v["leg_km"] for k, v in paths_along.items()})
    for table, n in counts.items():
        print(f"  {table:<16} {n:>6,} rows")
    stations = declared_station_names(lines)
    print(f"\n{len(stations)} stations declared: {', '.join(stations) or 'none'}")
    wide = wide_stations(lines, settings.MAX_STATION_SPREAD_M)
    if len(wide):
        print(f"WARNING: {len(wide)} station(s) group platforms more than "
              f"{settings.MAX_STATION_SPREAD_M} m apart:")
        print(wide.to_string(index=False))

    report.section("The lines along the streets")
    features, rows = [], []
    for key, line in lines.items():
        mode = MODES.get(line["route_type"], str(line["route_type"]))
        color = colors.get(line["short"], "#555555")
        each_way = departures(line, start_h * 3600, end_h * 3600)
        busiest = max(_per_hour(each_way).values(), default=0)
        for direction, stops in enumerate(directions(line)):
            points = [(lat, lon) for _, lat, lon, _ in stops]
            straight = [[lon, lat] for lat, lon in points]
            along, km, unrouted = straight, None, 0
            found = paths_along.get((key, direction))
            if found:
                along = [[lon, lat] for lat, lon in found["path"]]
                km, unrouted = found["km"], found["unrouted"]
            towards = headsign(stops)
            props = {"route": line["short"], "name": line["long"], "mode": mode, "color": color,
                     "towards": towards, "headway_min": line["headway_s"] / 60,
                     "service": said_service(line), "busiest_hour": busiest,
                     # End to end as the feed times it: along the streets, set-by-hand legs too.
                     "run_min": round(run_time_s(line, stops, found["leg_km"] if found else None,
                                                 direction) / 60, 1),
                     "speed_kmh": line["speed_kmh"], "dwell_s": line["dwell_s"],
                     "stops": [list(s) for s in stops], "km_streets": km}
            features.append({"type": "Feature", "properties": dict(props, shape="streets"),
                             "geometry": {"type": "LineString", "coordinates": along}})
            features.append({"type": "Feature", "properties": dict(props, shape="straight"),
                             "geometry": {"type": "LineString", "coordinates": straight}})
            rows.append((line["short"], towards, len(stops), km, unrouted))
            print(f"  {line['short']:<10} towards {towards:<22} {len(stops):>3} stops"
                  + (f"  {km:6.1f} km along the streets" if km is not None else
                     "  (metro: stop to stop)")
                  + (f", {unrouted} leg(s) with no way along the streets" if unrouted else ""))
    with open(paths.lines, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)

    report.section("Things to look at")
    _checks(lines, streets, paths_along, settings)

    report.section("The map")
    kit = MapKit("EPSG:3857", paths.maps)
    maps.map_design(kit, features, design["label"], len(lines))

    n_stops = len({(s[1], s[2]) for line in lines.values()
                   for s in line["stops"] + line.get("stops_back", [])})
    # Departures in each hour, every direction, by mode: the busiest hour of each.
    per_hour = {}
    for line in lines.values():
        mode = MODES.get(line["route_type"], str(line["route_type"]))
        hours = per_hour.setdefault(mode, {})
        each_way = _per_hour(departures(line, start_h * 3600, end_h * 3600))
        for hour, n in each_way.items():
            hours[hour] = hours.get(hour, 0) + n * len(directions(line))
    report.section("What it takes to run")
    ops = _operations(paths, lines, colors, paths_along, settings, start_h, end_h,
                      getattr(inputs, "DEFAULT_CAPACITY", {}))
    fleet, vkm = {}, 0.0
    for row in ops:
        fleet[row["mode"]] = fleet.get(row["mode"], 0) + max(
            row.get(f"vehicles_{d}") or 0 for d in DAYS)
        vkm += row.get("vehicle_km_weekday") or 0
    headline = [["lines", f"{len(lines)}"], ["stops", f"{n_stops}"]] + [
        [f"departures in the busiest hour, {mode}", f"{max(hours.values(), default=0):,.0f}"]
        for mode, hours in sorted(per_hour.items())] + [
        [f"vehicles needed, {mode}", f"{n:,}"] for mode, n in sorted(fleet.items())] + [
        ["vehicle-km a weekday", f"{vkm:,.0f}"]]
    summary = {"kind": "design", "city": inputs.LABEL, "city_key": city, "design": name,
               "label": design["label"], "description": design["description"],
               "changes": said, "finished": time.strftime("%Y-%m-%d %H:%M"),
               "minutes": round((time.time() - started) / 60, 1), "headline": headline,
               "layover": {"share": settings.LAYOVER_SHARE, "min_s": settings.LAYOVER_MIN_S}}
    with open(paths.summary, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1, ensure_ascii=False)
    print(f"\nDone: {paths.output}")
    return paths
