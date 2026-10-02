#!/usr/bin/env python3
"""gen_chat_i1_vectors.py — golden vectors for CHAT_SEQ gate I1.

    gen_chat_i1_vectors.py <out-prefix> [--base tb/scripts/w4/model_v2_s1]

Gate I1 (docs/CHAT_SEQ_SPEC.md) proves, on the REAL RTL (tb/tb_seq_chip.sv:
real seq_unit + seq_movers + layer_chan + matvec_chan), that

  (a) a second START PRESERVES the in-chip context (KV / DeltaNet / conv /
      TCNT banks): the launch-per-step chat flow of spec decision 4 works;
  (b) an "ldc" position-mode launch at pos > 85 loads the CORRECT RoPE
      table.  The XRF[4] cursor is a SIGNED 18-bit register (seq_unit.sv
      xrf_rd) so it only reaches pos <= 85, and ref/seq_model.py does NOT
      model the sign extension — the hazard is invisible in simulation
      through the model, which is exactly why it has to be shown on the RTL.

This script builds the launch SEQUENCE the host (sw/chat_seq.py) would run

    launch 0   session preamble          TurnCompiler.build_session()
    launch 1   prefill-lite step         tok=--tok0 pos=0     (no token out)
    launch 2   full step                 tok=--tok1 pos=1     -> 1 token
    launch 3   full step                 tok=<launch 2's token> pos=--far-pos
               (--far-pos defaults to 86 = the first position the XRF[4]
                cursor CANNOT address)

and emits everything tb_seq_chip needs to replay it:

  <out>.seq          the four record images CONCATENATED, each 4 KiB
                     aligned, at SEQ_STREAM_BASE.  The testbench launches
                     image k by writing SEQ_BASE = base + off_k and
                     SEQ_LEN = nrec_k — no DUT reset in between.
  <out>.seqdata.bin  the session const blob = committed const region
                     [0,998144) + a --t-max position RoPE pool.
  <out>.chip         a MULTI-LAUNCH golden: one section per launch with
                     PC / XRF / TOK / TCNT / EOUT / AMAX / MEM (the same
                     keywords the single-launch .chip uses) plus RDWIN
                     lines that make the RTL prove WHICH RoPE table it
                     fetched from DDR.

The weight region (<base>.wimg.bin) and the embedding table
(<base>.emb.bin) are the existing model_v2 artifacts and are reused
untouched — pass --wimg to rebuild the weight image if it is missing.

PATCH EQUIVALENCE.  On silicon the host keeps ONE lite and ONE full image
resident in DDR and DMAs a 48-byte (pos_mode="xrf") / 72-byte
(pos_mode="ldc": 48 B head + 6 x 4 B LDC addr_lo) patch into it before each
START.  A simulation cannot rewrite the file seq_mem_file.sv is reading, so
this generator applies the SAME Patch object to the SAME resident image and
lays the result down as a separate copy.  It ASSERTS that each launch image
differs from the resident image ONLY inside the patch window, so
"patched before load" is byte-for-byte what "DMA-patched while resident"
produces.
"""
import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
_REF = os.path.join(_ROOT, "ref")
_SW = os.path.join(_ROOT, "sw")
for _p in (_REF, _SW):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import seq_format as SF                                         # noqa: E402
import seq_model as SM                                          # noqa: E402
import seq_chat as SC                                           # noqa: E402
import hwmap as HW                                              # noqa: E402
import gen_layer_script as GLS                                  # noqa: E402

ALIGN = 4096


def _pad(n, a=ALIGN):
    return (n + a - 1) // a * a


def patch_window(img):
    """Byte offsets a per-launch Patch is allowed to touch in `img`."""
    ok = set(range(SC.PATCH_BYTES))                    # the 48 B head
    for o in img.pos_ldc:                              # 6 x 4 B addr_lo
        ok |= set(range(o, o + 4))
    return ok


def check_patch(resident, patched, name):
    """The patched image may differ from the resident one ONLY in the window."""
    a = np.frombuffer(resident.data, dtype=np.uint8)
    b = np.frombuffer(patched, dtype=np.uint8)
    assert a.size == b.size, f"{name}: patch changed the image size"
    diff = set(int(i) for i in np.nonzero(a != b)[0])
    win = patch_window(resident)
    bad = sorted(diff - win)
    assert not bad, (f"{name}: bytes outside the patch window differ: "
                     f"{bad[:8]}{'...' if len(bad) > 8 else ''}")
    return len(diff), sorted(win)[0], len(win)


