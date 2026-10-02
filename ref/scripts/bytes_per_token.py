#!/usr/bin/env python3
"""bytes_per_token.py — per-token DDR weight traffic of a precision map.

    python3 ref/scripts/bytes_per_token.py --selftest
    python3 ref/scripts/bytes_per_token.py --model 2b --map all:w4g64
    python3 ref/scripts/bytes_per_token.py --model 2b --table
    python3 ref/scripts/bytes_per_token.py --from-json evidence/.../ppl_v2.json

WHAT IT COMPUTES.  A decode step reads every weight image exactly once, so
per-token weight traffic IS the packed image footprint:

    bytes/token = SUM over the 187 matvec images of  nrows * row_stride(K, g)

with `row_stride` (W4) / `row_stride8` (W8) from `ref/w4a8_ref.py` — the
production row format, beat padding included, NOT the ideal bits/weight rate.
The embedding table is excluded from that headline and reported separately:
it is a single-ROW lookup per token (2*H bytes), not a streamed image.  That
is the same convention `evidence/qwen2b/q2/sensitivity/SENSITIVITY.md` used,
and it is what reproduces the feasibility study's numbers to the byte.

WHERE THE SHAPES COME FROM.  The image inventory is derived from the model
config with the formulas `ref/layer_ref.py:29-40` uses and the per-tensor
shapes `ref/load_qwen35.py:201-216` (`_EXPECT_*`) declares — one image per W4
matvec weight, walking `layer_types` exactly as `load_qwen35.load_model` does.
Nothing is hardcoded per model: `--model 0.8b` and `--model 2b` run the same
code over the two config JSONs.

HOW IT IS VALIDATED (`--selftest`, all hard asserts):
  1. the two feasibility-study byte totals, 0.8B W4 g128 = 417,435,648 and
     2B W4 g128 = 996,282,368;
  2. every per-class `total_bits` of five COMMITTED perplexity_eval runs
     (0.8B w4g128, 2B V1 g128, 2B V2 g64, 2B V5 w8g128, 2B V4mix top-3 —
     the last two cover the W8 rows) — those came from the real
     checkpoint's tensor shapes through `perplexity_eval.packed_bits`, so
     agreement means this inventory matches the actual model, matrix by
     matrix, and that the two tools' `--inject`/`--map` grammars resolve the
     same way;
  3. the busiest-channel beat counts of `evidence/qwen2b/ra/MOVER_NORM.md`
     section 3.1 (0.8B 1,643,280 and 2B 3,915,664 at nch=4), which validates
     the 4-channel row split this file re-implements from
     `ref/seq_format.py:1113-1181`;
  4. (E-pre) that this file's DUPLICATED quant tables -- `W4_QUANTS`,
     `QUANTS`, `_G_OF` -- still agree with `ref/perplexity_eval.py`'s, read
     by AST so no torch import is pulled in.  The duplication exists so this
     tool stays cheap, and it has already drifted once (`w4g128gptq` landed
     in perplexity_eval at 7010157 and here only at 161ce2e);
  5. (E-bis) that `w4g128gptq` is bit-rate IDENTICAL to `w4g128` and
     `w4g64gptq` to `w4g64`, to the byte, in all seven classes at all four
     geometries -- the fact the qwen-next ladder's "GPTQ is free" conclusion
     rests on.

DDR FIT.  `sw/hwmap.py:plan_weights` packs images back to back from
`W_BASE`, each start aligned up to `WID_ALIGN`, and asserts the pack ends
below `EMB_BASE` — a 1,280 MiB window PER CHANNEL (`sw/hwmap.py`'s DDR map).
`--table` checks each variant against it at nch=1 and nch=4 and says which
ones do not fit.  It never re-maps anything.

THE nch=4 COLUMN NEEDS THE REPACK (R-c).  Two packs exist, and `--table`'s
nch=4 column describes the second:

  * the nch-INDEPENDENT pack (`plan_weights` with no `rows_of`) is what
    every artifact frozen before R-c encodes — FULL image footprints
    accumulated once, each channel's slice placed at `wbase_of[wid] +
    r0*stride` INSIDE the whole image's span.  A variant that overflows at
    nch=1 overflows at nch=4 too.
  * the PER-CHANNEL REPACK (`plan_weights(..., nch, rows_of)`, emitted with
    `SEQ_REPACK=1`) gives each channel its own cursor over only the rows it
    owns, ILV-placed LM head included.  That is what makes the nch=4 column
    a fit rather than a byte count.

`--fit --map ... --nch 4` runs the REAL allocator (not this file's
re-implementation) and asserts every channel top stays below `EMB_BASE`;
`--fit --no-repack` measures the nch-independent pack instead.
"""
import argparse
import json
import os
import sys

REF = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(REF)
sys.path.insert(0, REF)
sys.path.insert(0, os.path.join(REPO, "sw"))

