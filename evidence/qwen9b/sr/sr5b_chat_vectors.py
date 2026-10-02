#!/usr/bin/env python3
"""sr5b_chat_vectors.py — Task SR5b (the r1 chat-image rung): multi-launch
chip-TB vectors of the chat tool's OWN step images, shipped order AND the r1
form-B per-image order (`--seq-rtl r1 --reorder B`: masked FENCEs, the
images SR6 pinned in sw/chat_seq.py REORDER_B_R1_IMAGES), for one chat
scenario.  BOARD-FREE.  Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh:

    FABLE5_MODEL=9b FABLE5_RS_F=7 python evidence/qwen9b/sr/sr5b_chat_vectors.py \
        <tag> --toks T0 T1 T2 --far-pos P

A COPY of evidence/qwen9b/ov/s1t_chat_vectors.py (Task S1T), changed only
where r1 needs it:
  * the second side is ("r1", reorder "B", seq_rtl "r1"): ChatSession's
    `_reorder_images_b` then builds the r1 images and REFUSES unless they
    regenerate equal to REORDER_B_R1_IMAGES (asserted again here);
  * the golden executor runs at the side's capability set
    (`SeqExec(..., caps=sess.level_caps)`: {"R1"} on the r1 side, empty on
    the shipped side), as the r1 images need (SEQ_ISA v2.3 B17.0);
  * files are tb/scripts/w9/sr5b_<tag>_{ship,r1}.e4.*; the shipped side is
    additionally compared byte for byte with S1T's shipped vectors
    tb/scripts/w9/s1t_<tag>_ship.e4.* when they exist (same scenario tag,
    same generator: they must be identical).
R3-9b addition, `--seq-rtl LEVEL` (default r1 = every committed SR5b use
unchanged; "flags, not copies", plan review I-5): the reordered side is built
at that chat level instead (form B, `--seq-rtl r3`: the pins are
chat_seq.REORDER_B_PINS_BY_RTL[LEVEL], the golden executor's caps
chat_seq.seq_rtl_caps(LEVEL) = {R1, R2, R3}); the side is named after the
level and, above r1, the files are tb/scripts/w9/sr5b<level>_<tag>_{ship,
<level>}.e4.* so SR5b's own sr5b_<tag>_* vectors are never rewritten.  At r3
the broadcast MOVX count of each pinned image is printed beside the masked
FENCE count.
S1T's header follows (its "form B" is r0's; here the reordered side is r1).

Writes, for side in (ship, r1), tb/scripts/w9/sr5b_<tag>_<side>.e4.{seq,
seqdata.bin,chip} (gitignored, regenerable), run by tb_seq_chip with
+base=tb/scripts/w9/model_9b_s1 (the chat tool's base).

The launch sequence (what chat_seq runs for a 3-token prompt + 1 decode):

    0 preamble                    sess.images["preamble"]
    1 lite  tok=T0 pos=0          step_patch("lite", T0, 0).apply(image)
    2 lite  tok=T1 pos=1
    3 full  tok=T2 pos=2          -> token o1
    4 full  tok=o1 pos=P          -> token o2   (P = --far-pos)

NOTHING HERE IS NEW MACHINERY.  The images are built by chat_seq's
ChatSession (form B: `_reorder_images_b`, which REFUSES unless the lite and
full images regenerate equal to their pins); each launch image is
`sess.step_patch(kind, tok, pos, tcnt=1, data_delta=0).apply(image)`, the
exact expression chat_seq's B6 gate uses (sw/chat_seq.py reorder_model_gate)
— for form B that is the record-following patch (follow_patch).  Emitter
space (data_delta 0) IS the chip TB's DDR plan.  The golden is
ref/seq_model.SeqExec over the image sequence with ONE persistent Mach and
ONE StateRegion loaded from <base>.state.bin (B6's and
tb/scripts/gen_chat_i1_vectors.py's method); the `.seq` layout is
gen_chat_i1_vectors' (images concatenated, 4 KiB aligned); the per-launch
golden lines are tb/scripts/gen_seq_chip_vectors.py's 9B ones (EMBLOG2,
SBASE, all-KVH TCNT, SMEM fnv1a64 per stored block, MEM minus staging).

ACCEPTANCE (asserted here, before any chip run): the two sides' tokens are
identical, and every launch's golden lines other than LAUNCH/PC are
identical (XRF, TOK, TCNT, EOUT, AMAX, SMEM, every checked scratch word).
The form-B side must also differ from the shipped side as an image (it is
reordered) and its head records must be the shipped ones.
"""
import argparse
import hashlib
import json
import os
import sys
import time
import types

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "sw"), os.path.join(ROOT, "ref"),
                os.path.join(ROOT, "ref", "scripts"),
                os.path.join(ROOT, "tb", "scripts")]
