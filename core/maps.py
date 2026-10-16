"""The map helpers every city shares: one hover panel design, one backdrop, one set of boxes.

The two main maps - the zones and the simulation - are drawn here alone, the same way for every
city, and only from what the run exported (`draw_main_maps`): zones.gpkg, link_volumes.gpkg,
city_limit.gpkg and the totals in summary.json. So they can be redrawn after a change to how they
look without running the model again (view.py --maps), and a redraw is what a run would draw.

Every other map is drawn by a function marked `@redrawable`. Its inputs exist only while the
model runs - census sectors, commuting, counts - so as it draws, it also saves them, in
map_data/ beside maps/; `redraw_maps` calls the same function on them again. Those files are
pickles the run wrote for itself: read them back with the code that wrote them, not as an
exchange format.

`MapKit` holds what the helpers need to know about the city - its metric CRS and where maps go -
so a case builds one and calls its methods.
"""
import functools
import glob
import importlib
import inspect
import os
import pickle
import re
from html import escape as html_escape

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
import shapely.wkb

from .network_classes import (CONGESTION_BANDS, LOCAL_ROAD_TYPES, MAP_ROAD_TYPES,
                              OFF_AT_START, ROAD_CLASS_ORDER)

# The hover panel. The styling lives in a single stylesheet so the per-feature HTML stays small.
TIP_CSS = """
<style>
.leaflet-tooltip { font-family: sans-serif; font-size: 12px; color: #222; }
.leaflet-tooltip table { margin: 0 !important; border-collapse: collapse; }
.leaflet-tooltip td, .leaflet-tooltip th { padding: 0; border: none; font-size: 12px; }
/* labels: a <th> when folium builds the rows, the first <td> when tip_html does */
.leaflet-tooltip th,
.leaflet-tooltip td:first-child { color: #555; font-weight: normal; text-align: left;
                                  padding-right: 12px; }
.leaflet-tooltip td:last-child { text-align: right; white-space: nowrap; }
/* the first row of folium's own rows gets the weight a title would have */
.leaflet-tooltip tr:first-child th + td { font-weight: bold; }
.leaflet-tooltip b { display: block; margin-bottom: 4px; white-space: nowrap; }
.leaflet-tooltip b span { font-weight: normal; color: white; border-radius: 3px;
                          padding: 1px 5px; font-size: 10px; margin-left: 6px; }
</style>
"""

AREA_RAMP = ("#cde2fb", "#9ec5f4", "#5598e7", "#2a78d6", "#104281")      # blue, light to dark
DENSITY_RAMP = ("#f9c3a8", "#f2996f", "#eb6834", "#b74a1f", "#8a3714")   # orange, light to dark
COORD_GRID = 1e-5            # about 1 m: past what the map can show, and half the file size
BOX_STYLE = ("position:fixed;z-index:9999;background:white;padding:9px 12px;"
             "border:1px solid #999;border-radius:6px;font-family:sans-serif;font-size:13px;")

# The backdrop: Esri's Light Gray Canvas, a pale base with its place labels as a separate layer.
# CARTO's Positron, used before, now answers every tile with "API key required"; Esri's canvas
# needs no key, only the attribution shown in the corner.
ESRI_CANVAS = ("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/{}/MapServer/tile/"
               "{{z}}/{{y}}/{{x}}")
ESRI_ATTRIBUTION = "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors"

LINE_WEIGHT = {"motorway": 3.6, "trunk": 3.2, "primary": 2.6, "secondary": 2.0, "tertiary": 1.4,
               "residential": 0.9, "unclassified": 0.9}
LINK_SIMPLIFY_M = 8
TRIP_CIRCLE_MAX_PX = 18                  # radius of the zone with the most trip ends
ZONES_MAP = "zones.html"
SIMULATION_MAP = "simulation.html"
CHANGE_MAP = "change.html"            # a scenario's traffic against its base's
SCENARIO_FILE = "scenario.json"       # beside summary.json: what the scenario's Overview shows
CHANGE_MIN = 25                       # veh/h: a smaller change in a link's flow is not drawn
MORE, LESS = "#e8590c", "#1c7ed6"     # more vehicles than the base, fewer: volume
# The edits as the Scenarios and Compare pages draw them: closures a black line over the change,
# capacity and speed as a halo under it.
EDIT_LOOK = {"close": {"color": "#111111", "weight": 4, "said": "closed"},
             "capacity": {"color": "#e8a400", "weight": 11, "opacity": 0.45,
                          "said": "capacity changed"},
             "speed": {"color": "#7048e8", "weight": 11, "opacity": 0.4, "said": "speed changed"},
             "road": {"color": "#0b7285", "weight": 5, "said": "new road"}}
TOP_CHANGES = 10                      # streets listed gaining, and losing, the most traffic
# A demand scenario's zones: where added trips start, where they end, a development.
ZONE_LOOK = {"from": ("#7048e8", "trips added from here"), "to": ("#0b7285", "trips added to here"),
             "develop": ("#e8a400", "a development")}
MIN_DVOC = 0.05                       # a capacity scenario's map: a smaller change in V/C, grey
# The notebook's congestion-change bands: (upper bound of the change in V/C, colour, said).
# Green eased, red worse - congestion's colours wherever it is shown, apart from volume's
# orange and blue.
DVOC_BANDS = [(-0.20, "#1a9850", "much less congested"), (-MIN_DVOC, "#91cf60", "less congested"),
              (MIN_DVOC, "#dddddd", "about the same"), (0.20, "#fc8d59", "more congested"),
              (float("inf"), "#d7301f", "much more congested")]
STREET_MIN_VKM = 500                  # a street listed as easing or worsening carries this much
TRIP_ENDS_MAP = "trip_ends.html"
STARTS, ENDS = "#2a78d6", "#eb6834"      # the results page's free flow / simulation pair
PLAIN_FILL = "#eae7e0"                   # the quiet backdrop circles sit on


def takes_white_text(hex_color, minimum=3.0):
    """Whether white text on this colour clears a contrast ratio, so a tag can be filled with it.

    Worked out rather than listed, so changing a colour cannot leave an unreadable tag behind.
    """
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return 1.05 / (luminance + 0.05) >= minimum


def tip_html(title, rows, tag=None, tag_color="#52514e"):
    """The panel as an HTML string. `rows` is a list of (label, value) pairs, pre-formatted.

    Deliberately bare markup: this string is stored once per feature and its quotes are escaped
    again inside the GeoJSON, so anything beyond the content is paid for thousands of times.
    """
    if tag and not takes_white_text(tag_color):
        tag_color = "#52514e"
    chip = f'<span style=background:{tag_color}>{tag}</span>' if tag else ""
    body = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in rows)
    return f"<b>{title}{chip}</b><table>{body}</table>"


def panel_tooltip():
    """The tooltip binding every map uses; the panel itself is in the `tip` column."""
    return folium.GeoJsonTooltip(fields=["tip"], labels=False, sticky=True)


