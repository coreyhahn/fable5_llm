#!/usr/bin/env bash
# sr1_score.sh <out_dir> — SR1 read-only scoring of the incremental probe from its
# OWN reports (a copy of evidence/qwen9b/bm/bm1_roll_score.sh's per-roll body,
# reading incrimpl.log instead of fullimpl.log), plus the reuse reports, DRC
# and the bitstream's size/sha256. Nothing is modified.
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
R=${1:?usage: sr1_score.sh <out_dir>}
I=$R/proj/stage1.runs/impl_1
echo "################ ROLL $R"
echo "SC mtimes:"
ls -la --time-style=full-iso $R/reports/*.rpt $I/*.bit $I/*.mmi $I/*_routed.dcp $I/*_postroute_physopt.dcp $I/*reuse*.rpt 2>&1 \
  | awk '{print "SC   " $6, $7, $5, $9}'
echo "SC incrimpl lines:"; grep -hE "^(INCR_|EXTRA_XDC|FULL_IMPL_CFG|TIMING|WHS_GATE|PBLOCK_COUNT|BUILD_OK|FATAL)" $R/incrimpl.log | sed "s/^/SC   /"
echo "SC ERROR lines: incrimpl.log $(grep -c '^ERROR' $R/incrimpl.log)  runme.log $(grep -c '^ERROR' $I/runme.log)"
echo "SC CRITICAL WARNING lines in runme.log: $(grep -c '^CRITICAL WARNING' $I/runme.log)"
grep -h '^CRITICAL WARNING' $I/runme.log | cut -c1-240 | sort | uniq -c | sed "s/^/SC   /"
echo "SC Timing 38-282 (failed to meet timing) count in runme.log: $(grep -c 'Timing 38-282' $I/runme.log)"
echo "SC incremental-flow messages (runme.log):"
grep -nE "Vivado 12-9151|Place 46-84|Place 46-44|Vivado_Tcl 4-24|Route 35-57|Place 30-746|Physopt 32-669|Route 35-416" $I/runme.log | cut -c1-240 | sed "s/^/SC   /"
echo "SC DRC (runme.log 'DRC finished' lines, incl. bitgen):"; grep -n "DRC finished" $I/runme.log | sed "s/^/SC   /"
echo "SC report_drc summary (reports/drc.rpt):"; grep -nE "^\| (Rule|[A-Z]+-[0-9]+)|Checks found|Violations found|^[0-9]+\. REPORT SUMMARY|ERROR|Error" $R/reports/drc.rpt | grep -iE "error|violations found|checks found" | head -20 | sed "s/^/SC   /"
awk '/^2\. REPORT DETAILS|^Table of Contents/ {exit} {print}' $R/reports/drc.rpt | grep -E "^\|" | head -40 | sed "s/^/SC DRCTAB /"
echo "SC bitstream:"; ls -la --time-style=full-iso $I/bd_wrapper.bit | sed "s/^/SC   /"; sha256sum $I/bd_wrapper.bit | sed "s/^/SC   sha256 /"
echo "SC VERSION baked in (create_project line of the source build):"; grep -h "create_project" synth/out_build_042_bm1/build.log | head -1 | sed "s/^/SC   /"
bash evidence/qwen9b/g5/g5d_roll_summary.sh $R/reports/timing_summary.rpt "$(basename $R)" "SR1 incremental probe"
echo "SC worst Max Delay path per named clock:"
awk '/^From Clock:|^Clock:/ {clk=$0} /^Slack \(VIOLATED\)|^Slack \(MET\)/ && !seen[clk]++ {sl=$0; getline; src=$0; getline; getline; dst=$0; print "WP " clk; print "WP   " sl; print "WP   " src; print "WP   " dst}' $R/reports/timing_summary.rpt \
  | grep -A3 -E "WP (Clock|From Clock): +(xdma_0_axi_aclk|pipe_clk|mmcm_clkout0(_[123])?)$" | grep -v "^--" | tr -s " "
echo "SC printed paths touching seq_0 / mv_busy_bm / bm_ cells: $(grep -cE 'bd_i/seq_0/|mv_busy_bm|/bm_[a-z0-9_]+_reg' $R/reports/timing_summary.rpt)"
for f in $I/bd_wrapper_incremental_reuse_pre_placed.rpt $I/bd_wrapper_incremental_reuse_routed.rpt; do
  echo "SC ======== $f (sections 1, 2, 4, 5.1, 7)"
  awk '/^1\. Incremental Flow Summary/{p=1} /^5\.2 /{p=0} /^7\. Non Reuse/{p=1} p' $f | grep -E "^\||^[0-9]" | sed "s/^/SC REUSE /"
done
echo "SC ======== hierarchical reuse (post-route), bd_i and its direct children (depth <= 2 under bd_wrapper), and layer_0 / seq_0 / mvchan_* subtrees to depth 5"
grep -E "^\|   bd_wrapper |^\|     bd_i |^\|       [a-z_0-9]+ " $R/reports/incr_reuse_routed_hier.rpt | sed "s/^/SC HIER /"
awk '/^\|       (layer_0|seq_0|mvchan_[0-3]|csr_0) /{p=1; print; next} /^\|       [a-z]/{p=0} p && /^\|           [ ]{0,6}[A-Za-z(]/' $R/reports/incr_reuse_routed_hier.rpt | sed "s/^/SC SUB /"
