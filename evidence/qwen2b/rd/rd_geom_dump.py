#!/usr/bin/env python3
"""rd_geom_dump.py — the derived chat geometry of an artifact, side by side
with the compiled step image, so the 2B and the 0.8B can be compared
structurally.  Board-free.
"""
import json
import sys

R = "/home/cah/r2d2/code/fpga/fable5_llm"
sys.path.insert(0, f"{R}/ref")
sys.path.insert(0, f"{R}/sw")

import seq_format as SF                                   # noqa: E402
import chat_seq as CS                                     # noqa: E402

for prefix in sys.argv[1:]:
    recs = SF.unpack_stream(open(prefix + ".seq", "rb").read())
    meta = json.load(open(prefix + ".seq.json"))
    g = CS.derive_geometry(recs, meta)
    print(f"\n=== {prefix}  ({len(recs)} records, nch={meta.get('nch', 1)}, "
          f"repack={bool(meta.get('weight_repack'))})")
    for k in ("R_PREAMBLE", "R_SEED_TOK", "R_SEED_POS", "R_BODY_FULL",
              "R_BODY_LITE", "R_TCNT", "R_POSADV", "R_JMP", "R_HALT",
              "NREC_PREAMBLE", "NREC_BODY_FULL", "NREC_BODY_LITE",
              "LITE_SUFFIX_RECS", "X8_WORD", "X8_LEN", "CONST_BYTES",
              "POS_WORDS", "POS_STRIDE", "POS_LDC_REC_OFFSETS"):
        print(f"   {k:<22} {g[k]}")
    b0 = g["R_BODY_FULL"][0]
    print(f"   R_TCNT inside body 0? "
          f"{g['R_BODY_FULL'][0] <= g['R_TCNT'] < g['R_BODY_FULL'][1]}")
    print(f"   _BODY_STARTS           {g['_BODY_STARTS']}")
    print("   --- preamble tail (last 4) ---")
    for i in range(b0 - 6, b0):
        print(f"     {i:6d}  {SF.disasm(recs[i], i)}")
    print("   --- body head (first 6) ---")
    for i in range(b0, b0 + 6):
        print(f"     {i:6d}  {SF.disasm(recs[i], i)}")
    print("   --- body tail (last 4) ---")
    for i in range(g["R_BODY_FULL"][1] - 4, g["R_BODY_FULL"][1]):
        print(f"     {i:6d}  {SF.disasm(recs[i], i)}")
    print("   --- lite cut neighbourhood ---")
    c = g["R_BODY_LITE"][1]
    for i in range(c - 2, c + 3):
        print(f"     {i:6d}  {SF.disasm(recs[i], i)}")
