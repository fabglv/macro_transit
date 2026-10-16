"""The simulation page, served by core/server.py at /simulate/<city>, in steps as the
macrosimulation's: 1 the zones (the road model's), 2 the demand (a uniform matrix of N trips - a
demand model for public transport is not implemented), 3 the assignment (optimal strategies, and
the graph's parameters it runs on: the day, the period, the walking, the transfer penalty, the
wait, the walk to a stop - transit/options.py), 4 the results. It runs `run.py <city> --transit --design
<name> [--day ...]`.

Nothing here edits a design; that is the line design editor's (editor_page.py).
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
<title>{title} simulation</title>
{icon}
<style>
{style}
  body { display:block; }
  .simulate { max-width:1000px; padding:28px 32px 60px; }
  .row { display:flex; gap:14px; flex-wrap:wrap; align-items:flex-end; margin:0 0 14px; }
  .row label { display:flex; flex-direction:column; font-size:12px; color:var(--soft); gap:4px; }
  .row select { font:inherit; padding:6px 9px; border:1px solid var(--line); border-radius:6px;
      background:var(--panel); min-width:360px; }
  .about { font-size:13px; margin:0 0 14px; }
  .actions { display:flex; gap:10px; margin:18px 0; align-items:center; flex-wrap:wrap; }
  button.btn { font:inherit; padding:8px 16px; border-radius:6px; cursor:pointer;
      border:1px solid var(--accent); background:var(--accent); color:#fff; }
  button.btn:disabled { opacity:.5; cursor:default; }
  .message { font-size:13px; }
  .message.error { color:#c62828; }
  .run { background:var(--panel); border:1px solid var(--line); border-radius:8px;
      padding:12px 14px; margin-top:6px; }
  .run pre { max-height:360px; overflow:auto; border:0; padding:0; background:none; }
  .opts { display:grid; grid-template-columns:repeat(auto-fill, minmax(190px, 1fr)); gap:12px 16px;
      max-width:900px; margin:0 0 10px; }
  .opts label { display:flex; flex-direction:column; font-size:12px; color:var(--soft); gap:4px; }
  .opts input, .opts select { font:inherit; color:var(--ink); padding:6px 9px; background:var(--panel);
      border:1px solid var(--line); border-radius:6px; }
  .opts .hint { font-size:11px; color:var(--soft); }
  .demand-note { font-size:13px; max-width:900px; margin:0 0 10px; }
  .plan { font-size:13px; margin:6px 0 0; }
  .plan code { font-size:12px; }
  button.small { font:inherit; font-size:12px; padding:3px 10px; cursor:pointer; border-radius:12px;
      border:1px solid var(--line); background:var(--panel); color:var(--accent); }
  .missing { border:1px solid #f0b4b4; background:#fdf2f2; border-radius:6px; max-width:900px;
      padding:8px 12px; margin:0 0 12px; font-size:13px; color:#c62828; }
  .missing b { display:block; margin-bottom:3px; }
  .missing li b { display:inline; }
  .missing ul { margin:0; padding-left:18px; }
  .step { border-top:1px solid var(--line); padding:6px 0 4px; margin:12px 0 0; max-width:960px; }
  .step h2 { display:flex; align-items:center; gap:10px; font-size:18px; margin:10px 0 8px; }
  .step h2 .n { display:inline-flex; width:26px; height:26px; border-radius:50%; background:var(--accent);
                color:#fff; font-size:14px; align-items:center; justify-content:center; }
  .zones b { font-weight:600; }
  .slider { display:flex; align-items:flex-end; gap:12px; flex-wrap:wrap; }
  .slider label { display:flex; flex-direction:column; font-size:12px; color:var(--soft); gap:4px; }
  .slider input[type=range] { width:360px; }
  .slider input[type=number] { width:110px; font:inherit; padding:6px 9px; border:1px solid var(--line);
                                border-radius:6px; background:var(--panel); }
  .slider .hint { font-size:12px; color:var(--soft); }
</style>
</head>
<body>
<main class="simulate">
  <a class="home" href="/{city}/simulations.html">← Simulations</a>
  <h1>Run a simulation – {title}</h1>
  <p class="note">Choose a design and assign passengers to its lines, in steps as a
  macrosimulation's: the zones, the demand, the assignment, the results.</p>

  <div class="row"><label>Design <select id="design"></select></label></div>
  <div id="about" class="about"></div>

  <section class="step"><h2><span class="n">1</span>Zones</h2>
    <p class="note">The city's own zones - the road model's, built from the city's data (census
    sectors, people, jobs), no road simulation needed - those whose middle is inside the study box
    the lines run in.</p>
    <div id="zones"></div>
  </section>

  <section class="step"><h2><span class="n">2</span>Demand</h2>
    <div class="missing"><b>Not implemented yet: a demand model for public transport.</b>
      The road model's matrices cannot be recycled: they come from a gravity model whose
      deterrence is the car's free-flow travel time, where public transport's would be its own
      impedance - the walk, the wait, the ride, the transfers. So the demand is a uniform matrix:
      the trips below, shared evenly among every pair of zones.</div>
    <div class="slider">
      <label>Trips in the period <input id="trips" type="range" min="1000" max="200000" step="1000"></label>
      <input id="tripsn" type="number" min="1000" step="1000">
      <span class="hint" id="perpair"></span>
    </div>
  </section>

  <section class="step"><h2><span class="n">3</span>Assignment</h2>
    <p class="note">Passengers choose by <b>optimal strategies</b> (Spiess &amp; Florian, 1989): at
    each stop, the set of lines that gets them there soonest on average, boarding whichever comes
    first. The method has no parameter of its own; what shapes it is the transit graph it runs on -
    these. The time a vehicle stands at a stop is each line's, set in its design: its timetable's
    and its passengers'. Left at their defaults the simulation is the design's; anything else is in its name,
    so it sits beside the default one.</p>
    <div class="opts">
      <label>Day <select id="day"></select><span class="hint" id="date"></span></label>
      <label>From <select id="from"></select></label>
      <label>To <select id="to"></select><span class="hint">the period simulated</span></label>
      <label>Walk to a stop up to, m <input id="access" type="number" min="0" max="3000" step="50">
        <span class="hint">from a zone's middle, in a straight line</span></label>
      <label>Walking speed, m/s <input id="walk" type="number" min="0.3" max="3" step="0.1"></label>
      <label>Transfers on foot up to, m <input id="transfer" type="number" min="0" max="2000"
        step="50"><span class="hint">stops this close are joined</span></label>
      <label>Transfer penalty, s <input id="penalty" type="number" min="0" max="3600" step="30">
        <span class="hint" id="penaltymin">added at each change of vehicle</span></label>
      <label>Wait, share of the headway <input id="waitf" type="number" min="0.1" max="1" step="0.1">
        <span class="hint">0.5: half the headway, for services that keep their timetable</span></label>
    </div>
    <p class="plan"><button class="small" id="reset">Reset to the defaults</button></p>
    <div class="plan" id="plan"></div>
    <div class="actions">
      <button id="run" class="btn">▶ Run the simulation</button>
      <span id="message" class="message"></span>
    </div>
  </section>

  <section class="step"><h2><span class="n">4</span>Results</h2>
    <div id="status"><p class="note">Run the simulation: its log comes here, then its results.</p></div>
    <p class="note"><a href="/transit/simulations/compare_{city}.html">Compare simulations →</a></p>
  </section>
</main>
<script>
const CITY = "{city}";
let designs = [];
const $ = id => document.getElementById(id);
const esc = t => String(t).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;",
                                                     '"': "&quot;", "'": "&#39;"}[c]));

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

function about() {
  const d = designs.find(x => x.name === $("design").value);
  if (!d) return;
  $("about").innerHTML = d.design ? `See <a href="${d.design}">its design page</a> for its lines,
    timetable and what it takes to run.` : "";
  plan();
}

function options() {
  return {day: $("day").value, period: [+$("from").value, +$("to").value],
          trips: parseFloat($("tripsn").value), walking_speed: parseFloat($("walk").value),
          transfer_walk_m: parseFloat($("transfer").value),
          transfer_penalty_s: parseFloat($("penalty").value), wait_factor: parseFloat($("waitf").value),
          access_m: parseFloat($("access").value)};
}

function describe() {
  const day = A.days.find(d => d.day === $("day").value);
  $("date").textContent = `the feed's service on ${day.date}`;
  // The uniform matrix: the trips over every pair of different zones.
  const n = A.zones && A.zones.ready ? A.zones.inside : 0, trips = parseFloat($("tripsn").value) || 0;
  $("perpair").textContent = n > 1 ? `${trips.toLocaleString()} trips over ${(n * (n - 1)).toLocaleString()}
    pairs of zones: ${(trips / (n * (n - 1))).toFixed(3)} trips each` : "";
  $("penaltymin").textContent = `added at each change of vehicle - ${(+$("penalty").value / 60).toFixed(1)} min`;
}

let planned = null;
async function plan() {
  // What this simulation will be called, and whether it exists already.
  describe();
  if (+$("to").value <= +$("from").value) { $("plan").innerHTML = "<span class='message error'>" +
    "The period must end after it starts.</span>"; planned = null; return; }
  try {
    planned = await api(`/api/${CITY}/simulation/${$("design").value}`, {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(options())});
    $("plan").innerHTML = `Saved as <code>${esc(planned.name)}</code>. ${planned.exists
      ? `It exists - <a href="${planned.result}">its results</a>, ${planned.finished}: running it
        again replaces them.` : "Not simulated yet."}`;
  } catch (e) { planned = null; $("plan").innerHTML = `<span class="message error">${esc(e.message)}</span>`; }
}

function defaults() {
  $("day").value = "weekday";
  $("from").value = A.period[0];
  $("to").value = A.period[1];
  $("trips").value = $("tripsn").value = A.demand_trips;
  $("walk").value = A.walking_speed;
  $("transfer").value = A.transfer_walk_m;
  $("penalty").value = A.transfer_penalty_s;
  $("waitf").value = A.wait_factor;
  $("access").value = A.access_m;
  plan();
}

async function run() {
  if (!planned) { say("Fix the options first.", true); return; }
  try {
    const started = await api(`/api/${CITY}/simulate/${$("design").value}`, {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(options())});
    $("run").disabled = true;
    say("");
    watch(started.job, started.name);
  } catch (e) { say(e.message, true); }
}

async function watch(job, name) {
  let s;
  try { s = await api(`/api/jobs/${job}`); }
  catch (e) {
    $("run").disabled = false;
    say(`The simulation could not be followed (${e.message}): see the list of simulations.`, true);
    return;
  }
  const done = s.state !== "running";
  $("status").innerHTML = `<div class="run"><b>${esc(name || s.name)}</b>: ${
    s.state === "running" ? `running, ${s.seconds} s` :
    s.state === "done" ? `done in ${s.seconds} s` : "failed"}
    ${s.result ? `<p><a class="button" href="${s.result}">Open the results</a></p>` : ""}
    <pre>${s.log.map(esc).join("\\n")}</pre></div>`;
  const pre = $("status").querySelector("pre");
  pre.scrollTop = pre.scrollHeight;
  if (done) {
    $("run").disabled = false;
    say(s.state === "done" ? "Simulation finished." : "The simulation failed: its log is below.",
        s.state !== "done");
    if (s.state === "done") {
      designs = await api(`/api/${CITY}/designs`);
      about();
    }
  } else setTimeout(() => watch(job, name), 1000);
}

$("design").addEventListener("change", about);
for (const id of ["day", "from", "to", "tripsn", "walk", "transfer", "penalty", "waitf", "access"])
  $(id).addEventListener("change", plan);
// The slider and the number are one value: either moves the other.
$("trips").addEventListener("input", () => { $("tripsn").value = $("trips").value; describe(); });
$("trips").addEventListener("change", plan);
$("tripsn").addEventListener("input", () => { $("trips").value = $("tripsn").value; describe(); });
$("penalty").addEventListener("input", describe);
$("reset").addEventListener("click", defaults);
$("run").addEventListener("click", run);

let A = null;
(async () => {
  const [list, settings] = await Promise.all([api(`/api/${CITY}/designs`),
                                              api(`/api/${CITY}/assignment`)]);
  designs = list;
  A = settings;
  $("day").innerHTML = A.days.map(d => `<option value="${d.day}">${esc(d.label)}</option>`).join("");
  const hours = (lo, hi) => Array.from({length: hi - lo + 1}, (_, k) => lo + k)
    .map(h => `<option value="${h}">${String(h).padStart(2, "0")}:00</option>`).join("");
  $("from").innerHTML = hours(0, 23);
  $("to").innerHTML = hours(1, 24);
  const z = A.zones || {};
  $("zones").innerHTML = z.ready
    ? `<p class="zones"><b>${z.inside.toLocaleString()}</b> zones of the road model's ${z.all.toLocaleString()}
       - <b>${z.pop.toLocaleString()}</b> people live in them; a zone is ${z.km2} km² in the middle of
       the range. Each zone's middle, the road model's centroid, is where its trips start and end.</p>`
    : `<p class="zones">The zones are built from the city's data when the simulation runs - about half
       a minute, the first time only.</p>`;
  if (!A.ready) {                         // a city with lines but nothing to assign yet
    $("run").disabled = true;
    $("plan").insertAdjacentHTML("beforebegin", `<div class="missing"><b>This city cannot be
      simulated yet.</b> ${esc(A.not_ready)}</div>`);
  }
  $("design").innerHTML = designs.map(d => `<option value="${esc(d.name)}">${esc(d.label)}${
    d.name !== "baseline" ? ` (${esc(d.name)})` : ""}${d.simulation ? " · simulated" : ""
    }</option>`).join("");
  const wanted = new URLSearchParams(location.search).get("design");
  if (wanted && designs.some(d => d.name === wanted)) $("design").value = wanted;
  defaults();
  about();
})();
</script>
</body>
</html>
"""
