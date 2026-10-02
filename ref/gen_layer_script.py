#!/usr/bin/env python3
"""gen_layer_script.py <outfile> <seed> [ntok]

Emit a layer_chan command script that replays one DeltaNet layer and one
full-attention layer (ntok tokens each, random weights/inputs) and checks
every intermediate against the frozen spec (ref/layer_fixed.py).

The generator maintains a scratchpad MODEL updated by the exact semantics
of each command (mirroring rtl/layer_chan.sv) and SELF-CHECKS the final
residual of every token against an independent layer_decode_fx run, so a
flawed command mapping aborts here and never reaches simulation.

Matvec round-trips are host-side (stage-2 verified engines): the script
asserts the on-chip x8/EOUT first (R/E records), then injects the raw y32
accumulators computed from those asserted values (W32 records).

Script records (hex fields):
  W <addr> <n>   + n hex16 lines     host scratch write
  C <op> <a0> <a1> <a2>              command, wait for completion
  R <addr> <n>   + n hex16 lines     read scratch, compare
  E <e>                              compare EOUT CSR
  T <val>                            write BOTH TCNT CSRs (current kv_slot:
                                     all _KVH = 4 append counters)
  L <hex32>                          write LAYER CSR = {kv_slot<<8, dn_slot}
                                     selects the banked layer state below
  V <wid> <x8a> <nin> <nrows> + nrows hex32   matvec point: hw runs weight
        image wid on x8 at x8a and must match these y32 (sim TB skips)
"""
import hashlib
import json
import os
import sys

# sw/hwmap.py is the device map — the DDR state region's plan comes from it
# (S3), and it is READ-ONLY here.  Same insert ref/seq_format.py makes, so
# this generator resolves it when it is run standalone from ref/.
_SW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sw")
if _SW not in sys.path:
    sys.path.insert(0, _SW)
import numpy as np

import fixedpoint as fp
import layer_ref as LR
import layer_fixed as LF
import model_select as MS
from w4a8_ref import (matvec_y32, matvec_y32_w8, pack_ddr_rows,
                      pack_ddr_rows8, rshift_round as rshr)

I64 = np.int64
RS_F, QKV_F, NRM_F, S_F, GAT_F, CW_F = (LF.RS_F, LF.QKV_F, LF.NRM_F,
                                        LF.S_F, LF.GAT_F, LF.CW_F)

# The geometries whose EMITTED ARTIFACTS are frozen: their bitstreams are
# built and their manifest/stream bytes are pinned
# (`evidence/qwen9b/g2/FINAL_BYTELOCK.md`, G2b).
#
# G3.1 SPENT THAT BYTE-LOCK.  SEQ_ISA v2.0 re-encodes every layer ARG word,
# so this generator no longer reproduces the frozen bytes and
# `evidence/qwen2b/rc/t4_bytes_unmoved.sh` is RETIRED BY DESIGN — it asserts
# the opposite of what this tree now does.  FINAL_BYTELOCK.md stays as the
# RECORD of what the 0.8B/2B artifacts contain, and those geometries are
# served by their frozen `build_034`/`build_035` bitstreams from a pre-G3
# checkout.  `ref/scripts/regen_gate.sh` is in the same position.
#
# The list itself still does its OTHER job, which G3.1 did not change: a
# generator may add a manifest key ONLY for a tag outside this set (spec
# A2.5's `rs_f` gating turns on exactly this).  This is the one place it
# lives.
BYTELOCKED_TAGS = ("0.8b", "2b")

# The value a manifest with NO `rs_f` key means to a reader.  It is the twin
# of `sw/hwmap.RS_F_DEFAULT` and the two MUST agree: withholding the key is
# only valid when the emitted value IS this number, which is what
# `Mach.dump_weights` asserts.  `ref/` does not import `sw/`, so the
# agreement is checked by `evidence/qwen9b/g2/isa_guards_check.py`.
RS_F_MANIFEST_DEFAULT = 8

# ----------------------------------------------------------------------
# SCRATCH REGION MAP — everything derives from the layer_ref geometry
# ----------------------------------------------------------------------
# The map used to be a set of hand-placed literals valid only for
# Qwen3.5-0.8B (H=1024, FFN=3584).  It is now expressed as functions of the
# FABLE5_MODEL-selected geometry so the SAME expressions serve 2B
# (H=2048, FFN=6144) and 9B (H=4096, FFN=12288, LNH=32).
#
# LEGACY LOCK: at the 0.8B geometry every constant below MUST evaluate to
# the frozen literal it replaced.  _LEGACY_MAP asserts exactly that at
# import time, so a bad refactor fails loudly before the regen gate runs.
# See docs/QWEN2B_SCRATCH_MAP.md for the derived 2B map and the
# collision-freedom argument.
H, FFN = LR.H, LR.FFN
CHUNK = 2048                     # host W32 injection chunk (int32 words)
STGCH = 2 * min(CHUNK, H)        # scratch words one y32 chunk of an H-row
                                 # matvec occupies (lo/hi int16 pairs)

X0 = 0                           # residual stream        H words
XN = H                           # RMSNorm output         H words
X8 = 2 * H                       # DYNQ8 int8 activation  H words
SCA = 3 * H                      # DeltaNet scalar tiles  SCA_SZ words

# ----------------------------------------------------------------------
# The SCA tile map is THE LAYOUT AUTHORITY (G2a).
#
# The nine DeltaNet scalar tiles used to sit on hand-placed 32-word strides
# with SCA_SZ frozen at 992.  Three of them are sized by the VALUE head
# count: B16 is LNH words, A16 and GD are 2*LNH each.  At LNH=16 each fits
# its 32-word slot exactly; at LNH=32 (4B/9B) A16 and GD need 64 and the
# tiles COLLIDE — silently, because nothing checked.
#
# The parameterized form below is NOT this campaign's invention: it is the
# `fix_sca` branch of `evidence/qwen_next/feas/scratch_peak.py:49-60`, the
# allocator the feasibility study's 9B scratch peak was computed with, and
# the offsets must reproduce it exactly.  Evaluated at LNH=16 it returns the
# as-built 0/32/64/96/224/352/480/736/864 with SCA_SZ = 992 — which is what
# _LEGACY_MAP below asserts and what the byte-lock proves.  At LNH=32 it
# returns 0/32/96/160/288/416/544/800/928 with SCA_SZ = 1056.
#
# STG MOVES WITH IT.  `STG = SCA + 1024` was a literal that happened to
# exceed SCA_SZ 992; at 1056 it would park the staging window on top of NH.
# The authority already models the fix — `STG = SCA + max(1024, SCA_SZ)` —
# and the study's 50,208-word 9B peak was computed with that expression, so
# using anything else would put this emitter and the derived peak out of
# step.  max(1024, 992) == 1024 is the as-built literal, so it is inert.
# ----------------------------------------------------------------------
_SCA_TILES = (                   # (name, size in words), in layout order
    ("B16",  max(32, LR.LNH)),       # beta logits        LNH
    ("A16",  max(32, 2 * LR.LNH)),   # A logits (int32)   2*LNH
    ("GD",   max(32, 2 * LR.LNH)),   # beta|decay gates   2*LNH
    ("QN",   LR.LDK),                # l2(q)              LDK
    ("QNS",  LR.LDK),                # l2(q) * 1/sqrt(dk) LDK
    ("KN",   LR.LDK),                # l2(k)              LDK
    ("DO32", 2 * LR.LDV),            # DNST out (int32)   2*LDV
    ("OH",   LR.LDV),                # block-floated out  LDV
    ("NH",   LR.LDV),                # gated-RMSNorm out  LDV
)
SCA_TILE = {}                    # name -> absolute base word
_o = 0
for _n, _sz in _SCA_TILES:
    SCA_TILE[_n] = SCA + _o
    _o += _sz
SCA_SZ = _o
del _n, _sz, _o

B16 = SCA_TILE["B16"]
A16 = SCA_TILE["A16"]
GD = SCA_TILE["GD"]
QN = SCA_TILE["QN"]
QNS = SCA_TILE["QNS"]
KN = SCA_TILE["KN"]
DO32 = SCA_TILE["DO32"]
OH = SCA_TILE["OH"]
NH = SCA_TILE["NH"]
ZG = QN                          # silu(z), reuses QN (q path already done)

# The GATE command writes beta|decay into GD as TWO LNH-word halves, and the
# DNST command's scalar pointers index them: beta at `beta_base + h`, decay
# at `decay_base + h`.  Export both so the emitter has ONE definition of
# where a decay word lives instead of a `GD + 16 + h` literal — the wall-17
# defect this map exists to close.
beta_base = GD                   # GATE writes beta   at beta_base  + h
decay_base = GD + LR.LNH         # GATE writes decay  at decay_base + h

# LAYOUT-AUTHORITY ASSERT.  Every tile's USED extent must fit inside the SLOT
# the map gave it — i.e. must not reach the next tile's base.
#
# G2a review N2: the first cut of this asserted `decay_base + LNH <= QN` and
# `A16 + 2*LNH <= GD`, both of which are TAUTOLOGIES.  `GD` is defined as
# `A16 + max(32, 2*LNH)` and `QN` as `GD + max(32, 2*LNH)`, so the second
# operand is the first plus a non-negative slack BY CONSTRUCTION and the
# assert cannot fail for any LNH.  It read like a guard and checked nothing —
# which is exactly the shape of the defect it was written to prevent.
#
# The real check compares each tile's USED size (what the emitter writes into
# it) against its SLOT size (what the map reserved), pairwise down the map.
#
# WHAT IT ACTUALLY GUARDS, stated precisely because the first cut of this
# comment overclaimed it as a geometry guard.  Sweeping the declared law over
# LNH 1..64 x LDK 1..256 x LDV 1..256 -- 4,194,304 combinations -- gives
# **ZERO violations**: with the size column as written, no GEOMETRY can make a
# slot too small, because every slot is `max(floor, use)` of its own use.
# So this is a TABLE-CONSISTENCY guard: it fires when the size column and the
# use column below DESYNC, which is what a hand edit to `_SCA_TILES` does.
# That is still worth having -- the wall-17 defect was born of exactly such a
# hand-placed table -- but it is not a check on the geometry, and calling it
# one would be the same overclaim N2 was raised about.
_SCA_ENDS = [SCA_TILE[n] + used for (n, used) in
             (("B16", LR.LNH), ("A16", 2 * LR.LNH), ("GD", 2 * LR.LNH),
              ("QN", LR.LDK), ("QNS", LR.LDK), ("KN", LR.LDK),
              ("DO32", 2 * LR.LDV), ("OH", LR.LDV), ("NH", LR.LDV))]
_SCA_BASES = [SCA_TILE[n] for (n, _sz) in _SCA_TILES[1:]] + [SCA + SCA_SZ]
for _i, (_end, _next) in enumerate(zip(_SCA_ENDS, _SCA_BASES)):
    assert _end <= _next, (
        f"SCA tile {_SCA_TILES[_i][0]} uses words up to {_end - SCA} but the "
        f"next tile starts at {_next - SCA} (LNH={LR.LNH}, LDK={LR.LDK}, "
        f"LDV={LR.LDV}) — the SCA map is not the layout authority")
del _i, _end, _next
# and the property the DNST pointer actually depends on, stated separately
assert decay_base == beta_base + LR.LNH, "beta|decay are not adjacent halves"

STG = SCA + max(1024, SCA_SZ)    # staging window base (authority: see above)
STG_SZ = LR.LVD + STGCH          # staging window size
BIG = STG + STG_SZ               # per-body big tiles (DN / ATTN / MLP)

# ---- per-body tiles.  SINGLE SOURCE OF TRUTH: the emitting bodies alias
# these names, scratch_map() reports them and PEAK_* is computed from them,
# so the layout algebra exists exactly ONCE.  _MAP_PEAK_OK below asserts
# that the three views still agree.
NQH, KVH = LR.NQ * LR.HD, LR.NKV * LR.HD

DN_QKV = BIG                     # conv q|k|v, 16-bit          CONV_DIM
DN_Z16 = DN_QKV + LR.CONV_DIM    # z branch                    LVD
DN_ON = XN                       # gated outputs, overlays XN  LVD
DN_OUTSTG = STG + LR.LVD         # out-proj y32 stage          STGCH
DN_OUTDST = BIG                  # residual delta, overlays dead QKV     H

AT_QG = BIG                      # q_proj out = q | gate       2*NQH
AT_K16 = AT_QG + 2 * NQH         # k_proj out                  KVH
AT_V16 = AT_K16 + KVH            # v_proj out                  KVH
AT_QR = AT_V16 + KVH             # roped q                     NQH
AT_KR = AT_QR + NQH              # roped k                     KVH
AT_AO32 = STG                    # ATTN out (int32)            2*HD
AT_OG = AT_AO32 + 2 * LR.HD      # sigmoid gate                HD
AT_GATED = AT_OG + LR.HD         # gated heads                 NQH
AT_GX8 = AT_GATED + NQH + 64     # o_proj int8 input (64-word legacy pad) NQH
AT_OSTG = BIG + H                # o_proj y32 stage            STGCH
AT_ODST = AT_OSTG + STGCH + H    # residual delta              H

ML_GP = STG                      # gate|up int32 pairs         2*FFN
ML_SG = ML_GP + 2 * FFN          # silu(gate)                  FFN
ML_DSTG = ML_SG                  # down y32 stage (SG is dead) STGCH
ML_DDST = ML_SG + STGCH          # residual delta              H

HD_LNF = STG                     # final-norm weight staging   H
HD_AMAX = STG                    # argmax y32 chunks           2*CHUNK

# peak word actually touched by each body (see docs/QWEN2B_SCRATCH_MAP.md)
PEAK_DN = DN_Z16 + LR.LVD
PEAK_ATTN = max(AT_KR + KVH, AT_ODST + H, AT_GX8 + NQH)
PEAK_MLP = max(ML_SG + FFN, ML_DDST + H)
PEAK = max(PEAK_DN, PEAK_ATTN, PEAK_MLP)
# physical scratch depth: the next power of two, never below the frozen 16K
SCRATCH = 1 << max(14, (PEAK - 1).bit_length())

_LEGACY_MAP = {                  # the frozen Qwen3.5-0.8B literals
    "X0": 0, "XN": 1024, "X8": 2048, "SCA": 3072, "SCA_SZ": 992, "STG": 4096,
    "STG_SZ": 4096, "BIG": 8192, "B16": 3072, "A16": 3104, "GD": 3136,
    "QN": 3168, "QNS": 3296, "KN": 3424, "DO32": 3552, "OH": 3808,
    "NH": 3936, "PEAK_DN": 16384, "PEAK_ATTN": 15872, "PEAK_MLP": 14848,
    "SCRATCH": 16384,
}
if (H, FFN) == (1024, 3584):
    _g = globals()
    for _k, _v in _LEGACY_MAP.items():
        assert _g[_k] == _v, f"0.8B scratch map moved: {_k} {_g[_k]} != {_v}"


