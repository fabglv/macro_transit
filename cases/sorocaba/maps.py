"""Sorocaba's own maps: jobs, external zones, gateways, and the traffic counts."""
import folium
import geopandas as gpd
import shapely

from core.maps import (BOX_STYLE, COORD_GRID, TIP_CSS, add_basemap, add_legend, add_panel,
                       panel_tooltip, redrawable, tip_html)

CIRCLE_FILL, CIRCLE_EDGE = "#6b3fa0", "#3d2159"
CIRCLE_MAX_PX = 18                # radius of the busiest zone; the rest scale by square root
PLAIN_FILL = "#eae7e0"


def zone_tips(drawn):
    """The hover panel both zone maps share."""
    return [tip_html(f"{r.zone} &middot; {r.ap_label}",
                     [("people", f"{r.pop:,.0f}"), ("households", f"{r.households:,.0f}"),
                      ("jobs", f"{r.jobs:,.0f}"),
                      ("&nbsp;&nbsp;in schools", f"{r.jobs_teaching:,.0f}"),
                      ("&nbsp;&nbsp;in health", f"{r.jobs_health:,.0f}"),
                      ("establishments", f"{r.other_estab + r.teaching + r.health:,.0f}"),
                      ("census sectors", f"{r.n_sectors}"),
                      ("area", f"{r.area_km2:.2f} km&sup2;"),
                      ("people per km&sup2;", f"{r.density:,.0f}")],
                     tag=f"{r.size:,.0f}", tag_color="#2a78d6")
            for r in drawn.itertuples()]


def zone_layer(m, drawn, fill_column):
    """The zones as filled polygons carrying the shared panel."""
    folium.GeoJson(
        drawn[["tip", fill_column, "geometry"]],
        style_function=lambda f: {"fillColor": f["properties"][fill_column], "color": "#ffffff",
                                  "weight": 0.6, "fillOpacity": 0.8},
        highlight_function=lambda f: {"fillOpacity": 1.0, "weight": 1.8, "color": "#1a1a19"},
        tooltip=panel_tooltip(),
    ).add_to(m)


@redrawable
def map_jobs(kit, cells, filename="1_jobs.html"):
    """Zones on a plain backdrop, with a circle per zone whose area is proportional to its jobs:
    the zones holding most jobs cover little land, so on a filled map they would be specks."""
    drawn = kit.for_the_browser(cells)
    drawn["fill"] = PLAIN_FILL
    drawn["tip"] = zone_tips(drawn)
    m = kit.base_map(drawn)
    zone_layer(m, drawn, "fill")
    biggest = cells["jobs"].max()
    panels = dict(zip(drawn["zone"], drawn["tip"]))
    for r in cells.itertuples():
        if r.jobs > 0:
            folium.CircleMarker(
                [r.centroid.y, r.centroid.x], radius=CIRCLE_MAX_PX * (r.jobs / biggest) ** 0.5,
                color=CIRCLE_EDGE, weight=0.6, fill=True, fill_color=CIRCLE_FILL,
                fill_opacity=0.75, tooltip=folium.Tooltip(panels[r.zone], sticky=True),
            ).add_to(m)
    m.get_root().html.add_child(folium.Element(
        f'<div style="{BOX_STYLE}bottom:24px;left:24px;line-height:1.45;max-width:270px;">'
        f'<b>Jobs per zone</b><div style="margin-top:3px;color:#555;font-size:11px;">'
        f'circle area proportional to jobs</div></div>'))
    add_panel(m, "Jobs",
              [f"{cells['jobs'].sum():,.0f} jobs in {(cells['jobs'] > 0).sum():,} zones",
               f"busiest zone {biggest:,.0f}",
               '<span style="color:#555;">CEMPRE 2024 jobs placed on CNEFE addresses</span>'])
    return kit.save(m, filename)


def gateway_diamonds(m, gateways, gate_volume, big=(5, 9), with_serves=True, control=True):
    """The gateways as yellow diamonds sized by the traffic the assignment sent through them."""
    group = folium.FeatureGroup(name="Gateways", show=True, control=control).add_to(m)
    pts = gateways.to_crs("EPSG:4326")
    biggest = max((gate_volume["in"] + gate_volume["out"]).max(), 1)
    for g, (_, b) in zip(pts.itertuples(), gate_volume.iterrows()):
        rows = [("into the city", f"{b['in']:,.0f} veh/h"),
                ("out of the city", f"{b['out']:,.0f} veh/h")]
        if with_serves:
            rows += [("fastest way in for", g.serves or "&mdash;"), ("class", g.kind)]
        folium.RegularPolygonMarker(
            [g.geometry.y, g.geometry.x], number_of_sides=4, rotation=45,
            radius=big[0] + big[1] * ((b["in"] + b["out"]) / biggest) ** 0.5,
            color="#1a1a19", weight=1, fill=True, fill_color="#f2c14e", fill_opacity=0.95,
            tooltip=folium.Tooltip(tip_html(g.road, rows, tag=g.label, tag_color="#8a3714"),
                                   sticky=True)).add_to(group)
    return group


