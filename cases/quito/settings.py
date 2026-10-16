"""Quito: every value in the model that is decided rather than measured.

Each goes through `assume()`, which records its unit and the reason for it; the full table is
printed at the end of a run and written to `assumptions.csv`. Change a value and run again.

`CAR_SHARE` and `OCCUPANCY` are the Municipio's own figures; everything else here is a guess.
"""
from core.settings import Assumptions

ASSUMED = Assumptions()
assume = ASSUMED.assume
setting = ASSUMED.setting

# --- Zones (C) - choices of method, not assumptions -----------------------------------------
MIN_ZONE_POP = setting("MIN_ZONE_POP", 500, "people below which a zone is merged into a neighbour")
MAX_ZONE_POP = setting("MAX_ZONE_POP", 8000, "people above which a zone is split into compact pieces")

# --- Road network (E0-E3) -----------------------------------------------------------------
NOT_ROADS = setting("NOT_ROADS", [
    "pedestrian", "bridleway", "construction", "crossing", "ladder", "rest_area", "bus_stop",
    "steps", "footway", "path", "track", "corridor", "elevator", "proposed", "platform",
    "raceway", "escalator"], "OSM link types dropped from the network: not roads for cars")
# Sorocaba repairs slip-road classes, one-way tags and roundabouts from OSM (E1b). Quito's model
# was built without it; switching it on downloads the district's tags once (cached) and changes
# the network the results stand on.
REPAIR_OSM_TAGS = setting("REPAIR_OSM_TAGS", False,
                          "put back slip-road classes, one-way tags and roundabouts from OSM (E1b)")

CONNECTORS_PER_ZONE = assume(
    "CONNECTORS_PER_ZONE", 3, "connectors joining each zone to the network",
    "one connector makes a zone's whole demand enter the network at a single node, which turns "
    "the access point into a bottleneck that is not real - the largest office zone in Inaquito "
    "was loading a one-way street at four times capacity. connect_mode picks the N nodes nearest "
    "the centroid, so this spreads the demand but does not choose where it spreads to")
RESCUE_ROADS = assume(
    "RESCUE_ROADS", ["trunk", "primary", "secondary", "tertiary"],
    "road classes a stranded zone may be joined to",
    "connect_mode only joins a centroid to a node inside its own zone, which leaves a few "
    "stranded on islands or in one-way traps; they are joined to the nearest node on a road of "
    "these classes instead, since a slightly longer connector is closer to the truth than none")
SPEED_KMH = assume(
    "SPEED_KMH",
    {"motorway": 90, "motorway_link": 60, "trunk": 80, "trunk_link": 55,
     "primary": 60, "primary_link": 45, "secondary": 50, "secondary_link": 40,
     "tertiary": 40, "tertiary_link": 35, "unclassified": 30, "residential": 30,
     "living_street": 20, "service": 20, "road": 30},
    "free-flow km/h by OSM road class",
    "no speed survey; typical urban values, used only where OSM has no maxspeed tag")
LANE_CAPACITY_BY_SPEED = assume(
    "LANE_CAPACITY_BY_SPEED",
    ((80, 2000), (60, 1300), (45, 900), (35, 700), (25, 500), (0, 300)),
    "(free-flow km/h at least, vehicles per hour per lane per direction)",
    "what limits a road is whether traffic has to stop. Nothing interrupts a grade-separated "
    "road, so a lane carries what car-following allows, about 2,000/h. A signalised street "
    "discharges at a similar rate but only while the light is green, so it carries about half "
    "that. OSM does not say which a road is, and its class tag is not reliable - `trunk` covers "
    "both Simon Bolivar at 90 km/h and 575 links at 60 or below. Speed is the usable proxy: you "
    "cannot post 90 km/h on a road with traffic lights. Rates are textbook, the speed that "
    "selects them is data. The lower bands matter as much as the upper: they cover 103,184 of "
    "the 116,697 links, and lumping them together washes out the difference between a service "
    "road and a through street")