def scratch_map():
    """The full region table: name -> (base, size, note).  A REPORTING view
    over the module constants above — it must not re-derive anything, so
    that the doc, the TB case generators and the emitting bodies can never
    disagree.  _MAP_PEAK_OK asserts the view still tops out at PEAK."""
    return {
        # ---- global (live across a whole token) ----
        "X0   residual":     (X0, H, "live end-to-end"),
        "XN   normed":       (XN, H, "transient, per norm"),
        "X8   int8 act":     (X8, H, "transient, per matvec group"),
        "SCA  DN scalars":   (SCA, SCA_SZ, "B16/A16/GD/QN/QNS/KN/DO32/OH/NH"),
        "STG  staging":      (STG, STG_SZ, "W/W32 window + out-proj x8"),
        # ---- DeltaNet body ----
        "DN.QKV":            (DN_QKV, LR.CONV_DIM, "conv q|k|v, 16-bit"),
        "DN.Z16":            (DN_Z16, LR.LVD, "z branch"),
        "DN.ON":             (DN_ON, LR.LVD, "gated outputs, overlays XN"),
        "DN.OUTSTG":         (DN_OUTSTG, STGCH, "out-proj y32 stage"),
        "DN.OUTDST":         (DN_OUTDST, H, "residual delta, overlays QKV (dead)"),
        # ---- full-attention body ----
        "AT.QG":             (AT_QG, 2 * NQH, "q_proj out = q | gate"),
        "AT.K16":            (AT_K16, KVH, "k_proj out"),
        "AT.V16":            (AT_V16, KVH, "v_proj out"),
        "AT.QR":             (AT_QR, NQH, "roped q"),
        "AT.KR":             (AT_KR, KVH, "roped k"),
        "AT.AO32":           (AT_AO32, 2 * LR.HD, "ATTN out (int32)"),
        "AT.OG":             (AT_OG, LR.HD, "sigmoid gate"),
        "AT.GATED":          (AT_GATED, NQH, "gated heads"),
        "AT.GX8":            (AT_GX8, NQH, "o_proj x8"),
        "AT.OSTG":           (AT_OSTG, STGCH, "o_proj y32 stage"),
        "AT.ODST":           (AT_ODST, H, "residual delta"),
        # ---- MLP body ----
        "ML.GP":             (ML_GP, 2 * FFN, "gate|up int32 pairs"),
        "ML.SG":             (ML_SG, FFN, "silu(gate)"),
        "ML.DSTG":           (ML_DSTG, STGCH, "down y32 stage (=SG)"),
        "ML.DDST":           (ML_DDST, H, "residual delta"),
        # ---- LM-head tail (gen_model_script / gen_token_script) ----
        "HD.LNF":            (HD_LNF, H, "final-norm weight staging"),
        "HD.AMAX":           (HD_AMAX, 2 * CHUNK, "argmax y32 chunks"),
    }


# The reported table and the PEAK used to size scratch must top out at the
# same word — otherwise one of the two views has drifted.
_MAP_PEAK_OK = max(b + s for b, s, _ in scratch_map().values())
assert _MAP_PEAK_OK == PEAK, \
    f"scratch_map() tops out at {_MAP_PEAK_OK} but PEAK is {PEAK}"
assert PEAK <= SCRATCH, f"PEAK {PEAK} exceeds SCRATCH {SCRATCH}"

# ----------------------------------------------------------------------
# BANKED LAYER STATE — one slot per layer of each kind (spec 7.1).
#
# G2a: 18 DN / 6 KV / 2 KV-heads served the 24-layer 0.8B and 2B models.
# The 32-layer 4B/9B geometry is 24 DeltaNet + 8 full-attention with NKV=4,
# so all three grow.  These are the ONE definition: `Mach.__init__` sizes its
# bank arrays from them, `Mach.layer()` range-checks against them, and
# `require_supported_geometry` reports them.  The RTL twin (layer_chan's
# bank depth and the KVAP/ATTN kvh field) is Task 10's — a host bank array
# that is larger than the hardware's cannot emit a byte that says so, since
# the only thing the stream carries is the LAYER CSR value.
# S3 (SEQ_ISA v2.1 B15, spec 2026-09-04-qwen35-9b-state-spill-design.md
# 2/3/6.5) RETIRES THE BANKS.  Until v2.0 the layer held one bank per layer
# of each kind and LAYER chose a bank; v2.1 puts the state in DDR and gives
# the layer TWO CACHE SLOTS per kind.  LAYER chooses a SLOT; the layer
# IDENTITY travels in the SLD/SST commands.  These are the ONE definition of
# the slot count -- `Mach.__init__` sizes its slot arrays from them and
# `Mach.layer` range-checks against them, beside `SF.layer_word`'s own check.
_DN_SLOTS = _KV_SLOTS = _CV_SLOTS = 2   # cache slots per kind (spec 3)
_KVH = 4                         # KV heads per attention layer (NKV at 4B/9B)
assert _DN_SLOTS == _KV_SLOTS == _CV_SLOTS == 2, \
    "B15.2's slot fields are ONE bit wide: two slots per kind, no more"
# The DDR IMAGE's extent is the MODEL's layer count, not the cache's -- the
# host mirror is sw/hwmap.STATE_DN_BLOCKS / STATE_KV_BLOCKS / STATE_CV_BLOCKS
# and the ISA mirror is B15.1's `layer` field (5 bits, DN/CV 0..23, KV 0..7).
_DN_LAYERS = 24                  # DeltaNet / conv blocks in the DDR image
_KV_LAYERS = 8                   # full-attention layers in the DDR image
# The SDMA kind codes, mirroring ref/seq_format.SDMA_KIND_{DN,KV,CV}.  They
# are re-declared (not imported) because seq_format imports THIS module at
# its top: see the `SF` proxy below.
K_DN, K_KV, K_CV = 0, 1, 2
# B15.1's block geometry, in bytes.  sw/hwmap.STATE_* is the host's mirror.
_DN_BLOCK  = 1 << 20             # a whole layer: 32 heads x 128 rows x 256 B
_KV_BLOCK  = 1 << 21             # 2 MiB per (layer, kvhead, K|V)
_KV_EXPOFF = 1 << 20             # the exponent side array inside a KV block
_CV_BLOCK  = 1 << 17             # 8192 rows x 16 B


class _LazySF(object):
    """`ref/seq_format` imported LAZILY.

    seq_format does `import gen_layer_script` at its top (it needs the ARG
    packers), so a module-level `import seq_format` HERE is a cycle.  Every
    attribute read goes through the real module, so `SF.layer_word(...)` and
    `SF.sdma_arg0(...)` read exactly as they would with a normal import."""

    def __getattr__(self, name):
        import seq_format
        return getattr(seq_format, name)


SF = _LazySF()


class StateImage(object):
    """The DDR state region as the emitter models it: one uint8 block per
    (kind, layer, head).

    ONE OF TWO INDEPENDENT IMPLEMENTATIONS of the B15.1 byte layouts.  The
    other is `ref/seq_model.StateRegion`, written separately ON PURPOSE: the
    SEQ gate compares the two, so a shared serialiser would make the
    comparison vacuous (spec 6.5, "the emitter model, in lockstep")."""

    def __init__(self):
        self.blocks = {}                 # (kind, layer, head) -> uint8 array

    def get(self, key, nbytes):
        # `setdefault` EVALUATES its default, so it allocated an nbytes array
        # on every HIT -- a 2 MiB KV block per SLD, per SST, per peek.  Look
        # up first, allocate only on a miss (S3 fix round 1, M3).
        b = self.blocks.get(key)
        if b is None:
            b = np.zeros(nbytes, dtype=np.uint8)
            self.blocks[key] = b
        assert len(b) == nbytes, (
            f"block {key} is {len(b)} B, this call wants {nbytes} B")
        return b


def clip16(x):
    return np.clip(np.asarray(x, dtype=I64), -32768, 32767)


# ---------------------------------------------------------------------
# 16-bit scratch addressing (G3.1, spec 4.3 S3, SEQ_ISA v2.0)
#
# The scratchpad is 65,536 words and every scratch address field in the
# layer command ISA is 16 bits.  There are NO SCATTERED BITS ANYWHERE:
#
#   ARG1 (every command) and ARG2 (GATE, DNST) carry a PAIR of addresses
#     as {hi[31:16], lo[15:0]}.
#   ALU  ARG2 is {dst[31:16], p0[15:0]}; p0 is 17 bits, so its ONE top bit
#     moves to ARG0[18] — the single relocation in the whole re-encoding,
#     into a bit feasibility 2.4 proved spare over 293,768 ALU dispatches.
#   GATE ARG0 is just dst, 16 bits wide (arg0[15:0]).
#   DNST ARG0 is {spare[31:5], head[4:0]}: its two SCALAR pointers are gone
#     from the arg words entirely and come from the new DNSB layer CSR as
#     a_dec = a_dec_base + head / a_beta = a_beta_base + head.  69 of 96.
#
# WHY THE SCATTER IS DELETED RATHER THAN EXTENDED.  R-b's
# {hi[27:14], lo[13:0]} + lo[14]@28 + hi[14]@29 existed for exactly one
# reason: every frozen pre-R-b stream had addresses < 16384, so the
# borrowed bits emitted 0 and those streams replayed bit-identically.  The
# 9B geometry has no frozen stream to preserve (spec 8 G3: the byte-lock is
# SPENT here), and there was no 16th spare bit to borrow anyway — DNST used
# 94 of its 96 arg bits.  build_034/build_035 keep running SEQ_ISA v1.7
# from their own pre-G3 checkout; this tree emits and decodes v2.0 ONLY.
# ---------------------------------------------------------------------
# G2a split two ceilings that one name was conflating.  G3.1 raises the
# narrower one to meet the wider, and they stay two names because they mean
# two different things:
#
#   SCRATCH_MAX     the scratchpad depth (spec 4.3 S4: 65,536 words, fully
#                   backed).  This is what `enc_saddr` range-checks.
#   ISA_SADDR_MAX   what an ARG word can CARRY.  v1.7's pair packing could
#                   express 32,768; v2.0's 16-bit halves express the whole
#                   array, so the two numbers now COINCIDE — which is the
#                   point of S4 ("fully backed, no unbacked hole"), not an
#                   invitation to merge the names.  If the array ever grows
#                   past what a half can carry, they part again.
SCRATCH_MAX = 65536               # scratch array depth (spec 4.3 S4)
ISA_SADDR_MAX = 65536             # 16-bit ARG halves (SEQ_ISA v2.0, G3.1)


def enc_saddr(a):
    """Range-check one scratch address against the scratchpad DEPTH.

    The ceiling is the array's, not this model's: a script that addresses
    past it cannot be stored.  What an ARG word can CARRY is
    `ISA_SADDR_MAX`, checked by the pair packers below."""
    a = int(a)
    assert 0 <= a < SCRATCH_MAX, \
        f"scratch address {a} outside the scratchpad 0..{SCRATCH_MAX - 1}"
    return a


def enc_isa_saddr(a):
    """Range-check one scratch address against what an ARG word can CARRY.

    Separate from `enc_saddr` because the two ceilings are different
    QUESTIONS even when they carry the same number: this one is about the
    ISA encoding (SEQ_ISA v2.0, 16-bit halves), that one about the array."""
    a = enc_saddr(a)
    assert a < ISA_SADDR_MAX, (
        f"scratch address {a} outside the 16-bit ISA range "
        f"0..{ISA_SADDR_MAX - 1} — SEQ_ISA v2.0 packs address PAIRS into one "
        f"ARG word as {{hi[31:16], lo[15:0]}}")
    return a


def enc_a1(lo, hi=0):
    """Pack an address PAIR the way ARG1 (and GATE/DNST ARG2) carries it."""
    lo, hi = enc_isa_saddr(lo), enc_isa_saddr(hi)
    return (lo & 0xFFFF) | ((hi & 0xFFFF) << 16)


def dec_a1_lo(a1):
    return a1 & 0xFFFF


def dec_a1_hi(a1):
    return (a1 >> 16) & 0xFFFF


def enc_alu_a2(p0, dst):
    """Pack the ALU ARG2 word: {dst[31:16], p0[15:0]}.

    p0 is SEVENTEEN bits (rtl/vec_alu.sv cfg_p0), so its top bit does NOT
    live here — `Mach.alu` puts it in ARG0[18].  `enc_alu_a0` is the other
    half of this pair and the two must be read together."""
    dst = enc_isa_saddr(dst)
    return (p0 & 0xFFFF) | ((dst & 0xFFFF) << 16)


def enc_alu_a0(op, n, p0):
    """Pack the ALU ARG0 word: {spare[31:19], p0[16]@18, len[13:0]@17:4,
    aop[3:0]}."""
    return (op & 0xF) | ((n & 0x3FFF) << 4) | (((p0 >> 16) & 1) << 18)


def dec_alu_dst(a2):
    return (a2 >> 16) & 0xFFFF


def dec_alu_len(a0):
    return (a0 >> 4) & 0x3FFF


def dec_alu_p0(a0, a2):
    """The 17-bit p0, whose top bit is the ONE relocation in SEQ_ISA v2.0."""
    return (a2 & 0xFFFF) | (((a0 >> 18) & 1) << 16)


def rs_s(v, p):
    """rshr64s: round-half-away right shift; negative p = left shift."""
    v = np.asarray(v, dtype=I64)
    return rshr(v, p) if p >= 0 else v << (-p)


