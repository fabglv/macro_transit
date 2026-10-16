"""The Scenarios page, served by core/server.py at /scenario/<city>: a scenario made from a
computed road run - its base - with edits to the network, run, then compared with its base.

    1. choose the base: any computed run of the city (not a scenario)
    2. select roads on its map - coloured by its congestion - by clicking them (a road's stretch
       to the next main road; shift+click one link), or from the
       corridors it suggests: the streets losing most vehicle-hours, carrying most traffic or
       most over capacity, a stretch grown from their worst link along the street
    3. say what happens to them - closed, capacity × a factor, a new speed - as an edit; as many
       edits as needed. A scenario either closes roads or changes their capacity or speed: a
       closure moves traffic and is shown in volumes, a capacity change makes roads more or less
       congested and is shown in V/C (core/maps.draw_scenario)
    4. run it: the base's zones and demand are taken as they are, and the assignment runs with
       the edits (core/edits.py); then compare it with its base (core/macro_compare.py)

The scenario is saved as macro_runs/<city>/<name>.json (core/runs.py): its base and its edits.
The map's roads and the base's flows are the compare page's files (macro_compare), loaded as
scripts.
"""
import html

from .viewer import ICON, STYLE

LEAFLET = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4"


def page(city):
    return (PAGE.replace("{style}", STYLE).replace("{icon}", ICON).replace("{leaflet}", LEAFLET)
            .replace("{city}", html.escape(city)).replace("{title}", html.escape(city.title())))


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} scenarios</title>
<link rel="stylesheet" href="{leaflet}/leaflet.min.css">
<script src="{leaflet}/leaflet.min.js"></script>
{icon}
<style>
{style}
  body { display:block; }
  .scen { max-width:1400px; padding:28px 32px 60px; }
  .row { display:flex; gap:14px; flex-wrap:wrap; align-items:flex-end; margin:0 0 12px; }
  .row label { display:flex; flex-direction:column; font-size:12px; color:var(--soft); gap:4px; }
  .row input, .row select, .row textarea { font:inherit; color:var(--ink); padding:6px 9px;
      border:1px solid var(--line); border-radius:6px; background:var(--panel); }
  .row select { min-width:280px; }
  .row textarea { width:640px; max-width:100%; min-height:40px; }
  .work { display:grid; grid-template-columns:minmax(0,1fr) 380px; gap:16px; align-items:start; }
  #map { height:680px; border:1px solid var(--line); border-radius:8px; }
  .side { background:var(--panel); border:1px solid var(--line); border-radius:8px;
      padding:12px 14px; max-height:680px; overflow:auto; font-size:13px; }
  .side h3 { font-size:14px; margin:14px 0 6px; }
  .side h3:first-child { margin-top:0; }
  .side .muted { color:var(--soft); }
  .side input[type=number] { font:inherit; width:70px; padding:3px 6px; border:1px solid var(--line);
      border-radius:5px; }
  .side select { font:inherit; padding:3px 6px; }
  .side label.choice { display:block; margin:4px 0; }
  h2.pick { font-size:17px; margin:18px 0 10px; }
  .kinds { display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:12px;
           max-width:1100px; }
  button.kind { position:relative; display:flex; flex-direction:column; gap:6px; text-align:left;
                font:inherit; padding:14px 16px; border:1px solid var(--line); border-radius:10px;
                background:var(--panel); color:var(--ink); cursor:pointer; }
  button.kind b { font-size:16px; }
  button.kind span { color:var(--soft); font-size:13px; }
  button.kind:hover:not(:disabled) { border-color:var(--accent);
                                     box-shadow:0 2px 8px rgba(31,111,235,.12); }
  button.kind:disabled { cursor:default; opacity:.55; }
  button.kind i { position:absolute; top:12px; right:12px; font-style:normal; font-size:11px;
                  color:var(--soft); border:1px solid var(--line); border-radius:10px;
                  padding:0 7px; }
  p.kindsaid { font-size:15px; margin:14px 0 10px; }
  .roadform { display:grid; grid-template-columns:1fr 1fr; gap:8px 10px; margin:10px 0 0; }
  .roadform label { display:flex; flex-direction:column; font-size:12px; color:var(--soft); gap:3px; }
  .roadform label.check { flex-direction:row; align-items:center; gap:6px; color:var(--ink);
                          font-size:13px; grid-column:1 / -1; }
  .roadform input, .roadform select { font:inherit; font-size:13px; padding:4px 6px;
      border:1px solid var(--line); border-radius:5px; background:var(--panel); color:var(--ink); }
  .leaflet-container.drawing { cursor:crosshair; }
  .zlabel { font:600 11px system-ui, sans-serif; color:#2f3842; text-align:center; white-space:nowrap;
            text-shadow:0 0 3px #fff, 0 0 3px #fff, 0 0 3px #fff; pointer-events:none; }
  .zchip { display:inline-block; padding:0 6px; margin:2px 3px 0 0; border-radius:9px; color:#fff;
           font-size:12px; }
  p.kindsaid a { font-size:13px; margin-left:8px; }
  button.small { font:inherit; font-size:12px; padding:3px 10px; cursor:pointer; border-radius:12px;
      border:1px solid var(--line); background:var(--panel); color:var(--accent); }
  button.small:disabled { opacity:.45; cursor:default; }
  .sugg div { padding:4px 6px; border-radius:5px; cursor:pointer; display:flex;
      justify-content:space-between; gap:8px; }
  .sugg div:hover { background:var(--pick); }
  .edit { border:1px solid var(--line); border-radius:6px; padding:6px 8px; margin:0 0 6px; }
  .edit b { display:block; }
  .edit .tools { display:flex; gap:6px; margin-top:4px; }
  .legend { display:flex; gap:12px; flex-wrap:wrap; font-size:12px; color:var(--soft); margin:6px 0 0; }
  .mapview { display:inline-flex; margin:0 0 8px; }
  .mapview button { font:inherit; font-size:13px; padding:4px 12px; border:1px solid var(--line);
                    background:var(--panel); color:var(--ink); cursor:pointer; }
  .mapview button:first-child { border-radius:6px 0 0 6px; }
  .mapview button:last-child { border-radius:0 6px 6px 0; border-left:0; }
  .mapview button.on { background:var(--pick); color:var(--accent); font-weight:600; }
  .legend i { display:inline-block; width:16px; height:4px; margin-right:5px; vertical-align:middle; }
  .actions { display:flex; gap:10px; margin:14px 0; align-items:center; flex-wrap:wrap; }
  .actions label.gap { font-size:13px; }
  .actions label.gap .muted { color:var(--soft); margin-left:4px; }
  button.btn { font:inherit; padding:8px 16px; border-radius:6px; cursor:pointer;
      border:1px solid var(--accent); background:var(--panel); color:var(--accent); }
  button.btn.primary { background:var(--accent); color:#fff; }
  button.btn:disabled { opacity:.45; cursor:default; }
  .message { font-size:13px; }
  .message.error { color:#c62828; }
  .job { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px 14px; }
  .job pre { max-height:240px; overflow:auto; border:0; padding:0; background:none; }
</style>
</head>
<body>
<main class="scen">
  <a class="home" href="/{city}/macro.html">← Macrosimulation</a>
  <h1>Scenarios – {title}</h1>
  <p class="note">A scenario is a computed run - its <b>base</b> - with edits to the network: roads
  closed, or their capacity or speed changed. Its trips are the base's, as they are: only the
  routes drivers take change, so comparing the two shows what the edits do. Running it takes the
  base's zones and demand and runs the assignment alone - a minute or a few.</p>

  <div class="row">
    <label>Base run <select id="base"></select></label>
    <label>Scenario <select id="scenario"></select></label>
  </div>

  <!-- A new scenario: its kind first - each is measured, and mapped, its own way. -->
  <div id="kinds">
    <h2 class="pick">What kind of scenario?</h2>
    <div class="kinds">
      <button class="kind" data-kind="closure"><b>Close roads</b><span>Roads taken out of the
        network. Where does their traffic go? Measured in traffic volumes.</span></button>
      <button class="kind" data-kind="capacity"><b>Change capacity or speed</b><span>Roads widened
        or narrowed, made faster or slower. How congested do they get? Measured in V/C.</span></button>
      <button class="kind" data-kind="demand"><b>Change the demand</b><span>Trips added between
        zones. Where does the new traffic go? Measured in traffic volumes.</span></button>
      <button class="kind" data-kind="newroad"><b>Build a new road</b><span>A new road between
        two junctions of the network. Who takes it, and which streets does it relieve? Measured
        in traffic volumes.</span></button>
    </div>
  </div>

  <div id="editor" hidden>
  <p class="kindsaid" id="kindsaid"></p>
  <div class="row">
    <label>Name (file name: a-z, 0-9, _) <input id="name" placeholder="e.g. bolivar_closed" size="22"></label>
    <label>Label <input id="label" placeholder="shown on the results pages" size="30"></label>
  </div>
  <div class="row"><label>Description <textarea id="description" placeholder="what the scenario is for (optional)"></textarea></label></div>

  <div class="work">
    <div><div class="mapview" id="mapview"><button data-view="roads">Road network</button
      ><button data-view="voc">Base congestion (V/C)</button></div>
      <div id="map"></div>
      <div class="legend" id="legend"></div></div>
    <div class="side">
      <div data-for="pick">
      <h3>Selected roads</h3>
      <div id="selected" class="muted">Click a road on the map for its stretch, to the next main
        road (shift+click: one piece), or pick a suggested corridor below.</div>
      <div style="margin-top:6px; display:flex; gap:6px; flex-wrap:wrap">
        <button class="small" id="clear">Clear</button>
        <button class="small" id="grow">Grow along the street</button>
        <button class="small" id="street">The whole street</button>
      </div>
      <h3>What happens to them</h3>
      <label class="choice" data-type="closure"><input type="radio" name="kind" value="close" checked> closed</label>
      <label class="choice" data-type="capacity"><input type="radio" name="kind" value="capacity"> capacity ×
        <input type="number" id="factor" value="1.5" step="0.1" min="0.1" max="10">
        <span class="muted">(1.5 ≈ one lane more, 0.5 a lane closed)</span></label>
      <label class="choice" data-type="capacity"><input type="radio" name="kind" value="speed"> free-flow speed
        <input type="number" id="kmh" value="50" step="5" min="1" max="150"> km/h</label>
      <button class="small" id="add" style="margin-top:6px">＋ Add as an edit</button>
      <h3>Suggested corridors <span class="muted">(from the base's results)</span></h3>
      <div>by <select id="by"><option value="delay">vehicle-hours lost</option>
        <option value="volume">traffic</option><option value="voc">worst V/C</option></select>
        &nbsp; a stretch of <input type="number" id="section" value="20" min="1" max="200"> links</div>
      <div class="sugg" id="sugg"></div>
      <p class="muted" style="margin:6px 0 0">Vehicle-hours lost is where a widening can win time
      back; the worst V/C is often a small street where it buys little.</p>
      </div>
      <div data-for="demand">
        <h3>Trips added between zones</h3>
        <p class="muted" style="margin:6px 0 8px">A pair at a time: click the zone the trips start
        from, then the zone they go to, give the trips, and add the pair. Then the next one.</p>
        <div id="pairsteps"></div>
        <div class="roadform">
          <label>Trips <input type="number" id="dtrips" value="500" min="1" step="50"></label>
          <label class="check"><input type="checkbox" id="dboth"> and as many back</label>
        </div>
        <div style="margin-top:6px; display:flex; gap:6px; flex-wrap:wrap">
          <button class="small" id="adddemand">＋ Add this pair</button>
          <button class="small" id="dclear">Clear</button>
        </div>
        <p class="muted" style="margin:8px 0 0" id="dperiod"></p>
      </div>
      <div data-for="road">
        <h3>The new road</h3>
        <div id="roaddraw" class="muted"></div>
        <div style="margin-top:6px; display:flex; gap:6px; flex-wrap:wrap">
          <button class="small" id="draw">✎ Draw</button>
          <button class="small" id="undo">Undo a point</button>
          <button class="small" id="rclear">Clear</button>
        </div>
        <div class="roadform">
          <label>Name <input id="rname" placeholder="e.g. Ligação Norte"></label>
          <label>Road class <select id="rclass"><option>motorway</option><option>trunk</option>
            <option selected>primary</option><option>secondary</option><option>tertiary</option></select></label>
          <label>Lanes each way <input type="number" id="rlanes" min="1" max="6" value="2"></label>
          <label>Free-flow speed, km/h <input type="number" id="rkmh" min="1" max="150" step="5"></label>
          <label>Capacity, veh/h a lane <input type="number" id="rcap" min="100" max="3000" step="50"></label>
          <label class="check"><input type="checkbox" id="roneway"> one way, as drawn</label>
        </div>
        <p class="muted" id="rdefaults" style="margin:4px 0 0"></p>
        <button class="small" id="addroad" style="margin-top:6px">＋ Add as an edit</button>
      </div>
      <h3>The edits</h3>
      <div id="edits" class="muted">None yet.</div>
    </div>
  </div>

  <div class="actions">
    <label class="gap">Convergence: relative gap <select id="rgap"></select>
      <span class="muted" id="rgapsaid"></span></label>
    <button id="run" class="btn primary">▶ Save and run the scenario</button>
    <button id="save" class="btn">Save</button>
    <span id="message" class="message"></span>
  </div>
  <div id="job"></div>
  </div>
</main>
<script>
const CITY = "{city}";
const $ = id => document.getElementById(id);
const esc = t => String(t).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;",
                                                     '"': "&quot;", "'": "&#39;"}[c]));
const NAME = /^[a-z0-9][a-z0-9_]{0,59}$/;
const num = (x, d) => Number(x).toLocaleString(undefined, {minimumFractionDigits: d, maximumFractionDigits: d});
// V/C bands as the results' congestion map draws them.
const BANDS = [[0.5, "#2c7bb6", "under 50%"], [0.85, "#8cc4de", "50-85%"], [1.0, "#fdae61", "85-100%"],
               [1.5, "#d7191c", "100-150%"], [1e9, "#7d0018", "over 150%"]];
const EDIT_STYLE = {close: {color: "#111111", weight: 5, said: "closed"},
                    road: {color: "#0b7285", weight: 5, said: "new road"},
                    capacity: {color: "#d4a017", weight: 9, opacity: 0.5, said: "capacity changed"},
                    speed: {color: "#8e44ad", weight: 9, opacity: 0.5, said: "speed changed"}};
const SELECTED = "#00b3c7";
// The road network as it is: each class a grey, darker and wider the bigger the road.
const CLASS_LOOK = {motorway: ["#2f3842", 4], trunk: ["#46505b", 3.5], primary: ["#5f6a75", 3],
                    secondary: ["#848e98", 2.4], tertiary: ["#a9b1b9", 1.8]};
const classOf = t => (t || "").replace("_link", "");
// What the map shows: "roads" - the network, to draw a new road on - or "voc", the base's
// congestion, to pick the roads to close or widen.
let mapView = "voc", roadLines = {};

let runs = [], base = null, data = null, net = null, map = null, roads = null, overlay = null;
let selection = new Set(), edits = [], loadedName = "", running = null;
// What the scenario does: "closure" (its edits close roads) or "capacity" (capacity and speed).
let stype = "closure";
let roadBounds = [];               // the roads' extent: the map fits it again once shown
// A new road being drawn: {from, to, points: [[lat, lon], ...] where it bends}; the junctions it
// can start and end at - node -> [lat, lon]; the city's settings, for a class's defaults.
let road = null, drawing = false, roadLayer = null, settings = {};
// A demand scenario: the base's zones on the map, alone - each in blue - and the pair being made:
// the zone the trips start from, the zone they go to.
let zonesLayer = null, zonesOf = "", zoneLabels = null, pairLines = null;
let pairA = null, pairB = null;
const LABELS_FROM_ZOOM = 13;       // each zone's number on the map from this zoom
const ZONE_BLUE = "#3b7dd8";
const ZONE_COLOUR = {from: "#f08c00", to: "#d6336c", pair: "#1f3a5f"};
const nodeAt = {};
const SNAP_PX = 14;                // a click this close to a junction is on it
const CLICK_PX = 6;                // ... and this close to a road, on the road
const byNode = {};                 // node -> [link ids], for growing a selection along a street

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || response.statusText);
  return body;
}
function say(text, error) { $("message").textContent = text; $("message").className = "message" + (error ? " error" : ""); }

