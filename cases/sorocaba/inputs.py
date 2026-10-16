"""Sorocaba sections A-D: what the zones are built from, the zones, and the commuting.

Each function takes the `Sorocaba` model and leaves what it builds on it, so later steps can
read it: `m.sectors`, `m.aps`, `m.zones`, `m.flows_out`, ...
"""
import gc
import html
import io
import os
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd

from core import report, zoning
from core.maps import AREA_RAMP, DENSITY_RAMP, MapKit, tip_html

from . import maps as smaps

MUNICIPIO = "3552205"        # Sorocaba; the 5-digit form without the state is used by 2010 files
MUNICIPIO_2010 = MUNICIPIO[2:]
VOTORANTIM = "3557006"
ESPECIE = {"1": "dwelling", "2": "collective", "3": "agricultural", "4": "teaching",
           "5": "health", "6": "other_estab", "7": "construction", "8": "religious"}
VACANT = r"\b(?:VAG[OA]S?|DESOCUPAD[OA]|FECHAD[OA]|ABANDONAD[OA]|DESATIVAD[OA])\b"
SHARED_BORDER_M = 1.0        # the least common border that makes two sectors neighbours
DRIVING_AGE = 18             # the age a Brazilian driving licence can be had


def files(p):
    """The inputs as tools/trim_inputs.py cuts them from the originals (data/sorocaba/input/):
    the census sample's records the model keeps, the state mesh's region, municipalities' centres
    and outlines, Sorocaba's rows of the weighting areas' composition, the counts it reads."""
    derived = p.inp("derived")
    sample = p.inp("sample_2010")
    return {
        "sectors": os.path.join(derived, "SOROCABA_setores_2022_completo.gpkg"),
        "crosswalk": os.path.join(derived, "crosswalk_setores_SOROCABA_2010_2022.csv"),
        "ap_2010": os.path.join(derived, "areas_ponderacao_SOROCABA_2010.csv"),
        "ap_composition": p.inp("ap_composition.txt"),
        "households_2010": os.path.join(sample, "households.csv"),
        "persons_2010": os.path.join(sample, "persons.csv"),
        "commuters_2010": os.path.join(sample, "commuters_in.csv"),
        "population_2010": os.path.join(sample, "population.csv"),
        "cnefe": p.inp("8_addresses", "CNEFE_3552205_SOROCABA.zip"),
        "cempre": p.inp("7_reference", "CEMPRE_9528_SOROCABA.csv"),
        "municipios": p.inp("7_reference", "IBGE_cidades_municipios_SP.csv"),
        "region_mesh": p.inp("sectors_region.gpkg.zip"),
        "commuting_mesh": p.inp("sectors_commuting.gpkg.zip"),
        "centres": p.inp("municipality_centres.csv"),
        "municipalities": p.inp("municipalities.gpkg"),
        # ARTESP's traffic counts, 2026 - not an input to the model, only what it is checked
        # against (F)
        "toll_hourly": p.inp("counts", "toll_hourly.csv"),
        "sat_daily": p.inp("counts", "sat_daily.csv"),
    }


def read_sectors(m):
    """A1. The census sectors: IBGE's 2022 mesh for the municipality, with the inhabited area and
    the 2010 geocode joined on."""
    report.section("A1. The census sectors")
    sectors = gpd.read_file(m.files["sectors"])
    sectors = sectors.rename(columns={"v0001": "pop", "v0002": "dwellings", "v0007": "households",
                                      "v0005": "per_household"})
    sectors["pop"] = sectors["pop"].fillna(0)
    # Areas need a projected CRS; the file is in SIRGAS 2000 degrees.
    m.metre_crs = sectors.estimate_utm_crs()
    m.maps = MapKit(m.metre_crs, m.paths.maps)
    sectors["area_km2"] = sectors.to_crs(m.metre_crs).area / 1e6
    sectors["density"] = sectors["pop"] / sectors["area_km2"]
    sectors["favela"] = sectors["CD_FCU"].fillna(".").ne(".")

    print(f"{len(sectors):,} sectors, crs {sectors.crs.to_string()}, metric crs "
          f"{m.metre_crs.to_string()}")
    print(f"population {sectors['pop'].sum():,.0f}, dwellings {sectors['dwellings'].sum():,.0f}, "
          f"occupied households {sectors['households'].sum():,.0f}")
    print(f"area {sectors['area_km2'].sum():,.1f} km2; distritos {sectors['CD_DIST'].nunique()}, "
          f"subdistritos {sectors['CD_SUBDIST'].nunique()}, "
          f"bairros named {sectors['NM_BAIRRO'].notna().sum()}")
    print("\nBy situation:")
    print(sectors.groupby("SITUACAO_DESC").agg(sectors=("CD_SETOR", "size"), people=("pop", "sum"),
                                               km2=("area_km2", "sum"))
          .round(1).sort_values("people", ascending=False).to_string())
    q = sectors["pop"].quantile([0, 0.1, 0.5, 0.9, 1])
    print(f"\nPeople per sector: min {q[0]:.0f} | 10th {q[0.1]:.0f} | median {q[0.5]:.0f} | "
          f"90th {q[0.9]:.0f} | max {q[1]:.0f}")
    print(f"Sectors with nobody living in them: {(sectors['pop'] == 0).sum()}")
    print(f"Favela / comunidade urbana: {sectors['favela'].sum()} sectors, "
          f"{sectors.loc[sectors['favela'], 'pop'].sum():,.0f} people")
    m.sectors = sectors


