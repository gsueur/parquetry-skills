# /// script
# requires-python = ">=3.10"
# dependencies = ["duckdb>=1.5"]
# ///
"""Everything the parquetry reference datasets say about one location.

    uv run locate.py <lon> <lat> [--radius-km 2]

Prints JSON: the administrative units (FAO GAUL 2024, worldwide), the FEMA
flood zone (United States), the CORINE land cover class (Europe), the
OpenStreetMap region file (US, Canada, Mexico) and the nearest power
infrastructure (GMWID, worldwide). Each block names its source, the date of
the data and the credit to give. A block is null when the dataset does not
cover the point.

Every lookup reads a few MB with HTTP range requests: a bbox filter first,
so only the row groups around the point are fetched, then an exact
geometry test on what is left.
"""

import argparse
import csv
import json
import math
import sys
import unicodedata
from pathlib import Path

import duckdb

BASE = "https://parquetry.geomermaids.com"
HERE = Path(__file__).resolve().parent

# GAUL is keyed by ISO alpha-3, CORINE by alpha-2. Only the CORINE
# countries are needed. xKO is FAO's pseudo-code for Kosovo, which CORINE
# files under Serbia.
CLC_ISO2 = {
    "ALA": "AX", "ALB": "AL", "AND": "AD", "AUT": "AT", "BEL": "BE", "BGR": "BG",
    "BIH": "BA", "CHE": "CH", "CYP": "CY", "CZE": "CZ", "DEU": "DE", "DNK": "DK",
    "ESP": "ES", "EST": "EE", "FIN": "FI", "FRA": "FR", "FRO": "FO", "GBR": "GB",
    "GGY": "GG", "GIB": "GI", "GRC": "GR", "HRV": "HR", "HUN": "HU", "IMN": "IM",
    "IRL": "IE", "ISL": "IS", "ITA": "IT", "JEY": "JE", "LIE": "LI", "LTU": "LT",
    "LUX": "LU", "LVA": "LV", "MCO": "MC", "MKD": "MK", "MLT": "MT", "MNE": "ME",
    "NLD": "NL", "NOR": "NO", "POL": "PL", "PRT": "PT", "ROU": "RO", "SRB": "RS",
    "SWE": "SE", "SVN": "SI", "SVK": "SK", "SMR": "SM", "TUR": "TR", "VAT": "VA",
    "xKO": "RS",
}
OSM_COUNTRY = {"USA": "US", "PRI": "US", "VIR": "US", "CAN": "CA", "MEX": "MX"}
NFHL_ISO3 = {"USA", "PRI"}


def connect():
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;")
    con.execute("SET geometry_always_xy = true;")
    return con


def bbox_hit(lon, lat, pad=0.0, col="bbox"):
    """Rows whose bbox covering touches the point, or the square around it."""
    return (
        f"{col}.xmin <= {lon + pad} AND {col}.xmax >= {lon - pad} "
        f"AND {col}.ymin <= {lat + pad} AND {col}.ymax >= {lat - pad}"
    )


def rows(con, sql):
    cur = con.execute(sql)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def admin(con, lon, lat):
    # The whole-world files hold the geometry of large row groups. Reading
    # only the country boxes (under 1 s) and then one country's file is
    # several times faster than a spatial filter on the world file.
    cands = rows(con, f"""
        SELECT DISTINCT iso3_code
        FROM read_parquet('{BASE}/gaul/2024/GAUL_2024_L0_derived.parquet')
        WHERE {bbox_hit(lon, lat)}""")
    for c in cands:
        hit = rows(con, f"""
            SELECT iso3_code, gaul0_name AS country, gaul1_name AS level1,
                   gaul2_name AS level2, gaul0_code, gaul1_code, gaul2_code,
                   disp_en AS display_name
            FROM read_parquet('{BASE}/gaul/2024/country={c["iso3_code"]}/L2.parquet')
            WHERE {bbox_hit(lon, lat)}
              AND ST_Intersects(geometry, ST_Point({lon}, {lat}))""")
        if hit:
            return {
                **hit[0],
                "source": "FAO GAUL 2024",
                "credit": "FAO GAUL 2024, CC BY 4.0. FAO does not endorse this use. "
                          "Boundaries do not imply any opinion of FAO on the legal "
                          "status of any territory.",
            }
    return None


