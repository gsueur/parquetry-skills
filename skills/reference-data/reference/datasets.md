# The parquetry datasets

All URLs are under `https://parquetry.geomermaids.com/`. The same keys are
on the anonymous S3 endpoint as `s3://parquetry/<key>` (endpoint
`s3.geomermaids.com`, path-style, empty credentials), which is the form a
glob needs.

Every file has a `bbox` struct column (`xmin`, `ymin`, `xmax`, `ymax`),
declared as the GeoParquet covering, and is sorted along a Hilbert curve.
Filter on `bbox` first. The geometry column is native Parquet `GEOMETRY`.
One exception: the CORINE H3 table is keyed by cell, without `bbox`.

The `bbox` fields are FLOAT in GAUL, GMWID, OpenStreetMap, Geoconnex,
Census, WorldPop, Structures, the fire layers, NWI and the schools (DOUBLE
in NFHL and CORINE). Compare them with literals or FLOAT values:
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

## US Census ACS 2020-2024: population, income, housing

The American Community Survey 5-year estimates for 2020-2024, from the
Census Bureau's Summary File: 33 measures, each with its 90 percent margin
of error in `<measure>_moe`. Two files per geography:

| File | Rows | Geometry |
|---|---|---|
| `census/acs/2024/state.parquet`, `state_geo.parquet` | 52 | outline in `_geo` |
| `census/acs/2024/county.parquet`, `county_geo.parquet` | 3,222 | |
| `census/acs/2024/place.parquet`, `place_geo.parquet` | 32,330 (32,304 with an outline) | |
| `census/acs/2024/tract.parquet`, `tract_geo.parquet` | 85,382 | |
| `census/acs/2024/bg.parquet`, `bg_geo.parquet` | 242,297 (block groups) | |
| `census/acs/2024/zcta520.parquet`, `zcta520_geo.parquet` | 33,772 (ZIP code areas) | |

- `<geo>.parquet` is the table alone, sorted by `GEOID`: a state or county
  prefix (`WHERE GEOID LIKE '25025%'`) reads few row groups.
  `<geo>_geo.parquet` adds TIGER/Line 2026's outline, `ALAND`, `AWATER`,
  `bbox` and `geometry`, **NAD83 (EPSG:4269)** like TIGER.
- Keys: `GEOID` (TIGER's identifier: state 2, county 5, tract 11, block
  group 12 digits, place 7, ZCTA 5), `NAME`, `STUSAB` (postal code).
- Measures: `population`, `median_age`, `households`,
  `median_household_income`, `per_capita_income`, `poverty_universe`,
  `below_poverty`, `poverty_rate`, `median_home_value`,
  `median_gross_rent`, `housing_units`, `vacant_units`, `vacancy_rate`,
  `occupied_units`, `owner_occupied`, `renter_occupied`,
  `owner_occupied_rate`, `hispanic_or_latino` and seven
  `<race>_not_hispanic` groups, `population_25_and_over`,
  `bachelors_or_higher`, `bachelors_or_higher_rate`, `workers`,
  `transit_commuters`, `transit_share`, `commuters_outside_home`,
  `mean_travel_time`. Rates are percent, 0 to 100. Each column's
  description in the catalog gives its ACS variable code.
- NULL where the Census Bureau could not compute an estimate (too few
  cases). Top codes mean "this much or more": income 250001, home value
  2000001, rent 3501. `mean_travel_time` is NULL for block groups (not
  published at that level).
- Counts add up across areas, with a MOE of `sqrt(sum(moe ^ 2))`.
  Medians do not: weight them by population, and say so.
- Known gap in the source: 14 tracts and 39 block groups of Suffolk County,
  NY are missing from the Summary File, though the county row counts
  their 77,579 people.
- Licence: public domain (US Government work). Credit "U.S. Census
  Bureau, American Community Survey 2020-2024 5-year estimates".

## FEMA National Risk Index 1.20: natural hazard risk, United States

