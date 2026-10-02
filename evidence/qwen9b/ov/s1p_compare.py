#!/usr/bin/env python3
"""s1p_compare.py — Task S1P deliverable 1: `reorder_e4 --cost static`
against `--cost csv` (the SV1/OV1 path), and on streams the CSV path cannot
cover.

    FABLE5_MODEL=9b python evidence/qwen9b/ov/s1p_compare.py

READ-ONLY (stdout only).  For model_9b_s1 (and model_9b_s2), forms B and A,
per decode segment:
  * MOVX elided (csv vs static);
  * the set of DEFERRED fences, each identified by the static pcs of the
    MVGOs it drains, csv vs static (equal / only-csv / only-static);
  * the modelled makespan: csv schedule at csv windows (= SV1's number),
    static schedule at static windows, and the static ORDER re-priced at the
    csv windows (so the two schedules are compared on the same costs);
  * the whole-run ms/token exactly as evidence/qwen9b/ov/sv1_derive.py
    forms its prediction (unrolled segments once, the body LOOP times, plus
    the launch cycles no window holds = today - the csv window sum);
  * the output stream sha256 of each path.
Then the chat step images (sw/chat_seq.py's shipped-template lite and full
images, emitter space, pos_mode ldc): the csv path must REFUSE them (no
template segment has their skeleton) and the static path must reorder them.
"""
import hashlib
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "ref", "scripts"))
sys.path.insert(0, os.path.join(REPO, "ref"))

import reorder_e4 as RE                  # noqa: E402
import seq_cost as SC                    # noqa: E402

SF, OC = RE.SF, RE.OC
W9 = os.path.join(REPO, "tb", "scripts", "w9")
TODAY = {1: 196706821, 2: 196707670}            # S4_REPLAY.md:398-399 (T)
LOOP = {1: 3, 2: 5}                             # sv1_derive.py LOOP (T)
NTOK = 6
OV1 = {"B": 114.438, "A": 117.935}              # n66:31/:41 (s1, D)


def ms(c):
    return c / 250e6 * 1e3


def fence_sets(S, order):
    """[(frozenset of drained MVGO pcs, deferred?)] per emitted FENCE."""
    nodes = S["nodes"]
    out = []
    unf = []
    seen_mvgo, gap = False, 0
    for x in order:
        if x == "FENCE":
            out.append((frozenset(nodes[m].pc for m in unf),
                        bool(seen_mvgo and gap)))
            unf = []
            seen_mvgo, gap = False, 0
        elif nodes[x].kind == "mvgo":
            unf.append(x)
            seen_mvgo, gap = True, 0
        elif seen_mvgo:
            gap += 1
    return out


def load(stem):
    p = os.path.join(W9, stem + ".e4")
    stream = open(p + ".seq", "rb").read()
    import json
    meta = json.load(open(p + ".seq.json"))
    sha = hashlib.sha256(stream).hexdigest()
    assert sha == meta["stream_sha256"], "stream sha mismatch"
    print(f"=== {stem}.e4.seq sha256 {sha[:16]} MATCH its manifest, "
          f"{len(stream) // 16} records")
    return SF.unpack_stream(stream), meta


def per_segment(recs, rows_c, rows_s, form):
    _pro, segs, _h = RE.segments(recs)
    res = []
    for k, (lo, hi, body) in enumerate(segs):
        Sc = RE.schedule_segment(recs, lo, hi, rows_c(k, lo, hi), form)
        oc = RE.order_and_fences(Sc)
        Ss = RE.schedule_segment(recs, lo, hi, rows_s(k, lo, hi), form)
        os_ = RE.order_and_fences(Ss)
        mc, _pc, _ = RE.replay(Sc, oc)
        ms_, _ps, _ = RE.replay(Ss, os_)
        mx, px, _ = RE.replay(Sc, os_)        # static order at csv costs
        fc, fs = fence_sets(Sc, oc), fence_sets(Ss, os_)
        dc = {f for f, d in fc if d}
        ds = {f for f, d in fs if d}
        res.append({"k": k, "lo": lo, "hi": hi, "body": body,
                    "red_c": Sc["nred"], "red_s": Ss["nred"],
                    "nf_c": len(fc), "nf_s": len(fs),
                    "def_c": len(dc), "def_s": len(ds),
                    "def_both": len(dc & ds), "def_only_c": len(dc - ds),
                    "def_only_s": len(ds - dc),
                    "all_same_fences": {f for f, _ in fc} == {f for f, _ in fs},
                    "orig_c": Sc["orig_win"], "orig_s": Ss["orig_win"],
                    "mk_c": mc, "mk_s": ms_, "mk_x": mx, "post_x": px,
                    "same_order": oc == os_})
    return res


