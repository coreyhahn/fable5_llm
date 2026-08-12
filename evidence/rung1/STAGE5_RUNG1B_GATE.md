# Stage 5 rung 1b: 4-channel weight-split sequencer — FUNCTIONAL PASS, PERF NEGATIVE

Date: 2026-08-09. Board: build_030_rr_AltSpreadLogic_medium (9e1e0bae),
NO rebuild — the 4 matvec engines + no-wait MVGO + FENCE-drain-4 were
already in the shipped bitstream. Generator/host/sim only.

## Functional result: PASS (capability proven on silicon)
The sequencer drives all 4 matvec_chans CONCURRENTLY (row-split every
matvec: MOVX x4 -> no-wait MVGO x4 -> FENCE -> MOVY x4 stitch),
verified end-to-end:
- seq_model --gate 4-chan: tok2/token24/model_v2 all checkpoints
  bit-exact, tokens IDENTICAL to 1-chan.
- tb_seq_chip CHIP_NMV=4 (real seq_unit+seq_movers + 4 real matvec_chans,
  build_030 RTL) on 4-chan tok2: PASS, 0 weight-beat miss.
- HW (seq_run.py --four-chan model_v2_s1, build_030): weights row-split
  over DDR chans [0,1,2,3], sequencer ran all 68,539 records, halted
  clean, tokens [561,314,279,369,279,6511] bit-exact, repeatable
  (evidence/rung1/seqrun_4chan_model_v2.log).
- nch=1 default is BYTE-IDENTICAL to pre-rung-1b (4 streams hash-proven);
  all prior gates unaffected.

## Performance result: 15% SLOWER, not faster (the honest finding)
- 1-chan: 1220.0 ms device / 60,495 records (rung 1)
- 4-chan: 1404.1 ms device / 68,539 records  => +15% device, REGRESSION

Root cause (corrects the ladder's rung-1b assumption):
1. Matvec is only ~36% of device time (tok_meter/STAGE5 analysis); the
   other ~64% is layer_chan ALU/VN and is untouched by channel-splitting
   matvecs. Amdahl caps any matvec-parallel win at ~1.37x even ideally.
2. The DOMINANT matvec — the 248,320-row LM head — CANNOT parallelize
   here: the on-chip AMAX32 argmax needs a sequential row scan for its
   running index, so the head runs channel-sequentially by construction
   (Agent A's correctness requirement; tokens-identical confirms it).
   tok_meter got its 1.38x precisely because it does argmax on the HOST
   and parallelizes the head; the autonomous on-chip loop cannot.
3. 4-chan overhead is real and negative: MOVX broadcasts x8 to each
   engine's private XWIN (4x the activation movement) and the stream
   grows +13% records, each with fetch/decode/issue cost. This exceeds
   the small-layer-matvec parallel savings.

## Disposition
- 4-chan capability RETAINED (correct, gated, default OFF / nch=1). It
  would help a matvec-heavier config, and becomes a real win once an RTL
  "sticky argmax index-base + 4-way argmax combine" lets the LM head
  parallelize (Agent A flagged this) — an RTL item, not no-RTL rung 1b.
- The real decode speedup is RUNG 2: parallelize layer_chan ALU/VN (the
  64%). This finding redirects effort there (docs/SPEEDUP_LADDER.md).
