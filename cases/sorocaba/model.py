"""Sorocaba/SP (IBGE 3552205): TAZ, O-D matrix and a baseline car assignment from official data.

Built the way the Quito model was built, with Sorocaba's inputs:

| Quito | Sorocaba |
|---|---|
| barrios and parroquias | the 19 áreas de ponderação of the 2010 census |
| INEC census sectors | IBGE census sectors 2022, 1,148 |
| cadastre floor area x land-use class | CNEFE establishment addresses x jobs from CEMPRE 2024 |
| no car ownership data | car ownership by weighting area, 2010 census sample |
| no external traffic | external zones fed by 2010 commuting, through traffic, ARTESP counts |

Everything is read from `data/sorocaba/input/`; see its README.md and DATA_INVENTORY.md.
"""
import numpy as np
import pandas as pd

from core import report
from core.pipeline import CityModel
from core.skim import skim_zones

from . import counts, demand, external, inputs
from . import maps as smaps

GATEWAY_SECTIONS = """
What the model does not capture, beyond what the Quito model lists (BPR is not physical above
capacity, the number of connectors per zone is a guess, roundabout entries are not modelled,
residential streets serve as free short cuts):
- Through traffic is a total and a rule, not an observation (set from the edge counts, F7).
- No freight: lorries are in no file here.
- Jobs are spread evenly over establishments of a kind: a factory and a newsstand are each one
  CNEFE address of espécie 6.
- Commuting is 2010's, scaled; commuters from other states are missing.
- CAR_SHARE, OCCUPANCY, EXTERNAL_CAR_SHARE and EXTERNAL_CAR_SHARE_STUDY are not Sorocaba's -
  the first numbers to replace when a mobility survey or the city's own counts turn up.
"""


