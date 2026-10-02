#!/usr/bin/env python3
"""g6_emblog2.py — Task 15 fix round 1, I-2: prove the EMBLOG2 WRITE takes,
by writing a value that is NOT the reset value and reading it back.

    /home/cah/.venv/bin/python evidence/qwen9b/g6/g6_emblog2.py \
        --prefix tb/scripts/w9/model_9b_s1.e4

WHY THIS FILE EXISTS.  `evidence/qwen9b/g6/RD9_GATE.md` §9 said of the 9B
run's `EMBLOG2 13` readback: "The reset value is `1 << SEQ_EMBLOG2_RST`, so
this is a real write, not the default surviving."  Review round 1 (I-2)
refuted it from the RTL: `sw/hwmap.py:342` reads `SEQ_EMBLOG2_RST = 13` and
`rtl/seq_unit.sv:346` reads `localparam logic [4:0] EMBLOG2_RST = 5'd13;`,
assigned at `rtl/seq_unit.sv:951`.  At 9B the CSR's reset value in LOG2 units
IS 13 — the same number the manifest asks for — so a readback of 13 cannot
distinguish a write that took from a reset default that survived.

This rung makes the distinction, on the resident silicon, with ONE CSR:

  [A] write 12 (4,096 B rows) and read it back.  12 != EMBLOG2_RST, so a
      readback of 12 is only possible if the WRITE LANDED.  If the field
      were read-only-at-reset the readback would answer 13 and
      `sw/seq_run.seq_set_emb_row_bytes` would raise — which is the same
      refusal the rung claims, exercised for real.
  [B] write the manifest's value back (8,192 B = 2*H at H=4096 -> 13) and
      read it back, leaving the CSR exactly as `028` left it.

Both steps go through `sw/seq_run.seq_set_emb_row_bytes` — the function the
rung actually rests on — not through a hand-rolled poke.

BOARD SAFETY.  Takes the shared lock.  `sw/seq_run.Dev`'s identity gate runs
first and REFUSES unless MAGIC / VERSION / CALIB 0xF / the five IDENTs are
right.  ZERO DMA: nothing is written to DDR, so the resident 9B weight pack
and its state region are untouched.  The only device write is the 32-bit
SEQ EMBLOG2 CSR, and it is restored to the manifest's value before exit
(including on the error path).  Refuses to run while the sequencer is busy.
No reprogram, no sudo, no flash.
"""
import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOP = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in ("sw", "ref"):
    _q = os.path.join(_TOP, _p)
    if _q not in sys.path:
        sys.path.insert(0, _q)

