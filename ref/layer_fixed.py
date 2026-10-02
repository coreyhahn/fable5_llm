#!/usr/bin/env python3
"""Fixed-point (integer-only) Qwen3.5 decoder layer — THE stage-3 RTL spec.

Every operation here is an exact integer algorithm built on ref/fixedpoint.py
and ref/w4a8_ref.py. The RTL must reproduce these results bit-for-bit.
Accuracy vs the float anchor (layer_ref.py) is reported by _selftest and by
state_drift experiments; formats below were frozen from those measurements.

Formats (Q<int>.<frac>, all signed unless noted):
  residual stream   int16 Q7.8        (RS_F = 8)
  matvec input      int8 via dyn_quant_i8 (per-token power-of-2)
  matvec output     int32 -> shift+round to target format (exact)
  pre-conv qkv      int16 Q7.8
  conv weights      int16 Q2.13
  q/k/v post-silu   int16 Q9.6? -> see QKV_F
  l2-normed q,k     int16 Q1.14
  deltanet state S  int16 QS (S_F frac bits; experiment-chosen)
  decay/beta/gates  Q15 (uint16)
  KV cache (attn)   int8 with per-vector power-of-2 exponent
  attn probs        Q15
"""
import os
import sys

import numpy as np

import fixedpoint as fp
import layer_ref as LR
import model_select as _MS
from w4a8_ref import (G, quantize_weights, quantize_weights8, matvec_y32,
                      matvec_y32_w8, rshift_round as rshr)

I64 = np.int64

# ---- frozen format constants ----
# RS_F is the ONE format constant that is MODEL-SELECTED rather than global
# (spec 4.4).  Two halves, landed at two gates:
#
#   the EMIT side (here).  `FABLE5_RS_F` chooses the residual binary point a
#     generator run bakes into its artifacts.  Unset == 8 == today,
#     byte-identical: `ref/gen_layer_script.py:56` re-exports this name, so an
#     unset process is the shipped one.  A1.8: 8 IS the shipped value —
#     G1 measured the `8 -> 7` rider and the ratified O5 condition rejected it
#     at the container it was scored on, and its sign under the `int16`
#     container that ships was never measured.
#   the CONSUME side (G2a).  The chosen value travels in the weights manifest
#     as the non-wid key `rs_f`, written by `Mach.dump_weights` the way
#     `emb_row_bytes` is (caller-gated, so no frozen manifest gains a byte)
#     and read back by `sw/hwmap.split_manifest`.  The host no longer pins 8;
#     `sw/head_cache.py` and `sw/chat_seq.py` derive the head dequant exponent
#     from the manifest instead.
#
# This is what removes the conflict spec 4.4 names: 0.8B/2B keep 8 and keep
# their byte-lock while 9B may take a different value, with no global constant
# for the two to fight over.
#
# NOTE the one RTL literal that is not format-agnostic: `rtl/conv4_silu.sv`'s
# baked shift `RS_F + CW_F - 12`.  The host expression below it
# (`rshr(acc, RS_F + CW_F - 12)`) already reads this constant, so the host
# follows the knob and only the RTL literal ever has to move.
#
# SUPERSEDED 2026-09-01 (spec 0b, A2 / A2.1).  This block used to say
# "A1.8 leaves that literal ALONE — RS_F stays 8, so Task 10 does not touch
# rtl/conv4_silu.sv".  A1.8 IS SUPERSEDED: the measurement was taken under
# the shipped `int16` container and `RS_F = 7` is ADOPTED for 9B
# (98/108 vs 95, rank max and top-5 unmoved, residual clips 23 -> 0), so
# G3.4 DID move the literal, 9 -> 8 = 7 + 13 - 12.
#
# AND THE NAME IS STILL NOT TRUE (A2.5): `RS_F` below is a process-global
# ENV knob, not a model-selected constant — the tag-scoping lives entirely
# in the caller (`ref/gen_model_script.py`'s BYTELOCKED_TAGS).  So a
# process that exports FABLE5_RS_F and then emits a byte-locked tag trips
# the `rs_f is None` refusal in `ref/gen_layer_script.py`.  That is the
# guard working, but it means `evidence/qwen2b/rc/t4_bytes_unmoved.sh` and
# `ref/scripts/regen_gate.sh` must NOT be run with FABLE5_RS_F exported.
# AND SINCE 2026-09-10 IT IS TRUE (#26, triage (b)11).  `RS_F` is DERIVED
# FROM THE MODEL TAG.  The hazard the env knob carried is stated exactly:
# `rtl/conv4_silu.sv:54` bakes the shift 8 (= RS_F 7 + CW_F 13 - 12), so a 9B artifact
# emitted by a process that FORGOT `FABLE5_RS_F=7` was self-consistent,
# wrote `rs_f: 8` into its own manifest, passed every byte-lock and every
# gate, and had every logit dequantized by 2x the right scale against the
# shipping bitstream.  Nothing could see it, because the only record of the
# intended value was the operator's memory.
#
#   * the LAW is `RS_F_BY_TAG[MS.TAG]`.  0.8b/2b/4b keep 8, which is
#     byte-identical to the old default and keeps the byte-locked tags'
#     `rs_f is None` manifest path exactly as it was; 9b is 7, the value A2
#     adopted and the RTL literal bakes.
#   * `FABLE5_RS_F` is still read, and it must AGREE.  A disagreeing value
#     is REFUSED by name rather than obeyed: the two ways to get the wrong
#     operating point were forgetting the variable and typing it wrong, and
#     deriving alone only closes the first.
#   * `FABLE5_RS_F_RIDER=1` is the one deliberate escape, for the
#     MEASUREMENT scripts whose whole purpose is to sweep the rider
#     (`evidence/qwen9b/g1/run_g1_point.sh` and `evidence/qwen9b/g1/run_g1_smoke.sh`,
#     and G2c's superseded A1.8 `evidence/qwen9b/g2/run_g2c_emit.sh`).  It
#     cannot be set by forgetting anything, which is the property that
#     matters: it takes TWO deliberate variables to reach a non-law value
#     and ZERO to reach the right one.  AND SINCE 2026-09-10 IT SAYS SO
#     (I-2): when the rider fires it prints ONE line on stderr naming the
#     tag, the law and the override, so a rider artifact is never emitted
#     in silence — which was the whole complaint behind #26.
RS_F_BY_TAG = {"0.8b": 8, "2b": 8, "4b": 8, "9b": 7}
_RS_F_LAW = RS_F_BY_TAG[_MS.TAG]
_RS_F_ENV = os.environ.get("FABLE5_RS_F") or None
if _RS_F_ENV is not None and int(_RS_F_ENV) != _RS_F_LAW:
    if os.environ.get("FABLE5_RS_F_RIDER") not in ("1", "true", "yes"):
        raise SystemExit(
            f"FABLE5_RS_F={_RS_F_ENV} disagrees with the operating point "
            f"FABLE5_MODEL={_MS.TAG!r} selects, which is RS_F={_RS_F_LAW} "
            f"(ref/layer_fixed.py RS_F_BY_TAG).  REFUSED: at 9b the RTL "
            f"literal in rtl/conv4_silu.sv bakes RS_F=7, so an artifact "
            f"emitted at any other value is self-consistent and WRONG "
            f"against the shipping bitstream, and its manifest records the "
            f"wrong value rather than the mismatch (#26).  Unset "
            f"FABLE5_RS_F, or set it to {_RS_F_LAW}.  A DELIBERATE rider "
            f"sweep sets FABLE5_RS_F_RIDER=1 as well.")
    # AND THE RIDER SAYS SO, ONCE, ON stderr (review of the pre-ship tool
    # chore, I-2).  #26 exists because a 9B artifact emitted at the wrong
    # residual binary point is SELF-CONSISTENT: it passes every byte-lock and
    # every gate, and NOTHING COULD SEE IT.  A silent escape re-creates
    # exactly that property for any process that sets the two variables, so
    # the escape is announced instead.  This module is imported once per
    # process and `RS_F` is fixed at import, so one line here IS every emit
    # path -- the generators, the reference executor, the fidelity harness --
    # and `evidence/qwen9b/run.sh` tees stderr into the run's own log.
    print(f"FABLE5_RS_F_RIDER=1: RS_F={int(_RS_F_ENV)} OVERRIDES the law "
          f"RS_F={_RS_F_LAW} for FABLE5_MODEL={_MS.TAG!r} "
          f"(ref/layer_fixed.py RS_F_BY_TAG) — this process is a DELIBERATE "
          f"rider sweep and ANY ARTIFACT IT EMITS IS NOT THE SHIPPING "
          f"OPERATING POINT (#26): at 9b rtl/conv4_silu.sv bakes RS_F=7, so "
          f"such an artifact is wrong against the shipping bitstream.",
          file=sys.stderr)
RS_F = int(_RS_F_ENV) if _RS_F_ENV is not None else _RS_F_LAW
                # residual fraction bits (int16 Q7.8 at 0.8b/2b/4b, 7 at 9b)
QKV_F = 8       # conv output / v fraction bits (int16)
NRM_F = 14      # l2-normed q/k fraction bits (int16 Q1.14)
S_F = 13        # deltanet state frac bits (int16 Q2.13): measured float
                # |S|max 0.76, rms 0.009 -> 74 LSB rms, range +/-4.
                # THAT NOTE IS 0.8B, not 9B (it is the note spec 4.1(a) cites
                # as `ref/layer_fixed.py:39`, which is where it sat before the
                # RS_F override above was added).  The 9B numbers are measured
                # by G1 and live in evidence/qwen9b/g1/RUNG_INT8_STATE.md.
GAT_F = 15      # gates (sigmoid/decay/beta) fraction bits
CW_F = 13       # conv weight fraction bits (int16 Q2.13)
ROPE_F = 15     # cos/sin table fraction bits
KVC_F = 6       # base fraction for KV cache int8 mantissa heuristic

EPS_RMS_Q = 1   # rms eps in the integer domain (see rmsnorm_fx)

# ---- THE DELTANET STATE CONTAINER (G1; spec 4.1 W1) ----
# FABLE5_DN_STATE selects the DeltaNet state container.  Read ONCE at import,
# like FABLE5_CALIB_MODE, so a process is one law for its whole life.
#   int16        the shipped Q2.13 container (default; byte-identical)
#   int8:<k>     S8 = sat8(rshr_round(S16, k))        -> Q2.(13-k).  ONE k for
#                the whole model: this is the GLOBAL exponent, and it is the
#                only point of the granularity axis the k sweep swept.
#   int8t:<k>    S8 = sat8(S16 >> k)   truncating     -> the negative point
#   int8h        int8 mantissa + per-HEAD power-of-two exponent (L1, coarse)
#   int8e        int8 mantissa + per-ROW  power-of-two exponent (L1, as spec'd)
#
# THE GRANULARITY AXIS, stated because the k sweep priced one point of it and
# an earlier revision of the gate doc mistook that for the whole axis.  All
# three int8 laws hold the same 7-bit magnitude + sign; they differ ONLY in how
# many values share one exponent:
#   global  1 exponent for everything          (int8:<k>)
#   head    1 per (dn_slot, head)              (int8h)  = 24*32 = 768 at 9B
#   row     1 per (dn_slot, head, row)         (int8e)  = 24*32*128 = 98,304
# "Row" is the URAM row of spec 4.1's split-row map: S[h] is (LDK, LDV) and a
# row is the LAST axis, 128 int8 codes = the 1024-bit half-row that
# `int8naive` writes independently.  `dn_step` walks LDK rows one at a time
# (rtl/dn_step.sv:226, :234), so a per-ROW exponent is computable from the row
# being written, while a per-HEAD exponent needs the whole head's max before
# any of it can be encoded -- a two-pass write or a one-token-stale exponent.
# THIS MODEL TAKES THE EXACT PER-HEAD MAX, i.e. it models the two-pass form;
# the stale-exponent variant is a different law and is NOT measured here.
#
# `dn_state_narrow` is applied after EVERY state update in the DeltaNet
# recurrence, so the host model is bit-exact against what the RTL would hold.
# Task 10 mirrors it in rtl/dn_step.sv / rtl/layer_chan.sv: THIS FUNCTION IS
# THE LAW AND THE RTL MIRRORS IT, NEVER THE REVERSE.
#
# It returns the state in the SAME Q.S_F numbering it was handed, i.e. the
# container's value re-expanded, not the raw code.  Two consequences worth
# stating because they are load-bearing:
#   * every consumer downstream (decay, kv_mem, delta, o) is untouched — what
#     changes is only WHICH VALUES ARE REPRESENTABLE, which is exactly the
#     fidelity question G1 asks and nothing else;
#   * idempotence is then an exact property, not an approximate one, which is
#     what makes it legal to apply the law on every update.
# `dn_state_pack` returns the codes an int8 bank would actually hold, for the
# selftest above and for the RTL mirror.
DN_STATE = os.environ.get("FABLE5_DN_STATE", "") or "int16"
S8_MAX = 127    # symmetric int8 rail: -127..127, never -128, so -x is
                # representable for every representable x (the argument
                # w4a8_ref.quantize_weights8 makes for its own [-127,127])


# exponent granularity per law: how the state is grouped before one exponent
# is chosen for each group.  None = no exponent (global k, or int16).
DN_GRAN = {"int16": None, "int8": None, "int8t": None,
           "int8h": "head", "int8e": "row"}


def _dn_state_parse(s):
    """'int16' | 'int8:<k>' | 'int8t:<k>' | 'int8h' | 'int8e' -> (law, k)."""
    s = str(s).strip()
    if s in ("int16", "int8h", "int8e"):
        return s, 0
    for pfx, law in (("int8:", "int8"), ("int8t:", "int8t")):
        if s.startswith(pfx):
            body = s[len(pfx):]
            if not body.isdigit():
                raise SystemExit(f"FABLE5_DN_STATE={s!r}: {body!r} is not an "
                                 "integer k")
            k = int(body)
            # 0..S_F: k is a right shift of a Q.S_F value, so k = S_F is the
            # last one that still leaves an integer container.  There is no
            # k <= 8 restriction, because `dn_state_narrow` is applied to the
            # UNCLIPPED accumulator and does the container's own saturation
            # itself — see the call site in `deltanet_decode_fx`.  (An earlier
            # revision applied it after clip16, which silently made every
            # k > 8 a double rail: 127 << 9 = 65024 is outside int16, so the
            # container could never reach its own ceiling.)
            if not 0 <= k <= S_F:
                raise SystemExit(f"FABLE5_DN_STATE={s!r}: k must be 0..{S_F}")
            return law, k
    raise SystemExit(f"FABLE5_DN_STATE={s!r} is not int16 / int8:<k> / "
                     "int8t:<k> / int8h / int8e")


DN_STATE_LAW, DN_STATE_K = _dn_state_parse(DN_STATE)

# Instrumentation, purely observational, in the BF_CLIP style: reset by
# bf_reset(), read by fidelity_check into the json and the SUMMARY row.
#   writes   state elements written (the s_writes denominator)
#   absmax   max |S| BEFORE the int16 clip, in Q.S_F LSBs (what centres k)
#   sat16    elements the int16 rail clipped   (== the existing s_sat)
#   sat8     elements the CONTAINER rail clipped (0 under int16)
#   e_min/e_max  exponent range, int8h/int8e only
#   e_fixup  groups whose first-choice exponent was one binade short
#   groups   exponent groups written (the e_fixup denominator)
DN_STATS = {"writes": 0, "absmax": 0, "sat16": 0, "sat8": 0,
            "e_min": 64, "e_max": -64, "e_fixup": 0, "groups": 0}


def _dn_state_set(law, k):
    """Set the law at runtime.  SELFTEST ONLY — production is import-time."""
    global DN_STATE_LAW, DN_STATE_K
    DN_STATE_LAW, DN_STATE_K = law, int(k)


def dn_state_pack(S16):
    """The container codes an int8 DN bank would hold, and their exponent.

    Returns (codes, exp): `codes` int64 in [-127,127] (or the input itself
    under int16, where there is no code), `exp` the per-row power-of-two
    exponent — a scalar array of one element under L0 (the shared k), one per
    ROW under `int8e`.  "Row" is the URAM row: S is (LDK, LDV) per head and a
    row of 128 int8 codes is exactly the 1024-bit half-row of spec 4.1's
    split-row map, which is why per-row is the granularity L1 gets for free.
    """
    S = np.asarray(S16, dtype=I64)
    law, k = DN_STATE_LAW, DN_STATE_K
    if law == "int16":
        return S, np.zeros(1, dtype=I64)
    if law == "int8":
        return np.clip(rshr(S, k), -S8_MAX, S8_MAX), np.full(1, k, dtype=I64)
    if law == "int8t":
        return np.clip(S >> I64(k), -S8_MAX, S8_MAX), np.full(1, k, dtype=I64)
    # int8h / int8e (L1): per-GROUP power-of-two exponent, mantissa in
    # [-127,127].  The exponent is the smallest shift that fits the group's own
    # max under the rail — bf_shift's priority encode with a 7-bit target
    # instead of a 15-bit one — so a quiet group keeps resolution and a loud
    # one keeps range.  `head` is one group per call (dn_state_narrow is
    # called once per head with that head's whole state); `row` groups along
    # the LAST axis, which is the 1024-bit URAM half-row.
    A = _dn_groups(S, DN_GRAN[law])
    amax = np.abs(A).max(axis=1)
    e = np.zeros(A.shape[0], dtype=I64)
    nz = amax > 0
    if nz.any():
        bl = np.array([int(v).bit_length() for v in amax[nz]], dtype=I64)
        e[nz] = np.maximum(bl - 7, 0)
    codes = _rshr_rows(A, e)
    # round-half-away can push a row max from 127.5+ to 128; bf_shift needs
    # the same +1 fixup and for the same reason.  One pass suffices: the
    # fixed-up shift halves the value.
    over = np.abs(codes).max(axis=1) > S8_MAX
    # G1 review F5 — the int8e saturation counter, and what it can honestly be.
    # `dn_state_narrow` used to count `|codes| > 127` AFTER the clip below,
    # which is structurally zero: a counter that cannot fire proves nothing.
    # Moving it before the clip is not enough either — the +1 fixup two lines
    # down has already removed every exceedance, so that is vacuous too.
    # What DOES vary, and is the number a scoring run of L1 needs, is how often
    # the FIRST-CHOICE exponent was one binade short:
    #   sat8    elements that exceed the rail at the first-choice exponent
    #   e_fixup rows whose exponent had to be incremented
    # After the fixup, element-level saturation is exactly zero BY
    # CONSTRUCTION, and that is L1's structural property rather than a
    # measurement — which is precisely why it must not be reported as one.
    DN_STATS["sat8"] += int((np.abs(codes) > S8_MAX).sum())
    DN_STATS["e_fixup"] += int(over.sum())
    DN_STATS["groups"] += int(e.shape[0])
    if over.any():
        e[over] += 1
        codes[over] = _rshr_rows(A[over], e[over])
    codes = np.clip(codes, -S8_MAX, S8_MAX)
    return (codes.reshape(S.shape), e)


