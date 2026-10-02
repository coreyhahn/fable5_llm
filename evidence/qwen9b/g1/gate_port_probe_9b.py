#!/usr/bin/env python3
"""G1(d) axis 2 — Track Q's gate-port probe, run at 9B, plus a cross-check.

WHY THIS FILE EXISTS, and why it is not an edit to the original.

`evidence/qwen2b/q2/audit/gate_port_probe.py` is Track Q's COMMITTED
evidence script and this campaign does not edit committed evidence in place
(plan, global constraints).  It also does not work at 9B as written, and the
reason is a one-line defect worth naming:

    st = LQ.SafeTensors(LQ.find_checkpoint())

`find_checkpoint` returns the FIRST SHARD ONLY, and its own docstring
(`ref/load_qwen35.py:108-113`) says so: "callers that read tensors want
`find_checkpoints` / `SafeTensors`, which take the whole shard list."  0.8B
and 2B are single-shard, so the probe was right everywhere it had ever run.
9B has four shards and `layers.0.linear_attn.A_log` lives in shard 2, so the
probe dies with a KeyError on the first DeltaNet layer.

So this file runs THE ORIGINAL SCRIPT, verbatim, with `find_checkpoint`
patched to return the whole shard list for the duration.  The measurement is
Track Q's code, not a re-implementation of it — which is the point.

It then adds the cross-check the spec's wording asks for.  Spec 4.1(d) says
the gate port "must come from `qd["gate_sat"]`", and the probe computes the
same two expressions rather than reading a `qd`.  Here that equivalence is
MEASURED at 9B: DeltaNet layer 0 is quantized with the production
`layer_fixed.quant_deltanet` and its `qd["gate_sat"]` is compared, entry for
entry, with the probe's own verdict for that layer.

Usage:  FABLE5_MODEL=9b python evidence/qwen9b/g1/gate_port_probe_9b.py
"""
import os
import runpy
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "ref"))

import layer_fixed as LF          # noqa: E402
import load_qwen35 as LQ          # noqa: E402
import model_select as MS         # noqa: E402

ORIG = os.path.join(ROOT, "evidence", "qwen2b", "q2", "audit",
                    "gate_port_probe.py")

print(f"=== gate_port_probe_9b: running {ORIG} at FABLE5_MODEL={MS.TAG}")
print("=== with LQ.find_checkpoint patched to the FULL shard list "
      "(see this file's header)")
_orig_find = LQ.find_checkpoint
LQ.find_checkpoint = lambda path=None: LQ.find_checkpoints(path)
try:
    runpy.run_path(ORIG, run_name="__main__")
finally:
    LQ.find_checkpoint = _orig_find

# ----------------------------------------------------------------------
# the cross-check: the probe's expressions vs the production qd["gate_sat"]
# ----------------------------------------------------------------------
print()
print("=== cross-check: qd[\"gate_sat\"] from the PRODUCTION quantizer")
print("=== (spec 4.1(d): the gate port must come from qd[\"gate_sat\"]; the")
print("===  probe recomputes the same two expressions, and this measures")
print("===  that the two agree at 9B rather than asserting it)")
cfg = LQ.load_config()
types = cfg["layer_types"]
li = types.index("linear_attention")
md = LQ.load_model(layer_idxs=[li], with_emb=False)
wf = md["layers"][li]["dn"]
qd = LF.quant_deltanet(wf, layer_idx=li)
gs = qd["gate_sat"]
print(f"layer {li} ({types[li]}): qd['gate_sat'] has {len(gs)} entries "
      f"over {len(qd['dt_bias_q12'])} heads")
for h, dt_spec, dt_q, A_spec, A_q in gs:
    print(f"  head {h}: dt_bias_q12 {dt_spec} -> {dt_q}   A_q15 {A_spec} "
          f"-> {A_q}")
# the same two expressions the probe uses, recomputed here from the floats
dt_spec = np.round(np.asarray(wf["dt_bias"]) * (1 << 12)).astype(np.int64)
A_spec = np.round(np.exp(wf["A_log"]) * (1 << 15)).astype(np.int64)
want = [(h, int(dt_spec[h]), int(np.clip(dt_spec[h], LF.DT_Q12_MIN,
                                         LF.DT_Q12_MAX)),
         int(A_spec[h]), int(np.clip(A_spec[h], 0, LF.A_Q15_MAX)))
        for h in range(len(dt_spec))
        if dt_spec[h] != np.clip(dt_spec[h], LF.DT_Q12_MIN, LF.DT_Q12_MAX)
        or A_spec[h] != np.clip(A_spec[h], 0, LF.A_Q15_MAX)]
same = [tuple(int(v) for v in r) for r in gs] == want
print(f"probe expressions == qd['gate_sat'] on layer {li}: "
      f"{'IDENTICAL' if same else 'DIFFER'}  "
      f"({len(gs)} vs {len(want)} saturating heads)")
print(f"max |dt_bias| this layer  : {float(np.abs(wf['dt_bias']).max()):.4f} "
      f"(port +/-8.0)")
print(f"max A = exp(A_log) here   : {float(np.exp(wf['A_log']).max()):.4f} "
      f"(port [0, 8.0))")
if not same:
    raise SystemExit("cross-check FAILED: the probe and the production "
                     "quantizer disagree about which heads saturate")
