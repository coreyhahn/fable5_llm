// s2_contract_stub.sv — NOT DESIGN RTL.  A fixture, and only a fixture.
//
// It carries the eighteen `// SDMA_BITS:` anchors the plan's S2 localparam
// bullet (docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md:340)
// tells Task S2 to emit, with B15's values, and NOTHING else — no ports, no
// logic, nothing synthesizable.  It exists so S1 can prove that its census's
// RED is STRUCTURAL (rtl/layer_chan.sv genuinely has no OP_SLD) rather than a
// broken parser that would refuse the real thing too:
//
//   SDMA_BITS_RTL=evidence/qwen9b/s1/s2_contract_stub.sv \
//     python3 evidence/qwen9b/s1/sdma_bits.py
//
// must be GREEN on all four views, and every `--perturb rtl*` must be CAUGHT.
// Driver: evidence/qwen9b/s1/rtl_contract_probe.sh.  When S2 lands the real
// anchors in rtl/layer_chan.sv this file stays as the parser's own control.

module s2_contract_stub;                                  // fixture only

    // ---- B15.1 the two layer commands ------------------------------
    localparam logic [3:0] OP_SLD = 4'd13;                // SDMA_BITS: OP_SLD
    localparam logic [3:0] OP_SST = 4'd14;                // SDMA_BITS: OP_SST

    // ---- B15.3 the five CSRs, by WORD offset ------------------------
    localparam logic [9:0] SB_DN_W    = 10'h019;          // SDMA_BITS: CSR_SB_DN
    localparam logic [9:0] SB_KV_W    = 10'h01A;          // SDMA_BITS: CSR_SB_KV
    localparam logic [9:0] SB_CV_W    = 10'h01B;          // SDMA_BITS: CSR_SB_CV
    localparam logic [9:0] SDMA_W     = 10'h01C;          // SDMA_BITS: CSR_SDMA
    localparam logic [9:0] SDMA_CYC_W = 10'h01D;          // SDMA_BITS: CSR_SDMA_CYC

    // ---- B15.4 the layer's error codes ------------------------------
    localparam logic [7:0] E_ENV       = 8'h01;           // SDMA_BITS: ERR_E_ENV
    localparam logic [7:0] E_LAYER     = 8'h02;           // SDMA_BITS: ERR_E_LAYER
    localparam logic [7:0] E_DMA_BASE  = 8'h10;           // SDMA_BITS: ERR_E_DMA_BASE
    localparam logic [7:0] E_DMA_RANGE = 8'h11;           // SDMA_BITS: ERR_E_DMA_RANGE
    localparam logic [7:0] E_DMA_AXI   = 8'h12;           // SDMA_BITS: ERR_E_DMA_AXI
    localparam logic [7:0] E_DMA_COLD  = 8'h13;           // SDMA_BITS: ERR_E_DMA_COLD

    // ---- B15.1 the three address shifts the adder applies ------------
    localparam int SDMA_SHIFT_DN = 20;                    // SDMA_BITS: SHIFT_DN
    localparam int SDMA_SHIFT_KV = 21;                    // SDMA_BITS: SHIFT_KV
    localparam int SDMA_SHIFT_CV = 17;                    // SDMA_BITS: SHIFT_CV

    // ---- B15.1 the ARG0 concat, B15.2 the LAYER word -----------------
    //   arg0 = {kind[12:11], slot[10], layer[9:5], head[4:0]}  // SDMA_BITS: ARG0_FIELDS
    // 10'h00C LAYER decode  // SDMA_BITS: LAYER_FIELDS {cv_slot[13:12], kv_layer[10:8], kv_slot[4:3], dn_slot[1:0]}

endmodule
