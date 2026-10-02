#!/usr/bin/env bash
# rd_prestate.sh — the board's state BEFORE R-d touches anything.
# Kept in a script file (not `bash -c`) so the pgrep patterns cannot match
# the capture command's own argv.
echo "--- other board users ---"
pgrep -af 'chat_seq|seq_run|serve\.py|infer\.py|tok_meter|matvec_test|layer_test' \
  | grep -v rd_prestate || echo "(none)"
echo "--- uptime / last boot ---"; uptime; who -b
echo "--- lspci 82:00.0 ---";     lspci -s 82:00.0 || true
echo "--- lspci -d 10ee: ---";    lspci -d 10ee:  || true
echo "--- lsmod xdma ---";        lsmod | grep -E '^xdma ' || echo "(xdma module NOT loaded)"
echo "--- /dev/xdma0_* ---";      ls -la /dev/xdma0_* 2>&1 || true
echo "--- sysfs 0000:82:00.0 ---"; ls -d /sys/bus/pci/devices/0000:82:00.0 2>&1 || true
echo "--- hw_server ---";         pgrep -af 'hw_server' | grep -v rd_prestate || echo "(hw_server not running)"
echo "--- vivado batch jobs ---"; pgrep -af 'vivado -mode batch' | grep -v rd_prestate || echo "(none)"
echo "--- bitstream to program ---"
ls -la synth/out_build_035_fp2a_exc_po/bd_wrapper.bit
sha256sum synth/out_build_035_fp2a_exc_po/bd_wrapper.bit
