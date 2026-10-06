# The parquetry datasets

All URLs are under `https://parquetry.geomermaids.com/`. The same keys are
on the anonymous S3 endpoint as `s3://parquetry/<key>` (endpoint
`s3.geomermaids.com`, path-style, empty credentials), which is the form a
glob needs.

Every file has a `bbox` struct column (`xmin`, `ymin`, `xmax`, `ymax`),
declared as the GeoParquet covering, and is sorted along a Hilbert curve.
Filter on `bbox` first. The geometry column is native Parquet `GEOMETRY`.

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
