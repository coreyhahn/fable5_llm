#!/usr/bin/env python3
"""rd_image_dump.py — build the chat launch images for an artifact and
disassemble their splice points, board-free.

`chat_seq` compiles three images out of the committed stream (preamble,
lite step, full step).  This prints their boundaries so a 2B image can be
compared record-for-record against the 0.8B one that is known good, and
against the artifact's own records.
"""
import json
import sys

R = "/home/cah/r2d2/code/fpga/fable5_llm"
sys.path.insert(0, f"{R}/ref")
sys.path.insert(0, f"{R}/sw")

import seq_format as SF                                   # noqa: E402
import chat_seq as CS                                     # noqa: E402

prefix = sys.argv[1]
recs = SF.unpack_stream(open(prefix + ".seq", "rb").read())
meta = json.load(open(prefix + ".seq.json"))
g = CS.derive_geometry(recs, meta)
m = CS.seq_chat_for(g)
tc = m.TurnCompiler(prefix, t_max=512, pos_mode="ldc", verify_sha=False)

print(f"=== {prefix}")
imgs = {"preamble": tc.build_session(),
        "lite": tc.build_step(0, 0, "lite"),
        "full": tc.build_step(0, 0, "full")}
for name, a in imgs.items():
    rr = SF.unpack_stream(a.data)
    print(f"\n--- {name}: {len(rr)} records, {len(a.data)} B")
    for i in list(range(min(6, len(rr)))):
        print(f"   [{i:5d}] {SF.disasm(rr[i], i)}")
    print("    ...")
    for i in range(max(0, len(rr) - 5), len(rr)):
        print(f"   [{i:5d}] {SF.disasm(rr[i], i)}")

# the full step image, minus its 3-record head and its HALT, must be the
# artifact's own body verbatim
full = SF.unpack_stream(imgs["full"].data)
b0, b1 = g["R_BODY_FULL"]
mine = SF.pack_stream(full[3:len(full) - 1])
theirs = SF.pack_stream(recs[b0:b1])
print(f"\nfull-step body vs artifact recs[{b0}:{b1}]: "
      f"{len(mine)} B vs {len(theirs)} B — "
      + ("BYTE-IDENTICAL" if mine == theirs else "DIFFERS"))
if mine != theirs and len(mine) == len(theirs):
    d = [i // SF.SEQ_REC_BYTES for i in range(len(mine))
         if mine[i] != theirs[i]]
    rd = sorted(set(d))
    print(f"   {len(rd)} records differ; first 8: {rd[:8]}")
    for k in rd[:8]:
        print(f"     mine  [{k}] {SF.disasm(full[3 + k], k)}")
        print(f"     theirs[{k}] {SF.disasm(recs[b0 + k], k)}")

pre = SF.unpack_stream(imgs["preamble"].data)
lo, hi = g["R_PREAMBLE"]
mine = SF.pack_stream(pre[:hi - lo])
theirs = SF.pack_stream(recs[lo:hi])
print(f"preamble body vs artifact recs[{lo}:{hi}]: "
      + ("BYTE-IDENTICAL" if mine == theirs else "DIFFERS"))
