"""The model's assignment against answers worked out by hand, on networks small enough to.

    python tests/toy_networks.py

Roads (core/assignment.py's Assigner, as the road model runs it):

    two zones joined by two routes - a short one (10 min, 1,000 veh/h) and a long one (15 min,
    2,000 veh/h, in two links) - and 3,000 vehicles from the first zone to the second. At user
    equilibrium both routes take the same time (Wardrop): with BPR that is one equation in the
    short route's flow x,
        10 (1 + a (x / 1000)^b) = 15 (1 + a ((3000 - x) / 2000)^b),
    solved here by bisection. Checked: the flows, the time between the zones in the congested
    skim, vehicle-hours, V/C, conservation; the short route closed (everything on the long one,
    its time from BPR); and a two-hour period (twice the trips against twice the capacity: the
    same split, doubled).

Public transport (AequilibraE's optimal strategies, as transit/graph.py and assignment.py set
it up) has its own section below: two lines serving the same two stops, and a third beyond
them that some passengers change to.
"""
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RESULTS = []
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def check(area, name, passed, detail=""):
    RESULTS.append((area, name, bool(passed), detail))
    print(f"  {'PASS' if passed else 'FAIL'}  {area}: {name}" + (f"  ({detail})" if detail else ""),
          flush=True)


def bisect(f, lo, hi, tol=1e-9):
    for _ in range(200):
        mid = (lo + hi) / 2
        if (f(lo) > 0) == (f(mid) > 0):
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2


# --- roads ------------------------------------------------------------------------------------------
ALPHA, BETA = 0.15, 4.0
DEMAND = 3000.0
SHORT = dict(minutes=10.0, capacity=1000.0)
LONG = dict(minutes=15.0, capacity=2000.0)          # two links of 7.5 min, the same capacity
CONNECTOR_MIN = 0.01


def bpr(t0, v, c):
    return t0 * (1 + ALPHA * (v / c) ** BETA)


def by_hand(demand, factor=1.0, closed=False):
    """(short route's flow, long route's flow, the time between the zones)."""
    if closed:
        return 0.0, demand, bpr(LONG["minutes"], demand, LONG["capacity"] * factor)
    gap = lambda x: (bpr(SHORT["minutes"], x, SHORT["capacity"] * factor)  # noqa: E731
                     - bpr(LONG["minutes"], demand - x, LONG["capacity"] * factor))
    x = bisect(gap, 0.0, demand)
    return x, demand - x, bpr(SHORT["minutes"], x, SHORT["capacity"] * factor)


def road_project(folder):
    """Zone 1 - A - (short) - B - zone 2, and A - M - B the long way; every link one way."""
    from aequilibrae import Project
    from shapely.geometry import LineString, Point
    project = Project()
    project.new(folder)
    links = project.network.links
    links.fields.add("lanes_ab", "lanes, a to b", "INTEGER")
    links.fields.add("lanes_ba", "lanes, b to a", "INTEGER")
    links.fields.add("junction", "OSM junction", "TEXT")
    links.refresh_fields()
    nodes = project.network.nodes
    for zone, x in ((1, 0.0), (2, 0.2)):
        c = nodes.new_centroid(zone)
        c.geometry = Point(x, 0.0)
        c.save()
    a, b, m = (0.01, 0.0), (0.19, 0.0), (0.10, 0.05)
    plan = [("connector", [(0.0, 0.0), a], CONNECTOR_MIN, 1e6),
            ("short", [a, b], SHORT["minutes"], SHORT["capacity"]),
            ("long_1", [a, m], LONG["minutes"] / 2, LONG["capacity"]),
            ("long_2", [m, b], LONG["minutes"] / 2, LONG["capacity"]),
            ("connector", [b, (0.2, 0.0)], CONNECTOR_MIN, 1e6)]
    ids = {}
    for name, points, minutes, capacity in plan:
        link = links.new()
        link.geometry = LineString(points)
        link.modes = "c"
        link.link_type = "default"
        link.direction = 1
        link.name = name
        link.save()
        ids.setdefault(name, []).append(int(link.link_id))
        with project.db_connection as conn:
            conn.execute("UPDATE links SET travel_time_ab = ?, travel_time_ba = ?, capacity_ab = ?, "
                         "capacity_ba = 0, speed_ab = 50, lanes_ab = 1 WHERE link_id = ?",
                         (minutes, minutes, capacity, link.link_id))
            conn.commit()
    return project, ids


