# Stage 5 increment ④: measured tok/s vs the bandwidth-ceiling prediction

Date: 2026-07-26. Board: SQRL BCU-1525 (xcvu9p) on snoke, JTAG volatile.
Bitstream: build_026_rr_AltSpreadLogic_medium (netlist 07ffc7b9, VERSION
CSR 0x07ffc7b9, CALIB=0xF) — **the same programming as the ①/②/③ gates,
no reprogram**. Workload: `tb/scripts/model_s1.txt` — the real
Qwen3.5-0.8B, 24 layers, 4-token prefill + 3 autoregressive tokens, full
248,320-row LM head. Tool: `sw/tok_meter.py` (device counters, no
on-chip sequencer — user-confirmed scope).

Reports: `tokmeter_1chan_build026.json`, `tokmeter_4chan_build026.json`
(2 runs each, 0 errors, 5,789,550 checks per run — the same check count
the increment-③ gate ran).

## 1. Predicted ceiling, recomputed from the real workload

The charter/PLAN figure was **~195 tok/s** = 58.7 GB/s aggregate DDR read
(stage-2 measured) over an assumed ~0.3 GB/token. The real model streams
more than that, and now we know exactly how much:

| quantity | value | source |
|---|---|---|
| streamed bytes/token | **417,435,648 B = 0.417436 GB** | 187 weight images, each read exactly once per token |
| aggregate DDR read BW (stage 2) | 58.7 GB/s (4 x 14.67) | evidence/stage2/STAGE2_GATE.md |
| **recomputed ceiling** | **140.6 tok/s** | 58.7 / 0.417436 |
| absolute DDR pin-rate ceiling | 184.1 tok/s | 4 x 19.21 GB/s / 0.417436 |

The LM head is the single largest term: 143,032,320 B = **34.3%** of the
per-token stream (248,320 rows x 576 B), the rest being 186 images across
18 DeltaNet + 6 GQA layers.

## 2. Measured — device counters

