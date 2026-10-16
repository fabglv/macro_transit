"""The interface, as someone uses it: a browser (headless Chrome, driven by Playwright) clicks
through the served pages on a server of its own, and what the pages say and make is checked.

    python tests/interface.py                 # every flow: about half an hour
    python tests/interface.py --only crawl,bad,files      # some of them (the quick ones)
    python tests/interface.py --keep          # leave the runs it made

The flows, on Sorocaba, in order (FLOWS):

    crawl      every page linked from the start page opens, with no script error
    nav        the menus in the top bar on every kind of page; another city keeps the kind of
               page; the start page goes on to the city last visited
    bad        what a person can get wrong is refused with a message, not a crash
    road       a road run step by step: the city's zones, a demand parameter changed, the
               assignment; its results page; compared with the baseline
    scenarios  a scenario of each kind, made by clicking the map (a road, a corridor, a road
               drawn junction to junction, two zones): saved, run, its results, reopened
    awkward    a scenario left on a run that is deleted; two runs at once; deleting while running;
               two deletes at once; the server stopped while a step runs
    delete     deleting a run from its list page
    transit    a line designed in the editor - stops clicked on the map, a timetable changed -
               saved, built, reopened; simulated twice from the simulation page; compared; deleted
    files      the pages opened as files, with no server

Everything it makes is named zzi_... and deleted after, by the server and then by a sweep of the
folders; the user's runs are not touched. The server is serve.py on PORT, never the user's own.
The report is tests/interface_report.txt; a failed check leaves a screenshot in tests/interface_shots/.
"""
import argparse
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CITY = "sorocaba"
PORT = 8765
URL = f"http://127.0.0.1:{PORT}"
PREFIX = "zzi_"
REPORT = os.path.join(ROOT, "tests", "interface_report.txt")
SHOTS = os.path.join(ROOT, "tests", "interface_shots")
SERVER_LOG = os.path.join(ROOT, "tests", "interface_server.log")
MINUTE = 60_000                    # ms, for Playwright's timeouts
RESULTS = []
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def check(area, name, passed, detail=""):
    RESULTS.append((area, name, bool(passed), detail))
    print(f"  {'PASS' if passed else 'FAIL'}  {area}: {name}" + (f"  ({detail})" if detail else ""),
          flush=True)
    return bool(passed)


