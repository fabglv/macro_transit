"""Speed, capacity and free-flow time on every link, and the roundabouts.

OSM's own `maxspeed` and lane counts are kept wherever the import found them; a value by road
class fills the rest. Capacity is **per lane**, and the per-lane rate comes from **free-flow
speed** rather than the OSM class: you cannot post 90 km/h on a road with traffic lights, so
speed is the usable proxy for whether traffic has to stop. A one-way link gets no capacity in the
direction it does not carry.

**Connectors are deliberately unlimited.** A connector is not a road; a real capacity would make
the zone system congest rather than the traffic.
"""
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components


def set_link_costs(project, s):
    """Fill speed, capacity and free-flow time. Returns any road class with no values of its own.

    `s` is the city's settings: SPEED_KMH, LANE_CAPACITY_BY_SPEED, DEFAULT_LANES, DEFAULT_SPEED,
    DEFAULT_LANE_CAPACITY, CONNECTOR_SPEED, CONNECTOR_CAPACITY.
    """
    with project.db_connection as conn:
        from_osm = pd.read_sql("SELECT count(*) n FROM links WHERE speed_ab IS NOT NULL",
                               conn).iloc[0, 0]
        links = pd.read_sql(
            "SELECT link_id, link_type, direction, lanes_ab, lanes_ba, speed_ab, speed_ba "
            "FROM links", conn)

    road = (links["link_type"] != "centroid_connector").to_numpy()
    unlisted = sorted({t for t in links.loc[road, "link_type"].dropna().unique()
                       if t not in s.SPEED_KMH})
    if unlisted:
        raise ValueError(f"link types with no speed or capacity of their own: {unlisted}")

    fallback = links["link_type"].map(s.DEFAULT_LANES).fillna(1)
    speed_by_class = links["link_type"].map(s.SPEED_KMH).fillna(s.DEFAULT_SPEED)

    tagged, unreadable = {}, {}
    for side in ("ab", "ba"):
        # AequilibraE splits a two-way `lanes` tag between the directions, so halves turn up;
        # round half up and never go below one lane in a direction that exists.
        raw = pd.to_numeric(links[f"lanes_{side}"], errors="coerce")
        known = (raw > 0).to_numpy()
        lanes = np.where(known, np.maximum(1.0, np.floor(raw.fillna(0) + 0.5)), fallback)
        tagged[side] = known & road

        # Speed first, then read back to choose the per-lane rate. OSM maxspeed is free text;
        # anything unreadable, or zero, is treated as missing, so the class value applies.
        osm_speed = pd.to_numeric(links[f"speed_{side}"], errors="coerce")
        osm_speed = osm_speed.where(osm_speed > 0)
        unreadable[side] = int((links[f"speed_{side}"].notna() & osm_speed.isna()).sum())
        links[f"speed_{side}"] = np.where(road, osm_speed.fillna(speed_by_class),
                                          s.CONNECTOR_SPEED)
        kmh = links[f"speed_{side}"].to_numpy(dtype=float)
        per_lane = np.full(len(links), float(s.DEFAULT_LANE_CAPACITY))
        for floor, rate in sorted(s.LANE_CAPACITY_BY_SPEED):
            per_lane = np.where(kmh >= floor, float(rate), per_lane)
        # A one-way link carries nothing the other way: direction 1 runs a->b, -1 runs b->a.
        exists = (links["direction"] != (-1 if side == "ab" else 1)).to_numpy()
        links[f"capacity_{side}"] = np.where(road, np.where(exists, per_lane * lanes, 0.0),
                                             s.CONNECTOR_CAPACITY)
        links[f"lanes_{side}"] = np.where(road, lanes, 1.0)

    rows = list(zip(links["speed_ab"].astype(float), links["speed_ba"].astype(float),
                    links["capacity_ab"].astype(float), links["capacity_ba"].astype(float),
                    links["link_id"].astype(int)))
    with project.db_connection as conn:
        conn.executemany("UPDATE links SET speed_ab = ?, speed_ba = ?, capacity_ab = ?, "
                         "capacity_ba = ? WHERE link_id = ?", rows)
        # Free-flow travel time, in MINUTES - the unit every cost in the model uses.
        conn.execute("UPDATE links SET travel_time_ab = (distance / 1000.0) / speed_ab * 60.0, "
                     "travel_time_ba = (distance / 1000.0) / speed_ba * 60.0")
        conn.commit()

    n_road = int(road.sum())
    known_either = tagged["ab"] | tagged["ba"]
    print(f"lane counts taken from OSM: {100 * known_either.sum() / n_road:.0f}% of "
          f"{n_road:,} roads in at least one direction; the rest use DEFAULT_LANES")
    if sum(unreadable.values()):
        print(f"  {sum(unreadable.values())} OSM maxspeed values were not numbers and were "
              f"treated as missing")

    print("\n  what each speed band was given:")
    kmh_ab = links["speed_ab"].to_numpy(dtype=float)
    upper = np.inf
    for floor, rate in sorted(s.LANE_CAPACITY_BY_SPEED, reverse=True):
        inside = road & (kmh_ab >= floor) & (kmh_ab < upper)
        top = "and up" if upper == np.inf else f"to {int(upper)}"
        print(f"    {floor:>3} km/h {top:<7} {rate:>5,} veh/h per lane  {inside.sum():>7,} links")
        upper = floor

    main = ["motorway", "trunk", "primary", "secondary", "tertiary"]
    shown = links[road & links["link_type"].isin(main)]
    summary = shown.groupby("link_type").agg(links=("link_id", "size"), lanes=("lanes_ab", "mean"),
                                             kmh=("speed_ab", "mean"), veh_h=("capacity_ab", "mean"))
    print("\n  the classes that carry the load:")
    for lt in [t for t in main if t in summary.index]:
        r = summary.loc[lt]
        print(f"    {lt:<10} {r.links:>6,.0f} links  {r.lanes:>4.1f} lanes  {r.kmh:>4.0f} km/h  "
              f"{r.veh_h:>6,.0f} veh/h per direction")

    with project.db_connection as conn:
        check = pd.read_sql(
            "SELECT count(*) links, sum(speed_ab IS NULL) no_speed, sum(capacity_ab IS NULL) "
            "no_cap, sum(travel_time_ab IS NULL) no_time, round(max(travel_time_ab), 1) slowest "
            "FROM links", conn)
    print(f"\nspeeds taken from OSM maxspeed: {from_osm:,} links; the rest by road class")
    print(check.to_string(index=False))


