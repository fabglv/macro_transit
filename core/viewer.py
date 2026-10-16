"""The results page: one index.html in a run's output folder, to open in a browser.

    Maps         the zones and the simulation; the others under More maps
    Statistics   headline numbers, travel times, trip distances, network load, congested
                 streets (stats.py)
    Feed         a public-transport run's timetable: routes, service by hour, line diagrams,
                 time-distance, stop timetables (gtfs_views.py)
    Parameters   every parameter of the run, by what it acts on (parameters.csv)
    Tables       the other .csv files in exports/, sortable and filterable
    Run          run_log.txt cut at its section headers; the files in exports/

The page only reads what the run left in the folder, so it can be rebuilt for any past run
(view.py) and needs nothing beyond the standard library. It links to the maps rather than copying
them, so it stays small and must sit in the output folder next to maps/ and exports/.

Runs come in three kinds, each in its own folder: macrosimulations (the road model,
output/macro/), and for public transport its network designs (output/transit/designs/) and their
simulations (output/transit/simulations/). output/index.html is the start page: the cities.
A city's pages are in output/<city>/: index.html chooses Macrosimulation (macro.html, its road
runs) or Public transport (transit.html), which chooses Line design (designs.html, with the
editor) or Simulation (simulations.html, with running and comparing them). Each run's page goes
back to its city's list of its kind, with a menu to go to the others in it. Building one page
rebuilds them all, so those menus always list every run there is - a page takes well under a
second.
"""
import base64
import csv
import html
import json
import math
import os
import re
import time

from . import design_stats, gtfs_views, stats, summary, transit_stats
from .parameter_groups import GROUPS, OTHER
from .paths import MACRO_OUTPUT, OUTPUT, ROOT, TRANSIT_OUTPUT

PAGE = "index.html"
RULE = re.compile(r"^={20,}$")
DESIGN_OUTPUT = os.path.join(TRANSIT_OUTPUT, "designs")
SIMULATION_OUTPUT = os.path.join(TRANSIT_OUTPUT, "simulations")
# The attlas logo and its symbol, written into the pages rather than linked, so they show them
# opened as files too, wherever they sit in output/: the logo on the left of the bar across the
# top of every page (in STYLE), the symbol as the tab's icon.
def _data_uri(name, kind):
    with open(os.path.join(ROOT, "assets", name), "rb") as f:
        return f"data:{kind};base64," + base64.b64encode(f.read()).decode()


BAR_LOGO = _data_uri("attlas_logo.png", "image/png")
ICON = f'<link rel="icon" href="{_data_uri("attlas_icon.png", "image/png")}">'
BAR_TITLE = "Macro & Transit Prototype"     # beside the logo: an internal tool, not the product

# --- the navigation, on every page -----------------------------------------------------------------
def _nav_cities():
    """[{key, label, transit}] - every city with a case, and whether it has public transport."""
    cases = os.path.join(ROOT, "cases")
    return [{"key": d, "label": d.replace("_", " ").title(),
             "transit": os.path.isfile(os.path.join(cases, d, "transit_settings.py"))}
            for d in sorted(os.listdir(cases))
            if os.path.isdir(os.path.join(cases, d)) and not d.startswith(("_", "."))]


# The menus over the top bar, built by the page itself from where it is: its city from its address
# (a city's folder, a run of it, its compare or server pages), else the city last visited. Served,
# every link is from the server's root; opened as a file, from the output folder the page is in -
# and the pages only the server makes are shown, not linked. The start page goes on to the last
# city visited, unless asked to choose (?choose).
NAV_SCRIPT = """<script>
document.addEventListener("DOMContentLoaded", () => {
  if (window.top !== window.self) return;                      // a page shown inside another
  const CITIES = %s;
  const served = location.protocol.startsWith("http");
  if (served) document.documentElement.classList.add("served");
  const path = decodeURIComponent(location.pathname).replace(/\\\\/g, "/");
  let root = "/", rel = path.slice(1);
  if (!served) {
    const at = path.toLowerCase().lastIndexOf("/output/");
    if (at < 0) return;
    root = "file://" + path.slice(0, at + 8);
    rel = path.slice(at + 8);
  }
  const parts = rel.split("/").filter(Boolean);
  const named = c => parts.some(p => p === c.key || p.startsWith(c.key + "-") || p === `compare_${c.key}.html`);
  let city = CITIES.find(named), remembered = null;
  try {
    if (city) localStorage.setItem("attlas.city", city.key);
    else remembered = localStorage.getItem("attlas.city");
  } catch (e) {}
  const start = !parts.length || (parts.length === 1 && parts[0] === "index.html");
  if (start && remembered && !location.search.includes("choose") && CITIES.some(c => c.key === remembered)) {
    location.replace(root + remembered + "/index.html");
    return;
  }
  city = city || CITIES.find(c => c.key === remembered);
  if (!city) return;
  const k = city.key;
  const link = (label, to, server) => ({label, to, server});
  const menus = [
    ["Road model", [link("Runs", `${k}/macro.html`), link("New run", `macro/${k}`, true),
                    link("Scenarios", `scenario/${k}`, true), link("Compare road runs", `macro/compare_${k}.html`)]],
  ];
  if (city.transit) menus.push(["Public transport", [
    link("Line designs", `${k}/designs.html`), link("Design lines", `editor/${k}`, true),
    link("Simulations", `${k}/simulations.html`), link("Run a simulation", `simulate/${k}`, true),
    link("Compare simulations", `transit/simulations/compare_${k}.html`)]]);
  // Another city: the same kind of page, where there is one; else its dashboard.
  const same = to => {
    const r = rel.split("?")[0];
    for (const [a, b] of [[`${k}/`, `${to}/`], [`macro/${k}`, `macro/${to}`], [`scenario/${k}`, `scenario/${to}`],
                          [`editor/${k}`, `editor/${to}`], [`simulate/${k}`, `simulate/${to}`],
                          [`macro/compare_${k}.html`, `macro/compare_${to}.html`],
                          [`transit/simulations/compare_${k}.html`, `transit/simulations/compare_${to}.html`]])
      if (r === a.replace(/\\/$/, "") || (a.endsWith("/") && r.startsWith(a) && !r.slice(a.length).includes("/")))
        return r.replace(a.replace(/\\/$/, ""), b.replace(/\\/$/, ""));
    return `${to}/index.html`;
  };
  const here = rel.split("?")[0];
  const esc = t => String(t).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const item = l => l.server && !served
    ? `<span class="off" title="made by the server: start it with python serve.py">${esc(l.label)}</span>`
    : `<a href="${root}${l.to}"${here === l.to ? ' class="here"' : ""}>${esc(l.label)}</a>`;
  const nav = document.createElement("div");
  nav.className = "topnav";
  nav.innerHTML = `<a class="city" href="${root}${k}/index.html" title="${esc(city.label)}: both models">${esc(city.label)}</a>`
    + `<div class="menu"><button type="button" aria-label="another city">▾</button><div class="items">`
    + CITIES.filter(c => c.key !== k).map(c => `<a href="${root}${same(c.key)}">${esc(c.label)}</a>`).join("")
    + `<hr><a href="${root}index.html?choose=1">All cities</a></div></div>`
    + menus.map(([heading, links]) => `<div class="menu"><button type="button">${heading} ▾</button>`
      + `<div class="items">${links.map(item).join("")}</div></div>`).join("");
  document.body.prepend(nav);
  const close = except => nav.querySelectorAll(".menu.open").forEach(m => { if (m !== except) m.classList.remove("open"); });
  nav.addEventListener("click", ev => {
    const b = ev.target.closest("button");
    if (!b) return;
    const m = b.parentElement;
    close(m);
    m.classList.toggle("open");
  });
  document.addEventListener("click", ev => { if (!nav.contains(ev.target)) close(null); });
  document.addEventListener("keydown", ev => { if (ev.key === "Escape") close(null); });
});
</script>""" % json.dumps(_nav_cities())

