#!/usr/bin/env python3
"""fix1_checks.py — the two arithmetic claims fix round 1 ADDS to the study.

(1) I-1: under the midpoint pipeline cut, how many DeltaNet and full-attention
    layers does each board hold?  Counted from each checkpoint's OWN
    `layer_types` list, not from `full_attention_interval`, and checked against
    the SLD/SST envelope N_DN = 24 / N_KV = 8 (rtl/layer_chan.sv:362-363).

(2) I-2: the MEASURED 0.8B W4 g128 step's bucket shares, from the committed
    equation at evidence/qwen_next/feas/f05_toks_model.log:61 and the (r, m)
    the same file solves.  This is the point that refutes "the first
    layer-bound target in this project's history".
"""
import json
import os

ROOT = "/home/cah/r2d2/code/fpga/fable5_llm"
GEOM = json.load(open(os.path.join(ROOT,
                                   "evidence/qwen_next/feas2/geometry2_raw.json")))
N_DN, N_KV = 24, 8          # rtl/layer_chan.sv:362-363

print("=" * 78)
print("(1) I-1 — the SLD/SST layer envelope under the midpoint pipeline cut")
print("=" * 78)
print(f"    the envelope: N_DN = {N_DN}, N_KV = {N_KV}  "
      "(rtl/layer_chan.sv:362-363), 5-bit sd_layer_a carries 0..31")
print()
for repo, short in (("Qwen/Qwen3.5-9B", "9B"),
                    ("Qwen/Qwen3.5-27B", "27B"),
                    ("Qwen/Qwen3.5-35B-A3B", "35B-A3B")):
    t = GEOM[repo]["config"]["layer_types"]
    NL = len(t)
    cut = NL // 2
    whole = (t.count("linear_attention"), t.count("full_attention"))
    a = (t[:cut].count("linear_attention"), t[:cut].count("full_attention"))
    b = (t[cut:].count("linear_attention"), t[cut:].count("full_attention"))
    def verdict(dn, kv):
        if dn > N_DN or kv > N_KV:
            return "FAIL"
        return "PASS, EXACTLY at the ceiling" if (dn == N_DN and kv == N_KV) \
            else f"PASS (room: {N_DN-dn} DN, {N_KV-kv} GQA)"
    print(f"  {short:9s} L={NL:3d}  cut@{cut:2d}")
    print(f"      whole model   {whole[0]:3d} DN / {whole[1]:3d} GQA   "
          f"{verdict(*whole)}")
    print(f"      board A [0,{cut})   {a[0]:3d} DN / {a[1]:3d} GQA   {verdict(*a)}")
    print(f"      board B [{cut},{NL})  {b[0]:3d} DN / {b[1]:3d} GQA   {verdict(*b)}")
    # any OTHER cut that still passes?
    ok = [c for c in range(1, NL)
          if t[:c].count("linear_attention") <= N_DN
          and t[:c].count("full_attention") <= N_KV
          and t[c:].count("linear_attention") <= N_DN
          and t[c:].count("full_attention") <= N_KV]
    print(f"      cuts of {NL} that pass on BOTH boards: {len(ok)} "
          f"{'(' + ', '.join(str(c) for c in ok) + ')' if len(ok) <= 12 else '(' + str(min(ok)) + '..' + str(max(ok)) + ')'}")
    print()

print("=" * 78)
print("(2) I-2 — the MEASURED 0.8B W4 g128 step, bucket by bucket")
print("=" * 78)
# evidence/qwen_next/feas/f05_toks_model.log:61, verbatim:
#   0.8B W4: matvec 5.4754*r + movers 11.332*m + layer 15.128 = 31.5023
r, m = 1.1037, 0.9117            # the same file's solve
mv, mo, lay = 5.4754 * r, 11.332 * m, 15.128
step = mv + mo + lay
print(f"    matvec 5.4754 x r={r}  = {mv:7.3f} ms  {100*mv/step:5.1f} %")
print(f"    movers 11.332 x m={m}  = {mo:7.3f} ms  {100*mo/step:5.1f} %")
print(f"    layer  (MEASURED)      = {lay:7.3f} ms  {100*lay/step:5.1f} %")
print(f"    step                   = {step:7.4f} ms  (the log's 31.5023)")
print()
print("    So the shipped 0.8B at W4 g128 was LAYER-BOUND at "
      f"{100*lay/step:.1f} % on silicon,")
print("    ABOVE the 35B-A3B's modelled 47.4 %.  'the first layer-bound target")
print("    in this project's history' is refuted by the study's own calibration")
print("    input, and the defensible claim is 'the first LARGE target to come")
print("    back layer-bound'.")