DEFAULT_LANES = assume(
    "DEFAULT_LANES",
    {"motorway": 2, "motorway_link": 1, "trunk": 2, "trunk_link": 1,
     "primary": 2, "primary_link": 1, "secondary": 2, "secondary_link": 1,
     "tertiary": 1, "tertiary_link": 1, "unclassified": 1, "residential": 1,
     "living_street": 1, "service": 1, "road": 1},
    "lanes per direction where OSM does not say",
    "used only where the lanes tag is missing; how often that happens is printed below")
CONNECTOR_SPEED, CONNECTOR_CAPACITY = assume(
    "CONNECTOR_SPEED_CAPACITY", (40, 100_000), "km/h and veh/h on centroid connectors",
    "a connector is not a road; an unlimited one keeps zone-system artefacts out of the queues")
DEFAULT_SPEED, DEFAULT_LANE_CAPACITY = assume(
    "DEFAULT_SPEED_LANE_CAPACITY", (30, 600), "km/h and veh/h per lane for an unlisted class",
    "the speed stands in for a class the table below does not list, and the check after it fails "
    "loudly if that happens. The capacity is unreachable in practice - the speed bands start at "
    "zero, so every link finds one")
EXTRA_CONNECTOR_MISMATCH = assume(
    "EXTRA_CONNECTOR_MISMATCH", 4.0, "how lopsided a zone must be to get another connector",
    "the ratio of a zone's share of the city's travel to the share of road capacity where it "
    "joins the network. At 4 a zone is carrying four times the traffic its access points are "
    "built for")
EXTRA_CONNECTOR_M = assume(
    "EXTRA_CONNECTOR_M", 1200, "how far an extra connector may reach",
    "far enough to find the arterial on a zone's edge, short enough that a zone still joins the "
    "network near its own people")

# --- Skim (E4) ----------------------------------------------------------------------------
INTRAZONAL_SHARE = assume(
    "INTRAZONAL_SHARE", 0.5,
    "intrazonal cost as a share of the trip to the nearest other zone",
    "a skim has no diagonal; without one every zone is its own best destination and the trip "
    "matrix collapses onto itself")
STRICT_SKIM = setting("STRICT_SKIM", False, "stop the run if a zone is cut off from most of the "
                      "network; False reports it and goes on")

# --- Trip generation (E5) -----------------------------------------------------------------
TRIPS_PER_PERSON = assume(
    "TRIPS_PER_PERSON", 0.32, "person trips per resident per peak hour",
    "no household travel survey; a typical peak share of a 2.5-3.5 trip day")
ATTRACTION_RATES = assume(
    "ATTRACTION_RATES",
    {"mixed/commercial": 1.00, "facilities": 0.70, "heritage core": 0.60,
     "industrial": 0.25, "residential": 0.05},
    "relative pull per m2 of floor area",
    "no establishment register and no employment data; shops pull hardest, industry least. Only "
    "the ratios matter - the totals are rescaled to match productions")
CAR_SHARE = assume(
    "CAR_SHARE", 0.19, "share of person trips made by car",
    "MEASURED, not assumed: the Municipio puts private vehicles at 19% of trips today, and aims "
    "for 3% by 2042 (Secretaria de Movilidad, reported in Primicias, 8 Jan 2024). This replaces a "
    "guess of 0.35, which gave 208% more travel time than free flow and was already cut to 0.20 "
    "on the grounds that no working city shows that - a correction the official figure then "
    "confirmed to within a point")
OCCUPANCY = assume(
    "OCCUPANCY", 1.3, "people per vehicle",
    "MEASURED, not assumed: the Municipio de Quito puts the average at 1.3 people per car "
    "(Alcalde Pabel Munoz, reported in Primicias, 8 Jan 2024). Was 1.5 by guesswork")

# --- Trip distribution (E5) ---------------------------------------------------------------
MEAN_TRIP_MIN = assume(
    "MEAN_TRIP_MIN", 16.0, "average vehicle trip length, minutes",
    "no observed trip length distribution; this sets the deterrence parameter, which is solved "
    "for rather than guessed")
DETERRENCE = assume(
    "DETERRENCE", "EXPO", "gravity deterrence function",
    "EXPO needs one parameter where GAMMA needs two, and nothing here would justify the second")
BETA_FLOOR, BETA_CEILING = setting("BETA_FLOOR_CEILING", (0.001, 1.0),
                                   "the range of deterrence the gravity search runs over")

