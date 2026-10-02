#!/usr/bin/env bash
# g6_pack_rung2.sh — the weight pack on silicon, audited BEFORE the program
# runs.  Supersedes g6_pack_rung.sh, whose ordering was wrong and whose log
# (016) records why: it audited AFTER a run, and all 24 conv images missed
# because the PROGRAM writes conv state into the very blocks the host
# uploaded.  The 1,114 weight pieces and the embedding were byte-identical
# there, so the pack was healthy and the probe was measuring the wrong
# moment.  See RD9_GATE for what that says about the conv witnesses.
set -euo pipefail
cd "$(dirname "$0")/../../.."
PY=/home/cah/.venv/bin/python
P=tb/scripts/w9/model_9b_s1.e4
G=evidence/qwen9b/g6
WID=248     # the LM head: chunk-INTERLEAVED across all four channels — the
            # image RD_GATE §4.2's blind spot was found in

echo "########## [1] upload the pack, per-piece verified, WITHOUT running it"
$PY sw/seq_run.py --prefix $P --four-chan --dry-run --out $G/017_upload.json

echo
echo "########## [2] the WHOLE-PACK audit — every host-written byte"
$PY $G/g6_residency.py --prefix $P --audit --json $G/017_audit_clean.json

echo
echo "########## [3] chat_seq's OWN R-d witness sampler, clean"
$PY $G/g6_residency.py --prefix $P --witness-probe --json $G/017_wit_clean.json

echo
echo "########## [4] CONTRIVE the miss — one piece of wid $WID"
$PY $G/g6_residency.py --prefix $P --corrupt-wid $WID --i-mean-it \
    --json $G/017_corrupt.json

echo
echo "########## [5] the WHOLE-PACK audit sees it"
set +e
$PY $G/g6_residency.py --prefix $P --audit --json $G/017_audit_damaged.json
echo "   (rc $? — 1 IS the verdict this step is asking for)"
set -e

echo
echo "########## [6] the WITNESS SAMPLER sees it too, and ESCALATES"
$PY $G/g6_residency.py --prefix $P --witness-probe --json $G/017_wit_damaged.json

echo
echo "########## [7] the whole-pack re-upload — the repair branch"
$PY sw/seq_run.py --prefix $P --four-chan --dry-run --out $G/017_repair.json

echo
echo "########## [8] the audit again — the damage is UNDONE"
$PY $G/g6_residency.py --prefix $P --audit --json $G/017_audit_repaired.json

echo
echo "########## [9] the witness sampler agrees"
$PY $G/g6_residency.py --prefix $P --witness-probe --json $G/017_wit_repaired.json

echo
echo "########## [10] and the repaired pack still computes §4.1a's tokens"
$PY sw/seq_run.py --prefix $P --four-chan --skip-weights --zero-scratch \
    --out $G/017_run_after_repair.json
