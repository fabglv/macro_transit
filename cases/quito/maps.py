"""Quito's own map: land use (the floor area that is not housing).

The backdrop is the shared Esri canvas (CARTO's Positron, which the notebook used, now asks for
an API key).
"""
import folium

from core.maps import (BOX_STYLE, TIP_CSS, add_basemap, add_panel, panel_tooltip, redrawable,
                       tip_html)


def _map(kit, drawn, zoom=11):
    whole = drawn.geometry.union_all().centroid
    m = folium.Map(location=[whole.y, whole.x], zoom_start=zoom, tiles=None)
    add_basemap(m)
    m.get_root().header.add_child(folium.Element(TIP_CSS))
    return m


NOTHING_GREY = "#b8b8b3"          # no buildings, or nobody living there
# Housing is pale so the four activity classes carry the map, but not so pale that it merges
# with the grey used for "nothing here".
CLASS_COLORS = {"residential": "#f0dcb0", "mixed/commercial": "#D55E00",
                "facilities": "#0072B2", "industrial": "#CC79A7", "heritage core": "#009E73",
                "no buildings": NOTHING_GREY}
PLAIN_FILL = "#eae7e0"            # the quiet backdrop the circles sit on
CIRCLE_FILL, CIRCLE_EDGE = "#6b3fa0", "#3d2159"
CIRCLE_MAX_PX = 17                # radius of the busiest zone; the rest scale by square root


@redrawable
def map_land_use(kit, cells, classes, filename="1_land_use.html"):
    """Zones by the floor area they hold that is not housing: a circle per zone whose area is
    proportional to it, since the zones holding most of it cover little land."""
    drawn = kit.for_the_browser(cells)
    # itertuples() rewrites any column name that is not a valid identifier, so rename first and
    # keep the mapping rather than guessing what it became.
    safe = {c: c.replace("/", "_").replace(" ", "_") for c in classes}

    def rows_for(r):
        rows = [("zone", r.zone), ("people", f"{r.pop:,.0f}"), ("dwellings", f"{r.dwellings:,.0f}")]
        rows += [(c, f"{getattr(r, safe[c]) / 1000:,.1f}k m²")
                 for c in classes if getattr(r, safe[c]) > 0]
        rows.append(("<b>not housing</b>", f"<b>{r.activity_m2 / 1000:,.1f}k m²</b>"))
        return rows

    drawn = drawn.rename(columns=safe)
    drawn["tip"] = [tip_html(r.nom_par, rows_for(r), tag=r.dominant,
                             tag_color=CLASS_COLORS[r.dominant]) for r in drawn.itertuples()]
    m = _map(kit, drawn)
    folium.GeoJson(
        drawn[["tip", "geometry"]],
        style_function=lambda f: {"fillColor": PLAIN_FILL, "color": "#ffffff", "weight": 0.5,
                                  "fillOpacity": 0.85},
        highlight_function=lambda f: {"fillOpacity": 1.0, "weight": 1.8, "color": "#1a1a19"},
        tooltip=panel_tooltip(),
    ).add_to(m)

    # A circle whose area - not radius - is proportional to the floor area. The circles sit over
    # the zones, so they carry the same panel rather than swallowing the hover.
    biggest = drawn["activity_m2"].max()
    panels = dict(zip(drawn["zone"], drawn["tip"]))
    for r in cells.itertuples():
        if r.activity_m2 <= 0:
            continue
        folium.CircleMarker(
            [r.centroid.y, r.centroid.x], radius=CIRCLE_MAX_PX * (r.activity_m2 / biggest) ** 0.5,
            color=CIRCLE_EDGE, weight=0.6, fill=True, fill_color=CIRCLE_FILL, fill_opacity=0.75,
            tooltip=folium.Tooltip(panels[r.zone], sticky=True),
        ).add_to(m)

    scale = "".join(
        f'<span style="display:inline-block;width:{2 * CIRCLE_MAX_PX * f:.0f}px;'
        f'height:{2 * CIRCLE_MAX_PX * f:.0f}px;border-radius:50%;background:{CIRCLE_FILL};'
        f'opacity:0.75;border:1px solid {CIRCLE_EDGE};vertical-align:middle;'
        f'margin-right:7px;"></span>' for f in (0.25, 0.55, 1.0))
    m.get_root().html.add_child(folium.Element(
        f'<div style="{BOX_STYLE}bottom:24px;left:24px;line-height:1.45;max-width:250px;">'
        f'<b>Floor area that is not housing</b><div style="margin:7px 0 2px;">{scale}</div>'
        f'</div>'))
    add_panel(m, "Floor area by use",
              [f"{drawn['built_m2'].sum() / 1e6:,.1f} km² over {len(drawn):,} zones",
               f"{100 * drawn['activity_m2'].sum() / drawn['built_m2'].sum():.0f}% of it is not "
               f"housing"])
    return kit.save(m, filename)
