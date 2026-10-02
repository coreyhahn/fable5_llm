#!/usr/bin/env bash
# census_nodrain_red.sh — the RED and the negative arm for the census's
# NON-DRAINING mode and its fence-hold counters (S4 fix round 1, review I4).
#
#   bash evidence/qwen9b/s4/census_nodrain_red.sh
#
# WHY THIS EXISTS.  The shipped census DRAINS the engine between commands,
# which is what makes each LCYC difference that command's cost — and which
# also makes an F1 or F2 hold structurally impossible, so the brief's "count
# of F1/F2 stalls actually taken" could not be produced by it.  `+nodrain=1`
# replays the same script under the SEQUENCER's back-pressure rule
# (rtl/seq_unit.sv:1188 polls cmd_cnt and never STATUS bit 0) and counts the
# holds per cycle.  A NEW counter is worth nothing until it has been seen to
# fire, and a counter that fires on everything is worth less than nothing.
#
# The SIX arms, all on the 1-layer 9B smoke `scripts/w9/lay9b_s1` (978
# commands, 174,238 bit-exact checks — minutes, not hours):
#
#   nd8      +nodrain=1 at LAT 8      the shipping latency
#   dr8      the DRAINING mode at LAT 8
#   nd4000   +nodrain=1 at LAT 4000   THE RED: the modelled window is slow
#            enough that a transfer CANNOT be hidden behind the compute that
#            follows it, so the F1 hold MUST be non-zero.  If it is zero the
#            counter is not proven and this script FAILS.
#   dr4000   the DRAINING mode at the SAME LAT 4000
#   f2half   +nodrain=1 at LAT 8 on a copy of the smoke with ONE record
#            retargeted — the arm that shows why one record is not enough
#            (printed, not asserted; see the header of arm_perturbed)
#   f2fence  +nodrain=1 at LAT 8 on a copy with TWO records perturbed —
#            S4 fix round 2, review I-2 — which makes the SPEC'S F2 fence
#            hold.  The long comment above that arm says why the shipped
#            schedule never can, what the two records change, and why the arm
#            is NOT a correctness run.  Its PASS criterion is F2 FENCE > 0
#            and nothing else.
#
# and FOUR verdicts, of which the third is the strongest:
#
#   RED       F1(nd4000) > 0 -- the counter fires.
#   NEGATIVE  every DRAINING arm reads 0 / 0 at BOTH latencies -- the drain
#             makes a hold structurally impossible, so a counter that read
#             anything there would be counting something else.
#   IDENTITY  LCYC(nodrain) - F1 - F2 == LCYC(draining), at BOTH latencies.
#             The compute lane's real work does not depend on the memory
#             model, so EVERY extra LCYC cycle back-to-back dispatch costs
#             must be a fence hold -- and the two counters must account for
#             all of it, to the cycle, or they are measuring the wrong thing.
#   RED-F2FENCE  F2 FENCE(f2fence) > 0 -- the THIRD counter fires too, on a
#             schedule perturbed into the shape S2's case 6 proved the fence
#             on.  Without it the 0 the model runs report is *not observed*,
#             not *measured zero*.
#
# The first four arms also have to stay BIT-EXACT (`TB_LAYER_CENSUS PASS`): a
# hold that corrupted an answer would be a fence defect, not a measurement.
# The last two deliberately break the schedule and say so — see their header.
#
# Run ON SNOKE (user rule 2026-08-09: heavy Verilator sims on snoke).
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
RUN=$ROOT/evidence/qwen9b/s4/run_s4_census.sh
SCRIPT=scripts/w9/lay9b_s1.txt
# The GENERATED artifacts of the last two arms.  They live beside the smoke
# because run_s4_census.sh derives `+state=` from the script's own path
# prefix, and `tb/scripts/w9/` is .gitignore'd (.gitignore:36), so nothing
# here can dirty the tree.  Every one of them is DELETED on exit, success or
# failure — the committed script is never edited in place and no generated
# file survives the run.
PW=$ROOT/tb/scripts/w9
PGEN="$PW/lay9b_s1_f2half.txt $PW/lay9b_s1_f2half.state.bin \
      $PW/lay9b_s1_f2fence.txt $PW/lay9b_s1_f2fence.state.bin"
