# R-c TIMING GATE — build_035 (W8 everywhere) + closure campaign (2026-08-22 → 08-23)

Tree: `54443b9f` on branch `qwen2b`, **clean at launch** (`git status --short`
empty). `launch_build.sh` stamps VERSION from `git rev-parse --short=8 HEAD`, so
the **netlist hash / VERSION CSR expectation is `54443b9f`** — verified in the
BD object model (`bd.bd` `csr_0` `VERSION = 0x54443b9f`), not merely assumed
from the launch banner.

> `54443b9f` is `790fef5`'s RTL plus the synth-script follow-ons committed
> immediately before launch (rsync/full-recipe/WHS gate/census, §10). **No RTL
> moved between the two.** The netlist is T1's W8 engine mode + T4's `cfg_len`
> 13-bit widening, exactly as the R-c sim gate proved it.

---

## 0. VERDICT — NOT CLOSED. ESCALATION, NOT A WAIVER I CAN TAKE

> ⚠ **SUPERSEDED — see §13. THE DESIGN IS NOW CLOSED.** This section is the
> dated verdict of 2026-08-23, when the campaign had reached −0.136 and the
> floorplan and vendor-exception work had not happened. It is preserved as the
> record that produced the escalation, not as current state. **Current state:
> WNS 0.000 / WHS 0.000, zero failing endpoints, no waiver — §13.** Read §0–§12
> as the history; read §13 for what ships.

**Best achieved: WNS −0.136 ns / WHS +0.001 ns**
(`synth/out_build_035_full_AltSpreadLogic_high`, the only best-roll with a
bitstream). A further phys_opt pass reaches **−0.132 / +0.001**
(`synth/out_build_035_po`) but **writes no bitstream** — its script only emits
one on closure.

The build_034 waiver **does not carry**, and this is not a re-affirmation
request dressed up as one. Three facts make it a genuinely new decision:

1. **The magnitude moved 5.4×** — −0.025 → −0.136.
2. **The failing set moved 55×** — 50 endpoints → **2,773**; TNS −0.613 →
   **−132.442**.
3. **The waiver's own subject changed.** The 034 waiver covered
   `matvec_engine` on the ch2 DDR UI domain. On build_035 **ch2 meets timing
   with zero failing endpoints** and the WNS driver is `layer_0` on the
   250 MHz `xdma_0_axi_aclk` domain. Vendor IP also violates for the first
   time (233 endpoints, §6) — 034 shipped 100% custom-RTL violations.

**The campaign is exhausted at the proven-lever level**: 7 placement
directives under the full recipe, plus a 4-directive phys_opt playbook that
saturated (§5). What remains is outside the proven set (floorplan, RTL
resize) and is a design decision, not a re-roll. **§9 states the options and
my recommendation; the user decides.**

**Nothing about this is a fidelity or correctness finding.** The W8 datapath
is bit-exact per the R-c sim gate, and — see §7 — the W8 CE cone the sketch
worried about actually got *faster*. This is a **capacity/floorplan** result.

---

## 1. In-flow gates — all green

| gate | where | result |
|---|---|---|
| `CREATE_PROJECT_OK` | `out_build_035/create.log:709` | ✅ |
| R5 layer_0 range assertion | fail-closed; reaching `ADDRESS MAP:` (create.log:569) proves it | ✅ 131072 / "128K" |
| BD window | `/seq_0/m_axib/SEG_layer_0_reg0 off=0x00060000 range=0x00020000` | ✅ 128 KiB @ 0x6_0000 |
| BD object model | `bd.bd` `layer_0/s_axib ADDR_WIDTH = '17'` (constant) | ✅ |
| Generated netlist | `bd.v` `burst_slice_4_M_AXI_AR/AWADDR` = `[16:0]`; `burst_slice_{0..3}` = `[15:0]` | ✅ width derived per-MI, no truncation |
| BD critical warnings | 11, **set byte-identical to build_034's** (diff empty) | ✅ no new CW |
| `SYNTHESIS` predefine | `bd_{mvchan_0,layer_0,seq_0}_0_synth_1/runme.log`: 0 `$fatal` / "unsupported system task", 0 `^ERROR`, no `-verilog_define` | ✅ |
| `CLOCK_GATE_OK` | post-impl, `build_run.log` | ✅ `pipe_clk xdma_0_axi_aclk` |
| `BUILD_OK` | `build_run.log` | ✅ |

On the `SYNTHESIS` predefine: the test is fail-loud, not decorative. R-c added a
**new** `ifndef SYNTHESIS` block at `rtl/matvec_engine.sv:704` containing
`$fatal` inside `always_ff`. Had Vivado *not* predefined `SYNTHESIS`, that block
would have been compiled and produced "unsupported system task" messages. Zero
such messages across all three OOC runs ⇒ the guards were excluded, matching
build_034's known-good baseline.

Base-roll wall: 20:01 → 23:45 = **3 h 44 m** (build_034: 3 h 31 m).

## 2. Campaign

Every roll below used the **FULL recipe** (`full_impl.tcl` via `launch_po2.sh`):
`place -directive D` → post-place `phys_opt` → `route` → post-route `phys_opt`,
both phys_opt stages `AggressiveExplore`. The phys_opt-less reroll flow was not
used and is no longer reachable (§10).

| roll | lever | WNS | WHS | bitstream |
|---|---|---|---|---|
| `out_build_035` | base, default impl strategy | −0.480 | +0.004 | yes |
| **`…_full_AltSpreadLogic_high`** | **full recipe** | **−0.136** | **+0.001** | **yes** |
| `…_full_WLDrivenBlockPlacement` | full recipe | −0.178 | 0.000 | yes |
| `…_full_Explore` | full recipe | −0.256 | +0.001 | yes |
| `…_full_ExtraPostPlacementOpt` | full recipe | −0.275 | 0.000 | yes |
| `…_full_AltSpreadLogic_medium` | full recipe | −0.318 | +0.001 | yes |
| `…_full_AltSpreadLogic_low` | full recipe | −0.377 | 0.000 | yes |
| `…_full_SSI_HighUtilSLRs` | full recipe | −1.211 | +0.001 | yes |
| `out_build_035_po` | 4 phys_opt directives on ASLh + `route -preserve` | **−0.132** | +0.001 | **no** |

Raw gate lines: `t5_06_campaign_timing_lines.log`.

**Directive choice still does not transfer, and still is not the problem.**
`AltSpreadLogic_high` won on 034 *and* on 035 — the first time a directive has
repeated in this project — but the spread top-to-bottom is 1.075 ns
(−0.136 … −1.211) and the winner is still 0.136 short. `SSI_HighUtilSLRs`, the
directive whose entire purpose is high-SLR-utilisation designs and which won
build_028, came **last by a factor of 9**.

### Base-vs-base: the regression is visible before any directive is chosen

| metric | 034 base | 035 base | delta |
|---|---|---|---|
| WNS | −0.369 | **−0.480** | −0.111 worse |
| TNS | −260.187 | **−2076.719** | **7.98× worse** |
| TNS failing endpoints | 3,703 | **16,677** | **4.50× more** |
| WHS | +0.010 | +0.004 | worse, still positive |
| THS failing endpoints | 0 | 0 | — |
| router congestion | level 5 (32×32) | **level 6 (64×64)** | worse |
| router global iterations | 4 | 6 | more effort needed |

Vivado's own note on the congestion line: *"Congestion levels of 5 and greater
may impact timing closure."* 034 sat exactly at the threshold; 035 is past it.

## 3. The phys_opt playbook — saturated, as it did on 034

`synth/scripts/po_035.tcl` on the ASLh post-route checkpoint, with the same
hold-abort guard `po3_physopt.tcl` used (WHS margin is only +0.001):

| step | WNS | WHS | gain |
|---|---|---|---|
| PASS0 (as shipped by full recipe) | −0.136 | +0.001 | — |
| + `AlternateReplication` | **−0.132** | +0.001 | **+0.004** |
| + `AggressiveFanoutOpt` | −0.132 | +0.001 | +0.000 |
| + `Explore` | −0.132 | +0.001 | +0.000 |
| + `AggressiveExplore` | −0.132 | +0.001 | +0.000 |
| `route_design -preserve` (PO035_FINAL) | −0.132 | +0.001 | +0.000 |

**Four independent directives, +0.004 total.** Identical shape to build_034's
iteration 3 (three directives, bit-identical slack, zero gain). The hold guard
never tripped. Log: `t5_05_physopt_playbook_035.log`.

This is the same conclusion 034 reached and it is worth restating plainly:
**the residual is not reachable by physical optimisation of a placement — only
by a different placement, or by less logic to place.**

## 4. Chosen-candidate artifacts and provenance

Candidate: `synth/out_build_035_full_AltSpreadLogic_high`, WNS **−0.136** /
WHS **+0.001**, netlist/VERSION CSR **`54443b9f`**. Built on **snoke**
(`| Host : snoke running 64-bit Ubuntu 24.04.4 LTS` in its own reports).

