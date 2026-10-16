"""The public-transport model: a GTFS feed, imported into AequilibraE and assigned.

    python run.py quito --transit

Shared machinery, knowing nothing about any one city; a city brings its feed and study box
(cases/<city>/transit_inputs.py) and its assumptions (cases/<city>/transit_settings.py).
"""
import importlib

# The cities with a public-transport case: settings module, inputs module.
TRANSIT_CASES = {
    "quito": ("cases.quito.transit_settings", "cases.quito.transit_inputs"),
    "sorocaba": ("cases.sorocaba.transit_settings", "cases.sorocaba.transit_inputs"),
}


def load(city):
    """The settings and inputs modules of a city's public-transport case."""
    if city not in TRANSIT_CASES:
        raise ValueError(f"{city!r} has no public-transport case; cities with one: "
                         f"{', '.join(sorted(TRANSIT_CASES))}")
    settings, inputs = TRANSIT_CASES[city]
    return importlib.import_module(settings), importlib.import_module(inputs)
