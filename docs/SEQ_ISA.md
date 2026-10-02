# SEQ ISA v2.3 (2026-09-27): the sequencer RTL round — SEQ_CAPS, the FENCE channel mask (B17)
# (v2.1 (2026-09-04): layer state in DDR — SLD/SST, cache slots, SB_*/SDMA CSRs)
# (v2.0 — AS-BUILT CONTRACT, 2026-09-01 — stands unchanged below; B15 at the bottom is v2.1's contract and its RTL lands at Task S2.)
# = the v1.5 FROZEN TEXT (unchanged, below) + AS-BUILT ADDENDA (bottom).
#
# v2.0 (G3.1) RE-ENCODES THE LAYER COMMAND ARG WORDS: clean 16+16 pairs, no
# scattered bits anywhere, DNST's two scalar pointers moved into a new DNSB
# layer CSR.  **Section B14 at the bottom is the current truth and WINS over
# B12.**  B12 is RETAINED, unedited, as `build_034`/`build_035`'s ISA —
# those bitstreams still run, served from a pre-G3 checkout — and reading
# B12 as current is the one way to get this file wrong.

THIS FILE IS THE SINGLE AS-BUILT TRUTH for the SEQ instruction set, the
SEQ CSR block, and the layer_chan / matvec_chan CSRs the ISA addresses.

Reading rule:
  * Everything from "## Record" to the end of the "v1.5 rulings" section
    is FROZEN CONTRACT TEXT — the historical record of what was ratified
    and when. It is kept VERBATIM and is never rewritten in place.
  * "AS-BUILT ADDENDA (v1.6)" at the bottom records what the shipped RTL
    actually does, re-verified line by line against rtl/seq_unit.sv,
    rtl/seq_movers.sv, rtl/layer_chan.sv, rtl/vec_alu.sv and sw/hwmap.py.
  * WHERE THE TWO DISAGREE, THE ADDENDA WIN. Every such case is listed
    explicitly in section B11 — nothing is corrected silently.
  * Section B12 (v1.7) is the ONE place where v1.7 CHANGES the contract
    rather than recording it: every scratch address field is now 15 bits.
    Where B12 and anything above it disagree about an address width or a
    field's bit layout, B12 WINS.
  * Section B13 (v1.7) adds one register — EMBLOG2 at SEQ 0x60 — and with
    it CHANGES the EMB opcode's address semantics: the row stride is no
    longer the fixed 2048 B of B4, it is `XRF[3] << EMBLOG2`. No other
    register changes, and EMBLOG2's RESET value reproduces the old
    arithmetic exactly, but B13 WINS over B4's EMB entry.

v1.0 -> v1.1: eleven ambiguities (A1-A11, ref/seq_format.py header)
resolved by orchestrator ruling; two new opcodes (LDC, XOP).
v1.5 -> v1.6 (2026-08-12): as-built consolidation. No opcode, field or
semantic CHANGE is introduced here; v1.6 folds in the 2026-08-09 chat-seq
corrections, the rung-4 OUT FIFO rework, the rung-4 TOPK-32 CSR block and
the g64 SHAPE bit, all of which shipped and are already on silicon
(build_033).
v1.6 -> v1.7 (2026-08-13, track R task R-b): the layer scratchpad doubles
to 32768 words and EVERY scratch address field becomes 15 bits. This IS a
field-layout change — the first since v1.1 — and it is back-compatible by
construction: each new bit 14 lives in a bit that
evidence/qwen2b/rb/spare_bits_report.txt proves was never set by any
pre-R-b stream, so every frozen 0.8B script (whose addresses are all
< 16384) emits zeros there and replays bit-identically. See B12.
v1.7 also ADDS the EMBLOG2 CSR (SEQ 0x60): the EMB row size stops being a
build-time constant so ONE bitstream serves H=1024 and H=2048. Its reset
value is today's 2048 B row, so a host that never writes it sees no
change at all. See B13.  **(G3.4 moved the RESET to 13 = 8192 B, the 9B
row — see B13's dated note.  The paragraph above is v1.7's, kept as the
record of what R-b shipped.)**

All sequencer workstreams (reference, generator, RTL, TB) build to this
document. Changes require re-freezing here first.

# ================= v1.5 FROZEN TEXT BEGINS (verbatim) =================
# SEQ ISA v1.5 — FROZEN CONTRACT (re-frozen 2026-08-09 after wave-3E)

## Record: 128 bits (16 B), little-endian fields

  [7:0]    opcode
  [15:8]   flags
  [31:16]  target        (register/space id, per opcode)
  [63:32]  imm32
  [95:64]  addr_lo       (DDR/scratch addresses, per opcode)
  [127:96] len_or_addr_hi

## Immediate indirection (flags[3:0])

  0x0  imm32 used as-is
  0x1  imm32 + XRF[flags[7:4]]        (signed add, low 17 bits used
                                       where the consumer is a cfg_p0)
XRF: 8 x signed 18b. [0]=e_x (DYNQ8 EOUT), [1]=k_dn (DYNQ16 dst dn),
[2]=k_attn (DYNQ16 dst attn), [3..7] spare. Writers: DYNQ8 retires ->
XRF[0]; DYNQ16 retires -> XRF[imm32[1:0] ? see ALU op below]. Read by
any record via indirection. Reset 0.

## Opcodes

  0x01 CSRWR   target=csr_id, write imm32 (post-indirection). csr_id
               space: 0x0nn = layer_chan byte offset nn; 0x1cn =
               matvec chan c reg n (layer/matvec maps in hwmap.py).
  0x02 CMD     CSRWR to layer CMD + WAIT busy-clear + err check
               (the C-record macro; ARG0-2 via preceding CSRWRs).
  0x03 MOVX    scratch[addr_lo, len] int8-packed -> engine chan
               (flags[7:4]) XWIN. Burst; self-fencing.
  0x04 MOVY    engine chan RES rows [0,len) -> dequant -> int16 pairs
               or int16 (flags bit4: pairs32/int16) at scratch addr_lo.
               Dequant shift = imm32 (post-indirection, so e_x-relative
               works); round-half-away; clip16 when int16 mode.
  0x05 MVGO    matvec chan (flags[7:4]) WBASE/BEATS/SHAPE from
               addr fields + imm32, start, WAIT done.
  0x06 EMB     DDR row (EMB_BASE + token*2048B, token from XRF[3]) ->
               scratch addr_lo, 1024 int16. Token XRF[3] is written by
               AMAXL or by host (prompt feed).
  0x07 AMAXL   read layer AMAXI -> XRF[3] and push to the OUT FIFO CSR.
  0x08 JMP     absolute record index imm32 if flags==0; flags 0x1:
               decrement token counter TCNT_SEQ, jump if nonzero.
  0x09 FENCE   drain all movers/engines.
  0x0A HALT    stop; raise done IRQ/CSR bit.
  0x0B LDC     DDR const blob [addr_lo + (flags&1 ? XRF[flags[7:5]] : 0),
               len words] -> scratch[target]. The <prefix>.seqdata.bin
               sidecar is part of the stream artifact. (A9/A10)
  0x0C XOP     XRF[target[2:0]] = s1*XRF[imm32[2:0]] + s2*XRF[imm32[6:4]]
               + simm18(imm32[31:14]); s1,s2 in {0,+1,-1} from
               imm32[9:8]/[11:10]. Subsumes XADD; solves the two-addend
               requant shift (A2/A3): precombine into a spare XRF entry,
               then single IND_ADD at the consumer.

## Field-packing rulings (A1/A7/A8)
  - MOVX/MVGO: engine chan in flags[7:4]; indirection FORBIDDEN there.
  - MOVY: chan = target[3:0]; pairs32/int16 mode = flags[4]; XRF index
    for the shift indirection = flags[7:5].
  - MVGO: imm32=SHAPE, addr_lo=WBASE[31:0],
    len_or_addr_hi={beats[23:0], wbase[39:32]}.
  - csr_id space: 0x0nn layer byte offset; 0x1000|chan<<8|byte_off for
    matvec; 0x2nn sequencer block (XRF write, TCNT_SEQ).
  - MOVY/MVGO pair 1:1 (no RES row offset) — RTL constraint (A6).
  - XRF entries signed 18b EXCEPT XRF[3] (token id) unsigned 18b (A11).
  - Only IND_ADD exists; sign combinations go through XOP (A2).

## New compute ops (semantics frozen by ref/layer_fixed.py, agent A)

  vec_alu op 12 DYNQ16: over n int32 pairs at srca: k = bf_shift(max|x|)
    (bitlen(absmax)-15, +1 fixup, guard 0 — EXACTLY layer_fixed.bf_shift);
    writes rshr64s(x,k) as int16 to dst; latches k -> XRF[1] or XRF[2]
    per cfg_p0[0]. cfg_p0[1]=1: clamp k at 0 (attn/op-8 semantics).
  vecnorm EPS-NORM: selected by ARG2[0]=1 with mode field = 2 (the
    2-bit VN mode cannot widen; ARG2 was hardwired 0, so this is
    back-compatible — A4). XRF index for k in ARG2[3:1]. Integer/ROM
    semantics FROZEN in ref/layer_fixed.py (eps_norm_fx, agent A);
    proven 0-LSB-identical to the host float scale path on the
    equivalence soak. The RTL builds to that file.

## Sequencer CSR block (new, AXIL at a free offset in csr_0 space)

  SEQ_BASE_LO/HI (DDR addr of record list), SEQ_LEN, CTRL at +0x00
  {START=bit0, ABORT=bit1 — there is NO separate SEQ_ABORT register;
  as-built correction ratified 2026-08-09, see docs/CHAT_SEQ_SPEC.md},
  SEQ_STATUS {halted, err, err_code[31:24], out_cnt[20:16] — pc is NOT
  in STATUS; it is its own 32-bit reg at +0x14}, OUT_FIFO at +0x18
  (generated token ids; READ IS THE POP; depth 16; overflow drops
  silently; only hard reset clears it), IN slot: host writes prompt
  tokens by writing XRF[3] + starting per-step region, or (v1 simple)
  host lays the whole prompt loop out as records. v1 keeps host = load
  stream, START, drain OUT FIFO (drain only while halted).

## Arbitration + clocks

SEQ is a second AXI-Lite master via the existing interconnect; host
MUST NOT touch layer/matvec CSRs while SEQ_STATUS.busy (host-side rule,
also guarded by SEQ err on unexpected STATUS). Movers are AXI4 masters
through the EXISTING interconnect only — NO new CDC structures in v1
(project rule; option B needs explicit user approval).

## v1.2 ruling (post wave-1A, 2026-08-08)
  attn k_a: vec_alu op 8 gains a pre-shift max|prod| running-max latch
  -> XRF (probe mode); schedule = probe pass, XOP to form k_a, real
  pass — the double-pass infer.py already runs on silicon. DYNQ16 is
  NOT used for k_a in v1 (op-8 products never land in scratch as int32
  — wave-1A gap note).

## v1.3 rulings (post wave-2C)
  - op-8 probe select = cfg_p0[6] (NOT p0[2]: op-8 has no inert low bit;
    [5:0] is the shift, >=64 was flush-to-zero dead space — audited all
    20 committed scripts, p0 <= 15). p0 in [64,127] = probe, shift p0-64.
  - The probe latches the FINISHED k_a (attn_o_shift semantics, clamp0)
    directly into XRF[2]; raw max|prod| on MAXPL/MAXPH CSRs for debug.
    The XOP step in the attn double-pass schedule is OPTIONAL (only for
    combined-exponent consumers like the o_proj requant, which still
    uses XOP to fold -e_x - k_a + const into a spare XRF entry).
  - op-8 probe target is fixed XRF[2]; vec_alu k_out is signed 7b
    (probe k can reach 33); vecnorm cfg_k stays signed 6b (DYNQ16-only).

## v1.4 rulings (post wave-2D, ratifying the built reality)
  - IND_SUB (0x2) EXISTS (implemented in seq_format + seq_unit; the
    v1.1 "only IND_ADD" line is superseded).
  - XOP sign code 11 = decode error (D-1). 0x0C is XOP everywhere;
    XADD spelling in seq_format to be re-encoded by the emitter
    (6 records/token, no ISA change).
  - LDC XRF index = flags[7:4] (as implemented; 3 LSBs significant).
  - JMP bound: target record index must be < nrec (err otherwise).
  - MVGO target[0] = NO-WAIT variant (start channel, no done-poll;
    FENCE drains). 0 in every current stream = bit-identical today;
    emitter may exploit for multi-channel overlap (~+2.4 tok/s).
  - Known slave hazards (worked around in seq_movers, candidates for a
    later slave patch): matvec RES_DATA needs >=3-cycle read spacing;
    STATUS.done sticky across the doorbell CDC.

## v1.5 rulings (post wave-3E)
  - 0x0C is XOP everywhere (XADD spelling dead); imm32[3]/imm32[7]
    reserved 0. MVGO target[15:1] and MOVX target reserved 0.
  - XRF[5] = o_proj folded shift scratch (XOP -XRF[0]-XRF[2]+const).
  - A3/A10 CLOSED: full_attention stacks loop with dyn_ka (one op-8
    probe covering ALL heads' products in a single op — vec_alu clears
    maxp at dispatch and the k latch is overwrite, so per-head probes
    are WRONG by construction; the emitter's attn block re-order is
    normative). Optional later RTL nicety: sticky-maxp bit.
  - MVGO no-wait (target[0]) verified full-chip (.enw stream).

# ================== v1.5 FROZEN TEXT ENDS (verbatim) ==================


# ======================================================================
# AS-BUILT ADDENDA (v1.6, 2026-08-12)
# ======================================================================

Every statement below was re-derived from the RTL/sw named beside it —
none of it is copied forward from an older doc. Sources and the commit
they were read at (HEAD ae5a316, board build_033, netlist 0x33D720E5):

  rtl/seq_unit.sv    the sequencer: CSR block, decode, validate, issue
  rtl/seq_movers.sv  MOVX / MVGO / MOVY / FENCE + the m_axib burst master
  rtl/layer_chan.sv  layer CSR map, XRF master copy, TOPK-32 sibling
  rtl/vec_alu.sv     the compute ops the ISA's CMD records dispatch
  rtl/matvec_chan.sv SHAPE/CTRL/STATUS the MVGO record programs
  sw/hwmap.py        the host-side device map (closest current truth)

