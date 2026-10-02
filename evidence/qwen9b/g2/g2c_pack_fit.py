#!/usr/bin/env python3
"""g2c_pack_fit.py — G2c Step 3's per-channel `plan_weights` fit.

WHY THIS FILE EXISTS, stated first because it is a deviation.

Task 5 Step 3 says "emit the image set and record the fit".  The image set
cannot be emitted: `ref/gen_model_script.py` writes its images from
`Mach.dump_weights`, which packs only the wids `Mach.matvec` REGISTERED, and
`Mach.matvec` is reached only from the token body — which at 9B is refused by
five SEQ_ISA v1.7 ARG-field guards before the first matvec runs
(`evidence/qwen9b/g2/G2C_CHAIN.md` §3, and `run_g2c_emit.sh` demonstrates it
live).  Weakening a guard to make an artifact emit is forbidden, so the fit is
computed from a DERIVED manifest instead and is labelled **D**, not **M**.

WHAT MAKES THE DERIVATION TRUSTWORTHY, and it is not this docstring:

  1. The SHAPES are not restated here.  They are read from
     `load_qwen35._EXPECT_DN` / `_EXPECT_ATTN` / `_EXPECT_MLP`, the same
     tables `load_layer` checks every real tensor against, evaluated at the
     `layer_ref` constants of the selected geometry.
  2. The ROW LAW is not restated either: `w4a8_ref.row_stride` /
     `row_stride8`, the functions `dump_weights` itself calls through
     `pack_ddr_rows`.
  3. The ADDRESSES come from `sw/hwmap.plan_weights` — the layout authority
     — exactly as `ref/seq_format.plan_weights_from_wids` and
     `sw/seq_run.plan_weights_for` reach it.  Nothing here does address
     arithmetic.
  4. Only the wid ORDER and the wid SET are this file's own, and both are
     CHECKED rather than asserted: at every geometry with a committed
     manifest on disk (0.8B W4 `model_v2_s1`, 2B W8 `model_w8_2b_s1`) the
     derived manifest is compared field by field against it, and a single
     mismatch fails the run.  187 committed rows at two geometries and two
     weight widths is the control the 9B row rides on.

  Note also that the fit's OUTPUT is order-independent: `plan_weights` walks
  wids in sorted order and advances each channel's cursor by
  `align_up(rows_c * stride, WID_ALIGN)`, so the per-channel TOP is a sum
  over the multiset of images and does not depend on the order at all.  The
  per-image BASES do depend on it, which is why it is checked anyway.

USAGE
    evidence/qwen9b/g2/g2c_pack_fit.py [--json-out PATH]
        forks one subprocess per geometry (ref/model_select freezes
        FABLE5_MODEL at import — one process is one geometry, always) and
        prints the whole report.
    FABLE5_MODEL=<tag> evidence/qwen9b/g2/g2c_pack_fit.py --one
        the single-geometry worker; prints one JSON object on stdout.
"""
import argparse
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "ref"))
sys.path.insert(0, os.path.join(REPO, "sw"))

MIB = 1024.0 * 1024.0

# Committed manifests to check the derivation against.  Both are gitignored
# NFS artifacts, so a missing file is reported as "control not available",
# never silently skipped.
COMMITTED = {
    "0.8b": ("tb/scripts/w4/model_v2_s1.weights.json", False),
    "2b": ("tb/scripts/w5/model_w8_2b_s1.weights.json", True),
}

# The head is the ONE chunk-interleaved image; every other wid is contiguous.
# Measured, not assumed: `tb/scripts/w4/model_v2_s1.e4.seq.json`'s
# `weight_layout.ilv_wids` is `[186]` and its `by_wid` map is `contig` for
# wids 0..185 — i.e. the head, and only the head.
HEAD_IS_ILV = True


