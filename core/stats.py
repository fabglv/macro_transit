"""The Statistics views of the results page, built from what the run exported.

    Overview            the headline numbers (summary.json)
    Travel times        free flow, simulation, or both compared (od_matrix.csv.gz)
    Trip distances      the length of the trips' routes (od_matrix.csv.gz)
    Network load        each road class's km by how close to capacity it runs (link_volumes.gpkg)
    Congested streets   the named streets with the most km over capacity (link_volumes.gpkg)

Only the standard library: a GeoPackage is an SQLite file, and the matrix a gzipped CSV. Trips
are counted only when both ends are in the city - a trip from outside spends most of its time
on the way to the edge, which says nothing about the city's streets.
"""
import csv
import gzip
import html
import json
import math
import os
import re
import sqlite3
from contextlib import closing

from . import summary
from .network_classes import CONGESTION_BANDS, ROAD_CLASS_ORDER

FREE, SIMULATED = "#2a78d6", "#eb6834"         # categorical slots 1 and 2: blue, orange
TOP_STREETS = 20


# A run's statistics, kept beside its results: computed again only when what they are drawn from
# - its exports, summary and scenario, or this module - has changed. Reading the matrix and
# weighing its trips takes tens of seconds, and every run's page is rebuilt whenever one of its
# kind is run or deleted.
CACHE = "stats_cache.json"
SOURCES = [os.path.join("exports", "od_matrix.csv.gz"), os.path.join("exports", "link_volumes.gpkg"),
           os.path.join("exports", "zones.gpkg"), "summary.json", "scenario.json"]


def _stamp(output_dir):
    """What the statistics are drawn from, as it is: each source's size and time, and this code's."""
    paths = [os.path.join(output_dir, p) for p in SOURCES] + [os.path.abspath(__file__)]
    return [[os.path.getsize(p), os.path.getmtime(p)] if os.path.exists(p) else None
            for p in paths]


def views(run, output_dir):
    """[(key, menu label, html)] for the Statistics part of the menu."""
    path, stamp = os.path.join(output_dir, CACHE), _stamp(output_dir)
    try:
        with open(path, encoding="utf-8") as f:
            kept = json.load(f)
        if kept["stamp"] == stamp:
            return [tuple(v) for v in kept["views"]]
    except (OSError, ValueError, KeyError):
        pass
    od = _read_od(output_dir)
    links = _read_links(output_dir)
    out = [("statistics", "Overview", _overview(run, output_dir, od)),
           ("travel-times", "Travel times", _travel_times(od)),
           ("distances", "Trip distances", _distances(od)),
           ("network-load", "Network load", _network_load(links)),
           ("congested-streets", "Congested streets", _congested_streets(links))]
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"stamp": stamp, "views": out}, f)
    except OSError:
        pass                                    # not kept: computed again next time
    return out


# --- reading the exports -----------------------------------------------------------------------
def _read_od(output_dir):
    """The trips with both ends in the city, as columns of floats; None without a matrix.

    `minutes` is always there; `congested_minutes` and `km` only in runs that wrote them."""
    path = os.path.join(output_dir, "exports", "od_matrix.csv.gz")
    if not os.path.exists(path):
        return None
    internal = _internal_zones(output_dir)
    od = {"external": 0.0, "groups": {key: 0.0 for key, _, _, _ in summary.TRIP_GROUPS}}
    group_of = {(o, d): key for key, _, o, d in summary.TRIP_GROUPS}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        columns = [c for c in ("trips", "minutes", "congested_minutes", "km")
                   if c in reader.fieldnames]
        for c in columns:
            od[c] = []
        for row in reader:
            key = group_of[(internal is None or row["origin"] in internal,
                            internal is None or row["destination"] in internal)]
            od["groups"][key] += float(row["trips"])
            if key != "within":
                od["external"] += float(row["trips"])
                continue
            for c in columns:
                od[c].append(float(row[c]))
    od["total"] = sum(od["trips"])
    return od if od["total"] else None


