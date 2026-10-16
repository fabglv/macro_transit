# Sorocaba — IBGE territorial and statistical data

Municipality **Sorocaba/SP**, IBGE code **3552205**.
1,148 census sectors (*setores censitários*), one district `355220505`, one subdistrict.
Population **723,682** — matches IBGE Cidades exactly. CRS throughout: SIRGAS 2000 / EPSG:4674.

## Layout — originals by function, derived kept apart

```
0_inbox/           staging area for new downloads (empty)
1_documentation/   dictionaries, Leia-me PDFs, 2010 microdata documentation
2_geometry/        census-sector mesh, with V0001-V0007 attached
3_aggregates/      thematic census aggregates (6 archives, 1,136 variables)
4_density/         effectively-inhabited area + adjusted density
5_comparability/   sector formation history 2010-2022
6_descriptions/    textual perimeter descriptions
7_reference/       municipality-level tables + MUNIC 2024 municipal survey
8_addresses/       CNEFE - every address with coordinates and type
9_archives/        original archives, incl. sources for other cities
10_traffic_counts/ ARTESP highway counts, 2026 - checked against, not read as inputs
derived/           OUTPUTS - produced from the above, not original data
```

Everything outside `derived/` is as-downloaded and unmodified: IBGE's, except
`10_traffic_counts/`, which is ARTESP's.

## Reusing this for another city

One parameter drives everything — the 7-digit municipality code:

| Source | Substitution |
|---|---|
| SIDRA API | `n6/<CODE>` |
| BR-wide FTP files | filter rows whose geocode starts with `<CODE>` |
| CNEFE | `Municipio/<UF#>_<UF>/<CODE>_<NAME>.zip` |
| Mesh | `<UF>_setores_CD2022_com_atributos.gpkg`, from the first 2 digits |

**Reusable as-is** (Brazil-wide): `3_aggregates/`, `4_density/`, `5_comparability/`, the
bairros and subdistritos archives, and the 2010 microdata documentation.
**One download per city**: the CNEFE municipality file (~8 MB), and the UF mesh only if the
city lies outside São Paulo.
**No download at all**: anything municipal-level, via SIDRA.

Full download paths are in [SOURCES.md](SOURCES.md); contents and usage in
[DATA_INVENTORY.md](DATA_INVENTORY.md).

## Verified figures

- 1,148 sectors — mesh and perimeter descriptions agree exactly
- Municipal area 450.2 km²; **effectively inhabited 151.9 km² (34%)**
- Population 723,682; households 307,419
- Density **1,607 inhab/km² raw** vs **4,731 inhab/km² on inhabited area** (the latter over the 1,108 sectors that have an inhabited-area value, using their own population of 718,444)
- 40 sectors are Favela/Comunidade Urbana, across 22 named communities
- 1,074 of 1,148 sectors unchanged since 2010 — intercensal comparison is safe
- **301,480 jobs** in 52,526 local units (CEMPRE 2024) — a jobs/population ratio of 0.42
- 19 áreas de ponderação (2010), composed of 678 2010 sectors

## Caveats

1. **Inhabited area and adjusted density cover the 1,108 urban sectors only** — published
   for urban situations by design. Population and households cover all 1,148; the 40 rural
   sectors hold 5,238 people.
2. The thematic aggregates cover **1,132** sectors. The 16 absent all have zero population
   (vacant, mostly *baixo patamar domiciliar*), so nothing is lost.
3. `DENSIDADE_..._DOMICILIADA_HAB_KM2` is *people in occupied private households* ÷ area,
   not total population ÷ area.
4. IBGE areas use an Albers equal-area projection, not UTM.
5. CNEFE's `COD_SETOR` carries a **trailing letter** (`355220505000300P`) absent from the
   mesh's `CD_SETOR`. Strip it before joining or you match zero rows.
6. The original `Descrição_SP.xlsx` has invalid column widths. Use
   `derived/Descrição_SP_corrigido.xlsx` — `<sheetData>` byte-identical to the original.
7. The thematic CSVs are `;`-delimited, quoted, UTF-8, no BOM, CRLF. Decimal marks are
   inconsistent within IBGE's own files — comma in some columns, dot in others.

## State of the macrosimulation inputs

| Need | Status |
|---|---|
| Zone system | 1,148 census sectors, with geometry |
| Trip production — household size, age, children | Census 2022 aggregates |
| Trip attraction — magnitude | CEMPRE 2024, 301,480 jobs by CNAE section |
| Trip attraction — spatial distribution | CNEFE establishment points, `8_addresses/` |
| Income, car ownership | Census **2010** sample, weighting-area level (19 zones) |
| Journey-to-work, commute time | Census **2010** sample — incl. destination municipality |
| Road network | **missing** — OpenStreetMap |
| OD survey for calibration | **missing** — check the municipal mobility plan |

Census 2022 used a short-form questionnaire and has **no** income, car ownership or
commuting. The 2010 sample has all three; `9_archives/SP1.zip` (the state outside the São Paulo
metropolitan region) and `9_archives/SP2_RM.zip` (the region itself) plus the layout in
`1_documentation/microdados_2010/Layout/` makes it readable. Resolution there is
weighting area (19 zones), not sector.
