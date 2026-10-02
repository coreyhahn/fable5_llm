#!/usr/bin/env python3
"""g6_frozen_footprint.py — what the FROZEN `--nch 1` chat session uploads.

Task 15 fix round 3, review I-2.  Scope E raised `ref/seq_chat.T_MAX` from
512 to 4,096 for EVERY model selection, so the frozen 0.8B/2B `--nch 1`
path — the one the shipped build_034/build_035 bitstreams run, whose
`rtl/layer_chan.sv kv_waddr` is still `tcnt[8:0]` — silently grew its
position pool 786,432 -> 6,291,456 B, its const blob by 5.5 MiB, and moved
every `data_base`-relative address with it.  Nothing on this board can
validate that: the 2B pack is gone and the 2B stream halts `err_op` on
build_041 (RD9_GATE.md §16.7).

This prints the whole footprint so the three trees can be compared byte for
byte:

    4662b06   the base of fix round 2 — the frozen numbers of record
    47e07cd   fix round 2's HEAD — the 8x pool the review found
    HEAD      fix round 3 — must be IDENTICAL to 4662b06

Run it in a worktree of each, pointing `--template` at the real (gitignored)
artifact.  NO BOARD, NO LOCK: `ChatSession.__init__` compiles, relocates and
plans without opening `/dev/xdma0_*`; nothing here calls `open_board`.
"""
import argparse
import hashlib
import json
import os
import sys
import types

TOP = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
for _p in (os.path.join(TOP, "sw"), os.path.join(TOP, "ref")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import chat_seq as C                                            # noqa: E402
import seq_chat as SC                                           # noqa: E402


def sha(b):
    return hashlib.sha256(bytes(b)).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default=C.TEMPLATE_PREFIX,
                    help="the FROZEN --nch 1 prefix (gitignored tree)")
    ap.add_argument("--t-max", type=int, default=None,
                    help="override the compiler ceiling (default: the "
                         "tree's own T_MAX)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    t_max = C.T_MAX if a.t_max is None else int(a.t_max)
    # 4662b06 predates chat_seq.MODEL_TAG (it landed with scope A), so this
    # probe must run against that tree too.
    tag = getattr(C, "MODEL_TAG", os.environ.get("FABLE5_MODEL", "0.8b"))
    print(f"=== FABLE5_MODEL={tag}  template="
          f"{os.path.basename(a.template)}  (--nch 1, the frozen path)")
    print(f"  T_MAX      chat_seq {C.T_MAX}  seq_chat {SC.T_MAX}  "
          f"compiling at {t_max}")
    print(f"  stride     POS_STRIDE {C.POS_STRIDE} B/pos  "
          f"POSBLOB_BYTES {C.POSBLOB_BYTES}")

    args = types.SimpleNamespace(
        template=a.template, nch=1, chan=0, t_max=t_max,
        pos_mode="ldc", max_ctx=min(C.DEFAULT_MAX_CTX, t_max - 1),
        any_template=False, force_upload=False,
        temp=C.DEFAULT_TEMP, top_k=C.DEFAULT_TOP_K, top_p=C.DEFAULT_TOP_P,
        seed=None, verify_head=False,
        prefill="lite", ntok=C.DEFAULT_NTOK, ntok_given=False,
        raw=False, system=None, dev="/dev/xdma0_user",
        timeout=C.STEP_TIMEOUT, preamble_timeout=C.PREAMBLE_TIMEOUT)
    sess = C.ChatSession(args, log=print)

    rep = {"model": tag, "t_max_chat_seq": C.T_MAX,
           "t_max_seq_chat": SC.T_MAX, "compiled_at": t_max,
           "pos_stride": C.POS_STRIDE, "posblob_bytes": C.POSBLOB_BYTES,
           "const_blob_bytes": len(sess.const_blob),
           "const_blob_sha256": sha(sess.const_blob),
           "plan": {k: int(v) for k, v in sorted(sess.plan.items())
                    if isinstance(v, int)},
           "images": {n: {"base": int(sess.images[n].base),
                          "nrec": int(sess.images[n].nrec),
                          "bytes": len(sess.images[n].data),
                          "sha256": sha(sess.images[n].data)}
                      for n in ("preamble", "lite", "full")}}
    print("-" * 72)
    print(f"  const blob {rep['const_blob_bytes']} B  sha "
          f"{rep['const_blob_sha256'][:32]}")
    for k, v in rep["plan"].items():
        print(f"  plan.{k:<12s} {v:#x}  ({v})")
    for n in ("preamble", "lite", "full"):
        im = rep["images"][n]
        print(f"  image {n:9s} base {im['base']:#x}  {im['nrec']:6d} recs  "
              f"{im['bytes']:8d} B  sha {im['sha256'][:32]}")
    print(f"  FOOTPRINT  {rep['const_blob_sha256'][:16]}/"
          + "/".join(rep["images"][n]["sha256"][:16]
                     for n in ("preamble", "lite", "full")))
    if a.out:
        json.dump(rep, open(a.out, "w"), indent=1)
    print("FROZEN FOOTPRINT: PRINTED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