def whole(res, seed, key):
    """sv1_derive's whole-run form: unrolled once, body LOOP times, plus the
    launch cycles no window holds (today - the CSV window sum)."""
    L = LOOP[seed]
    orig = sum(r["orig_c"] for r in res[:-1]) + L * res[-1]["orig_c"]
    new = sum(r[key] for r in res[:-1]) + L * res[-1][key]
    over = TODAY[seed] - orig
    return new + over, over


def compare(stem, seed):
    recs, meta = load(stem)
    W = RE.Windows()
    rows_c = W.rows_for(recs)
    rows_s = SC.rows_for(recs, 0)
    for form in ("B", "A"):
        t0 = time.monotonic()
        res = per_segment(recs, rows_c, rows_s, form)
        print(f"\n=== {stem} form {form}  (per segment; csv | static)")
        for r in res:
            print(f"  seg {r['k']} {r['lo']}..{r['hi']}"
                  f"{' BODY' if r['body'] else ''}: MOVX elided "
                  f"{r['red_c']} | {r['red_s']};  fences {r['nf_c']} | "
                  f"{r['nf_s']} (same drained sets: {r['all_same_fences']});"
                  f"  DEFERRED {r['def_c']} | {r['def_s']} (both "
                  f"{r['def_both']}, only csv {r['def_only_c']}, only static "
                  f"{r['def_only_s']});  same emitted order: {r['same_order']}")
            print(f"      makespan: csv {r['mk_c']} cyc = {ms(r['mk_c']):.3f} ms"
                  f" | static {r['mk_s']} = {ms(r['mk_s']):.3f} ms "
                  f"({100.0 * (r['mk_s'] - r['mk_c']) / r['mk_c']:+.3f} %)"
                  f" | static ORDER at csv costs {r['mk_x']} = "
                  f"{ms(r['mk_x']):.3f} ms "
                  f"({100.0 * (r['mk_x'] - r['mk_c']) / r['mk_c']:+.3f} %; "
                  f"postcheck {r['post_x'][0]} edges, 0 violations);  "
                  f"program order csv {r['orig_c']} static {r['orig_s']}")
        pc, over = whole(res, seed, "mk_c")
        ps, _ = whole(res, seed, "mk_s")
        px, _ = whole(res, seed, "mk_x")
        print(f"  WHOLE RUN (x{LOOP[seed]} body, outside {over} cyc): csv "
              f"{pc} cyc = {ms(pc) / NTOK:.3f} ms/token | static "
              f"{ps} = {ms(ps) / NTOK:.3f} ms/token "
              f"({100.0 * (ps - pc) / pc:+.3f} %) | static order at csv "
              f"costs {px} = {ms(px) / NTOK:.3f} ms/token "
              f"({100.0 * (px - pc) / pc:+.3f} %)")
        if seed == 1:
            print(f"  vs the committed SV1 prediction {OV1[form]} ms/token: "
                  f"static {ms(ps) / NTOK - OV1[form]:+.3f} ms "
                  f"({100.0 * (ms(ps) / NTOK - OV1[form]) / OV1[form]:+.3f} %)"
                  f"; static order at csv costs "
                  f"{100.0 * (ms(px) / NTOK - OV1[form]) / OV1[form]:+.3f} %")
        tot = {k: sum(r[k] for r in res) for k in
               ("red_c", "red_s", "def_c", "def_s", "def_both",
                "def_only_c", "def_only_s")}
        print(f"  totals over {len(res)} segments: MOVX elided {tot['red_c']}"
              f" | {tot['red_s']};  deferred {tot['def_c']} | {tot['def_s']}"
              f" (both {tot['def_both']}, only csv {tot['def_only_c']}, only "
              f"static {tot['def_only_s']})")
        outs = {}
        for cost, f in (("csv", rows_c), ("static", rows_s)):
            new, _cps, rep = RE.reorder(recs, f, form,
                                        meta.get("checkpoints", []))
            outs[cost] = hashlib.sha256(SF.pack_stream(new)).hexdigest()
            print(f"  whole-stream reorder, cost {cost}: {len(new)} records, "
                  f"sha256 {outs[cost][:16]}, hazard assert PASS "
                  f"{rep['hazard']}")
        print(f"  output streams {'IDENTICAL' if outs['csv'] == outs['static'] else 'DIFFER'}"
              f" ({time.monotonic() - t0:.0f} s)")
        # fix round 1 (M3): the FULL sha256 against the committed pins
        pin = pinned_sha(stem, form)
        ok = outs["csv"] == outs["static"] == pin
        print(f"  PIN {stem}_reord{form}: {pin}  csv == static == pin: "
              f"{'PASS' if ok else 'FAIL'}")
        assert ok, f"{stem} form {form}: {outs} vs pin {pin}"


