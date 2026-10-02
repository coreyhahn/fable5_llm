# W8 wire-format sketch — what an 8-bit weight path would cost

> **SUPERSEDED IN PART (R-c, 2026-08-22): gate D picked V5, so the RTL now
> exists** — `rtl/matvec_engine.sv` `cfg_w8`, SHAPE bit 29. Read §1, §2 and
> the §3 WIDTH TABLE as still-current law: the row format, the `ng` encoding
> and the derived widths were implemented as written, with ONE deviation —
> the table's "retire product 17 x 20" is **17 x 21** as built, because the
> as-built `acc_bank` holds the merged 64-lane value (the table's own
> "64-lane beat 21 b") rather than a 32-lane half. It is still ONE DSP48E2:
> 27x18 signed, 21 b operand on the 27 b port. `sum4_q` = the table's
> "32-lane half" 20 b, `p_acc` and `cfg_sh` unchanged, `g_cnt` widened to
> 7 b. `prod_q` is built 1 b WIDER than the table's 15 b (16 b) so the
> illegal code -128 cannot sign-flip; the law still excludes it.
>
> §3's PROSE is where the real divergence is: the as-built engine does
> **not** run the retire walk to `2*ng`, does **not** index scales with
> `r_g >> 1`, and does **not** grow `acc_bank` to `2*MAX_NG`. It keeps all
> three at ng units and spends the W8 half-beat toggle in the lane array
> instead (phase 0 drives lanes 0..63, phase 1 drives lanes 64..127, so the
> two beats of a unit land in the two halves of ONE `acc_bank` entry). That
> variant is cheaper on accumulator storage (half) and on retire length
> (half), and **decisive on the axis that mattered**: it adds no mux to the
> `x_mem`/`xline_q` cone holding the 24 worst waived endpoints — that cone
> grows by exactly one comparator bit (`g_cnt` 6->7), against a whole
> 512-bit mux level for the §3 variant. It is NOT cheaper everywhere: the
> multiplier array stays 128 lanes of 8x8 rather than 64, i.e. 64 more 8x8
> lanes than §3's shape, and the tree is 3-4 b wider throughout. §3's
> closing paragraph ("the honest way to find out is one synthesis run") is
> therefore still unanswered, and still the right instruction.
>
> §6.1's per-channel repack prerequisite is unaffected and still
> outstanding. The original text follows unedited.

**Status: TEXT ONLY. No RTL exists and none is planned unless gate D picks a
W8 variant** (V5 = W8 everywhere, or one of the V4mix mixed maps). This
document is the *costing basis* for that decision: it fixes the wire format
precisely enough that the byte budget in `V4_V5.md` is a real number rather
than an 8.125 b/w idealization, and it says which RTL fields move. Every
number in §1-§3 is produced by `ref/w4a8_ref.py`'s `_selftest_w8` (log:
`selftest_w4a8_w8.log`) or by `ref/scripts/bytes_per_token.py`, not asserted
here.

The modeled quantizer and packer are already committed and self-tested —
`w4a8_ref.quantize_weights8` / `row_beats8` / `row_stride8` / `pack_w8` /
`pack_ddr_rows8` / `unpack_ddr_rows8` — so the format below is executable
today on the host side. Only the engine and the emitter are missing.

---

## 1. The row

A W8 row is the W4 row with **one substitution**: a weight is a byte, not a
nibble. Everything else — the 64-byte beat, the `[weight beats | scale
beats]` order, the uint16-mantissa-per-group scale encoding with one shared
exponent per matrix, the zero-padded 64 B stride, `rshift_round` at the end —
is unchanged, which is what lets the whole existing dequantization chain
(`m * 2^(e-15)`, arbitrated against `matvec_y32` in `perplexity_eval
--selftest` sections A and D4) apply verbatim.

```
  weight beats = K // 64            (W4: K // 128)
  scale beats  = ceil((K/g) / 32)   (IDENTICAL to W4 — the scales did not move)
  row stride   = (K//64 + ceil((K/g)/32)) * 64 bytes
```

`K` keeps W4's legality rule, a multiple of **128**, even though 64 would
divide evenly. That is not arithmetic, it is the SHAPE field constraint of
§2.

| K (2B geometry) | W4 g128 row | W8 g128 row | W8 b/w | ideal 8.125 |
|---|---|---|---|---|
| 1024 | 8w+1s = 576 B | **16w+1s = 1088 B** | 8.500 | +4.6 % |
| 2048 (`H`, most rows) | 16w+1s = 1088 B | **32w+1s = 2112 B** | 8.250 | +1.5 % |
| 3584 | 28w+1s = 1856 B | 56w+1s = 3648 B | 8.143 | +0.2 % |
| 6144 (`FFN`, mlp.down) | 48w+2s = 3200 B | **96w+2s = 6272 B** | 8.167 | +0.5 % |

Two consequences worth stating, because both cut the *other* way from the
naive "W8 is 2x W4":

