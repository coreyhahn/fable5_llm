// tb_attn_core: attn_core vs layer_fixed attention-core golden vectors
// (T=48), bit-exact on the 256 output accumulators.
`timescale 1ns/1ps
module tb_attn_core;
    logic clk = 0;
    /* verilator lint_off BLKSEQ */
    always #2 clk = ~clk;
    /* verilator lint_on BLKSEQ */
    logic rstn = 0, start = 0, busy, done;
    /* verilator lint_off UNUSEDSIGNAL */
    wire bu = busy;
    /* verilator lint_on UNUSEDSIGNAL */
    logic [9:0] cfg_t = 0;
    logic q_we = 0;
    logic [7:0] q_waddr = 0;
    logic signed [15:0] q_wdata = 0;
    logic [9:0] kv_addr;
    logic [2047:0] kv_data;
    logic signed [7:0] kv_exp;
    logic m_valid, m_ready = 0;
    logic signed [31:0] m_data;
    logic [7:0] m_idx;

    attn_core #(
        .EXP2_ROM("../rtl/roms/exp2_pair_rom.hex"),
        .RECIP_ROM("../rtl/roms/recip_rom.hex")
    ) dut (.clk, .rstn, .start, .busy, .done, .cfg_t,
           .q_we, .q_waddr, .q_wdata,
           .kv_addr, .kv_data, .kv_exp,
           .m_valid, .m_ready, .m_data, .m_idx);

    // KV memory model (2-cycle read latency: URAM + OREG)
    logic [2047:0] kmem [512];
    logic [2047:0] vmem [512];
    logic signed [7:0] kexp [512];
    logic signed [7:0] vexp [512];
    logic [2047:0] kv_p;
    logic signed [7:0] ke_p;
    always_ff @(posedge clk) begin
        kv_p    <= kv_addr[9] ? vmem[kv_addr[8:0]] : kmem[kv_addr[8:0]];
        ke_p    <= kv_addr[9] ? vexp[kv_addr[8:0]] : kexp[kv_addr[8:0]];
        kv_data <= kv_p;
        kv_exp  <= ke_p;
    end

    logic [15:0] qvf [256];
    logic [7:0]  k8f [12288];   // 48*256
    logic [7:0]  kef [48];
    logic [7:0]  v8f [12288];
    logic [7:0]  vef [48];
    logic [31:0] gacc [256];
    int errors = 0, rcvd = 0;

    initial begin
        forever begin
            @(negedge clk);
            m_ready = 1;
            if (m_valid && m_ready) begin
                if (m_data !== signed'(gacc[m_idx])) begin
                    errors++;
                    if (errors < 6)
                        $display("FAIL acc[%0d]: got %0d want %0d",
                                 m_idx, m_data, signed'(gacc[m_idx]));
                end
                rcvd++;
            end
        end
    end

    string vecdir;
    initial begin
        int i;
        if (!$value$plusargs("vecdir=%s", vecdir)) $fatal(1, "need +vecdir=");
        $readmemh({vecdir, "/attn_q.hex"}, qvf);
        $readmemh({vecdir, "/attn_k8.hex"}, k8f);
        $readmemh({vecdir, "/attn_ke.hex"}, kef);
        $readmemh({vecdir, "/attn_v8.hex"}, v8f);
        $readmemh({vecdir, "/attn_ve.hex"}, vef);
        $readmemh({vecdir, "/attn_acc.hex"}, gacc);
        for (i = 0; i < 48; i++) begin
            for (int d = 0; d < 256; d++) begin
                kmem[i][d*8 +: 8] = k8f[i*256 + d];
                vmem[i][d*8 +: 8] = v8f[i*256 + d];
            end
            kexp[i] = signed'(kef[i]);
            vexp[i] = signed'(vef[i]);
        end
        repeat (5) @(negedge clk);
        rstn = 1;
        repeat (2) @(negedge clk);
        for (i = 0; i < 256; i++) begin
            @(negedge clk);
            q_we = 1; q_waddr = 8'(i); q_wdata = signed'(qvf[i]);
        end
        @(negedge clk); q_we = 0;
        cfg_t = 10'd48;
        start = 1; @(negedge clk); start = 0;
        begin
            int guard = 0;
            while (!done) begin
                @(negedge clk);
                guard++;
                if (guard > 100000) begin
                    errors++; $display("FAIL: timeout rcvd=%0d st=%0d", rcvd, dut.st);
                    break;
                end
            end
        end
        repeat (3) @(negedge clk);
        if (rcvd != 256) begin errors++; $display("FAIL rcvd=%0d", rcvd); end
        if (errors == 0) begin
            $display("TB_ATTN_CORE PASS: 256 outputs bit-exact (T=48)");
            $finish;
        end else $fatal(1, "TB_ATTN_CORE FAIL: %0d", errors);
    end
    initial begin #20ms; $fatal(1, "watchdog"); end
endmodule
