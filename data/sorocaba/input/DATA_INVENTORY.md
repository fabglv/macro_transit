# Data inventory — what each file is, and how it was used

Every file in this folder, with its origin, contents, and the role it played in building
the Sorocaba dataset. Sizes and dimensions below were read off the files themselves.

Municipality code **3552205**. All files key on the 15-digit sector geocode (`CD_SETOR`,
or `CD_setor` in the thematic CSVs).

---

## 1_documentation/ — read these before trusting any number

### `Dicionario_de_dados_malha_agregados.xlsx` — 0.03 MB
Sheets: `Setor` (57x3), `Distrito` (15x2), `Subdistrito` (17x2), `Bairro` (19x2).
Field definitions for the census-sector mesh, plus code lists for `CD_SIT` (situação, 1–9)
and `CD_TIPO` (tipo, 0–9).

**Used for:** decoding `CD_SIT`/`CD_TIPO` into readable labels. Also for a diagnostic that
mattered — this dictionary describes **36** fields, but the mesh originally downloaded had
only **29**. The nine missing ones (`V0001`–`V0007` plus two naming variants) revealed that
the correct product was *malha com atributos*, not the plain mesh. That one comparison
redirected the whole download.

### `dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx` — 0.12 MB
Sheets: `Dicionário Básico` (10x3), `Siglas Básico` (8x2), `Dicionário não PCT` (1412x4),
`Dicionário PCT - Indígenas` (1030x4), `Dicionário PCT - Quilombolas` (952x4).

**Used for three decisions:**
- `Dicionário Básico` has only 10 rows — the *básico* aggregate is nothing but `V0001`–`V0007`.
  Since the mesh already carries those joined to geometry, the 15 MB `basico` archive was
  redundant and was deleted.
- Decoding the 36 demografia variables (`V01006`–`V01041`).
- Searching all 1,412 non-PCT variables for `rendimento`, `automóvel`, `veículo`,
  `deslocamento`, `trabalho`. **None exist.** The only `carro` matches are *carro-pipa*
  (water trucks) and dwellings improvised inside vehicles. This establishes that income,
  car ownership and journey-to-work are absent from Census 2022.

### `Leia_me_Area_efetivamente_ocupada.pdf` — 0.7 MB, 4 pages
Methodology for the inhabited-area file, plus its full field table.

**Used to explain three things:** why 40 Sorocaba sectors have no inhabited-area value (the
product is published *"apenas... em situações territoriais urbanas"*); that the density
column is *people in occupied private households* ÷ area, **not** total population ÷ area;
and that IBGE computes areas in an Albers equal-area projection, not UTM.

### `Leia_me_Comparabilidade_2010_2022.pdf` — 0.4 MB, 13 pages
Rules governing sector maintenance, subdivision and aggregation between censuses.

**Used for:** decoding the `FRM` formation codes (Quadros 2 and 3) — `111` maintained,
`161` maintained with geometry adjustment, `221`/`222` quantitative subdivision,
`241`/`242` territorial-structure subdivision, `371`/`372` aggregation with dwellings,
`391` aggregation without. It also documents the recommended dasimetric approach using
CNEFE block faces, which is the method to use if 2010 and 2022 data must be reconciled.

---

## 2_geometry/ — the spatial base

### `SP_setores_CD2022_com_atributos.gpkg` — 182.1 MB
**103,620 features, 36 fields, EPSG:4674 (SIRGAS 2000).** All São Paulo census sectors.
Carries the full IBGE hierarchy (região → UF → município → distrito → subdistrito → bairro),
the special-area codes (`CD_NU` núcleo urbano, `CD_FCU` favela/comunidade urbana,
`CD_AGLOM`), the regional groupings (`CD_RGINT`, `CD_RGI`, `CD_CONCURB`), and `V0001`–`V0007`.

**Used as the primary source.** Filtering `CD_MUN='3552205'` yields Sorocaba's **1,148
polygons**, all geometries valid, total 450.2 km². This is the file that closed the rural
gap: population went from 718,444 (1,108 urban sectors) to **723,682** (all 1,148), the
40 rural sectors contributing 5,238 people.

> Field-name casing differs: the V-variables are **lowercase** (`v0001`) in the GeoPackage
> but uppercase in the dictionary and the CSVs.

---

## 3_aggregates/ — thematic census tables, all Brazil

Six archives, each a single `;`-delimited CSV: quoted, UTF-8, **no BOM, CRLF** endings.
Each covers **458,772** sectors nationally. About 2.3 GB uncompressed in total, which is
why they are kept zipped and read by streaming.

