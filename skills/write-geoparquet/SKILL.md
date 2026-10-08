---
name: write-geoparquet
description: Write optimized GeoParquet files that read fast over HTTP, the way the Geomermaids parquetry datasets are built. Use when converting vector data (Shapefile, GeoPackage, GeoJSON, FlatGeobuf, PostGIS export, plain Parquet) to GeoParquet, when publishing a dataset to object storage for DuckDB, GDAL or browser readers, when a GeoParquet file is slow to query remotely, or when choosing row groups, sorting, compression, partitioning, CRS handling or polygon subdivision. Covers GeoParquet 2.0 with native Parquet GEOMETRY, the bbox covering column, Hilbert sorting, byte-capped row groups, verification and hosting headers.
---

# Writing optimized GeoParquet

A GeoParquet file is fast over HTTP when a reader can skip almost all of
it. Everything below serves that: rows sorted so neighbours sit together,
a per-row bounding box the reader filters on, row groups small enough that
skipping them matters, and a footer that says so correctly.

Each rule comes from measurements on the parquetry datasets (OSM North
America, GMWID, FAO GAUL, FEMA NFHL, CORINE). The numbers are in
`reference/measurements.md`.

## Quick path

`scripts/write_geoparquet.py` applies every rule and verifies the result:

```bash
# A file DuckDB can read (Parquet, Shapefile, GeoPackage, GeoJSON, a URL):
uv run scripts/write_geoparquet.py input.gpkg output.parquet

# One file per value of a column, plus _manifest.json with sha256:
uv run scripts/write_geoparquet.py admin.shp out/ --partition-by iso3 --name L2

# Heavy polygons for point lookups: pieces of at most 100 vertices.
uv run scripts/write_geoparquet.py zones.parquet zones_100.parquet --make-valid --subdivide 100

# Any query:
uv run scripts/write_geoparquet.py - out.parquet --sql "SELECT * FROM read_parquet('in/*.parquet') WHERE kind = 'x'"
```

Options: `--crs EPSG:xxxx` when the input carries none, `--group-mib`
(default: about 16 groups per file, 0.25 to 8 MiB each), `--max-rows`
(default 131,072), `--zstd` (default 15). It
holds one output file in memory: partition anything above a few GB.

Use the script unless the person needs a different toolchain. Then apply
the rules below by hand and run the checks in "Verify" on the result.

## The rules

### 1. GeoParquet 2.0, native GEOMETRY, one `geo` key

- Write the geometry with the native Parquet `GEOMETRY` logical type
  (GeoParquet 2.0). DuckDB 1.5 does this; plain pyarrow writes a BLOB.
- A bare DuckDB 1.5 `COPY ... (FORMAT parquet)` writes GeoParquet **1.0.0**
  metadata. Always set `GEOPARQUET_VERSION`.
- To declare a bbox covering, write the whole `geo` value yourself through
  `KV_METADATA` and set `GEOPARQUET_VERSION 'NONE'`. With `'V2'` plus your
  own key, the footer carries two `geo` keys, and each reader silently keeps
  one or the other.

### 2. CRS

- Lon/lat data: leave the GEOMETRY type untagged. Untagged means OGC:CRS84
  (lon, lat) by the spec. EPSG:4326 declares lat, lon axis order, which is
  not what the bytes hold.
- Projected data: keep the tag (`ST_SetCRS(geom, 'EPSG:3035')`) and put the
  PROJJSON in the `geo` footer. DuckDB has no function that returns
  PROJJSON. Write a one-point probe file with `GEOPARQUET_VERSION 'V2'` and
  read its footer (the script does this).
- `ST_MakeValid`, `ST_Subdivide` and some other functions drop the CRS tag.
  Set it again as the last step.

### 3. A `bbox` column, and say that readers must use it

