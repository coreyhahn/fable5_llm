#!/usr/bin/env python3
"""sr6fix1_hand_repairs.py — SR6 fix round 1: the citation tokens re-pointed
BY HAND after the fix's edits (base 3b3c727), the sr6_hand_repairs.py
pattern, checked WHOLE-FILE (the doc names NEW somewhere and OLD nowhere):

  * SR6_HOST.md's own sw/seq_run.py tokens (the gate doc is excluded from
    the o3 pass; the fix's docstring/help lines shifted them +1 / +3);
  * the --doc-cites class (n633): tokens into docs/USAGE.md (+7 after its
    §3 paragraph grew) and NEXT_SESSION.md (+5 after the admission
    paragraph's SR6 sentence).
NOT re-aimed (records / not ours): BOARD_LOCK.md's was/now table
(645-647), sr6_hand_repairs.py (n617's list), RD9_GATE.md:2613's sha pin
f9828f2:NEXT_SESSION.md:6-731, and the board-idle-counters spec's
NEXT_SESSION.md:385, already stale in content at 3b3c727.
Prints base text at OLD beside work text at NEW.  Nothing numeric.
"""
import re, subprocess, sys
BASE = "3b3c727"
H = "evidence/qwen9b/sr/SR6_HOST.md"
E = [(H, "sw/seq_run.py:" + o, "sw/seq_run.py:" + n) for o, n in (
    ("9-22", "9-23"), ("242", "243"), ("297-298", "298-299"),
    ("605", "606"), ("795", "796"), ("1296", "1297"), ("3090", "3091"),
    ("3164", "3165"), ("3208-3234", "3211-3237"), ("3236-3253", "3239-3256"),
    ("3257", "3260"), ("3301", "3304"), ("2887", "2888"))] + [
 ("docs/superpowers/plans/2026-08-12-qwen2b-track-r.md", "docs/USAGE.md:577-581", "docs/USAGE.md:584-588"),
 ("docs/superpowers/plans/2026-08-16-qwen2b-v5-w8.md", "docs/USAGE.md:562-576", "docs/USAGE.md:569-583"),
 ("evidence/qwen9b/o3/BOARD_LOCK.md", "docs/USAGE.md:457", "docs/USAGE.md:464"),
 ("ref/scripts/regen_gate.sh", "docs/USAGE.md:577-581", "docs/USAGE.md:584-588"),
 ("evidence/qwen9b/g6/RD9_GATE.md", "NEXT_SESSION.md:416-417", "NEXT_SESSION.md:421-422"),
 ("evidence/qwen9b/g3/G3_3_MATVEC.md", "NEXT_SESSION.md:449", "NEXT_SESSION.md:454"),
 ("evidence/qwen9b/sr/SR2_ISA.md", "NEXT_SESSION.md:1082-1087", "NEXT_SESSION.md:1087-1092"),
]


def show(ref, path):
    return subprocess.run(["git", "show", "%s:%s" % (ref, path)],
                          capture_output=True, text=True).stdout.split("\n")


def ends(tok):
    fn, rng = tok.rsplit(":", 1)
    a, _, b = rng.partition("-")
    return fn, [int(a)] + ([int(b)] if b else [])


def check():
    bad = 0
    for d, old, new in E:
        t = open(d).read()
        o = len(re.findall(r"(?<![0-9A-Za-z/_.])" + re.escape(old) + r"(?![0-9-])", t))
        n = len(re.findall(re.escape(new) + r"(?![0-9-])", t))
        ok = o == 0 and n >= 1
        bad += not ok
        print("%s %s  %s -> %s" % ("OK " if ok else "BAD", d, old, new))
        fn, oe = ends(old)
        _, ne = ends(new)
        b, w = show(BASE, fn), open(fn).read().split("\n")
        for x in oe:
            print("      base %4d | %s" % (x, b[x - 1].strip()[:90]))
        for x in ne:
            print("      work %4d | %s" % (x, w[x - 1].strip()[:90]))
    print("SR6FIX1_HAND_REPAIRS %s (%d tokens, %d bad)"
          % ("PASS" if bad == 0 else "FAIL", len(E), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(check())
