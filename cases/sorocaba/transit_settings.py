"""Sorocaba's public transport: every value that is decided rather than measured.

What turns OSM's routes into lines (transit/osm_lines.py), how a bus is matched onto the
streets, what a line takes to run - and a simulation's zones and demand, both SYNTHETIC: a grid
over the built-up area and a gravity-style matrix drawn to the stops and the centre, as Quito's.
Rough guesses to see the network carry passengers, not estimates of Sorocaba's travel.

    python run.py sorocaba --transit
"""
from core.settings import Assumptions

ASSUMED = Assumptions()
assume = ASSUMED.assume
setting = ASSUMED.setting

# Where the results page lists these (the groups exist in core/parameter_groups.py).
ASSUMED.groups.update(
    {name: "Zone parameters" for name in
     ["COARSE_GRID", "TRIM_SOUTH_NORTH_EAST", "SPLIT", "MIN_ROAD_KM"]}
    | {name: "Network parameters" for name in
       ["MATCHED_ROUTE_TYPES", "MATCH_RADIUS_M", "MAX_STATION_SPREAD_M", "CITY_SHARE",
        "TERMINAL_RADIUS_M", "OSM_JUMP_KM", "OSM_JUMP_FACTOR", "OSM_ENDS_KM",
        "OSM_LENGTH_RATIO", "OSM_MIN_STOPS"]}
    | {name: "Transit service parameters" for name in
       ["PERIOD_HOURS", "CONNECTOR_METHOD", "GRAPH_TRANSFERS", "TRANSIT_ALGORITHM",
        "LAYOVER_SHARE", "LAYOVER_MIN_S", "OSM_HEADWAY_MIN", "OSM_SPEED_KMH", "OSM_DWELL_S",
        "OSM_CAPACITY"]}
    | {name: "Transit demand parameters" for name in
       ["TARGET_PEAK_TRIPS", "ACCESS_DECAY_KM", "CORRIDOR_SHARE", "NORTH_SHARE", "CORE_CENTRE",
        "CORE_SPREAD_DEG", "ATTRACTION_FLOOR"]}
    | {name: "Walking parameters" for name in
       ["WALKING_SPEED", "SAME_STATION_M", "TRANSFER_WALK_M", "WALK_ROUTE_MAX_STRAIGHT_M",
        "TRANSFER_PENALTY_S", "WAIT_TIME_FACTOR", "ACCESS_RADIUS_M"]})

# --- The lines from OpenStreetMap (transit/osm_lines.py) -----------------------------------------
CITY_SHARE = setting(
    "CITY_SHARE", 0.8, "share of a route's stops inside the city limit for it to be a city line; "
                       "fewer, and it is a regional route passing through")
TERMINAL_RADIUS_M = assume(
    "TERMINAL_RADIUS_M", 150, "m", "a stop this close to a mapped terminal (amenity=bus_station) "
                                   "is one of its platforms: passengers change line there")
# OSM's route relations have slips: a stop of the far end listed first or last, a stretch of
# another route inside one, a return mapped only in part. For a demo network that looks right,
# not a faithful copy of Urbes's.
OSM_JUMP_KM = setting(
    "OSM_JUMP_KM", 1.5, "km between two stops in a row, and OSM_JUMP_FACTOR times the route's "
    "usual spacing: further is a slip in the mapping, not a leg - the route keeps its longest "
    "piece without one")
OSM_JUMP_FACTOR = setting(
    "OSM_JUMP_FACTOR", 6, "times a route's median stop spacing: see OSM_JUMP_KM")
OSM_ENDS_KM = setting(
    "OSM_ENDS_KM", 1.5, "km between where one direction ends and the other starts: further, "
    "or lengths more than OSM_LENGTH_RATIO apart, and the two are not one line's - it keeps the "
    "longer and runs back by its stops reversed")
OSM_LENGTH_RATIO = setting(
    "OSM_LENGTH_RATIO", 1.6, "the longer direction over the shorter: see OSM_ENDS_KM")
