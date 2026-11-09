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

## Election districts

"Which districts do I vote in at this address?" The US House, State
Senate and State House districts of the November 2026 elections, about
3 s. The files are NAD83: an untagged `ST_Point` compares with them
directly, but cast with `geometry::GEOMETRY` to join them with CRS84 data.

<!-- test: election-districts -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
SET VARIABLE lon = -97.7431;
SET VARIABLE lat = 30.2672;

CREATE TABLE d AS
SELECT 'US House' AS chamber, NAMELSAD AS district, GEOID, geometry
FROM read_parquet('https://parquetry.geomermaids.com/census/tiger/2026/legislative/cd120.parquet')
WHERE bbox.xmin <= getvariable('lon') AND bbox.xmax >= getvariable('lon')
  AND bbox.ymin <= getvariable('lat') AND bbox.ymax >= getvariable('lat')
UNION ALL
SELECT 'State Senate', NAMELSAD, GEOID, geometry
FROM read_parquet('https://parquetry.geomermaids.com/census/tiger/2026/legislative/sldu.parquet')
WHERE bbox.xmin <= getvariable('lon') AND bbox.xmax >= getvariable('lon')
  AND bbox.ymin <= getvariable('lat') AND bbox.ymax >= getvariable('lat')
UNION ALL
SELECT 'State House', NAMELSAD, GEOID, geometry
FROM read_parquet('https://parquetry.geomermaids.com/census/tiger/2026/legislative/sldl.parquet')
WHERE bbox.xmin <= getvariable('lon') AND bbox.xmax >= getvariable('lon')
  AND bbox.ymin <= getvariable('lat') AND bbox.ymax >= getvariable('lat');

SELECT chamber, district, GEOID FROM d
WHERE ST_Intersects(geometry, ST_Point(getvariable('lon'), getvariable('lat')));
```

Austin city hall: Congressional District 10, State Senate District 14,
State House District 49. A `ZZ` or `ZZZ` code means no district there
(usually water). Nebraska has no State House row: its one chamber is in
`sldu`. To say whether the US House district changed since 2024, look the
`GEOID` up under `districts` in
`https://census.geomermaids.com/redistricting.json`: the overlap (IoU)
with its closest 2024 district, 1.0 when unchanged. Only the ten redrawn
states are listed there. TX-10 (`4810`) scores 0.26: it was largely
redrawn.

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

## Land cover of a large area, from H3 cells

For a whole country or a large region, the polygon recipe reads and
clips millions of polygons: on all of Spain it ran out of memory on a
laptop. The H3 table answers the level-1 group shares from resolution 7
cells (5.2 km2): Spain in about 4 s, Hérault in 1 s (forest 49.2 %,
agriculture 39.0 %, where the polygons say 49.3 % and 39.1 %).

<!-- test: h3-composition -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
INSTALL h3 FROM community; LOAD h3;

CREATE TABLE aoi AS
SELECT geometry AS geom
FROM read_parquet('https://parquetry.geomermaids.com/gaul/2024/country=FRA/L2.parquet')
WHERE gaul2_name = 'Hérault';

-- The resolution 7 cells whose centre is in the area. The H3 function
-- takes polygons, not multipolygons: dump the parts first. Simplifying the
-- outline to about 500 m first barely changes the cells (Spain: 95,535
-- against 95,518) and takes 48 s down to under 1 s.
CREATE TABLE cells AS
SELECT DISTINCT h3_h3_to_string(unnest(h3_polygon_wkb_to_cells(ST_AsWKB(p.geom), 7))) AS h3
FROM (SELECT unnest(ST_Dump(ST_SimplifyPreserveTopology(geom, 0.005))) AS p FROM aoi);

CREATE TABLE lc AS
SELECT c.*
FROM read_parquet('https://parquetry.geomermaids.com/clc/2018/clc_2018_h3.parquet') c
JOIN cells USING (h3)
WHERE c.h3_res = 7;

-- Shares weighted by how much of each cell CORINE covers. The _pct
-- columns are UTINYINT: cast before multiplying.
SELECT count(*) AS cells,
       round(sum(forest_pct::INT * coverage_pct) / sum(coverage_pct), 1) AS forest,
       round(sum(agricultural_pct::INT * coverage_pct) / sum(coverage_pct), 1) AS agricultural,
       round(sum(artificial_pct::INT * coverage_pct) / sum(coverage_pct), 1) AS artificial,
       round(sum(wetland_pct::INT * coverage_pct) / sum(coverage_pct), 1) AS wetland,
       round(sum(water_pct::INT * coverage_pct) / sum(coverage_pct), 1) AS water