# What every page's head carries: the tab's icon and the navigation.
ICON += NAV_SCRIPT
# What differs between the kinds of run: where they live, what they are called, how a city's page
# introduces them, the maps shown first (by the name a run gives them, without its number, and
# their label), and the Statistics and Feed views. `first_run` takes the city.
KINDS = {
    "macro": {"title": "Macrosimulation", "folder": MACRO_OUTPUT, "when": "Last assignment run",
              "page": "macro.html",
              "about": "Road traffic: zones, an O-D matrix of car trips and their assignment to "
                       "the streets.",
              "first_run": "python run.py {city}",
              # A scenario's change from its base first; other runs have no such map.
              "main_maps": {"change": "Change from its base", "zones": "Zones",
                            "simulation": "Simulation"},
              "stats": stats.views, "feed": None},
    "design": {"title": "Line designs", "folder": DESIGN_OUTPUT, "when": "Built",
               "page": "designs.html",
               "about": "The lines: create and edit them, and see each design's maps and "
                        "timetable. No passengers.",
               "first_run": "python design.py {city}",
               "main_maps": {"network": "Network"},
               "stats": design_stats.views, "feed": gtfs_views.views},
    "transit": {"title": "Simulations", "folder": SIMULATION_OUTPUT, "when": "Last run",
                "page": "simulations.html",
                "about": "Passengers on a design: run the assignment, see where they travel, and "
                         "compare simulations.",
                "first_run": "python run.py {city} --transit",
                "main_maps": {"loads": "Passenger loads"},
                "stats": transit_stats.views, "feed": None},
}
# Shown under Parameters, so not again under Tables.
PARAMETER_FILES = ("parameters.csv", "assumptions.csv")
# operations.csv is a design's Operations view.
SHOWN_ELSEWHERE = PARAMETER_FILES + ("operations.csv",)
# A table longer than this is not put on the page - it would make the page itself tens of MB -
# and is only listed under Exported files.
TABLE_ROW_LIMIT = 5000


def build(output_dir):
    """Write index.html into `output_dir`, refresh its neighbours, its kind's list of runs and
    the start page. Returns the path of this run's page."""
    output_dir = os.path.abspath(output_dir)
    root = os.path.dirname(output_dir)
    runs = find_runs(root)
    if output_dir not in runs:
        runs.append(output_dir)
    for run in runs:
        _page(run, runs)
    # A run elsewhere (--out output/test) gets a list of its own folder's runs; the start page
    # and the cities' pages list the runs in the usual folders.
    standard = {os.path.normcase(k["folder"]) for k in KINDS.values()} | {os.path.normcase(OUTPUT)}
    if os.path.normcase(root) not in standard:
        build_home(root, runs, _kind(output_dir))
    build_start()
    return os.path.join(output_dir, PAGE)


def build_all():
    """Every run's page, every list of runs and the start pages; returns the start page."""
    for kind in KINDS.values():
        runs = find_runs(kind["folder"])
        if runs:
            build(runs[0])                 # builds its neighbours and the list too
    return build_start()


def build_start():
    """output/index.html - the cities - and each city's page with all of its runs. The pages
    that used to list one kind of run for every city send their visitors to the start page."""
    runs = {kind: find_runs(k["folder"]) for kind, k in KINDS.items()}
    cards = []
    for city in _cities(runs):
        mine = {kind: [r for r in found if _city_key(r) == city] for kind, found in runs.items()}
        label = _city_label(city, mine)
        build_city(city, label, mine)
        macro = (f"last run {max(_last_run(r) for r in mine['macro'])}" if mine["macro"]
                 else "not run yet")
        lines = [("Macrosimulation", macro), ("Line designs", len(mine["design"])),
                 ("Simulations", len(mine["transit"]))]
        cards.append(f"<a class='run kind' href='{html.escape(city)}/{PAGE}'>"
                     f"<div class='name'>{html.escape(label)}</div><div class='lines'>"
                     + "".join(f"<span class='k'>{k}</span><span class='v'>{v}</span>"
                               for k, v in lines) + "</div></a>")
    for folder in (MACRO_OUTPUT, TRANSIT_OUTPUT, DESIGN_OUTPUT, SIMULATION_OUTPUT):
        up = os.path.relpath(os.path.join(OUTPUT, PAGE), folder).replace(os.sep, "/")
        write(os.path.join(folder, PAGE), REDIRECT.format(to=up))
    return write(os.path.join(OUTPUT, PAGE), START.format(style=STYLE, icon=ICON, cards="".join(cards)))


def _cities(runs):
    """Every city: those with a case (cases/<city>/) and those with runs."""
    cases = os.path.join(ROOT, "cases")
    keys = {d for d in os.listdir(cases)
            if os.path.isdir(os.path.join(cases, d)) and not d.startswith(("_", "."))}
    return sorted(keys | {_city_key(r) for found in runs.values() for r in found})


def _city_label(city, runs):
    """"Quito": as the city's runs name it, or from its key."""
    for found in runs.values():
        for run in found:
            name = (summary.read(run) or {}).get("city")
            if name:
                return name
    return city.replace("_", " ").title()


def city_page(city, kind=None):
    """A city's page in output/<city>/: its choice of model (index.html), public transport's
    choice (kind "transit_choice", transit.html), or the list of one kind of its runs."""
    name = (PAGE if kind is None else "transit.html" if kind == "transit_choice"
            else KINDS[kind]["page"])
    return os.path.join(OUTPUT, city, name)


def build_city(city, label, runs):
    """A city's pages: Macrosimulation or Public transport; Public transport's Line design or
    Simulation; and the list of each kind of its runs, public transport's with the editor,
    running a simulation and comparing them."""
    here = os.path.join(OUTPUT, city)
    backs = {"macro": (PAGE, label), "design": (PAGE, label), "transit": (PAGE, label)}
    for kind, about in KINDS.items():
        found = runs[kind]
        cards = [_deletable(run, _run_card(run, kind, here), kind) for run in found]
        if kind == "macro":
            cards += _unfinished_macro(city)
        if not found and not cards:
            cards.append(f"<div class='run empty'>None yet: "
                         f"<code>{about['first_run'].format(city=city)}</code></div>")
        write(city_page(city, kind), LIST.format(
            style=STYLE, icon=ICON, back=backs[kind][0], back_label=html.escape(backs[kind][1]),
            title=f"{html.escape(label)} – {about['title']}", note=about["about"],
            runs=_city_actions(city, kind, found, here) + "".join(cards)))

    # Public transport's own choice page is the dashboard now: its address sends there.
    write(city_page(city, "transit_choice"), REDIRECT.format(to=PAGE))
    return write(city_page(city), DASHBOARD.format(
        style=STYLE, icon=ICON, title=html.escape(label), cards=_dashboard(city, runs, here)))