class Sorocaba(CityModel):
    label = "Sorocaba"
    # Drawn in step 1, from CNEFE and CEMPRE: where the jobs that attract trips are.
    step1_maps = ["1_jobs.html"]
    attraction_map = "1_jobs.html"

    def prepare(self):
        self.files = inputs.files(self.paths)
        self.paths.require(*self.files.values())
        inputs.read_sectors(self)
        inputs.weighting_areas(self)
        inputs.sample_2010(self)
        inputs.jobs(self)
        inputs.build_zones(self)
        inputs.neighbours(self)
        inputs.commuting(self)

    def network_outline(self):
        # The city outline plus the margin, smoothed: Overpass is asked for a polygon. The roads
        # have to cross the boundary inside the model for the cordon zones to join them.
        return self.city.buffer(self.s.NETWORK_MARGIN_M).simplify(500)

    def after_network(self, road):
        report.section("E2b. Where the roads leave the city")
        external.find_gateways(self, road)

    def reserved_centroids(self):
        return len(self.zones) + len(self.gateways)

    def travel_share(self):
        share = self.zones.set_index("zone_number")
        return 0.5 * (share["pop"] / share["pop"].sum() + share["jobs"] / share["jobs"].sum())

    def zone_system(self):
        """The cordon zones, a skim with them, the routing to the gateways, and then the external
        zones that replace the cordon zones (EXTERNAL_ZONES)."""
        external.add_cordon_zones(self, self.model)
        report.section("E6. How far every zone is from every other (with the cordon zones)")
        all_zones = np.array(sorted(list(self.zones["zone_number"])
                                    + list(self.gateways["zone_number"])))
        cost, km, order = skim_zones(self.model, all_zones, self.n_internal,
                                     self.s.INTRAZONAL_SHARE, "cordon", strict=self.s.STRICT_SKIM)
        # Kept apart: the routing reads gateway-to-city times from it.
        self.cost_cordon, self.km_cordon, self.zones_cordon = cost.copy(), km, order.copy()
        external.route_to_gateways(self)
        return external.external_zone_system(self, self.model)

    def build_demand(self):
        demand.internal_generation(self)
        demand.external_trips(self)
        return demand.full_matrix(self)

    def demand_replaced(self):
        """What the gateway check and the external zones' map read from the demand model,
        from the matrix assigned: the trips into and out of the city, and by external zone."""
        self.ei, self.ie, self.by_ext = self.external_totals(self.demand)
        print(f"into the city {self.ei:,.0f}, out of it {self.ie:,.0f} (through trips counted "
              f"in both)")

    def external_totals(self, demand):
        """The trips of `demand` into and out of the city, and by external zone."""
        inside = self.is_internal
        pos = {z: i for i, z in enumerate(self.all_zones)}
        ext_pos = [pos[z] for z in self.external_zones["zone_number"]]
        by_ext = pd.DataFrame({
            "label": self.external_zones["label"].to_numpy(),
            "description": self.external_zones["description"].to_numpy(),
            "in": demand[ext_pos].sum(axis=1), "out": demand[:, ext_pos].sum(axis=0)})
        return demand[~inside].sum(), demand[:, ~inside].sum(), by_ext

    def after_assignment(self):
        """What each gateway carried: the flow on the links joining its outer nodes to an
        external centroid. Every external trip must cross the city limit through some gateway,
        exactly once - a conservation check, not a proof of the route."""
        flows, gateways = self.flows, self.gateways
        ext_ids = set(self.external_zones["zone_number"])
        gate_of = {n: g.label for g in gateways.itertuples() for n in g.outer_nodes}
        gc_ = flows[flows["link_type"].isin(["centroid_connector", "external_access"])
                    & (flows["a_node"].isin(ext_ids) | flows["b_node"].isin(ext_ids))].copy()
        from_zone = gc_["a_node"].isin(ext_ids)
        gc_["gate"] = np.where(from_zone, gc_["b_node"], gc_["a_node"])
        gc_["gate"] = gc_["gate"].map(gate_of)
        gc_["into_city"] = np.where(from_zone, gc_["car_ab"], gc_["car_ba"])
        gc_["out_of_city"] = np.where(from_zone, gc_["car_ba"], gc_["car_ab"])
        if gc_["gate"].isna().any():
            raise ValueError("an external zone joins the network somewhere that is not a gateway")
        carried = gc_.groupby("gate")[["into_city", "out_of_city"]].sum()
        vol = pd.DataFrame({"label": gateways["label"].to_numpy(),
                            "road": gateways["road"].to_numpy()})
        vol["in"] = vol["label"].map(carried["into_city"]).fillna(0).to_numpy()
        vol["out"] = vol["label"].map(carried["out_of_city"]).fillna(0).to_numpy()
        print("\nwhat each gateway carried in the assignment:")
        print(vol.round(0).to_string(index=False))
        # A scenario's closures can leave trips with no route: they are not assigned (the log
        # says how many), so the gateways carry the matrix's other trips - every one of them.
        ei, ie, by_ext = self.ei, self.ie, self.by_ext
        unrouted = getattr(self, "unrouted", None)
        if unrouted is not None and unrouted.any():
            ei, ie, by_ext = self.external_totals(np.where(unrouted, 0, self.demand))
            print(f"  the closures leave {self.ei - ei:,.0f} trips into the city and "
                  f"{self.ie - ie:,.0f} out of it with no route: not assigned")
        if not (np.isclose(vol["in"].sum(), ei, rtol=1e-3)
                and np.isclose(vol["out"].sum(), ie, rtol=1e-3)):
            raise ValueError("the gateways do not carry the external trips the matrix holds")
        print(f"  total {vol['in'].sum():,.0f} in and {vol['out'].sum():,.0f} out, matching the "
              f"matrix")
        if self.s.EXTERNAL_ZONES == "gateways" and not np.allclose(
                by_ext["in"].to_numpy(), vol["in"].to_numpy(), rtol=1e-3, atol=1):
            raise ValueError("with one zone per gateway, each gateway must carry exactly its "
                             "zone's trips")
        self.gate_volume = vol

    def extra_maps(self):
        if self.zoned_externals:
            smaps.map_external_zones(self.maps, self.external_zones, self.by_ext, self.gateways,
                                     self.gate_volume, self.boundary, self.s.EXTERNAL_ZONES)
        else:
            print("EXTERNAL_ZONES is 'gateways': the external zones are the gateways, so there "
                  "is no separate map")

    def caveats(self):
        print(f"\ncongestion adds "
              f"{100 * (self.load['veh_hours'] / self.load['free_hours'] - 1):.1f}% to travel "
              f"time in the modelled network; the corridors carrying the most traffic:")
        for r in self.load["streets_busy"].nlargest(6, "veh_km").itertuples():
            print(f"  {r.Index}")
        print(GATEWAY_SECTIONS)

    def export(self, ex):
        zones, dem = self.zones, self.demand
        zones["veh_attractions"] = pd.Series(dem.sum(axis=0), index=self.all_zones).reindex(
            zones["zone_number"]).to_numpy()
        zones["veh_origins"] = pd.Series(dem.sum(axis=1), index=self.all_zones).reindex(
            zones["zone_number"]).to_numpy()
        fields = (["zone", "zone_number", "ap", "ap_label", "n_sectors", "area_km2", "pop",
                   "dwellings", "households", "density", "jobs"]
                  + [f"jobs_{k}" for k in self.job_classes]
                  + ["car_share_hh", "income_pc", "car_share", "productions", "veh_productions",
                     "pull", "veh_origins", "veh_attractions"])
        ex.zones(zones, fields)

        cordon = self.gateways.drop(columns=["outer_nodes", "x", "y"]).to_crs("EPSG:4326")
        if self.zoned_externals:
            # The gateways are not zones of the matrix here, and their old numbers overlap the
            # external zones' - renamed so a join on zone_number cannot match the wrong thing.
            cordon = cordon.rename(columns={"zone_number": "cordon_zone_e6"})
        cordon["veh_in"] = self.gate_volume["in"].to_numpy()
        cordon["veh_out"] = self.gate_volume["out"].to_numpy()
        ex.layer(cordon, "cordon_zones.gpkg", "cordon")

        if self.zoned_externals:
            import geopandas as gpd
            ext = self.external_zones
            pts = ext.to_crs("EPSG:4326").geometry
            out = gpd.GeoDataFrame(ext.drop(columns=["x", "y", "geometry", "shape"]),
                                   geometry=list(ext["shape"]), crs=self.metre_crs)
            out = out.to_crs("EPSG:4326")
            out["centre_lon"], out["centre_lat"] = pts.x.to_numpy(), pts.y.to_numpy()
            out["veh_in"] = self.by_ext["in"].to_numpy()
            out["veh_out"] = self.by_ext["out"].to_numpy()
            ex.layer(out, "external_zones.gpkg", "external_zones")
            ex.csv(self.gateway_offer.merge(ext[["zone_number", "label"]], on="zone_number"),
                   "external_gateway_choices.csv", index=False)
        ex.od(dem, self.all_zones, self.cost, self.congested, self.distance_km)

    def validate(self, ex):
        report.section("F. Against the traffic counts")
        counts.run(self, ex)
