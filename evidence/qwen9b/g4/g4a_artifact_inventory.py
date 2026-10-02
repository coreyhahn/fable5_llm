#!/usr/bin/env python3
"""g4a_artifact_inventory.py — what the 9B emit produced, and does it fit.

    python3 evidence/qwen9b/g4/g4a_artifact_inventory.py <base> [<seq-prefix>]

`<base>` is the generator prefix (`.weights.json`, `_w*.bin`, `.emb.bin`,
`.txt`); `<seq-prefix>` defaults to `<base>.e4`.

Four things, all of them measurements:

  INVENTORY  every file the emit wrote, with size; sha256 for the small
             ones (the stream, the const blob, the two JSONs) so the gate
             doc can pin a regenerable artifact by hash.  The 249 weight
             images are pinned by COUNT and TOTAL BYTES plus a sha256 over
             the sorted per-image `name:size:sha256` rows -- the per-image
             sha256 being the image's CONTENT, so the digest moves if any
             byte does.  The 1.9 GiB embedding table and the .txt are given
             by size only; they are named, not pinned.
  MANIFEST   the two caller-gated non-wid keys — `emb_row_bytes` (R-b) and
             `rs_f` (A2.5) — read back off the disk, because a 9B artifact
             that carries neither is one a reader would silently
             mis-address and mis-scale.
  FIT        `sw/hwmap.plan_weights` re-run against the REAL manifest with
             `wdir` set, which additionally stats every image and checks
             its size against `nrows * stride`.  Closes
             `evidence/qwen9b/g2/G2C_CHAIN.md`'s handoff 3, whose numbers
             were derived from shapes rather than from an emitted set.
  NCH=1      the SAME manifest offered to `plan_weights` with `rows_of=None`
             — the nch-independent pack every artifact frozen before R-c
             encodes — which must REFUSE, because the 9B pack is 3,902 MiB
             against a 1,280 MiB window.  That refusal is why there is no
             `<prefix>.e` in the 9B set, and it is recorded as a
             measurement rather than as a sentence.

Exit 0 = every check passed.
"""
import hashlib
import json
import os
import sys

TOP = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", ".."))
for _p in ("ref", "sw"):
    _q = os.path.join(TOP, _p)
    if _q not in sys.path:
        sys.path.insert(0, _q)

import seq_format as SF                                        # noqa: E402
import hwmap as HW                                             # noqa: E402

bad = []
MiB = 1 << 20
EXPECT_REFUSAL = False


