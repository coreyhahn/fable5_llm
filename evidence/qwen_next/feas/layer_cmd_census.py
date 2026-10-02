#!/usr/bin/env python3
"""layer_cmd_census.py — the layer-unit command census, from the REAL 0.8B stream.

Review round 2, finding 1: this study's LOW layer bracket assumed the DeltaNet
lane array could absorb 32 value heads in the cycles it spends on 16.  The
as-built RTL refutes that:

  rtl/dn_step.sv:13-14   "128 parallel lanes; lane math is pipelined
                          mult->shift->accumulate so every stage fits 250 MHz
                          (~10 cycles/row -> ~1300 cycles/head)"
  rtl/dn_step.sv:1       "one gated-delta-rule recurrence step for ONE head"
  rtl/layer_chan.sv:525  ONE `dn_step u_dn (...)` instance
  rtl/layer_chan.sv:1036   `dn_head <= arg0[3:0];`  -- the head is a per-COMMAND
                          dispatch argument
                          [CLASS B, kept as the record.  :891 is this
                          citation's number in the FEASIBILITY STUDY's own
                          tree and it is the number G3.4 started from
                          (8138d66); the QUOTATION had ALREADY died before
                          then -- `git log -S "dn_head <= arg0[3:0]"` lands
                          on 8ef57a8 (G3.1), which took the field to five
                          bits, so 8138d66:rtl/layer_chan.sv:1036 is a
                          comment about 16-bit scratch addressing.  This is
                          pre-existing drift G3.4 INHERITED, not drift it
                          caused; what G3.4 changed is the banking behind
                          the field.  Post-G3.4 site:
                          rtl/layer_chan.sv:1513 `dn_head <= arg0[4:0];`
                          (2026-09-02, Task 10 fix round 2)]
  ref/gen_layer_script.py:2002  `for h in range(LR.LNH):` emitting
                          vn / alu / vn / dnst PER HEAD
                          [G3.4 fix round 3: this read :1074-1081 at the
                          study's own base and :1101-1108 after two passes
                          renumbered it, and BOTH are the `_aud` ALU-audit
                          block -- the pointer never named the loop.  A
                          renumber tracks a LINE, not a MEANING.]

Heads are the OUTER loop and they are SERIALIZED through one 128-lane engine.
16 -> 32 value heads therefore doubles the whole per-head loop.  There is no
idle lane capacity: the array is 128 wide working on LDK=128 rows.

So this script stops modelling the layer term from an abstract "element count"
and counts the ACTUAL emitted layer commands, per opcode, with their length
fields, from `tb/scripts/model_v2_s1.txt` -- the 0.8B stream the 15.128
ms/token measurement was taken on.

PROVENANCE, stated exactly (re-review N1).  That file is **gitignored** --
`.gitignore:13` `tb/scripts/model_*`, because it is ~45 MB of a ~950 MB
artifact set -- so it is on disk here, not in the repo.  That does NOT make
the census unreproducible, and the reason is stronger than "it happens to be
sitting there": `ref/scripts/regen_gate.sh` **byte-locks exactly this file**.
The gate re-emits it from committed sources, checks
`sha256(model_v2_s1.e.seq)` against the frozen
`GOLD_SEQ_SHA=a69864d2...` (`:5`, `:38-40`) and then runs
`cmp $TMP/model_v2_s1.txt ../tb/scripts/model_v2_s1.txt` (`:41`), failing
`REGEN_GATE_FAIL_TXT` on any difference.  So from a clean checkout:

    make -C tb model_script_s1      # or ref/scripts/regen_gate.sh, which
                                    # regenerates AND proves byte-identity

reproduces this exact input.  The census below is therefore reproducible from
committed sources via a committed gate, which is a better guarantee than an
untracked file that merely exists.

The analytic count model is then validated against that census before being
extrapolated.

Opcodes (docs/SEQ_ISA.md, rtl/layer_chan.sv:149-151 and the emitters):
   1 VN     n = 1 << arg0[5:2]
   2 VNW    n = arg0[10:0]  (0 encodes 2048)
   4 ROPE
   5 KVAP
   6 ATTN
   7 CONV   nch = arg0[25:13]
   8 DNST   one head
   9 GATE
  11 ALU    n = arg0[16:4]
"""
import collections
import json
import os
import sys

