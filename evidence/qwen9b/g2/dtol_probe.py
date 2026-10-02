#!/usr/bin/env python3
"""D-TOL probe — where the `attn softmax+pv` selftest error comes from, and
what bound the block actually deserves.

Task 2 (G2 / D-TOL) of docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md.

The defect under investigation: `ref/layer_fixed.py::_selftest`'s
`attn softmax+pv` check reports rel=2.666e-02 at FABLE5_MODEL=0.8b (PASS
against the 3e-02 bound) and rel=3.288e-02 at 2b (FAIL).  The question the
plan asks is whether the BOUND is wrong or the CODE is wrong.

This script answers it with five panels, each self-contained:

  geom    the block's arithmetic inputs at every geometry the campaign cares
          about, read from the committed configs.  Establishes that T and HD
          are literals/constants that DO NOT MOVE across 0.8b/2b/4b/9b, and
          that no head count (NQ/NKV/LNH/LNKH) enters the block at all.

  replay  reproduces the two committed rel values from a standalone replay of
          _selftest's draw sequence with H as the only free parameter.  This
          is the decisive experiment: same code, same shapes, same seed —
          only the position of the shared RNG stream differs, because the
          preceding rmsnorm1p block draws 2*H normals.

  mc      the Monte-Carlo distribution of the rel statistic over independent
          draws of the identical block.  Tells us whether 3e-02 is a bound
          the block passes and 2b broke, or a threshold sitting inside the
          body of a random variable.

  attrib  error attribution: a ladder of hybrids that replaces one fixed-point
          stage at a time with exact float, so each stage's contribution to
          the total is measured rather than argued.

  damage  deliberate-damage panel: five realistic defect classes injected into
          the block, so a proposed bound can be shown to still catch them.

  scale   how the statistic moves with the accumulation length T and with HD,
          i.e. the derivation behind a geometry-parametric bound.

Usage (run on snoke):
    python3 dtol_probe.py --ref-dir /path/to/ref [--panels geom,replay,...]
                          [--mc-draws 4000] [--json out.json]

The block reproduced here is a verbatim transcription of the
`# attention core: identical KV content, T=48` stanza inside
ref/layer_fixed.py's `_selftest`.  It is cited by ANCHOR TEXT and not by line
number on purpose: Task 1 (G1) is editing that file concurrently, so any
`path:NNN` into it rots within the hour.  The block is not imported from
_selftest because _selftest is one monolithic function; the `replay` panel
exists precisely to prove the transcription is exact, by reproducing the
committed numbers to every printed digit.
"""
import argparse
import json
import os
import statistics
import sys

import numpy as np


