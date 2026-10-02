# NVFP4 study — rung 1: the Qwen3.5-2B ranking (Task NV1, rungs 0 + 1)

**Status: the 2B ranking the controller brings to the user before any 9B run
(Ruling C6).** It decides nothing. It is not docs/NVFP4_STUDY.md (written
after the user's rung-2 decision). Everything below is Python simulation on
snoke; nothing touches RTL or the board.

**Every number is cited `path:line`.** PPL figures cite the `"ppl"` field of
their run's json; every derived figure (Δ, %, bytes, ms, spreads) cites the
line of `evidence/qwen_next/nvfp4/n36_rung1_table.log` that printed it — `rung1_table.py` does the
arithmetic on snoke from the committed jsons and ASSERTS, before printing
anything, that all 21 rows share one corpus, checkpoint, window, batch,
position count, host and device (`evidence/qwen_next/nvfp4/n36_rung1_table.log:5`). Labels: **E** =
measured by a run in this directory; **D** = derived by `rung1_table.py`
(arithmetic or a model), never re-measured.

---

## 0. What was measured, and how to read the names

**Setup (all rows).** 2B checkpoint, pinned corpus `ref/ppl_corpus_eval.txt`
(`--expect-corpus-sha256 6bf4f867…`), window 512, batch 4, 24,528 scored
positions, snoke, CPU float32, shipped venv, `--threads 6`
(`evidence/qwen_next/nvfp4/n36_rung1_table.log:5`). The bf16 anchor is the committed
`evidence/qwen2b/q1/ppl_2b_bf16_snoke.json`, re-used (same host, same venv).

**The shipped point is `all:w4g128 --act a8`** — W4 g128 weights AND the A8
activation rule — so its gap to bf16 (+2.514444, `evidence/qwen_next/nvfp4/n36_rung1_table.log:11`) is
larger than the familiar V1 weight-only gap (+1.830886 here,
`evidence/qwen_next/nvfp4/n36_rung1_table.log:12`; the 2B study's V1, 14.176885, also carried
emb16+cw13, whose increment it measured at −0.000299 —
`docs/QWEN2B_QUANT_STUDY.md:85`, `:38`). **% of the shipped gap left** = ΔPPL / that
+2.514444.

**`all:` resolves to the seven W4 matvec classes** (qkv, o_proj, gate_up,
down, dn_in, dn_out, lm_head — `evidence/qwen_next/nvfp4/n14_ppl_2b_nvfp4.json:140-148`);
`emb` and `dn_conv` stay bf16 float in every row (`evidence/qwen_next/nvfp4/n14_ppl_2b_nvfp4.json:83`,
`evidence/qwen_next/nvfp4/n14_ppl_2b_nvfp4.json:47`), exactly as the anchor.

### 0.1 The format, as coded (`ref/nvfp4.py`, selftest `evidence/qwen_next/nvfp4/n25_nvfp4_selftest.log`)

* **Element E2M1**, ±{0, 0.5, 1, 1.5, 2, 3, 4, 6}; round to nearest on the
  grid, **ties to the even code** (the neighbour with mantissa bit 0: 0.25→0,
  0.75→1, 1.25→1, 1.75→2, 2.5→2, 3.5→4, 5→4); |v|>6 saturates. One code
  table serves quantize and dequantize.
* **Stage 1: UE4M3 per 16 along K** — bias 7, 3 mantissa bits, max 448,
  **subnormals kept** (down to 2^-9; below 2^-10 → 0, the block reads zero),
  RNE ties to even mantissa, saturating at 448. It encodes amax(block)/6/s_t.
* **Stage 2: FP32 s_t = amax/(6·448)**: weights, per matrix (of the rotated
  matrix under RHT); activations, per token (`:dyn`) or per input site from a
  calibration pass (`:static`, C3 — `ref/calib_stats_2b*.npz` carry mean|x|
  and E[x²], not amax, so a pass over `ref/ppl_corpus_calib.txt`, sha256
  `522afbca…`, 32,768 tokens, weights as injected, activations float —
  `evidence/qwen_next/nvfp4/n30_ppl_2b_nvfp4h_hd_actstatic.json:5-8`).
* **Bits/weight** 4 + 8/16 = **4.5**; DDR row = ceil(K/128) weight beats +
  ceil(K/16/64) scale beats, padded to 64-byte beats, + one FP32 s_t per
  matrix (every K here is a multiple of 1024, so exactly 4.5 packed).
* **RHT** — one random ±1 vector D per **input site** (q/k/v share one,
  gate/up one, the four DeltaNet in_proj one, the head one; 97 sites at 2B —
  `evidence/qwen_next/nvfp4/n27_ppl_2b_nvfp4h_hd.json:160`), shared by every 16-block:
  **M = H16·diag(D)/4 (signs first)**. Weights are rotated offline and
  injected as Q(W Rᵀ)·R; the `--act` hook computes Rᵀ·Q(R x); the hook
  asserts per site that its signs are the weight's.
* **A8 (Ruling C5)** — the rule found in the shipped path
  (`fixedpoint.dyn_quant_i8` as `layer_fixed.matvec_fx` feeds it): per matvec
  input vector (= per token) a power-of-two scale 2^e, e the smallest with
  round_half_away(amax/2^e) ≤ 127, x8 = clip(round_half_away(x/2^e), ±127) —
  dynamic, not calibrated (`evidence/qwen_next/nvfp4/n21_ppl_2b_bf16_a8.json:137`). Selftest G checks
  it equals `dyn_quant_i8` bit for bit on 150 int16 vectors. On an RHT site
  it quantizes the rotated input (the hardware would have to rotate).
* **Hooked sites (C4)** — every `nn.Linear` of the body plus the LM head
  (applied in `compute_ppl`'s head path): 187 matvecs on 97 input sites —
  qkv 18 on 6, o_proj 6/6, gate_up 48/24, down 24/24, dn_in 72/18, dn_out
  18/18, lm_head 1/1 (`evidence/qwen_next/nvfp4/n18_ppl_2b_nvfp4_actdyn.json:6-35`).

### 0.2 A defect in the brief's RHT formula, found and fixed during rung 1

The brief writes the rotation as x' = (D·H16/4)·x. **In that order D only
flips the signs of the outputs, and every quantizer here is sign-symmetric**
(Q(D y) = D·Q(y) bit for bit), so D cancels on the way back and **every seed
gives the same model**: seed 1 reproduced seed 0's nll_sum bit for bit
(`evidence/qwen_next/nvfp4/n36_rung1_table.log:6`). The four rows run that way (n15, n17, n19, n20)
therefore measured a **plain, un-randomized block-16 Hadamard**; they are kept
below as "plain H" and superseded. The code now uses H16·diag(D)/4 (the
standard randomized Hadamard; commit 44a105c; the json gains `rht_form`;
selftest C asserts both that the seed bites and that the old order is inert).

---

## 1. THE 2B TABLE

### Panel A — quality

| row | run | weights | activations | PPL (E) | ΔPPL vs bf16 (D) | Δ % (D) | % of shipped gap left (D) | cite |
|---|---|---|---|---|---|---|---|---|
| **bf16 anchor** | re-used | bf16 | float | **12.346298** | — | — | 0 % | `evidence/qwen2b/q1/ppl_2b_bf16_snoke.json:123`, `evidence/qwen_next/nvfp4/n36_rung1_table.log:10` |
| **SHIPPED** W4 g128 + A8 | n11 | w4g128 | a8 | **14.860742** | +2.514444 | +20.37 % | 100.00 % | `evidence/qwen_next/nvfp4/n11_ppl_2b_w4g128_a8.json:293`, `evidence/qwen_next/nvfp4/n36_rung1_table.log:11` |
| W4 g64 GPTQ + A8 | n13 | w4g64gptq | a8 | 13.423831 | +1.077533 | +8.73 % | 42.85 % | `evidence/qwen_next/nvfp4/n13_ppl_2b_w4g64gptq_a8.json:315`, `evidence/qwen_next/nvfp4/n36_rung1_table.log:13` |
| NVFP4 + A8 | n16 | nvfp4 | a8 | 14.028509 | +1.682211 | +13.63 % | 66.90 % | `evidence/qwen_next/nvfp4/n16_ppl_2b_nvfp4_a8.json:293`, `evidence/qwen_next/nvfp4/n36_rung1_table.log:16` |
| **NVFP4 + RHT + A8** | n28 | nvfp4h | a8 (rotated) | **13.494146** | +1.147848 | +9.30 % | 45.65 % | `evidence/qwen_next/nvfp4/n28_ppl_2b_nvfp4h_hd_a8.json:391`, `evidence/qwen_next/nvfp4/n36_rung1_table.log:17` |
| **full NVFP4, dyn** | n18 | nvfp4 | nvfp4:dyn | **14.305507** | +1.959209 | +15.87 % | 77.92 % | `evidence/qwen_next/nvfp4/n18_ppl_2b_nvfp4_actdyn.json:293`, `evidence/qwen_next/nvfp4/n36_rung1_table.log:18` |
| full NVFP4 + RHT, dyn | n29 | nvfp4h | nvfp4h:dyn | 14.710242 | +2.363944 | +19.15 % | 94.01 % | `evidence/qwen_next/nvfp4/n29_ppl_2b_nvfp4h_hd_actdyn.json:391`, `evidence/qwen_next/nvfp4/n36_rung1_table.log:19` |
| full NVFP4 + RHT, static | n30 | nvfp4h | nvfp4h:static | 14.790656 | +2.444358 | +19.80 % | 97.21 % | `evidence/qwen_next/nvfp4/n30_ppl_2b_nvfp4h_hd_actstatic.json:496`, `evidence/qwen_next/nvfp4/n36_rung1_table.log:20` |
| *weights only:* W4 g128 | n12 | w4g128 | float | 14.177184 | +1.830886 | +14.83 % | 72.81 % | `evidence/qwen_next/nvfp4/n12_ppl_2b_w4g128.json:157`, `evidence/qwen_next/nvfp4/n36_rung1_table.log:12` |
| *weights only:* NVFP4 | n14 | nvfp4 | float | 13.493740 | +1.147442 | +9.29 % | 45.63 % | `evidence/qwen_next/nvfp4/n14_ppl_2b_nvfp4.json:157`, `evidence/qwen_next/nvfp4/n36_rung1_table.log:14` |
| *weights only:* NVFP4 + RHT | n27 | nvfp4h | float | 13.420657 | +1.074360 | +8.70 % | 42.73 % | `evidence/qwen_next/nvfp4/n27_ppl_2b_nvfp4h_hd.json:157`, `evidence/qwen_next/nvfp4/n36_rung1_table.log:15` |
| *acts only:* A8 | n21 | bf16 | a8 | 12.842898 | +0.496600 | +4.02 % | 19.75 % | `evidence/qwen_next/nvfp4/n21_ppl_2b_bf16_a8.json:285`, `evidence/qwen_next/nvfp4/n36_rung1_table.log:21` |
| *acts only:* NVFP4 dyn | n22 | bf16 | nvfp4:dyn | 13.153599 | +0.807301 | +6.54 % | 32.11 % | `evidence/qwen_next/nvfp4/n22_ppl_2b_bf16_actnvfp4dyn.json:285`, `evidence/qwen_next/nvfp4/n36_rung1_table.log:22` |
| ~~plain H, weights only~~ | n15 | nvfp4h (inert D) | float | 13.818605 | +1.472308 | +11.93 % | 58.55 % | `evidence/qwen_next/nvfp4/n15_ppl_2b_nvfp4h.json:157`, `evidence/qwen_next/nvfp4/n36_rung1_table.log:23` |
| ~~plain H + A8~~ | n17 | nvfp4h (inert D) | a8 | 13.843699 | +1.497401 | +12.13 % | 59.55 % | `evidence/qwen_next/nvfp4/n17_ppl_2b_nvfp4h_a8.json:391`, `evidence/qwen_next/nvfp4/n36_rung1_table.log:24` |
| ~~plain H, full, dyn~~ | n19 | nvfp4h (inert D) | nvfp4h:dyn | 15.074142 | +2.727844 | +22.09 % | 108.49 % | `evidence/qwen_next/nvfp4/n19_ppl_2b_nvfp4h_actdyn.json:391`, `evidence/qwen_next/nvfp4/n36_rung1_table.log:25` |
| ~~plain H, full, static~~ | n20 | nvfp4h (inert D) | nvfp4h:static | 15.136248 | +2.789950 | +22.60 % | 110.96 % | `evidence/qwen_next/nvfp4/n20_ppl_2b_nvfp4h_actstatic.json:496`, `evidence/qwen_next/nvfp4/n36_rung1_table.log:26` |

(All `nXX_…` paths are under `evidence/qwen_next/nvfp4/`.)

**Ranking of the current rows** (`evidence/qwen_next/nvfp4/n36_rung1_table.log:27`): bf16 12.346298 <
bf16+A8 12.842898 < bf16+NVFP4-act 13.153599 < NVFP4+RHT w-only 13.420657 <
**GPTQ g64 + A8 13.423831** < NVFP4 w-only 13.493740 < **NVFP4+RHT + A8
13.494146** < NVFP4 + A8 14.028509 < W4 g128 w-only 14.177184 < **full NVFP4
dyn 14.305507** < full NVFP4+RHT dyn 14.710242 < full NVFP4+RHT static
14.790656 < **SHIPPED 14.860742**.

**The two readings that matter.**
(a) **Full NVFP4 (weights AND activations) beats the shipped point, but not
by much and not best:** the best full-NVFP4 row is the one WITHOUT the RHT,
14.305507, 0.555235 PPL better than shipped (`evidence/qwen_next/nvfp4/n36_rung1_table.log:28`) —
77.92 % of the shipped gap is left. Every A8-activation row with IMPROVED
weights beats it — W4 g64 GPTQ + A8 (n13, 13.423831), NVFP4 + RHT + A8 (n28,
13.494146) and NVFP4 + A8 (n16, 14.028509) — while the shipped row, which
also keeps A8, does not (14.860742). GPTQ g64 needs no new datapath and fewer **[CORRECTED 2026-09-24: false for the shipped 9B engine — see docs/NVFP4_STUDY.md Panel B note and §9 below]**
bytes (Panel B); the NVFP4 + RHT + A8 row needs the rotation hardware (its
activations are "a8 (rotated)": a 16-point butterfly ahead of the A8
quantizer) as well as the NVFP4 weight decode.
(b) **The NVFP4 activation format is the weaker half.** Alone on bf16 weights
it costs +0.807301 against A8's +0.496600 (`evidence/qwen_next/nvfp4/n36_rung1_table.log:21-22`), i.e.
block-16 FP4 activations lose more than the shipped per-token int8, and the
RHT makes them worse, not better (§2).

### Panel B — cost (bytes are the packed DDR rows; 9B columns are a model, D)

| row | packed b/w (matvec) | bytes/token 2B | × shipped | 9B Δ ms/token (D) | 9B ms/token (D) | 9B tok/s (D) | cite |
|---|---|---|---|---|---|---|---|
| bf16 anchor | 16.000 | 3,762,552,832 | 3.7766 | n/a | n/a | n/a | `evidence/qwen_next/nvfp4/n36_rung1_table.log:36` |
| **SHIPPED** W4 g128 (+A8) | 4.2366 | 996,282,368 | 1.0000 | +0.000 | 137.121 | 7.293 | `evidence/qwen_next/nvfp4/n36_rung1_table.log:37` |
| W4 g64 GPTQ (+A8) | 4.2500 | 999,428,096 | 1.0032 | +1.649 | 138.770 | 7.206 | `evidence/qwen_next/nvfp4/n36_rung1_table.log:39` |
| **every NVFP4 row** (with or without RHT, any act) | 4.5000 | 1,058,218,732 | 1.0622 | **+4.946** | 142.067 | 7.039 | `evidence/qwen_next/nvfp4/n36_rung1_table.log:40-46` |

* **2B bytes/token** is the harness's new `bytes_per_token_matvec` field; the
  shipped row reproduces `ref/scripts/bytes_per_token.py`'s 2B figure
  996,282,368 exactly (asserted, `evidence/qwen_next/nvfp4/n36_rung1_table.log:31`). The 2B's shipped
  rate is 4.2366 b/w (K=2048 rows pay a whole scale beat), so NVFP4 costs
  ×1.0622 the bytes at 2B.
* **The 9B model (D).** At 9B every K is a multiple of 1024, so both formats
  pack at their ideal rates: every image's row stride grows by the same
  ×1.090909 and the busiest channel with it (4,091,805,696 → 4,463,789,028
  B/token; busiest channel 1,025,925,120 → 1,119,191,040 B,
  `evidence/qwen_next/nvfp4/n36_rung1_table.log:32-34`). The token's weight-streaming term is
  54.408 ms of the 131.138 ms testbench token
  (`evidence/qwen9b/bn/BN_CENSUS.md:41`, `:18`; board 137.121 ms, `:19`), so
  the modelled cost is 54.408 × 0.090909 = **+4.946 ms/token → 142.067 ms,
  7.039 tok/s vs 7.293** (`evidence/qwen_next/nvfp4/n36_rung1_table.log:40`). It prices the weight
  stream only: the NVFP4 activation path (block-16 quantizer, UE4M3 scale
  generation, the 16-point butterfly for RHT) is new hardware not in this
  number, and the engine's timing closure is not modelled at all.
* The W4 g64 GPTQ row costs +1.649 ms at 9B (×1.030303 busiest channel,
  `evidence/qwen_next/nvfp4/n36_rung1_table.log:33`, `:39`) and needs no new datapath (the shipped W4
  engine at g64 — `docs/QWEN2B_QUANT_STUDY.md` Panel B). **[CORRECTED 2026-09-24: false for the shipped 9B engine — see docs/NVFP4_STUDY.md Panel B note and §9 below]**

---

## 2. Decomposition (the study's §3 style): weight damage vs activation damage vs RHT

All ΔPPL vs bf16; interaction = combined − weight − activation
(`evidence/qwen_next/nvfp4/n36_rung1_table.log:55-62`).

| pairing | weight damage | activation damage | combined | interaction |
|---|---|---|---|---|
| W4 g128 × A8 (shipped) | +1.830886 | +0.496600 | +2.514444 | +0.186958 |
| NVFP4 × A8 | +1.147442 | +0.496600 | +1.682211 | +0.038169 |
| NVFP4 × NVFP4 act (dyn) | +1.147442 | +0.807301 | +1.959209 | +0.004467 |

| RHT effect, same activations | randomized RHT (H·D) | plain H (inert D) |
|---|---|---|
| weights only | **−0.073082** | +0.324866 |
| + A8 | **−0.534363** | −0.184809 |
| + NVFP4 act, dyn | **+0.404735** | +0.768634 |

* **Weights:** NVFP4 weight damage is +1.147442 against W4 g128's +1.830886,
  for ×1.0622 the 2B bytes (Panel B); the RHT shaves a further 0.073082.
* **Activations:** NVFP4 activations (+0.807301) do more damage than A8
  (+0.496600). The damages add almost linearly (interactions ≤ 0.04 for
  NVFP4 weights, `evidence/qwen_next/nvfp4/n36_rung1_table.log:56-57`; +0.19 for the shipped pair,
  `evidence/qwen_next/nvfp4/n36_rung1_table.log:55`).
* **The RHT is a property of the ACTIVATION format:** it helps a lot when the
  rotated input is quantized per token to int8 (it spreads the outlier
  channels that set the single per-token scale: −0.534), a little on the
  weights, and it HURTS block-16 FP4 activations (+0.405), whose per-16
  UE4M3 scale already isolates outliers; rotating smears them over the block.
* **Scale mode:** static vs dynamic tensor scale is within seed noise (§3):
  +0.080 at seed 0 (`evidence/qwen_next/nvfp4/n36_rung1_table.log:62`), −0.040 averaged over three
  seeds (`evidence/qwen_next/nvfp4/n36_rung1_table.log:73`).

---

## 3. RHT seed sensitivity

Three seeds on each full-NVFP4 + RHT row (seed 0 is the row itself;
`evidence/qwen_next/nvfp4/n36_rung1_table.log:65-73`):

| row | seed 0 | seed 1 | seed 2 | mean | spread (max−min) | % of shipped gap |
|---|---|---|---|---|---|---|
| nvfp4h + nvfp4h:dyn (the better RHT row at seed 0) | 14.710242 (n29) | 14.665678 (n31) | 14.885853 (n32) | 14.753924 | 0.220174 | 8.76 % |
| nvfp4h + nvfp4h:static | 14.790656 (n30) | 14.659090 (n33) | 14.691098 (n34) | 14.713615 | 0.131566 | 5.23 % |

* The seed matters at the 0.1–0.2 PPL level — larger than the static/dynamic
  difference, and 271× the P40's fp16 delta (`evidence/qwen_next/nvfp4/n36_rung1_table.log:77`).
* **No seed rescues the RHT for full NVFP4:** the best of six, 14.659090, is
  still worse than the no-RHT full row 14.305507
  (`evidence/qwen_next/nvfp4/n36_rung1_table.log:72`).
* The best full-NVFP4 row (n18) has no RHT, so it has no seed; the seeds were
  run on the best RHT rows, which is where a seed exists.

---

## 4. Rung 0 (the checks these rows stand on)

* **Backward compatibility (C1): PASS.** The pre-change tree (n01, commit
  7c5d0f3) and the post-change harness (n08, be32d23) score 0.8B
  `all:w4g128` on snoke with byte-identical nll_sum, ppl, n_positions,
  total_bits, avg_bits_per_weight and the 101-line classes block
  (`evidence/qwen_next/nvfp4/n10_c1_byte_identity.log:26-31`, `:37`). Secondary: vs the committed
  cross-host json (torch 2.6.0+cu124), nll_sum differs by 1.812e-10 relative
  (`evidence/qwen_next/nvfp4/n10_c1_byte_identity.log:33`).
* **Self-tests:** `ref/nvfp4.py --selftest` PASS (`evidence/qwen_next/nvfp4/n25_nvfp4_selftest.log`,
  after the RHT fix; first pass n04; n02 FAILED on an over-claimed assertion
  that the RHT always lowers weight error — false, dropped);
  `ref/perplexity_eval.py --selftest` PASS with the new section H
  (`evidence/qwen_next/nvfp4/n26_ppl_eval_selftest.log`); `ref/scripts/bytes_per_token.py --selftest`
  still PASS (`evidence/qwen_next/nvfp4/n07_bytes_per_token_selftest.log`).
* **P40 (C2): FEASIBLE.** A separate venv `/home/cah/.venv_nvfp4_cuda`
  (torch 2.12.0+cu126, whose arch list carries sm_60, runs on the P40's sm_61;
  transformers 5.11.0 — `evidence/qwen_next/nvfp4/n03_p40_venv.log:166-177`). The 2B bf16 anchor in
  fp16 on the P40: PPL 12.346783 vs CPU 12.346298, +0.000485 (3.9e-5
  relative), **within the 0.001 PPL tolerance** (1/16 of the smallest gap the
  2B study ranked on, 0.016537 — `docs/QWEN2B_QUANT_STUDY.md:308`); eval
  17.5 s vs 404.9 s, **23.2×** (`evidence/qwen_next/nvfp4/n36_rung1_table.log:76-78`). Rung 1 stayed on
  CPU (the 2B is cheap, and the `--act` hooks run in numpy on the CPU
  whatever the device, so act rows would not get the 23×). The 9B fits in
  fp16 on paper (17.98 GiB of weights in 23 GB); not tried.

---

## 5. What this does NOT establish

* **PPL is not the fixed-point top-1 gate.** Every row is float fake-quant in
  a float32 torch model; nothing is bit-exact, nothing ran on silicon.
* **A8 is modelled in float** (no upstream int16 grid, no e ≥ 0 floor).
* **The 9B cost column is the streaming term only** (D); the NVFP4
  activation path, the RHT butterfly and `matvec_engine` timing are unpriced.
* **2B ≠ 9B.** Rung 2 (the 9B anchor and the top rows) is the user's call.
* `nvfp4gptq` (GPTQ onto the NVFP4 grid) was not run — optional in the brief,
  and it would cost well over an hour (the 2B GPTQ build alone took 3,187 s
  under load, `evidence/qwen_next/nvfp4/n13_ppl_2b_w4g64gptq_a8.log:22`).

## 6. Traceability

| what | where |
|---|---|
| quantizers, codecs, RHT, A8, accounting, selftest | `ref/nvfp4.py` |
| harness: `nvfp4`/`nvfp4h`, `--act`, `--rht-seed`, `--device`, json fields | `ref/perplexity_eval.py` |
| provenance wrapper (every log's header: host, tree, cmd) | `evidence/qwen_next/nvfp4/nvfp4_run.sh` |
| the table's arithmetic and asserts | `evidence/qwen_next/nvfp4/rung1_table.py` → `evidence/qwen_next/nvfp4/n36_rung1_table.log` |
| C1 check | `evidence/qwen_next/nvfp4/c1_identity.sh` → `evidence/qwen_next/nvfp4/n10_c1_byte_identity.log` |
| P40 venv | `evidence/qwen_next/nvfp4/p40_venv.sh` → `evidence/qwen_next/nvfp4/n03_p40_venv.log` |

---

## 9. Corrections (added 2026-09-24, after rung 2; the lines above keep their numbers because `docs/NVFP4_STUDY.md` cites them)

1. **GPTQ g64 does need new hardware on the shipped 9B engine.** The marked sentences at lines 130 and 167 hold for the 2B engine only. G3.3 deleted the g64 row format, and at the 9B NG = 96 it is unrepresentable (`rtl/matvec_engine.sv:25-28`). Restoring it also doubles the scale bank from NSCAL = 96 to 192 (`rtl/matvec_engine.sv:179-182`). That bank feeds the NSCAL:1 `scales_q` mux, which owns a +0.001 ui_clk cone (`rtl/matvec_engine.sv:117-118`). See `docs/NVFP4_STUDY.md` §1, the Panel B note.
2. **Reading (b) in §1 does not hold at 9B.** It says "the NVFP4 activation format is the weaker half". At 9B, NVFP4 dynamic activations cost LESS than A8: +0.223285 against +0.490651, the reverse of the 2B (`evidence/qwen_next/nvfp4/n63_rung2_table.log:65-67`; `docs/NVFP4_STUDY.md` §3.1).
3. **The final-tree C1 proof is n43/n44, not n08/n10.** §4 names only n08/n10 at be32d23. The byte-identity proof on the final tree is n43 (at cabacee) checked by n44: PASS (`evidence/qwen_next/nvfp4/n44_c1_byte_identity_final.log`).
4. **`evidence/qwen_next/nvfp4/n24_ppl_2b_nvfp4h_actdyn_seed2.log` is committed truncated.** It was aborted at window 4/48 when the inert-RHT defect was found. It has no json and nothing cites it.
5. **Six selftest logs carry unexplained `+dirty` stamps.** n05, n06, n07, n25, n26 and n39 predate the wrapper's dirty-detail fix (fix round 1), so their stamps say nothing about what was dirty. The clean-HEAD selftest runs are `evidence/qwen_next/nvfp4/n40_nvfp4_selftest_HEAD.log` and `evidence/qwen_next/nvfp4/n41_ppl_eval_selftest_HEAD.log`.
