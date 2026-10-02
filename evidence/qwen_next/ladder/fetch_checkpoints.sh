#!/usr/bin/env bash
# Track L (qwen-next fidelity/PPL ladder) — fetch the 4B and 9B bf16 checkpoints
# into snoke's HuggingFace cache.  RUN FROM SNOKE.
#
# Disk discipline (docs/QWEN35_NEXT_FEASIBILITY.md §5): 4B is 8.68 GiB (2
# shards), 9B is 17.98 GiB (4 shards).  `f07_disk.log` recorded 94 GB free of
# 458 GB; this script re-checks before and after so the number in the evidence
# is the one that actually held on the day.
#
#   bash evidence/qwen_next/ladder/fetch_checkpoints.sh 4B 9B
set -u
cd "$(dirname "$0")/../../.."   # repo root
UV="$HOME/.local/bin/uv run --no-project --with huggingface_hub python"

echo "=== host $(hostname)  $(date -Is) ==="
df -h / | tail -1

for M in "$@"; do
  echo "--- Qwen/Qwen3.5-$M ---"
  $UV - "$M" <<'PY'
import sys, time
from huggingface_hub import snapshot_download
m = sys.argv[1]
t0 = time.time()
p = snapshot_download(
    f"Qwen/Qwen3.5-{m}",
    allow_patterns=["*.safetensors", "*.json", "*.txt", "*.jinja", "LICENSE"],
    max_workers=8,
)
print(f"{m}: {p}  ({time.time()-t0:.1f}s)")
PY
  df -h / | tail -1
done
echo "=== done $(date -Is) ==="
