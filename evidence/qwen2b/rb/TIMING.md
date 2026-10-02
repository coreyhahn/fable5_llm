# R-b TIMING GATE — build_034 + closure campaign (2026-08-14 → 08-16)

Tree: `4f908df` on branch `qwen2b`, **clean at launch** (`git status --short`
empty). `launch_build.sh` stamps VERSION from `git rev-parse --short=8 HEAD`, so
the **netlist hash / VERSION CSR expectation is `4f908df2`**.

**Outcome: WNS −0.025 ns. Not closed to ≥ 0. Accepted under a written waiver,
re-affirmed on the corrected rationale (§6).** WHS +0.001. Shipping roll:
`synth/out_build_034_po2_AltSpreadLogic_high`.

> **Correction notice (2026-08-16).** An earlier revision of this document based
> the waiver's technical rationale on the census of the **base/Explore** rolls
> rather than the **shipped** roll. Those are different placements with different
> failing paths, and the earlier rationale was wrong in both of its load-bearing
> claims. The shipped roll's own report (§5) shows the DDR4 ch3 domain
> (`mmcm_clkout0_1`) **met** timing with zero failing endpoints, while **100% of
> violating endpoints are custom RTL** (proven per-endpoint, §5), 23 of them
> inside `layer_0` and 3 in `seq_0`. The waiver
> was re-put to the user against the corrected facts and **re-affirmed** (§6).

---

## 1. Base roll — build_034

Gate lines from `synth/out_build_034/build_run.log`, anchored to start-of-line
(Vivado echoes the sourced TCL, so an unanchored `grep FATAL` matches the
`puts "FATAL: …"` *source* lines — always anchor):

```
4741:CLOCK_GATE_OK: 250MHz clocks: pipe_clk xdma_0_axi_aclk
4771:TIMING: WNS=-0.369 WHS=0.010
4788:BITSTREAM: .../impl_1/bd_wrapper.bit
4790:BUILD_OK
```
0 `^ERROR:` / `^FATAL:`. Wall 3h31m (20:38 → 00:09).

**Base vs build_033's base — R-b improved every headline metric.** (The `+0.009`
often quoted for 033 is its best *reroll*, not its base; base-vs-base is the fair
comparison.)

| metric | 033 base | 034 base | delta |
|---|---|---|---|
| WNS | −0.490 | **−0.369** | +0.121 better |
| TNS | −883.966 | **−260.187** | −70.6% |
| TNS failing endpoints | 7780 | **3703** | −52.4% |
| WHS | 0.000 | **+0.010** | better |
| THS failing endpoints | 0 | 0 | — |

## 2. Failing-path census

`report_timing_summary` reports the worst path per path group; 6 groups violated
on the base roll, 3703 endpoints total. Census of the Explore roll
(`synth/out_build_034_po1/census.log`), top 25 setup paths:

- **17 × `mmcm_clkout0_1`** (ddr4_3 UI clock, 300 MHz — `DDR4_TimePeriod 833` ps
  × 4 = 3332 ps), nearly all at **2 logic levels**, running
  `smc_ch3/m00_exit_pipeline/w_reg` → `ddr4_3/…/u_ddr_ui_wr_data/wr_buffer_ram[*].RAM32M0`.
- 8 × `xdma_0_axi_aclk` (250 MHz).

| # | slack | group | lvl | path |
|---|---|---|---|---|
| 1 | −0.214 | xdma_0_axi_aclk | 8 | `seq_0/u_seq/f_pend_reg[6]` → `axi_smc/s01_mmu/ar_sreg` |
| 2–6, 8 | −0.191 … −0.170 | mmcm_clkout0_1 | 2 | `smc_ch3/…/w_reg` → `ddr4_3/…/wr_buffer_ram[*]` |
| 7 | −0.173 | xdma_0_axi_aclk | 12 | `layer_0/u_core/u_conv/u_silu` carry → DSP `B[12]` |

**Two-level failures are route delay, not logic depth** — there is nothing to
pipeline, which is why this is a placement/phys_opt problem and not an RTL one.
The failing band is tight (−0.214 … −0.149) and concentrated on **channel 3**:
regional congestion around `ddr4_3`, not one pathological path.

**Watch-item disposition:**

| watch-item | result |
|---|---|
| R4 scales mux 96:1 + x LUTRAM 48-line | Live but **not critical**. −0.168 (3rd worst) on the base roll via a `RAMD64E`; **dropped out of the top 25 entirely** under Explore. |
| R6 EMB 5-bit barrel shift | **Never violated, in any roll.** The 3-bit mitigation is **not needed** — do not spend fidelity buying timing that is already met. |
| scratch BRAM (+16 RAMB36) | No violating path. 033's WNS driver was `layer_0/u_core/g_cv[6].wm_reg_bram_0/WEA[2]` (−0.490); it is **absent from 034's violated set**. |

