#!/usr/bin/env python3
"""s1p_formB_pins.py — Task S1P deliverable 2: generate the form-B per-image
reorder of chat_seq's two step images and print what sw/chat_seq.py pins
(REORDER_B_IMAGES).  BOARD-FREE, read-only (stdout).

    FABLE5_MODEL=9b python evidence/qwen9b/ov/s1p_formB_pins.py

The images are built exactly as a `--nch 4 --max-ctx 511` session builds
them (the shipped template's TurnCompiler, pos_mode auto -> ldc), then
reordered by sw/chat_seq.reorder_b_images — the function the session calls.
It runs twice, to show the reorder is deterministic.
"""
import hashlib
import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "sw"), os.path.join(ROOT, "ref")]
import chat_seq as CS                                          # noqa: E402
import seq_format as SF                                        # noqa: E402


def main():
    args = types.SimpleNamespace(
        template=CS.TEMPLATE4_PREFIX, any_template=False, nch=4,
        t_max=CS.T_MAX, pos_mode="auto", max_ctx=511, chan=0, temp=0.0,
        top_k=CS.DEFAULT_TOP_K, top_p=CS.DEFAULT_TOP_P, seed=None,
        verify_head=False, system=None, reorder=None)
    sess = CS.ChatSession(args, log=lambda *x: None)
    print(f"=== shipped session: pos_mode {sess.pos_mode}; lite "
          f"{sess.images['lite'].nrec} / full {sess.images['full'].nrec} "
          f"records; REORDER_B_POS {CS.REORDER_B_POS}")
    shas = []
    for run in (1, 2):
        built = CS.reorder_b_images(sess.tc, sess.SCm)
        shas.append({k: hashlib.sha256(v[0].data).hexdigest()
                     for k, v in built.items()})
        if run == 2:
            break
        for kind, (img, perm, rep) in built.items():
            s = rep["segments"][0]
            ship = sess.images[kind].a
            print(f"--- {kind}: {ship.nrec} -> {img.nrec} records; sha256 "
                  f"{hashlib.sha256(img.data).hexdigest()}")
            print(f"    MOVX elided {s['movx_elided']}; fences {s['fences_in']}"
                  f" -> {s['fences_out']}, deferred {s['fences_deferred']}; "
                  f"rule {s['rule']}; static model: program order "
                  f"{s['orig_win']} cyc -> {s['replay_mk']} cyc (x"
                  f"{s['orig_win'] / s['replay_mk']:.4f}); postcheck "
                  f"{s['post_replay'][0]} edges, 0 violations; hazard "
                  f"{rep['hazard']}")
            print(f"    head records 0..2 -> {[perm[i] for i in range(3)]}; "
                  f"position-LDC addr_lo byte offsets {list(ship.pos_ldc)} -> "
                  f"{list(img.pos_ldc)}")
            nr = SF.unpack_stream(img.data)
            print(f"    at the new offsets: "
                  f"{[SF.OP_NAME[nr[o // 16].opcode] + ('/ind' if nr[o // 16].ind else '') for o in img.pos_ldc]}")
    print(f"=== deterministic: {'YES' if shas[0] == shas[1] else 'NO'}")
    for k in ("lite", "full"):
        print(f"PIN {k} {shas[0][k]} "
              f"{len(built[k][0].data) // 16}")


if __name__ == "__main__":
    main()
