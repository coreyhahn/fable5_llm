#!/usr/bin/env python3
"""Increment (3) PREP — saturation / range audit of the FROZEN fixed-point
formats against the REAL checkpoint weights of the model `FABLE5_MODEL`
selects (`ref/model_select.py`; 0.8b default, 2b).

Everything reported here is computable from weights alone.  The quantized
values are produced by the actual production quantizers
(layer_fixed.quant_layer / quant_linear -> w4a8_ref.quantize_weights,
fixedpoint.softplus_q / exp_neg_q), never by a re-implementation; this
script only *measures* their outputs against the container each value has
to survive in.

Containers (from the RTL + the script emitter, not from the maths):
  * every scalar constant reaches the chip through the 16-bit scratchpad
    (rtl/layer_chan.sv "scratchpad: 16K x 16"); ref/gen_layer_script.py
    Mach.W ASSERTS -32768 <= v <= 32767, so an out-of-range weight aborts
    script generation rather than silently wrapping.
  * conv weights land in conv4_silu's `signed [15:0] w0..w3`.
  * norm weights land in vecnorm_unit's `logic signed [15:0] wbuf[1024]`.
  * DeltaNet A is the one exception: gate_unit has `logic [17:0] Av[NH]`
    ("UNSIGNED Q15 (A in (0,8))"), shipped as a lo16 + hi2 pair by
    gen_layer_script.dn_token -> Mach.W_raw / Mach.gate (`Ahi & 0x3`).
  * the embedding table is int16 Q7.8 (`<prefix>.emb.bin`, `<i2`).

Activation-dependent formats (residual Q7.8 occupancy after layer 0, the
QKV_F/NRM_F/KVC_F intermediates, the DeltaNet S state Q2.13 of the
layer_fixed.py:439 "revisit w/ real weights (S5)" note, and the y32
accumulator occupancy) CANNOT be settled from weights alone; they are
listed in section 5 as a runtime audit owed by gen_model_script.

Usage:  ref/.venv/bin/python ref/audit_ranges.py [-o report.md]
"""
import argparse
import datetime
import inspect
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fixedpoint as fp                                       # noqa: E402
import layer_fixed as LF                                      # noqa: E402
import layer_ref as LR                                        # noqa: E402
import load_qwen35 as LQ                                      # noqa: E402
import model_select as MS                                     # noqa: E402
import w4a8_ref as W4                                         # noqa: E402

I16_MIN, I16_MAX = -32768, 32767
U18_MAX = (1 << 18) - 1
I64 = np.int64

HERE = os.path.dirname(os.path.abspath(__file__))
# Free-RAM headroom we insist on before quantizing the VOCAB x H LM head with
# the real (float64) quant_linear: the MSE grid search holds the matrix plus
# several float64 temporaries of the same shape.  GEOMETRY-DERIVED, and
# calibrated to sit just above the measured peak RSS of a whole run
# (7 copies of the VOCAB x H float64 matrix): 0.8B (248320x1024) -> 13.3 GiB
# guard vs 12.1 GiB measured; 2B (248320x2048) -> 26.5 GiB vs 24.8 GiB
# measured (evidence/qwen2b/q2/audit/audit_time_*.txt).  The hardcoded
# 10.0 GiB this replaces was already optimistic at 0.8B and would have let
# the 2B head start on a machine with well under half the RAM it needs.
HEAD_MEM_COPIES = 7.0

# The `dt_bias` / `A` rows of sections 1 and 3 are fed the values
# layer_fixed.quant_deltanet STORES, and since 82781e5 those are already
# np.clip'ped into their ports (layer_fixed.py:805-806).  This auditor
# therefore cannot see a gate-port overflow at all.  Every report says so,
# in the header and beside both sets of rows — text only, no measurement
# moves.
GATE_CLAMP_NOTE = (
    "**GATE-PORT CAVEAT — the `dt_bias` and `A` rows of sections 1 and 3 "
    "audit POST-CLAMP values.** `layer_fixed.quant_deltanet` saturates both "
    "into their ports before returning them (`np.clip`, "
    "`layer_fixed.py:805-806`, since `82781e5`), so those rows report "
    "`0 / N` out of range and a max pinned exactly at the rail EVEN IF the "
    "checkpoint exceeds the port — and section 3's \"max used (real "
    "weights)\" column, which is computed from the FLOAT weights, can then "
    "contradict its own verdict. The pre-clamp truth is recorded in "
    "`qd[\"gate_sat\"]` (which this script does not read) and is measured by "
    "`evidence/qwen2b/q2/audit/gate_port_probe.py`.")


# ----------------------------------------------------------------------
# report plumbing
# ----------------------------------------------------------------------
class Report:
    def __init__(self):
        self.buf = []
        self.attention = []

    def w(self, s=""):
        self.buf.append(s)

    def table(self, hdr, rows):
        self.w("| " + " | ".join(hdr) + " |")
        self.w("|" + "|".join("---" for _ in hdr) + "|")
        for r in rows:
            self.w("| " + " | ".join(str(c) for c in r) + " |")
        self.w()

    def text(self):
        return "\n".join(self.buf) + "\n"


def verdict(bad, note_ok, note_bad):
    return ("ATTENTION", note_bad) if bad else ("PASS", note_ok)


def _mem_available_gib():
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 2**20
    except OSError:
        pass
    return 0.0


