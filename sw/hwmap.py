"""hwmap.py — the one place the fable5_llm device map is written down.

Every host tool (matvec_test.py, layer_test.py, tok_meter.py, ...) imports
these constants instead of re-declaring them.  They must track the RTL:

  rtl/csr_block.sv     stage-1 CSR block          (AXI-Lite BAR 0x0000)
  rtl/matvec_chan.sv   per-DDR-channel matvec     (BAR 0x1000*(c+1))
  rtl/layer_chan.sv    layer-orchestration engine (BAR 0x5000)
  rtl/seq_unit.sv      on-chip command sequencer  (BAR 0x6000)

and the DDR layout `plan_weights()` below packs — THE weight-address
authority (R-c): the emitter (ref/seq_format.plan_weights_from_wids), the
host (sw/seq_run.plan_weights_for) and the golden (ref/seq_model.DDRWeights)
all resolve to it, and sw/layer_test.py's copy of it is gone.
"""

import json
import os

# ---------------------------------------------------------------- clocks
UI_CLK_HZ = 300.12e6      # DDR4 user clock: matvec_chan / ddr_rd_streamer
                          # (PERF_CYC counts here)
ACLK_HZ = 250.0e6         # xdma_0_axi_aclk: AXI-Lite + layer_chan
                          # (LCYC counts here)

# ------------------------------------------------- stage-1 CSR (csr_0 @ 0x0)
R_MAGIC, R_VERSION, R_SCRATCH, R_CALIB = 0x0, 0x4, 0x8, 0xC
R_UPTIME_LO, R_UPTIME_HI = 0x10, 0x14
MAGIC = 0xFAB1E001
CALIB_ALL = 0xF           # all 4 DDR4 channels calibrated

# ------------------------------------ matvec_chan: channel c at 0x1000*(c+1)
R_CTRL, R_STATUS, R_WBASE_LO, R_WBASE_HI = 0x00, 0x04, 0x08, 0x0C
R_WBEATS, R_SHAPE = 0x10, 0x14
R_PERF_CYC_LO, R_PERF_CYC_HI, R_PERF_BEATS = 0x18, 0x1C, 0x20
R_XWIN, R_XPTR, R_RES_PTR, R_RES_DATA, R_IDENT = 0x24, 0x28, 0x2C, 0x30, 0x34
MV_IDENT0 = 0xFAB1C4A0    # channel c reads MV_IDENT0 + c
MV_ST_BUSY, MV_ST_DONE, MV_ST_ERR_RRESP, MV_ST_XOVFL = 0x1, 0x2, 0x4, 0x8

# ------------------------------------------------------------------------
# R_SHAPE — TWO LAYOUTS, and which one a bitstream decodes is a property of
# THE BITSTREAM, not of this file (G3.3, spec §4.5 W5 / §5.1 S5 / §5.2 S6).
# ------------------------------------------------------------------------
# isa=1  build_034 / build_035, i.e. every image that has ever been resident:
#          {2'b0, w8[29], g64[28], nrows[27:12], sh[11:6], ng[5:0]}
#        ng is the ng-UNIT count of one row = K//128, in EVERY mode.  It is
#        the WEIGHT-beat count only in W4; a W8 row streams 2*ng weight beats
#        (a weight is a byte, so a 64 B beat holds 64 of them) — see
#        ref/w4a8_ref.py row_beats8 and W8_SKETCH.md §2 for why ng was NOT
#        redefined (K=6144 would need 96 > 63 and overflow the 6-bit field).
#        g64 = W4 group-size mode (1 = each 64 B weight beat carries TWO
#        groups of 64, with ceil((K/64)/32) scale beats); w8 = weight width
#        (1 = INT8 bytes, V5).  W8 is defined at the g128 cadence ONLY, so
#        w8 with g64 is rejected here and $error'd by the pre-G3 engine.
#        Both travel in the manifest ("g" ABSENT == 128, "w8" ABSENT == W4).
#
# isa=2  THIS TREE's RTL (rtl/matvec_chan.sv), the 9B bitstream:
#          {spare[31:29], ng[28:22], nrows[21:6], sh[5:0]}
#        CONTIGUOUS, three spare bits, no scattered field.  G3.3 deleted the
#        W8 and g64 ENGINE modes, which freed bits 29 and 28, and ng took
#        bit 28 as its SEVENTH: the 9B `down_proj` row is K = FFN = 12288,
#        so ng = 96, which does not fit six bits.  There is no w8 bit and no
#        g64 bit — an isa=2 word cannot express either mode, and asking for
#        one here is refused rather than silently dropped.
#
# THE HOST'S W8 LAW STAYS (spec §3.3).  Stripping W8 from the RTL did not
# strip it from `ref/w4a8_ref.py`, from `matvec_y32_w8`, or from the `w8`
# plumbing in this file: `build_035` is resident and still runs the 2B in
# W8, and `shape_word(..., isa=1)` is what drives it.  The `w8 + g64` assert
# below is vacuous for the 9B build and STAYS, because it still guards the
# old bitstreams' host path.
SHAPE_G64 = 1 << 28        # isa=1 ONLY
SHAPE_W8  = 1 << 29        # isa=1 ONLY

SHAPE_ISA_PRE_G3 = 1       # build_034 / build_035
SHAPE_ISA_9B     = 2       # this tree
SHAPE_ISA        = SHAPE_ISA_9B    # the layout THIS tree's RTL decodes

# The ENGINE ENVELOPE per layout — `rtl/matvec_engine.sv`'s `MAX_NG`
# parameter, which is 96 in this tree (K <= 12288) and was 48 (K <= 6144) in
# `build_034`/`build_035`.  The packer refuses `ng` outside `1..MAX_NG`
# because the engine's own envelope guard is `` `ifndef SYNTHESIS ``: it is
# LOUD in simulation and ABSENT on silicon, so the host is the only thing
# standing between a bad `ng` and a silently wrong y32 on a live board.
SHAPE_MAX_NG = {SHAPE_ISA_PRE_G3: 48, SHAPE_ISA_9B: 96}

# Which SHAPE layout a resident bitstream's VERSION CSR implies.  EXPLICIT,
# never a heuristic and NEVER a default: a tool that drives a live BAR reads
# VERSION anyway, so it asks this instead of assuming.  Both hashes are the
# low 32 bits of the netlist's git hash, as `synth/scripts/create_project.tcl`
# stamps them into `csr_block`; this tree already records both, at
# `sw/seq_run.py:124` (the history line) and `sw/seq_run.py:130` /
# `sw/infer.py:98` (the live constant).
# The 9B row lands in the SAME edit that moves EXPECTED_SEQ_VERSION; Task 15
# (G6) did it, after g6/003_identity_9b.log read 0xc973c18a off the silicon.
SHAPE_ISA_BY_VERSION = {
    0x4F908DF2: SHAPE_ISA_PRE_G3,   # build_034_po2_AltSpreadLogic_high (R-b)
    0x54443B9F: SHAPE_ISA_PRE_G3,   # build_035_fp2a_exc_po (2B W8; R-d)
    0xC973C18A: SHAPE_ISA_9B,       # build_041_ckr2 (9B state spill; G6)
    0xE3C2FF1E: SHAPE_ISA_9B,       # build_044_r1_incr (R1 FENCE mask; SR7)
    # SR11a fix round 3: build_042_bm1 (BM1 idle counters; its SHAPE decode
    # is build_041's) — without this row the measurement bitstream is
    # refused by every tool that keys the layout by VERSION
    0x9B588E78: SHAPE_ISA_9B,       # build_042_bm1 (BM1 counters; BM1-T4prep)
}   # + build_045_r2_incr (SR14), assigned after SEQ_BM_IDENT_BY_VERSION below