def note(s):
    print("  " + s)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main():
    global EXPECT_REFUSAL
    argv = [a for a in sys.argv[1:] if a != "--expect-refusal"]
    # Only the FULL model overflows the 1,280 MiB window; a smoke set fits at
    # nch=1 and that is not a defect, so the demand is opt-in.
    EXPECT_REFUSAL = "--expect-refusal" in sys.argv
    base = argv[0]
    pre = argv[1] if len(argv) > 1 else base + ".e4"
    base = base if os.path.isabs(base) else os.path.join(TOP, base)
    pre = pre if os.path.isabs(pre) else os.path.join(TOP, pre)
    d = os.path.dirname(base)
    print("G4a 9B artifact inventory")
    note(f"base {os.path.relpath(base, TOP)}")
    note(f"seq  {os.path.relpath(pre, TOP)}")

    # ---------------- INVENTORY ----------------
    print("\nINVENTORY — hashed")
    for sfx in (".e4.seq", ".e4.seqdata.bin", ".e4.seq.json", ".weights.json"):
        p = (pre + sfx[3:]) if sfx.startswith(".e4") else (base + sfx)
        if not os.path.exists(p):
            bad.append(f"ABSENT {p}")
            note(f"ABSENT  {os.path.basename(p)}")
            continue
        note(f"{os.path.getsize(p):>14,} B  {sha(p)}  {os.path.basename(p)}")

    print("\nINVENTORY — sized")
    man, meta_man = HW.load_weights_manifest(base)
    imgs = sorted(man, key=lambda k: int(k))
    tot = 0
    # G4a fix round 1 (I4): the row carries the image's CONTENT hash.  It
    # used to be name and size only, which pins nothing a regeneration could
    # plausibly break -- two different 3.9 GiB packs with the same file sizes
    # would produce the same digest.  Hashing 249 images is a few seconds,
    # and the whole point of the line is to be the pin for a set that is
    # deliberately NOT committed.
    rows = []
    for wid in imgs:
        p = os.path.join(d, man[wid]["file"])
        if not os.path.exists(p):
            bad.append(f"ABSENT weight image {p}")
            continue
        sz = os.path.getsize(p)
        tot += sz
        rows.append(f"{man[wid]['file']}:{sz}:{sha(p)}")
    listsha = hashlib.sha256("\n".join(rows).encode()).hexdigest()
    note(f"{len(imgs):>14,} weight images, {tot:,} B = {tot / MiB:,.1f} MiB")
    note(f"{'':>14}  image-CONTENT sha256 (over the sorted "
         f"name:size:sha256 rows) {listsha}")
    for sfx in (".emb.bin", ".txt"):
        p = base + sfx
        if not os.path.exists(p):
            bad.append(f"ABSENT {p}")
            note(f"ABSENT  {os.path.basename(p)}")
            continue
        sz = os.path.getsize(p)
        note(f"{sz:>14,} B = {sz / MiB:,.1f} MiB  {os.path.basename(p)}")

    # ---------------- MANIFEST ----------------
    print("\nMANIFEST — the two caller-gated non-wid keys")
    erb = meta_man.get("emb_row_bytes")
    rsf = meta_man.get("rs_f")
    note(f"emb_row_bytes = {erb}   -> EMBLOG2 "
         f"{None if not erb else erb.bit_length() - 1}")
    note(f"rs_f          = {rsf}")
    if erb != 8192:
        bad.append(f"emb_row_bytes is {erb}, expected 8192 (2*H at H=4096)")
    if rsf != 7:
        bad.append(f"rs_f is {rsf}, expected 7 (plan A2)")

    # ---------------- the stream's own metadata ----------------
    meta = json.load(open(pre + ".seq.json"))
    print("\nSTREAM metadata")
    for k in ("format_version", "profile", "nch", "nrec", "stream_bytes",
              "stream_sha256", "seqdata_bytes", "seqdata_sha256", "steps",
              "loop_steps", "loop_structurally_safe", "expect_tokens",
              "prompt_fed", "shape_isa", "weight_repack"):
        note(f"{k:24s} {meta.get(k)!r}")
    wl = meta.get("weight_layout", {})
    note(f"{'weight_layout':24s} nch={wl.get('nch')} "
         f"chunk_rows={wl.get('chunk_rows')} default={wl.get('default')!r} "
         f"ilv_wids={wl.get('ilv_wids')}")

    # ---------------- FIT, against the real manifest ----------------
    print("\nFIT — plan_weights on the REAL manifest, wdir set")
    depth = int(wl["chunk_rows"])
    nch = int(wl["nch"])

    def rows_of(wid, nrows):
        return SF.chan_rows(int(nrows), nch,
                            wl["by_wid"].get(str(wid), wl["default"]), depth)

    got, tops = HW.plan_weights(man, wdir=d, nch=nch, rows_of=rows_of)
    plan = {int(k): v for k, v in meta["weights"].items()}
    mism = [w for w, p in plan.items() if list(got[int(w)]) != list(p["base"])]
    if mism:
        bad.append(f"plan_weights disagrees with the stream on wid(s) "
                   f"{sorted(mism)[:8]}")
    note(f"{len(plan)} images, every base identical to the stream's MVGOs: "
         f"{'YES' if not mism else 'NO'}")
    for c, t in enumerate(tops):
        note(f"chan {c}  {t:#010x}   {(t - HW.W_BASE) / MiB:8,.1f} MiB")
    note(f"window: {(max(tops) - HW.W_BASE) / MiB:,.1f} MiB of "
         f"{(HW.EMB_BASE - HW.W_BASE) / MiB:,.0f} MiB "
         f"= {100.0 * (max(tops) - HW.W_BASE) / (HW.EMB_BASE - HW.W_BASE):.1f} %")

    # ---------------- NCH=1: for the full model it must REFUSE ----------------
    print("\nNCH=1 — the nch-INDEPENDENT pack, offered to the same manifest")
    try:
        _, top1 = HW.plan_weights(man, nch=1)
    except Exception as e:
        note(f"REFUSED: {type(e).__name__}: {str(e).splitlines()[0]}")
        if not EXPECT_REFUSAL:
            note("(no refusal was demanded; recorded either way)")
    else:
        note(f"ACCEPTED at {top1:#x} = "
             f"{(top1 - HW.W_BASE) / MiB:,.1f} MiB of "
             f"{(HW.EMB_BASE - HW.W_BASE) / MiB:,.0f} MiB")
        if EXPECT_REFUSAL:
            bad.append("--expect-refusal was given and the nch-independent "
                       f"pack was ACCEPTED at top {top1:#x}")

    print("\nG4A_INVENTORY: %s (%d problem(s))"
          % ("PASS" if not bad else "FAIL", len(bad)))
    for b in bad:
        print("  ! " + b)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
