"""What a public-transport run writes out, in formats that open in QGIS or pandas on their own.

The AequilibraE project holds the network, the zones and the imported feed, but none of the
results - the assignment lives in memory. What goes out instead, into exports/:

| file | what it holds |
|---|---|
| `zones.gpkg` | the zones: centroid, served or not, walk to the nearest stop, trips made |
| `segments.csv` | one row per segment and direction: passengers, places offered, share used |
| `stops.csv` | every stop: route, position, boardings and alightings |
| `skims.csv` | every O-D pair with demand: trips and the journey's parts, in minutes |
| `gtfs_feed.zip` | the feed the run imported (written before the import) |
| `assumptions.csv`, `parameters.csv` | the assumptions and the method settings, by group |

And summary.json beside them: the headline numbers, formatted for reading and raw.
"""
import json
import time

import geopandas as gpd
import numpy as np
import pandas as pd

from .gtfs import route_of

# The skims written in minutes; `transfers` and `boardings` are counts.
MINUTE_SKIMS = ["trav_time", "in_vehicle_trav_time", "waiting_time", "access_trav_time",
                "egress_trav_time", "transfer_walk_time"]

# summary.json's lines, in order: the page shows them as they are.
HEADLINE = ["trips in the matrix", "trips that can reach the network", "board a vehicle",
            "walk the whole way", "boardings per boarding trip", "passenger-hours",
            "average journey", "riding", "waiting", "walking", "transfers per trip"]


def zones_layer(ex, zones, coverage, demand):
    """zones.gpkg: the zone polygons with their coverage and the trips they make.

    `served` is whether the graph joined the zone to at least one stop; `walk_min` and
    `nearest_stop_km` are the straight-line walk from its centroid to the nearest stop, for every
    zone - served or not."""
    out = zones[["zone_id", "geometry"]].merge(coverage.reset_index(), on="zone_id", how="left")
    centres = out.geometry.centroid          # in degrees, as the demand and coverage take them
    out["centroid_lon"] = centres.x.to_numpy()
    out["centroid_lat"] = centres.y.to_numpy()
    out["served"] = out["served"].fillna(False).astype(bool)
    out = out.rename(columns={"nearest_stop_min": "walk_min"})
    index = out["zone_id"].to_numpy() - 1
    out["trips_produced"] = demand.sum(axis=1)[index]
    out["trips_attracted"] = demand.sum(axis=0)[index]
    columns = ["zone_id", "centroid_lon", "centroid_lat", "served", "stops_in_reach", "walk_min",
               "nearest_stop_km", "trips_produced", "trips_attracted", "geometry"]
    out = gpd.GeoDataFrame(out[columns], geometry="geometry", crs="EPSG:4326")
    ex.layer(out, "zones.gpkg", "zones")
    return out


def segments_table(ex, segments):
    """segments.csv: one row per segment of one pattern - a pattern is one direction of a route,
    named by the stop it runs towards. `pt_volume` is the passengers riding it in the period,
    `places` what the service offers in the same period, `pct_capacity` the share used."""
    seg = segments.copy()
    from .gtfs import pattern_towards
    seg["direction"] = "towards " + seg["pattern_id"].map(pattern_towards(seg))
    seg["length_km"] = seg["distance"] / 1000.0
    out = seg[["route", "pattern_id", "direction", "line_seg_idx", "from_name", "to_name",
               "segment", "pt_volume", "places", "pct_capacity", "length_km"]]
    out = out.sort_values(["route", "pattern_id", "line_seg_idx"]).round(
        {"pt_volume": 1, "places": 0, "pct_capacity": 2, "length_km": 3})
    ex.csv(out, "segments.csv", index=False)


def segments_layer(ex, segments, metre_crs):
    """segments.geojson: every segment as a straight line from stop to stop - the load map's
    lines - each direction moved to the right of its own travel, so the two directions of a
    route lie side by side. The Compare page draws two simulations' changes on these; plain
    GeoJSON, so the page needs nothing beyond the standard library. (The lines along the
    streets are the line design's: transit/design.py.)"""
    from .maps import LOAD_OFFSET_M, offset_to_the_right

    seg = segments[["segment", "route", "geometry"]].copy()
    seg["geometry"] = offset_to_the_right(seg, LOAD_OFFSET_M, metre_crs)
    seg = gpd.GeoDataFrame(seg, geometry="geometry", crs="EPSG:4326")
    seg["geometry"] = seg.to_crs(metre_crs).simplify(5).to_crs("EPSG:4326")
    path = ex.path("segments.geojson")
    seg.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=6)
    ex.written("segments.geojson")


