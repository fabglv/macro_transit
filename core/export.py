"""What a run writes out, in formats that open in QGIS or pandas on their own.

The AequilibraE project holds the network and the zones but none of the results - every matrix is
`memory_only`. What goes out instead:

| file | what it holds |
|---|---|
| `zones.gpkg` | the zones: boundaries, people, what they attract, trips produced and attracted |
| `od_matrix.csv.gz` | the O-D matrix, one row per zone pair that carries trips: trips, minutes on empty streets and on the loaded network, km |
| `od_matrix.omx` | the same matrix, square, in the format AequilibraE reads back |
| `link_volumes.gpkg` | every street the assignment loaded, with flow, V/C and congested time |
| `assumptions.csv` | every number in the assumptions table |
| `parameters.csv` | the assumptions and the method settings, by group, for the results page |

A city adds its own files through the same `Exporter`.
"""
import os
import tempfile

import geopandas as gpd
import numpy as np
import pandas as pd

from .assignment import CAR_AB, CAR_BA
from .maps import link_frame

MIN_TRIPS = 0.01          # a pair below this is rounding noise, not demand
VOLUME_FIELDS = ["link_id", "name", "link_type", "junction", "distance", "lanes_ab", "speed_ab",
                 "capacity_ab", "capacity_ba", "travel_time_ab", "travel_time_ba", CAR_AB, CAR_BA,
                 "Congested_Time_AB", "Congested_Time_BA", "voc_ab", "voc_ba", "voc", "flow"]


class Exporter:
    def __init__(self, folder):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)
        print(f"writing to {folder}")

    def path(self, name):
        return os.path.join(self.folder, name)

    def written(self, name):
        print(f"  {name:<28} {os.path.getsize(self.path(name)) / 1e6:>7.2f} MB")

    def layer(self, frame, name, layer):
        frame.to_file(self.path(name), driver="GPKG", layer=layer)
        self.written(name)

    def csv(self, frame, name, **kwargs):
        frame.to_csv(self.path(name), **kwargs)
        self.written(name)

    def zones(self, zones, fields, extra=None):
        """The zones, with their centroid as a coordinate pair: `centroid` is a second geometry
        column, and no single-geometry format can hold it. Column names a GIS might refuse
        ("mixed/commercial") are made safe. A field the run did not compute - the demand model's,
        when the matrix was loaded - is written empty; a loaded zoning's ids are added."""
        centres = gpd.GeoSeries(zones["centroid"], crs="EPSG:4326")
        zones = zones.copy()
        for field in fields:
            if field not in zones:
                zones[field] = np.nan
        if "file_id" in zones and "file_id" not in fields:
            fields = fields + ["file_id"]
        out = gpd.GeoDataFrame(zones[fields + ["geometry"]].copy(), geometry="geometry",
                               crs=zones.crs).to_crs("EPSG:4326")
        out["centroid_lon"] = centres.x.to_numpy()
        out["centroid_lat"] = centres.y.to_numpy()
        out = out.rename(columns={c: c.replace("/", "_").replace(" ", "_") for c in fields})
        if extra:
            out = extra(out)
        self.layer(out, "zones.gpkg", "zones")
        return out

    def od(self, demand, zone_ids, cost, congested, km):
        """The matrix twice: long CSV for reading, square OMX for assigning - read back, because
        a matrix that does not reopen is worse than no matrix.

        The CSV carries each pair's minutes twice: on empty streets (`minutes`, the skim the
        demand was built on) and on the loaded network (`congested_minutes`); and the length of
        the free-flow route (`km`)."""
        from aequilibrae.matrix import AequilibraeMatrix

        origin, dest = np.meshgrid(zone_ids, zone_ids, indexing="ij")
        carries = demand > MIN_TRIPS
        od = pd.DataFrame({"origin": origin[carries], "destination": dest[carries],
                           "trips": demand[carries].round(3),
                           "minutes": np.round(cost[carries], 2),
                           "congested_minutes": np.round(congested[carries], 2),
                           "km": np.round(km[carries], 2)})
        self.csv(od, "od_matrix.csv.gz", index=False, compression="gzip")
        print(f"    {len(od):,} pairs of {demand.size:,}, holding "
              f"{100 * od['trips'].sum() / demand.sum():.2f}% of the trips")

        omx = self.path("od_matrix.omx")
        if os.path.exists(omx):
            os.remove(omx)
        out = AequilibraeMatrix()
        out.create_empty(zones=len(zone_ids), matrix_names=["car"], index_names=["taz"],
                         memory_only=True)
        out.index[:] = zone_ids
        out.matrices[:, :, 0] = demand
        out.computational_view(["car"])
        out.export(omx)
        out.close()
        self.written("od_matrix.omx")

        check = AequilibraeMatrix()
        check.create_from_omx(omx, os.path.join(tempfile.gettempdir(), "_omx_check.aem"),
                              memory_only=True)
        if not np.array_equal(check.index[:], zone_ids):
            raise ValueError("the exported matrix does not carry the zone numbers")
        worst = float(np.abs(np.array(check.matrix["car"], dtype=float) - demand).max())
        check.close()
        print(f"    reopened: {len(zone_ids)} zones, largest difference from the matrix in "
              f"memory {worst:.2e}")

    def link_volumes(self, project, loaded):
        """Only the streets that carry traffic, with full geometry."""
        shapes = link_frame(project, "link_id")
        out = gpd.GeoDataFrame(loaded[VOLUME_FIELDS].merge(shapes, on="link_id", how="inner"),
                               geometry="geometry", crs="EPSG:4326")
        self.layer(out, "link_volumes.gpkg", "link_volumes")
        if len(out) != len(loaded):
            raise ValueError(f"{len(loaded) - len(out)} loaded links have no geometry")

    def assumptions(self, registry):
        self.csv(registry.table(), "assumptions.csv")
        self.csv(registry.parameters(), "parameters.csv", index=False)

    def total(self):
        files = os.listdir(self.folder)
        size = sum(os.path.getsize(self.path(f)) for f in files)
        print(f"\n{len(files)} files, {size / 1e6:.1f} MB in total")
