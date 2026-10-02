# G3.3 — `matvec` at `MAX_NG = 96` and XWIN 12 KiB, W8 and g64 stripped

**Task 9 of the Qwen3.5-9B migration (spec §4.5 W5, §5.1 S5, §5.2 S6).
Base tree `a08a90b`.  Simulation only — no synthesis, no board.**  Every
number below is labelled **M**(easured), **D**(erived), **T**(ranscribed
from another gate), **E**(stimate) or **S**(tated as an intent), and every
numeric step went through `evidence/qwen9b/run.sh`.

**The claim.**  `rtl/matvec_engine.sv` now runs `cfg_ng` up to **96**
(K = 12288, the 9B `down_proj` row) bit-exactly against `ref/w4a8_ref.py`,
on four seeds, with the whole W8 lane array and the g64 mode **deleted** and
today's W4 vector sets proven **byte-identical** to `a08a90b` first.  The
XWIN aperture is **3072 words / 12 KiB** in both RTL files that declare it,
and the SHAPE CSR word is repacked **contiguously** with `ng` at 7 bits —
versioned in `sw/hwmap.shape_word`, so the host can still drive
`build_034`/`build_035`.

**Interpreter, per host — probed with `test -x`, never by name** (the plan's
standing hazard: `ref/.venv/bin/python` is a DANGLING SYMLINK on snoke):

| host | `/home/cah/.venv/bin/python` | `ref/.venv/bin/python` | `sw/.venv/bin/python` | used for |
|---|---|---|---|---|
| snoke | **exists** (numpy 2.4.6) | ABSENT | exists (`/usr/bin/python3`) | every Verilator target (`VECPY=`), the board-free gate |
| darthplagueis | ABSENT | **exists** (3.11) | exists | `isa_bits.py`, the citation set, `hwmap --selftest` |

`FABLE5_RS_F` was **never exported** in any run (plan A2.5); every log's
provenance header records `FABLE5_RS_F=unset`.

---

## 0. The log inventory

| # | log | what |
|---|---|---|
| 130 | `evidence/qwen9b/g3/130_w4_baseline_a08a90b.log` | the four targets + both lints on a **`git archive a08a90b`** export (`.g33_baseline/`) — the BEFORE state, snoke |
| 131 | `evidence/qwen9b/g3/131_w4_after_strip.log` | first post-strip suite run — **`tb_mvshim_b` failed to elaborate**, `tb/mvshim_b_stubs.sv` still declared `cfg_g64`/`cfg_w8` (fixed) |
| 132 | `evidence/qwen9b/g3/132_w4_after_strip.log` | second — **`tb_mvshim_b` T1 failed**, its SHAPE round-trip mask still admitted bits 28/29 (fixed) |
| 133 | `evidence/qwen9b/g3/133_w4_after_strip.log` | **the W4-unchanged run**: four targets + both lints GREEN after the strip, `MAX_NG` still 48 |
| 134 | `evidence/qwen9b/g3/134_w4_vector_bitidentical.log` | **the byte-identity proof**: 84 vector files, `a08a90b` vs now |
| 135 | `evidence/qwen9b/g3/135_tb_suite_9b.log` | first post-widening suite — **`tb_matvec_chan` failed at K = 12288**, `xq_d` was still 43 bits (fixed; §4a) |
| 136 | `evidence/qwen9b/g3/136_tb_suite_9b.log` | second — **`tb_mvshim_b` T1** again, the SHAPE mask had to admit bit 28 back as `ng[6]` (fixed) |
| 137 | `evidence/qwen9b/g3/137_tb_suite_9b.log` | **the suite** on the final working tree |
| 138 | `evidence/qwen9b/g3/138_boardfree.log` | the board-free gate on the final working tree |
| 140 | `evidence/qwen9b/g3/140_isa_bits_g33.log` | `isa_bits.py` — the G3.1 ARG gate, still PASS on this tree |
| 141 | `evidence/qwen9b/g3/141_isa_bits_negctl_g33.log` | `--negative-control` — 19 of 19 REFUSED |
| 142 | `evidence/qwen9b/g3/142_isa_bits_shape.log` | **`--shape`** — the six-way SHAPE round trip, both isa layouts |
| 143 | `evidence/qwen9b/g3/143_isa_bits_shape_control.log` | **`--shape-control`** — 5 of 5 field-width perturbations REFUSED |
| 144 | `evidence/qwen9b/g3/144_hwmap_selftest.log` | `sw/hwmap.py --selftest`, the `isa=1` RD_GATE pins |
| 145 | `evidence/qwen9b/g3/145_seq_model_selftest.log` | `ref/seq_model.py --selftest`, the W8 goldens at `isa=1` |
| 150-162 | see §11.2 | the citation-drift set: `--check`, `--fix`, `--verify`, `--range-control`, both negative controls, `--doc-cites` × 4 rounds |
| 163-169 | see §11.2 | `spec_cites.py`, its `--selftest`, and the pinned-count regression |
| 170 | `evidence/qwen9b/g3/170_spec_cites_final_working.log` | the last `spec_cites.py` pass on the working tree |
| 200-201 | see §14.7 | **FIX ROUND 1** on the working tree: the suite + `tb_streamer_engine`, and the board-free gate |
| 210-219 | see §14.8 | **FIX ROUND 1** re-run on the COMMITTED tree |
| 180-197 | see §12 | **the gate evidence, re-run on the COMMITTED tree `26e934b`** |

Logs 131/132/135/136 are kept deliberately: three of the four defects this
task found were found by a test, and deleting the failing runs would delete
the evidence that the tests are load-bearing.

---

## 1. What was deleted, in order — Step 1 before Step 2

The brief's order is the subtraction first.  It was followed, and log 133 is
the proof that the subtraction alone changed nothing about W4.

**Out of `rtl/matvec_engine.sv`:** the `cfg_w8` and `cfg_g64` ports; the
8-bit operand mux in stage 1; the whole W8-envelope adder tree (four stage
widths, §4); the half-beat toggle (`wbeats`, `w8_phase`, `ph_q` and its five
pipeline copies `ph1_q`…`ph5_q`); the `wr_lo`/`wr_hi` split write-enables;
the `cfg_g64`-selected `sc_idx_a`/`sc_idx_b` pair and the second scale
register `mac_mb_q`; the `cfg_w8 && cfg_g64` `$error`.

**Out of `rtl/matvec_chan.sv`:** `csr_static_w8`, `csr_static_g64`, SHAPE
bits 29 and 28 in the decode, the readback, and the header table.

**No dead logic is left under a comment.**  The header now describes the
one row format the engine has; the two deleted modes are named in a boxed
paragraph as DELETED, with the measurement that priced the W8 one, and
nothing below that paragraph mentions them as live.

---

## 2. The retired targets and vector families — recorded, not hidden

| retired | what it tested | why it went |
|---|---|---|
| `make -C tb tb_matvec_w8` | the W8 engine mode end to end: 4 shapes × 4 seeds, mixed W4/W8 on one instance, chunk=1/3, `+nogap`, the `w8+g64` `$error` loud-in-sim / quiet-under-`+define+SYNTHESIS`, the `-128` rejection, and `sw/hwmap.py`'s bit-29 selftest | the mode does not exist in this bitstream |
| `make -C tb tb_matvec_chan_w8` | the same SHAPE bit 29 through the full CSR/DMA chain | ditto |
| `make -C tb tb_matvec_g64` | the g64 mode: 6 shapes × 4 seeds, MIXED g128/g64 without reset, chunk=5, and `+nogap +pairs` | ditto (§5.2 S6) |
| `make -C tb tb_matvec_chan_g64` | g64 through the full chain | ditto |
| `W8SHAPES` = `w1:23:128 w2:17:512 w3:9:2048 w4:7:6144`, the `w8_vectors` target, and the DIRECTED `w5_maxmag` case | vectors for the W8 lane array, `w5` sitting exactly on its 15/16/18/20/21-bit envelope, plus `maxmag128` (weight code `-128`) which the generator had to REFUSE | the DUT they drove is gone |
| `V2SHAPES` = `a:64:1024 b:37:3584 c:13:4096 d:16:2048 e:9:128 f:11:6144` and the `v2_vectors` target | the (g128, g64) TWIN family — every case existed so a g64 run had a same-shape g128 partner for `+pairs` | its only consumers were the two g64 targets.  Its distinct W4 coverage is CARRIED FORWARD, not dropped: NG 32 (the exact `ceil(NG/32) == 1` boundary, shape `c`) is the new 9B shape `q1`; NG 8/28/16 (`a`/`b`/`d`) are the frozen `tb_matvec` shapes `vec_s1`/`vec_s2`/`vec_s4`; NG 1 (`e`) is `n1` and NG 48 (`f`) is `n5` |
| `tb/tb_matvec.sv`'s `+w8g64test` plusarg and its `+define+SYNTHESIS` control build | that the illegal-combination `$error` is loud in sim and absent on silicon | there is no illegal combination left to raise it |
| `tb/tb_matvec.sv`'s `+pairs` mode and the `c_g64`/`c_w8`/`c_k` case arrays | that a g64 run costs no more than its g128 twin plus the extra scale beats | it is a comparison BETWEEN the two group modes; one of them is gone.  `+nogap` keeps `+maxstall`/`+ngfloor`, which are the bounds that were doing the work on the g128 half |
| `tb/scripts/gen_matvec_v2_vectors.py`'s `g` and `w8` CLI arguments, its `maxmag`/`maxmag128` kinds, its `_envelope()` assert, and the 6th and 7th fields (`G64`, `W8`) of each vector dir's params file | the generator side of all of the above | the fields are always 0 now; the params file is back to the 5-field form `ref/gen_matvec_vectors.py` has always emitted |
| `make -C tb tb_seq_chip_w8` and `tb_seq_chip_w8_smoke` | the full 2B W8 chip replay (R-c / V5) | **REFUSE with a message rather than mis-verify.**  A W8 SHAPE word now decodes as a W4 one, so the chip would silently disagree with its `.chip` golden.  The targets and the whole recipe are KEPT — they are the record of how `build_035`'s chain was gated and the recipe a pre-G3 checkout still runs — under a dated banner in `tb/Makefile`.  (G3.1 had already made the family unrunnable from a post-G3 checkout for an independent reason: the pinned 2B artifacts are SEQ_ISA v1.7 streams.) |

**What did NOT go, and this is the half that is easy to get wrong.**  The
**host-side W8 law stays** (spec §3.3): `ref/w4a8_ref.py`'s W8 section,
`quantize_weights8` / `pack_ddr_rows8` / `row_stride8` / `matvec_y32_w8`,
`sw/hwmap.py`'s `w8` plumbing, and `ref/seq_model.py`'s
`selftest_w8_mvgo` / `selftest_repack` W8 goldens — all still run, and
`selftest_w8_mvgo` still PASSES (§8).  `build_035` is resident and still
serves the 2B in W8; the strip is RTL-only.  `sw/hwmap.py`'s
`assert not (w8 and g == 64)` is vacuous for this build and **stays**,
guarding the old bitstreams' host path.