def _dn_groups(S, gran):
    """S -> (groups, elems) for the chosen exponent granularity.

    `head`: one group, the whole state handed to this call.  `row`: one group
    per entry of the last axis, i.e. per URAM half-row.  A 1-D input is one
    group either way (the selftest's vectors).
    """
    A = np.asarray(S, dtype=I64)
    if gran == "head" or A.ndim == 1:
        return A.reshape(1, -1)
    return A.reshape(-1, A.shape[-1])


def _rshr_rows(A, e):
    """rshift_round with a PER-ROW shift: the vector form of w4a8_ref.rshr.

    Same rule, element for element — v>=0: (v+add)>>s, v<0: -((-v+add)>>s)
    with add = 2^(s-1) — so a row at e=0 is the identity.
    """
    add = np.where(e > 0, I64(1) << np.maximum(e - 1, 0), 0)[:, None]
    mag = (np.abs(A) + add) >> e[:, None]
    return np.where(A >= 0, mag, -mag)


def dn_state_narrow(S16):
    """THE LAW.  int16 state -> the value the chosen container actually holds,
    returned in the same Q.S_F numbering (see the block comment above)."""
    law, k = DN_STATE_LAW, DN_STATE_K
    S = np.asarray(S16, dtype=I64)
    if law == "int16":
        # the int16 container's OWN saturation.  This is the line the shipped
        # model already had (`Sh = clip16(Sh)`), moved inside the law so that
        # every container saturates exactly once, at its own rail.
        return clip16(S)
    if law in ("int8h", "int8e"):
        codes, e = dn_state_pack(S)
        DN_STATS["e_min"] = min(DN_STATS["e_min"], int(e.min()))
        DN_STATS["e_max"] = max(DN_STATS["e_max"], int(e.max()))
        A = _dn_groups(codes, DN_GRAN[law])
        # sat8 and e_fixup are accumulated inside dn_state_pack, on the
        # PRE-fixup codes.  Counting here would be vacuous: pack has already
        # clipped AND corrected the exponent (G1 review F5).
        return (A << e[:, None]).reshape(S.shape)
    # L0: the pre-clip code is what tells us whether the rail bit
    pre = rshr(S, k) if law == "int8" else (S >> I64(k))
    DN_STATS["sat8"] += int((np.abs(pre) > S8_MAX).sum())
    codes = np.clip(pre, -S8_MAX, S8_MAX)
    return codes << I64(k)


# ---- int32 -> int16 alignment: BLOCK FLOATING (SCRIPT-SIDE, not RTL) ----
# PRODUCTION path since Phase 1A of docs/FIDELITY_REDESIGN.md.  These are
# no longer knobs: this is exactly what gen_layer_script.dn_token /
# attn_token emit, and therefore exactly what the (frozen) RTL executes.
# The pre-Phase-1A path — a FIXED `DN_O_SHIFT = S_F - QKV_F = 5` immediate
# plus a vecnorm-mode-1 gated norm — is preserved in git history at 229c033;
# it measured 0/24 top-1 against bf16 (evidence/stage5/fidelity_*.log),
# because the DN head output leaves dnst at ~5.7 LSB rms (int32, Q.S_F), >>5
# squeezes that to 0.17 LSB rms in int16, and the gated RMSNorm renormalises
# the surviving quantization noise to full scale.
#
# DeltaNet output (per HEAD, per token).  dn_step hands the head output `o`
# to the scratchpad as int32 pairs at Q.S_F; the script emits
#   op1 SHIFT32 k_h    = bf_shift(max|o|)   block-float into int16 (k<0 = <<)
#   op2 SCALE   m_q15  = dn_norm_scale(o, k_h) >>15   1/sqrt(mean(o^2)+eps)
#                        folded with 2^(DN_NORM_F - S_F)
#   op3 EMUL    norm_w                      >>14      per-channel gate weight
# i.e. the SAME op count as the old alu+vn pair, and every operand is a
# command immediate the generator computes from the o32 it already models
# bit-exactly (a DYNQ16-style RTL scan would compute the same k_h from the
# same numbers — see bf_shift).  Two independent wins, both measured:
#   * block floating uses the whole int16 for every head instead of ~0.2 LSB;
#   * the SCRIPT-SIDE norm honours the reference eps (rms_norm_eps = 1e-6,
#     added to mean(o^2)).  vecnorm_unit/rmsnorm_fx have NO eps — `ss == 0
#     -> 1` is a divide-by-zero guard — so a head whose o is below the eps
#     floor was renormalised to FULL SCALE.  Phase-0 probe: block floating
#     alone 70-147% gated-norm rel error, block floating + eps 3.6-10%.
#
# Attention output: ONE k_a for the whole token (all query heads).  Not free
# per-head — the heads are concatenated straight into the o_proj matvec, so a
# per-head shift would change their relative weighting and there is no
# per-head compensation lever (o_proj group scales are static weights).  A
# SHARED k_a is compensated EXACTLY by the o_proj input format
# (matvec_to/shift_for in_f = QKV_F + GAT_F - k_a), because dyn_quant_i8 is
# power-of-two invariant.  k_a is clamped at 0: vec_alu op 8 (EMUL32) reads
# its shift with rshr64 (UNSIGNED), so a negative immediate would yield 0.
#
# DN_NORM_F is the OUTPUT binary point of the gated norm (its input is
# renormalised, so the input's real binary point never appears — see the
# derivation in rmsnorm_fx).  11 is the Phase-0c measured optimum; 8 (the
# old value) wasted 3 bits of the int16, 12+ starts clipping the norm output.
# BF_GUARD keeps extra headroom bits below the int16 rail (0 = fill it).
DN_NORM_F = 11
BF_GUARD = 0
M_Q15_MAX = 65535        # vec_alu cfg_p0 signed[16:0] positive limit
# Instrumentation for the reports (histograms of the emitted immediates and
# the two saturation counters).  Purely observational.
BF_K_HIST = {"dn": {}, "attn": {}}
BF_CLIP = {"m_q15": 0, "m_q15_nonzero": 0, "m_max": 0, "attn_k": 0}

# ---- SEQUENCER RUNG 1: the two immediates move ON CHIP (docs/SEQ_ISA.md) ----
# SEQ_NORM selects WHO computes the DeltaNet gated-norm scale:
#   False (default, SHIPPED): the host/generator float64 immediate
#           dn_norm_scale() -> vec_alu op 2 SCALE.  Byte-identical to every
#           committed artifact; the script generators depend on this.
#   True  (opt-in, sequencer): eps_norm_fx() — the integer vecnorm EPS-NORM
#           mode, computed on chip from the DYNQ16 int16 output + the k that
#           DYNQ16 latched into the XRF.  No host round trip, so the whole
#           token loop can run from a static record stream.
# It is a REFERENCE/harness flag only: gen_*_script.py never sets it (they
# emit the op-2 immediate), so flipping it cannot corrupt a generated script.
SEQ_NORM = False
SEQ_STATS = {"n": 0, "exact": 0, "d_max": 0, "rel_max": 0.0, "clip": 0,
             "scale_max": 0, "k_min": 0, "k_max": 0, "p_min": 63, "p_max": 0,
             "v_max": 0, "sh_min": 63, "sh_max": -63}


def bf_reset():
    """Zero the instrumentation counters (per-run reporting)."""
    BF_K_HIST["dn"], BF_K_HIST["attn"] = {}, {}
    for k in BF_CLIP:
        BF_CLIP[k] = 0
    DN_STATS.update({"writes": 0, "absmax": 0, "sat16": 0, "sat8": 0,
                     "e_min": 64, "e_max": -64, "e_fixup": 0, "groups": 0})
    SEQ_STATS.update({"n": 0, "exact": 0, "d_max": 0, "rel_max": 0.0,
                      "clip": 0, "scale_max": 0, "k_min": 0, "k_max": 0,
                      "p_min": 63, "p_max": 0, "v_max": 0, "sh_min": 63,
                      "sh_max": -63})


def bf_shift(absmax, guard=0):
    """Block-floating alignment for an int32 block whose |max| is `absmax`.

    Returns the SMALLEST k (negative = exact left shift) such that every
    element of the block lands inside int16 after rshr(.,k), i.e. the block
    occupies the int16 as fully as possible without clipping:

        k = bitlen(absmax) - 15 + guard          [+1, see below]

    bitlen(absmax)-15 is a plain priority encode of the block max, which is
    what a DYNQ16-style RTL op would compute; the generator computes the same
    number from the o32 it already models bit-exactly, so a script-side
    immediate and a hardware-side scan agree by construction.
    Correctness: absmax < 2^bitlen, so absmax/2^k < 2^15.  The one exception
    is round-half-away pushing absmax/2^k in (32767.5, 32768) up to 32768,
    hence the explicit +1 fixup — with it the "never clips" property is exact,
    not approximate.  absmax == 0 -> k = 0 (all-zero block; the consumer
    RMSNorm emits zeros for any k).
    """
    m = int(absmax)
    if m <= 0:
        return 0
    k = m.bit_length() - 15 + int(guard)
    if k > 0 and int(rshr(I64(m), k)) > 32767:
        k += 1
    return k


def dn_o_shift(o32, note=True):
    """SHIFT32 (vec_alu op 1) immediate for one DeltaNet head output.

    Signed: k < 0 is an exact left shift (cfg_p0 is `signed [16:0]` and ops
    1/5/6/7/9 use rshr64s).  Range on any int32 block is [-14, +17], well
    inside vec_alu's |p0| < 64 fast path.

    `note` records the immediate in BF_K_HIST.  The script generators pass
    note=False: they call this once per head from the scratchpad MODEL and
    once more via layer_decode_fx (the golden), and only one of the two
    should show up in the histogram.
    """
    k = bf_shift(int(np.abs(np.asarray(o32, dtype=I64)).max()), BF_GUARD)
    assert -64 < k < 64, f"SHIFT32 immediate {k} outside the vec_alu range"
    if note:
        BF_K_HIST["dn"][k] = BF_K_HIST["dn"].get(k, 0) + 1
    return int(k)


def attn_o_shift(absmax, note=True):
    """EMUL32 (vec_alu op 8) immediate for the gated attention output.

    ONE shift for the whole token (see the module header).  vec_alu reads
    op-8 shifts with rshr64 (UNSIGNED: `pu_big = (cfg_p0 < 0) || ...`), so a
    negative immediate would return 0 — clamp at 0 and count it.  On the real
    checkpoint the measured range is k_a in [8, 12], so the clamp is inert
    there; it only ever engages on tiny synthetic-weight activations.
    """
    k = bf_shift(int(absmax), BF_GUARD)
    if k < 0:
        k = 0
        if note:
            BF_CLIP["attn_k"] += 1
    assert 0 <= k < 64, f"EMUL32 immediate {k} outside the vec_alu range"
    if note:
        BF_K_HIST["attn"][k] = BF_K_HIST["attn"].get(k, 0) + 1
    return int(k)


def dn_norm_scale(o32, k_h, note=True):
    """SCALE (vec_alu op 2) immediate m_q15 for the gated RMSNorm of `o32`.

        ss    = sum(o32^2)                              exact integer
        s     = 1 / sqrt(ss / (n * 2^(2*S_F)) + rms_norm_eps)     float64
        A     = s * 2^(DN_NORM_F - S_F)
        m_q15 = round(A * 2^(15 + k_h))                 undoes the op-1 k_h

    so that `clip16(rshr(clip16(rshr64s(o32, k_h)) * m_q15, 15))` is the
    unit-RMS head output at Q.DN_NORM_F.  Deterministic across machines:
    integer sum, IEEE sqrt/divide, exact powers of two.

    m_q15 must fit vec_alu's cfg_p0 as a POSITIVE constant; it is clipped at
    32767 and the clip is counted.  The clip is benign on an all-zero head
    (m is then driven by the eps floor alone, but o16 == 0, so the head emits
    zeros for any m) — BF_CLIP["m_q15_nonzero"] counts the cases that are NOT
    benign and every generated script reports it.

    Ceiling M_Q15_MAX = 65535 (raised from the Phase-0 prototype's 32767 on
    2026-07-27): cfg_p0 is `signed [16:0]` and vec_alu's SCALE path is
    `mul_b <= 33'(cfg_p0)` (rtl/vec_alu.sv E_EX, op 2), so +65535 is the
    exact positive limit of the SHIPPED RTL immediate.  At 32767 the clip
    bound on ~3% of live heads (747/23526 head-evals over four prompts,
    fidelity_phase1a_prod.log), under-scaling them by up to 2x.
    """
    x = np.asarray(o32, dtype=I64)
    ss = int((x * x).sum())
    mean = ss / float(1 << (2 * S_F)) / float(len(x))
    s = 1.0 / np.sqrt(mean + LR.EPS)
    A = s * (2.0 ** (DN_NORM_F - S_F))
    m_raw = round(A * (2.0 ** (15 + k_h)))
    if note:
        if m_raw > M_Q15_MAX:
            BF_CLIP["m_q15"] += 1
            if ss != 0:
                BF_CLIP["m_q15_nonzero"] += 1
        BF_CLIP["m_max"] = max(BF_CLIP["m_max"], int(min(m_raw, 1 << 40)))
    return int(np.clip(m_raw, 0, M_Q15_MAX))


# ======================================================================
# ON-CHIP OP 1 — DYNQ16  (vec_alu op 12, docs/SEQ_ISA.md)
# ======================================================================
def dynq16_fx(x32_block, clamp0=False):
    """vec_alu op 12 DYNQ16 — THE frozen integer spec.  Returns (y16, k).

    Semantics (PROVABLY identical to what ships today — _dynq16_soak
    asserts it element-for-element):

        k  = bf_shift(max|x|, guard=0)          [clamped at 0 if clamp0]
        y  = clip16(rshr64s(x, k))              element-wise

    i.e. exactly `dn_o_shift(o32)` + the op-1 SHIFT32 that consumes it
    (clamp0=False), and exactly `attn_o_shift(max|prod|)` + the op-8 EMUL32
    shift (clamp0=True).  The ONLY change is WHO computes k: today the
    generator does it from its scratchpad model and emits it as a command
    immediate; DYNQ16 computes it from the same numbers in a scan pass and
    latches it into the XRF for later records to use as an indirect
    immediate.  Same k, same y, bit for bit.

    ---- RTL (two passes over `len` int32 {lo,hi} scratch pairs) ----
    PASS 1 (scan, 1 element / 4 cycles, the op-0 DYNQ8 Q_RD/Q_S/Q_W shape):
      av[31:0] = |x|  -- UNSIGNED 32 bits: x = -2^31 gives av = 2^31, which
                 does NOT fit a signed 32-bit register (the one width trap
                 in this op).
      maxabs[31:0] <= av when av > maxabs.
    PASS 1 EXIT (one cycle, pure combinational on maxabs):
      L    = bitlen(maxabs)      priority encode, 0..32 (0 <=> all-zero block)
      k    = (L == 0) ? 0 : L - 15                       signed, -14..+17
      fix  = (k > 0) && (maxabs[L-1 -: 16] == 16'hFFFF)  the +1 of bf_shift
      k   += fix                                          -> k in [-14, +17]
      if (clamp0 && k < 0) k = 0                          cfg_p0[1]
      XRF[cfg_p0[0] ? 2 : 1] <= k                         6-bit signed, sext
      NOTE the `fix` test is EXACT, not an approximation: rshr(m,k) > 32767
      <=> m + 2^(k-1) >= 2^(15+k) <=> m >= 2^L - 2^(L-16) <=> the 16 bits
      below and including the leading one are all ones.  Cost: ONE 32-bit
      normalising shift (maxabs >> (L-16)) plus a 16-input AND, evaluated
      once per vector at the pass-1 exit — no 64-bit shifter, no rounding
      adder and no compare against 32767 anywhere in the exponent path.
      (_dynq16_soak asserts fix == (bf_shift's own +1 branch) over the whole
      exponent range and both signs.)
    PASS 2 (write, the existing op-1 datapath):
      y = clip16(rshr64s(x, k)) with the SH_A/SH_M/SH_C/SH_F decomposition
      of vec_alu (abs -> +round -> coarse >>4n -> fine, sign restore; k < 0
      = exact left shift).  The rounding constant 1 << (k-1) and the
      coarse/fine nibbles are decoded ONCE at the pass-1 exit, exactly like
      cfg_p0 is decoded at IDLE today, so the element loop is unchanged.

    Provable properties (asserted in _dynq16_soak, they are what makes the
    op safe to build):
      * clip16 NEVER fires.  k >= 0: |y| <= 32767 by the +1 fixup.  k < 0:
        maxabs < 2^(15+k) so |y| = maxabs << -k < 2^15.  clamp0: k was
        negative, so maxabs < 2^14 and y = x.  The clip stays in the RTL as
        a width guard only.
      * absmax == 0 -> k = 0, y = 0 (the consumer norm emits zeros for any
        k, so the value of k is arbitrary; 0 is what bf_shift returns).
      * k in [-14, +17] for ANY int32 block: 6 bits signed, well inside the
        18-bit XRF and inside vec_alu's |p0| < 64 fast path.
    """
    x = np.asarray(x32_block, dtype=I64)
    absmax = int(np.abs(x).max()) if x.size else 0
    k = bf_shift(absmax, 0)
    if clamp0 and k < 0:
        k = 0
    return clip16(rshr(x, k)), int(k)


