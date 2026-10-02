#!/usr/bin/env python3
"""sr11c_prove_stale.py — SR11c pass 4: which PRE-EXISTING stale citations
can o3's own line map PROVE the right number for?

Input: spec_cites QUOTE failures into the round's files (the survey,
evidence/qwen9b/sr/sr11c_stale_survey.sh, re-run here).  A QUOTE failure is
`"<quote>" — present in F but NOT within 6 lines of the cited line`.

THE PROOF, per full `F:N` / `F:N-M` token on the failing document line (bare
`:NNN` continuations are not handled and are listed):
  1. C0 = the commit that INTRODUCED the quotation into the document
     (`git log -S<quote> --reverse`, the first hit);
  2. at C0, the same document line (same digit-stripped skeleton, else the
     line carrying the quote) and the k-th F token on it: N0;
  3. BORN RIGHT?  at C0, the quote (whitespace-normalised prefix) is within
     6 lines of N0 in F@C0 — spec_cites' own criterion.  If not, the cite
     was stale when written: NOT provable (SR9);
  4. N* = o3's line_map (evidence/qwen9b/o3/o3_cite_drift.py, imported)
     from F@C0 to the working F; an endpoint that maps to None was rewritten:
     NOT provable (SR9);
  5. at HEAD the quote is within 6 lines of N* — else NOT provable (SR9);
  6. N* != the number the document names now -> PROVEN REPAIR (N -> N*).
Read-only: prints the proof and the (doc, line, old token, new token) list;
the edits are made by hand with the Edit tool and re-checked by spec_cites.
  sr11c_prove_stale.py
"""
import importlib.util
import os
import re
import subprocess
import sys

REPO = "/home/cah/r2d2/code/fpga/fable5_llm"
spec = importlib.util.spec_from_file_location(
    "o3", os.path.join(REPO, "evidence/qwen9b/o3/o3_cite_drift.py"))
o3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(o3)

FILES = ["sw/hwmap.py", "sw/seq_run.py", "sw/chat_seq.py", "ref/seq_chat.py",
         "ref/seq_model.py", "ref/seq_format.py", "ref/seq_cost.py",
         "rtl/seq_unit.sv", "rtl/seq_movers.sv", "rtl/matvec_chan.sv",
         "rtl/matvec_engine.sv"]
T = "|".join(re.escape(f) for f in FILES)
FAIL = re.compile(r'^  (\S+):(\d+)  QUOTE  "(.*)" — present in (\S+) but NOT '
                  r'within 6 lines')
NUM = re.compile(r"\d+")


def git(*a):
    return subprocess.run(["git"] + list(a), cwd=REPO, capture_output=True,
                          text=True).stdout


def norm(s):
    return " ".join(s.replace("`", " ").split())


def near(lines, n, q, w=6):
    lo, hi = max(1, n - w), min(len(lines), n + w)
    return norm(q) in norm(" ".join(lines[lo - 1:hi]))


def docs():
    out = git("ls-files", "--", "docs/*.md", "docs/*.txt", "evidence/*.md",
              "evidence/*.txt", "NEXT_SESSION.md", "CHARTER.md").split()
    rx = re.compile(r"(%s):\d" % T)
    keep = []
    for d in out:
        try:
            with open(os.path.join(REPO, d), encoding="utf-8",
                      errors="replace") as f:
                if rx.search(f.read()):
                    keep.append(d)
        except OSError:
            pass
    return sorted(keep)