# the SHIPPING latency: the perturbation makes its own long transfer, so the
# fence arm needs no latency knob (see arm_perturbed's header).  LAT 8 is the
# COMMITTED figure -- 076_census_nodrain_red2.log is the only log of these two
# arms and it is LAT 8 throughout.  Other latencies were explored uncommitted
# while the arm was being built and are NOT evidence; nothing in this script
# or in S4_REPLAY.md claims a latency sweep.
F2LAT=${F2LAT:-8}
# per-arm stdout goes to a PRIVATE temp directory, never beside the evidence:
# two of these running at once would otherwise delete each other's captures.
TMP=$(mktemp -d "${TMPDIR:-/tmp}/s4_nodrain_red.XXXXXX")
# shellcheck disable=SC2086  # PGEN is a deliberate word-split list
trap 'rm -rf "$TMP"; rm -f $PGEN' EXIT

FAIL=0
echo "CENSUS_NODRAIN_RED: host $(hostname), script $SCRIPT"

val () {  # $1 = census table, $2 = the TOTAL_* key
  awk -v k="$2" '$2 == k { print $3 }' "$1"
}

arm () {  # $1 = cfg, $2 = NODRAIN, $3 = LAT
  echo
  echo "=== arm $1: NODRAIN=$2 LAT=$3"
  T0=$(date +%s)
  NODRAIN=$2 LAT=$3 JOBS="${JOBS:-12}" bash "$RUN" "$1" "$SCRIPT" \
    > "$TMP/$1.out" 2>&1
  rc=$?
  T1=$(date +%s)
  OUT=$TMP/$1.out
  grep -E "TB_LAYER_CENSUS|LAYER_CENSUS (dispatch|state_region|commands|steps)" \
    "$OUT" | sed 's/^/    /'
  echo "    rc=$rc  wall=$((T1 - T0))s"
  [ "$rc" = 0 ] || { echo "    UNEXPECTED rc $rc"; FAIL=1; }
  grep -q "TB_LAYER_CENSUS PASS" "$OUT" \
    || { echo "    NOT BIT-EXACT: no TB_LAYER_CENSUS PASS"; FAIL=1; }
  T=$ROOT/evidence/qwen9b/s4/census_$1.txt
  F1=$(val "$T" TOTAL_F1_HOLD_CYCLES)
  F2=$(val "$T" TOTAL_F2_HOLD_CYCLES)
  FF=$(val "$T" TOTAL_F2_FENCE_CYCLES)
  BZ=$(val "$T" TOTAL_BUSY_CYCLES)
  SD=$(val "$T" TOTAL_SDMA_CYCLES)
  echo "    F1_HOLD=$F1  F2_HOLD=$F2  F2_FENCE=$FF  LCYC=$BZ  SDMA=$SD"
}

arm nd8    1 8;     ND8F1=$F1; ND8F2=$F2; ND8LC=$BZ
arm dr8    0 8;     DR8F1=$F1; DR8F2=$F2; DR8LC=$BZ
arm nd4000 1 4000;  NDF1=$F1;  NDF2=$F2;  NDLC=$BZ
arm dr4000 0 4000;  DRF1=$F1;  DRF2=$F2;  DRLC=$BZ

