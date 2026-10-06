---
name: reference-data
description: Answer spatial questions with the Geomermaids parquetry reference datasets, queried in place with DuckDB. Use when a question needs real geographic data rather than general knowledge, such as "what is the predominant land use in Hérault", "how many buildings in Eastern Massachusetts are in the 100-year floodplain", "which substations are within 5 km of this site", "which district is this point in", "how many km of high-voltage line cross this region", or when tagging a list of locations with country, admin unit, flood zone, land cover or nearby infrastructure. Covers administrative units worldwide (FAO GAUL 2024), power, telecom, oil and gas and water infrastructure worldwide (GMWID), US flood zones (FEMA NFHL), European land cover (CORINE 2018), and OpenStreetMap buildings, roads, POIs and more for the US, Canada and Mexico.
---

# Spatial questions with the parquetry reference datasets

Five open datasets sit on `https://parquetry.geomermaids.com` as GeoParquet.
You query them in place with DuckDB over HTTP range requests: no download
step, no account, no API. Most questions combine two or three of them: an
area from one, a phenomenon from another, the features to count from a
third.

Your job is to turn a plain-language question into a precise definition,
check that the data covers it, run the spatial query, and answer with the
number, the definition you used, the coverage, the data dates and the
credit.

## The datasets

| Dataset | Covers | Use it for | CRS | Layout |
|---|---|---|---|---|
| **GAUL 2024** (FAO) | World | Areas of interest: countries (L0), states and regions (L1), districts, counties, départements (L2). Point to admin unit. | CRS84 | `gaul/2024/country=<ISO3>/L0_derived,L1,L2.parquet`, or one world file per level |
| **GMWID** | World | Power lines, substations, plants, generators, towers; telecom cables and masts; pipelines, wells, platforms; water plants. | CRS84 | `gmwid/latest/<layer>.parquet`, one world file per layer |
| **FEMA NFHL** | US (50 states, PR) | Flood zones: 1% annual chance (100-year), 0.2% (500-year), floodway, base flood elevation. | **EPSG:4269** | `nfhl/latest/state=<XX>/<DFIRM_ID>.parquet`, one per county delivery, indexed by `nfhl/latest/counties.parquet` |
| **CORINE Land Cover 2018** | Europe (EEA39) | Land cover and land use composition, 44 classes, 25 ha minimum unit. | **EPSG:3035** | `clc/2018/country=<ISO2>/clc_2018.parquet`, or `clc/2018/clc_2018.parquet` |
| **OpenStreetMap** | US, Canada, Mexico | Buildings, roads, railways, POIs, amenities, places, land use, water, boundaries, power, public transport, updated daily. | CRS84 | `osm/latest/country=<CC>/state=<ISO 3166-2>/<theme>.parquet` |

Read `reference/datasets.md` for columns, value domains and licences
before writing a query against a dataset you have not used in this
session. Each collection also publishes an agent guide with its full
column list: `https://parquetry.geomermaids.com/<dataset>/catalog/<collection>/AGENTS.md`.

Outside these footprints, say so. Do not answer a land-cover question
about Texas from CORINE, or a building count for France from OSM here.

## Setup

```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
SET geometry_always_xy = true;  -- lon, lat order in ST_Transform, always
-- Only for globs (s3://parquetry/...): the anonymous S3 endpoint.
CREATE SECRET parquetry (TYPE s3, ENDPOINT 's3.geomermaids.com', URL_STYLE 'path',
                         KEY_ID '', SECRET '', REGION 'auto');
```

Use the DuckDB CLI or the `duckdb` Python package (1.5 or later). Plain
`https://` URLs need no secret. A glob needs the `s3://` form because HTTPS
cannot list files.

## Method

### 1. Pin the question down

Write the definitions before the SQL, and state them in the answer.

- **Place names become areas.** Find them in GAUL by name at the right
  level: "Hérault" is an L2 unit of France, "Massachusetts" an L1 unit of
  the USA. Names are in the local language with accents (`Hérault`,
  `Île-de-France`, `Quebec / Québec`): search with `ILIKE` and confirm the
  hit, its parent and its code.
- **Informal regions become explicit lists.** "Eastern Massachusetts",
  "the Gulf Coast", "Northern Italy" have no boundary in any dataset.
  Choose the member units, name them in the answer, and offer to redo it
  with another definition.
- **Vague terms become column filters.** "100-year flood" is the 1% annual
  chance flood: NFHL `risk = '1 percent flood zone'`, which holds FEMA's A
  and V zones (A, AE, AH, AO, VE...). "Impacted building" usually means a footprint that
  touches the zone: say whether you used the footprint or its centroid.
  "Predominant land use" can mean the largest CORINE class or the largest
  level-1 group: give both when they differ. "High-voltage" needs a
  threshold: say which (for example `voltage_kv >= 100`).

### 2. Check coverage before computing

- NFHL: list the deliveries for the area from `counties.parquet` (by
  `state` and `county`, or by bbox). Some US counties have no FEMA
  county-wide digital delivery and are absent: report them as unmapped,
  never as free of flood risk.