def weighting_areas(m):
    """A2-A3. The 19 áreas de ponderação of the 2010 census sample, reached through two files.

    1. Composicao_das_Areas_de_Ponderacao.txt - weighting area -> 2010 sector (UTF-16)
    2. crosswalk_setores_SOROCABA_2010_2022.csv - 2010 sector -> 2022 sector
    A 2022 sector with two parents in different areas takes the one most of its parents belong
    to; where evenly split, the one of the two it shares the longest border with. One whose
    parents are in no area takes the area it shares the longest border with.
    """
    report.section("A2. The áreas de ponderação")
    sectors = m.sectors
    comp = pd.read_csv(m.files["ap_composition"], sep="\t", encoding="utf-16", dtype=str)
    comp.columns = ["ap", "setor_2010"]
    comp = comp[comp["ap"].str.startswith(MUNICIPIO)]
    cw = pd.read_csv(m.files["crosswalk"], sep=";", encoding="utf-8-sig", dtype=str)
    print(f"composition: {comp['ap'].nunique()} weighting areas, {len(comp)} 2010 sectors")
    print(f"crosswalk: {len(cw):,} rows for {cw['GEOCODIGO_2022'].nunique():,} 2022 sectors")

    chain = cw.merge(comp, left_on="GEOCODIGO_2010", right_on="setor_2010", how="left")
    votes = (chain.dropna(subset=["ap"]).groupby(["GEOCODIGO_2022", "ap"]).size()
             .rename("n").reset_index().sort_values(["GEOCODIGO_2022", "n"],
                                                    ascending=[True, False]))
    split = votes.groupby("GEOCODIGO_2022")["ap"].nunique()
    top = votes.groupby("GEOCODIGO_2022")["n"].transform("max")
    tied = votes[votes["n"] == top].groupby("GEOCODIGO_2022")["ap"].agg(list)
    tied = tied[tied.str.len() > 1]
    print(f"\n2022 sectors in exactly one weighting area: {(split == 1).sum():,}")
    print(f"  in two: {(split > 1).sum()} - {(split > 1).sum() - len(tied)} by a majority of "
          f"parents, {len(tied)} evenly split and settled by the longest shared border")
    ap_of = votes.drop_duplicates("GEOCODIGO_2022").set_index("GEOCODIGO_2022")["ap"]
    ap_of = ap_of.drop(index=tied.index)
    sectors["ap"] = sectors["CD_SETOR"].map(ap_of)

    # Repeated, because an unassigned sector may only touch other unassigned sectors on the
    # first pass.
    sec_m = sectors.to_crs(m.metre_crs)
    orphans = sectors.index[sectors["ap"].isna() & ~sectors["CD_SETOR"].isin(tied.index)]
    print(f"  in none: {len(orphans)}, holding {sectors.loc[orphans, 'pop'].sum():,.0f} people; "
          f"they take the area they share the longest border with")
    for _ in range(5):
        still = sectors.index[sectors["ap"].isna()]
        if not len(still):
            break
        for i in still:
            shape = sec_m.geometry[i]
            near = sec_m[sec_m.geometry.touches(shape) & sectors["ap"].notna()]
            candidates = tied.get(sectors.at[i, "CD_SETOR"])
            if candidates is not None:
                near = near[sectors.loc[near.index, "ap"].isin(candidates)]
            if len(near):
                shared = near.geometry.intersection(shape.boundary).length
                sectors.loc[i, "ap"] = sectors.loc[shared.idxmax(), "ap"]
    if sectors["ap"].isna().any():
        raise RuntimeError("some sectors reach no weighting area even through their neighbours")
    # The official codes are 13 digits; AP01..AP19 is what the maps and tables show.
    labels = {code: f"AP{int(code[-2:]):02d}" for code in sorted(sectors["ap"].unique())}
    sectors["ap_label"] = sectors["ap"].map(labels)
    print(f"\nevery sector now sits in one of {sectors['ap'].nunique()} weighting areas")

    report.section("A3. The weighting areas as a layer")
    ap2010 = pd.read_csv(m.files["ap_2010"], sep=";", encoding="utf-8-sig",
                         dtype={"cod_area_ponderacao": str}).set_index("cod_area_ponderacao")
    aps = sectors.dissolve(by="ap", aggfunc={"pop": "sum", "households": "sum", "area_km2": "sum",
                                             "CD_SETOR": "count", "ap_label": "first"})
    aps = aps.rename(columns={"CD_SETOR": "n_sectors"}).reset_index()
    aps["pop_2010"] = aps["ap"].map(ap2010["populacao_estimada"])
    aps["growth"] = aps["pop"] / aps["pop_2010"] - 1
    aps["density"] = aps["pop"] / aps["area_km2"]
    print(f"{len(aps)} weighting areas; population 2010 {aps['pop_2010'].sum():,.0f} -> 2022 "
          f"{aps['pop'].sum():,.0f} ({100 * (aps['pop'].sum() / aps['pop_2010'].sum() - 1):.1f}%)")
    cols = ["ap_label", "n_sectors", "area_km2", "pop_2010", "pop", "growth"]
    print("Fastest and slowest growing, 2010-2022:")
    print(aps.sort_values("growth", ascending=False)[cols].head(4).round(2).to_string(index=False))
    print(aps.sort_values("growth")[cols].head(3).round(2).to_string(index=False))

    m.aps = aps


