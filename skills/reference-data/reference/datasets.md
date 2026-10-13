# The parquetry datasets

All URLs are under `https://parquetry.geomermaids.com/`. The same keys are
on the anonymous S3 endpoint as `s3://parquetry/<key>` (endpoint
`s3.geomermaids.com`, path-style, empty credentials), which is the form a
glob needs.

Every file has a `bbox` struct column (`xmin`, `ymin`, `xmax`, `ymax`),
declared as the GeoParquet covering, and is sorted along a Hilbert curve.
Filter on `bbox` first. The geometry column is native Parquet `GEOMETRY`.
One exception: the CORINE H3 table is keyed by cell, without `bbox`.

The `bbox` fields are FLOAT in GAUL, GMWID, OpenStreetMap, Geoconnex and
Census (DOUBLE in NFHL and CORINE). Compare them with literals or FLOAT values:
a DOUBLE bound (any computed value, any Python float passed as a
parameter) makes DuckDB 1.5 cast the column and skip no row group, 5 to
10 times slower. Cast computed bounds with `::FLOAT`, widened by 1e-4
degree so the rounding never cuts a feature off.

## FAO GAUL 2024: administrative units, worldwide

| Level | Rows | File for one country | World file |
|---|---|---|---|
| L0 countries (derived) | 272 | `gaul/2024/country=<ISO3>/L0_derived.parquet` | `gaul/2024/GAUL_2024_L0_derived.parquet` (228 MB) |
| L1 states, regions, provinces | 3,110 | `gaul/2024/country=<ISO3>/L1.parquet` | `gaul/2024/GAUL_2024_L1.parquet` (268 MB) |
| L2 districts, counties, départements | 45,524 | `gaul/2024/country=<ISO3>/L2.parquet` | `gaul/2024/GAUL_2024_L2.parquet` (419 MB) |

Row groups hold at most 4 MiB of geometry, so a bbox filter on a point
reads a couple of MB even in the largest country file.

- Columns: `iso3_code`, `gaul0_code`, `gaul0_name`, `gaul1_code`,
  `gaul1_name`, `gaul2_code`, `gaul2_name` (L2 rows carry all three
  levels), `continent`, `disp_en` (the display name), `geometry`
  (MultiPolygon, CRS84).
- `iso3_code` is ISO 3166-1 alpha-3, plus FAO pseudo-codes for disputed
  areas (`xAB`, `xJK`, `xKO`, `xxx` and others). A few codes group several
  units (`AUS`, `PYF`, `xFR`, `xUK`).
- Each country has a `Waterbody` unit at L1 and L2 for large lakes. Leave it
  out of land statistics.
- Names are FAO's, usually in the local form with accents
  (`Île-de-France`, `Hérault`, `Quebec / Québec`). Match with `ILIKE` and
  check the result.
- `L0_derived` is dissolved by Geomermaids from L1. FAO publishes no 2024
  country layer.
- Licence: CC BY 4.0, with the GAUL 2024 Terms of Use. Credit: "FAO. 2024.
  Global Administrative Unit Layers (GAUL). Licence: CC-BY-4.0". FAO does
  not endorse this use, and the boundaries do not imply any opinion of FAO
  on the legal status of any territory. Full text:
  `gaul/2024/ATTRIBUTION.txt`.

## GMWID: infrastructure, worldwide

One world file per layer: `gmwid/latest/<layer>.parquet`. Rebuilt weekly.

| Group | Layers |
|---|---|
| Power | `power_line`, `power_circuit`, `power_tower`, `power_substation`, `power_plant`, `power_generator`, `power_switchgear`, `power_other` |
| Telecoms | `telecom_cable`, `telecom_building`, `telecom_location`, `telecom_mast`, `telecom_antenna`, `utility_pole`, `street_cabinet` |
| Oil and gas | `pipeline`, `petroleum_site`, `petroleum_well`, `offshore_platform`, `pipeline_feature`, `marker` |
| Water | `water_treatment_plant`, `wastewater_plant`, `pumping_station`, `water_tower`, `water_well`, `pressurised_waterway` |

