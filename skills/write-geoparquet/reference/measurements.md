# Measurements behind the rules

All on the parquetry datasets, DuckDB 1.5.x, pyarrow 22, 2026-09 and
2026-10. Remote reads over HTTPS from a home connection unless stated.

## Row groups

| File | Before | After | Effect |
|---|---|---|---|
| GAUL `country=USA/L2` (3,145 counties) | 1 group, 69 MB | 32 groups, largest 2.1 MB (4 MiB WKB cap, zstd 19) | Point lookup 40 to 60 s → 2.1 s |
| GAUL world L2 (45,524 units) | 24 groups, up to 42 MB | 190 groups, up to 6.2 MB | Point lookup 12 s → 3.2 s |
| GAUL world L0 (272 countries) | 1 group, 286 MB | 67 groups (one country each when larger than the cap) | A country no longer costs the world |
| NFHL Orleans view, one window | 149.7 MiB read | 40.8 MiB (16 MiB cap), 28.4 MiB (8 MiB cap) | Read volume follows the cap; page index added 0.01 % |

DuckDB row group sizes, asked versus written, on a 45,524-row file: asking
for 256, 1,000 or 2,048 rows all gave 23 groups of about 1,979 rows; 3,000
and 5,000 gave 12; 20,000 gave 3. The floor is 2,048 rows, and
`ROW_GROUP_SIZE_BYTES` does not lower it.

## Spatial filter without bbox

NFHL Charleston county file (EPSG:4269, 20,480-row groups, Hilbert
sorted), one point:

| Query | Time |
|---|---|
| `bbox` filter only | 1.1 s |
| `bbox` filter and `ST_Intersects` | 5 s (geometry of the kept groups) |
| `ST_Intersects` alone | 18 s (every group fetched) |

DuckDB 1.5.6 does not use the native GEOMETRY row-group statistics to
prune a spatial predicate. The explicit `bbox` filter is what prunes.

## FLOAT bbox against DOUBLE bounds

The same bbox filter, DuckDB 1.5.6, remote, FLOAT `bbox` columns:

| File | Bounds | Time |
|---|---|---|
| Geoconnex `epa_wqp` (113 groups) | literals (DECIMAL) | 1.8 s |
| | `::DOUBLE` | 19.1 s |
| | `::FLOAT` | 2.9 s |
| GMWID `power_substation`, 5 km around Lyon | `lon + dx` (DOUBLE) | 10.9 s |
| | `(lon + dx)::FLOAT` | 1.7 s |

Compared with a DOUBLE, the FLOAT column is cast and its statistics are
not used. FLOAT keeps the column half the size; the rule for readers is to
cast computed bounds, widened by 1e-4 degree against rounding.

## Compression

| Level | Size versus level 3 | Write time | Reads |
|---|---|---|---|
| zstd 15 | about 3 % smaller | 3 to 12x level 3 | unchanged |
| zstd 19 | 16 to 19 % smaller on NFHL county files (80.9 → 68.2 MB), 13 to 15 % on GMWID layers (power_line 598 → 506 MB) | 2.4 to 4x level 15 | about 15 % slower |

WKB doubles dominate geometry columns and compress poorly. `PARQUET_VERSION
V2` data pages gained nothing.

## Subdivision

NFHL Middlesex county, a 951,116-vertex flood zone: DuckDB `ST_Subdivide`
at 100 vertices cut it in 5.4 s, valid polygons only, area preserved to
1e-14. Rows grow by an order of magnitude: the national NFHL is 5.8 million
zones in 95.6 million pieces. Each piece's bbox is then close to the
piece, so a bbox filter or DuckDB's `SPATIAL_JOIN` R-tree discards most
candidates before any vertex is tested. The nfhl-geoparquet-workshop
benchmark (`nfhl bench --stage subdivide`) times the join before and after
on your own machine.

## Page index

GDAL 3.13 writes a page index by default; DuckDB and gpio write none. A
pyarrow-written page index on a covering column is ignored by DuckDB 1.5.6
reads: the whole row group is fetched. Do not rely on it for pruning.
