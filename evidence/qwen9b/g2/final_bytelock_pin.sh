#!/usr/bin/env bash
# final_bytelock_pin.sh — G2b's PIN on the 0.8B and 2B artifact sets.
#
# WHAT THIS IS, AND WHY IT IS NOT rd_golden_shas.sh.
#
#   evidence/qwen2b/rd/rd_golden_shas.sh carries NO expected values and makes
#   NO comparison: it `ls`es and `sha256sum`s three `.chip` goldens and exits 0
#   on any tree, so "passing" it means nothing.  It is a RECORDING, not a gate
#   — the distinction evidence/qwen_next/ladder/LADDER.md:618 already draws
#   when it reports t4_bytes_unmoved.sh as PASS and rd_golden_shas.sh as
#   merely "rc 0".  That recording is exactly what G2b needs as an INPUT.
#
#   This script is the other half.  It carries the expected sha256 of every
#   artifact in the frozen 0.8B and 2B chains, compares, and EXITS NON-ZERO on
#   any mismatch.  The expected values are what make it a pin: a future run is
#   a pass/fail comparison against the bytes build_034 and build_035 were
#   built from, not a fresh recording of whatever happens to be on disk.
#
# WHAT IT PINS.  Every artifact below is .gitignored (.gitignore:23 covers
# tb/scripts/w4/, :27 covers tb/scripts/w5/), so these hashes are the ONLY
# in-repo record of the bytes.  Three groups:
#
#   A  the frozen 0.8B chain          -> build_034_po2_AltSpreadLogic_high
#   B  the 2B W8 chain                -> build_035_fp2a_exc_po (resident)
#   C  the 2B 1-layer W8 gold that    -> the reference half of
#      evidence/qwen2b/rc/t4_bytes_unmoved.sh compares against, 4 seeds
#
#   Group C is here because the byte-lock is only as good as its own gold: if
#   tb/scripts/w5/lay2b_w8_s*.* were to move, t4_bytes_unmoved.sh would keep
#   printing PASS against the moved bytes and nothing would notice.
#
#   The three `.chip` goldens rd_golden_shas.sh records are already rows of A
#   and B — model_v2_s1.e.chip, model_v2_s1.e4.chip and model_w8_2b_s1.e.chip,
#   the `.e.chip`/`.e4.chip` rows below.  They are pinned here and recorded
#   there, and their expected values agree with
#   evidence/qwen2b/rd/hw_47_golden_shas.log to the digit.
#
# AFTER G3 THIS STILL WORKS, and that is the point.  The migration's ISA
# re-encoding retires evidence/qwen2b/rc/t4_bytes_unmoved.sh — the emitted ARG
# words change at every geometry, so REGENERATION stops reproducing these
# bytes.  Nothing regenerates the artifacts named here; they are on disk and
# this script hashes them where they lie.  A FAIL after G3 therefore means the
# files were touched, moved or lost, NOT that the emitter drifted.
#
# USAGE
#   bash evidence/qwen9b/g2/final_bytelock_pin.sh              # the gate
#   bash evidence/qwen9b/g2/final_bytelock_pin.sh --emit       # print a table
#   bash evidence/qwen9b/g2/final_bytelock_pin.sh --selftest   # neg. control
#
# --emit prints the table in the embedded format so a deliberate re-pin is
# mechanical.  It is NOT a refresh button: these values are the provenance of
# two frozen bitstreams' inputs, and re-emitting them over a mismatch would
# destroy the only record there is.  See FINAL_BYTELOCK.md before using it.
#
# Run on snoke (the artifacts live on NFS; snoke is the campaign's numeric
# host).  ~6.9 GiB of sha256 — about a minute warm.
set -u
export LC_ALL=C          # glob order and sort order must not depend on locale
cd "$(dirname "$0")/../../.." || exit 2
ROOT=$PWD

W4=tb/scripts/w4/model_v2_s1
W5=tb/scripts/w5/model_w8_2b_s1

