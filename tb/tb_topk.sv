// tb_topk: unit gate for the RUNG-4 S5 TOPK-32 block (docs/RUNG4_SPEC.md)
// on the REAL rtl/layer_chan.sv — no behavioural stub anywhere.
// Agent-D namespace: obj_dir_tb_topk.
//
// WHY THE DUT IS layer_chan AND NOT THE TOPK MODULE ITSELF
//   The block is fed by ONE registered 51-bit bundle exported from vec_alu
//   ({we = t_cp[0] && op_q==10, val = cp_v32, idx = am_g}) and is read only
//   through the layer CSR map.  Both ends of the contract therefore live
//   inside layer_chan, so the only stimulus that exercises the real thing is
//   a real ALU AMAX32 command (opcode 11, aop 10) over the real scratchpad.
//   That also makes this TB independent of the TOPK module's internal port
//   names — it depends on nothing but the frozen S5 CSR map.
//
// CSR map under test (spec S5; layer-local byte addresses, the sequencer
// sees them at 0x5048.. because layer_0 sits at 5<<16):
//   0x48 IDENT   R  0xFAB1704B
//   0x4C STATUS  R  {overflow[7], complete[6], count[5:0]}
//   0x50 PTR     RW
//   0x54 VAL     R  entry[PTR].val   (NO side effect)
//   0x58 IDX     R  entry[PTR].idx   (PTR++ on read)
//
// What it proves (golden = tb/scripts/gen_topk_cases.py, numpy):
//   T1  IDENT
//   T2  every case: count / overflow / the full sorted {val,idx} list
//   T3  entry[0] == (AMAXV, AMAXI) after EVERY command, not just at the end
//       (the TOPK-vs-AMAX equality, on chained chunks)
//   T4  <32 elements (1,2,8,17,31) and the 32/33 boundary
//   T5  +-2^31 rails, including an all-rail tie storm
//   T6  ties: 4/8/40-symbol alphabets, plus the two directed overflow cases
//   T7  >2^18 elements (270,336) — am_g wraps, and the winner's index is
//       the WRAPPED index
//   T8  protocol: one PTR write then a VAL/IDX walk (IDX auto-increment,
//       the S8 host pattern); VAL has no side effect; PTR round-trips
//   T9  RESET IS THE AMAX FRESH FLAG ONLY: unrelated ALU ops, non-ALU
//       commands, CSR traffic and a simulated host launch leave the list
//       bit-identical; only aop 10 with p0[0]=1 clears it
//   T10 `complete` is 0 while an AMAX32 is in flight and 1 once it retires
//
// plusargs
//   +cases=<path>   golden file (default vectopk/s1/topk_cases.txt)
//   +ovf_disp       gate `overflow` against the DISPLACED-TIE reading
//                   instead of the literal one (see the generator header)
//   +sabotage=<k>   corrupt one expected value; every check MUST then fail
//   +quiet          suppress the per-case line
//
// Discipline: every DUT input driven at NEGEDGE, every DUT output sampled
// at NEGEDGE.  Failures are $fatal(1, ...) — $finish sets no exit code.

