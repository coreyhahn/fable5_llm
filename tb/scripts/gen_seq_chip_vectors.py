#!/usr/bin/env python3
"""gen_seq_chip_vectors.py — golden state for tb/tb_seq_chip.sv.

    gen_seq_chip_vectors.py <seq-prefix> [--base <artifact-prefix>]

Replays <seq-prefix>.seq through ref/seq_model.py (the SAME executor the
wave-1B .txt-vs-.seq gate uses) against the REAL packed weight images, and
writes what a full-chip simulation must reproduce:

  <seq-prefix>.chip     NREC / PC / BASES / XRF / TOK / TCNT / EOUT / AMAX /
                        MEM keyword lines, terminated by END.  The MEM set is
                        the FINAL 16K scratchpad MINUS the y32 staging windows
                        the .seq stream legitimately leaves different from the
                        host-driven .txt run (they are declared in the
                        emitter's .seq.json), so every word the schedule is
                        supposed to determine is checked.
  <base>.wimg.bin       the weight REGION image: every packed <base>_w*.bin
                        laid down at the DDR offset the emitter's MVGO records
                        address (plan_weights_from_wids / sw/hwmap.py
                        plan_weights), so matvec_chan's own AXI4 master
                        fetches exactly the bytes the engine expects.
  <base>.wimg<c>.bin    R-c: a REPACKED stream (SEQ_REPACK=1) gives every
                        channel its own address space, so the region is
                        written once PER CHANNEL, each holding only the rows
                        that channel owns.  Build tb_seq_chip with
                        -GWIMGPC=1 -GNMV=<nch> to serve them.

The .seq / .seqdata.bin / .emb.bin files are read by the simulation directly
(tb/seq_mem_file.sv $fseek/$fread's them beat by beat), so nothing else has to
be converted.
"""
import argparse
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_REF = os.path.normpath(os.path.join(_HERE, "..", "..", "ref"))
_SW = os.path.normpath(os.path.join(_HERE, "..", "..", "sw"))
for _p in (_REF, _SW):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import seq_format as SF                                       # noqa: E402
import seq_model as SM                                        # noqa: E402
import hwmap as HW                                            # noqa: E402


WIMG_SFX = ".wimg.bin"

# FNV-1a 64, the SMEM golden's transport (spec 8.3).  `tb/seq_mem_file.sv`'s
# `win_fnv` is the identical arithmetic in SystemVerilog: the hash travels in
# the .chip file, and what it stands for is byte equality of the block.
FNV64_OFFSET = 0xcbf29ce484222325
FNV64_PRIME = 0x100000001b3


def fnv1a64(buf):
    # Sequential by construction, so this is a tight Python loop with every
    # name bound locally: ~10 M bytes/s, i.e. seconds for a smoke artifact's
    # blocks and minutes for a whole model's region.
    h, p, m = FNV64_OFFSET, FNV64_PRIME, 0xFFFFFFFFFFFFFFFF
    for b in bytes(buf):
        h = ((h ^ b) * p) & m
    return h


