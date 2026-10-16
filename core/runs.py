"""Named road runs: a city's road model with some of its parameters changed.

A run is a small file, macro_runs/<city>/<name>.json, listing only what it changes:

    {"label": "Car share 40%", "description": "...",
     "parameters": {"CAR_SHARE": 0.4, "BPR_ALPHA_BETA": [0.15, 5.0]}}

    python run.py sorocaba --run car_share_40      output/macro/sorocaba-car_share_40/

The names are those of the city's settings module (cases/<city>/settings.py), each value in the
shape of the module's own (core.settings.conform). The run hands them to the module as it is
imported (core.settings.OVERRIDES), so anything the module works out from a value follows it,
and its results page marks each value it changed. *baseline* is the settings module as it is, with
no file: its results are output/macro/<city>/.

The Run a macrosimulation page (core/macro_page.py, when served) writes and runs these files.

A **scenario** is a run made from another, computed one - its *base* - with **edits** to the
network, and nothing else of its own: its parameters and files are the base's, so the difference
between the two is the edits alone.

    {"label": "Bolivar closed", "base": "baseline",
     "edits": [{"kind": "close", "links": [101, 102], "label": "Avenida Simon Bolivar"},
               {"kind": "capacity", "links": [...], "factor": 1.5, "label": "..."},
               {"kind": "speed", "links": [...], "kmh": 50, "label": "..."}]}

It takes its base's zones and demand as they are (core/steps.reuse) and runs the assignment with
the edits (core/edits.py). The Scenarios page (core/scenario_page.py) writes and runs these.
"""
import importlib
import json
import os
import re

from .paths import MACRO_OUTPUT, ROOT

RUNS = os.path.join(ROOT, "macro_runs")
BASELINE = "baseline"
NAME = re.compile(r"^[a-z0-9][a-z0-9_]{0,59}$")


def path(city, name):
    return os.path.join(RUNS, city, f"{name}.json")


def output_dir(city, name):
    """Where a run's results go: the baseline's in output/macro/<city>/, a named run's next to it."""
    return os.path.join(MACRO_OUTPUT, city if name == BASELINE else f"{city}-{name}")


def defaults(city):
    """{name: the settings module's value} and the parameters as the page lists them: [{group,
    name, value, unit, kind, why}], in the results page's order."""
    from cases import CASES
    if city not in CASES:
        raise ValueError(f"unknown city {city!r}")
    module = importlib.import_module(CASES[city][2])
    rows = module.ASSUMED.parameters().drop(columns="default").to_dict("records")
    return {r["name"]: r["value"] for r in rows}, rows


def load(city, name):
    """A saved run, checked against the city's parameters; the baseline is one with no changes.
    Imports the settings module: not for run.py (read, apply)."""
    return check(city, name, read(city, name))


def check(city, name, run):
    """The run with its label filled in and its parameters in their modules' shapes; raises
    ValueError naming what does not fit. A scenario's are its base's, read again here."""
    from .settings import conform
    if run.get("base"):
        return check_scenario(city, name, run)
    known, _ = defaults(city)
    parameters = run.get("parameters") or {}
    unknown = sorted(set(parameters) - set(known))
    if unknown:
        raise ValueError(f"{city} has no parameter {', '.join(unknown)}")
    out = {}
    for key, value in parameters.items():
        value = conform(value, known[key], key)
        if value != known[key]:                   # the module's own value is no change
            out[key] = value
    loads = {key: run.get(key) for key in INPUTS if run.get(key)}
    if name == BASELINE and (out or loads):
        raise ValueError("the baseline is the settings as they are: save the changes - and any "
                         "file it loads - under a name of their own")
    for key, meta in loads.items():
        if not isinstance(meta, dict) or not meta.get("file"):
            raise ValueError(f"{key}: expected the file it loads")
        if not os.path.isfile(os.path.join(files_dir(city, run.get("files_from", name)),
                                           meta["file"])):
            raise ValueError(f"{key}: {meta['file']} has not been uploaded for {name}")
    return {"name": name, "label": (run.get("label") or name).strip(),
            "description": (run.get("description") or "").strip(), "parameters": out,
            "zoning": loads.get("zoning"), "od_matrix": loads.get("od_matrix")}


EDIT_KINDS = {"close": "closed", "capacity": "capacity x", "speed": "speed", "road": "new road",
              "trips": "trips added", "develop": "development", "growth": "trip group grown"}
