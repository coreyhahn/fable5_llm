# R-c gate — the 2B W8 (V5) artifact chain, and the one thing that stops it

**Verdict: COMPLETE. The R-c sim gate is GREEN — the first full 2B model
simulation in this project's history passes end to end.**

```
TB_SEQ_CHIP PASS: model_w8_2b_s1.e — 68,503 records, 88,534,927 cycles
                  (354.140 ms @250MHz), 6/6 tokens == golden,
                  16,384 scratch words, tcnt 6
  TOK 279, 314, 279, 369, 11751, 13   — the generator's argmaxes exactly
  weight beats 45,675,360 on CHANNEL 0 (miss 0)   ddr beats 239,345 (miss 0)
  decerr 0, non-OK 0, fetch-empty stalls 48, reset never violated
```

(The weight-beat counter is PER CHANNEL and this run's TB printed only
`w_nbeats[0]`; the four per-channel packs are within 1 % of each other, so
the fabric total is ~4x that, ~182 M beats. `tb_seq_chip.sv` now prints the
sum and the per-channel split, so no later run has to be read with that
caveat — the token smoke below is the first to carry the new line.)

Getting there found **three** latent walls in that first full-2B run — all
pre-existing, none W8-related, none introduced by Task 4, and **none
exposing silicon**. All three are now fixed and gated:

| | what | where | status |
|---|---|---|---|
| **6** | ALU element count was 12 bits; the 2B MLP DYNQ8 is 6144 | `rtl/vec_alu.sv` + `layer_chan.sv` | **FIXED** — 13 bits, ahead of Task 5's synthesis |
| **7** | the chip checker read a 32K scratch with a 14-bit index | `tb/tb_seq_chip.sv` | **FIXED** — width derived from `MAXMEM` + address guard |
| **8** | the chip TB never programmed the `EMBLOG2` row stride | `tb/tb_seq_chip.sv` | **FIXED** — programmed from the artifact + readback |

Walls 7 and 8 were both **TB host-model gaps at a new-geometry corner** and
**neither touched the RTL, the golden, or the artifacts** — see the pattern
note in §5c, which is the R-d de-risking story.

**Wall 6 — the ALU element count. FOUND, FIXED, AND GATED IN THIS TASK**
(controller ruling, §5):

> `rtl/vec_alu.sv` took the ALU element count as a 12-bit `cfg_len`
> (`rtl/layer_chan.sv`, `.cfg_len(arg0[15:4])`), so 4095 was the ceiling.
> The Qwen3.5-2B MLP quantizes its whole `FFN = 6144` intermediate in ONE
> DYNQ8 (`ref/gen_layer_script.py:1556`), and `6144 & 0xFFF = 2048`.

Nothing in the chain could see it: the generator emitted `ARG0 = 0x18000`
unmasked, `ref/seq_model.py` decoded the count with a **14-bit** mask, and
the `.txt`/`.seq`/golden sides therefore all agreed with each other while
the RTL alone ran the wrong length. The count is now 13 bits
(`arg0[16:4]`), both encoders refuse what they cannot encode, the golden's
bound mirrors the hardware field exactly, and the widening is proven
invisible at 0.8B three independent ways (§5, §6).

That unblocked the python lockstep — **`seq_model --gate` on the full 2B W8
stream now PASSES, 1770/1770 checkpoints bit-exact** — and the host-driven
`tb_layer_chan` at the 2B geometry, which now passes 88,158 checks where it
failed before.

**Wall 7 — a TESTBENCH indexing bug. DIAGNOSED, RULED, AND FIXED** (§5b).
`tb_seq_chip.sv` read the 32,768-word scratch with a 14-bit index at two
sites, so every checked address `>= 16384` aliased down by 16K — into the
y32 staging window, whose contents a `.seq` run is explicitly licensed to
leave different from the `.txt` run.

**Neither the RTL nor the golden was at fault — the CHECKER was**, and that
was settled before any code moved, by a falsifiable prediction tested
against `ref/seq_model.py` with no rebuild at all: the values the TB
printed as "got" at `0x5c00+k` are `seq_model`'s true contents at the
*aliased* address `0x1c00+k` (**21/21**), and its "expected" values are the
golden at the real address (**21/21**). The RTL held the right value at
both. Fixed structurally — the index width is now DERIVED from `MAXMEM`,
plus a `$fatal` guard on any golden address the checker cannot index —
testbench-only, and proven behaviour-neutral: the 0.8B replays come back
**cycle-identical**.

**Wall 8 — the chip TB never programmed the EMB row stride. PROVEN AND
FIXED** (§5c; closed by gate rows 35-38). With walls 6 and 7 cleared, the
FULL 2B W8 replay ran to completion (65 min, 88.5 M cycles, 68,503 records)
and failed with every generated token wrong. `rtl/seq_unit.sv` keeps the EMB row
stride in CSR `0x60 EMBLOG2`, reset **11** (2048 B rows); this 2B artifact
declares 4096 B rows (EMBLOG2 **12**); and the string `EMBLOG2` **does not
appear in `tb/tb_seq_chip.sv`**, whose host BFM therefore leaves it at
reset. `sw/seq_run.py:1762` programs it on silicon, so **R-d is not
exposed**, and `ref/seq_model.py` takes the stride from the artifact, which
is why the golden was green. Proven by the same falsifiable-prediction
method as wall 7: feeding the golden executor a 2048-B-stride table
reproduces the RTL's six wrong tokens **exactly**. Testbench-only again.
The TB now programs `EMBLOG2` from the artifact and reads it back, the
fail-fast gained token coverage that catches this in minutes (4-of-4 RED
against the pre-fix BFM), and **the replay is green** — gate rows 35-38.

Provenance: every numeric step ran ON SNOKE through
`evidence/qwen2b/rc/t4_run.sh`, which stamps host / date / tree / venv into
each log. Branch `qwen2b`, stacked on `999df81` (T3).

---

## 1. Gates

