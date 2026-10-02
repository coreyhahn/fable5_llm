#!/usr/bin/env python3
"""o3_cite_drift.py — did this task's edits move a line somebody cites?

THE CLASS THIS EXISTS FOR.  `evidence/qwen_next/spec_cites.py` only
cross-checks a quotation when it shares a markdown LINE with its cite, so a
citation that drifts but stays IN RANGE passes silently — spec §8 G2's
stated blind spot, demonstrated on this campaign's own edits three times
(G2a's `c366b3a`, G2c's off-by-one, G2b's stale batch).  O3 edits twelve
`sw/` files that the spec, the plan and five gate documents cite by line,
so it has to answer the question mechanically rather than by re-reading.

METHOD, and it does not depend on the checker.

  * the LINE MAP.  For each edited file, `difflib.SequenceMatcher` over
    `git show <base>:<file>` and the working tree gives an exact
    old-line -> new-line map (None where the line was rewritten or
    deleted).  Content matching was tried first and is not good enough: a
    cited `# ====` separator matches fourteen lines and a cited
    `errors += 1` matches two, so it reported UNRESOLVED on lines that had
    simply moved.
  * the CITE SWEEP is taken from `<doc-base>`, NOT from the working tree.
    That is what makes this reproducible after the fix has been applied:
    the question "where did the line this document USED to name go?" has
    one answer forever, and asking the fixed document would just re-derive
    a fresh, wrong drift for every citation that was already corrected.

FORMS THIS TOOL DOES NOT PARSE, and the damage each one does (G3.4 fix
round 3, m4).  `CITE` matches `path:NNN` and `path:NNN-MMM`, and `CONT`
matches a BACKTICKED bare continuation `` `:NNN` `` on a line that names
exactly one file.  Anything else is invisible, and invisible is not
harmless: a citation LIST joined by slashes --
`ref/seq_chat.py:935/936/1213/1214/1215` -- has its FIRST element rewritten
and the rest left behind, which turns one honest stale token into a token
that is half repaired and reads as if it were checked.  THOSE FIVE NUMBERS
ARE AN EXAMPLE, NOT A CITATION: do not "repair" them.  Fix round 2's own
pass rewrote the 935 to 945 and turned this illustration into an instance of
itself (Task 15 round-3 review, m11); it is restored here, and a pass over
this file must exclude its own docstring -- `--exclude
evidence/qwen9b/o3/o3_cite_drift.py`.  Two of those were
found in this campaign (`NEXT_SESSION.md` and
`evidence/qwen_next/defect_a/damage_test.py`, both naming pre-`2a50cac`
coordinates on purpose); both were rewritten OUT of citation form rather
than maintained, because the code they name no longer exists.  If you write
a list, write each element as a full `path:NNN` token, or write it as prose
the tool cannot half-fix.

Modes
  --check    (default)  report the drift.  Non-zero if anything drifted.
                        This is the RED half and it is meaningful on the
                        UNFIXED working tree.
  --plan                DRY RUN.  What a `--fix` at this base WOULD rewrite,
                        split into REPAIR (the document still names the OLD
                        line) and COLLATERAL (it already names the right one
                        and the pass would move it AGAIN).  Ask it before
                        every `--fix` at a base some pass has already run.
  --fix                 renumber the drifted citations in the working
                        documents, in ONE pass, ranges included.  It REFUSES
                        (rc 2) on a tree where the pass has already landed —
                        wholly (`--verify` clean) or PARTLY (any COLLATERAL,
                        which is the MIXED tree
                        `evidence/qwen9b/g6/RD9_GATE.md` section 18.2 is
                        about).
  --allow-collateral    the escape from the COLLATERAL refusal, per DOCUMENT
                        (`--allow-collateral <citing-doc>`) or per CITATION
                        (`--allow-collateral <path>:<line>`).  For the case
                        the refusal is otherwise too coarse for: a plan that
                        is mostly REPAIR with one collateral token the
                        operator has CHECKED BY HAND — S5's own pass
                        (`evidence/qwen9b/s5/170_cite_drift_plan.log`, REPAIR
                        11 / COLLATERAL 1) is the recorded instance, and
                        `--exclude`, the other remedy, would have forfeited
                        those eleven repairs.  Every cleared token is printed
                        BY NAME and counted, in `--plan` and in `--fix` both,
                        so the operator's decision lands in the log; a value
                        that names no collateral token clears nothing and
                        says so.  Repeatable.  An optional `=<reason>` after
                        the value is printed beside the token it clears (the
                        WHY, not just the WHAT), and a run that is about to
                        REFUSE says WOULD CLEAR rather than ALLOWED, because
                        it applies none of them.
  --verify              the GREEN half: for every drifted citation, require
                        the working document to name the NEW line, to no
                        longer name the old one, and require the content at
                        the new line to equal the base content at the old
                        one.  Non-zero otherwise.
  --negative-control    proves each half can fail: `--check` compares one
                        line off and must report drift; `--verify` demands
                        a deliberately wrong target and must refuse.

CHANGES, DATED — because a commit message that under-declares an edit is
how a review round starts.
  2026-09-10  `ca6adc7` (the fix-round-1 drift commit).  Its message declares
              ONE docstring repair, a bare RD9_GATE.md mention written out
              to its full path.  It also added four lines to `--plan`'s help
              naming `--allow-collateral` — half of m6, landing in the
              drift commit, not in `824a9f6` with the rest.  Help text
              only, no behaviour; declared here because the message did not
              (re-review of fix round 1, m3).
  2026-09-10  fix round 2, the re-review's m5/m6/m7: `--allow-collateral`
              takes an optional `=<reason>`, printed with the cleared token;
              a run that is about to refuse prints WOULD CLEAR instead of
              ALLOWED; and the flag's help says what to pass for a bare
              continuation, which the refusal prints as `` `:NNN` `` and
              nobody can type.  Fixture cases F and G are the RED/GREEN.

Usage:
  python3 o3_cite_drift.py [--base dc8f492] [--doc-base dc8f492]
                           [--check | --plan | --fix | --verify]
                           [--allow-collateral DOC|path:NNN[=REASON]] ...
                           [--negative-control]
"""
import argparse
import difflib
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

# every sw/ file Task 6 edits.  These are REPO-RELATIVE PATHS: T6 only ever
# edited sw/, so the first cut carried bare basenames and prefixed "sw/" at
# every use.  G3.1 (Task 7) edits rtl/, ref/, tb/, sw/, synth/ and docs/, so
# the list is full paths now and `--edited` overrides it.  The T6 default is
# byte-identical in effect, which is what keeps `--base d2d774b` reproducible
# for the documents T6 fixed.
EDITED = ["sw/chat_seq.py", "sw/serve.py", "sw/cycle_census.py",
          "sw/seq_run.py", "sw/infer.py", "sw/tok_meter.py",
          "sw/mover_bench.py", "sw/layer_test.py", "sw/matvec_test.py",
          "sw/ddr_test.py", "sw/program_fpga.sh", "sw/stage1_hw_bringup.sh"]


# A SHA PIN IS NOT A CITATION, and this tool used to rewrite them (#158,
# triage (b)1).  A citation written `<sha>:path:line` names where a line
# was IN THAT COMMIT: it is a statement about a tree that cannot move, so
# it is correct forever and a base->work renumber turns it into a lie.
# The campaign carries ~35 of them, and `evidence/qwen9b/s5/S5_STRUCT.md`
# names this exact gap ("the drift tool treats it as live"); the damage is
# already on record at `evidence/qwen9b/s3/S3_CHAIN.md` — "an already-
# PINNED citation the map shifted anyway".  Every pattern below carries an
# optional `sha` group and every call site skips a match that has one, so
# a pin is invisible to the sweep, to the rewriter and to the verifier
# alike — which is the only combination that is self-consistent (a pin
# that were swept but not rewritten would be reported as eternal drift).
#
# The pin is only recognised at a WORD BOUNDARY, so `0x00abcdef:sw/x.py:5`
# is still a live cite and only a real leading token counts.
#
# LIMIT, stated because it cannot be closed by a regex: a BARE
# CONTINUATION has no pin syntax of its own — `` `:NNN` `` after a pinned
# mention is pinned by CONTEXT.  It is protected because `named` skips
# pinned mentions, so a line whose ONLY file mention is a pin binds no
# continuation.  A line carrying BOTH a pin and a live mention of a
# DIFFERENT file still binds its continuations to the live one; write the
# pin's continuations as full `<sha>:path:line` tokens if that line ever
# occurs.
SHA = r"(?:(?P<sha>\b[0-9a-f]{7,40}):)?"


