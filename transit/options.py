"""What a simulation runs: the type of day, the period, the trips, and the assignment's
parameters - the walking, the transfers, the wait, the walk to a stop. The time a vehicle stands
at a stop is each line's own, from its design's timetable (graph.py).

Left at their defaults - a weekday, the city's PERIOD_HOURS, its TARGET_PEAK_TRIPS, its walking,
transfer penalty, wait and walk to a stop - a simulation is its design's, and named as it
("l1_double"). Anything else is in its name too, so a design's simulations on other days or with
other parameters sit beside its default one instead of replacing it: "l1_double-saturday-t20000".

The demand is a uniform matrix: `trips` in the period, shared evenly among every pair of zones
(the road model's zones). The road model's matrices are not reused: their gravity model's
deterrence is the car's free-flow time, where public transport's would be its own impedance.
"""
import datetime
from dataclasses import dataclass

DAYS = {"weekday": "weekday", "saturday": "Saturday", "sunday": "Sunday"}
WEEKDAY_NUMBER = {"saturday": 5, "sunday": 6}


@dataclass
class Options:
    day: str = "weekday"
    period: tuple = None              # (start hour, end hour); None: the city's PERIOD_HOURS
    trips: float = None               # in the period; None: the city's TARGET_PEAK_TRIPS
    walking_speed: float = None       # m/s; None: the city's WALKING_SPEED
    transfer_walk_m: float = None     # m; None: the city's TRANSFER_WALK_M
    transfer_penalty_s: float = None  # s at each change of vehicle; None: TRANSFER_PENALTY_S
    wait_factor: float = None         # share of the headway waited; None: WAIT_TIME_FACTOR
    access_m: float = None            # m from a zone to its stops; None: ACCESS_RADIUS_M

    def check(self):
        """Raise ValueError for an option that cannot be run."""
        if self.day not in DAYS:
            raise ValueError(f"the day is one of {', '.join(DAYS)}, not {self.day!r}")
        if self.period is not None:
            a, b = self.period
            if not (0 <= a < b <= 24) or a != int(a) or b != int(b):
                raise ValueError(f"the period is whole hours, start before end, within the day: "
                                 f"not {a}-{b}")
        if self.trips is not None and not 0 < self.trips <= 10_000_000:
            raise ValueError("the trips are more than 0")
        if self.transfer_penalty_s is not None and not 0 <= self.transfer_penalty_s <= 3600:
            raise ValueError("the transfer penalty is between 0 and 3,600 s")
        if self.wait_factor is not None and not 0.1 <= self.wait_factor <= 1:
            raise ValueError("the wait is between 0.1 and 1 times the headway")
        if self.access_m is not None and not 0 <= self.access_m <= 3000:
            raise ValueError("the walk to a stop is between 0 and 3,000 m")
        if self.walking_speed is not None and not 0.3 <= self.walking_speed <= 3:
            raise ValueError("a walking speed is between 0.3 and 3 m/s")
        if self.transfer_walk_m is not None and not 0 <= self.transfer_walk_m <= 2000:
            raise ValueError("the transfer walk is between 0 and 2,000 m")
        return self

    def resolved(self, s):
        """Every option with a value: the city's settings where this one has none."""
        given = lambda value, default: default if value is None else value      # noqa: E731
        return Options(self.day, tuple(self.period or (s.PERIOD_START_H, s.PERIOD_END_H)),
                       given(self.trips, s.TARGET_PEAK_TRIPS),
                       given(self.walking_speed, s.WALKING_SPEED),
                       given(self.transfer_walk_m, s.TRANSFER_WALK_M),
                       given(self.transfer_penalty_s, s.TRANSFER_PENALTY_S),
                       given(self.wait_factor, s.WAIT_TIME_FACTOR),
                       given(self.access_m, s.ACCESS_RADIUS_M))

    def pieces(self, s):
        """What differs from the defaults, as parts of a name: ["saturday", "10-14", "x0.6"]."""
        r = self.resolved(s)
        out = []
        if r.day != "weekday":
            out.append(r.day)
        if r.period != (s.PERIOD_START_H, s.PERIOD_END_H):
            out.append(f"{r.period[0]:02d}-{r.period[1]:02d}")
        if r.trips != s.TARGET_PEAK_TRIPS:
            out.append(f"t{r.trips:g}")
        if r.walking_speed != s.WALKING_SPEED:
            out.append(f"walk{r.walking_speed:g}")
        if r.transfer_walk_m != s.TRANSFER_WALK_M:
            out.append(f"transfer{r.transfer_walk_m:g}")
        if r.transfer_penalty_s != s.TRANSFER_PENALTY_S:
            out.append(f"penalty{r.transfer_penalty_s:g}")
        if r.wait_factor != s.WAIT_TIME_FACTOR:
            out.append(f"wait{r.wait_factor:g}")
        if r.access_m != s.ACCESS_RADIUS_M:
            out.append(f"access{r.access_m:g}")
        return out

    def name(self, design, s):
        """The simulation's name: its design's, and what differs from the defaults."""
        return "-".join([design] + self.pieces(s))

    def record(self, s, weekday_date, calendar=None):
        """What summary.json says of the simulation's options, in values and in words."""
        r = self.resolved(s)
        date = service_date(weekday_date, r.day, calendar)
        period = f"{r.period[0]:02d}:00-{r.period[1]:02d}:00"
        short = []
        if r.day != "weekday":
            short.append(DAYS[r.day])
        if r.period != (s.PERIOD_START_H, s.PERIOD_END_H):
            short.append(period)
        if r.trips != s.TARGET_PEAK_TRIPS:
            short.append(f"{r.trips:,.0f} trips")
        if r.walking_speed != s.WALKING_SPEED:
            short.append(f"walking {r.walking_speed:g} m/s")
        if r.transfer_walk_m != s.TRANSFER_WALK_M:
            short.append(f"transfers up to {r.transfer_walk_m:g} m")
        if r.transfer_penalty_s != s.TRANSFER_PENALTY_S:
            short.append(f"transfer penalty {r.transfer_penalty_s:g} s")
        if r.wait_factor != s.WAIT_TIME_FACTOR:
            short.append(f"waiting {r.wait_factor:g} of the headway")
        if r.access_m != s.ACCESS_RADIUS_M:
            short.append(f"stops up to {r.access_m:g} m away")
        day = (f"a weekday ({_weekday_name(date)} {date})" if r.day == "weekday"
               else f"{DAYS[r.day]} {date}")
        return {"day": r.day, "date": date, "period": period, "trips": r.trips,
                "walking_speed": r.walking_speed, "transfer_walk_m": r.transfer_walk_m,
                "transfer_penalty_s": r.transfer_penalty_s, "wait_factor": r.wait_factor,
                "access_m": r.access_m,
                "said": (f"{day}, {period}, {r.trips:,.0f} trips (a uniform matrix), walking "
                         f"{r.walking_speed:g} m/s, transfers up to {r.transfer_walk_m:g} m, "
                         f"{r.transfer_penalty_s:g} s a transfer, waiting {r.wait_factor:g} of "
                         f"the headway, each line's time at a stop, "
                         f"stops up to {r.access_m:g} m from a zone's middle"),
                "short": " · ".join(short)}

    def apply(self, s):
        """Set the period and the walking on the settings module `s` - and in its record of
        them, so parameters.csv says what was run."""
        r = self.resolved(s)
        s.PERIOD_START_H, s.PERIOD_END_H = r.period
        s.WALKING_SPEED, s.TRANSFER_WALK_M = r.walking_speed, r.transfer_walk_m
        s.TRANSFER_PENALTY_S, s.WAIT_TIME_FACTOR = r.transfer_penalty_s, r.wait_factor
        s.TARGET_PEAK_TRIPS, s.ACCESS_RADIUS_M = r.trips, r.access_m
        if "PERIOD_HOURS" in s.ASSUMED.settings:
            s.ASSUMED.settings["PERIOD_HOURS"]["value"] = tuple(r.period)
        for name, value in (("WALKING_SPEED", r.walking_speed),
                            ("TRANSFER_WALK_M", r.transfer_walk_m),
                            ("TRANSFER_PENALTY_S", r.transfer_penalty_s),
                            ("WAIT_TIME_FACTOR", r.wait_factor),
                            ("TARGET_PEAK_TRIPS", r.trips),
                            ("ACCESS_RADIUS_M", r.access_m)):
            if name in s.ASSUMED.entries:
                s.ASSUMED.entries[name]["value"] = value
        return r


def service_date(weekday_date, day, calendar=None):
    """The date a type of day is imported on: the city's weekday SERVICE_DAY, or the Saturday or
    Sunday after it - or the one before, if that would fall after `calendar`'s end_date: a date
    the feed has no service on would import no trips at all."""
    date = datetime.date.fromisoformat(weekday_date)
    if day in WEEKDAY_NUMBER:
        date += datetime.timedelta(days=(WEEKDAY_NUMBER[day] - date.weekday()) % 7)
        if calendar and date.strftime("%Y%m%d") > str(calendar["end_date"]):
            date -= datetime.timedelta(days=7)
    return date.isoformat()


def _weekday_name(iso):
    return datetime.date.fromisoformat(iso).strftime("%A")
