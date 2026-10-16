"""A city's bus lines from OpenStreetMap: its route relations turned into the LINES a city's
public-transport case brings (transit_inputs.py) - for a city without a GTFS feed of its own.

    python -m transit.osm_lines sorocaba

reads the city's OSM extract (its transit_inputs.OSM_DIR: routes.json - the bus route relations
with their geometry, `out geom` - stop_nodes.json - their stops' tags - and terminals.json) and
writes OSM_DIR/lines.json, which transit_inputs reads as its LINES. What OSM has is used as it
is; what it does not have is assumed, from the city's transit_settings, and said in the report:

    a line          the route relations sharing a `ref` - its two directions paired by their
                    `from` and `to`; a third or fourth (a variant) a line of its own, "52b"
    its stops       the relation's stop members in order (`stop`, `start_stop`, `end`, ...), or
                    its platforms if it lists none; two in a row a few metres apart are one
    a stop's name   its OSM name - or the street it stands on, or "Stop n"
    a station       every stop within TERMINAL_RADIUS_M of a mapped terminal (amenity=
                    bus_station): passengers change line there
    its headway     its `interval` tag ("00:12"), or OSM_HEADWAY_MIN - ASSUMED
    its speed, dwell and places   OSM_SPEED_KMH, OSM_DWELL_S, OSM_CAPACITY - ASSUMED

A route is kept when most of its stops - CITY_SHARE - are inside the city limit: the regional
routes passing through are another network's (the state's feed, for Sorocaba).
"""
import collections
import json
import os
import re
import statistics
import sys
import unicodedata

from .gtfs import km

STOP_ROLES = ("stop", "stop_entry_only", "stop_exit_only", "stop_position", "start_stop",
              "end", "forward_stop", "backward_stop")
PLATFORM_ROLES = ("platform", "platform_entry_only", "platform_exit_only")
SAME_STOP_M = 25              # two stops in a row closer than this are one
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7", "#008300",
           "#e34948", "#7f5539", "#00838f", "#6d4c41", "#9e9d24"]


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _ident(text):
    """"Terminal São Bento" -> "TERMINAL_SAO_BENTO"."""
    text = unicodedata.normalize("NFD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_") or "X"


def _minutes(interval):
    """OSM's interval ("00:12", "12", "PT12M") in minutes, or None."""
    if not interval:
        return None
    text = str(interval).split(";")[0].strip()
    if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", text):
        parts = [int(p) for p in text.split(":")]
        return parts[0] * 60 + parts[1] + (parts[2] / 60 if len(parts) > 2 else 0)
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    found = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", text)
    if found:
        return int(found.group(1) or 0) * 60 + int(found.group(2) or 0)
    return None


def _stops(relation, names):
    """The relation's stops in order: [(node id, lat, lon, name)] - its stop members, or its
    platforms when it has none; neighbours closer than SAME_STOP_M merged."""
    members = relation.get("members", [])
    chosen = [m for m in members if m["type"] == "node" and m.get("role", "") in STOP_ROLES]
    if not chosen:
        chosen = [m for m in members if m.get("role", "") in PLATFORM_ROLES]
    out = []
    for m in chosen:
        if m["type"] == "node":
            lat, lon = m.get("lat"), m.get("lon")
        else:                                             # a platform drawn as a way: its middle
            pts = m.get("geometry") or []
            if not pts:
                continue
            lat = sum(p["lat"] for p in pts) / len(pts)
            lon = sum(p["lon"] for p in pts) / len(pts)
        if lat is None:
            continue
        if out and km((out[-1][1], out[-1][2]), (lat, lon)) * 1000 < SAME_STOP_M:
            continue
        out.append((m["ref"], round(lat, 6), round(lon, 6), names.get(m["ref"], "")))
    return out


def _length(stops):
    return sum(km(a[1:3], b[1:3]) for a, b in zip(stops, stops[1:]))


def _clean(stops, settings):
    """A relation's stops without its slips: cut at every gap between two stops in a row longer
    than OSM_JUMP_KM and OSM_JUMP_FACTOR times the median spacing - a stop of the far end listed
    first or last, a stretch of another route - and the longest piece kept; with how many it
    left out."""
    if len(stops) < 3:
        return stops, 0
    legs = [km(a[1:3], b[1:3]) for a, b in zip(stops, stops[1:])]
    limit = max(settings.OSM_JUMP_KM, settings.OSM_JUMP_FACTOR * statistics.median(legs))
    pieces = [[stops[0]]]
    for stop, leg in zip(stops[1:], legs):
        if leg > limit:
            pieces.append([])
        pieces[-1].append(stop)
    best = max(pieces, key=len)
    return best, len(stops) - len(best)


