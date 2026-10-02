#!/usr/bin/env python3
"""seq_cost.py — Task S1P: a STATIC per-record cycle-cost source for the S1
reorder pass (ref/scripts/reorder_e4.py --cost static).

    FABLE5_MODEL=9b python ref/seq_cost.py --selftest

WHY.  The reorder pass schedules with OV1's model
(evidence/qwen9b/ov/ov_census.py), which needs, per static record, the
window it occupies on the issue lane, per MVGO the engine-busy cycles of its
stream (S) and per FENCE group the poll tail after the last stream ends
(tau).  Until S1P those came ONLY from BN1's untracked timeline CSV of
model_9b_s1, mapped onto a target stream by segment skeleton — so a stream
the CSV does not cover could not be reordered at all.  This module computes
the same three quantities from the record fields alone.

WHERE EVERY NUMBER COMES FROM (the table below; the fit and its residuals
are evidence/qwen9b/ov/s1p_cost_fit.py, run on snoke, log cited in
evidence/qwen9b/ov/S1P_SHIP.md §1):
  * ALU / VN busy cycles per command key: E1's measured per-key table
    (evidence/qwen9b/sd/014_e1_analysis.log, the `mean` column, rounded to
    the cycle), plus a per-key issue/drain/poll overhead measured on the
    CSV as (node window - busy_cmp), the node window including the three
    ARG CSRWRs that ride the command (ov_census.build_nodes merges them).
  * every other layer command: its measured node window on the CSV (all
    constant to the cycle over six tokens except ATTN, which grows 39 cycles
    per position, and the 6th DMA command of a run, which waits for the DMA
    queue — see DMA_QDEPTH).
  * MOVX / MOVY / LDC: dur = a + b * length, least squares on the CSV.
  * MVGO: a constant issue window; its stream S = a + b * beats (the beats
    field of the record), least squares on the CSV.
  * FENCE: ends TAU cycles after the last stream of its group ends (TAU by
    group size, the CSV mean).  SR4 (SEQ_ISA v2.3 B17.1, the R1 channel
    mask): the group is the MASKED pending streams only (mask 0 = all four,
    today's meaning); an unmasked stream stays pending.  A masked FENCE
    makes groups of sizes 1 and 3, which the CSV never measured: both take
    the nearest measured size (1 -> 2, and 3 ties between 2 and 4 and takes
    the smaller, 2) — an EXTRAPOLATION, below.
The costs are cycles of the 250 MHz aclk on the chip testbench, as the CSV's
are.

SR11b — THE FENCE CORRECTION, FOR PREDICTIONS ONLY.  SR5b measured on the
chip TB that the FENCE convention above is wrong twice over and that at
R1's operating point the two errors cancel: every FENCE record costs 23
cycles the rows charge nothing for, and a single-channel poll tail is ~20
cycles where TAU prices ~47.  FENCE_REC, TAIL1 (per drained matvec class)
and CMD_RESID_FRAC (the inherited CMD contention residual) below are the
corrected convention; reorder_e4.predict() prices an emitted order with
them.  They do NOT enter cost_of_segment's rows: the rows feed the
SCHEDULER (via ov_census.stream_durations' tau), and a schedule change
would move every pinned r0/r1 image (sw/chat_seq.py) and every measured
r1 stream — the correction changes predictions, not schedules.

WHAT IS REFUSED AND WHAT IS EXTRAPOLATED (final-fix C1, stated plainly).
StaticCostError is an AssertionError subclass (like reorder_e4's
HazardError / ReorderError), raised explicitly so it survives `python -O`;
sw/chat_seq.py's resolve_reorder (form A) and _reorder_images_b (form B)
turn it into their ChatSeqError refusal through `except AssertionError`.
  REFUSED — a key the table does not carry raises StaticCostError, never
  guessed:
    * ALU / VN command keys (E1_BUSY: sub-op, length, probe bit),
    * the fixed-window layer commands (CMD_FIXED: CONV by size, DNST, GATE,
      KVAP, ROPE, ROPET; any other layer opcode, e.g. DNZ, CONVW),
    * EMB by length (EMB),
    * MOVY by MODE (MOVY: pairs32 / int16),
    * any record opcode _record_dur does not list.
  EXTRAPOLATED — a law fitted on the CSV prices ANY value of its variable,
  including values the CSV never showed:
    * linear in length: MOVX, MOVY (within a known mode), LDC, and the MVGO
      stream S (linear in beats); VNW busy = 3n + 1 (exact on n = 256 and
      4096, any other n by the line; its overhead falls back to
      CMD_OVH_DEFAULT);
    * linear in position: ATTN (exact on positions 0..5);
    * nearest neighbour: TAU by FENCE group size (2 and 4 measured; the
      masked groups of sizes 1 and 3 an R1 FENCE makes take 2's value);
    * CMD_OVH_DEFAULT for an E1 key whose overhead the CSV never measured
      (the key itself must still be in E1_BUSY).

R3 — THE ONE-WINDOW ASSUMPTION (R3 campaign Task R3-4: stated and pinned; no
price moved).  A broadcast MOVX (flags[7:4] = 0xF, seq_format.MOVX_BCAST;
docs/SEQ_ISA.md B17.3) costs ONE MOVX window, a + b * length exactly as a
unicast of the same length, and the three sibling unicasts it replaces cost
zero (they are no longer in the stream).  This is the spec's pricing (the
round's design spec, section 1.3 (a): "It prices as OV1's R3 (siblings
free)") and the R3 plan's default; nothing here measured it.  _record_dur's
MOVX row reads the length, never the channel, so the pricing needed no code:
selftest (d) is a CHARACTERISATION case (it passed at the base commit; not a
RED) that fails loudly if an edit ever prices a broadcast differently.  What
TESTS the assumption is the chip TB: R3-9a's one-window measurement on the
coverage streams and R3-9b's measured saving on the r3 streams, both after
R3-7's committed prediction.  The SR11b FENCE correction above (FENCE_REC,
TAIL1, CMD_RESID_FRAC) applies to an r3 order unchanged.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import seq_format as SF                    # noqa: E402
import gen_layer_script as GLS             # noqa: E402

# the CSV's 16 activity classes (tb/seq_timeline.svh header,
# evidence/qwen9b/bn/bn_timeline_model_9b_s1.csv line 2); MV0_BSY is 8
BSY0 = 8
NCLS = 16


class StaticCostError(AssertionError):
    """A record the static table cannot price — raised explicitly, so it
    survives `python -O`."""


# ======================================================================
# THE TABLE — every constant cites where it was measured.
# KEYED (unknown key REFUSED): E1_BUSY, CMD_FIXED, EMB, MOVY's mode.
# EXTRAPOLATING: MOVX / MOVY length / LDC / STREAM / VNW_BUSY / ATTN
# (linear), TAU (nearest neighbour), CMD_OVH_DEFAULT (see the docstring).
# ======================================================================
# E1 busy_cmp cycles per command, the `mean` column of
# evidence/qwen9b/sd/014_e1_analysis.log:15-41 rounded to the cycle (T)
E1_BUSY = {
    ("ALU", "ADD", 4096): 4102,
    ("ALU", "AMAX32", 2048): 2053,
    ("ALU", "AMAX32", 512): 517,
    ("ALU", "DYNQ16", 128): 269,
    ("ALU", "DYNQ8", 12288): 24594,
    ("ALU", "DYNQ8", 4096): 8210,
    ("ALU", "EMUL", 128): 140,
    ("ALU", "EMUL32", 2048): 4108,
    ("ALU", "EMUL32", 256): 524,
    ("ALU", "EMUL32", 4096): 8204,
    ("ALU", "EMUL32", 4096, "probe"): 8205,
    ("ALU", "SCALE", 128): 140,
    ("ALU", "SCALE", 2048): 2060,
    ("ALU", "SHIFT32", 1024): 1034,
    ("ALU", "SHIFT32", 128): 138,
    ("ALU", "SHIFT32", 2048): 2058,
    ("ALU", "SHIFT32", 32): 42,
    ("ALU", "SHIFT32W", 2048): 4106,
    ("ALU", "SIGM16", 256): 271,
    ("ALU", "SILU16", 128): 147,
    ("ALU", "SILU32", 1024): 1043,
    ("ALU", "SILU32", 2048): 2067,
    ("VN", "EPS-NORM", 128): 308,
    ("VN", "l2norm", 128): 304,
    ("VN", "rmsnorm0", 256): 563,
    ("VN", "rmsnorm0", 4096): 8243,
    ("VN", "rmsnorm1", 4096): 8243,
}
# per-key overhead = mean(node window - busy_cmp) on the CSV, node window
# including the command's three ARG CSRWRs (s1p_cost_fit.py fit, n80/n82)
CMD_OVH = {
    ("ALU", "ADD", 4096): 32, ("ALU", "AMAX32", 2048): 27,
    ("ALU", "AMAX32", 512): 29, ("ALU", "DYNQ16", 128): 58,
    ("ALU", "DYNQ8", 12288): 43, ("ALU", "DYNQ8", 4096): 44,
    ("ALU", "EMUL", 128): 29, ("ALU", "EMUL32", 2048): 39,
    ("ALU", "EMUL32", 4096): 38, ("ALU", "EMUL32", 4096, "probe"): 65,
    ("ALU", "SCALE", 128): 29, ("ALU", "SCALE", 2048): 33,
    ("ALU", "SIGM16", 256): 28, ("ALU", "SILU16", 128): 35,
    ("ALU", "SILU32", 1024): 36, ("ALU", "SILU32", 2048): 39,
    ("VN", "EPS-NORM", 128): 30, ("VN", "l2norm", 128): 34,
    ("VN", "rmsnorm0", 256): 35, ("VN", "rmsnorm0", 4096): 38,
    ("VN", "rmsnorm1", 4096): 38,
    ("VNW", 256): 37, ("VNW", 4096): 35,
}
# an E1 key the CSV's stream does not issue (EMUL32 x256, SHIFT32*): the
# median of the measured ALU overheads (I — inferred, not measured)
CMD_OVH_DEFAULT = 36
# measured node windows of the other layer commands (constant to the cycle
# over six tokens on the CSV)
CMD_FIXED = {
    ("CONV", 8192): 41002, ("DNST",): 2990, ("GATE",): 1352,
    ("KVAP",): 4654, ("ROPE",): 1066, ("ROPET",): 416,
}
# ATTN node window = a + b * position (exact on positions 0..5; beyond 5
# an EXTRAPOLATION of that line, labelled so wherever it is used)
ATTN = (1898, 39)
# VNW busy_cmp = 3n + 1 (exact on n = 256 and 4096); overhead CMD_OVH
VNW_BUSY = (1, 3)
# SLD/SST: the node window of an enqueue; the 6th DMA command of a run of
# consecutive DMA commands waits for the queue (docs/SEQ_ISA.md B15.5: one
# transfer in flight; measured: every 6th and none earlier, 42/42)
SDMA = 39
DMA_QDEPTH = 6
SDMA_STALL = 17251
# movers and bulk: dur = a + b * length (least squares on the CSV)
MOVX = (71.1636, 1.012031)
MOVY = {SF.MOVY_PAIRS32: (68.0, 2.03125), SF.MOVY_INT16: (67.0129, 1.01947)}
LDC = (58.2936, 1.125075)
EMB = {4096: 4699}
# MVGO issue window, and its stream: S = a + b * beats
MVGO = 32
STREAM = (36.1753, 0.846518)
# FENCE poll tail after the group's last stream ends, by group size
# (2 and 4 measured; any other size takes the nearer — I)
TAU = {2: 61, 4: 47}
# ----------------------------------------------------------------------
# SR11b — THE FENCE CORRECTION (PREDICTIONS ONLY; see the docstring).  The
# chip TB measured on the R1 streams (SR5b, evidence/qwen9b/sr/
# SR5b_R1_CHIP.md §4) that every FENCE RECORD costs 23 cycles (decode, the
# F_SCAN walk, S_DONE) and that a single-channel poll tail is far shorter
# than the 4-group TAU the scheduler prices it at.  The corrected
# convention, priced by reorder_e4.predict():
#   FENCE end = max(t, max over the drained streams (stream end + TAIL1[k]))
#               + FENCE_REC
# with k the drained stream's matvec class (ov_census.segment_matvecs).
# FENCE_REC: min = max = 23 over the 981 zero-wait FENCEs of the s1 r1 body
# (evidence/qwen9b/sr/n570_sr5_derive.log:80), and over the 1022 FENCEs
# that did not wait on each of tokens 4, 5, 6
# (evidence/qwen9b/sr/n1157_sr11b_fence_fit.log:21-23).
FENCE_REC = 23
# TAIL1[k]: the effective single-channel tail = mean(FENCE end - 23 -
# (MVGO end + model S)) over the FENCEs that WAITED on the TB, tokens 5-6
# of the measured R1 run (token 4, the prediction target, held out);
# measured S = model S to within a cycle per class, so this is the poll
# tail itself (evidence/qwen9b/sr/n1157_sr11b_fence_fit.log:25-39).
TAIL1 = {
    ("DN", "dn_out"): 18, ("DN", "in_a"): 18, ("DN", "in_qkv"): 22,
    ("DN", "in_z"): 27, ("DN", "mlp_down"): 74, ("DN", "mlp_gate"): 25,
    ("DN", "mlp_up"): 26,
    ("GQA", "mlp_down"): 75, ("GQA", "mlp_gate"): 25, ("GQA", "mlp_up"): 26,
    ("GQA", "o_proj"): 19, ("GQA", "q_proj"): 26,
    ("HEAD", "lm_head"): 23,
}
# a class the fit never saw WAIT (k_proj, v_proj, in_b: always done before
# their FENCE at R1) or a stream no 9B label fits: the pooled mean over all
# 696 waited FENCEs of tokens 5-6
# (evidence/qwen9b/sr/n1157_sr11b_fence_fit.log:40; EXTRAPOLATED — I)
TAIL1_DEFAULT = 28
# the inherited CMD contention residual: the R1 chip TB ran the layer
# commands +19,308 cyc over BN1's program-order windows on s1 token 4
# (evidence/qwen9b/sr/n570_sr5_derive.log:67), carried as a fraction of the
# CMD+ARG work and ADDED to the predicted makespan (not a timing effect)
CMD_RESID_FRAC = 19308 / 10710770
# sequencer records
XOP, AMAXL, JMP = 4, 17, 39
CSRWR = 3
CSRWR_XRF = 4
CSRWR_TCNT_SEQ = 2

ALU_NAME = {0: "DYNQ8", 1: "SHIFT32", 2: "SCALE", 3: "EMUL", 4: "ADD",
            5: "SILU16", 6: "SILU32", 7: "SIGM16", 8: "EMUL32",
            9: "SHIFT32W", 10: "AMAX32", 12: "DYNQ16"}
VN_NAME = {0: "rmsnorm0", 1: "rmsnorm1", 2: "l2norm", 3: "mode3"}
LOP_NAME = {1: "VN", 2: "VNW", 3: "ROPET", 4: "ROPE", 5: "CONVW",
            6: "CONV", 7: "GATE", 8: "DNST", 9: "KVAP", 10: "ATTN",
            11: "ALU", 12: "DNZ", 13: "SLD", 14: "SST"}
ARG_CSRS = (SF.CSR_L_ARG0, SF.CSR_L_ARG1, SF.CSR_L_ARG2)


def cmd_key(lop, a0, a1, a2):
    """E1's key for ALU/VN (evidence/qwen9b/sd/sd1_common.key_of), the size
    field for VNW/CONV, the bare name otherwise."""
    if lop == 11:
        sub = a0 & 0xF
        n = GLS.dec_alu_len(a0)
        p0 = GLS.dec_alu_p0(a0, a2)
        k = ("ALU", ALU_NAME.get(sub, f"sub{sub}"), n)
        if sub == 8 and (p0 & SF.ALU_PROBE_BIT) and p0 < (1 << 16):
            k = k + ("probe",)
        return k
    if lop == 1:
        mode = a0 & 0x3
        n = 1 << ((a0 >> 2) & 0xF)
        name = VN_NAME[mode]
        if mode == SF.VN_EPSNORM_MODE and (a2 & SF.VN_ARG2_EPS):
            name = "EPS-NORM"
        return ("VN", name, n)
    if lop == 2:
        return ("VNW", a0 & 0x1FFF)
    if lop == 6:
        return ("CONV", (a0 >> 14) & 0x3FFF)
    return (LOP_NAME.get(lop, f"op{lop}"),)


def _lin(ab, x):
    return int(round(ab[0] + ab[1] * x))


def cmd_node(key, pos, burst):
    """The node window (ARGs merged, three of them) of one layer command."""
    k0 = key[0]
    if k0 in ("ALU", "VN"):
        if key not in E1_BUSY:
            raise StaticCostError(f"no E1 cost for command key {key}")
        return E1_BUSY[key] + CMD_OVH.get(key, CMD_OVH_DEFAULT)
    if k0 == "VNW":
        return VNW_BUSY[0] + VNW_BUSY[1] * key[1] + \
            CMD_OVH.get(key, CMD_OVH_DEFAULT)
    if k0 == "ATTN":
        return ATTN[0] + ATTN[1] * int(pos)
    if k0 in ("SLD", "SST"):
        return SDMA_STALL if burst >= DMA_QDEPTH else SDMA
    if key in CMD_FIXED:
        return CMD_FIXED[key]
    raise StaticCostError(f"no static cost for layer command {key}")


def _record_dur(r):
    """-> (row window, stream S) of one non-CMD, non-FENCE record."""
    o = r.opcode
    if o == SF.OP_CSRWR:
        sp = r.target & 0xF000
        if sp == SF.CSR_SPACE_SEQ:
            return (CSRWR_XRF if (r.target & 0xFF) >= SF.SOFF_XRF0
                    else CSRWR_TCNT_SEQ), 0
        return CSRWR, 0
    # R3 (Task R3-4): priced by LENGTH only.  A broadcast MOVX (chan 0xF)
    # costs ONE MOVX window and the siblings it replaces cost zero: spec
    # section 1.3 (a) and the plan's default, which the chip TB tests
    # (R3-9a / R3-9b).  Pinned by selftest (d); see the docstring, R3.
    if o == SF.OP_MOVX:
        return _lin(MOVX, r.len_or_addr_hi & 0xFFFFFF), 0
    if o == SF.OP_MOVY:
        if r.movy_mode not in MOVY:         # keyed on the MODE (refused);
            raise StaticCostError(          # linear in the length
                f"no static cost for MOVY mode {r.movy_mode!r}")
        return _lin(MOVY[r.movy_mode], r.len_or_addr_hi & 0xFFFFFF), 0
    if o == SF.OP_MVGO:
        return MVGO, _lin(STREAM, (r.len_or_addr_hi >> 8) & 0xFFFFFF)
    if o == SF.EXT_LDC:
        return _lin(LDC, r.imm32 & 0xFFFFFF), 0
    if o == SF.OP_EMB:
        ln = r.len_or_addr_hi & 0xFFFFFF
        if ln not in EMB:
            raise StaticCostError(f"no static cost for EMB x{ln}")
        return EMB[ln], 0
    if o == SF.EXT_XOP:
        return XOP, 0
    if o == SF.OP_AMAXL:
        return AMAXL, 0
    if o == SF.OP_JMP:
        return JMP, 0
    raise StaticCostError(f"no static cost for {SF.OP_NAME.get(o, o)}")


def _tau(ngroup):
    """The poll tail of a FENCE group of `ngroup` streams: TAU where
    measured (2, 4), else the nearest measured size, a tie to the smaller
    (SR4: the masked groups of sizes 1 and 3 both take TAU[2])."""
    if ngroup in TAU:
        return TAU[ngroup]
    return TAU[min(TAU, key=lambda g: (abs(g - ngroup), g))]


def fence_tail(key):
    """SR11b: the corrected single-channel poll tail of a stream of matvec
    class `key` ((layer type, class) as ov_census.segment_matvecs labels
    it; None when unlabelled) — TAIL1, else TAIL1_DEFAULT."""
    return TAIL1.get(key, TAIL1_DEFAULT)


def cost_of_segment(recs, lo, hi, pos):
    """rows {pc: (opcode, cyc0, dur, cls16)} for records lo..hi in program
    order — the shape ov_census.load_csv gives, so OV1's build_nodes /
    stream_durations consume it unchanged.  S sits on the MVGO's own row
    (stream_durations sums MVc_BSY over MVGO..FENCE); a FENCE row ends TAU
    after the last stream of its group ends."""
    rows = {}
    args = {t: 0 for t in ARG_CSRS}
    burst = 0
    pend = []                 # (channel, stream end) of undrained streams
    t = 0
    for pc in range(lo, hi + 1):
        r = recs[pc]
        o = r.opcode
        cls = [0] * NCLS
        if o == SF.OP_FENCE:
            # SR4 (SEQ_ISA v2.3 B17.1): target[3:0] is the channel mask,
            # mask 0 = all four.  The FENCE drains only the MASKED pending
            # streams; its group is those, priced _tau(len(group)) — sizes 1
            # and 3 are nearest-neighbour (only 2 and 4 measured, TAU).  An
            # unmasked stream stays pending for a later FENCE.
            fm = r.target & 0xF
            sel = [e for (c, e) in pend if fm == 0 or (fm >> c) & 1]
            if sel:
                end = max(max(sel) + _tau(len(sel)), t + 1)
            else:
                end = t + 1
            dur = end - t
            pend = [(c, e) for (c, e) in pend
                    if not (fm == 0 or (fm >> c) & 1)]
        elif o == SF.OP_CMD:
            lop = r.imm32 & 0xFF
            burst = burst + 1 if lop in (SF.OP_L_SLD, SF.OP_L_SST) else 0
            node = cmd_node(cmd_key(lop, *(args[x] for x in ARG_CSRS)),
                            pos, burst)
            # the table is in NODE terms with three ARG writes riding the
            # command; its own row is the rest
            dur = node - 3 * CSRWR
            if dur <= 0:
                raise StaticCostError(f"CMD at {pc}: node {node} too short")
        else:
            dur, S = _record_dur(r)
            if o == SF.OP_CSRWR and r.target in args:
                args[r.target] = r.imm32
            if o == SF.OP_MVGO:
                cls[BSY0 + r.chan] = S
                pend.append((r.chan, t + dur + S))
        rows[pc] = (o, t, dur, cls)
        t += dur
    return rows


def rows_for(recs, pos0=0):
    """The static twin of reorder_e4.Windows.rows_for: segment k is priced
    at position pos0 + k (the s1 template: segment k is token k+1 at
    position k; its loop body at the position of its first iteration)."""
    def f(k, lo, hi):
        return cost_of_segment(recs, lo, hi, pos0 + k)
    return f


def node_cost(recs, pc, pos=0, burst=1):
    """(node window, stream S) of record `pc`, the ARG values in force read
    from the records before it.  For a CMD the window is the NODE's (three
    ARG CSRWRs merged).  Used by the selftest and the fit's cross-check."""
    r = recs[pc]
    if r.opcode == SF.OP_CMD:
        a = {x: 0 for x in ARG_CSRS}
        for q in recs[:pc]:
            if q.opcode == SF.OP_CSRWR and q.target in a:
                a[q.target] = q.imm32
        return cmd_node(cmd_key(r.imm32 & 0xFF, *(a[x] for x in ARG_CSRS)),
                        pos, burst), 0
    return _record_dur(r)


