#!/usr/bin/env python3
"""sr3c_hand_repairs.py — Task SR3c: the 16 citation tokens the o3 drift
tool cannot renumber (n1981: 8 UNRESOLVED lines inside 4 HALF-MAPPED ranges
+ singles — SR3 REWROTE the cited line, so there is no base->work map).
Each was re-pointed BY HAND to the successor line(s) after opening the
target; the list below is the whole decision.  The APPLY half ran once
(identical list, before this file was committed); --check is the residual
proof and is what the n198x log records:

  * the doc line now carries NEW and no longer carries OLD;
  * prints the 3ae0ff9 text at OLD's endpoints beside the working-tree
    text at NEW's endpoints, so a reader sees what each cite moved to.

Nothing numeric; reads git + files only.  Run on snoke via sr_run.sh.
"""
import re, subprocess, sys
BASE = "3ae0ff9"
E = [
 ("docs/superpowers/specs/2026-09-24-board-idle-counters-design.md", 147, "rtl/seq_movers.sv:812-814", "rtl/seq_movers.sv:821-824"),
 ("docs/SEQ_ISA.md", 1473, "`rtl/seq_movers.sv:818`", "`rtl/seq_movers.sv:828`"),
 ("docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md", 103, "rtl/seq_unit.sv:794-797", "rtl/seq_unit.sv:806-813"),
 ("docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md", 136, "rtl/seq_unit.sv:794-797", "rtl/seq_unit.sv:806-813"),
 ("docs/superpowers/plans/2026-09-27-seq-rtl-round.md", 176, "rtl/seq_unit.sv:794-797", "rtl/seq_unit.sv:806-813"),
 ("docs/superpowers/plans/2026-09-27-seq-rtl-round.md", 190, "rtl/seq_unit.sv:794-797", "rtl/seq_unit.sv:806-813"),
 ("docs/superpowers/plans/2026-09-27-seq-rtl-round.md", 180, "tb/Makefile:862", "tb/Makefile:865"),
 ("docs/superpowers/plans/2026-09-27-seq-rtl-round.md", 180, "tb/Makefile:870", "tb/Makefile:875"),
 ("docs/superpowers/plans/2026-09-27-seq-rtl-round.md", 61, "tb/scripts/gen_seq_unit_vectors.py:282-283", "tb/scripts/gen_seq_unit_vectors.py:306-320"),
 ("docs/superpowers/plans/2026-09-27-seq-rtl-round.md", 62, "tb/scripts/gen_seq_unit_vectors.py:282-283", "tb/scripts/gen_seq_unit_vectors.py:306-320"),
 ("docs/superpowers/plans/2026-09-27-seq-rtl-round.md", 178, "tb/scripts/gen_seq_unit_vectors.py:282-283", "tb/scripts/gen_seq_unit_vectors.py:306-320"),
 ("docs/superpowers/plans/2026-09-27-seq-rtl-round.md", 178, "tb/scripts/gen_seq_unit_vectors.py:362-364", "tb/scripts/gen_seq_unit_vectors.py:399-409"),
 ("docs/superpowers/plans/2026-09-27-seq-rtl-round.md", 190, "tb/scripts/gen_seq_unit_vectors.py:679", "tb/scripts/gen_seq_unit_vectors.py:812"),
 ("evidence/qwen9b/g3/G3_4_LAYER.md", 986, "tb/scripts/gen_seq_unit_vectors.py:679", "tb/scripts/gen_seq_unit_vectors.py:812"),
 ("evidence/qwen9b/g3/G3_4_LAYER.md", 1286, "tb/scripts/gen_seq_unit_vectors.py:679", "tb/scripts/gen_seq_unit_vectors.py:812"),
 ("evidence/qwen9b/g4/G4A_REPLAY.md", 216, "tb/scripts/gen_seq_unit_vectors.py:679", "tb/scripts/gen_seq_unit_vectors.py:812"),
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
    print("SR3C_HAND_REPAIRS %s (%d tokens, %d bad)"
          % ("PASS" if bad == 0 else "FAIL", len(E), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(check())