FROM lc;
```

The cells give the group shares, and per cell only the dominant class:
`SELECT label, count(*) FROM lc GROUP BY 1 ORDER BY 2 DESC` counts cells
by dominant class, not area by class. For a class share (vineyards), and
for areas smaller than a few hundred km2, use the polygon recipe above.
For a country, read its L0 file: `country=ESP/L0_derived.parquet`.

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

For "how many people", OSM has no population per building: use USA
Structures (`POP_MEDIAN`) or the 2020 blocks, as in "Buildings and
residents inside an area" below. For the share of buildings, divide by the buildings inside
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
-- GMWID's bbox is FLOAT: FLOAT bounds keep row-group pruning (see datasets.md).
SET VARIABLE x0 = (ST_XMin(getvariable('ext')) - 1e-4)::FLOAT;
SET VARIABLE x1 = (ST_XMax(getvariable('ext')) + 1e-4)::FLOAT;
SET VARIABLE y0 = (ST_YMin(getvariable('ext')) - 1e-4)::FLOAT;
SET VARIABLE y1 = (ST_YMax(getvariable('ext')) + 1e-4)::FLOAT;

SELECT l.voltage_kv,
       round(sum(ST_Length(ST_Transform(ST_Intersection(l.geometry, a.geom),
                                        'OGC:CRS84', 'EPSG:3035'))) / 1000) AS km
FROM read_parquet('https://parquetry.geomermaids.com/gmwid/latest/power_line.parquet') l, aoi a
WHERE l.country = 'IT'
  AND l.bbox.xmin <= getvariable('x1') AND l.bbox.xmax >= getvariable('x0')
  AND l.bbox.ymin <= getvariable('y1') AND l.bbox.ymax >= getvariable('y0')
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
-- The bounds as FLOAT, like the bbox column, widened by 1e-4 degree so the
-- rounding never cuts a feature off. Compared with a DOUBLE, DuckDB casts
-- the column and skips no row group: 10.9 s instead of 1.7 s here.
SET VARIABLE x0 = (getvariable('lon') - getvariable('dx') - 1e-4)::FLOAT;
SET VARIABLE x1 = (getvariable('lon') + getvariable('dx') + 1e-4)::FLOAT;
SET VARIABLE y0 = (getvariable('lat') - getvariable('dy') - 1e-4)::FLOAT;
SET VARIABLE y1 = (getvariable('lat') + getvariable('dy') + 1e-4)::FLOAT;

SET geometry_always_xy = true;
SELECT * FROM (
  SELECT name, operator, voltage_kv, origin,
         round(ST_Distance_Sphere(ST_Centroid(geometry),
                                  ST_Point(getvariable('lon'), getvariable('lat')))) AS metres
  FROM read_parquet('https://parquetry.geomermaids.com/gmwid/latest/power_substation.parquet')
  WHERE bbox.xmin <= getvariable('x1') AND bbox.xmax >= getvariable('x0')
    AND bbox.ymin <= getvariable('y1') AND bbox.ymax >= getvariable('y0'))
WHERE metres <= getvariable('km') * 1000
ORDER BY metres;
```

Near a city this returns every distribution substation: add
`AND voltage_kv >= 63` (or the threshold the question implies) for the
transmission grid only. `ST_Distance_Sphere` takes points. For lines and polygons, measure in a
projected CRS: `ST_Distance(ST_Transform(geometry, 'OGC:CRS84', 'EPSG:3035'), ...)`
in Europe, the UTM zone elsewhere.

## Along a river

"Which dams are on the Colorado River, and on its tributaries?" Geoconnex
mainstems are whole rivers, head to outlet, each linked to the river it
flows into (`downstream_mainstem_id`). Dams and gages carry the
`mainstem_uri` of the river they sit on. Find the river by name, walk the
network upstream, then join.

<!-- test: river-network -->
```sql
INSTALL httpfs; LOAD httpfs;
SET VARIABLE river = 'Colorado River';

-- Several rivers share a name: list them and pick by size or place.
SELECT uri, primary_name, lengthkm, outlet_drainagearea_sqkm
FROM read_parquet('https://parquetry.geomermaids.com/geoconnex/latest/reference/mainstems.parquet')
WHERE primary_name = getvariable('river') AND NOT superseded
ORDER BY outlet_drainagearea_sqkm DESC LIMIT 5;
-- The Colorado of the Southwest (2,138 km, 557,743 km2), not the Texas one.
SET VARIABLE outlet = 'https://geoconnex.us/ref/mainstems/29559';

-- The network: four columns of 853,000 rivers, about 10 s.
CREATE TABLE net AS
SELECT uri, downstream_mainstem_id AS down, primary_name, lengthkm
FROM read_parquet('https://parquetry.geomermaids.com/geoconnex/latest/reference/mainstems.parquet')
WHERE NOT superseded;
CREATE TABLE basin AS
WITH RECURSIVE up(uri) AS (
  SELECT getvariable('outlet')
  UNION
  SELECT n.uri FROM net n JOIN up ON n.down = up.uri)
SELECT * FROM up;

SELECT d.name, n.primary_name AS river, round(d.drainage_area_sqkm) AS drainage_km2,
       d.mainstem_uri = getvariable('outlet') AS on_main_river, d.uri
FROM read_parquet('https://parquetry.geomermaids.com/geoconnex/latest/reference/dams.parquet') d
JOIN basin b ON d.mainstem_uri = b.uri
JOIN net n ON n.uri = d.mainstem_uri
ORDER BY on_main_river DESC, drainage_km2 DESC NULLS LAST;
```

406 dams on the Colorado's network, 17 on the main river (Morelos, Hoover,
Glen Canyon...). Only dams and gages that Geoconnex placed on a mainstem
carry `mainstem_uri`: about 21% of dams and half the gages. For every dam
in a basin whether it sits on a mapped river or not, use the watershed
polygons instead (`hu02` to `hu12`, by `huc` prefix) and a point-in-polygon
test.