def derive_manifest(w8, g=128):
    """The wid -> image map `Mach.dump_weights` would write, from geometry.

    ORDER — one entry per `M.matvec(...)` call site, in the order the token
    body reaches them.  The call sites, verbatim from the current tree:

      DeltaNet body  ref/gen_layer_script.py:1945 `qd["in_qkv"]`
                     ref/gen_layer_script.py:1947 `qd["in_z"]`
                     ref/gen_layer_script.py:1949 `qd["in_b"]`
                     ref/gen_layer_script.py:1951 `qd["in_a"]`
                     ref/gen_layer_script.py:2047 `qd["out"]`
      GQA body       ref/gen_layer_script.py:2068 `qa["q_proj"]`
                     ref/gen_layer_script.py:2070 `qa["k_proj"]`
                     ref/gen_layer_script.py:2072 `qa["v_proj"]`
                     ref/gen_layer_script.py:2154 `qa["o_proj"]`
      MLP (both)     ref/gen_layer_script.py:2174 `qm["gate"]`
                     ref/gen_layer_script.py:2176 `qm["up"]`
                     ref/gen_layer_script.py:2188 `qm["down"]`
      LM head        ref/gen_model_script.py:634  `qw_head`   (last)

    `Mach.matvec` keys its registry by `id(qw)` and every layer holds its own
    dict, so no two layers ever share a wid; the head is registered on the
    first forward step, after every layer of that step, hence last.
    """
    import layer_ref as LR
    import load_qwen35 as LQ
    from w4a8_ref import row_stride, row_stride8

    dn = LQ._EXPECT_DN
    at = LQ._EXPECT_ATTN
    ml = LQ._EXPECT_MLP
    dn_order = [("dn.in_qkv", dn["in_qkv"]), ("dn.in_z", dn["in_z"]),
                ("dn.in_b", dn["in_b"]), ("dn.in_a", dn["in_a"]),
                ("dn.out", dn["out"])]
    at_order = [("attn.q_proj", at["q_proj"]), ("attn.k_proj", at["k_proj"]),
                ("attn.v_proj", at["v_proj"]), ("attn.o_proj", at["o_proj"])]
    ml_order = [("mlp.gate", ml["gate"]), ("mlp.up", ml["up"]),
                ("mlp.down", ml["down"])]

    types = LR.CFG["layer_types"]
    plan = []
    for i, lt in enumerate(types):
        blk = dn_order if lt == "linear_attention" else at_order
        for nm, sh in blk + ml_order:
            plan.append((f"L{i}.{nm}", sh))
    plan.append(("lm_head", (int(LR.CFG["vocab_size"]), LR.H)))

    man, names = {}, {}
    for wid, (name, (nrows, K)) in enumerate(plan):
        stride = row_stride8(K, g) if w8 else row_stride(K, g)
        m = {"file": f"derived_w{wid}.bin", "nrows": int(nrows), "k": int(K),
             "ng": int(K) // 128, "nbeats": int(nrows) * stride // 64,
             "stride": stride}
        if g != 128:
            m["g"] = g
        if w8:
            m["w8"] = True
        man[wid] = m
        names[wid] = name
    return man, names


# fields `sw/hwmap.plan_weights` actually reads.  `sh` and `e` are
# quantization outputs, are NOT fit inputs, and are deliberately not derived:
# a number this file cannot compute must not appear in its output.
FIT_FIELDS = ("nrows", "k", "ng", "nbeats", "stride", "g", "w8")


def cmp_committed(man, path):
    """Field-by-field check of the derived manifest against a committed one."""
    with open(path) as f:
        gold = json.load(f)
    meta = {k: v for k, v in gold.items() if not k.isdigit()}
    gold = {int(k): v for k, v in gold.items() if k.isdigit()}
    diffs = []
    if sorted(gold) != sorted(man):
        diffs.append(f"wid sets differ: gold {len(gold)} wids, "
                     f"derived {len(man)} wids")
    for wid in sorted(set(gold) & set(man)):
        for fld in FIT_FIELDS:
            gv = gold[wid].get(fld, 128 if fld == "g" else
                               (False if fld == "w8" else None))
            dv = man[wid].get(fld, 128 if fld == "g" else
                              (False if fld == "w8" else None))
            if gv != dv:
                diffs.append(f"wid {wid}.{fld}: gold {gv!r} != derived {dv!r}")
    return {"path": path, "n_gold": len(gold), "meta_keys": sorted(meta),
            "diffs": diffs, "ok": not diffs}


