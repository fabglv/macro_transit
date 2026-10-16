"""The cities' inputs cut to what the model reads, for the repository: data/<city>/input_min/.

    python tools/trim_inputs.py              # both cities
    python tools/trim_inputs.py sorocaba     # one

The originals - data/<city>/input/, as downloaded from their publishers (SOURCES.md) - are read
and left as they are; they are not in the repository (several files are over GitHub's 100 MB).
What is written here is what the cases read (cases/<city>/inputs.py, model.py): the same files
cut to the rows, columns and area the model uses, or a small table computed from one exactly as
the model would, so a run on them gives the same results as on the originals (the regression
tests check it).

Sorocaba
    derived/*, CNEFE, CEMPRE, the IBGE municipalities table, osm_transit/*   as they are
    ap_composition.txt        the áreas de ponderação's composition: Sorocaba's rows
    sample_2010/              the 2010 census sample: Sorocaba's households and persons, the people
                              of other municipalities who work or study in it, and every
                              municipality's 2010 population (its persons' weights summed)
    sectors_region.gpkg.zip   the state's 2022 sectors within MESH_REACH_KM of the city, zipped
    sectors_commuting.gpkg.zip  every sector of each municipality exchanging commuters with the
                              city within COMMUTING_KM, zipped
    municipality_centres.csv  every municipality's population-weighted centre, from all its sectors
    municipalities.gpkg       the state's municipalities, simplified: the commuting map's outlines
    counts/                   ARTESP's counts: the toll gantries and SAT stations the model reads,
                              the columns it reads
Quito
    population .xlsx          as it is
    barrios, sectors, land_use .parquet   every feature, exact; the columns the model reads
    buildings.parquet         the cadastre's buildings as a point inside each, with its footprint
"""
import csv
import io
import os
import shutil
import sys
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# The state's sectors kept around Sorocaba: REACH_KM (90 in its settings) may be raised to this.
# Further out the São Paulo metropolitan region's small sectors take the file past GitHub's 100 MB.
MESH_REACH_KM = 100
OUTLINE_M = 50                # the commuting map's municipality outlines, simplified this far
# The commuting municipalities kept whole: those whose centre is this close. A run counts commuters
# within the range of a daily commute (100 km for Sorocaba at DAILY_COMMUTE_PERCENTILE 0.99).
COMMUTING_KM = 200


def _copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def _mb(path):
    return os.path.getsize(path) / 1e6