# ======================================================================
# selftest
# ======================================================================
def _rec_cmd(lop):
    return SF.Rec(SF.OP_CMD, imm32=lop)


def _args(a0, a1=0, a2=0):
    return [SF.Rec(SF.OP_CSRWR, target=SF.CSR_L_ARG0, imm32=a0),
            SF.Rec(SF.OP_CSRWR, target=SF.CSR_L_ARG1, imm32=a1),
            SF.Rec(SF.OP_CSRWR, target=SF.CSR_L_ARG2, imm32=a2)]


def _movx(c, src, ln):
    return SF.Rec(SF.OP_MOVX, flags=(c << SF.CHAN_SHIFT), addr_lo=src,
                  len_or_addr_hi=ln)


def _mvgo(c, beats, nrows=1024):
    import hwmap as HW
    return SF.Rec(SF.OP_MVGO, flags=(c << SF.CHAN_SHIFT),
                  target=SF.MVGO_NOWAIT, imm32=HW.shape_word(nrows, 0, 32),
                  addr_lo=0, len_or_addr_hi=(beats << 8))


def _movy(c, dst, ln, int16=True):
    return SF.Rec(SF.OP_MOVY, flags=(SF.MOVY_MODE_BIT if int16 else 0),
                  target=c, addr_lo=dst, len_or_addr_hi=ln)