def fit(man, nch, repack):
    """`plan_weights` three ways.  All addresses come from hwmap."""
    import hwmap as HW
    import seq_format as SF
    rows_of = None
    lay = None
    if repack:
        head = max(man)
        lay = {w: (SF.LAYOUT_ILV if (HEAD_IS_ILV and w == head)
                   else SF.LAYOUT_CONTIG) for w in man}

        def rows_of(wid, nrows):
            return SF.chan_rows(nrows, nch, lay[wid], SF.CHUNK_ROWS)

    try:
        base, top = HW.plan_weights(man, wdir=None, nch=nch, rows_of=rows_of)
    except AssertionError as e:
        # plan_weights REFUSES a pack that reaches EMB_BASE rather than
        # returning an address nobody could use.  That refusal is a result,
        # not a crash — the 2B W8 pack at nch-independent is exactly the
        # documented case (V4_V5.md 5) — so it is recorded, with the sizes
        # computed the same way the assert computed them.
        tot = 0
        for m in sorted(man.values(), key=lambda m: m["nrows"]):
            csz = int(m["nrows"]) * int(m["stride"])
            tot += (csz + HW.WID_ALIGN - 1) // HW.WID_ALIGN * HW.WID_ALIGN
        return {"nch": nch, "repack": bool(repack), "refused": str(e),
                "tops": [HW.W_BASE + tot] * nch,
                "used_bytes": [tot] * nch,
                "used_mib": [tot / MIB] * nch,
                "window_mib": (HW.EMB_BASE - HW.W_BASE) / MIB,
                "head_base": None,
                "layout": ("head=ILV, rest=CONTIG, chunk_rows=2048" if repack
                           else "nch-independent (every channel reserves the "
                                "whole image)")}
    tops = list(top) if isinstance(top, (list, tuple)) else [top]
    return {"nch": nch, "repack": bool(repack),
            "tops": [int(t) for t in tops],
            "used_bytes": [int(t) - HW.W_BASE for t in tops],
            "used_mib": [(int(t) - HW.W_BASE) / MIB for t in tops],
            "window_mib": (HW.EMB_BASE - HW.W_BASE) / MIB,
            "head_base": (list(base[max(man)])
                          if isinstance(base[max(man)], (list, tuple))
                          else int(base[max(man)])),
            "layout": ("head=ILV, rest=CONTIG, chunk_rows=2048" if repack
                       else "nch-independent (every channel reserves the "
                            "whole image)")}


def one():
    import hwmap as HW
    import layer_ref as LR
    import model_select as MS
    from layer_fixed import RS_F

    tag = MS.TAG
    w8 = os.environ.get("G2C_W8", "0") == "1"
    man, names = derive_manifest(w8=w8)
    head = max(man)
    total = sum(m["nbeats"] * 64 for m in man.values())
    emb_bytes = int(LR.CFG["vocab_size"]) * LR.H * 2

    out = {
        "tag": tag, "w8": w8, "H": LR.H, "FFN": LR.FFN,
        "n_layers": len(LR.CFG["layer_types"]),
        "n_dn": LR.CFG["layer_types"].count("linear_attention"),
        "n_gqa": LR.CFG["layer_types"].count("full_attention"),
        "vocab": int(LR.CFG["vocab_size"]), "RS_F": RS_F,
        "n_images": len(man), "head_wid": head,
        "head_name": names[head], "head_shape": [man[head]["nrows"],
                                                 man[head]["k"]],
        "head_bytes": man[head]["nbeats"] * 64,
        "pack_bytes": total, "pack_mib": total / MIB,
        "emb_bytes": emb_bytes, "emb_mib": emb_bytes / MIB,
        "W_BASE": HW.W_BASE, "EMB_BASE": HW.EMB_BASE,
        "control": None,
        "fits": [fit(man, 1, False), fit(man, 4, False), fit(man, 4, True)],
    }
    rel, gold_w8 = COMMITTED.get(tag, (None, None))
    if rel is not None:
        path = os.path.join(REPO, rel)
        if not os.path.exists(path):
            out["control"] = {"path": rel, "ok": None,
                              "diffs": ["committed manifest not on disk "
                                        "(gitignored NFS artifact)"]}
        elif bool(gold_w8) != bool(w8):
            out["control"] = {"path": rel, "ok": None,
                              "diffs": [f"control is w8={gold_w8}, this run "
                                        f"is w8={w8}"]}
        else:
            out["control"] = cmp_committed(man, path)
    # per-channel MiB of the busiest channel, the number the spec projects
    r = out["fits"][2]
    out["busiest_mib"] = max(r["used_mib"])
    out["busiest_pct"] = 100.0 * max(r["used_mib"]) / r["window_mib"]
    out["chan0_total_mib"] = (HW.W_BASE / MIB + r["used_mib"][0]
                              + emb_bytes / MIB)
    print(json.dumps(out, indent=1))
    return 0


