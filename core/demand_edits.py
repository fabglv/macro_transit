"""A scenario's edits to the demand (core/runs.py), made on the base's matrix as the scenario's
assignment starts; the network is the base's.

    trips     trips added from zones to others, a number for each pair (and as many back, if
              both ways); or - a file may say so - a number shared among the pairs of some zones
              and others, as the base's trips between them are (evenly where it has none)
    develop   a new development in zones: residents, whose trips leave the zone at the city's
              trips per resident, going where the zone's own trips go (where the city's go, for a
              zone with none); jobs, whose trips come to it at the city's trips per job, from
              where the zone's own arrivals come - per resident, in a city with no jobs data
    growth    a trip group - within the city, out of it, into it, through it - grown or shrunk by
              a percentage

The trips are the matrix's: the modelled period's vehicle trips, an hour or a day. The rates come
from the base's matrix as it is, before any edit, so two developments do not feed each other.
"""
import numpy as np

KINDS = ("trips", "develop", "growth")
# A trip group: (origin inside the city, destination inside it).
GROUPS = {"within": (True, True), "outbound": (True, False), "inbound": (False, True),
          "through": (False, False)}
GROUP_SAID = {"within": "trips within the city", "outbound": "trips from the city to outside",
              "inbound": "trips from outside into the city", "through": "trips through the city"}


def said(edit):
    """'+500 trips from zones 12, 14 to 30, both ways', 'zone 7: 2,000 residents, 300 jobs',
    'trips through the city +20%'."""
    if edit["kind"] == "trips" and edit.get("pairs"):
        back = ", and as many back" if edit["both"] else ""
        pairs = edit["pairs"]
        if len(pairs) == 1:
            a, b, n = pairs[0]
            return f"+{n:,.0f} trips from zone {a} to zone {b}{back}"
        listed = "; ".join(f"{a}->{b}: {n:,.0f}" for a, b, n in pairs[:4])
        return (f"+{sum(n for *_, n in pairs):,.0f} trips between {len(pairs)} pairs of zones "
                f"({listed}{'; ...' if len(pairs) > 4 else ''}){back}")
    if edit["kind"] == "trips":
        return (f"+{edit['trips']:,.0f} trips from zone{'s' if len(edit['from_zones']) > 1 else ''} "
                f"{_zones(edit['from_zones'])} to {_zones(edit['to_zones'])}"
                + (", and as many back" if edit["both"] else ""))
    if edit["kind"] == "develop":
        parts = [f"{edit['residents']:,.0f} residents" if edit["residents"] else "",
                 f"{edit['jobs']:,.0f} jobs" if edit["jobs"] else ""]
        return (f"development in zone{'s' if len(edit['zones']) > 1 else ''} "
                f"{_zones(edit['zones'])}: " + ", ".join(p for p in parts if p))
    return f"{GROUP_SAID[edit['group']]} {edit['percent']:+g}%"


def _zones(zones):
    return ", ".join(map(str, zones[:6])) + (f" and {len(zones) - 6} more" if len(zones) > 6 else "")


def apply(model, edits):
    """The edits made on `model.demand`, in order; each edit gets the trips it added (`added`,
    negative if it took some away), and is printed."""
    base = np.asarray(model.demand, dtype=float)
    demand = base.copy()
    pos = {int(z): i for i, z in enumerate(model.all_zones)}
    inside = np.asarray(model.is_internal)
    zones = model.zones.set_index("zone_number")
    # The city's rates, from the base: trips leaving its zones per resident, reaching them per job.
    pop = float(zones["pop"].sum())
    per_resident = base[inside].sum() / pop if pop else 0.0
    jobs = float(zones["jobs"].sum()) if "jobs" in zones else 0.0
    per_job = base[:, inside].sum() / jobs if jobs else per_resident
    for edit in edits:
        before = demand.sum()
        if edit["kind"] == "trips" and edit.get("pairs"):
            for a, b, n in edit["pairs"]:
                i, j = _positions([a, b], pos)
                demand[i, j] += n
                if edit["both"]:
                    demand[j, i] += n
        elif edit["kind"] == "trips":
            pairs = [(edit["from_zones"], edit["to_zones"])]
            if edit["both"]:
                pairs.append((edit["to_zones"], edit["from_zones"]))
            for origins, destinations in pairs:
                rows, cols = _positions(origins, pos), _positions(destinations, pos)
                other = rows[:, None] != cols[None, :]          # a zone's trips to itself: none
                weight = base[np.ix_(rows, cols)] * other
                if weight.sum() <= 0:
                    weight = other.astype(float)
                demand[np.ix_(rows, cols)] += edit["trips"] * weight / weight.sum()
        elif edit["kind"] == "develop":
            share = len(edit["zones"])
            for zone in edit["zones"]:
                i = _positions([zone], pos)[0]
                row, col = base[i].copy(), base[:, i].copy()
                row[i] = col[i] = 0.0
                # Where the zone's trips go, and come from; the city's, for a zone with none.
                goes = row if row.sum() > 0 else base[inside].sum(axis=0)
                comes = col if col.sum() > 0 else base[:, inside].sum(axis=1)
                demand[i] += edit["residents"] / share * per_resident * goes / goes.sum()
                demand[:, i] += edit["jobs"] / share * per_job * comes / comes.sum()
        else:
            o, d = GROUPS[edit["group"]]
            group = (inside == o)[:, None] & (inside == d)[None, :]
            demand[group] *= 1 + edit["percent"] / 100
        edit["added"] = round(float(demand.sum() - before), 1)
        print(f"  {said(edit)}: {edit['added']:+,.0f} trips")
    print(f"the matrix: {base.sum():,.0f} -> {demand.sum():,.0f} trips "
          f"({demand.sum() - base.sum():+,.0f})")
    model.demand = demand


def _positions(zones, pos):
    missing = [z for z in zones if int(z) not in pos]
    if missing:
        raise ValueError(f"no zone {', '.join(map(str, missing))} in the city's zones")
    return np.array([pos[int(z)] for z in zones])
