# The data in this repository

`data/<city>/input_min/` holds the cities' inputs cut to what the model reads
(`tools/trim_inputs.py`). The originals come from their publishers, which keep their rights.
Where each Sorocaba file came from is in `data/sorocaba/input/SOURCES.md`.

| data | publisher | terms |
|---|---|---|
| **Sorocaba** | | |
| 2022 census sectors and their attributes (`derived/`, `sectors_*.gpkg.zip`, `municipalities.gpkg`, `municipality_centres.csv`) | IBGE, Censo Demográfico 2022 | public data of the Brazilian government; reuse with the source cited ("Fonte: IBGE") |
| 2010 census sample (`sample_2010/`, `ap_composition.txt`, `derived/areas_ponderacao_*`, the 2010-2022 crosswalk) | IBGE, Censo Demográfico 2010, microdados da amostra | as above |
| addresses (`8_addresses/CNEFE_*.zip`) | IBGE, CNEFE, Censo 2022 | as above |
| establishments and jobs (`7_reference/CEMPRE_*.csv`) | IBGE, SIDRA table 9528 (CEMPRE) | as above |
| municipalities (`7_reference/IBGE_cidades_municipios_SP.csv`) | IBGE Cidades | as above |
| traffic counts (`counts/`) | ARTESP, open data portal (dadosabertos.artesp.sp.gov.br) | open data of the State of São Paulo; reuse with the source cited |
| bus routes and stops (`osm_transit/`) | © OpenStreetMap contributors | Open Database License (ODbL) 1.0: credit OpenStreetMap, and share any adapted database under the ODbL |
| **Quito** | | |
| 2022 census sectors (`sectors.parquet`) | INEC Ecuador, Censo de Población y Vivienda 2022 | public data; reuse with the source cited |
| population projections (`03_Resultados_proyeccion2023_2035.xlsx`) | to be confirmed | to be confirmed |
| barrios (`barrios.parquet`), land-use plan (`land_use.parquet`), cadastre buildings (`buildings.parquet`) | Municipio del Distrito Metropolitano de Quito | **to be confirmed** before reuse |

The street networks the model downloads (`data/<city>/cache/`, not in the repository) are
© OpenStreetMap contributors, under the ODbL.
