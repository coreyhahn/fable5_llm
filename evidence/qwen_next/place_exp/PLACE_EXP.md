# Track P — the URAM placement experiment (qwen-next de-risking, D3)

**Verdict, in the form D1 needs it** (revised 2026-08-25 after a review round
whose first finding changed the answer — see §3.7–§3.8):

> **The count is exact.** The widened `layer_chan` infers **928 URAM288**,
> matching §2.7 to the primitive, with zero DN banks falling out of URAM.
>
> **It places.** `place_design` legalises 928 URAM at 312 / 312 / 304 of 320
> per SLR, no ERROR. **Nothing was routed**, so the "places **and routes**"
> question §6 item 3 actually asked is still half open.
>
> **The study's sharp form was right, and is now refined.** At the as-built
> read-path structure the named 2048-bit DN bank-mux net is **−1.848 ns**
> against 4.000, where the as-built geometry **meets at +0.211** in the
> identical flow. Two refinements: the crossing is **one** boundary per access,
> not two (the placer centres the mux destination); and the regression is
> **route** (+2.12 ns), not **logic** (−0.06 ns).
>
> **But "option 1 is dead" is WITHDRAWN.** Pipelining the crossings — cost in
> silicon: flip-flops only, **~1 %** of the device, URAM unchanged at 928 —
> takes that named path to **+0.097 ns, MET** (N=2 under
> `AltSpreadLogic_medium`; the same build at the Default directive is −0.162). The read-path objection this document
> originally rested the verdict on does not survive the experiment. What now
> binds is a **different** net the study never named: the **write-control
> fan-out** (−1.391 to −1.956 ns), whose worst path is one logic level and
> **95.9 % route** between a dedicated register and the single bank it drives.
> That is a **floorplanning** problem, and no floorplan was tried here. So
> option 1 is **neither demonstrated live nor demonstrated dead**.
>
> **And the revival is tempered, because the cheap price and the closing
> result are different builds.** Read latency is 2 + 2N. **N=1** costs
> **~0.15 %** — the address is a pure counter, so issuing it in `P1_DEC` /
> `P2_OUT` absorbs the latency with no extra states — but N=1 sits at
> **−0.339, violating**. **N=2** is the build that reaches MET, and its lead
> of 6 does not fit `dn_step`'s 5-state pass-2 loop at all: it costs a wait
> state (**≈ +10 %**) or an unpriced two-outstanding restructure. Option 1's
> real price is therefore **≈ 10 % or an unquantified redesign**, not 0.15 %.
>
> **The recovery cost was also wrong, by ~250×, in both directions.**
> `dn_step` reads the state memory **256 times per head**, so a naive extra
> latency cycle is **+19.7 %**, not the ~0.08 % implied. But the read address
> is a pure counter, so issuing it two states earlier absorbs the latency with
> **no extra states**: **~0.15 %**. And the contract is local to `dn_step` —
> `dn_rdq` has exactly one consumer — not "every FSM", as claimed.
>
> **Option 2 (int8 DN state) is measured LIVE and is the answer D1 should
> carry.** 580 URAM with a write-combining register, **592 without one** — and
> §3.5 measures that the naive partial write does **not** fall out of URAM, so
> the combiner is an optimization worth 12 URAM, not a requirement. Under
> `AltSpreadLogic_medium` the named path **MEETS at +0.033** and the module
> sits at **WNS −0.119 / TNS −2.7 / 48 failing endpoints** — the same order as
> the as-built control's 16. **Fidelity remains unmeasured.**
>
> **Option 3 (DDR spill) is untouched.** And every number here is
> out-of-context and post-place: **a failure is definitive, a success is
> necessary but not sufficient**, and nothing was routed.

---

## 1. The question, in the form the study sharpened it to

`docs/QWEN35_NEXT_FEASIBILITY.md` §6 item 3 and §8 D3:

> does a `layer_chan` widened to the 4B/9B head geometry — DN state 24 URAM
> banks (24 layers × 32 value heads × 128 rows), KV 8 banks, total **928
> URAM288 = 96.7 %** of the VU9P's 960, necessarily spanning **3 SLRs** —
> synthesize to the predicted 928, and then **PLACE**?

and its sharp form:

> the **2048-bit DN bank-mux read path** (`rtl/layer_chan.sv:562-575`, feeding
> `dn_rdq`) must cross **both** SLR boundaries on every access, because 928
> URAM cannot fit in fewer than three SLRs and the mux has one destination.

The study is explicit about what each Vivado step can answer, and this
experiment respects that split:

| step | answers |
|---|---|
| `synth_design` | **inference only** — that the widened banks map to 928 URAM288 primitives and not to something worse |
| `place_design` | the **real** question — URAM columns are physical and the 320-per-SLR limit binds at placement |

So every variant runs `synth_design -mode out_of_context` **and then**
`opt_design` + `place_design`.

## 2. Method

* **Experiment RTL, not migration RTL.** `main`'s `rtl/` is untouched
  (`git status --porcelain rtl/` empty throughout this track). The twelve files
  of `layer_chan`'s dependency closure were copied to `synth/exp_uram/rtl/`,
  each with an EXPERIMENT banner. **Ten of the twelve are byte-identical to
  `rtl/` apart from that banner**; only `layer_chan.sv` and `gate_unit.sv`
  changed, and both changes are purely **parameterization**. They were never
  simulated: this is a synthesis/placement experiment and no functional claim
  is made about them.