def flood(con, lon, lat):
    # The index stores each delivery's bounding rectangle, so near a county
    # line a point falls in two. Every candidate is read; the zone pieces,
    # which carry their county, decide.
    paths = [r["path"] for r in rows(con, f"""
        SELECT path FROM read_parquet('{BASE}/nfhl/latest/counties.parquet')
        WHERE xmin <= {lon} AND xmax >= {lon} AND ymin <= {lat} AND ymax >= {lat}""")]
    zone = []
    if paths:
        files = ", ".join(f"'{BASE}/nfhl/latest/{p}'" for p in paths)
        zone = rows(con, f"""
            SELECT county, state, dfirm_id, fema_update_date,
                   flood_zone, zone_subtype, sfha, static_bfe, risk
            FROM read_parquet([{files}])
            WHERE {bbox_hit(lon, lat)}
              AND ST_Intersects(geometry, ST_Point({lon}, {lat}))
            LIMIT 1""")
    if not zone:
        return {"covered": False,
                "note": "No FEMA county-wide delivery maps this point: unmapped, "
                        "not free of flood risk."}
    return {
        "covered": True,
        **zone[0],
        "fema_update_date": str(zone[0]["fema_update_date"]),
        "source": "FEMA National Flood Hazard Layer",
        "credit": "FEMA National Flood Hazard Layer, public domain. Not for official "
                  "flood zone determinations.",
    }


def land_cover(con, lon, lat, iso2):
    x, y = con.execute(
        f"SELECT ST_X(p), ST_Y(p) FROM (SELECT ST_Transform(ST_Point({lon}, {lat}), "
        f"'OGC:CRS84', 'EPSG:3035') AS p)").fetchone()
    hit = rows(con, f"""
        SELECT Code_18 AS clc_code, Area_Ha AS polygon_area_ha
        FROM read_parquet('{BASE}/clc/2018/country={iso2}/clc_2018.parquet')
        WHERE {bbox_hit(x, y)} AND ST_Intersects(Shape, ST_Point({x}, {y}))""")
    if not hit:
        return None
    return {
        **hit[0],
        "label": CLC_LABELS.get(hit[0]["clc_code"]),
        "source": "CORINE Land Cover 2018",
        "credit": "(c) European Union, Copernicus Land Monitoring Service, "
                  "European Environment Agency (EEA)",
    }


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in s if ch.isalpha())


def osm_region(a):
    country = OSM_COUNTRY.get(a["iso3_code"])
    if not country:
        return None
    if a["iso3_code"] == "PRI":
        code = "US-PR"
    elif a["iso3_code"] == "VIR":
        code = "US-VI"
    else:
        regions = [r for r in csv.DictReader(open(HERE.parent / "reference" / "osm-regions.csv"))
                   if r["country"] == country]
        want = norm(a["level1"])
        exact = [r for r in regions if norm(r["state_name"]) == want]
        # GAUL writes "Quebec / Québec", OSM "Québec": match either way round.
        part = [r for r in regions
                if want in norm(r["state_name"]) or norm(r["state_name"]) in want]
        match = exact or (part if len(part) == 1 else [])
        if not match:
            return None
        code = match[0]["state_iso"]
    return {
        "region": code,
        "files": f"{BASE}/osm/latest/country={country}/state={code}/<theme>.parquet",
        "source": "OpenStreetMap",
        "credit": "(c) OpenStreetMap contributors, ODbL 1.0",
    }


def utm(lon, lat):
    return f"EPSG:{(32600 if lat >= 0 else 32700) + int((lon + 180) // 6) + 1}"