def _internal_zones(output_dir):
    """The zone numbers in zones.gpkg - the city's own zones, not the external ones."""
    path = os.path.join(output_dir, "exports", "zones.gpkg")
    if not os.path.exists(path):
        return None
    with closing(sqlite3.connect(path)) as db:
        return {str(z) for (z,) in db.execute("SELECT zone_number FROM zones")}


def _read_links(output_dir):
    """The loaded streets: name, road class, metres, V/C and the busier direction's flow."""
    path = os.path.join(output_dir, "exports", "link_volumes.gpkg")
    if not os.path.exists(path):
        return None
    with closing(sqlite3.connect(path)) as db:
        rows = db.execute("SELECT name, link_type, distance, voc, "
                          "MAX(COALESCE(car_ab, 0), COALESCE(car_ba, 0)) FROM link_volumes")
        return [{"name": (n or "").strip(), "class": (t or "").replace("_link", ""),
                 "m": d or 0.0, "voc": v or 0.0, "flow": q or 0.0}
                for n, t, d, v, q in rows]


# --- weighted figures ----------------------------------------------------------------------------
class Weighted:
    """A distribution of values, each weighted by its trips. A value that is not finite - a
    trip a scenario's closures leave with no route, never assigned - is left out."""

    def __init__(self, values, weights):
        self.pairs = sorted((v, w) for v, w in zip(values, weights) if math.isfinite(v))
        self.total = sum(w for _, w in self.pairs)
        self.mean = sum(v * w for v, w in self.pairs) / self.total if self.total else 0.0

    def quantile(self, q):
        running = 0.0
        for value, weight in self.pairs:
            running += weight
            if running >= q * self.total:
                return value
        return self.pairs[-1][0]

    def bins(self, top, step=1):
        """Trips per bin `step` wide, `top` bins from 0; one more holds everything beyond."""
        counts = [0.0] * (top + 1)
        for value, weight in self.pairs:
            # The small nudge keeps 0.3 / 0.1 (2.9999...) in the bin it belongs to.
            counts[min(int(value / step + 1e-9), top)] += weight
        return counts


def _missing(title, what):
    return (f"<h1>{title}</h1><p class='note'>This run did not export {what}. Run the city "
            f"again to see it here.</p>")


# --- the views -----------------------------------------------------------------------------------
def _overview(run, output_dir, od=None):
    if run is None:
        return ("<h1>Overview</h1><p class='note'>This run was made before runs saved their "
                "statistics. Run the city again to see them here.</p>")
    values = summary.headline(run)
    cards = "".join(f"<div class='card'><div class='k'>{html.escape(k)}</div>"
                    f"<div class='v'>{html.escape(values[k])}</div></div>"
                    for k in summary.HEADLINE if k in values)
    return (f"<h1>Overview</h1>"
            f"<p class='note'>Run finished {html.escape(run['finished'])}, in {run['minutes']} "
            f"minutes. Output folder: <code>{html.escape(os.path.abspath(output_dir))}</code></p>"
            + _scenario(output_dir)
            + f"<div class='cards'>{cards}</div>" + _trip_groups(run, od))


def _number(text):
    """The first number in a headline value - "9,065" -> 9065.0, "0.27 min" -> 0.27."""
    found = re.search(r"-?[\d,]*\.?\d+", text or "")
    return float(found.group().replace(",", "")) if found else None


