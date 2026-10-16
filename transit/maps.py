"""The public-transport maps: a design's lines, and a simulation's reach, loads and how full they
run.

| file | function | what it shows | drawn by |
|---|---|---|---|
| network.html | `map_design` | the lines and stops, along the streets or stop to stop | a design |
| 2_coverage.html | `map_coverage` | which zones can walk to a stop, and how far | a simulation |
| loads.html | `map_loads` | passengers per segment and boardings per stop | a simulation |
| 3_capacity.html | `map_capacity` | each segment's share of the places its service offers | a simulation |

They share the road model's look (core/maps.py): the Esri backdrop, the hover panel, the legend
and info boxes. Every function is `@redrawable`: it takes the MapKit first and only plain frames
and numbers after, so a run saves what each map was drawn from in map_data/ and
`core.maps.redraw_maps` can draw it again without running the model.

A simulation's segments are drawn stop to stop - a schematic line is easier to read when the point
of it is the number attached. Where both directions of a route share an
alignment, each is nudged to the right of its own travel direction and drawn in its own shade,
so a route reads as a parallel pair.
"""
import folium
import geopandas as gpd
import numpy as np
import pandas as pd
from branca.element import MacroElement
from jinja2 import Template

from core.maps import TIP_CSS, add_basemap, add_legend, add_panel, panel_tooltip, redrawable, \
    route_class, tip_html

from .gtfs import route_of

DEFAULT_LINE_COLOR = "#555555"
DIRECTION_OFFSET_M = 12      # each direction drawn this far to the right of its travel direction
DETAIL_ZOOM = 15             # a design's map from this zoom: every stop, and each direction apart
LINE_WEIGHT = {"merged": 2.5, "dir": 4}   # px: zoomed out a route is thinner, the map less crowded

# A design's map zoomed out shows each route once and no stops; from DETAIL_ZOOM, each direction
# on its own side and every stop. The page's body carries "far" while zoomed out; a route picked
# out (ROUTE_TOGGLE_JS's "rt-on") shows its stops however far out.
DETAIL_CSS = """<style>
body.far .stop, body:not(.far) .ln.merged, body.far .ln.dir { display:none; }
body.far.rt-focus .stop.rt-on { display:inline; }
</style>"""
DETAIL_JS = """(function (map) {
  function far() { document.body.classList.toggle('far', map.getZoom() < %d); }
  map.on('zoomend', far);
  far();
})(%s);"""
LOAD_OFFSET_M = 40           # wider on the load maps, whose lines are up to twice as thick

# Walking minutes are a magnitude, so the scale is one hue running light to dark - short walk
# pale, long walk deep. The breaks are set from the data (its quartiles land near 4, 7 and 10
# minutes) so all four classes fill up.
WALK_BREAKS = (4, 7, 10)                                            # minutes
WALK_COLORS = ("#cde2fb", "#86b6ef", "#2a78d6", "#104281")          # one hue, light -> dark
NOT_SERVED_COLOR = "#d03b3b"     # a state, not a step on the ramp, so deliberately off-hue

# Share of places used carries a magnitude in the middle and a state at each end. Violet for
# barely-used segments - a service running nearly empty is worth noticing - a blue ramp across
# the working range, then amber for "near capacity" and red for "over capacity": conditions to act
# on, and neither one the model reports on its own. The breaks are a planner's thresholds, not
# quantiles. Amber against red and violet against mid blue were checked in OKLab for normal and
# red-green-deficient vision.
CAPACITY_BREAKS = (20, 50, 85, 100)                     # per cent of places used
CAPACITY_COLORS = ("#4a3aa7", "#86b6ef", "#2a78d6", "#fab219", "#d03b3b")
CAPACITY_LABELS = ("barely used", "", "", "near capacity", "over capacity")


def _txt(value, default="unnamed"):
    return default if value is None or pd.isna(value) else str(value)