## Water monitoring sites near a point

"Where is water quality measured near this site?" The Water Quality Portal
(EPA, USGS and states) and USGS monitoring locations, one file each. Every
`uri` resolves at geoconnex.us to the site's page and its data.

<!-- test: water-sites -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
SET geometry_always_xy = true;
SET VARIABLE lon = -71.0490;
SET VARIABLE lat = 42.3480;
SET VARIABLE km = 2;
SET VARIABLE x0 = (getvariable('lon') - getvariable('km') / (111.0 * cos(radians(getvariable('lat')))) - 1e-4)::FLOAT;
SET VARIABLE x1 = (getvariable('lon') + getvariable('km') / (111.0 * cos(radians(getvariable('lat')))) + 1e-4)::FLOAT;
SET VARIABLE y0 = (getvariable('lat') - getvariable('km') / 111.0 - 1e-4)::FLOAT;
SET VARIABLE y1 = (getvariable('lat') + getvariable('km') / 111.0 + 1e-4)::FLOAT;

CREATE TABLE sites AS
SELECT 'Water Quality Portal' AS source, uri, name, geometry
FROM read_parquet('https://parquetry.geomermaids.com/geoconnex/latest/providers/epa_wqp.parquet')
WHERE bbox.xmin <= getvariable('x1') AND bbox.xmax >= getvariable('x0')
  AND bbox.ymin <= getvariable('y1') AND bbox.ymax >= getvariable('y0')
UNION ALL
SELECT 'USGS monitoring location', uri, name, geometry
FROM read_parquet('https://parquetry.geomermaids.com/geoconnex/latest/providers/usgs_monitoring_locations.parquet')
WHERE bbox.xmin <= getvariable('x1') AND bbox.xmax >= getvariable('x0')
  AND bbox.ymin <= getvariable('y1') AND bbox.ymax >= getvariable('y0');

SELECT source, name, round(ST_Distance_Sphere(geometry, ST_Point(getvariable('lon'), getvariable('lat')))) AS metres, uri
FROM sites
WHERE ST_Distance_Sphere(geometry, ST_Point(getvariable('lon'), getvariable('lat'))) <= getvariable('km') * 1000
ORDER BY metres;
```

Boston Inner Harbor: 24 sites within 2 km, about 5 s. A USGS site usually
appears in both files (the WQP copy has `NWIS/USGS-<id>` in its `uri`, the
USGS one `monitoring-location/USGS-<id>`): count distinct site numbers
when the question is "how many".

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

## Population near a point

"How many people live within 5 km of this site, and what do they earn?"
ACS tracts whose centroid is within the distance, about 1 s. Say that it
counts whole tracts by their centroid; for a sharper figure use block
groups (`bg_geo.parquet`) or weight each tract by the share of its area
inside the circle.

<!-- test: population-near-point -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
SET VARIABLE lon = -71.0589;
SET VARIABLE lat = 42.3601;
SET VARIABLE km = 5;
SET VARIABLE dy = getvariable('km') / 111.0;
SET VARIABLE dx = getvariable('km') / (111.0 * cos(radians(getvariable('lat'))));
-- FLOAT bounds, like the bbox column, so row groups are skipped.
SET VARIABLE x0 = (getvariable('lon') - getvariable('dx') - 1e-4)::FLOAT;
SET VARIABLE x1 = (getvariable('lon') + getvariable('dx') + 1e-4)::FLOAT;
SET VARIABLE y0 = (getvariable('lat') - getvariable('dy') - 1e-4)::FLOAT;
SET VARIABLE y1 = (getvariable('lat') + getvariable('dy') + 1e-4)::FLOAT;

SET geometry_always_xy = true;
CREATE TABLE t AS
SELECT GEOID, NAME, population, population_moe, median_household_income,
       ST_Distance_Sphere(ST_Centroid(geometry),
                          ST_Point(getvariable('lon'), getvariable('lat'))) AS metres
FROM read_parquet('https://parquetry.geomermaids.com/census/acs/2024/tract_geo.parquet')
WHERE bbox.xmin <= getvariable('x1') AND bbox.xmax >= getvariable('x0')
  AND bbox.ymin <= getvariable('y1') AND bbox.ymax >= getvariable('y0');

-- Tracts whose centroid is within the distance. Counts add up, and their
-- MOE is the root of the summed squared MOEs; medians do not add up, so
-- the income is weighted by the population of the tracts that have one.
SELECT count(*) AS tracts,
       sum(population) AS population,
       round(sqrt(sum(population_moe ^ 2))) AS population_moe,
       round(sum(median_household_income * population)
             / sum(population) FILTER (WHERE median_household_income IS NOT NULL))
         AS weighted_median_income
FROM t
WHERE metres <= getvariable('km') * 1000;
```

Boston City Hall, 5 km: 143 tracts, 446,386 people (margin 5,793), a
population-weighted median household income of about $111,000. The
weighted median is an approximation; a true median of the area needs the
income distribution tables, which this dataset does not carry.

## Natural hazard risk at a point

"Which natural hazards threaten this site?" The NRI tract under the
point, its composite rating and its five highest hazards, about 1.5 s.
`UNPIVOT` turns the per-hazard columns (`<prefix>_RISKS`, `<prefix>_RISKR`)
into rows, and `hazards.parquet` names the prefixes.

