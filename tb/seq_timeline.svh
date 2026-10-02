// seq_timeline.svh — the WHOLE-TOKEN TIMELINE CENSUS (task BN1).
//
// INCLUDED INTO tb_seq_chip's module body (one `include line in
// tb/tb_seq_chip.sv).  It is an INSTRUMENT, not a testbench change:
//
//   * it NEVER drives a DUT signal.  Every name it touches is read, in a
//     `always @(negedge clk)` block, at the TB's own sampling edge (house
//     rule: the DUT changes state on posedge, the TB samples on negedge),
//     so a value sampled at negedge N is the value that stood DURING
//     cycle N.
//   * it is GATED by `+timeline=<csv path>`.  Absent, `tl_en` is 0, the
//     sampler's body never executes and the testbench is behaviourally
//     what it was — which is deliverable 2's control: the same binary,
//     run twice, must report the SAME cycle count and the SAME tokens.
//   * `rtl/` is untouched.  Everything below is a hierarchical reference
//     from the TB into the instantiated design, which is what this file
//     already does for `u_layer.tcnt_bank`, `u_layer.smem_a` and
//     `u_layer.eout_q` (tb/tb_seq_chip.sv:878, :1039, :1018).
//
// WHAT IT CLASSIFIES, per aclk cycle, while the sequencer is BUSY
// (`seq_unit.busy_r`, rtl/seq_unit.sv:341 — the same condition
// `PERF_CYC` counts on, rtl/seq_unit.sv:928, so the census total is
// checkable against CSR 0x2C):
//
//   bit  0  L_CMP    layer compute lane          rtl/layer_chan.sv:455
//   bit  1  L_DMA    layer state-DMA lane        rtl/layer_chan.sv:687
//   bit  2  MOVER    seq_movers engine busy      rtl/seq_unit.sv:833
//   bit  3  SEQBULK  LDC/EMB DDR read active     rtl/seq_unit.sv:488
//   bit  4  MV0_STR  weight beat on chan 0 this cycle   (see below)
//   bit  5  MV1_STR                   chan 1
//   bit  6  MV2_STR                   chan 2
//   bit  7  MV3_STR                   chan 3
//   bit  8  MV0_BSY  matvec chan 0 engine busy   rtl/matvec_chan.sv:222-224
//   bit  9  MV1_BSY                   chan 1
//   bit 10  MV2_BSY                   chan 2
//   bit 11  MV3_BSY                   chan 3
//   bit 12  SMEM_RD  state window read beat      tb/tb_seq_chip.sv:427
//   bit 13  SMEM_WR  state window write beat     tb/tb_seq_chip.sv:431
//   bit 14  RECDDR   record/LDC/EMB read beat    tb/tb_seq_chip.sv:162
//   bit 15  BFAB     burst fabric busy           tb/seq_burst_fabric.sv:227
//
// THE WEIGHT-STREAM BITS CROSS A CLOCK DOMAIN AND ARE COUNTED, NOT
// SAMPLED.  Each channel's weight memory (`g_mv[c].u_wmem`) runs on
// `ui_clk` (~300 MHz) while this sampler runs on `clk` (250 MHz), so a
// level sampled at the slower edge would drop beats.  `w_nbeats[c]` is
// that model's own R-beat counter (tb/seq_mem_file.sv:348-349), monotone
// and already a TB-level signal (tb/tb_seq_chip.sv:174); the sampler takes
// its DELTA since the previous negedge.  "Streaming this cycle" is
// delta != 0 — lossless in the aggregate, and the deltas themselves are
// summed per record and per token so the measured beats/cycle rate comes
// out of the same sampling.
//
// NOT IN THE SIGNATURE, counted as scalars (they are sequencer-internal
// and would quadruple the histogram): the fetch-empty stall
// (rtl/seq_unit.sv:933's own condition), the AXI-Lite fabric's outstanding
// counters, the issue FSM's state `ist` (a per-token histogram over all 32
// encodings) and the mover's `mv_op`.
//
// WHAT IT WRITES
//   * a per-RECORD row: index, pc, opcode, flags, target, the layer
//     opcode it dispatched (if any), the first busy cycle, the cycle
//     count, then the 16 class counts, the 4 weight-beat deltas, the
//     stall count, and the "no class active" residue.  A record's window
//     runs from the cycle the issue FSM latched it (`rec_valid`,
//     rtl/seq_unit.sv:976-977) to the cycle before the next record is
//     latched, so the rows PARTITION the busy time exactly.
//   * a signature histogram section: every 16-bit active-set mask that
//     occurred, per token and for the run.
//   * a `SEQ_TIMELINE` block on stdout carrying every total, so the log
//     alone is sufficient if the CSV is lost.
//
// TOKENS, and why the boundary is the EMB record and NOT the backward
// jump.  `model_9b_s1` is ONE launch of 158,536 records that decodes six
// tokens, but it does NOT loop six times: the stream holds FOUR forward
// steps written out (their `OP_EMB` records at indices 39, 39,663, 79,286
// and 118,911) and the LAST of them is a TCNT_SEQ=3 loop body
// (`CSRWR -> 0x2020 imm 3` at record 118,910, then `OP_JMP` flags[0] at
// 158,534 targeting 118,911; rtl/seq_unit.sv:1086-1098).  So `pc` steps
// BACKWARD only twice in the whole launch while six tokens come out, and a
// backward-jump segmentation would put four tokens in one bucket.
//
// Every forward step instead begins by fetching its embedding row, so the
// sampler opens a new segment on each `OP_EMB` record: segment 0 is the
// launch PREAMBLE (records 0..38, before the first EMB) and segments 1..6
// are the six tokens.  The backward steps of `pc` are still counted and
// reported (`SEQ_TIMELINE backjump`) so the two views can be checked
// against each other.  NB the backward jump is fine as a PERIOD measure —
// RD9 §10.1's "cycles between consecutive backward jumps of `S_PC`" spans
// exactly one token here (32,792,031 cycles).  It is useless as a
// SEGMENTATION on this stream, which is the point above: two jumps, six
// tokens, four of them in one bucket.
//
// The few records between an `AMAXL` and the next `EMB` (two, here) are
// charged to the OUTGOING segment; the boundary is the EMB itself.

    // ------------------------------------------------------------------
    // sizes
    // ------------------------------------------------------------------
    localparam int TL_NCLS = 16;               // signature width
    localparam int TL_NSIG = 1 << TL_NCLS;
    localparam int TL_NTOK = 8;                // segments a launch may have
    localparam int TL_NOP  = 16;               // SEQ record opcodes 0..15
    localparam int TL_NIST = 32;               // istate_e is 5 bits

    string tl_path;
    int    tl_fd  = 0;
    bit    tl_en  = 1'b0;

    // ---- accumulators, per segment (token) ---------------------------
    longint tl_cls  [TL_NTOK][TL_NCLS];
    longint tl_pair [TL_NTOK][TL_NCLS][TL_NCLS];
    longint tl_union[TL_NTOK];
    longint tl_none [TL_NTOK];
    longint tl_tcyc [TL_NTOK];
    longint tl_stall[TL_NTOK];
    longint tl_axw  [TL_NTOK];
    longint tl_axr  [TL_NTOK];
    longint tl_ist  [TL_NTOK][TL_NIST];
    longint tl_opcyc[TL_NTOK][TL_NOP];
    longint tl_opcnt[TL_NTOK][TL_NOP];
    longint tl_mvop [TL_NTOK][4];
    longint tl_wb   [TL_NTOK][4];
    longint tl_sig  [TL_NTOK][TL_NSIG];
    longint tl_sigall[TL_NSIG];
    longint tl_bcyc;                            // busy cycles, whole launch
    longint tl_backj;                           // backward pc steps seen
    longint tl_nrec;                            // records seen
    int     tl_tok;                             // current segment
    int     tl_ntok;                            // segments seen

    // ---- the open record ---------------------------------------------
    longint rc_cls [TL_NCLS];
    longint rc_wb  [4];
    longint rc_cyc0, rc_ncyc, rc_stall, rc_none;
    int     rc_pc, rc_op, rc_flags, rc_tgt, rc_lop, rc_tok;
    longint rc_idx;
    bit     rc_open;

    // ---- sampler state ------------------------------------------------
    logic [63:0]        tl_wbprev [4];
    logic [63:0]        tl_wbd    [4];
    logic [TL_NCLS-1:0] tl_sigw;
    bit                 tl_rvq;
    bit                 tl_busyq;
    int                 tl_pcq;

    // matvec engine busy, in the ACLK domain: matvec_chan's own 2FF
    // synchroniser of `ui_busy` (rtl/matvec_chan.sv:221-224), which is the
    // same bit its STATUS CSR reports.  Slots the elaboration does not
    // build read 0, exactly as `w_nbeats` does (tb/tb_seq_chip.sv:407-410).
    logic [3:0] tl_mvb;
    for (genvar tc = 0; tc < 4; tc++) begin : g_tl_mvb
        if (tc < NMV) begin : g_on
            assign tl_mvb[tc] = g_mv[tc].u_mv.cdc_sync_stat[0];
        end else begin : g_off
            assign tl_mvb[tc] = 1'b0;
        end
    end

    // ------------------------------------------------------------------
    function automatic string tl_clsname(input int i);
        case (i)
            0:  tl_clsname = "L_CMP";
            1:  tl_clsname = "L_DMA";
            2:  tl_clsname = "MOVER";
            3:  tl_clsname = "SEQBULK";
            4:  tl_clsname = "MV0_STR";
            5:  tl_clsname = "MV1_STR";
            6:  tl_clsname = "MV2_STR";
            7:  tl_clsname = "MV3_STR";
            8:  tl_clsname = "MV0_BSY";
            9:  tl_clsname = "MV1_BSY";
            10: tl_clsname = "MV2_BSY";
            11: tl_clsname = "MV3_BSY";
            12: tl_clsname = "SMEM_RD";
            13: tl_clsname = "SMEM_WR";
            14: tl_clsname = "RECDDR";
            15: tl_clsname = "BFAB";
            default: tl_clsname = "?";
        endcase
    endfunction

    // ------------------------------------------------------------------
    task automatic tl_reset_rec();
        begin
            for (int i = 0; i < TL_NCLS; i++) rc_cls[i] = 64'd0;
            for (int c = 0; c < 4; c++)       rc_wb[c]  = 64'd0;
            rc_ncyc = 64'd0; rc_stall = 64'd0; rc_none = 64'd0;
            rc_lop  = -1;
        end
    endtask

    // one CSV row per record.  `-1` in the lop column means the record
    // dispatched no layer command (or none was in flight in its window).
    task automatic tl_flush_rec();
        begin
            if (rc_open && (tl_fd != 0)) begin
                $fwrite(tl_fd, "R,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",
                        rc_idx, rc_tok, rc_pc, rc_op, rc_flags, rc_tgt,
                        rc_lop, rc_cyc0, rc_ncyc);
                for (int i = 0; i < TL_NCLS; i++)
                    $fwrite(tl_fd, ",%0d", rc_cls[i]);
                for (int c = 0; c < 4; c++)
                    $fwrite(tl_fd, ",%0d", rc_wb[c]);
                $fwrite(tl_fd, ",%0d,%0d\n", rc_stall, rc_none);
            end
            rc_open = 1'b0;
        end
    endtask

    // ------------------------------------------------------------------
    initial begin
        tl_bcyc = 64'd0; tl_nrec = 64'd0; tl_tok = 0; tl_ntok = 1;
        tl_backj = 64'd0;
        tl_rvq = 1'b0; tl_busyq = 1'b0; tl_pcq = 0; rc_open = 1'b0;
        rc_idx = 64'd0; rc_cyc0 = 64'd0;
        rc_pc = 0; rc_op = 0; rc_flags = 0; rc_tgt = 0; rc_lop = -1;
        rc_tok = 0;
        for (int c = 0; c < 4; c++) tl_wbprev[c] = 64'd0;
        for (int t = 0; t < TL_NTOK; t++) begin
            tl_union[t] = 64'd0; tl_none[t] = 64'd0; tl_tcyc[t] = 64'd0;
            tl_stall[t] = 64'd0; tl_axw[t] = 64'd0; tl_axr[t] = 64'd0;
            for (int i = 0; i < TL_NCLS; i++) begin
                tl_cls[t][i] = 64'd0;
                for (int j = 0; j < TL_NCLS; j++) tl_pair[t][i][j] = 64'd0;
            end
            for (int i = 0; i < TL_NIST; i++) tl_ist[t][i] = 64'd0;
            for (int i = 0; i < TL_NOP; i++) begin
                tl_opcyc[t][i] = 64'd0; tl_opcnt[t][i] = 64'd0;
            end
            for (int c = 0; c < 4; c++) begin
                tl_wb[t][c] = 64'd0; tl_mvop[t][c] = 64'd0;
            end
            for (int s = 0; s < TL_NSIG; s++) tl_sig[t][s] = 64'd0;
        end
        for (int s = 0; s < TL_NSIG; s++) tl_sigall[s] = 64'd0;
        tl_reset_rec();

        if ($value$plusargs("timeline=%s", tl_path)) begin
            tl_fd = $fopen(tl_path, "w");
            if (tl_fd == 0) begin
                $display("tb_seq_chip: +timeline path was %s", tl_path);
                $fatal(1, "tb_seq_chip: cannot open the timeline CSV for writing");
            end
            tl_en = 1'b1;
            $fwrite(tl_fd, "# SEQ_TIMELINE v1  csv=%s\n", tl_path);
            $fwrite(tl_fd, "# classes:");
            for (int i = 0; i < TL_NCLS; i++)
                $fwrite(tl_fd, " %0d=%s", i, tl_clsname(i));
            $fwrite(tl_fd, "\n");
            $fwrite(tl_fd, "#COLS R,rec,tok,pc,op,flags,tgt,lop,cyc0,ncyc");
            for (int i = 0; i < TL_NCLS; i++)
                $fwrite(tl_fd, ",%s", tl_clsname(i));
            $fwrite(tl_fd, ",wb0,wb1,wb2,wb3,stall,none\n");
            $fwrite(tl_fd, "#COLS S,tok,mask,cycles\n");
            $display("tb_seq_chip: TIMELINE CENSUS ON -> %s", tl_path);
        end
    end

    // ==================================================================
    // the sampler.  Reads only; drives nothing.
    // ==================================================================
    /* verilator lint_off BLKSEQ */
    always @(negedge clk) if (tl_en) begin
        if (rstn && dut.busy_r) begin
            // ---------- the per-cycle active set ----------------------
            for (int c = 0; c < 4; c++) begin
                tl_wbd[c]    = w_nbeats[c] - tl_wbprev[c];
                tl_wbprev[c] = w_nbeats[c];
            end
            tl_sigw[0]  = u_layer.busy_cmp;
            tl_sigw[1]  = u_layer.busy_dma;
            tl_sigw[2]  = dut.mv_busy;
            tl_sigw[3]  = dut.bulk_active;
            tl_sigw[4]  = (tl_wbd[0] != 64'd0);
            tl_sigw[5]  = (tl_wbd[1] != 64'd0);
            tl_sigw[6]  = (tl_wbd[2] != 64'd0);
            tl_sigw[7]  = (tl_wbd[3] != 64'd0);
            tl_sigw[8]  = tl_mvb[0];
            tl_sigw[9]  = tl_mvb[1];
            tl_sigw[10] = tl_mvb[2];
            tl_sigw[11] = tl_mvb[3];
            tl_sigw[12] = sm_rvalid && sm_rready;
            tl_sigw[13] = sm_wvalid && sm_wready;
            tl_sigw[14] = d_rvalid  && d_rready;
            tl_sigw[15] = (u_bfab.wr_outst != '0) || (u_bfab.rd_outst != '0);

            // ---------- record boundary, BEFORE this cycle is charged --
            // `rec_valid` is high exactly on the I_EXEC cycle of a record
            // (rtl/seq_unit.sv:977 sets it, :984 clears it), so its rising
            // edge is "a new record has been latched".
            if (dut.rec_valid && !tl_rvq) begin
                tl_flush_rec();
                // a BACKWARD pc step between consecutive records is the
                // TCNT_SEQ loop's JMP having been taken — counted, but NOT
                // the segment boundary (see the header: it fires twice on
                // this stream while six tokens come out).
                if (tl_nrec != 64'd0 && int'(dut.pc) < tl_pcq)
                    tl_backj = tl_backj + 64'd1;
                // OP_EMB (8'h06, rtl/seq_unit.sv:264-266) opens a token.
                if (dut.r_op == 8'h06) begin
                    tl_tok++;
                    if (tl_tok >= TL_NTOK)
                        $fatal(1, "seq_timeline: more segments than TL_NTOK holders");
                    if (tl_tok + 1 > tl_ntok) tl_ntok = tl_tok + 1;
                end
                tl_pcq   = int'(dut.pc);
                tl_reset_rec();
                rc_open  = 1'b1;
                rc_idx   = tl_nrec;
                rc_tok   = tl_tok;
                rc_pc    = int'(dut.pc);
                rc_op    = int'(dut.r_op);
                rc_flags = int'(dut.r_flags);
                rc_tgt   = int'(dut.r_tgt);
                rc_cyc0  = tl_bcyc;
                tl_nrec  = tl_nrec + 64'd1;
                tl_opcnt[tl_tok][int'(dut.r_op) & (TL_NOP - 1)] += 64'd1;
            end
            tl_rvq = dut.rec_valid;

            // ---------- charge the cycle ------------------------------
            tl_bcyc          = tl_bcyc + 64'd1;
            tl_tcyc[tl_tok]  = tl_tcyc[tl_tok] + 64'd1;
            tl_sig[tl_tok][int'(tl_sigw)] += 64'd1;
            tl_sigall[int'(tl_sigw)]      += 64'd1;
            if (tl_sigw == '0) begin
                tl_none[tl_tok] = tl_none[tl_tok] + 64'd1;
                rc_none = rc_none + 64'd1;
            end else
                tl_union[tl_tok] = tl_union[tl_tok] + 64'd1;
            for (int i = 0; i < TL_NCLS; i++) if (tl_sigw[i]) begin
                tl_cls[tl_tok][i] = tl_cls[tl_tok][i] + 64'd1;
                rc_cls[i]         = rc_cls[i] + 64'd1;
                for (int j = 0; j < TL_NCLS; j++)
                    if (tl_sigw[j]) tl_pair[tl_tok][i][j] += 64'd1;
            end
            for (int c = 0; c < 4; c++) begin
                tl_wb[tl_tok][c] = tl_wb[tl_tok][c] + tl_wbd[c];
                rc_wb[c]         = rc_wb[c] + tl_wbd[c];
            end
            // the issue FSM's own state, and the record type it is on
            tl_ist[tl_tok][int'(dut.ist) & (TL_NIST - 1)] += 64'd1;
            if (rc_open) begin
                rc_ncyc = rc_ncyc + 64'd1;
                tl_opcyc[tl_tok][rc_op & (TL_NOP - 1)] += 64'd1;
                if (u_layer.busy_cmp) rc_lop = int'(u_layer.cmd_op);
            end
            // rtl/seq_unit.sv:933's own fetch-empty stall condition
            if ((dut.ist == 5'd3) && (dut.fq_cnt == 16'd0)) begin
                tl_stall[tl_tok] = tl_stall[tl_tok] + 64'd1;
                rc_stall         = rc_stall + 64'd1;
            end
            if (dut.mv_busy) tl_mvop[tl_tok][int'(dut.mv_op)] += 64'd1;
            if (u_fab.wr_outst != '0) tl_axw[tl_tok] += 64'd1;
            if (u_fab.rd_outst != '0) tl_axr[tl_tok] += 64'd1;
        end else if (tl_busyq) begin
            tl_flush_rec();                    // the launch's last record
            tl_rvq = 1'b0;
        end
        tl_busyq = rstn && dut.busy_r;
    end
    /* verilator lint_on BLKSEQ */

    // ==================================================================
    // the report.  Printed from `final` so it lands whichever way the
    // testbench's own initial block reaches $finish, and so tb_seq_chip's
    // logic needs no edit beyond the `include.
    // ==================================================================
    /* verilator lint_off BLKSEQ */
    final begin
        if (tl_en) begin
            longint tot;
            int     bs;
            longint bv;
            longint seen [TL_NSIG];
            tl_flush_rec();
            $display("SEQ_TIMELINE v1 BEGIN");
            $display("SEQ_TIMELINE meta ntok=%0d bcyc=%0d nrec=%0d nmv=%0d wimgpc=%0d lat=%0d ddrlat=%0d wlat=%0d ncls=%0d",
                     tl_ntok, tl_bcyc, tl_nrec, NMV, WIMGPC, LAT, DDRLAT,
                     WLAT, TL_NCLS);
            $display("SEQ_TIMELINE backjump %0d", tl_backj);
            for (int i = 0; i < TL_NCLS; i++)
                $display("SEQ_TIMELINE clsname %0d %s", i, tl_clsname(i));
            for (int t = 0; t < tl_ntok; t++) begin
                $display("SEQ_TIMELINE tcyc %0d %0d", t, tl_tcyc[t]);
                $display("SEQ_TIMELINE union %0d %0d", t, tl_union[t]);
                $display("SEQ_TIMELINE none %0d %0d", t, tl_none[t]);
                $display("SEQ_TIMELINE stall %0d %0d", t, tl_stall[t]);
                $display("SEQ_TIMELINE axil %0d %0d %0d", t, tl_axw[t],
                         tl_axr[t]);
                for (int i = 0; i < TL_NCLS; i++)
                    $display("SEQ_TIMELINE class %0d %0d %s %0d", t, i,
                             tl_clsname(i), tl_cls[t][i]);
                for (int i = 0; i < TL_NCLS; i++)
                    for (int j = i; j < TL_NCLS; j++)
                        if (tl_pair[t][i][j] != 64'd0)
                            $display("SEQ_TIMELINE pair %0d %0d %0d %0d", t, i,
                                     j, tl_pair[t][i][j]);
                for (int i = 0; i < TL_NIST; i++)
                    if (tl_ist[t][i] != 64'd0)
                        $display("SEQ_TIMELINE ist %0d %0d %0d", t, i,
                                 tl_ist[t][i]);
                for (int i = 0; i < TL_NOP; i++)
                    if (tl_opcnt[t][i] != 64'd0 || tl_opcyc[t][i] != 64'd0)
                        $display("SEQ_TIMELINE opcyc %0d %0d %0d %0d", t, i,
                                 tl_opcnt[t][i], tl_opcyc[t][i]);
                for (int c = 0; c < 4; c++) begin
                    $display("SEQ_TIMELINE wbeat %0d %0d %0d", t, c,
                             tl_wb[t][c]);
                    $display("SEQ_TIMELINE mvop %0d %0d %0d", t, c,
                             tl_mvop[t][c]);
                end
            end
            // the whole-run active-set distribution: every mask, in
            // descending order, into the CSV; the top 40 also into the log
            // so the headline survives without the CSV.
            for (int s = 0; s < TL_NSIG; s++) seen[s] = tl_sigall[s];
            for (int k = 0; k < 40; k++) begin
                bs = -1; bv = 64'd0;
                for (int s = 0; s < TL_NSIG; s++)
                    if (seen[s] > bv) begin bv = seen[s]; bs = s; end
                if (bs < 0) break;
                $display("SEQ_TIMELINE topsig %0d %0d %0d", k, bs, bv);
                seen[bs] = 64'd0;
            end
            tot = 64'd0;
            for (int s = 0; s < TL_NSIG; s++) tot += tl_sigall[s];
            $display("SEQ_TIMELINE sigtotal %0d", tot);
            $display("SEQ_TIMELINE END");
            if (tl_fd != 0) begin
                for (int t = 0; t < tl_ntok; t++)
                    for (int s = 0; s < TL_NSIG; s++)
                        if (tl_sig[t][s] != 64'd0)
                            $fwrite(tl_fd, "S,%0d,%0d,%0d\n", t, s,
                                    tl_sig[t][s]);
                $fwrite(tl_fd, "#END\n");
                $fclose(tl_fd);
                tl_fd = 0;
            end
        end
    end
    /* verilator lint_on BLKSEQ */