def _scenario(output_dir):
    """A scenario's block (maps.SCENARIO_FILE, written with its change map): its base, its edits,
    its headline numbers beside the base's, and the streets that changed most - in volumes for a
    closure, which moves traffic; in V/C for a capacity or speed change, which makes roads more
    or less congested, with its edited roads before and after. Nothing for any other run."""
    path = os.path.join(output_dir, "scenario.json")
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as f:
        s = json.load(f)
    closure = s.get("type", "closure") == "closure"
    newroad = s.get("type") == "newroad"
    demand = s.get("type") == "demand"
    base = f"../{html.escape(s['base_folder'])}/index.html"
    label = html.escape(s["base_label"])

    def streets_of(e):
        return (html.escape(", ".join(e["streets"][:4]) or "unnamed roads")
                + (f" and {len(e['streets']) - 4} more" if len(e["streets"]) > 4 else ""))

    def change(a, b):
        if a == b:
            return "<span class='muted'>&ndash;</span>"
        x, y = _number(a), _number(b)
        if x is None or y is None:
            return ""
        if not x:
            return f"{y - x:+,.2f}"
        cls = "up" if y > x else "down" if y < x else ""
        return f"<span class='{cls}'>{100 * (y - x) / x:+.1f}%</span>"

    def table(head, body):
        return (f"<table class='scen'><thead><tr>{''.join(f'<th>{h}</th>' for h in head)}"
                f"</tr></thead><tbody>{body}</tbody></table>")

    headline = table(["", label, "this scenario", "change"], "".join(
        f"<tr><td>{html.escape(k)}</td><td class='n'>{html.escape(a or '')}</td>"
        f"<td class='n'>{html.escape(b)}</td><td class='n'>{change(a, b)}</td></tr>"
        for k, a, b in s["headline"]))

    def pct(p):
        return "" if p is None else f"{p:+}%"
    if demand:
        modelled = dict((k, b) for k, _, b in s["headline"]).get("modelled", "")
        about = ("changes the demand: the trips the base's network carries. Its trips are added "
                 "to the <b>final matrix</b> - the one assigned, for the period modelled"
                 + (f" ({html.escape(modelled)})" if modelled else "")
                 + " - after the day and time of day are worked out, and are not converted again. "
                 "Its map <b>Change from its base</b> shows the change in volume - more vehicles in "
                 "orange, fewer in blue - and the zones it edits.")
        edits = table(["edit", "trips added"], "".join(
            f"<tr><td>{html.escape(e['said'])}</td><td class='n'><b>{e['added'] or 0:+,.0f}</b></td></tr>"
            for e in s["edits"]))
        names = {key: label for key, label, _, _ in summary.TRIP_GROUPS}
        groups = s.get("groups") or {}
        if groups:
            edits += table(["trips", html.escape(s["base_label"]), "this scenario", "change"], "".join(
                f"<tr><td>{html.escape(names.get(k, k))}</td><td class='n'>{(a or 0):,.0f}</td>"
                f"<td class='n'>{(b or 0):,.0f}</td><td class='n'>{(b or 0) - (a or 0):+,.0f}</td></tr>"
                for k, (a, b) in groups.items()))

        def streets(part, title):
            body = "".join(f"<tr><td>{html.escape(n)}</td><td class='n'>{vb:,}</td>"
                           f"<td class='n'>{c:+,}</td><td class='n'>{pct(p)}</td></tr>"
                           for n, vb, c, p in part)
            return (f"<div><h3>{title}</h3>"
                    + table(["street", "vehicle-km in the base", "change", ""], body) + "</div>"
                    if part else "")
        lists = (streets(s["more"], "Streets gaining the most volume")
                 + streets(s["less"], "Streets losing the most volume"))
    elif newroad:
        about = ("builds new roads. Its trips are the base's: a new road gives them another way, "
                 "so the map <b>Change from its base</b> shows the change in volume - more "
                 "vehicles in orange, fewer in blue - and the new roads in teal, each with the "
                 "vehicles it carries.")
        edits = table(["new road", "what it is", "length", "vehicles an hour", "V/C"], "".join(
            f"<tr><td><b>{html.escape(e['label'] or 'new road')}</b></td>"
            f"<td>{html.escape(e['said'])}</td><td class='n'>{e['km']:.2f} km</td>"
            f"<td class='n'><b>{e['flow'][1]:,}</b></td><td class='n'>{e['voc'][1]:.2f}</td></tr>"
            for e in s["edits"]))

        def streets(part, title):
            body = "".join(f"<tr><td>{html.escape(n)}</td><td class='n'>{vb:,}</td>"
                           f"<td class='n'>{c:+,}</td><td class='n'>{pct(p)}</td></tr>"
                           for n, vb, c, p in part)
            return (f"<div><h3>{title}</h3>"
                    + table(["street", "vehicle-km in the base", "change", ""], body) + "</div>"
                    if part else "")
        lists = (streets(s["less"], "Streets the new roads relieve most")
                 + streets(s["more"], "Streets gaining the most volume"))
    elif closure:
        about = ("closes roads. Its trips are the base's, so what a closure does is move them: "
                 "the map <b>Change from its base</b> shows the change in volume - more "
                 "vehicles in orange, fewer in blue - and the closed roads in black, each with "
                 "what it carried.")
        lost = s.get("unrouted") or {}
        if lost.get("trips"):
            zones = lost.get("zones") or []
            about += (f"</p><p class='warn'>The closures leave {lost['trips']:,.0f} trips with no "
                      f"route at all: they are not assigned, so they are missing from its "
                      f"numbers and maps"
                      + (f" - zone{'s' if len(zones) > 1 else ''} "
                         f"{', '.join(map(str, zones[:12]))} cut off" if zones else "") + ".")
        edits = "<ul class='edits'>" + "".join(
            f"<li><b>{html.escape(e['said'])}</b>: {streets_of(e)} <span class='muted'>"
            f"({e['links']} links, {e['km']:.1f} km; {e['flow'][0]:,} vehicles on an average "
            f"link before)</span></li>" for e in s["edits"]) + "</ul>"

        def streets(part, title):
            body = "".join(f"<tr><td>{html.escape(n)}</td><td class='n'>{vb:,}</td>"
                           f"<td class='n'>{c:+,}</td><td class='n'>{pct(p)}</td></tr>"
                           for n, vb, c, p in part)
            return (f"<div><h3>{title}</h3>"
                    + table(["street", "vehicle-km in the base", "change", ""], body) + "</div>"
                    if part else "")
        lists = (streets(s["more"], "Streets gaining the most volume")
                 + streets(s["less"], "Streets losing the most volume"))
    else:
        about = ("changes the capacity or the speed of roads. Its effect is how congested the "
                 "roads get, not how much they carry - a widened road usually draws more traffic, "
                 "with less congestion - so the map <b>Change from its base</b> shows the change "
                 "in V/C: green where it eased, red where it worsened, the edited roads haloed. "
                 "City-wide the numbers move little, as drivers fill the room made; the effect "
                 "is on the edited roads and around them.")
        edits = table(["edit", "roads", "length", "vehicles on a link", "worst V/C"], "".join(
            f"<tr><td><b>{html.escape(e['said'])}</b></td><td>{streets_of(e)}</td>"
            f"<td class='n'>{e['links']} links, {e['km']:.1f} km</td>"
            f"<td class='n'>{e['flow'][0]:,} &rarr; {e['flow'][1]:,}</td>"
            f"<td class='n'>{e['voc'][0]:.2f} &rarr; <b>{e['voc'][1]:.2f}</b></td></tr>"
            for e in s["edits"]))

        def streets(part, title):
            body = "".join(f"<tr><td>{html.escape(n)}</td><td class='n'>{a:.2f}</td>"
                           f"<td class='n'>{b:.2f}</td><td class='n'>{d:+.2f}</td>"
                           f"<td class='n'>{pct(p)}</td></tr>" for n, a, b, d, p in part)
            return (f"<div><h3>{title}</h3>"
                    + table(["street", "V/C before", "after", "change", "volume"], body)
                    + "</div>" if part else "")
        lists = (streets(s["less"], "Streets less congested")
                 + streets(s["more"], "Streets more congested"))
    return (f"<h2 class='scen-title'>This scenario</h2>"
            f"<p class='note'>A scenario of <a href='{base}'>{label}</a> that {about}</p>"
            f"{edits}{headline}<div class='scen-streets'>{lists}</div>"
            f"<h2 class='scen-title'>Its numbers</h2>")