class Mach:
    """Scratchpad model + script emitter. Every emitter applies the exact
    layer_chan semantics to the model."""

    def __init__(self, f):
        self.f = f
        self.mem = np.zeros(SCRATCH, dtype=I64)  # int16 view
        self.eout = 0
        self.vnw = np.zeros(H, dtype=I64)
        self.cos = np.zeros(LR.ROT, dtype=I64)
        self.sin = np.zeros(LR.ROT, dtype=I64)
        # ---- v2.1 CACHE SLOTS + the DDR state image (spec 3, 6.5) ------
        # TWO slots per kind, and one DDR image behind them.  SLD copies
        # image -> slot, SST copies slot -> image, compute runs on the slot,
        # and every compute command asserts its slot is WARM (the emitter's
        # twin of the RTL's E_DMA_COLD, B15.4).
        self.cw = np.zeros((_CV_SLOTS, LR.CONV_DIM, 4), dtype=I64)
        self.cs = np.zeros((_CV_SLOTS, LR.CONV_DIM, 3), dtype=I64)
        self.S = np.zeros((_DN_SLOTS, LR.LNH, LR.LDK, LR.LDV), dtype=I64)
        # ONE kvhead per KV slot; WHICH one is the slot's TAG (spec A1.3),
        # not an address field.  Each list is that slot's K (kc) / V (vc)
        # rows, in append order.
        self.kc = [[] for _ in range(_KV_SLOTS)]
        self.vc = [[] for _ in range(_KV_SLOTS)]
        # TCNT is indexed by ATTENTION LAYER, exactly as the hardware's
        # `tcnt_bank[kv_layer][kvhead]` is (spec A1.3, B15.2).
        self.T = [[0] * _KVH for _ in range(_KV_LAYERS)]
        self.img = StateImage()                  # the DDR side
        self.img_init = None                     # snapshot before the 1st SST
        self.warm = {k: [False, False] for k in (K_DN, K_KV, K_CV)}
        self.slot_id = {k: [None, None] for k in (K_DN, K_KV, K_CV)}
        self.tag = [None, None]                  # KV slot tag (layer, kvhead)
        self.dn_slot = 0                         # current DN cache slot
        self.kv_slot = 0                         # current KV cache slot
        self.cv_slot = 0                         # current conv cache slot
        self.kv_layer = 0                        # LAYER.kv_layer (TCNT index)
        self.layer_is_set = False                # has a LAYER record run?
        # SEQ_ISA v2.0: the DNSB layer CSR (a_beta_base, a_dec_base) and the
        # dst of the last GATE, which is the LAYOUT AUTHORITY for the
        # beta|decay tile the DNST scalar pointers index (spec 4.3 S3).
        self.dnsb_bases = None
        self.gate_dst = None
        self.ncmd = 0
        self.nw = 0
        self.wids = {}                           # id(qw) -> (wid, qw)
        self.emb = None                          # stage 4 embedding table
        self.am_val = 0                          # AMAX32 running state
        self.am_idx = 0
        self.am_g = 0
        self.am_first = True
        self.audit = None                        # see audit_on()
        # optional callback fn(dn_slot, a[16], dt[16], A[16], decay[16])
        # invoked after every GATE; used by gen_model_script to measure the
        # gate-port clamp error at the real runtime activations.
        self.gate_probe = None
        # ---- SEQ binary-stream emitter (OPT-IN, rung 1) -----------------
        # `self.seq` is None unless SEQ_EMIT is set in the environment, and
        # every hook below is guarded by `if self.seq is not None`, so the
        # DEFAULT .txt output of every generator is byte-identical to the
        # pre-sequencer tree (proved by the regen hashes in the gate log).
        # See ref/seq_format.py (records) and ref/seq_model.py (executor).
        self.seq = None
        self._seq_mute = False
        import os as _os
        if _os.environ.get("SEQ_EMIT"):
            import seq_format as _sq
            self.seq = _sq.maybe_attach(self, f)
        # S3: WHERE the DDR state region sits.  It is DERIVED, not chosen --
        # sw/hwmap.plan_state_base is a function of the stream's channel
        # count -- so the emitter, the reference model, the chip TB and the
        # host cannot disagree about it, and the program can carry the three
        # base CSR writes itself (see `sbase`).
        #
        # LAZY, because at nch == 1 the plan needs the EMBEDDING TABLE's
        # extent to prove it does not overlap (S3 fix round 1, I4) and
        # `self.emb` is set by the caller AFTER construction.  Every
        # consumer -- `sbase()` from the preamble, `dump_state()` at the end
        # -- runs after that.
        self._state_plan = None

    # ---------------- runtime range audit (opt-in, emits nothing) ----------
    # Completes the "deferred, activation-dependent" rows of
    # ref/audit_ranges_report.md section 5.  Every command that writes int16
    # scratch reports how many written words sit AT the int16 rail; a true
    # clip is always a rail hit, so "0 rail hits" proves no saturation
    # anywhere in the run.  DNST additionally reports true |S| > 32767
    # saturations (the layer_fixed.py S_F note) and matvec reports y32
    # occupancy + the DYNQ8 exponents.
    def audit_on(self):
        self.audit = {"rail": {}, "y32": {}, "eout": {}, "s_sat": 0,
                      "s_absmax": 0, "s_writes": 0, "s_where": {},
                      "silu_pre": 0}

    def _aud(self, tag, arr):
        if self.audit is None:
            return
        a = np.asarray(arr, dtype=I64)
        st = self.audit["rail"].setdefault(tag, [0, 0, 0])
        st[0] += int(((a >= 32767) | (a <= -32768)).sum())
        st[1] += int(a.size)
        if a.size:
            st[2] = max(st[2], int(np.abs(a).max()))

    def audit_report(self, out=None):
        """Human-readable audit + hard verdicts. Returns (text, ok)."""
        import io
        a = self.audit
        buf = out or io.StringIO()
        w = buf.write
        w("--- runtime range audit (activation-dependent formats) ---\n")
        w(f"{'site':<14}{'rail hits':>11}{'of words':>12}{'|max|':>9}\n")
        rail_total = 0
        for tag in sorted(a["rail"]):
            n, tot, mx = a["rail"][tag]
            rail_total += n
            w(f"{tag:<14}{n:>11d}{tot:>12d}{mx:>9d}\n")
        w(f"{'TOTAL':<14}{rail_total:>11d}\n")
        w(f"DeltaNet state S_F={S_F} (int16 Q{15 - S_F}.{S_F}, "
          f"+/-{(1 << 15) / (1 << S_F):.1f}): true saturations="
          f"{a['s_sat']} of {a['s_writes']} state writes, "
          f"|S|max={a['s_absmax']} of 32767 "
          f"({100.0 * a['s_absmax'] / 32767:.1f}% of the int16 rail, "
          f"= {a['s_absmax'] / (1 << S_F):.3f} in Q{15 - S_F}.{S_F})\n")
        if a["s_where"]:
            w("  saturating (dn_slot, head): "
              + ", ".join(f"{k}x{v}" for k, v in sorted(a["s_where"].items()))
              + "\n")
        w(f"silu 21-bit port clips: {a['silu_pre']}\n")
        w("y32 accumulator occupancy (int32 = 31 magnitude bits):\n")
        for tag in sorted(a["y32"]):
            mx, n = a["y32"][tag]
            w(f"  {tag:<12} |y32|max={mx:<12d} bits={int(mx).bit_length():>2d}"
              f"  spare={31 - int(mx).bit_length():>2d}  ({n} matvecs)\n")
        w("DYNQ8 activation exponents (e_x histogram): "
          + " ".join(f"{k}:{v}" for k, v in sorted(a["eout"].items())) + "\n")
        ok = (rail_total == 0) and (a["s_sat"] == 0) and (a["silu_pre"] == 0)
        w("RANGE AUDIT: " + ("PASS (no saturation anywhere)\n" if ok else
                             "FAIL — saturation observed, see above\n"))
        return (None if out else buf.getvalue()), ok

    # ---------------- records ----------------
    def _emit16(self, vals):
        self.f.write("".join(f"{int(v) & 0xFFFF:04x}\n" for v in vals))

    def W(self, addr, vals):
        vals = np.asarray(vals, dtype=I64)
        assert np.all(vals >= -32768) and np.all(vals <= 32767), "W range"
        assert addr + len(vals) <= SCRATCH
        self.mem[addr:addr + len(vals)] = vals
        print(f"W {addr:x} {len(vals):x}", file=self.f)
        self._emit16(vals)
        self.nw += len(vals)
        if self.seq is not None and not self._seq_mute:
            self.seq.on_w(addr, vals)

    def W_raw(self, addr, vals):
        """16-bit raw bit patterns (e.g. low halves of 18-bit constants)."""
        vals = np.asarray(vals, dtype=I64) & 0xFFFF
        vals = np.where(vals >= 32768, vals - 65536, vals)
        self.W(addr, vals)

    def W32(self, addr, vals32):
        vals32 = np.asarray(vals32, dtype=I64)
        assert np.all(np.abs(vals32) < (1 << 31)), "y32 overflow"
        w = np.zeros(2 * len(vals32), dtype=I64)
        w[0::2] = vals32 & 0xFFFF
        w[1::2] = (vals32 >> 16) & 0xFFFF
        w = np.where(w >= 32768, w - 65536, w)
        if self.seq is not None:
            # W32 is ONLY ever the matvec y32 injection; in the SEQ stream
            # the engine writes it directly (MVGO + MOVY), so the host W is
            # muted and the following ALU command is fused instead.
            self.seq.on_w32(addr, vals32)
            self._seq_mute = True
        self.W(addr, w)
        self._seq_mute = False

    def pairs(self, addr, n):
        lo = self.mem[addr:addr + 2 * n:2] & 0xFFFF
        hi = self.mem[addr + 1:addr + 2 * n:2] & 0xFFFF
        v = lo | (hi << 16)
        return np.where(v >= (1 << 31), v - (1 << 32), v)

    def set_pairs(self, addr, vals32):
        vals32 = np.asarray(vals32, dtype=I64)
        w = np.zeros(2 * len(vals32), dtype=I64)
        w[0::2] = vals32 & 0xFFFF
        w[1::2] = (vals32 >> 16) & 0xFFFF
        self.mem[addr:addr + 2 * len(vals32)] = np.where(w >= 32768,
                                                         w - 65536, w)

    def R(self, addr, n):
        print(f"R {addr:x} {n:x}", file=self.f)
        self._emit16(self.mem[addr:addr + n])
        if self.seq is not None:
            self.seq.on_r(addr, n)

    def E(self):
        print(f"E {self.eout:x}", file=self.f)

    def Treset(self):
        """Zero EVERY KV append counter — all _KV_LAYERS x _KVH of them.

        ONE record, ALL the counters.  Under v2.0 TCNT was banked by
        kv_slot and this record zeroed the CURRENT bank's _KVH counters.
        Under v2.1 (spec A1.3) `tcnt_bank` is indexed by ATTENTION LAYER and
        the LAYER CSR's `kv_layer` field selects which pair of counters the
        TCNT/TCNT2 CSRs address, so a session reset is EIGHT LAYER writes
        and SIXTEEN TCNT/TCNT2 writes.  The replayers expand this one record
        into exactly that (ref/seq_format.SeqEmitter.on_treset,
        ref/seq_model.TxtReplay, tb/tb_layer_chan.sv), so the script format
        is unchanged.  Nothing else may write TCNT.
        """
        self.T = [[0] * _KVH for _ in range(_KV_LAYERS)]
        print("T 0", file=self.f)
        if self.seq is not None:
            self.seq.on_treset()

    def layer(self, dn_slot, kv_slot, cv_slot=0, kv_layer=0):
        """Select the CACHE SLOTS the compute commands read (B15.2).

        `cv_slot` and `kv_layer` DEFAULT so that a two-argument caller from
        the banked era still runs; every live 9B path passes four.  Emits
        the LAYER CSR record
        L {18'b0, cv_slot[13:12], 1'b0, kv_layer[10:8], 3'b0,
           kv_slot[4:3], 1'b0, dn_slot[1:0]}."""
        assert 0 <= dn_slot < _DN_SLOTS and 0 <= kv_slot < _KV_SLOTS, \
            f"LAYER slot fields are one bit: dn={dn_slot} kv={kv_slot}"
        assert 0 <= cv_slot < _CV_SLOTS, f"LAYER cv_slot {cv_slot} > 1"
        assert 0 <= kv_layer < _KV_LAYERS, \
            f"LAYER kv_layer {kv_layer} outside 0..{_KV_LAYERS - 1}"
        self.dn_slot = dn_slot
        self.kv_slot = kv_slot
        self.cv_slot = cv_slot
        self.kv_layer = kv_layer
        self.layer_is_set = True
        print(f"L {SF.layer_word(dn_slot, kv_slot, cv_slot, kv_layer):08x}",
              file=self.f)
        if self.seq is not None:
            self.seq.on_layer(dn_slot, kv_slot, cv_slot, kv_layer)

    @property
    def state_plan(self):
        """The DDR state region's plan, computed once, on first use."""
        if self._state_plan is None:
            import hwmap as _hw
            nch = self.seq.nch if self.seq is not None else 1
            if self.emb is None:
                vocab, row_b = 0, 0
            else:
                vocab, row_b = len(self.emb), 2 * int(self.emb.shape[1])
            self._state_plan = _hw.plan_state(
                _hw.plan_state_base(nch, vocab=vocab, emb_row_bytes=row_b))
        return self._state_plan

    def sbase(self):
        """Program SB_DN / SB_KV / SB_CV (B15.3), in 64 KiB units.

        Emits the record `S <sb_dn> <sb_kv> <sb_cv> <units>`, all four in
        64 KiB units, which is what the CSRs take.  The host writes the same
        three values from the manifest before the first launch and refuses
        to launch on a zero readback (spec 7.2); the program carries them so
        that a replay -- the chip TB, `tb_layer_chan`, `ref/seq_model` -- is
        self-contained and cannot be run against a region nobody
        programmed (the RTL would answer E_DMA_BASE)."""
        p = self.state_plan
        u = 1 << 16
        print(f"S {p['dn'] // u:x} {p['kv'] // u:x} {p['cv'] // u:x} "
              f"{(p['end'] - p['dn']) // u:x}", file=self.f)
        if self.seq is not None:
            self.seq.on_sbase(p["dn"] // u, p["kv"] // u, p["cv"] // u)

    # ---------------- v2.1 state DMA: SLD / SST (B15.1) ----------------
    _KIND_NAME = ("DN", "KV", "CV")

    def _blk_id(self, kind, layer, head):
        """WHICH BLOCK a slot holds.  For KV the identity is the slot's TAG
        — (layer, kvhead) — not (layer, head): the K and V halves of one
        kvhead are two SLD/SST commands (head = {kvhead[1:0], kv}) that fill
        and drain the SAME slot, so keying on `head` would make the SST of
        the K half claim the slot held 'another block'.  The hardware says
        the same thing with `kv_tag = {layer[2:0], kvhead[1:0]}` (A1.3)."""
        return (layer, head >> 1) if kind == K_KV else (layer, head)

    def sld(self, kind, slot, layer, head=0):
        """Queue a load of block (kind, layer, head) into cache slot `slot`."""
        self.C(13, SF.sdma_arg0(kind, slot, layer, head), 0, 0)
        self._sdma_copy(kind, slot, layer, head, to_slot=True)
        self.warm[kind][slot] = True
        self.slot_id[kind][slot] = self._blk_id(kind, layer, head)
        if kind == K_KV:
            self.tag[slot] = (layer, head >> 1)

    def sst(self, kind, slot, layer, head=0):
        """Queue a store of cache slot `slot` to block (kind, layer, head)."""
        self.C(14, SF.sdma_arg0(kind, slot, layer, head), 0, 0)
        want = self._blk_id(kind, layer, head)
        assert self.slot_id[kind][slot] == want, (
            f"SST of a slot holding another block: "
            f"{self._KIND_NAME[kind]} slot {slot} holds "
            f"{self.slot_id[kind][slot]}, the command names {want}")
        self._sdma_copy(kind, slot, layer, head, to_slot=False)
        self.warm[kind][slot] = False

    def _require_warm(self, kind, slot, what):
        assert self.warm[kind][slot], \
            f"{what}: {self._KIND_NAME[kind]} slot {slot} is COLD (E_DMA_COLD)"

    def _require_tag(self, kvh, what):
        """The hardware's tag check (A1.3): KVAP/ATTN name the kvhead the
        slot's tag carries, or the command is refused (E_DMA_RANGE)."""
        tg = self.tag[self.kv_slot]
        assert tg is not None and tg[1] == kvh, (
            f"{what} kvhead {kvh} on KV slot {self.kv_slot}, whose tag is "
            f"{tg} (E_DMA_RANGE)")
        return tg

    def seed_conv(self, layer, conv_w):
        """Seed the DDR image's conv block for `layer` with the weight taps
        the RETIRED CONVW preamble used to load (spec 2 'Initial contents',
        6.4).  The host writes exactly these bytes at upload (the manifest's
        `conv_images`); the three state words stay zero, which is what the
        retired CONVZ did.  `evidence/qwen9b/s3/preamble_equiv.py` is the
        guard that the two really are the same bytes."""
        blk = self.img.get((K_CV, layer, 0), _CV_BLOCK)
        w = np.asarray(conv_w, dtype=I64).reshape(LR.CONV_DIM, 4)
        rows = blk.reshape(LR.CONV_DIM, 16)
        rows[:, 0:8] = w.astype("<i2").view(np.uint8).reshape(LR.CONV_DIM, 8)
        rows[:, 8:16] = 0
        return blk

    def _sdma_copy(self, kind, slot, layer, head, to_slot):
        """The B15.1 DDR row formats, serialised/deserialised.

        DN  a WHOLE layer (A1.1): 4096 rows x 256 B, row {head[4:0],
            dk[6:0]} = S[head][dk] as LDV int16 little-endian.
        KV  TCNT[layer][kvhead] rows x 256 B of int8, then the exponent side
            array (one signed byte per row) at +1 MiB.  `head` is
            {kvhead[1:0], kv}; kv 0 is K, 1 is V.  TCNT is read HERE, at the
            SST's own point in the program, which is the ISA's "TCNT as read
            when the transfer starts" (B15.1) for this schedule.
        CV  8192 rows x 16 B: [63:0] the four weight taps, [111:64] the three
            state words, [127:112] zero."""
        if not to_slot and self.img_init is None:
            # The INITIAL image is what the host uploads and what the chip
            # TB preloads, and this is the last moment it still exists: the
            # first SST is the first write into the region.  A block created
            # after this point was zero before it, which is what a reader
            # that does not find it in the snapshot answers.
            self.img_init = {k: v.copy() for k, v in self.img.blocks.items()}
        if kind == K_DN:
            assert head == 0, "a DN transfer moves the WHOLE layer (A1.1)"
            blk = self.img.get((K_DN, layer, 0), _DN_BLOCK)
            v = blk.view("<i2").reshape(LR.LNH, LR.LDK, LR.LDV)
            if to_slot:
                self.S[slot] = v.astype(I64)
            else:
                v[:] = np.asarray(self.S[slot], dtype="<i2")
        elif kind == K_KV:
            kvh, kv = head >> 1, head & 1
            T = int(self.T[layer][kvh])
            assert T <= SF.STATE_T_MAX, f"KV transfer of {T} rows > 4096"
            blk = self.img.get((K_KV, layer, head), _KV_BLOCK)
            rows = blk[:T * LR.HD].view(np.int8).reshape(T, LR.HD)
            exps = blk[_KV_EXPOFF:_KV_EXPOFF + T].view(np.int8)
            cache = self.kc[slot] if kv == 0 else self.vc[slot]
            if to_slot:
                new = [(rows[t].astype(I64), int(exps[t])) for t in range(T)]
                if kv == 0:
                    self.kc[slot] = new
                else:
                    self.vc[slot] = new
            else:
                assert len(cache) == T, (
                    f"SST KV (layer {layer}, kvhead {kvh}, kv {kv}): the slot "
                    f"holds {len(cache)} rows, TCNT says {T}")
                for t in range(T):
                    rows[t] = np.asarray(cache[t][0], dtype=np.int8)
                    exps[t] = np.int8(cache[t][1])
        elif kind == K_CV:
            assert head == 0, "a CV transfer moves the whole layer block"
            blk = self.img.get((K_CV, layer, 0), _CV_BLOCK)
            rows = blk.reshape(LR.CONV_DIM, 16)
            if to_slot:
                w = rows[:, 0:8].copy().view("<i2").reshape(LR.CONV_DIM, 4)
                st = rows[:, 8:14].copy().view("<i2").reshape(LR.CONV_DIM, 3)
                self.cw[slot] = w.astype(I64)
                self.cs[slot] = st.astype(I64)
            else:
                rows[:, 0:8] = (np.asarray(self.cw[slot], dtype="<i2")
                                .view(np.uint8).reshape(LR.CONV_DIM, 8))
                rows[:, 8:14] = (np.asarray(self.cs[slot], dtype="<i2")
                                 .view(np.uint8).reshape(LR.CONV_DIM, 6))
                rows[:, 14:16] = 0
        else:
            raise AssertionError(f"SDMA kind {kind} is reserved (B15.1)")

    def C(self, op, a0, a1, a2):
        # debug hook: GLS_DUMP_AT=<N> GLS_DUMP_TO=<file.npy> dumps the model
        # scratch after exactly N commands (state at entry of command N+1);
        # pairs with layer_test.py --stop-after/--dump for HW bisection.
        import os as _os
        if (self.ncmd == int(_os.environ.get("GLS_DUMP_AT", "-1"))
                and _os.environ.get("GLS_DUMP_TO")):
            np.save(_os.environ["GLS_DUMP_TO"], self.mem)
        assert 0 <= a0 < (1 << 32) and 0 <= a1 < (1 << 32) and 0 <= a2 < (1 << 32)
        print(f"C {op:x} {a0:x} {a1:x} {a2:x}", file=self.f)
        self.ncmd += 1
        if self.seq is not None:
            self.seq.on_c(op, a0, a1, a2)

    # ---------------- commands (emit + model) ----------------
    def vn(self, mode, n, inf, outf, src, dst):
        nlog2 = int(n).bit_length() - 1
        assert (1 << nlog2) == n
        self.C(1, mode | (nlog2 << 2) | (inf << 6) | (outf << 10),
               enc_a1(src, dst), 0)
        x = self.mem[src:src + n]
        if mode == 0:
            y = LF.rmsnorm_fx(x, self.vnw[:n], inf, True)
        elif mode == 1:
            y = LF.rmsnorm_fx(x, self.vnw[:n], inf, False)
        else:
            y = LF.l2norm_fx(x, inf, outf)
        self.mem[dst:dst + n] = np.asarray(y, dtype=I64)
        self._aud(f"vn{mode}", y)

    # VNW's count field is ARG0[12:0] in the RTL (G3.1, spec 4.3): THIRTEEN
    # bits, so 4096 is carried DIRECTLY and there is NO ESCAPE ENCODING.
    # v1.7's field was ARG0[10:0] and 0 MEANT 2048, which is why `4096 &
    # 0x7FF == 0` would have normalised over half the vector and said
    # nothing (wall 3's shape).  At 13 bits `0` means 0, and an emitter
    # assert refuses it — the RTL's `ld_i + 1 == ld_n` would otherwise run
    # the full 8192-count wrap.  The 2048 every 2B stream emits is
    # BYTE-IDENTICAL either way (2048 fits both fields unmasked).
    #
    # Three bounds, three different questions, and only the middle one moved
    # here (the controller's field-vs-datapath split):
    #   VNW_MAX      what a GEOMETRY may ask for (H, so 4096 at 9B)
    #   VNW_ISA_MAX  what the ARG0 FIELD can carry — 4096, lifted at G3.1
    #   VNW_HW_MAX   how deep `vecnorm_unit`'s wbuf actually IS — 4096
    #                since G3.2 (Task 8) widened xbuf/wbuf, the counters to
    #                13 b and w_waddr/vn_waddr to 12 b.  It is a DATAPATH
    #                bound, not a field, and it stays as a SEPARATE name:
    #                the three now coincide at 4096, but they answer three
    #                different questions and a future geometry moves them
    #                independently.
    VNW_MAX = 4096
    VNW_ISA_MAX = 4096
    VNW_HW_MAX = 4096

    def vnw_(self, src, n):
        assert 1 <= n <= self.VNW_MAX, f"VNW count {n} outside 1..{self.VNW_MAX}"
        assert 1 <= n <= self.VNW_ISA_MAX, (
            f"VNW count {n} does not fit ARG0[12:0] (max {self.VNW_ISA_MAX}); "
            f"SEQ_ISA v2.0 has NO 0-encodes-the-top escape, so 0 is 0.")
        assert n <= self.VNW_HW_MAX, (
            f"VNW count {n} exceeds the vecnorm wbuf depth "
            f"{self.VNW_HW_MAX} — the ARG0 field would carry it (G3.1) but "
            f"rtl/vecnorm_unit.sv's xbuf/wbuf are only that deep.  G3.2 "
            f"took the DATAPATH to 4096; anything beyond is new RTL, not "
            f"a host patch.")
        self.C(2, n, enc_a1(src), 0)
        self.vnw[:n] = self.mem[src:src + n]

    def ropet(self, src):
        self.C(3, 0, enc_a1(src), 0)
        self.cos = self.mem[src:src + LR.ROT].copy()
        self.sin = self.mem[src + LR.ROT:src + 2 * LR.ROT].copy()

    def rope(self, src, dst):
        self.C(4, 0, enc_a1(src, dst), 0)
        self.mem[dst:dst + LR.HD] = LF.rope_fx(self.mem[src:src + LR.HD],
                                               self.cos, self.sin)

    # CONVW/CONVZ ARG0 = {nch[29:16], first[15:2], sel[1:0]} and CONV
    # ARG0 = {nch[27:14], first[13:0]} — both FOURTEEN-bit channel fields
    # since G3.1 (spec 4.3's per-command table; RTL: the CONV/CONVW slices
    # in rtl/layer_chan.sv).  These asserts exist because the ALU one did
    # not (see alu() further down) and a silently truncated channel range is
    # the same silent-corruption class.
    #
    # G2a review N10: CONV_DIM is 8192 at 4B/9B (2*LKD + LVD with
    # LVD = 4096), which is ONE COUNT over the old 13-bit field's 8191 —
    # `M.convz(0, LR.CONV_DIM)` was the first thing a 9B emission stopped
    # on (G2c).  The FIELD was widened here so a whole-block convz could be
    # ENCODED; G3.4 grew the conv BANKS to 24 x 8192 so it is now
    # EXECUTABLE too, and added the matching SYNTHESIZABLE refusal in
    # rtl/layer_chan.sv (first + nch > CVD, and nch == 0).
    #
    # THE CONVW WRAP ESCAPE IS RETIRED, and this assert is what replaced it
    # (spec 4.6 wall 11).  It was never designed: the two CONVW compare
    # sites did `wi + 1` in THIRTEEN-bit arithmetic, so at wi = 8191 the sum
    # wrapped to 0 and a field value of 0 already encoded 8192 by accident.
    # Task 7 widened `wi` and the field to 14 bits, which removed the 8191
    # wrap; G3.4 finishes the job by making `nch == 0` mean ZERO and be
    # REFUSED on both sides — here in the emitter, and in the RTL envelope.
    CONV_FIELD_MAX = (1 << 14) - 1

    def _conv_fields(self, first, nch):
        assert 0 <= first <= self.CONV_FIELD_MAX, \
            f"CONV first-channel {first} does not fit its 14-bit field"
        assert 1 <= nch <= self.CONV_FIELD_MAX, \
            f"CONV channel count {nch} does not fit its 14-bit field"

    def convw(self, first, nch, src):
        """CONVW sel 0 — the RETIRED weight load (spec 5.5, B15.5).

        S3 keeps this method callable and MODELLING: it loads the current
        conv SLOT's weight memory and warms that slot, which is what the
        pre-G3 (frozen-model) generator paths still need.  Only the RTL
        refuses sel 0/1 (E_DMA_RANGE) — conv blocks arrive by SLD on every
        live 9B path, so no stream this tree emits for the hardware carries
        one.  The plan's standing hazard names this shim by hand."""
        self._conv_fields(first, nch)
        self.C(5, 0 | (first << 2) | (nch << 16), enc_a1(src), 0)
        self.cw[self.cv_slot][first:first + nch] = \
            self.mem[src:src + 4 * nch].reshape(nch, 4)
        self.warm[K_CV][self.cv_slot] = True

    def convz(self, first, nch):
        """CONVW sel 2 — zero the state words of the current conv slot, and
        WARM it (spec 5.5: CONVZ counts as a load for F1)."""
        self._conv_fields(first, nch)
        self.C(5, 2 | (first << 2) | (nch << 16), 0, 0)
        self.cs[self.cv_slot][first:first + nch] = 0
        self.warm[K_CV][self.cv_slot] = True

    def conv(self, first, nch, src, dst):
        self._require_warm(K_CV, self.cv_slot, "CONV")
        self._conv_fields(first, nch)
        self.C(6, first | (nch << 14), enc_a1(src, dst), 0)
        x = self.mem[src:src + nch]
        cs = self.cs[self.cv_slot]
        win = np.concatenate([cs[first:first + nch], x[:, None]], axis=1)
        cs[first:first + nch] = win[:, 1:]
        acc = (win * self.cw[self.cv_slot][first:first + nch]).sum(axis=1)
        pre_raw = rshr(acc, RS_F + CW_F - 12)
        pre = np.clip(pre_raw, -(1 << 20), (1 << 20) - 1)
        if self.audit is not None:
            self.audit["silu_pre"] += int((pre_raw != pre).sum())
        self.mem[dst:dst + nch] = clip16(
            np.array([fp.silu_q(int(v)) for v in pre], dtype=I64))
        self._aud("conv", self.mem[dst:dst + nch])

    # ---- the remaining layer_chan ARG fields, against their RTL slices ----
    # R-c fold 10.  Every SCRATCH ADDRESS already goes through enc_saddr's
    # range check, but the small non-address fields beside them did not, and
    # under SEQ_ISA v1.7 they shared ARG0 with things that DID matter: DNST
    # packed head into arg0[3:0] with a_dec at [17:4] right above it, so a
    # head of 16 corrupted the pointer.  v2.0 empties DNST's ARG0 down to
    # the head, so the CORRUPTION mode is gone and only the truncation mode
    # is left — the guards stay, because truncation is still silent.  Same
    # refuse-don't-corrupt guards alu()/vnw_()/_conv_fields() carry, written
    # after reading each RTL slice, and `ref/scripts/scan_spare_bits.py`
    # confirms none of them can fire on any frozen stream (GATE ARG0 mask
    # 0x00000c40, DNST 0x313cc5ff, KVAP 0x00000081, ATTN 0x00000001).
    #
    # G2a WIDENS TWO OF THESE, and the coupling must be read correctly: the
    # RTL fields are still 4-bit dn_head and 1-bit kvhead at this gate.  What
    # moves here is the HOST's willingness to name head 16..31 / kvh 2..3,
    # which no 0.8B or 2B stream ever does (LNH=16, NKV=2), so nothing is
    # emitted differently.  Task 10 (G3.4) widens the RTL slices to match;
    # until it does, a widened host guard is not a widened hardware field.
    # G3.4 (Task 10) LANDED THE RTL SLICES these two bounds were waiting
    # for: dn_head is five bits of DATAPATH (32-head DN banking) and
    # kvhead is two (4-head KV banking), so the host bound and the hardware
    # bound are the same number again and neither is "a widened host guard
    # that is not a widened hardware field" any more.
    DNST_HEAD_MAX = (1 << 5) - 1        # LNH=32 at 4B/9B; RTL: 32 banks/slot
    KVAP_EXPB_MAX = (1 << 5) - 1        # kv_expbias = arg0[8:4]
    KVH_MAX       = _KVH - 1            # NKV=4 at 4B/9B; RTL: 8 KV banks

    def gate(self, src_b, src_a, src_A, src_dt, dst):
        # every GATE field is a scratch address, so enc_saddr/enc_a1 already
        # range-check all five; nothing else to guard here.
        # G2a: the beta|decay pair is LNH + LNH words, NOT 16 + 16.
        nh = LR.LNH
        self.C(7, enc_isa_saddr(dst), enc_a1(src_b, src_a),
               enc_a1(src_A, src_dt))
        # GATE IS THE LAYOUT AUTHORITY for beta|decay: it is the writer.
        # DNST's scalar pointers are checked against THIS, not against
        # their own base (spec 4.3: a self-consistency assert "passes while
        # both sides are wrong" and would have sailed through GD + 16 + h).
        self.gate_dst = int(dst)
        b = self.mem[src_b:src_b + nh]
        a = self.mem[src_a:src_a + nh]
        Alo = self.mem[src_A:src_A + 2 * nh:2] & 0xFFFF
        Ahi = self.mem[src_A + 1:src_A + 2 * nh:2] & 0x3
        A = Alo | (Ahi << 16)
        dt = self.mem[src_dt:src_dt + nh]
        for h in range(nh):
            self.mem[dst + h] = fp.sigmoid_q(int(b[h]))
            sp = fp.softplus_q(int(a[h] + dt[h]))
            g = -rshr(I64(int(A[h])) * sp, 11)
            self.mem[dst + nh + h] = min(
                rshr(I64(fp.exp_neg_q(int(min(g, 0)))), 15), I64(32767))
        if self.gate_probe is not None:
            self.gate_probe(self.dn_slot, a, dt, A,
                            self.mem[dst + nh:dst + 2 * nh])
        # beta/decay are Q15 gates: 32767 is their legal top rail, not a
        # clip, so they are audited separately from the int16 transports.
        if self.audit is not None:
            self.audit["rail"].setdefault("gate(Q15)", [0, 0, 0])
            self.audit["rail"]["gate(Q15)"][1] += 2 * nh
            self.audit["rail"]["gate(Q15)"][2] = max(
                self.audit["rail"]["gate(Q15)"][2],
                int(np.abs(self.mem[dst:dst + 2 * nh]).max()))

    # SEQ_ISA v2.0 packs the DNST head into ARG0[4:0] and NOTHING ELSE —
    # the two scalar pointers moved out of ARG0 into the DNSB CSR (G3.1),
    # so a head that overran its field can no longer corrupt a pointer.
    # DNST_HEAD_MAX above is the GEOMETRY bound (LNH-1); this is what the
    # ARG word can CARRY.  They are kept as two names because they answer
    # two questions, exactly as SCRATCH_MAX and ISA_SADDR_MAX do.
    ARG0_HEAD_BITS = 5

    # KVAP/ATTN kvhead: the SAME three-name split VNW has, applied the same
    # way.  G3.1 lifts the FIELD (`kvhead_r <= arg0[1:0]`, spec 4.3's table)
    # and introduces the DATAPATH twin, because the KV cache and TCNT banks
    # are still built for TWO heads and a field the RTL decodes at 2 bits is
    # not a bank the RTL can address.
    #   KVH_MAX        what a GEOMETRY may ask for (NKV-1, so 3 at 4B/9B)
    #   ARG0_KVH_BITS  what the ARG0 FIELD can carry — 2, lifted at G3.1
    #   KVH_HW_MAX     how many KV heads the RTL actually BANKS.  G3.4 took
    #                  it 1 -> 3: rtl/layer_chan.sv reads the full
    #                  `kvhead_r <= arg0[KHB-1:0]` (KHB = 2), the KV array
    #                  is 8 banks of {kv_slot, kvhead, k/v, t[8:0]} and
    #                  tcnt_bank is [8][4].  The THREE names stay, because
    #                  they still answer three different questions and the
    #                  next geometry change will separate them again.
    ARG0_KVH_BITS = 2
    KVH_HW_MAX = _KVH - 1

    def _kvh_isa(self, kvh, op):
        """Refuse a kvhead the ARG word cannot carry, then one the hardware
        cannot bank.

        KVH_MAX above is the GEOMETRY bound (NKV-1).  Under SEQ_ISA v1.7 the
        RTL decoded only `arg0[0]`, so kvh 2..3 did not corrupt a
        neighbouring field — it selected the WRONG BANK silently, which is
        worse.  v2.0 gave the field two bits and G3.4 gave the DATAPATH the
        same two, so both bounds are 3 at this geometry; the split is kept
        because the two questions are still different ones."""
        assert kvh < (1 << self.ARG0_KVH_BITS), (
            f"{op} kvhead {kvh} does not fit ARG0"
            f"[{self.ARG0_KVH_BITS - 1}:0]; layer_chan.sv reads it as a "
            f"{self.ARG0_KVH_BITS}-bit field, so a larger value selects the "
            f"wrong KV bank SILENTLY.")
        assert kvh <= self.KVH_HW_MAX, (
            f"{op} kvhead {kvh} exceeds the {self.KVH_HW_MAX + 1} KV banks "
            f"this build HAS.  rtl/layer_chan.sv banks "
            f"{{kv_slot, kvhead, k/v, t[8:0]}} into 8 URAM banks with "
            f"tcnt_bank[8][4]; a larger kvhead has no counter and no bank.")

    def dnsb(self, a_beta_base, a_dec_base):
        """Program the DNSB layer CSR: {a_dec_base[31:16], a_beta_base[15:0]}.

        ONE record per layer BODY, not per command (spec 4.3 S3).  The
        hardware forms `a_beta = a_beta_base + head` and
        `a_dec = a_dec_base + head` in the DNST decode.

        THE LAYOUT-AUTHORITY ASSERT LIVES HERE, and it checks against the
        WRITER.  `self.gate_dst` is the dst the GATE command actually
        carried — GATE is what POPULATES beta|decay, so it is the authority
        (spec 4.3 S3).  A self-consistency assert ("the a_dec I emitted
        equals the a_dec_base I programmed") passes while BOTH SIDES ARE
        WRONG and would have sailed straight through the `GD + 16 + h`
        aliasing G2a fixed, because base and pointer derive from the same
        literal.  Comparing the reader's base against the writer's tile is
        what makes a perturbation of the SCA map FIRE — that is G3's
        negative control (evidence/qwen9b/g3/isa_bits.py --dnst-map)."""
        a_beta_base = enc_isa_saddr(a_beta_base)
        a_dec_base = enc_isa_saddr(a_dec_base)
        if self.gate_dst is not None:
            assert (a_beta_base == self.gate_dst
                    and a_dec_base == self.gate_dst + LR.LNH), (
                f"DNSB programs a_beta_base={a_beta_base} / "
                f"a_dec_base={a_dec_base}, but the GATE command that WRITES "
                f"beta|decay put them at {self.gate_dst}.."
                f"{self.gate_dst + 2 * LR.LNH - 1} (LNH={LR.LNH}), i.e. beta "
                f"at {self.gate_dst} and decay at "
                f"{self.gate_dst + LR.LNH}.  The SCA tile map is the layout "
                f"authority and the reader has desynced from the writer — "
                f"this is the wall-17 defect class, where every head reads "
                f"the wrong word and nothing reports it.")
        self.dnsb_bases = (a_beta_base, a_dec_base)
        print(f"B {(a_dec_base << 16) | a_beta_base:08x}", file=self.f)
        if self.seq is not None:
            self.seq.on_dnsb(a_beta_base, a_dec_base)

    def dnst(self, head, src_q, src_k, src_v, a_dec, a_beta, dst):
        # S3: the cold-slot fence FIRST, before any other refusal, so the
        # emitter's answer to "compute on a slot no SLD loaded" is the
        # hardware's (E_DMA_COLD, B15.4) and not some later assert.
        self._require_warm(K_DN, self.dn_slot, "DNST")
        # ARG0 is {spare[31:5], head[4:0]} — 5 bits used of 32.  The two
        # scalar pointers are NOT in the arg words at all: they come from
        # the DNSB CSR as base+head (spec 4.3 S3, SEQ_ISA v2.0).
        a_dec, a_beta = enc_isa_saddr(a_dec), enc_isa_saddr(a_beta)
        assert 0 <= head <= self.DNST_HEAD_MAX, (
            f"DNST head {head} outside 0..{self.DNST_HEAD_MAX} (LNH="
            f"{LR.LNH})")
        assert head < (1 << self.ARG0_HEAD_BITS), (
            f"DNST head {head} does not fit ARG0[{self.ARG0_HEAD_BITS - 1}:0]; "
            f"layer_chan.sv reads dn_head <= arg0[4:0].  Widening this field "
            f"needs the RTL slice to move with it, not a host patch.")
        assert self.dnsb_bases is not None, (
            "DNST before any DNSB: SEQ_ISA v2.0 reads a_beta/a_dec from the "
            "DNSB layer CSR, so a body must program it before its first "
            "DNST or the hardware uses whatever the last body left there")
        b_base, d_base = self.dnsb_bases
        assert a_beta == b_base + head and a_dec == d_base + head, (
            f"DNST head {head} names a_beta={a_beta} / a_dec={a_dec}, but "
            f"the DNSB CSR this stream programmed is "
            f"(a_beta_base={b_base}, a_dec_base={d_base}), so the hardware "
            f"would read ({b_base + head}, {d_base + head}).  The two "
            f"scalar pointers are AFFINE IN THE HEAD with stride 1 by "
            f"construction (spec 4.3 S3); a pointer that is not is a "
            f"different command than the one the RTL will run.")
        self.C(8, head, enc_a1(src_q, src_k), enc_a1(src_v, dst))
        dec = int(self.mem[a_dec])
        bet = int(self.mem[a_beta])
        q = self.mem[src_q:src_q + LR.LDK]
        k = self.mem[src_k:src_k + LR.LDK]
        v = self.mem[src_v:src_v + LR.LDV] << (S_F - QKV_F)
        Sh = rshr(self.S[self.dn_slot][head] * dec, GAT_F)
        kvm = rshr((Sh * k[:, None]).sum(axis=0), NRM_F)
        dlt = rshr((v - kvm) * bet, GAT_F)
        Sr = Sh + rshr(k[:, None] * dlt[None, :], NRM_F)
        Sh = clip16(Sr)
        if self.audit is not None:
            nsat = int((np.abs(Sr) > 32767).sum())
            self.audit["s_sat"] += nsat
            self.audit["s_writes"] += int(Sr.size)
            self.audit["s_absmax"] = max(self.audit["s_absmax"],
                                         int(np.abs(Sr).max()))
            if nsat:
                k = (self.dn_slot, head)
                self.audit["s_where"][k] = self.audit["s_where"].get(k, 0) + nsat
        o = rshr((Sh * q[:, None]).sum(axis=0), NRM_F)
        self.S[self.dn_slot][head] = Sh
        self.set_pairs(dst, o)

    def kvap(self, kvh, src_k, src_v, expbias=QKV_F):
        assert 0 <= kvh <= self.KVH_MAX, (
            f"KVAP kvhead {kvh} outside 0..{self.KVH_MAX} (NKV={_KVH})")
        self._kvh_isa(kvh, "KVAP")
        assert 0 <= expbias <= self.KVAP_EXPB_MAX, (
            f"KVAP expbias {expbias} does not fit ARG0[8:4] (layer_chan.sv "
            f"kv_expbias = arg0[8:4], {self.KVAP_EXPB_MAX} max)")
        self._require_warm(K_KV, self.kv_slot, "KVAP")
        tg = self._require_tag(kvh, "KVAP")
        self.C(9, kvh | (expbias << 4), enc_a1(src_k, src_v), 0)
        k8, ke = fp.dyn_quant_i8(self.mem[src_k:src_k + LR.HD])
        v8, ve = fp.dyn_quant_i8(self.mem[src_v:src_v + LR.HD])
        self.kc[self.kv_slot].append((k8.astype(I64), ke - expbias))
        self.vc[self.kv_slot].append((v8.astype(I64), ve - expbias))
        # the counter is indexed through the SLOT'S TAG, as the hardware
        # indexes `tcnt_bank` (spec A1.3), not through LAYER.kv_layer
        self.T[tg[0]][tg[1]] += 1

    def _kv_view(self, kvh):
        """(K rows, V rows, TCNT) as the ATTN command sees them: the CURRENT
        KV cache slot, whose kvhead identity is the slot's TAG (A1.3), and
        the counter that tag indexes."""
        tg = self._require_tag(kvh, "ATTN")
        T = int(self.T[tg[0]][tg[1]])
        kc, vc = self.kc[self.kv_slot], self.vc[self.kv_slot]
        assert len(kc) == T and len(vc) == T, (
            f"KV slot {self.kv_slot} holds {len(kc)}/{len(vc)} rows but "
            f"TCNT[{tg[0]}][{tg[1]}] is {T}")
        return kc, vc, T

    def _kv_img_view(self, layer, kvh):
        """The same triple read from the DDR IMAGE instead of a slot — the
        MODEL-ONLY path.  After an SLD the slot holds exactly these bytes,
        so the two views agree by construction; `_sdma_copy` is the one
        place that says how."""
        T = int(self.T[layer][kvh])
        out = []
        for kv in (0, 1):
            blk = self.img.get((K_KV, layer, (kvh << 1) | kv), _KV_BLOCK)
            rows = blk[:T * LR.HD].view(np.int8).reshape(T, LR.HD)
            exps = blk[_KV_EXPOFF:_KV_EXPOFF + T].view(np.int8)
            out.append([(rows[t].astype(I64), int(exps[t]))
                        for t in range(T)])
        return out[0], out[1], T

    def attn_peek_img(self, layer, kvh, src_q, src_k, src_v, expbias=QKV_F):
        """`_attn_acc` for (layer, kvhead) READ FROM THE DDR IMAGE, with the
        row KVAP is ABOUT to append included.  Emits nothing, mutates
        nothing.

        WHY IT EXISTS (spec 6.2).  The gated-attention block-float shift
        `k_a` is ONE shift for the whole token, so `attn_token` must
        evaluate every query head before it emits the first command — but
        with TWO KV cache slots the four kvheads of an attention layer are
        never resident at once.  The DDR image holds every block, and after
        an SLD the slot holds exactly the image's bytes, so this reads the
        same numbers the emitted ATTN will."""
        kc, vc, T = self._kv_img_view(layer, kvh)
        k8, ke = fp.dyn_quant_i8(self.mem[src_k:src_k + LR.HD])
        v8, ve = fp.dyn_quant_i8(self.mem[src_v:src_v + LR.HD])
        kc = kc + [(k8.astype(I64), ke - expbias)]
        vc = vc + [(v8.astype(I64), ve - expbias)]
        return self._attn_acc(kc, vc, T + 1,
                              self.mem[src_q:src_q + LR.HD])

    def _attn_acc(self, kcache, vcache, T, qn):
        """The ATTN command's numeric core: score -> softmax -> P*V.

        Pure: reads the (K, V, TCNT) triple it is handed and mutates
        nothing, so the same arithmetic serves the emitted command (the
        slot, `_kv_view`) and the block-float peek (the DDR image,
        `_kv_img_view`)."""
        SC = int(round((1 << 15) / np.sqrt(LR.HD)))
        sc = np.zeros(T, dtype=I64)
        for t in range(T):
            k8, ke = kcache[t]
            dot = int((qn * k8).sum())
            s_ = rshr(I64(dot) * SC, 15)
            f = QKV_F - ke - 16
            sc[t] = rshr(I64(int(s_)), f) if f >= 0 else int(s_) << (-f)
        mx = int(sc.max())
        es = np.array([fp.exp_neg_q(int(min(int(sc[t]) - mx, 0)))
                       for t in range(T)], dtype=I64)
        r, re = fp.recip_q(int(es.sum()), 30)
        p = np.clip(rshr(es * r, 30 - re + 15), 0, 1 << 15)
        acc = np.zeros(LR.HD, dtype=I64)
        for t in range(T):
            v8, ve = vcache[t]
            term = I64(int(p[t])) * v8
            sh = 15 - ve - QKV_F
            acc += rshr(term, sh) if sh >= 0 else term << (-sh)
        return acc

    def attn(self, kvh, src_q, dst):
        assert 0 <= kvh <= self.KVH_MAX, (
            f"ATTN kvhead {kvh} outside 0..{self.KVH_MAX} (NKV={_KVH})")
        self._kvh_isa(kvh, "ATTN")
        self._require_warm(K_KV, self.kv_slot, "ATTN")
        self._require_tag(kvh, "ATTN")
        self.C(10, kvh, enc_a1(src_q, dst), 0)
        kc, vc, T = self._kv_view(kvh)
        self.set_pairs(dst, self._attn_acc(kc, vc, T,
                                           self.mem[src_q:src_q + LR.HD]))

    def attn_peek(self, kvh, src_q):
        """_attn_acc on the RESIDENT slot, emitting nothing."""
        kc, vc, T = self._kv_view(kvh)
        return self._attn_acc(kc, vc, T, self.mem[src_q:src_q + LR.HD])

    def sigm_peek(self, n, p0, srca):
        """ALU op 7 (SIGM16) evaluated without emitting."""
        x = rs_s(self.mem[srca:srca + n], p0)
        return np.array([fp.sigmoid_q(int(v)) for v in x], dtype=I64)

    # ALU's element count is ARG0[17:4] -> rtl/vec_alu.sv `cfg_len`, 14
    # bits since G3.1 (13 at R-c), so 16383 elements is the ceiling and the
    # 9B FFN of 12288 fits in ONE command.  There is NO 0-encodes-the-top
    # escape (unlike v1.7's VNW count): vec_alu compares `cfg_len == 1` and
    # loads `len_q <= cfg_len`, so 0 would run zero elements.
    #
    # The field was 12 bits and R-c found that the expensive way — the 2B
    # MLP DYNQ8 is FFN = 6144 elements, `6144 & 0xFFF` = 2048, and this
    # emitter produced arg0 = 0x18000 with the top bit outside the field.
    # Nothing downstream could see it: the .txt, the .seq and every python
    # golden had no 12-bit field, so they agreed with each other and only
    # the RTL ran the wrong length.  G3.1's 14th bit is arg0[17]; arg0[18]
    # is now p0[16] (the one relocation) and ARG0[31:19] is still spare.
    ALU_LEN_MAX = (1 << 14) - 1

    def alu(self, op, n, p0, srca, srcb, dst):
        assert 1 <= n <= self.ALU_LEN_MAX, (
            f"ALU op {op} count {n} does not fit ARG0[17:4] (max "
            f"{self.ALU_LEN_MAX}); rtl/vec_alu.sv cfg_len is 14 bits. "
            "Chunk the op if its semantics allow it — DYNQ8/DYNQ16 pick ONE "
            "shared exponent over the whole vector and CANNOT be chunked, so "
            "a longer one needs the field widened again (ARG0[31:19] is "
            "still spare) and rtl/vec_alu.sv cfg_len with it. "
            "ref/seq_model.py:_alu refuses such a stream on the reading "
            "side, so an artifact built before this check is caught too.")
        self.C(11, enc_alu_a0(op, n, p0), enc_a1(srca, srcb),
               enc_alu_a2(p0, dst))
        a = self.mem[srca:srca + n]
        b = self.mem[srcb:srcb + n]
        if op == 0:                                  # DYNQ8
            y, e = fp.dyn_quant_i8(a)
            self.mem[dst:dst + n] = y
            self.eout = e
            if self.audit is not None:
                self.audit["eout"][e] = self.audit["eout"].get(e, 0) + 1
        elif op == 1:                                # SHIFT32
            self.mem[dst:dst + n] = clip16(rs_s(self.pairs(srca, n), p0))
        elif op == 2:                                # SCALE
            self.mem[dst:dst + n] = clip16(rshr(a * p0, 15))
        elif op == 3:                                # EMUL
            self.mem[dst:dst + n] = clip16(rshr(a * b, p0))
        elif op == 4:                                # ADD
            self.mem[dst:dst + n] = clip16(a + b)
        elif op == 5:                                # SILU16
            x = rs_s(a, p0)
            self.mem[dst:dst + n] = clip16(
                np.array([fp.silu_q(int(v)) for v in x], dtype=I64))
        elif op == 6:                                # SILU32
            x = np.clip(rs_s(self.pairs(srca, n), p0),
                        -(1 << 20), (1 << 20) - 1)
            self.mem[dst:dst + n] = clip16(
                np.array([fp.silu_q(int(v)) for v in x], dtype=I64))
        elif op == 7:                                # SIGM16
            x = rs_s(a, p0)
            self.mem[dst:dst + n] = np.array(
                [fp.sigmoid_q(int(v)) for v in x], dtype=I64)
        elif op == 8:                                # EMUL32
            self.mem[dst:dst + n] = clip16(rshr(self.pairs(srca, n) * b, p0))
        elif op == 9:                                # SHIFT32W
            y = np.clip(rs_s(self.pairs(srca, n), p0),
                        -(1 << 31), (1 << 31) - 1)
            self.set_pairs(dst, y)
        elif op == 10:                               # AMAX32 (running)
            v = self.pairs(srca, n)
            if p0 & 1:
                self.am_g, self.am_first = 0, True
            for e in v:
                if self.am_first or int(e) > self.am_val:
                    self.am_val, self.am_idx = int(e), self.am_g
                    self.am_first = False
                self.am_first = False
                self.am_g += 1
        else:
            raise ValueError(op)
        # int8/int16 writers: audit the words just written (op 9 writes
        # int32 pairs, op 10 writes nothing, op 0 writes int8 by construction)
        if self.audit is not None and op not in (0, 9, 10):
            self._aud(f"alu{op}", self.mem[dst:dst + n])

    def dnz(self, head):
        # SAME slice DNST's head uses — layer_chan.sv dispatches both through
        # `dn_head <= arg0[3:0]` — so it needs BOTH of DNST's guards.
        #
        # G2a review B1: it had only the first.  When `DNST_HEAD_MAX` went
        # 15 -> 31 for LNH=32, `dnz` silently started ACCEPTING heads 16..31
        # and `self.C(12, head, ...)` handed them to a 4-bit RTL field, so
        # head 16 aliased onto head 0.  The six callers all walked
        # `range(LR.LNH)` to zero every head at preamble time
        # (`sw/infer.py:766`, `ref/gen_model_script.py:573`,
        # `ref/gen_token_script.py:201`, `ref/gen_chain_script.py:111`,
        # `ref/seq_chat.py:1419`, and this file's own `main`), so at 9B that
        # is "heads 0-15 zeroed TWICE, heads 16-31 never" — a DeltaNet state
        # left holding whatever the last token wrote, silently.  Exactly the
        # class the ARG0 split exists for; `dnst` got the second guard and
        # this did not, which is the hole.
        #
        # CLASS B, 2026-09-04 (S3, base 07eea51).  Those five coordinates
        # are kept at their BASE numbers because the code they name is
        # RETIRED, not moved: the 768-DNZ preamble is gone (spec 6.4, the
        # host writes the DN region) and every one of the five call sites is
        # now `GLS.sched_preamble`.  DNZ itself survives for TESTS only
        # (spec 5.5) and warms the slot it zeroes, so the guards below are
        # still the ones the ARG0 split needs.
        assert 0 <= head <= self.DNST_HEAD_MAX, (
            f"DNZ head {head} outside 0..{self.DNST_HEAD_MAX} (LNH="
            f"{LR.LNH})")
        assert head < (1 << self.ARG0_HEAD_BITS), (
            f"DNZ head {head} does not fit ARG0"
            f"[{self.ARG0_HEAD_BITS - 1}:0]; layer_chan.sv reads "
            f"dn_head <= arg0[4:0] for DNZ exactly as it does for DNST, so a "
            f"larger value ALIASES onto head "
            f"{head & ((1 << self.ARG0_HEAD_BITS) - 1)} and leaves head "
            f"{head} un-zeroed.")
        self.C(12, head, 0, 0)
        self.S[self.dn_slot][head] = 0
        # spec 5.5: DNZ WRITES the slot, so it warms it (it counts as a load
        # for F1) and is legal on a cold slot.  Tests only: the steady-state
        # program zeroes nothing, the host writes the region.
        self.warm[K_DN][self.dn_slot] = True

    # ---------------- stage 4: embedding + argmax ----------------
    def embed(self, tokid, dst, n):
        """M record: executor looks up row tokid of the embedding table
        (TB: from <prefix>.emb.bin; HW: c2h read from board DDR) and
        writes n words at dst. Model mirrors from self.emb."""
        print(f"M {tokid:x} {dst:x} {n:x}", file=self.f)
        self.mem[dst:dst + n] = self.emb[tokid][:n]
        self._aud("embed", self.mem[dst:dst + n])
        if self.seq is not None:
            self.seq.on_embed(tokid, dst, n)

    def amax(self, n, src, fresh):
        """ALU op 10 AMAX32 over n {lo,hi} pairs at src; fresh resets the
        running scan. Strictly-greater update -> first max wins."""
        self.alu(10, n, 1 if fresh else 0, src, 0, 0)

    def A(self):
        """Assert the AMAXI/AMAXV CSRs against the model's running scan."""
        print(f"A {self.am_idx:x} {int(self.am_val) & 0xFFFFFFFF:x}",
              file=self.f)
        self.nchk_a = getattr(self, "nchk_a", 0) + 1
        if self.seq is not None:
            self.seq.on_amaxl(self.am_idx, self.am_val)

    # ---------------- host matvec round-trip ----------------
    def matvec(self, qw, x8_addr, n_in, rowchunk=None):
        """Assert the on-chip x8/EOUT, then compute raw y32 host-side
        from those asserted values. Caller stages + dequants. Emits a V
        record so the hardware host can run the REAL matvec engine on
        weight image wid and verify it reproduces these y32.

        rowchunk: evaluate matvec_y32 in row blocks (matvec_y32 is exactly
        row-separable, so this is bit-identical) — needed for the full-vocab
        LM head, whose one-shot int64 temporary is 2 GiB.

        WEIGHT WIDTH (V5): the quantized dict says which one it is, through
        `layer_fixed.qw_codes` — `{"w8", ...}` (int8 codes in [-127,127])
        goes to `matvec_y32_w8`, `{"w4", ...}` to `matvec_y32`.  Nothing
        else about the record, the y32 assertion or the audit changes: `e`
        and `sh` mean the same thing in both widths."""
        k = id(qw)
        if k not in self.wids:
            self.wids[k] = (len(self.wids), qw)
        wid = self.wids[k][0]
        self.R(x8_addr, n_in)                      # assert on-chip x8
        self.E()                                   # assert on-chip e_x
        x8 = np.asarray(self.mem[x8_addr:x8_addr + n_in]).astype(np.int8)
        wcodes, w8 = LF.qw_codes(qw)
        mv = matvec_y32_w8 if w8 else matvec_y32
        nrows = wcodes.shape[0]
        g = int(qw.get("g", 128))          # v2 group size (absent == 128)
        if rowchunk is None or rowchunk >= nrows:
            y32 = np.asarray(mv(wcodes, qw["m"], qw["sh"], x8, g=g),
                             dtype=I64)
        else:
            parts = []
            for r0 in range(0, nrows, rowchunk):
                r1 = min(r0 + rowchunk, nrows)
                parts.append(np.asarray(
                    mv(wcodes[r0:r1], qw["m"][r0:r1], qw["sh"], x8, g=g),
                    dtype=I64))
            y32 = np.concatenate(parts)
        print(f"V {wid:x} {x8_addr:x} {n_in:x} {len(y32):x}", file=self.f)
        self.f.write("".join(f"{int(v) & 0xFFFFFFFF:08x}\n" for v in y32))
        if self.seq is not None:
            self.seq.on_matvec(wid, qw, x8_addr, n_in, y32)
        if self.audit is not None:
            tag = f"{nrows}x{wcodes.shape[1]}"
            st = self.audit["y32"].setdefault(tag, [0, 0])
            st[0] = max(st[0], int(np.abs(y32).max()))
            st[1] += 1
        return y32, self.eout

    def dump_weights(self, prefix, emb_row_bytes=None, rs_f=None):
        """Pack each registered matrix's DDR image + manifest.

        Manifest fields (per wid) — the host tools derive EVERYTHING from
        these, so the v2 group size travels with the image:
          nrows/k     matrix shape
          ng          WEIGHT-beat count = K//128, in BOTH group modes (this
                      is the SHAPE CSR ng field; its meaning did not change)
                      — W4 ONLY.  In W8 (SHAPE bit 29) ng is still K//128
                      but it counts ng UNITS, and the row streams 2*ng
                      weight beats (w4a8_ref.row_beats8).
          nbeats      total 64B beats of the whole image = nrows*stride/64,
                      i.e. it already includes the extra g=64 scale beat
          stride      row stride in bytes (w4a8_ref.row_stride/row_stride8)
          g           group size — EMITTED ONLY WHEN != 128, so every g=128
                      manifest stays byte-identical to the pre-v2 tree.
                      Consumers must read it as `int(m.get("g", 128))`.
          w8          weight width — EMITTED ONLY WHEN TRUE (V5), for the
                      same reason `g` is: every W4 manifest ever written
                      stays byte-identical.  Consumers read it as
                      `bool(m.get("w8", False))`; `ref/seq_format.py`'s
                      `plan_weights_from_wids` (the live-tensor twin of
                      this function) already emits it the same way, and
                      `sw/hwmap.plan_weights` re-derives the row law from
                      it rather than trusting `stride`.

        WHICH WIDTH an image is comes from `layer_fixed.qw_codes` — the one
        place that knows `"w4"` means nibbles and `"w8"` means bytes — so a
        dict can never be packed with the wrong packer by a key typo here.

        NON-WID KEYS — there are now TWO, and both are CALLER-GATED for the
        same reason.  A manifest is a wid -> image map plus a small amount of
        artifact-level metadata; every consumer that iterates wids must split
        the metadata off first (sw/hwmap.split_manifest), and any key emitted
        UNCONDITIONALLY would move bytes in every manifest ever written.  So
        both are `None`-defaulted keyword arguments emitted only when the
        caller passes them.  Note the contrast with the per-wid `g`/`w8`
        keys, which are VALUE-gated (`g` when != 128, `w8` when true) — that
        works for a wid entry, where the reader has a documented default for
        a missing key, and is the wrong shape for artifact metadata.

          `emb_row_bytes` (R-b): the byte stride of a `<prefix>.emb.bin` row
            = 2*H, which the host writes into seq_unit's EMBLOG2 CSR before
            any EMB record.  Passed only by the generator that also writes an
            .emb.bin.  Readers default it to 2048 when absent.

          `rs_f` (G2a, spec 4.4): the residual binary point this artifact was
            emitted with.  `RS_F` used to be one module-level constant shared
            by every geometry, so moving it moved every emitted byte at 0.8B
            and 2B as well; carrying it in the manifest makes it MODEL-SELECTED
            instead — 0.8B/2B keep 8 and keep their byte-lock while a 9B
            artifact may carry a different value.  The precedent is
            `res_scale`, a generator choice recorded in the artifact and read
            back by the host.  Readers default it to 8 when absent.  (A1.8:
            the shipped value is 8; this is the plumbing, not a change of
            value.)  NOT to be confused with `sw/head_cache.py`'s per-image
            `"rs_f"`, which lives INSIDE a spec dict describing one weight
            image — see that file's note; the two scopes are disjoint and
            both are documented at their sites.
        """
        man = {}
        for wid, qw in sorted(self.wids.values(), key=lambda t: t[0]):
            g = int(qw.get("g", 128))
            wcodes, w8 = LF.qw_codes(qw)
            if w8 and g != 128:
                raise SystemExit(
                    f"wid {wid}: W8 + g{g} is not a defined row format (the "
                    "W8 wire format is g128-cadence only — sw/hwmap."
                    "shape_word and rtl/matvec_engine.sv both refuse it)")
            pack = pack_ddr_rows8 if w8 else pack_ddr_rows
            img, stride = pack(wcodes, qw["m"], g=g)
            fn = f"{prefix}_w{wid}.bin"
            with open(fn, "wb") as wf:
                wf.write(img)
            nrows, K = wcodes.shape
            man[wid] = {"file": fn.split("/")[-1], "nrows": nrows, "k": K,
                        "ng": K // 128, "sh": qw["sh"], "e": qw["e"],
                        "nbeats": len(img) // 64, "stride": stride}
            if g != 128:
                man[wid]["g"] = g
            if w8:
                man[wid]["w8"] = True
        nw = len(man)
        if emb_row_bytes is not None:
            man["emb_row_bytes"] = int(emb_row_bytes)
        if rs_f is not None:
            man["rs_f"] = int(rs_f)
        else:
            # G2a review B6 — THE EMIT/CONSUME TIE.  Withholding `rs_f` is
            # not a free choice: a reader that finds no key answers
            # `RS_F_MANIFEST_DEFAULT`.  So withholding is valid ONLY when the
            # value this artifact was actually emitted with IS that default.
            #
            # Without this the two halves could disagree silently and the
            # failure is not subtle: the head dequant exponent is
            # `e + sh - 15 + e_x - rs_f`, so an artifact emitted at
            # `FABLE5_RS_F=7` and read as 8 dequants every logit by a factor
            # of TWO.  The byte-lock cannot catch it — it compares a 2B
            # artifact against a 2B gold, both emitted under the same env —
            # and no host assert downstream can, because the manifest simply
            # does not carry the contradicting evidence.  It has to refuse
            # HERE, where the key is dropped.
            assert RS_F == RS_F_MANIFEST_DEFAULT, (
                f"refusing to write a manifest with no `rs_f` key while "
                f"RS_F is {RS_F}: a reader defaults a missing key to "
                f"{RS_F_MANIFEST_DEFAULT}, so this artifact would be "
                f"dequantized by 2^{RS_F_MANIFEST_DEFAULT - RS_F} times the "
                f"right scale, silently.  Pass rs_f= explicitly (a 9B "
                f"artifact does), or emit at the default.")
        st = self.dump_state(prefix)
        if st is not None:
            man["state"] = st[0]
            man["conv_images"] = st[1]
        with open(f"{prefix}.weights.json", "w") as jf:
            json.dump(man, jf, indent=1)
        return nw

    def dump_state(self, prefix):
        """Write the DDR state region's INITIAL image and the conv images
        the host uploads, and return (state-plan, conv-image-file-list).

        `<prefix>.state.bin` is the WHOLE region as it stands before the
        first launch -- DN zero, KV zero, conv blocks holding the taps
        `seed_conv` put there.  It is written SPARSE (seek past the zeros),
        so 155 MiB of region costs a few MiB on disk; the chip TB maps it
        read-only behind its write window and `ref/seq_model.StateRegion`
        loads it.  `<prefix>_cv<L>.bin` is the same conv block on its own,
        one file per DeltaNet layer, because THAT is what the host uploads
        (spec 7.1); the DN and KV regions are a memset, not an image.

        WHERE THE REGION SITS.  The base is the LAST channel's
        `STATE_MIN_BASE` (sw/hwmap): above the weight pack, which
        `plan_weights` asserts ends below `EMB_BASE`, and above the 485 MiB
        embedding table that shares channel 0.  It is derived from the
        stream's CHANNEL COUNT alone, so the emitter, the reference model,
        the chip TB and the host all name the same address without any of
        them re-deriving the pack.

        Returns None only when the program touched no state at all.  This
        is NOT gated on `BYTELOCKED_TAGS` the way `rs_f` is, and the reason
        is the opposite of that key's: the v2.1 schedule is UNCONDITIONAL,
        so a stream emitted at ANY geometry carries SLD/SST and would be
        unreplayable without a region.  The frozen 0.8B/2B ARTIFACTS are not
        regenerated by this plan and their byte-lock was already spent by
        G3.1 (evidence/qwen9b/g4/G4A_REPLAY.md 10.6)."""
        if not self.img.blocks:
            return None
        import hwmap as HW
        plan = dict(self.state_plan)
        base = {K_DN: plan["dn"], K_KV: plan["kv"], K_CV: plan["cv"]}
        stride = {K_DN: HW.STATE_DN_LAYER, K_KV: HW.STATE_KV_STRIDE,
                  K_CV: HW.STATE_CV_STRIDE}

        def _write(path, blocks):
            """Write the region image and hash THE FILE'S BYTES.

            S3 fix round 1, M6: the first cut hashed the block keys and the
            block contents, which is a digest of the emitter's data
            structure and NOT of the artifact.  The host has to be able to
            verify what it is about to upload (spec 7.2, "the manifest
            carries the region's sha"), and it can only hash the file.
            """
            with open(path, "wb") as f:
                f.truncate(plan["end"] - plan["dn"])
                for key in sorted(blocks):
                    kind, layer, head = key
                    idx = (layer if kind != K_KV
                           else ((layer * _KVH) + (head >> 1)) * 2
                           + (head & 1))
                    f.seek(base[kind] + idx * stride[kind] - plan["dn"])
                    f.write(blocks[key].tobytes())
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 22), b""):
                    h.update(chunk)
            return h.hexdigest()

        init = self.img.blocks if self.img_init is None else self.img_init
        plan["sha256"] = _write(f"{prefix}.state.bin", init)
        # THE EMITTER'S FINAL IMAGE, for the SEQ gate's STATE comparison.
        # It is written by StateImage and read back against
        # ref/seq_model.StateRegion, which serialises the same B15.1 layouts
        # from its own code -- that comparison IS the lockstep spec 6.5 asks
        # for, and it is only worth having because the two were written
        # twice.
        plan["final_sha256"] = _write(f"{prefix}.state_final.bin",
                                      self.img.blocks)
        cvs = []
        for key in sorted(init):
            kind, layer, head = key
            if kind != K_CV:
                continue
            fn = f"{prefix}_cv{layer}.bin"
            init[key].tofile(fn)
            cvs.append({"layer": int(layer), "file": fn.split("/")[-1],
                        "bytes": int(HW.STATE_CV_STRIDE)})
        return plan, cvs

    def shift_for(self, qw, e_x, in_f, out_f):
        return (15 - qw["e"] - qw["sh"]) - e_x + in_f - out_f

    def inject_dequant(self, y32, p0, stage, dst, op=1):
        """W32 + SHIFT32(op1)/SHIFT32W(op9)/SILU32(op6) in <=2048 chunks."""
        n = len(y32)
        c = 0
        while c < n:
            m = min(2048, n - c)
            self.W32(stage, y32[c:c + m])
            if op == 9:
                self.alu(9, m, p0, stage, 0, dst + 2 * c)
            else:
                self.alu(op, m, p0, stage, 0, dst + c)
            c += m