def _dashboard(city, runs, here):
    """A city's page: its road model and its public transport side by side - each one's main
    actions (the server's, when served), its latest runs, and its full lists."""
    from transit import TRANSIT_CASES

    from . import macro_compare

    def rel(path):
        return os.path.relpath(path, here).replace(os.sep, "/")

    def action(label, href, server=False, primary=False):
        cls = "btn primary" if primary else "btn"
        if not server:
            return f"<a class='{cls}' href='{href}'>{label}</a>"
        return (f"<a class='{cls} server-only' href='{href}'>{label}</a><span class='btn off "
                f"file-only' title='made by the server: start it with python serve.py'>{label}</span>")

    def latest(found, n=5):
        newest = sorted(found, key=lambda r: os.path.getmtime(os.path.join(r, "run_log.txt")),
                        reverse=True)[:n]
        rows = "".join(
            f"<a href='{html.escape(rel(os.path.join(r, PAGE)))}'><span>"
            f"{html.escape(_name(r).split(' – ', 1)[-1])}</span><span class='w'>"
            f"{html.escape(_last_run(r))}</span></a>" for r in newest)
        return f"<div class='minis'>{rows}</div>" if rows else "<p class='note'>None yet.</p>"

    def more(href, n, what):
        return f"<a class='more' href='{href}'>All {n} {what}{'s' if n != 1 else ''} →</a>" if n else ""

    done = [r for r in runs["macro"] if summary.read(r)]
    road = [action("▶ New run", f"/macro/{city}", server=True, primary=True)]
    if done:
        road.append(action("✎ Scenarios", f"/scenario/{city}", server=True))
    if os.path.isfile(macro_compare.page_path(city)):
        road.append(action("Compare road runs", rel(macro_compare.page_path(city))))
    out = (f"<div class='col'><h2><a href='{KINDS['macro']['page']}'>Road model</a></h2>"
           f"<p class='note'>{KINDS['macro']['about']}</p><div class='acts'>{''.join(road)}</div>"
           f"<h3>Latest runs</h3>{latest(runs['macro'])}"
           f"{more(KINDS['macro']['page'], len(runs['macro']), 'run')}</div>")
    if city in TRANSIT_CASES:
        compare = os.path.join(SIMULATION_OUTPUT, f"compare_{city}.html")
        pt = [action("✎ Design lines", f"/editor/{city}", server=True, primary=True),
              action("▶ Run a simulation", f"/simulate/{city}", server=True)]
        if os.path.isfile(compare):
            pt.append(action("Compare simulations", rel(compare)))
        out += (f"<div class='col'><h2>Public transport</h2><p class='note'>Buses and metro: design "
                f"the lines, then simulate the passengers on them.</p><div class='acts'>{''.join(pt)}"
                f"</div><h3>Line designs</h3>{latest(runs['design'], 4)}"
                f"{more(KINDS['design']['page'], len(runs['design']), 'design')}"
                f"<h3>Simulations</h3>{latest(runs['transit'], 4)}"
                f"{more(KINDS['transit']['page'], len(runs['transit']), 'simulation')}</div>")
    return out


def _run_card(run, kind, here):
    """A run's card, linking to its page from the folder `here`."""
    name = _name(run)
    city = (summary.read(run) or {}).get("city", "")
    shown = name.removeprefix(f"{city} – ") if city else name   # on its city's page: "baseline"
    href = os.path.relpath(os.path.join(run, PAGE), here).replace(os.sep, "/")
    return (f"<a class='run' href='{html.escape(href)}'>"
            f"<div class='name'>{html.escape(shown)}</div>"
            f"<div class='when'>{KINDS[kind]['when']}: {html.escape(_last_run(run))}</div></a>")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _kind(output_dir):
    """'macro', 'design' or 'transit': from the run's summary, or failing that its folder."""
    info = summary.read(output_dir) or {}
    if info.get("kind") in KINDS:
        return info["kind"]
    parent = os.path.normcase(os.path.dirname(os.path.abspath(output_dir)))
    for key, kind in KINDS.items():
        if parent == os.path.normcase(kind["folder"]):
            return key
    return "macro"


def _city_key(run):
    """The city a run belongs to ("quito"): a public-transport run says so; a road model's run
    names its city ("Quito"); failing both, the folder's name up to its first "-"."""
    info = summary.read(run) or {}
    if info.get("city_key"):
        return info["city_key"]
    if info.get("city"):
        return re.sub(r"[^a-z0-9_]+", "_", info["city"].lower()).strip("_")
    return os.path.basename(run).split("-")[0].lower()


def _unfinished_macro(city):
    """Cards for a city's road runs computed in part - a step or two, not yet the assignment -
    which have no results to list: each opens on the run page to go on (when served). Computing a
    step takes a run's results off the pages until its assignment is computed again."""
    from . import runs as road_runs, steps
    cards = []
    # Scenarios run in one go, from their own page: not here.
    named = {r["name"]: r.get("label") or r["name"] for r in road_runs.saved(city)
             if not r.get("base")}
    for name in [road_runs.BASELINE] + list(named):
        folder = road_runs.output_dir(city, name)
        status = steps.read_status(folder)
        if not status or os.path.isfile(os.path.join(folder, "run_log.txt")):
            continue
        done = sum(1 for k in steps.STEPS if k in status)
        title = "the baseline" if name == road_runs.BASELINE else named[name]
        cards.append(f"<a class='run server-only' href='/macro/{city}?run={html.escape(name)}'>"
                     f"<div class='name'>{html.escape(title)}</div><div class='when'>not "
                     f"finished: {done} of {len(steps.STEPS)} steps computed</div>"
                     f"<p class='note'>Open it to compute the rest - its results are listed once "
                     f"the assignment is done.</p></a>")
    return cards


def find_runs(root):
    """Every run's output folder in `root`: a folder a run wrote its log in."""
    if not os.path.isdir(root):
        return []
    return sorted(os.path.join(root, d) for d in os.listdir(root)
                  if os.path.isfile(os.path.join(root, d, "run_log.txt")))


def build_home(root, runs=None, kind="macro"):
    """The page listing the runs in a folder of runs sent elsewhere (run.py --out): what each is,
    and when it last ran. The usual folders' runs are on their cities' pages."""
    runs = find_runs(root) if runs is None else runs
    cards = "".join(_run_card(run, _kind(run), root) for run in runs)
    start = os.path.relpath(os.path.join(OUTPUT, PAGE), root).replace(os.sep, "/")
    return write(os.path.join(root, PAGE), HOME.format(
        style=STYLE, icon=ICON, runs=cards, root=html.escape(root), title=KINDS[kind]["title"],
        back=start, back_label="Cities"))


def _deletable(run, card, kind):
    """A design's, a simulation's or a named road run's card with a Delete button (served
    pages only), which asks the server to delete it. The baselines have none: every design starts
    from the baseline, its simulation holds the demand every other simulation reads, and the road
    baseline is the settings as they are."""
    city = _city_key(run)
    design = os.path.basename(run)[len(city) + 1:]
    if design in ("baseline", ""):
        return card
    what = {"design": "designs", "transit": "simulations", "macro": "macro"}[kind]
    label = html.escape(_name(run), quote=True)
    return (f"<div class='runwrap'>{card}<button class='delete server-only' "
            f"data-url='/api/{city}/{what}/{html.escape(design)}' data-what='{what}' "
            f"data-label='{label}' title='delete it'>Delete</button></div>")


def _city_actions(city, kind, runs, here):
    """The cards opening a city's public-transport sections: the editor, running a simulation
    (both when served), comparing its simulations (its compare page, written here too)."""
    from transit import TRANSIT_CASES
    if kind != "macro" and city not in TRANSIT_CASES:
        return ""

    def card(title, text, href, extra=""):
        return (f"<a class='run kind action{extra}' href='{href}'><div class='name'>{title}"
                f"</div><p>{text}</p></a>")

    def needs_server(title):
        return (f"<div class='run kind empty file-only'><div class='name'>{title}</div><p>This "
                f"runs from a small server on this computer: start it with <code>python "
                f"serve.py</code>, which opens these pages at http://localhost:8000.</p></div>")

    if kind == "macro":
        out = (card("▶ Run a macrosimulation", "Change any of the road model's parameters - "
                    "trips, car share, speeds, the gravity model, the cost function - name the "
                    "run, and run it.", f"/macro/{city}", " server-only")
               + needs_server("▶ Run a macrosimulation"))
        done = [r for r in runs if summary.read(r)]
        if done:
            # Scenarios are made from a computed run, on the Scenarios page (when served).
            out += (card("✎ Scenarios", "Make a scenario from a computed run: close roads, change "
                         "their capacity or speed - on its map, from the corridors it suggests - "
                         "run it on the same trips, and compare it with its run.",
                         f"/scenario/{city}", " server-only")
                    + needs_server("✎ Scenarios"))
            # One run's files too: the Scenarios page reads them; the compare page needs two.
            from . import macro_compare
            try:
                page = macro_compare.build(city, _city_label(city, {kind: done}), done,
                                           {r: _name(r).split(" – ", 1)[-1] for r in done})
            except Exception as problem:                   # noqa: BLE001 - a list without it
                print(f"(the compare page of {city}'s road runs was not built: {problem})")
                page = None
            if page:
                href = os.path.relpath(page, here).replace(os.sep, "/")
                out += card("Compare road runs", "Pick one run as the baseline and another as the "
                            "alternative: what each changed, the headline numbers, where the "
                            "traffic moved, the streets that changed most.", href)
        return out
    if kind == "design":
        return (card("✎ Create or edit a design", "Start from the baseline or an existing "
                     "design: change frequencies and speeds, remove lines, draw new ones on a "
                     "map, and save it under a name.", f"/editor/{city}", " server-only")
                + needs_server("✎ Create or edit a design"))
    from . import compare_page
    out = (card("▶ Run a simulation", "Choose a design and the assignment's parameters, and "
                "assign the passengers to it.", f"/simulate/{city}", " server-only")
           + needs_server("▶ Run a simulation"))
    if runs:
        page = compare_page.build(SIMULATION_OUTPUT, city, runs, {r: _name(r) for r in runs})
        href = os.path.relpath(os.path.join(SIMULATION_OUTPUT, page), here).replace(os.sep, "/")
        out += card("Compare simulations", "Pick one simulation as the baseline and another as "
                    "the alternative: the headline numbers, where passengers moved, every "
                    "segment.", href)
    return out