def infrastructure(con, lon, lat, radius_km):
    # The search square is padded in degrees, then distances are measured in
    # metres in the local UTM zone, which is exact enough at this range.
    pad = radius_km / 111.0 / max(math.cos(math.radians(lat)), 0.01)
    crs = utm(lon, lat)
    here = f"ST_Transform(ST_Point({lon}, {lat}), 'OGC:CRS84', '{crs}')"
    out = {}
    for layer, cols in [
        ("power_substation", "name, operator, voltage_kv, lifecycle, origin"),
        ("power_line", "name, operator, voltage_kv, lifecycle, origin"),
        ("power_plant", "name, operator, source, output_mw, lifecycle, origin"),
    ]:
        found = rows(con, f"""
            SELECT {cols},
                   round(ST_Distance(ST_Transform(geometry, 'OGC:CRS84', '{crs}'), {here}))
                       AS distance_m
            FROM read_parquet('{BASE}/gmwid/latest/{layer}.parquet')
            WHERE {bbox_hit(lon, lat, pad)}
            ORDER BY distance_m LIMIT 1""")
        out[layer] = found[0] if found and found[0]["distance_m"] <= radius_km * 1000 else None
    return {
        **out,
        "radius_km": radius_km,
        "source": "GMWID (OpenStreetMap, completed from authoritative open sources)",
        "credit": "(c) OpenStreetMap contributors, ODbL 1.0; rows with origin other "
                  "than osm carry the credit of that source, see https://parquetry.geomermaids.com/gmwid/ATTRIBUTION.txt",
    }


CLC_LABELS = {
    "111": "Continuous urban fabric", "112": "Discontinuous urban fabric",
    "121": "Industrial or commercial units", "122": "Road and rail networks and associated land",
    "123": "Port areas", "124": "Airports", "131": "Mineral extraction sites",
    "132": "Dump sites", "133": "Construction sites", "141": "Green urban areas",
    "142": "Sport and leisure facilities", "211": "Non-irrigated arable land",
    "212": "Permanently irrigated land", "213": "Rice fields", "221": "Vineyards",
    "222": "Fruit trees and berry plantations", "223": "Olive groves", "231": "Pastures",
    "241": "Annual crops associated with permanent crops", "242": "Complex cultivation patterns",
    "243": "Land principally occupied by agriculture, with significant areas of natural vegetation",
    "244": "Agro-forestry areas", "311": "Broad-leaved forest", "312": "Coniferous forest",
    "313": "Mixed forest", "321": "Natural grasslands", "322": "Moors and heathland",
    "323": "Sclerophyllous vegetation", "324": "Transitional woodland-shrub",
    "331": "Beaches, dunes, sands", "332": "Bare rocks", "333": "Sparsely vegetated areas",
    "334": "Burnt areas", "335": "Glaciers and perpetual snow", "411": "Inland marshes",
    "412": "Peat bogs", "421": "Salt marshes", "422": "Salines", "423": "Intertidal flats",
    "511": "Water courses", "512": "Water bodies", "521": "Coastal lagoons",
    "522": "Estuaries", "523": "Sea and ocean", "999": "NODATA",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("lon", type=float)
    ap.add_argument("lat", type=float)
    ap.add_argument("--radius-km", type=float, default=2.0,
                    help="search radius for infrastructure (default 2)")
    a = ap.parse_args()
    if not (-180 <= a.lon <= 180 and -90 <= a.lat <= 90):
        sys.exit("lon must be in [-180, 180] and lat in [-90, 90]: lon comes first")

    con = connect()
    result = {"lon": a.lon, "lat": a.lat}
    adm = admin(con, a.lon, a.lat)
    result["admin"] = adm
    iso3 = adm["iso3_code"] if adm else None
    result["flood"] = flood(con, a.lon, a.lat) if iso3 in NFHL_ISO3 else None
    result["land_cover"] = (land_cover(con, a.lon, a.lat, CLC_ISO2[iso3])
                            if iso3 in CLC_ISO2 else None)
    result["osm"] = osm_region(adm) if adm else None
    result["infrastructure"] = infrastructure(con, a.lon, a.lat, a.radius_km)
    print(json.dumps(result, indent=2, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()