OSM_MIN_STOPS = setting(
    "OSM_MIN_STOPS", 5, "stops a line keeps after that cleaning, or it is left out")
OSM_HEADWAY_MIN = assume(
    "OSM_HEADWAY_MIN", {"bus": 20, "BRT": 10}, "min between vehicles, a line OSM gives no "
    "interval for", "ASSUMED: OSM has the BRT's intervals (10-12 min) and one line's; the rest "
                    "are a guess to replace with Urbes's timetables")
OSM_SPEED_KMH = assume(
    "OSM_SPEED_KMH", {"bus": 18, "BRT": 22}, "km/h along the streets",
    "ASSUMED: a city bus's commercial speed in mixed traffic; the BRT's on its corridors")
OSM_DWELL_S = assume("OSM_DWELL_S", 25, "s at a stop", "ASSUMED")
OSM_CAPACITY = assume(
    "OSM_CAPACITY", {"bus": 80, "BRT": 160}, "places a vehicle",
    "ASSUMED: a standard city bus; the BRT's articulated buses - check against the fleet")

# --- Matching and checking the buses on the streets -----------------------------------------------
MATCHED_ROUTE_TYPES = setting(
    "MATCHED_ROUTE_TYPES", [3], "GTFS route types matched onto the streets: the buses")
MATCH_RADIUS_M = setting(
    "MATCH_RADIUS_M", 50, "m: AequilibraE's map matcher looks this far from a stop for a street")
MAX_STATION_SPREAD_M = assume(
    "MAX_STATION_SPREAD_M", 300, "m between a station's furthest platforms",
    "a terminal's bays and the stops at its gates; further is two places, not one station")

# --- What a line takes to run (transit/fleet.py) ----------------------------------------------------
LAYOVER_SHARE = assume(
    "LAYOVER_SHARE", 0.10, "share of the trip's running time",
    "layover at each terminus: a usual planning allowance for recovery time")
LAYOVER_MIN_S = assume(
    "LAYOVER_MIN_S", 300, "s",
    "the shortest layover at a terminus, however short the trip: a driver's break")

# --- Zones (A3) - a synthetic grid over transit_inputs.ZONE_BOX --------------------------------------
COARSE_ROWS, COARSE_COLS = setting("COARSE_GRID", (10, 10),
                                   "rows and columns of the coarse grid over the zone box")
TRIM_SOUTH, TRIM_NORTH, TRIM_EAST = setting(
    "TRIM_SOUTH_NORTH_EAST", (0, 0, 0), "none: the zone box is drawn round the built-up area")
SPLIT = setting("SPLIT", 2, "each coarse cell becomes SPLIT x SPLIT zones (~1 km)")
MIN_ROAD_KM = assume(
    "MIN_ROAD_KM", 4.0, "km of street a cell needs to be kept as a zone",
    "GUESS: drops the farmland and the empty edges of the box; a built-up square km has well "
    "over 10 km of street")

# --- The modelled period (A4) ------------------------------------------------------------------------
PERIOD_START_H, PERIOD_END_H = setting(
    "PERIOD_HOURS", (7, 9), "the modelled period, hours from midnight: the morning peak. The "
    "service is counted inside it and the demand describes the same window")

# --- Demand (A7) - synthetic ----------------------------------------------------------------------------
TARGET_PEAK_TRIPS = assume(
    "TARGET_PEAK_TRIPS", 30_000, "public-transport trips in the PERIOD_HOURS peak - the "
    "uniform matrix's total, shared evenly among the zones' pairs",
    "GUESS: a city of about 700,000 whose buses carry some 150,000-200,000 a day, a fifth of them "
    "in the two morning hours. Sets the level only: no crowding, so it moves every volume in "
    "proportion and changes no route")