`timescale 1ns/1ps
module tb_topk;

    logic aclk = 0;
    /* verilator lint_off BLKSEQ */
    always #2 aclk = ~aclk;
    /* verilator lint_on BLKSEQ */
    logic aresetn = 0;

    // ---- AXI-Lite (CSR) ----
    logic [11:0] awaddr;  logic awvalid; wire awready;
    logic [31:0] wdata;   logic [3:0] wstrb; logic wvalid; wire wready;
    wire  [1:0]  bresp;   wire bvalid;   logic bready = 0;
    logic [11:0] araddr;  logic arvalid; wire arready;
    wire  [31:0] rdata;   wire [1:0] rresp; wire rvalid; logic rready = 0;

    // ---- AXI4 burst window: tied off (not under test here) ----
    wire bawready, bwready, bbvalid, barready, brvalid, brlast;
    wire [0:0] bbid, brid;
    wire [1:0] bbresp, brresp;
    wire [31:0] brdata;

    /* verilator lint_off UNUSEDSIGNAL */
    wire [9:0] unused_tb = {bresp, rresp, bbid, brid, bbresp, brresp};
    wire [37:0] unused_b = {brdata, bawready, bwready, bbvalid, barready,
                            brvalid, brlast};
    /* verilator lint_on UNUSEDSIGNAL */

    layer_chan #(
        .RSQRT_ROM("../rtl/roms/rsqrt_rom.hex"),
        .SIGMOID_ROM("../rtl/roms/sigmoid_pair_rom.hex"),
        .SOFTPLUS_ROM("../rtl/roms/softplus_pair_rom.hex"),
        .EXP2_ROM("../rtl/roms/exp2_pair_rom.hex"),
        .RECIP_ROM("../rtl/roms/recip_rom.hex")
    ) dut (
        .aclk, .aresetn,
        .s_axil_awaddr(awaddr), .s_axil_awvalid(awvalid),
        .s_axil_awready(awready),
        .s_axil_wdata(wdata), .s_axil_wstrb(wstrb), .s_axil_wvalid(wvalid),
        .s_axil_wready(wready),
        .s_axil_bresp(bresp), .s_axil_bvalid(bvalid), .s_axil_bready(bready),
        .s_axil_araddr(araddr), .s_axil_arvalid(arvalid),
        .s_axil_arready(arready),
        .s_axil_rdata(rdata), .s_axil_rresp(rresp), .s_axil_rvalid(rvalid),
        .s_axil_rready(rready),
        .s_axib_awid(1'b0), .s_axib_awaddr(18'd0), .s_axib_awlen(8'd0),
        .s_axib_awsize(3'd2), .s_axib_awburst(2'b01),
        .s_axib_awvalid(1'b0), .s_axib_awready(bawready),
        .s_axib_wdata(32'd0), .s_axib_wstrb(4'd0), .s_axib_wlast(1'b0),
        .s_axib_wvalid(1'b0), .s_axib_wready(bwready),
        .s_axib_bid(bbid), .s_axib_bresp(bbresp), .s_axib_bvalid(bbvalid),
        .s_axib_bready(1'b1),
        .s_axib_arid(1'b0), .s_axib_araddr(18'd0), .s_axib_arlen(8'd0),
        .s_axib_arsize(3'd2), .s_axib_arburst(2'b01),
        .s_axib_arvalid(1'b0), .s_axib_arready(barready),
        .s_axib_rid(brid), .s_axib_rdata(brdata), .s_axib_rresp(brresp),
        .s_axib_rlast(brlast), .s_axib_rvalid(brvalid),
        .s_axib_rready(1'b1)
    );

    // ==================================================================
    // CSR map
    // ==================================================================
    localparam logic [11:0] A_CMD  = 12'h000, A_STAT = 12'h004,
                            A_ARG0 = 12'h008, A_ARG1 = 12'h00C,
                            A_ARG2 = 12'h010, A_SPTR = 12'h014,
                            A_SWIN = 12'h018, A_TCNT = 12'h020,
                            A_IDNT = 12'h024, A_AMXI = 12'h028,
                            A_AMXV = 12'h02C, A_LAYR = 12'h030,
                            A_XRFI = 12'h038, A_XRFD = 12'h03C;
    // ---- S5 TOPK block ----
    localparam logic [11:0] A_TKID = 12'h048, A_TKST = 12'h04C,
                            A_TKPT = 12'h050, A_TKVL = 12'h054,
                            A_TKIX = 12'h058;
    localparam logic [31:0] TK_IDENT = 32'hFAB1704B;

    localparam int NENT   = 32;       // TOPK depth
    localparam int MAXW   = 8192;     // scratch words per case
    localparam int MAXCMD = 160;      // AMAX32 commands per case
    localparam int SDST   = 12000;    // ALU dst park region (op 10 writes none)

    int errors = 0;
    int sabotage = 0;
    bit quiet = 0;
    bit ovf_disp_mode = 0;

    task automatic chk(input bit cond, input string msg);
        if (!cond) begin
            errors++;
            if (errors < 40) $display("[%0t] FAIL: %s", $time, msg);
        end
    endtask

    // ==================================================================
    // AXI-Lite master (negedge discipline)
    // ==================================================================
    task automatic wr32(input logic [11:0] addr, input logic [31:0] data);
        @(negedge aclk);
        awaddr = addr; awvalid = 1; wdata = data; wstrb = 4'hF; wvalid = 1;
        while (!(awready && wready)) @(negedge aclk);
        @(negedge aclk);
        awvalid = 0; wvalid = 0;
        while (!bvalid) @(negedge aclk);
        bready = 1;
        @(negedge aclk);
        bready = 0;
    endtask

    task automatic rd32(input logic [11:0] addr, output logic [31:0] data);
        @(negedge aclk);
        araddr = addr; arvalid = 1;
        while (!arready) @(negedge aclk);
        @(negedge aclk);
        arvalid = 0;
        while (!rvalid) @(negedge aclk);
        data = rdata;
        rready = 1;
        @(negedge aclk);
        rready = 0;
    endtask

    /* verilator lint_off UNUSEDSIGNAL */
    logic [31:0] cv, cs;
    /* verilator lint_on UNUSEDSIGNAL */

    // ==================================================================
    // command issue.  `complete` is sampled WHILE the command runs (T10):
    // the TOPK pipe is fed from a registered bundle, so it can never be
    // drained in the same cycle the ALU is producing elements.
    // ==================================================================
    int n_incomplete = 0;      // times complete==0 was observed mid-command
    int n_long_cmd   = 0;      // commands long enough to observe it

    task automatic cmd_go(input logic [31:0] a0, input logic [31:0] a1,
                          input logic [31:0] a2, input bit watch_complete);
        int guard;
        bit saw0;
        wr32(A_ARG0, a0);
        wr32(A_ARG1, a1);
        wr32(A_ARG2, a2);
        wr32(A_CMD,  32'd11);          // OP_ALU
        guard = 0; saw0 = 0;
        forever begin
            rd32(A_STAT, cs);
            if (watch_complete && cs[0]) begin       // busy
                rd32(A_TKST, cv);
                if (!cv[6]) saw0 = 1;
            end
            if (!cs[0]) break;
            guard++;
            if (guard > 200000) begin
                chk(0, "command never retired");
                break;
            end
        end
        if (watch_complete) begin
            n_long_cmd++;
            if (saw0) n_incomplete++;
        end
        // once idle, the TOPK pipe must be drained
        rd32(A_TKST, cv);
        chk(cv[6] == 1'b1, "STATUS.complete==0 after the command retired");
    endtask

    // AMAX32 (aop 10) over `len` {lo,hi} pairs at scratch word `srca`
    task automatic amax32(input int srca, input int len, input bit fresh,
                          input bit watch_complete);
        cmd_go(32'd10 | (32'(len) << 4), 32'(srca),
               (fresh ? 32'd1 : 32'd0) | (32'(SDST) << 16), watch_complete);
    endtask

    task automatic cmd_other(input logic [31:0] op);   // non-ALU opcode
        int guard;
        wr32(A_CMD, op);
        guard = 0;
        forever begin
            rd32(A_STAT, cs);
            if (!cs[0]) break;
            guard++;
            if (guard > 200000) begin chk(0, "non-ALU cmd hung"); break; end
        end
    endtask

    // ==================================================================
    // scratch load
    // ==================================================================
    logic [15:0] words [MAXW];
    task automatic load_words(input int n);
        wr32(A_SPTR, 32'd0);
        for (int i = 0; i < n; i++) wr32(A_SWIN, {16'b0, words[i]});
    endtask

    // ==================================================================
    // TOPK read helpers
    // ==================================================================
    logic [31:0] got_val [NENT];
    logic [31:0] got_idx [NENT];

    // ONE PTR write then a VAL/IDX walk — the S8 host pattern.
    task automatic topk_drain(input int n);
        wr32(A_TKPT, 32'd0);
        for (int i = 0; i < n; i++) begin
            rd32(A_TKVL, cv); got_val[i] = cv;
            rd32(A_TKIX, cv); got_idx[i] = cv;
        end
        // TK_PTR is 5 bits (it indexes 32 entries), so a full 32-entry walk
        // lands back on 0.
        rd32(A_TKPT, cv);
        chk(cv[4:0] == 5'(n % NENT),
            $sformatf("PTR after a %0d-entry walk: got %0d want %0d",
                      n, cv[4:0], n % NENT));
    endtask

    task automatic topk_entry0(output logic [31:0] v, output logic [31:0] ix);
        wr32(A_TKPT, 32'd0);
        rd32(A_TKVL, v);
        rd32(A_TKIX, ix);
    endtask

    // ==================================================================
    // golden case file (tb/scripts/gen_topk_cases.py)
    // ==================================================================
    string cases_path;
    int    fd;
    logic [31:0] exp_val [NENT];
    logic [31:0] exp_idx [NENT];
    int   c_sa [MAXCMD], c_ln [MAXCMD], c_fr [MAXCMD];

    int n_case = 0, n_elem_tot = 0, n_amax_eq = 0;

    task automatic run_case();
        string name;
        int nw, ncmd, nent, cnt, ovfl, ovfd, aidx, nelem, r, want_ovf;
        logic [31:0] aval, e0v;
        /* verilator lint_off UNUSEDSIGNAL */
        logic [31:0] e0i;
        /* verilator lint_on UNUSEDSIGNAL */
        r = $fscanf(fd, " %s %d %d %d %d %d %d %d %h %d",
                    name, nw, ncmd, nent, cnt, ovfl, ovfd, aidx, aval, nelem);
        if (r != 10) $fatal(1, "bad case header (fscanf=%0d)", r);
        if (nw > MAXW)     $fatal(1, "case %0s: %0d words > MAXW", name, nw);
        if (ncmd > MAXCMD) $fatal(1, "case %0s: %0d cmds > MAXCMD", name, ncmd);
        for (int i = 0; i < nw; i++) begin
            r = $fscanf(fd, " %h", words[i]);
            if (r != 1) $fatal(1, "case %0s: short word list", name);
        end
        for (int i = 0; i < ncmd; i++) begin
            r = $fscanf(fd, " %d %d %d", c_sa[i], c_ln[i], c_fr[i]);
            if (r != 3) $fatal(1, "case %0s: short cmd list", name);
        end
        for (int i = 0; i < nent; i++) begin
            r = $fscanf(fd, " %h %d", exp_val[i], exp_idx[i]);
            if (r != 2) $fatal(1, "case %0s: short entry list", name);
        end

        // ---- sabotage: every corruption below MUST make the case fail ----
        case (sabotage)
            1: exp_val[0] = exp_val[0] ^ 32'h1;
            2: exp_idx[nent - 1] = exp_idx[nent - 1] ^ 32'h1;
            3: cnt = (cnt == 0) ? 1 : cnt - 1;
            4: aval = aval ^ 32'h8000_0000;
            5: begin ovfl = 1 - ovfl; ovfd = 1 - ovfd; end
            default: ;
        endcase

        load_words(nw);
        for (int i = 0; i < ncmd; i++) begin
            amax32(c_sa[i], c_ln[i], c_fr[i] != 0, i < 4);
            // T3: after EVERY command the TOPK head must be the AMAX winner
            topk_entry0(e0v, e0i);
            rd32(A_AMXI, cv);
            chk(e0i[17:0] == cv[17:0],
                $sformatf("%0s cmd %0d: TOPK idx %0d != AMAXI %0d",
                          name, i, e0i[17:0], cv[17:0]));
            rd32(A_AMXV, cs);
            chk(e0v == cs,
                $sformatf("%0s cmd %0d: TOPK val %h != AMAXV %h",
                          name, i, e0v, cs));
            n_amax_eq++;
        end

        // ---- T2: STATUS ----
        rd32(A_TKST, cv);
        chk(int'(cv[5:0]) == cnt,
            $sformatf("%0s: count %0d != %0d", name, cv[5:0], cnt));
        chk(cv[6] == 1'b1, $sformatf("%0s: complete==0 when idle", name));
        want_ovf = ovf_disp_mode ? ovfd : ovfl;
        chk(int'(cv[7]) == want_ovf,
            $sformatf("%0s: overflow %0d != %0d (ovf_lit=%0d ovf_disp=%0d)",
                      name, cv[7], want_ovf, ovfl, ovfd));

        // ---- T2: the whole sorted list ----
        topk_drain(cnt);
        for (int i = 0; i < cnt; i++) begin
            chk(got_val[i] == exp_val[i],
                $sformatf("%0s entry %0d val: got %h want %h",
                          name, i, got_val[i], exp_val[i]));
            chk(got_idx[i][17:0] == exp_idx[i][17:0],
                $sformatf("%0s entry %0d idx: got %0d want %0d",
                          name, i, got_idx[i][17:0], exp_idx[i][17:0]));
        end
        // sortedness is an independent property of the golden compare
        for (int i = 1; i < cnt; i++)
            chk($signed(got_val[i - 1]) >= $signed(got_val[i]),
                $sformatf("%0s: entry %0d not sorted (%h then %h)",
                          name, i, got_val[i - 1], got_val[i]));

        // ---- T2: AMAXI / AMAXV vs numpy ----
        rd32(A_AMXI, cv);
        chk(int'(cv[17:0]) == aidx,
            $sformatf("%0s: AMAXI %0d != %0d", name, cv[17:0], aidx));
        rd32(A_AMXV, cv);
        chk(cv == aval, $sformatf("%0s: AMAXV %h != %h", name, cv, aval));

        // ---- T8: PTR protocol, random access ----
        if (cnt > 0)
            for (int t = 0; t < 4; t++) begin
                int p;
                p = (t * 7 + 3) % cnt;
                wr32(A_TKPT, 32'(p));
                rd32(A_TKPT, cv);
                chk(int'(cv[4:0]) == p,
                    $sformatf("%0s: PTR write %0d read back %0d",
                              name, p, cv[4:0]));
                rd32(A_TKVL, cv);
                chk(cv == exp_val[p],
                    $sformatf("%0s: VAL@%0d %h != %h", name, p, cv, exp_val[p]));
                rd32(A_TKVL, cs);
                chk(cs == cv, $sformatf("%0s: VAL@%0d not idempotent", name, p));
                rd32(A_TKPT, cv);
                chk(int'(cv[4:0]) == p,
                    $sformatf("%0s: VAL read moved PTR %0d -> %0d",
                              name, p, cv[4:0]));
                rd32(A_TKIX, cv);
                chk(cv[17:0] == exp_idx[p][17:0],
                    $sformatf("%0s: IDX@%0d %0d != %0d",
                              name, p, cv[17:0], exp_idx[p][17:0]));
                rd32(A_TKPT, cv);
                chk(int'(cv[4:0]) == ((p + 1) % NENT),
                    $sformatf("%0s: IDX read did not ++PTR (%0d -> %0d)",
                              name, p, cv[4:0]));
            end

        n_case++;
        n_elem_tot += nelem;
        if (!quiet)
            $display("  case %-16s nelem=%7d cmds=%3d count=%2d ovf=%0d/%0d OK",
                     name, nelem, ncmd, cnt, ovfl, ovfd);
    endtask

    // ==================================================================
    // T9: reset is the AMAX fresh flag ONLY
    // ==================================================================
    logic [31:0] snap_val [NENT];
    logic [31:0] snap_idx [NENT];
    int snap_cnt;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [31:0] snap_st;
    /* verilator lint_on UNUSEDSIGNAL */

    task automatic snapshot();
        rd32(A_TKST, snap_st);
        snap_cnt = int'(snap_st[5:0]);
        topk_drain(snap_cnt);
        for (int i = 0; i < snap_cnt; i++) begin
            snap_val[i] = got_val[i];
            snap_idx[i] = got_idx[i];
        end
    endtask

    task automatic expect_unchanged(input string what);
        rd32(A_TKST, cv);
        chk(cv[5:0] == snap_st[5:0],
            $sformatf("%0s changed count: %0d -> %0d",
                      what, snap_st[5:0], cv[5:0]));
        chk(cv[7] == snap_st[7],
            $sformatf("%0s changed overflow: %0d -> %0d",
                      what, snap_st[7], cv[7]));
        topk_drain(snap_cnt);
        for (int i = 0; i < snap_cnt; i++) begin
            chk(got_val[i] == snap_val[i],
                $sformatf("%0s changed entry %0d val %h -> %h",
                          what, i, snap_val[i], got_val[i]));
            chk(got_idx[i] == snap_idx[i],
                $sformatf("%0s changed entry %0d idx %0d -> %0d",
                          what, i, snap_idx[i][17:0], got_idx[i][17:0]));
        end
    endtask

    task automatic t9_reset_scope();
        // build a list from 64 elements of the last case's scratch image
        amax32(0, 64, 1'b1, 1'b0);
        snapshot();
        chk(snap_cnt == NENT, "T9 setup: expected a full list");

        // (a) a DIFFERENT ALU op — ADD (4), 64 elements, dst well clear
        cmd_go(32'd4 | (32'd64 << 4), 32'd0 | (32'd64 << 16),
               32'd0 | (32'(SDST) << 16), 1'b0);
        expect_unchanged("ALU op 4 (ADD)");

        // (b) ALU DYNQ8 (op 0) — the other scan op, and it writes the XRF
        cmd_go(32'd0 | (32'd64 << 4), 32'd0,
               32'd0 | (32'(SDST) << 16), 1'b0);
        expect_unchanged("ALU op 0 (DYNQ8)");

        // (c) ALU DYNQ16 (op 12) — the other running-scan op
        cmd_go(32'd12 | (32'd64 << 4), 32'd0,
               32'd0 | (32'(SDST) << 16), 1'b0);
        expect_unchanged("ALU op 12 (DYNQ16)");

        // (d) a NON-ALU command: DNZ (opcode 12) zeroes DeltaNet state
        cmd_other(32'd12);
        expect_unchanged("non-ALU command DNZ");

        // (e) an ILLEGAL opcode (err_op path) — must not disturb it either
        cmd_other(32'd15);
        wr32(A_CMD, 32'd0);            // clear err_op via a benign CMD
        expect_unchanged("illegal opcode");

        // (f) a SIMULATED HOST LAUNCH: everything a fresh sequencer launch
        //     writes to layer_chan except aresetn — banks, XRF, args,
        //     counters, scratch — plus a full CSR sweep.
        wr32(A_LAYR, 32'h0000_0305);
        wr32(A_TCNT, 32'h0000_0000);
        wr32(A_XRFI, 32'd3);
        wr32(A_XRFD, 32'd12345);
        wr32(A_ARG0, 32'hDEAD_BEEF);
        wr32(A_ARG1, 32'hCAFE_F00D);
        wr32(A_ARG2, 32'h1234_5678);
        wr32(A_SPTR, 32'd200);
        wr32(A_SWIN, 32'h0000_ABCD);
        rd32(A_IDNT, cv);
        rd32(A_STAT, cv);
        rd32(A_LAYR, cv);
        wr32(A_LAYR, 32'd0);
        expect_unchanged("simulated host launch (banks/XRF/args/scratch)");

        // (g) AMAX32 with fresh=0 EXTENDS: count stays 32, overflow can only
        //     become stickier, and entry[0] stays the AMAX winner.
        amax32(0, 64, 1'b0, 1'b0);
        rd32(A_TKST, cv);
        chk(cv[5:0] == 6'd32, "fresh=0 rescan changed count off 32");
        begin
            logic [31:0] e0v;
            /* verilator lint_off UNUSEDSIGNAL */
            logic [31:0] e0i;
            /* verilator lint_on UNUSEDSIGNAL */
            topk_entry0(e0v, e0i);
            rd32(A_AMXV, cv);
            chk(e0v == cv, "fresh=0 rescan: entry0 val != AMAXV");
            rd32(A_AMXI, cs);
            chk(e0i[17:0] == cs[17:0], "fresh=0 rescan: entry0 idx != AMAXI");
        end

        // (h) ONLY fresh=1 clears: one element, fresh -> count==1
        amax32(0, 1, 1'b1, 1'b0);
        rd32(A_TKST, cv);
        chk(cv[5:0] == 6'd1,
            $sformatf("fresh=1 did not reset the list (count=%0d)", cv[5:0]));
        chk(cv[7] == 1'b0, "fresh=1 did not clear sticky overflow");
        $display("  T9 reset-scope: 6 non-fresh disturbance classes left the list bit-identical; only aop10 p0[0]=1 cleared it");
    endtask

    // ==================================================================
    initial begin
        int ncase;
        if (!$value$plusargs("cases=%s", cases_path))
            cases_path = "vectopk/s1/topk_cases.txt";
        void'($value$plusargs("sabotage=%d", sabotage));
        quiet = $test$plusargs("quiet");
        ovf_disp_mode = $test$plusargs("ovf_disp");

        awvalid = 0; wvalid = 0; arvalid = 0; wstrb = 4'hF;
        awaddr = 0; araddr = 0; wdata = 0;

        repeat (8) @(negedge aclk);
        aresetn = 1;
        repeat (4) @(negedge aclk);

        // ---- T1 IDENT (both the layer's and the TOPK block's) ----
        rd32(A_IDNT, cv);
        chk(cv == 32'hFAB1E5A0, $sformatf("layer IDENT %h", cv));
        rd32(A_TKID, cv);
        chk(cv == TK_IDENT, $sformatf("TOPK IDENT %h != %h", cv, TK_IDENT));

        // reset state: empty, complete, no overflow
        rd32(A_TKST, cv);
        chk(cv[5:0] == 6'd0, $sformatf("post-reset count %0d != 0", cv[5:0]));
        chk(cv[6] == 1'b1, "post-reset complete != 1");
        chk(cv[7] == 1'b0, "post-reset overflow != 0");

        fd = $fopen(cases_path, "r");
        if (fd == 0) $fatal(1, "cannot open %0s", cases_path);
        if ($fscanf(fd, " %d", ncase) != 1) $fatal(1, "bad case count");
        for (int c = 0; c < ncase; c++) run_case();
        $fclose(fd);

        chk(n_long_cmd > 0, "T10: no command ran long enough to sample");
        chk(n_incomplete > 0,
            "T10: STATUS.complete was NEVER 0 while an AMAX32 was in flight");

        t9_reset_scope();

        if (errors == 0) begin
            $display("TB_TOPK PASS: %0d cases, %0d elements, %0d AMAX-equality checks, complete==0 seen on %0d/%0d watched commands",
                     n_case, n_elem_tot, n_amax_eq, n_incomplete, n_long_cmd);
            $finish;
        end else
            $fatal(1, "TB_TOPK FAIL: %0d errors", errors);
    end

    initial begin
        #4000ms;
        $fatal(1, "TB_TOPK FAIL: global watchdog");
    end

endmodule