def _sdma(lop, kind, slot, layer):
    a0 = (kind << 11) | (slot << 10) | (layer << 5)
    return _args(a0) + [_rec_cmd(lop)]


def _synthetic():
    """One segment exercising every class the table prices."""
    vn = (0 | (12 << 2))                       # rmsnorm0 x4096
    recs = [SF.Rec(SF.OP_CSRWR, target=SF.CSR_SEQ_TCNT, imm32=1),    # 0
            SF.Rec(SF.OP_EMB, addr_lo=0x100, len_or_addr_hi=4096)]   # 1
    recs += _args(vn, GLS.enc_a1(0x100, 0x2000))                     # 2-4
    recs += [_rec_cmd(1)]                                            # 5
    recs += [_movx(c, 0x2000, 4096) for c in range(4)]               # 6-9
    recs += [_mvgo(c, 67584) for c in range(4)]                      # 10-13
    recs += [SF.Rec(SF.OP_FENCE)]                                    # 14
    recs += [_movy(c, 0x3000 + 0x800 * c, 2048) for c in range(4)]   # 15-18
    recs += _args(GLS.enc_alu_a0(12, 128, 0), GLS.enc_a1(0x3000, 0),
                  GLS.enc_alu_a2(0, 0x5000))                         # 19-21
    recs += [_rec_cmd(11)]                                           # 22 DYNQ16
    recs += _args(0, GLS.enc_a1(0x3000, 0x6000)) + [_rec_cmd(10)]    # 23-26 ATTN
    for k in range(6):                                               # 27-50
        recs += _sdma(SF.OP_L_SLD if k % 2 else SF.OP_L_SST, k % 3, 0, k)
    recs += _args(4096, GLS.enc_a1(0x3000, 0)) + [_rec_cmd(2)]       # 51-54 VNW
    recs += _sdma(SF.OP_L_SLD, 2, 1, 3)                              # 55-58
    recs += [SF.Rec(SF.EXT_LDC, target=0x7000, imm32=4096,
                    addr_lo=0, len_or_addr_hi=0x80)]                 # 59
    recs += [SF.Rec(SF.OP_HALT)]                                     # 60
    return recs