def build_wimg(base, plan, out, meta=None):
    """The DDR weight region(s) tb_seq_chip's `seq_mem_file` serves.

    NCH-INDEPENDENT PACK (`plan[wid]["base"]` an int — every artifact frozen
    before R-c).  One flat file starting at HW.W_BASE: it holds
    (base - W_BASE) .. (base - W_BASE + size) for each image, with the
    WID_ALIGN padding between images left as zeros (never fetched: a MVGO's
    BEATS only ever covers real rows).  Returns the file size, an int.

    PER-CHANNEL PACK (`plan[wid]["base"]` a list of nch addresses, R-c
    `SEQ_REPACK=1` — what makes the 2B W8 images fit).  Each channel has its
    OWN address space, so one flat region file cannot serve all NMV engines;
    this writes `<stem>.wimg<c>.bin`, one per channel, and tb_seq_chip
    elaborates each `matvec_chan`'s `seq_mem_file` against its own (the
    `WIMGPC` parameter).  A channel's copy holds ONLY the rows that channel
    owns, at `chan_base + row_off*stride` — `row_off` being the row index
    inside THAT channel's copy, which is what the emitter built the MVGO
    WBASEs from (`ref/seq_format.weight_pieces_at(..., repack=True)`).
    Returns one size per channel, a list.

    `meta` is the stream's `.seq.json`: the per-channel build needs
    `meta["weight_layout"]` (nch / chunk_rows / per-wid layout) to know how
    each image was SPLIT, because the row counts differ between the
    contiguous split and the CHUNK INTERLEAVE the AMAX/LM-head image uses.
    A repacked plan without it is refused rather than guessed at.  The
    interleave depth is `weight_layout["chunk_rows"]` — the ARTIFACT's, not
    this tree's `ref/seq_format.CHUNK_ROWS`: a stream emitted at another
    depth must still be placed the way its own MVGO WBASEs read it.
    `verify_plan` below is what makes that faithful rather than merely
    stated.
    """
    man, _ = HW.load_weights_manifest(base)     # R-b: drops the meta key
    d = os.path.dirname(os.path.abspath(base)) or "."
    repack = any(isinstance(p["base"], (list, tuple)) for p in plan.values())
    if not repack:
        top = 0
        for wid, p in plan.items():
            top = max(top, p["base"] - HW.W_BASE + p["nrows"] * p["stride"])
        with open(out, "wb") as f:
            f.truncate(top)
            for wid, p in sorted(plan.items()):
                path = os.path.join(d, man[str(wid)]["file"])
                img = np.fromfile(path, dtype=np.uint8)
                sz = p["nrows"] * p["stride"]
                assert len(img) == sz, \
                    f"wid {wid}: image {path} is {len(img)} B, plan says {sz}"
                f.seek(p["base"] - HW.W_BASE)
                f.write(img.tobytes())
        return top

    if not out.endswith(WIMG_SFX):
        raise SystemExit(f"per-channel build needs an output named *{WIMG_SFX}"
                         f", got {out!r}")
    stem = out[:-len(WIMG_SFX)]
    if meta is None or "weight_layout" not in meta:
        raise SystemExit(
            "this stream carries a PER-CHANNEL weight pack (meta "
            "weight_repack) but no meta[\"weight_layout\"] was supplied; the "
            "per-channel row split cannot be guessed from the plan alone")
    if not all(isinstance(p["base"], (list, tuple)) for p in plan.values()):
        raise SystemExit("mixed plan: some images per-channel, some not")
    wl = meta["weight_layout"]
    nch, depth = int(wl["nch"]), int(wl["chunk_rows"])
    if any(len(p["base"]) != nch for p in plan.values()):
        raise SystemExit(f"plan bases are not {nch} long — plan and "
                         "weight_layout disagree about nch")

    pieces, tops = {}, [0] * nch
    for wid, p in sorted(plan.items()):
        layout = wl["by_wid"].get(str(wid), wl["default"])
        pcs = SF.weight_pieces_at(int(p["nrows"]), nch, layout, depth,
                                  repack=True)
        assert sum(n for (_c, _r, n, _o) in pcs) == int(p["nrows"]), \
            f"wid {wid}: pieces do not partition the image"
        pieces[wid] = pcs
        for (c, _r0, npc, off) in pcs:
            tops[c] = max(tops[c],
                          p["base"][c] - HW.W_BASE + (off + npc) * p["stride"])

    # a stale flat region file from an earlier NON-repacked build must not
    # sit beside the per-channel set where a TB could still open it
    if os.path.exists(out):
        os.remove(out)
    files = [open(f"{stem}.wimg{c}.bin", "wb") for c in range(nch)]
    written = [[] for _ in range(nch)]           # disjointness witness
    try:
        for c in range(nch):
            files[c].truncate(tops[c])
        for wid, p in sorted(plan.items()):
            path = os.path.join(d, man[str(wid)]["file"])
            n, stride = int(p["nrows"]), int(p["stride"])
            img = np.memmap(path, dtype=np.uint8, mode="r")
            assert img.size == n * stride, \
                f"wid {wid}: image {path} is {img.size} B, plan says " \
                f"{n * stride}"
            img = img.reshape(n, stride)
            for (c, r0, npc, off) in pieces[wid]:
                lo = p["base"][c] - HW.W_BASE + off * stride
                files[c].seek(lo)
                files[c].write(np.ascontiguousarray(img[r0:r0 + npc]).tobytes())
                written[c].append((lo, lo + npc * stride, wid, r0))
            del img
    finally:
        for f in files:
            f.close()
    for c in range(nch):
        w = sorted(written[c])
        for (a, b) in zip(w, w[1:]):
            assert a[1] <= b[0], (
                f"chan {c}: wid {a[2]} rows at {a[0]:#x}..{a[1]:#x} OVERLAP "
                f"wid {b[2]} at {b[0]:#x} — the repack plan is not disjoint")
    return tops


