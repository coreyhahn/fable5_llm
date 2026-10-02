# R-c gate 1 — W8 engine mode (V5), RTL + TB

`rtl/matvec_engine.sv` gains `cfg_w8` (SHAPE bit 29) so a 64-byte weight
beat can carry 64 INT8 weights instead of 128 packed nibbles. The wire law
is `ref/w4a8_ref.py`'s W8 section, unchanged and already self-tested; this
gate proves the RTL is bit-exact to it and that the W4 path did not move.

## The one design decision worth stating

`cfg_ng` keeps meaning **ng units = K//128 in every mode** (W8_SKETCH.md §2:
redefining it as the W8 beat count needs 96 > 63 at K = 6144). A W8 ng unit
is therefore two physical beats, and the engine spends that half-beat toggle
**in the lane array**:

* phase 0 (`g_cnt[0] == 0`) drives lanes 0..63 with the beat's 64 bytes and
  writes `acc_bank_lo`; lanes 64..127 get a zero weight.
* phase 1 drives lanes 64..127 and writes `acc_bank_hi`.

Lane k therefore always pairs with activation byte k of the *same* x line.
Stated precisely, for the cone that holds the 24 worst waived endpoints
(`xline_q0_reg[*]/CE`, −0.025, route-dominated):

* the **address path is genuinely untouched** — `x_mem` is still addressed by
  a bare flop output (`x_line`, which equals `g_cnt` beat for beat in W4).
  No mux, no added logic level in front of the LUTRAM.
* the **CE cone grew by exactly one comparator bit**. The enable is still
  `beat_fire && !is_scale_beat`, unchanged in form, but `g_cnt` went 6→7
  bits, so `is_scale_beat` / `is_last_scale` / `row_start_blocked` each
  compare one more bit (`g_cnt[6]`). That is the entire delta.
* the **operand side** of those compares (`wbeats`, `last_scale_g`) derives
  from `cfg_ng`/`cfg_w8`/`cfg_g64`, which are `csr_static_*` and false-pathed
  into `ui_clk` (`synth/constraints/fable5_cdc.xdc:14`) — quasi-static, not a
  launch point for this path.

The retire, `sc_hold`, `pd_wait`, the descriptor, the bank ping-pong and the
scale indexing are literally untouched: they still walk `cfg_ng` units and
still drive both scale operands with `m_i`.

This differs from W8_SKETCH.md §3's *prose* (walk to `2*ng`, scales at
`r_g >> 1`, `acc_bank` at `2*MAX_NG`). It is cheaper on **accumulator
storage** (half) and **retire length** (half), and decisive on the **x-cone**
axis (one comparator bit versus a whole 512-bit mux level). It is *not*
cheaper everywhere: the multiplier array stays 128 lanes of 8×8 rather than
64, i.e. 64 more 8×8 lanes than the §3 shape, and the tree is 3-4 b wider
throughout. Which shape is smaller overall is a synthesis question, still
open — see "Still owed" below. The sketch now carries a
superseded-in-part banner.

## Widths (derived, then checked against the sketch)

Derived from the real activation rail (x8 in [−128,127]) and cross-checked
against `w4a8_ref._selftest_w8`, logged at
`evidence/qwen2b/q2/v4_v5/selftest_w4a8_w8.log:18-21`:

| stage | lanes | W4 was | W8 needs | now | sketch |
|---|---|---|---|---|---|
| `prod_q` | 1 | 12 b | 127·128 → 15 b | **16 b** | — (see note) |
| `sum64_q` | 2 | 13 b | 16 b | 16 b | — |
| `sum16_q` | 8 | 15 b | 18 b | 18 b | — |
| `sum4_q` | 32 | 17 b | 32·127·128 → **20 b** | 20 b | "32-lane half 20b" ✔ |
| `acc_bank_{lo,hi}` | 64 | 18 b | 64·127·128 → **21 b** | 21 b | "64-lane beat 21b" ✔ |
| `pa_q`/`pb_q` | — | 17×18 | 17×21 → 38 b | 38 b | table says 17×**20** — deviation, see note |
| `p_acc` | — | 48 b | 44 b at K=6144 | 48 b | unchanged ✔ |
| `cfg_sh` | — | 6 b | 12 max | 6 b | unchanged ✔ |
| `g_cnt`, `last_scale_g` | — | 6 b | max 96+2 | 7 b | ✔ |