def roads():
    from core.assignment import Assigner, conservation, flow_table, vehicle_hours
    s = SimpleNamespace(BPR_ALPHA=ALPHA, BPR_BETA=BETA, MAX_ITER=500, RGAP_TARGET=1e-6)
    zones = [1, 2]
    folder = os.path.join(tempfile.mkdtemp(prefix="toy_roads_"), "project")
    project, ids = road_project(folder)
    short, long1 = ids["short"][0], ids["long_1"][0]
    demand = np.array([[0.0, DEMAND], [0.0, 0.0]])
    try:
        for label, factor, closed in (("equilibrium", 1.0, False), ("a two-hour period", 2.0, False),
                                      ("the short route closed", 1.0, True)):
            print(f"\nroads, {label}:")
            x, y, t = by_hand(DEMAND * factor, factor, closed)
            assigner = Assigner(project, zones, s, closed=[short] if closed else [])
            results = assigner.solve(demand * factor, label=label, capacity_factor=factor)
            flows, _ = flow_table(project, results, capacity_factor=factor)
            got = flows.set_index("link_id")
            gx = float(got["car_ab"].get(short, 0.0) or 0.0)
            gy = float(got.loc[long1, "car_ab"])
            check("roads", f"{label}: route flows as by hand",
                  abs(gx - x) < 0.5 and abs(gy - y) < 0.5,
                  f"short {gx:,.1f} / {x:,.1f}, long {gy:,.1f} / {y:,.1f}")
            free = np.array([[0.0, 2 * CONNECTOR_MIN + SHORT["minutes"]], [1e9, 0.0]])
            if closed:
                free[0, 1] = 2 * CONNECTOR_MIN + LONG["minutes"]
            minutes = assigner.congested_minutes(free, results, np.array([True, True]),
                                                 faster_allowed=True)
            check("roads", f"{label}: the congested skim's time between the zones",
                  abs(minutes[0, 1] - (t + 2 * CONNECTOR_MIN)) < 0.01,
                  f"{minutes[0, 1]:.3f} / {t + 2 * CONNECTOR_MIN:.3f} min")
            busy, free_h = vehicle_hours(flows)
            want = (x * bpr(SHORT["minutes"], x, SHORT["capacity"] * factor)
                    + y * bpr(LONG["minutes"], y, LONG["capacity"] * factor)
                    + DEMAND * factor * 2 * CONNECTOR_MIN) / 60
            check("roads", f"{label}: vehicle-hours", abs(busy - want) / want < 1e-3,
                  f"{busy:,.2f} / {want:,.2f}")
            voc = float(got.loc[long1, "voc"])
            check("roads", f"{label}: V/C on the long route", abs(voc - y / (LONG["capacity"] * factor)) < 1e-3,
                  f"{voc:.4f} / {y / (LONG['capacity'] * factor):.4f}")
            worst = conservation(flows, demand * factor, zones)
            check("roads", f"{label}: conservation", worst < 1e-6, f"{100 * worst:.6f}%")
    finally:
        project.close()
        shutil.rmtree(os.path.dirname(folder), ignore_errors=True)


# --- public transport ---------------------------------------------------------------------------------
# Three stops in a row, S1 - S2 - S3, each in a zone of its own, its middle 200 m east of its stop.
# A and B run S1 -> S2, A every 10 min in 20 min, B every 20 min in 15 min; C runs S2 -> S3 every
# 15 min in 10 min. Each stands 30 s at a stop (its design's: in the timetable). In the hour 07-08,
# 600 passengers from zone 1 to zone 2 and 300 from zone 1 to zone 3, who change at S2.
#
# By hand (Spiess & Florian 1989, as AequilibraE 1.6.2 codes it, with the wait factor 0.5): at S1
# both A and B are attractive - alone each costs 1,530 s to S2, together 1,330 - so the wait is
# 0.5 / (6/h + 3/h) = 200 s and the passengers split as the frequencies, 2/3 on A. A ride runs
# from one stop's departure to the next's, so it holds the 30 s at the stop it reaches: 1,230 s
# on A, 930 on B, 630 on C. The trip to zone 3 waits 0.5 x 15 min = 450 s more at S2, and pays the
# transfer penalty once; the trip to zone 2 pays none.
LINES = {"A": dict(stops=("S1", "S2"), headway_min=10, ride_min=20),
         "B": dict(stops=("S1", "S2"), headway_min=20, ride_min=15),
         "C": dict(stops=("S2", "S3"), headway_min=15, ride_min=10)}
