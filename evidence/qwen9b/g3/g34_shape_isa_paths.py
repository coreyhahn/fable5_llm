#!/usr/bin/env python3
"""g34_shape_isa_paths.py — G3.4 fix round 2: who states the SHAPE LAYOUT.

`ref/seq_format.validate` gained a `shape_isa` keyword at fix round 1, and
the MVGO `ng` envelope fires only under `SHAPE_ISA_9B`.  The question this
script answers, on a REAL frozen artifact rather than on synthetic records
(`evidence/qwen9b/g3/isa_bits.py` does those), is WHO gets to state the
layout — because round 1's board-free failure and round 2's first cut were
the same mistake twice: a CALLER asserting a layout that belongs to the
ARTIFACT.

The rule this round settles on: **a tool that LOADS a stream takes the
layout from the artifact's own seq metadata; a tool that BUILDS one states
it.**  Three loaders (`ref/seq_chat.Templates`, `ref/seq_model.gate`,
`tb/scripts/gen_seq_chip_vectors`) and one builder
(`tb/scripts/gen_seq_unit_vectors`).

Four checks, two of them negative controls:

  1  GREEN   the frozen build_034/build_035 template validates when the
             layout comes from its meta (which declares none, so the
             envelope stays off) — this is what the board-free gate needs.
  2  RED     the SAME stream is REFUSED when isa=2 is stated for it.  That
             is the form round 2's first cut put in
             `gen_seq_chip_vectors.py`, and it is why that form is gone.
  3  ARMING  inject `shape_isa: 2` into a COPY of the meta and the same
             stream is refused — so the check turns itself on the moment an
             emitter writes the key, with no edit to any of the three
             loaders.  (No emitter writes it yet: that is the declared gap,
             Task 11's file — see G3_4_LAYER.md 16.5.)
  4  SITES   each of the three loaders is read out of its own source and
             required to take `shape_isa` from the artifact.

The 9B EMIT path is not left unchecked by any of this: `sw/hwmap.shape_word`
asserts `1 <= ng <= SHAPE_MAX_NG[isa]` for EVERY word it packs, in both
layouts, so a stream this tree emits cannot carry an out-of-envelope `ng` in
the first place.  Check 5 states that too, from hwmap's own source.

Usage:  python3 evidence/qwen9b/g3/g34_shape_isa_paths.py
Exit 0 = PASS, 1 = a check failed, **2 = NO_ARTIFACT**: `tb/scripts/w3` is a
build product and is not tracked, so in a fresh checkout the GREEN / RED /
ARMING evidence cannot run — and a run that could not gather its evidence
reports `SHAPE_ISA_PATHS: NO_ARTIFACT` and exits non-zero.  It never prints
PASS.  Regenerate with `make -C tb seq_chip_scripts`.
"""
import glob
import json
import os
import re
import sys

TOP = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", ".."))
for _p in ("ref", "sw"):
    _q = os.path.join(TOP, _p)
    if _q not in sys.path:
        sys.path.insert(0, _q)

import seq_format as SF                                        # noqa: E402

# BOTH frozen artifacts, because the two refusals carry DIFFERENT record
# numbers and a claim that names one without naming the artifact is an
# overclaim (G3.4 fix round 3, m5): lay_s1.e refuses at rec 108, tok2_s1.e
# -- which is `tb/Makefile`'s default SEQP, i.e. what
# `make -C tb seq_chip_vectors` would actually have hit -- at rec 112.
ARTS = [os.path.join(TOP, "tb/scripts/w3/lay_s1.e"),
        os.path.join(TOP, "tb/scripts/w3/tok2_s1.e")]
bad = []


def note(s):
    print("  " + s)


print("G3.4 SHAPE-layout paths — who states isa, and on whose authority")

# A MISSING ARTIFACT IS A FAILURE, NOT A PASS (G3.4 fix round 3, m6).
# tb/scripts/w3 is a build product, so in a fresh checkout the GREEN / RED /
# ARMING evidence simply is not there -- and evidence that is not there must
# not print PASS.  The first cut exited 0 with "[artifact checks SKIPPED]",
# which is the same defect class as a row claiming "class A clean" over a
# FAIL log: a reader sees the marker, not the caveat.
missing = [a for a in ARTS if not os.path.exists(a + ".seq")]
for a in missing:
    note("ABSENT: %s.seq (tb/scripts/w3 is a build product; run "
         "`make -C tb seq_chip_scripts` to regenerate it)"
         % os.path.relpath(a, TOP))
