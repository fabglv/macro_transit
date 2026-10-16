"""What a design takes to run: vehicles, vehicle-km and vehicle-hours, line by line.

    running time   a trip's, first stop to last, as the feed has it (gtfs.run_time_s): the
                   distance - along the streets for a bus - at the line's speed, or its legs' times
                   set by hand, and a dwell at every stop between the termini
    layover        at each terminus before the vehicle sets off again: LAYOVER_SHARE of the
                   running time, at least LAYOVER_MIN_S
    round trip     the time a vehicle takes to be back where it started: out and back, both
                   directions' running time and layovers; a loop, once round and a layover - a
                   loop run both ways round is two circulations, each with its own vehicles
    vehicles       round trip / headway, rounded up, at the line's shortest headway that day:
                   the vehicles in service at its busiest. Spares for maintenance come on top.
    vehicle-km     every departure times its length - along the streets for a bus, stop to stop
                   for the metro
    vehicle-hours  every departure times its running time and its layover

Weekdays, Saturday and Sunday each as day_timetables says; a week is five weekdays and a weekend.
"""
import math

from .gtfs import day_timetables, departures, directions, km, run_time_s, service_pieces

DAYS = ["weekday", "saturday", "sunday"]


def operations(line, start_s, end_s, layover_share, layover_min_s, lengths=None, leg_km=None):
    """The line's round trip and, for each type of day it runs, its vehicles, departures,
    vehicle-km and vehicle-hours. `lengths` gives each direction's km (along the streets) and
    `leg_km` each direction's legs', which its running times are measured on; without them,
    stop to stop."""
    journeys = directions(line)
    runs = [run_time_s(line, stops, leg_km[d] if leg_km else None, d)
            for d, stops in enumerate(journeys)]
    layovers = [max(layover_min_s, layover_share * r) for r in runs]
    if lengths is None:
        lengths = [sum(km((a[1], a[2]), (b[1], b[2])) for a, b in zip(stops, stops[1:]))
                   for stops in journeys]
    # The circulations a vehicle goes round: out and back is one; a loop each way its own.
    circulations = ([r + w for r, w in zip(runs, layovers)] if line.get("loop")
                    else [sum(runs) + sum(layovers)])
    out = {"round_trip_min": round(max(circulations) / 60, 1),
           "layover_min": round(sum(layovers) / len(layovers) / 60, 1),
           "km": round(sum(lengths), 2)}
    for day, timetable in day_timetables(line):
        pieces = service_pieces(timetable, start_s, end_s)
        if not pieces:
            continue
        shortest = min(h for _, _, h in pieces)
        each_way = len(departures(timetable, start_s, end_s))
        out[day] = {
            "vehicles": sum(math.ceil(c / shortest - 1e-9) for c in circulations),
            "departures": each_way * len(journeys),
            "vehicle_km": round(each_way * sum(lengths), 1),
            "vehicle_hours": round(each_way * (sum(runs) + sum(layovers)) / 3600, 1)}
    return out


def week(ops, field):
    """Five weekdays and a weekend of one field ("vehicle_km")."""
    return 5 * ops.get("weekday", {}).get(field, 0) + sum(
        ops.get(day, {}).get(field, 0) for day in ("saturday", "sunday"))