DWELL_S, PENALTY_S, WALK_SPEED, WAIT_FACTOR = 30.0, 480.0, 1.2, 0.5
STOPS = {"S1": (-47.45, -23.50), "S2": (-47.40, -23.50), "S3": (-47.35, -23.50)}
TO_TWO, TO_THREE = 600.0, 300.0
OFFSET = 0.002                                 # a zone's middle, east of its stop (about 200 m)


def toy_feed(path):
    import zipfile

    def clock(minutes, seconds=0):
        return f"06:{minutes:02d}:{seconds:02d}"
    files = {
        "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\nT,Toy,http://t,America/Sao_Paulo\n",
        "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
                        "start_date,end_date\nWD,1,1,1,1,1,0,0,20260101,20261231\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\n"
                     + "".join(f"{k},Stop {k},{lat},{lon}\n" for k, (lon, lat) in STOPS.items()),
        "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type\n"
                      + "".join(f"{r},T,{r},Line {r},3\n" for r in LINES),
        "trips.txt": "route_id,service_id,trip_id,direction_id\n"
                     + "".join(f"{r},WD,{r}_t,0\n" for r in LINES),
        # As transit/gtfs.py writes them: a stop's departure is its arrival plus the dwell.
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n" + "".join(
            f"{r}_t,{clock(0)},{clock(0, int(DWELL_S))},{v['stops'][0]},1\n"
            f"{r}_t,{clock(v['ride_min'], int(DWELL_S))},{clock(v['ride_min'] + 1)},{v['stops'][1]},2\n"
            for r, v in LINES.items()),
        "frequencies.txt": "trip_id,start_time,end_time,headway_secs\n" + "".join(
            f"{r}_t,06:00:00,10:00:00,{v['headway_min'] * 60}\n" for r, v in LINES.items()),
    }
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)