ACCESS_DECAY_KM = assume(
    "ACCESS_DECAY_KM", 0.6, "km: how fast transit trip-making falls off away from a stop",
    "stands in for a mode-choice model: a zone at the doorstep counts fully, one at this "
    "distance about a third")
CORRIDOR_SHARE = assume(
    "CORRIDOR_SHARE", 0.0, "share of peak demand on an unserved axis", "none drawn for Sorocaba")
NORTH_SHARE = assume(
    "NORTH_SHARE", 0.0, "share of peak demand from suburbs only a feeder reaches",
    "none drawn for Sorocaba")
CORE_LAT, CORE_LON = assume(
    "CORE_CENTRE", (-23.500, -47.458), "lat, lon of the business core trips are drawn to",
    "Sorocaba's centre, round the cathedral: where the lines meet")
CORE_SPREAD_LAT, CORE_SPREAD_LON = assume(
    "CORE_SPREAD_DEG", (0.025, 0.025), "degrees of latitude and longitude the core's pull spans",
    "GUESS: a soft bump about 5 km across")
ATTRACTION_FLOOR = assume(
    "ATTRACTION_FLOOR", 0.25, "pull of a zone far from the core, against 1 at its centre",
    "so no zone attracts nothing; a little higher than Quito's - industry and the universities "
    "lie on the edges")

# --- The transit graph (B2) ------------------------------------------------------------------------------
# The optimal strategies themselves take no parameter: what shapes them is the graph they run on.
ACCESS_RADIUS_M = assume(
    "ACCESS_RADIUS_M", 600, "m from a zone's middle to the stops it walks to, in a straight line",
    "about 8 minutes on foot; a zone also keeps the stops AequilibraE's overlapping regions give it")
TRANSFER_PENALTY_S = assume(
    "TRANSFER_PENALTY_S", 480, "s added at each change of vehicle - not at the first boarding nor "
    "the last alighting", "AequilibraE's default alighting penalty: the inconvenience of a "
    "transfer, beyond its walk and its wait")
WAIT_TIME_FACTOR = assume(
    "WAIT_TIME_FACTOR", 0.5, "share of the headway a passenger waits on average, at a stop "
    "served by lines of the given frequencies",
    "half the headway: passengers arriving at random at a service that keeps its timetable. "
    "AequilibraE's default, 1, is the wait for vehicles arriving at random")
WALKING_SPEED = assume(
    "WALKING_SPEED", 1.2, "m/s (about 4.3 km/h) for every access, egress and transfer walk",
    "AequilibraE's default of 1.0 m/s is a slow walk")
CONNECTOR_METHOD = setting(
    "CONNECTOR_METHOD", "overlapping_regions", "a zone is joined to every stop within reach, not "
    "only its nearest")
GRAPH_TRANSFERS = setting(
    "GRAPH_TRANSFERS", {"with_walking_edges": True, "with_inner_stop_transfers": True,
                        "with_outer_stop_transfers": True, "blocking_centroid_flows": True},
    "walking between a station's platforms, changing at a stop and across a station; no walk "
    "passes through a zone (zone - stop - zone - stop ... on foot)")
SAME_STATION_M = assume(
    "SAME_STATION_M", 300, "metres on foot two platforms of one station may be apart",
    "the routed counterpart of MAX_STATION_SPREAD_M")
TRANSFER_WALK_M = assume(
    "TRANSFER_WALK_M", 400, "m on foot within which two stops on different routes are joined",
    "GUESS: further apart than this and nobody changes there on foot")
WALK_ROUTE_MAX_STRAIGHT_M = setting(
    "WALK_ROUTE_MAX_STRAIGHT_M", 600, "stop pairs further apart than this in a straight line are "
    "not routed on foot at all")

# --- The assignment (B4) ---------------------------------------------------------------------------------
TRANSIT_ALGORITHM = setting(
    "TRANSIT_ALGORITHM", "os", "optimal strategies (Spiess & Florian, 1989): frequency-based "
    "hyperpaths, uncapacitated")