# KNOWN pre-existing stale tokens that carry NO quotation spec_cites checks
# (the brief's list, the SR11b re-review's m3, and the tokens SR11c's passes
# carried by content and flagged): the same proof with an ANCHOR — a
# substring of the code the document's claim names — in place of the quote.
# (doc, doc line, F, k = which F token on that line, -S key in the doc, anchor)
KNOWN = [
 ("evidence/qwen2b/rc/t4_wall8_probe.py", 11, "sw/seq_run.py", 0,
  "host programs it before any EMB", "EMBLOG2"),
 # fix round 1 (review I3): RC_GATE.md's three twins of t4_wall8_probe's token
 ("evidence/qwen2b/rc/RC_GATE.md", 80, "sw/seq_run.py", 0,
  "programs it on silicon, so", "EMBLOG2"),
 ("evidence/qwen2b/rc/RC_GATE.md", 667, "sw/seq_run.py", 0,
  "programs it before any EMB record runs, on silicon", "EMBLOG2"),
 ("evidence/qwen2b/rc/RC_GATE.md", 765, "sw/seq_run.py", 0,
  "**already does it** (`sw/seq_run.py:", "EMBLOG2",
  # the row was born (6b5d940) with a BARE continuation `:1228` the tool cannot
  # bind; 77584e9 rewrote it to a full token already stale (1229): C0 and N0
  # are given explicitly, read off `git show 6b5d940:evidence/qwen2b/rc/RC_GATE.md`
  ("6b5d940", 1228)),
 ("docs/superpowers/plans/2026-09-27-seq-rtl-round.md", 211, "ref/seq_cost.py", 0,
  "poll tail is `_tau(n)`", "_tau"),
 ("docs/superpowers/plans/2026-09-27-seq-rtl-round.md", 211, "ref/seq_cost.py", 1,
  "poll tail is `_tau(n)`", "_tau"),
 ("docs/superpowers/plans/2026-09-27-seq-rtl-round.md", 211, "ref/seq_cost.py", 2,
  "poll tail is `_tau(n)`", "nearest"),
 ("evidence/qwen9b/ov/S1P_SHIP.md", 99, "ref/seq_cost.py", 0,
  "the ATTN line beyond position 5", "ATTN"),
 ("evidence/qwen9b/ov/S1P_SHIP.md", 100, "ref/seq_cost.py", 0,
  "for other group sizes, nearest neighbour", "TAU = {"),
 ("evidence/qwen9b/ov/S1P_SHIP.md", 101, "ref/seq_cost.py", 0,
  "the E1 keys the stream never issues", "E1"),
 ("evidence/qwen9b/ov/SV1_S1_VERIFY.md", 109, "ref/seq_model.py", 0,
  "asserts on a MOVX and an", "MOVX writes"),
 ("evidence/qwen9b/ov/SV1_S1_VERIFY.md", 110, "ref/seq_model.py", 0,
  "beside the existing MOVY refusal", "MVGO starts"),
 ("evidence/qwen9b/g3/G3_3_MATVEC.md", 441, "sw/seq_run.py", 0,
  "reads `EXPECTED_SEQ_VERSION = 0xC973C18A`", "EXPECTED_SEQ_VERSION"),
 ("evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md", 231, "rtl/seq_unit.sv", 0,
  "Can FENCE name a channel today?", "OP_FENCE"),
 ("ref/scripts/reorder_e4.py", 35, "rtl/seq_unit.sv", 0,
  "so fence-at-use can only DEFER a fence", "OP_FENCE"),
 ("evidence/qwen9b/g6/RD9_GATE.md", 3043, "ref/seq_model.py", 0,
  "takes a `region=` argument", "region="),
 ("docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md", 437,
  "ref/seq_model.py", 2, "`gate()` at `ref/seq_model.py:", "def gate"),
 ("docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md", 1333,
  "rtl/matvec_engine.sv", 0, "`wire [6:0] ng7 = {1'b0, cfg_ng};`", "ng7"),
]


def prove_known(proven, unproven):
    for d, ln, F, k, key, anchor, *ovr in KNOWN:
        with open(os.path.join(REPO, d), encoding="utf-8") as f:
            cur = f.read().split("\n")[ln - 1]
        tok = re.compile(r"\b%s:(\d+)(?:-(\d+))?(?![0-9])" % re.escape(F))
        toks = list(tok.finditer(cur))
        if k >= len(toks):
            unproven.append((d, ln, F, "-", "no token %d on the line" % k,
                             anchor))
            continue
        t = toks[k]
        c0 = git("log", "--reverse", "--format=%h", "-S", key, "--", d).split()
        if not c0:
            unproven.append((d, ln, F, t.group(0), "doc key's introducing "
                             "commit not found", anchor))
            continue
        c0 = c0[0] if not ovr else ovr[0][0]
        dl = git("show", "%s:%s" % (c0, d)).split("\n")
        sk = NUM.sub("#", cur)
        cand = [x for x in dl if NUM.sub("#", x) == sk] or \
            [x for x in dl if key in x]
        t0 = list(tok.finditer(cand[0])) if len(cand) == 1 else []
        if k >= len(t0) and not ovr:
            unproven.append((d, ln, F, t.group(0), "line/token not uniquely "
                             "found at %s" % c0, anchor))
            continue
        a0 = int(t0[k].group(1)) if not ovr else ovr[0][1]
        b0 = (int(t0[k].group(2)) if t0[k].group(2) else None) if not ovr else None
        fl0 = git("show", "%s:%s" % (c0, F)).split("\n")
        head = (o3.work_text(F) or "").split("\n")
        if not (near(fl0, a0, anchor) or (b0 and near(fl0, b0, anchor))):
            unproven.append((d, ln, F, t.group(0), "BORN STALE: %r not within "
                             "6 lines of :%s at %s"
                             % (anchor, t0[k].group(0).split(":")[-1], c0),
                             anchor))
            continue
        mp = o3.line_map(fl0, head)
        na, nb = mp.get(a0), (mp.get(b0) if b0 else None)
        if na is None or (b0 and nb is None):
            unproven.append((d, ln, F, t.group(0), "cited line rewritten "
                             "since %s (map None)" % c0, anchor))
            continue
        if not (near(head, na, anchor) or (nb and near(head, nb, anchor))):
            unproven.append((d, ln, F, t.group(0), "mapped :%d, anchor not "
                             "near it at HEAD" % na, anchor))
            continue
        new = "%s:%d" % (F, na) + ("-%d" % nb if b0 else "")
        if new == t.group(0):
            unproven.append((d, ln, F, t.group(0), "already the proven "
                             "number", anchor))
            continue
        proven.append((d, ln, t.group(0), new, c0, "anchor " + anchor))


