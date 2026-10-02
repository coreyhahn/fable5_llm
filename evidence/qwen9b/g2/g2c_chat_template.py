#!/usr/bin/env python3
"""g2c_chat_template.py — G2c Step 5: re-derive the chat template at 9B.

Two facts are routinely conflated and this script separates them by
MEASUREMENT rather than by assertion:

  * the TOKENIZING files (`tokenizer.json`, `vocab.json`, `merges.txt`) — are
    they the same across the four models?  If they are, the pinned PPL corpus
    and its 24,528 scored positions carry over untouched, and so does every
    id in the frozen wrapper.
  * the TEMPLATE files (`chat_template.jinja`, and `tokenizer_config.json`
    which embeds a copy of it) — Track L reports these DIFFER between the
    0.8B/2B pair and the 4B/9B pair, inverting the `enable_thinking` default.

It then renders the three canonical conversations HF's own way at 0.8B and at
9B, in every thinking mode, and compares each id list against the constants
frozen in `sw/chat_seq.py` — which is the only thing that can say whether the
host's id-spliced wrapper still reproduces the model's own template.

RUN ON SNOKE: the 4B and 9B snapshots exist only there.

    evidence/qwen9b/g2/g2c_chat_template.py [--json-out PATH]
"""
import argparse
import ast
import difflib
import glob
import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

HUB = os.path.expanduser("~/.cache/huggingface/hub")
MODELS = ("Qwen3.5-0.8B", "Qwen3.5-2B", "Qwen3.5-4B", "Qwen3.5-9B")
TOKENIZING = ("tokenizer.json", "vocab.json", "merges.txt")
TEMPLATING = ("chat_template.jinja", "tokenizer_config.json")

# the three canonical conversations of docs/INSTRUCT_SPEC.md T1/T5/T3,
# spelled with the same literals sw/chat_seq.py uses
Q = "What is the capital of France?"
SYS = "You are a helpful assistant."
REPLY = "Paris."
Q2 = "And of Italy?"
CONVS = {
    "single": [{"role": "user", "content": Q}],
    "system": [{"role": "system", "content": SYS},
               {"role": "user", "content": Q}],
    "3msg": [{"role": "user", "content": Q},
             {"role": "assistant", "content": REPLY},
             {"role": "user", "content": Q2}],
}
# frozen constant in sw/chat_seq.py that each rendering is pinned against
PINNED = {"single": "HF_REF_SINGLE", "system": "HF_REF_SYSTEM_SINGLE",
          "3msg": "HF_REF_3MSG"}


