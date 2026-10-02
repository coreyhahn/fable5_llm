#!/usr/bin/env python3
"""t4_wall8_probe.py — is wall 8 the un-programmed EMB row stride?

WALL 8: the FULL 2B W8 chip replay fails with every generated token wrong
(`TOK[0] = 0x0d`, expected `0x117`) while `seq_model --gate` on the SAME
stream passes 1770/1770 and the 4-seed 1-layer smoke passes on the same TB.

CANDIDATE MECHANISM.  `rtl/seq_unit.sv` holds the EMB row stride in a CSR
(`0x60 EMBLOG2`) whose RESET value is 11, i.e. 2048-byte rows
(`EMBLOG2_RST = 5'd11`).  On silicon the host programs it before any EMB
record runs (`sw/seq_run.py:1762`).  `tb/tb_seq_chip.sv` — the TB's host
BFM — never writes it: the string EMBLOG2 does not appear in that file.

At 0.8B that is harmless, because the reset value is already correct
(`emb_row_bytes = 2048`).  This 2B artifact declares `emb_row_bytes = 4096`
(EMBLOG2 = 12), so the DUT would fetch every embedding from
`EMB_BASE + tok*2048` instead of `EMB_BASE + tok*4096` — the wrong row, and
the first token's embedding is wrong before any layer runs.

FALSIFIABLE PREDICTION.  If that is the mechanism, then feeding
`ref/seq_model.py` an embedding table read at the WRONG stride — row `tok`
taken as the 2048 int16 words starting at word `tok*1024` — must reproduce
the RTL's exact wrong token sequence, all six of them:

    TB TOK[0..5] = 0x0d, 0x0d, 0x2c, 0xdc, 0x8e, 0xdc

Matching all six by chance is not plausible, so a match proves the
mechanism and a mismatch refutes it.  Nothing is rebuilt and no RTL runs.

    python3 evidence/qwen2b/rc/t4_wall8_probe.py
"""
import json
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
import hwmap as HW                                             # noqa: E402

TB_TOK = [0x0d, 0x0d, 0x2c, 0xdc, 0x8e, 0xdc]     # what the RTL produced
GOLD_TOK = [0x117, 0x13a, 0x117, 0x171, 0x2de7, 0x0d]   # the .chip golden
BASE = os.path.join(_ROOT, "tb/scripts/w5/model_w8_2b_s1")
PREFIX = BASE + ".e"


def run(emb, tag):
    meta = json.load(open(PREFIX + ".seq.json"))
    recs = SF.unpack_stream(open(PREFIX + ".seq", "rb").read())
    blob = open(PREFIX + ".seqdata.bin", "rb").read()
    W = SM.DDRWeights.from_files(BASE, meta["weights"], meta)
    ex = SM.SeqExec(recs, blob, W, emb=emb).run(max_steps=50 * len(recs))
    toks = [int(t) for t in ex.out_fifo]
    print(f"  {tag:34s} -> {[hex(t) for t in toks]}")
    return toks


def main():
    rb = HW.load_weights_manifest(BASE)[1]["emb_row_bytes"]
    H = rb // 2
    flat = np.memmap(BASE + ".emb.bin", dtype="<i2", mode="r")
    nrow = flat.size // H
    print(f"emb.bin: {flat.size} int16 words, declared row = {rb} B = {H} "
          f"words, {nrow} rows")
    print(f"seq_unit EMBLOG2 reset = 11 -> {1 << 11} B rows; this artifact "
          f"needs {rb} B (EMBLOG2 {rb.bit_length() - 1})")
    print()

    right = flat.reshape(nrow, H)

    # the DUT's view with EMBLOG2 stuck at 11: row `tok` starts at byte
    # tok*2048, i.e. int16 word tok*1024, and is still H words long
    half = (1 << 11) // 2                       # 1024 int16 words per 2048 B
    nwrong = (flat.size - H) // half
    wrong = np.lib.stride_tricks.as_strided(
        np.asarray(right).reshape(-1), shape=(nwrong, H),
        strides=(half * 2, 2)).copy()
    print(f"wrong-stride view: {nwrong} rows of {H} words, stride {half} "
          f"words ({1 << 11} B)")
    print(f"  sanity: token 760 would read true row {760 * half // H} "
          f"instead of 760")
    print()

    print("replaying the FULL 2B stream through seq_model:")
    got_right = run(right, "correct stride (4096 B rows)")
    got_wrong = run(wrong, "EMBLOG2 stuck at 11 (2048 B)")
    print()
    print(f"  .chip golden tokens : {[hex(t) for t in GOLD_TOK]}")
    print(f"  RTL produced        : {[hex(t) for t in TB_TOK]}")
    print()
    ok_r = got_right == GOLD_TOK
    ok_w = got_wrong == TB_TOK
    print(f"correct-stride replay == the golden      : {ok_r}")
    print(f"wrong-stride  replay == what the RTL did : {ok_w}")
    print()
    if ok_r and ok_w:
        print("VERDICT: PROVEN.  Feeding the golden executor an embedding table")
        print("read at 2048 B rows reproduces the RTL's six wrong tokens")
        print("EXACTLY.  Wall 8 is tb_seq_chip.sv never programming EMBLOG2 —")
        print("a TESTBENCH host-BFM gap.  sw/seq_run.py does program it, so")
        print("silicon/R-d is NOT exposed; ref/seq_model.py reads the stride")
        print("from the artifact, which is why the golden was green.")
        return 0
    if ok_r:
        print("VERDICT: the stride hypothesis does NOT reproduce the RTL's")
        print("tokens.  Something else is wrong; keep the artifacts.")
        return 1
    print("VERDICT: the correct-stride replay does not even match the golden;")
    print("re-check the probe's inputs before drawing any conclusion.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