const scripts = {};
function load(src) {
  return scripts[src] || (scripts[src] = new Promise((ok, fail) => {
    const s = document.createElement("script");
    s.src = src; s.onload = ok; s.onerror = () => fail(new Error(`cannot read ${src}`));
    document.head.appendChild(s);
  }));
}

const folderOf = run => run.output.split("/").filter(Boolean).pop();
const band = v => BANDS.find(b => v < b[0]) || BANDS[BANDS.length - 1];
const flow = id => (data.flows[id] || [0, 0, 0, 0]);

// --- the base: its roads, coloured by its congestion ------------------------------------------------
async function chooseBase(name) {
  base = runs.find(r => r.name === name);
  if (!base) return;
  say("Loading the base's results ...");
  try {
    await Promise.all([load(`/macro/compare_${CITY}_network.js`), load(`${base.output}exports/compare_data.js`)]);
  } catch (e) { say(`${e.message} - open the city's Macrosimulation list once, so its files are written.`, true); return; }
  net = window.MACRO_NETWORK;
  if (zonesLayer) { zonesLayer.remove(); zonesLayer = null; zonesOf = ""; }
  data = window.MACRO_RUNS[folderOf(base)];
  // Where a demand scenario's trips go: the base's final matrix, for the period it models.
  $("dperiod").innerHTML = `The trips are added to the <b>final matrix</b> - the one the base assigns, `
    + `for the period it models${data && data.modelled ? ` (${esc(data.modelled)})` : ""} - after its day `
    + `and time of day are worked out, and are not converted again: vehicle trips in that period, an hour `
    + `or a day.`;
  for (const k in byNode) delete byNode[k];
  for (const [id, g] of Object.entries(net)) for (const n of [g[3], g[4]]) (byNode[n] = byNode[n] || []).push(id);
  // Each junction's place: the ends of the roads' links - where a new road may start and end.
  for (const k in nodeAt) delete nodeAt[k];
  for (const g of Object.values(net)) { nodeAt[g[3]] = g[2][0]; nodeAt[g[4]] = g[2][g[2].length - 1]; }
  drawRoads();
  scenarioList();
  suggest();
  say("");
}