**Closed with this step:** the open follow-on *"W8 CSR-decode range checks"*
(`NEXT_SESSION.md`) is moot — there is no W8 CSR field left.  It is struck
in place with what replaced it: `shape_word` now range-checks `ng`/`sh`/
`nrows` in **both** layouts, and `isa_bits.py --shape` / `--shape-control`
gate the word mechanically (§5, §9).

---

## 3. THE W4 BIT-IDENTICAL PROOF — M, two halves

The claim is *"the subtraction changed nothing about W4"*, and it is checked
on both sides of the DUT boundary.

### 3.1 The vectors are byte-identical — `134_w4_vector_bitidentical.log`

The generator was rewritten in the same step, so its output has to be
proven a no-op before any RTL result means anything.  `a08a90b` was exported
with `git archive` into `.g33_baseline/` and its `tb_matvec`/`tb_matvec_ng`
vector sets regenerated with the `a08a90b` generator; the working tree
regenerated its own with the new one.

**Result: 84 of 84 files byte-identical** — `x8.hex`, `beats.hex` and
`y32.hex` for the four frozen `vec_s1..4` dirs and for `n1..n6 × 4 seeds`
at g128.  The ONLY difference is the params file, which loses its two
always-zero trailing fields:

```
  a08a90b : 6144 48 8 9 50 0 0
  now     : 6144 48 8 9 50
```

### 3.2 The RTL reproduces them — `130_…` vs `133_…`

| | `a08a90b` export (130) | after the strip (133) |
|---|---|---|
| `tb_matvec` | 4 seeds PASS, `vec_s1..4` | 4 seeds PASS, same dirs |
| `tb_matvec_ng` | 16 runs × up to 12 cases (g128 **and** g64) | 16 runs × 6 cases (g128 only) |
| `tb_matvec_chan` | 4 seeds PASS, K = 1024/3584/256/2048 | 4 seeds PASS, same K |
| `tb_mvshim_b` | 4 seeds PASS (2 fast ui_clk, 2 slow) + the `+sabotage` self-test | identical |
| `lint_matvec`, `lint_mvshim_b` | `-Wall` clean | `-Wall` clean |
| PASS/OK markers | 31 | 28 |

The marker count drops by exactly the three g64-only `tb_matvec_ng` runs
(chunk=1, chunk=3 and the g64 half of the random run print fewer PASS
lines); every W4 case that ran before still runs and still compares
bit-exact against the SAME committed goldens, which is what "bit-identical"
means here — `y32` equality against `ref/w4a8_ref.py`, not log equality.

**MAX_NG was still 48 for log 133.**  The widening is a separate step and a
separate run (§7).

---

## 4. The width table — M, read out of the post-change tree

"before" is `git show a08a90b:rtl/matvec_engine.sv`; "after" is the
committed tree.  The first block is §4.5's widening; the second is §5.1's
**narrowing**, which is where the LUT saving lives and which the spec asks
for in the same breath ("the widened adder tree ... goes").

### 4.1 Widened for `MAX_NG = 96`

| # | site | before | after | why |
|---|---|---|---|---|
| 1 | `rtl/matvec_engine.sv:142` `parameter int MAX_NG = 96` | 48 | **96** | `down_proj` is K = FFN = 12288 → ng = 96.  The comment is RE-DERIVED: "K <= 6144" → "K <= 12288" |
| 2 | `rtl/matvec_engine.sv:150` `input wire [6:0] cfg_ng` | 6 b | **7 b** | 96 > 63 |
| 3 | `rtl/matvec_engine.sv:219` `x_mem [32][MAX_NG]` | 1536 words | **3072** | 96 lines × 1024 b |
| 4 | `rtl/matvec_engine.sv:223` `x_mem[b][x_waddr[11:5]]` | `[10:5]` | **`[11:5]`** | 96 backed lines need a 7-bit line index |
| 5 | `rtl/matvec_engine.sv:163` `input wire [11:0] x_waddr` | 11 b | **12 b** | 3072 words |
| 6 | `rtl/matvec_engine.sv:247` `logic [6:0] x_line` | 6 b | **7 b** | the group index that addresses `x_mem` |
| 7 | `rtl/matvec_engine.sv:302,319,352,368,386,408` `g_q`,`g1_q`,`g2_q`,`g3_q`,`g4_q`,`g5_q` | 6 b ×6 | **7 b ×6** | the ng index travelling with each pipeline stage; the comment "0..NG-1 <= 47" is now "<= 95" |
| 8 | `rtl/matvec_engine.sv:527` `logic [6:0] r_g` | 6 b | **7 b** | the retire walk index; its four literals (`+ 6'd1`, `== 6'd0`) move with it |
| 9 | `rtl/matvec_engine.sv:453-454` `acc_bank_lo [2][MAX_NG]` and its `_hi` twin | 48 | **96** | parameterized, moves with #1 |
| 10 | `rtl/matvec_chan.sv:228` `logic [6:0] csr_static_ng` | 6 b | **7 b** | the CSR shadow feeding #2 |
| 11 | `rtl/matvec_chan.sv:235` `logic [11:0] xptr`, `:342` `wdata_q[11:0]`, `:361` readback | 11 b | **12 b** | 3072 x words |
| 12 | `rtl/matvec_chan.sv:252-260` and `rtl/matvec_chan.sv:404`, `rtl/matvec_chan.sv:436` — the x-write FIFO payload | 43 b | **44 b** | it carries `{xptr[11:0], data[31:0]}`.  **`xq_d` at `rtl/matvec_chan.sv:404` is where log 135 failed** — see §4a |  <!--cites:noquote-->
| 13 | `rtl/matvec_chan.sv:564` `XWIN_WORDS`, `:566` `wb_ptr`, `:606-607` the decode, `:614` its SLVERR | 1536 / 11 b / 6 KiB | **3072 / 12 b / 12 KiB** | §6 |
| 14 | `rtl/seq_movers.sv:195` `XWIN_WORDS` (**the second copy**) and `:191` `MVB_XWIN`'s comment | 1536 | **3072** | the mover's own `$error` bound reads it |

### 4.2 Narrowed back to the W4 law (spec §5.1's "widened adder tree")

|w| ≤ 8 (a sign-extended nibble) and |x8| ≤ 128, and every tree stage is an
exact sum, so each width is one bit past the worst value it can hold.  **D**,
arithmetic; **M**, because a wrong width wraps and the bit-exact TB catches
it on four seeds at eleven shapes.

| site | W8 envelope (before) | W4 law (after) | bound |
|---|---|---|---|
| `rtl/matvec_engine.sv:342` `prod_q` | 16 b | **12 b** | 8·128 = 1024 |
| `rtl/matvec_engine.sv:375` `sum64_q` | 16 b | **13 b** | 16·128 = 2048 |
| `rtl/matvec_engine.sv:391` `sum16_q` | 18 b | **15 b** | 64·128 = 8192 |
| `rtl/matvec_engine.sv:409` `sum4_q` | 20 b | **17 b** | 256·128 = 32768 |
| `rtl/matvec_engine.sv:431` `acc_lo_q`/`acc_hi_q`, `:453-454` the banks, `:546` `mac_lo_q`/`mac_hi_q` | 21 b | **18 b** | 512·128 = 65536 |
| `rtl/matvec_engine.sv:553` `pa_q`/`pb_q` | 38 b | **35 b** | 17 × 18, still ONE DSP48E2 each (27×18 signed) |
| `rtl/matvec_engine.sv:557` `ps_q` | 39 b | **36 b** | `pa + pb` |
| `rtl/matvec_engine.sv:182` `NSCAL` | `2 * MAX_NG` = 96 | **`32 * ((MAX_NG + 31) / 32)`** = 96 | the scale buffer was sized for mode 1's TWO scales per group.  At MAX_NG = 96 the two expressions coincide at 96 — but they are different derivations, and the new one is what the scale BEATS need (3 × 32).  Under the old rule the same MAX_NG would have demanded a 192-entry NSCAL:1 mux |  <!--cites:noquote-->
| `rtl/matvec_engine.sv:543,517` `sc_idx` / `mac_m_q` | `sc_idx_a`+`sc_idx_b`, `mac_ma_q`+`mac_mb_q` | **one of each** | with g64 gone both operands are the SAME `m_g`; keeping two identical reads of one mux would be dead duplication.  The mux itself is unchanged in form — `r_g` still feeds it directly, and nothing was inserted between them |

### 4.3 The confirmed NON-movers, with their arithmetic

