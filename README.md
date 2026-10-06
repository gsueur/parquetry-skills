# parquetry skills

A skill that lets an AI agent answer spatial questions with real reference
data, not general knowledge:

- *What is the predominant land use in Hérault, France?*
- *How many buildings could be hit by a 100-year flood in Eastern Massachusetts?*
- *How many km of 380 kV line cross Lombardy?*
- *Which substations are within 5 km of this site?*
- *Add the country, district and flood zone to my list of 300 sites.*

The agent turns the question into a spatial query over five open datasets
published by Geomermaids on [parquetry](https://geoparquet.geomermaids.com),
runs it with DuckDB straight from the URLs, and answers with the number,
the definitions it chose, the coverage, the data dates and the credits.
There is no server, no API key and no download step: DuckDB reads only the
parts of the GeoParquet files the question needs.

| Dataset | Covers | Answers |
|---|---|---|
| [FAO GAUL 2024](https://parquetry.geomermaids.com/gaul/) | World | Countries, regions, districts: the areas questions are about |
| [GMWID](https://gmwid.geomermaids.com) | World | Power, telecoms, oil and gas, water infrastructure |
| [FEMA NFHL](https://nfhl.geomermaids.com) | United States | 100-year and 500-year flood zones, updated daily |
| [CORINE Land Cover 2018](https://parquetry.geomermaids.com/clc/) | Europe | Land cover and land use, 44 classes |
| [OpenStreetMap](https://geoparquet.geomermaids.com) | US, Canada, Mexico | Buildings, roads, POIs, places and more, updated nightly |

## Install

### Claude Code

```
/plugin marketplace add gsueur/parquetry-skills
/plugin install parquetry@geomermaids
```

The skill loads when a question needs geographic data. You can also call
it by name: `/parquetry:reference-data`.

### Other agents

The skill is plain Markdown in `skills/reference-data/`: `SKILL.md` is the
method, `reference/datasets.md` the data, `reference/recipes.md` the
tested queries. Point any agent that can run code at those files.

The agent needs a shell with [DuckDB](https://duckdb.org) 1.5 or later
(the CLI or the Python package) and network access to
`parquetry.geomermaids.com`. The optional `scripts/locate.py` runs with
[uv](https://docs.astral.sh/uv/).

## What is in it

```
skills/reference-data/
  SKILL.md                 the method: definitions, coverage, efficient reads, CRS, answer
  reference/datasets.md    layout, columns, value domains, licences of each dataset
  reference/recipes.md     tested queries: point context, area composition,
                           overlay count, length in area, nearest, tagging, per-unit stats
  reference/osm-regions.csv  the 98 OpenStreetMap regions
  scripts/locate.py        everything the datasets say about one lon/lat
tests/check_recipes.py     runs every recipe against the live data
```

## Tests

Every SQL block in `reference/recipes.md` that follows a
`<!-- test: name -->` marker runs against the live datasets:

```
uv run tests/check_recipes.py          # all but the slow ones
uv run tests/check_recipes.py --slow   # all, including the Massachusetts overlay
```

CI runs them weekly, so a change in a dataset that breaks a recipe shows
up here first.

## Credits

The data keeps its own licences, listed in `reference/datasets.md`:
OpenStreetMap and GMWID under ODbL ("(c) OpenStreetMap contributors"),
GAUL under CC BY 4.0 (FAO), CORINE under the Copernicus licence (EEA),
NFHL in the public domain (FEMA). The skill tells the agent to credit each
dataset it uses.

The skill itself is MIT licensed.
