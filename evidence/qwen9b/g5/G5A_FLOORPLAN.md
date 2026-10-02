# G5a — the OOC floorplan experiment

**Task 13 of the Qwen3.5-9B migration. THE CRITICAL EXPERIMENT.** Track P
measured the binding path — the DN write-control fan-out, one logic level with
~96 % route, WNS −1.391 — and named "a pblock that pins each fan-out register
set into the clock region of the banks it drives" as the only proposed fix.
Nobody had tried it. This document is that experiment.

---

## 0. HOW TO READ EVERY NUMBER BELOW — stated before the numbers

This is Track P's own reading rule (`evidence/qwen_next/place_exp/PLACE_EXP.md`
§2.1), and it governs the whole document.

**Out-of-context means `layer_chan` ALONE on the whole VU9P.** No XDMA/PCIe/GTs
at their fixed sites, no four DDR4 MIGs anchored to their IO banks, no four
`matvec_chan`s, no `seq_unit`, and none of the ~200 K CLB LUTs a full build
spends outside `layer_0`. Therefore:

* a **failure here is DEFINITIVE** — the in-context problem is strictly harder;
* a **success here is NECESSARY BUT NOT SUFFICIENT** — it is the best case that
  exists, not a prediction of the full build.

**All timing below is POST-PLACE, PRE-ROUTE, PRE-`phys_opt_design`.** For a
design in the normal regime the final number is usually better (build_035
closed −0.091 → 0.000 in one `phys_opt` pass). For a design whose deficit is
unregistered SLR-spanning wire it is not, because routing has no shorter wire
to find.

**Directive spread is SAMPLED, NOT CHARACTERISED.** One directive change moved
WNS by 0.475 ns in Track P's own runs (PLACE_EXP.md §3.6). Every number here
carries that uncertainty, and it matters most where two numbers are close.
This document samples two directives (`Default`, `AltSpreadLogic_medium`) on
the unconstrained baseline and on the critical variant, and one directive
everywhere else.

**A partial result is a result.** A variant that moves −1.391 to −0.4 is not
closure; it is a direction, and the remaining gap is named rather than rounded
away. The house playbook has closed −0.091 in one `phys_opt` pass. It has
never been asked to close −1.4.

**Label.** Every number in §2 and §3 is **T (toolchain-measured)** — Vivado
2024.2 `synth_design -mode out_of_context` → `opt_design` → `place_design` on
`xcvu9p-fsgd2104-2L-e` at 4.000 ns, on snoke, on the SHIPPING `rtl/`.

### 0.1 The reading thresholds, stated before the numbers

The brief reserves two STOP protocols for the user and neither is this
document's to pre-make, so the test each one turns on is written down first.
**"Stated before", not "pre-registered":** there is no committed artefact that
carries these thresholds ahead of the runs — they were written into this
document's draft before the numbers came back, and you have only this sentence
for that. The 0.475 ns figure is not free-floating, though: it is Track P's one
measured directive spread (`evidence/qwen_next/place_exp/PLACE_EXP.md` §3.6),
so the threshold is inherited rather than chosen to fit.

| verdict | test on the **write-control fan-out** slack |
|---|---|
| **closes (OOC)** | MET, or within the band the house playbook has closed (≥ −0.1 ns) |
| **material direction** | improves on the same-directive baseline by **more than 0.475 ns**, the one sampled directive spread — i.e. more than placer noise can explain |
| **not material** | improves by ≤ 0.475 ns, or gets worse |

**If no constrained variant is better than "not material", that is the
target-invalidating negative** and the task stops back to the user. **If the
three-SLR floorplan closes only WITH a `layer_0` pblock, that is O4** and the
task stops back to the user. Both are reported, never decided here.

### 0.1a What the "DN write fan-out" column actually measures

`synth/exp_uram/scripts/exp_ooc.tcl:424` selects the endpoint set as **every
pin of every DN URAM288 cell**, so the column is the worst setup path into the
DN array by *any* pin, not specifically into a write-enable. Counted over the eleven `FAM_PATH DN_URAM_WRITE` lines: **seven end at
`BWE_B[*]` or `DIN_B[*]`** — a genuine write-control or write-data pin — (1'a,
1'b, 2', 3', 4'a, 4'b, 5') and **four end at `ADDR_A[*]`**, a read-address pin:
2'alt, **2'cr**, 5'cr and **6'**. **So both headline numbers the reader cares
about are address paths** — the chosen variant's −0.001 and 6''s +0.092 MET
(`g5_v2cr_family_run.log`, `ra_p_reg[1][2]/C -> g_dn[7].mem_reg_uram_28/ADDR_A[2]`).

**What rescues the reading is a stronger fact, not a weaker one.**
`evidence/qwen9b/g5/g5_v2cr_dn_write_fanout_paths.rpt` reports the ten worst
DN-array path blocks in 2'cr, and **every one of them ends at `ADDR_A` or
`ADDR_B`** — eight and two respectively — spanning −0.001 ns to **+0.050 ns**.
No write-enable and no write-data pin appears among them at all, so in 2'cr
**every `BWE_B` / `DIN_B` path is better than +0.050 ns**, comfortably MET.
**6' is the same shape and stronger**: all ten blocks of
`g5_v6_dn_write_fanout_paths.rpt` are `ADDR_A`/`ADDR_B` and every one is MET,
from +0.092 upward, so its write pins are better still. The
§5.1 reading survives more strongly than it was stated; the earlier sentence
claiming five-of-nine with 2'alt as the lone exception did not, and is corrected
here. (The count is of reported path BLOCKS: `report_timing -max_paths 10
-nworst 10` lists each of the five distinct endpoint pins twice, for the rising
and falling transition.) The column remains the right
instrument — address, write-enable and write-data all arrive on the same
per-group fan-out from the same registers — but it is a bound on the whole
fan-out, not a write-enable measurement.

### 0.2 What "a `layer_0` pblock" means, and a caveat the 2B record forces

`synth/constraints/fable5_floorplan_a.xdc:8-10` says the campaign winner's key result is
DELIBERATE ABSENCE of a `layer_0` pblock, because "constraining `layer_0` in
any form cost ~1 ns". Read `TIMING_035.md:716-735` for what was actually run:
variant **B** pinned `u_dn` + `u_attn` **as one cluster inside `layer_0`** into
SLR2 (−1.078), variant **C** pinned the compute cluster alone (−1.148), against
variant A's −0.004 with `layer_0` entirely free. **Neither B nor C pblocked the
`layer_0` instance as a whole — both constrained cells INSIDE it.** So the 2B
lesson bears on *every* variant in this document, not only on the one that adds
a whole-design pblock; variants 2′, 3′ and 4′a all constrain cells inside
`layer_0`, and 4′b is the strongest form of the same question.

---

## 1. What was run

**The vehicle was re-pointed at the SHIPPING `rtl/`** (brief Step 1, second
option). `synth/exp_uram/scripts/exp_ooc.tcl:75` sets `Rtl` to `$RepoRoot/rtl`
and `synth/exp_uram/scripts/exp_ooc.tcl:166` echoes every file it reads as
`EXP_RTL_SRC`; all eleven run logs each
carry twelve of those lines naming `rtl/*.sv`
(`evidence/qwen9b/g5/005_step1_repoint.log`). `synth/exp_uram/rtl/` was NOT
refreshed and is byte-untouched: it is Track P's measured artifact and
`o3_cite_drift.py --plan` over a tree in which the twelve files had been
refreshed reported **UNSAFE — 8 stale, 1 collateral**, into
`evidence/qwen9b/g3/G3_4_LAYER.md` and `rtl/layer_chan.sv`. The refresh was
applied, planned, and reverted; the copy's staleness (950 diff lines in
`synth/exp_uram/rtl/layer_chan.sv` alone) is recorded in 005 rather than repaired.

**The configuration built is the SHIPPING one**, which is not exactly Track
P's: `DN_PIPE = 2` **with** `P2_WAIT = 1`: `a51bc8e:rtl/layer_chan.sv:337` is
`DN_P2WAIT = (DN_RLAT > 2) ? 1 : 0`, and the parameter reaches `dn_step` at
`a51bc8e:rtl/layer_chan.sv:521`. Track P's
`r2widepipe2` predates `P2_WAIT`. The difference is small and attributed:

> **On the `a51bc8e:` prefixes.** G5a measured the RTL as it shipped at
> `a51bc8e`; S2's two-slot caches (SEQ ISA v2.1) then rewrote those blocks,
> so the lines this gate quotes no longer exist at HEAD. Citations to them
> are PINNED to the tree that carries the quotation rather than re-anchored
> — re-anchoring would silently repoint a measurement at RTL it never ran
> against (class B, `evidence/qwen9b/g3/G3_4_LAYER.md` §15.5). Citations to
> code the rewrite left in place (`dn_rdq`) stay unpinned and name HEAD.

| | G5a, shipping `rtl/` | Track P `r2widepipe2` | delta |
|---|---|---|---|
| URAM288 | **928** | **928** | **0** |
| DN banks out of URAM | **0** | **0** | 0 |
| DSP48E2 | 1,836 | 1,838 | −2 |
| LUT as Logic | 109,728 | 109,305 | +423 |
| LUT as Distributed RAM | **600** | **344** | **+256** |
| CLB Registers | 79,078 | 78,948 | +130 |
| CARRY8 | 7,834 | 7,814 | +20 |
| RAMB36 / RAMB18 | 674 / 32 | 641 / 33 | +33 / −1 |

Sources: `evidence/qwen9b/g5/g5_v1a_util_synth.rpt`,
`evidence/qwen_next/place_exp/r2widepipe2_util_synth.rpt`. The **+256
distributed RAM** is exactly the `attn_core` `sc_mem` inference wobble Task 12
put on record (`a51bc8e:rtl/attn_core.sv:69`, 512 × 32 b, no `ram_style`): every G5a
run reports `EXP_SC_MEM: RAMB=0 LUTRAM=256`, i.e. it went to **LUTRAM**, the
same way Task 12's `DN_PIPE = 2` run went and the opposite way Track P's went.
It is immaterial to the DN write fan-out and is reported, not treated as a
delta. The remaining rows are two different designs — the twelve experiment
copies differ from `rtl/` by 12 to 950 lines each — not a `P2_WAIT` measurement.

