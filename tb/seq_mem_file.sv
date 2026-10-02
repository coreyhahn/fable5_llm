// seq_mem_file — simulation-only AXI4 read-only memory model whose backing
// store is a set of BINARY FILES mapped at absolute DDR byte addresses.
//
// tb/seq_ddr_model.sv keeps its whole image in a `logic [127:0] mem [N]`
// array loaded with $readmemh, which is right for the small unit-TB streams.
// The FULL-CHIP testbench (tb/tb_seq_chip.sv) needs the real artifacts:
// ~300 MB of packed weight images for token24 and ~950 MB for model_v2, plus
// a 16 MB / 508 MB embedding table.  Turning those into hex text and holding
// them in simulator memory is neither necessary nor affordable, so this model
// $fseek/$fread's ONE beat at a time straight out of the committed binaries.
//
// Regions are declared as PARAMETERS: each slot names a +plusarg holding a
// path PREFIX, a filename SUFFIX and the DDR base the file is mapped at, and
// the module opens them itself in an initial block:
//     seq_mem_file #(.A0("base"), .S0(".wimg.bin"), .B0(64'h1000_0000)) ...
// (parameters rather than a hierarchical add_region() call, because a
// hierarchical task call into a generate-block instance is not portable.)
// Reads outside every region return zeros and are COUNTED on n_miss, so an
// unmapped fetch shows up as a number rather than as silent garbage.
//
// DATA_W is a parameter so the SAME model serves both AXI ports the chip has:
//   128-bit  seq_unit.m_axi    (records + LDC blob + embedding rows)
//   512-bit  matvec_chan.m_axi (packed W4 weight rows, in the ui_clk domain)
//
// Timing model is seq_ddr_model's: a depth-QD AR queue, one LAT countdown per
// burst so outstanding bursts genuinely overlap, in-order data return, one
// beat per cycle while RREADY.  The file read for beat N+1 is issued in the
// same cycle beat N is consumed, so a burst streams with no bubble; a new
// burst costs one bubble cycle while its first beat is fetched.
//
// Protocol assumptions are $fatal-checked: INCR only, ARSIZE must match
// DATA_W, no burst may cross a 4 KB boundary.
//
// S3 (SEQ_ISA v2.1) ADDS A WRITE PATH, over ONE window.  The file-backed
// weight and embedding images stay READ-ONLY; when `WR` is set the module
// also carries an AXI4 write channel over the DDR STATE REGION
// [win_base, win_base + win_len), whose initial contents come from the file
// named by the `AS`/`SS` plusarg pair (`<prefix>.state.bin`, written by
// ref/gen_layer_script's dump_state) and whose WRITTEN beats live in an
// associative array on top of it -- a copy-on-write overlay, so the model
// costs what the run actually stores, not the 155 MiB the region spans.
// Reads inside the window come from the overlay when it holds the beat and
// from the file otherwise; reads and writes OUTSIDE it $fatal, because a
// state transfer that leaves its region is the failure this model exists to
// catch (spec 8.3).  `win_base`/`win_len` are PORTS, not parameters: the
// region's address belongs to the artifact, and the testbench reads it from
// the `.chip` golden or from the script's own S record.
//
// `win_fnv(addr, len)` is the golden's transport: FNV-1a 64 over the window
// bytes, computed here exactly as tb/scripts/gen_seq_chip_vectors.py
// computes it in Python.  The hash is the transport; byte equality is the
// check.

`timescale 1ns/1ps
`default_nettype none