# ---------------------------------------------------------------- measure ---
# Prints "<sha256>  <key>" lines.  A missing file prints "MISSING" as its sha
# so an absent artifact fails the comparison LOUDLY instead of vanishing from
# both sides of it.
sha_of() {
  if [ -f "$1" ]; then sha256sum "$1" | cut -d' ' -f1; else echo MISSING; fi
}
# sha over the per-file sha lines of a glob — the form
# b9e0851:evidence/qwen2b/rd/rd_2b_artifact_shas.sh:19 established for the 187-image
# sets, with ONE deliberate change.  It covers the file NAMES as well as the
# bytes, so a renamed image is a mismatch too.
#
# THE CHANGE, and it is a finding this gate made rather than a style choice:
# b9e0851:evidence/qwen2b/rd/rd_2b_artifact_shas.sh:19 hashes the glob in SHELL ORDER
# (CLOSED 2026-09-10, #19 = triage (b)13: it pins LC_ALL=C and an explicit sort now), and shell glob
# order is LC_COLLATE-dependent.  Under the login default LANG=en_US.UTF-8 the
# names sort w0, w100, w101, … ; under LC_ALL=C they sort w0, w1, w10, w100, …
# Same 187 files, same bytes, TWO different digests — measured on snoke
# 2026-08-31, both recorded in FINAL_BYTELOCK.md §4.  RC_GATE.md:194's
# c9e6d0a6… is the en_US.UTF-8 one, and nothing in that script or that
# document says so, so the same command in a C-locale shell reads as a
# mismatch that is not one.  A pin may not have an ambient dependency, so this
# one sorts the sha lines under LC_ALL=C before digesting: the result is
# independent of the glob order and of the caller's locale both.
list_sha() {
  local n; n=$(ls $1 2>/dev/null | wc -l)
  if [ "$n" = 0 ]; then echo "MISSING(0)"; return; fi
  echo "$(sha256sum $1 | LC_ALL=C sort | sha256sum | cut -d' ' -f1)(n=$n)"
}

measure() {
  echo "# A — frozen 0.8B chain (build_034_po2_AltSpreadLogic_high)"
  for f in e.seq e.seq.json e.seqdata.bin e.chip \
           e4.seq e4.seq.json e4.seqdata.bin e4.chip \
           txt emb.bin weights.json wimg.bin; do
    echo "$(sha_of $W4.$f)  $W4.$f"
  done
  echo "$(list_sha "${W4}_w*.bin")  ${W4}_w[N].bin"
  echo "$(sha_of tb/scripts/model_v2_s1.txt)  tb/scripts/model_v2_s1.txt"
  echo "# B — 2B W8 chain (build_035_fp2a_exc_po, the resident bitstream)"
  for f in e.seq e.seq.json e.seqdata.bin e.chip txt emb.bin weights.json \
           wimg0.bin wimg1.bin wimg2.bin wimg3.bin; do
    echo "$(sha_of $W5.$f)  $W5.$f"
  done
  echo "$(list_sha "${W5}_w*.bin")  ${W5}_w[N].bin"
  echo "# C — the byte-lock's own gold, 4 seeds (t4_bytes_unmoved.sh:21)"
  for s in 1 2 3 4; do
    L=tb/scripts/w5/lay2b_w8_s$s
    for f in txt e.seq e.seq.json e.seqdata.bin e.chip weights.json; do
      echo "$(sha_of $L.$f)  $L.$f"
    done
    echo "$(list_sha "${L}_w*.bin")  ${L}_w[N].bin"
  done
}