def set_roundabout_capacity(project):
    """Give each roundabout at least the capacity of the largest road that enters it.

    OSM records the circulating carriageway, often with too few lanes, and a model with no
    junction delay anywhere should not make the ring the one junction that constrains. A
    roundabout is a connected set of `junction=roundabout` (or `circular`) links, grouped by
    connectivity rather than by name so the unnamed ones are handled too. A ring already
    carrying more keeps its own. Its entries are still not modelled.
    """
    with project.db_connection as conn:
        links = pd.read_sql("SELECT link_id, a_node, b_node, name, link_type, junction, "
                            "capacity_ab, capacity_ba FROM links", conn)
    circle = links[links["junction"].isin(["roundabout", "circular"])]
    if not len(circle):
        print("no links tagged junction=roundabout")
        return pd.DataFrame()

    nodes = pd.unique(circle[["a_node", "b_node"]].to_numpy().ravel())
    seat = {n: i for i, n in enumerate(nodes)}
    _, part = connected_components(
        coo_matrix((np.ones(len(circle)), (circle["a_node"].map(seat), circle["b_node"].map(seat))),
                   shape=(len(nodes), len(nodes))), directed=False)
    circle = circle.assign(ring=circle["a_node"].map(dict(zip(nodes, part))))

    roads = links[~links["junction"].isin(["roundabout", "circular"])
                  & (links["link_type"] != "centroid_connector")]
    updates, report = [], []
    for ring, part_links in circle.groupby("ring"):
        on_ring = set(part_links["a_node"]) | set(part_links["b_node"])
        # An approach is a road touching the ring but not part of it. The largest approach, not
        # the total: the ring should never be the reason one approach cannot discharge.
        approach = roads[roads["a_node"].isin(on_ring) | roads["b_node"].isin(on_ring)]
        if not len(approach):
            continue
        feeds = float(approach[["capacity_ab", "capacity_ba"]].max(axis=1).max())
        was = float(part_links[["capacity_ab", "capacity_ba"]].max(axis=1).mean())
        updates += [(max(feeds, float(ab)), max(feeds, float(ba)), int(i))
                    for i, ab, ba in zip(part_links["link_id"], part_links["capacity_ab"],
                                         part_links["capacity_ba"])]
        report.append({"ring": int(ring), "links": len(part_links), "approaches": len(approach),
                       "was": was, "now": feeds})
    with project.db_connection as conn:
        conn.executemany("UPDATE links SET capacity_ab = ?, capacity_ba = ? WHERE link_id = ?",
                         updates)
        conn.commit()
    frame = pd.DataFrame(report)
    print(f"{len(frame)} roundabouts, {len(circle):,} links, recosted from their approaches")
    print(f"  capacity per link: median {frame['was'].median():,.0f} -> "
          f"{frame['now'].median():,.0f} veh/h; approaches per roundabout: median "
          f"{frame['approaches'].median():.0f}")
    return frame