module seq_mem_file #(
    parameter int ADDR_W = 34,
    parameter int DATA_W = 128,
    parameter int LAT    = 32,
    parameter int NREG   = 4,
    parameter int QD     = 4,
    // region i: $value$plusargs("<Ai>=%s") + <Si>, mapped at <Bi>;
    // <Oi> = 1 makes a missing file a warning instead of a fatal.
    parameter string  A0 = "", parameter string S0 = "",
    parameter longint B0 = 0,  parameter bit    O0 = 1'b0,
    parameter string  A1 = "", parameter string S1 = "",
    parameter longint B1 = 0,  parameter bit    O1 = 1'b0,
    parameter string  A2 = "", parameter string S2 = "",
    parameter longint B2 = 0,  parameter bit    O2 = 1'b0,
    parameter string  A3 = "", parameter string S3 = "",
    parameter longint B3 = 0,  parameter bit    O3 = 1'b0,
    // fallback plusarg used when <Ai> is not on the command line
    parameter string  AFB = "seq",
    // S3: the writable state window.  WR=0 ties the write channel idle and
    // leaves this module exactly what it was.
    parameter bit     WR = 1'b0,
    parameter string  AS = "base", parameter string SS = ".state.bin"
) (
    input  wire                aclk,
    input  wire                aresetn,

    input  wire [ADDR_W-1:0]   araddr,
    input  wire [7:0]          arlen,
    input  wire [2:0]          arsize,
    input  wire [1:0]          arburst,
    input  wire                arvalid,
    output logic               arready,

    output logic [DATA_W-1:0]  rdata,
    output logic [1:0]         rresp,
    output logic               rlast,
    output logic               rvalid,
    input  wire                rready,

    // ---- S3: the AXI4 write channel over the state window (WR=1) ----
    input  wire [ADDR_W-1:0]   win_base,
    input  wire [ADDR_W-1:0]   win_len,

    input  wire [ADDR_W-1:0]   awaddr,
    input  wire [7:0]          awlen,
    input  wire                awvalid,
    output logic               awready,

    input  wire [DATA_W-1:0]   wdata,
    input  wire [DATA_W/8-1:0] wstrb,
    input  wire                wlast,
    input  wire                wvalid,
    output logic               wready,

    output logic [1:0]         bresp,
    output logic               bvalid,
    input  wire                bready,

    output logic [63:0]        n_beats,
    output logic [63:0]        n_miss,     // beats served from NO region
    output logic [63:0]        n_wbeats    // write beats accepted
);

    localparam int BYTES = DATA_W / 8;
    localparam int LSB   = $clog2(BYTES);           // 4 (128b) or 6 (512b)
    localparam int QW    = (QD > 1) ? $clog2(QD) : 1;
    localparam int QCW   = QW + 1;

    // ------------------------------------------------------------------
    // file-backed regions
    // ------------------------------------------------------------------
    int           f_fd   [NREG];
    longint       f_base [NREG];
    longint       f_size [NREG];
    // n_reg MUST be a declaration initializer, not an `initial` block: the
    // testbench registers its regions from its own time-0 initial and the
    // ordering between two initial blocks is indeterminate.
    int           n_reg = 0;
    byte unsigned bb     [BYTES];

    // `opt`: a missing file is not an error (scripts with no decode step
    // have no embedding table).
    task automatic add_region_opt(input string path, input longint base,
                                  input bit opt);
        int fd, sz, r;
        begin
            fd = $fopen(path, "rb");
            if (fd == 0) begin
                if (opt) begin
                    $display("  mem region -: (absent) %s", path);
                    return;
                end
                $fatal(1, "seq_mem_file: cannot open '%s'", path);
            end
            r  = $fseek(fd, 0, 2);
            sz = $ftell(fd);
            if (r != 0) $fatal(1, "seq_mem_file: seek failed on '%s'", path);
            if (n_reg >= NREG)
                $fatal(1, "seq_mem_file: more than %0d regions", NREG);
            f_fd[n_reg]   = fd;
            f_base[n_reg] = base;
            f_size[n_reg] = longint'(sz);
            $display("  mem region %0d: %0d B @ %012h   %s",
                     n_reg, sz, base, path);
            n_reg = n_reg + 1;
        end
    endtask

    task automatic add_region(input string path, input longint base);
        add_region_opt(path, base, 1'b0);
    endtask

    task automatic add_param_region(input string arg, input string sfx,
                                    input longint base, input bit opt);
        string pre;
        begin
            if (arg == "") return;
            if (!$value$plusargs({arg, "=%s"}, pre))
                if (!$value$plusargs({AFB, "=%s"}, pre))
                    $fatal(1, "seq_mem_file: neither +%s= nor +%s= given",
                           arg, AFB);
            add_region_opt({pre, sfx}, base, opt);
        end
    endtask

    // ------------------------------------------------------------------
    // S3: the writable state window (WR=1 only)
    // ------------------------------------------------------------------
    int                 w_fd = 0;            // <prefix>.state.bin
    longint             w_fsz = 0;
    logic [DATA_W-1:0]  wram [longint];      // copy-on-write overlay, by beat
    byte unsigned       wb [BYTES];

    initial begin
        string pre;
        add_param_region(A0, S0, B0, O0);
        add_param_region(A1, S1, B1, O1);
        add_param_region(A2, S2, B2, O2);
        add_param_region(A3, S3, B3, O3);
        // The image is OPTIONAL: a testbench that issues no SLD/SST (the
        // directed +envtest mode) leaves the window closed, and `win_len`
        // stays 0 so every access still $fatals if one ever arrives.
        if (WR && $value$plusargs({AS, "=%s"}, pre)) begin
            w_fd = $fopen({pre, SS}, "rb");
            if (w_fd == 0)
                $fatal(1, "seq_mem_file: cannot open the state image '%s'",
                       {pre, SS});
            void'($fseek(w_fd, 0, 2));
            w_fsz = longint'($ftell(w_fd));
            $display("  state window: %0d B image   %s", w_fsz, {pre, SS});
        end else if (WR) begin
            $display("  state window: no +%s= — the window stays closed",
                     AS);
        end
    end

    function automatic bit in_win(input longint a);
        in_win = WR && (win_len != '0)
                 && (a >= longint'(win_base))
                 && (a < longint'(win_base) + longint'(win_len));
    endfunction

    // the window beat at `a`: the overlay if it holds it, else the image
    // file, else zeros (a region the image does not reach is zero).
    function automatic logic [DATA_W-1:0] win_rd(input longint a);
        longint idx, off;
        int r;
        idx = a >> LSB;
        if (wram.exists(idx)) return wram[idx];
        win_rd = '0;
        off = a - longint'(win_base);
        if ((w_fd != 0) && (off >= 0) && (off < w_fsz)) begin
            r = $fseek(w_fd, int'(off), 0);
            r = $fread(wb, w_fd);
            for (int k = 0; k < BYTES; k++)
                win_rd[8 * k +: 8] = (k < r) ? wb[k] : 8'h00;
        end
    endfunction

    function automatic byte unsigned win_byte(input longint a);
        logic [DATA_W-1:0] beat;
        beat = win_rd(a & ~longint'(BYTES - 1));
        win_byte = beat[8 * int'(a & longint'(BYTES - 1)) +: 8];
    endfunction

    // FNV-1a 64 over [a, a+n) of the window.  The SAME arithmetic
    // tb/scripts/gen_seq_chip_vectors.py runs in Python; the hash is the
    // transport, byte equality is the check (spec 8.3).
    function automatic logic [63:0] win_fnv(input longint a, input longint n);
        logic [DATA_W-1:0] beat;
        longint i;
        win_fnv = 64'hcbf2_9ce4_8422_2325;
        beat = '0;
        for (i = 0; i < n; i++) begin
            if (((a + i) & longint'(BYTES - 1)) == 0 || i == 0)
                beat = win_rd((a + i) & ~longint'(BYTES - 1));
            win_fnv = win_fnv ^ 64'(beat[8 * int'((a + i)
                                                  & longint'(BYTES - 1)) +: 8]);
            win_fnv = win_fnv * 64'h0000_0100_0000_01b3;
        end
    endfunction

    function automatic bit mapped(input longint a);
        // S3: the writable window counts as mapped -- it is served from the
        // overlay or from the state image, never from "no region", and
        // otherwise every state read would land on `n_miss`.
        if (in_win(a)) return 1'b1;
        mapped = 1'b0;
        for (int i = 0; i < NREG; i++)
            if ((i < n_reg) && (a >= f_base[i]) && (a < f_base[i] + f_size[i]))
                mapped = 1'b1;
    endfunction

    function automatic logic [DATA_W-1:0] mem_rd(input longint a);
        int r;
        mem_rd = '0;
        if (in_win(a)) return win_rd(a);
        for (int i = 0; i < NREG; i++) begin
            if ((i < n_reg) && (a >= f_base[i])
                && (a < f_base[i] + f_size[i])) begin
                r = $fseek(f_fd[i], int'(a - f_base[i]), 0);
                r = $fread(bb, f_fd[i]);
                for (int k = 0; k < BYTES; k++)
                    mem_rd[8 * k +: 8] = (k < r) ? bb[k] : 8'h00;
                return mem_rd;
            end
        end
    endfunction

    // ------------------------------------------------------------------
    // AR queue (depth QD), returned strictly in order
    // ------------------------------------------------------------------
    longint        q_addr [QD];
    logic [7:0]    q_len  [QD];
    logic [31:0]   q_dn   [QD];
    logic [QW-1:0] q_wp, q_rp;
    logic [QCW-1:0] q_cnt;

    logic q_push, q_pop, head_ready, pf_valid;
    logic [7:0] cur_beat;
    logic [DATA_W-1:0] pf_data;

    assign arready = aresetn && (q_cnt != QCW'(QD));
    assign q_push  = arvalid && arready;

    assign head_ready = (q_cnt != '0) && (q_dn[q_rp] == '0);
    assign rvalid = head_ready && pf_valid;
    assign rlast  = rvalid && (cur_beat == q_len[q_rp]);
    assign rresp  = 2'b00;
    assign rdata  = pf_data;
    assign q_pop  = rvalid && rready && rlast;

    // 4 KB boundary check
    logic [8:0] last_beat_in_page;
    assign last_beat_in_page = {1'b0, araddr[11:LSB]} + {1'b0, arlen};

    /* verilator lint_off BLKSEQ */
    longint nxt_addr;

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            q_wp <= '0; q_rp <= '0; q_cnt <= '0;
            cur_beat <= '0; pf_valid <= 1'b0; pf_data <= '0;
            n_beats <= '0; n_miss <= '0;
        end else begin
            for (int i = 0; i < QD; i++)
                if (q_dn[i] != '0) q_dn[i] <= q_dn[i] - 32'd1;

            if (q_push) begin
                if (arburst != 2'b01)
                    $fatal(1, "seq_mem_file: ARBURST=%b, INCR only", arburst);
                if (arsize != 3'(LSB))
                    $fatal(1, "seq_mem_file: ARSIZE=%b, expected %0d on a %0d-bit port",
                           arsize, LSB, DATA_W);
                if (last_beat_in_page > 9'd255)
                    $fatal(1, "seq_mem_file: burst crosses 4 KB (araddr=%h arlen=%0d)",
                           araddr, arlen);
                q_addr[q_wp] <= longint'(araddr);
                q_len[q_wp]  <= arlen;
                q_dn[q_wp]   <= 32'(LAT);
                q_wp         <= q_wp + 1'b1;
            end
            if (q_pop) q_rp <= q_rp + 1'b1;

            case ({q_push, q_pop})
                2'b10:   q_cnt <= q_cnt + QCW'(1);
                2'b01:   q_cnt <= q_cnt - QCW'(1);
                default: ;
            endcase

            // ---- beat prefetch ---------------------------------------
            if (rvalid && rready) begin
                n_beats <= n_beats + 64'd1;
                if (rlast) begin
                    cur_beat <= 8'd0;
                    pf_valid <= 1'b0;          // reload for the next burst
                end else begin
                    nxt_addr = q_addr[q_rp]
                               + (longint'({24'd0, cur_beat}) + 64'd1) * BYTES;
                    if (!mapped(nxt_addr)) n_miss <= n_miss + 64'd1;
                    cur_beat <= cur_beat + 8'd1;
                    pf_data  <= mem_rd(nxt_addr);
                    pf_valid <= 1'b1;
                end
            end else if (!pf_valid && head_ready) begin
                nxt_addr = q_addr[q_rp] + longint'({24'd0, cur_beat}) * BYTES;
                if (!mapped(nxt_addr)) n_miss <= n_miss + 64'd1;
                pf_data  <= mem_rd(nxt_addr);
                pf_valid <= 1'b1;
            end
        end
    end
    /* verilator lint_on BLKSEQ */

    // ==================================================================
    // S3: the AXI4 write channel over the state window
    // ==================================================================
    // AW is queued QD deep and W data follows AW order (a single-ID master
    // must), so one burst is consumed at a time and B is answered per burst.
    // Every address is checked against the window: a store that leaves the
    // region is a $fatal, not a silent write somewhere else.
    longint         aq_addr [QD];
    logic [7:0]     aq_len  [QD];
    logic [QW-1:0]  aq_wp, aq_rp;
    logic [QCW-1:0] aq_cnt;
    logic           w_act;
    longint         w_addr;
    logic [8:0]     w_left;
    logic [QCW-1:0] b_cnt;

    assign awready = WR && aresetn && (aq_cnt != QCW'(QD));
    assign wready  = WR && aresetn && w_act;
    assign bvalid  = WR && aresetn && (b_cnt != '0);
    assign bresp   = 2'b00;

    /* verilator lint_off BLKSEQ */
    longint w_beat_a;
    longint w_beat_i;
    logic [DATA_W-1:0] w_old;

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            aq_wp <= '0; aq_rp <= '0; aq_cnt <= '0;
            w_act <= 1'b0; w_addr <= '0; w_left <= '0; b_cnt <= '0;
            n_wbeats <= '0;
        end else if (WR) begin
            logic push, pop, bpush, bpop;
            push  = awvalid && awready;
            pop   = 1'b0;
            bpush = 1'b0;
            bpop  = bvalid && bready;

            if (push) begin
                if (!in_win(longint'(awaddr))
                    || !in_win(longint'(awaddr)
                               + (longint'({24'd0, awlen}) + 1) * BYTES - 1))
                    $fatal(1, "seq_mem_file: WRITE outside the state window: awaddr=%h awlen=%0d, window [%h, %h)",
                           awaddr, awlen, win_base,
                           longint'(win_base) + longint'(win_len));
                aq_addr[aq_wp] <= longint'(awaddr);
                aq_len[aq_wp]  <= awlen;
                aq_wp          <= aq_wp + 1'b1;
            end

            if (!w_act && (aq_cnt != '0)) begin
                w_act  <= 1'b1;
                w_addr <= aq_addr[aq_rp];
                w_left <= {1'b0, aq_len[aq_rp]} + 9'd1;
                aq_rp  <= aq_rp + 1'b1;
                pop    = 1'b1;
            end else if (w_act && wvalid && wready) begin
                w_beat_a = w_addr & ~longint'(BYTES - 1);
                w_beat_i = w_beat_a >> LSB;
                w_old    = win_rd(w_beat_a);
                for (int k = 0; k < BYTES; k++)
                    if (wstrb[k]) w_old[8 * k +: 8] = wdata[8 * k +: 8];
                wram[w_beat_i] = w_old;
                n_wbeats <= n_wbeats + 64'd1;
                w_addr <= w_addr + BYTES;
                w_left <= w_left - 9'd1;
                if (w_left == 9'd1) begin
                    if (!wlast)
                        $fatal(1, "seq_mem_file: WLAST missing at the last beat of a burst");
                    w_act <= 1'b0;
                    bpush = 1'b1;
                end else if (wlast) begin
                    $fatal(1, "seq_mem_file: WLAST %0d beats early", w_left - 9'd1);
                end
            end

            case ({push, pop})
                2'b10:   aq_cnt <= aq_cnt + QCW'(1);
                2'b01:   aq_cnt <= aq_cnt - QCW'(1);
                default: ;
            endcase
            case ({bpush, bpop})
                2'b10:   b_cnt <= b_cnt + QCW'(1);
                2'b01:   b_cnt <= b_cnt - QCW'(1);
                default: ;
            endcase
        end
    end
    /* verilator lint_on BLKSEQ */

endmodule

`default_nettype wire