| Archive | Zip | Uncompressed | Variables |
|---|---:|---:|---:|
| `..._alfabetizacao_BR.zip` | 142.1 MB | 735 MB | 362 |
| `..._caracteristicas_domicilio1_BR.zip` | 24.2 MB | 186 MB | 89 |
| `..._caracteristicas_domicilio2_BR_20250417.zip` | 84.0 MB | 784 MB | 406 |
| `..._caracteristicas_domicilio3_BR_20250417.zip` | 52.7 MB | 305 MB | 148 |
| `..._cor_ou_raca_BR.zip` | 43.8 MB | 201 MB | 95 |
| `..._demografia_BR.zip` | 22.6 MB | 89 MB | 36 |

The `_20250417` suffix marks IBGE revisions; undated twins of those two were discarded as
superseded.

**Used to produce `derived/agregados_sorocaba/`.** Each archive was streamed and filtered to
rows beginning `"3552205`, as a pure byte operation — no decode/encode round trip — so the
extracts are byte-identical to the corresponding source lines. Verified per file by MD5
against a freshly recomputed expectation.

Demografia is the most directly useful: `V01006` total residents, `V01007`/`V01008`
male/female, then 11 age bands by sex and 11 combined (`V01031`–`V01041`, 0–4 through 70+).

---

## 4_density/

### `Area_efetivamente_domiciliada_e_densidade_ajustada_dos_Setores_Censitarios.xlsx` — 40.0 MB
Single sheet, **354,966 x 14**. Per sector: `V0001`–`V0007`, `AREA_DOMICILIADA_KM2`,
`AREA_KM2`, and two density columns. Built from a 250 m grid over the coordinates of
dwellings visited during the census.

**Used for** Sorocaba's **1,108 urban** sectors. It establishes that only **151.9 km² of
450.2 km² (34%)** of the municipality is actually inhabited, and that density is **1,607
inhab/km²** municipality-wide versus **4,731 inhab/km²** on inhabited area — the latter over
the 1,108 sectors that have such a value, using their own population of 718,444. It was also the first
source of population, before the attributed mesh superseded it.

> Mixed decimal marks within a single row: `V0005` arrives as `2,6` while
> `AREA_DOMICILIADA_KM2` is `0.105864...`. Both need normalizing.

---

## 5_comparability/

### `Historico_formacao_Setores_Censitarios_2010_2022.xlsx` — 83.7 MB
Single sheet `Exportar Planilha`, **489,736 x 43**. Every Brazilian sector tracked year by
year, 2022 back to 2010, with a geocode, formation code and situação/tipo per year.

**Used to produce `derived/crosswalk_setores_SOROCABA_2010_2022.csv`** — 1,180 rows covering
Sorocaba's 1,148 sectors (the extra 32 are sectors with more than one 2010 parent, i.e.
merges), descending from 687 distinct 2010 sectors, 684 of them Sorocaba's and 3 from
annexed neighbouring territory.

Its headline finding: **1,074 of 1,148 sectors are unchanged since 2010**, so intercensal
comparison in Sorocaba is unusually safe. Scanning the file takes about 80 seconds.

---

## 6_descriptions/

### `Descrição_SP.xlsx` — 11.4 MB
Sheet `Descrição`, **103,320 x 10** (103,319 sectors plus header). Textual perimeter
descriptions: a starting point, then a walk around the boundary naming each street, river
or railway. No geometry.

**Used as an independent cross-check.** Its 1,148 Sorocaba geocodes match the mesh exactly,
with no extras on either side — that is what confirms the sector list is right. Also the
source for rural settlement names (Lugarejo "Mato Dentro", Povoados "Inhayba II" and "III").

> This file has broken column widths — column H is declared 14,200 characters, which Excel
> renders about 32 screens wide, making the sheet look empty past column F. See
> `derived/Descrição_SP_corrigido.xlsx`.

---

## 7_reference/

### `IBGE_cidades_municipios_SP.csv` — 0.12 MB, 647 rows
All 645 São Paulo municipalities: code, demonym, mayor, area, 2022 population, density,
estimated population, HDI, GDP figures. HTML-entity encoded (`S&atilde;o Paulo`).

**Not yet used.** Relevant for a macrosimulation when external zones are needed —
neighbouring municipalities' population and density for trips crossing the boundary.

### `IBGE_cidades_panorama_Sorocaba.csv` — 0.003 MB, 26 rows
IBGE Cidades panorama export for Sorocaba: mayor, demonym, area 449.872 km², and
`POPCENSO 723.682 [2022]`.

