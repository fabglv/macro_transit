"""Sorocaba's public transport: its study box, its feed's agency and calendar, and its lines.

There is no GTFS feed of the city's buses (Urbes, the BRT) to hand - the state's (ARTESP) has
only the regional routes reaching the city - so the lines come from OpenStreetMap: its bus
route relations, turned into LINES by transit/osm_lines.py

    python -m transit.osm_lines sorocaba

which writes OSM_DIR/lines.json, read here. OSM has each mapped line's route and stops; its
headways mostly, and its speeds and vehicles always, are assumed (transit_settings.py) and said
in lines.json's report. OSM has about thirty of the city's lines: a partial network.

The line design part works on these (design.py, the editor), and a simulation on synthetic
zones and demand, as Quito's (transit_settings.py): guesses, to see the network work - the road
model's zones and O-D matrix are the likely real source.
"""
import json
import os

from core.paths import ROOT

LABEL = "Sorocaba"

# [min_lat, min_lon, max_lat, max_lon]: the municipality and a margin - the streets downloaded
# for the bus routes' paths and stop checks.
BBOX = (-23.60, -47.58, -23.34, -47.29)
CITY_LIMIT = os.path.join(ROOT, "output", "macro", "sorocaba", "exports", "city_limit.gpkg")
OSM_DIR = os.path.join(ROOT, "data", "sorocaba", "input_min", "osm_transit")
# The zones' grid: the built-up area the lines run through (their stops reach -23.55 to -23.40,
# -47.51 to -47.36), not the whole study box - the open country around it would be zones nobody
# travels from.
ZONE_BOX = (-23.57, -47.53, -23.38, -47.34)

AGENCY = dict(agency_id="URBES", agency_name="Urbes - Transito e Transportes de Sorocaba",
              agency_url="https://www.urbes.com.br", agency_timezone="America/Sao_Paulo",
              agency_lang="pt")
CALENDAR = dict(service_id="WEEKDAY", monday=1, tuesday=1, wednesday=1, thursday=1, friday=1,
                saturday=0, sunday=0, start_date="20260101", end_date="20261231")
FEED_DESCRIPTION = "Sorocaba's bus lines from OpenStreetMap, timetables assumed"
SERVICE_DAY = "2026-10-14"                   # a Wednesday, inside the calendar above
SERVICE_HOURS = (5, 23)                      # first and last departures - ASSUMED

# A new line's places per vehicle when a design gives none.
DEFAULT_CAPACITY = {"bus": 90, "metro": 1200}


def _lines():
    """LINES and LINE_COLORS from OSM_DIR/lines.json - empty, with a word, if not made yet."""
    path = os.path.join(OSM_DIR, "lines.json")
    if not os.path.exists(path):
        print(f"No {path} yet: run python -m transit.osm_lines sorocaba")
        return {}, {}
    with open(path, encoding="utf-8") as f:
        made = json.load(f)
    lines = {}
    for key, line in made["lines"].items():
        line = dict(line)
        line["stops"] = [tuple(s) for s in line["stops"]]
        if line.get("stops_back"):
            line["stops_back"] = [tuple(s) for s in line["stops_back"]]
        line.pop("osm", None)                      # where it came from: lines.json keeps it
        lines[key] = line
    return lines, made["colors"]


LINES, LINE_COLORS = _lines()
