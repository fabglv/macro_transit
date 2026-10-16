"""Sorocaba's demand: internal trips, the trips that cross the city limit, and through traffic."""
import numpy as np
import pandas as pd

from core import report
from core.gravity import Gravity, busiest_pairs


def internal_generation(m):
    """E8. How many trips each zone makes and receives.

    - Productions = population x a trip rate x the zone's car share / occupancy.
    - Car share varies by zone: scaled by the weighting area's 2010 car ownership against the
      city's (CAR_OWNERSHIP_ELASTICITY), then rescaled so the city average is CAR_SHARE.
    - Attractions = jobs x a rate per kind of establishment, plus a small pull per household for
      the journeys home and to visit. Rescaled to productions, so only the ratios survive.
    """
    report.section("E8. How many trips each zone makes and receives")
    s, zones = m.s, m.zones
    rel = (zones["car_share_hh"] / m.city_car_share_hh) ** s.CAR_OWNERSHIP_ELASTICITY
    zones["car_share"] = (s.CAR_SHARE * rel * zones["pop"].sum()
                          / (rel * zones["pop"]).sum()).clip(upper=0.9)
    zones["productions"] = zones["pop"] * s.TRIPS_PER_PERSON
    zones["veh_productions"] = zones["productions"] * zones["car_share"] / s.OCCUPANCY
    # The day's weights: a weekday's, or a weekend day's (CityModel.weights).
    rates, household = m.weights("ATTRACTION_RATES"), m.weights("HOUSEHOLD_PULL")
    zones["pull"] = sum(zones[f"jobs_{k}"] * r for k, r in rates.items()) \
        + zones["households"] * household
    zones["pull_work"] = zones["jobs"]
    zones["pull_study"] = zones["jobs_teaching"]
    print(f"peak-hour person trips: {zones['productions'].sum():,.0f}")
    print(f"  {zones['pop'].sum():,.0f} residents at {s.TRIPS_PER_PERSON} each")
    print(f"car share by zone: {100 * zones['car_share'].min():.0f}% to "
          f"{100 * zones['car_share'].max():.0f}%, population-weighted average "
          f"{100 * np.average(zones['car_share'], weights=zones['pop']):.0f}%")
    print(f"vehicle trips produced: {zones['veh_productions'].sum():,.0f}")
    pull = pd.Series({k: (zones[f'jobs_{k}'] * r).sum() for k, r in rates.items()})
    pull["households"] = (zones["households"] * household).sum()
    print("\nwhere the pull comes from:")
    print((100 * pull / pull.sum()).round(1).rename("% of attractions").to_string())