SCRIPT = "/home/cah/r2d2/code/fpga/fable5_llm/tb/scripts/model_v2_s1.txt"

OPNAME = {1: "VN", 2: "VNW", 3: "CONVW", 4: "ROPE", 5: "KVAP", 6: "ATTN",
          7: "CONV", 8: "DNST", 9: "GATE", 10: "EMB", 11: "ALU", 12: "AMAX"}


def length_of(op, a0):
    if op == 1:
        return 1 << ((a0 >> 2) & 0xF)
    if op == 2:
        n = a0 & 0x7FF
        return n if n else 2048
    if op == 7:
        return (a0 >> 13) & 0x1FFF
    if op == 11:
        return (a0 >> 4) & 0x1FFF
    return 0


def census(path):
    cnt = collections.Counter()
    ln = collections.Counter()
    per_vn_len = collections.Counter()
    per_alu_len = collections.Counter()
    with open(path) as fh:
        for line in fh:
            if not line.startswith("C "):
                continue
            _, op, a0, a1, a2 = line.split()
            op = int(op, 16)
            a0 = int(a0, 16)
            cnt[op] += 1
            n = length_of(op, a0)
            ln[op] += n
            if op == 1:
                per_vn_len[n] += 1
            if op == 11:
                per_alu_len[n] += 1
    return cnt, ln, per_vn_len, per_alu_len


# ----------------------------------------------------------------------
# the ANALYTIC count model, read off the emitters, for one decode token
# ----------------------------------------------------------------------
def analytic(H, FFN, nDN, nGQA, LNH, LDK, LDV, NQ, NKV, HD, CONV_DIM, VOCAB):
    """(counts, length-sums) per token — mirrors gen_layer_script's blocks."""
    c, L = collections.Counter(), collections.Counter()

    def add(op, n, k=1):
        c[op] += k
        L[op] += n * k

    NL = nDN + nGQA
    for _ in range(NL):                       # every layer: ln1 + ln2
        add(1, H, 2)                          # VN mode 0/1 over H
        add(2, H, 2)                          # VNW weight loads
        # MLP: silu(gate) + gate*up + residual add
        add(11, FFN, 2)                       # silu, mul
        add(11, H, 1)                         # residual add
        add(11, H, 1)                         # DYNQ8 of the normed vector
    for _ in range(nDN):                      # DeltaNet body
        add(7, CONV_DIM, 1)                   # CONV over CONV_DIM
        add(9, LNH, 1)                        # GATE over LNH
        for _h in range(LNH):                 # ref/gen_layer_script.py:2002
            add(1, LDK, 2)                    # l2(q), l2(k)
            add(11, LDK, 1)                   # q * 1/sqrt(dk)
            add(8, LDK, 1)                    # DNST — ONE HEAD
            add(11, LDV, 2)                   # block-float + gated norm
        add(11, LDV, 1)                       # silu(z) * out
    for _ in range(nGQA):                     # attention body
        add(4, NQ * HD + NKV * HD, 1)         # ROPE
        add(5, NKV * HD, 1)                   # KVAP
        add(6, NQ * HD, 1)                    # ATTN
        add(11, NQ * HD, 2)                   # gate + pack
    add(1, H, 1)                              # final norm
    add(2, H, 1)
    add(11, H, 1)                             # final DYNQ8
    add(12, VOCAB, 1)                         # AMAX over the vocabulary
    return c, L


GEOM = {
    #        H    FFN   nDN nGQA LNH LDK LDV NQ NKV  HD  CONV  VOCAB
    "0.8B": (1024, 3584, 18, 6, 16, 128, 128, 8, 2, 256, 6144, 248320),
    "2B":   (2048, 6144, 18, 6, 16, 128, 128, 8, 2, 256, 6144, 248320),
    "4B":   (2560, 9216, 24, 8, 32, 128, 128, 16, 4, 256, 8192, 248320),
    "9B":   (4096, 12288, 24, 8, 32, 128, 128, 16, 4, 256, 8192, 248320),
}