- Common columns: `osm_id`, `osm_type`, `origin`, `source_id`, `country`
  (ISO alpha-2), `state` (slug of the GAUL L1 unit, see
  `gmwid/latest/_regions.json`), `type`, `lifecycle` (`active`,
  `construction`, `proposed`, `disused`, `abandoned`), `name`, `operator`,
  `tags` (every OSM tag, a MAP), `geometry`.
- Filter on `country` and `state` as well as `bbox`: both prune row groups.
- Units: `voltage_kv` (the highest) and `voltages_kv` (list), `output_mw`,
  `length_km`, `area_m2`, heights in m.
- `power_plant.source`: `solar`, `hydro`, `wind`, `gas`, `biomass`, `coal`,
  `oil`, `battery`, `nuclear` and others. `power_line.line` separates
  lines from cables.
- `origin` is `osm` for OpenStreetMap features. Other values are records
  added from authoritative sources where OSM has nothing: `eia` (US power
  plants), `uswtdb` (US wind turbines), `fcc` (US towers), `boem` (US
  offshore), `ogim` (oil and gas worldwide), `ore` (French distribution
  substations), and others. How OSM compares to each source:
  `gmwid/latest/_coverage.json`.
- Licence: ODbL 1.0 for OSM rows, "(c) OpenStreetMap contributors". Rows
  from other sources carry that source's credit: `gmwid/ATTRIBUTION.txt`.

## FEMA NFHL: flood hazard areas, United States

- Index: `nfhl/latest/counties.parquet`, one row per FEMA county-wide
  delivery: `state` (2-letter), `county`, `dfirm_id`, `fema_update_date`,
  `path`, `features`, `zones`, `xmin`, `ymin`, `xmax`, `ymax`, `bbox`,
  `geometry`. The geometry is the delivery's bounding **rectangle**, not
  the county outline: near a county line a point falls in two rectangles.
  Read every candidate file and let the zone pieces decide (they carry
  `state`, `county`, `dfirm_id`), or place features in counties with the
  GAUL L2 polygons.
- Data: `nfhl/latest/<path>`, for example
  `nfhl/latest/state=SC/45019C.parquet`. Updated daily as FEMA republishes.
- Columns: `state`, `county`, `dfirm_id`, `fema_update_date`,
  `flood_zone` (FEMA: `A`, `AE`, `AH`, `AO`, `VE`, `X`, `D` and
  others), `zone_subtype` (FEMA, for example `FLOODWAY`,
  `0.2 PCT ANNUAL CHANCE FLOOD HAZARD`), `sfha` (FEMA's Special Flood
  Hazard Area flag), `static_bfe` (base flood elevation, feet),
  `risk` (Geomermaids reading, below), `floodplain`, `subzone`,
  `piece_id`, `geometry` (Polygon, **EPSG:4269**).
- `risk` values:

  | `risk` | FEMA `flood_zone` | Meaning |
  |---|---|---|
  | `1 percent flood zone` | A, AE, AH, AO, VE... | 100-year floodplain, the Special Flood Hazard Area |
  | `0.2 percent flood zone` | X (shaded) | 500-year floodplain |
  | `minimal` | X (unshaded) | Outside both |
  | `undetermined` | D | Possible but not studied |
  | `water` | OPEN WATER | |
  | `unmapped` | AREA NOT INCLUDED | Inside the delivery, not mapped |
- Rows are pieces of zones, at most 100 vertices each. `piece_id = 0` marks
  one piece per zone.
- Coverage: only counties with a FEMA county-wide digital delivery. Some
  counties have none and are absent from the index, for example Berkshire,
  Franklin and Hampshire in Massachusetts. Absent means unmapped, not
  safe. New York City is not in the index: FEMA delivers it as a
  community, not a county.
- Licence: public domain (FEMA). Credit "FEMA National Flood Hazard Layer".
  Not for official flood zone determinations.

## CORINE Land Cover 2018: land cover, Europe

- Files: `clc/2018/country=<ISO2>/clc_2018.parquet` for each of 48
  countries (list: `clc/index.json`), or `clc/2018/clc_2018.parquet` for
  Europe (2.7 GB).
- Columns: `Code_18` (VARCHAR, three digits), `Area_Ha`, `ID`, `Remark`,
  `country` (ISO alpha-2), `Shape` (the geometry column, **EPSG:3035**).
- Each polygon is whole in the country it overlaps most: a country file can
  run a little past the border. Clip to the area of interest.