| artifact | bytes | mtime |
|---|---|---|
| `bd_wrapper_opt.dcp` | 155,734,824 | 2026-08-23 00:21 |
| `bd_wrapper_placed.dcp` | 221,988,296 | 2026-08-23 01:43 |
| `bd_wrapper_physopt.dcp` (post-place) | 221,188,766 | 2026-08-23 02:30 |
| `bd_wrapper_routed.dcp` | 282,167,994 | 2026-08-23 03:34 |
| `bd_wrapper_postroute_physopt.dcp` | 281,816,249 | 2026-08-23 05:22 |
| **`bd_wrapper.bit`** | **51,643,673** | **2026-08-23 05:29** |

**Stale-artifact check passes:** timestamps are strictly monotonic through the
flow and the `.bit` (05:29) **post-dates the final post-route-phys_opt
checkpoint** (05:22), so the bitstream is built from exactly the −0.136
netlist. Every census/report in this document was regenerated **from that
checkpoint** (`CENSUS_CHECKPOINT_MTIME: 2026-08-23 05:22:15`), never inherited
from the base roll — build_034 §7 finding 6, applied.

## 5. Per-clock table (shipping candidate)

Design summary: **WNS −0.136, TNS −132.442, 2,773 failing endpoints** of
1,204,553; **WHS +0.001, THS 0.000, 0 failing hold endpoints** of 1,201,417;
WPWS 0.000, 0 pulse-width failures.

| clock | period | WNS | TNS | failing EP | total EP | vs 034 shipped |
|---|---|---|---|---|---|---|
| mmcm_clkout0 (ch0 UI) | 3.332 | +0.006 | 0.000 | **0** | 158,758 | same (0) |
| mmcm_clkout0_2 (ch1 UI) | 3.332 | −0.103 | −15.572 | 362 | 158,736 | **regressed** (was 0) |
| **mmcm_clkout0_3 (ch2 UI)** | 3.332 | **0.000** | 0.000 | **0** | 158,729 | **CLOSED** (was −0.025 / 24) |
| mmcm_clkout0_1 (ch3 UI) | 3.332 | −0.087 | −34.158 | 841 | 158,869 | **regressed** (was +0.001 / 0) |
| pipe_clk | 4.000 | +0.128 | 0.000 | **0** | 4,764 | met, margin down from +0.762 |
| **xdma_0_axi_aclk** | 4.000 | **−0.136** | −82.711 | **1,570** | 520,041 | **regressed** (was −0.011 / 26) |

362 + 841 + 1,570 = **2,773**, reconciling exactly with the design summary.

Note the **WNS driver changed clock domains**: on 034 it was a DDR UI domain
(ch2, `matvec_engine`); on 035 it is the 250 MHz `xdma_0_axi_aclk` domain
(`layer_0`).

## 6. Failing-path census — AUTHORITATIVE, per-endpoint

`synth/scripts/census_035.tcl` on the shipping candidate's own checkpoint;
2,773 endpoints enumerated, reconciling with the design summary. Raw:
**`t5_01_census_035_shipped_candidate.log`**. Base-roll census for contrast:
**`t5_02_census_035_base.log`**.

### The three build_034 classes — closed / kept / worsened

| 034 class | 034 shipped | 035 candidate | verdict |
|---|---|---|---|
| **A — `matvec_engine`, ch2** | 24 EP, −0.025 … −0.007, `mmcm_clkout0_3` | **`mvchan_2`: 0 EP. Domain closed at 0.000.** But the *class* moved channels: `mvchan_3/u_engine` **485 EP**, `mvchan_1/u_engine` **305 EP** | **worsened as a class (790 EP), and it changed channel.** The specific waived endpoints are gone; the structure is not |
| **B — `layer_0`** (`u_dn` 18, `u_topk` 2, 3 loose) | 23 EP, −0.011 … −0.001 | **1,525 EP** — `u_dn` **1,237**, `g_dn` 115, `u_topk` **39**, `dn_rdq_reg` 30, `tcnt_bank_reg` 24, `u_attn` 18 (new), `u_alu` 9, `g_cv` 7, `u_axib` 6, `s_axil_rdata_reg` 6, + a `smem_a_reg_bram_*` tail | **worsened 66×, and it is now the WNS driver** |
| **C — `seq_0` MOV addressing** | 3 EP, −0.010 … −0.002 | **18 EP** | **worsened 6×** |

**`mvchan_2` — the channel the entire 034 waiver was written about — is
completely clean on this roll, and its clock domain closes at exactly 0.000.**
That is the single clearest proof that the 034 waiver cannot be carried
forward: it is a waiver for logic that no longer fails, on a domain that now
meets, while the design fails elsewhere by 5.4× as much.

### NEW class — vendor / BD infrastructure IP violates for the first time

build_034 shipped with **100% of failing endpoints in custom RTL** and *zero*
in `ddr4_*`, `xdma_*`, `axi_smc`, `smc_ch*`. That is no longer true:

| owner | EP | kind |
|---|---|---|
| `bd_i/layer_0/inst` | 1,525 | custom |
| `bd_i/mvchan_3/inst` | 649 | custom (`u_engine` 485, `u_streamer` **164** — new) |
| `bd_i/mvchan_1/inst` | 348 | custom (`u_engine` 305, `u_streamer` 43 — new) |
| `bd_i/seq_0/inst` | 18 | custom |
| `bd_i/smc_ch3/inst` | 161 | **vendor** (SmartConnect) |
| `bd_i/ddr4_3/inst` | 31 | **vendor** (MIG) |
| `bd_i/axil_smc/inst` | 16 | **vendor** |
| `bd_i/smc_ch1/inst` | 10 | **vendor** |
| `bd_i/xdma_0/inst` | 9 | **vendor** |
| `bd_i/ddr4_1/inst` | 4 | **vendor** |
| `bd_i/burst_smc/inst`, `bd_i/axil_slice_5/inst` | 1 + 1 | **vendor** |
| **total** | **2,773** | 2,540 custom / **233 vendor** |

`mvchan_*/u_chan/u_streamer` (207 EP) is also new — 034 had no streamer
endpoint in its failing set.

### Route-vs-logic split of the four worst paths

(`route = DATAPATH_DELAY − DATAPATH_LOGIC_DELAY`; the format string is fixed in
`census_035.tcl`, unlike the archived 034 log — see build_034 TIMING.md §5's
reading note.)

| slack | logic | route | total | endpoint |
|---|---|---|---|---|
| −0.136 | 0.251 (6.7%) | 3.479 (93.3%) | 3.730 | `layer_0/u_core/tcnt_bank_reg[2][0][6]/CE` |
| −0.136 | 0.077 (2.0%) | 3.698 (98.0%) | 3.775 | `layer_0/u_core/u_dn/vdata_q_reg[3]_rep__4_replica_1/D` |
| −0.135 | **2.773 (72.3%)** | 1.062 (27.7%) | 3.835 | `layer_0/u_core/s_axil_rdata_reg[3]/D` |
| −0.135 | 0.374 (9.6%) | 3.516 (90.4%) | 3.890 | `layer_0/u_core/u_dn/g_lane[96].o_acc_reg[96]_i_14_psdsp/D` |

Three of the four are ≥90% **routing** — the same "nothing to pipeline"
conclusion 034 reached. **The third is the exception and worth naming:**
`s_axil_rdata_reg[3]/D` is **72% logic** (2.773 ns), i.e. a genuinely deep
combinational cone — the AXI-Lite readback mux in `layer_chan`. That one *is*
an RTL-fixable path (a readback pipeline stage), and it is the only endpoint in
the top four that is. It is not, however, the WNS driver on its own; cutting it
alone would move WNS from −0.136 to at best −0.136 (two other paths tie).

## 7. `xline_q0_reg[*]/CE` — RC_W8_GATE.md's outstanding debt, PAID

RC_W8_GATE.md §"Still owed" required this build to report those endpoints **by
name, before and after**, because the claim that W8 mode cost the CE cone
"exactly one comparator bit" (`g_cnt` 6→7) had never been synthesised. It is
now measured, from both shipped checkpoints directly:

| property | 034 shipped (ch2) | 035 candidate (ch3) | delta |
|---|---|---|---|
| endpoint | `mvchan_2/…/u_engine/xline_q0_reg[11]__14/CE` | `mvchan_3/…/u_engine/xline_q0_reg[18]__6/CE` | — |
| slack | −0.025 | −0.087 | **−0.062 worse** |
| **datapath total** | 3.113 | **3.025** | **−0.088 — FASTER** |
| — logic | 0.399 | 0.497 | +0.098 |
| — route | 2.714 | 2.528 | −0.186 |
| **logic levels** | 5 | **4** | **−1 — SHALLOWER** |
| clock skew | −0.131 | **−0.281** | **−0.150 worse** |
| uncertainty | 0.052 | 0.052 | 0 |
| requirement | 3.332 | 3.332 | 0 |
| startpoint clock delay | 3.369 | 5.051 | +1.682 |
| endpoint clock delay | 3.703 | 5.077 | +1.374 |
| negative EP in the cone | 24 | **269** (of 1,000 sampled) | more |

Full path reports: `t5_03_xline_ce_path_035.rpt`, `t5_04_xline_ce_path_034.rpt`.

