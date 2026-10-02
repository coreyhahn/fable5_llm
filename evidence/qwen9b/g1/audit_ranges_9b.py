#!/usr/bin/env python3
"""G1(d) axis 1 — `ref/audit_ranges.py` run at 9B, without editing it.

Same one-line defect as the gate-port probe, in the same place:
`ref/audit_ranges.py:283` does `cp = LQ.find_checkpoint()`, which is the FIRST
SHARD ONLY (`ref/load_qwen35.py:108-113`).  0.8B and 2B are single-shard, so
the auditor was right everywhere it had ever run; 9B has four shards and the
DeltaNet tensors of layer 0 live in shard 2.

This wrapper runs the auditor verbatim with `find_checkpoint` patched to the
whole shard list, so the measurement is `audit_ranges`'s own code.

TWO THINGS THIS DOES NOT FIX, both recorded in the gate doc rather than
papered over:
  * section 2b calls the LM head "the tied `embed_tokens` matrix".  At 9B the
    head is the checkpoint's own `lm_head.weight` and `embed_tokens` is a
    DIFFERENT tensor (`ref/load_qwen35.py:371-375`), so that section audits
    the embedding table under a label that says head.  It is still a real
    audit of a real matrix; it is just not the head.
  * the GATE-PORT CAVEAT the auditor prints about itself — sections 1 and 3
    read POST-clamp `dt_bias`/`A`, so they cannot see a gate-port overflow.
    That is exactly why spec 4.1(d) makes this two tools, and the other one is
    `gate_port_probe_9b.py`.

Usage:  FABLE5_MODEL=9b python evidence/qwen9b/g1/audit_ranges_9b.py -o OUT.md
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "ref"))

import load_qwen35 as LQ          # noqa: E402
import model_select as MS         # noqa: E402

ORIG = os.path.join(ROOT, "ref", "audit_ranges.py")
print(f"=== audit_ranges_9b: running {ORIG} at FABLE5_MODEL={MS.TAG}")
print("=== with LQ.find_checkpoint patched to the FULL shard list "
      "(see this file's header)")
sys.argv = [ORIG] + sys.argv[1:]
LQ.find_checkpoint = lambda path=None: LQ.find_checkpoints(path)
runpy.run_path(ORIG, run_name="__main__")
