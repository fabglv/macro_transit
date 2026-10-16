"""A design: edits to a city's public-transport lines, saved as a file. transit/design.py builds
its pages (its lines, maps and feed); a simulation (transit/pipeline.py) assigns passengers to it.

    designs/<city>/<name>.json

    {
      "label": "L1 every 2.5 minutes",
      "description": "free text, shown on the results page",
      "changes": [
        {"type": "headway",   "route": "L1", "minutes": 2.5},
        {"type": "frequency", "route": "Trolebus", "factor": 1.5},
        {"type": "speed",     "route": "Ecovia", "kmh": 22},
        {"type": "add_line",  "route": "L2", "name": "Metro Linea 2", "mode": "metro",
                              "headway_min": 5, "speed_kmh": 30, "dwell_s": 30, "color": "#9467bd",
                              "stops": [["Chilibulo", -0.236, -78.542, ""], ...],
                              "stops_back": [...],
                              "hours": ["05:30", "23:00"],
                              "bands": [{"from": "07:00", "to": "09:00", "headway_min": 3}],
                              "loop": "one_way",
                              "via": [[0, 2, [[-0.231, -78.528]]]]},
        {"type": "service",   "route": "Ecovia", "headway_min": 4, "speed_kmh": 17,
                              "dwell_s": 25, "hours": ["05:30", "23:00"],
                              "bands": [{"from": "07:00", "to": "09:00", "headway_min": 2}],
                              "saturday": {"headway_min": 6, "hours": ["06:00", "22:00"]},
                              "sunday": "none"},
        {"type": "edit_line", "route": "Trolebus", "headway_min": 3, "speed_kmh": 18,
                              "dwell_s": 25, "stops": [...], "bands": [...]},
        {"type": "remove_line", "route": "Ecovia"}
      ]
    }

A route is named by its short name ("L1", "Trolebus") or its key in the city's LINES. A stop is
[name, lat, lon, station]: `station` is the GTFS parent_station - give a new line's stop the same
one as an existing platform ("EST_MARIN") and passengers can change between them there; leave it
"" for an ordinary stop. `stops_back` is optional: without it the return trip is the outward one
reversed.

`service` gives an existing line a new timetable and nothing else: its headway, and if given its
speed, dwell, hours and bands - no `hours` is the city's service hours, no `bands` one headway all
day. `via` shapes a bus line's route: [journey, leg, [[lat, lon], ...]] - the way from stop number
`leg` of journey `journey` (0 outward or one way round, 1 back or the other way round, as
gtfs.directions lists their stops) to the next passes through those points, in that order. It
shapes the route the maps draw, the feed's shapes - which guide a simulation's map matching - and
everything measured along it: a bus's running times, vehicle-km and vehicles needed.

`capacity` is a line's places per vehicle, seated and standing: what its capacity figures count.
`leg_minutes` sets the running time of some legs by hand: [journey, leg, minutes] - the leg from
stop number `leg` of journey `journey` to the next - instead of the time its length at the line's
speed gives. Both go with a new line, a redrawn line or a `service`.

`edit_line` redraws an existing line: the same as a new line's, all of it - its stops (moved,
added, dropped), its way back or loop, its service - but it keeps its route, id and mode. What it
leaves out is as a new line would have it: no `stops_back` is the way out reversed, no `hours` the
city's service hours, no `bands` one headway all day.

A timetable - a new line's, an edited line's, a `service` - is its weekdays'. `saturday` and
`sunday` are left out to run the weekdays' timetable then too; "none" for no service that day; or
a timetable of their own: `headway_min`, and `hours` and `bands` as below.

A new line's service: `hours` its first departure and when it stops departing (the city's service
hours without it), `headway_min` its headway, and `bands` other hours with another headway - the
peaks, say. A time earlier than the first departure is the next day's ("00:30"). `loop` makes it a
loop - its stops and on to the first again - run "one_way" round or "both_ways"; a loop has no
`stops_back`.

What a design does not change is the demand: a simulation of it uses the baseline's, read from
the baseline's simulation, so two simulations compare two networks carrying the same travellers. A new line along an
unserved corridor therefore picks up the trips the baseline demand already put there - it does
not generate new ones.
"""
import copy
import json
import os


MODES = {"tram": 0, "metro": 1, "rail": 2, "bus": 3}
# A new route's colour, when the design gives none: the page's categorical palette, last slots
# first, so it does not repeat a colour the baseline routes are likely to use.
NEW_LINE_COLORS = ["#4a3aa7", "#e87ba4", "#eda100", "#1baf7a", "#e34948"]


def scenario_path(city, name):
    from .paths import design_file
    return design_file(city, name)