def quintile_shader(values, ramp, fmt="{:,.0f}", unit=""):
    """Quintile classes of a skewed quantity: a colour per value and the legend labels."""
    cuts = list(np.quantile(values, [0.2, 0.4, 0.6, 0.8]))
    labels = ([f"under {fmt.format(cuts[0])}{unit}"]
              + [f"{fmt.format(lo)} &ndash; {fmt.format(hi)}{unit}"
                 for lo, hi in zip(cuts, cuts[1:])]
              + [f"over {fmt.format(cuts[-1])}{unit}"])

    def shade(value):
        for limit, colour in zip(cuts, ramp):
            if value <= limit:
                return colour
        return ramp[-1]
    return shade, labels


def add_basemap(m):
    """Pale grey base and its labels, kept out of the layer control: not something to switch off."""
    for layer, name in (("World_Light_Gray_Base", "Light grey"),
                        ("World_Light_Gray_Reference", "Place names")):
        folium.TileLayer(tiles=ESRI_CANVAS.format(layer), attr=ESRI_ATTRIBUTION, name=name,
                         max_zoom=16, control=False).add_to(m)
    return m


def route_class(*routes):
    """The CSS classes a map element of these routes carries, for the legend's toggles
    (add_legend `toggles`): "rt rt-T48", or "rt rt-A rt-B" for a stop several routes share - it
    hides only when all of them are hidden."""
    return "rt " + " ".join("rt-" + re.sub(r"[^A-Za-z0-9_-]", "_", str(r)) for r in routes)


# Showing, hiding and picking out routes. Every element with class "rt" is shown while any of its
# "rt-<route>" classes is not hidden. A MutationObserver re-applies it when Leaflet redraws a
# layer (switching between base layers creates its paths again); hiding changes only styles,
# which it ignores. Picking out a route - pointing at it in the legend, or clicking it there or on
# the map - fades every other route: the page's body gets "rt-focus" and the route's elements
# "rt-on". Clicking the map elsewhere puts every route back.
ROUTE_TOGGLE_JS = """
<style>.rt-entry{cursor:pointer;user-select:none;border-radius:3px;padding:0 2px}
.rt-entry:hover,.rt-entry.on{background:#eef2f7}.rt-entry input{margin:0 4px 0 0;vertical-align:middle;cursor:pointer}
.rt-btn{font:inherit;font-size:11px;padding:0 6px;margin-left:4px;border:1px solid #bbb;
border-radius:4px;background:#fff;cursor:pointer}
body.rt-focus .rt{opacity:.12}body.rt-focus .rt.rt-on{opacity:1}
body.rt-focus path.ln.rt-on{stroke-width:6px}</style>
<script>
(function () {
  var hidden = new Set(), pinned = null, pointed = null;
  function keysOf(el) {
    return (el.getAttribute('class') || '').split(/\\s+/)
      .filter(function (c) { return c.indexOf('rt-') === 0 && c !== 'rt-on'; })
      .map(function (c) { return c.slice(3); });
  }
  function apply() {
    var focus = pointed || pinned;
    document.body.classList.toggle('rt-focus', !!focus);
    document.querySelectorAll('.rt').forEach(function (el) {
      var keys = keysOf(el);
      var show = keys.some(function (k) { return !hidden.has(k); });
      el.style.display = show ? '' : 'none';
      el.classList.toggle('rt-on', !!focus && keys.indexOf(focus) >= 0);
    });
    document.querySelectorAll('[data-rt]').forEach(function (e) {
      var k = e.getAttribute('data-rt');
      e.style.opacity = hidden.has(k) ? 0.45 : 1;
      e.classList.toggle('on', k === pinned);
      var box = e.querySelector('input');
      if (box) box.checked = !hidden.has(k);
    });
  }
  window.rtToggle = function (key) {
    if (hidden.has(key)) hidden.delete(key); else hidden.add(key);
    apply();
  };
  window.rtAll = function (on) {
    hidden.clear();
    if (!on) document.querySelectorAll('[data-rt]').forEach(function (e) {
      hidden.add(e.getAttribute('data-rt'));
    });
    apply();
  };
  window.rtPoint = function (key) { pointed = key; apply(); };
  window.rtPin = function (key) {
    pinned = pinned === key ? null : key;
    if (pinned) hidden.delete(pinned);
    apply();
  };
  // On the map: a click on a route's line picks it out, a click elsewhere puts them all back.
  document.addEventListener('click', function (e) {
    if (!e.target.closest || !e.target.closest('.leaflet-container')
        || e.target.closest('.leaflet-control')) return;
    var el = e.target.closest('.rt');
    var keys = el ? keysOf(el) : [];
    if (keys.length === 1) { pinned = pinned === keys[0] ? null : keys[0]; apply(); }
    else if (!el && pinned) { pinned = null; apply(); }
  });
  window.addEventListener('load', function () {
    new MutationObserver(function () { if (hidden.size || pinned || pointed) apply(); })
      .observe(document.body, {childList: true, subtree: true});
  });
})();
</script>
"""


def add_legend(m, title, ramp, labels, note="", max_width=270, extra="", toggles=None):
    """A legend box: a swatch per colour, then `extra` (html of entries of another kind), then
    the note, if any. With `toggles` - a route per entry - each entry's box shows or hides that
    route's lines and stops (drawn with route_class), "all" and "none" do every route, and
    pointing at an entry, or clicking it, picks its route out (ROUTE_TOGGLE_JS)."""
    keys = [route_class(t).split()[1][3:] for t in toggles] if toggles else [None] * len(labels)
    swatches = "".join(
        (f'<div class="rt-entry" data-rt="{k}" onclick="rtPin(\'{k}\')" '
         f'onmouseenter="rtPoint(\'{k}\')" onmouseleave="rtPoint(null)">'
         f'<input type="checkbox" checked title="show or hide it" '
         f'onclick="event.stopPropagation(); rtToggle(\'{k}\')">' if k else '<div>')
        + f'<span style="display:inline-block;width:14px;height:10px;background:{c};'
        f'margin:0 6px 1px 0;border:1px solid #fff;vertical-align:middle;"></span>{lab}</div>'
        for c, lab, k in zip(ramp, labels, keys))
    if len(labels) > 16:                  # a city of many lines: the list scrolls, the map shows
        swatches = f'<div style="max-height:40vh;overflow-y:auto;padding-right:6px;">{swatches}</div>'
    if toggles:
        m.get_root().header.add_child(folium.Element(ROUTE_TOGGLE_JS))
        title += ('<button class="rt-btn" onclick="rtAll(true)">all</button>'
                  '<button class="rt-btn" onclick="rtAll(false)">none</button>')
        note = ("point at a line, or click it here or on the map, to pick it out; its box shows "
                "or hides it" + ("<br>" + note if note else ""))
    note =f'<div style="margin-top:5px;color:#555;font-size:11px;">{note}</div>' if note else ""
    m.get_root().html.add_child(folium.Element(
        f'<div style="{BOX_STYLE}bottom:24px;left:24px;line-height:1.45;max-width:{max_width}px;">'
        f'<b>{title}</b>{swatches}{extra}{note}</div>'))


def add_panel(m, title, lines, max_width=280):
    body = "".join(f"<div>{line}</div>" for line in lines)
    m.get_root().html.add_child(folium.Element(
        f'<div style="{BOX_STYLE}top:20px;right:20px;line-height:1.5;max-width:{max_width}px;">'
        f'<b>{title}</b>{body}</div>'))