function drawRoads() {
  if (!map) {
    // A road takes a click within CLICK_PX of it - Leaflet's own is half the line's width, a
    // pixel or two, which a hand on a mouse misses.
    map = L.map("map", {zoomSnap: 0.25, preferCanvas: true, renderer: L.canvas({tolerance: CLICK_PX})});
    const esri = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/";
    L.tileLayer(esri + "World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", {maxZoom: 18, maxNativeZoom: 16,
      attribution: "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors"}).addTo(map);
    L.tileLayer(esri + "World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}", {maxZoom: 18, maxNativeZoom: 16}).addTo(map);
    map.on("click", ev => drawClick(ev.latlng));
    map.on("moveend", () => { if (drawing) drawRoadLayer(); });
  }
  if (roads) roads.remove();
  roads = L.layerGroup().addTo(map);
  const bounds = [];
  const ids = Object.keys(net).sort((a, b) => flow(a)[2] - flow(b)[2]);    // the worst drawn last
  roadLines = {};
  for (const id of ids) {
    const g = net[id], f = flow(id);
    bounds.push(g[2][0]);
    roadLines[id] = L.polyline(g[2], roadStyle(id))
      .bindTooltip(`<b>${esc(g[0] || "unnamed")}</b> · ${esc(g[1])}<br>${num(f[0] + f[1], 0)} vehicles,
        V/C ${num(f[2], 2)}, ${num(f[3], 1)} vehicle-hours lost<br><i>click: its stretch, to the
        next main road · shift+click: this piece only</i>`, {sticky: true})
      .on("click", ev => {
        if (stype === "newroad" || stype === "demand") return;   // drawing a road, picking zones
        if (ev.originalEvent.shiftKey) toggle(id); else toggleAll(stretchOf(id));
      })
      .addTo(roads);
  }
  if (mapView === "roads") showView("roads");     // the bigger roads over the smaller
  if (stype === "demand") roads.remove();         // a demand scenario's map: the zones alone
  if (overlay) overlay.remove();
  overlay = L.layerGroup().addTo(map);          // the selection and the edits, over the roads
  if (roadLayer) roadLayer.remove();
  roadLayer = L.layerGroup().addTo(map);        // a new road being drawn, and the junctions
  roadBounds = bounds;
  map.fitBounds(bounds);
  drawLegend();
  drawOverlay();
}

function roadStyle(id) {
  const g = net[id];
  if (mapView === "roads") {
    const [color, weight] = CLASS_LOOK[classOf(g[1])] || ["#a9b1b9", 1.8];
    return {color, weight: g[1].endsWith("_link") ? weight * 0.6 : weight, opacity: 0.9};
  }
  return {color: band(flow(id)[2])[1], weight: g[1].startsWith("tertiary") ? 2 : 3, opacity: 0.85};
}