FEMA's National Risk Index, version 1.20 (December 2025), from OpenFEMA.
One file per level, **CRS84** (FEMA ships Web Mercator; reprojected):

| File | Rows | Key |
|---|---|---|
| `nri/v1.20/tracts.parquet` | 85,154 | `TRACTFIPS`, joins TIGER and ACS tract `GEOID` |
| `nri/v1.20/counties.parquet` | 3,232 | `STCOFIPS`, joins county `GEOID` |
| `nri/v1.20/states.parquet` | 56 | `STATEFIPS` |
| `nri/v1.20/tribal_counties.parquet` | 1,232 | `NRI_ID` (tribe `AIANNHCE`, `JURS_NAME`, county `STCOFIPS`) |
| `nri/v1.20/hazards.parquet` | 18 | `Prefix` to `Hazard` name, period of record |

- Columns are FEMA's names (468 for tracts). The composite:
  `RISK_SCORE`, `RISK_RATNG`, `RISK_VALUE` (dollars a year); expected
  annual loss `EAL_VALT` (total, dollars a year), `EAL_SCORE`,
  `EAL_RATNG`; social vulnerability `SOVI_SCORE`, `SOVI_RATNG`; community
  resilience `RESL_SCORE`, `RESL_RATNG`. Exposure: `POPULATION`,
  `BUILDVALUE`, `AGRIVALUE`, `AREA` (square miles).
- Per hazard, columns start with the hazard's prefix: `<P>_RISKS`
  (score), `<P>_RISKR` (rating), `<P>_EALT` (expected annual loss),
  `<P>_AFREQ` (annual frequency), `<P>_EXPT` (exposure). The 18 prefixes:
  `AVLN` avalanche, `CFLD` coastal flooding, `CWAV` cold wave, `DRGT`
  drought, `ERQK` earthquake, `HAIL` hail, `HWAV` heat wave, `HRCN`
  hurricane, `ISTM` ice storm, `LNDS` landslide, `LTNG` lightning, `IFLD`
  inland flooding, `SWND` strong wind, `TRND` tornado, `TSUN` tsunami,
  `VLCN` volcanic activity, `WFIR` wildfire, `WNTW` winter weather.
- Scores are national percentiles (0 to 100) among areas of the same
  level. Ratings are FEMA's classes: `Very Low`, `Relatively Low`,
  `Relatively Moderate`, `Relatively High`, `Very High`, plus
  `No Rating`, `Insufficient Data`, `Not Applicable`. A high score with a
  moderate rating is normal: quote both.
- States are rated on expected annual loss only: no `RISK_*`, `SOVI_*`
  or `RESL_*` columns at that level.
- The full dictionary: `nri/v1.20/NRIDataDictionary.csv`.
- The NRI is a screening tool for comparing communities, not a
  property-level assessment. Say so when you report it for a site.
- Licence: public domain (US Government work). Credit "FEMA, National
  Risk Index, version 1.20".

## Natural Earth 5.1.2: world basemap layers

Natural Earth's cultural and physical vectors at three scales, **CRS84**,
Natural Earth's columns unchanged:
`natural-earth/v5.1.2/<scale>/<layer>.parquet`.

| Layer | 10m | 50m | 110m |
|---|---|---|---|
| `admin_0_countries`, `admin_1_states_provinces`, `populated_places`, `coastline`, `land`, `ocean`, `rivers_lake_centerlines`, `lakes`, `graticules_10` | yes | yes | yes |
| `urban_areas` | yes | yes | |
| `airports`, `ports`, `time_zones` | yes | | |

- 10m (1:10 million) for analysis and labels; 50m and 110m for world and
  continent maps.
- `admin_1_states_provinces` covers every country at 10m only (9
  countries at 50m, the US at 110m).
- `populated_places`: `NAME`, `NAMEASCII`, `ADM0NAME`, `ADM0_A3`,
  `ADM1NAME`, `FEATURECLA` (for example `Admin-0 capital`), `POP_MAX`,
  `POP_MIN`, `SCALERANK` (0 most important), `LATITUDE`, `LONGITUDE`.
  7,342 places at 10m, chosen for labels, not a complete list.
  `POP_MAX` is `-99` when unknown: filter it out before ranking.
