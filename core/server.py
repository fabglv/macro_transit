"""A small local server: the results pages, the line design editor, and simulations started from it.

    python serve.py                 http://localhost:8000, opened in the browser

It listens on this computer only (127.0.0.1), and only the standard library:

    GET  /                                    the start page and every results page (output/)
    GET  /editor/<city>                       the line design editor for a city's public transport
    GET  /simulate/<city>                     running a simulation of one of its designs
    GET  /macro/<city>                        running its road model with parameters changed
    GET  /scenario/<city>                     a scenario of one of its road runs: edits to the
                                              network, run on the same trips, then compared
    GET  /api/<city>/lines                    the baseline lines, as the editor shows them
    GET  /api/<city>/network                  the lines' stops and the study box, for its map
    GET  /api/<city>/assignment               the settings a simulation runs with
    POST /api/<city>/check                    how far points are from a street a bus can use
    POST /api/<city>/path                     the way along the streets through stops in order
    GET  /api/<city>/designs                  the baseline and the city's designs: built? run?
    GET  /api/<city>/designs/<name>           one design, as the editor loads it
    POST /api/<city>/designs/<name>           save it (checked first: nothing invalid is written)
    POST /api/<city>/build/<name>             build its pages (design.py), in the background
    POST /api/<city>/simulate/<name>          simulate it (run.py --transit), in the background,
                                              with the options in its body (transit/options.py)
    POST /api/<city>/simulation/<name>        what a simulation of it with those options is called,
                                              and whether it exists
    DELETE /api/<city>/designs/<name>         delete a design: its file and its pages
    DELETE /api/<city>/simulations/<name>     delete a design's simulation: its results
    GET  /api/<city>/macro                    the road model's parameters, its saved runs, and
                                              the run going, if one is
    POST /api/<city>/macro/<name>             save a road run (core/runs.py), and with "step"
                                              in its body compute that step (run.py --run --step:
                                              zones, demand, assignment), in the background
    POST /api/<city>/macro/<name>/upload/<what>   a file the run loads - "zoning" or "od_matrix",
                                              the file itself as the body, ?filename= its name -
                                              kept beside the run's file, and checked
    DELETE /api/<city>/macro/<name>           delete a road run: its file and its results
    GET  /api/jobs/<id>                       a job's state and the last lines of its log

A job is the same command as from a terminal - `design.py <city> <name>`, `run.py <city>
--transit --design <name>` or `run.py <city> --run <name>` - in a separate process, so a page and
a terminal cannot differ.
One of each at a time: a second simulation while one runs is refused, not queued.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from . import viewer
from .paths import OUTPUT, ROOT

# A design's file name, and its folders': no "-", which joins a simulation's options to it
# (l1_double-saturday-10-14), so a design's name and another's simulation cannot be confused.
NAME = re.compile(r"^[a-z0-9][a-z0-9_]{0,59}$")
SIM_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,119}$")  # a simulation's: a design and options
MODES = {0: "tram", 1: "metro", 2: "rail", 3: "bus"}
LOG_TAIL = 40
BASELINE = "baseline"


class Jobs:
    """Design builds and simulations started from the pages: one of each kind at a time, each
    with its log kept in memory."""

    def __init__(self):
        self.lock = threading.Lock()
        self.jobs, self.running = {}, {}

    def start(self, kind, city, name, args=(), sim=None):
        """`args` the simulation's options for run.py, `sim` its name (its design's without)."""
        with self.lock:
            busy = self.running.get(kind)
            if busy and self.jobs[busy]["state"] == "running":
                return None, f"{self.jobs[busy]['sim'] or self.jobs[busy]['name']} is still running"
            job_id = f"{int(time.time() * 1000)}"
            self.jobs[job_id] = {"kind": kind, "city": city, "name": name, "state": "running",
                                 "log": [], "started": time.time(), "result": None,
                                 "args": list(args), "sim": sim or name}
            self.running[kind] = job_id
        threading.Thread(target=self._run, args=(job_id,), daemon=True).start()
        return job_id, None

    def _run(self, job_id):
        job = self.jobs[job_id]
        city, name = job["city"], job["name"]
        if job["kind"] == "build":
            command = [os.path.join(ROOT, "design.py"), city, name]
            result = f"/transit/designs/{city}-{name}/index.html"
        elif job["kind"] == "macro":                  # run.py builds its own pages
            from . import runs
            command = [os.path.join(ROOT, "run.py"), city, "--run", name] + job["args"]
            folder = os.path.basename(runs.output_dir(city, name))
            # A step before the assignment has no results page: its preview is on the run page.
            result = (f"/macro/{folder}/index.html" if "--step" not in job["args"]
                      or job["args"][-1] == "assignment" else None)
        else:
            command = [os.path.join(ROOT, "run.py"), city, "--transit", "--design", name] \
                + job["args"]
            result = f"/transit/simulations/{city}-{job['sim']}/index.html"
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        try:
            process = subprocess.Popen([sys.executable] + command, cwd=ROOT,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                       encoding="utf-8", errors="replace", env=env)
            for line in process.stdout:
                job["log"].append(line.rstrip())
            process.wait()
            if process.returncode:
                job["state"] = "failed"
                return
            if job["kind"] == "simulate":             # design.py builds its own pages
                viewer.build(os.path.join(OUTPUT, result.strip("/").rsplit("/", 1)[0]))
                pages = _design_output(city, name).output
                if os.path.isfile(os.path.join(pages, "run_log.txt")):
                    viewer.build(pages)                # its link to the new simulation
            # What the build or the simulation says to look at: its "WARNING:" lines - apart
            # from those the baseline's build gives too, which are not the design's doing.
            warnings = _warnings(job["log"])
            known = set(_baseline_warnings(city)) if name != BASELINE else set()
            job["warnings"] = [w for w in warnings if w not in known]
            job["baseline_warnings"] = [w for w in warnings if w in known]
            job["result"], job["state"] = result, "done"
        except Exception as problem:                       # shown on the page, not lost
            job["log"].append(f"ERROR: {problem}")
            job["state"] = "failed"

    def busy_with(self, city, name):
        """The kind of job running on this design, or None."""
        for job in self.jobs.values():
            if job["state"] == "running" and job["city"] == city \
                    and name in (job["name"], job["sim"]):
                return job["kind"]
        return None

    def status(self, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            return None
        return {k: job[k] for k in ("kind", "city", "name", "state", "result")} | {
            "warnings": job.get("warnings", []),
            "baseline_warnings": job.get("baseline_warnings", []),
            "log": job["log"][-LOG_TAIL:], "seconds": round(time.time() - job["started"])}


JOBS = Jobs()

# Pages rebuilt after a delete, one rebuild at a time: the lists and the start page at once (a
# second or two), the runs' own pages - their menus of runs - in the background, as rebuilding
# a kind's every page takes a while and the delete has been done already.
_REBUILDING = threading.Lock()


def _rebuild(output_dir=None):
    """The lists and the start page now; `output_dir`'s page and its neighbours' after."""
    _build_again(viewer.build_start)
    if output_dir:
        threading.Thread(target=_build_again, args=(viewer.build, output_dir),
                         daemon=True).start()


def _build_again(build, *args):
    """A build, one at a time - and once more if a run it listed was deleted while it ran (by
    another delete): the second finds the runs as they are."""
    with _REBUILDING:
        for attempt in (1, 2):
            try:
                return build(*args)
            except OSError as problem:
                if attempt == 2:
                    print(f"(the pages were not all rebuilt: {problem})")


def _remove(path):
    """A run's folder or file deleted - after any page build going on, which may be reading it,
    and tried again for a few seconds if a page request still holds one of its files open:
    Windows does not delete a file in use. Returns whether it was there to delete: of two deletes
    at once, the second finds it gone."""
    with _REBUILDING:
        for attempt in range(10):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                elif os.path.exists(path):
                    os.remove(path)
                else:
                    return attempt > 0            # gone: by this delete's own first try, or another's
                return True
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.5)


# --- what the pages read and write ---------------------------------------------------------------
def _transit(city):
    """The city's transit settings and inputs, and the design module; ValueError for a city
    without a public-transport case."""
    import transit
    from transit import scenario
    settings, inputs = transit.load(city)
    return settings, inputs, scenario


def lines_of(lines, colors):
    """The lines as the editor shows them, in minutes and km/h."""
    return [{"key": key, "route": line["short"], "name": line["long"],
             "mode": MODES.get(line["route_type"], str(line["route_type"])),
             "headway_min": round(line["headway_s"] / 60, 2), "speed_kmh": line["speed_kmh"],
             "dwell_s": line["dwell_s"], "capacity": line.get("capacity"),
             "leg_minutes": [[d, k, round(sec / 60, 2)] for (d, k), sec in
                             sorted((line.get("leg_s") or {}).items())],
             # Its own hours if it has them (else the city's), and its bands of other headways.
             "hours": [_clock(t) for t in line["hours_s"]] if line.get("hours_s") else None,
             "bands": [{"from": _clock(a), "to": _clock(b), "headway_min": round(h / 60, 2)}
                       for a, b, h in line.get("bands_s") or []],
             # Saturday and Sunday as a design file says them: left out (the weekdays'), "none",
             # or their own timetable.
             **{day: "none" if own is None else {
                 "headway_min": round(own["headway_s"] / 60, 2),
                 "hours": [_clock(t) for t in own["hours_s"]] if own.get("hours_s") else None,
                 "bands": [{"from": _clock(a), "to": _clock(b), "headway_min": round(h / 60, 2)}
                           for a, b, h in own.get("bands_s") or []]}
                for day, own in (line.get("days") or {}).items()},
             "stops": len(line["stops"]), "color": colors.get(line["short"], "#555555")}
            for key, line in lines.items()]


def _clock(seconds):
    """Seconds after midnight as the editor's time fields hold them: "07:30" (the next day's
    times as the day's: the editor reads one before the first departure as the next day's)."""
    seconds = int(seconds) % (24 * 3600)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"


def _warnings(log):
    """A build's or simulation's "WARNING:" lines, as said."""
    return [line.split("WARNING:", 1)[1].strip() for line in log if line.startswith("WARNING:")]


def _baseline_warnings(city):
    """What the city's baseline build warns about - its lines as its inputs give them; [] if it
    is not built."""
    path = _design_output(city, BASELINE).log
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as f:
        return _warnings(f.read().splitlines())


def _design_output(city, name):
    from transit.paths import DesignPaths
    return DesignPaths(city, name)


def _along(city, name, routes=None):
    """A built design's lines along the streets, as [route, [[lat, lon], ...]] - from its
    lines.geojson, so the design part never depends on a simulation. [] if not built."""
    path = _design_output(city, name).lines
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        features = json.load(f)["features"]
    return [[p["route"], [[round(y, 6), round(x, 6)] for x, y in f["geometry"]["coordinates"]]]
            for f in features for p in [f["properties"]]
            if p["shape"] == "streets" and (routes is None or p["route"] in routes)]


def _street_km(city, name):
    """{route: [km along the streets, each journey]} of a built design's buses - what the editor
    times them on; {} if it is not built."""
    path = _design_output(city, name).lines
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        features = json.load(f)["features"]
    out = {}
    for f in features:
        p = f["properties"]
        if p.get("shape") == "streets" and p.get("km_streets") is not None:
            out.setdefault(p["route"], []).append(p["km_streets"])
    return out


def _study_area(city, bbox):
    """The outline of the zones a simulation takes - the city's, those whose middle is in the
    study box (transit/project.road_zones) - as GeoJSON, for the editor to draw: the area the
    simulation covers, along zone borders. None while the city's zones are not built yet."""
    import shapely
    import shapely.geometry
    from shapely.ops import unary_union

    from transit.project import zone_sources
    if not any(os.path.isfile(p) for p in zone_sources(city)):
        return None
    from transit.project import city_zones
    zones = city_zones(city)
    min_lat, min_lon, max_lat, max_lon = bbox
    inside = zones[zones["centroid_lat"].between(min_lat, max_lat)
                   & zones["centroid_lon"].between(min_lon, max_lon)]
    if inside.empty:
        return None
    # About 50 m of detail, coordinates to about a metre: an outline, not a map of the zones.
    area = shapely.set_precision(unary_union([g.buffer(0) for g in inside.geometry])
                                 .simplify(0.0005), 1e-5)
    return shapely.geometry.mapping(area)


