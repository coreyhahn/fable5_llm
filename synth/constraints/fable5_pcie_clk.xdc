# PCIe 100 MHz reference clock — THE constraint the community XDC set lacks.
# Without it the XDMA's entire derived clock tree (userclk/axi_aclk 250 MHz)
# is unconstrained and P&R produces randomly-broken PCIe logic
# (root-caused 2026-06-11: evidence/stage1/dma_hang_debug/FINDINGS.md).
create_clock -period 10.000 -name pcie_refclk [get_ports pcie_refclk_clk_p]
