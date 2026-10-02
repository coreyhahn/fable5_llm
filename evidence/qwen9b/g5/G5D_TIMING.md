# G5d — the rebuild on the pipelined netlist, and its timing closure (Task 14-B)

Task 14's first campaign (`evidence/qwen9b/g5/G5B_TIMING.md`) failed the gate
at **WNS −0.130** after the whole house playbook and found two things the next
round had to act on: the floorplan *costs* slack on this design, and the
residual was partly **logic**, not routing. Task 14-A
(`evidence/qwen9b/g5/G5C_RTL.md`) removed the logic-dominated cones in RTL —
the scratchpad BRAM cascade capped, `fx_silu`'s s2 split, the attention and
DeltaNet output muxes split — bit-exact and token-identical, and said in its
own design note that it did **not** expect the gate to close
(`.superpowers/sdd/2026-09-04-qwen35-9b-state-spill/task-14A-design-note.md`
§5). **This document is where that estimate becomes a measurement.**

---

## 0. HOW TO READ EVERY NUMBER BELOW — stated before the numbers

* **T** = transcribed from a named report or log, copied into
  `evidence/qwen9b/g5/` as a new numbered file. **D** = derived, with the
  arithmetic shown. **S** = stated by a source, cited.
* **Every Vivado number in this document was produced ON SNOKE.** Vivado runs
  nowhere else in this project. Each run went through
  `evidence/qwen9b/run.sh`, whose header records `=== host: snoke`, the tree
  sha, the command and the return code, and whose footer records `=== rc:` and
  `=== end:`. A log is cited only after both exist.
* **Reports are read fresh, by timestamp, from the roll's own out dir.** Out
  dirs (`synth/out_*`) are gitignored, so the sections quoted here are copied
  into `evidence/qwen9b/g5/` as numbered files and it is those copies the
  citations point at.
* **The pass criterion is the plan's and is not relaxed anywhere in this
  document**: WNS ≥ 0.000 **and** WHS ≥ 0.000 on **all** clocks, **zero**
  failing endpoints, **no waiver**.
* **The board was never touched.** Task 14-B produces a bitstream and its
  `VERSION` if the gate passes; Task 15 is bring-up. Nothing here programs
  anything, and nothing here writes flash.
* **Two provenance notes, stated rather than left to be noticed.**
  (1) `evidence/qwen9b/g5/g5d_clockskew_probe.tcl` and
  `evidence/qwen9b/g5/g5d_superlatives.py` are new files created by this task,
  and they were **untracked** when the runs that used them executed —
  `evidence/qwen9b/run.sh`'s `=== tree:` line uses `git diff --quiet`, which tests tracked
  files only, so those logs read `c973c18` with no `+dirty` flag and that is
  accurate for the tracked tree. The instruments are committed with the
  evidence they produced.
  (2) The numbered files are new; **no file committed by Task 13, Task 14 or
  Task 14-A under `evidence/qwen9b/g5/` was modified by this task.**

---

## 1. WHAT RAN, WHERE, ON WHICH TREE

**Every row is `=== host: snoke`**, every row went through
`evidence/qwen9b/run.sh`, and every row's `=== rc:` is **0**. Times are the
wrapper's own `=== date:` → `=== end:`.

| # | log | tree | start → end | what |
|---|---|---|---|---|
| 103 | `103_t14b_build_041.log` | `c973c18` | 06:08:56 → 09:49:33 (**3 h 40 m**) | the first roll (§3.1) |
| 104 | `104_t14b_skewprobe_14A_comparand.log` | `c973c18` | 06:16:05 → 06:26:38 | the skew probe's dry run on Task 14's artifact (§5.1) |
| 107 | `107_t14b_build_041_cascade.log` | `c973c18` | 06:30:27 → 06:32:05 | the cascade on build_041's layer netlist (§2.3) |
| 109 | `109_t14b_spread_po2.log` | `0dde838` | 09:50:08 → 15:26:00 (**5 h 35 m**) | the four-directive spread (§3.2) |
| 110 | `110_t14b_skewprobe_041.log` | `0dde838` | 09:50:18 → 10:00:11 | the skew probe on build_041 (§5.1) |
| 113 | `113_t14b_smem_041.log` | `a945159` | 10:02:06 → 10:10:57 | the scratchpad census on build_041 (§4.5) |
| 115 | `115_t14b_census_ash.log` | `a945159` | 14:55:17 → 15:06:46 | `synth/scripts/census_035.tcl` on roll #2 (§4.3) |
| 116 | `116_t14b_slrcensus_ash.log` | `a945159` | 14:55:22 → 15:04:53 | `synth/scripts/slr_census.tcl` on roll #2 (§4.2) |
| 117 | `117_t14b_fam_po2_AltSpreadLogic_high.log` | `a945159` | 14:55:27 → 15:04:36 | the family census on roll #2 (§4.6) |
| 118 | `118_t14b_final_verify_ash.log` | `a945159` | 14:55:32 → 15:04:51 | `synth/scripts/final_verify.tcl` on roll #2 (§4.8) |
| 119 | `119_t14b_playbook_ash.log` | `a945159` | 14:55:12 → 16:10:48 | the closure playbook on roll #2 (§6) |
| 121 | `121_t14b_smem_ash.log` | `a945159` | 15:15:18 → 15:24:05 | the scratchpad census on roll #2 (§4.5) |
| 123 | `123_t14b_cones_ash.log` | `a945159` | 15:15:23 → 15:25:03 | the cone census on roll #2 (§4.4) |
| 125 | `125_t14b_skewprobe_ash.log` | `a945159` | 15:15:28 → 15:25:26 | the skew probe on roll #2 — the arm's evidence (§5.1) |
| 133 | `133_t14b_clockroot_check.log` | `a945159` | 15:56:48 → 16:03:18 | the clock-root RED/GREEN, before the roll (§5.2) |
| 134 | `134_t14b_arm_clockroot_ckr2.log` | `a945159` | 16:03:37 → 20:57:41 (**4 h 54 m**) | **the clock-root arm — the roll that closes** (§8) |
| 136 | `136_t14b_final_verify_playbook.log` | `a945159` | 16:11:15 → 16:19:58 | `synth/scripts/final_verify.tcl` on the playbook output (§6) |
| 138 | `138_t14b_spread_po4.log` | `51f49d2+dirty` | 16:34:30 → 22:12:18 (**5 h 38 m**) | two supplementary directives (§9) |
| 139 | `139_t14b_owner_probe_ash.log` | `51f49d2+dirty` | 16:35:11 → 16:44:09 | what the residual owner would need (§11) |
| 142 | `142_t14b_final_verify_ckr2.log` | `51f49d2+dirty` | 20:58:46 → 21:08:00 | **the signoff verification** (§8.3) |
| 143 | `143_t14b_census_ckr2.log` | `51f49d2+dirty` | 20:58:50 → 21:10:29 | `synth/scripts/census_035.tcl` on the closing roll (§8.3) |
| 144 | `144_t14b_slrcensus_ckr2.log` | `51f49d2+dirty` | 20:58:54 → 21:08:52 | `synth/scripts/slr_census.tcl` on the closing roll (§8.3) |
| 145 | `145_t14b_fam_ckr2_AltSpreadLogic_high.log` | `51f49d2+dirty` | 20:58:58 → 21:08:21 | the family census on the closing roll (§8.3) |
| 146 | `146_t14b_skewprobe_ckr2.log` | `51f49d2+dirty` | 20:59:02 → 21:09:22 | the skew probe on the closing roll (§8.2) |
| 148 | `148_t14b_playbook_ckr2.log` | `51f49d2+dirty` | 21:09:08 → 22:01:48 | the playbook on the closing roll — `POPB_CLOSED` (§8.4) |
| 149 | `149_t14b_cones_ckr2.log` | `51f49d2+dirty` | 21:19:31 → 21:29:12 | the cone census on the closing roll (§8.3) |
| 151 | `151_t14b_smem_ckr2.log` | `51f49d2+dirty` | 21:19:35 → 21:28:20 | the scratchpad census on the closing roll (§8.3) |
| 154 | `154_t14b_final_verify_po_ckr2.log` | `51f49d2+dirty` | 22:02:32 → 22:11:07 | `synth/scripts/final_verify.tcl` on the playbook output (§8.4) |

**Two provenance notes on the tree column.**

* The `+dirty` on logs 138–154 is **this document**. `evidence/qwen9b/run.sh`'s `=== tree:` uses
  `git diff --quiet` over tracked files, and `evidence/qwen9b/g5/G5D_TIMING.md`
  was being written while those runs executed. **No RTL, no constraint and no
  script was modified after `51f49d2` and before the closing roll finished.**
  Fix round 1 then edited two files, after every run in this table had
  finished and on a clean committed tree: comment lines into
  `synth/constraints/fable5_clockroot_9b.xdc`'s header, and the widened
  `evidence/qwen9b/g5/g5d_clockroot_check.tcl` — both in `00fffbf`, both
  declared in §12.1. Neither is in a build path: the XDC edit adds no line a
  parser reads, and no implementation script sources the check script. One of
  them nevertheless destroyed a piece of this section's own evidence, which
  the third and fourth bullets below record.
* **Two runs used the clock-root XDC while it was still UNTRACKED, and one of
  them is the roll that ships.** An earlier version of this bullet claimed the
  opposite — that the file *"was committed in `51f49d2`, before every run that
  used it"* — and its own table contradicts it. `51f49d2` was committed at
  **16:23:54** (`git log --date=iso-local`). The guard run
  `133_t14b_clockroot_check.log` started at **15:56:48** and the arm
  `134_t14b_arm_clockroot_ckr2.log` at **16:03:37**, both on tree `a945159`,
  both *before* that commit. The file was untracked, so `git diff --quiet`
  — which tests tracked files only — reported the tree clean; that is accurate
  about the tracked tree and says nothing about the XDC. The commit landed
  while roll 134 was still running, and the file was committed **unchanged**.
* **The bytes cannot be PROVEN identical, and this document no longer claims
  they can.** `synth/scripts/full_impl.tcl:26` is `add_files -fileset constrs_1 -norecurse $x`, which **references** the
  file rather than importing a copy: the run's project retains only the path (its
  `stage1.xpr` holds `<File Path="$PPRDIR/../../constraints/fable5_clockroot_9b.xdc">`),
  its `EXTRA_XDC:` and `TIMING: … XDC=…` lines record only the path, and
  `evidence/qwen9b/g5/g5d_clockroot_check.tcl` recorded no hash and echoed no
  line of the file. **No copy of the XDC as it stood at run time is retained
  anywhere.** When review round 1 read the working-tree file, its mtime was
  2026-09-07 **15:56:19**, earlier than both runs — corroboration, never proof,
  because an mtime is not a hash and does not survive a clone. **That
  corroboration is gone, and fix round 1 destroyed it.** `00fffbf` (committed
  2026-09-07 22:53:18) appended comment lines to that same file's header, so the
  mtime now reads 2026-09-07 **22:52:32** — *later* than both runs, which
  inverts what it corroborated, and 15:56:19 is not re-derivable from anything
  in the repository. Until fix round 2 this bullet still printed 15:56:19 as
  corroboration, under a §12.5 row that said the destruction was recorded here
  when it was not (§12.6).
* **What stands in its place is a byte comparison, which is stronger than an
  mtime and is re-runnable by anyone.** The comment-only edit is machine-checked
  rather than asserted: `git diff 5c4c829..9a84a52 -- synth/constraints/fable5_clockroot_9b.xdc`
  adds **0** lines that are not `#`-or-blank and deletes **0**, and lines 1–101
  of the file at HEAD are byte-identical to the same lines at `5c4c829`, which
  are in turn byte-identical to `51f49d2`'s, the commit that first tracked the
  file. The added block sits at the end of the header, immediately above the
  file's single `set_property`
  (`synth/constraints/fable5_clockroot_9b.xdc:132`), so no line a tool reads
  moved. The mtime is therefore no longer corroboration of anything; the byte
  comparison is, and it says the constraint content review round 1 examined is
  the constraint content in the tree today. So, stated flatly: **the arm's A/B
  result is carried by a run whose XDC bytes are unproven-identical to the
  committed file** — unproven at run time, and not made less unproven by a
  timestamp this round's own edit overwrote.
