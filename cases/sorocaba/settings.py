"""Sorocaba: every value in the model that is decided rather than measured, in one place.

Each goes through `assume()`, which records its unit and the reason for it; the full table is
printed at the end of a run and written to `assumptions.csv`. Change a value and run again.

The first group is the one to replace first: no Sorocaba source measures them.

Technical constants - map colours, simplification tolerances, the bounds of a diagnostic range -
stay with the code that uses them.
"""
from core.settings import Assumptions

ASSUMED = Assumptions()
assume = ASSUMED.assume
setting = ASSUMED.setting

# Where the results page lists the parameters only Sorocaba has (the shared ones: core.settings).
ASSUMED.groups.update(
    {name: "Trip generation parameters" for name in
     ["CAR_OWNERSHIP_ELASTICITY", "HOUSEHOLD_PULL"]}
    | {name: "External traffic parameters" for name in
       ["EXTERNAL_ZONES", "EXTERNAL_CAR_SHARE", "EXTERNAL_CAR_SHARE_STUDY", "PEAK_HOUR_SHARE",
        "THROUGH_SHARE", "REGIONAL_TRIP_FACTOR", "THROUGH_TRIPS", "THROUGH_MIN_ANGLE",
        "DAILY_COMMUTE_PERCENTILE", "REACH_KM", "GATEWAY_ROADS", "REGIONAL_SPEED_KMH",
        "ACCESS_KMH", "FAR_ACCESS_KMH", "ACCESS_SLACK_MIN", "MUNI_MIN_COMMUTERS",
        "VOTORANTIM_MIN_COMMUTERS", "POOL_MIN_COMMUTERS", "RING_MIN_COMMUTERS"]}
    | {"COUNT_HOUR": "Count comparison parameters"})

# --- To calibrate first -------------------------------------------------------------------
# Not measured for Sorocaba. These are the numbers a mobility survey or traffic counts
# should replace, and the ones the calibration phase will move.
CAR_SHARE = assume(
    "CAR_SHARE", 0.30, "share of person trips made by car, city average - REPLACE WHEN KNOWN",
    "NOT MEASURED. ANTP's urban mobility information system puts the car at roughly a quarter to "
    "a third of trips in Brazilian municipalities of Sorocaba's size. The city's own Pesquisa OD "
    "or Plano de Mobilidade, if one is published, should replace this")
OCCUPANCY = assume(
    "OCCUPANCY", 1.4, "people per car - REPLACE WHEN KNOWN",
    "NOT MEASURED. Brazilian OD surveys typically find 1.3 to 1.5 in the peak")
EXTERNAL_CAR_SHARE = assume(
    "EXTERNAL_CAR_SHARE", 0.45, "share of intermunicipal commuters to WORK travelling by car - "
    "REPLACE WHEN KNOWN",
    "NOT MEASURED. Higher than the city's own share because the trips are longer and "
    "intermunicipal buses are sparser than city ones; Votorantim is served by both")
EXTERNAL_CAR_SHARE_STUDY = assume(
    "EXTERNAL_CAR_SHARE_STUDY", 0.20, "share of ADULT intermunicipal students driving - REPLACE "
    "WHEN KNOWN",
    "NOT MEASURED. Far below the workers' share: students travel by intercity bus or by the "
    "buses many municipalities of the region run to take their students to the university "
    "cities, and a household's car usually goes with a parent to work. Students under 18 are "
    "not drivers at all - that part is the data's (their age, E9), not this setting's")
TRIPS_PER_PERSON = assume(
    "TRIPS_PER_PERSON", 0.24, "person trips per resident in the morning peak hour",
    "no household travel survey; Brazilian OD surveys find about two trips per person per day, "
    "of which the busiest hour carries around an eighth")
PEAK_HOUR_SHARE = assume(
    "PEAK_HOUR_SHARE", 0.30, "share of a day's commuters whose outbound trip is in the peak hour",
    "a morning peak spread over about three hours, with the busiest carrying a little under a "
    "third of it")
MEAN_TRIP_MIN = assume(
    "MEAN_TRIP_MIN", 9.0, "average car trip within the city, free-flow minutes",
    "no observed trip length distribution. The city is compact: with no deterrence at all the "
    "average free-flow car trip is about 10 minutes, so any target at or above that switches "
    "travel time off as a reason to choose a destination. 9 keeps it inside the range the "
    "network can produce while still letting distance matter; the census's door-to-door times, "
    "all modes, are an upper bound on it, not a target")

