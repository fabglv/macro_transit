"""The Compare page of a city's simulations: pick one as the baseline, another as the
alternative, and see what changed - the headline numbers side by side, a map of where passengers
moved, and every segment's passengers in both.

Any two simulations of a city can be compared, two designs as well as a design and the baseline.
On the same options they carry the same demand - every simulation reads the baseline's - so the
difference between them is the service alone; on different days, hours or demand the page says
so. Every run's numbers, segments and their lines (exports/segments.geojson) are
written into the page, and the browser does the comparison for the pair chosen - so the page
works opened as a file too, without the server. Only the standard library, like the rest of
the results pages.
"""
import csv
import html
import io
import json
import os
import re
import zipfile

from . import summary
from .transit_stats import COMPARISON
from .viewer import ICON, STYLE

LEAFLET = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4"


def build(root, city, runs, names):
    """Write compare_<city>.html into `root` for `runs` (output folders of one city), each named
    by `names[run]`; returns its file name."""
    data = {"city": city.title(), "runs": [], "geometry": {}, "colors": {},
            "rows": [[label.strip(), key, _decimals(fmt)] for label, key, _, fmt in COMPARISON]}
    for run in runs:
        info = summary.read(run) or {}
        if "totals" not in info:
            continue
        exports = os.path.join(run, "exports")
        segments = {}
        for r in _csv(os.path.join(exports, "segments.csv")):
            segments[r["segment"]] = [r["route"], r["from_name"], r["to_name"],
                                      round(float(r["pt_volume"] or 0), 1)]
        stops = [[r["name"], float(r["lat"]), float(r["lon"])]
                 for r in _csv(os.path.join(exports, "stops.csv")) if r.get("lat")]
        design = info.get("design") or {}
        data["runs"].append({"id": os.path.basename(run), "label": names[run],
                             "scenario": design.get("name", "baseline") != "baseline",
                             "description": design.get("description", ""),
                             "changes": design.get("changes") or [],
                             "finished": info.get("finished", ""), "totals": info["totals"],
                             "simulated": info.get("simulated") or {},
                             "operations": info.get("operations") or {},
                             "segments": segments, "stops": stops})
        _geometry(os.path.join(exports, "segments.geojson"), data["geometry"])
        data["colors"].update(_colors(os.path.join(exports, "gtfs_feed.zip")))
    data["runs"].sort(key=lambda r: (r["scenario"], r["label"]))     # the baseline first
    name = f"compare_{city}.html"
    page = (PAGE.replace("{style}", STYLE).replace("{icon}", ICON).replace("{leaflet}", LEAFLET)
            .replace("{title}", html.escape(city.title())).replace("{city}", city)
            # Inside <script>, "</" would end it early.
            .replace("{data}", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")))
    with open(os.path.join(root, name), "w", encoding="utf-8") as f:
        f.write(page)
    return name


def _csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _decimals(fmt):
    """'{:,.0f}' -> 0, '{:.3f}' -> 3."""
    found = re.search(r"\.(\d+)f", fmt)
    return int(found.group(1)) if found else 0


def _geometry(path, into):
    """Segment key -> its line as [[lat, lon], ...], for segments not already known."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for feature in json.load(f)["features"]:
            key, geom = feature["properties"]["segment"], feature["geometry"]
            if key in into or not geom or geom["type"] != "LineString":
                continue
            into[key] = [[round(lat, 6), round(lon, 6)] for lon, lat in geom["coordinates"]]


def _colors(path):
    """Route short name -> '#rrggbb', from the feed's own route_color."""
    if not os.path.exists(path):
        return {}
    with zipfile.ZipFile(path) as z, z.open("routes.txt") as f:
        rows = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
        return {r["route_short_name"]: f"#{r['route_color']}" for r in rows
                if r.get("route_color")}


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} simulations compared</title>
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
      background:var(--panel); min-width:260px; }
  .pick button { font:inherit; padding:6px 12px; border:1px solid var(--line); border-radius:6px;
      background:var(--panel); cursor:pointer; }
  .top { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.6fr); gap:18px;
      align-items:start; }
  #map { height:560px; border:1px solid var(--line); border-radius:8px; }
  .about { font-size:13px; margin:0 0 12px; }
  .about b { display:block; }
  .about ul { margin:4px 0 0; padding-left:18px; color:var(--soft); }
  table.compare td.n.up { color:#b5470f; }
  table.compare td.n.down { color:#1858c4; }
  .scroll { max-height:520px; }
  table.compare tr.part td { font-weight:650; padding-top:12px; border-bottom:1px solid var(--line); }
  p.trade { font-size:13px; max-width:520px; }
  p.warn { font-size:13px; color:#c62828; max-width:520px; }
</style>
</head>
<body>
<script>if (location.protocol.startsWith("http")) document.documentElement.classList.add("served");</script>
<main class="compare-page">
  <a class="home" href="../../{city}/simulations.html">← Simulations</a>
  <h1>Compare simulations – {title}</h1>
  <p class="note">Pick the simulation to compare against (the baseline) and the one to compare
  (the alternative). On the same options both carry the same travellers - every simulation reads the baseline's
  demand - so what differs is the design. The model has no crowding, so more vehicles help only by cutting the
  wait; average journey times are over the trips that reach the network, so when the two reach
  different numbers of trips they describe a different mix as much as a faster network.</p>
  <div class="pick">
    <label>Baseline <select id="a"></select></label>
    <button id="swap" title="swap">⇄</button>
    <label>Alternative <select id="b"></select></label>
  </div>
  <div id="out"></div>
</main>
<script>
const D = {data};
const GAIN = "#eb6834", LOSS = "#2a78d6", MINOR = "#a8adb3", MIN_CHANGE = 10;
const $ = id => document.getElementById(id);
const esc = t => String(t).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;",
                                                     '"': "&quot;", "'": "&#39;"}[c]));
