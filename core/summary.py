"""A run's headline numbers, saved as summary.json in the run's output folder.

The results page (viewer.py) shows them at the top. They are written already formatted, as
label and value pairs, so whatever reads them - the page now, a settings editor later - does not
need to know what each number means to show it.

The lines are the same for every city (HEADLINE), so every run's overview can be read against
any other's.
"""
import json
import os
import time

# The overview's lines, in order. The page shows these alone, so a run written before the list
# changed still shows the same lines as the others.
HEADLINE = ["zones", "modelled", "vehicle trips", "vehicle-hours", "congestion adds",
            "delay per trip"]

FILE = "summary.json"

# Where a trip goes against the city limit, from whether each end is in one of the city's own
# zones (an internal zone) or an external one. A city without external zones - Quito - has every
# trip "within". Labelled once here: the run's log and summary (numpy, trip_groups) and the
# results page (stats.py, from the exported matrix) say the same.
TRIP_GROUPS = [("within", "within the city", True, True),
               ("outbound", "from the city to outside", True, False),
               ("inbound", "from outside into the city", False, True),
               ("through", "through the city", False, False)]


def trip_groups(demand, is_internal):
    """{group: trips} of a zones x zones matrix, `is_internal` a bool per zone."""
    import numpy as np
    inside = np.asarray(is_internal, dtype=bool)
    return {key: float(demand[np.ix_(inside if o else ~inside, inside if d else ~inside)].sum())
            for key, _, o, d in TRIP_GROUPS}


# What the headline lines were called before a run could model another hour than the peak: an
# older run's summary is read under today's names.
OLD_NAMES = {"vehicle trips, peak hour": "vehicle trips",
             "vehicle-hours, peak hour": "vehicle-hours"}


def modelled(m):
    """"weekday, morning peak 07:00-08:00" - a loaded matrix's said as such: it is turned into
    the run's day and period like the model's."""
    from . import timeofday
    if m.demand_loaded:
        return f"a loaded O-D matrix, as {timeofday.label(m.s)}"
    return timeofday.label(m.s)


def headline(run):
    """{label: value} of a run's headline, older names read as today's."""
    return {OLD_NAMES.get(k, k): v for k, v in run.get("headline", [])}


def write(m, minutes):
    """`minutes` the run's steps took, together."""
    load = m.load
    trips = float(m.demand.sum())
    external = int((~m.is_internal).sum())
    delay_h = load["veh_hours"] - load["free_hours"]
    headline = [
        ["zones", f"{m.n_internal:,}" + (f" + {external} external" if external else "")],
        ["modelled", modelled(m)],
        ["vehicle trips", f"{trips:,.0f}"],
        ["vehicle-hours", f"{load['veh_hours']:,.0f}"],
        ["congestion adds", f"{100 * (load['veh_hours'] / load['free_hours'] - 1):.1f}% "
                            f"to travel time"],
        ["delay per trip", f"{60 * delay_h / trips:.2f} min"],
    ]
    assert [label for label, _ in headline] == HEADLINE
    summary = {
        "kind": "macro",               # a road run; public-transport runs write "transit"
        "city": m.label,
        "city_key": m.paths.city,
        # A named run (core/runs.py): name, label, description and {parameter: settings value}.
        "run": {k: v for k, v in (m.run_info or {"name": "baseline", "label": "baseline",
                                                 "description": "", "changes": {}}).items()},
        # The files it loaded instead of computing: {"zoning" | "od_matrix": the file's name}.
        "loaded": {k: v["name"] for k, v in (m.inputs or {}).items()},
        "finished": time.strftime("%Y-%m-%d %H:%M"),
        "minutes": round(minutes, 1),
        "headline": headline,
        # Unformatted, for the maps drawn from the exports (maps.draw_main_maps).
        "totals": {"trips": trips, "veh_hours": float(load["veh_hours"])},
        "modelled": modelled(m),
        # Zones numbered 1..internal are the city's own, the rest external (core/pipeline.py).
        "zones": {"internal": int(m.n_internal), "external": external},
        "trip_groups": trip_groups(m.demand, m.is_internal),
        # A scenario's closures: the trips left with no route, not assigned, and zones cut off.
        "unrouted": getattr(m, "unrouted_said", None),
    }
    with open(os.path.join(m.paths.output, FILE), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1, ensure_ascii=False)


def read(output_dir):
    """The summary of the run in `output_dir`, or None if it has none."""
    path = os.path.join(output_dir, FILE)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)