# --- the server --------------------------------------------------------------------------------------
class Server:
    """serve.py on PORT, its output in SERVER_LOG."""

    def __init__(self):
        self.process = None

    def start(self, wait_s=600):
        log = open(SERVER_LOG, "a", encoding="utf-8")
        log.write(f"\n--- started {time.strftime('%H:%M:%S')}\n")
        log.flush()
        self.process = subprocess.Popen([sys.executable, "serve.py", "--port", str(PORT), "--no-open"],
                                        cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        end = time.time() + wait_s                # it builds every page before it listens
        while time.time() < end:
            if self.process.poll() is not None:
                raise RuntimeError(f"serve.py stopped: see {SERVER_LOG}")
            try:
                with socket.create_connection(("127.0.0.1", PORT), timeout=1):
                    return
            except OSError:
                time.sleep(1)
        raise RuntimeError(f"serve.py did not listen on {PORT} in {wait_s} s")

    def stop(self):
        """The server alone: a run it started goes on, as when its window is closed."""
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(30)


def api(method, path, body=None, timeout=120):
    """(status, answer) of the server's API."""
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    request = urllib.request.Request(URL + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except ValueError:
            return e.code, {"raw": raw[:300].decode("utf-8", "replace")}


def wait_job(job, timeout_s=1800):
    end = time.time() + timeout_s
    while time.time() < end:
        status, s = api("GET", f"/api/jobs/{job}")
        if status != 200 or s.get("state") != "running":
            return s
        time.sleep(3)
    return {"state": "timeout"}


def our_processes():
    """The python processes running something of ours (zzi_ in their command line): pid, line."""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*" + PREFIX + "*' } | "
          "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                         text=True).stdout
    return [line.split("\t", 1) for line in out.splitlines() if "\t" in line]


# --- the browser -------------------------------------------------------------------------------------
class Pages:
    """Chrome, headless; every page's script errors and failed requests to the server kept, and
    its dialogs (confirm, alert) accepted and kept."""

    def __init__(self, playwright):
        self.browser = playwright.chromium.launch(channel="chrome", headless=True)
        self.context = self.browser.new_context(viewport={"width": 1500, "height": 1000})

    def open(self, url, wait="load"):
        p = self.context.new_page()
        p.errors, p.dialogs = [], []
        p.on("pageerror", lambda e: p.errors.append(f"script error: {e}"))
        p.on("console", lambda m: p.errors.append(f"console: {m.text}")
             if m.type == "error" and "Failed to load resource" not in m.text else None)
        p.on("response", lambda r: p.errors.append(f"{r.status} {r.url}")
             if r.status >= 400 and r.url.startswith(URL) and "favicon" not in r.url else None)

        def dialog(d):
            p.dialogs.append(d.message)
            d.accept()
        p.on("dialog", dialog)
        p.set_default_timeout(60_000)
        p.goto(url if "://" in url else URL + url, wait_until=wait)
        return p

    def close(self):
        self.browser.close()


def shot(p, name):
    os.makedirs(SHOTS, exist_ok=True)
    path = os.path.join(SHOTS, f"{name}.png")
    try:
        p.screenshot(path=path, full_page=True)
    except Exception:                                         # noqa: BLE001 - a picture, at best
        return ""
    return path


def page_ok(area, name, p, expect_errors=()):
    """No script error, no failed request to the server, on page p so far."""
    errors = [e for e in p.errors if not any(x in e for x in expect_errors)]
    said = [f"it said: {d[:200]}" for d in p.dialogs if not d.startswith("Delete ")]
    ok = check(area, f"{name}: no script error or failed request", not errors,
               "; ".join(errors[:3] + said[:2]))
    if not ok:
        shot(p, f"{area}_{name}".replace(" ", "_")[:80])
    return ok


def wait_text(p, selector, wanted, failed=(), timeout=MINUTE):
    """Waits until selector's text has one of `wanted` (or `failed`); returns the text."""
    words = json.dumps(list(wanted) + list(failed))
    try:
        p.wait_for_function(f"""() => {{ const el = document.querySelector({json.dumps(selector)});
            return el && {words}.some(w => el.textContent.includes(w)); }}""", timeout=timeout)
    except Exception:                                         # noqa: BLE001 - said by the check
        pass
    return p.locator(selector).first.text_content() or ""


def click_map(p, latlng, map_var="map"):
    """A real click on the Leaflet map at a place: where it is on the screen, then the mouse."""
    # From the map's inside, past its border: a road takes a click only within half its width
    # (1.5 px for most), so a pixel off is a miss.
    p.evaluate(f"() => {map_var}.getContainer().scrollIntoView({{block: 'center'}})")
    point = p.evaluate(f"""([lat, lon]) => {{ const c = {map_var}.getContainer(),
        r = c.getBoundingClientRect(), q = {map_var}.latLngToContainerPoint([lat, lon]);
        return [r.left + c.clientLeft + q.x, r.top + c.clientTop + q.y]; }}""", latlng)
    p.mouse.click(point[0], point[1])


def summary_of(folder):
    path = os.path.join(ROOT, "output", "macro", folder, "summary.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --- the flows ---------------------------------------------------------------------------------------
def flow_crawl(pages):
    """Every page linked from the start page, down three levels, and every link from those
    checked for an answer."""
    seen, broken, bad_pages, opened = set(), [], [], 0
    todo = [("/", 0)]
    while todo:
        path, depth = todo.pop(0)
        if path in seen:
            continue
        seen.add(path)
        if depth > 3:                             # deep enough: does it answer
            try:
                urllib.request.urlopen(URL + path, timeout=30)
            except urllib.error.HTTPError as e:
                broken.append(f"{path}: {e.code}")
            continue
        p = pages.open(path)
        opened += 1
        try:
            p.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:                                     # noqa: BLE001 - maps keep fetching tiles
            pass
        if p.errors:
            bad_pages.append(f"{path}: {p.errors[0]}")
            shot(p, "crawl_" + path.strip("/").replace("/", "_")[:60])
        links = p.evaluate("""() => [...document.querySelectorAll('a[href]')].map(a => a.href)
                              .filter(h => h.startsWith(location.origin))""")
        p.close()
        for link in links:
            rel = link[len(URL):].split("#")[0]
            if not rel or rel in seen:
                continue
            if rel.split("?")[0].endswith((".html", "/")) and not rel.startswith(("/api/",)):
                todo.append((rel, depth + 1))
            else:
                seen.add(rel)
                try:
                    urllib.request.urlopen(URL + rel, timeout=30)
                except urllib.error.HTTPError as e:
                    broken.append(f"{rel} from {path}: {e.code}")
    check("crawl", f"{opened} pages open with no script error", not bad_pages, "; ".join(bad_pages[:4]))
    check("crawl", f"{len(seen)} links answer", not broken, "; ".join(broken[:4]))


def flow_nav(pages):
    p = pages.open("/?choose=1")
    check("nav", "asked to choose, the start page stays", p.url.endswith("?choose=1"), p.url)
    p.close()
    other = "quito" if CITY != "quito" else "sorocaba"
    for path in (f"/{CITY}/index.html", f"/{CITY}/simulations.html", f"/macro/{CITY}",
                 f"/simulate/{CITY}", f"/editor/{CITY}", f"/macro/{CITY}/index.html",
                 f"/macro/compare_{CITY}.html"):
        p = pages.open(path)
        p.wait_for_selector(".topnav", timeout=MINUTE)
        menus = p.locator(".topnav .menu > button").all_text_contents()
        check("nav", f"{path}: the city and both models' menus",
              p.text_content(".topnav a.city").strip().lower() == CITY and len(menus) == 3, str(menus))
        p.click(".topnav .menu:nth-of-type(1) button")
        to = p.get_attribute(".topnav .menu:nth-of-type(1) .items a", "href")
        want = path.replace(CITY, other, 1) if path != f"/macro/{CITY}/index.html" else f"/{other}/index.html"
        check("nav", f"{path}: another city keeps the kind of page", to == want, to if to == want else f"{to}, not {want}")
        page_ok("nav", path, p)
        p.close()
    p = pages.open("/")
    p.wait_for_load_state("load")
    check("nav", "the start page goes on to the city last visited", p.url.endswith(f"/{CITY}/index.html"),
          p.url)
    p.click(".topnav .menu:nth-of-type(3) button")
    p.click(".topnav .menu:nth-of-type(3) .items a:has-text('Run a simulation')")
    p.wait_for_load_state("load")
    check("nav", "two clicks from the city page to running a simulation",
          p.url.endswith(f"/simulate/{CITY}"), p.url)
    page_ok("nav", "after the menus", p)
    p.close()


def flow_bad(pages):
    # The road run page.
    p = pages.open(f"/macro/{CITY}")
    p.wait_for_function("() => STEPS.length > 0")
    p.fill("#name", "Bad Name!")
    p.click("#stepper button[data-k='0']")         # the baseline opens on its results
    p.click("#compute")
    said = p.text_content("#message")
    check("bad", "a run named with spaces and capitals is refused", "Give the run a name" in said, said)
    p.fill("#name", f"{PREFIX}bad")
    p.click("#stepper button[data-k='0']")
    number = p.locator("#panel .param input[type=number]").first
    if number.count():
        number.fill("")
        p.click("#compute")
        said = p.text_content("#message")
        check("bad", "an emptied number is refused before anything runs",
              "marked red" in said, said)
    page_ok("bad", "road run page", p)
    p.close()

    # The scenario page: nothing to run, a reserved name.
    p = pages.open(f"/scenario/{CITY}")
    p.wait_for_function("() => typeof net === 'object' && net && Object.keys(nodeAt).length > 0",
                        timeout=3 * MINUTE)
    p.click("#kinds button[data-kind=closure]")
    p.fill("#name", f"{PREFIX}nothing")
    p.click("#run")
    said = p.text_content("#message")
    check("bad", "a scenario with no edits is refused", "Select the roads" in said, said)
    p.fill("#name", "baseline")
    p.click("#run")
    said = p.text_content("#message")
    check("bad", "a scenario named baseline is refused", "Give the scenario a name" in said, said)
    page_ok("bad", "scenario page", p)
    p.close()

    # The simulation page: a period that ends before it starts.
    p = pages.open(f"/simulate/{CITY}")
    p.wait_for_function("() => A && document.querySelector('#plan').textContent.length > 0")
    p.select_option("#from", "10")
    p.select_option("#to", "9")
    said = p.text_content("#plan")
    check("bad", "a period ending before it starts is said at once", "must end after" in said, said)
    p.click("#run")
    said = p.text_content("#message")
    check("bad", "... and is not run", "Fix the options" in said, said)
    page_ok("bad", "simulation page", p)
    p.close()

    # The editor: no name, then nothing changed.
    p = pages.open(f"/editor/{CITY}")
    p.wait_for_function("() => typeof base === 'object' && base && net", timeout=2 * MINUTE)
    p.click("#save")
    said = p.text_content("#message")
    check("bad", "a design with no name is refused", "Give the design a name" in said, said)
    p.fill("#name", f"{PREFIX}empty")
    p.click("#save")
    said = p.text_content("#message")
    check("bad", "a design with no change is refused", "Nothing is changed" in said, said)
    page_ok("bad", "editor page", p)
    p.close()

    # The API itself: what a page would never send.
    cases = [
        ("broken JSON", "POST", f"/api/{CITY}/macro/{PREFIX}junk", b"{not json"),
        ("a link the network does not have", "POST", f"/api/{CITY}/macro/{PREFIX}junk",
         {"label": "x", "base": "baseline", "type": "closure",
          "edits": [{"kind": "close", "links": [999999999]}]}),
        ("a scenario of a base that does not exist", "POST", f"/api/{CITY}/macro/{PREFIX}junk",
         {"label": "x", "base": "nowhere", "type": "closure", "edits": [{"kind": "close", "links": [1]}]}),
        ("a scenario of the wrong kind for its edits", "POST", f"/api/{CITY}/macro/{PREFIX}junk",
         {"label": "x", "base": "baseline", "type": "demand", "edits": [{"kind": "close", "links": [1]}]}),
        ("negative trips added", "POST", f"/api/{CITY}/macro/{PREFIX}junk",
         {"label": "x", "base": "baseline", "type": "demand",
          "edits": [{"kind": "trips", "pairs": [[1, 2, -50]], "both": False}]}),
        ("a step that does not exist", "POST", f"/api/{CITY}/macro/{PREFIX}junk",
         {"label": "x", "parameters": {}, "step": "teleport"}),
        ("a simulation with no trips", "POST", f"/api/{CITY}/simulation/baseline",
         {"day": "weekday", "period": [7, 8], "trips": 0}),
        ("a simulation on a day with no name", "POST", f"/api/{CITY}/simulation/baseline",
         {"day": "someday", "period": [7, 8]}),
        ("a city that does not exist", "GET", "/api/atlantis/macro", None),
        ("deleting the baseline", "DELETE", f"/api/{CITY}/macro/baseline", None),
        ("deleting a run that does not exist", "DELETE", f"/api/{CITY}/macro/{PREFIX}never", None),
        ("a name with a path in it", "DELETE", f"/api/{CITY}/macro/..%2F..%2Fsettings", None),
    ]
    for said, method, path, body in cases:
        status, answer = api(method, path, body)
        check("bad", f"API: {said} is refused with a message",
              400 <= status < 500 and ("error" in answer), f"{status} {str(answer)[:150]}")
    status, _ = api("GET", f"/api/{CITY}/macro")
    check("bad", "the server still answers after all that", status == 200)
    from core import runs
    check("bad", "nothing refused was saved", not os.path.exists(runs.path(CITY, f"{PREFIX}junk")))


def flow_road(pages):
    p = pages.open(f"/macro/{CITY}")
    p.wait_for_function("() => STEPS.length > 0")
    p.fill("#name", f"{PREFIX}run")
    p.fill("#label", "interface test run")
    check("road", "a new name: step 1 not computed",
          "not computed" in p.text_content("#stepper button[data-k='0']"))
    p.click("#stepper button[data-k='0']")
    p.click("#compute")
    said = wait_text(p, "#message", ["Step 1 computed"], ["failed"], 20 * MINUTE)
    if not check("road", "step 1 (the city's zones) computes", "Step 1 computed" in said, said):
        shot(p, "road_step1")
        return
    check("road", "the page moves on to step 2 itself",
          "on" in (p.get_attribute("#stepper button[data-k='1']", "class") or ""))
    # A demand parameter changed: more trips per person.
    name = p.evaluate("""() => ["TRIPS_PER_PERSON", "CAR_SHARE", "OCCUPANCY"].find(n =>
        document.querySelector(`.param[data-name="${n}"] input[type=number]`))""")
    field = p.locator(f".param[data-name='{name}'] input[type=number]").first
    before = float(field.input_value())
    field.fill(f"{before * 1.2:.4g}")
    changes = p.text_content("#changes")
    check("road", f"changing {name} counts as one change", changes.startswith("1 change"), changes)
    check("road", "... and offers the way back to the setting",
          p.locator(f".param[data-name='{name}'] button[data-reset]").count() == 1)
    p.click("#compute")
    said = wait_text(p, "#message", ["Step 2 computed"], ["failed"], 20 * MINUTE)
    if not check("road", "step 2 (the demand) computes", "Step 2 computed" in said, said):
        shot(p, "road_step2")
        return
    p.click("#next")
    p.click("#compute")
    said = wait_text(p, "#message", ["Step 3 computed"], ["failed"], 30 * MINUTE)
    if not check("road", "step 3 (the assignment) computes", "Step 3 computed" in said, said):
        shot(p, "road_step3")
        return
    p.click("#stepper button[data-k='3']")
    link = p.get_attribute("text=Open the results page", "href")
    check("road", "the results step links its results page", bool(link), link)
    page_ok("road", "road run page", p)
    p.close()

    r = pages.open(link)
    check("road", "its results page has its label", "interface test run" in r.content())
    page_ok("road", "its results page", r)
    r.close()
    run, base = summary_of(f"{CITY}-{PREFIX}run"), summary_of(CITY)
    check("road", f"more {name} gives more trips than the baseline",
          run and run["totals"]["trips"] > base["totals"]["trips"],
          f"{base['totals']['trips']:,.0f} -> {run['totals']['trips']:,.0f}" if run else "no summary")
    from core import runs
    with open(runs.path(CITY, f"{PREFIX}run"), encoding="utf-8") as f:
        saved = json.load(f)
    check("road", "the run's file holds the change, and only it",
          list(saved["parameters"]) == [name], str(saved["parameters"]))

    # Back on the page: it opens on the results, every step computed.
    p = pages.open(f"/macro/{CITY}?run={PREFIX}run")
    p.wait_for_function("() => STEPS.length > 0")
    check("road", "reopened, the run shows every step computed",
          p.locator("#stepper button.done").count() == 4)
    page_ok("road", "the run reopened", p)
    p.close()

    c = pages.open(f"/macro/compare_{CITY}.html?a={CITY}&b={CITY}-{PREFIX}run")
    try:
        c.wait_for_function("() => !document.querySelector('#out').textContent.includes('Loading')",
                            timeout=MINUTE)
    except Exception:                                         # noqa: BLE001 - said below
        pass
    chosen = c.evaluate("() => RUNS[document.querySelector('#b').value].id")
    check("road", "the compare page takes it as the alternative", chosen == f"{CITY}-{PREFIX}run", chosen)
    page_ok("road", "compare page", c)
    c.close()


def scenario_page(pages, query=""):
    p = pages.open(f"/scenario/{CITY}{query}")
    p.wait_for_function("() => typeof net === 'object' && net && Object.keys(nodeAt).length > 0",
                        timeout=3 * MINUTE)
    return p


def run_scenario(p, kind):
    """Names it, saves and runs it from the page; True if it ran."""
    p.fill("#name", f"{PREFIX}{kind}")
    p.fill("#label", f"interface {kind}")
    p.click("#run")
    said = wait_text(p, "#message", ["The scenario has run"], ["failed", "Give", "Select", "Pick",
                                                               "Draw", "compute"], 30 * MINUTE)
    ok = check("scenarios", f"{kind}: saved and run from the page", "has run" in said, said)
    if not ok:
        shot(p, f"scenario_{kind}")
        return False
    links = {a: p.get_attribute(f"#job a:has-text('{a}')", "href")
             for a in ("Open its results", "Compare it with its base")}
    check("scenarios", f"{kind}: links its results and the comparison", all(links.values()), str(links))
    return links


def flow_scenarios(pages):
    made = {}

    # A closure: a real click on the busiest main road.
    p = scenario_page(pages)
    p.click("#kinds button[data-kind=closure]")
    target = p.evaluate("""() => {
        let best = null;
        for (const [id, g] of Object.entries(net)) {
          if (!g[0] || !/^(primary|secondary)$/.test(g[1]) || g[2].length < 2) continue;
          const f = flow(id), v = f[0] + f[1];
          if (!best || v > best[1]) best = [id, v];
        }
        const pts = net[best[0]][2], i = Math.floor((pts.length - 2) / 2);
        map.fitBounds(pts, {maxZoom: 17, animate: false});
        return {id: best[0], name: net[best[0]][0],
                at: [(pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2]};
    }""")
    click_map(p, target["at"])
    picked = p.evaluate("() => [...selection]")
    check("scenarios", "closure: a click on a road selects its stretch",
          target["id"] in picked and len(picked) > 1, f"{len(picked)} links, {target['name']}")
    check("scenarios", "closure: the selection is described",
          target["name"] in p.text_content("#selected"), p.text_content("#selected")[:120])
    p.click("#add")
    check("scenarios", "closure: added as an edit", "closed" in p.text_content("#edits"))
    made["closure"] = run_scenario(p, "closure")
    page_ok("scenarios", "closure page", p)
    p.close()

    # A capacity change: a suggested corridor.
    p = scenario_page(pages)
    p.click("#kinds button[data-kind=capacity]")
    p.locator("#sugg div[data-street]").first.click()
    n = p.evaluate("() => selection.size")
    check("scenarios", "capacity: a suggested corridor selects a stretch of it", 1 < n <= 20, f"{n} links")
    p.fill("#factor", "1.5")
    p.click("#add")
    check("scenarios", "capacity: added as an edit", "capacity × 1.5" in p.text_content("#edits"),
          p.text_content("#edits")[:120])
    made["capacity"] = run_scenario(p, "capacity")
    page_ok("scenarios", "capacity page", p)
    p.close()

    # A new road: drawn from a junction to another, 1-2 km away.
    p = scenario_page(pages)
    p.click("#kinds button[data-kind=newroad]")
    check("scenarios", "new road: the map shows the road network",
          p.evaluate("() => mapView") == "roads")
    p.click("#draw")
    ends = p.evaluate("""() => {
        const main = n => (byNode[n] || []).length >= 3 &&
          byNode[n].some(id => /^(primary|secondary)$/.test(net[id][1]));
        const nodes = Object.keys(nodeAt).filter(main).sort((a, b) => a - b);
        const a = nodes[Math.floor(nodes.length / 2)];
        for (const b of nodes) {
          const d = map.distance(nodeAt[a], nodeAt[b]);
          if (d > 1000 && d < 1800) {
            map.fitBounds([nodeAt[a], nodeAt[b]], {padding: [120, 120], animate: false});
            return {a: +a, b: +b, at: [nodeAt[a], nodeAt[b]]};
          }
        }
        return null;
    }""")
    click_map(p, ends["at"][0])
    started = p.evaluate("() => road && road.from")
    check("scenarios", "new road: the first click starts on a junction", started is not None,
          str(started))
    click_map(p, ends["at"][1])
    ended = p.evaluate("() => road && road.to")
    check("scenarios", "new road: a click on another junction ends it",
          ended is not None and ended != started, f"{started} -> {ended}")
    p.fill("#rname", "Interface test road")
    p.click("#addroad")
    check("scenarios", "new road: added as an edit",
          "new road: Interface test road" in p.text_content("#edits"), p.text_content("#edits")[:120])
    made["newroad"] = run_scenario(p, "newroad")
    page_ok("scenarios", "new road page", p)
    p.close()

    # Trips added: two zones clicked on the map.
    p = scenario_page(pages)
    p.click("#kinds button[data-kind=demand]")
    p.wait_for_function("() => zonesLayer && zonesOf === base.name", timeout=2 * MINUTE)
    at = p.evaluate("""() => {
        const layers = []; zonesLayer.eachLayer(l => layers.push(l));
        layers.sort((x, y) => x.feature.properties.zone - y.feature.properties.zone);
        const two = [layers[Math.floor(layers.length / 3)], layers[Math.floor(2 * layers.length / 3)]];
        map.fitBounds(two[0].getBounds().extend(two[1].getBounds()), {padding: [60, 60], animate: false});
        return two.map(l => { const c = l.getCenter(); return [c.lat, c.lng]; });
    }""")
    click_map(p, at[0])
    click_map(p, at[1])
    pair = p.evaluate("() => [pairA, pairB]")
    check("scenarios", "demand: two clicks pick the zones the trips go from and to",
          None not in pair and pair[0] != pair[1], str(pair))
    p.fill("#dtrips", "800")
    p.check("#dboth")
    p.click("#adddemand")
    check("scenarios", "demand: added as an edit", "+800 trips" in p.text_content("#edits"),
          p.text_content("#edits")[:120])
    made["demand"] = run_scenario(p, "demand")
    page_ok("scenarios", "demand page", p)
    p.close()
    if made["demand"]:
        s, base = summary_of(f"{CITY}-{PREFIX}demand"), summary_of(CITY)
        added = s["totals"]["trips"] - base["totals"]["trips"]
        check("scenarios", "demand: 800 trips each way are 1,600 more trips", abs(added - 1600) < 1e-6,
              f"+{added:,.3f}")

    # Each scenario's results and comparison; each reopened from its saved file.
    for kind, links in made.items():
        if not links:
            continue
        for what, link in links.items():
            r = pages.open(link)
            try:
                r.wait_for_load_state("networkidle", timeout=20_000)
            except Exception:                                 # noqa: BLE001 - tiles
                pass
            page_ok("scenarios", f"{kind}: {what.lower()}", r)
            r.close()
        p = scenario_page(pages, f"?scenario={PREFIX}{kind}")
        edits = p.text_content("#edits")
        check("scenarios", f"{kind}: reopened with its edit and its kind fixed",
              edits.strip() not in ("", "None yet.") and p.locator("#rekind").count() == 0,
              edits[:100])
        page_ok("scenarios", f"{kind}: reopened", p)
        p.close()


def flow_awkward(pages, server):
    from core import runs

    # A scenario left behind when the run it is made on is deleted.
    status, _ = api("POST", f"/api/{CITY}/macro/{PREFIX}orphan",
                    {"label": "orphan", "description": "", "base": f"{PREFIX}run", "type": "closure",
                     "edits": [{"kind": "close", "links": [int(next(iter(_some_links())))]}]})
    if check("awkward", "a scenario is saved on the test run", status == 200, str(status)):
        status, answer = api("DELETE", f"/api/{CITY}/macro/{PREFIX}run")
        said = f"{status} {answer}"
        # Either refused (it has scenarios) or done and the scenario left readable.
        if status == 200:
            status, state = api("GET", f"/api/{CITY}/macro")
            orphan = [r for r in state.get("runs", []) if r["name"] == f"{PREFIX}orphan"]
            check("awkward", "deleting a run with a scenario on it: the run list still loads",
                  status == 200, said)
            check("awkward", "... and its scenario says its base is gone",
                  bool(orphan) and bool(orphan[0].get("error")), str(orphan)[:200])
            for path in (f"/{CITY}/macro.html", f"/scenario/{CITY}", f"/macro/{CITY}"):
                p = pages.open(path)
                p.wait_for_timeout(3000)
                page_ok("awkward", f"{path} with a scenario whose base is gone", p)
                p.close()
        else:
            message = answer.get("error", "")
            check("awkward", "deleting a run with a scenario on it is refused, with a message",
                  message and "Error" not in message and "Errno" not in message, said)
            folder = runs.output_dir(CITY, f"{PREFIX}run")
            check("awkward", "... and the run is left whole",
                  os.path.isfile(runs.path(CITY, f"{PREFIX}run"))
                  and os.path.isfile(os.path.join(folder, "summary.json"))
                  and os.path.isdir(os.path.join(folder, "steps", "road_model")), folder)

    # Two runs at once: the second is told to wait.
    links = _some_links()
    body = lambda: {"label": "x", "description": "", "base": "baseline", "type": "closure",  # noqa: E731
                    "edits": [{"kind": "close", "links": links}], "run": True}
    s1, a1 = api("POST", f"/api/{CITY}/macro/{PREFIX}first", body())
    s2, a2 = api("POST", f"/api/{CITY}/macro/{PREFIX}second", body())
    check("awkward", "a second run while one runs is told to wait", s1 == 200 and s2 == 409,
          f"{s1}, {s2} {a2.get('error', '')}")

    # Deleting a run while it runs.
    status, answer = api("DELETE", f"/api/{CITY}/macro/{PREFIX}first")
    check("awkward", "deleting a run while it runs is refused", status == 400 and "running" in
          answer.get("error", ""), f"{status} {answer}")
    p = pages.open(f"/{CITY}/macro.html")
    button = p.locator(f"button.delete[data-url$='/{PREFIX}second']")
    if button.count():
        button.click()
        p.wait_for_timeout(1500)
    page_ok("awkward", "the list page while a run runs", p)
    p.close()
    done = wait_job(a1["job"]) if s1 == 200 else {}
    check("awkward", "the run goes on to the end", done.get("state") == "done", done.get("state"))

    # Two deletes at once: of two runs, and of one run twice.
    for name in ("third", "fourth"):
        api("POST", f"/api/{CITY}/macro/{PREFIX}{name}",
            {"label": name, "description": "", "base": "baseline", "type": "closure",
             "edits": [{"kind": "close", "links": links}]})
    answers = {}

    def delete(key, name):
        answers[key] = api("DELETE", f"/api/{CITY}/macro/{PREFIX}{name}")
    threads = [threading.Thread(target=delete, args=(k, n)) for k, n in
               (("a", "first"), ("b", "third"), ("c", "fourth"), ("d", "fourth"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    codes = {k: v[0] for k, v in answers.items()}
    check("awkward", "two runs deleted at once are both deleted",
          codes["a"] == 200 and codes["b"] == 200, str(codes))
    check("awkward", "one run deleted twice at once: one delete, one message, no crash",
          sorted([codes["c"], codes["d"]]) == [200, 400], str(codes))
    gone = [n for n in ("first", "third", "fourth")
            if os.path.exists(runs.path(CITY, PREFIX + n)) or os.path.isdir(runs.output_dir(CITY, PREFIX + n))]
    check("awkward", "their files and results are gone", not gone, str(gone))
    time.sleep(20)                                   # the lists are rebuilt in the background
    p = pages.open(f"/{CITY}/macro.html")
    left = [n for n in ("first", "third", "fourth")
            if p.locator(f"button.delete[data-url$='/{PREFIX}{n}']").count()]
    check("awkward", "the list page no longer shows them", not left, str(left))
    page_ok("awkward", "the list page after the deletes", p)
    p.close()

    # The server stopped while a scenario runs, and started again.
    status, answer = api("POST", f"/api/{CITY}/macro/{PREFIX}restart",
                         {"label": "restart", "description": "", "base": "baseline", "type": "closure",
                          "edits": [{"kind": "close", "links": links}], "run": True})
    if not check("awkward", "a run is started before the server stops", status == 200, str(status)):
        return
    time.sleep(15)
    server.stop()
    alive = our_processes()
    check("awkward", "the server stopped: what happens to its run", True,
          f"{len(alive)} of our run.py still going after the server stopped")
    server.start()
    status, state = api("GET", f"/api/{CITY}/macro")
    check("awkward", "the server starts again, its run list readable", status == 200)
    mine = [r for r in state.get("runs", []) if r["name"] == f"{PREFIX}restart"]
    check("awkward", "the run cut short is listed, not shown as running",
          mine and state.get("running") is None, json.dumps(mine[0].get("done") if mine else None))
    p = scenario_page(pages, f"?scenario={PREFIX}restart")
    page_ok("awkward", "the scenario page after the restart", p)
    p.close()
    # Whatever went on: once the stray run has ended, the scenario runs again from the start.
    end = time.time() + 900
    while our_processes() and time.time() < end:
        time.sleep(5)
    status, answer = api("POST", f"/api/{CITY}/macro/{PREFIX}restart",
                         {"label": "restart", "description": "", "base": "baseline", "type": "closure",
                          "edits": [{"kind": "close", "links": links}], "run": True})
    done = wait_job(answer["job"]) if status == 200 else {"state": f"{status} {answer}"}
    check("awkward", "after the restart the run can be run again, to the end",
          done.get("state") == "done", done.get("state"))


_LINKS = []


def _some_links():
    """Ten links of the baseline's busiest main street."""
    if not _LINKS:
        import geopandas as gpd

        from core import runs
        links = gpd.read_file(os.path.join(runs.output_dir(CITY, runs.BASELINE), "exports",
                                           "link_volumes.gpkg"), ignore_geometry=True)
        links["flow"] = links["car_ab"].fillna(0) + links["car_ba"].fillna(0)
        main = links[links["link_type"].isin(["primary", "secondary"])]
        top = main.groupby("name")["flow"].sum().idxmax()
        _LINKS.extend(int(i) for i in main[main["name"] == top].nlargest(10, "flow")["link_id"])
    return list(_LINKS)


def flow_delete(pages):
    from core import runs
    name = f"{PREFIX}capacity"
    if not os.path.isfile(runs.path(CITY, name)):
        check("delete", "a run to delete is there", False, "the capacity scenario was not made")
        return
    p = pages.open(f"/{CITY}/macro.html")
    button = p.locator(f"button.delete[data-url$='/{name}']")
    check("delete", "the list page has a Delete button for it", button.count() == 1)
    button.click()
    p.wait_for_load_state("load")
    check("delete", "it asks first", any("Delete the run" in d for d in p.dialogs), str(p.dialogs))
    end = time.time() + 120
    while time.time() < end:
        if not os.path.exists(runs.path(CITY, name)) and not os.path.isdir(runs.output_dir(CITY, name)):
            break
        time.sleep(1)
    check("delete", "its file and results are deleted",
          not os.path.exists(runs.path(CITY, name)) and not os.path.isdir(runs.output_dir(CITY, name)))
    end = time.time() + 120
    while time.time() < end:
        p.reload()
        if not p.locator(f"button.delete[data-url$='/{name}']").count():
            break
        time.sleep(3)
    check("delete", "the list page drops it", not p.locator(f"button.delete[data-url$='/{name}']").count())
    page_ok("delete", "list page", p)
    p.close()


def flow_transit(pages):
    design = f"{PREFIX}line"
    p = pages.open(f"/editor/{CITY}")
    p.wait_for_function("() => typeof base === 'object' && base && net && map", timeout=2 * MINUTE)
    p.click("#tabs button[data-new]")
    stops = p.evaluate("""() => {
        const line = net.lines.find(l => l.stops.length >= 8);
        const four = line.stops.slice(2, 6).map(t => [t[1], t[2]]);
        map.fitBounds(four, {padding: [80, 80], animate: false});
        return four;
    }""")
    for at in stops:
        click_map(p, at)
        p.wait_for_timeout(300)
    n = p.evaluate("() => active(newLines[current]).length")
    check("transit", "four clicks on the map place four stops", n == 4, f"{n} stops")
    # Typed as a person does: each field's change comes as the next one is clicked into.
    p.fill("#lineform input[data-f=route]", "ZZI1")
    p.fill("#lineform input[data-f=name]", "Interface test line")
    p.wait_for_timeout(3000)                     # its legs routed along the streets
    first = p.locator(".tt[data-key] input[data-t=headway_min]").first
    old = first.input_value()
    first.click()
    first.fill("7")
    first.press("Tab")
    check("transit", "a line's headway changed in its timetable card",
          "changed" in (p.locator(".tt[data-key]").first.get_attribute("class") or ""), f"{old} -> 7")
    p.fill("#name", design)
    p.fill("#label", "interface test design")
    p.click("#save")
    said = wait_text(p, "#message", ["its pages are built"], ["failed", "Give", "Nothing", "⚠"],
                     10 * MINUTE)
    if not check("transit", "saved and built from the editor", "its pages are built" in said, said):
        shot(p, "transit_save")
        return
    with open(os.path.join(ROOT, "designs", CITY, f"{design}.json"), encoding="utf-8") as f:
        kept = json.load(f)["changes"]
    check("transit", "the design file holds the new line and the headway",
          any(c["type"] == "add_line" and c["route"] == "ZZI1" and len(c["stops"]) == 4 for c in kept)
          and any(c["type"] == "service" and c.get("headway_min") == 7 for c in kept),
          json.dumps([{k: c.get(k) for k in ("type", "route", "headway_min")} for c in kept]))
    view = p.get_attribute("#status a:has-text('View the design')", "href")
    page_ok("transit", "editor", p)
    p.close()
    r = pages.open(view)
    check("transit", "the design page shows the new line", "ZZI1" in r.content())
    page_ok("transit", "design page", r)
    r.close()

    p = pages.open(f"/editor/{CITY}?scenario={design}")
    p.wait_for_function(f"() => typeof loadedName === 'string' && loadedName === '{design}'",
                        timeout=2 * MINUTE)
    back = p.evaluate("""() => ({lines: newLines.length + added.length,
        stops: (added[0] || newLines[0] || {stops: []}).stops.length})""")
    check("transit", "reopened in the editor with its line and stops", back["stops"] == 4, str(back))
    page_ok("transit", "editor, design reopened", p)
    p.close()

    sims = []
    for trips in (None, 20000):
        p = pages.open(f"/simulate/{CITY}?design={design}")
        p.wait_for_function("() => document.querySelector('#plan').textContent.includes('Saved as')")
        if trips:
            p.fill("#tripsn", str(trips))
            p.dispatch_event("#tripsn", "change")
            p.wait_for_function(f"() => document.querySelector('#plan').textContent.includes('{trips}')")
        name = p.text_content("#plan code")
        p.click("#run")
        said = wait_text(p, "#message", ["Simulation finished"], ["failed", "Fix"], 30 * MINUTE)
        if check("transit", f"simulation {name} runs from the page", "finished" in said, said):
            sims.append(name)
            result = p.get_attribute("#status a:has-text('Open the results')", "href")
            r = pages.open(result)
            page_ok("transit", f"simulation {name}'s results", r)
            r.close()
        else:
            shot(p, f"transit_sim_{trips}")
        page_ok("transit", "simulation page", p)
        p.close()
    check("transit", "the trips are in the second simulation's name", any("20000" in s for s in sims),
          str(sims))

    c = pages.open(f"/transit/simulations/compare_{CITY}.html")
    text = c.content()
    check("transit", "the compare page offers both simulations", all(s in text for s in sims), str(sims))
    page_ok("transit", "compare simulations", c)
    c.close()

    for what, names in (("simulations", sims), ("designs", [design])):
        p = pages.open(f"/{CITY}/{what}.html")
        for name in names:
            button = p.locator(f"button.delete[data-url$='/{what}/{name}']")
            if check("transit", f"{what}: {name} has a Delete button", button.count() == 1):
                button.click()
                p.wait_for_load_state("load")
                p.wait_for_timeout(2000)
        page_ok("transit", f"{what} list after deleting", p)
        p.close()
    left = glob.glob(os.path.join(ROOT, "output", "transit", "*", f"{CITY}-{design}*")) + \
        glob.glob(os.path.join(ROOT, "designs", CITY, f"{design}.json"))
    check("transit", "the design and its simulations are deleted", not left, str(left))


def flow_files(pages):
    """The pages as files, as view.py opens them: no server behind."""
    from core import runs
    paths = [os.path.join(ROOT, "output", "index.html"), os.path.join(ROOT, "output", CITY, "index.html"),
             os.path.join(ROOT, "output", CITY, "macro.html"),
             os.path.join(ROOT, "output", CITY, "simulations.html"),
             os.path.join(runs.output_dir(CITY, runs.BASELINE), "index.html"),
             os.path.join(ROOT, "output", "transit", "designs", f"{CITY}-baseline", "index.html"),
             os.path.join(ROOT, "output", "transit", "simulations", f"{CITY}-baseline", "index.html")]
    for path in paths:
        if not os.path.isfile(path):
            check("files", f"{os.path.relpath(path, ROOT)} is there", False)
            continue
        p = pages.open("file:///" + path.replace("\\", "/"))
        p.wait_for_timeout(2500)
        page_ok("files", os.path.relpath(path, ROOT), p)
        hidden = p.evaluate("""() => [...document.querySelectorAll('.server-only')]
                               .every(b => getComputedStyle(b).display === 'none')""")
        check("files", f"{os.path.relpath(path, ROOT)}: no server-only button shown", hidden)
        p.close()


FLOWS = {"crawl": flow_crawl, "nav": flow_nav, "bad": flow_bad, "road": flow_road, "scenarios": flow_scenarios,
         "awkward": flow_awkward, "delete": flow_delete, "transit": flow_transit, "files": flow_files}


# --- cleaning up -------------------------------------------------------------------------------------
def clean():
    """Every zzi_ thing: by the server if it is up, then off the disk; the pages rebuilt."""
    from core import runs
    for pid, line in our_processes():
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
    for path in glob.glob(os.path.join(os.path.dirname(runs.path(CITY, "x")), f"{PREFIX}*")):
        shutil.rmtree(path, ignore_errors=True) if os.path.isdir(path) else os.remove(path)
    patterns = [os.path.join(ROOT, "output", "macro", f"{CITY}-{PREFIX}*"),
                os.path.join(ROOT, "output", "transit", "*", f"{CITY}-{PREFIX}*"),
                os.path.join(ROOT, "designs", CITY, f"{PREFIX}*")]
    for pattern in patterns:
        for path in glob.glob(pattern):
            shutil.rmtree(path, ignore_errors=True) if os.path.isdir(path) else os.remove(path)
    subprocess.run([sys.executable, "view.py", "--no-open"], cwd=ROOT, capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="flows, comma-separated: " + ", ".join(FLOWS))
    parser.add_argument("--keep", action="store_true", help="leave what it made")
    args = parser.parse_args()
    chosen = args.only.split(",") if args.only else list(FLOWS)
    from playwright.sync_api import sync_playwright

    shutil.rmtree(SHOTS, ignore_errors=True)
    server = Server()
    started = time.time()
    try:
        server.start()
        with sync_playwright() as playwright:
            pages = Pages(playwright)
            try:
                for name in chosen:
                    print(f"\n{name} ({time.strftime('%H:%M:%S')})", flush=True)
                    t = time.time()
                    try:
                        FLOWS[name](pages, server) if name == "awkward" else FLOWS[name](pages)
                    except Exception as problem:                  # noqa: BLE001 - the next flow
                        check(name, "the flow ran to its end", False,
                              f"{type(problem).__name__}: {str(problem)[:300]}")
                        traceback.print_exc()
                    print(f"  ({(time.time() - t) / 60:.1f} min)", flush=True)
            finally:
                pages.close()
    finally:
        server.stop()
        if not args.keep:
            clean()
    failed = [r for r in RESULTS if not r[2]]
    lines = [f"Interface checks, {time.strftime('%Y-%m-%d %H:%M')}, {(time.time() - started) / 60:.0f} min: "
             f"{len(RESULTS) - len(failed)} of {len(RESULTS)} passed", ""]
    lines += [f"{'PASS' if ok else 'FAIL'}  {area}: {name}" + (f"  ({detail})" if detail else "")
              for area, name, ok, detail in RESULTS]
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n" + lines[0] + f"\nReport: {REPORT}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