| # | gate | result | log |
|---|---|---|---|
| 1 | producers RED (both refuse before implementation) | **RED OK** | `t4_01_red_producers.log` |
| 2 | producers GREEN (W8 pack + per-channel `.wimg`) | **PASS 5/5** | `t4_02_green_producers.log`, `t4_15_green_producers_final.log` |
| 3 | `regen_gate.sh` + `.e4` lock, BEFORE the emitter edits | **PASS** | `t4_03_locks.log` |
| 4 | 1-layer 2B W8 artifacts, 4 seeds, repacked | **PASS** | `t4_04_smoke_scripts.log` |
| 5 | 1-layer 2B W8 **chip** smoke, 4 seeds | **FAIL** → §5 | `t4_05_smoke_chip.log` |
| 6 | **2B W8 full artifact set** (187 images + emb + stream) | **BUILT** | `t4_06_gen2b_noallowclip.log` |
| 7 | runtime range audit, 2B W8 | FAIL (known classes only — §3) | same |
| 8 | 2B **W4 control** at the same S=4 (the "is it W8?" test) | **no new class at W8** | `t4_08_gen2b_w4_control.log` |
| 9 | 3-cell RTL bisect {0.8B,2B} x {W4,W8} x nch=4 | **isolates 2B, exonerates W8** | `t4_07_bisect_n4.log` |
| 10 | host-driven `layer_chan` TB at 2B (no seq/movers/mvchan) | **FAIL — same** | `t4_09_layerchan_2b.log` |
| 11 | `seq_model --gate`, 2B W8 full stream | **REFUSED** (§6) | `t4_10_seqgate_2b_w8.log` |
| 12 | `t3_audit.py` on the REAL 2B W8 repacked stream | **PASS**, 3/3 mutations killed | `t4_12_audits_2b.log` |
| 13 | `regen_gate.sh` + `.e4` lock, AFTER every edit | **PASS** (§7) | `t4_13_locks_after.log` |
| 14 | `seq_selftest` / `serve_test` / `chat_seq --selftest` | **2735 / 85 / 337, 0 failed** | `t4_14_sw_selftests.log` |
| 15 | `seq_model.py --selftest` (W8 + REPACK) | **PASS** | `t4_15_green_producers_final.log` |
| 16 | fidelity `--w8 --res-scale 4` at 2B | **90/108**, best 2B fixed-point score measured (§4) | `t4_11_fidelity_2b_w8.log` |
| 17 | ALU `arg0[16]` spare-bit scan, `scan_spare_bits.py` | **never set in 248,218 ALU records** (§5) | `t4_17_spare_bits_alu_len.log` |
| **--** | **--- wall 6 fixed below this line: the 13-bit widening ---** | | |
| 18 | `tb_vec_alu` directed 6144-element pair, OLD 12-bit RTL | **RED** (4096/6144 wrong) | `t4_18_red_vec_alu_len.log` |
| 19 | `tb_vec_alu` same pair, WIDENED RTL, 4 seeds + amaxlong | **GREEN** | `t4_19_green_vec_alu_len.log` |
| 20 | frozen TB set: `tb_vec_alu`, `tb_vecnorm`, `tb_ru2_diff`, `tb_layer_chan`, `tb_token`, `tb_seq_layer` | **6/6 PASS** | `t4_20_widen_frozen_gates.log` |
| 21 | no emitted byte moved (regenerate + `cmp`) | **PASS**, §2's shas stand | `t4_21_bytes_unmoved.log` |
| 22 | `regen_gate.sh` + `.e4` lock, after the widening | **REGEN_GATE_PASS / E4_LOCK_PASS** | `t4_22_locks_after_widen.log` |
| 23 | **`seq_model --gate`, 2B W8 full stream** | **PASS** — 1770/1770 checkpoints bit-exact | `t4_23_seqgate_2b_w8_after_widen.log` |
| 24 | 1-layer 2B W8 chip smoke, widened RTL | **FAIL at `ML_DDST`** → §5b | `t4_24_smoke_chip_after_widen.log` |
| 25 | `seq_selftest` / `serve_test` / `chat_seq`, after the widening | **2735 / 85 / 337, 0 failed** | `t4_25_sw_selftests_after_widen.log` |
| 26 | host-driven `tb_layer_chan` at 2B, widened RTL | **PASS** — 88,158 checks (was FAIL) | `t4_26_layerchan_2b_after_widen.log` |
| 27 | 0.8B chip replays after the widening (regression) | **PASS, CYCLE-identical** | `t4_27_bisect_after_widen.log` |
| 28 | wall-7 side-bisect: is the RTL or the golden wrong? | **NEITHER — 21/21, the TB read the wrong word** | `t4_28_wall2_probe.log` |
| 29 | wall-7 fix confirmed in a SCRATCH TREE (repo untouched) | **4/4 smoke seeds PASS**, 16,384 words each | `t4_29_wall2_scratch_experiment.log` |
| **--** | **--- wall 7 fixed below this line: the derived index + guard ---** | | |
| 30 | 0.8B w3 chip pair + 2B 4-seed smoke, on the FIXED repo TB | **PASS / 4-of-4 PASS** | `t4_30_wall2_fix_gates.log` |
| 31 | **`.chip` golden + 4 per-channel `.wimg` for the FULL 2B stream** | **BUILT** — 68,503 records, 6 tokens, 4x ~462 MiB | `t4_31_full2b_chip_replay.log` |
| 32 | 0.8B chip replays after the TB fix (cycle identity) | **PASS, CYCLE-IDENTICAL** | `t4_32_cycle_identity_after_tbfix.log` |
| 33 | full 2B W8 chip replay, first attempt | **FAIL — wall 8** (§5c): ran to completion, every token wrong | `t4_31_full2b_chip_replay.log` |
| 34 | wall-8 root cause proven against the golden executor | **PROVEN** — a 2048-B-stride emb reproduces all 6 wrong tokens exactly | `t4_33_wall8_probe.log` |
| **--** | **--- wall 8 fixed below this line: EMBLOG2 from the artifact + token coverage ---** | | |
| 35 | 2B **token** smoke, 4 seeds (EMB 2 / AMAXL 2 / JMP 2) | **BUILT** — 1,244 records, 2 tokens | `t4_34_tok_smoke_scripts.log` |
| 36 | token smoke vs a BFM with no EMBLOG2 write / vs the repo TB | **RED 4-of-4 FAIL -> GREEN 4-of-4 PASS** | `t4_35_wall8_red_green.log` |
| 37 | 0.8B w3 pair: existing `.chip` (default 11) and regenerated | **PASS both ways, CYCLE-IDENTICAL** (1,355,737 / 2,272,141) | `t4_36_final_gates_and_full_replay.log` |
| 38 | review folds: `tb_ru2_diff` with 3584 in `gen_len()`, 6 configs | **PASS**, `len_max=3584` in every census | `t4_38_fold_locks.log` |
| 39 | fold 10 — the ARG-field asserts EXECUTED on every regenerated record | **REGEN_GATE_PASS / E4_LOCK_PASS**, 2735/85/337 | `t4_38_fold_locks.log`, `t4_39_dnz_locks.log` |
| 40 | **THE R-c SIM GATE — full 2B W8 chip replay, re-run** | **PASS** — 88,534,927 cycles, 6/6 tokens match, 16,384 words, 45.7 M weight beats on chan 0, 0 misses, 0 decerr | `t4_36_final_gates_and_full_replay.log` |

---

## 2. The 2B W8 artifact set (Step 1 — BUILT)

```
FABLE5_MODEL=2b SEQ_PROFILE=epsnorm SEQ_NCH=4 SEQ_REPACK=1 \
  SEQ_EMIT=tb/scripts/w5/model_w8_2b_s1.e \
  gen_model_script.py tb/scripts/w5/model_w8_2b_s1.txt 1 3 \
  --res-scale=4 --wq=w8
```

Reproduced exactly, and note the `W8_FLAGS` override — the make target's
DEFAULT is `--res-scale=4 --allow-clip --wq=w8`, so the run of record had to
say otherwise:

```
make -C tb w8_2b_model_script MODELPY=/home/cah/.venv/bin/python \
     'W8_FLAGS=--res-scale=4 --wq=w8'
```

`--allow-clip` was deliberately NOT passed: the honest default is the one
that reports (§3). The artifacts are written BEFORE the audit verdict, so
the set below is complete and is byte-for-byte what an `--allow-clip` run
produces — only the exit code and the closing banner differ. The make
target keeps `--allow-clip` in its default because that is the recipe a
routine rebuild wants; this gate deliberately overrode it.

| fact | value |
|---|---|
| checkpoint header sha256 | `ccba2c1f645fe59268f89ee7ea552e02ce6bf0c8a087bf332fb0e3bd99bfee9d` |
| geometry | 24 layers (18 DN / 6 GQA), H=2048, FFN=6144, vocab 248,320 |
| LM head | (248320, 2048) **W8**, e=−8, sh=10 |
| embedding | int16 Q7.8 at S=4, \|q\|max **202** of 32767 |
| stream | 68,503 records / 1,096,048 B, blob 1,107,712 B, loop 3 steps, STRUCTURALLY SAFE |
| weight images | **187**, 1,936,920,576 B = **1,847.2 MiB** |
| argmax per step | 279, 314, 279, 369, 11751, 13 |

`emb \|q\|max = 202` reproduces `audit_ranges_2b_report.md` §6.6's
independently-measured `202 (0.616%)` at S=4 exactly — a free cross-check
that the S=4 seed is the one Q5 ruled.

**sha256 of the artifact set** (the artifacts stay UNCOMMITTED — they are
regenerable and total 2.9 GiB; `.gitignore` carries `tb/scripts/w5/`):

```
fa8d9349cf1d0aa618ab79e0a2565dd89adbb147b665cb49b582d83c95b05bcb  model_w8_2b_s1.e.seq
998ab2604d4ed44f396a78c292a3ddb40aaaf3244968e2f8b4b4ab58cb4cead8  model_w8_2b_s1.e.seq.json
e8d536ee95880ff399ff25ebad13b851486ea51cb32b6dd216125b6e87f8fc28  model_w8_2b_s1.e.seqdata.bin
f4eb9b25cb07f357127272edbdf7b4f2b1471eb4ebd137729cb0bee117c672c3  model_w8_2b_s1.weights.json
be2180584ce3ca8a03d8edb4c36bc31b9daa5333eb6cfb5cba90084b331c1255  model_w8_2b_s1.txt
b54db7a9fa6ba97fda253b00c7ed9a4a0afe7ba43b93b9b85c2aa3876963d3aa  model_w8_2b_s1.emb.bin
c9e6d0a61bfda3542890689c3c69620fa7681c8bc82f6aa4c3e57c9f749e66ef  - (sha256 of the 187-image sha256 list)
e6a1c0b5ff873fad88243ea1c52599a672844dd31db3aac7e23c0cd65ac0a9b2  - (the SAME 187 images in LC_ALL=C order — the value pinned since 2026-09-10)
```

### The repack, audited at production shape (`t4_12_audits_2b.log`)

```
187 images, 68503 records, nch=4, repack=True
tops 0x2d0c4000 / 0x2cdac000 / 0x2cca4000 / 0x2cca4000
chan 0..3 host spans == engine spans: 464.63 / 461.54 / 460.51 / 460.51 MiB
RANGE EQUALITY: PASS (3464 MVGO WBASEs resolved to global rows)
wid 186 (ILV LM head, 122 chunks of 2048): chunk j -> chan j%4, every row once: PASS
mutations KILLED: +32 KiB shift | ILV chunks -> packed row 0 | GLOBAL-row addressing
```

This is T3's fit PREDICTION met on the real thing, to the tenth: T3 projected
464.8 / 461.7 / 460.6 / 460.6 MiB and 1,847.3 MiB packed, measured
464.63 / 461.54 / 460.51 / 460.51 and 1,847.2 MiB. **36.3 % of the 1,280 MiB
window; FIT PASS.** EMB at `0x6000_0000` is 970.0 MiB ending `0x9CA0_0000`,
above every channel top by construction.

---

## 3. The range audit — evaluated against `audit_ranges_2b_report.md` §6

