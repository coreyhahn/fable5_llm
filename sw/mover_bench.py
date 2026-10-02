#!/usr/bin/env python3
"""mover_bench.py — per-record-class cycle costs on silicon (rung-3 census).

Method: build micro-streams by REPLICATING real records sliced from the
gated model_v2 stream (so no hand-packed field encodings), run each with
the sequencer, and read S_PERF_CYC/AXW/AXR.  cost/record =
(cyc - N_halt_overhead) / N.  Streams live at the chat stream window
(0x0900_0000 chan-local) — this clobbers the resident chat images, which
the next chat session simply re-uploads (2 MiB).

Classes measured:
  int_csrwr   CSRWR to SEQ-internal XRF (issue+decode floor, no AXI)
  ext_csrwr   CSRWR to a layer CSR (adds one AXIL write)
  movx        a real MOVX record x N   (DDR -> engine XWIN via AXIL writes)
  movy        a real MOVY record x N   (engine Y -> scratch, AXIL rd+wr)
  mvgo_ffn    a real mid-size MVGO x N (engine run incl per-row bubble)
  mvgo_head   the first LM-head MVGO x N
  ldc         a real LDC x N           (DDR -> scratch via AXI4 + AXIL)

Usage (snoke): .venv/bin/python mover_bench.py --out ../evidence/rung3/mover_bench.json
"""
import argparse, json, struct, time

import numpy as np
import board_lock as BL
import seq_run as SR
import hwmap as HW
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "ref"))
import seq_format as SF

PREFIX = "/home/cah/r2d2/code/fpga/fable5_llm/tb/scripts/w4/model_v2_s1.e"
STREAM_BASE = 0x0900_0000          # chan-0 local, the chat stream window
BODY = (1526, 16266)               # T_BODY_FULL record span
ACLK = HW.ACLK_HZ


def rec_bytes(buf, i):
    return buf[16 * i:16 * (i + 1)]


def find(recs, lo, hi, op, k=0):
    hits = [i for i in range(lo, hi) if recs[i].opcode == op]
    return hits[k] if hits else None