# --- Set from the traffic counts at the city's edges (F7) ---------------------------------
# The counts where the city's own trips do not reach measure the region's traffic - commuting,
# other trips to Sorocaba, and trips passing through - but not how it divides between the last
# two. THROUGH_SHARE says how; the other two are what F7 then finds the counts ask for.
THROUGH_SHARE = assume(
    "THROUGH_SHARE", 0.3, "share of the edge traffic beyond commuting that is passing through - "
    "REPLACE WHEN KNOWN",
    "NOT MEASURED, and the counts cannot tell (F7 shows the fit barely moves with it). The "
    "concessionaire knows it: the free-flow gantries read number plates, so vehicles seen at "
    "both gantry 09 and gantry 12 are the SP-270's through traffic")
REGIONAL_TRIP_FACTOR = assume(
    "REGIONAL_TRIP_FACTOR", 2.82, "external trips per commuting trip, all purposes, in the peak "
    "hour",
    "set from the edge counts in F7, given THROUGH_SHARE: the region's shopping, services, "
    "business and van trips to and from Sorocaba, on top of the census commuters")
THROUGH_TRIPS = assume(
    "THROUGH_TRIPS", 2141, "vehicles an hour passing through the city, external zone to external "
    "zone",
    "set from the edge counts in F7, given THROUGH_SHARE")
THROUGH_MIN_ANGLE = assume(
    "THROUGH_MIN_ANGLE", 120, "degrees between two external zones, seen from the city centre, "
    "for trips between them to cross the city",
    "zones closer in angle than this lie on the same side, and their trips would not come in")

# --- Switches -----------------------------------------------------------------------------
# Choices of method rather than of a number.
EXTERNAL_ZONES = setting("EXTERNAL_ZONES", "municipalities",
                         "how external zones are drawn: municipalities, ring or gateways (E5, E7)")

# --- Zones (C) ----------------------------------------------------------------------------
MAX_ZONE_SIZE = assume(
    "MAX_ZONE_SIZE", 4000, "people + jobs above which a zone is split",
    "gives about 390 zones for Sorocaba's million people and jobs - a median zone of a few "
    "blocks, coarse enough for the matrix to carry whole trips, fine enough that a zone joins the "
    "network close to its own people")
MIN_ZONE_SIZE = assume(
    "MIN_ZONE_SIZE", 1000, "people + jobs below which a zone is merged into a neighbour",
    "a zone this small produces a few dozen car trips in the peak hour at most; merging it "
    "costs nothing measurable")

# --- Trip generation (E8) -----------------------------------------------------------------
CAR_OWNERSHIP_ELASTICITY = assume(
    "CAR_OWNERSHIP_ELASTICITY", 1.0,
    "how strongly a zone's car share follows its 2010 car ownership",
    "1 means proportional: an area with 20% more car-owning households makes 20% more of its trips "
    "by car. 0 would give every zone the city average")
ATTRACTION_RATES = assume(
    "ATTRACTION_RATES",
    {"other_estab": 1.0, "teaching": 2.5, "health": 1.3, "agricultural": 0.5},
    "relative peak-hour pull per job, by kind of establishment",
    "a job draws its worker; a school job also draws the students it teaches, a clinic job its "
    "patients. Only the ratios matter - the totals are rescaled to match productions")
HOUSEHOLD_PULL = assume(
    "HOUSEHOLD_PULL", 0.15, "peak-hour pull of an occupied household, relative to one job",
    "a single all-purpose matrix carries escort trips, visits and the journey home as well as the "
    "journey out; Quito gave housing floor area a twentieth of the commercial rate")

# --- The day and the time of day (E10b, core/timeofday.py) --------------------------------
# As the Quito notebooks time_of_day_demo and weekday_weekend_demo do it, with their numbers -
# none measured for Sorocaba. The defaults - a weekday, the morning peak - are the model as it
# was: the base matrix itself.
DAY = setting("DAY", "weekday", "the day modelled: a weekday, or a weekend day (the average of "
                                "a Saturday and a Sunday)")
PERIOD = setting("PERIOD", "morning peak", "the hour modelled - 07:00, 12:00, 17:00 or 22:00, "
                                           "an hour each - or the whole day")