def from_wq_cache(cachedir):
    """The manifest from the REAL quantized tensors, not from geometry.

    The quantized-weight cache `ref/fidelity_check.py` writes holds exactly
    the objects `ref/gen_model_script.py` would hand to `Mach.matvec`: a list
    of `layer_fixed.quant_layer` outputs plus the `quant_linear_big` head, at
    the same `(res_scale, g, w8, calib)` this build ships.  So the wid
    registry can be built from them in the emitter's call order and handed to
    `ref/seq_format.plan_weights_from_wids` — the COMMITTED live-tensor twin
    of `dump_weights`, which delegates every address to
    `sw/hwmap.plan_weights`.

    This is the strongest form of the check available without an emitted
    artifact: the shapes come from the real quantized matrices rather than
    from `_EXPECT_*`, and the row law and the addresses come from committed
    code.  It still does not prove the wid ORDER, which only an emitted
    manifest can — and the 0.8B/2B controls are what stand in for that.
    """
    import pickle
    import glob as _g
    import layer_ref as LR
    import model_select as MS
    import seq_format as SF

    def newest(pat):
        hits = sorted(_g.glob(os.path.join(cachedir, pat)),
                      key=os.path.getmtime)
        if not hits:
            raise SystemExit(f"no {pat} in {cachedir}")
        return hits[-1]

    lp, hp = newest(f"wq_layers_{MS.TAG}_*.pkl"), newest(f"wq_head_{MS.TAG}_*.pkl")
    out = {}
    for what, p in (("layers", lp), ("head", hp)):
        with open(p, "rb") as f:
            blob = pickle.load(f)
        out[what] = blob["payload"]
        k = blob["key"]
        print(f"  {what:6s} {os.path.basename(p)}")
        print(f"         src_sha256={k['src_sha256']} "
              f"g={k['g']} w8={k['w8']} "
              f"res_scale={k.get('res_scale')} calib_mode={k['calib_mode']}")
        print(f"         checkpoint={k['checkpoint']}")
        print(f"         calib_sha256={k['calib_sha256']}")
    layers_q, head_q = out["layers"], out["head"]

    wids = {}

    def reg(qw):
        wids[id(qw)] = (len(wids), qw)

    types = LR.CFG["layer_types"]
    assert len(layers_q) == len(types), \
        f"cache holds {len(layers_q)} layers, config says {len(types)}"
    for i, lt in enumerate(types):
        q = layers_q[i]
        if lt == "linear_attention":
            for k in ("in_qkv", "in_z", "in_b", "in_a", "out"):
                reg(q["dn"][k])
        else:
            for k in ("q_proj", "k_proj", "v_proj", "o_proj"):
                reg(q["attn"][k])
        for k in ("gate", "up", "down"):
            reg(q["mlp"][k])
    reg(head_q)
    head = len(wids) - 1
    lay = {w: (SF.LAYOUT_ILV if w == head else SF.LAYOUT_CONTIG)
           for w in range(len(wids))}
    plan = SF.plan_weights_from_wids(wids, nch=4, repack=True,
                                     layout_of=lay, chunk_rows=SF.CHUNK_ROWS)
    return plan, len(wids)


def cmp_plan_to_derived(plan, man):
    """`plan_weights_from_wids` output vs the derived manifest, field by field."""
    diffs = []
    if sorted(plan) != sorted(man):
        diffs.append(f"wid sets differ: live {len(plan)}, derived {len(man)}")
    for wid in sorted(set(plan) & set(man)):
        for fld in ("nrows", "k", "ng", "stride", "nbeats"):
            if int(plan[wid][fld]) != int(man[wid][fld]):
                diffs.append(f"wid {wid}.{fld}: live {plan[wid][fld]} != "
                             f"derived {man[wid][fld]}")
    return diffs


