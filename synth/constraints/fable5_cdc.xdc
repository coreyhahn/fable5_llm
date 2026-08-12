# CDC declarations for csr_block.
# calib_in[3:0] are quasi-static DDR4 init_calib_complete bits crossing from
# the four MIG ui_clk domains (300 MHz) into xdma_0_axi_aclk (250 MHz)
# through a 2FF synchronizer (ASYNC_REG=TRUE in rtl/csr_block.sv).
# Declare the crossing so the router does not try to time 4 unrelated
# clock pairs (and does not tear csr placement across SLRs doing so).
set_false_path -to [get_pins -hierarchical -filter {NAME =~ */u_csr/calib_meta_reg[*]/D}]

# ---- matvec_chan CDC (hand-rolled crossings; XPM macros constrain themselves)
# 2FF synchronizer first stages (status ui->aclk, doorbell toggle aclk->ui)
set_false_path -to [get_pins -hierarchical -filter {NAME =~ */cdc_meta_*_reg*/D}]
# Quasi-static cfg (written before doorbell, stable during run): aclk -> ui_clk only.
# The MIG ui clocks are the mmcm_clkout0* generated clocks.
set_false_path -from [get_cells -hierarchical -filter {NAME =~ */csr_static_*_reg*}] \
               -to   [get_clocks -filter {NAME =~ mmcm_clkout0*}]
# Perf counters (frozen at done, read only when done): ui_clk -> aclk
set_false_path -from [get_cells -hierarchical -filter {NAME =~ */perf_cycles_reg* || NAME =~ */perf_beats_reg*}] \
               -to   [get_clocks -filter {NAME =~ *axi_aclk*}]