* **The widening is derived from the study's wall rows, not invented.** The
  parameter block in `synth/exp_uram/rtl/layer_chan.sv` carries the mapping and
  the citations:

  | knob | as built | 4B and 9B | study wall row (§2.1) |
  |---|---|---|---|
  | `LNH` DN value heads | 16 | **32** | row 10 — `dn_head` 4 bits / `gate_unit` NH=16 |
  | `N_DN` DeltaNet slots | 18 | **24** | rows 6, 16 |
  | `N_KV` GQA slots | 6 | **8** | rows 7, 16 |
  | `NKVH` kv heads/layer | 2 | **4** | row 9 — `kvhead` is ONE bit |
  | `CVD` conv bank depth | 6144 | **8192** | row 8 — 18×6144 → 24×8192 |
  | `DN_EW`/`DN_PACK` DN state element | 16 | 16, or 8 packed = §2.7 lever 1 | §2.7 |

  The as-built hand-split address (`{dn_layer_r[0], head[3:0], row[6:0]}`
  in-bank, `dn_layer_r[4:1]` as the bank) was rewritten as ONE linear address
  `{dn_slot, head, row}` cut at the 4096-row URAM depth. At the default
  parameters that is **bit-identical** to the shipped expression, and it
  generalizes: at `LNH=32` the head+row field is exactly 12 bits, so one bank
  holds exactly one layer and the bank count becomes 24. The KV array gets the
  same treatment (`{kv_slot, kvhead, k/v, t[8:0]}` → 8 banks at `NKVH=4`).
  The field walls the study lists separately (rows 9, 10, 11 — `kvhead` is one
  bit, `dn_head` four, `cvi` thirteen) are **not** addressed; the experiment
  simply takes the extra bit, because those are *field* walls and this is a
  *capacity and placement* question.
* **Verilator first, no testbench campaign.** All **eight** parameter sets lint
  clean under `verilator --lint-only -Wall --timing`, Verilator 5.020 —
  `lint_exp_rtl.log` covers **all eight** parameter sets used here.
