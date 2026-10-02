#!/usr/bin/env bash
# r3_5_pin_compare.sh — Task R3-5 step 4: the regenerated r0 / r1 / r2 streams
# in tb/scripts/w9_r3regen/ (r3_5_regen.sh) against their PINS, read-only:
# the FULL sha256 of each regenerated .seq and its manifest's stream_sha256
# must equal the pin digest (r0: SV1 n32/n34/n35/n36; r1: SR4 n410-n413 /
# sr15_preflight.sh [7a]; r2: SR11b n1161-n1164 / sr15_preflight.sh [7]); the
# pinned file's own sha256 and the manifest bytes are printed beside it
# (informational).  Any difference is a STOP (reported, the pins untouched).
# Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh.
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
cd "$ROOT" || exit 1
DIR=tb/scripts/w9_r3regen
PIN=tb/scripts/w9
declare -A W
W[r0_1]=57ec3051a0d6e68ee689859bc020b44001bcce6323b8d5c78415055853bee4da
W[r0_2]=e883a016e1ee5e2bf2608b72747e6a9dbaa4e6149ee712241de1b5221ce7790b
W[r0_3]=42fa77cbdb2f1c206386e69534eded424d4b42cb6915a59bb467c6cf24cfdd63
W[r0_4]=059e0ba6820f064667bb2b80f4d2eaacb972626452c3339a1ffa2b8064674d5d
W[r1_1]=4e11a2ae6872970ecb61e2bb37524b7bd863815e47df1fb9c3af2fbb3218cb28
W[r1_2]=cc982e4f66be17cef279bf09dcbc36d1170a4347b68b90e31a51d5993b93bbd4
W[r1_3]=0f85a974ffa9aa7e9431202e9346b74073fb0ab51624bb3720edb3927946fe3b
W[r1_4]=492e0def197b635b9e64b01e2ff1637bc4f1eda4db0899961e994160274e6c95
W[r2_1]=117ed8b061d5662517d67f905ff1b5900520ba39eff680548e8af9a7efc17d19
W[r2_2]=5d0a8bdd8298ea252af063041c63bb5df654a9aa834be4acb66e8772c23c6756
W[r2_3]=e35772cc8ed3e554bd3f1fbe93e2f40a754b70e2ea98adaa94d66e71a097a70c
W[r2_4]=8b16c7b15d1f204a00bc47b3cce11f8c85dc580ee4294f069451d41155b28563
bad=0; n=0
for rtl in r0 r1 r2; do
  for k in 1 2 3 4; do
    if [ $rtl = r0 ]; then s=model_9b_s${k}_reordB; else s=model_9b_s${k}_reordB_$rtl; fi
    want=${W[${rtl}_$k]}
    g=$(sha256sum "$DIR/$s.e4.seq" | cut -d' ' -f1)
    m=$(/home/cah/.venv/bin/python -c "import json,sys;print(json.load(open(sys.argv[1]))['stream_sha256'])" "$DIR/$s.e4.seq.json")
    p=$(sha256sum "$PIN/$s.e4.seq" | cut -d' ' -f1)
    if cmp -s "$DIR/$s.e4.seq.json" "$PIN/$s.e4.seq.json"; then mj=IDENTICAL; else mj=DIFFERS; fi
    if cmp -s "$DIR/$s.e4.seqdata.bin" "$PIN/$s.e4.seqdata.bin"; then dj=IDENTICAL; else dj=DIFFERS; fi
    ok=OK
    [ "$g" = "$want" ] && [ "$m" = "$want" ] || { ok=STOP; bad=$((bad+1)); }
    n=$((n+1))
    echo "$rtl s$k $s"
    echo "    regenerated .seq  $g"
    echo "    its manifest      $m"
    echo "    pin digest        $want"
    echo "    pinned file       $p"
    echo "    manifest bytes vs the pin's: $mj; .seqdata.bin: $dj  -> $ok"
  done
done
echo "R3_5_PIN_COMPARE: $n compared, $bad differ -> $([ $bad = 0 ] && echo PASS || echo STOP)"
[ $bad = 0 ]
