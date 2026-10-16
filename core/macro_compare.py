"""The Compare page of a city's road runs (macrosimulations): pick one as the baseline, another as
the alternative, and see what changed - the headline numbers side by side, where the traffic
moved on a map, and the streets that changed most.

    output/macro/compare_<city>.html            the page
    output/macro/compare_<city>_network.js      the main roads' lines, shared by every run
    output/macro/<run>/exports/compare_data.js  each run's numbers and flows

A road network holds tens of thousands of links, so the runs are not written into the page as the
public-transport compare page does: each run's flows are a file of their own, and the page loads
the two it compares - with <script>, so it works opened as a file too. The files are written as
the city's pages are built (viewer.build_city), once per run: again only when its run is newer.

Any two runs can be compared. When they model different days or hours the page says so: the
difference is then not their parameters' alone.
"""
import html
import json
import os
from contextlib import closing

import numpy as np

from . import summary
from .paths import MACRO_OUTPUT
from .viewer import ICON, STYLE

LEAFLET = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4"
# The roads drawn on the map: the network through traffic uses. Residential streets and service
# roads are in the numbers, not on the map - they would make the page heavy and the map unreadable.
DRAWN = ["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
         "secondary", "secondary_link", "tertiary", "tertiary_link"]
DATA = "compare_data.js"
# What the files hold changes now and then: a file of another version is written again.
VERSION = 3
SIMPLIFY_M = 6
STREETS = 400                   # the streets listed, the biggest change first


def page_path(city):
    return os.path.join(MACRO_OUTPUT, f"compare_{city}.html")


def network_path(city):
    return os.path.join(MACRO_OUTPUT, f"compare_{city}_network.js")


def _newer(path, *than):
    """`path` exists, is of this VERSION and is newer than every file of `than` that exists."""
    if not os.path.isfile(path):
        return False
    with open(path, encoding="utf-8") as f:
        if f'"v":{VERSION}' not in f.read(300):
            return False
    mine = os.path.getmtime(path)
    return all(mine >= os.path.getmtime(t) for t in than if os.path.isfile(t))


def _read_links(run):
    import geopandas as gpd
    path = os.path.join(run, "exports", "link_volumes.gpkg")
    if not os.path.isfile(path):
        return None
    return gpd.read_file(path)


def _with_said(edit):
    """A demand edit with what it is, in words (core/demand_edits.py); any other as it is."""
    from .demand_edits import KINDS, said
    return dict(edit, said=said(edit)) if edit.get("kind") in KINDS else edit


def _new_roads(links, edits):
    ids = {int(i) for e in edits if e.get("kind") == "road" for i in e.get("links") or []}
    return {int(r.link_id): [str(r.name or "new road"), str(r.link_type),
                             [[round(y, 5), round(x, 5)] for x, y in r.geometry.coords]]
            for r in links[links["link_id"].isin(ids)].itertuples()}


