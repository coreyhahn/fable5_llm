#!/usr/bin/env python3
"""g6_nch.py — Task 15 fix round 1, I-5: the plan's `then nch=1, then nch=4`
rung, discharged on evidence instead of on one artifact's `meta` field.

    /home/cah/.venv/bin/python evidence/qwen9b/g6/g6_nch.py \
        --prefix tb/scripts/w9/model_9b_s1.e4

WHY THIS FILE EXISTS.  `evidence/qwen9b/g6/RD9_GATE.md` §4.2 retired the
plan's nch=1 rung with the sentence "Every 9B stream this campaign emitted
reports `meta nch = 4`", and the only line on the record was `006`:19's
`[auto-detected from meta nch]` for ONE artifact.  Review round 1 (I-5)
called that retiring a required rung on a sentence.  This script replaces the
sentence with three measurements:

  [1] THE CONTRACT.  `sw/seq_run.py` has NO `--nch` option: the mode is read
      out of the stream's own `meta["nch"]` (`sw/seq_run.py:374`,
      `sw/seq_run.py:3052`) and `--four-chan` only ASSERTS it
      (`sw/seq_run.py:2942`).  So "run it at nch=1" is a request for an
      nch=1 ARTIFACT, not for a flag.

  [2] THE ENUMERATION.  Every committed 9B artifact's `meta["nch"]`, all of
      them, not one -- and, as the control that keeps [2] from being
      vacuous, the 0.8B/2B artifacts in `tb/scripts/w4/`, where an nch=1
      stream DOES exist and the same reader reports 1 for it.

  [3] THE REFUSAL.  The RESIDENT artifact's own manifest offered to
      `sw/hwmap.plan_weights` at nch=1 -- the nch-INDEPENDENT pack every
      pre-R-c artifact encodes -- which refuses, because the 9B pack is
      3,902 MiB against the 1,280 MiB `W_BASE .. EMB_BASE` window.  That is
      `evidence/qwen9b/g4/G4A_REPLAY.md` §3.1's measurement
      (`evidence/qwen9b/g4/013_inventory_9b.log`), re-made here on the
      artifact the board is actually holding.

So the rung is not skipped and not asserted: an nch=1 9B model stream is
REFUSED BY THE ADDRESS MAP before any board tool could be pointed at one.

BOARD SAFETY.  Takes the shared lock (another host must not be mid-run while
this reads the identity CSRs).  Opens ONLY `/dev/xdma0_user`, and only to
read MAGIC/VERSION/CALIB/UPTIME before and after, so the log carries proof
that this rung left the resident 9B pack and its state region untouched.
ZERO DMA, no SEQ CSR write, no reprogram, no sudo, no flash.
"""
import argparse
import glob
import json
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

sys.path.insert(0, _HERE)
import g6_ident as ID                                          # noqa: E402

MiB = 1024.0 * 1024.0

# The 9B artifact set, and the 0.8B/2B set that is the enumeration's control.
NINE = ("tb/scripts/w9/*.seq.json", "tb/scripts/w9/emit2/*/*.seq.json")
CTRL = ("tb/scripts/w4/model_v2_s1.e.seq.json",
        "tb/scripts/w4/model_v2_s1.e4.seq.json")