class UnknownBitstream(ValueError):
    """The VERSION CSR names an image this checkout has no SHAPE layout for.

    Raised rather than defaulted, because a DEFAULT here is a silent
    mis-drive of a live board: the two layouts put `ng`, `nrows` and `sh` on
    disjoint bits, so an isa=2 word written to `build_034` decodes as a
    perfectly plausible — and completely different — row shape.
    """


def shape_isa_for_version(version):
    """The R_SHAPE layout the bitstream reporting `version` decodes.

    THERE IS NO FALLBACK.  An unmapped version raises `UnknownBitstream`;
    every direct-CSR caller gates on this in the same place it asserts
    MAGIC / CALIB / IDENT, BEFORE it packs anything.
    """
    v = int(version) & 0xFFFFFFFF
    if v not in SHAPE_ISA_BY_VERSION:
        raise UnknownBitstream(
            f"VERSION={v:#010x} is not a bitstream this checkout knows the "
            f"SHAPE layout of (known: "
            + ", ".join(f"{k:#010x}" for k in sorted(SHAPE_ISA_BY_VERSION))
            + ").  Add its row to sw/hwmap.SHAPE_ISA_BY_VERSION, or use a "
              "checkout that matches the resident image — do NOT guess: the "
              "two layouts decode each other's words as plausible garbage.")
    return SHAPE_ISA_BY_VERSION[v]


def shape_word(nrows, sh, ng, g=128, w8=False, isa=SHAPE_ISA):
    """Pack the matvec_chan SHAPE CSR word for one engine run.

    `isa` selects the LAYOUT, and it is the layout of the bitstream being
    driven — see the block comment above and `shape_isa_for_version`.
    """
    assert isa in (SHAPE_ISA_PRE_G3, SHAPE_ISA_9B), f"unknown SHAPE isa {isa}"
    assert g in (128, 64), f"unsupported W4 group size {g}"
    # ENVELOPE, not just field range: the engine's own 1..MAX_NG guard is
    # sim-only, so this is the only check a LIVE board gets.
    assert 1 <= ng <= SHAPE_MAX_NG[isa], (
        f"isa={isa} ng {ng} is outside the engine envelope 1..{SHAPE_MAX_NG[isa]} "
        f"(rtl/matvec_engine.sv MAX_NG)")
    assert not (w8 and g == 64), \
        "w8 + g64 is not a defined row format (W8 is g128-cadence only)"
    if isa == SHAPE_ISA_PRE_G3:
        assert 0 <= ng < (1 << 6), f"isa=1 ng {ng} does not fit 6 bits"
        assert 0 <= sh < (1 << 6), f"sh {sh} does not fit 6 bits"
        assert 0 <= nrows < (1 << 16), f"nrows {nrows} does not fit 16 bits"
        return (((nrows << 12) | (sh << 6) | ng)
                | (SHAPE_G64 if g == 64 else 0)
                | (SHAPE_W8 if w8 else 0))
    # isa=2: the modes are GONE from the hardware, so they cannot be packed
    assert g == 128, \
        "g64 has no isa=2 encoding (the engine mode was stripped at G3.3); " \
        "pass isa=1 to drive build_034/build_035"
    assert not w8, \
        "w8 has no isa=2 encoding (the engine mode was stripped at G3.3); " \
        "pass isa=1 to drive build_034/build_035"
    assert 0 <= ng < (1 << 7), f"isa=2 ng {ng} does not fit 7 bits"
    assert 0 <= sh < (1 << 6), f"sh {sh} does not fit 6 bits"
    assert 0 <= nrows < (1 << 16), f"nrows {nrows} does not fit 16 bits"
    return (ng << 22) | (nrows << 6) | sh


def mv_base(c):
    """AXI-Lite byte offset of matvec_chan c (c = 0..3)."""
    return 0x1000 * (c + 1)


# ----------------------------------------------- layer_chan (base 0x5000)
LB = 0x5000
L_CMD, L_STAT, L_ARG0, L_ARG1, L_ARG2 = LB + 0x00, LB + 0x04, LB + 0x08, LB + 0x0C, LB + 0x10
L_SPTR, L_SWIN, L_EOUT, L_TCNT, L_IDENT = LB + 0x14, LB + 0x18, LB + 0x1C, LB + 0x20, LB + 0x24
L_AMAXI, L_AMAXV = LB + 0x28, LB + 0x2C
L_TCNT2 = LB + 0x60       # RW KV append counters for kvheads 2 and 3,
                          # same {hi[25:16], lo[9:0]} layout as L_TCNT.
                          # G3.4: NKVH = 4 needs four 10-bit counters per
                          # kv_slot and a 32-bit word holds two, so the
                          # second pair got its own offset rather than
                          # aliasing onto the first (rtl/layer_chan.sv
                          # CSR 0x60).  A host that resets T must write
                          # BOTH, or kvheads 2/3 keep a stale count.
L_LAYER = LB + 0x30       # bank select.  v2.0 / today's RTL:
                          # {kv_slot[10:8], dn_slot[4:0]}.  SEQ_ISA v2.1
                          # (B15.2) RE-PURPOSES the word into CACHE slots
                          # plus the attention layer index:
                          # {cv_slot[13:12], kv_layer[10:8], kv_slot[4:3],
                          #  dn_slot[1:0]}, packed by
                          # ref/seq_format.layer_word().  The RTL half
                          # lands at Task S2 — until then this offset
                          # still carries the v2.0 word.
L_LCYC = LB + 0x34        # 32-bit busy-cycle accumulator @ ACLK_HZ;
                          # ANY write clears it, so read-and-difference
# ISA v1.3 XRF window + vec_alu op-8 probe readback (rtl/layer_chan.sv:29-32).
# XRFD is RAW 18 bits: XRF[3] is an unsigned token id, the rest signed (A11).
L_XRFI = LB + 0x38        # RW {29'b0, idx[2:0]}
L_XRFD = LB + 0x3C        # RW XRF[XRFI]; read {14'b0, raw18}, write d[17:0]
L_MAXPL = LB + 0x40       # R  vec_alu op-8 probe max|prod| [31:0]
L_MAXPH = LB + 0x44       # R  {16'b0, max|prod|[47:32]}
# ---- TOPK-32 capture block (rung 4; SEQ_ISA v1.6 B8) ----------------
L_TOPK_IDENT  = LB + 0x48  # R  0xFAB1704B
L_TOPK_STATUS = LB + 0x4C  # R  {24'b0, overflow[7], complete[6], count[5:0]}
L_TOPK_PTR    = LB + 0x50  # RW entry pointer 0..31 (5 bits; wraps at 32)
L_TOPK_VAL    = LB + 0x54  # R  entry[PTR].val int32 (no side effect)
L_TOPK_IDX    = LB + 0x58  # R  {14'b0, idx[17:0]}; PTR++ on read

# SEQ_ISA v2.0 (G3.1, spec 4.3 S3): the DeltaNet scalar-pointer BASE PAIR.
# {a_dec_base[31:16], a_beta_base[15:0]}; the DNST decode forms
# a_beta = a_beta_base + head and a_dec = a_dec_base + head, so this is
# written ONCE PER LAYER BODY rather than once per command.
L_DNSB = LB + 0x5C        # RW {a_dec_base[31:16], a_beta_base[15:0]}

