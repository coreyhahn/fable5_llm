#!/usr/bin/env python3
"""s1p_reorderA_nocsv.py — S1P fix round 1 (I2): `chat_seq --reorder A`
resolves, regenerates the reordered template and matches the committed pin
with the BN1 CSV made UNREADABLE (ov_census.load_csv and reorder_e4.Windows
both raise), i.e. on the static cost table alone.  BOARD-FREE.

    FABLE5_MODEL=9b python evidence/qwen9b/ov/s1p_reorderA_nocsv.py
"""
import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "sw"), os.path.join(ROOT, "ref"),
                os.path.join(ROOT, "ref", "scripts")]
import chat_seq as CS                                          # noqa: E402

RE = CS._reorder_mod()
reads = []


def boom(*_a, **_k):
    reads.append(1)
    raise RuntimeError("the BN1 CSV was read")


RE.OC.load_csv = boom
RE.Windows = boom
args = types.SimpleNamespace(template=CS.TEMPLATE4_PREFIX, nch=4, reorder="A")
try:
    rep = CS.resolve_reorder(args)
    ok = (rep["regenerated_sha256"] == CS.REORDER4_BY_FORM["A"][1]
          and args.template.endswith("model_9b_s1_reordA.e4") and not reads)
    print(f"regenerated {rep['regenerated_sha256']}")
    print(f"pinned      {CS.REORDER4_BY_FORM['A'][1]}")
    print(f"CSV reads attempted: {len(reads)}; template -> {args.template}")
except Exception as e:                                          # noqa: BLE001
    ok = False
    print(f"REFUSED: {type(e).__name__}: {e}")
print("REORDER_A_NOCSV: " + ("PASS" if ok else "FAIL"))
sys.exit(0 if ok else 1)