<!-- test: hazard-risk-at-point -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
SET VARIABLE lon = -121.6219;
SET VARIABLE lat = 39.7596;
SET VARIABLE x = getvariable('lon')::FLOAT;
SET VARIABLE y = getvariable('lat')::FLOAT;

CREATE TABLE tract AS
SELECT * EXCLUDE (bbox, geometry)
FROM read_parquet('https://parquetry.geomermaids.com/nri/v1.20/tracts.parquet')
WHERE bbox.xmin <= getvariable('x') AND bbox.xmax >= getvariable('x')
  AND bbox.ymin <= getvariable('y') AND bbox.ymax >= getvariable('y')
  AND ST_Intersects(geometry, ST_Point(getvariable('lon'), getvariable('lat')));

-- One row per hazard: <PREFIX>_RISKS is the score, <PREFIX>_RISKR the rating.
CREATE TABLE per_hazard AS
SELECT s.TRACTFIPS, split_part(s.col, '_', 1) AS prefix, s.score, r.rating
FROM (UNPIVOT (SELECT TRACTFIPS, COLUMNS('^[A-Z]{4}_RISKS$') FROM tract)
      ON COLUMNS('_RISKS$') INTO NAME col VALUE score) AS s
JOIN (UNPIVOT (SELECT TRACTFIPS, COLUMNS('^[A-Z]{4}_RISKR$') FROM tract)
      ON COLUMNS('_RISKR$') INTO NAME col VALUE rating) AS r
  ON r.TRACTFIPS = s.TRACTFIPS AND split_part(r.col, '_', 1) = split_part(s.col, '_', 1);

SELECT t.TRACTFIPS, t.COUNTY, t.STATEABBRV, t.RISK_RATNG, round(t.RISK_SCORE, 1) AS risk_score,
       t.SOVI_RATNG, t.RESL_RATNG, h.Hazard, round(p.score, 1) AS hazard_score, p.rating
FROM tract AS t
JOIN per_hazard AS p USING (TRACTFIPS)
JOIN read_parquet('https://parquetry.geomermaids.com/nri/v1.20/hazards.parquet') AS h
  ON h.Prefix = p.prefix
ORDER BY p.score DESC NULLS LAST
LIMIT 5;
```

Paradise, California: composite risk "Relatively Low" (score 32.3), social
vulnerability "Relatively High". Wildfire leads with a score of 95.2,
rated "Relatively Moderate": the score is a national percentile among
tracts, the rating FEMA's class, and both belong in the answer. For a
county, read `counties.parquet` the same way with `STCOFIPS`.

## Largest places near a point

"What are the ten largest cities within 200 km?" Natural Earth's
populated places, about 0.6 s.

<!-- test: largest-places-near-point -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
SET VARIABLE lon = 4.8357;
SET VARIABLE lat = 45.7640;
SET VARIABLE km = 200;
SET VARIABLE dy = getvariable('km') / 111.0;
SET VARIABLE dx = getvariable('km') / (111.0 * cos(radians(getvariable('lat'))));
SET VARIABLE x0 = (getvariable('lon') - getvariable('dx') - 1e-4)::FLOAT;
SET VARIABLE x1 = (getvariable('lon') + getvariable('dx') + 1e-4)::FLOAT;
SET VARIABLE y0 = (getvariable('lat') - getvariable('dy') - 1e-4)::FLOAT;
SET VARIABLE y1 = (getvariable('lat') + getvariable('dy') + 1e-4)::FLOAT;

SET geometry_always_xy = true;
SELECT * FROM (
  SELECT NAME, ADM0NAME AS country, POP_MAX,
         round(ST_Distance_Sphere(geometry, ST_Point(getvariable('lon'), getvariable('lat'))) / 1000)
           AS km
  FROM read_parquet('https://parquetry.geomermaids.com/natural-earth/v5.1.2/10m/populated_places.parquet')
  WHERE bbox.xmin <= getvariable('x1') AND bbox.xmax >= getvariable('x0')
    AND bbox.ymin <= getvariable('y1') AND bbox.ymax >= getvariable('y0'))
WHERE km <= getvariable('km')
ORDER BY POP_MAX DESC
LIMIT 10;
```

Lyon: Lyon, Geneva (112 km), Grenoble, Lausanne, Saint-Étienne,
Clermont-Ferrand, Dijon, Besançon, Annecy, Roanne. `POP_MAX` is the
urban area population, not the municipality's, and `-99` when unknown.
Natural Earth lists 7,342 places worldwide, picked for map labels rather
than completeness: for every town in North America, use OSM `places`.

## Protected land at a site

"Is this site on protected land, and who manages it?" Every PAD-US area
under the point, about 1.5 s.

<!-- test: protected-land-at-point -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
SET VARIABLE lon = -109.5925;
SET VARIABLE lat = 38.7331;
SET VARIABLE x = getvariable('lon')::FLOAT;
SET VARIABLE y = getvariable('lat')::FLOAT;

-- Every PAD-US area under the point: fee land, designations on it, and the
-- proclamation boundaries around them. NAD83 like TIGER: an untagged point
-- compares with it directly.
SELECT Category, Unit_Nm, Mang_Name_Desc AS manager, Des_Tp_Desc AS designation,
       GAP_Sts AS gap, Pub_Access_Desc AS access
