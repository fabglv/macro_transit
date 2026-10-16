"""The Feed views of a public-transport run's page: what the GTFS timetable says, read straight
from exports/gtfs_feed.zip.

    Routes            one row per route and direction: stops, trips, hours, speed, and the
                      headway between any two hours
    Service by hour   departures per hour, route by route
    Calendar          each route on weekdays, Saturday and Sunday: its hours and its service
    Line diagrams     each direction's stops in order: interchanges, one-way stops
    Time-distance     every trip of a direction as a line through time and along the route,
                      between any two hours
    Stop timetables   a stop or station at a time: its service per route and direction,
                      and every departure, hour by hour
    GTFS              the feed's own files, each as a table, and the feed to download

Any GTFS feed reads the same way, so these views do not depend on how the feed was made. They
show the weekdays' service - the services calendar.txt runs Monday to Friday - but Calendar,
which sets the days side by side. Only the standard library, like the rest of the page.
"""
import csv
import html
import io
import json
import math
import os
import statistics
import zipfile

from .stats import _Frame

MODES = {"0": "tram", "1": "metro", "2": "rail", "3": "bus", "4": "ferry", "5": "cable tram",
         "6": "aerial lift", "7": "funicular", "11": "trolleybus", "12": "monorail"}
# For a route the feed gives no colour: the page's categorical palette, in order.
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7",
           "#e34948"]
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]
DAY_COLUMNS = [("Weekdays", WEEKDAYS), ("Saturday", ["saturday"]), ("Sunday", ["sunday"])]
ON_WEEKDAYS = " On weekdays; Calendar sets weekdays, Saturday and Sunday side by side."
WINDOW_FROM_H, WINDOW_SPAN_H = 7, 3       # the hours Routes and Time-distance open on
FILE_ROW_LIMIT = 5000                     # rows shown of one GTFS file


def views(output_dir):
    """[(key, menu label, html)] for the Feed part of the menu; [] without a feed."""
    path = os.path.join(output_dir, "exports", "gtfs_feed.zip")
    if not os.path.exists(path):
        return []
    feed = Feed(path)
    return [("feed-routes", "Routes", _routes(feed)),
            ("feed-hours", "Service by hour", _hours(feed)),
            ("feed-calendar", "Calendar", _calendar(path)),
            ("feed-lines", "Line diagrams", _diagrams(feed)),
            ("feed-marey", "Time–distance", _marey(feed)),
            ("feed-stops", "Stop timetables", _timetables(feed)),
            ("feed-files", "GTFS", _files(path))]


# --- reading the feed ----------------------------------------------------------------------------
class Feed:
    """The parts of a GTFS feed the views use, with times in seconds from midnight."""

    def __init__(self, path):
        with zipfile.ZipFile(path) as z:
            def table(name):
                with z.open(name) as f:
                    return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))
            routes = table("routes.txt")
            trips = table("trips.txt")
            stops = table("stops.txt")
            times = table("stop_times.txt")
            frequencies = table("frequencies.txt") if "frequencies.txt" in z.namelist() else []
            calendar = table("calendar.txt") if "calendar.txt" in z.namelist() else []
        # The weekdays' service: the trips of the services running Monday to Friday.
        weekday = {c["service_id"] for c in calendar if any(c.get(d) == "1" for d in WEEKDAYS)}
        if weekday:
            trips = [t for t in trips if t["service_id"] in weekday]
        self.stops = {s["stop_id"]: s for s in stops}
        self.routes = {}
        for n, r in enumerate(routes):
            colour = (r.get("route_color") or "").strip()
            r["colour"] = f"#{colour}" if colour else PALETTE[n % len(PALETTE)]
            r["name"] = r.get("route_short_name") or r.get("route_long_name") or r["route_id"]
            self.routes[r["route_id"]] = r
        calls = {}
        for t in times:
            calls.setdefault(t["trip_id"], []).append(
                (int(t["stop_sequence"]), t["stop_id"], _seconds(t["arrival_time"]),
                 _seconds(t["departure_time"])))
        # A trip in frequencies.txt is a template: it runs every headway_secs from start_time,
        # the template's own times shifted, and none departs at or after end_time.
        repeats = {}
        for f in frequencies:
            repeats.setdefault(f["trip_id"], []).append(
                (_seconds(f["start_time"]), _seconds(f["end_time"]), int(f["headway_secs"])))
        # One pattern per route and direction: the stop list its trips call at, and the trips.
        self.patterns = {}
        for trip in trips:
            stops_called = sorted(calls.get(trip["trip_id"], []))
            if not stops_called:
                continue
            key = (trip["route_id"], trip.get("direction_id") or "0")
            pattern = self.patterns.setdefault(key, {"route": self.routes[trip["route_id"]],
                                                     "direction": key[1], "trips": []})
            if trip["trip_id"] not in repeats:
                pattern["trips"].append(stops_called)
                continue
            first = stops_called[0][3]
            for start, end, headway in repeats[trip["trip_id"]]:
                for departure in range(start, end, headway):
                    shift = departure - first
                    pattern["trips"].append([(seq, stop, arr + shift, dep + shift)
                                             for seq, stop, arr, dep in stops_called])
        for p in self.patterns.values():
            p["trips"].sort(key=lambda calls_: calls_[0][3])
            p["stops"] = [stop for _, stop, _, _ in p["trips"][0]]
            p["km"] = _cumulative_km([self.stops[s] for s in p["stops"]])
            # A loop ends where it starts: which way round it goes says more.
            p["towards"] = (f"{self.name(p['stops'][1])} (a loop)"
                            if p["stops"][0] == p["stops"][-1] and len(p["stops"]) > 2
                            else self.name(p["stops"][-1]))
        self.ordered = sorted(self.patterns.values(),
                              key=lambda p: (list(self.routes).index(p["route"]["route_id"]),
                                             p["direction"]))

    def name(self, stop_id):
        """A stop's name without the route prefix the feed may carry ("L1 - Solanda")."""
        return self.stops[stop_id]["stop_name"].split(" - ", 1)[-1]

    def by_route(self):
        routes = {}
        for p in self.ordered:
            routes.setdefault(p["route"]["route_id"], []).append(p)
        return routes


