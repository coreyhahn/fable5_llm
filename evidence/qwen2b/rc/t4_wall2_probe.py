#!/usr/bin/env python3
"""t4_wall2_probe.py — which SIDE is wrong at wall 2?  An implementation-
independent check that needs no RTL rebuild.

WALL 2 (RC_GATE 5b): the 2B chip replay reports its first scratch mismatch
at MEM[0x5c00].  `tb/tb_seq_chip.sv:995` reads the DUT scratch as

    u_layer.smem_a[exp_mem_a[i][13:0]]

— a FOURTEEN-bit index into a 32,768-word array (`layer_chan.sv`
`smem_a[32768]`).  R-b widened the scratchpad to 32K; these two index
expressions (lines 668 and 807) kept the 16K width.  Every 0.8B address is
below 16384 so the truncation is a no-op there; at 2B the map reaches
25,600 and address `a >= 16384` ALIASES to `a - 16384`.

    0x5c00 (ML_DDST, checked)  ->  0x1c00 (ML_GP, a y32 STAGING window)

Staging words are exactly the ones the `.seq` run is ALLOWED to leave
different from the `.txt` run, so the TB would be comparing a golden value
against a word that is licensed to differ.

FALSIFIABLE PREDICTION.  If the RTL is correct and only the TB's index is
wrong, then the values the TB PRINTED as "got" at 0x5c00+k are the true
contents of scratch word 0x1c00+k — which `ref/seq_model.py`'s executor
computes independently of the RTL.  So:

    got[k]  ==  seq_model_final_mem[0x1c00 + k]      for every k
    exp[k]  ==  seq_model_final_mem[0x5c00 + k]      (the golden, sanity)

If both hold, the RTL scratch is right, the TB read the wrong address, and
wall 2 is a TESTBENCH bug.  If got[k] does NOT match, the RTL really is
writing something wrong and the alias is a red herring.

    python3 evidence/qwen2b/rc/t4_wall2_probe.py [<seq-prefix> <base>]
"""
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (os.path.join(_ROOT, "ref"), os.path.join(_ROOT, "sw"),
           os.path.join(_ROOT, "tb", "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import seq_format as SF                                        # noqa: E402
import seq_model as SM                                         # noqa: E402

# the 21 words tb_seq_chip printed before it gave up, verbatim from
# evidence/qwen2b/rc/t4_24_smoke_chip_after_widen.log
TB_GOT = [0xffdf, 0xfed1, 0xffe5, 0x0032, 0xfffe, 0x009f, 0x0045, 0x00a5,
          0x000a, 0xfff3, 0x0201, 0xffc4, 0xfffd, 0x00f0, 0xfffb, 0x0000,
          0xffff, 0xfff7, 0xffb3, 0xfff1, 0x0016]
TB_EXP = [0xff93, 0x0139, 0x0050, 0x00e2, 0x0095, 0x0015, 0x014c, 0xfe88,
          0x00b1, 0x00a8, 0xff4c, 0xff3f, 0x01d2, 0xff3f, 0xfea2, 0xfea2,
          0xffc6, 0x000b, 0xff1a, 0x012b, 0x0078]
BAD = 0x5c00
ALIAS = BAD & 0x3FFF


def main():
    prefix = (sys.argv[1] if len(sys.argv) > 1
              else os.path.join(_ROOT, "tb/scripts/w5/lay2b_w8_s1.e"))
    base = (sys.argv[2] if len(sys.argv) > 2
            else os.path.join(_ROOT, "tb/scripts/w5/lay2b_w8_s1"))
    import json
    meta = json.load(open(prefix + ".seq.json"))
    recs = SF.unpack_stream(open(prefix + ".seq", "rb").read())
    blob = open(prefix + ".seqdata.bin", "rb").read()

    W = SM.DDRWeights.from_files(base, meta["weights"], meta)
    ex = SM.SeqExec(recs, blob, W).run(max_steps=50 * len(recs))
    mem = np.asarray(ex.M.mem)
    print(f"scratch depth {len(mem)} words")

    stage = np.zeros(len(mem), dtype=bool)
    for (lo, hi) in meta.get("staging_words", []):
        stage[lo:hi] = True
    print(f"staging windows: {meta.get('staging_words')}")
    print(f"  0x{BAD:04x} (ML_DDST, the reported address) staging? "
          f"{bool(stage[BAD])}   <- must be False (it IS checked)")
    print(f"  0x{ALIAS:04x} (= 0x{BAD:04x} & 0x3FFF, what a 14-bit index "
          f"reads) staging? {bool(stage[ALIAS])}   <- if True, the TB is "
          f"comparing against a word licensed to differ")
    print()

    def u16(v):
        return int(v) & 0xFFFF

    ok_alias = ok_gold = 0
    print(f"{'k':>3} {'TB got':>7} {'mem[0x1c00+k]':>14} {'':3} "
          f"{'TB exp':>7} {'mem[0x5c00+k]':>14}")
    for k in range(len(TB_GOT)):
        a = u16(mem[ALIAS + k])
        g = u16(mem[BAD + k])
        m1 = "==" if a == TB_GOT[k] else "!!"
        m2 = "==" if g == TB_EXP[k] else "!!"
        ok_alias += (a == TB_GOT[k])
        ok_gold += (g == TB_EXP[k])
        print(f"{k:>3}   {TB_GOT[k]:04x}           {a:04x} {m1}   "
              f"  {TB_EXP[k]:04x}           {g:04x} {m2}")
    print()
    print(f"TB 'got'      == seq_model mem[0x{ALIAS:04x}+k] : "
          f"{ok_alias}/{len(TB_GOT)}")
    print(f"TB 'expected' == seq_model mem[0x{BAD:04x}+k] : "
          f"{ok_gold}/{len(TB_EXP)}")
    print()
    if ok_alias == len(TB_GOT) and ok_gold == len(TB_EXP):
        print("VERDICT: the RTL scratch is CORRECT at the aliased address and")
        print("the golden is correct at the real one — tb_seq_chip.sv read the")
        print("WRONG WORD.  Wall 2 is a TESTBENCH indexing bug (14-bit index")
        print("into a 32K array), not an RTL or golden defect.")
        return 0
    if ok_gold == len(TB_EXP):
        print("VERDICT: the golden is confirmed, but the TB's 'got' values are")
        print("NOT the aliased word — the alias is a red herring and the RTL")
        print("really is writing something wrong.  Diagnose the mover path.")
        return 1
    print("VERDICT: neither side reproduces; re-check the probe's inputs.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