def _tooltip(title, rows, tag=None, tag_color="#52514e"):
    """The shared hover panel, for a marker rather than a GeoJson layer."""
    return folium.Tooltip(tip_html(title, rows, tag=tag, tag_color=tag_color), sticky=True)


def _new_map(frame):
    """The backdrop with the panel stylesheet, opened fitted to `frame`."""
    m = add_basemap(folium.Map(tiles=None, zoom_snap=0.25))
    m.get_root().header.add_child(folium.Element(TIP_CSS))
    if len(frame):
        minx, miny, maxx, maxy = frame.to_crs("EPSG:4326").total_bounds
        m.fit_bounds([[miny, minx], [maxy, maxx]])
    return m


def _lighten(hex_color, amount=0.55):
    """Blend a colour towards white. Used for the second direction of each route."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    r, g, b = (int(c + (255 - c) * amount) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def direction_colors(seg, route_col, colors):
    """`seg` with `towards`, `shade` and `color`: the route's colour for one direction, a paler
    version of it for the other.

    A route has one pattern per direction, so a pattern *is* a direction. The terminus comes from
    the pattern's last segment, which makes a legend entry readable ("towards El Labrador" rather
    than "direction 0"); the shade is the pattern's rank within its route.
    """
    from .gtfs import pattern_towards
    shading = (seg[["pattern_id", route_col]].drop_duplicates()
               .sort_values([route_col, "pattern_id"]).reset_index(drop=True))
    shading["towards"] = shading["pattern_id"].map(pattern_towards(seg))
    shading["shade"] = shading.groupby(route_col).cumcount()
    seg = seg.join(shading.set_index("pattern_id")[["towards", "shade"]], on="pattern_id")
    base = [colors.get(r, DEFAULT_LINE_COLOR) for r in seg[route_col]]
    seg["color"] = [c if sh == 0 else _lighten(c) for c, sh in zip(base, seg["shade"])]
    return seg


def offset_to_the_right(gdf, metres, metre_crs):
    """Every line shifted sideways, to the right of its own direction of travel.

    Where both directions of a route run along the same alignment they would otherwise be drawn on
    top of each other - the metro's case, and every two-way street the buses use. Offsetting
    happens in a metre CRS, so `metres` means metres. A line too short or too kinked to offset
    cleanly keeps its original geometry rather than being dropped.
    """
    out = []
    for geom in gdf.to_crs(metre_crs).geometry:
        shifted = None
        if geom is not None and geom.geom_type == "LineString":
            try:
                shifted = geom.offset_curve(-metres)          # negative = right-hand side
            except Exception:
                shifted = None
        ok = shifted is not None and shifted.geom_type == "LineString" and len(shifted.coords) > 1
        out.append(shifted if ok else geom)
    return gpd.GeoSeries(out, crs=metre_crs).to_crs("EPSG:4326").to_numpy()


# Stops several lines share and stations, in greys: findable on a line, quieter than its colour.
SHARED_STOP_RING = "#8a939c"
SHARED_STOP_FILL = "#c9ced4"
STATION_RING = "#5d6873"


def _stop_look(routes_here, color, station=""):
    """A stop's circle: one line's in its colour; one several lines share light grey, ringed
    grey - no line's colour, since it is none's alone; a station larger, white ringed slate."""
    if station:
        return dict(radius=5.5, color=STATION_RING, weight=2, fill_color="#ffffff")
    if len(routes_here) > 1:
        return dict(radius=4, color=SHARED_STOP_RING, weight=1, fill_color=SHARED_STOP_FILL)
    return dict(radius=4, color=color, weight=1, fill_color=color)


def _key_dot(border, weight, size, text, fill="#ffffff"):
    return (f'<div style="margin-top:3px;"><span style="display:inline-block;width:{size}px;'
            f'height:{size}px;border-radius:50%;border:{weight}px solid {border};'
            f'background:{fill};margin:0 6px 1px 1px;vertical-align:middle;"></span>{text}</div>')


# The stops' entries under a map's lines.
STOP_KEY = (_key_dot(SHARED_STOP_RING, 1, 9, "a stop several lines share", SHARED_STOP_FILL)
            + _key_dot(STATION_RING, 2, 11, "a station: change line here")
            + '<div style="color:#555;font-size:11px;">a stop of one line is in its colour</div>')


def _place_name(name):
    """"30 - Avenida São Paulo" -> "Avenida São Paulo": a feed's stop names its route first."""
    route = route_of(name)
    return name[len(route) + 3:] if route and name.startswith(f"{route} - ") else name


