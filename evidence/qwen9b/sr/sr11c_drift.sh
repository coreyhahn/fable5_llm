#!/usr/bin/env bash
# sr11c_drift.sh — SR11c: the one combined cite-drift repair of the sequencer
# RTL round, one o3_cite_drift.py argument list per pass.  Docs are read at
# the PASS BASE (--doc-base = --base), not at HEAD: a token written after the
# base (e.g. SEQ_ISA.md's B17.2, in post-edit coordinates) is then not in the
# sweep, so a rewrite of it can only show as COLLATERAL (hand-checked) — never
# as a silent REPAIR (a double shift).  Exclusions: the Addendum-2 rule,
# applied mechanically by evidence/qwen9b/sr/sr11c_excl.py (first commit after
# the base; the standing list; tb/ and SR13a's files), printed into the log.
#   evidence/qwen9b/sr/sr11c_drift.sh <pass> --plan|--fix|--verify|--audit [extra]
# passes:
#   hwmap   sw/hwmap.py since c8aef0e^ (67181c6)               — SR7's n761
#   host9c  sw/seq_run.py, sw/chat_seq.py, ref/seq_chat.py since 9c8e73b
#           (cfbf90f, SR11a fix2: its drift was applied to NEXT_SESSION.md
#           only, n1149k; + fa7f5df/925d29d/3eb0728) — NEXT_SESSION.md is
#           excluded here (it was re-aimed through 966cbcf)
#   host96  sw/seq_run.py, sw/chat_seq.py since 966cbcf (SR13b's 3eb0728,
#           n1361/n1362) — only NEXT_SESSION.md and the documents first
#           committed after 9c8e73b (the host9c pass owns the rest)
#   model   ref/seq_model.py, ref/seq_format.py since d501068^ (7e64d05)
#   rtl     rtl/seq_unit.sv, rtl/seq_movers.sv, rtl/matvec_chan.sv,
#           rtl/matvec_engine.sv since 2910d4d (f4c1fb7, 2327d7a, 9ff3e7e)
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
PY=/home/cah/.venv/bin/python
P=${1:?usage: sr11c_drift.sh <pass> --plan|--fix|--verify [extra]}; shift
XA=()
case "$P" in
  hwmap)  B=67181c6; E=sw/hwmap.py ;;
  host9c) B=9c8e73b; E=sw/seq_run.py,sw/chat_seq.py,ref/seq_chat.py
          XA=(--also-exclude NEXT_SESSION.md) ;;
  host96) B=966cbcf; E=sw/seq_run.py,sw/chat_seq.py
          XA=(--before 9c8e73b --keep NEXT_SESSION.md) ;;
  # fix round 1 (m6): pass 2c — SR11a_R2_MODEL.md only (standing-listed, but
  # its host cites were written/re-aimed in 966cbcf coordinates and SR13b's
  # 3eb0728 moved them; the coordinator named it)
  host96b) B=966cbcf; E=sw/seq_run.py,sw/chat_seq.py
          XA=(--only evidence/qwen9b/sr/SR11a_R2_MODEL.md) ;;
  model)  B=7e64d05; E=ref/seq_model.py,ref/seq_format.py ;;
  rtl)    B=2910d4d; E=rtl/seq_unit.sv,rtl/seq_movers.sv,rtl/matvec_chan.sv,rtl/matvec_engine.sv ;;
  *) echo "unknown pass $P" >&2; exit 2 ;;
esac
EX=$("$PY" evidence/qwen9b/sr/sr11c_excl.py --base "$B" --edited "$E" "${XA[@]}") || exit 2
# --audit: the hand-check sheet (evidence/qwen9b/sr/sr11c_audit.py) for the
# SAME argument list; anything else goes to o3 unchanged.
TOOL=evidence/qwen9b/o3/o3_cite_drift.py
if [ "${1:-}" = "--audit" ]; then TOOL=evidence/qwen9b/sr/sr11c_audit.py; shift; fi
# shellcheck disable=SC2086
exec "$PY" "$TOOL" \
  --base "$B" --doc-base "$B" --edited "$E" $EX "$@"