# Three colour families: Votorantim, which holds the most commuters and is the one municipality
# split into several zones; the inner band, zones holding a municipality that borders Sorocaba;
# and the outer band beyond. Shades cycle within a family so neighbours rarely share one.
DISPLAY_BANDS = ["Votorantim", "inner", "outer"]
BAND_RAMPS = {"Votorantim": ("#7b3fa0", "#5b2a7d", "#9b6cc0", "#4a1f66"),
              "inner": ("#f2996f", "#eb6834", "#f9c3a8", "#b74a1f"),
              "outer": ("#9ec5f4", "#5598e7", "#cde2fb", "#2a78d6")}
BAND_LEGEND = {"Votorantim": "Votorantim &mdash; split by border crossing",
               "inner": "inner band &mdash; municipalities bordering Sorocaba",
               "outer": "outer band &mdash; beyond them, coarser"}


@redrawable
def map_external_zones(kit, external_zones, by_ext, gateways, gate_volume, boundary, mode,
                       filename="4_external_zones.html"):
    """The external zones as areas, by kind, with the gateways they come in through."""
    drawn = gpd.GeoDataFrame(external_zones.drop(columns=["geometry", "shape"]),
                             geometry=list(external_zones["shape"]), crs=kit.metre_crs)
    drawn = drawn.assign(veh_in=by_ext["in"].to_numpy(), veh_out=by_ext["out"].to_numpy())
    drawn = drawn[~drawn.geometry.is_empty].to_crs("EPSG:4326")
    drawn["geometry"] = shapely.set_precision(drawn.geometry.values, COORD_GRID)
    # Shades cycle within a kind, west to east, so neighbouring zones rarely share one.
    drawn["fill"] = ""
    for band in DISPLAY_BANDS:
        ramp = BAND_RAMPS[band]
        idx = drawn.index[drawn["display_band"] == band]
        order = drawn.loc[idx].geometry.representative_point().x.sort_values().index
        for k, i in enumerate(order):
            drawn.loc[i, "fill"] = ramp[k % len(ramp)]
    drawn["tip"] = [tip_html(r.title, [("band", r.display_band), ("municipalities", r.serves),
                                       ("commuters into Sorocaba", f"{r.commuters_in:,.0f} a day"),
                                       ("commuters out of Sorocaba",
                                        f"{r.commuters_out:,.0f} a day"),
                                       ("car trips in, peak hour", f"{r.veh_in:,.0f}"),
                                       ("car trips out, peak hour", f"{r.veh_out:,.0f}"),
                                       ("fastest gateway", r.main_gateway),
                                       ("gateways it may use", f"{r.gateways_offered}")]
                             + ([("also, beyond the map", f"{r.distant_towns} distant towns")]
                                if r.distant_towns else []),
                             tag=r.label, tag_color=BAND_RAMPS[r.display_band][3])
                    for r in drawn.itertuples()]
    m = kit.base_map(drawn, zoom=9)
    folium.GeoJson(
        drawn[["tip", "fill", "geometry"]],
        style_function=lambda f: {"fillColor": f["properties"]["fill"], "color": "#ffffff",
                                  "weight": 1, "fillOpacity": 0.7},
        highlight_function=lambda f: {"fillOpacity": 0.95, "weight": 2, "color": "#1a1a19"},
        tooltip=panel_tooltip(),
    ).add_to(m)
    kit.add_borders(m, boundary, "Sorocaba", weight=2)
    gateway_diamonds(m, gateways, gate_volume, big=(4, 8), with_serves=False, control=False)
    minx, miny, maxx, maxy = drawn.total_bounds
    m.fit_bounds([[miny, minx], [maxy, maxx]])
    add_legend(m, "External zones", [BAND_RAMPS[b][1] for b in DISPLAY_BANDS],
               [BAND_LEGEND[b] for b in DISPLAY_BANDS],
               "yellow diamonds = gateways, sized by traffic")
    counts = ", ".join(f"{(drawn['display_band'] == b).sum()} {b}" for b in DISPLAY_BANDS)
    add_panel(m, f"External zones: {mode}",
              [f"{len(external_zones)} zones ({counts})",
               f"{drawn['commuters_in'].sum():,.0f} commute in, "
               f"{drawn['commuters_out'].sum():,.0f} commute out a day",
               f"{drawn['veh_in'].sum():,.0f} peak-hour trips in, {drawn['veh_out'].sum():,.0f} out"])
    return kit.save(m, filename)