def network(city):
    """What the editor's map draws and checks against: every baseline line with its stops,
    the baseline design's lines along the streets, the study box (the streets' extent, which a
    stop must be in) and the area its zones cover, and the street-matching rule for buses."""
    settings, inputs, _ = _transit(city)
    lines = [{"route": line["short"], "name": line["long"],
              "mode": MODES.get(line["route_type"], str(line["route_type"])),
              "color": inputs.LINE_COLORS.get(line["short"], "#555555"),
              "stops": [list(stop) for stop in line["stops"]],
              "stops_back": [list(stop) for stop in line.get("stops_back", [])]}
             for line in inputs.LINES.values()]
    return {"bbox": list(inputs.BBOX), "area": _study_area(city, inputs.BBOX),
            "lines": lines, "aligned": _along(city, BASELINE),
            "street_km": _street_km(city, BASELINE),
            "default_capacity": getattr(inputs, "DEFAULT_CAPACITY", {}),
            "match_radius_m": settings.MATCH_RADIUS_M,
            "matched_modes": [MODES[t] for t in settings.MATCHED_ROUTE_TYPES if t in MODES],
            "transfer_walk_m": settings.TRANSFER_WALK_M, "feed": _feed_fixed(inputs),
            "layover": {"share": settings.LAYOVER_SHARE, "min_s": settings.LAYOVER_MIN_S}}


