# Multicycle exceptions — ONLY for registers whose VALUE is constant for
# the entire window in which any enabled capture can occur. FLAT XDC (no
# foreach — rejected in .xdc, Designutils 20-1307).
#
# HARD-WON RULE (hardware failure 2026-07-26, build_025_rr_mcp2_ETO):
# source-value cadence is NOT a valid MCP argument when the consumer's
# capture is enable-aligned a fixed 1 cycle after launch (vin/vwe_q,
# conv CV_P sampling). The MCP lets the router exceed one period and the
# single enabled capture latches mid-flight data — sim (zero-delay)
# cannot catch this; only hardware does. vdata_q/dn_vdata/conv-BRAM MCPs
# were removed for exactly this reason.
#
# Remaining constraints — value constant across the WHOLE consume phase:
# - u_dn/decay_r, u_dn/beta_r: re-registered copies of CSR-preloaded
#   config; constant from preload to end of DNST command. Any capture
#   >=1 cycle after the last change (which is >>2 cycles before compute)
#   is correct.
# - u_attn/p_t_r, shamt_r, vadd_r: per-t values, but with the P_VW2 state
#   in attn_core (added 2026-07-26 — see the comment there) every aligned
#   consume is >=2 cycles after the replica update and the intermediate
#   free-running captures are dead. These three MCPs are ONLY legal with
#   P_VW2 present.
# -hold 1 keeps the hold check at the launch edge (standard MCP pairing).

set_multicycle_path -setup 2 -from [get_cells -hier -filter {NAME =~ *u_dn/decay_r_reg*}]
set_multicycle_path -hold  1 -from [get_cells -hier -filter {NAME =~ *u_dn/decay_r_reg*}]
set_multicycle_path -setup 2 -from [get_cells -hier -filter {NAME =~ *u_dn/beta_r_reg*}]
set_multicycle_path -hold  1 -from [get_cells -hier -filter {NAME =~ *u_dn/beta_r_reg*}]
set_multicycle_path -setup 2 -from [get_cells -hier -filter {NAME =~ *u_attn/p_t_r_reg*}]
set_multicycle_path -hold  1 -from [get_cells -hier -filter {NAME =~ *u_attn/p_t_r_reg*}]
set_multicycle_path -setup 2 -from [get_cells -hier -filter {NAME =~ *u_attn/shamt_r_reg*}]
set_multicycle_path -hold  1 -from [get_cells -hier -filter {NAME =~ *u_attn/shamt_r_reg*}]
set_multicycle_path -setup 2 -from [get_cells -hier -filter {NAME =~ *u_attn/vadd_r_reg*}]
set_multicycle_path -hold  1 -from [get_cells -hier -filter {NAME =~ *u_attn/vadd_r_reg*}]
