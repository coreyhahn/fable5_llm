#!/usr/bin/env bash
# g6_pack_rung.sh — the weight pack on silicon: whole-pack audit, the
# CONTRIVED miss, both detectors, the whole-pack re-upload, and the undo.
#
# The plan's Step 3 asks for three things this runs in order:
#   (a) per-PIECE readback verification  — sw/seq_run.upload does it inline
#   (b) RD_GATE follow-on 2's WHOLE-PACK HASH replacing the witness sample
#   (c) the re-upload branch DELIBERATELY exercised, because on hardware it
#       has never fired (sw/chat_seq.py:1194-1196) and hoping is not a test
set -euo pipefail
cd "$(dirname "$0")/../../.."
PY=/home/cah/.venv/bin/python
P=tb/scripts/w9/model_9b_s1.e4
G=evidence/qwen9b/g6
WID=248     # the LM head: chunk-INTERLEAVED across all four channels, the
            # image RD_GATE §4.2's blind spot was found in

echo "########## [1] re-establish the pack, per-piece verified, and run"
$PY sw/seq_run.py --prefix $P --four-chan --zero-scratch --out $G/016_seq_s1.json

echo
echo "########## [2] the WHOLE-PACK audit — clean"
$PY $G/g6_residency.py --prefix $P --audit --json $G/016_audit_clean.json

echo
echo "########## [3] chat_seq's OWN witness sampler on a clean pack"
$PY $G/g6_residency.py --prefix $P --witness-probe --json $G/016_witness_clean.json

echo
echo "########## [4] CONTRIVE the miss — one piece of wid $WID"
$PY $G/g6_residency.py --prefix $P --corrupt-wid $WID --i-mean-it \
    --json $G/016_corrupt.json

echo
echo "########## [5] does the WHOLE-PACK audit see it?"
set +e
$PY $G/g6_residency.py --prefix $P --audit --json $G/016_audit_damaged.json
echo "   (rc $? — 1 is the expected verdict here)"
set -e

echo
echo "########## [6] does chat_seq's WITNESS SAMPLER see it, and escalate?"
$PY $G/g6_residency.py --prefix $P --witness-probe \
    --json $G/016_witness_damaged.json

echo
echo "########## [7] the WHOLE-PACK re-upload — the repair"
$PY sw/seq_run.py --prefix $P --four-chan --out $G/016_seq_s1_repair.json

echo
echo "########## [8] the audit again — the damage is UNDONE"
$PY $G/g6_residency.py --prefix $P --audit --json $G/016_audit_repaired.json

echo
echo "########## [9] and the witness sampler agrees"
$PY $G/g6_residency.py --prefix $P --witness-probe \
    --json $G/016_witness_repaired.json