def live():
    """`--from-wq-cache` mode: compare the live-tensor plan to the derived one."""
    import model_select as MS
    cachedir = os.environ.get("WQ_CACHE", "/var/tmp/fable5_wq")
    print(f"=== G2c fit CROSS-CHECK — the manifest from the REAL quantized "
          f"tensors\n=== FABLE5_MODEL={MS.TAG}  cache={cachedir}\n")
    plan, n = from_wq_cache(cachedir)
    man, _names = derive_manifest(w8=False)
    print(f"\n  live-tensor wids : {n}")
    print(f"  derived wids     : {len(man)}")
    diffs = cmp_plan_to_derived(plan, man)
    if diffs:
        for d in diffs[:20]:
            print(f"    {d}")
        print("G2C_FIT_LIVE FAIL")
        return 1
    print("  every nrows/k/ng/stride/nbeats identical on all "
          f"{len(man)} wids")
    print(f"  head wid {max(plan)} base per channel: "
          + " ".join(f"{b:#x}" for b in plan[max(plan)]["base"]))
    print("G2C_FIT_LIVE PASS")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--one", action="store_true",
                    help="single-geometry worker (FABLE5_MODEL selects it)")
    ap.add_argument("--from-wq-cache", action="store_true",
                    help="cross-check against the real quantized tensors in "
                         "$WQ_CACHE (needs FABLE5_MODEL set)")
    ap.add_argument("--json-out")
    a = ap.parse_args()
    if a.from_wq_cache:
        return live()
    if a.one:
        return one()

    runs = [("0.8b", False), ("2b", True), ("9b", False)]
    res = []
    for tag, w8 in runs:
        env = dict(os.environ, FABLE5_MODEL=tag, G2C_W8="1" if w8 else "0")
        p = subprocess.run([sys.executable, os.path.abspath(__file__), "--one"],
                           env=env, capture_output=True, text=True)
        if p.returncode != 0:
            print(f"--- {tag}: worker FAILED rc={p.returncode}")
            print(p.stderr)
            return 1
        res.append(json.loads(p.stdout))

    rc = 0
    print("=== G2c per-channel weight-pack fit "
          "(sw/hwmap.plan_weights is the authority) ===\n")
    print("CONTROL — the derived manifest against the committed one\n")
    for r in res:
        c = r["control"]
        if c is None:
            print(f"  {r['tag']:5s} no committed manifest for this geometry "
                  f"(none exists — no 9B artifact has ever been emitted)")
            continue
        if c["ok"]:
            print(f"  {r['tag']:5s} PASS  {c['n_gold']} committed wids, "
                  f"every {'/'.join(FIT_FIELDS)} field identical "
                  f"({c['path']}); non-wid keys {c['meta_keys']}")
        else:
            rc = 1
            print(f"  {r['tag']:5s} FAIL  {c['path']}")
            for d in c["diffs"][:20]:
                print(f"          {d}")
    print()

    print("GEOMETRY\n")
    hdr = ("  tag    layers      H   FFN   images  head wid  head shape"
           "            pack MiB    emb MiB")
    print(hdr)
    for r in res:
        print(f"  {r['tag']:5s}  {r['n_layers']:2d} "
              f"({r['n_dn']:2d}DN+{r['n_gqa']}GQA) {r['H']:5d} {r['FFN']:5d}"
              f"   {r['n_images']:4d}     {r['head_wid']:4d}  "
              f"{r['head_shape'][0]:7d}x{r['head_shape'][1]:<6d}"
              f"  {r['pack_mib']:9.1f}  {r['emb_mib']:9.1f}"
              f"{'  [W8]' if r['w8'] else ''}")
    print()

    print("FIT — bytes packed from W_BASE, per channel, against the "
          f"{res[0]['fits'][0]['window_mib']:.0f} MiB window below EMB_BASE\n")
    for r in res:
        print(f"  --- {r['tag']}{' W8' if r['w8'] else ' W4 g128'} ---")
        for f in r["fits"]:
            name = (f"nch={f['nch']} "
                    + ("REPACKED" if f["repack"] else "nch-independent"))
            over = [i for i, t in enumerate(f["tops"])
                    if t >= r["EMB_BASE"]]
            verdict = ("PASS" if not over else
                       "REFUSED by plan_weights (reaches EMB_BASE)"
                       if f.get("refused") else
                       f"OVERFLOW on channels {over}")
            print(f"    {name:24s} tops "
                  + " ".join(f"{t:#011x}" for t in f["tops"]))
            print(f"    {'':24s} MiB  "
                  + " ".join(f"{m:9.1f}" for m in f["used_mib"])
                  + f"   busiest {max(f['used_mib']):.1f} MiB = "
                  f"{100.0 * max(f['used_mib']) / f['window_mib']:.1f}% "
                  f"— {verdict}")
        print(f"    head image {r['head_bytes']:,} B "
              f"({r['head_bytes'] / MIB:.1f} MiB) at wid {r['head_wid']}")
        print(f"    channel-0 total = {r['W_BASE'] / MIB:.0f} (W_BASE) + "
              f"{r['fits'][2]['used_mib'][0]:.1f} (pack, repacked) + "
              f"{r['emb_mib']:.1f} (emb) = {r['chan0_total_mib']:.1f} of "
              f"{4096} MiB")
        print()

    if a.json_out:
        with open(a.json_out, "w") as f:
            json.dump({"runs": res}, f, indent=1)
        print(f"json -> {a.json_out}")
    print("G2C_PACK_FIT " + ("PASS" if rc == 0 else "FAIL"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
