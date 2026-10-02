#!/bin/bash
# Rebuild docs/flythrough.html: inline placement.json into the page source
# (build.py writes the HTML fragment), then wrap the fragment as a document.
set -euo pipefail
D=$(cd "$(dirname "$0")" && pwd)
python3 "$D/build.py" "$D/placement.json"
{ printf '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n<meta name="description" content="A 3D flythrough of the fable5_llm design placed on the xcvu9p die: every used site drawn from the routed build_046 checkpoint, with one decode step animated.">\n</head>\n<body>\n'
  cat "$D/die-flythrough.html"
  printf '\n</body>\n</html>\n'; } > "$D/../flythrough.html"
rm "$D/die-flythrough.html"
ls -la "$D/../flythrough.html"