def _one_line(out, back, settings):
    """Whether two directions are one line's: each ends near where the other starts, and
    neither is much longer - else one of them is mapped in part, or is another route."""
    ends = max(km(out[-1][1:3], back[0][1:3]), km(back[-1][1:3], out[0][1:3]))
    a, b = _length(out), _length(back)
    return ends <= settings.OSM_ENDS_KM and max(a, b) <= settings.OSM_LENGTH_RATIO * min(a, b)


def _pairs(relations):
    """A ref's relations as lines: [(outward, return or None)] - two whose from and to are each
    other's to and from are one line; any other pairing left over, a line each."""
    left = list(relations)
    out = []
    while left:
        a = left.pop(0)
        ta = a["tags"]
        match = next((b for b in left if b["tags"].get("from") and b["tags"].get("from") == ta.get("to")
                      and b["tags"].get("to") == ta.get("from")), None)
        if match is None and len(left) == 1 and not out:
            match = left[0]                               # the two of a ref: its two directions
        if match is not None:
            left.remove(match)
        out.append((a, match))
    return out


def lines_from_osm(routes, nodes, terminals, city_limit, settings, streets=None):
    """LINES and LINE_COLORS from the OSM extract, and a report: [str]."""
    from shapely.geometry import Point
    names = {e["id"]: e.get("tags", {}).get("name", "") for e in nodes.get("elements", [])}
    hubs = {}
    for t in terminals.get("elements", []):
        name = t.get("tags", {}).get("name")
        centre = t.get("center") or {"lat": t.get("lat"), "lon": t.get("lon")}
        if name and centre.get("lat") is not None:
            hubs.setdefault(name, (centre["lat"], centre["lon"]))
    report = []
    by_ref = collections.defaultdict(list)
    for r in routes.get("elements", []):
        if r.get("type") != "relation":
            continue
        stops = _stops(r, names)
        ref = r["tags"].get("ref") or r["tags"].get("name") or str(r["id"])
        if len(stops) < 2:
            report.append(f"skipped {ref} ({r['tags'].get('name', '')}): no stops mapped")
            continue
        inside = sum(city_limit.contains(Point(lon, lat)) for _, lat, lon, _ in stops) / len(stops)
        if inside < settings.CITY_SHARE:
            report.append(f"skipped {ref} ({r['tags'].get('name', '')}): {inside:.0%} of its stops "
                          f"in the city - a regional route")
            continue
        r["_stops"] = stops
        by_ref[ref].append(r)

    lines, colors, street_named, stations = {}, {}, 0, collections.Counter()
    cleaned = 0

    def name_of(node, lat, lon, osm_name, n):
        nonlocal street_named
        if osm_name:
            return osm_name
        if streets is not None:
            street = streets.nearest([(lat, lon)])[0]
            if street["street"] and street["metres"] < 60:
                street_named += 1
                return street["street"]
        return f"Stop {n}"

    def station_of(lat, lon):
        best = min(((km((lat, lon), xy) * 1000, name) for name, xy in hubs.items()),
                   default=(None, None))
        if best[0] is not None and best[0] <= settings.TERMINAL_RADIUS_M:
            stations[best[1]] += 1
            return "EST_" + _ident(best[1])
        return ""

    moved = {}

    def on_street(lat, lon):
        """A bus stop further from a street than the map matcher looks (MATCH_RADIUS_M) - a
        terminal's bays, whose lanes OSM's street network leaves out, or a stop mapped off the
        road - moved onto the nearest street a bus can come and go along (not an island of
        them), so its route can be matched there. A stop several lines share moves to the same
        place for each."""
        if streets is None or 3 not in settings.MATCHED_ROUTE_TYPES:
            return lat, lon
        if (lat, lon) not in moved:
            near = streets.nearest([(lat, lon)])[0]
            if near["metres"] > settings.MATCH_RADIUS_M:
                near = streets.nearest([(lat, lon)], connected=True)[0]
                moved[(lat, lon)] = (near["metres"], *near["snap"])
            else:
                moved[(lat, lon)] = None
        return tuple(moved[(lat, lon)][1:]) if moved[(lat, lon)] else (lat, lon)

    def as_stops(osm):
        # Named and put in a station where OSM has it; then onto its street if it is off it.
        return [(name_of(node, lat, lon, osm_name, k + 1), *on_street(lat, lon),
                 station_of(lat, lon)) for k, (node, lat, lon, osm_name) in enumerate(osm)]

    for ref in sorted(by_ref, key=lambda x: (len(x), x)):
        for k, (out, back) in enumerate(_pairs(by_ref[ref])):
            short = ref if k == 0 else f"{ref}{chr(ord('a') + k)}"
            key = "OSM_" + _ident(short)
            # Its stops without OSM's slips; two directions that are not one line's, the longer.
            way, cut = _clean(out["_stops"], settings)
            fixes = [f"{cut} stop(s) cut off the outward" if cut else ""]
            way_back = None
            if back is not None:
                way_back, cut = _clean(back["_stops"], settings)
                fixes.append(f"{cut} stop(s) cut off the return" if cut else "")
                if not _one_line(way, way_back, settings):
                    if _length(way_back) > _length(way):
                        way = way_back[::-1]
                    way_back = None
                    fixes.append("its directions do not match: runs back by its stops reversed")
            fixes = [f for f in fixes if f]
            if len(way) < settings.OSM_MIN_STOPS:
                report.append(f"skipped {short}: {len(way)} stops left once cleaned")
                continue
            if fixes:
                report.append(f"{short}: " + "; ".join(fixes))
                cleaned += 1
            tags = out["tags"]
            interval = _minutes(tags.get("interval")) or (back and _minutes(back["tags"].get("interval")))
            brt = "brt" in " ".join(str(v) for v in tags.values()).lower()
            kind = "BRT" if brt else "bus"
            long = re.sub(r"\s*\([^)]*\)\s*$", "", tags.get("name", short)).strip(" -") or short
            long = re.sub(r"\s*(→|->|<->)\s*", " - ", long)          # one name for both ways
            line = dict(route_id=key, short=short, long=long, route_type=3,
                        headway_s=int(round((interval or settings.OSM_HEADWAY_MIN[kind]) * 60)),
                        speed_kmh=settings.OSM_SPEED_KMH[kind], dwell_s=settings.OSM_DWELL_S,
                        capacity=settings.OSM_CAPACITY[kind], stops=as_stops(way),
                        osm={"relations": [out["id"]] + ([back["id"]] if back else []),
                             "operator": tags.get("operator", ""), "headway": "OSM" if interval
                             else "assumed"})
            if way_back is not None:
                line["stops_back"] = as_stops(way_back)
            lines[key] = line
            colors[short] = "#d62728" if brt else PALETTE[len(colors) % len(PALETTE)]
    # A terminal only one line stops at is no change of line: no station there.
    served = collections.defaultdict(set)
    for key, line in lines.items():
        for s in line["stops"] + line.get("stops_back", []):
            if s[3]:
                served[s[3]].add(key)
    lonely = {st for st, keys in served.items() if len(keys) < 2}
    for line in lines.values():
        for part in ("stops", "stops_back"):
            if part in line:
                line[part] = [(n, la, lo, "" if st in lonely else st) for n, la, lo, st in line[part]]
    n_stops = sum(len(l["stops"]) + len(l.get("stops_back", [])) for l in lines.values())
    report += [f"{cleaned} lines cleaned of OSM's slips (above)",
               f"{len(lines)} lines from {sum(len(v) for v in by_ref.values())} OSM relations; "
               f"{n_stops} stops, {street_named} named after their street",
               f"{sum(1 for l in lines.values() if l['osm']['headway'] == 'OSM')} headways from OSM, "
               f"{sum(1 for l in lines.values() if l['osm']['headway'] == 'assumed')} assumed",
               f"{sum(1 for m in moved.values() if m)} stop places more than "
               f"{settings.MATCH_RADIUS_M} m from a street moved onto the nearest one "
               f"({', '.join(f'{m[0]:.0f} m' for m in sorted(moved.values(), key=lambda m: -(m or (0,))[0]) if m) or 'none'})",
               f"stations at terminals, two lines or more: "
               f"{sorted(s for s in served if s not in lonely) or 'none'}"]
    return lines, colors, report


def main(city):
    import geopandas as gpd

    from . import load
    from .paths import street_cache
    from .project import ensure_street_cache
    from .streets import streets_for

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")    # OSM's names: any character
    settings, inputs = load(city)
    folder = inputs.OSM_DIR
    limit = gpd.read_file(inputs.CITY_LIMIT).to_crs("EPSG:4326")
    city_limit = limit.union_all() if hasattr(limit, "union_all") else limit.unary_union
    cache = street_cache(city)
    ensure_street_cache(cache, inputs.BBOX, inputs.LABEL)
    streets = streets_for(cache)
    lines, colors, report = lines_from_osm(
        _load(os.path.join(folder, "routes.json")), _load(os.path.join(folder, "stop_nodes.json")),
        _load(os.path.join(folder, "terminals.json")), city_limit, settings, streets)
    out = os.path.join(folder, "lines.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"source": "OpenStreetMap contributors (ODbL)", "lines": lines, "colors": colors,
                   "report": report}, f, indent=1, ensure_ascii=False)
    print("\n".join(report))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sorocaba")