FROM read_parquet('https://parquetry.geomermaids.com/padus/v4.1/combined.parquet')
WHERE bbox.xmin <= getvariable('x') AND bbox.xmax >= getvariable('x')
  AND bbox.ymin <= getvariable('y') AND bbox.ymax >= getvariable('y')
  AND ST_Intersects(geometry, ST_Point(getvariable('lon'), getvariable('lat')))
ORDER BY Category, GAP_Sts;
```

Arches National Park: the fee land (National Park Service, GAP 1, open
access) and its proclamation boundary. Expect several rows: a designation
lies on fee land and a boundary encloses both. Report the fee row for
ownership and the strongest GAP status for protection; never add their
areas.

## Geocode an address

"Where is 1 Beacon Street, Boston?" The NAD file of the state, narrowed by
ZIP code, ranked by similarity to the normalized input, about 3 s.

<!-- test: geocode-address -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
-- The input normalized the way full_address is: upper case, no punctuation,
-- USPS abbreviations, '<number> <street>, <city>, <state> <zip>'.
SET VARIABLE q = '1 BEACON ST, BOSTON, MA 02108';

SELECT full_address, Longitude, Latitude, Placement, County
FROM read_parquet('https://parquetry.geomermaids.com/addresses/nad/r24/state=MA/addresses.parquet')
WHERE Zip_Code = '02108'
ORDER BY jaro_winkler_similarity(full_address, getvariable('q')) DESC
LIMIT 3;
```

`1 BEACON ST, BOSTON, MA 02108` matches exactly at (-71.06084, 42.35846).
A similarity below about 0.95 is a different address: say so rather than
return the nearest number. If the state has no NAD rows (HI, MI, MS, NH,
NV), fall back to OSM `buildings` addresses, then to the street.

## Place name to coordinates

"Where is Springfield?" Census places with their ACS population, and
GeoNames places, about 1 s.

<!-- test: place-name-lookup -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
-- US: the Census places, with their ACS population through GEOID.
SELECT 'census' AS source, g.NAME AS name, g.USPS AS region, a.population,
       g.INTPTLONG AS lon, g.INTPTLAT AS lat, g.GEOID AS id
FROM read_parquet('https://parquetry.geomermaids.com/gazetteer/census/2026/place.parquet') AS g
LEFT JOIN read_parquet('https://parquetry.geomermaids.com/census/acs/2024/place.parquet') AS a
  USING (GEOID)
WHERE g.NAME = 'Springfield city'
UNION ALL
-- Anywhere: GeoNames' places of 1,000 people or more.
SELECT 'geonames', name, country_code || '-' || admin1_name, population,
       longitude, latitude, geonameid::VARCHAR
FROM read_parquet('https://parquetry.geomermaids.com/gazetteer/geonames/latest/cities1000.parquet')
WHERE name = 'Springfield'
ORDER BY population DESC NULLS LAST, source
LIMIT 10;
```

Both sources agree: Springfield MO (about 170,000), MA, IL, OR, OH. Census
names carry the legal suffix ("Springfield city"); GeoNames gives the
region name and works outside the US. For a name with no population
(a mountain, a lake), use `geonames.parquet` and its `feature_code`.

## Population near a point, outside the US

"How many people live within 10 km of this site?" anywhere in the world,
from the WorldPop cells of the country, under 1 s. It counts whole cells
by their centre: good to a cell (about 2.5 km), not to a street. In the
US, use the ACS tracts above or the 2020 blocks below.

<!-- test: population-worldpop -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
SET VARIABLE iso3 = 'KEN';
SET VARIABLE lon = 36.8219;
SET VARIABLE lat = -1.2921;
SET VARIABLE km = 10;
SET VARIABLE dy = getvariable('km') / 111.0;
SET VARIABLE dx = getvariable('km') / (111.0 * cos(radians(getvariable('lat'))));
SET VARIABLE x0 = (getvariable('lon') - getvariable('dx') - 1e-4)::FLOAT;
SET VARIABLE x1 = (getvariable('lon') + getvariable('dx') + 1e-4)::FLOAT;
SET VARIABLE y0 = (getvariable('lat') - getvariable('dy') - 1e-4)::FLOAT;
SET VARIABLE y1 = (getvariable('lat') + getvariable('dy') + 1e-4)::FLOAT;

SET geometry_always_xy = true;
-- Cells whose centre is within the distance; lon, lat are the cell centre.
SELECT count(*) AS cells,
       round(sum(population)) AS population,
       round(sum(pop_0_14)) AS under_15,
       round(sum(pop_65_plus)) AS over_64,
       round(100 * sum(female) / sum(population), 1) AS female_pct
FROM read_parquet('https://parquetry.geomermaids.com/worldpop/R2025A/2025/country='
                  || getvariable('iso3') || '/worldpop_2025.parquet')
WHERE bbox.xmin <= getvariable('x1') AND bbox.xmax >= getvariable('x0')
  AND bbox.ymin <= getvariable('y1') AND bbox.ymax >= getvariable('y0')
  AND ST_Distance_Sphere(ST_Point(lon, lat), ST_Point(getvariable('lon'), getvariable('lat')))
      <= getvariable('km') * 1000;
```

