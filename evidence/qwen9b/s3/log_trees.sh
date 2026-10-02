#!/usr/bin/env sh
# log_trees.sh — every s3 log's `=== tree:` header, so §9's table can be
# CHECKED rather than typed (S3 fix round 2, I1: two cells were wrong).
cd "$(dirname "$0")"
for f in [0-9][0-9][0-9]_*.log; do
  printf '%-42s %s\n' "$f" "$(sed -n 's/^=== tree: //p' "$f" | head -1)"
done