def verify_plan(base, plan, meta):
    """Re-derive every image address from the MANIFEST and require it to
    reproduce the plan the stream's MVGO records already encode.

    G4a, closing `evidence/qwen9b/g2/G2C_CHAIN.md`'s handoff 3 ("re-run
    `plan_weights` against the REAL manifest with `wdir` set").  The bases in
    `meta["weights"]` were computed by `sw/hwmap.plan_weights` at EMIT time
    from the live quantized tensors; this recomputes them from the manifest
    on disk plus the layout the artifact declares, so the two sides share no
    intermediate.  A `chunk_rows` that did not match the split the emitter
    used moves the per-channel row counts, which moves every cursor after the
    first ILV image, and the comparison below fails instead of the region
    file being written at the wrong rows.

    `wdir` additionally makes `plan_weights` stat every image and check its
    SIZE against `nrows * stride`, which is the other half of "the bytes are
    where the stream says".
    """
    man, _ = HW.load_weights_manifest(base)
    d = os.path.dirname(os.path.abspath(base)) or "."
    # `weight_layout` rides every nch>1 stream, repacked or not; `depth` is
    # the artifact's own interleave chunk and is read only from there.
    wl = meta.get("weight_layout")
    nch = int(wl["nch"]) if wl else int(meta.get("nch", 1) or 1)
    depth = int(wl["chunk_rows"]) if wl else None
    if depth is not None and (depth <= 0 or (depth & (depth - 1))):
        raise SystemExit(f"weight_layout chunk_rows {depth} is not a "
                         "positive power of two")

    def split(wid, nrows):
        return SF.chan_rows(int(nrows), nch,
                            wl["by_wid"].get(str(wid), wl["default"]), depth)

    # rows_of is the REPACK question only: without it every channel reserves
    # the whole image and the split does not enter the addresses.
    rows_of = split if meta.get("weight_repack") else None
    got, top = HW.plan_weights(man, wdir=d, nch=nch, rows_of=rows_of)
    bad = [wid for wid, p in plan.items()
           if list(np.atleast_1d(got[int(wid)])) != list(np.atleast_1d(
               p["base"]))]
    if bad:
        raise SystemExit(
            f"the re-derived weight plan disagrees with the stream's on "
            f"wid(s) {sorted(bad)[:8]} — first: manifest says "
            f"{got[int(sorted(bad)[0])]}, the stream's MVGOs encode "
            f"{plan[sorted(bad)[0]]['base']}")
    ilv = sorted(wl["ilv_wids"]) if wl else []
    print(f"  plan re-derived from the manifest: {len(plan)} images, "
          f"nch={nch}, chunk_rows={depth if depth else 'n/a'}, "
          f"repack={bool(meta.get('weight_repack'))}, ilv_wids={ilv}, "
          f"every base identical")
    for w in ilv:
        print(f"    wid {w} (LAYOUT_ILV, {plan[w]['nrows']} rows) -> "
              f"per-channel rows {split(w, plan[w]['nrows'])}")
    print(f"  pack top: {top}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("prefix", help="the .seq / .seqdata.bin / .seq.json prefix")
    ap.add_argument("--base", default=None,
                    help="prefix of the generator artifacts (.weights.json, "
                         "_w*.bin, .emb.bin); defaults to PREFIX")
    ap.add_argument("--no-wimg", action="store_true",
                    help="skip rebuilding <base>.wimg.bin (it is large and "
                         "only depends on the weights, not on the stream)")
    # SR5b (SEQ_ISA v2.3 B17.0): the capability set the stream is validated
    # and executed at, named by the CALLER (`--caps R1` for an r1 stream
    # with masked FENCEs), as ref/seq_model.py gate --caps does.  Default:
    # the empty set, i.e. every earlier invocation unchanged, byte for byte.
    ap.add_argument("--caps", default="",
                    help="comma-separated capability set (e.g. R1); "
                         "default: none")
    a = ap.parse_args()
    base = a.base or a.prefix
    caps = frozenset(c.strip() for c in a.caps.split(",") if c.strip())
    if caps:
        print(f"  caps {sorted(caps)} (validated and executed at them)")

    meta = json.load(open(a.prefix + ".seq.json"))
    stream = open(a.prefix + ".seq", "rb").read()
    blob = open(a.prefix + ".seqdata.bin", "rb").read()
    recs = SF.unpack_stream(stream)
    # G3.4 fix round 2: the SHAPE LAYOUT comes from the ARTIFACT, because
    # that is where it lives.  This tool LOADS a <prefix>.seq -- it does
    # not build one -- and its default target is tb/scripts/w3, the FROZEN
    # build_034/build_035 set, whose MVGO SHAPE words are legitimately
    # isa=1 (`ng` in bits [5:0]).  A first cut stated SHAPE_ISA_9B here
    # unconditionally, and it refuses BOTH of them -- w3/tok2_s1.e, which is
    # tb/Makefile's default SEQP and so what `make -C tb seq_chip_vectors`
    # would actually have hit, at rec 112, and w3/lay_s1.e at rec 108 (both
    # measured: evidence/qwen9b/g3/g34_shape_isa_paths.py check 2).  Same
    # over-reach the board-free gate caught in round 1, one file further
    # along.  Absent key = not stated = the envelope stays
    # off; a 9B artifact that declares `shape_isa` turns it on with no edit
    # here, exactly as ref/seq_model.gate() and ref/seq_chat.Templates do.
    SF.validate_stream(recs, shape_isa=meta.get("shape_isa"), caps=caps)

    plan = {int(k): v for k, v in meta["weights"].items()}
    if plan:
        verify_plan(base, plan, meta)
    if plan and not a.no_wimg:
        n = build_wimg(base, plan, base + ".wimg.bin", meta=meta)
        if isinstance(n, list):
            for c, sz in enumerate(n):
                print(f"  {base}.wimg{c}.bin: {sz} B "
                      f"({sz / (1 << 20):.1f} MiB) @ {HW.W_BASE:#x}")
            print(f"  per-channel weight pack: {len(n)} channels, "
                  f"{len(plan)} images (run tb_seq_chip with -GWIMGPC=1)")
        else:
            print(f"  {base}.wimg.bin: {n} B ({len(plan)} images) @ "
                  f"{HW.W_BASE:#x}")

    emb = None
    # R-c wall 8: the declared row stride, whether or not this artifact has
    # an embedding table — a stream with no EMB record still states the
    # geometry it was built for, and the TB asserts seq_unit accepts it.
    emb_row_bytes = HW.load_weights_manifest(base)[1]["emb_row_bytes"]
    embf = base + ".emb.bin"
    if os.path.exists(embf):
        # R-b: the row stride comes from the manifest (2*H), not a literal
        rb = emb_row_bytes
        nrow = os.path.getsize(embf) // rb
        emb = np.memmap(embf, dtype="<i2", mode="r").reshape(nrow, rb // 2)

    W = SM.DDRWeights.from_files(base, meta["weights"], meta)
    # S3 (SEQ_ISA v2.1): the DDR state region, loaded from the artifact's
    # INITIAL image `<base>.state.bin` -- the same file the chip TB's DDR
    # model maps behind its write window and the same bytes the host
    # uploads.  None for a pre-S3 artifact, which emits no SLD/SST.
    region = SM.StateRegion.load(base)
    ex = SM.SeqExec(recs, blob, W, emb=emb,
                    region=region, caps=caps).run(max_steps=50 * len(recs))
    M = ex.M

    # the pc a halted seq_unit reports = the index of the HALT record
    halt_pc = None
    for i, r in enumerate(recs):
        if r.opcode == SF.OP_HALT:
            halt_pc = i
    assert halt_pc is not None, "stream has no HALT"

    stage = np.zeros(len(M.mem), dtype=bool)   # R-b: the model's own depth
    for (lo, hi) in meta.get("staging_words", []):
        stage[lo:hi] = True

    with open(a.prefix + ".chip", "w") as f:
        f.write(f"NREC {len(recs)}\n")
        f.write(f"PC {halt_pc}\n")
        f.write(f"BASES {SF.SEQ_STREAM_BASE:08x} {SF.SEQ_DATA_BASE:08x} "
                f"{HW.EMB_BASE:08x} {HW.W_BASE:08x}\n")
        # R-c wall 8: the EMB row stride the host must program into
        # seq_unit's EMBLOG2 CSR before any EMB record runs (the TB's host
        # BFM never did, and a 2B artifact's 4096 B rows were fetched as
        # 2048 B ones).  Derived from the manifest exactly as sw/seq_run.py
        # derives it, so the TB cannot drift from the artifact.
        # `bit_length()-1` IS log2 only for a power of two — and seq_unit's
        # EMBLOG2 can express nothing else (it shifts by the value).  An
        # oddly-sized row would otherwise be silently rounded DOWN here and
        # fetched at the wrong stride: wall 8's exact failure mode wearing a
        # different hat.  Refuse it instead.
        assert emb_row_bytes > 0 and (emb_row_bytes & (emb_row_bytes - 1)) == 0, (
            f"emb_row_bytes {emb_row_bytes} is not a power of two; seq_unit's "
            f"EMBLOG2 CSR is a SHIFT amount and cannot express it")
        f.write(f"EMBLOG2 {emb_row_bytes.bit_length() - 1}\n")
        if region is not None:
            # WHERE the state region is, in 64 KiB units -- the units the
            # SB_* CSRs take (B15.3).  The PROGRAM writes those CSRs itself
            # (the .txt's S record, three CSRWRs in the .seq); this line is
            # what the TB's DDR model needs to place its write window.
            u = 1 << 16
            p = region.plan
            f.write(f"SBASE {p['dn'] // u:x} {p['kv'] // u:x} "
                    f"{p['cv'] // u:x} {(p['end'] - p['dn']) // u:x}\n")
        for i in range(SF.XRF_N):
            f.write(f"XRF {i} {int(ex.xrf[i]) & 0x3FFFF:05x}\n")
        for t in ex.out_fifo:
            f.write(f"TOK {int(t):05x}\n")
        # G4a fix round 1 (I6): ALL NKVH counters per bank, not the first
        # two.  `layer_chan`'s `tcnt_bank` is `[N_KV][NKVH]` = [8][4] since
        # G3.4 and `Mach.Treset` zeroes `[0] * _KVH`, but this line wrote
        # only heads 0 and 1 — so kvheads 2 and 3 were never in the golden
        # and never checked, at any bank.  That is the OTHER half of the
        # geometry `ref/seq_model.SeqExec._tcnt_wr` exists for: the first
        # half (the checker could not HOLD banks 6/7) was found by the first
        # full 9B replay, and this half was invisible because the golden
        # never carried the columns.  The width is the model's own, so it
        # follows any future NKVH by itself.
        for s in range(len(M.T)):
            f.write("TCNT %d %s\n"
                    % (s, " ".join(str(int(v)) for v in M.T[s])))
        f.write(f"EOUT {int(M.eout) & 0xF:x}\n")
        f.write(f"AMAX {int(M.am_idx) & 0x3FFFF:05x} "
                f"{int(M.am_val) & 0xFFFFFFFF:08x}\n")
        # S3: one SMEM record per block the run STORED, so a store that
        # never happened -- or happened to the wrong block -- is caught by
        # the golden and not only by the token compare (spec 8.3).
        nsmem = 0
        if region is not None:
            for key in sorted(region.touched):
                # NOT `a`/`n`: `a` is the argparse namespace this whole
                # function reads and `n` is the wimg size above.
                b_ad, b_ln = region.addr_of(*key)
                b_off = b_ad - region.plan["dn"]
                f.write(f"SMEM {b_ad:x} {b_ln:x} "
                        f"{fnv1a64(region.mem[b_off:b_off + b_ln]):016x}\n")
                nsmem += 1
        nmem = 0
        for addr in range(len(M.mem)):     # R-b: 16K at 0.8B, 32K at 2B
            if stage[addr]:
                continue
            f.write(f"MEM {addr:04x} {int(M.mem[addr]) & 0xFFFF:04x}\n")
            nmem += 1
        f.write("END\n")

    print(f"  {a.prefix}.chip: {len(recs)} records, pc {halt_pc}, "
          f"{len(ex.out_fifo)} tokens, {nmem} scratch words checked "
          f"({int(stage.sum())} staging words excluded), "
          f"{nsmem} state block(s)")
    print(f"  seq_model stats: {ex.stats}")


if __name__ == "__main__":
    main()