Nairobi, 10 km: 54 cells, about 3.1 million people, 869,000 under 15 and
38,000 over 64. These are modelled estimates: round them in the answer.
For a radius across a border, read each country file, or the
`s3://parquetry/worldpop/R2025A/2025/country=*/` glob.

## Fire history at a site

"Has this site burned?" Every MTBS burned area since 1984 and every WFIGS
perimeter under the point, about 1.5 s.

<!-- test: fire-history-at-point -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
SET VARIABLE lon = -120.9520;
SET VARIABLE lat = 40.1396;
SET VARIABLE x = getvariable('lon')::FLOAT;
SET VARIABLE y = getvariable('lat')::FLOAT;

-- Large fires since 1984 (MTBS), then every WFIGS perimeter since 2016.
SELECT 'mtbs' AS source, incid_name AS name, incid_type AS type,
       ig_date::DATE AS started, round(burnbndac) AS acres
FROM read_parquet('https://parquetry.geomermaids.com/fire/mtbs/latest/mtbs_perimeters.parquet')
WHERE bbox.xmin <= getvariable('x') AND bbox.xmax >= getvariable('x')
  AND bbox.ymin <= getvariable('y') AND bbox.ymax >= getvariable('y')
  AND ST_Intersects(geometry, ST_Point(getvariable('lon'), getvariable('lat')))
UNION ALL
SELECT 'wfigs', poly_IncidentName, attr_IncidentTypeCategory,
       attr_FireDiscoveryDateTime::DATE, round(poly_GISAcres)
FROM read_parquet('https://parquetry.geomermaids.com/fire/wfigs/latest/all_since_2016.parquet')
WHERE bbox.xmin <= getvariable('x') AND bbox.xmax >= getvariable('x')
  AND bbox.ymin <= getvariable('y') AND bbox.ymax >= getvariable('y')
  AND ST_Intersects(geometry, ST_Point(getvariable('lon'), getvariable('lat')))
ORDER BY started;
```

Greenville, California: the Dixie fire of July 2021, in both sources
(963,309 acres in WFIGS, 979,722 in MTBS, which maps it from imagery).
WFIGS starts in practice in 2020 and MTBS lags a year or two and keeps
only large fires: before 2020 trust MTBS, for this year trust WFIGS
(`year_to_date`), for small fires `incidents_ytd` (points only). No row is
not proof that no fire ever burned there.

## Buildings and residents inside an area

"How many buildings and people were inside the Eaton fire perimeter?"
USA Structures footprints touching the perimeter, by occupancy, about 5 s.
The same pattern works for a flood zone or a PAD-US unit.

<!-- test: structures-in-perimeter -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
SET VARIABLE fire = 'Eaton';
SET VARIABLE state = 'CA';
SET VARIABLE year = 2025;

-- 1. The perimeter, from WFIGS (2020 on; use MTBS for older fires).
CREATE TABLE p AS
SELECT poly_IncidentName AS name, poly_GISAcres AS acres, geometry AS geom,
       bbox.xmin AS x0, bbox.ymin AS y0, bbox.xmax AS x1, bbox.ymax AS y1
FROM read_parquet('https://parquetry.geomermaids.com/fire/wfigs/latest/all_since_2016.parquet')
WHERE poly_IncidentName = getvariable('fire')
  AND attr_POOState = 'US-' || getvariable('state')
  AND year(attr_FireDiscoveryDateTime) = getvariable('year');
SELECT name, round(acres) AS acres FROM p;
SET VARIABLE x0 = (SELECT min(x0) FROM p);
SET VARIABLE x1 = (SELECT max(x1) FROM p);
SET VARIABLE y0 = (SELECT min(y0) FROM p);
SET VARIABLE y1 = (SELECT max(y1) FROM p);

-- 2. Footprints inside it (FLOAT bounds read from bbox, so row groups are skipped).
CREATE TABLE b AS
SELECT BUILD_ID, OCC_CLS, POP_MEDIAN, geometry
FROM read_parquet('https://parquetry.geomermaids.com/structures/latest/state='
                  || getvariable('state') || '/structures.parquet')
WHERE bbox.xmin <= getvariable('x1') AND bbox.xmax >= getvariable('x0')
  AND bbox.ymin <= getvariable('y1') AND bbox.ymax >= getvariable('y0');

-- 3. Buildings touching the perimeter, by occupancy, with ORNL's residents.
SELECT b.OCC_CLS, count(DISTINCT b.BUILD_ID) AS buildings, round(sum(b.POP_MEDIAN)) AS residents
FROM b JOIN p ON ST_Intersects(p.geom, b.geometry)
GROUP BY ALL ORDER BY buildings DESC;
```

Eaton fire, January 2025 (14,021 acres): 10,644 residential buildings with
about 25,800 residents by ORNL's model, 172 commercial, 80 education. This
counts buildings inside the perimeter, not damage. The 2020 blocks give
24,295 people for the same perimeter (next recipe): quote the census
figure for people and Structures for buildings.

## Population inside an area, from 2020 blocks

"How many people live inside this polygon?" The 2020 blocks whose interior
point falls inside, about 1.5 s. Blocks are the finest US count, much
sharper than tracts for a small or irregular area.

<!-- test: blocks-in-polygon -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
SET VARIABLE state = 'CA';
SET VARIABLE fire = 'Eaton';
SET VARIABLE year = 2025;

