#!/usr/bin/env python3
"""sr6_hand_repairs.py — Task SR6: the citation tokens the o3 drift tool
cannot renumber, re-pointed BY HAND (the sr3c_hand_repairs.py pattern).

  * 15 sw/ tokens the tool reports UNRESOLVED (n611): SR6 REWROTE the cited
    line (the three seq_run validate_stream calls, chat_seq's two, the
    module contract line, reorder_b_images' def, and the B3 refusal block
    that moved above the artifacts), so there is no base->work map;
  * 5 tokens into docs/USAGE.md (the --doc-cites class, n615), which is
    check-only in the tool.  NOT re-aimed: the "was / now" TABLE of
    evidence/qwen9b/o3/BOARD_LOCK.md:645-647, a record of O3's own repair.

--check (what the n6xx log records): each doc line now carries NEW and no
longer OLD; prints the 7e72126 text at OLD's endpoints beside the working
text at NEW's.  Nothing numeric; reads git + files only.  Run on snoke.
"""
import re, subprocess, sys
BASE = "7e72126"
P = "docs/superpowers/plans/2026-09-27-seq-rtl-round.md"
E = [
 (P, 59, "sw/seq_run.py:254", "sw/seq_run.py:297"),
 (P, 59, "sw/seq_run.py:559", "sw/seq_run.py:605"),
 (P, 59, "sw/seq_run.py:746", "sw/seq_run.py:795"),
 (P, 59, "sw/seq_run.py:10", "sw/seq_run.py:16"),
 (P, 275, "sw/seq_run.py:254", "sw/seq_run.py:297"),
 (P, 275, "sw/seq_run.py:559", "sw/seq_run.py:605"),
 (P, 275, "sw/seq_run.py:746", "sw/seq_run.py:795"),
 (P, 275, "sw/seq_run.py:10", "sw/seq_run.py:16"),
 (P, 276, "sw/chat_seq.py:474", "sw/chat_seq.py:477"),
 (P, 276, "sw/chat_seq.py:514", "sw/chat_seq.py:518"),
 ("NEXT_SESSION.md", 369, "sw/seq_run.py:3131", "sw/seq_run.py:3213"),
 ("NEXT_SESSION.md", 372, "sw/seq_run.py:3148", "sw/seq_run.py:3230"),
 ("NEXT_SESSION.md", 384, "sw/seq_run.py:3143-3152", "sw/seq_run.py:3225-3234"),
 ("NEXT_SESSION.md", 1330, "sw/seq_run.py:3143-3152", "sw/seq_run.py:3225-3234"),
 ("evidence/qwen9b/ov/S1P_SHIP.md", 161, "sw/chat_seq.py:794", "sw/chat_seq.py:903"),
 ("docs/superpowers/plans/2026-08-12-qwen2b-track-r.md", 17, "docs/USAGE.md:551-555", "docs/USAGE.md:577-581"),
 ("docs/superpowers/plans/2026-08-12-qwen2b-track-r.md", 48, "docs/USAGE.md:551-555", "docs/USAGE.md:577-581"),
 ("docs/superpowers/plans/2026-08-16-qwen2b-v5-w8.md", 238, "docs/USAGE.md:536-550", "docs/USAGE.md:562-576"),
 ("evidence/qwen9b/o3/BOARD_LOCK.md", 411, "docs/USAGE.md:431", "docs/USAGE.md:457"),
 ("ref/scripts/regen_gate.sh", 5, "docs/USAGE.md:551-555", "docs/USAGE.md:577-581"),
]


def show(ref, path):
    return subprocess.run(["git", "show", "%s:%s" % (ref, path)],
                          capture_output=True, text=True).stdout.split("\n")


def ends(tok):
    fn, rng = tok.strip("`").rsplit(":", 1)
    a, _, b = rng.partition("-")
    return fn, [int(a)] + ([int(b)] if b else [])


def check():
    bad = 0
    for d, ln, old, new in E:
        line = open(d).read().split("\n")[ln - 1]
        o = len(re.findall(re.escape(old) + r"(?![0-9-])", line))
        n = len(re.findall(re.escape(new) + r"(?![0-9-])", line))
        ok = (o == 0 and n >= 1)
        bad += not ok
        print("%s %s:%d  %s -> %s" % ("OK " if ok else "BAD", d, ln, old, new))
        fn, oe = ends(old)
        _, ne = ends(new)
        b = show(BASE, fn)
        w = open(fn).read().split("\n")
        for x in oe:
            print("      base %4d | %s" % (x, b[x - 1].strip()[:90]))
        for x in ne:
            print("      work %4d | %s" % (x, w[x - 1].strip()[:90]))
    print("SR6_HAND_REPAIRS %s (%d tokens, %d bad)"
          % ("PASS" if bad == 0 else "FAIL", len(E), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(check())
