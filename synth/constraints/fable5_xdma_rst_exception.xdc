# fable5_xdma_rst_exception.xdc — extend Xilinx's own reset-synchronizer
# timing exception to the XDMA wrapper level.
#
# IMPLEMENTATION-ONLY (USED_IN_SYNTHESIS false). No RTL is affected.
# FLAT XDC — no foreach (Designutils 20-1307).
#
# =============================================================================
# USER DECISION, 2026-08-24 (interactive three-option prompt).
# =============================================================================
# build_035's floorplanned roll (fp2a) closed every clock and every line of
# custom RTL, leaving WNS -0.004 on SIX endpoints, all of them inside vendor IP.
# The user was offered (a) waive -0.004, (b) extend this exception, or (c) keep
# re-rolling, and chose (b): **this is to be closed as a CONSTRAINT, not a
# waiver.** Full analysis: evidence/qwen2b/rc/TIMING_035.md §11.7, §11.8, §12.
#
# =============================================================================
# WHAT THE SIX ENDPOINTS ARE
# =============================================================================
# Census of the fp2a roll (evidence/qwen2b/rc/t5_13_census_fp2a_winner.log),
# every failing endpoint in the design, all in Vivado's **async_default**
# group — recovery/removal checks, NOT datapath — and all at 0 logic levels:
#
#   -0.004  .../udma_wrapper/dma_top/user_rst_ff_2_reg/CLR
#   -0.001  .../udma_wrapper/dma_top/user_rst_n_2ff_reg[2]/CLR
#   -0.001  .../udma_wrapper/dma_top/user_rst_n_3ff_reg[0]_rep__14/CLR
#   -0.001  .../udma_wrapper/dma_top/user_rst_n_3ff_reg[0]_rep__3/CLR
#   -0.001  .../udma_wrapper/dma_top/user_rst_n_3ff_reg[2]/CLR
#   -0.001  .../udma_wrapper/dma_top/user_rst_n_ff_reg[2]/CLR
#
# All six are driven from bd_i/xdma_0/inst/pcie4_ip_i/inst/user_reset_reg/C —
# the PCIe hard block's user_reset — into the asynchronous CLEAR pins of
# XDMA's own multi-flop user-reset synchronizer (_ff, _2ff, _3ff), i.e. exactly
# the structure whose design purpose is to absorb asynchronous deassertion.
# Both ends are inside vendor IP; no custom logic lies on any of these paths.
#
# =============================================================================
# THE XILINX PRECEDENT THIS EXTENDS  (and why it did not already cover us)
# =============================================================================
# The PCIe core's own constraint file, shipped with this very IP —
#   synth/out_build_035/proj/stage1.gen/sources_1/bd/bd/ip/bd_xdma_0_0/ip_0/
#     source/ip_pcie4_uscale_plus_x1y2.xdc
# — already treats this exact class as false by construction:
#
#   line 166: set_false_path -to [get_pins .../phy_wrapper/rst_psrst_n_r_reg[*]/CLR]
#   line 168: set_false_path -to [get_pins .../phy_rst_i/prst_n_r_reg[*]/CLR]
#   line 187: set_false_path -to [get_pins user_reset_reg/PRE]
#   line 246: create_waiver -type CDC -id CDC-10 -user "pcie4_uscale_plus" \
#             -desc "PCIe user_reset path - safe to waive" ...
#
# Xilinx false-paths the CLR pins of the GT reset synchronizers, false-paths
# the PRE of user_reset_reg itself, and ships a CDC waiver stating the PCIe
# user_reset path is safe. What it does NOT cover is the DOWNSTREAM
# udma_wrapper/dma_top/user_rst_* synchronizer: that XDC is scoped to the PCIe
# sub-IP (ip_0) and stops at the XDMA wrapper boundary — which is precisely
# where our six endpoints live. This file closes that scope gap and nothing
# else.
#
# =============================================================================
# WHY THIS CANNOT SWALLOW A DATAPATH VIOLATION
# =============================================================================
# (Comment-only correction, 2026-08-24 review — no constraint line was touched.
#  This block previously said "four synchronizer families" and credited the
#  cell-name wildcard with more scoping strength than Tcl glob actually gives.)
#
# The exception is scoped three ways, but the three legs are NOT equally
# strong, and it matters which one carries the guarantee:
#
#   1. hierarchy  — only inside */udma_wrapper/dma_top/. STRONG: confines the
#                   whole exception to XDMA vendor IP. Nothing it matches can
#                   be custom RTL.
#   2. cell name  — registers named user_rst_*_reg*. WEAKER THAN IT LOOKS: in
#                   Tcl/Vivado glob, `*` matches `/` as well, so this leg does
#                   not by itself forbid crossing into deeper hierarchy under
#                   dma_top. Treat it as a narrowing convenience, not a proof.
#   3. PIN        — only /CLR, the asynchronous clear input. STRONG, and this
#                   is the leg that carries the safety argument: datapath
#                   arrives at a flop's /D pin, never at /CLR, so a `-to /CLR`
#                   exception is structurally incapable of exempting a data
#                   path no matter what the middle wildcard spans.
#
# So the guarantee is legs 1 and 3 together — inside vendor IP, and reset pins
# only. The only checks removed are recovery/removal on reset synchronizers.
#
# The claim is also checked EMPIRICALLY rather than argued, because the glob
# caveat above means the pattern's reach should not be taken on trust:
# exception_check.tcl enumerates every matched pin and asserts 0 outside
# xdma_0 and 0 that are not /CLR, and the analysed-endpoint count moves by
# exactly the number of matched pins and no more (1,203,526 -> 1,203,486 setup;
# 1,200,390 -> 1,200,350 hold; 40 matched). See TIMING_035.md §13.3.
#
# The 40 matched pins span SIX register families, not four:
#   user_rst_ff_2_reg   user_rst_n_ff_reg   user_rst_n_2ff_reg
#   user_rst_n_3ff_reg  user_rst_3ff_0_reg  user_rst_3ff_2_reg
# The last two carry no `_n_` and were missed by the original comment's list;
# they are the same synchronizer structure and are correctly covered.
# Enumerated in t5_18_exception_scope_check.log.
#
# The trailing *_reg* wildcard is required, not laziness: phys_opt replicates
# these flops and appends suffixes (_rep__3, _rep__14 above), so an exact-name
# list would silently stop matching after any re-placement — the classic way an
# exception looks applied and is not.
#
# NB scope check: only /CLR is constrained, because all six observed endpoints
# use /CLR. If a future re-place ever implements this same synchronizer family
# with /PRE instead, these pins would fall OUTSIDE this exception and reappear
# as failing endpoints — which is the safe direction to fail, and the roll's
# own census would catch it.
# =============================================================================

set_false_path -to [get_pins -quiet -hierarchical -filter {NAME =~ */udma_wrapper/dma_top/user_rst_*_reg*/CLR}]