function showView(view) {
  // The roads restyled for the view; drawn in its order - by class, or the worst V/C on top.
  mapView = view;
  document.querySelectorAll("#mapview button").forEach(b => b.classList.toggle("on", b.dataset.view === view));
  const rank = id => view === "roads" ? -Object.keys(CLASS_LOOK).indexOf(classOf(net[id][1])) : flow(id)[2];
  for (const id of Object.keys(roadLines).sort((a, b) => rank(a) - rank(b))) {
    roadLines[id].setStyle(roadStyle(id));
    roadLines[id].bringToFront();
  }
  drawLegend();
}

$("mapview").addEventListener("click", ev => {
  const b = ev.target.closest("button[data-view]");
  if (b && map) showView(b.dataset.view);
});

function drawLegend() {
  // A demand scenario's zones and pairs; else the network's classes or the base's V/C, the
  // selection, and the edits of the scenario's kind.
  if (stype === "demand") {
    $("legend").innerHTML = `<span><i style="background:${ZONE_BLUE};height:10px"></i>a zone</span>`
      + Object.entries({from: "trips start", to: "trips end", pair: "a pair added"}).map(([k, said]) =>
          `<span><i style="background:${ZONE_COLOUR[k]};height:${k === "pair" ? 3 : 10}px"></i>${said}</span>`).join("");
    return;
  }
  const kinds = {closure: ["close"], capacity: ["capacity", "speed"], newroad: ["road"]}[stype];
  $("legend").innerHTML = (mapView === "roads"
    ? `<span>the road network:</span>` + Object.entries(CLASS_LOOK).map(([c, [color]]) =>
        `<span><i style="background:${color}"></i>${c}</span>`).join("")
    : `<span>the base's V/C:</span>` + BANDS.map(b => `<span><i style="background:${b[1]}"></i>${b[2]}</span>`).join(""))
    + `<span><i style="background:${SELECTED}"></i>selected</span>`
    + kinds.map(k => `<span><i style="background:${EDIT_STYLE[k].color}"></i>${EDIT_STYLE[k].said}</span>`).join("");
}

function drawOverlay() {
  overlay.clearLayers();
  for (const e of edits) {
    if (DEMAND_KINDS.includes(e.kind)) continue;            // its zones are on the zones layer
    const st = EDIT_STYLE[e.kind];
    if (e.kind === "road") {
      L.polyline(roadPoints({from: e.from_node, to: e.to_node, points: e.points}),
                 {color: st.color, weight: st.weight, opacity: 0.95, interactive: false}).addTo(overlay);
      continue;
    }
    for (const id of e.links) {
      const g = net[id];
      if (g) L.polyline(g[2], {color: st.color, weight: st.weight, opacity: st.opacity || 0.95,
                               dashArray: st.dashArray || null, interactive: false}).addTo(overlay);
    }
  }
  for (const id of selection) {
    const g = net[id];
    if (g) L.polyline(g[2], {color: SELECTED, weight: 7, opacity: 0.9, interactive: false}).addTo(overlay);
  }
  describeSelection();
}

// --- selecting -------------------------------------------------------------------------------------------
function toggle(id) {
  if (selection.has(id)) selection.delete(id); else selection.add(id);
  drawOverlay();
}

function toggleAll(ids) {
  // Selected already, every one: unselected; else every one selected.
  const all = [...ids].every(id => selection.has(id));
  for (const id of ids) if (all) selection.delete(id); else selection.add(id);
  drawOverlay();
}

function stretchOf(id) {
  // OSM cuts a road at every junction, side streets included: a link alone is a few dozen
  // metres. Its stretch: along the same street through every node only it meets, up to where
  // another main road crosses or joins it; an unnamed link (a ramp), through plain joints only.
  const name = net[id][0], out = new Set([id]), todo = [id];
  while (todo.length) {
    const j = todo.pop();
    for (const nd of [net[j][3], net[j][4]]) {
      const here = byNode[nd] || [];
      if (here.some(k => net[k][0] !== name) || (!name && here.length > 2)) continue;
      for (const k of here) if (!out.has(k)) { out.add(k); todo.push(k); }
    }
  }
  return out;
}

function streetsOf(ids) {
  const names = [...new Set([...ids].map(id => (net[id] || [""])[0]).filter(Boolean))];
  return names.length ? names.slice(0, 3).join(", ") + (names.length > 3 ? ` and ${names.length - 3} more` : "") : "unnamed roads";
}

function describeSelection() {
  const ids = [...selection];
  $("selected").innerHTML = ids.length
    ? `<b>${ids.length} link${ids.length !== 1 ? "s" : ""}</b> of ${esc(streetsOf(ids))}<br>
       <span class="muted">${num(ids.reduce((s, id) => s + flow(id)[0] + flow(id)[1], 0) / ids.length, 0)} vehicles
       on average, worst V/C ${num(Math.max(...ids.map(id => flow(id)[2])), 2)}</span>`
    : "Click a road on the map for its stretch, to the next main road (shift+click: one piece), "
      + "or pick a suggested corridor below.";
  for (const b of ["clear", "grow", "street", "add"]) $(b).disabled = !ids.length;
}

function metric(id, by) {
  const f = flow(id);
  return by === "delay" ? f[3] : by === "volume" ? f[0] + f[1] : f[2];
}

function grow(n, by) {
  // n more links joined to the selection along its streets, the worst by `by` first.
  const names = new Set([...selection].map(id => net[id][0]).filter(Boolean));
  for (let k = 0; k < n; k++) {
    const nodes = new Set([...selection].flatMap(id => [net[id][3], net[id][4]]));
    const next = [...nodes].flatMap(nd => byNode[nd] || [])
      .filter(id => !selection.has(id) && names.has(net[id][0]));
    if (!next.length) break;
    next.sort((a, b) => metric(b, by) - metric(a, by));
    selection.add(next[0]);
  }
}

$("clear").addEventListener("click", () => { selection.clear(); drawOverlay(); });
$("grow").addEventListener("click", () => { grow(5, $("by").value); drawOverlay(); });
$("street").addEventListener("click", () => {
  const names = new Set([...selection].map(id => net[id][0]).filter(Boolean));
  for (const [id, g] of Object.entries(net)) if (names.has(g[0])) selection.add(id);
  drawOverlay();
});

// --- suggested corridors ---------------------------------------------------------------------------------
function suggest() {
  const by = $("by").value;
  const streets = {};
  for (const [id, g] of Object.entries(net)) {
    if (!g[0]) continue;
    const m = metric(id, by);
    streets[g[0]] = by === "voc" ? Math.max(streets[g[0]] || 0, m) : (streets[g[0]] || 0) + m;
  }
  const top = Object.entries(streets).sort((a, b) => b[1] - a[1]).slice(0, 10);
  const unit = by === "delay" ? " veh-h lost" : by === "volume" ? " veh on its links" : " V/C";
  $("sugg").innerHTML = top.map(([name, v]) => `<div data-street="${esc(name)}"><span>${esc(name)}</span>
    <span class="muted">${num(v, by === "voc" ? 2 : 0)}${unit}</span></div>`).join("");
}