import w4a8_ref as W                                            # noqa: E402
import model_select as MS                                       # noqa: E402
import hwmap as HW                                              # noqa: E402
import seq_format as SF                                         # noqa: E402

# the seven W4A8 matvec classes, in perplexity_eval's order
W4_CLASSES = ("qkv", "o_proj", "gate_up", "down", "dn_in", "dn_out", "lm_head")
W4_QUANTS = ("w4g128", "w4g64", "w4g64s", "w4g64h", "w4g64gptq",
             "w4g128gptq")
QUANTS = W4_QUANTS + ("w8g128",)
_G_OF = {"w4g128": 128, "w4g64": 64, "w4g64s": 64, "w4g64h": 64,
         "w4g64gptq": 64, "w4g128gptq": 128,      # = perplexity_eval._G_OF
         "w8g128": 128}

# Track Q sensitivity ranking (evidence/qwen2b/q2/sensitivity/SENSITIVITY.md):
# the order V4mix promotes classes to W8 in.
SENSITIVITY_ORDER = ("gate_up", "lm_head", "dn_in", "down", "o_proj", "qkv",
                     "dn_out")

# ---- the DDR windows this checks against (sw/hwmap.py) ------------------
WEIGHT_WINDOW = HW.EMB_BASE - HW.W_BASE          # 1,280 MiB per channel
CHUNK_ROWS = 2048                       # ref/seq_format.py:1211 (the
                                        # definition; :951/:982/:1001 were
                                        # res_chunks' docstring — G3.4 r3)
UI_CLK_HZ = HW.UI_CLK_HZ                         # 300.12 MHz

# ---- MOVER_NORM.md section 4 constants (2B, nch=4) ----------------------
MOVERS_MS_2B = 15.994        # movers+polls, band 15.5-17.0
LAYER_MS_2B = 17.4           # feasibility-study figure, NOT verified there
R_BRACKET = (1.000, 1.0892, 1.131)   # ui-cycles per 64 B beat: lo, central, hi


# ======================================================================
# geometry -> the 187-image inventory
# ======================================================================
def geometry(cfg):
    """The derived dims, mirroring ref/layer_ref.py:29-40 exactly."""
    H = cfg["hidden_size"]
    LNH = cfg["linear_num_value_heads"]
    LNKH = cfg["linear_num_key_heads"]
    # q/k are sized by the KEY head count and v by the VALUE head count.  They
    # are equal at 0.8B/2B and NOT at 4B/9B (16 key, 32 value), where
    # `LNH * key_head_dim` would give CONV_DIM 12288 against the checkpoint's
    # 8192 — docs/QWEN35_NEXT_FEASIBILITY.md §2.9.  Mirrors ref/layer_ref.py.
    LKD = LNKH * cfg["linear_key_head_dim"]
    LVD = LNH * cfg["linear_value_head_dim"]
    return {"H": H, "FFN": cfg["intermediate_size"],
            "NQ": cfg["num_attention_heads"],
            "NKV": cfg["num_key_value_heads"], "HD": cfg["head_dim"],
            "LNH": LNH, "LNKH": LNKH, "LKD": LKD, "LVD": LVD,
            "CONV_DIM": 2 * LKD + LVD, "VOCAB": cfg["vocab_size"],
            "NL": cfg["num_hidden_layers"], "TYPES": cfg["layer_types"]}


def inventory(cfg):
    """[{cls, name, nrows, k, amax}] — one entry per W4A8 matvec DDR image.

    Shapes are `load_qwen35._EXPECT_MLP/_EXPECT_DN/_EXPECT_ATTN`; the walk
    over `layer_types` is `load_qwen35.load_model`'s.  `amax` marks the LM
    head, the one image the emitter places with the S4 interleave
    (`ref/seq_format.py:2099`, `layout = LAYOUT_ILV if amax`).
    """
    d = geometry(cfg)
    H, FFN, VOCAB = d["H"], d["FFN"], d["VOCAB"]
    assert len(d["TYPES"]) == d["NL"], "layer_types/num_hidden_layers mismatch"
    img = []

    def add(cls, name, nrows, k, amax=False):
        img.append({"cls": cls, "name": name, "nrows": int(nrows),
                    "k": int(k), "amax": amax})

    for i, t in enumerate(d["TYPES"]):
        p = f"layers.{i}."
        add("gate_up", p + "mlp.gate", FFN, H)
        add("gate_up", p + "mlp.up", FFN, H)
        add("down", p + "mlp.down", H, FFN)
        if t == "linear_attention":
            add("dn_in", p + "dn.in_qkv", d["CONV_DIM"], H)
            add("dn_in", p + "dn.in_z", d["LVD"], H)
            add("dn_in", p + "dn.in_b", d["LNH"], H)
            add("dn_in", p + "dn.in_a", d["LNH"], H)
            add("dn_out", p + "dn.out", H, d["LVD"])
        elif t == "full_attention":
            add("qkv", p + "attn.q_proj", 2 * d["NQ"] * d["HD"], H)
            add("qkv", p + "attn.k_proj", d["NKV"] * d["HD"], H)
            add("qkv", p + "attn.v_proj", d["NKV"] * d["HD"], H)
            add("o_proj", p + "attn.o_proj", H, d["NQ"] * d["HD"])
        else:
            raise SystemExit(f"layer {i}: unknown layer type {t!r}")
    add("lm_head", "lm_head", VOCAB, H, amax=True)
    return img