**Used as external validation.** Its population figure matches the sum of `v0001` across the
1,148 sectors exactly. That also settled an earlier doubt: a remembered figure near 687,000
is an **intercensal estimate**, not the census count.

---

## 9_archives/ — originals, and the sources for other cities

| Archive | Zip | Uncompressed | Contents |
|---|---:|---:|---|
| `Descricoes_limites_...20251010.zip` | 45.6 MB | 56 MB | 27 files, one per state — **only SP is unpacked** |
| `BR_subdistritos_CD2022.zip` | 240.3 MB | 352 MB | shapefile, 11,307 subdistricts |
| `SP1.zip` | 136.6 MB | 1,456 MB | Censo 2010 sample microdata, SP outside the metropolitan region (606 municipalities) |
| `SP2_RM.zip` | 66.9 MB | 725 MB | the same for the 39 municipalities of the São Paulo metropolitan region, capital included |
| `SP_setores_CD2022_com_atributos.zip` | 86.6 MB | 370 MB | shapefile twin of `2_geometry/` |
| `BR_bairros_CD2022.zip` | 27.4 MB | 65 MB | shapefile, 17,575 neighbourhoods |
| `volume_trafego_hora.rar`, `volume_diario.rar` | 72.9 MB, 7.4 MB | 1.4 GB, 0.1 GB | ARTESP toll volumes 2026, unpacked into `10_traffic_counts/artesp/` |

**Why these are kept despite being useless for Sorocaba:** bairros has **zero** Sorocaba
features (IBGE mapped neighbourhoods for only 895 of 5,570 municipalities) and subdistritos
yields a single polygon covering the whole municipality — but both are national, so a
different city may well be subdivided by them.

`SP1.zip` was the source of `derived/areas_ponderacao_SOROCABA_2010.csv`. Its fixed-width
layout was decoded by position: UF 1–2, município 3–7, **área de ponderação 8–20**, control
21–28, sample weight 29–44 with 13 implied decimals. Applying those weights reproduced
Sorocaba's official 2010 population of 586,625 exactly, which is what validated the
decoding. **It remains, with `SP2_RM.zip`, the only source here containing income, car ownership and
journey-to-work** — none of which exist in Census 2022. Reading its remaining ~500
person-file columns would require IBGE's layout spreadsheet, which is not in this folder.

---

## 10_traffic_counts/ — ARTESP highway counts, 2026

What the model is checked against (notebook section F), not an input. Not IBGE.

### `artesp/volume_trafego_hora/` — 22 files, 1.4 GB, one per concession lot
Hourly toll volumes, January to August 2026. Columns `DATA, HORA, LOTE, PRACA, SENTIDO,
TIPO_CABINE, TIPO_PASSAGEM, TP_PAGAMENTO`, then one column per vehicle class and axle count
(`LEVE-EIXOS 2`, `MOTO-EIXOS 2`, `PESADO-EIXOS 2` ... `PESADO-EIXOS 51`). A plaza's traffic in an
hour is the sum over every cabin type, passage type (valid, exempt, evasion) and payment.
**L33 (Rota Sorocabana)** is the lot around Sorocaba: free-flow gantries 06–23 and the plazas
`ITU` (eastbound only) and `SOROCABA` (SP-075 km 13+325, southbound only). The files name each
gantry and its direction, not its location: see SOURCES.md.

### `artesp/volume_diario/` — 22 files, 0.1 GB
The same, by day (no `HORA`), to the end of August.