def link_frame(project, columns="link_id, a_node, b_node, direction, link_type, name"):
    """Links with shapely geometry, in lat/lon."""
    with project.db_connection_spatial as conn:
        frame = pd.read_sql(f"SELECT {columns}, AsBinary(geometry) wkb FROM links", conn)
    frame["geometry"] = [shapely.wkb.loads(bytes(b)) for b in frame["wkb"]]
    return gpd.GeoDataFrame(frame.drop(columns="wkb"), geometry="geometry", crs="EPSG:4326")


MAP_DATA = "map_data"


def redrawable(draw):
    """Mark a map function so a run saves what it was drawn from, for `redraw_maps`.

    The function takes the MapKit first (as `kit` or `self`) and a `filename`; everything else
    it is given is saved as it was, under map_data/<filename>.pkl."""
    signature = inspect.signature(draw)

    @functools.wraps(draw)
    def drawing(kit, *args, **kwargs):
        bound = signature.bind(kit, *args, **kwargs)
        bound.apply_defaults()
        inputs = dict(bound.arguments)
        inputs.pop(next(iter(signature.parameters)))          # the kit: rebuilt on a redraw
        folder = os.path.join(os.path.dirname(kit.maps_dir), MAP_DATA)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, inputs["filename"][:-5] + ".pkl"), "wb") as f:
            pickle.dump({"module": draw.__module__, "function": draw.__qualname__,
                         "metre_crs": kit.metre_crs, "simplify_m": kit.simplify_m,
                         "inputs": inputs}, f)
        return draw(kit, *args, **kwargs)

    return drawing


def redraw_maps(output_dir):
    """Every map of the run in `output_dir` drawn again, without running the model: the two
    main ones from the exports, the others from what map_data/ kept of their inputs.

    A public-transport run has no road exports: all its maps come from map_data/."""
    from . import summary
    if (summary.read(output_dir) or {}).get("kind", "macro") == "macro":
        draw_main_maps(output_dir)
    maps_dir = os.path.join(output_dir, "maps")
    for path in sorted(glob.glob(os.path.join(output_dir, MAP_DATA, "*.pkl"))):
        with open(path, "rb") as f:
            saved = pickle.load(f)
        draw = importlib.import_module(saved["module"])
        for part in saved["function"].split("."):
            draw = getattr(draw, part)
        kit = MapKit(saved["metre_crs"], maps_dir, saved["simplify_m"])
        # An input the function no longer takes - a layer since dropped from the map - is left
        # out, so a map can lose one without a new run. One it now needs and was never given
        # still fails: that takes a run.
        takes = inspect.signature(draw.__wrapped__).parameters
        inputs = {k: v for k, v in saved["inputs"].items() if k in takes}
        draw.__wrapped__(kit, **inputs)          # not saved again: nothing changed


def draw_main_maps(output_dir):
    """The zones and simulation maps of the run in `output_dir`, from its exports."""
    from . import summary          # here, not at the top: summary is only needed for a redraw

    exports = os.path.join(output_dir, "exports")
    totals = (summary.read(output_dir) or {}).get("totals")
    if totals is None:
        raise FileNotFoundError(f"no totals in {output_dir}/summary.json: run the city again "
                                f"once to write them")
    zones = gpd.read_file(os.path.join(exports, "zones.gpkg"))
    zones["centroid"] = gpd.points_from_xy(zones["centroid_lon"], zones["centroid_lat"])
    links = gpd.read_file(os.path.join(exports, "link_volumes.gpkg"))
    boundary = gpd.read_file(os.path.join(exports, "city_limit.gpkg"))
    kit = MapKit(zones.estimate_utm_crs(), os.path.join(output_dir, "maps"))
    kit.map_zones(zones)
    run = summary.read(output_dir) or {}
    kit.map_congestion(links, boundary, totals["trips"], totals["veh_hours"],
                       title=(f"Car traffic, {run['modelled']}" if run.get("modelled")
                              else "Peak-hour car traffic"))
    od = pd.read_csv(os.path.join(exports, "od_matrix.csv.gz"), usecols=["origin", "destination",
                                                                         "trips"])
    kit.map_trip_ends(zones, od)
    if (run.get("run") or {}).get("base"):
        draw_scenario(output_dir, kit, links, boundary, run)


def _or_zero(x):
    """A number, 0 where there is none (NaN: no row to take it from)."""
    return 0.0 if pd.isna(x) else float(x)


def edit_said(edit):
    """'closed', 'capacity × 1.5', 'speed 30 km/h', 'new primary, 2 lanes each way, 60 km/h', or
    a demand edit as core/demand_edits says it."""
    from .demand_edits import KINDS as DEMAND_KINDS, said
    if edit["kind"] in DEMAND_KINDS:
        return said(edit)
    if edit["kind"] == "close":
        return "closed"
    if edit["kind"] == "road":
        lanes = f"{edit['lanes']} lane{'s' if edit['lanes'] > 1 else ''}"
        return (f"new {edit['link_type']}, {lanes} {'one way' if edit['oneway'] else 'each way'}, "
                f"{edit['kmh']:g} km/h")
    if edit["kind"] == "capacity":
        return f"capacity × {edit['factor']:g}"
    return f"speed {edit['kmh']:g} km/h"


def _edited_zones(base_dir, edits):
    """A demand scenario's zones, each with its role (ZONE_LOOK) and the edit that names it; None
    for a scenario that names none."""
    roles = []
    for e in edits:
        for role, key in (("from", "from_zones"), ("to", "to_zones"), ("develop", "zones")):
            roles += [(int(z), role, edit_said(e)) for z in e.get(key) or []]
    if not roles:
        return None
    zones = gpd.read_file(os.path.join(base_dir, "exports", "zones.gpkg"))[
        ["zone_number", "zone", "pop", "geometry"]]
    named = pd.DataFrame(roles, columns=["zone_number", "role", "edit"])
    return gpd.GeoDataFrame(named.merge(zones, on="zone_number"), geometry="geometry",
                            crs=zones.crs).to_crs("EPSG:4326")


