#!/usr/bin/env python3
"""Defect A, shown at the real 2B geometry: the wrong bytes, then the right
ones, both against the bf16 checkpoint row they are a quantization of.

Artifact: tb/scripts/w5/model_w8_2b_s1  (the R-d 2B W8 golden set)
  .emb.bin            1,017,118,720 B = 248,320 rows x 4096 B  (H = 2048)
  .weights.json       {"emb_row_bytes": 4096}

PRE-FIX reader (ref/seq_chat.py:978-979, :1213-1215 before this fix):
    n   = os.path.getsize(embf) // 2048
    emb = np.memmap(embf, dtype="<i2", mode="r").reshape(n, 1024)
`n * 1024 == vocab * H` holds exactly at H = 2048, so the reshape is LEGAL
and raises nothing.  Row `tok` of that view is half of row `tok // 2` of the
real table: the low half for even `tok`, the high half for odd.

POST-FIX reader: ref/seq_chat.load_emb(), stride from the manifest.

The float anchor is the checkpoint's own bf16 `embed_tokens.weight` row,
read straight out of the safetensors shard (numpy only, see `bf16_rows`).
The table is int16 Q7.8 scaled by res_scale (gen_model_script.py:517-523):

    emb_q = round(emb_f * res_scale * 2**RS_F)        RS_F = 8

model_w8_2b_s1 was generated with --res-scale=4 (evidence/qwen2b/rc/
RC_GATE.md:150-151), i.e. exactly 1024 counts per unit.

Run under FABLE5_MODEL=2b.
"""
import glob
import hashlib
import json
import os
import struct
import sys

import numpy as np

R = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(R, "ref"))

import seq_chat as SC                                          # noqa: E402
import layer_ref as LR                                         # noqa: E402
from model_select import TAG, REPO_DIR                         # noqa: E402

BASE = os.path.join(R, "tb", "scripts", "w5", "model_w8_2b_s1")
RES_SCALE, RS_F = 4, 8                       # RC_GATE.md:150; layer_fixed.RS_F
Q = RES_SCALE * (1 << RS_F)                  # counts per unit = 1024
TOKENS = [760, 6511, 314, 9338, 561]         # the gate A1 prompt + its answer
EMB_KEY = "model.language_model.embed_tokens.weight"


def bf16_rows(toks):
    """The checkpoint's own bf16 `embed_tokens` rows for `toks`, float32.

    Deliberately self-contained (numpy + struct + json, ~20 lines): a
    safetensors file is [u64 header_len][header JSON][raw tensor bytes], and
    BF16 is the top 16 bits of an IEEE f32.  Reading the header here instead
    of through ref/load_qwen35.py keeps this evidence reproducible while that
    module is being extended for the 4B/9B (sharded) checkpoints.

    Only the requested rows are touched — the 1 GiB tensor is never copied.
    """
    pat = os.path.join(os.path.expanduser("~/.cache/huggingface/hub"),
                       REPO_DIR, "snapshots", "*", "*.safetensors")
    hits = sorted(glob.glob(pat))
    if len(hits) != 1:
        raise SystemExit(f"expected one shard for {REPO_DIR}, got {hits}")
    path = hits[0]
    with open(path, "rb") as f:
        (hlen,) = struct.unpack("<Q", f.read(8))
        raw_hdr = f.read(hlen)
    hdr = json.loads(raw_hdr)
    ent = hdr[EMB_KEY]
    assert ent["dtype"] == "BF16", ent["dtype"]
    v, h = ent["shape"]
    b0, b1 = ent["data_offsets"]
    mm = np.memmap(path, dtype=np.uint8, mode="r")
    words = mm[8 + hlen + b0:8 + hlen + b1].view("<u2").reshape(v, h)
    f32 = {t: (np.asarray(words[t]).astype(np.uint32) << 16
               ).view(np.float32) for t in toks}
    return v, h, path, hashlib.sha256(raw_hdr).hexdigest(), f32