def pinned_sha(stem, form):
    """The stream_sha256 of the committed SV1 reordered artifact's manifest;
    for s1 form A also sw/chat_seq.REORDER4_BY_FORM's pin (must agree)."""
    import json
    p = os.path.join(W9, f"{stem}_reord{form}.e4.seq.json")
    sha = json.load(open(p))["stream_sha256"]
    if stem == "model_9b_s1" and form == "A":
        sys.path.insert(0, os.path.join(REPO, "sw"))
        import chat_seq as CS
        assert CS.REORDER4_BY_FORM["A"][1] == sha, "chat_seq A pin != manifest"
    return sha


def chat_images():
    """The chat step images: csv must refuse them, static must reorder."""
    sys.path.insert(0, os.path.join(REPO, "sw"))
    import json
    import chat_seq as CS
    pre = CS.TEMPLATE4_PREFIX
    recs = SF.unpack_stream(open(pre + ".seq", "rb").read())
    meta = json.load(open(pre + ".seq.json"))
    g = CS.derive_geometry(recs, meta)
    m = CS.seq_chat_for(g)
    tc = m.TurnCompiler(pre, t_max=512, pos_mode="ldc", verify_sha=False)
    print("\n=== chat step images (shipped template, pos_mode ldc, emitter "
          "space)")
    for kind in ("lite", "full"):
        im = tc.build_step(0, 0, kind)
        irecs = SF.unpack_stream(im.data)
        try:
            RE.reorder(irecs, RE.Windows().rows_for(irecs), "B", [])
            print(f"  {kind}: csv path REORDERED it (unexpected)")
        except AssertionError as e:
            print(f"  {kind} ({len(irecs)} records): csv path REFUSES — "
                  f"{type(e).__name__}: {e}")
        for form in ("B", "A"):
            new, _c, rep = RE.reorder(irecs, SC.rows_for(irecs, 0), form, [])
            s = rep["segments"][0]
            print(f"  {kind} form {form}: static path reorders it — "
                  f"{len(new)} records, MOVX elided {s['movx_elided']}, "
                  f"fences {s['fences_out']} deferred {s['fences_deferred']}, "
                  f"program order {s['orig_win']} cyc = "
                  f"{ms(s['orig_win']):.3f} ms -> {s['replay_mk']} = "
                  f"{ms(s['replay_mk']):.3f} ms (x"
                  f"{s['orig_win'] / s['replay_mk']:.4f}); hazard PASS")


def main():
    compare("model_9b_s1", 1)
    compare("model_9b_s2", 2)
    chat_images()
    print("\nS1P_COMPARE: DONE")


if __name__ == "__main__":
    main()