def _feed_fixed(inputs):
    """The city's service hours: where a new line's timetable starts from in the editor."""
    start_h, end_h = inputs.SERVICE_HOURS
    return {"start": f"{start_h:02d}:00", "end": f"{end_h % 24:02d}:00"}


def assignment(city):
    """What a simulation can choose (transit/options.py) and the city's defaults for it."""
    from transit.options import DAYS, service_date
    settings, inputs, _ = _transit(city)
    return {"ready": getattr(settings, "SIMULATION_READY", True),
            "not_ready": getattr(settings, "NOT_READY", ""),
            "days": [{"day": d, "label": label,
                      "date": service_date(inputs.SERVICE_DAY, d, inputs.CALENDAR)}
                     for d, label in DAYS.items()],
            "period": [settings.PERIOD_START_H, settings.PERIOD_END_H],
            "service_hours": list(inputs.SERVICE_HOURS),
            "demand_trips": settings.TARGET_PEAK_TRIPS,
            "walking_speed": settings.WALKING_SPEED, "transfer_walk_m": settings.TRANSFER_WALK_M,
            "transfer_penalty_s": settings.TRANSFER_PENALTY_S,
            "wait_factor": settings.WAIT_TIME_FACTOR,
            "access_m": settings.ACCESS_RADIUS_M,
            "zones": _road_zones_said(city),
            "algorithm": f"{settings.TRANSIT_ALGORITHM} - optimal strategies: the services that "
                         f"get them there soonest on average"}