const num = (x, d) => Number(x).toLocaleString(undefined,
  {minimumFractionDigits: d, maximumFractionDigits: d});
let map, layer;

function about(run) {
  return `<div class="about"><b>${esc(run.label)}</b>${run.simulated.said
    ? `<span class="note">Simulated: ${esc(run.simulated.said)}.</span> ` : ""}${run.description
    ? `<span class="note">${esc(run.description)}</span>` : ""}${run.changes.length
    ? `<ul>${run.changes.map(c => `<li>${esc(c)}</li>`).join("")}</ul>`
    : `<ul><li>the baseline network, no changes</li></ul>`}</div>`;
}

// What a design takes to run on the day simulated: [label, value, decimals] - those both have.
function costRows(a, b) {
  const oa = a.operations, ob = b.operations;
  if (!oa.vehicles || !ob.vehicles) return [];
  const modes = [...new Set(Object.keys(oa.vehicles).concat(Object.keys(ob.vehicles)))].sort();
  return modes.map(m => [`vehicles needed, ${m}`, oa.vehicles[m] || 0, ob.vehicles[m] || 0, 0])
    .concat([["vehicle-km, the day", oa.vehicle_km, ob.vehicle_km, 0],
             ["vehicle-hours, the day", oa.vehicle_hours, ob.vehicle_hours, 0]]);
}