def stops_table(ex, stops):
    """stops.csv: every stop with its boardings and alightings from and to the street (a
    passenger changing service boards on a transfer edge, not counted here)."""
    out = pd.DataFrame({
        "stop": stops["stop"].astype(str), "stop_id": stops["stop_id"].astype(str),
        "name": stops["name"], "route": [route_of(n) for n in stops["name"]],
        "station": stops["parent_station"].fillna(""),
        "lat": stops.geometry.y.round(6), "lon": stops.geometry.x.round(6),
        "boardings": stops["boarding"].round(1), "alightings": stops["alighting"].round(1)})
    ex.csv(out.sort_values(["route", "name"]), "stops.csv", index=False)


def skims_table(ex, result):
    """skims.csv: every O-D pair with demand, by zone.

    Times are in minutes, over a pair's whole strategy. `trav_time` is the generalised cost the
    algorithm minimises and includes the transfer penalty; `journey_time` is the sum of the real
    parts - the ride, the wait, the walks. `boarding_share` is the share of its trips that board
    (a strategy may split); `transfers` and `boardings` are per trip. A pair the network cannot
    carry (`reachable` 0) has blank times. A reachable pair with a boarding share of 0 walks the
    whole way."""
    demand = result.demand
    rows, cols = np.nonzero(demand > 0)
    reachable = result.reached[rows, cols]
    out = pd.DataFrame({"origin": result.zone_ids[rows], "destination": result.zone_ids[cols],
                        "trips": demand[rows, cols].round(3), "reachable": reachable.astype(int)})
    parts = {"waiting_time": result.pair_wait()}
    for name in MINUTE_SKIMS:
        values = parts[name] if name in parts else result.skim(name)
        out[name] = np.where(reachable, values[rows, cols] / 60.0, np.nan).round(2)
    out.insert(out.columns.get_loc("in_vehicle_trav_time"), "journey_time",
               np.where(reachable, result.pair_journey()[rows, cols] / 60.0, np.nan).round(2))
    for name, values in (("boarding_share", result.boarding_share),
                         ("transfers", result.pair_transfers()), ("boardings", result.skim("boards"))):
        out[name] = np.where(reachable, values[rows, cols], np.nan).round(3)
    ex.csv(out, "skims.csv", index=False)
    print(f"    {len(out):,} pairs carry demand, {int(out['reachable'].sum()):,} of them "
          f"reachable; "
          f"{int(((out['boarding_share'] == 0) & (out['reachable'] == 1)).sum()):,} reachable "
          f"pairs never board")


def write_summary(path, city, city_key, design, changes, result, started, simulated=None,
                  operations=None):
    """summary.json: the headline, formatted like the run's read-out, and the raw totals - and
    which design was simulated: its name, label, description and changes in words (none for the
    baseline). `city_key` is the city's folder name ("quito"), which every simulation of the
    city shares, so the pages can tell which simulations compare."""
    r = result
    served = max(r.served_demand, 1)
    trips = float(r.demand.sum())
    headline = [
        ["trips in the matrix", f"{trips:,.0f}"],
        ["trips that can reach the network",
         f"{r.served_demand:,.0f} ({100 * r.served_demand / trips:.0f}%)"],
        ["board a vehicle", f"{r.boarded_demand:,.0f} ({100 * r.boarded_demand / served:.0f}%)"],
        ["walk the whole way",
         f"{r.walk_only_demand:,.0f} ({100 * r.walk_only_demand / served:.0f}%)"],
        ["boardings per boarding trip",
         f"{r.boardings / max(r.boarded_demand, 1):.2f} ({r.boardings:,.0f} boardings)"],
        ["passenger-hours", f"{r.passenger_hours:,.0f}"],
        ["average journey", f"{r.journey_time:.1f} min"],
        ["riding", f"{r.in_vehicle_time:.1f} min"],
        ["waiting", f"{r.waiting_time:.1f} min"],
        ["walking", f"{r.walking_time:.1f} min"],
        ["transfers per trip", f"{r.transfers:.2f}"],
    ]
    assert [label for label, _ in headline] == HEADLINE
    totals = {"trips": trips, "served": r.served_demand, "boarded": r.boarded_demand,
              "walk_only": r.walk_only_demand, "boardings": r.boardings,
              "passenger_hours": r.passenger_hours, "journey_min": r.journey_time,
              "riding_min": r.in_vehicle_time, "waiting_min": r.waiting_time,
              "walking_min": r.walking_time, "transfers": r.transfers}
    summary = {"kind": "transit", "city": city, "city_key": city_key,
               "design": {"name": design["name"], "label": design["label"],
                          "description": design["description"], "changes": changes},
               "finished": time.strftime("%Y-%m-%d %H:%M"),
               "minutes": round((time.time() - started) / 60, 1), "headline": headline,
               "totals": {k: float(v) for k, v in totals.items()},
               # What it ran (transit/options.py), and what its design takes to run that day.
               "simulated": simulated or {}, "operations": operations or {}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1, ensure_ascii=False)
    print(f"summary written: {path}")
