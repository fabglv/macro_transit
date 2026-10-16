"""The Statistics views of a public-transport run's page, built from what the run exported.

    Overview        the headline numbers (summary.json)
    Journey times   how long the trips take door to door, and what the average is made of
                    (exports/skims.csv)
    Busiest rides   the stop-to-stop segments carrying the most passengers (exports/segments.csv)
    Busiest stops   where passengers get on and off from the street (exports/stops.csv)
    Coverage        how far the trips start from a stop (exports/zones.gpkg)

Only the standard library, like the rest of the page; the charts are the ones stats.py draws
for the road runs.
"""
import csv
import html
import math
import os
import sqlite3
from contextlib import closing

from .stats import Weighted, _missing, _single

# The numbers two simulations are compared on - on the Compare page (compare_page.py) and in a
# design's simulation log (transit/compare.py): (label, the totals key in summary.json, the
# SimulationResult attribute, format). Journey times are averages over the trips that reach the
# network, so when a design changes how many reach it - a new line - they describe a different
# mix of trips as much as a faster network.
COMPARISON = [("trips that can reach the network", "served", "served_demand", "{:,.0f}"),
              ("board a vehicle", "boarded", "boarded_demand", "{:,.0f}"),
              ("walk the whole way", "walk_only", "walk_only_demand", "{:,.0f}"),
              ("boardings", "boardings", "boardings", "{:,.0f}"),
              ("passenger-hours", "passenger_hours", "passenger_hours", "{:,.0f}"),
              ("average journey, min", "journey_min", "journey_time", "{:.1f}"),
              ("  riding", "riding_min", "in_vehicle_time", "{:.1f}"),
              ("  waiting", "waiting_min", "waiting_time", "{:.1f}"),
              ("  walking", "walking_min", "walking_time", "{:.1f}"),
              ("transfers per trip", "transfers", "transfers", "{:.3f}")]
# Categorical slots 1-3 of the page's palette: blue, orange, aqua.
RIDING, WAITING, WALKING = "#2a78d6", "#eb6834", "#1baf7a"
TOP_RIDES, TOP_STOPS = 20, 15


def views(run, output_dir):
    """[(key, menu label, html)] for the Statistics part of the menu."""
    exports = os.path.join(output_dir, "exports")
    return [("statistics", "Overview", _overview(run, output_dir)),
            ("journey-times", "Journey times", _journey_times(run, exports)),
            ("busiest-rides", "Busiest rides", _busiest_rides(exports)),
            ("busiest-stops", "Busiest stops", _busiest_stops(exports)),
            ("coverage", "Coverage", _coverage(exports))]