**The verdict on the sketch's claim: vindicated on the datapath, and the
regression is not this cone's fault.** The W8 CE cone is **one logic level
shallower** and its **total datapath delay is 0.088 ns faster** than the W4 path
it replaced. Logic delay did grow (+0.098 ns), which is consistent with the
extra comparator bit, but route fell further (−0.186 ns), so the net datapath
improved. The 0.062 ns of slack that was nonetheless lost is **accounted for by
clock skew alone** (−0.131 → −0.281, i.e. −0.150), and the clock delays to both
endpoints roughly *doubled* (3.4/3.7 ns → 5.1/5.1 ns) — the signature of a clock
network re-routed across a different SLR footprint, not of a slower data cone.

Two honest caveats, stated so nobody over-reads this:
- These are **different physical endpoints on different placements** (ch2
  replica 14 vs ch3 replica 6). This is a **class-level** comparison — the
  strongest one available, since the specific 034 endpoints no longer exist —
  not the same path measured twice.
- The cone **still violates** (−0.087) and now does so on **269** endpoints
  rather than 24. "Not the cause" is not "not a problem".

Also confirmed at the netlist level: **`u_engine` LUTRAM is bit-identical at
1,308 on all four channels, before and after** (§8). The sketch's claim that
`x_mem`'s *address path* is untouched — "no mux, no added logic level in front
of the LUTRAM" — is therefore not just an argument either; the memory did not
change shape.

## 8. Utilization — the lane-array price, finally priced

### 8a. Placement-independent (OOC synthesis) — the number the sketch asked for

`bd_mvchan_0_0` is one `matvec_chan` (engine + streamer + shim) synthesised
out-of-context, so this is the pure RTL cost with no placer in the loop.
Log: `t5_07_ooc_synth_utilization.log`.

| resource | 034 (W4) | 035 (W8) | delta |
|---|---|---|---|
| **CLB LUTs** | 14,023 | **19,849** | **+5,826 (+41.5%)** |
| — LUT as Logic | 10,318 | 16,143 | **+5,825 (+56.5%)** |
| — LUT as Distributed RAM | 3,698 | **3,698** | **0** |
| — LUT as Shift Register | 7 | 8 | +1 |
| **CARRY8** | 772 | **1,269** | **+497 (+64.4%)** |
| CLB Registers | 10,590 | 11,924 | +1,334 (+12.6%) |
| F7 Muxes | 887 | 964 | +77 |
| F8 Muxes | 272 | 296 | +24 |
| Block RAM Tile | 4 | **4** | **0** |
| **DSPs** | 2 | **2** | **0** |

**Answers, unambiguous:**
- **The W8 lane array costs +5,826 LUTs per channel, ×4 channels =
  +23,304 LUTs device-wide.** All of it is `LUT as Logic` + `CARRY8` — i.e.
  the 128 8×8 multiplier lanes and the 3–4 b wider adder tree, exactly the two
  things W8_SKETCH.md §3 flagged as "one synthesis run, not an argument".
- **DSP delta is ZERO.** The retire product widened to 17×21 and still fits a
  single DSP48E2 (27×18 signed, the 21 b operand on the 27 b port) — the
  sketch's *conclusion* holds even though its tabulated operand width did not.
- **LUTRAM delta is ZERO** and **BRAM delta is ZERO** — W8 touched logic, not
  memories, exactly as predicted.

**T4's `cfg_len` 13-bit widening is free.** `bd_layer_0_0` OOC synthesis:
LUTs 98,468 → 98,495 (**+27**), FFs 52,254 → 52,239 (**−15**), and CARRY8 /
BRAM / URAM / DSP **bit-identical**. The entire device delta is the four
mvchans.

### 8b. Device-wide, shipped candidate vs build_034 shipped

| resource | 034 shipped | 035 candidate | delta |
|---|---|---|---|
| **CLB LUTs** | 277,965 (23.51%) | **299,076 (25.30%)** | **+21,111 (+7.6%)** |
| — LUT as Logic | 239,289 | 260,396 | +21,107 |
| — LUTRAM | 33,724 | **33,724** | **0** |
| SRLs | 4,952 | 4,956 | +4 |
| CLB Registers | 287,372 (12.15%) | 292,520 (12.37%) | +5,148 |
| **CARRY8** | 11,693 (7.91%) | **13,681 (9.26%)** | **+1,988 (+17.0%)** |
| **Block RAM Tile** | 561 + 31 RAMB18 | **561 + 31** | **0 — as predicted** |
| **URAM** | 348 (36.25%) | **348** | **0** |
| **DSPs** | 1,858 (27.16%) | **1,858** | **0** |

Per `u_engine` instance (post-route, shipped candidates), 034 → 035:
ch0 10,232 → 11,695; ch1 10,185 → 11,719; ch2 10,220 → 11,635;
ch3 10,201 → 11,719. LUTRAM 1,308 → **1,308** on all four; DSP 2 → **2** on all
four. (The routed per-instance split differs from 8a's OOC split because
phys_opt replication re-attributes cells between `u_chan` and `u_engine`; 8a is
the clean measurement of the RTL cost, 8b of what ships.)

### 8c. Why +21K LUTs cost 0.111 ns before a directive was even chosen

| | 034 shipped | 035 candidate | delta |
|---|---|---|---|
| CLB occupancy SLR0 | 3,624 (7.36%) | 8,815 (**17.89%**) | +5,191 |
| CLB occupancy SLR1 | 39,351 (**79.88%**) | 36,402 (73.90%) | −2,949 |
| CLB occupancy SLR2 | 14,744 (29.93%) | 16,524 (33.54%) | +1,780 |
| **SLL: SLR2 ↔ SLR1** | 2,761 (15.98%) | **3,202 (18.53%)** | **+441** |
| **SLL: SLR1 ↔ SLR0** | 1,329 (7.69%) | **1,830 (10.59%)** | **+501** |
| **total SLL crossings** | **4,090** | **5,032** | **+942 (+23.0%)** |
| router congestion | level 5 (32×32) | **level 6 (64×64)** | worse |

**This is the mechanism, and it is not subtle.** SLR1 was already at 79.88%
occupancy on 034 — build_034's TIMING.md §4 called it "the highest per-SLR
pressure in the design and the figure worth tracking on the next build". The
extra 21K LUTs did not fit there, so the placer **spread the design outward**:
SLR1 occupancy actually *fell* while SLR0 more than doubled, and **SLL crossings
rose 23%**. SLL crossings and the wider clock footprint are what showed up as
the +0.150 ns of extra skew on the W8 cone (§7) and as 93–98% route-dominated
critical paths everywhere else (§6).

**The design has no pblocks at all** (verified again: no `create_pblock`
anywhere in `synth/constraints/`), so nothing constrained that spread. 034's
TIMING.md already named a floorplan as "the highest-leverage remaining lever";
that assessment now has a measured mechanism behind it.

## 9. ESCALATION — options and recommendation. THE USER DECIDES.

I am not taking a waiver here and I am not treating build_034's as carrying.
Presented for decision, cheapest first:

**(a) Accept −0.136 / +0.001 under a NEW waiver.**
*For:* magnitude is 3.4% of the 4 ns period. This project has shipped
hardware-clean negative WNS four times, twice on **this exact domain** at
**worse WNS**: `build_026` −0.142 (24/24 bit-exact), `build_030` −0.141
(rung-1 gate + 26/26 ladder, tokens bit-identical), `build_028` −0.106 (34/34),
`build_034` −0.025. **`build_030` is the closest precedent in kind as well as
magnitude**: its census was recorded as *"diffuse `layer_0` congestion, only
3/999 in `seq_0`"* — the same dominant block, the same domain, 999 failing
endpoints, and it was hardware-clean.
*Against:* 2,773 endpoints is **2.8× build_030's 999**, TNS is −132.4, and
**233 endpoints are inside vendor IP** (SmartConnect/MIG/XDMA) — a class this
project has never shipped a violation in, and the one class whose failure mode
is *not* covered by the bit-exact ladder argument (a SmartConnect or MIG timing
failure can present as a bus hang or corrupted DMA, not as a token mismatch).
Hold is +0.001 — one picosecond, an outcome rather than a guarantee, although
`full_impl.tcl` now at least gates it loudly (§10).

**(b) Floorplan the design — pblocks. (My recommendation, first move.)**
§8c shows the regression is SLR spread, not logic depth, and the design has
zero floorplan constraints. Constraining the four `mvchan_*` and `layer_0` to
SLRs would attack the +23% SLL growth and the +0.150 ns skew directly. This is
the lever 034 identified and deliberately did not pull. *Risks, from the house
rules:* never pblock GT/Aurora blocks (fixed physical locations), and check DSP
capacity per SLR before constraining `layer_0` — it holds 1,838 of the design's
1,858 DSPs, so it cannot be squeezed into an SLR that lacks them. Cost: a new
lever, a few build cycles. No RTL change, so **the R-c sim gate stays valid**.

