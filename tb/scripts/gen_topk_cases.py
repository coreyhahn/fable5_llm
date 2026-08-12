#!/usr/bin/env python3
"""Golden cases for the RUNG-4 S5 TOPK-32 block (docs/RUNG4_SPEC.md).

The block is a sibling of vec_alu inside layer_chan, fed by ONE registered
51-bit bundle {we = t_cp[0] && op_q==10, val = cp_v32, idx = am_g}.  So the
ONLY way to drive it from outside is a real ALU AMAX32 command (opcode 11,
aop 10) over a real scratch region — which is exactly what tb_topk.sv does.
This script is the numpy reference for that stimulus.

REFERENCE SEMANTICS (all derived from rtl/vec_alu.sv, not from prose):

  element e of a command with (srca, len) is the 32-bit LE pair
      v = int32( {mem[srca + 2e + 1], mem[srca + 2e]} )
  because op 10 is `op_pr2`: port a starts at srca, port b at srca+1, both
  stride 2, and cp_v32 = {b_q, a_q}.  cfg_srcb is IGNORED for op 10.

  am_g is an 18-bit GLOBAL element counter.  It is zeroed ONLY by an AMAX32
  command with cfg_p0[0]=1 ("fresh"); every other command — AMAX32 with
  fresh=0, any other ALU op, any non-ALU command, any number of CMD
  dispatches — leaves it running.  It WRAPS at 2^18 (the >2^18 case below
  is the only place that is observable; the production LM head is 248,320
  rows, i.e. 94.7% of the way to the wrap).

  AMAX32 winner: strictly-greater update, so FIRST occurrence wins a tie.

  TOPK-32: a 32-entry list sorted by value descending, ties broken by
  arrival order (= ascending idx), which makes entry[0] identically the
  AMAX32 winner.  Insertion is stable-after-equals.  Once the list holds 32
  entries an arriving element with val <= entry[31].val is REJECTED.

  overflow (sticky) — two readings of "a rejected element tied entry[31]":
     ovf_lit   an ARRIVING element was rejected and its val == entry[31].val
               at that moment.  (the literal spec sentence)
     ovf_disp  ovf_lit, OR an element was DISPLACED off the end of the list
               by an insertion and its val == the value of the NEW entry[31]
               (i.e. the retained boundary is still ambiguous).
  Both are emitted; tb_topk.sv gates on ovf_lit unless +ovf_disp is given.

  complete: no AMAX32 in flight.  Not modelled here (it is a timing
  property); tb_topk.sv checks it directly against `busy`.

Usage: gen_topk_cases.py <out_dir> <seed>
Writes <out_dir>/topk_cases.txt (and prints a one-line summary per case).
"""
import os
import sys

import numpy as np

SBASE = 0          # scratch word base of the element array
NENT = 32          # TOPK depth
IDXW = 18          # am_g width
IDXM = (1 << IDXW) - 1
I32MIN = -(1 << 31)
I32MAX = (1 << 31) - 1


class Ref:
    """Bit-exact model of {AMAX32 running scan} + {TOPK-32 list}."""

    def __init__(self):
        self.am_g = 0
        self.am_first = True
        self.am_idx = 0
        self.am_val = 0
        self.lst = []          # [(val, idx)] sorted desc by val, stable
        self.ovf_lit = False
        self.ovf_disp = False
        self.nelem = 0

    def fresh(self):
        self.am_g = 0
        self.am_first = True
        self.lst = []
        self.ovf_lit = False
        self.ovf_disp = False

    def push(self, v):
        idx = self.am_g & IDXM
        # ---- AMAX32 (rtl/vec_alu.sv op 10) ----
        if self.am_first or v > self.am_val:
            self.am_val = v
            self.am_idx = idx
        self.am_first = False
        self.am_g = (self.am_g + 1) & IDXM
        self.nelem += 1
        # ---- TOPK-32 ----
        if len(self.lst) < NENT:
            pos = 0
            while pos < len(self.lst) and self.lst[pos][0] >= v:
                pos += 1
            self.lst.insert(pos, (v, idx))
            return
        if v > self.lst[NENT - 1][0]:
            pos = 0
            while pos < NENT and self.lst[pos][0] >= v:
                pos += 1
            self.lst.insert(pos, (v, idx))
            dropped = self.lst.pop()
            if dropped[0] == self.lst[NENT - 1][0]:
                self.ovf_disp = True
        else:
            if v == self.lst[NENT - 1][0]:
                self.ovf_lit = True
                self.ovf_disp = True