PERIOD_SCALE = assume(
    "PERIOD_SCALE", {"morning peak": 1.00, "midday": 0.48, "evening peak": 1.00, "night": 0.17},
    "a weekday hour's traffic against the morning peak's (s)",
    "NOT MEASURED: Quito's notebook profile. The SAT counts' hourly profiles at the city's edges "
    "would set it")
WEEKEND_PERIOD_SCALE = assume(
    "WEEKEND_PERIOD_SCALE", {"morning peak": 0.30, "midday": 0.57, "evening peak": 0.50,
                             "night": 0.20},
    "a weekend day's hour against the weekday morning peak (s)",
    "ASSUMED: a later, flatter day peaking around midday, its busiest hour 7.7% of the day")
PERIOD_DIRECTION = assume(
    "PERIOD_DIRECTION", {"morning peak": 1.00, "midday": 0.50, "evening peak": 0.00,
                         "night": 0.50},
    "share of the hour's trips from home to activity (f); the rest go back",
    "the extremes: the morning all outward, the evening all home, midday and night both ways. A "
    "Pesquisa OD would give it - nearer 0.85 in a commute peak")
WEEKDAY_SIZE = assume(
    "WEEKDAY_SIZE", 10.16, "a weekday's traffic, in morning-peak hours (S)",
    "NOT MEASURED: the morning peak as 9.8% of the day, a usual share")
SATURDAY_SUNDAY = assume(
    "SATURDAY_SUNDAY", (0.80, 0.65), "a Saturday's and a Sunday's traffic against a weekday's",
    "NOT MEASURED: an ordinary weekend profile; a weekend day is their average")
WEEKEND_ATTRACTION_RATES = assume(
    "WEEKEND_ATTRACTION_RATES",
    {"other_estab": 1.0, "teaching": 0.2, "health": 0.8, "agricultural": 0.3},
    "relative pull per job on a weekend day, by kind of establishment",
    "NOT MEASURED: shops and services pull as on a weekday, schools hardly, clinics and "
    "hospitals less, farms little")
WEEKEND_HOUSEHOLD_PULL = assume(
    "WEEKEND_HOUSEHOLD_PULL", 0.40, "pull of an occupied household on a weekend day, relative to "
                                    "one job",
    "NOT MEASURED: weekends carry more visits to family and friends")

# --- Trip distribution (E6, E10) ----------------------------------------------------------
DETERRENCE = assume(
    "DETERRENCE", "EXPO", "gravity deterrence function",
    "EXPO needs one parameter where GAMMA needs two, and nothing here would justify the second")
INTRAZONAL_SHARE = assume(
    "INTRAZONAL_SHARE", 0.5, "intrazonal cost as a share of the trip to the nearest other zone",
    "a skim has no diagonal; without one every zone is its own best destination")

# --- Road network (E0–E4) -----------------------------------------------------------------
NETWORK_MARGIN_M = assume(
    "NETWORK_MARGIN_M", 1500, "metres of network downloaded beyond the city limit",
    "enough for every road leaving the city to cross the boundary inside the model, which is "
    "what the cordon zones join to; more would add Votorantim's streets for no gain")
SPEED_KMH = assume(
    "SPEED_KMH",
    {"motorway": 100, "motorway_link": 60, "trunk": 80, "trunk_link": 50,
     "primary": 60, "primary_link": 40, "secondary": 50, "secondary_link": 40,
     "tertiary": 40, "tertiary_link": 30, "unclassified": 40, "residential": 30,
     "living_street": 20, "service": 20, "road": 30},
    "free-flow km/h by OSM road class",
    "no speed survey; CTB limits for unsigned streets (arterial 60, collector 40, local 30, with "
    "secondary between them at 50), typical posted limits on the state highways, and slower slip "
    "roads. Used only where OSM has no maxspeed tag")
LANE_CAPACITY_BY_SPEED = assume(
    "LANE_CAPACITY_BY_SPEED",
    ((80, 2000), (60, 1300), (45, 900), (35, 700), (25, 500), (0, 300)),
    "(free-flow km/h at least, vehicles per hour per lane per direction)",
    "Quito's bands: an uninterrupted road carries about 2,000 an hour a lane, a signalised street "
    "about half that because it only discharges on green. Rates are textbook; the speed that "
    "selects them is data")
