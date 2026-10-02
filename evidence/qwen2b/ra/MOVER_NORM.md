# Mover cost re-normalization — per ROW, and the 2B band (Track R, R-a task 2)

Closes the second (U) item of `docs/QWEN2B_FEASIBILITY.md:66-72`
("post-rung-3 mover per-ROW costs — re-normalize mover_bench donors") and
**replaces the study's `movers 11-14 ms (U band)`**.

*Rev 2 (2026-08-12), after adversarial review: max-channel matvec, engine-only
DDR rate, MVGO config charged in both channel modes, no double-counted issue
floor, and the calibration-free bracket of §3.2 adopted as the primary
refutation. Every number below is the amended one.*

> **Headline.** 2B `movers+polls` at nch=4 = **16.0 ms/token (band 15.5-17.0)**,
> up from **~11.4 ms** at 0.8B (x1.41). The study's 11-14 ms band was low
> because it inherited a wrong 0.8B baseline: the 0.8B nch=4 mover bucket was
> published as "~9 ms" (`evidence/rung4/RUNG4_GATE.md:57-58`, quoted as
> superseded history at `docs/ARCHITECTURE.md:621-622`). That figure is
> **refuted without any calibration** in §3.2 — it is bracketed at
> **[11.17, 11.89] ms** by arithmetic that uses only counted work, one RTL
> fact (1 beat/cycle) and two measured step times. 9 ms is outside that
> bracket by >= 2.2 ms.
> (`docs/ARCHITECTURE.md` has since been corrected; `RUNG4_GATE.md` is left as
> a dated record.)

---

## 1. The cost law (what one mover record actually costs)

`evidence/rung3/mover_bench_build032.json` measures whole records at ONE
length each. Splitting that into rate x work needs the RTL: `rtl/seq_movers.sv`
gives each mover a **32-bit AXI4 burst master (`m_axib`) at aclk = 250 MHz**,
one beat per cycle, and `seq_movers.sv:511-514` gives the beat counts:

```systemverilog
wire [23:0] x_wwords = 24'((len_q + 24'd3) >> 2);      // MOVX XWIN writes
wire [23:0] y_wwords = i16_q ? len_q : 24'(len_q << 1);// MOVY scratch writes
```

MOVX reads `len` scratch words (one int8 per 32-bit word) and writes
`len/4`; MOVY reads `len` RES rows and writes `len` (int16) or `2*len`
(pairs32) scratch words, read and write concurrently. So **beats = max(read,
write)** and the cost is affine in beats:

| class | donor record | measured cyc/rec | beats | cyc/beat | **cyc per unit** | fixed (cyc) |
|---|---|---|---|---|---|---|
| `movx` | 1024 int8 -> XWIN | 1144.70 | `len` = 1024 | 1.0 | **1.0 / int8** | 120.7 |
| `movy` int16 | RES[0..2048) >>13 | 2184.70 | `len` = 2048 | 1.0 | **1.0 / row** | 136.7 |
| `movy_head` pairs32 | RES[0..2048) | 4258.72 | `2*len` = 4096 | 1.0 | **2.0 / row** | 162.7 |
| `ldc` | 1024 words DDR->scratch | 1618.87 | `words` = 1024 | 1.0 | **1.0 / word** | 594.9 |
| `ext_csrwr` | one layer CSR write | 16.99 | - | - | - | 16.99/rec |
| `int_csrwr` | XRF write-through | 33.99 | - | - | - | - |
| `tcnt_csrwr` | issue/decode floor | 2.06 | - | - | - | 2.06/rec |
| `mvgo` config | 5 AXI-Lite writes | - | - | - | - | 5 x 16.99 = 84.95 |