def snap(name):
    hits = sorted(glob.glob(os.path.join(HUB, f"models--Qwen--{name}",
                                         "snapshots", "*")))
    return hits[0] if hits else None


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def frozen_ids():
    """The pinned id lists, read out of sw/chat_seq.py without importing it.

    `ast` rather than `import`: the constants are what this check is about,
    and parsing the module text means a run cannot be perturbed by anything
    else that file does at import time.  The values are compared against the
    file the repo actually ships, so this is a check of the shipped constant.
    """
    src = open(os.path.join(REPO, "sw", "chat_seq.py")).read()
    tree = ast.parse(src)
    want = set(PINNED.values()) | {"WRAP_PER_MESSAGE", "WRAP_GEN_PROMPT",
                                   "TOK_IM_START", "TOK_IM_END", "TOK_THINK",
                                   "TOK_THINK_END", "TOK_ENDOFTEXT"}
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in want:
            out[node.targets[0].id] = ast.literal_eval(node.value)
    missing = want - set(out)
    if missing:
        raise SystemExit(f"sw/chat_seq.py: constants not found: "
                         f"{sorted(missing)}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out")
    a = ap.parse_args()
    rc = 0
    rep = {"models": {}, "classes": {}, "diff": {}, "renders": {},
           "pinned": {}}

    print("=== G2c Step 5 — the 9B chat template, re-derived ===\n")

    # ---------------- 1. which files are shared, which are not -----------
    snaps = {m: snap(m) for m in MODELS}
    for m, s in snaps.items():
        if s is None:
            raise SystemExit(f"no snapshot for {m} in {HUB} — this script "
                             f"must run on snoke, which has all four")
        rep["models"][m] = {"snapshot": s}
    print("1. FILE EQUIVALENCE CLASSES (sha256, first 16 hex)\n")
    hdr = f"  {'file':<24s}" + "".join(f"  {m.split('-')[-1]:>16s}"
                                       for m in MODELS)
    print(hdr)
    for f in TOKENIZING + TEMPLATING:
        digs = []
        for m in MODELS:
            p = os.path.join(snaps[m], f)
            digs.append(sha(p) if os.path.exists(p) else "ABSENT")
            rep["models"][m].setdefault("sha256", {})[f] = digs[-1]
        klass = {}
        for m, d in zip(MODELS, digs):
            klass.setdefault(d, []).append(m)
        rep["classes"][f] = {d[:16]: v for d, v in klass.items()}
        print(f"  {f:<24s}" + "".join(f"  {d[:16]:>16s}" for d in digs)
              + ("   ONE CLASS" if len(klass) == 1
                 else f"   {len(klass)} CLASSES"))
    print()
    tok_one = all(len(rep["classes"][f]) == 1 for f in TOKENIZING)
    tpl_two = all(len(rep["classes"][f]) == 2 for f in TEMPLATING)
    print(f"  tokenizing files ({', '.join(TOKENIZING)}): "
          + ("ONE class across all four models — the pinned PPL corpus and "
             "its 24,528 positions, and every wrapper id, carry over "
             "UNCHANGED" if tok_one else "*** NOT one class ***"))
    print(f"  templating files ({', '.join(TEMPLATING)}): "
          + ("TWO classes — 0.8B/2B share one, 4B/9B share the other"
             if tpl_two else "*** NOT two classes ***"))
    rc |= 0 if (tok_one and tpl_two) else 1
    print()

    # ---------------- 2. the template diff, measured ---------------------
    A = open(os.path.join(snaps["Qwen3.5-0.8B"],
                          "chat_template.jinja")).read().splitlines(True)
    B = open(os.path.join(snaps["Qwen3.5-9B"],
                          "chat_template.jinja")).read().splitlines(True)
    ud = list(difflib.unified_diff(A, B, "0.8B", "9B", n=3))
    changed = [l for l in ud if l[:1] in "+-" and l[:3] not in ("+++", "---")]
    print("2. chat_template.jinja — 0.8B vs 9B\n")
    print(f"  lines: 0.8B {len(A)}, 9B {len(B)}   "
          f"bytes: {os.path.getsize(os.path.join(snaps['Qwen3.5-0.8B'], 'chat_template.jinja'))}"
          f" / {os.path.getsize(os.path.join(snaps['Qwen3.5-9B'], 'chat_template.jinja'))}")
    print(f"  changed lines: {sum(1 for l in changed if l[0] == '-')} removed "
          f"+ {sum(1 for l in changed if l[0] == '+')} added "
          f"= {len(changed)} of {len(A)}")
    # The feasibility study calls this "a 12-line unified diff touching 3 of
    # the template's 154 lines".  Both halves reproduce here and the two
    # counts are of DIFFERENT things: 3 lines of the 0.8B file are replaced
    # by 3 of the 9B file (6 changed lines), inside a single hunk whose BODY
    # is 12 lines (6 context + 6 changed).  `len(ud)` adds the ---/+++/@@
    # headers on top of that body.
    print(f"  unified diff (n=3): {len(ud)} lines total = 3 header lines "
          f"+ a {len(ud) - 3}-line hunk body "
          f"({len(ud) - 3 - len(changed)} context + {len(changed)} changed)\n")
    for l in ud:
        print("    " + l.rstrip("\n"))
    rep["diff"] = {"lines_a": len(A), "lines_b": len(B),
                   "removed": sum(1 for l in changed if l[0] == '-'),
                   "added": sum(1 for l in changed if l[0] == '+'),
                   "unified_lines": len(ud),
                   "unified": [l.rstrip("\n") for l in ud]}
    print()

    # ---------------- 3. renderings ---------------------------------------
    from transformers import AutoTokenizer
    import transformers
    print(f"3. HF RENDERINGS  (transformers {transformers.__version__})\n")
    F = frozen_ids()
    rep["pinned"] = {k: F[v] for k, v in PINNED.items()}
    modes = [("default", {}),
             ("enable_thinking=True", {"enable_thinking": True}),
             ("enable_thinking=False", {"enable_thinking": False})]
    for m in ("Qwen3.5-0.8B", "Qwen3.5-9B"):
        tk = AutoTokenizer.from_pretrained(snaps[m])
        rep["renders"][m] = {}
        print(f"  --- {m} ---")
        for cname, msgs in CONVS.items():
            pin = F[PINNED[cname]]
            rep["renders"][m][cname] = {}
            for mname, kw in modes:
                ids = [int(i) for i in tk.apply_chat_template(
                    msgs, tokenize=True, return_dict=False,
                    add_generation_prompt=True, **kw)]
                same = ids == pin
                rep["renders"][m][cname][mname] = {"ids": ids, "eq_pin": same}
                print(f"    {cname:7s} {mname:22s} {len(ids):3d} ids  "
                      + ("== " if same else "!= ")
                      + f"{PINNED[cname]}"
                      + ("" if same else
                         f"   (tail differs from id {_first_diff(ids, pin)})"))
        print()

    # ---------------- 4. the consequence ----------------------------------
    print("4. WHAT IT MEANS FOR THE HOST WRAPPER\n")
    ok_default = rep["renders"]["Qwen3.5-0.8B"]["single"]["default"]["eq_pin"]
    ok_9b_def = rep["renders"]["Qwen3.5-9B"]["single"]["default"]["eq_pin"]
    ok_9b_off = (rep["renders"]["Qwen3.5-9B"]["single"]
                 ["enable_thinking=False"]["eq_pin"])
    print(f"  0.8B, enable_thinking UNSET     reproduces HF_REF_SINGLE: "
          f"{ok_default}")
    print(f"  9B,   enable_thinking UNSET     reproduces HF_REF_SINGLE: "
          f"{ok_9b_def}")
    print(f"  9B,   enable_thinking=False     reproduces HF_REF_SINGLE: "
          f"{ok_9b_off}")
    print()
    print(f"  WRAP_PER_MESSAGE = {F['WRAP_PER_MESSAGE']}, "
          f"WRAP_GEN_PROMPT = {F['WRAP_GEN_PROMPT']}  "
          f"(overhead = 5*messages + 7)")
    print(f"  the closed-empty block is [{F['TOK_THINK']}, enc('\\n\\n'), "
          f"{F['TOK_THINK_END']}, enc('\\n\\n')] = 4 ids;")
    print("  the OPEN block is [<think>, enc('\\n')] = 2 ids, so a host that "
          "followed\n  the 9B jinja default would emit a 5-id generation "
          "prompt and then have to\n  generate the reasoning and the "
          "'</think>' itself before any visible token.")
    print()
    if not (ok_default and ok_9b_off and not ok_9b_def):
        rc |= 1
        print("  *** UNEXPECTED: the three lines above do not read "
              "True / False / True ***")
    else:
        print("  Reading: the frozen wrapper is UNCHANGED as a SEQUENCE OF "
              "IDS at 9B — every\n  id in it comes from tokenizing files that "
              "are byte-identical across the four\n  models.  What changes is "
              "which HF invocation it CORRESPONDS to: at 0.8B/2B\n  it is "
              "`apply_chat_template(...)` with the default, at 4B/9B it is\n"
              "  `apply_chat_template(..., enable_thinking=False)`.  So the "
              "host's T2 decision\n  (\"NEVER enable_thinking=True\") is "
              "unchanged and its ids are unchanged; the\n  REFERENCE the "
              "selftest compares against must name the flag explicitly at 9B.")
    print()
    if a.json_out:
        with open(a.json_out, "w") as f:
            json.dump(rep, f, indent=1)
        print(f"json -> {a.json_out}")
    print("G2C_CHAT_TEMPLATE " + ("PASS" if rc == 0 else "FAIL"))
    return rc


def _first_diff(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return min(len(a), len(b))


if __name__ == "__main__":
    sys.exit(main())