# --- The day and the time of day (E5b, core/timeofday.py) ---------------------------------
# From the notebooks time_of_day_demo and weekday_weekend_demo. The defaults - a weekday, the
# morning peak - are the model as it was: the base matrix itself.
DAY = setting("DAY", "weekday", "the day modelled: a weekday, or a weekend day (the average of "
                                "a Saturday and a Sunday)")
PERIOD = setting("PERIOD", "morning peak", "the hour modelled - 07:00, 12:00, 17:00 or 22:00, "
                                           "an hour each - or the whole day")
PERIOD_SCALE = assume(
    "PERIOD_SCALE", {"morning peak": 1.00, "midday": 0.48, "evening peak": 1.00, "night": 0.17},
    "a weekday hour's traffic against the morning peak's (s)",
    "the morning peak is 1 by construction - the matrix checked against the AMT's roads; the "
    "evening equals it (the same journeys reversed, spread over more hours, so its busiest hour "
    "lands close); midday and night are an ordinary urban profile. NOT MEASURED: one AMT count "
    "station with an hourly profile would replace them")
WEEKEND_PERIOD_SCALE = assume(
    "WEEKEND_PERIOD_SCALE", {"morning peak": 0.30, "midday": 0.57, "evening peak": 0.50,
                             "night": 0.20},
    "a weekend day's hour against the weekday morning peak (s)",
    "ASSUMED: a later, flatter day peaking around midday; the busiest hour, 0.57, is the 7.7% of "
    "the weekend day the daily notebook takes (7.7% x 10.16 x 0.725)")
PERIOD_DIRECTION = assume(
    "PERIOD_DIRECTION", {"morning peak": 1.00, "midday": 0.50, "evening peak": 0.00,
                         "night": 0.50},
    "share of the hour's trips from home to activity (f); the rest go back",
    "the notebook's extremes: the morning all outward, the evening all home, midday and night "
    "both ways. Practice takes f from a household survey - nearer 0.85 in a commute peak; Quito "
    "has none")
WEEKDAY_SIZE = assume(
    "WEEKDAY_SIZE", 10.16, "a weekday's traffic, in morning-peak hours (S)",
    "NOT MEASURED: the morning peak as 9.8% of the day, a usual share")
SATURDAY_SUNDAY = assume(
    "SATURDAY_SUNDAY", (0.80, 0.65), "a Saturday's and a Sunday's traffic against a weekday's",
    "NOT MEASURED: an ordinary weekend profile; a weekend day is their average")
WEEKEND_ATTRACTION_RATES = assume(
    "WEEKEND_ATTRACTION_RATES",
    {"mixed/commercial": 1.00, "facilities": 0.40, "heritage core": 1.00,
     "industrial": 0.05, "residential": 0.15},
    "relative pull per m2 of floor area on a weekend day",
    "NOT MEASURED: shops and the historic centre pull as hard as anything, schools and offices "
    "less, industry hardly, homes more (visits). Weekend counts at shopping centres and in the "
    "historic centre would set them")

# --- Assignment (E6) ----------------------------------------------------------------------
BPR_ALPHA, BPR_BETA = assume(
    "BPR_ALPHA_BETA", (0.15, 4.0), "alpha and beta in the BPR volume-delay function",
    "no observed speed-flow data for Quito's streets; these are the values BPR is almost always "
    "published with, and the ones the scenarios notebook uses")
RGAP_TARGET, MAX_ITER = setting("RGAP_TARGET_MAX_ITER", (0.0001, 1000),
                                "equilibrium: relative gap to reach, and iterations at most - "
                                "1e-4: a scenario's effect of a fraction of a percent is not "
                                "the solver's own tolerance; Quito's congestion slows the solver "
                                "near the answer, so it is given more iterations than Sorocaba")

# --- Reporting (E8) -----------------------------------------------------------------------
PEAK_TRIPS_PER_DAY = assume(
    "PEAK_TRIPS_PER_DAY", 2, "peak-hour trips a person makes on a working day",
    "one out and one back; nothing in the data says so")
WORKING_DAYS = assume(
    "WORKING_DAYS", 250, "working days a year",
    "a common figure for a five-day year less holidays; not specific to Quito")
