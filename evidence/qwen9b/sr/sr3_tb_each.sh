#!/usr/bin/env bash
# sr3_tb_each.sh — Task SR3: build tb_seq_unit into ONE named obj_dir and run
# EVERY vector of `make tb_seq`'s list (SEQ_SEEDS / SEQ_ERRS / SEQ_MICRO /
# SEQ_DIRECTED, read from tb/Makefile itself), NOT stopping at the first
# failure — so a RED run on the pre-SR3 RTL records every vector's verdict
# and every vector's cycle line (the base for sr3_cycles.py's
# backward-compatibility compare).  Run ON SNOKE, through sr_run.sh.
#   evidence/qwen9b/sr/sr3_tb_each.sh <obj_dir> <vec_dir> [<rtl_dir>]
# (obj_dir, vec_dir relative to tb/).  <rtl_dir> (relative to tb/) replaces
# ../rtl for seq_unit.sv + seq_movers.sv only — the RED run builds the BASE
# commit's two files (extracted by `git show`) without touching the working
# tree, and the mutant control builds a deliberately broken copy.
set -u
OBJ=${1:?obj_dir}; VEC=${2:?vec_dir}; RTLD=${3:-../rtl}
PY=/home/cah/.venv/bin/python
cd "$(dirname "$0")/../../../tb" || exit 1
mv_() { make -s --no-print-directory --eval="sr3pv: ; @echo \$($1)" sr3pv; }
SEEDS=$(mv_ SEQ_SEEDS); ERRS=$(mv_ SEQ_ERRS); MICRO=$(mv_ SEQ_MICRO)
DIR=$(mv_ SEQ_DIRECTED)
echo "SR3 lists: seeds [$SEEDS] errs [$ERRS] micro [$MICRO] directed [$DIR]"
make --no-print-directory seq_unit_vectors SEQ_VEC="$VEC" VECPY=$PY || exit 1
echo "SR3 RTL: $RTLD/seq_unit.sv sha256 $(sha256sum < "$RTLD/seq_unit.sv" | cut -c1-16)," \
     "$RTLD/seq_movers.sv sha256 $(sha256sum < "$RTLD/seq_movers.sv" | cut -c1-16)"
make --no-print-directory tb_seq_build SEQ_OBJ="$OBJ" JOBS=16 \
     SEQ_RTL="$RTLD/seq_unit.sv $RTLD/seq_movers.sv" || exit 1
npass=0; nfail=0; fails=""
run1() {
  echo "----- SR3VEC $1"
  "$OBJ/tb_seq" +vec="$VEC/$1" 2>&1
  rc=$?
  if [ $rc -eq 0 ]; then npass=$((npass+1)); v=PASS
  else nfail=$((nfail+1)); fails="$fails $1"; v=FAIL; fi
  echo "SR3VEC $1 $v rc=$rc"
}
for s in $SEEDS; do run1 seq_u_s$s; done
for e in $ERRS;  do run1 seq_e_$e;  done
for m in $MICRO; do run1 seq_m_$m;  done
for d in $DIR;   do run1 seq_h_$d;  done
echo "SR3 SUMMARY: $npass PASS, $nfail FAIL:$fails"