def sample_2010(m):
    """A5-A6. Cars and income, from the 2010 census sample; and the commuting records.

    The state's samples (SP1.zip outside the São Paulo metropolitan region, SP2_RM.zip the
    region) are fixed-width records, one per sampled household and one per sampled person, with
    a weight each: tools/trim_inputs.py keeps Sorocaba's households and persons, the people of
    other municipalities who work or study in it, and every municipality's 2010 population, their
    fields as the records have them. Car ownership is a share of private households: a blank
    V0222 is a collective dwelling. The figures are 2010, and are used as relative values between
    areas, not as a 2022 level.
    """
    report.section("A5. Cars and income, from the 2010 sample")

    def read(key):
        frame = pd.read_csv(m.files[key], dtype=str, keep_default_na=False)
        frame["w"] = frame.pop("weight").astype(int) / 1e13      # the records' own weight
        return frame

    households = read("households_2010")[["ap", "w", "car", "moto"]]
    collective = ~households["car"].isin(["1", "2"])
    print(f"collective dwellings in the household sample, left out of the shares: "
          f"{households.loc[collective, 'w'].sum():,.0f} weighted")
    households = households[~collective]

    # Persons: income, plus every record needed later for commuting. A resident of Sorocaba is
    # kept whole; a resident of anywhere else only if they work or study in Sorocaba.
    persons = read("persons_2010")[["ap", "w", "income", "work_where", "work_mun", "work_daily",
                                    "work_time", "study_where", "study_mun", "age"]]
    persons["income"] = pd.to_numeric(persons["income"], errors="coerce") / 100
    commuters = read("commuters_2010")[["origin", "w", "works", "work_daily", "studies", "age"]]
    commuters["works"], commuters["studies"] = commuters["works"] == "1", commuters["studies"] == "1"
    # V6036, age in years: decides who among the students can drive (E9).
    for frame in (persons, commuters):
        frame["age"] = pd.to_numeric(frame["age"], errors="coerce")
    population = pd.read_csv(m.files["population_2010"], dtype={"municipio": str, "pop_2010": str})
    m.pop_2010 = pd.Series(population["pop_2010"].astype(float).to_numpy(),
                           index=population["municipio"].to_numpy())
    m.rmsp_codes = set(population.loc[population["rmsp"] == 1, "municipio"])
    print(f"households sampled: {len(households):,}, weighted {households['w'].sum():,.0f}")
    print(f"persons sampled:    {len(persons):,}, weighted {persons['w'].sum():,.0f} "
          f"(official 2010 population: 586,625)")
    print(f"people elsewhere in the state who work or study in Sorocaba: "
          f"{len(commuters):,} sampled, {commuters['w'].sum():,.0f} weighted")

    own = households.assign(has_car=households["car"].eq("1") * households["w"],
                            has_moto=households["moto"].eq("1") * households["w"])
    by_ap = own.groupby("ap").agg(households=("w", "sum"), car=("has_car", "sum"),
                                  moto=("has_moto", "sum"))
    by_ap["car_share_hh"] = by_ap["car"] / by_ap["households"]
    by_ap["moto_share_hh"] = by_ap["moto"] / by_ap["households"]

    def weighted_median(values, weights):
        order = np.argsort(values)
        cum = np.cumsum(weights[order])
        return float(values[order][np.searchsorted(cum, cum[-1] / 2)])

    inc = persons.dropna(subset=["income"])
    by_ap["income_pc"] = inc.groupby("ap").apply(
        lambda g: weighted_median(g["income"].to_numpy(), g["w"].to_numpy()),
        include_groups=False)
    aps = m.aps
    aps = aps.drop(columns=[c for c in by_ap.columns if c in aps.columns]).merge(
        by_ap, left_on="ap", right_index=True, how="left")
    m.city_car_share_hh = float(by_ap["car"].sum() / by_ap["households"].sum())
    print(f"\nhouseholds with a car, whole city: {100 * m.city_car_share_hh:.1f}%")
    print(f"  by weighting area: {100 * aps['car_share_hh'].min():.0f}% to "
          f"{100 * aps['car_share_hh'].max():.0f}%")
    print(f"median family income per head: R$ {aps['income_pc'].min():,.0f} to "
          f"R$ {aps['income_pc'].max():,.0f} across the areas (2010 reais)")
    print(f"  correlation of car ownership with income, across areas: "
          f"{aps[['car_share_hh', 'income_pc']].corr().iloc[0, 1]:.2f}")
    report.preview(aps.sort_values("ap_label").round(3), "weighting areas",
                   columns=["ap_label", "n_sectors", "pop_2010", "pop", "growth", "car_share_hh",
                            "moto_share_hh", "income_pc"], rows=19)

    report.section("A6. Who owns a car")
    tips = [tip_html(r.ap_label, [("people 2010", f"{r.pop_2010:,.0f}"),
                                  ("people 2022", f"{r.pop:,.0f}"),
                                  ("growth", f"{100 * r.growth:+.0f}%"),
                                  ("households with a car", f"{100 * r.car_share_hh:.0f}%"),
                                  ("with a motorcycle", f"{100 * r.moto_share_hh:.0f}%"),
                                  ("family income per head, median", f"R$ {r.income_pc:,.0f}"),
                                  ("census sectors", f"{r.n_sectors}")],
                     tag="2010 sample", tag_color="#104281")
            for r in aps.itertuples()]
    m.maps.choropleth(aps, "car_share_hh", AREA_RAMP, tips, "Weighting areas, by car ownership",
                      "Households with a car, 2010", "quintiles &middot; darker = more cars",
                      "Car ownership by weighting area",
                      [f"{100 * m.city_car_share_hh:.0f}% of households city-wide",
                       f"from {100 * aps['car_share_hh'].min():.0f}% to "
                       f"{100 * aps['car_share_hh'].max():.0f}% across {len(aps)} areas",
                       '<span style="color:#555;">2010 census sample, weighted</span>'],
                      "2_car_ownership.html", fmt="{:.0%}", layer_panel=False)
    m.aps, m.persons_2010, m.commuters_in_2010 = aps, persons, commuters


