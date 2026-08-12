# Rung 1b — 4-channel weight-split sequencer stream (FROZEN spec, 2026-08-09)

Goal: sequencer drives all 4 matvec_chans concurrently (row-split each
matvec) -> ~12 tok/s. NO RTL, NO rebuild — build_030 (9e1e0ba, on the
board) already has 4 matvec_chans, seq_0 masters reaching mvchan_0..3 +
ddr4_0..3, no-wait MVGO (target[0]), and FENCE-drain-all-4 (commit
b060156, ancestor of the bitstream). Template: sw/tok_meter.py --four-chan
(proven host-side, 12.23 tok/s measured).

## Per-matvec 4-chan record sequence (emit once per matvec)
```
MOVX c (x8_addr, n_in)  for c in 0..3          # same x8 into each engine XWIN
parts = split_rows(nrows, 4)                    # tok_meter.py:77 (first rem chans +1)
for j in range(max chunks over channels):       # res_chunks per channel, tok_meter:94
    for c in active(j): MVGO c NO-WAIT (WBASE=base+row*stride, BEATS, SHAPE(rc))
    FENCE                                        # drains all pending channels
    for c in active(j): [XOP] MOVY c (dst=dst_base+row, nrows=rc) [CMD]
```
- WBASE stays CHANNEL-LOCAL (base+row*stride, NO c*CH_STRIDE) — each
  matvec_chan/m_axi sees its channel at 0.
- Each channel's MOVY writes its rows to dst_base+row -> reproduces the
  identical contiguous scratch image the downstream layer command reads.
- DROP zero-count channels (never emit MVGO with 0 rows) — tok_meter's
  `if n>0` filter; handles nrows%4!=0 and nrows<4.
- Dequant recipe (sub/p0/e_x/ka/mode) is per-matvec UNIFORM -> one recipe
  for all 4 MOVYs. Review the ka/XOP coupling when re-partitioning
  chunking by channel instead of by .txt W32/ALU boundary.

## Files (investigation-confirmed)
- ref/seq_format.py — THE work (medium). SeqEmitter drives its OWN row
  partition (split_rows/res_chunks over nch) instead of mirroring .txt
  chunk boundaries; MOVX x nch; no-wait MVGO x active + 1 FENCE + MOVY x
  active per chunk-index; record nch in meta. nch from SEQ_NCH env
  (default 1 = current byte-identical behavior — PROVE it).
- ref/seq_model.py — NONE (already models 4 chan + no-wait + FENCE).
- sw/seq_run.py — small/med. plan_ddr: relax meta["chan"]==chan single
  assert. upload: write each matrix's row-quarter to c*CH_STRIDE +
  wbase_of[wid] + off for c in 0..3 (port tok_meter:264-285). relocate/
  check_* unchanged (channel-local). Add --four-chan / nch flag.
- tb/tb_seq_chip.sv + Makefile — trivial: build CHIP_NMV=4 (already
  -GNMV param); same wimg into 4 chans is a harmless superset.
- tb/scripts/gen_seq_chip_vectors.py — none (regen golden from new .seq).

## Gates
1. seq_model --gate on the 4-chan stream (tok2_s1 + model_v2_s1):
   bit-exact final state + IDENTICAL tokens vs the 1-chan/.txt flow.
2. tb_seq_chip CHIP_NMV=4 on the 4-chan tok2_s1 stream: real seq_unit/
   seq_movers (build_030 RTL) driving 4 real matvec_chans — exercises
   no-wait MVGO + FENCE-drain-4 + per-channel CSR path. SEQ-driven ==
   golden.
3. Backward compat: nch=1 default regenerates byte-identical .seq
   (chain_s1/token24_s1 hashes) and re-passes existing gates.
4. HW (me, no rebuild): seq_run.py --four-chan model_v2_s1.e on
   build_030 -> tokens bit-exact + tok/s vs ~12 target. Gate doc.
```