DEFAULT_LANES = assume(
    "DEFAULT_LANES",
    {"motorway": 2, "motorway_link": 1, "trunk": 2, "trunk_link": 1,
     "primary": 2, "primary_link": 1, "secondary": 1, "secondary_link": 1,
     "tertiary": 1, "tertiary_link": 1, "unclassified": 1, "residential": 1,
     "living_street": 1, "service": 1, "road": 1},
    "lanes per direction where OSM does not say",
    "used only where the lanes tag is missing; how often that happens is printed below")
DEFAULT_SPEED, DEFAULT_LANE_CAPACITY = assume(
    "DEFAULT_SPEED_LANE_CAPACITY", (30, 600), "km/h and veh/h per lane for an unlisted class",
    "stands in for a class the table does not list; the check after it fails loudly if needed")
CONNECTORS_PER_ZONE = assume(
    "CONNECTORS_PER_ZONE", 3, "connectors joining each zone to the network",
    "Quito's value: one connector makes a zone's whole demand enter the network at a single node, "
    "a bottleneck that is not real. connect_mode picks the N nodes nearest the centroid, so this "
    "spreads the demand but does not choose where it spreads to")
CONNECTOR_SPEED, CONNECTOR_CAPACITY = assume(
    "CONNECTOR_SPEED_CAPACITY", (40, 100_000), "km/h and veh/h on centroid connectors",
    "a connector is not a road; an unlimited one keeps zone-system artefacts out of the queues")
RESCUE_ROADS = assume(
    "RESCUE_ROADS", ["trunk", "primary", "secondary", "tertiary"],
    "road classes a stranded zone may be joined to",
    "connect_mode only joins a centroid to a node inside its own zone, which leaves a few "
    "stranded on islands or in one-way traps; they are joined to the nearest node on a road of "
    "these classes instead")
EXTRA_CONNECTOR_MISMATCH = assume(
    "EXTRA_CONNECTOR_MISMATCH", 4.0, "how lopsided a zone must be to get another connector",
    "the ratio of a zone's share of the city's travel to the share of road capacity where it "
    "joins the network; Quito's value")
EXTRA_CONNECTOR_M = assume(
    "EXTRA_CONNECTOR_M", 1000, "how far an extra connector may reach",
    "far enough to find the arterial on a zone's edge; Sorocaba's zones are smaller than Quito's, "
    "so a little shorter than its 1,200")

# --- External traffic (D, E2, E7) ---------------------------------------------------------
DAILY_COMMUTE_PERCENTILE = assume(
    "DAILY_COMMUTE_PERCENTILE", 0.99, "share of daily workers whose distance sets the range of a "
    "daily commute",
    "the census asks only workers whether they go home every day; the distance within which 99% "
    "of those who do live - computed in D2, about 100 km - is taken as the most anyone commutes "
    "daily, and applied to students too, whom the census does not ask")
REACH_KM = assume(
    "REACH_KM", 90, "km around the city limit within which census sectors and regional roads are read",
    "far enough for Itu, Tatuí and Itapetininga, and most of the capital; municipalities with commuters beyond it are read whole in E7")
GATEWAY_ROADS = assume(
    "GATEWAY_ROADS", ["motorway", "trunk", "primary", "secondary"],
    "road classes whose crossing of the city limit makes a gateway",
    "the classes that carry traffic between municipalities; tertiary and below are local "
    "streets, which in the Votorantim conurbation cross the line by the dozen")
REGIONAL_SPEED_KMH = assume(
    "REGIONAL_SPEED_KMH",
    {"motorway": 100, "trunk": 80, "primary": 70, "secondary": 60, "link": 40},
    "free-flow km/h on the regional roads that route commuters to a gateway",
    "posted limits on São Paulo state highways, a little under for the single carriageways; "
    "ramps slower. Only the relative times matter: they decide which gateway is fastest")
ACCESS_KMH = assume(
    "ACCESS_KMH", 30, "speed from a census sector to the nearest regional road, straight line",
    "local streets, and a straight line shorter than the real path; it is the same for every "
    "gateway from a given sector unless the nearest regional road differs, so it rarely decides")