**The rate falls out of the RTL exactly (1.0 / 1.0 / 2.0 beats per unit) and
the residue is a per-record fixed cost of 120-165 cycles** — two AXI-Lite
setup writes (2 x 17) plus burst round-trip and drain. That the three
independent donors all land on integer rates with a consistent fixed term is
the evidence that this decomposition, not the raw cyc/rec, is the right
normalization. (LDC's 594.9 is bigger because its read side is a DDR burst
through `seq_unit`'s ext client; it is also the smallest term.)

Two accounting rules that the review corrected, and that matter:

* **The 2.06 cyc/record issue floor is NOT charged separately.** Every class
  cost above is a whole-record cost measured in a replicated stream, so it
  already contains that record's fetch/decode/issue — `tcnt_csrwr` **is** the
  floor and `ext_csrwr` is the floor plus one AXI-Lite write. Charging 2.06
  again across all ~15-17k body records would double-count ~0.11 ms/token.
  Only the handful of records no class covers (EMB, XOP, AMAXL, and FENCE at
  nch>1) get the bare floor: 8 records at nch=1, 225 at nch=4, i.e. <0.01 ms.
  (EMB also moves 1024 words that nothing here charges — another <0.01 ms.)
* **`mvgo` is not a mover**, but its **config writes are**. Its 30,885 cyc/rec
  is dominated by the engine's DDR run, which the census charges to the matvec
  bucket. Its 5 AXI-Lite config writes, however, **precede the doorbell in
  both channel modes** — wait-mode and no-wait alike — so they land in the
  residual at nch=1 as well as nch=4 (rev 1 wrongly zeroed them at nch=1).
  Consequently the DDR rate `r` below is derived from the donor **with those
  102 ui-cycles removed**, so the config is counted once, on the mover side.
  `MVGO_GUARD` (64 aclk) is *not* charged: it elapses after the doorbell,
  inside the engine's busy interval.

### Per-ROW summary (the deliverable)

```
    MOVX   1.00 aclk cycle per int8 element of x   (+121/record)
    MOVY   1.00 aclk cycle per result row  int16   (+137/record)
           2.00 aclk cycles per result row pairs32 (+163/record)
    LDC    1.00 aclk cycle per constant word       (+595/record)
    CSRWR  16.99 aclk cycles per layer-CSR write
    CMD    16.99 (doorbell; the DONE poll is layer-busy, charged to layer)
    MVGO   84.95 per record (5 config writes; both channel modes)
```

---

## 2. Per-token mover work, 0.8B (counted, not estimated)

Counted over one full decode step of the frozen streams — body span
`[1526, 16266)` of `tb/scripts/w4/model_v2_s1.e.seq` (nch=1) and
`[1526, 18172)` of `...e4.seq` (nch=4):

| quantity | nch=1 | nch=4 | rule |
|---|---|---|---|
| MOVX records / elements | 187 / 277,504 | 748 / 1,110,016 | one per weight image, `len = K`; **x nch** (every channel needs all of x) |
| MOVY rows int16 / pairs32 | 227,904 / 420,352 | same | invariant |
| MOVY **records** int16 / pairs32 | 180 / 218 | 552 / 314 | tracks the MVGO chunk cut |
| MVGO records | 398 | 866 | rows row-split then cut at `CHUNK_ROWS`=2048 |
| MVGO beats / rows | 6,522,432 / 648,256 | same | invariant (417,435,648 B/token) |
| MVGO beats **on the busiest channel** | 6,522,432 | **1,643,280** | see §3.1 |
| LDC records / words | 121 / 57,184 | same | invariant |
| CSRWR / CMD | 10,227 / 3,401 | 10,371 / 3,449 | ~invariant |

Two independent confirmations that this census is right:

* `sum(K_i)` over the 187 images of the emitter's own weight plan
  (`model_v2_s1.e.seq.json:weights`) = **277,504** = the counted MOVX
  elements, i.e. exactly one MOVX per image of length K.
* The nch=1 -> nch=4 projection (`split_rows` + `res_chunks`, `ilv_chunks`
  for the LM head) predicts **866** MVGO and **748** MOVX records; the
  committed 4-chan stream has exactly 866 and 748.

---

## 3. Cross-check on silicon — HARD GATE

### 3.1 The matvec term, and why it is the MAX channel

The bucket is a **residual**: `REST = seq_total - layer_busy - matvec_busy`
(`sw/cycle_census.py:1-20`), so it cannot be checked without a matvec term.
**No silicon measurement of that term exists** in the committed evidence:
`cycle_census` reports `mv_ms ≈ 0` (the census json's `mv_cyc` deltas are
-62..+122 cycles) because the matvec PERF CSRs reset on every engine start, so
step-deltas cancel — stated at `evidence/rung3/CENSUS.md:70`. It therefore has
to be *derived* from beats x a DDR rate, and both factors need care:

**Beats.** The 4-channel row split is **uneven** — `split_rows` gives the
first `nrows % 4` channels one extra row, and the LM head's `ilv_chunks` deals
whole 2048-row chunks round-robin. Per channel, per token:

```
   0.8B  chan0 1,643,280   chan1 1,629,456   chan2/3 1,624,848   (beats/4 = 1,630,608)
   2B    chan0 3,915,664   chan1 3,889,552   chan2/3 3,880,848   (beats/4 = 3,891,728)
```

The census instruments **chan 0**, and wall-clock exposure at a FENCE is the
**max** channel — which is also chan 0. So matvec_4 uses 1,643,280, not
beats/4 (rev 1's error; +0.8% on the term).

**Rate.** Two equations, neither using any nch=4 measurement:

```
(i)  donor MVGO, build_032: 18,432 beats + 2,048 rows = 30,885.45 aclk
                          = 37,077 ui-cyc, of which 102 ui is config (§1)
(ii) the rung-4 zero-bubble fix removed ONLY the per-row bubble, so the
     build_032 -> build_033 nch=1 step delta is all bubble:
       (62.842 - 45.018) ms x 300.12 MHz / 648,256 rows = 8.252 ui-cyc/row
=>   r = (37,077 - 102 - 2048 x 8.252) / 18,432 = 1.0892 ui-cyc per 64 B beat
     = 17.63 GB/s/chan = 91.8% of the 19.2 GB/s DDR4-2400 peak
```

**Sensitivity, stated here because Track Q consumes it:** `r` rests on a
bubble recovered across two builds (8.252) where the repo's own figure is
8.94 (`evidence/rung3/CENSUS.md:33`); 8% on the bubble moves `r` 7%
(8.94 -> r = 1.013). The independent bracket in §3.2 bounds
**r in [1.000, 1.131]**, i.e. DDR in **[17.0, 19.2] GB/s/chan**, which
contains 1.0892 and is the range every derived matvec number below is
quoted over.

**Per-token device times** are the seq_run totals with the *session-once*
preamble removed (`(197.64 - 8.671)/6`; the 8.671 ms preamble is
`evidence/rung3/census_step_build032.json:preamble.device_ms`), confirmed by
an independent instrument — `chat_seq --canned` reports 31.476-31.512 ms/step
at nch=4 (`evidence/rung4/chat_canned_4chan.json`).

| build / nch | measured ms/token | layer (LCYC) | matvec (derived, max-chan) | **residual = movers+polls** | model | err |
|---|---|---|---|---|---|---|
| 033 / nch=1 | 45.018 | 14.13 | 23.671 | **7.217** | 7.293 | +1.1% |
| **033 / nch=4** | **31.495** | 14.13 | **5.964** | **11.401** | **11.334** | **-0.6%** |

### 3.2 The bracket that needs no calibration at all (primary refutation)

Adopted from the review; it removes `r` from the argument entirely.

```
  a) movers_1 has a floor from counted work alone — burst beats at the RTL
     maximum of 1 beat/cycle, plus the CSR writes and LDC words, no fixed
     costs, no CMD, no MVGO config:
        277,504 + 227,904 + 2x420,352 + 10,227x16.99 + 57,184
      = 1,577,053 aclk = 6.308 ms
  b) at nch=1 nothing overlaps: MVGO is wait-mode, there are no FENCEs, and
     the sequencer runs records to completion, so
        45.018 = 14.13 + matvec_1 + movers_1  ,  movers_1 >= 6.308
     =>  matvec_1 <= 24.580 ms  =>  r <= 1.131 ui-cyc/beat
  c) r >= 1.000 by construction (the engine cannot exceed one 64 B beat per
     ui-clk), so
        movers_4(r) = 31.495 - 14.13 - 5.4754 x r        [5.4754 ms = chan0's
                                                          1,643,280 beats / ui-clk]
        r = 1.000 -> movers_4 = 11.889      (DDR 19.21 GB/s/chan)
        r = 1.131 -> movers_4 = 11.172      (DDR 16.98 GB/s/chan)
```

**Bracket: movers+polls at nch=4 is in [11.17, 11.89] ms.** The per-row
recompute (11.334) and the point-estimate residual (11.401) both sit inside
it. **9 ms is outside it by >= 2.2 ms.** The same bracket pins the DDR rate to
[17.0, 19.2] GB/s/chan, corroborating the 17.63 derived independently in §3.1.

This is also what closes the one real modelling gap at nch=4: with no-wait
MVGO and 217 FENCEs per token, mover beats *could* in principle hide under
engine time, which a serial model would miss. The bracket does not care — it
is an identity over the measured step time — and it still excludes 9 ms.

### 3.3 The gate

| | ms/token |
|---|---|
| **recompute from the per-row costs of §1 x the work of §2** | **11.334** |
| measured residual at the central r (table in §3.1) | 11.401 |
| **error** | **-0.6%** |
| calibration-free bracket (§3.2) | [11.17, 11.89] |
| the brief's / `RUNG4_GATE.md:57-58` "movers + polls ~9" (history at `ARCHITECTURE.md:558-559`) | 9 |
| **error against that figure** | **+26% — GATE MISSED as written** |

Full step model vs both silicon measurements (same law, nothing refit):

```
  nch=1  MOVX 1.200 + MOVY (1.010+3.505) + LDC 0.517 + CSRWR/CMD 0.926
         + MVGO cfg 0.135
         = movers 7.293 | matvec 23.671 | layer 14.130 -> 45.094 (meas 45.018, +0.17%)
  nch=4  MOVX 4.801 + MOVY (1.213+3.567) + LDC 0.517 + CSRWR/CMD 0.939
         + MVGO cfg 0.294 + unmodeled 0.002
         = movers 11.334 | matvec 5.964 | layer 14.130 -> 31.428 (meas 31.495, -0.21%)
```

The nch=4 line is a **fully independent prediction** — no nch=4 number enters
the calibration (only the donor MVGO and the nch=1 build_032/033 delta do).

### 3.4 Why "~9 ms" was wrong

Beyond the bracket, two mechanical errors explain where it came from:

1. **The 32.94 ms it was derived from charges every token 1/6 of the
   session-once preamble.** `197.64/6 = 32.94`, but 8.671 ms of that 197.64
   is the one-time preamble; per-token is **31.50**, measured directly by
   `chat_seq --canned`.
2. **Its matvec term was assumed, not measured.** `RUNG4_GATE.md:57` derives
   "~10.4 GB/s/chan" *from* the assumed ~10 ms, and `ARCHITECTURE.md` already
   flagged the surrounding bandwidth claims `[UNVERIFIED]`. ~10 ms/chan at
   nch=4 implies ~40 ms at nch=1 — more than the entire measured 45.02 ms step
   minus its 14.13 ms layer bucket, i.e. negative mover time.

Corrected decomposition at nch=4: **layer 14.13 (44.9%), movers+polls ~11.4
(36.2%), matvec ~6.0 (18.9%)**. `docs/ARCHITECTURE.md:623-647` and its
bottleneck ranking at `:658-681` have been updated to this;
`evidence/rung4/RUNG4_GATE.md` is deliberately left as a dated record of what
was believed on 2026-08-12.

---

## 4. The 2B projection

### Method, and why it is not an emitted stream

The 2B geometry cannot emit a SEQ stream today — **both** emitter paths abort
on the 14-bit scratch-address packing that `docs/QWEN2B_SCRATCH_MAP.md`
already flags as R-b item 1:

```
SEQ_NCH=1: gen_layer_script.py:552 alu()  srca | (srcb << 14)
           -> seq_format.py:1357 AssertionError:
              ALU op 1 reads 0xc00/2048, W32 staged 0x4c00/2048
SEQ_NCH=4: seq_format.py:1555 AssertionError: non-contiguous dequant dst
           (4-chan)   [(a2 >> 17) & 0x3FFF truncates dst >= 16384]
```

This is *new evidence for a known item*: the packing is not only an RTL
concern, it blocks the emitter, and it is therefore on R-b's critical path
for any 2B artifact chain. (Both aborts are the 15th address bit; nothing
here is a mover problem.)

So the 2B work is counted from the two things that do work at 2B:

* the **weight plan** of a real 24-layer / 187-image 2B generator run
  (`FABLE5_MODEL=2b gen_token_script.py t.txt 1 2 4096 24`, no emitter), which
  gives every image's `nrows / k / nbeats`, with the LM head rescaled from the
  reduced vocab 4,096 to the production 248,320 (rows and beats are both
  exactly linear in vocab: the 0.8B control run's 4,096-row head carries 9
  beats/row and 1 pairs32 MOVY row/row, and rescaling it to 248,320 rows
  reproduces the real stream's head exactly — 2,234,880 beats, 248,320 MOVY
  rows, 122 MVGO/MOVY records, 366 CSRWR, 122 CMD, 31 FENCE);
* the structural rules of §2, each validated at 0.8B against the committed
  streams.

Validation of the 2B plan itself: its total is **15,566,912 beats x 64 B =
996,282,368 B/token**, which is *exactly* the byte count the feasibility study
computed independently (`QWEN2B_FEASIBILITY.md:37`). The 0.8B run of the same
generator reproduces the real model's per-token body work **exactly**
(MOVY rows 227,904/172,032, MVGO 4,287,552 beats, LDC 57,184 words, CSRWR
10,005, CMD 3,327 — all identical to `model_v2_s1.e4`'s body).

### What moves, image by image (187 images, both geometries)

| (nrows, K) 0.8B | -> 2B | x | role | MOVY mode |
|---|---|---|---|---|
| (6144, 1024) | (6144, **2048**) | 18 | DN `in_qkv` (`CONV_DIM` rows) | int16 |
| (2048, 1024) | (2048, **2048**) | 18 | DN `in_z` gate (`LVD` rows) | int16 |
| (16, 1024) | (16, **2048**) | 36 | DN `in_a` / `in_b` (`LNH` rows) | int16 |
| (1024, 2048) | (**2048**, 2048) | 24 | DN `out` / GQA `o_proj` (`H` rows, K=`LVD`) | int16 |
| (3584, 1024) | (**6144**, **2048**) | 48 | MLP gate / up (`FFN` rows) | pairs32 |
| (1024, 3584) | (**2048**, **6144**) | 24 | MLP down | int16 |
| (4096, 1024) | (4096, **2048**) | 6 | GQA q+gate (`2*NQ*HD`) | int16 |
| (512, 1024) | (512, **2048**) | 12 | GQA k / v (`NKV*HD`) | int16 |
| (248320, 1024) | (248320, **2048**) | 1 | LM head (vocab rows) | pairs32 |

### Per-token totals

| quantity | 0.8B | 2B | ratio |
|---|---|---|---|
| MOVX elements `sum(K)` (nch=1) | 277,504 | **481,280** | 1.73 |
| MOVX elements (nch=4) | 1,110,016 | **1,925,120** | 1.73 |
| MOVY rows int16 | 227,904 | **277,056** | 1.22 |
| MOVY rows pairs32 | 420,352 | **543,232** | 1.29 |
| MOVY records nch=1 (i16/p32) | 180 / 218 | **180 / 266** | - |
| MOVY records nch=4 (i16/p32) | 552 / 314 | **552 / 314** | - |
| LDC words | 57,184 | **107,360** | 1.88 |
| MVGO beats total / busiest channel | 6,522,432 / 1,643,280 | **15,566,912 / 3,915,664** | 2.39 |
| MVGO/MOVY records nch=1 / nch=4 | 398 / 866 | **446 / 866** | - |
| CSRWR + CMD (nch=4) | 13,820 | **14,108** | 1.02 |

LDC: 49 of the 121 records are `H`-length (24 layers x ln1/ln2 + the final
norm) and double; the other 72 are `LNH`/`LDK`/`HD`-sized and are invariant
(18x32, 18x16, 18x128, 12x256, 6x128-roped) — 57,184 + 49x1024 = 107,360.
CSRWR/CMD: the .txt command count over the same 24-layer run moves 7,450 ->
7,594, i.e. **+72 commands/token**; each command emits one CMD record plus up
to three ARG CSRWR records, so **+72 CMD and +216 CSRWR = +288 records** is
what is applied (0.02 ms — the term is inert either way).

### The band

| bucket (nch=4) | 0.8B | **2B** |
|---|---|---|
| MOVX (x broadcast) | 4.801 | **8.062** |
| MOVY int16 | 1.213 | **1.410** |
| MOVY pairs32 | 3.567 | **4.550** |
| LDC | 0.517 | **0.717** |
| CSRWR + CMD | 0.939 | **0.959** |
| MVGO config | 0.294 | **0.294** |
| unmodeled records | 0.002 | **0.002** |
| **movers + polls** | **11.334** | **15.994** |

```
   2B movers+polls, nch=4 :  15.99 ms/token   published band 15.5 - 17.0
   2B movers+polls, nch=1 :   9.56 ms/token
```

Band construction (the real uncertainty is the rate/fixed split, which one
measurement per class cannot resolve):

* central affine model -> **15.99 ms** (-0.6% against the 0.8B residual).
* raw variant — charge every class its whole `cyc_per_rec` per unit (MOVX
  1.1179/elem, MOVY 1.0667 / 2.0794 per row, LDC 1.5809/word) -> **16.24 ms**;
  the same variant gives 11.03 ms at 0.8B, i.e. -3.3% against the measured
  residual, so it is the worse fit and serves only as the upper edge.
* arithmetic spread is therefore **15.99 - 16.24**. The published
  **15.5 lower edge is judgment margin**, not arithmetic: it carries the
  structural risk of §5.1 (the 2B record mix is derived, not emitted) and the
  model's own +-1% spread on the two 0.8B silicon points.

**For Track Q task 10** (modeled tok/s column), the matching whole-step model
at nch=4, quoted over the full honest `r` range of §3.1 and using the
**busiest-channel** beats (3,915,664):

```
   2B matvec = 13.05 ms (r=1.000) .. 14.21 (r=1.089) .. 14.76 (r=1.131)
   2B step   = matvec + movers 15.99 + layer 17.4*  ->  46.4 .. 47.6 .. 48.2 ms
   2B decode = 21.5 .. 21.0 .. 20.8 tok/s
   (*17.4 is the feasibility study's layer figure, NOT verified here — it is
     the widest remaining uncertainty in this line, larger than the r range.
     The study's matvec 23.9 ms assumed ~10.4 GB/s/chan, refuted in §3.)
```

---

## 5. Risks and levers this exposes

1. **Structural risk on the headline number.** The 2B record mix is derived,
   not emitted, because R-b's 15-bit packing is not done. If R-b changes
   `CHUNK_ROWS`, the x-broadcast, or the 4-chan row split, MOVX and the
   record-count terms move. Re-run this census against the first real 2B
   4-chan stream; it is a ~10-line diff of the tables in §4.
2. **MOVX is now the single biggest mover item at 2B** (8.06 of 15.99 ms) and
   it is doubly wasteful *by construction*: the same x is streamed once per
   channel (x4), and the scratch stores one int8 per 32-bit word so each
   element costs a full 32-bit beat (x4 again). Packing X8 four-per-word, or
   broadcasting once into all four XWINs, is worth ~6 ms/token at 2B — a
   bigger lever than anything left in the matvec bucket. Flagged for R-b /
   the ladder, not scoped here.
3. **The pairs32 MOVY costs 2 cycles/row** where int16 costs 1; the LM head
   alone is 248,320 pairs32 rows = 1.99 ms/token at both geometries. If the
   head's AMAX32 chain could consume int16, that halves.
4. **The matvec engine runs at 17.0-19.2 GB/s/chan** post-rung-4 (bracket,
   §3.2), not the 10.4 GB/s the docs carried. Aggregate 68-77 GB/s moves the
   bandwidth ceiling to ~163-184 tok/s at 0.8B (0.417436 GB/token) and
   **~68-77 tok/s at 2B** (0.996282 GB/token), against the 140.6 / 58.9 that
   `ARCHITECTURE.md:16` and `QWEN2B_FEASIBILITY.md:40` carry from the 14.67
   GB/s figure. **Nothing here is a direct measurement of the matvec bucket**
   (see §3.1): re-running `sw/matvec_test.py` on build_033 would measure the
   sustained rate in one command and is the cheapest outstanding measurement
   in this area.

---

## 6. Reproduction

```bash
cd ref
# 2B weight plan (no SEQ emitter — the emitter cannot run at 2B yet, see §4)
FABLE5_MODEL=2b ./.venv/bin/python gen_token_script.py /tmp/t2b.txt 1 2 4096 24
# the 0.8B control: same generator, same shape, emitter ON, nch=4
FABLE5_MODEL=0.8b SEQ_EMIT=/tmp/t08 SEQ_PROFILE=epsnorm SEQ_NCH=4 \
  ./.venv/bin/python gen_token_script.py /tmp/t08.txt 1 2 4096 24
```

Record/work counts come from `ref/seq_format.unpack_stream` over the body
span `[first EMB, first AMAXL]`; the nch=4 projection and the per-channel beat
split use `seq_format.split_rows` / `res_chunks` / `ilv_chunks` unchanged.
Inputs: `evidence/rung3/mover_bench_build032.json`,
`evidence/rung3/census_step_build032.json`, `evidence/rung3/CENSUS.md`,
`evidence/rung4/RUNG4_GATE.md`, `evidence/rung4/chat_canned_4chan.json`,
`tb/scripts/w4/model_v2_s1.e{,4}.seq{,.json}`.
