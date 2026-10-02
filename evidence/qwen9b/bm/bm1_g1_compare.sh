#!/usr/bin/env bash
# bm1_g1_compare.sh — BM1-T1's G1 checks that need the finished G1 run
# (spec docs/superpowers/specs/2026-09-24-board-idle-counters-design.md §3.3
# A and C).  Run ON SNOKE through evidence/qwen9b/bm/bm_run.sh, after
# n10 (run_bm1.sh model_9b_s1 bmtl) has finished.  Read-only.
#
#   A  the G1 run's SEQ_TIMELINE block equals the census's (003) LINE FOR
#      LINE — the counters add registers only; any moved line FAILS;
#      and the G1 CSV equals the census CSV byte for byte below its first
#      line (line 1 names the CSV's own path, which differs by design).
#   C  the union counters exactly against a recount over the G1 run's OWN
#      CSV (evidence/qwen9b/bm/bm1_expect.py), and the RTL registers the
#      G1 run printed against that recount.
#   +  the sha256 of the binary every G1/G2 run used.
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
cd "$ROOT" || exit 1
CEN_LOG=evidence/qwen9b/bn/003_timeline_model_9b_s1.log
CEN_CSV=evidence/qwen9b/bn/bn_timeline_model_9b_s1.csv
CEN_SHA=evidence/qwen9b/bn/bn_timeline_model_9b_s1.csv.sha256
G1_LOG=evidence/qwen9b/bm/seedlogs_model_9b_s1_bmtl/model_9b_s1.log
G1_CSV=evidence/qwen9b/bm/bm1_timeline_model_9b_s1.csv
BIN=tb/obj_dir_seq_chip_bm1/tb_seq_chip_9b_bm1
FAIL=0

echo "=== A1: SEQ_TIMELINE block, census 003 vs G1 (line for line)"
NC=$(grep -c '^SEQ_TIMELINE' "$CEN_LOG")
NG=$(grep -c '^SEQ_TIMELINE' "$G1_LOG")
echo "    lines: census $NC   G1 $NG"
if diff <(grep '^SEQ_TIMELINE' "$CEN_LOG") <(grep '^SEQ_TIMELINE' "$G1_LOG") \
     > /dev/null; then
  echo "    SEQ_TIMELINE BLOCK IDENTICAL ($NC lines)"
else
  FAIL=1
  echo "    SEQ_TIMELINE BLOCK DIFFERS — first differences:"
  diff <(grep '^SEQ_TIMELINE' "$CEN_LOG") <(grep '^SEQ_TIMELINE' "$G1_LOG") \
    | head -20 | sed 's/^/      /'
fi

echo "=== A2: the CSV, census vs G1"
echo "    census csv sha256 (whole)  $(sha256sum < "$CEN_CSV" | cut -d' ' -f1)"
echo "    committed census sha256    $(cut -d' ' -f1 "$CEN_SHA")"
echo "    G1 csv sha256 (whole)      $(sha256sum < "$G1_CSV" | cut -d' ' -f1)  $(wc -c < "$G1_CSV") B"
echo "    census line 1: $(head -1 "$CEN_CSV")"
echo "    G1     line 1: $(head -1 "$G1_CSV")"
HC=$(tail -n +2 "$CEN_CSV" | sha256sum | cut -d' ' -f1)
HG=$(tail -n +2 "$G1_CSV" | sha256sum | cut -d' ' -f1)
echo "    below line 1: census $HC"
echo "                  G1     $HG"
if [ "$HC" = "$HG" ]; then
  echo "    CSV BODY IDENTICAL (every record row and signature row)"
else
  FAIL=1
  echo "    CSV BODY DIFFERS"
fi

echo "=== C: exact recount of the unions over the G1 run's OWN CSV"
TMP=$(mktemp)
/home/cah/.venv/bin/python evidence/qwen9b/bm/bm1_expect.py "$G1_LOG" \
    --csv "$G1_CSV" --out "$TMP" | sed 's/^/    /'
for NAME in BM_MVANY CENSUS_I2 BM_MV0 BM_MV1 BM_MV2 BM_MV3 BM_FENCE \
            BM_MOVX BM_MOVY BM_MVWORK BM_IMOVER BM_STEPS PERF_CYC; do
  WANT=$(awk -v n="$NAME" '$1 == n { print $2 }' "$TMP")
  if [ "$NAME" = CENSUS_I2 ]; then
    # the TB sampler's I-2 figure ("ref I2 <n>" on the INFO line)
    GOT=$(sed -n 's/^BM1 L0 INFO .* ref I2 \([0-9]*\) .*/\1/p' "$G1_LOG")
    SRC="TB sampler"
  else
    GOT=$(awk -v n="$NAME" '$1 == "BM1" && $2 == "L0" && $3 == n { print $5 }' "$G1_LOG")
    SRC="RTL register"
  fi
  if [ -n "$GOT" ] && [ "$GOT" = "$WANT" ]; then
    echo "    $NAME  $SRC $GOT  = G1-CSV/G1-block recount $WANT  OK"
  else
    FAIL=1
    echo "    $NAME  $SRC '$GOT'  vs recount '$WANT'  MISMATCH"
  fi
done
rm -f "$TMP"

echo "=== the binary"
echo "    $BIN"
echo "    built  $(date -Is -r "$BIN")"
echo "    sha256 $(sha256sum < "$BIN" | cut -d' ' -f1)"

if [ "$FAIL" = 0 ]; then echo "BM1_G1_COMPARE: PASS"
else echo "BM1_G1_COMPARE: FAIL"; fi
exit "$FAIL"