# A scenario is of one type, and its edits of that type's kinds: a closure's effect is where the
# traffic goes (volumes), a capacity or speed change's is how congested the roads get (V/C) -
# measured, and mapped, differently (core/maps.draw_scenario).
SCENARIO_TYPES = {"closure": ("close",), "capacity": ("capacity", "speed"), "newroad": ("road",),
                  "demand": ("trips", "develop", "growth")}
# What a scenario may set of its own, beside its base's parameters: how close its assignment
# converges (the Scenarios page's choice).
SCENARIO_PARAMETERS = {"RGAP_TARGET_MAX_ITER"}
# A new road's class: the main ones, whose speed, lanes and capacity the settings give.
ROAD_CLASSES = ("motorway", "trunk", "primary", "secondary", "tertiary")


def scenario_type(edits):
    """A scenario's type from its edits: 'closure', 'newroad', else 'capacity'."""
    kinds = {e.get("kind") for e in edits}
    if kinds & set(SCENARIO_TYPES["demand"]):
        return "demand"
    return "closure" if "close" in kinds else "newroad" if "road" in kinds else "capacity"


def _demand_edit(k, edit):
    """An edit to the demand as checked: trips added between zones, a development, a trip group
    grown (core/demand_edits.py)."""
    kind, label = edit["kind"], str(edit.get("label") or "").strip()
    zones = lambda key: sorted({int(z) for z in edit.get(key) or []})       # noqa: E731
    try:
        if kind == "trips" and edit.get("pairs") is not None:
            # A number for each pair: [[from, to, trips], ...]; the zones and the total with it.
            pairs = [[int(a), int(b), float(n)] for a, b, n in edit["pairs"]]
            if not pairs:
                raise ValueError(f"edit {k}: trips go from a zone to another: pick both")
            if any(a == b for a, b, _ in pairs):
                raise ValueError(f"edit {k}: trips go from a zone to another, not to itself")
            if any(not 0 < n <= 1_000_000 for *_, n in pairs):
                raise ValueError(f"edit {k}: each pair's trips added are more than 0")
            if len({(a, b) for a, b, _ in pairs}) < len(pairs):
                raise ValueError(f"edit {k}: a pair of zones is given twice")
            out = {"kind": kind, "label": label, "pairs": pairs, "both": bool(edit.get("both")),
                   "from_zones": sorted({a for a, _, _ in pairs}),
                   "to_zones": sorted({b for _, b, _ in pairs}),
                   "trips": sum(n for *_, n in pairs)}
        elif kind == "trips":
            out = {"kind": kind, "label": label, "from_zones": zones("from_zones"),
                   "to_zones": zones("to_zones"), "trips": float(edit.get("trips", 0)),
                   "both": bool(edit.get("both"))}
            if not out["from_zones"] or not out["to_zones"]:
                raise ValueError(f"edit {k}: trips go from some zones to others: pick both")
            if out["from_zones"] == out["to_zones"] and len(out["from_zones"]) == 1:
                raise ValueError(f"edit {k}: trips go from a zone to another")
            if not 0 < out["trips"] <= 1_000_000:
                raise ValueError(f"edit {k}: the trips added are more than 0")
        elif kind == "develop":
            out = {"kind": kind, "label": label, "zones": zones("zones"),
                   "residents": float(edit.get("residents") or 0), "jobs": float(edit.get("jobs") or 0)}
            if not out["zones"]:
                raise ValueError(f"edit {k}: a development is in a zone: pick one")
            if out["residents"] < 0 or out["jobs"] < 0 or not out["residents"] + out["jobs"]:
                raise ValueError(f"edit {k}: a development brings residents, jobs, or both")
        else:
            from .demand_edits import GROUPS
            out = {"kind": kind, "label": label, "group": str(edit.get("group")),
                   "percent": float(edit.get("percent", 0))}
            if out["group"] not in GROUPS:
                raise ValueError(f"edit {k}: a trip group is one of {', '.join(GROUPS)}")
            if not -100 <= out["percent"] <= 1000 or not out["percent"]:
                raise ValueError(f"edit {k}: a trip group changes by -100% to +1000%, not 0")
    except (TypeError, ValueError) as problem:
        if str(problem).startswith(f"edit {k}"):
            raise
        raise ValueError(f"edit {k}: {problem}") from None
    return out


