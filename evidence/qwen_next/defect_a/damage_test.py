#!/usr/bin/env python3
"""Deliberate damage: put the PRE-FIX reader back and re-run the regression.

`ref/seq_chat.emb_geometry_selftest()` is the new regression.  This script
monkeypatches `seq_chat.emb_row_bytes` / `seq_chat.load_emb` back to the
literals that were there before the fix

    n   = os.path.getsize(embf) // 2048
    emb = np.memmap(embf, dtype="<i2", mode="r").reshape(n, 1024)

and runs the SAME regression against them, at whichever geometry
FABLE5_MODEL selects.  Expected:

    FABLE5_MODEL=0.8b   PASS   (H=1024: the literals happen to be right)
    FABLE5_MODEL=2b     FAIL   (H=2048)
    FABLE5_MODEL=4b     FAIL   (H=2560)
    FABLE5_MODEL=9b     FAIL   (H=4096)

Every failure is SILENT in the reader — wrong rows, no exception — which is
what makes the regression the thing that has to catch it.  (Correction,
2026-08-25: an earlier revision of the regression used an ODD synthetic
vocab, which made the pre-fix reshape raise at H=2560 and was reported as
"loud at this geometry".  The real vocabulary is even; see CORRECTIONS.md.)

Exit code is INVERTED except at 0.8b: this script exits 0 when the damaged
reader behaves as the defect report says it does.
"""
import os
import sys

import numpy as np

R = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(R, "ref"))

import seq_chat as SC                                          # noqa: E402
import layer_ref as LR                                         # noqa: E402
from model_select import TAG                                   # noqa: E402


def prefix_emb_row_bytes(base):
    """The pre-fix code had no such function; 2048 B was assumed."""
    return 2048


def prefix_load_emb(base, emb_path=None, expect_vocab=None):
    """ref/seq_chat.py at 2a50cac^, lines 935-936 and 1213-1215, verbatim,
    as they were.

    `expect_vocab` is accepted and IGNORED on purpose: the pre-fix code had
    no vocabulary cross-check at all, and swallowing the argument is what
    lets the same regression body run against both readers.
    """
    if emb_path is None:
        emb_path = base + ".emb.bin"
    n = os.path.getsize(emb_path) // 2048
    emb = np.memmap(emb_path, dtype="<i2", mode="r").reshape(n, 1024)
    return emb, n


def main():
    SC.emb_row_bytes = prefix_emb_row_bytes
    SC.load_emb = prefix_load_emb
    print(f"### DAMAGED reader (pre-fix literals) at FABLE5_MODEL={TAG} (H={LR.H})")
    # guards=False: the refusal checks (short table, other-geometry
    # manifest, no manifest, wrong vocab, mis-named path) are all NEW with
    # the fix, so the pre-fix reader fails them at EVERY geometry including
    # 0.8b.  Dropping them isolates the geometry defect itself, which is the
    # thing under test here.
    try:
        passed = SC.emb_geometry_selftest(guards=False)
    except Exception as e:                      # a raise is also a "caught it"
        print(f"    [regression raised] {type(e).__name__}: {e}")
        passed = False
    want_pass = (LR.H == 1024)          # the one geometry the literals fit
    verdict = (passed == want_pass)
    print(f"### damaged reader {'PASSED' if passed else 'FAILED'} the "
          f"regression; expected {'PASS' if want_pass else 'FAIL'} at "
          f"FABLE5_MODEL={TAG}  ->  {'as documented' if verdict else 'UNEXPECTED'}")
    raise SystemExit(0 if verdict else 1)


if __name__ == "__main__":
    main()