* **A W8 image is 1.94x its W4 g128 twin at 2B, not 2.00x** (1.90x at 0.8B).
  The weight side doubles exactly; the scale side does not move, and the
  beat-padding overhead *falls* (more whole weight beats to amortize the same
  partial scale beat). At 2B the packed rate is 8.237 b/w against W4 g128's
  4.237.
* g64 is **more** expensive in W8 relative terms than in W4 only where the
  extra scale beat lands (K=3584, K=6144); nothing in the model needs it,
  because the W8 error is already 15-18x below W4's (`_selftest_w8`), so
  every variant scored in `V4_V5.md` uses **w8g128**.

## 2. The SHAPE word — it fits in the spare bits, if `ng` keeps its meaning

> ### PRE-G3.3 ROWS, KEPT AS THE RECORD — dated note 2026-09-02 (Task 9)
>
> Rows here marked `<!--cites:noquote-->` quote **source that G3.3 DELETED**,
> not source that merely moved: the `cfg_w8` / `cfg_g64` ports and everything that selected on them, SHAPE bits 28 and 29, and the W8-envelope adder tree.  They are kept verbatim, because they
> are the record of what the pre-G3.3 tree said and the argument they support
> rests on them (§0: nothing is deleted or struck).  The exemption marker is
> used for exactly the reason §7.6 gives — *"an exemption is for source that
> no longer exists, not for a citation that has merely moved"* — and every
> citation that had merely MOVED was RENUMBERED instead, mechanically, by
> `evidence/qwen9b/o3/o3_cite_drift.py --base a08a90b`.
> **The post-G3.3 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_3_MATVEC.md` §11.1.**

`rtl/matvec_chan.sv:18` (and `sw/hwmap.py:36-52`):  <!--cites:noquote-->

```
  R_SHAPE = { 3'b0 , g64[28] , nrows[27:12] , sh[11:6] , ng[5:0] }
              ^^^^^
              bits [31:29] — the only spare, and W8 needs exactly one
```

**Proposal: bit 29 = `w8`** (0 = W4 nibbles, 1 = W8 bytes), leaving [31:30]
spare. Bit 28 (`g64`) keeps its meaning in both, so `w8`+`g64` is a legal
(if unused) combination and needs no decode special case.

The load-bearing part is what `ng` means. `ng` is **6 bits, valid 1..48**
(`matvec_engine.sv:106,113`, `MAX_NG = 48`, with a `$fatal` envelope check at
`:597`). The model's widest row is K=6144:

* if `ng` were redefined as the W8 weight-beat count, K=6144 needs
  **96 > 63** — the field overflows and `nrows` has no room to give;
* keeping `ng = K // 128` in W8 mode (so **weight beats = 2*`ng`**) keeps
  every value in 1..48, needs no field to widen, and — because `NSCAL_ROW`
  for w8g128 is `ng`, exactly as for W4 g128 — **reuses the mode-0 scale-beat
  count `ceil(ng/32)` unchanged** (`matvec_engine.sv:168`).

That is why `row_beats8` asserts `K % 128 == 0`: the wire format is written
so the CSR does not move. `sh` does move — 6 bits still, but ~4 higher
(K=2048: 6 -> 10; K=6144: 8 -> 12), which the 6-bit field holds with room.

## 3. Engine delta (one paragraph, then the widths)

`matvec_engine` streams one 64-byte beat per cycle into a 128-lane
multiply-add tree whose last stage emits two halves (`sum4_q[0..1]` = k
0..63, `[2..3]` = k 64..127), banks them as `acc_bank_{lo,hi}` (18-bit
signed, `MAX_NG` entries), and retires each row with two 17x18 DSP products
`m*lo + m*hi` accumulated into a 48-bit `p_acc`, then one `rshift_round`.
**The W8 change is: the nibble unpack disappears (a byte IS the operand), a
beat carries 64 weights instead of 128 so the lane array halves in count and
doubles in operand width, the beat counter and the retire walk run to
`2*ng` instead of `ng` with the scale index becoming `r_g >> 1` (both beats
of a W8 g128 group share one mantissa, which is exactly the existing mode-0
"drive both scale operands with `m_g`" trick spread over two cycles), and
`acc_bank` grows from `MAX_NG` to `2*MAX_NG` entries — the same depth the
scale buffer `NSCAL = 2*MAX_NG` already has.** Nothing about the row
cadence, the tagged retire pipeline, `sc_hold`, or the result BRAM changes;
the engine simply spends twice as many beats on a row, which is the whole
point (and the whole cost).

Widths, derived in `_selftest_w8` from the real activation rail (x8 in
[-128,127]) rather than from the frozen `sh` bound:

| quantity | W4 today | W8 needed | verdict |
|---|---|---|---|
| per-half beat sum (32 lanes, W8) | 18 b signed (64 lanes x 8 x 128) | **20 b** (32 x 127 x 128) | +2 b on `acc_bank_{lo,hi}` |
| whole-beat sum (64 lanes, W8) | - | 21 b | if the halves are merged instead |
| retire product | 17 x 18 (1 DSP48E2) | **17 x 20** | still ONE DSP48E2 (27x18 signed: the 20 b operand goes on the 27 b port) |
| row accumulator `p_acc` | 48 b (needs 39 b at K=6144) | 44 b at K=6144 | **48 b unchanged** |
| `cfg_sh` | 6 b | 12 max at K=6144 | unchanged |
| beat counter `g_cnt`, `last_scale_g` | 6 b (max 48+2) | max 96+2 | **widen to 7 b** |
| `x_mem` (32 banks x `MAX_NG` x 32 b) | one line = 128 x int8 | two W8 beats share one line | unchanged, index `g_cnt >> 1` |
| `WBEATS` CSR | 32 b | doubles | unchanged |

The one item this sketch does **not** price is LUT/DSP area of the lane
array: 64 lanes of 8x8 against 128 lanes of 4x8 is "probably similar, maybe
cheaper", and the honest way to find out is one synthesis run of a
parameterized `matvec_engine`, not an argument. Flagged, not answered.

## 4. Host / generator delta

Small but non-zero, listed so the estimate is not "just RTL":

* `sw/hwmap.py:shape_word()` gains a `w8` argument (bit 29) — and
  `sw/layer_test.py:plan_weights` gains a W8 branch in its stride
  cross-check, which today hardcodes `stride == (K//128 + ceil((K/g)/32))*64`
  (`sw/layer_test.py:77-100`);
* the weight manifest needs a per-image format tag (it already carries `g`;
  "absent == 128" is the precedent to follow, i.e. "absent == W4");
* `ref/gen_layer_script.py` / `gen_model_script.py` must call
  `w4a8_ref.quantize_weights8` + `pack_ddr_rows8` for the promoted classes —
  and, for a **mixed** (V4mix) map, must carry the per-class choice through
  the emitter, which today has no notion of per-class precision at all. A
  mixed map is therefore materially more emitter work than V5's uniform one.
* nothing in the SEQ ISA moves: MOVX/MOVY/LDC and the record layout are
  activation- and result-side.

## 5. Why this is not a W8+GPTQ sketch

Deliberately out of scope, and the reason is arithmetic rather than
schedule: GPTQ buys output fidelity by re-rounding the *quantization
residual* of neighbouring columns, and at 8 bits that residual is 15-18x
smaller than at 4 bits (measured, `_selftest_w8`; 15.4-15.7x against the
production MSE-scale W4 rule in `perplexity_eval --selftest D4`). V5's
measured PPL (`V4_V5.md`) is within a fraction of the bf16 anchor, so the
entire remaining headroom for any better W8 quantizer is smaller than the
error bar the study can resolve — there is nothing for error feedback to
recover. A W8+GPTQ point would cost a full calibration + scoring run to
measure a number that cannot change a gate-D decision.

## 6. Where the cost lands

`ref/scripts/bytes_per_token.py --model 2b --table` (log: `bytes_table_2b.log`)
is the authority; the two facts that matter for the gate are:

1. **DDR fit.** The weight window is 1,280 MiB *per channel*
   (`W_BASE 0x1000_0000` .. `EMB_BASE 0x6000_0000`, asserted by
   `sw/layer_test.py:plan_weights`). At 2B, V5 packs to **1,847 MiB —
   144 % of the window, it does NOT fit**; V4mix top-2 (116 %) and top-3
   (127 %) do not fit either. By *bytes* each channel carries only a quarter
   of that (V5 = 36.3 %), but that is **not** a fit today — see §6.1.
2. **Throughput.** Doubling weight traffic does *not* halve tok/s, because
   the matvec bucket is only ~28 % of the modeled 2B step: V5 lands at
   **16.1-17.0 tok/s against V2's 20.7-21.5**, i.e. **-21 to -22 %** across
   MOVER_NORM's honest `r` bracket (-20.9 % at r=1.000, -22.4 % at
   r=1.131). That is the single most decision-relevant number this sketch
   exists to support.

### 6.1 The per-channel repack is a W8 prerequisite, and it is not built

`plan_weights` takes **no `nch`**: it accumulates FULL image footprints from
`W_BASE`, and `sw/seq_run.py:plan_weight_split` places each channel's slice
at `wbase_of[wid] + r0*stride`, i.e. *inside the whole image's span*. Every
channel therefore reserves the entire image today and the pack is
nch-independent — **V5 trips the `plan_weights` assert at nch=4 exactly as it
does at nch=1** (top address 0x8374c000, past `EMB_BASE`). Turning the
per-channel byte counts into a real fit needs per-channel image bases *and*
per-chunk rebasing for the ILV-placed LM head, whose channel rows are
strided through the image rather than contiguous. **Add that to the W8
costing** alongside §4's host/generator items: it is host + emitter work, not
RTL, but it is on the critical path for any W8 variant beyond V4mix top-1.
