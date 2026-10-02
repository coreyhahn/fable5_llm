#!/usr/bin/env bash
# rd_golden_shas.sh — the `.chip` goldens the state checks were made against.
#
# Review round 1: RD_GATE cites "16,404 golden state checks ALL MATCH" and
# "7,188", but rd_2b_artifact_shas.sh hashes the ARTIFACT SET only — the
# `.chip` files are excluded, and the 2B one's mtime postdates the set
# because R-c regenerated it when wall 8 was fixed.  A gate that rests on a
# golden must name that golden's bytes.
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
echo "--- the .chip goldens this gate compared against ---"
ls -la tb/scripts/w5/model_w8_2b_s1.e.chip \
       tb/scripts/w4/model_v2_s1.e4.chip \
       tb/scripts/w4/model_v2_s1.e.chip
echo
sha256sum tb/scripts/w5/model_w8_2b_s1.e.chip \
          tb/scripts/w4/model_v2_s1.e4.chip \
          tb/scripts/w4/model_v2_s1.e.chip
echo
echo "--- MEM lines each one asserts (= the scratch half of the check count) ---"
for f in tb/scripts/w5/model_w8_2b_s1.e.chip \
         tb/scripts/w4/model_v2_s1.e4.chip \
         tb/scripts/w4/model_v2_s1.e.chip; do
  printf '  %-40s MEM %6d   NREC %s  PC %s  EMBLOG2 %s\n' \
    "$(basename "$f")" "$(grep -c '^MEM ' "$f")" \
    "$(awk '/^NREC/{print $2}' "$f")" "$(awk '/^PC/{print $2}' "$f")" \
    "$(awk '/^EMBLOG2/{print $2}' "$f")"
done
echo
echo "NOTE the 2B golden's mtime postdates the artifact set: R-c regenerated"
echo "it when wall 8 (the TB's missing EMBLOG2 write) was fixed — its own"
echo "EMBLOG2 line above is that fix, and RC_GATE.md gate 40 is the run that"
echo "accepted it.  The .seq/.seqdata/.emb/187-image shas are unchanged and"
echo "are in hw_18_2b_artifact_shas.log."