* **Out-of-context, on the board's part.** `synth_design -top layer_chan -part
  xcvu9p-fsgd2104-2L-e -mode out_of_context`, one 4.000 ns clock on `aclk` —
  the 250 MHz `xdma_0_axi_aclk` domain `layer_0` lives in on every shipped
  bitstream (`synth/scripts/build.tcl:34-42` gates on exactly that). Fresh
  `synth/out_exp_uram_<variant>/` per run, never reused. Script
  `synth/exp_uram/scripts/exp_ooc.tcl`, launcher `launch_exp.sh`, detached on
  **snoke**. No other Vivado job was running when this started (checked: only
  idle `vivado-mcp` servers and Track L's Python).
* **No board, no full build, no bitstream.**

### 2.1 What an out-of-context placement can and cannot say

This governs how every number below should be read, so it is stated before
them.

OOC placement puts `layer_chan` **alone** on the whole VU9P: no XDMA/PCIe/GTs
at their fixed sites, no four DDR4 MIGs anchored to their IO banks, no four
`matvec_chan`s, no `seq_unit`, no pblocks, and none of the ~200 K CLB LUTs
build_035 spends outside `layer_0` (299,076 for the whole design vs 98,495 for
`layer_0` alone).

Therefore:

* a **failure here is definitive** — the in-context problem is strictly harder;
* a **success here is necessary but not sufficient** — it is the best case that
  exists.

There is a second asymmetry on top: these are **post-place estimates, before
routing and before `phys_opt_design`**. For a design in the normal regime the
final number is usually *better* (build_035 closed −0.091 → 0.000 in one
phys_opt pass). For a design whose deficit is unregistered SLR-spanning wire it
is not, because routing has no shorter wire to find. That distinction is
exactly what separates `wide` from `int8p` below.

### 2.2 The control, and why it comes first

The shipped flow already synthesizes `layer_chan` out of context: build_035's
`bd_layer_0_0_synth_1` run is exactly this module at the as-built geometry, and
it is committed. Its numbers are the yardstick. The **committed source of
record** is `evidence/qwen2b/rc/t5_07_ooc_synth_utilization.log:39-47` — the
"build_035 bd_layer_0_0 (layer_chan OOC synth)" block.
`ref_build035_layer0_ooc_utilization_synth.rpt` in this directory is the full
report copied out of the gitignored run dir as **corroboration**, not as the
source:

| | build_035 OOC `layer_chan` | this experiment, `base` |
|---|---|---|
| **URAM** | **348** (36.25 % of 960) | **348** |
| Block RAM Tile | 408.5 (395 RAMB36 + 27 RAMB18) | 396 RAMB36 + 27 RAMB18 |
| DSPs | 1,838 | 1,838 |

348 is also the whole shipped design's URAM
(`evidence/qwen2b/rc/TIMING_035.md:850-851`), because `layer_0` is the only
URAM user. The control reproduces it **exactly**, with DSP and RAMB18 exact and
one RAMB36 of difference. That tile is **not** "re-synthesis noise": the
reference was synthesized as a BD module wrapper (`bd_layer_0_0` — an extra
Verilog level carrying the IPI interface attributes) while this experiment
synthesizes `layer_chan` directly as top. It is a **flow difference**, and a
repeatable one. The parameterized copy is faithful, so what it says about the
wide geometry counts.

---

## 3. Results

Four variants, each `synth_design -mode out_of_context` → `opt_design` →
`place_design` on `xcvu9p-fsgd2104-2L-e` at 4.000 ns.

### 3.1 (a) The URAM count — the study's arithmetic is exactly right

| variant | geometry | predicted URAM288 | **inferred** | match | DN banks out of URAM |
|---|---|---|---|---|---|
| `base` | as built (16 heads, 18 DN, 6 GQA) | 348 | **348** | ✅ | 0 |
| `wide` | **4B / 9B** (32 heads, 24 DN, 8 GQA) | **928** | **928** | ✅ | 0 |
| `int8u` | wide + int8 DN state, unpacked | 592 | **592** | ✅ | 0 |
| `int8p` | wide + int8 DN state, **packed**, write-combined (§2.7 lever 1 as costed) | **580** | **580** | ✅ | 0 |
| `int8naive` | wide + int8, packed rows, **naive 1024-bit partial write** | 580 | **592** | ✗ (see below) | **0** |

`synth_design` answers its half with no ambiguity: the widened banks map to
**exactly 928 URAM288**, not to something worse, not to LUTRAM or BRAM. §2.7's
`9 × 29 + 3 × 29 = 348` → `24 × 29 + 8 × 29 = 928` is confirmed at both ends.
Every variant reports DSP **1,838** and RAMB18 **27 / 33** — the widening moves
URAM and RAMB36 and nothing else, as it must, since none of it touches an
arithmetic unit.

Two notes on the int8 rows, because the study's 580 needed a mechanism it did
not state:

* the **naive** int8 mapping (24 banks of 4096 × 1024 b) costs
  `ceil(1024/72) = 15` URAM per bank → 360 + 232 = **592**, not 580, because a
  1024-bit row wastes 56 of every 1080 URAM bits;
* the study's **580** needs the packing it describes ("two state rows pack into
  one 2048-bit URAM row"), which halves the bank count to 12 — **and the mux
  fan-in with it, which turns out to matter more than the URAM saving** (§3.3).

**And the claim this document made about *why* the packing needs a write
combiner was wrong — measuring it is what caught that.** An earlier revision
asserted that a 1024-bit partial write of a 2048-bit URAM row "would drop the
array out of URAM entirely", on the reasoning that "1024 is not a multiple of
the 9-bit BWE lane". Both halves of that are wrong: URAM288's write enable is
9 lanes of **8** bits, so 1024 **is** byte-aligned; and the array does **not**
leave URAM. The `int8naive` variant implements exactly that partial write and
`synth_design` reports **592 URAM288 with zero non-URAM cells in `g_dn`**
(`r2int8naive_summary.log`: `EXP_SYNTH_DN_NONURAM_CELLS: 0`). Vivado simply
maps each independently-written half to its own 15-URAM slice
(`ceil(1024/72) = 15`), so a bank costs **30** instead of 29 — 12 banks × 30 =
360, + 232 KV = **592**.

So the corrected mechanism, and it is a much weaker claim than the one it
replaces:

* the 72-bit primitive boundary is real — 1024 is not a multiple of 72, so the
  half-row boundary falls inside URAM #14 (bits 1008–1079) and Vivado cannot
  share that primitive between the halves;
* but its consequence is **+1 URAM per bank**, not a fallback out of URAM;
* the **write-combining register therefore buys 12 URAM (592 → 580, 2 %)** and
  nothing else. It is an optimization, **not** an enabling requirement.
* **Practical consequence for a migration:** `int8naive` gets the same 12-bank
  read mux as `int8p` for 12 extra URAM and no write combiner, no even/odd
  flush reasoning, and no new correctness obligation. On this evidence it is
  the better engineering trade, and the study's 580 is best read as the
  *floor*, with 592 the price of not having to be clever.

Where the combiner *is* used (`int8p`), its legality rests on `dn_step` driving
`s_wraddr` **ascending within each pass**, starting even and ending odd: pass 1
walks rows 0…127 (`rtl/dn_step.sv:262` sets `s_wraddr <= row`, `:226` increments
and re-issues), `DLT_K` resets `row`, and pass 2 walks 0…127 again (`:224`,
`:234`). LDK = 128 is even, so every pass starts even and ends odd and the
combiner is never left holding a stranded half at a pass boundary. **That
even-start / odd-end flush property is what the legality hangs on**, not
"monotonic addresses" in general.

**Provenance.** The whole set was run twice: `DN_PACK` was added to
`layer_chan.sv` after a first wave, so everything was re-run on the final
committed RTL. `base`, `wide` and `int8u` returned **metrics-identical** URAM,
BRAM, DSP, SLR spans, bank-mux slack and WNS in both waves
(`wave1_*_summary.log` vs `v2*_summary.log`). That is the empirical statement
that `DN_PACK=0` is inert. It is **not** evidence about placer variance — same
RTL, same directive, same tool is expected to repeat; §3.6 is the one sample
that addresses that. The numbers below are the final wave.

### 3.2 (b) Placement, and the timing estimate on the bank-mux path

| variant | URAM | `place_design` | URAM per SLR (of 320) | SLRs | **DN bank-mux worst slack** | module WNS | TNS | failing EP |
|---|---|---|---|---|---|---|---|---|
| `base` | 348 | **OK**, 1981 s | 261 / 87 / 0 | 2 | **+0.211 MET** | −0.145 | −1.2 | **16** |
| `wide` | 928 | **OK**, 2715 s | **312 / 312 / 304** | **3** | **−1.848** | **−2.103** | **−12,945.8** | **27,287** |
| `int8u` | 592 | **OK**, 2185 s | 168 / 192 / 232 | 3 | −0.613 | −0.846 | −2,272.2 | 8,167 |
| `int8p` | **580** | **OK**, 2338 s | 112 / 236 / 232 | 3 | **−0.259** | −0.594 | −117.4 | 1,025 |

**Placement legalises.** `place_design` placed 928 URAM288 across the three
SLRs at 97.5 % / 97.5 % / 95.0 % of each SLR's 320 columns, in 2715 s, with
**no ERROR and no CRITICAL WARNING** (there is no `*_vivado_errors.log` in this
directory because there were none, in any variant). The `Macro Placement`
phase — the one that assigns URAM macros to physical columns — passed.

**What that does and does not retire.** It answers *only* the narrow reading
"can the URAM macros be legally sited". It does **not** retire the risk the
study stated: §6 item 3 asked whether the VU9P "**places and routes**" at this
occupancy with zero timing margin, and §7.2 ranked it as "URAM at 96.7 %,
unpriced by synthesis *and* by placement, on a design that closes at WNS 0.000".
**Only `place_design` ran — nothing was routed**, so the "and routes" half of
the study's own question is still open (§5 item 2). On the substance the study
was **right**: its sharp form named the exact net that fails, and it fails.
Track P's contribution is **confirmation plus two refinements** — one crossing
rather than two, and route rather than logic — not a twist against a risk
framing the study never held.

The per-SLR percentages also confirm the 320-per-SLR figure straight from the
device rather than from folklore: `base`'s 261 URAM is reported as 81.56 % of
SLR0, and 261 / 0.8156 = 320.

**Timing is the wall, and for `wide` it is not close.**

### 3.3 The decomposition — `wide` is a wire problem, not a mux problem

The same path, `g_dn[*].mem_reg_uram_*/CLK → dn_rdq_n_reg[*]/D`, in the same
flow, across the four geometries (`v2*_dn_bank_mux_paths.rpt`):

| | DN banks | Logic Levels | Data Path Delay | of which **logic** | of which **route** | slack vs 4.000 |
|---|---|---|---|---|---|---|
| `base` | 9 | 2 (LUT5, LUT6) | 3.717 ns | 1.433 (38.6 %) | 2.284 (61.4 %) | **+0.211** |
| `wide` | **24** | 3 (+MUXF7) | **5.772 ns** | **1.373 (23.8 %)** | **4.399 (76.2 %)** | **−1.848** |
| `int8u` | 24 | 3 (+MUXF7) | 4.537 ns | 1.491 (32.9 %) | 3.046 (67.1 %) | −0.613 |
| `int8p` | **12** | **2 (LUT5, LUT6)** | 4.183 ns | 1.445 (34.5 %) | 2.738 (65.5 %) | **−0.259** |

**The mux logic did not get slower at `wide`.** Widening the fan-in from 9 to
24 added one MUXF7 level and *negative* net logic delay (1.433 → 1.373 ns). The
entire 2.06 ns regression is **route**: 2.284 → 4.399 ns. That matters because
it says which fixes are useless — pipelining the mux buys back ~1.4 ns of logic
that was never the problem.

The physical reason is in the SLR connectivity tables
(`v2*_util_placed_slr.rpt`):

| | SLR0↔SLR1 SLLs | SLR1↔SLR2 SLLs | total | **crossings using Laguna TX_REG / RX_REG** |
|---|---|---|---|---|
| `base` | 1,002 (5.8 %) | 0 | 1,002 | **0** |
| `wide` | **3,870 (22.4 %)** | 884 (5.1 %) | 4,754 | **0** |
| `int8u` | 2,545 (14.7 %) | 192 (1.1 %) | 2,737 | **0** |
| `int8p` | 3,738 (21.6 %) | 144 (0.8 %) | 3,882 | **0** |

Every SLR crossing in every variant is **unregistered**. Laguna TX/RX registers
are the hardware that makes an UltraScale+ SLR crossing fast, and they need a
register immediately either side of the crossing with a whole clock cycle for
the hop. The DN read path is URAM CQ → combinational bank mux → fabric OREG in
**one** cycle; there is nowhere to put them **in the as-built structure**.
So 24 banks spread over three SLRs means 4.4 ns of raw unregistered
SLL-and-interconnect haul on a 4.0 ns budget. **§3.7 tests adding a place to
put them** — and finds the read path recovers, though not by the Laguna
mechanism this paragraph implies.

**And the named path is not the module's worst path.** `wide`'s post-place WNS
endpoint is not the read mux at all — it is the **write-control broadcast**:

```
Slack (VIOLATED) :        -2.103ns
  Source:                 dnz_we_reg/C                       (FDRE)
  Destination:            g_dn[1].mem_reg_uram_19/BWE_B[4]   (URAM288)
  Data Path Delay:        5.682ns  (logic 0.205ns (3.608%)  route 5.477ns (96.392%))
  Logic Levels:           2  (LUT3=1 LUT5=1)
