#!/usr/bin/env bash
# sr7_drc_table.sh <out_dir> — print the REPORT SUMMARY rule table of
# <out_dir>/reports/drc.rpt and count Error / Critical Warning rule rows.
# Read-only.  A copy of sr1_drc_table.sh with its range fixed: that script
# starts at the first "1. REPORT SUMMARY" but exits at the first
# "2. REPORT DETAILS", which is the Table of Contents entry printed BEFORE the
# summary, so it printed nothing and its count was vacuous (SR7 n726/n727).
# Here the summary is the text between the SECOND "1. REPORT SUMMARY" line
# (the section header, after the ToC) and the SECOND "2. REPORT DETAILS".
R=${1:?}
F=$R/reports/drc.rpt
ls -la --time-style=full-iso $F
grep -E "Design State|Checks found" $F | head -2
SUM=$(awk '/^1\. REPORT SUMMARY/{n1++} /^2\. REPORT DETAILS/{n2++} n1==2 && n2<2' $F)
printf '%s\n' "$SUM" | grep -E "^\|"
echo "DRC_RULE_ROWS: $(printf '%s\n' "$SUM" | grep -cE '^\| [A-Z0-9-]+ +\| ')"
echo "DRC_ERROR_OR_CRITICAL_ROWS: $(printf '%s\n' "$SUM" | grep -cE '^\| [A-Z0-9-]+ +\| (Error|Critical Warning) ')"