# ----------------------------------------------------------------------
# the block under test, and the knobs that let us take it apart
# ----------------------------------------------------------------------
def attn_block(q, ks, vs, fp, rshr, QKV_F, I64,
               v_int8=True, k_int8=True, fixed_softmax=True,
               acc_round=True, acc_f=None, damage=None):
    """One attention head, T tokens, HD dims.

    Returns (got, ref).  `ref` is always the float anchor.  The keyword
    switches replace ONE fixed-point stage at a time with exact float so the
    error can be attributed:

      v_int8=False        V comes from the float draw (no int8 KV cache)
      k_int8=False        scores come from the float draw (no int8 KV cache)
      fixed_softmax=False p comes from float softmax (no exp_neg_q/recip_q,
                          no Q15 probability quantization)
      acc_round=False     the PV accumulation keeps full precision instead of
                          rounding every term into Q.acc_f
      acc_f               accumulator fraction bits (default QKV_F)

    `damage` injects a defect (see DAMAGE_MODES).
    """
    T, HD = ks.shape
    if acc_f is None:
        acc_f = QKV_F

    # ---- float anchor (exactly the selftest's) ----
    sc_f = (ks @ q) / np.sqrt(HD)
    e_f = np.exp(sc_f - sc_f.max())
    pf = e_f / e_f.sum()
    ref = pf @ vs

    def kv_quant(v16, in_f):
        x8, e = fp.dyn_quant_i8(v16)
        return x8.astype(np.int8), e - in_f

    qn = np.round(q * (1 << QKV_F)).astype(I64)
    kcache = [kv_quant(np.round(ks[t] * (1 << QKV_F)).astype(I64), QKV_F)
              for t in range(T)]
    vcache = [kv_quant(np.round(vs[t] * (1 << QKV_F)).astype(I64), QKV_F)
              for t in range(T)]

    # ---- scores ----
    if damage == "scale_hd":            # 1/HD instead of 1/sqrt(HD)
        SC = int(round((1 << 15) / HD))
    else:
        SC = int(round((1 << 15) / np.sqrt(HD)))

    if k_int8:
        sc_q = np.zeros(T, dtype=I64)
        for t in range(T):
            k8, ke = kcache[t]
            dot = int((qn * k8.astype(I64)).sum())
            sq_ = rshr(I64(dot) * SC, 15)
            f = QKV_F - ke - 16
            sc_q[t] = rshr(I64(int(sq_)), f) if f >= 0 else int(sq_) << (-f)
    else:                                # exact float scores, placed in Q16
        base = (ks @ q) / HD if damage == "scale_hd" else sc_f
        sc_q = np.round(base * (1 << 16)).astype(I64)

    # ---- softmax ----
    if fixed_softmax:
        if damage == "no_maxsub":        # forget the max subtraction
            mx = 0
        else:
            mx = int(sc_q.max())
        es = np.array([fp.exp_neg_q(int(min(int(sc_q[t]) - mx, 0)))
                       for t in range(T)], dtype=I64)
        r, re = fp.recip_q(int(es.sum()), 30)
        shift = 30 - re + 15
        if damage == "p_shift":          # off-by-one in the probability shift
            shift += 1
        pq = np.clip(rshr(es * r, shift), 0, 1 << 15)
    else:
        s = sc_q.astype(np.float64) / (1 << 16)
        ee = np.exp(s - s.max())
        pq = np.round(ee / ee.sum() * (1 << 15)).astype(I64)

    # ---- PV accumulation ----
    acc = np.zeros(HD, dtype=np.float64 if not acc_round else I64)
    for t in range(T):
        if v_int8:
            v8, ve = vcache[t]
            v_term = v8.astype(I64)
        else:
            v8, ve = None, -QKV_F
            v_term = np.round(vs[t] * (1 << QKV_F)).astype(I64)
        term = I64(int(pq[t])) * v_term
        sh = 15 - ve - acc_f
        if not acc_round:
            acc = acc + term.astype(np.float64) / float(1 << 15) * \
                (2.0 ** ve) * (1 << acc_f)
        elif damage == "trunc":          # truncate instead of round
            acc += (term >> sh) if sh >= 0 else term << (-sh)
        else:
            acc += rshr(term, sh) if sh >= 0 else term << (-sh)

    return np.asarray(acc, dtype=np.float64) / (1 << acc_f), ref


DAMAGE_MODES = {
    "trunc":     "PV accumulation truncates instead of rounding (>> vs rshr)",
    "acc_f_m1":  "accumulator carries one fewer fraction bit (QKV_F-1)",
    "no_maxsub": "softmax forgets the running-max subtraction",
    "scale_hd":  "score scale is 1/HD instead of 1/sqrt(HD)",
    "p_shift":   "off-by-one in the Q15 probability shift",
}


def rel_of(got, ref):
    return float(np.abs(got - ref).max() / (np.abs(ref).max() + 1e-12))


# ----------------------------------------------------------------------
# panels
# ----------------------------------------------------------------------
def panel_geom(cfgdir, out):
    print("== geom: the block's arithmetic inputs, per geometry ==")
    print("   (T is the literal 48 in `T, HD = 48, LR.HD`; every other")
    print("    quantity below is read from the committed config JSON)")
    rows = []
    hdr = f"  {'tag':>5s} {'H':>6s} {'HD':>5s} {'NQ':>4s} {'NKV':>4s} " \
          f"{'LNH':>4s} {'LNKH':>5s} {'LDK':>4s} {'T':>4s}"
    print(hdr)
    for tag in ("0.8b", "2b", "4b", "9b"):
        c = json.load(open(os.path.join(cfgdir, f"qwen3_5_{tag}_config.json")))
        t = c["text_config"]
        row = dict(tag=tag, H=t["hidden_size"], HD=t["head_dim"],
                   NQ=t["num_attention_heads"], NKV=t["num_key_value_heads"],
                   LNH=t["linear_num_value_heads"],
                   LNKH=t["linear_num_key_heads"],
                   LDK=t["linear_key_head_dim"], T=48)
        rows.append(row)
        print(f"  {row['tag']:>5s} {row['H']:>6d} {row['HD']:>5d} "
              f"{row['NQ']:>4d} {row['NKV']:>4d} {row['LNH']:>4d} "
              f"{row['LNKH']:>5d} {row['LDK']:>4d} {row['T']:>4d}")
    hd = {r["HD"] for r in rows}
    tt = {r["T"] for r in rows}
    print(f"  -> HD identical across all four geometries: {hd} "
          f"{'YES' if len(hd) == 1 else 'NO'}")
    print(f"  -> T  identical across all four geometries: {tt} "
          f"{'YES' if len(tt) == 1 else 'NO'}")
    print("  -> the block indexes ONE head with a literal T; NQ/NKV/LNH/LNKH")
    print("     never enter it.  H moves, and H is not an input to the block.")
    out["geom"] = rows
    return len(hd) == 1 and len(tt) == 1