`t_matvec` = matvec_chan PERF_CYC @ ui_clk 300.12 MHz, summed over the
187 V records of a token (4-chan: **max over the 4 channels** per chunk
index, i.e. a sequencer that starts all four in the same cycle; the
host's ~1.5 us/channel MMIO doorbell skew is deliberately not charged).
`t_layer` = layer_chan LCYC @ aclk 250 MHz, read-and-differenced around
every one of the 3,395 C records of a token. Both are pure busy time —
host stalls are structurally excluded.

| mode | t_matvec/tok | aggregate DDR | t_layer/tok | device ms/tok | **device tok/s** | wall tok/s |
|---|---|---|---|---|---|---|
| 1 channel | 40.93 ms | 10.20 GB/s | 71.58 ms | 112.50 | **8.89** | 0.191 |
| 4 channels (row-split) | 10.16 ms | 41.08 GB/s | 71.58 ms | 81.74 | **12.23** | 0.183 |

Run-to-run repeatability: identical to 4 significant figures (8.889 /
8.889 and 12.234 / 12.234 across 2 runs each) — these are hardware
counters, not sampled timings.

4-chan matvec scaling is **4.03x** with zero measurable contention
(each engine owns its own DDR4 channel). The 4-chan number is the one
comparable to the aggregate-bandwidth prediction:

> **12.23 tok/s measured vs 140.6 tok/s predicted — 11.5x short, and
> the shortfall is NOT bandwidth.**

## 3. Where the time actually goes

**87.6% of 4-chan device time is layer_chan, not weight streaming.**
Even with an infinitely fast matvec, 1 / 71.58 ms = **13.97 tok/s** is a
hard ceiling on this RTL. Per-token layer_chan busy profile (identical
in both modes; LCYC deltas by opcode):

| op | cmds/token | ms/token | % |
|---|---|---|---|
| ALU | 1,893 | 52.30 | 73.1 |
| VN (RMSNorm) | 973 | 12.34 | 17.2 |
| DNST | 288 | 3.41 | 4.8 |
| CONV | 18 | 1.77 | 2.5 |
| VNW / ROPE / ATTN / KVAP / GATE / ROPET | 223 | 1.75 | 2.4 |

`vec_alu` is a strictly serial 1-element-at-a-time unit. Static analysis
of the script says a token needs **1,251,392 ALU element-ops**; 52.30 ms
x 250 MHz / 1,251,392 = **10.4 cycles/element** average (the LCYC smoke
test below pins AMAX32 at exactly 6.0). VN costs 17.5 cycles/element
over 176,128 elements. Roughly 40% of the ALU work is the LM head
(248,320 SHIFT32 + 248,320 AMAX32 elements).

### Bonus: the matvec engine's real cost model (and a stage-2 correction)

A 2-parameter least-squares fit over the 9 distinct image shapes in the
1-chan run reproduces every measurement to <0.5% (except the 216 tiny
16-row images, 0.5% of the bytes):

```
cycles = 0.996 * beats + 8.94 * rows          @ ui_clk 300.12 MHz
```

At 1 cycle/beat a channel would sustain 64 B x 300.12 MHz = 19.21 GB/s,
i.e. DDR4 pin rate. The ~8.9-cycle **per-row pipeline bubble** is what
actually limits it, and it is shape-dependent:

| k | bytes/row | beats/row | efficiency | measured GB/s (1 ch) |
|---|---|---|---|---|
| 1024 | 576 | 9 | 9/17.9 = 50.2% | 9.65 |
| 2048 | 1088 | 17 | 17/25.9 = 65.6% | 12.66 |
| 3584 | 1856 | 29 | 29/37.9 = 76.4% | 14.71 |

The stage-2 gate reported "14.66 GB/s = 76% of the 19.2 GB/s pin rate"
and read that as DDR4 efficiency. It is not: stage 2 used K=3584
(29-beat rows), and 29/(29+8.94) = 76.4% reproduces it exactly. **The
matvec engine, not DDR4, is the 76%.** The real model is dominated by
K=1024 rows, so it gets 50% instead — which is why the 4-chan aggregate
lands at 41.08 GB/s rather than 58.7 GB/s. Removing the per-row bubble
would take 4-chan t_matvec from 10.16 ms to ~5.4 ms/token; it would move
device tok/s from 12.23 to only 13.0, because layer_chan dominates.

## 4. Wall clock — MMIO-orchestration-bound, reported honestly

**0.183–0.191 tok/s wall** (5.2–5.5 s/token) — 67x below the 4-chan
device figure (47x below the 1-chan one). The host is the sequencer, and
every scalar crosses PCIe as a 4-byte MMIO access. Per token, over ~2.5 M
MMIO operations:

| traffic | ops/token | inherent to host orchestration? |
|---|---|---|
| W: matvec y32 -> scratch | 1,427,424 writes | yes |
| V: y32 read-back for comparison | 648,256 reads | yes (host must move the data) |
| x vectors -> XWIN | 89,344 (1-ch) / 292,864 (4-ch) writes | yes |
| R/E/A: bit-exactness checks | 316,669 reads | **no** — verification only |

Removing verification entirely (`--verify matvec`) moves wall from 0.191
to **0.216 tok/s**: only ~12% of the wall clock is the gate's checking.
The other 88% is the architecture — the host is a DMA/scheduler engine
by design (rtl/layer_chan.sv header), and at 24 layers x 3,395 commands
that design choice costs 5.3 s/token.

## 5. What an on-chip sequencer would buy — explicitly

- It closes the **entire** 0.183 -> 12.23 tok/s gap: a **67x** speedup,
  and that is its whole benefit. The device counters prove the silicon
  already does the arithmetic in 81.7 ms/token; the other 5.4 s is
  PCIe round-trips for scratch loads/stores that never leave the chip in
  a sequenced design.
- It would **not** get anywhere near the 140.6 tok/s bandwidth ceiling.
  Ceiling after sequencing = 12.2 tok/s (serial matvec+layer) or 14.0
  tok/s (perfect matvec/layer overlap, = 1/t_layer). Bandwidth is 11x
  away and irrelevant until layer_chan is fixed.
- The ordered list to actually approach 140 tok/s (arithmetic on the
  measured 4-chan budget of 10.16 ms matvec + 71.58 ms layer):
  1. **Widen vec_alu and vecnorm_unit** — 52.30 + 12.34 = 64.64 ms of
     the 71.58, i.e. 79% of 4-chan device time. They are 1-element per
     ~10-cycle serial datapaths. A 16-lane version gives 64.64/16 =
     4.04 ms; with the 6.94 ms of other opcodes unchanged, t_layer goes
     71.58 -> ~11.0 ms and device tok/s 12.2 -> **~47** (21.2 ms/token).
  2. Remove the matvec engine's ~8.9-cycle per-row bubble (row-pipelined
     accumulator flush) — 41 -> ~77 GB/s aggregate on K=1024 shapes,
     t_matvec 10.16 -> 5.43 ms, so ~47 -> **~61 tok/s** (16.4 ms).
  3. Past that the residue is the non-ALU opcodes (DNST/CONV/ATTN) and
     the remaining serial dependency; reaching 140 tok/s needs
     matvec/layer overlap on top of 1 and 2. Bandwidth is the *last*
     thing to run out.

