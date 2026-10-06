# /// script
# requires-python = ">=3.10"
# dependencies = ["duckdb>=1.5"]
# ///
"""Run every tested SQL block in the skill against the live datasets.

    uv run tests/check_recipes.py            # all blocks but the slow ones
    uv run tests/check_recipes.py --slow     # all blocks
    uv run tests/check_recipes.py nearest    # blocks whose name contains it

A block is the ```sql fence right after a `<!-- test: <name> [slow] -->`
comment. It passes when every statement runs and its last statement returns
at least one row. The data changes under the queries (OSM nightly, FEMA
daily), so the check is that the recipe still works, not a fixed number.
"""

import re
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted((ROOT / "skills").rglob("*.md"))
BLOCK = re.compile(r"<!-- test: ([\w-]+)( slow)? -->\s*```sql\n(.*?)```", re.S)


def blocks():
    for f in FILES:
        for m in BLOCK.finditer(f.read_text()):
            yield f.relative_to(ROOT), m.group(1), bool(m.group(2)), m.group(3)


def run(sql):
    con = duckdb.connect()
    last = None
    for stmt in con.extract_statements(sql):
        last = con.execute(stmt)
    return last.fetchall() if last and last.description else []


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    slow = "--slow" in sys.argv
    failed = 0
    for path, name, is_slow, sql in blocks():
        if args and not any(a in name for a in args):
            continue
        if is_slow and not slow and not args:
            print(f"skip  {name} (slow; pass --slow)")
            continue
        t = time.time()
        try:
            out = run(sql)
            ok = bool(out)
            msg = f"{len(out)} rows, first {out[0]}" if ok else "no rows"
        except Exception as e:  # noqa: BLE001 - report any failure and go on
            ok, msg = False, f"{type(e).__name__}: {e}".splitlines()[0]
        print(f"{'ok  ' if ok else 'FAIL'}  {name} ({path}, {time.time() - t:.0f} s): {msg}")
        failed += not ok
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
