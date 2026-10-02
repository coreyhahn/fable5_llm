#!/usr/bin/env bash
# bm1_roll_score.sh <out_dir>... — BM1-T3 read-only scoring of implementation rolls
# against G5D_TIMING.md §10's bar, from each roll's OWN reports.
# Per roll: report/artifact mtimes (freshness), the fullimpl TIMING/WHS_GATE/
# PBLOCK/EXTRA_XDC lines, g5d_roll_summary.sh's design row + six named clocks,
# the first (worst) Max Delay path per named clock (source, destination), and
# whether ANY path printed in the report's per-clock sections touches seq_0 or
# a mv_busy_bm / bm_ net (the counters). Nothing is modified.
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
for R in "$@"; do
  echo "################ ROLL $R"
  echo "SC mtimes:"
  ls -la --time-style=full-iso $R/reports/timing_summary.rpt $R/reports/utilization.rpt $R/reports/utilization_hier.rpt \
     $R/proj/stage1.runs/impl_1/*.bit $R/proj/stage1.runs/impl_1/*.mmi $R/proj/stage1.runs/impl_1/*_routed.dcp \
     $R/proj/stage1.runs/impl_1/*_postroute_physopt.dcp 2>&1 | awk '{print "SC   " $6, $7, $5, $9}'
  echo "SC fullimpl lines:"; grep -hE "^(EXTRA_XDC|FULL_IMPL_CFG|TIMING|WHS_GATE|PBLOCK_COUNT|BUILD_OK|FATAL)" $R/fullimpl.log | sed "s/^/SC   /"
  echo "SC ERROR lines in fullimpl.log: $(grep -c '^ERROR' $R/fullimpl.log)"
  bash evidence/qwen9b/g5/g5d_roll_summary.sh $R/reports/timing_summary.rpt "$(basename $R)" "BM1-T3 spread roll"
  echo "SC worst Max Delay path per named clock:"
  awk '/^From Clock:|^Clock:/ {clk=$0} /^Slack \(VIOLATED\)|^Slack \(MET\)/ && !seen[clk]++ {sl=$0; getline; src=$0; getline; getline; dst=$0; print "WP " clk; print "WP   " sl; print "WP   " src; print "WP   " dst}' $R/reports/timing_summary.rpt \
    | grep -A3 -E "WP (Clock|From Clock): +(xdma_0_axi_aclk|pipe_clk|mmcm_clkout0(_[123])?)$" | grep -v "^--" | tr -s " "
  echo "SC printed paths touching seq_0 / mv_busy_bm / bm_ cells: $(grep -cE 'bd_i/seq_0/|mv_busy_bm|/bm_[a-z0-9_]+_reg' $R/reports/timing_summary.rpt)"
  grep -nE 'bd_i/seq_0/|mv_busy_bm|/bm_[a-z0-9_]+_reg' $R/reports/timing_summary.rpt | head -5 | tr -s " " | sed "s/^/SC   /"
done
