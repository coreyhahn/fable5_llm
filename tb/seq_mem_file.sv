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
    parameter string  AFB = "seq"
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

    output logic [63:0]        n_beats,
    output logic [63:0]        n_miss      // beats served from NO region
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

    initial begin
        add_param_region(A0, S0, B0, O0);
        add_param_region(A1, S1, B1, O1);
        add_param_region(A2, S2, B2, O2);
        add_param_region(A3, S3, B3, O3);
    end

    function automatic bit mapped(input longint a);
        mapped = 1'b0;
        for (int i = 0; i < NREG; i++)
            if ((i < n_reg) && (a >= f_base[i]) && (a < f_base[i] + f_size[i]))
                mapped = 1'b1;
    endfunction

    function automatic logic [DATA_W-1:0] mem_rd(input longint a);
        int r;
        mem_rd = '0;
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

endmodule

`default_nettype wire