def require_supported_geometry(where="gen_layer_script"):
    """ASSERT THE ALGEBRA this generator now implements (G2a).

    HISTORY.  Added 2026-08-26 (Track L review, finding D7) as a REFUSAL:
    this file was written for 0.8B/2B, where `linear_num_value_heads ==
    linear_num_key_heads == 16`, and it hard-coded that equality in two
    places that produced a WRONG ANSWER rather than an exception:

      * `dn_token`'s per-head loop (the `for h in range(LR.LNH)` in
        `dn_token`, cited by symbol because a line range in a file this
        size is stale within a commit or two — D-CITE)
        walked `for h in range(LR.LNH)` reading `q_src = QKV + h * LR.LDK`.
        The packed QKV block is [q: LKD][k: LKD][v: LVD] with
        LKD = LNKH*LDK, so at 4B/9B (LNH 32, LNKH 16) every h >= 16 walked
        q_src straight into the K region and k_src into V, silently.
      * the DN/KV state banks were fixed at 18 and 6 slots.  4B and 9B are
        32 layers = 24 DeltaNet + 8 full-attention, so 24 > 18 overflowed
        the bank arrays.

    G2a GENERALIZED BOTH.  Value head h now reads key head `h // VREP`, the
    same law `ref/layer_ref.py:223-225` and `ref/layer_fixed.py` already
    implement, and the banks are `_DN_SLOTS` / `_KV_SLOTS` / `_KVH`.  So this
    function is no longer a refusal on head counts — it is the ASSERTION of
    the new algebra, which is what spec 7.1 asks for.

    WHAT STILL REFUSES, and it is not here.  G3.1 lifted every ARG FIELD
    ceiling to SEQ_ISA v2.0's widths — `enc_isa_saddr` to 65,536,
    `Mach.ARG0_HEAD_BITS` to 5, `Mach.CONV_FIELD_MAX` and `Mach.ALU_LEN_MAX`
    to 2**14-1, `Mach.VNW_ISA_MAX` to 4096 — because a field the RTL decodes
    at 14 bits and the emitter refuses at 13 is a self-contradictory ISA.
    What is left are DATAPATH bounds the RTL cannot yet honour, and they
    stay where the RTL is: `Mach.ARG0_KVH_BITS` (the RTL still decodes
    arg0[0] — Task 10) and the conv bank's channel capacity at
    CONV_DIM = 8192 (Task 10).  `Mach.VNW_HW_MAX` was one of them and is
    NOT any more: G3.2 (Task 8) widened `rtl/vecnorm_unit.sv` to N = 4096,
    so the bound still exists and is still a DATAPATH bound, but it now
    sits at 4096 and refuses nothing a 9B geometry asks for.
    """
    assert LR.LNH % LR.LNKH == 0 and LR.VREP == LR.LNH // LR.LNKH, (
        f"({where}) LNH={LR.LNH} is not a whole multiple of LNKH={LR.LNKH}; "
        f"the VREP algebra (value head h reads key head h // VREP) does not "
        f"hold and the QKV slicing would be wrong, not slow.")
    assert LR.LKD == LR.LNKH * LR.LDK and LR.LVD == LR.LNH * LR.LDV, (
        f"({where}) the packed QKV block is [q:LKD][k:LKD][v:LVD] with "
        f"LKD = LNKH*LDK and LVD = LNH*LDV; layer_ref reports LKD={LR.LKD}, "
        f"LVD={LR.LVD}, which contradicts LNKH={LR.LNKH} LDK={LR.LDK} "
        f"LNH={LR.LNH} LDV={LR.LDV}.")
    lt = LR.CFG.get("layer_types") or []
    n_dn = sum(1 for t in lt if t == "linear_attention")
    n_kv = sum(1 for t in lt if t == "full_attention")
    # S3: the bound is no longer the CACHE (two slots per kind, always),
    # it is the DDR IMAGE's extent — which is B15.1's 5-bit `layer` field
    # and sw/hwmap's STATE_*_BLOCKS.  A model with more DeltaNet layers
    # than the image has blocks cannot be addressed by an SLD at all.
    if n_dn > _DN_LAYERS or n_kv > _KV_LAYERS or LR.NKV > _KVH:
        raise SystemExit(
            f"REFUSING ({where}): FABLE5_MODEL={MS.TAG} has {n_dn} DeltaNet "
            f"and {n_kv} full-attention layers with NKV={LR.NKV}, but the "
            f"DDR state image holds {_DN_LAYERS} DN/conv blocks, "
            f"{_KV_LAYERS} attention layers and {_KVH} KV heads per layer "
            f"(SEQ_ISA v2.1 B15.1's `layer` field, sw/hwmap.STATE_*_BLOCKS "
            f"and Mach.__init__).\n"
            f"  Widening the image is migration work, not a host patch.")