$("by").addEventListener("change", suggest);
$("sugg").addEventListener("click", ev => {
  const row = ev.target.closest("[data-street]");
  if (!row) return;
  // A stretch of the street: from its worst link, grown along it.
  const by = $("by").value, name = row.dataset.street;
  const links = Object.keys(net).filter(id => net[id][0] === name);
  links.sort((a, b) => metric(b, by) - metric(a, by));
  selection = new Set([links[0]]);
  grow(Math.max(0, (+$("section").value || 20) - 1), by);
  drawOverlay();
  const pts = [...selection].flatMap(id => net[id][2]);
  if (pts.length) map.fitBounds(pts, {maxZoom: 14, padding: [40, 40]});
});

// --- edits -----------------------------------------------------------------------------------------------
function zonesSaid(zones) {
  return zones.slice(0, 6).join(", ") + (zones.length > 6 ? ` and ${zones.length - 6} more` : "");
}

function editSaid(e) {
  if (e.kind === "trips" && e.pairs) {
    const back = e.both ? ", and as many back" : "";
    if (e.pairs.length === 1) return `+${num(e.pairs[0][2], 0)} trips from zone ${e.pairs[0][0]} to zone ${e.pairs[0][1]}${back}`;
    return `+${num(e.trips, 0)} trips between ${e.pairs.length} pairs of zones (`
      + e.pairs.slice(0, 4).map(([a, b, n]) => `${a}→${b}: ${num(n, 0)}`).join("; ")
      + `${e.pairs.length > 4 ? "; ..." : ""})${back}`;
  }
  if (e.kind === "trips")
    return `+${num(e.trips, 0)} trips from zone${e.from_zones.length > 1 ? "s" : ""} ${zonesSaid(e.from_zones)} `
      + `to ${zonesSaid(e.to_zones)}${e.both ? ", and as many back" : ""}`;
  if (e.kind === "develop")
    return `development in zone${e.zones.length > 1 ? "s" : ""} ${zonesSaid(e.zones)}: `
      + [e.residents ? `${num(e.residents, 0)} residents` : "", e.jobs ? `${num(e.jobs, 0)} jobs` : ""].filter(Boolean).join(", ");
  if (e.kind === "growth")
    return `${{within: "trips within the city", outbound: "trips from the city to outside",
      inbound: "trips from outside into the city", through: "trips through the city"}[e.group]} `
      + `${e.percent > 0 ? "+" : ""}${e.percent}%`;
  if (e.kind === "road")
    return `new road: ${e.label} (${e.link_type}, ${e.lanes} lane${e.lanes > 1 ? "s" : ""} `
      + `${e.oneway ? "one way" : "each way"}, ${e.kmh} km/h, `
      + `${num(roadKm({from: e.from_node, to: e.to_node, points: e.points}), 2)} km)`;
  return (e.kind === "close" ? "closed" : e.kind === "capacity" ? `capacity × ${e.factor}` : `speed ${e.kmh} km/h`)
    + `: ${e.label} (${e.links.length} link${e.links.length !== 1 ? "s" : ""})`;
}

function drawEdits() {
  $("edits").innerHTML = edits.length ? edits.map((e, i) => `<div class="edit"><b>${esc(editSaid(e))}</b>
    <div class="tools"><button class="small" data-show="${i}">show</button>
    <button class="small" data-drop="${i}">remove</button></div></div>`).join("") : "None yet.";
  drawOverlay();
  if (zonesLayer) zonesLayer.setStyle(zoneStyle);
  drawPairLines();
}

$("add").addEventListener("click", () => addEdit());

// --- a demand scenario: trips added between zones, a pair at a time ------------------------------------
function demandKind() { return "trips"; }       // core/demand_edits.py has others, for a run file

function showDemandKind() { describePicks(); }

function drawZoneLabels() {
  // Each zone's number at its middle, from LABELS_FROM_ZOOM, the zones in view only.
  if (!zoneLabels) zoneLabels = L.layerGroup().addTo(map);
  zoneLabels.clearLayers();
  if (stype !== "demand" || !zonesLayer || map.getZoom() < LABELS_FROM_ZOOM) return;
  const view = map.getBounds();
  zonesLayer.eachLayer(l => {
    const at = l.getBounds().getCenter();
    if (view.contains(at))
      L.marker(at, {interactive: false, icon: L.divIcon({className: "zlabel", iconSize: [40, 14],
        html: String(l.feature.properties.zone)})}).addTo(zoneLabels);
  });
}

async function loadZones() {
  // The base's zones, once: shapes with their people, jobs and trips.
  if (!map || !base) return;
  if (zonesLayer && zonesOf === base.name) {
    if (!map.hasLayer(zonesLayer)) zonesLayer.addTo(map);
    drawPairLines();
    drawZoneLabels();
    return;
  }
  try {
    say("Loading the base's zones ...");
    const data = await api(`/api/${CITY}/macro/${base.name}/zones`);
    if (zonesLayer) zonesLayer.remove();
    zonesOf = base.name;
    zonesLayer = L.geoJSON(data, {style: zoneStyle, onEachFeature: (f, layer) => {
      const z = f.properties;
      layer.bindTooltip(`<b>zone ${z.zone}</b> (${esc(z.name)})<br>${num(z.pop, 0)} people`
        + (z.jobs != null ? `, ${num(z.jobs, 0)} jobs` : "")
        + `<br>${num(z.out, 0)} trips leave it, ${num(z.in, 0)} reach it`, {sticky: true});
      layer.on("click", () => pickZone(z.zone));
    }});
    if (stype === "demand") zonesLayer.addTo(map);
    if (!zoneLabels) map.on("moveend", drawZoneLabels);       // once: the labels follow the map
    drawPairLines();
    drawZoneLabels();
    say("");
  } catch (e) { say(e.message, true); }
}

function zoneStyle(f) {
  // Every zone blue with a white border; the pair being made in its two colours.
  const z = f.properties.zone;
  const role = z === pairA ? "from" : z === pairB ? "to" : null;
  return role ? {color: "#ffffff", weight: 2, fillColor: ZONE_COLOUR[role], fillOpacity: 0.85}
    : {color: "#ffffff", weight: 1, fillColor: ZONE_BLUE, fillOpacity: 0.45};
}

function zoneCentres() {
  const at = {};
  if (zonesLayer) zonesLayer.eachLayer(l => { at[l.feature.properties.zone] = l.getBounds().getCenter(); });
  return at;
}

function drawPairLines() {
  // The pairs added: a line from the zone the trips start from to the one they go to.
  if (!map) return;
  if (!pairLines) pairLines = L.layerGroup().addTo(map);
  pairLines.clearLayers();
  if (stype !== "demand" || !zonesLayer) return;
  const at = zoneCentres();
  for (const e of edits) for (const [a, b, n] of (e.kind === "trips" && e.pairs) || []) {
    if (!at[a] || !at[b]) continue;
    L.polyline([at[a], at[b]], {color: ZONE_COLOUR.pair, weight: 3, opacity: 0.9})
      .bindTooltip(`zone ${a} → zone ${b}: ${num(n, 0)} trips${e.both ? ", and as many back" : ""}`, {sticky: true})
      .addTo(pairLines);
    L.circleMarker(at[b], {radius: 5, color: ZONE_COLOUR.pair, weight: 2, fillColor: "#fff", fillOpacity: 1,
                           interactive: false}).addTo(pairLines);
  }
}

