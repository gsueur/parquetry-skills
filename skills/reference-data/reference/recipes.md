# Tested query patterns

Every block below runs as written in the DuckDB CLI (1.5 or later) against
the live files, and CI runs them every week. Change the `SET VARIABLE`
lines at the top to adapt a block. Each block starts with the setup it
needs.

Times are for a home connection. Most of the time is spent downloading the
row groups the bbox filter keeps, so a cloud machine is faster.

## Point to context

Admin units and flood zone for a point in the US. For any location, the
script `scripts/locate.py` does this and more in one call.

<!-- test: point-context -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
SET VARIABLE lon = -79.935;
SET VARIABLE lat = 32.776;

-- 1. The country: GAUL L0 boxes only (no geometry read, under 1 s).
SET VARIABLE iso3 = (
  SELECT any_value(iso3_code)
  FROM read_parquet('https://parquetry.geomermaids.com/gaul/2024/GAUL_2024_L0_derived.parquet')
  WHERE bbox.xmin <= getvariable('lon') AND bbox.xmax >= getvariable('lon')
    AND bbox.ymin <= getvariable('lat') AND bbox.ymax >= getvariable('lat'));
-- If two countries' boxes hold the point, repeat step 2 for each.

-- 2. The admin units, from that country's L2 file.
SELECT gaul0_name, gaul1_name, gaul2_name, gaul2_code
FROM read_parquet('https://parquetry.geomermaids.com/gaul/2024/country=' || getvariable('iso3') || '/L2.parquet')
WHERE bbox.xmin <= getvariable('lon') AND bbox.xmax >= getvariable('lon')
  AND bbox.ymin <= getvariable('lat') AND bbox.ymax >= getvariable('lat')
  AND ST_Intersects(geometry, ST_Point(getvariable('lon'), getvariable('lat')));

-- 3. The FEMA deliveries whose rectangle holds the point. The index stores
--    rectangles, so near a county line two can match: read them all, the
--    zone pieces say which county the point is in.
SET VARIABLE nfhl = (
  SELECT list('https://parquetry.geomermaids.com/nfhl/latest/' || path)
  FROM read_parquet('https://parquetry.geomermaids.com/nfhl/latest/counties.parquet')
  WHERE xmin <= getvariable('lon') AND xmax >= getvariable('lon')
    AND ymin <= getvariable('lat') AND ymax >= getvariable('lat'));
SELECT county, state, fema_update_date, flood_zone, zone_subtype, risk, static_bfe
FROM read_parquet(getvariable('nfhl'))
WHERE bbox.xmin <= getvariable('lon') AND bbox.xmax >= getvariable('lon')
  AND bbox.ymin <= getvariable('lat') AND bbox.ymax >= getvariable('lat')
  AND ST_Intersects(geometry, ST_Point(getvariable('lon'), getvariable('lat')));
```

An empty `nfhl` list, or no row from the last query, means no FEMA
delivery maps the point: report "unmapped", not "no flood risk".

## Composition of an area

"What is the predominant land use in Hérault, France?" The département is
a GAUL L2 unit. CORINE is in EPSG:3035, so the area moves to 3035, never
the CORINE polygons. About 20 s.

Result (2026-10): vineyards (221) are the largest class at 23.8 %, but
forest and semi-natural areas (group 3) cover 49 % against 39 % for
agriculture (group 2). Report both readings.

<!-- test: area-composition -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
SET geometry_always_xy = true;

-- 1. The area, from GAUL, moved to EPSG:3035.
CREATE TABLE aoi AS
SELECT ST_Transform(geometry, 'OGC:CRS84', 'EPSG:3035') AS geom
FROM read_parquet('https://parquetry.geomermaids.com/gaul/2024/country=FRA/L2.parquet')
WHERE gaul2_name = 'Hérault';
SET VARIABLE ext = (SELECT ST_Extent_Agg(geom) FROM aoi);

-- 2. CORINE polygons in the extent, clipped to the area.
CREATE TABLE lc AS
SELECT c.Code_18 AS code, ST_Area(ST_Intersection(c.Shape, a.geom)) / 1e4 AS ha
FROM read_parquet('https://parquetry.geomermaids.com/clc/2018/country=FR/clc_2018.parquet') c, aoi a
WHERE c.bbox.xmin <= ST_XMax(getvariable('ext')) AND c.bbox.xmax >= ST_XMin(getvariable('ext'))
  AND c.bbox.ymin <= ST_YMax(getvariable('ext')) AND c.bbox.ymax >= ST_YMin(getvariable('ext'))
  AND ST_Intersects(c.Shape, a.geom);

-- 3. By class, and by level-1 group.
SELECT code, round(sum(ha)) AS ha, round(100 * sum(ha) / (SELECT sum(ha) FROM lc), 1) AS pct
FROM lc GROUP BY code ORDER BY ha DESC LIMIT 10;
SELECT left(code, 1) AS group_1, round(100 * sum(ha) / (SELECT sum(ha) FROM lc), 1) AS pct
FROM lc GROUP BY 1 ORDER BY pct DESC;
```