- Minimum mapping unit 25 ha, 100 m minimum width: CORINE does not see a
  single field or a small village.
- Licence: Copernicus, full and open. Credit "(c) European Union,
  Copernicus Land Monitoring Service, European Environment Agency (EEA)".

### CORINE on H3 cells

`clc/2018/clc_2018_h3.parquet` (79 MB) summarizes CORINE on H3 cells of
resolutions 3 to 7, for questions about large areas. Every resolution 9
cell (about 0.1 km2) takes the class of the polygon holding its centre;
each coarser cell counts its resolution 9 children.

| `h3_res` | Cells | Cell area |
|---|---|---|
| 3 | 866 | 12,400 km2 |
| 4 | 5,165 | 1,770 km2 |
| 5 | 33,244 | 250 km2 |
| 6 | 224,652 | 36 km2 |
| 7 | 1,549,546 | 5.2 km2 |

- Columns: `h3` (VARCHAR cell id), `h3_res`, `Code_18` (the dominant
  class), `color`, `label`, `dominant_pct`, `artificial_pct`,
  `agricultural_pct`, `forest_pct`, `wetland_pct`, `water_pct` (shares of
  the CORINE-covered part of the cell, in percent), `coverage_pct` (how
  much of the cell CORINE covers: low on coasts and borders), `geometry`
  (the cell, CRS84).
- Rows are sorted by `h3_res`, then `h3`: a filter on `h3_res` reads only
  that resolution's row groups.
- The `_pct` columns are UTINYINT. Cast them before multiplying
  (`forest_pct::INT * coverage_pct`), or DuckDB overflows.
- The level-1 group shares agree with the polygons within half a point
  (Hérault: forest 49.2 % against 49.3 %). All of Spain takes about 4 s,
  where clipping the polygons ran out of memory on a laptop. Per class, a
  cell gives only its dominant class: for the share of vineyards, use the
  polygons.
- Needs the `h3` DuckDB community extension (`INSTALL h3 FROM community`).

### CORINE classes

The first digit is the level-1 group: **1** artificial surfaces,
**2** agricultural areas, **3** forest and semi-natural areas,
**4** wetlands, **5** water bodies.

| Code | Class | Code | Class |
|---|---|---|---|
| 111 | Continuous urban fabric | 242 | Complex cultivation patterns |
| 112 | Discontinuous urban fabric | 243 | Agriculture with significant natural vegetation |
| 121 | Industrial or commercial units | 244 | Agro-forestry areas |
| 122 | Road and rail networks | 311 | Broad-leaved forest |
| 123 | Port areas | 312 | Coniferous forest |
| 124 | Airports | 313 | Mixed forest |
| 131 | Mineral extraction sites | 321 | Natural grasslands |
| 132 | Dump sites | 322 | Moors and heathland |
| 133 | Construction sites | 323 | Sclerophyllous vegetation |
| 141 | Green urban areas | 324 | Transitional woodland-shrub |
| 142 | Sport and leisure facilities | 331 | Beaches, dunes, sands |
| 211 | Non-irrigated arable land | 332 | Bare rocks |
| 212 | Permanently irrigated land | 333 | Sparsely vegetated areas |
| 213 | Rice fields | 334 | Burnt areas |
| 221 | Vineyards | 335 | Glaciers and perpetual snow |
| 222 | Fruit trees and berry plantations | 411 | Inland marshes |
| 223 | Olive groves | 412 | Peat bogs |
| 231 | Pastures | 421 | Salt marshes |
| 241 | Annual crops with permanent crops | 422 | Salines |
| 511 | Water courses | 423 | Intertidal flats |
| 512 | Water bodies | 521 | Coastal lagoons |
| 522 | Estuaries | 523 | Sea and ocean |

## Geoconnex: US water reference features and monitoring sites

Geoconnex (Internet of Water) links US water data to the places it
describes. Republished weekly, Hilbert sorted, row groups of at most
4 MiB. CRS84.