def load(city, name):
    """The design file `designs/<city>/<name>.json`, read and checked."""
    path = scenario_path(city, name)
    if not os.path.exists(path):
        folder = os.path.dirname(path)
        known = sorted(f[:-5] for f in os.listdir(folder) if f.endswith(".json")) \
            if os.path.isdir(folder) else []
        raise FileNotFoundError(f"no design {path}"
                                + (f"; {city} has: {', '.join(known)}" if known else ""))
    with open(path, encoding="utf-8") as f:
        scenario = json.load(f)
    scenario["name"] = name
    scenario.setdefault("label", name.replace("_", " "))
    scenario.setdefault("description", "")
    if not scenario.get("changes"):
        raise ValueError(f"{path}: a design needs at least one change")
    return scenario


def apply(scenario, lines, colors):
    """The city's LINES and LINE_COLORS with the design's changes made, and one sentence per
    change describing it. The originals are left untouched."""
    lines, colors = copy.deepcopy(lines), dict(colors)
    said = []
    for n, change in enumerate(scenario["changes"], 1):
        kind = change.get("type")
        where = f"change {n} ({kind})"
        if kind == "add_line":
            said.append(_add_line(lines, colors, change, where))
            continue
        if kind == "edit_line":
            said.append(_edit_line(lines, colors, change, where))
            continue
        key = _route_key(lines, change.get("route"), where)
        line = lines[key]
        if kind == "service":
            said.append(_timetable(line, change, where))
        elif kind == "headway":
            minutes = _positive(change, "minutes", where)
            said.append(f"{line['short']}: a vehicle every {minutes:g} min "
                        f"(was {line['headway_s'] / 60:g})")
            line["headway_s"] = _seconds(minutes * 60)
        elif kind == "frequency":
            factor = _positive(change, "factor", where)
            before = line["headway_s"]
            line["headway_s"] = _seconds(before / factor)
            if line.get("bands_s"):                         # every hour of it, the peaks too
                line["bands_s"] = [(a, b, _seconds(h / factor)) for a, b, h in line["bands_s"]]
            for own in (line.get("days") or {}).values():  # and the weekend's
                if own is not None:
                    own["headway_s"] = _seconds(own["headway_s"] / factor)
                    if own.get("bands_s"):
                        own["bands_s"] = [(a, b, _seconds(h / factor)) for a, b, h in own["bands_s"]]
            said.append(f"{line['short']}: {factor:g} times the vehicles - every "
                        f"{round(line['headway_s'] / 60, 2):g} min (was {before / 60:g})")
        elif kind == "speed":
            kmh = _positive(change, "kmh", where)
            said.append(f"{line['short']}: commercial speed {kmh:g} km/h "
                        f"(was {line['speed_kmh']:g})")
            line["speed_kmh"] = kmh
        elif kind == "remove_line":
            said.append(f"{line['short']}: removed")
            del lines[key]
        else:
            raise ValueError(f"{where}: unknown type {kind!r}; known: service, headway, frequency, "
                             f"speed, add_line, edit_line, remove_line")
    if not lines:
        raise ValueError("the design removes every line; there is nothing left to assign")
    return lines, colors, said


def _add_line(lines, colors, change, where):
    route = str(change.get("route", "")).strip()
    if not route:
        raise ValueError(f"{where}: a new line needs a 'route' (its short name, e.g. 'L2')")
    route_id = route.upper().replace(" ", "_")
    if any(route in (key, line["short"], line["route_id"]) or route_id in (key, line["route_id"])
           for key, line in lines.items()):
        raise ValueError(f"{where}: there already is a route {route!r}")
    mode = change.get("mode", "bus")
    if mode not in MODES:
        raise ValueError(f"{where}: mode {mode!r} unknown; one of {', '.join(MODES)}")
    line = _line(change, where, route_id, route, MODES[mode])
    stops = line["stops"]
    lines[line["route_id"]] = line
    used = set(colors.values())
    colors[route] = change.get("color") or next(
        (c for c in NEW_LINE_COLORS if c not in used), NEW_LINE_COLORS[0])
    from .gtfs import said_service
    shape = (f"a loop of {len(stops)} stops from {stops[0][0]}, "
             f"{'one way round' if line['loop'] == 'one_way' else 'both ways round'}"
             if line.get("loop") else f"{len(stops)} stops from {stops[0][0]} to {stops[-1][0]}"
             + (", back by its own stops" if line.get("stops_back") else ""))
    return (f"{route}: a new {mode} line, {shape}, {said_service(line)} at "
            f"{line['speed_kmh']:g} km/h{_said_days(line)}")