def _trip_groups(run, od):
    """Where the trips go against the city limit, and what each figure on the page counts: from
    the run's summary, exact, or for a run older than that from the exported matrix, whose cells
    are rounded."""
    groups = run.get("trip_groups") or (od["groups"] if od else None)
    if not groups:
        return ""
    total = sum(groups.values()) or 1.0
    if total == groups["within"]:
        return ("<h2>Where the trips go</h2><p class='note'>This city's model has no external "
                "zones: every trip has both ends in the city, and traffic from beyond its limit "
                "is not modelled. Every figure on these pages counts the same trips.</p>")
    rows = "".join(f"<tr><td>{label}</td><td class='n'>{groups[key]:,.0f}</td>"
                   f"<td class='n'>{100 * groups[key] / total:.1f}%</td></tr>"
                   for key, label, _, _ in summary.TRIP_GROUPS)
    return (f"<h2>Where the trips go</h2><p class='note'>Against the city limit: the city's own "
            f"zones, and the external zones standing for the roads that cross the limit.</p>"
            f"<table class='compare'><thead><tr><th></th><th>trips</th><th>share</th></tr>"
            f"</thead><tbody>{rows}<tr><td><b>all</b></td><td class='n'><b>{total:,.0f}</b>"
            f"</td><td class='n'></td></tr></tbody></table>"
            f"<p class='note'>The headline numbers and the network's load count every trip on "
            f"the streets, from outside too. Travel times and trip distances count the trips "
            f"within the city: a trip from outside spends most of its time on the way to the "
            f"limit, which says nothing about the city's streets.</p>")


