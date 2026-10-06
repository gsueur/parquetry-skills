# Changelog

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
