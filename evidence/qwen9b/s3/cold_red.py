#!/usr/bin/env python3
"""cold_red.py — S3 step 1's RED, for the RIGHT reason.

The fence this proves is the EMITTER's twin of the RTL's `E_DMA_COLD`
(SEQ_ISA v2.1 B15.4, spec 2026-09-04-qwen35-9b-state-spill-design.md 5.4):
a compute command on a cache slot that has had no completed load since its
last SST must be refused BY THE GENERATOR, not discovered on the hardware.

Five statements, no generator run: a `Mach`, a LAYER select, the DNSB base
pair every DNST needs, and one DNST with no SLD ahead of it.  Re-running a
whole generator is NOT this RED -- its own preamble calls `convw`, and the
first failure would be that one.

  rc 0  the fence fired      (GREEN, S3's emitter)
  rc 1  the fence is absent  (RED,  the pre-S3 emitter)
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "ref"))
import gen_layer_script as G                                   # noqa: E402

M = G.Mach(io.StringIO())
try:
    M.layer(0, 0, 0, 0)          # v2.1: dn_slot, kv_slot, cv_slot, kv_layer
except TypeError:
    M.layer(0, 0)                # pre-S3: two BANK indices, no cv/kv_layer
    print("cold_red: layer() takes two arguments on this tree (pre-S3)")
M.dnsb(0x140, 0x100)             # a_beta_base, a_dec_base (no GATE emitted)
try:
    M.dnst(0, 0x200, 0x300, 0x400, 0x100, 0x140, 0x800)
except AssertionError as e:
    ok = "E_DMA_COLD" in str(e)
    print(f"COLD_RED: {'GREEN' if ok else 'RED'} — {e}")
    sys.exit(0 if ok else 1)
print("COLD_RED: RED — DNST on a COLD DN slot 0 was ACCEPTED; the emitter "
      "has no E_DMA_COLD fence")
sys.exit(1)