def _page(output_dir, runs):
    """One run's page."""
    maps_dir = os.path.join(output_dir, "maps")
    exports_dir = os.path.join(output_dir, "exports")
    maps = sorted(_files(maps_dir, ".html"), key=_map_order)
    kind = _kind(output_dir)
    main_maps = KINDS[kind]["main_maps"]
    labels = list(main_maps.values())
    main = sorted((m for m in maps if _main_label(m, main_maps)),
                  key=lambda m: labels.index(_main_label(m, main_maps)))
    more = [m for m in maps if m not in main]
    tables = sorted(t for t in _files(exports_dir, ".csv") if t not in SHOWN_ELSEWHERE
                    and _rows(os.path.join(exports_dir, t)) <= TABLE_ROW_LIMIT)
    exports = sorted(_files(exports_dir))
    run = summary.read(output_dir)

    nav, views = [], []
    if maps:
        nav.append("<h2>Maps</h2>")
        for name in main:
            nav.append(_link(f"map={name}", _main_label(name, main_maps)))
        if more:
            nav.append("<details class='more'><summary>More maps</summary>"
                       + "".join(_link(f"map={name}", _map_title(name)) for name in more)
                       + "</details>")
    nav.append("<h2>Statistics</h2>")
    for key, label, body in KINDS[kind]["stats"](run, output_dir):
        nav.append(_link(key, label))
        views.append(_view(key, body))
    feed = KINDS[kind]["feed"](output_dir) if KINDS[kind]["feed"] else []
    if feed:
        nav.append("<h2>Feed</h2>")
        for key, label, body in feed:
            nav.append(_link(key, label))
            views.append(_view(key, body))
    groups = _parameters(output_dir)
    if groups:
        nav.append("<h2>Parameters</h2>")
        for n, (group, rows) in enumerate(groups):
            key = f"parameters={n}"
            nav.append(_link(key, html.escape(group.removesuffix(" parameters"))))
            views.append(_view(key, _parameter_table(group, rows)))
    if tables:
        nav.append("<h2>Tables</h2>")
        for name in tables:
            key = f"table={name}"
            nav.append(_link(key, _plain(name[:-4])))
            views.append(_view(key, _table(os.path.join(exports_dir, name), name)))
    nav.append("<h2>Run</h2>")
    nav.append(_link("log", "Run log"))
    views.append(_view("log", _log(os.path.join(output_dir, "run_log.txt"))))
    nav.append(_link("exports", "Exported files"))
    views.append(_view("exports", _exports(exports_dir, exports)))
    # One frame for every map: a map can run to tens of MB, so it loads only when chosen.
    views.append('<section class="view map" data-view="map"><iframe title="map"></iframe></section>')

    first = f"map={(main or maps)[0]}" if maps else "statistics"
    page = TEMPLATE.format(style=STYLE, icon=ICON, title=html.escape(_name(output_dir)),
                           sub=html.escape(f"{KINDS[kind]['when'].lower()} "
                                           f"{_last_run(output_dir)}"),
                           switch=_switch(output_dir, runs, kind),
                           first=html.escape(first),
                           nav="\n".join(nav), views="\n".join(views))
    path = os.path.join(output_dir, PAGE)
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    return path