# SEQ_ISA v2.1 (B15.3, spec 5.3 + A1.4): layer state in DDR.  The three
# region bases are 64 KiB-granular (`base >> 16`, 18 bits of a 34-bit
# address); SDMA is the DMA lane's status word and SDMA_CYC is LCYC's twin
# for that lane.  RTL word offsets 0x19..0x1D (rtl/layer_chan.sv, Task S2);
# reference mirror: ref/seq_format.CSR_L_SB_DN..CSR_L_SDMA_CYC.
L_SB_DN    = LB + 0x64    # RW DN state region base >> 16   (B15.3)
L_SB_KV    = LB + 0x68    # RW KV region base >> 16
L_SB_CV    = LB + 0x6C    # RW conv region base >> 16
L_SDMA     = LB + 0x70    # RW R: {busy_dma, queued[2:0], last_kind[1:0], last_slot, err[7:0]}; W clears err
L_SDMA_CYC = LB + 0x74    # R  busy_dma cycles; any write clears
TOPK_IDENT_VAL = 0xFAB1704B
TOPK_K = 32               # capture depth; reset ONLY by AMAX fresh flag
LAYER_IDENT = 0xFAB1E5A0
L_ST_BUSY, L_ST_ERR_OP = 0x1, 0x2
# layer_chan scratchpad depth.  G2a: 32,768 -> 65,536 (spec 4.3 S4, the
# fully-backed 64K-word array).  THE COUPLING, and G3.1 CHANGED WHICH HALF OF
# IT IS TRUE: the RTL array IS 65,536 words now and the ISA's scratch address
# IS 16 bits (SEQ_ISA v2.0), so this constant and the hardware finally agree.
# What does NOT agree is the SHIPPED bitstreams: `build_034`/`build_035` are
# pre-G3 and have a 32,768-word array, which is what `SCRATCH_WORDS_BUILT`
# below is for.  (The earlier text here said "the RTL array is still 32K …
# Task 7 re-encodes ARG and Task 10 grows the array", and cited
# `evidence/qwen2b/rc/t4_bytes_unmoved.sh` as live proof of inertness.  All
# four claims were falsified by G3.1: Task 7 grew the array as well as the
# ISA, and that script is RETIRED BY DESIGN — G3.1 is where the byte-lock is
# SPENT, so a bytes-unmoved check must now fail.  See
# `evidence/qwen9b/g3/G3_1_ISA.md` and `evidence/qwen9b/g2/FINAL_BYTELOCK.md`,
# which is where the pin it protected now lives.)
#
# BUT A HOST CONSTANT IS NOT ONLY READ BY EMITTERS, and G2a review N11 caught
# the difference the hard way.  An earlier revision of this comment claimed
# "`layer_zero_scratch` and `layer_read_scratch` take an explicit count at
# every live call site".  **That was false**: `layer_zero_scratch(n=...)`
# DEFAULTS to this constant and three live callers pass nothing —
# `sw/seq_run.py:2575`, `sw/seq_run.py:3161` and
# `evidence/qwen2b/rd/rd_zero_scratch.py:23-25`.  Doubling this number alone
# would have made them walk 65,536 words of a 32,768-word array on the
# CURRENT bitstreams.  So the two meanings are two names:
#
#   SCRATCH_WORDS        the array the 9B build has (spec 4.3 S4).
#                        Emitters and address maths use this.
#   SCRATCH_WORDS_BUILT  the array the RESIDENT bitstream has.  Anything
#                        that walks the device end to end uses this.
#                        G3.4 did NOT raise it, and that was the correct
#                        call at the time: no BITSTREAM carrying G3.1's
#                        65,536-word RTL existed.  It said it "is raised by
#                        the task that SHIPS a 9B bitstream (G6)", and TASK
#                        15 DID -- --zero-scratch was clearing HALF the pad
#                        and calling it clean.  REVERSE HAZARD: at 65,536 a
#                        tool on a build_034/035 board walks twice an array
#                        that exists, so use a pre-G6 checkout there.
#                        evidence/qwen9b/g6/RD9_GATE.md 4.2 and 14.4.
#
# THE READ PATH WAS MISSED BY THIS FIX'S FIRST CUT, and it is the half with
# teeth.  That revision moved the WRITE side (`layer_zero_scratch`) and then
# claimed "anything that walks the device end to end uses BUILT" while
# `layer_read_scratch` still took `SCRATCH_WORDS` at three live sites --
# including `verify_chip_golden`, a BOARD VERIFICATION path.  That is the
# same claim-the-code-does-not-support defect the original N11 was, made a
# second time by its own fix.  Both defaults are `SCRATCH_WORDS_BUILT` now
# and every call site is explicit or defaulted to it.
#
# THE COUPLING RESTATED AT G3.1, because it is the same two names for a
# different reason now.  The RTL array is 65,536 words and the ISA address is
# 16 bits, so `SCRATCH_WORDS` describes the CURRENT RTL — not a future build.
# `SCRATCH_WORDS_BUILT` is the array the RESIDENT bitstream has; it moved when
# the 9B bitstream shipped (Task 15/G6), and the two names agree again now.
#
# `SCRATCH_WORDS` is THE canonical definition: `sw/seq_run.py`, `sw/infer.py`,
# `sw/layer_test.py` and `tb/scripts/gen_seq_unit_vectors.py` all read it from
# here rather than repeating the literal.
SCRATCH_WORDS = 65536
SCRATCH_WORDS_BUILT = 65536   # build_041 (0xc973c18a); 32768 for build_034/035

# layer_chan opcodes (rtl/layer_chan.sv header)
OP_VN, OP_VNW, OP_ROPET, OP_ROPE = 1, 2, 3, 4
OP_CONVW, OP_CONV, OP_GATE, OP_DNST = 5, 6, 7, 8
OP_KVAP, OP_ATTN, OP_ALU, OP_DNZ = 9, 10, 11, 12
ALU_AMAX32 = 10           # vec_alu op 10, arg2[0]=1 starts a fresh scan

# ------------------------------------------- seq_unit (SEQ CSR block @ 0x6000)
# rtl/seq_unit.sv:19-58 is authoritative; docs/SEQ_ISA.md v1.5 describes it.
# The offsets below are BYTE offsets in the csr_0 AXI-Lite BAR, i.e. exactly
# what synth/scripts/create_project.tcl maps seq_0's s_axil to (0x6000), and
# also what ref/seq_format.SEQ_CSR_BASE assumes.
SB = 0x6000
S_CTRL     = SB + 0x00    # W bit0 START (ignored while busy), bit1 ABORT
                          # R {29'b0, halted, err, busy}
S_STATUS   = SB + 0x04    # R {err_code[31:24], of_ovf[23], out_cnt[22:16],
                          #    13'b0, halted[2], err[1], busy[0]}
                          # rung 4 S6: out_cnt widened 5 -> 7 bits (depth 64)
                          # and of_ovf moved in beside it
S_BASE_LO  = SB + 0x08    # RW record-list DDR byte address [31:0]
S_BASE_HI  = SB + 0x0C    # RW record-list DDR byte address [33:32]
S_LEN      = SB + 0x10    # RW records in the stream
S_PC       = SB + 0x14    # R  current record index
S_OUT_FIFO = SB + 0x18    # R  {valid[31], 13'b0, token[17:0]} — READ-DRAINS
S_OUT_CNT  = SB + 0x1C    # R  {25'b0, entries[6:0]}  (S6: 0..64)
S_TCNT_SEQ = SB + 0x20    # RW token counter consumed by JMP flags 0x1
S_ENTRY    = SB + 0x24    # RW record index START jumps to
S_IDENT    = SB + 0x28    # R  SEQ_IDENT
S_PERF_CYC = SB + 0x2C    # R  cycles busy since START (@ ACLK_HZ)
S_PERF_REC = SB + 0x30    # R  records retired since START
S_PERF_AXW = SB + 0x34    # R  AXI-Lite writes issued
S_PERF_AXR = SB + 0x38    # R  AXI-Lite reads issued
S_PERF_FST = SB + 0x3C    # R  {fetch-starved cycles[31:1], xrf_ovf[0]}
S_XRF0     = SB + 0x40    # RW XRF[i] at S_XRF0 + 4*i, i = 0..7 (raw 18b)
S_EMBLOG2  = SB + 0x60    # RW log2 of the EMB row size in bytes (R-b).
                          # G3.4 (spec 5.3 S8): the RESET is 13 = 8192 B =
                          # H 4096, the 9B row, so a host that never writes
                          # it is RIGHT BY DEFAULT at 9B instead of silently
                          # addressing the wrong row.  12 = 4096 B = H 2048
                          # (Qwen3.5-2B), 11 = 2048 B = H 1024 (0.8B) — both
                          # still reachable, the CSR stays RUNTIME.
                          # HOST-ONLY: the ISA's
                          # 0x2nn CSRWR space cannot reach it.  A write
                          # outside [8,13] is REJECTED by the RTL.
                          # On a pre-R-b bitstream this offset reads
                          # 0xDEADC0DE (outside the map) — that is how the
                          # host tells "no EMBLOG2" from "row size 11".