# --------------------------------------------------------------- expected ---
# Measured on snoke 2026-08-31 at tree c9d2a2f (clean), the commit G2a closed
# on.  Cross-lock: the first row below is ref/scripts/regen_gate.sh:5's
# GOLD_SEQ_SHA, so the pin and the regen gate agree on the 0.8B .e.seq
# independently of each other.
expected() {
cat <<'EXPECT'
# A — frozen 0.8B chain (build_034_po2_AltSpreadLogic_high)
a69864d25b6b129a4d6c74b3c78dfcbedf1edce219d32cc05d05bc54f444aaf1  tb/scripts/w4/model_v2_s1.e.seq
bc6869ba1179788c71f97922404f0a34e35b675e1d7ea2421473910a7055069d  tb/scripts/w4/model_v2_s1.e.seq.json
13bc65821b18194b7672c366894b2c2cd4ad6e2e966f12738b6d2faeeafcb6fb  tb/scripts/w4/model_v2_s1.e.seqdata.bin
7207d57bae31a7f99358f4d1b443d629ce42e610aaa046a9988ef5246189c1ec  tb/scripts/w4/model_v2_s1.e.chip
e102e2df0835097d0d622cd17109b9cbfea1ab4e78818bcddf3873ec6d8ac933  tb/scripts/w4/model_v2_s1.e4.seq
745456c8f2eb1ccb6942e7245a61a9b5a7f5a2948c756f3fec0a56cca1fd8aed  tb/scripts/w4/model_v2_s1.e4.seq.json
13bc65821b18194b7672c366894b2c2cd4ad6e2e966f12738b6d2faeeafcb6fb  tb/scripts/w4/model_v2_s1.e4.seqdata.bin
e5436b72e93c3ada85653060ca0ddf571a7b4f0a3a3d8504ab2db78bace2cdf3  tb/scripts/w4/model_v2_s1.e4.chip
57be703747c9f95dc28e8ab8c4dd98c9b495e727ac752c454cfb67ed964c0936  tb/scripts/w4/model_v2_s1.txt
973c94bdad73163775425bba017edd93e9fea4e268ef96ef222b5c53eca61453  tb/scripts/w4/model_v2_s1.emb.bin
087f0a0115c9951e8e14812f73de93e51c2526975548211f2a0543724fbd6aa9  tb/scripts/w4/model_v2_s1.weights.json
31fde284d61580d62b4aa0fc4b197b0d6f980b569e0fb7b421248efa53b764ee  tb/scripts/w4/model_v2_s1.wimg.bin
38234398cd217d8e5e64dae9f6b9fcfa2f1f6a63cc7a3f8cd27513ee570838d2(n=187)  tb/scripts/w4/model_v2_s1_w[N].bin
57be703747c9f95dc28e8ab8c4dd98c9b495e727ac752c454cfb67ed964c0936  tb/scripts/model_v2_s1.txt
# B — 2B W8 chain (build_035_fp2a_exc_po, the resident bitstream)
fa8d9349cf1d0aa618ab79e0a2565dd89adbb147b665cb49b582d83c95b05bcb  tb/scripts/w5/model_w8_2b_s1.e.seq
998ab2604d4ed44f396a78c292a3ddb40aaaf3244968e2f8b4b4ab58cb4cead8  tb/scripts/w5/model_w8_2b_s1.e.seq.json
e8d536ee95880ff399ff25ebad13b851486ea51cb32b6dd216125b6e87f8fc28  tb/scripts/w5/model_w8_2b_s1.e.seqdata.bin
15c39f54f75adcc3252d9fbfc35a91b3a8cda79fcb13a5a20fd0fa9711dd3fed  tb/scripts/w5/model_w8_2b_s1.e.chip
be2180584ce3ca8a03d8edb4c36bc31b9daa5333eb6cfb5cba90084b331c1255  tb/scripts/w5/model_w8_2b_s1.txt
b54db7a9fa6ba97fda253b00c7ed9a4a0afe7ba43b93b9b85c2aa3876963d3aa  tb/scripts/w5/model_w8_2b_s1.emb.bin
f4eb9b25cb07f357127272edbdf7b4f2b1471eb4ebd137729cb0bee117c672c3  tb/scripts/w5/model_w8_2b_s1.weights.json
d765e255ee0b9afde760a6c4d73b58793d4f0552f9d076a5b5a5632453b29c0b  tb/scripts/w5/model_w8_2b_s1.wimg0.bin
3ad2ff0aca12d352df094b5d3296b57733205280d88fb634b00d52d117c38779  tb/scripts/w5/model_w8_2b_s1.wimg1.bin
ce7d1b84e7a46545d468b26ec05f2b0b24b4c4a01c8895e1983b4697987bdd39  tb/scripts/w5/model_w8_2b_s1.wimg2.bin
f5bb0c7e69304bf9bc960260613265875cc5d1b7d6e0c7fc53653555410cd62a  tb/scripts/w5/model_w8_2b_s1.wimg3.bin
823396ccd46144e17f0f5401ad3143c984c0478277297f4b6da171c93d2cacaa(n=187)  tb/scripts/w5/model_w8_2b_s1_w[N].bin
# C — the byte-lock's own gold, 4 seeds (t4_bytes_unmoved.sh:21)
d416c57b7b37b2d6615d22481dde5213ad5fbe12d537bdeb5fe915196d07a556  tb/scripts/w5/lay2b_w8_s1.txt
0cad08f32ff22f0a1e0c5f0bf14aae8d8f9539ab9967d2d404180f939f7ddee1  tb/scripts/w5/lay2b_w8_s1.e.seq
6270ec0f948ca144fd905d425eb50e4470c959d9adb5945392d2f58a4f626998  tb/scripts/w5/lay2b_w8_s1.e.seq.json
91affc691347eb66dd2c5e8770ea30226bae5d38c71c98657b5a8a010fa04229  tb/scripts/w5/lay2b_w8_s1.e.seqdata.bin
2cbc8ee699663dbfc7fca0ec9be4fab9e6c88e1f669d13e76702dce6b084d4c9  tb/scripts/w5/lay2b_w8_s1.e.chip
a883081b3928bb99ca8a4504a79e36fae16f0746a98eab5638f74b72e362e1b0  tb/scripts/w5/lay2b_w8_s1.weights.json
b96ea68e92ba0e23a6213b217c2dfb73d892c2da6a20c3d755ba5be31651e995(n=15)  tb/scripts/w5/lay2b_w8_s1_w[N].bin
9097b19089f9c3ae1ba76a2ef61ce630c314f383393bb43f8da28c74162f3216  tb/scripts/w5/lay2b_w8_s2.txt
0cad08f32ff22f0a1e0c5f0bf14aae8d8f9539ab9967d2d404180f939f7ddee1  tb/scripts/w5/lay2b_w8_s2.e.seq
9e49ec617f738c5b6021ba6ac1a2febf45aeee3f76ac9449ff58c8af87724276  tb/scripts/w5/lay2b_w8_s2.e.seq.json
3135a943906f5c44894bb91aba08b0764720826077d676adc8ad4def735871da  tb/scripts/w5/lay2b_w8_s2.e.seqdata.bin
25d183e8a4aef7096e05292e3fc5fdda4bd04b043a8d7fe08eb63282d1e371f0  tb/scripts/w5/lay2b_w8_s2.e.chip
c5f449b2119ec4404f7fc69488a963c4e9ac8ef269a75f1fa08f9987f1207238  tb/scripts/w5/lay2b_w8_s2.weights.json
8fd36fbe33ab83ea7b84aaec4cd4c24d4cfbf20b7cc380fe997ff9cb57f31b58(n=15)  tb/scripts/w5/lay2b_w8_s2_w[N].bin
8a89ea704c86080eba67572d34bd5c3cd1ce0f64e2c066709d3c0c01b0e7a542  tb/scripts/w5/lay2b_w8_s3.txt
0cad08f32ff22f0a1e0c5f0bf14aae8d8f9539ab9967d2d404180f939f7ddee1  tb/scripts/w5/lay2b_w8_s3.e.seq
ae6210d4bcf2c4bbfba992948cd943126d52bcbc856e07fcfe71b858a33d0ff1  tb/scripts/w5/lay2b_w8_s3.e.seq.json
87a288e51946a6bc9d88d2e5f5071fdee7567b318085b1c00e868dc3ecc6d01c  tb/scripts/w5/lay2b_w8_s3.e.seqdata.bin
fa1399419b3d2ffbeb8f99da8de63e81e4d59e63a4a6680648167620eed97d46  tb/scripts/w5/lay2b_w8_s3.e.chip
91a251707a4e679f0c30e66db0d6594b0158aea242e546ca4d1db718767e2c0d  tb/scripts/w5/lay2b_w8_s3.weights.json
76dbf6355ac800a759023f5a4b1e222112bd83e19d3243cf29c67eafee472d3a(n=15)  tb/scripts/w5/lay2b_w8_s3_w[N].bin
f4c165573cd13dbeb118d919b10e97a99141066a9bc0623b6a947d7d327375dd  tb/scripts/w5/lay2b_w8_s4.txt
0cad08f32ff22f0a1e0c5f0bf14aae8d8f9539ab9967d2d404180f939f7ddee1  tb/scripts/w5/lay2b_w8_s4.e.seq
c1e290a05a49ea8dc03310c56e92104bded31fb3dbfc523b5c7222494ea088f9  tb/scripts/w5/lay2b_w8_s4.e.seq.json
9a23dd34fad910959be32841276d149ab98d3082d18b99d74490e294110e91b0  tb/scripts/w5/lay2b_w8_s4.e.seqdata.bin
bdc0bd827014070e81bb48589169966b28114db06e08a17b7b762e650820b6cd  tb/scripts/w5/lay2b_w8_s4.e.chip
c5d928234683533114ac7330bce81d1d0a5f0c093c47db072b510545a565213d  tb/scripts/w5/lay2b_w8_s4.weights.json
1c1cd810e49515ddd344faf1cc8627f19f7e33fdc36a426b76892844d3671d13(n=15)  tb/scripts/w5/lay2b_w8_s4_w[N].bin
EXPECT
}

