# SEQ ISA v1.6 — AS-BUILT CONTRACT (2026-08-12)
#
# = the v1.5 FROZEN TEXT (unchanged, below) + AS-BUILT ADDENDA (bottom).

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

v1.0 -> v1.1: eleven ambiguities (A1-A11, ref/seq_format.py header)
resolved by orchestrator ruling; two new opcodes (LDC, XOP).
v1.5 -> v1.6 (2026-08-12): as-built consolidation. No opcode, field or
semantic CHANGE is introduced here; v1.6 folds in the 2026-08-09 chat-seq
corrections, the rung-4 OUT FIFO rework, the rung-4 TOPK-32 CSR block and
the g64 SHAPE bit, all of which shipped and are already on silicon
(build_033).

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
  2026-08-09  chat-seq as-built corrections (CTRL[1]=ABORT, no
              pc field in STATUS)                               -> B2
  2026-08-11  rung 4 S5: TOPK-32 CSR block at layer 0x48..0x58  -> B8
  2026-08-11  rung 4 S6: OUT FIFO depth 64, derived of_cnt,
              sticky of_ovf in STATUS, pop-only-if-delivering   -> B3

---------------------------------------------------------------------
## B1. SEQ CSR block — as-built map (rtl/seq_unit.sv:24-43)
---------------------------------------------------------------------

4 KB AXI-Lite window; create_project.tcl maps seq_0's s_axil at BAR byte
offset 0x6000, which is what sw/hwmap.py:85 (`SB`) and
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

  Reads outside the map return 0xDEADC0DE (seq_unit.sv:1385).
  PERF_FST bit0 is the STICKY xrf_ovf flag, not a cycle count: an XOP
  result that did not fit 18 bits was truncated (B5).

WHAT A START DOES NOT CLEAR (seq_unit.sv:890-898, verified against the
reset block at :841-861): the OUT FIFO contents, of_ovf, the XRF,
xrf_ovf, TCNT_SEQ, BASE/LEN/ENTRY. START clears only busy/halted/err/
err_code/abort_req and the five PERF counters, and sets pc <= ENTRY.
Only a hard reset clears the rest. This is the contract the host chat
loop depends on (sw/chat_seq.py drains the FIFO before every START).

---------------------------------------------------------------------
## B2. CTRL / STATUS — as-built (ratified 2026-08-09, widened 2026-08-11)
---------------------------------------------------------------------

The v1.1 text sketched "SEQ_STATUS {halted, err, err_code[31:24],
out_cnt[20:16]}" and implied a SEQ_ABORT register. As built:

  * ABORT is CTRL bit 1 (seq_unit.sv:1200, `abort_req`). There is NO
    separate SEQ_ABORT register and never was. Ratified 2026-08-09,
    docs/CHAT_SEQ_SPEC.md:145.
  * ABORT is honoured at a RECORD BOUNDARY only (tested in I_FETCH,
    seq_unit.sv:911) and raises err_code 0x0C. There is no watchdog on
    I_SYNCW / I_AMAXW / I_BULK*, so a wedged DDR read is NOT abortable —
    it needs a reprogram.
  * STATUS has no pc field. pc is its own 32-bit register at +0x14.
  * STATUS bit layout, as built (seq_unit.sv:1358-1359), after rung 4 S6
    widened out_cnt from 5 to 7 bits and moved of_ovf in beside it:

      [31:24] err_code   [23] of_ovf   [22:16] out_cnt(0..64)
      [15:3]  reserved 0 [2]  halted   [1] err   [0] busy

    sw/hwmap.py:117-123 (SEQ_ST_OUTCNT_MASK = 0x7F, SEQ_ST_OF_OVF =
    1<<23) and hwmap.seq_status() decode exactly this.

---------------------------------------------------------------------
## B3. OUT FIFO — as-built (rung 4 S6, 2026-08-11)
---------------------------------------------------------------------