S_SEQ_CAPS = SB + 0x64    # R  SEQ_CAPS (docs/SEQ_ISA.md v2.3 B17.0):
                          # {magic[31:8] = 24'hFAB1CA, 5'b0, r3, r2, r1}.
                          # Read-only, HOST-ONLY.  Every pre-round bitstream
                          # (build_041/042) reads 0xDEADC0DE here, which
                          # decodes as the EMPTY capability set.

SEQ_IDENT = 0xFAB1E5E0
SEQ_EMBLOG2_RST = 13      # rtl/seq_unit.sv EMBLOG2_RST (G3.4: 11 -> 13)
SEQ_EMBLOG2_MIN, SEQ_EMBLOG2_MAX = 8, 13
SEQ_CSR_UNMAPPED = 0xDEADC0DE   # what a read outside the SEQ map returns
SEQ_XRF_N = 8

# SEQ_CAPS (SEQ_ISA v2.3 B17.0, the sequencer RTL round, Task SR2).  THE ONE
# DEFINITION: ref/seq_format.py uses these through `import hwmap`, the doc's
# B17.0 table is tied to them by evidence/qwen9b/sr/sr2_isa_tdd.py (h), and
# the RTL literal is tied to them by the unit TB (SR3).  Nothing else
# re-types the values.  The magic is the round plan's choice.
SEQ_CAPS_MAGIC = 0xFAB1CA                 # word[31:8]
SEQ_CAP_BITS = {"R1": 1 << 0,             # the FENCE channel mask (B17.1)
                "R2": 1 << 1,             # XWIN/RES bank bits     (B17.2)
                "R3": 1 << 2}             # MOVX broadcast         (B17.3)


def seq_caps_set(word):
    """SEQ_CAPS word -> the device's capability set (a frozenset of names).

    EMPTY unless word[31:8] is SEQ_CAPS_MAGIC — so a pre-round bitstream's
    0xDEADC0DE (the unmapped-read value) is the empty set.  With the magic,
    a set bit that names no capability is REFUSED (ValueError, by bit
    number): an unknown capability is never guessed at."""
    word = int(word) & 0xFFFFFFFF
    if word >> 8 != SEQ_CAPS_MAGIC:
        return frozenset()
    low = word & 0xFF
    known = 0
    for b in SEQ_CAP_BITS.values():
        known |= b
    unknown = low & ~known
    if unknown:
        bad = [f"bit {i}" for i in range(8) if unknown >> i & 1]
        raise ValueError(f"SEQ_CAPS {word:#010x}: unknown capability "
                         f"{', '.join(bad)} (known: "
                         f"{sorted(SEQ_CAP_BITS)}) — docs/SEQ_ISA.md B17.0")
    return frozenset(n for n, b in SEQ_CAP_BITS.items() if low & b)


def seq_caps_check(caps):
    """Normalise a capability-name collection to a frozenset, refusing any
    name outside SEQ_CAP_BITS by name (ValueError).  A bare str is refused
    explicitly: frozenset("R1") would be {"R", "1"}, a set of characters,
    not a set of names."""
    if isinstance(caps, (str, bytes)):
        raise ValueError(f"SEQ capabilities must be a set of names, not the "
                         f"string {caps!r} (write {{{caps!r}}}) — "
                         f"docs/SEQ_ISA.md B17.0")
    caps = frozenset(caps)
    bad = sorted(c for c in caps if c not in SEQ_CAP_BITS)
    if bad:
        raise ValueError(f"unknown SEQ capability {', '.join(map(str, bad))}"
                         f" (known: {sorted(SEQ_CAP_BITS)}) — "
                         f"docs/SEQ_ISA.md B17.0")
    return caps


def seq_caps_word(caps):
    """Capability set -> the SEQ_CAPS word a bitstream with exactly those
    features reads (for mocks and the unit TB's side file)."""
    w = SEQ_CAPS_MAGIC << 8
    for c in seq_caps_check(caps):
        w |= SEQ_CAP_BITS[c]
    return w
SEQ_XRF_BITS = 18
SEQ_OUT_DEPTH = 64        # out_fifo[64] in the RTL (rung 4 S6, was 16):
                          # pushes past it are DROPPED and set the sticky
                          # of_ovf bit — a DROPPED TOKEN, never a stall

SEQ_CTRL_START, SEQ_CTRL_ABORT = 0x1, 0x2
SEQ_ST_BUSY, SEQ_ST_ERR, SEQ_ST_HALTED = 0x1, 0x2, 0x4
SEQ_ST_OUTCNT_SHIFT, SEQ_ST_OUTCNT_MASK = 16, 0x7F   # S6: 5 -> 7 bits
SEQ_ST_OF_OVF = 1 << 23   # sticky OUT-FIFO overflow: a token was DROPPED.
                          # Sticky until RESET (the xrf_ovf precedent) — NOT
                          # cleared by START, by a halt or by draining the
                          # FIFO, so a host that sees it must treat every
                          # later token of the session as suspect.
SEQ_ST_ERRCODE_SHIFT, SEQ_ST_ERRCODE_MASK = 24, 0xFF
SEQ_OUT_VALID = 1 << 31
SEQ_OUT_TOK_MASK = (1 << 18) - 1
SEQ_PERF_XRF_OVF = 0x1    # sticky bit0 of S_PERF_FST: an XOP result truncated

# err_code (STATUS[31:24]) — rtl/seq_unit.sv:40-58 + rtl/seq_movers.sv:136-139
SEQ_ERR = {
    0x00: "no error",
    0x01: "unknown opcode",
    0x02: "bad indirection code",
    0x03: "XRF index out of range",
    0x04: "illegal flags for the opcode",
    0x05: "engine channel >= 4",
    0x06: "reserved field non-zero",
    0x07: "unknown CSR space",
    0x08: "JMP target outside the stream",
    0x09: "pc outside the stream",
    0x0A: "illegal XOP sign code",
    0x0B: "unaligned LDC/EMB address",
    0x0C: "host ABORT",
    0x10: "layer_chan err_op",
    0x11: "layer CMD watchdog",
    0x12: "AXI-Lite SLVERR/DECERR (or a DDR read error)",
    0x20: "matvec err_rresp",
    0x21: "matvec done watchdog",
    0x22: "XWIN fifo overflow",
    0x23: "mover stream watchdog",
}


def s_xrf(i):
    """AXI-Lite byte offset of the sequencer's XRF[i] window."""
    assert 0 <= i < SEQ_XRF_N, f"XRF index {i} out of range"
    return S_XRF0 + 4 * i


def seq_err_name(code):
    return SEQ_ERR.get(int(code) & 0xFF, "UNKNOWN err_code")


def seq_emb_log2(row_bytes):
    """EMBLOG2 CSR value for an embedding row of `row_bytes` bytes."""
    n = int(row_bytes)
    if n <= 0 or (n & (n - 1)):
        raise ValueError(f"emb row {n} B is not a power of two")
    lg = n.bit_length() - 1
    if not (SEQ_EMBLOG2_MIN <= lg <= SEQ_EMBLOG2_MAX):
        raise ValueError(f"emb row {n} B (log2 {lg}) outside the CSR's "
                         f"[{SEQ_EMBLOG2_MIN},{SEQ_EMBLOG2_MAX}]")
    return lg