def jobs(m):
    """B. What happens in each sector: CNEFE says **where** activity is, CEMPRE **how much**.

    CNEFE's addresses carry a sector code (with a trailing letter, stripped) and an espécie.
    Addresses whose sector code the final mesh lacks are placed by their coordinates; vacant
    establishments are not counted. CEMPRE is filtered to its 21 CNAE sections, and jobs per
    address are measured by espécie: teaching = P, health = Q, agricultural = A, every other
    section is an establishment of espécie 6.
    """
    report.section("B1. The addresses")
    sectors = m.sectors
    with zipfile.ZipFile(m.files["cnefe"]) as z:
        cnefe = pd.read_csv(z.open(z.namelist()[0]), sep=";", dtype=str,
                            usecols=["COD_SETOR", "COD_ESPECIE", "DSC_ESTABELECIMENTO",
                                     "LATITUDE", "LONGITUDE"])
    cnefe["CD_SETOR"] = cnefe["COD_SETOR"].str[:15]
    cnefe["especie"] = cnefe["COD_ESPECIE"].map(ESPECIE)
    print(f"{len(cnefe):,} addresses, with coordinates: {100 * cnefe['LATITUDE'].notna().mean():.1f}%")

    # Some addresses carry a sector code that the final 2022 mesh no longer has - sectors
    # subdivided after the address list was frozen. They are placed by location: inside the
    # sector they fall in, or the nearest one if they fall just outside.
    stale = ~cnefe["CD_SETOR"].isin(set(sectors["CD_SETOR"]))
    pts = gpd.GeoDataFrame(cnefe.loc[stale, []], crs="EPSG:4674", geometry=gpd.points_from_xy(
        cnefe.loc[stale, "LONGITUDE"].astype(float), cnefe.loc[stale, "LATITUDE"].astype(float)))
    hit = gpd.sjoin_nearest(pts.to_crs(m.metre_crs),
                            sectors[["CD_SETOR", "geometry"]].to_crs(m.metre_crs),
                            how="left", max_distance=500, distance_col="off_m")
    hit = hit[~hit.index.duplicated(keep="first")]
    cnefe.loc[stale, "CD_SETOR"] = hit["CD_SETOR"]
    print(f"  {stale.sum():,} carry a sector code the final mesh does not have; placed by "
          f"coordinates, {(hit['off_m'] == 0).mean():.1%} inside a sector, "
          f"{hit['CD_SETOR'].isna().sum()} left unplaced")
    cnefe = cnefe[cnefe["CD_SETOR"].notna()]
    vacant = (cnefe["COD_ESPECIE"].isin(["3", "4", "5", "6", "8"])
              & cnefe["DSC_ESTABELECIMENTO"].fillna("").str.upper().str.contains(VACANT))
    print(f"  {vacant.sum():,} establishments described as vacant or closed; not counted")
    cnefe.loc[vacant, "especie"] = "vacant"
    print("\nby espécie:")
    print(cnefe["especie"].value_counts().to_string())
    addresses = (cnefe.pivot_table(index="CD_SETOR", columns="especie", values="COD_SETOR",
                                   aggfunc="size", fill_value=0)
                 .reindex(columns=list(ESPECIE.values()), fill_value=0))
    # CNEFE's dwellings against the census count come from the same field operation; a big gap
    # would mean the join is losing addresses.
    dw = sectors.set_index("CD_SETOR")["dwellings"]
    cmp = pd.concat([addresses["dwelling"] + addresses["collective"], dw], axis=1).fillna(0)
    print(f"\ndwelling addresses {int(cmp.iloc[:, 0].sum()):,} against census dwellings "
          f"{int(cmp.iloc[:, 1].sum()):,}; correlation by sector {cmp.corr().iloc[0, 1]:.3f}")

    report.section("B2. How many jobs an address stands for")
    cempre = pd.read_csv(m.files["cempre"], sep=";", encoding="utf-8-sig")
    cempre["valor"] = pd.to_numeric(cempre["valor"], errors="coerce")
    sections = cempre[cempre["cnae"].str.match(r"^[A-U] ")
                      & cempre["variavel"].str.contains("ocupado total", case=False)]
    sections = sections.assign(section=sections["cnae"].str[0]).set_index("section")["valor"] \
        .fillna(0)
    total = cempre.loc[cempre["cnae"].eq("Total")
                       & cempre["variavel"].str.contains("ocupado total", case=False),
                       "valor"].iloc[0]
    print(f"CEMPRE 2024: {sections.sum():,.0f} jobs over the 21 sections "
          f"(published total {total:,.0f})")
    section_of = {"teaching": ["P"], "health": ["Q"], "agricultural": ["A"]}
    section_of["other_estab"] = [s for s in sections.index
                                 if s not in sum(section_of.values(), [])]
    m.job_classes = list(section_of)
    jobs_per_address = pd.Series({k: sections[v].sum() / addresses[k].sum()
                                  for k, v in section_of.items()})
    print("\njobs per address, measured:")
    for k in m.job_classes:
        print(f"  {k:<13} {sections[section_of[k]].sum():>8,.0f} jobs / "
              f"{addresses[k].sum():>6,} addresses = {jobs_per_address[k]:5.1f}")

    report.section("B3. Jobs on the sectors")
    job_cols = addresses[m.job_classes].mul(jobs_per_address, axis=1).add_prefix("jobs_")
    sectors = sectors.merge(addresses, left_on="CD_SETOR", right_index=True, how="left")
    sectors = sectors.merge(job_cols, left_on="CD_SETOR", right_index=True, how="left")
    fill = list(ESPECIE.values()) + [f"jobs_{k}" for k in m.job_classes]
    sectors[fill] = sectors[fill].fillna(0)
    sectors["jobs"] = sectors[[f"jobs_{k}" for k in m.job_classes]].sum(axis=1)
    sectors["size"] = sectors["pop"] + sectors["jobs"]
    print(f"jobs placed: {sectors['jobs'].sum():,.0f} of {sections.sum():,.0f}")
    print(f"sectors with any job: {(sectors['jobs'] > 0).sum():,} of {len(sectors):,}")
    print(f"jobs per resident, whole city: {sectors['jobs'].sum() / sectors['pop'].sum():.2f}")
    lonely = sectors[(sectors["pop"] < 50) & (sectors["jobs"] > 200)]
    print(f"sectors with jobs and almost nobody living there: {len(lonely)}, "
          f"{lonely['jobs'].sum():,.0f} jobs")
    # The biggest employers by name, so the sectors on top can be recognised.
    names = (cnefe[cnefe["especie"].isin(m.job_classes) & cnefe["DSC_ESTABELECIMENTO"].notna()]
             .groupby("CD_SETOR")["DSC_ESTABELECIMENTO"]
             .agg(lambda s: ", ".join(s.value_counts().index[:2])))
    top = sectors.nlargest(10, "jobs")[["CD_SETOR", "ap_label", "pop", "other_estab", "teaching",
                                        "health", "jobs"]].copy()
    top["examples"] = top["CD_SETOR"].map(names).str[:48]
    print("\nthe ten sectors holding the most jobs (other_estab, teaching, health count "
          "establishment addresses):")
    print(top.round(0).to_string(index=False))
    m.sectors = sectors