**(c) Shrink the lane array — build W8_SKETCH.md §3's shape instead.**
§8a proves the as-built engine's price precisely: +5,826 LUTs/channel, all of
it multiplier lanes and adder tree. The sketch's §3 alternative keeps **64**
8×8 lanes instead of 128 with narrower trees, at the cost of a 512-bit mux
level in front of `x_mem`. RC_W8_GATE.md explicitly left "which shape is
smaller overall" open as *"a synthesis question, still open"*. **It is now
answered for the as-built shape only**, and the answer is expensive enough that
the alternative deserves pricing. *Cost:* re-does T1's RTL and invalidates the
R-c sim gate — the most expensive option, and the one with real schedule risk.

**(d) Reduce scope.** Drop to 3 channels, or lower the DDR UI / AXI clock.
Both cost tok/s directly against a V5 operating point that was already accepted
at −21..22% tok/s, so this trades away the thing V5 was chosen for.

**(e) Revert the operating point.** V4/V4gptq needs no W8 lane array at all and
was the quant study's own recommendation before it was declined in favour of
maximum quality. This is a gate-D reopen, not a timing decision, and I raise it
only because §8a is the first hard number on what V5's engine actually costs.

**My recommendation: (b) first, then re-roll the spread; hold (c) in reserve.**
The evidence says this is a placement/capacity problem, not an RTL-depth
problem — the W8 CE cone got *faster and shallower* (§7), 93–98% of the
critical delay is routing (§6), and the design has never been floorplanned
despite SLR1 sitting near 80% for two builds running. (b) is the only untried
lever with a measured mechanism pointing at it, and it costs no RTL and no
re-gating. If (b) does not close it, (a) becomes a much better-informed
decision than it is today — and if the user wants (a) *now*, the −0.136
bitstream exists and is ready to program.

**One concrete sub-item regardless of choice:** `s_axil_rdata_reg[3]/D` (§6) is
72% logic — a genuinely deep AXI-Lite readback mux in `layer_chan`, and the
only top-four endpoint that pipelining could actually help. It is a small,
contained RTL fix worth folding into whichever path is chosen.

## 10. Follow-ons closed by this task, and new process findings

**Closed (both were build_034 TIMING.md §7 findings, fixed BEFORE this build so
the campaign could not inherit them):**

1. **`launch_reroll.sh:34` `cp -a` NFS hang — gone.** The script is now a shim
   that `exec`s `launch_po2.sh`, which uses `rsync -a`. Measured here: three
   1.7 GB project copies completed in well under a minute each, versus the
   62-minutes-for-3.7 MB wedge observed on 2026-08-15.
2. **The phys_opt-less reroll flow is no longer reachable.** Every roll in §2
   ran the full recipe. `reroll_impl.tcl` is banner'd SUPERSEDED and retained
   only so the historical `out_*_rr_*` rolls stay reproducible. Output dirs are
   now tagged `_full_` rather than `_rr_`, so the tag names the recipe.

**Also folded in, both aimed at what this build had to report:**

3. **`full_impl.tcl` gained a greppable `WHS_GATE:` line** (§7 finding 5: this
   is the script that builds what *ships*, and it previously only *printed*
   WHS). Deliberately **non-fatal** — aborting would discard a routed bitstream
   that might still be the best roll — but a negative-hold roll can no longer
   ship unnoticed. All seven rolls reported `WHS_GATE: OK`.
4. **`full_impl.tcl` now emits `report_utilization -hierarchical`.** The flat
   report cannot separate the W8 lane array from the rest of the device, and
   §8 is exactly that separation.