# ------------------------------------------- generator-artifact manifest
# `<prefix>.weights.json` is a map wid -> image record (ref/gen_layer_script
# dump_weights) plus a small amount of ARTIFACT-LEVEL metadata under non-wid
# keys.  Every consumer that iterates wids must split the metadata off first —
# an old artifact simply has no such key and the default is the answer.
#
#   emb_row_bytes  (R-b) the embedding row stride = 2*H, so the host can size
#                  the table and program EMBLOG2 instead of assuming 2048.
#   rs_f           (G2a, spec 4.4) the residual binary point this artifact was
#                  emitted with.  Absent means 8, which is what every frozen
#                  0.8B/2B artifact carries and what A1.8 keeps as the shipped
#                  value; the key exists so a future geometry can differ
#                  without a global constant the two have to share.
#
# BOTH DEFAULTS AND THE FILTER MUST MOVE TOGETHER.  Adding a key to
# MANIFEST_META_KEYS without adding it to `meta` hides it from every consumer;
# adding it to `meta` without the filter hands it to wid-iterating callers as
# if it were an image record — the exact failure `emb_row_bytes` needed this
# split to avoid.  `_META_DEFAULTS` makes that one edit instead of two.
EMB_ROW_BYTES_DEFAULT = 1 << SEQ_EMBLOG2_RST      # G3.4: 8192 B = H 4096
# ^ This is the value for a manifest with NO emb_row_bytes key, i.e. a
# PRE-R-b artifact, and G3.4 moved it 2048 -> 8192 with the RTL reset it
# mirrors.  That is BY DESIGN (spec 5.3 S8, task brief step 4): the mirror
# must not lie about the hardware's reset.  Every R-b-and-later artifact
# carries the key, so the default is unreachable for anything this build
# serves; a pre-R-b 0.8B artifact replayed on THIS bitstream would need its
# manifest regenerated, which it needs anyway (SEQ_ISA v2.0).
RS_F_DEFAULT = 8                                  # ref/layer_fixed.py RS_F
_META_DEFAULTS = {"emb_row_bytes": EMB_ROW_BYTES_DEFAULT,
                  "rs_f": RS_F_DEFAULT}
# S3 (SEQ_ISA v2.1): two NON-SCALAR meta keys, so they cannot live in
# `_META_DEFAULTS` (whose values go through `int()`).  `state` is
# `plan_state(...)` plus the initial image's sha256; `conv_images` is the
# per-DeltaNet-layer conv block list the host uploads (spec 7.1).  Both are
# ABSENT from every pre-S3 manifest, and `split_manifest` answers None for a
# manifest that does not carry them -- which is what a frozen 0.8B/2B
# artifact is, and it emits no SLD/SST for a region to serve.
MANIFEST_STATE_KEYS = ("state", "conv_images")
MANIFEST_META_KEYS = tuple(_META_DEFAULTS) + MANIFEST_STATE_KEYS


def split_manifest(man):
    """(wid entries, meta) — meta holds MANIFEST_META_KEYS with defaults."""
    wids = {k: v for k, v in man.items() if k not in MANIFEST_META_KEYS}
    meta = {k: int(man.get(k, d)) for k, d in _META_DEFAULTS.items()}
    for k in MANIFEST_STATE_KEYS:
        meta[k] = man.get(k)
    return wids, meta


def load_weights_manifest(prefix):
    """Read `<prefix>.weights.json` -> (wid entries, meta). THE reader."""
    with open(prefix + ".weights.json") as f:
        return split_manifest(json.load(f))


def seq_status(word):
    """Decode a S_STATUS read into a dict (see the field map above)."""
    w = int(word) & 0xFFFFFFFF
    return {
        "busy": bool(w & SEQ_ST_BUSY),
        "err": bool(w & SEQ_ST_ERR),
        "halted": bool(w & SEQ_ST_HALTED),
        "out_cnt": (w >> SEQ_ST_OUTCNT_SHIFT) & SEQ_ST_OUTCNT_MASK,
        "of_ovf": bool(w & SEQ_ST_OF_OVF),
        "err_code": (w >> SEQ_ST_ERRCODE_SHIFT) & SEQ_ST_ERRCODE_MASK,
        "raw": w,
    }


# --------------------------------------------------------------- DDR map
CH_STRIDE = 1 << 32       # host DMA: DDR channel c starts at c * 4 GiB
W_BASE = 0x1000_0000      # weight images packed from here (per channel)
WID_ALIGN = 4096          # per-image start alignment inside the pack
RES_DEPTH = 4096          # matvec result BRAM rows -> max rows per run
EMB_BASE = 0x6000_0000    # embedding table (channel 0)

# ---- SEQ artifacts: the record stream + the LDC constant blob ----------
#
# THE COMPLETE CHANNEL-0 MAP (4 GiB; every host tool in sw/ and every
# address the sequencer's AXI4 read master can emit).  Addresses here are
# CHANNEL-LOCAL: the host adds `chan * CH_STRIDE` for its DMA fds, and so
# does seq_0/m_axi (create_project.tcl gives it the SAME 16 GiB 4-channel
# view XDMA M_AXI has), while mvchan_c/m_axi sees its own channel at 0.
#
#   0x0000_0000 .. 0x08FF_FFFF  144 MiB  FREE / scratch.  sw/ddr_test.py
#                                        sweeps the WHOLE channel with its
#                                        PRNG pattern, so it destroys every
#                                        region below — run it before an
#                                        upload, never between one and a run.
#   0x0900_0000 .. 0x0BFF_FFFF   48 MiB  SEQ_STREAM_BASE: the record list
#                                        (<prefix>.seq).  Biggest stream to
#                                        date: model_v2_s1.x, 1.44 MB.
#   0x0C00_0000 .. 0x0FFF_FFFF   64 MiB  SEQ_DATA_BASE: the LDC constant
#                                        blob (<prefix>.seqdata.bin).
#                                        Biggest to date: ~1 MB.
#   0x1000_0000 .. 0x5FFF_FFFF 1280 MiB  W_BASE: packed weight images,
#                                        variable stride, WID_ALIGN-aligned
#                                        (plan_weights below;
#                                        model_v2_s1 = 187 images, 398 MiB).
#                                        plan_weights ASSERTS the pack ends
#                                        below EMB_BASE — PER CHANNEL when
#                                        the pack is repacked (rows_of).
#   0x6000_0000 .. 0x7E4F_FFFF  485 MiB  EMB_BASE: embedding table,
#                                        vocab x 2048 B rows (248,320 rows =
#                                        0x1E50_0000 B) — THAT SIZE IS
#                                        0.8B-SPECIFIC (H=1024).  At H=2048
#                                        (Qwen3.5-2B) the same 248,320 rows
#                                        are 4096 B each = 970 MiB, ending at
#                                        0x9CA0_0000: still inside the FREE
#                                        tail below, and still above every
#                                        weight top (plan_weights asserts
#                                        top < EMB_BASE on EVERY channel), so
#                                        the region does not collide — see
#                                        evidence/qwen2b/q2/v4_v5/V4_V5.md §5.
#   0x7E50_0000 .. 0xFFFF_FFFF          FREE (2.4 GiB tail; 0.8B numbers —
#                                        at 2B the emb table runs to
#                                        0x9CA0_0000 and the free tail
#                                        starts there instead).
#
# ref/seq_format.py's own SEQ_DATA_BASE/SEQ_STREAM_BASE (0x8000_0000 /
# 0x9000_0000) are EMITTER-SIDE defaults and are NEVER an address anything
# reads at run time: they are baked into the LDC records as ABSOLUTE
# addresses, and sw/seq_run.py RELOCATES every one of them by
# (SEQ_DATA_BASE - meta["seq_data_base"]) before upload — unconditionally,
# on every artifact, by `sw/seq_run.relocate`, which range-checks each one
# against the blob as it goes.  That is what makes those emitter-side
# addresses safe DESPITE landing inside the 2B embedding table
# (0x6000_0000 .. 0x9CA0_0000): nothing is ever written or fetched there.
# Keeping the runtime copies below W_BASE puts every SEQ artifact in one
# contiguous, weight-independent region that no other tool allocates.
SEQ_STREAM_BASE = 0x0900_0000
SEQ_DATA_BASE = 0x0C00_0000
SEQ_STREAM_MAX = SEQ_DATA_BASE - SEQ_STREAM_BASE   # 48 MiB window
SEQ_DATA_MAX = W_BASE - SEQ_DATA_BASE              # 64 MiB window
SEQ_REC_BYTES = 16        # one SEQ record (docs/SEQ_ISA.md)
SEQ_ALIGN = 64            # LDC/EMB bursts: keep every SEQ region 64B aligned


