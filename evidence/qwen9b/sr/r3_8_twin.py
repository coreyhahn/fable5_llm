#!/usr/bin/env python3
"""r3_8_twin.py — Task R3-8 Step 5b: the unit-vector generator's executor
(tb/scripts/gen_seq_unit_vectors.py, R3 block) against ref/seq_model.py's
(R3-3's _movx_bcast), on every broadcast vector R3-8 emits.

New file (a flag on an existing tool would not do): no tool compares the two
executors; this is the twin cross-check plan review I-2 asked for.

For each seed 1..4, build_bcast's stream (the generator's own builder, the
same rng seed main_r3 uses) runs through
  * the generator's Model (the stub-side golden of tb_seq_unit), and
  * ref/seq_model.SeqExec at caps {R1,R2,R3} on the stream's DATA-MOVEMENT
    records — its LDC (rebased to SF.SEQ_DATA_BASE) and every MOVX, unicast
    and broadcast, in order.  MVGO / MOVY / FENCE are left out: the stub's
    matvec is not the model's (the generator says so in its docstring), and
    the model's MVGO needs weight images.  The per-destination running rule
    is therefore not exercised on the model side here (R3-3's own TDD did);
    the generator's twin of it runs in the full Model.
Scratch mapping: the RTL (and the generator's packer) moves the LOW BYTE of
each 16-bit scratch word (m_axib_rdata[7:0]); the model's scratch is
int8-packed by contract.  So the model's blob is the generator's with every
int16 word replaced by its sign-extended low byte — the same bytes move.
Compared, word for word:
  1. every channel's XWIN image, 4 x 3072 words (a word neither wrote = 0),
     and the count of words the generator wrote;
  2. the LDC'd scratch the MOVXs read (words 0..8191, low byte);
  3. XPTR: the set of channels whose XPTR a unicast zeroed (the generator's
     .wtr XPTR writes vs the model's ex.xptr) — a broadcast writes none;
  4. the admission twins: bcast_mvgo / movx_chan5 / bcast_range — the
     generator Model's (err, pc) against ref/seq_format.validate_stream's
     refusal at caps {R1,R2,R3} (record index and class); and build_bcast at
     caps {R1,R2} — refused by the validator, err 0x05 at the first
     broadcast in the generator Model (the pre-R3 bitstream's fault).
Prints TWIN PASS/FAIL per item and a summary; exit 1 on any FAIL.
Run ON SNOKE through sr_run.sh with FABLE5_MODEL=9b FABLE5_RS_F=7.
"""
import importlib.util
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
GEN = os.path.join(ROOT, "tb", "scripts", "gen_seq_unit_vectors.py")
spec = importlib.util.spec_from_file_location("gen_suv", GEN)
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)          # puts ref/ and sw/ on sys.path
import seq_format as SF              # noqa: E402
import seq_model as SM               # noqa: E402

CAPS3 = frozenset({"R1", "R2", "R3"})
nfail = 0


def verdict(ok, what):
    global nfail
    print(f"TWIN {'PASS' if ok else 'FAIL'}: {what}")
    if not ok:
        nfail += 1


def int8_blob(blob):
    w = np.frombuffer(blob, dtype="<i2").astype(np.int64)
    lo = w & 0xFF
    return np.where(lo >= 128, lo - 256, lo).astype("<i2").tobytes()


def model_words(ex, c):
    m = ex.xwin.mem.get(c)
    if m is None:
        return [0] * SF.XWIN_WORDS
    b = (np.asarray(m, dtype=np.int64) & 0xFF).reshape(-1, 4)
    return [int(x) for x in (b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
                             | (b[:, 3] << 24))]