def run_data(run, label):
    """Write the run's compare_data.js unless it is current; its path, or None for a run without
    the exports it needs."""
    out = os.path.join(run, "exports", DATA)
    info = summary.read(run)
    sources = [os.path.join(run, "summary.json"), os.path.join(run, "exports", "link_volumes.gpkg")]
    if info is None:
        return None
    if _newer(out, *sources):
        return out
    links = _read_links(run)
    if links is None:
        return None
    for col in ("car_ab", "car_ba", "Congested_Time_AB", "Congested_Time_BA", "travel_time_ab",
                "travel_time_ba", "voc", "distance"):
        links[col] = links[col].fillna(0.0)
    flow = links["car_ab"] + links["car_ba"]
    km = links["distance"] / 1000
    busy = float((links["car_ab"] * links["Congested_Time_AB"]
                  + links["car_ba"] * links["Congested_Time_BA"]).sum() / 60)
    free = float((links["car_ab"] * links["travel_time_ab"]
                  + links["car_ba"] * links["travel_time_ba"]).sum() / 60)
    # The exports leave the centroid connectors out; the run's own vehicle-hours count them
    # (core/assignment.py vehicle_hours). A connector does not congest: its hours are the same
    # loaded or empty, so they go on both - the two pages then agree, and the delay is unchanged.
    connectors = float(info.get("totals", {}).get("veh_hours", busy)) - busy
    if connectors > 0:
        busy, free = busy + connectors, free + connectors
    # Vehicle-hours lost on each link: what congestion costs there, the target a widening buys
    # back (the highest V/C is often a small street where it buys nothing).
    links["delay_h"] = ((links["car_ab"] * (links["Congested_Time_AB"] - links["travel_time_ab"])
                         + links["car_ba"] * (links["Congested_Time_BA"]
                                              - links["travel_time_ba"])) / 60).clip(lower=0)
    drawn = links[links["link_type"].isin(DRAWN)]
    named = links.assign(veh_km=flow * km, street=links["name"].fillna("").astype(str).str.strip())
    named = named[named["street"] != ""]
    streets = named.groupby("street").agg(veh_km=("veh_km", "sum"), km=("distance", "sum"),
                                          voc=("voc", "max"), delay_h=("delay_h", "sum"))
    times = _trip_times(run)
    run_info = info.get("run") or {}
    data = {
        "v": VERSION, "id": os.path.basename(run), "label": label,
        "modelled": info.get("modelled", ""),
        # A scenario: the run it is made from, and its edits to the network.
        "base": run_info.get("base"), "edits": [_with_said(e) for e in run_info.get("edits") or []],
        "description": run_info.get("description", ""),
        "changes": {k: v for k, v in (run_info.get("changes") or {}).items()},
        "loaded": info.get("loaded") or {}, "finished": info.get("finished", ""),
        "totals": {
            "trips": float(info.get("totals", {}).get("trips", 0)),
            "veh_km": float((flow * km).sum()), "veh_hours": busy, "free_hours": free,
            "congestion": 100 * (busy / free - 1) if free else 0.0,
            "delay_min": 60 * (busy - free) / max(float(info.get("totals", {}).get("trips", 1)), 1),
            "km_over": float(km[links["voc"] >= 1].sum()),
            **times},
        "groups": info.get("trip_groups") or {},
        # link: [cars A->B, cars B->A, V/C, vehicle-hours lost] - the main roads, as drawn
        "flows": {int(r.link_id): [round(float(r.car_ab), 1), round(float(r.car_ba), 1),
                                   round(float(r.voc), 3), round(float(r.delay_h), 2)]
                  for r in drawn.itertuples()},
        "streets": {name: [round(float(r.veh_km), 1), round(float(r.km) / 1000, 2),
                           round(float(r.voc), 3), round(float(r.delay_h), 1)]
                    for name, r in streets.iterrows()},
        # A scenario's new roads: in no other run's network, so their lines come with it -
        # link: [name, class, [[lat, lon], ...]], as the network's.
        "roads": _new_roads(links, run_info.get("edits") or []),
    }
    # What the run changed: its value and the settings', for the "what differs" lines - of a value
    # per key (a speed per road class, a size per hour), only the keys it changed.
    params = os.path.join(run, "exports", "parameters.csv")
    if os.path.isfile(params) and data["changes"]:
        import ast
        import csv
        with open(params, encoding="utf-8", newline="") as f:
            now = {r["name"]: r["value"] for r in csv.DictReader(f)}
        lines = {}
        for name, was in data["changes"].items():
            try:
                value = ast.literal_eval(now.get(name, ""))
            except (ValueError, SyntaxError):
                value = now.get(name, "?")
            if isinstance(value, dict) and isinstance(was, dict):
                for key in value:
                    if value[key] != was.get(key):
                        lines[f'{name}["{key}"]'] = [str(value[key]), str(was.get(key))]
            else:
                lines[name] = [str(value), str(was)]
        data["changes"] = lines
    with open(out, "w", encoding="utf-8") as f:
        f.write("(window.MACRO_RUNS = window.MACRO_RUNS || {})[" + json.dumps(data["id"])
                + "] = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")
    return out


def _trip_times(run):
    """Average trip within the city, minutes, on empty streets and on the loaded network."""
    from .stats import _read_od
    od = _read_od(run)
    if not od:
        return {}
    trips = np.array(od["trips"])
    out = {}
    for key, col in (("free_min", "minutes"), ("loaded_min", "congested_minutes")):
        if col in od:
            values = np.array(od[col])
            ok = np.isfinite(values)
            out[key] = float((trips[ok] * values[ok]).sum() / max(trips[ok].sum(), 1e-9))
    return out