def _road_zones_said(city):
    """The city's zones a simulation takes, for the page's step 1: how many, people - or that
    they are built from the city's inputs when it runs, if neither the road baseline nor the
    city's cache has them yet."""
    import geopandas as gpd

    from transit.project import zone_sources
    settings, inputs, _ = _transit(city)
    path = next((p for p in zone_sources(city) if os.path.isfile(p)), None)
    if path is None:
        return {"ready": False}
    zones = gpd.read_file(path, ignore_geometry=True)
    min_lat, min_lon, max_lat, max_lon = inputs.BBOX
    inside = zones[zones["centroid_lat"].between(min_lat, max_lat)
                   & zones["centroid_lon"].between(min_lon, max_lon)]
    return {"ready": True, "all": len(zones), "inside": len(inside),
            "pop": round(float(inside["pop"].sum())), "km2": round(float(inside["area_km2"].median()), 2)}


def _options(body):
    """transit/options.py's Options from a page's request, checked."""
    from transit.options import Options
    period = body.get("period")

    def number(key):
        return float(body[key]) if body.get(key) not in (None, "") else None
    return Options(str(body.get("day") or "weekday"),
                   tuple(int(h) for h in period) if period else None,
                   number("trips"), number("walking_speed"), number("transfer_walk_m"),
                   number("transfer_penalty_s"), number("wait_factor"), number("access_m")).check()


def simulation(city, design, body):
    """What a simulation of `design` with these options is called, and whether it exists."""
    from transit.paths import TransitPaths
    settings, _, _ = _transit(city)
    options = _options(body)
    name = options.name(design, settings)
    paths = TransitPaths(city, design=design, name=name)
    exists = os.path.exists(paths.summary)
    return {"name": name, "exists": exists,
            "finished": time.strftime("%Y-%m-%d %H:%M", time.localtime(
                os.path.getmtime(paths.summary))) if exists else None,
            "result": f"/transit/simulations/{city}-{name}/index.html" if exists else None,
            "args": _run_args(options)}


def _run_args(options):
    """run.py's arguments for these options, only where they are not the defaults."""
    out = []
    if options.day != "weekday":
        out += ["--day", options.day]
    if options.period:
        out += ["--period", f"{options.period[0]}-{options.period[1]}"]
    if options.trips is not None:
        out += ["--trips", f"{options.trips:g}"]
    if options.transfer_penalty_s is not None:
        out += ["--transfer-penalty", f"{options.transfer_penalty_s:g}"]
    if options.wait_factor is not None:
        out += ["--wait-factor", f"{options.wait_factor:g}"]
    if options.access_m is not None:
        out += ["--access", f"{options.access_m:g}"]
    if options.walking_speed is not None:
        out += ["--walking-speed", f"{options.walking_speed:g}"]
    if options.transfer_walk_m is not None:
        out += ["--transfer-walk", f"{options.transfer_walk_m:g}"]
    return out


def street_path(city, points):
    """The way along the streets through `points` [[lat, lon], ...] in order, with its km."""
    from transit.paths import street_cache
    from transit.streets import streets_for
    _transit(city)
    points = [(float(lat), float(lon)) for lat, lon in points]
    if len(points) < 2:
        return {"path": [], "km": 0, "unrouted": 0}
    return streets_for(street_cache(city)).path(points)


def check_points(city, points):
    """For each [lat, lon]: metres to the nearest street a bus can be matched onto, its name,
    whether it is cut off from the other streets (no bus gets in or out), and where to snap the
    stop: onto the nearest street a bus can reach - `snap`, `snap_metres`, `snap_street`."""
    from transit.paths import street_cache
    from transit.streets import streets_for
    _transit(city)                                         # an unknown city fails here
    points = [(float(lat), float(lon)) for lat, lon in points]
    streets = streets_for(street_cache(city))
    reach = streets.nearest(points, connected=True)
    return [dict(near, snap=r["snap"], snap_metres=r["metres"], snap_street=r["street"])
            for near, r in zip(streets.nearest(points), reach)]


