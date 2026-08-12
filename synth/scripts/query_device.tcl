# Query VU9P device model facts needed to configure XDMA for BCU-1525.
create_project -in_memory -part xcvu9p-fsgd2104-2L-e
link_design -part xcvu9p-fsgd2104-2L-e
puts "PCIE4_SITES: [get_sites -filter {SITE_TYPE == PCIE40E4}]"
puts "AM11_SITE: [get_sites -of_objects [get_package_pins AM11]]"
puts "AM10_SITE: [get_sites -of_objects [get_package_pins AM10]]"
foreach p {AM11 AM10 BD21 AY37 AW19 E32 H16} {
  puts "PINFO $p: bank=[get_property BANK [get_package_pins $p]] site=[get_sites -of_objects [get_package_pins $p]]"
}
# GTY channel sites and their package pins for likely PCIe quads (banks 224-227)
foreach s [get_sites -filter {SITE_TYPE == GTYE4_CHANNEL}] {
  set pins [get_package_pins -of_objects $s]
  puts "GTY $s pins: $pins"
}
puts "VCU1525_BOARDS: [get_board_parts *vcu1525*]"
puts "U200_BOARDS: [get_board_parts *u200*]"
puts "XDMA_IP: [get_ipdefs -all *xdma*]"
puts "DDR4_IP: [get_ipdefs -all xilinx.com:ip:ddr4:*]"
puts "DONE_QUERY"