def network_data(city, runs):
    """The main roads' lines for the city's runs: every link any of them loaded, written once and
    again only when a run is newer."""
    out = network_path(city)
    sources = [os.path.join(r, "exports", "link_volumes.gpkg") for r in runs]
    if _newer(out, *sources):
        return out
    lines = {}
    for run in sorted(runs, key=lambda r: -os.path.getmtime(os.path.join(r, "exports",
                                                                          "link_volumes.gpkg"))):
        links = _read_links(run)
        if links is None:
            continue
        ends = _link_ends(run)
        links = links[links["link_type"].isin(DRAWN) & ~links["link_id"].isin(list(lines))]
        if links.empty:
            continue
        metric = links.to_crs(links.estimate_utm_crs())
        simple = metric.simplify(SIMPLIFY_M).to_crs("EPSG:4326")
        for r, geom in zip(links.itertuples(), simple):
            parts = getattr(geom, "geoms", [geom])
            coords = [[round(y, 5), round(x, 5)] for part in parts for x, y in part.coords]
            a, b = ends.get(int(r.link_id), (0, 0))
            lines[int(r.link_id)] = [str(r.name) if isinstance(r.name, str) else "",
                                     r.link_type, coords, a, b]
    with open(out, "w", encoding="utf-8") as f:
        f.write(f'/*"v":{VERSION}*/ window.MACRO_NETWORK = '
                + json.dumps(lines, ensure_ascii=False, separators=(",", ":")) + ";\n")
    return out


def _link_ends(run):
    """{link: (A node, B node)} from the run's own network - for growing a selection along a
    street on the Scenarios page."""
    import sqlite3
    path = os.path.join(run, "aequilibrae", "road_model", "project_database.sqlite")
    if not os.path.isfile(path):
        return {}
    with closing(sqlite3.connect(path)) as db:
        return {int(i): (int(a), int(b)) for i, a, b in
                db.execute("SELECT link_id, a_node, b_node FROM links")}


def build(city, label, runs, names):
    """The city's compare page for `runs` (its road runs' output folders), each named by
    `names[run]`; returns the page's path, or None with fewer than two runs that can be."""
    usable = [r for r in runs if run_data(r, names[r])]
    if usable:
        network_data(city, usable)
    if len(usable) < 2:
        return None
    manifest = []
    for r in usable:
        base = ((summary.read(r) or {}).get("run") or {}).get("base")
        manifest.append({"id": os.path.basename(r), "label": names[r],
                         "data": f"{os.path.basename(r)}/exports/{DATA}",
                         "baseline": os.path.basename(r) == city,
                         "base": (city if base == "baseline" else f"{city}-{base}") if base
                         else None})
    page = (PAGE.replace("{style}", STYLE).replace("{icon}", ICON).replace("{leaflet}", LEAFLET)
            .replace("{title}", html.escape(label)).replace("{city}", city)
            .replace("{network}", os.path.basename(network_path(city)))
            .replace("{runs}", json.dumps(manifest, ensure_ascii=False).replace("</", "<\\/")))
    with open(page_path(city), "w", encoding="utf-8") as f:
        f.write(page)
    return page_path(city)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} road runs compared</title>
