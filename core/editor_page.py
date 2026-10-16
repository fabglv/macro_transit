"""The line design editor's page, served by core/server.py at /editor/<city>: the lines, and nothing
about passengers - simulating a design is the simulation page's (simulate_page.py).

Two parts, one under the other, the way GTFS keeps them apart too.

1. Where the lines run - a map and a panel beside it. Add a line, or open an existing one on the
   map: in *Add stops* mode click the map to place a stop, or an existing stop to stop there too
   (and change to its lines); in *Move stops* mode drag a stop; rename, reorder and drop stops in
   the list. In *Shape the route* mode (buses), drag the route between two stops to make it
   pass through a point - a via point, kept in its place along the route, its order the order
   along the leg - drag a via point to move it, click it to remove it; each journey, outward
   and return, has its own. A line runs out and back or round a loop, one way or both. Out and back, its outward
   journey's stops come first; under them its return journey is the same stops reversed until it
   is given stops of its own, which start as the outward ones reversed. A bus line's stops are checked against the streets as they are placed,
   since a bus route is matched onto them and a stop too far from any street breaks that; a
   flagged stop can be snapped onto the nearest one. The map shows the lines stop to stop or along
   the streets: the baseline's and a started-from design's as their design pages drew them, a new
   bus line along the shortest way through the streets between its stops - a preview of the map
   matching (transit/streets.py).

2. When they run - the timetable of every line, existing, edited and new: whether it runs, its
   hours, its headway and other headways at some hours (the peaks), its speed, dwell and places
   per vehicle, its time between stops (estimated, or set by hand), weekdays, Saturday and
   Sunday, with its departures an hour drawn as it is set.

What is saved: a new line is an `add_line` change; an existing line whose stops were edited an
`edit_line`, timetable included; one whose timetable alone changed a `service`; one that no longer
runs a `remove_line`. Start from the baseline or an existing design and save it under a name - a
file in designs/<city>/, the same file design.py and run.py read. Saving builds the design's pages
(design.py, a few seconds); a button then opens them, another the simulation page with it.
"""
import html

from .viewer import ICON, STYLE

LEAFLET = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4"


def page(city):
    return PAGE.replace("{style}", STYLE).replace("{icon}", ICON).replace("{city}", html.escape(city)) \
        .replace("{title}", html.escape(city.title())).replace("{leaflet}", LEAFLET)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} line design editor</title>