# ======================================================================
# THE SCHEDULE (spec 2026-09-04-qwen35-9b-state-spill-design.md 6.1-6.3).
# ONE definition, because five emitters need it: this file's `main`,
# ref/gen_model_script.py, ref/gen_token_script.py, ref/gen_chain_script.py
# and the two host tools (ref/seq_chat.py, sw/infer.py).  The compute half
# stays in dn_token / attn_token; these emit only the transfers.
# ======================================================================
def sched_kv_prefetch(layer_types):
    """Per position, the ATTENTION-LAYER index whose kvhead 0 the layer at
    that position must prefetch: the index of the NEXT layer when the next
    layer is a full-attention one.  The stack repeats every token, so the
    LAST position's `next` is position 0 -- which is what makes the first
    attention layer of a token resident without a preamble SLD (6.1's last
    sentence)."""
    n = len(layer_types)
    a_of, a = {}, 0
    for i, lt in enumerate(layer_types):
        if lt == "full_attention":
            a_of[i] = a
            a += 1
    return [a_of.get((i + 1) % n) for i in range(n)]


def sched_dn_pair(M, L, n_dn, a_next=None):
    """6.1: write back DeltaNet layer L-1, prefetch L+1, and -- when the
    NEXT layer is an attention layer -- both halves of its first kvhead."""
    if L > 0:
        M.sst(K_DN, (L - 1) % 2, L - 1)
    if L + 1 < n_dn:
        M.sld(K_DN, (L + 1) % 2, L + 1)
    if a_next is not None:
        M.sld(K_KV, 0, a_next, 0)
        M.sld(K_KV, 0, a_next, 1)


