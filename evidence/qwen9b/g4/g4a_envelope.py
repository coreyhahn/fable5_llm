#!/usr/bin/env python3
"""g4a_envelope.py — the OTHER half of G3.4's S9 proof: it must NOT fire.

G3.4 (Task 10) added the MVGO SHAPE `ng` envelope in three places at once —
`rtl/matvec_engine.sv`'s `MAX_NG`, `rtl/seq_unit.sv`'s E_ENV refusal, and
`ref/seq_format.validate`'s reference twin — and proved each one REFUSES an
out-of-envelope word.  A guard that only ever refuses is indistinguishable
from a guard that always refuses, so the complementary half is: on the real
9B stream, at the real 9B shapes, it accepts.  That can only be measured
where a 9B stream exists, which is here.

For each `<prefix>` (a `<prefix>.seq` + `<prefix>.seq.json` pair):

  DECLARED  the artifact's own `shape_isa` key — Task 11 is where the
            emitter starts writing it, so this is also the record that the
            key landed.
  HISTOGRAM every MVGO's SHAPE `ng`, decoded at the v2.0 layout
            {spare[31:29], ng[28:22], nrows[21:6], sh[5:0]}.  The
            interesting number is the MAXIMUM: at 9B `mlp.down` has
            K = 12,288, so `ng = K // 128 = 96` — EXACTLY `MAX_NG`.  The
            envelope is therefore exercised at its ceiling by this stream
            and not merely stepped around.
  GREEN     `validate_stream(recs, shape_isa=<the artifact's key>)`
            accepts the whole stream.
  RED       one MVGO's SHAPE is rewritten to `ng = MAX_NG + 1` in a COPY of
            the record list and the same call must refuse it, naming the
            envelope.  Without this the GREEN proves only that the clause
            was skipped.
  TIED      `ref/seq_format.MVGO_MAX_NG`, `sw/hwmap.SHAPE_MAX_NG[2]` and
            `rtl/matvec_engine.sv`'s `MAX_NG` are read out of their own
            sources and required equal (the same three-way tie
            `evidence/qwen9b/g3/isa_bits.py` enforces; re-read here so this
            log stands alone about WHICH bound it is talking about).

The RTL half of the non-firing proof is not here and cannot be: it is
`TB_SEQ_CHIP PASS` on a run whose final `STATUS[31:24]` err_code is 0
(`tb/tb_seq_chip.sv` fatals on any non-zero err_code, and E_ENV = 0x0D /
E_LAYEROP = 0x10 are the two the envelope reports through).

S3 EXTENDS IT TO SLD/SST (`--sdma`).  SEQ_ISA v2.1 B15.1 gives the two new
layer commands a field envelope of their own -- kind 3 reserved, layer and
head inside the kind's range, DN/CV head 0, ARG1/ARG2 zero -- checked in
`ref/seq_format.validate_stream` and in `rtl/layer_chan.sv`'s
`sdma_range_bad`.  The same two halves apply: on the real 9B stream every
SLD/SST field must be AT OR INSIDE its ceiling and accepted, and a forced
kind 3 must be REFUSED.  The census prints the per-field maxima beside the
ISA's bounds, so a reader sees which ones the schedule actually reaches.

Usage:  python3 evidence/qwen9b/g4/g4a_envelope.py [--sdma] <prefix> [...]
Exit 0 = PASS.
"""
import copy
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
import gen_layer_script as GLS                                 # noqa: E402
import hwmap as HW                                             # noqa: E402

bad = []


def note(s):
    print("  " + s)


def shape_ng(imm32):
    """SEQ_ISA v2.0 SHAPE: ng lives in bits [28:22] (rtl/seq_unit.sv)."""
    return (int(imm32) >> 22) & 0x7F


print("G4a MVGO SHAPE envelope — the non-firing half of G3.4's S9")

# ---- the bound, read out of all three sources ------------------------
rtl = open(os.path.join(TOP, "rtl/matvec_engine.sv")).read()
m = re.search(r"parameter\s+int\s+MAX_NG\s*=\s*(\d+)", rtl)
rtl_ng = int(m.group(1)) if m else None
tie = {"rtl/matvec_engine.sv": rtl_ng,
       "ref/seq_format.py": int(SF.MVGO_MAX_NG),
       "sw/hwmap.py": int(HW.SHAPE_MAX_NG[HW.SHAPE_ISA_9B])}
note("TIED      MAX_NG " + ", ".join(f"{k}={v}" for k, v in tie.items()))
if rtl_ng is None:
    bad.append("could not read MAX_NG out of rtl/matvec_engine.sv")
elif len(set(tie.values())) != 1:
    bad.append(f"the three MAX_NG statements disagree: {tie}")
