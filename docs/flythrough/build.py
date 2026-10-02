#!/usr/bin/env python3
"""Inline placement JSON into the die flythrough page.

usage: python3 build.py [placement.json]

Reads die-flythrough.src.html next to this script and writes
die-flythrough.html. With a placement file, the JSON replaces the
__PLACEMENT_JSON__ placeholder; without one, the placeholder stays and the
page draws its built-in stylized layout.
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "die-flythrough.src.html"
OUT = HERE / "die-flythrough.html"
PLACEHOLDER = "__PLACEMENT_JSON__"
REQUIRED = ("meta", "extent", "slr", "types", "blocks", "used", "columns", "pitch")


def main(argv):
    src = SRC.read_text(encoding="utf-8")
    if src.count(PLACEHOLDER) != 1:
        sys.exit(f"error: expected exactly one {PLACEHOLDER} in {SRC.name}")
    if len(argv) > 2:
        sys.exit(__doc__)
    if len(argv) == 2:
        path = pathlib.Path(argv[1])
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = [k for k in REQUIRED if k not in data]
        if missing:
            sys.exit(f"error: {path} lacks keys: {', '.join(missing)}")
        payload = json.dumps(data, separators=(",", ":"))
        # Keep the JSON from closing the <script> element early.
        payload = payload.replace("</", "<\\/").replace("<!--", "<\\!--")
        out = src.replace(PLACEHOLDER, payload)
        print(f"inlined {path} ({len(payload):,} bytes, {data['used'].get('count', '?')} used sites)")
    else:
        out = src
        print("no placement given: page will use its stylized fallback layout")
    OUT.write_text(out, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main(sys.argv)