def baseline_lines(city):
    _, inputs, _ = _transit(city)
    return lines_of(inputs.LINES, inputs.LINE_COLORS)


def design_list(city):
    """The baseline and every design of the city, each with its pages and its simulation if
    they exist."""
    from transit.paths import DESIGNS, TransitPaths
    _, _, designs = _transit(city)
    folder = os.path.join(DESIGNS, city)
    names = [BASELINE] + sorted(f[:-5] for f in os.listdir(folder) if f.endswith(".json")) \
        if os.path.isdir(folder) else [BASELINE]
    out = []
    for name in names:
        label = "baseline - the network as it runs today"
        if name != BASELINE:
            try:
                label = designs.load(city, name)["label"]
            except (OSError, ValueError) as problem:
                label = f"{name} (unreadable: {problem})"
        built = os.path.join(_design_output(city, name).output, "index.html")
        run = os.path.join(TransitPaths(city, design=name).output, "index.html")
        out.append({"name": name, "label": label,
                    "design": f"/transit/designs/{city}-{name}/index.html"
                    if os.path.exists(built) else None,
                    "simulation": f"/transit/simulations/{city}-{name}/index.html"
                    if os.path.exists(run) else None,
                    "simulated": time.strftime("%Y-%m-%d %H:%M",
                                               time.localtime(os.path.getmtime(run)))
                    if os.path.exists(run) else None})
    return out


def design_state(city, name):
    """A design as the editor loads it: every baseline line with the design's values (whatever
    kind of change set them), the lines it removes, and its added lines (`kept`, the add_line
    changes as written) with their way along the streets if the design is built."""
    _, inputs, designs = _transit(city)
    loaded = designs.load(city, name)
    lines, colors, _ = designs.apply(loaded, inputs.LINES, inputs.LINE_COLORS)
    effective = {line["route"]: line for line in lines_of(lines, colors)}
    kept = [c for c in loaded["changes"] if c.get("type") == "add_line"]
    edited = [c for c in loaded["changes"] if c.get("type") == "edit_line"]
    return {"name": name, "label": loaded["label"], "description": loaded["description"],
            "lines": [effective.get(line["short"]) or {"route": line["short"], "removed": True}
                      for line in inputs.LINES.values()],
            "kept": kept, "edited": edited, "street_km": _street_km(city, name), "aligned": _along(city, name, {c["route"] for c in kept})}