def twin_seed(seed):
    recs, blob, emb = G.build_bcast(np.random.default_rng(9600 + seed), seed)
    gm = G.Model(blob, emb)
    gm.run(recs)
    verdict(gm.err == 0, f"seed {seed}: generator Model ran the stream "
            f"(err {gm.err:#04x}, pc {gm.pc})")
    img = G._xwin_img(gm)
    # the model: LDC (rebased) + every MOVX, then HALT
    sub = []
    for r in recs:
        if r.opcode == SF.EXT_LDC:
            sub.append(SF.Rec(SF.EXT_LDC, r.flags, r.target, r.imm32,
                              SF.SEQ_DATA_BASE & 0xFFFFFFFF,
                              SF.SEQ_DATA_BASE >> 32))
        elif r.opcode == SF.OP_MOVX:
            sub.append(r)
    sub.append(SF.Rec(SF.OP_HALT, 0, 0, 0, 0, 0))
    ex = SM.SeqExec(sub, int8_blob(blob), None, caps=CAPS3)
    ex.run()
    nb = sum(1 for r in sub if r.opcode == SF.OP_MOVX
             and r.chan == SF.MOVX_BCAST)
    nu = sum(1 for r in sub if r.opcode == SF.OP_MOVX
             and r.chan != SF.MOVX_BCAST)
    nwr, bad = 0, []
    for c in range(4):
        mw = model_words(ex, c)
        for w in range(SF.XWIN_WORDS):
            g = img[c][w]
            if g is not None:
                nwr += 1
            if (g or 0) != mw[w]:
                bad.append((c, w, g, mw[w]))
    verdict(not bad, f"seed {seed}: XWIN images, 4 x {SF.XWIN_WORDS} words "
            f"({nwr} written by {nb} broadcasts + {nu} unicast MOVX): "
            f"{len(bad)} differ" + (f", first {bad[:3]}" if bad else ""))
    gs = [(int(v) & 0xFF) for v in gm.mem[0:8192]]
    ms = [(int(v) & 0xFF) for v in ex.M.mem[0:8192]]
    nd = sum(1 for a, b in zip(gs, ms) if a != b)
    verdict(nd == 0, f"seed {seed}: the LDC'd scratch the MOVXs read, words "
            f"0..8191 (low byte): {nd} differ")
    gx = sorted({(a >> 12) - 1 for (a, d) in gm.wtr
                 if (a & 0xFFF) == G.MV_XPTR and 0x1000 <= a < 0x5000})
    mx = sorted(ex.xptr)
    verdict(gx == mx, f"seed {seed}: XPTR zeroed on channels {gx} "
            f"(generator .wtr) vs {mx} (model) — broadcasts write none")
    return nwr


def twin_errs():
    _b, eb, ee = G.build_bcast(np.random.default_rng(9601), 1)
    for nm, (er, code) in G.build_errs_r3().items():
        gm = G.Model(eb, ee)
        gm.run(er)
        try:
            SF.validate_stream(er, shape_isa=SF.SHAPE_ISA_9B, caps=CAPS3)
            vmsg, vok = "ADMITTED", False
        except SF.SeqValidationError as e:
            vmsg, vok = str(e).splitlines()[0][:140], True
        pc_ok = gm.pc == len(er) - 2
        verdict(gm.err == code and pc_ok and vok,
                f"{nm}: generator err {gm.err:#04x} at pc {gm.pc} (want "
                f"{code:#04x} at {len(er) - 2}); ref validator: {vmsg}")
    recs, blob, emb = G.build_bcast(np.random.default_rng(9601), 1)
    gm = G.Model(blob, emb)
    gm.caps = frozenset({"R1", "R2"})
    gm.run(recs)
    first = next(i for i, r in enumerate(recs) if r.opcode == SF.OP_MOVX
                 and r.chan == SF.MOVX_BCAST)
    try:
        SF.validate_stream(recs, shape_isa=SF.SHAPE_ISA_9B,
                           caps=frozenset({"R1", "R2"}))
        vmsg, vok = "ADMITTED", False
    except SF.SeqValidationError as e:
        vmsg, vok = str(e).splitlines()[0][:160], "R3" in str(e)
    verdict(gm.err == 0x05 and gm.pc == first and vok,
            f"build_bcast at caps {{R1,R2}}: generator err {gm.err:#04x} at pc "
            f"{gm.pc} (want 0x05 at the first broadcast, {first}); ref "
            f"validator: {vmsg}")


def main():
    tot = 0
    for seed in (1, 2, 3, 4):
        tot += twin_seed(seed)
    twin_errs()
    print(f"TWIN SUMMARY: {tot} XWIN words compared-as-written over 4 seeds; "
          f"{nfail} FAIL")
    sys.exit(1 if nfail else 0)


if __name__ == "__main__":
    main()