def _stop_dots(m, stops, rows_of, radius=3, fill="#222222"):
    """Small dark stops with a white ring, legible on every colour beneath them."""
    for stop in stops.itertuples():
        folium.CircleMarker(
            [stop.geometry.y, stop.geometry.x], radius=radius, color="#ffffff", weight=1.5,
            fill=True, fill_color=fill, fill_opacity=1.0,
            tooltip=_tooltip(_txt(stop.name), rows_of(stop), tag="STOP",
                             tag_color=fill)).add_to(m)


def walk_band_labels():
    """Legend labels derived from WALK_BREAKS, so the two can never drift apart."""
    return ([f"up to {WALK_BREAKS[0]:g} min"]
            + [f"{lo:g} &ndash; {hi:g} min" for lo, hi in zip(WALK_BREAKS, WALK_BREAKS[1:])]
            + [f"over {WALK_BREAKS[-1]:g} min"])


@redrawable
def map_coverage(kit, zones, segments, stops, n_routes, filename="2_coverage.html"):
    """Which zones can reach the network, and how far the walk is.

    Reads no demand and no assignment result: a zone is served when the graph gave it an access
    connector, which depends only on where the stops and the zones are. `zones` are the zone
    polygons with the coverage columns (`served`, `stops_in_reach`, `nearest_stop_km`,
    `nearest_stop_min`). Hovering an unserved zone still gives its distance to the nearest stop,
    which separates a zone 1 km short of a stop from one 6 km up a hillside.
    """
    zones = zones.copy()
    zones["served"] = zones["served"].fillna(False).astype(bool)

    def shade(served, walk):
        # Keyed on `served`, not on a missing walk: every zone has a distance to its nearest stop,
        # so "not served" is a statement about the catchment, not about missing data.
        if not served or pd.isna(walk):
            return NOT_SERVED_COLOR
        for limit, color in zip(WALK_BREAKS, WALK_COLORS):
            if walk <= limit:
                return color
        return WALK_COLORS[-1]

    zones["fill"] = [shade(s, w) for s, w in zip(zones["served"], zones["nearest_stop_min"])]
    zones["tip"] = [tip_html(
        f"Zone {int(r.zone_id)}",
        ([("Stops within reach", f"{int(r.stops_in_reach)}"),
          ("Nearest stop", f"{r.nearest_stop_min:.0f} min walk"),
          ("", f"{r.nearest_stop_km:.2f} km straight line")] if r.served else
         [("On the network",
           f'<b style="color:{NOT_SERVED_COLOR};">no stop within walking distance</b>'),
          ("Nearest stop anyway", f"{r.nearest_stop_min:.0f} min walk"),
          ("", f"{r.nearest_stop_km:.2f} km straight line")])
        + [("Zone id", f"{int(r.zone_id)}")],
        tag="SERVED" if r.served else "NOT SERVED",
        # The badge is a label, not a data mark: a neutral ink keeps it from competing with the
        # fill, which is what carries the walking time.
        tag_color="#52514e" if r.served else NOT_SERVED_COLOR)
        for r in zones.itertuples()]

    m = _new_map(zones)
    folium.GeoJson(
        zones[["tip", "fill", "served", "geometry"]],
        style_function=lambda f: {
            "color": f["properties"]["fill"], "weight": 1.5,
            "dashArray": "5,4" if not f["properties"]["served"] else None,
            "fill": True, "fillColor": f["properties"]["fill"],
            # Served zones carry the ramp, so they need enough opacity for four steps to be told
            # apart over the backdrop; unserved zones are context and stay quiet.
            "fillOpacity": 0.62 if f["properties"]["served"] else 0.16},
        tooltip=panel_tooltip()).add_to(m)
    folium.GeoJson(segments[["geometry"]],
                   style_function=lambda f: {"color": "#222222", "weight": 3,
                                             "opacity": 0.8}).add_to(m)
    # The stops on top: without them the ramp is abstract - a zone is "7 minutes" from something
    # you cannot see.
    _stop_dots(m, stops, lambda s: [("Route", route_of(s.name) or "unknown"),
                                    ("Stop id", f"{int(s.stop_id)}")], radius=3.5)

    add_legend(m, "Walk to the nearest stop",
               list(WALK_COLORS) + [NOT_SERVED_COLOR, "#222222"],
               walk_band_labels() + ["NOT SERVED", "transit lines and stops"],
               "darker = further to walk &middot; hover a zone or a stop for its details")
    n_served = int(zones["served"].sum())
    add_panel(m, "Accessibility", [
        f"{n_served} of {len(zones)} zones within walking distance "
        f"({100 * n_served / len(zones):.0f}%)",
        f"{len(stops)} stops on {n_routes} routes"])
    return kit.save(m, filename)