- Countries: join on `ISO_A2_EH`, `ISO_A3_EH` or `ADM0_A3`. `ISO_A2` and
  `ISO_A3` are `-99` for France, Norway and a few others.
- Seven units cross the antimeridian (Fiji, Russia among them): their
  `bbox` spans every longitude, so a box filter keeps them everywhere.
  Test the geometry.
- Licence: public domain. Credit "Made with Natural Earth".

## USGS PAD-US 4.1: protected areas, United States

The Protected Areas Database of the United States, version 4.1 (2025),
from USGS's Gap Analysis Project. **NAD83 (EPSG:4269)**, like TIGER.

| File | Rows | What |
|---|---|---|
| `padus/v4.1/combined.parquet` | 656,986 | every feature class together: start here |
| `padus/v4.1/combined/state=<XX>/combined.parquet` | 58 files | Combined per state or territory (postal code) |
| `padus/v4.1/fee.parquet` | 296,456 | ownership parcels |
| `padus/v4.1/designation.parquet` | 13,398 | policy designations (wilderness, monuments) |
| `padus/v4.1/easement.parquet` | 341,954 | conservation easements |
| `padus/v4.1/marine.parquet` | 1,739 | marine protected areas |
| `padus/v4.1/proclamation.parquet` | 3,439 | approved and proclamation boundaries |
| `padus/v4.1/lookups/<table>.parquet` | 8 tables | the code tables (`Code`, `Dom`) |

- Columns are PAD-US's, plus `<col>_Desc` beside every coded one:
  `Category` (Fee, Designation, Easement, Marine, Proclamation),
  `Unit_Nm`, `Own_Type`, `Own_Name`, `Mang_Type`, `Mang_Name` (agency
  code, `Mang_Name_Desc` the name), `Des_Tp`, `State_Nm`, `GIS_Acres`,
  `GAP_Sts`, `Pub_Access`, `IUCN_Cat`, `Date_Est`, `Source_PAID`,
  `WDPA_Cd`.
- GAP status: `1` and `2` managed for biodiversity (1 lets disturbance
  such as fire run its course, 2 suppresses it), `3` multiple use (open
  to mining, logging or off-highway vehicles), `4` no known mandate.
- Public access: `OA` open, `RA` restricted (permit or season), `XA`
  closed, `UK` unknown.
- **Areas overlap, in Combined too.** For "how much is protected", take
  the union of the geometries, or `Category = 'Fee'` for ownership, and
  leave `Proclamation` out: it is an approved or extent boundary, not land
  held. Never sum `GIS_Acres` across rows.
- `OBJECTID` is unique within 4.1 only; `Source_PAID` and `WDPA_Cd`
  identify an area across releases where present.
- A few Alaska areas are 10 to 26 MB each: always filter on `bbox` first.
- Licence: public domain. Credit "U.S. Geological Survey, Gap Analysis
  Project, PAD-US 4.1".

## US National Address Database, release 24

USDOT's National Address Database, compiled 2026-09-30: 99,226,272
address points. **CRS84** (NAD's lon/lat are WGS 84).

- Files: `addresses/nad/r24/state=<XX>/addresses.parquet`, one per state
  (postal code), Hilbert sorted. No national file: read every state with
  `s3://parquetry/addresses/nad/r24/state=*/addresses.parquet` on the S3
  endpoint, `hive_partitioning = false`.
- Columns are NAD's 62 (`Add_Number`, `St_PreDir`, `St_Name`,
  `St_PosTyp`, `StNam_Full`, `Unit`, `Inc_Muni`, `Post_City`, `County`,
  `State`, `Zip_Code`, `Longitude`, `Latitude`, `Placement`, `UUID`,
  `OID_`, `DateUpdate`...) plus `full_address`, normalized for matching:
  upper case, no punctuation, USPS abbreviations,
  `'<number> <street with modifiers> <unit>, <city>, <state> <zip>'`.
  Normalize the input the same way, filter on `Zip_Code` or `State`, then
  match exactly or rank with `jaro_winkler_similarity`.