**ELEVEN runs in four waves.** Seven concurrent on snoke launched 2026-09-03
20:19 MDT from one script; then, in fix round 1, **2'cr and 5' concurrently** at
22:48 and **5'cr** at 00:06 on 2026-09-04; then, in fix round 2, **6'** at
02:03. Each in its own never-reused out dir
(`synth/out_exp_uram_g5_*`). Measured per run (`evidence/qwen9b/g5/010_wallclock_memory.log`): `opt_design`
**357–428 s**, `place_design` **2,220–3,728 s**, peak memory **9,763–13,466 MB**
against snoke's 247 GB. Track P's single-run comparators were 380–461 s,
2,540–2,637 s and 11,722 MB, so seven-way contention cost little. Fix round
1's three runs took 2,475 / 2,604 / 2,577 s to place. The first seven runs
were launched from a working tree whose **nine dirty files are exactly what
commit `5ee5f0e` landed** — proved file by file in
`evidence/qwen9b/g5/006_bytelock_vehicle.log`.

**Every pblock took.** `synth/exp_uram/scripts/exp_ooc.tcl:268-284` copies
`synth/scripts/full_impl.tcl:50-59`'s
sanity block and makes an empty pblock a HARD STOP, because a pblock matching
zero cells is silently harmless in Vivado — which is exactly what the first
revision of these XDC files did (`evidence/qwen9b/g5/001_pblock_preflight.log`,
three `CRITICAL WARNING 12-1433`s and six empty pblocks). The live runs report
`pb_dn_grp* cells=10510`, `pb_dn_slr* cells=232`, `pb_layer0 cells=62333`.

**Those counts are PRE-`opt_design`** — `exp_ooc.tcl` reads the XDC and checks
the pblocks between `synth_design` and `opt_design`, which is what
"implementation-only" means here. `opt_design` then changes the netlist, so the
same pblocks report different membership afterwards: `pb_layer0` is
**62,563** post-place (`g5_v4b_finish_run.log`), 230 cells more than the 62,333
it was given. The difference is `opt_design`'s own doing (replication and
absorption — the placed netlist has `kv_layer_r_reg[2]_replica_1` and friends
that did not exist when the XDC was read), and a cell created inside a pinned
cell's cone inherits the pblock. Nothing escaped: the DN pblocks hold 232
URAM288 each in both counts.

---

## 2. The per-variant table

| # | variant | URAM288 | place result | SLR span (SLR0/1/2) | DN mux slack | DN write fan-out | **KV write fan-out** | WNS | TNS | failing EP |
|---|---|---|---|---|---|---|---|---|---|---|
| 1'a | no floorplan, Default | 928 | PLACED (2285 s) | 3 (320/312/296) | 0.048 | -1.141 | **-0.853** | -1.141 | -3020.119 | 8632 |
| 1'b | no floorplan, AltSpreadLogic_medium | 928 | PLACED (2431 s) | 3 (320/312/296) | 0.224 | -1.820 | **-1.014** | -1.820 | -4980.572 | 10088 |
| 2' | per-group fan-out co-location, Default | 928 | PLACED (2440 s) | 3 (304/312/312) | 0.207 | -0.463 | **-0.831** | -0.831 | -1416.742 | 6188 |
| 2'cr | 2' at CLOCK-REGION granularity, Default | 928 | PLACED (2475 s) | 3 (304/312/312) | 0.038 | -0.001 | **-0.368** | -0.554 | -230.377 | 2057 |
| 2'alt | per-group fan-out co-location, AltSpreadLogic_medium | 928 | PLACED (2538 s) | 3 (304/312/312) | 0.217 | -0.333 | **-0.990** | -1.115 | -3645.209 | 11121 |
| 3' | per-BANK fan-out co-location, DN_BPG=1, Default | 928 | PLACED (2887 s) | 3 (312/312/304) | -0.842 | -0.208 | **-1.216** | -1.442 | -6636.769 | 23217 |
| 4'a | DN array -> 3 SLRs (banks only), Default | 928 | PLACED (2220 s) | 3 (320/312/296) | 0.100 | -0.711 | **-0.769** | -1.469 | -1472.879 | 5936 |
| 4'b | 4'a + layer_0 pblock, Default | 928 | PLACED (3728 s) | 3 (307/320/301) | 0.111 | -0.477 | **-0.531** | -1.174 | -3933.103 | 11320 |
| 5' | KV array + its control regs into ONE SLR, Default | 928 | PLACED (2604 s) | 3 (319/319/290) | 0.101 | -0.525 | **0.315** | -0.663 | -2257.003 | 8705 |
| 5'cr | 5' + 2'cr's clock-region DN pins (the union), Default | 928 | PLACED (2577 s) | 3 (319/319/290) | 0.297 | -0.536 | **0.370** | -0.720 | -1456.269 | 6000 |
| 6' | 2'cr + the conv BRAM banks and their control regs, Default | 928 | PLACED (2543 s) | 3 (304/312/312) | 0.020 | 0.092 | **-0.559** | -0.896 | -1416.658 | 5436 |

Generated by `evidence/qwen9b/g5/g5_table.py` from the committed
`evidence/qwen9b/g5/g5_v*_summary.log`, `*_finish_run.log` and
`*_family_run.log` — the table is emitted from the logs rather than typed, so
it cannot say more than they say.

**All ELEVEN PLACED.** URAM288 is **928** in every run, DN non-URAM cells **0**,
and the array spans **three SLRs in every run** — A1.4's arithmetic (2 × 320 =
640 < 928) holds against the placer as well as on paper. Hold is clean
everywhere (WHS +0.013 to +0.019).


Worst-path decomposition, per variant (the whole reading of this experiment
turns on `one logic level, ~96 % route`):

| # | write fan-out worst path | levels | datapath | logic | route | route % | SLR |
|---|---|---|---|---|---|---|---|
| 1'a | `g_dnpipeN.g_grp[0].bs_p_reg[1][1]/C` -> `g_dnpipeN.g_grp[0].g_dn[0].mem_reg_uram_28/BWE_B[1]` | 1 | 4.720 | 0.226 | 4.494 | 95.2 | SLR1 -> SLR2 |
| 1'b | `g_dnpipeN.g_grp[2].bs_p_reg[1][3]/C` -> `g_dnpipeN.g_grp[2].g_dn[4].mem_reg_uram_24/BWE_B[3]` | 1 | 5.399 | 0.201 | 5.198 | 96.3 | SLR1 -> SLR2 |
| 2' | `g_dnpipeN.g_grp[2].bs_p_reg[1][4]/C` -> `g_dnpipeN.g_grp[2].g_dn[0].mem_reg_uram_22/BWE_B[7]` | 1 | 4.053 | 0.171 | 3.882 | 95.8 | SLR2 -> SLR2 |
| 2'cr | `g_dnpipeN.g_grp[0].ra_p_reg[1][2]/C` -> `g_dnpipeN.g_grp[0].g_dn[7].mem_reg_uram_28/ADDR_A[2]` | 0 | 3.479 | 0.079 | 3.400 | 97.7 | SLR0 -> SLR0 |
| 2'alt | `g_dnpipeN.g_grp[2].ra_p_reg[1][0]/C` -> `g_dnpipeN.g_grp[2].g_dn[1].mem_reg_uram_12/ADDR_A[0]` | 0 | 3.839 | 0.080 | 3.759 | 97.9 | SLR2 -> SLR2 |
| 3' | `g_dnpipeN.g_grp[14].bs_p_reg[1][1]/C` -> `g_dnpipeN.g_grp[14].g_dn[0].mem_reg_uram_6/BWE_B[3]` | 1 | 3.797 | 0.166 | 3.631 | 95.6 | SLR1 -> SLR1 |
| 4'a | `g_dnpipeN.g_grp[0].wd_p_reg[1][1127]/C` -> `g_dnpipeN.g_grp[0].g_dn[3].mem_reg_uram_15/DIN_B[47]` | 0 | 4.426 | 0.081 | 4.345 | 98.2 | SLR1 -> SLR0 |
| 4'b | `g_dnpipeN.g_grp[0].wd_p_reg[1][89]/C` -> `g_dnpipeN.g_grp[0].g_dn[5].mem_reg_uram_1/DIN_B[17]` | 0 | 4.128 | 0.081 | 4.047 | 98.0 | SLR1 -> SLR0 |
| 5' | `g_dnpipeN.g_grp[1].bs_p_reg[1][4]/C` -> `g_dnpipeN.g_grp[1].g_dn[0].mem_reg_uram_18/BWE_B[5]` | 1 | 4.106 | 0.229 | 3.877 | 94.4 | SLR1 -> SLR0 |
| 5'cr | `g_dnpipeN.g_grp[1].ra_p_reg[1][3]/C` -> `g_dnpipeN.g_grp[1].g_dn[7].mem_reg_uram_3/ADDR_A[3]` | 0 | 4.045 | 0.079 | 3.966 | 98.0 | SLR1 -> SLR2 |
| 6' | `g_dnpipeN.g_grp[0].ra_p_reg[1][2]/C` -> `g_dnpipeN.g_grp[0].g_dn[2].mem_reg_uram_1/ADDR_A[2]` | 0 | 3.386 | 0.079 | 3.307 | 97.7 | SLR0 -> SLR0 |

Structure, pblocks and the runs' own provenance:

| # | DN_BPG | directive | extra XDC | pblocks (cells) | group return | KV mux | WHS | sc_mem | opt s | place s |
|---|---|---|---|---|---|---|---|---|---|---|
| 1'a | 8 | Default | none | none | 0.234 | n/a | 0.019 | RAMB=0 LUTRAM=256 | 358 | 2285 |
| 1'b | 8 | AltSpreadLogic_medium | none | none | -0.027 | n/a | 0.013 | RAMB=0 LUTRAM=256 | 388 | 2431 |
| 2' | 8 | Default | fable5_floorplan_9b_dngrp.xdc | pb_dn_grp0=10510; pb_dn_grp1=10510; pb_dn_grp2=10510 | -0.373 | n/a | 0.019 | RAMB=0 LUTRAM=256 | 375 | 2440 |
| 2'cr | 8 | Default | fable5_floorplan_9b_dngrpcr.xdc | 6 pblocks, 2078..8432 cells | -0.304 | n/a | 0.019 | RAMB=0 LUTRAM=256 | 324 | 2475 |
| 2'alt | 8 | AltSpreadLogic_medium | fable5_floorplan_9b_dngrp.xdc | pb_dn_grp0=10510; pb_dn_grp1=10510; pb_dn_grp2=10510 | -0.488 | n/a | 0.019 | RAMB=0 LUTRAM=256 | 357 | 2538 |
| 3' | 1 | Default | fable5_floorplan_9b_dnbank.xdc | 24 pblocks, 4156..4156 cells | 0.572 | n/a | 0.019 | RAMB=0 LUTRAM=256 | 428 | 2887 |
| 4'a | 8 | Default | fable5_floorplan_9b_dnslr.xdc | pb_dn_slr0=232; pb_dn_slr1=232; pb_dn_slr2=232 | -0.588 | n/a | 0.016 | RAMB=0 LUTRAM=256 | 370 | 2220 |
| 4'b | 8 | Default | fable5_floorplan_9b_layer0.xdc, fable5_floorplan_9b_dnslr.xdc | pb_dn_slr0=232; pb_dn_slr1=232; pb_dn_slr2=232; pb_layer0=62333 | -0.478 | n/a | 0.019 | RAMB=0 LUTRAM=256 | 392 | 3728 |
| 5' | 8 | Default | fable5_floorplan_9b_kvslr.xdc | 7 pblocks, 60..10510 cells | -0.663 | n/a | 0.019 | RAMB=0 LUTRAM=256 | 318 | 2604 |
| 5'cr | 8 | Default | fable5_floorplan_9b_combo.xdc | 9 pblocks, 60..10270 cells | -0.720 | n/a | 0.006 | RAMB=0 LUTRAM=256 | 317 | 2577 |
| 6' | 8 | Default | fable5_floorplan_9b_convcr.xdc | 8 pblocks, 37..8432 cells | -0.548 | n/a | 0.019 | RAMB=0 LUTRAM=256 | 316 | 2543 |