def selftest():
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}{('  ' + detail) if detail else ''}")

    # (a) anchors: the table reproduces the CSV's measured class means
    #     (T: evidence/qwen9b/ov/n78_s1p_cost_census.log)
    print("(a) anchors — the table at the CSV's measured means")
    recs = _synthetic()
    try:
        c = {pc: node_cost(recs, pc, pos=3) for pc in (1, 5, 6, 10, 15, 22,
                                                      26, 59)}
        check("EMB x4096 = 4699", c[1][0] == 4699, str(c[1]))
        check("VN rmsnorm0 x4096 node = 8281", c[5][0] == 8281, str(c[5]))
        check("MOVX x4096 = 4216", c[6][0] == 4216, str(c[6]))
        check("MVGO 67584 beats: issue 32, S 57247", c[10] == (32, 57247),
              str(c[10]))
        check("MOVY int16 x2048 = 2155", c[15][0] == 2155, str(c[15]))
        check("ALU DYNQ16 x128 node = 327", c[22][0] == 327, str(c[22]))
        check("ATTN at pos 3 node = 2015", c[26][0] == 2015, str(c[26]))
        check("LDC x4096 = 4667", c[59][0] == 4667, str(c[59]))
        more = [(_movx(0, 0, 12288), 12507), (_movy(0, 0, 1024, False), 2148),
                (_mvgo(0, 101376), (32, 85853)), (_mvgo(0, 264), (32, 260))]
        for r, want in more:
            got = node_cost([r], 0)
            got = got if isinstance(want, tuple) else got[0]
            check(f"{SF.OP_NAME[r.opcode]} {r.len_or_addr_hi} -> {want}",
                  got == want, str(got))
    except Exception as e:                  # noqa: BLE001  (RED stub)
        check("anchors computed", False, f"{type(e).__name__}: {e}")

    # (b) the synthetic segment through OV1's own node builder
    print("(b) the rows feed ov_census.build_nodes / stream_durations")
    try:
        sys.path.insert(0, os.path.join(HERE, "..", "evidence", "qwen9b", "ov"))
        import ov_census as OC
        f = rows_for(recs)
        rows = f(0, 1, len(recs) - 2)
        nodes = OC.build_nodes(recs, 1, len(recs) - 2, rows)
        groups, leak = OC.stream_durations(nodes, rows)
        by = {n.pc: n for n in nodes}
        check("VN node (ARGs merged) = 8281", by[5].dur == 8281, str(by[5].dur))
        check("four streams of S 57247", all(by[pc].S == 57247
                                            for pc in range(10, 14)))
        check("one group, tau = 47, no leak", len(groups) == 1
              and groups[0]["tau"] == 47 and leak == 0,
              f"{[g['tau'] for g in groups]} leak {leak}")
        dma = [by[pc].dur for pc in range(30, 51, 4)] + [by[58].dur]
        check("DMA run: 5 x 39 then the 6th waits 17251; a compute CMD resets"
              " the run", dma == [39] * 5 + [17251, 39], str(dma))
        check("VNW x4096 node = 12324", by[54].dur == 12324, str(by[54].dur))
        # (d) no skeleton, no template: a second, different segment
        other = recs[:5] + [_rec_cmd(1), SF.Rec(SF.OP_HALT)]
        r2 = rows_for(other, pos0=7)(0, 1, len(other) - 2)
        check("an arbitrary segment is priced (no template match)",
              sum(r2[pc][2] for pc in r2) == 4699 + 8281, str(r2))
    except Exception as e:                  # noqa: BLE001
        check("rows built", False, f"{type(e).__name__}: {e}")

    # (c) fail-closed on what the table does not carry
    print("(c) refusals")
    for name, bad in (
            ("DNZ (never measured)", _args(0) + [_rec_cmd(12)]),
            ("CONV x4096 (only x8192 measured)",
             _args(4096 << 14) + [_rec_cmd(6)]),
            ("EMB x1024 (only x4096 measured)",
             [SF.Rec(SF.OP_EMB, addr_lo=0, len_or_addr_hi=1024)])):
        try:
            node_cost(bad, len(bad) - 1)
            check(f"refuses {name}", False, "priced it")
        except StaticCostError as e:
            check(f"refuses {name}", True, str(e))
        except Exception as e:              # noqa: BLE001
            check(f"refuses {name}", False, f"{type(e).__name__}: {e}")

    # (d) R3-4: the one-window assumption (the docstring, R3).  It passed at
    #     the base commit — the MOVX row never read the channel — so it is a
    #     CHARACTERISATION, not a RED: it trips if a broadcast is ever priced
    #     differently from a unicast of the same length.
    print("(d) CHARACTERISATION (passes at base, not a RED): a broadcast MOVX"
          " = ONE unicast MOVX window")
    try:
        bc = getattr(SF, "MOVX_BCAST", None)
        check("seq_format.MOVX_BCAST = 0xF (the broadcast channel)",
              bc == 0xF, repr(bc))
        for ln, want in ((4096, 4216), (12288, 12507)):
            uni = node_cost([_movx(0, 0x2000, ln)], 0)
            got = node_cost([_movx(0xF, 0x2000, ln)], 0)
            check(f"broadcast MOVX x{ln} = unicast = ({want}, 0)",
                  uni == (want, 0) and got == (want, 0),
                  f"unicast {uni}, broadcast {got}")
        one = cost_of_segment([_movx(0xF, 0x2000, 4096)], 0, 0, 0)
        four = cost_of_segment([_movx(c, 0x2000, 4096) for c in range(4)],
                               0, 3, 0)
        one = sum(v[2] for v in one.values())
        four = sum(v[2] for v in four.values())
        check("one broadcast x4096 = 4216; four unicasts x4096 = 4 x 4216 "
              "= 16864", one == 4216 and four == 4 * 4216,
              f"one broadcast {one}, four unicasts {four}")
    except Exception as e:                  # noqa: BLE001
        check("broadcast characterisation computed", False,
              f"{type(e).__name__}: {e}")
    print("SEQ_COST SELFTEST: " + ("PASS" if ok else "FAIL"))
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest and not selftest():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