def sched_cv_pair(M, L, n_dn):
    """6.3: the conv block's own SST/SLD pair, one per DeltaNet layer."""
    if L > 0:
        M.sst(K_CV, (L - 1) % 2, L - 1)
    if L + 1 < n_dn:
        M.sld(K_CV, (L + 1) % 2, L + 1)


def sched_preamble(M, layer_types):
    """6.4: the TCNT resets and the first SLDs of a session.

    The 768 DNZ and the 120 CONVW the pre-S3 preamble emitted are RETIRED:
    the host writes zeros to the DN region and the conv images to the conv
    region during upload (spec 2 'Initial contents', 7.1), and
    `evidence/qwen9b/s3/preamble_equiv.py` is the guard that the bytes are
    the same ones.  The first attention layer's kvhead 0 is prefetched HERE
    only when no DeltaNet layer precedes it in the stack; otherwise that
    layer's own 6.1 pair does it and this SLD would be redundant."""
    M.layer(0, 0, 0, 0)
    M.sbase()                        # the three region base CSRs (B15.3)
    M.Treset()                       # ALL _KV_LAYERS x _KVH counters (A1.3)
    M.sld(K_DN, 0, 0)
    M.sld(K_CV, 0, 0)
    if layer_types and layer_types[0] == "full_attention":
        M.sld(K_KV, 0, 0, 0)
        M.sld(K_KV, 0, 0, 1)