**What owns the residual in each variant is §4.4**, which carries the family
table for all eleven runs. It is not repeated here.

---

## 3. THE ANSWER TO THE CRITICAL QUESTION: the pblock WORKS

The task exists to find out whether a placement constraint moves the DN
write-control fan-out off −1.391. Measured against **the same-directive
baseline on the same RTL**, it does, in every constrained variant:

| variant | what it pins, and at what granularity | DN write fan-out | vs its own baseline | material? (threshold 0.475 ns) |
|---|---|---|---|---|
| **1'a** `Default`, none | — | **−1.141** | baseline | — |
| **1'b** `AltSpreadLogic_medium`, none | — | **−1.820** | baseline | — |
| **4'a** the DN BANKS only | banks, SLR-wide | −0.711 | **+0.430** vs 1'a | **no** (just under) |
| **4'b** banks + `layer_0` | banks + every cell, SLR-wide | −0.477 | **+0.664** vs 1'a | **yes** |
| **2'** banks + `g_lmux` + LAST fan-out stage | SLR-wide | **−0.463** | **+0.678** vs 1'a | **yes** |
| **5'** 2'-style DN + the KV array in one SLR | SLR-wide, DN split 11/3/10 | −0.525 | **+0.616** vs 1'a | **yes** |
| **2'alt** the same as 2', `AltSpread` | SLR-wide | **−0.333** | **+1.487** vs 1'b | **yes** |
| **3'** per-BANK RTL, `DN_BPG = 1` | SLR-wide (see below) | **−0.208** | **+0.933** vs 1'a | **yes** |
| **5'cr** 5' + 2'cr's clock-region DN pins (the union) | CLOCK-REGION granular | −0.536 | **+0.605** vs 1'a | **yes** |
| **2'cr** the same members as 2' | **CLOCK-REGION granular** | **−0.001** | **+1.140** vs 1'a | **yes** |
| **6'** 2'cr + the conv BRAM banks | CLOCK-REGION granular | **+0.092 MET** | **+1.233** vs 1'a | **yes** |

**2'cr is the brief's own constraint, and it very nearly closes the path.**
The brief's Step 2 asks for a pblock pinning each fan-out register set "into the
CLOCK REGION of the banks it drives". Every DN pblock in the first seven runs is
SLR-WIDE — including 3''s twenty-four, which share only three SLR-wide ranges,
so the only per-bank thing about 3' is its RTL (`DN_BPG = 1`), not its
placement. 2'cr is the range-only refinement: banks + `g_lmux` into the SLR's
URAM clock-region columns X1..X4, and the LAST fan-out stage into the CENTRE
clock-region ROW of those columns. It takes the DN write fan-out to **−0.001 ns
with ZERO logic levels, `SLR0 -> SLR0`** — from −1.141 unconstrained.

**The mechanism is confirmed, and 4'a BOUNDS its contribution — it does not
isolate it.** Track P's diagnosis was that the fan-out registers sit near the
central write port while the banks they drive are an SLR away, and that
`dont_touch` stops synthesis merging the copies but nothing *places* them.
Variant **4'a pins the banks and nothing else** and buys +0.430; variant **2'
pins the banks AND the last fan-out stage** and buys +0.678; **3' does the same
at per-bank RTL granularity** and buys +0.933.

**Two metrics, and they rank the variants differently — so each is stated with
its own ordering.**

*By GAIN against the variant's own same-directive baseline* (the column above),
the order is **2'alt +1.487 > 6' +1.233 > 2'cr +1.140 > 3' +0.933 > 2' +0.678 >
4'b +0.664 > 5' +0.616 > 5'cr +0.605 > 4'a +0.430**. 2'alt leads because its
baseline is 1'b's −1.820, the worst of the eleven, so it has the most to
recover.

*By the ABSOLUTE slack the variant reaches* — which is what has to reach zero —
the order is **6' +0.092 > 2'cr −0.001 > 3' −0.208 > 2'alt −0.333 > 2' −0.463 >
4'b −0.477 > 5' −0.525 > 5'cr −0.536 > 4'a −0.711**. **6' is the only variant of
the eleven in which the DN write fan-out MEETS.** The worst path's SLR crossing disappears with it — 1'a is
`SLR1 -> SLR2`, 2' is `SLR2 -> SLR2`, 3' is `SLR1 -> SLR1`.

**But the +0.248 between 4'a and 2' is an upper bound on the fan-out
registers' contribution, not a measurement of it**, because 2' pins a third
thing 4'a does not: `synth/constraints/fable5_floorplan_9b_dngrp.xdc:78` also
pins **`g_lmux`**, the group's local read mux and its first return register
`rq_p_reg[0]` (`a51bc8e:rtl/layer_chan.sv:640-643`). That pin was not inert — §4.3
shows it moved the DN group-return path from +0.234 to −0.373 — so some
unknown share of the +0.248 belongs to it. Separating them would need a fourth
variant pinning banks + fan-out registers WITHOUT `g_lmux`, which was not run.

**3' also settles the §3.8 question it was built for.** Per-bank fan-out was
*worse* unconstrained (Track P, −1.956) and the hypothesis was that it was worse
only because nothing placed the copies. On the named path that hypothesis is
**correct**: constrained, `DN_BPG = 1` takes the write fan-out to −0.208 (one
logic level, 95.6 % route, no SLR crossing), better than every SLR-wide variant
— though **not the best of the eleven: 6' MEETS at +0.092 and 2'cr is −0.001**,
both at `DN_BPG = 8` with a clock-region range. So the gain came from PLACEMENT granularity, not from the
per-bank RTL. 3' is still the worst variant on TNS (−6,636.8) and on failing endpoints
(23,217) — though not on WNS, where 1'b's −1.820 is worse. See §4.

**So the target-invalidating negative does NOT fire.** The brief's second STOP
is "if none of 2', 3' or 4' moves the write-control fan-out materially off
−1.391". All three move it, by 0.43 to 1.49 ns, far outside the one sampled
directive spread.

---

## 4. AND THE MODULE STILL DOES NOT CLOSE — the binding path MOVED

| variant | DN write | KV write | **WNS** | what owns the WNS path now |
|---|---|---|---|---|
| 1'a | −1.141 | −0.853 | **−1.141** | the DN write fan-out itself |
| 1'b | −1.820 | −1.014 | −1.820 | the DN write fan-out itself |
| 2' | −0.463 | −0.831 | −0.831 | the KV cache write fan-out |
| 2'alt | −0.333 | −0.990 | −1.115 | a KV URAM read into `u_attn`'s DSP lanes |
| 3' | −0.208 | −1.216 | −1.442 | inside `u_attn` (and the DN read mux collapses to −0.842) |
| 4'a | −0.711 | −0.769 | −1.469 | the conv BRAM write |
| 4'b | −0.477 | −0.531 | −1.174 | a KV URAM read into `u_attn`'s DSP lanes |
| **5'** | −0.525 | **+0.315 MET** | −0.663 | `u_attn`'s DSP lanes and the DN group return, tied |
| **2'cr** | **−0.001** | −0.368 | **−0.554** | **the conv BRAM write** |
| 5'cr † | −0.536 | +0.370 MET | −0.720 | the DN group return, 195 of the 200 worst |
| 6' | **+0.092 MET** | −0.559 | −0.896 | `u_attn`'s DSP lanes, 179 of the 200 worst |

† 5'cr was run beyond the controller's ruling — see §5.5.

**The KV write fan-out was never a fixed residual.** Across the **nine** runs
that constrain nothing about it — 1'a, 1'b, 2', 2'cr, 2'alt, 3', 4'a, 4'b and
6' (whose XDC touches only `*g_cv*`, `st_reg*` and `dn_layer_r_reg*`) — it
moves from **−0.368 (2'cr) to −1.216 (3')**, a **0.848 ns spread produced
entirely by where the placer happened to put an unconstrained array**. Round 1
of this document quoted 2''s −0.831 as if it were a property of the design. It
is one draw.

2''s WNS is −0.831 against 1'a's −1.141: the SLR-wide floorplan bought only
**0.310 ns of WNS**, *inside* the sampled directive spread, even though the path
it was aimed at moved 0.678 ns. **2'cr, the clock-region version, improves WNS by 0.587 ns
to −0.554, the best WNS of the eleven.**

**Why: `synth/exp_uram/scripts/family_census.tcl` on each run's own
`post_place.dcp`** (the full per-variant set is §4.4). For the
baseline, the 200 worst setup paths in the design are **100 % DN write
fan-out**. For 2', the DN write fan-out is not in the 200 worst at all:

**1'a — no floorplan, Default**

| family | endpoints | worst slack | levels | datapath | logic | route | route % | SLR | in the 200 worst |
|---|---|---|---|---|---|---|---|---|---|
| DN_URAM_WRITE | 720 | -1.141 | 1 | 4.720 | 0.226 | 4.494 | 95.2 | SLR1->SLR2 | 200 paths, worst -1.141 |
| KV_URAM_WRITE | 240 | -0.853 | 1 | 4.432 | 0.175 | 4.257 | 96.1 | SLR1->SLR0 | — |
| KV_EXP_MEM | 8 | 1.521 | 0 | 2.088 | 0.080 | 2.008 | 96.2 | SLR0->SLR1 | — |
| CONV_BRAM | 4223 | -0.686 | 2 | 4.556 | 0.231 | 4.325 | 94.9 | SLR1->SLR0 | — |
| ATTN_DSP | 85376 | -0.590 | 2 | 4.298 | 0.199 | 4.099 | 95.4 | SLR1->SLR0 | — |
| DN_MUX_OREG | 2048 | 0.048 | 1 | 3.931 | 0.202 | 3.729 | 94.9 | SLR2->SLR1 | — |
| DN_GRP_RETURN | 18432 | 0.234 | 2 | 3.693 | 1.467 | 2.226 | 60.3 | SLR2->SLR2 | — |

