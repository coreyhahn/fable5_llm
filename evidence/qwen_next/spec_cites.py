#!/usr/bin/env python3
"""spec_cites.py — mechanize the citation check for a spec/gate document.

WHY THIS EXISTS
---------------
The Qwen3.5-9B migration spec was hand-swept for citation accuracy twice, and
review found drifted citations BOTH times — the second time in the very prose
that was correcting the first.  Hand-sweeping does not work at this citation
density (250+ distinct sites).  So the check is mechanized, in the house style
Track L's review round established: a script that re-derives the claim, plus a
NEGATIVE CONTROL that proves the script can fail.

WHAT IT CHECKS
--------------
For every `path:line` / `path:line-line` citation in the document:

  EXIST   the cited file exists in the tree
  RANGE   every cited line number is within the file
  QUOTE   where the document puts a source quotation NEXT TO a citation, that
          text really appears at or near the cited line
  AMBIG   a bare `:NNN` continuation on a line naming MORE THAN ONE file --
          the convention silently picks the last one named
  ORPHAN  a bare `:NNN` continuation on a line naming NO file -- it binds to
          nothing, so the cite AND any quotation beside it go unchecked

and two non-failures, each listed deliberately in this file so a typo cannot
hide behind them: PENDING (a path a future gate creates) and RETIRED (a path
a gate has deleted, whose citing text needs a dated supersession note).

Citation forms understood (all inside markdown backticks):

    `rtl/foo.sv`             bare path            -> EXIST
    `rtl/foo.sv:159`         path + line          -> EXIST, RANGE
    `rtl/foo.sv:159-161`     path + range         -> EXIST, RANGE
    `:424-426`               CONTINUATION — inherits the most recently named
                             file on the same line, which is the convention
                             this repo's documents already use.

Quotation forms understood, on the same markdown line as a citation:

    `logic [11:0] cnt, n_total;`      backticked source span
    *"12 bits: n_total = 2048 must FIT"*   italic-quoted comment text
    **"…"**                                bold-quoted comment text
    ```lang … ```                          a fenced block immediately below

A backticked span is treated as a source quotation only if it looks like code
(length >= MIN_QUOTE and contains one of = < > [ ] ( ) ; ,) — otherwise prose
like `cfg_ng` or `int8naive` would be checked as if it were a quotation.
Quoted text is whitespace-normalized before comparison, so a quotation may span
a line break in the source.

EXIT
----
0 with "SPEC CITES: PASS" if every check passes, 1 otherwise.  PENDING and
RETIRED citations are reported and do NOT fail the run.

USAGE
-----
    ./spec_cites.py <document.md> [<document.md> ...]
    ./spec_cites.py --selftest        # the negative control, see below

IN SCOPE for the 9B campaign -- both are gated before every commit that
touches them (see the plan's Global Constraints):

    docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md
    docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md

THE NEGATIVE CONTROL (--selftest)
---------------------------------
A checker that cannot fail proves nothing.  --selftest copies the real document
to a scratch tree, perturbs it SIX ways -- a line number pushed past EOF, a path
that does not exist, a quotation moved far from its cite, a fabricated
quotation, an orphan continuation, and an ambiguous one -- and REQUIRES the
checker to reject each.  It then re-runs the unperturbed copy and requires a
pass.  This mirrors the negative controls in
evidence/qwen_next/ladder/LADDER.md section 5b.

It works on ANY document.  Until 2026-08-31 it did not: it assumed the document
cited RTL, assumed the document carried a line holding both a cite and a
quotation of it, and resolved bare-filename cites against its own scratch tree.
Each assumption crashed or false-failed a real gate document -- see the block
above selftest() for the three defects, and
evidence/qwen9b/g2/spec_cites_selftest_regression.sh for the regression that
holds the repair in place, including the counter-experiment showing what the
obvious wrong fix would have done to the EXIST check.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MIN_QUOTE = 12          # shorter backticked spans are prose, not source
NEAR = 6                # a quotation may sit this many lines either side
CODEISH = set("=<>[]();,")

# Extensions we treat as citable source.  A citation to anything else (a .bit,
# a directory) is ignored rather than failed.
CITE_EXT = (".sv", ".v", ".py", ".md", ".sh", ".tcl", ".xdc", ".csv",
            ".json", ".txt", ".log", ".rpt", "Makefile")

# Paths the document names that no gate has created yet.  A citation to one of
# these is reported as PENDING, not as a failure -- but it must be listed here
# deliberately, so a typo cannot hide in the pending set.
PENDING = {
    # 2026-09-04 state-spill plan (docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md): Tasks S1-S5 create these;
    # prune each when it lands.
    #
    # S5 fix round 2 (2026-09-05) pruned the last five, all LANDED:
    # synth/constraints/fable5_floorplan_9b_1slr.xdc (the floorplan Task S5
    # exists to produce), evidence/qwen9b/s5/S5_STRUCT.md,
    # evidence/qwen9b/s5/s5_superlatives.py,
    # evidence/qwen9b/s5/ooc_s5_layer_util_synth.rpt and
    # evidence/qwen9b/s4/S4_REPLAY.md (landed at S4, carried stale into S5).
    # They are out for the reason every removal below is: PENDING is checked
    # BEFORE EXIST, so a stale entry would let a typo in the path, or a
    # deletion of the file, pass silently -- which is exactly what happened,
    # 15 citations in S5's own gate doc and 9 in the plan going unchecked in
    # evidence/qwen9b/s5/130_spec_cites.log, including all eight to the
    # floorplan XDC.
    # Task S1's sdma_bits.py and S1_ISA.md LANDED (2026-09-04) -- OUT of
    # PENDING for the reason every removal below was: PENDING is checked
    # BEFORE EXIST, so a stale entry would let a typo in the path, or a
    # deletion of the file, pass silently on the documents that cite it.
    #
    # S2's and S3's landed paths went the same way (2026-09-04, S3's Step
    # 5'; S2's gate doc section 7.6 handed this tidy-up over by name):
    # rtl/state_dma.sv, tb/axi_ram_bfm.sv, tb/tb_layer_sdma.sv,
    # evidence/qwen9b/s2/S2_RTL.md, evidence/qwen9b/s2/001_tb_layer_sdma_red.log,
    # evidence/qwen9b/s3/{S3_CHAIN.md, cold_red.py, preamble_equiv.py,
    # sdma_census.py, 001_emitter_cold_red.log} all EXIST now.
    # named by the spec
    # T4's FINAL_BYTELOCK.md is OUT of PENDING as of G2b -- see below.
    # named by docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md.
    # Each is created by the task whose name appears beside it; when a task
    # lands, its entries here become live paths and may be deleted from this
    # set (leaving them is harmless -- PENDING is checked before EXIST).
    # T1's three landed at G1 (commits 4965057 / cb12a59) and are live paths
    # now, so they are OUT of PENDING -- leaving them here would let a typo or
    # a deletion pass EXIST silently, which is the one thing PENDING costs.
    # T2's D_TOL.md landed at f3da761 -- live path, out of PENDING.
    # T2's run_ref_selftests_9b.sh landed at f3da761 -- live path, out of
    # PENDING (Task 2 is closed, so nothing is still going to create it).
    # T3's G2A_HOST.md and damage_defect_b.py landed at b2f1223 -- live paths,
    # out of PENDING; T3 is CLOSED, so nothing is still going to create them
    # and leaving them would suppress EXIST on two live files.
    # T4's FINAL_BYTELOCK.md landed at G2b, together with the pin script it
    # documents (evidence/qwen9b/g2/final_bytelock_pin.sh, never PENDING
    # because no document cited it before it existed).  It is cited from
    # evidence/qwen2b/rc/RC_GATE.md and evidence/qwen2b/rd/RD_GATE.md, which
    # are exactly the documents a stale PENDING would have stopped checking.
    # T5's G2C_CHAIN.md landed at G2c, together with the four evidence
    # scripts it documents (run_g2c_emit.sh, run_g2c_fit.sh, run_g2c_point.sh,
    # g2c_pack_fit.py, g2c_chat_template.py -- none of them ever PENDING,
    # because no document cited any of them before it existed).  It is out of
    # PENDING for the reason every removal before it was: PENDING is checked
    # BEFORE EXIST, so a stale entry would let a typo in the path, or a
    # deletion of the file, pass silently on the one document that cites it.
    # T6's sw/board_lock.py and evidence/qwen9b/o3/BOARD_LOCK.md landed at O3,
    # together with the three evidence scripts they document
    # (o3_red_percheckout.py, o3_lock_gate.py, o3_cite_drift.py -- none of them
    # ever PENDING, because no document cited any of them before it existed).
    # Both are out for the reason every removal before them was: PENDING is
    # checked BEFORE EXIST, so a stale entry would let a typo in the path, or
    # a deletion of the file, pass silently.  sw/board_lock.py in particular
    # is now cited by docs/USAGE.md, docs/ARCHITECTURE.md and docs/HISTORY.md
    # as well as by its own gate doc.
    # T7's isa_bits.py and G3_1_ISA.md landed at G3.1, together with the
    # SEQ_ISA v2.0 re-encoding they gate.  They are out of PENDING for the
    # reason every removal before them was: PENDING is checked BEFORE EXIST,
    # so a stale entry would let a typo in the path, or a deletion of the
    # file, pass silently on the one document that cites it.
    # T8's G3_2_VECNORM.md and T9's G3_3_MATVEC.md are OUT for the same
    # reason as every removal above: they have LANDED, and PENDING is checked
    # BEFORE EXIST, so keeping a landed file here would let a typo in its
    # path -- or a deletion of it -- pass silently on the documents that
    # cite it.  (G3_2's row was left behind when it landed at T8; T9 removed
    # both, its own with the gate doc it was holding open.)
    # G3.4's gate doc LANDED at T10, so it is out of PENDING for the same
    # reason every removal above it was: PENDING is checked BEFORE EXIST, so
    # a stale entry would let a typo or a deletion in that path pass
    # silently -- which is the one thing PENDING costs.
    # T14's two entries are OUT as of G5b (2026-09-06): both LANDED.
    # evidence/qwen9b/g5/G5B_TIMING.md is the gate document, and
    # synth/constraints/fable5_floorplan_9b_1slr_ctx.xdc is the in-context
    # one-SLR pblock the plan's AMENDED 2026-09-05 block told Task 14 to write
    # (the OOC original, fable5_floorplan_9b_1slr.xdc, was never pending).
    # They are removed for the reason every removal above was: PENDING is
    # checked BEFORE EXIST, so a stale entry would let a typo in the path -- or
    # a deletion of the file -- pass silently on the documents that cite it,
    # which is the one thing PENDING costs.  This is the S5 lesson applied on
    # the task that created the files rather than a round later.
    # T15's evidence/qwen9b/g6/RD9_GATE.md is OUT as of G6 (2026-09-09): it
    # LANDED.  Removed for the reason every removal above was: PENDING is
    # checked BEFORE EXIST, so a stale entry would let a typo in that path --
    # or a deletion of the file -- pass silently on every document that cites
    # it, which is the one thing PENDING costs.  This is the S5 lesson applied
    # on the task that created the file rather than a round later.
    # 2026-09-04: G4A_REPLAY.md, G4B_STRUCT.md and G5A_FLOORPLAN.md landed at
    # Tasks 11-13 -- OUT of PENDING (live paths, checked by EXIST).
}

# Paths a gate has DELETED.  A citation to one of these is reported as
# RETIRED, not as a failure, in the same shape PENDING is -- and, like
# PENDING, it must be listed here DELIBERATELY so a typo cannot hide behind
# it.  The difference is the direction of travel: a PENDING path is about to
# exist, a RETIRED one used to and never will again, so the documents that
# cite it need a dated supersession note rather than a wait.
#
# RETIRED is checked BEFORE Exist, exactly as PENDING is, and both are
# checked before ALIAS resolution -- so a short form that resolves to a
# retired path must be removed from ALIAS or it would resolve to a live
# file with the same basename somewhere else.
RETIRED = {
    # G2a (T3) deleted this in commit b2f1223: it was a stale near-copy of
    # tb/scripts/gen_seq_unit_vectors.py that tb/Makefile mentioned only in a
    # comment and never invoked (spec 7.5 E, 9's D-DEAD row).  Its ALIAS
    # entry was dropped in the same commit.  The sha is recorded here because
    # a RETIRED entry with no deleting commit is an assertion a reader cannot
    # check -- `git show b2f1223 --stat` is the whole audit trail.
    "tb/scripts/gen_seq_vectors.py",
}

# Short forms the documents use after naming the full path once.  Resolving
# them here is what lets the checker range-check `LADDER.md:615` rather than
# skip it.  A name that is NOT in this map and does not exist is a failure, so
# a typo cannot hide behind the convention.
ALIAS = {
    "LADDER.md":            "evidence/qwen_next/ladder/LADDER.md",
    "CHECKPOINT_VERIFY.md": "evidence/qwen_next/ladder/CHECKPOINT_VERIFY.md",
    "checkpoint_verify.py": "evidence/qwen_next/ladder/checkpoint_verify.py",
    "PLACE_EXP.md":         "evidence/qwen_next/place_exp/PLACE_EXP.md",
    "CORRECTIONS.md":       "evidence/qwen_next/defect_a/CORRECTIONS.md",
    "progress.md":          ".superpowers/sdd/2026-08-25-qwen-next-derisking/progress.md",
    "RD_GATE.md":           "evidence/qwen2b/rd/RD_GATE.md",
    "RC_GATE.md":           "evidence/qwen2b/rc/RC_GATE.md",
    "TIMING_035.md":        "evidence/qwen2b/rc/TIMING_035.md",
    "scratch_peak.py":      "evidence/qwen_next/feas/scratch_peak.py",
    "gate_port_probe.py":   "evidence/qwen2b/q2/audit/gate_port_probe.py",
    "gate_port_probe.txt":  "evidence/qwen2b/q2/audit/gate_port_probe.txt",
    "audit_log.txt":        "evidence/qwen2b/q2/audit/audit_log.txt",
    "rd_census.py":         "evidence/qwen2b/rd/rd_census.py",
    "scratch_probe.log":    "evidence/qwen2b/ra/scratch_probe.log",
    "ladder_table.py":      "evidence/qwen_next/ladder/ladder_table.py",
    "bytes_per_token.py":   "ref/scripts/bytes_per_token.py",
    "spec_cites.py":        "evidence/qwen_next/spec_cites.py",
    "t4_bytes_unmoved.sh":  "evidence/qwen2b/rc/t4_bytes_unmoved.sh",
    "rd_golden_shas.sh":    "evidence/qwen2b/rd/rd_golden_shas.sh",
    # was "sw/rd_residency_audit.py", which is not where the file is -- a wrong
    # ALIAS target is the one way a short form can silently fail EXIST.  The
    # only in-tree copy is under evidence/ (git ls-files, 2026-08-29).
    "rd_residency_audit.py": "evidence/qwen2b/rd/rd_residency_audit.py",
    "head_baseline_layer_fixed_2b.log":
        "evidence/qwen_next/ladder/head_baseline_layer_fixed_2b.log",
    "launch_exp.sh":        "synth/exp_uram/scripts/launch_exp.sh",
    "exp_ooc.tcl":          "synth/exp_uram/scripts/exp_ooc.tcl",
    "launch_build.sh":      "synth/scripts/launch_build.sh",
    "seq_model.py":         "ref/seq_model.py",
    "seq_format.py":        "ref/seq_format.py",
    "gen_layer_script.py":  "ref/gen_layer_script.py",
    "gen_model_script.py":  "ref/gen_model_script.py",
    "gen_token_script.py":  "ref/gen_token_script.py",
    "load_qwen35.py":       "ref/load_qwen35.py",
    "layer_fixed.py":       "ref/layer_fixed.py",
    "layer_ref.py":         "ref/layer_ref.py",
    "perplexity_eval.py":   "ref/perplexity_eval.py",
    "fidelity_check.py":    "ref/fidelity_check.py",
    "audit_ranges.py":      "ref/audit_ranges.py",
    "calib_stats.py":       "ref/calib_stats.py",
    "seq_chat.py":          "ref/seq_chat.py",
    "model_select.py":      "ref/model_select.py",
    "hwmap.py":             "sw/hwmap.py",
    "seq_run.py":           "sw/seq_run.py",
    "chat_seq.py":          "sw/chat_seq.py",
    "infer.py":             "sw/infer.py",
    "tok_meter.py":         "sw/tok_meter.py",
    "head_cache.py":        "sw/head_cache.py",
    "tb_seq_chip.sv":       "tb/tb_seq_chip.sv",
    "tb_seq_unit.sv":       "tb/tb_seq_unit.sv",
    "gen_seq_unit_vectors.py": "tb/scripts/gen_seq_unit_vectors.py",
    "gen_seq_layer_script.py": "tb/scripts/gen_seq_layer_script.py",
    "gen_seq_c_vectors.py": "tb/scripts/gen_seq_c_vectors.py",
}

# Upstream checkpoint files, named by the documents but not in this repo.
EXTERNAL = {"config.json", "tokenizer.json", "vocab.json", "merges.txt",
            "tokenizer_config.json", "chat_template.jinja",
            "model.safetensors", "golden_bf16_9b.npz"}

CITE_RE = re.compile(
    r'`(?P<path>(?:[A-Za-z0-9_.\-]+/)*[A-Za-z0-9_.\-]+'
    r'(?:' + "|".join(re.escape(e) for e in CITE_EXT) + r'))'
    r'(?::(?P<a>\d+)(?:-(?P<b>\d+))?)?`'
)
CONT_RE = re.compile(r'`:(?P<a>\d+)(?:-(?P<b>\d+))?`')
ITAL_RE = re.compile(r'\*{1,2}"([^"\n]{%d,})"\*{1,2}' % MIN_QUOTE)

# Markdown furniture that proves a span is prose, not a source quotation.
# (A backtick span containing a section sign is document text that merely
# happens to sit between two code spans.)
#
# `|` WAS IN THIS TUPLE AND IS NOT ANY MORE (#64, triage (b)2).  It was put
# here for the table-pipe case, but `backtick_spans` pairs backticks EXACTLY
# — the separators of a well-formed table row land in the EVEN pieces, never
# in a span — so the only spans a pipe reached were the ones where THE
# QUOTED SOURCE LINE ITSELF CONTAINS A PIPE: SystemVerilog `||`, a Python
# `|`, a shell pipeline.  That is the campaign's own gate-doc idiom, and
# every one of those quotations was exempt from the QUOTE check.  The
# residual case the mark also covered — a line with an ODD number of
# backticks, where the pairing slips and a span swallows a cell separator —
# is a MALFORMED line, and a QUOTE failure is the right report for it.
PROSE_MARK = ("§", "**", "—", "…", "->", "→")


def quote_forms(qn):
    r"""The forms a quotation may legitimately have been WRITTEN in.

    MARKDOWN REQUIRES `|` TO BE ESCAPED INSIDE A TABLE CELL, and this
    campaign's gate documents are mostly tables, so an honest quotation of a
    line carrying a pipe -- SystemVerilog `||`, a Python `|`, a shell
    pipeline -- is written `\|` and does not match its own source.  That did
    not matter while `|` was in `PROSE_MARK` (the span was never checked at
    all); dropping it (#64, triage (b)2) makes it matter for every such row,
    and it surfaced immediately on `evidence/qwen9b/g3/G3_3_MATVEC.md:859`.

    The unescaping is ADDITIVE -- the raw form is tried first and is never
    removed -- so this can only turn a failure into a pass, never the other
    way, and a quotation that really does carry a backslash-pipe (a regex,
    say) still matches on its raw form.
    """
    forms = [qn]
    if "\\|" in qn:
        forms.append(qn.replace("\\|", "|"))
    return forms


def backtick_spans(line):
    """Exact backtick pairing: split on `, odd-indexed pieces are the spans.

    A regex over `([^`]+)` mis-pairs when a line has an odd number of
    backticks, which silently turns the PROSE BETWEEN two code spans into a
    'quotation' -- the first bug this checker had, found by running it.
    """
    parts = line.split("`")
    return parts[1::2], "".join(parts[0::2])


def norm(s):
    """Whitespace-normalize so a quotation may wrap in either document."""
    return re.sub(r'\s+', ' ', s).strip()


def nlines(path):
    with open(path, 'rb') as f:
        return sum(1 for _ in f)


def readlines(path):
    with open(path, 'r', errors='replace') as f:
        return f.read().split("\n")


NOQUOTE = "<!--cites:noquote-->"


class Check:
    def __init__(self):
        self.fail = []
        self.pending = []
        self.retired = []
        self.noquote = []
        self.n_exist = self.n_range = self.n_quote = self.n_ambig = 0
        self.n_orphan = 0

    def bad(self, doc, lineno, kind, msg):
        self.fail.append((doc, lineno, kind, msg))


def fenced_after(lines, i):
    """Return the fenced code block that starts within 2 lines after i."""
    j = i + 1
    while j < len(lines) and j <= i + 2 and not lines[j].startswith("```"):
        j += 1
    if j >= len(lines) or not lines[j].startswith("```"):
        return None
    out = []
    j += 1
    while j < len(lines) and not lines[j].startswith("```"):
        out.append(lines[j])
        j += 1
    return "\n".join(out) if out else None


def resolve(p, doc, docdir=None):
    """repo-root path, then ALIAS, then the document's OWN directory.

    Gate documents under evidence/<stage>/ name their sibling logs by bare
    filename; that is a real convention and the checker honours it rather
    than reporting 140 false failures on a document it did not write.

    `docdir` OVERRIDES that third candidate and exists for exactly one caller:
    --selftest, which copies the document into a temp dir and would otherwise
    resolve every bare-filename cite against the temp dir, where none of the
    siblings exist.  Measured on evidence/qwen9b/g2/FINAL_BYTELOCK.md: the
    relocation alone invents 18 EXIST failures, so the selftest's POSITIVE
    control failed on any document using the sibling convention.

    THE FIX THAT WOULD HAVE BEEN WORSE THAN THE BUG: adding an
    always-existing candidate (os.devnull, or the temp dir itself) so bare
    names "resolve".  That does not relocate the lookup, it DISABLES it —
    every nonexistent path in every document would then resolve, and
    evidence/qwen2b/rc/RC_GATE.md silently drops from FAIL 27 to FAIL 4.  A
    checker that stops failing is not a fixed checker.  So this parameter
    moves the search, and the default None reproduces the old behaviour
    exactly.
    """
    for cand in (os.path.join(REPO, p),
                 os.path.join(REPO, ALIAS.get(p, p)),
                 os.path.join(docdir or os.path.dirname(os.path.abspath(doc)),
                              p)):
        if os.path.exists(cand):
            return cand
    return os.path.join(REPO, ALIAS.get(p, p))


def check_doc(doc, ck, docdir=None):
    lines = readlines(doc)
    for i, line in enumerate(lines, 1):
        # --- collect citations on this markdown line -------------------
        cites = []          # (path, a, b)
        last_path = None
        for m in CITE_RE.finditer(line):
            p, a, b = m.group("path"), m.group("a"), m.group("b")
            last_path = p
            cites.append((p, int(a) if a else None, int(b) if b else None))
        conts = list(CONT_RE.finditer(line))
        for m in conts:
            if last_path is None:
                continue
            cites.append((last_path, int(m.group("a")),
                          int(m.group("b")) if m.group("b") else None))

        named = {m.group("path") for m in CITE_RE.finditer(line)}

        # --- ORPHAN ----------------------------------------------------
        # A bare `:NNN` on a line that names NO file inherits nothing: the
        # continuation convention only reaches back within one markdown line,
        # so the cite binds to nothing, is skipped entirely, and neither its
        # range NOR any quotation beside it is ever checked.  That is worse
        # than AMBIG -- AMBIG picks the wrong file loudly, ORPHAN checks
        # nothing silently.  31 of these were sitting in the 9B spec when G2a
        # added this check, every one of them a table row or list item whose
        # file was named on an EARLIER line.  The fix is always the same:
        # write the full path.
        #
        # THIS CHECK MUST RUN BEFORE THE `not cites` BAIL, and G2a's first
        # cut did not -- which made it DEAD CODE for the only input it
        # exists to catch.  An orphan line produces NO cites by construction
        # (the loop above skips every continuation when `last_path is
        # None`), so `if not cites: continue` returned before the branch was
        # ever reached and the reviewer's negative control passed silently.
        # A checker that cannot fail proves nothing; a checker whose new
        # check cannot fire proves less. `--selftest` now carries an ORPHAN
        # case and an AMBIG case so this cannot regress.
        if conts and not named:
            ck.n_orphan += 1
            ck.bad(doc, i, "ORPHAN",
                   f"bare continuation {conts[0].group(0)} on a line that "
                   f"names no file — it binds to nothing and is NOT checked; "
                   f"write the full path")

        if not cites:
            continue

        # --- AMBIG ------------------------------------------------------
        # A bare `:NNN` continuation inherits the most recently named file.
        # On a line that names TWO OR MORE distinct files that convention is
        # ambiguous to a reader and silently wrong when the writer meant the
        # other one.  This check exists because exactly that defect shipped
        # five times in this spec and RANGE only caught the subset where the
        # wrong file happened to be shorter.
        if conts and len(named) > 1:
            ck.n_ambig += 1
            ck.bad(doc, i, "AMBIG",
                   f"bare continuation {conts[0].group(0)} on a line naming "
                   f"{len(named)} files ({', '.join(sorted(named))}) — "
                   f"write the full path")

        # --- EXIST / RANGE ---------------------------------------------
        live = []
        for (p, a, b) in cites:
            if p in PENDING:
                ck.pending.append((doc, i, p))
                continue
            if p in RETIRED:
                ck.retired.append((doc, i, p))
                continue
            if p in EXTERNAL:
                continue
            full = resolve(p, doc, docdir)
            ck.n_exist += 1
            if not os.path.exists(full):
                ck.bad(doc, i, "EXIST", f"{p} does not exist")
                continue
            if a is None:
                continue
            ck.n_range += 1
            n = nlines(full)
            hi = b if b else a
            if hi > n or a < 1 or (b is not None and b < a):
                ck.bad(doc, i, "RANGE",
                       f"{p}:{a}{'-'+str(b) if b else ''} but file has {n} lines")
                continue
            live.append((p, full, a, hi))
        if not live:
            continue

        # --- QUOTE ------------------------------------------------------
        quotes = []
        spans, outside = backtick_spans(line)
        for t in spans:
            if len(t) < MIN_QUOTE:
                continue
            # the citation text itself is not a quotation of the file
            if CITE_RE.fullmatch("`" + t + "`") or CONT_RE.fullmatch("`" + t + "`"):
                continue
            if any(k in t for k in PROSE_MARK):
                continue
            if any(c in CODEISH for c in t):
                quotes.append(t)
        # italic/bold quotations are looked for OUTSIDE the code spans, so a
        # quote mark inside a code span cannot start a bogus match
        quotes += [m.group(1) for m in ITAL_RE.finditer(outside)]
        blk = fenced_after(lines, i - 1)
        if blk:
            quotes.append(blk)
        if NOQUOTE in line:
            ck.noquote.append((doc, i, len(quotes)))
            continue
        if not quotes:
            continue

        for q in quotes:
            qn = norm(q)
            if len(qn) < MIN_QUOTE:
                continue
            forms = quote_forms(qn)
            hit = False
            for (p, full, a, hi) in live:
                src = readlines(full)
                lo = max(0, a - 1 - NEAR)
                up = min(len(src), hi + NEAR)
                window = norm("\n".join(src[lo:up]))
                if any(f in window for f in forms):
                    hit = True
                    break
            ck.n_quote += 1
            if not hit:
                # is it anywhere in any cited file?  a different failure.
                anywhere = None
                for (p, full, a, hi) in live:
                    whole = norm("\n".join(readlines(full)))
                    if any(f in whole for f in forms):
                        anywhere = p
                        break
                where = (f"present in {anywhere} but NOT within {NEAR} lines of "
                         f"the cited line" if anywhere else
                         "not found in any cited file")
                ck.bad(doc, i, "QUOTE",
                       f'"{qn[:88]}{"…" if len(qn) > 88 else ""}" — {where} '
                       f"(cited: {', '.join(f'{p}:{a}' for p, _, a, _ in live)})")


def run(docs, docdir=None):
    ck = Check()
    for d in docs:
        if not os.path.exists(d):
            print(f"no such document: {d}")
            return 1
        check_doc(d, ck, docdir)
    print(f"checked: {ck.n_exist} exist, {ck.n_range} range, {ck.n_quote} quote"
          f"  |  pending {len(ck.pending)}  |  retired {len(ck.retired)}"
          f"  |  noquote {len(ck.noquote)}"
          f"  |  FAIL {len(ck.fail)}")
    for (d, i, k, m) in ck.fail:
        print(f"  {os.path.basename(d)}:{i}  {k}  {m}")
    for (d, i, n) in ck.noquote:
        print(f"  {os.path.basename(d)}:{i}  NOQUOTE  {n} span(s) exempted "
              f"(proposed encoding / shorthand, not a quotation)")
    if ck.pending:
        for (d, i, p) in ck.pending:
            print(f"  {os.path.basename(d)}:{i}  PENDING  {p} (a future gate creates this)")
    if ck.retired:
        for (d, i, p) in ck.retired:
            print(f"  {os.path.basename(d)}:{i}  RETIRED  {p} "
                  f"(deleted by a gate; the citing text needs a dated "
                  f"supersession note, not a fix)")
    if ck.fail:
        print("SPEC CITES: FAIL")
        return 1
    print("SPEC CITES: PASS")
    return 0


# ---------------------------------------------------------------- selftest
#
# THREE THINGS THIS USED TO ASSERT OUT ON, all found at G2b (2026-08-31) and
# all of them the same underlying mistake: the selftest assumed the document
# under test looks like THE SPEC.
#
#   (a) case (1)/(2) searched for an `rtl/*.sv:N` citation to perturb and
#       asserted if there was none.  Any document that cites no RTL -- every
#       host-only gate doc -- crashed before a single control ran.
#   (b) case (3)/(4) searched for a line carrying BOTH a cite and a quotation
#       of that cite, and asserted if there was none.  The real trigger is a
#       ZERO-QUOTE document, which is NOT the same set: G2A_HOST.md has three
#       rtl cites, sails past (a), and still crashed here.  Since a QUOTE check
#       only fires when the quotation shares a markdown line with its cite,
#       "no such line" is the NORMAL state of a document written as lists and
#       tables -- i.e. exactly the documents that most need a working control.
#   (c) the perturbed copies live in a temp dir, so resolve()'s
#       document's-own-directory fallback pointed at the temp dir and every
#       bare-filename cite stopped resolving.  On FINAL_BYTELOCK.md that
#       invents 18 EXIST failures, so even the POSITIVE control failed.
#
# (a) and (b) are fixed by deriving the perturbation targets from the document
# instead of assuming them -- and, for (b), by SYNTHESIZING a cite+quotation
# line from a real cited file when the document has none.  The synthetic line
# is verified clean before it is perturbed, so a broken synthesis fails loudly
# instead of making cases (3) and (4) vacuously "CAUGHT".
# (c) is fixed by passing the ORIGINAL document's directory to resolve(); see
# the warning in resolve() about the sentinel that would have "fixed" it by
# disabling the EXIST check.


def _resolvable_cites(src, doc, docdir):
    """Every citation in SRC that names an existing file and an in-range line."""
    out = []
    for m in CITE_RE.finditer(src):
        p, a = m.group("path"), m.group("a")
        if not a or p in PENDING or p in RETIRED or p in EXTERNAL:
            continue
        full = resolve(p, doc, docdir)
        if os.path.exists(full) and 1 <= int(a) <= nlines(full):
            out.append((m.group(0), p, int(a), full))
    return out


def _far_line(a, n):
    """A line number in a file of N lines that is unambiguously FAR from A.

    "Far" means further than the +/-NEAR window the QUOTE check searches, with
    room to spare.  Returns None when the file is too short for the move to
    prove anything -- in which case the caller tries another citation rather
    than running a control that could pass for the wrong reason.
    """
    if n > a + 3 * NEAR:
        return n
    if a > 3 * NEAR:
        return 1
    return None


def _natural_quote_line(src, doc, docdir):
    """A line already carrying a cite AND a quotation of that cite's file."""
    for line in src.split("\n"):
        if NOQUOTE in line:
            continue
        c = CITE_RE.search(line)
        if not c or not c.group("a"):
            continue
        spans, _ = backtick_spans(line)
        for t in spans:
            if len(t) < MIN_QUOTE or any(k in t for k in PROSE_MARK):
                continue
            if not any(ch in CODEISH for ch in t):
                continue
            if CITE_RE.fullmatch("`" + t + "`"):
                continue
            f = resolve(c.group("path"), doc, docdir)
            if not os.path.exists(f):
                continue
            srcl = readlines(f)
            a = int(c.group("a"))
            w = norm("\n".join(srcl[max(0, a - 1 - NEAR):a + NEAR]))
            if norm(t) in w and _far_line(a, nlines(f)) is not None:
                return (line, c.group(0), c.group("path"), a, f)
    return None


def _synthetic_quote_line(src, doc, docdir):
    """Build a cite+quotation line from a real cited file.

    Needed because a document whose citations all sit on their own lines --
    the normal shape of a list or a table -- gives the QUOTE check nothing to
    fire on, and so gave cases (3) and (4) nothing to perturb.  The quotation
    is a REAL line of a REALLY cited file, taken from inside the window the
    QUOTE check searches, so the synthetic line must pass before it is broken.
    """
    for (cite, path, a, full) in _resolvable_cites(src, doc, docdir):
        n = nlines(full)
        if _far_line(a, n) is None:
            continue
        srcl = readlines(full)
        # prefer the cited line itself, then its neighbours, in the same
        # window the QUOTE check uses
        order = [a] + [k for k in range(max(1, a - NEAR), min(n, a + NEAR) + 1)
                       if k != a]
        for k in order:
            t = norm(srcl[k - 1])
            if len(t) < MIN_QUOTE or "`" in t:
                continue
            if any(mark in t for mark in PROSE_MARK):
                continue
            if not any(ch in CODEISH for ch in t):
                continue
            if CITE_RE.fullmatch("`" + t + "`"):
                continue
            newcite = f"`{path}:{a}`"
            line = f"SELFTEST SYNTHETIC CITE LINE: {newcite} carries `{t}`."
            # The line must name exactly ONE file and carry no bare `:NNN`,
            # or it would trip AMBIG/ORPHAN instead of QUOTE and the control
            # would be "CAUGHT" for a reason that has nothing to do with the
            # perturbation.
            if len(CITE_RE.findall(line)) != 1 or CONT_RE.search(line):
                continue
            # NOTE the cite returned is the one that is IN the line, not the
            # `cite` this candidate came from: the source cite may be a RANGE
            # (`path:49-60`) while the line carries `path:49`, and case (3)
            # rewrites the line by string replacement.  Returning the wrong
            # one makes that replacement a silent no-op and the control
            # MISSES -- which is exactly what happened when this was written.
            return (line, newcite, path, a, full)
    return None


def _doc_counts(path, docdir):
    """(quote checks performed, failures) for one document — in process."""
    ck = Check()
    check_doc(path, ck, docdir)
    return ck.n_quote, len(ck.fail)


def selftest(doc):
    """Negative control: six deliberate perturbations, each must be caught."""
    ok = True
    # BEFORE the copy: resolve() must keep searching the REAL document's
    # directory, or the sibling-filename convention breaks in the temp tree.
    docdir = os.path.dirname(os.path.abspath(doc))
    tmp = tempfile.mkdtemp(prefix="spec_cites_")
    try:
        base = os.path.join(tmp, os.path.basename(doc))
        shutil.copy(doc, base)
        src = open(base).read()

        cites = _resolvable_cites(src, doc, docdir)
        if not cites:
            print("  *** no citation in this document names an existing file "
                  "with an in-range line — nothing to perturb ***")
            print("SELFTEST: FAIL")
            return 1
        cite, cpath, ca, _cfull = cites[0]

        cases = []

        # (1) a line number pushed past EOF.  Any cited file will do; it does
        # not have to be RTL, which is what the old regex demanded.
        cases.append(("line past EOF",
                      src.replace(cite, f"`{cpath}:999999`", 1)))

        # (2) a path that does not exist, with the same extension so it is
        # still a CITABLE path rather than one the checker ignores.
        ext = os.path.splitext(cpath)[1] or ".sv"
        cases.append(("nonexistent path",
                      src.replace(cite,
                                  f"`rtl/no_such_file_xyz{ext}:{ca}`", 1)))

        # (3) and (4) need a line carrying a cite AND a quotation of it.
        qm = _natural_quote_line(src, doc, docdir)
        synthetic = qm is None
        if synthetic:
            qm = _synthetic_quote_line(src, doc, docdir)
        if qm is None:
            print("  *** could not find OR synthesize a line carrying a cite "
                  "and a quotation — QUOTE controls cannot run ***")
            print("SELFTEST: FAIL")
            return 1
        line, qcite, qpath, a, qfull = qm

        if synthetic:
            # The synthetic line becomes part of the document under test.  It
            # must PASS on its own first: a mis-built quotation would make
            # cases (3) and (4) fail for the wrong reason and still print
            # CAUGHT, which is the "check that cannot fire" trap one level up.
            q_before, _ = _doc_counts(base, docdir)
            src = src + "\n\n" + line + "\n"
            probe = os.path.join(tmp, "synth_probe.md")
            open(probe, "w").write(src)
            print("  [synthesized a cite+quotation line: this document has "
                  "none of its own]")
            print(f"    {line}")
            q_after, nfail = _doc_counts(probe, docdir)
            # TWO preconditions, because "it passes" is not enough.  A quote
            # the gatherer silently ignores also passes, and then cases (3)
            # and (4) perturb something nothing checks and still print
            # CAUGHT.  So require the line to pass AND to have raised the
            # number of QUOTE checks performed.
            if nfail != 0:
                print("  *** the synthesized line does not itself pass — "
                      "the QUOTE controls below would be meaningless ***")
                run([probe], docdir)
                print("SELFTEST: FAIL")
                return 1
            if q_after <= q_before:
                print(f"  *** the synthesized quotation is not CHECKED "
                      f"(quote checks {q_before} -> {q_after}) — cases (3) "
                      f"and (4) would be vacuous ***")
                print("SELFTEST: FAIL")
                return 1
            print(f"    quote checks {q_before} -> {q_after}, document clean")

        far = _far_line(a, nlines(qfull))
        cases.append(("quotation moved away from its cite",
                      src.replace(line, line.replace(qcite, f"`{qpath}:{far}`"),
                                  1)))

        # (4) a fabricated quotation beside a real cite
        cases.append(("fabricated quotation",
                      src.replace(line,
                                  line + " `zz_fabricated_token = 12345;`", 1)))

        # (5) an ORPHAN: a bare continuation on a line naming no file.
        # Added after review found the ORPHAN branch was DEAD CODE -- it sat
        # behind `if not cites: continue`, and an orphan line produces no
        # cites by construction, so the check could never fire on the one
        # input it exists for.  This control is what makes that permanent.
        cases.append(("orphan continuation (no file on the line)",
                      src + "\n\nA line with a bare `:4242` and no path.\n"))

        # (6) an AMBIG: a bare continuation on a line naming TWO files.
        cases.append(("ambiguous continuation (two files on the line)",
                      src + "\n\nSee `ref/layer_ref.py:1` and "
                            "`ref/model_select.py:1` and also `:2`.\n"))

        for name, text in cases:
            p = os.path.join(tmp, "case.md")
            open(p, "w").write(text)
            rc = run([p], docdir)
            verdict = "CAUGHT" if rc == 1 else "*** MISSED ***"
            print(f"  negative control [{name}]: {verdict}\n")
            if rc != 1:
                ok = False

        print("  positive control [unperturbed document]:")
        rc = run([base], docdir)
        if rc != 0:
            print("  *** the unperturbed document does not pass ***")
            ok = False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("SELFTEST: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        sys.exit("usage: spec_cites.py <doc.md>… | --selftest [<doc.md>]")
    if args[0] == "--selftest":
        d = args[1] if len(args) > 1 else os.path.join(
            REPO, "docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md")
        sys.exit(selftest(d))
    sys.exit(run(args))