def run_stream(dev, blob, nrec, timeout=60.0):
    dev.dma_write(STREAM_BASE, blob)
    for i in range(8):                       # XRF known state
        dev.seq_wr(HW.s_xrf(i), 0)
    dev.seq_wr(HW.S_TCNT_SEQ, 1)
    dev.seq_wr(HW.S_BASE_LO, STREAM_BASE)
    dev.seq_wr(HW.S_BASE_HI, 0)
    dev.seq_wr(HW.S_LEN, nrec)
    dev.seq_wr(HW.S_ENTRY, 0)
    while True:                              # drain OUT FIFO (halted)
        v = dev.seq_rd(HW.S_OUT_FIFO)
        if not (v >> 31):
            break
    dev.seq_wr(HW.S_CTRL, 1)                 # START
    t0 = time.monotonic()
    while True:
        st = dev.seq_rd(HW.S_STATUS)
        if st & (HW.SEQ_ST_HALTED | HW.SEQ_ST_ERR):
            break
        if time.monotonic() - t0 > timeout:
            dev.seq_wr(HW.S_CTRL, 2)         # ABORT
            raise RuntimeError("bench stream timeout")
    err = (st >> 24) & 0xFF
    return {"cyc": dev.seq_rd(HW.S_PERF_CYC),
            "rec": dev.seq_rd(HW.S_PERF_REC),
            "axw": dev.seq_rd(HW.S_PERF_AXW),
            "axr": dev.seq_rd(HW.S_PERF_AXR),
            "err": HW.seq_err_name(err) if err else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("-n", type=int, default=20000, help="reps for cheap recs")
    ap.add_argument("--nmv", type=int, default=64, help="reps for MVGO/mover")
    # O3: the device was hard-coded here too (see cycle_census.py).
    ap.add_argument("--dev", default="/dev/xdma0")
    ap.add_argument("--chan", type=int, default=0)
    BL.add_lock_args(ap)                        # O3: --lock / --no-lock
    args = ap.parse_args()

    # O3: this tool CLOBBERS the chat-resident stream images at
    # 0x0900_0000 and, until now, took no lock at all — the sharpest
    # single case in docs/USAGE.md §5's old "does NOT take the lock"
    # column.  It takes it first, before the donor stream is even read.
    try:
        _lock = BL.from_args(args, tool="mover_bench.py").acquire()
    except BL.BoardLockError as e:
        print("*** %s" % e)
        raise SystemExit(4)

    buf = open(PREFIX + ".seq", "rb").read()
    recs = SF.unpack_stream(buf)
    lo, hi = BODY

    # donor records (byte-verbatim from the gated stream)
    i_movx = find(recs, lo, hi, SF.OP_MOVX)
    i_mvgo = find(recs, lo, hi, 0x05)              # first MVGO (q-proj ish)
    i_movy = find(recs, i_mvgo, hi, SF.OP_MOVY)
    i_head = lo + 14007                            # first LM-head MVGO
    i_hmvy = find(recs, i_head, hi, SF.OP_MOVY)
    i_ldc  = find(recs, lo, hi, 0x0B)
    halt = SF.pack(SF.OP_HALT)
    int_csr = rec_bytes(buf, 1524)                 # CSRWR XRF[3] (write-through x2 AXIL)
    tcnt_csr = rec_bytes(buf, 45751)               # CSRWR TCNT_SEQ (truly internal)
    # ext CSRWR donor: any real layer-CSR write from the body (the emitter
    # only produces legal targets — steal one instead of guessing)
    i_ext = next(i for i in range(lo, hi)
                 if recs[i].opcode == SF.OP_CSRWR
                 and (recs[i].target & 0xF000) not in (0x2000,))
    ext_csr = rec_bytes(buf, i_ext)

    def stream(rec16, n):
        return rec16 * n + halt, n + 1

    dev = SR.Dev(args.dev, chan=args.chan, allow_seq=True)
    if not dev.seq_ok:
        raise SystemExit("SEQ refused: " + dev.seq_why)
    print(f"  board VERSION={dev.ident['version']:#010x}")

    n, nmv = args.n, args.nmv
    plan = [
        ("halt_only",  b"", 0, 1),
        ("int_csrwr",  int_csr, n, 1),
        ("tcnt_csrwr", tcnt_csr, n, 1),
        ("ext_csrwr",  ext_csr, n, 1),
        ("movx",       rec_bytes(buf, i_movx), nmv, 1),
        ("movy",       rec_bytes(buf, i_movy), nmv, 1),
        ("mvgo_ffn",   rec_bytes(buf, i_mvgo), nmv, 1),
        ("mvgo_head",  rec_bytes(buf, i_head), nmv, 1),
        ("movy_head",  rec_bytes(buf, i_hmvy), nmv, 1),
        ("ldc",        rec_bytes(buf, i_ldc), n // 10, 1),
    ]
    res = {}
    base_cyc = None
    for name, rb, reps, _ in plan:
        blob, nrec = (halt, 1) if not rb else stream(rb, reps)
        p = run_stream(dev, blob, nrec)
        per = (p["cyc"] - (base_cyc or 0)) / max(reps, 1)
        if name == "halt_only":
            base_cyc = p["cyc"]
        res[name] = dict(reps=reps, **p, cyc_per_rec=round(per, 2),
                         axw_per=round(p["axw"] / max(reps, 1), 2),
                         axr_per=round(p["axr"] / max(reps, 1), 2))
        print(f"  {name:10s} reps={reps:6d}  cyc={p['cyc']:>11,}  "
              f"cyc/rec={per:10.2f}  axw/rec={res[name]['axw_per']:8.2f}  "
              f"axr/rec={res[name]['axr_per']:8.2f}"
              + (f"  ERR={p['err']}" if p.get("err") else ""))

    # donor record shapes for the report
    def shape_of(i):
        r = recs[i]
        return dict(idx=i, opcode=r.opcode, flags=r.flags, target=r.target,
                    imm32=r.imm32, addr_lo=getattr(r, "addr_lo", None))
    res["_donors"] = {k: shape_of(v) for k, v in
                      dict(movx=i_movx, movy=i_movy, mvgo_ffn=i_mvgo,
                           mvgo_head=i_head, movy_head=i_hmvy, ldc=i_ldc).items()}
    if args.out:
        json.dump(res, open(args.out, "w"), indent=1)
        print(f"  -> {args.out}")


if __name__ == "__main__":
    main()
