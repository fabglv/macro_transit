"""Which group of the model each parameter belongs to, for parameters.csv and the results page.

Kept apart from settings.py so the page, which needs nothing beyond the standard library, can
read the order without loading pandas.
"""

# The parameters by what they act on, in the order the results page lists them. A name a city
# alone has goes in its settings module's `ASSUMED.groups`; one in neither is listed under "Other".
GROUPS = {
    "Network parameters": [
        "NETWORK_MARGIN_M", "NOT_ROADS", "REPAIR_OSM_TAGS", "SPEED_KMH", "LANE_CAPACITY_BY_SPEED",
        "DEFAULT_LANES", "DEFAULT_SPEED_LANE_CAPACITY", "STRICT_SKIM"],
    "Zone parameters": [
        "MIN_ZONE_POP", "MAX_ZONE_POP", "MIN_ZONE_SIZE", "MAX_ZONE_SIZE", "CONNECTORS_PER_ZONE",
        "CONNECTOR_SPEED_CAPACITY", "RESCUE_ROADS", "EXTRA_CONNECTOR_MISMATCH",
        "EXTRA_CONNECTOR_M"],
    "Trip generation parameters": [
        "TRIPS_PER_PERSON", "ATTRACTION_RATES", "CAR_SHARE", "OCCUPANCY"],
    "Gravity model parameters": [
        "MEAN_TRIP_MIN", "DETERRENCE", "BETA_FLOOR_CEILING", "INTRAZONAL_SHARE"],
    "Time of day parameters": [
        "DAY", "PERIOD", "PERIOD_SCALE", "WEEKEND_PERIOD_SCALE", "PERIOD_DIRECTION",
        "WEEKDAY_SIZE", "SATURDAY_SUNDAY", "WEEKEND_ATTRACTION_RATES", "WEEKEND_HOUSEHOLD_PULL"],
    "External traffic parameters": [],
    "Cost function parameters": ["BPR_ALPHA_BETA"],
    "Simulation parameters": ["RGAP_TARGET_MAX_ITER"],
    "Reporting parameters": ["PEAK_TRIPS_PER_DAY", "WORKING_DAYS"],
    "Count comparison parameters": [],
    # The public-transport run (transit/); its names are grouped in its settings module.
    "Transit service parameters": [],
    "Transit demand parameters": [],
    "Walking parameters": [],
}
OTHER = "Other parameters"