Written by AMAXL (B4) and drained by the host through OUT_FIFO (0x18).

  * DEPTH 64 (seq_unit.sv:306, `OF_DEPTH`; was 16). The old depth silently
    dropped tokens on any launch longer than 16 tokens.
  * of_cnt is DERIVED, not stored: `of_cnt = of_wp - of_rp` over two
    7-bit pointers with the extra MSB that distinguishes full from empty
    (seq_unit.sv:308-310). This retires an entire race class: push
    (I_AMAXW) and pop (csr_of_pop) live in the same always_ff and used to
    both assign a third `of_cnt` register, so a host pop landing on an
    AMAXL push lost the push's increment. sw/chat_seq.py:93 documents the
    host-side workaround that is no longer needed.
  * OVERFLOW DROPS, NEVER STALLS. A push into a full FIFO is discarded
    and sets the sticky of_ovf (seq_unit.sv:1143-1146). Fullness is
    judged on the PRE-pop count, so a push racing a host pop on a full
    FIFO is dropped rather than squeezed into the slot being freed.
  * of_ovf is STICKY UNTIL HARD RESET — not cleared by START, by a halt,
    or by draining. A host that sees it must treat every later token of
    the session as suspect (sw/hwmap.py:118-122).
  * READ IS THE POP, and the pop now happens ONLY IF THE READ ACTUALLY
    DELIVERED A TOKEN: `csr_of_pop <= (of_cnt != 0)` (seq_unit.sv:1372).
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
decode validator (seq_unit.sv:684-737); execution-time errors are in B6.

0x01 CSRWR  flags[3:0]=ind, flags[7:4]=XRF idx; target=csr_id;
            imm32=value (post-indirection). addr_lo/hi unused.
            csr_id spaces (seq_unit.sv:814-825):
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
            sequencer's ARG0/ARG1/ARG2 shadow (seq_unit.sv:949-954) —
            that shadow is what makes the XRF-writer sniff of B5 work.

0x02 CMD    flags must be 0 (err 0x04); target[15:12] must be 0 (err
            0x07); writes imm32 to LAYER_BASE + target[7:0], then waits
            for the layer cmd_cnt shadow to advance and checks err_op.
            Layer err_op -> err 0x10; watchdog -> err 0x11.

0x03 MOVX   flags[3:0] must be 0 (indirection FORBIDDEN, err 0x02);
            flags[7:4]=chan, >=4 -> err 0x05.
            addr_lo[13:0] = scratch source word; len_or_addr_hi[23:0] =
            int8 ELEMENT count. XWIN words pushed = ceil(len/4)
            (seq_movers.sv:512); a ragged tail is zero-padded.
            target is reserved 0 by convention — see B10.

0x04 MOVY   flags[3:0]=ind, flags[4]=mode (0 = int32 {lo,hi} pairs,
            1 = int16), flags[7:5]=XRF idx (A1);
            target[3:0]=chan (>=4 -> err 0x05), target[15:4] must be 0
            (err 0x06); imm32 = dequant shift, POST-indirection, signed;
            addr_lo[13:0] = scratch dst word; len_or_addr_hi[23:0] = RES
            rows. Scratch words written = len (int16) or 2*len (pairs).
            Dequant = rshr64s + round-half-away, then clip to int16 in
            int16 mode and to int32 in pairs mode (seq_movers.sv:432-440,
            460-475) — bit-for-bit ref/w4a8_ref.rshift_round +
            seq_model.rs_s/clip16.

0x05 MVGO   flags[3:0] must be 0 (err 0x02); flags[7:4]=chan (err 0x05);
            imm32 = SHAPE (B9); addr_lo = WBASE[31:0];
            len_or_addr_hi = {beats[23:0], wbase[39:32]} (A7 — the RTL
            reads mv_wbase={hi[7:0],lo}, mv_beats=hi[31:8],
            seq_unit.sv:970-977). target[0] = NO-WAIT (v1.4);
            target[15:1] reserved 0 by convention — see B10.

0x06 EMB    flags must be 0 (err 0x04).
            DDR byte address = {target[15:0], imm32[31:0]} truncated to
            ADDR_W(34) + XRF[3] * 2048 (seq_unit.sv:827-829, EMB_ROW_
            BYTES = 2048). i.e. the embedding table base is carried in
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
            taken iff the PRE-decrement TCNT_SEQ != 1 (seq_unit.sv:1023-
            1033). HAZARD: TCNT_SEQ == 0 at a flags=1 JMP wraps to
            2^32-1 and the stream runs ~forever — every compiled image
            must set TCNT_SEQ explicitly.