def _read(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return math.nan


def _overview(run, output_dir):
    if run is None:
        return ("<h1>Overview</h1><p class='note'>This run has no summary. Run it again to see "
                "its headline numbers here.</p>")
    cards = "".join(f"<div class='card'><div class='k'>{html.escape(k)}</div>"
                    f"<div class='v'>{html.escape(v)}</div></div>" for k, v in run["headline"])
    simulated = (run.get("simulated") or {}).get("said")
    ops = run.get("operations") or {}
    running = ""
    if ops.get("vehicles") is not None:
        day = {"weekday": "a weekday", "saturday": "Saturday", "sunday": "Sunday"}.get(
            ops.get("day"), ops.get("day", ""))
        items = [(f"vehicles needed, {m}", f"{n:,}") for m, n in sorted(ops["vehicles"].items())]
        items += [("vehicle-km", f"{ops['vehicle_km']:,.0f}"),
                  ("vehicle-hours", f"{ops['vehicle_hours']:,.0f}")]
        running = (f"<h2 class='section'>What its design takes to run, {html.escape(day)}</h2>"
                   f"<div class='cards'>" + "".join(
                       f"<div class='card'><div class='k'>{html.escape(k)}</div>"
                       f"<div class='v'>{html.escape(v)}</div></div>" for k, v in items)
                   + "</div>")
    return (f"<h1>Overview</h1>"
            + (f"<p><b>Simulated:</b> {html.escape(simulated)}.</p>" if simulated else "")
            + f"<p class='note'>Run finished {html.escape(run['finished'])}, in {run['minutes']} "
            f"minutes. Output folder: <code>{html.escape(os.path.abspath(output_dir))}</code></p>"
            f"<div class='cards'>{cards}</div>{running}")


def _journey_times(run, exports):
    rows = _read(os.path.join(exports, "skims.csv"))
    if rows is None:
        return _missing("Journey times", "its level-of-service matrix")
    # The trips that board: a pair's share of them (a simulation before 2026-10-16 has no
    # boarding_share, and its walkers are in).
    share = lambda r: _number(r["boarding_share"]) if "boarding_share" in r else 1.0  # noqa: E731
    reached = [r for r in rows if r["reachable"] == "1" and r["journey_time"] and share(r) > 0]
    if not reached:
        return "<h1>Journey times</h1><p class='note'>No trip boards a vehicle.</p>"
    dist = Weighted([_number(r["journey_time"]) / share(r) for r in reached],
                    [_number(r["trips"]) * share(r) for r in reached])
    top = max(1, math.ceil(dist.quantile(0.99)))
    left_out = sum(_number(r["trips"]) for r in rows) - dist.total
    return (f"<h1>Journey times</h1><p class='note'>Door to door, of the trips that board a "
            f"vehicle: the walk to the stop, the wait, the ride and any change, and the walk at "
            f"the other end - weighted by trips; the transfer penalty is not time, and is not in "
            f"it. {left_out:,.0f} trips that cannot reach the network or walk the whole way are "
            f"left out.</p>"
            + _composition(run) + _single(dist, top, "min", "minutes", RIDING))


def _composition(run):
    """The average journey as one bar: walking, waiting, riding."""
    totals = (run or {}).get("totals", {})
    parts = [("walking", WALKING, totals.get("walking_min")),
             ("waiting", WAITING, totals.get("waiting_min")),
             ("riding", RIDING, totals.get("riding_min"))]
    if any(v is None for _, _, v in parts):
        return ""
    total = sum(v for _, _, v in parts)
    segments = "".join(
        f"<div class='col seg-part' style='flex:{v:.3f};background:{colour}' "
        f"data-tip='{name}: {v:.1f} min ({100 * v / total:.0f}%)'></div>"
        for name, colour, v in parts)
    legend = "".join(f"<span><i style='background:{colour}'></i>{name} {v:.1f} min</span>"
                     for name, colour, v in parts)
    return (f"<h2 class='section'>The average journey, {total:.1f} min</h2>"
            f"<div class='legend'>{legend}</div>"
            f"<div class='chart hbars'><div class='hrow single'><div class='hbar'>{segments}"
            f"</div></div><div class='tip' hidden></div></div>"
            f"<h2 class='section'>Every journey</h2>")


def _busiest_rides(exports):
    rows = _read(os.path.join(exports, "segments.csv"))
    if rows is None:
        return _missing("Busiest rides", "its segment loads")
    rows.sort(key=lambda r: -_number(r["pt_volume"]))
    over = sum(1 for r in rows if _number(r["pct_capacity"]) > 100)
    body = "".join(
        f"<tr><td>{html.escape(r['route'])}</td><td>{html.escape(r['direction'])}</td>"
        f"<td>{html.escape(r['from_name'])} → {html.escape(r['to_name'])}</td>"
        f"<td class='n' data-v='{_number(r['pt_volume'])!r}'>{_number(r['pt_volume']):,.0f}</td>"
        f"<td class='n' data-v='{_number(r['pct_capacity'])!r}'>"
        f"{_number(r['pct_capacity']):,.0f}%</td></tr>"
        for r in rows[:TOP_RIDES])
    return (f"<h1>Busiest rides</h1><p class='note'>The {min(TOP_RIDES, len(rows))} stop-to-stop "
            f"segments carrying the most passengers in the modelled period, out of {len(rows)}; "
            f"{over} segment{'s' if over != 1 else ''} carry more passengers than the service "
            f"has places. The model has no crowding, so it reports that without complaint. "
            f"Click a column to sort.</p>"
            f"<div class='scroll'><table style='width:100%'><thead><tr><th>route</th>"
            f"<th>direction</th><th>ride</th><th>passengers</th><th>places used</th></tr></thead>"
            f"<tbody>{body}</tbody></table></div>")


def _busiest_stops(exports):
    rows = _read(os.path.join(exports, "stops.csv"))
    if rows is None:
        return _missing("Busiest stops", "its stop counts")
    rows.sort(key=lambda r: -(_number(r["boardings"]) + _number(r["alightings"])))
    body = "".join(
        f"<tr><td>{html.escape(r['name'])}</td><td>{html.escape(r['route'])}</td>"
        f"<td class='n' data-v='{_number(r['boardings'])!r}'>{_number(r['boardings']):,.0f}</td>"
        f"<td class='n' data-v='{_number(r['alightings'])!r}'>"
        f"{_number(r['alightings']):,.0f}</td></tr>"
        for r in rows[:TOP_STOPS])
    return (f"<h1>Busiest stops</h1><p class='note'>The {min(TOP_STOPS, len(rows))} stops where "
            f"most passengers get on or off from the street, out of {len(rows)}. A passenger "
            f"changing service is not counted here: that boarding happens on a transfer. Click a "
            f"column to sort.</p>"
            f"<div class='scroll'><table style='width:100%'><thead><tr><th>stop</th>"
            f"<th>route</th><th>boardings</th><th>alightings</th></tr></thead><tbody>{body}"
            f"</tbody></table></div>")


def _coverage(exports):
    path = os.path.join(exports, "zones.gpkg")
    if not os.path.exists(path):
        return _missing("Coverage", "its zones")
    with closing(sqlite3.connect(path)) as db:
        zones = db.execute("SELECT served, nearest_stop_km, trips_produced FROM zones").fetchall()
    served = [z for z in zones if z[0]]
    trips = sum(z[2] or 0 for z in zones)
    served_trips = sum(z[2] or 0 for z in served)
    known = [z for z in zones if z[1] is not None and (z[2] or 0) > 0]
    dist = Weighted([z[1] for z in known], [z[2] for z in known])
    step = 0.1                                   # km: 100 m bins
    top = max(1, math.ceil(dist.quantile(0.99) / step))
    return (f"<h1>Coverage</h1><p class='note'>Whether a zone's trips can reach a stop at all, "
            f"and how far they start from the nearest one. A zone is served when a stop is "
            f"within walking reach of its centroid.</p>"
            f"<div class='figs'><div><span>zones served</span><b>{len(served)} of {len(zones)}"
            f"</b></div><div><span>trips starting in a served zone</span>"
            f"<b>{100 * served_trips / trips:.0f}%</b></div></div>"
            f"<h2 class='section'>Distance from a trip's start to the nearest stop</h2>"
            + _single(dist, top, "km", "km", WALKING, step))