Check the total against the area (`ST_Area(geom)` in `aoi`): CORINE
covers land and inland water fully, so a gap above a few percent means a
filter went wrong.

## Overlay count

"How many buildings can be impacted by a 100-year flood in Eastern
Massachusetts?" Three choices to state in the answer:

- Eastern Massachusetts = Essex, Middlesex, Suffolk, Norfolk, Plymouth,
  Bristol, Barnstable, Dukes and Nantucket counties (Worcester is Central).
- 100-year flood = `risk = '1 percent flood zone'`.
- Impacted = the building footprint touches the zone.

It reads about 300 MB of flood zones and 220 MB of buildings, a few
minutes on a home connection.

<!-- test: overlay-count slow -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;

-- 1. The FEMA deliveries of the area. Counties missing here have no FEMA
--    data: list them in the answer as unmapped.
CREATE TABLE dl AS
SELECT path, county, fema_update_date, xmin, ymin, xmax, ymax
FROM read_parquet('https://parquetry.geomermaids.com/nfhl/latest/counties.parquet')
WHERE state = 'MA'
  AND county IN ('Essex', 'Middlesex', 'Suffolk', 'Norfolk', 'Plymouth',
                 'Bristol', 'Barnstable', 'Dukes', 'Nantucket');
SELECT county, fema_update_date FROM dl ORDER BY county;

-- 2. The 1% annual chance zones. NAD83 and WGS84 differ by about 1 m here:
--    the cast drops the CRS tag so the zones join with OSM.
SET VARIABLE files = (SELECT list('https://parquetry.geomermaids.com/nfhl/latest/' || path) FROM dl);
CREATE TABLE fz AS
SELECT county, geometry::GEOMETRY AS geom
FROM read_parquet(getvariable('files'))
WHERE risk = '1 percent flood zone';

-- 3. The buildings in the deliveries' extent.
SET VARIABLE x0 = (SELECT min(xmin) FROM dl);
SET VARIABLE x1 = (SELECT max(xmax) FROM dl);
SET VARIABLE y0 = (SELECT min(ymin) FROM dl);
SET VARIABLE y1 = (SELECT max(ymax) FROM dl);
CREATE TABLE b AS
SELECT osm_type, osm_id, geometry AS geom
FROM read_parquet('https://parquetry.geomermaids.com/osm/latest/country=US/state=US-MA/buildings.parquet')
WHERE bbox.xmin <= getvariable('x1') AND bbox.xmax >= getvariable('x0')
  AND bbox.ymin <= getvariable('y1') AND bbox.ymax >= getvariable('y0');

-- 4. Buildings touching a zone, once each, by county delivery.
CREATE TABLE hit AS
SELECT DISTINCT b.osm_type, b.osm_id, fz.county
FROM b JOIN fz ON ST_Intersects(b.geom, fz.geom);
SELECT county, count(*) AS buildings FROM hit GROUP BY county ORDER BY buildings DESC;
SELECT count(DISTINCT (osm_type, osm_id)) AS buildings_total FROM hit;
```

For "how many people", OSM has no population per building: say so rather
than estimate. For the share of buildings, divide by the buildings inside
the counties, not inside the extent: join `b` with the GAUL L2 polygons of
the counties first.

## Length inside an area

"How many km of power lines of 100 kV and more cross Lombardy?" Lines are
clipped to the region, and lengths are measured in EPSG:3035. Outside
Europe, use the local UTM zone.

<!-- test: length-in-area -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
SET geometry_always_xy = true;

CREATE TABLE aoi AS
SELECT geometry AS geom
FROM read_parquet('https://parquetry.geomermaids.com/gaul/2024/country=ITA/L1.parquet')
WHERE gaul1_name ILIKE 'Lombard%';
SET VARIABLE ext = (SELECT ST_Extent_Agg(geom) FROM aoi);

SELECT l.voltage_kv,
       round(sum(ST_Length(ST_Transform(ST_Intersection(l.geometry, a.geom),
                                        'OGC:CRS84', 'EPSG:3035'))) / 1000) AS km
FROM read_parquet('https://parquetry.geomermaids.com/gmwid/latest/power_line.parquet') l, aoi a
WHERE l.country = 'IT'
  AND l.bbox.xmin <= ST_XMax(getvariable('ext')) AND l.bbox.xmax >= ST_XMin(getvariable('ext'))
  AND l.bbox.ymin <= ST_YMax(getvariable('ext')) AND l.bbox.ymax >= ST_YMin(getvariable('ext'))
  AND l.voltage_kv >= 100 AND l.lifecycle = 'active'
  AND ST_Intersects(l.geometry, a.geom)
GROUP BY l.voltage_kv ORDER BY l.voltage_kv DESC;
```