<link rel="stylesheet" href="{leaflet}/leaflet.min.css">
<script src="{leaflet}/leaflet.min.js"></script>
{icon}
<style>
{style}
  body { display:block; }
  .compare-page { max-width:1400px; padding:28px 32px 60px; }
  .pick { display:flex; gap:14px; align-items:flex-end; flex-wrap:wrap; margin:6px 0 18px; }
  .pick label { display:flex; flex-direction:column; font-size:12px; color:var(--soft); gap:4px; }
  .pick select { font:inherit; padding:6px 9px; border:1px solid var(--line); border-radius:6px;
      background:var(--panel); min-width:300px; }
  .pick button { font:inherit; padding:6px 12px; border:1px solid var(--line); border-radius:6px;
      background:var(--panel); cursor:pointer; }
  .top { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.5fr); gap:18px;
      align-items:start; }
  #map { height:600px; border:1px solid var(--line); border-radius:8px; }
  .about { font-size:13px; margin:0 0 12px; }
  .about b { display:block; }
  .about ul { margin:4px 0 0; padding-left:18px; color:var(--soft); }
  table.compare td.n.up { color:#b5470f; }
  table.compare td.n.down { color:#1858c4; }
  table.compare tr.part td { font-weight:650; padding-top:12px; border-bottom:1px solid var(--line); }
  .scroll { max-height:560px; }
  p.warn { font-size:13px; color:#c62828; max-width:560px; }
  .legend { display:flex; gap:14px; flex-wrap:wrap; font-size:12px; color:var(--soft); margin:6px 0 0; }
  .legend i { display:inline-block; width:16px; height:4px; margin-right:5px; vertical-align:middle; }
  .mapview { display:inline-flex; margin:0 0 8px; }
  .mapview button { font:inherit; font-size:13px; padding:4px 12px; border:1px solid var(--line);
      background:var(--panel); cursor:pointer; }
  .mapview button:first-child { border-radius:6px 0 0 6px; }
  .mapview button:last-child { border-radius:0 6px 6px 0; border-left:0; }
  .mapview button.on { background:var(--pick); color:var(--accent); font-weight:600; }
</style>
</head>
<body>
<script>if (location.protocol.startsWith("http")) document.documentElement.classList.add("served");</script>
<main class="compare-page">
  <a class="home" href="../{city}/macro.html">← Macrosimulation</a>
  <h1>Compare road runs – {title}</h1>
  <p class="note">Pick the run to compare against (the baseline) and the one to compare (the
  alternative): what each changed, the headline numbers side by side, where the traffic moved on
  the main roads, and the streets that changed most. Two runs of the same day and hour differ by
  their parameters and files alone; otherwise the page says so.</p>
  <div class="pick">
    <label>Baseline <select id="a"></select></label>
    <button id="swap" title="swap">⇄</button>
    <label>Alternative <select id="b"></select></label>
  </div>
  <div id="out"><p class="note">Loading ...</p></div>
</main>
<script>
const RUNS = {runs};
// Volume: more vehicles orange, fewer blue - neither better nor worse. Congestion: worse red,
// eased green - so the two views are never read for each other.
const GAIN = "#eb6834", LOSS = "#2a78d6", MINOR = "#c3c8ce";
const WORSE = "#d7301f", EASED = "#1a9850";
// A scenario's edits, drawn over the change: closed, widened (or narrowed), a new speed.
const EDIT_STYLE = {close: {color: "#111111", weight: 5, said: "closed"},
                    road: {color: "#0b7285", weight: 6, said: "new road"},
                    capacity: {color: "#d4a017", weight: 9, opacity: 0.45, said: "capacity changed"},
                    speed: {color: "#8e44ad", weight: 9, opacity: 0.45, said: "speed changed"}};
let view = "volume";
let shownPair = "";              // the runs shown: a new pair opens on its scenario's own view
const $ = id => document.getElementById(id);
const esc = t => String(t).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;",
                                                     '"': "&quot;", "'": "&#39;"}[c]));
const num = (x, d) => Number(x).toLocaleString(undefined,
  {minimumFractionDigits: d, maximumFractionDigits: d});
let map;

const loaded = {};
function load(src) {
  // A run's data, or the network, as a script: it works opened as a file too.
  return loaded[src] || (loaded[src] = new Promise((ok, fail) => {
    const s = document.createElement("script");
    s.src = src; s.onload = ok; s.onerror = () => fail(new Error(`cannot read ${src}`));
    document.head.appendChild(s);
  }));
}

function editSaid(e) {
  if (["trips", "develop", "growth"].includes(e.kind)) return e.said || e.kind;
  if (e.kind === "road")
    return `new road: ${e.label || "unnamed"} (${e.link_type}, ${e.lanes} lane${e.lanes > 1 ? "s" : ""} `
      + `${e.oneway ? "one way" : "each way"}, ${e.kmh} km/h)`;
  const what = e.kind === "close" ? "closed" : e.kind === "capacity" ? `capacity × ${e.factor}`
    : `speed ${e.kmh} km/h`;
  return `${what}: ${e.label || "links"} (${e.links.length} link${e.links.length !== 1 ? "s" : ""})`;
}