# --- the parts ---------------------------------------------------------------------------------
def _parameters(output_dir):
    """[(group, rows)] from parameters.csv; a run older than it has assumptions.csv alone."""
    path = os.path.join(output_dir, "exports", "parameters.csv")
    if os.path.exists(path):
        with open(path, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    else:
        path = os.path.join(output_dir, "exports", "assumptions.csv")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8", newline="") as f:
            rows = [{"group": "Parameters", "name": r[""], "kind": "assumed", **r}
                    for r in csv.DictReader(f)]
    groups = {}
    for row in rows:
        groups.setdefault(row["group"], []).append(row)
    # In the order of GROUPS now, not of when the run wrote the file.
    order = list(GROUPS) + [OTHER]
    return sorted(groups.items(),
                  key=lambda g: order.index(g[0]) if g[0] in order else len(order))


def _parameter_table(group, rows):
    # A value a named run changed carries the settings module's next to it.
    body = "".join(
        f"<tr><td class='pname'>{html.escape(r['name'])}</td>"
        f"<td class='pvalue'>{html.escape(r['value'])}"
        + (f"<div class='was'>changed by this run · default {html.escape(r['default'])}</div>"
           if r.get("default") else "") + "</td>"
        f"<td>{html.escape(r['unit'])}</td>"
        f"<td class='why'>{html.escape(r['why']) if r['kind'] == 'assumed' else ''}"
        f"{'<span class=tag>method setting</span>' if r['kind'] == 'setting' else ''}</td></tr>"
        for r in rows)
    return (f"<h1>{html.escape(group)}</h1>"
            f"<p class='note'>{len(rows)} parameters. To change one, run the city with it changed "
            f"(Run a macrosimulation, when served) or edit its <code>cases/&lt;city&gt;/"
            f"settings.py</code>.</p>"
            f"<div class='scroll'><table class='params'><thead><tr><th>parameter</th>"
            f"<th>value</th><th>unit</th><th>why this value</th></tr></thead>"
            f"<tbody>{body}</tbody></table></div>")


def _table(path, name):
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return f"<h1>{_plain(name[:-4])}</h1><p class='note'>Empty file.</p>"
    head, body = rows[0], rows[1:]
    head = [h or "name" for h in head]
    th = "".join(f"<th>{html.escape(h)}</th>" for h in head)
    tr = "\n".join("<tr>" + "".join(_cell(c) for c in r) + "</tr>" for r in body)
    return (f"<h1>{_plain(name[:-4])}</h1>"
            f"<p class='note'>{len(body):,} rows · <code>exports/{html.escape(name)}</code> · "
            f"click a column to sort</p>"
            f"<input class='filter' type='search' placeholder='Filter rows'>"
            f"<div class='scroll'><table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody>"
            f"</table></div>")


def _cell(text):
    """Numbers rounded for reading and right-aligned; the sort uses the full value."""
    try:
        x = float(text)
    except ValueError:
        return f"<td>{html.escape(text)}</td>"
    if not math.isfinite(x):                     # NaN, inf: as written
        shown = html.escape(text)
    elif x == int(x) and abs(x) < 1e15:
        shown = f"{int(x):,}"
    elif abs(x) >= 100:
        shown = f"{x:,.0f}"
    elif abs(x) >= 1:
        shown = f"{x:.2f}"
    else:
        shown = f"{x:.3g}"
    return f"<td class='n' data-v='{x!r}'>{shown}</td>"


def _log(path):
    if not os.path.exists(path):
        return "<h1>Run log</h1><p class='note'>No run_log.txt in this folder.</p>"
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    # Sections are a title between two rules of '=' (report.section).
    sections, title, text, i = [], "Start", [], 0
    while i < len(lines):
        if RULE.match(lines[i]) and i + 2 < len(lines) and RULE.match(lines[i + 2]):
            sections.append((title, text))
            title, text, i = lines[i + 1].strip(), [], i + 3
            continue
        text.append(lines[i])
        i += 1
    sections.append((title, text))
    sections = [(t, x) for t, x in sections if "\n".join(x).strip()]
    toc = "".join(f"<li><a href='#log' data-jump='log-{n}'>{html.escape(t)}</a></li>"
                  for n, (t, _) in enumerate(sections))
    parts = "".join(f"<h3 id='log-{n}'>{html.escape(t)}</h3>"
                    f"<pre>{html.escape(chr(10).join(x).strip(chr(10)))}</pre>"
                    for n, (t, x) in enumerate(sections))
    return f"<h1>Run log</h1><ul class='toc'>{toc}</ul>{parts}"


def _exports(folder, files):
    if not files:
        return "<h1>Exported files</h1><p class='note'>Nothing in exports/.</p>"
    rows = "".join(f"<tr><td><a href='exports/{html.escape(f)}'>{html.escape(f)}</a></td>"
                   f"<td class='n'>{os.path.getsize(os.path.join(folder, f)) / 1e6:,.2f} MB</td>"
                   f"</tr>" for f in files)
    kinds = {os.path.splitext(f)[1].lower() for f in files}
    said = [text for ext, text in EXPORT_KINDS if ext in kinds]
    return (f"<h1>Exported files</h1><p class='note'>In <code>{html.escape(os.path.abspath(folder))}"
            f"</code>.{' ' + ' '.join(said) if said else ''}</p><table class='files'>{rows}</table>")


# What opens each kind of exported file: said only for the kinds a run's exports hold.
EXPORT_KINDS = [(".gpkg", "The .gpkg files open in QGIS."),
                (".geojson", "The .geojson files open in QGIS or any web map."),
                (".omx", "The .omx matrix opens in AequilibraE or any OMX reader."),
                (".zip", "The GTFS feed (.zip) opens in any GTFS tool."),
                (".csv", "The .csv tables open in a spreadsheet.")]


def _switch(output_dir, runs, kind):
    """The top of a run's page: back to its city, and a menu of the city's runs of its kind."""
    city = _city_key(output_dir)
    options = []
    for run in runs:
        if _city_key(run) != city:
            continue
        folder = os.path.basename(run)
        name = _name(run)
        # The folder only when the name does not already say which run it is.
        plain = True                       # the name says which run it is
        label = name if plain else f"{name} ({folder})"
        chosen = " selected" if run == output_dir else ""
        options.append(f"<option value='../{html.escape(folder)}/{PAGE}'{chosen}>"
                       f"{html.escape(label)}</option>")
    back = (os.path.relpath(city_page(city, kind), output_dir).replace(os.sep, "/"),
            KINDS[kind]["title"])
    info = summary.read(output_dir) or {}
    design = ""
    if kind == "transit" and info.get("design"):
        # A simulation's design, whose page has its lines, maps and timetable.
        page = f"../../designs/{_city_key(output_dir)}-{info['design']['name']}/{PAGE}"
        if os.path.exists(os.path.join(output_dir, page)):     # a deleted design: no link
            design = (f"<a class='edit' href='{page}'>Design: "
                      f"{html.escape(info['design']['label'])} →</a>")
    if kind == "design" and info.get("design"):
        # A design's simulation, if it has one, and (served) simulating and editing it.
        city, name = _city_key(output_dir), info["design"]
        page = f"../../simulations/{city}-{name}/{PAGE}"
        links = ([f"<a class='edit' href='{page}'>Open its last simulation →</a>"]
                 if os.path.exists(os.path.join(output_dir, page)) else []) + [
            f"<a class='edit server-only' href='/simulate/{city}?design={name}'>▶ Simulate it</a>",
            f"<a class='edit server-only' href='/editor/{city}?scenario={name}'>✎ Edit it</a>"]
        design = f"<div class='side-links'>{''.join(links)}</div>"
    return (f"<a class='home' href='{back[0]}'>← {back[1]}</a>"
            f"<select class='switch' onchange='location.href = this.value'>"
            f"{''.join(options)}</select>{design}")


# --- helpers -----------------------------------------------------------------------------------
def _files(folder, ext=""):
    if not os.path.isdir(folder):
        return []
    return [f for f in os.listdir(folder)
            if f.endswith(ext) and os.path.isfile(os.path.join(folder, f))]


def _map_order(name):
    """Maps are numbered in the order the run draws them: 2_ before 10_."""
    number = re.match(r"(\d+)_", name)
    return (int(number.group(1)) if number else 999, name)


def _rows(path):
    with open(path, encoding="utf-8", newline="") as f:
        return sum(1 for _ in f) - 1


def _name(output_dir):
    """The city and the run: "Quito – L1 service doubled", "Sorocaba – baseline"."""
    info = summary.read(output_dir)
    if not info:
        return os.path.basename(os.path.normpath(output_dir)).title()
    if info.get("kind") == "design":
        return f"{info['city']} – {info['label']}"
    if info.get("kind") == "transit":
        design = info.get("design") or {"label": "baseline"}
        short = (info.get("simulated") or {}).get("short")
        return f"{info['city']} – {design['label']}" + (f" · {short}" if short else "")
    # A road run: the baseline, or a named run (core/runs.py) - a run older than those, baseline;
    # a scenario says which run it is made from.
    run = info.get("run") or {}
    return (f"{info['city']} – {run.get('label', 'baseline')}"
            + (f" (scenario of {run['base']})" if run.get("base") else ""))


def _last_run(output_dir):
    """When the run finished: from its summary, or when its log was last written."""
    info = summary.read(output_dir)
    if info:
        return info["finished"]
    log = os.path.join(output_dir, "run_log.txt")
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(log)))


def _main_label(name, main_maps):
    """'simulation.html' -> 'Simulation'; None for a map not among the kind's main maps."""
    stem = re.sub(r"^\d+_", "", name[:-5])
    return main_maps.get(stem)


def _map_title(name):
    """'5_zones_car_ownership.html' -> 'Zones car ownership'."""
    return _plain(re.sub(r"^\d+_", "", name[:-5]))


def _plain(stem):
    """'zones_car_ownership' -> 'Zones car ownership'."""
    text = stem.replace("_", " ").strip()
    return html.escape(text[:1].upper() + text[1:])


def _link(key, label):
    return f"<a class='nav' href='#{html.escape(key)}'>{label}</a>"


def _view(key, body):
    return f"<section class='view' data-view='{html.escape(key)}'>{body}</section>"