def _road(k, edit):
    """A new road as checked: its two junctions, the points it bends through, its class, lanes
    each way, free-flow speed, capacity a lane, one way or not, its name."""
    try:
        out = {"kind": "road", "label": str(edit.get("label") or "").strip(),
               "from_node": int(edit["from_node"]), "to_node": int(edit["to_node"]),
               "points": [[round(float(lat), 6), round(float(lon), 6)]
                          for lat, lon in edit.get("points") or []],
               "link_type": str(edit.get("link_type")), "lanes": int(edit.get("lanes", 0)),
               "kmh": float(edit.get("kmh", 0)), "lane_capacity": float(edit.get("lane_capacity", 0)),
               "oneway": bool(edit.get("oneway"))}
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"edit {k}: a new road needs its two junctions, class, lanes, speed and "
                         f"capacity") from None
    if out["from_node"] == out["to_node"]:
        raise ValueError(f"edit {k}: a new road joins two different junctions")
    if out["link_type"] not in ROAD_CLASSES:
        raise ValueError(f"edit {k}: a new road's class is one of {', '.join(ROAD_CLASSES)}")
    if not 1 <= out["lanes"] <= 6:
        raise ValueError(f"edit {k}: a new road has 1 to 6 lanes each way")
    if not 1 <= out["kmh"] <= 150:
        raise ValueError(f"edit {k}: the speed is between 1 and 150 km/h")
    if not 100 <= out["lane_capacity"] <= 3000:
        raise ValueError(f"edit {k}: the capacity is between 100 and 3,000 vehicles an hour a lane")
    if len(out["points"]) > 200:
        raise ValueError(f"edit {k}: a new road bends through 200 points at most")
    if edit.get("links"):                    # its link, once a run has added it
        out["links"] = [int(i) for i in edit["links"]]
    return out


def _on_network(city, base_name, edits):
    """The links and junctions the edits name are on the base's network - when its zones step
    has made one to look in; else the run itself checks (core/edits.py)."""
    import sqlite3
    from contextlib import closing

    from .steps import folder
    db = os.path.join(folder(output_dir(city, base_name)), "road_model", "project_database.sqlite")
    if not os.path.isfile(db):
        return
    links = sorted({int(i) for e in edits if e["kind"] in ("close", "capacity", "speed")
                    for i in e["links"]})
    nodes = sorted({int(e[k]) for e in edits if e["kind"] == "road" for k in ("from_node", "to_node")})
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as conn:
        found = {r[0] for r in conn.execute(f"SELECT link_id FROM links WHERE link_id IN "
                                            f"({','.join(map(str, links)) or 'NULL'})")}
        junctions = {r[0] for r in conn.execute(f"SELECT node_id FROM nodes WHERE is_centroid = 0 "
                                                f"AND node_id IN ({','.join(map(str, nodes)) or 'NULL'})")}
    missing = [i for i in links if i not in found]
    if missing:
        raise ValueError(f"link{'s' if len(missing) > 1 else ''} "
                         f"{', '.join(map(str, missing[:10]))} not on {base_name}'s network")
    missing = [n for n in nodes if n not in junctions]
    if missing:
        raise ValueError(f"junction{'s' if len(missing) > 1 else ''} "
                         f"{', '.join(map(str, missing))} not on {base_name}'s network")