5. **New `census_035.tcl`**: `census_034_shipped.tcl` generalised to take the
   roll dir as an argument (that one hardcoded build_034's path), with the
   `SPLIT` format string **corrected at last** (`DATAPATH_DELAY` is the *total*
   datapath delay, so `route = datapath − logic`), a 5-deep owner tally so
   `u_dn` / `u_topk` / `u_engine` / `u_streamer` separate, and a dedicated pass
   that reports `xline_q0_reg[*]/CE` by name whether or not it still violates.

**New finding — the authoritative placement-directive list, queried from the
tool rather than transcribed.** `SpreadLogic_medium` was rejected
(`ERROR: [Common 17-110] Invalid property value`), costing one wasted roll
slot. `list_property_value STEPS.PLACE_DESIGN.ARGS.DIRECTIVE` on this project
under Vivado 2024.2 returns exactly:

```
Explore WLDrivenBlockPlacement ExtraNetDelay_high ExtraNetDelay_low
AltSpreadLogic_low AltSpreadLogic_medium AltSpreadLogic_high
ExtraPostPlacementOpt ExtraTimingOpt SSI_SpreadLogic_high SSI_SpreadLogic_low
SSI_SpreadSLLs SSI_BalanceSLLs SSI_BalanceSLRs SSI_HighUtilSLRs
RuntimeOptimized Quick Default EarlyBlockPlacement RQS Auto_1 Auto_2 Auto_3
```

Corrections this forces on the notes we carry:
- **`SpreadLogic_high/medium/low` do not exist at all.** HISTORY.md's
  "empirical do-not-use list" entry for `SpreadLogic_high` was really an
  invalid name, not a bad directive.
- **`SSI_SpreadLogic_high` IS valid** — confirming build_034 §7 finding 4
  against the `fpga-tooling-reference` skill, which lists it as invalid.
- **`SSI_ExtraTimingOpt` and `ExtraNetDelay_medium` do not exist**; the skill
  lists both. `SSI_SpreadSLLs_high` is really `SSI_SpreadSLLs`.
- **Do not transcribe this list — query it.** One command, zero ambiguity.

**New finding — the post-place phys_opt estimate is not a reliable predictor,
in either direction.** `WLDrivenBlockPlacement` reported
`WNS=-0.022 | TNS=-0.573` at post-place phys_opt and looked like the closing
roll; it routed to −0.256 (TNS −385.8) and finished at −0.178. Meanwhile ASLh
went the other way (−0.180 post-place → −0.136 final), as did Explore (−0.436
→ −0.256) and ASLm (−0.458 → −0.318). **Never call a roll from its post-place
number on a congested design** — at congestion level 6 the estimate carries no
sign, let alone a magnitude.

**Machine sharing.** snoke carried three idle `vivado-mcp` server processes at
launch and no running `vivado` binaries; load 0.17, 247 GB RAM, 48 cores. No
other project's jobs were touched. Peak concurrency here was four full-recipe
rolls plus the phys_opt playbook.

---

# 11. FLOORPLAN CAMPAIGN (USER DECISION, 2026-08-23)

The user reviewed the §6 census personally and chose option **(b), the
floorplan**, over a waiver or the engine redesign. The engine redesign stays in
reserve. **If this campaign exhausts short of closure I stop and escalate back
rather than proceeding into RTL.**

Campaign discipline, as set: design from the census *before* the first run;
XDC-only (so every frozen gate and the R-c sim gate stay valid); full-recipe
rolls reusing build_035's synthesis; 2–3 directives per iteration; **if 3–4
iterations show no convergent trend toward 0, that is the exhaustion signal.**
Success = WNS ≥ 0, or a ps-scale residue with **zero vendor-IP endpoints** —
anything touching vendor IP or tens-of-ns TNS is not waiver-shaped.

## 11.1 The measurement the floorplan is designed from

`synth/scripts/slr_census.tcl`, run on **both** the build_035 shipping
candidate and the build_034 shipped roll (`t5_08_slr_census_035.log`,
`t5_09_slr_census_034.log`).

SLR geometry, read from the device rather than assumed from part folklore:

| SLR | clock regions | SLICE Y | CLB | DSP48E2 | URAM288 |
|---|---|---|---|---|---|
| SLR0 | X0Y0 … X5Y4 | 0–299 | 49,260 | 2,280 | 320 |
| SLR1 | X0Y5 … X5Y9 | 300–599 | 49,260 | 2,280 | 320 |
| SLR2 | X0Y10 … X5Y14 | 600–899 | 49,260 | 2,280 | 320 |

MIG anchors — fixed by the memory-interface IO banks, immovable:

| MIG | anchor clock regions | SLR |
|---|---|---|
| `ddr4_0` | X2Y1 … X2Y3 | **SLR0** |
| `ddr4_1` | X4Y5 … X4Y8 | **SLR1** |
| `ddr4_2` | X2Y7 … X2Y9 | **SLR1** |
| `ddr4_3` | X4Y11 … X4Y13 | **SLR2** |

## 11.2 A hypothesis that the evidence refuted, recorded

The first draft of this floorplan blamed **clock-SLR remoteness**: `mvchan_3`
sits in SLR1 while `ddr4_3` and its MMCM are in SLR2, and §7 measured that
channel's clock delays at 5.051/5.077 ns with skew −0.281 against 3.369/3.703
and −0.131 for build_034's co-located `mvchan_2`.

**Censusing build_034's placement refuted the causal story.** On build_034 **all
four mvchans were in SLR1**, `mvchan_3` included — so nothing about its
placement changed between the builds, and remoteness cannot be what broke.
Recorded rather than quietly corrected, because §7 finding 6 of build_034's
TIMING.md ("re-census the shipped roll, never a predecessor") exists precisely
because this project has shipped a wrong causal claim before.

## 11.3 What the per-channel evidence does say

All four channels of build_035, side by side:

| ch | mvchan | MIG | co-located? | SLR load | xline CE worst | domain WNS | failing EP |
|---|---|---|---|---|---|---|---|
| 0 | SLR0 | SLR0 | yes | **17.89%** | **+0.092** | +0.006 | **0** |
| 1 | SLR1 | SLR1 | yes | 73.90% | −0.080 | −0.103 | 348 |
| 2 | SLR1 | SLR1 | yes | 73.90% | (better than worst-1000) | 0.000 | **0** |
| 3 | SLR1 | **SLR2** | **no** | 73.90% | −0.087 | −0.087 | **649** |

- **Congestion is the primary axis.** The only channel with real margin is the
  one in the nearly empty SLR — +0.092 is the sole *positive* xline CE slack in
  the design. All three channels sharing the 73.90%-full SLR1 sit at or below
  zero, co-located or not.
- **Remoteness is a secondary aggravator.** Among the three crowded channels,
  the one that is also remote from its MIG carries **649** failing endpoints
  against ch1's 348 and ch2's zero, and drags `smc_ch3` into a 60/40 straddle
  worth another 161.
- **On build_034, with engines 39% smaller, SLR1 held all four mvchans and
  three of the four channels met timing.** SLR1's capacity was the latent
  single point of failure all along; W8's +41.5% per channel crossed it.

## 11.4 Iteration 1 — the floorplan

`synth/constraints/fable5_floorplan.xdc`, five **soft** pblocks (no
`CONTAIN_ROUTING`, no `EXCLUDE_PLACEMENT` — they constrain placement of the
named cells and nothing else):

| pblock | cells | region | effect |
|---|---|---|---|
| `pb_mvchan_0` | `bd_i/mvchan_0` | SLR0 | holds where it already is |
| `pb_mvchan_1` | `bd_i/mvchan_1` | SLR1 | holds where it already is |
| `pb_mvchan_2` | `bd_i/mvchan_2` | SLR1 | holds where it already is |
| **`pb_mvchan_3`** | `bd_i/mvchan_3` | **SLR2** | **relocates an entire engine off SLR1, beside its own MIG** |
| **`pb_layer_dn`** | `bd_i/layer_0/inst/u_core/u_dn` | **SLR2** | **de-straddles the 1,237-endpoint block (was 74/26)** |

Projected CLB occupancy (LUT counts at the design's measured 4.93 LUTs/CLB):

| | before | after |
|---|---|---|
| SLR0 | 17.89% | ~16.9% |
| **SLR1** | **73.90%** | **~52.8%** |
| SLR2 | 33.54% | ~53.4% |

`u_dn` goes to SLR2 rather than SLR1 (where 74% of it already sits) purely for
balance: sending it to SLR1 leaves SLR1 at ~70.7% and relieves nothing. `u_dn`
is free to move — 43,391 LUTs and 1,280 DSPs but **zero URAM, zero BRAM**, so
no memory anchor holds it anywhere.

**DSP capacity check (the house-rule pitfall), done before writing the file.**
`u_dn` is DSP-heavy. The pblocks *force* 1,282 DSPs into SLR2 (`u_dn` 1,280 +
`mvchan_3` 2) = **56% of SLR2's 2,280** — comfortable. If the other DSP-heavy
block, `u_attn` (526), also stays in SLR2, the total reaches ~1,844 = 81%,
which is legal but is the tightest number here. `u_attn` is **deliberately left
unconstrained so it can act as the relief valve** and migrate to SLR1 if the
placer needs the room.

**URAM is the hard limit that cannot be satisfied in one SLR:** `layer_0` needs
348 URAM and an SLR has 320, so `layer_chan`'s memory level *must* straddle.
It is left unconstrained so the placer can put up to 320 in SLR2 and spill only
the remainder — better than build_035's 189/159 split.

**Deliberately not pblocked:** `xdma_0`/PCIe/GTs (house rule — fixed locations;
measured here at `PCIE40E4_X1Y2` in clock region X5Y5 and 8× `GTYE4_CHANNEL` in
X5Y7/X5Y8, all SLR1, so they are anchored by hardware anyway); the `ddr4_*`
MIGs (anchored by their IO banks); `layer_0`'s memory level and `u_attn` (see
above); `seq_0` and the SmartConnects, left free to follow their masters —
`smc_ch3` in particular should stop straddling once `mvchan_3` and `ddr4_3` are
on the same side.

**Pre-flight validation** (`synth/scripts/floorplan_check.tcl`, dry-run against
the routed checkpoint before any roll started): XDC reads clean, 5 pblocks
created, every cell path resolves, and each region reports 49,260 SLICE /
2,280 DSP / 320 URAM. This guards the classic floorplan-campaign failure —
a pblock that matches zero cells is silently harmless in Vivado and would
measure nothing. `full_impl.tcl` now also prints a `PBLOCK` line per pblock on
every roll, so the constraint is re-proven in-flight rather than assumed.

## 11.5 Iteration 1 result — the floorplan made it WORSE, and why

| directive | unconstrained | **floorplan iter 1** | delta |
|---|---|---|---|
| AltSpreadLogic_high | −0.136 | **−0.624** | **−0.488 worse** |
| WLDrivenBlockPlacement | −0.178 | **−0.557** | −0.379 worse |
| Explore | −0.256 | **−0.510** | −0.254 worse |

WHS stayed non-negative on all three (+0.002 / 0.000 / 0.000, all
`WHS_GATE: OK`). Lines: `t5_11_fp1_campaign_lines.log`.

**The pblocks were honoured** — this is not a case of a floorplan that silently
did nothing. `full_impl.tcl`'s in-flight check reports all 5 pblocks with their
ranges on every roll, and the post-run census (`t5_10_slr_census_fp1.log`)
confirms the placement moved exactly as instructed:

| block | build_035 | floorplan iter 1 | asked for? |
|---|---|---|---|
| `mvchan_3` | SLR1 100% | **SLR2 100%** | yes ✔ |
| `u_dn` | SLR1 74% / SLR2 26% | **SLR2 100%** | yes ✔ |
| `u_attn` | **SLR2 100%** | **SLR1 100%** | **NO — evicted** |
| `u_topk` | SLR2 100% | SLR1 100% | no — evicted |
| `u_alu` | SLR2 100% | SLR1 100% | no — evicted |
| `layer_0` overall | SLR1 30% / SLR2 70% | SLR1 60% / SLR2 40% | — |

**The defect is mine, and it is precise.** Pinning `u_dn` alone into SLR2 left
the placer only one way to balance the resulting SLR2 load: evict everything
else in `layer_0` that was not nailed down. `u_attn` — 37,190 LUTs, 526 DSPs,
and the block `u_dn` is most tightly coupled to — went from **100% co-resident
with `u_dn`'s SLR2 share** to **100% on the other side of the SLL boundary**.
Iteration 1 optimised `u_dn`'s internal coherence and paid for it by breaking
`u_dn`↔`u_attn` adjacency completely.

The load-balancing intent also failed, for the same reason: SLR1 was supposed
to drop from 73.90% to ~52.8%, but `u_attn` (37,190 LUTs) moved *in* as
`mvchan_3` (19,182 LUTs) moved *out*, so SLR1 gained LUTs on net.

Two things did work and are worth keeping:
- **`mvchan_3` relocated cleanly** — engine 100% in SLR2 with its own MIG and
  MMCM, exactly as designed.
- **Congestion on the ASLh roll fell from level 6 (64×64) to level 5 (32×32)**,
  back to build_034's level. The floorplan genuinely relieved routing
  congestion; it just introduced a worse problem elsewhere.

**Correction to §11.4's reasoning.** The "relief valve" argument — that leaving
`u_attn` unconstrained would let it migrate if SLR2 got tight — was written as
a *safety* feature. It was actually the failure mechanism: an unconstrained
block adjacent to a pinned one does not stay put, it gets pushed out. **A
tightly-coupled pair must be constrained as one cluster or not at all.**

## 11.6 Iteration 2 — controlled A/B/C on the single best directive

Rather than re-run one floorplan across three directives, iteration 2 runs
three *floorplans* under the one directive that has won every campaign so far
(`AltSpreadLogic_high`). The unproven lever here is the floorplan, so that is
what the experiment should vary.

| variant | XDC | pblocks | isolates |
|---|---|---|---|
| **A** | `fable5_floorplan_a.xdc` | mvchan affinity only (4) | the engine-relocation effect, `layer_0` entirely free |
| **B** | `fable5_floorplan_b.xdc` | mvchan affinity + **`u_dn`+`u_attn` as ONE cluster** in SLR2 (5) | iteration 1 with its diagnosed defect repaired |
| **C** | `fable5_floorplan_c.xdc` | compute cluster only (1) | the `layer_0` coherence effect, mvchans entirely free |

Variant B is the corrected design; A and C decompose it so that whichever way
the result falls, it is attributable rather than another lottery ticket.

## 11.7 Iteration 2 result — VARIANT A WINS, and it is not close

| variant | pblocks | WNS | WHS | vs unconstrained −0.136 |
|---|---|---|---|---|
| **A** | **mvchan affinity only (4)** | **−0.004** | **0.000** | **+0.132 better** |
| B | mvchan + `u_dn`+`u_attn` cluster (5) | −1.078 | 0.000 | 0.942 worse |
| C | compute cluster only (1) | −1.148 | 0.000 | 1.012 worse |

Lines: `t5_17_fp2_fp3_campaign_lines.log`. All three report their pblocks
honoured in-flight.

**The A/B/C decomposition settles it.** Constraining `layer_0` is catastrophic —
it costs about a full nanosecond whether or not the mvchan pblocks are present
(B −1.078, C −1.148). Constraining *only* the mvchans, and letting the placer
solve `layer_0` freely, closes the design to within 4 ps. The two effects are
cleanly separable and they point in opposite directions.

**Iteration 1's "fix" was worse than useless, and so was my repair of it.** The
compute-cluster idea from §11.5 — pin `u_dn` and `u_attn` together so they stop
being separated — is variant B, and it is the second-worst result of the entire
campaign. The lesson is not "cluster them properly" but **"do not floorplan
`layer_0` at all."**

### What the winning placement actually did (`t5_14_slr_census_fp2a_winner.log`)

| block | build_035 | **fp2a winner** |
|---|---|---|
| `mvchan_0` / `ddr4_0` | SLR0 / SLR0 ✔ | SLR0 / SLR0 ✔ |
| `mvchan_1` / `ddr4_1` | SLR1 / SLR1 ✔ | SLR1 / SLR1 ✔ |
| `mvchan_2` / `ddr4_2` | SLR1 / SLR1 ✔ | SLR1 / SLR1 ✔ |
| `mvchan_3` / `ddr4_3` | **SLR1 / SLR2 ✘** | **SLR2 / SLR2 ✔** |
| `layer_0` | SLR1 30% / SLR2 70% | **SLR0 70% / SLR1 30%**, SLR2 vacated |
| `u_dn` | SLR1 74% / SLR2 26% | SLR0 25% / SLR1 75% |
| `u_attn` | SLR2 100% | SLR0 100% |
| SLR CLB | 17.89 / 73.90 / 33.54 | **42.91 / 70.43 / 15.47** |

**All four channels are now co-located with their own MIG** — the first time
that has ever been true in this project. Given those four anchors the placer
found its own global arrangement: it moved `layer_0` wholesale into SLR0+SLR1
and handed SLR2 to channel 3 alone.

**Sources for the SLR CLB percentages above, the SLL counts below and the
utilization table further down** (the `synth/out_*` trees they were read from
are gitignored, so the reports themselves are committed):
`t5_26_utilization_build035_candidate.rpt` (the build_035 column) and
`t5_25_utilization_fp2a_winner.rpt` (the fp2a column). Per-SLR CLB is section
"14. SLR CLB Logic and Dedicated Block Utilization"; SLL crossings are section
"12. SLR Connectivity"; device totals are section "1. CLB Logic".

Two of my own earlier claims need correcting against this:

- **`u_dn` is still split (SLR0 25% / SLR1 75%) and `u_attn` is in a different
  SLR from `u_dn`'s bulk — and it closed anyway.** So "`u_dn` must be coherent"
  and "`u_dn` and `u_attn` must be adjacent" are both **false as stated**. What
  iteration 1 actually did wrong was not the split itself but *forcing* a
  layer_0 placement, which pushed the placer into a bad global solution.
- **Total SLL crossings went UP, from 5,032 to 5,230** (SLR2↔SLR1 3,202→2,113;
  SLR1↔SLR0 1,830→3,117), and SLR1 barely moved (73.90% → 70.43%). So §8c's
  framing — "SLL crossings +23% is the mechanism" — is **too crude**. The count
  of crossings is not what matters; *which* nets cross, and whether each
  DDR-clocked engine sits in its own clock's SLR, is.

### The winner's timing, in full (`t5_15_timing_summary_fp2a.rpt`)

Design summary: **WNS −0.004, TNS −0.010, 6 failing endpoints** of 1,203,526;
**WHS 0.000, THS 0.000, 0 failing hold endpoints** of 1,200,390; WPWS 0.000,
0 pulse-width failures.

| clock | WNS | TNS | failing EP | vs build_035 |
|---|---|---|---|---|
| mmcm_clkout0 (ch0 UI) | **+0.042** | 0.000 | **0** | was +0.006 / 0 |
| mmcm_clkout0_2 (ch1 UI) | **+0.005** | 0.000 | **0** | was −0.103 / 362 |
| mmcm_clkout0_3 (ch2 UI) | **+0.009** | 0.000 | **0** | was 0.000 / 0 |
| mmcm_clkout0_1 (ch3 UI) | **+0.048** | 0.000 | **0** | was −0.087 / 841 |
| pipe_clk | **+0.840** | 0.000 | **0** | was +0.128 / 0 |
| xdma_0_axi_aclk | **0.000** | 0.000 | **0** | was −0.136 / 1570 |

**Every one of the six named clocks meets timing with zero failing endpoints.**

### Failing-endpoint census (`t5_13_census_fp2a_winner.log`)

**6 endpoints, 2,767 fewer than build_035. ZERO of them are custom RTL.**

| owner | EP | kind |
|---|---|---|
| `bd_i/xdma_0/inst/udma_wrapper/dma_top` | **6** | vendor (XDMA) |
| `layer_0`, `mvchan_*`, `seq_0` | **0** | — |

All six are in Vivado's **`**async_default**`** path group — recovery/removal
checks, not datapath:

```
EP -0.004 **async_default** lvl=0  .../dma_top/user_rst_ff_2_reg/CLR
EP -0.001 **async_default** lvl=0  .../dma_top/user_rst_n_2ff_reg[2]/CLR
EP -0.001 **async_default** lvl=0  .../dma_top/user_rst_n_3ff_reg[0]_rep__14/CLR
EP -0.001 **async_default** lvl=0  .../dma_top/user_rst_n_3ff_reg[0]_rep__3/CLR
EP -0.001 **async_default** lvl=0  .../dma_top/user_rst_n_3ff_reg[2]/CLR
EP -0.001 **async_default** lvl=0  .../dma_top/user_rst_n_ff_reg[2]/CLR

   all six  <- bd_i/xdma_0/inst/pcie4_ip_i/inst/user_reset_reg/C
```

All **six** are listed above — complete, not elided. (An earlier revision
printed only four under prose saying six.) Verbatim source:
`t5_13_census_fp2a_winner.log`.

Startpoint is the **PCIe hard block's `user_reset_reg`**; the endpoints are the
**asynchronous CLR pins of XDMA's own user-reset synchronizer** (`_2ff`, `_3ff`
— the multi-flop chain whose entire purpose is to tolerate asynchronous
deassertion). **Zero logic levels**: pure routing between two vendor blocks.
No custom logic is on any of these paths.