- CORINE: the country must be among the 48 in `clc/index.json`.
- OSM: the region must be one of the 98 in `reference/osm-regions.csv`.
  OSM completeness varies: building coverage is good in most US cities,
  thinner in rural areas.
- GMWID: worldwide, but it is OSM plus authoritative sources. Report
  `origin` when it matters.

### 3. Read only what the question needs

- Pick the smallest file set: a country file, a state file, the county
  deliveries. A whole-world or whole-Europe file is the last resort.
- Compute the extent of the area first, then filter every big file on its
  `bbox` column with that extent. Files are sorted along a Hilbert curve,
  so the bbox filter skips most row groups. Never call a geometry function
  on a file without a bbox filter.
- Select only the columns you need: the geometry column is most of the
  bytes.
- Materialize the filtered inputs into local tables (`CREATE TABLE ... AS`)
  before a spatial join. DuckDB then joins in memory with its R-tree
  spatial join instead of fetching remote pages repeatedly.
- Read per file, not per feature. To test 200 hospitals against flood
  zones, group them by FEMA delivery and read each delivery once, filtered
  on the extent of its hospitals and on `risk`. One remote query per
  feature costs a round trip each and turns minutes into a quarter hour.

### 4. Align the coordinate systems

- GAUL, GMWID and OSM are CRS84 lon/lat. NFHL is NAD83 lon/lat
  (EPSG:4269). The two differ by about 1 m in the US: cast the NFHL
  geometry with `geometry::GEOMETRY` to drop the CRS tag and join them
  directly.
- CORINE is EPSG:3035 (metres). Transform the area of interest into 3035
  with `ST_Transform(geom, 'OGC:CRS84', 'EPSG:3035')`. Never transform the
  CORINE polygons, which are many and large.
- Measure areas and distances in metres in a projected CRS: EPSG:3035 in
  Europe, the local UTM zone elsewhere (`EPSG:326<zone>` north,
  `EPSG:327<zone>` south, zone = floor((lon + 180) / 6) + 1), or use
  `ST_Area_Spheroid` and `ST_Distance_Sphere` on lon/lat.

### 5. Compute with a tested pattern

`reference/recipes.md` holds a tested query for each pattern, including the
two worked examples below. Adapt the closest one:

| Pattern | Example question |
|---|---|
| Point to context | "Which county and flood zone is this address in?" |
| Composition of an area | "Predominant land use in Hérault" |
| Overlay count | "Buildings in the 100-year floodplain in Eastern Massachusetts" |
| Length or area inside an area | "Km of power lines over 100 kV in Lombardy" |
| Nearest features | "Substations within 5 km of this site" |
| Tag a list of points | "Add country, district and flood zone to my 300 sites" |
| Per-unit statistics | "Wind farm capacity per French région" |

For a single location, `scripts/locate.py <lon> <lat>` returns the admin
units, flood zone, land cover class, OSM region and nearest power
infrastructure in one call:

```bash
uv run scripts/locate.py -71.0490 42.3480 --radius-km 2
```

It takes 10 to 60 s: a point in the US or another large country reads
that country's whole GAUL file (see Pitfalls).

### 6. Answer

Give, in this order:

1. The number or the answer, with units.
2. The definitions you chose (area members, thresholds, footprint or
   centroid).
3. Coverage and gaps (counties without FEMA data, the OSM completeness
   caveat).
4. The data dates: the FEMA `fema_update_date` per delivery, the OSM
   snapshot date (`osm/snapshots.json`), CORINE 2018, GAUL 2024.
5. The credit for each dataset used, from `reference/datasets.md`.

Offer the SQL you ran, so the person can rerun or adjust it.

## Pitfalls

- A geometry filter on a whole-world file is slow: the GAUL world L2 file
  takes about 12 s for one point. Find the country from the L0 boxes
  first (under 1 s), then read that country's file.
- The GAUL files of large countries are one row group, so a bbox filter
  cannot skip anything: `country=USA/L2.parquet` is 69 MB read in full.
  Read such a file once into a local table and reuse it for every point
  or area of the session. For a US county, the NFHL index
  (`counties.parquet`, 2,500 rows) is a faster first lookup when the
  county has a FEMA delivery.
- `ST_Transform` without `SET geometry_always_xy = true` reads EPSG:4326
  as lat, lon and puts the point in the wrong place without an error.
- NFHL rows are pieces of zones, cut to at most 100 vertices. Count zones
  with `count(*) FILTER (WHERE piece_id = 0)`, and use `DISTINCT` when you
  count features that touch pieces, since one building can touch several.
- An OSM feature that crosses a state border is in both state files. Use
  `DISTINCT (osm_type, osm_id)` when you combine regions.
- CORINE codes are strings (`'221'`), and the first digit is the level-1
  group: 1 artificial, 2 agricultural, 3 forest and semi-natural,
  4 wetlands, 5 water.
- NFHL is not an official flood zone determination. Say so whenever you
  report a flood zone for a property.
- GAUL L0 (`L0_derived`) is dissolved by Geomermaids from L1, not
  published by FAO, and GAUL boundaries carry the UN disclaimer.