```

(`v2wide_timing_summary_placed.rpt`, the first `Slack (VIOLATED)` block.) One
register fanning out a write enable to 24 banks across three SLRs, **96.4 %
route**. So there are **two** SLR-spanning problems in this design, not one:
the study named the read mux, and the module is actually limited by the write
side. §3.7 and §3.8 are mostly about the second one.

**On the study's "must cross both boundaries" phrasing.** The placer did better
than the study assumed, and `wide` still lost. It put the mux destination
register in the *middle* SLR, so no single access crosses more than one
boundary: all 30 worst DN-mux paths are `SLR0 → SLR1`, never `SLR0 → SLR2`. The
study's mechanism as written ("crosses both SLR boundaries on every access") is
therefore **too strong**; the correct statement is that the *path family* spans
both boundaries because the sources sit in all three SLRs, while any one access
crosses at most one. The conclusion survives a fortiori: **one** crossing is
already −1.848 ns.

### 3.4 Why `int8p` is a different kind of number

`int8p` is not just "less URAM". It wins on two axes at once:

1. **Bank count 24 → 12**, which puts the mux back at **2 logic levels** with
   no MUXF7 — the same depth as the shipped 9-bank design.
2. **DN state 696 → 348 URAM**, which fits in **two** SLRs — and the placer put
   it there: `DN_STATE : SLR0=112 SLR1=236` (`v2int8p_uram_slr_census.rpt`).
   The 3-SLR *total* span is only because the unconstrained placer sent the KV
   array to SLR2; 348 + 232 = 580 ≤ 640, so a floorplan that keeps both in two
   SLRs is arithmetically available and was **not** tried here.

The result is TNS **−117 ns over 1,025 endpoints** — three orders of magnitude
off `wide`'s −12,946 over 27,287, and in the band this project has closed
before (the timing-closure playbook's census → reroll → phys_opt sequence
closed −0.091 → 0.000 in one pass; the build_034 campaign handled ~1 ns
classes with floorplanning).

### 3.5 The "falls out of URAM" claim, measured

`int8naive` (`DN_PACK=2`) implements the 1024-bit partial write of a 2048-bit
URAM row that §3.1 previously asserted was impossible. `synth_design` reports
**592 URAM288 and `EXP_SYNTH_DN_NONURAM_CELLS: 0`** — the array stays entirely
in URAM. Vivado maps each independently-written half to its own 15-URAM slice
(`ceil(1024/72) = 15`), so a bank costs **30** rather than 29: 12 × 30 = 360,
+ 232 KV = 592. **The assertion was wrong, and only running it found that.**
The write-combining register is an optimization worth 12 URAM, not an enabling
requirement. Evidence: `r2int8naive_summary.log`.

### 3.6 Placer-directive spread, sampled once

The two waves of §3.1 are *not* a variance sample. `int8p_alt` re-runs `int8p`
with `place_design -directive AltSpreadLogic_medium` and nothing else changed:

| `int8p`, 580 URAM | DN bank-mux | WNS | TNS | failing EP |
|---|---|---|---|---|
| `-directive Default` | −0.259 | −0.594 | −117.4 | 1,025 |
| `-directive AltSpreadLogic_medium` | **+0.033 MET** | **−0.119** | **−2.7** | **48** |

One directive change moves the named path from failing to **meeting** and the
module to **48 failing endpoints** — the same order as the control's 16. So the
house playbook's "±3 ns multi-SLR placer spread" is live on this design, ~0.5 ns
was available for free here, and **`int8p`'s Default number should be read as
one draw, not as the design's capability**. It also means the wide variants'
numbers carry the same uncertainty — which matters most where they are close.

### 3.7 The registered-crossing experiment — does pipelining rescue option 1?

The review's decision-moving question: the −1.848 ns is unregistered
SLR-spanning wire, so what happens if the crossings are pipelined? `DN_PIPE=N`
inserts N register stages on the per-group control/address/write-data fan-out
**and** N stages on the read-data return, so each long haul runs flop-to-flop.
Read latency 2 → 2 + 2N; write latency +N. Cost is flip-flops only: LUTs stay
at ~109.5 K, FFs go 54,276 → 66,501 (N=1) → 78,948 (N=2) — deltas of 0.52 %
and **1.04 %** of the device's 2,364,480, i.e. **~1 %**. URAM stays exactly 928
in both.

| wide, 928 URAM | DN bank-mux | group return | **write fan-out** | WNS | TNS | failing EP |
|---|---|---|---|---|---|---|
| `wide` (as built, N=0) | −1.848 | — | −2.103 | −2.103 | −12,945.8 | 27,287 |
| `widepipe1` (N=1) | **−0.339** | −0.876 | **−3.185** | −3.185 | −6,189.9 | 6,480 |
| `widepipe2` (N=2) | **−0.162** | −0.052 | **−1.391** | −1.391 | −2,007.2 | 6,638 |

**Two findings, and they point opposite ways.**

1. **The study's named path is largely fixable by pipelining.** −1.848 →
   **−0.162** at N=2, and the group return is at −0.052. Combined with §3.6's
   ~0.5 ns of free directive spread, the 2048-bit DN bank-mux read path is
   **not** a structural dead end. **The read-path objection that this document
   originally rested "option 1 is dead" on does not survive the experiment.**
2. **But the binding constraint moves to the write-control fan-out, and
   per-group registers do not fix it.** At N=2 it is −1.391 ns, and the worst
   path is `g_grp[0].bs_p_reg[1][0] → g_grp[0].g_dn[7].mem_reg_uram_17/BWE_B[3]`
   — **route 4.747 of 4.972 ns, one logic level**. A group register drives its
   own group's 8 banks, which is still 232 URAM write ports spread across an
   unfloorplanned SLR. `DN_BPG=1` (one fan-out register set per bank, 29 write
   ports each) is the obvious next structure and is tested in §3.8.

**And the hypothesis about *why* is essentially unconfirmed — but "zero" would
be an overstatement.** The stated mechanism for pipelining the crossing was
that flop-to-flop crossings can use Laguna TX/RX registers. Across the nine
placed variants the SLR connectivity tables report **TX_REG/RX_REG usage of
zero in eight of them**, and in `r3pipe2alt` exactly **2 crossings of 4,967**
(SLR1→SLR2: RX_REG-only 1, Both 1). So the placer *can* and does engage the
hardware — an earlier revision of this document said "zero in any variant",
which is **false** — but at 0.04 % of the crossings it explains nothing about
the timing. The read-path gain came from shorter logic depth and more placement
freedom, **not** from the dedicated SSI crossing hardware. What is genuinely
untested is whether Laguna could be engaged *at scale* here, e.g. by a
structure or constraint that makes the crossing registers Laguna-eligible by
construction; that is on the not-established list.

### 3.8 Per-bank fan-out, and where option 1 actually stops

`DN_BPG=1` gives every bank its own fan-out register set, so a write-control
register drives **one** bank's 29 URAM write ports instead of a group's 232.
Adding a directive sample on the grouped variant at the same time:

| wide, 928 URAM, N=2 | grouping | directive | DN bank-mux | group return | **write fan-out** | WNS | TNS | failing EP |
|---|---|---|---|---|---|---|---|---|
| `widepipe2` | 8 banks/grp | Default | −0.162 | −0.052 | −1.391 | −1.391 | −2,007.2 | 6,638 |
| `pipe2alt` | 8 banks/grp | AltSpread | **+0.097 MET** | −0.089 | −1.539 | −1.539 | −3,252.2 | 6,406 |
| `pipe2bank` | **1 bank/grp** | Default | −0.344 | **+0.439 MET** | **−1.956** | −1.956 | −4,671.3 | 12,692 |

**The read side is finished.** With pipelining and one directive change the
study's named 2048-bit bank-mux path **MEETS at +0.097 ns** at the full wide
geometry, and the per-bank variant's group return meets at +0.439. Whatever
else is true, **the read path the study named as the sharp form of D3 is not
what stops option 1.**

**The write fan-out is not fixed by more registers — and the failure has a
placement signature, not a structural one.** Per-bank fan-out made it *worse*
(−1.956 vs −1.391). Its worst path is
`g_grp[18].w_p_reg[1] → g_grp[18].g_dn[0].mem_reg_uram_7/BWE_B[3]`: a register
driving **its own single bank**, **one logic level**, and **route 5.307 ns of
5.535 (95.9 %)**. A dedicated register one LUT from the 29 URAMs it drives
should not be 5.3 ns away from them. It is, because `dont_touch` stops
synthesis merging the copies but nothing *places* them — the fan-out registers
are fed from the central write port, so the placer keeps them near the source
and leaves the long hop on the register→URAM side.

The remaining blocker is therefore **exactly the thing this experiment
deliberately did not do**: constrain placement. Pinning each fan-out register
set into its bank's clock region is a pblock, not an RTL change. **That was not
tried, so option 1 is neither demonstrated live nor demonstrated dead** — and
`NEXT_SESSION.md` T5's warning cuts both ways here, because constraining
`layer_0` *at all* cost build_035 ~1 ns.

---

## 4. What this means for §8 D3's three options

**Option 1 — NOT dead on the mechanism the study named, and NOT shown live
either.** The verdict this document can support is narrower than the one an
earlier revision stated, and §3.7 is why.

* **Dead as-built**: at the shipped read-path structure the named 2048-bit
  bank-mux net is −1.848 ns and the module is −2.103 / −12,946 / 27,287
  endpoints. That much is measured and unambiguous.
* **But the read-path objection does not survive pipelining.** Two register
  stages on the crossings take the named net to **−0.162 ns** and the group
  return to −0.052, for **~1 %** of the device in flip-flops and no LUT change
  (§3.7), and to **+0.097 MET** with a directive change (§3.8). That path is
  **not** a structural dead end.
* **The binding constraint moves to the write-control fan-out**, and **more
  registers do not fix it**: −1.391 ns per-group, −1.956 ns per-bank (§3.8).
  Its worst path is one logic level and **95.9 % route** between a dedicated
  register and the single bank it drives — a **placement** signature.
* **No floorplan was tried**, and that is now the identified next step rather
  than an oversight to be glossed. So the honest status is **"neither
  demonstrated live nor demonstrated dead"** — not "dead". Anyone quoting this
  document should quote that, and should note that `NEXT_SESSION.md` T5 cuts
  both ways: constraining `layer_0` *at all* cost build_035 ~1 ns.

**The recovery cost, corrected — this was wrong by ~250× and it cut both
ways.** An earlier revision asserted a low price ("costs a cycle") while
arguing from the difficulty of the high one. The real arithmetic:

* **`dn_step` reads the state memory 256 times per head, not once.** Once per
  row per pass: pass 1 walks 128 rows through a 6-state loop re-issuing
  `s_rdaddr` at `rtl/dn_step.sv:226`, pass 2 walks 128 rows through a 5-state
  loop re-issuing at `:234`. LDK = LDV = 128 (`:20-21`).
* A **naive** extra latency cycle adds a wait state to each loop:
  **+256 cycles/head ≈ +19.7 %** on the ~1300 cyc/head DeltaNet step (§4.3).
  *That* is the number the "materially harder problem" language belongs to.
* **But the naive cost is avoidable, because the read address is a pure
  counter.** `s_rdaddr <= row + 1` is knowable as soon as `row` is. Today it is
  issued in the loop *tail* — `P1_KW` and `P2_QW` (`rtl/dn_step.sv:226`,
  `:234`) — which delivers a lead of **2** cycles. Moving it **two states
  earlier**, to **`P1_DEC`** and **`P2_OUT`**, delivers a lead of **4** with no
  extra states at all. (One state earlier — `P1_KM`/`P2_QM`, alongside
  `s_wraddr` — gives only **3**; an earlier revision of this document named
  those two states for a lead of 4, which is off by one and would leave an
  implementer a cycle short.) Only pass 1's *first* read pays, because `IDLE`
  issues `s_rdaddr <= 0` immediately before `P1_RD`; pass 2's first read
  already has 6 cycles of lead from the `DLT_*` chain. Steady-state:
  **~2 cycles per head, ≈ 0.15 %**.
* **That price is `DN_PIPE=1`'s, and `DN_PIPE=1` does not close.** Read latency
  at N is 2 + 2N, so N=1 needs a lead of 4 — exactly what `P1_DEC`/`P2_OUT`
  buy. **N=2 needs a lead of 6, and pass 2's loop is only 5 states long**, so
  it cannot be absorbed by moving the issue point at all: it costs either a
  **wait state in pass 2** (+128 cyc/head, **≈ +10 %** on ~1300) or a
  **two-outstanding address restructure**, which nobody has designed or priced.
  §3.7–§3.8 measure that N=1 sits at −0.339 (violating) while N=2 is the one
  that reaches MET. **So the cheap latency price and the closing timing result
  do not come from the same build**, and §4's verdict says so.
* **The contract is local to `dn_step`.** `dn_rdq` is driven once
  (`rtl/layer_chan.sv:570`) and consumed at exactly one port
  (`.s_rddata(dn_rdq)` on `u_dn`, `:398`); `layer_chan`'s collection is a
  count-based handshake (`:1174-1182`, `rcvd`), not a latency-timed one. An
  earlier revision said the change would touch "every FSM timed against it" —
  **false**, and it inflated the perceived cost.
* The write side is tolerant: within a pass, row *r* is read then written
  before row *r+1* is read, and the passes are separated by `DLT_*`. Extra
  write latency is free.

So the price of the **`DN_PIPE=1`** structure is a prefetch change in
`dn_step`'s two loop tails plus ~1 % of the device in flip-flops — on the order
of **0.15 %** throughput, not 19.7 %, and not zero. **But `DN_PIPE=1` does not
close** (−0.339), and the build that does — `DN_PIPE=2` — needs a lead of 6
that pass 2's 5-state loop cannot provide at any issue point, so it costs a
wait state (**≈ +10 %**) or an unpriced two-outstanding restructure. **Quote
the ~0.15 % only against N=1, and N=1 is not the build that meets timing.**
It is also still new logic in the one block build_035's floorplan campaign
could only close by leaving **unconstrained** (`NEXT_SESSION.md` T5:
constraining `layer_0` in any form cost ~1 ns), and nothing here was routed.

**Option 2 — the int8 DN state: LIVE, and the one this experiment can call
live.** The study's 580 is reproduced exactly with a write-combining register;
**592** without one, and the array stays in URAM either way (§3.5). It places,
it keeps the DN state inside two SLRs, it restores the mux to 2 logic levels,
and under `AltSpreadLogic_medium` the named path **MEETS at +0.033 ns** with
the module at **WNS −0.119 / TNS −2.7 / 48 failing endpoints** — the same order
as the as-built control's 16. On this evidence it is closable with the
techniques the house playbook already documents, before any floorplan is tried.

Two caveats it must carry. Its **fidelity** cost is unmeasured — §6 item 5
stands untouched, and §2.7's own reason to expect a cost (the `Av` gate port
already running 1-of-288 heads over its rail) is unaddressed;
`ref/audit_ranges.py` still has to score it. And **nothing was routed.**

**Option 3 — DDR spill: untouched.** Out of scope for a placement experiment.
Its bandwidth argument (1.2 % of 4B W8 traffic) is unaffected by anything here,
and its cost is still a large new RTL path.

**For D1:** the URAM answer that is live is the **int8 DN state**. Because
walls 6–8 are identical at 4B and 9B, this does **not** discriminate between
the two targets — it prices a line item both carry. What it removes is the
option of carrying the DeltaNet state at int16 at *either* target without a new
pipeline stage in `layer_chan`'s state read path. D1 should treat "int8 DN
state, fidelity unmeasured" as a mandatory line in both columns.

---

## 5. What this experiment did NOT establish

Stated in the study's own idiom, because the study's "(U)" list was its most
useful section.

1. **The experiment RTL is not verified.** No testbench was run against it, by
   design. Its *structural* fidelity is evidenced by the control reproducing
   348 URAM / 1,838 DSP / 27 RAMB18 and by ten of twelve files being
   byte-identical to `rtl/`; its *functional* correctness is not evidenced at
   all. The `int8` variants truncate int16 state to int8 with no rounding.
2. **No routing, no `phys_opt_design`, no full build.** Every timing number is
   a post-place estimate. §2.1 argues why that does not rescue `wide` and why
   it understates `int8p`, but those are arguments, not routed numbers.
3. **In-context placement is not measured.** Everything is OOC, the most
   favourable case. The real design adds XDMA/PCIe/GTs, four MIGs, four
   `matvec_chan`s and `seq_unit` — and `matvec_engine`, not `layer_chan`, owns
   build_035's worst waived endpoints (`docs/QWEN2B_QUANT_STUDY.md` §1.1).
4. **No floorplan was tried.** `place_design` ran with no pblocks in every
   variant. Pinning `int8p`'s DN and KV arrays into two SLRs is the obvious
   next experiment for option 2, and it was not run.
5. **The `int8p` write-combining register is a sketch.** Structurally right —
   12 banks, 2048-bit rows, 580 URAM, half-select on read — and it relies on
   `dn_step`'s strictly-ascending `s_wraddr`, which is real
   (`rtl/dn_step.sv:262`, `:297`). It has not been proven correct at command
   boundaries (DNZ, partial rows, back-to-back commands).
6. **The scratchpad was not widened.** Wall 1 (32,768 → 65,536 words) is an ISA
   question, not a URAM one, and carrying it would have changed the BRAM totals
   without touching the URAM answer. The BRAM figures here therefore sit below
   the study's §2.7 device totals and are not a rebuttal of them.
7. **The KV bank mux was not measured separately.** The report hook found no
   `at_kvdata_reg` cell to key on. The KV array lands wholly inside one SLR in
   every variant, so it is not the binding path, but that is an inference from
   the census, not a measurement.
8. **Directive/seed spread is sampled once, not characterised.** §3.6 is a
   single `AltSpreadLogic_medium` draw on one variant, and it moved WNS by
   0.475 ns. The house playbook's ±3 ns multi-SLR spread is therefore live and
   **unquantified for the wide variants**, where several conclusions sit within
   a few tenths of a nanosecond. `base` and `wide` repeating across two waves
   bounds nothing here: same RTL, same directive, same tool is expected to
   repeat.
9. **`int8p` at the Default directive is a single run**, as is every other
   variant except `int8p` itself (two directives). No variant has an n > 2.
10. **The Laguna mechanism is unconfirmed at scale.** §3.7's pipelining was
    motivated by making the crossings flop-to-flop so Laguna TX/RX registers
    become usable. Eight of the nine placed variants use **zero**; `r3pipe2alt`
    uses **2 of 4,967** crossings (0.04 %). So the placer *will* engage the
    hardware — the absolute "zero in any variant" an earlier revision asserted
    is false — but not at any scale that explains the timing. Whether a
    structure or constraint could make the crossing registers Laguna-eligible
    **by construction**, and what that would be worth, is untested.
11. **The write-control fan-out is not solved, and no floorplan was tried.**
    It is the binding path in every wide variant, at both groupings (§3.8), and
    its 95.9 %-route / one-logic-level signature says the fix is placement
    constraint rather than more pipelining. Pinning each fan-out register set
    into its bank's clock region is the obvious next experiment and it was
    **not run**. Until it is, option 1 is undetermined in both directions.
12. **`route_design` was never run, on anything.** Every number in this
    document is post-place. The study asked whether the part "places **and
    routes**"; only the first half was answered.
13. **The `int8naive` variant was synthesized but not placed.** Its 592-URAM
    result (§3.5) is an inference measurement only; its timing is unknown, and
    the claim that it should time like `int8p` (same 12-bank mux) is reasoning,
    not measurement.
14. **The N=2 latency price is not designed, only bounded.** "≈ +10 % or an
    unpriced two-outstanding restructure" (§4) is an upper bound and an
    admission, not an implementation. Nobody has written the pass-2 restructure
    or shown that it closes — and it is the build that meets timing.

---

## 6. Reproduction

```
# lint (any host, Verilator 5.020)
# Explicit file order, NOT a glob: fx_pkg.sv must be read before anything that
# imports it or Verilator fails with PKGNODECL.  Same order as exp_ooc.tcl:78-81.
verilator --lint-only -Wall --timing --top-module layer_chan \
    -GLNH=32 -GN_DN=24 -GN_KV=8 -GNKVH=4 -GCVD=8192 -Isynth/exp_uram/rtl \
    synth/exp_uram/rtl/{fx_pkg,fx_rsqrt,fx_recip,fx_silu,vecnorm_unit,\
rope_unit,conv4_silu,dn_step,attn_core,gate_unit,vec_alu,layer_chan}.sv

