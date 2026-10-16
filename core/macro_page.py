"""The Run a macrosimulation page, served by core/server.py at /macro/<city>: a road run built in
steps (core/steps.py), each with its own parameters and computed before the next -

    1  Zones          the city's zones (the default: the baseline's step 1, taken as it is) or a
                      zoning file; the network is the city's as it is - not decided here
    2  Demand         the trip matrix (the city's model, with a summary from people to trips and
                      the gravity model's formula, or an O-D matrix file)
    3  Assignment     the cost function and the convergence (α and β by road class: not yet)
    4  Results        the run's results page

The page shows the parameters a run decides (core/steps.on_page): not step 1's, nor the
reporting factors. Each starts at the city's settings' value (cases/<city>/settings.py) and is
edited in its own shape: a number (its arrows step by its last decimal), true or false, some text,
a list of names (comma-separated), a few numbers side by side, a row per item, a value per key; a
text with a fixed set of values is a choice, or shown when it has one (DETERRENCE). A step's Compute saves the run
(macro_runs/<city>/<name>.json, core/runs.py) and runs `run.py <city> --run <name> --step
<step>`; its preview - numbers, a map, files - shows when it is done. A step is done only for
the values it was computed with: change one of its parameters, or of a step before it, and it
needs computing again before Next.
"""
import html

from .viewer import ICON, STYLE


