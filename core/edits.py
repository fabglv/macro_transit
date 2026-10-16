"""A scenario's edits to the road network (core/runs.py), made on the run's own copy of it.

    close      the links are taken out of routing - in the assignment and in the loaded skim
    capacity   their capacity, both directions, times `factor` (1.5: about one lane more)
    speed      their free-flow speed set to `kmh`, and their free-flow time worked out again
    road       a new link between two junctions, through the points it bends through, of a
               class, lanes each way, speed and capacity a lane; its id kept on the edit as
               `links`, for the results

The scenario's assignment starts from a fresh copy of the network (core/steps.restore_project),
so the edits are written into that copy - capacity and time where the solver, the V/C and the
exports read them - and the base's network is never touched. Closures are not written: a link is
dropped from a graph as it is built (Assigner), so nothing routes over it.

The demand is the base's, as it is: an edit changes the routes drivers take, not where they go.
"""
import numpy as np


def describe(project, edits):
    """Print each edit: what, where, how many links and km."""
    with project.db_connection as conn:
        for edit in edits:
            if edit["kind"] == "road":
                print(f"  new road         {edit.get('label') or 'unnamed'}: {road_said(edit)}")
                continue
            ids = ",".join(str(int(i)) for i in edit["links"])
            km = conn.execute(f"SELECT COALESCE(SUM(distance), 0) / 1000.0 FROM links "
                              f"WHERE link_id IN ({ids})").fetchone()[0]
            what = {"close": "closed", "capacity": f"capacity x {edit.get('factor', 1):g}",
                    "speed": f"speed {edit.get('kmh', 0):g} km/h"}[edit["kind"]]
            print(f"  {what:<18} {edit.get('label') or 'links'}: {len(edit['links'])} links, "
                  f"{km:.1f} km")


def road_said(edit):
    """'primary, 2 lanes each way, 60 km/h, 1,300 veh/h a lane'."""
    lanes = f"{edit['lanes']} lane{'s' if edit['lanes'] > 1 else ''}"
    return (f"{edit['link_type']}, {lanes} {'one way' if edit['oneway'] else 'each way'}, "
            f"{edit['kmh']:g} km/h, {edit['lane_capacity']:,.0f} veh/h a lane")


def add_road(project, edit):
    """A new road in the run's copy of the network: a link from junction to junction - each end
    exactly on its node, so AequilibraE joins it to them rather than making nodes of its own -
    with the modes the class's links have, and its speed, lanes, capacity and free-flow time.
    Returns its link id."""
    from shapely.geometry import LineString
    ends = []
    with project.db_connection as conn:
        for node in (edit["from_node"], edit["to_node"]):
            row = conn.execute("SELECT is_centroid FROM nodes WHERE node_id = ?", (node,)).fetchone()
            if row is None or row[0]:
                raise ValueError(f"new road {edit.get('label') or ''}: junction {node} is not "
                                 f"on the network")
        modes = conn.execute("SELECT modes FROM links WHERE link_type = ? GROUP BY modes "
                             "ORDER BY COUNT(*) DESC LIMIT 1", (edit["link_type"],)).fetchone()
    for node in (edit["from_node"], edit["to_node"]):
        point = project.network.nodes.get(node).geometry
        ends.append((point.x, point.y))
    link = project.network.links.new()
    link.geometry = LineString([ends[0]] + [(lon, lat) for lat, lon in edit["points"]] + [ends[1]])
    link.modes = modes[0] if modes else "c"
    link.link_type = edit["link_type"]
    link.direction = 1 if edit["oneway"] else 0
    link.name = edit.get("label") or "new road"
    link.save()
    lid = int(link.link_id)
    lanes, kmh = float(edit["lanes"]), float(edit["kmh"])
    capacity = lanes * float(edit["lane_capacity"])
    back = 0.0 if edit["oneway"] else 1.0
    with project.db_connection as conn:
        conn.execute("UPDATE links SET speed_ab = ?, speed_ba = ?, lanes_ab = ?, lanes_ba = ?, "
                     "capacity_ab = ?, capacity_ba = ?, "
                     "travel_time_ab = distance / 1000.0 / ? * 60.0, "
                     "travel_time_ba = distance / 1000.0 / ? * 60.0 WHERE link_id = ?",
                     (kmh, kmh, lanes, lanes * back, capacity, capacity * back, kmh, kmh, lid))
        conn.commit()
        a, b, metres = conn.execute("SELECT a_node, b_node, distance FROM links WHERE link_id = ?",
                                    (lid,)).fetchone()
    if (a, b) != (edit["from_node"], edit["to_node"]):
        raise ValueError(f"new road {edit.get('label') or ''} did not join its junctions")
    print(f"    link {lid}: {metres / 1000:.2f} km, junction {a} to {b}")
    return lid


def apply(project, edits):
    """Write the capacity and speed edits and the new roads into the run's copy of the network;
    the links closed. A new road's link id goes on its edit, as `links`."""
    closed = []
    for edit in edits:
        if edit["kind"] == "road":
            edit["links"] = [add_road(project, edit)]
    with project.db_connection as conn:
        for edit in edits:
            if edit["kind"] == "road":
                continue
            ids = ",".join(str(int(i)) for i in edit["links"])
            # A link the network does not have would change nothing, and say nothing.
            found = {r[0] for r in conn.execute(f"SELECT link_id FROM links WHERE link_id IN ({ids})")}
            missing = [int(i) for i in edit["links"] if int(i) not in found]
            if missing:
                raise ValueError(f"{edit.get('label') or edit['kind']}: link"
                                 f"{'s' if len(missing) > 1 else ''} "
                                 f"{', '.join(map(str, missing[:10]))} not on the network")
            if edit["kind"] == "close":
                closed += [int(i) for i in edit["links"]]
            elif edit["kind"] == "capacity":
                conn.execute(f"UPDATE links SET capacity_ab = capacity_ab * ?, "
                             f"capacity_ba = capacity_ba * ? WHERE link_id IN ({ids})",
                             (edit["factor"], edit["factor"]))
            elif edit["kind"] == "speed":
                kmh = float(edit["kmh"])
                conn.execute(f"UPDATE links SET speed_ab = ?, speed_ba = ?, "
                             f"travel_time_ab = distance / 1000.0 / ? * 60.0, "
                             f"travel_time_ba = distance / 1000.0 / ? * 60.0 "
                             f"WHERE link_id IN ({ids})", (kmh, kmh, kmh, kmh))
        conn.commit()
    return sorted(set(closed))


def cut_off(assigner, demand, zones):
    """The trips no route serves any more once the links are closed: (trips, [zones that reach
    nowhere or cannot be reached], which O-D pairs - a mask over the matrix) - they are not
    assigned, and the results would miss them."""
    skims = assigner.graph.compute_skims().results.skims
    minutes = np.array(skims.matrix["travel_time"], dtype=float)
    if not np.array_equal(np.array(skims.index).astype(int), np.asarray(zones)):
        raise ValueError("the skim is not in zone order")
    lost = ~np.isfinite(minutes)
    np.fill_diagonal(lost, False)
    trips = float(demand[lost].sum())
    others = len(zones) - 1                      # every other zone out of reach, one way or other
    stranded = [int(z) for z, row, col in zip(zones, lost.sum(axis=1) >= others,
                                               lost.sum(axis=0) >= others) if row or col]
    return trips, stranded, lost