RATIO_BANDS = [(0.00, 0.50, "#b2182b", "model under half the count"),
               (0.50, 0.85, "#ef8a62", "model 50-85% of the count"),
               (0.85, 1.15, "#4d9221", "within 15%"),
               (1.15, 1.50, "#67a9cf", "model 15-50% over"),
               (1.50, 1e9, "#2166ac", "model over 1.5 times the count")]


@redrawable
def map_counts(kit, compared, boundary, count_hour, filename="5_counts.html"):
    """One circle per count station, coloured by the model's volume over the count."""
    sites = compared.groupby(["site", "source", "road"]).agg(
        x=("x", "mean"), y=("y", "mean"), count=("count", "sum"), model=("model", "sum"),
        km=("km", "mean")).reset_index()
    ll = gpd.GeoSeries(gpd.points_from_xy(sites["x"], sites["y"]), crs=kit.metre_crs).to_crs(4326)
    m = add_basemap(folium.Map(tiles=None))
    m.get_root().header.add_child(folium.Element(TIP_CSS))
    m.fit_bounds([[ll.y.min(), ll.x.min()], [ll.y.max(), ll.x.max()]])
    kit.add_borders(m, boundary, "City limit", weight=1.2)
    for s, pt in zip(sites.itertuples(), ll):
        ratio = s.model / s.count
        colour = next(c for lo, hi, c, lab in RATIO_BANDS if lo <= ratio < hi)
        rows = [("road, km", f"{s.road[:2]}-{s.road[2:]} km {s.km:.1f}")]
        for d in compared[compared["site"] == s.site].sort_values("dir").itertuples():
            rows += [(f"{d.dir.lower()}: counted", f"{d.count:,.0f} veh/h"),
                     (f"{d.dir.lower()}: model", f"{d.model:,.0f} veh/h, GEH {d.geh:.0f}"
                      + (" - calibrates the region's traffic" if getattr(d, "calibrates", False)
                         else ""))]
        rows.append(("counted by", "gantry, by the hour" if s.source == "gantry"
                     else "SAT, by the day, made hourly"))
        folium.CircleMarker(
            [pt.y, pt.x], radius=5 + 9 * (s.count / sites["count"].max()) ** 0.5,
            color="#1a1a19", weight=0.8, fill=True, fill_color=colour, fill_opacity=0.9,
            tooltip=folium.Tooltip(tip_html(s.site.title() if s.source == "gantry" else s.site,
                                            rows, tag=f"model {ratio:.0%} of count",
                                            tag_color=colour), sticky=True)).add_to(m)
    swatches = "".join(
        f'<div><span style="display:inline-block;width:12px;height:12px;border-radius:6px;'
        f'background:{c};margin:0 6px 2px 0;vertical-align:middle;"></span>{lab}</div>'
        for _, _, c, lab in RATIO_BANDS)
    m.get_root().html.add_child(folium.Element(
        f'<div style="{BOX_STYLE}bottom:24px;left:24px;line-height:1.45;max-width:270px;">'
        f'<b>Model volume over count</b>{swatches}<div style="margin-top:5px;color:#555;'
        f'font-size:11px;">circle size = vehicles counted, both directions</div></div>'))
    add_panel(m, f"Light vehicles, {count_hour:02d}:00-{count_hour + 1:02d}:00",
              [f"{len(compared)} counted directions at {len(sites)} stations",
               f"model {compared['model'].sum():,.0f} against {compared['count'].sum():,.0f} "
               f"counted, {compared['model'].sum() / compared['count'].sum():.0%}",
               f"GEH under 5 at {(compared['geh'] < 5).mean():.0%}",
               *([f"the check - the {(~compared['calibrates']).sum()} not calibrating the region's "
                  f"traffic: model {compared.loc[~compared['calibrates'], 'model'].sum() / compared.loc[~compared['calibrates'], 'count'].sum():.0%} "
                  f"of count, GEH under 5 at {(compared.loc[~compared['calibrates'], 'geh'] < 5).mean():.0%}"]
                 if "calibrates" in compared and (~compared["calibrates"]).any() else []),
               '<span style="color:#555;">ARTESP 2026, median weekday</span>'])
    return kit.save(m, filename)