The audit FAILED (as the 0.8B production recipe's does). The question the
controller set is whether any clip class is **NEW at W8**. It is not, and
that is measured rather than argued: the same generation was run at 2B with
`--wq=w4` at the same `--res-scale=4` (`t4_08_gen2b_w4_control.log`).

| site | 0.8B W4 S=8 (frozen production) | **2B W4 S=4 (control)** | **2B W8 S=4 (V5)** |
|---|---|---|---|
| alu1 SHIFT32 | 4 | 1 | 1 |
| alu3 EMUL | 1 | 1 | 1 |
| alu5 SILU16 | 0 | **2** | **3** |
| alu6 SILU32 | 1 | **96** | **105** |
| conv Q2.13 | 82 | 68 | 70 |
| **ALU rail TOTAL** | 88 | **168** | **180** |
| S_F=13 state saturations | 8 | **21** | **21** |
| saturating (dn_slot, head) | (3,5)x8 | (3,5)x18, (4,4)x3 | **(3,5)x18, (4,4)x3** |
| gate heads the clamp CHANGES | 2 (+1 at the rail) | 5 (+1) | **5 (+1)** |
| residual \|x\|max | 7127 | 16927 (51.7 %) | 19582 (59.8 %) |
| silu 21-bit port clips | 0 | 0 | **0** |

**Reading.** Every class present at 2B W8 is present at 2B W4. The S_F
saturation count and the *identical set of saturating heads* are the same
number on both, and the gate-port clamp hits the same 5 heads — which is
`audit_ranges_2b_report.md` §6.5's independent prediction ("`dt_bias` over
int16 Q3.12: **5 / 288** at 2B") reproduced at runtime for the first time.
The growth from 0.8B (alu5/alu6 appearing, S_F 8 -> 21) is a **2B-geometry**
effect, not a W8 effect: W8 moves the counts by 5-9 % (96 -> 105, 2 -> 3,
68 -> 70), the ordinary spread between two quantizations of the same
weights. `--wq=w8` adds **no new clip class**, so the controller's
DONE_WITH_CONCERNS trigger for a new W8 clip class does **not** fire; the
`--allow-clip` trade is exactly the one the 0.8B recipe already takes.

y32 headroom is comfortable at W8: worst occupancy 22 bits of 31
(`6144x2048`, spare 9), i.e. the widened W8 accumulator is not close to
anything. DYNQ8 exponent histogram `0:4 1:24 2:39 3:44 4:68 5:157 6:192
7:16 8:36 9:2`.

### 3.1 RISK REGISTER — the 2B saturation characteristic (RULING: proceed)

**Controller ruling, 2026-08-22: PROCEED AS-IS. No format change.**

The two rows above that grow from 0.8B to 2B —

* `S_F = 13` DeltaNet state: **21** saturations of 28.3 M writes (8 at
  0.8B), on `(dn_slot, head)` `(3,5)` x18 and `(4,4)` x3;
* the gate ports: the production clamp CHANGES **5** heads' decay (2 at
  0.8B), worst `L0h13` +0.089 absolute and `L0h3` +105 % relative

— are the **production formats' known, audited characteristic**, not a
regression this task introduced and not a W8 effect:

1. They are **identical in the 2B W4 control** (21 saturations, the same
   two heads; the same 5 clamped heads). Weight width does not touch them.
2. They were **predicted before this run**: `audit_ranges_2b_report.md`
   §6.5 measured `dt_bias` over int16 Q3.12 at exactly **5/288** at 2B, and
   named `L0h13` and `L0h3` as the worst distortions. This run is that
   prediction confirmed at runtime for the first time.
3. They are **priced into every number the gate-D decision used**: Q5 ruled
   S = 4 the 2B operating point knowing the residual/clamp trade, and the
   study scored V5 with these clamps in place.

Changing a format now would re-open the datapath axis the study closed, so
it is explicitly NOT done. Both effects are bounded and deterministic
(saturation, not wrap — the pre-clamp wrap sent `L0h3` from 0.0086 to
0.9997, which is what the clamp exists to prevent).

**Carried to R-d:** the bring-up census should quantify BOTH on silicon —
the S_F saturation count per layer and the decay of the five clamped heads
— so the sim-side numbers here have a hardware counterpart rather than
staying a reference-model claim.

---

## 4. Fidelity — 2B, W8, S=4, g128 (Step 3)

`fidelity_check.py --w8 --res-scale 4 --wire-group 128 --ntok 24
--free-ntok 24` against the bf16 golden
`tb/scripts_scratch/golden_bf16_2b.npz` (same checkpoint header sha256,
re-asserted by the tool). 4 prompts x 27 teacher-forced steps + 27
free-running each. Wall time 4,930.6 s of config + 50 s of setup on snoke —
above the brief's 30-60 min estimate, because a W8 matvec moves twice the
weight bytes of the W4 runs the estimate came from. Full log
`t4_11_fidelity_2b_w8.log`, machine-readable `t4_fidelity_2b_w8.json`.

| config (2B, S=4, 108 teacher-forced steps) | top-1 | rank med | rank max | top5 ovl | `|x|`max | clips | S_F sat |
|---|---|---|---|---|---|---|---|
| exact float (the ceiling) | 108/108 | — | — | — | — | — | — |
| V2 — W4 g64 mse | 80/108 | 0.0 | 911 | 3.46 | 26465 (81 %) | 0 | 391 |
| V3 — W4 g64 + salience | 86/108 | 0.0 | 7 | 3.56 | 27820 (85 %) | 0 | 414 |
| V4 — W4 g64 + GPTQ | 85/108 | 0.0 | 68 | 3.49 | 28068 (86 %) | 0 | 380 |
| **V5 — W8 g128 (this run)** | **90/108** | **0.0** | **37** | **3.79** | **28342 (86.5 %)** | **0** | **411** |

(V2/V3/V4 rows are Q5's B-table, `evidence/qwen2b/q2/v4/GPTQ.md` §7.1. They
are g64 because W4's best wire format is g64; W8 has no g64 cadence, so
"same ruler" here means the same 108 steps at the same S=4, not the same
group size.)

**Reading. W8's float advantage does survive into fixed point.** V5 scores
**90/108**, four steps above the best W4 variant ever measured at 2B (V3's
86) and ten above the shipped-format V2 — and it does it with the highest
top-5 overlap of any row (3.79 vs 3.46-3.56) and a rank max of 37 against
V2's 911. Q5's honest caveat that "this probe cannot resolve a −0.45 float
PPL improvement" cuts the other way here: the study's V5 leaves only
**1.03 %** of the V2 weight-damage gap open, an order of magnitude more
float headroom than V4gptq's 42.6 %, and a +4 / +10-step move is exactly the
size that ladder predicts.

Per prompt (27 steps each): **25 / 19 / 21 / 25**. Free-running text is
readable and coherent on all four prompts — and notably prompt 1 does NOT
show the repetition-loop failure mode V2, V3 and V4 all exhibit there
(`" is Paris.\nThe capital of the United States is Washington, D.C.\nThe
capital of the United Kingdom is"`).

**Datapath health at S=4:** residual peak 28,342 of 32,767 (86.5 %) with
**0 clips**, i.e. the Q5 S=4 ruling still has margin at W8 — a little less
than V2's 81 % but the same regime, and S=8 would rail it exactly as Q5
found. S_F=13 saturations 411, in family with V2/V3/V4's 380-414 (this is
the frozen-RTL DeltaNet-state class, unchanged by weight width). The int16
dequant probe reports `6144x2048` |y|max 61,853 with 4,121 clips of
87.6 M and `16x2048` 68 of 124 k — the same pre-`clip16` saturation the W4
runs carry, not a W8-specific effect.

**Note the two `|x|max` figures are different measurements**, deliberately:
19,582 (59.8 %) in section 2 is the GENERATOR's 6-step prompt-1 run, 28,342
(86.5 %) here is the worst of 4 prompts x 54 steps. The longer trajectory
finds a bigger peak, as it does for every variant in the table.

**T2 carry folded here:** the config row no longer prints `mse` on a `--w8`
run. `mse` names the W4 group-scale RULE and W8 has only one
(`max|W_g|/127`); `check_w8_flags` already pins `--mse` to its default under
`--w8`, so a row reading "S=4 mse w8" was the very mislabel that check
exists to forbid. The head line now prints `rule=max|W_g|/127` too.

---

## 5. WALL 6 — the ALU element count: 12 bits, and the 2B MLP needs 13

### How it was isolated

The 1-layer 2B W8 chip smoke failed at once (that is what the cheap smoke is
for). Five experiments, each one variable:

| experiment | result | conclusion |
|---|---|---|
| `seq_model --gate` on the failing 2B W8 smoke | **PASS**, 46/46 checkpoints bit-exact | the artifacts + goldens are self-consistent; the RTL disagrees |
| cell `08_w4_n4` — 0.8B, W4, nch=4, repack, per-channel `.wimg`, NMV=4 | **TB_SEQ_CHIP PASS** | the new per-channel plumbing is correct |
| cell `08_w8_n4` — 0.8B, **W8**, nch=4, repack | **TB_SEQ_CHIP PASS**, weight beats 327,440 vs W4's 171,664 (1.91x) | **W8 works end to end on the real chip**, engine in W8 mode |
| cell `2b_w4_n4` — **2B**, W4, nch=4 | **FAIL** | it is the 2B geometry, not W8, not the repack |
| host-driven `tb_layer_chan` on the same 2B script | **FAIL**, `R[0x3400+2058]` | not seq_unit, not the movers, not `matvec_chan` — `layer_chan` alone |

The first mismatched element is 2058 — i.e. everything up to ~2048 was
right. That is the signature.

### The mechanism

`ref/gen_layer_script.py:1556` (`:1517` before this commit's guard) emits
the MLP's pre-`down_proj` DYNQ8 over
the whole FFN vector:

```python
M.alu(0, FFN, 0, GP, 0, GP + FFN)          # FFN = 3584 at 0.8B, 6144 at 2B
```

`Mach.alu` packed `op | (n << 4)` with no range check, producing
`ARG0 = 0x18000`. `0455999:rtl/layer_chan.sv:545` wires `.cfg_len(arg0[15:4])`
into a `logic [11:0] cfg_len` (`0455999:rtl/vec_alu.sv:104`), so **bit 16 is
dropped and
the engine quantizes 2048 elements instead of 6144**. Everything downstream
of that DYNQ8 — `down_proj`, the residual, every later layer, the argmax — is
then different. At 0.8B, FFN = 3584 < 4096, which is why every frozen gate
has always passed and why this had never been seen.

Exact count in the shipped 2B W8 script: **144 of 15,246 ALU records**
(24 layers x 6 steps), every one of them `len = 6144`. Zero at 0.8B.

There is **no `0`-encodes-4096 escape** the way VNW's count has one:
`vec_alu` loads `len_q <= cfg_len` and compares `cfg_len == 12'd1`, so 0
would run zero elements.

**It cannot be worked around in the emitter.** DYNQ8 picks ONE shared
exponent from `max|x|` over the whole vector and reports it on EOUT, so
splitting it into two ≤4095 halves is not the same function. There is no
"forced exponent" ALU mode to rejoin them with.

### The fix — MADE IN THIS TASK (controller ruling, discovered scope)

One bit, and free in the encoding: for the ALU opcode `arg0[31:16]` is
entirely unused (`layer_chan.sv` reads only `arg0[3:0]` and `arg0[15:4]` on
op 11; `arg0[17:4]`/`arg0[31:18]` belong to DNST, a different opcode).

* `rtl/vec_alu.sv` `cfg_len` and `len_q` `[11:0]` -> `[12:0]`, and the four
  `12'd1` comparisons with them -> `13'd1`;
* `rtl/layer_chan.sv` `.cfg_len(arg0[16:4])`;
* `ref/gen_layer_script.py` `Mach.ALU_LEN_MAX` 4095 -> 8191, and the SAME
  bound in `ref/seq_format.py` `SeqEmitter._cmd` — the **second encode
  site**, which a scope check turned up: that emitter synthesizes ALU
  commands of its own (the attention EMUL32 probe pair, the fused matvec
  dequant, the AMAX32 chunks, DYNQ16) which never pass through `Mach.alu`.
  The guard sits at `_cmd`, the one choke point every layer command goes
  through, so it also re-covers the pass-through path;
* `ref/seq_model.py:_alu` the same bound — 13 bits, mirroring the hardware
  field EXACTLY rather than being wider than it, which is the property whose
  absence let the truncation hide.

8191 covers FFN = 6144 with room.

**Scope was checked before touching anything, and it did not ripple.**
`ag_i`, the address generator's element index, was ALREADY 13 bits; a sweep
of `len_q`/`cfg_len` found no other consumer in either module; the movers'
length is 24 bits and `matvec_chan`'s XWIN is already sized for K <= 6144.

**TDD at the unit level.** `tb/tb_vec_alu.sv` gains a directed pair at the
REAL production length: ADD over 6144 elements checked elementwise, and a
DYNQ8 whose maximum is planted at index 5000 so that the SCAN's reach is
what is under test — stated as a property (the 6144-element exponent must
DIFFER from the 2048-element one) rather than as golden arithmetic. On the
old RTL it fails exactly as the production bug does:

```
FAIL R-c ADD len=6144: 4096 of 6144 elements wrong (a 12-bit cfg_len runs 2048)
FAIL R-c DYNQ8 len=6144: exponent 0 equals the one the first 2048 elements
  imply: the scan did NOT reach the max planted at index 5000
```

and after the widening: `ADD 6144/6144 exact; DYNQ8 e=8 over 6144 vs e=0
over 2048`.

**Invisible at 0.8B — measured three independent ways, not argued.**

1. **The differential against the FROZEN legacy unit.**
   `tb/tb_vecalu_diff.sv` drives ONE randomized stimulus into both
   `tb/legacy/vec_alu_legacy.sv` (12-bit `cfg_len`, deliberately NOT
   widened) and the current RTL and requires them to agree element for
   element: **4,803 commands bit-exact** across six harness configurations
   (read-first, write-first, `coll_fatal`, `cfgscramble`). Only the
   new-RTL side of the harness widened, which is what makes it a proof
   rather than a tautology.
2. **The frozen TB set**: `tb_vec_alu`, `tb_vecnorm`, `tb_ru2_diff`,
   `tb_layer_chan`, `tb_token`, `tb_seq_layer` — 6/6 PASS; plus
   `REGEN_GATE_PASS`, `E4_LOCK_PASS`, and 2735/85/337 host selftests.
3. **The 0.8B chip replays are CYCLE-identical, not merely bit-identical**:
   `08_w4_n4` 1,069,855 cycles / 171,664 weight beats and `08_w8_n4`
   1,201,597 / 327,440 — the same numbers as before the widening.

**No emitted byte moved** (`t4_21_bytes_unmoved.log`): `Mach.alu` always
packed the count unmasked, so the streams already carried `arg0 = 0x18000`;
what changed is that the RTL now DECODES bit 16. The 1-layer 2B artifact
regenerates byte-identically (`.txt`, `.seq`, `.seq.json`, `.seqdata.bin`,
`.weights.json` and all 15 images), so §2's artifact shas STAND and the 2B
set did not need regenerating.

**The widening is FREE for the frozen streams, and that is measured, not
asserted** (`t4_alu_sparebit.sh` -> `t4_16_alu_sparebit_scan.log`), which is
the R-b `scan_spare_bits` argument applied to this field:

| script | ALU records | max len | `arg0 >= 2^16` |
|---|---|---|---|
| `w4/model_v2_s1.txt` (the frozen production script) | 14,814 | 3584 | **0** |
| `w3/lay_s1.txt` / `w3/tok2_s1.txt` | 306 / 474 | 3584 | **0** |
| `bis_08_w4_n4` / `bis_08_w8_n4` | 306 / 306 | 3584 | **0** |
| `bis_2b_w4_n4` / `lay2b_w8_s1` (1 layer, 2B) | 318 | **6144** | **4** |
| `w5/model_w8_2b_s1.txt` (the 2B W8 model) | 15,246 | **6144** | **144** |

Bit 16 is never set anywhere at 0.8B, so `.cfg_len(arg0[16:4])` decodes
every frozen stream identically. The re-runs it needed are done and green
(gate rows 18-22, 27, 32, 37 — `tb_vec_alu`, `tb_ru2_diff` against the
frozen legacy unit, `tb_layer_chan`, `tb_token`, `tb_seq_layer`,
`tb_vecnorm`, both chip elaborations, the regen gate and the `.e4` lock),
and it landed **ahead of Task 5's synthesis**, which is what keeps a
bitstream from carrying the truncation into R-d bring-up.

### What wall 6 unblocked

* **`seq_model --gate` on the full 2B W8 stream: PASS.** 1770/1770
  live-state checkpoints bit-exact, banked state (conv / S / KV / TCNT /
  EOUT / AMAX) bit-exact, tokens IDENTICAL `[279, 314, 279, 369, 11751,
  13]` — the same six the generator reported. **Brief Step 2a is green.**
* **Host-driven `tb_layer_chan` at the 2B geometry: PASS**, 88,158 checks
  bit-exact, where before the widening it failed at `R[0x3400+2058]`.
  `layer_chan` + `vec_alu` are now correct at 2B.
* **Task 5's synthesis is unblocked** for this issue: the widening is in
  the tree ahead of it, so a bitstream built from `main`+`qwen2b` will not
  carry the truncation into R-d.

---

## 5b. WALL 7 — the checker was wrong, not the RTL and not the golden

**Root cause: `tb/tb_seq_chip.sv` indexes a 32,768-word array with 14 bits.**

```
line 668:  v = {16'd0, u_layer.smem_a[prev_mem_a[i][13:0]]}
line 807:  v = {16'd0, u_layer.smem_a[exp_mem_a[i][13:0]]} & 32'hFFFF;
```

`layer_chan.smem_a` is `logic signed [15:0] smem_a [32768]`. R-b widened the
scratchpad from 16K to 32K words and gave the TB `MAXMEM = 32768`, but these
two index expressions kept their 16K width. Every checked address `a >=
16384` therefore reads word `a - 16384` instead. **Not one 0.8B stream can
see it** — the 0.8B map is 16,384 words, so `[13:0]` is exact there, which
is why every frozen gate has always passed.

### The symptom, fully accounted for

At 2B the smoke's staging window is a single span `[7168, 23552)`, so the
checked set is `[0, 7168) ∪ [23552, 32768)`:

| | |
|---|---|
| checked words | 16,384 |
| checked and `>= 16384` (i.e. can alias) | **9,216** |
| they alias into | `0x1c00 .. 0x3fff` |
| of those aliases, how many land INSIDE the staging window | **9,216 of 9,216** |
| the first such address | **`0x5c00`** |

Staging words are precisely the ones a `.seq` run is LICENSED to leave
different from the `.txt` run. So every aliasing comparison pits a golden
value against a word that is allowed to be anything — and the first one is
`0x5c00`, which is exactly where the TB reported its first mismatch. The
onset address is not a clue about the MLP; it is an arithmetic consequence
of where the staging window ends.

### Which side is wrong — decided without rebuilding anything

`evidence/qwen2b/rc/t4_wall2_probe.py` (committed) states a falsifiable
prediction and tests it against `ref/seq_model.py`, independently of the
RTL: *if only the index is wrong, the values the TB printed as "got" at
`0x5c00+k` are the true contents of `0x1c00+k`.*

```
TB 'got'      == seq_model mem[0x1c00+k] : 21/21
TB 'expected' == seq_model mem[0x5c00+k] : 21/21
```

**21/21 on both.** The RTL held the right value at BOTH addresses; the
checker read the wrong word. Neither `seq_model` nor the RTL is deviating.

### Confirmation, in a scratch tree (before the fix was ruled in)

`evidence/qwen2b/rc/t4_wall2_scratch_experiment.sh` copies the TB, changes
only `[13:0]` -> `[14:0]` at both sites, builds into a scratch `obj_dir`,
and re-runs the 4-seed 1-layer 2B W8 smoke. The repo's `tb_seq_chip.sv` is
untouched and the script prints `git status --porcelain` to prove it.

```
seed 1..4:  LAUNCH 0 PASS: pc 2306, tokens 0, tcnt 6, scratch 16384
            TB_SEQ_CHIP PASS  (1,992,631 cycles)
wall7 scratch experiment rc=0
```

All 16,384 checked words verified on every seed — including the 9,216 that
used to alias, so the coverage is real and not merely quieter. **There is no
wall 8 behind wall 7** at the one-layer scale.

### On "shrink to one record's effect"

That step does not apply here and the reason is itself the finding: the bug
is in the CHECKER, not in any record's effect. No stream can be shrunk to
expose it, because no record causes it — the trigger condition is purely
*"the checked scratch set contains an address >= 16384"*, which is true of
every 2B stream and no 0.8B one. The existing 4-seed 1-layer smoke is
already the minimal repro at ~1 minute per seed, and the 10-second
`t4_wall2_probe.py` is a smaller one still.

### The recommended fix, and its blast radius

**Fix: `[13:0]` -> `[14:0]` at `tb_seq_chip.sv` lines 668 and 807.** Two
characters. This is a TESTBENCH fix — the smallest of the three categories:

| category | affected | frozen-gate implication |
|---|---|---|
| **testbench (this one)** | `tb/tb_seq_chip.sv` only | **none.** No RTL, no golden, no emitter, no artifact. At 0.8B the two expressions are already exact (every address < 16384), so `tb_seq_chip_fast`, `chat_i1_gate` and the 0.8B replays are bit-identical by construction — re-run to confirm, nothing to re-bless. |
| RTL (wall 6 was this) | `vec_alu` + `layer_chan` | needs the spare-bit proof, the differential vs the frozen unit, the whole TB set, and it gates Task 5's synthesis |
| golden / emitter | `seq_model` / `seq_format` | needs regen gate + `.e4` lock + the artifact shas re-checked |

### RULED IN AND APPLIED (commit `617f667`)

The fix landed as recommended, and **structurally rather than as a patched
literal** — writing the width out by hand is exactly how this happened:

* `localparam int MEMAW = $clog2(MAXMEM);` — the index width is DERIVED
  from the array size, so the two cannot drift apart again;
* both reads use `[MEMAW-1:0]`;
* **the guard the bug deserved**: the parser already `$fatal`'d on the MEM
  line COUNT (`n_exp_mem >= MAXMEM`) but never on the ADDRESS. A golden the
  checker cannot index now aborts the run instead of silently comparing the
  wrong word — which would have caught this the first time a 2B `.chip` was
  ever loaded.

**Behaviour-neutral, proven rather than argued** (`t4_30_wall2_fix_gates.log`,
`t4_32_cycle_identity_after_tbfix.log`):

| check | result |
|---|---|
| 0.8B w3 pair, the frozen NMV=1/WIMGPC=0 elaboration | `lay_s1` **PASS** (1,355,737 cyc), `tok2_s1` **PASS** (2,272,141 cyc, 3 tokens) |
| `08_w4_n4` after the fix | **1,069,855 cycles / 171,664 weight beats** — IDENTICAL to the pre-fix run |
| `08_w8_n4` after the fix | **1,201,597 / 327,440** — IDENTICAL |
| 2B W8 4-seed smoke on the REPO tb | **4/4 PASS**, 16,384 words each |

Cycle-identity is the strong form: the TB change cannot have perturbed the
DUT, and the numbers say so against values recorded two waves earlier.

---

## 5c. WALL 8 — the chip TB never programmed the EMB row stride (FIXED)

With walls 6 and 7 cleared, the **full 2B W8 chip replay ran to completion**
— 65 min 42 s of wall time, 354.14 ms simulated (~88.5 M cycles at 250 MHz),
all 68,503 records, no watchdog, no hang. It then failed its checks:

```
tb_seq_chip: launch 0 [-] rec_off 0, 68503 records, 6 tokens, 16384 scratch
             words, NMV=4 WIMGPC=1
XRF[1] = 3fff8, expected 3fff9      XRF[3] = 000dc, expected 0000d
TOK[0] = 0000d, expected 00117      TOK[3] = 000dc, expected 00171
TOK[1] = 0000d, expected 0013a      TOK[4] = 0008e, expected 02de7
TOK[2] = 0002c, expected 00117      TOK[5] = 000dc, expected 0000d
AMAXI  = 000dc, expected 0000d      AMAXV  = 0002cf6d, expected 00056aa3
MEM[0000] = 0228, expected 02d8     ... (mismatch from scratch word 0)
```

**Every generated token is wrong, from the first one.** That is the shape of
a fault at the very front of the datapath, not in a layer: the argmax feeds
the next step's embedding, so one bad first token diverges everything after
it, and `MEM[0000]` (the residual `X0`) being wrong at the end follows.

### Why the fail-fast could not have caught it

| opcode | 4-seed 1-layer smoke | full 2B stream |
|---|---|---|
| `EMB` | **0** | 6 |
| `AMAXL` | **0** | 6 |
| `JMP` | **0** | 3 |

The smoke has **zero coverage** of exactly the three opcodes the full stream
adds — it generates no tokens at all. All three ARE exercised at 0.8B by
`w3/tok2_s1` (EMB 1, AMAXL 1, JMP 1), which passes on this same TB, so the
machinery is sound and only its 2B configuration is not.

### Root cause, PROVEN (not inferred)

`rtl/seq_unit.sv` holds the EMB row stride in a runtime CSR:

```
0x60 EMBLOG2  RW log2 of the EMB row size in bytes, reset 11 (2048 B)
localparam logic [4:0] EMBLOG2_RST = 5'd11;
```

* this 2B artifact declares `emb_row_bytes = 4096` -> **EMBLOG2 must be 12**;
* `sw/seq_run.py:1762` programs it before any EMB record runs, on silicon;
* **`EMBLOG2` does not appear anywhere in `tb/tb_seq_chip.sv`.** The TB's
  host BFM writes BASE/LEN/ENTRY and pulses START, and never touches it.

So in simulation the DUT fetched every embedding from `EMB_BASE + tok*2048`
instead of `tok*4096`. At 0.8B the reset value is already right, which is
why no 0.8B replay ever needed it.

Proven with the wall-7 method — a falsifiable prediction tested against the
golden executor, no rebuild (`t4_wall8_probe.py`):

```
  correct stride (4096 B rows)  -> ['0x117','0x13a','0x117','0x171','0x2de7','0xd']
  EMBLOG2 stuck at 11 (2048 B)  -> ['0xd','0xd','0x2c','0xdc','0x8e','0xdc']
  .chip golden tokens           : ['0x117','0x13a','0x117','0x171','0x2de7','0xd']
  RTL produced                  : ['0xd','0xd','0x2c','0xdc','0x8e','0xdc']
```

Feeding `seq_model` a 2048-B-stride table reproduces the RTL's six wrong
tokens **exactly**, and the correct stride reproduces the golden exactly.
Six-for-six is not coincidence. (Sanity check in the same log: token 760
would read true row 380 — `760*2048/4096` — which is what a halved stride
does to an even token id.)

### Recommended fix and blast radius

**Testbench-only, like wall 7. Neither the RTL, the golden, the emitter nor
the artifacts are at fault**, and silicon is not exposed:

| | |
|---|---|
| `rtl/seq_unit.sv` | correct — it implements the CSR and defaults to the 0.8B value |
| `sw/seq_run.py` | correct — it programs EMBLOG2 (R-b), so **R-d / Task 6 is NOT exposed** |
| `ref/seq_model.py` | correct — it reads the stride from the artifact manifest |
| **`tb/tb_seq_chip.sv`** | **the gap** — its host BFM never programs the CSR |

Fix: have the TB's host BFM write `EMBLOG2 = log2(emb_row_bytes)` before
START, taking the value from the artifact rather than a literal — the
`.chip` file's `BASES` line already carries generator-derived values the TB
asserts against, so the row stride belongs there too. And, in the spirit of
wall 7's guard, `seq_unit` could `$error` on an EMB record issued while
EMBLOG2 is still at reset *if* the stream's own metadata disagrees —
cheaper still, the TB can assert it.

### RULED IN AND APPLIED

The fix landed as recommended, and so did the follow-on it implied.

**1. The TB's host BFM programs EMBLOG2, from the artifact.** The value is
generator-derived and travels in the `.chip` file's own `EMBLOG2` line —
`gen_seq_chip_vectors.py` writes `log2(emb_row_bytes)` beside the `BASES`
line it already emits, so the TB cannot drift from the artifact any more
than it can drift on the DDR bases. The TB writes the CSR at exactly the
point `sw/seq_run.py` does (after XRF/TCNT zeroing, before START) **and
reads it back**, so a geometry `seq_unit` cannot serve fails loudly instead
of silently fetching the wrong row. An absent `EMBLOG2` line means 11 — so
every `.chip` written before this, all of them 0.8B where 11 is already
correct, is untouched.

**2. The fail-fast got token coverage** (`make -C tb w8_2b_tok_smoke_scripts`
+ `tb_seq_chip_w8_tok_smoke`). `gen_token_script.py` gains `--wq=w8` and
emits a HEAD, so the new 2B smoke carries **EMB 2 / AMAXL 2 / JMP 2** and
generates real tokens in 1,244 records. This is the gap that let wall 8
cost 66 minutes: the 1-layer smoke could not see the embed/argmax/loop path
at all.

**RED -> GREEN, and the RED is the point** (`t4_35_wall8_red_green.log`):

| | |
|---|---|
| new token smoke vs a host BFM with the EMBLOG2 write REMOVED (scratch copy) | **4 of 4 seeds FAIL** |
| the same vectors on the repo TB | **4 of 4 PASS**, 2 tokens + 16,384 words each |

The improved fail-fast catches wall 8 in **minutes**, on all four seeds —
had it existed, walls 7 and 8 would both have surfaced before the 66-minute
run rather than after it.

**0.8B untouched, both paths and cycle-identical:**

| check | result |
|---|---|
| w3 pair on the EXISTING `.chip` files (no `EMBLOG2` line -> default 11) | **both PASS** — `lay_s1` 1,355,737 cyc, `tok2_s1` 2,272,141 cyc / 3 tokens |
| w3 pair REGENERATED, `EMBLOG2 11` now emitted | **both PASS**, the SAME cycle counts — `EMBLOG2 11` written and read back |

---

### The pattern walls 7 and 8 share — and why it de-risks R-d

Both were **TB host-model gaps at a new-geometry corner**, and **neither
touched the RTL, the golden, or the artifacts**:

| | wall 7 | wall 8 |
|---|---|---|
| what was wrong | the checker read `smem_a` with a 14-bit index | the host BFM never programmed `EMBLOG2` |
| where | `tb_seq_chip.sv` | `tb_seq_chip.sv` |
| RTL | correct | correct (`seq_unit` implements the CSR) |
| golden `seq_model` | correct | correct (reads the stride from the artifact) |
| artifacts / emitter | correct, unchanged | correct, unchanged |
| the real host `sw/seq_run.py` | n/a (checker-only) | **already does it** (`sw/seq_run.py:1762`) |
| why 0.8B never saw it | its map IS 16K, so the slice was exact | reset 11 IS its stride |

That is a genuinely reassuring shape for R-d. The two failures that stopped
the first full-2B simulation were **simulation-harness** defects, not design
defects: the sequencer, the layer engine, the matvec channels, the W8 wire
format, the per-channel repack and the emitted artifacts were all correct at
2B the whole time. Wall 6 was real RTL — and it is fixed, gated and ahead of
Task 5's synthesis. The host software that R-d will actually run already
does the right thing on both counts, so nothing here shifts bring-up risk
onto the board; it shifts it onto keeping the TB's host model honest, which
is what the `EMBLOG2` readback and wall 7's address guard now enforce.

Everything is preserved: the artifacts, their §2 shas, the 68,503-record
`.chip` golden and the four per-channel region files.

---

## 5d. Review folds

| # | fold | done |
|---|---|---|
| 1 | §6 quoted the pre-widening 12-bit / 4095 bounds | corrected to the shipped 13-bit / 8191 throughout |
| 2 | **wall 8** still called open in three places | all three now point at the closing rows |
| 3 | the T5/T6 hand-off report was stale | header counts, gate table, §3 remnant and follow-on numbering brought current |
| 4 | the weight-beat line read as a fabric total but was channel 0 | **`tb_seq_chip.sv` now prints the SUM and the per-channel split** — first run of the new line: `4,116,544 total across 4 chan [1029136/1029136/1029136/1029136]` |
| 5 | §4 repeated its fidelity preamble | deduped |
| 6 | `bit_length()-1` is log2 only for a power of two | `gen_seq_chip_vectors` asserts it — an odd row size would round DOWN and re-create wall 8 in a new disguise |
| 7 | the differential never drove the real production length | `gen_len()` offers **3584**, the longest ALU command any frozen 0.8B stream issues; 6 configs re-run, `len_max=3584` in every census |
| 8 | §2's recipe omitted the `W8_FLAGS` override | the command of record now reproduces exactly, and says the make default carries `--allow-clip` |

**Fold 7's one wrinkle, recorded rather than smoothed over.** 3584 does not
fit every op: `run_case` needs `k*len` words and the FROZEN legacy copy has
only a 16K map, so op 9 (SHIFT32W, `k = 5`) cannot host it. The harness now
clamps per op class to the longest length that op's own geometry allows,
rather than dropping the case or overflowing — every op still gets its
longest legal length, and the ops that can take 3584 do.

**Fold 10 (ruled): the GATE / DNST / KVAP / ATTN ARG fields are guarded.**
Three waves of this bug class was enough. `DNST head` (`arg0[3:0]`),
`KVAP kvhead` (`arg0[0]`) and `expbias` (`arg0[8:4]`), and `ATTN kvhead`
(`arg0[0]`) now assert against their RTL slices, in the same
refuse-don't-corrupt style as `alu()`, `vnw_()` and `_conv_fields()`. GATE
needed nothing — all five of its fields are scratch addresses already
range-checked by `enc_saddr`. `DNZ head` gets the same assert as DNST,
because `layer_chan.sv` dispatches both through the SAME
`dn_head <= arg0[3:0]`. Pure asserts; no encoding changed.

DNST's `head` is the one that mattered: `a_dec` sits at `arg0[17:4]`
directly above it, so an out-of-range head would have corrupted a POINTER,
not merely a head index — the same shape as wall 6.

**The honest remainder.** This is the ruled set, not every field in the
ISA. Still unasserted: `Mach.vn`'s `mode` / `inf` / `outf` sub-fields
(4 bits each in `arg0`), and its `nlog2`, which is already doubly covered —
`vn()` asserts the count is a power of two, and `vecnorm_unit` has its own
envelope guard that `tb_vecnorm`'s self-test proves fires. Those are the
known gap; naming them is cheaper than implying the sweep was total.

**Proven non-firing — and the two proofs cover different things.**

* **The scan** (`scan_spare_bits.py`) shows the OR-masks over all 38 frozen
  files: GATE ARG0 `0x00000c40`, KVAP `0x00000081`, ATTN `0x00000001` —
  each field plainly inside its width, across every stream. **It does NOT
  carry DNST's `head`**: DNST ARG0's mask is `0x313cc5ff`, whose low nibble
  is `0xF`, i.e. the head field is exactly FULL (16 DeltaNet heads in 4
  bits) and `a_dec`'s bits sit directly above it, so an OR-mask cannot
  separate the two. The mask argument is evidence for KVAP/ATTN/GATE only.
* **The regen gate EXECUTES the asserts**, which is what settles DNST.
  It regenerates `model_v2_s1` — 1,728 DNST, 72 KVAP, 288 ATTN and 288 DNZ
  records — twice, once for lock A's `.e` and once for lock B's `.e4`:
  **3,456 / 144 / 576 / 576 assert executions**, every one passing, with the
  streams still byte-identical. `REGEN_GATE_PASS` against
  `a69864d2…f444aaf1`, `E4_LOCK_PASS` against `e102e2df…d6e8ac933`, and
  `seq_selftest` 2,735 / `serve_test` 85 / `chat_seq` 337, all 0 failed.

(The scan's per-opcode totals — 33,344 DNST, 1,432 KVAP, 5,728 ATTN — are
records across all 38 scanned files, most of which the gate does not
regenerate. They are the mask evidence, not assert executions; conflating
the two would overstate the execution count roughly 19x on DNST.)

---

## 6. The blind spots that hid WALL 6 — closed, and the class swept

A silent field truncation survived because **every model agreed with the
generator instead of with the hardware**:

1. **`ref/gen_layer_script.py` `Mach.alu` emitted an unencodable command.**
   It now `assert`s `1 <= n <= 8191` — `ALU_LEN_MAX`, matching the WIDENED
   13-bit `cfg_len` this task shipped (§5) — and names the RTL field, the
   reason DYNQ8 cannot be chunked, and the spare bits a further widening
   would use. This is the house pattern `vnw_` already carried for VNW's
   11-bit count; ALU simply never got one. `ref/seq_format.py`'s
   `SeqEmitter._cmd` carries the same bound, because that emitter
   synthesizes ALU commands of its own which never pass through `Mach.alu`.
2. **`ref/seq_model.py` `_alu` decoded the count with `& 0x3FFF` — 14 bits,
   WIDER than the hardware field.** So the golden could express lengths the
   sequencer cannot ask for, and the `.txt`-vs-`.seq` gate compared two
   sides that were both wrong in the same direction. It now REFUSES a stream
   above the field, and its bound MIRRORS the hardware exactly — 13 bits
   since the widening, never wider:

```
seq_format.SeqValidationError: ALU record count 8704 exceeds the 13-bit
cfg_len field (ARG0=0x22000); rtl/vec_alu.sv would run 512 elements. This
stream is NOT executable by the RTL as built — see
ref/gen_layer_script.py Mach.alu.
```

(Before the widening the same refusal fired at 12 bits, which is how the
2B stream's 6144-element DYNQ8 was caught — §5.)

3. **And the same class, swept as far as it was ruled** (§5's "audit the other fields" follow-on,
   landed): `_conv_fields` guards CONV/CONVW's two 13-bit channel fields,
   and DNST's `head` (`arg0[3:0]`), KVAP's `kvhead` (`arg0[0]`) and
   `expbias` (`arg0[8:4]`) and ATTN's `kvhead` now assert against their RTL
   slices too. None can fire on any frozen stream — `scan_spare_bits.py`'s
   masks (GATE ARG0 `0x00000c40`, DNST `0x313cc5ff`, KVAP `0x00000081`,
   ATTN `0x00000001`) show every field well inside its width. GATE needed
   nothing: all five of its fields are scratch addresses, already checked by
   `enc_saddr`. DNST's `head` is the one that mattered most — `a_dec` sits
3. **And the same class, swept as far as it was ruled**

Net effect: what cost a Verilator build plus a full-chip run to discover now
fails in **two seconds**, at generation time, with the field named — and an
artifact built before the check is caught on the reading side too.

---

## 7. Frozen guards (mandatory after every emitter edit)

| lock | what | gold | before edits | after edits |
|---|---|---|---|---|
| A | `ref/scripts/regen_gate.sh` — 0.8B `.e` + `.txt` | `a69864d2…f444aaf1` | REGEN_GATE_PASS | **REGEN_GATE_PASS** |
| B | `SEQ_NCH=4` `.e4` stream **and** its `.seq.json` | `e102e2df…d6e8ac933` | E4_LOCK_PASS | **E4_LOCK_PASS** |
| — | `make seq_selftest` | — | 2,735 / 0 | **2,735 / 0** |
| — | `make serve_test` | — | 85 / 0 | **85 / 0** |
| — | `chat_seq.py --selftest` | — | 337 / 0 | **337 / 0** |
| — | `seq_model.py --selftest` (W8 + REPACK) | — | PASS | **PASS** |

"Before edits" is `t4_03_locks.log` for locks A/B (run on the pristine
`999df81` tree at the start of this task) and T3's `t3_sw_selftests.log` for
the four selftests; "after edits" is `t4_13_locks_after.log` /
`t4_14_sw_selftests.log` / `t4_15_green_producers_final.log`.

**Re-run a THIRD time after the RTL widening**, since it touched both
emitters and the golden: `t4_22_locks_after_widen.log` (REGEN_GATE_PASS,
E4_LOCK_PASS) and `t4_25_sw_selftests_after_widen.log` (2,735 / 85 / 337,
0 failed). **And a FOURTH after the review folds** added the GATE/DNST/
KVAP/ATTN/DNZ ARG-field asserts — which is the run that EXECUTES them,
3,456 / 144 / 576 / 576 times, on a byte-identical stream:
`t4_38_fold_locks.log` and `t4_39_dnz_locks.log`. Plus the six frozen TBs (`t4_20_widen_frozen_gates.log`) and the
cycle-identical 0.8B chip replays (`t4_27_bisect_after_widen.log`), which
the earlier waves did not have to prove because no RTL had moved.

One deliberate, non-hashed change: the generator's header line now reports
`wq=` and, on W8, `group_rule=max|W_g|/127` in place of `mse_scale=True`.
Logs are not hashed by any gate; the artifacts are, and they did not move.

---

## 8. What was built (Task 4's producers)

TDD, RED first (`t4_01_red_producers.log`), then GREEN
(`t4_02_green_producers.log`), gate script
`evidence/qwen2b/rc/t4_producers.py` (committed, re-runnable).

* **`ref/gen_model_script.py --wq=w4|w8`** — routes EVERY matvec matrix,
  the 24 layers and the tied LM head alike, through
  `layer_fixed.quant_linear_w8` -> `w4a8_ref.quantize_weights8`. The
  embedding stays int16 Q7.8 and the conv window stays Q2.13, per V5.
  Refuses `--w4-group=64` (the W8 wire format is g128-cadence only) and
  refuses `FABLE5_CALIB_STATS` (the calibrated quantizers are W4-only, and
  the head path would have ignored the plumb silently where the body path
  refuses it).
* **`Mach.dump_weights` W8** — dispatches on `layer_fixed.qw_codes`, packs
  with `pack_ddr_rows8`, and tags the manifest `"w8": true` **only when
  true**, exactly as `"g"` is emitted only when != 128, so every W4
  manifest ever written stays byte-identical. `Mach.matvec` dispatches the
  same way (`matvec_y32_w8`), row-chunk-identically.
* **`tb/scripts/gen_seq_chip_vectors.build_wimg` per channel** — a repacked
  stream gets `<base>.wimg<c>.bin`, one per channel, each holding only that
  channel's rows at `chan_base + row_off*stride`, with the piece list taken
  from the stream's own `meta["weight_layout"]` (refused, not guessed, when
  absent). Writes are checked DISJOINT per channel, and a stale flat
  `.wimg.bin` is removed so no TB can open the wrong file. The
  non-repacked path is unchanged and still returns one flat region.
* **`tb/tb_seq_chip.sv` `WIMGPC`** — each `matvec_chan`'s `seq_mem_file`
  elaborates against its own region file. Default `0` = the shared
  `.wimg.bin` every frozen gate uses; lint clean at both settings.
* **`tb/Makefile`** — `w8_2b_smoke_scripts`, `w8_2b_model_script`,
  `seq_chip_vectors_w8`, `tb_seq_chip_w8_build/_smoke`, `lint_seq_chip_w8`,
  in their OWN `obj_dir_tb_seq_chip_w8` (`-GNMV=4 -GWIMGPC=1`), never
  touching the NMV=1 elaboration the frozen gates use.
* **`ref/fidelity_check.py`** — the `mse` label suppressed under `--w8` (§4).

The 0.8B W8 cell of the bisect is worth naming as a result in its own
right, because it is the first time the whole V5 stack ran together on RTL:
**`08_w8_n4` — W8 images + SHAPE bit 29 + per-channel repack + 4 real
`matvec_chan` + per-channel region files — TB_SEQ_CHIP PASS**, 1,201,597
cycles, 327,440 weight beats (1.91x the W4 twin's 171,664, i.e. the engine
really did stream 8-bit rows), 0 misses, scratch and banked state exact.

---

## 9. Follow-ons

1. ~~Widen ALU `cfg_len` to 13 bits~~ — **DONE** (§5), `scan_spare_bits.py`
   carries the home and re-proves it every run.
2. ~~Wall 7: the checker's scratch index~~ — **DONE** (§5b), width derived
   from `MAXMEM` plus the `$fatal` address guard.
3. ~~Wall 8: program `EMBLOG2` from the artifact~~ — **DONE** (§5c), with
   a readback so an unservable geometry fails loudly.
4. ~~Give the fail-fast token coverage~~ — **DONE**: `w8_2b_tok_smoke_scripts`
   + `tb_seq_chip_w8_tok_smoke`, 4 seeds carrying EMB/AMAXL/JMP, which fail
   4-of-4 against the pre-fix BFM. Run it before the 66-minute replay.
5. **Audit the OTHER command fields at 2B the way this one was missed.**
   `_conv_fields` now guards CONV/CONVW; VNW was already guarded. Nothing
   else was checked systematically — a one-pass sweep of every `layer_chan`
   ARG field against the 2B geometry would be cheap now and is the class of
   bug that costs a whole simulation to find.
6. **The 2B `--allow-clip` blessing run was not made** — deliberately: the
   artifacts are written before the audit verdict and are byte-identical
   either way (proven, `t4_21_bytes_unmoved.log`). Optional tidy-up, not a
   blocker; §2's hashes stand as they are.
7. **S_F = 13 saturates 21 times at 2B** (8 at 0.8B), on `(dn_slot, head)`
   `(3,5)` and `(4,4)`, and the gate-port clamp now distorts **5** heads
   rather than 2 — both W4 and W8 alike. Frozen-RTL, accepted under
   `--allow-clip`, but at 2B it is no longer the 2-head curiosity
   `audit_ranges_report.md` described, and §6.5 of the 2B report already
   flagged `L0h13` (+0.089 absolute) and `L0h3` (+105 % relative). Worth a
   ruling before R-d rather than after.
8. **`tb_seq_chip` at NMV=4 was never exercised before this task.** It is
   now (two cells, both PASS). Consider adding `08_w8_n4` to a routine
   regression — it is ~1 minute of sim and it covers the whole V5 stack.

---

## DATED NOTE (2026-08-29) — this gate's byte-lock is scheduled to be SPENT

`evidence/qwen2b/rc/t4_bytes_unmoved.sh` — the gate that proves the 2B artifact
set regenerates byte-for-byte, and the tool Track L used on 2026-08-26 to show
its `ref/` geometry guards were inert — **will stop being runnable against the
tree during the Qwen3.5-9B migration**, by design and not by accident.

**ONE** decision in `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md`
destroys byte-identity at *every* geometry: the layer-ISA re-encoding (§4.3 — the
R-b 15-bit scatter is replaced by plain 16+16 pairs, because the frozen-stream
contract it existed to serve is retired).

> **CORRECTION-OF-CORRECTION (2026-08-29, same day).** The first version of this
> note said **two** decisions destroy byte-identity, naming a move of the
> residual binary point `RS_F` (§4.4) as the second. **That is wrong, and it was
> wrong in the spec too before its fix round.** §4.4 makes `RS_F`
> *model-selected*: 0.8B and 2B keep `RS_F = 8` and their emitted bytes do not
> move at all. Only the 9B value may differ, and 9B has no byte-lock to break.
> The `RS_F` relocation is **inert here** and lands in the migration's G2, on the
> safe side of the retirement. Recorded rather than silently edited, because a
> stale claim in an evidence document outlives the spec that spawned it — which
> is exactly what this note exists to prevent.

The migration spec's §8 sequences it explicitly:

* **G2a** — the geometry generalizations are supposed to be inert, so this gate
  **must still pass** there. That is the last time it means anything.
* **G2b** — immediately after, the artifact sha256 set is recorded once more into
  `evidence/qwen9b/g2/FINAL_BYTELOCK.md`. That record, not a regeneration, is
  thereafter the provenance of what `build_034` / `build_035` were built from.
* **G3** — the re-encoding lands and this gate is retired. **Rebuilding 0.8B/2B
  artifacts from the post-migration tree is declared unsupported**; no v1.7
  emitter path is kept.

Nothing about the numbers in this document changes. `build_035` and its 2B W8
pack are unaffected and stay serving. If you find `t4_bytes_unmoved.sh` failing
after the 9B migration's G3, **this note is the explanation — do not debug it.**

---

## DATED NOTE (2026-08-31) — the byte-lock is now PINNED; retirement is the next thing that happens to it

The note above was written on 2026-08-29 as a forecast. This one closes it:
the migration's **G2a passed and G2b has landed**, so the sequencing that note
describes is no longer a plan, it is a record. Nothing above is edited —
including its correction-of-correction, which stands.

**What happened, 2026-08-31, on snoke at tree `c9d2a2f`.**

* `evidence/qwen2b/rc/t4_bytes_unmoved.sh` ran a final time at **four seeds**
  — it takes its gold from `tb/scripts/w5/lay2b_w8_s$SEED`
  (`evidence/qwen2b/rc/t4_bytes_unmoved.sh:21`), so each seed is a different
  2B one-layer artifact set — and returned **`BYTES_UNMOVED PASS` on all four**.
  Every earlier run of this gate, this campaign's included, used `SEED=1` only.
* `ref/scripts/regen_gate.sh` returned **`REGEN_GATE_PASS`**, `got` =
  `a69864d2…f444aaf1`, 60,495 records — the constant at
  `ref/scripts/regen_gate.sh:5`.
* `evidence/qwen2b/rc/t3_locks.sh` returned **`E4_LOCK_PASS`**,
  `e102e2df…d6e8ac933`, with the 4-chan weight-plan JSON and the model `.txt`
  both compared identical.

**Those three runs are the last readings that will ever mean anything**, and
they are recorded under `evidence/qwen9b/g2/` as
`evidence/qwen9b/g2/t4_bytes_unmoved_g2b_s1.log` and its three siblings,
`evidence/qwen9b/g2/regen_gate_g2b.log` and
`evidence/qwen9b/g2/t3_locks_g2b.log`.

**Section 2's artifact shas STAND, and are now checkable rather than merely
recorded.** The six file rows at `evidence/qwen2b/rc/RC_GATE.md:188-194` were
re-measured at G2b and **all six match to the digit**; the image-list row on
the last of those lines matches too, but only under the collation it was taken
with — see the caveat below. They have been copied into a **pin with expected values** —
`evidence/qwen9b/g2/final_bytelock_pin.sh`, 54 rows over the 0.8B chain, the 2B
chain and the byte-lock's own gold, which **compares and exits non-zero on any
mismatch** — with the full record and the reasoning in
`evidence/qwen9b/g2/FINAL_BYTELOCK.md`. That is the difference between this
document's section 2 and the pin: section 2 is a document nothing executes.

> **One caveat on section 2's last row, found by G2b and recorded rather than
> edited.** The 187-image digest at `evidence/qwen2b/rc/RC_GATE.md:194` is
> produced by `sha256sum ${P}_w*.bin | sha256sum`
> (`b9e0851:evidence/qwen2b/rd/rd_2b_artifact_shas.sh:19`), which hashes the glob in
> **shell order**, and shell glob order depends on `LC_COLLATE`. Same 187
> files, same bytes: `c9e6d0a6…` under the login default `LANG=en_US.UTF-8`,
> `e6a1c0b5…` under `LC_ALL=C` (both measured on snoke, 2026-08-31). The
> recorded value is the `en_US.UTF-8` one and neither the line nor the script
> says so, **so the same command from a C-locale shell reads as a mismatch that
> is not one.** The number here is correct under the collation it was taken
> with and is left alone; the pin uses a locale-independent form and states why
> at its own definition.
>
> **CLOSED 2026-09-10 (#19, triage (b)13).** `evidence/qwen2b/rd/rd_2b_artifact_shas.sh`
> now pins the order — `printf '%s\\n' ${P}_w*.bin | LC_ALL=C sort | LC_ALL=C
> xargs sha256sum | sha256sum` — so the digest is a property of the FILES and
> not of the shell that ran it. The pinned value is therefore the `LC_ALL=C`
> one, `e6a1c0b5…`, added as the line below section 2's `c9e6d0a6…` rather
> than replacing it, so the original record still reconciles. Both digests
> were re-measured under both locales before the change:
> `evidence/qwen9b/o3/84_artifact_shas_locale_RED.log` (SPLIT) and
> `evidence/qwen9b/o3/85_artifact_shas_locale_GREEN.log` (one digest).

**After G3, this gate is retired and rebuilding is UNSUPPORTED.** The ARG
re-encoding changes the emitted words at *every* geometry, so
`evidence/qwen2b/rc/t4_bytes_unmoved.sh` stops being runnable against the tree.
**This project does not keep a v1.7 emitter path** — the migration spec says so
at `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md:2077-2085`.
Rebuilding the 0.8B or 2B artifacts from the post-migration tree is therefore
**declared unsupported**: those artifacts already exist, they are pinned in
`evidence/qwen9b/g2/FINAL_BYTELOCK.md`, and the bitstreams that consume them —
`build_034_po2_AltSpreadLogic_high` and `build_035_fp2a_exc_po` — are frozen.

**If you find `t4_bytes_unmoved.sh` failing after G3, read this note; do not
debug the script.** If instead
`evidence/qwen9b/g2/final_bytelock_pin.sh` fails, that is a different and worse
thing: the pin hashes files where they lie and does not regenerate anything, so
a pin failure means **an artifact was touched, moved or lost**, and the fix is
to restore the bytes, not to re-emit them.