- Reference layers, full attributes: `geoconnex/latest/reference/<layer>.parquet`
  - `mainstems`: 852,673 rivers, each one line from head to outlet.
    `uri`, `primary_name`, `name_at_outlet`, `lengthkm`,
    `outlet_drainagearea_sqkm`, `downstream_mainstem_id` (the river it
    flows into, empty at the sea), `superseded` (filter it out), NHDPlus
    and HUC12 ids at head and outlet. Names repeat (two Colorado Rivers):
    pick by drainage area or place.
  - `gages` (203,525), `dams` (98,534, USACE National Inventory of Dams):
    `uri`, `name`, `mainstem_uri` (the river they sit on, set for about
    half the gages and 21% of dams), drainage areas, NHDPlus reach, `provider`.
  - `hu02`, `hu04`, `hu06`, `hu08`, `hu10`, `hu12`: watersheds, `huc`,
    `name`, `uri`. A HUC12 starts with its HU10, HU08... code.
  - `principal_aquifers`, `national_aquifers`, `hydrogeologic_regions`.
  - `water_systems`: public water system service areas, `pwsid`, `name`.
- Features published by data providers, one file per source:
  `geoconnex/latest/providers/<source>.parquet`, columns `uri`, `name`,
  `description`, `mainstem_uri`.
  - `epa_wqp`: 2.87 million Water Quality Portal sites (EPA, USGS, states).
  - `usgs_monitoring_locations`: 1.74 million USGS sites (stream gages,
    wells, lakes...). Most also appear in `epa_wqp`.
  - `usgs_gnis` (names), `usgs_national_geologic_map` (map units,
    polygons), and state and western water sources (`iow_state_gages_*`,
    `wwdh_snotel`, `wwdh_usbr_rise`...). The list: `providers/_manifest.json`.
- Every `uri` resolves at geoconnex.us to the feature's page and the data
  published about it: give it in answers.
- Versions: `geoconnex/latest/_source.json` (Geoconnex export date, rivers
  release).
- Licence: CC0. No attribution required; credit "Geoconnex, Internet of
  Water" and the agency of the source (USGS, USACE, EPA).

## US Census TIGER/Line 2026: election districts

The Census Bureau's 2026 Legislative Areas, the districts of the November
2026 elections. One national file per layer, Hilbert sorted, row groups of
at most 4 MiB. **NAD83 (EPSG:4269)**, like NFHL.

| File | Rows | Districts |
|---|---|---|
| `census/tiger/2026/legislative/cd120.parquet` | 444 | US House, 120th Congress: 435 seats, 50 states, plus DC and the territories |
| `census/tiger/2026/legislative/sldu.parquet` | 1,964 | State Senates (upper chambers), 50 states, DC, Puerto Rico |
| `census/tiger/2026/legislative/sldl.parquet` | 4,879 | State Houses (lower chambers), 49 states and Puerto Rico. Nebraska's legislature has one chamber, in `sldu`. |