def _set_edited(paths):
    """Re-derive the three path regexes after `--edited` replaces the list."""
    global EDITED, CITE, NAMED
    EDITED = list(paths)
    alt = "|".join(re.escape(f) for f in EDITED)
    CITE = re.compile(r"%s\b(?P<fn>%s):(?P<a>\d+)(?:-(?P<b>\d+))?"
                      % (SHA, alt))
    NAMED = re.compile(r"`%s(?P<fn>%s)(?::\d+(?:-\d+)?)?`" % (SHA, alt))


CITE = re.compile(r"%s\b(?P<fn>%s):(?P<a>\d+)(?:-(?P<b>\d+))?"
                  % (SHA, "|".join(re.escape(f) for f in EDITED)))
ROOTS = ["docs", "evidence", "CHARTER.md", "NEXT_SESSION.md"]
# A BARE CONTINUATION — `` `:NNN` `` on a line that already names a file —
# is a citation too, and it drifts exactly like a full one.  It is also
# the weakest kind: `evidence/qwen_next/spec_cites.py` binds it to the
# file named on its own line and can flag it as ORPHAN/AMBIG, but it
# cannot see that it moved.  `docs/QWEN35_NEXT_FEASIBILITY.md` carries a
# row reading ``**`sw/infer.py:781-785`** | `1024` x4 (`:781`, `:782`,
# `:783`, `:785`)`` — one full token and four continuations, all naming
# the same four lines.  Renumbering only the full token leaves the row
# internally inconsistent, which is worse than leaving it alone.
CONT = re.compile(r"`%s:(?P<a>\d+)(?:-(?P<b>\d+))?`" % SHA)
# A line can NAME the file without citing a line in it -- ``| the real host
# `sw/seq_run.py` | ... (`:1228`) |`` -- and then a first cut of this gate
# saw no CITE on the line, so `named` was empty and the continuation bound
# to nothing.  That is how `plan:809` ended up with `:1504` meaning the OLD
# line in one half of a sentence and `sw/chat_seq.py:1597` meaning the NEW
# one in the other half.  `named` is computed from bare mentions too.
NAMED = re.compile(r"`%s(?P<fn>%s)(?::\d+(?:-\d+)?)?`"
                   % (SHA, "|".join(re.escape(f) for f in EDITED)))

# ---------------------------------------------------------------------
# THE SECOND CLASS, and this gate could not see it either (review F6).
# A task that edits a DOCUMENT moves the lines that OTHER documents cite in
# it.  O3 edited `docs/USAGE.md`, `docs/ARCHITECTURE.md` and
# `docs/HISTORY.md`; the `sw/`-only sweep above is blind to that, and it
# left eight citations pointing at the wrong paragraph -- including
# `ref/scripts/regen_gate.sh:5`, which is a GATE SCRIPT telling its reader
# where the sha lock is documented.
#
# `--doc-cites` answers it the same way and with the same machinery: the
# targets are DERIVED (every .md/.txt whose LINE COUNT moved between
# --base and the worktree), not listed, so the next task that edits a
# document is covered without editing this file.  Check-only on purpose:
# a document citation carries no `sw/`-style file token to key a rewrite
# on, and eight hand-fixes verified against base content are safer than a
# rewriter nobody has exercised.
DOC_CITE = re.compile(
    r"([A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:md|txt)):(\d+(?:[-,]\d+)*)")
DOC_SWEPT = (".md", ".txt", ".py", ".sh", ".sv", ".v", ".tcl")


def doc_targets(base):
    """{path: (base lines, work lines)} for every .md/.txt whose length moved.

    DERIVED, not listed: a same-length edit cannot move a citation, so the
    targets are exactly the documents this task renumbered, and the next
    task that edits a document is covered without touching this file.
    """
    out = {}
    for p in git_ls(base):
        if not p.endswith((".md", ".txt")):
            continue
        b, w = git_show(base, p), work_text(p)
        if b is None or w is None:
            continue
        bl, wl = b.split("\n"), w.split("\n")
        if len(bl) != len(wl):
            out[p] = (bl, wl)
    return out


def _doc_nums(tok):
    """`386-390` / `128,150` / `189` -> the line numbers it names."""
    return [int(x) for x in re.split(r"[-,]", tok)]


def doc_drift(base):
    """[(citing file, line, target, cited, correct)] — SWEPT FROM `base`.

    Same discipline as the sw/ half and for the same reason: sweeping the
    WORKING tree would make the GREEN half vacuous, because a citation this
    round rewrote would no longer be found and so would no longer be
    checked.  `base` is fixed, so "where did the line this file used to
    name go?" has one answer forever.
    """
    tgts = doc_targets(base)
    if not tgts:
        return [], 0, {}
    maps = {p: line_map(bl, wl) for p, (bl, wl) in tgts.items()}
    by_base = {}
    for p in tgts:
        by_base.setdefault(os.path.basename(p), []).append(p)
    drift, nc = [], 0
    for f in sorted(git_ls(base)):
        if not f.endswith(DOC_SWEPT):
            continue
        text = git_show(base, f)
        if text is None:
            continue
        for i, line in enumerate(text.split("\n"), 1):
            for mo in DOC_CITE.finditer(line):
                cand = [p for p in by_base.get(os.path.basename(mo.group(1)),
                                               [])
                        if p.endswith(mo.group(1))]
                if len(cand) != 1:
                    continue                # unknown or ambiguous: not ours
                tgt = cand[0]
                if tgt == f:
                    continue                # a document citing itself
                for ln in _doc_nums(mo.group(2)):
                    nc += 1
                    new = maps[tgt].get(ln)
                    if new != ln:
                        drift.append((f, i, tgt, ln, new))
    return drift, nc, tgts


def doc_cited_nums(f, tgt):
    """Every line number the WORKING file `f` names in `tgt`."""
    t = work_text(f)
    if t is None:
        return set()
    out = set()
    for line in t.split("\n"):
        for mo in DOC_CITE.finditer(line):
            if not tgt.endswith(mo.group(1)):
                continue
            out.update(_doc_nums(mo.group(2)))
    return out


def doc_verify(base, drift, wrong=False):
    """The GREEN half: each drifted doc citation now names the RIGHT line."""
    bad = []
    targets = {}
    for f, _i, tgt, _ln, new in drift:
        if new is not None:
            targets.setdefault((f, tgt), set()).add(new + (7 if wrong else 0))
    for f, _i, tgt, ln, new in drift:
        if new is None:
            bad.append("%s:%d was rewritten away; %s must be re-read by hand"
                       % (tgt, ln, f))
            continue
        tv = new + (7 if wrong else 0)
        b = (git_show(base, tgt) or "").split("\n")
        w = (work_text(tgt) or "").split("\n")
        if not (1 <= tv <= len(w)) or b[ln - 1] != w[tv - 1]:
            bad.append("%s:%d -> :%d  content does not match the base line"
                       % (tgt, ln, tv))
            continue
        nums = doc_cited_nums(f, tgt)
        if tv not in nums:
            bad.append("%s does not cite %s:%d" % (f, tgt, tv))
        if ln in nums and ln != tv and ln not in targets.get((f, tgt), set()):
            bad.append("%s still cites the OLD %s:%d" % (f, tgt, ln))
    return bad