def page(city):
    return PAGE.replace("{style}", STYLE).replace("{icon}", ICON).replace("{city}", html.escape(city)) \
        .replace("{title}", html.escape(city.title()))


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} macrosimulation</title>
{icon}
<style>
{style}
  body { display:block; }
  .macro { max-width:1100px; padding:28px 32px 60px; }
  .row { display:flex; gap:14px; flex-wrap:wrap; align-items:flex-end; margin:0 0 12px; }
  .row label { display:flex; flex-direction:column; font-size:12px; color:var(--soft); gap:4px; }
  .row input, .row select, .row textarea { font:inherit; color:var(--ink); padding:6px 9px;
      border:1px solid var(--line); border-radius:6px; background:var(--panel); }
  .row select { min-width:340px; }
  .row textarea { width:640px; max-width:100%; min-height:42px; }
  .row .hint { font-size:11px; }
  .param .dict .hint { font-size:12px; color:var(--soft); margin-top:4px; max-width:520px; }
  .stepper { display:flex; gap:0; margin:22px 0 18px; border:1px solid var(--line);
      border-radius:10px; overflow:hidden; background:var(--panel); }
  .stepper button { flex:1; font:inherit; text-align:left; padding:10px 14px; border:0;
      border-right:1px solid var(--line); background:var(--panel); cursor:pointer; color:var(--ink); }
  .stepper button:last-child { border-right:0; }
  .stepper button.on { background:var(--pick); box-shadow:inset 0 -3px 0 var(--accent); }
  .stepper button:disabled { cursor:default; color:var(--soft); }
  .stepper .n { display:inline-flex; width:22px; height:22px; border-radius:50%; align-items:center;
      justify-content:center; font-size:12px; font-weight:700; background:var(--line);
      margin-right:6px; }
  .stepper .done .n { background:#1baf7a; color:#fff; }
  .stepper .t { font-weight:650; font-size:14px; }
  .stepper .s { display:block; font-size:11px; color:var(--soft); margin:3px 0 0 28px; }
  .stepper .stale .s { color:#b45309; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:8px;
      padding:12px 14px; margin:0 0 12px; }
  .card h3 { margin:0 0 8px; font-size:14px; }
  .card label.choice { display:block; font-size:13px; margin:4px 0; }
  .card .file { margin:6px 0 0 22px; font-size:13px; }
  .card .file .about { color:var(--soft); font-size:12px; margin-top:4px; }
  .card .file select { font:inherit; font-size:13px; padding:3px 6px; }
  details.group { background:var(--panel); border:1px solid var(--line); border-radius:8px;
      margin:0 0 10px; }
  details.group > summary { cursor:pointer; padding:10px 14px; font-weight:650; font-size:15px; }
  details.group > summary .count { font-weight:400; font-size:12px; color:var(--soft);
      margin-left:8px; }
  details.group > summary .count b { color:#b45309; }
  details.group.unused { opacity:.55; }
  .param { display:grid; grid-template-columns:220px minmax(0,1fr) 300px; gap:6px 16px;
      padding:9px 14px; border-top:1px solid var(--line); align-items:start; }
  .param.changed { background:#fff8eb; }
  .param.unused { opacity:.5; }
  .param .pn { font-weight:600; font-size:13px; }
  .param .pn code { display:block; font-size:11px; font-weight:400; color:var(--soft);
      background:none; padding:0; }
  .param .pw { font-size:12px; color:var(--soft); }
  .param .pw .unit { color:var(--ink); }
  .param .pw .tag { font-size:10px; text-transform:uppercase; letter-spacing:.04em;
      border:1px solid var(--line); border-radius:4px; padding:0 4px; }
  .param input[type=number], .param input[type=text] { font:inherit; font-size:13px;
      color:var(--ink); padding:4px 7px; border:1px solid var(--line); border-radius:5px;
      background:var(--panel); width:96px; }
  .param input.list { width:100%; }
  .param input.bad { border-color:#c62828; background:#fdf2f2; }
  .param .tuple { display:inline-flex; gap:6px; }
  .param .rows { display:flex; flex-direction:column; gap:4px; }
  .param .dict { display:grid; grid-template-columns:repeat(auto-fill, minmax(170px, 1fr));
      gap:4px 12px; }
  .param .dict label { display:flex; align-items:center; justify-content:space-between; gap:6px;
      font-size:12px; color:var(--soft); }
  .param .was { font-size:11px; color:#b45309; margin-top:4px; }
  .param .was button { font:inherit; font-size:11px; padding:0 7px; margin-left:6px;
      border:1px solid #e5b673; border-radius:10px; background:var(--panel); color:#b45309;
      cursor:pointer; }
  .tools { display:flex; gap:8px; margin:0 0 10px; }
  button.small { font:inherit; font-size:12px; padding:3px 10px; cursor:pointer; border-radius:12px;
      border:1px solid var(--line); background:var(--panel); color:var(--accent); }
  .actions { position:sticky; bottom:0; z-index:5; display:flex; gap:10px; padding:12px 0;
      margin:8px 0 0; align-items:center; flex-wrap:wrap; background:var(--bg);
      border-top:1px solid var(--line); }
  button.btn { font:inherit; padding:8px 16px; border-radius:6px; cursor:pointer;
      border:1px solid var(--accent); background:var(--panel); color:var(--accent); }
  button.btn.primary { background:var(--accent); color:#fff; }
  button.btn:disabled { opacity:.45; cursor:default; }
  .changes { font-size:13px; color:var(--soft); }
  .message { font-size:13px; }
  .message.error { color:#c62828; }
  .job { background:var(--panel); border:1px solid var(--line); border-radius:8px;
      padding:12px 14px; margin:10px 0; }
  .job .step { font-size:13px; color:var(--soft); }
  .job pre { max-height:260px; overflow:auto; border:0; padding:0; background:none; }
  .preview { margin:14px 0 0; }
  .preview h3 { font-size:15px; margin:0 0 8px; }
  .preview table { border-collapse:collapse; font-size:13px; margin:0 0 12px; }
  .preview td { padding:4px 14px 4px 0; border-bottom:1px solid var(--line); vertical-align:top; }
  .preview td:first-child { color:var(--soft); }
  .preview iframe { width:100%; height:520px; border:1px solid var(--line); border-radius:8px;
      background:var(--panel); }
  .preview .files a { font-size:13px; margin-right:12px; }
  .missing { border:1px solid #f0b4b4; background:#fdf2f2; border-radius:6px; padding:8px 12px;
      margin:0 0 12px; font-size:13px; color:#c62828; }
  .sums { border-collapse:collapse; font-size:13px; margin:0 0 10px; }
  .sums td { padding:4px 16px 4px 0; border-bottom:1px solid var(--line); vertical-align:top; }
  .sums td.sv { font-weight:600; text-align:right; white-space:nowrap; }
  .param-section-extra { padding:10px 14px 14px; border-top:1px solid var(--line); }
  .summary h3 { font-size:14px; margin:4px 0 8px; }
  iframe.amap { width:100%; height:440px; border:1px solid var(--line); border-radius:8px; }
  h3.part { font-size:16px; margin:22px 0 4px; }
  h3.part .n { display:inline-flex; min-width:28px; height:22px; padding:0 6px; border-radius:11px;
      background:var(--accent); color:#fff; font-size:12px; align-items:center;
      justify-content:center; margin-right:8px; vertical-align:2px; }
  .partnote { font-size:13px; color:var(--soft); margin:0 0 10px; max-width:900px; }
  .weights { font-size:13px; padding:10px 14px; border-top:1px solid var(--line); background:#f4f8ff; }
  .now { font-size:13px; margin:8px 0 0; padding:6px 10px; background:var(--pick);
      border-radius:6px; }
  .formula { font-family:Georgia, "Times New Roman", serif; font-size:17px; margin:6px 0 8px; }
  .card ul { margin:4px 0 0; padding-left:18px; font-size:13px; color:var(--soft); }
  .card ul b { color:var(--ink); font-weight:600; }
  .param .fixed { font-size:13px; font-weight:600; }
  .param .fixed span { font-weight:400; color:var(--soft); margin-left:6px; }
  .stalenote { border:1px solid #f0d5a8; background:#fff8eb; color:#8a4b00; border-radius:6px;
      padding:7px 11px; font-size:13px; margin:0 0 12px; }
</style>
</head>
<body>
<main class="macro">
  <a class="home" href="/{city}/macro.html">← Macrosimulation</a>
  <h1>Run a macrosimulation – {title}</h1>
  <p class="note">A road run in steps: the zones, the demand, the assignment. Each step has its
  own choices - every parameter starting at the city's settings - and is computed before the next,
  which starts from it. Change a step later and it, and the steps after it,
  are computed again; the steps before it are kept.</p>

  <div class="row">
    <label>Start from <select id="start"></select></label>
    <label>Name (file name: a-z, 0-9, _) <input id="name" placeholder="e.g. car_share_40 (empty: the baseline)" size="30"
      title="lower-case letters, digits and _"></label>
    <label>Label <input id="label" placeholder="shown on the results pages" size="30"></label>
  </div>
  <div class="row">
    <label>Description <textarea id="description" placeholder="what the run is for (optional)"></textarea></label>
  </div>

  <div class="stepper" id="stepper"></div>
  <section id="panel"></section>

  <div class="actions" id="actions">
    <button id="compute" class="btn primary"></button>
    <button id="next" class="btn">Next →</button>
    <span id="changes" class="changes"></span>
    <span id="message" class="message"></span>
  </div>
  <div id="job"></div>
  <div id="preview" class="preview"></div>
</main>
<script>
const CITY = "{city}";
const $ = id => document.getElementById(id);
const esc = t => String(t).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;",
                                                     '"': "&quot;", "'": "&#39;"}[c]));
const NAME = /^[a-z0-9][a-z0-9_]{0,59}$/;
const clone = v => JSON.parse(JSON.stringify(v));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const ABOUT = {
  zones: "The traffic analysis zones: the city's own, or a zoning file of yours. The road network " +
    "is the city's as it is - its speeds, capacities and lanes are not a run's to decide here " +
    "(alternative networks will be scenarios of their own). Computing the step joins the zones " +
    "to it and works out the travel times between every two zones on empty streets.",
  demand: "The trips of the day and hour the run models, zone to zone: the city's model - how many " +
    "trips each zone makes and draws, by car, spread by the gravity model, then turned into the " +
    "day and hour chosen - or an O-D matrix of yours.",
  assignment: "The trips on the network: the cost function (how much slower a road gets as it " +
    "fills), how close the assignment must converge, the checks against observations, and the " +
    "exports and results page."};

// `params`: every parameter (its group and step); `runs`: the saved runs, each with its steps'
// state; `cur`: each parameter's value on the page; `inputs`: the files loaded on the page;
// `saved`: the run as last saved (what its steps' state is about); `bad`: inputs not holding a
// value of their kind.
let params = [], runs = [], STEPS = [], LABELS = {}, cur = {}, bad = new Set();
let inputs = {zoning: null, od_matrix: null}, saved = null, loaded = "baseline", step = 0;
let running = null, CITY_ZONES = {}, CITY_ZONES_READY = false, ATTRACTION_MAP = null;
const closed = new Set();          // the groups closed, "step|group": every other one is open

document.addEventListener("toggle", ev => {
  const d = ev.target;
  if (!d.matches || !d.matches("details.group")) return;
  const key = STEPS[step] + "|" + d.dataset.g;
  if (d.open) closed.delete(key); else closed.add(key);
}, true);

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || response.statusText);
  return body;
}

function say(text, error) {
  $("message").textContent = text;
  $("message").className = "message" + (error ? " error" : "");
}

function title(name) {
  const text = name.toLowerCase().replace(/_/g, " ");
  return text[0].toUpperCase() + text.slice(1);
}

function shown(v) {
  if (Array.isArray(v)) return "(" + v.map(shown).join(", ") + ")";
  if (v && typeof v === "object") return "{" + Object.entries(v).map(([k, x]) => `${k}: ${shown(x)}`)
    .join(", ") + "}";
  return String(v);
}

// --- what the page holds against what was saved and computed -------------------------------------
function changes() {
  const out = {};
  for (const p of params) if (!same(cur[p.name], p.value)) out[p.name] = cur[p.name];
  return out;
}

function runName() {
  const name = $("name").value.trim();
  return name || "baseline";
}

function runNow() { return runs.find(r => r.name === runName()); }

function edited(k) {
  // Step k's values on the page differ from the run as saved - its parameters or its file.
  if (!saved) return true;
  const key = STEPS[k];
  for (const p of params.filter(q => q.step === key)) {
    const was = p.name in saved.parameters ? saved.parameters[p.name] : p.value;
    if (!same(cur[p.name], was)) return true;
  }
  if (key === "zones" && !same(inputs.zoning, saved.zoning || null)) return true;
  if (key === "demand" && !same(inputs.od_matrix, saved.od_matrix || null)) return true;
  return false;
}

function stateOf(k) {
  // "done", "stale" (computed, but with other values) or "missing" - and none is done after a
  // step that is not.
  const run = runNow();
  for (let j = 0; j <= k; j++) {
    const st = run && run.steps && run.steps[STEPS[j]] ? run.steps[STEPS[j]].state : "missing";
    if (st !== "done") return j === k ? st : "missing";
    if (edited(j)) return "stale";
  }
  return "done";
}

// --- the stepper ------------------------------------------------------------------------------------
function drawStepper() {
  const items = STEPS.map((key, k) => {
    const st = stateOf(k);
    const said = st === "done" ? "computed" : st === "stale" ? "needs computing again" : "not computed yet";
    return `<button data-k="${k}" class="${k === step ? "on" : ""} ${st}"><span class="n">${k + 1}</span>
      <span class="t">${esc(LABELS[key])}</span><span class="s">${said}</span></button>`;
  });
  const ready = STEPS.every((_, k) => stateOf(k) === "done");
  items.push(`<button data-k="3" class="${step === 3 ? "on" : ""} ${ready ? "done" : ""}" ${ready ? "" : "disabled"}>
    <span class="n">4</span><span class="t">Results</span><span class="s">${ready ? "ready" : "after step 3"}</span></button>`);
  $("stepper").innerHTML = items.join("");
}

$("stepper").addEventListener("click", ev => {
  const b = ev.target.closest("button[data-k]");
  if (!b || b.disabled) return;
  const k = +b.dataset.k;
  // A step after one not computed cannot be opened: its parameters would mean nothing yet.
  for (let j = 0; j < k && j < 3; j++) if (stateOf(j) !== "done") {
    say(`Compute step ${j + 1} first.`, true); return;
  }
  step = k; draw();
});

// --- one parameter's editor, in its value's shape ---------------------------------------------------
function shownNumber(v, decimal) {
  // A decimal the settings write 1.0 is shown 1.0, not 1 - so its arrows move the decimal.
  return decimal && Number.isInteger(v) ? v.toFixed(1) : String(v);
}

function stepFor(text) {
  // The arrows move a value by its last decimal shown: 0.24 by 0.01, 1.4 by 0.1, 9 by 1.
  if (/e/i.test(text)) return "any";
  const dot = text.indexOf(".");
  return dot < 0 ? "1" : (10 ** -(text.length - dot - 1)).toFixed(text.length - dot - 1);
}

function editor(v, path, fl) {
  // `fl`: the value's shape, true where a number is a decimal (the server's "floats").
  const p = esc(JSON.stringify(path));
  const at = k => (fl && typeof fl === "object" ? fl[k] : false);
  if (typeof v === "boolean") return `<input type="checkbox" data-p="${p}" ${v ? "checked" : ""}>`;
  if (typeof v === "number") {
    const text = shownNumber(v, fl === true);
    return `<input type="number" step="${stepFor(text)}" data-p="${p}" value="${text}">`;
  }
  if (typeof v === "string") return `<input type="text" data-p="${p}" value="${esc(v)}">`;
  if (Array.isArray(v)) {
    if (v.length && v.every(x => typeof x === "string"))
      return `<input type="text" class="list" data-p="${p}" data-list="1" value="${esc(v.join(", "))}"
        title="names, separated by commas">`;
    if (v.every(x => typeof x === "number"))
      return `<span class="tuple">${v.map((x, i) => editor(x, path.concat(i), at(i))).join("")}</span>`;
    return `<div class="rows">${v.map((x, i) => `<div>${editor(x, path.concat(i), at(i))}</div>`).join("")}</div>`;
  }
  if (v && typeof v === "object")
    return `<div class="dict">${Object.entries(v).map(([k, x]) =>
      `<label><span>${esc(k)}</span>${editor(x, path.concat(k), at(k))}</label>`).join("")}</div>`;
  return `<code>${esc(JSON.stringify(v))}</code>`;
}

const CHOICE_SAID = {EXPO: "exp(-β × minutes): the only function available for now"};

function chooser(p) {
  if (!p.choices) return "";
  if (p.choices.length === 1)
    return `<div class="fixed">${esc(p.choices[0])}<span>${esc(CHOICE_SAID[p.choices[0]] || "the only value available")}</span></div>`;
  return `<select data-p="[]">${p.choices.map(c => `<option ${c === cur[p.name] ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>`;
}

// Read only by the check against traffic counts - a weekday's, at 07:00 - which another day or
// hour is not set against (cases/sorocaba/counts.py).
const COUNT_CHECK = ["COUNT_HOUR", "THROUGH_SHARE"];

function unusedParam(p) {
  if (p.step === "demand" && inputs.od_matrix && !TIME_OF_DAY.includes(p.name))
    return "not used: the matrix is loaded";
  if (COUNT_CHECK.includes(p.name) && cur.DAY && !(cur.DAY === "weekday" && cur.PERIOD === "morning peak"))
    return "not used: the traffic counts are a weekday morning's, so another day or hour is not checked against them";
  return "";
}

// How close the assignment converges: the relative gap as a choice, the iterations as a number.
const GAPS = [1e-3, 5e-4, 1e-4, 5e-5, 1e-5];
function gapEditor(v) {
  const gaps = GAPS.includes(v[0]) ? GAPS : GAPS.concat([v[0]]).sort((a, b) => b - a);
  return `<div class="dict"><label><span>relative gap to reach</span><select data-p="[0]" data-num="1">${
    gaps.map(g => `<option value="${g}" ${g === v[0] ? "selected" : ""}>${g.toExponential(0)}${
      g === 1e-4 ? " (recommended)" : ""}</option>`).join("")}</select></label>
    <label><span>iterations at most</span><input type="number" step="10" min="1" data-p="[1]" value="${v[1]}"></label>
    <div class="hint">A smaller gap is a closer equilibrium, and a longer run: 1e-3 is looser than many
    scenarios' effects, 1e-4 makes a change of a fraction of a percent the scenario's, not the solver's.</div></div>`;
}

function row(p) {
  const changed = !same(cur[p.name], p.value), unused = unusedParam(p);
  return `<div class="param${changed ? " changed" : ""}${unused ? " unused" : ""}" data-name="${esc(p.name)}">
    <div class="pn">${esc(title(p.name))}<code>${esc(p.name)}</code></div>
    <div class="pe">${p.name === "RGAP_TARGET_MAX_ITER" ? gapEditor(cur[p.name])
      : chooser(p) || editor(cur[p.name], [], p.floats)}${changed ? `<div class="was">settings: ${esc(shown(p.value))}
      <button data-reset="${esc(p.name)}">↺ back</button></div>` : ""}</div>
    <div class="pw">${unused ? `<div><b>${esc(unused)}</b></div>` : ""}${p.unit ? `<span class="unit">${esc(p.unit)}</span>` : ""}${
      p.kind === "setting" ? ` <span class="tag">method setting</span>`
      : p.why ? `<div>${esc(p.why)}</div>` : ""}</div></div>`;
}

// The demand step in the gravity model's order: what zones make, what they draw, how the trips
// are spread; anything else by its group.
const TIME_OF_DAY = ["DAY", "PERIOD", "PERIOD_SCALE", "WEEKEND_PERIOD_SCALE", "PERIOD_DIRECTION",
                     "WEEKDAY_SIZE", "SATURDAY_SUNDAY"];
const PRODUCTION = ["TRIPS_PER_PERSON", "CAR_SHARE", "OCCUPANCY", "CAR_OWNERSHIP_ELASTICITY"];
const ATTRACTION = ["ATTRACTION_RATES", "HOUSEHOLD_PULL", "WEEKEND_ATTRACTION_RATES",
                    "WEEKEND_HOUSEHOLD_PULL"];

function groupsOf(key) {
  const shown = params.filter(q => q.step === key && q.on_page);
  const out = [];
  if (key === "demand") {
    const take = (name, pick, extra) => {
      // In the order the lists name them: the day and the period first.
      const order = TIME_OF_DAY.concat(PRODUCTION, ATTRACTION);
      const rank = q => (order.includes(q.name) ? order.indexOf(q.name) : order.length);
      const ps = shown.filter(pick).sort((a, b) => rank(a) - rank(b));
      if (ps.length) out.push({name, params: ps, extra});
    };
    // The day's weights only: a weekday's, or a weekend day's.
    const dayWeights = q => (cur.DAY === "weekend") === q.name.startsWith("WEEKEND_");
    take("Trip production", p => PRODUCTION.includes(p.name), "production");
    take("Trip attraction", p => ATTRACTION.includes(p.name) && dayWeights(p), "attraction");
    take("Gravity model settings", p => p.group === "Gravity model parameters", null);
  }
  const placed = q => out.some(g => g.params.includes(q)) || (key === "demand"
    && (TIME_OF_DAY.includes(q.name) || ATTRACTION.includes(q.name)));
  for (const p of shown.filter(q => !placed(q))) {
    let g = out.find(x => x.name === p.group);
    if (!g) out.push(g = {name: p.group, params: [], extra: null});
    g.params.push(p);
  }
  return out;
}

function beforeOf(g) {
  if (g.extra !== "attraction") return "";
  return `<div class="weights">${cur.DAY === "weekend"
    ? "<b>Suggested for a weekend day.</b> Shops, services and leisure pull as hard as on a weekday, " +
      "workplaces and schools much less, and homes more - the visits of a weekend. Edit them if you " +
      "know better; the gravity model finds the β that gives the average trip time below for them."
    : "<b>Suggested for a weekday.</b> Workplaces, schools and services pull the morning's trips; " +
      "homes hardly. Choose a weekend day in 2a for the weekend's weights."}</div>`;
}

function extraOf(g) {
  if (g.extra === "production") return `<div class="param-section-extra" id="dsum">${productionCard()}</div>`;
  if (g.extra === "attraction") return `<div class="param-section-extra">${attractionMap()}</div>`;
  return "";
}

// --- the files a step can load ----------------------------------------------------------------------
function fileCard(key) {
  if (key === "zones") {
    const z = inputs.zoning;
    const own = (CITY_ZONES.lines || []).find(l => l[0] === "zones");
    return `<div class="card"><h3>The zones</h3>
      <label class="choice"><input type="radio" name="zsrc" value="rules" ${z ? "" : "checked"}>
        the city's zones${own ? `: <b>${esc(own[1])}</b>` : ""} - the default, nothing to decide${
        CITY_ZONES_READY ? " (ready: the baseline's, taken as they are)" : ""}</label>
      <label class="choice"><input type="radio" name="zsrc" value="file" ${z ? "checked" : ""}>
        a zoning file: GeoPackage, GeoJSON or zipped Shapefile</label>
      <div class="file" ${z ? "" : "hidden"} id="zfile">
        <input type="file" id="zupload" accept=".gpkg,.geojson,.json,.zip">
        ${z ? `<div class="about"><b>${esc(z.name)}</b>: ${z.zones} zones. Each census sector
          goes to the zone holding its centre, so people and jobs are still the census's; a
          zone's shape follows its sectors.<br>Zone ids from
          <select id="zid"><option value="">their order in the file (1, 2, ...)</option>${
            (z.unique || []).map(c => `<option value="${esc(c)}" ${z.id_column === c ? "selected" : ""}>
              the column ${esc(c)}</option>`).join("")}</select></div>` : ""}
      </div></div>`;
  }
  if (key === "demand") {
    const m = inputs.od_matrix;
    return `<div class="card"><h3>The demand</h3>
      <label class="choice"><input type="radio" name="dsrc" value="model" ${m ? "" : "checked"}>
        the city's model: trip generation and the gravity model (the parameters below)</label>
      <label class="choice"><input type="radio" name="dsrc" value="file" ${m ? "checked" : ""}>
        an O-D matrix file: vehicle trips in the modelled hour - CSV (origin, destination,
        trips) or OMX</label>
      <div class="file" ${m ? "" : "hidden"} id="dfile">
        <input type="file" id="dupload" accept=".csv,.omx">
        <div class="about">Zones are named as in step 1's <a href="${runNow() ? runNow().output : "#"}exports/zone_list.csv"
          target="_blank">zone list</a>: a loaded zoning's ids, the zone codes (Z001...) or the
          zone numbers.</div>
        ${m ? `<div class="about"><b>${esc(m.name)}</b>: ${Math.round(m.trips).toLocaleString()} trips,
          ${m.pairs.toLocaleString()} pairs, ${m.zones} zones named</div>` : ""}
      </div></div>`;
  }
  return "";
}

async function upload(key, input) {
  const file = input.files[0];
  if (!file) return;
  const name = runName();
  if (name === "baseline" || !NAME.test(name)) {
    say("Give the run a name first: a file belongs to a run.", true); input.value = ""; return;
  }
  say(`Reading ${file.name} ...`);
  try {
    const about = await api(`/api/${CITY}/macro/${name}/upload/${key}?filename=${encodeURIComponent(file.name)}`,
                            {method: "POST", body: file});
    inputs[key] = about;
    if (key === "zoning") inputs.zoning.id_column = "";
    say(`${file.name} read.`);
  } catch (e) { say(e.message, true); }
  draw();
}

// --- the demand step's summary: from people to trips, and the gravity model ---------------------------
function fmt(x) { return Math.round(x).toLocaleString(); }

function formulaCard() {
  if (inputs.od_matrix) return `<div class="card"><h3>The demand is loaded</h3><p class="note">
    ${fmt(inputs.od_matrix.trips)} vehicle trips from ${esc(inputs.od_matrix.name)} replace the city's model:
    trip production, attraction and the gravity model below are not used.</p></div>`;
  const v = n => (n in cur ? cur[n] : null);
  const att = "HOUSEHOLD_PULL" in cur ? "its jobs by kind × the attraction rates, plus households × the household pull"
    : "its floor area by use × the attraction rates";
  return `<div class="card"><h3>The gravity model</h3>
    <div class="formula">T<sub>ij</sub> = a<sub>i</sub> O<sub>i</sub> · b<sub>j</sub> D<sub>j</sub> · f(c<sub>ij</sub>),
      &nbsp; f(c) = e<sup>−β c</sup></div>
    <ul><li><b>T<sub>ij</sub></b> car trips from zone i to zone j in the hour</li>
      <li><b>O<sub>i</sub></b> trips zone i makes - <i>trip production</i>: its people × trips per person × car share ÷ occupancy</li>
      <li><b>D<sub>j</sub></b> trips zone j draws - <i>trip attraction</i>: ${att}, scaled so all D add up to all O</li>
      <li><b>a<sub>i</sub>, b<sub>j</sub></b> balancing factors: every zone makes exactly its O and draws exactly its D (doubly constrained)</li>
      <li><b>c<sub>ij</sub></b> minutes between the two zones on empty streets (step 1); a zone to itself, c<sub>ii</sub> =
        ${v("INTRAZONAL_SHARE")} × the time to its nearest zone</li>
      <li><b>f, β</b> the deterrence: β found so the average trip within the city takes ${v("MEAN_TRIP_MIN")} min on empty streets</li></ul></div>`;
}

const HOURS = {"morning peak": "07:00-08:00", "midday": "12:00-13:00", "evening peak": "17:00-18:00",
               "night": "22:00-23:00"};

function todTerms() {
  // s, f and F for the day and period on the page - core/timeofday.terms, the same sums.
  const day = cur.DAY, period = cur.PERIOD;
  if (!day || !period) return null;
  const sat = cur.SATURDAY_SUNDAY || [1, 1];
  const size = day === "weekday" ? cur.WEEKDAY_SIZE : cur.WEEKDAY_SIZE * (sat[0] + sat[1]) / 2;
  const scales = day === "weekday" ? cur.PERIOD_SCALE : cur.WEEKEND_PERIOD_SCALE;
  if (period === "whole day")
    return {s: size, f: 0.5, F: size / Math.max(...Object.values(scales)), size, whole: true};
  return {s: scales[period], f: cur.PERIOD_DIRECTION[period], F: 1, size, whole: false};
}

function said() {
  const day = cur.DAY === "weekday" ? "weekday" : "weekend day";
  return cur.PERIOD === "whole day" ? `${day}, the whole day` : `${day}, ${cur.PERIOD} ${HOURS[cur.PERIOD]}`;
}

function todCard() {
  // 2c's formula and what it gives now - redrawn as the numbers change.
  const t = todTerms();
  if (!t) return "";
  const n = x => (+x).toFixed(2);
  const run = runNow();
  const zones = run && run.steps && run.steps.zones && run.steps.zones.preview || {};
  const people = (zones.values || {}).people;
  const base = people != null && cur.TRIPS_PER_PERSON != null && cur.OCCUPANCY
    ? people * cur.TRIPS_PER_PERSON * cur.CAR_SHARE / cur.OCCUPANCY : null;
  const total = base != null && !inputs.od_matrix
    ? ` ≈ ${fmt(base * t.s)} car trips by the city's residents in ${t.whole ? "the day" : "the hour"}` : "";
  if (t.whole) {
    const sat = cur.SATURDAY_SUNDAY || [1, 1];
    const size = cur.DAY === "weekday" ? `S = ${n(cur.WEEKDAY_SIZE)}`
      : `S = ${n(cur.WEEKDAY_SIZE)} × (${n(sat[0])} + ${n(sat[1])}) / 2 = ${n(t.s)}`;
    return `<div class="formula">T = S · ( B + B<sup>T</sup> ) / 2, &nbsp; against capacity × F</div>
      <ul><li><b>B</b> the morning peak (2b); <b>B<sup>T</sup></b> the same trips turned round, from the
          activity back home: over a whole day every trip out has its trip home</li>
        <li><b>S</b> the day's traffic, counted in morning-peak hours${cur.DAY === "weekend"
          ? ": a weekday's, times the average of Saturday's and Sunday's share of it" : ""}</li>
        <li><b>F</b> = S ÷ the day's busiest hour: capacity is per hour, so the day's trips are assigned as if
          its busiest hour lasted all day</li></ul>
      <div class="now"><b>${esc(said())}</b>: ${size}, F = ${n(t.s)} ÷ ${n(t.s / t.F)} = ${n(t.F)}.${total}</div>`;
  }
  if (t.s === 1 && t.f === 1)
    return `<div class="now"><b>${esc(said())}</b>: the morning peak itself - nothing more to set.${total}</div>`;
  return `<div class="formula">T = s · ( f · B + (1 − f) · B<sup>T</sup> )</div>
    <ul><li><b>B</b> the morning peak (2b), from home to activity; <b>B<sup>T</sup></b> the same trips
        turned round, from the activity back home</li>
      <li><b>f</b> the share of the hour's trips going out, the rest coming back: 1 all out, 0 all home,
        ½ both ways</li>
      <li><b>s</b> the hour's traffic against the weekday morning peak</li></ul>
    <div class="now"><b>${esc(said())}</b>: s = ${n(t.s)}, f = ${n(t.f)} - T = ${n(t.s)} · (${n(t.f)}·B +
      ${n(1 - t.f)}·B<sup>T</sup>).${total}</div>`;
}

function partRow(p, key, label, why) {
  // One value of a parameter that holds one per period: the period chosen's alone.
  const v = cur[p.name][key];
  const fl = p.floats && typeof p.floats === "object" ? p.floats[key] : false;
  const changed = !same(v, p.value[key]);
  return `<div class="param${changed ? " changed" : ""}" data-name="${esc(p.name)}">
    <div class="pn">${esc(label)}<code>${esc(p.name)}["${esc(key)}"]</code></div>
    <div class="pe">${editor(v, [key], fl)}${changed ? `<div class="was">settings: ${esc(shown(p.value[key]))}
      <button data-reset="${esc(p.name)}">↺ back</button></div>` : ""}</div>
    <div class="pw">${esc(why)}</div></div>`;
}

function choiceRows() {
  // 2c's numbers: only those the day and period chosen use.
  const t = todTerms(), P = n => params.find(q => q.name === n);
  if (!t) return "";
  const scales = cur.DAY === "weekday" ? "PERIOD_SCALE" : "WEEKEND_PERIOD_SCALE";
  if (t.whole) {
    const day = cur.DAY === "weekday" ? cur.PERIOD_SCALE : cur.WEEKEND_PERIOD_SCALE;
    const busiest = Object.keys(day).reduce((a, b) => (day[b] > day[a] ? b : a));
    return [row(P("WEEKDAY_SIZE")), cur.DAY === "weekend" ? row(P("SATURDAY_SUNDAY")) : "",
            partRow(P(scales), busiest, `Busiest hour: ${busiest}`,
                    "the day's busiest hour against the weekday morning peak - it sets F")].join("");
  }
  if (t.s === 1 && t.f === 1) return "";
  const period = cur.PERIOD;
  return partRow(P(scales), period, `Size of the ${period} hour (s)`,
                 `the ${cur.DAY === "weekday" ? "weekday" : "weekend day"}'s ${period} hour against the weekday morning peak`)
    + partRow(P("PERIOD_DIRECTION"), period, `Direction of the ${period} hour (f)`,
              "share of its trips going from home to activity; the rest go back home");
}

function productionCard() {
  const run = runNow();
  const zones = run && run.steps && run.steps.zones && run.steps.zones.preview || {};
  const values = zones.values || {};
  const v = n => (n in cur ? cur[n] : null);
  const people = values.people, tpp = v("TRIPS_PER_PERSON"), cs = v("CAR_SHARE"), occ = v("OCCUPANCY");
  const varies = "CAR_OWNERSHIP_ELASTICITY" in cur;
  const rows = [];
  if (people != null) {
    rows.push(["People in the zones (step 1)", fmt(people)]);
    if (tpp != null) rows.push([`× trips per person, ${tpp}`, `${fmt(people * tpp)} person trips in the hour`]);
    if (tpp != null && cs != null && occ)
      rows.push([`× car share ÷ occupancy, ${cs} ÷ ${occ}${varies ? " (the car share varies by zone, around this average)" : ""}`,
                 `${varies ? "≈ " : ""}${fmt(people * tpp * cs / occ)} car trips by the city's residents in the morning peak`]);
    if (values.external) rows.push([`+ ${values.external} external zones`, "trips across the city limit: " +
      "commuting and through traffic (the preview below gives them)"]);
  }
  return `<div class="summary"><h3>From population to trips</h3>
    ${rows.length ? `<table class="sums">${rows.map(([k, x]) => `<tr><td>${esc(k)}</td><td class="sv">${esc(x)}</td></tr>`).join("")}</table>`
      : `<p class="note">Compute step 1 to see the population.</p>`}</div>`;
}

function attractionMap() {
  // The city's map of what attracts trips - its jobs, or its floor area by use - drawn in step 1:
  // the run's own, or for the city's zones the baseline's, which is the same map.
  if (!ATTRACTION_MAP) return "";
  const run = runNow(), base = runs.find(r => r.name === "baseline");
  const from = !inputs.zoning && base ? base.output : run ? run.output : null;
  if (!from) return "";
  return `<div class="summary"><h3>Where the trips are drawn to</h3>
    <iframe class="amap" src="${from}maps/${ATTRACTION_MAP}"></iframe></div>`;
}

// --- the demand step's first and last parts -----------------------------------------------------------
function partA() {
  const P = n => params.find(q => q.name === n);
  return `<h3 class="part"><span class="n">2a</span>When</h3>
    <p class="partnote">A weekday or a weekend day, and an hour of it - or the whole day. Whatever you
    choose, the model first builds the <b>morning peak</b> (2b): the hour it can be checked against,
    and the one every other hour and the whole day are worked out from (2c).</p>
    <div class="card" style="padding:0">${row(P("DAY"))}${row(P("PERIOD"))}</div>`;
}

function partC() {
  return `<h3 class="part"><span class="n">2c</span>From the morning peak to ${esc(said())}</h3>
    <div class="card"><div id="dtod">${todCard()}</div></div>
    <div class="card" style="padding:0">${choiceRows()}</div>`;
}

// --- drawing a step -----------------------------------------------------------------------------------
function draw() {
  drawStepper();
  if (step === 3) { drawResults(); return; }
  const key = STEPS[step];
  const st = stateOf(step);
  const wholeUnused = key === "demand" && inputs.od_matrix;
  $("panel").innerHTML = `<h2 class="section">${step + 1}. ${esc(LABELS[key])}</h2>
    <p class="note">${ABOUT[key]}</p>
    ${st === "stale" ? `<div class="stalenote">Computed with other values than the page has now:
      compute it again before going on.</div>` : ""}
    ${key === "demand" ? partA() : ""}
    ${key === "demand" ? `<h3 class="part"><span class="n">2b</span>The morning peak - the starting point</h3>
      <p class="partnote">One hour of trips from home to activity, the size of a weekday's morning peak:
      the city's model - on a weekend day with the weekend's weights - or a matrix of yours. 2c then
      turns it into what you chose in 2a.</p>` : ""}
    ${fileCard(key)}
    <div class="tools" ${groupsOf(key).length ? "" : `style="display:none"`}><button class="small" data-tool="open">Open every group</button>
      <button class="small" data-tool="close">Close every group</button>
      <button class="small" data-tool="reset">This step back to the settings</button></div>
    ${key === "demand" ? `<div id="dformula">${formulaCard()}</div>` : ""}
    ${key === "assignment" ? `<div class="card"><h3>The assignment</h3>
      <p class="note">Static user equilibrium: every driver takes the quickest route as the roads
      load, until no one could gain by changing - solved by <b>bi-conjugate Frank-Wolfe (BFW)</b>,
      AequilibraE's fastest equilibrium algorithm. How a road slows as it fills is the <b>BPR</b>
      cost function: t = t<sub>0</sub> · (1 + α (V/C)<sup>β</sup>), t<sub>0</sub> its free-flow
      time, V its volume, C its capacity. It stops at the relative gap or the iteration limit below,
      whichever comes first.</p></div>` : ""}
    ${key === "assignment" ? `<div class="missing"><b>Not available yet: α and β by road class.</b>
      The cost function has one α and one β for every road for now; a pair per road class
      (motorways, arterials, local streets...) is still to be built.</div>` : ""}
    ${groupsOf(key).map(g => `<details class="group${wholeUnused ? " unused" : ""}" data-g="${esc(g.name)}"
      ${closed.has(key + "|" + g.name) || wholeUnused ? "" : "open"}>
      <summary>${esc(g.name.replace(/ parameters$/, ""))} <span class="count"></span></summary>
      ${beforeOf(g)}${g.params.map(row).join("")}${extraOf(g)}</details>`).join("")}
    ${key === "demand" ? partC() : ""}`;
  $("actions").style.display = "";
  $("compute").textContent = key === "zones" && !inputs.zoning ? "Use the city's zones →"
    : `▶ Compute step ${step + 1}`;
  $("next").hidden = false;
  $("next").disabled = st !== "done" || !!running;
  $("compute").disabled = !!running;
  counts();
  drawPreview();
}

function counts() {
  const drawn = step < 3 ? groupsOf(STEPS[step]) : [];
  for (const d of document.querySelectorAll("details.group")) {
    const g = (drawn.find(x => x.name === d.dataset.g) || {params: []}).params;
    const n = g.filter(p => !same(cur[p.name], p.value)).length;
    d.querySelector(".count").innerHTML = `${g.length} parameter${g.length !== 1 ? "s" : ""}` +
      (n ? ` · <b>${n} changed</b>` : "");
  }
  const all = Object.keys(changes()).length;
  const here = params.filter(p => p.step === STEPS[step] && p.on_page && !same(cur[p.name], p.value)).length;
  $("changes").textContent = step < 3 ? `${here} change${here !== 1 ? "s" : ""} in this step, ${all} in all` : "";
}

function drawPreview() {
  const run = runNow();
  const key = STEPS[step];
  const st = run && run.steps ? run.steps[key] : null;
  if (!st || !st.preview || stateOf(step) === "missing") { $("preview").innerHTML = ""; return; }
  const p = st.preview;
  $("preview").innerHTML = `<h3>What step ${step + 1} made${stateOf(step) === "stale" ? " (with the earlier values)" : ""}
    <span class="changes">· ${esc(st.finished || "")}, ${st.minutes} min</span></h3>
    <table>${(p.lines || []).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("")}</table>
    ${(p.files || []).length ? `<p class="files">${p.files.map(f => `<a href="${run.output}${f}" target="_blank">${esc(f.split("/").pop())}</a>`).join("")}</p>` : ""}
    ${(p.maps || []).length ? `<iframe src="${run.output}maps/${p.maps[0]}?t=${encodeURIComponent(st.finished || "")}"></iframe>` : ""}`;
}

function drawResults() {
  const run = runNow();
  const st = run && run.steps ? run.steps.assignment : null;
  $("actions").style.display = "none";
  $("preview").innerHTML = "";
  $("panel").innerHTML = `<h2 class="section">4. Results</h2>
    <p class="note">The run's results page: maps, statistics, the parameters it ran with (what it
    changed marked), the tables and the log.</p>
    ${st && st.preview ? `<div class="card"><table class="preview">${(st.preview.lines || []).map(([k, v]) =>
      `<tr><td>${esc(k)}</td><td><b>${esc(v)}</b></td></tr>`).join("")}</table></div>` : ""}
    <p><a class="button" href="${run.output}index.html">Open the results page</a>
      ${run.name !== "baseline" ? `<a class="button" href="/macro/compare_${CITY}.html?a=${CITY}&b=${
        run.output.split("/").filter(Boolean).pop()}">Compare with the baseline</a>` : ""}
      <a class="button" href="/scenario/${CITY}?base=${encodeURIComponent(run.name)}">Create a scenario from this run</a>
      <a class="button" href="/${CITY}/macro.html">All of ${esc(CITY.replace(/^./, c => c.toUpperCase()))}'s runs</a></p>`;
}

// --- editing --------------------------------------------------------------------------------------------
function setAt(value, path, x) {
  if (!path.length) return x;
  const copy = clone(value);
  let at = copy;
  for (const k of path.slice(0, -1)) at = at[k];
  at[path[path.length - 1]] = x;
  return copy;
}

$("panel").addEventListener("input", ev => {
  const input = ev.target.closest("input[data-p], select[data-p]");
  if (!input) return;
  const el = input.closest(".param"), name = el.dataset.name;
  const path = JSON.parse(input.dataset.p);
  let x;
  if (input.type === "checkbox") x = input.checked;
  else if (input.type === "number" || input.dataset.num) x = input.value === "" ? NaN : parseFloat(input.value);
  else if (input.dataset.list) x = input.value.split(",").map(t => t.trim()).filter(Boolean);
  else x = input.value;
  const invalid = (typeof x === "number" && !isFinite(x)) || x === "" || (Array.isArray(x) && !x.length);
  input.classList.toggle("bad", invalid);
  const key = name + input.dataset.p;
  if (invalid) { bad.add(key); return; }
  bad.delete(key);
  cur[name] = setAt(cur[name], path, x);
  const p = params.find(q => q.name === name);
  const changed = !same(cur[name], p.value);
  if (changed !== el.classList.contains("changed")) {
    el.classList.toggle("changed", changed);
    const was = el.querySelector(".was");
    if (changed && !was) el.querySelector(".pe").insertAdjacentHTML("beforeend",
      `<div class="was">settings: ${esc(shown(p.value))} <button data-reset="${esc(name)}">↺ back</button></div>`);
    if (!changed && was) was.remove();
  }
  counts();
  drawStepper();
  $("next").disabled = stateOf(step) !== "done" || !!running;
  if (name === "DAY" || name === "PERIOD") { draw(); return; }
  if ($("dsum")) $("dsum").innerHTML = productionCard();
  if ($("dformula")) $("dformula").innerHTML = formulaCard();
  if ($("dtod")) $("dtod").innerHTML = todCard();
});

$("panel").addEventListener("click", ev => {
  const reset = ev.target.closest("button[data-reset]");
  if (reset) {
    const name = reset.dataset.reset, p = params.find(q => q.name === name);
    cur[name] = clone(p.value);
    for (const key of [...bad]) if (key.startsWith(name + "[")) bad.delete(key);
    reset.closest(".param").outerHTML = row(p);
    counts(); drawStepper();
    $("next").disabled = stateOf(step) !== "done" || !!running;
    return;
  }
  const tool = ev.target.closest("button[data-tool]");
  if (!tool) return;
  if (tool.dataset.tool === "open") document.querySelectorAll("details.group").forEach(d => d.open = true);
  if (tool.dataset.tool === "close") document.querySelectorAll("details.group").forEach(d => d.open = false);
  if (tool.dataset.tool === "reset") {
    for (const p of params.filter(q => q.step === STEPS[step])) cur[p.name] = clone(p.value);
    bad.clear(); draw();
  }
});

$("panel").addEventListener("change", ev => {
  const t = ev.target;
  if (t.name === "zsrc") { if (t.value === "rules") inputs.zoning = null;
    else { $("zfile").hidden = false; return; } draw(); }
  if (t.name === "dsrc") { if (t.value === "model") inputs.od_matrix = null;
    else { $("dfile").hidden = false; return; } draw(); }
  if (t.id === "zupload") upload("zoning", t);
  if (t.id === "dupload") upload("od_matrix", t);
  if (t.id === "zid") { inputs.zoning.id_column = t.value; drawStepper();
    $("next").disabled = stateOf(step) !== "done" || !!running; }
});

// --- computing a step -----------------------------------------------------------------------------------
async function compute() {
  if (bad.size) { say("Some fields do not hold a value of their kind (marked red).", true); return; }
  const name = runName();
  if (!NAME.test(name)) { say("Give the run a name: lower-case letters, digits and _.", true); return; }
  for (const [radio, key, what] of [["zsrc", "zoning", "zoning"], ["dsrc", "od_matrix", "matrix"]])
    if (document.querySelector(`input[name=${radio}][value=file]:checked`) && !inputs[key]) {
      say(`Choose the ${what} file to load, or the city's own.`, true); return;
    }
  const changed = changes();
  if (name === "baseline" && (Object.keys(changed).length || inputs.zoning || inputs.od_matrix)) {
    say("The baseline is the settings as they are: give these changes a name of their own.", true); return;
  }
  // An empty name is the baseline itself: computing any of its steps takes its results off the
  // pages until the assignment is computed again - never without asking.
  if (name === "baseline" && !confirm(`No name given: this computes the baseline's step ${step + 1}
again, and its results leave the pages until its assignment is computed again. To try something,
give the run a name instead. Compute the baseline?`)) return;
  const existing = runs.find(r => r.name === name);
  if (existing && name !== loaded && name !== "baseline"
      && !confirm(`A run named ${name} exists: replace its values with these?`)) return;
  try {
    const answer = await api(`/api/${CITY}/macro/${name}`, {method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({label: $("label").value.trim() || name, description: $("description").value,
                            parameters: changed, zoning: inputs.zoning, od_matrix: inputs.od_matrix,
                            step: STEPS[step]})});
    loaded = name;
    saved = answer.saved;
    await refresh();
    say("");
    running = {job: answer.job, name, step: STEPS[step]};
    draw();
    watch();
  } catch (e) { say(e.message, true); }
}

async function watch() {
  let s;
  try { s = await api(`/api/jobs/${running.job}`); }
  catch (e) { running = null; draw(); say(`The step could not be followed (${e.message}).`, true); return; }
  const lines = s.log.filter(l => /^[A-F][0-9]*b?[.] /.test(l));
  const at = lines.length ? lines[lines.length - 1] : "starting";
  const k = STEPS.indexOf(running.step);
  $("job").innerHTML = `<div class="job"><b>${esc(running.name)} · step ${k + 1}, ${esc(LABELS[running.step])}</b>: ${
    s.state === "running" ? `running, ${Math.floor(s.seconds / 60)} min ${s.seconds % 60} s
      <div class="step">${esc(at)}</div>` :
    s.state === "done" ? `done in ${Math.max(1, Math.round(s.seconds / 60))} min` : "failed"}
    <pre>${s.log.map(esc).join("\\n")}</pre></div>`;
  const pre = $("job").querySelector("pre");
  pre.scrollTop = pre.scrollHeight;
  if (s.state === "running") { setTimeout(watch, 2000); return; }
  const ok = s.state === "done";
  const wasZones = running.step === "zones" && !inputs.zoning;
  running = null;
  await refresh();
  say(ok ? `Step ${k + 1} computed.` : "The step failed: its log is above.", !ok);
  if (ok) $("job").innerHTML = "";
  if (ok && wasZones && step === 0) step = 1;      // the city's zones: nothing to look at first
  draw();
}

// --- starting from a saved run -----------------------------------------------------------------------------
async function refresh() {
  const state = await api(`/api/${CITY}/macro`);
  runs = state.runs.filter(r => !r.base);        // scenarios are the Scenarios page's
  STEPS = state.steps;
  LABELS = state.labels;
  $("start").innerHTML = runs.map(r => {
    const done = STEPS.filter(k => r.steps && r.steps[k] && r.steps[k].state === "done").length;
    return `<option value="${esc(r.name)}">${r.name === "baseline" ? "the baseline (the settings as they are)"
      : `${esc(r.label)} (${esc(r.name)})`} · ${done === 3 ? "computed" : `${done} of 3 steps computed`}${
      r.error ? " · cannot be read" : ""}</option>`;
  }).join("");
  $("start").value = loaded;
  return state;
}

function start(name) {
  const r = runs.find(x => x.name === name);
  if (!r) return;
  if (r.error) { say(`${r.name}: ${r.error}`, true); return; }
  loaded = name;
  saved = clone({parameters: r.parameters, zoning: r.zoning || null, od_matrix: r.od_matrix || null});
  $("start").value = name;
  for (const p of params) cur[p.name] = clone(p.name in r.parameters ? r.parameters[p.name] : p.value);
  inputs = {zoning: r.zoning ? clone(r.zoning) : null, od_matrix: r.od_matrix ? clone(r.od_matrix) : null};
  bad.clear();
  $("name").value = name === "baseline" ? "" : name;
  $("label").value = name === "baseline" ? "" : r.label;
  $("description").value = r.description || "";
  // Open on the first step not computed - or the results, when all are.
  step = 0;
  while (step < 3 && stateOf(step) === "done") step++;
  draw();
  say("");
}

function unsaved() {
  return [0, 1, 2].some(k => edited(k));
}

$("start").addEventListener("change", () => {
  if (unsaved() && !confirm("Start from this run instead? The changes on the page are lost.")) {
    $("start").value = loaded; return;
  }
  start($("start").value);
});
$("name").addEventListener("input", () => {
  // Another name is another run: its steps' state is that run's, if it exists.
  const r = runNow();
  if (r) saved = clone({parameters: r.parameters, zoning: r.zoning || null, od_matrix: r.od_matrix || null});
  else saved = null;
  drawStepper();
  if (step < 3) $("next").disabled = stateOf(step) !== "done" || !!running;
});
$("compute").addEventListener("click", compute);
$("next").addEventListener("click", () => { if (stateOf(step) === "done") { step++; draw(); } });

(async () => {
  const state = await refresh();
  params = state.parameters;
  CITY_ZONES = state.city_zones || {};
  CITY_ZONES_READY = !!state.city_zones_ready;
  ATTRACTION_MAP = state.attraction_map || null;
  for (const p of params) cur[p.name] = clone(p.value);
  const wanted = new URLSearchParams(location.search).get("run");
  start(wanted && runs.some(r => r.name === wanted) ? wanted : "baseline");
  if (state.running && state.running.city === CITY) {     // a step going: follow it
    running = {job: state.running.job, name: state.running.name, step: state.running.step};
    draw();
    watch();
  }
})();
</script>
</body>
</html>
"""