import board_lock as BL                                        # noqa: E402
import hwmap as HW                                             # noqa: E402
import seq_run as SR                                           # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prefix", default="tb/scripts/w9/model_9b_s1.e4",
                    help="the RESIDENT artifact; its manifest's "
                         "emb_row_bytes is the value restored at the end")
    ap.add_argument("--dev", default="/dev/xdma0")
    ap.add_argument("--probe-bytes", type=int, default=4096,
                    help="the NON-reset row size written in step [A]")
    BL.add_lock_args(ap)
    a = ap.parse_args(argv)
    os.chdir(_TOP)

    try:
        lk = BL.from_args(a, tool="g6_emblog2.py").acquire()
    except BL.BoardLockError as e:
        print("*** %s" % e)
        return 4

    bad = []
    base = SR.derive_base(a.prefix)
    _man, mmeta = HW.load_weights_manifest(base)
    want_bytes = int(mmeta["emb_row_bytes"])
    want_log2 = HW.seq_emb_log2(want_bytes)
    probe_log2 = HW.seq_emb_log2(a.probe_bytes)

    print("--- what the RTL and the manifest say, before the board is asked")
    print(f"  SEQ_EMBLOG2_RST            {HW.SEQ_EMBLOG2_RST}   "
          f"(sw/hwmap.py:342, mirroring rtl/seq_unit.sv:346)")
    print(f"  SEQ_EMBLOG2_MIN..MAX       {HW.SEQ_EMBLOG2_MIN}"
          f"..{HW.SEQ_EMBLOG2_MAX}")
    print(f"  manifest emb_row_bytes     {want_bytes} B -> EMBLOG2 "
          f"{want_log2}   ({base}.weights.json)")
    print(f"  the probe value            {a.probe_bytes} B -> EMBLOG2 "
          f"{probe_log2}")
    print(f"  the discrimination         EMBLOG2 {want_log2} == "
          f"SEQ_EMBLOG2_RST {HW.SEQ_EMBLOG2_RST}, so a readback of "
          f"{want_log2} ALONE proves nothing; a readback of {probe_log2} "
          f"can only come from a write")
    if probe_log2 == HW.SEQ_EMBLOG2_RST:
        print("  ! the probe equals the reset value — this rung would prove "
              "nothing")
        return 2
    if want_log2 != HW.SEQ_EMBLOG2_RST:
        print(f"  NOTE the manifest's {want_log2} differs from the reset "
              f"{HW.SEQ_EMBLOG2_RST} on this artifact, so the ordinary "
              f"readback WAS already discriminating")

    dev = SR.Dev(a.dev, expect_version=SR.EXPECTED_SEQ_VERSION)
    try:
        print("\n--- identity, through sw/seq_run.Dev's own gate")
        print(f"  MAGIC {dev.ident['magic']:#010x}  VERSION "
              f"{dev.ident['version']:#010x}  CALIB "
              f"{dev.ident['calib']:#x}  SEQ IDENT "
              f"{dev.ident.get('seq_ident', 0):#010x}  seq_ok={dev.seq_ok}")
        dev.require_seq("an EMBLOG2 write")
        st = dev.seq_status()
        print(f"  SEQ STATUS {st['raw']:#010x}  busy={st['busy']} "
              f"halted={st['halted']} err={st['err']} "
              f"err_code={st['err_code']:#04x}")
        if st["busy"]:
            print("  ! the sequencer is BUSY — another host has it; "
                  "REFUSING")
            return 3

        found = dev.seq_rd(HW.S_EMBLOG2) & 0x1F
        print(f"\n[0] as found, before this rung writes anything: EMBLOG2 "
              f"{found}  ({1 << found} B rows)")
        if found != want_log2:
            bad.append(f"as found EMBLOG2 {found} != the manifest's "
                       f"{want_log2} — the board was not as `028` left it")

        print(f"\n[A] write {a.probe_bytes} B rows (EMBLOG2 {probe_log2}) "
              f"through sw/seq_run.seq_set_emb_row_bytes, then read back")
        got_a = SR.seq_set_emb_row_bytes(dev, a.probe_bytes)
        raw_a = dev.seq_rd(HW.S_EMBLOG2) & 0x1F
        print(f"  independent re-read: EMBLOG2 {raw_a}")
        if raw_a != probe_log2:
            bad.append(f"[A] re-read {raw_a}, wrote {probe_log2}")
        elif raw_a == HW.SEQ_EMBLOG2_RST:
            bad.append("[A] the probe landed on the reset value after all")
        else:
            print(f"  ==> THE WRITE TOOK.  {raw_a} is not the reset value "
                  f"{HW.SEQ_EMBLOG2_RST}, so this readback cannot be the "
                  f"default surviving.")

        print(f"\n[B] write the manifest's {want_bytes} B rows (EMBLOG2 "
              f"{want_log2}) back, then read back")
        got_b = SR.seq_set_emb_row_bytes(dev, want_bytes)
        raw_b = dev.seq_rd(HW.S_EMBLOG2) & 0x1F
        print(f"  independent re-read: EMBLOG2 {raw_b}")
        if raw_b != want_log2:
            bad.append(f"[B] re-read {raw_b}, wrote {want_log2}")
        print(f"  the CSR now holds {raw_b} = {1 << raw_b} B rows, which is "
              f"the manifest's value and what `028` left")
        if got_a is None or got_b is None:
            bad.append("seq_set_emb_row_bytes returned None — this "
                       "bitstream has no EMBLOG2 CSR")
    finally:
        # Restore on EVERY path: a run that dies between [A] and [B] must
        # not leave the next session's embedding fetch on a 4 KiB stride.
        try:
            cur = dev.seq_rd(HW.S_EMBLOG2) & 0x1F
            if cur != want_log2:
                dev.seq_wr(HW.S_EMBLOG2, want_log2)
                cur = dev.seq_rd(HW.S_EMBLOG2) & 0x1F
                print(f"  [restore] EMBLOG2 forced back to {cur}")
                if cur != want_log2:
                    bad.append(f"RESTORE FAILED: EMBLOG2 reads {cur}")
        except Exception as e:                                 # noqa: BLE001
            bad.append(f"restore path raised {type(e).__name__}: {e}")

    print()
    print("G6_EMBLOG2: %s (%d problem(s))" % ("PASS" if not bad else "FAIL",
                                              len(bad)))
    for b in bad:
        print("  ! " + b)
    if not bad:
        print(f"G6_EMBLOG2: the CSR is WRITABLE and READS BACK WHAT WAS "
              f"WRITTEN — {probe_log2} then {want_log2}; the resident value "
              f"is {want_log2} and no DDR byte was touched")
    del lk
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
