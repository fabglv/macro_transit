# Provenance — where every file came from

Download origin for each file, so the dataset can be rebuilt or repeated for another city.

**Verification status** is marked per entry:
- ✅ **verified** — I fetched this directory listing and confirmed the file is there under this exact name
- ◻ **reported** — path taken from the download page as shown to me, not independently confirmed
- ⚠ **reconstructed** — inferred from filename and content; check before relying on it

Host for all FTP paths: `https://ftp.ibge.gov.br/`

---

## 2_geometry/

| File | Origin |
|---|---|
| `SP_setores_CD2022_com_atributos.gpkg` | ✅ `Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/malha_com_atributos/` |

Note this is **not** from the Geociências "Malha Censitária" page. The plain mesh there has
29 fields; the one under `Agregados_por_Setores_Censitarios/malha_com_atributos/` has 36,
including `V0001`–`V0007`. That distinction cost a day — see DATA_INVENTORY.md.

The shapefile twin in `9_archives/` came from the same directory.

---

## 3_aggregates/ — thematic sector tables

✅ Parent: `Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/`
with sibling directories `Agregados_por_Setor` (csv and xlsx variants),
`Agregados_por_Bairro`, `Agregados_por_Distrito`, `Agregados_por_Municipio`,
`Agregados_por_SubDistrito`.

Six archives taken from the sector-level CSV directory:

```
Agregados_por_setores_alfabetizacao_BR.zip
Agregados_por_setores_caracteristicas_domicilio1_BR.zip
Agregados_por_setores_caracteristicas_domicilio2_BR_20250417.zip
Agregados_por_setores_caracteristicas_domicilio3_BR_20250417.zip
Agregados_por_setores_cor_ou_raca_BR.zip
Agregados_por_setores_demografia_BR.zip
```

Not taken: `..._basico_BR_20260520.zip` (payload is only `V0001`–`V0007`, already in the mesh),
`..._parentesco_BR.zip`, `..._obitos_BR.zip`, and the four indígenas/quilombolas archives
(zero such sectors in Sorocaba).

---

## 1_documentation/

| File | Origin |
|---|---|
| `dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx` | ✅ `Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/` (116 K, dated 2026-05-12) |
| `Dicionario_de_dados_malha_agregados.xlsx` | ◻ Geociências, "Acesso ao produto — 2022 Malha Censitária" |
| `Leia_me_Area_efetivamente_ocupada.pdf` | ◻ same page, "Área territorial efetivamente domiciliada" section |
| `Leia_me_Comparabilidade_2010_2022.pdf` | ◻ same page, "Comparabilidade" section |

---

## 4_density/ · 5_comparability/ · 6_descriptions/

◻ All three from the Geociências page
**"Acesso ao produto — 2022 Malha Censitária"**:

| File | Item on that page |
|---|---|
| `Area_efetivamente_domiciliada_e_densidade_ajustada_dos_Setores_Censitarios.xlsx` | "Área territorial efetivamente domiciliada e densidade demográfica ajustada" |
| `Historico_formacao_Setores_Censitarios_2010_2022.xlsx` | "Histórico de formação dos Setores Censitários (2010-2022)" |
| `Descrição_SP.xlsx` | "Descrições de limites dos Setores Censitários", updated 10/10/2025 |

The descriptions download is a single zip of 27 state files — see `9_archives/`.

---

## 7_reference/

| File | Origin |
|---|---|
| `CEMPRE_9528_SOROCABA.csv` | ✅ SIDRA API, pulled here — see query below |
| `IBGE_cidades_panorama_Sorocaba.csv` | ⚠ IBGE Cidades panorama export for Sorocaba. Downloaded with a hash filename; renamed. |
| `IBGE_cidades_municipios_SP.csv` | ⚠ IBGE Cidades, all SP municipalities. Same origin, same renaming. |

CEMPRE is a **query, not a download**:

```
metadata  https://servicodados.ibge.gov.br/api/v3/agregados/9528/metadados
values    https://apisidra.ibge.gov.br/values/t/9528/n6/3552205/p/last/v/706,707,708,662/c12762/all
```

`t`=table, `n6`=município level, then the code, `p`=period, `v`=variables
(706 local units, 707 total employed, 708 salaried, 662 wages), `c12762`=CNAE 2.0.
Responses are **gzipped**; row `[0]` is a header mapping `D1`–`D4` to dimension names.