### The W8 cone — RC_W8_GATE's structure, now fully closed with margin

| channel | build_035 | **fp2a** |
|---|---|---|
| `mvchan_0` xline CE worst | +0.092 | **+0.173** |
| `mvchan_1` | −0.080 | **+0.094** |
| `mvchan_2` | (>worst-1000) | **+0.221** |
| `mvchan_3` | −0.087 | **+0.077** |
| negative endpoints in the cone | 269 | **0** |

`xline_q0_reg[*]/CE` — the family that carried build_034's 24 waived endpoints,
that build_033's −0.344 path lived in, and that W8_SKETCH.md flagged as the
structure at risk — is **positive on all four channels with 77–221 ps of
margin**. The W8 engine mode costs this cone nothing.

### Utilization — unchanged, as it must be (XDC-only)

| resource | build_035 candidate | fp2a |
|---|---|---|
| CLB LUTs | 299,076 (25.30%) | 299,529 (25.34%) |
| CLB Registers | 292,520 | 292,692 |
| CARRY8 | 13,681 | 13,681 |
| Block RAM Tile | 576.5 | **576.5** |
| URAM | 348 | **348** |
| DSPs | 1,858 | **1,858** |

The ±0.15% LUT/FF wobble is phys_opt replication differing between placements.
Memories and DSPs are identical, as they must be — nothing but constraints
changed. Sources: `t5_26_utilization_build035_candidate.rpt` and
`t5_25_utilization_fp2a_winner.rpt`.

### Winning artifacts

`synth/out_build_035_fp2a_AltSpreadLogic_high`, built on **snoke**,
netlist/VERSION CSR **`54443b9f`** (unchanged — XDC-only).

| artifact | bytes | mtime |
|---|---|---|
| `bd_wrapper_opt.dcp` | 155,722,843 | 2026-08-23 21:29 |
| `bd_wrapper_placed.dcp` | 222,673,289 | 2026-08-23 22:58 |
| `bd_wrapper_physopt.dcp` | 221,803,520 | 2026-08-24 00:18 |
| `bd_wrapper_routed.dcp` | 282,775,812 | 2026-08-24 01:18 |
| `bd_wrapper_postroute_physopt.dcp` | 282,363,832 | 2026-08-24 01:56 |
| **`bd_wrapper.bit`** | **54,072,409** | **2026-08-24 02:06** |