def _line(change, where, route_id, short, route_type):
    """A line as LINES holds it, from an add_line or edit_line change."""
    line = dict(route_id=route_id, short=short, long=change.get("name") or short,
                route_type=route_type,
                headway_s=_seconds(_positive(change, "headway_min", where) * 60),
                speed_kmh=_positive(change, "speed_kmh", where),
                dwell_s=_seconds(change.get("dwell_s", 30)),
                stops=_stops(change.get("stops"), where))
    if change.get("stops_back"):
        line["stops_back"] = _stops(change["stops_back"], where + " stops_back")
    _service(line, change, where)
    _via(line, change.get("via"), where)
    _capacity_and_times(line, change, where)
    return line


def _capacity_and_times(line, change, where):
    """A line's places per vehicle and the leg times set by hand, checked, onto `line`:
    `capacity` and `leg_s` {(journey, leg): seconds}."""
    from .gtfs import directions
    if change.get("capacity") is not None:
        line["capacity"] = int(round(_positive(change, "capacity", where)))
    if change.get("leg_minutes"):
        journeys = directions(line)
        out = {}
        for item in change["leg_minutes"]:
            try:
                d, k, minutes = int(item[0]), int(item[1]), float(item[2])
            except (TypeError, ValueError, IndexError):
                raise ValueError(f"{where}: a leg time is [journey, leg, minutes], not {item!r}") \
                    from None
            if not (0 <= d < len(journeys) and 0 <= k < len(journeys[d]) - 1):
                raise ValueError(f"{where}: no leg {k} in journey {d} for its time")
            if minutes <= 0:
                raise ValueError(f"{where}: a leg's time must be more than 0 minutes")
            out[(d, k)] = _seconds(minutes * 60)
        line["leg_s"] = out


def _via(line, via, where):
    """The via points of a line's legs, checked, onto `line["via"]`: {(journey, leg): [(lat,
    lon), ...]}."""
    if not via:
        return
    from .gtfs import directions
    journeys = directions(line)
    out = {}
    for item in via:
        try:
            d, k, points = int(item[0]), int(item[1]), item[2]
            points = [(float(p[0]), float(p[1])) for p in points]
        except (TypeError, ValueError, IndexError):
            raise ValueError(f"{where}: a via entry is [journey, leg, [[lat, lon], ...]], not "
                             f"{item!r}") from None
        if not (0 <= d < len(journeys) and 0 <= k < len(journeys[d]) - 1):
            raise ValueError(f"{where}: no leg {k} in journey {d} for its via points")
        if points:
            out[(d, k)] = points
    if out:
        line["via"] = out


def _edit_line(lines, colors, change, where):
    """An existing line redrawn: everything the change gives, its route, id and mode kept."""
    from .gtfs import said_service
    key = _route_key(lines, change.get("route"), where)
    old = lines[key]
    change = dict(change)
    change.setdefault("name", old["long"])
    change.setdefault("dwell_s", old["dwell_s"])
    line = _line(change, where, old["route_id"], old["short"], old["route_type"])
    lines[key] = line
    if change.get("color"):
        colors[old["short"]] = change["color"]
    places = lambda l: {(s[1], s[2]) for s in l["stops"] + l.get("stops_back", [])}
    new, gone = len(places(line) - places(old)), len(places(old) - places(line))
    moved = ", ".join(part for part in (
        f"{new} stop{'s' if new != 1 else ''} new or moved" if new else "",
        f"{gone} dropped" if gone else "") if part) or "the same stops"
    shape = ("a loop, " + ("one way round" if line["loop"] == "one_way" else "both ways round")
             if line.get("loop") else "back by its own stops" if line.get("stops_back")
             else "back by the same stops")
    return (f"{line['short']}: redrawn - {len(line['stops'])} stops ({moved}), {shape}, "
            f"{said_service(line)} at {line['speed_kmh']:g} km/h{_said_days(line)}")


DAY = 24 * 3600


def _timetable(line, change, where):
    """An existing line's new timetable: its headway, and its speed, dwell, hours and bands."""
    from .gtfs import said_service
    line["headway_s"] = _seconds(_positive(change, "headway_min", where) * 60)
    if change.get("speed_kmh") is not None:
        line["speed_kmh"] = _positive(change, "speed_kmh", where)
    if change.get("dwell_s") is not None:
        line["dwell_s"] = _seconds(change["dwell_s"])
    line.pop("hours_s", None)
    line.pop("bands_s", None)
    line.pop("days", None)
    line.pop("leg_s", None)
    _hours_bands(line, change, where)
    _days(line, change, where)
    _capacity_and_times(line, change, where)
    return (f"{line['short']}: a new timetable - {said_service(line)} at "
            f"{line['speed_kmh']:g} km/h, {line['dwell_s']:g} s at a stop{_said_days(line)}")


def _service(line, change, where):
    """A new line's hours, bands, weekend and loop, checked, onto `line` (in seconds)."""
    _hours_bands(line, change, where)
    _days(line, change, where)
    _loop(line, change, where)


