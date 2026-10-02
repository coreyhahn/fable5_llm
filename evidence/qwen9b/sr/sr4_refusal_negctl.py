#!/usr/bin/env python3
"""sr4_refusal_negctl.py — SR4 fix round 1 (review minor 3): the negative
control for ref/seq_model.selftest_running_refusal.  It runs the selftest
with SeqExec's `caps` argument forced to the EMPTY set, so each r1_ stream's
masked FENCE raises SeqValidationError instead of reaching the refusal.  The
selftest must report those cases as "error" and FAIL overall.  It must never
count them as refused hazards.

    /home/cah/.venv/bin/python evidence/qwen9b/sr/sr4_refusal_negctl.py

Exit 0 when the selftest FAILS as it must; exit 1 if it passes vacuously.
"""
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                    ".."))
sys.path.insert(0, os.path.join(REPO, "ref"))
import seq_model as SM                       # noqa: E402

_Real = SM.SeqExec


class _NoCaps(_Real):
    def __init__(self, *a, **k):
        k["caps"] = frozenset()
        super().__init__(*a, **k)


SM.SeqExec = _NoCaps
q = SM.selftest_running_refusal()
SM.SeqExec = _Real
errs = sorted(n for n, v in q["cases"].items() if v == "error")
print(f"cases {q['cases']}")
print(f"refused {q['refused']}/{q['hazards']}; errors {errs}; selftest ok "
      f"{q['ok']}")
good = (not q["ok"]) and errs == sorted(n for n in q["cases"]
                                        if n.startswith("r1_"))
print("NEGCTL: " + ("PASS (the wrong-caps run FAILS the selftest; no "
                    "SeqValidationError counted as a refusal)"
                    if good else "FAIL"))
raise SystemExit(0 if good else 1)