Strictly monotonic, and the `.bit` (02:06) post-dates the final checkpoint
(01:56) — **the bitstream is built from exactly the −0.004 netlist.**

## 11.8 Closing the last 4 ps — both cheap levers spent, both failed

**(a) phys_opt playbook on the fp2a checkpoint** (`po_fp2a.tcl`,
`t5_16_physopt_playbook_fp2a.log`):

| step | WNS | WHS |
|---|---|---|
| PASS0 | −0.004 | 0.000 |
| + `AlternateReplication` | −0.004 | 0.000 |
| + `AggressiveFanoutOpt` | −0.004 | 0.000 |
| + `Explore` | −0.004 | 0.000 |
| + `AggressiveExplore` | −0.004 | 0.000 |
| `route_design -preserve` → `POFP_NOT_CLOSED` | −0.004 | 0.000 |

**Four directives, bit-identical slack, zero movement.** Expected in hindsight:
the path is 0 logic levels from a *hard block* output to an async CLR pin.
There is no logic for phys_opt to restructure and no cell it is allowed to move.

**(b) sibling directives on the winning floorplan** (TAG `fp3`, same
`fable5_floorplan_a.xdc`):

| directive | WNS | WHS |
|---|---|---|
| **AltSpreadLogic_high** (fp2a) | **−0.004** | 0.000 |
| ExtraTimingOpt | −0.073 | 0.000 |
| WLDrivenBlockPlacement | −0.202 | +0.001 |
| AltSpreadLogic_medium | −0.428 | +0.005 |

The spread did **not** straddle zero — `AltSpreadLogic_high` beat the next best
by 69 ps. Three more placement lottery tickets all landed worse.

## 12. VERDICT AND ESCALATION — the user decides

> ⚠ **SUPERSEDED — see §13.** This is the dated escalation of 2026-08-24 that
> put options (a) waive / (b) extend the exception / (c) keep rolling to the
> user. **The user chose (b), and the design closed: WNS 0.000 / WHS 0.000,
> zero failing endpoints, no waiver.** The "stopped 4 ps short" framing below
> was true when written and is no longer current state. Preserved as the record
> the decision was made on.

**The floorplan campaign succeeded at what it was aimed at and stopped 4 ps
short of the finish line.**

| | build_034 (shipped) | build_035 (best) | **fp2a (floorplan)** |
|---|---|---|---|
| WNS | −0.025 | −0.136 | **−0.004** |
| TNS | −0.613 | −132.442 | **−0.010** |
| failing endpoints | 50 | 2,773 | **6** |
| **custom-RTL endpoints** | 50 | 2,540 | **0** |
| **vendor-IP endpoints** | 0 | 233 | **6** |
| clocks with failures | 2 of 6 | 3 of 6 | **0 of 6** |
| hold failing endpoints | 0 | 0 | **0** |
| W8 xline cone | n/a | 269 negative | **0 negative, +77…+221 ps** |

**Against the stated success criterion this is a NO.** The bar was "WNS ≥ 0, or
a ps-scale residue with **zero** vendor-IP endpoints". The residue is ps-scale
(−0.004, TNS −0.010) but it is **100% vendor IP**, so it fails the criterion as
written and I am not treating it as a pass.

**But the criterion was written against a different animal, and the difference
is worth stating plainly.** build_035's 233 vendor-IP endpoints were
SmartConnect/MIG **datapath** violations — the kind that can hang a bus or
corrupt a DMA transfer silently, which is exactly why they were ruled
not-waiver-shaped. fp2a's 6 are `**async_default**` **recovery checks on the
CLR pins of a reset synchronizer**, 0 logic levels, both ends inside vendor IP,
on the structure whose entire design purpose is to absorb asynchronous
deassertion. These are different failure classes, not different magnitudes of
the same one.

**Relevant evidence the user should weigh, which I am reporting but did NOT act
on.** Xilinx's own PCIe XDC for this very core
(`ip_pcie4_uscale_plus_x1y2.xdc`) treats this class as false by construction:

```
line 166: set_false_path -to [get_pins .../phy_wrapper/rst_psrst_n_r_reg[*]/CLR]
line 168: set_false_path -to [get_pins .../phy_rst_i/prst_n_r_reg[*]/CLR]
line 187: set_false_path -to [get_pins user_reset_reg/PRE]
line 246: create_waiver -type CDC -id CDC-10 ... -desc "PCIe user_reset path - safe to waive"
```

It false-paths the CLR pins of the GT reset synchronizers and the PRE of
`user_reset_reg`, and ships a CDC waiver calling the user_reset path safe. What
it does **not** cover is the *downstream* `udma_wrapper/dma_top/user_rst_*/CLR`
pins — the shipped constraints are scoped to the PCIe sub-IP and stop at the
XDMA wrapper boundary, which is precisely where our 6 endpoints live.

**Options, for the user's decision:**

**(a) Accept −0.004 / 6 async-reset endpoints under a waiver.** Precedent is
overwhelming on magnitude: this project has shipped −0.142, −0.141, −0.106 and
−0.025, all hardware-clean, all with *custom datapath* violations. −0.004 with
**zero custom-RTL endpoints and zero failing clocks** is by a wide margin the
cleanest netlist this project has ever produced.

**(b) Add the missing timing exception** —
`set_false_path -to [get_pins .../udma_wrapper/dma_top/user_rst*/CLR]` —
extending to the XDMA wrapper the same constraint Xilinx already applies to the
sibling synchronizers one level up. This is arguably not a waiver at all but
the correct constraint for a CDC reset synchronizer, after which WNS is ≥ 0 by
construction. **I did not do this**: it changes what is *checked*, on vendor IP,
and that is a decision for the user, not for me.

**(c) Keep rolling.** Not recommended, and now evidence-backed: phys_opt is
exhausted (4 directives, zero movement, structurally unable to help) and 3
further placement directives on the winning floorplan all landed 69–424 ps
worse.

**My recommendation: (b), then re-roll once to confirm ≥ 0; fall back to (a).**
The residue is a reset synchronizer, not a datapath, and (b) makes the
constraint set say what the hardware actually is. If the user prefers not to
touch vendor-IP constraints, (a) is defensible on this record — but either way
**the call is the user's.**

**What is settled regardless of that call:** the floorplan works, it is
XDC-only, and it took the design from 2,773 failing endpoints across 3 clocks
to 6 async-reset endpoints across none, with **every line of custom RTL closed**
and the W8 cone positive on all four channels. `fable5_floorplan_a.xdc` — mvchan
channel affinity, and nothing else — is the constraint that did it.

---

# 13. CLOSED — build_035 meets timing. Decision record and signoff.

## 13.1 The decision

**USER DECISION, 2026-08-24, interactive three-option prompt.** Presented with
(a) waive −0.004, (b) extend the Xilinx reset-synchronizer exception to the
XDMA wrapper, (c) keep re-rolling, the user chose **(b)**. Waiving was
**declined**: this is closed as a **constraint, not a waiver**. §12 recorded the
options; this section records the outcome.

## 13.2 The constraint

`synth/constraints/fable5_xdma_rst_exception.xdc`, one line,
implementation-only, no RTL touched:

```
set_false_path -to [get_pins -quiet -hierarchical \
    -filter {NAME =~ */udma_wrapper/dma_top/user_rst_*_reg*/CLR}]
```

It extends to the XDMA wrapper the exception the PCIe core's own shipped XDC
(`ip_pcie4_uscale_plus_x1y2.xdc`) already applies one level up — `-to
.../rst_psrst_n_r_reg[*]/CLR` (line 166), `-to .../prst_n_r_reg[*]/CLR`
(line 168), `-to user_reset_reg/PRE` (line 187), plus `create_waiver` CDC-10
*"PCIe user_reset path - safe to waive"* (line 246). That file is scoped to the
PCIe sub-IP and stops at the XDMA wrapper boundary, which is exactly where the
six endpoints lived.

## 13.3 Scope verification — done BEFORE trusting any number

`synth/scripts/exception_check.tcl` (`t5_18_exception_scope_check.log`), run
against the fp2a checkpoint. Because it re-places nothing, it also settled the
whole question in ten minutes instead of five hours:

| check | result |
|---|---|
| pins matched | **40** (non-zero — an exception matching nothing is silently harmless and would fake a pass) |
| matched pins outside `xdma_0` | **0** |
| matched pins that are not `/CLR` | **0** |
| before | WNS −0.004, **6** failing |
| after | WNS **0.000**, **0** failing |
| `xline_q0/CE` still analysed | **yes**, slack +0.077 |
| `layer_0/u_dn` still analysed | **yes**, slack +0.001 |

**The decisive scope proof is the analysed-endpoint count.** Setup endpoints
went **1,203,526 → 1,203,486** and hold endpoints **1,200,390 → 1,200,350** —
exactly **40** fewer in each, precisely the 40 pins matched, and not one
endpoint more. Nothing beyond the reset synchronizer stopped being checked.