### `artesp/contagem_sat/contagem_sat_dia_2026.csv` — 26.7 MB
Daily counts at ARTESP's automatic stations (SAT), every lot. Columns `DATA, CONCESSIONARIA, RA,
RODOVIA, KM, COMPLEMENTO, SENTIDO, MARGINAL, QTD_MOTO, QTD_PASSEIO, QTD_COMERCIAL`; the position is
`KM` + `COMPLEMENTO` metres. Detectors are renumbered during the year — a station can appear at
km 101+000 and 101+005 — so neighbouring positions are one station. A few directions read a
fraction of the other (SP-270 km 94+800 eastbound), a detector fault rather than traffic.

---

## derived/ — produced here, regenerable, not original data

| File | Size | Shape |
|---|---:|---|
| `SOROCABA_setores_2022_completo.gpkg` | 1.8 MB | 1,148 features x 44 fields, EPSG:4674 |
| `SOROCABA_setores_2022_completo.csv` | 0.4 MB | same, attributes only |
| `setores_censitarios_SOROCABA_enriquecido.csv` | 0.6 MB | 1,148 x 14 |
| `crosswalk_setores_SOROCABA_2010_2022.csv` | 0.05 MB | 1,180 x 4 |
| `areas_ponderacao_SOROCABA_2010.csv` | 0.001 MB | 19 x 6 |
| `Descrição_SP_corrigido.xlsx` | 11.5 MB | 103,320 x 10 |
| `agregados_sorocaba/*.csv` | 5.9 MB | 6 files, 1,132 rows each |

**`SOROCABA_setores_2022_completo.gpkg`** is the main working file: geometry and the 36 mesh
fields, plus inhabited area and both densities from `4_density/`, plus `FRM_2022` and the
2010 geocode from `5_comparability/`, plus readable `SITUACAO_DESC` and `TIPO_DESC` labels
from `1_documentation/`.

**`setores_censitarios_SOROCABA_enriquecido.csv`** is the perimeter descriptions joined to
the situação/tipo classification and the 2010 geocode — the only derived file carrying the
boundary texts.

**`Descrição_SP_corrigido.xlsx`** repairs the column widths and freezes the header row.
Its `<sheetData>` block — all 39,154,676 bytes, every cell — is byte-for-byte identical to
the original, verified by hashing each part of both packages.

**`agregados_sorocaba/`** holds 1,132 rows per theme, not 1,148. The 16 absent sectors all
have **zero population** (vacant, 13 of them classed *baixo patamar domiciliar*), so IBGE
has nothing to tabulate for them. A join against the mesh will leave 16 null rows, correctly.

### Encoding difference worth knowing

The files in `agregados_sorocaba/` have **no BOM**, because they are byte-faithful copies of
IBGE's lines. The other derived CSVs **do** have a UTF-8 BOM, added deliberately so they open
correctly in Excel and LibreOffice by double-click. Read those with `utf-8-sig`.


---

## 8_addresses/ — CNEFE, address-level microdata

### `CNEFE_3552205_SOROCABA.zip` — 8.4 MB (60.4 MB CSV)
Every address in Sorocaba recorded by the 2022 census. **34 columns**, `;`-delimited, UTF-8.

Key fields: `COD_SETOR` (sector, with trailing letter), `COD_ESPECIE` (what the address is),
`DSC_ESTABELECIMENTO` (establishment name), `LATITUDE`/`LONGITUDE`, `CEP`, `NUM_QUADRA`,
`NUM_FACE`, and the street parsed into type / title / name / number.

**Not yet used.** Its purpose is trip attraction: counting non-residential espécies per
sector converts CEMPRE's municipal job total into a spatial distribution. It is also the
raw material behind `AREA_DOMICILIADA_KM2`, and the input the comparability Leia-me
recommends for dasimetric 2010-2022 redistribution.

> Two alternates were downloaded and discarded after comparison. The GeoJSON version has
> only 14 properties and is 148 MB uncompressed; the Coordenadas file has 6 fields and no
> sector code, so it cannot be joined to anything. The CSV is a strict superset of both and
> already carries coordinates.

---

## 7_reference/munic_2024/ — MUNIC, the municipal government survey

| File | Size | Contents |
|---|---:|---|
| `Base_MUNIC_2024_20251107.xlsx` | 25 MB | Complete microdata, every municipality, every question |
| `05_Transporte.xlsx` | 0.1 MB | Transport module, pre-tabulated |
| `03_Governanca.xlsx` | 0.1 MB | Planning instruments — master plan, land-use law |
| `Indice_de_Tabelas.pdf` | 0.1 MB | Table index |

**Not yet used.** MUNIC surveys municipal *government*, not travel: what the administration
has and does. It will not feed numbers into a model. Its value is as a pointer — whether
Sorocaba has a Plano de Mobilidade Urbana (which typically contains an OD survey, modal
split and screenline counts), and which body manages transport and therefore holds the
counts and ticketing data.

### `CEMPRE_9528_SOROCABA.csv` — 4,268 records
Pulled from the SIDRA API, not downloaded. Local units, persons employed, salaried staff
and wages by CNAE, for 2024. Totals: **52,526 local units, 301,480 jobs, 236,866 salaried**.

Contains all 1,067 CNAE levels — sections, divisions, groups and classes together. Summing
them double-counts; filter to the 21 sections using `nivel == 1` from the table metadata.

---

## 1_documentation/microdados_2010/ — unpacked from Documentacao.zip

47 files. This closes the gap that DATA_INVENTORY previously recorded as blocking.

### `Layout/Layout_microdados_Amostra.xls` (and `.ods`)
Four sheets — `DOMI`, `PESS`, `EMIG`, `MORT` — matching SP1's four files. Gives every
variable's name, start and end position, and category codes.

It confirms the field positions derived by inspection before it arrived: V0001 at 1-2,
V0002 at 3-7, V0011 area de ponderacao at 8-20, V0300 at 21-28, V0010 sample weight at
29-44 with 13 implied decimals.

The variables that matter for a macrosimulation:

| Variable | Position | Meaning |
|---|---|---|
| `V0222` | 103 (DOMI) | **Automóvel para uso particular** |
| `V0221` | 102 (DOMI) | Motocicleta para uso particular |
| `V0213`-`V0220` | 94-101 (DOMI) | Radio, TV, washer, fridge, mobile, landline, PC, internet |
| `V5070` | 406-413 (PESS) | **Rendimento familiar per capita** |
| `V5080` | 414-422 (PESS) | Same, in minimum wages |
| `V0651` / `V6521` | 212 / 232-237 | Earnings, main and other jobs |
| `V0660` | 328 (PESS) | **Where the person works** (own dwelling, this municipality, elsewhere) |
| `V6604` | 336-342 (PESS) | **Municipality of work — code** |
| `V6602` | 329-335 (PESS) | State of work — code |
| `V0662` | 351 (PESS) | **Commute time, home to work** |
| `V0661` | 350 (PESS) | Returns home from work daily |
| `V0636` | 168 (PESS) | Municipality where studying |

`V0011` (weighting area of residence) paired with `V6604` (municipality of work) is an
origin-destination relation, weighted — for work and study trips. Resolution is weighting
area to municipality, not zone to zone.

### `Areas_de_Ponderacao/Composicao_das_Areas_de_Ponderacao.txt` — 19 MB
**UTF-16 encoded**, tab-delimited, two columns: area de ponderacao, setor. 310,120 rows
nationally.

Sorocaba: **19 weighting areas composed of 678 sectors (2010)**, from 27 to 60 sectors each.
Chained through `derived/crosswalk_setores_SOROCABA_2010_2022.csv` this maps the weighting
areas onto 2022 geometry — so the 19 zones become mappable without any further download.

Note 678 here against 684 Sorocaba 2010 sectors in the crosswalk: six sectors are not
assigned to a weighting area. A 0.9% difference, worth checking before relying on totals.

### `Anexos_Auxiliares/` — the code tables those variables reference
`Migracao_e_deslocamento_Municipios.xls` decodes `V6604` and `V6254`;
`Ocupacao_COD_2010.xls` and `Atividade_CNAE_DOM_2.0_2010.xls` decode occupation and
activity. `Instrumentos_de_Coleta/` holds the 2010 questionnaire itself.

> `xlrd` is not installed, so the `.xls` files are not readable by script. Every one has an
> `.ods` twin, which is a zip of XML and readable without extra libraries.


### Format pruning, 2026-09-29

IBGE ships most of the 2010 documentation in two or three formats. 22 duplicate-format
files were dropped, keeping one per document, chosen for usability rather than size:

| Preference | Reason |
|---|---|
| `.txt` first | plain, streamable, no parsing layer |
| then `.ods` | a zip of XML, readable with the standard library — `xlrd` is not installed, so `.xls` cannot be read by script here |
| then `.pdf` | portable and searchable, unlike `.doc` |

25 files remain, 25.1 MB. Freed 11.9 MB.

One deliberate exception: `Composicao_das_Areas_de_Ponderacao` was kept as the **18.8 MB
`.txt`** rather than its 2.4 MB `.ods`. For a 310,120-row lookup, tab-delimited text that
streams beats a zipped spreadsheet that must be parsed whole. That choice costs ~16 MB and
is why pruning freed 11.9 MB rather than the 28.1 MB a size-first rule would have.

Nothing is unrecoverable — all 47 original files remain in
`9_archives/Documentacao_microdados_2010.zip`.

### Two extraction traps in that archive

Filenames are stored in **cp850**, which Python's zipfile decodes as cp437 — recover with
`name.encode('cp437').decode('cp850')`.

More dangerous: the archive holds four files whose names differ only by case and accent
(`Migração e Deslocamento_Paises estrangeiros` vs `Migração e deslocamento_Países
estrangeiros`, each as `.ods` and `.xls`). ASCII-folding those names makes them collide on
a case-insensitive filesystem, and two files are silently overwritten with no error. They
are kept here as `Migracao_e_deslocamento_Paises.*` and `..._Paises_acentuado.*`.