# -------------------------------------------------- the DDR state region
# SEQ_ISA v2.1 / spec 2 + A1.1: the layer's DeltaNet state, KV cache and
# conv weights+state live in DDR and reach the layer by SLD/SST.  The three
# region bases are programmed into SB_DN/SB_KV/SB_CV in 64 KiB units, which
# is why every base below is 64 KiB aligned.  The strides are the SHIFTS
# the RTL applies (B15.1), not a product, so they are powers of two.
STATE_BASE_UNIT   = 1 << 16
STATE_DN_LAYER    = 1 << 20          # one DN transfer: 32 heads x 128 rows x 256 B (spec A1.1)
STATE_DN_HEAD     = 1 << 15          # the layout unit inside a layer block
STATE_KV_STRIDE   = 1 << 21          # 2 MiB per (layer, kvhead, K|V)
STATE_KV_EXP_OFF  = 1 << 20          # exponent side array inside the block
STATE_CV_STRIDE   = 1 << 17          # 8192 rows x 16 B
STATE_DN_BLOCKS, STATE_KV_BLOCKS, STATE_CV_BLOCKS = 24 * 32, 8 * 4 * 2, 24
STATE_T_MAX       = 4096


# WHERE the region sits.  S3's rule, and the ONE place it is written: the
# LAST channel, at 2 GiB into it.  That is above the weight pack (which
# `plan_weights` ASSERTS ends below EMB_BASE on every channel), and it is
# derived from the stream's CHANNEL COUNT alone -- so the emitter
# (ref/gen_layer_script.Mach.dump_state), the reference model
# (ref/seq_model.StateRegion), the chip TB's DDR model and this host all
# name the same address without any of them re-deriving the pack.  The
# 34-bit address carries the channel in bits [33:32], exactly as the layer's
# m_axis master sees it through the SmartConnect (spec 4).
#
# THE EMBEDDING TABLE IS THE HAZARD, and it is CHECKED, not assumed (S3 fix
# round 1, I4).  The table lives at EMB_BASE on CHANNEL 0 and its size is
# `vocab * 2 * H`: 485 MiB at H = 1024 (ends 0x7E4F_FFFF, below this base)
# but 970 MiB at H = 2048 (ends 0x9CA0_0000) and 1.9 GiB at H = 4096, both
# of which CONTAIN 0x8000_0000.  So `nch == 1` -- the only case that puts
# the region on channel 0 -- is refused unless the caller proves the table
# ends below it.  A 9B stream is nch = 4 and never reaches the check;
# `sw/infer.py` and `ref/seq_chat.py` can build an nch = 1 Mach and do.
STATE_MIN_BASE = 0x8000_0000


def emb_table_top(vocab, emb_row_bytes):
    """The first address ABOVE the embedding table on channel 0."""
    return EMB_BASE + int(vocab) * int(emb_row_bytes)


def plan_state_base(nch=1, vocab=None, emb_row_bytes=None):
    """The 34-bit base of the state region for an `nch`-channel stream.

    `vocab`/`emb_row_bytes` are only consulted when the region would land
    on CHANNEL 0 (nch == 1), which is the one case where the embedding
    table can reach it.  Absent, the conservative bound is used: the
    largest table this project plans for (H = 4096) tops out well above
    STATE_MIN_BASE, so an unqualified nch == 1 is REFUSED rather than
    silently overlapped.
    """
    assert 1 <= nch <= 4, nch
    b = ((nch - 1) * CH_STRIDE) + STATE_MIN_BASE
    assert b % STATE_BASE_UNIT == 0, hex(b)
    if nch == 1:
        end = plan_state(b)["end"]
        top = (emb_table_top(vocab, emb_row_bytes)
               if (vocab is not None and emb_row_bytes is not None)
               else emb_table_top(248320, 2 * 4096))
        assert top <= b or EMB_BASE >= end, (
            f"the state region [{b:#x}, {end:#x}) overlaps the embedding "
            f"table [{EMB_BASE:#x}, {top:#x}) on channel 0.  A single-channel "
            f"stream at this geometry has nowhere for the region: repack "
            f"over more channels, or move EMB_BASE.  (sw/hwmap's DDR map "
            f"above; S3 fix round 1, I4.)")
    return b


def state_dn_witnesses(plan, n=8, nbytes=4096):
    """`n` offsets into the DN region a zero-check should read back.

    PURE, so `--selftest` can drive it off-board (S3 fix round 1, I6/I7).
    Spec 2 "Initial contents" says the host writes the DN region to zero and
    spec 7.1 says it AUDITS the region like it audits the weights; a memset
    nobody reads back is not an audit.  The offsets are spread over the
    region and are 4 KiB aligned, and the FIRST and LAST blocks are always
    included -- a short write is the failure this catches, and it shows at
    the end.
    """
    lo, hi = int(plan["dn"]), int(plan["kv"])
    span = hi - lo
    assert span >= nbytes, (span, nbytes)
    n = max(2, int(n))
    out = []
    for i in range(n):
        off = (span - nbytes) * i // (n - 1)
        out.append(lo + (off & ~(nbytes - 1)))
    return sorted(set(out))


def plan_state(base):
    """Lay the three regions out from `base` (64 KiB aligned), B15.1 order."""
    assert base % STATE_BASE_UNIT == 0, hex(base)
    dn = base
    kv = dn + STATE_DN_BLOCKS * STATE_DN_HEAD             # 24 MiB
    cv = kv + STATE_KV_BLOCKS * STATE_KV_STRIDE           # 128 MiB
    end = cv + STATE_CV_BLOCKS * STATE_CV_STRIDE          # 3 MiB
    for a in (dn, kv, cv):
        assert a % STATE_BASE_UNIT == 0
    return dict(dn=dn, kv=kv, cv=cv, end=end)