Both halves of that pair are committed, from the **same checkpoint** with the
exception the only difference — which is what makes it a clean subtraction:
`t5_15_timing_summary_fp2a.rpt` (before: 1,203,526 setup / 1,200,390 hold) and
`t5_24_timing_summary_fp2a_WITH_exception.rpt` (after: 1,203,486 / 1,200,350).
This matters more than the argument in the XDC header, because Tcl glob lets
`*` cross `/` — so the pattern's reach is established by counting what it
actually matched, not by reading the pattern.

40 pins rather than 6 because the exception covers the whole synchronizer
structure — six register families (`user_rst_ff_2`, `user_rst_n_ff`,
`user_rst_n_2ff`, `user_rst_n_3ff`, `user_rst_3ff_0`, `user_rst_3ff_2`) and
their phys_opt replicas — not merely the subset that happened to violate on one
placement. That is the correct unit: constraining only the failing six would
leave sibling flops of the same synchronizer checked, and re-placement changes
which of them fails.

**Why this cannot hide a datapath failure:** it is scoped by hierarchy (inside
`*/udma_wrapper/dma_top/`), by cell name (`user_rst_*_reg*`) and by **pin**
(`/CLR` only). Datapath arrives at a flop's `/D`, never its `/CLR`, so a
`-to /CLR` exception is structurally incapable of exempting one. The three
custom-RTL classes are asserted still-analysed by the script, which exits FATAL
if they ever stop returning slack.

## 13.4 SIGNOFF — the shipping build

**`synth/out_build_035_fp2a_exc_po/bd_wrapper.bit`**
Netlist / **VERSION CSR = `54443b9f`** (unchanged throughout — every step since
build_035 has been XDC-only).

Re-verified from the shipping checkpoint by `synth/scripts/final_verify.tcl`
(`t5_21_final_signoff_verify.log`). **What that script does and does not
establish, stated precisely** (an earlier revision claimed it "re-derives every
claim", which overreached): it opens `bd_wrapper_po_routed.dcp` in a fresh
session, applies the exception itself, and independently re-derives **WNS, WHS,
the failing setup and hold endpoint counts, the per-channel `xline_q0/CE`
margins, and the still-analysed assertions**. It does **not** regenerate the
design summary or the six-clock table below — those are read from the producing
run's own `report_timing_summary` (`po_fp2a_exc.tcl:43`) and are byte-identical
to it, so they are corroboration from the same run, not an independent
derivation. The independently re-derived numbers are these:

```
FV_WNS: 0.000          FV_WHS: 0.000
FV_FAILING_SETUP: 0    FV_FAILING_HOLD: 0
FV_XLINE_WORST_mvchan_0: 0.173   mvchan_1: 0.094
FV_XLINE_WORST_mvchan_2: 0.221   mvchan_3: 0.077
FV_STILL_CHECKED *layer_0*u_core/u_dn/*/D  slack=0.001
FV_STILL_CHECKED *seq_0*u_seq/*/D          slack=0.011
FV_STILL_CHECKED *u_engine/xline_q0_reg*/CE slack=0.077
```

Design summary: **WNS 0.000, TNS 0.000, 0 failing setup endpoints** of
1,203,486; **WHS 0.000, THS 0.000, 0 failing hold endpoints** of 1,200,350;
WPWS 0.000, 0 pulse-width failures. All six clocks meet with **zero** failing
endpoints (+0.042 / +0.005 / +0.009 / +0.048 / +0.840 / 0.000).

**Hold, held to this document's own §9 standard.** §9 said of build_035's
+0.001 that it was "one picosecond, an outcome rather than a guarantee". The
shipping build's hold is **0.000 — less margin than that, not more**, and the
same caveat applies with more force: it is measured non-negative on every one
of 1,200,350 hold endpoints (THS 0.000, zero failing), but zero picoseconds of
*reported* margin is an outcome of this placement, not a property the flow
guarantees. `full_impl.tcl`'s `WHS_GATE` line makes it loud rather than silent,
and `po_fp2a_exc.tcl` refuses to emit a bitstream unless `WHS >= 0`, so nothing
here shipped unchecked — but neither mechanism creates margin.
**Relevance to board bring-up (T6/R-d):** hold failures do not scale away with
a slower clock the way setup failures do, and 0.000 leaves nothing for
on-silicon PVT spread. If R-d sees intermittent or non-reproducible behaviour
that the bit-exact ladder cannot pin to a datapath, hold on this build is a
legitimate suspect and should be re-examined before anything is attributed to
the W8 datapath — which, on setup, closed with margin on all four channels.

| artifact | bytes | mtime |
|---|---|---|
| `bd_wrapper_po_routed.dcp` | 281,799,346 | 2026-08-24 23:03 |
| **`bd_wrapper.bit`** | **54,072,409** | **2026-08-24 23:13** |

Monotonic, `.bit` post-dates the checkpoint. Written by `po_fp2a_exc.tcl`,
which emits a bitstream **only** when `WNS >= 0 && WHS >= 0` — so the existence
of this file is itself the closure gate (`POEX_CLOSED`).

## 13.5 The confirming reroll — and what it honestly shows

The reroll of fp2a's exact recipe with the exception added (TAG `fp4`,
`t5_23_fp4_reroll_lines.log`) did **not** reproduce fp2a's quality. All three
fp4 rolls carried **both** XDCs — floorplan A *and* the exception — during
implementation, so the exception was in force while they placed and routed and
still did not rescue them; they are simply worse placements.

**Every place-and-route roll on floorplan A — there are SEVEN, not ten:**

| roll | directive | exception in force? | WNS | WHS |
|---|---|---|---|---|
| **fp2a** | AltSpreadLogic_high | no | **−0.004** | 0.000 |
| fp3 | ExtraTimingOpt | no | −0.073 | 0.000 |
| fp3 | WLDrivenBlockPlacement | no | −0.202 | +0.001 |
| fp3 | AltSpreadLogic_medium | no | −0.428 | +0.005 |
| fp4 | WLDrivenBlockPlacement | **yes** | −0.080 | 0.000 |
| fp4 | AltSpreadLogic_high | **yes** | −0.231 | 0.000 |
| fp4 | ExtraTimingOpt | **yes** | −0.264 | 0.000 |

**Roll spread: −0.004 … −0.428, and fp2a is the best of the seven.**

Two further passes ran on fp2a's *existing* checkpoint and are **not rolls** —
they re-place nothing: `fp2a_po` (phys_opt playbook, no exception, −0.004) and
`fp2a_exc_po` (phys_opt with the exception, **0.000** — the shipping artifact).
Counting those as well reaches nine, still not ten.

> **Correction (2026-08-24 review).** An earlier revision of this section said
> "all ten rolls … spread 0.000 … −0.428" and listed the 0.000 shipping
> artifact in the same table as the rolls. Both halves were wrong: there are
> **seven** rolls, their spread is **−0.004 … −0.428**, and **0.000 is the
> post-processed artifact, not a roll**. No roll ever measured 0.000.
> The corrected numbers make the caveat below *stronger*, not weaker.

**This must not be glossed.** fp2a's closure is real
and independently verified, but it is one favourable placement, not a robust
margin — consistent with the ±ns placer non-determinism this device is known
for. Two things temper it: the failures in the other rolls are ordinary
datapath placement noise with **no new structural class**, and the shipping
design sits at a hard floor — four phys_opt directives with the exception in
force (`po_fp2a_exc.tcl`, `t5_20_physopt_with_exception.log`) returned
**0.000 unchanged every time**, and `route_design -preserve` left utilization,
per-SLR distribution and every per-clock number bit-identical to fp2a.

**Practical consequence for R-d and beyond: this bitstream is the artifact to
program; do not expect a fresh re-roll of the same recipe to close.** If the
netlist ever has to be rebuilt, budget a spread and expect to need several
rolls to land a closing one.

## 13.6 Final state — build_035, end to end

| | build_034 shipped | build_035 base | build_035 best | **SHIPPING** |
|---|---|---|---|---|
| WNS | −0.025 | −0.480 | −0.136 | **0.000** |
| TNS | −0.613 | −2076.719 | −132.442 | **0.000** |
| failing setup EP | 50 | 16,677 | 2,773 | **0** |
| custom-RTL EP | 50 | — | 2,540 | **0** |
| vendor-IP EP | 0 | — | 233 | **0** |
| failing hold EP | 0 | 0 | 0 | **0** |
| clocks with failures | 2 of 6 | 3 of 6 | 3 of 6 | **0 of 6** |
| W8 `xline` cone | n/a | — | 269 negative | **0 negative, +77…+221 ps** |
| waiver required | yes (−0.025) | — | — | **NONE** |

**build_035 is the first bitstream this project has produced that requires no
timing waiver at all.** build_034 shipped under one; build_030, build_028 and
build_026 all shipped negative. This one meets timing outright, with every line
of custom RTL closed and the W8 cone positive on all four channels.

Getting there cost no RTL: the whole distance from −0.136 to 0.000 was four
soft pblocks giving each matvec engine its own MIG's SLR, plus one `set_false_path`
extending a vendor exception across a scope gap in the vendor's own XDC.