@redrawable
def map_loads(kit, segments, stops, label, boardings, boarded, journey_min, colors,
              filename="loads.html", max_marker=14):
    """Segment loads and stop boardings for one result: the classic transit load diagram.

    Line width is proportional to the passengers riding a segment, circle area at each stop to
    its boardings - the pair matters: a stop with heavy boardings feeding a thin segment is a
    different story from one feeding a thick one. Each direction is drawn on its own side in its
    own shade, because every load is directional and in a morning peak the two directions of
    one link differ by a factor of two or more.

    Two denominators, on purpose. Width is scaled to the busiest segment anywhere, so thickness
    compares between routes. The hover percentage is scaled to the route's own busiest segment -
    its maximum load point, which sizes its fleet.

    `segments` and `stops` are a result's `segments` and `stops`; `label`, `boardings`,
    `boarded` and `journey_min` its headline numbers, for the panel.
    """
    seg = segments[segments["pt_volume"] > 0].sort_values("pt_volume").copy()
    peak = float(seg["pt_volume"].max()) if len(seg) else 1.0
    seg["share_of_route_peak"] = 100 * seg["pt_volume"] / seg.groupby("route")["pt_volume"] \
        .transform("max")
    seg = direction_colors(seg, "route", colors)
    seg["tip"] = [tip_html(
        f"{r.from_name} &rarr; {r.to_name}",
        [("Route", r.route), ("Direction", f"towards {r.towards}"),
         ("Passengers", f"{r.pt_volume:,.0f}"),
         ("Share of this route's peak", f"{r.share_of_route_peak:.0f}%"),
         ("Length", f"{r.distance / 1000:.2f} km"), ("Segment", r.segment)],
        tag=f"{r.route} &rarr; {r.towards}", tag_color=r.color)
        for r in seg.itertuples()]
    # Offset last, so `distance` and the tooltips describe the real segment.
    seg = seg.set_geometry(offset_to_the_right(seg, LOAD_OFFSET_M, kit.metre_crs),
                           crs="EPSG:4326")
    seg["cls"] = [route_class(r) for r in seg["route"]]

    m = _new_map(seg)
    folium.GeoJson(
        seg[["tip", "color", "pt_volume", "cls", "geometry"]],
        style_function=lambda f: {
            "color": f["properties"]["color"], "className": f["properties"]["cls"],
            "weight": 2 + 10 * (f["properties"]["pt_volume"] / peak), "opacity": 0.85},
        tooltip=panel_tooltip()).add_to(m)

    # A feed's stop belongs to one route, so lines calling at one place are several stops on one
    # spot: drawn as one circle, its boardings summed, light grey if several lines share it.
    places = {}
    for r in stops.itertuples():
        at = (round(r.geometry.y, 5), round(r.geometry.x, 5))
        places.setdefault(at, []).append(r)
    busiest = max((sum(max(r.boarding, 0) for r in here) for here in places.values()),
                  default=1.0)
    for (lat, lon), here in places.items():
        routes_here = list(dict.fromkeys(route_of(r.name) or "unknown" for r in here))
        boarding = sum(max(r.boarding, 0) for r in here)
        color = colors.get(routes_here[0], DEFAULT_LINE_COLOR)
        shared = len(routes_here) > 1
        radius = 3 + max_marker * np.sqrt(boarding / busiest) if busiest > 0 else 3
        rows = ([("Lines", ", ".join(routes_here))] if shared else [("Line", routes_here[0])])
        rows += [("Boardings", f"{boarding:,.0f}"),
                 ("Alightings", f"{sum(r.alighting for r in here):,.0f}")]
        if shared:
            rows += [(f"&nbsp;&nbsp;{route_of(r.name) or 'unknown'}", f"{r.boarding:,.0f} board")
                     for r in here]
        rows += [("Stop id", ", ".join(f"{int(r.stop_id)}" for r in here))]
        folium.CircleMarker(
            [lat, lon], radius=radius, color=SHARED_STOP_RING if shared else "#333333",
            weight=1, fill=True,
            fill_color=SHARED_STOP_FILL if shared else color, fill_opacity=0.85,
            class_name=route_class(*routes_here),
            tooltip=_tooltip(_txt(_place_name(here[0].name)), rows, tag="STOP",
                             tag_color=SHARED_STOP_RING if shared else color)).add_to(m)

    shown = seg.drop_duplicates("pattern_id").sort_values(["route", "shade"])
    add_legend(m, "Passenger loads", list(shown["color"]),
               [f"{r.route} &rarr; {r.towards}" for r in shown.itertuples()],
               "line width &prop; passengers riding &middot; circle area &prop; boardings"
               "<br>pale = the other direction &middot; each is drawn on its own side"
               "<br>a white circle: a stop several lines share",
               toggles=list(shown["route"]))
    # One line for boardings and boarding trips: side by side they invite "aren't those the
    # same?", and they differ only by transfers - so the ratio belongs next to them.
    add_panel(m, label, [
        f"{boardings:,.0f} boardings by {boarded:,.0f} trips "
        f"({boardings / max(boarded, 1):.2f} each)",
        f"peak segment load: {peak:,.0f}",
        f"average journey: {journey_min:.1f} min"])
    return kit.save(m, filename)