def external_trips(m):
    """E9. The commuters of section D as peak-hour vehicle trips, towards work and school.

    In-commuters go from their municipality's external zones to Sorocaba zones - by jobs for
    work, by teaching jobs for study. Out-commuters go from Sorocaba zones - spread over their
    weighting area by population - to the external zones of their destination. Workers drive at
    EXTERNAL_CAR_SHARE, adult students at EXTERNAL_CAR_SHARE_STUDY, under-18s not at all.
    REGIONAL_TRIP_FACTOR scales commuting up to all the region's trips. Out-commuters are
    already in the internal productions, so they are taken out of them.
    """
    report.section("E9. The trips that cross the city limit")
    s, zones = m.s, m.zones
    n_all = len(m.all_zones)
    pos = {z: i for i, z in enumerate(m.all_zones)}
    zone_idx = zones.set_index("zone_number")
    car_share = {"work": s.EXTERNAL_CAR_SHARE, "study": s.EXTERNAL_CAR_SHARE_STUDY, "school": 0.0}
    veh = {p: s.PEAK_HOUR_SHARE * c / s.OCCUPANCY for p, c in car_share.items()}
    external = np.zeros((n_all, n_all))

    for (ap, dest, purpose), part in m.flows_out.groupby(["ap", "dest", "purpose"]):
        trips = part["commuters"].sum() * veh[purpose]
        home = zone_idx[zone_idx["ap"] == ap]
        if not len(home) or dest not in m.gateway_share:
            continue
        rows = [pos[z] for z in home.index]
        spread = (home["pop"] / home["pop"].sum()).to_numpy()
        for gate, share in m.gateway_share[dest].items():
            external[rows, pos[gate]] += trips * share * spread

    for (origin, purpose), part in m.flows_in.groupby(["origin", "purpose"]):
        trips = part["commuters"].sum() * veh[purpose]
        if origin not in m.gateway_share:
            continue
        pull = zone_idx["pull_work" if purpose == "work" else "pull_study"]
        cols = [pos[z] for z in pull.index]
        spread = (pull / pull.sum()).to_numpy()
        for gate, share in m.gateway_share[origin].items():
            external[pos[gate], cols] += trips * share * spread

    inside = m.is_internal
    m.external_commuting = external
    m.external = s.REGIONAL_TRIP_FACTOR * external
    ie = m.external[np.ix_(inside, ~inside)].sum()
    ei = m.external[np.ix_(~inside, inside)].sum()
    print(f"peak-hour commuting car trips crossing the city limit: "
          f"{external[np.ix_(~inside, inside)].sum():,.0f} in, "
          f"{external[np.ix_(inside, ~inside)].sum():,.0f} out")
    print(f"with the region's other trips, x{s.REGIONAL_TRIP_FACTOR:.2f}: {ei:,.0f} in, "
          f"{ie:,.0f} out")
    print(f"  from {m.flows_in['commuters'].sum():,.0f} and {m.flows_out['commuters'].sum():,.0f} "
          f"daily commuters, {s.PEAK_HOUR_SHARE:.0%} of them in the hour, {s.OCCUPANCY} per car")
    for p, c in car_share.items():
        n_in = m.flows_in.loc[m.flows_in["purpose"] == p, "commuters"].sum()
        n_out = m.flows_out.loc[m.flows_out["purpose"] == p, "commuters"].sum()
        print(f"  {p:<7} {c:>4.0%} by car: {n_in:>7,.0f} in, {n_out:>7,.0f} out a day -> "
              f"{n_in * veh[p]:>6,.0f} and {n_out * veh[p]:>6,.0f} car trips in the hour")
    ext_pos = [pos[z] for z in m.external_zones["zone_number"]]
    m.by_ext = pd.DataFrame({
        "label": m.external_zones["label"].to_numpy(),
        "description": m.external_zones["description"].to_numpy(),
        "in": m.external[ext_pos, :].sum(axis=1),
        "out": m.external[:, ext_pos].sum(axis=0)})
    print("\nby external zone (with the region's other trips):")
    print(m.by_ext.round(0).to_string(index=False))

    out_rows = m.external[np.ix_(inside, ~inside)].sum(axis=1)
    m.zones = zones.set_index("zone_number").loc[m.all_zones[inside]].reset_index()
    m.zones["veh_productions_internal"] = (m.zones["veh_productions"] - out_rows).clip(lower=0)
    print(f"\ninternal productions after taking out-commuters out: "
          f"{m.zones['veh_productions_internal'].sum():,.0f} of "
          f"{m.zones['veh_productions'].sum():,.0f}")