def meta_nch(path):
    """(nch, nrec, key_present) the way `sw/seq_run.py:374` reads it:
    `int(meta.get("nch", 1))` — an ABSENT key means the single-channel
    stream, which is how the pre-R-c 1-chan artifacts encode it."""
    with open(path) as f:
        d = json.load(f)
    m = d.get("meta") or d
    return (int(m.get("nch", 1)), int(m.get("nrec", 0) or 0),
            "nch" in m)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prefix", default="tb/scripts/w9/model_9b_s1.e4",
                    help="the RESIDENT artifact, whose manifest [3] offers "
                         "to plan_weights at nch=1")
    ap.add_argument("--dev", default="/dev/xdma0")
    ap.add_argument("--expect-version", default="0xc973c18a")
    BL.add_lock_args(ap)
    a = ap.parse_args(argv)
    os.chdir(_TOP)

    try:
        lk = BL.from_args(a, tool="g6_nch.py").acquire()
    except BL.BoardLockError as e:
        print("*** %s" % e)
        return 4

    bad = []

    print("=== [0] the board BEFORE this rung (AXI-Lite reads only, no DMA)")
    pre = ID.read_ident(a.dev)
    ID.report(pre)
    want = int(a.expect_version, 0)
    if pre["version"] != want:
        bad.append(f"VERSION {pre['version']:#010x} != {want:#010x}")

    print("\n=== [1] THE CONTRACT — is nch a flag, or a property of the "
          "artifact?")
    src = open(os.path.join(_TOP, "sw", "seq_run.py")).read()
    has_flag = ('"--nch"' in src) or ("'--nch'" in src)
    print(f"  sw/seq_run.py declares a --nch option:      "
          f"{'YES' if has_flag else 'NO'}")
    print(f"  sw/seq_run.py declares --four-chan:         "
          f"{'YES' if '--four-chan' in src else 'NO'}")
    print("  --four-chan's own help says:                "
          "\"The mode is otherwise auto-detected from meta['nch']; this "
          "flag just asserts it.\"")
    print("  => nch is a property of the ARTIFACT.  An nch=1 rung needs an "
          "nch=1 STREAM.")
    if has_flag:
        bad.append("sw/seq_run.py has a --nch option after all — this "
                   "script's premise is wrong, re-read it")

    print("\n=== [2] THE ENUMERATION — meta['nch'] for EVERY committed 9B "
          "artifact")
    nine = []
    for pat in NINE:
        nine.extend(sorted(glob.glob(os.path.join(_TOP, pat))))
    if not nine:
        bad.append("no 9B .seq.json found under tb/scripts/w9/")
    n1 = 0
    for p in nine:
        nch, nrec, present = meta_nch(p)
        rel = os.path.relpath(p, _TOP)
        print(f"  nch={nch}{'' if present else ' (key absent -> 1)'}  "
              f"nrec={nrec:>7}  {rel}")
        if nch == 1:
            n1 += 1
    print(f"  --- {len(nine)} 9B artifact(s); at nch=1: {n1}")
    if n1:
        bad.append(f"{n1} 9B artifact(s) report nch=1 — the rung CAN be run, "
                   f"run it")

    print("\n  the CONTROL — the same reader on the 0.8B/2B set, where an "
          "nch=1 stream exists")
    ctrl_seen = []
    for pat in CTRL:
        p = os.path.join(_TOP, pat)
        if not os.path.exists(p):
            print(f"  (absent) {pat}")
            continue
        nch, nrec, present = meta_nch(p)
        ctrl_seen.append(nch)
        print(f"  nch={nch}{'' if present else ' (key absent -> 1)'}  "
              f"nrec={nrec:>7}  {pat}")
    if 1 not in ctrl_seen:
        bad.append("the control did not find a single nch=1 stream anywhere "
                   "— the enumeration above is then vacuous")

    print("\n=== [3] THE REFUSAL — the RESIDENT artifact's manifest, offered "
          "to plan_weights at nch=1")
    import seq_run as SR                                       # noqa: E402
    base = SR.derive_base(a.prefix)
    man, mmeta = HW.load_weights_manifest(base)
    tot = sum(int(v["nrows"]) * int(v["stride"]) for v in man.values())
    print(f"  base            {base}")
    print(f"  images          {len(man)}  packed {tot} B = {tot / MiB:,.1f} "
          f"MiB")
    print(f"  window          W_BASE {HW.W_BASE:#x} .. EMB_BASE "
          f"{HW.EMB_BASE:#x} = "
          f"{(HW.EMB_BASE - HW.W_BASE) / MiB:,.0f} MiB per channel")
    refused = None
    try:
        _, top1 = HW.plan_weights(man, nch=1)
    except Exception as e:                                     # noqa: BLE001
        refused = f"{type(e).__name__}: {str(e).splitlines()[0]}"
        print(f"  nch=1           REFUSED: {refused}")
    else:
        print(f"  nch=1           ACCEPTED at {top1:#x} = "
              f"{(top1 - HW.W_BASE) / MiB:,.1f} MiB")
        bad.append(f"the nch-independent pack was ACCEPTED at {top1:#x} — an "
                   f"nch=1 9B stream is emittable and the rung must be run")
    # the nch=4 arm, for contrast: the pack that DOES fit, on the same
    # manifest, with the stream's own per-wid layout.
    import seq_format as SF                                     # noqa: E402
    _sj = json.load(open(a.prefix + ".seq.json"))
    wl = dict((_sj.get("meta") or _sj).get("weight_layout") or {})
    if wl:
        depth = int(wl["chunk_rows"])
        nch4 = int(wl["nch"])

        def rows_of(wid, nrows):
            return SF.chan_rows(int(nrows), nch4,
                                wl["by_wid"].get(str(wid), wl["default"]),
                                depth)

        _, tops = HW.plan_weights(man, wdir=os.path.dirname(base),
                                  nch=nch4, rows_of=rows_of)
        print(f"  nch={nch4}           ACCEPTED — busiest channel "
              f"{(max(tops) - HW.W_BASE) / MiB:,.1f} MiB = "
              f"{100.0 * (max(tops) - HW.W_BASE) / (HW.EMB_BASE - HW.W_BASE):.1f} "
              f"% of the window")

    print("\n=== [4] the board AFTER this rung — nothing moved")
    post = ID.read_ident(a.dev)
    ID.report(post)
    for k in ("magic", "version", "calib"):
        if pre[k] != post[k]:
            bad.append(f"{k} changed across this rung: {pre[k]:#x} -> "
                       f"{post[k]:#x}")
    if post["uptime_cyc"] < pre["uptime_cyc"]:
        bad.append("UPTIME went BACKWARDS — the device was reset")
    print(f"  UPTIME advanced {(post['uptime_s'] - pre['uptime_s']):.3f} s "
          f"across the rung (the device was never reset)")

    print()
    if refused is not None and not bad:
        print("G6_NCH: nch=1 REFUSED BY THE ADDRESS MAP, nch=4 is the only "
              "pack that fits")
    print("G6_NCH: %s (%d problem(s))" % ("PASS" if not bad else "FAIL",
                                          len(bad)))
    for b in bad:
        print("  ! " + b)
    del lk
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