def save_design(city, name, body):
    """Write the design file, after checking it applies; the file is only written if it does."""
    if name == BASELINE:
        raise ValueError("'baseline' is the city's own network: give the design another name")
    _, inputs, designs = _transit(city)
    data = {"label": str(body.get("label") or name).strip(),
            "description": str(body.get("description") or "").strip(),
            "changes": body.get("changes") or []}
    designs.apply(dict(data, name=name), inputs.LINES, inputs.LINE_COLORS)   # raises if wrong
    path = designs.scenario_path(city, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def _deletable(city, name):
    _transit(city)                                         # an unknown city fails here
    if name == BASELINE:
        raise ValueError("the baseline is not deleted: every design starts from it, and its "
                         "simulation holds the demand every other simulation reads")
    busy = JOBS.busy_with(city, name)
    if busy:
        raise ValueError(f"{name} is being {'built' if busy == 'build' else 'simulated'}: "
                         f"wait for it to finish")


def delete_design(city, name):
    """Delete a design's file and its pages. Its simulation, a result of its own, is kept;
    its page loses the link to the design."""
    from transit.paths import TransitPaths
    _deletable(city, name)
    _, _, designs = _transit(city)
    path, pages = designs.scenario_path(city, name), _design_output(city, name).output
    if not os.path.exists(path) and not os.path.isdir(pages):
        raise ValueError(f"there is no design {name}")
    if not any([_remove(path), _remove(pages)]):          # another delete was first
        raise ValueError(f"there is no design {name}")
    simulation = TransitPaths(city, design=name).output
    # Its simulation's page loses its link to the design.
    _rebuild(simulation if os.path.isfile(os.path.join(simulation, "run_log.txt")) else None)
    return {"deleted": name}


def delete_simulation(city, name):
    """Delete a simulation - named as its design, or with its options after it: its whole
    results folder. The design is kept."""
    from transit.paths import TransitPaths
    _deletable(city, name)
    folder = TransitPaths(city, name=name).output
    if not os.path.isdir(folder):
        raise ValueError(f"{name} has no simulation")
    design = name
    try:
        with open(os.path.join(folder, "summary.json"), encoding="utf-8") as f:
            design = (json.load(f).get("design") or {}).get("name") or name
    except (OSError, ValueError):
        pass
    if not _remove(folder):                                # another delete was first
        raise ValueError(f"{name} has no simulation")
    pages = _design_output(city, design).output
    if os.path.isfile(os.path.join(pages, "run_log.txt")):
        _rebuild(pages)                                    # its link to the simulation goes
    else:
        viewer.build_start()
    return {"deleted": name}


# --- road runs (core/runs.py) ---------------------------------------------------------------------
def _is_city(name):
    from cases import CASES
    return name in CASES


def _macro_city(city):
    from cases import CASES
    if city not in CASES:
        raise ValueError(f"unknown city {city!r}")


def _float_shape(value):
    """`value` with each number replaced by whether it is a decimal (a float), the rest False."""
    if isinstance(value, bool):
        return False
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return {k: _float_shape(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_float_shape(v) for v in value]
    return False


def macro_state(city):
    """What the Run a macrosimulation page opens with: every parameter as the settings module
    has it, the saved runs, and the road run going, if one is."""
    from . import runs
    _macro_city(city)
    from . import steps
    _, parameters = runs.defaults(city)
    for row in parameters:
        row["step"] = steps.step_of(row["name"], row["group"])
        row["on_page"] = steps.on_page(row["name"], row["group"])
        # JSON writes 1.0 as 1: which numbers are decimals, shaped as the value, so the page
        # shows 1.0 and its arrows step by 0.1.
        row["floats"] = _float_shape(row["value"])
        if row["name"] in steps.CHOICES:
            row["choices"] = steps.CHOICES[row["name"]]
    baseline = runs.read(city, runs.BASELINE) | {"done": os.path.isfile(os.path.join(
        runs.output_dir(city, runs.BASELINE), "summary.json"))}
    out = []
    for run in [baseline] + runs.saved(city):
        run["steps"] = runs.step_states(city, run) if "error" not in run else {}
        run["output"] = f"/macro/{os.path.basename(runs.output_dir(city, run['name']))}/"
        out.append(run)
    going = JOBS.running.get("macro")
    job = JOBS.jobs.get(going) if going else None
    from cases import load
    model_cls, _ = load(city)
    # The city's own zoning, as the baseline's step 1 has it: what "the city's zones" means.
    city_zones = (out[0]["steps"].get("zones") or {}).get("preview") or {}
    return {"parameters": parameters, "runs": out, "steps": steps.STEPS,
            "labels": steps.LABELS, "city_zones": city_zones,
            "attraction_map": model_cls.attraction_map,
            "city_zones_ready": (out[0]["steps"].get("zones") or {}).get("state") == "done",
            "running": {"job": going, "city": job["city"], "name": job["name"],
                        "step": job["args"][-1] if job["args"] else None}
            if job and job["state"] == "running" else None}


def macro_save(city, name, body):
    """Save a road run (checked: nothing invalid is written) and, with "run" in the body, run
    it. Returns (answer, status)."""
    from . import runs
    _macro_city(city)
    if JOBS.busy_with(city, name) == "macro":
        return {"error": f"{name} is running: wait for it to finish"}, 409
    from . import steps
    step = body.get("step")
    if step and step not in steps.STEPS:                   # before anything is saved
        return {"error": f"no step {step!r}: {', '.join(steps.STEPS)}"}, 400
    run = runs.save(city, name, body)
    answer = {"saved": run}
    if step:
        job_id, busy = JOBS.start("macro", city, name, ["--step", step])
        if busy:
            return {"error": busy, "saved": run}, 409
        answer["job"] = job_id
    elif body.get("run") and run.get("base"):
        # A scenario runs whole: its base's zones and demand taken as they are, its assignment
        # with the edits - so its base must be computed, with what it says now.
        base = runs.read(city, run["base"])
        states = runs.step_states(city, base)
        if any(states[k]["state"] != "done" for k in ("zones", "demand")):
            return {"error": f"compute {run['base']} first: a scenario takes its zones and demand",
                    "saved": run}, 409
        job_id, busy = JOBS.start("macro", city, name)
        if busy:
            return {"error": busy, "saved": run}, 409
        answer["job"] = job_id
    return answer, 200


UPLOAD_LIMIT = 300 * 1024 * 1024


def macro_upload(city, name, what, filename, data):
    """Keep a file a run loads - a zoning (step 1) or an O-D matrix (step 2) - beside the run's
    file, after reading it: what is wrong with it is said now, not when its step runs."""
    from . import runs
    _macro_city(city)
    if name == runs.BASELINE or not runs.NAME.match(name):
        raise ValueError("give the run a name of its own before loading a file into it")
    if what not in runs.INPUTS:
        raise ValueError(f"no file kind {what!r}: {', '.join(runs.INPUTS)}")
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in runs.INPUTS[what]:
        raise ValueError(f"a {what.replace('_', ' ')} file is {', '.join(runs.INPUTS[what])}")
    if not data:
        raise ValueError("the file is empty")
    folder = runs.files_dir(city, name)
    os.makedirs(folder, exist_ok=True)
    stored = f"{what}{ext}"
    path = os.path.join(folder, stored)
    for old in os.listdir(folder):                         # one file of each kind
        if old.startswith(what + "."):
            os.remove(os.path.join(folder, old))
    with open(path, "wb") as f:
        f.write(data)
    try:
        if what == "zoning":
            from .zoning import read_zoning_file
            zones = read_zoning_file(path)
            columns = [c for c in zones.columns if c != "geometry"]
            about = {"zones": len(zones), "columns": columns,
                     "unique": [c for c in columns if zones[c].notna().all()
                                and zones[c].astype(str).is_unique]}
        else:
            from .odfile import read_long
            long = read_long(path)
            about = {"pairs": len(long), "trips": float(long["trips"].sum()),
                     "zones": len(set(long["origin"]) | set(long["destination"]))}
    except (ValueError, OSError) as problem:
        os.remove(path)
        raise ValueError(str(problem)) from None
    return {"file": stored, "name": os.path.basename(filename)} | about


def macro_zones(city, name):
    """A computed run's zones, for the Scenarios page to pick them on its map: GeoJSON, lightly
    simplified, each with its number, name, people, jobs (where the city has them), and the trips
    leaving and reaching it in the run's matrix. Kept beside its exports until they change."""
    import geopandas as gpd
    import pandas as pd

    from . import runs
    _macro_city(city)
    exports = os.path.join(runs.output_dir(city, name), "exports")
    sources = [os.path.join(exports, f) for f in ("zones.gpkg", "od_matrix.csv.gz")]
    if not all(os.path.isfile(f) for f in sources):
        raise ValueError(f"{name} has no zones and matrix: run it first")
    kept = os.path.join(exports, "zones_web.json")
    if os.path.isfile(kept) and os.path.getmtime(kept) >= max(map(os.path.getmtime, sources)):
        with open(kept, encoding="utf-8") as f:
            return json.load(f)
    zones = gpd.read_file(sources[0]).to_crs("EPSG:4326")
    od = pd.read_csv(sources[1], usecols=["origin", "destination", "trips"])
    leaving, reaching = od.groupby("origin")["trips"].sum(), od.groupby("destination")["trips"].sum()
    zones["geometry"] = zones.geometry.simplify(0.0002)
    out = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": json.loads(gpd.GeoSeries([z.geometry]).to_json())
         ["features"][0]["geometry"],
         "properties": {"zone": int(z.zone_number), "name": str(z.zone), "pop": round(float(z.pop)),
                        "jobs": round(float(z.jobs)) if "jobs" in zones and pd.notna(z.jobs) else None,
                        "out": round(float(leaving.get(z.zone_number, 0))),
                        "in": round(float(reaching.get(z.zone_number, 0)))}}
        for z in zones.itertuples()]}
    with open(kept, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    return out


def delete_macro(city, name):
    """Delete a named road run: its file and its results. The baseline is the settings as they
    are: it has neither to delete."""
    from . import runs
    _macro_city(city)
    if name == runs.BASELINE:
        raise ValueError("the baseline cannot be deleted")
    if JOBS.busy_with(city, name):
        raise ValueError(f"{name} is running: wait for it to finish")
    folder, file = runs.output_dir(city, name), runs.path(city, name)
    if not os.path.isdir(folder) and not os.path.isfile(file):
        raise ValueError(f"{city} has no run {name}")
    removed = [_remove(path) for path in (folder, runs.files_dir(city, name), file)]
    if not any(removed):                                   # another delete was first
        raise ValueError(f"{city} has no run {name}")
    baseline = runs.output_dir(city, runs.BASELINE)
    # The other runs' menus lose it.
    _rebuild(baseline if os.path.isfile(os.path.join(baseline, "run_log.txt")) else None)
    return {"deleted": name}


# --- the server ----------------------------------------------------------------------------------
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=OUTPUT, **kwargs)

    def log_message(self, format, *args):                  # quiet: the page shows what matters
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text):
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _parts(self):
        path = urllib.parse.urlparse(self.path).path
        return [urllib.parse.unquote(p) for p in path.strip("/").split("/") if p]

    def end_headers(self):
        # Pages are rebuilt after every run: never serve a stale copy from the browser's cache.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        parts = self._parts()
        try:
            if parts[:1] == ["editor"] and len(parts) == 2:
                from .editor_page import page
                _transit(parts[1])                         # an unknown city fails here
                self._html(page(parts[1]))
            elif parts[:1] == ["macro"] and len(parts) == 2 and _is_city(parts[1]):
                # /macro/<city> is the run page; anything else under /macro/ is a file of the
                # road runs' folder (output/macro/): their compare pages, say.
                from .macro_page import page
                self._html(page(parts[1]))
            elif parts[:1] == ["scenario"] and len(parts) == 2 and _is_city(parts[1]):
                from .scenario_page import page
                self._html(page(parts[1]))
            elif parts[:1] == ["simulate"] and len(parts) == 2:
                from .simulate_page import page
                _transit(parts[1])
                self._html(page(parts[1]))
            elif parts[:1] == ["api"]:
                self._api_get(parts[1:])
            else:
                super().do_GET()
        except ValueError as problem:
            self._json({"error": str(problem)}, 404)

    def _api_get(self, parts):
        if parts[:1] == ["jobs"] and len(parts) == 2:
            status = JOBS.status(parts[1])
            return self._json(status or {"error": "no such job"}, 200 if status else 404)
        answers = {"lines": baseline_lines, "network": network, "assignment": assignment,
                   "designs": design_list, "macro": macro_state}
        if len(parts) == 2 and parts[1] in answers:
            return self._json(answers[parts[1]](parts[0]))
        if len(parts) == 4 and parts[1] == "macro" and parts[3] == "zones" and NAME.match(parts[2]):
            try:
                return self._json(macro_zones(parts[0], parts[2]))
            except (OSError, ValueError) as problem:
                return self._json({"error": str(problem)}, 400)
        if len(parts) == 3 and parts[1] == "designs" and NAME.match(parts[2]):
            try:
                return self._json(design_state(parts[0], parts[2]))
            except (OSError, ValueError) as problem:
                return self._json({"error": str(problem)}, 400)
        self._json({"error": "not found"}, 404)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_POST(self):
        parts = self._parts()
        if len(parts) == 6 and parts[0] == "api" and parts[2] == "macro" and parts[4] == "upload":
            length = int(self.headers.get("Content-Length", 0))
            if length > UPLOAD_LIMIT:
                return self._json({"error": "the file is over 300 MB"}, 413)
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                return self._json(macro_upload(parts[1], parts[3], parts[5],
                                               (query.get("filename") or [""])[0],
                                               self.rfile.read(length)))
            except (OSError, ValueError) as problem:
                return self._json({"error": str(problem)}, 400)
        if len(parts) == 3 and parts[0] == "api" and parts[2] in ("check", "path"):
            answer = check_points if parts[2] == "check" else street_path
            try:
                return self._json(answer(parts[1], self._body().get("points", [])))
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as problem:
                return self._json({"error": str(problem)}, 400)
        if len(parts) != 4 or parts[0] != "api" or not NAME.match(parts[3]):
            return self._json({"error": "not found; a design's name is lower-case letters, "
                                        "digits and _"}, 404)
        city, action, name = parts[1], parts[2], parts[3]
        try:
            if action == "macro":
                return self._json(*macro_save(city, name, self._body()))
            if action == "designs":
                path = save_design(city, name, self._body())
                return self._json({"saved": os.path.relpath(path, ROOT)})
            if action == "simulation":
                return self._json(simulation(city, name, self._body()))
            if action == "build":
                _transit(city)
                job_id, busy = JOBS.start(action, city, name)
                return self._json({"error": busy}, 409) if busy else self._json({"job": job_id})
            if action == "simulate":
                settings, _, _ = _transit(city)
                if not getattr(settings, "SIMULATION_READY", True):
                    raise ValueError(settings.NOT_READY)
                planned = simulation(city, name, self._body())
                job_id, busy = JOBS.start(action, city, name, planned["args"], planned["name"])
                return self._json({"error": busy}, 409) if busy else self._json(
                    {"job": job_id, "name": planned["name"]})
        except (OSError, ValueError, json.JSONDecodeError) as problem:
            return self._json({"error": str(problem)}, 400)
        self._json({"error": "not found"}, 404)

    def do_DELETE(self):
        parts = self._parts()
        if len(parts) != 4 or parts[0] != "api" \
                or parts[2] not in ("designs", "simulations", "macro") \
                or not (SIM_NAME if parts[2] == "simulations" else NAME).match(parts[3]):
            return self._json({"error": "not found"}, 404)
        city, what, name = parts[1], parts[2], parts[3]
        try:
            delete = {"designs": delete_design, "simulations": delete_simulation,
                      "macro": delete_macro}[what]
            return self._json(delete(city, name))
        except (OSError, ValueError) as problem:
            return self._json({"error": str(problem)}, 400)


def serve(port=8000):
    """Serve until interrupted; returns the address."""
    try:
        viewer.build_all()                                 # the pages, current before serving
    except OSError as problem:                             # a run's folder going as it is read:
        print(f"(the pages were not all rebuilt: {problem})")   # serve what is there
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return server