def draw_scenario(output_dir, kit, links, boundary, run):
    """A scenario's change from its base: the map (CHANGE_MAP), and SCENARIO_FILE - its edits
    with their streets, the headline numbers beside its base's, and the streets that changed
    most - for its Overview. Both from the two runs' exports. A closure moves traffic: its map
    and streets are volumes. A capacity or speed change makes roads more or less congested - a
    widened road usually carries more, with less congestion, which a volume map would paint as
    worse: its map and streets are V/C, and its edited roads are shown before and after."""
    import json

    from . import runs, summary
    scenario = run["run"]
    kind = scenario.get("type") or runs.scenario_type(scenario.get("edits", []))
    base_dir = runs.output_dir(run["city_key"], scenario["base"])
    base_run = summary.read(base_dir)
    if base_run is None:
        print(f"(no change map: its base {scenario['base']} has no results)")
        return
    # The base's links, every one - a closed link has no flow in the scenario - with both runs'
    # flows: veh/h both ways, and V/C of the busier way.
    base = gpd.read_file(os.path.join(base_dir, "exports", "link_volumes.gpkg"))
    own = pd.DataFrame(links.drop(columns="geometry"))[["link_id", "car_ab", "car_ba", "voc"]]
    both = base.merge(own, on="link_id", how="left", suffixes=("_base", ""))
    # A new road is the scenario's alone: nothing on it in the base.
    new = links[~links["link_id"].isin(base["link_id"])]
    if len(new):
        both = pd.concat([both, new.rename(columns={"car_ab": "car_ab", "car_ba": "car_ba"})
                          .assign(car_ab_base=0.0, car_ba_base=0.0, voc_base=0.0)],
                         ignore_index=True)
    both["flow_base"] = both["car_ab_base"].fillna(0) + both["car_ba_base"].fillna(0)
    both["flow"] = both["car_ab"].fillna(0) + both["car_ba"].fillna(0)
    both["change"] = both["flow"] - both["flow_base"]
    both["voc_base"] = both["voc_base"].fillna(0)
    both["voc"] = both["voc"].fillna(0)
    both["dvoc"] = both["voc"] - both["voc_base"]
    both["km"] = both["distance"] / 1000
    both["vkm_base"], both["vkm"] = both["flow_base"] * both["km"], both["flow"] * both["km"]
    main = both[both["link_type"].isin(MAP_ROAD_TYPES)]

    by_id = both.set_index("link_id")
    edits = []
    from .demand_edits import KINDS as DEMAND_KINDS
    for e in scenario.get("edits", []):
        if e["kind"] in DEMAND_KINDS:
            edits.append({"kind": e["kind"], "said": edit_said(e), "label": e.get("label") or "",
                          "added": e.get("added")})
            continue
        ids = [i for i in e["links"] if i in by_id.index]
        on = by_id.loc[ids]
        names = [n for n in dict.fromkeys(on["name"].fillna("")) if n]
        said = {"kind": e["kind"], "said": edit_said(e), "label": e.get("label") or "",
                "streets": names, "links": len(e["links"]), "km": round(float(on["km"].sum()), 2),
                # The roads it edits, before and after: the vehicles on an average link both
                # ways, and the worst V/C along them.
                # A link the assignment left empty is not in the exports: it carries nothing.
                "flow": [round(_or_zero(on["flow_base"].mean())), round(_or_zero(on["flow"].mean()))],
                "voc": [round(_or_zero(on["voc_base"].max()), 2), round(_or_zero(on["voc"].max()), 2)]}
        if e["kind"] == "road":
            said["road"] = {k: e[k] for k in ("link_type", "lanes", "kmh", "lane_capacity",
                                               "oneway")}
        edits.append(said)

    # Each named street, in both runs: its vehicle-km, and its V/C weighted by them.
    # The streets the edits change - not a new road itself, which the Overview lists on its own.
    new_ids = {i for e in scenario.get("edits", []) if e["kind"] == "road" for i in e.get("links", [])}
    named = main[(main["name"].fillna("") != "") & ~main["link_id"].isin(new_ids)].assign(
        w_base=lambda d: d["voc_base"] * d["vkm_base"], w=lambda d: d["voc"] * d["vkm"])
    streets = named.groupby("name").agg(km=("km", "sum"), vkm_base=("vkm_base", "sum"),
                                       vkm=("vkm", "sum"), w_base=("w_base", "sum"),
                                       w=("w", "sum"))
    streets["change"] = streets["vkm"] - streets["vkm_base"]
    streets["voc_base"] = streets["w_base"] / streets["vkm_base"].where(streets["vkm_base"] > 0)
    streets["voc"] = streets["w"] / streets["vkm"].where(streets["vkm"] > 0)
    streets["dvoc"] = streets["voc"] - streets["voc_base"]
    if kind in ("closure", "newroad", "demand"):           # traffic moved: volumes
        def rows(part):
            return [[name, round(r.vkm_base), round(r.change),
                     round(100 * r.change / r.vkm_base) if r.vkm_base else None]
                    for name, r in part.iterrows()]
        more = rows(streets[streets["change"] > 0].nlargest(TOP_CHANGES, "change"))
        less = rows(streets[streets["change"] < 0].nsmallest(TOP_CHANGES, "change"))
    else:
        busy = streets[(streets["vkm_base"] >= STREET_MIN_VKM) & streets["dvoc"].notna()]

        def rows(part):
            return [[name, round(r.voc_base, 2), round(r.voc, 2), round(r.dvoc, 2),
                     round(100 * r.change / r.vkm_base) if r.vkm_base else None]
                    for name, r in part.iterrows()]
        more = rows(busy[busy["dvoc"] > 0].nlargest(TOP_CHANGES, "dvoc"))
        less = rows(busy[busy["dvoc"] < 0].nsmallest(TOP_CHANGES, "dvoc"))
    out = {"base": scenario["base"], "type": kind,
           "base_label": (base_run.get("run") or {}).get("label") or scenario["base"],
           "base_folder": os.path.basename(base_dir), "edits": edits,
           "headline": [[k, dict(base_run["headline"]).get(k), v] for k, v in run["headline"]],
           "totals": {"base": base_run["totals"], "scenario": run["totals"]},
           "more": more, "less": less, "unrouted": run.get("unrouted"),
           # The trips by group, base and scenario: a demand scenario changes them.
           "groups": {k: [(base_run.get("trip_groups") or {}).get(k), (run.get("trip_groups") or {}).get(k)]
                      for k in (run.get("trip_groups") or {})}}
    with open(os.path.join(output_dir, SCENARIO_FILE), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    drawn = main[["link_id", "name", "link_type", "distance", "flow_base", "flow", "change",
                  "voc_base", "voc", "dvoc", "geometry"]].reset_index(drop=True)
    as_drawn = [dict(e, links=[int(i) for i in e.get("links", [])]) for e in scenario.get("edits", [])]
    if kind in ("closure", "newroad", "demand"):
        kit.map_change(drawn, boundary, as_drawn, out["base_label"], out["totals"],
                       zones=_edited_zones(base_dir, scenario.get("edits", [])))
    else:
        kit.map_congestion_change(drawn, boundary, as_drawn, out["base_label"], out["totals"])


class MapKit:
    """The map helpers, bound to one city's metric CRS and map folder."""

    def __init__(self, metre_crs, maps_dir, simplify_m=12):
        self.metre_crs = metre_crs
        self.maps_dir = maps_dir
        self.simplify_m = simplify_m

    def for_the_browser(self, frame, simplify_m=None):
        """A copy in lat/lon, simplified and snapped so neighbours still share their borders."""
        drawn = frame.copy()
        drawn["geometry"] = (drawn.to_crs(self.metre_crs)
                             .simplify(self.simplify_m if simplify_m is None else simplify_m)
                             .to_crs("EPSG:4326"))
        drawn["geometry"] = shapely.set_precision(drawn.geometry.values, COORD_GRID)
        return drawn

    def base_map(self, frame, zoom=12):
        """A pale backdrop centred on the data, with the panel stylesheet loaded."""
        whole = frame.to_crs("EPSG:4326").geometry.union_all().centroid
        m = folium.Map(location=[whole.y, whole.x], zoom_start=zoom, tiles=None)
        add_basemap(m)
        m.get_root().header.add_child(folium.Element(TIP_CSS))
        return m

    def add_borders(self, m, frame, name, weight=1.4, show=True, simplify_m=25, control=True):
        """Outlines only - no fill, so they never catch the mouse over the data beneath.

        `control=False` keeps them out of the layer panel: always drawn."""
        folium.GeoJson(
            self.for_the_browser(frame, simplify_m)[["geometry"]],
            style_function=lambda f: {"fill": False, "color": "#1a1a19", "weight": weight},
        ).add_to(folium.FeatureGroup(name=name, show=show, control=control).add_to(m))

    def map_zones(self, zones, filename=ZONES_MAP):
        """The zones shaded by people per km2, with their centroids - the same for every city.

        `zones` has one row per zone: `zone` (its code), `pop`, `area_km2`, `n_sectors` (census
        sectors it was built from), `centroid` (a lat/lon point) and its polygon. How a city
        gets there - census zonas, weighting areas - is its own business; the map is not.

        The zones are always drawn; the centroids can be switched on, and start off."""
        drawn = self.for_the_browser(zones[["zone", "pop", "area_km2", "n_sectors", "geometry"]])
        drawn["density"] = drawn["pop"] / drawn["area_km2"]
        shade, labels = quintile_shader(drawn["density"], DENSITY_RAMP)
        drawn["fill"] = [shade(v) for v in drawn["density"]]
        drawn["tip"] = [
            tip_html(r.zone, [("people", f"{r.pop:,.0f}"),
                              ("census sectors", f"{r.n_sectors}"),
                              ("area", f"{r.area_km2:.2f} km&sup2;"),
                              ("people per km&sup2;", f"{r.density:,.0f}")])
            for r in drawn.itertuples()]
        m = add_basemap(folium.Map(tiles=None, zoom_snap=0.25))
        m.get_root().header.add_child(folium.Element(TIP_CSS))
        minx, miny, maxx, maxy = drawn.total_bounds
        m.fit_bounds([[miny, minx], [maxy, maxx]])
        folium.GeoJson(
            drawn[["tip", "fill", "geometry"]],
            style_function=lambda f: {"fillColor": f["properties"]["fill"], "color": "#ffffff",
                                      "weight": 0.5, "fillOpacity": 0.8},
            # Hover deepens the fill rather than restroking: neighbours share every border and
            # each draws its own copy, so a restroke would land under whichever is on top.
            highlight_function=lambda f: {"fillOpacity": 1.0, "weight": 1.8, "color": "#1a1a19"},
            tooltip=panel_tooltip(),
        ).add_to(folium.FeatureGroup(name="Zones", control=False).add_to(m))
        dots = folium.FeatureGroup(name="Zone centroids", show=False).add_to(m)
        for point in zones["centroid"]:
            folium.CircleMarker([point.y, point.x], radius=1.6, color="#1a1a19", weight=0,
                                fill=True, fill_opacity=0.85).add_to(dots)
        folium.LayerControl(collapsed=False, position="topleft").add_to(m)
        add_legend(m, "People per km&sup2;", DENSITY_RAMP, labels,
                   "quintiles &middot; darker = denser<br>black dots = zone centroids")
        add_panel(m, "Traffic analysis zones",
                  [f"{len(zones):,} zones", f"{zones['pop'].sum():,.0f} people"])
        return self.save(m, filename)

    @redrawable
    def map_change(self, links, boundary, edits, base_label, totals, filename=CHANGE_MAP,
                   zones=None):
        """A closure scenario's traffic against its base's, link by link: more in orange, less in
        blue, the width the change; the closed roads in black over it, each saying what it
        carried.
        `links` are the main roads with both runs' flows (draw_scenario)."""
        drawn = links.copy()
        drawn["geometry"] = (drawn.to_crs(self.metre_crs).simplify(LINK_SIMPLIFY_M)
                             .to_crs("EPSG:4326"))
        drawn["geometry"] = shapely.set_precision(drawn.geometry.values, COORD_GRID)
        name = drawn["name"].fillna("").replace("", "unnamed street")

        def rows(r):
            out = [("class", r.link_type),
                   (f"in {html_escape(base_label)}", f"{r.flow_base:,.0f} veh/h"),
                   ("in the scenario", f"{r.flow:,.0f} veh/h"),
                   ("change", f"{r.change:+,.0f} veh/h"
                    + (f" ({100 * r.change / r.flow_base:+.0f}%)" if r.flow_base else ""))]
            if pd.notna(r.voc_base) and pd.notna(r.voc):
                out.append(("V/C", f"{r.voc_base:.2f} &rarr; {r.voc:.2f}"))
            return out

        m = add_basemap(folium.Map(tiles=None, zoom_snap=0.25))
        m.get_root().header.add_child(folium.Element(TIP_CSS))
        minx, miny, maxx, maxy = drawn.total_bounds
        m.fit_bounds([[miny, minx], [maxy, maxx]])
        self.add_borders(m, boundary, "City limit", weight=1.2, control=False)
        # The roads, pale: where the changes are.
        folium.GeoJson(drawn[["geometry"]], style_function=lambda f: {
            "color": "#c9ced4", "weight": 1, "opacity": 0.8}, interactive=False).add_to(
            folium.FeatureGroup(name="The roads", control=False).add_to(m))
        by_id = drawn.set_index("link_id")

        def edit_layer(kinds, layer_name):
            group = folium.FeatureGroup(name=layer_name, control=False).add_to(m)
            for e in edits:
                if e["kind"] not in kinds:
                    continue
                look = EDIT_LOOK[e["kind"]]
                part = by_id.loc[[i for i in e["links"] if i in by_id.index]].reset_index()
                if part.empty:
                    continue
                streets = ", ".join(n for n in dict.fromkeys(part["name"].fillna("")) if n)
                if e["kind"] == "road":
                    part["tip"] = [tip_html(html_escape(streets or "new road"), [
                        ("edit", edit_said(e)), ("it carries", f"{r.flow:,.0f} veh/h, both ways"),
                        ("V/C", f"{r.voc:.2f}"), ("length", f"{r.distance / 1000:,.2f} km")],
                        tag="NEW ROAD", tag_color=look["color"]) for r in part.itertuples()]
                else:
                    part["tip"] = [tip_html(html_escape(streets or "unnamed roads"), [
                        ("edit", edit_said(e)), ("this link carried", f"{r.flow_base:,.0f} veh/h"),
                        ("now", "nothing: closed" if e["kind"] == "close"
                         else f"{r.flow:,.0f} veh/h"),
                        ("the edit", f"{len(part)} links, "
                                     f"{part['distance'].sum() / 1000:,.1f} km")],
                        tag="CLOSED" if e["kind"] == "close" else "EDIT", tag_color=look["color"])
                        for r in part.itertuples()]
                folium.GeoJson(part[["geometry", "tip"]], style_function=lambda f, look=look: {
                    "color": look["color"], "weight": look["weight"],
                    "opacity": look.get("opacity", 0.95), "dashArray": look.get("dashArray")},
                    tooltip=panel_tooltip()).add_to(group)

        if zones is not None:                                        # a demand scenario's zones
            zones = zones.copy()
            zones["colour"] = [ZONE_LOOK[r][0] for r in zones["role"]]
            zones["tip"] = [tip_html(html_escape(f"zone {r.zone_number} ({r.zone})"), [
                ("edit", html_escape(r.edit)), ("people", f"{r.pop:,.0f}")],
                tag=ZONE_LOOK[r.role][1].upper(), tag_color=r.colour) for r in zones.itertuples()]
            folium.GeoJson(zones[["geometry", "colour", "tip"]], style_function=lambda f: {
                "color": f["properties"]["colour"], "weight": 2, "fillColor": f["properties"]["colour"],
                "fillOpacity": 0.25}, tooltip=panel_tooltip()).add_to(
                folium.FeatureGroup(name="Zones edited", control=False).add_to(m))
        edit_layer({"capacity", "speed"}, "Capacity and speed")      # a halo, under the change
        changed = drawn[drawn["change"].abs() >= CHANGE_MIN].copy()
        biggest = max(changed["change"].abs().max(), 1) if len(changed) else 1
        changed["colour"] = np.where(changed["change"] > 0, MORE, LESS)
        changed["weight"] = 1.5 + 7 * np.sqrt(changed["change"].abs() / biggest)
        changed = changed.loc[changed["change"].abs().sort_values().index]   # biggest on top
        changed["tip"] = [tip_html(html_escape(n), rows(r), tag="MORE" if r.change > 0 else "LESS",
                                   tag_color=MORE if r.change > 0 else LESS)
                          for n, r in zip(name[changed.index], changed.itertuples())]
        if len(changed):                     # nothing changed enough: no layer (an empty one fails)
            folium.GeoJson(changed[["geometry", "tip", "colour", "weight"]],
                           style_function=lambda f: {"color": f["properties"]["colour"],
                                                     "weight": f["properties"]["weight"],
                                                     "opacity": 0.9},
                           tooltip=panel_tooltip()).add_to(
                folium.FeatureGroup(name="The change", control=False).add_to(m))
        edit_layer({"close"}, "Closures")                            # black, over the change
        edit_layer({"road"}, "New roads")                            # over it too

        key = "".join(
            f'<div><span style="display:inline-block;width:16px;height:4px;background:{c};'
            f'margin:0 6px 3px 0;vertical-align:middle;"></span>{t}</div>'
            for c, t in ((MORE, "more vehicles than the base"), (LESS, "fewer vehicles")))
        key += "".join(
            f'<div><span style="display:inline-block;width:16px;height:4px;'
            f'background:{EDIT_LOOK[k]["color"]};margin:0 6px 3px 0;vertical-align:middle;">'
            f'</span>{EDIT_LOOK[k]["said"]}</div>'
            for k in EDIT_LOOK if any(e["kind"] == k for e in edits))
        if zones is not None:
            key += "".join(
                f'<div><span style="display:inline-block;width:12px;height:10px;'
                f'background:{c};opacity:.5;border:2px solid {c};margin:0 6px 1px 0;'
                f'vertical-align:middle;"></span>{t}</div>'
                for role, (c, t) in ZONE_LOOK.items() if role in set(zones["role"]))
        m.get_root().html.add_child(folium.Element(
            f'<div style="{BOX_STYLE}bottom:24px;left:24px;line-height:1.45;max-width:285px;">'
            f'<b>Change in volume</b>{key}<div style="margin-top:5px;color:#555;font-size:11px;">'
            f'width: the change, both directions; under {CHANGE_MIN} veh/h not drawn</div></div>'))
        before, after = totals["base"]["veh_hours"], totals["scenario"]["veh_hours"]
        add_panel(m, f"Change from {html_escape(base_label)}",
                  [f"{before:,.0f} &rarr; {after:,.0f} vehicle-hours",
                   f"{after - before:+,.0f} ({100 * (after - before) / before:+.1f}%)"])
        return self.save(m, filename)

    @redrawable
    def map_congestion_change(self, links, boundary, edits, base_label, totals,
                              filename=CHANGE_MAP):
        """A capacity or speed scenario's congestion against its base's: the change in each
        link's V/C, green where it eased, red where it worsened, the width its size; the edited
        roads haloed (capacity gold, speed purple). Not volumes: a widened road usually carries
        more traffic, with less congestion, and a volume map would paint it as worse. Under
        MIN_DVOC is grey - below the threshold, not unchanged: an equilibrium nudges thousands
        of links by a little, which is the solver, not a result."""
        drawn = links.copy()
        drawn["geometry"] = (drawn.to_crs(self.metre_crs).simplify(LINK_SIMPLIFY_M)
                             .to_crs("EPSG:4326"))
        drawn["geometry"] = shapely.set_precision(drawn.geometry.values, COORD_GRID)
        name = drawn["name"].fillna("").replace("", "unnamed street")
        edited = {i: e for e in edits for i in e["links"]}

        def band(dv):
            return next((c, said) for top, c, said in DVOC_BANDS if dv <= top)

        def rows(r):
            out = [("class", r.link_type), ("V/C before", f"{r.voc_base:.2f}"),
                   ("V/C after", f"{r.voc:.2f}"),
                   ("V/C change", f"<b style='color:{band(r.dvoc)[0]}'>{r.dvoc:+.2f}</b>"),
                   ("volume before", f"{r.flow_base:,.0f} veh/h"),
                   ("volume after", f"{r.flow:,.0f} veh/h"),
                   ("volume change", f"{r.change:+,.0f} veh/h"
                    + (f" ({100 * r.change / r.flow_base:+.0f}%)" if r.flow_base else ""))]
            if r.link_id in edited:
                out.insert(1, ("edit", edit_said(edited[r.link_id])))
            return out

        m = add_basemap(folium.Map(tiles=None, zoom_snap=0.25))
        m.get_root().header.add_child(folium.Element(TIP_CSS))
        minx, miny, maxx, maxy = drawn.total_bounds
        m.fit_bounds([[miny, minx], [maxy, maxx]])
        self.add_borders(m, boundary, "City limit", weight=1.2, control=False)
        folium.GeoJson(drawn[["geometry"]], style_function=lambda f: {
            "color": "#c9ced4", "weight": 1, "opacity": 0.8}, interactive=False).add_to(
            folium.FeatureGroup(name="The roads", control=False).add_to(m))
        # The edited roads haloed, under their change.
        halo = drawn[drawn["link_id"].isin(edited)].copy()
        halo["colour"] = [EDIT_LOOK[edited[i]["kind"]]["color"] for i in halo["link_id"]]
        folium.GeoJson(halo[["geometry", "colour"]], style_function=lambda f: {
            "color": f["properties"]["colour"], "weight": 11, "opacity": 0.55},
            interactive=False).add_to(folium.FeatureGroup(name="Edited", control=False).add_to(m))
        shown = drawn[(drawn["dvoc"].abs() > MIN_DVOC) | drawn["link_id"].isin(edited)].copy()
        print(f"{len(drawn) - len(shown):,} links moved by {MIN_DVOC:g} V/C or less and stay "
              f"grey; {len(shown):,} drawn")
        biggest = max(float(shown["dvoc"].abs().max()), 1e-6) if len(shown) else 1.0
        shown["colour"] = [band(v)[0] for v in shown["dvoc"]]
        shown["weight"] = 2 + 5 * np.minimum(shown["dvoc"].abs() / biggest, 1)
        shown = shown.loc[shown["dvoc"].abs().sort_values().index]      # biggest on top
        shown["tip"] = [tip_html(html_escape(n), rows(r),
                                 tag=("EDITED" if r.link_id in edited else band(r.dvoc)[1].upper()),
                                 tag_color=(EDIT_LOOK[edited[r.link_id]["kind"]]["color"]
                                            if r.link_id in edited else band(r.dvoc)[0]))
                        for n, r in zip(name[shown.index], shown.itertuples())]
        if len(shown):                     # nothing changed enough: no layer (an empty one fails)
            folium.GeoJson(shown[["geometry", "tip", "colour", "weight"]],
                           style_function=lambda f: {"color": f["properties"]["colour"],
                                                     "weight": f["properties"]["weight"],
                                                     "opacity": 0.95},
                           tooltip=panel_tooltip()).add_to(
                folium.FeatureGroup(name="The change", control=False).add_to(m))

        def swatch(colour, text):
            return (f'<div><span style="display:inline-block;width:16px;height:4px;'
                    f'background:{colour};margin:0 6px 3px 0;vertical-align:middle;"></span>'
                    f'{text}</div>')
        key = "".join(swatch(c, said) for _, c, said in DVOC_BANDS if said != "about the same")
        key += "".join(swatch(EDIT_LOOK[k]["color"], EDIT_LOOK[k]["said"] + " here")
                       for k in ("capacity", "speed") if any(e["kind"] == k for e in edits))
        m.get_root().html.add_child(folium.Element(
            f'<div style="{BOX_STYLE}bottom:24px;left:24px;line-height:1.45;max-width:285px;">'
            f'<b>Congestion change (V/C)</b>{key}<div style="margin-top:5px;color:#555;'
            f'font-size:11px;">width: the size of the change in V/C, the busier direction; '
            f'grey: under {MIN_DVOC:g}, not unchanged</div></div>'))
        before, after = totals["base"]["veh_hours"], totals["scenario"]["veh_hours"]
        add_panel(m, f"Congestion against {html_escape(base_label)}",
                  [f"{before:,.0f} &rarr; {after:,.0f} vehicle-hours",
                   f"{after - before:+,.0f} ({100 * (after - before) / before:+.1f}%)"])
        return self.save(m, filename)

    def save(self, m, filename):
        path = os.path.join(self.maps_dir, filename)
        m.save(path)
        print(f"Map saved: {filename}  ({os.path.getsize(path) / 1e6:.1f} MB)"
              f"\n  location: {os.path.abspath(path)}")
        return m

    @redrawable
    def choropleth(self, frame, value, ramp, tips, layer, legend_title, legend_note, panel_title,
                   panel_lines, filename, borders=None, border_name=None, fmt="{:,.0f}", unit="",
                   layer_panel=True, zoom=12):
        """Polygons shaded by quintiles of one column, with an optional border layer over them.

        `layer_panel=False` leaves out the panel for switching layers, where there is nothing
        worth switching off."""
        drawn = self.for_the_browser(frame)
        shade, labels = quintile_shader(drawn[value], ramp, fmt, unit)
        drawn["fill"] = [shade(v) for v in drawn[value]]
        drawn["tip"] = tips
        m = self.base_map(drawn, zoom)
        folium.GeoJson(
            drawn[["tip", "fill", "geometry"]],
            style_function=lambda f: {"fillColor": f["properties"]["fill"], "color": "#ffffff",
                                      "weight": 0.4, "fillOpacity": 0.8},
            # Hover deepens the fill rather than restroking: neighbours share every border and
            # each draws its own copy, so a restroke would land under whichever is on top.
            highlight_function=lambda f: {"fillOpacity": 1.0, "weight": 1.6, "color": "#1a1a19"},
            tooltip=panel_tooltip(),
        ).add_to(folium.FeatureGroup(name=layer, show=True).add_to(m))
        if borders is not None:
            self.add_borders(m, borders, border_name)
        if layer_panel:
            # Top left, under the zoom buttons: the info panel holds the top right, and a
            # control there would sit behind it.
            folium.LayerControl(collapsed=False, position="topleft").add_to(m)
        add_legend(m, legend_title, ramp, labels, legend_note)
        add_panel(m, panel_title, panel_lines)
        return self.save(m, filename)

    def map_trip_ends(self, zones, od, filename=TRIP_ENDS_MAP):
        """How many trips start and end in each zone - the same for every city.

        `zones` as for `map_zones`, with `zone_number`; `od` the matrix's origin, destination and
        trips. A trip to or from outside the city counts at its end inside. One view at a time:
        a circle per zone whose area is proportional to its trips."""
        starts = od.groupby("origin")["trips"].sum()
        ends = od.groupby("destination")["trips"].sum()
        drawn = self.for_the_browser(zones[["zone", "zone_number", "pop", "geometry"]])
        drawn["starts"] = drawn["zone_number"].map(starts).fillna(0).to_numpy()
        drawn["ends"] = drawn["zone_number"].map(ends).fillna(0).to_numpy()
        drawn["tip"] = [tip_html(r.zone, [("trips starting here", f"{r.starts:,.0f}"),
                                          ("trips ending here", f"{r.ends:,.0f}"),
                                          ("people", f"{r.pop:,.0f}")])
                        for r in drawn.itertuples()]
        m = add_basemap(folium.Map(tiles=None, zoom_snap=0.25))
        m.get_root().header.add_child(folium.Element(TIP_CSS))
        minx, miny, maxx, maxy = drawn.total_bounds
        m.fit_bounds([[miny, minx], [maxy, maxx]])
        folium.GeoJson(
            drawn[["tip", "geometry"]],
            style_function=lambda f: {"fillColor": PLAIN_FILL, "color": "#ffffff", "weight": 0.5,
                                      "fillOpacity": 0.85},
            highlight_function=lambda f: {"fillOpacity": 1.0, "weight": 1.8, "color": "#1a1a19"},
            tooltip=panel_tooltip(),
        ).add_to(folium.FeatureGroup(name="Zones", control=False).add_to(m))
        # Both views on one scale, so a circle means the same number of trips in either.
        biggest = max(drawn["starts"].max(), drawn["ends"].max(), 1)
        for name, column, colour, first in (("Trips starting here", "starts", STARTS, True),
                                            ("Trips ending here", "ends", ENDS, False)):
            # overlay=False makes these radio buttons: one view at a time, not stacked.
            view = folium.FeatureGroup(name=name, overlay=False, show=first).add_to(m)
            for r, point in zip(drawn.itertuples(), zones["centroid"]):
                value = getattr(r, column)
                if value <= 0:
                    continue
                folium.CircleMarker(
                    [point.y, point.x], radius=TRIP_CIRCLE_MAX_PX * (value / biggest) ** 0.5,
                    color="#ffffff", weight=1, fill=True, fill_color=colour, fill_opacity=0.8,
                    tooltip=folium.Tooltip(r.tip, sticky=True)).add_to(view)
        folium.LayerControl(collapsed=False, position="topleft").add_to(m)
        scale = "".join(
            f'<span style="display:inline-block;width:{2 * TRIP_CIRCLE_MAX_PX * f:.0f}px;'
            f'height:{2 * TRIP_CIRCLE_MAX_PX * f:.0f}px;border-radius:50%;background:#8a8f96;'
            f'vertical-align:middle;margin-right:7px;"></span>' for f in (0.25, 0.55, 1.0))
        m.get_root().html.add_child(folium.Element(
            f'<div style="{BOX_STYLE}bottom:24px;left:24px;line-height:1.45;max-width:260px;">'
            f'<b>Trips per zone</b><div style="margin:7px 0 4px;">{scale}</div>'
            f'<div style="color:#555;font-size:11px;">circle area proportional to trips; '
            f'largest {biggest:,.0f}<br><span style="color:{STARTS}">&#9679;</span> starting '
            f'&nbsp; <span style="color:{ENDS}">&#9679;</span> ending</div></div>'))
        add_panel(m, "Trip ends", [f"{od['trips'].sum():,.0f} vehicle trips",
                                   f"{len(zones):,} zones"])
        return self.save(m, filename)

    def map_congestion(self, links, boundary, trips, veh_hours, filename=SIMULATION_MAP,
                       title="Peak-hour car traffic"):
        """Loaded streets coloured by how far past capacity their busier direction runs - the
        same for every city.

        `links` is link_volumes.gpkg: the loaded links with their geometry. `boundary` is the
        city limit, `trips` and `veh_hours` the totals for the panel.

        One layer per road class, ramps included with their road. Residential and unclassified
        streets start switched off: they are most of the network's length but carry little of
        its traffic, so shown together they bury the corridors. Tertiary roads start off too
        (OFF_AT_START): drawing them at once made Quito's map slow to appear. The city limit is
        always drawn."""
        drawn = links[links["link_type"].isin(MAP_ROAD_TYPES + LOCAL_ROAD_TYPES)
                      & (links["flow"] > 0)].copy()
        drawn["geometry"] = (drawn.to_crs(self.metre_crs).simplify(LINK_SIMPLIFY_M)
                             .to_crs("EPSG:4326"))
        drawn["geometry"] = shapely.set_precision(drawn.geometry.values, COORD_GRID)
        drawn["base"] = drawn["link_type"].str.replace("_link", "", regex=False)
        drawn["weight"] = drawn["base"].map(LINE_WEIGHT).fillna(1.4)
        # A ramp is drawn thinner than the road it serves.
        drawn.loc[drawn["link_type"].str.endswith("_link"), "weight"] *= 0.6
        drawn["local"] = drawn["link_type"].isin(LOCAL_ROAD_TYPES)
        main_net = drawn[~drawn["local"]]
        print(f"drawing {len(main_net):,} main-network links, "
              f"{main_net['distance'].sum() / 1000:,.0f} km, and {drawn['local'].sum():,} local "
              f"streets, {drawn.loc[drawn['local'], 'distance'].sum() / 1000:,.0f} km")

        def rows_for(r):
            rows = [("class", r.link_type), ("length", f"{r.distance:,.0f} m")]
            for side, label in (("ab", "A&rarr;B"), ("ba", "B&rarr;A")):
                veh, voc = getattr(r, f"car_{side}"), getattr(r, f"voc_{side}")
                if pd.notna(veh) and veh > 0:
                    rows.append((f"{label} flow", f"{veh:,.0f} veh/h"))
                    rows.append((f"{label} of capacity", f"{100 * voc:,.0f}%"))
            free, now = r.travel_time_ab, r.Congested_Time_AB
            if pd.notna(free) and pd.notna(now) and free > 0:
                rows.append(("time A&rarr;B", f"{now:.1f} min, {now / free:.1f}&times; free flow"))
            rows.append(("link", f"{r.link_id}"))
            return rows

        m = add_basemap(folium.Map(tiles=None, zoom_snap=0.25))
        m.get_root().header.add_child(folium.Element(TIP_CSS))
        minx, miny, maxx, maxy = drawn.total_bounds
        m.fit_bounds([[miny, minx], [maxy, maxx]])
        self.add_borders(m, boundary, "City limit", weight=1.2, control=False)

        def band_of(voc):
            for lo, hi, colour, label in CONGESTION_BANDS:
                if lo <= voc < hi:
                    return colour, label.split(" - ")[-1]
            return CONGESTION_BANDS[-1][2], CONGESTION_BANDS[-1][3].split(" - ")[-1]

        drawn["colour"], drawn["band"] = zip(*[band_of(v) for v in drawn["voc"].fillna(0)])

        # Within a layer the quiet links go first so the jammed ones end up drawn on top.
        layers = []
        for base in ROAD_CLASS_ORDER:
            part = drawn[drawn["base"] == base].sort_values("voc")
            if part.empty:
                continue
            named = part["name"].fillna("unnamed street").replace("", "unnamed street")
            part["tip"] = [tip_html(nm, rows_for(r), tag=r.band, tag_color=r.colour)
                           for nm, r in zip(named, part.itertuples())]
            layer = folium.GeoJson(
                part[["geometry", "tip", "weight", "colour"]],
                name=(f"{base.capitalize()}  ({len(part):,} links, "
                      f"{part['distance'].sum() / 1000:,.0f} km)"),
                show=base not in OFF_AT_START,
                style_function=lambda f: {"color": f["properties"]["colour"],
                                          "weight": f["properties"]["weight"], "opacity": 0.9},
                tooltip=panel_tooltip()).add_to(m)
            layers.append(layer)

        # The control lists layers in the order they were added, and Leaflet draws a layer
        # switched back on above the rest. So each time one comes back, the classes are
        # re-stacked from the smallest road up, which keeps the big roads on top whatever was
        # toggled.
        lifted = ",".join(layer.get_name() for layer in layers)
        m.get_root().script.add_child(folium.Element(
            f'window.addEventListener("load", function () {{ var stack = function () {{ '
            f'[{lifted}].slice().reverse().forEach(function (l) {{ if ({m.get_name()}.hasLayer(l)) '
            f'{{ l.bringToFront(); }} }}); '
            f'}}; stack(); '
            f'{m.get_name()}.on("overlayadd", stack); }});'))

        # Top left, under the zoom buttons: the info panel holds the top right, and the layer
        # names here are long enough that the control would sit behind it.
        folium.LayerControl(collapsed=False, position="topleft").add_to(m)

        swatches = "".join(
            f'<div><span style="display:inline-block;width:16px;height:4px;background:{c};'
            f'margin:0 6px 3px 0;vertical-align:middle;"></span>{lab}</div>'
            for _, _, c, lab in CONGESTION_BANDS)
        m.get_root().html.add_child(folium.Element(
            f'<div style="{BOX_STYLE}bottom:24px;left:24px;line-height:1.45;max-width:285px;">'
            f'<b>Volume over capacity</b>{swatches}</div>'))
        add_panel(m, title,
                  [f"{trips:,.0f} vehicles", f"{veh_hours:,.0f} vehicle-hours"])
        return self.save(m, filename)