-- 1. Any area as a polygon: here a fire perimeter.
CREATE TABLE area AS
SELECT geometry AS geom, bbox.xmin AS x0, bbox.ymin AS y0, bbox.xmax AS x1, bbox.ymax AS y1
FROM read_parquet('https://parquetry.geomermaids.com/fire/wfigs/latest/all_since_2016.parquet')
WHERE poly_IncidentName = getvariable('fire') AND attr_POOState = 'US-' || getvariable('state')
  AND year(attr_FireDiscoveryDateTime) = getvariable('year');
SET VARIABLE x0 = (SELECT min(x0) FROM area);
SET VARIABLE x1 = (SELECT max(x1) FROM area);
SET VARIABLE y0 = (SELECT min(y0) FROM area);
SET VARIABLE y1 = (SELECT max(y1) FROM area);

-- 2. The 2020 blocks of the state in that extent, by interior point.
--    INTPTLON20/INTPTLAT20 are text; NAD83 against WGS84 is about 1 m here.
CREATE TABLE blk AS
SELECT GEOID20, POP20, HOUSING20,
       ST_Point(INTPTLON20::DOUBLE, INTPTLAT20::DOUBLE) AS pt
FROM read_parquet('https://parquetry.geomermaids.com/census/tiger/2020/block/state='
                  || getvariable('state') || '/blocks.parquet', hive_partitioning = false)
WHERE bbox.xmin <= getvariable('x1') AND bbox.xmax >= getvariable('x0')
  AND bbox.ymin <= getvariable('y1') AND bbox.ymax >= getvariable('y0');

SELECT count(*) AS blocks, sum(POP20) AS population_2020, sum(HOUSING20) AS housing_units_2020
FROM blk JOIN area ON ST_Intersects(area.geom, blk.pt);
```

Eaton fire perimeter: 267 blocks, 24,295 people and 9,335 housing units in
2020. Say that the count is of 2020 and by block interior point. For a
radius, build the circle in a UTM zone and transform it back, or filter
the interior points with `ST_Distance_Sphere`.

## Wetlands at a site

"Are there wetlands on or near this site?" NWI polygons within 200 m,
with distance, area inside the circle and the imagery year, about 1.5 s.

<!-- test: wetlands-near-point -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
SET VARIABLE state = 'MA';
SET VARIABLE lon = -70.3300;
SET VARIABLE lat = 41.7080;
SET VARIABLE m = 200;
SET VARIABLE utm = 'EPSG:269' || (floor((getvariable('lon') + 180) / 6) + 1)::INT;  -- NAD83 UTM zone
SET VARIABLE dy = getvariable('m') / 111000.0;
SET VARIABLE dx = getvariable('m') / (111000.0 * cos(radians(getvariable('lat'))));
SET VARIABLE x0 = (getvariable('lon') - getvariable('dx') - 1e-4)::FLOAT;
SET VARIABLE x1 = (getvariable('lon') + getvariable('dx') + 1e-4)::FLOAT;
SET VARIABLE y0 = (getvariable('lat') - getvariable('dy') - 1e-4)::FLOAT;
SET VARIABLE y1 = (getvariable('lat') + getvariable('dy') + 1e-4)::FLOAT;

SET geometry_always_xy = true;
-- Wetland polygons near the site, in metres (NAD83 / UTM). Deepwater types
-- are kept and labelled: leave them out if the question is about wetlands.
CREATE TABLE w AS
SELECT ATTRIBUTE, WETLAND_TYPE, ACRES,
       ST_Transform(geometry::GEOMETRY, 'EPSG:4269', getvariable('utm')) AS g
FROM read_parquet('https://parquetry.geomermaids.com/wetlands/nwi/2026-10/state='
                  || getvariable('state') || '/wetlands.parquet', hive_partitioning = false)
WHERE bbox.xmin <= getvariable('x1') AND bbox.xmax >= getvariable('x0')
  AND bbox.ymin <= getvariable('y1') AND bbox.ymax >= getvariable('y0');

CREATE TABLE site AS
SELECT ST_Transform(ST_Point(getvariable('lon'), getvariable('lat')), 'EPSG:4269', getvariable('utm')) AS p;

SELECT ATTRIBUTE, WETLAND_TYPE,
       round(min(ST_Distance(g, p))) AS metres,
       round(sum(ST_Area(ST_Intersection(g, ST_Buffer(p, getvariable('m'))))) / 1e4, 2) AS ha_within,
       (SELECT max(IMAGE_YR) FROM read_parquet('https://parquetry.geomermaids.com/wetlands/nwi/2026-10/projects.parquet')
        WHERE bbox.xmin <= getvariable('lon')::FLOAT AND bbox.xmax >= getvariable('lon')::FLOAT
          AND bbox.ymin <= getvariable('lat')::FLOAT AND bbox.ymax >= getvariable('lat')::FLOAT
          AND ST_Intersects(geometry, ST_Point(getvariable('lon'), getvariable('lat')))) AS imagery_year
FROM w, site
WHERE ST_DWithin(g, p, getvariable('m'))
GROUP BY ALL
ORDER BY metres;
```

