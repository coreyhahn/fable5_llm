#!/usr/bin/env bash
# evidence/qwen9b/g2/g2a_census.sh — the closure sweep for G2a's literal census.
# One command per census row, so the gate doc's "closed" column is a rerunnable
# claim rather than a table someone typed.  /usr/bin/grep, per the campaign's
# standing rule (the shell grep here is ugrep and skips gitignored trees).
set -u
cd "$(dirname "$0")/../../.."
echo "=== G2a literal-census closure sweep ($(date -Is), /usr/bin/grep) ==="
echo
echo "--- [1] hard 1024 arguments on sw/infer.py's step() path (defect B)"
/usr/bin/sed -n '/def step(self, tok, pos)/,/return M.hw_amax/p' sw/infer.py \
  | /usr/bin/grep -n "1024" || echo "  (no 1024 at all)"
echo
echo "--- [2] SCRATCH_WORDS: one definition, the rest import it"
git ls-files '*.py' | xargs /usr/bin/grep -n "SCRATCH_WORDS = "
echo
echo "--- [3] SPTR masks in sw/chat_seq.py (three -> SPTR_MASK; the remaining"
echo "        0x7FFF is the GATE dst ISA FIELD and stays 15-bit until Task 7)"
/usr/bin/grep -n "0x7FFF\|SPTR_MASK" sw/chat_seq.py
echo
echo "--- [4] RS_F: no host site pins the value 8 any more"
git ls-files 'sw/*.py' | xargs /usr/bin/grep -n "RS_F == 8\|HEAD_LOGIT_EXP0 = -22" \
  || echo "  (none)"
echo
echo "--- [5] manifest meta keys and their defaults (one edit, not two)"
/usr/bin/grep -n "MANIFEST_META_KEYS = \|_META_DEFAULTS = \|RS_F_DEFAULT = \|EMB_ROW_BYTES_DEFAULT = " sw/hwmap.py
echo
echo "--- [6] DN/KV slot counts and KV heads: one definition"
git ls-files 'ref/*.py' | xargs /usr/bin/grep -n "^_DN_SLOTS = \|^_KV_SLOTS = \|^_KVH = \|^DN_SLOTS, KV_SLOTS"
echo
echo "--- [7] the GD+16+h wall-17 defect (live sites only)"
/usr/bin/grep -n "M.dnst(h," ref/gen_layer_script.py
echo
echo "--- [7b] dnz has BOTH guards, not just the geometry one (review B1)"
/usr/bin/grep -n "def dnz" -A 34 ref/gen_layer_script.py \
  | /usr/bin/grep -E "DNST_HEAD_MAX|ARG0_HEAD_BITS"
echo
echo "--- [8] VREP in the emitter's QKV head loop"
/usr/bin/grep -n "h // LR.VREP\|hk \* LR.LDK" ref/gen_layer_script.py
echo
echo "--- [9] POS_COPIES / POS_STRIDE derived on both sides"
/usr/bin/grep -n "^POS_COPIES\|^POS_STRIDE\|^POS_BLOCK\|^POS_WORDS\|^POS_COPY_BYTES" \
  ref/seq_chat.py sw/chat_seq.py
echo
echo "--- [10] tok_meter's plan_weights call (D-TOK)"
/usr/bin/grep -n "wbase_of, wtop = plan_weights" sw/tok_meter.py
echo
echo "--- [11] the dead generator (D-DEAD)"
git ls-files | /usr/bin/grep "gen_seq_vectors.py" \
  || echo "  tb/scripts/gen_seq_vectors.py: DELETED (absent from git ls-files)"
echo
echo "CENSUS SWEEP DONE"
