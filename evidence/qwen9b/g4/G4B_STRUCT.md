# G4b — the OOC structure gates on the SHIPPING RTL, `p_acc` headroom, and the layer-term cycle census

*Task 12 of the Qwen3.5-9B migration. Two independent measurements that both
had to happen before a build cycle is spent, plus a decision package the
controller routed here from Task 11.*

**Read `§0` for the verdict, `§1` for what was measured on what, `§2` for the
OOC structure numbers (Step 1), `§3` for `p_acc` (Step 2), `§4` for the gate-port
clamp decision package (Step 2, extended), `§5` for the cycle census (Step 3),
`§8` for what this gate does NOT establish.**

---

## 0. Verdict

| # | claim | verdict |
|---|---|---|
| 1 | `layer_chan` at the 9B geometry infers **exactly 928 URAM288** on the SHIPPING `rtl/` | **PASS** — 928, split 696 DN + 232 KV, DN non-URAM cells **0** |
| 2 | `DN_PIPE = 2` costs **flip-flops and nothing else** | **PASS on FF and URAM, QUALIFIED on LUT** — FF **+24,645**, URAM **0**; LUT **+381**, and **every LUT of it is attributed** (§2.3, §2.3a, §2.3b): +256 to `attn_core`'s score memory, which **Track P's own `DN_PIPE 0 → 2` pair proves is not a pipelining cost** (distributed RAM 344 → 344), +5 to the DN delay line (Track P: the identical +5), and +120 to a `(layer_chan)` +12,477 / `u_dn` −12,272 re-attribution across the `dn_step` boundary |
| 3 | BRAM lands where §4.3 costs it | **MEASURED BELOW THE MODEL** — `layer_chan` **690.0 tiles (T)**; device **858.0 of 2,160 (39.7 %)** by substitution (**S**) against the model's **886.5 (41.0 %)** (**D**) |
| 4 | the four-`matvec_chan` LUT delta | **MEASURED: −4,903 per channel, −19,612 device-wide** vs build_035's W8 engine; the direction is DOWN and the two moves are separated (§2.5) |
| 5 | `p_acc` fits its 48-bit container on the real 9B stream | **PASS** — observed max **422,300,890 = 29 magnitude bits of 48, 18 spare**; the two MODELLED figures (41 of 48, ≈45 of 48) are worst-case bounds the stream never approaches (§3) |
| 6 | the layer term, MEASURED | **46.079 ms/token**, the mean over all six forward steps in the shipping configuration, against the modelled **47.00 (E)** — **0.980×**, 2.0 % below. Step 1 46.027, step 6 46.132: the whole `T` dependence of this prompt is **0.227 %** (§5.4, §5.4a) |
| 6a | A1.6's *"≈ +10 %"* for the pass-2 wait state | **REFUTED BY MEASUREMENT — it is +0.86 %** of the layer term (98,304 cyc/token). §10's band should be **restored to 6.98 – 7.47** and A1.6's re-anchor to ≈ 6.5 – 7.0 **retired** (§5.5); accepted by the controller and recorded as plan amendment **A3** |
| 7 | the gate-port clamp decision package | **DELIVERED, §4** — three parts, measured numbers with labels, **no recommendation** |
| 8 | `rtl/` is byte-identical to the tree Task 11 gated | **PASS** — `git diff f81902b -- rtl/` is empty (§1.3) |

---

## 1. Provenance and the operating point

### 1.1 The tree, and what this task changed

`rtl/`, `tb/`, `ref/`, `sw/` and `docs/` are **untouched**. Everything this task
adds is under `evidence/qwen9b/g4/` plus the one file the brief names,
`synth/scripts/ooc_9b.tcl`.

### 1.2 Operating point

`FABLE5_MODEL=9b`, `FABLE5_RS_F=7`, int16 DN state, `DN_PIPE = 2` with the
pass-2 wait state shipped — the same point Task 11 replayed the whole model at.

### 1.3 The `DN_P2WAIT` knob — the permitted `rtl/` change was built and REVERTED

The brief permits *"a one-line exposure of `DN_P2WAIT` as a parameter if the
census cannot flip it otherwise"*. It was built (commit `8ea8121`), it worked,
and it was **reverted** (`7b763d7`), because the census **can** flip it
otherwise and the exposure is not free.

**What it costs, measured with the campaign's own tool:**

```
python3 evidence/qwen9b/o3/o3_cite_drift.py --base f81902b \
        --edited rtl/layer_chan.sv --plan
  TOTAL      REPAIR 221  COLLATERAL 7
  O3_FIX_PLAN: UNSAFE — 7 of 228 rewrites would move a citation that is
  already correct; repair the 221 stale one(s) BY HAND or --exclude the document
```

221 citations across 20 documents, with 7 collateral rewrites inside two OTHER
gates' committed evidence (`evidence/qwen9b/g3/G3_4_LAYER.md` 6,
`evidence/qwen_next/place_exp/PLACE_EXP.md` 1). Inserting a parameter into
`layer_chan`'s port list moves every line below it, and
`rtl/layer_chan.sv` is the
most-cited source file in the campaign.

**The two cheaper routes were TESTED, not assumed:**

* Verilator's `-G` reaches the **top module only**, and `DN_P2WAIT` is a
  `layer_chan` localparam (`rtl/layer_chan.sv:337`), not a port parameter.
* `defparam dut.u_dn.P2_WAIT = 0;` is refused:
  `%Error-UNSUPPORTED: Unsupported: defparam with more than one dot`
  (Verilator 5.020).

**So option (ii) is built from a SCRATCH COPY of `rtl/layer_chan.sv`** with that one
localparam forced to 0. `evidence/qwen9b/g4/run_g4b_census.sh` makes the copy,
**prints the diff**, and **refuses** unless the diff is exactly the one
substitution; it also **refuses to run at all if `rtl/` is dirty**, because
every census number is claimed against HEAD's RTL. The TB reads `DN_RLAT` and
`DN_P2WAIT` **out of the DUT** for its header line, so the census names the
value the elaboration actually used rather than restating a parameter.

`rtl/` is therefore byte-identical to `f81902b`:

```
$ git diff f81902b --stat -- rtl/     # empty
```

### 1.4 Files this task adds

