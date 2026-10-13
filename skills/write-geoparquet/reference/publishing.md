# Publishing GeoParquet for remote readers

## Headers

| Object | Content-Type | Cache-Control |
|---|---|---|
| Parquet at a dated or versioned URL | `application/vnd.apache.parquet` | `public, max-age=31536000, immutable` |
| Parquet at a moving URL (`latest/`) | `application/vnd.apache.parquet` | `public, max-age=300` |
| Manifests, indexes, `snapshots.json`, catalogs | `application/json` or Parquet | `public, max-age=300` |

- Mark a URL `immutable` only if its bytes will never change. If they do,
  a browser that cached the old file can combine its old footer with new
  pages. A CDN in front of the bucket must then be purged as well.
- The server must answer `Range` requests with `206` and a correct
  `Content-Range`. Readers fetch the footer first, then row groups.
- For browser readers (DuckDB-WASM, web maps), CORS must allow `GET` and
  `HEAD` with a `Range` header and expose `Content-Range`,
  `Content-Length`, `ETag` and `Accept-Ranges`.

## Object storage

- On Cloudflare R2, a server-side copy (`rclone copy` or `copyto` within
  the bucket) drops `Content-Type` and `Cache-Control`, and
  `--metadata-set` on a self-copy does not restore them. To rename or move,
  upload again from local disk with `--header-upload`.
- Upload the data first, then the manifest and index, then the catalog, so
  nothing ever points at a file that is not there.
- Use `rclone copy`, never `sync`, against a bucket other jobs also write.
- Readers that glob (`s3://bucket/x/*/*.parquet`) need an S3-compatible
  endpoint that answers LIST. Plain HTTPS cannot expand a glob.

## Documentation readers and agents need

- A README with the layout (paths, partition keys), the CRS, the columns,
  the row group size, the `bbox` filter rule and the licence and credit.
- An `AGENTS.md` with the same facts, written as instructions, with one
  working query per access pattern.
- An `ATTRIBUTION.txt` beside the data when the licence asks for a notice
  to travel with the files.
- A Portolan/STAC catalog makes the dataset findable and machine-readable.
  The `portolan` skills (`portolan-bootstrap`, `register-catalog`) cover it.
  Validate with `rashid`.
- A PMTiles archive beside the file for maps: `pmtiles.md`.

## Catalog extents that cross the antimeridian

A plain min/max of longitudes turns data on both sides of 180 degrees
(Alaska's Aleutians, Guam, American Samoa, Fiji) into a box around the
whole world: `[-179.2, ..., 179.9, ...]`. Readers take it for "global",
and a registry map centred the OSM North America marker on France, the
box's centre. STAC writes such a box with west > east:
`[172.4, 14.5, -52.6, 83.3]`.

Compute it from the data, not from the file's min/max:

1. Collect the longitude intervals the rows cover, from the `bbox` column.
   A row whose box is wider than 180 degrees is a multipolygon with parts
   on both sides: `ST_Dump` it and take each part's interval.
2. Merge intervals closer than about 1 degree, so a few thousand islands
   become a few intervals.
3. The extent is the circle minus its largest empty arc. When that arc
   does not contain 180, write west > east.
4. Clamp to [-180, 180]: a FLOAT `bbox` rounded outward can overshoot by
   1e-4.

A catalog-level extent is the same operation over the collections' boxes,
each box with west > east read as two intervals. A dataset whose rows each
span the world (a global footprint) yields the world: leave those rows out
when they would hide the real extent, and say so in the description.

## Mistakes we made

- A footer that held `<function geo_metadata at 0x...>` instead of the
  metadata, three builds running: every file read back fine. The verify
  step exists because of it.
- Two `geo` keys in one footer (DuckDB `GEOPARQUET_VERSION 'V2'` plus our
  own `KV_METADATA`). pyarrow and gpio showed one, so it went unnoticed.
- `gpio add bbox-metadata` re-encoded the whole file at DuckDB's default
  compression level just to add one footer key (geoparquet-io issue #1141).
  Patch the footer or rewrite deliberately.
- An index whose geometry was the file's bounding rectangle, documented as
  the outline. Readers placed points in the wrong county near borders.
- A download that was an HTML page. census.gov's firewall answers a
  rejected request with a small "Request Rejected" page and **HTTP 200**,
  so `curl -f` passes. Check the bytes (a zip starts with `PK`, a
  GeoPackage with `SQLite format 3`), retry with a pause, then fail
  loudly.
- A Cloudflare Worker in front of R2 passed the browser's `If-None-Match`
  value to R2's `onlyIf` as a string, quotes included, and answered 500 to
  every revalidation. Files loaded once, then the PMTiles maps broke on
  reload. Pass the request headers object (`onlyIf: request.headers`), and
  read an R2 object without `body` as a failed condition: 304 for
  `If-None-Match`, 412 otherwise. Test a conditional range request
  (`curl -H 'If-None-Match: "<etag>"' -r 0-99`) after any change to the
  Worker.
- Collection extents computed as a plain min/max: a catalog for North
  America declared the whole world (see the antimeridian section above).