def main():
    proven, unproven = [], []
    prove_known(proven, unproven)
    for d in docs():
        r = subprocess.run([sys.executable, "evidence/qwen_next/spec_cites.py",
                            d], cwd=REPO, capture_output=True, text=True)
        with open(os.path.join(REPO, d), encoding="utf-8") as f:
            wl = f.read().split("\n")
        for line in r.stdout.split("\n"):
            m = FAIL.match(line)
            if not m or m.group(4) not in FILES:
                continue
            ln, q, F = int(m.group(2)), m.group(3), m.group(4)
            q = q[:-1] if q.endswith("…") else q
            cur = wl[ln - 1]
            tok = re.compile(r"\b%s:(\d+)(?:-(\d+))?(?![0-9])" % re.escape(F))
            toks = list(tok.finditer(cur))
            head = (o3.work_text(F) or "").split("\n")
            if not toks:
                unproven.append((d, ln, F, "-", "only bare continuations on "
                                 "the line (not handled)", q))
                continue
            key = q[:60]
            c0 = git("log", "--reverse", "--format=%h", "-S", key, "--",
                     d).split()
            if not c0:
                for t in toks:
                    unproven.append((d, ln, F, t.group(0), "quote's "
                                     "introducing commit not found", q))
                continue
            c0 = c0[0]
            dl = (git("show", "%s:%s" % (c0, d))).split("\n")
            sk = NUM.sub("#", cur)
            cand = [x for x in dl if NUM.sub("#", x) == sk] or \
                [x for x in dl if norm(key) in norm(x)]
            if len(cand) != 1:
                for t in toks:
                    unproven.append((d, ln, F, t.group(0), "line not "
                                     "uniquely found at %s" % c0, q))
                continue
            t0 = list(tok.finditer(cand[0]))
            fl0 = (git("show", "%s:%s" % (c0, F))).split("\n")
            mp = o3.line_map(fl0, head)
            for k, t in enumerate(toks):
                if k >= len(t0):
                    unproven.append((d, ln, F, t.group(0), "no k-th token "
                                     "at %s" % c0, q))
                    continue
                a0 = int(t0[k].group(1))
                b0 = int(t0[k].group(2)) if t0[k].group(2) else None
                if not near(fl0, a0, q) and not (b0 and near(fl0, b0, q)):
                    unproven.append((d, ln, F, t.group(0), "BORN STALE: the "
                                     "quote was not within 6 lines of :%s at "
                                     "%s" % (t0[k].group(0).split(":")[-1],
                                             c0), q))
                    continue
                na = mp.get(a0)
                nb = mp.get(b0) if b0 else None
                if na is None or (b0 and nb is None):
                    unproven.append((d, ln, F, t.group(0), "cited line "
                                     "rewritten since %s (map None)" % c0, q))
                    continue
                if not near(head, na, q) and not (nb and near(head, nb, q)):
                    unproven.append((d, ln, F, t.group(0), "mapped :%d but "
                                     "the quote is not near it at HEAD" % na,
                                     q))
                    continue
                new = "%s:%d" % (F, na) + ("-%d" % nb if b0 else "")
                if new == t.group(0):
                    unproven.append((d, ln, F, t.group(0), "already the "
                                     "proven number (the failing quote is "
                                     "another token's)", q))
                    continue
                proven.append((d, ln, t.group(0), new, c0, q))
    print("--- PROVEN (o3 line map from the quote's introducing commit)")
    for d, ln, old, new, c0, q in proven:
        print("  PROVEN   %s:%d  %s -> %s   (C0 %s)  %r"
              % (d, ln, old, new, c0, q[:60]))
    print("--- NOT PROVABLE (listed for SR9)")
    for d, ln, F, t, why, q in unproven:
        print("  SR9      %s:%d  %s  — %s   %r" % (d, ln, t, why, q[:60]))
    print("SR11C_PROVE_STALE: %d proven, %d not provable"
          % (len(proven), len(unproven)))


if __name__ == "__main__":
    main()
