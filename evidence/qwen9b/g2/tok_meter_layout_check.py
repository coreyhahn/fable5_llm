#!/usr/bin/env python3
"""tok_meter_layout_check.py — what D-TOK's fix does to the DDR layout.

    /home/cah/.venv/bin/python evidence/qwen9b/g2/tok_meter_layout_check.py

G2a's §0 claims, as a MEASURED number, that `sw/tok_meter.py --four-chan`
moves 186 of its 187 image bases at 0.8B and drops the pack top from
`0x28e34000` to `0x16396000`.  Review found that number had no committed log
behind it — it came from an interactive session.  This file is that log.

WHAT IT COMPARES.  Both plans, on the SAME committed manifest:

  before  `plan_weights(man, wdir)`               — the nch-INDEPENDENT pack
          every channel reserves the WHOLE image.  This is what `tok_meter`
          asked for before G2a, and it is why the tool "cannot plan a 2B
          pack": four copies of a 2B pack collide with `EMB_BASE`.
  after   `plan_weights(man, wdir, nch=4, rows_of=split_rows-derived)`
          each channel reserves only the rows it owns — the layout the tool's
          own uploader has always written.

WHAT MOVING MEANS, AND WHAT IT DOES NOT.  The computation is unchanged: every
engine still reads its own rows, because `run_matvec` addresses them through
`wbase_chan(wid, i) + (r0 - cr0) * stride`.  What moves is WHERE those rows
sit on DDR.  **The hazard is `--skip-upload`**: a channel populated under one
layout and read under the other returns the wrong bytes from the right
addresses, with no error.  Anyone who uploaded with a pre-G2a `tok_meter`
must re-upload.

This is arithmetic on a committed manifest — no board, no DMA, no device.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "sw"))

import hwmap as HW                                              # noqa: E402
from tok_meter import split_rows                                # noqa: E402

PREFIX = os.path.join(_ROOT, "tb", "scripts", "w4", "model_v2_s1")
NCH = 4


def main():
    if not os.path.exists(PREFIX + ".weights.json"):
        sys.exit(f"missing {PREFIX}.weights.json (gitignored, regenerable)")
    man, meta = HW.load_weights_manifest(PREFIX)
    wdir = os.path.dirname(PREFIX)

    old, top_old = HW.plan_weights(man, wdir)

    def rows_of(_wid, nrows):
        return [n for (_r0, n) in split_rows(nrows, NCH)]

    new, top_new = HW.plan_weights(man, wdir, nch=NCH, rows_of=rows_of)

    def c0(v):
        return v[0] if isinstance(v, (list, tuple)) else v

    moved = [k for k in man if c0(new[int(k)]) != old[int(k)]]
    tops = top_new if isinstance(top_new, (list, tuple)) else (top_new,)

    print(f"  manifest        {PREFIX}.weights.json")
    print(f"  images          {len(man)}   (emb_row_bytes={meta['emb_row_bytes']}"
          f", rs_f={meta['rs_f']})")
    print(f"  nch             {NCH}")
    print(f"  channel-0 base MOVED for   {len(moved)} of {len(man)} images")
    print(f"  pack top  before (shared)  {top_old:#x}")
    print(f"  pack top  after  (repack)  "
          f"{'/'.join(f'{t:#x}' for t in tops)}")
    print(f"  W_BASE                     {HW.W_BASE:#x}")
    print(f"  bytes reserved before      {top_old - HW.W_BASE:,}")
    print(f"  bytes reserved after (ch0) {max(tops) - HW.W_BASE:,}")

    # The one image that does NOT move is the first one placed: both plans
    # start it at W_BASE.  Everything after it shifts because the shared pack
    # advances by the WHOLE image and the repack by one channel's share.
    still = [k for k in man if k not in moved]
    print(f"  unmoved                    {still} (both plans start at W_BASE)")

    ok = len(man) > 0
    print("TOK_METER_LAYOUT: "
          + (f"{len(moved)}/{len(man)} image bases move — the computation is "
             f"unchanged, the LAYOUT is not (see --skip-upload above)"
             if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
