#!/usr/bin/env python3
"""sr13b_r2_pins.py — Task SR13b: generate the --seq-rtl r2 form-B per-image
reorder of chat_seq's two step images and print what sw/chat_seq.py pins
(REORDER_B_R2_IMAGES).  BOARD-FREE, read-only (stdout).

    FABLE5_MODEL=9b FABLE5_RS_F=7 /home/cah/.venv/bin/python \
        evidence/qwen9b/sr/sr13b_r2_pins.py [--rtl r2|r3]

The recipe of evidence/qwen9b/sr/sr6_r1_pins.py (n601), at rtl="r2": the
images are built exactly as a `--nch 4 --max-ctx 511` session builds them
(the shipped template's TurnCompiler, pos_mode auto -> ldc), then reordered
by sw/chat_seq.reorder_b_images(..., rtl="r2") — the function the session
calls — twice, to show the reorder is deterministic.  reorder_e4 at r2 is
SR11b's pass (ref/scripts/reorder_e4.py, commits 0cf3f1f / e2095f6): r1's
per-channel-fence schedule on the depth-2 XWIN/RES buffers, bank-1 fields
(MOVX word 1536, MVGO XBANK/RBANK, MOVY row 2048).  Also printed:

  * per image: the FENCE mask histogram, the bank-field counts, validation
    at {R1, R2} and refusal at {R1} (build_044_r1_incr's set) and at the
    empty set (build_041/042's), the pass's hazard assert, and the STATIC
    model's makespan (program order -> the replay of the emitted order;
    THIS lineage's numbers, MODEL, position 0) plus the pass's corrected
    prediction (SR11b);
  * the r1 and r0 regenerations (the same function) against their pins
    REORDER_B_R1_IMAGES / REORDER_B_IMAGES: both byte-identical.

--rtl r3 (Task R3-6 of the R3 campaign; a flag, not a copy — the default r2
is today's run, byte for byte): the SAME recipe at rtl="r3" (R3-5's pass:
r2 plus the MOVX broadcast, B17.3), caps {R1, R2, R3}.  Each image must
validate at {R1, R2, R3} and be REFUSED at {R1, R2} (naming the BROADCAST),
at {R1} and at {}; the broadcast / forced / unicast-left counts are
printed; the r2, r1 and r0 regenerations are checked against their pins,
and the r2 images' STATIC model makespans (replay, corrected prediction,
position 0) are printed beside the r3 ones (the input R3-11's primary
prediction needs).  The PIN lines read `PIN r3 ...`.
"""
import argparse
import hashlib
import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                    ".."))
sys.path[:0] = [os.path.join(ROOT, "sw"), os.path.join(ROOT, "ref")]
import chat_seq as CS                                          # noqa: E402
import seq_format as SF                                        # noqa: E402

R12 = {"R1", "R2"}
# the lower sets an image of each level must be REFUSED at, in print order
LOWER = {"r2": ({"R1"}, frozenset()),
         "r3": (R12, {"R1"}, frozenset())}


def capstr(caps):
    return "{" + ",".join(sorted(caps)) + "}"


def nbank(recs):
    return sum(1 for r in recs
               if (r.opcode == SF.OP_MOVX and r.target)
               or (r.opcode == SF.OP_MOVY and r.target >> 4)
               or (r.opcode == SF.OP_MVGO and r.imm32
                   & (SF.SHAPE_XBANK | SF.SHAPE_RBANK)))


def refused(recs, caps):
    try:
        SF.validate_stream(recs, caps=caps, shape_isa=SF.SHAPE_ISA_9B)
        return "ADMITTED"
    except SF.SeqValidationError as e:
        return f"REFUSED ({str(e)[:70]}...)"