function costLine(a, b) {
  // The trade in one line: what the alternative costs more (or less), and what passengers gain.
  const oa = a.operations, ob = b.operations;
  if (!oa.vehicles || !ob.vehicles) return "";
  const dh = ob.vehicle_hours - oa.vehicle_hours, dp = a.totals.passenger_hours - b.totals.passenger_hours;
  const veh = m => Object.values(m).reduce((x, y) => x + y, 0);
  const dv = veh(ob.vehicles) - veh(oa.vehicles);
  const more = (x, unit) => `${num(Math.abs(x), 0)} ${unit} ${x >= 0 ? "more" : "fewer"}`;
  let line = `The alternative runs ${more(dv, "vehicles")} and ${more(dh, "vehicle-hours")} a day, and
    its passengers spend ${num(Math.abs(dp), 0)} hours ${dp >= 0 ? "less" : "more"} travelling in the
    modelled period`;
  if (dh > 0 && dp > 0) line += ` - ${num(dp / dh, 2)} passenger-hours saved in the period for every
    extra vehicle-hour of the day`;
  return `<p class="trade">${line}.</p>`;
}

function render() {
  const a = D.runs[$("a").value], b = D.runs[$("b").value];
  history.replaceState(null, "", `?a=${a.id}&b=${b.id}`);
  if (a === b) {
    $("out").innerHTML = `<p class="note">Pick two different runs.</p>`;
    return;
  }
  const rows = D.rows.map(([label, key, d]) => {
    const va = a.totals[key], vb = b.totals[key];
    const shownZero = Number(va.toFixed(d)) === 0;
    const pct = shownZero ? "n/a" : `${vb >= va ? "+" : ""}${num(100 * (vb - va) / va, 1)}%`;
    const cls = Math.abs(vb - va) < 1e-9 ? "" : vb > va ? "up" : "down";
    return `<tr><td>${esc(label)}</td><td class="n">${num(va, d)}</td><td class="n">${
      num(vb, d)}</td><td class="n ${cls}">${pct}</td></tr>`;
  }).join("") + (costRows(a, b).length ? `<tr class="part"><td colspan="4">What it takes to run</td></tr>`
    + costRows(a, b).map(([label, va, vb, d]) => {
      const pct = va ? `${vb >= va ? "+" : ""}${num(100 * (vb - va) / va, 1)}%` : "n/a";
      const cls = Math.abs(vb - va) < 1e-9 ? "" : vb > va ? "up" : "down";
      return `<tr><td>${esc(label)}</td><td class="n">${num(va, d)}</td><td class="n">${
        num(vb, d)}</td><td class="n ${cls}">${pct}</td></tr>`;
    }).join("") : "");
  // Two simulations on different days, hours or demand compare those too, not only the designs.
  const sa = a.simulated.said, sb = b.simulated.said;
  const differ = sa && sb && sa !== sb ? `<p class="warn">⚠ These two did not simulate the same
    thing: ${esc(sa)} - against ${esc(sb)}. The difference is not the design's alone.</p>` : "";

  const keys = new Set(Object.keys(a.segments).concat(Object.keys(b.segments)));
  const segs = [...keys].map(k => {
    const sa = a.segments[k], sb = b.segments[k], info = sb || sa;
    const va = sa ? sa[3] : 0, vb = sb ? sb[3] : 0;
    return {key: k, route: info[0], from: info[1], to: info[2], va, vb, change: vb - va,
            onlyB: !sa, onlyA: !sb};
  }).sort((x, y) => Math.abs(y.change) - Math.abs(x.change));

  $("out").innerHTML = `
    <div class="top">
      <div>${about(a)}${about(b)}${differ}
        <table class="compare"><thead><tr><th></th><th>baseline</th><th>alternative</th>
          <th>change</th></tr></thead><tbody>${rows}</tbody></table>${costLine(a, b)}</div>
      <div><div id="map"></div>
        <div class="legend"><span><i style="background:${GAIN}"></i>more passengers</span>
          <span><i style="background:${LOSS}"></i>fewer passengers</span>
          <span><i style="background:${MINOR}"></i>moved by ${MIN_CHANGE} or less</span>
          <span>a line only in one run is drawn in its own colour; width shows the change</span>
        </div></div>
    </div>
    <h2 class="section">Every segment</h2>
    <p class="note">Passengers in the modelled period, the biggest change first. A segment of a
    line that runs in one of the two only has none in the other. Click a column to sort.</p>
    <div class="scroll"><table style="width:100%"><thead><tr><th>route</th><th>ride</th>
      <th>baseline</th><th>alternative</th><th>change</th></tr></thead><tbody>${segs.map(s => `
      <tr><td>${esc(s.route)}</td><td>${esc(s.from)} → ${esc(s.to)}</td>
      <td class="n" data-v="${s.va}">${num(s.va, 0)}</td>
      <td class="n" data-v="${s.vb}">${num(s.vb, 0)}</td>
      <td class="n" data-v="${s.change}">${s.change > 0 ? "+" : ""}${num(s.change, 0)}</td>
      </tr>`).join("")}</tbody></table></div>`;
  sortable($("out").querySelector(".scroll table"));
  drawMap(b, segs);
}