So: increment ④'s answer is that this design is **not** bandwidth-bound.
It is scalar-ALU-bound on-chip and MMIO-bound off-chip, and the
bandwidth ceiling that motivated the 4-channel split is 11x away.

## 6. Free integrity check: beats*64 vs manifest — EXACT

Every engine run asserts `PERF_BEATS == rowcount * stride / 64`, and each
token's summed `beats * 64` is compared against the manifest's
`sum(nbeats * 64)` over its 187 V records:

```
1-chan run0/run1: 2,504,613,888 streamed == 2,504,613,888 manifest   EXACT
4-chan run0/run1: 2,504,613,888 streamed == 2,504,613,888 manifest   EXACT
```

Not one spurious or missing 64-byte beat in 4 runs (10.0 GB of DDR
reads). In 4-chan mode this also proves the row-split covers each image
exactly once: the four channels' beats sum to the single-channel total.

## 7. Mode 2 (`--four-chan`) correctness

Each weight image is row-split into 4 contiguous pieces; piece c is
DMA'd to DDR channel c **at the byte offset it would occupy in a
single-channel image** (`c*CH_STRIDE + wbase[wid] + r0*stride`), so the
engine's address math is untouched. All 4 matvec_chans are configured,
then doorbelled back-to-back, then polled; results are stitched by row.

This is exact because every output row is an independent dot product
over the full k, and the per-image shift `sh` is a whole-image constant.
Splitting is verified, not assumed: the stitched y32 is compared
bit-exact against the V record. **2 runs x 6 tokens x 187 matvecs =
2,244 stitched matvecs, 7,779,072 row comparisons, 0 mismatches.**

Chunking: rows are split in two independent stages — rows to channels
(`nrows//4`, first `nrows%4` channels take one extra row, so no
divisibility constraint is ever imposed), then each channel cuts *its
own* range by RES_DEPTH=4096. The 248,320-row LM head becomes 62,080
rows per channel = 15 chunks of 4096 + 1 of 640 on every channel (64
engine runs vs 61 for one channel), perfectly balanced. Verified as an
exact partition for nrows in {1,2,3,4,5,10,16,3584,4096,4097,6144,248320}.
Per-token engine runs: 265 (1-chan) -> 808 (4-chan); the extra runs cost
nothing measurable because the per-run overhead is the same ~8.9
cycles/row bubble already in the cost model.

## 8. LCYC smoke test (first ever use of the counter, netlist 07ffc7b9)

Write-clear, run one command whose cost is known analytically, read back.
Probe = ALU AMAX32, the only opcode that reads scratch and writes no
scratch word (it touches AMAXI/AMAXV only, which every script re-seeds
with a fresh scan) — safe on a live board.

| len | LCYC | cyc/elem | device | wall |
|---|---|---|---|---|
| (cleared) | 0 | — | — | — |
| 256 | 1,539 | 6.01 | 6.16 us | 13.5 us |
| 512 | 3,075 | 6.01 | 12.30 us | 16.6 us |
| 1024 | 6,147 | 6.00 | 24.59 us | 28.1 us |
| 2048 | 12,291 | 6.00 | 49.16 us | 52.2 us |

Exactly `6*len + 3` cycles: perfectly linear, write-clear works, and
device time is always below wall time by a constant ~3-7 us of MMIO
round-trip. The counter is trustworthy. PASS.

## 9. Honest caveats

- `t_matvec` comes from the streamer's counter, which spans start ->
  last beat. The engine's post-stream compute drain (a few tens of
  cycles per run) is not counted: <0.02% at 265-808 runs/token.
- `t_device = t_matvec + t_layer` is charged **serially**. That is
  conservative-but-correct for the dependent chain (layer math consumes
  matvec output); a sequencer could overlap across heads/chunks, which
  is why the "perfect overlap" bound (13.97 tok/s) is quoted separately.
- In this replay the on-chip pipeline consumes host-written y32 (W
  records) while the matvec engine independently recomputes the same
  products for verification (V records). The two are measured on the
  same real work but never overlap in the current topology.
- The design is timing-marginal at 250 MHz on this bitstream (axi_aclk
  WNS -0.142, Fmax 241.4 MHz — see STAGE5_INC12_GATE.md). Device times
  are quoted at the nominal 250 MHz / 300.12 MHz the counters run at.
