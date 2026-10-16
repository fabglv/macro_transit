"""The views of a network design's page, built from what transit/design.py wrote.

    Overview   its lines, stops and vehicles an hour by mode (summary.json)
    Operations what each line takes to run: its round trip, the vehicles it needs, its
               vehicle-km and vehicle-hours on each type of day (exports/operations.csv)
    Lines      every route and direction: stops, headway, vehicles an hour, speed, length along
               the streets, time end to end (exports/lines.geojson)

Only the standard library, like the rest of the results pages.
"""
import csv
import html
import json
import os


def views(run, output_dir):
    """[(key, menu label, html)] for the design page's Statistics part of the menu."""
    return [("statistics", "Overview", _overview(run, output_dir)),
            ("operations", "Operations", _operations(run, output_dir)),
            ("lines", "Lines", _lines(output_dir))]


def _overview(run, output_dir):
    if run is None:
        return "<h1>Overview</h1><p class='note'>This design has no summary: build it again.</p>"
    cards = "".join(f"<div class='card'><div class='k'>{html.escape(k)}</div>"
                    f"<div class='v'>{html.escape(v)}</div></div>" for k, v in run["headline"])
    return f"<h1>Overview</h1><div class='cards'>{cards}</div>"


def _operations(run, output_dir):
    path = os.path.join(output_dir, "exports", "operations.csv")
    if not os.path.exists(path):
        return ("<h1>Operations</h1><p class='note'>This design has no operations.csv: build it "
                "again.</p>")
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    num = lambda v: float(v) if v not in ("", None) else None
    days = [("weekday", "weekdays"), ("saturday", "Saturday"), ("sunday", "Sunday")]

    def cell(v, digits=0):
        return (f"<td class='n' data-v='{v}'>{v:,.{digits}f}</td>" if v is not None
                else "<td class='n none' data-v='0'>-</td>")
    body, totals = [], {}
    for r in rows:
        values = {f"{f}_{d}": num(r.get(f"{f}_{d}")) for f in ("vehicles", "vehicle_km",
                                                              "vehicle_hours") for d, _ in days}
        values["vehicle_km_week"] = num(r["vehicle_km_week"])
        values["vehicle_hours_week"] = num(r["vehicle_hours_week"])
        for k, v in values.items():
            t = totals.setdefault(r["mode"], {}).setdefault(k, 0)
            totals[r["mode"]][k] = t + (v or 0)
        body.append(
            f"<tr><td><i class='chip' style='background:{html.escape(r['color'])}'></i>"
            f"{html.escape(r['route'])}</td><td>{html.escape(r['mode'])}</td>"
            f"{cell(num(r.get('capacity')))}{cell(num(r['round_trip_min']))}"
            + "".join(cell(values[f"vehicles_{d}"]) for d, _ in days)
            + "".join(cell(values[f"vehicle_km_{d}"]) for d, _ in days)
            + cell(values["vehicle_km_week"]) + cell(values["vehicle_hours_weekday"])
            + cell(values["vehicle_hours_week"]) + "</tr>")
    for mode, t in sorted(totals.items()):
        body.append(
            f"<tr class='total'><td><b>all {html.escape(mode)}</b></td><td></td><td></td><td></td>"
            + "".join(cell(t[f"vehicles_{d}"]) for d, _ in days)
            + "".join(cell(t[f"vehicle_km_{d}"]) for d, _ in days)
            + cell(t["vehicle_km_week"]) + cell(t["vehicle_hours_weekday"])
            + cell(t["vehicle_hours_week"]) + "</tr>")
    lay = (run or {}).get("layover") or {}
    layover = (f"{lay['share'] * 100:g}% of the trip's running time, at least "
               f"{lay['min_s'] / 60:g} min" if lay else "a share of the running time")
    head = ("<th>route</th><th>mode</th><th>places a vehicle</th><th>round trip, min</th>"
            + "".join(f"<th>vehicles, {label}</th>" for _, label in days)
            + "".join(f"<th>vehicle-km, {label}</th>" for _, label in days)
            + "<th>vehicle-km a week</th><th>vehicle-hours, weekdays</th>"
              "<th>vehicle-hours a week</th>")
    return (f"<style>.ops td:first-child, .ops tr.total td {{ white-space:nowrap; }}</style>"
            f"<h1>Operations</h1><p class='note'>What each line takes to run. Its <b>round trip</b>"
            f" is the time a vehicle takes to be back where it started: both directions' running "
            f"time - as the timetable has it, a dwell at every stop - and a layover at each "
            f"terminus ({layover}); a loop run both ways round is two circulations. The "
            f"<b>vehicles</b> it needs are its round trip over its shortest headway that day, "
            f"rounded up - in service at its busiest, spares for maintenance on top. "
            f"<b>Vehicle-km</b> are every departure times its length, along the streets for a bus; "
            f"<b>vehicle-hours</b> every departure times its running time and layover. A week is "
            f"five weekdays and a weekend. Click a column to sort.</p>"
            f"<div class='scroll'><table class='ops' style='width:100%'><thead><tr>{head}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>")


def _lines(output_dir):
    path = os.path.join(output_dir, "exports", "lines.geojson")
    if not os.path.exists(path):
        return "<h1>Lines</h1><p class='note'>This design has no lines file: build it again.</p>"
    with open(path, encoding="utf-8") as f:
        features = [x["properties"] for x in json.load(f)["features"]
                    if x["properties"]["shape"] == "streets"]
    rows = []
    for p in features:
        km = p["km_streets"]
        if km is None:                                      # the metro: stop to stop
            km = _straight_km(p["stops"])
        minutes = p.get("run_min") or (km / p["speed_kmh"] * 60
                                       + max(0, len(p["stops"]) - 2) * p["dwell_s"] / 60)
        rows.append(
            f"<tr><td><i class='chip' style='background:{p['color']}'></i>"
            f"{html.escape(p['route'])}</td><td>{p['mode']}</td>"
            f"<td>towards {html.escape(p['towards'])}</td><td class='n'>{len(p['stops'])}</td>"
            f"<td>{html.escape(_service(p))}</td>"
            f"<td class='n'>{p.get('busiest_hour', 60 / p['headway_min']):.0f}</td>"
            f"<td class='n'>{p['speed_kmh']:g}</td>"
            f"<td class='n'>{km:.1f}{'' if p['km_streets'] is not None else ' *'}</td>"
            f"<td class='n'>{minutes:.0f} min</td></tr>")
    return (f"<h1>Lines</h1><p class='note'>Every route in each direction. The time end to end is "
            f"the feed's: each leg's length - along the streets for a bus - at the line's speed, "
            f"or its time set by hand, and a dwell at every stop between the termini. "
            f"* stop to stop in a straight line: the metro runs in a tunnel.</p>"
            f"<div class='scroll'><table style='width:100%'><thead><tr><th>route</th>"
            f"<th>mode</th><th>direction</th><th>stops</th><th>service</th>"
            f"<th>vehicles, busiest hour</th><th>km/h</th><th>km</th><th>end to end</th></tr>"
            f"</thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>")


def _service(p):
    """A direction's service in words; a design built before it was written: its headway."""
    return p.get("service") or f"every {p['headway_min']:g} min"


def _straight_km(stops):
    import math
    km = 0.0
    for (_, la1, lo1, _), (_, la2, lo2, _) in zip(stops, stops[1:]):
        la1, lo1, la2, lo2 = map(math.radians, (la1, lo1, la2, lo2))
        h = (math.sin((la2 - la1) / 2) ** 2
             + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
        km += 6371 * 2 * math.asin(math.sqrt(h))
    return km