def _scope(od):
    return ("Trips with both ends in the city, weighted by trips"
            + (f"; the {od['external']:,.0f} trips with an end outside are left out."
               if od["external"] else "."))


def _travel_times(od):
    if od is None:
        return _missing("Travel times", "a trip matrix")
    free = Weighted(od["minutes"], od["trips"])
    if "congested_minutes" not in od:
        top = max(1, math.ceil(free.quantile(0.99)))
        return (f"<h1>Travel times</h1><p class='note'>On empty streets (the free-flow skim the "
                f"gravity model distributes the trips by). {_scope(od)} This run has no "
                f"simulated times: run the city again to compare them.</p>"
                + _single(free, top, "min", "minutes", FREE))
    sim = Weighted(od["congested_minutes"], od["trips"])
    top = max(1, math.ceil(max(free.quantile(0.99), sim.quantile(0.99))))   # one scale for all
    change = sim.mean - free.mean
    rows = "".join(
        f"<tr><td>{label}</td><td class='n'>{f(free):.1f} min</td><td class='n'>{f(sim):.1f} min"
        f"</td><td class='n'>{f(sim) - f(free):+.1f} min</td></tr>"
        for label, f in (("mean", lambda w: w.mean), ("median", lambda w: w.quantile(0.5)),
                         ("90% of trips under", lambda w: w.quantile(0.9))))
    comparison = (
        f"<p class='lead'>On the loaded network the average trip takes <b>{change:+.1f} min</b> "
        f"({100 * change / free.mean:+.0f}%) more than on empty streets.</p>"
        f"<table class='compare'><thead><tr><th></th><th><i style='background:{FREE}'></i>free "
        f"flow</th><th><i style='background:{SIMULATED}'></i>simulation</th><th>change</th></tr>"
        f"</thead><tbody>{rows}</tbody></table>"
        + _lines([("free flow", FREE, free.bins(top)), ("simulation", SIMULATED, sim.bins(top))],
                 _labels(top, "min"), free.total, "minutes"))
    return (f"<h1>Travel times</h1><p class='note'>Free flow: on empty streets, the skim the "
            f"gravity model distributes the trips by. Simulation: on the loaded network, each "
            f"trip's quickest route at the congested times the assignment ends with. "
            f"{_scope(od)}</p>"
            f"<div class='seg' role='tablist'>"
            f"<button data-panel='free'>Free flow</button>"
            f"<button data-panel='simulation'>Simulation</button>"
            f"<button data-panel='comparison' class='on'>Comparison</button></div>"
            f"<div class='panel' data-panel='free' hidden>{_single(free, top, 'min', 'minutes', FREE)}</div>"
            f"<div class='panel' data-panel='simulation' hidden>"
            f"{_single(sim, top, 'min', 'minutes', SIMULATED)}</div>"
            f"<div class='panel' data-panel='comparison'>{comparison}</div>")


def _distances(od):
    if od is None or "km" not in od:
        return _missing("Trip distances", "the length of each trip's route")
    km = Weighted(od["km"], od["trips"])
    top = max(1, math.ceil(km.quantile(0.99)))
    return (f"<h1>Trip distances</h1><p class='note'>The length of each trip's route on empty "
            f"streets; a trip that stays in its zone counts as 0 km. {_scope(od)}</p>"
            + _single(km, top, "km", "km", FREE))