def refused_bcast(recs, caps):
    """r3: the refusal at `caps` must name the broadcast (not a bank
    field): its full message, shortened around the name."""
    try:
        SF.validate_stream(recs, caps=caps, shape_isa=SF.SHAPE_ISA_9B)
        return False, "ADMITTED"
    except SF.SeqValidationError as e:
        s = str(e)
        return "BROADCAST" in s, f"REFUSED ({s[:96]}...)"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rtl", choices=("r2", "r3"), default="r2",
                    help="the level to pin (default r2, SR13b's run)")
    rtl = ap.parse_args(argv).rtl
    assert CS.MODEL_TAG == "9b", CS.MODEL_TAG
    args = types.SimpleNamespace(
        template=CS.TEMPLATE4_PREFIX, any_template=False, nch=4,
        t_max=CS.T_MAX, pos_mode="auto", max_ctx=511, chan=0, temp=0.0,
        top_k=CS.DEFAULT_TOP_K, top_p=CS.DEFAULT_TOP_P, seed=None,
        verify_head=False, system=None, reorder=None, seq_rtl="r0")
    sess = CS.ChatSession(args, log=lambda *x: None)
    print(f"=== shipped session: pos_mode {sess.pos_mode}; lite "
          f"{sess.images['lite'].nrec} / full {sess.images['full'].nrec} "
          f"records; REORDER_B_POS {CS.REORDER_B_POS}")
    RE = CS._reorder_mod()
    caps_lvl = RE.CAPS_OF[rtl]
    ok = True
    shas = []
    built = None
    for run in (1, 2):
        built = CS.reorder_b_images(sess.tc, sess.SCm, rtl=rtl)
        shas.append({k: hashlib.sha256(v[0].data).hexdigest()
                     for k, v in built.items()})
        if run == 2:
            break
        for kind, (img, perm, rep) in built.items():
            s = rep["segments"][0]
            ship = sess.images[kind].a
            nr = SF.unpack_stream(img.data)
            print(f"--- {rtl} {kind}: {ship.nrec} -> {img.nrec} records; "
                  f"sha256 {hashlib.sha256(img.data).hexdigest()}")
            print(f"    rtl {rep['rtl']}; caps {rep['caps']}; FENCE masks "
                  f"{rep['fence_masks']}; bank fields {rep['bank_fields']} "
                  f"(per kind {s.get('banks')}); refused at {{R1}}: "
                  f"{rep['refused_at_r1']}; at the empty set: "
                  f"{rep['refused_at_empty']}")
            print(f"    MOVX elided {s['movx_elided']}; fences {s['fences_in']}"
                  f" -> {s['fences_out']}; rule {s['rule']}; STATIC model: "
                  f"program order {s['orig_win']} cyc -> replay "
                  f"{s['replay_mk']} cyc (x{s['orig_win'] / s['replay_mk']:.4f}"
                  f"); corrected prediction {s.get('pred_mk')} cyc; postcheck "
                  f"{s['post_replay'][0]} edges, 0 violations; hazard "
                  f"{rep['hazard']}")
            nlv = SF.validate_stream(nr, caps=caps_lvl,
                                     shape_isa=SF.SHAPE_ISA_9B)
            at1, at0 = refused(nr, {"R1"}), refused(nr, frozenset())
            ok = ok and at1.startswith("REFUSED") \
                and at0.startswith("REFUSED") and nbank(nr) > 0 \
                and nbank(nr) == rep["bank_fields"]
            hz = RE.assert_no_pending_hazard(nr, f"{rtl} {kind}")
            print(f"    validate_stream at {capstr(caps_lvl)} (isa=2): {nlv} "
                  f"records; at {{R1}}: {at1}; at {{}}: {at0}; bank fields "
                  f"re-counted {nbank(nr)}; hazard assert (re-run here): {hz}")
            if rtl == "r3":
                nbc = sum(1 for r in nr if r.opcode == SF.OP_MOVX
                          and r.chan == SF.MOVX_BCAST)
                good = nbc > 0 and nbc == rep["broadcasts"] \
                    and rep["refused_at_r1r2"]
                vv = []
                for lc in LOWER[rtl]:
                    b, t = refused_bcast(nr, lc)
                    good = good and b
                    vv.append(f"at {capstr(lc)}: {t}")
                ok = ok and good
                print(f"    r3: broadcasts {nbc} (pass report "
                      f"{rep['broadcasts']}; siblings merged "
                      f"{s['siblings_merged']}, FORCED {s['forced']}, "
                      f"unicast-left groups {s['unicast_left_groups']} (MOVX "
                      f"{s['unicast_left_movx']}); consumers asserted "
                      f"{s['bcast_consumers']}); refused at {{R1,R2}} (pass) "
                      f"{rep['refused_at_r1r2']}")
                print("    r3: every lower set refuses NAMING THE BROADCAST: "
                      + ("YES" if good else "NO") + "; " + "; ".join(vv))
            print(f"    head records 0..2 -> {[perm[i] for i in range(3)]}; "
                  f"position-LDC addr_lo byte offsets {list(ship.pos_ldc)} -> "
                  f"{list(img.pos_ldc)}")
            print("    at the new offsets: "
                  f"{[SF.OP_NAME[nr[o // 16].opcode] + ('/ind' if nr[o // 16].ind else '') for o in img.pos_ldc]}")
    det = shas[0] == shas[1]
    ok = ok and det
    print(f"=== deterministic: {'YES' if det else 'NO'}")
    for lvl in [x for x in ("r2", "r1", "r0") if x < rtl]:
        pins = CS.REORDER_B_PINS_BY_RTL[lvl][0]
        b = CS.reorder_b_images(sess.tc, sess.SCm,
                                **({} if lvl == "r0" else {"rtl": lvl}))
        for k in ("lite", "full"):
            got = hashlib.sha256(b[k][0].data).hexdigest()
            pin, pn = pins[k]
            same = got == pin and b[k][0].nrec == pn
            ok = ok and same
            print(f"=== {lvl} {k} regenerated {got[:16]} ({b[k][0].nrec}) vs "
                  f"pin {pin[:16]} ({pn}): "
                  f"{'IDENTICAL' if same else 'DIFFERENT'}")
            if rtl == "r3" and lvl == "r2":
                s2, s3 = b[k][2]["segments"][0], built[k][2]["segments"][0]
                print(f"=== STATIC model, position 0, {k}: r2 replay "
                      f"{s2['replay_mk']} cyc, corrected prediction "
                      f"{s2.get('pred_mk')} cyc; r3 replay {s3['replay_mk']} "
                      f"cyc, corrected prediction {s3.get('pred_mk')} cyc "
                      f"(MODEL)")
    for k in ("lite", "full"):
        print(f"PIN {rtl} {k} {shas[0][k]} {len(built[k][0].data) // 16}")
    print(f"{rtl.upper()} PINS: " + ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
