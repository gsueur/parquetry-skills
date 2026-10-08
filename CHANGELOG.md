# Changelog

## Unreleased

### reference-data

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