# ---------------------------------------------------------------- compare ---
# $1 (optional) = a sed expression applied to the EXPECTED table only.  The
# selftest uses it to corrupt one expected value; nothing else passes it.
compare() {
  local perturb=${1:-}
  local exp mea ok=0 bad=0 line key eSha mSha
  exp=$(expected | grep -v '^#')
  [ -n "$perturb" ] && exp=$(echo "$exp" | sed "$perturb")
  mea=$(measure | grep -v '^#')
  # every EXPECTED key must appear in MEASURED with the same sha
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    eSha=${line%% *}; key=${line##*  }
    mSha=$(echo "$mea" | awk -v k="$key" '$2==k{print $1}')
    if [ -z "$mSha" ]; then
      printf '  MISSING-KEY  %s\n' "$key"; bad=$((bad+1))
    elif [ "$mSha" = "$eSha" ]; then
      printf '  ok           %s\n' "$key"; ok=$((ok+1))
    else
      printf '  *** MISMATCH %s\n      expected %s\n      measured %s\n' \
        "$key" "$eSha" "$mSha"; bad=$((bad+1))
    fi
  done <<< "$exp"
  # and MEASURED must carry nothing EXPECTED does not name: a new artifact in
  # a pinned set is a change to the set, and silence about it is how a pin
  # rots.  (Both sides are generated from the same list today; this catches a
  # future edit that adds a row to one and not the other.)
  local ne nm
  ne=$(echo "$exp" | grep -c .); nm=$(echo "$mea" | grep -c .)
  if [ "$ne" != "$nm" ]; then
    printf '  *** ROW COUNT expected %s measured %s\n' "$ne" "$nm"
    bad=$((bad+1))
  fi
  echo
  echo "  rows ok $ok, bad $bad"
  [ "$bad" = 0 ]
}

# --------------------------------------------------------------- doc sync ---
# FINAL_BYTELOCK.md reprints this table, because the gate DOCUMENT has to be
# readable on its own — the whole point of a pin is that someone finds it
# years later.  Two copies of a table is two things that can drift, so the
# copies are tied mechanically rather than by care: the doc's copy lives
# between two HTML-comment markers in that file and must equal expected()
# exactly.  --selftest has a negative control for this check too.
DOC=evidence/qwen9b/g2/FINAL_BYTELOCK.md
doc_table() {
  sed -n '/<!-- PIN TABLE BEGIN -->/,/<!-- PIN TABLE END -->/p' "$DOC" \
    | grep -v -e 'PIN TABLE BEGIN' -e 'PIN TABLE END' -e '^```'
}
check_doc() {
  if [ ! -f "$DOC" ]; then
    echo "  *** DOC $DOC is MISSING — the pin's document is the record"
    return 1
  fi
  if diff -u <(expected) <(doc_table) > /dev/null; then
    echo "  doc table in sync with expected() ($DOC)"
    return 0
  fi
  echo "  *** DOC TABLE DRIFT — $DOC disagrees with expected():"
  diff -u <(expected) <(doc_table) | sed 's/^/      /'
  return 1
}

# -------------------------------------------------------------- crosslock ---
# A pin written from ONE measurement is only as good as that measurement.  For
# every expected sha, look for an INDEPENDENT prior committed record of the
# same value elsewhere in the repo — a lock script's gold constant, an older
# gate doc's sha table, a run log.  Anything under evidence/qwen9b/ is this
# campaign's own work and is excluded, so a hit is genuinely independent.
# Some records keep only a 16-hex prefix (the .json session dumps), so match
# on the first 16 characters.
crosslock() {
  local line sha key n first
  expected | grep -v '^#' | while IFS= read -r line; do
    sha=${line%% *}; key=${line##*  }
    sha=${sha%%(*}                       # drop the "(n=187)" suffix
    n=$(git grep -l "${sha:0:16}" -- . ':!evidence/qwen9b/' 2>/dev/null | wc -l)
    first=$(git grep -l "${sha:0:16}" -- . ':!evidence/qwen9b/' 2>/dev/null | head -1)
    if [ "$n" = 0 ]; then
      printf '  --  %-52s no prior record\n' "$key"
    else
      printf '  %2d  %-52s %s\n' "$n" "$key" "$first"
    fi
  done
}

case "${1:-}" in
  --crosslock) crosslock; exit 0 ;;
  --emit)
    echo "# emitted $(date -Is) host=$(hostname) tree=$(git rev-parse --short HEAD 2>/dev/null)$(git diff --quiet 2>/dev/null || echo '+dirty')"
    measure
    exit 0
    ;;
  --selftest)
    # NEGATIVE CONTROL.  A comparator that cannot fail proves nothing, so
    # prove it fails: corrupt ONE expected sha and require a non-zero exit
    # that names the corrupted row.  Then require the untouched run to pass,
    # so an always-failing comparator cannot score a perfect red either.
    T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
    echo "--- selftest RED: one expected sha corrupted (0.8B .e.seq) ---"
    if compare "s/^a69864d2/deadbeef/" > "$T/red" 2>&1; then
      cat "$T/red"
      echo "PIN_SELFTEST FAIL — the corrupted table still PASSED"; exit 1
    fi
    grep -E 'MISMATCH|rows ok' "$T/red"
    if ! grep -qE 'MISMATCH .*model_v2_s1\.e\.seq$' "$T/red"; then
      echo "PIN_SELFTEST FAIL — it failed, but not on the corrupted row"; exit 1
    fi
    if [ "$(grep -c MISMATCH "$T/red")" != 1 ]; then
      grep MISMATCH "$T/red"
      echo "PIN_SELFTEST FAIL — one corruption produced more than one mismatch"
      exit 1
    fi
    echo "--- selftest RED 2: the DOC's copy of the table perturbed ---"
    # Same lesson as G2a's B2: a check that cannot fire proves nothing.  The
    # doc-sync check gets its own negative control, on a temp copy — the
    # committed document is never written.
    DOC_REAL=$DOC
    sed 's/^a69864d2/deadbeef/' "$DOC_REAL" > "$T/doc.md"
    DOC=$T/doc.md
    if check_doc > "$T/docred" 2>&1; then
      cat "$T/docred"
      echo "PIN_SELFTEST FAIL — a perturbed doc table still read as in sync"
      exit 1
    fi
    head -3 "$T/docred"
    DOC=$DOC_REAL
    echo "--- selftest GREEN: the table as committed, and the doc in sync ---"
    if compare > "$T/green" 2>&1 && check_doc >> "$T/green" 2>&1; then
      grep -E 'rows ok|doc table' "$T/green"
      echo "PIN_SELFTEST PASS — CAUGHT the corrupted sha and the drifted doc,"
      echo "clean on the real table"
      exit 0
    fi
    grep -E 'MISMATCH|MISSING|ROW COUNT|DOC|rows ok' "$T/green"
    echo "PIN_SELFTEST FAIL — the real table does not pass"; exit 1
    ;;
  "")
    echo "final_bytelock_pin: $(date -Is)  host=$(hostname)"
    echo "  root  = $ROOT"
    echo "  tree  = $(git rev-parse HEAD 2>/dev/null)$(git diff --quiet 2>/dev/null || echo ' +dirty')"
    echo
    drift=0
    check_doc || drift=1
    echo
    if compare && [ "$drift" = 0 ]; then
      echo "FINAL_BYTELOCK_PIN PASS — every pinned artifact is byte-identical to"
      echo "the set build_034 and build_035 were built from."
      exit 0
    fi
    echo "FINAL_BYTELOCK_PIN FAIL — a pinned artifact MOVED, or the document"
    echo "and this script disagree about what the pin says."
    echo "Read evidence/qwen9b/g2/FINAL_BYTELOCK.md before doing anything else:"
    echo "after G3 these artifacts cannot be regenerated, so a mismatch is a"
    echo "LOSS, not a drift, and the fix is to restore the bytes."
    exit 1
    ;;
  *) echo "usage: $0 [--emit|--selftest]" >&2; exit 2 ;;
esac