for ART in [a for a in ARTS if a not in missing]:
    meta = json.load(open(ART + ".seq.json"))
    recs = SF.unpack_stream(open(ART + ".seq", "rb").read())
    note("artifact  %s  (%d records), meta declares shape_isa = %r"
         % (os.path.relpath(ART, TOP), len(recs), meta.get("shape_isa")))

    # 1 GREEN — the layout comes from the artifact, which declares none
    try:
        SF.validate_stream(recs, shape_isa=meta.get("shape_isa"))
        note("1 GREEN   meta-driven      -> ACCEPTED (frozen isa=1 stream, "
             "envelope off)")
    except SF.SeqValidationError as e:
        bad.append("meta-driven validation REFUSED %s: %s" % (ART, e))

    # 2 RED — the form round 2's first cut shipped in gen_seq_chip_vectors
    try:
        SF.validate_stream(recs, shape_isa=SF.SHAPE_ISA_9B)
    except SF.SeqValidationError as e:
        note("2 RED     stated isa=2     -> REFUSED: %s"
             % str(e).split(";")[0].strip())
    else:
        bad.append("RED CONTROL FAILED on %s: an isa=1 stream passed the "
                   "isa=2 envelope, so check 1 proves nothing" % ART)

    # 3 ARMING — the key, and only the key, turns the check on
    armed = dict(meta)
    armed["shape_isa"] = SF.SHAPE_ISA_9B
    try:
        SF.validate_stream(recs, shape_isa=armed.get("shape_isa"))
    except SF.SeqValidationError:
        note("3 ARMING  meta says isa=2  -> REFUSED (the check arms itself "
             "when an artifact declares the layout)")
    else:
        bad.append("a meta declaring shape_isa=2 did NOT arm the envelope")

# 4 SITES — read each loader out of its own source
SITES = [
    ("ref/seq_chat.py",
     r'self\.shape_isa = self\.meta\.get\("shape_isa"\)'),
    ("ref/seq_model.py",
     r'SF\.validate_stream\(recs, shape_isa=meta\.get\("shape_isa"\)\)'),
    ("tb/scripts/gen_seq_chip_vectors.py",
     r'SF\.validate_stream\(recs, shape_isa=meta\.get\("shape_isa"\)\)'),
]
for path, pat in SITES:
    src = open(os.path.join(TOP, path)).read()
    n = len(re.findall(pat, src))
    if n < 1:
        bad.append("%s does not take shape_isa from the artifact" % path)
    else:
        note("4 SITE    %-34s %d site(s) take the layout from the artifact"
             % (path, n))
BUILDER = ("tb/scripts/gen_seq_unit_vectors.py",
           r'SF\.validate_stream\(recs, shape_isa=SF\.SHAPE_ISA_9B\)')
src = open(os.path.join(TOP, BUILDER[0])).read()
if not re.search(BUILDER[1], src):
    bad.append("%s no longer STATES the 9B layout on the streams it builds"
               % BUILDER[0])
else:
    note("4 SITE    %-34s STATES isa=2 (it builds the stream in memory)"
         % BUILDER[0])

# 5 the emit path is checked unconditionally, at the packer
hw = open(os.path.join(TOP, "sw/hwmap.py")).read()
if not re.search(r"assert 1 <= ng <= SHAPE_MAX_NG\[isa\]", hw):
    bad.append("sw/hwmap.shape_word no longer asserts the ng envelope, so "
               "the EMIT path is unchecked and the declared gap is real")
else:
    note("5 EMIT     sw/hwmap.shape_word asserts 1 <= ng <= SHAPE_MAX_NG[isa] "
         "for every word it packs")

# the declared gap, stated as a measurement rather than a claim
metas = sorted(glob.glob(os.path.join(TOP, "tb/scripts/w*/*.seq.json")))
declaring = [p for p in metas if "shape_isa" in open(p).read()]
note("GAP       %d of %d artifact metas declare shape_isa (no emitter writes "
     "it yet — Task 11)" % (len(declaring), len(metas)))

if missing:
    # Distinct marker, distinct exit code: this is NOT a pass and it is NOT
    # the same thing as a check that ran and failed.
    print("SHAPE_ISA_PATHS: NO_ARTIFACT — %d of %d frozen artifact(s) absent, "
          "so the GREEN/RED/ARMING evidence did not run (%d other problem(s))"
          % (len(missing), len(ARTS), len(bad)))
    for b in bad:
        print("  ! " + b)
    sys.exit(2)
print("SHAPE_ISA_PATHS: %s (%d problem(s))"
      % ("PASS" if not bad else "FAIL", len(bad)))
for b in bad:
    print("  ! " + b)
sys.exit(1 if bad else 0)
