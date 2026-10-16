"""The road classes and congestion bands the simulation map and the results page share.

Kept apart from maps.py so the page, which needs nothing beyond the standard library, uses the
same bands and colours as the map's legend without loading folium.
"""

CONGESTION_BANDS = [(0.00, 0.50, "#2c7bb6", "under 50% - free flowing"),
                    (0.50, 0.85, "#8cc4de", "50-85% - busy"),
                    (0.85, 1.00, "#fdae61", "85-100% - at capacity"),
                    (1.00, 1.50, "#d7191c", "100-150% - over capacity"),
                    (1.50, 1e9, "#7d0018", "over 150% - far beyond capacity")]
MAP_ROAD_TYPES = ["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
                  "secondary", "secondary_link", "tertiary", "tertiary_link"]
LOCAL_ROAD_TYPES = ["residential", "unclassified"]
# Classes whose layer on the simulation map starts switched off: the local streets, and the
# tertiary roads - drawing all of them at once made Quito's map slow to appear.
OFF_AT_START = LOCAL_ROAD_TYPES + ["tertiary"]
ROAD_CLASS_ORDER = ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
                    "residential"]                     # the layer list, biggest road first