STYLE = """  :root { --ink:#1d2329; --soft:#5d6873; --line:#dde2e7; --bg:#f6f7f9; --panel:#fff;
           --accent:#1f6feb; --pick:#e8f0fe; }
  * { box-sizing:border-box; }
  html, body { height:100%; margin:0; }
  body { display:flex; font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;
          color:var(--ink); background:var(--bg); }
  nav { width:240px; flex:none; overflow-y:auto; background:var(--panel);
         border-right:1px solid var(--line); padding:16px 10px; }
  nav .title { font-size:18px; font-weight:650; padding:0 8px; }
  nav .sub { color:var(--soft); font-size:12px; padding:0 8px 12px; }
  nav h2 { font-size:11px; letter-spacing:.06em; text-transform:uppercase; color:var(--soft);
            margin:16px 8px 4px; }
  a.nav { display:block; padding:5px 8px; border-radius:6px; color:var(--ink);
           text-decoration:none; }
  a.nav:hover { background:var(--bg); }
  a.nav.on { background:var(--pick); color:var(--accent); font-weight:600; }
  .num { display:inline-block; min-width:20px; color:var(--soft); font-variant-numeric:tabular-nums; }
  main { flex:1; min-width:0; position:relative; }
  .view { display:none; position:absolute; inset:0; overflow:auto; padding:24px 32px; }
  .view.on { display:block; }
  .view.map { padding:0; overflow:hidden; }
  iframe { width:100%; height:100%; border:0; background:#fff; }
  h1 { font-size:22px; margin:0 0 6px; }
  h3 { font-size:14px; margin:22px 0 6px; padding-top:8px; border-top:1px solid var(--line); }
  .note { color:var(--soft); margin:0 0 16px; }
  code { font-size:12px; background:var(--bg); padding:1px 4px; border-radius:4px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:12px;
            margin:8px 0 20px; max-width:1000px; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px 14px; }
  .card .k { color:var(--soft); font-size:12px; }
  .card .v { font-size:20px; font-weight:600; margin-top:2px; }
  .button { display:inline-block; background:var(--accent); color:#fff; padding:8px 14px;
             border-radius:6px; text-decoration:none; }
  .filter { width:280px; padding:6px 10px; border:1px solid var(--line); border-radius:6px;
             margin-bottom:10px; font:inherit; }
  .scroll { overflow:auto; max-height:calc(100vh - 170px); border:1px solid var(--line);
             border-radius:6px; background:var(--panel); }
  table { border-collapse:collapse; font-size:13px; }
  th, td { padding:5px 10px; border-bottom:1px solid var(--line); text-align:left;
            vertical-align:top; }
  th { position:sticky; top:0; background:var(--bg); cursor:pointer; white-space:nowrap; }
  th.up::after { content:" ▲"; } th.down::after { content:" ▼"; }
  td { max-width:520px; }
  td.n { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
  table.files { background:var(--panel); border:1px solid var(--line); }
  pre { background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:10px 12px;
         font:12px/1.4 Consolas,"Cascadia Mono",monospace; overflow-x:auto; margin:0; }
  .toc { columns:2; max-width:900px; padding-left:18px; }
  .toc a { color:var(--accent); text-decoration:none; }
  details.more summary { cursor:pointer; padding:5px 8px; color:var(--soft); border-radius:6px; }
  details.more summary:hover { background:var(--bg); }
  details.more a.nav { padding-left:22px; }
  table.params { width:100%; max-width:1300px; }
  table.params th { cursor:default; }
  td.pname { font:12px Consolas,"Cascadia Mono",monospace; white-space:nowrap; }
  td.pvalue { font:12px Consolas,"Cascadia Mono",monospace; max-width:300px; word-break:break-word; }
  td.why { color:var(--soft); max-width:560px; }
  .tag { display:inline-block; font-size:11px; color:var(--soft); border:1px solid var(--line);
         border-radius:10px; padding:0 7px; }
  h2.section { font-size:16px; margin:28px 0 4px; }
  .figs { display:flex; gap:28px; margin:10px 0 8px; flex-wrap:wrap; }
  .figs span { display:block; color:var(--soft); font-size:12px; }
  .figs b { font-size:18px; font-variant-numeric:tabular-nums; }
  .chart { position:relative; max-width:760px; background:var(--panel);
           border:1px solid var(--line); border-radius:8px; padding:12px 12px 4px; }
  .chart svg { width:100%; height:auto; display:block; }
  .chart.wide { max-width:1000px; }
  .chart .grid { stroke:#e9ecef; stroke-width:1; }
  .chart .axis { stroke:#c4cad0; stroke-width:1; }
  .chart .tick { font-size:11px; fill:var(--soft); font-variant-numeric:tabular-nums; }
  .chart .hit { fill:transparent; }
  .chart .col:hover .bar { opacity:.8; }
  .chart .dot { opacity:0; stroke:var(--panel); stroke-width:2; }
  .chart .col:hover .dot { opacity:1; }
  .seg { display:inline-flex; border:1px solid var(--line); border-radius:7px; overflow:hidden;
         margin:4px 0 14px; background:var(--panel); }
  .seg button { font:inherit; border:0; background:none; padding:6px 14px; cursor:pointer;
                color:var(--ink); border-right:1px solid var(--line); }
  .seg button:last-child { border-right:0; }
  .seg button.on { background:var(--pick); color:var(--accent); font-weight:600; }
  .legend { display:flex; gap:16px; flex-wrap:wrap; font-size:12px; color:var(--soft);
            margin:6px 0 8px; }
  .legend i { display:inline-block; width:12px; height:10px; border-radius:2px; margin-right:6px;
              vertical-align:middle; }
  .legend i.line { width:16px; height:2px; border-radius:1px; }
  .lead { font-size:15px; margin:4px 0 12px; }
  table.compare { margin:0 0 14px; background:var(--panel); border:1px solid var(--line); }
  table.compare th { cursor:default; }
  table.compare i { display:inline-block; width:12px; height:2px; margin-right:6px;
                    vertical-align:middle; }
  .hbars { padding:14px 16px 10px; }
  .hrow.single { grid-template-columns:1fr; margin:0; }
  .hrow.single .hbar { height:26px; border-radius:4px; }
  .hrow { display:grid; grid-template-columns:110px 1fr 170px; align-items:center; gap:12px;
          margin-bottom:10px; }
  .hname { color:var(--ink); }
  .hbar { display:flex; gap:2px; height:18px; border-radius:0 4px 4px 0; overflow:hidden; }
  .hbar .seg-part { min-width:2px; }
  .hval { font-variant-numeric:tabular-nums; }
  .hval span { display:block; font-size:11px; color:var(--soft); }
  .chart .tip { position:absolute; pointer-events:none; background:var(--ink); color:#fff;
                font-size:12px; padding:4px 8px; border-radius:4px; white-space:nowrap; }
  details.as-table { margin:10px 0 0; max-width:760px; }
  ul.changes { margin:0 0 12px; padding-left:20px; }
  details.as-table summary { cursor:pointer; color:var(--accent); font-size:13px; }
  details.as-table table { margin-top:8px; background:var(--panel); border:1px solid var(--line); }
  i.chip { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:7px;
           vertical-align:middle; }
  .legend.toggles button { font:inherit; font-size:12px; color:var(--ink); background:none;
      border:1px solid var(--line); border-radius:12px; padding:2px 9px; cursor:pointer; }
  .legend.toggles button.series:not(.on) { color:var(--soft); opacity:.55;
      text-decoration:line-through; }
  .legend.toggles .series-none { margin-right:8px; }
  .legend i.band { width:14px; height:10px; background:#eef0f3; border:1px solid var(--line); }
  .chart .period { fill:#eef0f3; }
  select.pick { font:inherit; padding:6px 10px; border:1px solid var(--line); border-radius:6px;
                background:var(--panel); margin:0 0 12px; max-width:100%; }
  .route-cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(420px,1fr)); gap:16px; }
  .route-card { background:var(--panel); border:1px solid var(--line); border-radius:8px;
                padding:12px 16px; }
  .route-card h3 { border:0; margin:0 0 10px; padding:0; font-size:15px; }
  .route-card h3 span { font-weight:400; color:var(--soft); font-size:12px; }
  .strips { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
  .strip .towards { font-size:12px; color:var(--soft); margin-bottom:6px; }
  .strip ol { list-style:none; margin:0; padding:0 0 0 22px; position:relative; }
  .strip ol::before { content:""; position:absolute; left:6px; top:9px; bottom:9px; width:4px;
                      border-radius:2px; background:var(--route); }
  .strip li { position:relative; padding:3px 0; font-size:13px; }
  .strip li::before { content:""; position:absolute; left:-20px; top:7px; width:10px;
                      height:10px; border-radius:50%; background:var(--panel);
                      border:2px solid var(--route); }
  .strip li.interchange::before { width:14px; height:14px; left:-22px; top:5px;
                                  border:3px solid var(--ink); }
  .strip .notes { display:block; font-size:11px; color:var(--soft); }
  .boards { display:flex; flex-wrap:wrap; gap:16px; }
  .board { background:var(--panel); border:1px solid var(--line); border-radius:8px;
           padding:10px 14px; }
  .board h3 { border:0; margin:0 0 6px; padding:0; font-size:14px; }
  .board td { border:0; padding:1px 8px 1px 0; font:12px Consolas,"Cascadia Mono",monospace; }
  .board td.h { font-weight:700; }
  td.none { color:var(--soft); font-style:italic; }
  .ttpick { display:flex; flex-wrap:wrap; gap:12px; align-items:flex-end; margin:0 0 6px; }
  .ttpick label { display:flex; flex-direction:column; font-size:12px; color:var(--soft); gap:4px; }
  .ttpick input, .ttpick select { font:inherit; padding:6px 10px; border:1px solid var(--line);
      border-radius:6px; background:var(--panel); min-width:180px; }
  .board .service { font-size:13px; margin:0 0 6px; }
  .ttways { display:flex; flex-wrap:wrap; align-items:stretch; gap:14px; margin:0 0 6px; }
  .ttway { background:var(--panel); border:1px solid var(--line); border-radius:8px;
      padding:10px 14px 4px; }
  .ttway .how { font-size:12px; font-weight:650; color:var(--ink); margin:0 0 6px; }
  .ttways .or { align-self:center; color:var(--soft); font-size:13px; font-style:italic; }
  .board details summary { font-size:12px; color:var(--accent); cursor:pointer; }
  .board details table { margin-top:6px; }
  /* Shown only when the pages are served (serve.py), or only when opened as files. */
  html:not(.served) .server-only, .served .file-only { display:none !important; }
  a.edit { color:var(--accent); text-decoration:none; font-size:12px; padding:2px 8px 8px; }
  .side-links { padding:0 0 6px; }
  .side-links a.edit { display:block; padding:3px 8px; }
  a.home { display:block; color:var(--accent); text-decoration:none; font-size:12px;
           padding:0 8px 6px; }
  select.switch { width:100%; font:inherit; font-size:16px; font-weight:650; color:var(--ink);
                  padding:5px 6px; border:1px solid var(--line); border-radius:6px;
                  background:var(--panel); cursor:pointer; margin-bottom:4px; }
  .home-page { display:block; padding:32px; max-width:1100px; }
  .runs { display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:16px; }
  a.run { display:block; background:var(--panel); border:1px solid var(--line); border-radius:10px;
          padding:16px 18px; color:var(--ink); text-decoration:none; }
  a.run:hover { border-color:var(--accent); box-shadow:0 2px 8px rgba(31,111,235,.12); }
  a.run .name { font-size:20px; font-weight:650; }
  a.run .when { color:var(--soft); font-size:12px; margin-bottom:10px; }
  .run.kind p { color:var(--soft); margin:6px 0 10px; }
  .run.kind .name { font-size:22px; }
  .run.empty { display:block; background:var(--panel); border:1px dashed var(--line);
               border-radius:10px; padding:16px 18px; color:var(--soft); }
  .home-page a.home { padding:0 0 10px; }
  .dash { display:grid; grid-template-columns:repeat(auto-fit,minmax(380px,1fr)); gap:20px;
           margin-top:12px; }
  .dash .col { background:var(--panel); border:1px solid var(--line); border-radius:10px;
                padding:18px 20px; }
  .home-page .dash h2 { margin:0 0 4px; font-size:22px; }
  .dash h2 a { color:var(--ink); text-decoration:none; }
  .dash h2 a:hover { color:var(--accent); }
  .dash .note { margin:0; }
  .dash .acts { display:flex; flex-wrap:wrap; gap:8px; margin:14px 0 6px; }
  .dash .btn { display:inline-block; padding:7px 14px; border-radius:6px; font-size:14px;
                border:1px solid var(--accent); color:var(--accent); text-decoration:none; }
  .dash a.btn.primary { background:var(--accent); color:#fff; }
  .dash span.btn.off { border-color:var(--line); color:var(--soft); cursor:default; }
  .dash h3 { font-size:13px; color:var(--soft); font-weight:600; margin:16px 0 4px; }
  .minis a { display:flex; justify-content:space-between; gap:12px; padding:6px 8px;
             border-radius:6px; color:var(--ink); text-decoration:none; font-size:14px; }
  .minis a:hover { background:var(--pick); }
  .minis .w { color:var(--soft); font-size:12px; white-space:nowrap; }
  .dash a.more { display:inline-block; margin:4px 8px 0; font-size:13px; color:var(--accent);
                  text-decoration:none; }
  .home-page h2 { font-size:19px; margin:30px 0 2px; }
  .home-page h2 + .note { margin:0 0 12px; }
  h2.scen-title { font-size:17px; margin:18px 0 6px; }
  p.warn { border:1px solid #f0d58c; background:#fff8e1; border-radius:6px; padding:8px 12px;
           max-width:900px; }
  ul.edits { margin:4px 0 12px; padding-left:20px; }
  ul.edits .muted { color:var(--soft); }
  table.scen { border-collapse:collapse; background:var(--panel); font-size:13px; margin:0 0 14px; }
  table.scen th, table.scen td { padding:4px 12px; border-bottom:1px solid var(--line);
                                 text-align:left; }
  table.scen th { color:var(--soft); font-weight:600; }
  table.scen td.n { text-align:right; font-variant-numeric:tabular-nums; }
  table.scen .up { color:#c2410c; } table.scen .down { color:#1d4ed8; }
  .scen-streets { display:flex; flex-wrap:wrap; gap:24px; }
  .scen-streets h3 { border:0; margin:6px 0; padding:0; }
  .runwrap { position:relative; }
  .runwrap a.run { height:100%; }
  .runwrap a.run .name { padding-right:64px; }
  .runwrap button.delete { position:absolute; top:12px; right:12px; font:inherit;
      font-size:12px; padding:3px 9px; border:1px solid var(--line); border-radius:5px;
      background:var(--panel); color:var(--soft); cursor:pointer; }
  .runwrap button.delete:hover { border-color:#c62828; color:#c62828; }
  .params .was { font-size:11px; color:#b45309; font-weight:600; margin-top:2px; }
  a.run .lines { display:grid; grid-template-columns:auto auto; gap:3px 14px; font-size:13px; }
  a.run .k { color:var(--soft); }
  a.run .v { font-weight:600; text-align:right; }
"""

