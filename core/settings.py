"""Every value the model decides rather than measures goes through `Assumptions.assume()`.

Each city's settings module holds one `Assumptions` registry and registers its numbers in it, so
the full table - value, unit and the reason for it - can be printed at the end of a run and
written to `assumptions.csv`.

Choices of method - which links are not roads, how close the assignment must converge - go through
`setting()` instead: they are not guesses about the city, so they are not counted or printed as
assumptions, but they are parameters a run can be changed by. Both are written to
`parameters.csv`, each in the group of the model it belongs to (GROUPS), for the results page.
"""
import textwrap

import pandas as pd

from .parameter_groups import GROUPS, OTHER

# The values a named run uses instead of the settings module's (core/runs.py, run.py --run): set
# before the module is imported, and taken by assume() and setting() as each value registers, so
# whatever the module works out from a value follows it.
OVERRIDES = {}


def conform(value, default, name="value"):
    """`value` in the shape of `default`: a number where it has a number (an int stays an int when
    it is a whole number), a tuple where it has a tuple, the same keys where it has a dict. Raises
    ValueError when the two do not fit - a run cannot hand the model something it does not
    expect."""
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValueError(f"{name}: expected true or false, got {value!r}")
        return value
    if isinstance(default, (int, float)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name}: expected a number, got {value!r}")
        if isinstance(default, int) and float(value).is_integer():
            return int(value)
        return float(value)
    if isinstance(default, str):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name}: expected some text, got {value!r}")
        return value.strip()
    if isinstance(default, dict):
        if not isinstance(value, dict) or set(value) != set(default):
            raise ValueError(f"{name}: expected the keys {', '.join(map(str, default))}")
        return {k: conform(value[k], default[k], f"{name}.{k}") for k in default}
    if isinstance(default, (list, tuple)):
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{name}: expected a list, got {value!r}")
        if isinstance(default, tuple) and len(value) != len(default):
            raise ValueError(f"{name}: expected {len(default)} values, got {len(value)}")
        if not default:
            return type(default)(value)
        out = [conform(v, default[min(i, len(default) - 1)], f"{name}[{i}]")
               for i, v in enumerate(value)]
        return tuple(out) if isinstance(default, tuple) else out
    raise ValueError(f"{name}: cannot be changed from a run")


class Assumptions:
    """A registry of assumed numbers, in the order they were registered."""

    def __init__(self):
        self.entries = {}
        self.settings = {}       # choices of method: parameters, but not assumptions
        self.groups = {}         # name -> group, for a name GROUPS does not list
        self.defaults = {}       # name -> the module's value, for each one a run changed

    def _take(self, name, value):
        """The run's value for `name` if it sets one, else the module's."""
        if name not in OVERRIDES:
            return value
        changed = conform(OVERRIDES[name], value, name)
        if changed != value:
            self.defaults[name] = value
        return changed

    def assume(self, name, value, unit, why):
        """Record a number that is not in the data, and hand it back."""
        value = self._take(name, value)
        self.entries[name] = {"value": value, "unit": unit, "why": why}
        return value

    def setting(self, name, value, unit):
        """Record a choice of method, not a guess about the city, and hand it back."""
        value = self._take(name, value)
        self.settings[name] = {"value": value, "unit": unit}
        return value

    def table(self):
        return pd.DataFrame(self.entries).T

    def group_of(self, name):
        if name in self.groups:
            return self.groups[name]
        return next((g for g, names in GROUPS.items() if name in names), OTHER)

    def parameters(self):
        """Every parameter, assumed or set, by group in GROUPS order, then as registered."""
        rows = ([{"name": n, "kind": "assumed", **e} for n, e in self.entries.items()]
                + [{"name": n, "kind": "setting", "why": "", **e}
                   for n, e in self.settings.items()])
        order = list(GROUPS) + [OTHER]
        for row in rows:
            row["group"] = self.group_of(row["name"])
            # A run's change: the settings module's value it replaced.
            row["default"] = self.defaults.get(row["name"], "")
        rows.sort(key=lambda r: order.index(r["group"]) if r["group"] in order else len(order))
        return pd.DataFrame(rows, columns=["group", "name", "value", "unit", "kind", "why",
                                           "default"])

    def print(self, width=88):
        """Every guess the model rests on, for reading and for replacing."""
        print(f"{len(self.entries)} values are assumed, not measured. Replace any of them and "
              f"re-run.\n")
        for name, entry in self.entries.items():
            value = entry["value"]
            if isinstance(value, dict):
                head = ", ".join(f"{k}={v}" for k, v in list(value.items())[:3])
                shown = f"{head}, ... ({len(value)} classes)"
            else:
                shown = str(value)
            print(f"  {name}  =  {shown}")
            print(f"      {entry['unit']}")
            for line in textwrap.wrap(entry["why"], width - 6):
                print(f"      {line}")
            print()
        return self.table()
