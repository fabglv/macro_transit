"""Quito's public-transport model: every value that is decided rather than measured.

Each goes through `assume()`, which records its unit and the reason for it; the full table is
printed at the end of a run and written to `assumptions.csv`. Choices of method - the period, how
the graph joins zones to stops - go through `setting()`. Change a value and run again:

    python run.py quito --transit

The feed itself (routes, stops, headways) is in transit_inputs.py. Nothing here is measured: the
demand is synthetic, so every number in its group is a knob, not an estimate.
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
       ["MATCHED_ROUTE_TYPES", "MATCH_RADIUS_M", "MAX_STATION_SPREAD_M"]}
    | {name: "Transit service parameters" for name in
       ["PERIOD_HOURS", "CONNECTOR_METHOD", "GRAPH_TRANSFERS", "TRANSIT_ALGORITHM",
        "LAYOVER_SHARE", "LAYOVER_MIN_S"]}
    | {name: "Transit demand parameters" for name in
       ["TARGET_PEAK_TRIPS", "ACCESS_DECAY_KM", "CORRIDOR_SHARE", "NORTH_SHARE", "CORE_CENTRE",
        "CORE_SPREAD_DEG", "ATTRACTION_FLOOR"]}
    | {name: "Walking parameters" for name in
       ["WALKING_SPEED", "SAME_STATION_M", "TRANSFER_WALK_M", "WALK_ROUTE_MAX_STRAIGHT_M",
        "TRANSFER_PENALTY_S", "WAIT_TIME_FACTOR", "ACCESS_RADIUS_M"]})

# --- Zones (A3) - a synthetic grid -----------------------------------------------------------
# A coarse grid over the study box, trimmed to the bands the corridors run through, then split.
# Zone size matters more here than in a road model: a zone's access connector stands for the walk
# from its centroid to a stop, so the zone size sets the walking distance.
COARSE_ROWS, COARSE_COLS = setting("COARSE_GRID", (12, 6),
                                   "rows and columns of the coarse grid over the study box")
TRIM_SOUTH, TRIM_NORTH, TRIM_EAST = setting(
    "TRIM_SOUTH_NORTH_EAST", (1, 0, 1), "coarse bands dropped off the south, north and east")
SPLIT = setting("SPLIT", 2, "each surviving coarse cell becomes SPLIT x SPLIT zones (~0.9 km)")
MIN_ROAD_KM = assume(
    "MIN_ROAD_KM", 2.0, "km of street a cell needs to be kept as a zone",
    "drops the mountainside - mostly the north-western wedge climbing Pichincha - by measuring "
    "street inside each cell rather than drawing a boundary by hand. A link touching a cell counts "
    "in full, which slightly over-credits boundary cells: immaterial against 2 km")

# --- The feed and its import (A5-A6) ---------------------------------------------------------
MATCHED_ROUTE_TYPES = setting(
    "MATCHED_ROUTE_TYPES", [3], "GTFS route types map-matched onto the streets: buses only - "
    "the metro runs in a tunnel")
MATCH_RADIUS_M = setting(
    "MATCH_RADIUS_M", 50, "metres a stop may be from a street and still be map-matched: "
    "AequilibraE's distance_to_project default, used by the audit, not passed to the matcher")
MAX_STATION_SPREAD_M = assume(
    "MAX_STATION_SPREAD_M", 200, "metres, straight line, two platforms of one station may be apart",
    "further apart than this is a walk between corridors, not a platform change; a shared "
    "parent_station claims an interchange AequilibraE takes at face value")

# --- Operations - what a design takes to run (transit/fleet.py) ------------------------------
# A vehicle waits at each terminus before it sets off again: time to recover a delay, and the
# driver's break. It counts in the vehicles a line needs and in its vehicle-hours, not in any
# passenger's journey.
LAYOVER_SHARE = assume(
    "LAYOVER_SHARE", 0.10, "share of the trip's running time",
    "layover at each terminus: a usual planning allowance for recovery time")
LAYOVER_MIN_S = assume(
    "LAYOVER_MIN_S", 300, "s",
    "the shortest layover at a terminus, however short the trip: a driver's break")

# --- The modelled period (A4) ----------------------------------------------------------------
PERIOD_START_H, PERIOD_END_H = setting(
    "PERIOD_HOURS", (7, 9), "the modelled period, hours from midnight: the morning peak. The "
    "service is counted inside it and the demand describes the same window")

# --- Demand (A7) - synthetic ------------------------------------------------------------------
TARGET_PEAK_TRIPS = assume(
    "TARGET_PEAK_TRIPS", 60_000, "public-transport trips in the PERIOD_HOURS peak - the "
    "uniform matrix's total, shared evenly among the zones' pairs",
    "SYNTHETIC. Sets the overall level only: with no crowding, scaling it moves every volume in "
    "proportion and changes no route, no journey time and no transfer")
ACCESS_DECAY_KM = assume(
    "ACCESS_DECAY_KM", 0.7, "km: how fast transit trip-making falls off away from a stop",
    "stands in for a mode-choice model. A Gaussian decay at both ends of a trip: a zone at the "
    "doorstep counts fully, one at this distance about a third, one three times as far nothing")
CORRIDOR_SHARE = assume(
    "CORRIDOR_SHARE", 0.20, "share of peak demand on the unserved cross-town axis",
    "SYNTHETIC. Every route runs north-south, so movements across the city have no transit option "
    "today; the ordinary reason a fourth line gets proposed, and the demand a new line would pick "
    "up")
NORTH_SHARE = assume(
    "NORTH_SHARE", 0.05, "share of peak demand originating in the northern suburbs",
    "SYNTHETIC. Commuter districts only the feeder reaches; their morning trips run one way, out "
    "of the north to the rest of the city, and change at El Labrador")
CORE_LAT, CORE_LON = assume(
    "CORE_CENTRE", (-0.195, -78.487), "lat, lon of the business core trips are drawn to",
    "La Carolina / El Ejido: a gravity-style pull so trips have somewhere to be going")
CORE_SPREAD_LAT, CORE_SPREAD_LON = assume(
    "CORE_SPREAD_DEG", (0.035, 0.020), "degrees of latitude and longitude the core's pull spans",
    "a soft bump about 4 km north-south by 2 km east-west, the shape of the valley's centre")
ATTRACTION_FLOOR = assume(
    "ATTRACTION_FLOOR", 0.15, "pull of a zone far from the core, against 1 at its centre",
    "so no zone attracts nothing")

# --- The transit graph (B2) ------------------------------------------------------------------
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
    "AequilibraE's default of 1.0 m/s is a slow walk and makes every walk 20% longer. It is not "
    "stored in the saved graph configuration, so it is set on every rebuild")
CONNECTOR_METHOD = setting(
    "CONNECTOR_METHOD", "overlapping_regions", "a zone is joined to every stop within reach, not "
    "only its nearest: choosing between two stops is what the hyperpath model exists to represent")
GRAPH_TRANSFERS = setting(
    "GRAPH_TRANSFERS", {"with_walking_edges": True, "with_inner_stop_transfers": True,
                        "with_outer_stop_transfers": True, "blocking_centroid_flows": True},
    "walking between a station's platforms, changing at a stop and across a station; no walk "
    "passes through a zone (zone - stop - zone - stop ... on foot)")
SAME_STATION_M = assume(
    "SAME_STATION_M", 200, "metres on foot two platforms of one station may be apart",
    "the routed counterpart of MAX_STATION_SPREAD_M: the audit flags a declared station whose "
    "platforms are further apart on the ground")
TRANSFER_WALK_M = assume(
    "TRANSFER_WALK_M", 500, "metres on foot within which two stops on different routes are joined",
    "further apart than this and nobody changes there on foot. The walk is routed on the streets "
    "and charged at WALKING_SPEED")
WALK_ROUTE_MAX_STRAIGHT_M = setting(
    "WALK_ROUTE_MAX_STRAIGHT_M", 800, "stop pairs further apart than this in a straight line are "
    "not routed on foot at all")

# --- The assignment (B4) ---------------------------------------------------------------------
TRANSIT_ALGORITHM = setting(
    "TRANSIT_ALGORITHM", "os", "optimal strategies (Spiess & Florian, 1989): frequency-based "
    "hyperpaths, uncapacitated")
