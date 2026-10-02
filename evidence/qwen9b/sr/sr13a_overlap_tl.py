#!/usr/bin/env python3
"""sr13a_overlap_tl.py — Task SR13a, coverage item (4): did the overlap
actually OVERLAP on the chip TB?

    sr13a_overlap_tl.py <timeline.csv> <sha256> <stem>.e4

The overlap stream (evidence/qwen9b/sr/sr13a_cov.py `overlap`) is legal by
the model's running ranges whatever the timing, so a PASS of its golden
alone does not show that a bank-1 MOVX really landed while the bank-0 stream
was running.  The chip TB's timeline instrument (tb/seq_timeline.svh, gated
by +timeline=) records, per record window, how many aclk cycles each
matvec channel's engine was busy (MVc_BSY) and the mover was busy (MOVER).

This walks the stream, marks every MOVX / MOVY issued on a channel whose
NO-WAIT MVGO is still pending (not yet drained by a FENCE whose mask covers
the channel), and prints, for each, the record's window and that channel's
engine-busy count inside it.  VERDICT: OVERLAPPED when every such record's
window has the channel's engine busy for EVERY cycle of it (MVc_BSY ==
ncyc), i.e. the MOVX/MOVY ran start to finish under the running stream.

Pure parsing and integer compares; run ON SNOKE through sr_run.sh.
"""
import hashlib
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "ref"))
sys.path.insert(0, os.path.join(ROOT, "sw"))
import seq_format as SF                                       # noqa: E402


def main():
    csv, want, sp = sys.argv[1:4]
    got = hashlib.sha256(open(csv, "rb").read()).hexdigest()
    print(f"  csv sha256 {got} ({'= the run log' if got == want else 'DIFFERS'})")
    if got != want:
        raise SystemExit("FAIL: the CSV is not the one the run logged")
    cols = None
    rows = {}
    for ln in open(csv):
        if ln.startswith("#COLS R,"):
            cols = ln[len("#COLS "):].strip().split(",")
        elif ln.startswith("R,"):
            v = ln.strip().split(",")
            d = dict(zip(cols, v))
            rows[int(d["pc"])] = {k: (int(x) if k != "R" else x)
                                  for k, x in d.items()}
    recs = SF.unpack_stream(open(sp + ".seq", "rb").read())
    print(f"  {len(rows)} timeline rows, {len(recs)} records")
    pend = set()
    marked, full = 0, 0
    print("   pc  op    ch  target   cyc0     ncyc  MOVER  MV0_BSY MV1_BSY "
          "MV2_BSY MV3_BSY  pending  (* = MOVX/MOVY under a running stream)")
    for pc, r in enumerate(recs):
        t = rows[pc]
        op = SF.OP_NAME.get(r.opcode, hex(r.opcode)).rstrip("*")
        ch = r.chan if r.opcode in (SF.OP_MOVX, SF.OP_MOVY,
                                    SF.OP_MVGO) else "-"
        star = ""
        if (r.opcode == SF.OP_MOVX and r.chan == SF.MOVX_BCAST) and pend:
            # R3-9a: a BROADCAST under running streams (B17.3; no pre-R3
            # stream holds one, so every earlier read is unchanged): every
            # pending channel's engine must be busy for its whole window
            marked += 1
            bsy = {c: t[f"MV{c}_BSY"] for c in sorted(pend)}
            star = "* BROADCAST"
            if all(v == t["ncyc"] for v in bsy.values()):
                full += 1
                star += f" engines {sorted(pend)} busy for the whole window"
            else:
                star += f" engines busy {bsy} of {t['ncyc']}"
        elif r.opcode in (SF.OP_MOVX, SF.OP_MOVY) and r.chan in pend:
            marked += 1
            bsy = t[f"MV{r.chan}_BSY"]
            star = "*"
            if bsy == t["ncyc"]:
                full += 1
                star += " engine busy for the whole window"
            else:
                star += f" engine busy {bsy} of {t['ncyc']}"
        print(f"  {pc:3d}  {op:5s} {ch!s:>2}  {r.target:#06x} {t['cyc0']:7d} "
              f"{t['ncyc']:8d} {t['MOVER']:6d} {t['MV0_BSY']:8d} "
              f"{t['MV1_BSY']:7d} {t['MV2_BSY']:7d} {t['MV3_BSY']:7d}  "
              f"{sorted(pend)!s:8s} {star}")
        if r.opcode == SF.OP_MVGO and (r.target & SF.MVGO_NOWAIT):
            pend.add(r.chan)
        elif r.opcode == SF.OP_FENCE:
            m = r.target & 0xF
            pend = set() if m == 0 else {c for c in pend if not (m >> c) & 1}
    print(f"  {marked} MOVX/MOVY records issued under a running stream; "
          f"{full} of them with the engine busy for every cycle of the window")
    ok = marked > 0 and full == marked
    print(f"SR13A_OVERLAP_TL: {'OVERLAPPED' if ok else 'NOT PROVEN'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