| site | stays | why — **D** |
|---|---|---|
| `rtl/matvec_engine.sv:238` `g_cnt` | **7 b** | RE-DERIVED, not scaled.  The old comment said "7 bits: 2*MAX_NG + 2 = 98 at MAX_NG = 48", which is the W8 beat doubling.  In W4 the counter runs `0 … MAX_NG + ceil(MAX_NG/32) − 1 = 96 + 3 − 1 = 98`, which fits 7 bits (max 127).  **Same number, different derivation** — which is exactly why the brief demanded a re-derivation |
| `wbeats` | **DELETED, not widened** | it existed only as the `cfg_w8 ? {cfg_ng,1'b0} : {1'b0,cfg_ng}` mux.  In W4 it *is* `cfg_ng`, so `is_scale_beat`, `last_scale_g` and `scale_beat_idx` now read `cfg_ng` directly |
| `ng7` | **DELETED, not widened to 8 b** | it was `{1'b0, cfg_ng}` zero-extending a 6-bit port into 7-bit arithmetic.  `cfg_ng` is 7 bits itself now, so the wire had no consumer left.  (§4.5's row offered "8 b, or deleted with `cfg_ng` already 7 b"; deleted.) |
| `rtl/matvec_engine.sv:259` `n_scale_beats`, and `scale_beat_idx` | **2 b** | at the g128 cadence `n_scale_beats = ceil(ng/32)`, and the 9B rows are `ng ∈ {32, 64, 96}` → `{1, 2, 3}` with `scale_beat_idx ∈ {0, 1, 2}`.  Both fit two bits at EVERY 9B row.  This is also why g64 had to go: its `ceil(2·ng/32)` needs 6 bits at ng = 96 |  <!--cites:noquote-->
| `p_acc` | **48 b** | `MAX_NG · 65535 · 131072 = 8.25e11` at ng = 96, i.e. 41 bits used, **7 spare**.  Task 12 measures it rather than arguing it; the arithmetic is written into the RTL header so the next reader does not redo it |
| `cfg_sh` | **6 b** | unchanged by geometry |
| the 16-bit row counters, the 4096-row RES window, the 18-bit AMAX index | unchanged | listed by §4.5 as verified safe at 9B and deliberately not touched |

### 4a. The defect the widening introduced, and what caught it

`rtl/matvec_chan.sv:404` `logic [42:0] xq_d;` is the ui_clk-side register  <!--cites:noquote-->
between the CDC FIFO and the engine's x port.  The FIFO payload widened
43 → 44 bits with `xptr`, and `xq_d` did **not**, so `xq_d[43:32]` selected
one bit past the register.  **Verilator 5.020 `-Wall` did not warn** — the
lint was clean, `tb_matvec` (which writes `x_mem` directly) was clean,
`tb_matvec_chan` at K = 4096 and K = 8192 was clean, and the failure only
appeared at **K = 12288**, the one shape whose x index uses bit 11:

```
[51964000] FAIL: row 0: y32=00017c6c golden=ffff8ab9
```

`evidence/qwen9b/g3/135_tb_suite_9b.log:498`.  The `q3` shape is the
regression that exists for exactly this class, and it is kept.

---

## 5. The SHAPE word

### 5.1 The layout, and the deviation, stated plainly

**Adopted (the brief's option 1):**

```
SHAPE = {spare[31:29], ng[28:22], nrows[21:6], sh[5:0]}
```

CONTIGUOUS, three spare bits, no scattered field.  Stripping W8 and g64
frees bits 29 and 28; `ng` needs a seventh bit and the spec's constraint is
that **three spare bits remain**, which this satisfies while honouring the
same no-scattered-bits principle the ARG re-encoding adopts.  The
alternative — leave `nrows`/`sh`/`ng[5:0]` in place and put `ng[6]` on the
freed **bit 28** — was the fallback if the contiguous repack turned out to
cost anything in `matvec_chan`'s decode.  **It did not**: the decode is
three fixed `wdata_q` slices latched into three registers
(`rtl/matvec_chan.sv:331-333`), the same three assignments as before with
different constant ranges, and the readback is one concat
(`rtl/matvec_chan.sv:361-363`).  There is no measurement to report because
there is no logic to measure — no mux, no shifter, no added level — so the
fallback was not taken.

**Stated plainly because it is a deviation:** the spec's §5.2 sentence is
"`cfg_ng` widens into **bit 30** with three spare bits left".  Neither
option here puts `ng`'s seventh bit on bit 30.  What the spec's *constraint*
pins is the spare-bit count, and both options leave exactly three; the bit
position is not otherwise derived anywhere in the spec.  If the user reads
§5.2 as pinning bit 30, say so and the field moves — the arithmetic is
unaffected.

`isa_bits.py --shape` MEASURES the spare-bit count off the RTL rather than
taking this paragraph's word for it, and FAILS if it is not three.

### 5.2 The packer is VERSIONED, and both halves of the resolution are done

`sw/hwmap.shape_word` is a **runtime CSR producer**, not only a stream
emitter: three tools write the packed word straight to a live BAR
(`sw/infer.py:244`, `sw/layer_test.py:133`, `sw/tok_meter.py:399`) and two
more put it into a stream record (`sw/seq_run.py:813`,
`ref/seq_format.py:1882`/`:2023`).  Spec §3.3 says `ref/` and `sw/` still
serve the old bitstreams, so an unversioned repack would have broken that.

**1. The packer is versioned.**
`shape_word(nrows, sh, ng, g=128, w8=False, isa=2)` —
`isa=1` packs the `build_034`/`build_035` layout
(`{2'b0, w8[29], g64[28], nrows[27:12], sh[11:6], ng[5:0]}`), `isa=2` the 9B
one.  `isa=2` **refuses** `g=64` and `w8=True` outright rather than dropping
them, because there is no bit to carry them; both refusals name `isa=1` in
the message.  **`isa=2` also refuses `ng` outside the ENGINE ENVELOPE `1..MAX_NG`**, not
merely outside the 7-bit field (`sw/hwmap.py:105` `SHAPE_MAX_NG`, `{1: 48,
2: 96}` — one per layout, keyed to `rtl/matvec_engine.sv`'s parameter).  The
engine's own `1..MAX_NG` guard is `` `ifndef SYNTHESIS ``: LOUD in
simulation, ABSENT on silicon — so the packer is the only thing standing
between a bad `ng` and a silently wrong `y32` on a live board.

**FOUR direct-CSR callers derive the ISA from the VERSION CSR** —
`sw/infer.py`, `sw/layer_test.py`, `sw/tok_meter.py` and
**`sw/matvec_test.py`** — each in the same block that asserts MAGIC / CALIB /
IDENT and **before** anything is packed.  `sw/hwmap.shape_isa_for_version()`
has **NO DEFAULT**: an unmapped VERSION raises `UnknownBitstream` and every
caller turns that into its own REFUSING-TO-TOUCH-THE-BOARD exit.  The map
names BOTH resident images explicitly (`0x4F908DF2` `build_034`,
`0x54443B9F` `build_035`, both `isa=1`); Task 16 adds the 9B row in the same
edit that moves `sw/seq_run.EXPECTED_SEQ_VERSION`, and until it does every
tool here refuses a 9B board rather than guessing.  `sw/layer_test.py`,
`sw/tok_meter.py` and `sw/matvec_test.py` PRINT the chosen `SHAPE_ISA`
beside VERSION and record it in their JSON reports.

**Why a default was wrong, demonstrated rather than argued** — and asserted
in `_selftest_shape_word`: `shape_word(2048, 5, 8)` is `0x02020005` at
isa=2, and `build_034` decodes that word as `ng=5 nrows=8224 sh=0` where the
caller meant `ng=8 nrows=2048 sh=5`.  Plausible, completely different, and
silent.

`_selftest_shape_word` pins the `isa=1` path to the words read off the four
live SHAPE registers after the 2B run — `evidence/qwen2b/rd/RD_GATE.md:238`:

| | ch0 | ch1 | ch2 | ch3 |
|---|---|---|---|---|
| 2B W8 | `0x20800290` | **`0x20200290`** | `0x20800290` | `0x20800290` |
| 0.8B W4 control | `0x00800148` | `0x00200148` | `0x00800148` | `0x00800148` |

All four are pinned, not just the two the brief named, because the W4
control is the half that proves the *base* layout did not move either.  A
future edit cannot silently shift the old word.

**2. What is still not served** — §7.

### 5.3 The six implementations, in lockstep — M

`evidence/qwen9b/g3/isa_bits.py --shape` (the same script and the same shape
of proof Task 7 used for the ARG encoding; no new script was added):

| implementation | how it is checked |
|---|---|
| `sw/hwmap.shape_word` | the PRODUCER, driven at every value below |
| `rtl/matvec_chan.sv` | **PARSED**, twice and independently inside the same file: the CSR WRITE case (`csr_static_* <= wdata_q[hi:lo]`) and the READBACK concat, which must agree with each other — a design that latched and reported different bits would pass either alone.  The register DECLARATIONS are read too and must be at least as wide as the slices they latch |
| `ref/seq_format.disasm` | its rendered `ng=… nrows=… sh=…` is parsed back out |
| `ref/seq_model.SeqExec._mvgo` | the REAL decode is executed, with a capturing `DDRWeights.matvec` |
| `tb/tb_matvec_chan.sv` | **PARSED** out of its `wr32(12'h014, {…})` concat |
| `tb/seq_stub_mvchan.sv` | STRUCTURAL: it must keep the word opaque (`10'h005: shape <= wdata_q;`) and must not grow a field decode — if it ever does, the checker refuses until it is listed as a seventh implementation |
| **every `R_SHAPE` writer in `sw/`** | STRUCTURAL, added at fix round 1: the checker walks `sw/*.py`, finds every `wr(… R_SHAPE …)` and requires the statement to name `shape_word` **and** an `isa=`.  "One packer, every producer in lockstep" is only a contract if something checks it — `sw/matvec_test.py` hand-rolled the packing and was invisible to every check above.  **4 of 4 producers PASS**; reverting `sw/matvec_test.py` to the hand-rolled line makes `SHAPE_BITS: FAIL`, which is the control |  <!--cites:noquote-->

**Result (log `142`):**

```
  field   rtl/matvec_chan.sv   tb/tb_matvec_chan.sv   width
  ng      [28:22]             [28:22]                7 b
  nrows   [21: 6]             [21: 6]               16 b
  sh      [ 5: 0]             [ 5: 0]                6 b
  spare bits: 3 (spec 5.2 pins THREE)
  isa=2 round-trips: 88 of 88 value sets (ng [1, 32, 64, 96] x nrows [0, 1, 65535] x sh [0, 63] + 64 seeded random) …
  isa=1 round-trips: 22 value sets (4 PINNED to RD_GATE.md:238 + ng 1/32/63 x nrows 0/1/65535 x sh 0/63) …
SHAPE_BITS: PASS
```

**The negative control** (`--shape-control`, log `143`) narrows or widens one
RTL field at a time and requires the round trip to refuse each: **5 of 5
REFUSED** (`ng`, `ng_wide`, `nrows`, `sh`, `sh_wide`).  `sw/hwmap.py
--selftest` carries its own field-width control in both layouts, including
the one that matters — `shape_word(…, ng=96, isa=1)` must be REFUSED,
because "96 does not fit six bits" is the whole reason the layout moved.

---

## 6. The XWIN aperture — the row that belongs INSIDE the wall

The 64 KiB per-channel stride was never the constraint; **the decode was**
(feasibility §2.5, quoted by spec §4.5).  Both are widened:

| | before | after |
|---|---|---|
| decode (`rtl/matvec_chan.sv:606-607`) | `awaddr[15:13] == 3'b010 && awaddr[12:11] != 2'b11` → `0x4000…0x57FF` | `awaddr[15:14] == 2'b01 && awaddr[13:12] != 2'b11` → **`0x4000…0x6FFF`** |  <!--cites:noquote-->
| `wb_ptr` (`rtl/matvec_chan.sv:566`, `rtl/matvec_chan.sv:608`) | `awaddr[12:2]`, 11 b | **`awaddr[13:2]`, 12 b**, words 0…3071 |  <!--cites:noquote-->
| `XWIN_WORDS` | 1536 in `rtl/matvec_chan.sv` **and** 1536 in `rtl/seq_movers.sv:195` | **3072 in both** |
| the sim-only AW bound (`rtl/matvec_chan.sv:655-660`) | 11-bit base | 12-bit base, `XWIN_WORDS - 1` |
| `xptr` (AXI-Lite) | 11 b | **12 b** |

The mvchan burst window is 64 KiB per channel with RES reads at
`0x0000–0x3FFF`, so 12 KiB of XWIN fits with the SLVERR behaviour unchanged:
`0x7000–0x7FFF` is what answers SLVERR now.

**TB twins (spec §7.5 A), all moved:** `tb/tb_matvec.sv:55` `MAXX` and its
`x_waddr` (11 → 12 b, and the `11'(i)` cast with it);
`tb/tb_matvec_chan.sv:14` `MAXX` and its `% 2048` XPTR check — which
*encoded the 11-bit XPTR* and is commented as such — now `% 4096`;
`tb/tb_mvshim_b.sv` `NX` at its declaration and every use, the "11-bit
counter" wording in T5, and T8's boundary probes; `tb/mvshim_b_stubs.sv`'s
11-bit `x_waddr` port and its `{5'b0, x_waddr}` RES echo;
`tb/seq_stub_mvchan.sv`'s 11-bit `xptr`, its burst decode and its window map
at three places.

**`tb_mvshim_b` T8 was rebuilt, not just moved.**  A boundary test that only
ever moves outward proves nothing about the bits that moved, so T8 now
checks BOTH sides: `0x7000` and `0x7800` must SLVERR, and `0x5800`, `0x6000`
(the two addresses that were REJECTED under the 6 KiB window) and `0x6FF0`
(the last four words) must now be ACCEPTED **and must land** — each is read
back through the RES echo.

**A third, unlisted copy of the decode was found and moved:**
`tb/tb_seq_unit.sv:593-595`, the burst-AW scoreboard bound, carried
`mb_awaddr[15:13] !== 3'b010 || mb_awaddr[12:11] === 2'b11` as a `$fatal`.
It would not have fired on today's vectors (the largest MOVX is 1536 words)
but it is a twin of the RTL decode and would have refused the first 3072-word
MOVX anyone wrote.  Declared as a deviation (§10).

---

## 7. Which host tools are valid against which bitstream — BY NAME

**RE-DERIVED from the code as it stands after fix round 1** (the round-1
version of this table over-claimed: `sw/layer_test.py` and `sw/tok_meter.py`
had no VERSION gate at all, and `sw/matvec_test.py` was not in it).  Every
row was checked against the source, not remembered.

**The rule the table rests on:** `sw/hwmap.shape_isa_for_version`
(`sw/hwmap.py:118-134`) has **NO DEFAULT** — an unmapped VERSION raises
`UnknownBitstream`, and all four direct-CSR tools resolve it in the same
block that asserts MAGIC / CALIB / IDENT, **before** anything is packed.
The map (`sw/hwmap.py:96-105`) names every image explicitly:
`0x4F908DF2` `build_034_po2_AltSpreadLogic_high` and `0x54443B9F`
`build_035_fp2a_exc_po`, both **isa=1**; the hashes come from where this
tree already records them (`sw/seq_run.py:124`, `sw/seq_run.py:130`,
`sw/infer.py:98`).

> **RE-ANCHORED AND AMENDED 2026-09-10 (pre-ship documentation chore).**
> Two things. **(1)** Every pointer in this section was hand-written in
> post-fix coordinates and then run through a `--fix` pass, so the numbers
> were shifted twice while the content stayed right; they are re-derived
> against HEAD here. `spec_cites` cannot see this class — a pointer that
> lands on a plausible line of the right file passes EXIST and RANGE — so
> the repair is by hand and by reading.  **(2)** The third column below is
> now HISTORICAL for the four direct-CSR tools: **Task 15 (G6) added the
> 9B row** to `sw/hwmap.py`'s map — `0xC973C18A` `build_041_ckr2`, the
> value G6 read back off the silicon — so those tools no longer REFUSE a
> 9B bitstream. What this section establishes and what still stands is the
> RULE: there is no default, the resolution happens in the identity gate,
> and an image this checkout has no row for refuses rather than guessing.
> **(3)** *(Added by this chore's fix round, 2026-09-10.)* Two of the three
> hash sources the paragraph above names have moved on with Task 15. At HEAD
> `sw/seq_run.py:132` reads `EXPECTED_SEQ_VERSION = 0xC973C18A`
> and `sw/infer.py:98` reads `EXPECT_VERSION = 0xC973C18A`
> (both build_041, 9B), so neither records `0x54443B9F` any longer;
> build_035's hash survives in this tree only as the trailing "Was" note on
> that `sw/infer.py` line. `sw/seq_run.py:124` still records
> `0x4F908DF2 build_034`, and the `sw/hwmap.py` row the paragraph is about is
> unchanged.

| tool | vs `build_034` | vs `build_035` | vs a 9B bitstream |
|---|---|---|---|
| `sw/infer.py` (`sw/infer.py:159-172`, `sw/infer.py:244-245`) | **VALID** with `--expect-version 0x4f908df2` | **VALID** (its own `EXPECT_VERSION`) | **REFUSES** until Task 16 adds the row |
| `sw/layer_test.py` (`sw/layer_test.py:86-96`, `sw/layer_test.py:132-133`) | **VALID** | **VALID** | **REFUSES** |
| `sw/tok_meter.py` (`sw/tok_meter.py:211-221`, `sw/tok_meter.py:428-429`) | **VALID** | **VALID** | **REFUSES** |
| `sw/matvec_test.py` (`sw/matvec_test.py:84-95`, `sw/matvec_test.py:123-124`) | **VALID** | **VALID** | **REFUSES** |
| `sw/hwmap.py` itself | **VALID** — `shape_word(..., isa=1)` pinned to RD_GATE's live words | **VALID** | packs `isa=2` on request; the VERSION map is what gates a board |
| `evidence/qwen2b/rd/rd_census.py:95` | **VALID** — LAYOUT-AGNOSTIC: it prints the raw SHAPE word and decodes no field.  It is where `RD_GATE.md:238`'s numbers came from | **VALID** | **VALID** |
| `ref/w4a8_ref.py` (W8 section, `matvec_y32_w8`, `pack_ddr_rows8`, `row_stride8`), `ref/model_select.py` | **VALID** — spec §3.3; never touched | **VALID** | **VALID** |
| `ref/seq_model.py` `selftest_w8_mvgo`, `selftest_repack` | **VALID** — they say `isa=HW.SHAPE_ISA_PRE_G3` explicitly | **VALID** | n/a (host goldens) |
| pinned `.e` / `.seq` streams | **UNAFFECTED** — the SHAPE word travels inside the record as data | **UNAFFECTED** | **UNAFFECTED** |
| `sw/seq_run.py --seq-run` / `--seq-dry-run` on a pinned pre-G3 stream | **VALID** — it uploads and launches BYTES; it never re-emits the SHAPE word | **VALID** | n/a |
| `sw/chat_seq.py` in any mode that DECODES a stream (`--verify`, `--model-only`) | **PRE-G3 CHECKOUT** | **PRE-G3 CHECKOUT** | valid once the artifacts are 9B |
| `ref/seq_model.SeqExec` on a pre-G3 **stream file** | **PRE-G3 CHECKOUT** | **PRE-G3 CHECKOUT** | valid |
| `ref/seq_format.py` EMITTING a W8 or g64 stream | **REFUSED** by `shape_word(isa=2)` | **REFUSED** | n/a |
| `ref/seq_format.disasm` on a pre-G3 stream | **misreads it** — ONE layout, deliberately | **misreads it** | correct |
| `make -C tb tb_seq_chip_w8` | **REFUSES** with a message (§2) | **REFUSES** | n/a |

**Why `ref/seq_format.disasm` is `isa=2`-only while `ref/seq_model.SeqExec`
is versioned, in one line:** the disassembler renders what THIS TREE emits
and this tree has exactly one emitter, whereas `SeqExec`'s `isa=` selector
picks a SHAPE FIELD LAYOUT — **not an ISA** — solely so the two W8 goldens
inside `ref/seq_model.py` can keep spec §3.3's host-side W8 law under test;
its ARG decode is SEQ_ISA v2.0 ONLY, so no `isa` value makes a real pre-G3
`.seq` file replayable and T7's "no v1.7 decoder path on main" stands
(`ref/seq_model.py:620-633`).

Task 16's `NEXT_SESSION.md` note must restate this table; it is not derivable
from §3.3 alone.


## 8. The suite — 4 seeds, snoke, one obj_dir per target

`137_tb_suite_9b.log`, `make -C tb VECPY=/home/cah/.venv/bin/python tb_matvec
tb_matvec_ng tb_matvec_chan tb_mvshim_b lint_matvec lint_mvshim_b`,
Verilator 5.020, `-Wall` clean, `rc: 0`, **56 PASS/OK markers**.

| target | runs | what |
|---|---|---|
| `tb_matvec` | 4 seeds × 1 case | the frozen `vec_s1..4` (K 1024/3584/256/2048) |
| `tb_matvec_ng` | 16 runs × 6 cases (n1..n6: NG 1/2/3/4/36/48) + **12 runs × 3 cases (q1/q2/q3: NG 32/64/96)** + 4 MIXED runs interleaving 9B and small-NG shapes on ONE instance with no reset | random gaps + backpressure, `+chunk=1/2/3`, `+nogap` with `+maxstall=0` / `+ngfloor=6` |
| `tb_matvec_chan` | 4 seeds × the 4 frozen shapes + **4 seeds × q1/q2/q3 with `+shapeback`** | the full async 250/300 MHz CSR/DMA chain; `+shapeback` reads SHAPE back so the NEW field placement round-trips through the real CSR.  It is passed ONLY on the 9B runs, because the extra CSR read shifts the AXI model's `$urandom` stream and the four frozen runs must stay cycle-reproducible against the stage-2 evidence |
| `tb_mvshim_b` | 4 seeds (2 fast ui_clk, 2 slow) + the `+sabotage` self-test | the burst shim on the REAL `matvec_chan`, now sweeping all **3072** XWIN words through both the AXI-Lite and the burst path and comparing them word for word |
| `tb_streamer_engine` | 4 seeds × the frozen `vec_s1..4` | the SECOND instantiator of `matvec_engine`: behavioural AXI4 read slave → `ddr_rd_streamer` → engine, with random `arready`/`rvalid` gaps.  **Added to the gate's target list at fix round 1**, where it was found broken (§14.1) |
| `lint_matvec`, `lint_mvshim_b` | — | `-Wall` clean, `matvec_chan` and `matvec_chan_ipi` |
| `sw/hwmap.py --selftest` | run INSIDE `tb_matvec_chan` | its docstring names that target as its gate, and at fix round 1 the invocation was actually WIRED there — the old one hung off `tb_matvec_w8`, which §2 retired |

**The `cfg_ng` refusal fails for the RIGHT reason.**  The self-test's
expected string moved with `MAX_NG`, and it was checked that the OLD string
is absent, not merely that the new one is present:

```
$ obj_dir_tb_matvec/tb_matvec +guardtest ; echo rc=$?
%Fatal: matvec_engine.sv:688: … matvec_engine: cfg_ng 97 unsupported (must be 1..96)
rc=134
  grep -c 'cfg_ng 49' → 0        grep -c 'cfg_ng 97' → 1
```

97 is the exact cliff, and the reason is re-derived too: the old one was
mode 1's `ceil(cfg_ng/16)` needing a third bit at 49; with mode 1 gone it is
the 7-bit `(cfg_ng + 31)` in `n_scale_beats` overflowing at 97, which makes
the count wrap to zero and turns the row's last WEIGHT beat into its "last
scale beat".

**Host regression floor** — `138_boardfree.log`, snoke:

```
  seq_run selftest:  2758 passed, 0 failed
  serve selftest:      85 passed, 0 failed
  chat_seq selftest:  356 passed, 0 failed
BOARDFREE_PASS
```

**No count moved.**  2758 / 85 / **356** is the committed baseline as of
G3.1: `evidence/qwen9b/g3/00_boardfree_baseline.log` (pre-G3) reads 357 and
`evidence/qwen9b/g3/11_boardfree_v20.log`, `14_boardfree_final.log` and
`38_boardfree_clean.log` (G3.1, `tree: 89bc9b0`) all read **356**.  The one
check that left did so at **Task 7, not here**.  Checked rather than
asserted: the 332 NAMED `check()` calls in `chat_seq.selftest` are
**identical, in order**, between this tree and a tree with `sw/hwmap.py`,
`sw/seq_run.py`, `sw/infer.py`, `sw/layer_test.py`, `sw/tok_meter.py` and
`ref/seq_format.py` reverted to `a08a90b`; the remaining 24 come from
`sw/head_cache.py._selftest`, which has exactly 24 `check()` calls and is
untouched.

`ref/seq_model.py --selftest` also PASSES, W8 goldens included:

```
W8 MVGO (SHAPE 0x200111c2, 17x256, stride 320B): packed-DDR and live-dict paths
  both == matvec_y32_w8 (|y|max 3297945), 2/2 wrong SHAPE words refused — PASS
REPACK (nch=2, 2 W8 images, 7 pieces): every piece's MVGO == matvec_y32_w8 …
```

---

## 9. The two D-CITE comments, RE-DERIVED

Task 7 deliberately left two stale pointers in `rtl/matvec_engine.sv` for
this task.  Both targets moved AGAIN here, so both were re-derived against
the post-change tree and each rendered `path:NNN` was read back beside its
source line:

| stale pointer (at `a08a90b`) | what it actually names now |
|---|---|
| "the burst path answers SLVERR outside the 1536-word XWIN (`rtl/matvec_chan.sv:550-554`)" | the decode is `rtl/matvec_chan.sv:606-607` and its SLVERR `rtl/matvec_chan.sv:614` — and the window is 3072 words |  <!--cites:noquote-->
| "the cfg_ng ENVELOPE assert below (":747")" | `rtl/matvec_engine.sv:717-719` — quoted with the FILE NAME, not a bare offset, because a bare offset is what rotted twice |  <!--cites:noquote-->

A third was found and fixed in the same class:
`tb/seq_stub_mvchan.sv`'s window-map comment cited
`rtl/matvec_chan.sv:596` for the burst decode; it now cites `:606-607`.

---

## 10. Deviations, declared

1. **The SHAPE bit position is not §5.2's literal bit 30** — §5.1 above, by
   controller ruling (option 1, the contiguous repack).  The spec's
   *constraint* (three spare bits) is met exactly.
2. **`ref/seq_model.py` was edited although the brief's file list does not
   name it.**  The brief names "`sw/chat_seq.py` (the SHAPE decoder)", but
   `sw/chat_seq.py` has **no SHAPE bit-unpack at all** — only prose, at its
   `SeqModelVerifier` docstring, which is fixed.  The second Python SHAPE
   DECODER in the tree is `ref/seq_model.py`'s `SeqExec._mvgo`.  Leaving it
   at the `isa=1` layout while `ref/seq_format.py` emits `isa=2` would have
   made the golden executor silently mis-decode every 9B stream (its
   `assert not (shape >> 30)` still passes on an `isa=2` word, so it would
   have been silent).  `SeqExec` gained an `isa=` selector defaulting to
   this tree's layout, and the two W8 goldens say `isa=HW.SHAPE_ISA_PRE_G3`
   explicitly — which KEEPS spec §3.3's host-side W8 law runnable instead of
   retiring it.
3. **`tb/tb_seq_unit.sv` was edited** — the burst-AW scoreboard bound is a
   third copy of the XWIN decode (§6).  Strict widening; no vector changes.
4. **`tb/scripts/gen_seq_unit_vectors.py` was edited** — one docstring line
   said its 1536-word MOVX "exercises the widened 0x4000-0x57FF mvchan
   window".  COMMENT ONLY; the generator's output is byte-identical.
5. **`docs/ARCHITECTURE.md` and `docs/SEQ_ISA.md` were edited** — three
   dated boxed notes and one TB-table row.  Nothing is deleted or struck:
   the sections describe `build_035`, which is resident and correct, and the
   notes say so and point at the post-G3.3 state.  Without them both files
   assert "the engine carries two orthogonal mode bits" and "the XWIN window
   is 1536 words" in the present tense about a tree where neither is true —
   the exact comment-hygiene class Tasks 7 and 8 were reviewed on.
6. **`evidence/qwen9b/g3/isa_bits.py`** and **`evidence/qwen_next/spec_cites.py`**
   join the pathspec by controller ruling (§5.3, §11).
7. **`NEXT_SESSION.md`** — the follow-on closure the brief's Step 1 requires.
8. **`.g33_baseline/`**, the `git archive a08a90b` export used for §3, is a
   scratch directory and is NOT committed; it is deleted before the gate
   run.  The log records the command that built it.

---

## 11. Citation drift — the class this gate caused, closed

The mechanism is `evidence/qwen9b/o3/o3_cite_drift.py` with
**`--base a08a90b`** and `--edited` naming every file this task touched, over
`docs/`, `evidence/`, `CHARTER.md` and `NEXT_SESSION.md` — the spec, the
plan, and every committed gate doc including `G3_1_ISA.md` and
`G3_2_VECNORM.md` (citation maintenance in those two is authorized; their
content is not touched).

| step | log | result |
|---|---|---|
| `--check` (RED, unfixed tree) | `150_cite_drift_check.log` | **196 drifted, 67 unresolved, 0 missing, 4 half-mapped** |
| `--fix` | `151_cite_drift_fix.log` | **196 citations in 42 documents** renumbered mechanically |
| `--verify` after the fix, before the class-B treatment | `152_cite_drift_verify.log` | 78 problems, all of them the 67+4 class-B rows and the two D-CITE pointers §9 rewrote |
| `--check` / `--verify` / `--range-control` / `--doc-cites --verify` on the treated tree | §11.2 | see below |

**Class A (196) — renumbered mechanically.**  Nothing was hand-edited.
One of them lands inside `rtl/layer_chan.sv` (a comment citing
`rtl/seq_movers.sv:600` → `:603`) — see §10.

**One file the fixer touched was REVERTED: `evidence/qwen9b/o3/o3_cite_drift.py`
itself.**  Its module docstring quotes a `docs/QWEN35_NEXT_FEASIBILITY.md`
row *as an illustration of a past defect* (`sw/infer.py:790-794` with four
bare continuations).  The auto-fix renumbered two of the five numbers and
left three, producing exactly the internally-inconsistent row the paragraph
warns against — and the docstring was already historical (the live row read
`789-793` before this task, not `781-785`).  G3.1 left it alone for the same
reason.  Reverted; the tool's behaviour is unchanged.

**Two pointers were REWRITTEN, not renumbered, and that is the point.**  The
fixer wanted to map `rtl/matvec_chan.sv:550-554` → `:541`/`:545`.  At
`a08a90b` those lines are the RES **read** decode (`rb_win <=
(s_axib_araddr[15:14] == 2'b00)`), not the XWIN write decode — the pointer
was WRONG, which is why Task 7 flagged it as a D-CITE and left it here.
Renumbering would have preserved the error at a new address.  §9 has the
re-derivation.

### 11.1 Post-G3.3 landmarks for every `<!--cites:noquote-->` row

Class B is *deleted source*, and the whole W8/g64 lane array is deleted
source, so there are many.  **59 document lines across 10 documents** carry
the marker, under a dated boxed note in each affected section (§7.6
precedent: the note names what was deleted; nothing is struck or removed).
The landmark for each pre-G3.3 citation:

| pre-G3.3 citations | what they quoted | post-G3.3 landmark |
|---|---|---|
| `rtl/matvec_engine.sv:221` (`cfg_w8` port), `:297` (`w8_phase`), `:365`/`:383` (`ph_q`), `:424`/`:427` (the 8-bit operand mux), `:10`/`:13` (the header's W8 paragraph), `:101`/`:106`/`:119`/`:126` (the W8 width table) | the W8 engine mode | **DELETED — no successor line.**  `rtl/matvec_engine.sv:19-24` is the boxed paragraph that records the mode, its price (`+5,826 LUT` / `+497 CARRY8` per channel) and why it went.  The W4 width table that replaced the W8 one is `rtl/matvec_engine.sv:52-78` |
| `rtl/matvec_engine.sv:294` (`wbeats`), `:311` (`ng7`), `:312-313` (`n_scale_beats`), `:320` (`scale_beat_idx`), `:633-634` (`sc_idx_a`/`sc_idx_b`) | the g64 mode and the two wires that existed only to select on it | **DELETED / COLLAPSED.**  `rtl/matvec_engine.sv:25-28` records the mode; the scale-beat count is now the single `2'((cfg_ng + 7'd31) >> 5)` at `rtl/matvec_engine.sv:259`, `scale_beat_idx` at `:266`, and the scale mux index is one `sc_idx` at `:543` |
| `rtl/matvec_chan.sv:18`/`rtl/matvec_chan.sv:20`/`rtl/matvec_chan.sv:45` (the SHAPE header table), `rtl/matvec_chan.sv:336` (`csr_static_ng <= wdata_q[5:0]`), `rtl/matvec_chan.sv:340` (`csr_static_w8 <= wdata_q[29]`) | SHAPE bits 28/29 and the 6-bit `ng` decode | `rtl/matvec_chan.sv:18-42` (the new header table) and `rtl/matvec_chan.sv:331-333` (the three-slice decode).  §5.1 |  <!--cites:noquote-->
| `rtl/matvec_engine.sv:209` (`MAX_NG = 48`), `rtl/matvec_engine.sv:216` (`cfg_ng [5:0]`) | the 48-group ceiling | `rtl/matvec_engine.sv:142` and `:150`.  §4.1 rows 1-2 |  <!--cites:noquote-->
| `rtl/matvec_engine.sv:273` (`x_waddr[10:5]`), `rtl/matvec_engine.sv:291` (`x_line`), `rtl/matvec_engine.sv:361`/`rtl/matvec_engine.sv:405`/`rtl/matvec_engine.sv:450`/`rtl/matvec_engine.sv:468`/`rtl/matvec_engine.sv:489`/`rtl/matvec_engine.sv:522` (`g_q`…`g5_q`), `rtl/matvec_engine.sv:619` (`r_g`) | the 6-bit ng indices and the 1536-word `x_mem` | `rtl/matvec_engine.sv:223`, `:247`, `:302`/`:344`/`:377`/`:393`/`:411`/`:433`, `:527`.  §4.1 rows 3-8 |  <!--cites:noquote-->
| `rtl/matvec_engine.sv:281` and the half-mapped range `:281-283` | *"7 bits: 2\*MAX_NG + 2 = 98 at MAX_NG = 48"* — a W8 statement | `rtl/matvec_engine.sv:230-236`, RE-DERIVED (`MAX_NG + ceil(MAX_NG/32) − 1 = 98`).  Same number, different derivation — §4.3 |  <!--cites:noquote-->
| `rtl/matvec_engine.sv:547-548` (`acc_bank_lo/_hi`, 21 b) | the W8-envelope accumulator banks | `rtl/matvec_engine.sv:453-454`, 18 b.  §4.2 |
| `rtl/matvec_engine.sv:262`/`:265` | the two stale D-CITE pointers Task 7 left | `rtl/matvec_engine.sv:207-218`, re-derived — §9 |
| `rtl/matvec_chan.sv:230` (`xptr` 11 b), `rtl/matvec_chan.sv:566`/`rtl/matvec_chan.sv:568` (the 6 KiB window comment), `rtl/matvec_chan.sv:571` (`XWIN_WORDS`), `rtl/matvec_chan.sv:573` (`wb_ptr`), `rtl/matvec_chan.sv:613`/`rtl/matvec_chan.sv:614` (the decode and its SLVERR), `rtl/seq_movers.sv:195` | the 6 KiB XWIN aperture and its 11-bit pointers | `rtl/matvec_chan.sv:226`, `rtl/matvec_chan.sv:557-562`, `rtl/matvec_chan.sv:564`, `rtl/matvec_chan.sv:566`, `rtl/matvec_chan.sv:606-607`/`rtl/matvec_chan.sv:614`, `rtl/seq_movers.sv:195`.  §6 |
| `sw/hwmap.py:52`, `:56`, `:65` and the half-mapped ranges `:36-52`, `:56-72`, `:65-73` | the SHAPE block comment and the UNVERSIONED `shape_word` signature | `sw/hwmap.py:40-71` (the two-layout block) and `sw/hwmap.py:137-169` (`shape_word(..., isa=…)`) and `sw/hwmap.py:118-134` (`shape_isa_for_version`).  §5.2 |
| `sw/infer.py:237`, `sw/layer_test.py:124` | the direct-CSR `shape_word` calls, before the ISA argument | `sw/infer.py:243-244`, `sw/layer_test.py:132-133`.  §5.2 |
| `tb/Makefile:266`/`tb/Makefile:269` | the `-128` rejection self-test inside `tb_matvec_w8` | **DELETED with the target.**  `tb/Makefile:60-70` records the retirement.  §2 |
| `tb/tb_matvec.sv:66`, `tb/tb_matvec_chan.sv:14`/`tb/tb_matvec_chan.sv:206`/`tb/tb_matvec_chan.sv:207`, `tb/tb_mvshim_b.sv:19`/`tb/tb_mvshim_b.sv:43`/`tb/tb_mvshim_b.sv:589`, `tb/mvshim_b_stubs.sv:54`, `tb/seq_stub_mvchan.sv:38`/`tb/seq_stub_mvchan.sv:48`/`tb/seq_stub_mvchan.sv:118` | the TB twins' 1536-word windows, 11-bit pointers and `0x4000-0x57FF` maps | `tb/tb_matvec.sv:55`, `tb/tb_matvec_chan.sv:14`/`tb/tb_matvec_chan.sv:203-208`, `tb/tb_mvshim_b.sv:17-21`/`tb/tb_mvshim_b.sv:43`/`tb/tb_mvshim_b.sv:591-622`, `tb/mvshim_b_stubs.sv:52`, `tb/seq_stub_mvchan.sv:38-44`/`tb/seq_stub_mvchan.sv:47-54`/`tb/seq_stub_mvchan.sv:123`.  §6 |
| `docs/HISTORY.md:781` | the *"W8 CSR-decode range checks"* follow-on line | `docs/HISTORY.md:781-790`, struck in place with what replaced it.  §2 |

### 11.2 The closing runs, and every residual accounted for

| run | log | result |
|---|---|---|
| `--range-control` | `160_cite_drift_range_control.log` | **PASS** — a half-mapped range is never rewritten (0 problems) |
| `--check --negative-control` | `161_cite_drift_negctl_check.log` | **CAUGHT** (405 reported) |
| `--verify --negative-control` | `162_cite_drift_negctl_verify.log` | **CAUGHT** (199 complaints) |
| `--verify` (source half) | `159_cite_drift_verify_r2.log` | 95 problems, ALL classified below |
| `--doc-cites --check` | `153_cite_drift_doccites.log` | 69 drifted of 87 |
| `--doc-cites --verify`, three fix rounds | `155`, `156`, `157`, `158_cite_drift_doccites_verify_r4.log` | 45 → 29 → 11 → **11**, all classified below |
| `spec_cites.py` on the gate doc, the spec, the plan, `docs/SEQ_ISA.md`, `G3_1_ISA.md`, `G3_2_VECNORM.md` | `163`, `164`, `165`, `168`, `169_spec_cites_r5.log` | **PASS — FAIL 0** (2074 exist, 1124 range, 67 quote, 195 noquote).  The first four rounds are the gate doc's OWN citation defects being closed: 30 → 7 → 0, then 7 again when §11.2 was written, then 0 |
| `spec_cites.py --selftest` with the plan's path | `166_spec_cites_selftest.log` | **PASS**, 6/6 negative controls CAUGHT |
| `evidence/qwen9b/g2/spec_cites_selftest_regression.sh` | `167_spec_cites_selftest_regression.log` | **PASS**, every pinned count unmoved (RC 27, RD 8, FINAL_BYTELOCK 0, G2A_HOST 0, D_TOL 3, RUNG_INT8_STATE 2, spec 0, plan 0) |

**`--verify`'s 95, classified.**  `o3_cite_drift --verify` has no exemption
mechanism — `spec_cites.py` is the checker that honours
`<!--cites:noquote-->` — so class B necessarily shows up here.

| n | class | disposition |
|---|---|---|
| 68 | UNRESOLVED — the cited line was DELETED | class B: `<!--cites:noquote-->` + a dated boxed note per section (§11.1) |
| 4 | HALF-MAPPED ranges (`rtl/matvec_engine.sv:281-283`, `sw/hwmap.py:36-52`, `sw/hwmap.py:56-72`, `sw/hwmap.py:65-73`) | class B, and the tool DELIBERATELY leaves them alone — `--range-control` PASSES, which is that behaviour under test |
| 8 | the trailing-endpoint complaints those four ranges generate | same four rows |
| 2 | `rtl/matvec_engine.sv` no longer cites `rtl/matvec_chan.sv:541` or `rtl/matvec_chan.sv:545` | the two D-CITE pointers, REWRITTEN not renumbered — §9 and §11 |
| 12 | citations in `evidence/qwen9b/o3/o3_cite_drift.py`'s own docstring | reverted on purpose — §11 |
| 3 | `evidence/qwen2b/ra/MOVER_NORM.md` ×2, `evidence/qwen2b/rb/RB_GATE.md` ×1 reported as not citing `docs/ARCHITECTURE.md:634`, `docs/ARCHITECTURE.md:635` and `docs/ARCHITECTURE.md:639` | **a FORM asymmetry in the tool, not a stale citation.**  Those two documents write the citation in its BASENAME form; `--check` resolves the basename and reported the drift, `--verify` looks only for the full-path token.  The citations ARE renumbered and correct — verified by hand against the base content |

**`--doc-cites --verify`'s 11, classified.**  Its cite sweep is taken from
the DOC-BASE by design ("the question *where did the line this document USED
to name go?* has one answer forever"), so a fixed citation still appears.

| n | complaint | disposition |
|---|---|---|
| 4 | `…:0 was rewritten away` in `evidence/qwen9b/g2/spec_cites_selftest_regression.sh` | the known artifact: its pinned expected-FAIL-count column parses as a citation.  Named by `G3_1_ISA.md` §13.2 and by `G3_2_VECNORM.md` §10.3 |
| 4 | `docs/QWEN35_NEXT_FEASIBILITY.md:764 was rewritten away` | HAND RE-READ, as the tool demands.  The row still exists — it moved to `docs/QWEN35_NEXT_FEASIBILITY.md:790` and its content changed only because a class-A renumber (`tb/Makefile:431` → `:289`) landed INSIDE it.  All four citing tokens (spec ×3, plan ×1) were renumbered to `:892` |
| 1 | `NEXT_SESSION.md:478 was rewritten away` | class B — the *"W8 CSR-decode range checks"* follow-on line this task struck.  The one citation (spec §5.1) carries `<!--cites:noquote-->` |
| 2 | `rtl/matvec_engine.sv` no longer cites `evidence/qwen2b/q2/v4_v5/W8_SKETCH.md:125` or `evidence/qwen2b/q2/v4_v5/W8_SKETCH.md:132` | the CITING lines were deleted with the W8 width table; there is no citation left to renumber |

**One thing this leaves open, stated rather than hidden.**  The boxed notes
were added AFTER `--fix` ran, so `--fix`'s output was one insertion-offset
stale for the six documents that gained notes.  That was repaired in three
further passes (logs 155-158) and one range token corrupted by an
old→new chain (`docs/HISTORY.md:791-792` had briefly become `249-240`) was
found by `--doc-cites --verify` and repaired.  **The right order is notes
first, then `--fix`** — recorded here so the next task does not repeat it.

---

## 12. The gate evidence, re-run on a COMMITTED tree

Every log in §0 and §11.2 was produced on a DIRTY working tree; its
provenance header says so.  The gate itself is the re-run below, on the
COMMITTED tree `26e934b` — every header reads `=== tree: 26e934b` with no
`+dirty` flag.

| # | log | result |
|---|---|---|
| 180 | `evidence/qwen9b/g3/180_tb_suite_committed.log` | `make -C tb tb_matvec tb_matvec_ng tb_matvec_chan tb_mvshim_b lint_matvec lint_mvshim_b`, snoke, 4 seeds — **rc 0, 56 PASS/OK markers**, identical to `137` |
| 181 | `evidence/qwen9b/g3/181_boardfree_committed.log` | the board-free gate — **BOARDFREE_PASS, 2758 / 85 / 356** |
| 182 | `evidence/qwen9b/g3/182_isa_bits_committed.log` | the G3.1 ARG gate — **ISA_BITS: PASS**, 348 command encodings × 29 address sets |
| 183 | `evidence/qwen9b/g3/183_isa_bits_negctl_committed.log` | **NEGATIVE_CONTROL: PASS** — every one of the 19 ARG perturbations refused |
| 184 | `evidence/qwen9b/g3/184_isa_bits_shape_committed.log` | **SHAPE_BITS: PASS** — 88 isa=2 and 22 isa=1 value sets through six implementations |
| 185 | `evidence/qwen9b/g3/185_isa_bits_shape_control_committed.log` | **SHAPE_CONTROL: PASS** — 5 of 5 field-width perturbations refused |
| 186 | `evidence/qwen9b/g3/186_hwmap_selftest_committed.log` | `sw/hwmap.py --selftest` — the `isa=1` RD_GATE pins hold |
| 187 | `evidence/qwen9b/g3/187_seq_model_selftest_committed.log` | `ref/seq_model.py --selftest` — the W8 MVGO and repack goldens PASS at `isa=1` |
| 188 | `evidence/qwen9b/g3/188_cite_drift_verify_committed.log` | `--verify`: 95, the classification in §11.2 |
| 189 | `evidence/qwen9b/g3/189_cite_drift_range_control_committed.log` | `--range-control`: **PASS**, 0 problems |
| 190 | `evidence/qwen9b/g3/190_cite_drift_doccites_verify_committed.log` | `--doc-cites --verify`: 11, the classification in §11.2 |
| 191 | `evidence/qwen9b/g3/191_cite_drift_negctl_check_committed.log` | `--check --negative-control`: **CAUGHT** (405) |
| 192 | `evidence/qwen9b/g3/192_cite_drift_negctl_verify_committed.log` | `--verify --negative-control`: **CAUGHT** (199) |
| 193 | `evidence/qwen9b/g3/193_spec_cites_committed.log` | `spec_cites.py` over the gate doc, the spec, the plan, `docs/SEQ_ISA.md` and both earlier G3 gate docs — **PASS, FAIL 0** (2082 exist, 1124 range, 67 quote, 195 noquote, pending 11, retired 18) |
| 194 | `evidence/qwen9b/g3/194_spec_cites_selftest_committed.log` | `spec_cites.py --selftest` with the plan's path — **PASS**, 6/6 negative controls CAUGHT |
| 195 | `evidence/qwen9b/g3/195_spec_cites_regression_committed.log` | `evidence/qwen9b/g2/spec_cites_selftest_regression.sh` — **PASS**, every pinned count unmoved |
| 196 | `evidence/qwen9b/g3/196_cite_drift_check_committed.log` | `--check` for the record.  It stays RED by construction: its sweep is taken from the doc-base, so it reports 199 drifted / 68 unresolved / 4 half-mapped — the same class it
reported before the fix, plus the three citations this task's own gate doc,
its noquote markers and its boxed notes newly created.  `--verify` (188) is its green half |

**`pending 11`** in log 193 is the `spec_cites.PENDING` set after this task
removed two rows from it: `evidence/qwen9b/g3/G3_2_VECNORM.md`, left behind
when Task 8 landed it, and `evidence/qwen9b/g3/G3_3_MATVEC.md`, this
document.  PENDING is checked BEFORE EXIST, so a landed file left in it
would let a typo in its path — or its deletion — pass silently on every
document that cites it.

---

## 14. FIX ROUND 1 (2026-09-02) — review findings I1-I3 closed

Three Important findings, two of them live-board safety.  The RTL, the SHAPE
repack, the lockstep proof and the W4-identity evidence were independently
reproduced by the reviewer and are unchanged by this round.

### 14.1 I1 — `tb_streamer_engine` no longer elaborated

`tb/tb_streamer_engine.sv` is a **second instantiator of `matvec_engine`**
and §1's sweep was scoped to EDITED files, so it was missed.  It still passed
`.cfg_g64(1'b0), .cfg_w8(1'b0)` to ports that no longer exist
(`%Error-PINNOTFOUND` ×2), with a 6-bit `cfg_ng` and an 11-bit `x_waddr`
behind that.  The target is live at `tb/Makefile:212-224`, 4 seeds.

| site | was | now |
|---|---|---|
| `tb/tb_streamer_engine.sv:79` the instantiation | `.cfg_g64(1'b0), .cfg_w8(1'b0)` | both dropped |  <!--cites:noquote-->
| `tb/tb_streamer_engine.sv:67-68` | `logic [5:0] cfg_ng, cfg_sh;` | `[6:0] cfg_ng;` + `[5:0] cfg_sh;` |  <!--cites:noquote-->
| `tb/tb_streamer_engine.sv:72` `x_waddr` | 11 b | **12 b**, and the `11'(i)` cast at `tb/tb_streamer_engine.sv:204` with it |
| `tb/tb_streamer_engine.sv:194` `cfg_ng = 6'(NG[5:0])` | 6 b | `7'(NG[6:0])` |  <!--cites:noquote-->
| `tb/tb_streamer_engine.sv:27` `MAXX` | 1024 | **3072**, so the TB can hold a 9B x window |
| `tb/Makefile:13` `.PHONY` | absent | `tb_streamer_engine` added |
| `docs/ARCHITECTURE.md:769` | listed it among the live matvec TBs (true only once it builds again) | the row now also records that it is the SECOND instantiator and moved with the engine |

**GREEN:** `TB_STREAMER_ENGINE PASS` on 4 seeds
(`evidence/qwen9b/g3/200_tb_suite_fix1.log:616,620,624,628`), K =
1024/3584/256/2048 bit-exact.

### 14.2 The sweep I1 asked for — ALL of `tb/` and `rtl/`, not only edited files

Every instantiation of `matvec_engine` / `matvec_chan`, and every surviving
reference to the deleted signals or the old widths.  `synth/out_*` is
excluded: those are gitignored, frozen netlists of SHIPPED builds, not
migration sites.

| site | what | disposition |
|---|---|---|
| `rtl/matvec_chan.sv:431` | `matvec_engine u_engine` | already moved (§4) |
| `tb/tb_matvec.sv:81` | `matvec_engine dut` | already moved |
| `tb/mvshim_b_stubs.sv:34` | the stub `module matvec_engine` | already moved |
| **`tb/tb_streamer_engine.sv:72`** | `matvec_engine u_engine` | **BROKEN — fixed here** |
| `rtl/matvec_chan_ipi.v:149`, `tb/tb_matvec_chan.sv:41`, `tb/tb_mvshim_b.sv:95`, `tb/tb_seq_chip.sv:336` | `matvec_chan` instances | **no change needed** — `matvec_chan`'s PORT LIST is unchanged; only its internals moved.  `matvec_chan_ipi` is lint-clean in `lint_mvshim_b` |
| `rtl/layer_chan.sv:2491,1763,1771-1772,1908-1910` `wbeats` | an AXI burst-beat counter | **UNRELATED NAME COLLISION** — no change |
| `tb/seq_stub_mvchan.sv:126,179,218,241` `wbeats` | the MV_BEATS CSR shadow | **UNRELATED NAME COLLISION** — no change |
| `tb/Makefile:801`, `tb/scripts/gen_seq_unit_vectors.py:915,749,967`, `tb/scripts/gen_chat_i1_vectors.py:247` | the string "1536" | **accurate as written** — a 1536-word MOVX case and the rope-table stride, neither an XWIN ceiling |  <!--cites:noquote-->
| `tb/scripts/layer_s*.txt`, `tb/scripts/token_s*.txt`, `tb/vec_s1/beats.hex`, `tb/rsqrt_cases_s4.txt`, `rtl/roms/*.hex` | "1536"/"5800" inside HEX VECTOR DATA | **not code** — no change |

**Result: `cfg_g64`, `cfg_w8`, `w8_phase` and a 6-bit `cfg_ng` / 11-bit
`x_waddr` / 11-bit `xptr` appear NOWHERE in tracked `rtl/` or `tb/` any
more** — the only live hits were the four `tb/tb_streamer_engine.sv` lines above.

### 14.3 I2 — an unknown VERSION now REFUSES, and every caller gates on it

The round-1 `shape_isa_for_version` **defaulted** to `isa=2`, and its
docstring justified that with a caller-side version gate that
`sw/layer_test.py` and `sw/tok_meter.py` do not have.  The reviewer's
demonstration is now an ASSERTION in `_selftest_shape_word`:
`shape_word(2048, 5, 8)` = `0x02020005`, which `build_034` decodes as
`ng=5 nrows=8224 sh=0` where the caller meant `ng=8 nrows=2048 sh=5`.

| change | site |
|---|---|
| the map names BOTH images explicitly — `0x4F908DF2 build_034`, `0x54443B9F build_035`, both `isa=1`; hashes taken from `sw/seq_run.py:124`, `sw/seq_run.py:130` and `sw/infer.py:98` | `sw/hwmap.py:96-105` |
| **no default**: an unmapped VERSION raises `UnknownBitstream` | `sw/hwmap.py:108-134` |
| `sw/infer.py` resolves the ISA INSIDE the identity gate, so `--expect-version 0x4f908df2` can no longer pass the gate and then pack `isa=2` | `sw/infer.py:159-172`, `sw/infer.py:121` |
| `sw/layer_test.py`, `sw/tok_meter.py`, `sw/matvec_test.py` gate in the same block as MAGIC/CALIB, converting the refusal to a `REFUSING TO TOUCH THE BOARD` exit | `sw/layer_test.py:86-96`, `sw/tok_meter.py:211-221`, `sw/matvec_test.py:84-95` |
| selftest: both known versions map to `isa=1`, an unknown one must RAISE, and the two decodes of `0x02020005` are asserted | `sw/hwmap.py:857-873` |
| **folded minor**: `shape_word` refuses `ng` outside `1..MAX_NG` per layout (`{1: 48, 2: 96}`), with a selftest case each side, because the engine's own envelope guard is `` `ifndef SYNTHESIS `` | `sw/hwmap.py:85`, `sw/hwmap.py:147-149` |  <!--cites:noquote-->

§7 is **re-derived from the post-fix code**, tool by tool, valid / refuses /
pre-G3 checkout — including the row the round-1 table over-claimed.

### 14.4 I3 — the fourth producer, and the "one packer" contract mechanized

`sw/matvec_test.py:110` (pre-fix) hand-rolled `(args.N << 12) | (sh << 6) | ng` — a  <!--cites:noquote-->
live board tool (the stage-2 charter acceptance test), unversioned, and
invisible to every check in §5.3.  It now delegates:
`shape_word(args.N, int(sh), ng, isa=shape_isa)`
(`sw/matvec_test.py:123-124`) behind the VERSION gate above, and it joins §7.

**And the contract is now checked, not just stated.**
`isa_bits.py --shape` gained `check_shape_producers`: it walks `sw/*.py`,
finds every `wr(… R_SHAPE …)` and requires the statement to name
`shape_word` and an `isa=`.

```
  infer.py:243   R_SHAPE write -> shape_word
  layer_test.py:132   R_SHAPE write -> shape_word
  matvec_test.py:123   R_SHAPE write -> shape_word
  tok_meter.py:398   R_SHAPE write -> shape_word
  4 live R_SHAPE producer(s) in sw/, all through the one packer: yes
```

Its control: reverting `sw/matvec_test.py` to the hand-rolled line reports
`matvec_test.py:123   R_SHAPE write -> HAND-ROLLED  (NO isa= ARGUMENT)` and
`SHAPE_BITS: FAIL`.

### 14.5 The sweep I3 asked for — every other SHAPE producer or decoder

`/usr/bin/grep` over `sw/`, `ref/`, `tb/` and every runnable script under
`evidence/` for `R_SHAPE`, `<< 12) |`, `<< 6) |`, `<< 22) |`, and `shape`
near `wr(`.

| hit | kind | disposition |
|---|---|---|
| `sw/infer.py:244`, `sw/layer_test.py:132`, `sw/tok_meter.py:428` | producers | already delegating (§5.2) |
| **`sw/matvec_test.py:123`** | producer | **hand-rolled — fixed here** |
| **`evidence/qwen2b/rd/rd_census.py:95`** `shape = dev.rd(b + HW.R_SHAPE)` | READER, runnable evidence script | **LAYOUT-AGNOSTIC, no change** — it prints the raw 32-bit word and decodes no field.  It is where `RD_GATE.md:238`'s pinned literals came from, which is why they are layout-independent evidence |
| `ref/seq_format.py:1882`, `ref/seq_format.py:2023` | stream producers | already delegating |
| `ref/seq_format.py:870-881` disasm, `ref/seq_model.py:921-956` `_mvgo` | decoders | already versioned/moved (§5.3) |
| `sw/hwmap.py:156`, `sw/hwmap.py:169`, `sw/hwmap.py:827`, `sw/hwmap.py:812` | the packer itself and its selftest | **the one packer** |
| `ref/gen_layer_script.py:919`, `tb/scripts/gen_seq_layer_script.py:161` | `(nlog2 << 2) \| (inf << 6) \| (outf << 10)` | **the VN COMMAND word, not SHAPE** — no change |
| `ref/calib_stats.py`, `ref/gptq.py`, `ref/layer_fixed.py`, `ref/perplexity_eval.py`, `ref/load_qwen35.py`, `ref/seq_chat.py` | `ndarray.shape` | **not the CSR** — no change |
| `evidence/qwen2b/q2/v4_v5/W8_SKETCH.md:108`, `evidence/qwen2b/rb/seq_isa_ref_sweep.txt:62,70` | PROSE quoting the pre-G3 word | already `<!--cites:noquote-->` under a dated note (§11.1) |

**No other hand-rolled SHAPE producer or decoder survives.**

### 14.6 One more, found while fixing: a gate that did not run

`sw/hwmap.py`'s selftest docstring was re-pointed in round 1 from the
retired `tb_matvec_w8` to `tb_matvec_chan` — but the *invocation* was never
wired there, so the docstring named a gate that did not exist.
`tb/Makefile:247-252` now runs `$(VECPY) ../sw/hwmap.py` inside
`tb_matvec_chan`, and log `200` carries its `HWMAP SHAPE_WORD SELFTEST PASS`
line at `evidence/qwen9b/g3/200_tb_suite_fix1.log:439`.

### 14.7 The fix-round evidence

| # | log | result |
|---|---|---|
| 200 | `evidence/qwen9b/g3/200_tb_suite_fix1.log` | the six targets **plus `tb_streamer_engine`**, snoke, 4 seeds — **rc 0, 61 PASS/OK markers** (56 + 4 `TB_STREAMER_ENGINE` + the hwmap selftest) |
| 201 | `evidence/qwen9b/g3/201_boardfree_fix1.log` | the board-free gate — **BOARDFREE_PASS, 2758 / 85 / 356**, unmoved |
| 210-219 | see §14.8 | the fix-round gate evidence on the COMMITTED tree |

The full six were re-run rather than a subset: `tb/Makefile` changed (the
`.PHONY` list and the `tb_matvec_chan` recipe) and `sw/hwmap.py` is now
executed by `tb_matvec_chan`, so every matvec target's recipe or environment
moved even though `rtl/` did not.

### 14.8 The fix round, re-run on a COMMITTED tree

Committed tree **`626c744`** — every header reads `=== tree: 626c744` with no
`+dirty` flag.

| # | log | result |
|---|---|---|
| 210 | `evidence/qwen9b/g3/210_tb_suite_fix1_committed.log` | the six targets **+ `tb_streamer_engine`**, snoke, 4 seeds — **rc 0, 61 PASS/OK markers**; `TB_STREAMER_ENGINE PASS` ×4 and `HWMAP SHAPE_WORD SELFTEST PASS` inside `tb_matvec_chan` |
| 211 | `evidence/qwen9b/g3/211_boardfree_fix1_committed.log` | **BOARDFREE_PASS, 2758 / 85 / 356** — unmoved by four `sw/` edits |
| 212 | `evidence/qwen9b/g3/212_isa_bits_shape_fix1.log` | **SHAPE_BITS: PASS** — the six implementations **plus the new 4-of-4 producer check** |
| 213 | `evidence/qwen9b/g3/213_isa_bits_shape_control_fix1.log` | **SHAPE_CONTROL: PASS** — 5 of 5 refused |
| 214 | `evidence/qwen9b/g3/214_isa_bits_arg_fix1.log` | the G3.1 ARG gate — **ISA_BITS: PASS** |
| 215 | `evidence/qwen9b/g3/215_hwmap_selftest_fix1.log` | `sw/hwmap.py --selftest` — the RD_GATE pins, the envelope refusals **and the unknown-VERSION refusal** |
| 216 | `evidence/qwen9b/g3/216_seq_model_selftest_fix1.log` | `ref/seq_model.py --selftest` — the W8 goldens still PASS at `isa=1` |
| 217 | `evidence/qwen9b/g3/217_cite_drift_check_fix1.log` | `--check`, RED by construction (base-relative sweep): 199 / 68 / 4 |
| 218 | `evidence/qwen9b/g3/218_cite_drift_verify_fix1.log` | `--verify`: **95 — the SAME count and the same classification as §11.2**, unchanged by this round |
| 219 | `evidence/qwen9b/g3/219_cite_drift_range_control_fix1.log` | `--range-control`: **PASS**, 0 problems |
| 220 | `evidence/qwen9b/g3/220_cite_drift_doccites_verify_fix1.log` | `--doc-cites --verify`: **11**, the §11.2 classification |
| 221 / 222 | `evidence/qwen9b/g3/221_cite_drift_negctl_check_fix1.log`, `evidence/qwen9b/g3/222_cite_drift_negctl_verify_fix1.log` | both negative controls **CAUGHT** (405 / 199) |
| 223 | `evidence/qwen9b/g3/223_spec_cites_fix1.log` | `spec_cites.py` over the gate doc, the spec, the plan, `docs/SEQ_ISA.md`, `G3_1_ISA.md`, `G3_2_VECNORM.md` — **PASS, FAIL 0** (2203 exist, 1190 range, 68 quote, 201 noquote) |
| 224 | `evidence/qwen9b/g3/224_spec_cites_selftest_fix1.log` | `--selftest` with the plan's path — **PASS**, 6/6 CAUGHT |
| 225 | `evidence/qwen9b/g3/225_spec_cites_regression_fix1.log` | **PASS**, every pinned count unmoved (27 / 8 / 0 / 0 / 3 / 2 / 0 / 0) |

**THE LESSON FROM ROUND 1 WAS APPLIED.**  §11.2 recorded that the boxed notes
must precede `--fix`; this round's incremental drift was therefore closed in
ONE pass with `--base d2d8b64 --doc-base d2d8b64` (the round-1 committed
state → the worktree), which is the question this round actually asks:
**111 citations in 29 documents**, `--verify` residual **3**, all of them the
`sw/hwmap.py:88-96` half-mapped range in this very document, which was
hand-repaired to `sw/hwmap.py:118-134` (`shape_isa_for_version`'s new home).
`evidence/qwen9b/o3/o3_cite_drift.py` was reverted again for the reason §11
gives.

## 15. What is NOT established by this gate

* **Timing.**  This wall re-opens the block that owned `build_034`'s worst
  22 endpoints and that `build_035` closed at exactly WNS 0.000 with zero
  margin.  Nothing here is synthesized.  **G5 owns it**, and the floorplan
  study (§6.2 S10) is what decides whether the re-opened block closes.
* **The LUT saving is E, not M, here.**  −5,826 CLB LUTs and −497 CARRY8 per
  channel, ×4 = −23,304 device-wide, is the STUDY's out-of-context
  measurement of `build_034` vs `build_035`
  (`evidence/qwen2b/rc/TIMING_035.md` §8a), carried as an **E**stimate of
  what this strip returns.  **Task 12 measures it** on this RTL; nothing was
  re-synthesized here, and the number must not be quoted as measured for
  this tree.
* **`p_acc`'s headroom at ng = 96 is D, not M.**  7 spare bits is
  arithmetic; no vector in this suite drives `p_acc` to its bound, because
  the DIRECTED max-magnitude case was a W8 vector and went with the W8 mode
  (§2).  Task 12 checks the accumulator rather than arguing it.
* **The 9B row shapes are SYNTHETIC.**  `q1`/`q2`/`q3` are random Gaussian
  matrices through the real quantizer at K = 4096/8192/12288 — the right
  GEOMETRY, not real `down_proj` weights.  The real-artifact replay is G4.
* **Nothing about `rtl/layer_chan.sv`.**  Task 10 owns the `cfg_ng`
  envelope check on that side and consumes `MAX_NG = 96` from here.
* **No board.**  `build_035` is serving the 2B on the BCU-1525 throughout;
  no `sw/pcie_helper.sh`, no JTAG, no DMA, no `sw/` tool pointed at
  `/dev/xdma0*`.  The three CSR-writing tools were exercised through
  `--selftest` paths and the board-free gate only.