function about(run) {
  const changes = Object.entries(run.changes || {});
  const files = Object.entries(run.loaded || {});
  if (run.base) {
    return `<div class="about"><b>${esc(run.label)}</b><span class="note">A scenario of
      ${esc(run.base)}: its parameters and files, with these edits to the network. Modelled:
      ${esc(run.modelled || "the morning peak")}. ${run.description ? esc(run.description) : ""}</span>
      <ul>${run.edits.map(e => `<li>${esc(editSaid(e))}</li>`).join("")}</ul></div>`;
  }
  return `<div class="about"><b>${esc(run.label)}</b><span class="note">Modelled: ${esc(run.modelled || "the morning peak")}.
    ${run.description ? esc(run.description) : ""}</span><ul>${
    changes.map(([k, v]) => `<li>${esc(k)} = ${esc(v[0])} <span class="note">(settings: ${esc(v[1])})</span></li>`).join("")}${
    files.map(([k, v]) => `<li>${k === "zoning" ? "zoning" : "O-D matrix"} loaded: ${esc(v)}</li>`).join("")}${
    !changes.length && !files.length ? "<li>the city's settings as they are</li>" : ""}</ul></div>`;
}

const ROWS = [["vehicle trips", "trips", 0], ["vehicle-km on the network", "veh_km", 0],
              ["vehicle-hours", "veh_hours", 0], ["the same trips on empty streets, vehicle-hours", "free_hours", 0],
              ["congestion adds, % of travel time", "congestion", 1], ["delay per trip, min", "delay_min", 2],
              ["km over capacity", "km_over", 1], ["average trip within the city, empty streets, min", "free_min", 1],
              ["average trip within the city, loaded network, min", "loaded_min", 1]];
const GROUPS = [["within the city", "within"], ["from the city to outside", "outbound"],
                ["from outside into the city", "inbound"], ["through the city", "through"]];

function line(label, va, vb, d) {
  if (va == null || vb == null) return "";
  const pct = Math.abs(va) < 1e-9 ? "n/a" : `${vb >= va ? "+" : ""}${num(100 * (vb - va) / va, 1)}%`;
  const cls = Math.abs(vb - va) < 1e-9 ? "" : vb > va ? "up" : "down";
  return `<tr><td>${esc(label)}</td><td class="n">${num(va, d)}</td><td class="n">${num(vb, d)}</td>
    <td class="n ${cls}">${pct}</td></tr>`;
}

