#!/usr/bin/env python3
"""r3_9a_windows.py — Task R3-9a: the MOVX windows of a chip-TB timeline.

    r3_9a_windows.py <stem>.e4 <timeline.csv> <sha256> [--vs <csv2> <sha2>]

New file (plan I-5: new content, no round tool reads MOVX windows).  The
chip TB's timeline instrument (tb/seq_timeline.svh, +timeline=) writes one
row per record: its window (the issue FSM latched it .. the cycle before the
next record is latched; a MOVX record's issue waits in I_MOVER for the mover
to finish, so its window is the whole mover job) and per-window busy counts
(MOVER, MVc_BSY).  This prints, for every MOVX record of the stream:
broadcast (flags[7:4] = 0xF) or unicast, channel, start word, length in
elements, x words, window cycles and MOVER cycles; then, for every length
that has both, the ONE-WINDOW comparison — mean broadcast window minus mean
unicast window, and their ratio (R3-7's measure: 1.00 plus the fixed extra,
three more closing STATUS reads).  Every FENCE row is printed with its
per-channel engine-busy counts (the late reader's wait).  With --vs, a
second CSV of the SAME stream (e.g. the +xp_hold run) is read too and the
per-record window differences are printed (the back-pressure stall).

Pure parsing and integer arithmetic; run ON SNOKE through sr_run.sh.
"""
import hashlib
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "ref"))
sys.path.insert(0, os.path.join(ROOT, "sw"))
import seq_format as SF                                       # noqa: E402


def load(csv, want):
    got = hashlib.sha256(open(csv, "rb").read()).hexdigest()
    print(f"  csv {os.path.relpath(csv, ROOT)} sha256 {got} "
          f"({'= the run log' if got == want else 'DIFFERS'})")
    if got != want:
        raise SystemExit("FAIL: the CSV is not the one the run logged")
    cols, rows = None, {}
    for ln in open(csv):
        if ln.startswith("#COLS R,"):
            cols = ln[len("#COLS "):].strip().split(",")
        elif ln.startswith("R,"):
            d = dict(zip(cols, ln.strip().split(",")))
            rows[int(d["pc"])] = {k: (int(x) if k != "R" else x)
                                  for k, x in d.items()}
    return rows


def main():
    a = sys.argv[1:]
    sp, csv, want = a[0], a[1], a[2]
    vs = None
    if len(a) > 3:
        assert a[3] == "--vs" and len(a) == 6, "usage: ... [--vs <csv2> <sha2>]"
        vs = (a[4], a[5])
    recs = SF.unpack_stream(open(sp + ".seq", "rb").read())
    rows = load(csv, want)
    rows2 = load(*vs) if vs else None
    print(f"  {len(rows)} timeline rows, {len(recs)} records")
    assert len(rows) == len(recs), "one row per record expected"
    print("   pc  kind     ch  word  len    words    ncyc   MOVER"
          + ("   ncyc(vs)   delta" if vs else ""))
    by_len = {}
    for pc, r in enumerate(recs):
        if r.opcode != SF.OP_MOVX:
            continue
        t = rows[pc]
        bc = r.chan == SF.MOVX_BCAST
        n = r.len_or_addr_hi & 0xFFFFFF
        w = r.target & SF.MOVX_WORD_MASK
        kind = "BCAST" if bc else "UNICAST"
        extra = ""
        if vs:
            t2 = rows2[pc]
            extra = f"  {t2['ncyc']:9d} {t2['ncyc'] - t['ncyc']:+7d}"
        print(f"  {pc:3d}  {kind:7s}  {'ALL' if bc else r.chan:>3}  {w:4d} "
              f"{n:5d}  {SF.movx_words(n):5d} {t['ncyc']:8d} {t['MOVER']:7d}"
              + extra)
        by_len.setdefault(n, {"b": [], "u": []})["b" if bc else "u"].append(
            t["ncyc"])
    print("  ONE-WINDOW (per length with both a broadcast and a unicast):")
    for n in sorted(by_len):
        b, u = by_len[n]["b"], by_len[n]["u"]
        if not b or not u:
            continue
        mb, mu = sum(b) / len(b), sum(u) / len(u)
        print(f"    len {n:5d} ({SF.movx_words(n)} words): broadcast "
              f"{b} mean {mb:.2f}, unicast {u} mean {mu:.2f}; "
              f"broadcast - unicast = {mb - mu:+.2f} cyc, ratio {mb / mu:.5f}")
    print("  FENCE windows (per-channel engine busy inside):")
    for pc, r in enumerate(recs):
        if r.opcode != SF.OP_FENCE:
            continue
        t = rows[pc]
        print(f"    pc {pc:3d} mask {r.target & 0xF:#06b}: ncyc {t['ncyc']:7d}, "
              f"MV0..3_BSY {t['MV0_BSY']} {t['MV1_BSY']} {t['MV2_BSY']} "
              f"{t['MV3_BSY']}")
    if vs:
        tot1 = sum(t["ncyc"] for t in rows.values())
        tot2 = sum(t["ncyc"] for t in rows2.values())
        print(f"  whole stream: {tot1} vs {tot2} cyc, delta {tot2 - tot1:+d}")
    print("R3_9A_WINDOWS: DONE")


if __name__ == "__main__":
    main()