`power_line` holds both overhead lines and cables (`line` column). A line
with several circuits counts once here: use `power_circuit` for circuit
km.

## Nearest features

"Which substations are within 5 km of this site?" The search square is
padded in degrees, then distances are exact on the sphere.

<!-- test: nearest -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
SET VARIABLE lon = 4.8357;
SET VARIABLE lat = 45.7640;
SET VARIABLE km = 5;
-- Degrees of padding: latitude is about 111 km per degree, longitude less.
SET VARIABLE dy = getvariable('km') / 111.0;
SET VARIABLE dx = getvariable('km') / (111.0 * cos(radians(getvariable('lat'))));

SELECT * FROM (
  SELECT name, operator, voltage_kv, origin,
         round(ST_Distance_Sphere(ST_Centroid(geometry),
                                  ST_Point(getvariable('lon'), getvariable('lat')))) AS metres
  FROM read_parquet('https://parquetry.geomermaids.com/gmwid/latest/power_substation.parquet')
  WHERE bbox.xmin <= getvariable('lon') + getvariable('dx')
    AND bbox.xmax >= getvariable('lon') - getvariable('dx')
    AND bbox.ymin <= getvariable('lat') + getvariable('dy')
    AND bbox.ymax >= getvariable('lat') - getvariable('dy'))
WHERE metres <= getvariable('km') * 1000
ORDER BY metres;
```

Near a city this returns every distribution substation: add
`AND voltage_kv >= 63` (or the threshold the question implies) for the
transmission grid only. `ST_Distance_Sphere` takes points. For lines and polygons, measure in a
projected CRS: `ST_Distance(ST_Transform(geometry, 'OGC:CRS84', 'EPSG:3035'), ...)`
in Europe, the UTM zone elsewhere.

## Tag a list of points

Add country and district to a set of locations. Replace the `VALUES` with
`read_csv('sites.csv')`. The countries come from the L0 boxes, then only
their L2 files are read.

<!-- test: tag-points -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;

CREATE TABLE sites AS
SELECT * FROM (VALUES ('Lyon', 4.8357, 45.7640),
                      ('Nairobi', 36.8219, -1.2921),
                      ('Charleston', -79.935, 32.776)) t(site, lon, lat);

-- 1. Candidate countries, from the L0 boxes only.
CREATE TABLE boxes AS
SELECT iso3_code, bbox
FROM read_parquet('https://parquetry.geomermaids.com/gaul/2024/GAUL_2024_L0_derived.parquet');
SET VARIABLE files = (
  SELECT list(DISTINCT 'https://parquetry.geomermaids.com/gaul/2024/country=' || iso3_code || '/L2.parquet')
  FROM sites s JOIN boxes b
    ON b.bbox.xmin <= s.lon AND b.bbox.xmax >= s.lon
   AND b.bbox.ymin <= s.lat AND b.bbox.ymax >= s.lat);

-- 2. The exact unit, from those countries' L2 files.
CREATE TABLE units AS
SELECT iso3_code, gaul0_name, gaul1_name, gaul2_name, gaul2_code, geometry
FROM read_parquet(getvariable('files'));
SELECT s.site, u.iso3_code, u.gaul1_name, u.gaul2_name, u.gaul2_code
FROM sites s LEFT JOIN units u ON ST_Intersects(u.geometry, ST_Point(s.lon, s.lat))
ORDER BY s.site;
```

A site with no unit is at sea or on a coast the generalised boundaries
miss: match it to the nearest unit within a few hundred metres, and say
so.

## Per-unit statistics

"Installed wind capacity per French région." GMWID rows carry `country`,
so the filter prunes before any geometry. Each plant is assigned to the
région that holds its centroid.

<!-- test: per-unit -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;

CREATE TABLE regions AS
SELECT gaul1_name, geometry
FROM read_parquet('https://parquetry.geomermaids.com/gaul/2024/country=FRA/L1.parquet');

CREATE TABLE wind AS
SELECT name, output_mw, ST_Centroid(geometry) AS pt
FROM read_parquet('https://parquetry.geomermaids.com/gmwid/latest/power_plant.parquet')
WHERE country = 'FR' AND source = 'wind' AND lifecycle = 'active';

SELECT r.gaul1_name, count(*) AS farms, round(sum(w.output_mw)) AS mw,
       count(*) FILTER (WHERE w.output_mw IS NULL) AS farms_without_output
FROM wind w JOIN regions r ON ST_Intersects(r.geometry, w.pt)
GROUP BY r.gaul1_name ORDER BY mw DESC NULLS LAST;
```

Report `farms_without_output`: OSM leaves the output of many plants
blank, so the MW total is a floor, not the installed capacity.