function pickZone(zone) {
  // The first click the zone the trips start from, the next the zone they go to; once both are
  // picked, a click starts a new pair.
  if (stype !== "demand") return;
  if (pairA == null || (pairB != null)) { pairA = zone; pairB = null; }
  else if (zone === pairA) pairA = null;
  else pairB = zone;
  zonesLayer.setStyle(zoneStyle);
  describePicks();
}

function describePicks() {
  const chip = (z, role) => `<span class="zchip" style="background:${ZONE_COLOUR[role]}">${z}</span>`;
  $("pairsteps").innerHTML = `From ${pairA != null ? chip(pairA, "from") : "<i>click a zone</i>"}`
    + ` → to ${pairB != null ? chip(pairB, "to") : pairA != null ? "<i>click the zone they go to</i>" : "…"}`;
  $("adddemand").disabled = pairA == null || pairB == null;
}

function demandPending() { return pairA != null && pairB != null; }

function addDemand() {
  // The pair, with its trips, as an edit; false if it cannot be one.
  if (pairA == null || pairB == null) { say("Click the zone the trips start from, then the zone they go to.", true); return false; }
  const n = +$("dtrips").value;
  if (!(n > 0)) { say("Give the trips added: more than 0.", true); return false; }
  const e = {kind: "trips", pairs: [[pairA, pairB, n]], both: $("dboth").checked,
             from_zones: [pairA], to_zones: [pairB], trips: n, links: []};
  e.label = editSaid(e);
  edits.push(e);
  pairA = pairB = null;
  drawEdits();
  if (zonesLayer) zonesLayer.setStyle(zoneStyle);
  describePicks();
  say("");
  return true;
}
$("adddemand").addEventListener("click", () => addDemand());
$("dclear").addEventListener("click", () => {
  pairA = pairB = null;
  if (zonesLayer) zonesLayer.setStyle(zoneStyle);
  describePicks();
});

function showZones(e) {
  // The map fitted to an edit's zones.
  const mine = new Set([...(e.from_zones || []), ...(e.to_zones || []), ...(e.zones || [])]);
  if (!zonesLayer || !mine.size) return;
  const parts = [];
  zonesLayer.eachLayer(l => { if (mine.has(l.feature.properties.zone)) parts.push(l.getBounds()); });
  if (parts.length) map.fitBounds(parts.reduce((x, y) => x.extend(y)), {maxZoom: 14, padding: [40, 40]});
}

// --- a new road: drawn from junction to junction -------------------------------------------------------
function roadPoints(r) {
  return [nodeAt[r.from]].concat(r.points, r.to != null ? [nodeAt[r.to]] : []).filter(Boolean);
}

function roadKm(r) {
  const pts = roadPoints(r);
  let km = 0;
  for (let k = 1; k < pts.length; k++) km += map.distance(pts[k - 1], pts[k]) / 1000;
  return km;
}

function shownJunction(n) {
  // Zoomed out, only where main roads meet (three links or more) or end; from zoom 15 every
  // junction - OSM splits a road at each side street, which crowds the map at city scale.
  const links = (byNode[n] || []).length;
  return map.getZoom() >= 15 || links >= 3 || links === 1;
}

function nearestJunction(latlng) {
  // The junction shown that a click is on - within SNAP_PX on the screen - or null.
  const p = map.latLngToContainerPoint(latlng);
  let best = null;
  for (const [n, q] of Object.entries(nodeAt)) {
    if (!shownJunction(n)) continue;
    const d = p.distanceTo(map.latLngToContainerPoint(q));
    if (d < SNAP_PX && (!best || d < best[1])) best = [+n, d];
  }
  return best && best[0];
}

function drawClick(latlng) {
  // Drawing: the first click starts on a junction, a click on another junction ends the road,
  // any other click is a point it bends through.
  if (stype !== "newroad" || !drawing) return;
  const n = nearestJunction(latlng);
  if (!road) {
    if (n == null) { say("Start on a junction: click one of the dots (zoom in to see them).", true); return; }
    road = {from: n, to: null, points: []};
  } else if (n != null && n !== road.from) {
    road.to = n;
    stopDrawing();
  } else road.points.push([+latlng.lat.toFixed(6), +latlng.lng.toFixed(6)]);
  say("");
  drawRoadLayer();
  describeRoad();
}

function stopDrawing() {
  drawing = false;
  map.getContainer().classList.remove("drawing");
}

function drawRoadLayer() {
  roadLayer.clearLayers();
  if (drawing && map.getZoom() >= 13) {           // the junctions in view, to start and end at
    const view = map.getBounds();
    for (const [n, q] of Object.entries(nodeAt))
      if (view.contains(q) && shownJunction(n)) L.circleMarker(q, {radius: 3, color: EDIT_STYLE.road.color, weight: 1,
                                               fillColor: "#fff", fillOpacity: 1, interactive: false}).addTo(roadLayer);
  }
  if (!road) return;
  const pts = roadPoints(road);
  if (pts.length > 1) L.polyline(pts, {color: EDIT_STYLE.road.color, weight: 5, opacity: 0.9,
                                       dashArray: road.to == null ? "6 6" : null, interactive: false}).addTo(roadLayer);
  for (const q of [pts[0], road.to != null ? pts[pts.length - 1] : null].filter(Boolean))
    L.circleMarker(q, {radius: 6, color: EDIT_STYLE.road.color, weight: 3, fillColor: "#fff",
                       fillOpacity: 1, interactive: false}).addTo(roadLayer);
}

function describeRoad() {
  $("roaddraw").innerHTML = !road
    ? (drawing ? "Click the junction the road starts from - the dots: where main roads meet, and "
       + "every junction from zoom 15."
       : "Press <b>Draw</b>, click the junction the road starts from, click where it bends if it "
         + "does, and finish on the junction it ends at.")
    : road.to == null
      ? `Started on a junction${road.points.length ? `, ${road.points.length} bend${road.points.length > 1 ? "s" : ""}` : ""}: `
        + `click where it bends, and finish on a junction. ${num(roadKm(road), 2)} km so far.`
      : `<b>${num(roadKm(road), 2)} km</b>, junction to junction${road.points.length
          ? `, through ${road.points.length} bend${road.points.length > 1 ? "s" : ""}` : ""}. `
        + `Give it a class and add it as an edit.`;
  $("undo").disabled = $("rclear").disabled = !road;
  $("addroad").disabled = !road || road.to == null;
}

function setting(name) {
  // The base's value - a run may have changed it - else the city's.
  return base && base.parameters && name in base.parameters ? base.parameters[name] : settings[name];
}

function laneCapacity(kmh) {
  // As the network's roads have it (core/costs.py): the rate of the speed band it is in.
  let rate = setting("DEFAULT_SPEED_LANE_CAPACITY") ? setting("DEFAULT_SPEED_LANE_CAPACITY")[1] : 600;
  for (const [floor, cap] of [...(setting("LANE_CAPACITY_BY_SPEED") || [])].sort((a, b) => a[0] - b[0]))
    if (kmh >= floor) rate = cap;
  return rate;
}