FAR_ACCESS_KMH = assume(
    "FAR_ACCESS_KMH", 75, "speed from a distant town to the edge of the regional network, "
    "straight line",
    "towns beyond the downloaded region - São Carlos, Piraju, the far side of the capital - reach "
    "it by highway; 75 km/h in a straight line is about 90 km/h on a road a fifth longer. At the "
    "local-street speed their trip would take hours, inflating the times of the zones they "
    "belong to")
ACCESS_SLACK_MIN = assume(
    "ACCESS_SLACK_MIN", 15, "gateways an external zone may use: within this many minutes of "
    "its fastest",
    "wide enough for the assignment to choose between real alternatives; for a zone next to the "
    "city - Votorantim - it takes in most of the southern crossings, and the assignment's own "
    "times inside the city then decide between them")
MUNI_MIN_COMMUTERS = assume(
    "MUNI_MIN_COMMUTERS", 1000, "daily commuters for a municipality to be a zone of its own",
    "16 municipalities clear it and carry 87% of all commuters; below it a town exchanges a few "
    "hundred people a day and comes in the same way as its neighbours, so it is pooled with them. "
    "Only used with EXTERNAL_ZONES = 'municipalities'")
VOTORANTIM_MIN_COMMUTERS = assume(
    "VOTORANTIM_MIN_COMMUTERS", 1500, "daily commuters below which a part of Votorantim joins the "
    "neighbouring part it shares the longest border with",
    "keeps Votorantim to a handful of zones, one per main border crossing it uses")
POOL_MIN_COMMUTERS = assume(
    "POOL_MIN_COMMUTERS", 500, "daily commuters below which a corridor pool joins the neighbouring "
    "pool it shares the longest border with",
    "a corridor carrying a few dozen commuters is not worth a zone of its own")
RING_MIN_COMMUTERS = assume(
    "RING_MIN_COMMUTERS", {"inner": 300, "outer": 2000},
    "daily commuters below which a catchment joins the neighbour it shares the longest border "
    "with, by band",
    "inner: a zone exchanging a few dozen people a day adds a row to the matrix and nothing else. "
    "outer: high on purpose, so the band beyond the neighbours is a few large zones, one per main "
    "approach. Only used with EXTERNAL_ZONES = 'ring'")

# --- Assignment (E11) ---------------------------------------------------------------------
BPR_ALPHA, BPR_BETA = assume(
    "BPR_ALPHA_BETA", (0.15, 4.0), "alpha and beta in the BPR volume-delay function",
    "no observed speed-flow data; the values BPR is almost always published with")
RGAP_TARGET, MAX_ITER = setting("RGAP_TARGET_MAX_ITER", (0.0001, 500),
                                "equilibrium: relative gap to reach, and iterations at most - "
                                "1e-4: a scenario's effect of a fraction of a percent is not "
                                "the solver's own tolerance")

# --- Reporting (E12) ----------------------------------------------------------------------
PEAK_TRIPS_PER_DAY = assume(
    "PEAK_TRIPS_PER_DAY", 2, "peak-hour trips a person makes on a working day",
    "one out and one back; nothing in the data says so")
WORKING_DAYS = assume(
    "WORKING_DAYS", 250, "working days a year", "a five-day year less holidays")

# --- Checking against counts (F) ----------------------------------------------------------
COUNT_HOUR = assume(
    "COUNT_HOUR", 7, "clock hour of the counts the peak hour is set against: 7 = 07:00-08:00",
    "the model's peak hour has no clock; 07:00-08:00 is the busiest hour of the weekday morning "
    "at the two gantries inside Sorocaba, in both directions")

# --- Choices of method the shared steps need, not assumptions --------------------------------
NOT_ROADS = setting("NOT_ROADS", [
    "pedestrian", "bridleway", "construction", "crossing", "ladder", "rest_area", "bus_stop",
    "steps", "footway", "path", "track", "corridor", "elevator", "proposed", "platform",
    "raceway", "escalator", "cycleway", "busway", "bus_guideway"],
    "OSM link types dropped from the network: not roads for cars")
REPAIR_OSM_TAGS = setting("REPAIR_OSM_TAGS", True,
                          "put back slip-road classes, one-way tags and one-way roundabouts (E1b)")
STRICT_SKIM = setting("STRICT_SKIM", True, "stop the run if a zone is cut off from most of the "
                      "network")
BETA_FLOOR, BETA_CEILING = setting("BETA_FLOOR_CEILING", (0.001, 1.5),
                                   "the range of deterrence the gravity search runs over")