- Columns are TIGER's, unchanged: `STATEFP` (state FIPS), the district
  code (`CD120FP`, `SLDUST` or `SLDLST`), `GEOID` (state FIPS + code),
  `GEOIDFQ` (for data.census.gov), `NAMELSAD` ("Congressional District
  10", "State Senate District 14"), `LSAD`, `MTFCC`, `FUNCSTAT`, `ALAND`
  and `AWATER` (m2), `INTPTLAT` and `INTPTLON` (an interior point, as
  text), `bbox`, `geometry`.
- Placeholders, not districts: `ZZ` or `ZZZ` (no district defined, often
  water) and, in `cd120`, `98` (the non-voting delegates of DC and the
  territories). Leave them out of counts:
  `WHERE CD120FP NOT LIKE 'ZZ%' AND CD120FP <> '98'`. `00` is a real
  at-large district (Alaska, Delaware, North Dakota, South Dakota,
  Vermont, Wyoming).
- State FIPS to postal code: `census/tiger/2026/legislative/_manifest.json`,
  under `states`, with each state's bounds.
- Maps redrawn since the 2024 elections: census.geomermaids.com compares
  these districts with the 119th Congress ones (TIGER 2025). Ten states
  changed (TN, UT, CA, OH, LA, MO, TX, AL, FL, NC); Iowa could not be
  compared. `https://census.geomermaids.com/redistricting.json` lists them
  (`redrawn`), and gives under `districts`, by `GEOID`, the overlap (IoU)
  of each of their new districts with its closest old one.
- Licence: public domain (US Government work). Credit "U.S. Census
  Bureau, TIGER/Line 2026". Boundaries are statistical, not legal
  descriptions. Full text: `census/tiger/2026/legislative/ATTRIBUTION.txt`.

## OpenStreetMap: US, Canada, Mexico

- Files: `osm/latest/country=<CC>/state=<ISO 3166-2>/<theme>.parquet`, for
  example `osm/latest/country=US/state=US-MA/buildings.parquet`. The 98
  regions are in `reference/osm-regions.csv`. Rebuilt nightly. Dated
  snapshots: `osm/snapshots.json`.
- A whole theme: `s3://parquetry/osm/latest/country=*/state=*/<theme>.parquet`.
- Themes: `buildings`, `roads`, `railways`, `waterways`, `water`,
  `landuse`, `natural_areas`, `natural_features`, `places`, `boundaries`,
  `pois`, `amenities_polygons`, `power`, `aeroways`, `barriers`,
  `public_transport`.
- Common columns: `osm_id`, `osm_type`, `country`, `state_name`,
  `state_iso`, `name`, `tags` (MAP of every tag), `bbox`, `geometry`.
  Theme columns, for example:
  - `buildings`: `building`, `levels`, `height`, `addr_street`,
    `addr_housenumber`, `addr_postcode`, `addr_city`.
  - `roads`: `highway`, `ref`, `oneway`, `surface`, `maxspeed`, `lanes`,
    `bridge`, `tunnel`.
  - `pois`: `amenity`, `shop`, `tourism`, `leisure`, `office`,
    `healthcare`, `brand`, `operator`.
  - `places`: `place`, `population`, `capital`.
  Full lists: `osm/catalog/<theme>/AGENTS.md`.
- A feature crossing a state border is in both files.
- Licence: ODbL 1.0. Credit "(c) OpenStreetMap contributors".

## Maps: PMTiles archives

When the answer is a map, draw it from a PMTiles archive with MapLibre and
the `pmtiles` protocol, not from the Parquet files. The archives sit next
to the data and answer range requests:

| Archive | Source layer | Zooms | Properties |
|---|---|---|---|
| `gaul/2024/GAUL_2024_L0_derived.pmtiles` (63 MB) | `l0_derived` | 0-10 | all |
| `gaul/2024/GAUL_2024_L1.pmtiles` (94 MB) | `l1` | 0-10 | all |
| `gaul/2024/GAUL_2024_L2.pmtiles` (178 MB) | `l2` | 3-10 | `iso3_code`, `gaul1_name`, `gaul2_code`, `gaul2_name`, `continent` |
| `clc/2018/clc_2018.pmtiles` (2.2 GB) | `cells` z0-8 (H3 cells, as in the H3 table), `clc_2018` z9-12 (polygons) | 0-12 | `Code_18`, `color`, `label`, and the cell shares |
| `census/tiger/2026/legislative/<cd120, sldu, sldl>.pmtiles` | `cd120`, `sldu`, `sldl` | 0-12 | `STATEFP`, the district code, `GEOID`, `NAMELSAD`, `ALAND`, `AWATER`, `color_index` |

- CORINE features carry their official colour: `["get", "color"]` draws
  the legend with no lookup table.
- Census districts carry `color_index` (0 to 5), chosen so that no two
  neighbouring districts share it: map it to a six-colour palette.
- Each Portolan collection also publishes ready MapLibre styles
  (`styles/default.json` and others) that point at the archive.
- A quick look without code: `https://geoparquet.geomermaids.com/viewer.html?url=<file URL>`
  opens a Parquet file or an archive.

## Portolan catalogs

Every dataset has a STAC catalog (Portolan profile):
`https://parquetry.geomermaids.com/<dataset>/catalog/catalog.json` for
`gaul`, `gmwid`, `nfhl`, `clc`, `geoconnex`, `census` and `osm`. Each
collection links its files, its PMTiles archive, its styles and an
`AGENTS.md`.

A collection extent that crosses the antimeridian is written the STAC
way, with west > east: `[172.4, 14.5, -52.6, 83.3]` is North America
including the Aleutians, not the world minus North America. Read such a
box as two ranges, [west, 180] and [-180, east], and split it the same
way before filtering a `bbox` column with it.
