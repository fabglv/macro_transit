"""The demand: a reproducible synthetic matrix of public-transport trips made in the period.

In a real study it would come from a survey or a mode-choice model. Here it blends three
patterns, each an attraction term times an accessibility term, normalised so the shares mean
what they say:

| pattern | origins | destinations | share |
|---|---|---|---|
| on the network | near a stop | near a stop, pulled to the core | the rest |
| latent corridor | near the unserved axis | near the axis, pulled to the core | CORRIDOR_SHARE |
| the northern suburbs | near the feeder | near a stop, pulled to the core | NORTH_SHARE |

**Accessibility** is a Gaussian decay on the distance to the nearest stop, at BOTH ends of a
trip, because a transit trip needs transit at both of them: a zone at the doorstep counts fully,
one at ACCESS_DECAY_KM about a third, one three times that nothing. It stands in for a
mode-choice model. **Attraction** is a soft bump over the business core, with a floor so no zone
attracts nothing.
"""
import geopandas as gpd
import numpy as np
from shapely.geometry import Point


def nearest_km(points_m, anchors_m):
    """For each point, the straight-line km to the nearest anchor (both in metres)."""
    return np.array([min(p.distance(a) for a in anchors_m) for p in points_m]) / 1000.0


def build_demand(polygons, stops, lines, feeder, corridor, s):
    """The (zones x zones) matrix of trips in the period, in zone-id order, and the zones'
    distance to the nearest stop in km.

    `polygons` are the zones in id order; `stops` the imported stops (a GeoDataFrame); `feeder`
    the key in `lines` of the route the northern-suburbs demand starts from; `corridor` the
    unserved axis as (name, lat, lon, station) tuples. A city without either gives None and a
    share of 0 for it: its demand is all on the network.
    """
    from aequilibrae.utils.geo_utils import metre_crs_for_gdf

    centres = [poly.centroid for poly in polygons]
    zone_lat = np.array([p.y for p in centres])
    zone_lon = np.array([p.x for p in centres])
    metre_crs = metre_crs_for_gdf(stops)
    stops_m = stops.to_crs(metre_crs)
    centres_m = gpd.GeoDataFrame(geometry=centres, crs="EPSG:4326").to_crs(metre_crs)
    zone_stop_km = np.array([float(stops_m.distance(point).min())
                             for point in centres_m.geometry]) / 1000.0

    def anchors(calls):
        return gpd.GeoDataFrame(geometry=[Point(lon, lat) for _, lat, lon, _ in calls],
                                crs="EPSG:4326").to_crs(metre_crs).geometry

    def decay(distance_km):
        return np.exp(-(distance_km / s.ACCESS_DECAY_KM) ** 2)

    access = decay(zone_stop_km)
    attraction = s.ATTRACTION_FLOOR + np.exp(-(((zone_lat - s.CORE_LAT) / s.CORE_SPREAD_LAT) ** 2
                                               + ((zone_lon - s.CORE_LON) / s.CORE_SPREAD_LON)
                                               ** 2))
    on_network = np.outer(access, access * attraction)
    np.fill_diagonal(on_network, 0)              # no intra-zonal trips
    demand = (1 - s.CORRIDOR_SHARE - s.NORTH_SHARE) * on_network / on_network.sum()
    if corridor and s.CORRIDOR_SHARE:
        corridor_access = decay(nearest_km(centres_m.geometry, anchors(corridor)))
        on_corridor = np.outer(corridor_access, corridor_access * attraction)
        np.fill_diagonal(on_corridor, 0)
        demand = demand + s.CORRIDOR_SHARE * on_corridor / on_corridor.sum()
    if feeder and s.NORTH_SHARE:
        line = lines[feeder]
        feeder_access = decay(nearest_km(centres_m.geometry,
                                         anchors(line["stops"] + line.get("stops_back", []))))
        from_north = np.outer(feeder_access, access * attraction)
        np.fill_diagonal(from_north, 0)
        demand = demand + s.NORTH_SHARE * from_north / from_north.sum()
    demand = demand / demand.sum() * s.TARGET_PEAK_TRIPS

    near = zone_stop_km <= s.ACCESS_DECAY_KM
    n = len(polygons)
    print(f"{n} zones; {demand.sum():,.0f} transit trips in the modelled peak.")
    print(f"Distance to the nearest stop: median {np.median(zone_stop_km):.1f} km, "
          f"worst {zone_stop_km.max():.1f} km.")
    print(f"{100 * demand[np.ix_(near, near)].sum() / demand.sum():.0f}% of the matrix is between "
          f"zones within {s.ACCESS_DECAY_KM:g} km of a stop ({near.sum()} of {n} zones).")
    top = np.argsort(demand.sum(axis=0))[::-1][:5]
    print("Strongest attractors (zone: arriving trips):",
          ", ".join(f"{z + 1}: {demand[:, z].sum():,.0f}" for z in top))
    return demand, zone_stop_km