# one variant, ON SNOKE, detached (the out dir is never reused)
cd synth/exp_uram/scripts
#            variant  LNH N_DN N_KV NKVH  CVD EW PACK PIPE PLACE [directive] [BPG]
nohup ./launch_exp.sh v2base      16   18    6    2 6144 16    0    0     1 &
nohup ./launch_exp.sh v2wide      32   24    8    4 8192 16    0    0     1 &
nohup ./launch_exp.sh v2int8u     32   24    8    4 8192  8    0    0     1 &
nohup ./launch_exp.sh v2int8p     32   24    8    4 8192  8    1    0     1 &
nohup ./launch_exp.sh r2int8naive 32   24    8    4 8192  8    2    0     0 &
nohup ./launch_exp.sh r2widepipe2 32   24    8    4 8192 16    0    2     1 &
nohup ./launch_exp.sh r2int8p_alt 32   24    8    4 8192  8    1    0     1 AltSpreadLogic_medium &
nohup ./launch_exp.sh r3pipe2bank 32   24    8    4 8192 16    0    2     1 Default 1 &

# carry the load-bearing report sections into evidence/ (synth/out_* is gitignored)
./collect_evidence.sh v2base v2wide v2int8u v2int8p \
    r2widepipe1 r2widepipe2 r2int8naive r2int8p_alt r3pipe2bank r3pipe2alt
```

Committed report copies here, per variant `<v>`: `<v>_summary.log` (the run's
own `EXP_` marker stream with host/date/tree header), `<v>_util_synth.rpt`,
`<v>_util_placed.rpt`, `<v>_util_placed_slr.rpt` (SLR connectivity + per-SLR
block tables), `<v>_uram_slr_census.rpt`, `<v>_dn_bank_mux_paths.rpt` (30 worst
DN-mux paths with start/end SLR, then full `report_timing` on the worst 10),
`<v>_timing_summary_placed.rpt` (the **whole** report — an earlier revision
truncated it at 200 lines, two lines before the write-fan-out block §3.3 and
§4 quote), and for every placed variant `<v>_dn_write_fanout_paths.rpt`, plus
`<v>_dn_group_return_paths.rpt` for the pipelined ones. Plus `lint_exp_rtl.log`,
`ref_build035_layer0_ooc_utilization_synth.rpt` (the committed control), and
`wave1_{base,wide,int8}_summary.log` (the independent first wave).

Runtimes on snoke, four concurrent: synth 12–25 min, `opt_design` 6–8 min,
`place_design` 33–45 min per variant.