MAX_NG = int(SF.MVGO_MAX_NG)

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
SDMA = "--sdma" in sys.argv[1:]

for prefix in ARGS:
    p = prefix if os.path.isabs(prefix) else os.path.join(TOP, prefix)
    if not os.path.exists(p + ".seq"):
        bad.append(f"ABSENT: {prefix}.seq (the 9B stream set is a build "
                   "product — `make -C tb w9_9b_model_script`)")
        note(f"ABSENT    {prefix}.seq")
        continue
    meta = json.load(open(p + ".seq.json"))
    recs = SF.unpack_stream(open(p + ".seq", "rb").read())
    mvgo = [r for r in recs if r.opcode == SF.OP_MVGO]
    print(f"\n{prefix}  ({len(recs)} records, {len(mvgo)} MVGO)")

    declared = meta.get("shape_isa")
    note(f"DECLARED  meta shape_isa = {declared!r}"
         + ("" if declared == SF.SHAPE_ISA_9B else
            "  <-- NOT the v2.0 layout this tree emits"))
    if declared != SF.SHAPE_ISA_9B:
        bad.append(f"{prefix}: meta does not declare shape_isa = "
                   f"{SF.SHAPE_ISA_9B}")

    hist = {}
    for r in mvgo:
        hist[shape_ng(r.imm32)] = hist.get(shape_ng(r.imm32), 0) + 1
    note("HISTOGRAM ng -> count  " + " ".join(f"{k}:{v}" for k, v
                                              in sorted(hist.items())))
    mx = max(hist) if hist else 0
    note(f"MAX       ng {mx} of MAX_NG {MAX_NG}"
         + ("  — EXACTLY at the ceiling" if mx == MAX_NG else
            f"  — {MAX_NG - mx} below the ceiling"))

    try:
        SF.validate_stream(recs, shape_isa=declared)
        note("GREEN     the whole stream validates under its own declared "
             "layout — the envelope does NOT fire")
    except SF.SeqValidationError as e:
        bad.append(f"{prefix}: GREEN failed — {e}")
        note(f"GREEN     FAILED: {e}")

    # ---- CENSUS (G4a fix round 1) -----------------------------------
    # Two things the gate had no record of, both one walk of the same
    # stream.
    #
    # DNSB: SEQ_ISA v2.0 writes the DeltaNet scalar-pointer base pair once
    # per DN LAYER BODY (`ref/seq_format.SeqEmitter.on_dnsb`).  The count is
    # per BODY PRESENT IN THE STREAM, not per step: a looped stream carries
    # `steps - loop_steps + 1` bodies, because the last `loop_steps` share
    # one.  24 per body is one per DeltaNet layer at the 9B geometry
    # (24 DN + 8 GQA).
    #
    # The 16-bit ARG: the whole reason this task could exist.  Under
    # SEQ_ISA v1.7 a scratch address had 15 bits and stopped at 32,767; a
    # 9B layer body peaks at 50,208.  MOVX / MOVY `addr_lo` is the
    # UNAMBIGUOUS witness -- for those opcodes the field IS the scratch
    # address.  The ARG1 / ARG2 rows decode every layer ARG word as if it
    # were an address pair (`enc_a1`) or an ALU dst (`enc_alu_a2`), which is
    # what the address-carrying commands pack, so they are UPPER BOUNDS:
    # an ARG1 belonging to a command that packs something else is counted
    # too.  Stated, not hidden -- the MOVX/MOVY row is the one that proves
    # the point on its own.
    nsteps = int(meta.get("steps") or 0)
    nloop = int(meta.get("loop_steps") or 0)
    bodies = (nsteps - nloop + 1) if nsteps else 0
    dnsb = sum(1 for r in recs
               if r.opcode == SF.OP_CSRWR and r.target == SF.CSR_L_DNSB)
    note(f"CENSUS    DNSB CSRWR {dnsb} in the stream; steps {nsteps}, "
         f"loop_steps {nloop} -> {bodies} body/bodies present"
         + (f", {dnsb / bodies:g} per body" if bodies else ""))
    cats = {}

    def bump(k, v):
        c = cats.setdefault(k, [0, 0, -1])
        c[0] += 1
        if v > 32767:
            c[1] += 1
        c[2] = max(c[2], v)

    for r in recs:
        if r.opcode == SF.OP_CSRWR and r.target == SF.CSR_L_ARG1:
            bump("ARG1 lo (as an addr pair)", GLS.dec_a1_lo(r.imm32))
            bump("ARG1 hi (as an addr pair)", GLS.dec_a1_hi(r.imm32))
        elif r.opcode == SF.OP_CSRWR and r.target == SF.CSR_L_ARG2:
            bump("ARG2 (as an ALU dst)", GLS.dec_alu_dst(r.imm32))
        elif r.opcode in (SF.OP_MOVX, SF.OP_MOVY):
            bump("MOVX/MOVY addr_lo", r.addr_lo)
    for k in sorted(cats):
        c_n, c_over, c_max = cats[k]          # NOT `mx`/`over`: those two
        note(f"CENSUS    {k:26s} n={c_n:<7d} "  # name the ng ceiling and the
             f"over 32767: {c_over:<6d} "       # RED's forced ng below
             f"max {c_max}")

    # ---- S3: the SLD/SST field envelope (SEQ_ISA v2.1 B15.1) ---------
    if SDMA:
        sd = []
        a0 = 0
        for r in recs:
            if r.opcode == SF.OP_CSRWR and r.target == SF.CSR_L_ARG0:
                a0 = r.imm32
            elif r.opcode == SF.OP_CMD and (r.imm32 & 0xFF) in (
                    SF.OP_L_SLD, SF.OP_L_SST):
                sd.append((r.imm32 & 0xFF, SF.sdma_fields(a0)))
        nsld = sum(1 for op, _f in sd if op == SF.OP_L_SLD)
        note(f"SDMA      {len(sd)} SLD/SST records ({nsld} SLD, "
             f"{len(sd) - nsld} SST)")
        if not sd:
            bad.append(f"{prefix}: no SLD/SST record — this stream is not "
                       f"SEQ_ISA v2.1 and the SDMA half is vacuous")
        else:
            per = {}
            for _op, (k, sl, ly, hd) in sd:
                q = per.setdefault(k, [0, -1, -1, -1])
                q[0] += 1
                q[1] = max(q[1], sl)
                q[2] = max(q[2], ly)
                q[3] = max(q[3], hd)
            for k in sorted(per):
                n_k, mx_sl, mx_ly, mx_hd = per[k]
                lmax = 7 if k == SF.SDMA_KIND_KV else 23
                hmax = {SF.SDMA_KIND_DN: 0, SF.SDMA_KIND_KV: 7,
                        SF.SDMA_KIND_CV: 0}[k]
                ok = (mx_sl <= 1 and mx_ly <= lmax and mx_hd <= hmax)
                note(f"SDMA      kind {SF.SDMA_KIND_NAME[k]:2s} n={n_k:<5d} "
                     f"slot max {mx_sl}/1  layer max {mx_ly}/{lmax}  "
                     f"head max {mx_hd}/{hmax}"
                     + ("" if ok else "   <-- OUTSIDE THE B15.1 CEILING"))
                if not ok:
                    bad.append(f"{prefix}: kind {k} field outside B15.1")
            # RED: one SLD forced to the reserved kind 3
            hurtd = copy.deepcopy(recs)
            ci = next(i for i, r in enumerate(hurtd)
                      if r.opcode == SF.OP_CMD
                      and (r.imm32 & 0xFF) in (SF.OP_L_SLD, SF.OP_L_SST))
            ai = max(i for i, r in enumerate(hurtd[:ci])
                     if r.opcode == SF.OP_CSRWR and r.target == SF.CSR_L_ARG0)
            hurtd[ai].imm32 = (hurtd[ai].imm32 | (3 << 11)) & 0xFFFFFFFF
            try:
                SF.validate_stream(hurtd, shape_isa=declared)
            except SF.SeqValidationError as e:
                note(f"SDMA RED  rec {ai} forced to kind 3 -> REFUSED: "
                     f"{str(e).split(';')[0].strip()}")
            else:
                bad.append(f"{prefix}: SDMA RED CONTROL FAILED — kind 3 was "
                           "accepted, so the SDMA GREEN proves nothing")

    if not mvgo:
        bad.append(f"{prefix}: no MVGO record, so the RED control is vacuous")
        continue
    hurt = copy.deepcopy(recs)
    idx = next(i for i, r in enumerate(hurt) if r.opcode == SF.OP_MVGO)
    over = MAX_NG + 1
    hurt[idx].imm32 = ((hurt[idx].imm32 & ~(0x7F << 22)) | (over << 22)) \
        & 0xFFFFFFFF
    try:
        SF.validate_stream(hurt, shape_isa=declared)
    except SF.SeqValidationError as e:
        note(f"RED       rec {idx} forced to ng={over} -> REFUSED: "
             f"{str(e).split(';')[0].strip()}")
    else:
        bad.append(f"{prefix}: RED CONTROL FAILED — ng={over} was accepted, "
                   "so the GREEN above proves nothing")

print("\nG4A_ENVELOPE: %s (%d problem(s))"
      % ("PASS" if not bad else "FAIL", len(bad)))
for b in bad:
    print("  ! " + b)
sys.exit(1 if bad else 0)
