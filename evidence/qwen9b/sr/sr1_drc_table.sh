#!/usr/bin/env bash
# sr1_drc_table.sh <out_dir> — print the REPORT SUMMARY table of <out_dir>/reports/drc.rpt
# and count Error / Critical Warning rule rows. Read-only.
R=${1:?}
ls -la --time-style=full-iso $R/reports/drc.rpt
awk '/^1\. REPORT SUMMARY/{p=1} /^2\. REPORT DETAILS/{exit} p' $R/reports/drc.rpt
grep -E "Design State" $R/reports/drc.rpt
echo "DRC_ERROR_OR_CRITICAL_ROWS: $(awk '/^1\. REPORT SUMMARY/{p=1} /^2\. REPORT DETAILS/{exit} p' $R/reports/drc.rpt | grep -cE '^\| [A-Z0-9-]+ +\| (Error|Critical Warning) ')"