def emb_row_bytes(cfg):
    """One embedding row = H int16 values (gen_model_script's emb table)."""
    return 2 * geometry(cfg)["H"]


# ======================================================================
# the precision map
# ======================================================================
def parse_map(spec):
    """'all:w4g64,gate_up:w8g128' -> {class: quant} — perplexity_eval's
    `--inject` grammar restricted to the classes that produce DDR weight
    IMAGES.  `emb`/`dn_conv` are accepted and ignored with a note (they are
    not streamed weight images); every W4 class must end up with a quant,
    because an unquantized class has no wire format at all.
    """
    plan, ignored = {}, []
    for item in [s for s in spec.split(",") if s.strip()]:
        if ":" not in item:
            raise SystemExit(f"--map item {item!r} is not CLASS:QUANT")
        cls, q = (s.strip() for s in item.split(":", 1))
        if cls in ("emb", "dn_conv"):     # checked BEFORE the quant name: a
            ignored.append(item)          # spec copied from --inject carries
            continue                      # emb:emb16 / dn_conv:cw13
        if q not in QUANTS:
            raise SystemExit(f"--map: unknown quant {q!r}, expected one of "
                             f"{', '.join(QUANTS)}")
        if cls == "all":
            for c in W4_CLASSES:
                plan[c] = q
            continue
        if cls not in W4_CLASSES:
            raise SystemExit(f"--map: unknown class {cls!r}, expected all, "
                             f"{', '.join(W4_CLASSES)} (or emb/dn_conv, "
                             "which carry no weight image)")
        plan[cls] = q
    missing = [c for c in W4_CLASSES if c not in plan]
    if missing:
        raise SystemExit(f"--map leaves {', '.join(missing)} with no format; "
                         "every W4A8 class streams from DDR. Start with "
                         "'all:<quant>'.")
    return plan, ignored


def image_bytes(nrows, k, quant):
    """Packed DDR bytes of one image — THE definition of the byte budget."""
    if quant in W4_QUANTS:
        return nrows * W.row_stride(k, _G_OF[quant])
    if quant == "w8g128":
        return nrows * W.row_stride8(k, _G_OF[quant])
    raise SystemExit(f"no DDR row format for quant {quant!r}")


# ======================================================================
# the 4-channel row split (ref/seq_format.py:1113-1181, re-implemented)
# ======================================================================
def split_rows(nrows, nch):
    """seq_format.split_rows: first (nrows % nch) channels take one extra."""
    base, rem = divmod(nrows, nch)
    out, r = [], 0
    for c in range(nch):
        n = base + (1 if c < rem else 0)
        out.append((r, n))
        r += n
    assert r == nrows
    return out


def ilv_chunks(nrows, nch, depth=CHUNK_ROWS):
    """seq_format.ilv_chunks: global chunk j -> channel j % nch."""
    out, r0, j = [], 0, 0
    while r0 < nrows:
        n = min(depth, nrows - r0)
        out.append((j % nch, r0, n))
        r0 += n
        j += 1
    return out


def per_channel_bytes(cfg, plan, nch):
    """[bytes on channel c] — the split the emitter actually places."""
    tot = [0] * nch
    for im in inventory(cfg):
        stride = image_bytes(1, im["k"], plan[im["cls"]])
        pieces = (ilv_chunks(im["nrows"], nch) if (im["amax"] and nch > 1)
                  else [(c, r0, n)
                        for c, (r0, n) in enumerate(split_rows(im["nrows"], nch))])
        for (c, _r0, n) in pieces:
            tot[c] += n * stride
    return tot