def panel_replay(mod, out):
    """Reproduce the committed rel values with H as the only free parameter."""
    fp, rshr, QKV_F, I64, LR = mod
    print("== replay: _selftest's draw sequence, H the only free parameter ==")
    print("   prefix draws before the attn block (the rmsnorm1p, rope and")
    print("   l2norm checks that precede it in _selftest):")
    print("     rng.normal(0,2,H)  rng.normal(0,0.1,H)  "
          "rng.normal(0,1,HD)  rng.normal(0,1.5,LDK)")
    HD, LDK = 256, 128
    got = {}
    for tag, H in (("0.8b", 1024), ("2b", 2048), ("4b", 2560), ("9b", 4096)):
        rng = np.random.default_rng(21)
        rng.normal(0, 2, H)              # rmsnorm1p x
        rng.normal(0, 0.1, H)            # rmsnorm1p w
        rng.normal(0, 1, HD)             # rope h
        rng.normal(0, 1.5, LDK)          # l2norm v
        T = 48
        q = rng.normal(0, 1, HD)
        ks = rng.normal(0, 1, (T, HD))
        vs = rng.normal(0, 1.2, (T, HD))
        g, r = attn_block(q, ks, vs, fp, rshr, QKV_F, I64)
        got[tag] = rel_of(g, r)
        print(f"  H={H:<5d} ({tag:>4s})  rel={got[tag]:.3e}")
    ok = (f"{got['0.8b']:.3e}" == "2.666e-02"
          and f"{got['2b']:.3e}" == "3.288e-02")
    print(f"  -> reproduces the committed 0.8b/2b values exactly: "
          f"{'YES' if ok else 'NO'}")
    print("  -> the block's code, shapes and seed are identical; only the")
    print("     RNG stream OFFSET differs (2*H normals consumed upstream).")
    out["replay"] = {k: v for k, v in got.items()}
    out["replay_exact"] = ok
    return ok


