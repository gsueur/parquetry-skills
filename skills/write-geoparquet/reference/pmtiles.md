# A PMTiles archive beside the GeoParquet

GeoParquet is for queries. A browser map needs vector tiles: one PMTiles
archive per layer, next to the Parquet file, read with range requests like
it. A Portolan collection pairs the two (the archive is its visual asset).

What follows is how the parquetry archives are built (GAUL, CORINE,
Census TIGER/Line) and what went wrong on the way.

## The tiler

[tylertoo](https://github.com/geoparquet-io/tylertoo) reads GeoParquet
directly and writes PMTiles. Use the release binary, pinned to a version
and checked against the release's sha256: the PyPI package does not expose
the options below.

```bash
tylertoo tiles in.parquet out.pmtiles --layer-name l2 \
  --min-zoom 3 --max-zoom 10 \
  --no-density-drop --polygon-thinning 0 \
  --include-property iso3_code --include-property gaul2_name \
  --report report.json --force
```

- **Coverages need `--no-density-drop --polygon-thinning 0`.** The
  defaults drop polygons to meet a per-zoom budget: fine for buildings,
  wrong for admin units, districts or land cover, which must tile the land
  without holes.
- **Read the report, and fail on loss.** A tile over the size cap (500 KB)
  loses features with only a log line. Check `oversized_tiles` and
  `encode_dropped_features` per zoom in the report, and refuse to publish
  when either is non-zero. The fixes, in order: fewer properties
  (`--include-property`), a later minimum zoom, aggregation (below).
- **Measured on GAUL L2** (45,524 districts): every property at zoom 0
  overflowed. Five properties and minimum zoom 3 fit, with 0 loss.
- Max zoom 10 suits admin boundaries, 12 suits districts and land cover
  polygons. Each zoom past that roughly quadruples the tile count for
  little gain: MapLibre overzooms the last level.
- tylertoo reads lon/lat (CRS84) or Web Mercator only. NAD83 (EPSG:4269)
  can be relabelled CRS84 for the tiles, since the two are within 2 m in
  the conterminous US: `ST_SetCRS(geometry::GEOMETRY, 'OGC:CRS84')`. Keep
  the GeoParquet in its own CRS. Transform projected data (EPSG:3035) for
  real.

## Styling baked into the tiles

Put what the style needs in the features, so any client draws the layer
with no lookup table:

- **Categorical data with an official palette** (CORINE): add `color`
  (the hex) and `label` to every feature. The style is then
  `"fill-color": ["get", "color"]`.
- **Coverages with no natural colour** (districts, admin units): add
  `color_index`, a greedy graph colouring where no two neighbours share a
  value. Find neighbours with `ST_DWithin` on geometries simplified to
  about 100 m, colour the most-connected first. Cap it at the palette
  size (six for the US districts): the rare district that needs a seventh
  takes the colour least used among its neighbours. Add it to the tiles
  only: the GeoParquet keeps the source's columns.
- Publish the matching MapLibre style JSON next to the archive, with an
  absolute `pmtiles://https://...` source URL.

## Too dense for the small scales: aggregate on H3

A coverage of millions of small polygons does not fit coarse tiles at
all. CORINE: 2.4 million polygons, about 18,000 per tile at zoom 6; past
the cap the tiler dropped up to 89 % of a tile's features. Neither
simplification nor dissolving helps: simplification keeps the count, and
CORINE never has two neighbours of the same class to dissolve. A raster
generalization through GDAL worked but looked like a raster.

What worked: H3 cells for the small zooms, the polygons for the large
ones, joined into one archive (as Fields of the World does with A5
cells).

1. **Sample once, finely.** Every resolution 9 cell (about 0.1 km2) takes
   the class of the polygon holding its centre, with the DuckDB `h3`
   community extension:
   `h3_polygon_wkb_to_cells(ST_AsWKB(part), 9)`. It takes polygons only:
   `ST_Dump` multipolygons first, or it silently returns no cell.
2. **Do not simplify the polygons before sampling.** Simplified one by
   one, neighbours overlap: 0.13 % of the cells landed in two classes on
   France. Check that no cell is sampled twice.
3. **Aggregate up.** `h3_cell_to_parent(cell, r)` for each coarser
   resolution: the dominant class, its share, each group's share, and the
   share of the cell the data covers. Children of one parent are
   near-equal in area, so counts are area shares.
4. **One resolution per zoom band**, a cell 3 to 7 pixels wide across the
   band. CORINE: z0-2 r3, z3 r4, z4-5 r5, z6 r6, z7-8 r7, then the
   polygons z9-12. Tile each band with `--verbatim` (cells must not be
   simplified or dropped), then join them:
   `tylertoo pyramid out.pmtiles --band 0-2:r3.pmtiles:cells --band ... --band 9-12:polygons.pmtiles:clc_2018`.
5. **Publish the cells as a table too.** The aggregate is a useful
   dataset by itself (`clc_2018_h3.parquet`, 79 MB): land cover shares of
   a whole country in seconds.

Cost on all of Europe: 36 min on a laptop (30 of them sampling), 7.4 GB
peak memory, a 2.2 GB archive. On a GitHub runner the whole build took
114 min: give the job a 180 min limit.

## Hosting

- `Content-Type: application/vnd.pmtiles`, range requests, the same CORS
  headers as Parquet (`Content-Range`, `ETag` exposed).
- A browser revalidates with `If-None-Match`. If a Worker or proxy fronts
  the bucket, test a conditional range request before publishing: see
  `publishing.md`, "Mistakes we made".
- Record in the manifest, per archive: layer names, zooms, properties,
  tile count, bytes, sha256 and the tiler version.