def pack_words(vals):
    """int32 element array -> 16-bit scratch words, LE pairs."""
    a = np.asarray(vals, dtype=np.int64).astype(np.uint32)
    lo = (a & 0xFFFF).astype(np.uint16)
    hi = ((a >> 16) & 0xFFFF).astype(np.uint16)
    w = np.empty(2 * len(a), dtype=np.uint16)
    w[0::2] = lo
    w[1::2] = hi
    return w


def build(name, vals, cmds, note=""):
    """cmds = [(elem_off, len, fresh)] over the element array `vals`."""
    words = pack_words(vals)
    ref = Ref()
    for (off, ln, fresh) in cmds:
        if fresh:
            ref.fresh()
        for e in range(ln):
            ref.push(int(np.int32(np.uint32(vals[off + e]))))
    return {
        "name": name, "words": words, "note": note,
        "cmds": [(SBASE + 2 * off, ln, fresh) for (off, ln, fresh) in cmds],
        "ref": ref,
    }


def main():
    out, seed = sys.argv[1], int(sys.argv[2])
    os.makedirs(out, exist_ok=True)
    rng = np.random.default_rng(seed)
    cases = []

    def r32(n, lo=I32MIN, hi=I32MAX):
        return rng.integers(lo, hi, size=n, dtype=np.int64, endpoint=True)

    # ---------------------------------------------------------------- 1
    # FEWER THAN 32 ELEMENTS: count must stop at nelem, entry[0] must still
    # be the AMAX winner, and no overflow is possible.
    for n in (1, 2, 8, 17, 31):
        v = r32(max(n, 4))
        cases.append(build(f"small{n}", v, [(0, n, 1)],
                           "count<32, no overflow possible"))

    # exactly 32, and 33 (the first element that can ever be rejected)
    for n in (32, 33):
        cases.append(build(f"edge{n}", r32(n + 4), [(0, n, 1)],
                           "the count==32 boundary"))

    # ---------------------------------------------------------------- 2
    # RAILS: +-2^31 present many times.  Exercises the signed compare at
    # both ends and guarantees ties at the very top and the very bottom.
    v = list(r32(200))
    for p in (0, 5, 77, 199, 3, 100):
        v[p] = I32MAX
    for p in (1, 6, 78, 198):
        v[p] = I32MIN
    cases.append(build("rails", np.array(v, dtype=np.int64), [(0, 200, 1)],
                       "6x +2^31-1 and 4x -2^31"))

    # every element is a rail: the list is 32 copies of I32MAX and overflow
    # must be sticky-set by the 33rd
    v = np.array([I32MAX] * 40 + [I32MIN] * 40, dtype=np.int64)
    cases.append(build("rails_only", v, [(0, 80, 1)],
                       "40x MAX then 40x MIN — pure tie storm"))

    # ---------------------------------------------------------------- 3
    # TIES: a tiny value alphabet so the top-32 boundary is ambiguous by
    # construction.  Three alphabets of different widths.
    for (an, ln) in ((4, 300), (8, 500), (40, 600)):
        alpha = np.unique(r32(an))
        v = alpha[rng.integers(0, len(alpha), size=ln)]
        cases.append(build(f"ties{an}", v, [(0, ln, 1)],
                           f"{len(alpha)}-symbol alphabet over {ln} elements"))

    # a case engineered so the 33rd element ties entry[31] EXACTLY once
    v = np.array(sorted(rng.choice(np.arange(1000, 9000), 32, replace=False),
                        reverse=True) + [0], dtype=np.int64)
    v[32] = v[31]                       # the tying rejected element
    cases.append(build("tie_at_31", v, [(0, 33, 1)],
                       "one rejected element, ties entry[31] -> ovf_lit"))

    # the displaced-tie variant: entries 30 and 31 are equal, then a bigger
    # element arrives.  ovf_lit stays 0; ovf_disp goes 1.
    v = np.array(sorted(rng.choice(np.arange(1000, 9000), 31, replace=False),
                        reverse=True), dtype=np.int64)
    v = np.append(v, v[30])             # entry 31 == entry 30
    v = np.append(v, I32MAX)            # displaces entry 31
    cases.append(build("tie_displaced", v, [(0, 33, 1)],
                       "displaced element ties the NEW entry[31] "
                       "-> ovf_disp only (ovf_lit stays 0)"))

    # ---------------------------------------------------------------- 4
    # CHAINED CHUNKS: fresh only on the first.  This is the LM-head shape
    # (122 chunks of 2048) in miniature, and the case that proves am_g and
    # the list survive a command boundary.
    v = r32(4096)
    cases.append(build("chain4", v,
                       [(0, 1024, 1), (1024, 1024, 0),
                        (2048, 1024, 0), (3072, 1024, 0)],
                       "4x1024 chained, fresh on chunk 0 only"))

    # the same data re-scanned with fresh on EVERY chunk: the answer must
    # collapse to the last chunk alone (the reset-is-fresh-only proof).
    cases.append(build("chain4_allfresh", v,
                       [(0, 1024, 1), (1024, 1024, 1),
                        (2048, 1024, 1), (3072, 1024, 1)],
                       "fresh on every chunk -> only chunk 3 survives"))

    # ragged chunk lengths, including 1-element chunks
    cases.append(build("chain_ragged", v,
                       [(0, 1, 1), (1, 7, 0), (8, 1, 0), (9, 2047, 0),
                        (2056, 33, 0), (2089, 1000, 0)],
                       "1/7/1/2047/33/1000 chained"))

    # ---------------------------------------------------------------- 5
    # MORE THAN 2^18 ELEMENTS: am_g wraps.  4096 elements in scratch, 132
    # chunks of 2048 taken at rotating offsets = 270,336 elements
    # (2^18 = 262,144).  The winner's index is therefore a WRAPPED index
    # and the reference above models exactly that.
    v = r32(4096)
    offs = [int(rng.integers(0, 1024)) * 2 for _ in range(132)]
    cases.append(build("wrap18", v, [(offs[i], 2048, 1 if i == 0 else 0)
                                     for i in range(132)],
                       "270,336 elements > 2^18 = 262,144 -> am_g wraps"))

    # exactly-at-the-wrap: 128 chunks of 2048 = 262,144 = 2^18, so the last
    # element sits at index 2^18-1 and the counter lands back on 0.
    cases.append(build("wrap18_exact", v, [(offs[i], 2048, 1 if i == 0 else 0)
                                           for i in range(128)],
                       "exactly 2^18 elements"))

    # ---------------------------------------------------------------- write
    path = os.path.join(out, "topk_cases.txt")
    with open(path, "w") as f:
        f.write(f"{len(cases)}\n")
        for c in cases:
            r = c["ref"]
            f.write(f"{c['name']} {len(c['words'])} {len(c['cmds'])} "
                    f"{len(r.lst)} {len(r.lst)} "
                    f"{1 if r.ovf_lit else 0} {1 if r.ovf_disp else 0} "
                    f"{r.am_idx} {(int(r.am_val) & 0xFFFFFFFF):08x} "
                    f"{r.nelem}\n")
            for w in c["words"]:
                f.write(f"{int(w):04x}\n")
            for (sa, ln, fr) in c["cmds"]:
                f.write(f"{sa} {ln} {fr}\n")
            for (val, idx) in r.lst:
                f.write(f"{(int(val) & 0xFFFFFFFF):08x} {idx}\n")
    tot = 0
    for c in cases:
        r = c["ref"]
        tot += r.nelem
        print(f"  {c['name']:16s} nelem={r.nelem:7d} cmds={len(c['cmds']):3d} "
              f"count={len(r.lst):2d} ovf_lit={int(r.ovf_lit)} "
              f"ovf_disp={int(r.ovf_disp)} amax=({r.am_idx},"
              f"{(int(r.am_val) & 0xFFFFFFFF):08x})  {c['note']}")
    print(f"wrote {path}: {len(cases)} cases, {tot} elements total")


if __name__ == "__main__":
    main()
