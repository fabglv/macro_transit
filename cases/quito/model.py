"""Quito: TAZ and O-D matrix from the city's own published data.

The **barrio boundaries** the municipality uses, the **census sectors** and their counted
population, and the **cadastre** of buildings with the **land-use plan** - so the zones and the
matrix are recognisably Quito rather than a grid laid over it.

Inputs, in `data/quito/input/` (official DMQ material, not something the program downloads):

| what | original (data/quito/input/) | read (input_min/, tools/trim_inputs.py) |
|---|---|---|
| barrio layer | `BARRIO_REF/BARRIO_REF.shp` | `barrios.parquet` |
| population per parroquia | `03_Resultados_proyeccion2023_2035.xlsx` | the same |
| census sectors 2022 | `sector_censal_2022_inec_q/sector_anonimizado_a.shp` | `sectors.parquet` |
| land-use plan | `ba003_uso_suelo_edificabilidad_a/ba003_uso_suelo_edificabilidad_a.shp` | `land_use.parquet` |
| cadastre | `BLOQUE_CONSTRUCTIVO/BLOQUE_CONSTRUCTIVO/catastro.gdb` | `buildings.parquet`: a point and footprint a building |
"""
import gc
import re
import unicodedata

import geopandas as gpd
import numpy as np
import pandas as pd

from core import report, zoning
from core.gravity import Gravity, busiest_pairs, stayers
from core.maps import MapKit
from core.pipeline import CityModel

from . import maps as qmaps

USE_CLASS = {"RUM": "residential", "RUB": "residential", "RUA": "residential",
             "RR": "residential", "RRR": "residential",
             "M": "mixed/commercial", "CSE": "mixed/commercial", "M-IMI-IAI": "mixed/commercial",
             "E": "facilities", "PUP": "heritage core",
             "IMI": "industrial", "IAI": "industrial", "IAR": "industrial"}
CLASSES = ["residential", "mixed/commercial", "facilities", "heritage core", "industrial"]

# The ten roads the Agencia Metropolitana de Transito names as the city's worst, reported in
# Primicias on 8 January 2024. Occidental is the northern stretch of Mariscal Sucre, so it is
# matched under that name. Kept as data so the comparison is redone every run.
AMT_WORST = {"Simon Bolivar": "Sim", "General Ruminahui": "Rumi",
             "Occidental (Mariscal Sucre)": "Mariscal Sucre", "Amazonas": "Amazonas",
             "De los Shyris": "Shyris", "10 de Agosto": "10 de Agosto",
             "Eloy Alfaro": "Eloy Alfaro", "6 de Diciembre": "6 de Diciembre",
             "Gaspar de Villarroel": "Gaspar de Villarroel", "Velasco Ibarra": "Velasco Ibarra"}
ZONE_SIMPLIFY_M = 0.5     # exported zone outlines: below the accuracy of any census boundary


def canonical(name):
    """A parroquia name reduced to a joinable key: uppercase, unaccented, single-spaced, no article.

    The two sources name parroquias differently in three ways: accents (PINTAG / PÍNTAG),
    spacing (LLANO  CHICO) and the leading article (CONCEPCION / LA CONCEPCION).
    """
    text = unicodedata.normalize("NFKD", str(name)).upper()
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^(LA|EL|LAS|LOS) ", "", text)