# ======================================================================
# ON-CHIP OP 2 — EPS-NORM  (vecnorm gated mode, docs/SEQ_ISA.md)
# ======================================================================
# Derivation of the eps addend (this is the whole design):
#
# The host today computes, in float64 from the int32 head output o32,
#     m_q15 = round( 2^(15+k) * 2^(DN_NORM_F-S_F) / sqrt(ss32/(n*2^(2*S_F))
#                                                        + rms_norm_eps) )
# On chip the norm only ever sees the DYNQ16 OUTPUT o16 = rshr64s(o32,k)
# (int16 scratch is the engine's transport), so it must work from
#     ss = sum(o16^2)              exact integer, <= n * 32767^2
# Reading ss at the binary point P0 = 2*S_F + n_log2 (the SAME wiring as
# the shipped vecnorm modes 0/1: rs_p = 2*cfg_inf + cfg_nlog2) declares the
# value mean(o_real^2) / 2^(2k) -- i.e. the block-float shift is still in
# there.  Adding an integer E to ss before the rsqrt therefore adds
# E*2^(2k-P0) to the real mean, so the eps floor is honoured exactly when
#     E = rms_norm_eps * 2^(P0 - 2k) = rms_norm_eps * 2^(2*(S_F-k)+n_log2)
# and the rsqrt result comes out 2^k too large -- which is PRECISELY the
# 2^(15+k) that m_q15 carries.  The two cancel, so the output shift
#     sh = S_F - DN_NORM_F + 15 - e
# has NO k in it at all.  k enters the hardware in exactly one place: the
# shift that scales the eps constant.  (Formally: rsqrt_q(v, P+2j) returns
# the same mantissa r and exponent e+j as rsqrt_q(v, P) — same parity, same
# normalisation, same Newton iterations — so declaring P0 instead of the
# true P = P0-2k is exact, not an approximation.)
#
# rms_norm_eps = 1e-6 is stored as a 21-bit integer mantissa at a fixed
# binary point EPS_Q, and E is a SHIFT of it (never a multiply):
#     EPS_M = round(1e-6 * 2^40) = 1099512      (rel. error 3.4e-7)
#     E     = rshr64(EPS_M, EPS_Q - P)          P = 2*(S_F-k) + n_log2
#           = rshr64(EPS_M, 7 + 2k)             for S_F=13, n_log2=7
# k in [-14,+17] -> shift in [-21,+41] -> E in [0, 2^41.1].  E is computed
# ONCE per vector, so this is one 64-bit shifter outside the element loop.
EPS_Q = 40
EPS_M = int(round(LR.EPS * (1 << EPS_Q)))        # 1099512 for eps = 1e-6


def _require_pow2_n(n, nbits, where):
    """The normalizer's 1/N is a SHIFT, not a divide — so N must be a power of 2.

    This is not a modelling convenience: it mirrors `rtl/vecnorm_unit.sv`,
    where N exists only as `cfg_nlog2` (`:277 n_total <= 12'd1 << cfg_nlog2`)
    and the 1/N is folded into the rsqrt binary point
    (`:331-333 rs_p <= 6'(2*cfg_inf) + 6'(cfg_nlog2)`).  There is no plain
    length input anywhere in the unit.

    Every geometry shipped or studied so far normalizes over a power of two
    (H = 1024 / 2048 / 4096, HD = 256, LDV = 128) — EXCEPT Qwen3.5-4B, whose
    H = 2560.  Supporting that needs a real reciprocal multiply in the
    normalizer datapath, which sits on the layer critical path
    (`docs/QWEN35_NEXT_FEASIBILITY.md` §2.3, wall 2).  Failing loudly here is
    the point: silently normalizing by 2048 or 4096 instead of 2560 would
    produce a fidelity number for a machine nobody has proposed.
    """
    if (1 << nbits) != n:
        raise SystemExit(
            f"{where}: N={n} is not a power of two.  The fixed-point "
            "normalizer folds 1/N into the rsqrt binary point as a SHIFT "
            "(rtl/vecnorm_unit.sv:285,331-333), so there is no representation "
            f"for N={n}.  This is feasibility-study wall 2 (§2.3) reaching the "
            "HOST reference model: it needs a reciprocal multiply in the "
            "normalizer, i.e. an RTL decision, not a host patch.  Refusing "
            "rather than normalizing by the wrong N.")


def eps_ss_addend(k, in_f=None, n_log2=7):
    """The integer eps addend E in the sum-of-squares domain (see above).

    E = rshr64(EPS_M, EPS_Q - (2*(in_f - k) + n_log2)), a pure shift of a
    21-bit constant with round-half-away (negative shift = exact left
    shift, the rshr64s convention).  E is 0 for k >= 8 at the DN geometry —
    correct and harmless: a block with k >= 8 has |o16|max >= 16384, so
    ss >= 2^28, and the true eps contribution there is < 2^-30 of ss.
    """
    in_f = S_F if in_f is None else in_f
    return int(rshr(I64(EPS_M), EPS_Q - (2 * (int(in_f) - int(k)) + n_log2)))


def eps_norm_scale(x16, k, in_f=None, out_f=None, note=True):
    """The Q15 multiplier the on-chip EPS-NORM computes (integer m_q15).

    THE FROZEN SPEC of the vecnorm gated mode's RSQ phase.  `x16` is the
    DYNQ16 output (int16), `k` the shift DYNQ16 latched into the XRF.

        n     = len(x16), n_log2 = log2(n)               (power of two)
        ss    = sum(x16^2)                exact, <= n*32767^2 (2^37 at n=128)
        v     = ss + eps_ss_addend(k)     <= 2^42, the 48-bit ss_acc holds it
        r, e  = rsqrt_q(v, 2*in_f + n_log2)      THE EXISTING fx_rsqrt/ROM
        scale = clip(rshr64(r, in_f - out_f + 15 - e), 0, M_Q15_MAX)

    ---- RTL (vecnorm_unit, one new mode; see the module header note) ----
    * ss_acc[47:0] += 32'(s_data)*32'(s_data) in FILL — unchanged.
    * EPS state (new, 1 cycle + 1 shift): eps_sh = (EPS_Q - 2*cfg_inf -
      cfg_nlog2) + 2*k with k the sign-extended 6-bit XRF field; E =
      rshr64(EPS_M, eps_sh); rs_v = ss_acc + E (43 bits worst case, the
      existing 48-bit port); the `(ss==0) -> 1` guard stays but is dead
      here (E > 0 whenever k <= 7, and k == 0 for an all-zero block).
    * rs_p = 6'(2*cfg_inf) + 6'(cfg_nlog2) — BIT-IDENTICAL to the mode-0/1
      wiring already in the RTL, 33 for the DN geometry (in_f = S_F = 13,
      n_log2 = 7).  p_in stays a 6-bit UNSIGNED port: the k-dependence was
      moved into E, so no signed-P widening of fx_rsqrt is needed.
    * ROM: unchanged.  fx_rsqrt's 512x16 bit-slice seed (rsqrt_rom.hex,
      addr = m[31] ? {1'b1,m[30:23]} : {1'b0,m[29:22]}) + 2 Newton
      iterations on the shared 33x33 multiplier.  Accuracy ~2^-26 relative,
      i.e. ~0.5 LSB of a 16-bit scale — three orders of magnitude below the
      output resolution, which is why no extra interpolation order or guard
      bit is required (measured: _epsnorm_soak, and the fidelity table).
    * SCALE state (new, 1 cycle after rs_done): sh_s = int'(cfg_inf) -
      int'(cfg_outf) + 15 - int'(rs_e); scale <= clip(rshr64(rs_r, sh_s),
      0, 16'hFFFF).  The 16-bit clamp is PROVABLY inert on any non-zero
      block: DYNQ16 guarantees |x16|max >= 16384, so ss >= 2^28,
      mean >= 2^-5 and scale <= 2^(15+out_f-in_f)/sqrt(2^-5) = 46341
      (verified: the tightest possible block, one element at 16384,
      scores 46341 over every k).  It fires only on all-zero heads, whose
      output is zero for ANY scale — the same benign clip the host path
      counts today (m_q15 raw 8192000 -> 65535 on exactly those heads).
    * OUT: one 16x17 multiply + a CONSTANT >>15 round-half-away per element
      (the vec_alu op-2 SCALE datapath) — strictly cheaper than the
      variable shifter modes 0/1 need.

    `note` accumulates SEQ_STATS (integer-vs-float scale agreement) for the
    fidelity report; the generators never call this.
    """
    x = np.asarray(x16, dtype=I64)
    in_f = S_F if in_f is None else in_f
    out_f = DN_NORM_F if out_f is None else out_f
    n = len(x)
    nbits = int(np.log2(n))
    _require_pow2_n(n, nbits, "eps_norm_scale")
    ss = int((x * x).sum())
    v = ss + eps_ss_addend(k, in_f, nbits)
    if v <= 0:
        v = 1                                    # RTL: the (ss==0)->1 guard
    p = 2 * int(in_f) + nbits
    assert 0 <= p < 64, f"rsqrt p_in {p} outside the 6-bit port"
    assert v < (1 << 48), f"rsqrt v {v} outside the 48-bit port"
    r, e = fp.rsqrt_q(v, p)
    sh = int(in_f) - int(out_f) + 15 - int(e)
    scale_raw = int(rshr(I64(r), sh))
    scale = int(np.clip(scale_raw, 0, M_Q15_MAX))
    if note:
        SEQ_STATS["n"] += 1
        SEQ_STATS["clip"] += int(scale_raw > M_Q15_MAX)
        SEQ_STATS["scale_max"] = max(SEQ_STATS["scale_max"], scale)
        SEQ_STATS["k_min"] = min(SEQ_STATS["k_min"], int(k))
        SEQ_STATS["k_max"] = max(SEQ_STATS["k_max"], int(k))
        SEQ_STATS["p_min"] = min(SEQ_STATS["p_min"], p)
        SEQ_STATS["p_max"] = max(SEQ_STATS["p_max"], p)
        SEQ_STATS["v_max"] = max(SEQ_STATS["v_max"], v)
        SEQ_STATS["sh_min"] = min(SEQ_STATS["sh_min"], sh)
        SEQ_STATS["sh_max"] = max(SEQ_STATS["sh_max"], sh)
    return scale


def eps_norm_fx(x16, k, in_f=None, out_f=None, note=True):
    """The on-chip gated RMSNorm (vecnorm EPS-NORM mode) — frozen spec.

        out = clip16(rshr64(x16 * eps_norm_scale(x16, k), 15))

    Output binary point Q.out_f (= DN_NORM_F), exactly like the op-2 SCALE
    it replaces, so the per-channel norm weight (op 3 EMUL, >>14) and
    everything downstream are untouched.
    """
    x = np.asarray(x16, dtype=I64)
    scale = eps_norm_scale(x, k, in_f, out_f, note=note)
    return clip16(rshr(clip16(x) * I64(scale), 15))


# ---- gate_unit transport limits (rtl/gate_unit.sv — FROZEN, see below) ----
# dtv[15:0] is signed  -> dt_bias Q3.12 in [-8.0, +7.99976]
# Av[17:0]  is unsigned -> A       Q3.15 in [ 0.0, +7.99997]
# Real Qwen3.5 weights exceed both on 3 of 288 DeltaNet heads
# (ref/audit_ranges_report.md sections 1 and 3).  Neither can be rehomed
# into a wider-headroom format without new ROM hex:
#   * dt at Q4.11 would need `a` at Q11 too (the RTL adds av+dtv with one
#     shared binary point), but the softplus PWL index is hardwired to a
#     Q12 [-16,16) abscissa (gate_unit.pwl_idx_lo + the +/-16<<12 exact
#     branches), so Q11 operands evaluate softplus at HALF the argument.
#   * A at Q4.14 would halve g, because g = -rshr(A*sp, 11) has the shift
#     hardwired to 11 = 15+12-16 and exp_neg consumes g as Q16 (LOG2E_Q16
#     + the exp2 ROM).  sp comes straight out of a ROM and decay goes
#     straight to DNST, so there is no second lever to compensate with.
# The resolution is therefore SATURATION (clamp), not wrapping: the ports
# as built silently truncate (Mach.W_raw masks A to 18 bits) which turns a
# fast-forgetting head into a never-forgetting one.  Clamping keeps the
# decay curve monotone and qualitatively faithful; measured cost is in
# evidence/stage5/ (worst |decay_clamp - decay_spec| = 2942/32768 at the
# a rail, vs 32609/32768 when the same head wraps).
# Widening dtv/Av + regenerating the softplus/exp2 ROMs is future work.
DT_Q12_MIN, DT_Q12_MAX = -32768, 32767
A_Q15_MAX = (1 << 18) - 1


def clip16(x):
    return np.clip(x, -32768, 32767).astype(np.int64)


# ----------------------------------------------------------------------
# weight quantization for ALL matvecs (stage-2 W4A8 path)
# ----------------------------------------------------------------------
# ---- OPT-IN activation salience (Track Q V3) — DEFAULT OFF ----
# FABLE5_CALIB_STATS names an .npz of per-input-channel salience vectors
# (ref/calib_stats.py).  It is read ONCE at import, exactly like
# model_select.FABLE5_MODEL, and when it is unset EVERY code path below is
# byte-identical to the frozen behaviour: `_salience_for` returns None, which
# `quant_linear_mse` short-circuits before it touches the objective.  That
# unset-is-identical property is asserted in `_selftest`.
#
# It exists so the FIXED-POINT path (fidelity_check's FxRunner, via
# quant_layer) can be scored with the same salience-aware quantizer that
# perplexity_eval reaches through its explicit --calib-stats flag: one
# production quantizer, two harnesses, no second implementation.
CALIB_STATS = os.environ.get("FABLE5_CALIB_STATS", "")
# ---- OPT-IN quantizer MODE (Track Q V4) — DEFAULT = V3's salience ----
# Only read when CALIB_STATS is set, so an unset plumb stays byte-identical
# to the frozen behaviour whatever this says.
#   ""/"salience" : V3 — weight the scale search by mean|x| (the frozen V3)
#   "h2"          : weight it by E[x^2] instead (the exact objective diagonal)
#   "gptq"        : V4 — E[x^2] scale search + GPTQ error feedback (ref/gptq.py)
CALIB_MODE = os.environ.get("FABLE5_CALIB_MODE", "") or "salience"
_CALIB_MODES = ("salience", "h2", "gptq")
if not CALIB_STATS and os.environ.get("FABLE5_CALIB_MODE"):
    # same discipline as perplexity_eval.check_res_scale / check_calib_stats:
    # a knob that cannot bite is a number nobody can interpret afterwards.
    raise SystemExit(
        f"FABLE5_CALIB_MODE={os.environ['FABLE5_CALIB_MODE']!r} has no effect "
        "without FABLE5_CALIB_STATS — the quantizer would silently be the "
        "plain frozen one under a calibrated name. Set both, or neither.")
_CALIB_CACHE = None
_H2_CACHE = None
_HESS_STORE = None


def _calib_mode():
    if CALIB_MODE not in _CALIB_MODES:
        raise SystemExit(f"FABLE5_CALIB_MODE={CALIB_MODE!r} is not one of "
                         f"{'/'.join(_CALIB_MODES)}")
    return CALIB_MODE


def calib_salience(key):
    """Salience vector for one canonical tensor key, or None when off.

    Keys are `ref/calib_stats.tensor_key()` names, e.g.
    'layers.7.mlp.gate_proj' or 'lm_head'.  A key that is MISSING from a
    loaded npz is a hard error, never a silent fall back to plain MSE: a
    half-salience-weighted model is a number nobody could interpret.

    Under FABLE5_CALIB_MODE=h2 the vector is sqrt(E[x^2]) instead of mean|x|
    (`quant_linear_mse` squares it, so the weight is exactly the objective's
    diagonal); under =gptq the scale weights come from the Hessian itself and
    this returns None.
    """
    global _CALIB_CACHE, _H2_CACHE
    if not CALIB_STATS:
        return None
    mode = _calib_mode()
    if mode == "gptq":
        return None                       # gptq weights the search by diag(H)
    import calib_stats                    # numpy-only loader
    if mode == "h2":
        if _H2_CACHE is None:
            _H2_CACHE = calib_stats.load_h2(CALIB_STATS)
            if not _H2_CACHE:
                raise SystemExit(
                    f"FABLE5_CALIB_MODE=h2 needs the second moments and "
                    f"{CALIB_STATS} has none — regenerate it with "
                    "`ref/calib_stats.py --hessian`")
        site = calib_stats.hess_key(key)
        try:
            return np.sqrt(_H2_CACHE[site].astype(np.float64))
        except KeyError:
            raise SystemExit(
                f"FABLE5_CALIB_STATS={CALIB_STATS} has no E[x^2] for site "
                f"{site!r} (needed by {key!r})") from None
    if _CALIB_CACHE is None:
        _CALIB_CACHE = calib_stats.load(CALIB_STATS)
    try:
        return _CALIB_CACHE[key]
    except KeyError:
        raise SystemExit(
            f"FABLE5_CALIB_STATS={CALIB_STATS} has no salience for {key!r} "
            f"({len(_CALIB_CACHE)} tensors present) — regenerate it with "
            "ref/calib_stats.py for THIS model") from None


def calib_hess(key):
    """`gptq.HessFactor` for one tensor key, or None outside gptq mode."""
    global _HESS_STORE
    if not CALIB_STATS or _calib_mode() != "gptq":
        return None
    if _HESS_STORE is None:
        import calib_stats
        _HESS_STORE = calib_stats.HessStore(CALIB_STATS)
    return _HESS_STORE.factor(key)


def _salience_for(sub, wkey, layer_idx):
    """Salience for one per-layer weight, or None when the plumb is off."""
    if not CALIB_STATS:
        return None
    if layer_idx is None:
        raise SystemExit(
            "FABLE5_CALIB_STATS is set but quant_layer/quant_* was called "
            "without layer_idx, so salience cannot be looked up per layer. "
            "Either pass layer_idx (fidelity_check.quantize_model does) or "
            "unset FABLE5_CALIB_STATS for this run.")
    import calib_stats
    return calib_salience(calib_stats.tensor_key(sub, wkey, layer_idx))


def _hess_for(sub, wkey, layer_idx):
    """GPTQ Hessian factor for one per-layer weight, or None when off."""
    if not CALIB_STATS or _calib_mode() != "gptq":
        return None
    if layer_idx is None:
        raise SystemExit(
            "FABLE5_CALIB_MODE=gptq is set but quant_layer/quant_* was called "
            "without layer_idx, so the input Hessian cannot be looked up per "
            "layer. Either pass layer_idx (fidelity_check.quantize_model "
            "does) or unset FABLE5_CALIB_STATS for this run.")
    import calib_stats
    return calib_hess(calib_stats.tensor_key(sub, wkey, layer_idx))


def _calib_for(sub, wkey, layer_idx):
    """(salience, hess) for one per-layer weight — (None, None) when off.

    Exactly one of the two is ever non-None: the salience path weights the
    scale search, the GPTQ path takes its weights from the Hessian diagonal.
    """
    return (_salience_for(sub, wkey, layer_idx),
            _hess_for(sub, wkey, layer_idx))