def _network_load(links):
    if links is None:
        return _missing("Network load", "its loaded streets")
    classes = [c for c in ROAD_CLASS_ORDER if any(l["class"] == c for l in links)]
    if any(l["class"] not in ROAD_CLASS_ORDER for l in links):
        classes.append("other")
    km = {c: [0.0] * len(CONGESTION_BANDS) for c in classes}
    for link in links:
        c = link["class"] if link["class"] in ROAD_CLASS_ORDER else "other"
        km[c][_band(link["voc"])] += link["m"] / 1000
    legend = "".join(f"<span><i style='background:{colour}'></i>{html.escape(label)}</span>"
                     for _, _, colour, label in CONGESTION_BANDS)
    bars, rows = [], []
    for c in classes:
        total = sum(km[c])
        over = sum(k for k, (lo, _, _, _) in zip(km[c], CONGESTION_BANDS) if lo >= 1.0)
        segments = "".join(
            f"<div class='col seg-part' style='flex:{k:.3f};background:{colour}' "
            f"data-tip='{html.escape(f'{c}, {label}: {k:,.1f} km ({100 * k / total:.0f}%)')}'>"
            f"</div>"
            for k, (_, _, colour, label) in zip(km[c], CONGESTION_BANDS) if k > 0)
        bars.append(f"<div class='hrow'><div class='hname'>{c.capitalize()}</div>"
                    f"<div class='hbar'>{segments}</div>"
                    f"<div class='hval'>{total:,.0f} km<span>{over:,.1f} km over capacity"
                    f"</span></div></div>")
        rows.append(f"<tr><td>{c}</td>" + "".join(f"<td class='n'>{k:,.1f}</td>" for k in km[c])
                    + f"<td class='n'>{total:,.1f}</td></tr>")
    head = "".join(f"<th>{html.escape(label.split(' - ')[0])}</th>"
                   for _, _, _, label in CONGESTION_BANDS)
    return (f"<h1>Network load</h1><p class='note'>Each road class's loaded streets, by how close "
            f"to capacity their busier direction runs in the peak hour - the bands and colours of "
            f"the simulation map. Bars are shares of the class's km; the length is on the right."
            f"</p><div class='legend'>{legend}</div>"
            f"<div class='chart hbars'>{''.join(bars)}<div class='tip' hidden></div></div>"
            f"<details class='as-table'><summary>Show as a table (km)</summary><table><thead>"
            f"<tr><th>class</th>{head}<th>all</th></tr></thead><tbody>{''.join(rows)}</tbody>"
            f"</table></details>")


def _congested_streets(links):
    if links is None:
        return _missing("Congested streets", "its loaded streets")
    streets, unnamed = {}, 0.0
    for link in links:
        if link["voc"] < 1.0:
            continue
        if not link["name"]:
            unnamed += link["m"]
            continue
        s = streets.setdefault(link["name"], {"m": 0.0, "voc": 0.0, "flow": 0.0, "classes": {}})
        s["m"] += link["m"]
        s["voc"] = max(s["voc"], link["voc"])
        s["flow"] = max(s["flow"], link["flow"])
        s["classes"][link["class"]] = s["classes"].get(link["class"], 0.0) + link["m"]
    if not streets:
        return "<h1>Congested streets</h1><p class='note'>No named street is over capacity.</p>"
    worst = sorted(streets.items(), key=lambda kv: -kv[1]["m"])[:TOP_STREETS]
    over_km = (sum(s["m"] for s in streets.values()) + unnamed) / 1000
    rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{max(s['classes'], key=s['classes'].get)}</td>"
        f"<td class='n' data-v='{s['m'] / 1000!r}'>{s['m'] / 1000:,.2f}</td>"
        f"<td class='n' data-v='{s['voc']!r}'>{100 * s['voc']:,.0f}%</td>"
        f"<td class='n' data-v='{s['flow']!r}'>{s['flow']:,.0f}</td></tr>"
        for name, s in worst)
    return (f"<h1>Congested streets</h1><p class='note'>The {len(worst)} named streets with the "
            f"most length over capacity in the peak hour, out of {len(streets):,} with any; "
            f"{over_km:,.1f} km are over capacity in all, {unnamed / 1000:,.1f} km of them on "
            f"unnamed streets. Click a column to sort.</p>"
            f"<div class='scroll'><table style='width:100%'><thead><tr><th>street</th><th>class</th>"
            f"<th>km over capacity</th><th>worst V/C</th><th>busiest flow, veh/h</th></tr>"
            f"</thead><tbody>{rows}</tbody></table></div>")


