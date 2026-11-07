# Changelog

## 0.5.0 (2026-11-07)

### reference-data

- Three datasets, thirteen in all:
  - USGS PAD-US 4.1: protected and conservation lands, Combined and the
    five feature classes, with decoded manager, designation, GAP status and
    public access.
  - USDOT National Address Database release 24: 99 million address points,
    one file per state, a normalized `full_address`, and its coverage.
  - Gazetteer: the Census Gazetteer 2026 (17 layers keyed by `GEOID`) and
    GeoNames (13.5 million names worldwide, `cities1000`).
- Three tested recipes: protected land at a site (PAD-US), geocode an
  address (NAD), place name to coordinates (Census with the ACS population,
  and GeoNames).
- Pitfalls: PAD-US areas overlap in Combined too, so never sum them (Grand
  County, Utah: 99.8% summed, 73.7% as a union); NAD coverage gaps; the
  NAD S3 glob needs `hive_partitioning = false`.
- Maps: PAD-US Combined, the NAD coverage on H3 cells, GeoNames places.

## 0.4.0 (2026-11-07)

### reference-data

- Three datasets, ten in all:
  - Census ACS 2020-2024: 33 measures with their margins of error by
    state, county, place, tract, block group and ZIP code area, as tables
    keyed by `GEOID` and joined to the TIGER/Line outlines.
  - FEMA National Risk Index 1.20: risk of 18 natural hazards by tract,
    county, state and tribal area, with FEMA's scores and ratings.
  - Natural Earth 5.1.2: world countries, states, places, coastlines,
    rivers, lakes, ports, airports and time zones at three scales.
- Three tested recipes:
  - Population near a point: ACS tracts by centroid, counts with combined
    margins, a population-weighted income. About 1 s.
  - Natural hazard risk at a point: the NRI tract, its composite and its
    five highest hazards through `UNPIVOT`. About 1.5 s.
  - Largest places near a point, from Natural Earth. Under 1 s.
- Pitfalls: ACS margins and medians, NRI scores against ratings (a tract
  can score 95 for wildfire and be rated "Relatively Moderate"), Natural
  Earth's `-99` ISO codes and populations.
- Maps: the PMTiles archives of ACS, NRI and Natural Earth (one per file,
  and Natural Earth's basemaps), with their layers and styling.
- Catalogs: `nri`, `natural-earth`, ACS under `census`, and
  catalog.geomermaids.com, the root that links them all.
- OSM: `latest/` is the only rolling version, and the first build of each
  month is kept for 12 months under `osm/<YYYY-MM-DD>/` (#7, #8).

### Tests

- CI reads the CRS checks through `execute()`: DuckDB 2.0 dropped
  `Relation.fetchone()` (#6).

## 0.3.0 (2026-10-13)

### reference-data

- Census TIGER/Line 2026, the seventh dataset: US House, State Senate and
  State House districts of the November 2026 elections, and the states
  redrawn since 2024. A tested recipe (election districts at a point), and
  `locate.py` returns the three districts for US points.
- CORINE on H3 cells (`clc_2018_h3.parquet`): land cover group shares of a
  whole country in seconds. A tested recipe: all of Spain in about 4 s,
  where clipping the polygons ran out of memory; Hérault within half a
  point of the polygons.
- Maps: the PMTiles archives of GAUL, CORINE and Census, their layers and
  the properties that carry the styling (`color`, `color_index`).
- Catalogs: how to read a collection extent with west > east (crossing
  the antimeridian), now published for Census, Geoconnex and OSM.

### write-geoparquet

- `reference/pmtiles.md`: a PMTiles archive beside the GeoParquet with
  tylertoo, the settings that keep a coverage without holes, failing on
  oversized tiles, styling in the tiles, and H3 aggregation for layers too
  dense for the small zooms (how the CORINE archive is built).
- Publishing: catalog extents that cross the antimeridian, computed from
  the data; two new mistakes (an HTML error page served with HTTP 200,
  and a Worker that answered 500 to conditional requests).
- Fix: `write_geoparquet.py` relabelled NAD83 (EPSG:4269) data as CRS84.
  It now keeps any CRS other than WGS84, as the NFHL and Census files do.

- Geoconnex (Internet of Water), the sixth dataset: US rivers head to outlet
  and their network, dams, gages, watersheds, aquifers, water systems, and
  4.6 million water monitoring sites. Two tested recipes: along a river
  (dams on the Colorado and its tributaries, by walking the network
  upstream) and water monitoring sites near a point.
- Fix: the nearest-features recipe measured distances with lon and lat
  swapped (`ST_Distance_Sphere` reads lat, lon unless
  `geometry_always_xy` is set) and returned 2,779 substations within 5 km
  of central Lyon instead of 3,555.
- Faster: computed bbox bounds are cast to FLOAT. Compared with DOUBLE
  bounds, DuckDB 1.5 casts the FLOAT `bbox` column and prunes no row
  group: the nearest recipe drops from 10.9 s to 1.7 s, the length-in-area
  recipe (380 kV lines in Lombardy) from 157 s to 16 s. Documented as a
  rule in both skills.

## 0.2.1 (2026-10-06)

First tagged release.

### reference-data

Answers spatial questions with the Geomermaids parquetry datasets, queried
in place with DuckDB: FAO GAUL 2024 (world), GMWID infrastructure (world),
FEMA NFHL flood zones (US), CORINE Land Cover 2018 (Europe) and
OpenStreetMap (US, Canada, Mexico).

- The method: definitions first, coverage checks, efficient reads, CRS
  alignment, and an answer with definitions, gaps, data dates and credits.
- Seven query patterns tested weekly against the live data: point context,
  area composition, overlay count, length in area, nearest features,
  tagging a list of points, per-unit statistics.
- `scripts/locate.py`: everything the datasets say about one lon/lat.

### write-geoparquet

Writes optimized GeoParquet the way the parquetry datasets are written.

- The rules, each with the measurement behind it: GeoParquet 2.0 with native
  GEOMETRY and one `geo` key, CRS handling, the `bbox` covering, Hilbert
  order, byte-capped row groups, subdivision, compression, partitioning,
  verification, publishing.
- `scripts/write_geoparquet.py`: applies the rules to anything DuckDB reads
  and refuses to finish unless six checks pass.

### Repository

- README illustrations: the Eastern Massachusetts and Hérault answers,
  mapped from the same files.