if __name__ == "__main__":
    print("=" * 78)
    print("A. CENSUS of the 0.8B stream  tb/scripts/model_v2_s1.txt")
    print("   (gitignored on disk -- .gitignore:13 -- but byte-locked by")
    print("    ref/scripts/regen_gate.sh:41 against a committed emitter hash,")
    print("    so it regenerates byte-identically from a clean checkout)")
    print("=" * 78)
    cnt, ln, vlen, alen = census(SCRIPT)
    tot = sum(cnt.values())
    print(f"    {tot:,} layer commands in the whole file "
          f"(the file is a MULTI-token script; per-token figures below)")
    print(f"    {'op':6s} {'count':>10s} {'sum of n':>14s}")
    for op in sorted(cnt):
        print(f"    {OPNAME.get(op, op):6s} {cnt[op]:10,} {ln[op]:14,}")
    print(f"\n    VN lengths seen: "
          f"{dict(sorted(vlen.items(), key=lambda kv: -kv[1])[:6])}")
    print(f"    ALU lengths seen: "
          f"{dict(sorted(alen.items(), key=lambda kv: -kv[1])[:6])}")

    # how many tokens does this script cover?  DNST count / (nDN * LNH)
    dnst_per_tok = 18 * 16
    ntok = cnt[8] / dnst_per_tok
    print(f"\n    DNST commands {cnt[8]:,} / (18 DN x 16 heads) = "
          f"{ntok:.4f} tokens' worth")

    print()
    print("=" * 78)
    print("B. the ANALYTIC model, checked against that census (per token)")
    print("=" * 78)
    a_c, a_L = analytic(*GEOM["0.8B"])
    print(f"    {'op':6s} {'analytic/tok':>13s} {'census/tok':>12s} {'ratio':>8s}")
    for op in sorted(set(a_c) | set(cnt)):
        cen = cnt[op] / ntok if ntok else 0
        r = (a_c[op] / cen) if cen else float("nan")
        print(f"    {OPNAME.get(op, op):6s} {a_c[op]:13,} {cen:12.1f} {r:8.3f}")
    print("\n    The DNST row is the one this study now depends on, and it is")
    print("    EXACT by construction: 288 per token = 18 DN layers x 16 heads.")

    print()
    print("=" * 78)
    print("C. PER-HEAD DeltaNet work — how it scales, per token")
    print("=" * 78)
    print(f"    {'model':6s} {'DN layers':>10s} {'heads':>7s} {'DNST cmds':>10s} "
          f"{'x0.8B':>7s} {'per-head VN/ALU cmds':>21s}")
    base = None
    for nm in ("0.8B", "2B", "4B", "9B"):
        H, FFN, nDN, nGQA, LNH, LDK, LDV, NQ, NKV, HD, CONV, V = GEOM[nm]
        d = nDN * LNH
        base = base or d
        print(f"    {nm:6s} {nDN:10d} {LNH:7d} {d:10,} {d/base:7.3f} "
              f"{nDN*LNH*5:21,}")
    print("\n    dn_step is ONE instance at ~1300 cycles/head (rtl/dn_step.sv:14),")
    print("    so this column is a SERIAL cost: 4B/9B pay 2.667x the 0.8B/2B")
    print("    DeltaNet recurrence, with no lane headroom to hide it.")
    print(f"    At 1300 cyc/head and 250 MHz that alone is "
          f"{18*16*1300/250e6*1e3:.3f} ms/token at 0.8B/2B and "
          f"{24*32*1300/250e6*1e3:.3f} ms/token at 4B/9B.")

    json.dump({"census_counts": {OPNAME.get(k, k): v for k, v in cnt.items()},
               "census_lensums": {OPNAME.get(k, k): v for k, v in ln.items()},
               "tokens_covered": ntok,
               "analytic_per_token": {OPNAME.get(k, k): v for k, v in a_c.items()}},
              open(sys.argv[1], "w") if len(sys.argv) > 1 else sys.stderr, indent=1)
