"""A road run in three steps, each computed on its own and kept, so the next can start from it.

    1  zones       the zones, the road network, speeds and capacities, the connectors, and the
                   free-flow times between every two zones (with a city's external zones)
    2  demand      the trip matrix: generated and distributed by the city's model, or loaded
    3  assignment  the matrix on the network, the cost function, the checks, the exports and
                   the results page

    python run.py sorocaba --run car_share_40 --step zones
    python run.py sorocaba --run car_share_40 --step demand
    python run.py sorocaba --run car_share_40 --step assignment

Without --step a run does the three in one go, the same way. Each step leaves, in the run's
output folder under steps/:

    status.json      for each step done: when, what it was computed with (a fingerprint), a
                     preview of what it made, and its log
    zones.pkl        the model's state after the step, read back by the next (pickle)
    demand.pkl
    road_model/      the AequilibraE project after step 1: the assignment starts from a fresh
                     copy of it, so it can be run again and again

A step runs only when the steps before it are done with what the run says now: its fingerprint
is every parameter of its step and the steps before it, and the files it reads (a zoning file
for step 1, a matrix for step 2). Change a step's parameter and that step and the ones after it
need computing again; the ones before do not.

Which step a parameter belongs to is where the model reads it (STEP_OF_GROUP, STEP_OF_NAME): a
parameter of no listed group is a step-1 one, so changing it computes everything again.
"""
import hashlib
import json
import os
import pickle
import shutil
import time

STEPS = ["zones", "demand", "assignment"]
LABELS = {"zones": "Zones", "demand": "Demand", "assignment": "Assignment"}

STEP_OF_GROUP = {
    "Network parameters": "zones", "Zone parameters": "zones",
    "Trip generation parameters": "demand", "Gravity model parameters": "demand",
    "Time of day parameters": "demand",
    "External traffic parameters": "demand",
    "Cost function parameters": "assignment", "Simulation parameters": "assignment",
    "Reporting parameters": "assignment", "Count comparison parameters": "assignment",
}
# Read in another step than their group's: everything that builds Sorocaba's external zones (its
# commuting, gateways and regional roads) is step 1's; THROUGH_SHARE is read only by the count
# comparison. INTRAZONAL_SHARE, a gravity model choice, is applied again in step 2
# (skim.with_intrazonal), so it is step 2's.
STEP_OF_NAME = {
    "STRICT_SKIM": "zones",
    "EXTERNAL_ZONES": "zones", "DAILY_COMMUTE_PERCENTILE": "zones", "REACH_KM": "zones",
    "GATEWAY_ROADS": "zones", "REGIONAL_SPEED_KMH": "zones", "ACCESS_KMH": "zones",
    "FAR_ACCESS_KMH": "zones", "ACCESS_SLACK_MIN": "zones", "MUNI_MIN_COMMUTERS": "zones",
    "VOTORANTIM_MIN_COMMUTERS": "zones", "POOL_MIN_COMMUTERS": "zones",
    "RING_MIN_COMMUTERS": "zones",
    "THROUGH_SHARE": "assignment",
}
# The model's state that does not go into a step's pickle: the settings (imported again with the
# run's values), the paths, the open AequilibraE project, what run.py sets, and the assignment's
# own objects (made again by step 3).
NOT_KEPT = {"s", "paths", "model", "run_info", "inputs", "assigner", "results", "fingerprints",
            "staged", "base_run", "edits"}
FOLDER = "steps"
STATUS = "status.json"


# What the Run a macrosimulation page lets a run decide. Step 1's parameters are not among them:
# its zones are the city's or a file's, and its network is the city's as it is (alternative
# networks will be scenarios of their own). The reporting factors are not the run's to decide.
# A run's file may still set any of them (run.py --run), as before.
NOT_ON_PAGE = {"PEAK_TRIPS_PER_DAY", "WORKING_DAYS"}
# A text parameter with a fixed set of values: a choice, or - one value - shown, not edited.
CHOICES = {"DETERRENCE": ["EXPO"], "DAY": ["weekday", "weekend"],
           "PERIOD": ["morning peak", "midday", "evening peak", "night", "whole day"]}