# The bar across the top: drawn by the page's style alone, so every page has it as it is. The
# body starts below it (its height is in the body's, every box being border-box); the bar's colour
# is the logo's own background; after it, a thin rule and the tool's name.
STYLE += f"""  :root {{ --bar:46px; }}
  body {{ padding-top:var(--bar); }}
  body::before {{ content:"{BAR_TITLE}"; position:fixed; z-index:2000; top:0; left:0; right:0;
                  height:var(--bar); line-height:var(--bar); padding-left:154px;
                  border-bottom:1px solid var(--line); font-size:15px; font-weight:500;
                  color:var(--soft); white-space:nowrap; overflow:hidden;
                  background:url({BAR_LOGO}) no-repeat 14px center / auto 36px,
                    linear-gradient(var(--line), var(--line)) no-repeat 140px center / 1px 22px,
                    #f0f7f9; }}
  .topnav {{ position:fixed; z-index:2001; top:0; left:372px; right:12px; height:var(--bar);
             display:flex; align-items:center; gap:2px; font-size:14px; }}
  .topnav a.city {{ font-weight:650; color:var(--ink); text-decoration:none; padding:6px 4px 6px 10px; }}
  .topnav .menu {{ position:relative; }}
  .topnav button {{ font:inherit; color:var(--ink); background:none; border:0; border-radius:6px;
                    padding:6px 10px; cursor:pointer; }}
  .topnav button:hover, .topnav .open > button {{ background:#dcebef; }}
  .topnav .items {{ display:none; position:absolute; top:calc(100% + 2px); left:0; min-width:210px;
                    background:var(--panel); border:1px solid var(--line); border-radius:8px;
                    box-shadow:0 6px 20px rgba(0,0,0,.12); padding:6px 0; }}
  .topnav .open .items {{ display:block; }}
  .topnav .items a, .topnav .items span {{ display:block; padding:6px 14px; color:var(--ink);
                                           text-decoration:none; white-space:nowrap; }}
  .topnav .items a:hover {{ background:var(--pick); }}
  .topnav .items a.here {{ font-weight:650; }}
  .topnav .items span.off {{ color:var(--soft); cursor:default; }}
  .topnav .items hr {{ border:0; border-top:1px solid var(--line); margin:6px 0; }}
"""

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} results</title>
{icon}
<style>
{style}</style>
</head>
<body>
<script>if (location.protocol.startsWith("http")) document.documentElement.classList.add("served");</script>
<nav>
  {switch}
  <div class="sub">{sub}</div>
{nav}
</nav>
<main>
{views}
</main>
<script>
  // The address after # says what is shown (#map=simulation.html), so reloading the page or
  // the browser's back button keeps your place.
  const frame = document.querySelector('.view.map iframe');
  function show() {{
    const key = decodeURIComponent(location.hash.slice(1)) || '{first}';
    const isMap = key.startsWith('map=');
    document.querySelectorAll('.view').forEach(v =>
      v.classList.toggle('on', isMap ? v.dataset.view === 'map' : v.dataset.view === key));
    document.querySelectorAll('a.nav').forEach(a => {{
      const on = decodeURIComponent(a.getAttribute('href').slice(1)) === key;
      a.classList.toggle('on', on);
      if (on && a.closest('details')) a.closest('details').open = true;
    }});
    if (isMap) {{
      const src = 'maps/' + key.slice(4);
      if (frame.getAttribute('src') !== src) frame.setAttribute('src', src);
    }}
  }}
  window.addEventListener('hashchange', show);
  show();

  // Run log: jump to a section without changing the address.
  document.querySelectorAll('[data-jump]').forEach(a => a.addEventListener('click', e => {{
    e.preventDefault();
    document.getElementById(a.dataset.jump).scrollIntoView();
  }}));

  // Charts: the hover note of the column under the pointer.
  document.querySelectorAll('.chart').forEach(chart => {{
    const tip = chart.querySelector('.tip');
    chart.querySelectorAll('.col').forEach(col => {{
      col.addEventListener('mousemove', e => {{
        const box = chart.getBoundingClientRect();
        tip.textContent = col.dataset.tip;
        tip.hidden = false;
        const x = Math.min(e.clientX - box.left + 12, box.width - tip.offsetWidth - 4);
        tip.style.left = x + 'px';
        tip.style.top = (e.clientY - box.top - 30) + 'px';
      }});
      col.addEventListener('mouseleave', () => {{ tip.hidden = true; }});
    }});
  }});

  // Selectors: one panel of a view at a time.
  document.querySelectorAll('.seg').forEach(seg => {{
    const view = seg.closest('.view');
    seg.querySelectorAll('button').forEach(button => button.addEventListener('click', () => {{
      seg.querySelectorAll('button').forEach(b => b.classList.toggle('on', b === button));
      view.querySelectorAll('.panel').forEach(p =>
        p.hidden = p.dataset.panel !== button.dataset.panel);
    }}));
  }});

  // Pickers: a <select> showing one panel of its view at a time, or all of them ("*").
  document.querySelectorAll('select.pick').forEach(pick => pick.addEventListener('change', () => {{
    pick.closest('.view').querySelectorAll('.panel').forEach(p =>
      p.hidden = pick.value !== '*' && p.dataset.panel !== pick.value);
  }}));

  // Tables: filter rows by text, sort by a column (numbers by value).
  document.querySelectorAll('.filter').forEach(input => input.addEventListener('input', () => {{
    const words = input.value.toLowerCase();
    input.parentElement.querySelectorAll('tbody tr').forEach(tr =>
      tr.style.display = tr.textContent.toLowerCase().includes(words) ? '' : 'none');
  }}));
  document.querySelectorAll('th').forEach((th, _, all) => th.addEventListener('click', () => {{
    const table = th.closest('table'), body = table.tBodies[0];
    const col = [...th.parentElement.children].indexOf(th);
    const up = !th.classList.contains('up');
    th.parentElement.querySelectorAll('th').forEach(h => h.classList.remove('up', 'down'));
    th.classList.add(up ? 'up' : 'down');
    const value = tr => {{
      const td = tr.children[col];
      return td && td.dataset.v !== undefined ? parseFloat(td.dataset.v) : (td ? td.textContent : '');
    }};
    const rows = [...body.rows].sort((a, b) => {{
      const x = value(a), y = value(b);
      const order = typeof x === 'number' && typeof y === 'number'
        ? (isNaN(x) ? 1 : isNaN(y) ? -1 : x - y)
        : String(x).localeCompare(String(y));
      return up ? order : -order;
    }});
    rows.forEach(r => body.appendChild(r));
  }}));
