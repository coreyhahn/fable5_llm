# Rung 1: on-chip command sequencer — plan (2026-08-08)

Goal: wall time/token = device time/token (9,300 ms -> 81.7 ms, x114).
Everything the host does per token today is either (a) issuing a
COMMAND SEQUENCE that is identical every token up to a handful of
runtime values, or (b) RELAYING DATA between on-chip memories through
PCIe MMIO. The sequencer removes (a) by executing the sequence from
on-chip/DDR memory; the movers remove (b) with direct on-fabric paths.

## Why this is the speedup (the accounting)

Per decode token today (measured, infer.py + tok_meter):
- ~3.8K engine commands, each = 4-6 MMIO ops + host Python between:
  dead time ~30-50x the command's device execution.
- ~1.4M words of matvec y32 relayed engine->host->scratch, ~0.6M words
  x8 relayed scratch->host->engine, each word one MMIO op (~1.2-1.7us)
  vs ~3ns/word for an on-fabric burst.
- Device is idle 98.8% of wall time. The sequencer makes the device
  the critical path; nothing else changes — same commands, same math,
  same bit-exact results, so the whole verification ladder carries.

## The four data-dependent values (the crux)

The command stream is static EXCEPT: e_x (DYNQ8 exponent, today read
from EOUT and folded into later shift immediates), k_h + m_q15 (DN
gated-norm block-float + eps scale, today computed by the host from an
o32 readback), k_a (attn shared shift, same pattern). Plan:
1. EXPONENT REGISTER FILE (XRF, ~8 x 6-18b) in layer_chan: EOUT, DN
   k latch, attn k latch, + spares. New command-word addressing mode:
   "immediate := XRF[i] (+ signed constant)". Static stream, dynamic
   values — no on-chip arithmetic beyond add.
2. DYNQ16 vec_alu op (scoped in FIDELITY_REDESIGN Phase-1B): scan
   max|.| over int32 pairs -> k (priority encode = bf_shift by
   construction), apply shift, latch k in XRF. Covers k_h and k_a.
3. EPS-AWARE GATED NORM: vecnorm variant computing
   1/sqrt(ss/(n*2^2f) + eps) via the existing rsqrt ROM path with an
   eps addend on ss — replaces the host-computed m_q15 (op2 SCALE
   becomes a norm-internal multiply). Bit-exactness vs layer_fixed
   requires freezing the integer eps-add and ROM domain first in the
   reference (layer_fixed grows the matching mode; fidelity_check
   re-gates — expected identical or 1-LSB-class deltas to quantify).

## Blocks

- SEQ: fetch unit (command list in DDR via a dedicated AXI read
  master, or BRAM-resident per-token macro since one token ~= 3.8K x
  16B = 61 KB; DDR-resident chosen — full-model stream fits easily and
  the generator already produces it), decode, issue over the existing
  AXI-Lite fabric as a second master (arbitration with the host: host
  pauses while SEQ runs; CSR START/ABORT/STATUS).
- MOVER-X: scratch -> engine XWIN burst path (x8 vectors).
- MOVER-Y: engine RES -> dequant -> scratch (y32 -> int16 with the
  shift from command-constant + XRF e_x; the dequant is ALU-op-1 math).
- CLOCKING DECISION (project rule: ask before adding CDC): engines run
  on ui_clk x4, layer on aclk. Options: (A) movers as AXI4 masters
  through the EXISTING interconnect (it already handles the crossings;
  zero new CDC structures; each burst pays interconnect latency once
  — est. fine: ~2M words/token @ >=128b/beat ~= 4-8 ms), or
  (B) dedicated CDC FIFOs (faster, new clock-domain structures).
  PLAN ASSUMES (A); (B) only with explicit approval + evidence (A) is
  insufficient.

## Command format

Extend the script-record model: the generator (single source of truth)
emits a binary sequence alongside the .txt script. Records map 1:1:
C -> CSR-write macro, W32/V -> mover ops, A -> argmax latch + branch
(token feedback = SEQ writes the argmax into the next embed fetch),
M -> embedding row DMA (DDR -> scratch, replaces host pread). Loop
control: token counter + jump — the whole decode loop runs on-chip;
host writes prompt ids, starts, and drains generated ids from a small
FIFO CSR.

## Verification ladder (charter-standard)

1. Reference first: layer_fixed grows DYNQ16/eps-norm modes; fidelity
   re-gated (quantify any delta vs 16/24 baseline). Generator emits
   binary streams; a python "SEQ model" replays them against Mach.
2. Unit TBs: SEQ decode/issue; DYNQ16; eps-norm (4 seeds each).
3. Full-chip sim: tb gains a SEQ path replaying the binary stream;
   chain/token24/model families re-gated both host-driven (regression)
   and SEQ-driven (must be bit-identical outputs).
4. Build + timing (SEQ logic is small; movers via interconnect keep
   clock story unchanged) -> reroll spread -> HW ladder host-driven +
   SEQ-driven + infer.py --seq mode; tok_meter re-measure = the rung-1
   number (target ~12 tok/s wall).

## Estimate / risks

RTL ~3 units (SEQ, 2 movers) + XRF + vec_alu op + vecnorm mode; the
familiar build/timing cycle applies (+SEQ fanout watch item). Risks:
eps-norm bit-exactness freeze (mitigated: reference-first), AXI-Lite
arbitration corner cases (mitigated: host quiesced while SEQ active),
interconnect throughput for movers (measure early; fallback (B) needs
approval). Rough effort: the largest single RTL increment since the
banking — budget multiple sim-gated sub-steps, not one shot.