def _band(voc):
    for i, (lo, hi, _, _) in enumerate(CONGESTION_BANDS):
        if lo <= voc < hi:
            return i
    return len(CONGESTION_BANDS) - 1


# --- charts --------------------------------------------------------------------------------------
def _labels(top, unit, step=1):
    return ([f"{b * step:g}–{(b + 1) * step:g} {unit}" for b in range(top)]
            + [f"{top * step:g} {unit} or more"])


def _figures(dist, unit):
    return (f"<div class='figs'>"
            f"<div><span>mean</span><b>{dist.mean:.1f} {unit}</b></div>"
            f"<div><span>median</span><b>{dist.quantile(0.5):.1f} {unit}</b></div>"
            f"<div><span>90% of trips under</span><b>{dist.quantile(0.9):.1f} {unit}</b></div>"
            f"<div><span>trips</span><b>{dist.total:,.0f}</b></div></div>")


def _single(dist, top, unit, axis, colour, step=1):
    counts, labels = dist.bins(top, step), _labels(top, unit, step)
    rows = "".join(f"<tr><td>{html.escape(lab)}</td><td class='n'>{c:,.0f}</td>"
                   f"<td class='n'>{100 * c / dist.total:.1f}%</td></tr>"
                   for lab, c in zip(labels, counts))
    return (_figures(dist, unit) + _bars(counts, labels, dist.total, axis, colour, step)
            + f"<details class='as-table'><summary>Show as a table</summary><table><thead><tr>"
              f"<th>{axis}</th><th>trips</th><th>share</th></tr></thead><tbody>{rows}</tbody>"
              f"</table></details>")


class _Frame:
    """The plot area and its axes, shared by the bar and line charts."""

    def __init__(self, n, peak, axis, step=1, width=760, height=260):
        self.n, self.width, self.height, self.axis, self.step_x = n, width, height, axis, step
        self.left, self.right, self.top, self.bottom = 56, 8, 10, 34
        self.plot_w = width - self.left - self.right
        self.plot_h = height - self.top - self.bottom
        self.step = _nice_step(peak / 4)
        self.y_max = self.step * math.ceil(peak / self.step) or 1
        self.slot = self.plot_w / n
        self.base = self.top + self.plot_h

    def y(self, value):
        return self.base - self.plot_h * value / self.y_max

    def x(self, i):
        return self.left + (i + 0.5) * self.slot

    def axes(self):
        parts = []
        for i in range(int(self.y_max / self.step) + 1):
            value = i * self.step
            y = self.y(value)
            parts.append(f"<line x1='{self.left}' x2='{self.width - self.right}' y1='{y:.1f}' "
                         f"y2='{y:.1f}' class='grid'/><text x='{self.left - 6}' y='{y + 4:.1f}' "
                         f"class='tick' text-anchor='end'>{value:,.0f}</text>")
        every = max(1, round(self.n / 12 / 5) * 5) if self.n > 12 else 1
        last = self.n - 1
        for i in range(self.n):
            # A regular tick too close to the last bin's own label would run into it.
            if i == last or (i % every == 0 and last - i >= max(2, every / 2)):
                parts.append(f"<text x='{self.x(i):.1f}' y='{self.height - self.bottom + 16}' "
                             f"class='tick' text-anchor='middle'>{i * self.step_x:g}{'+' if i == last else ''}"
                             f"</text>")
        parts.append(f"<line x1='{self.left}' x2='{self.width - self.right}' y1='{self.base}' "
                     f"y2='{self.base}' class='axis'/><text x='{self.left + self.plot_w / 2:.1f}' "
                     f"y='{self.height - 2}' class='tick' text-anchor='middle'>{self.axis}</text>")
        return "".join(parts)

    def hit(self, i, tip):
        """The hover target: the whole column slot, taller and wider than any mark in it."""
        return (f"<rect x='{self.left + i * self.slot:.1f}' y='{self.top}' "
                f"width='{self.slot:.1f}' height='{self.plot_h}' class='hit'/>")

    def svg(self, body, label):
        return (f"<div class='chart'><svg viewBox='0 0 {self.width} {self.height}' role='img' "
                f"aria-label='{html.escape(label)}'>{self.axes()}{body}</svg>"
                f"<div class='tip' hidden></div></div>")