@redrawable
def map_capacity(kit, segments, stops, filename="3_capacity.html"):
    """How full each segment is, as a share of the places its service offers.

    The companion to the loads map: volumes say where the passengers are; this says how hard
    each service is working for them. A metro segment carrying 1,500 people on 13,440 places is
    emptier than a bus segment carrying 150 on 2,400, and only this map will say so. Colour is
    the share of places used, width still the passengers - the pairing the road model uses for
    volume over capacity.

    **The model does not compute any of this**: the assignment is uncapacitated, and the places
    are worked out in `onboard_by_segment` from the service the feed declares. Nothing here fed
    back into the route choice.
    """
    seg = segments[segments["pt_volume"] > 0].sort_values("pct_capacity").copy()
    if not len(seg):
        print("No segment carries any passengers.")
        return None
    widest = float(seg["pt_volume"].max())

    def band(pct):
        for limit, color in zip(CAPACITY_BREAKS, CAPACITY_COLORS):
            if pct <= limit:
                return color
        return CAPACITY_COLORS[-1]

    seg["fill"] = [band(p) for p in seg["pct_capacity"]]
    seg["tip"] = [tip_html(
        f"{r.from_name} &rarr; {r.to_name}",
        [("Route", r.route), ("Capacity used", f"<b>{r.pct_capacity:.1f}%</b>"),
         ("Passengers", f"{r.pt_volume:,.0f}"), ("Places on offer", f"{r.places:,.0f}"),
         ("Length", f"{r.distance / 1000:.2f} km"), ("Segment", r.segment)],
        tag=f"{r.pct_capacity:.0f}% full", tag_color=r.fill)       # grey if white won't read
        for r in seg.itertuples()]
    seg = seg.set_geometry(offset_to_the_right(seg, LOAD_OFFSET_M, kit.metre_crs),
                           crs="EPSG:4326")

    m = _new_map(seg)
    folium.GeoJson(
        seg[["tip", "fill", "pt_volume", "geometry"]],
        style_function=lambda f: {
            "color": f["properties"]["fill"],
            "weight": 2 + 9 * (f["properties"]["pt_volume"] / widest), "opacity": 0.9},
        tooltip=panel_tooltip()).add_to(m)
    _stop_dots(m, stops, lambda s: [("Boardings", f"{s.boarding:,.0f}")])

    ranges = ([f"under {CAPACITY_BREAKS[0]:g}%"]
              + [f"{lo:g} &ndash; {hi:g}%" for lo, hi in zip(CAPACITY_BREAKS, CAPACITY_BREAKS[1:])]
              + [f"over {CAPACITY_BREAKS[-1]:g}%"])
    # The status bands are named as well as bounded: a colour standing for a condition should not
    # rely on the reader inferring the condition from a number.
    add_legend(m, "Share of places used", list(CAPACITY_COLORS),
               [f"{r} &mdash; {n}" if n else r for r, n in zip(ranges, CAPACITY_LABELS)],
               "width still &prop; passengers &middot; each direction on its own side<br>both "
               "ends are flagged: violet is nearly empty, amber and red nearly or over full")
    add_panel(m, "Share of places used", [
        f"fullest segment: <b>{seg['pct_capacity'].max():.1f}%</b> of its places",
        f"median segment: {seg['pct_capacity'].median():.1f}%",
        f'<span style="color:#555;">{int((seg["pct_capacity"] > 100).sum())} segment(s) over '
        f'capacity</span>'])
    return kit.save(m, filename)