- `Placement` says how the point was placed: `Structure - Rooftop`,
  `Structure - Entrance`, `Site`, `Parcel - Centroid`, `Other`, `Unknown`.
  A rooftop point is not a parcel centroid; say which you return.
- Coverage: no rows for HI, MI, MS, NH, NV, AS, GU, MP, PR; partial in
  others (GA 2 of 159 counties, FL 8/67, SC 3/46, LA 5/64, CA 18/58,
  PA 25/67, MO 33/115). `addresses/nad/r24/_coverage.json` lists rows and
  counties per state; `addresses_h3.parquet` counts points on H3 cells
  (resolutions 4, 6, 8).
- `OID_` is unique within r24; `UUID` follows a point across releases
  (220 values repeat in r24).
- Licence: public domain. Credit "U.S. Department of Transportation,
  National Address Database, release 24".

## Gazetteer: Census Gazetteer 2026 and GeoNames

Names to points. **Census** for US statistical areas, joined to TIGER and
the ACS on `GEOID`; **GeoNames** for anywhere else, and for features that
are not statistical areas (mountains, lakes, buildings).

- Census Gazetteer 2026, **EPSG:4269**:
  `gazetteer/census/2026/<layer>.parquet`, named like the TIGER layers:
  `state`, `county`, `place` (32,363), `cousub`, `tract`, `zcta520`,
  `cbsa`, `cd120`, `sldu`, `sldl`, `uac20`, `aiannh`, `elsd`, `scsd`,
  `unsd`, `sdadm`, `aiannhrt`. Columns `USPS`, `GEOID`, `NAME` ("Springfield
  city", with the legal suffix), `ALAND`, `AWATER`, `INTPTLAT`,
  `INTPTLONG`, a point `geometry`. No population: join the ACS on `GEOID`.
- GeoNames, **CRS84**, rebuilt weekly (`_manifest.json` gives the dump
  date): `gazetteer/geonames/latest/geonames.parquet` (13,483,704 names),
  `country=<CC>/geonames.parquet`, and `cities1000.parquet` (172,035
  places of 1,000 people or more, plus seats of government). Columns
  `geonameid`, `name`, `asciiname`, `alternatenames`, `feature_class`,
  `feature_code` with `feature_name`, `country_code`, `country_name`,
  `admin1_name`, `admin2_name`, `population`, `elevation`, `timezone`.
  About 55,000 admin1 and 163,000 admin2 codes have no name in GeoNames'
  own lists: the code is kept, the name is empty.
- Licence: Census public domain, credit "U.S. Census Bureau, 2026
  Gazetteer Files"; GeoNames CC BY 4.0, credit "GeoNames
  (www.geonames.org)".

## WorldPop 2025: population on H3 cells, worldwide

WorldPop Global2 R2025A: people per H3 resolution 7 cell (about 5 km²)
in 2025, with age groups and sex. **CRS84**, the cell hexagon as
geometry.

- Files: `worldpop/R2025A/2025/country=<ISO3>/worldpop_2025.parquet`, one
  per country (253, GAUL `iso3_code`), and
  `worldpop/R2025A/2025/worldpop_2025_world_r5.parquet` (resolution 5,
  one row per cell, for world and continent questions). Every country:
  `s3://parquetry/worldpop/R2025A/2025/country=*/worldpop_2025.parquet`.
- Columns: `h3` (the cell as text), `country`, `population`, `pop_0_14`,
  `pop_15_64`, `pop_65_plus`, `pop_80_plus`, `female`, `male`, `area_km2`,
  `lon`, `lat` (the cell centre: use it, not `ST_Centroid`, which a cell
  cut at the antimeridian puts far away).
- Modelled estimates, good to a cell (about 2.5 km across), not to a
  street. In the US, prefer the 2020 blocks or the ACS; elsewhere this is
  the population layer.
- H3 joins: `h3_string_to_h3(h3)` with DuckDB's community `h3` extension;
  `h3_cell_to_parent` aggregates to coarser cells.
- Licence: CC BY 4.0. Credit "WorldPop (www.worldpop.org), Global2 R2025A
  v1, University of Southampton, doi:10.5258/SOTON/WP00846".

## FEMA USA Structures: building footprints, United States

USA Structures (ORNL and FEMA): 146 million building footprints with
occupancy class and ORNL's modelled residents. **CRS84**.

- Files: `structures/latest/state=<XX>/structures.parquet`, one per state
  or territory (56, postal code). Every state:
  `s3://parquetry/structures/latest/state=*/structures.parquet`.
- Counts per area without the footprints:
  `structures/latest/state=<XX>/cells.parquet`, one row per H3 cell and
  resolution (`h3_res` 4, 6, 8) with `structures`, `residential` and
  `population`. A cell on a state line is in both states' files.
- Columns: `BUILD_ID`, `OCC_CLS` (Residential, Commercial, Industrial,
  Education, Government, Assembly, Agriculture, Utility and Misc,
  Unclassified), `PRIM_OCC` ('Single Family Dwelling', 'Multi - Family
  Dwelling'...), `OUTBLDG` (sheds, garages), `HEIGHT`, `SQMETERS`,
  `SQFEET`, `PROP_ADDR`, `PROP_CITY`, `PROP_ZIP`, `FIPS` (county),
  `CENSUSCODE` (block), `POP_MEDIAN`, `POP_CI95_LOWER`, `POP_CI95_UPPER`,
  `IMAGE_DATE`, `SOURCE`, `state`.
- Residents: `sum(POP_MEDIAN)` is ORNL's model, not a census count.
  Commercial and other non-residential buildings have NULL. Under 90% of
  residential footprints carry an estimate in DC (27%) and the
  territories (0%): there, use the 2020 blocks for people. Arkansas runs
  high against the 2020 census.
- States come from different imagery vintages (`IMAGE_DATE`): compare
  states with care.
- Licence: public domain. Credit "Oak Ridge National Laboratory (ORNL);
  FEMA Geospatial Response Office".

## Wildfire perimeters: NIFC WFIGS and MTBS, United States

Fire perimeters and incident points, **CRS84**, dates in UTC.

| File | Rows | What |
|---|---|---|
| `fire/wfigs/latest/current.parquet` | tens | fires burning now, rebuilt several times a day |
| `fire/wfigs/latest/year_to_date.parquet` | about 8,300 | this year's perimeters |
| `fire/wfigs/latest/all_since_2016.parquet` | about 43,000 | the last perimeter of every WFIGS fire |
| `fire/wfigs/latest/incidents_ytd.parquet` | about 45,000 | one point of origin per incident this year, most never get a perimeter |
| `fire/mtbs/latest/mtbs_perimeters.parquet` | 31,514 | burned areas since 1984, large fires only (1,000 acres West, 500 East) |

- WFIGS perimeter columns start with `poly_` (`poly_IncidentName`,
  `poly_GISAcres`, `poly_PolygonDateTime`), incident columns with `attr_`
  (`attr_FireDiscoveryDateTime`, `attr_FireOutDateTime` empty while it
  burns, `attr_PercentContained`, `attr_IncidentTypeCategory` WF wildfire
  / RX prescribed / CX complex, `attr_FireCause`, `attr_POOState` as
  `US-CA`, `attr_POOFips` county FIPS). `incidents_ytd` has the same
  names without `attr_`.
- **WFIGS history starts in practice in 2020**: fewer than ten
  perimeters before it (no Camp Fire, 2018). For older fires, use MTBS.
- MTBS: `event_id`, `irwinid`, `incid_name`, `incid_type`, `ig_date`,
  `burnbndac` (acres), and the burn severity thresholds. A fire reaches
  MTBS a year or two after it burns (352 fires for 2025 so far).
- `attr_IrwinID` (WFIGS), `IrwinID` (incidents) and `irwinid` (MTBS) join
  the same fire across layers where present.
- Perimeters overlap (complexes, re-burns): take the union before summing
  an area.
- Not for evacuation or safety decisions. Say so when reporting an active
  fire.
- Licence: public domain. Credit "National Interagency Fire Center
  (NIFC), WFIGS" and "Monitoring Trends in Burn Severity (MTBS), USGS and
  USDA Forest Service".

## USFWS National Wetlands Inventory, October 2026

Wetlands and deepwater habitats: 38.7 million polygons. **NAD83
(EPSG:4269)**, like TIGER.

- Files: `wetlands/nwi/2026-10/state=<XX>/wetlands.parquet`, 57 (states,
  DC, PR, territories; `UM` for Palmyra and Kingman). Read with
  `hive_partitioning = false`: the `state` column already holds it.
  `wetlands/nwi/2026-10/projects.parquet`: the mapping projects, with the
  imagery year (`IMAGE_YR`). `codes.parquet`: FWS's definitions, by
  `ATTRIBUTE`.
- Columns: `NWI_ID`, `ATTRIBUTE` (the Cowardin code, for example `PFO1A`),
  `WETLAND_TYPE`, `ACRES`, `SYSTEM_NAME`, `SUBSYSTEM_NAME`, `CLASS_NAME`,
  `SUBCLASS_NAME`, `WATER_REGIME_NAME`, `MODIFIER1_NAME`, `MODIFIER2_NAME`.
- `WETLAND_TYPE`: Freshwater Emergent Wetland, Freshwater Forested/Shrub
  Wetland, Freshwater Pond, Estuarine and Marine Wetland, Riverine, Lake,
  Estuarine and Marine Deepwater, Other. Lakes, rivers and bays are
  mapped too: "wetland area" usually leaves out Lake, Riverine and
  Estuarine and Marine Deepwater.
- Each polygon is in one file: FWS's copies across state downloads were
  removed. A polygon crossing a state line is in the state of its
  interior point; clip to the state for an exact state area. `ACRES` is
  the whole polygon's.
- Imagery years run from 1971 to 2024: give the `IMAGE_YR`
  of the project under the site.
- Not a jurisdictional delineation (Clean Water Act or otherwise). Say so.
- Licence: public domain. Credit "U.S. Fish and Wildlife Service,
  National Wetlands Inventory".

## NCES school locations, United States

The National Center for Education Statistics' EDGE geocodes. **CRS84**
points.

| File | Rows | Key | Year |
|---|---|---|---|
| `schools/latest/public.parquet` | 102,178 | `NCESSCH` (12 characters), `LEAID` the district | 2024-25 |
| `schools/latest/private.parquet` | 22,510 | `PPIN` | 2023-24 |
| `schools/latest/postsecondary.parquet` | 6,438 | `UNITID` (IPEDS) | 2025-26 |

- Columns: `NAME`, `STREET`, `CITY`, `STATE`, `ZIP`, `STFIP`, `CNTY`
  (county GEOID), `NMCNTY`, `LOCALE`, `LAT`, `LON`, `CBSA`, `CSA`, `CD`,
  `SLDL`, `SLDU`, `SCHOOLYEAR`.
- `LEAID` joins TIGER school district `GEOID`
  (`census/tiger/2026/school/unsd, elsd, scsd.parquet`); `CNTY` joins
  county `GEOID`; `NCESSCH` joins NCES's Common Core of Data (enrollment,
  grades), which is not here.
- `LOCALE`: first digit 1 city, 2 suburb, 3 town, 4 rural. NCES writes
  `M` for missing and `N` for not applicable.
- Licence: public domain. Credit "U.S. Department of Education, National
  Center for Education Statistics, EDGE".

## Census TIGER/Line: tribal areas and 2020 blocks

**NAD83 (EPSG:4269)**, TIGER's columns.

- Tribal areas, 2026: `census/tiger/2026/aiarelated/<layer>.parquet`:
  `aiannh` (867 reservations, off-reservation trust lands, statistical
  areas, Hawaiian home lands; `COMPTYP` T for an off-reservation trust
  land, R for the rest; `AIANNHR` F federally, S state recognized), `anrc` (12 Alaska Native Regional
  Corporations), `aitsn` (484 tribal subdivisions), `ttract` (494 tribal
  tracts), `tbg` (936 tribal block groups). `AIANNHCE` links them, and
  NRI's `tribal_counties`. The Census Gazetteer's `aiannh` joins on `GEOID`.
- 2020 tabulation blocks, with the 2020 census counts:
  `census/tiger/2020/block/state=<XX>/blocks.parquet`, 52 files (50
  states, DC, PR; 8,174,955 blocks), read with `hive_partitioning = false`.
  Columns `GEOID20` (15 digits: state, county, tract, block), `POP20`,
  `HOUSING20`, `ALAND20`, `AWATER20`, `UR20` (urban/rural),
  `INTPTLAT20`, `INTPTLON20` (interior point, as text).
  `POP20` sums to 334,735,155, the official 2020 count with PR.
- Blocks on H3: `census/tiger/2020/block/blocks_h3.parquet` (`h3_res` 4,
  6, 8; `population`, `housing_units`, `blocks`), each block counted at
  its interior point.
- Blocks are the finest US population: for a small or odd-shaped area
  (a fire perimeter, a flood zone, 1 km around a site), sum `POP20` of
  the blocks whose interior point is inside. The Island Areas (AS, GU,
  MP, VI) are not included.
- Licence: public domain. Credit "U.S. Census Bureau, TIGER/Line 2026"
  and "2020 Census Redistricting Data (P.L. 94-171)".

## OpenStreetMap: US, Canada, Mexico

- Files: `osm/latest/country=<CC>/state=<ISO 3166-2>/<theme>.parquet`, for
  example `osm/latest/country=US/state=US-MA/buildings.parquet`. The 98
  regions are in `reference/osm-regions.csv`. Rebuilt nightly. The
  first build of each month is kept for 12 months under `osm/<YYYY-MM-DD>/`:
  `osm/snapshots.json` gives the build date and lists them.
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
| `census/acs/2024/<geo>_geo.pmtiles` | `acs_<geo>` | state, county 0-12; place, zcta520 6-12; tract 7-12; bg 10-12 | state: every measure. County, place, ZCTA: `GEOID`, `NAME`, `population`, `median_household_income` and its MOE, `poverty_rate`. Tract, bg: `GEOID`, `median_household_income` |
| `nri/v1.20/<level>.pmtiles` | `tracts`, `counties`, `states`, `tribal_counties` | tracts 7-12, counties and states 0-10, tribal 0-12 | the key, the ratings (`RISK_RATNG`; `EAL_RATNG` for states) and their scores |
| `natural-earth/v5.1.2/<scale>/<layer>.pmtiles` | the layer name | 10m 0-8 (admin-1, places, airports 1-8), 50m 0-5, 110m 0-3 | all, but only the naming columns for 10m admin-1 and places and for 50m places |
| `natural-earth/v5.1.2/<scale>/basemap.pmtiles` | `ne`, every layer, told apart by `ne_layer` | as above | as above |
| `padus/v4.1/combined.pmtiles` | `combined` | 0-12 | `Unit_Nm`, `Category`, `Mang_Name_Desc`, `Des_Tp_Desc`, `GAP_Sts`, `Pub_Access`, `IUCN_Cat`, `GIS_Acres`, codes |
| `addresses/nad/r24/addresses_h3.pmtiles` | `cells_r4` z0-4, `cells_r6` z5-7, `cells_r8` z8-11 | 0-11 | address count per H3 cell: where the NAD has data |
| `gazetteer/geonames/latest/cities1000.pmtiles` | `cities1000` | 0-12 | `geonameid`, `name`, `feature_code`, `country_code`, `population` (the most populous place per cell at each zoom) |
| `gmwid/latest/<layer>.pmtiles` (27 archives) | the layer name | from 2, 4 or 6 to 13, by layer | `name`, `operator`, `origin`, the layer's class and `voltage_kv` where it has one |
| `worldpop/R2025A/2025/worldpop_2025.pmtiles` (1.3 GB) | `population` | 0-9 | `h3`, `population`, `density`, `pop_0_14`, `pop_65_plus` |
| `structures/latest/state=<XX>/structures.pmtiles` | `cells_r4` z0-4, `cells_r6` z5-7, `cells_r8` z8-12, `structures` z13-14 | 0-14 | cells: `structures`, `residential`, `population`; footprints: `BUILD_ID`, `OCC_CLS`, `PRIM_OCC`, `HEIGHT`, `SQFEET`, `POP_MEDIAN` |
| `fire/wfigs/latest/<current, year_to_date, all_since_2016>.pmtiles`, `fire/mtbs/latest/mtbs_perimeters.pmtiles` | the file name | 0-12 (year to date 0-13, current 1-14) | name, acres, type, containment (WFIGS); `event_id`, `incid_name`, `ig_date`, `burnbndac` (MTBS) |
| `wetlands/nwi/2026-10/wetlands.pmtiles` (13 GB) | `wetlands` | 6-13 | `ATTRIBUTE`, `WETLAND_TYPE`, `ACRES` |
| `schools/latest/<public, private, postsecondary>.pmtiles` | the file name | 0-13 | the key, `NAME`, `CITY`, `STATE`, `LOCALE` |
| `census/tiger/2026/aiarelated/<layer>.pmtiles` | the layer name | 0-12 | `GEOID`, `NAMELSAD`, `AIANNHCE`, `ALAND`, `AWATER`, `color_index` |
| `census/tiger/2020/block/blocks_h3.pmtiles` | `cells_r4` z0-4, `cells_r6` z5-7, `cells_r8` z8-11 | 0-11 | `population`, `housing_units`, `blocks` per H3 cell |

- CORINE features carry their official colour: `["get", "color"]` draws
  the legend with no lookup table.
- Census districts and tribal areas carry `color_index` (0 to 5), chosen so that no two
  neighbouring districts share it: map it to a six-colour palette.
- ACS styles colour `median_household_income` in fixed national classes
  ($50k, 65k, 80k, 100k, 125k), so a colour means the same at every
  geography; NRI styles colour the five rating classes. Below an
  archive's first zoom, draw the coarser geography instead (counties
  under tracts).
