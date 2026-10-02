#!/usr/bin/env python3
"""gate A3's ANCHOR, on its own: `layer_fixed_greedy` still reproduces the
committed golden tokens at 0.8B after both fixes to that function.

`ref/seq_chat.gate_a3` opens with

    anchor = layer_fixed_greedy([760, 6511, 314, 9338], 3)
    want   = [561, 314, 279, 369, 279, 6511]

and that single call exercises BOTH sites this branch touched inside
`layer_fixed_greedy`: the embedding table read (defect A) and the final
RMSNorm + DYNQ8 + LM head (the loud sibling).  At 0.8B `LR.H == 1024`, so
both fixes must be byte-identical to the frozen behaviour — this is the
check that says so, without paying for A3's four extra prompts.

Runs at the default geometry (FABLE5_MODEL unset == 0.8b).
"""
import os
import sys
import time

R = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(R, "ref"))

import seq_chat as SC                                          # noqa: E402
import layer_ref as LR                                         # noqa: E402
from model_select import TAG                                   # noqa: E402

PROMPT = [760, 6511, 314, 9338]
WANT = [561, 314, 279, 369, 279, 6511]


def main():
    print(f"FABLE5_MODEL={TAG}  H={LR.H}")
    print(f"anchor prompt {PROMPT} ntok 3   want {WANT}")
    t0 = time.time()
    got = SC.layer_fixed_greedy(PROMPT, 3)
    ok = (got == WANT)
    print(f"got  {got}   ({time.time() - t0:.0f}s)")
    print(f"A3 ANCHOR: {'PASS' if ok else 'FAIL'} — layer_fixed_greedy "
          f"{'reproduces' if ok else 'does NOT reproduce'} the committed "
          f"golden tokens")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
