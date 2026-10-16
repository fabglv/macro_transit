# macro_program — TAZ, O-D matrix and baseline assignment

The two notebooks `sorocaba/TAZ_OD_sorocaba.ipynb` and `aequilibrae/notebooks/TAZ_OD_demo.ipynb`
(Quito), turned into one Python program. What both cities do is shared code; what only one does
lives with that city.

## The data

The model reads `data/<city>/input_min/` - in the repository, about 70-80 MB a city: the
originals cut to what the model uses by `tools/trim_inputs.py` (the rows, columns and area it
reads, or a small table worked out from a file exactly as the model would), so a run on them gives
the results a run on the originals did. The originals - `data/<city>/input/`, about 1 GB, several
files over GitHub's 100 MB - are not in the repository; `data/sorocaba/input/SOURCES.md` and
`DATA_INVENTORY.md` say where Sorocaba's come from. With them in `data/<city>/input/`,
`python tools/trim_inputs.py` writes `input_min/` again. The downloads (the OSM street network,
regional roads, km posts) are fetched on the first run and kept in `data/<city>/cache/`, which is
not in the repository either: OSM changes, so a network downloaded later may differ a little from
the one these results were made on. `output/`, everything the program writes, is not in it.

## Running it

Python 3.12 with AequilibraE 1.6.2 (the interpreter the `aequilibrae-py312` kernel uses):

```bash
python run.py sorocaba
python run.py quito
python run.py sorocaba --out output/macro/test  # a test run that cannot touch output/macro/sorocaba
python run.py quito --rebuild-network            # download the OSM network again
python compare_reference.py sorocaba             # set a run against the notebook's exports
```

With the caches in place, a run takes about 3 minutes for Sorocaba and 5 for Quito. Everything
printed also goes to `output/macro/<city>/run_log.txt`.

Sorocaba's results are identical to the notebook's (zones, matrix, link flows, count comparison);
Quito's zones are identical and its matrix nearly so - see below.