def _salience_weights(salience, K, g):
    """Per-input-channel error weights for `quant_linear_mse` (Track Q V3).

    Returns None (= plain, unweighted MSE — the frozen behaviour) or a
    (1, K//g, g) float64 array of `salience[k]**2` normalised to mean 1.

    The normalisation is numerical hygiene only: the scale search takes an
    argmin over candidate group scales, and multiplying every term of that
    objective by one positive constant cannot move the argmin.  It also makes
    `salience = ones(K)` reduce to EXACTLY the unweighted path (mean of ones
    is 1.0, and both 1.0/1.0 and x*1.0 are exact in IEEE-754), which is what
    `_selftest`'s invariance check asserts.
    """
    if salience is None:
        return None
    s = np.asarray(salience, dtype=np.float64).reshape(-1)
    if s.shape[0] != K:
        raise ValueError(f"salience has {s.shape[0]} entries but the matrix "
                         f"has K={K} input channels")
    if not np.all(np.isfinite(s)) or np.any(s < 0.0):
        raise ValueError("salience must be finite and non-negative "
                         "(it is a mean |activation| per input channel)")
    w = s * s
    mean = float(w.mean())
    if not mean > 0.0:
        raise ValueError("salience is identically zero — no input channel "
                         "carries signal, so there is nothing to weight by")
    return (w / mean).reshape(1, K // g, g)


def quant_linear_mse(Wf, nalpha=17, amin=0.55, g=G, salience=None):
    """W4A8 group quantization with an MSE-OPTIMAL group scale.

    Same frozen wire format as `quantize_weights` (INT4 nibbles, one uint16
    mantissa per group of `g`, one shared exponent per matrix, same `sh`) —
    only the CHOICE of each group's scale changes, so nothing in the RTL or
    the DDR image layout moves.  `quantize_weights` uses scale = max|W_g|/7,
    which spends the whole INT4 range on the single largest weight of the
    group; on real (outlier-heavy) checkpoint weights that costs ~12% relative
    Frobenius error per matrix (audit_ranges_report.md section 2), which is
    the dominant fidelity loss of the whole pipeline.  Here each group's scale
    is picked by a small grid search that minimises the true reconstruction
    error, trading a few clipped outliers for resolution on the bulk.

    `g` is the GROUP SIZE (w4a8_ref module header): 128 = the legacy wire
    format and the default; 64 = the v2 row format (SHAPE bit 28).  The math
    is identical, only the groups are finer.  `sh` does not move with g
    (p_bound is g-independent), so a g=64 image reuses the same requant.

    `salience` (OPT-IN, default None = the frozen behaviour) is a float
    vector of length K: a per-INPUT-CHANNEL activation magnitude, typically
    mean |x_k| measured on a calibration corpus (`ref/calib_stats.py`).  When
    given, each column's squared reconstruction error is weighted by
    `salience[k]**2` in the scale search, i.e. the objective becomes
    ||(W - Wq) diag(salience)||_F^2 — the diagonal approximation of "error
    that the model actually sees", since a column multiplying a large
    activation propagates its error proportionally.  ONLY the choice of each
    group's scale changes: the wire format (w4 / m / e / sh / g and all their
    shapes and dtypes) is untouched, which `_selftest` asserts.  Track Q V3.
    """
    W = np.asarray(Wf, dtype=np.float64)
    N, K = W.shape
    assert K % g == 0
    NG = K // g
    Wg = W.reshape(N, NG, g)
    sw = _salience_weights(salience, K, g)          # None, or (1, NG, g)
    smax = np.maximum(np.abs(Wg).max(axis=2), 1e-12)
    best_s = smax / 7.0
    best_e = np.full((N, NG), np.inf)
    for a in np.linspace(amin, 1.0, nalpha):
        s = (smax / 7.0) * a
        q = np.clip(np.round(Wg / s[:, :, None]), -8, 7)
        sqerr = (q * s[:, :, None] - Wg) ** 2
        err = (sqerr if sw is None else sqerr * sw).sum(axis=2)
        upd = err < best_e
        best_s = np.where(upd, s, best_s)
        best_e = np.where(upd, err, best_e)
    e = int(np.ceil(np.log2(best_s.max()))) + 1
    m = np.clip(np.round(best_s * np.exp2(15 - e)).astype(np.uint32),
                1, 65535).astype(np.uint16)
    eff = m.astype(np.float64) * np.exp2(e - 15)
    w4 = np.clip(np.round(Wg / eff[:, :, None]), -8, 7).astype(np.int8)
    p_bound = NG * 65535 * (g * 8 * 127)
    return {"w4": w4.reshape(N, K), "m": m, "e": e, "g": int(g),
            "sh": max(0, p_bound.bit_length() - 31)}


def quant_linear(Wf, tighten_e=False, mse_scale=True, g=G, salience=None,
                 hess=None):
    """W4A8 group quantization of one matvec matrix.

    `mse_scale` is the PRODUCTION group-scale rule since Phase 1A of
    docs/FIDELITY_REDESIGN.md (see quant_linear_mse): same frozen wire
    format, ~12% less reconstruction error per matrix.  Passing
    mse_scale=False selects the historical max|W_g|/7 rule, which is what
    every artifact committed before Phase 1A was built with.

    `tighten_e` (OPT-IN, default off) reclaims the mantissa headroom the
    shared exponent leaves on the table.  It is only implemented for the
    max-rule quantizer.  `quantize_weights` picks
    e = ceil(log2(max group scale)) + 1,
    which pins max(m) into (2^13, 2^14] even though m is a uint16: two bits
    of the group-scale mantissa are always unused, and every group whose
    scale is more than ~2^15 below the matrix maximum underflows to m == 0
    (clipped up to 1, which quantizes the whole group to INT4 zero).
    Lowering e by the largest delta that still keeps max(m) <= 65535 divides
    the underflow threshold by 2^delta and refines every group scale, at the
    cost of delta bits of the (deliberately conservative) y32 headroom.
    See ref/audit_ranges_report.md section 2 and the stage-5 fidelity report:
    on the real Qwen3.5-0.8B checkpoint NO group needs it (the only 112
    underflowing groups are 14 rows that are literally ~1e-37 in the
    checkpoint), so this stays off by default.

    `g` = quantization group size; 128 (default) is the legacy wire format,
    64 is the v2 row format.  See quant_linear_mse and the w4a8_ref header.

    `salience` (OPT-IN, default None) is the Track Q V3 per-input-channel
    activation weighting; it only reaches the MSE scale search.  None is
    bit-identical to omitting the argument entirely (asserted in _selftest).

    `hess` (OPT-IN, default None) is the Track Q V4 input second moment
    E[x x^T] (or a `gptq.HessFactor`), which selects the GPTQ error-feedback
    quantizer — same wire format, same group-scale search, different nibbles.
    It is mutually exclusive with `salience` (GPTQ weights its scale search by
    the Hessian's own diagonal).  None is bit-identical to omitting it.
    """
    if hess is not None:
        if salience is not None:
            raise SystemExit("GPTQ takes its scale-search weights from the "
                             "Hessian diagonal; passing `salience` as well "
                             "would silently weight it twice")
        if not mse_scale or tighten_e:
            raise SystemExit("GPTQ is only defined on the MSE group-scale "
                             "rule (mse_scale=True, tighten_e=False)")
        import gptq                        # lazy: the frozen path never imports it
        return gptq.quant_linear_gptq(Wf, g=g, hess=hess)
    if mse_scale:
        assert not tighten_e, ("tighten_e is only implemented for the "
                               "max-rule quantizer (see quant_linear_mse)")
        return quant_linear_mse(Wf, g=g, salience=salience)
    if salience is not None:
        raise SystemExit("salience weighting is only defined for the MSE "
                         "group-scale rule (mse_scale=True); the historical "
                         "max|W_g|/7 rule has no scale search to weight")
    w4, m, e, sh = quantize_weights(np.asarray(Wf, dtype=np.float64), g=g)
    if tighten_e:
        W = np.asarray(Wf, dtype=np.float64)
        N, K = W.shape
        NG = K // g
        scale = np.maximum(np.abs(W.reshape(N, NG, g)).max(axis=2), 1e-12) / 7.0
        d = 0
        while d < 15 and np.round(scale.max() * np.exp2(15 - (e - d - 1))) <= 65535:
            d += 1
        if d:
            e -= d
            m = np.clip(np.round(scale * np.exp2(15 - e)).astype(np.uint32),
                        1, 65535).astype(np.uint16)
            eff = m.astype(np.float64) * np.exp2(e - 15)
            w4 = np.clip(np.round(W.reshape(N, NG, g) / eff[:, :, None]),
                         -8, 7).astype(np.int8).reshape(N, K)
    return {"w4": w4, "m": m, "e": int(e), "sh": int(sh), "g": int(g)}


def quant_linear_w8(Wf, g=G, rowchunk=None):
    """W8A8 group quantization of one matvec matrix — the V5 twin of
    `quant_linear` (gate D, "W8 everywhere").

    It IS `w4a8_ref.quantize_weights8` packed into a dict: the production
    quantizer is the wire law, and this file does not get a second copy of
    it (the same principle that keeps `quant_linear`'s max-rule branch a
    call to `quantize_weights`).  Everything about the ENCODING except the
    weight width is the W4 one — a uint16 mantissa per group of `g`, one
    shared exponent per matrix, value `m * 2^(e-15)`, one final `sh` — so
    every consumer of `e`/`sh` (shift_for, matvec_to, the emitters'
    dequant immediates) needs no W8 case at all.

    The weight key is `"w8"`, NOT `"w4"`.  That is the type tag: an int8
    code array read as nibbles would decode to garbage silently, so the
    only safe design is a key the W4 readers do not recognise.  Read a
    dict's codes with `qw_codes` rather than by indexing a literal key.

    `g` is the quantization group size, as in `quant_linear`.  The W8 WIRE
    format is defined at g=128 cadence only — that restriction lives in
    the SHAPE word (`sw/hwmap.shape_word` asserts it) and in the engine,
    not in the arithmetic, which is group-agnostic; `_w8_invariance`
    exercises both sizes for exactly that reason.

    `rowchunk` (default None = one shot) forwards to `quantize_weights8`'s
    row blocking, which is bit-identical and is how the full-vocab LM head
    is quantized without a multi-GiB float64 temporary — the W8 answer to
    `gen_model_script.quant_linear_big`.

    NOTE what is NOT here: no MSE scale search, no salience weighting, no
    GPTQ.  V5 is plain W8 (the Track Q study ruled the calibrated variants
    out of scope at 8 bits), and `_quant_matvec` REFUSES those knobs on
    this path rather than accepting and ignoring them.
    """
    w8, m, e, sh = quantize_weights8(np.asarray(Wf), g=g, rowchunk=rowchunk)
    return {"w8": w8, "m": m, "e": int(e), "sh": int(sh), "g": int(g)}


def qw_codes(qw):
    """(weight code array, is_w8) of a quantized matvec dict.

    THE one place that knows a W4 image carries "w4" (int4 codes in an
    int8 array) and a W8 image carries "w8" (int8 codes).  Everything that
    reaches into a quantized dict for its weights — the matvec dispatch,
    the fidelity probes, the shape tags — goes through here, so no reader
    can silently treat one width as the other.
    """
    if "w8" in qw:
        assert "w4" not in qw, \
            "a quantized dict carries ONE weight image, not both w4 and w8"
        return qw["w8"], True
    return qw["w4"], False


def _quant_matvec(Wf, tighten_e, mse_scale, g, cal, w8):
    """Quantize ONE matvec matrix for quant_attn/quant_deltanet/quant_mlp.

    `w8=False` (every frozen flow) is the `quant_linear(...)` call those
    three used to make, argument for argument.  `w8=True` selects V5's
    plain 8-bit quantizer — and REFUSES the W4-only knobs instead of
    ignoring them, because a W8 run whose log says "mse" or "salience"
    would be a number nobody could interpret afterwards (the discipline
    `_calib_mode` / `check_res_scale` already apply to their knobs).
    """
    salience, hess = cal
    if not w8:
        return quant_linear(Wf, tighten_e, mse_scale, g, salience, hess)
    if tighten_e:
        raise SystemExit("tighten_e is a W4 exponent fix-up (quant_linear); "
                         "W8's shared exponent is chosen by "
                         "quantize_weights8 and has no such knob")
    if not mse_scale:
        raise SystemExit("mse_scale selects between the two W4 group-scale "
                         "rules; W8 has ONE rule (max|W_g|/127, "
                         "quantize_weights8), so mse_scale=False on a W8 run "
                         "would silently score the same image under a "
                         "different name")
    if salience is not None or hess is not None or CALIB_STATS:
        raise SystemExit(
            "the calibrated quantizers (FABLE5_CALIB_STATS salience / h2 / "
            "gptq) are W4-only — V5 is plain W8 and the Track Q study ruled "
            "GPTQ-on-W8 out of scope. Running them together would quantize "
            "W8 weights with the plumb silently ignored. Unset "
            "FABLE5_CALIB_STATS for W8 runs, or drop w8.")
    return quant_linear_w8(Wf, g=g)


def matvec_fx(qw, x16, out_f):
    """W4A8 matvec: int16 input (RS-scaled by in_f bits implied in caller),
    returns int32 vector with out_f fraction bits relative to the FLOAT
    product W_f @ x_real. Exact: y_real ~= W@x; y_out = round(y_real*2^out_f).
    in_f: fraction bits of x16.

    The group size travels in the quantized dict ("g", absent == 128) and is
    handed to matvec_y32 explicitly; the accumulate order is identical in
    both modes (see the matvec_y32 docstring).

    The WEIGHT WIDTH travels the same way (V5): a `{"w8",...}` dict goes to
    `matvec_y32_w8`, which is `matvec_y32` plus the [-127,127] code-range
    contract.  This is the ONLY matvec call in this file, so it is also the
    only place `matvec_to` and everything above it needs a W8 case."""
    x8, e_x = fp.dyn_quant_i8(x16)
    w, w8 = qw_codes(qw)
    mv = matvec_y32_w8 if w8 else matvec_y32
    y32 = mv(w, qw["m"], qw["sh"], x8, g=qw.get("g", G))
    # y32 scale: x8*2^-(in_f - e_x) ... dequant = y32 * 2^(e-15+sh) * 2^(e_x-in_f)
    # caller passes in_f via closure: we standardize x16 always carries in_f
    return y32, e_x


def matvec_to(qw, x16, in_f, out_f):
    """Full path: x16 (in_f frac) -> y int64 with out_f frac bits.
    y_real = y32 * 2^(e-15+sh) * 2^(e_x-in_f); y_out = y_real * 2^out_f
           = y32 >> ((15-e-sh) - e_x + in_f - out_f).

    W4 and W8 dicts both come through here unchanged: the weight-width
    branch is inside `matvec_fx`, and W8 reuses the W4 (e, sh) scale law
    verbatim (ref/w4a8_ref.py's W8 header), so this shift needs no case."""
    y32, e_x = matvec_fx(qw, x16, out_f)
    sh = (15 - qw["e"] - qw["sh"]) - e_x + in_f - out_f
    if sh >= 0:
        return rshr(y32.astype(I64), sh)
    return y32.astype(I64) << (-sh)


# ----------------------------------------------------------------------
# vector blocks
# ----------------------------------------------------------------------
def rmsnorm_fx(x16, w_q14, in_f, one_plus):
    """RMSNorm: x int (in_f frac), weight Q14 int16 (zero-centered if
    one_plus). Output int16 with in_f frac bits (unit-RMS scaled).

    SCALE INVARIANCE (relied on by the DeltaNet block floating — verified
    here, not assumed).
    Let the input actually carry f fraction bits, x16 = X*2^f, while the
    caller passes in_f = F.  Then
        ss   = sum(x16^2)               = sum(X^2) * 2^(2f)
        rsqrt_q(ss, 2F+n) reads ss as    mean(X^2) * 2^(2f-2F)
        => r*2^(e-30) = 2^(F-f) / rms(X)
        y = rshr(x16*r, 30-e)           = (X/rms(X)) * 2^F
    The 2^f cancels: `in_f` is purely the OUTPUT binary point, the input's
    real binary point never appears.  So shifting x16 by any k (the DN
    block-floating k_h) leaves this function's output format at Q.in_f and
    its value unchanged except for rounding.  The DeltaNet gated norm now
    runs as script_norm_fx (op2 SCALE + op3 EMUL) rather than this vecnorm,
    but the same algebra is what makes dn_norm_scale's 2^(15 + k_h) factor
    exact and keeps the gated-norm output pinned at Q.DN_NORM_F whatever
    k_h is — so nothing downstream of the DeltaNet moves with k_h.
    THIS function is still the ln1/ln2/q_norm/k_norm/ln_f path (vn modes
    0 and 1), which is unchanged.
    """
    x = np.asarray(x16, dtype=I64)
    n = len(x)
    ss = int((x * x).sum())                      # frac 2*in_f
    if ss == 0:
        ss = 1
    # mean = ss/n; rsqrt(mean) — fold n into the binary point when pow2
    nbits = int(np.log2(n))
    _require_pow2_n(n, nbits, "rmsnorm_fx")
    r, e = fp.rsqrt_q(ss, 2 * in_f + nbits)      # 1/sqrt(mean(x^2))
    y = rshr(x * r, 30 - e)                      # x * rsqrt, frac in_f
    y = np.clip(y, -(1 << 32), (1 << 32) - 1)    # RTL 33-bit intermediate
    w = np.asarray(w_q14, dtype=I64)
    scale = w + (1 << 14) if one_plus else w
    return clip16(rshr(y * scale, 14))


def script_norm_fx(o32, o16, k_h, w_q14, note=True):
    """Gated RMSNorm as a SCRIPT-SIDE per-head scale (the production path).

    The generator already models `o32` (the dnst Q.S_F output) bit-exactly,
    so it computes the head's normalisation factor itself -- INCLUDING the
    reference eps that vecnorm_unit does not have -- and emits it as an ALU
    SCALE immediate.  Hardware then only multiplies:

        m_q15 = dn_norm_scale(o32, k_h)         the op-2 SCALE immediate
        u     = clip16(rshr64s(o32, k_h))       op1 SHIFT32, already emitted
        t     = clip16(rshr(u * m_q15, 15))     op2 SCALE  (>>15 hardwired)
        y     = clip16(rshr(t * w_q14, 14))     op3 EMUL with norm_w

    y is at Q.DN_NORM_F, exactly like the vecnorm it replaces (see the
    SCALE-INVARIANCE note in rmsnorm_fx for why k_h never propagates).

    SEQ_NORM (opt-in, docs/SEQ_ISA.md) swaps the first two lines for the
    on-chip EPS-NORM: the scale comes from eps_norm_fx (integer rsqrt ROM
    path, ss taken from o16 and the eps floor added in the ss domain) so
    the host never sees o32 and the token loop needs no round trip.  o32
    is then used ONLY to score the integer scale against the float one
    (SEQ_STATS, observational).  Default False = the shipped path, so the
    generators and every committed artifact are unaffected.
    """
    if SEQ_NORM:
        t = eps_norm_fx(o16, k_h, note=note)
        if note:                       # observational: integer vs float m_q15
            m_ref = dn_norm_scale(o32, k_h, note=False)
            m_int = eps_norm_scale(np.asarray(o16, dtype=I64), k_h, note=False)
            d = abs(m_int - int(np.clip(m_ref, 0, M_Q15_MAX)))
            SEQ_STATS["exact"] += int(d == 0)
            SEQ_STATS["d_max"] = max(SEQ_STATS["d_max"], d)
            if m_ref > 0:
                SEQ_STATS["rel_max"] = max(SEQ_STATS["rel_max"],
                                           d / float(m_ref))
    else:
        m_q15 = dn_norm_scale(o32, k_h, note=note)
        t = clip16(rshr(clip16(o16) * I64(m_q15), 15))
    return clip16(rshr(t * np.asarray(w_q14, dtype=I64), 14))


def l2norm_fx(x16, in_f, out_f):
    """L2-normalize a head vector -> int16 with out_f frac bits."""
    x = np.asarray(x16, dtype=I64)
    ss = int((x * x).sum())
    if ss == 0:
        ss = 1
    r, e = fp.rsqrt_q(ss, 2 * in_f)              # 1/||x||
    # out = (x*2^-in_f)*(r*2^-30*2^e)*2^out_f  =>  shift = in_f + 30 - e - out_f
    return clip16(rshr(x * r, in_f + 30 - e - out_f))


def rope_tables_q15(pos):
    """Q15 tables clamped to int16 (cos(0)=+1.0 would round to +32768)."""
    cos, sin = LR.rope_cos_sin(pos)
    return (np.clip(np.round(cos * (1 << ROPE_F)), -32767, 32767).astype(I64),
            np.clip(np.round(sin * (1 << ROPE_F)), -32767, 32767).astype(I64))


def rope_fx(x16, cos_q, sin_q):
    """Rotate first ROT dims; int16 in/out, same frac."""
    x = np.asarray(x16, dtype=I64)
    ROT = LR.ROT
    xr, xp = x[:ROT], x[ROT:]
    h = ROT // 2
    rot = np.concatenate([-xr[h:], xr[:h]])
    y = rshr(xr * cos_q + rot * sin_q, ROPE_F)
    return clip16(np.concatenate([y, xp]))


# ----------------------------------------------------------------------
# full attention (decode step)
# ----------------------------------------------------------------------
def res_scaled(W, s):
    """W * s in float64 (s is a power of two, so this is EXACT)."""
    W = np.asarray(W, dtype=np.float64)
    return W if s == 1.0 else W * np.float64(s)


def quant_attn(wf, res_scale=1.0, tighten_e=False, mse_scale=True, g=G,
               layer_idx=None, w8=False):
    def cal(k):
        return _calib_for("attn", k, layer_idx)

    def q(W, k):
        return _quant_matvec(W, tighten_e, mse_scale, g, cal(k), w8)
    return {
        "q_proj": q(wf["q_proj"], "q_proj"),
        "k_proj": q(wf["k_proj"], "k_proj"),
        "v_proj": q(wf["v_proj"], "v_proj"),
        "o_proj": q(res_scaled(wf["o_proj"], res_scale), "o_proj"),
        "q_norm": np.round(np.asarray(wf["q_norm"]) * (1 << 14)).astype(I64),
        "k_norm": np.round(np.asarray(wf["k_norm"]) * (1 << 14)).astype(I64),
    }


def kv_quant(v16, in_f):
    """int16 vector -> (int8 mantissas, shared exponent) power-of-2."""
    x8, e = fp.dyn_quant_i8(v16)
    return x8.astype(np.int8), e - in_f          # value = x8 * 2^(e - in_f)


def attn_decode_fx(xn16, qw, cache, pos):
    """xn16: normed residual int16 Q7.8. Returns int16 Q7.8 contribution."""
    NQ, NKV, HD = LR.NQ, LR.NKV, LR.HD
    qg = matvec_to(qw["q_proj"], xn16, RS_F, QKV_F).reshape(NQ, 2 * HD)
    # gate clip16 = RTL int16 scratch transport; output-identical since
    # sigmoid_q saturates for |x| >= 16.0 Q12 i.e. |gate| >= 4096 Q8
    q16, gate = clip16(qg[:, :HD]), clip16(qg[:, HD:])      # Q.QKV_F
    k16 = clip16(matvec_to(qw["k_proj"], xn16, RS_F, QKV_F).reshape(NKV, HD))
    v16 = clip16(matvec_to(qw["v_proj"], xn16, RS_F, QKV_F).reshape(NKV, HD))

    cos_q, sin_q = rope_tables_q15(pos)
    qn = np.stack([rope_fx(rmsnorm_fx(q16[h], qw["q_norm"], QKV_F, True), cos_q, sin_q)
                   for h in range(NQ)])                     # Q.QKV_F unit-RMS
    kn = np.stack([rope_fx(rmsnorm_fx(k16[h], qw["k_norm"], QKV_F, True), cos_q, sin_q)
                   for h in range(NKV)])

    # KV cache: int8 + exponent per (token, head)
    cache["k"].append([kv_quant(kn[h], QKV_F) for h in range(NKV)])
    cache["v"].append([kv_quant(v16[h], QKV_F) for h in range(NKV)])
    T = len(cache["k"])

    group = NQ // NKV
    out = np.zeros((NQ, HD), dtype=I64)                     # Q.QKV_F
    SCALE_Q15 = int(round((1 << 15) / np.sqrt(HD)))
    for h in range(NQ):
        kv = h // group
        # scores in Q16 for exp_neg_q
        sc = np.zeros(T, dtype=I64)
        for t in range(T):
            k8, ke = cache["k"][t][kv]
            dot = int((qn[h].astype(I64) * k8.astype(I64)).sum())   # frac QKV_F - ke... value = dot*2^(ke-QKV_F)
            # score = dot * 2^(ke - QKV_F) / sqrt(HD); to Q16:
            s = rshr(I64(dot) * SCALE_Q15, 15)
            f = QKV_F - ke - 16
            sc[t] = rshr(I64(int(s)), f) if f >= 0 else int(s) << (-f)
        mx = int(sc.max())
        es = np.array([fp.exp_neg_q(int(min(sc[t] - mx, 0))) for t in range(T)],
                      dtype=I64)                            # Q30
        denom = int(es.sum())                               # Q30
        r, re = fp.recip_q(denom, 30)
        # p[t] Q15 = es[t] * recip
        p = rshr(es * r, 30 - re + 15)                      # Q30*Q30->.. to Q15
        p = np.clip(p, 0, 1 << 15)
        # acc_QKV_F = sum_t rshr(p[t]*v8, 15 - ve)
        acc = np.zeros(HD, dtype=I64)
        for t in range(T):
            v8, ve = cache["v"][t][kv]
            # term_real = p*2^-15 * v8*2^ve; acc(frac QKV_F) => >> (15-ve-QKV_F)
            term = I64(int(p[t])) * v8.astype(I64)
            sh = 15 - ve - QKV_F
            acc += rshr(term, sh) if sh >= 0 else term << (-sh)
        out[h] = acc                                        # Q.QKV_F

    # output gate: sigmoid(gate) Q15; gate is Q.QKV_F -> to Q12 for sigmoid_q
    og = np.array([fp.sigmoid_q(rshr(I64(int(g)), QKV_F - 12)) for g in
                   gate.reshape(-1)], dtype=I64)
    prod = out.reshape(-1) * og                             # Q.(QKV_F+GAT_F)
    # int32*Q15 -> int16 alignment, ONE block-float shift for the whole token
    # (gen_layer_script.attn_token: `M.alu(8, 256, k_a, AO32, OG, GATED+...)`).
    k_a = attn_o_shift(int(np.abs(prod).max()))
    gated = rshr(prod, k_a)                                 # k_a >= 0
    cache["attn_o_shift"] = k_a
    # the o_proj input frac bits move with k_a; matvec_to folds them into the
    # requant shift, and dyn_quant_i8 is exactly power-of-two invariant, so
    # this is a pure resolution change with no residual-scale side effect.
    y = matvec_to(qw["o_proj"], clip16(gated), QKV_F + GAT_F - k_a, RS_F)
    return clip16(y)


# ----------------------------------------------------------------------
# DeltaNet (decode step)
# ----------------------------------------------------------------------
def quant_deltanet(wf, res_scale=1.0, tighten_e=False, mse_scale=True, g=G,
                   layer_idx=None, w8=False):
    # Spec (unbounded) quantization first, then SATURATE into the frozen
    # gate_unit ports.  Both clamps are no-ops for every synthetic-weight
    # script ever committed, so stage-3/4/5-(1)(2) artifacts are unchanged.
    dt_spec = np.round(np.asarray(wf["dt_bias"]) * (1 << 12)).astype(I64)
    A_spec = np.round(np.exp(wf["A_log"]) * (1 << 15)).astype(I64)
    dt_q = np.clip(dt_spec, DT_Q12_MIN, DT_Q12_MAX)
    A_q = np.clip(A_spec, 0, A_Q15_MAX)

    def cal(k):
        return _calib_for("dn", k, layer_idx)

    def q(W, k):
        return _quant_matvec(W, tighten_e, mse_scale, g, cal(k), w8)
    qd = {
        "in_qkv": q(wf["in_qkv"], "in_qkv"),
        "in_z": q(wf["in_z"], "in_z"),
        "in_b": q(wf["in_b"], "in_b"),
        "in_a": q(wf["in_a"], "in_a"),
        "out": q(res_scaled(wf["out"], res_scale), "out"),
        "conv_w": np.round(np.asarray(wf["conv_w"]) * (1 << CW_F)).astype(I64),
        "dt_bias_q12": dt_q,
        # legacy alias, unreferenced; kept at its historical (positive) value
        "negA_q15": A_q,
        # store A = exp(A_log) Q15 (positive), port-saturated
        "norm_w_q14": np.round(np.asarray(wf["norm_w"]) * (1 << 14)).astype(I64),
    }
    qd["A_q15"] = A_q
    # provenance for the range audit: which heads had to saturate, and by
    # how much (0 entries => this layer is an exact port fit)
    qd["gate_sat"] = [(int(h), int(dt_spec[h]), int(dt_q[h]),
                       int(A_spec[h]), int(A_q[h]))
                      for h in range(len(dt_q))
                      if dt_spec[h] != dt_q[h] or A_spec[h] != A_q[h]]
    return qd


def deltanet_decode_fx(xn16, qd, state):
    # LNH = VALUE heads, LNKH = KEY heads, VREP = LNH // LNKH.  They are equal
    # at 0.8B/2B (VREP == 1) and differ at 4B/9B (16 key heads feed 32 value
    # heads), so the q/k slice width is LR.LKD = LNKH*LDK — NOT LNH*LDK — and
    # value head h reads key head h // VREP
    # (vendor/modeling_qwen3_5.py:519-521, mirrored in layer_ref.deltanet_decode).
    LNH, LDK, LDV = LR.LNH, LR.LDK, LR.LDV
    LNKH, LKD, VREP = LR.LNKH, LR.LKD, LR.VREP
    qkv16 = clip16(matvec_to(qd["in_qkv"], xn16, RS_F, RS_F))
    z16 = clip16(matvec_to(qd["in_z"], xn16, RS_F, QKV_F)).reshape(LNH, LDV)
    # int16 transport width (RTL gate_unit port); sigmoid/softplus saturate
    # beyond +/-8.0 so the clip only pins the already-flat tail
    b_q12 = clip16(matvec_to(qd["in_b"], xn16, RS_F, 12))
    a_q12 = clip16(matvec_to(qd["in_a"], xn16, RS_F, 12))

    # depthwise conv4 + silu  (win frac RS_F, weights CW_F)
    win = np.concatenate([state["conv"], qkv16[:, None]], axis=1)   # (C,4)
    state["conv"] = win[:, 1:]
    acc = (win.astype(I64) * qd["conv_w"]).sum(axis=1)              # frac RS_F+CW_F
    pre = rshr(acc, RS_F + CW_F - 12)                               # Q12
    pre = np.clip(pre, -(1 << 20), (1 << 20) - 1)   # RTL 21-bit silu port
    conv_out = clip16(np.array([fp.silu_q(int(v)) for v in pre], dtype=I64))
    # (int16 Q12 — RTL fx_silu output width)
    qkv = rshr(conv_out, 12 - QKV_F)                                # Q.QKV_F

    q = qkv[:LKD].reshape(LNKH, LDK)
    k = qkv[LKD:2 * LKD].reshape(LNKH, LDK)
    v = qkv[2 * LKD:].reshape(LNH, LDV)

    # gates per head
    beta = np.array([fp.sigmoid_q(int(b)) for b in b_q12], dtype=I64)      # Q15
    # g = -A * softplus(a + dt_bias); decay = exp(g) Q15
    decay = np.zeros(LNH, dtype=I64)
    for h in range(LNH):
        sp = fp.softplus_q(int(a_q12[h] + qd["dt_bias_q12"][h]))           # Q12
        g_q16 = -rshr(I64(int(qd["A_q15"][h])) * sp, 15 + 12 - 16)         # Q16 <=0
        decay[h] = min(rshr(I64(fp.exp_neg_q(int(min(g_q16, 0)))), 15),
                       I64(32767))      # Q15 saturated to int16 (RTL width)

    INV_SQRT_DK_Q15 = int(round((1 << 15) / np.sqrt(LDK)))
    o16 = np.zeros((LNH, LDV), dtype=I64)
    o32 = np.zeros((LNH, LDV), dtype=I64)      # the Q.S_F dnst output
    S = state["S"]                                                  # int16 Q.S_F
    sat = 0
    k_log = []                       # per-head block-float shifts (op 1 immed)
    for h in range(LNH):
        kh = h // VREP                          # the KEY head this value head reads
        qn = l2norm_fx(q[kh], QKV_F, NRM_F)
        qn = rshr(qn * I64(INV_SQRT_DK_Q15), 15)                    # Q.NRM_F
        kn = l2norm_fx(k[kh], QKV_F, NRM_F)

        Sh = S[h].astype(I64)
        Sh = rshr(Sh * I64(int(decay[h])), GAT_F)                   # decay
        kv_mem = rshr((Sh * kn[:, None]).sum(axis=0), NRM_F)        # Q.S_F
        # v is Q.QKV_F; align to S_F
        v_s = rshr(v[h], QKV_F - S_F) if QKV_F >= S_F else v[h] << (S_F - QKV_F)
        delta = rshr((v_s - kv_mem) * I64(int(beta[h])), GAT_F)     # Q.S_F
        Sh = Sh + rshr(kn[:, None] * delta[None, :], NRM_F)         # Q.S_F
        sat += int((np.abs(Sh) > 32767).sum())
        # the state-range audit G1 needs, taken BEFORE either clip so it is
        # the accumulator's own range and not the container's
        DN_STATS["writes"] += int(Sh.size)
        DN_STATS["absmax"] = max(DN_STATS["absmax"], int(np.abs(Sh).max()))
        DN_STATS["sat16"] += int((np.abs(Sh) > 32767).sum())
        # THE CONTAINER LAW (G1), applied to the UNCLIPPED accumulator so the
        # chosen container saturates at its OWN rail and only there.  Under
        # FABLE5_DN_STATE=int16 it IS `clip16`, i.e. this line is exactly the
        # `Sh = clip16(Sh)` it replaces, byte for byte.
        Sh = dn_state_narrow(Sh)
        o = rshr((Sh * qn[:, None]).sum(axis=0), NRM_F)             # Q.S_F
        o32[h] = o
        # int32 -> int16: per-head, per-token block floating (op 1 SHIFT32)
        k_h = dn_o_shift(o)
        o16[h] = clip16(rshr(o, k_h) if k_h >= 0 else o << (-k_h))
        k_log.append(k_h)
        S[h] = Sh.astype(S.dtype)      # int16 shipped; see new_cache_fx
    state["sat"] = state.get("sat", 0) + sat
    state["dn_o_shift"] = k_log              # what dn_token emits (op 1)

    # gated rmsnorm (script-side scale, op2 SCALE + op3 EMUL) + silu(z)
    on = np.zeros((LNH, LDV), dtype=I64)
    for h in range(LNH):
        nh = script_norm_fx(o32[h], o16[h], k_log[h], qd["norm_w_q14"])
        zg = clip16(np.array([fp.silu_q(rshr(I64(int(zz)), QKV_F - 12))
                              for zz in z16[h]], dtype=I64))        # Q12 int16
        on[h] = rshr(nh * zg, 12)
    y = matvec_to(qd["out"], clip16(on.reshape(-1)), DN_NORM_F, RS_F)
    return clip16(y)


# ----------------------------------------------------------------------
# MLP + layer
# ----------------------------------------------------------------------
def quant_mlp(wf, res_scale=1.0, tighten_e=False, mse_scale=True, g=G,
              layer_idx=None, w8=False):
    q = {k: _quant_matvec(wf[k], tighten_e, mse_scale, g,
                          _calib_for("mlp", k, layer_idx), w8)
         for k in ("gate", "up")}
    q["down"] = _quant_matvec(res_scaled(wf["down"], res_scale), tighten_e,
                              mse_scale, g,
                              _calib_for("mlp", "down", layer_idx), w8)
    return q


def mlp_fx(xn16, qm):
    g = matvec_to(qm["gate"], xn16, RS_F, 12)
    u = matvec_to(qm["up"], xn16, RS_F, RS_F)
    sg = clip16(np.array([fp.silu_q(int(np.clip(x, -(1 << 20), (1 << 20) - 1)))
                          for x in g], dtype=I64))                  # Q12 int16
    # (input clip = RTL 21-bit port; output clip16 = RTL output width)
    prod = clip16(rshr(sg * u, 12))                                 # Q.RS_F
    return clip16(matvec_to(qm["down"], prod, RS_F, RS_F))


def quant_layer(wf, res_scale=1.0, tighten_e=False, mse_scale=True, g=G,
                layer_idx=None, w8=False):
    """Quantize one decoder layer.

    `res_scale` S multiplies ONLY the residual-adding projection of each
    sub-block (attn.o_proj / dn.out and mlp.down) before quantization.  Done
    for every layer AND on the embedding table (caller's job), it scales the
    entire residual stream by S: RMSNorm is invariant to a positive scale of
    its input, so every norm output, every matvec input and the final argmax
    are EXACTLY unchanged in float.  In fixed point the residual (int16 Q7.8)
    then carries log2(S) more fraction bits — the embedding seed goes from
    0.18% of the rail to S*0.18% — traded against int16 headroom.
    S must be a power of two so the quantization is exact (a power-of-two
    scale shifts `e` by log2(S) and leaves w4/m/sh bit-identical).
    Default 1.0 reproduces every committed artifact byte for byte.

    `g` = W4 group size for EVERY matvec matrix of this layer (128 legacy /
    64 = v2 row format).  Default 128 keeps every committed artifact
    bit-identical; the flip to 64 is an explicit opt-in from the generators.

    `layer_idx` is this layer's index in the model.  It is used for exactly
    ONE thing: looking up per-tensor activation salience when
    FABLE5_CALIB_STATS is set (Track Q V3).  With that env var unset — the
    default, and every frozen flow — it is ignored entirely.

    `w8` (OPT-IN, default False = every frozen flow, bit-identically) puts
    EVERY matvec matrix of this layer in the V5 8-bit weight format
    (`quant_linear_w8`).  It changes the weight images and nothing else:
    the norms, the conv window, the DeltaNet gate ports and the whole
    fixed-point datapath are untouched, which `_w8_invariance` asserts.
    The W4-only knobs (tighten_e, mse_scale=False, the FABLE5_CALIB_STATS
    plumb) are REFUSED under it rather than ignored.
    """
    qw = {"ln1": np.round(np.asarray(wf["ln1"]) * (1 << 14)).astype(I64),
          "ln2": np.round(np.asarray(wf["ln2"]) * (1 << 14)).astype(I64),
          "mlp": quant_mlp(wf["mlp"], res_scale, tighten_e, mse_scale, g,
                           layer_idx, w8),
          "type": wf["type"]}
    if wf["type"] == "full_attention":
        qw["attn"] = quant_attn(wf["attn"], res_scale, tighten_e, mse_scale, g,
                                layer_idx, w8)
    else:
        qw["dn"] = quant_deltanet(wf["dn"], res_scale, tighten_e, mse_scale, g,
                                  layer_idx, w8)
    return qw


def new_cache_fx(layer_type):
    if layer_type == "full_attention":
        return {"k": [], "v": []}
    # The state array's DTYPE is the container's transport width in this
    # model, not the container itself: `dn_state_narrow` decides what values
    # are representable.  int16 is the shipped container and stays int16 —
    # byte-identical — but an int8:<k> container holds codes at Q.(S_F-k),
    # which re-expanded to Q.S_F reach 127 << k, and that leaves int16 at
    # k >= 9 (127 << 9 = 65024).  Storing those in int16 would WRAP, i.e. the
    # narrow k values would have been scored against a silently broken state.
    return {"conv": np.zeros((LR.CONV_DIM, LR.CONV_K - 1), dtype=I64),
            "S": np.zeros((LR.LNH, LR.LDK, LR.LDV),
                          dtype=np.int16 if DN_STATE_LAW == "int16" else I64)}


def layer_decode_fx(x16, qw, cache, pos):
    xn = rmsnorm_fx(x16, qw["ln1"], RS_F, True)
    if qw["type"] == "full_attention":
        h = attn_decode_fx(xn, qw["attn"], cache, pos)
    else:
        h = deltanet_decode_fx(xn, qw["dn"], cache)
    x16 = clip16(np.asarray(x16, dtype=I64) + h)
    xn = rmsnorm_fx(x16, qw["ln2"], RS_F, True)
    return clip16(x16 + mlp_fx(xn, qw["mlp"]))


# ----------------------------------------------------------------------
# self-test: matched-input per-block fidelity (the meaningful metric).
# Trajectory comparisons diverge chaotically through caches/states and are
# dominated by inherent W4 weight-quantization noise on random weights —
# they are NOT a fixed-point correctness signal. Instead: feed identical
# inputs/state to fixed and float versions of each VECTOR block and require
# fixed-point-resolution agreement; matvec blocks are checked against the
# documented W4 noise floor separately (see w4a8_ref).
# ----------------------------------------------------------------------
def _blk(name, got, ref, bound):
    got = np.asarray(got, dtype=np.float64)
    ref = np.asarray(ref, dtype=np.float64)
    rel = np.abs(got - ref).max() / (np.abs(ref).max() + 1e-12)
    ok = rel < bound
    print(f"  {name:22s} rel={rel:.3e}  bound={bound:.0e}  {'OK' if ok else 'FAIL'}")
    return ok


def _dynq16_cases(rng):
    """Blocks that exercise every corner of the DYNQ16 exponent path."""
    cases = []
    I32MIN, I32MAX = -(1 << 31), (1 << 31) - 1
    for L in range(1, 33):                      # every possible bitlen(absmax)
        hi = min((1 << L) - 1, 1 << 31)         # |x| <= 2^31 (int32 domain)
        lo = min(1 << (L - 1), 1 << 31)
        for _ in range(6):
            x = np.clip(rng.integers(-hi, hi + 1, 128, dtype=np.int64),
                        I32MIN, I32MAX)
            x[int(rng.integers(0, 128))] = int(
                np.clip(rng.choice([lo, -lo, hi, -hi]), I32MIN, I32MAX))
            cases.append(("rand", x))
    for k in range(1, 18):                      # the (32767.5, 32768) fixup
        base = 1 << (15 + k)
        for j in (1, 2, (1 << (k - 1)) if k > 1 else 1,
                  (1 << (k - 1)) + 1 if k > 1 else 2, 1 << k):
            m = base - j
            if 0 < m <= (1 << 31):
                cases.append(("fixup", np.array([m, -m, 0, 1], dtype=I64)))
                cases.append(("fixup", np.array([-m, m // 3, 0, 0],
                                                dtype=I64)))
    cases.append(("zero", np.zeros(128, dtype=I64)))
    cases.append(("zero1", np.zeros(1, dtype=I64)))
    cases.append(("int32min", np.full(8, -(1 << 31), dtype=I64)))
    cases.append(("int32max", np.full(8, (1 << 31) - 1, dtype=I64)))
    for v in (1, -1, 2, 16383, 16384, 32767, 32768, 32769, 65535, 65536):
        cases.append((f"tiny{v}", np.array([v, -v, v // 2, 0], dtype=I64)))
    return cases


def _dynq16_soak():
    """DYNQ16 (vec_alu op 12) IS the shipped bf_shift + rshr64s path.

    Asserts, element for element and over every exponent decade:
      dynq16_fx(o32)            == (dn_o_shift  + op-1 SHIFT32) on the DN path
      dynq16_fx(prod, clamp0=1) == (attn_o_shift + op-8 EMUL32 shift)
    plus the properties the RTL relies on (no clip16, block fills the int16,
    k in [-14,17], and the "top 16 bits all ones" form of the +1 fixup).
    """
    assert BF_GUARD == 0, "DYNQ16 has no guard input: the spec is guard 0"
    rng = np.random.default_rng(1212)
    cases = _dynq16_cases(rng)
    n_fix = n_neg = n_zero = 0
    kmin, kmax, ymin = 99, -99, 32767
    for tag, x in cases:
        x = np.asarray(x, dtype=I64)
        absmax = int(np.abs(x).max())
        y, k = dynq16_fx(x)
        # (a) k is EXACTLY the immediate the generator emits today
        assert k == dn_o_shift(x, note=False), (tag, absmax, k)
        # (b) y is EXACTLY what vec_alu op 1 writes for that immediate
        ref = clip16(rshr(x, k))
        assert np.array_equal(y, ref), (tag, absmax, k)
        # (c) clip16 is inert -> the RTL never has to reason about clipping
        raw = rshr(x, k)
        assert int(np.abs(raw).max()) <= 32767, (tag, absmax, k)
        # (d) the block fills the int16 (that is the point of the op)
        if absmax:
            assert int(np.abs(y).max()) >= 16384, (tag, absmax, k)
            ymin = min(ymin, int(np.abs(y).max()))
        else:
            assert k == 0 and not y.any()
            n_zero += 1
        # (e) k range / RTL fixup form: fix <=> top 16 bits of maxabs are 1s
        assert -14 <= k <= 17, (tag, k)
        L = absmax.bit_length()
        k0 = 0 if L == 0 else L - 15
        fix = (k0 > 0) and ((absmax >> (L - 16)) == 0xFFFF)
        assert k == k0 + int(fix), (tag, absmax, k, k0, fix)
        n_fix += int(fix)
        n_neg += int(k < 0)
        kmin, kmax = min(kmin, k), max(kmax, k)
        # (f) clamp0 mode == the attention immediate + its shift
        yc, kc = dynq16_fx(x, clamp0=True)
        assert kc == attn_o_shift(absmax, note=False), (tag, absmax, kc)
        assert np.array_equal(yc, clip16(rshr(x, kc))), (tag, absmax, kc)
        assert kc == max(k, 0)
    # (g) the LIVE DN path: intercept every dn_o_shift call inside
    # deltanet_decode_fx and require DYNQ16 to reproduce it on the real o32
    import sys as _sys
    mod = _sys.modules[__name__]
    orig, n_live = mod.dn_o_shift, 0
    def _rec(o32, note=True):
        nonlocal n_live
        k_ref = orig(o32, note=note)
        y, k = dynq16_fx(o32)
        assert k == k_ref
        assert np.array_equal(y, clip16(rshr(np.asarray(o32, dtype=I64),
                                             k_ref)))
        n_live += 1
        return k_ref
    mod.dn_o_shift = _rec
    try:
        rngw = np.random.default_rng(7)
        wf = LR.init_layer_weights(rngw, "linear_attention")
        qd = quant_layer(wf)["dn"]
        st = new_cache_fx("linear_attention")
        for _t in range(3):
            xn = np.round(rngw.normal(0, 1, LR.H) * (1 << RS_F)).astype(I64)
            deltanet_decode_fx(clip16(xn), qd, st)
    finally:
        mod.dn_o_shift = orig
    print(f"  DYNQ16 soak: {n_live} live DN head outputs + {len(cases)} "
          f"synthetic blocks, k in [{kmin},{kmax}], "
          f"{n_fix} fixup / {n_neg} left-shift / {n_zero} zero blocks, "
          f"min filled |y|max={ymin} (>=16384)  OK")
    return True


def _epsnorm_soak():
    """EPS-NORM (vecnorm gated mode) vs the float64 host immediate.

    Sweeps head outputs across 20 decades of magnitude — the eps floor is
    the whole reason this op exists, so the small-magnitude end (where
    dn_norm_scale is dominated by rms_norm_eps) is where the integer design
    has to hold.  Also checks the RTL envelope: p_in, ss/v widths, the
    output shift range and the 16-bit scale clamp.
    """
    rng = np.random.default_rng(99)
    n = LR.LDV
    # the exponent-shift identity the whole design rests on:
    # rsqrt_q(v, P) and rsqrt_q(v, P-2k) share r, and e differs by exactly k
    for _ in range(400):
        v = int(rng.integers(1, 1 << 42))
        k = int(rng.integers(-14, 18))
        P0 = 2 * S_F + 7
        r0, e0 = fp.rsqrt_q(v, P0)
        r1, e1 = fp.rsqrt_q(v, P0 - 2 * k)
        assert r0 == r1 and e0 == e1 + k, (v, k, e0, e1)
    worst_s, worst_o, worst_tag = 0.0, 0, None
    rows = []
    for dec in range(-10, 10):
        amp = 2.0 ** dec
        rel, dout, nclip = 0.0, 0, 0
        for _ in range(60):
            o = np.round(rng.normal(0, amp, n) * (1 << S_F)).astype(I64)
            o = np.clip(o, -(1 << 31), (1 << 31) - 1)
            o16, k = dynq16_fx(o)
            m_ref = dn_norm_scale(o, k, note=False)
            m_int = eps_norm_scale(o16, k, note=True)   # -> SEQ_STATS envelope
            nclip += int(m_ref >= M_Q15_MAX)
            if m_ref:
                rel = max(rel, abs(m_int - m_ref) / m_ref)
            t_ref = clip16(rshr(clip16(o16) * I64(m_ref), 15))
            t_int = eps_norm_fx(o16, k, note=False)
            dout = max(dout, int(np.abs(t_int - t_ref).max()))
            if rel > worst_s:
                worst_s, worst_tag = rel, (dec, k, m_ref, m_int)
            worst_o = max(worst_o, dout)
        rows.append((dec, rel, dout, nclip))
    print("  EPS-NORM soak (per magnitude decade: scale rel err, "
          "max |out| LSB delta, float-clip count)")
    for dec, rel, dout, nclip in rows:
        print(f"    2^{dec:<4d} scale_rel={rel:.2e}  out_dlsb={dout}"
              f"  m_ref_clipped={nclip}")
    print(f"  worst scale rel err {worst_s:.2e} at (decade,k,m_ref,m_int)="
          f"{worst_tag}; worst out delta {worst_o} LSB")
    # end-to-end gated norm INCLUDING the op-3 norm-weight multiply
    w = np.round(rng.normal(1.0, 0.1, n) * (1 << 14)).astype(I64)
    dy, ny = 0, 0
    for _ in range(200):
        amp = 2.0 ** int(rng.integers(-6, 6))
        o = np.clip(np.round(rng.normal(0, amp, n) * (1 << S_F)),
                    -(1 << 31), (1 << 31) - 1).astype(I64)
        o16, k = dynq16_fx(o)
        globals()["SEQ_NORM"] = False
        y0 = script_norm_fx(o, o16, k, w, note=False)
        globals()["SEQ_NORM"] = True
        y1 = script_norm_fx(o, o16, k, w, note=False)
        globals()["SEQ_NORM"] = False
        dy = max(dy, int(np.abs(y1 - y0).max()))
        ny += int(np.array_equal(y0, y1))
    print(f"  gated-norm output (script_norm_fx, incl. norm_w op-3): "
          f"{ny}/200 heads bit-identical, max |delta| {dy} LSB")
    assert dy <= 4, dy
    # zero block -> zeros for any k
    assert not eps_norm_fx(np.zeros(n, dtype=I64), 0, note=False).any()
    for kz in (-14, 0, 17):
        assert not eps_norm_fx(np.zeros(n, dtype=I64), kz, note=False).any()
    # the 16-bit scale clamp is INERT on every non-zero block: DYNQ16 floors
    # |x|max at 16384, and the tightest such block (one element at the floor,
    # eps addend 0) is the global maximum of the scale
    tight = np.zeros(n, dtype=I64)
    tight[0] = 16384
    smax_nz = max(eps_norm_scale(tight, kt, note=False)
                  for kt in range(-14, 18))
    assert smax_nz == 46341 and smax_nz < M_Q15_MAX, smax_nz
    print(f"  scale ceiling on any NON-ZERO block: {smax_nz} < "
          f"{M_Q15_MAX} -> the cfg_p0/16-bit clamp is inert there")
    # RTL envelope (measured over the sweep above)
    s = SEQ_STATS
    vbits = int(max(1, np.ceil(np.log2(max(s["v_max"], 1) + 1))))
    print(f"  RTL envelope over {s['n']} vectors: p_in={s['p_min']}"
          f"..{s['p_max']} (6b port), k in [{s['k_min']},{s['k_max']}], "
          f"v_max={s['v_max']} (<2^{vbits}, 48b port), out shift "
          f"{s['sh_min']}..{s['sh_max']}, scale_max={s['scale_max']} "
          f"(clamped {s['clip']}x at {M_Q15_MAX})")
    print(f"  eps addend E(k): k=-14 -> {eps_ss_addend(-14)}, k=-4 -> "
          f"{eps_ss_addend(-4)}, k=0 -> {eps_ss_addend(0)}, k=4 -> "
          f"{eps_ss_addend(4)}, k=8 -> {eps_ss_addend(8)} "
          f"(EPS_M={EPS_M} at 2^-{EPS_Q})")
    assert s["p_min"] == s["p_max"] == 2 * S_F + 7   # k is NOT in rs_p
    assert s["v_max"] < (1 << 48) and vbits <= 43
    assert worst_s < 1e-3, worst_s
    assert worst_o <= 2, worst_o
    bf_reset()
    return True


def _qeq(a, b):
    """Two W4 images are the SAME image (wire format included)."""
    return (np.array_equal(a["w4"], b["w4"]) and a["w4"].dtype == b["w4"].dtype
            and np.array_equal(a["m"], b["m"]) and a["m"].dtype == b["m"].dtype
            and a["e"] == b["e"] and a["sh"] == b["sh"] and a["g"] == b["g"]
            and sorted(a) == sorted(b))


def _salience_invariance():
    """Track Q V3 regression guard — the frozen flows must not move.

    Three properties, in the order they matter:
      1. `salience=None` is bit-identical to the argument being ABSENT, and
         `salience=ones(K)` is bit-identical to both.  Every frozen artifact
         goes through this quantizer, so if uniform weighting were not an
         exact no-op the whole 0.8B image set would silently move.
      2. With the FABLE5_CALIB_STATS plumb OFF (the default), every salience
         lookup returns None — i.e. an unset env var cannot be picked up
         accidentally by any flow, including quant_layer.
      3. With the plumb ON, a NON-uniform salience does change the chosen
         group scales (the knob bites) while leaving the wire format —
         shapes, dtypes, e, sh, g — untouched.
    """
    global CALIB_STATS, _CALIB_CACHE
    ok = True
    rng = np.random.default_rng(1234)

    # --- 1. the no-op cases ------------------------------------------------
    for (N, K) in ((64, 256), (37, 1024)):
        Wf = rng.normal(0, 0.02, (N, K)).astype(np.float32)
        for g in (G, 64):
            absent = quant_linear(Wf, g=g)
            none = quant_linear(Wf, g=g, salience=None)
            ones = quant_linear(Wf, g=g, salience=np.ones(K, dtype=np.float32))
            direct = quant_linear_mse(Wf, g=g,
                                      salience=np.ones(K, dtype=np.float64))
            ok &= _qeq(absent, none) and _qeq(absent, ones) and _qeq(absent, direct)
    print(f"  salience: None == arg-absent == ones(K) "
          f"(bit-identical, g={G} and 64) {'OK' if ok else 'FAIL'}")

    # bad salience is rejected rather than silently reshaped/ignored
    Wf = rng.normal(0, 0.02, (8, 256)).astype(np.float32)
    for bad in (np.ones(255), np.zeros(256), np.full(256, np.nan),
                -np.ones(256)):
        try:
            quant_linear(Wf, salience=bad)
        except ValueError:
            pass
        else:
            print("  salience: BAD input accepted — FAIL")
            ok = False
    try:                       # the max rule has no scale search to weight
        quant_linear(Wf, mse_scale=False, salience=np.ones(256))
    except SystemExit:
        pass
    else:
        print("  salience: max-rule quantizer accepted salience — FAIL")
        ok = False

    # --- 2. the env plumb is OFF by default --------------------------------
    off = (CALIB_STATS == "")
    if off:
        for probe in (("attn", "q_proj", 0), ("dn", "in_qkv", 3),
                      ("mlp", "down", 11), ("mlp", "gate", None)):
            ok &= (_salience_for(*probe) is None)
        ok &= (calib_salience("lm_head") is None)
    else:                      # someone exported it into this shell
        print(f"  salience: FABLE5_CALIB_STATS={CALIB_STATS!r} is SET in this "
              "environment — the default-off property cannot be checked here")
        ok = False
    print(f"  salience: FABLE5_CALIB_STATS unset -> every lookup is None "
          f"(quant_layer inert) {'OK' if off and ok else 'FAIL'}")

    # --- 3. the plumb ON changes scales but not the wire format ------------
    import tempfile
    import calib_stats as CS
    lt = "linear_attention"
    wf = LR.init_layer_weights(rng, lt)
    base = quant_layer(wf, g=64)
    sal = {}
    for sub, wsrc in (("dn", wf["dn"]), ("mlp", wf["mlp"])):
        for wk in CS.SUFFIX[sub]:
            K = np.asarray(wsrc[wk]).shape[1]
            sal[CS.tensor_key(sub, wk, 0)] = \
                rng.lognormal(0.0, 1.5, K).astype(np.float32)
    saved_path, saved_cache = CALIB_STATS, _CALIB_CACHE
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "sal.npz")
        CS.save(p, sal, {"model_tag": "_selftest"})
        CALIB_STATS = p
        _CALIB_CACHE = None
        try:
            wtd = quant_layer(wf, g=64, layer_idx=0)
            # missing layer_idx must fail LOUDLY, never fall back to plain MSE
            try:
                quant_layer(wf, g=64)
            except SystemExit:
                pass
            else:
                print("  salience: plumb ON accepted a missing layer_idx — FAIL")
                ok = False
            # a key this npz does not carry is an error, not a silent None
            try:
                calib_salience("layers.99.mlp.gate_proj")
            except SystemExit:
                pass
            else:
                print("  salience: missing key silently ignored — FAIL")
                ok = False
        finally:
            CALIB_STATS = saved_path
            _CALIB_CACHE = saved_cache
    moved = n_e = 0
    for sub in ("dn", "mlp"):
        for wk in CS.SUFFIX[sub]:
            a, b = base[sub][wk], wtd[sub][wk]
            # WIRE FORMAT = shapes, dtypes, the group size and the requant
            # shift.  `e` is DATA (the shared exponent, ceil(log2 max scale));
            # a different scale choice may legitimately move it by a step and
            # the DDR image is still the same format, so it is reported, not
            # asserted.
            same_format = (a["w4"].shape == b["w4"].shape
                           and a["w4"].dtype == b["w4"].dtype
                           and a["m"].shape == b["m"].shape
                           and a["m"].dtype == b["m"].dtype
                           and sorted(a) == sorted(b)
                           and a["sh"] == b["sh"]
                           and a["g"] == b["g"] == 64)
            n_e += int(a["e"] != b["e"])
            if not same_format:
                print(f"  salience: {sub}.{wk} WIRE FORMAT MOVED — FAIL")
                ok = False
            moved += int(not np.array_equal(a["m"], b["m"]))
    if moved == 0:
        print("  salience: non-uniform weighting changed nothing — FAIL")
        ok = False
    print(f"  salience: plumb ON re-scales {moved}/8 DeltaNet+MLP matrices "
          f"({n_e} shifted the shared exponent), wire format "
          f"(shape/dtype/sh/g/keys) unchanged {'OK' if ok else 'FAIL'}")
    return ok


def _w8eq(a, b):
    """Two W8 images are the SAME image (wire format included).

    The W4 twin is `_qeq`; the two are deliberately separate functions
    keyed on separate weight keys, so neither can be handed the other's
    dict and silently compare `None == None`.
    """
    return (np.array_equal(a["w8"], b["w8"]) and a["w8"].dtype == b["w8"].dtype
            and np.array_equal(a["m"], b["m"]) and a["m"].dtype == b["m"].dtype
            and a["e"] == b["e"] and a["sh"] == b["sh"] and a["g"] == b["g"]
            and sorted(a) == sorted(b))


def _w8_invariance():
    """V5 (W8 everywhere) — the 8-bit dicts, and the W4 flows they cannot move.

    Five properties, in the order a reviewer would doubt them:

      1. `quant_linear_w8` IS `w4a8_ref.quantize_weights8` in a dict — no
         second quantization rule exists anywhere in this file (the
         production-quantizer principle the W4 path already follows), and
         its `rowchunk` (the LM head's memory route) is bit-identical.
      2. `matvec_fx`/`matvec_to` dispatch a W8 dict to `matvec_y32_w8` and
         nothing else: same `dyn_quant_i8` activation, same `e_x`, same
         final shift.  Checked against a by-hand call, 4 seeds x 3 shapes
         x both group sizes.
      3. `quant_layer(w8=True)` puts a W8 image behind EVERY matvec of the
         layer and leaves every non-matvec tensor (norms, conv_w, the gate
         ports) bit-identical to the W4 layer's — W8 is a weight-format
         change, not a datapath change — and the layer still decodes.
      4. `w8=False` (the default) is bit-identical to the argument being
         ABSENT, at both group sizes.  Every frozen artifact flows through
         these functions.
      5. The calibration plumb (FABLE5_CALIB_STATS / salience / GPTQ /
         tighten_e) is REFUSED on the W8 path rather than silently ignored.
         V5 is plain W8 — the Track Q study ruled GPTQ-on-W8 out of scope
         — so a calibrated-looking W8 run must not be producible at all.
    """
    global CALIB_STATS, _CALIB_CACHE
    from w4a8_ref import quantize_weights8, matvec_y32_w8
    ok = True

    # --- 1 + 2. the quantizer and the matvec ------------------------------
    # NOTE each section prints its OWN verdict, not the running `ok`: a
    # cumulative flag makes every later line read FAIL and hides which
    # property actually broke.
    sec = True
    ratio = np.inf
    for seed in (1, 2, 3, 4):
        r = np.random.default_rng(seed)
        for (N, K) in ((64, 256), (37, 1024), (5, 128)):
            Wf = r.normal(0, 0.02, (N, K)).astype(np.float32)
            for g in (G, 64):
                q = quant_linear_w8(Wf, g=g)
                w8, m8, e8, sh8 = quantize_weights8(np.asarray(Wf), g=g)
                sec &= (np.array_equal(q["w8"], w8)
                        and q["w8"].dtype == np.int8
                        and np.array_equal(q["m"], m8)
                        and q["m"].dtype == np.uint16
                        and q["e"] == e8 and q["sh"] == sh8 and q["g"] == g
                        and sorted(q) == ["e", "g", "m", "sh", "w8"])
                # the head's row-chunked route is the same image
                sec &= _w8eq(q, quant_linear_w8(Wf, g=g, rowchunk=7))
                # --- the matvec dispatch ---
                x16 = np.round(r.normal(0, 1, K) * (1 << RS_F)).astype(I64)
                x8, e_x = fp.dyn_quant_i8(x16)
                y_ref = matvec_y32_w8(w8, m8, sh8, x8, g=g)
                y_fx, e_fx = matvec_fx(q, x16, RS_F)
                sec &= (int(e_fx) == int(e_x)
                        and np.array_equal(y_fx, y_ref))
                # matvec_to = that y32 with the ONE documented shift
                shift = (15 - q["e"] - q["sh"]) - e_x + RS_F - RS_F
                want = (rshr(np.asarray(y_ref, dtype=I64), shift) if shift >= 0
                        else np.asarray(y_ref, dtype=I64) << (-shift))
                sec &= np.array_equal(matvec_to(q, x16, RS_F, RS_F), want)
                # the W4 dict on the same call is still matvec_y32
                q4 = quant_linear(Wf, g=g)
                sec &= np.array_equal(
                    matvec_fx(q4, x16, RS_F)[0],
                    matvec_y32(q4["w4"], q4["m"], q4["sh"], x8, g=g))
                # V5's whole point: 8 bits reconstruct the matrix better
                NG = K // g
                W64 = np.asarray(Wf, dtype=np.float64)
                nrm = np.linalg.norm(W64)

                def _deq(qd):
                    w, _is8 = qw_codes(qd)
                    eff = qd["m"].astype(np.float64) * np.exp2(qd["e"] - 15)
                    return (w.reshape(N, NG, g).astype(np.float64)
                            * eff[:, :, None]).reshape(N, K)
                r8 = np.linalg.norm(_deq(q) - W64) / nrm
                r4 = np.linalg.norm(_deq(q4) - W64) / nrm
                ratio = min(ratio, r4 / max(r8, 1e-300))
    sec &= bool(ratio > 3.0)
    ok &= sec
    print(f"  w8: quant_linear_w8 == quantize_weights8 (rowchunk-identical), "
          f"matvec_fx -> matvec_y32_w8 bit-exact on 4 seeds x 3 shapes x "
          f"g{G}/g64; weight error beats the MSE W4 rule by >= {ratio:.1f}x "
          f"{'OK' if sec else 'FAIL'}")

    # --- 3. a whole layer in W8 ------------------------------------------
    rng = np.random.default_rng(4321)
    sec, nmv = True, 0
    for lt in ("linear_attention", "full_attention"):
        wf = LR.init_layer_weights(rng, lt)
        q4 = quant_layer(wf)
        q8 = quant_layer(wf, w8=True)
        sub4 = q4["attn"] if lt == "full_attention" else q4["dn"]
        sub8 = q8["attn"] if lt == "full_attention" else q8["dn"]
        for blk4, blk8 in ((sub4, sub8), (q4["mlp"], q8["mlp"])):
            for k, v in blk4.items():
                if isinstance(v, dict) and "w4" in v:
                    nmv += 1
                    if not ("w8" in blk8[k] and "w4" not in blk8[k]
                            and blk8[k]["w8"].shape == v["w4"].shape):
                        print(f"  w8: {lt}.{k} is not a W8 image — FAIL")
                        sec = False
                else:                       # non-matvec tensors must not move
                    same = (np.array_equal(np.asarray(v),
                                           np.asarray(blk8[k]))
                            if not isinstance(v, list) else v == blk8[k])
                    if not same:
                        print(f"  w8: non-matvec tensor {lt}.{k} moved — FAIL")
                        sec = False
        for k in ("ln1", "ln2"):
            sec &= bool(np.array_equal(q4[k], q8[k]))
        # and it still decodes (stability/saturation only, as the W4 soak)
        c = new_cache_fx(lt)
        xq = np.round(rng.normal(0, 1, LR.H) * (1 << RS_F)).astype(I64)
        for t in range(16):
            xq = layer_decode_fx(xq, q8, c, t)
        rms = float(np.sqrt(np.mean((xq / (1 << RS_F)) ** 2)))
        good = bool(np.isfinite(rms) and rms < 100 and c.get("sat", 0) == 0)
        sec &= good
        print(f"  w8: soak {lt:18s} 16 steps: rms={rms:.2f} "
              f"sat={c.get('sat', 0)} {'OK' if good else 'FAIL'}")
    sec &= (nmv == 15)          # dn(5)+mlp(3) then attn(4)+mlp(3)
    ok &= sec
    print(f"  w8: quant_layer(w8=True) -> a W8 image behind all {nmv}/15 "
          f"matvecs of both layer types, every non-matvec tensor "
          f"bit-identical to the W4 layer's {'OK' if sec else 'FAIL'}")

    # --- 4. w8=False is the argument being absent ------------------------
    sec = True
    wf = LR.init_layer_weights(np.random.default_rng(77), "linear_attention")
    for g in (G, 64):
        a, b = quant_layer(wf, g=g), quant_layer(wf, g=g, w8=False)
        for blk in ("dn", "mlp"):
            for k, v in a[blk].items():
                if isinstance(v, dict) and "w4" in v:
                    sec &= _qeq(v, b[blk][k])
    ok &= sec
    print(f"  w8: w8=False == the argument being absent (g{G} and g64, "
          f"bit-identical) {'OK' if sec else 'FAIL'}")

    # --- 5. the calibration plumb is refused, not ignored -----------------
    import tempfile
    import calib_stats as CS
    sec, refused = True, 0
    for kw in ({"tighten_e": True}, {"mse_scale": False}):
        try:
            quant_layer(wf, w8=True, **kw)
        except SystemExit:
            refused += 1
        else:
            print(f"  w8: quant_layer(w8=True, {kw}) was ACCEPTED — FAIL")
            sec = False
    sal = {}
    for wk in CS.SUFFIX["dn"]:
        sal[CS.tensor_key("dn", wk, 0)] = np.ones(
            np.asarray(wf["dn"][wk]).shape[1], dtype=np.float32)
    for wk in CS.SUFFIX["mlp"]:
        sal[CS.tensor_key("mlp", wk, 0)] = np.ones(
            np.asarray(wf["mlp"][wk]).shape[1], dtype=np.float32)
    saved_path, saved_cache = CALIB_STATS, _CALIB_CACHE
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "sal.npz")
        CS.save(p, sal, {"model_tag": "_selftest"})
        CALIB_STATS = p
        _CALIB_CACHE = None
        try:
            quant_layer(wf, w8=True, layer_idx=0)
        except SystemExit:
            refused += 1
        else:
            print("  w8: FABLE5_CALIB_STATS was silently ignored by a W8 "
                  "run — FAIL")
            sec = False
        finally:
            CALIB_STATS = saved_path
            _CALIB_CACHE = saved_cache
    sec &= (refused == 3)
    ok &= sec
    print(f"  w8: tighten_e / mse_scale=False / FABLE5_CALIB_STATS all "
          f"REFUSED on the W8 path ({refused}/3) {'OK' if sec else 'FAIL'}")
    return ok


def _gptq_invariance():
    """Track Q V4 regression guard — the same discipline as V3's.

    Four properties:
      1. `hess=None` is bit-identical to the argument being ABSENT (every
         frozen artifact flows through `quant_linear`).
      2. With FABLE5_CALIB_STATS unset, `calib_hess`/`_hess_for` are None and
         `_calib_for` is (None, None) — quant_layer cannot pick GPTQ up by
         accident, whatever FABLE5_CALIB_MODE says.
      3. With the plumb ON in mode=gptq, a DIAGONAL Hessian reproduces
         mode=h2 bit-identically — the property that makes "diagonal-Hessian
         GPTQ" a contradiction in terms (no off-diagonal, no feedback) and,
         end to end, the proof that the stored `h2/` vectors really are the
         stored Hessians' diagonals.
      4. With a CORRELATED Hessian the nibbles move while the wire format —
         shapes, dtypes, sh, g — AND the group scales (m, e) stay put.
    """
    global CALIB_STATS, CALIB_MODE, _CALIB_CACHE, _H2_CACHE, _HESS_STORE
    ok = True
    rng = np.random.default_rng(4321)

    # --- 1. the no-op case -------------------------------------------------
    for (N, K) in ((64, 256), (37, 1024)):
        Wf = rng.normal(0, 0.02, (N, K)).astype(np.float32)
        for g in (G, 64):
            ok &= _qeq(quant_linear(Wf, g=g), quant_linear(Wf, g=g, hess=None))
    print(f"  gptq: hess=None == arg-absent (bit-identical, g={G} and 64) "
          f"{'OK' if ok else 'FAIL'}")

    # --- 2. the env plumb is OFF by default --------------------------------
    off = (CALIB_STATS == "")
    if off:
        ok &= (calib_hess("lm_head") is None)
        for probe in (("mlp", "down", 3), ("dn", "in_qkv", 0)):
            ok &= (_hess_for(*probe) is None)
            ok &= (_calib_for(*probe) == (None, None))
    else:
        print(f"  gptq: FABLE5_CALIB_STATS={CALIB_STATS!r} is SET in this "
              "environment — the default-off property cannot be checked here")
        ok = False
    print(f"  gptq: FABLE5_CALIB_STATS unset -> no Hessian lookup "
          f"(quant_layer inert) {'OK' if off and ok else 'FAIL'}")

    # --- 3 + 4. the plumb ON ----------------------------------------------
    import tempfile
    import calib_stats as CS
    wf = LR.init_layer_weights(rng, "linear_attention")
    base = quant_layer(wf, g=64)
    sal, hess_diag, hess_full = {}, {}, {}
    for sub, wsrc in (("dn", wf["dn"]), ("mlp", wf["mlp"])):
        for wk in CS.SUFFIX[sub]:
            key = CS.tensor_key(sub, wk, 0)
            K = np.asarray(wsrc[wk]).shape[1]
            sal[key] = rng.lognormal(0.0, 1.5, K).astype(np.float32)
            site = CS.hess_key(key)
            if site in hess_diag:
                continue
            d = rng.lognormal(0.0, 1.0, K)
            hess_diag[site] = np.diag(d).astype(np.float32)
            A = rng.normal(0, 1, (K + 32, K)) * np.sqrt(d)[None, :]
            hess_full[site] = ((A.T @ A) / A.shape[0]).astype(np.float32)
    saved = (CALIB_STATS, CALIB_MODE, _CALIB_CACHE, _H2_CACHE, _HESS_STORE)
    with tempfile.TemporaryDirectory() as td:
        try:
            got = {}
            for tag, hs in (("diag", hess_diag), ("full", hess_full)):
                p = os.path.join(td, f"h_{tag}.npz")
                CS.save(p, sal, {"model_tag": "_selftest"}, hs)
                for mode in ("h2", "gptq"):
                    CALIB_STATS, CALIB_MODE = p, mode
                    _CALIB_CACHE = _H2_CACHE = _HESS_STORE = None
                    got[(tag, mode)] = quant_layer(wf, g=64, layer_idx=0)
                # a bad mode name must be loud, not a silent fall back to V3
                CALIB_MODE = "gptq!"
                try:
                    quant_layer(wf, g=64, layer_idx=0)
                except SystemExit:
                    pass
                else:
                    print("  gptq: a bogus FABLE5_CALIB_MODE was accepted — FAIL")
                    ok = False
        finally:
            (CALIB_STATS, CALIB_MODE, _CALIB_CACHE, _H2_CACHE,
             _HESS_STORE) = saved
    same = moved = n_scale = 0
    for sub in ("dn", "mlp"):
        for wk in CS.SUFFIX[sub]:
            d_h2, d_gp = got[("diag", "h2")], got[("diag", "gptq")]
            same += int(_qeq(d_h2[sub][wk], d_gp[sub][wk]))
            a, b = got[("full", "h2")][sub][wk], got[("full", "gptq")][sub][wk]
            fmt = (a["w4"].shape == b["w4"].shape
                   and a["w4"].dtype == b["w4"].dtype
                   and a["m"].shape == b["m"].shape
                   and a["m"].dtype == b["m"].dtype
                   and sorted(a) == sorted(b)
                   and a["sh"] == b["sh"] and a["g"] == b["g"] == 64
                   and base[sub][wk]["sh"] == a["sh"])
            if not fmt:
                print(f"  gptq: {sub}.{wk} WIRE FORMAT MOVED — FAIL")
                ok = False
            moved += int(not np.array_equal(a["w4"], b["w4"]))
            n_scale += int(not (np.array_equal(a["m"], b["m"])
                                and a["e"] == b["e"]))
    ok &= (same == 8 and moved == 8 and n_scale == 0)
    print(f"  gptq: DIAGONAL Hessian == mode=h2 on {same}/8 matrices "
          f"(bit-identical: no off-diagonal, no feedback) "
          f"{'OK' if same == 8 else 'FAIL'}")
    print(f"  gptq: correlated Hessian moves nibbles on {moved}/8 matrices, "
          f"{n_scale}/8 changed a group scale, wire format "
          f"(shape/dtype/sh/g/keys) unchanged "
          f"{'OK' if moved == 8 and n_scale == 0 else 'FAIL'}")
    return ok


def _dn_state_law():
    """G1: the DeltaNet state container law (`FABLE5_DN_STATE`).

    Four properties, each proved on a vector rather than asserted in prose,
    and each one of them is a thing the RTL mirror in Task 10 has to reproduce:

      (a) ROUNDS to nearest, it does not truncate.  Track P's experiment RTL
          truncated (`PLACE_EXP.md` §5.1); the law here rounds and `int8t:<k>`
          exists only so the rung can price that difference.  Proved on a
          vector whose truncated and rounded results differ.
      (b) SATURATES symmetrically at +/-127, it does not wrap.  Proved at
          S16 = +/-32767, i.e. the int16 rail, which is exactly the input the
          existing `s_sat` counter says the state reaches 4,392 times at 9B.
          -128 is deliberately NOT used: a symmetric rail keeps -x
          representable for every representable x (the same argument
          `w4a8_ref.quantize_weights8` makes for its own [-127,127]).
      (c) is EXACTLY `clip16` under `int16` — the default, so an unset env var
          is byte-identical to the shipped model, whose recurrence had that
          very `clip16` on the line this law replaced.  Every container
          saturates at its OWN rail and only there.
      (d) is IDEMPOTENT: narrowing an already-narrowed state changes nothing.
          This is the property that makes it legal to apply the law after
          EVERY state update rather than once per token.
    """
    ok = True
    rng = np.random.default_rng(9106)
    sweep = (5, 6, 7, 8, 9, 10)

    # (c) int16 == clip16 — checked through the public entry point with the
    # module law temporarily set, so this tests the dispatch too.
    saved = (DN_STATE_LAW, DN_STATE_K)
    try:
        S = np.round(rng.normal(0, 900, (16, 128))).astype(I64)
        S = np.clip(S, -32768, 32767)
        _dn_state_set("int16", 0)
        got = dn_state_narrow(S)
        wide = np.array([40000, -40000, 32767, -32768, 0], dtype=I64)
        c = bool(np.array_equal(got, S)
                 and np.array_equal(dn_state_narrow(wide),
                                    np.array([32767, -32768, 32767, -32768, 0],
                                             dtype=I64)))
        print(f"  dn_state int16 : identity in range on {S.size} elements, "
              f"and int16's OWN rail beyond it {'OK' if c else 'FAIL'}")
        ok &= c

        for k in sweep:
            _dn_state_set("int8", k)
            # (a) rounding, on the exact half-way vector: 2^(k-1) * odd
            half = np.array([(2 * i + 1) << (k - 1) for i in range(-8, 8)],
                            dtype=I64)
            r = dn_state_narrow(half)
            _dn_state_set("int8t", k)
            t = dn_state_narrow(half)
            a = bool((not np.array_equal(r, t))
                     and np.array_equal(r, rshr(half, k) << k)
                     and np.array_equal(t, (half >> k) << k))
            # (b) saturation, symmetric, at the CONTAINER's own rail — tested
            # at the int16 rail AND beyond it, because the law now sees the
            # unclipped accumulator and k > 8 puts the int8 ceiling outside
            # int16 (127 << 9 = 65024)
            _dn_state_set("int8", k)
            rail = np.array([32767, -32767, 1 << 20, -(1 << 20)], dtype=I64)
            sr = dn_state_narrow(rail)
            codes, _ = dn_state_pack(rail)
            want = np.array([min(127, int(rshr(I64(32767), k))),
                             -min(127, int(rshr(I64(32767), k))),
                             127, -127], dtype=I64)
            b = bool(np.array_equal(codes, want)
                     and np.array_equal(sr, want << k)
                     and int(codes.min()) >= -127 and int(codes.max()) <= 127)
            # (d) idempotence, on real-shaped random state
            once = dn_state_narrow(S)
            twice = dn_state_narrow(once)
            d = bool(np.array_equal(once, twice))
            # the container's own arithmetic, restated: ceiling and resolution
            ceil_ = 127.0 / (1 << (S_F - k))
            res_ = 1.0 / (1 << (S_F - k))
            print(f"  dn_state int8:{k} : round!=trunc {'OK' if a else 'FAIL'}"
                  f"  sat+/-127 {'OK' if b else 'FAIL'}"
                  f"  idempotent {'OK' if d else 'FAIL'}"
                  f"   [Q2.{S_F - k}: ceiling {ceil_:.4f}, resolution "
                  f"{res_:.4f}]")
            ok &= a and b and d

        # ---- L1, both granularities (user ruling 2026-08-30) ----
        # int8h groups the WHOLE head under one exponent, int8e groups each
        # 1024-bit URAM half-row.  Same mantissa, same rounding, same rail;
        # the only difference is how many values share an exponent, so the
        # two must agree exactly on a state whose rows all share a max.
        _dn_state_set("int8h", 0)
        flat = np.tile(np.arange(-64, 64, dtype=I64) * 97, (16, 1))
        ch, eh = dn_state_pack(flat)
        _dn_state_set("int8e", 0)
        cr, er = dn_state_pack(flat)
        g = bool(np.array_equal(ch, cr) and int(eh[0]) == int(er[0])
                 and eh.shape == (1,) and er.shape == (16,))
        # and they must DIFFER when one row is much louder than the others:
        # per-head drags every quiet row down to the loud row's exponent,
        # which is exactly the resolution per-row buys.
        mixed = flat.copy()
        mixed[0] = flat[0] << 6
        _dn_state_set("int8h", 0)
        chm, ehm = dn_state_pack(mixed)
        _dn_state_set("int8e", 0)
        crm, erm = dn_state_pack(mixed)
        # the quiet rows keep their own exponent under int8e and are dragged
        # to the loud row's under int8h; the cost is DISTINCT CODES, which is
        # resolution, which is the whole question the granularity axis asks
        nq_h = len(np.unique(chm[1]))
        nq_r = len(np.unique(crm[1]))
        g &= bool(int(ehm[0]) == int(eh[0]) + 6
                  and int(erm[0]) == int(er[0]) + 6
                  and np.array_equal(erm[1:], er[1:])
                  and np.array_equal(crm[1], cr[1])
                  and nq_h * 8 < nq_r)
        print(f"  dn_state gran  : int8h == int8e on a uniform state; a 2^6 "
              f"loud row leaves a quiet row {nq_r} distinct codes under "
              f"int8e but only {nq_h} under int8h {'OK' if g else 'FAIL'}")
        ok &= g

        # the F5 counters must be able to FIRE, at both granularities
        for law in ("int8h", "int8e"):
            _dn_state_set(law, 0)
            bf_reset()
            dn_state_pack(np.full((1, 4), 32700, dtype=I64))
            fired = DN_STATS["sat8"] > 0 and DN_STATS["e_fixup"] > 0
            bf_reset()
            dn_state_pack(np.full((1, 4), 32639, dtype=I64))
            quiet = DN_STATS["sat8"] == 0 and DN_STATS["e_fixup"] == 0
            print(f"  dn_state {law:6s}: rail counters fire at |S|max 32700 "
                  f"and stay silent at 32639 "
                  f"{'OK' if fired and quiet else 'FAIL'}")
            ok &= fired and quiet
        bf_reset()

        # L1 (int8e), implemented so the grammar is complete.  MEASURING it is
        # a STOP-back item (spec 4.1(f) case 2) — this only proves the law.
        _dn_state_set("int8e", 0)
        once = dn_state_narrow(S)
        twice = dn_state_narrow(once)
        codes, ex = dn_state_pack(S)
        e = bool(np.array_equal(once, twice)
                 and int(np.abs(codes).max()) <= 127
                 and ex.shape == (S.shape[0],))
        # per-row exponent means each row carries its OWN scale.  Two halves:
        #  * a row scaled up by an exact 2^3 gets exponent+3 and BIT-IDENTICAL
        #    mantissas — the exponent absorbed the rescale, which is the whole
        #    claim of L1;
        #  * a quiet row (max < 128) keeps exponent 0, i.e. full resolution,
        #    which is what L1 buys over L0's one shared k.
        Sbig = S.copy()
        Sbig[0] = S[0] << 3
        Sbig[1] = np.clip(S[1] >> 8, -120, 120)
        c1, e1 = dn_state_pack(Sbig)
        e &= bool(int(e1[0]) == int(ex[0]) + 3
                  and np.array_equal(c1[0], codes[0])
                  and int(e1[1]) == 0
                  and np.array_equal(c1[1], Sbig[1]))
        print(f"  dn_state int8e : idempotent + a 2^3 row rescale moves only "
              f"the exponent + a quiet row keeps e=0 {'OK' if e else 'FAIL'}")
        ok &= e
    finally:
        _dn_state_set(*saved)
    return ok


def _selftest():
    rng = np.random.default_rng(21)
    ok = True

    # ---- G1: the DeltaNet state container law ----
    ok &= _dn_state_law()

    # ---- sequencer rung-1 op specs (docs/SEQ_ISA.md) ----
    ok &= _dynq16_soak()
    ok &= _epsnorm_soak()

    # ---- Track Q V3: the salience arg is INERT unless it is used ----
    ok &= _salience_invariance()

    # ---- Track Q V4: the hess arg is INERT unless it is used ----
    ok &= _gptq_invariance()

    # rmsnorm (1+w)
    x = rng.normal(0, 2, LR.H).astype(np.float64)
    w = rng.normal(0, 0.1, LR.H)
    x16 = np.round(x * (1 << RS_F)).astype(I64)
    wq = np.round(w * (1 << 14)).astype(I64)
    got = rmsnorm_fx(x16, wq, RS_F, True) / (1 << RS_F)
    ok &= _blk("rmsnorm1p", got, LR.rmsnorm1p(x, w), 2e-2)

    # rope
    cq, sq = rope_tables_q15(37)
    cf, sf = LR.rope_cos_sin(37)
    h = rng.normal(0, 1, LR.HD)
    h16 = np.round(h * (1 << QKV_F)).astype(I64)
    ok &= _blk("rope", rope_fx(h16, cq, sq) / (1 << QKV_F),
               LR.apply_rope(h.astype(np.float32), cf, sf), 1e-2)

    # l2norm
    v = rng.normal(0, 1.5, LR.LDK)
    v16 = np.round(v * (1 << QKV_F)).astype(I64)
    ok &= _blk("l2norm", l2norm_fx(v16, QKV_F, NRM_F) / (1 << NRM_F),
               LR.l2norm(v), 1e-2)

    # attention core: identical KV content, T=48
    T, HD = 48, LR.HD
    q = rng.normal(0, 1, HD); ks = rng.normal(0, 1, (T, HD)); vs = rng.normal(0, 1.2, (T, HD))
    # float
    sc = (ks @ q) / np.sqrt(HD); e = np.exp(sc - sc.max()); pf = e / e.sum()
    ref = pf @ vs
    # fixed (mirrors attn_decode_fx inner loop)
    qn = np.round(q * (1 << QKV_F)).astype(I64)
    sc_q = np.zeros(T, dtype=I64)
    kcache = [kv_quant(np.round(ks[t] * (1 << QKV_F)).astype(I64), QKV_F) for t in range(T)]
    vcache = [kv_quant(np.round(vs[t] * (1 << QKV_F)).astype(I64), QKV_F) for t in range(T)]
    SC = int(round((1 << 15) / np.sqrt(HD)))
    for t in range(T):
        k8, ke = kcache[t]
        dot = int((qn * k8.astype(I64)).sum())
        sq_ = rshr(I64(dot) * SC, 15)
        f = QKV_F - ke - 16
        sc_q[t] = rshr(I64(int(sq_)), f) if f >= 0 else int(sq_) << (-f)
    mx = int(sc_q.max())
    es = np.array([fp.exp_neg_q(int(min(int(sc_q[t]) - mx, 0))) for t in range(T)], dtype=I64)
    r, re = fp.recip_q(int(es.sum()), 30)
    pq = np.clip(rshr(es * r, 30 - re + 15), 0, 1 << 15)
    acc = np.zeros(HD, dtype=I64)
    for t in range(T):
        v8, ve = vcache[t]
        term = I64(int(pq[t])) * v8.astype(I64)
        sh = 15 - ve - QKV_F
        acc += rshr(term, sh) if sh >= 0 else term << (-sh)
    # Bound 8e-2, DERIVED — G2/D-TOL ruling, evidence/qwen9b/g2/D_TOL.md.
    # Unlike the three checks above, this one is not a resolution check: it is
    # the max of HD accumulated-rounding errors OVER the max of HD softmax
    # outputs, and that ratio is a random variable with a ~20% coefficient of
    # variation.  Measured over 43,000 draws of this exact block (T=48,
    # HD=256): mean 3.30e-2, sd 6.7e-3, max 6.75e-2.  The old 3e-2 sat INSIDE
    # that distribution and false-failed 66% of the time; 0.8B's 2.666e-2 was
    # one lucky draw and 2B's 3.288e-2 is the SAME computation on a different
    # one — T and HD do not move with the geometry, only the shared rng's
    # stream position does, because rmsnorm1p above draws 2*LR.H normals.
    # Law:  rel ~= 2^-QKV_F * sqrt(T/12) / (sigma_v * sqrt(sum_t p_t^2)),
    # measured/predicted = 1.015 +- 0.169.  The numerator is the per-term
    # round into Q.QKV_F that rtl/attn_core.sv:213-224 performs because each
    # token's V carries its own power-of-two exponent; the two max-of-HD order
    # statistics cancel, so the bound scales with T and QKV_F and NOT with H,
    # HD, NQ/NKV or LNH/LNKH.  8e-2 is 2.4x the mean and 1.19x the largest of
    # those 43,000 draws: it admits the block's own noise at every geometry
    # this campaign uses, and still refuses truncation-instead-of-rounding
    # (99.5%) and every structural defect measured (100%).  It does NOT catch
    # a 1-bit accumulator narrowing (7.5%); D_TOL.md names what does.
    ok &= _blk("attn softmax+pv", acc / (1 << QKV_F), ref, 8e-2)

    # deltanet recurrence single step from identical NONZERO state
    LDK, LDV = LR.LDK, LR.LDV
    Sf = rng.normal(0, 0.01, (LDK, LDV)).astype(np.float32)
    qv = LR.l2norm(rng.normal(0, 1, LDK)) / np.sqrt(LDK)
    kv_ = LR.l2norm(rng.normal(0, 1, LDK))
    vv = rng.normal(0, 0.8, LDV).astype(np.float32)
    dec, bet = 0.21, 0.83
    Sf2 = Sf * dec
    kvm = Sf2.T @ kv_
    dlt = (vv - kvm) * bet
    Sf2 = Sf2 + np.outer(kv_, dlt)
    of = Sf2.T @ qv
    # fixed
    Sq = np.round(Sf * (1 << S_F)).astype(I64)
    qn16 = np.round(qv * (1 << NRM_F)).astype(I64)
    kn16 = np.round(kv_ * (1 << NRM_F)).astype(I64)
    v16_ = np.round(vv * (1 << S_F)).astype(I64)
    dq, bq = int(round(dec * (1 << GAT_F))), int(round(bet * (1 << GAT_F)))
    Sh = rshr(Sq * dq, GAT_F)
    kvm_q = rshr((Sh * kn16[:, None]).sum(axis=0), NRM_F)
    dlt_q = rshr((v16_ - kvm_q) * bq, GAT_F)
    Sh = Sh + rshr(kn16[:, None] * dlt_q[None, :], NRM_F)
    oq = rshr((Sh * qn16[:, None]).sum(axis=0), NRM_F)
    # bound = S_F=13 resolution at random-weight state rms ~0.01 (82 LSB);
    # o = 128-dim contraction -> ~3% inherent. Revisit w/ real weights (S5).
    ok &= _blk("deltanet step out", oq / (1 << S_F), of, 5e-2)
    ok &= _blk("deltanet step S", Sh / (1 << S_F), Sf2, 2e-2)

    # trajectory soak: only stability/saturation checked (not pointwise err).
    # Run at BOTH wire group sizes: g=128 is the default/legacy path, g=64 is
    # the v2 row format (same math, finer groups) — this proves the group size
    # is plumbed through quant_layer -> quant_* -> matvec_fx end to end.
    for lt in ["linear_attention", "full_attention"]:
        wf = LR.init_layer_weights(rng, lt)
        for g in (G, 64):
            qw = quant_layer(wf, g=g)
            sub = qw["attn"] if lt == "full_attention" else qw["dn"]
            key = "q_proj" if lt == "full_attention" else "in_qkv"
            assert sub[key]["g"] == g and qw["mlp"]["down"]["g"] == g
            assert sub[key]["m"].shape[1] == sub[key]["w4"].shape[1] // g
            cq2 = new_cache_fx(lt)
            xq = np.round(rng.normal(0, 1, LR.H) * (1 << RS_F)).astype(I64)
            for t in range(32):
                xq = layer_decode_fx(xq, qw, cq2, t)
            rms = float(np.sqrt(np.mean((xq / (1 << RS_F)) ** 2)))
            sat = cq2.get("sat", 0)
            good = bool(np.isfinite(rms) and rms < 100 and sat == 0)
            print(f"  soak {lt:18s} g={g:<4d} 32 steps: rms={rms:.2f} "
                  f"sat={sat} {'OK' if good else 'FAIL'}")
            ok &= good

    # ---- V5: the W8 weight format (APPENDED on purpose — everything the
    # W4 sections print above is a byte-identical prefix of this log) ----
    ok &= _w8_invariance()

    if ok:
        print("LAYER_FIXED SELFTEST PASS")
    else:
        raise SystemExit("LAYER_FIXED SELFTEST FAIL")


if __name__ == "__main__":
    _selftest()