import chat_seq as CS                                          # noqa: E402
import seq_format as SF                                        # noqa: E402
import seq_model as SM                                         # noqa: E402
import hwmap as HW                                             # noqa: E402
from gen_seq_chip_vectors import fnv1a64                       # noqa: E402

ALIGN = 4096
W9 = os.path.join(ROOT, "tb", "scripts", "w9")


def mk_args(**kw):
    # s1p_formB_tdd.mk_args: the chat tool's 9B --nch 4 session defaults
    a = dict(template=CS.TEMPLATE4_PREFIX, any_template=False, nch=4,
             t_max=CS.T_MAX, pos_mode="auto", max_ctx=511, chan=0,
             temp=0.0, top_k=CS.DEFAULT_TOP_K, top_p=CS.DEFAULT_TOP_P,
             seed=None, verify_head=False, system=None, reorder=None,
             seq_rtl="r0")
    a.update(kw)
    return types.SimpleNamespace(**a)


def _pad(n):
    return (n + ALIGN - 1) // ALIGN * ALIGN


def run_side(sess, seq, tag, log):
    """Replay `seq` [(kind, tok|None, pos)] on ONE Mach + ONE region.
    tok None = the previous full launch's token (the chat loop)."""
    Wt = SM.DDRWeights.from_files(sess.base, sess.meta["weights"], sess.meta)
    row = sess.emb_row_bytes
    emb = np.memmap(sess.embf, dtype="<i2", mode="r").reshape(
        os.path.getsize(sess.embf) // row, row // 2)
    mach = SM._fresh_mach()
    region = CS.SeqModelVerifier.state_region(sess)
    assert region is not None, "9B chat must have a DDR state region"
    stage = np.zeros(len(mach.mem), dtype=bool)
    for (lo, hi) in sess.meta.get("staging_words", []):
        stage[lo:hi] = True
    out, last_tok = [], None
    for kind, tok, pos in seq:
        im = sess.images[kind].a
        if kind == "preamble":
            data = im.data
        else:
            tok = last_tok if tok is None else tok
            data = sess.step_patch(kind, tok=tok, pos=pos, tcnt=1,
                                   data_delta=0).apply(im)
        recs = SF.unpack_stream(data)
        t1 = time.monotonic()
        ex = SM.SeqExec(recs, sess.const_blob, Wt, emb=emb, mach=mach,
                        region=region, caps=sess.level_caps).run(max_steps=50 * len(recs))
        M = ex.M
        toks = [int(x) for x in ex.out_fifo]
        if toks:
            last_tok = toks[-1]
        pc = max(i for i, r in enumerate(recs) if r.opcode == SF.OP_HALT)
        lines = []
        for i in range(SF.XRF_N):
            lines.append(f"XRF {i} {int(ex.xrf[i]) & 0x3FFFF:05x}")
        for t in toks:
            lines.append(f"TOK {t:05x}")
        for s in range(len(M.T)):
            lines.append("TCNT %d %s" % (s, " ".join(str(int(v))
                                                     for v in M.T[s])))
        lines.append(f"EOUT {int(M.eout) & 0xF:x}")
        lines.append(f"AMAX {int(M.am_idx) & 0x3FFFF:05x} "
                     f"{int(M.am_val) & 0xFFFFFFFF:08x}")
        for key in sorted(region.touched):
            b_ad, b_ln = region.addr_of(*key)
            b_off = b_ad - region.plan["dn"]
            lines.append(f"SMEM {b_ad:x} {b_ln:x} "
                         f"{fnv1a64(region.mem[b_off:b_off + b_ln]):016x}")
        for addr in range(len(M.mem)):
            if not stage[addr]:
                lines.append(f"MEM {addr:04x} {int(M.mem[addr]) & 0xFFFF:04x}")
        out.append({"kind": kind, "tok_in": tok, "pos": pos, "data": data,
                    "nrec": len(recs), "pc": pc, "tok": toks,
                    "lines": lines,
                    "sha": hashlib.sha256(data).hexdigest()})
        log(f"  [{tag}] launch {len(out) - 1} {kind} tok={tok} pos={pos}: "
            f"{len(recs)} recs, pc {pc}, out {toks}, image sha "
            f"{out[-1]['sha'][:16]} ({time.monotonic() - t1:.0f} s)")
    return out, region


def write_vectors(prefix, sess, launches, region):
    off = 0
    with open(prefix + ".seq", "wb") as f:
        for L in launches:
            f.seek(off)
            f.write(L["data"])
            assert off % SF.REC_BYTES == 0
            L["rec_off"] = off // SF.REC_BYTES
            off += _pad(len(L["data"]))
        f.truncate(off + ALIGN)
    open(prefix + ".seqdata.bin", "wb").write(sess.const_blob)
    rb = sess.emb_row_bytes
    assert rb > 0 and (rb & (rb - 1)) == 0
    u = 1 << 16
    p = region.plan
    with open(prefix + ".chip", "w") as f:
        f.write(f"BASES {SF.SEQ_STREAM_BASE:08x} {SF.SEQ_DATA_BASE:08x} "
                f"{HW.EMB_BASE:08x} {HW.W_BASE:08x}\n")
        f.write(f"EMBLOG2 {rb.bit_length() - 1}\n")
        f.write(f"SBASE {p['dn'] // u:x} {p['kv'] // u:x} "
                f"{p['cv'] // u:x} {(p['end'] - p['dn']) // u:x}\n")
        f.write(f"NLAUNCH {len(launches)}\n")
        for i, L in enumerate(launches):
            f.write(f"LAUNCH {i} {L['rec_off']} {L['nrec']}\n")
            f.write(f"KIND {L['kind']}\n")
            f.write(f"PC {L['pc']}\n")
            for ln in L["lines"]:
                f.write(ln + "\n")
            f.write("ENDL\n")
        f.write("END\n")
    return {s: hashlib.sha256(open(prefix + s, "rb").read()).hexdigest()
            for s in (".seq", ".seqdata.bin", ".chip")}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tag")
    ap.add_argument("--toks", type=int, nargs=3, required=True)
    ap.add_argument("--far-pos", type=int, required=True)
    ap.add_argument("--seq-rtl", default="r1",
                    help="the reordered side's chat level (default r1, "
                         "SR5b's committed use; R3-9b runs r3)")
    a = ap.parse_args()
    assert CS.MODEL_TAG == "9b", "run with FABLE5_MODEL=9b"
    lv = a.seq_rtl
    assert lv in CS.REORDER_B_PINS_BY_RTL and lv != "r0", lv
    fpre = "sr5b" if lv == "r1" else f"sr5b{lv}"
    t0 = time.monotonic()
    quiet = (lambda *_a, **_k: None)
    seq = [("preamble", None, 0), ("lite", a.toks[0], 0),
           ("lite", a.toks[1], 1), ("full", a.toks[2], 2),
           ("full", None, a.far_pos)]
    # the default the chat tool resolves on this operating point
    eff = CS.effective_reorder(types.SimpleNamespace(
        reorder=CS.REORDER_AUTO, nch=4, template=CS.TEMPLATE4_PREFIX),
        env={"FABLE5_MODEL": "9b"}, log=print)
    print(f"  effective_reorder(auto, 9b, --nch 4, shipped template) = "
          f"{eff!r}  (the per-image order below is what a default 9B "
          f"session runs)")
    sides = {}
    for side, form, lvl in (("ship", None, "r0"), (lv, "B", lv)):
        args = mk_args(reorder=form, seq_rtl=lvl)
        if form:
            CS.resolve_reorder(args, log=print)
        sess = CS.ChatSession(args, log=print if form else quiet)
        print(f"  [{side}] seq_rtl {sess.seq_rtl}, caps {sorted(sess.level_caps)}")
        if form == "B":
            assert sess.seq_rtl == lv and sess.level_caps == CS.seq_rtl_caps(lv)
            if lv == "r1":
                assert sess.level_caps == {"R1"}
            for kind in ("lite", "full"):
                sha = hashlib.sha256(sess.images[kind].a.data).hexdigest()
                pin = CS.REORDER_B_PINS_BY_RTL[lv][0][kind]
                assert sha == pin[0] and sess.images[kind].a.nrec == pin[1]
                rr = SF.unpack_stream(sess.images[kind].a.data)
                nm = sum(1 for r in rr
                         if r.opcode == SF.OP_FENCE and r.target & 0xF)
                nb = ("" if lv == "r1" else ", %d broadcast MOVX" % sum(
                    1 for r in rr if r.opcode == SF.OP_MOVX
                    and ((r.flags >> 4) & 0xF) == 0xF))
                print(f"  {lv} {kind}: == pin {sha} ({pin[1]} records, "
                      f"{nm} masked FENCEs{nb})")
        launches, region = run_side(sess, seq, side, print)
        prefix = os.path.join(W9, f"{fpre}_{a.tag}_{side}.e4")
        assert not os.path.exists(prefix + ".chip") or lv == "r1", \
            f"REFUSING to rewrite {prefix}.*"
        shas = write_vectors(prefix, sess, launches, region)
        print(f"  wrote {os.path.relpath(prefix, ROOT)}.{{seq,seqdata.bin,chip}}"
              f"  " + " ".join(f"{k} {v[:16]}" for k, v in shas.items()))
        sides[side] = (sess, launches, shas)

    ok = True
    _, Ls, shs = sides["ship"]
    _, Lb, shb = sides[lv]
    # the shipped side against S1T's shipped vectors (same tag, same
    # generator): byte-identical when they exist
    s1t = os.path.join(W9, f"s1t_{a.tag}_ship.e4")
    if os.path.exists(s1t + ".chip"):
        for sfx in (".seq", ".seqdata.bin", ".chip"):
            o = hashlib.sha256(open(s1t + sfx, "rb").read()).hexdigest()
            same = o == shs[sfx]
            ok &= same
            print(f"  ship{sfx} vs S1T's {os.path.relpath(s1t, ROOT)}{sfx}: "
                  f"{'IDENTICAL' if same else 'DIFFER'} ({o[:16]})")
    else:
        print(f"  (S1T's shipped vectors {os.path.relpath(s1t, ROOT)} absent: "
              f"no byte comparison)")
    print(f"--- acceptance: shipped vs {lv}, launch by launch")
    for i, (x, y) in enumerate(zip(Ls, Lb)):
        same = x["lines"] == y["lines"]
        diffimg = x["data"] != y["data"]
        headok = x["data"][:CS.PATCH_BYTES] == y["data"][:CS.PATCH_BYTES]
        want_diff = x["kind"] != "preamble"
        good = same and headok and (diffimg == want_diff)
        ok &= good
        print(f"  launch {i} {x['kind']:8s} tok {x['tok_in']} pos {x['pos']}: "
              f"records {x['nrec']} -> {y['nrec']}, pc {x['pc']} -> {y['pc']}; "
              f"tokens {x['tok']} vs {y['tok']}; golden lines "
              f"{'IDENTICAL' if same else 'DIFFER'} ({len(x['lines'])}); "
              f"image {'reordered' if diffimg else 'identical'}; head "
              f"{'same' if headok else 'MOVED'} -> {'OK' if good else 'FAIL'}")
    print(f"  seqdata identical: {shs['.seqdata.bin'] == shb['.seqdata.bin']}")
    ok &= shs[".seqdata.bin"] == shb[".seqdata.bin"]
    toks = [L["tok"] for L in Ls]
    print(f"SR5B_CHAT_VECTORS {a.tag}: {'PASS' if ok else 'FAIL'} tokens {toks} "
          f"({time.monotonic() - t0:.0f} s)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