Chronology of what is folded in here:
  2026-08-05  MVGO SHAPE gains g64 (bit 28), v2 W4 row format   -> B9
  2026-08-22  MVGO SHAPE gains w8 (bit 29), V5 INT8 weights   -> B9
  2026-08-09  chat-seq as-built corrections (CTRL[1]=ABORT, no
              pc field in STATUS)                               -> B2
  2026-08-11  rung 4 S5: TOPK-32 CSR block at layer 0x48..0x58  -> B8
  2026-08-11  rung 4 S6: OUT FIFO depth 64, derived of_cnt,
              sticky of_ovf in STATUS, pop-only-if-delivering   -> B3

---------------------------------------------------------------------
## B1. SEQ CSR block — as-built map (rtl/seq_unit.sv:24-48)
---------------------------------------------------------------------

4 KB AXI-Lite window; create_project.tcl maps seq_0's s_axil at BAR byte
offset 0x6000, which is what sw/hwmap.py:210 (`SB`) and
ref/seq_format.SEQ_CSR_BASE assume. Every register here is host-writable
over AXI-Lite; only TWO of them are also writable IN-STREAM, through the
ISA's 0x2nn CSRWR space, and those writes never leave the sequencer as
AXI traffic: 0x20 TCNT_SEQ and 0x40+4i XRF[i] (B4, CSRWR). An in-stream
XRF write is additionally mirrored into layer_chan; a host XRF write is
not (B5).

  off   name      acc  contents
  0x00  CTRL      W    bit0 START (ignored while busy), bit1 ABORT
                  R    {29'b0, halted, err, busy}
  0x04  STATUS    R    {err_code[31:24], of_ovf[23], out_cnt[22:16],
                        13'b0, halted[2], err[1], busy[0]}
  0x08  BASE_LO   RW   record-list DDR byte address [31:0]
  0x0C  BASE_HI   RW   record-list DDR byte address [33:32]
  0x10  LEN       RW   records in the stream (the JMP/pc bound)
  0x14  PC        R    current record index
  0x18  OUT_FIFO  R    {valid[31], 13'b0, token[17:0]} — READ IS THE POP
  0x1C  OUT_CNT   R    {25'b0, entries[6:0]}, 0..64
  0x20  TCNT_SEQ  RW   token counter consumed by JMP flags 0x1
  0x24  ENTRY     RW   record index START jumps to (pc <= ENTRY)
  0x28  IDENT     R    0xFAB1E5E0
  0x2C  PERF_CYC  R    cycles busy since START (@ ACLK 250 MHz)
  0x30  PERF_REC  R    records retired since START
  0x34  PERF_AXW  R    AXI-Lite writes issued
  0x38  PERF_AXR  R    AXI-Lite reads issued
  0x3C  PERF_FST  R    {fetch-starved cycles[31:1], xrf_ovf[0]}
  0x40+4i XRF[i]  RW   i = 0..7, raw 18b ({14'b0, raw18} on read)
  0x60  EMBLOG2   RW   log2 of the EMB row size in BYTES, reset **13**
                       (8192 B, the 9B row — G3.4; it was 11 through R-d).
                       Legal 8..13; a write outside that is REJECTED (B13).

  Reads outside the map return 0xDEADC0DE (`rtl/seq_unit.sv:1641`).
  PERF_FST bit0 is the STICKY xrf_ovf flag, not a cycle count: an XOP
  result that did not fit 18 bits was truncated (B5).

EMBLOG2 (0x60) is host-writable ONLY: like the rest of the block it is not
reachable from the ISA's 0x2nn CSRWR space, and unlike TCNT_SEQ/XRF it has
no in-stream form at all — a record that targets 0x260 halts with err 0x07
(B4, unknown CSR space). See B13.

WHAT A START DOES NOT CLEAR (`rtl/seq_unit.sv:1008-1016`, verified against the
reset block at `rtl/seq_unit.sv:958-979`): the OUT FIFO contents, of_ovf, the XRF,
xrf_ovf, TCNT_SEQ, BASE/LEN/ENTRY. START clears only busy/halted/err/
err_code/abort_req and the five PERF counters, and sets pc <= ENTRY.
Only a hard reset clears the rest. This is the contract the host chat
loop depends on (sw/chat_seq.py drains the FIFO before every START).

---------------------------------------------------------------------
## B2. CTRL / STATUS — as-built (ratified 2026-08-09, widened 2026-08-11)
---------------------------------------------------------------------

The v1.1 text sketched "SEQ_STATUS {halted, err, err_code[31:24],
out_cnt[20:16]}" and implied a SEQ_ABORT register. As built:

  * ABORT is CTRL bit 1 (`rtl/seq_unit.sv:1325`, `abort_req`). There is NO
    separate SEQ_ABORT register and never was. Ratified 2026-08-09,
    docs/CHAT_SEQ_SPEC.md:145.
  * ABORT is honoured at a RECORD BOUNDARY only (tested in I_FETCH,
    `rtl/seq_unit.sv:1028`, in I_FETCH at `:1027`) and raises err_code 0x0C. There is no watchdog on
    I_SYNCW / I_AMAXW / I_BULK*, so a wedged DDR read is NOT abortable —
    it needs a reprogram.
  * STATUS has no pc field. pc is its own 32-bit register at +0x14.
  * STATUS bit layout, as built (`rtl/seq_unit.sv:1610-1611`), after rung 4 S6
    widened out_cnt from 5 to 7 bits and moved of_ovf in beside it:

      [31:24] err_code   [23] of_ovf   [22:16] out_cnt(0..64)
      [15:3]  reserved 0 [2]  halted   [1] err   [0] busy

    sw/hwmap.py:286-291 (SEQ_ST_OUTCNT_MASK = 0x7F, SEQ_ST_OF_OVF =
    1<<23) and hwmap.seq_status() decode exactly this.

---------------------------------------------------------------------
## B3. OUT FIFO — as-built (rung 4 S6, 2026-08-11)
---------------------------------------------------------------------

Written by AMAXL (B4) and drained by the host through OUT_FIFO (0x18).

  * DEPTH 64 (`rtl/seq_unit.sv:387`, `OF_DEPTH`; was 16). The old depth silently
    dropped tokens on any launch longer than 16 tokens.
  * of_cnt is DERIVED, not stored: `of_cnt = of_wp - of_rp` over two
    7-bit pointers with the extra MSB that distinguishes full from empty
    (`rtl/seq_unit.sv:389-391`). This retires an entire race class: push
    (I_AMAXW) and pop (csr_of_pop) live in the same always_ff and used to
    both assign a third `of_cnt` register, so a host pop landing on an
    AMAXL push lost the push's increment. sw/chat_seq.py:93 documents the
    host-side workaround that is no longer needed.
  * OVERFLOW DROPS, NEVER STALLS. A push into a full FIFO is discarded
    and sets the sticky of_ovf (`rtl/seq_unit.sv:1268-1271`). Fullness is
    judged on the PRE-pop count, so a push racing a host pop on a full
    FIFO is dropped rather than squeezed into the slot being freed.
  * of_ovf is STICKY UNTIL HARD RESET — not cleared by START, by a halt,
    or by draining. A host that sees it must treat every later token of
    the session as suspect (sw/hwmap.py:287-291).
  * READ IS THE POP, and the pop now happens ONLY IF THE READ ACTUALLY
    DELIVERED A TOKEN: `csr_of_pop <= (of_cnt != 7'd0)` (`rtl/seq_unit.sv:1624`).
    With the previous unconditional strobe, a read that reported EMPTY at
    its accept edge still popped one cycle later if an AMAXL push landed
    on that same edge — an entry consumed by nobody. Both fixes are
    covered by the tb_seq_unit +ofrace directed test.
  * bit31 of the OUT_FIFO word is the valid flag; the token is bits
    [17:0] (an unsigned 18-bit id, matching XRF[3]).

---------------------------------------------------------------------
## B4. Opcode field packing — as-built table
---------------------------------------------------------------------

Record layout is unchanged (128 b LE, four u32 words). Field names below
are the frozen ones. "err" gives the err_code raised by the one-cycle
decode validator (`rtl/seq_unit.sv:765-850`); execution-time errors are in B6.

0x01 CSRWR  flags[3:0]=ind, flags[7:4]=XRF idx; target=csr_id;
            imm32=value (post-indirection). addr_lo/hi unused.
            csr_id spaces (`rtl/seq_unit.sv:928-934`, `csr_addr`):
              0x0nn  layer_chan   -> LAYER_BASE + target[7:0]
              0x1cnn matvec chan c-> MV_BASE + MV_STRIDE*target[11:8]
                                     + target[7:0], c = target[11:8] < 4
              0x2nn  sequencer-internal, NOT an AXI write:
                       0x20      -> TCNT_SEQ
                       0x40..0x5C-> XRF[target[4:2]]
                       anything else in 0x2nn -> err 0x07 at execute
            target[15:12] > 2 -> err 0x07; matvec chan >= 4 -> err 0x05;
            ind not in {0,1,2} -> err 0x02; XRF idx set with ind==0 ->
            err 0x02; XRF idx >= 8 -> err 0x03.
            SIDE EFFECT: a CSRWR to layer 0x08/0x0C/0x10 also updates the
            sequencer's ARG0/ARG1/ARG2 shadow (`rtl/seq_unit.sv:1067-1071`) —
            that shadow is what makes the XRF-writer sniff of B5 work.

0x02 CMD    flags must be 0 (err 0x04); target[15:12] must be 0 (err
            0x07); writes imm32 to LAYER_BASE + target[7:0], then waits
            for the layer cmd_cnt shadow to advance and checks err_op.
            Layer err_op -> err 0x10; watchdog -> err 0x11.

0x03 MOVX   flags[3:0] must be 0 (indirection FORBIDDEN, err 0x02);
            flags[7:4]=chan, >=4 -> err 0x05.
            addr_lo[13:0] = scratch source word; len_or_addr_hi[23:0] =
            int8 ELEMENT count. XWIN words pushed = ceil(len/4)
            (`rtl/seq_movers.sv:547`); a ragged tail is zero-padded.
            target is reserved 0 by convention — see B10.

0x04 MOVY   flags[3:0]=ind, flags[4]=mode (0 = int32 {lo,hi} pairs,
            1 = int16), flags[7:5]=XRF idx (A1);
            target[3:0]=chan (>=4 -> err 0x05), target[15:4] must be 0
            (err 0x06); imm32 = dequant shift, POST-indirection, signed;
            addr_lo[13:0] = scratch dst word; len_or_addr_hi[23:0] = RES
            rows. Scratch words written = len (int16) or 2*len (pairs).
            Dequant = rshr64s + round-half-away, then clip to int16 in
            int16 mode and to int32 in pairs mode (`rtl/seq_movers.sv:467-479`,
            `rtl/seq_movers.sv:495-510`) — bit-for-bit ref/w4a8_ref.rshift_round +
            seq_model.rs_s/clip16.

0x05 MVGO   flags[3:0] must be 0 (err 0x02); flags[7:4]=chan (err 0x05);
            imm32 = SHAPE (B9); addr_lo = WBASE[31:0];
            len_or_addr_hi = {beats[23:0], wbase[39:32]} (A7 — the RTL
            reads mv_wbase={hi[7:0],lo}, mv_beats=hi[31:8],
            `rtl/seq_unit.sv:1093-1101`). target[0] = NO-WAIT (v1.4);
            target[15:1] reserved 0 by convention — see B10.

0x06 EMB    flags must be 0 (err 0x04).
            DDR byte address = {target[15:0], imm32[31:0]} truncated to
            ADDR_W(34) + (XRF[3] << EMBLOG2) — the row size is the RUNTIME
            CSR at SEQ 0x60, reset 13 (8192 B, G3.4); SEE B13, which supersedes
            the fixed *2048 this line carried through v1.6.
            i.e. the embedding table base is carried in
            target:imm32, NOT in addr_lo.
            addr_lo[13:0] = scratch DST word; len_or_addr_hi[23:0] =
            16-bit WORD COUNT (0 = retire immediately, no burst).
            Odd byte address -> err 0x0B.

0x07 AMAXL  every field must be 0 (err 0x06). Reads layer AMAXI (0x28)
            -> XRF[3], pushes the same 18-bit value into the OUT FIFO
            (B3), and writes through to layer_chan's XRF[3] when
            XRF_WRITE_THROUGH (default on).

0x08 JMP    flags 0 or 1 only (err 0x04). imm32 = absolute record index,
            and imm32 >= SEQ_LEN -> err 0x08 (v1.4 bound, enforced at
            decode). flags 0x1: TCNT_SEQ is decremented and the jump is
            taken iff the PRE-decrement TCNT_SEQ != 1 (`rtl/seq_unit.sv:1148-1160`).
            HAZARD: TCNT_SEQ == 0 at a flags=1 JMP wraps to
            2^32-1 and the stream runs ~forever — every compiled image
            must set TCNT_SEQ explicitly.

0x09 FENCE  every field must be 0 (err 0x06). Drains movers + the burst
            write engine; this is what retires a NO-WAIT MVGO.

0x0A HALT   every field must be 0 (err 0x06). busy -> 0, halted -> 1.

0x0B LDC    flags[3:0]=ind, flags[7:4]=XRF idx (v1.4; only the 3 LSBs
            are significant, idx >= 8 -> err 0x03).
            DDR byte address = signed{len_or_addr_hi, addr_lo} +/- XRF[i]
            per the indirection code (`rtl/seq_unit.sv:946-949`);
            imm32[23:0] = 16-bit WORD COUNT (0 = retire immediately);
            target[13:0] = scratch DST word. Odd address -> err 0x0B.
            NOTE the asymmetry with EMB: LDC's count is in imm32, EMB's
            is in len_or_addr_hi.

0x0C XOP    flags must be 0 (err 0x04); target < 8 (err 0x03);
            XRF[target[2:0]] = s1*XRF[imm32[2:0]] + s2*XRF[imm32[6:4]]
            + simm18(imm32[31:14]); s1=imm32[9:8], s2=imm32[11:10],
            codes 00=0, 01=+1, 10=-1, 11 -> err 0x0A (D-1).

Anything else -> err 0x01 (unknown opcode).

---------------------------------------------------------------------
## B5. Indirection, XRF and XOP — as-built
---------------------------------------------------------------------

  * Indirection codes as built: 0x0 none, 0x1 imm32 + XRF[i], 0x2
    imm32 - XRF[i] (IND_SUB, ratified v1.4). Any other code -> err 0x02.
  * Which flag bits carry the XRF index: flags[7:5] for MOVY, flags[7:4]
    for everything else (`rtl/seq_unit.sv:725-728`). The index actually used is
    the low 3 bits.
  * XRF[3] READS AS UNSIGNED, every other entry as signed 18-bit
    (`rtl/seq_unit.sv:404-408`, xrf_rd) — A11, as built on both sides
    (`rtl/layer_chan.sv:85-88` says the same about its XRFD window).
  * XOP overflow: the 32-bit result is written truncated to 18 bits and
    sets the STICKY xrf_ovf flag if it leaves [-131072, +262143]
    (`rtl/seq_unit.sv:1162-1164`). The asymmetric bound is deliberate: the
    positive side allows a full UNSIGNED 18-bit token id (XRF[3]).
    xrf_ovf is readable as PERF_FST bit 0.
  * WRITE-THROUGH. Every XRF write a RECORD makes (CSRWR into the 0x2nn
    XRF space, XOP, AMAXL) is also written into layer_chan's XRFI/XRFD
    window when XRF_WRITE_THROUGH=1 (the default), so the two copies
    cannot disagree — vecnorm EPS-NORM reads k from layer_chan's copy.
    A HOST AXI write to SEQ 0x40+4i does NOT write through
    (`rtl/seq_unit.sv:1348-1349`): host XRF seeding must go in-stream.
  * REFRESH (the other direction). The sequencer re-reads the XRF after
    exactly the commands that write it, recognised from the ARG shadow it
    issued itself: ALU sub-op 0 (DYNQ8) -> read layer EOUT 0x1C -> XRF[0];
    ALU sub-op 12 (DYNQ16) -> read layer XRFD -> XRF[1] or XRF[2] per
    arg2[0]; ALU sub-op 8 with arg2[6] (the op-8 k_a probe) -> XRF[2]
    (`rtl/seq_unit.sv:120-124`, `:922-925`).

---------------------------------------------------------------------
## B6. err_code (STATUS[31:24]) — as-built, complete
---------------------------------------------------------------------

  0x00 no error                     0x01 unknown opcode
  0x02 bad indirection code         0x03 XRF index out of range
  0x04 illegal flags for the opcode 0x05 engine channel >= 4
  0x06 reserved field non-zero      0x07 unknown CSR space
  0x08 JMP target outside stream    0x09 pc outside the stream
  0x0A illegal XOP sign code        0x0B unaligned LDC/EMB address
  0x0C host ABORT
  0x10 layer_chan err_op            0x11 layer CMD watchdog
  0x12 AXI-Lite SLVERR/DECERR, or an m_axib RRESP/BRESP != OKAY
  0x20 matvec err_rresp             0x21 matvec done watchdog
  0x22 XWIN fifo overflow           0x23 mover stream watchdog

0x01..0x12 are raised in rtl/seq_unit.sv:287-292 (G3.4 fix round 1 added
0x0D, the S9 MVGO SHAPE envelope, and moved the block's end line; the
numbers here are the pre-fix ones and the post-fix declarations are
rtl/seq_unit.sv:286-292); 0x12 and 0x20..0x23
also in rtl/seq_movers.sv:202-206. sw/hwmap.py:298-319 (SEQ_ERR) carries
the same table with the same text.

---------------------------------------------------------------------
## B7. layer_chan CSR map — as-built (rtl/layer_chan.sv:12-33)

> ### PRE-G3.3 ROWS, KEPT AS THE RECORD — dated note 2026-09-02 (Task 9)
>
> Rows here marked `<!--cites:noquote-->` quote **source that G3.3 DELETED**,
> not source that merely moved: the `cfg_w8` / `cfg_g64` ports and everything that selected on them, SHAPE bits 28 and 29, and the W8-envelope adder tree.  They are kept verbatim, because they
> are the record of what the pre-G3.3 tree said and the argument they support
> rests on them (§0: nothing is deleted or struck).  The exemption marker is
> used for exactly the reason §7.6 gives — *"an exemption is for source that
> no longer exists, not for a citation that has merely moved"* — and every
> citation that had merely MOVED was RENUMBERED instead, mechanically, by
> `evidence/qwen9b/o3/o3_cite_drift.py --base a08a90b`.
> **The post-G3.3 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_3_MATVEC.md` §11.1.**
---------------------------------------------------------------------

The CSRWR 0x0nn space. Base 0x5000 in the BAR (hwmap.LB).

  0x00 CMD    W  {opcode[3:0]} dispatch (idle only)
  0x04 STATUS R  {cmd_cnt[15:0], 14'b0, err_op, busy}
  0x08 ARG0   RW    0x0C ARG1 RW    0x10 ARG2 RW
  0x14 SPTR   RW scratch word pointer [13:0]
  0x18 SWIN   W  scratch[SPTR]=d[15:0], SPTR++;  R same, idle only
  0x1C EOUT   R  last ALU DYNQ8 exponent [3:0]
  0x20 TCNT   RW {6'b0, T1[9:0], 6'b0, T0[9:0]} KV append counters
  0x24 IDENT  R  0xFAB1E5A0
  0x28 AMAXI  R  ALU AMAX32 running argmax index [17:0]
  0x2C AMAXV  R  ALU AMAX32 running max value (int32)
  0x30 LAYER  RW {21'b0, kv_slot[10:8], 3'b0, dn_slot[4:0]}
  0x34 LCYC   R  busy-cycle accumulator @ ACLK; ANY WRITE CLEARS IT
  0x38 XRFI   RW {29'b0, idx[2:0]}
  0x3C XRFD   RW XRF[XRFI]: read {14'b0, raw18}, write raw18 = d[17:0]
  0x40 MAXPL  R  vec_alu op-8 probe max|prod| [31:0]
  0x44 MAXPH  R  {16'b0, max|prod|[47:32]}
  0x48..0x58  the TOPK-32 block — see B8

ALL SIX of the "post-v1.5" L_* registers (LAYER, LCYC, XRFI, XRFD, MAXPL,
MAXPH) are present in the RTL and in sw/hwmap.py:65-73. The TOPK block is  <!--cites:noquote-->
the only layer CSR group hwmap does NOT carry (B11).

Layer COMMAND opcodes (the CMD record's payload, `rtl/layer_chan.sv:140-185`):
1 VN, 2 VNW, 3 ROPET, 4 ROPE, 5 CONVW, 6 CONV, 7 GATE, 8 DNST, 9 KVAP,
10 ATTN, 11 ALU, 12 DNZ.

VNW (command 2, vecnorm weight preload) element COUNT = ARG0[10:0], and
**0 ENCODES 2048** — the full 2048-entry wbuf of a Qwen3.5-2B rmsnorm
(n_log2 = 11).  `ld_n`/`ld_i` in layer_chan.sv are both 11 bits, so
`ld_i + 1 == ld_n` wraps and fires at ld_i = 2047, i.e. after all 2048
entries have been written (layer_chan.sv, OP_VNW dispatch + L_P/LT_VNW).
Counts 1..2047 are literal.  A count of 0 meaning "none" was never
expressible and is not used.  (R-b, 2026-08-13.)  **SUPERSEDED — READ B14.5: G3.1 made the field ARG0[12:0] with NO escape (`0` means 0 and is refused), and G3.2 made the wbuf 4096 deep, so neither the 11-bit field nor the 2048-entry ceiling in this paragraph is current. (2026-09-02.)**

ALU (command 11) element COUNT = **ARG0[16:4], 13 bits, max 8191**
(rtl/vec_alu.sv `cfg_len`; layer_chan.sv wires `.cfg_len(arg0[16:4])`).
Unlike VNW's count there is NO 0-encodes-8192 escape: vec_alu compares
`cfg_len == 13'd1` and loads `len_q <= cfg_len`, so 0 runs zero elements.

The count was **12 bits (ARG0[15:4], max 4095) before R-c**, and every
0.8B stream stays inside that: the longest ALU command any of them issues
is 3584 elements (the FFN of Qwen3.5-0.8B) and `arg0[16]` is 0 in all
248,218 ALU records of the frozen set — `ref/scripts/scan_spare_bits.py`
carries that home in its table and re-proves it on every run, exactly as
it does for R-b's bit-14 scratch addresses.  So the widening is invisible
to every artifact built before it, and `tb/tb_vecalu_diff.sv` demonstrates
it directly by driving the widened unit and the FROZEN 12-bit legacy copy
from one stimulus and requiring them to agree.

WHY IT HAD TO GROW: Qwen3.5-2B's MLP quantizes its whole `FFN = 6144`
intermediate in ONE DYNQ8, and a DYNQ8 cannot be split — it picks a single
shared exponent from `max|x|` over the vector and reports it on EOUT, so
two half-length commands are a different function.  At 12 bits the
sequencer asked for 6144 and the engine ran `6144 & 0xFFF` = 2048.
Both emitters (`gen_layer_script.Mach.alu` and `seq_format.SeqEmitter._cmd`,
which synthesizes ALU commands of its own) now REFUSE an unencodable
count, and `ref/seq_model.py:_alu` refuses to replay a stream carrying one
— the model's bound mirrors the hardware field exactly rather than being
wider than it, which is what let the truncation hide.  (R-c, 2026-08-22.)

vec_alu SUB-ops (command 11 ALU, sub-op = ARG0[3:0], rtl/vec_alu.sv:13-47)
— do not confuse these two numberings:
sub-op 0 DYNQ8, 1 SHIFT32, 2 SCALE, 3 EMUL, 4 ADD, 5 SILU16, 6 SILU32,
7 SIGM16, 8 EMUL32 (+ probe), 9 SHIFT32W, 10 AMAX32, 12 DYNQ16.
There is no vec_alu sub-op 11. The two ISA-introduced ops are unchanged
from v1.1:
DYNQ16 latches k into XRF[cfg_p0[0] ? 2 : 1] with cfg_p0[1] = clamp-at-0,
and the op-8 PROBE is selected by cfg_p0[6] (v1.3, NOT p0[2] — vec_alu.sv
:55-63 records why p0[2] was impossible) and always targets XRF[2].

---------------------------------------------------------------------
## B8. TOPK-32 block — NEW CSR contract (rung 4 S5, 2026-08-11)
---------------------------------------------------------------------

A sibling block inside layer_chan (module `layer_topk32`,
rtl/layer_chan.sv:2170-2301), addressed in the layer 0x0nn CSRWR space at
0x48..0x58 — decode space that was free, so no BD / create_project edit
was needed. Live on silicon since build_033. Previously documented only
in docs/RUNG4_SPEC.md S5; this is now its ISA home.

  0x48 TK_IDENT  R  0xFAB1704B
  0x4C TK_STATUS R  {24'b0, overflow[7], complete[6], count[5:0]}
  0x50 TK_PTR    RW {27'b0, ptr[4:0]}  entry cursor
  0x54 TK_VAL    R  int32 value of entry[ptr]  — NO side effect
  0x58 TK_IDX    R  {14'b0, idx[17:0]} of entry[ptr] — PTR++ ON READ

Semantics, all verified against `rtl/layer_chan.sv:953-977`, `:1179-1187`, `:1198-1199`
and the module body:

  * FEED. One registered 51-bit bundle exported from vec_alu at the
    AMAX32 compare site: {we = t_cp[0] && op_q==10, val = cp_v32,
    idx = am_g} (`rtl/vec_alu.sv:433-434`). II=1, no backpressure, and the
    export is inert for every other op.
  * ORDER. 32 entries kept sorted value-DESCENDING; the arrival must be
    STRICTLY greater to displace an incumbent, so ties keep the lower
    index — the same first-wins rule as np.argmax and as AMAX32 itself.
  * COUNT. Valid entries, saturating at 32.
  * COMPLETE (bit 6) = registered (!amax_busy && !we): no AMAX32 command
    in flight in the engine AND no sample being presented. It can only
    rise after the final insert has been clocked in.
  * OVERFLOW (bit 7) = STICKY, and its meaning is LITERAL: it is set when
    an arrival was REJECTED (not greater than entry[31]) while being
    EXACTLY EQUAL to entry[31]. It means "the top-32 SET is not unique by
    value alone, so a host cross-check that breaks ties differently may
    legitimately differ". It is NOT an error and NOT a count of dropped
    candidates. (evidence/rung4/RUNG4_GATE.md logs this literal reading
    as a standing follow-on; the host cross-check assumes it.)
  * RESET IS FRESH-ONLY. List, count, overflow and ptr are cleared by the
    AMAX32 "fresh" flag alone — an ALU command with aop 10 and
    cfg_p0[0]=1 — and by NOTHING else: not by START, not by a launch,
    not by a command boundary. A vocabulary scanned as N chained AMAX32
    chunks therefore accumulates into ONE top-32. fresh leads the first
    sample of its own scan by 4 cycles, so the clear cannot race it.
  * READBACK PROTOCOL. Write TK_PTR once (or not at all — it resets to 0),
    then per entry read TK_VAL then TK_IDX; the TK_IDX read advances the
    cursor. sel is a registered mux updated from the NEXT ptr, and the
    slave is single-outstanding, so val/idx are always in step with ptr.
    TK_PTR WRAPS AT 32 (5 bits) — the host loops i < count.
  * The idx field is the GLOBAL element index am_g, 18 bits: it wraps at
    262,144, i.e. only 5.6% of headroom above the 248,320-row vocabulary
    (logged follow-on, policy undecided).

---------------------------------------------------------------------
## B9. MVGO SHAPE word — as-built (rtl/matvec_chan.sv:18-45, 322-327)  <!--cites:noquote-->
---------------------------------------------------------------------

> ### THIS SECTION DESCRIBES `build_034` / `build_035` — dated note 2026-09-02 (G3.3, Task 9)
>
> Everything in B9 below is the SHAPE word of the **resident** bitstream and
> is kept verbatim, because that bitstream is still on the board and
> `sw/hwmap.shape_word(..., isa=1)` still packs exactly this layout for it.
> **It is NOT the word this tree's RTL decodes.**  G3.3 stripped the W8
> (bit 29) and g64 (bit 28) ENGINE modes (spec §5.1 S5, §5.2 S6) and `ng`
> took bit 28 as its seventh, because the 9B `down_proj` row is K = 12288
> → ng = 96, which does not fit six bits.  The post-G3.3 word is
> **`{spare[31:29], ng[28:22], nrows[21:6], sh[5:0]}`** — contiguous, three
> spare bits — and it is `shape_word(..., isa=2)`, the default.  The two
> layouts, and which host tools remain valid against which bitstream, are
> tabulated in `evidence/qwen9b/g3/G3_3_MATVEC.md` §5 and §7.

The MVGO record's imm32 is written verbatim to the channel's SHAPE CSR:

  bit 29    w8    0 = INT4 nibble weights (legacy), 1 = INT8 byte weights
                  (V5 — a 64 B weight beat holds 64 weights instead of 128,
                  so a row streams 2*ng weight beats; the scale beats are
                  bit-for-bit a W4 g128 row's — ref/w4a8_ref.py row_beats8)
  bit 28    g64   0 = legacy G=128 rows (bit-identical to pre-v2),
                  1 = G=64 v2 row format (each 64 B weight beat carries
                  TWO groups of 64; ceil((K/64)/32) scale beats follow
                  the weight beats — see ref/w4a8_ref.py)
  [27:12]   nrows (16 bits as built)
  [11:6]    sh
  [5:0]     ng    = ng-UNIT count of one row = K//128, in EVERY mode

Bits [31:30] are read back as 0 (they were [31:29] before V5 took bit 29).

`ng` is the WEIGHT-beat count only in W4. It was deliberately NOT redefined
for W8: at K = 6144 the W8 weight-beat count is 96, which does not fit the
6-bit field, and nrows has no room to give. Keeping ng = K//128 also keeps
the scale-beat count (ceil(ng/32) at g128) unchanged, so the whole scale
path is mode-independent. Row beats per mode:

  W4 g128:  ng + ceil(ng/32)
  W4 g64 :  ng + ceil(2*ng/32)
  W8     : 2*ng + ceil(ng/32)

w8 + g64 is ILLEGAL: the wire law defines no such image, sw/hwmap.shape_word
asserts against it, and rtl/matvec_engine.sv raises $error (sim-only — SHAPE
is host/sequencer-written, so this is misuse of a frozen field, not a
hardware fault; the datapath does not fault, it would produce silently wrong
y32).

The per-image group size travels in the manifest as "g" (ABSENT means 128)
and the weight width the same way (ABSENT means W4); hosts pack the word
with sw/hwmap.shape_word(nrows, sh, ng, g, w8).

---------------------------------------------------------------------
## B10. What the RTL enforces vs what only the emitter enforces
---------------------------------------------------------------------

Two v1.5 reserved-field rulings are EMITTER-SIDE ONLY. They are real
contract, but a hand-built stream that violates them will run, not fault:

  * "MOVX target reserved 0" — ref/seq_format.py:592-593 rejects it;
    rtl/seq_unit.sv:787-795 does not look at MOVX target at all.
  * "MVGO target[15:1] reserved 0" — ref/seq_format.py:590-591 rejects it;
    the RTL uses only target[0] (NO-WAIT) and ignores the rest.

Enforced by BOTH sides: MOVY target[15:4]==0, AMAXL/FENCE/HALT all-zero
operands, XOP flags==0 and target<8, XOP sign code 11, JMP flags in
{0,1}, MOVX/MVGO no-indirection, channel < 4, XRF index < 8.

Enforced by the RTL ONLY (the emitter validator does not check it):
CSRWR csr_id space (target[15:12] <= 2) and the matvec channel field.

---------------------------------------------------------------------
## B11. Disagreements found while consolidating (2026-08-12)
---------------------------------------------------------------------

Recorded; where a fix later landed, the item says so (1 and 2 below).
The RTL is the truth in each case.

1. JMP BOUND, off by one — ALREADY FIXED. rtl/seq_unit.sv:817 faults when
   `r_imm >= seq_len`, while the emitter validator used to fault only on
   `r.imm32 > nrec`, so a JMP to exactly `nrec` passed the validator and
   then died on chip with err 0x08. The v1.4 ruling ("target must be <
   nrec") agrees with the RTL, and ref/seq_format.py:686 now reads
   `r.imm32 >= nrec` with a comment pointing back at this item. (The fix
   landed in the SAME commit that first wrote this entry, 6472f92, so the
   "not changed here" this paragraph used to carry was never true; the
   record is kept because the ISA-side ruling is what matters.)
2. SHAPE nrows WIDTH. hwmap's comment used to document `nrows[24:12]`
   (13 bits) while rtl/matvec_chan.sv:318 latches `wdata_q[27:12]` into a
   16-bit register. shape_word() does not mask, so packing was correct for
   any nrows the RTL accepts — only the comment understated the field, and
   sw/hwmap.py:36-38 now carries the as-built `nrows[27:12]` with a pointer
   back to this item. B9 above carries the as-built width.
3. TOPK-32 IS ABSENT FROM sw/hwmap.py. The block's five CSRs are
   declared locally in sw/chat_seq.py:220 (TOPK_BASE = HW.LB + 0x48)
   instead of in the device map that "every host tool imports". B8 is
   the ISA-side record; folding the constants into hwmap.py is a
   one-line follow-on for its owner.
4. THE v1.1 OUT-FIFO SENTENCE IS STALE in the frozen text ("depth 16;
   overflow drops silently"). As built: depth 64, and the drop is no
   longer silent — it sets sticky of_ovf in STATUS[23]. B3 wins.
5. THE v1.1 "only IND_ADD exists" LINE was already superseded by v1.4
   (IND_SUB 0x2). Restated here because it is the single most-quoted
   stale line in the frozen text.
6. docs/CHAT_SEQ_SPEC.md:69-73 still lists the of_cnt push/pop race as a
   "KNOWN RTL BUG ... fix candidate for the next RTL rung". That rung
   happened: rung 4 S6 fixed it (B3). The spec is a frozen historical
   record and is left as-is; this file is the current truth.

---------------------------------------------------------------------
## B12. 15-bit scratch addressing — the R-b widening (v1.7, 2026-08-13)
---------------------------------------------------------------------

> **SUPERSEDED 2026-09-01 by B14 (SEQ_ISA v2.0 / G3.1).  RETAINED VERBATIM
> as `build_034` and `build_035`'s ISA, because those bitstreams still run
> and are served from a pre-G3 checkout.**  Everything in B12 describes an
> encoding THIS TREE NO LONGER EMITS OR DECODES: the bit-14 scatter is
> deleted, not extended.  Read B12 for what the shipped 0.8B/2B artifacts
> contain; read B14 for what the RTL in this repository decodes today.

Qwen3.5-2B needs 25600 scratch words (docs/QWEN2B_SCRATCH_MAP.md), so the
layer_chan scratchpad went 16384 -> 32768 words and every field that names
a scratch word went 14 -> 15 bits. THIS SECTION WINS over any address
width stated earlier in this file.

WHY IT IS BACK-COMPATIBLE. No field had room to grow in place, so bit 14
of each rides in a bit of the SAME record/arg word that was proven spare
FIRST, before any decode changed: `ref/scripts/scan_spare_bits.py`
OR-accumulates every arg/field of every layer command and every SEQ record
across the FROZEN PRE-R-b STREAM SET — 32 .txt scripts and 6 binary .seq
streams, 365 605 `C` records + 222 817 SEQ records = 588 422 records,
giving 415 314 layer commands once the SEQ streams' own CMDs are counted —
and prints, per opcode, exactly which bits are EVER set. The report is
`evidence/qwen2b/rb/spare_bits_report.txt`; every home below is 0 in it.

  THE SCANNER IS SCOPED, ON PURPOSE. Its default root list
  (`LEGACY_STREAMS`) is the pre-R-b set and nothing else. Post-R-b streams
  — `tb/scripts/seqlayer_s*.txt`, the R-b directed >16K case — SET these
  bits by construction, so scanning them reports the new usage as a
  conflict; `--all` does exactly that and is for inspection only. Run with
  no arguments it exits 0 on a healthy tree and non-zero if a bit-14 home
  stops being spare IN THE LEGACY SET, which is the only set the
  back-compatibility claim is about.

  A ROW CAN PASS VACUOUSLY. "never set" is evidence only where the field is
  exercised; check the record count beside each opcode. One row in the
  table below is vacuous today: the layer SPTR CSR (0x14) has no in-stream
  writer at all (the movers program SPTR over AXI-Lite, not via a CSRWR
  record), so its width change rests on SPTR being a HOST-written CSR whose
  bit 14 the old RTL simply ignored — not on the scan.

Every 0.8B address is < 16384, so every one of these bits emits 0 and every
frozen stream replays bit-identically.

### B12.1 Layer command ARG fields (`d2d774b:rtl/layer_chan.sv:69-116`)

> **PINNED, dated note 2026-09-10 (pre-ship documentation chore).** This
> section describes the **15-bit** v1.7 ARG layout — bit 14 of each address
> riding in a spare bit of the same arg word — and G3.1 replaced that with
> 16-bit fields and no scattered bits at all. An earlier repair round
> re-anchored this heading onto HEAD's `rtl/layer_chan.sv`, which points a
> pre-G3.1 section at RTL that **contradicts** it. The citation is therefore
> pinned to `d2d774b`, the tree G3.1 took as its base and the last one where
> what this section says was true of the RTL. **For the CURRENT layout read
> B14 and the v2.0 block at `rtl/layer_chan.sv:120-157`**; this section is
> kept because the frozen 0.8B/2B streams and `build_034`/`build_035` still
> run it.

  ARG1, on EVERY command, carries an address PAIR:

      bit 29 = hi[14]   bit 28 = lo[14]   [27:14] = hi[13:0]   [13:0] = lo[13:0]

  ARG2 uses that SAME pair layout on GATE and DNST. The exceptions:

  | command | field            | bit-14 home    | note                        |
  |---------|------------------|----------------|-----------------------------|
  | VN      | src / dst        | ARG1[28]/[29]  | pair layout                 |
  | VNW     | src              | ARG1[28]       |                             |
  | ROPET   | src              | ARG1[28]       |                             |
  | ROPE    | src / dst        | ARG1[28]/[29]  |                             |
  | CONVW   | src              | ARG1[28]       | first/nch are channel idxs  |
  | CONV    | src / dst        | ARG1[28]/[29]  |                             |
  | GATE    | dst              | ARG0[14]       | ARG0 is just dst -> [14:0]  |
  | GATE    | src_b / src_a    | ARG1[28]/[29]  |                             |
  | GATE    | src_A / src_dt   | ARG2[28]/[29]  |                             |
  | DNST    | src_q / src_k    | ARG1[28]/[29]  |                             |
  | DNST    | src_v / dst      | ARG2[28]/[29]  |                             |
  | DNST    | a_dec            | ARG1[30]       | ARG0 is FULL — see below    |
  | DNST    | a_beta           | ARG1[31]       | ARG0 is FULL — see below    |
  | KVAP    | src_k / src_v    | ARG1[28]/[29]  |                             |
  | ATTN    | src_q / dst      | ARG1[28]/[29]  |                             |
  | ALU     | srca / srcb      | ARG1[28]/[29]  |                             |
  | ALU     | dst              | ARG2[31]       | ARG2 = {dst[30:17],p0[16:0]}|

  DNST's ARG0 is `{a_beta[13:0]@31:18, a_dec[13:0]@17:4, head[3:0]}` — 32
  bits EXACTLY full, with no spare anywhere in it. That is why its two
  scalar pointers borrow ARG1's last two spare bits rather than growing in
  place. (This also retires the R1 finding that a naive widening of the
  emitter's `head | a_dec<<4 | a_beta<<18` pack would overflow ARG0: the
  emitter now packs the low 14 bits there and the 15th in ARG1, and
  `ref/gen_layer_script.enc_saddr` asserts every address is < 32768.)

  ALU's ARG2 has exactly ONE spare bit, 31, and that is where its dst[14]
  went. Its [30:17] dst field and [16:0] p0 field are unchanged.

  The RTL reads these through four wires — `a1_src`, `a1_dst`, `a2_src`,
  `a2_dst` (rtl/layer_chan.sv) — so no command decodes the layout by hand.

### B12.2 SEQ record fields

  | opcode | field                | bit-14 home  | note                     |
  |--------|----------------------|--------------|--------------------------|
  | MOVX   | scratch src          | addr_lo[14]  | addr_lo is a full u32    |
  | MOVY   | scratch dst          | addr_lo[14]  |                          |
  | EMB    | scratch dst          | addr_lo[14]  |                          |
  | LDC    | scratch dst          | target[14]   | target is u16, 2 spare   |

  Nothing about the record layout, the flags, or the length fields changes:
  each of these fields simply reads one bit wider (`r_lo[14:0]` /
  `r_tgt[14:0]`, rtl/seq_unit.sv). The emitter needed NO change here — it
  already writes the full value into a wider field.

### B12.3 Widths and windows that follow

  * layer_chan SPTR (0x14) is `wdata[14:0]`, read back as `{17'b0, sptr}`.
  * layer_chan scratch memories are `[32768]`; every internal address
    signal (sptr, hw_addr, sa/sb/sw_addr, eng_sa/eng_swa, ld_src, dst_r,
    src2_r, alu_aa/ba/wa, bw_addr/br_addr, wa_ptr) is [14:0].
  * vec_alu `cfg_srca/cfg_srcb/cfg_dst` and `a_addr/b_addr/w_addr` are
    [14:0]; its drain-time parking address `cfg_dst + len` no longer wraps
    at 16K.
  * seq_movers `SCR_WORDS = 32768`, `cmd_saddr [14:0]`.
  * seq_unit's LDC/EMB scratch-window bound is 32768 words.
  * sw/hwmap.py `SCRATCH_WORDS = 32768`.

  S6 BURST APERTURE. layer_chan's `s_axib` address grows 16 -> 17 bits:
  the window is now 128 KiB (scratch word w at byte 4w, w = 0..32767) and
  the IPI wrapper declares `ADDR_WIDTH 17`. matvec_chan's `s_axib` is
  untouched at 16 bits / 64 KiB.

  MVB WINDOW MAP (the sequencer's private m_axib map, RUNG3 S4). An AXI
  segment must be RANGE-ALIGNED, and 0x5_0000 is not a 128 KiB-aligned
  address, so the layer window MOVED as well as grew:

      mvchan_c   (c+1) << 16   64 KiB   READ 0x0000-0x3FFF  RES row r
                                        WRITE 0x4000-0x57FF XWIN word w
      (0x5_0000)              64 KiB   DECODE HOLE (was layer_0)
      layer_0     6 << 16      128 KiB  R/W scratch word w, w < 32768

  i.e. `LAYB_BASE` 0x0005_0000 -> 0x0006_0000 in rtl/seq_unit.sv and
  rtl/seq_movers.sv, and `layer_0 0x60000` with range 128K in
  synth/scripts/create_project.tcl. The mvchan windows are unchanged.

### B12.4 Two field notes this widening pins down

  * VNW COUNT. ARG0[10:0], and 0 ENCODES 2048 (B7). The emitter writes the
    literal count UNMASKED (so 2048 goes out as 0x800 and the RTL's 11-bit
    truncation does the wrap), and `ref/gen_layer_script.Mach.vnw_` now
    asserts `1 <= n <= 2048` so the wrap is deliberate rather than lucky.
    ref/seq_model.py and sw/chat_seq.py both use the UNTRUNCATED value;
    all three agree only because 2048 wraps to exactly one full pass.
  * VECNORM nlog2 CEILING. `n_log2 = 11` (n = 2048) is the ceiling: the
    vecnorm element counter is 12 bits, and nlog2 >= 12 wraps to zero and
    deadlocks. Today that is caught by a SIMULATION-ONLY `$fatal` in
    rtl/vecnorm_unit.sv — there is NO command-decode range check, so a
    hand-built stream with nlog2 >= 12 hangs the engine on silicon.
    Promoting it to a decode error (err_op) is a logged follow-on, not
    part of R-b.

---------------------------------------------------------------------
## B13. EMBLOG2 — the EMB row size becomes runtime (v1.7, 2026-08-13)
---------------------------------------------------------------------

Before R-b, `rtl/seq_unit.sv` fetched an embedding row at

    emb_a = {target, imm32} + XRF[3] * 2048        (localparam, 2048 B)

which hard-codes H = 1024. Qwen3.5-2B has H = 2048 (4096 B rows), so that
constant alone would have forced a SECOND bitstream. It is now a register:

    emb_a = {target, imm32} + (XRF[3] << EMBLOG2)

  off   name      acc  contents
  0x60  EMBLOG2   RW   {27'b0, log2(emb row bytes)[4:0]}, reset 13 (G3.4)

  * RESET = **13 (8192 B)** since G3.4 (spec §5.3 S8); it was 11 (2048 B)
    through R-d, and `sw/hwmap.SEQ_EMBLOG2_RST` /
    `EMB_ROW_BYTES_DEFAULT` mirror whichever value the RTL holds.  Moving
    the reset converts "a site that never learned to program EMBLOG2 from
    the artifact silently addresses the wrong row" into "right by default"
    at the only geometry this bitstream serves.  A host that never writes it — every pre-R-b tool,
    every frozen 0.8B flow — gets the OLD address math bit for bit. That
    is the whole back-compatibility argument: nothing in the stream, the
    record encoding or the frozen artifacts changed.
  * LEGAL RANGE 8..13 (256 B .. 8 KiB). A write outside it is REJECTED —
    the register KEEPS ITS OLD VALUE — and raises a simulation `$error`.
    This is the host-misuse class, NOT a stream error: no err_code is
    defined for a host CSR write, and inventing one would change the
    frozen err map (B6). A bad row size is a host bug, catchable in sim
    and in the host's own readback, never a sequencer halt.
  * HOST-ONLY. Not reachable from the 0x2nn CSRWR space (B4): only
    TCNT_SEQ (0x20) and XRF (0x40..0x5C) are in-stream writable. A record
    targeting 0x260 halts with err 0x07.
  * NOT CLEARED BY START (the B1 rule): only a hard reset restores 11.
    A host that switches models on a resident bitstream MUST rewrite it,
    which is why sw writes it at every bring-up rather than once.
  * POWER OF TWO ONLY, by construction: the row size is 2*H and both
    supported H are powers of two, so a shift replaces the old multiply.

WHERE THE VALUE COMES FROM. `ref/gen_layer_script.dump_weights()` writes
`"emb_row_bytes": 2*H` into `<prefix>.weights.json` when the caller passes
it, which is EVERY generator that also emits an `.emb.bin` — today
`ref/gen_model_script.py` and `ref/gen_token_script.py`, both of which pass
`2 * LR.H`. Any future generator that writes an embedding table MUST do the
same, or its artifacts ship a row size the host cannot see. That is the ONLY
non-wid key the manifest may carry; readers must go through
`sw/hwmap.split_manifest()` / `load_weights_manifest()`, which separates it
from the wid entries and DEFAULTS IT TO 2048 when absent, so pre-R-b
artifacts keep working untouched. `sw/seq_run.seq_set_emb_row_bytes()`
programs the CSR and verifies the readback; on a pre-R-b bitstream the
offset reads 0xDEADC0DE, which the host treats as "the CSR's fixed reset
row" — tolerated for an artifact of exactly that row size, a hard error for
anything else.

---------------------------------------------------------------------
## B14. The weight DDR pack — nch-independent vs PER-CHANNEL (R-c, v1.7)
---------------------------------------------------------------------

MVGO's WBASE is a CHANNEL-LOCAL byte address: `mvchan_c/m_axi` sees its own
DDR channel at 0, so the host adds `c * CH_STRIDE` for its DMA fds and the
record does not. Where inside that channel an image lives is `sw/hwmap.py:
plan_weights()` — THE authority, which `ref/seq_format.plan_weights_from_
wids` (emitter), `sw/seq_run.plan_weights_for` (host) and
`ref/seq_model.DDRWeights` (golden) all resolve to. Two packs exist:

  * NCH-INDEPENDENT (the default, `rows_of=None`). Images go back to back
    from `W_BASE` in wid order, each start aligned up to `WID_ALIGN` (4096),
    and EVERY channel reserves the whole image. A piece is addressed by its
    GLOBAL row: `WBASE = base + r0 * stride`. `weights[wid]["base"]` in the
    .seq.json is an INT. This is what every artifact frozen before R-c
    encodes, at nch=1 and at nch=4 alike, and the 4-chan stream's byte-
    identical regeneration is the standing gate on it.

  * PER-CHANNEL REPACK (`SEQ_REPACK=1`, meta `"weight_repack": true`).
    Each channel keeps its OWN cursor and packs only the rows it owns, so
    `weights[wid]["base"]` is a LIST of nch channel-local addresses and
    `WBASE = base[c] + row_off * stride`, where `row_off` is the row index
    inside THAT channel's copy — `ref/seq_format.weight_pieces_at()` returns
    it beside the global `r0`. Under LAYOUT_CONTIG that is `r0` minus the
    channel's first row; under LAYOUT_ILV (the LM head) the channel's rows
    are strided through the image while its BYTES are contiguous from its
    base, which is why an affine rebase cannot express it and the row map
    travels as pieces, not as an offset.

    The row counts are LAYOUT-DEPENDENT (`chan_rows`): at 248,320 rows over
    4 channels the contiguous split gives 62,080 each while the 2048-row
    interleave gives 63,488 / 61,952 / 61,440 / 61,440. So an image cannot
    be placed before its layout is pinned — the emitter places it at its
    first MVGO (`_note_layout` then `_replan`), and the host reproduces the
    same walk from `meta["weight_layout"]["by_wid"]` in wid order.

WHY IT EXISTS. The weight window is 1,280 MiB per channel (`W_BASE` ..
`EMB_BASE`) and `plan_weights` asserts the pack ends below `EMB_BASE` — per
channel when repacked. V5 (W8 everywhere, 2B) is 1,847 MiB packed as one
span: 144% of the window, DOES NOT FIT. Repacked over 4 channels the
busiest channel is 464.8 MiB, 36.3% (`ref/scripts/bytes_per_token.py --fit
--model 2b --map all:w8g128 --nch 4`). The 970 MiB 2B embedding table stays
at `EMB_BASE` on the fetch channel and ends at 0x9CA0_0000, above every
weight top and inside the 4 GiB channel.

COMPATIBILITY. `weight_repack` ABSENT means false, exactly as `"g"` absent
means 128 and `"w8"` absent means W4. A repacked plan and a non-repack meta
(or the reverse) is REFUSED by `sw/seq_run.plan_weight_split`, and
`DDRWeights` refuses a per-channel plan without the meta that explains it —
the two shapes are never inferred from each other. `check_mvgo_targets`
resolves a repacked WBASE against the RECORD'S OWN channel, which the
nch-independent check could not do (every channel held the same span).

THE RTL IS UNCHANGED by all of this: an address is an address, and the
engine reads its own channel. The repack is entirely a host/emitter/golden
contract about which bytes are written where.

---------------------------------------------------------------------
## B14. 16-bit scratch addressing — the G3.1 re-encoding (v2.0, 2026-09-01)
---------------------------------------------------------------------

Qwen3.5-9B needs 50,208 scratch words at its worst body (spec 4.3's table:
PEAK_DN 33,824 / PEAK_ATTN 37,920 / PEAK_MLP 50,208, all three over the
32,768-word array), so the layer_chan scratchpad goes 32768 -> **65536**
words and every field that names a scratch word goes 15 -> **16** bits.
**THIS SECTION WINS over B12 and over any address width stated earlier in
this file.**

**IT IS NOT BACK-COMPATIBLE, AND THAT IS THE POINT.** R-b's bit-scatter
existed for exactly one reason: to let every frozen pre-R-b stream (all
addresses < 16384) emit zeros in the borrowed bits and replay
bit-identically. The 9B geometry has no frozen stream to preserve — G3.1 is
where the byte-lock recorded in `evidence/qwen9b/g2/FINAL_BYTELOCK.md` is
SPENT — and there was no 16th spare bit to borrow anyway: DNST used **94 of
its 96 arg bits** under v1.7. So the scatter is DELETED, not extended.

  **Consequence, stated plainly.** `build_034` and `build_035` run
  SEQ_ISA v1.7 and their artifacts (`tb/scripts/w4/model_v2_s1.e`, the
  frozen `tb/scripts/layer_s*` / `token_s*` .txt sets, the `.chip`/`.seq`
  wave-3/4 sets) encode v1.7 ARG words. **This tree cannot drive them and
  does not try**: there is no v1.7 emitter or decoder path on main. The
  0.8B and 2B geometries stay served by those bitstreams from a PRE-G3
  CHECKOUT. `ref/seq_format.SEQ_ISA_VERSION` names the generation this tree
  speaks (2); `sw/chat_seq.TEMPLATE_ISA_VERSION` names the generation of
  the frozen template it still loads for its non-ARG checks (1).

### B14.1 Layer command ARG fields (rtl/layer_chan.sv, the ISA header)

  ARG1, on EVERY command, carries an address PAIR:

      [31:16] = hi[15:0]      [15:0] = lo[15:0]

  ARG2 uses that SAME pair layout on GATE and DNST. There are no scattered
  bits anywhere. Per command, with the bit budget out of the 96 bits ARG0..2
  hold (mechanized: `evidence/qwen9b/g3/isa_bits.py` reads every width out
  of the RTL and prints the spare):

  | command | ARG0                                   | ARG1        | ARG2        | used | spare |
  |---------|----------------------------------------|-------------|-------------|-----:|------:|
  | VN      | `{outf[13:10],inf[9:6],nlog2[5:2],mode[1:0]}` | `{dst,src}` | `{xrf_k[3:1],eps[0]}` | 50 | 46 |
  | VNW     | `ld_n[12:0]`                           | `{-,src}`   | —           | 29 | 67 |
  | ROPET   | —                                      | `{-,src}`   | —           | 16 | 80 |
  | ROPE    | —                                      | `{dst,src}` | —           | 32 | 64 |
  | CONVW   | `{nch[29:16],first[15:2],sel[1:0]}`    | `{-,src}`   | —           | 46 | 50 |
  | CONV    | `{nch[27:14],first[13:0]}`             | `{dst,src}` | —           | 60 | 36 |
  | GATE    | `dst[15:0]`                            | `{src_a,src_b}` | `{src_dt,src_A}` | 80 | 16 |
  | KVAP    | `{expbias[8:4],kvhead[1:0]}`           | `{src_v,src_k}` | —       | 39 | 57 |
  | ATTN    | `kvhead[1:0]`                          | `{dst,src_q}` | —         | 34 | 62 |
  | ALU     | `{spare[31:19],p0[16]@18,len[17:4],aop[3:0]}` | `{srcb,srca}` | `{dst[31:16],p0[15:0]}` | 83 | 13 |
  | DNST    | `{spare[31:5],head[4:0]}`              | `{src_k,src_q}` | `{dst,src_v}` | 69 | 27 |
  | DNZ     | `head[4:0]`                            | —           | —           | 5 | 91 |

  **ONE RELOCATION IN THE WHOLE RE-ENCODING.** `cfg_p0` is SEVENTEEN bits
  (`rtl/vec_alu.sv`), and v2.0's ARG2 gives it only 16, so **p0[16] moves to
  ARG0[18]**, above the count — a bit feasibility 2.4 proved spare over
  293,768 ALU dispatches. `ref/gen_layer_script.enc_alu_a0` and
  `enc_alu_a2` are the two halves of that pack and must be read together;
  `dec_alu_p0(a0, a2)` is the only sanctioned way to open it.

  **DNST NO LONGER CARRIES ITS SCALAR POINTERS.** Six 16-bit pointers plus a
  5-bit head would be 101 bits of 96. The two SCALAR pointers are affine in
  the head with stride 1 from a per-body base (GATE writes beta at
  `dst + h` and decay at `dst + LNH + h`), so they move into a CSR:

      a_beta = DNSB[15:0]  + head
      a_dec  = DNSB[31:16] + head

  formed in the DNST decode as two 16-bit adds with a 5-bit addend, off the
  lane datapath. That takes DNST to 69 of 96 bits with 27 spare.

  **NAMED FALLBACK, NOT BUILT.** If the affine relation ever has to be
  broken, a FOURTH arg word `ARG3` at layer CSR `0x60` (the next word after
  DNSB), mirrored in `rtl/seq_unit.sv`'s ARG shadow, costs one extra CSRWR
  record per DNST — 768 DNST/token at 9B, about 6 KiB/token against
  3.9 GB/token of weights. Cheap, mechanical, and strictly larger a change
  than the affine map. It is recorded here so nobody has to re-derive it,
  and it is NOT built speculatively.

  The RTL reads the pairs through four wires — `a1_src`, `a1_dst`,
  `a2_src`, `a2_dst` — so no command decodes the layout by hand.

### B14.2 DNSB — the DeltaNet scalar-pointer base pair

  off   name    acc  contents
  0x5C  DNSB    RW   `{a_dec_base[31:16], a_beta_base[15:0]}`

  * `awaddr[11:2] == 10'h017`; `0x58 TK_IDX` was the last word used.
  * Written **ONCE PER LAYER BODY** by one CSRWR record, not once per
    command. `t[15:12] == 0` routes a CSRWR target of `0x005C` to
    `LAYER_BASE + t[7:0]`, which the sequencer's target validation already
    allows — no sequencer change was needed.
  * Text-script record: `B <32-bit hex>` (`ref/gen_layer_script.Mach.dnsb`,
    consumed by `ref/seq_model.py`, `tb/tb_layer_chan.sv`, `sw/layer_test.py`).
  * Host mirror: `sw/hwmap.L_DNSB`; SEQ mirror: `ref/seq_format.CSR_L_DNSB`.
  * A DNST issued before any DNSB is a HOST BUG: the emitter asserts, both
    decoders refuse, and the hardware would silently use whatever the last
    body left in the register.

  **THE COUPLING IS ASSERTED AGAINST THE WRITER, NOT AGAINST ITSELF.**
  `Mach.dnsb` compares the base pair being programmed against the dst of the
  GATE command that POPULATES beta|decay. A self-consistency assert ("the
  `a_dec` I emitted equals the `a_dec_base` I programmed") passes while both
  sides are wrong and would have sailed straight through the `GD + 16 + h`
  aliasing G2a fixed. `evidence/qwen9b/g3/isa_bits.py --dnst-map` is the
  negative control: it perturbs the SCA tile map five ways and requires the
  assert to fire on every one while staying silent on the healthy map.

### B14.3 SEQ record fields

  Unchanged in LAYOUT; the scratch fields simply read one bit wider than
  B12.2 says:

  | opcode | field       | width    | note                             |
  |--------|-------------|----------|----------------------------------|
  | MOVX   | scratch src | `r_lo[15:0]`  | addr_lo is a full u32       |
  | MOVY   | scratch dst | `r_lo[15:0]`  |                             |
  | EMB    | scratch dst | `r_lo[15:0]`  |                             |
  | LDC    | scratch dst | `r_tgt[15:0]` | target is u16, now FULL     |

  LDC's target is now fully consumed: there are no spare bits left in it.

### B14.4 Widths and windows that follow

  * layer_chan SPTR (0x14) is `wdata[15:0]`, read back as `{16'b0, sptr}`.
  * layer_chan scratch memories are `[65536]`; every internal address
    signal (sptr, hw_addr, sa/sb/sw_addr, eng_sa/eng_swa, ld_src, dst_r,
    src2_r, alu_aa/ba/wa, bw_addr/br_addr, wa_ptr) is [15:0].
  * vec_alu `cfg_srca/cfg_srcb/cfg_dst` and `a_addr/b_addr/w_addr` are
    [15:0]; `cfg_len` is [13:0] (14 bits, max 16383 — the 9B FFN of 12288
    fits ONE command).
  * layer_chan `ld_n`/`ld_i` are [12:0] so VNW's count field can be read
    directly.
  * seq_movers `SCR_WORDS = 65536`, `cmd_saddr [15:0]`.
  * seq_unit's LDC/EMB scratch-window bound is 65536 words.
  * sw/hwmap.py `SCRATCH_WORDS = 65536` (already, since G2a).

  S6 BURST APERTURE. layer_chan's `s_axib` address grows 17 -> **18** bits:
  the window is now 256 KiB (scratch word w at byte 4w, w = 0..65535) and
  the IPI wrapper (`rtl/layer_chan_ipi.v`) declares `ADDR_WIDTH 18`.
  matvec_chan's `s_axib` is untouched at 16 bits / 64 KiB.

  MVB WINDOW MAP (the sequencer's private m_axib map, RUNG3 S4). An AXI
  segment must be RANGE-ALIGNED, and 0x6_0000 is not a 256 KiB-aligned
  address, so the layer window MOVED as well as grew — the same reason R-b
  moved it from 5<<16 to 6<<16:

      mvchan_c   (c+1) << 16   64 KiB   READ 0x0000-0x3FFF  RES row r
                                        WRITE 0x4000-0x57FF XWIN word w
      (0x5_0000-0x7_FFFF)     192 KiB   DECODE HOLE (0x6_0000 was layer_0)
      layer_0     8 << 16      256 KiB  R/W scratch word w, w < 65536

  i.e. `LAYB_BASE` 0x0006_0000 -> **0x0008_0000** in rtl/seq_unit.sv and
  rtl/seq_movers.sv, and `layer_0 0x80000` with range **256K** in
  synth/scripts/create_project.tcl — BOTH the `seq_axib_map` entry AND the
  per-slave range expectation, which `exit 1`s on any range it does not
  expect. The mvchan windows are unchanged, and the two-pass parking still
  works: layer_0 is index 4, parked at 0x840000, which is 256 KiB-aligned
  and clear of the four 64 KiB mvchan parking slots ending at 0x83FFFF.

### B14.5 Field notes this re-encoding changes

  * **VNW COUNT: THE ESCAPE IS GONE.** B12.4 records that ARG0[10:0] made
    `0` ENCODE 2048. The field is ARG0[**12:0**] now, which holds 4096
    directly, so **`0` means 0** and `ref/gen_layer_script.Mach.vnw_`
    refuses it. `ld_n`/`ld_i` are 13 bits, so `ld_i + 1 == ld_n` still
    fires exactly at the last write. The 2048 every 2B stream emits is
    byte-identical either way. *(G3.1 wrote here: "The DATAPATH is
    unchanged: the vecnorm wbuf is still 2048 deep (`Mach.VNW_HW_MAX`) and
    a longer load still refuses — widening it to N=4096 is G3.2."  All
    three clauses are **SUPERSEDED 2026-09-02**; the sentence is kept as
    the record of what v2.0 landed with, and the amendment is below.)*

> **AMENDED 2026-09-02 — G3.2 LANDED THE VNW DATAPATH, so the bullet above
> is the only part of B14 that a later gate has overtaken.**
> `rtl/vecnorm_unit.sv`'s `xbuf`/`wbuf` are **4096** deep, its element
> counters (`cnt`/`n_total`/`oidx`/`ecnt`) are **13 bits**, its `w_waddr`
> and `layer_chan`'s `vn_waddr` are **12 bits**, and
> `ref/gen_layer_script.py:953` reads `VNW_HW_MAX = 4096`.  **A
> 4096-element VNW no longer refuses on either side**: the FIELD ceiling
> and the DATAPATH ceiling are both 4096, so `Mach.vnw_`'s assert can only
> fire above 4096, and `layer_chan`'s guard  <!--cites:noquote-->
> (`rtl/layer_chan.sv:1544-1547`, then a sim-only `$fatal` on
> `arg0[12:0] > 13'd4096`) is
> reachable only from a hand-built stream, because ARG0[12:0] still
> carries up to 8191.  **G3.4 made that guard SYNTHESIZABLE** — it is now
> a hardware refusal in `cmd_env_bad`, `rtl/layer_chan.sv:1131`, and 0 is
> refused too.
>
> **This also supersedes B12.4's "VECNORM nlog2 CEILING" note.**  The
> ceiling is `n_log2 = **12**` (n = 4096), the element counter is **13**
> bits, and `rtl/vecnorm_unit.sv:432`'s simulation `$fatal` now fires at
> `cfg_nlog2 >= 4'd13` with the message *"max 12, N=4096"*.  What B12.4
> says NEXT still stands and is still the open follow-on: there is **no
> command-decode range check on VN's `nlog2`** — `layer_chan`'s five
> envelope guards cover DNST/DNZ head, CONV, CONVW, VNW length and
> KVAP/ATTN kvhead, not `arg0[5:2]` — and every guard named in this
> paragraph is `` `ifndef SYNTHESIS ``, i.e. a simulation gate, not
> silicon protection.
>
> Gate: `evidence/qwen9b/g3/G3_2_VECNORM.md`.

  * **CONV/CONVW CHANNEL FIELDS ARE 14 BITS.** `CONV_DIM` is 8192 at 4B/9B,
    one count past the old 13-bit field's 8191, which is what a whole-block
    `convz` stopped on. **G3.4 grew the conv BANKS to 24 × 8192**, so the
    field, the counters and the bank all express 8192; the bank address
    registers stay 13 bits because 8192 IS 13 bits.  The sim-only guard is
    gone: `first + nch > 8192` and `nch == 0` are now refused **in
    hardware** (`err_op`, spec §5.4 S9).
  * **DNST/DNZ HEAD IS 5 BITS**, ARG0[4:0], for LNH = 32. **G3.4 widened
    the DN banking to 32 heads** — 24 URAM banks addressed as one linear
    `{dn_slot, head, row}` — so `dn_head_hw` and the head-≥-16 guard are
    both RETIRED and the ISA field and the datapath are the same five bits.
  * **KVAP/ATTN kvhead is 2 BITS**, ARG0[1:0], for NKV = 4 — and **G3.4
    widened the BANKING to match**: 8 KV banks of
    `{kv_slot, kvhead, k/v, t[8:0]}` and `tcnt_bank[8][4]`, so
    `kvhead_hw`, `Mach.KVH_HW_MAX = 1` and the sim guard are all retired.
    The four counters need two CSRs: TCNT (kvheads 0/1) and **TCNT2 at
    layer 0x60** (kvheads 2/3); a host that resets T must write both.
  * VECNORM nlog2 ceiling is unchanged from B12.4 — but `cfg_nlog2 > 12`
    is now a **hardware refusal** at the layer, not a `$fatal` inside
    `vecnorm_unit` (spec §5.4 S9).
  * Gate: `evidence/qwen9b/g3/G3_4_LAYER.md`.

### B14.6 What mechanizes this

  `evidence/qwen9b/g3/isa_bits.py` is the checker, and it is three things:
  a BIT BUDGET read out of `rtl/layer_chan.sv` by parsing (not
  transcribing); an EQUIVALENCE round-trip of every command through the
  THREE independent implementations of the pair layout — the canonical
  emitter, `sw/chat_seq.py`'s decoder and the RTL — plus the two sites that
  delegate to the helpers and hand-code the DNST parts
  (`ref/seq_model.py`, `tb/scripts/gen_seq_layer_script.py`); and a
  CEILING cross-check of every emitter bound against the RTL slice that has
  to carry it. `--negative-control` perturbs each field width in turn and
  requires every perturbation to be refused; `--dnst-map` is the DNSB
  layout-authority control. Gate doc: `evidence/qwen9b/g3/G3_1_ISA.md`.

---------------------------------------------------------------------
## B15. Layer state in DDR — the v2.1 extension (2026-09-04)

Spec: docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md §5 and A1.
(This file carries two sections numbered B14; B15 follows the second.)

### B15.1 Two new layer commands

  op 13 SLD   arg0={kind[12:11], slot[10], layer[9:5], head[4:0]}  arg1=0  arg2=0
  op 14 SST   the same fields
  kind: 0 DN, 1 KV, 2 CV, 3 reserved (refused, E_DMA_RANGE)
  slot: 0/1 (the cache slot of that kind)
  layer: DN/CV 0..23; KV 0..7 (the attention layer index)
  head:  DN must be 0 (a DN transfer moves the WHOLE layer, spec A1.1);
         KV {kvhead[2:1], kv[0]} (kv 0=K 1=V); CV must be 0
  arg1/arg2 must be 0 (refused otherwise, E_DMA_RANGE) — reserved for a row range.

  DDR address = SB_<kind> << 16  +  (index << shift)
     DN: index = layer                   shift 20  (1 MiB = 32 heads x 128 rows x 256 B,
                                                    laid out head-major: head h at +h<<15)
     KV: index = (layer*4 + kvhead)*2 + kv   shift 21  (2 MiB blocks; exponent side array at +1 MiB)
     CV: index = layer                   shift 17  (128 KiB blocks, rows padded to 16 B:
                                                    [63:0] weights, [111:64] state, [127:112] 0)
  Length: DN 4096 rows x 256 B; CV 8192 rows x 16 B; KV TCNT[layer][kvhead] rows x 256 B
          + TCNT exponent bytes (rounded up to 64 B), TCNT read when the
          transfer STARTS (the range check at dispatch uses the dispatch-time
          value).  The row a KVAP appends while the SST is still queued must
          therefore reach that SST, which is what the schedule needs.
          A KV SLD with TCNT = 0 moves nothing, warms the slot and sets its tag.

### B15.2 The LAYER CSR (0x30) selects CACHE SLOTS and the attention layer
  {18'b0, cv_slot[13:12], 1'b0, kv_layer[10:8], 3'b0, kv_slot[4:3], 1'b0, dn_slot[1:0]}
  dn_slot / kv_slot / cv_slot: 0 or 1 (2-bit fields; a value above 1 is refused at the
  next compute command, E_LAYER).  kv_layer: 0..7, the attention layer whose TCNT/TCNT2
  CSRs the host or program reads and writes.  Each KV slot carries a hardware TAG
  {layer[2:0], kvhead[1:0]} latched by the SLD that filled it; KVAP and ATTN index the
  append counters through the tag of the slot kv_slot names, and refuse (E_DMA_RANGE)
  when the command's own kvhead field differs from the tag's.

### B15.3 New CSRs (byte offsets; the RTL decodes word offsets 0x19..0x1D)
  0x64 SB_DN     RW  DN region base >> 16   (18 bits used)
  0x68 SB_KV     RW  KV region base >> 16
  0x6C SB_CV     RW  conv region base >> 16
  0x70 SDMA      RW  R: {busy_dma[31], queued[30:28], last_kind[27:26], last_slot[25], 17'b0, err[7:0]}
                     W: any write clears err (and err_op if it was set by E_DMA_AXI)
  0x74 SDMA_CYC  R   cycles while busy_dma; ANY write clears it (LCYC's twin for the DMA lane)
  STATUS (0x04) bit 0 is busy_any = busy_cmp | busy_dma; the CMD accept gate is busy_cmp
  alone; cmd_cnt increments when an SLD/SST is ENQUEUED; LCYC counts busy_cmp cycles only.

### B15.4 Error codes — STATUS.err_op set; SDMA.err carries the code
  (a different namespace from seq_unit's err_code: these are the LAYER's)
  0x01 E_ENV        a compute command's field envelope refused (the S9 checks, rtl/layer_chan.sv cmd_env_bad)
  0x02 E_LAYER      a LAYER slot field above 1 at a compute command's dispatch
  0x10 E_DMA_BASE   SB_<kind> is 0 at dispatch of an SLD/SST
  0x11 E_DMA_RANGE  kind 3; layer/head outside the kind's range; DN or CV head != 0; arg1/arg2 != 0;
                    a KV TCNT above 4096; a KVAP/ATTN kvhead that differs from the slot's tag
  0x12 E_DMA_AXI    any SLVERR/DECERR on the transfer — raised at completion, STICKY with err_op
                    until the host writes SDMA (the next compute dispatch does NOT clear it)
  0x13 E_DMA_COLD   a compute command names a slot with no completed load (or DNZ/CONVZ)
                    since the slot's last SST, or since reset
  Every refusal, including E_DMA_*, advances cmd_cnt (the layer's standing
  contract) so a polling sequencer halts on err_op rather than hangs.
  While E_DMA_AXI stands, a later refusal sets err_op but does NOT overwrite
  SDMA.err: the sticky code survives until the host writes SDMA.

### B15.5 Ordering
  SLD/SST run on the DMA lane, in program order among themselves, one transfer in
  flight. F1: a compute command whose slot has an SLD queued or in flight waits.
  F2: an SLD/SST on a slot waits while a compute command holds it; an SLD waits
  for every earlier SST on the same slot. A transfer on one slot of a kind may be in
  flight while a compute command holds the OTHER slot of that kind.
  DNZ zeroes head rows in the LAYER-selected DN slot and warms it; CONVW sel 2
  zeroes the state words of the LAYER-selected CV slot and warms it; CONVW sel 0/1
  are refused by the RTL (E_DMA_RANGE) — conv blocks arrive by SLD.

## B16. BM1 idle counters — SEQ 0x100.. (v2.2, 2026-09-24)

Spec: docs/superpowers/specs/2026-09-24-board-idle-counters-design.md §1–§2
(the user's rulings D1a–D8a, 2026-09-24) plus OV1's request that MOVX and
MOVY work be counted SEPARATELY (the next free words of the reserved block,
0x130/0x134; no address of the spec's table moved). RTL: rtl/seq_unit.sv,
the "BM1 idle counters" block and the read mux's 0x100 branch.

Host-read-only. Cleared by START with the PERF_* registers, counted while
busy_r (the PERF_CYC window), frozen at HALT. Writes are ignored (the block
has no write decode; ABORT does not clear it). Not reachable from any record
(0x2nn admits only 0x20 and 0x40..0x5C).
  0x100 BM_IDENT      R  0xFAB1_B301  (reads 0xDEADC0DE on build_041)
  0x104 BM_MVANY      R  cycles: any matvec engine busy
  0x108 BM_MV0        R  cycles: matvec chan 0 engine busy
  0x10C BM_MV1        R  ... chan 1
  0x110 BM_MV2        R  ... chan 2
  0x114 BM_MV3        R  ... chan 3
  0x118 BM_FENCE      R  cycles: mover busy on a FENCE (drain wait)
  0x11C BM_MVWORK     R  cycles: mover busy on MOVX/MVGO/MOVY
  0x120 BM_MVWORK_ANY R  cycles: mover work while any matvec engine busy
  0x124 BM_IMOVER     R  cycles: issue FSM in I_MOVER
  0x128 BM_STEPS      R  OP_EMB records dispatched (forward steps)
                         (also counts an OP_EMB that then faults E_ALIGN:
                         the term is (ist == I_EXEC) && !v_bad && r_op ==
                         OP_EMB, rtl/seq_unit.sv:1386, taken before the
                         alignment check at rtl/seq_unit.sv:1118-1120 —
                         harmless: a fault ends the run; noted 2026-09-27)
  0x12C (reserved; reads 0)
  0x130 BM_MOVX       R  cycles: mover busy on MOVX            (OV1's split)
  0x134 BM_MOVY       R  cycles: mover busy on MOVY            (OV1's split)
  0x138..0x1FC reserved for BM1/OV1 additions (read 0)
"engine busy" = matvec_chan's own STATUS bit 0 (cdc_sync_stat[0]),
already in aclk; no new CDC.

Derived on the host, not counted: weight path idle = PERF_CYC − BM_MVANY;
mover work with no engine busy = BM_MVWORK − BM_MVWORK_ANY; MVGO work =
BM_MVWORK − BM_MOVX − BM_MOVY. Identities (exact in simulation):
BM_FENCE + BM_MVWORK = mover busy cycles; max(BM_MV0..3) ≤ BM_MVANY ≤
Σ BM_MVc; BM_MOVX + BM_MOVY ≤ BM_MVWORK.

WIDTH AND WRAP. 32 bits, like PERF_CYC: a launch longer than 2^32 cycles
(17.2 s at 250 MHz) wraps every counter together.

ALIGNMENT. Each matvec_chan registers its busy bit once (port mv_busy_bm);
seq_unit takes it through two more flops and delays every local term
(busy_r, mv_busy, mv_op, ist == I_MOVER, the OP_EMB dispatch) by the same
three cycles, so every counter evaluates one cycle's values. On silicon the
2-FF synchroniser behind cdc_sync_stat resolves each asynchronous edge within
a cycle either way (spec §7 item 4); in simulation the counts are exact.

THIS SECTION WINS over B1's "reads outside the map return 0xDEADC0DE" for
0x100..0x1FC on a bitstream that has the block. Above 0x1FC (outside the
block, and not an XRF word) still reads 0xDEADC0DE.

WIRING. matvec_chan (and rtl/matvec_chan_ipi.v) gains ONE output,
mv_busy_bm; seq_unit gains mv_busy_bm[3:0] (rtl/seq_unit_ipi.v: four scalar
pins mv_busy_bm0..3); synth/scripts/create_project.tcl connects
mvchan_c/mv_busy_bm -> seq_0/mv_busy_bm<c>, both ends on xdma_0/axi_aclk.
No matvec_chan or layer_chan CSR changes; no other register moves.

FEATURE DETECTION, NOT A VERSION TABLE (spec §2.2). The host reads BM_IDENT
first and trusts the block only on the exact magic: sw/seq_run.py
Dev.seq_bm() (called by seq_perf(), which then carries a "bm" sub-dict); on
build_041 BM_IDENT reads 0xDEADC0DE and the key is omitted, so the same tool
runs on both bitstreams. The BM1 bitstream's VERSION (its tree hash, stamped
by synth/scripts/launch_build.sh) must still be admitted explicitly by the
identity gate (expect_version) before any SEQ access — that host change, the
SHAPE_ISA_BY_VERSION row and chat_seq --lanes are the board task's (T4), not
this addendum's. (Dated note, 2026-09-27: the expect_version admission
landed in sw/seq_run.py (SEQ_VERSIONS); the per-step lanes read that
chat_seq --lanes was to add went into evidence/qwen9b/bm/bm1_census.py
instead (it reads L_LCYC / L_SDMA_CYC around every launch), and chat_seq has
no --lanes flag; the sw/hwmap.py SHAPE_ISA_BY_VERSION row for build_042_bm1
is DEFERRED — NEXT_SESSION.md §9(b)21.)

## B17. The sequencer RTL round — SEQ_CAPS and the FENCE channel mask (v2.3, 2026-09-27)

(The header line was NOT bumped at v2.2 — §B16, the BM1 idle counters, is
v2.2 while line 1 still read v2.1 until this section; v2.3 bumps it.)

Spec: docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md §1.1 (R1)
and §1.4 (decision D5, the host-side guard); plan:
docs/superpowers/plans/2026-09-27-seq-rtl-round.md, Task SR2. RTL: lands at
Task SR3 (rtl/seq_unit.sv, rtl/seq_movers.sv) — until then NO bitstream
implements this section, and every shipped bitstream (build_041, build_042)
has the empty capability set. **AS BUILT (SR9, 2026-09-29):** R1 is in build_044_r1_incr (VERSION e3c2ff1e, SEQ_CAPS 0xFAB1CA01) and R1+R2 in build_045_r2_incr (266e3ae7, 0xFAB1CA03), both signed off and each loaded once and restored (`evidence/qwen9b/sr/SR8_R1_BOARD.md`, `evidence/qwen9b/sr/SR15_R2_BOARD.md`); build_041/042 keep the empty set; R3 is not built (§B17.3).

### B17.0 SEQ_CAPS — the capabilities word (SEQ 0x64)

  0x64 SEQ_CAPS  R  {magic[31:8] = 24'hFAB1CA, 5'b0, r3[2], r2[1], r1[0]}
    bit 0  r1  R1 built: the FENCE channel mask (B17.1)
    bit 1  r2  R2 built: XWIN/RES bank bits (B17.2)
    bit 2  r3  R3 built: MOVX broadcast (B17.3)
    bits 7:3   zero
    bits 31:8  the magic 0xFAB1CA

Read-only; writes are ignored. HOST-ONLY, not reachable from any record
(the 0x2nn CSRWR space admits only 0x20 and 0x40..0x5C). The magic is the
round plan's choice (the spec fixes only "a fixed magic in the high bits and
one bit per built feature", §1.4).

DECODE. The capability set is EMPTY unless word[31:8] == 0xFAB1CA; with the
magic, it is the set of names whose bit is 1, and a set bit in [7:3] is
REFUSED by name (an unknown capability is never guessed at). Every
pre-round bitstream (build_041, build_042) reads 0xDEADC0DE at 0x64 (the
read mux default; B1's "reads outside the map"), whose high 24 bits are not
the magic — so it decodes as the empty set. THIS SECTION WINS over B1 for
0x64 on a bitstream that has the word.

ONE DEFINITION. The offset, magic, bit positions and the word -> set
decoder live in sw/hwmap.py (S_SEQ_CAPS, SEQ_CAPS_MAGIC, SEQ_CAP_BITS,
seq_caps_set, seq_caps_word); ref/seq_format.py imports them and defines
none of its own; evidence/qwen9b/sr/sr2_isa_tdd.py ties this text to those
constants (offset, magic and bit positions are parsed out of the table
above), and the unit TB ties the RTL literal to them (SR3).

ADMISSION. The host validates every stream against the capability set
decoded from the DEVICE's SEQ_CAPS, and only on a VERSION the caller named
(sw/seq_run.py SEQ_VERSIONS, expect_version); a manifest's `caps` list is
informational and must be a subset of the device's. The validator's
argument is ref/seq_format.validate(..., caps=) / validate_stream(...,
caps=), default the empty set (today's rules — every existing caller is
unchanged).

### B17.1 R1 — the FENCE channel mask (capability "R1")

0x09 FENCE  target[3:0] = channel mask: the FENCE drains exactly the
            pending channels whose bit is set; mask 0 means ALL FOUR
            (today's meaning, so every existing stream — FENCE target 0 —
            is unchanged). flags, imm32, addr_lo, len_or_addr_hi and
            target[15:4] must be 0 (err 0x06).
            F_SCAN still waits for the AXI-Lite write pipe (wr_idle) in
            every case; the burst write engine needs no FENCE-side drain
            (MOVX and MOVY wait for it before they retire).
            A masked FENCE is still mv_op 3: §B16's BM_FENCE (C5) counts
            it unchanged.
            CHANNEL BINDING: bit c of target[3:0] is channel c — the
            mover's chan_pend[c] (`rtl/seq_movers.sv:255`; set by a
            no-wait MVGO at `rtl/seq_movers.sv:729`, cleared when its poll
            returns at `rtl/seq_movers.sv:754`, scanned by F_SCAN at
            `rtl/seq_movers.sv:846`), which is the engine channel c that
            MVGO/MOVX name in flags[7:4] and MOVY in target[3:0]
            (`docs/SEQ_ISA.md:115`, `docs/SEQ_ISA.md:378`) — matvec chan c
            (mvchan_c, whose m_axi reaches ddr4_c through smc_ch c:
            `synth/scripts/create_project.tcl:243`, then
            `synth/scripts/create_project.tcl:237`).
            NO RTL INTERLOCK: a pending channel OUTSIDE the mask stays
            pending after the FENCE, and the RTL does not stall or refuse a
            later MOVX/MVGO/MOVY on it. A stream that touches a pending
            channel before a FENCE covering it is INVALID; it is refused by
            the reference model gate (RunningChannelError,
            `ref/seq_model.py:455`) and by the pass's hazard assert
            (`ref/scripts/reorder_e4.py:225`), not by the RTL (spec §7 Q8
            default, decision D4 (a):
            `docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md:776-779`).
0x0A HALT   unchanged: every field must be 0 (err 0x06).

Validator: without "R1" in caps, FENCE keeps the all-zero rule (a non-zero
mask is refused, as the pre-round RTL refuses it); with "R1", target[3:0]
is admitted on FENCE only.

FORWARD COMPATIBILITY — fail-closed. An R1 stream on build_041/042: the
first FENCE with a non-zero mask faults err 0x06 at decode, BEFORE any
wrong result is consumed (those bitstreams require every FENCE field zero). AS BUILT: the RTL is SR3's (`rtl/seq_unit.sv`, `rtl/seq_movers.sv`; `evidence/qwen9b/sr/SR3_R1_RTL.md`), signed off in build_044_r1_incr (`evidence/qwen9b/sr/SR7_R1_BUILD.md`), and on silicon SEQ_CAPS read 0xfab1ca01 with every token identical (`evidence/qwen9b/sr/SR8_R1_BOARD.md`; SR9, 2026-09-29).

### B17.2 R2 — XWIN and RES bank bits (capability "R2")

Spec §1.2 (docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md);
plan Task SR11a (contract, validator, model) — the RTL lands at SR12, so
until then NO bitstream implements this section (AS BUILT, SR9 2026-09-29: the RTL is SR12's, `evidence/qwen9b/sr/SR12_R2_RTL.md` — where the engine's accumulator index g_q takes g_cnt, not x_line, its §6 item 2 — signed off in build_045_r2_incr, `evidence/qwen9b/sr/SR14_R2_BUILD.md`, and on silicon SEQ_CAPS 0xfab1ca03 with every token identical, `evidence/qwen9b/sr/SR15_R2_BOARD.md`). Semantics: a second x
vector can be loaded into a channel while its stream runs, and a finished
stream's RES can be drained while the next stream on that channel writes
the other half. No new storage: x_mem is 96 lines x 32 words = 3072 words
(12288 int8) per channel, RES is 4096 rows; a bank is half of each.

  field               where   meaning                          build_041/042 on non-zero
  MOVX target[11:0]   record  XWIN start WORD, 0..3071;        IGNORED (the MOVX dispatch
                              bank 1 is word 1536              never reads target)
  MVGO SHAPE bit 29   imm32   XBANK: x_line starts at line 48  IGNORED (SHAPE[31:29] not
                              instead of 0                     stored)
  MVGO SHAPE bit 30   imm32   RBANK: result rows land at       IGNORED
                              2048 + r
  MOVY target[15:4]   record  RES start ROW (12 bits)          faults err 0x06
  MVGO SHAPE bit 31   imm32   spare, must be 0 under every caps

  MOVX target[15:12] must be 0 (err 0x06). MVGO target[15:1] stays
  reserved 0 (target[0] = NO-WAIT, v1.4). The SHAPE READBACK (mvchan 0x14) still returns bits [31:29] as 0 on the R2 RTL — XBANK/RBANK are latched on write and are NOT readable (`rtl/matvec_chan.sv:18-31`), so host diagnostics must not try to read them back.

RANGE RULES (err 0x06 — E_RSVD, the code MOVY's target[15:4] faults with
today):
  MOVX   start word + ceil(len/4) words <= 3072 (the ragged tail's
         zero-padded word counts); start word <= 3071.
  MOVY   start row + len rows <= 4096.

BANK LEGALITY: a bank is legal only where the matvec fits it —
  XBANK  K <= 6144, i.e. SHAPE ng <= 48 (x lines 48 .. 48+ng-1 <= 95);
  RBANK  nrows <= 2048 (rows 2048 .. 2048+nrows-1 <= 4095).
  A K = 12288 matvec (mlp_down, ng 96) stays single and spans BOTH XWIN
  banks. The validator refuses an illegal bank. The RTL's only twin is the
  engine's sim-only envelope $fatal (spec §1.2), so on silicon this rule is
  VALIDATOR-SIDE ONLY, in the sense of §B10.

The MVGO reads x from word 1536*XBANK for K/4 words (ng lines) and writes
its nrows rows at 2048*RBANK; the MOVY reads len rows from its start row;
the MOVX writes at its start word. With every bank bit and start word
zero, all of this is exactly the pre-round behaviour (word 0, line 0,
row 0), so every existing stream is unchanged.

NO RTL INTERLOCK — RUNNING RANGES. The RTL keeps one pending bit per
channel and does not stall or refuse an access to a channel whose stream
is pending (B17.1). Per channel the pending stream owns an x-word range
[1536*XBANK, 1536*XBANK + 32*ng) and a RES-row range [2048*RBANK,
2048*RBANK + nrows). A stream is INVALID if, before a FENCE covering that
channel, it issues
  * a MVGO on the channel — whatever its banks (one engine per channel);
  * a MOVX whose word range overlaps the pending x range;
  * a MOVY whose row range overlaps the pending RES range.
A MOVX into the other bank, or a MOVY of the other half, is legal. The
reference model gate refuses an invalid stream by an explicit raise of
RunningChannelError (ref/seq_model.py SeqExec._movx/_mvgo/_movy, the
running ranges `SeqExec.running`); the model is also STRICTER than the
RTL about what a MVGO/MOVY reads: a MVGO reads exactly the vector the last
MOVX that started at its x word wrote (while no later MOVX overwrote any of
it), and a MOVY must lie inside one live MVGO result.

Validator: WITHOUT "R2" in caps the pre-round rules stand — MOVX target
non-zero, MOVY target[15:4] non-zero, and MVGO SHAPE bits 29/30 set are
each REFUSED (the SHAPE refusal is new with this section: it applies
whenever the caller has not stated the frozen isa=1 SHAPE layout, whose
bit 29 is w8 — the board-admission path it guards, sw/seq_run.py and sw/chat_seq.py,
has stated the DEVICE's layout since SR11a fix round 2, as below; evidence/qwen9b/sr/SR11a_R2_MODEL.md §8). SHAPE bit 29 is
AMBIGUOUS without a stated layout: w8 on build_034/035 (isa=1), XBANK on
build_041 onward (isa=2). A frozen isa=1 W8 artifact therefore validates
ONLY when its caller states shape_isa = SHAPE_ISA_PRE_G3, and the frozen 2B
W8 BOARD PATHS — evidence/qwen2b/rd/RD_GATE.md T4's seq_run4 on
build_035, and evidence/qwen2b/rd/rd_chat2b.sh (the tb/scripts/w5/ W8
template) — are admitted only because, since SR11a fix round 2,
sw/seq_run.py and sw/chat_seq.py state the DEVICE's layout
(hwmap.shape_isa_for_version of the VERSION the identity gate admitted;
build_035 is a SEQ_VERSIONS row named by --expect-version 54443b9f).
Pre-board and --dry-run validations state --shape-isa (1 for these
paths) or none, and with none such a stream is refused. WITH "R2" the three
fields are admitted under the range and bank-legality rules above. The
constants are ref/seq_format.py's XWIN_WORDS, XBANK_WORD, RES_ROWS,
RBANK_ROW, SHAPE_XBANK, SHAPE_RBANK.

FORWARD COMPATIBILITY — NOT fail-closed. An R2 stream on build_041/042
faults only at its first MOVY with a non-zero start row; a bank-1 MOVX
writes word 0 and an XBANK MVGO reads line 0, SILENTLY, so a MVGO whose RES
goes to bank 0 computes on the wrong x without any fault. The ONLY guard is
admission by the device's caps (B17.0): the host validates the stream at
the capability set decoded from the DEVICE's SEQ_CAPS, on a VERSION the
caller named — never at a manifest's claim — and an R2 record is refused
at caps {} (every pre-round bitstream) and at {"R1"} (an R1-only
bitstream).

### B17.3 R3 — MOVX broadcast (capability "R3")

AS BUILT (Task R3-10, 2026-10-01): BUILT — build_046_r3_incr, VERSION 2e874592, bitstream sha256 8b6675315ed8fd832aeea189638587e2dda86641e8665408f9140dbc67964993, signed off to G5D §10 (`evidence/qwen9b/sr/R3_10_BUILD.md`), NOT LOADED (its own load ruling names file + sha256). History: the round's R3 decision was SR16's (`evidence/qwen9b/sr/SR16_R3_DECISION.md`, form (a), (b) the fallback); NOT BUILT at the round's close (SR17 2026-09-29); ruled A 2026-09-29, plan docs/superpowers/plans/2026-09-29-r3-broadcast.md; the bit kept its reserved position so the
layout does not move.

CONTRACT (Task R3-1 of the R3 campaign, 2026-09-29; plan
docs/superpowers/plans/2026-09-29-r3-broadcast.md, Task R3-1). This
transcribes the design of spec §1.3 (a) and §1.4
(docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md) into contract
language and adds nothing to it. STATUS: BUILT (the AS BUILT line above). The
R3 RTL is Task R3-8's (rtl/seq_unit.sv, rtl/seq_movers.sv, rtl/matvec_chan.sv;
rtl/ at the build's launch tree 2e87459 is identical to R3-8's e4d8166); an
RTL line cited below with no commit pin is that R3 RTL. The AS BUILT note is
R3-10's. evidence/qwen9b/sr/sr2_isa_tdd.py --r3 ties
this text to sw/hwmap.py and to the RTL's error codes.

Semantics: one MOVX reads its scratch source ONCE and writes the same x into
the XWIN of all four channels, at the same words (the census's "one scratch
read, four XWIN writes", `evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md:633`).

  field               where   value       meaning
  MOVX flags[7:4]     record  0xF         BROADCAST to channels 0..3 (capability "R3")
  MOVX flags[7:4]     record  4..14       reserved, err 0x05 (E_CHAN), as today
  MVGO flags[7:4]     record  0xF         err 0x05: a broadcast is a MOVX only
  MOVX flags[3:0]     record  IND_NONE    indirection refused, err 0x02 (E_IND), as today
  MOVX target[11:0]   record  start word  the XWIN start word for ALL FOUR channels
  MOVX target[15:12]  record  0           err 0x06, as B17.2
  MOVX addr_lo, len   record  as unicast  scratch source word; int8 element count

  The error codes are the RTL's E_IND = 0x02 and E_CHAN = 0x05
  (`rtl/seq_unit.sv:298-299`). MOVY's channel field (target[3:0]) is
  unchanged: 4 or more is still err 0x05 — there is no broadcast MOVY.

WINDOW. The one target[11:0] names the window on every channel, so B17.2's
range rule (start word + ceil(len/4) words <= 3072; start word <= 3071; err
0x06) is applied to that one window, and a broadcast writes the same bank on
all four channels (bank 1 = word 1536, B17.2). The pass that emits a
broadcast forces the four consumers' XBANK to agree (spec §1.3, Emitter /
pass).

RETIREMENT. A broadcast MOVX retires only when every word is in every
channel's XWIN FIFO — the same commit contract the unicast burst keeps
(`rtl/matvec_chan.sv:100-110`), so the next MVGO's doorbell on any of the
four channels cannot overtake its x. How form (a) meets this is Task R3-8's
(the push leg's own commit contract).

XPTR. Today a unicast MOVX writes its channel's XPTR to 0 before its burst
(the X_XPTR state, `rtl/seq_movers.sv:904-905`); the burst itself never
touches XPTR (`rtl/matvec_chan.sv:112`). A broadcast leaves all four XPTRs
unchanged (the push carries its word index). This is architecturally
visible: the XPTR readback (mvchan 0x28, `rtl/matvec_chan.sv:381`) and the
next AXI-Lite XWIN write, which pushes at xptr (`rtl/matvec_chan.sv:350-353`),
see whatever the last unicast MOVX or host write left — host diagnostics
must not assume XPTR = 0 after a broadcast.

NO RTL INTERLOCK — RUNNING RANGES, per destination (B17.2's rule, applied to
each of the four channels). A broadcast is INVALID if, for ANY channel c,
its word range overlaps channel c's pending x range — every destination
channel's XWIN bank must be free. Such a stream is refused by the reference
model gate (RunningChannelError, `ref/seq_model.py:455`) and by the pass's
hazard assert (`ref/scripts/reorder_e4.py:225`), not by the RTL (spec §7
Q8). The cited lines are today's unicast refusals; the per-destination
check for a broadcast lands in the model at Task R3-3 and in the pass at
Task R3-5. Spec §1.3 says "the validator requires every destination
channel's XWIN bank free"; as B17.2 splits it, the per-record validator
(ref/seq_format.validate) is stateless and cannot see pending ranges, so
"the validator" there means the model gate plus the pass's assert.

ADMISSION. A broadcast is validated only when {"R1", "R2", "R3"} ⊆ caps
(the one bitstream that builds R3 also has R1 and R2; the validator names
every missing capability). That bitstream's SEQ_CAPS word = 0xFAB1CA07,
which is hwmap.seq_caps_word of {"R1", "R2", "R3"} (the bits are
SEQ_CAP_BITS, `sw/hwmap.py:358-360`; B17.0). Without that set, MOVX
flags[7:4] of 4 or more keeps today's refusal. As B17.0: caps are the
DEVICE's, decoded from its SEQ_CAPS on a VERSION the caller named, never a
manifest's claim. An r3 stream also carries B17.2 bank fields, which are
NOT fail-closed on an older bitstream (B17.2, FORWARD COMPATIBILITY), so on
an R1-only or R1+R2 device the admission must fail on the broadcast record,
by the validator, before upload — never by reaching the RTL. (The validator
is Task R3-2's.)

FORWARD COMPATIBILITY — fail-closed. Every pre-R3 bitstream (build_041,
build_042, build_044_r1_incr, build_045_r2_incr) faults err 0x05 at the
decode of a broadcast MOVX, before any word moves: the pre-R3 RTL refuses a
MOVX or MVGO whose flags[7:4] is 4 or more as E_CHAN
(`a65f87c:rtl/seq_unit.sv:798-800`; spec §1.3 reads the same refusal on
build_041/042). The device-keyed admission refuses it first; the RTL fault
is the second line.

COUNTERS. A broadcast is one mover job with mv_op 0: BM_MVWORK (the BM1
spec's C6) and BM_MOVX count its cycles once, as one MOVX; no counter
changes (§B16).

FORM. (a), the direct x-push bus (spec §1.3 (a), decision D3; the user's
ruling 2026-09-29): seq_movers pushes each word with its word index to all
four matvec_chan XWIN FIFOs on a new aclk point-to-point port, only when all
four have room (lockstep); AXI-Lite still wins each FIFO's mux. The ISA
above does not depend on the form (another form would have to meet the same
XPTR and retirement rules).

NOT CLAIMED. This section states semantics only. It does not claim that a
broadcast costs one MOVX window (the spec's pricing, not measured), the push
rate, the lockstep's back-pressure, or any timing; none is established
(`evidence/qwen9b/sr/SR16_R3_DECISION.md:237-252`).