**2' — per-group fan-out co-location, Default**

| family | endpoints | worst slack | levels | datapath | logic | route | route % | SLR | in the 200 worst |
|---|---|---|---|---|---|---|---|---|---|
| DN_URAM_WRITE | 720 | -0.463 | 1 | 4.053 | 0.171 | 3.882 | 95.8 | SLR2->SLR2 | — |
| KV_URAM_WRITE | 240 | -0.831 | 1 | 4.412 | 0.169 | 4.243 | 96.2 | SLR1->SLR0 | 167 paths, worst -0.831 |
| KV_EXP_MEM | 8 | 1.052 | 1 | 2.581 | 0.116 | 2.465 | 95.5 | SLR1->SLR1 | — |
| CONV_BRAM | 4223 | -0.474 | 3 | 4.346 | 0.305 | 4.041 | 93.0 | SLR1->SLR2 | — |
| ATTN_DSP | 85460 | -0.565 | 2 | 4.229 | 1.404 | 2.825 | 66.8 | SLR2->SLR1 | 33 paths, worst -0.565 |
| DN_MUX_OREG | 2048 | 0.207 | 1 | 3.770 | 0.115 | 3.655 | 96.9 | SLR0->SLR1 | — |
| DN_GRP_RETURN | 18432 | -0.373 | 0 | 4.352 | 0.079 | 4.273 | 98.2 | SLR0->SLR1 | — |


### 4.1 The residual is the SAME failure, on the array nothing constrained

2''s worst path is
`kv_layer_r_reg[0]/C -> g_kv[2].mem_reg_uram_22/BWE_B[3]` — **one logic level,
route 4.243 of 4.412 ns (96.2 %), `SLR1 -> SLR0`**. Put that beside the path
this whole task was built to fix
(`bs_p_reg[1][1] -> g_dn[0].mem_reg_uram_28/BWE_B[1]`, one logic level, 95.2 %
route, `SLR1 -> SLR2`) and they are the same failure with a different array
name: a write-control register broadcasting to a URAM bank an SLR away, with
essentially all of the delay in the wire. 167 of the 200 worst paths in 2' are
that family; the other 33 are `u_attn`'s DSP lanes fed from a **KV URAM read**
that crosses `SLR2 -> SLR1`.

### 4.2 A pblock CAN fix the KV array — MEASURED, and round 1 had this wrong

Round 1 of this document said "a pblock CANNOT fix the KV array" and gave two
independent reasons. **Reason (a) was wrong, and variant 5' is the measurement
that shows it.**

**What round 1 claimed.** "The KV cache is 8 banks × 29 = 232 URAM288, and a DN
group is also 232. One SLR holds 320. 232 + 232 = 464 > 320, so with 928 of 960
URAM288 in use the KV array MUST scatter across all three SLRs no matter how it
is floorplanned."

**Why it was wrong.** The arithmetic is only binding **if the DN array is split
evenly, 8 banks per SLR** — which every round-1 variant did because the pblocks
were written that way. Nothing forces it. An **11 / 3 / 10** bank split is
319 / 87+232 / 290 URAM288, so the SLR carrying only 3 DN banks has **233 free —
one more than the KV array needs.** And the document's own evidence already
contradicted the claim: in the *unconstrained* 1'a run the placer put the KV
array in **two** SLRs by itself (`evidence/qwen9b/g5/g5_v1a_uram_slr_census.rpt`,
`KV_CACHE : SLR0=200 SLR1=32`).

**What 5' measures** (`synth/constraints/fable5_floorplan_9b_kvslr.xdc`): the
whole KV array plus its write-control and read-return registers pinned into
SLR1, DN split 11 / 3 / 10 to make room.

