"""Quito's public-transport inputs: the study box, the feed and the unserved corridor.

This is data, not assumptions: what the network is made of. The numbers the model decides -
how much demand, how fast people walk, how far apart two platforms may be - are in
transit_settings.py.

**A demonstration, not a study of Quito.** The corridors and station names are real; the
coordinates are approximate, the stop lists abridged, and the timetable is generated from a
headway, a commercial speed and a dwell time (transit/gtfs.py). What the feed does not have is
Quito's ordinary bus network - the hundreds of feeder and city routes around these corridors -
which is most of why so many zones come out unserved.

Each stop is (name, lat, lon, interchange). `interchange` is the GTFS `parent_station`: stops
sharing one are platforms of the same station, and a passenger can walk (and therefore transfer)
between them. An empty string means an ordinary stop served by a single line. It is **not** the
way to say "a passenger could walk between these two stops" - that is a different claim, made by
the walking transfers the graph adds on its own (transit/graph.py), with a routed walk.
"""

LABEL = "Quito"

# [min_lat, min_lon, max_lat, max_lon] spanning Quito's north-south valley: the box the road
# scenarios notebook used, so both models look at the same slice of the valley.
BBOX = (-0.30, -78.55, -0.11, -78.45)

# Who publishes the feed, and the dates it runs. Weekdays all year, so any Wednesday gives the same
# service; SERVICE_DAY is the one imported.
AGENCY = dict(agency_id="EPMTPQ", agency_name="Movilidad Quito",
              agency_url="https://example.org/quito", agency_timezone="America/Guayaquil",
              agency_lang="es")
CALENDAR = dict(service_id="WEEKDAY", monday=1, tuesday=1, wednesday=1, thursday=1, friday=1,
                saturday=0, sunday=0, start_date="20250101", end_date="20251231")
FEED_DESCRIPTION = "Synthetic timetable for Quito's trunk network"
SERVICE_DAY = "2025-06-04"                  # a Wednesday, inside the calendar above
SERVICE_HOURS = (5, 22)                     # first and last departures, so the peak runs in full

