"""hwmap.py — the one place the fable5_llm device map is written down.

Every host tool (matvec_test.py, layer_test.py, tok_meter.py, ...) imports
these constants instead of re-declaring them.  They must track the RTL:

  rtl/csr_block.sv     stage-1 CSR block          (AXI-Lite BAR 0x0000)
  rtl/matvec_chan.sv   per-DDR-channel matvec     (BAR 0x1000*(c+1))
  rtl/layer_chan.sv    layer-orchestration engine (BAR 0x5000)
  rtl/seq_unit.sv      on-chip command sequencer  (BAR 0x6000)

and the DDR layout that sw/layer_test.py:plan_weights() packs.
"""

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

# R_SHAPE layout:  {g64[28], nrows[27:12], sh[11:6], ng[5:0]}
#                  (RTL latches wdata[27:12] — 16 bits, not 13;
#                   SEQ_ISA v1.6 B11-2)
#   ng   = WEIGHT-beat count of one row = K//128, in BOTH group modes
#   g64  = W4 group-size mode: 0 = g128 legacy (bit-identical to pre-v2),
#          1 = g64 (v2 row format: each 64B weight beat carries TWO groups
#          of 64, and ceil((K/64)/32) scale beats follow the weight beats —
#          see ref/w4a8_ref.py's module header).  The per-image group size
#          travels in the manifest as "g" (ABSENT == 128), so hosts write
#          `SHAPE_G64 if int(m.get("g", 128)) == 64 else 0`.
SHAPE_G64 = 1 << 28


def shape_word(nrows, sh, ng, g=128):
    """Pack the matvec_chan SHAPE CSR word for one engine run."""
    assert g in (128, 64), f"unsupported W4 group size {g}"
    return ((nrows << 12) | (sh << 6) | ng) | (SHAPE_G64 if g == 64 else 0)


def mv_base(c):
    """AXI-Lite byte offset of matvec_chan c (c = 0..3)."""
    return 0x1000 * (c + 1)


# ----------------------------------------------- layer_chan (base 0x5000)
LB = 0x5000
L_CMD, L_STAT, L_ARG0, L_ARG1, L_ARG2 = LB + 0x00, LB + 0x04, LB + 0x08, LB + 0x0C, LB + 0x10
L_SPTR, L_SWIN, L_EOUT, L_TCNT, L_IDENT = LB + 0x14, LB + 0x18, LB + 0x1C, LB + 0x20, LB + 0x24
L_AMAXI, L_AMAXV = LB + 0x28, LB + 0x2C
L_LAYER = LB + 0x30       # {kv_slot[10:8], dn_slot[4:0]} bank select
L_LCYC = LB + 0x34        # 32-bit busy-cycle accumulator @ ACLK_HZ;
                          # ANY write clears it, so read-and-difference
# ISA v1.3 XRF window + vec_alu op-8 probe readback (rtl/layer_chan.sv:26-29).
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
TOPK_IDENT_VAL = 0xFAB1704B
TOPK_K = 32               # capture depth; reset ONLY by AMAX fresh flag
LAYER_IDENT = 0xFAB1E5A0
L_ST_BUSY, L_ST_ERR_OP = 0x1, 0x2
SCRATCH_WORDS = 16384     # layer_chan scratchpad depth (16K x 16b)

# layer_chan opcodes (rtl/layer_chan.sv header)
OP_VN, OP_VNW, OP_ROPET, OP_ROPE = 1, 2, 3, 4
OP_CONVW, OP_CONV, OP_GATE, OP_DNST = 5, 6, 7, 8
OP_KVAP, OP_ATTN, OP_ALU, OP_DNZ = 9, 10, 11, 12
ALU_AMAX32 = 10           # vec_alu op 10, arg2[0]=1 starts a fresh scan

# ------------------------------------------- seq_unit (SEQ CSR block @ 0x6000)
# rtl/seq_unit.sv:19-51 is authoritative; docs/SEQ_ISA.md v1.5 describes it.
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

SEQ_IDENT = 0xFAB1E5E0
SEQ_XRF_N = 8
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

# err_code (STATUS[31:24]) — rtl/seq_unit.sv:40-51 + rtl/seq_movers.sv:115-118
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
#                                        (sw/layer_test.py:plan_weights;
#                                        model_v2_s1 = 187 images, 398 MiB).
#                                        plan_weights ASSERTS the pack ends
#                                        below EMB_BASE.
#   0x6000_0000 .. 0x7E4F_FFFF  485 MiB  EMB_BASE: embedding table,
#                                        vocab x 2048 B rows (248,320 rows =
#                                        0x1E50_0000 B for Qwen3.5-0.8B).
#   0x7E50_0000 .. 0xFFFF_FFFF          FREE (2.4 GiB tail).
#
# ref/seq_format.py's own SEQ_DATA_BASE/SEQ_STREAM_BASE (0x8000_0000 /
# 0x9000_0000) are EMITTER-SIDE defaults that land in this free tail; they
# are baked into the LDC records as ABSOLUTE addresses, so sw/seq_run.py
# RELOCATES the stream by (SEQ_DATA_BASE - meta["seq_data_base"]) instead of
# uploading at the emitter's addresses.  Keeping the runtime copies below
# W_BASE puts every SEQ artifact in one contiguous, weight-independent
# region that no other tool allocates.
SEQ_STREAM_BASE = 0x0900_0000
SEQ_DATA_BASE = 0x0C00_0000
SEQ_STREAM_MAX = SEQ_DATA_BASE - SEQ_STREAM_BASE   # 48 MiB window
SEQ_DATA_MAX = W_BASE - SEQ_DATA_BASE              # 64 MiB window
SEQ_REC_BYTES = 16        # one SEQ record (docs/SEQ_ISA.md)
SEQ_ALIGN = 64            # LDC/EMB bursts: keep every SEQ region 64B aligned