function classDefaults() {
  // A class's speed, lanes and capacity, as the city's roads of that class have them.
  const c = $("rclass").value, speeds = setting("SPEED_KMH") || {}, lanes = setting("DEFAULT_LANES") || {};
  $("rkmh").value = speeds[c] || 50;
  $("rlanes").value = lanes[c] || 1;
  $("rcap").value = laneCapacity(+$("rkmh").value);
  $("rdefaults").textContent = `A ${c} as the city's roads of that class: ${$("rkmh").value} km/h, `
    + `${$("rlanes").value} lane${+$("rlanes").value > 1 ? "s" : ""} each way, ${$("rcap").value} veh/h a lane `
    + "- change any of them.";
}

$("rclass").addEventListener("change", classDefaults);
$("rkmh").addEventListener("change", () => { $("rcap").value = laneCapacity(+$("rkmh").value); });
$("draw").addEventListener("click", () => {
  if (road && road.to != null) road = null;       // a road drawn already: a new one
  drawing = true;
  map.getContainer().classList.add("drawing");
  if (map.getZoom() < 13) say("Zoom in to see the junctions it can start and end at.");
  drawRoadLayer();
  describeRoad();
});
$("undo").addEventListener("click", () => {
  if (!road) return;
  if (road.to != null) { road.to = null; drawing = true; map.getContainer().classList.add("drawing"); }
  else if (road.points.length) road.points.pop();
  else road = null;
  drawRoadLayer();
  describeRoad();
});
$("rclear").addEventListener("click", () => { road = null; stopDrawing(); drawRoadLayer(); describeRoad(); });
$("addroad").addEventListener("click", () => addRoad());

function addRoad() {
  // The road drawn, with its class, lanes, speed and capacity, as an edit; false if it cannot be.
  if (!road || road.to == null) { say("Draw the road first, from a junction to a junction.", true); return false; }
  const e = {kind: "road", label: $("rname").value.trim() || `New road ${edits.length + 1}`,
             from_node: road.from, to_node: road.to, points: road.points, link_type: $("rclass").value,
             lanes: +$("rlanes").value, kmh: +$("rkmh").value, lane_capacity: +$("rcap").value,
             oneway: $("roneway").checked};
  if (!(e.lanes >= 1 && e.lanes <= 6) || !(e.kmh >= 1 && e.kmh <= 150)
      || !(e.lane_capacity >= 100 && e.lane_capacity <= 3000)) {
    say("Lanes 1 to 6, speed 1 to 150 km/h, capacity 100 to 3,000 veh/h a lane.", true);
    return false;
  }
  edits.push(e);
  road = null;
  stopDrawing();
  $("rname").value = "";
  drawEdits();
  drawRoadLayer();
  describeRoad();
  say("");
  return true;
}

function addEdit() {
  // The selected roads, with what happens to them, as an edit; false if it cannot be one.
  const kind = document.querySelector("input[name=kind]:checked").value;
  const e = {kind, links: [...selection].map(Number), label: streetsOf(selection)};
  if (kind === "capacity") e.factor = parseFloat($("factor").value);
  if (kind === "speed") e.kmh = parseFloat($("kmh").value);
  if ((kind === "capacity" && !(e.factor > 0)) || (kind === "speed" && !(e.kmh > 0))) {
    say("Give the edit a number.", true); return false;
  }
  // A link edited again: the new edit replaces what an earlier one of the same kind did to it.
  for (const old of edits) if (old.kind === kind) old.links = old.links.filter(id => !selection.has(String(id)));
  edits = edits.filter(old => old.kind === "road" || old.links.length);
  edits.push(e);
  selection.clear();
  drawEdits();
  say("");
  return true;
}
$("edits").addEventListener("click", ev => {
  const show = ev.target.closest("[data-show]"), drop = ev.target.closest("[data-drop]");
  if (drop) { edits.splice(+drop.dataset.drop, 1); drawEdits(); }
  if (show) {
    const e = edits[+show.dataset.show];
    if (DEMAND_KINDS.includes(e.kind)) { showZones(e); return; }
    const pts = e.kind === "road" ? roadPoints({from: e.from_node, to: e.to_node, points: e.points})
      : e.links.flatMap(id => (net[id] || [null, null, []])[2]);
    if (pts.length) map.fitBounds(pts, {maxZoom: 14, padding: [40, 40]});
  }
});

// --- the scenarios of a base -----------------------------------------------------------------------------
function scenarioList() {
  const mine = runs.filter(r => r.base === base.name);
  $("scenario").innerHTML = `<option value="">a new scenario</option>` + mine.map(r =>
    `<option value="${esc(r.name)}">${esc(r.label)} (${esc(r.name)}) · ${{closure: "closes roads",
      capacity: "capacity or speed", newroad: "builds roads", demand: "changes demand"}[typeOf(r)]}${r.done ? " · run" : ""}</option>`).join("");
  $("scenario").value = mine.some(r => r.name === loadedName) ? loadedName : "";
}

// --- what the scenario does ----------------------------------------------------------------------------
const DEMAND_KINDS = ["trips", "develop", "growth"];

function typeOf(r) {
  return r.type || (r.edits.some(e => DEMAND_KINDS.includes(e.kind)) ? "demand"
    : r.edits.some(e => e.kind === "close") ? "closure"
    : r.edits.some(e => e.kind === "road") ? "newroad" : "capacity");
}

const KIND_SAID = {closure: "A scenario that closes roads",
                   capacity: "A scenario that changes roads' capacity or speed",
                   newroad: "A scenario that builds new roads",
                   demand: "A scenario that changes the demand"};

function setType(t, fixed) {
  // The editor for one kind: only its edits offered, the corridors ranked the notebook's way - a
  // closure by the traffic it moves, a widening by the vehicle-hours it can win back. A saved
  // scenario's kind is `fixed`; a new one's can be chosen again.
  stype = t;
  road = null;
  if (map) stopDrawing();
  // Picking roads for a closure or a capacity change; drawing one for a new road.
  const panel = {closure: "pick", capacity: "pick", newroad: "road", demand: "demand"}[t];
  document.querySelectorAll("[data-for]").forEach(d => {
    d.style.display = d.dataset.for === panel ? "" : "none";
  });
  pairA = pairB = null;
  if (t === "demand") { showDemandKind(); loadZones(); } else if (zonesLayer) zonesLayer.remove();
  if (pairLines) drawPairLines();
  $("mapview").style.display = t === "demand" ? "none" : "";
  if (roads) { if (t === "demand") roads.remove(); else if (!map.hasLayer(roads)) roads.addTo(map); }
  if (zoneLabels) drawZoneLabels();
  document.querySelectorAll("label.choice[data-type]").forEach(l => {
    l.style.display = l.dataset.type === t ? "" : "none";
  });
  const first = document.querySelector(`label.choice[data-type=${t}] input[name=kind]`);
  if (first) first.checked = true;
  if (t === "newroad") { classDefaults(); describeRoad(); if (roadLayer) drawRoadLayer(); }
  // A new road is drawn on the network; roads to close or widen are picked by their congestion.
  const view = t === "newroad" || t === "demand" ? "roads" : "voc";
  if (map) showView(view); else mapView = view;
  $("by").value = t === "closure" ? "volume" : "delay";
  $("kindsaid").innerHTML = `<b>${KIND_SAID[t]}</b>`
    + (fixed ? "" : `<a href="#" id="rekind">← choose another kind</a>`);
  $("kinds").hidden = true;
  $("editor").hidden = false;
  if (map) { map.invalidateSize(); if (roadBounds.length) map.fitBounds(roadBounds); drawLegend(); }
  if (net) suggest();
}

