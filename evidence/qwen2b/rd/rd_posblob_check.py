#!/usr/bin/env python3
"""rd_posblob_check.py — agent A's gate A2, applied to the 2B artifact.

`ref/seq_chat.TurnCompiler` does not reuse the artifact's position blob: it
RECOMPUTES one from `ref/layer_fixed.rope_tables_q15` and uploads that.  The
committed seqdata carries the emitter's own six positions immediately after
the const region, so the two must agree byte for byte — that equality is
gate A2 at 0.8B and is exactly what makes the host-built 512-position pool
trustworthy.

Run under the model whose artifact is being checked (FABLE5_MODEL).
"""
import hashlib
import json
import os
import sys

R = "/home/cah/r2d2/code/fpga/fable5_llm"
sys.path.insert(0, f"{R}/ref")
sys.path.insert(0, f"{R}/sw")

import numpy as np                                        # noqa: E402
import layer_fixed as LF                                  # noqa: E402
import model_select as MS                                 # noqa: E402

prefix = sys.argv[1]
const_bytes = int(sys.argv[2])
POS_COPIES, POS_WORDS = 6, 128

print(f"FABLE5_MODEL={MS.TAG}   artifact={os.path.basename(prefix)}")
raw = open(prefix + ".seqdata.bin", "rb").read()
meta = json.load(open(prefix + ".seq.json"))
print(f"seqdata {len(raw)} B, sha256 {hashlib.sha256(raw).hexdigest()[:16]} "
      f"(meta {meta['seqdata_sha256'][:16]})")
tail = raw[const_bytes:]
print(f"const region {const_bytes} B, committed position tail {len(tail)} B "
      f"= {len(tail) // (POS_COPIES * POS_WORDS * 2)} positions")

out = np.empty((6, POS_COPIES, POS_WORDS), dtype="<i2")
for p in range(6):
    cos, sin = LF.rope_tables_q15(p)
    one = np.concatenate([cos, sin]).astype("<i2")
    print(f"  rope_tables_q15({p}): {one.size} words, "
          f"first 4 {one[:4].tolist()}")
    if one.size != POS_WORDS:
        raise SystemExit(f"FAIL: {one.size} words, the LDC reads {POS_WORDS}")
    out[p, :, :] = one
mine = out.tobytes()

print(f"\nhost-rebuilt 6 positions: {len(mine)} B")
if mine == tail:
    print("POS_BLOB_MATCH — the host pool reproduces the emitter's positions")
    sys.exit(0)
d = [i for i in range(min(len(mine), len(tail))) if mine[i] != tail[i]]
print(f"POS_BLOB_DIFFERS — {len(d)} of {len(tail)} bytes differ, "
      f"first at {d[0] if d else 'n/a'}")
a = np.frombuffer(mine, dtype="<i2")
b = np.frombuffer(tail, dtype="<i2")
print(f"  host   [:8] {a[:8].tolist()}")
print(f"  emitter[:8] {b[:8].tolist()}")
w = np.nonzero(a != b)[0]
print(f"  {w.size} of {a.size} int16 words differ; "
      f"positions touched: {sorted({int(i) // (POS_COPIES * POS_WORDS) for i in w})}")
sys.exit(1)