function drawMap(b, segs) {
  if (map) map.remove();                       // the last pair's map, before the next one
  map = L.map("map", {zoomSnap: 0.25});
  const esri = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/";
  L.tileLayer(esri + "World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", {maxZoom: 16,
    attribution: "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors"})
    .addTo(map);
  L.tileLayer(esri + "World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}", {maxZoom: 16})
    .addTo(map);
  const biggest = Math.max(1, ...segs.filter(s => Math.abs(s.change) > MIN_CHANGE)
                                     .map(s => Math.abs(s.change)));
  const bounds = [];
  for (const s of segs.slice().reverse()) {                // the biggest changes drawn last
    const line = D.geometry[s.key];
    if (!line) continue;
    bounds.push(...line);
    const minor = Math.abs(s.change) <= MIN_CHANGE;
    const own = (s.onlyA || s.onlyB) && !minor;
    const color = minor ? MINOR : own ? (D.colors[s.route] || "#555") : s.change > 0 ? GAIN : LOSS;
    const tag = minor ? "minor change" : s.onlyB ? `only in the alternative`
      : s.onlyA ? `only in the baseline` : s.change > 0 ? "more passengers" : "fewer passengers";
    L.polyline(line, {color, opacity: minor ? 0.7 : 0.9,
      weight: minor ? 2 : 2 + 9 * Math.min(Math.abs(s.change) / biggest, 1)})
      .bindTooltip(`<b>${esc(s.from)} → ${esc(s.to)}</b><br>${esc(s.route)} · ${tag}<br>
        baseline ${num(s.va, 0)} · alternative ${num(s.vb, 0)}<br>change <b>${
        s.change > 0 ? "+" : ""}${num(s.change, 0)}</b>`, {sticky: true})
      .addTo(map);
  }
  for (const [name, lat, lon] of b.stops)
    L.circleMarker([lat, lon], {radius: 3, color: "#fff", weight: 1, fillColor: "#333",
                                fillOpacity: 1}).bindTooltip(esc(name)).addTo(map);
  if (bounds.length) map.fitBounds(bounds);
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

const options = D.runs.map((r, i) => `<option value="${i}">${esc(r.label)}</option>`).join("");
$("a").innerHTML = $("b").innerHTML = options;
const params = new URLSearchParams(location.search);
const find = id => D.runs.findIndex(r => r.id === id);
$("a").value = Math.max(0, find(params.get("a")) >= 0 ? find(params.get("a"))
                           : D.runs.findIndex(r => !r.scenario));
$("b").value = find(params.get("b")) >= 0 ? find(params.get("b"))
             : Math.max(0, D.runs.findIndex(r => r.scenario));
$("a").addEventListener("change", render);
$("b").addEventListener("change", render);
$("swap").addEventListener("click", () => {
  [$("a").value, $("b").value] = [$("b").value, $("a").value];
  render();
});
if (D.runs.length < 2)
  $("out").innerHTML = `<p class="note">There is one simulation so far: simulate a design first.</p>`;
else render();
</script>
</body>
</html>
"""
