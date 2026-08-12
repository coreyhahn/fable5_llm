#!/usr/bin/env python3
"""gen_seq_chip_vectors.py — golden state for tb/tb_seq_chip.sv.

    gen_seq_chip_vectors.py <seq-prefix> [--base <artifact-prefix>]

Replays <seq-prefix>.seq through ref/seq_model.py (the SAME executor the
wave-1B .txt-vs-.seq gate uses) against the REAL packed weight images, and
writes what a full-chip simulation must reproduce:

  <seq-prefix>.chip     NREC / PC / BASES / XRF / TOK / TCNT / EOUT / AMAX /
                        MEM keyword lines, terminated by END.  The MEM set is
                        the FINAL 16K scratchpad MINUS the y32 staging windows
                        the .seq stream legitimately leaves different from the
                        host-driven .txt run (they are declared in the
                        emitter's .seq.json), so every word the schedule is
                        supposed to determine is checked.
  <base>.wimg.bin       the weight REGION image: every packed <base>_w*.bin
                        laid down at the DDR offset the emitter's MVGO records
                        address (plan_weights_from_wids / sw/layer_test.py
                        plan_weights), so matvec_chan's own AXI4 master
                        fetches exactly the bytes the engine expects.

The .seq / .seqdata.bin / .emb.bin files are read by the simulation directly
(tb/seq_mem_file.sv $fseek/$fread's them beat by beat), so nothing else has to
be converted.
"""
import argparse
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_REF = os.path.normpath(os.path.join(_HERE, "..", "..", "ref"))
_SW = os.path.normpath(os.path.join(_HERE, "..", "..", "sw"))
for _p in (_REF, _SW):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import seq_format as SF                                       # noqa: E402
import seq_model as SM                                        # noqa: E402
import hwmap as HW                                            # noqa: E402


def build_wimg(base, plan, out):
    """The DDR weight region as one flat file starting at HW.W_BASE.

    plan[wid]["base"] is an ABSOLUTE DDR address; the file therefore holds
    (base - W_BASE) .. (base - W_BASE + size) for each image, with the
    WID_ALIGN padding between images left as zeros (never fetched: a MVGO's
    BEATS only ever covers real rows).
    """
    man = json.load(open(base + ".weights.json"))
    d = os.path.dirname(os.path.abspath(base)) or "."
    top = 0
    for wid, p in plan.items():
        top = max(top, p["base"] - HW.W_BASE + p["nrows"] * p["stride"])
    with open(out, "wb") as f:
        f.truncate(top)
        for wid, p in sorted(plan.items()):
            path = os.path.join(d, man[str(wid)]["file"])
            img = np.fromfile(path, dtype=np.uint8)
            sz = p["nrows"] * p["stride"]
            assert len(img) == sz, \
                f"wid {wid}: image {path} is {len(img)} B, plan says {sz}"
            f.seek(p["base"] - HW.W_BASE)
            f.write(img.tobytes())
    return top


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("prefix", help="the .seq / .seqdata.bin / .seq.json prefix")
    ap.add_argument("--base", default=None,
                    help="prefix of the generator artifacts (.weights.json, "
                         "_w*.bin, .emb.bin); defaults to PREFIX")
    ap.add_argument("--no-wimg", action="store_true",
                    help="skip rebuilding <base>.wimg.bin (it is large and "
                         "only depends on the weights, not on the stream)")
    a = ap.parse_args()
    base = a.base or a.prefix

    meta = json.load(open(a.prefix + ".seq.json"))
    stream = open(a.prefix + ".seq", "rb").read()
    blob = open(a.prefix + ".seqdata.bin", "rb").read()
    recs = SF.unpack_stream(stream)
    SF.validate_stream(recs)

    plan = {int(k): v for k, v in meta["weights"].items()}
    if plan and not a.no_wimg:
        n = build_wimg(base, plan, base + ".wimg.bin")
        print(f"  {base}.wimg.bin: {n} B ({len(plan)} images) @ "
              f"{HW.W_BASE:#x}")

    emb = None
    embf = base + ".emb.bin"
    if os.path.exists(embf):
        nrow = os.path.getsize(embf) // 2048
        emb = np.memmap(embf, dtype="<i2", mode="r").reshape(nrow, 1024)

    W = SM.DDRWeights.from_files(base, meta["weights"])
    ex = SM.SeqExec(recs, blob, W, emb=emb).run(max_steps=50 * len(recs))
    M = ex.M

    # the pc a halted seq_unit reports = the index of the HALT record
    halt_pc = None
    for i, r in enumerate(recs):
        if r.opcode == SF.OP_HALT:
            halt_pc = i
    assert halt_pc is not None, "stream has no HALT"

    stage = np.zeros(16384, dtype=bool)
    for (lo, hi) in meta.get("staging_words", []):
        stage[lo:hi] = True

    with open(a.prefix + ".chip", "w") as f:
        f.write(f"NREC {len(recs)}\n")
        f.write(f"PC {halt_pc}\n")
        f.write(f"BASES {SF.SEQ_STREAM_BASE:08x} {SF.SEQ_DATA_BASE:08x} "
                f"{HW.EMB_BASE:08x} {HW.W_BASE:08x}\n")
        for i in range(SF.XRF_N):
            f.write(f"XRF {i} {int(ex.xrf[i]) & 0x3FFFF:05x}\n")
        for t in ex.out_fifo:
            f.write(f"TOK {int(t):05x}\n")
        for s in range(len(M.T)):
            f.write(f"TCNT {s} {int(M.T[s][0])} {int(M.T[s][1])}\n")
        f.write(f"EOUT {int(M.eout) & 0xF:x}\n")
        f.write(f"AMAX {int(M.am_idx) & 0x3FFFF:05x} "
                f"{int(M.am_val) & 0xFFFFFFFF:08x}\n")
        nmem = 0
        for addr in range(16384):
            if stage[addr]:
                continue
            f.write(f"MEM {addr:04x} {int(M.mem[addr]) & 0xFFFF:04x}\n")
            nmem += 1
        f.write("END\n")

    print(f"  {a.prefix}.chip: {len(recs)} records, pc {halt_pc}, "
          f"{len(ex.out_fifo)} tokens, {nmem} scratch words checked "
          f"({int(stage.sum())} staging words excluded)")
    print(f"  seq_model stats: {ex.stats}")


if __name__ == "__main__":
    main()