def check_scenario(city, name, body):
    """A scenario as saved: its base a computed-or-not run (not a scenario), its edits each a kind,
    links and the number the kind needs. Its parameters and files are the base's - and of its own,
    SCENARIO_PARAMETERS (`own_parameters`)."""
    from .settings import conform
    if name == BASELINE:
        raise ValueError("the baseline is the settings as they are: a scenario has a name of its own")
    base_name = body["base"]
    if base_name == name:
        raise ValueError("a scenario cannot be its own base")
    base = check(city, base_name, read(city, base_name))
    if base.get("base"):
        raise ValueError(f"{base_name} is a scenario: a scenario is made from a run")
    edits = []
    for k, edit in enumerate(body.get("edits") or [], 1):
        kind = edit.get("kind")
        if kind not in EDIT_KINDS:
            raise ValueError(f"edit {k}: a kind is one of {', '.join(EDIT_KINDS)}")
        if kind == "road":
            edits.append(_road(k, edit))
            continue
        if kind in SCENARIO_TYPES["demand"]:
            edits.append(_demand_edit(k, edit))
            continue
        links = sorted({int(x) for x in edit.get("links") or []})
        if not links:
            raise ValueError(f"edit {k}: no links")
        out = {"kind": kind, "links": links, "label": str(edit.get("label") or "").strip()}
        if kind == "capacity":
            factor = float(edit.get("factor", 0))
            if not 0 < factor <= 10:
                raise ValueError(f"edit {k}: the capacity factor is between 0 and 10")
            out["factor"] = factor
        if kind == "speed":
            kmh = float(edit.get("kmh", 0))
            if not 1 <= kmh <= 150:
                raise ValueError(f"edit {k}: the speed is between 1 and 150 km/h")
            out["kmh"] = kmh
        edits.append(out)
    if not edits:
        raise ValueError("a scenario needs at least one edit")
    kind = body.get("type") or scenario_type(edits)
    if kind not in SCENARIO_TYPES:
        raise ValueError(f"a scenario's type is one of {', '.join(SCENARIO_TYPES)}")
    if any(e["kind"] not in SCENARIO_TYPES[kind] for e in edits):
        raise ValueError("a scenario is of one kind - it closes roads, changes their capacity or "
                         "speed, builds new ones, or changes the demand: their effects are "
                         "measured differently. Make a scenario of each.")
    _on_network(city, base_name, edits)
    # Its own parameters: SCENARIO_PARAMETERS only, over its base's. A scenario read back from
    # its file (`read`) carries its base's merged in as `parameters`, and its own apart.
    own = (body["own_parameters"] if "own_parameters" in body else body.get("parameters")) or {}
    unknown = sorted(set(own) - SCENARIO_PARAMETERS)
    if unknown:
        raise ValueError(f"a scenario takes its base's parameters; of its own only "
                         f"{', '.join(sorted(SCENARIO_PARAMETERS))}, not {', '.join(unknown)}")
    known, _ = defaults(city)
    own = {k: conform(v, known[k], k) for k, v in own.items()}
    parameters = {k: v for k, v in (base["parameters"] | own).items() if v != known[k]}
    return base | {"parameters": parameters, "own_parameters": own,
                   "name": name, "label": (body.get("label") or name).strip(),
                   "description": (body.get("description") or "").strip(),
                   "base": base_name, "type": kind, "edits": edits,
                   "files_from": base.get("files_from", base_name)}


def save(city, name, body):
    """Write a run's file, checked first; returns the run as saved."""
    if name == BASELINE:
        return check(city, name, body)
    if not NAME.match(name or ""):
        raise ValueError("a run's name is lower-case letters, digits and _ (no spaces, no -)")
    run = check(city, name, body)
    os.makedirs(os.path.dirname(path(city, name)), exist_ok=True)
    if run.get("base"):                   # a scenario: its base, its edits, its own settings
        body = {k: run[k] for k in ("label", "description", "base", "type", "edits")}
        if run.get("own_parameters"):
            body["parameters"] = run["own_parameters"]
        with open(path(city, name), "w", encoding="utf-8") as f:
            json.dump(body, f, indent=1, ensure_ascii=False)
        return run
    with open(path(city, name), "w", encoding="utf-8") as f:
        json.dump({k: run[k] for k in ("label", "description", "parameters", "zoning",
                                       "od_matrix") if run[k] is not None or k == "parameters"},
                  f, indent=1, ensure_ascii=False)
    return run


def saved(city):
    """Every saved run of the city: [run], by name, each with whether it has results."""
    folder = os.path.join(RUNS, city)
    names = sorted(f[:-5] for f in os.listdir(folder) if f.endswith(".json")) \
        if os.path.isdir(folder) else []
    out = []
    for name in names:
        try:
            run = load(city, name)
        except (ValueError, json.JSONDecodeError) as problem:     # listed, with what is wrong
            run = {"name": name, "label": name, "description": "", "parameters": {},
                   "error": str(problem)}
        run["done"] = os.path.isfile(os.path.join(output_dir(city, name), "summary.json"))
        out.append(run)
    return out