Both of the sketch's accumulator rows are used: 32 lanes IS `sum4_q`, 64
lanes IS `acc_bank`, because the as-built engine merges the halves of a
physical W8 beat (the sketch's own "if the halves are merged instead" row).
That merge is also the one deviation from the table: the retire product is
17×**21**, not the tabulated 17×20, because it consumes the merged 64-lane
value. Still ONE DSP48E2 (27×18 signed, the 21 b operand on the 27 b port),
so the table's *conclusion* holds even though its operand width does not.

**`prod_q` is built 16 b, one bit above the law's 15 b.** The law excludes
the weight code −128 (`quantize_weights8` clips to ±127, `pack_w8` asserts
it, `matvec_y32_w8` asserts it), but nothing on the DMA path validates weight
bytes, and at 15 b a −128 × −128 lane silently sign-flips 16384 → −16384,
i.e. a corrupt or foreign image produces a *plausible-looking* wrong y32
rather than anything detectable. 16 b costs 128 flops and no tree change
(`sum64_q` was already 16 b). **Everything above that row is sized to the
law, not to −128** — the invariant is enforced at the source, and the
generator's `maxmag128` control proves it (below).

W4 is bit-identical through the widened path because every stage is exact —
widening is pure sign extension, never a re-round. That was re-proved after
the `prod_q` 15→16 b change, not assumed.

## Logs

| file | what |
|---|---|
| `00_ref_selftest_w8.log` | `python3 ref/w4a8_ref.py` with `matvec_y32_w8` added. W4 sections (lines 1-9) byte-identical to HEAD. W8 section now also proves matvec_y32_w8 == matvec_y32 on every pair, agrees with dequantized float math to 0.50 lsb (bound 0.51 — selftest-A arbitration), and rejects the illegal code −128. |
| `01_red_w8.log` | TDD RED. W8 vector dirs against HEAD's engine + TB: every row of every shape/seed wrong, stream desyncs, watchdog $fatal, rc=134. 8 runs. |
| `02_frozen_goldens.log` | 20 W4 vector dirs (shape c K=4096 NG=32, shape f K=6144 NG=48, shape a; g128+g64; 4 seeds) generated by HEAD's generator and by the W8-capable one: `y32.hex`/`beats.hex`/`x8.hex` byte-identical. Only `params.txt` moved (7th field). |
| `03_green_matvec_w8.log` | `make -C tb tb_matvec_w8`. 4 random shapes × 4 seeds + the directed `w5` max-magnitude case, MIXED, chunk=1, chunk=3, nogap, both halves of the w8+g64 guard, the −128 rejection control, and the `shape_word` bit-29 self-test. |
| `04_regress_w4_suite.log` | `lint_matvec`, `tb_matvec`, `tb_matvec_ng`, `tb_matvec_g64`, `tb_matvec_chan`, `tb_matvec_chan_g64`, `tb_matvec_chan_w8`, `tb_streamer_engine`, `lint_mvshim_b`, `tb_mvshim_b`. 36 TB_MATVEC PASS + 44 TB_MATVEC_CHAN PASS (16 of them W8) + every OK line. |

## What the W8 gate covers

* **Shapes** `w1` K=128 NG=1 (2w+1s), `w2` K=512 NG=4 (8w+1s), `w3` K=2048
  NG=16 (32w+1s, the production H shape), `w4` K=6144 NG=48 (96w+2s — the
  MAX_NG ceiling and the first W8 shape with two scale beats). 4 seeds each,
  random input gaps + result backpressure.
* **MIXED** — W4 g128 → W8 → W4 g64 → W8 → W4 g128 → W8 → W4 g64 → W8 →
  W4 g128 → W8, ten cases on ONE engine instance with no reset between them.
  All bit-exact.
* **Chunked rows** at chunk=1 and chunk=3 (a chunk boundary every few beats
  is where a mis-tagged `first`/`last` shows up).
* **Throughput** with no gaps: NG ≥ 4 shapes run at period == BPR exactly,
  zero stalls, zero retire residual — the W8 row is longer than the W4 one
  so the retire has *more* slack, and the bound did not have to move. NG=1
  costs 2.86 stalls/row against the sanctioned 3 (the S2 single-scale-bank
  floor of 6 cycles minus BPR 3), which is the pre-existing law, not a W8
  effect.
* **w8+g64 is illegal** — `$error` in a normal build (message grepped, exit
  non-zero), and the SAME stimulus in a `+define+SYNTHESIS` build reaches the
  marker and exits 0, followed by a legal W8 case through that same
  as-synthesized binary. Loud in simulation, absent on silicon.
* **`w5` — the directed max-magnitude case, which GATES the widths.**
  `K=6144`, `w = ±127`, `x8 = −128`, `m = 65535`, rows alternating weight
  sign, so every stage sits exactly on its envelope in both signs (including
  the final round-half-away-from-zero). The generator asserts each magnitude
  against the width the RTL declares before it will emit the vectors:

  ```
  envelope: |prod|=16256 (15b, RTL prod_q 16b = law 15b + 1 for the illegal -128)
            2-lane 16b  8-lane 18b  32-lane 20b  64-lane 21b
            |p|=6545430282240 (44b, RTL 48b)  |y32|max=1598005440
  ```

  It runs in the correctness set, in MIXED and under `+chunk=3`, on all four
  seeds. The widths are therefore gated by a failing test, not argued.
* **The −128 invariant is enforced at the source** — the same directed vector
  built with the illegal code (`kind=maxmag128`) is REFUSED by the generator
  (`W8 code out of range: [-128, 127] not in +-127`, non-zero exit), which is
  the control for the `prod_q` headroom above.
* **`shape_word` bit 29** — `python3 sw/hwmap.py` checks all three legal
  (g, w8) packings, that `[31:30]` stay 0, that the default word is the
  legacy one bit for bit, and that `w8 + g64` is refused. Run by this target.

## Still owed (not this task)

* **A synthesis run must report `xline_q0_reg[*]/CE` specifically.** Plan
  Task 5's R-c build is where the one-comparator-bit claim above stops being
  an argument. It should report those 24 endpoints by name, before/after, and
  the lane-array LUT/DSP delta that `W8_SKETCH.md` §3's closing paragraph
  flagged as "one synthesis run, not an argument". Nothing here was
  synthesized.
* `sw/layer_test.py:plan_weights` has no W8 stride branch and no `nch`
  (W8_SKETCH.md §4, §6.1); no manifest carries a weight-width tag. Tasks 2-4.