**To look at the results**, open `output/index.html` in a browser (or run `python view.py`): the
start page chooses the **city** - and goes straight on to the one last visited (`?choose=1` to
choose again) - whose page (`output/<city>/index.html`) has its **road model** (its runs,
`output/macro/`) and its **public transport** (line designs and simulations, `output/transit/`)
side by side: each one's actions - a new run, scenarios, the line editor, a simulation, the
compare pages - and its latest runs, with links to the full lists. On every page, the bar at the
top has the city (and a menu to switch to another, on the same kind of page) and a menu for each
model, reaching any of those pages in a click; opened as files, the pages only the server makes
(`serve.py`) are shown greyed. A menu at the top of each run's page moves between that kind's
runs. A road run's page (`output/macro/<city>/index.html`)
opens on the zones map, with the simulation map next and the others under *More
maps* (among them the trip ends per zone); then the run's statistics - an overview, travel
times on empty streets and in the simulation (or both compared), trip distances, how loaded
each road class runs, the most congested streets - its parameters by group (network, zones, trip generation,
gravity model, cost function, simulation...), the other exported tables (sortable, filterable),
the run log by section and the exported files. Each run writes the pages at the end; `python view.py` builds
them again and opens the start page (`view.py <city>` opens that city's road run, `view.py <city>
--transit` its public-transport run), without running the model. A public-transport run's page
opens on its network map, with the passenger loads next, and its statistics are an overview,
journey times (and what the average journey is made of), the busiest rides and stops, and how
far trips start from a stop. Its **Feed** section reads the GTFS timetable the run wrote
(`exports/gtfs_feed.zip`, any GTFS feed reads the same way): the routes with their headways and
speeds, departures by hour with the modelled period shaded, line diagrams with interchanges and
one-way stops, a time-distance diagram of every trip around the period, and stop timetables.
Route colours come from the feed's own `route_color`, the colours the maps use. A table longer than 5,000 rows (the transit skims) is not put on the
page, only listed under the exported files.
After a change to how a map looks, `python view.py <city> --maps` (or `view.py --maps` for every
run) redraws every map in seconds - no need to run the model again. The zones and simulation maps
are drawn from the run's exports (`zones.gpkg`, `link_volumes.gpkg`, `city_limit.gpkg` and the
totals in `summary.json`); every other map is drawn by a function marked `@redrawable`, which
saves what it was drawn from in `map_data/` in the run's folder as the run draws it. A new map gets the
same by carrying the decorator. A change to what a map is drawn *from* still needs a run. The
overview's headline numbers are in `summary.json`, the same lines for every city (`HEADLINE` in
`core/summary.py`).

**To prepare a run in steps**, use the **Run a macrosimulation** page (a city's Macrosimulation
list, when served: `python serve.py`). A road run is three steps (`core/steps.py`), each with its
own parameters and computed before the next, which starts from it:

1. **Zones** - the city's zones (the default: nothing to decide, and the baseline's step 1 is
   taken as it is, in seconds) or a **zoning file** (GeoPackage, GeoJSON or zipped Shapefile; each
   census sector goes to the file's zone holding its centre, so people and jobs stay the
   census's). The network is the city's as it is: its speeds, capacities and lanes are not
   decided here. The step joins the zones to it and works out the free-flow times between zones;
   its preview is the zones map, their numbers and the zone list (`exports/zone_list.csv`) a
   matrix is written against;
2. **Demand** - the city's model, with a summary from people to trips and the gravity model's
   formula (the intrazonal share is one of its parameters), or an **O-D matrix file** (CSV
   origin, destination, trips, or OMX; vehicle trips in the modelled hour; zones named by the
   zoning file's ids, the zone codes or numbers); its preview is the trip groups and the
   trip-ends map;
3. **Assignment** - user equilibrium by bi-conjugate Frank-Wolfe, the BPR cost function (one α
   and β for every road: by road class is not built yet) and the convergence; then the results
   page.

**The day and the time of day** (step 2, `core/timeofday.py`, from the notebooks
`time_of_day_demo` and `weekday_weekend_demo`), in the page's three parts of step 2:

- **2a When** - a **weekday** or a **weekend day** (the average of a Saturday and a Sunday), and
  the **morning peak** (07:00), **midday** (12:00), **evening peak** (17:00), **night** (22:00) -
  an hour each - or the **whole day**. Every choice starts from the morning peak.
- **2b The morning peak** - the city's model, as before, with the pull weights suggested for the
  day (`ATTRACTION_RATES`, or on a weekend day `WEEKEND_ATTRACTION_RATES`: shops and leisure pull
  harder, workplaces and schools less) and the β the gravity model finds for them; or a loaded
  matrix, taken as the morning peak. This is B, one hour from home to activity.
- **2c From the morning peak to the choice** - only the numbers it uses:

    an hour   T = s · (f·B + (1 − f)·Bᵀ)        s = PERIOD_SCALE (or WEEKEND_PERIOD_SCALE),
                                                f = PERIOD_DIRECTION (1 out, 0 home, ½ both)
    the day   T = S · (B + Bᵀ) / 2, assigned against capacity × F,
              S = WEEKDAY_SIZE (× the average of SATURDAY_SUNDAY on a weekend), F = S ÷ max s

The default - a weekday morning peak - is the base matrix itself, so the model's results are
unchanged. Another day or hour leaves out Sorocaba's count comparison (its counts are a weekday's
at 07:00) and the yearly delay figure; the results say what was modelled.

The page shows the parameters a run decides (`core/steps.on_page`), each starting at the city's
settings' value and edited in its own shape (a number, whose arrows step by its last decimal, a
value per key, a row of numbers...); changed values are highlighted, with the settings' value
beside them. A step is done for the values it was computed with: change
a parameter or file of it, or of a step before it, and it needs computing again before Next - the
steps before it are kept. From a terminal: `python run.py <city> --run <name> --step zones`
(then `demand`, `assignment`), or without `--step` all three in one go.

**To compare road runs**, a city's Macrosimulation list opens `output/macro/compare_<city>.html`
once it has two runs (`core/macro_compare.py`): pick a baseline and an alternative, and see what
each changed (only the keys of a value per key it changed), a warning when they model different
days or hours, the headline numbers and trip groups side by side, the change in traffic on the
main roads on a map (more in orange, less in blue, width the change) and the 400 streets whose
vehicle-km changed most, sortable. Each run's numbers and flows are written once, as the pages
are built, into its `exports/compare_data.js`, and the main roads' lines into
`compare_<city>_network.js`; the page loads the two it compares, so it works opened as a file.
The map has two views, each in its own colours: Volume (more vehicles orange, fewer blue) and
Congestion (V/C - worse red, eased green), and a scenario's edits
are drawn on the map (closures in black, capacity gold, speed purple).

**Scenarios** (`/scenario/<city>`, `core/scenario_page.py`, served only) change the network of a
computed run, its base, and keep everything else: its zones, demand and trips are the base's
(steps 1-2 are copied from it, `core/steps.reuse`), and only the assignment is run again with the
edits applied (`core/edits.py`). An edit closes links, multiplies their capacity, or sets their
speed (km/h); links are picked on a map of the base's V/C - a click takes the road's stretch,
along the same street up to where another main road meets it (OSM cuts a road at every junction,
side streets too, so a link alone is a few dozen metres; shift+click takes one) - grown along a street, or taken from the
suggested corridors (the worst sections by delay, volume or V/C). The run file keeps
`"base"` and `"edits"` only; `run.py <city> --run <name>` runs it from a terminal too. Trips that
a closure leaves without a route are reported in the log. The results step of a run links to a
new scenario of it, and the Compare page opens a scenario against its base.

A scenario is of one **type** (`"type"` in its file, `runs.SCENARIO_TYPES`): it **closes roads**,
**changes their capacity or speed**, **builds new roads**, or **changes the demand** - one at a
time, as their effects are measured differently.
A closure moves traffic; a widening makes roads less congested, and usually draws *more* traffic
onto them, which a volume map would paint as worse. So a scenario's results page opens on
**Change from its base** (`change.html`, `core.maps.draw_scenario`) drawn for its type: a closure's
change in flow on each main road (more orange, less blue, under 25 veh/h not drawn; the closed
roads in black, each saying what it carried), or a capacity change's change in V/C (green eased, red
worsened, under 0.05 grey - below the threshold, not unchanged; the edited roads in a gold or purple
halo). Its **Overview** starts with the scenario (`scenario.json`, written with the map): its base,
its edits, the headline numbers beside the base's, then for a closure the streets gaining and
losing the most vehicle-km, and for a capacity change the edited roads' vehicles and worst V/C
before and after, and the streets that eased and worsened most. A **new road** is measured as a closure is, in
volumes: its map draws the new roads in teal, each with the vehicles it carries, and its Overview
lists each new road - class, lanes, speed, length, vehicles an hour, V/C - then the streets it
relieves and those gaining volume. A new road is drawn on the Scenarios page from a junction of
the main roads to another, through any points it bends through; its class sets its speed, lanes
each way and capacity a lane as the city's roads of that class have them (`SPEED_KMH`,
`DEFAULT_LANES`, `LANE_CAPACITY_BY_SPEED`), each editable, and it may be one way. The run adds it
to its copy of the network (`core.edits.add_road`: its ends exactly on the two nodes, so
AequilibraE joins it to them) and keeps its link id on the edit; the Compare page draws it from the
scenario's own data, as no other run has it. A **demand** scenario keeps the base's network and
changes its matrix as its assignment starts (`core/demand_edits.py`): trips added from zones to
others, a number for each pair (`"pairs": [[from, to, trips], ...]`, and as many back if asked) - or,
a file may say so, one number shared among the pairs as the base's trips between them are - a
development in a zone (residents' trips leaving at the city's trips per resident, where the zone's
trips go; jobs' trips arriving at the city's trips per job, or per resident where a city has no
jobs data), or a trip group - within, out of, into, through the city - grown by a percentage; the
Scenarios page offers the first, trips added between zones, a pair at a time - click the zone
the trips start from, the zone they go to, give the trips, add the pair, and on to the next - the
others being there for a run file to use. It is measured in volumes; its map draws the zones it edits, and its Overview the trips
each edit adds and the trip groups beside the base's. The Scenarios page shows its map as the zones
alone - blue, white borders, numbered from zoom 13, the pairs added drawn as lines -
(`/api/<city>/macro/<run>/zones`, the run's zones with their people, jobs and trips, kept as
`exports/zones_web.json`). A new scenario on the Scenarios page starts with its kind - close roads,
change capacity or speed, build a new road, change the demand - and only then shows the map (the
road network, or the base's congestion: a switch above it) and the edits of that kind (corridors ranked by traffic for a closure, by
vehicle-hours lost for a widening); a saved scenario opens on its own kind. Roads still selected
when it is saved become an edit too. The Compare page opens a capacity scenario on its V/C view.

A run is a small file listing only what it changes, `macro_runs/<city>/<name>.json`
(`core/runs.py`), with the files it loads beside it in `<name>_files/`, checked before anything is
saved. Its results go to `output/macro/<city>-<name>/`, beside the baseline's (with each step's
state, log and checkpoint in `steps/`), and its Parameters view marks each value it changed. The
values reach the settings module as it is imported (`core.settings.OVERRIDES`), so anything
worked out from them follows.

**To change an assumption** for every run, edit `cases/<city>/settings.py` and run again. Every assumed number
there goes through `assume()`, which records its unit and why; the full table is printed at the
end of a run and written to `assumptions.csv`. Choices of method (the OSM link types dropped, the
assignment's convergence gap and iterations...) go through `setting()`: not assumptions, but
listed with them in `parameters.csv`, each in its group (`GROUPS` in `core/parameter_groups.py`,
in the order the results page lists them; a name only one city has is grouped in its settings
module).

## Public transport: line designs and simulations

Two parts, kept apart: **line design** - the lines, their maps and timetable, no passengers -
and **simulation** - passengers assigned to a design.

```bash
python design.py quito                   # the baseline design's pages: output/transit/designs/quito-baseline/
python design.py quito l1_double         # designs/quito/l1_double.json
python design.py quito --all             # the baseline and every design
python run.py quito --transit            # simulate the baseline: output/transit/simulations/quito-baseline/
python run.py quito --transit --design l1_double   # simulate a design
python run.py quito --transit --out output/transit/test  # a test simulation elsewhere
python run.py quito --transit --rebuild-network    # download the study box's streets again
python run.py quito --transit --design l1_double --day saturday --period 10-14 --demand-factor 0.6
                                         # another day, hours, demand (also --walking-speed, --transfer-walk)
python -m transit.osm_lines sorocaba     # Sorocaba's lines from OpenStreetMap -> osm_transit/lines.json
python design.py sorocaba                # its baseline design
python run.py sorocaba --transit         # on the city's zones (the road model's), a uniform demand
```

**Sorocaba** has no GTFS feed of its city buses (ARTESP's covers only the regional routes), so
its lines come from OpenStreetMap's bus route relations (`transit/osm_lines.py`, extract in
`data/sorocaba/input/osm_transit/`, OSM 2026-10-12): the routes with most stops inside the city
limit, paired by direction, their stops in order (unnamed ones named after their street), a
station at each mapped terminal two lines or more stop at. OSM's slips are cleaned for a network
that looks right (a demo, not Urbes's network as it is): a direction is cut at any gap between
two stops in a row longer than `OSM_JUMP_KM` and `OSM_JUMP_FACTOR` times its usual spacing - a
stop of the far end listed first or last, a stretch of another route - keeping its longest piece;
two directions that do not meet at their ends (`OSM_ENDS_KM`) or differ much in length
(`OSM_LENGTH_RATIO`) become the longer one, run back by its stops reversed; a line left with fewer
than `OSM_MIN_STOPS` stops is dropped (the run's report lists each). A stop further than `MATCH_RADIUS_M`
from a street - the Santo Antônio terminal's bays, whose lanes OSM's street network leaves out, and
line 52's end - is moved onto the nearest street a bus can come and go along (not an island of
streets cut off from the rest), so every route map-matches. A design's build lists apart, folded
away in the editor, the warnings the baseline's build gives too. Headways (but 4), speeds and vehicle
places are assumed - `cases/sorocaba/transit_settings.py`, and `lines.json`'s report. Its designs
and editor work, and so does a simulation - on the road model's zones and a uniform demand, as
Quito's (below).

**Designs.** A design is a JSON file in `designs/<city>/` listing changes to the city's lines: a
new timetable for an existing line (`service`: headway, speed, dwell, hours, bands - its stops
untouched), a new headway, a frequency multiplier, a new speed (the older, single-field forms), an
existing line redrawn (`edit_line`: the same
fields as a new line's, its route and mode kept), a line added (mode, stops, headway, speed,
dwell, colour; out and back - back by the same stops reversed or by its own, `stops_back` - or
round a loop, one way or both ways, `loop`; its own service hours, `hours`, and other headways at
some hours, `bands`, written to `frequencies.txt` one row per stretch of one headway) or removed -
the format is in `transit/scenario.py`. A timetable is the weekdays'; `saturday` and `sunday` run it
too unless they say "none" (no service) or give a timetable of their own;
`designs/quito/l1_double.json` and `new_line_l2.json` are the notebook's two scenarios. The
*baseline* is a design too: the city's lines as `cases/quito/transit_inputs.py` gives them, with
no file. `design.py` builds a design's pages in a second or so (`transit/design.py`): its feed
(`exports/gtfs_feed.zip`: a service per type of day in `calendar.txt` - WEEKDAY, SATURDAY,
SUNDAY; one template trip per direction and day in `stop_times.txt`, with its headsign, and its
headway in `frequencies.txt`; the buses' shapes along the streets in `shapes.txt`, the metro's
stop to stop; a row per station (`location_type` 1) its platforms point to; a simulation imports a copy with every trip written out, because AequilibraE 1.6.2 drops the trips in `frequencies.txt`), every route and direction along the streets and stop to stop
(`exports/lines.geojson`; bus routes along the shortest way through the streets between their
stops, `transit/streets.py` - each stop on whichever street within 50 m makes the whole route
shortest, so a stop on a divided avenue takes the carriageway running its way - a preview of a
simulation's map matching, and what a bus's running times are measured on: each leg's length
along the streets at the line's speed (the metro's stop to stop); the metro runs in a
tunnel, stop to stop), what each line takes to run (`exports/operations.csv`, `transit/fleet.py`:
its round trip - both directions' running time and a layover at each terminus, `LAYOVER_SHARE`
of the running time and at least `LAYOVER_MIN_S` - the vehicles it needs at its shortest headway,
its vehicle-km and vehicle-hours on weekdays, Saturday, Sunday and in a week), a network map, and
a page with an overview (lines, stops, departures in the busiest hour, vehicles needed and
vehicle-km a weekday), Operations, its lines, and the Feed views (routes, service by hour, line diagrams, time-distance, stop timetables - on
weekdays - and calendar, each route on weekdays, Saturday and Sunday side by side, and the feed's
files).

**Simulations.** `run.py --transit` is the notebook `aequilibrae/notebooks/
quito_public_transit_demo.ipynb` (its Parts A and B): an AequilibraE project on the OSM streets
of the study box (downloaded once, kept in `data/quito/cache/transit_road_network/`), the
**road model's zones** - the city's own, built from its data (census sectors, people, jobs), no
road simulation needed: read from the road baseline's export if it has run, else from
`data/<city>/cache/city_zones.gpkg`, else built from the inputs (the road model's `prepare`, about
half a minute) and kept there (`project.city_zones`); those whose middle is in the study box
(`project.road_zones`; the line editor draws their outline, the area simulated) - the design's feed imported with the buses map-matched onto the streets, the
demand, the transit graph - with walking transfers routed on the streets between nearby stops,
and each zone joined to every stop within `ACCESS_RADIUS_M` of its middle (AequilibraE's
overlapping regions reach only the next zone's distance, a block among census zones) - and a
frequency-based hyperpath assignment (optimal strategies) for the 07:00-09:00 peak. The **demand
is a uniform matrix**: `TARGET_PEAK_TRIPS` (or the page's slider) shared evenly among every pair
of zones. A demand model for public transport is not implemented: the road model's matrices are
not recycled, as their gravity model's deterrence is the car's free-flow time, where public
transport's would be its own impedance (walk, wait, ride, transfers). Optimal strategies take no
parameter of their own; what shapes them is the graph, whose parameters a simulation may set
(`transit/options.py`): walking speed, the transfer walk, the walk to a stop (`ACCESS_RADIUS_M`),
the transfer penalty (`TRANSFER_PENALTY_S`, 480 s, at each change of vehicle - not at the first
boarding nor the last alighting) and the wait (`WAIT_TIME_FACTOR`, 0.5: half the combined headway
of the lines a passenger will take). The time a vehicle stands at a stop is each line's own, from
its design's timetable: AequilibraE times a ride from one stop's departure to the next's, so the
ride holds it, and the graph adds none (`transit/graph.py`'s notes). Walks do not pass through
zones. The journey time and its parts are of the trips that board, without the penalty; the trips
that walk the whole way are counted on their own. The Run a simulation page is in steps as a macrosimulation's: 1
Zones, 2 Demand, 3 Assignment, 4 Results. The feed audits (wide stations, one-way stops,
unmatchable stops, interchanges), the coverage and a uniform-demand structural check are printed
sections of the log, and a design's simulation compares itself with the baseline's there.
Assumptions are in `cases/quito/transit_settings.py`, the same `assume()`/`setting()` registry.
A simulation writes:

- `summary.json` - `kind: "transit"`, the city, the design simulated, the headline (trips,
  reach, boardings, passenger-hours, the journey and its parts) formatted, and `totals` raw;
- `exports/` - `zones.gpkg` (served or not, walk to the nearest stop, trips produced and
  attracted), `segments.csv` (passengers, places offered and share used per segment and
  direction), `segments.geojson` (each segment stop to stop, one per direction), `stops.csv`
  (boardings, alightings), `skims.csv` (every O-D pair with demand, times in minutes),
  `gtfs_feed.zip`, `parameters.csv`, `assumptions.csv`;
- `maps/` - `loads.html`, `2_coverage.html`, `3_capacity.html`, each redrawable from `map_data/`
  (`core.maps.redraw_maps`); on `loads.html`, as on a design's `network.html`, a line's box in
  the legend shows or hides it ("all" / "none" for every line), and pointing at a line there, or
  clicking it there or on the map, picks it out - bold, its stops shown, the others faded; a stop
  of one line is drawn in its colour, one several lines share white ringed grey, a station larger
  and ringed black. A design's `network.html` zoomed out (below `DETAIL_ZOOM`, 15) draws each
  line once and no stops; zoomed in, each direction on its own side and every stop. The
  editor's map shows the existing lines' stops the same way, and picks a line out when pointed
  at in Show or clicked on the map with no tool on;
- `run_log.txt`, and the working project in `aequilibrae/transit_project/`.

**The pages.** A city's Public transport opens on **Line design** and **Simulation**.
*Line design* lists the designs, each with its page, and opens the design
editor (when served). *Simulation* lists the simulations, each with its results page and a link
to its design, runs a simulation (when served), and compares simulations: on
`compare_<city>.html` any simulation is picked as the baseline and any other as the alternative -
the headline numbers side by side and what each design takes to run on the day simulated
(vehicles by mode, vehicle-km, vehicle-hours, and the trade in one line: passenger-hours saved per
extra vehicle-hour), a warning when the two simulated different days, hours or demand, a map of
where passengers moved (from each simulation's `segments.geojson`), every segment in both -
worked out in the browser, so it works opened as a file too. A simulation's Overview says what it
simulated and what its design takes to run that day.

**The editor and the simulation page.** `python serve.py` serves the same pages from a small
server on this computer (http://localhost:8000, not reachable from the network) and opens the
browser.

- **The line design editor** (`/editor/<city>`): start from the baseline or an existing design -
  the lines it added become existing lines here - and work in two parts, one under the other.
  **1. Where the lines run**: a map and a panel beside it. Add a line (route, name, bus or metro,
  colour; out and back, or a loop one way or both ways round - out and back, its *outward
  journey*'s stops come first, and under them its *return journey* is the same stops reversed
  until **Give it its own stops** copies them, reversed, to change from there: an *Outward* /
  *Return* switch then picks the journey edited, the return drawn dashed), or open an existing one
  (*Change the stops of an existing line*) to move, add or drop its stops - its old drawing shows
  faint and dashed underneath. In *Add stops* mode click the map to place stops in order - or an
  existing stop, to stop there too and take its station so passengers can change there - and in
  *Move stops* mode drag a stop; rename, reorder and drop stops in the list; a stop's *Station*
  menu joins it to a station within 300 m or makes it a new one (`EST_<NAME>`), which any line
  can then join - a new interchange. In *Shape the route*
  mode (buses) drag the route between two stops to make it pass through a point - a *via point*,
  numbered in its order along the leg, wherever it was grabbed; drag one to move it, click it to
  remove it; *Outward route* / *Return route* picks the journey shaped. Via points are saved with
  the line (`via`) and shape its route on the maps, the feed's shapes and everything measured
  along it - its running times, vehicle-km and vehicles needed. A bus stop is checked
  against the streets as it is placed: one further than `MATCH_RADIUS_M` from a street, or on a
  street cut off from the rest (an island in OSM's network no bus gets into or out of), is flagged
  and can be snapped onto the nearest street a bus can reach; a leg with no way along the streets
  is listed under the line and marked red on the map as it is drawn; a stop outside the study box is refused. The map shows the lines
  *stop to stop* or *along the streets*. **2. When they run**: a card per line, existing, edited
  and new - whether it runs, its first departure and end of service, its headway and other
  headways at some hours (the peaks), its speed, dwell and places per vehicle, and *Time between
  stops* - each leg's time estimated from its length at the speed, or set by hand - with its
  departures in each hour as
  bars, its vehicles an hour and its time end to end - on *Weekdays*, and on *Saturday* and
  *Sunday* the weekdays' timetable, one of their own, or no service. **Save design** writes a new line as
  `add_line`, an existing line whose stops changed as `edit_line` (timetable included), one whose
  timetable alone changed as `service`, one that no longer runs as `remove_line` - under the name
  given (keep it to change a design, give another to keep both; lower-case letters, digits and
  _ - no "-", which joins a simulation's options to its design's name) - and builds its pages, then
  offers them and a simulation of it, with what the build found to look at (bus stops too far
  from a street, legs with no way along the streets, leg times set by hand at an implausible
  speed, stations only one line uses). **↶ Undo** (Ctrl+Z) steps back through the changes;
  **Duplicate** copies a line - on the map or from its timetable card - as a new one; leaving the
  page or starting from another design with unsaved changes asks first. A leg's time set by hand,
  like its via points, belongs to the stop the leg starts from, so it follows that stop when
  stops are added, moved or reordered.
- **The simulation page** (`/simulate/<city>`): choose a design and what the simulation runs
  (`transit/options.py`): the type of day - weekday, Saturday or Sunday, its timetable imported
  for `SERVICE_DAY` or the weekend after it - the period, the demand (the baseline's weekday-peak
  matrix, times a factor: another day or period at 1 asks how the peak's travellers would fare
  on that service, not how many travel then), the walking speed and the walk between stops that
  joins them. At the defaults a simulation is its design's (`l1_double`); anything else is in its
  name (`l1_double-saturday-10-14-x0.6`), so it sits beside the default one. The page says what
  it will be saved as and whether that exists; **Run the simulation** runs
  `run.py <city> --transit --design <name>` with those options in
  the background with its log shown live, and a button then opens the results. One simulation at
  a time.
- **Deleting**: when served, every design and simulation card in the two lists has a *Delete*
  button. Deleting a design removes its file and its pages and keeps its simulation; deleting a
  simulation removes its results folder and keeps the design. The baseline cannot be deleted (its
  simulation holds the demand every other simulation reads), nor anything being built or simulated.

## Layout

```
run.py                      command line: python run.py <city> [--transit]
view.py                     open the results pages: python view.py [<city> [--transit]]
serve.py                    the pages, the line design editor and simulations, served: python serve.py
design.py                   a public-transport design's pages: python design.py <city> [<design>]
compare_reference.py        a run's exports against the notebook's
core/                       shared: knows nothing about any one city
  pipeline.py               the run, step by step, and the hooks a city fills in
  settings.py               the assume() registry
  zoning.py                 adjacency, connected pieces, split large, merge small, renumber, centroids
  network.py                OSM download and cache, non-roads dropped, OSM tag repair, Overpass
  connectors.py             zones into the model, stranded centroids, extra connectors
  costs.py                  speed, capacity, free-flow time; roundabouts
  skim.py                   free-flow skim, checked, diagonal filled
  gravity.py                gravity model solved for a mean trip length; matrix checks
  assignment.py             user-equilibrium assignment and how the network carries it; delay
  maps.py                   hover panel, backdrop, legends, choropleth; the zones and simulation maps
  export.py                 zones.gpkg, od_matrix.csv.gz/.omx (read back), link_volumes.gpkg, assumptions.csv
  summary.py                the run's headline numbers, summary.json
  viewer.py                 the results page, index.html, built from what the run left
  stats.py                  its Statistics views: travel times, distances, network load, streets
  transit_stats.py          ... for a public-transport run: journeys, rides, stops, coverage
  gtfs_views.py             its Feed views, read from the GTFS zip
  compare_page.py           the Compare page: any two simulations of a city
  server.py                 serve.py's server: the pages, the editor's API, runs started from it
  editor_page.py            the line design editor's page
  simulate_page.py          the simulation page: choose a design, run it
  design_stats.py           a design page's Overview and Lines
  network_classes.py        road classes and congestion bands, shared by the map and the page
  parameter_groups.py       which group each parameter is listed under, and in what order
  paths.py, report.py       where things are; printing and the log file
transit/                    the public-transport run, knowing nothing about any one city
  pipeline.py               the run, step by step (A1-A7 build, B2-B7 solve and read out)
  project.py                streets from the cache, the road model's zones, the period, the feed import
  gtfs.py                   write_gtfs from a dict of lines; wide, one-way and unmatchable stops
  demand.py                 the earlier synthetic peak matrix (no longer used: the demand is uniform)
  graph.py                  stops and segments read back, walking transfers, the transit graph
  assignment.py             the solve, ScenarioResult, coverage, the structural check
  maps.py                   network, alignment, coverage, loads, capacity
  export.py                 zones.gpkg, segments/stops/skims.csv, summary.json
  paths.py                  designs/, output/transit/designs|simulations/, the street cache
  scenario.py               a design file read, checked and applied to the lines
  design.py                 a design's pages: feed, lines along the streets, network map
  streets.py                how far a point is from a street a bus can be matched onto (editor)
  compare.py                a simulation against the baseline's, in its log
designs/<city>/             design files: python design.py <city> <name>; run.py --transit --design <name>
cases/
  quito/                    settings, model (barrios, sectors, zones, cadastre floor area, AMT check), maps
    transit_settings.py     the public-transport run's assumptions
    transit_inputs.py       its study box, the GTFS lines, the unserved corridor, line colours
  sorocaba/                 settings, model, and:
    inputs.py               sectors, áreas de ponderação, 2010 sample, CNEFE x CEMPRE jobs, zones, commuting
    external.py             gateways, cordon zones, regional routing, external zones
    demand.py               trip generation, trips across the city limit, through traffic, the matrix
    counts.py               ARTESP counts: placing them, GEH, levers, the edge calibration (F7)
    maps.py                 jobs, external zones, gateways, counts
    transit_settings.py     public transport: the OSM lines' assumed headways, speeds, places;
                            the uniform demand's trips, the assignment graph's parameters
    transit_inputs.py       study box, agency, calendar, LINES from data/sorocaba/input/osm_transit/lines.json
data/<city>/input/          the input files the notebooks read, copied from the original projects
data/<city>/cache/          downloads kept between runs (OSM network, regional roads, km posts...)
data/<city>/reference/      the exports the notebooks last wrote, for compare_reference.py
assets/attlas_logo.png      on the left of the bar across the top of every page, in the bar's colour,
                            then the tool's name (core/viewer.BAR_TITLE, "Macro & Transit Prototype")
assets/attlas_icon.png      its symbol, every page's tab icon (both written into the pages by
                            core/viewer: replace a file and run view.py)
