#!/usr/bin/env python3
"""Q6 supplement: gate-port occupancy measured BEFORE the production clamp.

Why this exists.  `audit_ranges.py` sections 1 and 3 feed `ConstAudit` /
the decay chain with `qd["dt_bias_q12"]` and `qd["A_q15"]` — the values
`layer_fixed.quant_deltanet` STORES.  Since commit 82781e5 (2026-07-26,
i.e. AFTER ref/audit_ranges_report.md was generated — its header stamps
repo `763396b`; `556dfe8` is the commit that added the report to the tree)
those two are `np.clip`ped into the frozen ports at layer_fixed.py:805-806

    dt_q = np.clip(dt_spec, DT_Q12_MIN, DT_Q12_MAX)   # int16
    A_q  = np.clip(A_spec,  0, A_Q15_MAX)             # uint18

so the auditor can no longer SEE an out-of-port weight: it reports
`0 / 288` out-of-range and a max pinned exactly at the rail, while its own
"max used (real weights)" column — computed from the FLOAT weights — still
prints the true 10.58 / 13.06 at 0.8B.  ("PASS `A` — max 10.5843 < 8.0".)

This probe measures the SPEC values with the same expressions
`quant_deltanet` uses, and runs the section-3 decay chain three ways:

  spec  : unbounded ports (what the float model means)
  prod  : the SATURATED values quant_deltanet stores today  <- what ships
  wrap  : the 18-bit / int16 truncation `Mach.W_raw` would do without the
          clamp (what ref/audit_ranges_report.md's "decay corruption" row
          measured back when nothing clamped)

Weights-only; the quantizers are imported, not re-implemented.
"""
import sys

import numpy as np

sys.path.insert(0, "/home/cah/r2d2/code/fpga/fable5_llm/ref")
import fixedpoint as fp         # noqa: E402
import layer_fixed as LF        # noqa: E402
import layer_ref as LR          # noqa: E402
import load_qwen35 as LQ        # noqa: E402
import model_select as MS       # noqa: E402
import w4a8_ref as W4           # noqa: E402

I64 = np.int64
I16_MIN, I16_MAX = -32768, 32767
U18_MAX = (1 << 18) - 1


def decay_of(Aq, dtq):
    """audit_ranges.py section 3 chain, verbatim."""
    sp = fp.softplus_q(int(dtq))
    g = -W4.rshift_round(I64(int(Aq)) * sp, 11)
    return min(int(W4.rshift_round(I64(fp.exp_neg_q(int(min(g, 0)))), 15)),
               32767)


st = LQ.SafeTensors(LQ.find_checkpoint())
cfg = LQ.load_config()
types = cfg["layer_types"]
p = LQ.TEXT_PREFIX
print(f"model          : {MS.TAG}  ({MS.REPO_DIR})")
print(f"checkpoint     : {LQ.find_checkpoint()}")
print(f"header sha256  : {st.header_sha}")
print(f"DN layers      : {types.count('linear_attention')} x LNH={LR.LNH} heads")
print(f"clamps in force: DT_Q12=[{LF.DT_Q12_MIN},{LF.DT_Q12_MAX}] "
      f"A_Q15=[0,{LF.A_Q15_MAX}]  (layer_fixed.py:805-806)")
print()

rows = []
convmax = 0.0
for i, t in enumerate(types):
    if t != "linear_attention":
        continue
    A_log = np.asarray(st.get(f"{p}layers.{i}.linear_attn.A_log"),
                       dtype=np.float64)
    dt = np.asarray(st.get(f"{p}layers.{i}.linear_attn.dt_bias"),
                    dtype=np.float64)
    cw = np.asarray(st.get(f"{p}layers.{i}.linear_attn.conv1d.weight"),
                    dtype=np.float64)
    convmax = max(convmax, float(np.abs(cw).max()))
    # the two production expressions, PRE-clamp (layer_fixed.py:803-804)
    dt_spec = np.round(dt * (1 << 12)).astype(I64)
    A_spec = np.round(np.exp(A_log) * (1 << 15)).astype(I64)
    dt_prod = np.clip(dt_spec, LF.DT_Q12_MIN, LF.DT_Q12_MAX)
    A_prod = np.clip(A_spec, 0, LF.A_Q15_MAX)
    for h in range(len(dt_spec)):
        dtw = int(dt_spec[h]) & 0xFFFF
        dtw -= 0x10000 if dtw >= 0x8000 else 0
        rows.append(dict(
            layer=i, head=h, A=float(np.exp(A_log[h])), dt=float(dt[h]),
            A_spec=int(A_spec[h]), dt_spec=int(dt_spec[h]),
            A_prod=int(A_prod[h]), dt_prod=int(dt_prod[h]),
            d_spec=decay_of(A_spec[h], dt_spec[h]),
            d_prod=decay_of(A_prod[h], dt_prod[h]),
            d_wrap=decay_of(int(A_spec[h]) & U18_MAX, dtw)))

n = len(rows)
nA = sum(r["A_spec"] > U18_MAX for r in rows)
ndt = sum(not (I16_MIN <= r["dt_spec"] <= I16_MAX) for r in rows)
nprod = sum(r["d_prod"] != r["d_spec"] for r in rows)
nwrap = sum(r["d_wrap"] != r["d_spec"] for r in rows)
Amax = max(r["A"] for r in rows)
dtmax = max(abs(r["dt"]) for r in rows)
print(f"heads                                   : {n}")
print(f"max A = exp(A_log)      (port [0, 8.0)) : {Amax:.4f}")
print(f"max |dt_bias|           (port +/-8.0)   : {dtmax:.4f}")
print(f"max |conv_w|            (port +/-4.0)   : {convmax:.4f}  "
      f"(CW_F={LF.CW_F}, stored UNCLIPPED -> Mach.W asserts)")
print(f"A   out of uint18 Q15 BEFORE the clamp  : {nA} / {n}")
print(f"dt  out of int16  Q12 BEFORE the clamp  : {ndt} / {n}")
print(f"decay CHANGED by the production clamp   : {nprod} / {n}")
print(f"decay CHANGED by 18-bit/int16 wrap      : {nwrap} / {n}  "
      f"(pre-82781e5 behaviour)")
print()
bad = [r for r in rows if r["A_spec"] > U18_MAX
       or not (I16_MIN <= r["dt_spec"] <= I16_MAX)
       or r["d_prod"] != r["d_spec"]]
if bad:
    print("offending heads (decay in Q15 / as a fraction):")
    print("  layer head |      A    A_q15(spec) |     dt   dt_q12(spec) |"
          " decay spec ->   prod  |    wrap")
    for r in bad:
        print(f"  L{r['layer']:<4d} h{r['head']:<3d} | {r['A']:8.4f} "
              f"{r['A_spec']:>11d} | {r['dt']:7.3f} {r['dt_spec']:>12d} | "
              f"{r['d_spec']:>10d} -> {r['d_prod']:>6d} | {r['d_wrap']:>7d}"
              f"   ({r['d_spec'] / 32768:.5f} -> {r['d_prod'] / 32768:.5f})")
else:
    print("no head exceeds either gate port before the clamp: the clamp is a "
          "no-op on this checkpoint and sections 1/3 of the report are exact.")
print()
n1 = sum(r["d_spec"] >= 32767 for r in rows)
n0 = sum(r["d_spec"] == 0 for r in rows)
print(f"decay dynamics at a=0 (SPEC): {n1}/{n} pinned at the no-decay rail "
      f"32767, {n0}/{n} collapse to 0")