def main():
    if TAG != "2b":
        raise SystemExit(f"run me under FABLE5_MODEL=2b (got {TAG!r})")
    embf = BASE + ".emb.bin"
    nby = os.path.getsize(embf)
    man = json.load(open(BASE + ".weights.json"))
    rb = int(man["emb_row_bytes"])

    print("=" * 72)
    print("artifact      ", os.path.relpath(BASE, R))
    print(f"  .emb.bin     {nby:,} B")
    print(f"  manifest     emb_row_bytes = {rb} B")
    print(f"  model_select FABLE5_MODEL={TAG}  ->  LR.H = {LR.H}  "
          f"(2*H = {2 * LR.H} B)")
    print(f"  rows         {nby // rb:,}  (config vocab_size "
          f"{LR.CFG['vocab_size']:,})")

    # ---------------- the two readers ----------------
    n_old = nby // 2048
    old = np.memmap(embf, dtype="<i2", mode="r").reshape(n_old, 1024)
    print("\npre-fix  `size//2048` + `.reshape(n,1024)`  -> "
          f"shape {old.shape}   (NO EXCEPTION: {n_old}*1024 == "
          f"{nby // rb}*{LR.H} == {n_old * 1024:,})")

    new, vocab = SC.load_emb(BASE)
    print(f"post-fix `seq_chat.load_emb`                -> shape {new.shape}"
          f"   vocab {vocab:,}")

    v, h, cp, sha, ref = bf16_rows(sorted(set(TOKENS + [t // 2 for t in TOKENS])))
    print(f"\nbf16 anchor   {cp}")
    print(f"  header sha256 {sha[:32]}…   embed_tokens.weight {(v, h)}")
    print(f"  Q7.8 x res_scale {RES_SCALE}  ->  {Q} counts per unit")

    # ---------------- per token ----------------
    ok = True
    for tok in TOKENS:
        want = np.clip(np.round(np.asarray(ref[tok], dtype=np.float64) * Q),
                       -32768, 32767).astype(np.int64)
        got_new = np.asarray(new[tok], dtype=np.int64)
        got_old = np.asarray(old[tok], dtype=np.int64)
        half = tok % 2
        frag = np.asarray(
            np.clip(np.round(np.asarray(ref[tok // 2], dtype=np.float64) * Q),
                    -32768, 32767).astype(np.int64)
            )[half * 1024:(half + 1) * 1024]

        print("\n" + "-" * 72)
        print(f"token {tok}")
        print(f"  bf16 row      -> Q7.8*{RES_SCALE}, first 8 words: "
              f"{[int(x) for x in want[:8]]}   (len {len(want)})")
        print(f"  post-fix      first 8 words: {[int(x) for x in got_new[:8]]}   "
              f"(len {len(got_new)})")
        print(f"  pre-fix       first 8 words: {[int(x) for x in got_old[:8]]}   "
              f"(len {len(got_old)})")

        exact_new = len(got_new) == len(want) and np.array_equal(got_new, want)
        print(f"  post-fix == round(bf16 * {Q}) exactly : {exact_new}"
              f"   max|diff| {int(np.abs(got_new - want).max())}")

        # the pre-fix row is not even the right LENGTH, so score it against
        # the leading H/2 words of the true row and against the fragment it
        # actually is
        lead = want[:1024]
        d_true = int(np.abs(got_old - lead).max())
        is_frag = np.array_equal(got_old, frag)
        cos = float(np.dot(got_old, lead)
                    / (np.linalg.norm(got_old) * np.linalg.norm(lead) + 1e-30))
        print(f"  pre-fix  vs the first 1024 words of token {tok}: "
              f"max|diff| {d_true}, cosine {cos:+.4f}")
        print(f"  pre-fix  IS the {'high' if half else 'low'} half of token "
              f"{tok // 2}'s row : {is_frag}")
        ok = ok and exact_new and is_frag and not np.array_equal(got_old, lead)

    print("\n" + "=" * 72)
    print(f"DEMO: {'PASS' if ok else 'FAIL'}  — post-fix rows are the "
          f"checkpoint's rows; pre-fix rows are halves of token tok//2's")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