0x09 FENCE  every field must be 0 (err 0x06). Drains movers + the burst
            write engine; this is what retires a NO-WAIT MVGO.

0x0A HALT   every field must be 0 (err 0x06). busy -> 0, halted -> 1.

0x0B LDC    flags[3:0]=ind, flags[7:4]=XRF idx (v1.4; only the 3 LSBs
            are significant, idx >= 8 -> err 0x03).
            DDR byte address = signed{len_or_addr_hi, addr_lo} +/- XRF[i]
            per the indirection code (seq_unit.sv:830-833);
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
    for everything else (seq_unit.sv:645-647). The index actually used is
    the low 3 bits.
  * XRF[3] READS AS UNSIGNED, every other entry as signed 18-bit
    (seq_unit.sv:323-327, xrf_rd) — A11, as built on both sides
    (layer_chan.sv:44-47 says the same about its XRFD window).
  * XOP overflow: the 32-bit result is written truncated to 18 bits and
    sets the STICKY xrf_ovf flag if it leaves [-131072, +262143]
    (seq_unit.sv:1037-1039). The asymmetric bound is deliberate: the
    positive side allows a full UNSIGNED 18-bit token id (XRF[3]).
    xrf_ovf is readable as PERF_FST bit 0.
  * WRITE-THROUGH. Every XRF write a RECORD makes (CSRWR into the 0x2nn
    XRF space, XOP, AMAXL) is also written into layer_chan's XRFI/XRFD
    window when XRF_WRITE_THROUGH=1 (the default), so the two copies
    cannot disagree — vecnorm EPS-NORM reads k from layer_chan's copy.
    A HOST AXI write to SEQ 0x40+4i does NOT write through
    (seq_unit.sv:1207-1208): host XRF seeding must go in-stream.
  * REFRESH (the other direction). The sequencer re-reads the XRF after
    exactly the commands that write it, recognised from the ARG shadow it
    issued itself: ALU sub-op 0 (DYNQ8) -> read layer EOUT 0x1C -> XRF[0];
    ALU sub-op 12 (DYNQ16) -> read layer XRFD -> XRF[1] or XRF[2] per
    arg2[0]; ALU sub-op 8 with arg2[6] (the op-8 k_a probe) -> XRF[2]
    (seq_unit.sv:104-107, 810-812).

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

0x01..0x12 are raised in rtl/seq_unit.sv:271-275; 0x12 and 0x20..0x23
also in rtl/seq_movers.sv:173-177. sw/hwmap.py:129-150 (SEQ_ERR) carries
the same table with the same text.

---------------------------------------------------------------------
## B7. layer_chan CSR map — as-built (rtl/layer_chan.sv:12-30)
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
MAXPH) are present in the RTL and in sw/hwmap.py:61-69. The TOPK block is
the only layer CSR group hwmap does NOT carry (B11).