</script>
</body>
</html>
"""

HOME = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} results</title>
{icon}
<style>
{style}</style>
</head>
<body>
<script>if (location.protocol.startsWith("http")) document.documentElement.classList.add("served");</script>
<main class="home-page">
  <a class="home" href="{back}">← {back_label}</a>
  <h1>{title}</h1>
  <p class="note">Pick one. Each page has a menu at the top to go to the others. They are in
  <code>{root}</code>.</p>
  <div class="runs">{runs}</div>
</main>
</body>
</html>
"""

CHOICE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{icon}
<style>
{style}</style>
</head>
<body>
<main class="home-page">
  <a class="home" href="{back}">← {back_label}</a>
  <h1>{title}</h1>
  <p class="note">What would you like to do?</p>
  <div class="runs">{cards}</div>
</main>
</body>
</html>
"""

LIST = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{icon}
<style>
{style}</style>
</head>
<body>
<script>if (location.protocol.startsWith("http")) document.documentElement.classList.add("served");</script>
<main class="home-page">
  <a class="home" href="{back}">← {back_label}</a>
  <h1>{title}</h1>
  <p class="note">{note}</p>
  <div class="runs">{runs}</div>
</main>
<script>
// Delete a design or a simulation: only when served, after asking.
document.addEventListener("click", async e => {{
  const button = e.target.closest("button.delete");
  if (!button) return;
  const d = button.dataset;
  const ask = d.what === "designs"
    ? `Delete the design "${{d.label}}"? Its file and its pages are deleted; its simulation, ` +
      `if it has one, is kept.`
    : d.what === "macro"
    ? `Delete the run "${{d.label}}"? Its file and its results are deleted.`
    : `Delete the simulation "${{d.label}}"? Its results are deleted; its design is kept and ` +
      `can be simulated again.`;
  if (!confirm(ask)) return;
  button.disabled = true;
  button.textContent = "Deleting…";
  let response;
  try {{ response = await fetch(d.url, {{method: "DELETE"}}); }}
  catch (problem) {{                         // the server is not there: say so, not "Deleting…"
    alert(`The server did not answer (${{problem.message}}): is serve.py running?`);
    button.disabled = false;
    button.textContent = "Delete";
    return;
  }}
  const body = await response.json().catch(() => ({{}}));
  if (!response.ok) {{
    alert(body.error || response.statusText);
    button.disabled = false;
    button.textContent = "Delete";
    return;
  }}
  location.reload();
}});
</script>
</body>
</html>
"""

# Where the lists of one kind of run for every city used to be: on to the start page.
DASHBOARD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{icon}
<style>
{style}</style>
</head>
<body>
<main class="home-page">
  <a class="home" href="../index.html?choose=1">← All cities</a>
  <h1>{title}</h1>
  <div class="dash">{cards}</div>
</main>
</body>
</html>
"""

REDIRECT = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta http-equiv="refresh" content="0; url={to}">
<title>Model results</title></head>
<body><a href="{to}">Model results</a></body></html>
"""

START = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Model results</title>
{icon}
<style>
{style}</style>
</head>
<body>
<main class="home-page">
  <h1>Model results</h1>
  <p class="note">Which city?</p>
  <div class="runs">{cards}</div>
</main>
</body>
</html>
"""
