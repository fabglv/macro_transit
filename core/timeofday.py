"""The day and the time of day a run models: its matrix, from the morning peak the demand step
builds, and the capacity it is assigned against.

Every choice starts from the **morning peak** B: one hour of trips from home to activity - the
city's model (on a weekend day with the weekend's pull weights, and the beta the gravity model
finds for them) or a loaded matrix. Then, as the notebooks time_of_day_demo and
weekday_weekend_demo do it:

    an hour     trips = s(day, period) × ( f(period) · B + (1 − f(period)) · Bᵀ )
    the day     trips = S(day) × (B + Bᵀ) / 2,   assigned against capacity × F(day)

    s   the hour's traffic against the weekday morning peak (PERIOD_SCALE on a weekday,
        WEEKEND_PERIOD_SCALE on a weekend day)
    f   the share of the hour's trips going from home to activity; the rest go back - Bᵀ, the
        matrix turned round. 1 in the morning, 0 in the evening, ½ when both ways balance
        (PERIOD_DIRECTION). Practice writes it f·T + (1−f)·Tᵀ and takes f from a travel survey.
    S   the day's traffic in weekday-morning-peak hours: WEEKDAY_SIZE on a weekday; on a weekend
        day WEEKDAY_SIZE × the average of Saturday's and Sunday's share of it (SATURDAY_SUNDAY)
    F   S ÷ the day's busiest hour s: capacity is per hour, so a day's matrix is assigned as if
        its busiest hour lasted all day

The weekday morning peak - s = 1, f = 1 - is the morning peak itself: the model as it was.
"""
import numpy as np

DAYS = ["weekday", "weekend"]
PERIODS = ["morning peak", "midday", "evening peak", "night", "whole day"]
HOURS = {"morning peak": "07:00-08:00", "midday": "12:00-13:00", "evening peak": "17:00-18:00",
         "night": "22:00-23:00", "whole day": "the whole day"}
DAY_SAID = {"weekday": "weekday", "weekend": "weekend day"}


def day_size(s, day):
    """S: the day's traffic, in weekday-morning-peak hours."""
    if day == "weekday":
        return float(s.WEEKDAY_SIZE)
    saturday, sunday = s.SATURDAY_SUNDAY
    return float(s.WEEKDAY_SIZE) * (saturday + sunday) / 2


def hour_scales(s, day):
    return dict(s.PERIOD_SCALE if day == "weekday" else s.WEEKEND_PERIOD_SCALE)


def terms(s):
    """{"s", "f", "F"} for the run's day and period."""
    day, period = s.DAY, s.PERIOD
    if period == "whole day":
        size = day_size(s, day)
        return {"s": size, "f": 0.5, "F": size / max(hour_scales(s, day).values())}
    return {"s": float(hour_scales(s, day)[period]), "f": float(s.PERIOD_DIRECTION[period]),
            "F": 1.0}


def check(s):
    """The day and period are ones this knows, with every number they need."""
    if s.DAY not in DAYS:
        raise ValueError(f"DAY is {s.DAY!r}: one of {', '.join(DAYS)}")
    if s.PERIOD not in PERIODS:
        raise ValueError(f"PERIOD is {s.PERIOD!r}: one of {', '.join(PERIODS)}")
    for name in ("PERIOD_SCALE", "WEEKEND_PERIOD_SCALE", "PERIOD_DIRECTION"):
        missing = [p for p in PERIODS[:-1] if p not in getattr(s, name)]
        if missing:
            raise ValueError(f"{name} has no {', '.join(missing)}")
    if not 0 <= s.PERIOD_DIRECTION.get(s.PERIOD, 0.5) <= 1:
        raise ValueError("a direction share f is between 0 and 1")


def is_base(s):
    """The weekday morning peak at s = 1, f = 1: the base matrix as it is."""
    t = terms(s)
    return s.DAY == "weekday" and s.PERIOD != "whole day" and t["s"] == 1 and t["f"] == 1


def apply(base, s):
    """The run's matrix from its day's base matrix."""
    t = terms(s)
    if is_base(s):
        return base
    return t["s"] * (t["f"] * base + (1 - t["f"]) * base.T)


def capacity_factor(s):
    """F: what a link's hourly capacity is multiplied by - 1 for an hour."""
    return terms(s)["F"]


def label(s):
    """"weekday, morning peak 07:00-08:00", "weekend day, the whole day"."""
    if s.PERIOD == "whole day":
        return f"{DAY_SAID[s.DAY]}, the whole day"
    return f"{DAY_SAID[s.DAY]}, {s.PERIOD} {HOURS[s.PERIOD]}"


def unit(s):
    """What the matrix and the flows count: "the hour", or "the day"."""
    return "the day" if s.PERIOD == "whole day" else "the hour"


def describe(s, base, matrix):
    """What the step prints: the formula with its numbers."""
    t = terms(s)
    print(f"\nModelled: {label(s)}")
    if s.PERIOD == "whole day":
        print(f"  trips in the day = S × (B + B') / 2,  S = {t['s']:.2f} weekday-morning-peak hours"
              + ("" if s.DAY == "weekday" else
                 f" ({s.WEEKDAY_SIZE} × the average of {s.SATURDAY_SUNDAY[0]} and "
                 f"{s.SATURDAY_SUNDAY[1]})"))
        print(f"  assigned against capacity × F, F = {t['F']:.2f} (S over the busiest hour's "
              f"{max(hour_scales(s, s.DAY).values()):.2f})")
    elif is_base(s):
        print("  the base matrix as it is: the weekday morning peak, from home to activity")
    else:
        print(f"  trips in the hour = s × (f·B + (1 - f)·B'),  s = {t['s']:.2f}, f = {t['f']:.2f}")
    print(f"  base matrix {base.sum():,.0f} trips -> {matrix.sum():,.0f} vehicle trips in "
          f"{unit(s)}")
    if not np.isclose(matrix.sum(), t["s"] * base.sum(), rtol=1e-9):
        raise ValueError("the period's matrix does not hold s times the base matrix's trips")
