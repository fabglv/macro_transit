"""An O-D matrix loaded instead of the demand model: vehicle trips in the modelled hour.

    CSV   three columns - origin, destination, trips (or o/d, from/to, flow/volume/demand) - or,
          without names it knows, its first three columns in that order
    OMX   its first matrix, square, with a zone mapping (or its rows numbered from 1)

A zone is named by the id it had in a loaded zoning file, by its code ("Z001", an external
zone's label) or by its number, as step 1's zone list gives them (exports/zone_list.csv). A pair
not in the file has no trips; a zone the run does not have is refused, as are negative trips.
"""
import os

import numpy as np
import pandas as pd

ORIGIN = ("origin", "orig", "o", "from", "from_zone", "origin_zone")
DESTINATION = ("destination", "dest", "d", "to", "to_zone", "destination_zone")
TRIPS = ("trips", "flow", "volume", "demand", "vehicles", "veh", "value", "count")


def _column(columns, names):
    lower = {c.strip().lower(): c for c in columns}
    return next((lower[n] for n in names if n in lower), None)


def read_long(path):
    """origin, destination, trips - as text, text and numbers - from a CSV or an OMX file."""
    if path.lower().endswith(".omx"):
        import openmatrix as omx
        with omx.open_file(path, "r") as f:
            names = f.list_matrices()
            if not names:
                raise ValueError("the OMX file has no matrix")
            square = np.array(f[names[0]])
            mappings = f.list_mappings()
            ids = (list(f.mapping(mappings[0]).keys()) if mappings
                   else list(range(1, square.shape[0] + 1)))
        if square.shape[0] != square.shape[1] or len(ids) != square.shape[0]:
            raise ValueError("the OMX matrix is not square, or its mapping does not fit it")
        rows, cols = np.nonzero(square)
        ids = np.array([str(i) for i in ids], dtype=object)
        return pd.DataFrame({"origin": ids[rows], "destination": ids[cols],
                             "trips": square[rows, cols].astype(float)})
    frame = pd.read_csv(path, dtype=str, sep=None, engine="python")
    o, d, t = (_column(frame.columns, ORIGIN), _column(frame.columns, DESTINATION),
               _column(frame.columns, TRIPS))
    if not (o and d and t):
        if frame.shape[1] < 3:
            raise ValueError("the matrix needs three columns: origin, destination, trips")
        o, d, t = frame.columns[:3]
    out = pd.DataFrame({"origin": frame[o].astype(str).str.strip(),
                        "destination": frame[d].astype(str).str.strip(),
                        "trips": pd.to_numeric(frame[t].str.replace(",", ".", regex=False),
                                               errors="coerce")})
    if out["trips"].isna().any():
        bad = frame.loc[out["trips"].isna(), t].head(3).tolist()
        raise ValueError(f"trips must be numbers: {', '.join(map(str, bad))} are not")
    return out


def zone_names(zone_list):
    """{name a file may use: zone number}: the loaded zoning's ids first, then codes, then
    numbers."""
    names = {}
    for col in ("zone_number", "zone", "file_id"):          # later ones win: file ids first
        for name, number in zip(zone_list[col], zone_list["zone_number"]):
            if name is not None and str(name).strip() not in ("", "nan"):
                key = str(name).strip()
                if col == "zone_number":
                    key = str(int(float(key)))
                names[key] = int(number)
    return names


def read_matrix(path, zone_list, all_zones):
    """The loaded matrix, zones x zones in the order of `all_zones` (the skim's)."""
    long = read_long(path)
    names = zone_names(zone_list)

    def number(name):
        key = str(name).strip()
        if key in names:
            return names[key]
        try:
            return names.get(str(int(float(key))))
        except ValueError:
            return None

    long["o"] = long["origin"].map(number)
    long["d"] = long["destination"].map(number)
    unknown = sorted(set(long.loc[long["o"].isna(), "origin"])
                     | set(long.loc[long["d"].isna(), "destination"]))
    if unknown:
        raise ValueError(f"the matrix names {len(unknown)} zone(s) the run does not have: "
                         f"{', '.join(unknown[:10])}{' ...' if len(unknown) > 10 else ''} - see "
                         f"step 1's zone list")
    if (long["trips"] < 0).any():
        raise ValueError("the matrix has negative trips")
    pos = {int(z): i for i, z in enumerate(all_zones)}
    demand = np.zeros((len(all_zones), len(all_zones)))
    np.add.at(demand, (long["o"].astype(int).map(pos).to_numpy(),
                       long["d"].astype(int).map(pos).to_numpy()), long["trips"].to_numpy())
    covered = len(set(long["o"]) | set(long["d"]))
    print(f"{os.path.basename(path)}: {demand.sum():,.0f} vehicle trips, {len(long):,} pairs, "
          f"{covered} of {len(all_zones)} zones with trips")
    return demand
