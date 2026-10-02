#!/usr/bin/env python3
"""Q6 supplement: enumerate the matrices whose W4 reconstruction error
exceeds the project's own 15% bound (w4a8_ref._selftest's `assert rel<0.15`).

audit_ranges.py prints at most 12 names.  Only the SMALL projections can be
involved (every large family's per-family max is < 13% in both reports), so
this re-measures just those with the production quantizer and lists all of
them, per model.  Same expression audit_ranges.audit_w4 uses for `rel`.
"""
import sys
import numpy as np
sys.path.insert(0, "/home/cah/r2d2/code/fpga/fable5_llm/ref")
import layer_fixed as LF        # noqa: E402
import load_qwen35 as LQ        # noqa: E402
import model_select as MS       # noqa: E402
import w4a8_ref as W4           # noqa: E402

st = LQ.SafeTensors(LQ.find_checkpoint())
types = LQ.load_config()["layer_types"]
p = LQ.TEXT_PREFIX
SMALL = {"linear_attention": [("dn.in_a", "linear_attn.in_proj_a.weight"),
                              ("dn.in_b", "linear_attn.in_proj_b.weight")],
         "full_attention": [("attn.k_proj", "self_attn.k_proj.weight"),
                            ("attn.v_proj", "self_attn.v_proj.weight"),
                            ("attn.q_proj", "self_attn.q_proj.weight"),
                            ("attn.o_proj", "self_attn.o_proj.weight")]}
out = []
for i, t in enumerate(types):
    for name, tn in SMALL[t]:
        Wf = np.asarray(st.get(f"{p}layers.{i}.{tn}"), dtype=np.float64)
        q = LF.quant_linear(Wf)
        eff = q["m"].astype(np.float64) * np.exp2(q["e"] - 15)
        N, K = Wf.shape
        NG = K // W4.G
        d = (q["w4"].reshape(N, NG, W4.G).astype(np.float64)
             * eff[:, :, None] - Wf.reshape(N, NG, W4.G))
        rel = float(np.sqrt((d * d).sum() / (Wf * Wf).sum()))
        out.append((rel, f"L{i}.{name}", Wf.shape))
out.sort(reverse=True)
print(f"model {MS.TAG}: {len(out)} small matrices re-measured "
      f"(production quant_linear)")
over = [o for o in out if o[0] > 0.15]
print(f"  above the 15% bound: {len(over)}")
for rel, lbl, shp in over:
    print(f"    {lbl:<18s} {shp[0]}x{shp[1]}  rel = {rel:.2%}")
print(f"  worst 5 overall:")
for rel, lbl, shp in out[:5]:
    print(f"    {lbl:<18s} {shp[0]}x{shp[1]}  rel = {rel:.2%}")