* **What the gate rests on instead is what the BUILT DESIGN says about
  itself**, every piece of it measured *after* the commit. The shipping routed
  checkpoint reads the property back on that one net —
  `146_t14b_skewprobe_ckr2.log:193` `root=X2Y2 user_root=X2Y2` (run 20:59:02,
  tree `51f49d2+dirty`). The placer's own CRITICAL WARNING names clock region
  **X2Y2** on that exact net (`173_t14b_fix1_place30890_ckr2.txt`, quoted from
  the run's impl log, line 767 — §8). The committed file sets `X2Y2` on exactly
  one net (`CRC_NET_COUNT: 1`). And fix round 1 re-read **the committed file**
  against **the shipping checkpoint** on a clean committed tree and got
  `CRC_VERIFY_BEFORE_OK` → `CRC_GREEN_OK` → `CLOCKROOT_SLR_OK SLR0`
  (`170_t14b_fix1_clockroot_slr_ckr2_GREEN.log`, `=== tree: 00fffbf`, rc 0).
  **The commit order is not what ties the file to the design; the readback
  is.**
* Logs 103–107 read `c973c18` with no `+dirty` because the instruments they
  used were still **untracked** at that moment, and `git diff --quiet` tests
  tracked files only. Those instruments are committed with the evidence they
  produced.

**Evidence numbers 105, 111, 114, 122, 124, 130, 140, 147, 150, 152** are
report prefixes rather than logs (some instruments write no report; those
prefixes produced no files). **Number 131 is burnt** — §5.2.

---

## 2. THE NETLIST — it IS Task 14-A's, checked three ways before a spread was spent

### 2.1 Both `create_project` assertions pass, before anything else

Task 14's first roll burnt four build numbers on two harness defects
(`G5B_TIMING.md` §1): `layer_0/m_axis` had no clock, and `rtl/state_dma.sv`
was never added to the project. Both repairs carry assertions, and 14-B's
brief makes checking them the first thing that happens. From
`evidence/qwen9b/g5/108_build_041_create_assertions.txt`, copied out of
build_041's own create.log (the out dir is gitignored), **T**:

```
LAYER_SOURCES_OK: 12 layer modules present
SDMA_FREQ_OK: layer_0/m_axis FREQ_HZ=250000000
SDMA_CLKDOM_SET: layer_0/m_axis CLK_DOMAIN=bd_xdma_0_0_axi_aclk
SDMA_CLOCK_OK: m_axis FREQ_HZ=250000000 CLK_DOMAIN=bd_xdma_0_0_axi_aclk; axi_smc S02==S00 domain 'bd_xdma_0_0_axi_aclk'
CREATE_PROJECT_OK
```

`SDMA_CLOCK_OK` is the decisive one: `axi_smc/S02_AXI` shares `S00_AXI`'s
`CLK_DOMAIN`, which is what says **no clock converter was inferred on the
state-DMA path**. The same file counts the two CRITICAL WARNING classes
build_036 carried — `[BD 41-967]` and SmartConnect *"do not share a common
clock"* — at **0** and **0**, and `^ERROR` at **0** both in create.log and in
the layer's own bd_layer_0_0_synth_1/runme.log. `create_project` ran
06:08:56 → 06:13:18, **4 m 22 s**.

### 2.2 The layer's own synthesis — the counts are 14-A's, not BASE's

`evidence/qwen9b/g5/106_build_041_layer_util_synth.rpt`, copied out of
`synth/out_build_041/proj/stage1.runs/bd_layer_0_0_synth_1/`. The comparand is
the **same flow on the same machine one round earlier** —
`evidence/qwen9b/g5/036_build_040_layer_util_synth.rpt`, build_040's
`bd_layer_0_0_synth_1` on the BASE RTL — so every delta below is Task 14-A's
and nothing else's. **T**:

| count | build_040 (BASE RTL) | **build_041 (14-A RTL)** | Δ | reading |
|---|---|---|---|---|
| **URAM288** | **182** | **182** | **0** | the escalation trigger did not fire; still S5's two-slot caches |
| **DSP48E2** | 1,838 | **1,840** | **+2** | 14-A's measured OOC delta, reproduced in project |
| **Block RAM Tile** | 79 (RAMB36 75 + RAMB18 8) | **83** (RAMB36 **79** + RAMB18 8) | **+4** | see below |
| **CARRY8** | 7,844 | **7,839** | **−5** | 14-A's OOC delta, to the unit |
| CLB LUTs | 113,485 | 116,093 | +2,608 | |
| — LUT as Logic | 108,989 | 111,597 | +2,608 | |
| — LUT as Memory | 4,496 | 4,496 | 0 | |
| CLB Registers | 59,835 | 61,470 | +1,635 | |

**D, the +4 BRAM, exactly.** `G5C_RTL.md` §7.2 records that *in context* the
BASE tool cascaded **both** scratch arrays as `FIRST 5 / MIDDLE 20 / LAST 5` —
5 chains of 6, **30 tiles per array**. A 2-deep cascade over the same array is
16 chains of 2, **32 tiles per array**. 2 × (32 − 30) = **+4**, which is the
whole of the Block RAM delta. The +2 DSP and −5 CARRY8 are 14-A's own OOC
numbers (`G5C_RTL.md` §7.1) reproduced by a different synthesis flow.

**One honest divergence from 14-A's OOC rung, reported rather than buried.**
Out of context 14-A measured LUT **−890** (the split muxes were *cheaper*) and
FF **+1,601**. In project the same RTL reads LUT **+2,608** and FF **+1,635**.
The FF number agrees to 2 %; the LUT number does not agree in sign. The two
runs are different synthesis flows over different tops (`layer_chan` alone
versus the BD IP `bd_layer_0_0` with its interface shims), and `G5C_RTL.md`
§7.2 already documents that the two flows disagree about the *cascade* on the
BASE netlist, so a disagreement about LUT count is the same class of thing.
**It is recorded here, and this document does not claim the split muxes are
cheaper in context.** Nothing in the gate depends on it: 116,093 LUT is 9.82 %
of the device's 1,182,240.

### 2.3 The cascade, on the netlist this build implements

`evidence/qwen9b/g5/107_t14b_build_041_cascade.log` (rc 0) runs Task 14-A's
own read-only instrument `evidence/qwen9b/g5/g5c_scratch_cascade.tcl` over
build_041's `bd_layer_0_0.dcp` — the post-synthesis checkpoint of the layer as
this project synthesised it. **T**:

```
G5C_ARRAY build_041_in_project smem_a cells=32
G5C_CASCADE_B build_041_in_project smem_a FIRST = 16
G5C_CASCADE_B build_041_in_project smem_a LAST = 16
G5C_ARRAY build_041_in_project smem_b cells=32
G5C_CASCADE_B build_041_in_project smem_b FIRST = 16
G5C_CASCADE_B build_041_in_project smem_b LAST = 16
```

**`MIDDLE` is absent on both arrays: 16 chains of exactly 2.** That is
`cascade_height = 2`, honoured, measured on the netlist rather than read off
the source — and it is measured **in context**, which is strictly stronger
than `G5C_RTL.md` §7.2's out-of-context rung, because the in-context BASE tool
is the one that cascaded 6 deep (`evidence/qwen9b/g5/064_t14a_eto_smem.log`:
`FIRST 5 / MIDDLE 20 / LAST 5` on both arrays). The structure the first
campaign's three worst paths walked through — seven `CASDOUTB → CASDINB` hops
carrying 2.55–2.60 ns of logic — cannot exist on this netlist: a 2-deep chain
has exactly one such hop.

---

## 3. THE CAMPAIGN

### 3.1 build_041 — the first roll, and what it is NOT

`evidence/qwen9b/g5/103_t14b_build_041.log`, rc 0, tree `c973c18` clean,
`=== host: snoke`, 2026-09-07T06:08:56 → 09:49:33 = **3 h 40 m 37 s**. Of that,
`create_project` is 4 m 22 s and synthesis (41 out-of-context IP runs, the
layer's among them) reaches `__synthesis_is_complete__` at 06:29; the rest is
one implementation.

**What it is NOT: a roll of the recipe this campaign scores.**
`synth/scripts/build.tcl` launches `impl_1` with the *Vivado defaults* — no
place directive, no post-route `phys_opt`, and no floorplan XDC of any kind. It
exists to produce the project the spread copies, and to exercise the one gate
that lives only in it.

**The three lines below are a COMPOSITE of two files, named here rather than
left to be discovered.** `BUILD_OK` is log 103's own last line
(`evidence/qwen9b/g5/103_t14b_build_041.log:22`); `CLOCK_GATE_OK` and the
`TIMING:` line are on the header line of
`evidence/qwen9b/g5/112_t14b_roll_build_041.txt:4` — log 103 captures only
`tail -5` of each Vivado invocation and does not contain them.

**T**, composite:

```
CLOCK_GATE_OK: 250MHz clocks: pipe_clk xdma_0_axi_aclk
TIMING: WNS=-0.859 WHS=0.006
BUILD_OK
```

`synth/scripts/full_impl.tcl` does not re-run the 250 MHz clock-sanity gate, so
re-implementation rolls inherit rather than re-check it; this is where it was
actually exercised.

**The headline, T** from `evidence/qwen9b/g5/112_t14b_roll_build_041.txt`,
extracted from that roll's own `synth/out_build_041/reports/timing_summary.rpt` (mtime
2026-09-07 09:44:39) by `evidence/qwen9b/g5/g5d_roll_summary.sh`:

| | **build_041** (14-A netlist) | build_040 (BASE netlist) | Δ |
|---|---|---|---|
| WNS | **−0.859** | −0.988 | **+0.129** |
| TNS | −5,879.083 | −16,181.674 | **+10,302.6** |
| failing setup EP | **29,237** of 1,321,608 | 52,609 of 1,319,661 | **−23,372** |
| WHS | **+0.006** | +0.010 | −0.004 |
| failing hold EP | **0** of 1,318,472 | 0 | 0 |
| WPWS / failures | 0.000 / **0** of 393,278 | 0.000 / 0 | 0 |

**D**: at matched recipe (both are `launch_build.sh`'s default implementation,
both unconstrained) the RTL round is worth **+0.129 ns of WNS**, **2.75× less
TNS** (−16,181.674 → −5,879.083) and **44 % fewer failing endpoints**. That is
the first in-context measurement of Task 14-A's change, and it is a real
number on a real routed design — but it is a number on the *default* recipe,
and the gate is scored on the full one.

**Per clock, T** from the same file. All four MIG UI clocks are **3.332 ns /
300.120 MHz**; `pipe_clk` and `xdma_0_axi_aclk` are **4.000 ns / 250.000 MHz**.
The channel labels are `G5B_TIMING.md` §5.1's:

| clock | period | WNS | TNS | failing EP | total EP | WHS | failing hold |
|---|---|---|---|---|---|---|---|
| `mmcm_clkout0` (ch0 UI) | 3.332 ns | −0.524 | −957.757 | 5,084 | 173,221 | +0.010 | 0 |
| `mmcm_clkout0_2` (ch1 UI) | 3.332 ns | −0.310 | −18.632 | 233 | 173,159 | +0.010 | 0 |
| `mmcm_clkout0_3` (ch2 UI) | 3.332 ns | −0.336 | −221.297 | 2,070 | 173,201 | +0.010 | 0 |
| `mmcm_clkout0_1` (ch3 UI) | 3.332 ns | −0.070 | −9.377 | 327 | 173,222 | +0.008 | 0 |
| `pipe_clk` | 4.000 ns | **+1.049** | 0.000 | **0** | 4,764 | +0.012 | 0 |
| **`xdma_0_axi_aclk`** | 4.000 ns | **−0.859** | −4,672.020 | **21,523** | 579,385 | +0.006 | 0 |

**D**: 5,084 + 233 + 2,070 + 327 + 0 + 21,523 = **29,237**, which reconciles
exactly with the design summary. **Hold meets on every clock**, and
`WHS_GATE:` is not printed by `synth/scripts/build.tcl` — the hold verdict for this roll is
the `+0.006` above and its zero failing endpoints.

A bitstream was written (`BITSTREAM: …/impl_1/bd_wrapper.bit`) because
`synth/scripts/build.tcl` runs `-to_step write_bitstream`. **It is a routed implementation of
a design that misses timing and it is not a Task 15 candidate.**

### 3.2 The spread — four directives, the full recipe, and NO floorplan XDC

`evidence/qwen9b/g5/109_t14b_spread_po2.log` (rc 0, `=== host: snoke`,
2026-09-07T09:50:08 → 15:26:00 = **5 h 35 m** for four concurrent rolls),
`TAG=po2 synth/scripts/launch_po2.sh build_041 AltSpreadLogic_high
ExtraTimingOpt Explore AltSpreadLogic_medium`, **no `XDC=`**.

**Why no floorplan.** Task 14's controlled A/B (`G5B_TIMING.md` §4.7) measured
the pblocks *costing* slack, monotonically: none −0.247, `synth/constraints/fable5_floorplan_a.xdc`
−0.768, + the one-SLR ctx pblock −1.126, at matched directive and recipe. 14-B's
brief therefore runs the primary arms unconstrained, and each roll's own
fullimpl.log prints `EXTRA_XDC: none` and `PBLOCK_COUNT: 0` — quoted in the
header of every roll file below, so this is a checked property of the runs, not
a description of the intent.

| roll | directive | WNS | TNS | failing setup EP | WHS | `WHS_GATE:` | evidence |
|---|---|---|---|---|---|---|---|
| **`po2_AltSpreadLogic_high`** | `AltSpreadLogic_high` | **−0.156** | **−126.221** | **2,507** of 1,318,525 | **+0.010** | OK | `126_t14b_roll_po2_AltSpreadLogic_high.txt` |
| `po2_AltSpreadLogic_medium` | `AltSpreadLogic_medium` | −0.159 | −182.889 | 3,629 of 1,319,644 | +0.010 | OK | `129_t14b_roll_po2_AltSpreadLogic_medium.txt` |
| `po2_ExtraTimingOpt` | `ExtraTimingOpt` | −0.196 | −312.103 | 4,460 of 1,318,463 | 0.000 | OK | `127_t14b_roll_po2_ExtraTimingOpt.txt` |
| `po2_Explore` | `Explore` | −0.651 | −3,471.757 | 19,611 of 1,320,567 | 0.000 | OK | `128_t14b_roll_po2_Explore.txt` |

**No `WHS_GATE: NEGATIVE` on any roll of this campaign**, and zero failing hold
endpoints on all four.

**The comparison that matters is at matched directive, matched recipe, matched
XDC (none) — only the netlist differs.** Against Task 14's `po2` roll of the
same name (`G5B_TIMING.md` §5.1):

| | 14-B (14-A netlist) | 14 (BASE netlist) | Δ |
|---|---|---|---|
| WNS | **−0.156** | −0.247 | **+0.091** |
| TNS | **−126.221** | −542.860 | **+416.6 (4.3× less)** |
| failing setup EP | **2,507** | 6,090 | **−3,583 (2.4× fewer)** |
| WHS | +0.010 | 0.000 | +0.010 |

**D**: the RTL round is worth **+0.091 ns** at the directive it was measured
on, and it takes the failing set below `synth/scripts/census_035.tcl`'s 5,000-path cap for
the first time in this campaign — **`CENSUS_COUNT: 2507` is a count, not a
limit**, where every census in `G5B_TIMING.md` had to be read with the cap
caveat.

**The spread is tight and the top of it is flat.** Three of four rolls land in
**0.040 ns** (−0.156 … −0.196); the fourth, `Explore`, is an outlier at
−0.651. **Why it is an outlier is not established by anything committed
here** — an earlier draft of this sentence attributed it to that roll's router
still being in global iteration when the other three had finished, and no
committed log carries that claim, so it is withdrawn. What is measured is the
number. Drawing again from this distribution is not a plausible way to find
0.156 ns.

---

## 4. THE CENSUS OF THE BEST ROLL OF THE FOUR-DIRECTIVE SPREAD

`po2_AltSpreadLogic_high`, censused on its own
`bd_wrapper_postroute_physopt.dcp` (mtime 2026-09-07 13:51:35, 287,183,326
bytes) by the three instruments the plan names, the family census, and Task
14-A's two cone instruments — all rc 0, all on snoke:

`115_t14b_census_ash.log` (`synth/scripts/census_035.tcl`),
`116_t14b_slrcensus_ash.log` (`synth/scripts/slr_census.tcl`),
`117_t14b_fam_po2_AltSpreadLogic_high.log`
(`evidence/qwen9b/g5/g5b_family_census.tcl`),
`118_t14b_final_verify_ash.log` (`synth/scripts/final_verify.tcl`),
`121_t14b_smem_ash.log` (`g5b_t14a_smem_cascade.tcl`),
`123_t14b_cones_ash.log` (`g5b_t14a_cone_census.tcl`),
`125_t14b_skewprobe_ash.log` (`g5d_clockskew_probe.tcl`).

### 4.1 Headline, and the per-clock table

**T** from `evidence/qwen9b/g5/126_t14b_roll_po2_AltSpreadLogic_high.txt`. All
four MIG UI clocks are **3.332 ns / 300.120 MHz**; `pipe_clk` and
`xdma_0_axi_aclk` are **4.000 ns / 250.000 MHz**. Channel labels are
`G5B_TIMING.md` §5.1's.

| clock | period | WNS | TNS | failing EP | total EP | WHS | failing hold |
|---|---|---|---|---|---|---|---|
| `mmcm_clkout0` (ch0 UI) | 3.332 ns | **+0.003** | 0.000 | **0** | 173,160 | +0.011 | 0 |
| `mmcm_clkout0_2` (ch1 UI) | 3.332 ns | **+0.008** | 0.000 | **0** | 173,251 | +0.010 | 0 |
| `mmcm_clkout0_3` (ch2 UI) | 3.332 ns | **+0.025** | 0.000 | **0** | 173,183 | +0.011 | 0 |
| `mmcm_clkout0_1` (ch3 UI) | 3.332 ns | **+0.013** | 0.000 | **0** | 173,187 | +0.010 | 0 |
| `pipe_clk` | 4.000 ns | **+0.268** | 0.000 | **0** | 4,764 | +0.011 | 0 |
| **`xdma_0_axi_aclk`** | 4.000 ns | **−0.156** | **−126.221** | **2,507** | 576,324 | +0.010 | 0 |

**Five of the six clocks MEET with zero failing endpoints and the entire
deficit is on one domain** — the 250 MHz clock the custom RTL runs on. In the
first campaign's best artifact **three** of six failed
(`G5B_TIMING.md` §8.1: ch2 UI −0.130/866 EP, ch3 UI −0.102/539 EP, aclk
−0.122/2,860 EP). **The two 300 MHz MIG UI clocks that failed there
(`mmcm_clkout0_3` and `mmcm_clkout0_1`, both 3.332 ns) are positive here**, at
**+0.025** and **+0.013**.

### 4.2 The per-SLR census — the placer finds the one-SLR answer again, and picks a THIRD SLR

`116_t14b_slrcensus_ash.log`'s SLICE-bucketed histogram, on a roll with
**`PBLOCK_COUNT: 0`**:

| instance | SLR0 | SLR1 | SLR2 |
|---|---|---|---|
| **`bd_i/layer_0`** | **205,807 (100 %)** | 6 | 0 |
| `bd_i/mvchan_0` | 28,816 (100 %) | 1 | 0 |
| `bd_i/mvchan_1` | 0 | 28,837 (100 %) | 0 |
| `bd_i/mvchan_2` | 0 | 28,797 (100 %) | 0 |
| `bd_i/mvchan_3` | 0 | 28,824 (100 %) | 0 |
| `bd_i/seq_0` | 0 | 7,408 (100 %) | 0 |
| `bd_i/xdma_0` | 0 | 53,042 (100 %) | 0 |

and the dedicated-block half, **T** from
`135_t14b_best_reports.txt`'s section-14 table:

| resource | **SLR0** | SLR1 | SLR2 |
|---|---|---|---|
| **URAM** | **182 = 56.88 %** | **0** | **0** |
| **DSPs** | **1,845 = 80.92 %** | 12 | 3 |
| Block RAM Tile | 112.5 | 113 | 25.5 |
| CLB LUTs | 153,154 | 140,790 | 15,455 |
| CLB Registers | 118,016 | 180,031 | 21,643 |

**The property `G5B_TIMING.md` §5.2 called the most useful thing the first
campaign measured reproduces, and the SLR it picks is a third one.** The whole
layer, all 182 URAM and 1,845 of the design's 1,860 DSPs land in ONE SLR with
no pblock of any kind — but where S5 reasoned SLR1 and Task 14's placer chose
SLR2, 14-B's placer chooses **SLR0**. Three campaigns, three different dies,
the same partition. **The floorplan is not the lever, and the placer does not
need one** — which is why 14-B's primary arms carry none.

`116_t14b_slrcensus_ash.log` also fixes the geometry this document's clock
work depends on, measured from the device rather than assumed:
`SLR0 CR_Y=0..4`, `SLR1 CR_Y=5..9`, `SLR2 CR_Y=10..14`.

**"No pblock" is now carried by the instrument the plan's Step 3 names, not
only by a substitute.** Step 3 of
`docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md` names
`synth/scripts/slr_census.tcl` **and** `synth/scripts/floorplan_check.tcl`;
during the campaign only the first was run, and the pblock fact was carried by
`synth/scripts/full_impl.tcl`'s `PBLOCK_COUNT:` line — measured on each run
itself, which is a good instrument and was an **undeclared substitution**. Fix
round 1 ran the named one, read-only, on the **shipping** roll's checkpoint:
`evidence/qwen9b/g5/172_t14b_fix1_floorplan_check_ckr2.log` reports
`FPCHECK_XDC_READ_OK` and **`FPCHECK_PBLOCK_COUNT: 0`**, then its own
`FPCHECK_FATAL: no pblocks created` and `=== rc: 1`. **That non-zero exit is
the affirmative answer here**: the script was written for the floorplan
campaign, where a run with zero pblocks measures nothing and must stop; on a
deliberately floorplan-free roll the same line is the confirmation. Both
instruments now say the same thing about the artifact, one from the run and
one from the checkpoint.

**The XDC that script was handed is the clock-root file, not a floorplan
file**, and the log says so itself: its `=== cmd:` line
(`evidence/qwen9b/g5/172_t14b_fix1_floorplan_check_ckr2.log:4`) gives
`synth/scripts/floorplan_check.tcl` two `-tclargs` — the shipping roll's out
directory `synth/out_build_041_ckr2_AltSpreadLogic_high` and
`synth/constraints/fable5_clockroot_9b.xdc` — because 14-B created no floorplan
XDC for it to read. So `FPCHECK_XDC_READ_OK` says *that* file parsed against
the routed design, and `FPCHECK_PBLOCK_COUNT: 0` is the **design's** pblock
count with it read in. It is not a pblock file that was opened and found to
define none.

**The DSP counts of §2.2 and this section are different questions, reconciled
here so nobody reads the layer as having grown.** §2.2's **1,840** is the
`bd_layer_0_0` IP's own post-synthesis DSP48E2 count; this section's **1,845**
is every DSP that landed in **SLR0**, whoever owns it. From the shipping roll's
hierarchical utilization, copied into
`evidence/qwen9b/g5/174_t14b_fix1_dsp_owner_reconcile.txt`: `layer_0` 1,840,
each of the four DDR4 MIGs 3, each of the four `mvchan`s 2 — **1,860** device
total. The five above 1,840 in SLR0 are `mvchan_0`'s 2 and `ddr4_0`'s 3 — the
two non-layer DSP owners the SLR census **places** in SLR0
(`144_t14b_slrcensus_ckr2.log:166` and `:170`), every other one being 100 % in
SLR1 or SLR2 on the same lines — and with no other candidate the arithmetic
closes: 1,845 + 12 + 3 = 1,860. **This is a placement plus arithmetic, not a
DSP census**: the SLR census's per-instance histogram counts `SLICE*` LOCs
only (`synth/scripts/slr_census.tcl:69-76`, `if {![string match "SLICE*" $loc]} { continue }`),
so it says which die an owner sits on, never how many of its DSPs went there.
An earlier version of this paragraph said the split was *forced*, which is one
inference more than that instrument can carry. **The layer's DSP count is 1,840
at synthesis and 1,840 on the routed shipping netlist.**

### 4.3 The endpoint owner tally

`synth/scripts/census_035.tcl`'s `OWNER` tally over **all 2,507** failing setup paths
(`115_t14b_census_ash.log`; `CENSUS_COUNT: 2507` is below the instrument's
5,000-path cap, so this is the complete set):

| owner | endpoints | share | kind |
|---|---|---|---|
| **`bd_i/layer_0/inst`** | **2,467** | **98.4 %** | custom |
| `bd_i/axi_smc/inst` | 37 | 1.5 % | vendor (SmartConnect) |
| `bd_i/seq_0/inst` | 3 | 0.1 % | custom |

**D**: 2,467 + 37 + 3 = 2,507. Vendor IP contributes **37 of 2,507 (1.5 %)**,
against 218 of 5,000 (4.4 %) in the first campaign; `bd_i/xdma_0` and the four
`mvchan`s own **zero**.

### 4.4 The four cones Task 14-A removed — gone, measured on the same directive

`123_t14b_cones_ash.log` runs Task 14-A's own instrument
(`evidence/qwen9b/g5/g5b_t14a_cone_census.tcl`) on this checkpoint. Its
comparand is `evidence/qwen9b/g5/062_t14a_po2_cones.log` — **the same
instrument, the same directive, the same recipe, the same absence of a
floorplan, on the BASE netlist**. Only the RTL differs.

| cone | 14 (BASE) EP / worst / logic | **14-B (14-A netlist)** EP / worst / logic |
|---|---|---|
| **`DN_VDATA`** | 12 / −0.247 / **2.596** | **ABSENT** |
| **`CONV_SILU_M3`** | 12 / −0.238 / **2.289** | **ABSENT** |
| **`AT_QDATA`** | 142 / −0.247 / **2.557** | **8 / −0.059 / 0.381** |
| **`AXIL_RDATA`** | 13 / −0.212 / **2.600** | **1 / −0.076 / 1.654** |
| `ATTN_DSP` | 1,679 / −0.243 / 0.368 | **385 / −0.156 / 1.700** ← owns the WNS |
| `DN_LANE` | 2,120 / −0.247 / 0.239 | 1,541 / −0.147 / 1.361 |
| `LAYER_OTHER` | 747 / −0.246 / 1.208 | 229 / −0.145 / 0.328 |
| `SDMA` | 659 / −0.244 / 0.482 | 217 / −0.124 / 0.472 |
| `KV_SLOT` | 146 / −0.234 / 0.330 | 34 / −0.138 / 0.381 |
| `SCRATCH_SMEM` | 53 / −0.212 / 0.118 | 34 / −0.142 / 0.376 |
| `DN_SLOT` | 35 / −0.231 / 0.204 | 16 / −0.143 / 0.212 |
| `VENDOR` | 275 / −0.240 / 0.079 | 37 / −0.127 / 0.670 |
| `MVCHAN` | 107 / −0.207 / 0.079 | **ABSENT** |
| `CV_SLOT` | absent (positive) | 2 / −0.020 / 0.566 |
| `SEQ` | absent | 3 / −0.047 / 0.691 |

**The two cones Task 14-A's stages A and C were written for do not appear in
the failing set at all**, and the two that survive are down from 142 and 13
endpoints to 8 and 1, with their logic content cut from 2.557/2.600 ns to
0.381/1.654 ns.

**The 1.700 ns is a SAMPLE maximum, and the sample is stated.** The
instrument's own cap is `123_t14b_cones_ash.log:38` `T14A_MAX_PATHS: 50`, and
the failing set is `123_t14b_cones_ash.log:126` `T14A_FAILING_SAMPLE: 2507`.
So what the log establishes is: **the largest logic content on the 50 worst
paths, and on every cone's own worst path, is 1.700 ns** — against **2.600 ns**
by the same instrument, the same cap and the same directive on the BASE
netlist. The other ~2,445 failing paths are never scanned for logic delay by
this instrument, and `124_t14b_cones_ash_lld.rpt` is a *logic-level*
distribution (`report_design_analysis -logic_level_distribution`), not a
logic-delay maximum, so it does not close that gap either. The one
full-population logic range this campaign has is on the scratchpad-launched
subset: `121_t14b_smem_ash.log:152` `SMC_SMEM_LOGIC_RANGE: min=1.296 max=1.654`
over all 10 of them.

Scoped that way it is still exactly the claim
`.superpowers/sdd/2026-09-04-qwen35-9b-state-spill/task-14A-design-note.md` §5 said the stages were for: *"the number these
stages move is not this build's WNS; it is the floor."*

### 4.5 The scratchpad-launched set — 159 endpoints, shown gone

`121_t14b_smem_ash.log`, the same instrument as
`evidence/qwen9b/g5/064_t14a_eto_smem.log` and `066_t14a_po2_smem.log`:

| artifact | failing sample | **launched by a scratchpad BRAM** | their slack range | their logic range |
|---|---|---|---|---|
| 14, ETO + playbook (WNS −0.130) | 4,265 | **159 (3.7 %)** | −0.119 … −0.001 | 1.296 … **2.840** |
| 14, `po2_AltSpreadLogic_high` (−0.247) | 6,000 | **315 (5.3 %)** | −0.247 … −0.003 | 1.296 … **2.828** |
| **14-B, `po2_AltSpreadLogic_high` (−0.156)** | **2,507** | **10 (0.4 %)** | −0.135 … −0.001 | 1.296 … **1.654** |
| 14-B, build_041 (−0.859) | 6,000 | **2 (0.03 %)** | −0.432 … −0.343 | **1.296 … 1.296** |

**D**: the scratchpad-launched share of the failing set falls **13×** at
matched directive (5.3 % → 0.4 %), and the maximum logic on those paths falls
from 2.828 ns to 1.654 ns. The same log confirms the cascade on the *routed*
netlist: `SMC_CASCADE_B smem_a FIRST = 16 / LAST = 16` and the same for
`smem_b`, no `MIDDLE` — where the BASE in-context netlist read
`FIRST 5 / MIDDLE 20 / LAST 5` (`064_t14a_eto_smem.log`).

### 4.6 The family census, and the four route-dominated aclk families of the note's §7.2

`117_t14b_fam_po2_AltSpreadLogic_high.log`, against
`G5B_TIMING.md` §5.4's table from the same instrument on the same directive:

| family | 14 worst | **14-B worst** | Δ | 14-B levels / logic / route / route % | start→end SLR |
|---|---|---|---|---|---|
| `DN_SLOT` | −0.231 | **−0.143** | **+0.088** | 2 / 0.212 / 3.380 / 94.1 % | SLR0→SLR0 |
| `KV_SLOT` | −0.234 | **−0.138** | **+0.096** | 2 / 0.381 / 3.299 / 89.6 % | SLR0→SLR0 |
| `CV_SLOT` | +0.090 | **−0.020** | **−0.110** | 3 / 0.566 / 3.155 / 84.8 % | SLR0→SLR0 |
| `SDMA` | −0.244 | **−0.124** | **+0.120** | 5 / 0.472 / 3.101 / 86.8 % | SLR0→SLR0 |
| `ATTN_DSP` | −0.243 | **−0.156** | **+0.087** | 2 / **1.700** / 2.062 / **54.8 %** | SLR0→SLR0 |
| `SCRATCH` | −0.212 | **−0.142** | **+0.070** | 3 / 0.376 / 3.543 / 90.4 % | SLR0→SLR0 |

**Every family improved except `CV_SLOT`**, which went from +0.090 to −0.020 —
the one regression, 2 endpoints, and reported here rather than left to be
found. Every family's worst path still starts and ends in the same SLR: **not
one SLR crossing on any of them.**

Histogram of the 200 worst setup paths: `LAYER_OTHER` 131 (−0.147),
`ATTN_DSP` 55 (−0.156), `SCRATCH` 6 (−0.142), `DN_SLOT` 3 (−0.143),
`KV_SLOT` 2 (−0.138), `VENDOR_SMC` 2 (−0.127), `SDMA` 1 (−0.124), and
`FAM_OTHER_WORST none` — every one of the 200 is in a named family.

**The note's §7.2 named four route-dominated aclk families tied at −0.122 and
asked whether the mux splits (D1, D2) would move them. Each, by name:**

| §7.2 owner | what it was | **what it is now** | verdict |
|---|---|---|---|
| `seq_0/u_seq/rec → pc/CE` — the next-PC enable | −0.122, 11 levels, 0.931 logic / 2.958 route | **+0.278** (`FV_STILL_CHECKED *seq_0*u_seq/*/D`), 3 endpoints in the whole failing set | **CLOSED** |
| `u_dma/f_wp → fmem` LUTRAM write cone | −0.102 (clock), −0.155 (`FV`), family −0.244 | **+0.143** (`FV_STILL_CHECKED *u_core/u_dma/*/D`), family **−0.124** | **CLOSED at the FV probe, family still −0.124** |
| `u_attn/oi → o_g4` — the 4 × 64:1 output mux (**D1 split it**) | −0.122, 3 levels, 0.276 logic / 3.882 route | family **−0.156**, and the cone census puts `ATTN_DSP` at 385 EP against 1,679 | **KEPT NEGATIVE — it now owns the design WNS** |
| `u_dn/oi → o_sel` — the 128:1 mux (**D2 split it**) | −0.122, 5 levels, 0.476 logic / 3.704 route | `DN_LANE` **−0.147**, 1,541 EP against 2,120 | **KEPT NEGATIVE** |

**Two of the four closed, two improved by ~0.09 and are still negative.** The
two that closed are the two the RTL round did *not* touch (§7.2 listed the
sequencer's next-PC enable and the DMA's LUTRAM write cone as *untaken*
items) — they closed because the whole aclk domain moved, not because anything
was done to them. The two that were split are the two that still own the
deficit.

### 4.7 What owns the WNS now, decomposed

`115_t14b_census_ash.log`'s worst paths and `123_t14b_cones_ash.log`'s
per-path split agree:

| slack | levels | logic | route | route % | endpoint ← startpoint |
|---|---|---|---|---|---|
| **−0.156** | 2 | **1.700 (45.2 %)** | 2.062 | 54.8 % | `u_attn/g_lane[38].pv_p_reg[38]_i_8_psdsp_1/D` ← `g_kvslot[0].mem_reg_uram_8/CLK` |
| −0.155 | 6 | 0.568 (14.8 %) | 3.275 | 85.2 % | `u_attn/dot_reg[31]/D` ← `u_attn/g_ps64[3].psum16_reg[3][13]/C` |
| −0.154 | 2 | 1.661 (45.4 %) | 2.001 | 54.6 % | `u_attn/g_lane[76].pv_p_reg[76]/DSP_A_B_DATA_INST/A[3]` ← `g_kvslot[1].mem_reg_uram_16/CLK` |
| −0.149 | 2 | 1.573 (41.5 %) | 2.221 | 58.5 % | `u_attn/g_lane[25].prod_reg[25]_i_8_psdsp_1/D` ← `g_kvslot[1].mem_reg_uram_4/CLK` |
| −0.147 | 1 | 1.361 (35.5 %) | 2.471 | 64.5 % | `u_dn/p_1_out__2__13/DSP_A_B_DATA_INST/A[7]` ← `g_dnslot[1].mem_reg_uram_12/CLK` |

**The owner is the URAM cache READ into the compute DSPs**, and it is the one
the plan's own 2026-09-05 amendment predicted from S5 §4.4: *"the compute READ
out of the KV slot into the attention multipliers"*. It is a **two-level**
path — a URAM288 clock-to-out plus the DSP's input mux — carrying 1.57-1.70 ns
of *cell* delay that no pipeline stage inside the mux can remove, because
there is no mux: the levels are the URAM and the DSP themselves.

`matvec_engine`'s 300 MHz `xline_q0` CE cone, which owned the first campaign's
design WNS at −0.130 under `ExtraTimingOpt`, is **closed on this directive
family exactly as Task 14-A's stage E predicted**: `XLINE_CE_NEGATIVE_COUNT: 0`
over 1,000 paths and 4,096 CE pins, worst **+0.014**
(`XLINE_CE_SPLIT slack=0.014 logic=0.376 route=2.565`), per channel
mvchan_0 +0.014, mvchan_2 +0.079, mvchan_3 +0.361.

**One instrument caveat, stated.** `synth/scripts/final_verify.tcl` and `synth/scripts/census_035.tcl`
report `XLINE_CE_WORST_mvchan_*` only for channels that appear among the 1,000
worst CE paths; on this roll **mvchan_1 does not appear at all**, which means
its worst CE path is better than +0.361, not that it was not analysed. The
`FV_STILL_CHECKED` assertion for the pattern as a whole passed (`FV_OK`).

### 4.8 The `FV_*` markers on the roll

`118_t14b_final_verify_ash.log`, rc 0, `synth/scripts/final_verify.tcl` on the
roll's own checkpoint with `synth/constraints/fable5_xdma_rst_exception.xdc`
applied:

```
FV_WNS: -0.156           FV_WHS: 0.010
FV_FAILING_SETUP: 2507   FV_FAILING_HOLD: 0
FV_XLINE_PATTERN: *u_engine/xline_q0_reg*/CE
FV_XLINE_WORST_mvchan_0: 0.014   mvchan_2: 0.079   mvchan_3: 0.361
FV_STILL_CHECKED *layer_0*u_core/u_dn/*/D    slack=-0.129
FV_STILL_CHECKED *layer_0*u_core/u_dma/*/D   slack=0.143
FV_STILL_CHECKED *layer_0*u_core/u_attn/*/D  slack=-0.156
FV_STILL_CHECKED *seq_0*u_seq/*/D            slack=0.278
FV_STILL_CHECKED *u_engine/xline_q0_reg*/CE  slack=0.014
FV_OK
```

`FV_FAILING_SETUP: 2507` equals the design summary's 2,507 — **the 5,000-path
cap that qualified every equivalent number in `G5B_TIMING.md` does not bite
here.** The exception XDC changes `FV_WNS` by nothing, exactly as in the first
campaign: it is scoped inside `xdma_0`, which owns zero failing endpoints.

**The six tracked owner classes against build_035 SHIPPED** (which had zero
failing endpoints in every class) and against Task 14's best roll:

| class | build_035 shipped | Task 14 best roll | **Task 14-B best roll** | verdict vs Task 14 |
|---|---|---|---|---|
| `matvec_engine` (`xline_q0`/CE) | 0 EP, +0.077 … +0.221 | 0 negative, +0.009 … +0.185 | **0 negative, +0.014 … +0.361** | **KEPT CLOSED**, more margin |
| `seq_0` MOV | 0 EP, +0.011 | +0.037 | **+0.278** | **KEPT CLOSED**, 7× the margin |
| `layer_0` / `u_dma` (SDMA) | did not exist | −0.155 | **+0.143** | **CLOSED** |
| `layer_0` / caches (DN/KV/CV) | did not exist | −0.231 / −0.234 / +0.090 | **−0.143 / −0.138 / −0.020** | improved, **still negative** |
| `layer_0` / `u_dn` | 0 EP, +0.001 | −0.244 | **−0.129** | improved, **still negative** |
| `layer_0` / `ATTN_DSP` | 0 EP | −0.243 | **−0.156** | improved, **still negative — owns the WNS** |

---

## 5. THE CLOCK-SKEW ARM

### 5.1 The probe — read-only, and it supports the arm

`.superpowers/sdd/2026-09-04-qwen35-9b-state-spill/task-14A-design-note.md` §7.3 recorded a term it did not propose to change:
the layer's paths carried `Clock Path Skew: −0.340 ns` against −0.117 … −0.169
elsewhere on an `aclk` net with fan-out 148,450. 14-B's brief made it the one
constraint-side arm **on condition that a read-only probe support it first**.

The instrument is new: `evidence/qwen9b/g5/g5d_clockskew_probe.tcl`. It was
first run on the **first campaign's own artifact** as a dry run
(`104_t14b_skewprobe_14A_comparand.log`, rc 0, reports
`105_t14b_skewprobe_14A_*.rpt`), where it reproduces the design note's number
to the digit — `Clock Path Skew: −0.340ns`, `Source Clock Delay 3.210`,
`Clock Net Delay (Source) 2.995 ns`, root `X3Y9`, `SLR Crossing[1->2]` on both
clock legs — which is what says the instrument measures what the note measured.

**On `po2_AltSpreadLogic_high`** (`125_t14b_skewprobe_ash.log`, rc 0, reports
`130_t14b_skewprobe_ash_*.rpt`), **T**:

| | value |
|---|---|
| aclk net | `…/phy_clk_i/PHY_USERCLK`, driven by `BUFG_GT_X1Y203` |
| loads | **150,233** |
| `CLOCK_ROOT` (placer's choice) | **X2Y5** — the bottom row of **SLR1** |
| `USER_CLOCK_ROOT` | **(none)** |
| `layer_0`'s 2,101 dedicated blocks | clock-region rows **Y0…Y4** = **SLR0**, X0…X5 |

and, on the paths:

| probe | slack | Clock Path Skew | SCD | DCD | Clock Net Delay src / dst | SLR hop on the clock |
|---|---|---|---|---|---|---|
| **the design's worst (in `layer_0`)** | **−0.156** | **−0.372** | 4.225 | 3.599 | **4.010 / 3.407** | **`SLR Crossing[1->0]` on BOTH legs** |
| `seq_0` (sits in SLR1, beside the root) | +0.278 | **−0.058** | 3.786 | 3.425 | 3.571 / 3.233 | none |
| `mvchan_0` (300 MHz ch0 UI, own root X3Y4) | +0.003 | −0.119 | 4.851 | 5.065 | 2.641 / 2.416 | none |

**D**: the layer's worst path pays **0.314 ns more clock skew than the
sequencer on the same clock** (−0.372 vs −0.058), and the report names the
mechanism — the root is on the far side of an SLR boundary from every load on
that path, so the two legs differ by **0.603 ns** of clock net delay
(4.010 − 3.407) after the crossing. **The probe supports the arm**, and it
also says the term is *placement-dependent rather than systemic*: on build_041,
whose placer put the layer in SLR0 with the root at X3Y5, the same probe reads
skew **−0.089** on the layer and **−0.101** on the sequencer
(`110_t14b_skewprobe_041.log`) — no anomaly at all.

### 5.2 A RED the arm produced before it ran: a guard that Vivado silently skipped

`synth/constraints/fable5_clockroot_9b.xdc`'s first version carried its own
assertion — two `if` guards on the net count and a confirming `puts`. **A
managed-project run parses an implementation-only XDC with Vivado's restricted
constraint parser, which accepts `set_property` but not `if` and not `puts`**,
and it dropped all three with a CRITICAL WARNING each
(`132_t14b_clockroot_xdc_RED.txt`, verbatim from the burnt roll's own impl
log). The file would then have constrained the design with **no assertion that
it had constrained anything** — the silent-no-op class this campaign has been
bitten by twice.

That roll (`TAG=ckr`) was **killed 22 minutes in**, before any checkpoint
existed; its out dir is burnt and never reused, and evidence log number **131**
is burnt with it (its `evidence/qwen9b/run.sh` log has no `=== rc:` because I killed the
wrapper, so it is not committed — `132` is the finding it produced).

**The repair, and the guard that does run.** The XDC is now one parser-legal
`set_property` and no control flow. The assertion moved into a read-only
`-source` script, where the full Tcl interpreter is available:
`evidence/qwen9b/g5/g5d_clockroot_check.tcl` opens a real checkpoint, reads
`USER_CLOCK_ROOT` **before**, applies the file, reads it **after**, and exits
non-zero unless it changed to the expected region. It ran **before** the
four-hour roll (`133_t14b_clockroot_check.log`, rc 0), on
`po2_AltSpreadLogic_high`'s own checkpoint:

```
CRC_NET_COUNT: 1
CRC_NET: bd_i/xdma_0/…/phy_clk_i/PHY_USERCLK
CRC_LOADS: 150233
CRC_BEFORE_USER_CLOCK_ROOT: '(none)'      CRC_BEFORE_CLOCK_ROOT: 'X2Y5'
CRC_RED_OK: no USER_CLOCK_ROOT before the file is applied
CRC_AFTER_USER_CLOCK_ROOT:  'X2Y2'        CRC_AFTER_CLOCK_ROOT:  'X2Y5'
CRC_GREEN_OK / CRC_OK
```

**That is a RED and a GREEN on the same object**: the property is provably
absent before and provably `X2Y2` after, on exactly one net carrying 150,233
loads. Reading the property back off the netlist is a stronger check than the
`puts` that could not run.

**The coordinate is computed, not chosen.** X2Y2 is the centroid of
`layer_0`'s 2,101 dedicated blocks from the probe's own histogram: rows
347/452/512/487/303 → 4,149/2,101 = **1.975 → Y2**; columns
502/429/395/315/388/72 → 4,076/2,101 = **1.940 → X2**. `layer_0` owns 98.4 %
of the failing endpoints (§4.3), so its centroid is where a clock root that has
to serve one owner belongs. **The cost is stated rather than discovered**:
`seq_0`, `xdma_0` and 78 % of `axi_smc` are in SLR1 and their clock legs get
longer. **No clock, MMCM, BUFG, CDC or pblock is added** — `USER_CLOCK_ROOT`
only tells the clock placer where to drive an existing global net from, and the
design stays single-clock-domain.

---

## 6. THE PLAYBOOK — CENSUS → SPREAD → POST-ROUTE `phys_opt`, AND WHERE IT STOPS

The house closure playbook's last step, `evidence/qwen9b/g5/g5b_physopt_playbook.tcl`
(Task 14's argument-parameterised copy of `synth/scripts/po_035.tcl`, nothing
else changed), on the best roll: `119_t14b_playbook_ash.log`, rc 0,
out dir `synth/out_g5d_po_ash`. **WNS/TNS before and after every step, T:**

| step | WNS | Δ | WHS | TNS |
|---|---|---|---|---|
| in (`po2_AltSpreadLogic_high`) | **−0.156** | — | +0.010 | −126.221 |
| `phys_opt_design -directive AlternateReplication` | −0.156 | **0.000** | +0.010 | — |
| `phys_opt_design -directive AggressiveFanoutOpt` | −0.156 | **0.000** | +0.010 | — |
| `phys_opt_design -directive Explore` | −0.156 | **0.000** | +0.010 | — |
| `phys_opt_design -directive AggressiveExplore` | −0.156 | **0.000** | +0.010 | — |
| `route_design -preserve` | **−0.156** | **0.000** | **+0.010** | **−126.221** |

`POPB_FINAL: WNS=-0.156 WHS=0.010`, `POPB_NOT_CLOSED`. The hold guard
(`POPB_HOLD_REGRESSION`) never fired.

**+0.000 ns total.** `137_t14b_roll_playbook_ash.txt` is the design timing
summary of the playbook's own output and it is **identical, field for field**,
to the input roll's: `-0.156 -126.221 2507 1318525 0.010 0.000 0 1315389`.
The first campaign's playbook bought +0.033 from −0.163 to −0.130
(`G5B_TIMING.md` §8) and saturated on its last directive; **this one saturates
on its first.** That is not a worse playbook — it is a residual the playbook
does not address at all: §4.7's owner is a URAM-to-DSP path with 1.700 ns of
cell delay and two logic levels, and `phys_opt` buys routing.

`136_t14b_final_verify_playbook.log` runs `synth/scripts/final_verify.tcl` on the playbook's
own `bd_wrapper_po_routed.dcp` (290,038,759 bytes, 2026-09-07 16:10) so the
chosen checkpoint is verified independently of the run that produced it. It
reports the identical `FV_*` set — `FV_WNS: -0.156`, `FV_WHS: 0.010`,
`FV_FAILING_SETUP: 2507`, `FV_FAILING_HOLD: 0`, `FV_OK`.

---

## 7. UTILIZATION — Task 14-A's price, on the device

**This section is priced on the roll that SHIPS.** The first version of it was
priced on roll #2 (`po2_AltSpreadLogic_high`) — the roll that did *not* ship —
and the shipping roll's own `report_utilization` was already committed and
unused. Both columns are kept, labelled, because the difference between them is
itself a measurement of what the clock-root roll cost in area: **nothing worth
noticing** (LUT −235, FF −518, every other row identical to the unit).

Sources, all post-route: the **shipping** roll from
`evidence/qwen9b/g5/153_t14b_closing_reports.txt` (its own
`report_utilization`, mtime 2026-09-07 20:56:07); **roll #2** from
`evidence/qwen9b/g5/135_t14b_best_reports.txt` (mtime 2026-09-07 14:13:39);
Task 14's best roll on the BASE netlist from
`evidence/qwen9b/g5/046_po2_best_reports.txt`; build_035 SHIPPED from
`evidence/qwen2b/rc/TIMING_035.md` §8b.

| resource | build_035 shipped | Task 14 best roll | 14-B roll #2 (**not** shipped) | **14-B CLOSING roll (SHIPPED)** | Δ shipped vs Task 14 |
|---|---|---|---|---|---|
| **CLB LUTs** | 299,076 | 306,312 (25.91 %) | 309,399 (26.17 %) | **309,164 (26.15 %)** | **+2,852** |
| — LUT as Logic | 260,396 | 256,409 | 259,496 | **259,261** | +2,852 |
| — LUT as Memory | 33,724 | 49,903 | 49,903 | **49,903** | **0** |
| — LUT as Distributed RAM | — | 43,780 | 43,780 | **43,780** | **0** |
| — LUT as Shift Register | 4,956 | 6,123 | 6,123 | **6,123** | **0** |
| **CLB Registers** | 292,520 | 317,866 (13.44 %) | 319,690 (13.52 %) | **319,172 (13.50 %)** | **+1,306** |
| **CARRY8** | 13,681 | 11,727 (7.94 %) | 11,722 (7.93 %) | **11,722 (7.93 %)** | **−5** |
| **Block RAM Tile** | 561 | 247 (11.44 %) | 251 (11.62 %) | **251 (11.62 %)** | **+4** |
| **URAM288** | 348 (36.25 %) | 182 (18.96 %) | 182 (18.96 %) | **182 (18.96 %)** | **0** |
| **DSP48E2** | 1,858 (27.16 %) | 1,858 (27.16 %) | 1,860 (27.19 %) | **1,860 (27.19 %)** | **+2** |

**D, on the shipped column**: the three dedicated-resource deltas against
Task 14 are Task 14-A's and match the layer's own synthesis deltas of §2.2 to
the unit — DSP **+2**, Block RAM **+4**, CARRY8 **−5**. The LUT and FF deltas
are **+2,852** and **+1,306** against the layer-only **+2,608** and **+1,635**:
they bracket the layer figures rather than reproducing them, which is what a
device total does — it contains everything the placer and two `phys_opt` passes
did around the layer on *both* sides of the comparison, and this document does
not claim to decompose it. **The distributed-RAM and shift-register rows are
unchanged to the unit**, which is the check that the RTL round touched no
memory inference.

**Nothing here is a fit problem.** On the shipped roll the largest device
utilization is **26.15 %** (LUTs); URAM 18.96 %, DSP 27.19 %, block RAM
11.62 %. The binding number is still the per-SLR one — **DSP 1,845 of 2,280 =
80.92 % of SLR0** (§4.2), the resource S5 named as tight — and even that is not
full. **This design does not miss timing because the part is full.**

---

## 8. THE ARM'S RESULT — THE CLOCK ROOT CLOSES THE GATE

`evidence/qwen9b/g5/134_t14b_arm_clockroot_ckr2.log`, rc 0, `=== host: snoke`,
2026-09-07T16:03:37 → 20:57:41 = **4 h 54 m**.

**The command, and how much of it the log actually witnesses.** The invocation
was `TAG=ckr2 XDC=…/fable5_clockroot_9b.xdc synth/scripts/launch_po2.sh
build_041 AltSpreadLogic_high`, but log 134's `=== cmd:` line records only
`synth/scripts/launch_po2.sh build_041 AltSpreadLogic_high` — the wrapper
captures `$*`, i.e. argv, and an environment prefix is not argv. The two
environment values are recoverable from the run's own artifacts rather than
taken on trust: **`TAG=ckr2`** from the out-dir name
`synth/out_build_041_ckr2_AltSpreadLogic_high` that `synth/scripts/launch_po2.sh` derives
from it, and **`XDC=`** from the `EXTRA_XDC:` and `TIMING: … XDC=<path>` lines
below, which name the file by absolute path. Its own fullimpl.log:

```
EXTRA_XDC: /…/synth/constraints/fable5_clockroot_9b.xdc (implementation-only)
FULL_IMPL_CFG: place=AltSpreadLogic_high phys_opt=AggressiveExplore (post-place AND post-route enabled)
TIMING: WNS=0.000 WHS=0.001 DIRECTIVE=AltSpreadLogic_high RECIPE=full XDC=/…/fable5_clockroot_9b.xdc
PBLOCK_COUNT: 0
WHS_GATE: OK whs=0.001
```

The XDC **parsed** with no CRITICAL WARNING this time (the burnt roll's three
are §5.2's RED). **The RUN produced one, and it is about this constraint —
§8.5.** The property is on the design that was built:
`146_t14b_skewprobe_ckr2.log:193` reads it back off the routed checkpoint —
`loc=BUFG_GT_X1Y198 root=X2Y2 user_root=X2Y2 loads=149574`.

### 8.1 The controlled A/B — one variable, the XDC list

Same netlist, same project, same directive, same full recipe, same absence of
any pblock. **The only difference is the one implementation-only XDC.**

| arm | XDC | WNS | TNS | failing setup EP | WHS | failing hold EP |
|---|---|---|---|---|---|---|
| `po2_AltSpreadLogic_high` | **none** | −0.156 | −126.221 | 2,507 | +0.010 | 0 |
| **`ckr2_AltSpreadLogic_high`** | **`synth/constraints/fable5_clockroot_9b.xdc`** | **0.000** | **0.000** | **0** | **+0.001** | **0** |
| **Δ** | | **+0.156** | **+126.221** | **−2,507** | −0.009 | 0 |

**D: the clock-root move is worth +0.156 ns of WNS and it removes every one of
the 2,507 failing setup endpoints.** Across every roll this campaign scored,
`ckr2_AltSpreadLogic_high` holds the best WNS and the best TNS and the fewest
failing setup endpoints. For contrast, the whole house `phys_opt`
playbook on the same starting point bought **+0.000** (§6), and the entire
six-roll directive spread spans 0.512 ns without reaching zero (§9).

**And it is not free on hold, which is said here rather than left in a table.**
`po2_AltSpreadLogic_high` holds the best WHS of the campaign at **+0.010**;
the closing roll ships on **+0.001**. Both meet the criterion, and neither has
a single failing hold endpoint, but the arm spends 0.009 ns of hold margin to
buy 0.156 ns of setup.

### 8.2 The mechanism, measured — it is the clock, not the datapath

`125_t14b_skewprobe_ash.log` (before) and `146_t14b_skewprobe_ckr2.log` (after),
on the worst path of each roll, **T**:

| | `po2_…_high` (no XDC) | **`ckr2_…_high` (XDC)** | Δ |
|---|---|---|---|
| slack | −0.156 | **0.000** | +0.156 |
| **Clock Path Skew** | **−0.372** | **+0.035** | **+0.407** |
| Source Clock Delay | 4.225 | 4.579 | −0.354 |
| Destination Clock Delay | 3.599 | 4.237 | +0.638 |
| Clock Pessimism Removal | 0.254 | 0.377 | +0.123 |
| Data Path Delay | 3.762 (logic 1.700) | **3.715 (logic 1.652)** | +0.047 |
| `CLOCK_ROOT` | X2Y5 (SLR1) | **X2Y2 (SLR0)** | |

**READ THE TABLE AS TWO PATHS, NOT ONE.** Each column is **that roll's own
worst path**, which is what the probe reports; they are different paths and the
row-by-row Δ is a comparison of two worst cases, not one path measured twice.
Both are the same *shape* — a KV-slot URAM288 clock-to-out into an attention
multiplier inside `layer_0` — and that is why the comparison is meaningful, but
the endpoints differ:

| roll | source, line 17 | destination, line 19 |
|---|---|---|
| `po2_…_high` | `…/u_core/g_kvslot[0].mem_reg_uram_8/CLK` | `…/u_attn/g_lane[38].pv_p_reg[38]_i_8_psdsp_1/D` |
| `ckr2_…_high` | `…/u_core/g_kvslot[0].mem_reg_uram_50/CLK` | `…/u_attn/g_lane[225].pv_p_reg[225]/DSP_A_B_DATA_INST/A[9]` |

(`130_t14b_skewprobe_ash_design_worst.rpt` and
`147_t14b_skewprobe_ckr2_design_worst.rpt`, lines 17 and 19 of each.)

**The data path barely moved (+0.047 ns between the two worst paths) and the
skew moved +0.407.** Both clock legs still show `SLR Crossing[1->0]`. **The
driving buffer did move**, and an earlier version of this paragraph said it
could not: it is `BUFG_GT_X1Y203` on the unconstrained roll and
`BUFG_GT_X1Y198` on the closing one (`125_t14b_skewprobe_ash.log:193` against
`146_t14b_skewprobe_ckr2.log:193`). What **cannot** move is its *column and
its SLR*: a `BUFG_GT` lives in the GT column beside the PCIe transceivers in
SLR1, so the buffer stays in SLR1 and both clock legs keep crossing into SLR0
however the root is placed. With the root inside the layer's own SLR the two
legs are now nearly balanced (4.364 vs 4.045 ns of clock net delay, against
4.010 vs 3.407 before), and it is the *imbalance*, not the insertion delay,
that setup slack pays for.

**The cost landed where §5.2 said it would, and it was affordable.** `seq_0`,
which sits in SLR1 beside the old root, sees its skew go from −0.058 to
**−0.096** — and still ends at **+0.397** of slack, because its data path
improved. No clock, MMCM, BUFG or CDC was added; `PBLOCK_COUNT: 0`.

### 8.3 The census of the closing roll — everything meets

`142_t14b_final_verify_ckr2.log` (`synth/scripts/final_verify.tcl`, rc 0),
`143_t14b_census_ckr2.log`, `144_t14b_slrcensus_ckr2.log`,
`145_t14b_fam_ckr2_AltSpreadLogic_high.log`, `149_t14b_cones_ckr2.log`,
`151_t14b_smem_ckr2.log`, `153_t14b_closing_reports.txt`.

**Per clock, T** from `141_t14b_roll_ckr2_AltSpreadLogic_high.txt`:

| clock | period | WNS | TNS | failing EP | total EP | WHS | failing hold |
|---|---|---|---|---|---|---|---|
| `mmcm_clkout0` (ch0 UI) | **3.332 ns** | **+0.003** | 0.000 | **0** | 173,220 | +0.010 | **0** |
| `mmcm_clkout0_2` (ch1 UI) | **3.332 ns** | **+0.031** | 0.000 | **0** | 173,278 | +0.010 | **0** |
| `mmcm_clkout0_3` (ch2 UI) | **3.332 ns** | **+0.016** | 0.000 | **0** | 173,285 | +0.010 | **0** |
| `mmcm_clkout0_1` (ch3 UI) | **3.332 ns** | **+0.026** | 0.000 | **0** | 173,280 | +0.010 | **0** |
| `pipe_clk` | 4.000 ns | **+0.766** | 0.000 | **0** | 4,764 | +0.011 | **0** |
| `xdma_0_axi_aclk` | 4.000 ns | **0.000** | 0.000 | **0** | 577,372 | +0.001 | **0** |
| **design** | | **0.000** | **0.000** | **0** of 1,319,855 | | **+0.001** | **0** of 1,316,719 |

Pulse width: WPWS 0.000, **0** failing of 392,523.

**The `FV_*` markers on the shipping checkpoint** (`142_…`, rc 0, with
`synth/constraints/fable5_xdma_rst_exception.xdc` applied):

```
FV_WNS: 0.000            FV_WHS: 0.001
FV_FAILING_SETUP: 0      FV_FAILING_HOLD: 0
FV_XLINE_PATTERN: *u_engine/xline_q0_reg*/CE
FV_XLINE_WORST_mvchan_0: 0.213  mvchan_1: 0.156  mvchan_2: 0.402  mvchan_3: 0.138
FV_STILL_CHECKED *layer_0*u_core/u_dn/*/D    slack=0.003
FV_STILL_CHECKED *layer_0*u_core/u_dma/*/D   slack=0.004
FV_STILL_CHECKED *layer_0*u_core/u_attn/*/D  slack=0.018
FV_STILL_CHECKED *seq_0*u_seq/*/D            slack=0.397
FV_STILL_CHECKED *u_engine/xline_q0_reg*/CE  slack=0.138
FV_OK
```

**Every one of the tracked classes is positive, and all four channels report
this time** (§4.7's caveat about `mvchan_1` not appearing does not apply here).
`synth/scripts/census_035.tcl` agrees independently: `CENSUS_COUNT: 0`,
`XLINE_CE_NEGATIVE_COUNT: 0` over 1,000 paths and 4,096 CE pins.

**The six owner classes, closed:**

| class | build_035 shipped | Task 14 best roll | 14-B best unconstrained | **14-B closing roll** |
|---|---|---|---|---|
| `matvec_engine` (`xline_q0`/CE) | +0.077 … +0.221 | +0.009 … +0.185 | +0.014 … +0.361 | **+0.138 … +0.402, all four channels** |
| `seq_0` MOV | +0.011 | +0.037 | +0.278 | **+0.397** |
| `layer_0` / `u_dma` (SDMA) | n/a | −0.155 | +0.143 | **+0.004** |
| `layer_0` / `u_dn` | +0.001 | −0.244 | −0.129 | **+0.003** |
| `layer_0` / `u_attn` (ATTN_DSP) | 0 EP | −0.243 | −0.156 | **+0.018** |
| `layer_0` / caches DN / KV / CV | n/a | −0.231 / −0.234 / +0.090 | −0.143 / −0.138 / −0.020 | **+0.070 / +0.013 / +0.450** |

**The family census** (`145_…`) has every family **non-negative** — not
"positive": `ATTN_DSP` is exactly **0.000**, which is the design WNS and is
printed as such two sentences below — and every worst path starting and ending
in the same SLR. Of the two rolls this campaign ran the
family census on, `ckr2_AltSpreadLogic_high` holds the best DN_SLOT, KV_SLOT,
CV_SLOT, SDMA, ATTN_DSP and SCRATCH slack: `DN_SLOT` +0.070, `KV_SLOT` +0.013,
`CV_SLOT` +0.450, `SDMA` +0.001, `ATTN_DSP` 0.000, `SCRATCH` +0.084 — all
`SLR0 → SLR0`. The 200-worst histogram is `LAYER_OTHER` 129, `ATTN_DSP` 37,
`SDMA` 27, `KV_SLOT` 3, `VENDOR_MIG` 3, `VENDOR_SMC` 1, `FAM_OTHER_WORST none`.

**Per SLR** (`144_…`, `153_…`), still with **no pblock**: `bd_i/layer_0`
**205,202 of 205,204 slices in SLR0**, `mvchan_0` in SLR0 with it,
`mvchan_1/2/3`, `seq_0` and `xdma_0` 100 % in SLR1; **URAM 182 / 0 / 0**
(56.88 % of SLR0), **DSPs 1,845 / 12 / 3** (80.92 % of SLR0), Total SLLs used
**4,303 of 17,280**. **"No pblock" on this checkpoint is stated by the plan's
own named instrument as well as by the run**:
`evidence/qwen9b/g5/172_t14b_fix1_floorplan_check_ckr2.log` reports
**`FPCHECK_PBLOCK_COUNT: 0`** on this roll's `bd_wrapper_postroute_physopt.dcp`
— see §4.2 for why that script then exits non-zero and why that is the
affirmative answer here.

**The cone census and the scratchpad census on this roll are empty by
construction**: `149_t14b_cones_ckr2.log` reads `T14A_FAILING_SAMPLE: 0` and
`151_t14b_smem_ckr2.log` reads `SMC_TALLY: smem_launched=0 other=0 of 0` —
there is no failing set left to classify. **One reading note so nobody quotes a
sentinel as a measurement**: with an empty set, that instrument prints its
initialisers, `SMC_SMEM_SLACK_RANGE: worst=99 best=-99` and
`SMC_SMEM_LOGIC_RANGE: min=99 max=-99`. Those are not numbers. The cascade
tally in the same log is real and unchanged: `smem_a` and `smem_b` both
`CASCADE_ORDER_B FIRST = 16 / LAST = 16`, no `MIDDLE`, on the routed shipping
netlist.

### 8.4 The playbook on the closing roll

`148_t14b_playbook_ckr2.log`, rc 0, out dir `synth/out_g5d_po_ckr2`:

| step | WNS | Δ | WHS |
|---|---|---|---|
| in (`ckr2_AltSpreadLogic_high`) | 0.000 | — | +0.001 |
| `AlternateReplication` / `AggressiveFanoutOpt` / `Explore` / `AggressiveExplore` | 0.000 | **0.000** each | +0.001 |
| `route_design -preserve` | **0.000** | **0.000** | **+0.001** |

`POPB_FINAL: WNS=0.000 WHS=0.001`, then **`POPB_BITSTREAM`** and
**`POPB_CLOSED`** — that script writes a bitstream **only** when both WNS and
WHS are non-negative, so `POPB_CLOSED` is an independent second statement of
the gate criterion by a script written for build_035 and not modified for this
one. `154_t14b_final_verify_po_ckr2.log` verifies its output checkpoint and
reproduces the whole `FV_*` set, `FV_FAILING_SETUP: 0`, `FV_OK`.

### 8.5 THE RUN'S ONE CRITICAL WARNING — the tool asks for this constraint to be deleted

**The shipping implementation carries exactly one CRITICAL WARNING, and it is
about the constraint this gate turns on.** An earlier version of §8 said the
XDC *"parsed with no CRITICAL WARNING this time"*, which is true of the parse
and invites the wrong conclusion about the run. The evidence file is
`evidence/qwen9b/g5/173_t14b_fix1_place30890_ckr2.txt`, copied verbatim out of
the roll's own gitignored implementation log proj/stage1.runs/impl_1/runme.log,
line 767 (Vivado's own tally on
that log's last invocation is `1625 Infos, 297 Warnings, 1 Critical Warnings
and 0 Errors encountered.`). Verbatim, with the one long net name wrapped for
page width and nothing else changed:

```
CRITICAL WARNING: [Place 30-890] Clock net 'bd_i/xdma_0/inst/pcie4_ip_i/inst/
bd_xdma_0_0_pcie4_ip_gt_top_i/diablo_gt.diablo_gt_phy_wrapper/phy_clk_i/PHY_USERCLK'
has a user defined clock root in clock region X2Y2, which is different than the
optimal location for the clock root of this net. Please remove the user defined
clock root for better timing.
```

**Three measurements answer it, and none of them is an argument.**

1. **The A/B says the opposite of the advice, at the same directive.** "Remove
   it for better timing" is a heuristic about where the placer would have put
   the root. §8.1 is the controlled experiment: same netlist, same project,
   same `AltSpreadLogic_high`, same full recipe, `PBLOCK_COUNT: 0` both sides,
   the file the only difference — **−0.156 → 0.000 and 2,507 → 0 failing setup
   endpoints**. The constraint the tool asks to delete is worth **+0.156 ns and
   2,507 endpoints** on this design.
2. **`[Timing 38-282]` is absent here and present on both unconstrained rolls.**
   The single critical warning on `po2_AltSpreadLogic_high` and on `build_041`
   is *"The design failed to meet the timing requirements"*; the shipping roll
   does not carry it (grep count 0). That is a second statement, by the same
   tool in the same log class, that this roll met.
3. **The check the tool's own companion WARNING asks for was run, and it
   passes.** `[Place 30-934]`, immediately above the critical warning, is the
   actionable half: it says X2Y2 is outside the region set that meets the
   `PCIE40E4` max-skew requirement "under all circumstances", and instructs the
   reader to verify max skew on `…/pcie_4_0_e4_inst` in the routed database.
   The shipping roll's own `report_timing_summary` carries both of that cell's
   max-skew checks at `PCIE40E4_X1Y2`, and **both are MET**: `CORECLK` vs
   `PIPECLK` slack **+0.041**, `PIPECLK` vs `CORECLK` **+0.029** (required
   0.357). Without the file the same two rows read **+0.097** and **+0.081**.
   **So the constraint does cost ~0.05 ns of PCIE max-skew margin, and it does
   not violate it** — the rows, verbatim, are §5 of file 173. Design-wide the
   same statement is the pulse-width column: **WPWS 0.000, 0 failing of
   392,523** (§8.3).

**What is NOT claimed**: that the tool is wrong about its own heuristic, or
that a future placement would behave the same way. The warning is a standing
invitation to re-measure, and §11 says what re-measuring means.

---

## 9. THE CAMPAIGN TABLE, COMPLETE

Ten implementation runs on the 14-A netlist, one burnt. Every one on snoke,
every one with **no pblock** (`PBLOCK_COUNT: 0` where the run reached that
line).

| # | roll | recipe | directive | XDC | WNS | TNS | failing setup EP | WHS | `WHS_GATE:` |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `build_041` | default | — | none | −0.859 | −5,879.083 | 29,237 | +0.006 | n/a (`synth/scripts/build.tcl`) |
| 2 | `po2_AltSpreadLogic_high` | full | `AltSpreadLogic_high` | none | −0.156 | −126.221 | 2,507 | +0.010 | OK |
| 3 | `po2_AltSpreadLogic_medium` | full | `AltSpreadLogic_medium` | none | −0.159 | −182.889 | 3,629 | +0.010 | OK |
| 4 | `po2_ExtraTimingOpt` | full | `ExtraTimingOpt` | none | −0.196 | −312.103 | 4,460 | 0.000 | OK |
| 5 | `po2_Explore` | full | `Explore` | none | −0.651 | −3,471.757 | 19,611 | 0.000 | OK |
| 6 | `po4_ExtraNetDelay_high` | full | `ExtraNetDelay_high` | none | **−0.139** | −165.674 | 3,461 | +0.002 | OK |
| 7 | `po4_ExtraPostPlacementOpt` | full | `ExtraPostPlacementOpt` | none | — | — | — | — | **no bitstream: 24 × DRC RTSTAT-11** |
| 8 | `playbook_ash` | playbook on #2 | — | none | −0.156 | −126.221 | 2,507 | +0.010 | `POPB_NOT_CLOSED` |
| 9 | **`ckr2_AltSpreadLogic_high`** | full | `AltSpreadLogic_high` | **clock-root** | **0.000** | **0.000** | **0** | **+0.001** | **OK** |
| 10 | `playbook_ckr2` | playbook on #9 | — | clock-root | **0.000** | **0.000** | **0** | **+0.001** | **`POPB_CLOSED`** |
| — | *(burnt)* `ckr_AltSpreadLogic_high` | full | `AltSpreadLogic_high` | clock-root **v1** | killed at 22 min | | | | §5.2's RED |

**Two honest notes on this table.**

1. **The census of §4 was run on roll #2, which led the four-directive spread
   at the time it was censused.** Roll #6, a supplementary directive launched
   later, finished at **−0.139**, so `po4_ExtraNetDelay_high` has the best WNS
   of the rolls that carried no XDC — a subset this document's checker cannot
   see, so the claim is marked `superlative-check: scoped` and the full
   ranking is printed beside it. The 0.017 ns between them does not touch any
   conclusion in §4 — and it does not touch §8's A/B either, which is
   controlled on the directive (#2 vs #9 are the same directive with and
   without the file).
2. **Roll #7 produced no bitstream** and its verdict is recorded in
   `158_t14b_po4_ExtraPostPlacementOpt_bitgen_DRC.txt`: it routed and
   post-route phys_opt'd, then `write_bitstream` failed **24 `[DRC RTSTAT-11]
   Invalid Site Programming` errors (of 28 DRC errors), all on nets inside the
   vendor SmartConnect `bd_i/smc_ch0/…/s00_r_node` XPM FIFO, all at one site,
   `SLICE_X28Y296`**. It carried `EXTRA_XDC: none`, so it is neither this
   campaign's RTL nor the clock-root constraint; it is a post-route `phys_opt`
   leaving a vendor macro in a site programming bitgen rejects. It is a
   supplementary roll and nothing in the gate depends on it.

**The six unconstrained rolls span −0.139 … −0.859 and not one reaches zero**;
the five that used the full recipe span **0.512 ns** (−0.139 … −0.651) with
their top four inside **0.057 ns**. The one roll that reaches zero is the one
carrying the clock-root constraint.

### 9.1 Waiver decisions

**None taken and none proposed.** The gate is met on the design's own
`report_timing_summary` with no exception applied. `synth/scripts/final_verify.tcl` applies
`synth/constraints/fable5_xdma_rst_exception.xdc` — the one-line
`set_false_path` the user chose over a waiver for build_035
(`evidence/qwen2b/rc/TIMING_035.md` §13.1) — and `FV_WNS: 0.000` is identical
to the un-excepted design summary, i.e. **that constraint carries no load
here**. That file is **not in the implementation run at all**:
`synth/scripts/create_project.tcl` imports the four board XDCs plus
`synth/constraints/fable5_pcie_clk.xdc`, `synth/constraints/fable5_cdc.xdc` and
`synth/constraints/layer_mcp.xdc`, and only `synth/scripts/final_verify.tcl`
reads the exception file.

**The exception constraints that ARE in the project, both of them, enumerated
— because a section headed "Waiver decisions" that names one of two is worse
than one that names neither.** `synth/constraints/layer_mcp.xdc` (the
multicycle file) has been in the project since build_034;
`synth/constraints/fable5_cdc.xdc` carries **four `set_false_path`s** —
including one `-to [get_clocks -filter {NAME =~ mmcm_clkout0*}]` and one to
`*cdc_meta_*_reg*/D`. **Both are pre-existing and both are byte-unmodified by
this task** (`git diff --name-only c973c18..HEAD` names neither), so neither is
a waiver decision *of this gate* — but a reader auditing what exceptions the
0.000 was measured under is entitled to the complete list, and this is it.

### 9.2 The artifact

**`BITSTREAM:`**

```
synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper.bit
  53,074,589 bytes   2026-09-07 20:46:01 -0600
VERSION = c973c18a   (the netlist's commit sha, from launch_build.sh's
                      `=== create_project (c973c18a) ===`, baked into the
                      VERSION CSR by create_project.tcl)
```

Checkpoint: `…/impl_1/bd_wrapper_postroute_physopt.dcp`, 288,126,447 bytes,
2026-09-07 20:34:57 — the checkpoint `synth/scripts/final_verify.tcl` verified.

A **second, independent** bitstream of the same design exists at
`synth/out_g5d_po_ckr2/bd_wrapper.bit` (53,074,589 bytes, 2026-09-07 22:01:37),
written by the closure playbook only because both WNS and WHS were
non-negative. Its checkpoint `bd_wrapper_po_routed.dcp` (287,245,808 bytes,
2026-09-07 21:51:21) verifies identically (`154_…`, `FV_OK`).

**THE BOARD WAS NOT TOUCHED.** Nothing in this task programmed anything and
nothing wrote flash. Bring-up is Task 15.

---

## 10. VERDICT — **THE GATE PASSES**

**The criterion**, unchanged and unrelaxed: WNS ≥ 0.000 **and** WHS ≥ 0.000 on
**all** clocks, **zero** failing endpoints, **no waiver**.

**The measurement**, on `ckr2_AltSpreadLogic_high`:

| | required | measured |
|---|---|---|
| WNS, design | ≥ 0.000 | **0.000** |
| WNS, worst of the six clocks | ≥ 0.000 | **0.000** (`xdma_0_axi_aclk`); the other five +0.003 … +0.766 |
| WHS, design | ≥ 0.000 | **+0.001** |
| WHS, worst of the six clocks | ≥ 0.000 | **+0.001** |
| failing setup endpoints | 0 | **0** of 1,319,855 |
| failing hold endpoints | 0 | **0** of 1,316,719 |
| failing pulse-width endpoints | 0 | **0** of 392,523 |
| waivers | none | **none** |

**"All clocks" is carried by the endpoint counts, not by the six rows.** The
criterion is *all* clocks; the two "worst of the six clocks" rows above are the
six clocks this campaign tracks by name (the four MIG UI domains, `pipe_clk`
and `xdma_0_axi_aclk`), and the design has more clocks than that — the GT/QPLL
tree, the `pll_clk*` divisions, `dbg_hub`'s BSCAN. What settles the criterion
design-wide is the row beneath them, which is a count over **every** endpoint
in **every** clock and path group: **0 failing setup of 1,319,855, 0 failing
hold of 1,316,719, 0 failing pulse-width of 392,523**. A single negative slack
anywhere, on any clock or in any path group, would appear there as a failing
endpoint. This document's committed per-clock evidence
(`141_t14b_roll_ckr2_AltSpreadLogic_high.txt`) covers the six by name; the
zero-endpoint row is what covers the rest.

**PASS.** This is the second bitstream in this project's history that needs no
waiver, and the first for the 9B design.

**It passes on 0.000, which is thin, and that is stated rather than dressed
up.** build_035 shipped on the same figure. The margin on the four 300 MHz MIG
UI clocks is +0.003 … +0.031 and on hold +0.001, so this is a design with no
slack to give: **any change to the RTL, the constraints or the tool version
requires the whole gate to be re-measured, not assumed.** §11 says what that
means for Task 15.

### 10.1 What actually closed it, in order of size

1. **Task 14-A's RTL round: +0.091 ns** at matched directive and recipe
   (−0.247 → −0.156, §3.2), plus a 2.4× cut in failing endpoints. Measured,
   not inferred. Its own design note predicted it would move the *floor* and
   not the WNS — and that is exactly what the cone census shows (§4.4): the
   four logic-dominated cones left the failing set, and the largest logic
   content **on the 50 worst paths the instrument samples and on every cone's
   own worst path** fell from 2.600 ns to 1.700 ns (`T14A_MAX_PATHS: 50` of a
   2,507-path failing set — §4.4 states the scope). That sample is what made
   the remaining gap look like a **clocking** problem rather than a
   logic-depth one, and §8.2's measurement — skew +0.407 against a data path
   that moved 0.047 — is what confirmed it on the design's own worst path.
2. **The clock-root constraint: +0.156 ns** (§8.1), and it is the step that
   crosses zero. Its mechanism is +0.407 ns of clock skew on the worst path
   with the data path unchanged (§8.2).
3. **The directive family**, worth ~0.5 ns across the spread and, as Task
   14-A's stage E predicted, the choice that keeps `matvec_engine`'s 300 MHz
   `xline_q0` CE cone closed (§4.7).
4. **The floorplan: nothing, by design.** No pblock was used on any roll of
   this campaign. Task 14's controlled A/B priced pblocks at −0.879 ns and 14-B
   simply did not pay it; the placer put the whole layer in one SLR unaided on
   every roll (§4.2, §8.3).
5. **The `phys_opt` playbook: +0.000** on both the negative and the closing
   position (§6, §8.4). On this design it is a confirmation step, not a lever.

---

## 11. WHAT IS *NOT* ESTABLISHED BY THIS GATE

* **Nothing here is a board measurement.** No bitstream was programmed, no DMA
  was run, no CSR was read. The `VERSION` value `c973c18a` is what
  `synth/scripts/create_project.tcl` baked in, read from the build log — not read back from
  hardware. Task 15 is the first time any of this touches the BCU-1525.
* **What the board carries right now is NOT this design**, which is the first
  thing Task 15 needs and which "the board was not touched" does not say. The
  resident bitstream is **`build_035_fp2a_exc_po`** (`VERSION 54443b9f`, the
  2B W8 design, CALIB 0xF, its 2B weight pack loaded and audited) —
  `docs/HISTORY.md:686` and `docs/HISTORY.md:730`, unchanged by Task 14, 14-A
  or 14-B. Task 15's first act is therefore a **replacement**, under
  `CLAUDE.md`'s safe reprogram flow (`sudo -n sw/pcie_helper.sh remove` →
  `sw/program_fpga.sh` → `sudo -n sw/pcie_helper.sh rescan`), JTAG-volatile
  only, and it invalidates the resident 2B weight pack in DDR.
* **The margin is 0.000/+0.001 and it is directive- and tool-specific.** The
  closing roll is one placement. Multi-SLR placer non-determinism is a
  documented ±ns effect on this part (`CLAUDE.md`), and this campaign measured
  0.512 ns of spread across six unconstrained rolls of the same netlist. **A
  re-run of the same command is not guaranteed to reproduce 0.000.** What is
  reproducible is the *mechanism*: the clock root, the one-SLR partition and
  the directive family, all measured here and all recorded in
  `synth/constraints/fable5_clockroot_9b.xdc`'s header.
* **`USER_CLOCK_ROOT X2Y2` is tied to a placement that put `layer_0` in SLR0
  — and that dependency now has a MECHANICAL check, not a sentence.** Task 14's
  placer chose SLR2 and S5 reasoned SLR1; three campaigns, three dies. If a
  future roll's placer chooses a different one, X2Y2 pulls the clock root away
  from its own loads and the arm becomes a cost rather than a gain, **silently**,
  because a `set_property` that lands in the wrong place still succeeds.

  **How a future build detects the flip.** Run
  `evidence/qwen9b/g5/g5d_clockroot_check.tcl` on the candidate's routed
  checkpoint **before `synth/scripts/final_verify.tcl`**:

  ```
  vivado -mode batch -nojournal -source evidence/qwen9b/g5/g5d_clockroot_check.tcl \
    -tclargs <candidate routed.dcp> synth/constraints/fable5_clockroot_9b.xdc X2Y2 verify
  ```

  The script censuses `bd_i/layer_0`'s URAM288 cells by clock region, maps each
  region to its SLR with the device-measured `get_clock_regions -of_objects
  [get_slrs]` mapping `synth/scripts/slr_census.tcl` uses, and requires the SLR
  holding the **majority** of them to be the SLR of the clock root.
  **The marker is `CLOCKROOT_SLR_OK <slr>`; the criterion is `=== rc: 0`.** On
  a mismatch it prints `CLOCKROOT_SLR_MISMATCH layer=<slr> root=<slr>` and exits
  1 — **do not ship that roll**: recompute the centroid from
  `evidence/qwen9b/g5/g5d_clockskew_probe.tcl`'s `CSK_LOADS bd_i/layer_0`
  histogram on that placement and edit the coordinate, or drop the file. The
  same statement is now in the XDC's own header, so the file carries its
  dependency with it.

  **Both halves are exercised on real checkpoints**, on the clean committed
  tree `00fffbf`:

  | half | checkpoint | result |
  |---|---|---|
  | **GREEN** | the shipping roll's `bd_wrapper_postroute_physopt.dcp` — the one `final_verify` ran on | `CRC_LAYER_SLR: SLR0 (182 of 182 = 100.0%)`, root `X2Y2` → SLR0, `CLOCKROOT_SLR_OK SLR0`, rc **0** (`170_t14b_fix1_clockroot_slr_ckr2_GREEN.log`) |
  | **RED** | the FIRST campaign's `synth/out_g5b_po_eto/bd_wrapper_po_routed.dcp`, whose placer put the layer in **SLR2** | `CRC_LAYER_SLR: SLR2 (182 of 182 = 100.0%)`, `CLOCKROOT_SLR_MISMATCH layer=SLR2 root=SLR0`, rc **1** (`171_t14b_fix1_clockroot_slr_g5b_po_eto_RED.log`) |

  **The RED is constructed the way a future failure would arrive**: the
  *committed file itself* is applied to a checkpoint that carries no user clock
  root, the property **takes** (`CRC_RED_OK` → `CRC_GREEN_OK: USER_CLOCK_ROOT
  'X2Y2'`), and the check then fails on the **dependency** rather than on the
  property. No hand `set_property` and no hard-coded expected region was used,
  because either would have let the check fire for the wrong reason.
  `evidence/qwen9b/g5/g5d_clockskew_probe.tcl` remains the instrument that
  measures *where to move the coordinate to*; the check is what says you must.

  **One hole is left open in that guard, named here and DEFERRED.**
  `evidence/qwen9b/g5/g5d_clockroot_check.tcl:143-149` is `slr_of_cry`, which
  maps a clock-region Y to its SLR and returns `"?"` for a Y outside every
  measured range. Every other degenerate input in that script is fatal; this one
  is not. If the layer majority and the clock root BOTH resolved to `"?"` — a
  device, a hierarchy or a geometry probe the script has not seen — then the
  comparison at `evidence/qwen9b/g5/g5d_clockroot_check.tcl:223` is `"?"` against
  `"?"`, which is equal, so the script prints `CLOCKROOT_SLR_OK ?` and exits
  **0**: a vacuous pass wearing the marker of a real one. Fix round 2 is
  documentation-only and edits no script, and the guard's committed bytes are
  the bytes its GREEN and its RED ran on, so the closure — one guard on `best`
  and `root_slr` before the comparison, exiting non-zero when either is
  unresolved — is deferred to the next round that opens the file. **Until then
  the reading rule is that `CLOCKROOT_SLR_OK ?` is a FAILURE, not a pass**: the
  marker counts only with a real SLR name beside it, as in both rows above.
* **The functional claim is S4's, not this build's.** That the RTL decodes
  Task 11's tokens is `evidence/qwen9b/s4/S4_REPLAY.md` and, for the 14-A
  netlist, `evidence/qwen9b/g5/G5C_RTL.md` §6 (token-identical on four seeds).
  **This gate establishes that the design closes timing, not that it computes
  the right thing on hardware.**
* **The 5.133 ms/token DMA-lane figure is MODELLED** (S4, LAT 8) and nothing in
  this document turns it into a board number.
* **Roll #7's bitgen DRC failure is recorded, not diagnosed.** It was a
  supplementary roll; no one has established whether the same
  `ExtraPostPlacementOpt` + post-route-`phys_opt` combination would fail again,
  or whether the vendor SmartConnect macro at `SLICE_X28Y296` is implicated
  generally. Nothing in the shipped artifact depends on it.
* **Task 14-A's design-note §7.2 list is now stale and should not be used to
  scope future work.** Two of its four route-dominated families
  (`seq_0`'s next-PC enable, the state DMA's LUTRAM write cone) are closed with
  +0.397 and +0.004 of margin. If a future round needs slack, the measured
  candidate is different: `139_t14b_owner_probe_ash.log` shows the residual
  owner is a two-level **URAM → DSP** read (`ATTN_DSP`) carrying 1.65-1.70 ns
  of *cell* delay, and that **all 182 cache URAM288 cells have `OREG_A` and
  `OREG_B` = `FALSE`** — the output register that would split that path is
  unused, on every slot (DN 58, KV 116, CV 8). The DSP side has room too
  (`BREG = 0` on 350 of the 529 attention DSPs). That is a +1-cycle RTL change
  on the cache read, and it is the lever if margin is ever needed — it is
  **not** needed for this gate.

---

## 12. CITATIONS

### 12.1 Drift

Task 14-B changed **one file outside `evidence/qwen9b/g5/`**:
`synth/constraints/fable5_clockroot_9b.xdc`, which is **new**. Creating a file
cannot move a line another document cites, so the mechanical check is expected
to be empty, and it is run rather than assumed:
`evidence/qwen9b/g5/159_t14b_cite_drift_plan.log` runs
`evidence/qwen9b/o3/o3_cite_drift.py --base c973c18 --doc-base c973c18 --edited
synth/constraints/fable5_clockroot_9b.xdc --plan` and reports
`TOTAL REPAIR 0 COLLATERAL 0`, `O3_FIX_PLAN: SAFE`. Nothing was rewritten.

**Fix round 1 re-ran the same gate over its own edits** — this document plus
the two files it touched, `synth/constraints/fable5_clockroot_9b.xdc` (comment
lines only) and `evidence/qwen9b/g5/g5d_clockroot_check.tcl` — with
`--base 5c4c829`: `evidence/qwen9b/g5/175_t14b_fix1_cite_drift_plan.log` and
`evidence/qwen9b/g5/176_t14b_fix1_cite_drift_verify.log`. **The XDC's added
comment block sits at the END of its header, immediately before the one
`set_property` line**, precisely so that every line number anything already
cites keeps its value — including the XDC line numbers 87, 92 and 96 that
`132_t14b_clockroot_xdc_RED.txt` quotes out of the burnt roll's parser errors,
each of which still names the same line of the file today.

**That gate ran on tree `786919b`, and `127651a` then edited this document
again** — so by the rule §12.2 applies to the superlative pair and §12.3 to
`spec_cites`, its verdict belongs to an earlier text. **It needs no re-run, and
the reason is mechanical rather than a judgement.** The three citations it
tracks are lines 87, 92 and 96 of `synth/constraints/fable5_clockroot_9b.xdc`,
quoted at `evidence/qwen9b/g5/132_t14b_clockroot_xdc_RED.txt:13-15`; all three
sit inside the file's frozen prefix, and lines 1–101 of that file are
byte-identical to `5c4c829`'s (§1). No number that gate checked can have moved,
in `127651a` or since. Fix round 2 ran its own drift gate over its own edited
set and on its own text — §12.6.

Every other file this task wrote is under `evidence/qwen9b/g5/` and is new.
**No file committed by Task 13, Task 14 or Task 14-A under `g5/` was
modified.** No script under `synth/scripts/` was changed: 14-B's commit block
allows it only if a script must change to run, and none did — the two harness
repairs Task 14 made to `synth/scripts/create_project.tcl` and `synth/scripts/final_verify.tcl` were
already in the tree and both did their job here (§2.1, §8.3).

### 12.2 The superlative checker, and its negative control

`evidence/qwen9b/g5/g5d_superlatives.py` is this task's copy of
`evidence/qwen9b/s5/s5_superlatives.py`, re-pointed at 14-B's rolls: it
discovers them from the committed `<nnn>_t14b_roll_<label>.txt` files, parses
each roll's Design Timing Summary row by shape, reads the six family slacks out
of the committed `<nnn>_t14b_fam_<label>.log` files, ranks every column across
all rolls, and then checks each ranking claim in this document against the
ranking. Its header states the four differences from S5's copy and nothing
else changed.

* `evidence/qwen9b/g5/167_t14b_superlatives.log` — the checker on this
  document as committed **at `28a95e4`, before fix round 1**: **`G5DSUP:
  PASS`**. The pair was re-run on the fixed text —
  `evidence/qwen9b/g5/180_t14b_fix1_superlatives.log` and
  `evidence/qwen9b/g5/181_t14b_fix1_superlatives_control.log` — because a
  checker's verdict belongs to the text it ran on, and this document changed
  after `28a95e4` (§12.5). `evidence/qwen9b/g5/177_t14b_fix1_superlatives.log`
  and `evidence/qwen9b/g5/178_t14b_fix1_superlatives_control.log` are the same
  pair on an earlier draft of the fix round's text, kept rather than re-run in
  place for the reason 160–165 are kept.
* `evidence/qwen9b/g5/168_t14b_superlatives_control.log` — the same checker
  with `--negative-control`, which plants a ranking claim that is false by
  construction and requires the checker to reject it:
  **`G5DSUP_CONTROL: CAUGHT — the checker is live`**. A checker that cannot
  fail proves nothing; this one fails when it should.
* Numbers **160/161**, **162/163** and **164/165** are the same pair run on
  three earlier drafts — twice while §12.1's citation gate was still being
  satisfied (it made this document spell nine bare script names as full
  repository paths) and once before §12.4's correction. Every pair returns the
  same verdict. The last pair is the one that ran on the committed text; the
  earlier ones are kept rather than re-run in place, because re-running a
  committed evidence log in place is the one thing `evidence/qwen9b/run.sh`
  exists to refuse.

**The `G5DSUP_UNCHECKED` list in `167_…` was read line by line.** Every entry
in it is prose that carries a marker word without making a cross-roll ranking
claim — "the worst path", "the one difference", "the largest device
utilization", and so on — and each of those numbers is quoted from a named
report in the section it appears in. The checker reports
`G5DSUP_SCOPED_TOTAL: 2`, and both are named here rather than one: the first is
the genuine ranking over a subset the checker cannot see
(`po4_ExtraNetDelay_high` against the rolls carrying no XDC, §9's note 1), and
the second is **this section's own sentence about the first**, which the
checker matches because it repeats the marker. Each carries the
`superlative-check: scoped` marker and the checker prints the full ranking
beside it, which is where a reader can check it in one place.

### 12.3 `spec_cites`

`evidence/qwen_next/spec_cites.py` needed **no edit**. Its `PENDING` set names
only `evidence/qwen9b/g6/RD9_GATE.md` (Task 15); neither
`evidence/qwen9b/g5/G5D_TIMING.md` nor
`synth/constraints/fable5_clockroot_9b.xdc` was ever listed there, so there was
nothing to prune and nothing was added — the S5 lesson (a stale `PENDING`
entry silences `EXIST` on a live path) applies by leaving the set alone.

`spec_cites` runs **LAST**, alone, on the committed tree: its commit contains
only its log, that log's `=== tree:` names the commit immediately preceding it,
and this document does not cite that log.

### 12.4 A correction this document's own self-review found, and where it was wrong

**§4.1's per-clock table was transcribed wrongly the first time it was
committed** (`9086a7b`), and the error was found by re-reading every table
against its source file before the task closed. Five of its six rows carried
numbers that are not in
`evidence/qwen9b/g5/126_t14b_roll_po2_AltSpreadLogic_high.txt`:

| clock | committed in `9086a7b` | **the file says** |
|---|---|---|
| `mmcm_clkout0` | 0.000, 173,181 EP, WHS +0.010 | **+0.003, 173,160, +0.011** |
| `mmcm_clkout0_2` | +0.006, 173,190 | **+0.008, 173,251** |
| `mmcm_clkout0_3` | +0.007, 173,163, +0.010 | **+0.025, 173,183, +0.011** |
| `mmcm_clkout0_1` | +0.031, 173,166 | **+0.013, 173,187** |
| `pipe_clk` | +1.021, WHS +0.013 | **+0.268, +0.011** |
| `xdma_0_axi_aclk` | −0.156, −126.221, 2,507 EP, 577,313 total | **same, except 576,324 total** |

**Nothing that the gate turns on was affected.** Every WNS in that row set was
positive before and after, every failing-endpoint count in it was and is
**zero**, and the row that carries the deficit — `xdma_0_axi_aclk`, −0.156 with
2,507 failing endpoints — was right. The corrected values are the ones now in
§4.1, and the prose beneath it, which quoted two of them, is corrected with
them.

**How it happened, so the next reader can distrust the right thing.** That
table describes `po2_AltSpreadLogic_high` — the roll the campaign *did not*
ship — and it was written from memory of the shape of the closing roll's table
rather than read back out of file 126. The tables that the verdict rests on
(§3.1, §8.3, §9) were each re-verified line by line against
`112_t14b_roll_build_041.txt` and
`141_t14b_roll_ckr2_AltSpreadLogic_high.txt` in the same pass and are correct
as committed. **This is recorded rather than quietly fixed** because a gate
document that silently repairs its own numbers is worth less than one that
says which number was wrong and for how long.

---

### 12.5 FIX ROUND 1 — what review round 1 found, and what changed

Review round 1 (`0 Critical, 6 Important, 10 Minor`, verdict *"the gate itself
is sound and I could not break it"*, bring-up judgement **yes**) found no
measurement defect. **No number in this document's verdict moved, no
constraint's effect changed, and the bitstream, the netlist and the checkpoint
are byte-identical to the ones §9.2 names.** What changed is what the document
discloses and what the result's dependency is guarded by.

| finding | what it was | what it is now |
|---|---|---|
| **I-1** | §8 said the XDC *"parsed with no CRITICAL WARNING"*; the run's one critical warning, `[Place 30-890]`, was undisclosed | §8.5 quotes it verbatim and answers it three ways (file 173) |
| **I-2** | the SLR0 dependency had no mechanical detection — the guard asserted only that the property took | `g5d_clockroot_check.tcl` now asserts layer-SLR == root-SLR; GREEN and RED both run (files 170, 171); the XDC header states the dependency; §11 gives the command and the criterion |
| **I-3** | `synth/scripts/floorplan_check.tcl`, named by the plan's Step 3, was never run and the substitution was undeclared | run read-only on the shipping checkpoint (file 172), declared in §4.2, cross-referenced in §8.3 |
| **I-4** | §7 priced roll #2, not the roll that ships | §7 carries both columns, labelled, from file 153 and file 135 |
| **I-5** | §1 claimed the XDC was committed before every run that used it; the timestamps say otherwise | §1 states which runs used it untracked, that the bytes are unproven-identical (this round's own comment-only edit destroyed the last mtime evidence, which is recorded there), and what does tie the file to the design |
| **I-6** | "the largest logic content anywhere in this failing set is 1.700 ns" was a max over a 50-path sample of 2,507 | scoped in §4.4 and §10.1, with the instrument's own cap quoted |
| **m1** | "every family positive" against `ATTN_DSP 0.000` | "non-negative", §8.3 |
| **m2** | §8.2's before/after read as one path measured twice | the two endpoints tabulated, §8.2 |
| **m3** | §2.2's 1,840 and §4.2's 1,845 unreconciled | reconciled from the hierarchical utilization, §4.2 and file 174 |
| **m4** | §9.1 named one of the project's two exception constraints | both enumerated, §9.1 |
| **m5** | §3.1's fenced block was an uncited composite of two files | both files named above it, §3.1 |
| **m6** | §10 framed the criterion as "the six clocks" | the zero-endpoint row named as what carries "all clocks", §10 |
| **m7** | §12.2 said "the one" scoped claim; the checker reports two | both named, §12.2 |
| **m8** | an uncited causal claim about the `Explore` outlier | withdrawn, §3.2 |
| **m9** | §8 quoted `TAG=`/`XDC=` that log 134's `=== cmd:` does not record | §8 says which artifact recovers each |
| **m10** | "the `BUFG_GT` … cannot move" — it moved; and §11 never said what the board carries | §8.2 gives both buffer sites and what actually cannot move; §11 names `build_035_fp2a_exc_po` |

**The fix round's own runs**, all through `evidence/qwen9b/run.sh`, all
`=== host: snoke`, all read-only on **existing** routed checkpoints — no
implementation, no bitstream, no write into any `synth/out_*`, no board:

| # | log | tree | rc | what |
|---|---|---|---|---|
| 170 | `170_t14b_fix1_clockroot_slr_ckr2_GREEN.log` | `00fffbf` | **0** | the widened guard, `verify`, on the shipping checkpoint — `CLOCKROOT_SLR_OK SLR0` |
| 171 | `171_t14b_fix1_clockroot_slr_g5b_po_eto_RED.log` | `00fffbf` | **1** | the widened guard, `dry`, on the first campaign's SLR2 roll — `CLOCKROOT_SLR_MISMATCH layer=SLR2 root=SLR0` |
| 172 | `172_t14b_fix1_floorplan_check_ckr2.log` | `00fffbf` | **1** | `synth/scripts/floorplan_check.tcl` on the shipping roll — `FPCHECK_PBLOCK_COUNT: 0`, then its own no-pblock exit |
| 175 | `175_t14b_fix1_cite_drift_plan.log` | `786919b` | 0 | citation drift over the fix round's edits, `--plan` |
| 176 | `176_t14b_fix1_cite_drift_verify.log` | `786919b` | 0 | the same, `--verify` |
| 177 | `177_t14b_fix1_superlatives.log` | `786919b` | 0 | the superlative checker, on an earlier draft of the fixed text |
| 178 | `178_t14b_fix1_superlatives_control.log` | `786919b` | 0 | its negative control, same draft |
| 180 | `180_t14b_fix1_superlatives.log` | `127651a` | 0 | the superlative checker on the text as committed |
| 181 | `181_t14b_fix1_superlatives_control.log` | `127651a` | 0 | its negative control |

`spec_cites` runs **LAST and alone** for this fix round exactly as it did for
the gate (§12.3): in a commit that holds only its log, on the tree of the
commit immediately preceding it, and **this document does not cite that log** —
which is why the table above stops at 181.

**Numbers 173 and 174 are extracts, not logs**: `173_t14b_fix1_place30890_ckr2.txt`
(the critical warning and the three measurements that answer it) and
`174_t14b_fix1_dsp_owner_reconcile.txt` (DSP ownership), both copied out of the
shipping roll's own gitignored reports with their source paths and mtimes in
their headers.

**Fix round 1's own report miscounted them, and the correction lives here
because that report is not tracked.** Its self-review
(`.superpowers/sdd/2026-09-04-qwen35-9b-state-spill/task-14B-fix1-report.md`)
says all *"thirteen new logs"* carry `=== host: snoke`, `=== rc:` and
`=== end:`. Thirteen files are new; **eleven** of them are logs and carry all
three — 170, 171, 172, 175, 176, 177, 178, 179, 180, 181, 182 — and the two
extracts named just above carry none, exactly as the paragraph above says.
Count, not substance.

**Two of the three Vivado runs exit non-zero and both are correct.** 171 is a
negative control — a guard that cannot fail proves nothing, and this one fails
on a real checkpoint whose placer made the choice the guard exists to catch.
172 is `synth/scripts/floorplan_check.tcl` refusing a design with no pblocks,
which is what
that script is for and which is the affirmative answer on a roll that carries
none by design (§4.2).

---

### 12.6 FIX ROUND 2 — the sentence fix round 1 falsified, and the rest of the re-review

Re-review round 1 (`0 Critical, 1 Important, 7 Minor`, bring-up judgement
**unchanged: yes, a Task 15 candidate**) re-derived the load-bearing numbers
from the primary files and confirmed all six of fix round 1's Importants and all
ten of its minors. **No measurement moved in this round either.** It is
documentation-only: this document and the citation logs beneath it are the only
files it writes, and the bitstream, the routed checkpoint, the netlist,
`synth/constraints/fable5_clockroot_9b.xdc` and
`evidence/qwen9b/g5/g5d_clockroot_check.tcl` are byte-untouched by it.

| finding | what it was | what it is now |
|---|---|---|
| **I-1** | §1 offered the XDC's mtime **15:56:19** as *"earlier than both runs"* — but fix round 1's own `00fffbf` had rewritten it to **22:52:32**, later than both, inverting the corroboration; and §1's first bullet still said no constraint and no script was modified after `51f49d2`, which that same commit falsified | §1 says which edit destroyed the mtime and when, scopes the "nothing was modified" claim to the build, and replaces the mtime with the byte comparison — 0 non-comment additions, 0 deletions, lines 1–101 identical to `5c4c829` |
| **m1** | fix round 1's report gave the wrong reason for citing `NEXT_SESSION.md` — it said `.superpowers/sdd/2026-09-04-qwen35-9b-state-spill/task-14-report.md` does not exist, and it does | nothing in this document changes: §11's citation was always into the tracked file, and the re-review verified both lines name the resident build |
| **m2** | the drift gate ran at `786919b`; `127651a` then edited this document again | §12.1 says why that gate needs no re-run — its three citations are in the XDC's frozen prefix — and this round ran its own |
| **m3** | §4.2 never said **which** XDC `synth/scripts/floorplan_check.tcl` was handed | §4.2 names it from the log's own `=== cmd:` line, and says what `FPCHECK_PBLOCK_COUNT: 0` does and does not mean |
| **m4** | §4.2's *"the split is forced"* leaned a slice-only histogram into a DSP attribution | §4.2 states what that instrument counts and calls the step arithmetic with no other candidate |
| **m5** | `slr_of_cry`'s `"?"` return is a vacuous-pass path left in the widened guard | §11 names it, gives its shape, and **defers** the closure — this round edits no script |
| **m6** | fix round 1's report counted *"thirteen new logs"* | eleven are logs; 173 and 174 are extracts — §12.5 |
| **m7** | §12.5's run table printed `—` in the tree column for 175–181 | filled in from each log's own `=== tree:` line, which is what makes 177/178 an earlier draft and 180/181 the committed text |

**A commit message and a report that describe an edit the commit does not
contain.** `127651a`'s message says §1 now records that this round's own edit
destroyed the mtime evidence. It does not: that commit is +12/−7 on this
document and its three hunks land in §12.2 and §12.5 only, and §1 kept printing
the dead number. The fix-round report and the campaign ledger repeat the claim,
so the correction was described in three places and made in none, while
§12.5's I-5 row pointed at a §1 sentence that was never written. The
re-review caught it by reading the diff instead of the message. It is recorded
here for the reason §12.4 records the wrong per-clock table: **a document whose
commit messages outrun its diffs is worth less than one that says where that
happened.**

**Two stale citations, repaired mechanically.** §11's two pointers at the
resident bitstream named lines 206 and 239 of `NEXT_SESSION.md` when fix round 1
wrote them, and both were right then. A later documentation chore inserted 75
lines at the top of that file and **left this document's two pointers stale on
purpose**, because `evidence/qwen9b/g5/` was off-limits to it while the
re-review was reading the range. (Those two numbers are written out here rather
than as citations, so that the repair pass renumbers §11's pointers and leaves
this sentence's history alone.) They are repaired here with
`evidence/qwen9b/o3/o3_cite_drift.py` at `--base 9a84a52`, not by hand, and the
pass is scoped to this document: the same chore already repaired the other
citers at that base, so an unscoped `--fix` would move those a second time.
That is the tool's own COLLATERAL class, and the plan is asked before the fix
rather than assumed.

**Fix round 2's runs**, all through `evidence/qwen9b/run.sh` on snoke, all
read-only except the citation repair itself, none of them opening a checkpoint,
writing into any `synth/out_*`, or touching the board:

| # | log | tree | rc | what |
|---|---|---|---|---|
| 183 | `183_t14b_fix2_superlatives.log` | `4a4082a` | **0** | the superlative checker on this round's text — `G5DSUP: PASS` |
| 184 | `184_t14b_fix2_superlatives_control.log` | `4a4082a` | **0** | its negative control — `G5DSUP_CONTROL: CAUGHT` |
| 185 | `185_t14b_fix2_cite_drift_plan.log` | `4a4082a` | **1** | the drift plan, UNSCOPED — `TOTAL REPAIR 2 COLLATERAL 16`, `O3_FIX_PLAN: UNSAFE` |
| 186 | `186_t14b_fix2_cite_drift_plan_scoped.log` | `4a4082a` | **0** | the same plan with the three already-repaired citers excluded — `TOTAL REPAIR 2 COLLATERAL 0`, `O3_FIX_PLAN: SAFE` |
| 187 | `187_t14b_fix2_cite_drift_fix.log` | `4a4082a` | **0** | the fix, scoped to this document — `FIXED 2 citation(s) in 1 document(s)` |
| 188 | `188_t14b_fix2_cite_drift_verify.log` | `4a4082a+dirty` | **0** | the verify — `relocated 2`, `O3_CITE_DRIFT VERIFY PASS (0 problem(s))` |

**185 exits 1 and that is the instrument working.** Asked without a scope, the
plan says a `--fix` at this base would move 16 citations that are already
correct — the documentation chore repaired them at the same base — and refuses
to call itself safe. 186 is the same question with those three documents
excluded, and 187 fixes only this document: two numbers, in §11, both of which
`--verify` had been reporting as stale. 188's tree carries `+dirty` because the
repair it checks was not committed yet; that is the shape the chore's own verify
carries for the same reason.

**The superlative pair was re-run rather than carried over**, which is §12.2's
rule applied to this round's own text. In 183, `G5DSUP_SCOPED_TOTAL` is still
**2** — the two sentences §12.2 names — and `G5DSUP_UNCHECKED` goes 65 → 71
against 180's list: §4.2's old *forced* sentence is gone and seven are new. Each of the seven was read.
They carry a marker word about this round's scope, about a byte comparison or
about a reading rule; none of them ranks one roll against another, which is the
only claim class this checker adjudicates.

**What this commit adds on top of the text those two gates ran on** is the two
citation numbers the drift fix itself wrote, and this table. No claim, no
measurement and no ranking is among them.