def _bars(counts, labels, total, axis, colour, step=1):
    """Columns on one baseline, a 2 px surface gap between them, 4 px rounded tops."""
    f = _Frame(len(counts), max(counts), axis, step)
    bar = min(24.0, f.slot - 2)
    parts = []
    for i, (count, label) in enumerate(zip(counts, labels)):
        x = f.left + i * f.slot + (f.slot - bar) / 2
        h = f.base - f.y(count)
        y, r = f.base - h, min(4.0, bar / 2, h)
        shape = (f"<path d='M{x:.1f},{f.base:.1f} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
                 f"H{x + bar - r:.1f} Q{x + bar:.1f},{y:.1f} {x + bar:.1f},{y + r:.1f} "
                 f"V{f.base:.1f} Z' class='bar' fill='{colour}'/>") if h > 0 else ""
        tip = html.escape(f"{label}: {count:,.0f} trips ({100 * count / total:.1f}%)")
        parts.append(f"<g class='col' data-tip='{tip}'>{f.hit(i, tip)}{shape}</g>")
    return f.svg("".join(parts), f"Histogram of trips by {axis}")


def _lines(series, labels, total, axis):
    """Two or more distributions on one scale: a 2 px line each, a legend above, and a hover
    note per bin listing every series."""
    n = len(labels)
    f = _Frame(n, max(max(counts) for _, _, counts in series), axis)
    parts = []
    for name, colour, counts in series:
        points = " ".join(f"{f.x(i):.1f},{f.y(c):.1f}" for i, c in enumerate(counts))
        parts.append(f"<polyline points='{points}' fill='none' stroke='{colour}' stroke-width='2' "
                     f"stroke-linejoin='round' stroke-linecap='round'/>")
    for i, label in enumerate(labels):
        tip = html.escape(f"{label}: " + " · ".join(
            f"{name} {counts[i]:,.0f} ({100 * counts[i] / total:.1f}%)"
            for name, _, counts in series))
        dots = "".join(f"<circle cx='{f.x(i):.1f}' cy='{f.y(counts[i]):.1f}' r='4' "
                       f"fill='{colour}' class='dot'/>" for _, colour, counts in series)
        parts.append(f"<g class='col' data-tip='{tip}'>{f.hit(i, tip)}{dots}</g>")
    legend = "".join(f"<span><i class='line' style='background:{colour}'></i>{html.escape(name)}"
                     f"</span>" for name, colour, _ in series)
    rows = "".join(f"<tr><td>{html.escape(label)}</td>"
                   + "".join(f"<td class='n'>{counts[i]:,.0f}</td>" for _, _, counts in series)
                   + "</tr>" for i, label in enumerate(labels))
    head = "".join(f"<th>{html.escape(name)}</th>" for name, _, _ in series)
    return (f"<div class='legend'>{legend}</div>"
            + f.svg("".join(parts), f"Trips by {axis}, " + " and ".join(s[0] for s in series))
            + f"<details class='as-table'><summary>Show as a table</summary><table><thead><tr>"
              f"<th>{axis}</th>{head}</tr></thead><tbody>{rows}</tbody></table></details>")


def _nice_step(raw):
    """1, 2 or 5 times a power of ten: grid lines at clean counts."""
    if raw <= 0:
        return 1
    power = 10 ** math.floor(math.log10(raw))
    return next(m * power for m in (1, 2, 5, 10) if m * power >= raw)