def full_matrix(m):
    """E10. The O-D matrix: the gravity model inside, the external trips, and through traffic.

    THROUGH_TRIPS vehicles an hour are shared over pairs of external zones at least
    THROUGH_MIN_ANGLE degrees apart seen from the centre, in proportion to the product of their
    traffic with Sorocaba. The 2010 census journey-to-work times (all modes, door to door) are
    printed beside the model's as an upper bound, not a target.
    """
    report.section("E10. The O-D matrix")
    s, zones, inside = m.s, m.zones, m.is_internal
    cost_int = m.cost[np.ix_(inside, inside)]
    internal_ids = m.all_zones[inside]
    vectors = pd.DataFrame({"productions": zones["veh_productions_internal"].to_numpy(),
                            "attractions": zones["pull"].to_numpy()}, index=internal_ids)
    m.gravity = Gravity(cost_int, vectors, s.DETERRENCE, s.BETA_FLOOR, s.BETA_CEILING)
    internal_demand = m.gravity.solve(s.MEAN_TRIP_MIN)

    pos = {z: i for i, z in enumerate(m.all_zones)}
    n_all = len(m.all_zones)
    ext_pos = np.array([pos[z] for z in m.external_zones["zone_number"]])
    centre = m.city.centroid
    pts = m.external_zones.geometry.to_crs(m.metre_crs)
    bearing = np.arctan2(pts.y.to_numpy() - centre.y, pts.x.to_numpy() - centre.x)
    apart = np.degrees(np.abs(np.angle(np.exp(1j * (bearing[:, None] - bearing[None, :])))))
    size = (m.by_ext["in"] + m.by_ext["out"]).to_numpy()
    pattern = np.zeros((n_all, n_all))
    pattern[np.ix_(ext_pos, ext_pos)] = np.outer(size, size) * (apart >= s.THROUGH_MIN_ANGLE)
    pattern /= pattern.sum()
    m.through_pattern = pattern
    m.through = s.THROUGH_TRIPS * pattern

    demand = m.external + m.through
    demand[np.ix_(inside, inside)] = internal_demand
    ie = m.external[np.ix_(inside, ~inside)].sum()
    ei = m.external[np.ix_(~inside, inside)].sum()
    print(f"\nvehicle trips in the full matrix: {demand.sum():,.0f}")
    print(f"  internal {internal_demand.sum():,.0f}, into the city {ei:,.0f}, out of it {ie:,.0f}, "
          f"through {m.through.sum():,.0f}")
    if s.THROUGH_TRIPS:
        pairs = pd.DataFrame(m.through[np.ix_(ext_pos, ext_pos)],
                             index=m.external_zones["description"].to_numpy(),
                             columns=m.external_zones["description"].to_numpy()).stack()
        print("  the busiest through pairs:")
        for (a, b), v in pairs.sort_values(ascending=False).head(6).items():
            print(f"    {a[:34]:<35} -> {b[:34]:<35} {v:5.0f}")

    # Every trip that crosses the city limit, the through trips twice: in at one gateway and out
    # at another. The gateways must carry these.
    m.ei = demand[~inside].sum()
    m.ie = demand[:, ~inside].sum()
    m.by_ext["in"] = demand[ext_pos].sum(axis=1)
    m.by_ext["out"] = demand[:, ext_pos].sum(axis=0)

    persons = m.persons_2010
    census = persons[(persons["work_where"] == "2") & persons["work_time"].isin(list("12345"))]
    census = census.groupby("work_time")["w"].sum() / census["w"].sum()
    bands = [("up to 5 min", 0, 5, "1"), ("6 to 30 min", 5, 30, "2"),
             ("30 min to 1 h", 30, 60, "3"), ("1 to 2 h", 60, 120, "4"),
             ("over 2 h", 120, 1e9, "5")]
    print("\njourney time, model (car, free flow) against census 2010 (to work, all modes, door "
          "to door):")
    print(f"  {'band':<16}{'model':>8}{'census':>9}")
    for label, lo, hi, code in bands:
        mask = np.isfinite(cost_int) & (cost_int >= lo) & (cost_int < hi)
        print(f"  {label:<16}{100 * internal_demand[mask].sum() / internal_demand.sum():>7.1f}%"
              f"{100 * census.get(code, 0):>8.1f}%")

    report.section("Is the matrix sensible?")
    print(f"cells with any trips: {(demand > 0.01).sum():,} of {demand.size:,}")
    m.gravity.check(internal_demand)
    names = dict(zip(zones["zone_number"], zones["zone"] + " " + zones["ap_label"]))
    names.update(dict(zip(m.external_zones["zone_number"],
                          m.external_zones["label"] + " "
                          + m.external_zones["description"].str[:24])))
    busiest_pairs(demand, m.cost, m.all_zones, names, n=10)
    print("\nthe zones attracting most trips:")
    att = pd.Series(demand.sum(axis=0), index=m.all_zones)[internal_ids]
    print(zones.set_index("zone_number").assign(arriving=att)
          .nlargest(8, "arriving")[["zone", "ap_label", "pop", "jobs", "arriving"]]
          .round(0).to_string())
    return demand