def sched_attn_layer(M, A, nkv, dn_slot, cv_slot, body):
    """6.2's per-kvhead loop for attention layer `A`.

    Prefetch the next kvhead into the other slot, select this one, run
    `body(kvh)` -- the KVAP and the kvhead's query heads -- and store the
    slot back.  The FIRST kvhead's slot was loaded by the preceding DN
    layer's pair (or by the preamble), which is why there is no SLD for
    kvh = 0.  The body is a callback so that the SCHEDULE lives in one
    place and can be counted without running the arithmetic
    (evidence/qwen9b/s3/sdma_census.py)."""
    for kvh in range(nkv):
        if kvh + 1 < nkv:
            M.sld(K_KV, (kvh + 1) % 2, A, (kvh + 1) << 1)
            M.sld(K_KV, (kvh + 1) % 2, A, ((kvh + 1) << 1) | 1)
        M.layer(dn_slot, kvh % 2, cv_slot, A)
        body(kvh)
        M.sst(K_KV, kvh % 2, A, kvh << 1)
        M.sst(K_KV, kvh % 2, A, (kvh << 1) | 1)


def sched_token_end(M, n_dn):
    """6.1's last sentence: the last DeltaNet layer of a token stores itself
    and layer 0 of the NEXT token is loaded in the same pair."""
    last = n_dn - 1
    M.sst(K_DN, last % 2, last)
    M.sst(K_CV, last % 2, last)
    M.sld(K_DN, 0, 0)
    M.sld(K_CV, 0, 0)


def dn_token(M, qd, ln1, ln2, qm, gold_x):
    """DeltaNet token body.  Region bases come from the module-level map
    (derived from LR.H / LR.FFN); at 0.8B they are the frozen literals
    QKV=8192, Z16=14336, B16=3072 ... NH=3936.

    REFUSES up front on a geometry this file cannot encode -- see
    `require_supported_geometry`.  0.8B and 2B pass unchanged."""
    require_supported_geometry("dn_token")
    QKV, Z16 = DN_QKV, DN_Z16
    OUTSTG, OUTDST = DN_OUTSTG, DN_OUTDST

    # ln1 norm
    M.W(STG, ln1)
    M.vnw_(STG, H)
    M.vn(0, H, RS_F, RS_F, X0, XN)
    M.alu(0, H, 0, XN, 0, X8)
    # 4 matvecs off xn
    y, ex = M.matvec(qd["in_qkv"], X8, H)
    M.inject_dequant(y, M.shift_for(qd["in_qkv"], ex, RS_F, RS_F), STG, QKV)
    y, _ = M.matvec(qd["in_z"], X8, H)
    M.inject_dequant(y, M.shift_for(qd["in_z"], ex, RS_F, QKV_F), STG, Z16)
    y, _ = M.matvec(qd["in_b"], X8, H)
    M.inject_dequant(y, M.shift_for(qd["in_b"], ex, RS_F, 12), STG, B16)
    y, _ = M.matvec(qd["in_a"], X8, H)
    M.inject_dequant(y, M.shift_for(qd["in_a"], ex, RS_F, 12), STG, A16)
    # conv + silu + requant to QKV_F (in place)
    M.conv(0, LR.CONV_DIM, QKV, QKV)
    for c in range(0, LR.CONV_DIM, CHUNK):
        n = min(CHUNK, LR.CONV_DIM - c)
        M.alu(2, n, 1 << (15 - (12 - QKV_F)), QKV + c, 0, QKV + c)
    M.R(QKV, 256)
    # gates (A/dt staged each token; cheap and keeps staging free).
    #
    # G2a: A_q15 is 2*LNH words (int32 lo/hi pairs) and dt_bias is LNH, so
    # the as-built literals STG+32 / STG+64 are 0.8B sizes.  At LNH=32
    # A_q15 spans STG+0..63 and dt_bias sat at STG+32..63 — **A_q15
    # OVERWRITES dt_bias**, and `M.gate` would then read its own A values
    # back as dt_bias.  Derived, dt_bias moves to STG+2*LNH and norm_w above
    # both; `max(64, 3*LNH)` keeps the as-built 0.8B/2B offsets exactly.
    #
    # PRECISELY ONE PAIR COLLIDES, and an earlier revision of this comment
    # said three did.  norm_w at the old STG+64 was NEVER overwritten: A+dt
    # reach word 63 at LNH=32, one short of it.  The assert below is what
    # makes the real bound checkable instead of argued.
    DTB = STG + 2 * LR.LNH       # dt_bias staging, right above A_q15
    M.W_raw(STG, np.stack([qd["A_q15"] & 0xFFFF, qd["A_q15"] >> 16],
                          axis=1).reshape(-1))
    M.W(DTB, qd["dt_bias_q12"])
    M.gate(B16, A16, STG, DTB, GD)
    M.R(GD, 2 * LR.LNH)
    # ---- SEQ_ISA v2.0: the DNSB base pair, ONE record per layer body ----
    # `Mach.dnsb` carries the layout-authority assert: it compares the base
    # pair being programmed against the dst of the GATE command emitted two
    # lines above, which is the tile WRITER.  See its docstring for why a
    # self-consistency assert would prove nothing.
    M.dnsb(beta_base, decay_base)
    # per-head recurrence.  norm_w stays RESIDENT in scratch at NW: the
    # gated RMSNorm is an op-3 EMUL against it now, not a vecnorm, so no
    # vnw_ load is needed (and none must be emitted — vnw still holds ln1,
    # which nothing between here and mlp_block reads).
    NW = STG + max(64, 3 * LR.LNH)
    # A REAL bound, not a restatement.  `NW >= DTB + LNH` is implied by
    # `max(64, 3*LNH) >= 2*LNH + LNH` and so could not fail -- the same
    # tautology class review N2 found in the SCA assert.  What actually has
    # to hold is that norm_w's LDV words fit between NW and the top of the
    # staging window, and that the three tiles below it do not overlap.
    assert STG + 2 * LR.LNH <= DTB, "A_q15 overruns the dt_bias tile"
    assert DTB + LR.LNH <= NW, "dt_bias overruns the norm_w tile"
    assert NW + LR.LDV <= STG + STG_SZ, (
        f"norm_w needs {LR.LDV} words at STG+{NW - STG} but the staging "
        f"window is only {STG_SZ} words (LNH={LR.LNH}, LDV={LR.LDV})")
    M.W(NW, qd["norm_w_q14"])
    INVQ = int(round((1 << 15) / np.sqrt(LR.LDK)))
    ON = XN                      # gated outputs (LVD) overwrite XN(/X8)
    for h in range(LR.LNH):
        # VREP: value head h reads KEY head h // VREP.  The packed block is
        # [q: LKD][k: LKD][v: LVD] with LKD = LNKH*LDK, so indexing q/k by
        # the VALUE head walks into the next region at 4B/9B — the exact
        # silent-wrong-answer `require_supported_geometry` used to refuse.
        # Mirrors `ref/layer_ref.py:223-225`'s np.repeat(..., VREP).
        hk = h // LR.VREP
        q_src = QKV + hk * LR.LDK
        k_src = QKV + LR.LKD + hk * LR.LDK
        v_src = QKV + 2 * LR.LKD + h * LR.LDV
        M.vn(2, LR.LDK, QKV_F, NRM_F, q_src, QN)
        M.alu(2, LR.LDK, INVQ, QN, 0, QNS)
        M.vn(2, LR.LDK, QKV_F, NRM_F, k_src, KN)
        # The SCA map is the layout authority: beta at beta_base + h, decay
        # at decay_base + h.  The old form was `GD + 16 + h`, where the 16
        # WAS LNH -- at LNH=32 every head read the wrong word (heads 0-15
        # from the beta half, 16-31 sixteen short of their decay).
        M.dnst(h, QNS, KN, v_src, decay_base + h, beta_base + h, DO32)
        # int32 -> int16 block float + script-side gated RMSNorm
        # (layer_fixed: dn_o_shift / dn_norm_scale / script_norm_fx).
        # Both immediates are computed from the o32 the DNST command just
        # produced in the MODEL, which is bit-identical to what dn_step
        # wrote into the on-chip scratch — so script and hardware agree by
        # construction, exactly like every other immediate here.
        o32 = M.pairs(DO32, LR.LDV)
        k_h = LF.dn_o_shift(o32, note=False)          # op 1 p0, signed
        m_q15 = LF.dn_norm_scale(o32, k_h, note=False)
        # dn_norm_scale already clips to the positive cfg_p0 range and
        # counts the clips (LF.BF_CLIP, reported by gen_model_script); this
        # is the belt-and-braces field check on the emitted immediate.
        assert 0 <= m_q15 <= LF.M_Q15_MAX, \
            f"SCALE immediate {m_q15} out of range"
        # SEQ hint (opt-in, emits nothing): the next two ALU commands are
        # the DeltaNet block-float pair, which the sequencer expresses as
        # DYNQ16 (+ EPS-NORM in the epsnorm profile).  See ref/seq_format.py.
        if M.seq is not None:
            M.seq.dn_bf(k_h, m_q15, LR.LDV, DO32, OH)
        M.alu(1, LR.LDV, k_h, DO32, 0, OH)            # SHIFT32
        M.alu(2, LR.LDV, m_q15, OH, 0, OH)            # SCALE   >>15
        M.alu(3, LR.LDV, 14, OH, NW, NH)              # EMUL norm_w >>14
        M.alu(5, LR.LDV, QKV_F - 12, Z16 + h * LR.LDV, 0, ZG)
        M.alu(3, LR.LDV, 12, NH, ZG, ON + h * LR.LDV)
    M.R(ON, 256)
    # out projection + residual
    M.alu(0, LR.LVD, 0, ON, 0, STG)
    y, ex = M.matvec(qd["out"], STG, LR.LVD)
    M.inject_dequant(y, M.shift_for(qd["out"], ex, LF.DN_NORM_F, RS_F),
                     OUTSTG, OUTDST)
    M.alu(4, H, 0, X0, OUTDST, X0)
    mlp_block(M, ln2, qm)
    M.R(X0, H)
    assert np.array_equal(M.mem[X0:X0 + H], gold_x), "dn token mismatch"


