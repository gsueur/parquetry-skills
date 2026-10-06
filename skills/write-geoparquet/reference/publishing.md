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