# ==================================================================
# THE LAST TWO ARMS (S4 fix round 2, review I-2): the SPEC'S F2, MADE TO FIRE.
# ==================================================================
# The four arms above prove the two DISPATCH holds.  They say NOTHING about
# the spec's F2 proper — "a transfer at the head of the DMA queue waits while
# a compute command holds its slot" (rtl/layer_chan.sv:114-115; `hd_f2` at
# rtl/layer_chan.sv:2086-2095 gating the start arm at rtl/layer_chan.sv:2151)
# — which the census counts SEPARATELY as F2 FENCE and which reads 0 on every
# arm above and on both model runs.  A counter that has never been seen to
# fire is not a measurement, and this script's own standard is stated at its
# head, so this arm makes it fire.
#
# WHY THE SHIPPED SCHEDULE NEVER FENCES — a property of the EMITTER *and* of
# the four-deep transfer QUEUE, not of the fence.  THREE legs, all needed:
#
# (a) gen_model_script DOUBLE-BUFFERS: each group of state transfers targets
#     ONE cache slot and the compute that IMMEDIATELY follows runs on the
#     OTHER (`C e 800 / C e 801 / C d 804 / C d 805` all name KV slot 0, then
#     `L 00000008` puts the KVAP/ATTN block that follows on KV slot 1), and
#     hd_f2 needs the HEAD transfer's slot to be the slot the RUNNING compute
#     command owns.
# (b) the LAYER DOES come back to a group's slot later, and leg (a) alone
#     would therefore be too strong: the shipped model stream holds 240 cases
#     of an SST to KV slot s followed 18-20 records later by a KVAP/ATTN on
#     that same s, out of 960 store/compute coincidences.  What keeps the
#     fence unarmed across all 960 is the QUEUE — the MINIMUM number of
#     transfers enqueued between the SST and the compute command is exactly
#     4, dq is FOUR deep and in order, and a fifth record is HELD at dispatch
#     rather than dropped (rtl/layer_chan.sv:1448-1457), so such a store has
#     always been popped before that command dispatches and cannot be at the
#     head.  The 240 and the 4 are the S4 round-3 REVIEW's derivation from a
#     scan of the emitted stream (scripts/w9/model_9b_s1.txt, relative to
#     tb/, .gitignore'd and regenerable), re-derived read-only in fix round
#     3.  They are a property of the schedule; NO log carries them.
# (c) what CAN still be at the head is that group's LOADS to the slot, and
#     those raise F1 first: F1 holds the command at dispatch with `cmd_pend`
#     set, and `cmp_holds = busy_cmp && !cmd_pend` (rtl/layer_chan.sv:2067)
#     is therefore LOW, so a queued transfer has nothing to be held against —
#     which is exactly the no-deadlock argument at
#     rtl/layer_chan.sv:2060-2065.  F1 shadows F2 by construction.
#
# THE PERTURBATION — TWO records of the KV group at
# scripts/w9/lay9b_s1.txt:435903-435906, in the shape of S2's case 6
# (tb/tb_layer_sdma.sv:765-801, "an SST queued behind a long SLD, with a CONV
# holding the SST's slot"):
#
#     C e 800 0 0   ->   C d 1400 0 0     the LONG transfer that goes AHEAD
#     C e 801 0 0   ->   C e c01 0 0      the STORE the compute must fence
#
# (1) the KV store of head 0 becomes an SLD OF A CONV BLOCK INTO CV SLOT 1 —
#     8192 rows, 2048 beats, ~12,000 cycles measured, on a kind and a slot
#     NOTHING else in this script touches, so it cannot stall or corrupt a
#     compute command; it exists only to occupy the DMA lane;
# (2) the KV store of head 1 is retargeted from slot 0 to KV SLOT 1 — the
#     slot the KVAP/ATTN block after `L 00000008` owns.  Being a STORE it
#     does not raise `sld_pend`, so the block is NOT held by F1
#     (rtl/layer_chan.sv:1356-1364); being BEHIND the long load it is still
#     QUEUED when the block claims the slot, and it reaches the HEAD while a
#     KVAP/ATTN owns KV slot 1.  That is F2, holding a real transfer.
#
# WHY TWO RECORDS AND NOT ONE, and the arm that shows it.  Retargeting the
# store ALONE does not arm the fence, because a KV transfer of this 1-layer
# smoke moves AT MOST ONE row -- the arms' own DDR counters say the six KV
# LOADS read 0 beats (f2half's r=55296 is the DN and CV loads alone) and each
# of the two KV STORES writes 5 (four row beats + one exponent beat) -- and is
# therefore SHORTER than the census's own dispatch path (five AXI-Lite ops):
# the store reaches the head while the engine is still between commands,
# starts, completes, and COOLS the slot (rtl/layer_chan.sv:2173), so the
# KVAP that follows is refused E_DMA_COLD instead of fencing it.  The
# `f2half` arm below IS that one-record perturbation and reports the counter
# it leaves — it is printed, not asserted, because its 0 is a timing outcome
# and not a structural guarantee.  Both arms run at the SHIPPING LAT 8: no
# latency knob is needed, because the transfer that has to still be moving is
# a whole conv block and is long by construction, not by latency.
#
# NEITHER ARM IS A CORRECTNESS RUN AND NEITHER PRETENDS TO BE.  The
# perturbation drops one KV STORE (`C e 800 0 0` is an SST, op 14, not a
# load), stores the wrong slot's rows over head 1,
# and cools KV slot 1 when that store finally completes, so a command behind
# it is refused E_DMA_COLD.  Both scripts are therefore TRUNCATED with a `Q`
# 15 commands past the perturbation — before any R/E/A record can read
# anything the perturbation touched — and this arm's PASS criterion is
# F2 FENCE > 0 ALONE.  A non-zero rc and refused commands are EXPECTED, are
# printed, and do not fail the arm; the census TABLE is written before the
# TB's $fatal (the report is emitted at the end of the replay, and the TB's
# hard stop is 20 errors), so the counter is read from the table either way.
#
# $1 = cfg, $2 = 1 to apply the RETARGET ONLY (the f2half control)
arm_perturbed () {
  local cfg=$1 half=$2 rc t0 t1 src ptxt pbin ft
  src=$ROOT/tb/$SCRIPT
  ptxt=$ROOT/tb/scripts/w9/lay9b_s1_$cfg.txt
  pbin=$ROOT/tb/scripts/w9/lay9b_s1_$cfg.state.bin
  echo
  if [ "$half" = 1 ]; then
    echo "=== arm $cfg: NODRAIN=1 LAT=$F2LAT, the RETARGET ALONE (one record)"
  else
    echo "=== arm $cfg: NODRAIN=1 LAT=$F2LAT, the PERTURBED schedule (two records)"
  fi
  # The copy is written FROM the committed script; the committed script is
  # never edited.  awk, so the 4.3 MB file streams.
  awk -v half="$half" '
    !a && $0 == "C e 800 0 0" {
      if (half == 0) { print "C d 1400 0 0" } else { print }
      a = 1; next
    }
    a && !b && $0 == "C e 801 0 0" { print "C e c01 0 0"; b = 1; next }
    b && $1 == "C" { n++; print; if (n == 15) { print "Q"; ok = 1; exit } next }
    { print }
    END { if (!a || !b) exit 3; if (!ok) exit 4 }
  ' "$src" > "$ptxt"
  rc=$?
  [ "$rc" = 0 ] || { echo "    FAIL: could not build $ptxt (awk rc $rc)"; FAIL=1; }
  # the generated script must carry the perturbation and stop where this arm
  # says it stops, or the arm is measuring something it has not described.
  if [ "$(grep -c '^C e c01 0 0$' "$ptxt")" != 1 ] \
     || [ "$(tail -n 1 "$ptxt")" != "Q" ] \
     || { [ "$half" = 0 ] && [ "$(grep -c '^C d 1400 0 0$' "$ptxt")" != 1 ]; }; then
    echo "    FAIL: $ptxt is not the script this arm describes"; FAIL=1
  fi
  echo "    the perturbed tail, VERBATIM (the changed records and all that follows):"
  tail -n 20 "$ptxt" | sed 's/^/      /'
  # the state image is the smoke's OWN; the symlink exists only because
  # run_s4_census.sh derives +state= from the script's path prefix.
  ln -sfn lay9b_s1.state.bin "$pbin"
  t0=$(date +%s)
  NODRAIN=1 LAT=$F2LAT JOBS="${JOBS:-12}" bash "$RUN" "$cfg" \
    "scripts/w9/lay9b_s1_$cfg.txt" > "$TMP/$cfg.out" 2>&1
  rc=$?
  t1=$(date +%s)
  # NOTE (S4 fix round 3, review m8): this grep deliberately still does NOT
  # include `FAIL [REA]`, so the "no R/E/A check failed" negative is DERIVED
  # from `errors` == the FAIL cmd count rather than SHOWN -- S4_REPLAY.md
  # section 5.5.6 states the derivation.  Adding the alternation is a one-word
  # change and it would be UNEXERCISED until this control next runs; round 3
  # was documentation-only and re-ran nothing, so it was not made blind.
  grep -E "TB_LAYER_CENSUS|LAYER_CENSUS (dispatch|state_region|commands|steps)|FAIL cmd" \
    "$TMP/$cfg.out" | sed 's/^/    /'
  echo "    rc=$rc  wall=$((t1 - t0))s   — a NON-ZERO rc and refused commands are"
  echo "    EXPECTED here and are NOT a failure of this arm (see the header above)"
  ft=$ROOT/evidence/qwen9b/s4/census_$cfg.txt
  if [ -s "$ft" ]; then
    FFF=$(val "$ft" TOTAL_F2_FENCE_CYCLES)
    FF1=$(val "$ft" TOTAL_F1_HOLD_CYCLES)
    FF2=$(val "$ft" TOTAL_F2_HOLD_CYCLES)
    FBZ=$(val "$ft" TOTAL_BUSY_CYCLES)
    FSD=$(val "$ft" TOTAL_SDMA_CYCLES)
    echo "    F1_HOLD=$FF1  F2_HOLD=$FF2  F2_FENCE=$FFF  LCYC=$FBZ  SDMA=$FSD"
  else
    echo "    FAIL: no census table at $ft — the counter could not be read"
    FAIL=1; FFF=; FF1=; FF2=
  fi
}