class Quito(CityModel):
    label = "Quito"
    # Drawn in step 1, from the cadastre: where the floor area that attracts trips is.
    step1_maps = ["1_land_use.html"]
    attraction_map = "1_land_use.html"

    # --- A-D: inputs and zones -----------------------------------------------------------------
    def prepare(self):
        p = self.paths
        self.files = {
            # As tools/trim_inputs.py cuts them from the originals (data/quito/input/).
            "barrios": p.inp("barrios.parquet"),
            "population": p.inp("03_Resultados_proyeccion2023_2035.xlsx"),
            "sectors": p.inp("sectors.parquet"),
            "land_use": p.inp("land_use.parquet"),
            "cadastre": p.inp("buildings.parquet")}
        p.require(*self.files.values())
        self.read_barrios()
        self.read_sectors()
        self.build_zones()
        self.read_floor_area()

    def read_barrios(self):
        """A1-A4. The barrios, the population per parroquia, and the parroquias as a layer.

        Neither `codigo` nor `nombre` is a safe key on its own; population is published for 65
        parroquias, and the barrios join it through the parroquia name.
        """
        report.section("A1. The barrios")
        barrios = gpd.read_parquet(self.files["barrios"])
        barrios = barrios.drop(columns=["norte", "sur", "este", "oeste"])
        # Areas need a projected CRS; the file is in degrees.
        self.metre_crs = barrios.estimate_utm_crs()
        self.maps = MapKit(self.metre_crs, self.paths.maps)
        barrios["area_km2"] = barrios.to_crs(self.metre_crs).area / 1e6
        print(f"{len(barrios):,} barrios in {barrios['parroquia'].nunique()} parroquias, "
              f"crs {barrios.crs.to_string()}")
        print(f"Total area: {barrios['area_km2'].sum():,.0f} km2")
        dupes = barrios[barrios.duplicated("codigo", keep=False)]
        print(f"{len(dupes)} rows share a `codigo` with another barrio: "
              f"{sorted(dupes['codigo'].unique())}")
        report.preview(barrios, "barrios")

        report.section("A2. Population")
        population = pd.read_excel(self.files["population"], sheet_name="poblacion_2022")
        projections = pd.read_excel(self.files["population"], sheet_name="resultados_por_modelos")
        print(f"{len(population)} parroquias, {population['pob_total_2022'].sum():,} people in "
              f"2022")
        print(population.groupby("area")["pob_total_2022"].agg(["count", "sum"]).to_string())
        models = [c for c in projections.columns
                  if c not in ("area", "codigo_parroquia", "nombre_parroquia", "anio")]
        spread = (projections[models].max(axis=1) - projections[models].min(axis=1)).max()
        print(f"projection models: {models}; they distribute a fixed total, and disagree about "
              f"one parroquia-year by up to {spread:,.0f} people")

        report.section("A3. Joining them")
        barrios["par_key"] = barrios["parroquia"].map(canonical)
        population["par_key"] = population["nombre_parroquia"].map(canonical)
        raw = len(set(barrios["parroquia"]) & set(population["nombre_parroquia"]))
        keyed = len(set(barrios["par_key"]) & set(population["par_key"]))
        print(f"Parroquias matched on the raw name: {raw} of {barrios['parroquia'].nunique()}")
        print(f"Parroquias matched on the key:      {keyed} of {barrios['par_key'].nunique()}")
        barrios = barrios.merge(
            population[["par_key", "codigo_parroquia", "area", "pob_total_2022"]],
            on="par_key", how="left", validate="many_to_one")
        if barrios["pob_total_2022"].isna().any():
            raise RuntimeError("Some barrios did not pick up a population figure.")

        report.section("A4. Parroquias")
        # There is no parroquia file - the layer is the barrios dissolved, which works because
        # the barrios tile the district exactly. Checked rather than assumed.
        parroquias = barrios.dissolve(
            by="par_key", aggfunc={"parroquia": "first", "area": "first",
                                   "pob_total_2022": "first", "area_km2": "sum", "id": "count"},
        ).rename(columns={"id": "n_barrios"}).reset_index()
        parroquias["density"] = parroquias["pob_total_2022"] / parroquias["area_km2"]
        parts = [1 if x.geom_type == "Polygon" else len(x.geoms) for x in parroquias.geometry]
        print(f"{len(parroquias)} parroquias, {sum(parts)} polygon parts "
              f"({(np.array(parts) > 1).sum()} multi-part)")
        print(f"Area preserved by the dissolve: "
              f"{barrios.to_crs(self.metre_crs).area.sum() / 1e6:,.1f} km2 -> "
              f"{parroquias.to_crs(self.metre_crs).area.sum() / 1e6:,.1f} km2")
        print(parroquias.groupby("area")["density"].describe()[["count", "min", "50%", "max"]]
              .round(0).to_string())

        self.barrios, self.population, self.parroquias = barrios, population, parroquias

    def read_sectors(self):
        """B1-B2. The census sectors: 7,179 of them, each with its own count."""
        report.section("B1. Census sectors")
        sectors = gpd.read_parquet(self.files["sectors"])
        # Two sectors in Guamani are empty: no people, no dwellings, and so no household size.
        sectors[["pob_t", "p_hog"]] = sectors[["pob_t", "p_hog"]].fillna(0)
        sectors["area_km2"] = sectors.to_crs(self.metre_crs).area / 1e6
        sectors["density"] = sectors["pob_t"] / sectors["area_km2"]
        print(f"{len(sectors):,} sectors, {sectors['area_km2'].sum():,.0f} km2 (the barrios "
              f"covered {self.barrios['area_km2'].sum():,.0f})")
        print(f"Population: {sectors['pob_t'].sum():,.0f}, against "
              f"{self.parroquias['pob_total_2022'].sum():,} in the spreadsheet")
        q = sectors["pob_t"].quantile([0, 0.1, 0.5, 0.9, 1])
        print(f"People per sector: min {q[0]:.0f} | 10th {q[0.1]:.0f} | median {q[0.5]:.0f} | "
              f"90th {q[0.9]:.0f} | max {q[1]:.0f}")
        # The sector file and the spreadsheet share the DPA parroquia code.
        by_par = sectors.groupby(sectors["parroquia"].astype(str))["pob_t"].sum()
        sheet = self.population.set_index(
            self.population["codigo_parroquia"].astype(str))["pob_total_2022"]
        gap = (by_par - sheet).dropna()
        print(f"Parroquias matched on the DPA code: {len(gap)} of {len(sheet)}; a single one "
              f"differs by up to {gap.abs().max():,.0f} people "
              f"({100 * (gap.abs() / sheet).max():.1f}%)")
        # Sectors and barrios come from different agencies, so they need not line up.
        centres = sectors[["id", "geometry"]].copy()
        centres["geometry"] = centres.representative_point()
        inside = gpd.sjoin(centres, self.barrios[["par_key", "geometry"]], how="left",
                           predicate="within")
        inside = inside[~inside.index.duplicated(keep="first")]
        agrees = (inside["par_key"].values == sectors["nom_par"].map(canonical).values).mean()
        print(f"Sector centres landing in a barrio of the same parroquia: {100 * agrees:.1f}%")
        report.preview(sectors.round(2), "census sectors",
                       columns=["sec_anm", "nom_par", "pob_t", "v_pres", "p_hog", "area_km2",
                                "density"])
        self.sectors = sectors

    def build_zones(self):
        """C. From sectors to zones.

        The first nine digits of the sector code are the INEC census zona. Four rules:
        1. group sectors by census zona
        2. split any zona that straddles a parroquia, so every zone sits in exactly one
        3. split any zona that is not a single connected piece
        4. merge zones under MIN_ZONE_POP into the neighbour sharing most sector borders (inside
           their parroquia), then split zones over MAX_ZONE_POP into compact pieces
        The centroid is population-weighted.
        """
        s = self.s
        report.section("C1. From sectors to zones")
        sectors = self.sectors.reset_index(drop=True)
        sectors["row"] = np.arange(len(sectors))
        sectors["zona"] = sectors["sec_anm"].astype(str).str[:9]
        sec_m = sectors.to_crs(self.metre_crs)
        loaded = (self.inputs or {}).get("zoning")
        if loaded:                     # the zones are a file's, not the rules'
            labels, self.zoning_report = zoning.from_file(sec_m, loaded["path"],
                                                          loaded.get("id_column", ""))
            keep = labels != None                                # noqa: E711 - an array
            print(f"Zones from {loaded['name']}: {len(set(labels[keep])):,} zones, "
                  f"{int(keep.sum()):,} of {len(sectors):,} sectors in them "
                  f"({sectors.loc[keep, 'pob_t'].sum():,.0f} of {sectors['pob_t'].sum():,.0f} "
                  f"people)")
            sectors = sectors[keep].reset_index(drop=True)
            sectors["file_id"] = labels[keep]
            sectors["zone"] = zoning.renumber(sectors, "file_id", "parroquia", "sec_anm", 4)
            sec_m = sectors.to_crs(self.metre_crs)
            print(f"Zones numbered Z0001 to Z{sectors['zone'].nunique():04d}, in the file's "
                  f"order of parroquia and sector")
        else:
            self.rule_zones(sectors, sec_m)
        self.summarise_zones(sectors, sec_m)

    def rule_zones(self, sectors, sec_m):
        """C1, by the rules: the census zona, cut at parroquias, merged and split by people."""
        s = self.s
        edges, _ = zoning.adjacency(sec_m)
        print(f"{len(sectors):,} sectors, {len(edges):,} adjacency pairs "
              f"({len(edges) / len(sectors):.1f} neighbours each)")

        # Rules 1-3: the census zona, cut at parroquia borders, then into connected pieces.
        base, _ = pd.factorize(sectors["zona"] + "|" + sectors["parroquia"].astype(str))
        part = zoning.pieces(base, edges, len(sectors))
        zone_of = (pd.Series(base).astype(str) + "-" + pd.Series(part).astype(str)).to_numpy()
        pop = sectors["pob_t"].to_numpy()
        first = zoning.sizes(zone_of, pop)
        print(f"After rules 1-3: {len(first):,} zones ({(first < s.MIN_ZONE_POP).sum()} under "
              f"{s.MIN_ZONE_POP:,}, {(first > s.MAX_ZONE_POP).sum()} over {s.MAX_ZONE_POP:,})")

        # Rule 4: the tails. Merge first, then split.
        zone_of, done = zoning.merge_small(zone_of, pop, edges,
                                           sectors["parroquia"].astype(str).to_numpy(),
                                           s.MIN_ZONE_POP)
        print(f"Merged {done['merged']} zones under {s.MIN_ZONE_POP:,} people"
              + (f"; {done['kept']} had no neighbour in their parroquia and were kept"
                 if done["kept"] else ""))
        xy = np.column_stack([sec_m.geometry.representative_point().x,
                              sec_m.geometry.representative_point().y])
        n_big = int((zoning.sizes(zone_of, pop) > s.MAX_ZONE_POP).sum())
        zone_of, _ = zoning.split_large(zone_of, pop, edges, xy, s.MAX_ZONE_POP, passes=1,
                                        too_few="skip", sep="s")
        print(f"Split {n_big} zones over {s.MAX_ZONE_POP:,} people")
        sectors["zone"] = zone_of
        sectors["zone"] = zoning.renumber(sectors, "zone", "parroquia", "sec_anm", 4)
        print(f"Zones numbered Z0001 to Z{sectors['zone'].nunique():04d}")

    def summarise_zones(self, sectors, sec_m):
        """C2. The sectors of each zone summed: people, dwellings, area; the centroid."""
        report.section("C2. The zones")
        zones = sectors.dissolve(
            by="zone", aggfunc={"pob_t": "sum", "v_pres": "sum", "area_km2": "sum", "id": "count",
                                "parroquia": "first", "nom_par": "first", "adm_zonal": "first"},
        ).rename(columns={"pob_t": "pop", "v_pres": "dwellings", "id": "n_sectors"}).reset_index()
        zones["density"] = zones["pop"] / zones["area_km2"]
        centroids, moved = zoning.weighted_centroids(
            sec_m, sectors["zone"], sectors["pob_t"],
            zones.set_index("zone").to_crs(self.metre_crs))
        zones["centroid"] = centroids.reindex(zones["zone"]).to_numpy()
        print(f"Centroids moved inside their zone: {moved} of {len(zones)}")
        parts = [1 if g.geom_type == "Polygon" else len(g.geoms) for g in zones.geometry]
        print(f"\n{len(zones):,} zones, from {len(sectors):,} sectors")
        print(f"  population preserved: {zones['pop'].sum():,.0f} of {sectors['pob_t'].sum():,.0f}")
        q = zones["pop"].quantile([0, 0.1, 0.5, 0.9, 1])
        print(f"  population  min {q[0]:,.0f} | 10th {q[0.1]:,.0f} | median {q[0.5]:,.0f} | "
              f"90th {q[0.9]:,.0f} | max {q[1]:,.0f}")
        print(f"  zones spanning more than one parroquia: "
              f"{(sectors.groupby('zone')['parroquia'].nunique() > 1).sum()}")
        print(f"  zones that are a single connected polygon: {sum(p == 1 for p in parts)} of "
              f"{len(zones)}")
        report.preview(zones.round(2), "zones", columns=["zone", "nom_par", "n_sectors", "pop",
                                                         "dwellings", "area_km2", "density"])
        # AequilibraE wants an integer zone id; ours read Z0001..
        zones["zone_number"] = zones["zone"].str.lstrip("Z").astype(int)
        if "file_id" in sectors:            # a loaded zoning: each zone's id in the file
            zones["file_id"] = zones["zone"].map(sectors.groupby("zone")["file_id"].first())
        self.sectors, self.zones = sectors, zones
        self.boundary = sectors[["geometry"]].dissolve()

    def read_floor_area(self):
        """D. What is built on the zones: cadastre floor area, classed by the land-use plan.

        The cadastre says **what is built**, the land-use plan **what it may be used for**. Its
        two layers, UNIDAD_CONSTRUCTIVA and BLOQUE_CONSTRUCTIVO, are disjoint and are added in
        full. Every building takes the `uso_prin` of the polygon it stands in, and nothing is
        adjusted after that: zoning is a plan, not a survey, and its artefacts are left visible.
        """
        report.section("D. What is built on the zones")
        crs = self.metre_crs
        land_use = gpd.read_parquet(self.files["land_use"]).to_crs(crs)

        # Every building of the two layers as tools/trim_inputs.py keeps it: its footprint's area
        # and a point inside it - all the floor area needs.
        units = gpd.read_parquet(self.files["cadastre"]).to_crs(crs)
        units["floors"] = units["PISOS"].clip(lower=1)
        units["floor_m2"] = units["ground_m2"] * units["floors"]   # the footprint, a floor of it
        print(f"land use: {len(land_use):,} polygons covering {land_use.area.sum() / 1e6:,.0f} km2")
        print(f"cadastre: {len(units):,} buildings, {units['ground_m2'].sum() / 1e6:,.1f} km2 of "
              f"footprint and {units['floor_m2'].sum() / 1e6:,.1f} km2 of floor area")
        print(f"  {units['PISOS'].isna().sum()} buildings have no floor count and carry no floor "
              f"area")

        report.section("D1-D2. The class is the plan's; attaching it to the zones")
        # Each unit is reduced to a point inside itself, so it is counted exactly once whatever
        # it straddles, then labelled by the zoning polygon and the sector it falls in.
        pts = units[["floor_m2", "ground_m2", "floors", "geometry"]].copy()
        tagged = gpd.sjoin(pts, land_use[["uso_prin", "geometry"]], how="left", predicate="within")
        tagged = tagged[~tagged.index.duplicated(keep="first")].drop(columns="index_right")
        sec_m = self.sectors.to_crs(crs)
        tagged = gpd.sjoin(tagged, sec_m[["row", "geometry"]], how="left", predicate="within")
        tagged = tagged[~tagged.index.duplicated(keep="first")]
        print(f"units landing in a land-use polygon: {100 * tagged['uso_prin'].notna().mean():.1f}%")
        print(f"units landing in a census sector:    {100 * tagged['row'].notna().mean():.1f}%")
        tagged = tagged[tagged["row"].notna()].copy()
        tagged["klass"] = tagged["uso_prin"].map(USE_CLASS)
        tagged["zone"] = tagged["row"].map(self.sectors.set_index("row")["zone"])
        dropped = tagged["klass"].isna()
        print(f"floor area on land with no built-use class: "
              f"{tagged.loc[dropped, 'floor_m2'].sum() / 1e6:.2f} km2 "
              f"({100 * tagged.loc[dropped, 'floor_m2'].sum() / tagged['floor_m2'].sum():.1f}%), "
              f"dropped")
        floor_by_class = (tagged[~dropped]
                          .pivot_table(index="zone", columns="klass", values="floor_m2",
                                       aggfunc="sum", fill_value=0.0)
                          .reindex(columns=CLASSES, fill_value=0.0))
        # The building frames hold close to a million geometries and are finished with once the
        # floor area is summed; releasing them keeps the network step within memory.
        del units, pts, tagged
        gc.collect()
        print("floor area by class, whole district (km2):")
        print((floor_by_class.sum() / 1e6).round(2).to_string())

        zones = self.zones.merge(floor_by_class, left_on="zone", right_index=True, how="left")
        zones[CLASSES] = zones[CLASSES].fillna(0.0)
        zones["built_m2"] = zones[CLASSES].sum(axis=1)
        zones["activity_m2"] = zones["built_m2"] - zones["residential"]
        zones["dominant"] = zones[CLASSES].idxmax(axis=1).where(zones["built_m2"] > 0,
                                                                "no buildings")
        # Housing floor area over people. Around 30 m² is ordinary; a very low figure is a fault
        # in the data rather than crowded housing.
        zones["m2_per_person"] = zones["residential"] / zones["pop"].replace(0, np.nan)
        pop, dw = zones["pop"].sum(), zones["dwellings"].sum()
        print(f"\nzones with built floor area: {(zones['built_m2'] > 0).sum():,} of {len(zones):,}")
        print(f"residential floor area per person: {zones['residential'].sum() / pop:5.1f} m2, "
              f"per dwelling {zones['residential'].sum() / dw:5.1f} m2")
        by_par = zones.groupby("nom_par")[["pop", "residential"]].sum()
        print(f"correlation of residential floor area with population, by parroquia: "
              f"{by_par.corr().iloc[0, 1]:.3f}")
        print("which class dominates, by zone count:")
        print(zones["dominant"].value_counts().to_string())
        thin = zones[(zones["pop"] > 1000) & (zones["m2_per_person"] < 10)]
        print(f"\nHousing floor area per person: median {zones['m2_per_person'].median():.1f} m²; "
              f"{len(thin)} zones hold over 1,000 people on under 10 m² each - "
              f"{thin['pop'].sum():,.0f} people. Their floor area cannot be taken at face value.")
        report.section("D3. Where the activity is")
        qmaps.map_land_use(self.maps, zones, CLASSES)
        print("\nThe ten zones that should attract the most trips:")
        print(zones.nlargest(10, "activity_m2")[["zone", "nom_par", "pop", "activity_m2",
                                                 "dominant"]].round(0).to_string(index=False))
        self.zones = zones

    # --- E: the shared chain, with Quito's choices -------------------------------------------
    def network_outline(self):
        # The district outline, smoothed: Overpass is asked for a polygon, and 7,179 sector
        # borders would make an enormous query for no extra network.
        return (self.sectors.to_crs(self.metre_crs).geometry.union_all()
                .buffer(200).simplify(2000).buffer(-200))

    def travel_share(self):
        share = self.zones.set_index("zone_number")
        return 0.5 * (share["pop"] / share["pop"].sum()
                      + share["activity_m2"] / share["activity_m2"].sum())

    def build_demand(self):
        """Productions = population x a rate; attractions = floor area x a rate per class,
        rescaled to the production total, so only the ratios between the classes survive.

        Residential floor area attracts too, at a low rate: a single all-purpose matrix has to
        carry the journey home as well as the journey out. Mode split is applied before
        distribution - both are constants, so the matrix is identical either way.
        """
        s, zones = self.s, self.zones
        zones["productions"] = zones["pop"] * s.TRIPS_PER_PERSON
        # The day's weights: a weekday's, or a weekend day's (CityModel.weights).
        rates = pd.Series(self.weights("ATTRACTION_RATES")).reindex(CLASSES).fillna(0.0)
        zones["pull"] = sum(zones[c] * rates[c] for c in CLASSES)
        # A gravity model needs both margins to agree. Productions come from a count and
        # attractions from assumed rates, so the attractions are the side that moves.
        zones["attractions"] = zones["pull"] * (zones["productions"].sum() / zones["pull"].sum())
        vehicle_factor = s.CAR_SHARE / s.OCCUPANCY
        zones["veh_productions"] = zones["productions"] * vehicle_factor
        zones["veh_attractions"] = zones["attractions"] * vehicle_factor
        print(f"peak-hour person trips: {zones['productions'].sum():,.0f}")
        print(f"  {zones['pop'].sum():,.0f} residents at {s.TRIPS_PER_PERSON} each")
        print(f"vehicle trips: {zones['veh_productions'].sum():,.0f}")
        print(f"  {s.CAR_SHARE:.0%} by car at {s.OCCUPANCY} people per vehicle "
              f"= {vehicle_factor:.3f} vehicles per person trip")
        by_area = set(zones.nlargest(15, "activity_m2")["zone"])
        by_pull = set(zones.nlargest(15, "veh_attractions")["zone"])
        print(f"top 15 attracting zones, by floor area and by the rates: "
              f"{len(by_area & by_pull)} in both")

        print("\nThe O-D matrix:")
        vectors = (zones.set_index("zone_number")[["veh_productions", "veh_attractions"]]
                   .sort_index().rename(columns={"veh_productions": "productions",
                                                 "veh_attractions": "attractions"}))
        if not np.array_equal(vectors.index.to_numpy().astype(int), self.all_zones):
            raise ValueError("the demand vectors are not in the same order as the skim")
        self.gravity = Gravity(self.cost, vectors, s.DETERRENCE, s.BETA_FLOOR, s.BETA_CEILING)
        demand = self.gravity.solve(s.MEAN_TRIP_MIN)

        print("\nIs the matrix sensible?")
        self.gravity.check(demand)
        by_number = zones.set_index("zone_number")
        stayers(demand, self.gravity.vectors, self.cost,
                lambda z: f"{by_number.at[z, 'zone']} {by_number.at[z, 'nom_par']:<20}",
                lambda z: f"non-residential floor area {by_number.at[z, 'activity_m2']:,.0f} m2")
        busiest_pairs(demand, self.cost, self.all_zones,
                      {z: f"{r.zone} {r.nom_par}" for z, r in by_number.iterrows()}, n=8)
        return demand

    def after_assignment(self):
        """Against the ten worst roads the AMT names (Primicias, 8 January 2024)."""
        over = self.load["over"]
        print(f"\nagainst the ten worst roads named by the AMT (Primicias, 8 January 2024):")
        print(f"  {'road':<30}{'over capacity':>14}{'typical V/C':>13}")
        named_over = over[over["name"].notna()]
        found = 0
        for label, pattern in AMT_WORST.items():
            hit = named_over[named_over["name"].str.contains(pattern, case=False, regex=False)]
            if len(hit):
                found += 1
                print(f"  {label:<30}{hit['distance'].sum() / 1000:>11,.1f} km"
                      f"{hit['voc'].median():>13.2f}")
            else:
                print(f"  {label:<30}{'not congested here':>27}")
        print(f"  {found} of {len(AMT_WORST)} appear in the model's over-capacity network")

    def caveats(self):
        print("  the Agencia Metropolitana de Transito puts the yearly delay at 63 hours "
              "(Primicias, 8 January 2024)")

    def export(self, ex):
        zones, demand = self.zones, self.demand
        fields = (["zone", "zone_number", "parroquia", "nom_par", "adm_zonal", "area_km2",
                   "n_sectors", "pop", "dwellings", "density"] + CLASSES
                  + ["built_m2", "activity_m2", "dominant", "productions", "attractions",
                     "veh_productions", "veh_attractions"])

        def simplify(out):
            # Dissolving sectors into zones leaves every point of the shared sector edges
            # behind, most of them collinear. Snapping at half a metre drops most of them and
            # moves no boundary anyone could measure.
            out["geometry"] = (out.to_crs(self.metre_crs).simplify(ZONE_SIMPLIFY_M)
                               .to_crs("EPSG:4326"))
            return out

        ex.zones(zones, fields, extra=simplify)
        ex.od(demand, self.all_zones, self.cost, self.congested, self.distance_km)