| file | what it is |
|---|---|
| `synth/scripts/ooc_9b.tcl` | the OOC harness for the SHIPPING `rtl/` (the brief's named file) |
| `evidence/qwen9b/g4/run_g4b_ooc.sh` | its launcher, one out dir per run |
| `evidence/qwen9b/g4/collect_g4b_ooc.sh` | carries the report sections out of the gitignored `synth/out_*`, flat AND hierarchical |
| `evidence/qwen9b/g4/ooc_dnpipe_attrib.tcl` + `run_g4b_attrib.sh` | the cell-by-cell attribution of the `DN_PIPE` LUT move |
| `evidence/qwen9b/g4/tb_layer_census.sv` | the census TB — `tb_layer_chan`'s replay loop plus the LCYC read |
| `evidence/qwen9b/g4/run_g4b_census.sh` | builds and runs one census configuration |
| `evidence/qwen9b/g4/g4b_pacc_probe.py` | `p_acc` over the real 9B stream, through the reference executor |
| `evidence/qwen9b/g4/pacc_probe.sv` + `run_g4b_pacc_sim.sh` | `p_acc` in Verilator, `bind`-ed into every `matvec_engine` |
| `evidence/qwen9b/g4/g4b_gate_clamp_package.py` | the decision package's table, joined from two committed logs |

---

## 2. STEP 1 — out-of-context synthesis on the SHIPPING `rtl/`

### 2.1 Method

`synth/scripts/ooc_9b.tcl`, Vivado **2024.2** on snoke, part
**`xcvu9p-fsgd2104-2L-e`**, `synth_design -mode out_of_context`, one 4.000 ns
clock on `aclk` (the 250 MHz `xdma_0_axi_aclk` domain every shipped bitstream
runs `layer_0` and the four mvchans in). One fresh `synth/out_ooc9b_<tag>/` per
run, never reused.

**It is COUNT ONLY, deliberately.** No `opt_design`, no `place_design`: a
structure number must not be confused with a timing number, and the timing half
is Task 13's. Track P already PLACED the equivalent wide geometry
(`evidence/qwen_next/place_exp/PLACE_EXP.md`).

**Not Track P's script.** `synth/exp_uram/scripts/exp_ooc.tcl` reads
`synth/exp_uram/rtl/` — experiment copies that were never functionally
verified — and takes the geometry from `-tclargs`. `synth/scripts/ooc_9b.tcl`
reads the real
`rtl/` and takes the geometry **from the RTL**: at G3.4 `LNH`/`N_DN`/`N_KV`/
`NKVH`/`CVD` became localparams (`rtl/layer_chan.sv:361-365`), so there is
nothing left to pass and nothing that can silently disagree with what the
testbenches replayed.

**Runs** (out dirs are gitignored; the report sections are committed here as
`ooc_<tag>_summary.log` and `ooc_<tag>_util_synth.rpt`, the whole 12 KB
utilization report each — an earlier campaign truncated one and then cited a row
past the cut, `PLACE_EXP.md` §6; not repeated):

| tag | top | override | out dir | synth wall |
|---|---|---|---|---|
| `layer_p2` | `layer_chan` | none (the RTL's own `DN_PIPE = 2`) | `synth/out_ooc9b_layer_p2` | **1,054 s** |
| `layer_p0` | `layer_chan` | `DN_PIPE = 0` — the CONTROL, not a shippable configuration | `synth/out_ooc9b_layer_p0` | **1,070 s** |
| `mvchan` | `matvec_chan` | none | `synth/out_ooc9b_mvchan` | **179 s** |
| `sequnit` | `seq_unit` | none | `synth/out_ooc9b_sequnit` | **156 s** |

All four ran on snoke, launched within six seconds of each other at
`2026-09-03T15:27:34-06:00` .. `15:27:40`, tree `f81902b9`
with **2 dirty files** — `synth/scripts/ooc_9b.tcl` and
`evidence/qwen9b/g4/run_g4b_ooc.sh`, this task's own harness, untracked at
launch and committed as `bcfa511` minutes later. **Nothing under `rtl/` was
dirty**, which is what the numbers are about. Declared here rather than left
in the header for a reader to wonder about.

### 2.2 THE STOP CONDITION — URAM 928 — **PASS**

**T**, `ooc_layer_p2_summary.log`:

```
OOC9B_URAM: 928
OOC9B_URAM_PREDICT: 928 (24 DN x 29 + 8 KV x 29)
OOC9B_URAM_MATCH: YES
OOC9B_DN_NONURAM_CELLS: 0
OOC9B_URAM_SPLIT: dn=696 kv=232 other=0
```

| quantity | model (**D**, feasibility §2.7 / spec §2) | Track P, **placed** (`PLACE_EXP.md` §3.1) | **this build, T** |
|---|---|---|---|
| DN state URAM288 | 24 banks × 29 = 696 | — | **696** |
| KV cache URAM288 | 8 banks × 29 = 232 | — | **232** |
| **total** | **928** | **928** | **928** |
| DN cells NOT in URAM | 0 | 0 | **0** |

The study's arithmetic is exactly right on the shipping RTL, the split is right
and not just the total, and **no DN bank fell out of URAM**. 928 of 960 is
**96.67 %** of the device's URAM. Track P placed the same count at the same
geometry, so the count half of the brief's stop condition closes with two
independent confirmations.

### 2.3 What `DN_PIPE = 2` costs — FF and URAM **PASS**, LUT **QUALIFIED**

**T**, both `evidence/qwen9b/g4/ooc_layer_p0_util_synth.rpt` and
`evidence/qwen9b/g4/ooc_layer_p2_util_synth.rpt`. Both runs are the SAME RTL, the same
tool, the same part; the only difference is the `-generic DN_PIPE`.

| row | `DN_PIPE = 0` (control) | `DN_PIPE = 2` (**ships**) | Δ | brief expects |
|---|---|---|---|---|
| **CLB LUTs** | 109,986 | **110,367** | **+381 (+0.35 %)** | unchanged |
| — LUT as Logic | 109,608 | 109,728 | +120 | |
| — LUT as Distributed RAM | 344 | 600 | **+256** | |
| — LUT as Shift Register | 34 | 39 | **+5** | |
| **CLB Registers** | 54,433 | **79,078** | **+24,645** | **≈ +24.7 K** ✅ |
| CARRY8 | 7,827 | 7,834 | +7 | |
| Block RAM Tile | 690.5 | 690.0 | −0.5 | |
| — RAMB36 / RAMB18 | 674 / 33 | 674 / **32** | 0 / **−1** | |
| **URAM288** | 928 | **928** | **0** | **unchanged** ✅ |
| DSPs | 1,837 | 1,836 | −1 | |

**FF: `+24,645`, which is `1.042 %` of the device's 2,364,480** — the brief's
`≈ +24.7 K, ≈ 1 %` measured. Track P's own delta at the same `N` was
**+24,672** (54,276 → 78,948, `PLACE_EXP.md` §3.7 and its committed
`evidence/qwen_next/place_exp/v2wide_util_synth.rpt` /
`evidence/qwen_next/place_exp/r2widepipe2_util_synth.rpt`). The two builds are
different trees
— G3.4's `layer_chan` carries the DNSB CSR, TCNT2, the S9 envelope and a
65,536-word scratchpad that Track P's experiment copy never had — and they
agree to **27 flip-flops, 0.11 %**. **URAM is unchanged at 928 in both.**

**The LUT move is +381, and it is ATTRIBUTED rather than waved past** (log
`069_dnpipe_attrib.log`, `ooc_dnpipe_attrib.tcl` over both post-synth
checkpoints):

```
ATTRIB P0 PAT *sc_mem* RAMB18E2 1
ATTRIB P2 RAMS64E1 total 256
ATTRIB P2 PAT *sc_mem* RAMS64E1 256
ATTRIB P2 PAT *g_dnpipeN* SRL16E 5
ATTRIB P2 PAT *g_dnpipeN* FDRE 26838
```

* **+256 of the +381 is `attn_core`'s score memory, `u_attn/sc_mem`, changing
  implementation.** At `DN_PIPE = 0` it is **1 RAMB18E2**; at `DN_PIPE = 2` it
  is **256 RAMS64E1**, and the arithmetic says it is the same array either way:
  `rtl/attn_core.sv:69` declares `logic signed [31:0] sc_mem [512]` = 16,384 b,  <!--cites:noquote-->
  and 256 × 64 b = 16,384 b.

  > **CLASS B, dated note 2026-09-10.** That quotation is of the tree this
  > census ran on and **the source no longer exists**: the state-spill's S2
  > (A1.5) widened the score memory and everything that indexes it from 512
  > to 4,096, so the declaration now reads
  > `(* ram_style = "block" *) logic signed [31:0] sc_mem [4096];` at
  > `rtl/attn_core.sv:77`. The pre-S2 line number and text are kept as the
  > record of what was measured, per the spec's own rule that an exemption
  > is for source that no longer exists; the +256 RAMS64E1 / 16,384 b
  > arithmetic above is a G4b measurement of the pre-S2 array and is not
  > re-derived here.
  That is also the entire RAMB18 33 → 32 move. `DN_PIPE` does not touch
  `attn_core` — this is Vivado picking a different memory implementation, and
  it is the kind of nudge a 25 K-FF change makes to a whole-module inference
  pass.
* **+5 is the DN pipeline itself** — `g_dnpipeN.dn_bsel_d_reg[*]_srl2/_srl4`,
  the `DN_SDEL = 2·DN_PIPE + 1` bank-select delay line mapped to SRL16E.
  **Track P's LUT-as-Memory delta was 378 → 383, the SAME +5.**
* **+120 is LUT as Logic**, against Track P's +29 — and it is closed
  instance by instance in §2.3a below rather than left as a residual.
* The DSP −1 is one multiplier in `u_dn` (1,280 → 1,279) that fell to LUTs.

#### 2.3a Track P's own `DN_PIPE 0 → 2` pair — the cross-check that settles it

The reports were committed beside the ones §2.3 already cites and the
comparison was not made in the first cut of this gate. It is decisive:

| LUT class | Track P `v2wide` (N=0) | Track P `r2widepipe2` (N=2) | Δ | this build, N=0 → N=2 |
|---|---|---|---|---|
| LUT as **Distributed RAM** | **344** (`evidence/qwen_next/place_exp/v2wide_util_synth.rpt:41`) | **344** (`evidence/qwen_next/place_exp/r2widepipe2_util_synth.rpt:41`) | **0** | 344 → 600, **+256** |
| LUT as Shift Register | 34 | 39 | **+5** | 34 → 39, **+5** |
| CLB Registers | 54,276 | 78,948 | +24,672 | +24,645 |
| URAM288 | 928 | 928 | 0 | 0 |

**Track P's `DN_PIPE 0 → 2` moves distributed RAM by ZERO, from the same 344
this build's `DN_PIPE = 0` reports.** So distributed RAM is *provably not* a
cost of the pipelining, and the +256 has to come from somewhere the pipelining
does not reach. It does: `rtl/attn_core.sv:69` declares
`logic signed [31:0] sc_mem [512]` with **no `ram_style` attribute**, and
`rtl/layer_chan.sv:802` instantiates `attn_core` with `EXP2_ROM` and
`RECIP_ROM` only — **no `DN_PIPE`-derived parameter reaches it at all**. It is
the tool re-inferring an unconstrained memory under a heavier netlist.

The SRL delay line moves by **+5 in both builds**, the FF cost agrees to
0.11 %, and URAM is 928 in both. **On every quantity that identifies the
pipelining, this build is Track P's build.**

#### 2.3b The +120 Logic-LUT residual, closed with the hierarchical report

`synth/scripts/ooc_9b.tcl:144` has always written
`report_utilization -hierarchical`; the first cut of this gate did not carry
it. Both are committed now
(`evidence/qwen9b/g4/ooc_layer_p0_util_synth_hier.rpt`,
`evidence/qwen9b/g4/ooc_layer_p2_util_synth_hier.rpt`), and the ten direct
children's `Logic LUTs` deltas **sum to exactly +120**:

| instance | module | P0 Logic LUTs | P2 Logic LUTs | **Δ** | Δ LUTRAM | Δ SRL | Δ FF |
|---|---|---|---|---|---|---|---|
| `(layer_chan)` | top-level glue | 4,694 | 17,171 | **+12,477** | 0 | **+5** | **+24,702** |
| `u_dn` | `dn_step` | 51,651 | 39,379 | **−12,272** | 0 | 0 | −74 |
| `u_rope` | `rope_unit` | 390 | 282 | −108 | 0 | 0 | 0 |
| `u_vn` | `vecnorm_unit` | 2,690 | 2,783 | +93 | 0 | 0 | 0 |
| `u_alu` | `vec_alu` | 4,958 | 4,881 | −77 | 0 | 0 | 0 |
| `u_attn` | `attn_core` | 43,142 | 43,118 | −24 | **+256** | 0 | +17 |
| `u_gate` | `gate_unit` | 973 | 996 | +23 | 0 | 0 | 0 |
| `u_topk` | `layer_topk32` | 533 | 538 | +5 | 0 | 0 | 0 |
| `u_axib` | `layer_axib_shim` | 271 | 275 | +4 | 0 | 0 | 0 |
| `u_conv` | `conv4_silu` | 306 | 305 | −1 | 0 | 0 | 0 |
| **total** | | **109,608** | **109,728** | **+120** | **+256** | **+5** | **+24,645** |

**Nothing is unattributed.** The +120 is the residual of two large opposing
moves in the DN path — `(layer_chan)` **+12,477** against `u_dn` **−12,272**,
netting **+205** — plus **−85** spread over seven blocks with no single move
above 108 LUTs.

**And the two large moves are re-attribution, not logic appearing and
disappearing.** `dn_step`'s own source differs between the two builds in
exactly two parameters: `RLAT` 2 → 6, which widens one counter
(`rtl/dn_step.sv:127-134` `PRE_W`), and `P2_WAIT` 0 → 1, which adds one FSM
state (`rtl/dn_step.sv:291`). Neither can account for 12 K LUTs. What the FF
column shows is the mechanism: **the pipeline's 24,702 new flip-flops are ALL
at the top level** — in `g_grp` / `g_dnpipeN`, where the RTL puts them —
and `u_dn` *loses* 74, so the 2048-bit DN read/write cone is simply attributed
to whichever side of the `dn_step` boundary it optimizes into. **This gate
states that as the reading of the measurement and not as a separate claim**;
the measurement itself is the table, and the table closes.

*(This also retires minor 7: a top-N cell census like
`evidence/qwen9b/g4/ooc_dnpipe_attrib.tcl` could never have found this,
because an instance whose count FALLS never appears in a top-N list.)*

**Verdict, and the judgement is stated rather than buried.** The brief makes a
LUT or URAM move a STOP on the reasoning that it *"means the pipelining was not
built the way Track P built it"*. The measurement says the pipelining **was**
built the way Track P built it: the FF delta agrees to 0.11 %, the bank-select
SRL line is the same +5, and URAM is identically 928 with zero DN cells outside
it. The residual LUT movement is **0.35 % of 110 K**, two thirds of it in a
module `DN_PIPE` does not touch. **This gate does not treat that as the stop
condition firing** — and says so here so a reviewer can disagree with the
judgement without having to re-derive the numbers.

### 2.4 BRAM — MEASURED BELOW THE MODEL

**T**, `ooc_layer_p2_summary.log` / `ooc_*_util_synth.rpt`:

```
OOC9B_BRAM: RAMB36=674 RAMB18=32 tiles=690.0
OOC9B_BRAM_SPLIT: scratch=62 conv=600
```

| block | 035, OOC (**T**, `evidence/qwen_next/place_exp/ref_build035_layer0_ooc_utilization_synth.rpt`) | 9B, OOC (**T**, here) |
|---|---|---|
| `layer_chan` | 395 RAMB36 + 27 RAMB18 = **408.5 tiles** | 674 + 32 = **690.0 tiles** |
| `matvec_chan` (×4) | 4 tiles each (`evidence/qwen2b/rc/TIMING_035.md` §8a) | **4 tiles each** — Δ **0** |
| `seq_unit` | no committed OOC twin | **0 tiles** |

**Device total, label S** — *this document's own arithmetic* on measured ends,
substituting `layer_chan` and the four `matvec_chan`s into build_035's device
figure (561 RAMB36 + 31 RAMB18 = 576.5 tiles, `TIMING_035.md` §8b). It is **S
and not D**: no committed script computes it, and the gate that MEASURES it is
a device build, which §8 item 2 says has not happened:

```
576.5 − 408.5 + 690.0 + 4 × (4 − 4) = 858.0 tiles = 39.72 % of 2,160
```

against the model's **886.5 tiles = 41.0 %** (**D**, spec §4.3 row A, from
feasibility §2.7's `f08` — that one IS D, a committed script computes it).
**The measurement lands 28.5 tiles — 3.2 % — BELOW the model.** The model is
conservative here; it is not re-fitted.

**Caveat on the substitution, stated because it is load-bearing:** `seq_unit`
changed at G3.2/G3.3 and has **no committed pre-9B OOC twin**, so the
substitution carries it as unchanged. Its 9B BRAM is measured at **0 tiles**,
so the only way this figure moves is if 035's `seq_unit` had BRAM — which
would make the device total *lower* still, never higher.

**The scratch array**, which §4.3 costs at "+28 RAMB36 over today": the
65,536-word `smem_a` + `smem_b` pair is measured at **62 RAMB36** (**T**,
`OOC9B_BRAM_SPLIT`). The 24 conv banks at 8,192 deep are **600 RAMB36**. This
gate does **not** claim a measured `+28`, because no build of the 32,768-word
array exists to difference against — the device substitution above is the
measured statement, and it is a whole-module delta, not a per-array one.

### 2.5 The four `matvec_chan` LUT delta — the measurement's OUTPUT

The brief is explicit that the **net direction is unknown and is this
measurement's output**: the block grows for `MAX_NG = 96` and shrinks for the
W8 strip at the same time. Both reference points are committed OOC numbers from
the same tool (`evidence/qwen2b/rc/TIMING_035.md` §8a, log
`evidence/qwen2b/rc/t5_07_ooc_synth_utilization.log`), so the two moves can be
separated.

| row | **034 (W4)** T | **035 (W8)** T | **9B** T | 9B − 035 | 9B − 034 |
|---|---|---|---|---|---|
| **CLB LUTs** | 14,023 | **19,849** | **14,946** | **−4,903 (−24.70 %)** | **+923 (+6.58 %)** |
| — LUT as Logic | 10,318 | 16,143 | 9,958 | −6,185 | −360 |
| — LUT as Distributed RAM | 3,698 | 3,698 | 4,980 | **+1,282** | **+1,282** |
| — LUT as Shift Register | 7 | 8 | 8 | 0 | +1 |
| **CARRY8** | 772 | **1,269** | **773** | **−496** | **+1** |
| CLB Registers | 10,590 | 11,924 | 14,108 | +2,184 | +3,518 |
| F7 / F8 Muxes | 887 / 272 | 964 / 296 | 1,072 / 496 | +108 / +200 | +185 / +224 |
| Block RAM Tile | 4 | 4 | **4** | **0** | **0** |
| DSPs | 2 | 2 | **2** | **0** | **0** |

**Read it against §5.1.**

* §5.1 prices the W8 strip at **−5,826 LUTs per channel, ×4 = −23,304
  device-wide**, *"all of it `LUT as Logic` + `CARRY8`"*.
* The **measured net** for the shipping 9B channel against the same W8
  baseline is **−4,903 per channel = −19,612 device-wide**.
* The difference, **+923 per channel = +3,692 device-wide**, is what the
  9B block costs against build_034's **W4** engine — the same weight format,
  so the W8 strip is not in that comparison at all. It is **+1,282 LUT as
  Distributed RAM** offset by **−360 LUT as Logic**: the `MAX_NG = 96` widening
  landing in memory, not logic.
* **`CARRY8` −496 against §5.1's predicted −497** — the W8 adder tree, gone,
  one cell off the prediction.
* **BRAM 0 and DSP 0**, exactly as §5.1 said and now measured at the 9B point
  too.

**Net direction: DOWN.** `−19,612` LUTs device-wide from the four channels,
which is §5.1's `−23,304` minus `+3,692` of `MAX_NG = 96` growth.

### 2.6 `seq_unit`, for the record

**T**, `ooc_sequnit_summary.log`: LUT **3,849** (logic 3,637, memory 212),
FF **2,580**, CARRY8 **185**, BRAM **0**, DSP **0**. There is **no committed
pre-9B `seq_unit` OOC** to difference against, so this is an absolute number
Task 13 can use as its own baseline, not a delta.

### 2.7 Device-wide, by substitution — label **S**

Substituting the measured `layer_chan` and the four measured `matvec_chan`s
into build_035's device figures (`TIMING_035.md` §8b). Everything outside those
five instances is carried unchanged, which `seq_unit` is **not** (§2.4's
caveat) — so these are the **model this task hands to G5a**, not measurements
of a device. **Label S** throughout: the ENDS are T, the substitution is this
document's arithmetic, and no committed script performs it.

| resource | 035 device (**T**) | 9B device (**S**, substitution) | of the part |
|---|---|---|---|
| CLB LUTs | 299,076 | **291,336** | 24.6 % of 1,182,240 |
| CLB Registers | 292,520 | **328,095** | 13.9 % of 2,364,480 |
| CARRY8 | 13,681 | **11,717** | 7.9 % of 147,780 |
| Block RAM Tile | 576.5 | **858.0** | **39.7 %** of 2,160 |
| **URAM288** | 348 | **928** | **96.7 %** of 960 |
| DSPs | 1,858 | **1,856** | 27.1 % of 6,840 |

**URAM at 96.7 % is the number G5a starts from, and it is the one the study
called its #1 risk.** It is a capacity fact, not a timing one; Task 13 owns the
timing.

---

## 3. STEP 2 — `p_acc` headroom, MEASURED

### 3.1 The three numbers, and which is which

`p_acc` is `rtl/matvec_engine.sv:561` `logic signed [47:0] p_acc`, the row
accumulator: accumulated at `rtl/matvec_engine.sv:675`, consumed by the single
`rshift_round` at R1/R2. **Three figures exist for it and only one is a
measurement.**

| # | figure | label | what it is |
|---|---|---|---|
| 1 | 96 × 65535 × 131072 = 824,621,137,920 → **40 magnitude bits + sign = 41 of 48, 7 spare** | **D** | the RTL header's own worst case, restated at G3.3 for `MAX_NG = 96` — `rtl/matvec_engine.sv:72-77` says `p_acc              MAX_NG * 65535 * 131072     48 b   UNCHANGED`. Every group at full magnitude simultaneously |
| 2 | **≈ 45 of 48 at `K = 12288`** (from *"44 b at K = 6144"*) | **D** | the STUDY's arithmetic, quoted by the Task 12 brief. It does not agree with figure 1, because it is arithmetic on an earlier form of the RTL note; both are worst-case bounds and neither is an occupancy |
| 3 | **`\|p_acc\|max = 422,300,890` → 29 magnitude bits + sign = 30 of 48, 18 spare** | **M** | **the real 9B stream** |

### 3.2 The measurement — the reference half, over the WHOLE 9B stream

`evidence/qwen9b/g4/g4b_pacc_probe.py`, log
`evidence/qwen9b/g4/066_pacc_observed_9b.log`, `rc: 0`, on snoke at
`FABLE5_MODEL=9b FABLE5_RS_F=7`.

It replays `tb/scripts/w9/model_9b_s1.e4` — all 158,483 records, all six
forward steps (`EMB: 6` in its own stats line), **8,220 MVGO records against
the weight images on disk** — through `ref/seq_model.SeqExec`, the
**same executor `tb/scripts/gen_seq_chip_vectors.py` uses to build the `.chip`
golden the RTL is checked against**, and spies on `w4a8_ref.rshift_round` for
the duration of each matvec. Spying rather than recomputing is deliberate: it
captures the accumulator the reference **actually formed**, so the probe
re-derives no arithmetic and cannot drift from `matvec_y32`.

**`p` in `ref/w4a8_ref.py`'s `matvec_y32` IS `p_acc`**: that function's
docstring states the RTL is built to its accumulate order and that *"no
intermediate truncation anywhere before `sh`"*, and G4a §5.3 replayed the whole
9B model through both bit-exactly.

**What the reference half does NOT see, stated because it bounds the claim.**
The spy fires on `ref/w4a8_ref.py:287` `y = rshift_round(p, sh)`, and the `p`
built one line earlier at `ref/w4a8_ref.py:286` is the **complete row
accumulator** — `(m * acc).sum(axis=1)`, every
group already summed. So §3.2's figure is the maximum of the **final**
accumulator, not of the running partial sums the RTL's `p_acc` register holds
between group beats. **It is therefore a LOWER bound on container occupancy.**
Two things make that immaterial here: the partial sums of a signed sum can
exceed the total, but not by more than the sum of the positive terms, and at
**18 spare magnitude bits** — a factor of 262,144 — no plausible partial
ordering reaches the rail; and **the sim half (§3.3) samples the register
itself on every clock**, so the intermediates ARE measured, on the 9B layer
smoke, at 28 bits against the reference's 29 on the model stream. A
whole-stream measurement of the intermediates would be §3.3's run on
`model_9b_s1.e4`, which deviation 8 says was not made.

```
PACC matvec calls          : 8220
PACC rows accumulated      : 10051584
PACC OBSERVED max |p_acc|  : 422300890
PACC OBSERVED magnitude bits: 29  ->  occupancy 29 + 1 sign = 30 of 48, headroom 18 of 47 magnitude bits
PACC worst matvec          : {'N': 2048, 'K': 4096, 'NG': 32, 'sh': 7, 'max_abs': 422300890}
PACC observed / RTL bound  : 5.121e-04
PACC VERDICT: FITS — 29 magnitude bits used, 18 of 47 spare
```

*The magnitude line above is quoted from the **re-run**,
`evidence/qwen9b/g4/082_pacc_observed_9b_r2.log`. The first run,
`evidence/qwen9b/g4/066_pacc_observed_9b.log:17`, printed
`29 of 48 (sign + 29, 18 spare)`, which reads as if the 29 already included
the sign bit — a wording defect in `g4b_pacc_probe.py`, not a number defect.
The script now prints the magnitude width, the occupancy and the headroom as
three separate quantities, and **the re-run reproduces every value bit for
bit**; 066 stays committed as the record of what the first cut said.*

**The container is 2,000× larger than the stream needs** — `observed / RTL
bound = 5.121e-04`. The worst row is a `2048 × 4096` matrix at `NG = 32`,
`sh = 7`; the widest matrices in the model (`K = 12288`, `NG = 96`) do **not**
produce the worst accumulator, because occupancy is driven by the activation
magnitudes and the per-group mantissas, not by `K` alone. That is exactly why
figures 1 and 2 are bounds and not predictions.

### 3.3 The measurement — the sim half

`evidence/qwen9b/g4/pacc_probe.sv`, `bind`-ed into **every** `matvec_engine`
instance, sampling `p_acc` on **every clock** (not only when written), so the
number is the largest magnitude the container ever holds — intermediate group
sums included. The probe drives nothing, and the run still checks the `.chip`
golden, so a probe that perturbed anything would fail the replay rather than
print a quiet number.

**M**, `evidence/qwen9b/g4/068_pacc_sim_lay9b.log`, 183 s, `rc: 0`, last
verdict line `TB_SEQ_CHIP PASS`:

| channel | samples | `max \|p_acc\|` | magnitude bits |
|---|---|---|---|
| 0 | 4,538,698 | 191,209,018 | 28 |
| 1 | 4,538,698 | 183,404,473 | 28 |
| 2 | 4,538,698 | 210,555,160 | 28 |
| 3 | 4,538,698 | 175,769,574 | 28 |

**This rung is the 9B LAYER SMOKE — random weights, one DN + one GQA layer** —
so it bounds that stream and not the model. It is here because it is the half
that runs on the RTL: it shows the `bind` reaches the real register in the
shipping engine, and that the occupancy the RTL forms is the same order as
the reference's (28 bits against 29).

**The whole-stream RTL run was NOT made, and the reason is cost against
value.** `evidence/qwen9b/g4/run_g4b_pacc_sim.sh` takes the full
`model_9b_s1.e4` unchanged, but that replay is **2 h 44 min** (**M**, G4a
§5.3.1 measured it) and it would confirm a number §3.2 already has over the
**same stream** — from a reference that G4a §5.3 replayed against this RTL
bit-exactly at four seeds. The harness is committed; anyone who wants the
number can have it for one afternoon of wall clock. Declared as deviation 8.

### 3.4 `ref/audit_ranges.py` at 9B

The brief asks for the audit "at 9B". **It has already been run at 9B and is
committed**: `evidence/qwen9b/g1/12_audit_ranges_9b.log` and
`evidence/qwen9b/g1/audit_ranges_9b_report.md` (G1(d), Track Q's committed
script under `runpy` with `find_checkpoint` patched to the full shard list).
It is **not re-run here**, and the reason is that it would answer a different
question than the brief wants: the audit is **weights-only by construction**
and says so — its §5 defers *"y32 matvec accumulator occupancy"* to a runtime
audit precisely because *"the achieved occupancy needs real activations"*.
What it does establish, and this gate uses:

* the frozen `sh` comes from the worst-case bound `NG*65535*(G*8*127)` — the
  same expression figure 1 above evaluates;
* *"the real mantissas peak at 16384, so up to **5.6 bits** of the int32
  accumulator are discarded by the pre-output shift"* (**T**, its §2). That is
  the weights-side half of why the measured occupancy is so far under the
  bound.

Two caveats on citing it, stated rather than glossed: it ran at
`FABLE5_RS_F` **unset (= 8)** and with **no GPTQ Hessian**, i.e. not at this
build's operating point. `RS_F` does not reach the quantizer (spec §0b measured
that with `--wq-cache-verify`), so the `sh` / mantissa rows carry over; the
residual-stream rows do not, and this gate does not use them. **The occupancy
number this gate reports is §3.2's, which was measured at the operating point.**

### 3.5 Verdict

**`p_acc` fits, with 18 of 47 magnitude bits spare on the real 9B stream.**
Neither modelled bound is contradicted — both are worst cases and the stream
does not approach either. Nothing here asks for an RTL change, and this gate
proposes none.

---

## 4. STEP 2, EXTENDED — the gate-port clamp DECISION PACKAGE

> **This section makes no recommendation.** It answers the three questions the
> controller routed here from Task 11's concern 2, with measured numbers and
> their labels, and stops.

Background, in one paragraph. `ref/layer_fixed.quant_deltanet`
(`ref/layer_fixed.py:1455-1490`) quantizes DeltaNet's two gate scalars and then
**saturates** them into the `rtl/gate_unit.sv` ports as built —
`dtv[15:0]` signed (`dt_bias` Q3.12, ±8.0) and `Av[17:0]` unsigned
(`A` Q3.15, [0, 8.0)) — at `ref/layer_fixed.py:1462-1463`, with the limits at
`ref/layer_fixed.py:805-806`. G4a's runtime range audit priced that clamp for
the first time at 9B and handed the decision here.

### 4.1 (a) Was the clamp inside the G1/A2 fidelity loop? — **YES**

**It was, and the 98/108 already prices it.** The call chain, by line:

```
ref/fidelity_check.py:394   layers.append(LF.quant_layer(wf, res_scale=..., ...))
ref/layer_fixed.py:1649       qw["dn"] = quant_deltanet(wf["dn"], ...)
ref/layer_fixed.py:1462-1463    dt_q = np.clip(dt_spec, DT_Q12_MIN, DT_Q12_MAX)
                                A_q  = np.clip(A_spec,  0, A_Q15_MAX)
ref/fidelity_check.py:430   x = LF.layer_decode_fx(x, qw, self.caches[i], t)
```

`evidence/qwen9b/g1/run_g1_point.sh` runs `ref/fidelity_check.py` for **every**
rung of the G1 ladder, and A2's `RS_F = 7` point is the same script at the same
geometry (spec §0b). So **every ladder number in this campaign — 95/108 at
`RS_F = 8`, 98/108 at `RS_F = 7`, and every int8 rung that was rejected — was
measured with the clamp ALREADY APPLIED.**

**What that does and does not mean.** It means the fidelity the user ratified
is the **clamped** model's fidelity: nothing is hiding behind the clamp that
the ladder did not already pay. It does **not** mean the clamp is free — it
means its cost is *inside* 98/108 rather than *on top of* it, and no
measurement anywhere says what 98/108 would be without it. Removing the clamp
is an **un-measured upside**, not a known one.

Cross-check that the probe and the production quantizer agree, so this is not
an argument from code reading: `evidence/qwen9b/g1/11_gate_port_probe_9b.log`
runs `qd["gate_sat"]` from `quant_deltanet` on DN layer 0 beside the probe's own
expressions and reports
`probe expressions == qd['gate_sat'] on layer 0: IDENTICAL  (10 vs 10 saturating heads)`.

### 4.2 (b) The 61 pairs, with the excess and which parameter carries it

**Two INDEPENDENT measurements name the SAME 61 pairs** —
`evidence/qwen9b/g1/11_gate_port_probe_9b.log` (weights only, off the
checkpoint) and `evidence/qwen9b/g4/003_emit_9b_s1.log` (runtime, inside the
emitter, at this prompt's own `a` values). `g4b_gate_clamp_package.py` joins
them and checks the sets rather than assuming; log
`evidence/qwen9b/g4/067_gate_clamp_package.log`, `rc: 0`:

```
GATECLAMP g1 pairs (weights-only, G1 log 11) : 61
GATECLAMP g4 pairs (runtime, G4a log 003)    : 61
GATECLAMP SETS IDENTICAL — the same (layer, head) pairs from two independent measurements
GATECLAMP carried by A only : 49
GATECLAMP carried by dt only: 12
GATECLAMP carried by both   : 0
GATECLAMP total             : 61
GATECLAMP worst runtime cost: L12h18 22430/32768 = 68.45% FS (spec 1779 -> clamped 24209), carried by A
GATECLAMP largest A excess  : L12h18 A_q15 2522996 vs the 18-bit ceiling 262143 = 9.62x  (A = 76.9957 vs the port's 8.0)
GATECLAMP largest dt excess : L0h4 dt_q12 75776 vs the int16 rail [-32768,32767] = 2.31x  (dt = 18.5000 vs the port's +/-8.0)
GATECLAMP wrap (no clamp)   : worst |decay_wrap - decay_spec| = 30221/32768 at L26h11 — what SATURATION buys
```

**Summary of the 61, label M:**

| which port | pairs | of 768 (24 DN layers × 32 heads) | largest excess |
|---|---|---|---|
| **`A` (`Av[17:0]`, unsigned Q3.15, [0, 8.0))** | **49** | 6.38 % | **9.62×** the port — `L12h18`, `A = 76.9957` |
| **`dt_bias` (`dtv[15:0]`, signed Q3.12, ±8.0)** | **12** | 1.56 % | **2.31×** the port — `L0h4`, `dt = 18.5000` |
| both at once | **0** | — | — |
| **total** | **61** | **7.94 %** | |

**The 61, listed.** `A` spec is `exp(A_log)` against a port that reaches 8.0;
`dt` spec is `dt_bias` against a port that reaches ±8.0; the `×port` columns
are the SPEC value over its port ceiling (1.00 = exactly at the rail); the
runtime columns are this prompt's worst evaluation of the six.

| layer | head | port over | `A` spec | `A_q15` spec | ×port | `dt` spec | `dt_q12` spec | ×port | runtime \|Δdecay\| | % FS | at `a` |
|---|---|---|---|---|---|---|---|---|---|---|---|
| L0 | h1 | **dt** | 0.0796 | 2607 | 0.01 | 12.500 | 51200 | 1.56 | **7942**/32768 | **24.24** | -5.557 |
| L0 | h4 | **dt** | 0.0564 | 1849 | 0.01 | 18.500 | 75776 | 2.31 | **9634**/32768 | **29.40** | -0.575 |
| L0 | h12 | **dt** | 0.0902 | 2954 | 0.01 | 15.438 | 63232 | 1.93 | **14028**/32768 | **42.81** | -7.718 |
| L0 | h13 | **dt** | 0.0930 | 3048 | 0.01 | 14.750 | 60416 | 1.84 | **13258**/32768 | **40.46** | -7.717 |
| L0 | h20 | **dt** | 0.1332 | 4366 | 0.02 | 13.625 | 55808 | 1.70 | **10354**/32768 | **31.60** | -4.196 |
| L0 | h21 | **dt** | 0.1429 | 4684 | 0.02 | 11.875 | 48640 | 1.48 | **7665**/32768 | **23.39** | -3.855 |
| L0 | h24 | **dt** | 0.0547 | 1792 | 0.01 | 9.375 | 38400 | 1.17 | **1978**/32768 | **6.04** | -5.883 |
| L0 | h25 | **dt** | 0.0564 | 1849 | 0.01 | 9.312 | 38144 | 1.16 | **1927**/32768 | **5.88** | -5.188 |
| L0 | h30 | **dt** | 0.1105 | 3619 | 0.01 | 13.125 | 53760 | 1.64 | **11537**/32768 | **35.21** | -6.717 |
| L0 | h31 | **dt** | 0.1122 | 3676 | 0.01 | 12.125 | 49664 | 1.52 | **9854**/32768 | **30.07** | -7.009 |
| L1 | h2 | **A** | 32.0966 | 1051741 | 4.01 | -2.797 | -11456 | 0.35 | **14974**/32768 | **45.70** | 0.260 |
| L1 | h9 | **dt** | 0.2000 | 6554 | 0.03 | -8.688 | -35584 | 1.09 | **32**/32768 | **0.10** | 3.386 |
| L1 | h11 | **A** | 20.4018 | 668527 | 2.55 | -2.438 | -9984 | 0.30 | **9575**/32768 | **29.22** | -0.696 |
| L1 | h17 | **A** | 40.5739 | 1329526 | 5.07 | -3.016 | -12352 | 0.38 | **17253**/32768 | **52.65** | 0.282 |
| L1 | h19 | **A** | 18.2881 | 599264 | 2.29 | -3.844 | -15744 | 0.48 | **9427**/32768 | **28.77** | 1.101 |
| L1 | h24 | **A** | 11.0923 | 363472 | 1.39 | -2.422 | -9920 | 0.30 | **3910**/32768 | **11.93** | 0.144 |
| L1 | h28 | **A** | 9.9431 | 325814 | 1.24 | -4.344 | -17792 | 0.54 | **2616**/32768 | **7.98** | 2.210 |
| L2 | h0 | **A** | 23.8522 | 781588 | 2.98 | -4.188 | -17152 | 0.52 | **12546**/32768 | **38.29** | 1.525 |
| L2 | h1 | **A** | 27.8860 | 913769 | 3.49 | -4.156 | -17024 | 0.52 | **13960**/32768 | **42.60** | 1.240 |
| L2 | h5 | **A** | 54.5982 | 1789072 | 6.82 | -4.469 | -18304 | 0.56 | **20107**/32768 | **61.36** | 1.324 |
| L2 | h11 | **A** | 9.4877 | 310894 | 1.19 | -2.891 | -11840 | 0.36 | **2035**/32768 | **6.21** | 0.635 |
| L2 | h12 | **A** | 34.1666 | 1119573 | 4.27 | -4.312 | -17664 | 0.54 | **16091**/32768 | **49.11** | 1.484 |
| L2 | h16 | **A** | 27.4537 | 899602 | 3.43 | -4.938 | -20224 | 0.62 | **13310**/32768 | **40.62** | 1.853 |
| L2 | h17 | **A** | 13.1724 | 431634 | 1.65 | -2.844 | -11648 | 0.36 | **5642**/32768 | **17.22** | 0.883 |
| L2 | h20 | **A** | 13.8046 | 452348 | 1.73 | -3.375 | -13824 | 0.42 | **6416**/32768 | **19.58** | 1.222 |
| L2 | h21 | **A** | 16.3933 | 537177 | 2.05 | -3.750 | -15360 | 0.47 | **8466**/32768 | **25.84** | 1.324 |
| L2 | h24 | **A** | 43.8708 | 1437560 | 5.48 | -4.500 | -18432 | 0.56 | **16171**/32768 | **49.35** | 0.861 |
| L2 | h26 | **A** | 9.9431 | 325814 | 1.24 | -4.344 | -17792 | 0.54 | **1794**/32768 | **5.47** | 1.156 |
| L2 | h31 | **A** | 70.1054 | 2297214 | 8.76 | -4.438 | -18176 | 0.55 | **21492**/32768 | **65.59** | 1.350 |
| L4 | h1 | **A** | 14.0220 | 459472 | 1.75 | -2.875 | -11776 | 0.36 | **6624**/32768 | **20.21** | 0.410 |
| L4 | h7 | **A** | 8.1153 | 265922 | 1.01 | -4.188 | -17152 | 0.52 | **143**/32768 | **0.44** | 1.451 |
| L4 | h18 | **A** | 11.0923 | 363472 | 1.39 | -2.703 | -11072 | 0.34 | **3909**/32768 | **11.93** | 0.421 |
| L4 | h20 | **A** | 14.6949 | 481522 | 1.84 | -3.266 | -13376 | 0.41 | **7216**/32768 | **22.02** | 0.880 |
| L4 | h22 | **A** | 20.0855 | 658163 | 2.51 | -4.250 | -17408 | 0.53 | **9249**/32768 | **28.23** | 1.079 |
| L4 | h24 | **A** | 8.6387 | 283072 | 1.08 | -3.422 | -14016 | 0.43 | **870**/32768 | **2.66** | 0.970 |
| L5 | h18 | **A** | 19.4676 | 637913 | 2.43 | -2.797 | -11456 | 0.35 | **10278**/32768 | **31.37** | 0.428 |
| L5 | h19 | **A** | 18.0046 | 589973 | 2.25 | -3.016 | -12352 | 0.38 | **9313**/32768 | **28.42** | 0.313 |
| L5 | h31 | **A** | 8.3729 | 274363 | 1.05 | -3.031 | -12416 | 0.38 | **548**/32768 | **1.67** | 0.918 |
| L6 | h2 | **A** | 8.1153 | 265922 | 1.01 | -4.094 | -16768 | 0.51 | **119**/32768 | **0.36** | 1.027 |
| L6 | h21 | **A** | 51.2902 | 1680678 | 6.41 | -2.672 | -10944 | 0.33 | **18613**/32768 | **56.80** | -0.082 |
| L6 | h26 | **A** | 17.4506 | 571822 | 2.18 | -5.438 | -22272 | 0.68 | **8655**/32768 | **26.41** | 3.331 |
| L8 | h4 | **A** | 8.6387 | 283072 | 1.08 | -4.000 | -16384 | 0.50 | **882**/32768 | **2.69** | 2.260 |
| L9 | h18 | **A** | 28.7712 | 942775 | 3.60 | -3.125 | -12800 | 0.39 | **14349**/32768 | **43.79** | 0.500 |
| L10 | h8 | **A** | 10.2587 | 336157 | 1.28 | -6.594 | -27008 | 0.82 | **1043**/32768 | **3.18** | 2.488 |
| L10 | h14 | **A** | 11.6246 | 380915 | 1.45 | -4.875 | -19968 | 0.61 | **3978**/32768 | **12.14** | 2.100 |
| L10 | h21 | **A** | 9.9431 | 325814 | 1.24 | -5.062 | -20736 | 0.63 | **2029**/32768 | **6.19** | 2.086 |
| L12 | h6 | **A** | 9.0533 | 296657 | 1.13 | -3.891 | -15936 | 0.49 | **1333**/32768 | **4.07** | 1.271 |
| L12 | h18 | **A** | 76.9957 | 2522996 | 9.62 | -3.656 | -14976 | 0.46 | **22430**/32768 | **68.45** | 0.400 |
| L13 | h21 | **A** | 14.0220 | 459472 | 1.75 | -5.781 | -23680 | 0.72 | **4720**/32768 | **14.40** | 2.450 |
| L13 | h22 | **A** | 10.4202 | 341450 | 1.30 | -4.406 | -18048 | 0.55 | **3002**/32768 | **9.16** | 2.586 |
| L13 | h28 | **A** | 12.9682 | 424942 | 1.62 | -4.219 | -17280 | 0.53 | **5617**/32768 | **17.14** | 1.685 |
| L14 | h4 | **A** | 8.9129 | 292058 | 1.11 | -5.094 | -20864 | 0.64 | **1294**/32768 | **3.95** | 3.133 |
| L14 | h5 | **A** | 39.9449 | 1308913 | 4.99 | -2.578 | -10560 | 0.32 | **17258**/32768 | **52.67** | -0.192 |
| L14 | h8 | **A** | 20.0855 | 658163 | 2.51 | -4.281 | -17536 | 0.54 | **6410**/32768 | **19.56** | 0.474 |
| L14 | h14 | **A** | 8.9129 | 292058 | 1.11 | -3.859 | -15808 | 0.48 | **1055**/32768 | **3.22** | 1.023 |
| L17 | h2 | **A** | 10.4202 | 341450 | 1.30 | -5.031 | -20608 | 0.63 | **2662**/32768 | **8.12** | 2.184 |
| L17 | h13 | **A** | 8.6387 | 283072 | 1.08 | -3.750 | -15360 | 0.47 | **758**/32768 | **2.31** | 0.954 |
| L17 | h18 | **A** | 20.4018 | 668527 | 2.55 | -5.531 | -22656 | 0.69 | **7224**/32768 | **22.05** | 1.871 |
| L17 | h27 | **A** | 10.4202 | 341450 | 1.30 | -5.406 | -22144 | 0.68 | **1708**/32768 | **5.21** | 1.834 |
| L18 | h3 | **A** | 10.9203 | 357837 | 1.37 | -5.281 | -21632 | 0.66 | **2424**/32768 | **7.40** | 1.956 |
| L26 | h11 | **dt** | 0.3122 | 10231 | 0.04 | 8.188 | 33536 | 1.02 | **877**/32768 | **2.68** | -6.126 |

**Worst runtime cost: `L12h18`, `|decay_clamp − decay_spec| = 22,430 / 32,768 =
68.45 % FS`**, at `a = +0.400`, spec decay `1779` → clamped `24209`, over 6
evaluations of this prompt. The table above is transcribed from
`evidence/qwen9b/g4/067_gate_clamp_package.log`, which is the committed source
for every one of its cells.

**One row is worth reading beside the others**: the same log's last line prices
what the ports as built would do **without** the clamp — the wrap `Mach.W_raw`'s
18-bit mask would perform — at **30,221 / 32,768** worst. Saturation is not free,
but it is 68 % FS instead of 92 % FS, and it keeps the decay curve monotone.

**A number correction, stated because Task 11's own report and its log
disagree.** The G4a report §5.2 said "62"; log `003_emit_9b_s1.log` contains
**61** `worst |decay_clamp` lines with **61** distinct `L<n>h<m>` labels, and
G1's independent probe reports `A out of uint18 Q15 BEFORE the clamp : 49 / 768`
plus `dt out of int16 Q12 BEFORE the clamp : 12 / 768` = **61**. **61 is the
number.**

### 4.3 (c) What "new ROM hex" would cost — STATED, NOT BUILT

`ref/gen_model_script.py`'s header and `ref/layer_fixed.py:784-804` both call
this future work. Here is what the work is, from the source, with nothing
built:

**Why the ports cannot simply be widened.** `ref/layer_fixed.py:789-798` states
the coupling and it is a ROM problem, not a wire problem:

* **`dt` at Q4.11** would need `a` at Q11 too, *"the RTL adds `av + dtv` with one
  shared binary point"* (`rtl/gate_unit.sv:106` `adt_q`, the 18-bit sum) — but
  the softplus PWL index is **hardwired to a Q12 `[-16,16)` abscissa**
  (`rtl/gate_unit.sv:83-89` `pwl_idx_lo`, whose clamp is the literal pair
  `rtl/gate_unit.sv:85-86` `18'sd65535` / `-18'sd65536` = `+/-16` in Q12, with
  the matching out-of-range branches at `rtl/gate_unit.sv:185-186`), so Q11
  operands would evaluate softplus at **half** the argument.
* **`A` at Q4.14** would **halve `g`**, because `g = -rshr(A*sp, 11)` has the
  shift **hardwired to 11 = 15 + 12 − 16** (`rtl/gate_unit.sv:5`, `:208`) and
  `exp_neg` consumes `g` as Q16 (`LOG2E_Q16` + the exp2 ROM). *"`sp` comes
  straight out of a ROM and decay goes straight to DNST, so there is no second
  lever to compensate with."*

**The port widths, as built** (`rtl/gate_unit.sv:49-52`):

```
logic signed [15:0] bv  [NH];
logic signed [15:0] av  [NH];
logic        [17:0] Av  [NH];   // UNSIGNED Q15 (A in (0,8))
logic signed [15:0] dtv [NH];
```

with the write port `w_data` at `signed [17:0]` (`rtl/gate_unit.sv:35`), which
is already 18 bits — so `A`'s transport is not the binding width; the **format**
is.

**The ROMs that would have to be regenerated** (`ref/gen_roms.py:31-36`, sizes
from `rtl/roms/`):

| ROM | shape | file | why it moves |
|---|---|---|---|
| `softplus_pair_rom.hex` | 256 × 34 b (128 pairs of the 257-entry table) | `rtl/roms/softplus_pair_rom.hex` | the PWL abscissa is Q12 `[-16,16)`; a new `dt` binary point re-tabulates it |
| `exp2_pair_rom.hex` | 256 × 36 b | `rtl/roms/exp2_pair_rom.hex` | `exp_neg` consumes `g` as Q16; a new `A` binary point re-tabulates it |
| (`rtl/roms/softplus_rom.hex` 257 x 17 b, `rtl/roms/exp2_rom.hex` 257 x 18 b) | | | the unpaired forms `ref/gen_roms.py` writes beside them |

**The files a change would have to move together**, from the citations above —
stated as a list, not a plan:

| file | what changes |
|---|---|
| `rtl/gate_unit.sv` | `Av` / `dtv` widths (`:49-52`), the `pwl_idx_lo` abscissa (`:83-89`) and its `±16<<12` branches, the hardwired `rshr(A*sp, 11)` (`:208`) |
| `ref/fixedpoint.py` | `softplus_q` / `exp_neg_q`, the tables `ref/gen_roms.py` writes from |
| `ref/gen_roms.py` | the two `pairs(...)` widths at `:35-36` |
| `rtl/roms/*.hex` | regenerated, and they are `$readmemh`'d by `layer_chan` — so every TB's ROM staging and `synth/scripts/ooc_9b.tcl`'s ROM assertion see them |
| `ref/layer_fixed.py` | `DT_Q12_MIN` / `DT_Q12_MAX` / `A_Q15_MAX` (`:805-806`) and the comment block `:784-804` that is the current record of the decision |
| `ref/gen_layer_script.py` | `Mach.W_raw` / `Mach.gate` — the `Ahi & 0x3` split that ships `A` as a lo16 + hi2 pair through the 16-bit scratchpad |
| `tb/vectors/gate_*` | the committed `tb_gate_unit` goldens |
| every committed artifact and golden | a ROM change is not bit-compatible with any frozen stream |

**What it would buy, and this is the part nobody has measured:** the 61 pairs
stop being clamped. **Nothing in this repo says what that is worth in top-1** —
§4.1 establishes that 98/108 was measured **with** the clamp, so the upside is
the un-measured difference between "clamped" and "exact", and the only way to
learn it is to build the wider ports and re-run the ladder.

**Cost of NOT deciding**, for completeness: nothing breaks. The clamp is what
ships today, it is bit-exact between `ref/` and the RTL (G4a §5.3 replayed the
whole model), and G4a §7's torch comparison shows this prompt's six tokens are
unaffected. The exposure is that a different prompt exercises one of the 61
heads harder than this one did.

---

## 5. STEP 3 — the layer-term cycle census

> **This is the section the brief calls "the study's own cheap closure": the
> layer term is 33.9 % of the modelled step and it *"has no measurement"*. It
> has one now.**

### 5.1 What was censused, and why the comparison is like-for-like

**The instrument.** `evidence/qwen9b/g4/tb_layer_census.sv` is
`tb/tb_layer_chan.sv`'s replay loop with one addition: it reads the **LCYC**
CSR (`rtl/layer_chan.sv:28` `0x34 LCYC  R  cycles elapsed while busy==1`,
implemented at `rtl/layer_chan.sv:475` and `rtl/layer_chan.sv:904`) after
**every** command. The engine is idle between commands by construction — the
TB polls STATUS to retire one before dispatching the next — so consecutive
readings differ by exactly that command's busy cycles and the differences
**partition the engine's whole busy time with nothing unattributed**. The TB
asserts LCYC reads 0 out of reset, so cycle 0 of the census is the engine's
first busy cycle.

**Every census is also a replay.** Every `R` / `E` / `A` record is still
compared bit-exactly, exactly as `tb_layer_chan` does. All three runs report
**`10,093 cmds, 1,433,339 checks bit-exact, 0 errors`** — identical in all
three, which is itself the statement that the two non-shipped configurations
are functionally correct at the layer level and not only in `tb_dn_step`.

**The comparison is like-for-like, and this is the load-bearing fact.** The
model's *"layer 47.00 ms"* **is the LCYC accumulator**:
`evidence/qwen2b/rd/RD_GATE.md` reports **"layer busy (LCYC) 22,692,603 cyc =
15.128 ms/token"** at 0.8B and **"26,940,149 cyc = 17.960 ms/token"** at 2B,
on silicon, and `evidence/qwen_next/feas/toks_model.py` fits its layer term to
exactly those two points — *"same L_LCYC accumulator, same board, same
bitstream"*. This census sums the **same CSR** on the **same engine** at the
**same 250 MHz**. What differs is the platform: Verilator, not the board.

**The stream: the ONE-TOKEN slice, per the controller's ruling.**
`tb/scripts/w9/model_9b_s1.txt` is the layer-command form of Task 11's 9B
artifact set — the real weights, the real GPTQ quantization, `RS_F = 7`.
`+stopm=2` stops the replay just before the SECOND `M` record, so the census
covers the preamble plus **forward step 1**. Measured contents of that step,
from the stream itself:

| | step 0 (preamble) | **step 1 (one token)** |
|---|---|---|
| `L` layer-select records | 32 | **32** — all 32 transformer layers |
| commands | 888 | **9,205** |
| `DNST` (op 8) | 0 | **768 = 24 DN layers × 32 heads** |
| `DNZ` (op 12) | 768 | **0** |
| `CONVW` (op 5) | 120 | **0** |
| `ATTN` (op 10) | 0 | **128** |
| `ALU` (op 11) | 0 | **6,219** |

**768 DNST per token is exactly the population the brief names**, measured on
the artifact rather than assumed.

**And step 1 is the step at the SHORTEST KV cache**, which matters for two of
the ten opcodes and is stated here rather than left for a reader to infer.
`rtl/attn_core.sv:37` takes `cfg_t` — *"cache length T"*, bounded at
`rtl/attn_core.sv:13` by the contract line's `T` ceiling (*"T <= 512"* when
this was measured; S2 widened it to *"T <= 4096"*) — and its inner loop runs over the
cache, so `ATTN` and `KVAP` are the two opcodes whose cost **grows with
sequence position**. Measured on the artifact: the stream's **eight `T`
records all carry the value 0** and all lie in the preamble (lines
98,432–787,456, before the first `M` at line 787,457), so every KV append
counter enters forward step 1 at **T = 0**; step 1's 32 `KVAP` commands take
it to 1 and its 128 `ATTN` commands therefore run at **T = 1**. The census
confirms it from the other side: step 1's `ATTN` reports
**`min == max == 1,860`** — every one of the 128 ran at the same cache length
— where the same binary on the two-token layer smoke reported `min 1,860,
max 1,901`. §5.4a measures what the growth actually costs across all six
steps. **The preamble is exactly 120 `CONVW` +
768 `DNZ` = 888 commands** — the once-per-launch conv-weight/state load and
the DeltaNet state zeroing, and nothing else. It is **reported separately and
is not part of the layer term**, which is the right cut: neither opcode
appears in the token at all.

### 5.2 The three runs

All on snoke, `tree: 7b763d7` (clean), one obj_dir each. They differ in **one
localparam and nothing else** — same stream, same host, same tree, same TB
source (§1.3).

| cfg | `DN_PIPE` | `DN_RLAT` | `DN_P2WAIT` | what it is | log | wall |
|---|---|---|---|---|---|---|
| `shipped` | 2 | 6 | **1** | **option (i) — what ships** | `evidence/qwen9b/g4/070_census_shipped.log` | 925 s |
| `optii` | 2 | 6 | **0** | option (ii), the two-outstanding form | `evidence/qwen9b/g4/071_census_optii.log` | 891 s |
| `pipe0` | **0** | 2 | 0 | the unpipelined control (**not shippable** — Track P measured its read path at −1.848 ns) | `evidence/qwen9b/g4/072_census_pipe0.log` | 813 s |

The `DN_RLAT` / `DN_P2WAIT` values above are **read out of the DUT** by the
TB, not restated from a parameter, so the table names what each elaboration
actually used.

### 5.3 Cycles per DNST — MEASURED, beside both comparators

**T**, `evidence/qwen9b/g4/074_layer_term.log`:

| cfg | `DNST` commands | **cycles / DNST** | min | max |
|---|---|---|---|---|
| `shipped` (i) | 768 | **3,090** | 3,090 | 3,090 |
| `optii` (ii) | 768 | **2,962** | 2,962 | 2,962 |
| `pipe0` (control) | 768 | **2,958** | 2,958 | 2,958 |

**`min == max` in every configuration**: the DNST cost is exactly
data-independent over 768 commands spanning all 24 DN layers and all 32 heads
of a real token. That is the same property Task 10 measured across four vector
seeds, now measured across the real stream's whole head population.

**Against the RTL's own estimate.** `rtl/dn_step.sv:14` says
*"~10 cycles/row -> ~1300 cycles/head"*. The measured DNST **command** is
**3,090 cycles — 2.38× that estimate**. The two are not the same quantity and
the gap decomposes cleanly:

| | cycles | what it is |
|---|---|---|
| `rtl/dn_step.sv:14` estimate | ~1,300 | the recurrence's row loops, as designed |
| Task 10, `tb_dn_step` at RLAT 6 / `P2_WAIT` 1 (**T**, `evidence/qwen9b/g3/G3_4_LAYER.md` §4.3) | **1,930** | the `dn_step` FSM alone, start-pulse to `done` |
| **this census, the whole DNST command** | **3,090** | + the vector preload (k, q, v), the DNSB scalar reads, and the 256-word result collect |
| the difference | **1,160** | `layer_chan`'s wrapper around `dn_step` — **measured here for the first time** |

So the RTL header's `~1300` was never wrong about the loop; it was an estimate
of the loop, and the loop is 1,930 as Task 10 measured. **What this census
adds is that the command costs 60 % more than the recurrence** — and at 768
commands per token that wrapper is **890,880 cycles = 3.56 ms per token**,
7.7 % of the whole layer term.

**Against Task 10's isolated numbers, the deltas reproduce to the cycle:**

| | Task 10 (`tb_dn_step`, one head, no stream) | this census (per DNST command, real stream) |
|---|---|---|
| option (i) − control | 1,930 − 1,798 = **+132** | 3,090 − 2,958 = **+132** |
| option (ii) − control | 1,802 − 1,798 = **+4** | 2,962 − 2,958 = **+4** |

Two independent measurements, on different testbenches at different levels of
hierarchy, agree exactly. That is the strongest statement this gate can make
that the census is measuring what it says it is.

### 5.4 THE LAYER TERM — measured, beside the modelled 47.00 ms

**T**, `evidence/qwen9b/g4/074_layer_term.log`. One forward step = one token = all 32 layers:

| cfg | commands | **busy cycles / token** | **ms @ 250 MHz** | vs modelled 47.00 |
|---|---|---|---|---|
| **`shipped` (option (i), what ships)** | 9,205 | **11,506,810** | **46.027** | **0.979×** |
| `optii` (option (ii)) | 9,205 | **11,408,506** | **45.634** | 0.971× |
| `pipe0` (control) | 9,205 | **11,405,434** | **45.622** | 0.971× |

**The modelled layer term is 47.00 ms (E). The measured one, in the shipping
configuration, is 46.027 ms at forward step 1 and 46.079 ms as the mean over
all six steps (§5.4a) — 2.1 % and 2.0 % BELOW the model.**

The model is not re-fitted to this and does not need to be: for once, the
measurement lands inside the model rather than outside it. What the
measurement removes is the *uncertainty*, not the number — §10 lists the layer
coefficient as *"a fit intercept, not a measured cost"* whose *"head-indexed
term … is whatever is left after the width term explains 0.8B→2B"*. **It is a
measured cost now**, and the intercept it was fitted from happens to have been
right to 2 %.

**Where the layer term goes**, per token, shipped configuration (**T**, from
the census table):

| opcode | commands | cycles | ms | share |
|---|---|---|---|---|
| `ALU` (11) | 6,219 | 5,661,464 | 22.646 | 49.20 % |
| **`DNST` (8)** | **768** | **2,373,120** | **9.492** | **20.62 %** |
| `VN` (1) | 1,761 | 1,092,819 | 4.371 | 9.50 % |
| `CONV` (6) | 24 | 983,328 | 3.933 | 8.55 % |
| `VNW` (2) | 81 | 811,089 | 3.244 | 7.05 % |
| `ATTN` (10) | 128 | 238,080 | 0.952 | 2.07 % |
| `ROPE` (4) | 160 | 164,320 | 0.657 | 1.43 % |
| `KVAP` (9) | 32 | 147,950 | 0.592 | 1.29 % |
| `GATE` (7) | 24 | 31,560 | 0.126 | 0.27 % |
| `ROPET` (3) | 8 | 3,080 | 0.012 | 0.03 % |
| **total** | **9,205** | **11,506,810** | **46.027** | 100 % |

*Three notes on that table. The ten rows sum to **11,506,810 exactly** — the
LCYC deltas partition the engine's busy time with nothing left over, which is
the census's own consistency check. `ROPET` **is** per-token here: the stream
re-emits its 8 RoPE-table loads every forward step; `CONVW` and `DNZ` are the
two opcodes that are preamble-only. The share column is this gate's arithmetic
on the measured cycles, label **S**.*

**The DNST commands are 20.6 % of the layer term at 9B.** §10 item 5 says they
are *"12.8 % of the intercept"* at the model's calibration geometry; the
2.667× serial increase the study predicted (288 → 768 DNST/token) is exactly
what moves the share, and it is now measured rather than projected.

**`ALU` is the largest single term at 49.2 %** — bigger than DeltaNet. That is
a fact this gate surfaces and does **not** act on: nothing in the brief asks
for it and no optimization is proposed here.

### 5.4a The SIX-STEP census — the `T` dependence MEASURED, not bounded

§5.4's figure is forward step 1, at `T = 1`. The controller's fix-round-1
ruling required the whole stream for the shipped configuration so the
`ATTN`/`KVAP` growth is a measurement rather than a bound. It is:

**T**, `evidence/qwen9b/g4/081_census_shipped_6step.log`, `rc: 0`,
tree `290cac2` (clean), **4,694 s = 1 h 18 min** on snoke, `+stopm` omitted so
the replay runs to the stream's `Q`. Verdict line:
**`TB_LAYER_CENSUS PASS: 56118 cmds, 8600034 checks bit-exact`** — the whole
six-step stream, bit-exact, `errors=0`.

| forward step | KV cache `T` | commands | **busy cycles** | **ms @ 250 MHz** | vs step 1 |
|---|---|---|---|---|---|
| 1 | 1 | 9,205 | **11,506,810** | **46.027** | — |
| 2 | 2 | 9,205 | 11,511,950 | 46.048 | **+5,140** |
| 3 | 3 | 9,205 | 11,517,223 | 46.069 | +10,413 |
| 4 | 4 | 9,205 | 11,522,454 | 46.090 | +15,644 |
| 5 | 5 | 9,205 | 11,527,697 | 46.111 | +20,887 |
| 6 | 6 | 9,205 | **11,532,962** | **46.132** | **+26,152** |
| **mean 1..6** | | 9,205 | **11,519,849** | **46.079** | |
| preamble (step 0) | — | 888 | 2,655,096 | 10.620 | not per-token |

**Two cross-checks the table gives for free.** Step 1 reads
**11,506,810 cycles — identical, to the cycle, to the one-token run's step 1**
(§5.4), from a different binary in a different obj_dir (the two runs are
1 h 36 min apart on the same day, `evidence/qwen9b/g4/070_census_shipped.log`
at 16:15 and `evidence/qwen9b/g4/081_census_shipped_6step.log` at 17:52, on
different trees — `7b763d7` and `290cac2`); and
the six steps plus the preamble sum to **71,774,192**, which is the
`TOTAL_BUSY_CYCLES` the TB reports independently.

**The `T` dependence, measured.** Over six steps the layer term grows
**26,152 cycles = 0.105 ms = 0.227 %**, and it grows **linearly** — the
step-to-step deltas are 5,140 / 5,273 / 5,231 / 5,243 / 5,265, i.e. about
**5,230 cycles per token of context**. The census attributes it exactly where
`rtl/attn_core.sv:37` says it must be, and the attribution is ARITHMETIC
rather than impression. Every per-step opcode's command count in the six-step
census is exactly six times the one-token census's, so the two per-opcode
`total_cyc` columns can be differenced directly — six copies of
`evidence/qwen9b/g4/070_census_shipped.log` against
`evidence/qwen9b/g4/081_census_shipped_6step.log`:

| opcode | 6 × one-token | six-step | delta |
|---|---:|---:|---:|
| `ATTN` | 1,428,480 | 1,507,200 | **+78,720** |
| `KVAP` | 887,700 | 887,369 | **−331** |
| `ALU` | 33,968,784 | 33,968,631 | **−153** |
| every other opcode | | | **0, exactly** |
| **net** | | | **+78,236** |

and **+78,236 is the sum of the per-step deltas in the table above**
(5,140 + 10,413 + 15,644 + 20,887 + 26,152), so the growth is accounted for
to the cycle. `ATTN` is the whole of it: its per-command cost runs
`min 1,860 → max 2,065` across the six-step run (**+205 over five tokens ≈ 41
cycles per `T`**, × 128 ATTN/step ≈ 5,250) against a flat `1,860 → 1,860` at
`T = 1`. `KVAP` and `ALU` move by less than a part in 2,600 and in the WRONG
direction; both spreads are per-command properties present in the one-token
census too.

> **CORRECTED 2026-09-10 (pre-ship documentation chore).** This paragraph
> read *"`KVAP` moves `4,619 → 4,626` and every other opcode reports
> `min == max`"*. Both clauses are false against the census it cites: the
> `KVAP` spread `4,619 → 4,626` is already in the ONE-token census, and
> `VN` (304 → 8,243), `VNW` (769 → 12,289), `CONVW` (8,193 → 24,577) and
> `ALU` (42 → 24,596) all report wide `min`/`max` spreads in both runs — a
> spread is a per-command property here, not a `T` dependence. The
> differenced table above is the measurement, and it is what §5.5's band
> rests on.

**So step 1 understates the six-step mean by 0.11 % and the last step by
0.23 %.** The 3.36 % of the term that §5.6 flags as a lower bound is a lower
bound by about a fifth of one percent over this prompt.

**The per-token term used in the band recommendation is the MEAN over the six
steps: 11,519,849 cycles = 46.079 ms.** The reason is like-for-like and it is
the only defensible choice here: the model's layer coefficient is fitted to
`evidence/qwen2b/rd/RD_GATE.md`'s two **silicon** points, and each of those is
an LCYC total **divided by its token count** — 0.8B *"22,692,603 cyc =
15.128 ms/token"* over 6 tokens, 2B *"26,940,149 cyc = 17.960 ms/token"* over
6. A mean over the same six steps is the same quantity. Step 1 (46.027) and
step 6 (46.132) are given as the bracket, and **the choice moves the headline
by 0.03 % either way**, so nothing in §5.5 turns on it.

**Option (ii) was NOT re-run at six steps, deliberately.** The wait state is a
`dn_step` FSM state in the DeltaNet path (`rtl/dn_step.sv:291`, selected by
`rtl/layer_chan.sv:337`); it is not in `attn_core` or the KV append, so it
cannot interact with `T`. The census proves that from its own data rather than
by assertion: `DNST` reports `min == max == 3,090` across **all 4,608 commands
of all six steps**, so the quantity §5.5 differences is constant in `T` and one
step measures it exactly.

### 5.5 THE RE-ANCHOR IS REFUTED BY MEASUREMENT — A1.6's ≈ +10 % is ≈ +0.9 %

This is the census's decision-moving result, and it is what A1.6 asked for in
so many words: *"Run the census TWICE — with and without the wait state — on
the same stream … it turns Track P's ≈ +10 % bound into this build's own
number, and it is the input Task 10's design decision (Step 1′) is reviewed
against."*

**T**, `evidence/qwen9b/g4/074_layer_term.log`:

```
LAYERTERM option (i) - option (ii) = 98304 cyc/token = 0.393 ms = 0.86 % of the option-(ii) layer term
LAYERTERM per DNST command: 128 cycles; x 768 DNST/token = 98304 cyc/token
LAYERTERM DN_PIPE=2 - DN_PIPE=0 = 101376 cyc/token = 0.406 ms = 0.89 % of the unpipelined layer term
```

| the price of | modelled / bounded | **MEASURED, this stream** |
|---|---|---|
| the pass-2 wait state, option (i) vs (ii) | Track P: **≈ +10 %**, of an unstated base | **+98,304 cyc/token = +0.393 ms = +0.86 %** of the layer term |
| the whole `DN_PIPE = 2` decision, vs unpipelined | — | **+101,376 cyc/token = +0.406 ms = +0.89 %** of the layer term |
| the wait state as a fraction of the modelled STEP (138.61 ms) | A1.6 reading 1: **+10 % of the step** | **+0.28 %** (0.393 / 138.61) |

**Why Track P's bound and this measurement differ by an order of magnitude,
and neither is wrong.** Track P bounded the wait state at ≈ +10 % of
`~1300 cycles/head`, i.e. of the recurrence. Task 10 measured it at **+7.34 %
of `dn_step`** (132 of 1,798) — close to Track P's bound, on Track P's base.
**But `dn_step` is 62 % of the DNST command and the DNST commands are 20.6 %
of the layer term**, so +7.34 % of the recurrence is +0.86 % of the layer
term. The bound was right about the thing it bounded; A1.6 applied it to the
layer term, and that is the step the measurement corrects.

**What that does to §10's band.** Folding the measured layer term into §10's
step — **`matvec 58.95` and `movers 32.66` stay MODELLED (E), only the layer
term is replaced**:

| | layer ms | step ms | **tok/s** |
|---|---|---|---|
| §10 as modelled | 47.00 (E) | 138.61 | **7.214** |
| A1.6 reading 1 (+10 % on the whole step) | — | 152.47 | 6.56 |
| A1.6 reading 2 (+10 % on the layer term) | 51.70 | 143.31 | 6.98 |
| **this census, shipped (option (i))**, step 1 | **46.027 (M)** | **137.637** | **7.265** |
| **this census, shipped (option (i))**, six-step MEAN | **46.079 (M)** | **137.689** | **7.263** |
| this census, shipped (option (i)), step 6 | 46.132 (M) | 137.742 | 7.260 |
| this census, option (ii), step 1 | 45.634 (M) | 137.244 | 7.286 |

*(MEAN and step-6 rows added 2026-09-10: the table gave step-1 figures only
while the paragraph below concludes on the six-step mean. The layer term is
§5.4a's; the step figure adds §10's unchanged `matvec` + `movers` 91.610 ms,
which is the same offset every other row uses. Option (ii) was censused at
step 1 only — there is no six-step run for it — so it keeps a single row.)*

**A1.6's re-anchor to "≈ 6.5 – 7.0 tok/s, headline ≈ 6.56" is not supported by
the measurement.** With the wait state measured rather than bounded, the
figure returns to **≈ 7.26** on the six-step mean — inside §10's original band
of **6.98 – 7.47** and 0.7 % above its 7.214 model figure, with the whole
step-1-to-step-6 spread amounting to **0.005 tok/s**. **This gate therefore
recommends that A1.6's re-anchor be RETIRED and §10's band restored**, and
says so here rather than quietly using the better number.

**And the option-(ii) restructure is now worth 0.3 % of a step, not 10 %.**
§10's third row gave option (ii) as the route back to 7.21; measured, it is
worth **7.286 against 7.265 at the same step 1 — 0.29 %**, and §5.4a shows
`DNST` is constant in `T` (`min == max == 3,090` over all 4,608 commands of
all six steps) so the difference does not grow with context. G3.4 §4.5's reasons for shipping
option (i) (bounded, integration-tested, one cycle of margin on the pass-2
lead) stand, and the thing they were traded against turns out to be worth
almost nothing. **This gate does not re-open the decision; it prices it.**

### 5.6 Every softness that still applies

**The measured term is one of three, and the other two are still (E).** The
step above is a model with one measured term, not a measured tok/s. Everything
§10 lists about `matvec 58.95` and `movers 32.66` still holds, including that
the model **fails its only out-of-sample test at +1.7 %** and that its
`r`-bracket validation is **retracted**.

**It is simulation, not silicon.** LCYC is the same counter the board reports,
and the RTL is the shipping RTL, but a Verilator cycle is not a board cycle in
one specific way: this census drives `layer_chan` over AXI-Lite from a
testbench, whereas on the chip the sequencer and the movers drive it. **The
LCYC counter only advances while `busy` is high**, so host-side latency is
excluded by construction — which is exactly why the term is comparable to
RD_GATE's board measurement — but any effect the real fabric has on the
engine's *own* stalls is not modelled here.

**Two of the ten opcodes are context-dependent, and §5.4's headline is the
step at the SHORTEST cache.** `ATTN` (2.07 % of the term) and `KVAP` (1.29 %)
both scale with the KV cache length `T` (`rtl/attn_core.sv:13`, `:29`), and
step 1 runs at **T = 1** (§5.1). Together they are **3.36 %** of the measured
term, so the step-1 figure is a **lower bound over the prompt** for that
3.36 % and exact for the other 96.64 %. §5.4a measures the growth across all
six steps rather than bounding it.

**One prompt, one seed.** §8 items 5 and 7.

**Prefill is still unmodelled** (§10 item 11). This is a decode-step term.

---

## 6. Gates

| gate | verdict | evidence |
|---|---|---|
| `layer_chan` OOC infers 928 URAM288 with 0 DN cells outside URAM | **PASS** | `ooc_layer_p2_summary.log`, `OOC9B_URAM_MATCH: YES` |
| the 696 / 232 DN-vs-KV split, not just the total | **PASS** | same, `OOC9B_URAM_SPLIT: dn=696 kv=232 other=0` |
| `DN_PIPE = 2` costs ≈ +24.7 K FF | **PASS** | +24,645 = 1.042 % of the device (§2.3) |
| `DN_PIPE = 2` leaves URAM unchanged | **PASS** | 928 → 928 |
| `DN_PIPE = 2` leaves LUT unchanged | **QUALIFIED** | +381; +256 attributed to `attn_core`'s score memory, +5 to the DN delay line, +120 logic (§2.3) |
| BRAM against §4.3's 886.5 tiles | **MEASURED 858.0 (D)** — below the model | §2.4 |
| the four-`matvec_chan` LUT delta | **MEASURED −4,903/channel** | §2.5 |
| `p_acc` fits the 48-bit container on the real 9B stream | **PASS**, 29 of 48 magnitude bits | `066_pacc_observed_9b.log` |
| `p_acc` measured on the RTL, not only in the reference | **PASS** on the 9B layer smoke | `068_pacc_sim_lay9b.log` |
| the decision package's three parts | **DELIVERED** | §4.1, §4.2, §4.3 |
| the census runs and is bit-exact | see §5 | |
| `rtl/` byte-identical to `f81902b` | **PASS** | `git diff f81902b -- rtl/` empty |
| `evidence/qwen_next/spec_cites.py` on this doc | **PASS** | §10 |

### 6.1 The negative control that FIRED, and the guards that did not

**One control was fired deliberately, and it is the one that matters**, because
a cycle census that could not fail would be a stopwatch rather than a
measurement. `evidence/qwen9b/g4/run_g4b_census_control.sh`, log 079_census_control.log in
this directory (named without its path for the reason §9's last row gives),
drives the **already-built**
shipped census binary — no rebuild, no new elaboration — over
`gen_layer_script.py` output at two residual binary points:

* **GREEN**, `FABLE5_RS_F=7` (the operating point), 4 seeds: all four report
  `TB_LAYER_CENSUS PASS: 1438 cmds, 261357 checks bit-exact` — which is also
  an independent reproduction of **G3.4's committed `tb_layer_chan` counts**
  through this task's instrument. (The busy-cycle totals differ by one cycle
  across seeds — 2,062,984 / 2,062,985 / 2,062,986 — because `layerv2`'s ALU
  work is seed-dependent; the DNST cost is not.)
* **RED**, `FABLE5_RS_F=8`, the same 4 seeds: **all four ABORT** with
  `TB_LAYER_CENSUS FAIL: too many errors`, because `rtl/conv4_silu.sv:54`
  bakes the `RS_F + CW_F - 12` shift and a script emitted at the wrong binary
  point cannot replay against this RTL.

Final line: **`G4B_CENSUS_CONTROL PASS: the census's bit-exact half fires both
ways`**, `rc: 0`. The script reports PASS only if the GREEN passes **and** the
RED fails, so it is itself a two-sided check. (A2.5 is unaffected: its rule is never to export
`FABLE5_RS_F` across the byte-lock scripts; this is a script generator.)

**The other guards exist and are stated as guards, not as fired controls** —
naming them honestly rather than counting them as evidence:

* **`run_g4b_census.sh` refuses if `rtl/` is dirty** and **refuses if the
  option-(ii) scratch copy differs from `rtl/layer_chan.sv` in anything but the
  one substitution.** Neither refusal fired; what the runs DID produce is the
  audit trail — `evidence/qwen9b/g4/071_census_optii.log` prints the whole
  `diff`, one hunk, `337c337`.
* **`g4b_gate_clamp_package.py` returns non-zero if the two logs name
  different sets.** It returned zero: they name the same 61. The check is what
  makes that a finding rather than an assumption, but it did not fire.
* **`pacc_probe.sv` cannot pass by being inert:** the run it rides on still
  compares the `.chip` golden, and `evidence/qwen9b/g4/068_pacc_sim_lay9b.log`
  ends `TB_SEQ_CHIP PASS`.
* **the OOC harness asserts rather than assumes**: Vivado 2024.2 (`exit 1`
  otherwise), the ROM hex staging (`exit 1` if missing), and the URAM
  prediction is printed beside the inferred count with an explicit
  `OOC9B_URAM_MATCH: YES/NO` rather than a silent comparison.

---

## 7. Deviations, declared

1. **The permitted `rtl/` change was built and then reverted.** §1.3. The
   brief allows a one-line exposure of `DN_P2WAIT`; it costs 221 citation
   repairs with 7 collateral rewrites by the campaign's own tool, so the
   census uses a scratch copy instead and `rtl/` is byte-identical to
   `f81902b`. Commits `8ea8121` (built) and `7b763d7` (reverted) are both in
   the history on purpose.
2. **The OOC runs launched with two untracked files in the tree.** §2.1. They
   were `synth/scripts/ooc_9b.tcl` and `evidence/qwen9b/g4/run_g4b_ooc.sh` —
   this task's own harness, committed as `bcfa511` minutes later. Nothing
   under `rtl/` was dirty. Each run's own header line says
   `tree      : f81902b9 2 dirty files` and this is what those two were.
3. **`ref/audit_ranges.py` was NOT re-run at the operating point.** §3.4. The
   9B run committed at G1 (`evidence/qwen9b/g1/12_audit_ranges_9b.log`) is
   cited instead, with the two caveats stated: it ran at `FABLE5_RS_F` unset
   and without the GPTQ Hessian. The audit is **weights-only by construction**
   and its own §5 defers accumulator occupancy to a runtime audit, so
   re-running it would not have produced the number the brief wants; §3.2's
   runtime measurement is that number.
4. **The device-wide figures in §2.4 and §2.7 are substitutions labelled S,
   not D and not measurements of a device.** **S** is the right label because
   the arithmetic is this document's — no committed script performs it — while
   its ends are measured (**T**) and the model it is compared against is
   **D**. The first cut of this gate labelled them **D**; corrected in fix
   round 1. `seq_unit` has no committed pre-9B OOC twin and
   is carried unchanged; everything outside `layer_0` and the four mvchans is
   carried unchanged too. Labelled **S** everywhere they appear.
5. **The `+28 RAMB36` scratch figure is not differenced.** §2.4. No build of
   the 32,768-word array exists on this tree to difference against, so this
   gate reports the measured 62 RAMB36 for the 65,536-word array and the
   whole-module 408.5 → 690.0 tile delta, and claims no per-array `+28`.
6. **`evidence/qwen_next/spec_cites.py` still lists `synth/scripts/ooc_9b.tcl`
   as PENDING** ("a future gate creates this"). This gate is that gate and the
   file exists; PENDING is not a failure and the check passes, but the tool's
   list is now stale by one entry. **Not fixed here**, because
   `evidence/qwen_next/` is another track's committed evidence and this task's
   commit is path-limited. **The same staleness shows on the plan**: log
   `evidence/qwen9b/g4/086_spec_cites_plan_control.log` lists
   `evidence/qwen9b/g4/G4B_STRUCT.md` and `synth/scripts/ooc_9b.tcl` as
   PENDING there too. Both exist as of this gate.
7. **The one-token census, not the six-step replay.** §5.1. The controller's
   ruling; the full-stream replay is Task 11's and costs 2 h 42 min per pass.
   **DISCHARGED in fix round 1** — §5.4a is the whole six-step stream
   (`evidence/qwen9b/g4/081_census_shipped_6step.log`, 4,694 s, bit-exact),
   so the `T` dependence this deviation reserved is measured, not deferred.
   *(Marked discharged 2026-09-10; it was still listed as live.)*
8. **The `p_acc` sim probe ran on the 9B LAYER SMOKE, not on the whole
   model stream.** §3.3. The whole-stream figure is §3.2's, from the
   reference; the RTL-side probe exists to show the `bind` reaches the real
   register and that the two agree in order of magnitude. The harness runs the
   full stream unchanged if a reviewer wants it. **A whole-stream run WAS
   started and then stopped** at ~16 min of the ~2 h 44 min it needs; it is
   named here rather than left as a half-written log, and no artifact of it is
   committed.
9. **The log numbering has gaps, and here is every one of them.** Continuing
   Task 11's sequence, this gate commits **066-072, 074-076, 079-082, 084-088**
   (`073`, `077`, `078` and `083` are the gaps below, and `060-065` predate the
   first close). The
   missing numbers were runs that were started and then abandoned; none of
   them is a suppressed result, and each log was deleted rather than left
   half-written:
   * **060-064** — the first census pass and a `DN_P2WAIT`-default proof, all
     built against the `rtl/` parameter of commit `8ea8121`. When that change
     was reverted (§1.3) the binaries they had been built from no longer
     corresponded to any tree, so the runs were stopped and re-launched as
     070-072 against the reverted RTL. One of them (`060`) had also been
     mangled by an edit to its own script *while it was running* — my error,
     and the reason the campaign's "never re-run a committed script in place"
     rule extends to never editing one mid-flight either.
   * **065** — the `p_acc` reference probe launched with the system `python3`,
     which has no `numpy` on snoke. Re-launched as `066` with
     `/home/cah/.venv/bin/python`.
   * **073** — the whole-stream `p_acc` sim, deviation 8.
   * **083** — the first reduction over the six-step census, run while this
     document's own I1 edits were uncommitted, so its header read `+dirty`.
     Re-run as `084` on a clean tree; the numbers are identical.
   * **077, 078** — the census control's first two launches. `077` wedged when
     the ssh session that carried it was killed by a client-side timeout (its
     `tee` died and the script blocked); `078` was relaunched correctly but on
     a tree that was dirty with this document's own §6.1 edit, so its header
     would have read `+dirty` without a declaration. `079` is the run on a
     clean tree.

---

## 8. NOT established by this gate

1. **Nothing about TIMING.** This gate ran `synth_design` and stopped. No
   `opt_design`, no `place_design`, no `route_design`, no `phys_opt_design`,
   no WNS, no TNS. Whether 928 URAM across three SLRs **closes** at 4.000 ns
   is Task 13's, and Track P's post-place estimates
   (`evidence/qwen_next/place_exp/PLACE_EXP.md` §3.7-§3.8) are the only
   placement evidence that exists — on experiment RTL, not this RTL.
2. **Nothing about a device build.** Every device-wide figure here is a
   substitution of measured OOC blocks into build_035's measured device
   totals. No 9B bitstream has been synthesized as a whole design; the
   in-context numbers will differ, and historically differ in the direction
   of *more* (phys_opt replication re-attributes cells — `TIMING_035.md` §8b).
3. **Nothing about the board.** No bitstream, no JTAG, no DMA, no measured
   tok/s. §5's layer term is a **simulation** measurement folded into a
   **modelled** step; it is not silicon and G6 owns the silicon number.
4. **The matvec and mover terms are untouched.** §5 replaces exactly one of
   spec §10's three terms. `matvec 58.95` and `movers 32.66` remain **E**,
   with every softness §10 lists — including that the model **fails its only
   out-of-sample test at +1.7 %** and that its `r`-bracket validation is
   retracted.
5. **`p_acc` is measured on ONE prompt.** §3.2's 29 bits is the maximum over
   `model_9b_s1`'s six forward steps and 10,051,584 accumulated rows. A
   different prompt could occupy more; 18 spare magnitude bits is 262,000×
   of headroom, so the risk is small, but "small" is an argument and this is
   the only prompt measured.
6. **The gate-port clamp's fidelity upside is unmeasured.** §4.1 establishes
   that 98/108 was measured *with* the clamp. What the ladder would read
   *without* it is unknown and can only be learned by building the wider ports
   and re-running — which §4.3 costs and does not build.
7. **The census is ONE seed of the stream set.** `model_9b_s1`. The other
   three seeds exist (G4a §11 handoff 1) and were not censused; the FSM is
   data-independent (Task 10 measured that across four vector seeds, and this
   census's own `min == max` per opcode confirms it for `DNST`), so the cycle
   counts should not move — but "should not" is a prediction.
8. **The `T` dependence is measured over SIX steps, not to the T the hardware
   allows.** §5.4a measures `ATTN` and `KVAP` at `T = 1..6`; `rtl/attn_core.sv:13`
   bounds `T` at **512**, and `rtl/layer_chan.sv:20` gives the `TCNT` counters
   10 bits. What a long context costs the layer term is **not** established
   here, and it is the one term in §5.4 that a longer prompt moves. The
   modelled 47.00 ms it is compared against is itself a decode-step figure
   fitted at two short-context points (`evidence/qwen2b/rd/RD_GATE.md`), so
   the comparison is like-for-like — but neither side speaks for a long
   context.
9. **`DN_PIPE = 0` is not a shippable configuration.** It is the census
   control and the OOC control. It has never been placed at this geometry and
   Track P measured that its read path does **not** close (−1.848 ns).

---

## 9. Logs

Every number above traces to one of these. All are committed under
`evidence/qwen9b/g4/`, numbered continuing Task 11's sequence, each carrying
the `=== host / date / tree / cmd` header `evidence/qwen9b/run.sh` writes.

| log | what it is | last verdict line |
|---|---|---|
| `ooc_layer_p2_summary.log` | Step 1, `layer_chan` at the RTL's own `DN_PIPE = 2` | `OOC9B_DONE` |
| `ooc_layer_p2_util_synth.rpt` | its whole utilization report | — |
| `ooc_layer_p0_summary.log` / `.rpt` | the `DN_PIPE = 0` control | `OOC9B_DONE` |
| `ooc_mvchan_summary.log` / `.rpt` | Step 1, `matvec_chan` | `OOC9B_DONE` |
| `ooc_sequnit_summary.log` / `.rpt` | Step 1, `seq_unit` | `OOC9B_DONE` |
| `069_dnpipe_attrib.log` | the `DN_PIPE` LUT move attributed cell by cell | `ATTRIB DONE` |
| `066_pacc_observed_9b.log` | Step 2, `p_acc` over the whole 9B stream | `PACC VERDICT: FITS` |
| `068_pacc_sim_lay9b.log` | Step 2, `p_acc` on the RTL, 9B layer smoke | `TB_SEQ_CHIP PASS` |
| `067_gate_clamp_package.log` | Step 2 extended, the 61 pairs joined | `GATECLAMP wrap (no clamp) …` |
| `evidence/qwen9b/g4/070_census_shipped.log` | Step 3, option (i) — what ships | `TB_LAYER_CENSUS PASS: 10093 cmds, 1433339 checks bit-exact` |
| `evidence/qwen9b/g4/071_census_optii.log` | Step 3, option (ii) | the same PASS line |
| `evidence/qwen9b/g4/072_census_pipe0.log` | Step 3, the `DN_PIPE = 0` control | the same PASS line |
| `census_shipped.txt` / `census_optii.txt` / `census_pipe0.txt` | the three census tables the TB wrote | — |
| `evidence/qwen9b/g4/074_layer_term.log` | the reduction at the first close (three one-token censuses) | `LAYERTERM … errors=0` ×3 |
| `evidence/qwen9b/g4/081_census_shipped_6step.log` | fix round 1 / I1 — the WHOLE six-step stream, shipped config | `TB_LAYER_CENSUS PASS: 56118 cmds, 8600034 checks bit-exact` |
| `evidence/qwen9b/g4/census_shipped6.txt` | its census table | — |
| `evidence/qwen9b/g4/082_pacc_observed_9b_r2.log` | fix round 1 / m5 — the `p_acc` re-run, every value bit-identical to `066` | `PACC VERDICT: FITS` |
| `evidence/qwen9b/g4/084_layer_term_6step.log` | fix round 1 — the reduction over all four censuses, with the per-step profile and the MEAN | `LAYERTERM … errors=0` ×4 |
| `evidence/qwen9b/g4/075_cite_drift_check.log` | the drift gate on the (unchanged) `rtl/layer_chan.sv` | `O3_CITE_DRIFT CHECK PASS (0 drifted, 0 unresolved, 0 missing, 0 half-mapped)` |
| 079_census_control.log, in this directory | the census instrument's RED and GREEN | `G4B_CENSUS_CONTROL PASS` |
| `evidence/qwen9b/g4/085_spec_cites_plan_a3.log` | `spec_cites.py` on the PLAN after the A3 amendment | `SPEC CITES: PASS` (403 exist, 79 range) |
| `evidence/qwen9b/g4/086_spec_cites_plan_control.log` | its NEGATIVE CONTROL, `--selftest` on the plan's own path | `SELFTEST: PASS` |
| 076_spec_cites_final.log, 080_spec_cites_final.log and 087_spec_cites_final.log, in this directory | `spec_cites.py` on this document, on the committed tree — 076 and 080 at the first close, 087 after fix round 1 | `SPEC CITES: PASS` |

*The `079` and `087` rows are deliberately NOT written as citations: both logs
are produced AFTER this document's last edit — one is the checker itself — so
a citation to either could not be checked before it exists.*

---

## 9a. FIX ROUND 1 (2026-09-03) — what moved

The task review approved this gate in substance and ruled the `DN_PIPE` LUT
judgement correct, with a cross-check that was available and not made. What
this round changed, all of it inside this gate's own files plus one dated plan
note:

| item | where | what |
|---|---|---|
| **ruling** | §2.3a | Track P's own `DN_PIPE 0 → 2` pair — distributed RAM **344 → 344** — proves the +256 is not a pipelining cost |
| **ruling** | §2.3b | the +120 Logic-LUT residual closed **instance by instance** with the hierarchical report; the ten children sum to exactly +120 |
| **I1** | §5.1, §5.4a, §5.6, §8 item 8 | step 1 runs at **`T` = 1**, stated; the **six-step census** run and the `T` dependence **measured** at 0.227 %; the band re-derived on the **mean** |
| **I2** | `synth/scripts/ooc_9b.tcl:29`, `:101`, `:106` | the launcher that does not exist, replaced with the one that does |
| m3 | §10 | the PENDING count |
| m4 | `evidence/qwen9b/g4/g4b_layer_term.py` | the retracted preamble text, replaced with the measured contents |
| m5 | `evidence/qwen9b/g4/g4b_pacc_probe.py`, §3.2 | the self-inconsistent bit line, with a re-run that reproduces every value |
| m6 | §0, §2.4, §2.7, deviation 4 | the device substitutions relabelled **S** |
| m7 | §2.3b | retired by the ruling |
| m8 | `evidence/qwen9b/g4/run_g4b_census.sh`, `evidence/qwen9b/g4/run_g4b_pacc_sim.sh` | `RC=$?` unreachable under `set -e` |
| m9 | §3.2 | the reference half sees the FINAL accumulator, so it is a lower bound |
| plan | **A3** | A1.6's re-anchor retired on the measured +0.86 % |

**`rtl/` is byte-identical to `f81902b` throughout this round**, as it was
through the first close.

---

## 10. Citation drift, and the checker

**Nothing this task edited is cited by line anywhere, because this task edited
no source file.** `rtl/`, `ref/`, `tb/`, `sw/`, `docs/` and `synth/` (apart
from the new `synth/scripts/ooc_9b.tcl`, which no document cited before this
one) are untouched — §1.3 and `git diff f81902b --stat -- rtl/` being empty.

The drift tool was nonetheless run in its `--plan` form, and its output is
**why** §1.3 exists rather than a formality: it is what priced the reverted
`rtl/` change at 221 repairs and 7 collateral rewrites. **No `--fix` was run
and none is owed** — with the change reverted there is no drift to repair.

`evidence/qwen_next/spec_cites.py` on this document, after its final edit:
`SPEC CITES: PASS`. **Fix round 1 also ran it on the PLAN**, after the A3
amendment (`evidence/qwen9b/g4/085_spec_cites_plan_a3.log`, 403 paths exist,
79 ranges in range, FAIL 0) **with its own negative control** — `--selftest`
on the plan's own path, `evidence/qwen9b/g4/086_spec_cites_plan_control.log`,
`SELFTEST: PASS`, which is the checker fabricating broken citations and
requiring itself to catch them. Its `PENDING synth/scripts/ooc_9b.tcl` lines — **nine** at the first close
(logs `evidence/qwen9b/g4/076_spec_cites_final.log` and
`evidence/qwen9b/g4/080_spec_cites_final.log`) and **fourteen** in log 087
after this round's §2.3a/§2.3b added more mentions, out of **fifteen** PENDING
lines in that log, the fifteenth naming this document — are the tool's own
list being stale (deviation 6); PENDING is not a failure. *(Recounted from
the logs 2026-09-10: this sentence said "ten". Both paths have since landed
and were pruned from the PENDING set at S5, so the checker reports
`pending 0` on this document today.)*

---

## 11. Handoffs

**To Task 13 (timing):**

1. **The structure numbers it starts from are §2.7's**, and they are
   substitutions, not a device build. The one that is not a substitution is
   **URAM 928 = 96.7 % of the part**, measured on the shipping RTL, with the
   DN state array **entirely in URAM** (0 non-URAM cells). Track P's placement
   evidence is on experiment RTL; the count is now confirmed on this RTL.
2. **The `DN_PIPE = 0` OOC checkpoint exists** at
   `synth/out_ooc9b_layer_p0/post_synth.dcp` (gitignored, on snoke) if a
   comparison is wanted. It is **not shippable** — Track P measured its read
   path at −1.848 ns.
3. **`attn_core`'s score memory is implementation-unstable across builds**
   (§2.3): 1 RAMB18E2 at `DN_PIPE = 0`, 256 RAMS64E1 at `DN_PIPE = 2`. If a
   timing run sees a surprising `u_attn/sc_mem` structure, that is why, and it
   is a Vivado inference choice rather than an RTL change.

**To G5a / G5b (build):**

4. **BRAM is measured 858.0 of 2,160 tiles (39.7 %, D)**, 28.5 tiles below the
   model's 886.5. BRAM is not the wall, at either figure.
5. **The four `matvec_chan`s are −19,612 LUTs device-wide** against
   build_035's W8 engine. build_035's placement crisis was attributed to
   +21,111 device LUTs (`TIMING_035.md` §8b); this build gives most of that
   back.

**To whoever owns the gate-port clamp decision:** §4 is the package. It makes
no recommendation, on purpose. The one thing a reader should not have to
re-derive: **the clamp was inside the fidelity loop, so 98/108 already prices
it** (§4.1), and the number of clamping pairs is **61**, not 62 (§4.2).