- Natural Earth tiles stop at 85.05 degrees of latitude (web maps cannot
  show more): the South Pole station is in the Parquet file, not the
  tiles.
- Each Portolan collection also publishes ready MapLibre styles
  (`styles/default.json` and others) that point at the archive.
- A quick look without code: `https://geoparquet.geomermaids.com/viewer.html?url=<file URL>`
  opens a Parquet file or an archive.

## Portolan catalogs

Every dataset has a STAC catalog (Portolan profile):
`https://parquetry.geomermaids.com/<dataset>/catalog/catalog.json` for
`gaul`, `gmwid`, `nfhl`, `clc`, `geoconnex`, `census` (TIGER/Line, and
the ACS in its `acs-2024` sub-catalog), `nri`, `natural-earth`, `padus`,
`addresses`, `gazetteer`, `worldpop`, `structures`, `fire`, `wetlands`,
`schools` and `osm`. The tribal areas and the 2020 blocks are in
`census`, as `tiger-2026-aiarelated` and `tiger-2020-block`.
`https://catalog.geomermaids.com/catalog.json` is the root that links
them all, with a browser for people. Each
collection links its files, its PMTiles archive, its styles and an
`AGENTS.md`.

A collection extent that crosses the antimeridian is written the STAC
way, with west > east: `[172.4, 14.5, -52.6, 83.3]` is North America
including the Aleutians, not the world minus North America. Read such a
box as two ranges, [west, 180] and [-180, east], and split it the same
way before filtering a `bbox` column with it.