def _rule_zones(m, sectors, sec_m):
    """C, by the rules (build_zones' 1-4): sets each sector's zone; returns the adjacency."""
    s = m.s
    edges, corners = zoning.adjacency(sec_m, SHARED_BORDER_M)
    print(f"{len(sectors):,} sectors, {len(edges):,} adjacency pairs "
          f"({len(edges) / len(sectors):.1f} neighbours each); {corners} pairs meet only at a "
          f"corner and are not counted")

    base, _ = pd.factorize(sectors["ap"])
    part = zoning.pieces(base, edges, len(sectors))
    zone_of = np.array([f"{a}-{p}" for a, p in zip(base, part)], dtype=object)
    print(f"after rules 1-2: {len(set(zone_of))} groups (the {sectors['ap'].nunique()} weighting "
          f"areas, split where they are not one piece)")

    size = sectors["size"].to_numpy()
    xy = np.column_stack([sec_m.geometry.representative_point().x,
                          sec_m.geometry.representative_point().y])
    zone_of, passes = zoning.split_large(zone_of, size, edges, xy, s.MAX_ZONE_SIZE, passes=12,
                                         too_few="all", sep=".")
    left = zoning.sizes(zone_of, size)
    print(f"after rule 3 ({passes} passes): {len(left)} zones, "
          f"{(left > s.MAX_ZONE_SIZE).sum()} still over {s.MAX_ZONE_SIZE:,} - single sectors, "
          f"which cannot be split further")
    zone_of, done = zoning.merge_small(zone_of, size, edges, sectors["ap"].to_numpy(),
                                       s.MIN_ZONE_SIZE, s.MAX_ZONE_SIZE)
    final = zoning.sizes(zone_of, size)
    over = final[final > s.MAX_ZONE_SIZE]
    over_multi = [z for z in over.index if (zone_of == z).sum() > 1]
    print(f"rule 4: merged {done['merged']} zones under {s.MIN_ZONE_SIZE:,}"
          + (f"; {done['kept']} had no neighbour in their area and were kept" if done["kept"]
             else ""))
    print(f"  {done['overflow']} of them had no neighbour with room, and joined the one ending "
          f"smallest")
    print(f"  zones over {s.MAX_ZONE_SIZE:,} after both rules: {len(over)} "
          f"({len(over) - len(over_multi)} single sectors, {len(over_multi)} of several), "
          f"largest {final.max():,.0f}")
    sectors["zone"] = zone_of
    sectors["zone"] = zoning.renumber(sectors, "zone", "ap_label", "CD_SETOR", 3)
    print(f"zones numbered Z001 to Z{sectors['zone'].nunique():03d}")
    return edges


