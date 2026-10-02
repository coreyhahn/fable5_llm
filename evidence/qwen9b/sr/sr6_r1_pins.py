#!/usr/bin/env python3
"""sr6_r1_pins.py — Task SR6: generate the --seq-rtl r1 form-B per-image
reorder of chat_seq's two step images and print what sw/chat_seq.py pins
(REORDER_B_R1_IMAGES).  BOARD-FREE, read-only (stdout).

    FABLE5_MODEL=9b FABLE5_RS_F=7 /home/cah/.venv/bin/python \
        evidence/qwen9b/sr/sr6_r1_pins.py

The recipe of evidence/qwen9b/ov/s1p_formB_pins.py (n88), at rtl="r1": the
images are built exactly as a `--nch 4 --max-ctx 511` session builds them
(the shipped template's TurnCompiler, pos_mode auto -> ldc), then reordered
by sw/chat_seq.reorder_b_images(..., rtl="r1") — the function the session
calls — twice, to show the reorder is deterministic.  Also printed:

  * per image: the FENCE mask histogram, validation at {"R1"} and refusal
    at the empty set (build_041/042's set), the pass's hazard assert, and
    the STATIC model's makespan (program order -> the replay of the emitted
    order).  THIS lineage's makespan — NOT n120's 27,136,513, which is the
    CSV-costed model_9b_s1 template loop body (SR4 §4);
  * the r0 regeneration (the same function at its default) against the
    S1P pins REORDER_B_IMAGES: default behaviour byte-identical.
"""
import hashlib
import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                    ".."))
sys.path[:0] = [os.path.join(ROOT, "sw"), os.path.join(ROOT, "ref")]
import chat_seq as CS                                          # noqa: E402
import seq_format as SF                                        # noqa: E402


def main():
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
    ok = True
    shas = []
    for run in (1, 2):
        built = CS.reorder_b_images(sess.tc, sess.SCm, rtl="r1")
        shas.append({k: hashlib.sha256(v[0].data).hexdigest()
                     for k, v in built.items()})
        if run == 2:
            break
        for kind, (img, perm, rep) in built.items():
            s = rep["segments"][0]
            ship = sess.images[kind].a
            nr = SF.unpack_stream(img.data)
            print(f"--- r1 {kind}: {ship.nrec} -> {img.nrec} records; sha256 "
                  f"{hashlib.sha256(img.data).hexdigest()}")
            print(f"    rtl {rep['rtl']}; caps {rep['caps']}; FENCE masks "
                  f"{rep['fence_masks']}; refused at the empty set: "
                  f"{rep['refused_at_empty']}")
            print(f"    MOVX elided {s['movx_elided']}; fences {s['fences_in']}"
                  f" -> {s['fences_out']}; rule {s['rule']}; STATIC model: "
                  f"program order {s['orig_win']} cyc -> replay "
                  f"{s['replay_mk']} cyc (x{s['orig_win'] / s['replay_mk']:.4f}"
                  f"); postcheck {s['post_replay'][0]} edges, 0 violations; "
                  f"hazard {rep['hazard']}")
            n_r1 = SF.validate_stream(nr, caps={"R1"})
            try:
                SF.validate_stream(nr)
                at_empty = "ADMITTED"
                ok = False
            except SF.SeqValidationError as e:
                at_empty = f"REFUSED ({str(e)[:60]}...)"
            hz = RE.assert_no_pending_hazard(nr, f"r1 {kind}")
            print(f"    validate_stream at {{R1}}: {n_r1} records; at the "
                  f"empty set: {at_empty}; hazard assert (re-run here): {hz}")
            print(f"    head records 0..2 -> {[perm[i] for i in range(3)]}; "
                  f"position-LDC addr_lo byte offsets {list(ship.pos_ldc)} -> "
                  f"{list(img.pos_ldc)}")
            print("    at the new offsets: "
                  f"{[SF.OP_NAME[nr[o // 16].opcode] + ('/ind' if nr[o // 16].ind else '') for o in img.pos_ldc]}")
    det = shas[0] == shas[1]
    ok = ok and det
    print(f"=== deterministic: {'YES' if det else 'NO'}")
    # r0: the default, against the S1P pins
    b0 = CS.reorder_b_images(sess.tc, sess.SCm)
    for k in ("lite", "full"):
        got = hashlib.sha256(b0[k][0].data).hexdigest()
        pin, pn = CS.REORDER_B_IMAGES[k]
        same = got == pin and b0[k][0].nrec == pn
        ok = ok and same
        print(f"=== r0 {k} regenerated {got[:16]} ({b0[k][0].nrec}) vs S1P pin "
              f"{pin[:16]} ({pn}): {'IDENTICAL' if same else 'DIFFERENT'}")
    for k in ("lite", "full"):
        print(f"PIN r1 {k} {shas[0][k]} {len(built[k][0].data) // 16}")
    print("R1 PINS: " + ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