def transit():
    import contextlib
    import io

    import pandas as pd
    from aequilibrae import Project
    from shapely.geometry import Point, box

    from transit.assignment import solve_transit
    from transit.graph import TransitNetwork
    from transit.project import declare_period, import_feed

    base = tempfile.mkdtemp(prefix="toy_transit_")
    folder = os.path.join(base, "project")
    project = Project()
    project.new(folder)
    try:
        for zone_id, (lon, lat) in enumerate(STOPS.values(), start=1):
            zone = project.zoning.new(zone_id)
            zone.geometry = box(lon - 0.004, lat - 0.004, lon + 0.004, lat + 0.004)
            zone.add_centroid(Point(lon + OFFSET, lat))
            zone.save()
        project.zoning.refresh_geo_index()
        hours = declare_period(project, 2, 7, 8)
        feed = os.path.join(base, "toy_gtfs.zip")
        toy_feed(feed)
        with contextlib.redirect_stdout(io.StringIO()):
            transit_model = import_feed(project, feed, "Toy", "toy feed", "2026-10-15", route_types=[])
        s = SimpleNamespace(WALKING_SPEED=WALK_SPEED, TRANSFER_PENALTY_S=PENALTY_S, ACCESS_RADIUS_M=600,
                            WAIT_TIME_FACTOR=WAIT_FACTOR, CONNECTOR_METHOD="overlapping_regions",
                            TRANSIT_ALGORITHM="os",
                            GRAPH_TRANSFERS={"with_walking_edges": True, "with_inner_stop_transfers": True,
                                             "with_outer_stop_transfers": False,  # no stations
                                             "blocking_centroid_flows": True})
        paths = SimpleNamespace(project_db=os.path.join(folder, "project_database.sqlite"),
                                transit_db=os.path.join(folder, "public_transport.sqlite"))
        net = TransitNetwork(project, transit_model, paths, s, 2)
        net.walk_pairs = pd.DataFrame(columns=["stop_a", "stop_b", "walk_m"])
        net.save_graph_configuration()
        graph = net.build_graph()
        edges = graph.edges
        route = lambda e: e["line_id"].astype(str).str.rsplit("_", n=1).str[0]  # noqa: E731
        board = edges[edges["link_type"] == "boarding"]
        per_hour = dict(zip(route(board), board["freq"] * 3600 * WAIT_FACTOR))
        check("transit", "frequencies from the timetable (over the wait factor on the edges)",
              all(abs(per_hour.get(r, 0) - 60 / v["headway_min"]) < 1e-6 for r, v in LINES.items()),
              ", ".join(f"{r} {f:g}/h" for r, f in per_hour.items()))
        times = {k: sorted(edges.loc[edges["link_type"] == k, "trav_time"].round(3).unique().tolist())
                 for k in ("boarding", "alighting", "on-board")}
        check("transit", "no stop time of the graph's own: boarding nothing, alighting the penalty",
              bool(times["boarding"]) and times["boarding"][-1] < 0.01
              and abs(times["alighting"][0] - PENALTY_S) < 0.01, str(times))
        # AequilibraE's import keeps a stop's departure as its arrival too, so a ride runs from
        # departure to departure: it holds the dwell at the stop it reaches - once.
        rides = {r: v["ride_min"] * 60 + DWELL_S for r, v in LINES.items()}
        check("transit", "a ride is the timetable's, with the dwell at the stop it reaches",
              times["on-board"] == sorted(rides.values()), str(times["on-board"]))

        demand = np.array([[0.0, TO_TWO, TO_THREE], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
        result = solve_transit(net, graph, demand, hours, "toy")
        e = result.edges
        on = e[e["link_type"] == "on-board"]
        ride = dict(zip(route(on), on["pt_volume"]))
        f = {r: 1 / (LINES[r]["headway_min"] * 60) for r in ("A", "B")}
        share = {r: f[r] / sum(f.values()) for r in f}
        check("transit", "the passengers split as the lines' frequencies, and all change to C",
              all(abs(ride.get(r, 0) - (TO_TWO + TO_THREE) * share[r]) < 0.5 for r in f)
              and abs(ride.get("C", 0) - TO_THREE) < 0.5,
              ", ".join(f"{r} {v:.1f}" for r, v in ride.items()))
        wait1 = WAIT_FACTOR / sum(f.values())
        ivt1 = sum(share[r] * rides[r] for r in f)
        wait3 = wait1 + WAIT_FACTOR * LINES["C"]["headway_min"] * 60
        ivt3 = ivt1 + rides["C"]
        walk = 2 * edges[edges["link_type"] == "access_connector"]["trav_time"].min()
        sk = lambda name, j: float(result.skim(name)[0, j])  # noqa: E731
        for j, label, wait, ivt, paid in ((1, "no change", wait1, ivt1, 0.0),
                                          (2, "one change", wait3, ivt3, PENALTY_S)):
            check("transit", f"{label}: the cost is walks + waits + rides + the penalty at a change",
                  abs(sk("trav_time", j) - (walk + wait + ivt + paid)) < 1,
                  f"{sk('trav_time', j):.1f} / {walk + wait + ivt + paid:.1f} s")
            check("transit", f"{label}: the wait read out is the wait alone",
                  abs(result.pair_wait()[0, j] - wait) < 1,
                  f"{result.pair_wait()[0, j]:.1f} / {wait:.1f} s")
            check("transit", f"{label}: the penalty paid", abs(sk("penalty_time", j) - paid) < 0.01,
                  f"{sk('penalty_time', j):.1f} / {paid:.0f} s")
            check("transit", f"{label}: the journey, without the penalty",
                  abs(result.pair_journey()[0, j] - (walk + wait + ivt)) < 1,
                  f"{result.pair_journey()[0, j]:.1f} / {walk + wait + ivt:.1f} s")
            check("transit", f"{label}: transfers counted",
                  abs(result.pair_transfers()[0, j] - (1 if paid else 0)) < 1e-6,
                  f"{result.pair_transfers()[0, j]:.3f}")
        check("transit", "every trip boards", abs(result.boarded_demand - TO_TWO - TO_THREE) < 0.5,
              f"{result.boarded_demand:.1f}")
        mean = (TO_TWO * (walk + wait1 + ivt1) + TO_THREE * (walk + wait3 + ivt3)) / (TO_TWO + TO_THREE)
        check("transit", "the average journey of the trips that board",
              abs(result.journey_time * 60 - mean) < 1, f"{result.journey_time * 60:.1f} / {mean:.1f} s")
        check("transit", "transfers per trip",
              abs(result.transfers - TO_THREE / (TO_TWO + TO_THREE)) < 1e-6, f"{result.transfers:.3f}")
        stops = result.stops.set_index("stop")
        # Those changing to C at S2 do so on a transfer edge: not an alighting to the street.
        check("transit", "alightings at a stop include the trips getting off to their destination",
              abs(stops.loc["S2", "alighting"] - TO_TWO) < 0.5
              and abs(stops.loc["S3", "alighting"] - TO_THREE) < 0.5,
              f"S2 {stops.loc['S2', 'alighting']:.1f}, S3 {stops.loc['S3', 'alighting']:.1f}")
    finally:
        project.close()
        shutil.rmtree(base, ignore_errors=True)


def main():
    roads()
    transit()
    failed = [r for r in RESULTS if not r[2]]
    print(f"\n{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