def build_zones(m):
    """C. From sectors to zones, with the weighting areas as the hard edge.

    1. every zone sits inside one weighting area, so it inherits that area's car ownership
    2. a zone is one connected piece; sectors meeting only at a corner are not neighbours
    3. a group larger than MAX_ZONE_SIZE is split into compact contiguous pieces, repeatedly,
       until none is - except single sectors, which cannot be split
    4. a zone smaller than MIN_ZONE_SIZE joins a neighbour in its area: one it can join without
       going over MAX_ZONE_SIZE if there is one, and among those the one sharing most borders
    Size is people plus jobs; the centroid is weighted by people plus jobs. With a zoning file
    loaded (core/zoning.from_file) its zones replace the rules: each sector goes to the file's
    zone holding its centre.
    """
    report.section("C. From sectors to zones")
    sectors = m.sectors.reset_index(drop=True)
    sectors["row"] = np.arange(len(sectors))
    sec_m = sectors.to_crs(m.metre_crs)
    loaded = (m.inputs or {}).get("zoning")
    if loaded:                         # the zones are a file's, not the rules'
        labels, m.zoning_report = zoning.from_file(sec_m, loaded["path"],
                                                   loaded.get("id_column", ""))
        keep = labels != None                                    # noqa: E711 - an array
        print(f"zones from {loaded['name']}: {len(set(labels[keep])):,} zones, "
              f"{int(keep.sum()):,} of {len(sectors):,} sectors in them "
              f"({sectors.loc[keep, 'pop'].sum():,.0f} of {sectors['pop'].sum():,.0f} people, "
              f"{sectors.loc[keep, 'jobs'].sum():,.0f} of {sectors['jobs'].sum():,.0f} jobs)")
        sectors = sectors[keep].reset_index(drop=True)
        sectors["row"] = np.arange(len(sectors))
        sectors["file_id"] = labels[keep]
        sec_m = sectors.to_crs(m.metre_crs)
        edges, _ = zoning.adjacency(sec_m, SHARED_BORDER_M)
        sectors["zone"] = zoning.renumber(sectors, "file_id", "ap_label", "CD_SETOR", 3)
        print(f"zones numbered Z001 to Z{sectors['zone'].nunique():03d}")
    else:
        edges = _rule_zones(m, sectors, sec_m)

    report.section("C1. The zones")
    total = ["pop", "dwellings", "households", "area_km2", "jobs", "size"] + \
        [f"jobs_{k}" for k in m.job_classes] + list(ESPECIE.values())
    zones = sectors.dissolve(by="zone", aggfunc={**{c: "sum" for c in total},
                                                 "CD_SETOR": "count", "ap": "first",
                                                 "ap_label": "first", "favela": "sum"})
    zones = zones.rename(columns={"CD_SETOR": "n_sectors",
                                  "favela": "favela_sectors"}).reset_index()
    zones["density"] = zones["pop"] / zones["area_km2"]
    zones["jobs_per_resident"] = zones["jobs"] / zones["pop"].replace(0, np.nan)
    zones = zones.merge(m.aps[["ap", "car_share_hh", "moto_share_hh", "income_pc"]], on="ap",
                        how="left")
    centroids, moved = zoning.weighted_centroids(
        sec_m, sectors["zone"], sectors["size"], zones.set_index("zone").to_crs(m.metre_crs))
    zones["centroid"] = centroids.reindex(zones["zone"]).to_numpy()
    print(f"centroids moved inside their zone: {moved} of {len(zones)}")
    if "file_id" in sectors:            # a loaded zoning: each zone's id in the file
        zones["file_id"] = zones["zone"].map(sectors.groupby("zone")["file_id"].first())
    parts = zoning.pieces_per_zone(sectors["zone"].to_numpy(), edges, len(sectors)) \
        .reindex(zones["zone"])
    print(f"\n{len(zones):,} zones, from {len(sectors):,} sectors")
    print(f"  people preserved: {zones['pop'].sum():,.0f}, jobs preserved: "
          f"{zones['jobs'].sum():,.0f}")
    for col, lab in (("size", "people + jobs"), ("pop", "people"), ("jobs", "jobs")):
        q = zones[col].quantile([0, 0.1, 0.5, 0.9, 1])
        print(f"  {lab:<14} min {q[0]:>6,.0f} | 10th {q[0.1]:>6,.0f} | median {q[0.5]:>6,.0f} | "
              f"90th {q[0.9]:>6,.0f} | max {q[1]:>6,.0f}")
    print(f"  zones spanning two weighting areas: "
          f"{(sectors.groupby('zone')['ap'].nunique() > 1).sum()}")
    print(f"  zones that are one connected piece: {(parts == 1).sum()} of {len(zones)}")
    report.preview(zones.round(2), "zones", columns=["zone", "ap_label", "n_sectors", "pop",
                                                     "jobs", "size", "area_km2", "car_share_hh"])

    report.section("C2-C3. What they look like")
    smaps.map_jobs(m.maps, zones)
    # AequilibraE wants an integer zone id; ours read Z001..
    zones["zone_number"] = zones["zone"].str.lstrip("Z").astype(int)
    m.sectors, m.zones = sectors, zones
    m.boundary = sectors[["geometry"]].dissolve()
    m.city = sectors.to_crs(m.metre_crs).geometry.union_all()