- Add `bbox STRUCT(xmin FLOAT, ymin FLOAT, xmax FLOAT, ymax FLOAT)` per row.
  Narrowing to FLOAT can move a value inward, so round each one outward
  (the script's `BBOX` expression). A bbox that does not contain its
  geometry silently drops rows from every filtered query.
- Declare it as the `covering` in the `geo` footer.
- Tell readers to compare it with FLOAT values or literals. DuckDB 1.5
  casts a FLOAT column compared with a DOUBLE and then prunes no row group:
  a computed bound (`lon + dx`, a Python float parameter) is 5 to 10 times
  slower than the same bound cast with `::FLOAT`.
- **DuckDB 1.5.6 does not prune row groups from a spatial predicate on the
  geometry.** Measured on an NFHL county file: `ST_Intersects` alone took
  18 s, the same query with a bbox filter 1 s. Document in the dataset's
  README and AGENTS.md that queries must filter on `bbox` first.

### 4. Sort along a Hilbert curve

`ORDER BY ST_Hilbert(geometry, <extent of the data>)`. Neighbours then share
row groups, so each group's bbox statistics are tight and a window query
touches few groups. Use the extent of the data in the file, not the world.

### 5. Cap row groups by bytes, not rows

- A reader fetches whole row groups. One group = no skipping. This is the
  biggest single lever.
- DuckDB will not write a row group under 2,048 rows, rounds requests to a
  power-of-two multiple of 1,024, and `ROW_GROUP_SIZE_BYTES` does not
  change that. Administrative units, flood zones and land cover polygons
  are few and heavy, so DuckDB leaves them in one huge group.
- Write the sorted file with DuckDB, then cut it with pyarrow and
  `geoarrow-pyarrow` (imported, so the extension type is registered) into
  groups of a fixed byte budget. geoarrow keeps the GEOMETRY type, a
  projected CRS and the `geo` footer.
- Budgets that worked: 4 to 8 MiB uncompressed for heavy polygons, about
  50,000 to 130,000 rows for points and small lines. A small file needs
  smaller groups, not one: aim at a dozen or more groups per file, down to
  a few hundred KB each.
- Measured: GAUL `country=USA/L2` went from one 69 MB group to 32 groups of
  at most 2 MB, and a point lookup over HTTP from 40 to 60 s to 2 s.

### 6. Subdivide heavy polygons for point lookups

- A flood zone can carry a million vertices, and a point test walks every
  one. `ST_Subdivide(geom, 100)` then `ST_Dump` cuts it into pieces whose
  bbox does most of the work. Keep the source id and add `piece_id`
  (0 for the first piece of each source feature).
- Trade-offs to state in the dataset docs: rows grow by an order of
  magnitude, area attributes are wrong on pieces, `count(*)` counts pieces
  (count features with `piece_id = 0`), and a map shows the cut lines.
- Skip it for data that is only rendered or downloaded whole.

### 7. Compression and encodings

- zstd 15 by default. zstd 19 is 13 to 19 % smaller on geometry-heavy
  files, at 2.4 to 4 times the write time and about 15 % slower reads.
  Use 19 for files written once and read many times.
- Dictionary encoding for string columns, `BYTE_STREAM_SPLIT` for floats.
- Do not count on a page index: DuckDB 1.5.6 ignores it and fetches the
  whole row group.

### 8. Partition by what readers filter on

- Split by the key most queries name (country, state, county, theme), into
  files of a few MB to a few hundred MB. A reader that knows its region
  names one file. HTTPS cannot list a directory.
- Publish an index next to the files: one row per file with its key, bbox,
  row count, bytes and sha256 (as a small Parquet file or a
  `_manifest.json`). Readers find the files there. Store the bbox columns,
  and say clearly if the index geometry is only a rectangle.
- For globs, readers need an S3-compatible endpoint that answers LIST.

## Verify

The footer is the part that fails silently: a file with a broken `geo` key
reads back fine everywhere. Check every file before publishing:

1. Exactly one `geo` key in the footer. Read the keys one by one with
   `parquet_kv_metadata`, not through pyarrow, which collapses duplicates.
2. The covering names the four `bbox` fields.
3. No geometry lies outside its own `bbox`.
4. The declared extent equals the data's extent.
5. The geometry column has the GEOMETRY logical type
   (`parquet_schema(...).logical_type` starts with `GeometryType`), with the
   CRS if projected.
6. No multi-row group over the byte cap.
7. Row count and a sample of rows equal the source.

`write_geoparquet.py` runs checks 1 to 6 and refuses to finish on any
failure.

## Publish

See `reference/publishing.md` for headers, caching, catalogs and the
mistakes we made. In short:

- `Content-Type: application/vnd.apache.parquet`. Range requests must
  work, and CORS must expose `Content-Range`, `Content-Length`, `ETag` and
  `Accept-Ranges` for browser readers.
- `Cache-Control: immutable` only on URLs whose bytes never change. Use a
  short `max-age` on `latest/` paths, manifests and indexes.
- Ship an `AGENTS.md` and a README that tell readers the layout, the CRS,
  the `bbox` filter rule and the licence. A Portolan/STAC catalog makes the
  dataset findable: the `portolan` skills cover that.