def step_of(name, group):
    return STEP_OF_NAME.get(name) or STEP_OF_GROUP.get(group, "zones")


def on_page(name, group):
    return step_of(name, group) != "zones" and name not in NOT_ON_PAGE


def folder(output_dir):
    return os.path.join(output_dir, FOLDER)


def file_hash(path):
    if not path or not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()[:16]


def fingerprint(values, groups, step, inputs=None, edits=None):
    """What step `step` is computed with: the values of every parameter of it and of the steps
    before it, the files they read, and - for the assignment - a scenario's edits. `values`
    {name: value}, `groups` {name: group}, `inputs` {"zoning": {"path": ...}, "od_matrix":
    {...}} - a run's loaded files; `edits` a scenario's (core/edits.py), None for a run."""
    upto = STEPS[:STEPS.index(step) + 1]
    chosen = {n: v for n, v in values.items() if step_of(n, groups.get(n, "")) in upto}
    inputs = inputs or {}
    files = {}
    for key, needed in (("zoning", "zones"), ("od_matrix", "demand")):
        if needed in upto and inputs.get(key):
            files[key] = {k: v for k, v in inputs[key].items() if k != "path"} | {
                "hash": file_hash(inputs[key].get("path"))}
    blob = {"parameters": chosen, "files": files}
    if edits and "assignment" in upto:
        blob["edits"] = [{k: v for k, v in e.items() if k != "label"} for e in edits]
    text = json.dumps(blob, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def registry_values(settings):
    """{name: value} and {name: group} of a settings module as imported (with a run's values)."""
    reg = settings.ASSUMED
    values = {n: e["value"] for n, e in list(reg.entries.items()) + list(reg.settings.items())}
    return values, {n: reg.group_of(n) for n in values}


def read_status(output_dir):
    path = os.path.join(folder(output_dir), STATUS)
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_status(output_dir, status):
    os.makedirs(folder(output_dir), exist_ok=True)
    with open(os.path.join(folder(output_dir), STATUS), "w", encoding="utf-8") as f:
        json.dump(status, f, indent=1, ensure_ascii=False, default=str)


def states(output_dir, current):
    """{step: "done" | "stale" | "missing"}: done with what `current` {step: fingerprint} says
    now, done with something else, or not done. A step after one that is not done is not done
    either, whatever its fingerprint."""
    status, out, ok = read_status(output_dir), {}, True
    for step in STEPS:
        entry = status.get(step)
        if not entry:
            out[step], ok = "missing", False
        elif not ok or entry.get("fingerprint") != current.get(step):
            out[step], ok = "stale", False
        else:
            out[step] = "done"
    return out


def save_state(model, step):
    """The model's state after `step`, for the next step's process. What cannot be pickled is
    left out and said: a next step needing it fails with its name, not silently."""
    kept, left = {}, []
    for key, value in model.__dict__.items():
        if key in NOT_KEPT:
            continue
        try:
            pickle.dumps(value)
            kept[key] = value
        except Exception:                                  # noqa: BLE001 - any reason at all
            left.append(key)
    os.makedirs(folder(model.paths.output), exist_ok=True)
    with open(os.path.join(folder(model.paths.output), f"{step}.pkl"), "wb") as f:
        pickle.dump(kept, f, protocol=pickle.HIGHEST_PROTOCOL)
    if left:
        print(f"(not kept for the next step: {', '.join(left)})")


def load_state(model, step):
    from .maps import MapKit
    with open(os.path.join(folder(model.paths.output), f"{step}.pkl"), "rb") as f:
        model.__dict__.update(pickle.load(f))
    # A map kit draws into the run's own maps folder - a state copied from another run (reuse)
    # would otherwise draw into that run's.
    for value in model.__dict__.values():
        if isinstance(value, MapKit):
            value.maps_dir = model.paths.maps


# What a run's steps leave that another run with the same steps can take as they are.
REUSABLE = {
    "zones": [os.path.join(FOLDER, "zones.pkl"), os.path.join(FOLDER, "road_model"),
              os.path.join(FOLDER, "zones.log"), os.path.join("maps", "zones.html"),
              os.path.join("exports", "zone_list.csv")],
    "demand": [os.path.join(FOLDER, "demand.pkl"), os.path.join(FOLDER, "demand.log"),
               os.path.join("maps", "trip_ends.html")],
}


def reuse(model, step, donor_dir, current):
    """`step` taken from another run - a scenario's base, or the city's baseline - when that run
    computed it, and every step before it, with exactly what this run's would be (the same
    fingerprints: the same zoning, network, parameters and files): its state, project, maps and
    lists are copied, in seconds instead of minutes. False when it cannot be."""
    if os.path.normcase(os.path.abspath(donor_dir)) == os.path.normcase(
            os.path.abspath(model.paths.output)):
        return False
    donor = read_status(donor_dir)
    upto = STEPS[:STEPS.index(step) + 1]
    if any(not donor.get(k) or donor[k].get("fingerprint") != current[k] for k in upto):
        return False
    parts = list(REUSABLE[step])
    if step == "zones":
        parts += [os.path.join("maps", name) for name in model.step1_maps] + [
            os.path.join("map_data", name[:-5] + ".pkl") for name in model.step1_maps]
    if not os.path.exists(os.path.join(donor_dir, parts[0])):
        return False
    from .network import release_log_files
    release_log_files(os.path.join(donor_dir, FOLDER, "road_model"))
    for part in parts:
        source, target = os.path.join(donor_dir, part), os.path.join(model.paths.output, part)
        if not os.path.exists(source):
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.isdir(source):
            if os.path.isdir(target):
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    status = {k: v for k, v in read_status(model.paths.output).items() if k in upto[:-1]}
    status[step] = dict(donor[step], reused_from=os.path.basename(donor_dir))
    write_status(model.paths.output, status)
    return True


def snapshot_project(paths):
    """Step 1's AequilibraE project, kept for the assignment to start from."""
    from .network import release_log_files
    target = os.path.join(folder(paths.output), "road_model")
    release_log_files(paths.road_model)
    if os.path.isdir(target):
        shutil.rmtree(target)
    shutil.copytree(paths.road_model, target)


def restore_project(paths):
    """A fresh copy of step 1's project as the run's working model, opened."""
    from aequilibrae import Project

    from .network import release_log_files
    source = os.path.join(folder(paths.output), "road_model")
    if os.path.isdir(paths.road_model):
        release_log_files(paths.road_model)
        shutil.rmtree(paths.road_model)
    shutil.copytree(source, paths.road_model)
    project = Project()
    project.open(paths.road_model)
    return project


def log_path(output_dir, step):
    """A step's own log, when it runs on its own (run.py --step)."""
    return os.path.join(folder(output_dir), f"{step}.log")


def join_logs(paths):
    """The run's log, run_log.txt, as one: its steps' logs in order - what the results page reads."""
    with open(paths.log, "w", encoding="utf-8") as out:
        for step in STEPS:
            path = log_path(paths.output, step)
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    out.write(f.read().rstrip("\n") + "\n\n")


def finish(model, step, started, current, preview):
    """Record a step as done: its fingerprint, when, how long, and its preview; the steps after
    it are dropped - they were computed from what this step has just replaced."""
    status = read_status(model.paths.output)
    for later in STEPS[STEPS.index(step):]:
        status.pop(later, None)
    status[step] = {"finished": time.strftime("%Y-%m-%d %H:%M"),
                    "minutes": round((time.time() - started) / 60, 1),
                    "fingerprint": current[step], "preview": preview}
    write_status(model.paths.output, status)


def require(model, step, current):
    """Refuse to run `step` unless the steps before it are done with what the run says now."""
    done = states(model.paths.output, current)
    for before in STEPS[:STEPS.index(step)]:
        if done[before] != "done":
            why = ("has not been computed" if done[before] == "missing" else
                   "was computed with other parameters or files than the run has now")
            raise RuntimeError(f"step {STEPS.index(before) + 1} ({LABELS[before]}) {why}: "
                               f"compute it first")