**No `layer_0` path violates on the base roll at all** — every remaining
custom-RTL violation on *that* roll is in `mvchan_*`.

> ⚠ **This section describes the BASE and Explore rolls, not the shipped roll.**
> Placement changes which paths fail. On the **shipped** roll `layer_0` *does*
> carry violations (**23** endpoints, of which **18** are in `u_dn`) and the ch3
> DDR4 domain meets timing. (26 is the `xdma_0_axi_aclk` *clock-group* total,
> which is 23 `layer_0` + 3 `seq_0` — see §5.) **§5 is authoritative for the
> shipped netlist**; do not quote this section as a property of what ships.
> On the R4/R6 watch-items specifically:
> neither the scales mux nor the EMB barrel shift appears in **either of the two
> worst violating paths** on the shipped roll. That is the limit of what the
> summary proves — `report_timing_summary` lists only the worst path per group,
> so the remaining 48 of 50 failing endpoints are not individually enumerated
> here. Treat R4/R6 as "not implicated at the top of the violation set", not as
> "proven absent from all 50 endpoints".

## 3. Closure campaign

Scope was held to **Tier 1 / placement-level**. RTL changes would invalidate
R-b's sim coverage and the frozen interface contract, so they were treated as
escalation material, not autonomous moves.

### Spread — plain reroll (`launch_reroll.sh`, no phys_opt)

| directive | WNS | WHS |
|---|---|---|
| **Explore** | **−0.214** | +0.004 |
| ExtraTimingOpt | −0.316 | +0.009 |
| AltSpreadLogic_medium | −0.377 | +0.010 |
| SSI_SpreadLogic_high | −0.533 | +0.010 |

Lottery reversal, as this project has seen before: 033's winner
(AltSpreadLogic_medium, +0.009) placed *third* here; Explore, 033's second-worst,
won. **Directive choice does not transfer between builds.**

### Iteration 1 — post-route phys_opt on Explore (`out_build_034_po1`)

| step | WNS | WHS | gain |
|---|---|---|---|
| PASS0 (as routed) | −0.214 | +0.004 | — |
| + `AggressiveExplore` | **−0.134** | 0.000 | **+0.080** |
| + `AlternateReplication` | −0.134 | 0.000 | +0.000 |
| + `AggressiveFanoutOpt` | −0.134 | 0.000 | +0.000 |
| + `route_design -preserve` | −0.134 | 0.000 | +0.000 |

Saturated after one directive. ~2h04m.

### Iteration 2 — full recipe (`out_build_034_po2_*`) — **the shipping roll**

| directive | recipe | WNS | WHS |
|---|---|---|---|
| **AltSpreadLogic_high** | full | **−0.025** | **+0.001** |
| Explore | full | −0.114 | +0.001 |
| ExtraNetDelay_high | full | −0.706 | +0.002 |

