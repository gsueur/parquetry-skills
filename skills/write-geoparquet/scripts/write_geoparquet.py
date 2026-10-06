# /// script
# requires-python = ">=3.10"
# dependencies = ["duckdb>=1.5", "pyarrow>=22", "geoarrow-pyarrow>=0.2"]
# ///
"""Write an optimized GeoParquet file the way the parquetry datasets are written.

    uv run write_geoparquet.py INPUT OUTPUT [options]

INPUT is anything DuckDB reads: a Parquet file, URL or glob, or a file
ST_Read opens (Shapefile, GeoPackage, GeoJSON, FlatGeobuf...). Or pass
--sql with a query and INPUT '-'.

What it does, in order:
  1. optional ST_MakeValid, optional ST_Subdivide into pieces of at most
     --subdivide vertices (with a piece_id column),
  2. a per-row `bbox` struct (FLOAT, rounded outward), sorted along a Hilbert
     curve over the data's extent,
  3. native Parquet GEOMETRY with the CRS: lon/lat is left untagged (OGC:CRS84
     by definition), a projected CRS is kept, and a GeoParquet 2.0 `geo` footer
     declares the bbox column as the covering,
  4. row groups capped by bytes (--group-mib, default about 16 groups per
     file, 0.25 to 8 MiB each) with pyarrow + geoarrow, because
     DuckDB writes none under 2,048 rows, zstd (--zstd),
  5. verify(): one `geo` key, covering, every bbox bounds its geometry, the
     declared extent equals the data's, native GEOMETRY type, groups under cap.

With --partition-by COL, OUTPUT is a directory: one COL=<value>/<name>.parquet
per value, and a _manifest.json with rows, bytes, row groups and sha256.

The table is held in memory once per output file: fine up to a few GB per
file. Partition anything bigger.
"""

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

import duckdb

LONLAT = {None, "", "EPSG:4326", "OGC:CRS84", "CRS84", "EPSG:4269"}
TYPE_NAMES = {
    "POINT": "Point", "LINESTRING": "LineString", "POLYGON": "Polygon",
    "MULTIPOINT": "MultiPoint", "MULTILINESTRING": "MultiLineString",
    "MULTIPOLYGON": "MultiPolygon", "GEOMETRYCOLLECTION": "GeometryCollection",
}
# Outer bound after narrowing to FLOAT: each value is pushed away from the
# box centre by far more than float32's rounding error.
BBOX = """struct_pack(
    xmin := (ST_XMin(geometry) - abs(ST_XMin(geometry)) * 1e-6 - 1e-9)::FLOAT,
    ymin := (ST_YMin(geometry) - abs(ST_YMin(geometry)) * 1e-6 - 1e-9)::FLOAT,
    xmax := (ST_XMax(geometry) + abs(ST_XMax(geometry)) * 1e-6 + 1e-9)::FLOAT,
    ymax := (ST_YMax(geometry) + abs(ST_YMax(geometry)) * 1e-6 + 1e-9)::FLOAT) AS bbox"""


def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def source_sql(inp: str, sql: str | None) -> str:
    if sql:
        return sql
    if re.search(r"\.parquet$|\*", inp, re.I):
        return f"SELECT * FROM read_parquet({q(inp)})"
    return f"SELECT * FROM ST_Read({q(inp)})"


def geometry_column(con, geom: str | None) -> tuple[str, str | None]:
    """The geometry column and the CRS its type carries."""
    cols = con.execute("DESCRIBE src").fetchall()
    for name, typ, *_ in cols:
        if (geom is None or name == geom) and typ.startswith("GEOMETRY"):
            m = re.match(r"GEOMETRY\('(.+)'\)", typ)
            return name, m.group(1) if m else None
    sys.exit(f"no GEOMETRY column{f' named {geom}' if geom else ''} in the input: "
             f"{[(c[0], c[1]) for c in cols]}")