# ------------------------------------------------------- the weight pack
def plan_weights(man, wdir=None, nch=1, rows_of=None):
    """Pack the manifest's weight images into DDR, variable stride.  THE
    weight-address authority: sw/layer_test.py, sw/seq_run.py, sw/chat_seq.py
    and ref/seq_format.py:plan_weights_from_wids all resolve to this function
    (the copy that used to live in layer_test.py is gone).

    A fixed 16 MiB per-wid stride only fits 80 images below EMB_BASE; a
    24-layer token script needs 187.  Instead lay the images out back-to-back
    from W_BASE in wid order, each start aligned up to WID_ALIGN.

    The image footprint is exactly nbeats*64 == nrows*stride == the file size
    (pack_ddr_rows emits nrows fixed-size, 64B-aligned rows and nothing else),
    so the intra-image row math the matvec engine uses (wbase = base + row*
    stride, wbeats = rc*stride/64) is untouched by the packing — only each
    image's base address moves.

    Group-size agnostic: `stride` and `nbeats` come from the manifest, which
    pack_ddr_rows already computed from the row format, so a g=64 image (one
    extra 64B scale beat per row when K > 2048) needs no special case.  It is
    WEIGHT-WIDTH agnostic for the same reason (V5): a W8 image (manifest
    `"w8": true`, ABSENT == W4) differs only in its stride.  The per-row
    arithmetic IS re-derived and asserted below, so a hand-edited manifest
    cannot silently mis-place an image — and that re-derivation has to know
    which row law to check against, because the SHAPE `ng` field means ng
    UNITS (K//128) in both widths while a W8 row streams 2*ng weight beats
    (ref/w4a8_ref.py row_beats8 / W8_SKETCH.md §2).

    NCH-INDEPENDENT (the default, `rows_of is None`) — every channel reserves
    the WHOLE image, because a 4-chan stream's MVGO WBASE is `base + r0*
    stride` with r0 a GLOBAL row index.  Returns `({wid: base}, top)`, ints.
    That is the layout every artifact frozen before R-c encodes, at nch=1 and
    at nch=4 alike; it is byte-for-byte what this function did before the
    per-channel repack was added, and passing `rows_of=None` is how a caller
    asks for it.

    PER-CHANNEL REPACK (`rows_of` given) — the V5 fit prerequisite: at 1.85
    GiB the W8 pack overflows the 1,280 MiB window a single span needs, while
    the busiest CHANNEL only holds ~465 MiB (V4_V5.md §5).  `rows_of(wid,
    nrows) -> [rows on channel 0, .., rows on channel nch-1]` (summing to
    nrows) says how the emitter split THAT image; each channel then advances
    its own cursor by only the rows it holds.  Returns `({wid: (base per
    channel)}, (top per channel))`.  A channel that holds zero rows of an
    image does not advance (its entry is that channel's next free address and
    is never read: a zero-row piece emits no MVGO).

    `wdir` is the directory the manifest's `file` entries live in; the image
    file size is cross-checked against nrows*stride when it is given.  Pass
    None to plan from a manifest with no files on disk (the fit checker).

    Returns (base_of_wid, top) where top is the first free address.
    """
    assert nch >= 1, f"nch {nch} must be >= 1"
    base, a = {}, [W_BASE] * nch
    for wid, m in sorted(man.items(), key=lambda kv: int(kv[0])):
        sz = int(m["nbeats"]) * 64
        assert sz == int(m["nrows"]) * int(m["stride"]), \
            f"wid {wid}: nbeats*64={sz} != nrows*stride"
        # v2 row format cross-check: stride == (K//128 + ceil((K/g)/32))*64
        # at W4, (K//64 + ceil((K/g)/32))*64 at W8; the SHAPE ng field is
        # the ng-UNIT count K//128 in every mode (= the weight-beat count
        # in W4 only).  See ref/w4a8_ref.py's row_beats/row_beats8.
        K, g = int(m["k"]), int(m.get("g", 128))
        w8 = bool(m.get("w8", False))
        assert g in (128, 64), f"wid {wid}: unsupported group size {g}"
        assert not (w8 and g == 64), \
            f"wid {wid}: w8 + g64 is not a defined row format"
        assert K % 128 == 0, f"wid {wid}: K={K} is not a multiple of 128"
        ng = K // 128
        wb = K // 64 if w8 else ng
        sb = -(-(K // g) // 32)
        assert int(m["ng"]) == ng, \
            f"wid {wid}: manifest ng={m['ng']} != ng units {ng}"
        assert int(m["stride"]) == (wb + sb) * 64, (
            f"wid {wid}: stride {m['stride']} != ({wb}w+{sb}s)*64 for "
            f"K={K} g={g} w8={int(w8)}")
        if wdir is not None:
            fsz = os.path.getsize(os.path.join(wdir, m["file"]))
            assert fsz == sz, \
                f"wid {wid}: {m['file']} is {fsz}B, manifest {sz}B"
        nrows, stride = int(m["nrows"]), int(m["stride"])
        if rows_of is None:
            rows = [nrows] * nch          # every channel reserves the image
        else:
            rows = [int(n) for n in rows_of(int(wid), nrows)]
            assert len(rows) == nch, \
                f"wid {wid}: rows_of returned {len(rows)} counts, nch={nch}"
            assert sum(rows) == nrows, (
                f"wid {wid}: the per-channel row counts {rows} sum to "
                f"{sum(rows)}, image has {nrows} rows")
        b = tuple(a)
        for c in range(nch):
            csz = rows[c] * stride
            a[c] += (csz + WID_ALIGN - 1) // WID_ALIGN * WID_ALIGN
        base[int(wid)] = b[0] if rows_of is None else b
    over = [(c, t) for c, t in enumerate(a) if t >= EMB_BASE]
    assert not over, (
        f"weight images ({len(man)} wids, "
        f"{max(a) - W_BASE} bytes packed from {W_BASE:#x}) reach "
        + ", ".join(f"chan {c} {t:#x}" for c, t in over)
        + f", past EMB_BASE {EMB_BASE:#x} — "
        + ("move EMB_BASE or split the images across DDR channels"
           if rows_of is None else
           "even repacked per channel this pack does not fit; move EMB_BASE"))
    return base, (a[0] if rows_of is None else tuple(a))


def _selftest_shape_word():
    """SHAPE packing — the one function in this file with real arithmetic.

    Gated by `make -C tb tb_matvec_chan`, the target that also drives the
    SHAPE word through the real CSR, so the layout is checked by the same
    run that checks the hardware.  (It used to hang off `tb_matvec_w8`,
    which G3.3 retired with the W8 engine mode.)
    """
    assert SHAPE_G64 == 1 << 28 and SHAPE_W8 == 1 << 29
    assert (SHAPE_ISA_PRE_G3, SHAPE_ISA_9B, SHAPE_ISA) == (1, 2, 2)
    assert SHAPE_MAX_NG == {1: 48, 2: 96}

    # ---- isa=1: the layout build_034/build_035 decode ------------------
    # PINNED to the words read off the four live SHAPE registers after the
    # 2B run, evidence/qwen2b/rd/RD_GATE.md:238 — so no future edit can
    # move the old layout without this failing.  (ch1 differs from ch0/2/3
    # only in `nrows`: the interleaved LM head gives it a smaller final
    # chunk, RD_GATE.md:240-243.)
    live = {
        (2048, 10, 16, 128, True): 0x20800290,   # ch0/ch2/ch3, 2B W8
        (512, 10, 16, 128, True): 0x20200290,    # ch1, 2B W8
        (2048, 5, 8, 128, False): 0x00800148,    # 0.8B W4 control, ch0/2/3
        (512, 5, 8, 128, False): 0x00200148,     # 0.8B W4 control, ch1
    }
    for (nr, sh, ng, g, w8), want in live.items():
        got = shape_word(nr, sh, ng, g=g, w8=w8, isa=1)
        assert got == want, \
            f"isa=1 shape_word({nr},{sh},{ng},g={g},w8={w8}) = {got:#010x}, want {want:#010x}"
    base1 = (13 << 12) | (7 << 6) | 32
    cases1 = {
        (128, False): base1,                         # legacy W4 g128
        (64, False): base1 | SHAPE_G64,              # W4 g64 (v2)
        (128, True): base1 | SHAPE_W8,               # W8 (V5)
    }
    for (g, w8), want in cases1.items():
        got = shape_word(13, 7, 32, g=g, w8=w8, isa=1)
        assert got == want, f"isa=1 shape_word(g={g}, w8={w8}) = {got:#x}, want {want:#x}"
        assert (got >> 30) == 0, "isa=1 bits [31:30] are spare and must stay 0"
    # w8 + g64 has no defined row format (W8 is g128-cadence only)
    try:
        shape_word(13, 7, 32, g=64, w8=True, isa=1)
        raise SystemExit("FAIL: shape_word accepted w8 + g64")
    except AssertionError as ex:
        assert "not a defined row format" in str(ex), ex

    # ---- isa=2: the layout THIS TREE's rtl/matvec_chan.sv decodes ------
    # {spare[31:29], ng[28:22], nrows[21:6], sh[5:0]} -- checked FIELD BY
    # FIELD against an independent unpack, at the boundary of every field
    # and at the three 9B row shapes.
    def unpack2(w):
        return ((w >> 22) & 0x7F, (w >> 6) & 0xFFFF, w & 0x3F, w >> 29)
    b2 = shape_word(13, 7, 32)
    assert b2 == (32 << 22) | (13 << 6) | 7, f"{b2:#010x}"
    assert unpack2(b2) == (32, 13, 7, 0)
    for ng in (1, 32, 64, 96):
        for nrows in (0, 1, 4096, 65535):
            for sh in (0, 1, 63):
                w = shape_word(nrows, sh, ng)
                assert unpack2(w) == (ng, nrows, sh, 0), \
                    f"isa=2 round-trip broke at ng={ng} nrows={nrows} sh={sh}"
    # the default IS isa=2, and it is NOT the old word
    assert shape_word(13, 7, 32, isa=2) == shape_word(13, 7, 32)
    assert shape_word(13, 7, 32) != shape_word(13, 7, 32, isa=1)
    # the two stripped modes have NO isa=2 encoding
    for kw, needle in (({"g": 64}, "g64 has no isa=2 encoding"),
                       ({"w8": True}, "w8 has no isa=2 encoding")):
        try:
            shape_word(13, 7, 32, **kw)
            raise SystemExit(f"FAIL: isa=2 shape_word accepted {kw}")
        except AssertionError as ex:
            assert needle in str(ex), ex
    # FIELD-WIDTH negative control: one past every field must be REFUSED,
    # in both layouts, rather than silently spilling into its neighbour
    for isa, over in ((1, [(0, 0, 64), (0, 64, 8), (1 << 16, 0, 8)]),
                      (2, [(0, 0, 128), (0, 64, 8), (1 << 16, 0, 8)])):
        for nr, sh, ng in over:
            try:
                shape_word(nr, sh, ng, isa=isa)
                raise SystemExit(
                    f"FAIL: isa={isa} shape_word accepted nrows={nr} sh={sh} ng={ng}")
            except AssertionError as ex:
                assert ("does not fit" in str(ex)
                        or "engine envelope" in str(ex)), ex
    # ENVELOPE, both sides, both layouts: the engine's own 1..MAX_NG guard is
    # sim-only, so the packer is what a LIVE board gets.  ng = 96 is also the
    # whole reason the layout moved, and it does NOT fit isa=1's engine.
    for isa, mx in SHAPE_MAX_NG.items():
        assert shape_word(13, 7, 1, isa=isa) is not None
        assert shape_word(13, 7, mx, isa=isa) is not None
        for bad_ng in (0, mx + 1):
            try:
                shape_word(13, 7, bad_ng, isa=isa)
                raise SystemExit(
                    f"FAIL: isa={isa} shape_word accepted ng={bad_ng}")
            except AssertionError as ex:
                assert "engine envelope" in str(ex), ex

    # ---- the VERSION -> isa map: EXPLICIT, and no default -------------
    assert shape_isa_for_version(0x54443B9F) == SHAPE_ISA_PRE_G3   # build_035
    assert shape_isa_for_version(0x4F908DF2) == SHAPE_ISA_PRE_G3   # build_034
    assert shape_isa_for_version(0xC973C18A) == SHAPE_ISA_9B       # build_041
    # AN UNKNOWN VERSION MUST REFUSE: a default is a silent mis-drive.
    try:
        shape_isa_for_version(0xDEADBEEF)
        raise SystemExit("FAIL: shape_isa_for_version defaulted an unknown "
                         "VERSION instead of refusing")
    except UnknownBitstream as ex:
        assert "not a bitstream this checkout knows" in str(ex), ex
    # and the demonstration, so the refusal is not an abstract rule:
    _b34 = shape_word(2048, 5, 8, isa=SHAPE_ISA_PRE_G3)
    _b9b = shape_word(2048, 5, 8, isa=SHAPE_ISA_9B)
    assert _b34 == 0x00800148 and _b9b == 0x02020005
    assert ((_b9b >> 12) & 0xFFFF, (_b9b >> 6) & 0x3F, _b9b & 0x3F) \
        == (8224, 0, 5), "the isa=1 decode of an isa=2 word"
    print("HWMAP SHAPE_WORD SELFTEST PASS: "
          f"isa=1 pinned to RD_GATE {0x20800290:#010x}/{0x20200290:#010x} "
          f"(+ the 0.8B W4 control), g64={cases1[(64, False)]:#010x} "
          f"w8={cases1[(128, True)]:#010x}, w8+g64 refused; "
          f"isa=2 ng[28:22] nrows[21:6] sh[5:0] round-trips at "
          "ng 1/32/64/96 x nrows 0/1/4096/65535 x sh 0/1/63, "
          "spare [31:29] zero, g64/w8/over-wide fields and ng outside "
          "1..MAX_NG all refused; an UNKNOWN VERSION refuses "
          "(034/035 isa=1, 041 0xc973c18a isa=2)")


# SR7 fix round 1 (I-1): the BM1 block's IDENT (docs/SEQ_ISA.md B16, SEQ
# 0x100) and what each admitted sequencer bitstream is EXPECTED to read there,
# keyed by VERSION — the ONE table the identity tools read
# (evidence/qwen9b/bm/bm1_ident.py).  Pre-BM1 bitstreams read the unmapped
# value; every netlist from build_042_bm1 on carries the block, R1 included
# (rtl/seq_unit.sv's BM_IDENT).  sw/seq_run.SEQ_BM_IDENT is the same word
# (sr7_host_tdd.py (j) ties them).  Placed after every cited definition (only
# the __main__ guard below it moved) so no line anyone cites shifts.
SEQ_BM_IDENT = 0xFAB1B301
SEQ_BM_IDENT_BY_VERSION = {
    0x4F908DF2: SEQ_CSR_UNMAPPED,   # build_034_po2 (no BM1 block)
    0x54443B9F: SEQ_CSR_UNMAPPED,   # build_035_fp2a (2B W8; no BM1 block)
    0xC973C18A: SEQ_CSR_UNMAPPED,   # build_041_ckr2 (no BM1 block)
    0x9B588E78: SEQ_BM_IDENT,       # build_042_bm1
    0xE3C2FF1E: SEQ_BM_IDENT,       # build_044_r1_incr (R1 + BM1)
    0x266E3AE7: SEQ_BM_IDENT,       # build_045_r2_incr (R1 + R2 + BM1; SR14)
}
# SR14 (evidence/qwen9b/sr/SR14_R2_BUILD.md): the R2 bitstream's SHAPE row,
# assigned here rather than inside SHAPE_ISA_BY_VERSION so no cited line
# moves (the dict's closing line says so).  isa=2: bits 29/30 are
# XBANK/RBANK on this netlist (docs/SEQ_ISA.md B17.2).
SHAPE_ISA_BY_VERSION[0x266E3AE7] = SHAPE_ISA_9B   # build_045_r2_incr (R2)
# R3-10 (evidence/qwen9b/sr/R3_10_BUILD.md): the R3 bitstream's rows, both
# assigned here (after every cited line, so none moves): isa=2, BM1 block.
SHAPE_ISA_BY_VERSION[0x2E874592] = SHAPE_ISA_9B   # build_046_r3_incr (R3)
SEQ_BM_IDENT_BY_VERSION[0x2E874592] = SEQ_BM_IDENT  # build_046_r3_incr (R3)


if __name__ == "__main__":
    _selftest_shape_word()