def neighbours(m):
    """D1. The neighbours: the census sectors within REACH_KM of the city, from the state mesh.

    Their outlines tell which municipalities border the city, and E7 routes each sector to it.
    Names and 2022 population come from the IBGE table - the sectors read stop at the edge of
    the area read and would cut a large municipality short.
    """
    report.section("D1. The neighbours")
    mun = pd.read_csv(m.files["municipios"], encoding="utf-8-sig", skiprows=1)
    mun.columns = [html.unescape(c) for c in mun.columns]
    mun = mun[pd.to_numeric(mun.iloc[:, 1], errors="coerce").notna()]
    municipios = pd.DataFrame({
        "code": mun.iloc[:, 1].astype(int).astype(str),
        "name": mun.iloc[:, 0].map(html.unescape),
        "pop_2022": pd.to_numeric(mun.iloc[:, 5], errors="coerce")}).set_index("code")
    municipios["pop_2010"] = m.pop_2010.reindex(municipios.index)
    print(f"{len(municipios)} municipalities in the IBGE table; "
          f"{municipios['pop_2010'].notna().sum()} found in the 2010 sample")
    if municipios["pop_2010"].isna().any():
        print(f"  missing from the sample: "
              f"{', '.join(municipios.loc[municipios['pop_2010'].isna(), 'name'])}")
    if municipios.loc[MUNICIPIO, "pop_2022"] != m.sectors["pop"].sum():
        raise ValueError("the IBGE table and the census sectors disagree about Sorocaba's "
                         "population")

    home = m.city
    bbox = gpd.GeoSeries([home.buffer(m.s.REACH_KM * 1000)], crs=m.metre_crs).to_crs("EPSG:4674")
    mesh = gpd.read_file(unzipped_mesh(m, "region_mesh"), bbox=tuple(bbox.total_bounds),
                         columns=["CD_MUN", "NM_MUN", "v0001"])
    # Every sector is kept as a point with its population, and its exact outline: E7 routes each
    # one to the city, tells from the outlines which places border which, and dissolves them
    # into the external zones' shapes. Empty sectors are kept: they fill in those shapes.
    region_people = gpd.GeoDataFrame(
        {"code": mesh["CD_MUN"], "pop": mesh["v0001"].fillna(0)},
        geometry=mesh.to_crs(m.metre_crs).representative_point(), crs=m.metre_crs)
    region_people["shape"] = mesh.to_crs(m.metre_crs).geometry.to_numpy()
    region_people = region_people[region_people["code"] != MUNICIPIO]
    nb = mesh.dissolve(by="CD_MUN", aggfunc={"NM_MUN": "first", "v0001": "sum"}).reset_index()
    nb = nb.rename(columns={"CD_MUN": "code", "NM_MUN": "name", "v0001": "pop_2022"})
    nb = nb[nb["code"] != MUNICIPIO].to_crs(m.metre_crs)
    nb["pop_2022"] = nb["code"].map(municipios["pop_2022"])
    nb["km"] = nb.geometry.distance(home) / 1000
    nb["adjacent"] = nb["km"] < 0.05
    print(f"{len(nb)} municipalities with sectors in the area read; {nb['adjacent'].sum()} share "
          f"a border with Sorocaba: {', '.join(sorted(nb.loc[nb['adjacent'], 'name']))}")
    del mesh
    gc.collect()
    m.municipios, m.region_people, m.neighbours, m.bbox = municipios, region_people, nb, bbox


def unzipped_mesh(m, key):
    """A part of the state mesh as tools/trim_inputs.py keeps it - the sectors around the city
    (`region_mesh`), or the municipalities exchanging commuters with it that those do not hold
    whole (`commuting_mesh`): zipped in the inputs, unzipped once into the city's cache - read
    inside the zip they take minutes."""
    zipped = m.files[key]
    name = os.path.basename(zipped)[:-len(".zip")]
    path = m.paths.cached(name)
    if not os.path.exists(path) or os.path.getmtime(path) < os.path.getmtime(zipped):
        with zipfile.ZipFile(zipped) as z:
            z.extract(name, os.path.dirname(path))
        os.utime(path)                                     # newer than its zip: current
    return path