class _MapScript(MacroElement):
    """Script run once its map exists: folium writes a map's children after the map itself."""

    def __init__(self, js):
        super().__init__()
        self._template = Template("{% macro script(this, kwargs) %}" + js + "{% endmacro %}")


@redrawable
def map_design(kit, features, label, n_lines, filename="network.html"):
    """A design's lines and stops, before any assignment: along the streets, or stop to stop.

    `features` are design.build's lines.geojson features - each route and direction twice, as
    `shape` "streets" and "straight". Each direction is drawn to the right of its own travel, so
    the two directions of a route do not lie on each other. A stop whose platform the feed
    groups with another route's (a station) is drawn larger and ringed dark: the places a
    passenger can change line by design."""
    from shapely.geometry import LineString, MultiLineString

    frame = gpd.GeoDataFrame([f["properties"] for f in features],
                             geometry=[LineString(f["geometry"]["coordinates"]) for f in features],
                             crs="EPSG:4326")
    frame["geometry"] = offset_to_the_right(frame, DIRECTION_OFFSET_M, kit.metre_crs)
    # The route's colour outward, a paler one back: features come outward first, per shape.
    frame["color"] = [c if back == 0 else _lighten(c) for c, back in
                      zip(frame["color"], frame.groupby(["route", "shape"]).cumcount())]
    frame["tip"] =[tip_html(f"{r.route} &rarr; {r.towards}", [
        ("Line", _txt(r.name)), ("Mode", r.mode),
        ("Service", _txt(getattr(r, "service", None) or f"every {r.headway_min:g} min")),
        ("Speed", f"{r.speed_kmh:g} km/h"), ("Stops", f"{len(r.stops)}")]
        + ([("Along the streets", f"{r.km_streets:.1f} km")] if pd.notna(r.km_streets) else []),
        tag=r.route, tag_color=r.color) for r in frame.itertuples()]
    frame["cls"] = [route_class(r) + " ln dir" for r in frame["route"]]
    # Zoomed out, a route once: both directions as they run, not set apart, in its colour.
    merged = []
    for (route, shape), group in pd.DataFrame([f["properties"] for f in features]).assign(
            coords=[f["geometry"]["coordinates"] for f in features]).groupby(
            ["route", "shape"], sort=False):
        r = group.iloc[0]
        merged.append({"route": route, "shape": shape, "color": r["color"],
                       "cls": route_class(route) + " ln merged",
                       "tip": tip_html(f"{route}: {_txt(r['name'])}", [
                           ("Mode", r["mode"]),
                           ("Service", _txt(r.get("service") or f"every {r['headway_min']:g} min")),
                           ("Towards", " / ".join(group["towards"])),
                           ("Zoom in", "to see each direction and every stop")],
                           tag=route, tag_color=r["color"]),
                       "geometry": MultiLineString([c for c in group["coords"] if len(c) > 1])})
    merged = gpd.GeoDataFrame(merged, geometry="geometry", crs="EPSG:4326")
    m = _new_map(frame)
    m.get_root().header.add_child(folium.Element(DETAIL_CSS))
    m.add_child(_MapScript(DETAIL_JS % (DETAIL_ZOOM, m.get_name())))
    for shape, name, first in (("streets", "Along the streets", True),
                               ("straight", "Stop to stop", False)):
        view = folium.FeatureGroup(name=name, overlay=False, show=first).add_to(m)
        part = pd.concat([merged[merged["shape"] == shape], frame[frame["shape"] == shape]])
        folium.GeoJson(gpd.GeoDataFrame(part[["tip", "color", "cls", "geometry"]],
                                        geometry="geometry", crs="EPSG:4326"),
                       style_function=lambda f: {"color": f["properties"]["color"],
                                                 "weight": LINE_WEIGHT[f["properties"]["cls"]
                                                                       .split()[-1]],
                                                 "opacity": 0.85,
                                                 "className": f["properties"]["cls"]},
                       tooltip=panel_tooltip()).add_to(view)
    stops, serving = {}, {}
    for f in features:
        if f["properties"]["shape"] != "streets":
            continue
        for name, lat, lon, station in f["properties"]["stops"]:
            at = (round(lat, 6), round(lon, 6))
            stops.setdefault(at, (name, station, f["properties"]["route"],
                                  f["properties"]["color"]))
            serving.setdefault(at, []).append(f["properties"]["route"])
    layer = folium.FeatureGroup(name="Stops", control=False).add_to(m)
    for (lat, lon), (name, station, route, color) in stops.items():
        routes_here = list(dict.fromkeys(serving[(lat, lon)]))
        rows = [("Lines" if len(routes_here) > 1 else "Line", ", ".join(routes_here))] + (
            [("Station", f"{station}: change line here")] if station else [])
        look = _stop_look(routes_here, color, station)
        folium.CircleMarker([lat, lon], fill=True, fill_opacity=1.0, **look,
                            class_name=route_class(*routes_here)
                            + " stop",
                            tooltip=_tooltip(name, rows, tag="STATION" if station else "STOP",
                                             tag_color=look["color"])
                            ).add_to(layer)
    folium.LayerControl(collapsed=False, position="topleft").add_to(m)
    routes = frame.drop_duplicates("route")
    add_legend(m, "The lines", list(routes["color"]), list(routes["route"]),
               extra=STOP_KEY, toggles=list(routes["route"]),
               note="zoomed out, each line once and no stops: zoom in for each direction and "
                    "the stops")
    add_panel(m, label, [f"{n_lines} lines, {len(stops)} stops"])
    return kit.save(m, filename)