def attn_token(M, qa, ln1, ln2, qm, pos, gold_x):
    """Full-attention token body.  At 0.8B: QG=8192, K16=12288, V16=12800,
    QR=13312, KR=15360, GX8=6976, OSTG=9216, ODST=12288 (frozen literals)."""
    QG, K16, V16 = AT_QG, AT_K16, AT_V16
    QR, KR = AT_QR, AT_KR
    AO32, OG, GATED, GX8 = AT_AO32, AT_OG, AT_GATED, AT_GX8
    OSTG, ODST = AT_OSTG, AT_ODST

    M.W(STG, ln1)
    M.vnw_(STG, H)
    M.vn(0, H, RS_F, RS_F, X0, XN)
    M.alu(0, H, 0, XN, 0, X8)
    y, ex = M.matvec(qa["q_proj"], X8, H)
    M.inject_dequant(y, M.shift_for(qa["q_proj"], ex, RS_F, QKV_F), STG, QG)
    y, _ = M.matvec(qa["k_proj"], X8, H)
    M.inject_dequant(y, M.shift_for(qa["k_proj"], ex, RS_F, QKV_F), STG, K16)
    y, _ = M.matvec(qa["v_proj"], X8, H)
    M.inject_dequant(y, M.shift_for(qa["v_proj"], ex, RS_F, QKV_F), STG, V16)
    # rope tables for this position
    cq, sq = LF.rope_tables_q15(pos)
    # SEQ hint (opt-in, emits nothing): the ONLY position-dependent constant
    # in the whole token body.  The emitter stores it in a strided DDR region
    # so the load can be XRF[4]-indexed and the decode loop can close.
    if M.seq is not None:
        M.seq.pos_hint = pos
    M.W(STG, np.concatenate([cq, sq]))
    M.ropet(STG)
    # q heads: rmsnorm(q_norm) + rope.  NRMW/NRMB live in the first
    # 2*ROT + 2*HD staging words (rope tables 2*ROT | norm weight HD |
    # head scratch HD) — 128 + 512 = 640 at every released geometry.
    NRMW, NRMB = STG + 2 * LR.ROT, STG + 2 * LR.ROT + LR.HD
    M.W(NRMW, qa["q_norm"])
    M.vnw_(NRMW, LR.HD)
    for h in range(LR.NQ):
        M.vn(0, LR.HD, QKV_F, QKV_F, QG + h * 2 * LR.HD, NRMB)
        M.rope(NRMB, QR + h * LR.HD)
    M.W(NRMW, qa["k_norm"])
    M.vnw_(NRMW, LR.HD)
    for h in range(LR.NKV):
        M.vn(0, LR.HD, QKV_F, QKV_F, K16 + h * LR.HD, NRMB)
        M.rope(NRMB, KR + h * LR.HD)
    group = LR.NQ // LR.NKV
    # S3 (spec 6.2): the attention layer's KV schedule.  `A` is the
    # ATTENTION LAYER index — the LAYER CSR's kv_layer field, which the
    # caller programmed with M.layer(...) before calling this body — and the
    # DN / conv slots stay exactly where the caller left them.
    A, dn_s, cv_s = M.kv_layer, M.dn_slot, M.cv_slot
    # S3 fix round 1, M8.  `A` is read off the LAYER CSR the CALLER
    # programmed, and every SLD/SST and every TCNT index below derives from
    # it -- so a caller that forgot `M.layer(..., kv_layer=A)` would emit a
    # whole attention layer against layer 0's KV blocks, silently.  Refuse.
    assert M.layer_is_set, (
        "attn_token: no LAYER record before this body — the attention "
        "layer index comes from LAYER.kv_layer (B15.2) and there is none")
    # The gated attention output uses ONE block-float shift for the whole
    # token (layer_fixed.attn_o_shift: the heads are concatenated into the
    # o_proj matvec, so a per-head shift would reweight them).  k_a is not
    # known until every head has been evaluated, so PEEK all of them first
    # — attn_peek_img/sigm_peek mutate nothing and emit nothing, and the
    # loop below then recomputes the identical values through the real
    # commands.
    #
    # THE PEEK READS THE DDR IMAGE, not a slot: with two KV cache slots the
    # four kvheads of an attention layer are never resident at once, and
    # the row KVAP is about to append is not appended yet.  `attn_peek_img`
    # adds that pending row, so it computes exactly what the ATTN below
    # will (Mach._kv_img_view / Mach._sdma_copy are the one place that says
    # the slot and the image hold the same bytes).
    amax = 0
    for h in range(LR.NQ):
        kvh = h // group
        prod = (M.attn_peek_img(A, kvh, QR + h * LR.HD,
                                KR + kvh * LR.HD, V16 + kvh * LR.HD)
                * M.sigm_peek(LR.HD, QKV_F - 12,
                              QG + h * 2 * LR.HD + LR.HD))
        amax = max(amax, int(np.abs(prod).max()))
    k_a = LF.attn_o_shift(amax, note=False)           # op 8 p0, unsigned
    # SEQ hint (opt-in, emits nothing): k_a WAS the one remaining
    # data-dependent command immediate the ISA had no XRF answer for
    # (docs SEQ_ISA A3 / seq_format.py).  With ISA v1.3 the emitter buffers
    # the 3*NQ commands below and re-emits them as the op-8 probe double
    # pass, so it needs the head count too.  Emits nothing on the .txt path.
    if M.seq is not None:
        M.seq.attn_bf(k_a, nq=LR.NQ)
    # spec 6.2, per kvhead h: prefetch h+1 into the other slot, select this
    # one, append, run its four query heads, then store the slot back.  The
    # FIRST kvhead's slot was loaded by the preceding DN layer's pair (or by
    # the preamble), which is why there is no SLD for h = 0 here.
    def _kv_body(kvh):
        M.kvap(kvh, KR + kvh * LR.HD, V16 + kvh * LR.HD)
        for h in range(kvh * group, (kvh + 1) * group):
            M.attn(kvh, QR + h * LR.HD, AO32)
            M.alu(7, LR.HD, QKV_F - 12, QG + h * 2 * LR.HD + LR.HD, 0, OG)
            M.alu(8, LR.HD, k_a, AO32, OG, GATED + h * LR.HD)

    sched_attn_layer(M, A, LR.NKV, dn_s, cv_s, _kv_body)
    M.R(GATED, 256)
    M.alu(0, NQH, 0, GATED, 0, GX8)
    y, ex = M.matvec(qa["o_proj"], GX8, NQH)
    # k_a moved the gated vector's binary point; the o_proj requant shift
    # absorbs it exactly (dyn_quant_i8 is power-of-two invariant).
    M.inject_dequant(y, M.shift_for(qa["o_proj"], ex,
                                    QKV_F + GAT_F - k_a, RS_F),
                     OSTG, ODST)
    M.alu(4, H, 0, X0, ODST, X0)
    mlp_block(M, ln2, qm)
    M.R(X0, H)
    assert np.array_equal(M.mem[X0:X0 + H], gold_x), "attn token mismatch"


def mlp_block(M, ln2, qm):
    """SwiGLU MLP.  At 0.8B: GP=4096, SG=11264, DSTG=11264, DDST=13312."""
    GP, SG = ML_GP, ML_SG
    DSTG, DDST = ML_DSTG, ML_DDST
    M.W(STG, ln2)
    M.vnw_(STG, H)
    M.vn(0, H, RS_F, RS_F, X0, XN)
    M.alu(0, H, 0, XN, 0, X8)
    y, ex = M.matvec(qm["gate"], X8, H)
    M.inject_dequant(y, M.shift_for(qm["gate"], ex, RS_F, 12), GP, SG, op=6)
    y, _ = M.matvec(qm["up"], X8, H)
    # u kept 32-bit: SHIFT32W in place, then EMUL32 in place
    p0 = M.shift_for(qm["up"], ex, RS_F, RS_F)
    for c in range(0, FFN, CHUNK):
        n = min(CHUNK, FFN - c)
        M.W32(GP + 2 * c, y[c:c + n])
        M.alu(9, n, p0, GP + 2 * c, 0, GP + 2 * c)
    for c in range(0, FFN, CHUNK):
        n = min(CHUNK, FFN - c)
        M.alu(8, n, 12, GP + 2 * c, SG + c, GP + c)
    M.R(GP, 128)
    M.alu(0, FFN, 0, GP, 0, GP + FFN)
    y, ex = M.matvec(qm["down"], GP + FFN, FFN)
    M.inject_dequant(y, M.shift_for(qm["down"], ex, RS_F, RS_F), DSTG, DDST)
    M.alu(4, H, 0, X0, DDST, X0)


def main():
    require_supported_geometry("gen_layer_script.main")
    # `--wq=w4|w8` (R-c) is the ONLY flag this generator takes.  Positional
    # parsing is unchanged and `--wq=w4` is the default, so every committed
    # artifact regenerates byte-identically (ref/scripts/regen_gate.sh).
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    wq = "w4"
    for fl in list(flags):
        if fl.startswith("--wq="):
            wq = fl.split("=", 1)[1]
            flags.discard(fl)
    if wq not in ("w4", "w8"):
        raise SystemExit("--wq must be w4 (default) or w8")
    if flags:
        raise SystemExit(f"unknown flags: {sorted(flags)}")
    w8 = (wq == "w8")
    outfile, seed = argv[0], int(argv[1])
    ntok = int(argv[2]) if len(argv) > 2 else 3
    rng = np.random.default_rng(seed)

    with open(outfile, "w") as f:
        M = Mach(f)

        # ---------- DeltaNet layer ----------
        # NOTE both quant_layer calls in this file quantize RANDOM weights,
        # so there is deliberately no layer_idx: activation calibration is a
        # property of the real checkpoint and would be meaningless here.  With
        # FABLE5_CALIB_STATS set, quant_layer refuses (missing layer_idx) —
        # loudly, which is the wanted behaviour: this generator is not a
        # calibrated flow.
        wf = LR.init_layer_weights(rng, "linear_attention")
        qw = LF.quant_layer(wf, w8=w8)
        cache = LF.new_cache_fx("linear_attention")
        x = np.round(rng.normal(0, 1, LR.H) * (1 << RS_F)).astype(I64)

        qd = qw["dn"]
        # S3: the conv weights reach the layer by SLD from the DDR image,
        # not by 120 CONVW commands the RTL now refuses (spec 5.5, 6.4).
        # `seed_conv` puts the same taps in the image that the CONVW loop
        # used to stage through scratch; the state words stay zero, which
        # is what the retired CONVZ did, and the DN block is zero, which is
        # what the retired 32 DNZ did.
        M.seed_conv(0, qd["conv_w"])
        sched_preamble(M, ["linear_attention"])
        M.W(X0, x)
        for t in range(ntok):
            M.layer(0, 0, 0, 0)
            gold = LF.layer_decode_fx(x, qw, cache, t)
            dn_token(M, qd, qw["ln1"], qw["ln2"], qw["mlp"], gold)
            # 6.1/6.3 at n_dn = 1: the layer stores itself and reloads for
            # the next token, which is the token boundary in miniature.
            sched_token_end(M, 1)
            x = gold

        # ---------- full-attention layer ----------
        wf = LR.init_layer_weights(rng, "full_attention")
        qw = LF.quant_layer(wf, w8=w8)
        cache = LF.new_cache_fx("full_attention")
        x = np.round(rng.normal(0, 1, LR.H) * (1 << RS_F)).astype(I64)

        # S3: attention layer 0 of the image.  The KV slots come out COLD
        # (B15.4), so kvhead 0's K and V halves are loaded before the first
        # token and re-loaded at every token boundary — the miniature of
        # 6.2's "the first kvhead is prefetched during the preceding DN
        # layers".  TCNT was reset by the preamble above (ALL 32 counters).
        M.layer(0, 0, 0, 0)
        M.sld(K_KV, 0, 0, 0)
        M.sld(K_KV, 0, 0, 1)
        M.W(X0, x)
        for t in range(ntok):
            M.layer(0, 0, 0, 0)
            gold = LF.layer_decode_fx(x, qw, cache, t)
            attn_token(M, qw["attn"], qw["ln1"], qw["ln2"], qw["mlp"],
                       t, gold)
            M.sld(K_KV, 0, 0, 0)
            M.sld(K_KV, 0, 0, 1)
            x = gold

        print("Q", file=f)

    prefix = outfile.rsplit(".", 1)[0]
    # A2.5 / A2.2, VALUE-GATED exactly as the shipping emitter is: a
    # manifest with no `rs_f` key MEANS RS_F_MANIFEST_DEFAULT, so the key
    # is written if and only if this emission used a different value.  At
    # the default the manifest is BYTE-IDENTICAL to what it always was,
    # which is what `evidence/qwen2b/rc/t4_bytes_unmoved.sh` (which calls
    # THIS main()) requires — and A2.5's operational rule that that script
    # must not run with FABLE5_RS_F exported still stands, because at
    # RS_F = 7 the bytes legitimately differ.  Without this, generating a
    # TB script under FABLE5_RS_F=7 tripped `dump_weights`' refusal.
    nW = M.dump_weights(
        prefix, rs_f=(LF.RS_F if LF.RS_F != RS_F_MANIFEST_DEFAULT else None))
    print(f"layer script: seed={seed} ntok={ntok} wq={wq} cmds={M.ncmd} "
          f"hostwords={M.nw} weights={nW} -> {outfile}")


if __name__ == "__main__":
    main()