def git_show(ref, path):
    r = subprocess.run(["git", "show", "%s:%s" % (ref, path)],
                       cwd=REPO, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def git_ls(ref):
    r = subprocess.run(["git", "ls-tree", "-r", "--name-only", ref],
                       cwd=REPO, capture_output=True, text=True)
    return r.stdout.splitlines() if r.returncode == 0 else []


def work_text(path):
    p = os.path.join(REPO, path)
    if not os.path.exists(p):
        return None
    with open(p, errors="replace") as f:
        return f.read()


def line_map(old, new):
    """{old 1-based line -> new 1-based line or None}, by difflib alignment."""
    m = {}
    sm = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                m[i1 + k + 1] = j1 + k + 1
        else:
            for k in range(i1, i2):
                m[k + 1] = None
    return m


def sweep(doc_base):
    """({(file, line): {doc}}, docs, {(file, a, b): {doc}}) at doc_base.

    The third value is the RANGE index (finding O3): a range is one TOKEN,
    and a renumber that resolves one endpoint and not the other produces a
    citation that is half pre-G3 and half post-G3.  Recording the pairing is
    what lets `classify` refuse to split it.
    """
    out = {}
    rng = {}
    # CODE COMMENTS CITE LINES TOO, and they are the citations nobody
    # re-reads: `rtl/`, `sw/`, `ref/`, `tb/` and the evidence scripts all
    # carry `sw/<file>:NNN` in comments, and a first cut of this gate swept
    # only .md/.txt and missed five of them.
    docs = [p for p in git_ls(doc_base)
            if (p.endswith((".md", ".txt"))
                and (p.split("/")[0] in ("docs", "evidence")
                     or p in ("CHARTER.md", "NEXT_SESSION.md")))
            or (p.endswith((".py", ".sh", ".sv", ".v", ".tcl"))
                and p.split("/")[0] in ("rtl", "sw", "ref", "tb", "evidence",
                                        "synth"))]
    for d in sorted(docs):
        text = git_show(doc_base, d)
        if text is None:
            continue
        for line in text.split("\n"):
            named = {m.group("fn") for m in NAMED.finditer(line)
                     if not m.group("sha")}
            for m in CITE.finditer(line):
                if m.group("sha"):          # a pin, not a citation (#158)
                    continue
                fn, a, b = m.group("fn"), int(m.group("a")), m.group("b")
                for ln in ({a, int(b)} if b else {a}):
                    out.setdefault((fn, ln), set()).add(d)
                if b:
                    rng.setdefault((fn, a, int(b)), set()).add(d)
            # a continuation binds to the ONE file its line names; on a line
            # naming two, it is ambiguous and neither this gate nor
            # spec_cites.py may guess (that is spec_cites' AMBIG class)
            if len(named) == 1:
                fn = next(iter(named))
                for m in CONT.finditer(line):
                    if m.group("sha"):      # a pin, not a citation (#158)
                        continue
                    a, b = int(m.group("a")), m.group("b")
                    for ln in ({a, int(b)} if b else {a}):
                        out.setdefault((fn, ln), set()).add(d)
                    if b:
                        rng.setdefault((fn, a, int(b)), set()).add(d)
    return out, docs, rng


def classify(base, doc_base, off=0):
    """(ok, drift, unresolved, missing, ncites, half)."""
    cites, _docs, ranges = sweep(doc_base)
    per_file = {}
    for (fn, _ln) in cites:
        if fn in per_file:
            continue
        b, w = git_show(base, fn), work_text(fn)
        per_file[fn] = (b.splitlines() if b is not None else None,
                        w.splitlines() if w is not None else None)
    maps = {fn: (line_map(b, w) if (b is not None and w is not None) else None)
            for fn, (b, w) in per_file.items()}

    ok, drift, unresolved, missing = [], [], [], []
    for (fn, ln) in sorted(cites):
        b, w = per_file[fn]
        who = sorted(cites[(fn, ln)])
        if b is None or w is None:
            missing.append((fn, ln, who, "file absent in base or worktree"))
            continue
        src = ln + off
        if src < 1 or src > len(b):
            missing.append((fn, ln, who,
                            "line %d not in %s:%s" % (src, base, fn)))
            continue
        new = maps[fn].get(src)
        txt = b[src - 1].strip()[:78]
        if new == ln:
            ok.append((fn, ln, who))
        elif new is None:
            unresolved.append((fn, ln, who, txt,
                               "the cited line was rewritten or deleted"))
        else:
            drift.append((fn, ln, new, who, txt))

    # HALF-MAPPED RANGES (finding O3).  One token, two endpoints: if either
    # is unresolved the whole token is left alone, and it is REPORTED here
    # rather than silently half-rewritten.
    half = []
    for (fn, a, b) in sorted(ranges):
        if fn not in maps or maps[fn] is None:
            continue
        bl = per_file[fn][0]
        if bl is None:
            continue
        sa, sb = a + off, b + off
        # AN ENDPOINT PAST THE END OF THE BASE FILE IS UNRESOLVED, not a
        # reason to skip the range (round-3 review).  The first cut
        # `continue`d here, so a range with one in-file endpoint and one
        # past-the-end endpoint fell out of the half-mapped set entirely and
        # only its MISSING row flagged it — while `_map_range`'s `x in m`
        # test let the out-of-range end keep its own number and the other
        # end move.  That is the O3 defect wearing a different hat.
        ina = 1 <= sa <= len(bl)
        inb = 1 <= sb <= len(bl)
        if not ina and not inb:
            continue                      # wholly outside: MISSING owns it
        na = maps[fn].get(sa) if ina else None
        nb = maps[fn].get(sb) if inb else None
        if (na is None) != (nb is None):
            half.append((fn, a, b, na, nb, sorted(ranges[(fn, a, b)]),
                         bl[sa - 1].strip()[:60] if ina else "<past EOF>",
                         bl[sb - 1].strip()[:60] if inb else "<past EOF>"))
    return ok, drift, unresolved, missing, len(cites), half


def _map_range(m, a, b=None, hi=None):
    """Map one citation token.  ALL OR NOTHING for a range.

    Returns `(new_a, new_b)`, or `(None, None)` when the token must be left
    alone: a single line whose map entry is None, or a RANGE either of whose
    endpoints is None.  `m.get(x)` returning None means that line was
    REWRITTEN OR DELETED between the base and the worktree — a number no
    renumber can invent, and half a renumbered range is worse than none
    (finding O3).  A line absent from the map entirely (never cited into the
    diff) keeps its own number, which is the unchanged-file case.
    """
    def one(x):
        # `x in m` and `m[x] is None` -> DELETED.  `x not in m` -> the line
        # was never in the diff, so it keeps its own number... EXCEPT past
        # the end of the base file, where "never in the diff" and "does not
        # exist" are the same absence and the map cannot tell them apart.
        # `_map_range` is given `hi` (the base file's length) so it can:
        # beyond it, the endpoint is UNRESOLVED and the whole token is left
        # alone (round-3 review).
        if hi is not None and x > hi:
            return None
        return m[x] if x in m else x
    na = one(a)
    if na is None:
        return None, None
    if b is None:
        return na, None
    nb = one(b)
    if nb is None:
        return None, None
    return na, nb


def rewrite_doc(text, maps, hi=None, report=None):
    """Renumber every citation in one document, LINE BY LINE, in ONE pass.

    THREE DEFECTS THIS FUNCTION HAD, all caught by re-running the gate after
    a `--fix`, all the same mistake — treating a renumber as a sequence of
    independent replacements:

      (a) SEQUENTIAL COLLISION.  `tok_meter.py:487 -> :500` was applied and
          then `:500 -> :513` was applied to the same document, moving the
          token just written.  Every substitution now happens inside one
          `re.sub` callback pass, so no rewrite can see another's output.
      (b) RANGES HALF-FIXED.  `sw/chat_seq.py:1185-1191` matched the `:1185`
          pattern and became `:1074-1100` — a range whose start had moved
          and whose end had not.  Both endpoints are mapped now.

          **AND THAT FIX WAS INCOMPLETE, which G3.1 found the expensive
          way (Task 7 re-review, finding O3).**  `na = m.get(a) or a` maps
          an endpoint when the map HAS it and silently KEEPS THE BASE
          NUMBER when the map returns None — i.e. when that line was
          REWRITTEN OR DELETED.  So a range with one live endpoint and one
          dead one was still half-rewritten: one number post-fix, the other
          pre-fix, in one token.  `spec_cites.py` cannot see it (RANGE
          passes on any in-file number), so it survived a FAIL 0.  Nine of
          them landed across the spec, the plan and two gate documents.

          **A RANGE IS NOW ALL OR NOTHING.**  `_map_range` returns None if
          EITHER endpoint is unresolved, `sub`/`csub` then leave the token
          BYTE-IDENTICAL, and `classify` reports the range as
          `HALF-MAPPED` naming both endpoints so a human repairs it against
          `git show <base>:<file>`.  `--range-control` is the negative
          control: a synthetic range whose one endpoint was deleted must
          come back unresolved AND untouched, and the same range with both
          endpoints live must still be rewritten, or the control proves
          nothing.
      (c) BARE CONTINUATIONS LEFT STALE.  A row naming
          `sw/infer.py:781-785` and then `` `:781` ``…`` `:785` `` had its
          full token renumbered and its four continuations left behind,
          which is a document that contradicts itself.  Continuations are
          rewritten with the map of the one file their line names.

    The blast radius of (a) and (b) was eleven documents including three
    other gates' committed evidence, which is why each repair was a
    `git checkout` and a redo rather than a patch on top.
    """
    out = []
    for line in text.split("\n"):
        named = {m.group("fn") for m in NAMED.finditer(line)
                 if not m.group("sha")}

        def sub(mo):
            if mo.group("sha"):             # a pin, never renumbered (#158)
                return mo.group(0)
            fn, a = mo.group("fn"), int(mo.group("a"))
            m = maps.get(fn) or {}
            b = int(mo.group("b")) if mo.group("b") else None
            na, nb = _map_range(m, a, b, (hi or {}).get(fn))
            if na is None:
                return mo.group(0)          # untouched: see (b) above
            new = ("%s:%d-%d" % (fn, na, nb)) if b is not None \
                else ("%s:%d" % (fn, na))
            if report is not None and new != mo.group(0):
                report.append((fn, a, b, na, nb, mo.group(0), new))
            return new

        line = CITE.sub(sub, line)
        if len(named) == 1:
            m = maps.get(next(iter(named))) or {}

            _fn = next(iter(named))

            def csub(mo, _m=m, _fn=_fn):
                if mo.group("sha"):         # a pin, never renumbered (#158)
                    return mo.group(0)
                a = int(mo.group("a"))
                b = int(mo.group("b")) if mo.group("b") else None
                na, nb = _map_range(_m, a, b, (hi or {}).get(_fn))
                if na is None:
                    return mo.group(0)      # untouched
                new = ("`:%d-%d`" % (na, nb)) if b is not None \
                    else ("`:%d`" % na)
                if report is not None and new != mo.group(0):
                    report.append((_fn, a, b, na, nb, mo.group(0), new))
                return new

            line = CONT.sub(csub, line)
        out.append(line)
    return "\n".join(out)


def fix_plan(base, drift, exclude=()):
    """What a --fix pass WOULD write: {document: new text}, + the skipped.

    `apply_fix` writes exactly this mapping and touches nothing else, and
    `exclude_control` asks THIS function both of its questions -- so the
    control exercises the real selection path instead of a copy of it that
    can drift away from it.  (The first cut of the control re-read the
    victim off disk and compared it with itself, which is true by
    construction: a control that cannot fail certifies nothing.)

    `exclude` is the ROOT-CAUSE fix for the defect that recurred at T9 and
    T10 (G3.4 review round 1, finding O3).  A gate document is WRITTEN
    DURING the task, in the FINAL tree's coordinates, and is then swept by
    --fix like any other citer -- so its already-correct pointers are
    mapped base->work a SECOND time and come out double-shifted.  Task 9
    lost ~20 pointers to this and Task 10 lost twelve.  The standing
    instruction was "keep your gate doc out of the pass", which is a rule a
    human has to remember; this makes it something the TOOL does.

    Paths are repo-relative and compared exactly, so a typo excludes
    nothing rather than silently excluding everything -- which
    `--exclude-control` proves as its third half.

    NOTE: only documents named by the drift list are candidates.  An
    earlier cut also swept every document containing ANY citation, which
    made --fix rewrite files that had nothing stale in them.
    """
    exclude = set(exclude)
    maps, hi = {}, {}
    for fn in EDITED:
        b, w = git_show(base, fn), work_text(fn)
        if b is not None and w is not None:
            maps[fn] = line_map(b.splitlines(), w.splitlines())
            hi[fn] = len(b.splitlines())
    docs = set()
    for _fn, _old, _new, who, _txt in drift:
        docs.update(who)
    skipped = sorted(docs & exclude)
    plan = {}
    for doc in sorted(docs - exclude):
        text = work_text(doc)
        if text is None:
            continue
        new = rewrite_doc(text, maps, hi)
        if new != text:
            plan[doc] = new
    return plan, skipped


def apply_fix(base, doc_base, drift, exclude=()):
    """Rewrite every document `fix_plan` names, and NOTHING else."""
    plan, skipped = fix_plan(base, drift, exclude)
    for doc in skipped:
        print("  EXCLUDED   %s (written in post-fix coordinates)" % doc)
    for doc in sorted(plan):
        with open(os.path.join(REPO, doc), "w") as f:
            f.write(plan[doc])
        print("  fixed      %s" % doc)
    return len(plan)


_DOC_CITES = {}


def doc_cite_lines(doc):
    """{sw file: {every line number this document names, range ends too}}."""
    if doc not in _DOC_CITES:
        t = work_text(doc) or ""
        d = {}
        for line in t.split("\n"):
            named = {m.group("fn") for m in NAMED.finditer(line)
                     if not m.group("sha")}
            for m in CITE.finditer(line):
                if m.group("sha"):          # a pin, not a citation (#158)
                    continue
                s = d.setdefault(m.group("fn"), set())
                s.add(int(m.group("a")))
                if m.group("b"):
                    s.add(int(m.group("b")))
            if len(named) == 1:            # bare continuations count too
                s = d.setdefault(next(iter(named)), set())
                for m in CONT.finditer(line):
                    if m.group("sha"):      # a pin, not a citation (#158)
                        continue
                    s.add(int(m.group("a")))
                    if m.group("b"):
                        s.add(int(m.group("b")))
        _DOC_CITES[doc] = d
    return _DOC_CITES[doc]


def verify(base, drift, wrong=False, exclude=()):
    """Every drifted citation now names the NEW line, and it is the right one.

    `exclude` mirrors apply_fix's: a document deliberately kept out of the
    --fix pass must not then be reported for not having been fixed.  A
    --fix exclusion that --verify still flags is half a feature, and half a
    feature is what makes an operator override the gate.
    """
    exclude = set(exclude)
    bad = []
    # Where a citation was RELOCATED ONTO another citation's old number —
    # `sw/infer.py:678-679` became `:679-680`, so 679 is now a legitimate
    # target — "still cites the OLD 679" is a false alarm.  Collect every
    # target per (doc, file) first and exempt those.
    targets = {}
    for fn, old, new, who, _t in drift:
        for doc in who:
            targets.setdefault((doc, fn), set()).add(new + (7 if wrong else 0))
    per_file = {}
    for fn, old, new, who, txt in drift:
        if fn not in per_file:
            b, w = git_show(base, fn), work_text(fn)
            per_file[fn] = (b.splitlines() if b else [],
                            w.splitlines() if w else [])
    for fn, old, new, who, txt in drift:
        tgt = new + (7 if wrong else 0)     # negative control: a wrong target
        b, w = per_file[fn]
        if not (1 <= tgt <= len(w)) or b[old - 1] != w[tgt - 1]:
            bad.append("%s:%d -> :%d  content does not match the base line"
                       % (fn, old, tgt))
            continue
        for doc in who:
            if doc in exclude:
                continue
            # Membership is tested over PARSED cite tokens, not by a regex
            # per number: `sw/infer.py:781-785` carries 785 as a RANGE END,
            # which `\bsw/infer\.py:785` cannot see.  That mistake reported
            # 21 false problems on a correctly fixed tree.
            lines = doc_cite_lines(doc).get(fn, set())
            if tgt not in lines:
                bad.append("%s does not cite %s:%d" % (doc, fn, tgt))
            if (old in lines and old != tgt
                    and old not in targets.get((doc, fn), set())):
                bad.append("%s still cites the OLD %s:%d" % (doc, fn, old))
    return bad


def _cmd_doc_cites(base, verify_mode=False, negative=False):
    """`--doc-cites`: the drift class the sw/-only sweep cannot see."""
    drift, n, tgts = doc_drift(base)
    print("o3 citation-drift gate  [doc-cites%s]"
          % (" verify" if verify_mode else ""))
    print("  doc base   %s" % base)
    print("  targets    %d document(s) whose line count moved since %s"
          % (len(tgts), base))
    for p, (bl, wl) in sorted(tgts.items()):
        print("               %-58s %d -> %d lines" % (p, len(bl), len(wl)))
    print("  citations  %d line number(s) cited into them at %s" % (n, base))
    print("  unmoved    %d" % (n - len(drift)))
    if negative:
        print("  MODE       NEGATIVE CONTROL")
    if not verify_mode:
        for f, i, tgt, ln, new in drift:
            print("  DRIFTED    %s:%d cites %s:%d -> should be %s"
                  % (f, i, tgt, ln, new))
        if negative:
            # the control for --check is the sweep itself: on a tree where
            # nothing moved there is nothing to report, so it is run with
            # every target shifted -- here, by asserting the sweep FOUND
            # the drift it is supposed to find.
            print("O3_DOC_CITES CHECK NEGATIVE CONTROL: %s (%d reported)"
                  % ("CAUGHT" if drift else "*** MISSED ***", len(drift)))
            return 0 if drift else 1
        print("O3_DOC_CITES CHECK %s (%d drifted of %d)"
              % ("PASS" if not drift else "FAIL", len(drift), n))
        return 0 if not drift else 1
    bad = doc_verify(base, drift, wrong=negative)
    for b in bad[:40]:
        print("  ! " + b)
    if negative:
        print("O3_DOC_CITES VERIFY NEGATIVE CONTROL: %s (%d complaints)"
              % ("CAUGHT" if bad else "*** MISSED ***", len(bad)))
        return 0 if bad else 1
    print("  relocated  %d citation(s) checked against the base content and "
          "the citing files" % len(drift))
    print("O3_DOC_CITES VERIFY %s (%d problem(s))"
          % ("PASS" if not bad else "FAIL", len(bad)))
    return 0 if not bad else 1


def range_control():
    """NEGATIVE CONTROL for the all-or-nothing range rule (finding O3).

    A checker that cannot fail proves nothing, and neither does a rewriter
    that cannot refuse.  Four synthetic cases against `rewrite_doc`, on a
    map built by hand so the outcome is not an accident of any real diff:

      1  both endpoints live      -> the range MUST be rewritten
      2  the END was deleted      -> the whole token MUST be untouched
      3  the START was deleted    -> the whole token MUST be untouched
      4  a bare continuation with a deleted endpoint -> untouched

    Case 1 is what makes 2-4 meaningful: if the rewriter refused
    everything the other three would pass vacuously.  Case 3 is the one
    that shipped: `na = m.get(a) or a` kept a DELETED start at its base
    number while mapping the end, producing `102-121` where 102 was pre-G3
    and 121 post-G3, in one token, inside a FAIL-0 document.
    """
    fn = EDITED[0]
    m_live = {10: 20, 30: 40}
    m_dead_end = {10: 20, 30: None}
    m_dead_start = {10: None, 30: 40}
    # HI is the BASE file's length.  An endpoint past it is absent from the
    # map for a different reason than "unchanged", and the first cut of this
    # control could not tell the two apart (round-3 review).
    HI = {fn: 50}
    cases = [
        ("both endpoints live",     m_live,       HI, "`%s:10-30`" % fn,
         "`%s:20-40`" % fn,  True),
        ("the END was deleted",     m_dead_end,   HI, "`%s:10-30`" % fn,
         "`%s:10-30`" % fn,  False),
        ("the START was deleted",   m_dead_start, HI, "`%s:10-30`" % fn,
         "`%s:10-30`" % fn,  False),
        ("a bare continuation, END deleted", m_dead_end, HI,
         "see `%s` at `:10-30`" % fn, "see `%s` at `:10-30`" % fn, False),
        ("the END is PAST the base file's end", m_live, HI,
         "`%s:10-99`" % fn, "`%s:10-99`" % fn, False),
        ("the START is PAST the base file's end", m_live, HI,
         "`%s:99-30`" % fn, "`%s:99-30`" % fn, False),
        ("a SINGLE line past the base file's end", m_live, HI,
         "`%s:99`" % fn, "`%s:99`" % fn, False),
    ]
    bad = []
    print("o3 citation-drift gate  [range negative control]")
    for name, mp, hi, src, want, should_change in cases:
        got = rewrite_doc(src, {fn: mp}, hi)
        ok = (got == want)
        changed = (got != src)
        verdict = "ok" if ok else "*** WRONG ***"
        if not ok or changed != should_change:
            bad.append(name)
            verdict = "*** WRONG ***"
        print("  %-36s %-28r -> %-28r %s"
              % (name, src, got, verdict))
    print("O3_RANGE_CONTROL: %s (%d problem(s))"
          % ("PASS — a half-mapped range is never rewritten" if not bad
             else "FAIL", len(bad)))
    return 0 if not bad else 1


def plan_split(base, drift, exclude=()):
    """([(doc, repairs, collateral)], [excluded docs]) — the plan, unprinted.

    Lifted out of `plan_report` so that `--fix` can ASK THE SAME QUESTION
    the dry run answers instead of a paraphrase of it (triage (b)1, the
    `--fix` non-idempotence recorded in `evidence/qwen9b/g6/RD9_GATE.md`
    section 18.2).  `--fix`'s only guard used to be "is `--verify` clean?",
    which catches a tree where the pass landed WHOLE and misses the one
    that actually cost that round an hour: a MIXED tree, some documents
    repaired by hand in post-fix coordinates and one still stale.  There
    `--verify` is dirty because of the stale one, the guard stands aside,
    and every already-correct citation moves a second time.  COLLATERAL is
    exactly that set, so `--fix` refuses when it is non-empty.
    """
    exclude = set(exclude)
    maps, hi = {}, {}
    for fn in EDITED:
        b, w = git_show(base, fn), work_text(fn)
        if b is not None and w is not None:
            maps[fn] = line_map(b.splitlines(), w.splitlines())
            hi[fn] = len(b.splitlines())
    # {(doc, file): {base lines the doc STILL names}} -- VERIFY'S OWN TEST,
    # including its "relocated onto another citation's old number" exemption,
    # so REPAIR here counts exactly what --verify complains about and the two
    # numbers can be compared without interpretation.
    targets, stale, docs = {}, {}, set()
    for fn, _old, new, who, _txt in drift:
        for doc in who:
            targets.setdefault((doc, fn), set()).add(new)
    for fn, old, new, who, _txt in drift:
        for doc in who:
            docs.add(doc)
            lines = doc_cite_lines(doc).get(fn, set())
            if (old in lines and old != new
                    and old not in targets.get((doc, fn), set())):
                stale.setdefault((doc, fn), set()).add(old)
    per_doc = []
    for doc in sorted(docs - exclude):
        text = work_text(doc)
        if text is None:
            continue
        rep = []
        if rewrite_doc(text, maps, hi, report=rep) == text:
            continue
        r = [t for t in rep if t[1] in stale.get((doc, t[0]), ())]
        c = [t for t in rep if t[1] not in stale.get((doc, t[0]), ())]
        per_doc.append((doc, r, c))
    return per_doc, sorted(docs & exclude)


def _tok_id(t):
    """The canonical `path:line[-line]` name of one rewrite report entry.

    A bare continuation is reported as `` `:NNN` `` -- a token an operator
    cannot type unambiguously on a command line, and one that does not say
    WHICH file it continues.  Both forms are named here by the (file, line)
    pair they resolve to, so `--allow-collateral sw/x.py:120` clears the full
    token and its continuations alike.
    """
    fn, a, b = t[0], t[1], t[2]
    return ("%s:%d-%d" % (fn, a, b)) if b is not None else ("%s:%d" % (fn, a))


def split_allowed(per_doc, allow=()):
    """([(doc, tok, matched-by, reason)], [(doc, tok)], [values matching none]).

    THE CASE THIS EXISTS FOR (review of the pre-ship tool chore, I-1).  The
    COLLATERAL refusal `--fix` gained is DOCUMENT-GRANULAR and its only
    documented escape, `--exclude`, drops a whole document -- including every
    legitimate REPAIR in it.  That is not hypothetical: S5's own pass
    (`evidence/qwen9b/s5/170_cite_drift_plan.log`) planned REPAIR 11 /
    COLLATERAL 1 on one document, the operator checked the single collateral
    token by hand, ran `--fix`, and `--verify` came back clean.  Under the
    refusal alone that pass is rc 2 and `--exclude` costs the eleven repairs.

    So the escape is PER CITATION as well as per document, and it is LOUD: an
    allowed token is not silently exempted, it is printed by name with the
    rewrite it will receive and counted in the verdict line, in `--plan` and
    `--fix` both.  The operator's assertion "I checked this one" is then IN
    THE LOG, which is the only property that makes it different from turning
    the guard off.

    Matching is EXACT, on either the citing document's repo-relative path or
    the cited `path:line[-line]` -- so a typo clears nothing rather than
    everything (the property `--exclude-control` proves for `--exclude`), and
    a value that matched nothing is returned so the caller can say so.

    THE REASON (re-review of fix round 1, m6).  A value may be written
    `<value>=<reason>`, and the reason is printed beside the token it
    clears.  Until 2026-09-10 the log recorded only WHAT was cleared, never
    WHY: enough to stop a silent widening, not enough for a reader a year
    later, who cannot tell a checked token from a cleared-to-get-on-with-it
    one.  The split is on the FIRST `=`; neither a repo path nor a
    `path:line` contains one.  A cleared token with no reason still clears
    -- the absence is PRINTED rather than hidden, which is the honest
    default for a flag that already existed without one.
    """
    reasons = {}
    for v in allow:
        k, sep, r = v.partition("=")
        k, r = k.strip(), r.strip()
        if reasons.get(k) is None:
            reasons[k] = (r if sep and r else None)
    allowed, refused, used = [], [], set()
    for doc, _r, c in per_doc:
        for t in c:
            key = doc if doc in reasons else (
                _tok_id(t) if _tok_id(t) in reasons else None)
            if key is None:
                refused.append((doc, t))
            else:
                used.add(key)
                allowed.append((doc, t, key, reasons[key]))
    return allowed, refused, sorted(set(reasons) - used)


def _print_allowed(allowed, unmatched, refused=0):
    """The record every `--allow-collateral` run leaves, in both modes.

    `refused` is how many collateral tokens were NOT cleared.  When it is
    non-zero the run is about to REFUSE and write nothing, so nothing is
    ALLOWED and the verb says WOULD CLEAR instead (re-review of fix round 1,
    m7: `_print_allowed` runs BEFORE the refusal, so a mixed run used to
    announce "ALLOWED N ... on the operator's assertion" and then apply
    none of it -- a log line that reads like a pass that happened).
    """
    verb = "WOULD CLEAR" if refused else "ALLOWED"
    for v in unmatched:
        print("  ! ALLOW-COLLATERAL %s matches no collateral token — it "
              "clears NOTHING (exact match on a citing document or a "
              "`path:line`)" % v)
    for doc, t, key, reason in allowed:
        print("  %s COLLATERAL %s  %s -> %s   (--allow-collateral %s)"
              % (verb, doc, t[5], t[6], key))
        print("      REASON  %s" % (reason if reason else
                                    "(NONE GIVEN — pass "
                                    "--allow-collateral <value>=<reason>)"))
    if allowed and refused:
        print("  WOULD CLEAR %d collateral rewrite(s), EVERY ONE NAMED "
              "ABOVE — but %d further collateral token(s) are NOT cleared, "
              "so this run REFUSES and writes NOTHING: none of them was "
              "applied" % (len(allowed), refused))
    elif allowed:
        print("  ALLOWED    %d collateral rewrite(s), EVERY ONE NAMED ABOVE, "
              "on the operator's assertion that each was checked by hand "
              "(%d with a recorded reason)"
              % (len(allowed), sum(1 for a in allowed if a[3])))


def plan_report(base, drift, exclude=(), allow=()):
    """DRY RUN: what a --fix at this base WOULD rewrite, token by token,
    split into the two kinds — and only one of them is a repair.

    THE DEFECT THIS EXISTS FOR (G3.4 fix round 3, R3-1).  `--fix` is a
    base->work renumber over a WHOLE document, but a document is not in one
    coordinate system: a pass at this same base has usually already run, so
    SOME of its citations already name the work line and some still name the
    base line.  `--verify` reports only the second kind.  Re-running `--fix`
    "to clear the residue" therefore repairs those few and DOUBLE-SHIFTS
    every citation the earlier pass got right -- the O3 defect, wearing the
    disguise of a maintenance pass.  MEASURED, at base 8138d66 over T10's
    set (evidence/qwen9b/g3/317_plan_seta_8138d66_r3.log):
    `TOTAL REPAIR 1 COLLATERAL 253` -- one citation stale, 253 already
    correct and about to be moved a second time.  Before that round's own
    hand repairs the same run read REPAIR 0 / COLLATERAL 250
    (evidence/qwen9b/g3/G3_4_LAYER.md section 17.2).  (This docstring said
    "3 citations are stale and the pass would move about 180 in 28
    documents" until 2026-09-10; no log carries those numbers.)

    So the question "is a --fix safe at this base?" has to be ASKED, and
    this answers it:

      REPAIR      the citing document still names the OLD line, which is
                  exactly what `--verify` complains about -- the rewrite
                  fixes it.
      COLLATERAL  the document already names a line that is NOT the base
                  line of the drift entry, i.e. it was repaired before and
                  the pass would move it again.

    Exit 0 only when COLLATERAL is empty -- or when every collateral token is
    named by `--allow-collateral`, which is the operator saying IN THE LOG
    that they checked those tokens by hand (see `split_allowed`).  Otherwise
    the residue at this base must be repaired BY HAND (or the document
    `--exclude`d), never by another pass.
    """
    per_doc, excluded = plan_split(base, drift, exclude)
    print("o3 citation-drift gate  [plan — dry run, nothing is written]")
    print("  code base  %s" % base)
    print("  files      %d edited file(s)" % len(EDITED))
    repairs = coll = 0
    for doc, r, c in per_doc:
        repairs += len(r)
        coll += len(c)
        print("  %-62s REPAIR %2d  COLLATERAL %3d" % (doc, len(r), len(c)))
        for t in c[:6]:
            print("      collateral  %s -> %s" % (t[5], t[6]))
        if len(c) > 6:
            print("      collateral  ... and %d more" % (len(c) - 6))
    for doc in excluded:
        print("  EXCLUDED   %s" % doc)
    print("  TOTAL      REPAIR %d  COLLATERAL %d" % (repairs, coll))
    allowed, refused, unmatched = split_allowed(per_doc, allow)
    _print_allowed(allowed, unmatched, refused=len(refused))
    print("O3_FIX_PLAN: %s"
          % ("SAFE — every rewrite repairs a citation --verify reports stale"
             if coll == 0 else
             "SAFE — %d of %d rewrites are COLLATERAL and every one is "
             "CLEARED BY NAME with --allow-collateral above; the other %d "
             "repair a citation --verify reports stale"
             % (coll, coll + repairs, repairs) if not refused else
             "UNSAFE — %d of %d rewrites would move a citation that is "
             "already correct; repair the %d stale one(s) BY HAND, "
             "--exclude the document, or clear each CHECKED token with "
             "--allow-collateral" % (len(refused), coll + repairs, repairs)))
    return 0 if not refused else 1


def exclude_control(base, doc_base, drift, exclude=()):
    """NEGATIVE CONTROL for --exclude (G3.4 review round 1, finding O3).

    A switch that cannot be shown to do anything is a comment.  THREE
    halves, and the first is what makes the second mean something:

      1  WITHOUT --exclude the chosen document IS in the pass's plan --
         i.e. --fix would rewrite it.  Otherwise the exclusion below would
         pass vacuously.
      2  WITH --exclude it is NOT in the plan, and `apply_fix` writes the
         plan and nothing else, so the document comes back BYTE-IDENTICAL
         -- while the rest of the pass still has documents to rewrite, so
         "skipped" cannot be confused with "did nothing".
      3  An --exclude path that names NO citer (a typo) changes the plan
         not at all: the flag excludes nothing rather than everything.

    Every half asks `fix_plan`, which is the function `apply_fix` writes
    out, so the control cannot certify behaviour the fix path does not
    have.  Nothing here touches the working tree.

    The victim is the document named by --exclude when one is given -- so
    the committed control is about the document the round actually
    excluded -- and otherwise the first document the pass would rewrite.
    """
    plan, _skipped = fix_plan(base, drift)          # half 1: nothing excluded
    movers = sorted(plan)
    print("o3 citation-drift gate  [exclude negative control]")
    print("  code base  %s" % base)
    print("  doc base   %s" % doc_base)
    print("  candidates %d document(s) this pass would rewrite" % len(movers))
    if not movers:
        print("O3_EXCLUDE_CONTROL: FAIL — no document would be rewritten, so "
              "the control is vacuous")
        return 1
    named = [d for d in exclude if d in movers]
    bad = []
    for d in exclude:
        if d not in movers:
            print("  %-52s %s" % (d, "not a document this pass would rewrite "
                                     "— not controllable here"))
    # EVERY document the round excluded is controlled, not just the first:
    # an exclusion nobody proved is an exclusion nobody can trust.
    for victim in (named or movers[:1]):
        # half 1 is `victim in movers`, which the selection above
        # guarantees; it is printed rather than assumed so the log says so.
        print("  %-52s %s" % (victim + " without --exclude",
                              "IN THE PLAN (as it must be)"))
        # half 2: the same pass, excluding it
        kept, skipped = fix_plan(base, drift, exclude={victim})
        if victim in kept:
            bad.append("%s is still in the plan with --exclude" % victim)
        if skipped != [victim]:
            bad.append("--exclude skipped %s, not [%s]" % (skipped, victim))
        print("  %-52s %s" % (victim + " with --exclude",
                              "NOT IN THE PLAN → byte-identical (apply_fix "
                              "writes the plan and nothing else)"))
        print("  %-52s %d" % ("other documents still in the pass", len(kept)))
        if not kept:
            bad.append("excluding %s emptied the pass — the control cannot "
                       "tell 'skipped' from 'did nothing'" % victim)
    # half 3: a path that names no citer must change nothing
    typo = (named or movers)[0] + ".not-a-citer"
    tplan, tskip = fix_plan(base, drift, exclude={typo})
    if sorted(tplan) != movers or tskip:
        bad.append("an --exclude path naming no citer changed the pass "
                   "(%d docs vs %d, skipped %s)"
                   % (len(tplan), len(movers), tskip))
    print("  %-52s %s" % ("a path that names no citer",
                          "changes nothing (%d document(s) still planned)"
                          % len(tplan)))
    print("O3_EXCLUDE_CONTROL: %s (%d problem(s))"
          % ("PASS — an excluded document is byte-identical, the rest of "
             "the pass still runs, and a typo excludes nothing"
             if not bad else "FAIL", len(bad)))
    for b in bad:
        print("  ! " + b)
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser()
    # dc8f492 is the tree Task 6 started from (A2 bound; G1/G2a/G2b/G2c
    # closed).  Any other base answers a different question.
    ap.add_argument("--base", default="dc8f492",
                    help="the sw/ tree the citations were written against")
    ap.add_argument("--doc-base", default=None,
                    help="the tree to read the CITING documents from "
                         "(default: --base).  Never the working tree: that "
                         "is what makes --verify reproducible after --fix")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true")
    g.add_argument("--fix", action="store_true")
    g.add_argument("--verify", action="store_true")
    ap.add_argument("--only-docs", default=None,
                    help="regex: fix only citing files whose path matches.  "
                         "--fix is NOT idempotent (it maps base->work, so a "
                         "second run would re-map an already-fixed number), "
                         "which is why a later round restricts itself to the "
                         "files an earlier round did not touch, or moves its "
                         "--base forward to that round's commit.  SINCE "
                         "2026-09-10 the non-idempotence is a REFUSAL rather "
                         "than damage: a WHOLLY landed pass fails --fix's "
                         "--verify-is-clean test and a PARTLY landed one "
                         "shows COLLATERAL, and both exit 2.  Restricting "
                         "the pass is still how the work gets DONE")
    ap.add_argument("--files", default=None,
                    help="regex: consider citations into these edited sw/ "
                         "files only")
    ap.add_argument("--edited", default=None,
                    help="comma-separated REPO-RELATIVE paths this task "
                         "edited, replacing the built-in Task 6 sw/ list.  "
                         "G3.1 (Task 7) edits rtl/, ref/, tb/, sw/, synth/ "
                         "and docs/, so it passes its own set; the default "
                         "keeps T6's runs reproducible")
    ap.add_argument("--exclude", action="append", default=[],
                    metavar="DOC",
                    help="repo-relative path of a CITING document to keep "
                         "OUT of a --fix pass.  For a document written "
                         "DURING the task in the FINAL tree's coordinates "
                         "-- a gate doc -- whose pointers --fix would "
                         "otherwise map base->work a second time and "
                         "double-shift (G3.4 review round 1, O3; the same "
                         "defect hit T9).  Repeatable.  Proven by "
                         "--exclude-control")
    ap.add_argument("--exclude-control", action="store_true",
                    help="--exclude's own negative control: a document the "
                         "pass WOULD rewrite comes back byte-identical when "
                         "excluded, and the rest of the pass still runs")
    ap.add_argument("--allow-collateral", action="append", default=[],
                    metavar="DOC|path:NNN[=REASON]",
                    help="clear ONE collateral rewrite (or a whole citing "
                         "document's worth) past --fix's COLLATERAL refusal, "
                         "having CHECKED it by hand.  Exact match on the "
                         "citing document's repo-relative path or on the "
                         "cited `path:line` / `path:line-line`; repeatable.  "
                         "Every cleared token is PRINTED BY NAME and counted "
                         "here and in --plan, so the decision is in the log. "
                         "An optional =REASON after the value is printed "
                         "beside the token it clears, which is how the "
                         "operator's ASSERTION and not just its consequence "
                         "reaches the log; with no reason the log says so.  "
                         "A BARE CONTINUATION (`` `:NNN` ``, a line naming "
                         "no file) is what the refusal PRINTS but not a "
                         "token you can type: pass the cited file and the "
                         "line that continuation currently names -- "
                         "path:NNN, the value --plan reports for it -- or "
                         "the citing document's path, and the continuation "
                         "is cleared along with its full token.  This is "
                         "the per-citation escape --exclude is not: "
                         "excluding a document forfeits its REPAIRs too, "
                         "which on S5's REPAIR 11 / COLLATERAL 1 plan "
                         "(evidence/qwen9b/s5/170_cite_drift_plan.log) meant "
                         "eleven citations repaired by hand.  A value that "
                         "names no collateral token clears NOTHING and says "
                         "so")
    ap.add_argument("--plan", action="store_true",
                    help="DRY RUN: what a --fix at this base would rewrite, "
                         "split into REPAIR (the document still names the "
                         "OLD line, so the rewrite fixes it) and COLLATERAL "
                         "(the document already names the right line and the "
                         "pass would move it AGAIN).  Ask this before every "
                         "--fix at a base some pass has already run: "
                         "non-empty COLLATERAL means repair by hand, or "
                         "clear the tokens you have CHECKED with "
                         "--allow-collateral, which this mode honours "
                         "and reports exactly as --fix does")
    ap.add_argument("--negative-control", action="store_true")
    ap.add_argument("--range-control", action="store_true",
                    help="the all-or-nothing range rule's own negative "
                         "control (finding O3): a synthetic range with one "
                         "deleted endpoint must come back UNTOUCHED, and one "
                         "with both live must still be rewritten")
    ap.add_argument("--doc-cites", action="store_true",
                    help="the OTHER drift class (review F6): citations into "
                         "the DOCUMENTS this task edited, whose lines its "
                         "insertions moved.  Check-only; targets derived "
                         "from the line-count change, not listed")
    a = ap.parse_args()
    if a.edited:
        _set_edited([p.strip() for p in a.edited.split(",") if p.strip()])
    if a.range_control:
        return range_control()
    if a.exclude_control:
        _dbase = a.doc_base or a.base
        _ok, _drift, _u, _m, _n, _h = classify(a.base, _dbase, 0)
        return exclude_control(a.base, _dbase, _drift, exclude=a.exclude)
    if a.plan:
        _dbase = a.doc_base or a.base
        _ok, _drift, _u, _m, _n, _h = classify(a.base, _dbase, 0)
        return plan_report(a.base, _drift, exclude=a.exclude,
                           allow=a.allow_collateral)
    if a.doc_cites:
        return _cmd_doc_cites(a.base, a.verify, a.negative_control)
    doc_base = a.doc_base or a.base
    mode = "fix" if a.fix else ("verify" if a.verify else "check")
    off = 1 if (a.negative_control and mode == "check") else 0

    ok, drift, unresolved, missing, ncites, half = classify(
        a.base, doc_base, off)
    if a.files:
        fre = re.compile(a.files)
        drift = [d for d in drift if fre.search(d[0])]
        unresolved = [u for u in unresolved if fre.search(u[0])]
        half = [h for h in half if fre.search(h[0])]
    if a.only_docs:
        dre = re.compile(a.only_docs)
        drift = [(fn, o, n, [w for w in who if dre.search(w)], t)
                 for (fn, o, n, who, t) in drift]
        drift = [d for d in drift if d[3]]

    print("o3 citation-drift gate  [%s]" % mode)
    print("  code base  %s" % a.base)
    print("  doc base   %s" % doc_base)
    print("  files      %d edited files" % len(EDITED))
    print("  citations  %d distinct (file, line) pairs" % ncites)
    print("  unmoved    %d" % len(ok))
    print("  half-ranges %d (one endpoint unresolved — NEVER rewritten)"
          % len(half))
    if a.negative_control:
        print("  MODE       NEGATIVE CONTROL")

    if mode == "check":
        for fn, ln, new, who, txt in drift:
            print("  DRIFTED    %s:%d -> :%d   %r\n             cited by %s"
                  % (fn, ln, new, txt, ", ".join(who)))
        for fn, ln, who, txt, why in unresolved:
            print("  UNRESOLVED %s:%d (%s)   %r\n             cited by %s"
                  % (fn, ln, why, txt, ", ".join(who)))
        for fn, ln, who, why in missing:
            print("  MISSING    %s:%d — %s\n             cited by %s"
                  % (fn, ln, why, ", ".join(who)))
        for fn, a_, b_, na, nb, who, ta, tb in half:
            print("  HALF-MAPPED %s:%d-%d — %s endpoint is unresolved, so the"
                  " WHOLE token is left alone (O3)\n"
                  "             :%d %r -> %s\n"
                  "             :%d %r -> %s\n"
                  "             cited by %s"
                  % (fn, a_, b_, "the start" if na is None else "the end",
                     a_, ta, na if na is not None else "GONE",
                     b_, tb, nb if nb is not None else "GONE",
                     ", ".join(who)))
        bad = len(drift) + len(unresolved) + len(missing) + len(half)
        if a.negative_control:
            print("O3_CITE_DRIFT CHECK NEGATIVE CONTROL: %s (%d reported)"
                  % ("CAUGHT" if bad else "*** MISSED ***", bad))
            return 0 if bad else 1
        print("O3_CITE_DRIFT CHECK %s (%d drifted, %d unresolved, "
              "%d missing, %d half-mapped)"
              % ("PASS" if bad == 0 else "FAIL", len(drift), len(unresolved),
                 len(missing), len(half)))
        return 0 if bad == 0 else 1

    if mode == "fix":
        # --fix is a base->work RENUMBER, so it is NOT IDEMPOTENT: `sweep`
        # reads the citing documents at --doc-base, so the drift list does
        # not shrink once the pass has landed, and a SECOND pass maps
        # already-fixed numbers a second time.  That is O3's double-shift
        # applied to every document instead of one.  Measured on this tree
        # at base 89b2d7d: a second pass would have moved
        # `ref/seq_format.py:560-561` in docs/SEQ_ISA.md to `:578-579`,
        # which is nowhere near the MOVX reject it names.
        #
        # `--verify` is exactly the question "has this base's pass already
        # landed?" -- it reads the WORKING tree's citations -- so ask it
        # before writing anything.  It catches the fully-applied case,
        # which is the one an operator re-runs by hand.  The HALF-applied
        # tree used to be "the operator's problem"; since triage (b)1 it is
        # the tool's, and the second guard below refuses it.
        if not verify(a.base, drift, exclude=a.exclude):
            print("O3_CITE_DRIFT FIX REFUSED — --verify is already clean at "
                  "base %s, so this pass has ALREADY been applied; a second "
                  "one would double-shift every citation it renumbered"
                  % a.base)
            return 2
        # ...AND THAT GUARD IS NOT ENOUGH, which is the half of section 18.2
        # that stayed open (triage (b)1).  It only sees a WHOLE landed pass.
        # On a MIXED tree -- some documents already repaired by hand in
        # post-fix coordinates, one still stale -- `--verify` is dirty
        # because of the stale one, so the guard above stands aside and the
        # repaired documents are shifted a SECOND time.  `--plan`'s
        # COLLATERAL is exactly the set that would move without needing to,
        # and it is now a REFUSAL rather than a dry run an operator has to
        # remember to ask for.
        _per_doc, _ = plan_split(a.base, drift, exclude=a.exclude)
        # ...and the refusal needs a PER-CITATION escape, or it blocks passes
        # the campaign itself ran (review of the pre-ship tool chore, I-1).
        # `--allow-collateral` clears a token the operator has checked BY
        # HAND, loudly: every cleared rewrite is named and counted below, so
        # the assertion is in the log rather than in someone's memory.
        # `--exclude`, the other remedy, drops the document's REPAIRs too.
        _allowed, _coll, _unmatched = split_allowed(_per_doc,
                                                    a.allow_collateral)
        _print_allowed(_allowed, _unmatched, refused=len(_coll))
        if _coll:
            for d, t in _coll[:12]:
                print("  ! COLLATERAL %s  %s -> %s" % (d, t[5], t[6]))
            if len(_coll) > 12:
                print("  ! COLLATERAL ... and %d more" % (len(_coll) - 12))
            print("O3_CITE_DRIFT FIX REFUSED — %d rewrite(s) would move a "
                  "citation that is ALREADY correct (a pass at base %s has "
                  "partly landed).  Repair the stale one(s) BY HAND, "
                  "--exclude those documents (which forfeits their REPAIRs "
                  "too), or clear each token you have CHECKED with "
                  "--allow-collateral <doc|path:NNN>; see --plan"
                  % (len(_coll), a.base))
            return 2
        n = apply_fix(a.base, doc_base, drift, exclude=a.exclude)
        print("  FIXED      %d citation(s) in %d document(s)"
              % (len(drift), n))
        print("O3_CITE_DRIFT FIX APPLIED — now run --verify")
        return 0

    bad = verify(a.base, drift, wrong=a.negative_control,
                 exclude=a.exclude)
    for b in bad[:40]:
        print("  ! " + b)
    if a.negative_control:
        print("O3_CITE_DRIFT VERIFY NEGATIVE CONTROL: %s (%d complaints)"
              % ("CAUGHT" if bad else "*** MISSED ***", len(bad)))
        return 0 if bad else 1
    print("  relocated  %d citation(s) checked against the base content and "
          "the citing documents" % len(drift))
    # An entry every one of whose citers is EXCLUDED is not this pass's
    # business: the excluded document was repaired by hand, in the final
    # tree's coordinates, which is the whole reason it was excluded.
    _ex = set(a.exclude)
    half = [h for h in half if set(h[5]) - _ex]
    unresolved = [u for u in unresolved if set(u[2]) - _ex]
    missing = [m for m in missing if set(m[2]) - _ex]
    if _ex:
        print("  excluded   %s" % ", ".join(sorted(_ex)))
    for fn, a_, b_, na, nb, who, _ta, _tb in half:
        print("  ! HALF-MAPPED %s:%d-%d left untouched (%s endpoint gone); "
              "repair by hand against `git show %s:%s`, cited by %s"
              % (fn, a_, b_, "start" if na is None else "end",
                 a.base, fn, ", ".join(who)))
    if unresolved or missing:
        for fn, ln, who, txt, why in unresolved:
            print("  ! UNRESOLVED %s:%d (%s) cited by %s"
                  % (fn, ln, why, ", ".join(who)))
        for fn, ln, who, why in missing:
            print("  ! MISSING %s:%d — %s" % (fn, ln, why))
    n = len(bad) + len(unresolved) + len(missing)
    print("O3_CITE_DRIFT VERIFY %s (%d problem(s))"
          % ("PASS" if n == 0 else "FAIL", n))
    return 0 if n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
