#!/usr/bin/env python3
"""sr11c_undo_ea72c43.py — SR11c pass 2a's precondition: put back the
`sw/seq_run.py` numbers that SR7 fix 1's drift commit ea72c43 wrote into
documents that were NOT in its base's coordinates.

WHY.  ea72c43 ran o3 at base 99c13ce (evidence/qwen9b/sr/sr7f1_drift.sh) on
the assumption that every document named `sw/seq_run.py` lines as they were
at 99c13ce.  They did not: SR11a fix 2 (cfbf90f, 11:07, between 9c8e73b and
99c13ce) had moved nearly every seq_run line (+4 at line 20, +13 by 168, ...)
and its drift was applied to NEXT_SESSION.md ONLY
(evidence/qwen9b/sr/n1149k_sr11af2_drift_fix_nextsession.log).  So every
other document still named 9c8e73b lines, and ea72c43 mapped those numbers
through the 99c13ce map — e.g. SR6_HOST.md's parse_caps cite 3121 (parse_caps
at 9c8e73b) became 3163 (nothing), where the right answer is parse_caps.
The provable repair is o3 at base 9c8e73b; o3 --fix renumbers the numbers
a document names NOW, so those documents must name their 9c8e73b numbers
again first.  This script does exactly that and nothing else.

METHOD, per (removed, added) line pair of ea72c43's diff in a document other
than NEXT_SESSION.md and the logs:
  * the removed line must be present VERBATIM in the document at 9c8e73b
    (else the line was written after 9c8e73b, not in 9c8e73b coordinates:
    SKIPPED and reported, for the pass's hand check);
  * the working line is the one whose digit-stripped text equals the added
    line's (exactly one; else reported);
  * the numbers are aligned run by run: a run ea72c43 changed (removed !=
    added) is set back to the removed value when the working line still
    holds the added value; a run it did not change keeps the working value
    (so a later pass's edit to another file's cite on the same line — pass 1's
    sw/hwmap.py — survives); a changed run that no longer holds the added
    value is a CONFLICT, reported and not touched.
Digits only, by construction.
  sr11c_undo_ea72c43.py --check | --apply
"""
import re
import subprocess
import sys

REPO = "/home/cah/r2d2/code/fpga/fable5_llm"
C = "ea72c43"
BASE = "9c8e73b"
NUM = re.compile(r"\d+")


def git(*a):
    r = subprocess.run(["git"] + list(a), cwd=REPO, capture_output=True,
                       text=True)
    return r.stdout


def pairs(doc):
    """[(removed, added)] from ea72c43's -U0 diff of one document."""
    out, rem, add = [], [], []
    for line in git("show", "-U0", "--format=", C, "--", doc).split("\n"):
        if line.startswith("@@"):
            if len(rem) != len(add):
                raise SystemExit("unequal hunk in %s" % doc)
            out += list(zip(rem, add))
            rem, add = [], []
        elif line.startswith("---") or line.startswith("+++"):
            continue
        elif line.startswith("-"):
            rem.append(line[1:])
        elif line.startswith("+"):
            add.append(line[1:])
    if len(rem) != len(add):
        raise SystemExit("unequal hunk in %s" % doc)
    return out + list(zip(rem, add))


def skel(s):
    return NUM.sub("#", s)


def main():
    apply = "--apply" in sys.argv
    docs = [d for d in git("show", "--name-only", "--format=", C).split()
            if d != "NEXT_SESSION.md" and not d.endswith(".log")]
    tot = rev = skip = conf = 0
    for doc in docs:
        base_lines = set((git("show", "%s:%s" % (BASE, doc))).split("\n"))
        with open("%s/%s" % (REPO, doc), encoding="utf-8") as f:
            work = f.read().split("\n")
        changed = False
        for rm, ad in pairs(doc):
            tot += 1
            if rm not in base_lines:
                skip += 1
                print("  SKIP     %s  (removed line not at %s)\n           %s"
                      % (doc, BASE, rm.strip()[:110]))
                continue
            hits = [i for i, w in enumerate(work) if skel(w) == skel(ad)]
            if len(hits) != 1:
                conf += 1
                print("  CONFLICT %s  (%d working lines match the added "
                      "line's skeleton)\n           %s"
                      % (doc, len(hits), ad.strip()[:110]))
                continue
            i = hits[0]
            r_n, a_n, w_n = (NUM.findall(rm), NUM.findall(ad),
                             NUM.findall(work[i]))
            if skel(rm) != skel(ad) or not (len(r_n) == len(a_n) == len(w_n)):
                conf += 1
                print("  CONFLICT %s:%d  (skeletons differ)" % (doc, i + 1))
                continue
            new_n, bad, moved = [], False, []
            for r, a, w in zip(r_n, a_n, w_n):
                if r != a:
                    if w == a:
                        new_n.append(r)
                        moved.append("%s->%s" % (a, r))
                    else:
                        bad = True
                        new_n.append(w)
                else:
                    new_n.append(w)
            if bad:
                conf += 1
                print("  CONFLICT %s:%d  (a changed number moved since)"
                      % (doc, i + 1))
                continue
            it = iter(new_n)
            nl = NUM.sub(lambda _m: next(it), work[i])
            if nl != work[i]:
                work[i] = nl
                changed = True
                rev += 1
                print("  REVERT   %s:%d  %s" % (doc, i + 1, " ".join(moved)))
        if changed and apply:
            with open("%s/%s" % (REPO, doc), "w", encoding="utf-8") as f:
                f.write("\n".join(work))
    print("SR11C_UNDO_EA72C43 %s: %d line pair(s) in %d document(s); "
          "reverted %d, skipped (not at %s) %d, conflict %d"
          % ("APPLIED" if apply else "CHECK", tot, len(docs), rev, BASE,
             skip, conf))
    return 0 if conf == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