output/index.html           the start page: the cities
output/<city>/              a city's pages: index.html (both models, side by side), macro.html,
                            designs.html, simulations.html (transit.html sends to index.html)
output/macro/<city>/        a road run: index.html, maps/, exports/, map_data/, aequilibrae/road_model/,
                            run_log.txt, summary.json, stats_cache.json (its Statistics, kept
                            until its exports change: delete it to have them computed again)
output/transit/designs/<city>-<design>/      a design's pages: index.html, maps/, exports/
output/transit/simulations/<city>-<design>/  a simulation: index.html, maps/, exports/,
                            map_data/, aequilibrae/transit_project/, run_log.txt, summary.json
```

## What is shared and what is not

| step | Quito | Sorocaba | where |
|---|---|---|---|
| inputs | barrios, parroquia population, INEC sectors | IBGE sectors, áreas de ponderação, 2010 sample | case |
| zoning | census zona cut at parroquias; merge < 500, then split > 8,000 people | weighting area; split > 4,000 people+jobs, then merge < 1,000 | rules shared, recipe in case |
| attractions | cadastre floor area x land-use class | CNEFE addresses x CEMPRE jobs | case |
| car share | constant (Municipio) | by zone, from 2010 car ownership | case |
| network, connectors, costs, skim | | | shared |
| external traffic | none | gateways, external zones, commuting, through trips | Sorocaba |
| zones map | | | shared: same inputs (zone, pop, area_km2, n_sectors, centroid) |
| gravity, assignment, simulation map, delay, exports | | | shared |
| validation | AMT's ten worst roads | ARTESP counts, edge calibration | case |

## Where the program differs from the notebooks

Where the two notebooks had drifted apart, the shared code takes Sorocaba's newer version, which
fixed things found after Quito was built:

- **link costs**: an OSM `maxspeed` of 0 is treated as missing, and a one-way link has no
  capacity in the direction it does not run;
- **roundabouts**: a ring already carrying more than its largest approach keeps its own capacity,
  and `junction=circular` counts too;
- **stranded zones**: found on the roads alone, so a zone cannot reach the network through
  another zone's centroid;
- **maps**: the Esri light-grey backdrop (CARTO Positron now asks for an API key). The zones and
  simulation maps are drawn by the same code for every city (`core/maps.py`): no parroquia or
  weighting-area outlines, no gateways, and the same info panel; the simulation (congestion) map
  has one layer per road class.

For Quito the zones and everything built on them (floor area, productions, attractions) are
identical to the notebook's. The matrix and the assignment differ slightly, because the corrected
capacities move a few zones' extra connector: the trip-matrix cells correlate at 0.9999, link
flows at 0.997.

Two Sorocaba steps are switched off for Quito to keep its results: the OSM tag repair
(`REPAIR_OSM_TAGS`) and the longer list of non-road link types (`NOT_ROADS`). Both are settings.

## Internal and external zones

A city's own zones, inside its limit, are numbered 1..n; a city with traffic from beyond the
limit adds **external zones** after them, one per road crossing the limit. Sorocaba has 25 (its
commuting, through traffic and ARTESP counts, `cases/sorocaba/external.py`); Quito has none - its
zones cover the whole district, and the traffic from beyond it (Rumiñahui, the Panamericana north
and south) is not modelled. The shared code works with none or any number: every trip is
**within the city**, **from the city out**, **from outside in** or **through** (`TRIP_GROUPS` in
`core/summary.py`), printed after the demand in the log, recorded in `summary.json` and shown on
the Overview. Figures over the whole network (vehicle-hours, delay, the network's load) count
every trip; figures about trips (travel times, distances) count those within the city, and say so.

## Adding a city

Write `cases/<city>/settings.py` (copy one) and a `CityModel` subclass that fills in `prepare()`
(read inputs, build `zones` with `zone`, `zone_number`, `centroid`, `pop`, geometry),
`network_outline()`, `travel_share()`, `build_demand()` and `export()`. Register it in
`cases/__init__.py`. Everything else - network, costs, skim, assignment, maps, exports - comes from
`core`.

## Checking nothing broke

What the model is known not to do, or does questionably, is in [LIMITATIONS.md](LIMITATIONS.md).
`python tests/toy_networks.py` checks the assignments against answers worked out by hand.

```bash
python tests/regression.py            # PASS, or what changed
python tests/regression.py --update   # after a change meant to move the results
```

Rebuilds the reference designs (the baseline and the notebook's two scenarios), simulates them into
a scratch folder - the results pages are left alone - and compares their feeds, operations and
simulation results with `tests/expected_quito.json`. About three minutes.

```bash
python tests/regression_road.py --quick   # Sorocaba: road baseline, a scenario of each kind, public transport
python tests/regression_road.py           # and Quito's road model too
python tests/regression_road.py --update  # after a change meant to move the results
```

The road model's counterpart, against `tests/expected_road.json`: the baseline run in one go into a
scratch folder (totals, trip groups, the 20 busiest streets), and a closure, a capacity change, a
new road and added trips made on the city's computed baseline (deleted after).

```bash
python tests/invariants.py               # Sorocaba; --city quito, --only road / --only transit
```

Checks what must hold whatever the numbers: a neutral edit changes nothing, a closure adds
vehicle-hours, added trips are exactly that many more, vehicles leaving the zones arrive, the staged
baseline equals the one-go one, public-transport trips add up. Report in
`tests/invariants_report.txt`.

```bash
python tests/interface.py                     # every flow, on Sorocaba: about a quarter of an hour
python tests/interface.py --only crawl,bad,files   # the quick ones
```

The pages as someone uses them: headless Chrome (Playwright, `pip install playwright`; it drives
the Chrome already installed) clicks through them on a server of its own (port 8765) - a road run
step by step, a scenario of each kind made on the map, a line drawn in the editor and simulated
twice, deletes, wrong input, the server stopped mid-run, the pages opened as files. What it makes
is named `zzi_...` and deleted after. Report in `tests/interface_report.txt`; a failed check leaves
a screenshot in `tests/interface_shots/`.