# Four routes of two kinds. `route_type` is what the map matcher selects on: three of the four
# routes here are buses, matched onto the streets. A bus's `speed_kmh` is its commercial speed
# along the streets it takes - its running times are measured along them; the metro's, in a
# tunnel, stop to stop. `capacity` is the places per vehicle, seated and standing: typical for
# the vehicle - an articulated trolleybus or bus about 160, a standard bus about 90, a six-car
# metro train about 1,200. ASSUMED: check them against the fleet. Without it AequilibraE's
# default for the route type is used (60 for a bus, 560 for a metro), far below these.
LINES = {
    "L1": dict(
        route_id="L1", short="L1", long="Metro Linea 1 (Solanda - El Labrador)",
        route_type=1,                       # 1 = metro/subway in GTFS
        headway_s=300, speed_kmh=35.0, dwell_s=30, capacity=1200,
        stops=[
            ("Solanda",             -0.27680, -78.54010, ""),
            ("El Calzado",          -0.26740, -78.53380, ""),
            ("El Recreo",           -0.25390, -78.52320, "EST_RECREO"),
            ("La Magdalena",        -0.24150, -78.52150, ""),
            ("San Francisco",       -0.22040, -78.51500, ""),
            ("La Alameda",          -0.21510, -78.50300, ""),
            ("El Ejido",            -0.21020, -78.49950, ""),
            ("Universidad Central", -0.20190, -78.49440, ""),
            ("La Pradera",          -0.19410, -78.48910, ""),
            ("La Carolina",         -0.18440, -78.48620, ""),
            ("Inaquito",            -0.17570, -78.48470, ""),
            ("Jipijapa",            -0.16560, -78.48340, ""),
            ("El Labrador",         -0.15390, -78.48590, "EST_LABRADOR"),
        ]),
    "TROLE": dict(
        route_id="TROLE", short="Trolebus", long="Corredor Central Trolebus",
        route_type=3,                       # 3 = bus; these are the routes map-matched
        headway_s=180, speed_kmh=22.0, dwell_s=25, capacity=160,
        stops=[
            ("El Recreo",        -0.25420, -78.52290, "EST_RECREO"),
            ("Villaflora",       -0.24380, -78.51830, ""),
            ("El Playon",        -0.22200, -78.51340, ""),
            ("La Marin",         -0.21990, -78.50820, "EST_MARIN"),
            ("Banco Central",    -0.21500, -78.50510, ""),
            ("Alameda",          -0.21390, -78.50110, ""),
            # Both sit on Avenida 10 de Agosto, the real Trolebus alignment. Placing them off it -
            # in a block more than 50 m from any street - would put them outside the map matcher's
            # search radius and break this route's geometry in both directions. A6 checks for that.
            ("Ejido",            -0.20909, -78.50029, ""),
            ("Santa Clara",      -0.20400, -78.49380, ""),
            ("Mariana de Jesus", -0.19450, -78.49322, ""),
            ("Iniguez",          -0.18490, -78.48810, ""),
            ("La Y",             -0.17720, -78.48770, ""),
            ("Estadio",          -0.16860, -78.48590, ""),
            ("El Labrador",      -0.15450, -78.48660, ""),
        ]),
    "ECOVIA": dict(
        route_id="ECOVIA", short="Ecovia", long="Corredor Sur-Oriental Ecovia",
        route_type=3,
        headway_s=240, speed_kmh=20.0, dwell_s=25, capacity=160,
        stops=[
            # The Ecovia runs up Avenida 6 de Diciembre, 500-900 m east of the axis the metro and
            # the Trolebus share. Its stops sit near theirs on a map of the whole city and a
            # ten-minute walk apart on the ground, so only La Marin - where the two corridors
            # genuinely meet - is declared an interchange. `wide_stations()` enforces that.
            ("La Marin",         -0.22050, -78.50760, "EST_MARIN"),
            ("Simon Bolivar",    -0.21430, -78.50000, ""),
            ("La Paz",           -0.20620, -78.49110, ""),
            ("Baca Ortiz",       -0.19870, -78.48690, ""),
            ("Colon",            -0.19620, -78.48430, ""),
            ("Estadio Olimpico", -0.18800, -78.48060, ""),
            ("La Y Norte",       -0.17640, -78.48250, ""),
            ("Rio Coca",         -0.16290, -78.47760, ""),
        ]),
    # A northern feeder, entirely above the rest of the network: it runs 4.5 km up Avenida Galo
    # Plaza Lasso from El Labrador - the northern interchange, and its only connection to the trunk
    # - through Cotocollao and Carcelen to Carapungo, none of which any other route reaches. The
    # southbound journey skips Bicentenario, so that stop is served in one direction only. That is
    # what `stops_back` expresses: a return journey that is not simply the outward one reversed.
    "CIRCULAR": dict(
        route_id="CIRCULAR", short="Circular",
        long="Alimentador Norte (El Labrador - Carapungo)",
        route_type=3,
        headway_s=180, speed_kmh=16.0, dwell_s=20, capacity=90,
        # Coordinates taken off the OSM links themselves rather than guessed, so every stop is
        # inside the map matcher's 50 m radius. A6's `unmatchable_stops()` is the check.
        stops=[                                      # northbound
            ("El Labrador",  -0.15347, -78.48469, "EST_LABRADOR"),  # meets L1 and the Trolebus
            ("Bicentenario", -0.15011, -78.48418, ""),              # northbound only
            ("La Luz",       -0.14594, -78.48367, ""),
            ("Cotocollao",   -0.14252, -78.48296, ""),
            ("Ponciano",     -0.13747, -78.48233, ""),
            ("Carcelen",     -0.13105, -78.48158, ""),
            ("La Bota",      -0.12427, -78.48046, ""),
            ("Carapungo",    -0.11805, -78.47976, ""),             # northern terminus
        ],
        stops_back=[                                 # southbound - Bicentenario is skipped
            ("Carapungo",    -0.11805, -78.47976, ""),
            ("La Bota",      -0.12427, -78.48046, ""),
            ("Carcelen",     -0.13105, -78.48158, ""),
            ("Ponciano",     -0.13747, -78.48233, ""),
            ("Cotocollao",   -0.14252, -78.48296, ""),
            ("La Luz",       -0.14594, -78.48367, ""),
            ("El Labrador",  -0.15347, -78.48469, "EST_LABRADOR"),
        ]),
}

# The feeder whose catchment the northern-suburbs demand starts from (NORTH_SHARE).
FEEDER = "CIRCULAR"

# An east-west axis carrying real trips today with no transit on it, from Chilibulo through the
# historic centre to the ridge above Guapulo. Every route above runs north-south along the valley
# floor, so nothing serves movements across the city. A share of the demand sits on it
# (CORRIDOR_SHARE); the design designs/quito/new_line_l2.json builds a line along this same list, so the
# demand and the alignment cannot drift apart.
LATENT_CORRIDOR = [
    ("Chilibulo",       -0.23600, -78.54200, ""),
    ("La Libertad",     -0.23000, -78.53200, ""),
    ("San Roque",       -0.22500, -78.52300, ""),
    ("San Francisco",   -0.22065, -78.51530, ""),
    ("La Marin",        -0.22015, -78.50790, "EST_MARIN"),
    ("Itchimbia",       -0.21650, -78.50100, ""),
    ("La Tola",         -0.21200, -78.49400, ""),
    ("La Vicentina",    -0.20600, -78.48700, ""),
    ("Guapulo",         -0.19800, -78.47800, ""),
    ("Gonzalez Suarez", -0.18900, -78.46900, ""),
]

# One colour per route, by its short name, used by every map so a line always looks the same.
LINE_COLORS = {"L1": "#d62728", "Trolebus": "#1f77b4", "Ecovia": "#2ca02c",
               "Circular": "#ff7f0e"}

# A new line's places per vehicle when a design gives none (see `capacity` above).
DEFAULT_CAPACITY = {"bus": 90, "metro": 1200}