async function render() {
  const ia = $("a").value, ib = $("b").value;
  history.replaceState(null, "", `?a=${RUNS[ia].id}&b=${RUNS[ib].id}`);
  if (ia === ib) { $("out").innerHTML = `<p class="note">Pick two different runs.</p>`; return; }
  $("out").innerHTML = `<p class="note">Loading ...</p>`;
  try {
    await Promise.all([load("{network}"), load(RUNS[ia].data), load(RUNS[ib].data)]);
  } catch (e) { $("out").innerHTML = `<p class="warn">${esc(e.message)}</p>`; return; }
  const a = window.MACRO_RUNS[RUNS[ia].id], b = window.MACRO_RUNS[RUNS[ib].id];
  // A closure is measured in traffic, a capacity or speed change in congestion: a new pair
  // opens on its scenario's view; a view picked by hand stays while the pair does.
  if (`${ia}-${ib}` !== shownPair) {
    shownPair = `${ia}-${ib}`;
    const edited = [b, a].find(r => r.edits && r.edits.length);
    if (edited) view = edited.edits.every(e => e.kind === "capacity" || e.kind === "speed")
      ? "voc" : "volume";
  }
  const rows = ROWS.map(([l, k, d]) => line(l, a.totals[k], b.totals[k], d)).join("");
  const hasGroups = Object.keys(a.groups).length && Object.keys(b.groups).length
    && (a.groups.outbound || a.groups.inbound || b.groups.outbound || b.groups.inbound);
  const groups = hasGroups ? `<tr class="part"><td colspan="4">Where the trips go</td></tr>`
    + GROUPS.map(([l, k]) => line(l, a.groups[k] || 0, b.groups[k] || 0, 0)).join("") : "";
  const differ = a.modelled !== b.modelled ? `<p class="warn">⚠ These two do not model the same
    day and hour: ${esc(a.modelled)} - against ${esc(b.modelled)}. The difference is not their
    parameters' alone.</p>` : "";

  // Every main-road link either run loads: the change in its flow, both ways together.
  const ids = new Set(Object.keys(a.flows).concat(Object.keys(b.flows)));
  const links = [...ids].map(id => {
    const fa = a.flows[id] || [0, 0, 0], fb = b.flows[id] || [0, 0, 0];
    const va = fa[0] + fa[1], vb = fb[0] + fb[1];
    return {id, va, vb, change: vb - va, voca: fa[2], vocb: fb[2]};
  });
  const streetNames = new Set(Object.keys(a.streets).concat(Object.keys(b.streets)));
  const streets = [...streetNames].map(n => {
    const sa = a.streets[n] || [0, 0, 0], sb = b.streets[n] || [0, 0, 0];
    return {name: n, km: Math.max(sa[1], sb[1]), va: sa[0], vb: sb[0], change: sb[0] - sa[0],
            voca: sa[2], vocb: sb[2], da: sa[3] || 0, db: sb[3] || 0};
  }).sort((x, y) => Math.abs(y.change) - Math.abs(x.change)).slice(0, """ + str(STREETS) + """);

  $("out").innerHTML = `
    <div class="top">
      <div>${about(a)}${about(b)}${differ}
        <table class="compare"><thead><tr><th></th><th>baseline</th><th>alternative</th>
          <th>change</th></tr></thead><tbody>${rows}${groups}</tbody></table></div>
      <div><div class="mapview"><button data-view="volume" class="${view === "volume" ? "on" : ""}">Volume</button
        ><button data-view="voc" class="${view === "voc" ? "on" : ""}">Congestion (V/C)</button></div>
        <div id="map"></div>
        <div class="legend" id="legend"></div></div>
    </div>
    <h2 class="section">The streets that changed most</h2>
    <p class="note">Vehicle-km on each named street, both directions, the biggest change first - the
    ${streets.length} with the largest. Click a column to sort.</p>
    <div class="scroll"><table style="width:100%"><thead><tr><th>street</th><th>km</th>
      <th>baseline veh-km</th><th>alternative veh-km</th><th>change</th><th>worst V/C, baseline</th>
      <th>worst V/C, alternative</th><th>veh-hours lost, baseline</th><th>veh-hours lost,
      alternative</th></tr></thead><tbody>${streets.map(s => `
      <tr><td>${esc(s.name)}</td><td class="n" data-v="${s.km}">${num(s.km, 1)}</td>
      <td class="n" data-v="${s.va}">${num(s.va, 0)}</td><td class="n" data-v="${s.vb}">${num(s.vb, 0)}</td>
      <td class="n" data-v="${s.change}">${s.change > 0 ? "+" : ""}${num(s.change, 0)}</td>
      <td class="n" data-v="${s.voca}">${num(s.voca, 2)}</td><td class="n" data-v="${s.vocb}">${num(s.vocb, 2)}</td>
      <td class="n" data-v="${s.da}">${num(s.da, 0)}</td><td class="n" data-v="${s.db}">${num(s.db, 0)}</td>
      </tr>`).join("")}</tbody></table></div>`;
  sortable($("out").querySelector(".scroll table"));
  $("out").querySelectorAll(".mapview button").forEach(b => b.addEventListener("click", () => {
    view = b.dataset.view; render();
  }));
  // The new roads either run has built: in neither's network, their lines come with them.
  drawMap(links, (a.edits || []).concat(b.edits || []), Object.assign({}, a.roads, b.roads));
}

