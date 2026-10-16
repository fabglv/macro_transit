"""The cities the program knows. Each is a `CityModel` subclass and a settings module."""
import importlib

CASES = {
    "quito": ("cases.quito.model", "Quito", "cases.quito.settings"),
    "sorocaba": ("cases.sorocaba.model", "Sorocaba", "cases.sorocaba.settings"),
}


def load(city):
    """The model class and settings module for a city."""
    if city not in CASES:
        raise ValueError(f"unknown city {city!r}; known: {', '.join(CASES)}")
    module, cls, settings = CASES[city]
    return getattr(importlib.import_module(module), cls), importlib.import_module(settings)