---

## 9_archives/

| Archive | Origin |
|---|---|
| `Descricoes_limites_Setores_Censitarios_20251010.zip` | ◻ Geociências malha page — 27 state files, only SP unpacked |
| `BR_bairros_CD2022.zip` | ◻ same page, "Arquivo geoespacial de Bairros – Brasil" |
| `BR_subdistritos_CD2022.zip` | ◻ same page, "Malha de Subdistritos – Brasil" |
| `SP_setores_CD2022_com_atributos.zip` | ✅ `.../Agregados_por_Setores_Censitarios/malha_com_atributos/` — shapefile twin of the gpkg |
| `SP1.zip` | ✅ `Censos/Censo_Demografico_2010/Resultados_Gerais_da_Amostra/Microdados/SP1.zip` (130 M) |
| `SP2_RM.zip` | ✅ `Censos/Censo_Demografico_2010/Resultados_Gerais_da_Amostra/Microdados/SP2_RM.zip` (64 M) |

### Downloaded 2026-09-29 — and it mattered

✅ `Censos/Censo_Demografico_2010/Resultados_Gerais_da_Amostra/Microdados/Documentacao.zip` — 10 MB

Now held as `9_archives/Documentacao_microdados_2010.zip`, unpacked to
`1_documentation/microdados_2010/`. It contains far more than the SP1 layout: also the
**composition of the áreas de ponderação**, the migration/commuting municipality code
tables, occupation and CNAE code tables, and the 2010 questionnaire.

---

## 0_inbox/ — CNEFE and MUNIC

All CNEFE paths ✅ verified this session.

```
Cadastro_Nacional_de_Enderecos_para_Fins_Estatisticos/Censo_Demografico_2022/
├── Arquivos_CNEFE/
│   ├── CSV/
│   │   ├── Dicionario_CNEFE_Censo_2022.xls            13 K
│   │   └── Municipio/35_SP/3552205_SOROCABA.zip      8.0 M   <- the one to keep
│   └── GeoJSON/
│       ├── Dicionario_CNEFE_Censo_2022_GeoJSON.xls    23 K
│       └── Municipio_20240910/qg_810_endereco_Munic3552205.json.zip   10 M
├── Coordenadas_enderecos/
│   ├── Dicionario_Coordenadas_Censo2022.xls          9.0 K
│   └── Municipio/35_SP/3552205.zip                   1.8 M   <- redundant
├── Agregados_por_CEP/      (not taken — CEP does not align with sectors)
└── Trajetos_dos_Recenseadores/  (not taken — enumerator routes, not travel demand)
```

The CSV has 34 columns including `LATITUDE`/`LONGITUDE`; the GeoJSON has 14 and the
Coordenadas file 6 with no sector code. The CSV supersedes both.

MUNIC — ◻ from `Perfil_Municipios`, 2024 edition:

```
Base_de_Dados/Base_MUNIC_2024_20251107.xlsx
Tabelas_de_Resultados/xlsx/05_Transporte.xlsx
Tabelas_de_Resultados/xlsx/03_Governanca.xlsx
Indice_de_Tabelas.pdf
```

---

## Repeating this for another city

One parameter drives everything — the 7-digit municipality code:

| Source | Substitution |
|---|---|
| SIDRA | `n6/<CODE>` |
| BR-wide FTP files | filter rows whose geocode starts with `<CODE>` |
| CNEFE | `Municipio/<UF#>_<UF>/<CODE>_<NAME>.zip` |
| Mesh | `<UF>_setores_CD2022_com_atributos.gpkg`, from the first 2 digits |

**Already reusable as-is** (Brazil-wide, no re-download): everything in `3_aggregates/`,
`4_density/`, `5_comparability/`, plus the bairros and subdistritos archives.

**Needs one download per city**: the CNEFE municipality file (~8 MB), and the UF mesh only
if the city is outside São Paulo.

**No download at all**: anything municipal-level, via SIDRA.

### A caution learned here

The FTP readme for `Economia_Cadastro_de_Empresas` states results are published for
"Brasil, unidade da federação e município **das capitais**". That is true of that FTP
bundle and **false of CEMPRE as a product** — SIDRA table 9528 serves any municipality.