def commuting(m):
    """D2-D3. Who commutes, and where - each person counted once, in 2022 terms.

    Flows are counted in 2010 and scaled by population growth: Sorocaba's for people leaving,
    the origin's for people arriving. Students under 18 are `school` commuters, who cannot
    drive; from 18, `study`. Only workers returning home daily are kept, and nobody beyond the
    range of a daily commute - the distance within which DAILY_COMMUTE_PERCENTILE of the daily
    workers live.
    """
    report.section("D2. Who commutes, and where")
    s, persons, municipios = m.s, m.persons_2010, m.municipios
    growth_sorocaba = m.sectors["pop"].sum() / persons["w"].sum()

    # Where each municipality's people live, as a point: the population-weighted centre of its
    # census sectors, all the state's - worked out from the state mesh by tools/trim_inputs.py.
    centres = pd.read_csv(m.files["centres"], dtype={"CD_MUN": str}).set_index("CD_MUN")
    if centres["crs"].iloc[0] != m.metre_crs.to_string():
        raise ValueError(f"the municipalities' centres are in {centres['crs'].iloc[0]}, the model "
                         f"in {m.metre_crs.to_string()}: run tools/trim_inputs.py sorocaba again")
    centres = centres[["x", "y"]]
    km_from = (np.hypot(centres["x"] - centres.loc[MUNICIPIO, "x"],
                        centres["y"] - centres.loc[MUNICIPIO, "y"]) / 1000)

    # out: Sorocaba residents working or studying elsewhere, by weighting area of residence.
    works_out = (persons["work_where"] == "3") & (persons["work_daily"] == "1")
    work_out = persons[works_out]
    # A student who also works across the line is already counted as a worker.
    study_out = persons[(persons["study_where"] == "2") & ~works_out]
    out = pd.concat([work_out.assign(purpose="work", dest=work_out["work_mun"]),
                     study_out.assign(purpose=np.where(study_out["age"] < DRIVING_AGE,
                                                       "school", "study"),
                                      dest=study_out["study_mun"])])
    out["km"] = out["dest"].map(km_from)

    # in: residents of other municipalities working or studying in Sorocaba.
    cin = m.commuters_in_2010
    works_in = cin["works"] & (cin["work_daily"] == "1")
    in_work = cin[works_in]
    in_study = cin[cin["studies"] & ~works_in]
    in_all = pd.concat([in_work.assign(purpose="work"),
                        in_study.assign(purpose=np.where(in_study["age"] < DRIVING_AGE,
                                                         "school", "study"))])
    in_all["km"] = in_all["origin"].map(km_from)

    # The range of a daily commute, from the people who say they make one.
    daily = pd.concat([out.loc[out["purpose"] == "work", ["km", "w"]],
                       in_all.loc[in_all["purpose"] == "work", ["km", "w"]]]).dropna()
    daily = daily.sort_values("km")
    max_km = float(np.ceil(
        daily["km"].to_numpy()[np.searchsorted(daily["w"].cumsum().to_numpy(),
                                               s.DAILY_COMMUTE_PERCENTILE * daily["w"].sum())]
        / 10) * 10)
    print(f"daily workers, both directions: {s.DAILY_COMMUTE_PERCENTILE:.0%} live within "
          f"{max_km:,.0f} km of Sorocaba - the range of a daily commute")
    for label, frame in (("out", out), ("in", in_all)):
        far = frame["km"] > max_km
        print(f"  beyond it, not counted as daily commuters ({label}): "
              + ", ".join(f"{p} {frame.loc[far & (frame['purpose'] == p), 'w'].sum():,.0f}"
                          for p in ("work", "study", "school")))

    placeable = out["dest"].isin(municipios.index)
    in_range_out = out["km"] <= max_km
    print(f"\nresidents commuting out, 2010: {out.loc[in_range_out, 'w'].sum():,.0f}")
    print(f"  {out.loc[~placeable, 'w'].sum():,.0f} name no São Paulo municipality and are left "
          f"out; {persons.loc[persons['work_where'] == '5', 'w'].sum():,.0f} work in more than "
          f"one municipality and cannot be placed")
    flows_out = (out[placeable & in_range_out].groupby(["ap", "dest", "purpose"])["w"].sum()
                 .mul(growth_sorocaba).rename("commuters").reset_index())
    in_range_in = in_all["km"] <= max_km
    flows_in = (in_all[in_range_in].groupby(["origin", "purpose"])["w"].sum()
                .rename("commuters_2010").reset_index())
    growth = (municipios["pop_2022"] / municipios["pop_2010"]).rename("growth")
    flows_in = flows_in.merge(growth, left_on="origin", right_index=True, how="left")
    flows_in["commuters"] = flows_in["commuters_2010"] * flows_in["growth"].fillna(growth_sorocaba)
    print(f"non-residents commuting in, 2010: {flows_in['commuters_2010'].sum():,.0f}, of them "
          f"from the São Paulo metropolitan region: "
          f"{flows_in.loc[flows_in['origin'].isin(m.rmsp_codes), 'commuters_2010'].sum():,.0f}")
    print(f"commuters in 2022 terms: {flows_out['commuters'].sum():,.0f} out, "
          f"{flows_in['commuters'].sum():,.0f} in")

    by_municipio = pd.concat([
        flows_out.groupby("dest")["commuters"].sum().rename("out"),
        flows_in.groupby("origin")["commuters"].sum().rename("in")], axis=1).fillna(0)
    by_municipio["name"] = municipios["name"].reindex(by_municipio.index)
    by_municipio["total"] = by_municipio["out"] + by_municipio["in"]
    by_municipio = by_municipio.sort_values("total", ascending=False)
    print("\nthe municipalities exchanging most commuters with Sorocaba (2022 terms):")
    print(by_municipio.head(12)[["name", "in", "out", "total"]].round(0).to_string())
    v_in = by_municipio.loc[VOTORANTIM, "in"]
    next_ten = by_municipio.drop(index=VOTORANTIM)["in"].nlargest(10).sum()
    print(f"Votorantim sends {v_in:,.0f} into Sorocaba; the next ten municipalities together "
          f"send {next_ten:,.0f}")

    report.section("D3. The commuting map")
    codes = list(by_municipio.index[by_municipio["total"] >= 50])
    # The municipalities' outlines, simplified: a map's (tools/trim_inputs.py).
    drawn = gpd.read_file(m.files["municipalities"], columns=["CD_MUN"],
                          where=f"CD_MUN IN ({','.join(repr(c) for c in codes)})")
    drawn = drawn.rename(columns={"CD_MUN": "code"})
    drawn = drawn.merge(by_municipio[["name", "in", "out", "total"]], left_on="code",
                        right_index=True, how="inner")
    drawn["pop_2022"] = drawn["code"].map(municipios["pop_2022"])
    drawn = drawn.to_crs(m.metre_crs)
    drawn["km"] = drawn.geometry.distance(m.city) / 1000
    drawn["adjacent"] = drawn["code"].isin(set(m.neighbours.loc[m.neighbours["adjacent"], "code"]))
    drawn = drawn.to_crs("EPSG:4326")
    tips = [tip_html(n, [("commute into Sorocaba", f"{i:,.0f} a day"),
                         ("commute out of Sorocaba", f"{o:,.0f} a day"),
                         ("population 2022", f"{p:,.0f}"),
                         ("distance from the city limit", f"{k:,.0f} km")],
                     tag="borders Sorocaba" if a else None, tag_color="#8a3714")
            for n, i, o, p, k, a in zip(drawn["name"], drawn["in"], drawn["out"],
                                        drawn["pop_2022"], drawn["km"], drawn["adjacent"])]
    m.maps.choropleth(drawn, "total", DENSITY_RAMP, tips, "Municipalities, by commuters",
                      "Commuters exchanged a day", "quintiles &middot; both directions, 2022 terms"
                      "<br>municipalities exchanging under 50 are not drawn",
                      "Commuting to and from Sorocaba",
                      [f"{by_municipio['in'].sum():,.0f} commute in, "
                       f"{by_municipio['out'].sum():,.0f} commute out",
                       f"Votorantim alone: {v_in:,.0f} in",
                       '<span style="color:#555;">2010 census sample, scaled by growth</span>'],
                      "3_commuting.html", borders=m.boundary, border_name="Sorocaba",
                      layer_panel=False, zoom=9)
    m.flows_out, m.flows_in, m.by_municipio = flows_out, flows_in, by_municipio