Barnstable, Massachusetts, 200 m: salt marsh (`E2EM1Pd`, estuarine
emergent) 38 m away, tidal flats under the point, 11.5 ha of wetland in
the circle, mapped from 2008 imagery. Name the Cowardin code and the type,
say how old the mapping is, and say that NWI is not a jurisdictional
delineation.

## Schools in the flood zone

"Which schools in Charleston County are in the 100-year floodplain?"
Public, private and postsecondary schools against the county's FEMA
delivery, read on the schools' extent only, about 3 s.

<!-- test: schools-in-flood-zone -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
SET VARIABLE county_geoid = '45019';  -- Charleston County, SC

-- 1. Public and private schools and colleges of the county.
CREATE TABLE s AS
SELECT 'public' AS kind, NCESSCH AS id, NAME, CITY, geometry
FROM read_parquet('https://parquetry.geomermaids.com/schools/latest/public.parquet')
WHERE CNTY = getvariable('county_geoid')
UNION ALL
SELECT 'private', PPIN, NAME, CITY, geometry
FROM read_parquet('https://parquetry.geomermaids.com/schools/latest/private.parquet')
WHERE CNTY = getvariable('county_geoid')
UNION ALL
SELECT 'postsecondary', UNITID, NAME, CITY, geometry
FROM read_parquet('https://parquetry.geomermaids.com/schools/latest/postsecondary.parquet')
WHERE CNTY = getvariable('county_geoid');

-- 2. The county's FEMA delivery, read on the schools' extent only. NFHL's
--    bbox is DOUBLE: computed DOUBLE bounds skip row groups there.
CREATE TABLE dl AS
SELECT path, fema_update_date
FROM read_parquet('https://parquetry.geomermaids.com/nfhl/latest/counties.parquet')
WHERE dfirm_id = getvariable('county_geoid') || 'C';  -- county-wide deliveries are <FIPS>C
SET VARIABLE files = (SELECT list('https://parquetry.geomermaids.com/nfhl/latest/' || path) FROM dl);
SET VARIABLE x0 = (SELECT min(ST_X(geometry)) FROM s);
SET VARIABLE x1 = (SELECT max(ST_X(geometry)) FROM s);
SET VARIABLE y0 = (SELECT min(ST_Y(geometry)) FROM s);
SET VARIABLE y1 = (SELECT max(ST_Y(geometry)) FROM s);
CREATE TABLE fz AS
SELECT flood_zone, geometry::GEOMETRY AS geom
FROM read_parquet(getvariable('files'))
WHERE risk = '1 percent flood zone'
  AND bbox.xmin <= getvariable('x1') AND bbox.xmax >= getvariable('x0')
  AND bbox.ymin <= getvariable('y1') AND bbox.ymax >= getvariable('y0');

-- 3. Schools inside a 1% annual chance zone, once each.
SELECT s.kind, count(DISTINCT s.id) AS in_zone,
       (SELECT count(*) FROM s AS a WHERE a.kind = s.kind) AS total
FROM s JOIN fz ON ST_Intersects(fz.geom, s.geometry)
GROUP BY s.kind ORDER BY s.kind;
```

Charleston County, SC: 14 of 95 public schools, 10 of 36 private schools
and 4 of 13 colleges sit in a 1% annual chance zone. A point is the
school's geocode, not its campus: say so, and remember NFHL is not an
official determination. Counties with no county-wide delivery have no
`<FIPS>C` row: look them up by `state` and `county` in `counties.parquet`.

## Tribal area at a point

"Is this site on tribal land?" The TIGER 2026 tribal area and tribal
census tract under the point, about 1 s.

<!-- test: tribal-area-at-point -->
```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
SET VARIABLE lon = -109.0526;
SET VARIABLE lat = 35.6807;
SET VARIABLE x = getvariable('lon')::FLOAT;
SET VARIABLE y = getvariable('lat')::FLOAT;

-- The tribal area under the point and its tribal census tract.
SELECT a.GEOID, a.NAMELSAD, a.COMPTYP, a.AIANNHR, t.NAMELSAD AS tribal_tract
FROM read_parquet('https://parquetry.geomermaids.com/census/tiger/2026/aiarelated/aiannh.parquet') AS a
LEFT JOIN (
  SELECT AIANNHCE, NAMELSAD, geometry
  FROM read_parquet('https://parquetry.geomermaids.com/census/tiger/2026/aiarelated/ttract.parquet')
  WHERE bbox.xmin <= getvariable('x') AND bbox.xmax >= getvariable('x')
    AND bbox.ymin <= getvariable('y') AND bbox.ymax >= getvariable('y')
    AND ST_Intersects(geometry, ST_Point(getvariable('lon'), getvariable('lat')))) AS t
  ON t.AIANNHCE = a.AIANNHCE
WHERE a.bbox.xmin <= getvariable('x') AND a.bbox.xmax >= getvariable('x')
  AND a.bbox.ymin <= getvariable('y') AND a.bbox.ymax >= getvariable('y')
  AND ST_Intersects(a.geometry, ST_Point(getvariable('lon'), getvariable('lat')));
```

Window Rock, Arizona: Navajo Nation Reservation (`2430R`, federally
recognized), tribal census tract T035. Census boundaries are statistical,
not legal descriptions of jurisdiction. NRI scores the tribal areas in
`nri/v1.20/tribal_counties.parquet`, by `AIANNHCE`.