Explore went **−0.214 → −0.114 (+0.100) on an identical netlist and placer
directive**, an exact isolated measurement of the two phys_opt stages.
AltSpreadLogic_high reached **−0.025**. (It has no plain-reroll counterpart, so
no same-directive delta can be computed for it — see §7 finding 1; do not compare
it against AltSpreadLogic_medium's plain roll, which is a different directive.)
`ExtraNetDelay_high` backfired (−0.706) despite targeting net delay.

### Iteration 3 — more phys_opt on the −0.025 checkpoint (`out_build_034_po3`)

| step | WNS | WHS |
|---|---|---|
| PASS0 | −0.025 | +0.001 |
| + `AlternateReplication` | −0.025 | +0.001 |
| + `AggressiveFanoutOpt` | −0.025 | +0.001 |
| + `Explore` | −0.025 | +0.001 |

**Three independent directives returned bit-identical slack.** The remaining
0.025 ns is not reachable by physical optimization of this placement — only by a
different placement. The WHS abort guard (see §7 finding 5) applied to **this
iteration only** and never tripped.

### Iteration 4 — last unplayed placement cards (`out_build_034_po4_*`)

| directive | recipe | WNS | WHS |
|---|---|---|---|
| AltSpreadLogic_medium | full | −0.321 | 0.000 |
| SSI_SpreadLogic_high | full | −0.493 | +0.004 |

Both lost. 033's winning directive under the full recipe still lands −0.321,
reconfirming that directive choice does not transfer. **Campaign ended here.**

### Campaign summary

| stage | lever | best WNS |
|---|---|---|
| base | build_034 as built | −0.369 |
| spread | 4 plain rerolls | −0.214 |
| iter 1 | post-route phys_opt | −0.134 |
| **iter 2** | **full recipe (both phys_opt stages)** | **−0.025** |
| iter 3 | 3 further phys_opt directives | −0.025 (zero gain) |
| iter 4 | 2 further placement directives | −0.321 |

## 4. Utilization

Device-wide, build_034 vs build_033 — **the R-b prediction lands exactly**:

| resource | 033 | 034 | delta |
|---|---|---|---|
| Block RAM Tile | 560.5 (25.95%) | 576.5 (26.69%) | **+16.0 — exactly as predicted** |
| RAMB36/FIFO | 543 | 561 | +18 |
| RAMB18 | 35 | 31 | −4 (nets to +16.0 tiles) |
| URAM | 348 (36.25%) | 348 (36.25%) | **0** |
| DSPs | 1858 (27.16%) | 1858 (27.16%) | **0** |
| CLB LUTs | 266889 (22.57%) | 279051 (23.60%) | +12162 |
| — LUT as Distributed RAM | 31156 | 33724 | +2568 (the R4 LUTRAM) |
| CLB Registers | 276573 (11.70%) | 285186 (12.06%) | +8613 |
| CARRY8 | 11687 | 11693 | +6 |

**Correction to the planning expectation.** The plan expected SLR1 BRAM
≈ 519.5 tiles / ~72.4% against a 70.21% baseline. **That did not happen: SLR1
Block RAM is 16.25%.** The placer *mirrored the design across SLR1↔SLR2* —
URAM and DSP counts swap exactly between the two SLRs, proving a placement
mirror rather than a resource change:

| | 033 SLR1 | 033 SLR2 | 034 SLR1 | 034 SLR2 |
|---|---|---|---|---|
| Block RAM Tile | **505.5 (70.21%)** | 29.5 (4.10%) | 117 (16.25%) | **434 (60.28%)** |
| URAM | 123 (38.44%) | 225 (70.31%) | **225** | **123** |
| DSPs | 739 | 1116 | **1116** | **739** |
| CLB | 37531 (76.19%) | 14295 (29.02%) | **39246 (79.67%)** | 13994 (28.41%) |

The meaningful number is the **device-wide +16.0 BRAM tiles**. The per-SLR
percentage is a placement artifact and should not be quoted as a result.
**SLR1 CLB occupancy 76.19% → 79.67%** is the highest per-SLR pressure in the
design and the figure worth tracking.

### Chosen roll utilization

Regenerated from the shipping checkpoint itself
(`bd_wrapper_postroute_physopt.dcp`), **not** inherited from the base roll —
phys_opt replicates logic, so the shipped netlist genuinely differs:

| resource | 034 base | **chosen roll** | chosen-roll vs base-roll netlist delta |
|---|---|---|---|
| CLB LUTs | 279051 (23.60%) | **277965 (23.51%)** | **−1086** |
| CLB Registers | 285186 (12.06%) | **287372 (12.15%)** | **+2186** |
| CARRY8 | 11693 | 11693 | 0 |
| Block RAM Tile | 576.5 (26.69%) | 576.5 (26.69%) | 0 |
| URAM | 348 (36.25%) | 348 (36.25%) | 0 |
| DSPs | 1858 (27.16%) | 1858 (27.16%) | 0 |

−1086 LUTs / +2186 registers is the classic replication signature. NB the two
rolls differ in **both** placer directive (AltSpreadLogic_high vs Explore) **and**
the two phys_opt stages, so this delta is not attributable to phys_opt alone. Memory and
DSP counts are untouched, as expected — physical optimization cannot change them.

Chosen roll vs **build_033** (the headline delta for R-b):

| resource | 033 | chosen roll | delta |
|---|---|---|---|
| Block RAM Tile | 560.5 (25.95%) | 576.5 (26.69%) | **+16.0 — exactly as predicted** |
| URAM | 348 | 348 | 0 |
| DSPs | 1858 | 1858 | 0 |
| CLB LUTs | 266889 | 277965 | +11076 |
| CLB Registers | 276573 | 287372 | +10799 |
| CARRY8 | 11687 | 11693 | +6 |

Chosen roll per-SLR (note the SLR1↔SLR2 mirror described above):

| site type | SLR0 | SLR1 | SLR2 | SLR1 % |
|---|---|---|---|---|
| CLB | 3624 | 39351 | 14744 | **79.88%** |
| CLB LUTs | 15514 | 190761 | 71690 | 48.41% |
| CLB Registers | 21766 | 201823 | 63783 | 25.61% |
| Block RAM Tile | 25.5 | 117 | 434 | 16.25% |
| URAM | 0 | 225 | 123 | 70.31% |
| DSPs | 3 | 1116 | 739 | 48.95% |

**SLR1 CLB occupancy 79.88%** (base roll 79.67%, build_033 76.19%) — the highest
per-SLR pressure in the design and the figure to track on the next build.

## 5. Chosen-roll artifacts

Shipping roll: `synth/out_build_034_po2_AltSpreadLogic_high`, WNS **−0.025** /
WHS **+0.001**, netlist/VERSION CSR **`4f908df2`**.

| artifact | path (under `proj/stage1.runs/impl_1/`) | mtime |
|---|---|---|
| **bitstream** | `bd_wrapper.bit` (50,115,049 B) | 2026-08-14 17:50:51 |
| final checkpoint | `bd_wrapper_postroute_physopt.dcp` | 2026-08-14 17:43:16 |
| routed (pre post-route phys_opt) | `bd_wrapper_routed.dcp` | 2026-08-14 17:03:24 |
| post-place phys_opt | `bd_wrapper_physopt.dcp` | 2026-08-14 15:52:42 |
| placed | `bd_wrapper_placed.dcp` | 2026-08-14 14:46:15 |
| opt | `bd_wrapper_opt.dcp` | 2026-08-14 13:11:11 |

**Stale-artifact check passes:** timestamps are strictly monotonic through the
flow and the `.bit` (17:50:51) **post-dates the final post-route-phys_opt
checkpoint** (17:43:16), so the bitstream is built from exactly the −0.025
netlist — not from the pre-phys_opt routed design.

Reports in `reports/` were regenerated directly from
`bd_wrapper_postroute_physopt.dcp` (see §7 finding 3).

### Shipped-roll failing-path census — AUTHORITATIVE

Design summary: **WNS −0.025, TNS −0.613, 50 failing endpoints** of 1,193,865;
**WHS +0.001, THS 0.000, 0 failing hold endpoints** of 1,190,729; WPWS 0.000,
0 pulse-width failures.

Intra-clock table, all six clocks (`reports/timing_summary.rpt`):

| clock | period | freq | WNS | TNS | failing EP | total EP |
|---|---|---|---|---|---|---|
| mmcm_clkout0 (ch0 UI) | 3.332 | 300.12 MHz | +0.006 | 0.000 | **0** | 156437 |
| mmcm_clkout0_2 (ch1 UI) | 3.332 | 300.12 MHz | +0.004 | 0.000 | **0** | 156016 |
| **mmcm_clkout0_3 (ch2 UI)** | 3.332 | 300.12 MHz | **−0.025** | −0.457 | **24** | 156168 |
| **mmcm_clkout0_1 (ch3 UI)** | 3.332 | 300.12 MHz | **+0.001** | 0.000 | **0** | 156382 |
| pipe_clk | 4.000 | 250 MHz | +0.762 | 0.000 | **0** | 4764 |
| **xdma_0_axi_aclk** | 4.000 | 250 MHz | **−0.011** | −0.156 | **26** | 519442 |

24 + 26 = **50**, reconciling exactly with the design summary.

The three violating path classes (worst path of each shown):

| class | slack | EP | levels | path |
|---|---|---|---|---|
| **A — matvec_engine, ch2** | **−0.025** | 24 | 5 (LUT3=1 LUT6=4) | `bd_i/mvchan_2/inst/u_chan/u_engine/r_g_reg[3]/C` → `bd_i/mvchan_2/inst/u_chan/u_engine/xline_q0_reg[11]__14/CE` |
| **B — `layer_0`** (`u_dn` 18, `u_topk`+loose 5) | **−0.011** | **23** | worst 5 (LUT6=2 MUXF7=2 MUXF8=1); mode 2 | `bd_i/layer_0/inst/u_core/u_dn/oi_reg[0]_rep__6/C` → `bd_i/layer_0/inst/u_core/u_dn/o_sel_reg[21]/D` |
| **C — `seq_0` MOV addressing** | −0.010 | **3** | 6 (all three) | 3 endpoint pins (not a src→dst pair): `bd_i/seq_0/inst/u_seq/mv_wbase_reg[33]/CE`, `…/u_seq/u_mov/yf_cnt_reg[0]/CE`, `…/yf_cnt_reg[1]/CE` |

#### Proven per-endpoint attribution (all 50 enumerated)

The summary above lists only the worst path per group. To settle attribution
with evidence rather than inference, every failing endpoint was enumerated from
the shipped checkpoint (`get_timing_paths -slack_lesser_than 0`, count = 50,
reconciling with the design summary). Raw output:
**`evidence/qwen2b/rb/shipped_roll_endpoint_census.log`**
(script `synth/scripts/census_034_shipped.tcl`).

> **Reading the archived log:** its trailing `SPLIT` lines label the field
> `route=`, but that value is Vivado's `DATAPATH_DELAY` — the **total** datapath
> delay (logic + route). True route = datapath − logic, e.g. class A
> `3.113 − 0.399 = 2.714 ns (87.2%)`, which is the figure quoted in §6. The
> script's format string has since been corrected; the committed log is left
> as-generated and stays reconcilable via that subtraction. Note also that both
> `SPLIT` lines are **class A** (the two worst paths overall), so class B's
> split is not in this log — it is preserved separately in
> `evidence/qwen2b/rb/shipped_classB_path_excerpt.rpt`.

| owner | EP | clock group | slack range |
|---|---|---|---|
| `bd_i/mvchan_2/inst/u_chan/u_engine` | **24** | mmcm_clkout0_3 (ch2, 300 MHz) | −0.025 … −0.007 |
| `bd_i/layer_0/inst/u_core/**u_dn**` | **18** | xdma_0_axi_aclk (250 MHz) | −0.011 … −0.001 |
| `bd_i/layer_0/inst/u_core/u_topk` | 2 | xdma_0_axi_aclk | |
| `bd_i/layer_0/inst/u_core/dn_rdq_reg[2021]` | 1 | xdma_0_axi_aclk | |
| `bd_i/layer_0/inst/u_core/dn_layer_r_reg[2]_rep__28` | 1 | xdma_0_axi_aclk | |
| `bd_i/layer_0/inst/u_core/s_axil_rdata_reg[1]` | 1 | xdma_0_axi_aclk | |
| `bd_i/seq_0/inst/u_seq/mv_wbase_reg[33]/CE` | 1 | xdma_0_axi_aclk | −0.010 |
| `bd_i/seq_0/inst/u_seq/u_mov/yf_cnt_reg[0,1]/CE` | 2 | xdma_0_axi_aclk | −0.003, −0.002 |
| **total** | **50** | | |

Per clock group: mmcm_clkout0_3 = 24 (all `mvchan_2`); xdma_0_axi_aclk = 26
(**23 `layer_0` + 3 `seq_0`**).

**CONFIRMED: 100% of failing endpoints are custom RTL.** Zero endpoints in
`ddr4_*`, `xdma_*`, `axi_smc` or `smc_ch*` — no vendor IP violates on the
shipped roll.

**CORRECTED: `layer_0` carries 23, not 26.** An earlier revision quoted 26,
which is the *clock-group* total for `xdma_0_axi_aclk`; that group is 23
`layer_0` + **3 `seq_0`**, and the `seq_0` endpoints were previously
unreported entirely. `layer_0`'s 23 are also not all `dn_step`: 18 are `u_dn`,
2 `u_topk`, 3 loose registers. **None of this changes the accepted magnitudes**
(WNS −0.025, TNS −0.613, 50 endpoints) or the waiver decision.

Historical echo worth noting: build_030's census was recorded as *"diffuse
layer_0 congestion, only 3/999 in seq_0"* — the same 3-endpoint `seq_0` tail
appears here.

Class A is internal to `matvec_engine` on channel 2; the dominant class-B block
is `layer_0`'s `dn_step` (the MUXF7/MUXF8 pair is a wide output-select mux),
i.e. **migrated logic**.

Note class A's endpoint family: `xline_q0_reg[*]/CE` is the same family that
drove build_033's −0.344 path (`mvchan_0/u_engine/xline_q0_reg[28]__18/CE`) —
a recurring critical structure in `matvec_engine` across builds, not new to R-b.

**The DDR4 `wr_buffer_ram` / SmartConnect class that dominated the base and
Explore rolls does not violate on the shipped roll at all** — the full-recipe
placement plus both phys_opt stages resolved it. `mmcm_clkout0_1` (ch3, the
domain that class lived in) finishes at **+0.001 with zero failing endpoints**.

## 6. WAIVER — WNS −0.025 accepted (re-affirmed on corrected rationale)

**Status: ACCEPTED by USER DECISION, 2026-08-16, re-affirmed the same day
against the corrected technical rationale below.** This waiver documents the
engineering basis; the decision itself was the user's, not this agent's.

**Two-prompt provenance — both recorded because the first was decided on facts
this document later found to be wrong:**

1. **Original acceptance (superseded rationale).** The user decided
   interactively in the controller session on 2026-08-16, selecting "Accept
   −0.025 with waiver" from an explicit three-option prompt
   (accept-with-waiver / keep-iterating / hold-for-gate-D) stating the WNS, the
   hold margin, the failing-path class and the exhausted playbook. **The
   failing-path class in that prompt was wrong** — it named the Xilinx DDR4 MIG
   on channel 3, which in fact *met* timing on the shipped roll.
2. **Re-affirmation (corrected rationale) — the operative decision.** After the
   §5 census corrected the record, the waiver was re-put to the user in a second
   interactive three-option prompt (re-affirm / targeted-fix-first / hold),
   stating: ch3 closed at +0.001 with zero failing endpoints; the real
   violations are `matvec_engine` ch2 −0.025 × 24 EP and `dn_step` in `layer_0`
   −0.011 × 26 EP on the 250 MHz domain, **all custom logic**; hold
   non-negative; the bit-exact
   ladder as arbiter; and the build_028 −0.106 precedent. **The user chose
   re-affirm.** The controller's ledger carries both records.

Rationale (as put to the user in the second prompt):

1. **Small, bounded violation set.** 50 failing endpoints of 1,193,865
   (0.0042%), TNS −0.613 ns total, in a small number of related path classes.
   *(As put to the user this said "exactly two classes"; the later per-endpoint
   census resolved it to **three** — A `mvchan_2` 24, B `layer_0` 23, C `seq_0`
   3, §5. Magnitudes and the 50-endpoint total are unchanged, so the decision
   basis is unaffected.)*
   Four of the six clocks meet timing outright, including all three other DDR4
   UI domains.
2. **The failing logic is custom RTL, in a few well-understood blocks.**
   *(As presented to the user this said "two blocks"; the per-endpoint
   census resolved it to three — the 23+3 `layer_0`/`seq_0` split is
   decomposed below and enumerated in §5. Magnitudes unchanged.)*
   Class A (−0.025, 24 EP) is internal to `matvec_engine` on channel 2, in the
   `xline_q0_reg[*]/CE` family — the *same* structure that was build_033's
   −0.344 critical path, i.e. a long-standing hot spot rather than something
   R-b introduced. Class B (−0.011, 26 EP on `xdma_0_axi_aclk` — **23
   `layer_0` + 3 `seq_0`**, per the §5 per-endpoint census) is dominated by
   `layer_0`'s `dn_step`
   output-select mux. **This is migrated logic and it does violate** — see the
   residual-risk paragraph.
3. **WHS is non-negative** (+0.001) with **0 failing hold endpoints** and 0
   pulse-width failures. Hold was *measured* non-negative at every step; note it
   was only *enforced* by an abort guard in iteration 3 (§7 finding 5), so on
   the shipped roll +0.001 is an outcome, not a constraint the flow guaranteed.
4. **Magnitude is picoseconds.** −0.025 ns against 3.332 ns is **0.75%** of the
   period; −0.011 ns against 4.000 ns is **0.28%**.
5. **Precedent — this project has shipped negative WNS three times, all
   hardware-clean, and two of them on this very clock domain.**

   | build | shipped WNS | hardware result | domain |
   |---|---|---|---|
   | `build_026_rr_AltSpreadLogic_medium` (07ffc7b9) | **−0.142** | **24/24 runs bit-exact** (`docs/HISTORY.md:1214`) | 250 MHz axi_aclk |
   | `build_030_rr_AltSpreadLogic_medium` (9e1e0bae) | **−0.141** | rung-1 gate + **26/26** host ladder, board-resident (`docs/HISTORY.md:1099,1121`) | 250 MHz axi_aclk |
   | `build_028_rr_SSI_HighUtilSLRs` (67a943bd) | **−0.106** | **HW 34/34, 0 errors** (`docs/HISTORY.md:1185`) | — |

   build_030 was accepted with exactly this reasoning recorded at the time:
   *"== build_026's shipped −0.142, same axi_aclk domain, bit-exact at 250 MHz
   precedent"*. Our class-B `dn_step` violation is **−0.011 on that same
   250 MHz `xdma_0_axi_aclk` domain — 13× smaller than either precedent**, and
   class A is −0.025, 5.7× smaller. build_030's census was also recorded as
   *"diffuse layer_0 congestion"*, so a `layer_0`-resident violation is itself
   precedented. For contrast (and to keep the record straight): build_033
   shipped at **+0.009 — passing** — and build_032 closed at **0.000 flat**;
   neither is a negative-WNS precedent and neither should be cited as one.
6. **A real failure would be detectable, not silent.** The R9 hardware ladder is
   bit-exact against the reference model, so a genuine setup failure on either
   class manifests as a **mismatch the gate catches**, not as quiet numerical
   degradation.

**Residual risk, stated plainly.** These are real setup violations, not rounding
artifacts, and — contrary to this document's earlier revision — **they are in our
own logic, including the migrated `layer_0` block**:

- **Class A — `mvchan_2/u_chan/u_engine`, 24 EP, −0.025…−0.007.** Could corrupt
  `xline_q0` capture on channel 2 under worst-case PVT. R9 should exercise
  **channel-2 traffic specifically** and compare against ch0/1/3, which all meet
  timing — **an asymmetry between ch2 and the other three is the signature.**
- **Class B — `layer_0/u_core/u_dn` (18 EP) + `u_topk` (2) + 3 loose regs,
  −0.011…−0.001.** Could mis-select a `dn_step` output. R9 should watch
  **`dn_step` behavior** and, secondarily, **top-k selection**. On the 250 MHz
  domain at −0.011 (0.28% of period) this is the lower-probability class, but it
  is inside migrated logic.
- **Class C — `seq_0/u_seq`, 3 EP: `mv_wbase_reg[33]/CE` (−0.010) and
  `u_mov/yf_cnt_reg[0,1]/CE` (−0.003, −0.002).** Not previously reported. Small
  but non-zero: a `mv_wbase` mis-capture would affect MOV base addressing, so R9
  should include a **sequencer MOV addressing** check.

The campaign spent 4 iterations and ~14 h; remaining levers are outside the
proven set (see below).

**Untried options, deliberately not taken:**
- A pblock / soft floorplan for the `smc_ch3`↔`ddr4_3` region. **The design has
  no pblocks at all** (verified: no `create_pblock` anywhere in
  `synth/constraints/`), which is exactly why WNS swings so widely between rolls.
  This is the highest-leverage remaining lever but is outside the proven set.
- MIG IP reconfiguration — **no longer relevant**: on the shipped roll no vendor-IP
  path violates at all (§5). This mattered only for the base/Explore rolls.
- RTL pipelining — **not applicable, but for the route reason, not a depth
  reason** — and the depth argument is *weaker* than the earlier "2 logic
  levels" claim suggested, not stronger. Per the census: class A is uniformly
  **5 levels** across all 24 endpoints; class B's worst path is 5 but its 23
  endpoints range **0–11 levels with a mode of 2**; class C is 6. So depth
  varies, and no single pipelining target exists. What is uniform is that the
  delay is overwhelmingly **routing**: class A
  `logic 0.399 ns (12.8%) / route 2.714 ns (87.2%)`, class B
  `logic 0.311 ns (7.95%) / route 3.599 ns (92.0%)`
  (`evidence/qwen2b/rb/shipped_classB_path_excerpt.rpt`). Pipelining subdivides
  the **logic** term, which is already only 8–13% of the path; even eliminating
  it entirely would leave 87–92% of the delay untouched. The conclusion holds
  *a fortiori*: pipelining cannot buy the missing picoseconds.

## 7. Reusable process findings

**1. `reroll_impl.tcl` enables neither phys_opt stage — worth +0.040…+0.100 ns/roll (n=3).**
It sets only `STEPS.PLACE_DESIGN.ARGS.DIRECTIVE`, leaving both
`STEPS.PHYS_OPT_DESIGN` (post-place) and `STEPS.POST_ROUTE_PHYS_OPT_DESIGN`
off. Only three directives were run **both** ways, so only these three yield a
valid same-directive measurement:

| directive | plain reroll | full recipe | gain |
|---|---|---|---|
| Explore | −0.214 | −0.114 | **+0.100** |
| AltSpreadLogic_medium | −0.377 | −0.321 | **+0.056** |
| SSI_SpreadLogic_high | −0.533 | −0.493 | **+0.040** |

**Honest range: +0.040…+0.100 ns, n=3.** An earlier revision of this document
(and the commit message of `b8a221d`) claimed "0.100–0.352"; **that figure is
superseded and should not be quoted.** The 0.352 came from comparing
AltSpreadLogic_**high** (full) against AltSpreadLogic_**medium** (plain) — two
*different* directives, so it conflates the directive change with the phys_opt
change and is not a valid measurement of either. Every reroll in this project's
history has still left this real +0.040…+0.100 on the table.
New `synth/scripts/full_impl.tcl` + `launch_po2.sh` implement the full recipe:

```
place_design -directive <D>
  STEPS.PHYS_OPT_DESIGN.IS_ENABLED            true   (post-place)
route_design
  STEPS.POST_ROUTE_PHYS_OPT_DESIGN.IS_ENABLED true   (post-route)
```

**2. `cp -a` can hang indefinitely on this NFS mount — use `rsync -a`.**
Observed 2026-08-15: `cp -a` of the 1708 MB project ran **62 minutes and copied
3.7 MB** (96 read syscalls), asleep in `handle_async_copy`. Coreutils `cp` uses
`copy_file_range()`, which this mount offloads server-side; the offload wedged.
NFS metadata was responsive, 21 T free, load normal. `rsync -a` did the same copy
in **875 MB / 40 s**. `launch_po2.sh` now uses rsync.
**`synth/scripts/launch_reroll.sh:34` still uses `cp -a` and carries the same
latent hang** — a stalled reroll is indistinguishable from a slow one, so this
can silently burn hours. Recommend the same fix.

**3. Parallel jobs raced their reports into one directory.** `full_impl.tcl`
originally derived the output dir with three `dirname` levels from
`<out>/proj/stage1.xpr`, landing reports in `synth/reports/` where all five
full-recipe jobs overwrote each other last-writer-wins — reports that described
a *different roll* than the directory implied. Fixed to two levels; the stray
`synth/reports/` was deleted and the chosen roll's reports regenerated directly
from its own final checkpoint.

**4. Vivado placer directive names are case-sensitive.**
`docs/HISTORY.md:1191` and the `fpga-tooling-reference` skill appeared to
contradict each other on `SSI_SpreadLogic_high`. The build log settles it:
`INFO: [Vivado_Tcl 4-2302] The placer was invoked with the 'SSI_SpreadLogic_high'
directive.` + `place_design completed successfully`, 0 errors. **Lowercase
`SSI_SpreadLogic_high` is valid; the capitalised `SSI_SpreadLogic_High` is not.**
`SpreadLogic_high` and `SSI_ExtraTimingOpt` remain on HISTORY.md's empirical
do-not-use list and were avoided.

**5. The WHS abort guard covered iteration 3 only — not the shipped roll.**
`po3_physopt.tcl` is the only script that aborts on `WHS < 0`
(`if {$h < 0} { … break }`). `full_impl.tcl` — which produced the **shipped**
bitstream — and `po1_physopt.tcl` only *print* WHS; neither enforces it. So the
shipped roll's **WHS +0.001 is a measured outcome, not a constraint the flow
guaranteed**. Any future run that leans on hold margin should put the guard in
`full_impl.tcl`, since that is the script that builds what ships.

**6. Re-census the SHIPPED roll, never a predecessor.** This document's first
revision derived its waiver rationale from the base/Explore censuses, which had
a completely different failing-path profile (DDR4 MIG ch3, vendor IP) from the
roll actually shipped (custom RTL, ch2 + `layer_0`). Placement changes *which
paths fail*, not just by how much. **Any claim about what ships must be derived
from the shipped checkpoint's own report** — the earlier claims were wrong in
both load-bearing assertions and would have pointed R9's hardware validation at
the one clock domain that met timing.

**7. Anchor `grep` when scanning Vivado logs.** Vivado echoes the sourced TCL
with a `# ` prefix, so `grep FATAL create.log` matches `puts "FATAL: …"` *source*
lines and produces false positives. Use `grep -E '^(FATAL:|ERROR:)'`.

**8. `CLOCK_GATE_OK` is a post-implementation gate**, emitted at
`synth/scripts/build.tcl:42` after `wait_on_run impl_1` — not an early gate. The
in-flight order is
`CREATE_PROJECT_OK` → synth → impl → `CLOCK_GATE_OK` → `TIMING:` → `BITSTREAM:` → `BUILD_OK`.

## 8. BD regeneration check (R5 assertion, zero sim coverage)

The one R-b file with no sim coverage is `rtl/layer_chan_ipi.v`; its risk was
silent address truncation through IPI. **Green, four independent ways:**

1. **R5 range assertion passed.** `create_project.tcl:416-433` asserts `layer_0`
   → 131072 / "128K", `exit 1` on mismatch. Fail-closed, so the proof is that
   execution reached `ADDRESS MAP:` (create.log:568) and `CREATE_PROJECT_OK`
   (create.log:707).
2. **Printed address map:** `/seq_0/m_axib/SEG_layer_0_reg0 off=0x00060000
   range=0x00020000` (128 KiB at 0x6_0000), mvchans at 0x1–0x4_0000 range
   0x10000, and `0x5_0000–0x5_FFFF` left a decode hole as designed.
3. **BD object model:** `bd.bd` `layer_0/s_axib` `ADDR_WIDTH = '17'` (constant).
4. **Generated netlist — decisive:** `bd.v` has
   `wire [16:0] burst_slice_4_M_AXI_AW/ARADDR` wired straight into
   `layer_0.s_axib_*addr`, while `burst_slice_{0..3}` are `wire [15:0]`. The
   17-bit width is *derived per-MI*, not accidental uniformity. **No truncation.**

BD critical-warning delta vs build_033: **zero** (11 in both, identical set —
all pre-existing AXI-Lite `MAX_BURST_LENGTH` cosmetics).

`SYNTHESIS` macro handling verified in
`bd_layer_0_0_synth_1/runme.log` (the OOC run that actually synthesizes
`layer_chan`): 0 `$fatal` / "unsupported system task" mentions, 0 errors, and no
`-verilog_define` is passed — matching build_033's known-good baseline. Both
`ifndef SYNTHESIS` blocks in `layer_chan.sv` contain only `$fatal` assertions
inside `always_ff`, so the synthesized netlist is identical either way.