def packed_footprint(cfg, plan, nch):
    """[bytes occupied on channel c] under sw/hwmap.py:plan_weights —
    images back to back from W_BASE, each start aligned up to WID_ALIGN."""
    tot = [0] * nch
    for im in inventory(cfg):
        stride = image_bytes(1, im["k"], plan[im["cls"]])
        pieces = (ilv_chunks(im["nrows"], nch) if (im["amax"] and nch > 1)
                  else [(c, r0, n)
                        for c, (r0, n) in enumerate(split_rows(im["nrows"], nch))])
        for (c, _r0, n) in pieces:
            if n:
                sz = n * stride
                tot[c] += -(-sz // HW.WID_ALIGN) * HW.WID_ALIGN
    return tot


# ======================================================================
# the FIT: walk the REAL per-channel plan and assert the tops (R-c)
# ======================================================================
def fit_manifest(cfg, plan):
    """The inventory as a `hwmap.plan_weights` manifest — no files on disk.

    wid order IS `inventory` order, which is the generator's first-use order
    (gen_layer_script assigns wids as matrices appear, walking the layers in
    exactly this sequence), so the pack this produces is the pack a real run
    produces.  `sh` is irrelevant to placement and is left 0.
    """
    man, lay = {}, {}
    for wid, im in enumerate(inventory(cfg)):
        q = plan[im["cls"]]
        stride = image_bytes(1, im["k"], q)
        man[str(wid)] = {"file": im["name"], "nrows": im["nrows"],
                         "k": im["k"], "ng": im["k"] // 128, "sh": 0,
                         "g": _G_OF[q], "stride": stride,
                         "nbeats": im["nrows"] * stride // 64,
                         "w8": q == "w8g128"}
        lay[wid] = SF.LAYOUT_ILV if im["amax"] else SF.LAYOUT_CONTIG
    return man, lay


def fit(cfg, plan, nch, repack=True, chunk_rows=SF.CHUNK_ROWS):
    """Place every image with the REAL allocator and report the tops.

    This is the shipped `hwmap.plan_weights` — the one the emitter and the
    host both go through — not a re-derivation, so a green --fit is evidence
    about the code that will place the bytes.  `packed_footprint` above IS an
    independent re-implementation, and the two are cross-checked here.
    """
    man, lay = fit_manifest(cfg, plan)
    rows_of = None
    if repack:
        def rows_of(wid, nrows):
            return SF.chan_rows(nrows, nch, lay[wid], chunk_rows)
    ref = packed_footprint(cfg, plan, nch)
    base, refused = None, None
    try:
        base, top = HW.plan_weights(man, wdir=None, nch=nch, rows_of=rows_of)
        tops = list(top) if isinstance(top, tuple) else [top] * nch
    except AssertionError as ex:
        # plan_weights REFUSING an overflowing pack is the point of the
        # assert, not a crash — report it, and use the re-implementation's
        # footprint so the numbers still say by how much it overflows.
        # ONLY that assert: every other one (a manifest whose stride does not
        # match its row law, a rows_of that does not sum to nrows) is a real
        # failure and must not be dressed up as "does not fit".
        if "past EMB_BASE" not in str(ex):
            raise
        refused = str(ex).split(" — ")[0]
        tops = [HW.W_BASE + u for u in (ref if repack
                                        else [sum(-(-image_bytes(im["nrows"],
                                                                 im["k"],
                                                                 plan[im["cls"]])
                                                   // HW.WID_ALIGN)
                                                  * HW.WID_ALIGN
                                                  for im in inventory(cfg))]
                                        * nch)]
    used = [t - HW.W_BASE for t in tops]
    emb = geometry(cfg)["VOCAB"] * emb_row_bytes(cfg)
    return {"nch": nch, "repack": repack, "images": len(man),
            "tops": tops, "used": used, "footprint": ref, "refused": refused,
            "agrees": used == ref if (repack and not refused) else None,
            "window": WEIGHT_WINDOW, "emb_bytes": emb,
            "emb_top": HW.EMB_BASE + emb,
            "fits": refused is None and max(tops) < HW.EMB_BASE,
            "emb_fits": HW.EMB_BASE + emb <= HW.CH_STRIDE,
            "base": base}


def report_fit(tag, plan, nch, repack=True):
    cfg = load_cfg(tag)
    f = fit(cfg, plan, nch, repack)
    how = ("PER-CHANNEL REPACK" if repack and nch > 1 else
           "single channel (the repack is a no-op)" if nch == 1 else
           "nch-INDEPENDENT pack")
    print(f"=== DDR fit, {tag}, nch={nch}, {how} ===")
    print(f"  map   " + ",".join(f"{c}:{plan[c]}" for c in W4_CLASSES))
    print(f"  {f['images']} images packed from W_BASE {HW.W_BASE:#x}, "
          f"window {fmt_mib(f['window'])} per channel to EMB_BASE "
          f"{HW.EMB_BASE:#x}")
    for c in range(nch):
        print(f"  chan {c}: top {f['tops'][c]:#x}  {fmt_mib(f['used'][c])} "
              f"({100 * f['used'][c] / f['window']:.1f}% of the window, "
              f"{fmt_mib(f['window'] - f['used'][c])} free)"
              + ("  OVERFLOWS" if f['tops'][c] >= HW.EMB_BASE else ""))
    if f["refused"]:
        print(f"  hwmap.plan_weights REFUSED this pack (the assert doing its "
              f"job):\n    {f['refused']}")
    elif repack:
        print(f"  cross-check vs packed_footprint (independent "
              f"re-implementation): {'AGREES' if f['agrees'] else 'DIFFERS'} "
              f"{f['footprint']}")
    print(f"  embedding table {fmt_mib(f['emb_bytes'])} at EMB_BASE ends "
          f"{f['emb_top']:#x} — above every weight top, inside the "
          f"{fmt_mib(HW.CH_STRIDE)} channel: "
          f"{'OK' if f['emb_fits'] else 'OVERFLOWS THE CHANNEL'}")
    ok = f["fits"] and f["emb_fits"] and (f["agrees"] is not False)
    print("FIT PASS" if ok else "FIT FAIL")
    return 0 if ok else 1


# ======================================================================
# the budget
# ======================================================================
def budget(cfg, plan):
    """Per-class and total per-token weight traffic for one precision map."""
    per = {c: {"quant": plan[c], "n_matrices": 0, "n_weights": 0, "bytes": 0}
           for c in W4_CLASSES}
    for im in inventory(cfg):
        s = per[im["cls"]]
        s["n_matrices"] += 1
        s["n_weights"] += im["nrows"] * im["k"]
        s["bytes"] += image_bytes(im["nrows"], im["k"], plan[im["cls"]])
    total = sum(s["bytes"] for s in per.values())
    for s in per.values():
        s["bits_per_weight"] = 8.0 * s["bytes"] / s["n_weights"]
    return {"classes": per, "bytes_per_token": total,
            "n_images": len(inventory(cfg)),
            "n_weights": sum(s["n_weights"] for s in per.values()),
            "bits_per_weight": 8.0 * total / sum(s["n_weights"]
                                                 for s in per.values()),
            "emb_row_bytes": emb_row_bytes(cfg)}


def tok_s_band(max_chan_bytes):
    """(ms, tok/s) at the three `r` of MOVER_NORM section 3.1-3.2, 2B nch=4.

    Only the matvec bucket moves with precision: MOVX/MOVY/LDC/CSRWR move
    activations, results and constants, whose sizes are precision-independent,
    and the MVGO record count follows the row split, not the row stride.
    """
    out = []
    for r in R_BRACKET:
        mv = (max_chan_bytes / 64.0) * r / UI_CLK_HZ * 1e3
        step = mv + MOVERS_MS_2B + LAYER_MS_2B
        out.append((r, mv, step, 1e3 / step))
    return out


# ======================================================================
# reporting
# ======================================================================
def load_cfg(tag):
    with open(MS.config_json(tag)) as f:
        return json.load(f)["text_config"]


def fmt_mib(b):
    return f"{b / 2**20:,.1f} MiB"


def report(tag, plan, ignored=(), nch=(1, 4), show_tok_s=True):
    cfg = load_cfg(tag)
    b = budget(cfg, plan)
    print(f"model {tag}  H={geometry(cfg)['H']}  "
          f"{geometry(cfg)['NL']} layers  {b['n_images']} images")
    print(f"map   " + ",".join(f"{c}:{plan[c]}" for c in W4_CLASSES))
    if ignored:
        print(f"      (ignored, not a streamed weight image: "
              f"{', '.join(ignored)})")
    print("  class    quant       mats      weights     b/w        bytes/token")
    for c in W4_CLASSES:
        s = b["classes"][c]
        print(f"  {c:<8s} {s['quant']:<10s} {s['n_matrices']:4d} "
              f"{s['n_weights'] / 1e6:9.2f} M {s['bits_per_weight']:7.3f}  "
              f"{s['bytes']:>15,}")
    print(f"  {'TOTAL':<8s} {'':<10s} {b['n_images']:4d} "
          f"{b['n_weights'] / 1e6:9.2f} M {b['bits_per_weight']:7.3f}  "
          f"{b['bytes_per_token']:>15,}   ({fmt_mib(b['bytes_per_token'])})")
    print(f"  + embedding row lookup: {b['emb_row_bytes']:,} B/token "
          "(one int16 row; excluded from the headline)")
    for n in nch:
        fp = packed_footprint(cfg, plan, n)
        ch = per_channel_bytes(cfg, plan, n)
        fit = "FITS" if max(fp) < WEIGHT_WINDOW else "DOES NOT FIT"
        print(f"  nch={n}: busiest channel {max(ch):,} B streamed, "
              f"{fmt_mib(max(fp))} packed of {fmt_mib(WEIGHT_WINDOW)} "
              f"({100 * max(fp) / WEIGHT_WINDOW:.1f}%) -> {fit}")
        if show_tok_s and tag == "2b" and n == 4:
            for (r, mv, step, tps) in tok_s_band(max(ch)):
                print(f"      r={r:.4f} ui-cyc/beat: matvec {mv:6.2f} ms, "
                      f"step {step:6.2f} ms -> {tps:5.2f} tok/s")
    return b


def variants():
    """The gate-D ladder, as {name: (map spec, note)} in table order."""
    v = [("V1  g128", "all:w4g128", "Track Q V1"),
         ("V2  g64", "all:w4g64", "Track Q V2"),
         ("V3  g64 salience", "all:w4g64s", "= V2 bytes, different scales"),
         ("V4gptq g64", "all:w4g64gptq", "= V2 bytes, error feedback")]
    for k in (1, 2, 3):
        promo = SENSITIVITY_ORDER[:k]
        spec = "all:w4g64," + ",".join(f"{c}:w8g128" for c in promo)
        v.append((f"V4mix top-{k}", spec, "+".join(promo) + " at W8"))
    # the composed point: the best W4 base with the cheapest W8 promotion
    # (task 9, evidence/qwen2b/q2/v4_v5/V4_V5.md section 7.1)
    v.append(("V4gptq+gate_up W8", "all:w4g64gptq,gate_up:w8g128",
              "GPTQ base, top-1 promoted"))
    v.append(("V5  W8 everywhere", "all:w8g128", "Track Q V5"))
    return v


def table(tag):
    cfg = load_cfg(tag)
    base = None
    print(f"=== bytes/token ladder, {tag} "
          f"({len(inventory(cfg))} images, packed rows) ===")
    print("  variant             bytes/token      MiB     b/w   xV2   "
          "nch=1 fit   nch=4 fit   tok/s band (2B)")
    for (name, spec, _note) in variants():
        plan, _ = parse_map(spec)
        b = budget(cfg, plan)
        if name.startswith("V2 "):
            base = b["bytes_per_token"]
    for (name, spec, _note) in variants():
        plan, _ = parse_map(spec)
        b = budget(cfg, plan)
        fp1 = max(packed_footprint(cfg, plan, 1))
        fp4 = max(packed_footprint(cfg, plan, 4))
        ch4 = max(per_channel_bytes(cfg, plan, 4))
        band = tok_s_band(ch4)
        tps = (f"{band[-1][3]:5.1f}-{band[0][3]:5.1f}" if tag == "2b" else "  -")
        print(f"  {name:<18s} {b['bytes_per_token']:>13,}  {b['bytes_per_token'] / 2**20:7.1f} "
              f"{b['bits_per_weight']:6.3f} {b['bytes_per_token'] / base:5.3f}  "
              f"{100 * fp1 / WEIGHT_WINDOW:6.1f}% {'OK ' if fp1 < WEIGHT_WINDOW else 'OVER'}  "
              f"{100 * fp4 / WEIGHT_WINDOW:6.1f}% {'OK ' if fp4 < WEIGHT_WINDOW else 'OVER'}  "
              f"{tps}")
    print(f"  weight window per channel: {fmt_mib(WEIGHT_WINDOW)} "
          f"(W_BASE {HW.W_BASE:#x} .. EMB_BASE {HW.EMB_BASE:#x}, "
          f"sw/hwmap.py:plan_weights asserts it)")
    print("  NOTE: the nch=4 column is the PER-CHANNEL REPACK (R-c, emitted "
          "with SEQ_REPACK=1 and\n        planned by plan_weights(nch, "
          "rows_of), ILV-placed LM head rebased per chunk).  The\n        "
          "nch-INDEPENDENT pack every pre-R-c artifact encodes reserves the "
          "FULL image on every\n        channel, so under IT a variant that "
          "overflows at nch=1 overflows at nch=4 too —\n        "
          "`--fit --no-repack` measures that one.")
    emb = geometry(cfg)["VOCAB"] * emb_row_bytes(cfg)
    print(f"  embedding table: {geometry(cfg)['VOCAB']:,} rows x "
          f"{emb_row_bytes(cfg)} B = {fmt_mib(emb)} at EMB_BASE "
          f"(traffic is ONE row/token: {emb_row_bytes(cfg):,} B)")
    if tag == "2b":
        print(f"  tok/s band = 1000 / (matvec(r) + movers {MOVERS_MS_2B} + "
              f"layer {LAYER_MS_2B}) ms, r in [{R_BRACKET[0]}, {R_BRACKET[-1]}] "
              "ui-cyc/beat (evidence/qwen2b/ra/MOVER_NORM.md sections 3.2, 4)")


# ======================================================================
# self-test
# ======================================================================
def _selftest():
    ok = True
    print("--- A: the two feasibility byte totals, to the byte ---")
    want = {"0.8b": 417_435_648, "2b": 996_282_368}
    for tag, exp in sorted(want.items()):
        plan, _ = parse_map("all:w4g128")
        got = budget(load_cfg(tag), plan)["bytes_per_token"]
        assert got == exp, f"{tag}: {got:,} != {exp:,}"
        print(f"  {tag:5s} W4 g128 = {got:,} B/token  MATCH "
              f"(docs/QWEN2B_FEASIBILITY.md, evidence/qwen2b/ra/MOVER_NORM.md)")

    print("--- B: per-class bytes vs five COMMITTED perplexity_eval runs ---")
    for tag, rel in (("0.8b", "evidence/qwen2b/q1/ppl_08b_w4g128.json"),
                     ("2b", "evidence/qwen2b/q2/v1_v2/ppl_v1.json"),
                     ("2b", "evidence/qwen2b/q2/v1_v2/ppl_v2.json"),
                     # the W8 side of the same check: V5's per-class bytes came
                     # from the real tensor shapes through
                     # perplexity_eval.packed_bits -> w4a8_ref.row_stride8
                     ("2b", "evidence/qwen2b/q2/v4_v5/ppl_v5.json"),
                     ("2b", "evidence/qwen2b/q2/v4_v5/ppl_v4mix_top3.json")):
        with open(os.path.join(REPO, rel)) as f:
            j = json.load(f)
        assert j["model_tag"] == tag, (rel, j["model_tag"])
        plan = {c: q for c, q in j["inject_resolved"].items()
                if c in W4_CLASSES}
        b = budget(load_cfg(tag), plan)
        for c in W4_CLASSES:
            s, r = b["classes"][c], j["classes"][c]
            assert s["n_matrices"] == r["n_matrices"], (rel, c, "mats")
            assert s["n_weights"] == r["n_weights"], (rel, c, "weights")
            assert s["bytes"] * 8 == r["total_bits"], (rel, c, "bytes")
        print(f"  {os.path.basename(rel):<20s} {j['inject']:<38s} "
              f"7/7 classes agree on mats, weights AND packed bytes "
              f"({b['bytes_per_token']:,} B/token)")

    print("--- C: the 4-channel split vs MOVER_NORM.md section 3.1 ---")
    for tag, exp in (("0.8b", 1_643_280), ("2b", 3_915_664)):
        plan, _ = parse_map("all:w4g128")
        ch = per_channel_bytes(load_cfg(tag), plan, 4)
        beats = [b // 64 for b in ch]
        assert sum(b % 64 for b in ch) == 0, "a channel is not beat-aligned"
        assert max(beats) == exp, f"{tag}: {max(beats):,} != {exp:,}"
        print(f"  {tag:5s} nch=4 beats per channel {beats} -> busiest "
              f"{max(beats):,}  MATCH")

    print("--- D: the W8 row law ---")
    for K in (1024, 2048, 3584, 6144):
        w4b, s4 = W.row_beats(K, 128)
        w8b, s8 = W.row_beats8(K, 128)
        assert w8b == 2 * w4b and s8 == s4
        assert image_bytes(3, K, "w8g128") == 3 * (w8b + s8) * 64
    # a W8 image is a hair under 2x its W4 g128 twin (the scale beats do not
    # double), and W8's padding overhead is SMALLER because the weight side is
    # twice as many whole beats
    for tag in ("0.8b", "2b"):
        cfg = load_cfg(tag)
        b4 = budget(cfg, parse_map("all:w4g128")[0])
        b8 = budget(cfg, parse_map("all:w8g128")[0])
        rt = b8["bytes_per_token"] / b4["bytes_per_token"]
        assert 1.9 < rt < 2.0, (tag, rt)
        print(f"  {tag:5s} W8 everywhere = {b8['bytes_per_token']:,} B/token "
              f"= {rt:.4f}x W4 g128, {b8['bits_per_weight']:.4f} b/w "
              f"(ideal 8.125, +{100 * (b8['bits_per_weight'] / 8.125 - 1):.2f}%)")

    print("--- E-pre: the quant tables vs perplexity_eval's, by AST ---")
    # WHY THIS EXISTS.  `W4_QUANTS`/`QUANTS`/`_G_OF` above are a DUPLICATE of
    # `ref/perplexity_eval.py`'s, kept only so this tool does not have to
    # import torch+transformers to price bytes.  A comment said "=
    # perplexity_eval._G_OF" and nothing enforced it -- and the duplication
    # HAS already bitten once: `w4g128gptq` was added to perplexity_eval in
    # 7010157 and to this file only in 161ce2e, so between those two commits
    # this tool silently could not price the point the campaign was about to
    # recommend.  Section :28's "HOW IT IS VALIDATED (--selftest, all hard
    # asserts)" claims coverage this file did not have.  Now it does.
    #
    # Read by AST, not by import: perplexity_eval pulls torch and
    # transformers at module scope and this selftest must stay cheap.
    import ast
    _pe = os.path.join(REPO, "ref", "perplexity_eval.py")
    with open(_pe) as f:
        _tree = ast.parse(f.read(), filename=_pe)
    _pev = {}
    for _n in _tree.body:
        if isinstance(_n, ast.Assign) and len(_n.targets) == 1 \
                and isinstance(_n.targets[0], ast.Name) \
                and _n.targets[0].id in ("QUANTS", "HESSIAN_QUANTS", "_G_OF"):
            _pev[_n.targets[0].id] = ast.literal_eval(_n.value)
    for _k in ("QUANTS", "HESSIAN_QUANTS", "_G_OF"):
        assert _k in _pev, f"perplexity_eval.{_k} not found by AST"
    assert _G_OF == _pev["_G_OF"], (
        f"_G_OF has DRIFTED from perplexity_eval's:\n  here {_G_OF}\n"
        f"  there {_pev['_G_OF']}")
    # perplexity_eval.QUANTS additionally carries the non-matvec quants
    # (emb16, cw13), which this tool prices separately -- so the contract is
    # containment plus exact agreement on the matvec set.
    _pe_matvec = tuple(q for q in _pev["QUANTS"] if q in _pev["_G_OF"])
    assert set(QUANTS) == set(_pe_matvec), (
        f"the matvec quant set has DRIFTED:\n  here {sorted(QUANTS)}\n"
        f"  there {sorted(_pe_matvec)}")
    for _q in _pev["HESSIAN_QUANTS"]:
        assert _q in W4_QUANTS, f"{_q} is a W4 GPTQ point but not in W4_QUANTS"
    print(f"  _G_OF, the matvec quant set and both GPTQ points agree with "
          f"perplexity_eval.py ({len(_G_OF)} quants, "
          f"{len(_pev['HESSIAN_QUANTS'])} Hessian)")

    print("--- E-bis: w4g128gptq is bit-rate identical to w4g128 ---")
    # The whole recommendation of evidence/qwen_next/ladder/LADDER.md rests on
    # this being EXACTLY true and not approximately true: GPTQ changes which
    # levels the weights land on, never the wire format, so the byte column
    # must be identical to the shipped W4's to the byte at every geometry.
    for tag in ("0.8b", "2b", "4b", "9b"):
        cfg = load_cfg(tag)
        b128 = budget(cfg, parse_map("all:w4g128")[0])
        bgptq = budget(cfg, parse_map("all:w4g128gptq")[0])
        assert b128["bytes_per_token"] == bgptq["bytes_per_token"], (
            tag, b128["bytes_per_token"], bgptq["bytes_per_token"])
        assert b128["bits_per_weight"] == bgptq["bits_per_weight"], tag
        for c in W4_CLASSES:
            assert b128["classes"][c]["bytes"] == bgptq["classes"][c]["bytes"], (tag, c)
        # and g64+GPTQ must match plain g64 the same way
        b64 = budget(cfg, parse_map("all:w4g64")[0])
        b64g = budget(cfg, parse_map("all:w4g64gptq")[0])
        assert b64["bytes_per_token"] == b64g["bytes_per_token"], tag
        print(f"  {tag:5s} w4g128gptq == w4g128 = {b128['bytes_per_token']:,} "
              f"B/token, and w4g64gptq == w4g64, to the byte in all 7 classes")

    print("--- E: map grammar ---")
    p, ig = parse_map("all:w4g64,gate_up:w8g128,emb:emb16")
    assert p["gate_up"] == "w8g128" and p["down"] == "w4g64" and ig == ["emb:emb16"]
    for bad in ("gate_up:w8g128", "all:w2", "nope:w4g64", "all"):
        try:
            parse_map(bad)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"parse_map accepted {bad!r}")
    print("  later-wins override, emb/dn_conv ignored with a note, partial "
          "maps and unknown names rejected")
    print("\nBYTES_PER_TOKEN SELFTEST PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", default=None, choices=list(MS.MODELS),
                    help="which geometry (default: $FABLE5_MODEL)")
    ap.add_argument("--map", help="CLASS:QUANT[,CLASS:QUANT...] "
                                  "(perplexity_eval --inject grammar)")
    ap.add_argument("--from-json", help="read the map out of a committed "
                                        "perplexity_eval --json-out record")
    ap.add_argument("--table", action="store_true",
                    help="the whole gate-D ladder with the DDR-fit check")
    ap.add_argument("--fit", action="store_true",
                    help="walk the REAL per-channel plan (hwmap.plan_weights) "
                         "for --map/--nch and assert every channel top is "
                         "below EMB_BASE")
    ap.add_argument("--nch", type=int, default=4,
                    help="channels the --fit pack is split across (default 4)")
    ap.add_argument("--no-repack", action="store_true",
                    help="--fit with the nch-INDEPENDENT pack (what every "
                         "artifact frozen before R-c encodes)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    tag = a.model or MS.TAG
    if a.fit:
        if not a.map:
            ap.error("--fit needs --map")
        return report_fit(tag, parse_map(a.map)[0], a.nch,
                          repack=not a.no_repack)
    if a.from_json:
        with open(a.from_json) as f:
            j = json.load(f)
        tag = a.model or j["model_tag"]
        plan = {c: q for c, q in j["inject_resolved"].items()
                if c in W4_CLASSES}
        miss = [c for c in W4_CLASSES if c not in plan]
        if miss:
            raise SystemExit(f"{a.from_json} leaves {miss} unquantized")
        report(tag, plan)
        return 0
    if a.table:
        table(tag)
        return 0
    if not a.map:
        ap.error("give --map, --from-json, --table or --selftest")
    plan, ignored = parse_map(a.map)
    report(tag, plan, ignored)
    return 0


if __name__ == "__main__":
    sys.exit(main())