def _git_rev():
    try:
        return subprocess.check_output(
            ["git", "-C", HERE, "rev-parse", "--short", "HEAD"],
            text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


# ----------------------------------------------------------------------
# section 1 helper: integer constant vs its container
# ----------------------------------------------------------------------
class ConstAudit:
    """Accumulate one family of quantized constants across layers."""

    def __init__(self, name, frac, lo, hi, container, unsigned=False):
        self.name, self.frac = name, frac
        self.lo, self.hi = lo, hi
        self.container = container
        self.unsigned = unsigned
        self.n = 0
        self.qmax = 0            # max |q| (or max q if unsigned)
        self.qmin = None
        self.nbad = 0
        self.offenders = []      # (label, index, float value)

    def add(self, label, q):
        q = np.asarray(q, dtype=np.int64).reshape(-1)
        self.n += q.size
        self.qmax = max(self.qmax, int(np.abs(q).max()))
        self.qmin = int(q.min()) if self.qmin is None else min(self.qmin, int(q.min()))
        bad = np.nonzero((q < self.lo) | (q > self.hi))[0]
        self.nbad += bad.size
        for i in bad[:8]:
            self.offenders.append((label, int(i), int(q[i]) / (1 << self.frac)))

    @property
    def used(self):
        return self.qmax / (1 << self.frac)

    @property
    def avail(self):
        return max(abs(self.lo), self.hi) / (1 << self.frac)

    def min_fit(self):
        """Largest fraction count that still fits every real value in this
        container (i.e. the format the frozen one would have to move to)."""
        if self.qmax == 0:
            return self.frac, self.frac
        span = max(abs(self.lo), self.hi)
        f = self.frac
        while (self.qmax >> (self.frac - f)) > span and f > 0:
            f -= 1
        # or keep the frac and widen the container instead
        bits = int(self.qmax).bit_length() + (0 if self.unsigned else 1)
        return f, bits

    def row(self):
        util = 100.0 * self.qmax / max(abs(self.lo), self.hi)
        v = "ATTENTION" if self.nbad else "PASS"
        f, bits = self.min_fit()
        fit = "fits" if not self.nbad else (
            f"Q{15 - f}.{f} in int16, or {bits} bits at Q{self.frac}"
            if not self.unsigned else
            f"Q.{f} in uint18, or {bits} bits at Q{self.frac}")
        return [self.name, self.container,
                f"+/-{self.avail:.5g}" if not self.unsigned else f"[0, {self.avail:.5g}]",
                f"{self.used:.5g}", f"{util:.2f}%",
                f"{self.nbad} / {self.n}", fit, v]


# ----------------------------------------------------------------------
# section 2 helper: W4 group quantization of one matrix
# ----------------------------------------------------------------------
def audit_w4(Wf, qw, block_rows=None):
    """Measure the real quantizer's output for one matvec matrix.

    Returns e, sh, mantissa stats, INT4 clip count, Frobenius error and the
    y32 headroom thrown away by the conservative `sh`.  Also splits the
    `m == 1` groups into "rounded down to 1" (<= 50% scale error) and
    "CLIPPED up from 0" (the real group scale is below the matrix-wide
    exponent's LSB — those groups get annihilated), and counts how many
    weights inside them quantize to zero.  Row-blocked so the 248320-row
    LM head fits in memory."""
    w4, m, e, sh = qw["w4"], qw["m"], qw["e"], qw["sh"]
    N, K = w4.shape
    NG = K // W4.G
    eff = m.astype(np.float64) * np.exp2(e - 15)          # (N,NG)
    m1 = (m == 1)
    blk = block_rows or N
    nclip = 0
    num = den = 0.0
    n_m_clip0 = 0
    n_m1_w = n_m1_wzero = 0
    for r0 in range(0, N, blk):
        r1 = min(N, r0 + blk)
        Wb = np.asarray(Wf[r0:r1], dtype=np.float64).reshape(-1, NG, W4.G)
        eb = eff[r0:r1][:, :, None]
        rnd = np.round(Wb / eb)                            # pre-clip, same expr
        wb4 = w4[r0:r1].reshape(-1, NG, W4.G).astype(np.float64)
        nclip += int((rnd != wb4).sum())
        d = wb4 * eb - Wb
        num += float((d * d).sum())
        den += float((Wb * Wb).sum())
        # was m rounded down to 1, or CLIPPED up from 0? (same expressions
        # quantize_weights uses, evaluated on the real `e` it chose)
        mr = (np.maximum(np.abs(Wb).max(axis=2), 1e-12) / 7.0) * np.exp2(15 - e)
        n_m_clip0 += int((mr < 0.5).sum())
        sel = m1[r0:r1]
        if sel.any():
            n_m1_w += int(sel.sum()) * W4.G
            n_m1_wzero += int((wb4[sel] == 0).sum())
        del Wb, eb, rnd, wb4, d, mr
    p_bound_spec = NG * 65535 * (W4.G * 8 * 127)
    p_bound_act = int(m.astype(np.int64).sum(axis=1).max()) * (W4.G * 8 * 127)
    return {
        "e": int(e), "sh": int(sh), "N": N, "K": K,
        "m_min": int(m.min()), "m_max": int(m.max()),
        "n_m1": int(m1.sum()), "n_m_lt16": int((m < 16).sum()),
        "n_m_clip0": n_m_clip0,
        "n_m1_w": n_m1_w, "n_m1_wzero": n_m1_wzero,
        "n_m_max": int((m == 65535).sum()), "n_groups": int(m.size),
        "n_w4_clip": nclip, "n_w4": int(w4.size),
        "rel": float(np.sqrt(num / den)),
        "hdr_bits": float(np.log2(p_bound_spec / max(p_bound_act, 1))),
    }


def merge_w4(acc, s):
    if not acc:
        acc.update({k: v for k, v in s.items()})
        acc["e_lo"] = acc["e_hi"] = s["e"]
        acc["sh_lo"] = acc["sh_hi"] = s["sh"]
        acc["rel_lo"] = acc["rel_hi"] = s["rel"]
        acc["hdr_lo"] = acc["hdr_hi"] = s["hdr_bits"]
        acc["nmat"] = 1
        return acc
    acc["e_lo"] = min(acc["e_lo"], s["e"]); acc["e_hi"] = max(acc["e_hi"], s["e"])
    acc["sh_lo"] = min(acc["sh_lo"], s["sh"]); acc["sh_hi"] = max(acc["sh_hi"], s["sh"])
    acc["rel_lo"] = min(acc["rel_lo"], s["rel"]); acc["rel_hi"] = max(acc["rel_hi"], s["rel"])
    acc["hdr_lo"] = min(acc["hdr_lo"], s["hdr_bits"])
    acc["hdr_hi"] = max(acc["hdr_hi"], s["hdr_bits"])
    acc["m_min"] = min(acc["m_min"], s["m_min"]); acc["m_max"] = max(acc["m_max"], s["m_max"])
    for k in ("n_m1", "n_m_lt16", "n_m_max", "n_groups", "n_w4_clip", "n_w4",
              "n_m_clip0", "n_m1_w", "n_m1_wzero"):
        acc[k] += s[k]
    acc["nmat"] += 1
    return acc


# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=os.path.join(HERE, "audit_ranges_report.md"))
    ap.add_argument("--emb-sample", type=int, default=4096,
                    help="token rows used for the layer-0 RMSNorm probe")
    args = ap.parse_args()

    R = Report()
    t0 = datetime.datetime.now()

    # ---------------- load ----------------
    # G2c: `find_checkpointS`.  `find_checkpoint` (singular) is the FIRST
    # shard only and says so in its own docstring — it exists for callers
    # that want the snapshot DIRECTORY, not the tensors.  0.8B and 2B are
    # single-shard so this tool was right everywhere it had ever run; 4B has
    # two shards and 9B four, and reading only shard 0 made every DeltaNet
    # tensor of layer 0 a `KeyError` (G1 forked this file under `runpy` with
    # exactly this patch to get its 9B numbers — `evidence/qwen9b/g1/
    # audit_ranges_9b.py`).  `SafeTensors` takes the whole shard list.
    cps = LQ.find_checkpoints()
    cp = cps[0]
    st = LQ.SafeTensors(cps)
    cfg = LQ.load_config()
    types = cfg["layer_types"]
    NL = cfg["num_hidden_layers"]
    N_DN = sum(1 for t in types if t == "linear_attention")
    N_GQA = sum(1 for t in types if t == "full_attention")
    VOCAB = cfg["vocab_size"]
    # G2c: ground truth from the checkpoint, cross-checked against the config
    # flag by `checkpoint_is_tied` (either direction of disagreement raises).
    TIED, HEAD_KEY = LQ.checkpoint_is_tied(st)

    model_name = MS.REPO_DIR.split("--")[-1]
    mse_default = bool(inspect.signature(LF.quant_linear)
                       .parameters["mse_scale"].default)
    R.w(f"# Increment (3) PREP — fixed-point range audit vs the real "
        f"{model_name} weights")
    R.w()
    R.w(f"- generated: `{t0:%Y-%m-%d %H:%M:%S}`  (repo `{_git_rev()}`)")
    R.w(f"- checkpoint: `{cp}`"
        + ("" if st.n_shards == 1 else f"  ({st.n_shards} shards)"))
    R.w(f"- safetensors header sha256: `{st.header_sha}`"
        + ("" if st.n_shards == 1 else
           "  (COMBINED over the shard header digests — a different kind of "
           "number from a single-shard one; per-shard: "
           + ", ".join(f"`{s}`" for s in st.shard_shas) + ")"))
    R.w(f"- model: {NL} layers "
        f"({types.count('linear_attention')} DeltaNet + "
        f"{types.count('full_attention')} GQA), H={LR.H}, FFN={LR.FFN}, "
        f"vocab={VOCAB} "
        + ("(TIED embeddings: the LM head is a copy of `embed_tokens`)"
           if TIED else
           f"(UNTIED: the LM head is the checkpoint's own `{HEAD_KEY}`)"))
    R.w(f"- frozen formats under test: RS_F={LF.RS_F} QKV_F={LF.QKV_F} "
        f"NRM_F={LF.NRM_F} S_F={LF.S_F} GAT_F={LF.GAT_F} CW_F={LF.CW_F} "
        f"ROPE_F={LF.ROPE_F} KVC_F={LF.KVC_F}, W4 group G={W4.G}")
    R.w("- quantizers exercised: `layer_fixed.quant_layer` (-> `quant_attn` /"
        " `quant_deltanet` / `quant_mlp` / `quant_linear`), "
        "`w4a8_ref.quantize_weights`, `fixedpoint.softplus_q` / `exp_neg_q`"
        " / `sigmoid_q`. Nothing is re-implemented here.")
    R.w(f"- W4 group-scale rule in force (`quant_linear` default "
        f"`mse_scale`): **{'MSE-optimal (quant_linear_mse)' if mse_default else 'max|W_g|/7 (quantize_weights)'}**"
        f" — section 2's `e` / `m` / INT4-clip / error columns are produced "
        f"by THIS rule.")
    R.w(f"- `res_scale = 1.0` (`quant_layer` default). res_scale is a "
        f"power-of-two prescale of the three residual-writing matrices "
        f"(`o_proj` / `dn.out` / `mlp.down`) and of the embedding seed, so "
        f"it moves section 2's `e` column by exactly log2(S) on those "
        f"families and nothing else there; section 4's seed occupancy DOES "
        f"scale with S (see the runtime note in section 5).")
    R.w()
    R.w(GATE_CLAMP_NOTE)
    R.w()

    # ---------------- constants ----------------
    # G2a: the per-family layer counts in these LABELS were 0.8B strings
    # (24 / 48 / 6 / 18).  The COUNTS the audit computes were always
    # geometry-correct; only the printed names lied at 4B/9B, which is a
    # reporting defect G1 recorded and this gate closes.  K_LN12 is a dict
    # KEY as well as a label, so it is built once here and used everywhere.
    K_LN12 = f"ln1/ln2 ({NL} layers x2, zero-centered 1+w)"
    C = {
        K_LN12:
            ConstAudit(f"ln1 / ln2 ({2 * NL} tensors, zero-centered 1+w)", 14,
                       I16_MIN, I16_MAX, "int16 Q1.14 (scratch / vecnorm wbuf)"),
        "ln_f":
            ConstAudit("model.norm (final RMSNorm, zero-centered 1+w)", 14,
                       I16_MIN, I16_MAX, "int16 Q1.14 (scratch / vecnorm wbuf)"),
        "qk_norm":
            ConstAudit(f"q_norm / k_norm ({N_GQA} GQA layers, "
                       f"zero-centered 1+w)", 14,
                       I16_MIN, I16_MAX, "int16 Q1.14 (scratch / vecnorm wbuf)"),
        "dn_norm":
            ConstAudit(f"linear_attn.norm ({N_DN} layers, ONE-centered, "
                       f"used as-is)",
                       14, I16_MIN, I16_MAX,
                       "int16 Q1.14 (scratch / vecnorm wbuf)"),
        "conv_w":
            ConstAudit("conv1d weights (CW_F=13)", 13, I16_MIN, I16_MAX,
                       "int16 Q2.13 (conv4_silu w0..w3)"),
        "dt_bias":
            ConstAudit("dt_bias (Q12)", 12, I16_MIN, I16_MAX,
                       "int16 Q3.12 (gate_unit dtv[15:0])"),
        "A_q15":
            ConstAudit("A = exp(A_log) (Q15)", 15, 0, U18_MAX,
                       "uint18 Q3.15 (gate_unit Av[17:0])", unsigned=True),
    }

    # per-layer quantization with the REAL quant_layer
    fam_acc = {}
    fam_order = []
    per_mat = []                 # (label, stats) for every individual matrix
    gate_rows = []
    n_mat = 0
    ln1_q_layer0 = None

    print(f"quantizing {NL} layers with layer_fixed.quant_layer ...", flush=True)
    for i in range(NL):
        wf = LQ.load_layer(st, i, types[i])
        qw = LF.quant_layer(wf)
        if i == 0:
            ln1_q_layer0 = np.asarray(qw["ln1"], dtype=I64).copy()
        C[K_LN12].add(f"L{i}.ln1", qw["ln1"])
        C[K_LN12].add(f"L{i}.ln2", qw["ln2"])

        mats = [("mlp.gate", wf["mlp"]["gate"], qw["mlp"]["gate"]),
                ("mlp.up", wf["mlp"]["up"], qw["mlp"]["up"]),
                ("mlp.down", wf["mlp"]["down"], qw["mlp"]["down"])]
        if types[i] == "full_attention":
            C["qk_norm"].add(f"L{i}.q_norm", qw["attn"]["q_norm"])
            C["qk_norm"].add(f"L{i}.k_norm", qw["attn"]["k_norm"])
            mats = [(f"attn.{k}", wf["attn"][k], qw["attn"][k])
                    for k in ("q_proj", "k_proj", "v_proj", "o_proj")] + mats
        else:
            qd, wd = qw["dn"], wf["dn"]
            C["conv_w"].add(f"L{i}.conv_w", qd["conv_w"])
            C["dt_bias"].add(f"L{i}.dt_bias", qd["dt_bias_q12"])
            C["A_q15"].add(f"L{i}.A", qd["A_q15"])
            C["dn_norm"].add(f"L{i}.norm_w", qd["norm_w_q14"])
            mats = [(f"dn.{k}", wd[k], qd[k])
                    for k in ("in_qkv", "in_z", "in_b", "in_a", "out")] + mats
            # ---- gate chain, weight-only baseline (a = 0) ----
            A_true = np.exp(np.asarray(wd["A_log"], dtype=np.float64))
            for h in range(LR.LNH):
                Aq = int(qd["A_q15"][h])
                dtq = int(qd["dt_bias_q12"][h])
                Aq_hw = Aq & U18_MAX                     # 18-bit port truncation
                dtq_hw = dtq & 0xFFFF                    # int16 scratch wrap
                dtq_hw -= 0x10000 if dtq_hw >= 0x8000 else 0
                sp = fp.softplus_q(dtq_hw)
                g = -W4.rshift_round(I64(Aq_hw) * sp, 11)
                dec_hw = min(int(W4.rshift_round(
                    I64(fp.exp_neg_q(int(min(g, 0)))), 15)), 32767)
                sp_t = fp.softplus_q(dtq)                # ideal (unbounded ports)
                g_t = -W4.rshift_round(I64(Aq) * sp_t, 11)
                dec_t = min(int(W4.rshift_round(
                    I64(fp.exp_neg_q(int(min(g_t, 0)))), 15)), 32767)
                gate_rows.append(dict(
                    layer=i, head=h, A=float(A_true[h]), Aq=Aq,
                    dt=float(np.asarray(wd["dt_bias"], dtype=np.float64)[h]),
                    dtq=dtq, dec_hw=dec_hw, dec_t=dec_t,
                    ok=(Aq <= U18_MAX and I16_MIN <= dtq <= I16_MAX)))

        for name, Wsrc, q in mats:
            n_mat += 1
            s = audit_w4(Wsrc, q)
            if name not in fam_acc:
                fam_acc[name] = {}
                fam_order.append(name)
            merge_w4(fam_acc[name], s)
            per_mat.append((f"L{i}.{name}", s))
        del wf, qw
        print(f"  layer {i:2d} ({types[i]:17s}) done", flush=True)

    # final norm — quantized exactly as gen_token_script does
    ln_f = st.get(f"{LQ.TEXT_PREFIX}norm.weight")
    ln_f_q = np.round(np.asarray(ln_f, dtype=np.float64) * (1 << 14)).astype(I64)
    C["ln_f"].add("model.norm", ln_f_q)

    # ---------------- section 1 ----------------
    R.w("## 1. Direct constant formats (int16 / uint18 transport)")
    R.w()
    R.w("Every row is a HARD limit: `gen_layer_script.Mach.W` asserts the "
        "int16 range, so an out-of-range value aborts script generation; "
        "`Mach.W_raw` (A) masks to 16+2 bits and would wrap silently.")
    R.w()
    hdr = ["format / tensor family", "container", "available", "max abs value",
           "range util", "out-of-range", "smallest container that fits", "verdict"]
    keys1 = (K_LN12, "ln_f", "qk_norm",
             "dn_norm", "conv_w", "dt_bias", "A_q15")
    R.table(hdr, [C[k].row() for k in keys1])

    R.w("Justifications:")
    for k in keys1:
        a = C[k]
        if a.nbad:
            det = ", ".join(f"{lbl}[{ix}]={v:.4g}" for lbl, ix, v in a.offenders[:6])
            f, bits = a.min_fit()
            R.w(f"- **ATTENTION `{a.name}`** — {a.nbad} of {a.n} values exceed "
                f"the container (max abs value {a.used:.5g} vs "
                f"{a.avail:.5g} representable, {100.0 * a.qmax / max(abs(a.lo), a.hi) - 100:.0f}% "
                f"over). Offenders: {det}"
                + (" ..." if len(a.offenders) > 6 else "")
                + f" Would fit at Q.{f} in the same container, or at the frozen "
                  f"Q.{a.frac} with {bits} bits.")
            R.attention.append(
                f"`{a.name}`: {a.nbad}/{a.n} values exceed "
                f"{a.container} (max {a.used:.5g} vs {a.avail:.5g})")
        else:
            R.w(f"- PASS `{a.name}` — max abs value {a.used:.5g} of "
                f"{a.avail:.5g} available ({100.0 * a.qmax / max(abs(a.lo), a.hi):.1f}% "
                f"of the container); 0 of {a.n} values clip.")
    R.w("- " + GATE_CLAMP_NOTE)
    R.w("- NOTE the four `1+w` families store the ZERO-CENTERED weight, so "
        "the effective RMSNorm scale is `1 + w`; `linear_attn.norm` stores "
        "the ONE-centered weight used as-is (`rmsnorm_fx(..., one_plus=False)`). "
        "Both conventions are confirmed against "
        "`vendor/modeling_qwen3_5.py` (`Qwen3_5RMSNorm` zero-init + `(1.0 + "
        "self.weight)`, `Qwen3_5RMSNormGated` ones-init used directly).")
    R.w()

    # ---------------- section 2 ----------------
    R.w("## 2. W4A8 group quantization of the matvec weights "
        "(`quant_linear` -> `quantize_weights`)")
    R.w()
    R.w("Per-group symmetric INT4, group size G=%d, one uint16 mantissa `m` "
        "per group and ONE shared exponent `e` per matrix. Failure modes: "
        "`m` underflowing to 1 (group scale unrepresentable under the "
        "matrix-wide exponent) and `round(W/eff)` leaving [-8, 7]." % W4.G)
    R.w()
    hdr = ["matrix family", "#mat", "N x K", "e", "sh", "m range",
           "m==1 (scale underflow)", "m clipped up from 0", "INT4 clip",
           "rel err (Frobenius)", "y32 headroom wasted"]
    rows = []
    for name in fam_order:
        a = fam_acc[name]
        rows.append([
            f"`{name}`", a["nmat"], f"{a['N']}x{a['K']}",
            a["e_lo"] if a["e_lo"] == a["e_hi"] else f"{a['e_lo']}..{a['e_hi']}",
            a["sh_lo"] if a["sh_lo"] == a["sh_hi"] else f"{a['sh_lo']}..{a['sh_hi']}",
            f"{a['m_min']}..{a['m_max']}",
            f"{a['n_m1']}/{a['n_groups']}",
            f"{a['n_m_clip0']}/{a['n_groups']}",
            f"{a['n_w4_clip']}/{a['n_w4']}",
            f"{a['rel_lo']:.2%}..{a['rel_hi']:.2%}",
            f"{a['hdr_lo']:.1f}..{a['hdr_hi']:.1f} b"])
    R.table(hdr, rows)

    # ---------------- LM head / embedding ----------------
    # G2c: audit the LM HEAD, which is only `embed_tokens` when the checkpoint
    # ties them.  At 9B `tie_word_embeddings` is false and `lm_head.weight` is
    # a genuinely different 1,017,118,720-parameter tensor that lives OUTSIDE
    # the `model.language_model.` prefix — auditing `embed_tokens` there would
    # have reported the wrong matrix's `e`/`sh`/INT4-clip as the head's, and
    # section 2's verdict is taken on those columns.
    R.w("### 2b. " + ("Tied embedding as the LM head" if TIED
                      else f"The untied LM head (`{HEAD_KEY}`)"))
    R.w()
    # `emb` stays the EMBEDDING TABLE for section 4's residual-seed audit —
    # a separate name, because at 9B the two matrices are different data and
    # section 4 must keep auditing the one that seeds the residual stream.
    emb = st.get(f"{LQ.TEXT_PREFIX}embed_tokens.weight")   # float32 (V,H)
    head_w = emb if TIED else st.get(HEAD_KEY)             # float32 (V,H)
    head_label = "`lm_head` = `embed_tokens`" if TIED else f"`{HEAD_KEY}`"
    memg = _mem_available_gib()
    HEAD_MEM_GIB = HEAD_MEM_COPIES * VOCAB * LR.H * 8 / 2**30
    head_stats = None
    head_note = ""
    if memg >= HEAD_MEM_GIB:
        print(f"quantizing the {VOCAB}x{LR.H} LM head "
              f"(MemAvailable {memg:.1f} GiB) ...", flush=True)
        qhead = LF.quant_linear(head_w)                    # real float64 path
        head_stats = audit_w4(head_w, qhead, block_rows=16384)
        head_note = ("quantized with the production `quant_linear` "
                     "(float64) on the full matrix")
        del qhead
    else:
        print(f"SKIP full-precision head quant (MemAvailable {memg:.1f} GiB "
              f"< {HEAD_MEM_GIB:.1f} GiB)", flush=True)
        head_note = (f"**not run**: only {memg:.1f} GiB RAM available, the "
                     f"float64 `quant_linear` path on {VOCAB}x{LR.H} needs "
                     f"~{HEAD_MEM_GIB:.0f} GiB. Re-run on an idle machine.")
    if head_stats:
        a = head_stats
        R.w((f"`lm_head` is the tied `embed_tokens` matrix ({head_note})."
             if TIED else
             f"`lm_head` is the checkpoint's own `{HEAD_KEY}`, a separate "
             f"tensor from `embed_tokens` ({head_note})."))
        R.w()
        R.table(["matrix", "N x K", "e", "sh", "m range",
                 "m==1 (scale underflow)", "m clipped up from 0", "INT4 clip",
                 "rel err (Frobenius)", "y32 headroom wasted"],
                [[head_label,
                  f"{a['N']}x{a['K']}", a["e"], a["sh"],
                  f"{a['m_min']}..{a['m_max']}",
                  f"{a['n_m1']}/{a['n_groups']}",
                  f"{a['n_m_clip0']}/{a['n_groups']}",
                  f"{a['n_w4_clip']}/{a['n_w4']}",
                  f"{a['rel']:.2%}", f"{a['hdr_bits']:.1f} b"]])
    # release the head; section 4 needs `emb` only.  At 9B this is a real
    # 4.07 GB float32 that is NOT the same object as `emb`.
    del head_w
    if not head_stats:
        R.w(f"- {head_note}")
        R.w()

    # verdicts for section 2
    R.w("Justifications:")
    all2 = [(n, fam_acc[n]) for n in fam_order]
    if head_stats:
        all2.append(("lm_head", dict(head_stats, nmat=1,
                                     rel_lo=head_stats["rel"],
                                     rel_hi=head_stats["rel"],
                                     hdr_lo=head_stats["hdr_bits"],
                                     hdr_hi=head_stats["hdr_bits"])))
    worst_rel = max(a["rel_hi"] for _, a in all2)
    tot_m1 = sum(a["n_m1"] for _, a in all2)
    tot_c0 = sum(a["n_m_clip0"] for _, a in all2)
    tot_m1w = sum(a["n_m1_w"] for _, a in all2)
    tot_m1z = sum(a["n_m1_wzero"] for _, a in all2)
    tot_clip = sum(a["n_w4_clip"] for _, a in all2)
    tot_w4 = sum(a["n_w4"] for _, a in all2)
    tot_g = sum(a["n_groups"] for _, a in all2)
    if tot_m1:
        who = sorted((lbl for lbl, s in per_mat if s["n_m1"]),)
        R.w(f"- **ATTENTION group-scale underflow** — {tot_m1} of {tot_g} groups "
            f"({100.0 * tot_m1 / tot_g:.4f}%) quantize their scale mantissa to "
            f"`m == 1`; {tot_c0} of those were CLIPPED UP from a rounded value "
            f"of 0, i.e. the real group scale is below the matrix-wide "
            f"exponent's LSB and the stored scale is too COARSE. "
            f"{tot_m1z} of the {tot_m1w} weights in those groups "
            f"({100.0 * tot_m1z / max(tot_m1w, 1):.1f}%) collapse to INT4 zero. "
            f"Affected matrices ({len(who)}): " + ", ".join(f"`{w}`" for w in who[:12])
            + (" ..." if len(who) > 12 else "")
            + ". Impact is bounded: these are the numerically smallest groups "
              "in the matrix, so the absolute error they contribute is at most "
              "one matrix-wide LSB per weight.")
        R.attention.append(
            f"W4 group-scale underflow: {tot_m1}/{tot_g} groups hit `m==1` "
            f"({tot_c0} clipped up from 0), annihilating {tot_m1z} weights")
    else:
        R.w(f"- PASS group-scale mantissa — 0 of {tot_g} groups underflow to "
            f"`m == 1` and 0 saturate at 65535; the matrix-wide shared "
            f"exponent covers the real per-group dynamic range.")
    if tot_clip:
        R.w(f"- **ATTENTION INT4 clipping** — {tot_clip} of {tot_w4} weights "
            f"({100.0 * tot_clip / tot_w4:.2e}%) round outside [-8,7] and are "
            f"clipped: " + ", ".join(f"`{n}`={a['n_w4_clip']}"
                                     for n, a in all2 if a["n_w4_clip"]))
        R.attention.append("W4 value clipping (round(W/eff) outside [-8,7])")
    else:
        R.w(f"- PASS INT4 range — 0 of {tot_w4} weights clip; "
            f"`scale = max|W_group|/7` is exact by construction and the "
            f"rounded mantissa `m` never rounds *down* enough to push a "
            f"weight past 7.")
    wm_lbl, wm = max(per_mat, key=lambda t: t[1]["rel"])
    over15 = sorted((l for l, s in per_mat if s["rel"] > 0.15))
    R.w(f"- {'**ATTENTION' if over15 else 'INFO'} quantization error"
        f"{'**' if over15 else ''} — measured as "
        f"`||W_dequant - W||_F / ||W||_F` per matrix (for isotropic inputs "
        f"this is the relative matvec output error, i.e. the same quantity "
        f"`w4a8_ref._selftest` calls the INT4 noise floor: ~12% there, with "
        f"`assert rel < 0.15`). Worst single matrix `{wm_lbl}` at "
        f"{wm['rel']:.2%}. "
        + (f"{len(over15)} of {len(per_mat) + (1 if head_stats else 0)} "
           f"matrices exceed that 15% bound: "
           + ", ".join(f"`{l}`" for l in over15[:12])
           + (" ..." if len(over15) > 12 else "")
           + ". They are the outlier-heavy small projections "
             "(`v_proj`/`k_proj`/`o_proj`, 512-2048 rows); no assert fires "
             "today because the 15% check only runs inside the synthetic "
             "self-test, but the real model quantizes measurably worse "
             "than the Gaussian weights every prior gate was measured on."
           if over15 else
           "Every matrix stays inside the 15% bound, so real weights "
           "quantize no worse than the synthetic weights every prior gate "
           "was measured on."))
    if over15:
        R.attention.append(
            f"W4 weight error above the project's own 15% bound on "
            f"{len(over15)}/{len(per_mat) + (1 if head_stats else 0)} matrices "
            f"(worst `{wm_lbl}` {wm['rel']:.2%})")
    hw_lbl, hw_s = max(per_mat, key=lambda t: t[1]["hdr_bits"])
    hw = hw_s["hdr_bits"]
    if hw >= 1.0:
        R.w(f"- **ATTENTION (precision, not correctness) y32 headroom** — the "
            f"frozen `sh` comes from the worst-case bound "
            f"`NG*65535*(G*8*127)`, but the real mantissas peak at "
            f"{max(a['m_max'] for _, a in all2)}, so up to {hw:.1f} bits of the "
            f"int32 accumulator are discarded by the pre-output shift "
            f"(worst: `{hw_lbl}`). No overflow risk and RTL still matches the "
            f"reference bit-for-bit — but every matvec output carries "
            f"~{hw:.0f} bits less resolution than the format allows.")
        R.attention.append(
            f"y32 headroom: conservative `sh` discards up to {hw:.1f} bits of "
            f"the int32 accumulator (precision only, no overflow)")
    else:
        R.w(f"- PASS y32 headroom — at most {hw:.1f} bits wasted by the "
            f"conservative `sh`.")
    R.w()

    # ---------------- section 3: gate chain ----------------
    R.w("## 3. DeltaNet gate chain (softplus / exp2 ROM domains, decay)")
    R.w()
    R.w("`sp = softplus_q(a + dt)` (Q12, PWL ROM over [-16,16) with an exact "
        "linear branch above +16 and a 0 branch below -16), "
        "`g = -rshr(A*sp, 11)` (Q16), `decay = rshr(exp_neg_q(g), 15)` (Q15). "
        "`a` is activation-dependent, so the table below is the weight-only "
        "baseline `a = 0` plus the two rails reachable after the int16 clip "
        "of `a` (`a = +/-8.0` in Q12).")
    R.w()
    nA_bad = sum(1 for g in gate_rows if g["Aq"] > U18_MAX)
    ndt_bad = sum(1 for g in gate_rows if not (I16_MIN <= g["dtq"] <= I16_MAX))
    n_dec0 = sum(1 for g in gate_rows if g["dec_t"] == 0)
    n_dec1 = sum(1 for g in gate_rows if g["dec_t"] >= 32767)
    n_dec_wrong = sum(1 for g in gate_rows if g["dec_hw"] != g["dec_t"])
    Amax = max(g["A"] for g in gate_rows)
    dtmax = max(abs(g["dt"]) for g in gate_rows)

    rows = [
        ["`A` -> `Av[17:0]` uint18 Q15", "[0, 7.99997]", f"{Amax:.4f}",
         f"{nA_bad} / {len(gate_rows)} heads",
         "ATTENTION" if nA_bad else "PASS"],
        ["`dt_bias` -> `dtv[15:0]` int16 Q12", "+/-8.0", f"{dtmax:.4f}",
         f"{ndt_bad} / {len(gate_rows)} heads",
         "ATTENTION" if ndt_bad else "PASS"],
        ["`a+dt` -> softplus ROM domain (18-bit adder)", "+/-32.0 (adder), "
         "ROM [-16,16) + exact branches", f"{8.0 + dtmax:.4f} at the `a` rail",
         "0 (branches are exact)", "PASS"],
        ["`decay` -> Q15 uint16 (`decay_o[15:0]`)", "[0, 0.99997]",
         "1.0 saturates to 32767 by construction",
         f"{n_dec1} head(s) pin at 32767, {n_dec0} collapse to 0 (a=0)", "PASS"],
        ["`beta = sigmoid_q(b)` Q15", "[0, 0.99997]",
         "saturating ROM", "0 (structural)", "PASS"],
        ["decay computed with the TRUNCATED 18-bit `A`", "-", "-",
         f"{n_dec_wrong} / {len(gate_rows)} heads give a WRONG decay",
         "ATTENTION" if n_dec_wrong else "PASS"],
    ]
    R.table(["gate quantity", "available", "max used (real weights)",
             "out-of-range / effect", "verdict"], rows)

    R.w(GATE_CLAMP_NOTE)
    R.w()
    R.w("Justifications:")
    if nA_bad:
        bad = [g for g in gate_rows if g["Aq"] > U18_MAX]
        det = ", ".join(f"L{g['layer']}h{g['head']} A={g['A']:.3f} "
                        f"(A_q15={g['Aq']}, needs {int(g['Aq']).bit_length()} b)"
                        for g in bad[:8])
        R.w(f"- **ATTENTION `A` exceeds the 18-bit gate port** — {nA_bad} head(s): "
            f"{det}. `Mach.W_raw`/`Mach.gate` mask the high half with `& 0x3` "
            f"and `gate_unit.Av` is `[17:0]`, so the value WRAPS silently. "
            f"Dropping A to Q14 would fit every head "
            f"({max(g['Aq'] for g in gate_rows) >> 1} <= {U18_MAX}) in the "
            f"port as built.")
        R.attention.append(
            f"`A = exp(A_log)` exceeds gate_unit's 18-bit uint Q15 port on "
            f"{nA_bad} head(s) (max A={Amax:.3f} > 8.0) and WRAPS silently")
    else:
        R.w(f"- PASS `A` — max {Amax:.4f} < 8.0, fits uint18 Q15.")
    if ndt_bad:
        bad = [g for g in gate_rows if not (I16_MIN <= g["dtq"] <= I16_MAX)]
        det = ", ".join(f"L{g['layer']}h{g['head']} dt={g['dt']:.3f} "
                        f"(Q12={g['dtq']})" for g in bad[:8])
        R.w(f"- **ATTENTION `dt_bias` exceeds int16 Q12** — {ndt_bad} head(s): "
            f"{det}. `Mach.W` ASSERTS on this, so `gen_model_script` aborts "
            f"before emitting anything (a hard blocker, not a silent one).")
        R.attention.append(
            f"`dt_bias` exceeds int16 Q12 on {ndt_bad} head(s) "
            f"(max |dt|={dtmax:.3f} > 8.0) — `Mach.W` will assert")
    else:
        R.w(f"- PASS `dt_bias` — max |dt| {dtmax:.4f} < 8.0.")
    if n_dec_wrong:
        bad = [g for g in gate_rows if g["dec_hw"] != g["dec_t"]]
        det = ", ".join(f"L{g['layer']}h{g['head']}: {g['dec_t']} -> {g['dec_hw']}"
                        for g in bad[:8])
        worst = max(bad, key=lambda g: abs(g["dec_hw"] - g["dec_t"]))
        R.w(f"- **ATTENTION decay corruption** — with the ports as built, "
            f"{n_dec_wrong} head(s) produce a different Q15 decay than the "
            f"unbounded spec value (a=0 baseline): {det}. Worst case "
            f"L{worst['layer']}h{worst['head']}: decay "
            f"{worst['dec_t'] / 32768:.5f} -> {worst['dec_hw'] / 32768:.5f}, "
            f"i.e. a head that should forget its state almost completely "
            f"every step instead keeps it — this is the functional "
            f"consequence of rows 1-2 and it silently changes the model.")
        R.attention.append(
            f"gate decay differs on {n_dec_wrong} head(s) once A/dt are forced "
            f"into their ports (worst: {worst['dec_t'] / 32768:.4f} -> "
            f"{worst['dec_hw'] / 32768:.4f})")
    R.w(f"- INFO decay dynamics at `a = 0`: {n_dec1} of {len(gate_rows)} heads "
        f"sit at the no-decay rail (Q15 32767, state never forgets) and "
        f"{n_dec0} collapse to 0 (state fully wiped every step). Both are "
        f"faithful to the float model at Q15 resolution but they bound what "
        f"the S-state soak in section 5 can look like.")
    R.w()

    # ---------------- section 4: residual seed ----------------
    R.w("## 4. Residual stream seed — embedding table at Q7.8 (RS_F=%d)" % LF.RS_F)
    R.w()
    embd = np.asarray(emb, dtype=np.float64)
    e_round = np.round(embd * (1 << LF.RS_F))
    n_emb_clip = int(((e_round < I16_MIN) | (e_round > I16_MAX)).sum())
    emb_q = np.clip(e_round, I16_MIN, I16_MAX)
    emb_absmax = float(np.abs(embd).max())
    emb_rms = float(np.sqrt((embd * embd).mean()))
    err = emb_q / (1 << LF.RS_F) - embd
    rel_rms = float(np.sqrt((err * err).mean()) / emb_rms)
    row_absmax = np.abs(emb_q).max(axis=1)
    n_row_zero = int((row_absmax == 0).sum())
    n_row_tiny = int((row_absmax <= 4).sum())
    row_rms = np.sqrt((emb_q * emb_q).mean(axis=1))
    R.table(["quantity", "value"], [
        ["max abs emb (float)", f"{emb_absmax:.6f}"],
        ["Q7.8 representable range", "+/-128.0 (int16, LSB = 1/256 = 0.003906)"],
        ["max abs emb in LSB", f"{emb_absmax * 256:.1f} of 32767"],
        ["range utilisation", f"{100.0 * emb_absmax / 128.0:.3f}%"],
        ["values clipped by `clip16`", f"{n_emb_clip} / {embd.size}"],
        ["emb RMS (float / LSB)", f"{emb_rms:.6f} / {emb_rms * 256:.2f} LSB"],
        ["relative RMS quantization error", f"{rel_rms:.2%}"],
        ["token rows quantizing to ALL ZERO", f"{n_row_zero} / {VOCAB}"],
        ["token rows with max abs q <= 4 LSB", f"{n_row_tiny} / {VOCAB}"],
        ["per-row RMS in LSB (min / median / max)",
         f"{row_rms.min():.2f} / {np.median(row_rms):.2f} / {row_rms.max():.2f}"],
        ["spare integer bits at the residual input",
         f"{int(np.floor(np.log2(32767 / max(emb_absmax * 256, 1e-9))))}"],
    ])
    emb_bad = (n_emb_clip > 0) or (rel_rms > 0.02)
    if emb_bad:
        R.w(f"- **ATTENTION residual seed resolution** — the embedding uses "
            f"only {100.0 * emb_absmax / 128.0:.3f}% of the Q7.8 range "
            f"({emb_absmax * 256:.0f} LSB peak, {emb_rms * 256:.1f} LSB RMS), "
            f"giving {rel_rms:.1%} relative RMS quantization error on the "
            f"layer-0 residual. {n_emb_clip} values clip. Nine of the sixteen "
            f"int16 bits are unused at the input of the network: RS_F is "
            f"sized for the residual AFTER it has grown through the stack, "
            f"not for the embedding.")
        R.attention.append(
            "embedding at Q7.8 uses %.2f%% of the int16 range (%.0f LSB peak, "
            "%.1f LSB RMS) -> %.1f%% relative RMS error on the layer-0 residual"
            % (100.0 * emb_absmax / 128.0, emb_absmax * 256, emb_rms * 256,
               100 * rel_rms))
    else:
        R.w("- PASS embedding at Q7.8.")
    R.w()

    # layer-0 RMSNorm probe: weight-only, uses the real rmsnorm_fx
    ns = min(args.emb_sample, VOCAB)
    idx = np.linspace(0, VOCAB - 1, ns).astype(int)
    outs = np.stack([LF.rmsnorm_fx(emb_q[j].astype(I64), ln1_q_layer0,
                                   LF.RS_F, True) for j in idx])
    o_absmax = int(np.abs(outs).max())
    o_rms = float(np.sqrt((outs.astype(np.float64) ** 2).mean()))
    n_out_sat = int((np.abs(outs) >= 32767).sum())
    R.w(f"Layer-0 `rmsnorm_fx(emb_q, ln1, RS_F, one_plus=True)` probe over "
        f"{ns} evenly spaced token rows (fully determined by weights): "
        f"max |out| = {o_absmax} LSB ({o_absmax / 256.0:.3f} in Q7.8), "
        f"RMS = {o_rms:.1f} LSB, {n_out_sat} values at the int16 rail. "
        + ("**ATTENTION: the norm output saturates.**" if n_out_sat else
           "PASS — the normalizer restores full-scale amplitude from the "
           "tiny embedding, so the resolution loss above happens BEFORE "
           "the norm and is not recovered."))
    if n_out_sat:
        R.attention.append("layer-0 rmsnorm output saturates int16")
    R.w()

    # ---------------- section 5: deferred ----------------
    R.w("## 5. Deferred — activation-dependent, needs a runtime audit in "
        "`gen_model_script`")
    R.w()
    R.table(["format", "container", "why it cannot be settled from weights"],
            [["residual stream `RS_F=%d` (int16 Q7.8) after layer 0" % LF.RS_F,
              "int16, +/-128.0",
              "the residual grows layer by layer; only a real forward pass "
              "gives the peak. Section 4 pins only the t=0 seed."],
             ["`QKV_F=%d` q/k/v + conv output (int16)" % LF.QKV_F,
              "int16, +/-128.0",
              "`matvec_to(...) -> clip16` outputs depend on the normed "
              "activation, not on the weights."],
             ["`NRM_F=%d` L2-normed q/k (int16 Q1.14)" % LF.NRM_F,
              "int16, +/-2.0",
              "unit-norm by construction, but the pre-norm magnitude sets "
              "the rounding error; needs live vectors."],
             ["`S_F=%d` DeltaNet state (int16 Q2.13)" % LF.S_F,
              "int16, +/-4.0",
              "**this is the `layer_fixed.py:439` note.** `deltanet_decode_fx` "
              "counts saturations in `state['sat']`; the bound was measured "
              "on RANDOM weights (|S|max 0.76, rms 0.009). Real decay/beta "
              "(section 3) and real v magnitudes change it. Soak the real "
              "model and assert `sat == 0`."],
             ["`KVC_F` / per-vector KV exponent (int8 + exp)",
              "int8 mantissa", "depends on live k/v vectors."],
             ["`b_q12` / `a_q12` gate inputs (int16 Q12)",
              "int16, +/-8.0",
              "`clip16` of a matvec output; the spec argues the sigmoid/"
              "softplus tail is flat there, but the clip COUNT is runtime data."],
             ["y32 matvec accumulator occupancy",
              "int32",
              "section 2 bounds the headroom from the weights; the achieved "
              "occupancy needs real activations (also gates whether `sh` can "
              "be lowered)."],
             ["attention score / probability Q15/Q30 path",
              "int16/int32", "depends on the live q.k dot products."]])

    # ---------------- section 0 summary (prepended) ----------------
    head = []
    head.append("## 0. Verdict summary")
    head.append("")
    n_att = len(R.attention)
    head.append(f"**{n_att} ATTENTION item(s)**"
                + (":" if n_att else " — every weight-derived format fits."))
    for i, a in enumerate(R.attention, 1):
        head.append(f"{i}. {a}")
    head.append("")
    head.append(f"Matrices quantized with the production path: {n_mat}"
                + (" + 1 LM head = %d" % (n_mat + 1) if head_stats else "")
                + f" (`gen_token_script` expects {8 * N_DN + 7 * N_GQA + 1} "
                  f"weight images at {NL} layers: 8 per DeltaNet layer, "
                  f"7 per full-attention layer, + the LM head).")
    head.append("")
    # splice section 0 right after the metadata block (before "## 1.")
    at = next(i for i, l in enumerate(R.buf) if l.startswith("## 1."))
    R.buf[at:at] = head

    txt = R.text()
    with open(args.out, "w") as f:
        f.write(txt)
    print()
    print(txt)
    print(f"[report written to {args.out}]")


if __name__ == "__main__":
    main()