def _seconds(text):
    h, m, s = (int(x) for x in text.strip().split(":"))
    return 3600 * h + 60 * m + s


def _clock(seconds):
    return f"{int(seconds // 3600):02d}:{int(seconds % 3600 // 60):02d}"


def _cumulative_km(stops):
    km = [0.0]
    for a, b in zip(stops, stops[1:]):
        km.append(km[-1] + _km(a, b))
    return km


def _km(a, b):
    """Straight-line km between two stops."""
    la1, lo1, la2, lo2 = (math.radians(float(v)) for v in
                          (a["stop_lat"], a["stop_lon"], b["stop_lat"], b["stop_lon"]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 6371 * 2 * math.asin(math.sqrt(h))


def _chip(colour):
    return f"<i class='chip' style='background:{colour}'></i>"


def _window(feed):
    """The service's first and last hours, and the hours a view opens on."""
    first = min(calls[0][3] for p in feed.ordered for calls in p["trips"])
    last = max(calls[-1][2] for p in feed.ordered for calls in p["trips"])
    first_h, last_h = int(first // 3600), math.ceil(last / 3600)
    from_h = min(max(WINDOW_FROM_H, first_h), last_h - 1)
    return first_h, last_h, from_h, min(from_h + WINDOW_SPAN_H, last_h)


def _hour_menus(prefix, feed):
    """From and To menus over the service's hours, classes `<prefix>-from` and `<prefix>-to`."""
    first_h, last_h, from_h, to_h = _window(feed)
    def hours(lo, hi, chosen):
        return "".join(f"<option value='{h}'{' selected' if h == chosen else ''}>{h:02d}:00"
                       f"</option>" for h in range(lo, hi + 1))
    return (f"<label>From <select class='{prefix}-from'>{hours(first_h, last_h - 1, from_h)}"
            f"</select></label><label>To <select class='{prefix}-to'>"
            f"{hours(first_h + 1, last_h, to_h)}</select></label>")


# --- the views -----------------------------------------------------------------------------------
def _routes(feed):
    rows, departures = [], []
    for n, p in enumerate(feed.ordered):
        r = p["route"]
        runs = [calls[-1][2] - calls[0][3] for calls in p["trips"]]
        run_min = statistics.median(runs) / 60
        departures.append(sorted(int(calls[0][3]) for calls in p["trips"]))
        rows.append(
            f"<tr data-i='{n}'><td>{_chip(r['colour'])}{html.escape(r['name'])}</td>"
            f"<td>{MODES.get(r.get('route_type', ''), r.get('route_type', ''))}</td>"
            f"<td>towards {html.escape(p['towards'])}</td>"
            f"<td class='n'>{len(p['stops'])}</td><td class='n'>{len(p['trips'])}</td>"
            f"<td class='n'>{_clock(p['trips'][0][0][3])}</td>"
            f"<td class='n'>{_clock(p['trips'][-1][0][3])}</td>"
            f"<td class='n rt-trips'></td><td class='n rt-headway'></td>"
            f"<td class='n'>{run_min:.0f} min</td><td class='n'>{p['km'][-1]:.1f} km</td>"
            f"<td class='n'>{60 * p['km'][-1] / run_min:.0f} km/h</td></tr>")
    data = json.dumps(departures, separators=(",", ":"))
    return (f"<h1>Routes</h1><p class='note'>What the timetable runs, route by route and in each "
            f"direction.{ON_WEEKDAYS} The trips and the headway - the average gap between departures from the "
            f"first stop - are for the hours chosen. Length and speed are along the stops in a "
            f"straight line, so both are a little short of the street distance.</p>"
            f"<div class='ttpick'>{_hour_menus('rt', feed)}</div>"
            f"<div class='scroll'><table style='width:100%'><thead><tr><th>route</th>"
            f"<th>mode</th><th>direction</th><th>stops</th><th>trips a day</th><th>first</th>"
            f"<th>last</th><th class='rt-h1'>trips in the hours</th>"
            f"<th class='rt-h2'>headway</th><th>run time</th><th>length</th><th>speed</th></tr>"
            f"</thead><tbody>{''.join(rows)}</tbody></table></div>"
            f"<script>{ROUTES_JS.replace('{data}', data)}</script>")


ROUTES_JS = r"""
(() => {
  const departures = {data};
  const view = document.currentScript.closest('.view') || document;
  const [from, to] = ['.rt-from', '.rt-to'].map(c => view.querySelector(c));
  function fill() {
    if (+to.value <= +from.value) to.value = String(+from.value + 1);
    const t0 = +from.value * 3600, t1 = +to.value * 3600;
    const span = `${String(from.value).padStart(2, '0')}–${String(to.value).padStart(2, '0')}`;
    view.querySelector('.rt-h1').textContent = `trips, ${span}`;
    view.querySelector('.rt-h2').textContent = `headway, ${span}`;
    view.querySelectorAll('tr[data-i]').forEach(tr => {
      const n = departures[+tr.dataset.i].filter(t => t >= t0 && t < t1).length;
      const trips = tr.querySelector('.rt-trips'), headway = tr.querySelector('.rt-headway');
      trips.textContent = n; trips.dataset.v = n;
      const minutes = n ? (t1 - t0) / 60 / n : NaN;
      headway.textContent = n ? `${minutes.toFixed(1)} min` : '—';
      headway.dataset.v = n ? minutes : 1e9;          // no trips: last when sorted
    });
  }
  [from, to].forEach(s => s.addEventListener('change', fill));
  fill();
})();
"""


def _hours(feed):
    """Departures per hour in each direction (the average of the route's directions)."""
    series = []
    for patterns in feed.by_route().values():
        counts = [0.0] * 24
        for p in patterns:
            for calls in p["trips"]:
                counts[min(int(calls[0][3] // 3600), 23)] += 1 / len(patterns)
        series.append((patterns[0]["route"]["name"], patterns[0]["route"]["colour"], counts))
    f = _Frame(24, max(max(c) for _, _, c in series), "hour of the day")
    parts = []
    for n, (name, colour, counts) in enumerate(series):
        points = " ".join(f"{f.x(i):.1f},{f.y(c):.1f}" for i, c in enumerate(counts))
        parts.append(f"<polyline points='{points}' fill='none' stroke='{colour}' "
                     f"stroke-width='2' stroke-linejoin='round' data-s='{n}'/>")
    for i in range(24):
        tip = html.escape(f"{i:02d}:00–{i + 1:02d}:00: " + " · ".join(
            f"{name} {c[i]:.0f}" for name, _, c in series))
        dots = "".join(f"<circle cx='{f.x(i):.1f}' cy='{f.y(c[i]):.1f}' r='4' fill='{colour}' "
                       f"class='dot' data-s='{n}'/>" for n, (_, colour, c) in enumerate(series))
        parts.append(f"<g class='col' data-tip='{tip}' data-h='{i}'>{f.hit(i, tip)}{dots}</g>")
    # Each line's name in the legend shows or hides it; the hover lists the lines shown.
    legend = ("<button class='series-all'>All</button><button class='series-none'>None</button>"
              + "".join(f"<button class='series on' data-s='{n}'><i class='line' "
                        f"style='background:{colour}'></i>{html.escape(name)}</button>"
                        for n, (name, colour, _) in enumerate(series)))
    counts = json.dumps([[name, [round(c, 1) for c in counts]] for name, _, counts in series],
                        ensure_ascii=False).replace("</", "<\\/")
    rows = "".join(f"<tr><td>{i:02d}:00</td>" + "".join(f"<td class='n'>{c[i]:.0f}</td>"
                                                        for _, _, c in series) + "</tr>"
                   for i in range(24))
    head = "".join(f"<th>{html.escape(name)}</th>" for name, _, _ in series)
    return (f"<h1>Service by hour</h1><p class='note'>{ON_WEEKDAYS.strip()} Departures per hour from the first stop, in "
            f"each direction (the average of the two). Routes running the same number of "
            f"departures share a line; click a route's name to hide or show it, and hover an "
            f"hour for the count of every route shown.</p><div class='legend toggles'>{legend}"
            f"</div>"
            + f.svg("".join(parts), "Departures per hour by route")
            + f"<script>{HOURS_JS.replace('{counts}', counts)}</script>"
            + f"<details class='as-table'><summary>Show as a table</summary><table><thead><tr>"
              f"<th>hour</th>{head}</tr></thead><tbody>{rows}</tbody></table></details>")


HOURS_JS = r"""
(() => {
  const series = {counts};
  const view = document.currentScript.closest('.view') || document;
  const shown = new Set(series.map((_, n) => n));
  const two = h => String(h).padStart(2, '0');
  function apply() {
    view.querySelectorAll('.legend .series').forEach(b =>
      b.classList.toggle('on', shown.has(+b.dataset.s)));
    view.querySelectorAll('svg [data-s]').forEach(el =>
      el.style.display = shown.has(+el.dataset.s) ? '' : 'none');
    view.querySelectorAll('g.col[data-h]').forEach(g => {
      const h = +g.dataset.h;
      const said = series.filter((_, n) => shown.has(n))
        .map(([name, c]) => `${name} ${Math.round(c[h])}`).join(' · ');
      g.dataset.tip = `${two(h)}:00–${two(h + 1)}:00: ${said || 'no route shown'}`;
    });
  }
  view.querySelector('.legend').addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.classList.contains('series-all')) series.forEach((_, n) => shown.add(n));
    else if (b.classList.contains('series-none')) shown.clear();
    else shown.has(+b.dataset.s) ? shown.delete(+b.dataset.s) : shown.add(+b.dataset.s);
    apply();
  });
  apply();
})();
"""


def _calendar(path):
    """Each route on weekdays, Saturday and Sunday: when it runs, its departures a day and in its
    busiest hour, each way - from calendar.txt, trips.txt, stop_times.txt and frequencies.txt."""
    with zipfile.ZipFile(path) as z:
        def table(name):
            if name not in z.namelist():
                return []
            with z.open(name) as f:
                return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))
        calendar, routes, trips = table("calendar.txt"), table("routes.txt"), table("trips.txt")
        times, frequencies = table("stop_times.txt"), table("frequencies.txt")
    if not calendar:
        return "<h1>Calendar</h1><p class='note'>The feed has no calendar.txt.</p>"
    first = {}                                   # a trip's departure from its first stop
    for t in times:
        seq, dep = int(t["stop_sequence"]), _seconds(t["departure_time"])
        if t["trip_id"] not in first or seq < first[t["trip_id"]][0]:
            first[t["trip_id"]] = (seq, dep)
    repeats = {}
    for f in frequencies:
        repeats.setdefault(f["trip_id"], []).append(
            (_seconds(f["start_time"]), _seconds(f["end_time"]), int(f["headway_secs"])))
    runs_on = {c["service_id"]: {label for label, days in DAY_COLUMNS
                                 if any(c.get(d) == "1" for d in days)} for c in calendar}
    # route -> day -> direction -> departures
    service = {}
    for trip in trips:
        if trip["trip_id"] not in first:
            continue
        start = first[trip["trip_id"]][1]
        deps = ([d for a, b, h in repeats[trip["trip_id"]] for d in range(a, b, h)]
                if trip["trip_id"] in repeats else [start])
        for label in runs_on.get(trip["service_id"], ()):
            (service.setdefault(trip["route_id"], {}).setdefault(label, {})
             .setdefault(trip.get("direction_id") or "0", []).extend(deps))
    rows = []
    for n, r in enumerate(routes):
        colour = (r.get("route_color") or "").strip()
        colour = f"#{colour}" if colour else PALETTE[n % len(PALETTE)]
        name = r.get("route_short_name") or r.get("route_long_name") or r["route_id"]
        cells = []
        for label, _ in DAY_COLUMNS:
            ways = service.get(r["route_id"], {}).get(label)
            if not ways:
                cells.append("<td class='none'>no service</td>")
                continue
            all_deps = sorted(d for deps in ways.values() for d in deps)
            each_way = len(all_deps) / len(ways)
            per_hour = {}
            for d in all_deps:
                per_hour[d // 3600] = per_hour.get(d // 3600, 0) + 1 / len(ways)
            cells.append(f"<td>{_clock(all_deps[0])}–{_clock(all_deps[-1])}<div class='was'>"
                         f"{each_way:.0f} a day each way · up to {max(per_hour.values()):.0f} an "
                         f"hour</div></td>")
        rows.append(f"<tr><td>{_chip(colour)}{html.escape(name)}</td>{''.join(cells)}</tr>")
    head = "".join(f"<th>{label}</th>" for label, _ in DAY_COLUMNS)
    return (f"<h1>Calendar</h1><p class='note'>Each route on each type of day: its first and last "
            f"departure from the first stop, its departures a day and in its busiest hour, each "
            f"way. The service days run from {html.escape(_date(calendar[0]['start_date']))} to "
            f"{html.escape(_date(calendar[0]['end_date']))}.</p>"
            f"<div class='scroll'><table style='width:100%'><thead><tr><th>route</th>{head}</tr>"
            f"</thead><tbody>{''.join(rows)}</tbody></table></div>")


def _date(text):
    """"20250101" -> "2025-01-01"."""
    text = str(text)
    return f"{text[:4]}-{text[4:6]}-{text[6:]}" if len(text) == 8 else text


def _diagrams(feed):
    """Each route's directions as strips of stops, the way a line map in a vehicle shows them."""
    # Platforms grouped by `parent_station` are one place: a change of service happens there.
    stations = {}
    for p in feed.ordered:
        for stop in p["stops"]:
            station = feed.stops[stop].get("parent_station") or ""
            if station:
                stations.setdefault(station, set()).add(p["route"]["name"])
    cards, options = [], []
    for n, patterns in enumerate(feed.by_route().values()):
        route = patterns[0]["route"]
        long = route.get('route_long_name') or ''
        # Its name, then its long name - unless that already starts with it (OSM's often do).
        said = (long if long.startswith(route["name"])
                else " - ".join(filter(None, [route["name"], long])))
        options.append(f"<option value='d{n}'>{html.escape(said)}</option>")
        served = {p["direction"]: set(p["stops"]) for p in patterns}
        strips = []
        for p in patterns:
            others = [s for d, s in served.items() if d != p["direction"]]
            items = []
            for stop in p["stops"]:
                station = feed.stops[stop].get("parent_station") or ""
                change = sorted(stations.get(station, set()) - {route["name"]})
                one_way = others and all(stop not in s for s in others)
                notes = []
                if change:
                    notes.append(f"change to {html.escape(', '.join(change))}")
                if one_way:
                    notes.append("this direction only")
                items.append(f"<li class='{'interchange' if change else ''}'>"
                              f"<span class='stop'>{html.escape(feed.name(stop))}</span>"
                              + (f"<span class='notes'>{'; '.join(notes)}</span>" if notes else "")
                              + "</li>")
            strips.append(f"<div class='strip' style='--route:{route['colour']}'>"
                          f"<div class='towards'>towards {html.escape(p['towards'])}</div>"
                          f"<ol>{''.join(items)}</ol></div>")
        cards.append(f"<div class='route-card panel' data-panel='d{n}'><h3>{_chip(route['colour'])}"
                     f"{html.escape(route['name'])} <span>"
                     f"{html.escape(long)}</span></h3>"
                     f"<div class='strips'>{''.join(strips)}</div></div>")
    return (f"<h1>Line diagrams</h1><p class='note'>Every route's stops in order, in each "
            f"direction. A ringed stop is an interchange - platforms the feed groups into one "
            f"station with another route's. A stop served in one direction only cannot be the "
            f"start of the return trip.</p>"
            f"<select class='pick'><option value='*'>All {len(cards)} lines</option>"
            f"{''.join(options)}</select><div class='route-cards'>{''.join(cards)}</div>")


def _marey(feed):
    """Every trip of one direction as a line: time across, distance along the route down, between
    any two hours. Drawn in the browser from each direction's trips: the calls of a trip relative
    to its first departure, kept once for every trip that shares them, and the departures."""
    patterns = []
    for p in feed.ordered:
        groups = {}
        for calls in p["trips"]:
            t = calls[0][3]
            offsets = tuple((int(a - t), int(d - t)) for _, _, a, d in calls)
            groups.setdefault(offsets, []).append(int(t))
        patterns.append({"name": p["route"]["name"], "towards": p["towards"],
                         "colour": p["route"]["colour"],
                         "stops": [feed.name(s) for s in p["stops"]],
                         "km": [round(k, 3) for k in p["km"]],
                         "groups": [{"off": [list(o) for o in off], "starts": sorted(starts)}
                                    for off, starts in groups.items()]})
    if not patterns:
        return "<h1>Time–distance</h1><p class='note'>The feed has no trips.</p>"
    options = "".join(f"<option value='{n}'>{html.escape(p['name'])} towards "
                      f"{html.escape(p['towards'])}</option>" for n, p in enumerate(patterns))
    data = json.dumps(patterns, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return (f"<h1>Time–distance</h1><p class='note'>{ON_WEEKDAYS.strip()} Every trip of one direction as a line: time "
            f"across, stops down, spaced by distance. A steeper line is a slower vehicle, a flat "
            f"step is a dwell at a stop, and the gaps between lines are the headway. Choose the "
            f"hours to show; hover a line for its times.</p>"
            f"<div class='ttpick'><label>Route and direction <select class='md-pattern'>"
            f"{options}</select></label>{_hour_menus('md', feed)}</div>"
            f"<p class='note md-count'></p>"
            f"<div class='chart wide md-chart'></div>"
            f"<script>{MAREY_JS.replace('{data}', data)}</script>")


MAREY_JS = r"""
(() => {
  const patterns = {data};
  const view = document.currentScript.closest('.view') || document;
  const q = c => view.querySelector(c);
  const [pick, from, to, chart, count] =
    ['.md-pattern', '.md-from', '.md-to', '.md-chart', '.md-count'].map(q);
  const clock = s => `${String(Math.floor(s / 3600)).padStart(2, '0')}:${
    String(Math.floor(s % 3600 / 60)).padStart(2, '0')}`;
  const esc = t => t.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  function draw() {
    if (+to.value <= +from.value) to.value = String(+from.value + 1);
    const p = patterns[+pick.value], t0 = +from.value * 3600, t1 = +to.value * 3600;
    const width = 1000, left = 170, right = 16, top = 24, row = 26;
    const height = top + row * (p.stops.length - 1) + 30, plotW = width - left - right;
    const span = p.km[p.km.length - 1] || 1;
    const x = s => (left + plotW * (s - t0) / (t1 - t0)).toFixed(1);
    const y = km => (top + (height - top - 30) * km / span).toFixed(1);
    const parts = p.stops.map((name, i) =>
      `<line x1='${left}' x2='${width - right}' y1='${y(p.km[i])}' y2='${y(p.km[i])}' class='grid'/>` +
      `<text x='${left - 8}' y='${(+y(p.km[i]) + 4).toFixed(1)}' class='tick' text-anchor='end'>${esc(name)}</text>`);
    const every = (t1 - t0) / 3600 > 12 ? 2 : 1;
    for (let h = t0 / 3600; h <= t1 / 3600; h += every)
      parts.push(`<text x='${x(h * 3600)}' y='${height - 10}' class='tick' text-anchor='middle'>${
        String(h).padStart(2, '0')}:00</text>`);
    const lines = [];
    for (const g of p.groups)
      for (const start of g.starts) {
        if (start + g.off[g.off.length - 1][0] < t0 || start > t1) continue;
        const points = g.off.map(([a, d], i) =>
          `${x(start + a)},${y(p.km[i])} ${x(start + d)},${y(p.km[i])}`).join(' ');
        lines.push(`<polyline points='${points}' fill='none' stroke='${p.colour}' ` +
          `stroke-width='1.2' opacity='.75'><title>departs ${clock(start)}, arrives ${
          clock(start + g.off[g.off.length - 1][0])}</title></polyline>`);
      }
    count.textContent = `${lines.length} trips between ${clock(t0)} and ${clock(t1)}.`;
    // A trip running past the window's edge is cut there, not over the labels.
    chart.innerHTML = `<svg viewBox='0 0 ${width} ${height}' role='img' ` +
      `aria-label='Time-distance diagram'><defs><clipPath id='md-clip'><rect x='${left}' y='0' ` +
      `width='${plotW}' height='${height}'/></clipPath></defs>${parts.join('')}` +
      `<g clip-path='url(#md-clip)'>${lines.join('')}</g></svg>`;
  }
  [pick, from, to].forEach(s => s.addEventListener('change', draw));
  draw();
})();
"""


def _timetables(feed):
    """One place at a time: a stop, or every platform of a station together, with a board per
    route and direction leaving from it - its service in a line ("every 5 min, 05:00-21:55"),
    and every departure, hour by hour, on request.

    A place is found by route, direction and stop in the order the line calls, or by name."""
    def place(stop):
        return feed.stops[stop].get("parent_station") or stop

    boards, stops_of = {}, {}
    for p in feed.ordered:
        for i, stop in enumerate(p["stops"][:-1]):            # the last stop has no departures
            departs = sorted(calls[i][3] for calls in p["trips"])
            boards.setdefault(place(stop), []).append((p, departs))
            stops_of.setdefault(place(stop), []).append(stop)
    names = {key: " / ".join(dict.fromkeys(feed.name(s) for s in stops))
             for key, stops in stops_of.items()}

    panels = []
    for n, key in enumerate(sorted(boards, key=lambda k: names[k])):
        routes = list(dict.fromkeys(p["route"]["name"] for p, _ in boards[key]))
        station = key not in feed.stops or key not in stops_of[key]
        head = (f"<p class='note'>A station: change between {html.escape(', '.join(routes))} "
                f"here.</p>" if station and len(routes) > 1 else "")
        cards = "".join(_board(p, departs) for p, departs in boards[key])
        panels.append(f"<div class='place' data-place='{html.escape(key)}'"
                      f"{'' if n == 0 else ' hidden'}><h2 class='section'>"
                      f"{html.escape(names[key])}</h2>{head}<div class='boards'>{cards}</div>"
                      f"</div>")

    # What the menus need: each route's directions, each with its stops in calling order.
    lines = {}
    for p in feed.ordered:
        lines.setdefault(p["route"]["name"], []).append(
            {"towards": p["towards"],
             "stops": [[feed.name(s), place(s)] for s in p["stops"][:-1]]})
    found = sorted((names[k], k, ", ".join(dict.fromkeys(p["route"]["name"]
                                                         for p, _ in boards[k])))
                   for k in boards)
    options = "".join(f"<option value='{html.escape(f'{name} ({routes})')}'></option>"
                      for name, _, routes in found)
    data = json.dumps({"lines": lines,
                       "find": {f"{name} ({routes})": key for name, key, routes in found}},
                      ensure_ascii=False).replace("</", "<\\/")
    return (f"<h1>Stop timetables</h1><p class='note'>{ON_WEEKDAYS.strip()} Find a stop by its name, or by a line "
            f"calling there: its route, direction and the stop. A station's platforms are shown together, a board per "
            f"route and direction leaving from it.</p>"
            f"<div class='ttways'><div class='ttway'><div class='how'>By name</div>"
            f"<div class='ttpick'><label>Stop <input type='search' class='tt-find' "
            f"list='tt-names' placeholder='type part of its name'></label></div></div>"
            f"<datalist id='tt-names'>{options}</datalist><div class='or'>or</div>"
            f"<div class='ttway'><div class='how'>By line</div><div class='ttpick'>"
            f"<label>Route <select class='tt-route'></select></label>"
            f"<label>Direction <select class='tt-dir'></select></label>"
            f"<label>Stop <select class='tt-stop'></select></label></div></div></div>"
            f"{''.join(panels)}<script>{TIMETABLE_JS.replace('{data}', data)}</script>")


def _board(p, departs):
    """A route and direction at one stop: its service summarised, and every departure."""
    hours = {}
    for t in departs:
        hours.setdefault(int(t // 3600), []).append(int(t % 3600 // 60))
    rows = "".join(f"<tr><td class='h'>{h:02d}</td><td>{' '.join(f'{m:02d}' for m in ms)}"
                   f"</td></tr>" for h, ms in sorted(hours.items()))
    service = "".join(f"<div>{html.escape(line)}</div>" for line in _service(departs))
    return (f"<div class='board'><h3>{_chip(p['route']['colour'])}"
            f"{html.escape(p['route']['name'])} towards {html.escape(p['towards'])}</h3>"
            f"<div class='service'>{service}</div><details><summary>Every departure "
            f"({len(departs)})</summary><table>{rows}</table></details></div>")


def _service(departs):
    """Departures as runs of one headway: ["every 5 min, 05:00-21:55", ...]."""
    if not departs:
        return ["no departures"]
    if len(departs) == 1:
        return [f"one departure, at {_clock(departs[0])}"]
    runs, first = [], 0
    gaps = [b - a for a, b in zip(departs, departs[1:])]
    for i in range(1, len(gaps) + 1):
        if i == len(gaps) or gaps[i] != gaps[first]:
            runs.append((departs[first], departs[i], gaps[first]))
            first = i
    out = []
    for a, b, gap in runs:
        if a == b:
            out.append(f"at {_clock(a)}")
        else:
            out.append(f"every {gap / 60:g} min, {_clock(a)}–{_clock(b)}")
    return out


TIMETABLE_JS = r"""
(() => {
  const data = {data};
  const view = document.currentScript.closest('.view') || document;
  const q = c => view.querySelector(c);
  const [route, dir, stop, find] = ['.tt-route', '.tt-dir', '.tt-stop', '.tt-find'].map(q);
  const fill = (select, items) => select.innerHTML = items.map(([v, t]) =>
    `<option value="${String(v).replace(/&/g, '&amp;').replace(/"/g, '&quot;')}">${
      t.replace(/&/g, '&amp;').replace(/</g, '&lt;')}</option>`).join('');
  const show = key => view.querySelectorAll('.place').forEach(p =>
    p.hidden = p.dataset.place !== key);
  const pattern = () => data.lines[route.value][+dir.value];
  function pickRoute() {
    fill(dir, data.lines[route.value].map((d, i) => [i, 'towards ' + d.towards]));
    pickDir();
  }
  function pickDir() {
    fill(stop, pattern().stops.map(([name], i) => [i, `${i + 1}. ${name}`]));
    if (pattern().stops.length) show(pattern().stops[0][1]);
  }
  fill(route, Object.keys(data.lines).map(r => [r, r]));
  route.addEventListener('change', pickRoute);
  dir.addEventListener('change', pickDir);
  stop.addEventListener('change', () => show(pattern().stops[+stop.value][1]));
  find.addEventListener('change', () => {
    const key = data.find[find.value];
    if (!key) return;
    show(key);
    // The menus follow: the first route and direction calling there.
    for (const [r, dirs] of Object.entries(data.lines))
      for (const [i, d] of dirs.entries()) {
        const k = d.stops.findIndex(s => s[1] === key);
        if (k < 0) continue;
        route.value = r; pickRoute(); dir.value = i; pickDir(); stop.value = k; show(key);
        find.value = '';
        return;
      }
  });
  pickRoute();
})();
"""


# What each file of a feed holds, for the GTFS view.
GTFS_FILES = {
    "agency.txt": "who runs the services",
    "routes.txt": "the routes: names, mode, colour",
    "trips.txt": "the trips: route, service days, direction, shape",
    "stop_times.txt": "when each trip calls at each stop",
    "frequencies.txt": "trips repeated every headway between two times",
    "stops.txt": "the stops: name, position, station",
    "calendar.txt": "the days and dates each service runs",
    "calendar_dates.txt": "exceptions to the calendar",
    "shapes.txt": "the path each trip draws",
    "feed_info.txt": "about the feed itself",
}


def _files(path):
    """The feed's own files: pick one, see it as a table - filter its rows, sort a column."""
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.endswith(".txt")]
        order = list(GTFS_FILES)
        names.sort(key=lambda n: (order.index(n) if n in order else len(order), n))
        tables = {}
        for name in names:
            with z.open(name) as f:
                tables[name] = list(csv.reader(io.TextIOWrapper(f, encoding="utf-8-sig")))
    options, panels = [], []
    for n, name in enumerate(names):
        rows = tables[name]
        head, body = (rows[0], rows[1:]) if rows else ([], [])
        about = GTFS_FILES.get(name, "")
        rows_said = f"{len(body):,} row{'' if len(body) == 1 else 's'}"
        options.append(f"<option value='g{n}'>{html.escape(name)} ({rows_said})</option>")
        shown = body[:FILE_ROW_LIMIT]
        th = "".join(f"<th>{html.escape(h)}</th>" for h in head)
        tr = "".join("<tr>" + "".join(_raw_cell(c) for c in r) + "</tr>" for r in shown)
        more = (f" · the first {FILE_ROW_LIMIT:,} shown" if len(body) > FILE_ROW_LIMIT else "")
        panels.append(f"<div class='panel' data-panel='g{n}'{'' if n == 0 else ' hidden'}>"
                      f"<p class='note'><code>{html.escape(name)}</code>"
                      f"{' - ' + html.escape(about) if about else ''} · {rows_said}{more}"
                      f" · click a column to sort</p>"
                      f"<input class='filter' type='search' placeholder='Filter rows'>"
                      f"<div class='scroll'><table><thead><tr>{th}</tr></thead><tbody>{tr}"
                      f"</tbody></table></div></div>")
    return (f"<h1>GTFS</h1><p class='note'>The feed's files as they are written, one at a time. "
            f"<a href='exports/{html.escape(os.path.basename(path))}' download>Download the feed"
            f"</a> ({html.escape(os.path.basename(path))}) to open it in any GTFS tool.</p>"
            f"<select class='pick'>{''.join(options)}</select>{''.join(panels)}")


def _raw_cell(text):
    """A value as the file has it; a number is right-aligned and sorts by value."""
    try:
        value = float(text)
    except ValueError:
        return f"<td>{html.escape(text)}</td>"
    return f"<td class='n' data-v='{value}'>{html.escape(text)}</td>" if math.isfinite(value) \
        else f"<td>{html.escape(text)}</td>"