def _zipped(frame, gpkg):
    """`frame` written as a GeoPackage inside gpkg + ".zip" - the case unzips it once into the
    city's cache: read inside the zip it takes minutes."""
    frame.to_file(gpkg, driver="GPKG")
    with zipfile.ZipFile(gpkg + ".zip", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(gpkg, os.path.basename(gpkg))
    os.remove(gpkg)


def sorocaba():
    from cases.sorocaba import counts
    from cases.sorocaba.inputs import MUNICIPIO, MUNICIPIO_2010
    src = os.path.join(ROOT, "data", "sorocaba", "input")
    dst = os.path.join(ROOT, "data", "sorocaba", "input_min")
    os.makedirs(dst, exist_ok=True)

    for rel in ("derived/SOROCABA_setores_2022_completo.gpkg",
                "derived/crosswalk_setores_SOROCABA_2010_2022.csv",
                "derived/areas_ponderacao_SOROCABA_2010.csv",
                "8_addresses/CNEFE_3552205_SOROCABA.zip", "7_reference/CEMPRE_9528_SOROCABA.csv",
                "7_reference/IBGE_cidades_municipios_SP.csv"):
        _copy(os.path.join(src, rel), os.path.join(dst, rel))
    for name in os.listdir(os.path.join(src, "osm_transit")):
        _copy(os.path.join(src, "osm_transit", name), os.path.join(dst, "osm_transit", name))

    # The composition of the áreas de ponderação: Sorocaba's, in the file's own format.
    comp = os.path.join(src, "1_documentation", "microdados_2010", "Areas_de_Ponderacao",
                        "Composicao_das_Areas_de_Ponderacao.txt")
    with open(comp, encoding="utf-16") as f:
        lines = f.read().splitlines()
    with open(os.path.join(dst, "ap_composition.txt"), "w", encoding="utf-16", newline="\n") as f:
        f.write("\n".join([lines[0]] + [l for l in lines[1:] if l.startswith(MUNICIPIO)]) + "\n")

    # The 2010 sample: what inputs.sample_2010 keeps of it, its fixed-width fields as text.
    out = os.path.join(dst, "sample_2010")
    os.makedirs(out, exist_ok=True)
    sp1, rm = os.path.join(src, "9_archives", "SP1.zip"), os.path.join(src, "9_archives", "SP2_RM.zip")
    with zipfile.ZipFile(sp1) as z, \
            io.TextIOWrapper(z.open("SP1/Amostra_Domicilios_35_outras.txt"), encoding="latin-1") as f, \
            open(os.path.join(out, "households.csv"), "w", newline="", encoding="utf-8") as o:
        w = csv.writer(o)
        w.writerow(["ap", "weight", "car", "moto"])
        for line in f:
            if line[2:7] == MUNICIPIO_2010:
                w.writerow([line[7:20], line[28:44], line[102], line[101]])
    pop, rmsp = {}, set()
    with open(os.path.join(out, "persons.csv"), "w", newline="", encoding="utf-8") as po, \
            open(os.path.join(out, "commuters_in.csv"), "w", newline="", encoding="utf-8") as co:
        persons, commuters = csv.writer(po), csv.writer(co)
        persons.writerow(["ap", "weight", "income", "work_where", "work_mun", "work_daily",
                          "work_time", "study_where", "study_mun", "age"])
        commuters.writerow(["origin", "weight", "works", "work_daily", "studies", "age"])
        for zipped, member in ((sp1, "SP1/Amostra_Pessoas_35_outras.txt"),
                               (rm, "SP2-RM/Amostra_Pessoas_35_RMSP.txt")):
            with zipfile.ZipFile(zipped) as z, \
                    io.TextIOWrapper(z.open(member), encoding="latin-1") as f:
                for line in f:
                    mun = line[2:7]
                    if zipped == rm:
                        rmsp.add("35" + mun)
                    # Summed in the file's order, as the model did: the same float.
                    pop[mun] = pop.get(mun, 0.0) + int(line[28:44]) / 1e13
                    works, studies = line[335:342], line[175:182]
                    if mun == MUNICIPIO_2010:
                        persons.writerow([line[7:20], line[28:44], line[405:413], line[327],
                                          line[335:342], line[349], line[350], line[167],
                                          line[175:182], line[61:64]])
                    elif works == MUNICIPIO or studies == MUNICIPIO:
                        commuters.writerow(["35" + mun, line[28:44], int(works == MUNICIPIO),
                                            line[349], int(studies == MUNICIPIO), line[61:64]])
    pd.DataFrame({"municipio": ["35" + k for k in pop], "pop_2010": [repr(v) for v in pop.values()],
                  "rmsp": [int("35" + k in rmsp) for k in pop]}).to_csv(
        os.path.join(out, "population.csv"), index=False)

    # The state's sector mesh: the region around the city, every municipality's centre, and the
    # municipalities' outlines.
    mesh_path = os.path.join(src, "2_geometry", "SP_setores_CD2022_com_atributos.gpkg")
    city = gpd.read_file(os.path.join(src, "derived", "SOROCABA_setores_2022_completo.gpkg"))
    metre_crs = city.estimate_utm_crs()                    # as inputs.read_sectors finds it
    limit = city.to_crs(metre_crs).union_all()
    box = gpd.GeoSeries([limit.buffer(MESH_REACH_KM * 1000)], crs=metre_crs).to_crs("EPSG:4674")
    region = gpd.read_file(mesh_path, bbox=tuple(box.total_bounds),
                           columns=["CD_MUN", "NM_MUN", "v0001"])
    # Zipped: the region is over 100 MB as a GeoPackage (the São Paulo metropolitan region's
    # sectors are within reach); the case unzips it once into the city's cache.
    _zipped(region, os.path.join(dst, "sectors_region.gpkg"))
    allsec = gpd.read_file(mesh_path, columns=["CD_MUN", "v0001"])
    p = allsec.to_crs(metre_crs).geometry.representative_point()
    weight = allsec["v0001"].fillna(0) + 1e-9
    centres = pd.DataFrame({"x": (p.x * weight).groupby(allsec["CD_MUN"]).sum()
                            / weight.groupby(allsec["CD_MUN"]).sum(),
                            "y": (p.y * weight).groupby(allsec["CD_MUN"]).sum()
                            / weight.groupby(allsec["CD_MUN"]).sum()})
    centres.index.name = "CD_MUN"
    centres.assign(crs=metre_crs.to_string()).to_csv(os.path.join(dst, "municipality_centres.csv"),
                                                     float_format="%.17g")
    # Every municipality exchanging commuters with the city - in the sample - within COMMUTING_KM,
    # whole: external.route_to_gateways reads whole those beyond the area a run reads (REACH_KM)
    # or cut by its edge, which depends on the run's settings.
    persons = pd.read_csv(os.path.join(out, "persons.csv"), dtype=str, keep_default_na=False)
    commuters = pd.read_csv(os.path.join(out, "commuters_in.csv"), dtype=str, keep_default_na=False)
    codes = (set(persons["work_mun"]) | set(persons["study_mun"]) | set(commuters["origin"])) - {MUNICIPIO}
    km = (np.hypot(centres["x"] - centres.loc[MUNICIPIO, "x"], centres["y"] - centres.loc[MUNICIPIO, "y"])
          / 1000)
    codes = {c for c in codes if c in km.index and km[c] <= COMMUTING_KM}
    _zipped(allsec[allsec["CD_MUN"].isin(codes)], os.path.join(dst, "sectors_commuting.gpkg"))
    outlines = allsec[["CD_MUN", "geometry"]].dissolve(by="CD_MUN").reset_index()
    outlines["geometry"] = outlines.to_crs(metre_crs).simplify(OUTLINE_M).to_crs(allsec.crs)
    outlines.to_file(os.path.join(dst, "municipalities.gpkg"), driver="GPKG")

    # ARTESP's counts: the rows counts.read_counts reads.
    cnt = os.path.join(src, "10_traffic_counts", "artesp")
    toll = pd.read_csv(os.path.join(cnt, "volume_trafego_hora", "VOLUME_PEDAGIADO-L33-HORARIO-2026.csv"),
                       low_memory=False, dtype=str)
    toll = toll[toll["PRACA"].isin(counts.GANTRY_AT)]
    toll = toll[["PRACA", "SENTIDO", "DATA", "HORA"] + [c for c in toll.columns if c.startswith("LEVE")]]
    os.makedirs(os.path.join(dst, "counts"), exist_ok=True)
    toll.to_csv(os.path.join(dst, "counts", "toll_hourly.csv"), index=False)
    sat = pd.read_csv(os.path.join(cnt, "contagem_sat", "contagem_sat_dia_2026.csv"), dtype=str)
    sat = sat[sat["CONCESSIONARIA"].str.startswith("L33") & sat["RODOVIA"].isin(counts.COUNT_ROADS)]
    sat.to_csv(os.path.join(dst, "counts", "sat_daily.csv"), index=False)
    return dst


def quito():
    src = os.path.join(ROOT, "data", "quito", "input")
    dst = os.path.join(ROOT, "data", "quito", "input_min")
    os.makedirs(dst, exist_ok=True)
    _copy(os.path.join(src, "03_Resultados_proyeccion2023_2035.xlsx"),
          os.path.join(dst, "03_Resultados_proyeccion2023_2035.xlsx"))
    barrios = gpd.read_file(os.path.join(src, "BARRIO_REF", "BARRIO_REF.shp"))
    barrios.to_parquet(os.path.join(dst, "barrios.parquet"), compression="zstd")
    gpd.read_file(os.path.join(src, "sector_censal_2022_inec_q", "sector_anonimizado_a.shp")).to_parquet(
        os.path.join(dst, "sectors.parquet"), compression="zstd")
    gpd.read_file(os.path.join(src, "ba003_uso_suelo_edificabilidad_a",
                               "ba003_uso_suelo_edificabilidad_a.shp"), columns=["uso_prin"]).to_parquet(
        os.path.join(dst, "land_use.parquet"), compression="zstd")
    # The buildings as the model reduces them (model.read_floor_area): the footprint's area and a
    # point inside it, in the metre CRS the barrios give.
    metre_crs = barrios.estimate_utm_crs()
    gdb = os.path.join(src, "BLOQUE_CONSTRUCTIVO", "BLOQUE_CONSTRUCTIVO", "catastro.gdb")
    parts = []
    for layer in ("UNIDAD_CONSTRUCTIVA", "BLOQUE_CONSTRUCTIVO"):
        frame = gpd.read_file(gdb, layer=layer, columns=["CODIGO", "PISOS"]).to_crs(metre_crs)
        parts.append(gpd.GeoDataFrame(
            {"source": layer, "CODIGO": frame["CODIGO"], "PISOS": frame["PISOS"],
             "ground_m2": frame.area}, geometry=frame.representative_point(), crs=metre_crs))
    pd.concat(parts, ignore_index=True).to_parquet(os.path.join(dst, "buildings.parquet"),
                                                   compression="zstd")
    return dst


def main():
    cities = sys.argv[1:] or ["sorocaba", "quito"]
    for city in cities:
        dst = {"sorocaba": sorocaba, "quito": quito}[city]()
        files = [os.path.join(d, f) for d, _, fs in os.walk(dst) for f in fs]
        print(f"{city}: {len(files)} files, {sum(map(_mb, files)):,.1f} MB in {dst}")
        for f in sorted(files, key=_mb, reverse=True)[:5]:
            print(f"  {_mb(f):6.1f} MB  {os.path.relpath(f, dst)}")


if __name__ == "__main__":
    main()
