# Known limitations

What the model cannot do, assumes without evidence, or does in a way that is known to be
questionable. It was written from the method review of 2026-10-15 (layer 3 of the test plan), and
updated on 2026-10-16 when its recommended fixes were made (listed at the end). Each item says what
it affects. Items marked **open** wait for a decision; the others are how the prototype is meant
to be.

## Road model

**Calibration**
- **Sorocaba is calibrated only against highway counts.** The 32 counted directions are all on
  SP-270, SP-075 and SP-264; the city's own streets have none.
  - **The 11 edge counts calibrate the region's traffic** (F7: REGIONAL_TRIP_FACTOR,
    THROUGH_TRIPS). They match as a sum by construction, but individually only 18% are within
    GEH 5.
  - **The other 21 are the check:** the model carries 0.73 of their traffic, and 19% are within
    GEH 5 (practice aims for about 85%).
  - **One factor serves every approach and both directions (open):** a factor per approach,
    fitted to its own counts, would use more of what the counts say.
  - **THROUGH_SHARE cannot be told from the counts:** any value matches the edges. It needs the
    gantries' plate matches; until then, a sensitivity range.
  - **The counts barely constrain the city's own trips:** internal trips make 0.10 of the counted
    flow. Trucks are not modelled, though they take the highways' capacity.
- **Sorocaba's morning peak is almost free-flowing (open).** Congestion adds 2.6% to travel time,
  0.27 minutes per trip, against 34% in Quito. Likely contributors: too little traffic (above),
  short trips (MEAN_TRIP_MIN 9 min, no trip over 30 min within the city) and generous capacities.
  Treat Sorocaba's delays and V/C as indicative.
- **The mean trip time sets the gravity model.** There is no observed trip length distribution.
  MEAN_TRIP_MIN is chosen near the top of what the network allows (3.0 to 10.5 min). It is the
  biggest uncalibrated lever on where trips go.
- **There are no surveys behind the trip rates.** TRIPS_PER_PERSON 0.24 per peak hour, car share
  and occupancy come from rules of thumb and the 2010 census sample. The day and period factors
  (WEEKDAY_SIZE, PERIOD_SCALE, PERIOD_DIRECTION) are also assumptions.

**Assignment**
- **One BPR α and β (0.15, 4) for every road class.** A pair per class is not built yet; the run
  page says so.
- **Convergence is a choice.** The relative gap defaults to 1e-4, chosen on the run page's step 3
  and on the Scenarios page (a scenario's own, beside its base's). 1e-3 is looser than many
  scenarios' effects; a scenario and its base are best compared at the same gap.
- **A whole-day run is the busiest hour repeated all day.** The day's matrix is assigned against
  capacity × S / the busiest hour's share. Every trip gets peak-hour congestion, so a day's delay
  and V/C read like the peak's.
- **Trips a closure strands are dropped from the time totals.** They are reported, but the
  scenario's vehicle-hours lose their time while the trip count keeps them. So a closure that
  strands trips looks a little better than it is.

**Network** (from OpenStreetMap)
- **Quito's network is used without the OSM tag repair (open).** REPAIR_OSM_TAGS is off.
  - 704 of its 800 roundabout links are two-way.
  - Slip roads take their parent class's speed and lanes.
  - `oneway=-1/1/true` streets are modelled as two-way.
- **Connectors can land on motorway and trunk nodes.** This affects 4 Sorocaba connectors and 13
  in Quito: traffic enters an expressway mid-carriageway. The effect is small and local.
- **A speed edit keeps the road's capacity.** The base network sets capacity per lane by speed
  band, but a speed scenario changes only the speed. Change capacity with its own edit.
- **Odd lane counts round up when split between directions.** A two-way road tagged 3 lanes
  becomes 2 + 2, and 1 lane becomes 1 + 1 (Quito: 128 and 358 links).

**Dormant** (not reachable from the pages)
- **Development edits (`develop`, run files only) treat a zone's trips as morning-peak
  ones.** In other periods new residents' trips go in the wrong direction (evening) or in one
  direction only (midday, night, whole day).

## Public transport

How a passenger's time is counted (since 2026-10-16; `transit/graph.py` has the notes):
- **A ride holds the dwell at the stop it reaches**, each line's own from its timetable, once.
  AequilibraE's import keeps a stop's departure as its arrival too, so a ride runs from departure
  to departure; the graph adds no dwell of its own.
- **The wait is WAIT_TIME_FACTOR (0.5) of the combined headway** of the lines a passenger will
  take - passengers arriving at random at services that keep their timetable. It is a simulation
  option.
- **The transfer penalty is paid at each change of vehicle only**, not at the first boarding nor
  the last alighting.
- **Walks do not pass through zones** (`blocking_centroid_flows`).
- **The journey time and its parts are of the trips that board**, without the penalty; the wait
  is the wait alone, and a change made on foot counts as a transfer. Trips that walk the whole way
  are counted on their own.

**By design for now**
- **The demand is uniform.** The trips are shared evenly over every pair of zones; there is no
  public-transport demand model. Only pairs with a stop in reach at both ends can travel: 18% of
  the trips in Sorocaba and 3% in Quito.
- **A period with changing headways uses the busiest frequency.** AequilibraE takes a line's
  shortest headway in the period for the whole period. A line that changes headway, starts or
  stops within it is overstated. The current runs have constant headways.
- **Distances use two measures.** AequilibraE's own connectors and walks inside a station use Web
  Mercator, which is about 9% long at Sorocaba's latitude. The project's own access and transfer
  walks are in metres.
- **The lines are synthetic.** Sorocaba's lines come from OpenStreetMap with assumed headways
  (only 4 are known) and synthetic stops. Quito's are hand-written.

## Checks behind this

- **`tests/toy_networks.py`** checks the assignments against answers worked out by hand.
  - **Roads:** all 15 checks pass (flows, times, vehicle-hours, V/C, a closure, a two-hour period).
  - **Public transport:** all 18 checks pass (frequencies, the wait at a stop and at a change,
    the split between lines, the penalty at a change only, the journey and its parts, transfers,
    alightings).
- **`tests/invariants.py`, `tests/regression_road.py`, `tests/regression.py`** check what must
  always hold, and that results stay the same between changes.
- **`tests/interface.py`** checks the pages.

## Fixed on 2026-10-16

- **Public transport:**
  - the dwell counted twice
  - the full-headway wait
  - the penalty at every alighting
  - walks through zones
  - waiting and journey time holding the penalty
  - transfers on foot not counted
  - averages that included the walkers
  - the demand matrix indexed by graph node, which only worked while walks could pass through
    zones
- **Road model:**
  - the convergence target, now 1e-4 and chosen on the pages
  - a loaded matrix in a whole-day run assigned against an hour's capacity
  - the compare page's vehicle-hours left out the centroid connectors
- **Pages:** a road on the Scenarios map takes a click within 6 px of it.
- **Sorocaba's counts:**
  - F3 says the calibrating counts and the check apart.
  - F7 measures each part of the matrix - internal, external, through - inside the baseline's own
    equilibrium (one assignment, a class each). Its through trips used to be assigned alone on
    empty roads, where the solver reported a gap of infinity for 250 iterations.
