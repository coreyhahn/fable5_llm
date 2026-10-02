#!/usr/bin/env python3
"""g6_template_9b.py — the chat template, re-verified against the 9B jinja.

Task 15 Step 5's second half, and `evidence/qwen9b/g6/RD9_GATE.md` §20.3's
one outstanding rung.

WHAT WAS ON RECORD BEFORE THIS.  `sw/chat_seq.py`'s `HF_REF_SINGLE` and its
two siblings are the ids `tokenizer.apply_chat_template` produced on the
**2B** checkpoint on 2026-08-11 (`sw/chat_seq.py`, the comment block above
them).  The 9B path has been reading them ever since — including
`evidence/qwen9b/g6/056_chat_seq_9b_model_set.log` attempt [6], where the
9B tokenizer loaded and `ChatTemplate` rendered a turn EQUAL to
`HF_REF_SINGLE`.  What that could NOT show is whether the **9B
checkpoint's own** `chat_template.jinja` agrees, because nothing had run it.

WHY IT MIGHT NOT.  `docs/QWEN35_NEXT_FEASIBILITY.md:255` records that 4B
and 9B INVERT the `enable_thinking` default: left unset, the jinja opens a
`<think>` block instead of emitting the closed-empty one.  `chat_seq`'s
`ChatTemplate` builds the wrapper by ID SPLICE and emits the closed-empty
block EXPLICITLY, never passing `enable_thinking` — so the tool's stream is
the same either way, and this run says so with numbers instead of
reasoning.

So the rendering is taken BOTH ways, on the 9B snapshot, and both are
reported:

    unset               the checkpoint's own default
    enable_thinking=0   the closed-empty block chat_seq feeds

NO BOARD, NO LOCK.  Run on snoke through `evidence/qwen9b/run.sh`.
"""
import glob
import hashlib
import json
import os
import sys

TOP = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
for _p in (os.path.join(TOP, "sw"), os.path.join(TOP, "ref")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import chat_seq as C                                            # noqa: E402
import model_select as MS                                       # noqa: E402

Q = C.HF_REF_USER
CASES = (
    ("single", [{"role": "user", "content": Q}], C.HF_REF_SINGLE),
    ("system", [{"role": "system", "content": C.HF_REF_SYSTEM},
                {"role": "user", "content": Q}], C.HF_REF_SYSTEM_SINGLE),
    ("3msg", [{"role": "user", "content": Q},
              {"role": "assistant", "content": C.HF_REF_REPLY},
              {"role": "user", "content": C.HF_REF_USER2}], C.HF_REF_3MSG),
)


def snapshot_dir():
    hits = sorted(glob.glob(os.path.join(
        os.path.expanduser("~/.cache/huggingface/hub"), MS.REPO_DIR,
        "snapshots", "*", "tokenizer.json")))
    if not hits:
        raise SystemExit(f"no {MS.REPO_DIR} snapshot in the HF cache")
    return os.path.dirname(hits[0])


def main():
    import transformers
    from transformers import AutoTokenizer
    snap = snapshot_dir()
    jinja = os.path.join(snap, "chat_template.jinja")
    print(f"=== FABLE5_MODEL={MS.TAG}  repo={MS.REPO_DIR}")
    print(f"    snapshot     {os.path.basename(snap)}")
    print(f"    transformers {transformers.__version__}")
    with open(jinja, "rb") as f:
        raw = f.read()
    print(f"    chat_template.jinja {len(raw)} B  sha256 "
          f"{hashlib.sha256(raw).hexdigest()}")
    cfg = json.load(open(os.path.join(snap, "tokenizer_config.json")))
    inline = "present" if cfg.get("chat_template") else "absent"
    print(f"    tokenizer_config.json chat_template key: {inline} "
          f"(the .jinja file above is what transformers loads)")
    tk = AutoTokenizer.from_pretrained(snap)

    nfail = 0
    for name, msgs, want in CASES:
        for tag, kw in (("unset", {}), ("enable_thinking=0",
                                        {"enable_thinking": False})):
            got = list(tk.apply_chat_template(
                msgs, tokenize=True, return_dict=False,
                add_generation_prompt=True, **kw))
            ok = (got == want)
            print(f"  [{name:6s}] {tag:17s} {len(got):3d} ids  "
                  f"{'== the pinned reference' if ok else '!= DIFFERS'}")
            if not ok:
                print(f"             got  {got}")
                print(f"             want {want}")
                d = [i for i in range(max(len(got), len(want)))
                     if got[i:i + 1] != want[i:i + 1]]
                print(f"             first difference at index "
                      f"{d[0] if d else None}")
            if tag == "enable_thinking=0" and not ok:
                nfail += 1

    # what chat_seq ACTUALLY feeds, through its own id-splicing wrapper
    tk2 = C.load_tokenizer(log=lambda *a: None)
    tmpl = C.ChatTemplate(tk2)
    fed = tmpl.turn_ids(Q, first=True)
    print(f"  [chat_seq] ChatTemplate.turn_ids  {len(fed)} ids  "
          f"{'== HF_REF_SINGLE' if fed == C.HF_REF_SINGLE else '!= DIFFERS'}")
    print(f"             {fed}")
    if fed != C.HF_REF_SINGLE:
        nfail += 1

    print(f"  ntok guidance  `--ntok >= 24` (docs/USAGE.md:241); "
          f"evidence/qwen9b/g2/G2C_CHAIN.md §8.4 ruled it DOES NOT MOVE at "
          f"9B")
    print("TEMPLATE_9B: " + ("PASS" if nfail == 0 else f"FAIL ({nfail})"))
    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
