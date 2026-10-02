#!/usr/bin/env bash
# rd_2b_artifact_shas.sh — the 2B W8 artifact set is UNCOMMITTED (2.9 GiB,
# .gitignored), so before it goes on silicon its identity is re-established
# against the shas RC_GATE.md §2 recorded when Task 4 built it.
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm/tb/scripts/w5 || exit 1
P=model_w8_2b_s1

echo "--- files ---"
ls -la $P.e.seq $P.e.seq.json $P.e.seqdata.bin $P.weights.json $P.txt \
       $P.emb.bin $P.e.chip
echo "  187 images: $(ls ${P}_w*.bin | wc -l) files, \
$(du -cb ${P}_w*.bin | tail -1 | cut -f1) B"
echo
echo "--- measured sha256 (RC_GATE.md §2 expects these) ---"
sha256sum $P.e.seq $P.e.seq.json $P.e.seqdata.bin $P.weights.json $P.txt \
          $P.emb.bin
echo -n "  187-image list sha: "
# LOCALE-INDEPENDENT SINCE 2026-09-10 (#19, triage (b)13).  This used to read
# `sha256sum ${P}_w*.bin | sha256sum`, which digests the list in SHELL GLOB
# order -- and glob order is LC_COLLATE-dependent.  The SAME 187 files, byte
# for byte, therefore had two identities:
#   c9e6d0a61bfda3542890689c3c69620fa7681c8bc82f6aa4c3e57c9f749e66ef  en_US.UTF-8
#   e6a1c0b5ff873fad88243ea1c52599a672844dd31db3aac7e23c0cd65ac0a9b2  C
# (both measured on snoke: evidence/qwen9b/o3/84_artifact_shas_locale_RED.log).
# On the artifact set that feeds the resident bitstream, a check that reports
# a mismatch which is not one is worse than no check.  The order is pinned to
# C collation now, explicitly, so the digest is a property of the FILES.
# THE PINNED VALUE IS THEREFORE THE C ONE; RC_GATE.md section 2 records both.
printf '%s\n' ${P}_w*.bin | LC_ALL=C sort | LC_ALL=C xargs sha256sum | sha256sum
echo
cat <<'EXPECT'
--- RC_GATE.md §2, the same digests (NOT a verbatim transcript: the two
    187-image rows are printed C-order FIRST, the order this script now
    measures in, and every row carries an expanded label) ---
fa8d9349cf1d0aa618ab79e0a2565dd89adbb147b665cb49b582d83c95b05bcb  .e.seq
998ab2604d4ed44f396a78c292a3ddb40aaaf3244968e2f8b4b4ab58cb4cead8  .e.seq.json
e8d536ee95880ff399ff25ebad13b851486ea51cb32b6dd216125b6e87f8fc28  .e.seqdata.bin
f4eb9b25cb07f357127272edbdf7b4f2b1471eb4ebd137729cb0bee117c672c3  .weights.json
be2180584ce3ca8a03d8edb4c36bc31b9daa5333eb6cfb5cba90084b331c1255  .txt
b54db7a9fa6ba97fda253b00c7ed9a4a0afe7ba43b93b9b85c2aa3876963d3aa  .emb.bin
e6a1c0b5ff873fad88243ea1c52599a672844dd31db3aac7e23c0cd65ac0a9b2  (187-image list, LC_ALL=C order — the pinned one since 2026-09-10)
c9e6d0a61bfda3542890689c3c69620fa7681c8bc82f6aa4c3e57c9f749e66ef  (187-image list, the ORIGINAL RC_GATE value: the same files in
                                                                   en_US.UTF-8 glob order, kept so the old record still reconciles)
EXPECT