<link rel="stylesheet" href="{leaflet}/leaflet.min.css">
<script src="{leaflet}/leaflet.min.js"></script>
{icon}
<style>
{style}
  body { display:block; }
  .editor { max-width:1400px; padding:28px 32px 60px; }
  .row { display:flex; gap:14px; flex-wrap:wrap; align-items:flex-end; margin:0 0 14px; }
  .row label, .form label, .ttfields label { display:flex; flex-direction:column; font-size:12px;
      color:var(--soft); gap:4px; }
  .row input, .row select, .row textarea, .form input, .form select, .ttfields input, .ttfields select,
  .side select.open { font:inherit; color:var(--ink); padding:6px 9px; border:1px solid var(--line);
      border-radius:6px; background:var(--panel); }
  .row textarea { width:640px; max-width:100%; min-height:64px; }
  .actions { display:flex; gap:10px; margin:18px 0; align-items:center; flex-wrap:wrap; }
  button.btn { font:inherit; padding:7px 14px; border-radius:6px; cursor:pointer;
      border:1px solid var(--accent); background:var(--panel); color:var(--accent); }
  button.btn.primary { background:var(--accent); color:#fff; }
  button.btn.danger { border-color:#c62828; color:#c62828; }
  button.btn:disabled { opacity:.5; cursor:default; }
  .message { font-size:13px; }
  .message.error { color:#c62828; }
  .run { background:var(--panel); border:1px solid var(--line); border-radius:8px;
      padding:12px 14px; margin-top:6px; }
  .run pre { max-height:320px; overflow:auto; border:0; padding:0; background:none; }

  h2.part { font-size:18px; margin:30px 0 4px; padding:0; border:0; }
  h2.part .n { display:inline-flex; width:24px; height:24px; border-radius:50%; background:var(--accent);
      color:#fff; font-size:13px; align-items:center; justify-content:center; margin-right:8px;
      vertical-align:2px; }
  .views { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin:0 0 10px;
      font-size:13px; color:var(--soft); }
  .views .seg { margin:0 12px 0 0; }
  .ttfilter { position:sticky; top:0; z-index:500; display:flex; gap:10px; align-items:center;
      flex-wrap:wrap; padding:8px 0; margin:0 0 6px; background:var(--bg); font-size:13px;
      color:var(--soft); }
  .ttfilter input[type=search] { font:inherit; width:260px; padding:6px 9px;
      border:1px solid var(--line); border-radius:6px; background:var(--panel); color:var(--ink); }
  .ttfilter .seg button { font:inherit; font-size:13px; }
  #ttnone { color:var(--soft); font-size:13px; }
  details.showlines { position:relative; margin:0 12px 0 0; }
  details.showlines summary { list-style:none; cursor:pointer; font-size:13px; color:var(--ink);
      padding:4px 10px; border:1px solid var(--line); border-radius:6px; background:var(--panel); }
  details.showlines summary::-webkit-details-marker { display:none; }
  details.showlines[open] summary { border-color:var(--accent); color:var(--accent); }
  details.showlines .menu { position:absolute; z-index:1000; top:calc(100% + 4px); left:0;
      width:240px; max-height:360px; overflow:auto; background:var(--panel); color:var(--ink);
      border:1px solid var(--line); border-radius:8px; box-shadow:0 4px 14px rgba(0,0,0,.12);
      padding:8px 10px; }
  details.showlines .menu .all { display:flex; gap:6px; margin:0 0 6px; }
  details.showlines .menu .all button { font:inherit; font-size:12px; padding:2px 8px;
      border:1px solid var(--line); border-radius:5px; background:var(--panel); cursor:pointer; }
  details.showlines label { display:flex; align-items:center; gap:6px; font-size:13px;
      padding:2px 0; cursor:pointer; }
  details.showlines .showhint { font-size:11px; color:var(--soft); margin:6px 0 0; }
  details.showlines label i { width:14px; height:4px; border-radius:2px; flex:none; }
  .seg button { font:inherit; font-size:13px; }
  .newlines { display:grid; grid-template-columns:minmax(0,1fr) 400px; gap:16px;
      align-items:start; }
  #map { height:620px; border:1px solid var(--line); border-radius:8px; }
  #map.adding { cursor:crosshair; }
  #map.moving .leaflet-marker-icon { cursor:move; }
  #map.adding .leaflet-interactive { cursor:pointer; }
  .side { background:var(--panel); border:1px solid var(--line); border-radius:8px;
      padding:12px 14px; max-height:620px; overflow:auto; }
  .side select.open { width:100%; margin:0 0 10px; font-size:13px; }
  .tabs { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px; }
  .tabs button { font:inherit; font-size:13px; padding:4px 10px; border-radius:14px;
      border:1px solid var(--line); background:var(--panel); cursor:pointer; }
  .tabs button.on { border-color:var(--accent); color:var(--accent); font-weight:600; }
  .form { display:grid; grid-template-columns:1fr 1fr; gap:8px 10px; margin-bottom:10px; }
  .form .wide { grid-column:1 / -1; }
  .form input[type=color] { padding:2px; height:34px; }
  .side h4 { margin:12px 0 6px; font-size:13px; }
  .figure { font-size:13px; margin:8px 0; }
  ol.stops { list-style:none; margin:0; padding:0; }
  ol.stops li { display:grid; grid-template-columns:24px 1fr auto; gap:6px; align-items:start;
      padding:5px 0; border-top:1px solid var(--line); }
  ol.stops li.picked { background:#eef4ff; }
  ol.stops .n { width:20px; height:20px; border-radius:50%; color:#fff; font-size:11px;
      display:flex; align-items:center; justify-content:center; margin-top:4px; }
  ol.stops input { font:inherit; font-size:13px; padding:3px 6px; width:100%;
      border:1px solid var(--line); border-radius:5px; box-sizing:border-box; }
  ol.stops .tools button { font-size:12px; width:24px; height:24px; border:1px solid var(--line);
      border-radius:4px; background:var(--panel); cursor:pointer; padding:0; }
  .hint { font-size:11px; color:var(--soft); margin-top:2px; }
  .hint.bad { color:#c62828; }
  .hint.ok { color:#2e7d32; }
  .side h5 { margin:10px 0 4px; font-size:13px; }
  .retbox { border:1px dashed var(--line); border-radius:6px; padding:8px 10px; margin:10px 0 0;
      font-size:12px; color:var(--soft); }
  .retbox b { color:var(--ink); }
  .retbox .acts { display:flex; gap:6px; flex-wrap:wrap; margin-top:6px; }
  .retbox button:disabled { opacity:.5; cursor:default; }
  .dirs { display:flex; gap:0; margin:4px 0 8px; }
  .dirs button { font:inherit; font-size:13px; padding:4px 12px; cursor:pointer;
      border:1px solid var(--line); background:var(--panel); }
  .dirs button:first-child { border-radius:6px 0 0 6px; }
  .dirs button:last-child { border-radius:0 6px 6px 0; border-left:0; }
  .dirs button.on { background:var(--pick); color:var(--accent); font-weight:600; }
  .stopnum { width:22px; height:22px; border-radius:50%; color:#fff; font:600 11px sans-serif;
      display:flex; align-items:center; justify-content:center; border:2px solid #fff;
      box-shadow:0 0 0 1px rgba(0,0,0,.35); }
  .stopnum.bad { box-shadow:0 0 0 3px #c62828; }
  .vianum { width:14px; height:14px; border-radius:3px; background:#fff; border:2px solid;
      font:700 9px sans-serif; color:#222; display:flex; align-items:center; justify-content:center;
      box-shadow:0 0 0 1px rgba(0,0,0,.25); }
  #map.shaping .leaflet-interactive { cursor:grab; }
  #map.shaping.dragging-route, #map.shaping.dragging-route .leaflet-interactive { cursor:grabbing; }
  .hint button.small { font-size:11px; padding:0 6px; }
  .warnings { border:1px solid #f0d58c; background:#fff8e1; border-radius:6px; padding:8px 12px;
      font-size:13px; max-width:900px; margin:0 0 10px; }
  .warnings ul { margin:4px 0 0; padding-left:18px; }
  .stationpick { display:flex; gap:6px; align-items:center; font-size:11px; color:var(--soft);
      margin-top:3px; }
  .stationpick select { font:inherit; font-size:11px; padding:1px 4px; border:1px solid var(--line);
      border-radius:4px; max-width:250px; }
  details.legs { margin:8px 0 0; font-size:12px; }
  details.legs summary { cursor:pointer; color:var(--accent); }
  table.legtimes { margin:6px 0; font-size:12px; background:var(--panel); }
  table.legtimes th { cursor:default; }
  table.legtimes td { padding:2px 8px 2px 0; }
  table.legtimes input { width:64px; font:inherit; font-size:12px; text-align:right; padding:1px 4px;
      border:1px solid var(--line); border-radius:4px; }
  button.small, button.onmap { font:inherit; font-size:12px; padding:2px 9px; cursor:pointer;
      border:1px solid var(--line); border-radius:12px; background:var(--panel); color:var(--accent); }

  /* The timetable: a card per line. */
  #timetable { display:flex; flex-direction:column; gap:12px; max-width:1100px; }
  .tt { background:var(--panel); border:1px solid var(--line); border-left:4px solid var(--c);
      border-radius:8px; padding:10px 14px; }
  .tt.changed { background:#fffaf0; }
  .tt.off { opacity:.6; }
  .tt.off .tthead b { text-decoration:line-through; }
  .tthead { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
  .tthead b { font-size:15px; }
  .tthead .ttname { color:var(--soft); font-size:13px; }
  .tthead .badge { font-size:11px; color:var(--accent); border:1px solid #c9dafb; border-radius:10px;
      padding:0 7px; background:#f3f7ff; }
  .tthead .ttright { margin-left:auto; display:flex; gap:12px; align-items:center; font-size:13px; }
  .tthead label.runs { display:flex; gap:5px; align-items:center; cursor:pointer; }
  .days { display:flex; gap:0; margin:8px 0 0; }
  .days button { font:inherit; font-size:12px; padding:3px 11px; cursor:pointer;
      border:1px solid var(--line); background:var(--panel); color:var(--soft); }
  .days button:first-child { border-radius:6px 0 0 6px; }
  .days button:last-child { border-radius:0 6px 6px 0; }
  .days button + button { border-left:0; }
  .days button.on { background:var(--pick); color:var(--accent); font-weight:600; }
  .ttbody { display:grid; grid-template-columns:minmax(0,1fr) 300px; gap:8px 20px; margin-top:8px; }
  .ttfields { display:flex; gap:10px; flex-wrap:wrap; }
  .ttfields input[type=number] { width:80px; text-align:right; }
  .ttfields input[type=time] { padding:5px 7px; }
  .bands { margin:8px 0 0; }
  .band { display:flex; gap:6px; align-items:center; font-size:12px; color:var(--soft);
      margin:0 0 6px; flex-wrap:wrap; }
  .band input { font:inherit; font-size:12px; padding:3px 5px; border:1px solid var(--line);
      border-radius:5px; }
  .band input[type=number] { width:56px; text-align:right; }
  .band button { font:inherit; font-size:12px; padding:2px 8px; cursor:pointer;
      border:1px solid var(--line); border-radius:5px; background:var(--panel); }
  .ttsum { font-size:12px; color:var(--soft); }
  .ttsum b { color:var(--ink); }
  .ttsum svg { display:block; width:100%; height:56px; margin-bottom:4px; }
  .ttsum .bad { color:#c62828; }
</style>
</head>
<body>
<main class="editor">
  <a class="home" href="/{city}/designs.html">← Line designs</a>
  <h1>Line design editor – {title}</h1>
  <p class="note">Start from the baseline or an existing design, then work in two parts: where the
  lines run - their stops, on the map - and when they run - their timetable. Save it under a name:
  keep the name to change that design, or give a new one to keep both. A design is saved as a file
  in <code>designs/{city}/</code>, and saving builds its pages - its maps and timetable. Passengers
  come in a simulation of it.</p>

  <div class="row">
    <label>Start from <select id="start"><option value="">the baseline (no changes)</option></select>
    </label>
  </div>
  <div class="row">
    <label>Save as (file name) <input id="name" placeholder="e.g. trole_every_2min" size="24">
    </label>
    <label>Label <input id="label" placeholder="shown on the results pages" size="36"></label>
  </div>
  <div class="row">
    <label>Description <textarea id="description"
      placeholder="what the design is for (optional)"></textarea></label>
  </div>

  <h2 class="part"><span class="n">1</span>Where the lines run</h2>
  <p class="note">Add a line, or open an existing one to change its stops. With <b>Add stops</b> on,
  click the map to place stops in order - or click an existing stop to stop there too, and
  passengers can change there; with <b>Move stops</b> on, drag a stop; with <b>Shape the
  route</b> on (buses), drag the route itself to make it pass through a point. A line runs out and back or
  round a loop. Out and back, place its outward journey's stops first; its return journey is the
  same stops reversed unless you then give it stops of its own (an avenue each way).
  A stop within <span id="walk"></span> m of another line's stop is joined to it on foot by the
  model. A bus line is matched onto the streets, so a bus stop more than <span id="radius"></span> m
  from a street is flagged - snap it onto the street, or the route is drawn as straight lines.</p>
  <div class="views">
    <span>Existing lines</span>
    <div class="seg" id="view-existing"><button data-v="straight" class="on">stop to stop</button
      ><button data-v="streets">along the streets</button></div>
    <details class="showlines" id="showlines"><summary id="showsummary">Show: all lines ▾</summary>
      <div class="menu"><div class="all"><button data-all="1">all</button
        ><button data-all="0">none</button></div><div id="showlist"></div>
        <p class="showhint">Point at a line to pick it out; with no tool on, click one on the
        map. Zoomed out, the stops are not shown: zoom in for them.</p></div></details>
    <span>Lines on the map</span>
    <div class="seg" id="view-new"><button data-v="straight" class="on">stop to stop</button
      ><button data-v="streets">along the streets</button></div>
  </div>
  <div class="newlines">
    <div id="map"></div>
    <div class="side">
      <select class="open" id="openexisting"></select>
      <div class="tabs" id="tabs"></div>
      <div id="lineform"></div>
    </div>
  </div>

  <h2 class="part" id="timetable-title"><span class="n">2</span>When they run: the timetable</h2>
  <p class="note">Every line of the design, existing, edited and new: whether it runs, its hours,
  how often - with other headways at some hours, the peaks say - and its speed and dwell at a
  stop, which set the time end to end - a bus's along the streets it takes - on weekdays, and on Saturday and Sunday the same timetable,
  one of their own, or no service. The bars are its departures in each hour, one direction. A time
  before the first departure is the next day's.</p>
  <div class="ttfilter">
    <input type="search" id="ttsearch" placeholder="Find a line: its number or name">
    <div class="seg" id="ttshow"><button data-v="all" class="on">All lines</button
      ><button data-v="new">New and edited</button
      ><button data-v="changed">Changed in this design</button></div>
    <span id="ttcount"></span>
  </div>
  <p id="ttnone" hidden>No line matches.</p>
  <div id="timetable"></div>

  <div class="actions">
    <button id="save" class="btn primary">Save design</button>
    <button id="undo" class="btn" disabled title="undo the last change (Ctrl+Z)">↶ Undo</button>
    <span id="message" class="message"></span>
  </div>
  <div id="status"></div>
</main>
<script>
const CITY = "{city}";
const PALETTE = ["#4a3aa7", "#e87ba4", "#eda100", "#1baf7a", "#e34948", "#008300"];
// `base`: the baseline's lines (as /api/lines gives them) and `cur`: each one's timetable in this
// design, and whether it runs. `added`: the lines the design started from added. `newLines`: the
// lines on the map - new ones, and existing ones whose stops are being changed (`existing`).
let base = [], cur = [], net = null, loadedName = "", known = [];
let added = [], newLines = [], current = -1, mode = "off", picked = -1;
let map, newLayer, existingLayer, checkTimer, pathTimer, dirty = false;
let viewExisting = "straight", viewNew = "straight", addedAligned = [], addedStreetKm = {};
// The existing lines hidden from the map (Show: ...), and each baseline line's stops, a layer of
// its own so hiding the line hides them.
const hiddenExisting = new Set(), baseStops = {}, baseStations = {};
// Zoomed out, the existing lines' stops are not shown; from DETAIL_ZOOM they are. A line picked out -
// pointed at in Show, or clicked on the map while not adding, moving or shaping - is drawn bold,
// with its stops however far out, and the others fade.
const DETAIL_ZOOM = 15;
let pickedRoute = null, pointedRoute = null;
function focusRoute() { return pointedRoute || pickedRoute; }
function detailed() { return map.getZoom() >= DETAIL_ZOOM; }
// The way along the streets between two stops, kept per leg: moving or adding a stop asks only
// for the legs it touches, and every other leg keeps the path it has.
const legs = {};

const $ = id => document.getElementById(id);
const fmt = (x, d) => Number(x).toLocaleString(undefined, {maximumFractionDigits: d});
const esc = t => String(t).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;",
                                                     '"': "&quot;", "'": "&#39;"}[c]));

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || response.statusText);
  return body;
}

function km(a, b) {
  const r = Math.PI / 180, dlat = (b[0] - a[0]) * r, dlon = (b[1] - a[1]) * r;
  const h = Math.sin(dlat / 2) ** 2
          + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(dlon / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.sqrt(h));
}

function asStop(t) {
  return Array.isArray(t) ? {name: t[0], lat: t[1], lon: t[2], station: t[3] || "", joins: null,
                             check: null}
                          : Object.assign({}, t, {check: null});
}

// --- a timetable: hours, headway, bands, speed, dwell ------------------------------------------
function defaultHours() { return [net.feed.start, net.feed.end]; }

const DAYS = [["weekday", "Weekdays"], ["saturday", "Saturday"], ["sunday", "Sunday"]];

function dayFrom(v) {
  // A design file's "saturday" / "sunday" (and the server's) as the editor holds it: the
  // weekdays' timetable ("same"), none, or its own.
  if (v === undefined || v === null || v === "same") return {mode: "same"};
  if (v === "none") return {mode: "none"};
  return {mode: "own", headway_min: v.headway_min, hours: (v.hours || defaultHours()).slice(),
          bands: (v.bands || []).map(b => ({from: b.from, to: b.to, headway_min: b.headway_min}))};
}

function copyDay(d) {
  return d.mode === "own" ? {mode: "own", headway_min: d.headway_min, hours: d.hours.slice(),
    bands: d.bands.map(b => Object.assign({}, b))} : {mode: d.mode};
}

// Leg times set by hand. A line on the map keeps them on the stop each leg starts from -
// "min0" outward, "min1" back, like its via points - so they go wherever their stop goes when
// stops are added, moved or reordered. Any other line, whose stops do not change here, by leg
// number: {"journey:leg": minutes}.
function isMapLine(o) { return newLines.includes(o); }

function legMinOf(o) {
  if (!isMapLine(o)) return o.legMin || {};
  const out = {};
  journeysOf(o).forEach((seq, d) => seq.slice(0, -1).forEach((st, k) => {
    if (st["min" + d]) out[`${d}:${k}`] = st["min" + d];
  }));
  return out;
}

function setLegMin(o, d, k, minutes) {
  if (isMapLine(o)) {
    const st = journeysOf(o)[d][k];
    if (minutes) st["min" + d] = minutes; else delete st["min" + d];
  } else {
    o.legMin = Object.assign({}, o.legMin);
    if (minutes) o.legMin[`${d}:${k}`] = minutes; else delete o.legMin[`${d}:${k}`];
  }
}

function applyLegMin(line, legMin) {
  // Leg times by leg number onto a line's stops, as it goes on the map.
  const js = journeysOf(line);
  for (const [key, m] of Object.entries(legMin || {})) {
    const [d, k] = key.split(":").map(Number);
    if (js[d] && js[d][k]) js[d][k]["min" + d] = m;
  }
  line.legMin = {};
  return line;
}

function legMinFrom(o) {
  // Leg times set by hand, as {"journey:leg": minutes} - from the editor's own, or a design
  // file's / the server's [[journey, leg, minutes], ...].
  if (isMapLine(o)) return legMinOf(o);
  if (o.legMin) return Object.assign({}, o.legMin);
  return Object.fromEntries((o.leg_minutes || []).map(([d, k, m]) => [`${d}:${k}`, m]));
}

function service(o) {
  return {headway_min: o.headway_min, speed_kmh: o.speed_kmh, dwell_s: o.dwell_s,
          capacity: o.capacity, legMin: legMinFrom(o),
          hours: (o.hours || defaultHours()).slice(),
          bands: (o.bands || []).map(b => ({from: b.from, to: b.to, headway_min: b.headway_min})),
          days: o.days ? {saturday: copyDay(o.days.saturday), sunday: copyDay(o.days.sunday)}
                       : {saturday: dayFrom(o.saturday), sunday: dayFrom(o.sunday)}};
}

function timetableOf(o, day) {
  // The timetable a line runs on a type of day: the weekdays', its own, or null - no service.
  if (day === "weekday") return o;
  const d = o.days[day];
  if (d.mode === "none") return null;
  return d.mode === "own" ? Object.assign({speed_kmh: o.speed_kmh, dwell_s: o.dwell_s,
                                           legMin: o.legMin}, d) : o;
}

function sameService(a, b) {
  const tt = o => [o.hours, +o.headway_min, o.bands.map(x => [x.from, x.to, +x.headway_min])];
  const legs = o => Object.entries(legMinOf(o)).sort().map(([k, m]) => [k, +m]);
  const key = o => JSON.stringify([+o.speed_kmh, +o.dwell_s, +o.capacity || 0, legs(o), tt(o)].concat(
    ["saturday", "sunday"].map(d => o.days[d].mode === "own" ? tt(o.days[d]) : o.days[d].mode)));
  return key(a) === key(b);
}

function minutesOf(t) { const [h, m] = t.split(":").map(Number); return h * 60 + m; }

function serviceProblem(o) {
  // As the design file reads it: a time before the first departure is the next day's.
  if (!o.hours[0] || !o.hours[1]) return "needs its first departure and its end of service";
  if (!(o.headway_min > 0)) return "needs a headway";
  if (!(o.speed_kmh > 0)) return "needs a speed";
  const start = minutesOf(o.hours[0]);
  const at = t => minutesOf(t) < start ? minutesOf(t) + 1440 : minutesOf(t);
  const end = at(o.hours[1]);
  if (end === start) return "ends its service when it starts it";
  const spans = [];
  for (const b of o.bands) {
    if (!b.from || !b.to || !(b.headway_min > 0)) return "has other hours without a time or a headway";
    const a = at(b.from), z = at(b.to);
    if (z <= a) return `has other hours ending before they start (${b.from} to ${b.to})`;
    if (z > end) return `has other hours (${b.from} to ${b.to}) after its service ends`;
    spans.push([a, z]);
  }
  spans.sort((x, y) => x[0] - y[0]);
  for (let k = 1; k < spans.length; k++)
    if (spans[k][0] < spans[k - 1][1]) return "has two sets of other hours that overlap";
  return "";
}

function departures(o) {
  // Minutes after midnight of every departure, one direction - as frequencies.txt will say.
  if (serviceProblem(o)) return [];
  const start = minutesOf(o.hours[0]);
  const at = t => minutesOf(t) < start ? minutesOf(t) + 1440 : minutesOf(t);
  const end = at(o.hours[1]);
  const bands = o.bands.map(b => [at(b.from), at(b.to), +b.headway_min]);
  const cuts = [...new Set([start, end].concat(bands.flatMap(([a, z]) => [a, z])
    .filter(t => t > start && t < end)))].sort((x, y) => x - y);
  const out = [];
  for (let k = 0; k + 1 < cuts.length; k++) {
    const a = cuts[k], z = cuts[k + 1];
    const band = bands.find(([x, y]) => x <= a && z <= y);
    const h = band ? band[2] : +o.headway_min;
    for (let t = a; t < z - 1e-9; t += h) out.push(t);
  }
  return out;
}

// --- the timetable part: a card per line -----------------------------------------------------
function entries() {
  // Every line of the design in the timetable's order: the baseline's, the started-from
  // design's additions, the new ones. `obj` holds the timetable edited; `state` whether it runs.
  const out = [];
  base.forEach((b, i) => {
    const onMap = newLines.find(l => l.existing && l.route === b.route);
    out.push({key: `b${i}`, kind: "base", i, obj: onMap || cur[i], state: cur[i], onMap,
              route: b.route, name: onMap ? onMap.name : b.name, mode: b.mode,
              color: onMap ? onMap.color : b.color, was: service(b), wasSaid: "baseline",
              streetKm: (net.street_km || {})[b.route],
              journeys: onMap ? journeys(onMap.stops, onMap.back, onMap.loop)
                : journeys(net.lines[i].stops.map(asStop), net.lines[i].stops_back.length
                           ? net.lines[i].stops_back.map(asStop) : null, "")});
  });
  added.forEach((a, j) => {
    if (a.moved) return;
    out.push({key: `a${j}`, kind: "added", j, obj: a, state: a, route: a.route, name: a.name,
              mode: a.mode, color: a.color, was: a.orig, wasSaid: "as designed",
              streetKm: addedStreetKm[a.route],
              journeys: journeys(a.stops.map(asStop), a.stops_back.length
                                 ? a.stops_back.map(asStop) : null, a.loop)});
  });
  newLines.forEach((l, k) => {
    if (l.existing) return;
    out.push({key: `n${k}`, kind: "new", k, obj: l, state: null, onMap: l, route: l.route || "?",
              name: l.name, mode: l.mode, color: l.color, was: null,
              journeys: journeys(l.stops, l.back, l.loop)});
  });
  return out;
}

function journeys(stops, back, loop) {
  // The stop lists a line runs, one per direction - transit/gtfs.py's directions().
  if (loop && stops.length > 2) {
    const ring = stops.concat([stops[0]]);
    return loop === "one_way" ? [ring] : [ring, ring.slice().reverse()];
  }
  return [stops, back || stops.slice().reverse()];
}

function feedKm(a, b) {
  // The feed's distance between two stops (transit/gtfs.py km), so times match it to the second.
  const mid = (a.lat + b.lat) / 2 * Math.PI / 180;
  return Math.hypot((b.lon - a.lon) * 111.32 * Math.cos(mid), (b.lat - a.lat) * 110.57);
}

function legKms(e, d) {
  // Each leg's km of journey `d`, as the feed times it: a bus's along the streets - the legs'
  // own once the server has routed them (lines on the map), else the straight legs scaled to
  // the journey's length along the streets as the design's build measured it; the metro's, and
  // any line not routed yet, the straight line.
  const seq = e.journeys[d];
  const straight = pairs(seq).map(([a, b]) => feedKm(a, b));
  if (!matched({mode: e.mode})) return straight;
  if (e.onMap) {
    const known = pairs(seq).map(([a, b]) => legs[legKey(a, b, viaOf(a, d))]);
    if (known.every(x => x)) return known.map(x => x.km);
  }
  const total = (e.streetKm || [])[d];
  const sum = straight.reduce((x, y) => x + y, 0);
  return total && sum ? straight.map(x => x * total / sum) : straight;
}

function legSeconds(t, stops, kms, d, estimate) {
  // Each leg's running time: set by hand - on its first stop, or by leg number - or its length
  // at the line's speed (at least 30 s). `estimate`: the latter only.
  const out = [];
  for (let k = 1; k < stops.length; k++) {
    const set = estimate ? null : stops[k - 1]["min" + d] || (t.legMin || {})[`${d}:${k - 1}`];
    out.push(set ? Math.max(1, Math.round(set * 60)) : Math.max(30, Math.round(
      (kms ? kms[k - 1] : feedKm(stops[k - 1], stops[k])) / t.speed_kmh * 3600)));
  }
  return out;
}

function runTime(t, stops, kms, d) {
  // Seconds, first stop to last: its legs, and a dwell at every stop between the termini.
  return legSeconds(t, stops, kms, d).reduce((a, b) => a + b, 0)
    + t.dwell_s * Math.max(0, stops.length - 2);
}

function fleet(e, t, loop) {
  // Its round trip, and the vehicles it needs at its shortest headway - transit/fleet.py.
  const runs = e.journeys.map((j, d) => [j, d]).filter(([j]) => j.length > 1)
    .map(([j, d]) => runTime(t, j, legKms(e, d), d));
  if (!runs.length) return null;
  const lay = runs.map(r => Math.max(net.layover.min_s, net.layover.share * r));
  const circulations = loop ? runs.map((r, k) => r + lay[k])
                            : [runs.reduce((a, b) => a + b, 0) + lay.reduce((a, b) => a + b, 0)];
  const shortest = Math.min(t.headway_min, ...t.bands.map(b => +b.headway_min)) * 60;
  return {round: Math.max(...circulations) / 60,
          vehicles: circulations.reduce((n, c) => n + Math.ceil(c / shortest - 1e-9), 0)};
}

function said(o) {
  const tt = t => `every ${fmt(t.headway_min, 2)} min, ${t.hours[0]}–${t.hours[1]}` +
    t.bands.map(b => `; every ${fmt(b.headway_min, 2)} min ${b.from}–${b.to}`).join("");
  return tt(o) + `, ${fmt(o.speed_kmh, 1)} km/h` + ["saturday", "sunday"].map(d =>
    o.days[d].mode === "none" ? `; no service on ${d}` :
    o.days[d].mode === "own" ? `; ${d} ${tt(o.days[d])}` : "").join("");
}

function chart(times) {
  // Departures in each hour, one bar an hour, over the hours the line runs.
  if (!times.length) return "";
  const first = Math.floor(times[0] / 60), last = Math.floor(times[times.length - 1] / 60);
  const counts = {};
  for (const t of times) counts[Math.floor(t / 60)] = (counts[Math.floor(t / 60)] || 0) + 1;
  const most = Math.max(...Object.values(counts));
  const n = last - first + 1, w = 300 / n;
  let bars = "";
  for (let h = first; h <= last; h++) {
    const c = counts[h] || 0, height = 40 * c / most;
    bars += `<rect x="${((h - first) * w + 0.5).toFixed(1)}" y="${(42 - height).toFixed(1)}"
      width="${Math.max(1, w - 1).toFixed(1)}" height="${height.toFixed(1)}" style="fill:var(--c)"
      opacity=".75"><title>${String(h % 24).padStart(2, "0")}:00 - ${c} departures</title></rect>`;
  }
  const label = h => `${String(h % 24).padStart(2, "0")}:00`;
  return `<svg viewBox="0 0 300 56">${bars}
    <text x="0" y="54" font-size="9" fill="currentColor">${label(first)}</text>
    <text x="300" y="54" font-size="9" fill="currentColor" text-anchor="end">${label(last + 1)}</text>
    <text x="150" y="54" font-size="9" fill="currentColor" text-anchor="middle">up to ${most} an hour</text></svg>`;
}

function summary(e, day) {
  const o = timetableOf(e.obj, day);
  if (!o) return `<p class="note">No service on ${day === "saturday" ? "Saturdays" : "Sundays"}.</p>`;
  const wrong = serviceProblem(o);
  if (wrong) return `<span class="bad">⚠ ${esc(e.route)} ${esc(wrong)}.</span>`;
  const times = departures(o);
  const minutes = e.journeys[0].length > 1 ? runTime(o, e.journeys[0], legKms(e, 0), 0) / 60 : 0;
  const fastest = Math.min(o.headway_min, ...o.bands.map(b => +b.headway_min));
  const same = day !== "weekday" && e.obj.days[day].mode === "same" ? "As on weekdays: " : "";
  const loop = e.obj.loop || "";
  const needs = fleet(e, o, loop);
  return chart(times) + `${same}<b>${fmt(60 / o.headway_min, 1)}</b> vehicles an hour${
    fastest < o.headway_min ? `, up to <b>${fmt(60 / fastest, 1)}</b>` : ""} ·
    ${times.length} departures a day each way · about <b>${fmt(minutes, 0)} min</b> end to end${
    matched({mode: e.mode}) ? " (along the streets)" : ""}${needs ? `<br>needs <b>${needs.vehicles} vehicles</b> at its busiest - a round
    trip of ${fmt(needs.round, 0)} min with the layovers` : ""}${e.was && !sameService(e.obj, e.was) ? `<br>${e.wasSaid}: ${esc(said(e.was))}` : ""}`;
}

// Which type of day each card shows: weekdays unless another is picked.
const dayShown = {};

function timetableFields(t, day) {
  // The fields of one day's timetable: its hours, headway and other headways at some hours.
  return `<div class="ttfields">
      <label>First departure <input type="time" data-t="h0" value="${t.hours[0]}"></label>
      <label>Service ends <input type="time" data-t="h1" value="${t.hours[1]}"></label>
      <label>A vehicle every, min <input type="number" min="0.5" step="0.5" data-t="headway_min"
        value="${t.headway_min}"></label>
      ${day === "weekday" ? `<label>Speed, km/h <input type="number" min="1" step="1"
        data-t="speed_kmh" value="${t.speed_kmh}"></label>
      <label>Dwell at a stop, s <input type="number" min="0" step="5" data-t="dwell_s"
        value="${t.dwell_s}"></label>
      <label>Places a vehicle <input type="number" min="1" step="10" data-t="capacity"
        value="${t.capacity || ""}" placeholder="default"></label>` : ""}
    </div>
    <div class="bands">${t.bands.map((b, k) => `<div class="band" data-b="${k}">from
      <input data-t="bf" data-bf="from" type="time" value="${b.from}"> to
      <input data-t="bf" data-bf="to" type="time" value="${b.to}"> every
      <input data-t="bf" data-bf="headway_min" type="number" min="0.5" step="0.5"
        value="${b.headway_min}"> min
      <button data-t="delband" data-k="${k}" title="remove these hours">✕</button></div>`).join("")}
      <button class="small" data-t="band">＋ Another headway at some hours</button></div>`;
}

function legTable(e) {
  // Each journey's legs: the time its length at the line's speed gives, and a field to set it
  // by hand instead - left empty, the estimate is used.
  const o = e.obj;
  const names = e.obj.loop ? ["One way round", "The other way round"] : ["Outward", "Return"];
  const set = Object.keys(legMinOf(o)).length;
  return `<details class="legs" data-key="${e.key}"${openLegs.has(e.key) ? " open" : ""}><summary>Time
    between stops${set ? ` - ${set} set by hand` : ""}</summary>
    <p class="hint">Estimated from each leg's length${matched({mode: e.mode}) ? " along the streets"
      : ""} at the line's speed; type a time to set it instead, empty it to go back to the
      estimate. Dwell at the stops comes on top.</p>
    ${e.journeys.map((seq, d) => {
      if (seq.length < 2) return "";
      const kms = legKms(e, d), est = legSeconds(o, seq, kms, d, true);
      return `<table class="legtimes"><thead><tr><th>${names[d] || "Journey " + (d + 1)}</th>
        <th>km</th><th>estimate, min</th><th>set, min</th></tr></thead><tbody>${
        pairs(seq).map(([a, b], k) => `<tr><td>${esc(a.name)} → ${esc(b.name)}</td>
          <td class="n">${fmt(kms[k], 2)}</td><td class="n est" data-leg="${d}:${k}">${
            fmt(est[k] / 60, 1)}</td>
          <td><input type="number" min="0.1" step="0.1" data-t="legmin" data-leg="${d}:${k}"
            data-est="${(est[k] / 60).toFixed(1)}"
            value="${legMinOf(o)[`${d}:${k}`] ?? ""}" placeholder="${fmt(est[k] / 60, 1)}"></td>
          </tr>`).join("")}</tbody></table>`;
    }).join("")}</details>`;
}

function updateEstimates(e, el) {
  // The legs' estimates after the speed changed: their cells and the empty fields' suggestions,
  // in place - the fields themselves stay, so one being typed in keeps its focus.
  e.journeys.forEach((seq, d) => {
    if (seq.length < 2) return;
    legSeconds(e.obj, seq, legKms(e, d), d, true).forEach((sec, k) => {
      const cell = el.querySelector(`td.est[data-leg="${d}:${k}"]`);
      const input = el.querySelector(`input[data-leg="${d}:${k}"]`);
      if (cell) cell.textContent = fmt(sec / 60, 1);
      if (input) { input.placeholder = fmt(sec / 60, 1); input.dataset.est = (sec / 60).toFixed(1); }
    });
  });
}

// The cards whose "Time between stops" is open, kept open across redraws.
const openLegs = new Set();

function card(e) {
  const o = e.obj, runs = e.state ? e.state.runs : true, day = dayShown[e.key] || "weekday";
  const badge = e.kind === "new" ? (e.obj.fromDesign ? "added by the design started from"
                                                     : "new line")
    : e.onMap ? "stops edited on the map" : e.kind === "added" ? "added by the design started from" : "";
  const changed = e.kind === "new" || e.onMap || (e.was && !sameService(o, e.was));
  const tabs = DAYS.map(([d, label]) => {
    const note = d === "weekday" ? "" : o.days[d].mode === "none" ? " · none"
      : o.days[d].mode === "same" ? " · as weekdays" : " · its own";
    return `<button data-t="tab" data-day="${d}" class="${d === day ? "on" : ""}">${label}${note}</button>`;
  }).join("");
  let body;
  if (day === "weekday") body = timetableFields(o, day) + legTable(e);
  else {
    const d = o.days[day], opt = (v, t) => `<option value="${v}" ${d.mode === v ? "selected" : ""}>${t}</option>`;
    body = `<div class="ttfields"><label>On ${day === "saturday" ? "Saturdays" : "Sundays"}
      <select data-t="daymode">${opt("same", "the weekdays' timetable")}${
        opt("own", "a timetable of its own")}${opt("none", "no service")}</select></label></div>
      ${d.mode === "own" ? timetableFields(d, day) + `<p class="hint">Speed and dwell as on
        weekdays.</p>` : ""}`;
  }
  return `<div class="tt ${runs ? "" : "off"} ${runs && changed ? "changed" : ""}"
      data-key="${e.key}" data-day="${day}" style="--c:${e.color}">
    <div class="tthead"><i class="chip" style="background:${e.color}"></i><b>${esc(e.route)}</b>
      <span class="ttname">${esc(e.name)} · ${esc(e.mode)}</span>
      ${badge ? `<span class="badge">${badge}</span>` : ""}
      <span class="ttright">
        <button class="onmap" data-t="map">${e.onMap ? "show on the map ↑"
          : "✎ its stops on the map ↑"}</button>
        <button class="onmap" data-t="dup" title="a new line, a copy of this one">⧉ duplicate</button>
        ${e.state ? `<label class="runs"><input type="checkbox" data-t="runs" ${runs ? "checked" : ""}>
          runs</label>` : ""}</span></div>
    ${runs ? `<div class="days">${tabs}</div><div class="ttbody"><div>${body}</div>
      <div class="ttsum">${summary(e, day)}</div></div>`
    : `<p class="note" style="margin:6px 0 0">Not running in this design.</p>`}
  </div>`;
}

function drawTimetable() {
  $("timetable").innerHTML = entries().map(card).join("");
  filterTimetable();
}

// Which cards show: those matching the search - a line's number or name, accents and case aside -
// among all lines, the new and edited ones (drawn on the map: new, a design's added, stops
// changed), or every one this design changes (those, and a timetable changed or not running).
let ttShow = "all";
const plain = text => String(text || "").normalize("NFD").replace(/[\\u0300-\\u036f]/g, "")
  .toLowerCase();

function isChanged(e) {
  return e.kind !== "base" || !!e.onMap || (e.was && !sameService(e.obj, e.was))
    || (e.state && e.state.runs === false);
}

function filterTimetable() {
  const words = plain($("ttsearch").value).split(/\\s+/).filter(Boolean);
  const all = entries();
  let shown = 0;
  for (const e of all) {
    const el = document.querySelector(`.tt[data-key="${e.key}"]`);
    if (!el) continue;
    const text = plain(`${e.route} ${e.name}`);
    const show = words.every(w => text.includes(w))
      && (ttShow === "all" || (ttShow === "new" ? e.kind !== "base" || !!e.onMap : isChanged(e)));
    el.style.display = show ? "" : "none";
    shown += show;
  }
  $("ttcount").textContent = shown === all.length ? `${all.length} lines`
    : `${shown} of ${all.length} lines`;
  $("ttnone").hidden = shown > 0 || !all.length;
}

$("ttsearch").addEventListener("input", filterTimetable);
$("ttshow").addEventListener("click", ev => {
  const b = ev.target.closest("button");
  if (!b) return;
  $("ttshow").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
  ttShow = b.dataset.v;
  filterTimetable();
});

function refreshCard(key) {
  // After a field of a card changes: its summary and highlight, never its fields - redrawing
  // those would take a field away while it is being edited.
  const e = entries().find(x => x.key === key);
  const el = document.querySelector(`.tt[data-key="${key}"]`);
  if (!e || !el) return;
  el.querySelector(".ttsum").innerHTML = summary(e, el.dataset.day);
  updateEstimates(e, el);
  el.classList.toggle("changed", e.kind === "new" || !!e.onMap || (e.was && !sameService(e.obj, e.was)));
  if (current >= 0 && newLines[current] === e.obj) $("linefigure").innerHTML = figure(e.obj);
}

$("timetable").addEventListener("change", ev => {
  const el = ev.target.closest(".tt");
  if (!el) return;
  const e = entries().find(x => x.key === el.dataset.key);
  const day = el.dataset.day, t = ev.target.dataset.t;
  // The fields edited: the weekdays' (the line itself) or a weekend day's own timetable.
  const o = day === "weekday" ? e.obj : e.obj.days[day];
  dirty = true;
  if (t === "runs") { e.state.runs = ev.target.checked; drawTimetable(); record(); return; }
  if (t === "daymode") {
    o.mode = ev.target.value;
    if (o.mode === "own" && !o.hours)               // its own starts as the weekdays'
      Object.assign(o, copyDay({mode: "own", headway_min: e.obj.headway_min,
                                hours: e.obj.hours, bands: e.obj.bands}));
    drawTimetable();
    record();
    return;
  }
  if (t === "h0" || t === "h1") o.hours[t === "h0" ? 0 : 1] = ev.target.value;
  else if (t === "bf") {
    const band = o.bands[+ev.target.closest(".band").dataset.b];
    band[ev.target.dataset.bf] = ev.target.type === "number" ? parseFloat(ev.target.value)
                                                             : ev.target.value;
  } else if (t === "legmin") {
    const v = parseFloat(ev.target.value);
    const [d, k] = ev.target.dataset.leg.split(":").map(Number);
    // Back at the estimate is not a time set by hand.
    setLegMin(e.obj, d, k, v > 0 && Math.abs(v - parseFloat(ev.target.dataset.est)) >= 0.05 ? v : 0);
  } else if (t === "capacity") {
    const v = parseInt(ev.target.value, 10);
    if (v > 0) o.capacity = v; else delete o.capacity;
  } else if (t) o[t] = parseFloat(ev.target.value);
  refreshCard(e.key);
  record();
});

// A leg's time left empty steps from its estimate, not from nothing: the arrow keys, or the
// field's own arrows (its right-hand edge), first fill it in with the estimate.
function fromEstimate(input) {
  if (input.dataset.t === "legmin" && input.value === "") input.value = input.dataset.est;
}
$("timetable").addEventListener("keydown", ev => {
  if (ev.key === "ArrowUp" || ev.key === "ArrowDown") fromEstimate(ev.target);
}, true);
$("timetable").addEventListener("mousedown", ev => {
  if (ev.target.dataset && ev.target.dataset.t === "legmin"
      && ev.offsetX > ev.target.clientWidth - 22) fromEstimate(ev.target);
}, true);

$("timetable").addEventListener("toggle", ev => {
  const d = ev.target.closest("details.legs");
  if (d) d.open ? openLegs.add(d.dataset.key) : openLegs.delete(d.dataset.key);
}, true);

$("timetable").addEventListener("click", ev => {
  const b = ev.target.closest("button");
  if (!b) return;
  const el = b.closest(".tt");
  const e = entries().find(x => x.key === el.dataset.key);
  const o = el.dataset.day === "weekday" ? e.obj : e.obj.days[el.dataset.day];
  if (b.dataset.t === "tab") {
    dayShown[e.key] = b.dataset.day;
    drawTimetable();
    return;
  } else if (b.dataset.t === "band") {
    o.bands.push({from: "07:00", to: "09:00", headway_min: o.headway_min});
  } else if (b.dataset.t === "delband") {
    o.bands.splice(+b.dataset.k, 1);
  } else if (b.dataset.t === "map") {
    openOnMap(e);
    return;
  } else if (b.dataset.t === "dup") {
    duplicate(e);
    return;
  } else return;
  dirty = true;
  drawTimetable();
  record();
});

// --- opening a line on the map ----------------------------------------------------------------
function lineFromEntry(e) {
  // A line not on the map yet, as a line on the map: a baseline line as an edit of it, a line
  // the started-from design added as a new line again - with everything it was given.
  let line;
  if (e.kind === "added") {
    const a = added[e.j], c = a.change;
    line = applyVia(Object.assign({existing: false, fromDesign: true, route: a.route,
      name: a.name, mode: a.mode, color: a.color, stops: c.stops.map(asStop),
      back: c.stops_back && !c.loop ? c.stops_back.map(asStop) : null, dir: 0,
      loop: c.loop || ""}, service(a)), c.via);
  } else {
    const n = net.lines[e.i], b = base[e.i];
    line = Object.assign({existing: true, route: b.route, name: b.name, mode: b.mode,
      color: b.color, stops: n.stops.map(asStop),
      back: n.stops_back.length ? n.stops_back.map(asStop) : null, dir: 0, loop: ""},
      service(cur[e.i]));
  }
  return applyLegMin(line, line.legMin);
}

function openOnMap(e) {
  // Its timetable comes along, and stays below.
  let at = newLines.findIndex(l => l.route === e.route);
  if (at < 0) {
    if (e.kind === "added") added[e.j].moved = true;
    newLines.push(lineFromEntry(e));
    at = newLines.length - 1;
  }
  current = at;
  picked = -1;
  setMode("off");
  drawExisting();
  changed();
  $("map").scrollIntoView({behavior: "smooth", block: "center"});
}

function duplicate(e) {
  // A new line, a copy of this one - on the map or not - to start a variant or a similar line
  // from: its stops, route, timetable and all, under a route name of its own.
  const src = e.onMap ? e.obj : lineFromEntry(e);
  const copy = JSON.parse(JSON.stringify(src));
  const taken = new Set(existingLines().map(l => l.route).concat(newLines.map(l => l.route)));
  let route = `${src.route}-B`, n = 2;
  while (taken.has(route)) route = `${src.route}-${String.fromCharCode(65 + n++)}`;
  const used = new Set(existingLines().map(l => l.color).concat(newLines.map(l => l.color)));
  Object.assign(copy, {existing: false, fromDesign: false, route, name: `${src.name} (copy)`,
    color: PALETTE.find(c => !used.has(c)) || copy.color, dir: 0});
  newLines.push(copy);
  current = newLines.length - 1;
  picked = -1;
  setMode("off");
  changed();
  $("map").scrollIntoView({behavior: "smooth", block: "center"});
}

function drawOpenMenu() {
  // The existing lines not on the map yet, to open one there.
  const items = entries().filter(e => e.kind !== "new" && !e.onMap);
  $("openexisting").innerHTML = `<option value="">✎ Change the stops of an existing line…</option>` +
    items.map(e => `<option value="${e.key}">${esc(e.route)} - ${esc(e.name)}</option>`).join("");
}

$("openexisting").addEventListener("change", ev => {
  const e = entries().find(x => x.key === ev.target.value);
  if (e) openOnMap(e);
});

// --- the map ---------------------------------------------------------------------------------
function initMap() {
  map = L.map("map", {zoomSnap: 0.25});
  const esri = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/";
  const attribution = "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors";
  L.tileLayer(esri + "World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
              {maxZoom: 16, attribution}).addTo(map);
  L.tileLayer(esri + "World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
              {maxZoom: 16}).addTo(map);
  // The area the simulation covers: its zones' outline (the study box picks them), else the box.
  const [s, w, n, e] = net.bbox;
  const studyLook = {color: "#5d6873", weight: 1, dashArray: "6 6", fill: false, interactive: false};
  const study = net.area ? L.geoJSON(net.area, {style: () => studyLook}).addTo(map)
    : L.rectangle([[s, w], [n, e]], studyLook).addTo(map);
  map.fitBounds(study.getBounds());
  existingLayer = L.layerGroup().addTo(map);
  for (const line of net.lines) {
    const seen = new Set();
    baseStops[line.route] = L.layerGroup();
    baseStations[line.route] = L.layerGroup();
    for (const t of line.stops.concat(line.stops_back)) {
      const key = t[0] + t[1] + t[2];
      if (seen.has(key)) continue;
      seen.add(key);
      L.circleMarker([t[1], t[2]], {radius: 5, color: line.color, weight: 2, fillColor: "#fff",
                                    fillOpacity: 1, bubblingMouseEvents: false})
        .bindTooltip(`<b>${esc(t[0])}</b><br>${esc(line.route)}` +
                     (t[3] ? `<br>station ${esc(t[3])}` : ""))
        .on("click", () => { if (mode === "add" && current >= 0) addStop(t[0], t[1], t[2], t[3], line.route); })
        .addTo((t[3] ? baseStations : baseStops)[line.route]);
    }
  }
  drawExisting();
  newLayer = L.layerGroup().addTo(map);
  map.on("zoomend", drawExisting);
  map.on("click", e => {
    if (mode === "off" && pickedRoute) { pickedRoute = null; drawExisting(); return; }
    if (mode !== "add" || current < 0) return;
    const line = newLines[current];
    addStop(`Stop ${active(line).length + 1}`, e.latlng.lat, e.latlng.lng, "", null);
  });
}

function existingLines() {
  // The baseline's lines and the started-from design's added ones, as [name, lat, lon, station].
  return net.lines.concat(added.filter(l => !l.moved).map(l => ({route: l.route, color: l.color,
    stops: l.stops, stops_back: l.stops_back || []})));
}

function drawExisting() {
  existingLayer.clearLayers();
  showList();
  const focus = focusRoute(), near = detailed();
  const look = route => !focus ? 1 : route === focus ? 1 : 0.15;
  for (const [route, layer] of Object.entries(baseStops).concat(Object.entries(baseStations))) {
    const show = !hiddenExisting.has(route) && (near || route === focus);
    if (!show) { layer.remove(); continue; }
    if (!map.hasLayer(layer)) layer.addTo(map);
    layer.eachLayer(m => m.setStyle({opacity: look(route), fillOpacity: look(route)}));
  }
  const colors = Object.fromEntries(existingLines().map(l => [l.route, l.color]));
  const streets = viewExisting === "streets";
  // Stop to stop: the way out, and the way back when it has stops of its own.
  const straight = l => [l.stops].concat(l.stops_back.length ? [l.stops_back] : [])
    .map(seq => [l.route, l.color, seq.map(t => [t[1], t[2]])]);
  const lines = streets && net.aligned.length
    ? net.aligned.map(([route, coords]) => [route, colors[route] || "#555", coords])
    : net.lines.flatMap(straight);
  for (const line of added.filter(l => !l.moved)) {
    const along = streets && addedAligned.filter(([route]) => route === line.route);
    if (along && along.length)
      along.forEach(([, coords]) => lines.push([line.route, line.color, coords]));
    else lines.push(...straight(line));
  }
  // A line being edited on the map: what it was, faint and dashed, under its new drawing.
  const onMap = new Set(newLines.filter(l => l.existing).map(l => l.route));
  // The picked line on top; clickable only while not adding, moving or shaping, to pick one.
  const order = lines.filter(([route]) => !hiddenExisting.has(route))
    .sort(([a], [b]) => (a === focus) - (b === focus));
  for (const [route, color, coords] of order) {
    const style = onMap.has(route)
      ? {color, weight: 2, opacity: 0.4, dashArray: "3 6"}
      : {color, weight: route === focus ? 5 : near ? 3 : 2,
         opacity: !focus ? 0.55 : route === focus ? 0.95 : 0.12};
    const pl = L.polyline(coords, Object.assign(style, {interactive: mode === "off",
                                                        bubblingMouseEvents: false}));
    if (mode === "off")
      pl.bindTooltip(`${esc(route)} - click to pick it out`, {sticky: true})
        .on("click", () => { pickedRoute = pickedRoute === route ? null : route; drawExisting(); });
    pl.addTo(existingLayer);
  }
  // The added lines' stops, clickable like the baseline's (drawn once, in initMap).
  for (const line of added.filter(l => !l.moved && !hiddenExisting.has(l.route))) {
    const seen = new Set();
    for (const t of line.stops.concat(line.stops_back)) {
      const key = t[0] + t[1] + t[2];
      if (seen.has(key) || !(near || line.route === focus)) continue;
      seen.add(key);
      L.circleMarker([t[1], t[2]], {radius: 5, color: line.color, weight: 2, fillColor: "#fff",
                                    fillOpacity: look(line.route), opacity: look(line.route),
                                    bubblingMouseEvents: false})
        .bindTooltip(`<b>${esc(t[0])}</b><br>${esc(line.route)}` +
                     (t[3] ? `<br>station ${esc(t[3])}` : ""))
        .on("click", () => { if (mode === "add" && current >= 0) addStop(t[0], t[1], t[2], t[3], line.route); })
        .addTo(existingLayer);
    }
  }
}

// Show: the existing lines as checkboxes, every one shown unless unticked. A line opened on the
// map to change its stops is drawn there whatever this says.
function showList() {
  const lines = existingLines();
  $("showlist").innerHTML = lines.map(l => `<label><input type="checkbox" data-route="${esc(l.route)}"
    ${hiddenExisting.has(l.route) ? "" : "checked"}><i style="background:${l.color}"></i>${esc(l.route)}</label>`)
    .join("");
  const shown = lines.filter(l => !hiddenExisting.has(l.route)).length;
  $("showsummary").textContent = `Show: ${shown === lines.length ? "all " + lines.length
    : shown + " of " + lines.length} lines ▾`;
}

$("showlist").addEventListener("mouseover", e => {
  const box = e.target.closest("label") && e.target.closest("label").querySelector("input[data-route]");
  const route = box ? box.dataset.route : null;
  if (route !== pointedRoute) { pointedRoute = route; drawExisting(); }
});
$("showlist").addEventListener("mouseleave", () => {
  if (pointedRoute) { pointedRoute = null; drawExisting(); }
});
$("showlines").addEventListener("change", e => {
  const box = e.target.closest("input[data-route]");
  if (!box) return;
  if (box.checked) hiddenExisting.delete(box.dataset.route);
  else hiddenExisting.add(box.dataset.route);
  drawExisting();
});
$("showlines").addEventListener("click", e => {
  const b = e.target.closest("button[data-all]");
  if (!b) return;
  hiddenExisting.clear();
  if (b.dataset.all === "0") existingLines().forEach(l => hiddenExisting.add(l.route));
  drawExisting();
});
// Clicking anywhere else closes the list.
document.addEventListener("click", e => {
  if (!e.target.closest("#showlines")) $("showlines").open = false;
});

// A leg's via points: on the stop it starts from, one list per journey - "via0" outward (or
// one way round), "via1" back (or the other way round). They go wherever their stop goes.
function viaOf(stop, d) { return stop["via" + d] || []; }

function legKey(a, b, via) {
  return `${a.lat},${a.lon}>${b.lat},${b.lon}|${(via || []).map(p => p.join(",")).join(";")}`;
}

// The journeys a line runs, as the feed writes them (transit/gtfs.py directions()).
function journeysOf(line) { return journeys(line.stops, line.back, line.loop); }

function shaping(line) { return mode === "shape" && line === newLines[current] && matched(line); }

function drawnJourneys(line) {
  // [direction, stops] drawn: the outward journey always; the return when it has stops or a
  // route of its own, or is the one being shaped.
  return journeysOf(line).map((seq, d) => [d, seq]).filter(([d, seq]) => d === 0 || line.back
    || seq.slice(0, -1).some(st => viaOf(st, d).length) || (shaping(line) && line.shapeDir === 1));
}

// The stop list being edited: the outward stops, or the way back when it has its own.
function active(line) { return line.back && line.dir === 1 ? line.back : line.stops; }

// The stop sequences a line runs, as drawn: out (and back by its own stops), or round its loop.
function runs(line) {
  if (line.loop && line.stops.length > 2) return [line.stops.concat([line.stops[0]])];
  return line.back ? [line.stops, line.back] : [line.stops];
}

function pairs(seq) { return seq.slice(1).map((b, k) => [seq[k], b]); }

function legPoints(line, a, b, d) {
  // A leg as drawn: along the streets once its way is known, else stop - via points - stop.
  const via = viaOf(a, d);
  const leg = along(line) && legs[legKey(a, b, via)];
  return leg ? leg.path : [[a.lat, a.lon]].concat(via, [[b.lat, b.lon]]);
}

function along(line) { return viewNew === "streets" && matched(line) && line.stops.length > 1; }

function shape(line, seq, d) {
  // A bus line along the streets, leg by leg, a leg whose path is not known yet stop to stop -
  // through its via points; a metro - in a tunnel - stop to stop throughout.
  if (seq.length < 2) return seq.map(s => [s.lat, s.lon]);
  const out = [];
  for (const [a, b] of pairs(seq)) {
    const points = legPoints(line, a, b, d);
    out.push(...(out.length ? points.slice(1) : points));
  }
  return out;
}

function streetKm(line, seq, d) {
  // The length along the streets once every leg is known; null until then.
  if (!along(line)) return null;
  let total = 0;
  for (const [a, b] of pairs(seq)) {
    const leg = legs[legKey(a, b, viaOf(a, d))];
    if (!leg) return null;
    total += leg.km;
  }
  return total;
}

// --- shaping the route: dragging it through a point ---------------------------------------
function alongLeg(points, p) {
  // How far along a drawn leg the point nearest `p` is, in degrees-ish: only to order points.
  let best = [Infinity, 0], walked = 0;
  for (let k = 1; k < points.length; k++) {
    const [ay, ax] = points[k - 1], [by, bx] = points[k];
    const dx = bx - ax, dy = by - ay, len2 = dx * dx + dy * dy;
    const t = len2 ? Math.max(0, Math.min(1, ((p.lng - ax) * dx + (p.lat - ay) * dy) / len2)) : 0;
    const qx = ax + t * dx, qy = ay + t * dy;
    const dist = (p.lng - qx) ** 2 + (p.lat - qy) ** 2, len = Math.sqrt(len2);
    if (dist < best[0]) best = [dist, walked + t * len];
    walked += len;
  }
  return best[1];
}

function startDrag(line, d, from, points, e) {
  // Grab the leg from stop `from` at `e`, and drag a new via point from there. It goes in
  // among the leg's via points by where it was grabbed along the leg, so the order is the
  // order along the route, whatever order they were added in.
  L.DomEvent.stop(e);
  const via = viaOf(from, d).slice();
  const at = via.filter(p => alongLeg(points, L.latLng(p[0], p[1])) < alongLeg(points, e.latlng)).length;
  via.splice(at, 0, [e.latlng.lat, e.latlng.lng]);
  const ghost = L.marker(e.latlng, {icon: viaIcon(line, at), interactive: false}).addTo(newLayer);
  const start = map.latLngToContainerPoint(e.latlng);
  let moved = false;
  map.dragging.disable();
  $("map").classList.add("dragging-route");
  const move = ev => {
    if (map.latLngToContainerPoint(ev.latlng).distanceTo(start) > 4) moved = true;
    via[at] = [ev.latlng.lat, ev.latlng.lng];
    ghost.setLatLng(ev.latlng);
  };
  const up = () => {
    map.off("mousemove", move);
    document.removeEventListener("mouseup", up);
    map.dragging.enable();
    $("map").classList.remove("dragging-route");
    if (!moved) { drawNewLines(); return; }             // a click, not a drag: nothing changes
    via[at] = [+via[at][0].toFixed(6), +via[at][1].toFixed(6)];
    from["via" + d] = via;
    changed();
  };
  map.on("mousemove", move);
  document.addEventListener("mouseup", up);
}

function viaIcon(line, k) {
  return L.divIcon({className: "", iconSize: [14, 14], iconAnchor: [7, 7],
    html: `<div class="vianum" style="border-color:${line.color}">${k + 1}</div>`});
}

function drawShaping(line) {
  // The journey being shaped: every leg grabbable, and its via points, numbered in their order.
  const d = line.shapeDir || 0, seq = journeysOf(line)[d];
  if (!seq || seq.length < 2) return;
  for (const [a, b] of pairs(seq)) {
    const points = legPoints(line, a, b, d);
    L.polyline(points, {color: line.color, weight: 16, opacity: 0, bubblingMouseEvents: false})
      .bindTooltip(`${esc(a.name)} → ${esc(b.name)}: drag the route to pass through a point`,
                   {sticky: true})
      .on("mousedown", e => startDrag(line, d, a, points, e))
      .addTo(newLayer);
    viaOf(a, d).forEach((p, k) => {
      L.marker(p, {icon: viaIcon(line, k), draggable: true, zIndexOffset: 900})
        .bindTooltip(`via point ${k + 1} of ${esc(a.name)} → ${esc(b.name)}: drag to move it,
          click to remove it`)
        .on("dragend", ev => {
          const q = ev.target.getLatLng(), list = viaOf(a, d).slice();
          list[k] = [+q.lat.toFixed(6), +q.lng.toFixed(6)];
          a["via" + d] = list;
          changed();
        })
        .on("click", () => {
          a["via" + d] = viaOf(a, d).filter((_, n) => n !== k);
          changed();
        })
        .addTo(newLayer);
    });
  }
}

function drawNewLines() {
  newLayer.clearLayers();
  newLines.forEach((line, i) => {
    drawnJourneys(line).forEach(([d, seq]) => {
      const points = shape(line, seq, d);
      // The return dashed; bold only the journey being edited - or shaped.
      const editing = shaping(line) ? d === (line.shapeDir || 0)
        : (d === 0) === (active(line) === line.stops);
      const on = i === current && editing;
      if (points.length > 1)
        L.polyline(points, {color: line.color, weight: on ? 5 : 3, opacity: on ? 0.95 : 0.45,
                            dashArray: d === 1 ? "8 6" : null, interactive: false})
          .addTo(newLayer);
    });
    // A leg with no way along the streets, marked red over the line.
    for (const [d, a, b] of unrouted(line))
      L.polyline([[a.lat, a.lon]].concat(viaOf(a, d), [[b.lat, b.lon]]),
                 {color: "#c62828", weight: 4, dashArray: "4 6", interactive: true})
        .bindTooltip(`${esc(a.name)} → ${esc(b.name)}: no way along the streets`)
        .addTo(newLayer);
    if (i !== current) return;
    if (shaping(line)) drawShaping(line);
    active(line).forEach((stop, k) => {
      const bad = problem(line, stop);
      const icon = L.divIcon({className: "", iconSize: [22, 22], iconAnchor: [11, 11],
        html: `<div class="stopnum${bad ? " bad" : ""}" style="background:${line.color}">${k + 1}</div>`});
      L.marker([stop.lat, stop.lon], {icon, draggable: mode === "move", zIndexOffset: 1000})
        .bindTooltip(esc(stop.name))
        .on("dragend", e => {
          const p = e.target.getLatLng();
          stop.lat = +p.lat.toFixed(6); stop.lon = +p.lng.toFixed(6); stop.check = null;
          changed();
        })
        .on("click", () => { picked = k; drawForm(); })
        .addTo(newLayer);
    });
  });
}

// --- the lines on the map --------------------------------------------------------------------
function blankLine() {
  const used = new Set(existingLines().map(l => l.color).concat(newLines.map(l => l.color)));
  const taken = new Set(existingLines().map(l => l.route).concat(newLines.map(l => l.route)));
  let n = 1;
  while (taken.has(`N${n}`)) n++;
  return {route: `N${n}`, name: "", mode: "bus", headway_min: 5, speed_kmh: 20, dwell_s: 30,
          capacity: (net.default_capacity || {}).bus, legMin: {},
          color: PALETTE.find(c => !used.has(c)) || PALETTE[0], stops: [],
          back: null, dir: 0, loop: "", hours: defaultHours(), bands: [],
          days: {saturday: {mode: "same"}, sunday: {mode: "same"}}};
}

function addStop(name, lat, lon, station, joins) {
  const line = newLines[current];
  if (joins === line.route) joins = null;            // its own stop, as it was: no change of line
  const list = active(line);
  list.push({name, lat: +(+lat).toFixed(6), lon: +(+lon).toFixed(6), station: station || "",
             joins, check: null});
  picked = list.length - 1;
  changed();
}

function nearestExisting(stop, own) {
  let best = null;
  for (const line of existingLines().filter(l => l.route !== own))
    for (const t of line.stops.concat(line.stops_back || [])) {
      const d = km([stop.lat, stop.lon], [t[1], t[2]]) * 1000;
      if (!best || d < best.m) best = {m: d, name: t[0], route: line.route};
    }
  return best;
}

function insideBox(stop) {
  const [s, w, n, e] = net.bbox;
  return stop.lat >= s && stop.lat <= n && stop.lon >= w && stop.lon <= e;
}

function matched(line) { return net.matched_modes.includes(line.mode); }

function problem(line, stop) {
  if (!insideBox(stop)) return "outside the study area: no streets or zones there";
  if (matched(line) && stop.check && stop.check.metres > net.match_radius_m)
    return `${fmt(stop.check.metres, 0)} m from a street (${esc(stop.check.street || "unnamed")})`;
  if (matched(line) && stop.check && stop.check.cut_off)
    return `on ${esc(stop.check.street || "an unnamed street")}, cut off from the other streets:
      no bus gets in or out - the nearest street it can reach${stop.check.snap_street
      ? ` (${esc(stop.check.snap_street)})` : ""} is ${fmt(stop.check.snap_metres, 0)} m away`;
  return "";
}

function stations() {
  // Every station the design knows: {id: [{name, lat, lon}, ...]} - its platforms, on every line.
  const out = {};
  const add = (id, name, lat, lon) => { if (id) (out[id] = out[id] || []).push({name, lat, lon}); };
  for (const l of existingLines())
    for (const t of l.stops.concat(l.stops_back || [])) add(t[3], t[0], t[1], t[2]);
  for (const l of newLines)
    for (const st of l.stops.concat(l.back || [])) add(st.station, st.name, st.lat, st.lon);
  return out;
}

function stationName(platforms) {
  // A station by the name most of its platforms have.
  const count = {};
  platforms.forEach(p => { count[p.name] = (count[p.name] || 0) + 1; });
  return Object.entries(count).sort((a, b) => b[1] - a[1])[0][0];
}

function stationMenu(line, stop, k) {
  // The stop's station: none, one within reach on foot, or a new one named after it.
  const all = stations(), near = [];
  for (const [id, platforms] of Object.entries(all)) {
    const m = Math.min(...platforms.map(p => km([stop.lat, stop.lon], [p.lat, p.lon]) * 1000));
    if (m <= 300 || id === stop.station) near.push([id, m, stationName(platforms)]);
  }
  near.sort((a, b) => a[1] - b[1]);
  return `<label class="stationpick">Station <select data-station="${k}">
    <option value="">none</option>${near.map(([id, m, name]) => `<option value="${esc(id)}"
      ${id === stop.station ? "selected" : ""}>${esc(name)} (${esc(id)}${m > 1 ? `, ${fmt(m, 0)} m`
      : ""})</option>`).join("")}
    ${stop.station ? "" : `<option value="+new">a new station: ${esc(stop.name)}</option>`}
    </select></label>`;
}

function newStationId(name) {
  const base = "EST_" + (name.toUpperCase().normalize("NFD").replace(/[\\u0300-\\u036f]/g, "")
    .replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "STOP");
  const taken = stations();
  let id = base, n = 2;
  while (taken[id]) id = `${base}_${n++}`;
  return id;
}

function hints(line, stop) {
  const out = [];
  const bad = problem(line, stop);
  if (bad) out.push(`<div class="hint bad">⚠ ${bad}</div>`);
  else if (matched(line) && stop.check)
    out.push(`<div class="hint ok">on ${esc(stop.check.street || "a street")}</div>`);
  if (stop.station) out.push(`<div class="hint">station ${esc(stop.station)}: a change of
    service here</div>`);
  else if (stop.joins) out.push(`<div class="hint">at a ${esc(stop.joins)} stop: passengers
    change here on foot</div>`);
  else {
    const near = nearestExisting(stop, line.route);
    if (near && near.m <= net.transfer_walk_m)
      out.push(`<div class="hint">${fmt(near.m, 0)} m from ${esc(near.name)} (${esc(near.route)}):
        joined on foot</div>`);
  }
  return out.join("");
}

function drawTabs() {
  $("tabs").innerHTML = newLines.map((l, i) =>
    `<button data-i="${i}" class="${i === current ? "on" : ""}"><i class="chip"
      style="background:${l.color}"></i>${l.existing ? "✎ " : ""}${esc(l.route)}</button>`).join("")
    + `<button data-new="1">＋ New line</button>`;
}

function drawForm() {
  drawTabs();
  drawOpenMenu();
  if (current < 0) {
    $("lineform").innerHTML = `<p class="note">${newLines.length ? "Pick a line above."
      : "No line on the map. Add one with ＋ New line, or open an existing one above to change its stops."}</p>`;
    drawNewLines();
    return;
  }
  const line = newLines[current];
  const list = active(line);
  const bad = line.stops.concat(line.back || []).filter(s => problem(line, s)).length;
  const opt = (value, now, text) =>
    `<option value="${value}" ${value === now ? "selected" : ""}>${text}</option>`;
  $("lineform").innerHTML = `
    <div class="form">
      <label>Route (short name) <input data-f="route" value="${esc(line.route)}"
        ${line.existing ? "disabled" : ""}></label>
      <label>Mode <select data-f="mode" ${line.existing ? "disabled" : ""}>${
        (line.existing ? [line.mode] : [...new Set([line.mode, "bus", "metro"])]).map(m =>
        `<option ${m === line.mode ? "selected" : ""}>${m}</option>`).join("")}</select></label>
      ${line.existing ? `<p class="hint wide">An existing line: its stops and way back are this
        design's; its route and mode stay.</p>` : ""}
      <label class="wide">Name <input data-f="name" value="${esc(line.name)}"
        placeholder="e.g. Corredor Oriental (A - B)"></label>
      <label>Colour <input data-f="color" type="color" value="${line.color}"></label>
    </div>
    <h4>Route</h4>
    <div class="form">
      <label class="wide">Shape <select data-f="loop">${opt("", line.loop, "out and back")}${
        opt("one_way", line.loop, "a loop, one way round")}${
        opt("both_ways", line.loop, "a loop, both ways round")}</select></label>
    </div>
    <div class="actions" style="margin:6px 0">
      <button class="btn ${mode === "add" ? "primary" : ""}" data-act="add"
        title="click the map, or an existing stop, to add a stop">Add stops</button>
      <button class="btn ${mode === "move" ? "primary" : ""}" data-act="move"
        title="drag a stop of this line to move it">Move stops</button>
      ${matched(line) ? `<button class="btn ${mode === "shape" ? "primary" : ""}" data-act="shape"
        title="drag the route between two stops to make it pass through a point">Shape the
        route</button>` : ""}
      ${matched(line) && bad ? `<button class="btn" data-act="snap">Snap to the streets</button>` : ""}
      <button class="btn" data-act="dup" title="a new line, a copy of this one">Duplicate</button>
      <button class="btn danger" data-act="delete">${line.existing ? "Stop editing"
        : "Delete line"}</button>
    </div>
    ${shaping(line) ? shapeBox(line) : ""}
    <div class="figure" id="linefigure">${figure(line)}</div>
    <p style="margin:0 0 8px"><button class="small" data-act="tt">Its timetable ↓</button></p>
    ${line.back ? `<div class="dirs"><button data-dir="0" class="${line.dir === 1 ? "" : "on"}">
      Outward journey</button><button data-dir="1" class="${line.dir === 1 ? "on" : ""}">Return
      journey</button></div>` : ""}
    <h5>${line.loop ? "Round the loop" : line.back && line.dir === 1 ? "Return journey"
      : "Outward journey"}</h5>
    <ol class="stops">${list.map((s, k) => `
      <li data-k="${k}" class="${k === picked ? "picked" : ""}">
        <span class="n" style="background:${line.color}">${k + 1}</span>
        <div><input data-s="name" value="${esc(s.name)}">${hints(line, s)}${
          viaHint(line, s, k, list)}${stationMenu(line, s, k)}</div>
        <span class="tools"><button data-move="-1" title="earlier">↑</button>
          <button data-move="1" title="later">↓</button>
          <button data-del="1" title="remove">✕</button></span></li>`).join("")}
    </ol>
    ${line.loop ? "" : returnBox(line)}`;
  drawNewLines();
}

function shapeBox(line) {
  // While shaping: which journey, and how.
  const two = journeysOf(line).length > 1;
  const names = line.loop ? ["One way round", "The other way round"] : ["Outward route", "Return route"];
  const d = line.shapeDir || 0;
  return `<div class="retbox"><b>Shaping the route.</b> Drag the route between two stops and
    drop it where the bus should pass: a via point. Drag a via point to move it, click it to
    remove it. A leg's via points are taken in their order along it - numbered on the map.
    ${along(line) ? "" : "Switch <i>Lines on the map</i> to <i>along the streets</i> to see the streets it takes."}
    ${two ? `<div class="dirs" style="margin-top:6px">${names.map((n, k) => `<button
      data-shape="${k}" class="${d === k ? "on" : ""}">${n}</button>`).join("")}</div>` : ""}</div>`;
}

function viaHint(line, stop, k, list) {
  // The via points of the leg from this stop, in the journey this list is.
  const d = line.back && list === line.back ? 1 : 0;
  const n = viaOf(stop, d).length;
  if (!n || k === list.length - 1 && !line.loop) return "";
  return `<div class="hint">to the next stop through ${n} via point${n > 1 ? "s" : ""}
    <button class="small" data-clearvia="${k}" data-d="${d}">clear</button></div>`;
}

function returnBox(line) {
  // The return journey, decided once the outward one has its stops: the same stops reversed,
  // or stops of its own - which start as the outward ones reversed, to change from there.
  const ends = list => list.length ? `${list.length} stops, ${esc(list[0].name)} → ${
    esc(list[list.length - 1].name)}` : "no stops yet";
  if (!line.back) {
    const ready = line.stops.length >= 2;
    const shaped = line.stops.filter(st => viaOf(st, 1).length).length;
    return `<div class="retbox"><b>Return journey:</b> the same stops, reversed${ready
      ? ` - ${ends(line.stops.slice().reverse())}` : ""}.${shaped ? ` Its route is shaped on
      ${shaped} leg${shaped > 1 ? "s" : ""} <button class="small" data-act="clearvia1">clear</button>`
      : ""}
      <div class="acts"><button class="small" data-act="ownback" ${ready ? "" : "disabled"}>
        Give it its own stops</button></div>
      ${ready ? "" : `<div class="hint">Place the outward stops first.</div>`}</div>`;
  }
  return `<div class="retbox"><b>Return journey:</b> its own stops - ${ends(line.back)}.
    Changes to the outward journey do not carry over to it.
    <div class="acts">${line.dir === 1 ? "" : `<button class="small" data-dir="1">Edit the
      return journey</button>`}<button class="small" data-act="recopy">Start again from the
      outward stops</button><button class="small" data-act="sameback">Use the same stops
      reversed again</button></div></div>`;
}

function figure(line) {
  // The line in numbers: its stops, length, and - with its timetable's speed and dwell - its
  // time end to end.
  const seq = runs(line)[0];
  let length = 0;
  for (let k = 1; k < seq.length; k++)
    length += km([seq[k - 1].lat, seq[k - 1].lon], [seq[k].lat, seq[k].lon]);
  const street = streetKm(line, seq, 0);
  if (street !== null) length = street;
  const e = entries().find(x => x.obj === line);
  const minutes = e && seq.length > 1 ? runTime(line, seq, legKms(e, 0), 0) / 60 : 0;
  const bad = line.stops.concat(line.back || []).filter(s => problem(line, s)).length;
  return `${line.stops.length} stops · ${fmt(length, 1)} km ${street !== null
      ? (line.loop ? "round the loop, along the streets" : "along the streets (outward)")
      : "in a straight line"} ·
      about ${fmt(minutes, 0)} min ${line.loop ? "round" : "end to end"}
      ${bad ? `<br><span class="hint bad">⚠ ${bad} stop${bad > 1 ? "s" : ""} to look at</span>` : ""}
      ${unrouted(line).map(([d, a, b]) => `<br><span class="hint bad">⚠ ${esc(a.name)} → ${
        esc(b.name)}${line.loop || !d ? "" : " (way back)"}: no way along the streets - drawn
        and timed as a straight line. Move a stop, or shape the route through a street</span>`)
        .join("")}`;
}

// The legs the server found no way along the streets for: [journey, from stop, to stop].
function unrouted(line) {
  if (!matched(line)) return [];
  return journeysOf(line).flatMap((seq, d) => pairs(seq)
    .filter(([a, b]) => (legs[legKey(a, b, viaOf(a, d))] || {}).unrouted)
    .map(([a, b]) => [d, a, b]));
}

function setMode(m) {
  mode = m;
  if (existingLayer) drawExisting();                 // its lines clickable only with no mode on
  $("map").classList.toggle("adding", mode === "add");
  $("map").classList.toggle("moving", mode === "move");
  $("map").classList.toggle("shaping", mode === "shape");
}

// Undo: the state after each change - the lines on the map, the timetables, the started-from
// design's lines - and one step back at a time.
let history = [];

function snapshot() { return JSON.stringify({newLines, cur, added, current}); }

function record() {
  const now = snapshot();
  if (history[history.length - 1] !== now) history.push(now);
  if (history.length > 100) history.shift();
  $("undo").disabled = history.length < 2;
}

function fresh() {
  // A design just loaded: nothing to save, nothing to undo.
  dirty = false;
  history = [snapshot()];
  $("undo").disabled = true;
}

function undo() {
  if (history.length < 2) return;
  history.pop();
  const s = JSON.parse(history[history.length - 1]);
  newLines = s.newLines; cur = s.cur; added = s.added; current = s.current;
  if (current < 0 || !newLines[current]) { current = newLines.length ? 0 : -1; setMode("off"); }
  picked = -1;
  dirty = true;
  drawExisting();
  drawForm();
  drawTimetable();
  $("undo").disabled = history.length < 2;
  clearTimeout(pathTimer);
  pathTimer = setTimeout(streetPaths, 300);
}

function redraw() {
  // The panel and the timetable drawn again, and the streets asked for what is new - with
  // nothing changed in the design: no "unsaved changes", no step to undo.
  drawForm();
  drawTimetable();
  clearTimeout(checkTimer);
  checkTimer = setTimeout(checkStreets, 400);
  clearTimeout(pathTimer);
  pathTimer = setTimeout(streetPaths, 500);
}

function editing() {
  // A field of the panel or of the timetable being typed in.
  const el = document.activeElement;
  return !!el && /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)
    && !!(el.closest("#lineform") || el.closest("#timetable"));
}

function redrawWhenFree() {
  // Street paths or checks just in: the map now; the panel and the timetable now too, unless a
  // field of theirs is being typed in - then a moment after it is left, so it is not taken
  // away mid-word (and a button clicked to leave it still gets its click).
  drawNewLines();
  if (!editing()) { drawForm(); drawTimetable(); return; }
  if (current >= 0 && $("linefigure")) $("linefigure").innerHTML = figure(newLines[current]);
  document.activeElement.addEventListener("blur", () => setTimeout(() => {
    if (!editing()) { drawForm(); drawTimetable(); }
  }, 300), {once: true});
}

function changed() {
  dirty = true;
  drawForm();
  drawTimetable();
  record();
  clearTimeout(checkTimer);
  checkTimer = setTimeout(checkStreets, 400);
  clearTimeout(pathTimer);
  pathTimer = setTimeout(streetPaths, 500);
}

async function streetPaths() {
  const missing = new Map();
  for (const line of newLines)
    if (matched(line) && line.stops.length > 1)
      for (const [d, seq] of journeysOf(line).map((q, k) => [k, q]))
        for (const [a, b] of pairs(seq)) {
          const via = viaOf(a, d), key = legKey(a, b, via);
          if (!legs[key]) missing.set(key, [[a.lat, a.lon]].concat(via, [[b.lat, b.lon]]));
        }
  if (!missing.size) return;
  try {
    await Promise.all([...missing].map(async ([k, points]) => {
      legs[k] = await api(`/api/${CITY}/path`, {method: "POST",
        headers: {"Content-Type": "application/json"}, body: JSON.stringify({points})});
    }));
  } catch (e) { say(e.message, true); return; }
  redrawWhenFree();
}

for (const [id, set] of [["view-existing", v => { viewExisting = v; drawExisting(); }],
                         ["view-new", v => { viewNew = v; drawForm(); streetPaths(); }]])
  $(id).addEventListener("click", e => {
    const b = e.target.closest("button");
    if (!b) return;
    $(id).querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
    set(b.dataset.v);
  });

async function checkStreets() {
  if (current < 0) return;
  const line = newLines[current];
  if (!matched(line)) return;
  const todo = line.stops.concat(line.back || []).filter(s => !s.check);
  if (!todo.length) return;
  try {
    const result = await api(`/api/${CITY}/check`, {method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({points: todo.map(s => [s.lat, s.lon])})});
    todo.forEach((s, k) => { s.check = result[k]; });
    redrawWhenFree();
  } catch (e) { say(e.message, true); }
}

$("tabs").addEventListener("click", e => {
  const b = e.target.closest("button");
  if (!b) return;
  picked = -1;
  if (b.dataset.new) {
    newLines.push(blankLine());
    current = newLines.length - 1;
    setMode("add");
    changed();
  } else {
    current = +b.dataset.i;
    redraw();
  }
});

$("lineform").addEventListener("change", e => {
  const line = newLines[current];
  const f = e.target.dataset.f;
  if (f) {
    const before = line[f];
    line[f] = e.target.value.trim();
    if (f === "name" || f === "route" || f === "color") {
      dirty = true;
      drawTabs();
      drawNewLines();
      // Its card's heading only: redrawing every card would take away the field being clicked
      // into next - this change comes as the line's field loses the focus to it.
      const e = entries().find(x => x.obj === line);
      const el = e && document.querySelector(`.tt[data-key="${e.key}"]`);
      if (el) {
        el.style.setProperty("--c", e.color);
        el.querySelector(".tthead .chip").style.background = e.color;
        el.querySelector(".tthead b").textContent = e.route;
        el.querySelector(".tthead .ttname").textContent = `${e.name} · ${e.mode}`;
        filterTimetable();                       // a search may now find it, or not
      } else drawTimetable();
      record();
      return;
    }
    if (f === "mode") {
      const defaults = net.default_capacity || {};
      line.stops.concat(line.back || []).forEach(s => {
        s.check = null;
        if (!matched(line)) { delete s.via0; delete s.via1; }   // no streets to shape it on
      });
      if (!line.capacity || line.capacity === defaults[before])
        line.capacity = defaults[line.mode] || line.capacity;
    }
    if (f === "loop" && line.loop) { line.back = null; line.dir = 0; }   // a loop has no way back
    changed();
  }
  if (e.target.dataset.s) {
    const k = +e.target.closest("li").dataset.k;
    active(line)[k].name = e.target.value.trim();
    dirty = true;
    drawNewLines();
    drawTimetable();
    record();
  }
  if (e.target.dataset.station !== undefined) {
    const stop = active(line)[+e.target.dataset.station];
    stop.station = e.target.value === "+new" ? newStationId(stop.name) : e.target.value;
    stop.joins = null;
    changed();
  }
});

$("lineform").addEventListener("click", e => {
  const b = e.target.closest("button");
  if (!b) return;
  const line = newLines[current];
  const li = b.closest("li");
  if (b.dataset.act === "add" || b.dataset.act === "move" || b.dataset.act === "shape") {
    setMode(mode === b.dataset.act ? "off" : b.dataset.act);    // a second click switches it off
    redraw();
    return;
  } else if (b.dataset.act === "dup") {
    duplicate(entries().find(x => x.obj === line));
    return;
  } else if (b.dataset.act === "tt") {
    const e2 = entries().find(x => x.obj === line);
    const el = e2 && document.querySelector(`.tt[data-key="${e2.key}"]`);
    if (el) el.scrollIntoView({behavior: "smooth", block: "center"});
    return;
  } else if (b.dataset.shape !== undefined) {
    line.shapeDir = +b.dataset.shape;
    redraw();
    return;
  } else if (b.dataset.clearvia !== undefined) {
    const list = +b.dataset.d === 1 && line.back ? line.back : active(line);
    delete list[+b.dataset.clearvia]["via" + b.dataset.d];
  } else if (b.dataset.act === "clearvia1") {
    line.stops.forEach(st => { delete st.via1; });
  } else if (b.dataset.dir !== undefined) {
    line.dir = +b.dataset.dir;
    picked = -1;
    redraw();
    return;
  } else if (b.dataset.act === "ownback" || b.dataset.act === "recopy") {
    if (b.dataset.act === "recopy" && !confirm(`Replace the return journey's stops with the
      outward ones, reversed?`)) return;
    line.back = line.stops.slice().reverse().map(t => {
      const copy = Object.assign({}, t);
      delete copy.via0;
      delete copy.min0;
      return copy;
    });
    line.dir = 1;
    picked = -1;
  } else if (b.dataset.act === "sameback") {
    if (!confirm("Drop the return journey's own stops, and run back by the outward ones reversed?"))
      return;
    line.back = null;
    line.dir = 0;
    picked = -1;
  } else if (b.dataset.act === "snap") {
    line.stops.concat(line.back || []).forEach(s => {
      if (s.check && (s.check.metres > net.match_radius_m || s.check.cut_off)) {
        s.lat = s.check.snap[0]; s.lon = s.check.snap[1];
        s.check = {metres: 0, snap: s.check.snap, street: s.check.snap_street, cut_off: false,
                   snap_metres: 0, snap_street: s.check.snap_street};
      }
    });
  } else if (b.dataset.act === "delete") {
    if (!confirm(line.existing ? `Put the stops of ${line.route} back as they were? Its timetable
      stays as set below.` : `Delete the new line ${line.route}?`)) return;
    if (line.existing) {                         // its timetable stays the design's
      const i = base.findIndex(x => x.route === line.route), n = net.lines[i];
      const svc = service(line);
      const own = JSON.stringify(journeysOf(line).map(j => j.map(st => [st.lat, st.lon])))
        === JSON.stringify(journeys(n.stops.map(asStop), n.stops_back.length
          ? n.stops_back.map(asStop) : null, "").map(j => j.map(st => [st.lat, st.lon])));
      if (!own) svc.legMin = cur[i].legMin || {};
      Object.assign(cur[i], svc);
    }
    newLines.splice(current, 1);
    current = newLines.length ? 0 : -1;
    setMode("off");
    drawExisting();
  } else if (li && b.dataset.move) {
    const list = active(line), k = +li.dataset.k, to = k + +b.dataset.move;
    if (to < 0 || to >= list.length) return;
    [list[k], list[to]] = [list[to], list[k]];
    picked = to;
  } else if (li && b.dataset.del) {
    active(line).splice(+li.dataset.k, 1);
    picked = -1;
  } else return;
  changed();
});

// --- saving: the changes, and what is wrong first --------------------------------------------
function serviceFields(o) {
  const bands = t => t.bands.map(b => ({from: b.from, to: b.to, headway_min: b.headway_min}));
  const out = {headway_min: o.headway_min, speed_kmh: o.speed_kmh, dwell_s: o.dwell_s,
               hours: o.hours};
  if (o.capacity) out.capacity = o.capacity;
  const set = Object.entries(legMinOf(o));
  if (set.length) out.leg_minutes = set.map(([key, m]) => key.split(":").map(Number).concat([m]))
    .sort((x, y) => x[0] - y[0] || x[1] - y[1]);
  if (o.bands.length) out.bands = bands(o);
  for (const day of ["saturday", "sunday"]) {
    const d = o.days[day];
    if (d.mode === "none") out[day] = "none";
    else if (d.mode === "own") {
      out[day] = {headway_min: d.headway_min, hours: d.hours};
      if (d.bands.length) out[day].bands = bands(d);
    }
  }
  return out;
}

function toChange(line) {
  const row = s => [s.name, s.lat, s.lon, s.station];
  const change = Object.assign({type: line.existing ? "edit_line" : "add_line", route: line.route,
                                name: line.name || line.route, mode: line.mode, color: line.color,
                                stops: line.stops.map(row)}, serviceFields(line));
  if (line.existing) delete change.mode;
  if (line.loop) change.loop = line.loop;
  if (line.back) change.stops_back = line.back.map(row);
  // [journey, leg, [[lat, lon], ...]]: the leg from that journey's stop number `leg`.
  const via = [];
  journeysOf(line).forEach((seq, d) => seq.slice(0, -1).forEach((st, k) => {
    if (viaOf(st, d).length) via.push([d, k, viaOf(st, d)]);
  }));
  if (via.length) change.via = via;
  return change;
}

function applyVia(line, via) {
  // A design file's via points onto the line's stops - each on the stop its leg starts from.
  const js = journeysOf(line);
  for (const [d, k, points] of via || [])
    if (js[d] && js[d][k]) js[d][k]["via" + d] = points.map(p => [p[0], p[1]]);
  return line;
}

function problems() {
  const routes = base.map(l => l.route).concat(added.filter(a => !a.moved).map(l => l.route));
  for (const line of newLines) {
    const i = line.existing ? base.findIndex(b => b.route === line.route) : -1;
    if (i >= 0 && !cur[i].runs) continue;                // removed: its stops do not matter
    if (!line.route) return "A new line needs a route name.";
    if (!line.existing) {
      if (routes.includes(line.route)) return `There already is a route called ${line.route}.`;
      routes.push(line.route);
    }
    if (line.stops.length < 2) return `${line.route} needs at least two stops.`;
    if (line.loop && line.stops.length < 3) return `${line.route}, a loop, needs at least three stops.`;
    if (line.back && line.back.length < 2)
      return `${line.route} needs at least two stops on its way back.`;
    const all = line.stops.concat(line.back || []);
    if (all.some(s => !s.name)) return `Every stop of ${line.route} needs a name.`;
    if (all.some(s => !insideBox(s)))
      return `${line.route} has a stop outside the study area.`;
  }
  for (const e of entries()) {
    if (e.state && !e.state.runs) continue;
    for (const [day, label] of DAYS) {
      const t = timetableOf(e.obj, day);
      const wrong = t && serviceProblem(t);
      if (wrong) return `${e.route} ${wrong} (in its timetable, ${label.toLowerCase()}).`;
    }
  }
  return "";
}

function changes() {
  const out = [];
  base.forEach((b, i) => {
    if (!cur[i].runs) { out.push({type: "remove_line", route: b.route}); return; }
    const onMap = newLines.find(l => l.existing && l.route === b.route);
    if (onMap) { out.push(toChange(onMap)); return; }
    if (sameService(cur[i], service(b))) return;
    const change = Object.assign({type: "service", route: b.route}, serviceFields(cur[i]));

    if (cur[i].hours[0] === net.feed.start && cur[i].hours[1] === net.feed.end) delete change.hours;
    out.push(change);
  });
  for (const a of added)                         // moved to the map: a new line again, below
    if (!a.moved && a.runs) {
      // Its timetable as it is now: what the change said of it before is dropped first.
      const change = Object.assign({}, a.change);
      for (const k of ["bands", "saturday", "sunday", "capacity", "leg_minutes"]) delete change[k];
      out.push(Object.assign(change, serviceFields(a)));
    }
  return out.concat(newLines.filter(l => !l.existing).map(toChange));
}

function say(text, error) {
  $("message").textContent = text;
  $("message").className = "message" + (error ? " error" : "");
}

function fileName(text) {
  // "Trolebús cada 2 min" -> "trolebus_cada_2_min": lower case, accents dropped, anything else
  // that cannot be in a file name turned into _.
  return text.toLowerCase().normalize("NFD").replace(/[\\u0300-\\u036f]/g, "")
    .replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60);
}

async function save() {
  say("");
  const name = fileName($("name").value);
  if (!name) {
    say("Give the design a name to save it under (e.g. trole_every_2min).", true);
    $("name").focus();
    return null;
  }
  $("name").value = name;
  const wrong = problems();
  if (wrong) { say(wrong, true); return null; }
  const list = changes();
  if (!list.length) { say("Nothing is changed from the baseline yet.", true); return null; }
  if (name !== loadedName && known.includes(name)
      && !confirm(`A design called ${name} exists. Replace it?`)) return null;
  try {
    const saved = await api(`/api/${CITY}/designs/${name}`, {method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({label: $("label").value, description: $("description").value,
                            changes: list})});
    loadedName = name;
    dirty = false;
    if (!known.includes(name)) {
      known.push(name);
      $("start").insertAdjacentHTML("beforeend", `<option value="${esc(name)}">${
        esc($("label").value || name)} (${esc(name)})</option>`);
    }
    $("start").value = name;
    say(`Saved: ${saved.saved}. Building its pages...`);
    const started = await api(`/api/${CITY}/build/${name}`, {method: "POST"});
    $("save").disabled = true;
    watch(started.job, name);
    return name;
  } catch (e) { say(e.message, true); return null; }
}

async function watch(job, name) {
  // The design's pages build in a few seconds; then its page, or a simulation of it.
  let s;
  try { s = await api(`/api/jobs/${job}`); }
  catch (e) {
    $("save").disabled = false;
    say(`Saved, but the build could not be followed (${e.message}): see the design's page.`, true);
    return;
  }
  if (s.state === "running") { setTimeout(() => watch(job, name), 700); return; }
  $("save").disabled = false;
  if (s.state === "done") {
    say("Saved, and its pages are built.");
    // What the design brought, then - folded away - what the baseline's lines already had.
    const list = ws => `<ul>${ws.map(w => `<li>${esc(w)}</li>`).join("")}</ul>`;
    const old = s.baseline_warnings || [], n = s.warnings.length;
    const look = n || old.length ? `<div class="warnings">${n ? `<b>The build found ${n}
      thing${n > 1 ? "s" : ""} to look at:</b>${list(s.warnings)}`
      : "<b>Nothing to look at in what this design changes.</b>"}${old.length ? `<details><summary>
      ${old.length} more the baseline already has - its lines as they are, not this design's
      doing</summary>${list(old)}</details>` : ""}</div>` : "";
    $("status").innerHTML = `${look}<p><a class="button" href="${s.result}">View the design</a>
      <a class="button" href="/simulate/${CITY}?design=${encodeURIComponent(name)}">Simulate it →</a></p>`;
  } else {
    say("Saved, but building its pages failed: the log is below.", true);
    $("status").innerHTML = `<div class="run"><pre>${s.log.map(esc).join("\\n")}</pre></div>`;
  }
}

// --- loading ---------------------------------------------------------------------------------
function baselineState() {
  cur = base.map(b => Object.assign({runs: true}, service(b)));
}

async function load(name) {
  loadedName = ""; added = []; addedAligned = []; newLines = []; current = -1; picked = -1;
  setMode("off");
  baselineState();
  if (!name) {
    $("name").value = $("label").value = $("description").value = "";
    drawExisting();
    drawForm();
    drawTimetable();
    fresh();
    return;
  }
  try {
    const s = await api(`/api/${CITY}/designs/${name}`);
    $("name").value = loadedName = s.name;
    $("label").value = s.label;
    $("description").value = s.description;
    // The baseline's lines as the design leaves them: their timetable, or not running.
    s.lines.forEach((l, i) => {
      if (l.removed) cur[i].runs = false;
      else Object.assign(cur[i], service(l));
    });
    added = s.kept.filter(c => c.type === "add_line").map(c => {
      const a = Object.assign({change: c, route: c.route, name: c.name || c.route,
        mode: c.mode || "bus", color: c.color || "#555", stops: c.stops, loop: c.loop || "",
        stops_back: c.loop ? [] : (c.stops_back || []), moved: false, runs: true},
        service(Object.assign({dwell_s: 30}, c)));
      a.orig = service(a);
      return a;
    });
    addedAligned = s.aligned || [];
    addedStreetKm = s.street_km || {};
    for (const c of s.edited || []) {
      const i = base.findIndex(b => b.route === c.route);
      if (i < 0) continue;
      newLines.push(applyVia(Object.assign({existing: true, route: c.route,
        name: c.name || base[i].name, mode: base[i].mode, color: c.color || base[i].color,
        stops: c.stops.map(asStop), back: c.stops_back ? c.stops_back.map(asStop) : null, dir: 0,
        loop: c.loop || ""}, service(Object.assign({dwell_s: base[i].dwell_s}, s.lines[i], c))),
        c.via));
      applyLegMin(newLines[newLines.length - 1], newLines[newLines.length - 1].legMin);
    }
    current = newLines.length ? 0 : -1;
    drawExisting();
    changed();
    fresh();
    $("status").innerHTML = "";
    say("");
  } catch (e) { say(e.message, true); }
}

// --- unsaved changes: asked about before they are lost ------------------------------------------
$("start").addEventListener("change", e => {
  if (dirty && !confirm("This design has changes that are not saved. Start from another and lose them?")) {
    e.target.value = loadedName;
    return;
  }
  load(e.target.value);
});
window.addEventListener("beforeunload", e => {
  if (dirty) { e.preventDefault(); e.returnValue = ""; }
});
$("undo").addEventListener("click", undo);
document.addEventListener("keydown", e => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if ((e.ctrlKey || e.metaKey) && e.key === "z" && !e.shiftKey && !typing) {
    e.preventDefault();
    undo();
  }
});
$("save").addEventListener("click", save);

(async () => {
  [base, net] = await Promise.all([api(`/api/${CITY}/lines`), api(`/api/${CITY}/network`)]);
  $("walk").textContent = net.transfer_walk_m;
  $("radius").textContent = net.match_radius_m;
  baselineState();
  initMap();
  const saved = (await api(`/api/${CITY}/designs`)).filter(d => d.name !== "baseline");
  known = saved.map(s => s.name);
  $("start").innerHTML += saved.map(s =>
    `<option value="${esc(s.name)}">${esc(s.label)} (${esc(s.name)})</option>`).join("");
  const params = new URLSearchParams(location.search);
  // ?existing=streets&new=streets opens the map on those views.
  for (const [id, v] of [["view-existing", params.get("existing")], ["view-new", params.get("new")]])
    if (v) $(id).querySelector(`button[data-v="${v}"]`)?.click();
  const wanted = params.get("scenario");
  if (wanted && known.includes(wanted)) { $("start").value = wanted; await load(wanted); }
  else { drawForm(); drawTimetable(); fresh(); }
})();
</script>
</body>
</html>
"""