function drawMap(links, edits, roads) {
  if (map) map.remove();
  map = L.map("map", {zoomSnap: 0.25, preferCanvas: true});
  const esri = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/";
  L.tileLayer(esri + "World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", {maxZoom: 16,
    attribution: "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors"})
    .addTo(map);
  L.tileLayer(esri + "World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}", {maxZoom: 16})
    .addTo(map);
  const net = Object.assign({}, window.MACRO_NETWORK, roads || {});
  // Volume: the change in vehicles. Congestion: the change in V/C - the honest view of a
  // widening, which draws more cars onto a road that is nonetheless less congested.
  const voc = view === "voc";
  const delta = l => (voc ? l.vocb - l.voca : l.change);
  const biggest = Math.max(voc ? 0.05 : 1, ...links.map(l => Math.abs(delta(l))));
  // A change smaller than this is drawn grey: a twentieth of the largest, at least 10 vehicles
  // (or 0.02 of V/C).
  const minor = voc ? Math.max(0.02, biggest / 20) : Math.max(10, Math.round(biggest / 20));
  $("legend").innerHTML = (voc
    ? `<span><i style="background:${WORSE}"></i>more congested</span><span><i style="background:${EASED}"></i>less congested</span>
       <span><i style="background:${MINOR}"></i>V/C changed by less than ${num(minor, 2)}</span>`
    : `<span><i style="background:${GAIN}"></i>more vehicles</span><span><i style="background:${LOSS}"></i>fewer vehicles</span>
       <span><i style="background:${MINOR}"></i>changed by less than ${num(minor, 0)} vehicles</span>`)
    + `<span>width shows the change; both directions together; motorways to tertiary streets</span>`
    + (edits.length ? Object.entries(EDIT_STYLE).filter(([k]) => edits.some(e => e.kind === k))
        .map(([, st]) => `<span><i style="background:${st.color}"></i>${st.said}</span>`).join("") : "");
  // Capacity and speed edits first, a halo under the change, which reads on top; closures last,
  // over it - a closed road's change is all its traffic gone.
  const drawEdits = closures => { for (const e of edits) {
    if ((e.kind === "close" || e.kind === "road") !== closures) continue;
    const st = EDIT_STYLE[e.kind];
    for (const id of e.links || []) {
      const g = net[id];
      if (!g) continue;
      L.polyline(g[2], {color: st.color, weight: st.weight, opacity: st.opacity || 0.95,
                        dashArray: st.dashArray || null})
        .bindTooltip(`<b>${esc(g[0] || "unnamed")}</b><br>${esc(editSaid(e))}`, {sticky: true}).addTo(map);
    }
  } };
  drawEdits(false);
  const bounds = [];
  links.sort((x, y) => Math.abs(delta(x)) - Math.abs(delta(y)));     // the biggest drawn last
  for (const l of links) {
    const g = net[l.id];
    if (!g) continue;
    const d = delta(l), small = Math.abs(d) < minor;
    if (!small) bounds.push(...g[2]);
    L.polyline(g[2], {color: small ? MINOR : d > 0 ? (voc ? WORSE : GAIN) : (voc ? EASED : LOSS),
                      opacity: small ? 0.6 : 0.9,
      weight: small ? 1.2 : 1.5 + 8 * Math.abs(d) / biggest})
      .bindTooltip(`<b>${esc(g[0] || "unnamed")}</b> · ${esc(g[1])}<br>baseline ${num(l.va, 0)} ·
        alternative ${num(l.vb, 0)} vehicles<br>change <b>${l.change > 0 ? "+" : ""}${num(l.change, 0)}</b>
        · V/C ${num(l.voca, 2)} → ${num(l.vocb, 2)}`, {sticky: true})
      .addTo(map);
  }
  drawEdits(true);
  if (bounds.length) map.fitBounds(bounds);
  else map.fitBounds(Object.values(net).map(g => g[2][0]));
}

function sortable(table) {
  table.querySelectorAll("th").forEach((th, col) => th.addEventListener("click", () => {
    const up = !th.classList.contains("up");
    table.querySelectorAll("th").forEach(h => h.classList.remove("up", "down"));
    th.classList.add(up ? "up" : "down");
    const value = tr => {
      const td = tr.children[col];
      return td.dataset.v !== undefined ? parseFloat(td.dataset.v) : td.textContent;
    };
    const rows = [...table.tBodies[0].rows].sort((x, y) => {
      const p = value(x), q = value(y);
      const order = typeof p === "number" ? p - q : String(p).localeCompare(String(q));
      return up ? order : -order;
    });
    rows.forEach(r => table.tBodies[0].appendChild(r));
  }));
}

const options = RUNS.map((r, i) => `<option value="${i}">${esc(r.label)}</option>`).join("");
$("a").innerHTML = $("b").innerHTML = options;
const params = new URLSearchParams(location.search);
const find = id => RUNS.findIndex(r => r.id === id);
$("b").value = find(params.get("b")) >= 0 ? find(params.get("b")) : Math.max(0, RUNS.findIndex(r => !r.baseline));
// The baseline asked for, or the alternative's base when it is a scenario, or the city's baseline.
const ofB = RUNS[$("b").value].base;
$("a").value = find(params.get("a")) >= 0 ? find(params.get("a"))
  : ofB && find(ofB) >= 0 ? find(ofB) : Math.max(0, RUNS.findIndex(r => r.baseline));
$("a").addEventListener("change", render);
$("b").addEventListener("change", render);
$("swap").addEventListener("click", () => {
  [$("a").value, $("b").value] = [$("b").value, $("a").value];
  render();
});
render();
</script>
</body>
</html>
"""