function chooseKind() {
  // A new scenario: its kind first, nothing to edit until it is chosen.
  $("editor").hidden = true;
  $("kinds").hidden = false;
}

$("kinds").addEventListener("click", ev => {
  const b = ev.target.closest("button[data-kind]");
  if (b) setType(b.dataset.kind, false);
});
$("kindsaid").addEventListener("click", ev => {
  if (ev.target.id !== "rekind") return;
  ev.preventDefault();
  if ((edits.length || selection.size) && !confirm("Choose another kind of scenario? Its edits "
      + "and selected roads are dropped.")) return;
  edits = [];
  selection.clear();
  drawEdits();
  chooseKind();
});

function openScenario(name) {
  const r = runs.find(x => x.name === name);
  loadedName = name || "";
  edits = r ? JSON.parse(JSON.stringify(r.edits)).map(e => ({...e, links: (e.links || []).map(Number)})) : [];
  if (r) setType(typeOf(r), true); else chooseKind();
  $("name").value = r ? r.name : "";
  $("label").value = r ? r.label : "";
  $("description").value = r ? r.description : "";
  $("scenario").value = loadedName;
  selection.clear();
  drawEdits();
  $("job").innerHTML = r && r.done ? results(r.name) : "";
  drawGap(gapOf(r || base)[0]);
}

$("base").addEventListener("change", async () => { loadedName = ""; await chooseBase($("base").value); openScenario(""); });
$("scenario").addEventListener("change", () => openScenario($("scenario").value));

// --- running ---------------------------------------------------------------------------------------------
function results(name) {
  const folder = `${CITY}-${name}`;
  return `<div class="job">The scenario has results:
    <a class="button" href="/macro/${folder}/index.html">Open its results</a>
    <a class="button" href="/macro/compare_${CITY}.html?a=${folderOf(base)}&b=${folder}">Compare it with its base</a></div>`;
}

// How close the scenario's assignment converges: its own, else its base's (the base's run, or the
// city's settings). A gap looser than its effect leaves the effect to the solver's tolerance.
const GAPS = [1e-3, 5e-4, 1e-4, 5e-5, 1e-5];
function gapOf(r) {
  const p = (r && r.parameters && r.parameters.RGAP_TARGET_MAX_ITER) || settings.RGAP_TARGET_MAX_ITER;
  return p || [1e-4, 500];
}
function drawGap(value) {
  const gaps = GAPS.includes(value) ? GAPS : GAPS.concat([value]).sort((a, b) => b - a);
  $("rgap").innerHTML = gaps.map(g => `<option value="${g}">${g.toExponential(0)}${
    g === 1e-4 ? " (recommended)" : ""}</option>`).join("");
  $("rgap").value = String(value);
  const fromBase = gapOf(base)[0];
  $("rgapsaid").textContent = +$("rgap").value === fromBase ? "as its base" : `its base: ${fromBase.toExponential(0)}`;
}
$("rgap").addEventListener("change", () => drawGap(+$("rgap").value));

async function save(andRun) {
  const name = $("name").value.trim();
  if (!NAME.test(name) || name === "baseline") { say("Give the scenario a name: lower-case letters, digits and _.", true); return; }
  // Roads selected and not yet added: they are what the scenario does to them, as an edit.
  if (stype === "newroad") { if (road && road.to != null && !addRoad()) return; }
  else if (stype === "demand") { if (demandPending() && !addDemand()) return; }
  else if (selection.size && !addEdit()) return;
  if (!edits.length) {
    say(stype === "demand" ? "Pick the zones on the map - where trips start, where they go - and add it as an edit."
        : stype === "newroad" ? "Draw a road on the map, from a junction to a junction."
        : "Select the roads to change on the map, and say what happens to them.", true);
    return;
  }
  const existing = runs.find(r => r.name === name);
  if (existing && name !== loadedName && !confirm(`A run named ${name} exists: replace it?`)) return;
  try {
    const answer = await api(`/api/${CITY}/macro/${name}`, {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({label: $("label").value.trim() || name, description: $("description").value,
                            base: base.name, type: stype, edits, run: andRun,
                            parameters: {RGAP_TARGET_MAX_ITER: [+$("rgap").value, gapOf(base)[1]]}})});
    loadedName = name;
    await refresh();
    scenarioList();
    say(`Saved as macro_runs/${CITY}/${name}.json.`);
    if (answer.job) { running = answer.job; $("run").disabled = $("save").disabled = true; watch(name); }
  } catch (e) { say(e.message, true); }
}

async function watch(name) {
  let s;
  try { s = await api(`/api/jobs/${running}`); }
  catch (e) { running = null; $("run").disabled = $("save").disabled = false; say(e.message, true); return; }
  const steps = s.log.filter(l => /^[A-F][0-9]*[a-z]?[.] /.test(l));
  $("job").innerHTML = `<div class="job"><b>${esc(name)}</b>: ${s.state === "running"
    ? `running, ${Math.floor(s.seconds / 60)} min ${s.seconds % 60} s - ${esc(steps.length ? steps[steps.length - 1] : "starting")}`
    : s.state === "done" ? "done" : "failed"}<pre>${s.log.map(esc).join("\\n")}</pre></div>`;
  const pre = $("job").querySelector("pre"); pre.scrollTop = pre.scrollHeight;
  if (s.state === "running") { setTimeout(() => watch(name), 2000); return; }
  running = null;
  $("run").disabled = $("save").disabled = false;
  await refresh();
  scenarioList();
  if (s.state === "done") { $("job").innerHTML = results(name); say("The scenario has run."); }
  else say("The scenario failed: its log is above.", true);
}

async function refresh() {
  const state = await api(`/api/${CITY}/macro`);
  runs = state.runs;
  settings = Object.fromEntries(state.parameters.map(p => [p.name, p.value]));
  return state;
}

$("run").addEventListener("click", () => save(true));
$("save").addEventListener("click", () => save(false));

(async () => {
  const state = await refresh();
  const bases = runs.filter(r => !r.base && r.steps && r.steps.assignment && r.steps.assignment.state === "done");
  if (!bases.length) { say("No computed run yet: run a macrosimulation first, then make scenarios from it.", true); return; }
  $("base").innerHTML = bases.map(r => `<option value="${esc(r.name)}">${r.name === "baseline" ? "the baseline"
    : `${esc(r.label)} (${esc(r.name)})`}</option>`).join("");
  const params = new URLSearchParams(location.search);
  const wanted = params.get("base"), scen = runs.find(r => r.name === params.get("scenario") && r.base);
  $("base").value = scen ? scen.base : bases.some(r => r.name === wanted) ? wanted : bases[0].name;
  await chooseBase($("base").value);
  openScenario(scen ? scen.name : "");
  if (state.running && state.running.city === CITY) { running = state.running.job; $("run").disabled = $("save").disabled = true; watch(state.running.name); }
})();
</script>
</body>
</html>
"""
