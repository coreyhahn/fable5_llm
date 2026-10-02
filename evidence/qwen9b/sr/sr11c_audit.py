#!/usr/bin/env python3
"""sr11c_audit.py — SR11c: the HAND-CHECK sheet for one o3 cite-drift plan.

o3's --plan (evidence/qwen9b/o3/o3_cite_drift.py) says WHAT a --fix would
rewrite, split REPAIR / COLLATERAL.  This prints, for EVERY planned rewrite,
what a human needs to judge it without re-deriving it:
  * the class (REPAIR / COLLATERAL), from o3's own plan_split (imported, so
    the sheet cannot disagree with the plan);
  * AT-BASE yes/no: is the citing line present VERBATIM in the document at
    the pass base?  A REPAIR on a line that is NOT at the base is SUSPECT (a
    token written after the base whose number happens to equal an old cite);
  * the cited code: the base content at the old line, the working content at
    the old line and at the proposed new line;
  * the citing document line (trimmed).
Read-only; writes nothing.  Takes o3's own arguments (the wrapper passes them).
  sr11c_audit.py --base B --doc-base B --edited f1,f2 [--exclude DOC]...
"""
import argparse
import importlib.util
import os
import sys

REPO = "/home/cah/r2d2/code/fpga/fable5_llm"
spec = importlib.util.spec_from_file_location(
    "o3", os.path.join(REPO, "evidence/qwen9b/o3/o3_cite_drift.py"))
o3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(o3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--doc-base", default=None)
    ap.add_argument("--edited", required=True)
    ap.add_argument("--exclude", action="append", default=[])
    a, _rest = ap.parse_known_args()
    o3._set_edited([p for p in a.edited.split(",") if p])
    dbase = a.doc_base or a.base
    _ok, drift, unres, missing, _n, half = o3.classify(a.base, dbase, 0)
    per_doc, skipped = o3.plan_split(a.base, drift, exclude=a.exclude)
    code_b, code_w = {}, {}
    for fn in o3.EDITED:
        code_b[fn] = (o3.git_show(a.base, fn) or "").split("\n")
        code_w[fn] = (o3.work_text(fn) or "").split("\n")

    def cl(lines, n):
        return lines[n - 1].strip()[:72] if 1 <= n <= len(lines) else "<EOF>"

    nrep = nsus = ncol = 0
    for doc, reps, cols in per_doc:
        wt = (o3.work_text(doc) or "").split("\n")
        bt = set((o3.git_show(a.base, doc) or "").split("\n"))
        print("=== %s  (REPAIR %d, COLLATERAL %d)" % (doc, len(reps), len(cols)))
        for kind, lst in (("REPAIR", reps), ("COLLATERAL", cols)):
            for t in lst:
                fn, x, y, nx, ny, old, new = t
                where = [i for i, l in enumerate(wt, 1) if old in l]
                atb = all(wt[i - 1] in bt for i in where) if where else False
                tag = kind
                if kind == "REPAIR":
                    nrep += 1
                    if not atb:
                        tag = "REPAIR-SUSPECT"
                        nsus += 1
                else:
                    ncol += 1
                print("  %-14s %s -> %s   doc lines %s   at-base %s"
                      % (tag, old, new, ",".join(map(str, where)) or "?",
                         "yes" if atb else "NO"))
                print("      base %s:%d  %r" % (fn, x, cl(code_b[fn], x)))
                print("      work %s:%d  %r" % (fn, x, cl(code_w[fn], x)))
                print("      work %s:%d  %r   <- proposed" % (fn, nx, cl(code_w[fn], nx)))
                if y is not None:
                    print("      base end :%d %r / work end :%d %r"
                          % (y, cl(code_b[fn], y), ny, cl(code_w[fn], ny)))
                for i in where[:2]:
                    s = wt[i - 1]
                    k = s.find(old)
                    print("      doc:%d  ...%s..." % (i, s[max(0, k - 90):k + len(old) + 40]))
    for d in skipped:
        print("  EXCLUDED %s" % d)
    print("--- UNRESOLVED (cited base line rewritten/deleted; o3 leaves these):")
    for fn, ln, who, txt, why in unres:
        w = [x for x in who if x not in a.exclude]
        if w:
            print("  %s:%d %r  cited by %s" % (fn, ln, txt, ", ".join(w)))
    print("--- HALF-MAPPED:")
    for h in half:
        w = [x for x in h[5] if x not in a.exclude]
        if w:
            print("  %s:%d-%d  cited by %s" % (h[0], h[1], h[2], ", ".join(w)))
    print("--- MISSING (past the base EOF / absent):")
    for fn, ln, who, why in missing:
        w = [x for x in who if x not in a.exclude]
        if w:
            print("  %s:%d %s cited by %s" % (fn, ln, why, ", ".join(w)))
    print("SR11C_AUDIT REPAIR %d (of which SUSPECT %d)  COLLATERAL %d"
          % (nrep, nsus, ncol))


if __name__ == "__main__":
    sys.exit(main())