def read(city, name):
    """A run's file as written, unchecked - for run.py, which must hand it to the settings module
    before anything imports it (checking imports it); `apply` then `unknown` check it there."""
    if name == BASELINE:
        return {"name": BASELINE, "label": "baseline", "description": "", "parameters": {},
                "zoning": None, "od_matrix": None}
    if not NAME.match(name or ""):
        raise ValueError(f"a run's name is lower-case letters, digits and _: {name!r}")
    try:
        with open(path(city, name), encoding="utf-8") as f:
            run = json.load(f)
    except FileNotFoundError:
        raise ValueError(f"no run {name!r} for {city}: {path(city, name)}") from None
    out = {"name": name, "label": (run.get("label") or name).strip(),
           "description": (run.get("description") or "").strip(),
           "parameters": run.get("parameters") or {},
           "zoning": run.get("zoning"), "od_matrix": run.get("od_matrix")}
    if run.get("base"):                   # a scenario: the base's parameters and files, its edits
        base = read(city, run["base"])
        if base.get("base"):
            raise ValueError(f"{name}'s base, {run['base']}, is a scenario itself: a scenario is "
                             f"made from a run")
        out.update({k: base[k] for k in ("parameters", "zoning", "od_matrix")})
        own = {k: v for k, v in (run.get("parameters") or {}).items() if k in SCENARIO_PARAMETERS}
        out["parameters"] = {**base["parameters"], **own}
        out["own_parameters"] = own
        out.update(base=run["base"], edits=run.get("edits") or [],
                   type=run.get("type") or scenario_type(run.get("edits") or []),
                   files_from=base.get("files_from", base["name"]))
    return out


# --- the files a run loads ---------------------------------------------------------------------
# A zoning file (step 1) and an O-D matrix (step 2), kept beside the run's file in
# macro_runs/<city>/<name>_files/. The run's file names them: {"zoning": {"file": "zoning.gpkg",
# "name": "the name it was uploaded as", "id_column": "..."}, "od_matrix": {"file": ..., "name":}}.
INPUTS = {"zoning": (".gpkg", ".geojson", ".json", ".zip"), "od_matrix": (".csv", ".omx")}


def files_dir(city, name):
    return os.path.join(RUNS, city, f"{name}_files")


def inputs_of(city, run):
    """{key: {"path", "name", ...}} of the files the run loads, for the model; {} for none."""
    out = {}
    for key in INPUTS:
        meta = run.get(key)
        owner = run.get("files_from", run["name"])          # a scenario's: its base's
        if meta and meta.get("file"):
            out[key] = {k: v for k, v in meta.items() if k != "file"} | {
                "path": os.path.join(files_dir(city, owner), meta["file"])}
            if not os.path.isfile(out[key]["path"]):
                raise ValueError(f"{run['name']} loads {meta.get('name', meta['file'])}, which is "
                                 f"not in {files_dir(city, owner)}")
    return out


def fingerprints(city, run):
    """{step: fingerprint} of a run as saved - what core/steps.py records when a step is
    computed with it, so a step done with other values or files shows as needing computing."""
    from . import steps
    known, rows = defaults(city)
    values = dict(known) | run["parameters"]
    groups = {r["name"]: r["group"] for r in rows}
    inputs = inputs_of(city, run)
    return {k: steps.fingerprint(values, groups, k, inputs, run.get("edits"))
            for k in steps.STEPS}


def step_states(city, run):
    """For the page: each step's state for the run as saved - done, stale or missing - and the
    preview each done step left."""
    from . import steps
    folder = output_dir(city, run["name"])
    try:
        current = fingerprints(city, run)
    except ValueError:
        current = {}
    status = steps.read_status(folder)
    return {k: {"state": v, "preview": (status.get(k) or {}).get("preview"),
                "finished": (status.get(k) or {}).get("finished"),
                "minutes": (status.get(k) or {}).get("minutes")}
            for k, v in steps.states(folder, current).items()}


def apply(run):
    """Hand the run's values to the settings module, which must not be imported yet: each is
    put in its module value's shape as the module registers it (core.settings.conform)."""
    import sys
    from cases import CASES
    from .settings import OVERRIDES
    module = CASES[run["city"]][2] if "city" in run else None
    if module and module in sys.modules:
        raise RuntimeError(f"{module} is imported already: a run's values would not reach it")
    OVERRIDES.clear()
    OVERRIDES.update(run["parameters"])


def unknown(run, settings):
    """The run's parameter names the settings module does not have."""
    registry = settings.ASSUMED
    return sorted(set(run["parameters"]) - set(registry.entries) - set(registry.settings))
