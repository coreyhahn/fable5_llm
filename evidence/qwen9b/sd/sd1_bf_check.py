#!/usr/bin/env python3
"""sd1_bf_check.py — Task SD1 deliverable 2: are the substituted commands
bit-identical on EVERY instance in the shipped artifact, not only at the
.txt's sampled checkpoints?

  FABLE5_MODEL=9b python evidence/qwen9b/sd/sd1_bf_check.py [<prefix>]   (default: model_9b_s1)

Replays tb/scripts/w9/model_9b_s1.txt with the SAME executor the SEQ gate
uses (ref/seq_model.TxtReplay, so every R/E/A assertion of the .txt is still
checked) and wraps gen_layer_script.Mach.alu — in THIS process only, nothing
on disk changes — to evaluate, at every instance, what the .e4 command that
replaces a .txt command would have produced from the same scratch state:

  (c1) every DN head SHIFT32(k_h) vs DYNQ16  (layer_fixed.dynq16_fx):
       same k?  same 128 int16 outputs?
  (c2) every DN head SCALE(m_q15) vs VN EPS-NORM (layer_fixed.eps_norm_fx
       from the SHIFT32 output and k): same scale?  same 128 outputs?
  (d)  every gated-attention block: the host's literal k_a vs the probe's
       attn_o_shift(max |pair(a) * b|) over all NQ heads.

The fused dequant (a) and the SILU32 re-chunk (b) are identical by
construction (same rshr64s/clip formula, same elements) and are NOT
re-checked here; the memo cites the source lines instead.
Pure Python, no simulation; stdout only.
"""
import os
import sys
import time

import numpy as np

import sd1_common as C
from sd1_common import GLS, LR, SF
import seq_model as SM
import layer_fixed as LF
import hwmap as HW

LDV, HD, NQ = LR.LDV, LR.HD, LR.NQ
I64 = np.int64
orig_alu = GLS.Mach.alu
st = {"pend": None, "blk": [], "blk_p0": []}
c1 = {"n": 0, "k_eq": 0, "y_eq": 0}
c2 = {"n": 0, "m_eq": 0, "y_eq": 0, "max_d": 0, "el_diff": 0,
      "m_d_max": 0, "first_bad": None, "bad": []}
d = {"blocks": 0, "k_eq": 0, "ks": {}}


def hooked(self, op, n, p0, srca, srcb, dst):
    if op == 1 and n == LDV:                           # DN head SHIFT32
        x = self.pairs(srca, n).copy()
        y, k = LF.dynq16_fx(x)
        orig_alu(self, op, n, p0, srca, srcb, dst)
        out = self.mem[dst:dst + n].copy()
        c1["n"] += 1
        c1["k_eq"] += int(k == p0)
        c1["y_eq"] += int(np.array_equal(np.asarray(y, dtype=I64), out))
        st["pend"] = (dst, p0)
        return
    if (op == 2 and n == LDV and st["pend"] is not None
            and srca == st["pend"][0]):                # the SCALE m_q15
        k = st["pend"][1]
        st["pend"] = None
        o16 = self.mem[srca:srca + n].copy()
        m_int = LF.eps_norm_scale(o16, k, note=False)
        y_eps = np.asarray(LF.eps_norm_fx(o16, k, note=False), dtype=I64)
        orig_alu(self, op, n, p0, srca, srcb, dst)
        y_txt = self.mem[dst:dst + n].copy()
        c2["n"] += 1
        c2["m_eq"] += int(m_int == p0)
        c2["m_d_max"] = max(c2["m_d_max"], abs(m_int - p0))
        dd = np.abs(y_eps - y_txt)
        c2["y_eq"] += int(not dd.any())
        c2["el_diff"] += int((dd != 0).sum())
        c2["max_d"] = max(c2["max_d"], int(dd.max()))
        if dd.any():
            i = c2["n"] - 1
            c2["bad"].append((i // (LR.LNH * 24), (i // LR.LNH) % 24, i % LR.LNH,
                              int((dd != 0).sum())))
        if dd.any() and c2["first_bad"] is None:
            c2["first_bad"] = (c2["n"] - 1, k, p0, m_int, int(dd.max()))
        return
    st["pend"] = None
    if op == 8 and n == HD and 0 <= p0 < 64:           # attention EMUL32
        prod = self.pairs(srca, n) * self.mem[srcb:srcb + n]
        st["blk"].append(int(np.abs(prod).max()))
        st["blk_p0"].append(p0)
        if len(st["blk"]) == NQ:
            ka = LF.attn_o_shift(max(st["blk"]), note=False)
            d["blocks"] += 1
            d["k_eq"] += int(all(p == ka for p in st["blk_p0"]))
            d["ks"][ka] = d["ks"].get(ka, 0) + 1
            st["blk"], st["blk_p0"] = [], []
    return orig_alu(self, op, n, p0, srca, srcb, dst)


GLS.Mach.alu = hooked

base = sys.argv[1] if len(sys.argv) > 1 else C.BASE   # a model_9b_s<N> prefix
print(f"=== replaying {base}.txt through seq_model.TxtReplay (the gate's "
      f".txt side), .txt sha256 {C.sha256(base + '.txt')}")
rb = HW.load_weights_manifest(base)[1]["emb_row_bytes"]
nemb = os.path.getsize(base + ".emb.bin") // rb
emb = np.memmap(base + ".emb.bin", dtype="<i2", mode="r").reshape(nemb, rb // 2)
reg = SM.StateRegion.load(base)
t0 = time.time()
rep = SM.TxtReplay(base + ".txt", emb=emb, region=reg).run()
print(f"  {rep.ncmd} commands, checks {rep.checks}, tokens {rep.tokens} "
      f"({time.time() - t0:.1f}s) — every R/E/A assertion held")
print(f"\n(c1) DN head SHIFT32(k_h) vs DYNQ16: {c1['n']} heads; k equal on "
      f"{c1['k_eq']}; all 128 outputs equal on {c1['y_eq']}")
print(f"(c2) DN head SCALE(m_q15) vs VN EPS-NORM: {c2['n']} heads; integer "
      f"scale == m_q15 on {c2['m_eq']} (max |dm| {c2['m_d_max']}); all 128 "
      f"outputs equal on {c2['y_eq']}; differing elements {c2['el_diff']}; "
      f"max |delta| {c2['max_d']} LSB; first differing head "
      f"(index, k, m_q15, m_int, |d|) = {c2['first_bad']}")
print(f"     differing heads as (step 0-based, DN layer 0..23, head, elements): "
      f"{c2['bad']}")
print(f"(d)  gated-attention blocks: {d['blocks']}; host k_a == probe k_a on "
      f"{d['k_eq']}; k_a histogram {dict(sorted(d['ks'].items()))}")
print(f"\n  checkpoint coverage of (c): gen_layer_script's R(ON, 256) samples "
      f"{256 // LDV} of {LR.LNH} heads per DN layer per step")
ok = (c1["n"] == c1["k_eq"] == c1["y_eq"] and d["blocks"] == d["k_eq"])
print(f"\nSD1_BF_CHECK: c1/d {'IDENTICAL on every instance' if ok else 'DIFFER'}"
      f"; c2 {'IDENTICAL on every instance' if c2['y_eq'] == c2['n'] else 'DIFFERS on %d of %d heads' % (c2['n'] - c2['y_eq'], c2['n'])}")