def _days(line, change, where):
    """Saturday's and Sunday's timetables: left out, the weekdays'; "none", no service; or their
    own - onto `line["days"]` as None or {headway_s, hours_s, bands_s}."""
    for day in ("saturday", "sunday"):
        value = change.get(day)
        if value in (None, "same"):
            continue
        days = line.setdefault("days", {})
        if value == "none":
            days[day] = None
        elif isinstance(value, dict):
            own = {"headway_s": _seconds(_positive(value, "headway_min", f"{where} {day}") * 60)}
            _hours_bands(own, value, f"{where} {day}")
            days[day] = own
        else:
            raise ValueError(f"{where}: {day!r} is 'none', or a timetable "
                             f"{{headway_min, hours, bands}}, not {value!r}")


def _said_days(line):
    """"; Saturday every 6 min, 06:00-22:00; no service on Sunday" - or nothing."""
    from .gtfs import said_service
    out = ""
    if line.get("via"):
        n = len(line["via"])
        out += f"; its route shaped through via points on {n} leg{'s' if n > 1 else ''}"
    if line.get("leg_s"):
        n = len(line["leg_s"])
        out += f"; {n} leg time{'s' if n > 1 else ''} set by hand"
    if line.get("capacity"):
        out += f"; {line['capacity']} places a vehicle"
    for day, own in (line.get("days") or {}).items():
        out += (f"; no service on {day.title()}" if own is None
                else f"; {day.title()} {said_service(own)}")
    return out


def _hours_bands(line, change, where):
    """A line's own hours and its bands of other headways, checked, onto `line` (seconds)."""
    start = end = None
    if change.get("hours"):
        hours = change["hours"]
        if not isinstance(hours, (list, tuple)) or len(hours) != 2:
            raise ValueError(f"{where}: 'hours' is [first departure, end], e.g. ['05:30', '23:00']")
        start, end = _time(hours[0], where), _time(hours[1], where)
        if end == start:
            raise ValueError(f"{where}: the service ends when it starts")
        if end < start:                                     # past midnight
            end += DAY
        line["hours_s"] = (start, end)
    bands = []
    for band in change.get("bands") or []:
        a, b = _time(band.get("from"), where), _time(band.get("to"), where)
        if start is not None:
            a, b = (a + DAY if a < start else a), (b + DAY if b < start else b)
        if b <= a:
            b += DAY
        if start is not None and (a < start or b > end):
            raise ValueError(f"{where}: the hours {band.get('from')}-{band.get('to')} are not "
                             f"inside the line's service")
        bands.append((a, b, _seconds(_positive(band, "headway_min", where) * 60)))
    bands.sort()
    for (a1, b1, _), (a2, _, _) in zip(bands, bands[1:]):
        if a2 < b1:
            raise ValueError(f"{where}: two bands of hours overlap")
    if bands:
        line["bands_s"] = bands


def _loop(line, change, where):
    loop = change.get("loop") or None
    if loop not in (None, "one_way", "both_ways"):
        raise ValueError(f"{where}: 'loop' is 'one_way' or 'both_ways', not {loop!r}")
    if loop and line.get("stops_back"):
        raise ValueError(f"{where}: a loop has no stops_back - it runs its stops round")
    if loop and len(line["stops"]) < 3:
        raise ValueError(f"{where}: a loop needs at least three stops")
    line["loop"] = loop


def _time(text, where):
    """"07:30" -> seconds after midnight."""
    try:
        h, m = (int(x) for x in str(text).strip().split(":")[:2])
    except (TypeError, ValueError):
        raise ValueError(f"{where}: {text!r} is not a time like '07:30'") from None
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"{where}: {text!r} is not a time like '07:30'")
    return h * 3600 + m * 60


def _stops(stops, where):
    if not stops or len(stops) < 2:
        raise ValueError(f"{where}: a line needs at least two stops")
    out = []
    for s in stops:
        if len(s) not in (3, 4):
            raise ValueError(f"{where}: a stop is [name, lat, lon, station], not {s!r}")
        name, lat, lon = str(s[0]), float(s[1]), float(s[2])
        out.append((name, lat, lon, str(s[3]) if len(s) == 4 else ""))
    return out


def _route_key(lines, route, where):
    for key, line in lines.items():
        if route in (key, line["short"], line["route_id"]):
            return key
    raise ValueError(f"{where}: no route {route!r}; routes: "
                     f"{', '.join(line['short'] for line in lines.values())}")


def _seconds(value):
    """Whole seconds: a GTFS timetable has no finer clock."""
    return max(1, int(round(float(value))))


def _positive(change, field, where):
    value = change.get(field)
    if not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{where}: '{field}' must be a positive number, not {value!r}")
    return float(value)