def projjson(con, crs: str) -> dict:
    """PROJJSON for the footer. DuckDB has no function for it, but its V2
    writer puts it in the footer of a probe file."""
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "probe.parquet"
        con.execute(f"COPY (SELECT ST_SetCRS(ST_Point(0, 0), {q(crs)}) AS g) "
                    f"TO {q(str(probe))} (FORMAT PARQUET, GEOPARQUET_VERSION 'V2')")
        geo = con.execute(f"SELECT decode(value) FROM parquet_kv_metadata({q(str(probe))}) "
                          "WHERE decode(key) = 'geo'").fetchone()[0]
    return json.loads(geo)["columns"]["g"]["crs"]


def prepare(con, geom: str, crs: str | None, make_valid: bool, subdivide: int | None) -> None:
    """View `prep`: the input with one `geometry` column, valid and cut if asked,
    tagged with its CRS (ST_MakeValid and ST_Subdivide drop the tag)."""
    g = f'"{geom}"'
    expr = f"ST_MakeValid({g})" if make_valid else g
    tag = (lambda e: f"({e})::GEOMETRY") if crs in LONLAT else (lambda e: f"ST_SetCRS({e}, {q(crs)})")
    rest = f'* EXCLUDE ("{geom}")'
    if subdivide:
        con.execute(f"""CREATE OR REPLACE TEMP VIEW prep AS
            SELECT * EXCLUDE (d), d.path[1] - 1 AS piece_id, {tag('d.geom')} AS geometry
            FROM (SELECT {rest}, unnest(ST_Dump(ST_Subdivide({expr}, {subdivide}))) AS d FROM src)
            WHERE NOT ST_IsEmpty(d.geom) AND ST_Dimension(d.geom) > 0""")
    else:
        con.execute(f"""CREATE OR REPLACE TEMP VIEW prep AS
            SELECT {rest}, {tag(expr)} AS geometry FROM src
            WHERE {g} IS NOT NULL AND NOT ST_IsEmpty({g})""")


def rewrite(src: Path, dest: Path, group_bytes: int | None, max_rows: int, zstd: int) -> int:
    """Cut a DuckDB-written file into row groups of at most group_bytes
    (geometry WKB plus the row's share of the other columns), same row order.
    Without a cap, aim at 16 groups, between 0.25 and 8 MiB each: a small
    file in one group cannot be pruned at all. Returns the cap used.

    pyarrow 22 with geoarrow-pyarrow registered keeps the native GEOMETRY
    logical type, a projected CRS, the geospatial statistics and the `geo`
    footer. Plain pyarrow writes a BLOB: verify() refuses that.
    """
    import geoarrow.pyarrow  # noqa: F401  registers the geoarrow.wkb extension type
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    table = pq.read_table(src)
    wkb = pa.chunked_array([c.storage for c in table.column("geometry").chunks])
    other = (table.nbytes - wkb.nbytes) / max(table.num_rows, 1)
    if group_bytes is None:
        group_bytes = int(min(8 << 20, max(256 << 10, table.nbytes / 16)))
    cuts, size, rows = [0], 0.0, 0
    for i, n in enumerate(pc.binary_length(wkb).to_pylist()):
        if rows and (size + n + other > group_bytes or rows >= max_rows):
            cuts.append(i)
            size, rows = 0.0, 0
        size += n + other
        rows += 1
    cuts.append(table.num_rows)

    meta = pq.ParquetFile(src).metadata.schema
    leaves = [meta.column(k) for k in range(len(meta))]
    with pq.ParquetWriter(
            dest, table.schema, compression="zstd", compression_level=zstd,
            write_statistics=True, data_page_size=1 << 20,
            use_dictionary=[c.path for c in leaves
                            if c.physical_type == "BYTE_ARRAY" and c.path != "geometry"],
            use_byte_stream_split=[c.path for c in leaves
                                   if c.physical_type in ("FLOAT", "DOUBLE")]) as w:
        for a, b in zip(cuts, cuts[1:]):
            w.write_table(table.slice(a, b - a), row_group_size=b - a)
    return group_bytes