| 5' | measured |
|---|---|
| where the KV array landed | **`FIN_KV_URAM_BY_SLR: SLR1=232`** — all of it, one SLR |
| KV write fan-out | **+0.315 ns, MET** (was −0.831 in 2') |
| that path | `kv_layer_r_reg[2]/C -> g_kv[3].mem_reg_uram_0/BWE_B[1]`, **`SLR1 -> SLR1`**, 1 logic level (LUT4), route 3.121 of 3.274 ns |
| per-SLR URAM288 | 319 / 319 / 290 of 320 |
| DN write fan-out | −0.525 (2' was −0.463 — the price of the uneven split) |
| WNS / TNS / failing EP | −0.663 / −2,257.0 / 8,705 |

The full report is `evidence/qwen9b/g5/g5_v5_kv_write_fanout_paths.rpt`, whose
first block reads `Slack (MET) : 0.315ns`. **A floorplan removes the KV SLR
crossing.** What it costs is `g_grp[1]`, which straddles all three SLRs 3/3/2
under the uneven split and drags the DN write fan-out back by 0.062 ns.

**Reason (b) still stands, and it is now the only one.** `a51bc8e:rtl/layer_chan.sv:712-724`
drives `kv_we`, `kv_wa_f`, `kv_wrow` and `kv_bsel` combinationally to all eight
banks in one cycle: there is **no `KV_PIPE` analogue of `DN_PIPE`**, so nothing
puts a register next to the KV banks for a pblock to pin. 5' works by pinning
the *source* registers into the same SLR as the banks — which is available only
because the whole array fits in one SLR. It is a real fix and it is a narrower
one than the DN array's: the DN fix survives the array spanning three SLRs
because `DN_PIPE = 2` gives it a register per group to pin, and the KV fix does
not have that fallback.

### 4.3 What the floorplan cost

2' more than doubled SLR crossings: **6,290 SLLs (1'a) -> 13,621 (2')**, with
`SLR2 <-> SLR1` at 50.47 % and `SLR1 <-> SLR0` at 28.36 % of the 17,280
available (`evidence/qwen9b/g5/g5_v1a_util_placed_slr.rpt` and
`evidence/qwen9b/g5/g5_v2_util_placed_slr.rpt`). Pinning each DN group into its
own SLR while the logic stayed central is what bought that. It also regressed
the DN per-group return path from **+0.234 to −0.373** (0 logic levels, 98.2 %
route, `SLR0 -> SLR1`): the co-location pushed the return crossing out of the
group. Neither is binding today, and both are named here because they are the
next things a tighter floorplan would have to hold.

**Per-SLR capacity, checked post-place for the four variants that matter
(the standing rule).** Nothing overflows in any of them:

| | URAM288 of 320 | DSP48E2 of 2,280 | Block RAM Tile of 720 | CLB LUTs % | SLLs |
|---|---|---|---|---|---|
| 2' | 304 / 312 / 312 | 152 / 1,490 / 194 | 0 / 498 / 192 | 4.2 / 21.2 / 2.3 | 13,621 |
| **2'cr** (chosen) | 304 / 312 / 312 | 166 / **1,504** / 166 | 0 / **450** / 240 | 4.0 / 19.3 / 4.4 | **11,029** |
| 5' | **319 / 319 / 290** | 0 / **1,836** / 0 | 0 / 498 / 192 | 1.0 / 24.8 / 1.2 | 20,802 |
| 6' | 304 / 312 / 312 | 166 / 1,475 / 195 | 0 / **627.5** / 62.5 | 4.0 / 16.9 / 6.7 | 11,548 |

(`g5_v2_util_placed_slr.rpt`, `g5_v2cr_util_placed_slr.rpt`,
`g5_v5_util_placed_slr.rpt`, `g5_v6_util_placed_slr.rpt`.) **6''s SLR1 block
RAM at 627.5 of 720 (87.2 %) is the tightest block-RAM figure of the campaign,
and §5.6 is what it cost.** The DN pblocks hold no DSP and no block RAM, so
the 1,836 DSPs and ~690 BRAM tiles are unconstrained in every variant; the
placer puts them in SLR1 on its own, and 5' puts **all** of them there
(DSP 1,836 / 1,836 in SLR1, 80.5 %). 5' and 5'cr share the most URAM-tight
partition, 99.69 % of two SLRs — which is what the 11 / 3 / 10 split costs.

**And the chosen variant costs the fewest SLR crossings of any CONSTRAINED
variant** (`superlative-check: scoped` — the claim is over the constrained
subset, and the script prints the full ranking beside it): 2'cr uses 11,029
SLLs, and the **full ranking log 027 prints beside the claim** is
**1'b 5,967 < 1'a 6,290 < 2'cr 11,029 < 4'a 11,136 < 6' 11,548 < 2' 13,621 <
2'alt 14,016 < 4'b 16,756 < 5'cr 20,738 < 5' 20,802 < 3' 22,634**. **4'a at
11,136 is the closest constrained variant — 107 SLLs behind — and it is named
here rather than skipped**; every
constrained variant is above the unconstrained 1'a's 6,290 and 1'b's 5,967 —
a floorplan buys locality by spending crossings elsewhere.  *(Ranking
completed 2026-09-10: the sentence quoted four of the ten other variants and
omitted the runner-up.)*


### 4.4 What owns the residual, every variant

`synth/exp_uram/scripts/family_census.tcl` on each run's own `post_place.dcp`:
the worst setup path into each named family, and the family histogram of the
200 worst setup PATHS. "cells" is a count of endpoint CELLS, not of timing
endpoints — one URAM288 carries many endpoint pins.

**1'a — no floorplan, Default**

| family | endpoints | worst slack | levels | datapath | logic | route | route % | SLR | in the 200 worst |
|---|---|---|---|---|---|---|---|---|---|
| DN_URAM_WRITE | 720 | -1.141 | 1 | 4.720 | 0.226 | 4.494 | 95.2 | SLR1->SLR2 | 200 paths, worst -1.141 |
| KV_URAM_WRITE | 240 | -0.853 | 1 | 4.432 | 0.175 | 4.257 | 96.1 | SLR1->SLR0 | — |
| KV_EXP_MEM | 8 | 1.521 | 0 | 2.088 | 0.080 | 2.008 | 96.2 | SLR0->SLR1 | — |
| CONV_BRAM | 4223 | -0.686 | 2 | 4.556 | 0.231 | 4.325 | 94.9 | SLR1->SLR0 | — |
| ATTN_DSP | 85376 | -0.590 | 2 | 4.298 | 0.199 | 4.099 | 95.4 | SLR1->SLR0 | — |
| DN_MUX_OREG | 2048 | 0.048 | 1 | 3.931 | 0.202 | 3.729 | 94.9 | SLR2->SLR1 | — |
| DN_GRP_RETURN | 18432 | 0.234 | 2 | 3.693 | 1.467 | 2.226 | 60.3 | SLR2->SLR2 | — |

**1'b — no floorplan, AltSpreadLogic_medium**

| family | endpoints | worst slack | levels | datapath | logic | route | route % | SLR | in the 200 worst |
|---|---|---|---|---|---|---|---|---|---|
| DN_URAM_WRITE | 720 | -1.820 | 1 | 5.399 | 0.201 | 5.198 | 96.3 | SLR1->SLR2 | 200 paths, worst -1.820 |
| KV_URAM_WRITE | 240 | -1.014 | 1 | 4.593 | 0.115 | 4.478 | 97.5 | SLR1->SLR0 | — |
| KV_EXP_MEM | 8 | 1.661 | 0 | 1.966 | 0.079 | 1.887 | 96.0 | SLR0->SLR1 | — |
| CONV_BRAM | 4223 | -0.328 | 7 | 4.262 | 2.508 | 1.754 | 41.2 | SLR0->SLR0 | — |
| ATTN_DSP | 85267 | -0.648 | 2 | 4.300 | 1.402 | 2.898 | 67.4 | SLR0->SLR0 | — |
| DN_MUX_OREG | 2048 | 0.224 | 1 | 3.753 | 0.180 | 3.573 | 95.2 | SLR2->SLR1 | — |
| DN_GRP_RETURN | 18432 | -0.027 | 2 | 3.954 | 1.458 | 2.496 | 63.1 | SLR2->SLR2 | — |

**2' — per-group fan-out co-location, Default**

| family | endpoints | worst slack | levels | datapath | logic | route | route % | SLR | in the 200 worst |
|---|---|---|---|---|---|---|---|---|---|
| DN_URAM_WRITE | 720 | -0.463 | 1 | 4.053 | 0.171 | 3.882 | 95.8 | SLR2->SLR2 | — |
| KV_URAM_WRITE | 240 | -0.831 | 1 | 4.412 | 0.169 | 4.243 | 96.2 | SLR1->SLR0 | 167 paths, worst -0.831 |
| KV_EXP_MEM | 8 | 1.052 | 1 | 2.581 | 0.116 | 2.465 | 95.5 | SLR1->SLR1 | — |
| CONV_BRAM | 4223 | -0.474 | 3 | 4.346 | 0.305 | 4.041 | 93.0 | SLR1->SLR2 | — |
| ATTN_DSP | 85460 | -0.565 | 2 | 4.229 | 1.404 | 2.825 | 66.8 | SLR2->SLR1 | 33 paths, worst -0.565 |
| DN_MUX_OREG | 2048 | 0.207 | 1 | 3.770 | 0.115 | 3.655 | 96.9 | SLR0->SLR1 | — |
| DN_GRP_RETURN | 18432 | -0.373 | 0 | 4.352 | 0.079 | 4.273 | 98.2 | SLR0->SLR1 | — |

**2'cr — 2' at CLOCK-REGION granularity, Default**

| family | endpoints | worst slack | levels | datapath | logic | route | route % | SLR | in the 200 worst |
|---|---|---|---|---|---|---|---|---|---|
| DN_URAM_WRITE | 720 | -0.001 | 0 | 3.479 | 0.079 | 3.400 | 97.7 | SLR0->SLR0 | — |
| KV_URAM_WRITE | 240 | -0.368 | 1 | 3.949 | 0.117 | 3.832 | 97.0 | SLR1->SLR0 | 57 paths, worst -0.368 |
| KV_EXP_MEM | 8 | 1.749 | 0 | 1.937 | 0.079 | 1.858 | 95.9 | SLR0->SLR1 | — |
| CONV_BRAM | 4223 | -0.554 | 3 | 4.426 | 0.298 | 4.128 | 93.3 | SLR1->SLR2 | 89 paths, worst -0.554 |
| ATTN_DSP | 85256 | -0.297 | 2 | 3.958 | 1.410 | 2.548 | 64.4 | SLR1->SLR1 | 33 paths, worst -0.297 |
| DN_MUX_OREG | 2048 | 0.038 | 1 | 3.941 | 0.115 | 3.826 | 97.1 | SLR0->SLR1 | — |
| DN_GRP_RETURN | 18432 | -0.304 | 2 | 4.231 | 1.408 | 2.823 | 66.7 | SLR2->SLR2 | 6 paths, worst -0.304 |

**2'alt — per-group fan-out co-location, AltSpreadLogic_medium**

| family | endpoints | worst slack | levels | datapath | logic | route | route % | SLR | in the 200 worst |
|---|---|---|---|---|---|---|---|---|---|
| DN_URAM_WRITE | 720 | -0.333 | 0 | 3.839 | 0.080 | 3.759 | 97.9 | SLR2->SLR2 | — |
| KV_URAM_WRITE | 240 | -0.990 | 1 | 4.571 | 0.116 | 4.455 | 97.5 | SLR1->SLR0 | — |
| KV_EXP_MEM | 8 | 1.573 | 1 | 2.009 | 0.168 | 1.841 | 91.6 | SLR1->SLR1 | — |
| CONV_BRAM | 4223 | -0.545 | 3 | 4.415 | 0.199 | 4.216 | 95.5 | SLR1->SLR2 | — |
| ATTN_DSP | 85566 | -1.115 | 2 | 4.734 | 1.424 | 3.310 | 69.9 | SLR2->SLR1 | 200 paths, worst -1.115 |
| DN_MUX_OREG | 2048 | 0.217 | 1 | 3.760 | 0.119 | 3.641 | 96.8 | SLR0->SLR1 | — |
| DN_GRP_RETURN | 18432 | -0.488 | 0 | 4.467 | 0.079 | 4.388 | 98.2 | SLR2->SLR1 | — |

**3' — per-BANK fan-out co-location, DN_BPG=1, Default**

| family | endpoints | worst slack | levels | datapath | logic | route | route % | SLR | in the 200 worst |
|---|---|---|---|---|---|---|---|---|---|
| DN_URAM_WRITE | 720 | -0.208 | 1 | 3.797 | 0.166 | 3.631 | 95.6 | SLR1->SLR1 | — |
| KV_URAM_WRITE | 240 | -1.216 | 1 | 4.796 | 0.179 | 4.617 | 96.3 | SLR1->SLR0 | 109 paths, worst -1.216 |
| KV_EXP_MEM | 8 | 1.894 | 0 | 1.776 | 0.076 | 1.700 | 95.7 | SLR1->SLR1 | — |
| CONV_BRAM | 4223 | -1.170 | 4 | 5.042 | 0.250 | 4.792 | 95.0 | SLR1->SLR2 | 4 paths, worst -1.170 |
| ATTN_DSP | 85821 | -1.442 | 2 | 5.254 | 0.150 | 5.104 | 97.1 | SLR0->SLR2 | 77 paths, worst -1.442 |
| DN_MUX_OREG | 2048 | -0.842 | 3 | 4.819 | 0.333 | 4.486 | 93.1 | SLR0->SLR1 | — |
| DN_GRP_RETURN | 98304 | 0.572 | 0 | 3.356 | 1.202 | 2.154 | 64.2 | SLR2->SLR2 | — |

**4'a — DN array -> 3 SLRs (banks only), Default**

| family | endpoints | worst slack | levels | datapath | logic | route | route % | SLR | in the 200 worst |
|---|---|---|---|---|---|---|---|---|---|
| DN_URAM_WRITE | 720 | -0.711 | 0 | 4.426 | 0.081 | 4.345 | 98.2 | SLR1->SLR0 | 3 paths, worst -0.711 |
| KV_URAM_WRITE | 240 | -0.769 | 1 | 4.348 | 0.114 | 4.234 | 97.4 | SLR1->SLR2 | 51 paths, worst -0.769 |
| KV_EXP_MEM | 8 | 1.103 | 0 | 2.538 | 0.081 | 2.457 | 96.8 | SLR2->SLR1 | — |
| CONV_BRAM | 4223 | -1.469 | 4 | 5.341 | 0.222 | 5.119 | 95.8 | SLR1->SLR0 | 42 paths, worst -1.469 |
| ATTN_DSP | 85542 | -0.696 | 5 | 4.682 | 1.526 | 3.156 | 67.4 | SLR2->SLR1 | 101 paths, worst -0.696 |
| DN_MUX_OREG | 2048 | 0.100 | 1 | 3.877 | 0.111 | 3.766 | 97.1 | SLR0->SLR1 | — |
| DN_GRP_RETURN | 18432 | -0.588 | 2 | 4.515 | 1.459 | 3.056 | 67.7 | SLR0->SLR0 | — |

**4'b — 4'a + layer_0 pblock, Default**

| family | endpoints | worst slack | levels | datapath | logic | route | route % | SLR | in the 200 worst |
|---|---|---|---|---|---|---|---|---|---|
| DN_URAM_WRITE | 720 | -0.477 | 0 | 4.128 | 0.081 | 4.047 | 98.0 | SLR1->SLR0 | — |
| KV_URAM_WRITE | 240 | -0.531 | 1 | 4.110 | 0.117 | 3.993 | 97.2 | SLR1->SLR2 | — |
| KV_EXP_MEM | 8 | 1.585 | 1 | 1.995 | 0.114 | 1.881 | 94.3 | SLR1->SLR1 | — |
| CONV_BRAM | 4223 | -1.068 | 3 | 4.938 | 0.250 | 4.688 | 94.9 | SLR1->SLR0 | 1 paths, worst -1.068 |
| ATTN_DSP | 85823 | -1.174 | 2 | 4.828 | 1.410 | 3.418 | 70.8 | SLR0->SLR1 | 199 paths, worst -1.174 |
| DN_MUX_OREG | 2048 | 0.111 | 1 | 3.867 | 0.116 | 3.751 | 97.0 | SLR0->SLR1 | — |
| DN_GRP_RETURN | 18432 | -0.478 | 0 | 4.455 | 0.078 | 4.377 | 98.2 | SLR0->SLR1 | — |

**5' — KV array + its control regs into ONE SLR, Default**

| family | endpoints | worst slack | levels | datapath | logic | route | route % | SLR | in the 200 worst |
|---|---|---|---|---|---|---|---|---|---|
| DN_URAM_WRITE | 720 | -0.525 | 1 | 4.106 | 0.229 | 3.877 | 94.4 | SLR1->SLR0 | — |
| KV_URAM_WRITE | 240 | 0.315 | 1 | 3.274 | 0.153 | 3.121 | 95.3 | SLR1->SLR1 | — |
| KV_EXP_MEM | 8 | 0.962 | 1 | 2.670 | 0.130 | 2.540 | 95.1 | SLR1->SLR1 | — |
| CONV_BRAM | 4223 | -0.454 | 3 | 4.326 | 0.299 | 4.027 | 93.1 | SLR1->SLR2 | — |
| ATTN_DSP | 85613 | -0.663 | 2 | 4.308 | 1.352 | 2.956 | 68.6 | SLR1->SLR1 | 68 paths, worst -0.663 |
| DN_MUX_OREG | 2048 | 0.101 | 1 | 3.876 | 0.204 | 3.672 | 94.7 | SLR2->SLR1 | — |
| DN_GRP_RETURN | 18432 | -0.663 | 2 | 4.587 | 1.433 | 3.154 | 68.8 | SLR2->SLR1 | 132 paths, worst -0.663 |

**5'cr — 5' + 2'cr's clock-region DN pins (the union), Default**

| family | endpoints | worst slack | levels | datapath | logic | route | route % | SLR | in the 200 worst |
|---|---|---|---|---|---|---|---|---|---|
| DN_URAM_WRITE | 720 | -0.536 | 0 | 4.045 | 0.079 | 3.966 | 98.0 | SLR1->SLR2 | — |
| KV_URAM_WRITE | 240 | 0.370 | 1 | 3.220 | 0.129 | 3.091 | 96.0 | SLR1->SLR1 | — |
| KV_EXP_MEM | 8 | 1.427 | 1 | 2.154 | 0.129 | 2.025 | 94.0 | SLR1->SLR1 | — |
| CONV_BRAM | 4223 | -0.629 | 4 | 4.500 | 0.225 | 4.275 | 95.0 | SLR1->SLR2 | 1 paths, worst -0.629 |
| ATTN_DSP | 85413 | -0.666 | 2 | 4.319 | 1.382 | 2.937 | 68.0 | SLR1->SLR1 | 4 paths, worst -0.666 |
| DN_MUX_OREG | 2048 | 0.297 | 1 | 3.681 | 0.204 | 3.477 | 94.5 | SLR2->SLR1 | — |
| DN_GRP_RETURN | 18432 | -0.720 | 2 | 4.644 | 1.447 | 3.197 | 68.8 | SLR2->SLR1 | 195 paths, worst -0.720 |

**6' — 2'cr + the conv BRAM banks and their control regs, Default**

| family | endpoints | worst slack | levels | datapath | logic | route | route % | SLR | in the 200 worst |
|---|---|---|---|---|---|---|---|---|---|
| DN_URAM_WRITE | 720 | 0.092 | 0 | 3.386 | 0.079 | 3.307 | 97.7 | SLR0->SLR0 | — |
| KV_URAM_WRITE | 240 | -0.559 | 1 | 4.139 | 0.177 | 3.962 | 95.7 | SLR1->SLR0 | 18 paths, worst -0.559 |
| KV_EXP_MEM | 8 | 0.737 | 1 | 2.897 | 0.118 | 2.779 | 95.9 | SLR1->SLR1 | — |
| CONV_BRAM | 4223 | -0.548 | 2 | 4.420 | 0.230 | 4.190 | 94.8 | SLR2->SLR1 | 1 paths, worst -0.548 |
| ATTN_DSP | 85812 | -0.896 | 2 | 4.708 | 0.217 | 4.491 | 95.4 | SLR2->SLR0 | 179 paths, worst -0.896 |
| DN_MUX_OREG | 2048 | 0.020 | 1 | 3.957 | 0.114 | 3.843 | 97.1 | SLR0->SLR1 | — |
| DN_GRP_RETURN | 18432 | -0.548 | 2 | 4.475 | 1.439 | 3.036 | 67.8 | SLR0->SLR0 | 1 paths, worst -0.548 |

**Read down the histogram column and the shape of the campaign is plain.**
Unconstrained (1'a) the DN write fan-out owns all 200. Constrain it (2') and the
KV write fan-out owns 167. Constrain that too (5') and `u_attn`'s DSP lanes and
the DN group return own it. Tighten the DN pin to clock regions (2'cr) and the
**conv BRAM write** owns 89 of 200 at −0.554. Combine both floorplans (5'cr)
and the **DN group return** owns 195 of 200. Each constraint removes its family
and the next one surfaces, and every one of them has the same signature — one
to four logic levels and 93-98 % route. **6' is where the pattern stops**: pin
the conv banks too and the conv family does NOT move (−0.554 → −0.548), while
`u_attn`'s DSP lanes go −0.297 → −0.896 and take 179 of the 200 worst. See
§5.6.

---

## 5. The two STOP protocols, and the decision

### 5.1 The target-invalidating negative — DOES NOT FIRE

The test is "none of 2', 3' or 4' moves the write-control fan-out materially off
−1.391". All three move it, and on the enlarged set the movement is not marginal:
**+0.430 (4'a), +0.605 (5'cr), +0.616 (5'), +0.664 (4'b), +0.678 (2'), +0.933
(3'), +1.140 (2'cr), +1.233 (6')** against the Default baseline — 6''s is the
largest of those — and **+1.487 (2'alt)** against the AltSpread one. 2'cr takes the path the whole task was built for to **−0.001 ns**.
Option B's binding path as Track P named it has a working fix, and the fix is a
pblock.

### 5.2 O4 — DOES NOT FIRE either, and the `layer_0` pblock HELPED

The condition is "the three-SLR floorplan closes only WITH a `layer_0` pblock".
It closes with **neither**: 4'a is WNS −1.469, 4'b is −1.174. The conditional
never triggers, so **there is no O4 question to put to the user from this
experiment** — and the chosen XDC (§5.3) has no `layer_0` pblock, so the 2B
campaign's lesson is not touched.

Worth recording anyway, because it points the opposite way to that lesson:
adding the `layer_0` pblock made things **better**, not worse — WNS −1.469 →
−1.174 (+0.295), DN write fan-out −0.711 → −0.477 (+0.234). Two caveats keep it
from being a finding: `TIMING_035.md:716-735`'s variants B and C constrained
cells *inside* `layer_0` on a design where `layer_0` was not the binding block,
and a single directive draw carries ±0.475 ns. And it does not affect the
decision — both 4' variants are far worse than 2'cr.

### 5.3 The chosen XDC, re-decided on the enlarged set

**The criterion, stated before the scoring.** The chosen XDC is the one Task 14
should start from, so it is scored on **WNS first** — that is the number that
has to reach zero — then **TNS**, which measures how much work a `phys_opt` pass
would face, then **failing endpoints**, which measures over how many places that
work is spread. Where two variants are within the one sampled directive spread
(0.475 ns) on WNS, the tie breaks on TNS.

| # | WNS | TNS | failing EP (of total) |
|---|---|---|---|
| **2'cr** | **−0.554** | **−230.4** | **2,057** (0.45 %) |
| 5' | −0.663 | −2,257.0 | 8,705 (1.92 %) |
| 5'cr † | −0.720 | −1,456.3 | 6,000 (1.33 %) |
| 2' | −0.831 | −1,416.7 | 6,188 (1.36 %) |
| **6'** | −0.896 | −1,416.7 | 5,436 (1.19 %) |
| 2'alt | −1.115 | −3,645.2 | 11,121 (2.44 %) |
| 1'a | −1.141 | −3,020.1 | 8,632 (1.90 %) |
| 4'b | −1.174 | −3,933.1 | 11,320 (2.50 %) |
| 3' | −1.442 | −6,636.8 | 23,217 (3.66 %) |
| 4'a | −1.469 | −1,472.9 | 5,936 (1.31 %) |
| 1'b | −1.820 | −4,980.6 | 10,088 (2.22 %) |

**Chosen: `synth/constraints/fable5_floorplan_9b_dngrpcr.xdc` (2'cr).** It wins
on all three criteria at once across all ELEVEN runs, so the tie-break is not
needed: WNS −0.554, TNS −230.4 (**6.15× better than the next-best TNS**, 6''s
−1,416.7) and 2,057 failing endpoints (**2.64× fewer than the next-best count**,
also 6''s, 5,436). Its WNS lead is narrower: 1.20× over 5''s −0.663. It carries no `layer_0` pblock. Fix round 2's 6' does not displace
it — see §5.6.

Note what 2'cr does NOT win: the DN write fan-out (6' MEETS at +0.092) and the
KV write fan-out (5'cr +0.370, 5' +0.315). Each of those variants buys its own
family at a larger cost elsewhere; the criterion scores the module, not a
family.

**Round 1 chose 2' and claimed it was "best of the seven on WNS, TNS and failing
endpoints simultaneously". That superlative was false even then**
(`superlative-check: quoted` — the quoted claim is the defect being corrected,
not an assertion of this document): 4'a had 5,936 failing endpoints against 2''s
6,188 — fewer in both count and fraction (1.31 % vs 1.36 %) — while being 0.638
ns worse on WNS. The correct round-1 statement
would have been "best on WNS and TNS". On the enlarged set 2'cr is best on all
three, and the claim is now true as written.

### 5.4 The gap that remains, named — and it is a THIRD family

**OOC WNS −0.554** under the chosen floorplan, against a 4.000 ns budget. What
owns it is neither of the two families this task has been chasing:

| what | 2'cr | and where it was |
|---|---|---|
| DN write fan-out | **−0.001** | −1.141 unconstrained |
| KV write fan-out | −0.368 | −0.831 in 2'; **+0.315 MET in 5'** |
| **conv BRAM write** | **−0.554** ← owns the WNS, 89 of the 200 worst | −0.686 in 1'a |
| `u_attn` DSP lanes | −0.297 | −0.590 in 1'a |
| DN group return | −0.304 | +0.234 in 1'a |

So, stated against what round 1 said:

* **The DN write-control fan-out is solved by a pblock.** −1.141 → −0.001 at
  clock-region granularity. Round 1 got this right and understated how far it
  goes.
* **The KV write fan-out is ALSO solvable by a pblock** — 5' has it MET at
  +0.315 with the array in one SLR. Round 1's "only RTL can fix this" was
  wrong on its arithmetic half, and the `KV_PIPE` that round 1 recommended is
  **not** needed to remove the SLR crossing.
* **But the two floorplans do NOT compose — MEASURED, §5.5.** Variant 5'cr
  holds both and lands at WNS −0.720, worse than either parent, because 5''s
  KV SLR is bought with an uneven DN split that breaks a DN group across three
  SLRs and makes the clock-region pin inert.
* **The conv BRAM write does NOT yield to the same technique — MEASURED,
  §5.6.** Variant 6' pins the conv banks and their control registers the same
  way, and the family moves 0.006 ns (−0.554 → −0.548) while `u_attn` goes
  −0.297 → −0.896 and the module to −0.896. The other two families are URAM,
  which nothing else contends for; the conv banks are block RAM sharing an SLR
  with the compute that reads them, so confining them evicts that compute.
  **The technique works where the constrained resource is uncontended, and it
  has now been shown not to generalise past that.**
* **The module still does not close at OOC**, and by the reading rule in §0
  that is a failure in the optimistic context. The remaining −0.554 under the
  chosen floorplan is the conv BRAM write path (3 logic levels, 93.3 % route,
  `SLR1 -> SLR2`) — and it is now known to be a family a floorplan does not
  reach.
* **The playbook gap is now much smaller than round 1 reported.** Round 1 said
  "the house playbook has closed −0.091 in one `phys_opt` pass and has never
  been asked to close −0.8". The chosen floorplan is at **−0.554 / −230.4 TNS /
  2,057 endpoints** — still outside anything this project has closed, but the
  TNS is an order of magnitude below round 1's chosen variant and two orders
  below the unconstrained baseline.

That is the finding. It is neither of the brief's two stop-backs.

### 5.5 Do the two floorplans COMPOSE? Measured: NO

**Beyond the ruling.** 2'cr fixes the DN write fan-out and 5' fixes the KV write
fan-out; they constrain disjoint cells, so the union looked like free money and
was run to find out. `synth/constraints/fable5_floorplan_9b_combo.xdc` (variant
**5'cr**) is 5''s 11 / 3 / 10 partition with 2'cr's two refinements layered on —
banks to the SLR's URAM clock-region columns, last fan-out stage to the centre
clock-region row. It PLACED in 2,577 s.

| | 2'cr | 5' | **5'cr (the union)** |
|---|---|---|---|
| DN write fan-out | **−0.001** | −0.525 | −0.536 |
| KV write fan-out | −0.368 | +0.315 MET | **+0.370 MET** |
| WNS | **−0.554** | −0.663 | −0.720 |
| TNS | **−230.4** | −2,257.0 | −1,456.3 |
| failing endpoints | **2,057** | 8,705 | 6,000 |
| worst-path owner | conv BRAM | attn / DN group return | **DN group return, 195 of the 200 worst** |

**The KV half composes; the DN half does not.** 5'cr keeps the KV write MET
(+0.370, `SLR1 -> SLR1`), but its DN write fan-out is −0.536 — 5''s number, not
2'cr's. The clock-region pin bought nothing.

**Why, and it is the URAM budget again.** 5' buys the KV array its own SLR by
splitting the DN array 11 / 3 / 10, which makes `g_grp[1]` straddle all three
SLRs at 87 / 87 / 58 URAM288. A clock-region pin on a group whose banks are in
three different SLRs has no clock region to pin to: the constraint is
satisfiable and inert. The group return pays for it — `DN_GRP_RETURN` goes from
−0.304 in 2'cr to −0.720 in 5'cr and owns **195 of the 200 worst paths**.

**So the two constraints are in TENSION, not independent**, and the coupling is
that 928 of 960 URAM288 leaves no partition that gives the KV array its own SLR
*and* every DN group its own SLR. That is a sharper form of the capacity finding
than §4.2's, and it is measured rather than argued. **The chosen XDC is
unaffected** — see §5.3.

---

### 5.6 Does the THIRD family yield to the same technique? Measured: NO

Two families have now fallen to the same instrument: the DN write fan-out
(−1.141 → −0.001, 2'cr) and the KV write fan-out (−0.831 → +0.315 MET, 5').
Under 2'cr the WNS is owned by a third with the same signature — the conv BRAM
write. **R-C asks whether it yields too. It does not.**

Variant **6'** (`synth/constraints/fable5_floorplan_9b_convcr.xdc`) is 2'cr
byte-for-byte plus two pblocks: the 24 conv BRAM banks (`g_cv[*]`) into SLR1,
and their write-control registers (`st_reg[*]`, `dn_layer_r_reg[*]`, probed off
2'cr's placed netlist — `evidence/qwen9b/g5/020_conv_register_probe.log`) into
SLR1's centre clock-region row. It PLACED in 2,543 s.

| | 2'cr | **6'** |
|---|---|---|
| DN write fan-out | −0.001 | **+0.092 MET** — the only variant where it meets |
| KV write fan-out | −0.368 | −0.559 |
| **conv BRAM write** | **−0.554** | **−0.548** ← the target, and it did not move |
| `u_attn` DSP lanes | −0.297 | **−0.896** ← now owns the WNS, 179 of the 200 worst |
| WNS / TNS / failing EP | **−0.554 / −230.4 / 2,057** | −0.896 / −1,416.7 / 5,436 |
| SLR1 Block RAM Tile | 450 of 720 (62.5 %) | **627.5 of 720 (87.2 %)** |

**The pblock did exactly what it was asked to do.** The conv banks went from
split to co-located — `FIN_CONV_BRAM_BY_SLR: SLR1=384 SLR2=240` in 2'cr becomes
**`SLR1=624`** in 6' (`g5_v2cr_finish_run3.log`, `g5_v6_finish_run3.log`), and
the `st_reg` path that WAS the family's worst is gone: 2'cr's worst conv path is
`st_reg[3]/C -> g_cv[4].wm_reg_bram_7/CASDOMUXEN_B`, and 6''s is a **different
path from a different source**, `rstn_i_reg/C -> g_cv[16].sm_reg_bram_7/CASDOMUXEN_B`
(`g5_v2cr_conv_bram_paths.rpt`, `g5_v6_conv_bram_paths.rpt`).

**And the family's slack did not move anyway: −0.554 → −0.548.** What replaced
the write-control path is the **reset distribution** — `rstn_i_reg`, which this
XDC deliberately does not pin because pinning a reset replica fights the tool
that created it, and which in 6' sits in SLR2 driving banks now confined to
SLR1 (`SLR2 -> SLR1`, 2 logic levels, 94.8 % route). Fixing the named source
promoted the next source at the same slack.

**The cost landed on `u_attn`.** Forcing 624 conv BRAM cells into SLR1 takes
that SLR's block RAM from 62.5 % to **87.2 %**; `u_attn`'s worst path goes from
`SLR1 -> SLR1` in 2'cr to `SLR2 -> SLR0` in 6', crossing **two** SLR boundaries,
and from −0.297 to −0.896. (Per-SLR DSP moved only 1,504 → 1,475, so this is a
change in where the critical PATH runs rather than a wholesale eviction of the
block.)

**Why this family is different from the other two.** The DN and KV arrays are
URAM, a resource almost nothing else in `layer_chan` competes for, so pinning
them displaces nothing and their write control is a small named register set
that can be pinned with them. The conv banks are block RAM at 87 % of an SLR's
supply, they share that SLR with the compute that reads them, and their worst
path's source after the fix is a **reset**, which is replicated by the tool and
is not a sensible pblock member. So two things are true at once and both matter
to Task 14: **the constraint worked** (the banks co-located, the `st_reg` path
went away) and **the family did not move**, because the next source was one the
technique cannot address. The technique is not general — it needs a constrained
resource that is uncontended AND a write-control source that is a nameable
register set.

**6' does NOT become the chosen XDC.** By §5.3's stated criterion it loses on
all three: WNS −0.896 vs −0.554, TNS −1,416.7 vs −230.4, failing endpoints
5,436 vs 2,057. **2'cr stands.**

---

## 6. What this experiment did NOT establish

1. **Anything in-context.** OOC is `layer_chan` alone on the whole VU9P. Every
   number here is the optimistic case; nothing here says what a build with
   XDMA/PCIe/GTs at fixed sites, four DDR4 MIGs anchored to IO banks, four
   `matvec_chan`s and `seq_unit` will do. A success here is necessary, not
   sufficient. (A failure here IS definitive — that asymmetry is the point.)
2. **Anything after `place_design`.** No `route_design`, no `phys_opt_design`,
   at either stage. Whether routing improves or degrades these numbers, and
   whether the house `phys_opt` recipe can close whatever residual remains, is
   unmeasured.
3. **The directive distribution.** Two directives are sampled, at two points.
   There is no variance sample at all: no variant was re-run at one directive
   to separate placer non-determinism from the constraint's effect. The ±0.475
   ns figure is one observation from Track P, carried forward as an order of
   magnitude, not a characterised spread.
4. ~~**Tighter co-location than one SLR.**~~ **MEASURED in fix round 1** —
   variant 2'cr, and it is the chosen XDC. Still not established: any
   granularity finer than "the centre clock-region ROW of the group's URAM
   columns", e.g. per-bank clock-region pins, or a fan-out register pinned to
   the same clock region as the bank rather than the same row.
5. **Laguna TX/RX at scale.** Track P's open item survives untouched: nothing
   here tries to make the SLR crossings Laguna-eligible by construction.
5a. **Most of this document's superlatives are NOT machine-checked, and the
   checker says so out loud.** `evidence/qwen9b/g5/027_superlatives.log`
   ends `G5SUP: PASS` on the claims it can mechanize — the nine
   `G5SUP_COL` best/runner-up columns, two `G5SUP_SCOPED` and four
   `G5SUP_QUOTED` lines — and then prints **48 `G5SUP_UNCHECKED` lines**,
   each naming this document's line number and the sentence it could not
   reduce to a column comparison. Those 48 rest on **reading**, not on the
   checker, and the log is where a reviewer finds them enumerated. Saying
   "every superlative is checked" would be false; what is true is that
   every superlative is either checked or listed. *(Added 2026-09-10: the
   `UNCHECKED` class was printed by the tool but not disclosed here. A
   re-run of the checker today reports **49**, this bullet being the
   forty-ninth; `G5SUP: PASS` is unchanged.)*
6. ~~**The KV array's placement.**~~ **MEASURED in fix round 1** — variant 5'
   pins it whole into SLR1 and its write fan-out MEETS at +0.315. Still not
   established: nothing further about the KV array's placement — §5.5 MEASURED
   the composition question and the answer is NO, the two floorplans are in
   tension. What is still open is whether a DIFFERENT partition exists that
   gives the KV array its own SLR without making a DN group straddle; at 928 of
   960 URAM288 no such partition was found, but none was searched for
   exhaustively.
7. **The in-context form of these XDC files.** Only the OOC addressing form has
   ever been read by Vivado. The `bd_i/layer_0/...` prefixed form Task 14 needs
   is a mechanical rewrite that has not been run.
8. **Any functional claim.** This is synthesis and placement only. The RTL is
   the verified shipping `rtl/` (which is the one thing this task improved over
   Track P, whose vehicle was an unverified copy), but no simulation was run
   here and none of these pblocks has ever been part of a bitstream.
9. **Narrower `layer_0` pblocks.** At 928 of 960 URAM288 a `layer_0` pblock
   must contain all four URAM CLOCKREGION columns (X1..X4) and all fifteen
   rows; the only freedom is the URAM-free columns X0 and X5, so 4'b tests the
   TIGHTEST shape that exists. "A `layer_0` pblock costs X" is established for
   that shape only — and, by the same arithmetic, no other shape is available.
10. **A per-bank comparison on the same RTL.** 3'`s unconstrained comparator
    (−1.956) is Track P's `r3pipe2bank`, measured on `synth/exp_uram/rtl/`, not
    on the shipping `rtl/`. Only the DN_BPG = 8 baseline was re-measured here.
    And 3' is NOT a per-bank *placement* test: its twenty-four pblocks share
    only three SLR-wide ranges, so the only per-bank thing about it is the RTL.
11. **That a `KV_PIPE` is needed at all.** Round 1 recommended one on the
    strength of an arithmetic claim that variant 5' has since refuted: a pblock
    DOES remove the KV SLR crossing. What a `KV_PIPE` would add is a fix that
    survives the KV array being forced to span SLRs — which 5' avoids rather
    than solves, by giving the array an SLR of its own at the cost of an uneven
    DN split. Whether that trade is the right one in context is not established
    here, and no `KV_PIPE` was built or costed.
12. **The KV bank-mux read path.** `at_kvdata_reg` matches nothing in any of
    the eleven placed netlists, under three different patterns
    (`*at_kvdata_reg*`, `*at_kvdata*`, `*kv_rdq_b*` — every run's
    `FIN_KVMUX_TRY` lines). The register is absorbed somewhere in
    synth/opt and the KV read path is therefore reported only through the
    `ATTN_DSP` family, never as its own number.

---

13. ~~**The conv BRAM write path.**~~ **MEASURED in fix round 2** — variant 6'
    pins its 24 banks and their control registers and the family does not move
    (§5.6). Still not established: any conv floorplan that does NOT confine the
    banks to one SLR, e.g. leaving them spread and pinning just the control
    registers near each bank's own clock region — 6' changed both at once, so
    it cannot separate "the conv family is unreachable" from "confining 624
    BRAM cells to one SLR costs more than it buys".
14. **Whether any of this survives an uneven DN split in context.** 5' and any
    combination built on it need 11 / 3 / 10, which in a full build competes
    with the four `mvchan` pblocks `synth/constraints/fable5_floorplan_a.xdc`
    places by SLR.

---

## 7. Reproduction

```bash
# ON SNOKE.  One out dir per run, never reused.  Seven runs fit concurrently
# on snoke (peak 9.8-13.5 GB each, measured); Track P's runtimes hold.
cd ~/r2d2/code/fpga/fable5_llm/synth/exp_uram/scripts
C=../../constraints
#           variant   LNH N_DN N_KV NKVH  CVD EW PACK PIPE PLACE [DIRECTIVE] [BPG] [xdc...]
nohup ./launch_exp.sh g5_v1a   32 24 8 4 8192 16 0 2 1 &
nohup ./launch_exp.sh g5_v1b   32 24 8 4 8192 16 0 2 1 AltSpreadLogic_medium &
nohup ./launch_exp.sh g5_v2    32 24 8 4 8192 16 0 2 1 Default 8 $C/fable5_floorplan_9b_dngrp.xdc &
nohup ./launch_exp.sh g5_v2alt 32 24 8 4 8192 16 0 2 1 AltSpreadLogic_medium 8 $C/fable5_floorplan_9b_dngrp.xdc &
nohup ./launch_exp.sh g5_v3    32 24 8 4 8192 16 0 2 1 Default 1 $C/fable5_floorplan_9b_dnbank.xdc &
nohup ./launch_exp.sh g5_v4a   32 24 8 4 8192 16 0 2 1 Default 8 $C/fable5_floorplan_9b_dnslr.xdc &
# layer0.xdc goes FIRST: it claims every cell, and dnslr.xdc then takes the DN
# URAMs back out of it.  The other order silently empties the DN pblocks.
nohup ./launch_exp.sh g5_v4b   32 24 8 4 8192 16 0 2 1 Default 8 $C/fable5_floorplan_9b_layer0.xdc $C/fable5_floorplan_9b_dnslr.xdc &

# fix round 1: the two ruled-in measurements, then their union
nohup ./launch_exp.sh g5_v2cr  32 24 8 4 8192 16 0 2 1 Default 8 $C/fable5_floorplan_9b_dngrpcr.xdc &
nohup ./launch_exp.sh g5_v5    32 24 8 4 8192 16 0 2 1 Default 8 $C/fable5_floorplan_9b_kvslr.xdc &
nohup ./launch_exp.sh g5_v5cr  32 24 8 4 8192 16 0 2 1 Default 8 $C/fable5_floorplan_9b_combo.xdc &

# fix round 2: the third family
nohup ./launch_exp.sh g5_v6    32 24 8 4 8192 16 0 2 1 Default 8 $C/fable5_floorplan_9b_convcr.xdc &

# the two post-place passes, off each run's own post_place.dcp
vivado -mode batch -nojournal -source finish_reports.tcl -tclargs <out_dir>
vivado -mode batch -nojournal -source family_census.tcl  -tclargs <out_dir>

# carry the report sections into evidence, and regenerate this document's tables
./collect_evidence.sh -d evidence/qwen9b/g5 \
    g5_v1a g5_v1b g5_v2 g5_v2cr g5_v2alt g5_v3 g5_v4a g5_v4b g5_v5 g5_v5cr g5_v6
python3 evidence/qwen9b/g5/g5_table.py          # the tables in sections 2 and 4.4
python3 evidence/qwen9b/g5/g5_superlatives.py   # every superlative, checked
python3 evidence/qwen9b/g5/g5_superlatives.py --negative-control
```

**A note on the runs' own tooling, because it changes what a re-run produces.**
The FIRST SEVEN placements used `exp_ooc.tcl` as committed at `5ee5f0e`, which
carried two defects that fire only *after* `place_design`: it searched for the
DN final bank-mux OREG under the EXPERIMENT COPY's name `dn_rdq_n_reg` (the
shipping RTL calls it `dn_rdq` — declared at `rtl/layer_chan.sv:613`,
assigned at `rtl/layer_chan.sv:781`) and so recorded
`EXP_DNMUX_WORST_SLACK: n/a` — a wrong answer, not an error — and its
timing-summary parse reused `h`, which is an array earlier in the same script,
killing the run at the last marker with `can't set "h": variable is array`.
Both are fixed in `exp_ooc.tcl` now. **The placements are unaffected**: they
were written to `post_place.dcp` before either defect fired, and
`synth/exp_uram/scripts/finish_reports.tcl` re-derives the missing sections from
those checkpoints
rather than by re-placing, which would have been a different placer draw. Every
number in §2 tagged to a `FIN_` marker comes from that pass; the `EXP_` numbers
come from the runs themselves; where both exist they agree
(e.g. `EXP_PLACED_WNS` == `FIN_PLACED_WNS` in all eleven). The four runs after
fix round 1 used the fixed script and needed no completion pass, though they
were given one anyway so every variant carries the same marker set.

## 8. The committed evidence

| what | where |
|---|---|
| the four pre-flights the XDC files rest on | `evidence/qwen9b/g5/001_pblock_preflight.log` … `004_timing_path_props.log` |
| which of the brief's Step-1 options was taken, and why | `evidence/qwen9b/g5/005_step1_repoint.log` |
| the placed vehicle == the committed vehicle, file by file | `evidence/qwen9b/g5/006_bytelock_vehicle.log` |
| the collection run | `evidence/qwen9b/g5/007_collect_reports.log` |
| the citation-drift gate (`--plan`, `--verify`, `--exclude-control`) | `evidence/qwen9b/g5/008_cite_drift.log` |
| `spec_cites` on this document, with its negative control | `evidence/qwen9b/g5/009_spec_cites_gatedoc.log`, `011_spec_cites_final.log`, `012_spec_cites_final2.log` |
| the wall-clock and memory census §1 quotes | `evidence/qwen9b/g5/010_wallclock_memory.log` |
| the KV write-control register probe the 5' member set rests on | `evidence/qwen9b/g5/013_kv_register_probe.log` |
| the fix-round-1 pre-flight of the 5' and 2'cr pblocks | `evidence/qwen9b/g5/014_pblock_preflight_r2.log` |
| the fix-round-1 and fix-round-2 collection runs | `evidence/qwen9b/g5/015_collect_reports_r2.log`, `017_collect_reports_r3.log`, `022_collect_reports_r4.log` |
| the fix-round-1 drift gate, and its by-hand check of five line numbers | `evidence/qwen9b/g5/016_cite_drift_r2.log` |
| `spec_cites` on this document through fix round 1 | `evidence/qwen9b/g5/018_spec_cites_r2_final.log`, `019_spec_cites_r2_last.log` |
| the conv write-control register probe the 6' member set rests on | `evidence/qwen9b/g5/020_conv_register_probe.log` |
| the fix-round-2 pre-flight of the 6' pblocks | `evidence/qwen9b/g5/021_pblock_preflight_r3.log` |
| the fix-round-2 drift gate and `spec_cites` LAST | `evidence/qwen9b/g5/023_cite_drift_r3.log`, `024_spec_cites_r3_last.log` |
| **the SUPERLATIVE checker and its negative control** — every "best / only / N×" claim in this document, checked against the logs | `evidence/qwen9b/g5/g5_superlatives.py`, `027_superlatives.log` |
| the FULL `report_timing` on the conv BRAM write — §5.6's primary artefact | `evidence/qwen9b/g5/g5_v2cr_conv_bram_paths.rpt`, `g5_v6_conv_bram_paths.rpt` |
| the conv path and per-SLR markers those sections quote | `g5_v2cr_finish_run3.log`, `g5_v6_finish_run3.log` |
| the fix-round-3 collection, drift gate and `spec_cites` LAST | `evidence/qwen9b/g5/025_conv_reports.log`, `026_collect_reports_r5.log`, `028_cite_drift_r4.log`, `029_spec_cites_r4_last.log` |
| the FULL `report_timing` on the KV write fan-out — the finding's primary artefact | `evidence/qwen9b/g5/g5_v2_kv_write_fanout_paths.rpt` (the residual) and `g5_v5_kv_write_fanout_paths.rpt` (MET at +0.315) |
| per variant: the whole `EXP_` marker stream | `g5_<v>_summary.log` |
| per variant: the completion and decomposition passes | `g5_<v>_finish_run.log`, `g5_<v>_family_run.log` |
| per variant: the timing summary, **whole** | `g5_<v>_timing_summary_placed.rpt` |
| per variant: the write fan-out and bank-mux path reports | `g5_<v>_dn_write_fanout_paths.rpt`, `g5_<v>_dn_bank_mux_paths.rpt`, `g5_<v>_dn_group_return_paths.rpt` |
| per variant: the URAM SLR census, now with clock regions | `g5_<v>_uram_slr_census.rpt` |
| per variant: utilisation, and utilisation per SLR | `g5_<v>_util_synth.rpt`, `g5_<v>_util_placed.rpt`, `g5_<v>_util_placed_slr.rpt` |
| the table generator | `evidence/qwen9b/g5/g5_table.py` |