IBGE's FTP dumps and its SIDRA tables are different distributions of the same statistics,
with different geographic coverage. When an FTP readme says a product does not reach your
level, check the SIDRA catalogue (`https://servicodados.ibge.gov.br/api/v3/agregados`,
70 researches / 9,336 tables) before believing it.

The reverse also holds: SIDRA census tables stop at **município**. Sector-level data exists
only as the FTP `Agregados_por_Setores_Censitarios` files.


---

## Added 2026-09-29

| File | Origin | Status |
|---|---|---|
| `8_addresses/CNEFE_3552205_SOROCABA.zip` | `Cadastro_Nacional_de_Enderecos_para_Fins_Estatisticos/Censo_Demografico_2022/Arquivos_CNEFE/CSV/Municipio/35_SP/3552205_SOROCABA.zip` | verified |
| `1_documentation/Dicionario_CNEFE_Censo_2022.xls` | `.../Arquivos_CNEFE/CSV/Dicionario_CNEFE_Censo_2022.xls` | verified |
| `9_archives/Documentacao_microdados_2010.zip` | `Censos/Censo_Demografico_2010/Resultados_Gerais_da_Amostra/Microdados/Documentacao.zip` | verified |
| `1_documentation/microdados_2010/` | unpacked from the above | derived |
| `7_reference/munic_2024/*` | `Perfil_Municipios`, 2024 edition | reported |
| `7_reference/CEMPRE_9528_SOROCABA.csv` | SIDRA API query, see above | verified |

Discarded after comparison, all verified redundant:
`Arquivos_CNEFE/GeoJSON/...` (14 properties vs the CSV's 34),
`Coordenadas_enderecos/...` (6 fields, no sector code), and both of their dictionaries.

### Note on the 2010 documentation archive

Unpacking needs two encoding fixes. Filenames are stored in **cp850**, which Python's
zipfile decodes as cp437 — recover with `name.encode('cp437').decode('cp850')`. And
`Composicao_das_Areas_de_Ponderacao.txt` is **UTF-16**, not Latin-1 or UTF-8.

## Added 2026-10-05

| File | Origin | Status |
|---|---|---|
| `9_archives/SP2_RM.zip` | `Censos/Censo_Demografico_2010/Resultados_Gerais_da_Amostra/Microdados/SP2_RM.zip` | verified |

`SP1.zip` covers São Paulo state **outside the metropolitan region** (606 municipalities), not
just outside the capital. `SP2_RM.zip` is the other half: the 39 municipalities of the Região
Metropolitana de São Paulo, capital included, in the same layout. The model reads both, so that
commuters from Osasco, Barueri, Cotia, the capital and the rest of the region into Sorocaba are
seen.

## 10_traffic_counts/ — added 2026-10-05

Not IBGE: ARTESP open data (`dadosabertos.artesp.sp.gov.br`). The model does not read these as
inputs; section F of the notebook checks the model against them.

| File | Origin | Status |
|---|---|---|
| `artesp/volume_trafego_hora/VOLUME_PEDAGIADO-L*-HORARIO-2026.csv` | dataset *Volume de Tráfego*, hourly toll volumes 2026, one file per concession lot | as downloaded |
| `artesp/volume_diario/VOLUME_PEDAGIADO-L*-DIARIO-2026.csv` | the same dataset, daily | as downloaded |
| `artesp/contagem_sat/contagem_sat_dia_2026.csv` | dataset *Contagem SAT*, daily counts at the automatic stations, all lots: `dataset/63017848-7c66-4a35-9c9a-ad4ef855b9c2/resource/6c7b98fb-822d-45d1-b230-2b9791bab265/download/contagem_sat_dia_2026.csv` | as downloaded |
| `9_archives/volume_diario.rar`, `9_archives/volume_trafego_hora.rar` | the archives the two toll folders were unpacked from | as downloaded |

The toll files name gantries and plazas but give no location. The km of the Rota Sorocabana
(lot L33) gantries on the SP-270 come from the concessionaire's published list: charging at
km 48+980, 82+600 and 111+850, counting only at 37, 58, 72, 95 and 101 (Sem Parar, *Free Flow
Raposo Tavares*; Portal Olá, 2025). They are set in the notebook (F1), not in these files.