def write_one(con, where: str, out: Path, crs: str | None, crs_json: dict | None,
              group_bytes: int | None, max_rows: int, zstd: int) -> dict:
    n, xmin, ymin, xmax, ymax, types = con.execute(f"""
        SELECT count(*), min(ST_XMin(geometry)), min(ST_YMin(geometry)),
               max(ST_XMax(geometry)), max(ST_YMax(geometry)),
               list(DISTINCT ST_GeometryType(geometry)::VARCHAR)
        FROM prep WHERE {where}""").fetchone()
    if not n:
        sys.exit(f"{out}: no rows")
    col = {"encoding": "WKB",
           "geometry_types": sorted(TYPE_NAMES.get(t.upper(), t) for t in types),
           "bbox": [xmin, ymin, xmax, ymax],
           "covering": {"bbox": {k: ["bbox", k] for k in ("xmin", "ymin", "xmax", "ymax")}}}
    if crs_json:
        col["crs"] = crs_json
    geo = json.dumps({"version": "2.0.0", "primary_column": "geometry",
                      "columns": {"geometry": col}})
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".tmp.parquet")
    box = f"ST_Extent(ST_MakeEnvelope({xmin!r}, {ymin!r}, {xmax!r}, {ymax!r}))"
    # GEOPARQUET_VERSION 'NONE': DuckDB would otherwise add a second `geo`
    # key beside ours, and readers silently keep one or the other. The
    # geometry column is still written with the native GEOMETRY type.
    con.execute(f"""
        COPY (SELECT * EXCLUDE (geometry), {BBOX}, geometry FROM prep WHERE {where}
              ORDER BY ST_Hilbert(geometry, {box}))
        TO {q(str(tmp))} (FORMAT PARQUET, GEOPARQUET_VERSION 'NONE', COMPRESSION ZSTD,
             COMPRESSION_LEVEL 1, ROW_GROUP_SIZE 1048576, KV_METADATA {{geo: {q(geo)}}})""")
    cap = rewrite(tmp, out, group_bytes, max_rows, zstd)
    tmp.unlink()
    verify(con, out, crs, cap, max_rows)
    groups, largest = con.execute(f"""
        SELECT count(*), max(b) FROM (SELECT row_group_id, sum(total_compressed_size) AS b
        FROM parquet_metadata({q(str(out))}) GROUP BY 1)""").fetchone()
    return {"file": str(out), "rows": n, "bytes": out.stat().st_size, "row_groups": groups,
            "largest_row_group_bytes": largest, "group_cap_bytes": cap,
            "sha256": hashlib.sha256(out.read_bytes()).hexdigest()}