Layer COMMAND opcodes (the CMD record's payload, layer_chan.sv:68-97):
1 VN, 2 VNW, 3 ROPET, 4 ROPE, 5 CONVW, 6 CONV, 7 GATE, 8 DNST, 9 KVAP,
10 ATTN, 11 ALU, 12 DNZ.

vec_alu SUB-ops (command 11 ALU, sub-op = ARG0[3:0], rtl/vec_alu.sv:14-48)
— do not confuse these two numberings:
sub-op 0 DYNQ8, 1 SHIFT32, 2 SCALE, 3 EMUL, 4 ADD, 5 SILU16, 6 SILU32,
7 SIGM16, 8 EMUL32 (+ probe), 9 SHIFT32W, 10 AMAX32, 12 DYNQ16.
There is no vec_alu sub-op 11. The two ISA-introduced ops are unchanged
from v1.1:
DYNQ16 latches k into XRF[cfg_p0[0] ? 2 : 1] with cfg_p0[1] = clamp-at-0,
and the op-8 PROBE is selected by cfg_p0[6] (v1.3, NOT p0[2] — vec_alu.sv
:57-66 records why p0[2] was impossible) and always targets XRF[2].

---------------------------------------------------------------------
## B8. TOPK-32 block — NEW CSR contract (rung 4 S5, 2026-08-11)
---------------------------------------------------------------------

A sibling block inside layer_chan (module `layer_topk32`,
rtl/layer_chan.sv:1774-1908), addressed in the layer 0x0nn CSRWR space at
0x48..0x58 — decode space that was free, so no BD / create_project edit
was needed. Live on silicon since build_033. Previously documented only
in docs/RUNG4_SPEC.md S5; this is now its ISA home.

  0x48 TK_IDENT  R  0xFAB1704B
  0x4C TK_STATUS R  {24'b0, overflow[7], complete[6], count[5:0]}
  0x50 TK_PTR    RW {27'b0, ptr[4:0]}  entry cursor
  0x54 TK_VAL    R  int32 value of entry[ptr]  — NO side effect
  0x58 TK_IDX    R  {14'b0, idx[17:0]} of entry[ptr] — PTR++ ON READ

Semantics, all verified against layer_chan.sv:556-580, 709-716, 727-728
and the module body:

  * FEED. One registered 51-bit bundle exported from vec_alu at the
    AMAX32 compare site: {we = t_cp[0] && op_q==10, val = cp_v32,
    idx = am_g} (vec_alu.sv:425-426). II=1, no backpressure, and the
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
## B9. MVGO SHAPE word — as-built (rtl/matvec_chan.sv:18-19, 305-309)
---------------------------------------------------------------------

The MVGO record's imm32 is written verbatim to the channel's SHAPE CSR:

  bit 28    g64   0 = legacy G=128 rows (bit-identical to pre-v2),
                  1 = G=64 v2 row format (each 64 B weight beat carries
                  TWO groups of 64; ceil((K/64)/32) scale beats follow
                  the weight beats — see ref/w4a8_ref.py)
  [27:12]   nrows (16 bits as built)
  [11:6]    sh
  [5:0]     ng    = WEIGHT-beat count of one row = K//128, in BOTH modes

Bits [31:29] are read back as 0. The per-image group size travels in the
manifest as "g" (ABSENT means 128); hosts pack the word with
sw/hwmap.shape_word(nrows, sh, ng, g).

---------------------------------------------------------------------
## B10. What the RTL enforces vs what only the emitter enforces
---------------------------------------------------------------------

Two v1.5 reserved-field rulings are EMITTER-SIDE ONLY. They are real
contract, but a hand-built stream that violates them will run, not fault:

  * "MOVX target reserved 0" — ref/seq_format.py:469 rejects it;
    rtl/seq_unit.sv:706-709 does not look at MOVX target at all.
  * "MVGO target[15:1] reserved 0" — ref/seq_format.py:467 rejects it;
    the RTL uses only target[0] (NO-WAIT) and ignores the rest.

Enforced by BOTH sides: MOVY target[15:4]==0, AMAXL/FENCE/HALT all-zero
operands, XOP flags==0 and target<8, XOP sign code 11, JMP flags in
{0,1}, MOVX/MVGO no-indirection, channel < 4, XRF index < 8.

Enforced by the RTL ONLY (the emitter validator does not check it):
CSRWR csr_id space (target[15:12] <= 2) and the matvec channel field.

---------------------------------------------------------------------
## B11. Disagreements found while consolidating (2026-08-12)
---------------------------------------------------------------------

Recorded, not silently patched. The RTL is the truth in each case.

1. JMP BOUND, off by one. rtl/seq_unit.sv:725 faults when
   `r_imm >= seq_len`; ref/seq_format.py:489 only faults when
   `r.imm32 > nrec`. A stream with a JMP to exactly `nrec` passes the
   emitter validator and then dies on chip with err 0x08. The v1.4
   ruling ("target must be < nrec") agrees with the RTL. Fix belongs in
   seq_format.validate — flagged for its owner, not changed here.
2. SHAPE nrows WIDTH. sw/hwmap.py:34 documents `nrows[24:12]` (13 bits);
   rtl/matvec_chan.sv:308 latches `wdata_q[27:12]` into a 16-bit
   register. hwmap's shape_word() does not mask, so packing is correct
   for any nrows the RTL accepts — only the comment understates the
   field. B9 above carries the as-built width.
3. TOPK-32 IS ABSENT FROM sw/hwmap.py. The block's five CSRs are
   declared locally in sw/chat_seq.py:203 (TOPK_BASE = HW.LB + 0x48)
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