def ldc_ranges(image):
    """[(lo, hi)] const-blob byte ranges (offsets from SEQ_DATA_BASE) read
    by this image's LDC records."""
    out = []
    for r in SF.unpack_stream(image):
        if r.opcode != SF.EXT_LDC:
            continue
        a = (((int(r.len_or_addr_hi) << 32) | int(r.addr_lo))
             - SF.SEQ_DATA_BASE)
        out.append((a, a + 2 * int(r.imm32)))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out", help="output prefix (.seq/.seqdata.bin/.chip)")
    ap.add_argument("--template", default=SC.DEFAULT_PREFIX,
                    help="gated .e.seq template prefix")
    ap.add_argument("--base", default=SC.DEFAULT_BASE,
                    help="artifact prefix for .weights.json/_w*.bin/.emb.bin")
    ap.add_argument("--t-max", type=int, default=128,
                    help="positions the session RoPE pool covers (128)")
    ap.add_argument("--tok0", type=int, default=760,
                    help="launch 1 (prefill-lite) token id")
    ap.add_argument("--tok1", type=int, default=6511,
                    help="launch 2 (full) token id")
    ap.add_argument("--far-pos", type=int, default=86,
                    help="launch 3 position (> 85 = beyond the XRF cursor)")
    ap.add_argument("--wimg", action="store_true",
                    help="(re)build <base>.wimg.bin")
    a = ap.parse_args()

    t0 = time.time()
    meta = json.load(open(a.template + ".seq.json"))
    plan = {int(k): v for k, v in meta["weights"].items()}

    wimg = a.base + ".wimg.bin"
    if a.wimg or not os.path.exists(wimg):
        import gen_seq_chip_vectors as G
        n = G.build_wimg(a.base, plan, wimg)
        print(f"  {wimg}: {n} B ({len(plan)} images) @ {HW.W_BASE:#x}")
    else:
        print(f"  {wimg}: {os.path.getsize(wimg)} B (reused)")

    embf = a.base + ".emb.bin"
    # R-b: the row stride comes from the manifest (2*H), not a literal
    rb = HW.load_weights_manifest(a.base)[1]["emb_row_bytes"]
    nrow = os.path.getsize(embf) // rb
    emb = np.memmap(embf, dtype="<i2", mode="r").reshape(nrow, rb // 2)
    W = SM.DDRWeights.from_files(a.base, meta["weights"], meta)
    print(f"  {embf}: {nrow} rows")

    # ---------------- the compiler, in the ratified ldc position mode -----
    tc = SC.TurnCompiler(a.template, t_max=a.t_max, pos_mode="ldc")
    blob = tc.blob()
    lay = tc.blob_layout()
    open(a.out + ".seqdata.bin", "wb").write(blob)
    print(f"  {a.out}.seqdata.bin: {len(blob)} B "
          f"(const {SC.CONST_BYTES} + {a.t_max} x {SC.POS_STRIDE}) "
          f"sha {hashlib.sha256(blob).hexdigest()[:12]}")
    print(f"  blob layout {json.dumps(lay)}")

    sess = tc.build_session()
    res_lite = tc.build_step(0, 0, "lite")
    res_full = tc.build_step(0, 0, "full")
    print(f"  resident images: session {sess.nrec} recs, "
          f"lite {res_lite.nrec} recs, full {res_full.nrec} recs "
          f"(pos_mode={tc.pos_mode})")

    # ---------------- build + execute the launch sequence ----------------
    # ONE persistent Mach across launches: that is exactly what the RTL does
    # when the host writes START again without resetting the chip
    # (rtl/seq_unit.sv I_IDLE clears pc/err/abort/perf only).
    M = SM._fresh_mach()
    launches = []          # (kind, image bytes, tokens, snapshot bits)

    def run(kind, data, note):
        ex = SM.SeqExec(data, blob, W, emb=emb, mach=M)
        t = time.time()
        ex.run(max_steps=50 * len(ex.recs))
        rec = {
            "kind": kind, "note": note, "data": data,
            "nrec": len(ex.recs),
            "pc": max(i for i, r in enumerate(ex.recs)
                      if r.opcode == SF.OP_HALT),
            "tok": [int(x) for x in ex.out_fifo],
            "xrf": [int(x) & 0x3FFFF for x in ex.xrf],
            "T": [[int(M.T[s][0]), int(M.T[s][1])] for s in range(len(M.T))],
            "eout": int(M.eout) & 0xF,
            "am": (int(M.am_idx) & 0x3FFFF, int(M.am_val) & 0xFFFFFFFF),
            "mem": M.mem.copy(),
            "rdwin": [],
        }
        launches.append(rec)
        print(f"  launch {len(launches) - 1} [{kind}] {note}: "
              f"{rec['nrec']} recs, pc {rec['pc']}, tokens {rec['tok']}, "
              f"TCNT {rec['T'][0]} ({time.time() - t:.1f}s)")
        return rec

    run("session", sess.data, "preamble (resets conv/dn/KV/TCNT)")

    p1 = tc.patch_step(res_lite, a.tok0, 0)
    im1 = p1.apply(res_lite)
    nd, w0, wn = check_patch(res_lite, im1, "launch1")
    print(f"    patch {p1.nbytes} B in {len(p1.writes())} write(s) "
          f"{p1.fields} -> {nd} byte(s) differ, all inside the "
          f"{wn}-byte window at +{w0}")
    run("lite", im1, f"tok={a.tok0} pos=0")

    p2 = tc.patch_step(res_full, a.tok1, 1)
    im2 = p2.apply(res_full)
    nd, w0, wn = check_patch(res_full, im2, "launch2")
    assert im2 == tc.build_step(a.tok1, 1, "full").data, \
        "resident+patch != freshly built image"
    print(f"    patch {p2.nbytes} B in {len(p2.writes())} write(s) "
          f"{p2.fields} -> {nd} byte(s) differ, all inside the "
          f"{wn}-byte window at +{w0}")
    r2 = run("full", im2, f"tok={a.tok1} pos=1")
    assert len(r2["tok"]) == 1, \
        f"launch 2 pushed {len(r2['tok'])} tokens, expected exactly 1"

    # launch 3 feeds the token launch 2 decoded — the real chat loop.
    tok2 = r2["tok"][0]
    p3 = tc.patch_step(res_full, tok2, a.far_pos)
    im3 = p3.apply(res_full)
    nd, w0, wn = check_patch(res_full, im3, "launch3")
    print(f"    patch {p3.nbytes} B in {len(p3.writes())} write(s) "
          f"{p3.fields} -> {nd} byte(s) differ, all inside the "
          f"{wn}-byte window at +{w0}")
    # the two full launches share one resident image: prove they differ only
    # in the patch window (this is the DMA-patch-in-place equivalence).
    d23 = np.nonzero(np.frombuffer(im2, dtype=np.uint8)
                     != np.frombuffer(im3, dtype=np.uint8))[0]
    assert set(int(i) for i in d23) <= patch_window(res_full), \
        "the two full launches differ outside the patch window"
    print(f"    launch2 vs launch3 image delta: {len(d23)} bytes, all inside "
          f"the patch window (one resident image, two patches)")
    r3 = run("full", im3, f"tok={tok2} pos={a.far_pos}")

    # ---------------- the RoPE-table witness for the pos>85 launch --------
    good_lo = SC.POS_BLOB_BASE + a.far_pos * SC.POS_STRIDE
    good_hi = good_lo + SC.POS_STRIDE
    # what the FROZEN xrf mode would have produced: XRF[4] = pos*1536 does
    # not fit the SIGNED 18-bit XRF, so seq_unit reads it back sign-extended.
    xrf4 = a.far_pos * SC.POS_STRIDE
    bits = SF.XRF_BITS
    sx = (xrf4 & ((1 << bits) - 1))
    if sx >= (1 << (bits - 1)):
        sx -= (1 << bits)
    bad_lo = SC.POS_BLOB_BASE + sx
    bad_hi = bad_lo + SC.POS_STRIDE
    print(f"  pos {a.far_pos}: ldc mode addresses {good_lo:#x}..{good_hi:#x}; "
          f"the xrf cursor would sign-extend {xrf4} -> {sx} and read "
          f"{bad_lo:#x}..{bad_hi:#x} (XRF_POS_MAX={SC.XRF_POS_MAX})")
    assert a.far_pos > SC.XRF_POS_MAX, \
        f"--far-pos {a.far_pos} <= XRF_POS_MAX {SC.XRF_POS_MAX}: the gate " \
        f"would not exercise the hazard"

    # the "bad" witness is only meaningful if NOTHING else in the launch
    # legitimately reads that range.
    bad_off = bad_lo - SF.SEQ_DATA_BASE
    clash = [(lo, hi) for (lo, hi) in ldc_ranges(im3)
             if lo < bad_off + SC.POS_STRIDE and bad_off < hi]
    launches[3]["rdwin"].append((good_lo, good_hi, SC.POS_COPIES, 1 << 30,
                                 "rope-pos%d" % a.far_pos))
    if clash:
        print(f"    NOTE: {len(clash)} const LDC(s) overlap the sign-extended "
              f"window {clash[:3]} — the negative witness is omitted")
    else:
        launches[3]["rdwin"].append((bad_lo, bad_hi, 0, 0, "rope-signext"))
        print(f"    negative witness armed: 0 DDR reads may land in "
              f"{bad_lo:#x}..{bad_hi:#x}")
    # and the same positive witness for the two in-range launches
    for k, pos in ((1, 0), (2, 1)):
        lo = SC.POS_BLOB_BASE + pos * SC.POS_STRIDE
        launches[k]["rdwin"].append((lo, lo + SC.POS_STRIDE, SC.POS_COPIES,
                                     1 << 30, "rope-pos%d" % pos))

    # ---------------- lay the images down as one stream file -------------
    off = 0
    with open(a.out + ".seq", "wb") as f:
        for L in launches:
            f.seek(off)
            f.write(L["data"])
            L["off"] = off
            assert off % SC.REC == 0
            L["rec_off"] = off // SC.REC
            off += _pad(len(L["data"]))
        f.truncate(off + ALIGN)          # a page of slack for burst prefetch
    print(f"  {a.out}.seq: {off + ALIGN} B, {len(launches)} images "
          f"@ {SF.SEQ_STREAM_BASE:#x} "
          f"(rec offsets {[L['rec_off'] for L in launches]})")

    # ---------------- the multi-launch golden ----------------------------
    # D-STAGE (spec 9).  This mask was the bare literal 16384 where its
    # sibling derives it.  It is CORRECT TODAY at the 0.8B default this
    # generator runs at, and the harm is UNDER-COVERAGE rather than a false
    # pass: `keep` below cannot name a word at or above the mask's length, so
    # a staging window in the upper half would go unchecked rather than
    # mis-checked.
    #
    # DERIVED FROM `GLS.SCRATCH`, NOT FROM `sw/hwmap.SCRATCH_WORDS`, and the
    # difference is load-bearing.  The mask indexes `L["mem"]`, which is
    # `gen_layer_script.Mach.mem` — depth `GLS.SCRATCH`, the emitter's
    # power-of-two scratch depth FOR THIS GEOMETRY (16384 at 0.8B).
    # `sw/hwmap.SCRATCH_WORDS` is the depth of the HARDWARE array, which G2a
    # moved to 65,536; masking with that produces `keep` entries past the end
    # of `L["mem"]` and the writer below dies with an IndexError.  Measured,
    # not reasoned: it did exactly that on the first attempt.  The sibling
    # that already had this right is `ref/seq_model.py:1200`, which also uses
    # `GLS.SCRATCH`.
    stage = np.zeros(GLS.SCRATCH, dtype=bool)
    for (lo, hi) in meta.get("staging_words", []):
        stage[lo:hi] = True
    keep = np.nonzero(~stage)[0]

    with open(a.out + ".chip", "w") as f:
        f.write(f"BASES {SF.SEQ_STREAM_BASE:08x} {SF.SEQ_DATA_BASE:08x} "
                f"{HW.EMB_BASE:08x} {HW.W_BASE:08x}\n")
        f.write(f"NLAUNCH {len(launches)}\n")
        for i, L in enumerate(launches):
            f.write(f"LAUNCH {i} {L['rec_off']} {L['nrec']}\n")
            f.write(f"KIND {L['kind']}\n")
            f.write(f"PC {L['pc']}\n")
            for j, v in enumerate(L["xrf"]):
                f.write(f"XRF {j} {v:05x}\n")
            for t in L["tok"]:
                f.write(f"TOK {t:05x}\n")
            for s, (b0, b1) in enumerate(L["T"]):
                f.write(f"TCNT {s} {b0} {b1}\n")
            f.write(f"EOUT {L['eout']:x}\n")
            f.write(f"AMAX {L['am'][0]:05x} {L['am'][1]:08x}\n")
            for (lo, hi, n0, n1, tag) in L["rdwin"]:
                f.write(f"RDWIN {lo:08x} {hi:08x} {n0} {n1}\n")
            for addr in keep:
                f.write(f"MEM {addr:04x} {int(L['mem'][addr]) & 0xFFFF:04x}\n")
            f.write("ENDL\n")
        f.write("END\n")

    print(f"  {a.out}.chip: {len(launches)} launches, "
          f"{len(keep)} scratch words/launch checked "
          f"({int(stage.sum())} staging words excluded), "
          f"tokens {[L['tok'] for L in launches]}")
    print(f"  TCNT trace {[L['T'][0] for L in launches]} "
          f"(bank 0; a reset between launches would show 0)")
    print(f"  gen_chat_i1_vectors: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