def verify(con, f: Path, crs: str | None, group_bytes: int, max_rows: int) -> None:
    """Refuse a file whose footer, bbox, type or row groups are wrong. A bad
    footer fails silently otherwise: the file reads back fine everywhere."""
    p = q(str(f))
    rp = f"read_parquet({p}, hive_partitioning = false)"
    errors = []
    kv = con.execute(f"SELECT decode(key), decode(value) FROM parquet_kv_metadata({p})").fetchall()
    geos = [v for k, v in kv if k == "geo"]
    if len(geos) != 1:
        errors.append(f"{len(geos)} 'geo' footer keys, want 1")
    else:
        col = json.loads(geos[0])["columns"]["geometry"]
        if col.get("covering", {}).get("bbox") != {k: ["bbox", k] for k in ("xmin", "ymin", "xmax", "ymax")}:
            errors.append(f"covering missing or malformed: {col.get('covering')}")
        actual = con.execute(f"""SELECT min(ST_XMin(geometry)), min(ST_YMin(geometry)),
            max(ST_XMax(geometry)), max(ST_YMax(geometry)) FROM {rp}""").fetchone()
        if [round(v, 6) for v in col["bbox"]] != [round(v, 6) for v in actual]:
            errors.append(f"declared extent {col['bbox']} != data {list(actual)}")
    outside = con.execute(f"""SELECT count(*) FROM {rp}
        WHERE bbox.xmin > ST_XMin(geometry) OR bbox.ymin > ST_YMin(geometry)
           OR bbox.xmax < ST_XMax(geometry) OR bbox.ymax < ST_YMax(geometry)""").fetchone()[0]
    if outside:
        errors.append(f"{outside} geometries outside their bbox")
    logical = con.execute(f"SELECT logical_type FROM parquet_schema({p}) "
                          "WHERE name = 'geometry'").fetchone()[0]
    if not (logical and str(logical).startswith("GeometryType")):
        errors.append(f"geometry is {logical!r}, not the native GEOMETRY type")
    elif crs not in LONLAT and "crs=<null>" in str(logical):
        errors.append(f"the {crs} CRS was lost from the GEOMETRY type")
    over = con.execute(f"""SELECT count(*) FROM (
        SELECT row_group_id, any_value(row_group_num_rows) AS n, sum(total_uncompressed_size) AS b
        FROM parquet_metadata({p}) GROUP BY 1) WHERE n > 1 AND (b > {group_bytes} * 1.5 OR n > {max_rows})""").fetchone()[0]
    if over:
        errors.append(f"{over} row group(s) over the cap")
    if errors:
        sys.exit(f"{f}: verification failed\n  " + "\n  ".join(errors))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("input", help="file, URL or glob DuckDB can read; '-' with --sql")
    ap.add_argument("output", help="output .parquet, or a directory with --partition-by")
    ap.add_argument("--sql", help="a query to read instead of INPUT")
    ap.add_argument("--geometry", help="geometry column (default: the first GEOMETRY column)")
    ap.add_argument("--crs", help="CRS when the input does not carry one, e.g. EPSG:2154")
    ap.add_argument("--make-valid", action="store_true", help="ST_MakeValid every geometry")
    ap.add_argument("--subdivide", type=int, metavar="N",
                    help="cut geometries into pieces of at most N vertices (adds piece_id)")
    ap.add_argument("--partition-by", metavar="COL", help="one file per value of COL")
    ap.add_argument("--name", default="data", help="file name inside each partition")
    ap.add_argument("--group-mib", type=float,
                    help="uncompressed MiB per row group (default: about 16 groups per "
                         "file, 0.25 to 8 MiB each)")
    ap.add_argument("--max-rows", type=int, default=131_072,
                    help="rows per row group at most (default 131072)")
    ap.add_argument("--zstd", type=int, default=15, help="zstd level (default 15; 19 is smaller, slower)")
    a = ap.parse_args()

    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;")
    con.execute("SET geometry_always_xy = true;")
    con.execute(f"CREATE TEMP VIEW src AS {source_sql(a.input, a.sql)}")
    geom, carried = geometry_column(con, a.geometry)
    crs = a.crs or carried
    if crs is None:
        print("warning: the input carries no CRS and --crs was not given: assuming lon/lat "
              "(OGC:CRS84)", file=sys.stderr)
    prepare(con, geom, crs, a.make_valid, a.subdivide)
    crs_json = None if crs in LONLAT else projjson(con, crs)
    group_bytes = int(a.group_mib * (1 << 20)) if a.group_mib else None
    out = Path(a.output)

    if not a.partition_by:
        print(json.dumps(write_one(con, "true", out, crs, crs_json, group_bytes,
                                   a.max_rows, a.zstd), indent=2))
        return
    keys = [r[0] for r in con.execute(
        f'SELECT DISTINCT "{a.partition_by}" FROM prep ORDER BY 1').fetchall()]
    bad = [k for k in keys if k is None or "/" in str(k) or str(k) != str(k).strip()]
    if bad:
        sys.exit(f"{a.partition_by} values unfit for a path: {bad[:10]}")
    files = []
    for k in keys:
        e = write_one(con, f'"{a.partition_by}" = {q(str(k))}',
                      out / f"{a.partition_by}={k}" / f"{a.name}.parquet",
                      crs, crs_json, group_bytes, a.max_rows, a.zstd)
        e["file"] = str(Path(e["file"]).relative_to(out))
        files.append({a.partition_by: k, **e})
        print(f"  {e['file']}: {e['rows']:,} rows, {e['bytes'] / 1e6:.1f} MB, "
              f"{e['row_groups']} row group(s)", file=sys.stderr)
    (out / "_manifest.json").write_text(json.dumps(
        {"partition_by": a.partition_by, "files": files,
         "rows": sum(f["rows"] for f in files), "bytes": sum(f["bytes"] for f in files)},
        indent=2, default=str) + "\n")
    print(json.dumps({"files": len(files), "rows": sum(f["rows"] for f in files),
                      "manifest": str(out / "_manifest.json")}, indent=2))


if __name__ == "__main__":
    main()
