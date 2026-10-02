#!/usr/bin/env python3
"""tie_ground_truth.py — where does tie_word_embeddings actually live, per model?

Review round 2 finding 4: fetch_geometry.py read `text_config.get(...)` and
printed None for an ABSENT key, which this study then read as an explicit
JSON `null`.  Those are different facts and they lead to opposite conclusions
about ref/load_qwen35.py:288.  This prints the raw truth.
"""
import json
from huggingface_hub import hf_hub_download

for repo in ("Qwen/Qwen3.5-0.8B", "Qwen/Qwen3.5-2B",
             "Qwen/Qwen3.5-4B", "Qwen/Qwen3.5-9B"):
    cfg = json.load(open(hf_hub_download(repo, "config.json")))
    tc = cfg.get("text_config", {})
    print(f"--- {repo}")
    print(f"    TOP-level  'tie_word_embeddings' present={'tie_word_embeddings' in cfg}"
          f"  value={cfg.get('tie_word_embeddings', '<ABSENT>')!r}")
    print(f"    text_config 'tie_word_embeddings' present={'tie_word_embeddings' in tc}"
          f"  value={tc.get('tie_word_embeddings', '<ABSENT>')!r}")
    # exactly what ref/load_qwen35.py:288 evaluates, on the dict it is handed.
    # load_qwen35 builds `cfg` from the TEXT config (ref/load_qwen35.py:60-70).
    for name, d in (("text_config", tc), ("top level", cfg)):
        got = d.get("tie_word_embeddings", True)
        print(f"    .get('tie_word_embeddings', True) on {name:11s} -> {got!r}"
              f"   `not it` -> {not got}   => guard {'RAISES' if not got else 'passes'}")