arm_perturbed f2half  1; HALFFF=${FFF:-}
arm_perturbed f2fence 0

echo
echo "=== the verdicts"

# --- RED: the counter fires
if [ "${NDF1:-0}" -gt 0 ]; then
  echo "    ok   RED: the F1 hold counter FIRED at LAT 4000 under +nodrain ($NDF1 cycles)"
else
  echo "    FAIL RED: the F1 hold counter is '$NDF1' at LAT 4000 — NOT PROVEN"; FAIL=1
fi

# --- NEGATIVE: the draining mode cannot produce a hold, at either latency
for a in "LAT 8:$DR8F1:$DR8F2" "LAT 4000:$DRF1:$DRF2"; do
  lab=${a%%:*}; rest=${a#*:}; f1=${rest%%:*}; f2=${rest#*:}
  if [ "${f1:-1}" = 0 ] && [ "${f2:-1}" = 0 ]; then
    echo "    ok   NEGATIVE ARM: the DRAINING mode at $lab reports 0 / 0"
  else
    echo "    FAIL NEGATIVE ARM: the draining mode at $lab reported F1=$f1 F2=$f2, which the drain makes impossible"
    FAIL=1
  fi
done

# --- IDENTITY: the holds account for the WHOLE difference between the modes
idc () {  # $1 = label, $2 = nodrain LCYC, $3 = F1, $4 = F2, $5 = draining LCYC
  if [ -z "${2:-}" ] || [ -z "${5:-}" ]; then
    echo "    FAIL IDENTITY at $1: a counter is missing"; FAIL=1; return; fi
  d=$(( $2 - $3 - $4 ))
  if [ "$d" = "$5" ]; then
    echo "    ok   IDENTITY at $1: LCYC $2 - F1 $3 - F2 $4 = $d = the draining LCYC"
  else
    echo "    FAIL IDENTITY at $1: LCYC $2 - F1 $3 - F2 $4 = $d, draining LCYC is $5"
    FAIL=1
  fi
}
idc "LAT 8"    "${ND8LC:-}" "${ND8F1:-0}" "${ND8F2:-0}" "${DR8LC:-}"
idc "LAT 4000" "${NDLC:-}"  "${NDF1:-0}"  "${NDF2:-0}"  "${DRLC:-}"

# --- RED-F2FENCE: the THIRD counter fires, on the perturbed schedule
if [ "${FFF:-0}" -gt 0 ]; then
  echo "    ok   RED-F2FENCE: the SPEC'S F2 fence FIRED — $FFF cycles with the"
  echo "         DMA queue's head held by a compute command that owned its slot"
  echo "         (the other two counters on the same arm: F1 $FF1, F2 hold $FF2)"
else
  echo "    FAIL RED-F2FENCE: the F2 FENCE counter is '${FFF:-}' on the perturbed"
  echo "         schedule — NOT PROVEN"
  FAIL=1
fi
echo "    note the one-record arm f2half reports F2 FENCE = '${HALFFF:-}' — the"
echo "         retarget ALONE does not arm the fence, which is why the perturbation"
echo "         changes a second record (printed, not asserted: this 0 is a timing"
echo "         outcome, not a structural guarantee like the draining arms')"

echo
if [ "$FAIL" = 0 ]; then
  echo "CENSUS_NODRAIN_RED: PASS — the fence-hold counters fire under"
  echo "  back-to-back dispatch at a latency the schedule cannot hide, read"
  echo "  zero when the drain makes a hold impossible, account to the CYCLE"
  echo "  for the whole difference between the two dispatch modes, every"
  echo "  measuring arm stayed bit-exact, and the SPEC'S F2 fence — which the"
  echo "  shipped schedule's double-buffering never arms — HOLDS a transfer"
  echo "  when two records of that schedule are perturbed into case 6's shape"
  exit 0
fi
echo "CENSUS_NODRAIN_RED: FAIL"
exit 1