def panel_mc(mod, out, ndraws, seeds=(1, 2, 3, 4)):
    fp, rshr, QKV_F, I64, LR = mod
    print(f"== mc: distribution of the rel statistic over {ndraws} draws "
          f"of the IDENTICAL block ==")
    T, HD = 48, 256
    per_seed = {}
    allv = []
    for s in seeds:
        rng = np.random.default_rng(s)
        vals = []
        for _ in range(ndraws // len(seeds)):
            q = rng.normal(0, 1, HD)
            ks = rng.normal(0, 1, (T, HD))
            vs = rng.normal(0, 1.2, (T, HD))
            g, r = attn_block(q, ks, vs, fp, rshr, QKV_F, I64)
            vals.append(rel_of(g, r))
        per_seed[s] = vals
        allv.extend(vals)
        print(f"  seed {s}: n={len(vals)} mean={statistics.mean(vals):.3e} "
              f"max={max(vals):.3e} P(>=3e-2)="
              f"{sum(v >= 3e-2 for v in vals) / len(vals):.3f}")
    a = np.array(allv)
    qs = {f"p{p}": float(np.quantile(a, p / 100)) for p in
          (1, 5, 25, 50, 75, 90, 95, 99, 99.9)}
    st = dict(n=len(a), mean=float(a.mean()), std=float(a.std(ddof=1)),
              min=float(a.min()), max=float(a.max()), **qs,
              p_over_3e2=float((a >= 3e-2).mean()))
    print(f"  pooled n={st['n']}  mean={st['mean']:.4e}  sd={st['std']:.3e}  "
          f"min={st['min']:.3e}  max={st['max']:.3e}")
    print("  quantiles: " + "  ".join(f"{k}={v:.3e}" for k, v in qs.items()))
    print(f"  P(rel >= 3e-02) = {st['p_over_3e2']:.4f}   "
          f"<- the 3e-02 bound's ACTUAL false-failure rate")
    print(f"  mean+6sd = {st['mean'] + 6 * st['std']:.3e}")
    out["mc"] = st
    return st


def panel_attrib(mod, out, ndraws=400, seed=7):
    fp, rshr, QKV_F, I64, LR = mod
    print(f"== attrib: which fixed-point stage owns the error ({ndraws} draws) ==")
    T, HD = 48, 256
    variants = {
        "full  (as shipped)":       dict(),
        "acc rounding ONLY":        dict(v_int8=False, k_int8=False,
                                         fixed_softmax=False),
        "V int8 cache ONLY":        dict(k_int8=False, fixed_softmax=False,
                                         acc_round=False),
        "K int8 cache ONLY":        dict(v_int8=False, fixed_softmax=False,
                                         acc_round=False),
        "fixed softmax ONLY":       dict(v_int8=False, k_int8=False,
                                         acc_round=False),
        "everything but acc round": dict(acc_round=False),
    }
    res = {}
    for name, kw in variants.items():
        rng = np.random.default_rng(seed)
        vals = []
        for _ in range(ndraws):
            q = rng.normal(0, 1, HD)
            ks = rng.normal(0, 1, (T, HD))
            vs = rng.normal(0, 1.2, (T, HD))
            g, r = attn_block(q, ks, vs, fp, rshr, QKV_F, I64, **kw)
            vals.append(rel_of(g, r))
        a = np.array(vals)
        res[name] = dict(mean=float(a.mean()), p99=float(np.quantile(a, .99)),
                         max=float(a.max()))
        print(f"  {name:28s} mean={a.mean():.4e}  p99={np.quantile(a,.99):.3e}"
              f"  max={a.max():.3e}")
    parts = [res[k]["mean"] for k in
             ("acc rounding ONLY", "V int8 cache ONLY", "K int8 cache ONLY",
              "fixed softmax ONLY")]
    quad = float(np.sqrt(sum(p * p for p in parts)))
    print(f"  quadrature sum of the four isolated means = {quad:.4e}   "
          f"vs full = {res['full  (as shipped)']['mean']:.4e}")
    out["attrib"] = res
    out["attrib_quadrature"] = quad
    return res


CANDIDATE_BOUNDS = (3e-2, 5e-2, 6e-2, 7e-2, 8e-2, 1e-1)


def panel_damage(mod, out, ndraws=200, seed=11):
    fp, rshr, QKV_F, I64, LR = mod
    print(f"== damage: does a loosened bound still catch real defects? "
          f"({ndraws} draws each) ==")
    T, HD = 48, 256
    res = {}
    for mode, desc in list(DAMAGE_MODES.items()) + [("HEALTHY", "no defect")]:
        rng = np.random.default_rng(seed)
        vals = []
        for _ in range(ndraws):
            q = rng.normal(0, 1, HD)
            ks = rng.normal(0, 1, (T, HD))
            vs = rng.normal(0, 1.2, (T, HD))
            if mode == "HEALTHY":
                kw = {}
            elif mode == "acc_f_m1":
                kw = dict(acc_f=QKV_F - 1)
            else:
                kw = dict(damage=mode)
            g, r = attn_block(q, ks, vs, fp, rshr, QKV_F, I64, **kw)
            vals.append(rel_of(g, r))
        a = np.array(vals)
        res[mode] = dict(desc=desc, mean=float(a.mean()), min=float(a.min()),
                         max=float(a.max()),
                         detect={f"{b:.0e}": float((a >= b).mean())
                                 for b in CANDIDATE_BOUNDS})
        print(f"  {mode:10s} mean={a.mean():.3e}  min={a.min():.3e}  "
              f"max={a.max():.3e}   {desc}")
    print("")
    print("  detection probability P(rel >= bound), by candidate bound:")
    print("   " + " ".join(f"{b:>10.0e}" for b in CANDIDATE_BOUNDS)
          + "   defect")
    for mode in list(DAMAGE_MODES) + ["HEALTHY"]:
        d = res[mode]["detect"]
        print("   " + " ".join(f"{d[f'{b:.0e}']:>10.4f}"
                               for b in CANDIDATE_BOUNDS)
              + f"   {mode}"
              + ("   <- this row is the FALSE-FAILURE rate"
                 if mode == "HEALTHY" else ""))
    out["damage"] = res
    return res


def panel_law(mod, out, ndraws=600, seed=17):
    """Check the closed form against measurement, term by term.

    Claim:  rel_acc  ~=  2^-QKV_F * sqrt(T/12) / (sigma_v * sqrt(sum_t p_t^2))

    Numerator:  every one of the T terms is rounded into Q.QKV_F, so the
    accumulated error per output dim is a sum of T independent uniform
    (-1/2, +1/2) LSB errors: sd = 2^-QKV_F * sqrt(T/12).
    Denominator: ref_d = sum_t p_t v_td with v ~ N(0, sigma_v^2) iid, so
    sd(ref_d) = sigma_v * sqrt(sum p^2).
    The statistic divides max_d|err| by max_d|ref|; both are the max of HD
    iid zero-mean Gaussians, so the order-statistic factor CANCELS -- which
    is why the statistic does not move with HD.
    """
    fp, rshr, QKV_F, I64, LR = mod
    print(f"== law: the closed form vs measurement ({ndraws} draws) ==")
    T, HD, SIG_V = 48, 256, 1.2
    rng = np.random.default_rng(seed)
    ratios, zn, zd = [], [], []
    for _ in range(ndraws):
        q = rng.normal(0, 1, HD)
        ks = rng.normal(0, 1, (T, HD))
        vs = rng.normal(0, 1.2, (T, HD))
        # accumulation-rounding error in isolation
        g, r = attn_block(q, ks, vs, fp, rshr, QKV_F, I64,
                          v_int8=False, k_int8=False, fixed_softmax=False)
        rel_acc = rel_of(g, r)
        sc = (ks @ q) / np.sqrt(HD)
        e = np.exp(sc - sc.max())
        p = e / e.sum()
        sig_e = 2.0 ** -QKV_F * np.sqrt(T / 12.0)
        sig_r = SIG_V * np.sqrt(float((p ** 2).sum()))
        ratios.append(rel_acc / (sig_e / sig_r))
        zn.append(float(np.abs(g - r).max()) / sig_e)
        zd.append(float(np.abs(r).max()) / sig_r)
    a = np.array(ratios)
    print(f"  measured/predicted ratio: mean={a.mean():.3f} "
          f"sd={a.std(ddof=1):.3f}  p5={np.quantile(a,.05):.3f} "
          f"p95={np.quantile(a,.95):.3f}")
    print(f"  order-statistic factor, numerator  max|err|/sd = "
          f"{np.mean(zn):.3f} (sd {np.std(zn):.3f})")
    print(f"  order-statistic factor, denominator max|ref|/sd = "
          f"{np.mean(zd):.3f} (sd {np.std(zd):.3f})")
    print("  -> the two order-statistic factors agree, so they cancel in the")
    print("     ratio: the statistic is HD-independent by construction.")
    out["law"] = dict(ratio_mean=float(a.mean()), ratio_sd=float(a.std(ddof=1)),
                      z_num=float(np.mean(zn)), z_den=float(np.mean(zd)))
    return out["law"]


def panel_scale(mod, out, ndraws=120, seed=13):
    fp, rshr, QKV_F, I64, LR = mod
    print(f"== scale: how the statistic moves with T and with HD ==")
    tt = {}
    for T in (4, 8, 16, 32, 48, 64, 128, 256):
        rng = np.random.default_rng(seed)
        vals = []
        for _ in range(ndraws):
            q = rng.normal(0, 1, 256)
            ks = rng.normal(0, 1, (T, 256))
            vs = rng.normal(0, 1.2, (T, 256))
            g, r = attn_block(q, ks, vs, fp, rshr, QKV_F, I64)
            vals.append(rel_of(g, r))
        a = np.array(vals)
        tt[T] = dict(mean=float(a.mean()), max=float(a.max()))
        print(f"  T={T:<4d} HD=256  mean={a.mean():.4e}  max={a.max():.3e}  "
              f"mean/sqrt(T)={a.mean()/np.sqrt(T):.4e}")
    hh = {}
    for HD in (64, 128, 256, 512):
        rng = np.random.default_rng(seed)
        vals = []
        for _ in range(ndraws):
            q = rng.normal(0, 1, HD)
            ks = rng.normal(0, 1, (48, HD))
            vs = rng.normal(0, 1.2, (48, HD))
            g, r = attn_block(q, ks, vs, fp, rshr, QKV_F, I64)
            vals.append(rel_of(g, r))
        a = np.array(vals)
        hh[HD] = dict(mean=float(a.mean()), max=float(a.max()))
        print(f"  T=48   HD={HD:<4d}  mean={a.mean():.4e}  max={a.max():.3e}")
    out["scale_T"] = tt
    out["scale_HD"] = hh
    return tt, hh


# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--ref-dir",
                    default=os.path.normpath(os.path.join(here, "..", "..",
                                                          "..", "ref")))
    ap.add_argument("--panels",
                    default="geom,replay,mc,attrib,law,damage,scale")
    ap.add_argument("--mc-draws", type=int, default=4000)
    ap.add_argument("--damage-draws", type=int, default=200)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    sys.path.insert(0, a.ref_dir)
    import fixedpoint as fp                                   # noqa: E402
    from w4a8_ref import rshift_round as rshr                 # noqa: E402
    QKV_F = 8
    I64 = np.int64
    mod = (fp, rshr, QKV_F, I64, None)

    # --- provenance, emitted by the script itself so the committed log is
    # --- self-describing and reproducible.  The md5s are of the files this
    # --- probe ACTUALLY reads: fixedpoint.py and w4a8_ref.py (imported), the
    # --- four config JSONs (panel `geom`), and the probe itself.  NOTE it does
    # --- NOT import ref/layer_fixed.py -- the block under test is transcribed
    # --- here (see the module docstring), so a layer_fixed md5 would be
    # --- decorative and is deliberately absent.
    import hashlib
    import platform
    import datetime

    def _md5(path):
        try:
            with open(path, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()
        except OSError:
            return "MISSING"

    print(f"=== host  : {platform.node()}")
    print(f"=== date  : {datetime.datetime.now().astimezone().isoformat()}")
    print(f"=== python: {sys.version.split()[0]}   numpy {np.__version__}")
    print(f"=== ref-dir: {a.ref_dir}")
    print(f"=== reads : fixedpoint.py {_md5(os.path.join(a.ref_dir, 'fixedpoint.py'))}")
    print(f"===         w4a8_ref.py   {_md5(os.path.join(a.ref_dir, 'w4a8_ref.py'))}")
    for _t in ("0.8b", "2b", "4b", "9b"):
        print(f"===         qwen3_5_{_t}_config.json "
              f"{_md5(os.path.join(a.ref_dir, f'qwen3_5_{_t}_config.json'))}")
    print(f"===         dtol_probe.py {_md5(os.path.abspath(__file__))}  (this script)")
    print(f"=== QKV_F : {QKV_F}   (ref/layer_fixed.py `QKV_F = 8`, transcribed here)")
    print("")

    out = {"ref_dir": a.ref_dir, "numpy": np.__version__, "QKV_F": QKV_F}
    panels = a.panels.split(",")
    ok = True
    if "geom" in panels:
        ok &= panel_geom(a.ref_dir, out); print("")
    if "replay" in panels:
        ok &= panel_replay(mod, out); print("")
    if "mc" in panels:
        panel_mc(mod, out, a.mc_draws); print("")
    if "attrib" in panels:
        panel_attrib(mod, out); print("")
    if "law" in panels:
        panel_law(mod, out); print("")
    if "damage" in panels:
        panel_damage(mod, out, ndraws=a.damage_draws); print("")
    if "scale" in panels:
        panel_scale(mod, out); print("")

    if a.json:
        with open(a.json, "w") as f:
            json.dump(out, f, indent=1, sort_keys=True)
        print(f"json -> {a.json}")
    print(f"DTOL_PROBE {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
