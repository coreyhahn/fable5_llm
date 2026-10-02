# SR — the sequencer RTL round (R1 fence mask, R2 XWIN/RES banks, R3 from silicon) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision 2 (2026-09-27, fix round 1):** the plan review's nine Important and ten minor findings and the controller's rulings are folded in. The ones that change behaviour: admission is keyed by the **device's** capability set read from SEQ_CAPS, not by the manifest's claim (I3/I8); the SEQ_CAPS constants have one definition, in `sw/hwmap.py` (I9); **the UI cut is not an R1 option** — the user's Q3 answer is "to close R2" (I1); an R1 retiming rung precedes the clock contingency (I2); SR14's order is written in full (I4); an identity failure on the board is a no-DMA restore-and-stop (I6); every chip-TB stream is judged (I5); SR5, SR11 and SR13 are split.

**Goal:** Put R1 (the FENCE channel mask) on silicon as its own signed-off bitstream, then R2 (XWIN/RES bank bits) as a second, separately-judged bitstream, with tokens identical to the shipped reference at every rung, and decide R3 from the two bitstreams' silicon counters — the user's option 2.

**Architecture:** Every RTL change is in `seq_0` (R1: decode + the mover's F_SCAN, aclk only) or crosses into the four `mvchan` blocks (R2: two quasi-static SHAPE flops and two reset values in `matvec_engine`, MIG UI clocks). Each tier goes gate-first (ISA text → reference model and validator → pass, TDD), then RTL (unit TB RED → GREEN), then the chip TB (backward compatibility cycle-identical, the new streams token-identical against a prediction committed first), then one build that starts from the incremental flow step 0 proves out, then one board session under one lock hold. A read-only `SEQ_CAPS` word at SEQ `0x64` plus a new `SEQ_VERSIONS` row make an R-stream fail closed on any bitstream that lacks the feature: the host validates every stream against the capability set **the device reports**.

**Tech Stack:** SystemVerilog (Verilator 5.020 `-Wall --timing`), Python (`ref/` models, `sw/` host tools; uv venvs), Vivado 2024.2 on snoke, BCU-1525 on snoke via the CHARTER safe JTAG flow; the campaign wrapper `evidence/qwen9b/sr/sr_run.sh` (committed by SR1 at `45deebf`, a copy of `evidence/qwen9b/ov/ov_run.sh`).

**Spec:** `docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md` (reviewed clean at `11e8947`; "the spec" below). **The spec wins on any conflict with this plan.** The user's answers to the spec's §7 are in the campaign ledger `.superpowers/sdd/2026-09-27-seq-rtl/progress.md`, entry "USER ANSWERS (2026-09-27)" (gitignored — cited by path and date, never by line). House models for form: `docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md` and `docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md`.

**The user's answers, as this plan binds them:**

| Q | answer (ledger, 2026-09-27) | where it binds |
|---|---|---|
| Q1 | YES — a new MMCM compute-clock domain MAY be added **if a build cannot close at 250 MHz**; conditional fallback, never a first move | Task SR7C only: for R1 after SR7's ladder is exhausted with the user informed first; for R2 only by an explicit user ruling (SR14) |
| Q2 | moot under Q1's condition; if SR7C is ever taken the default applies: accept an aclk cut up to 5 %, ask beyond (spec §7 Q2) | SR7C |
| Q3 | a UI (DDR4) clock cut of up to ~5 % is acceptable **to close R2** if the MIG accepts the period and the DIMMs calibrate; never a full grade | SR10 (establishes it), SR14 step 5 (uses it). **Not an R1 option** |
| Q4 | option 2: R1 as one build; R2 as its own build, kept only after a spread / incremental reuse; R3 from silicon | the task order; SR14's drop rule |
| Q5 | step 0 first (SR1, in flight concurrently) | Task SR1 (= Task 0) |
| Q6 | R3 form (a), direct x-push bus, if taken | SR16 |
| Q7 | keep the BM1 counters | every netlist |
| Q8 | no RTL interlock — the hazard stays emitter-enforced | SR4, SR11a |
| Q9 | each round bitstream needs its own waiver ruling | SR7, SR8, SR14, SR15 |

**Review minor N1 (the SR0 re-review, ledger 2026-09-27), folded here as the plan's first doc touch:** the spec's Q3 text says "~5–7 %"; §3.2, §5 and D7 say ~5 %. The **5 % point is the model-backed one** (R1+R2 8.906 above R1-at-full 8.811 at a 5 % UI cut; 8.656 below it at 10 %; spec §3.2, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:72-73`); 7 % is a linear interpolation between grid points, not a grid result. This plan uses **≤ 5 %** wherever it names the UI-cut bound, matching the user's Q3 answer.

---

## Global Constraints

Every one binds every task.

- **NEVER read/grep/copy the pre-existing private implementation (the "answer key")**, its git history, or auto-memory entries about it.
- **One board, 9B only.** No 0.8B/2B work; every quality or speed statement is at the 9B operating point `FABLE5_MODEL=9b FABLE5_RS_F=7` (`ref/model_select.py` refuses a disagreeing `FABLE5_RS_F`); a reference or emitter run without `FABLE5_MODEL` set is invalid (read a wrapper's header before trusting a run).
- **Every numeric run on snoke, through the wrapper:** `ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm && bash evidence/qwen9b/sr/sr_run.sh <log-name> <cmd> [args...]'`. darthplagueis does no numeric work of any kind (no Python arithmetic, no sim, no Vivado). The wrapper refuses to overwrite a log; never re-run a committed evidence script in place when a gate doc cites its log by line.
- **Log numbering — disjoint blocks per task** (the SR0 round's `n132` collision with S1D is why). SR1 owns `n001–n099`. Task SR*k* owns `n{k}00–n{k}99` (SR2 → `n200…`, SR10 → `n1000…`, SR17 → `n1700…`), with these exceptions: split tasks halve their block (SR5a `n500–n549`, SR5b `n550–n599`; SR11a `n1100–n1149`, SR11b `n1150–n1199`; SR13a `n1300–n1349`, SR13b `n1350–n1399`); **SR7C owns `n1800–n1899`**; **SR-ISABITS owns `n1900–n1999`** (a free block, so SR10 keeps its whole `n1000–n1099`); SR9 owns `n900–n989`, and **`n990–n999` are reserved for this plan's own fix rounds** (fix round 1's spec_cites logs are `n990–n992`: FAIL 144 → FAIL 1 → PASS; fix round 2's start at `n993`). A fix round continues its task's block.
- **Vivado on snoke only**, detached for long runs (`nohup … &`), bounded polling (tail every ~20 min). `source /home/cah/r2d2/sc2data/tools/Vivado/2024.2/settings64.sh`. Other projects' Vivado jobs may share snoke — never touch them. **Every build writes its own new `synth/out_<build>/` directory; never reuse, open-for-write or overwrite an existing one** (the launchers refuse: `synth/scripts/launch_build.sh:14-17`, `synth/scripts/launch_po2.sh:13-15`). Read fresh reports only — check timestamps.  <!--cites:noquote-->
- **Heavy Verilator sims on snoke**, seeds in parallel as separate processes; **4 seeds minimum** on every TB run; one `obj_dir_<name>` per binary; never build or run one obj_dir from two hosts at once. TB discipline: drive/sample at negedge; failures `$fatal(1, …)`.
- **Board safety:** JTAG-volatile bitstreams only, never flash. The safe reprogram is `sw/program_fpga.sh <bit>`, which runs `remove → JTAG → rescan` **under one hold of the shared board lock** (`docs/USAGE.md` §2; `NEXT_SESSION.md` §4); `sudo -n /home/cah/r2d2/code/fpga/fable5_llm/sw/pcie_helper.sh load` only if the driver is absent. **Never DMA before `CALIB == 0xF`.** Every new bitstream is admitted only when NAMED: its VERSION row in `sw/seq_run.py`'s `SEQ_VERSIONS` (`sw/seq_run.py:164-189`), and every SEQ-driving tool of a session passes `--expect-version <hash>` / `FABLE5_SEQ_EXPECT_VERSION=<hash>` (`NEXT_SESSION.md` §3, "The admission rule"). **An identity failure — VERSION not the expected one, CALIB not `0xF`, SEQ_CAPS not the expected word — means NO DMA: reprogram build_041 under the safe flow, read its identity, record, STOP.** **The restore target at the end of every session is build_041, always.** No board action happens without the controller's go.  <!--cites:noquote-->
- **The standing RTL ladder** (`NEXT_SESSION.md` §9; spec §4.1) for every netlist: lint → unit TBs ×4 seeds → the layer census bit-exact → the S4 replay token-identical, no re-emission → OOC counts (`OOC9B_URAM: 182`, RAMB36 79 / RAMB18 8 = 83.0 tiles, DSP 1840 — the post-T14A counts, `evidence/qwen9b/g5/G5C_RTL.md:773-777`; S5's `OOC9B_BRAM: RAMB36=77 RAMB18=8 tiles=81.0` / `OOC9B_DSP: 1838`, `evidence/qwen9b/s5/S5_STRUCT.md:519-521`, are pre-T14A — corrected by SR9 under the ledger's SR3 ruling) → a full build with `evidence/qwen9b/g5/g5d_clockroot_check.tcl` on the routed checkpoint **before** `synth/scripts/final_verify.tcl` → the safe reprogram → the RD9 board ladder (`evidence/qwen9b/g6/RD9_GATE.md`). **The bar is G5D §10's, unrelaxed:** WNS ≥ 0.000 and WHS ≥ 0.000 on all clocks, zero failing setup/hold/pulse-width endpoints, no waiver (`evidence/qwen9b/g5/G5D_TIMING.md:1255-1269`). **Per-clock reporting names the six tracked clocks by their Vivado names:** `xdma_0_axi_aclk`, `pipe_clk`, and the four MIG UI clocks `mmcm_clkout0` (ch0), `mmcm_clkout0_2` (ch1), `mmcm_clkout0_3` (ch2), `mmcm_clkout0_1` (ch3) (`evidence/qwen9b/g5/G5D_TIMING.md:1010-1015`); "all clocks" is carried by the design-wide failing-endpoint counts (G5D §10).
- **Keep the BM1 counters** (Q7; `docs/SEQ_ISA.md` §B16). A masked FENCE stays `mv_op 3`, so counter C5 needs no change (spec §1.1).
- **No RTL interlock** (Q8): the pending-channel hazard is refused by the model gate (`RunningChannelError`, `ref/seq_model.py:455`) and the pass's assert (`ref/scripts/reorder_e4.py:225`), and both must stay armed under every new semantic.
- **No new clock, no new CDC** except by Task SR7C under Q1's condition (the FPGA-level CLAUDE.md single-clock rule; the user's Q1 answer is the explicit OK, and it is conditional).
- **SEQ_CAPS has ONE definition:** the constants (offset `0x64`, magic, one bit per feature, and the word → capability-set decoder) live in `sw/hwmap.py`; `ref/seq_format.py` already imports `hwmap` (`ref/seq_format.py:133`) and uses them; `docs/SEQ_ISA.md` B17.0 states the same values and SR2's test ties the doc to the constant; the RTL's literal is checked against the hwmap constant by the unit TB (SR3, SR12). Nothing else re-types the value.
- **Admission is keyed by the device's capabilities, not the manifest.** Every host path that validates a stream for a board validates it with `caps = the set decoded from the device's SEQ_CAPS` (empty on every pre-round bitstream); a stream that uses a feature the device lacks fails validation before any DMA of the stream, whatever its manifest says.
- **Measured, not modelled.** Every tok/s in this plan is MODEL (spec §0) unless it names a board log. Labels: **S** stated by a cited source, **E** printed by a committed run, **D** derived with the arithmetic shown in a committed script run on snoke, **T** transcribed from an earlier gate. A number a gate doc quotes cites a committed log line or gate doc.
- **Commit at every green gate, path-limited:** `git add <new files>` then `git commit -m "…" -- <paths>`; the pathspec names FILES, except a task's own evidence files under `evidence/qwen9b/sr/` (named by glob of its own log block and its gate doc — never the whole `evidence/qwen9b/sr/` directory, which SR1 and other tasks also write). Before committing any file another task also names (`ref/seq_format.py`, `ref/seq_model.py`, `ref/scripts/reorder_e4.py`, `sw/hwmap.py`, `sw/seq_run.py`, `sw/chat_seq.py`, `tb/scripts/gen_seq_unit_vectors.py`, `tb/tb_seq_unit.sv`, `docs/SEQ_ISA.md`, `NEXT_SESSION.md`), run `git diff --stat <file>` and never commit another task's work. Never `--amend`. Every commit message ends with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. **Never push** (the push is the user's action, `NEXT_SESSION.md` §8 item 4).
- **Doc gates:** `evidence/qwen_next/spec_cites.py` runs LAST, alone, on the committed tree, over every gate doc, spec, plan and `NEXT_SESSION.md` a task edits — FAIL 0; `evidence/qwen9b/o3/o3_cite_drift.py --plan` before any `--fix`, `--exclude` your own gate doc, `--verify` after. Sweep with `/usr/bin/grep` (the shell's `grep` is `ugrep` and honours `.gitignore`). **This plan's own citation convention:** a file no task has created yet is written WITHOUT backticks (spec_cites checks only backticked paths, so a future name cannot false-fail EXIST, and a task that creates it may backtick it from then on); a line that shows code or a command a task will WRITE carries `<!--cites:noquote-->` so its prospective spans are not checked as quotations of today's files (the state-spill plan's convention). Backticked directories and globs (`synth/out_<build>/`, `evidence/qwen9b/sr/n4*.log`) may name future paths too: spec_cites checks only backticked FILE paths with a citable extension, and only ones that exist.
- **Boardfree selftests unmoved** except upward by added selftests; the triple a task quotes is the one its own committed log prints on a clean tree (run through `evidence/qwen2b/rd/rd_boardfree.sh`).

### Standing hazards this plan inherits

- **R2 is NOT fail-closed on an old bitstream** (spec §1.2 "Forward — NOT fail-closed"): build_041/042 ignore MOVX target (`rtl/seq_unit.sv:1082-1092` never reads it) and drop SHAPE[31:29] (`rtl/matvec_chan.sv:341-347`), so an XBANK MVGO computes on the wrong x silently. The device-keyed validation (SEQ_CAPS) + VERSION (spec §1.4, D5) is the only guard; SR6 and SR13b build it and test it with mocks that read `0xDEADC0DE` and `0xFAB1CA01`.
- **SEQ `0x64` reads `0xDEADC0DE` today** (the read mux default, `rtl/seq_unit.sv:1641`); that value is what every pre-round bitstream returns for SEQ_CAPS, and the host must decode it as the empty capability set.
- **`sw/seq_run.py` validates every stream it loads with today's rules** (`SF.validate_stream(...)` at `sw/seq_run.py:412`, `sw/seq_run.py:723`, `sw/seq_run.py:913`; the module contract at `sw/seq_run.py:17`). Left alone, it would refuse every r1 stream **on the R1 bitstream**. SR6 threads the device's caps into those calls.  <!--cites:noquote-->
- **`docs/SEQ_ISA.md`'s header line still says v2.1** (`docs/SEQ_ISA.md:1`) although §B16 is v2.2 (`docs/SEQ_ISA.md:1331`). SR2 bumps it to v2.3 and says in B17's first line that the header skipped v2.2.
- **The unit TB's read golden excludes STATUS polls** (`tb/tb_seq_unit.sv:63`; the golden generator's FENCE writes nothing, `tb/scripts/gen_seq_unit_vectors.py:306-320`). A masked FENCE's semantics are therefore invisible to the existing `.rtr` compare; SR3 adds a per-channel poll check.
- **The golden generator carries its own validator and executor** (`tb/scripts/gen_seq_unit_vectors.py:344-411`, `tb/scripts/gen_seq_unit_vectors.py:306-320`), a twin of `ref/seq_format.py`/`ref/seq_model.py`: every semantic change lands in both.
- **UI misses are placement luck on every build of this design** (spec §1.2; the shipped netlist's own base roll missed all four UI clocks, ch0 −0.524, `evidence/qwen9b/g5/G5D_TIMING.md:322-325`). A UI miss on a round build is never, by itself, evidence against the R-change.
- **The shipped margin is 0.000, produced once** (`NEXT_SESSION.md` §9; `evidence/qwen9b/g5/G5D_TIMING.md:1337-1344`); any netlist change re-opens the whole timing gate.
- **FENCE poll-tail costs are measured only for group sizes 2 and 4** (`ref/seq_cost.py:68`); a masked FENCE makes groups of 1 and 3, priced by nearest neighbour. This is why SR5b's "model held" band is not tighter.
- **VERSION is the launch tree's git hash** (`synth/scripts/launch_build.sh:12`): a build must launch from a clean, committed tree, and the hash is known at launch — the `SEQ_VERSIONS` row can be written then.
- **The r1/r2 `.e4` streams are gitignored and regenerable** (as every `.e4` in `tb/scripts/w9/` is, `evidence/qwen9b/ov/SV1_S1_VERIFY.md` §2): a task that consumes one re-checks its sha256 against the log that generated it before use.

---

## File structure

| file | responsibility | task |
|---|---|---|
| `docs/SEQ_ISA.md` | v2.3 header; B17 (B17.0 SEQ_CAPS, B17.1 R1, B17.2 R2; B17.3 R3 reserved text only) | SR2, SR11a |
| `sw/hwmap.py` | **the one definition** of `S_SEQ_CAPS = SB + 0x64` (beside `S_EMBLOG2`, `sw/hwmap.py:327`), `SEQ_CAPS_MAGIC`, `SEQ_CAP_BITS`, `seq_caps_set(word) -> frozenset` | SR2 |  <!--cites:noquote-->
| `ref/seq_format.py` | `caps=` argument on `validate`/`validate_stream` (imports the hwmap constants); FENCE mask (caps ∋ R1); MOVX start word / MOVY start row / SHAPE bits 29-30 (caps ∋ R2); disasm | SR2, SR11a |
| `rtl/seq_unit.sv` | FENCE/HALT validator split, `mv_fmask`, SEQ_CAPS read at word `10'h019`; (R2) MOVY/MOVX fields, range checks, caps bit | SR3, SR12 |
| `rtl/seq_movers.sv` | `cmd_fmask` port, `fmask_q`, F_SCAN mask; (R2) `cmd_row`, `cmd_xword` | SR3, SR12 |
| `rtl/matvec_chan.sv`, `rtl/matvec_engine.sv` | (R2 only) `csr_static_xbank/rbank`, the bank reset values, the sim-only envelope | SR12 |
| `tb/scripts/gen_seq_unit_vectors.py`, `tb/tb_seq_unit.sv`, `tb/Makefile` | masked-FENCE vectors, the per-channel poll check, the SEQ_CAPS check against hwmap; (R2) start-word/start-row vectors | SR3, SR12 |
| `tb/tb_matvec.sv`, `tb/tb_matvec_chan.sv`, `tb/seq_stub_mvchan.sv` | (R2) bank-1 cases, stub banks | SR12 |
| `ref/seq_model.py` | masked FENCE (R1); running ranges + real x_mem/RES storage (R2) | SR4, SR11a |
| `ref/seq_cost.py` | masked-FENCE group cost | SR4 |
| `ref/scripts/reorder_e4.py` | RTL level `r0/r1/r2`; masked-FENCE emission; bank emission; mask-aware hazard assert; manifest `seq_isa` + `caps` (informational; admission uses the device) | SR4, SR11b |
| `sw/seq_run.py`, `sw/chat_seq.py` | device-caps detection; caps threaded into every `validate_stream`; `--seq-rtl` level on the reorder path; new VERSION rows | SR6, SR7, SR13b, SR14 |
| `evidence/qwen9b/sr/` | the campaign's logs, scripts (sr_build.sh, sr_derive.py, sr8_ident.py, sr10_mig_period.tcl, …) and gate docs `SR<k>_*.md` | every task |
| `synth/scripts/incr_impl.tcl`, `synth/scripts/launch_incr.sh` | owned by SR1 (committed at `1682074`); later tasks invoke them, never edit them without a task of their own | SR1 (SR7, SR14 use) |
| `NEXT_SESSION.md`, `docs/USAGE.md` | one-line §8 status at the SR5b and SR7 gates; §1/§3/§8 at each board gate; USAGE for the new flags | SR5b, SR7, SR9, SR17 |

---

## Task map

| task | what | depends on | board? | est. wall |
|---|---|---|---|---|
| **SR1** (= Task 0) | step 0: incremental probe on build_042_bm1 — IN FLIGHT | — | no | 2–4 h |
| SR2 | ISA v2.3 text (B17.0 SEQ_CAPS, B17.1 R1) + hwmap constants + validator `caps=` (isa_bits out of scope — see SR-ISABITS) | — | no | short |
| SR3 | R1 RTL + SEQ_CAPS register + unit TB RED→GREEN + OOC | SR2 | no | ~1 h sim + ~2 h OOC |
| SR4 | R1 model + cost + pass (TDD), gate s1..s4 at r1 | SR2 | no | ~3 h/stream on snoke |
| SR5a | R1 chip TB, part 1 — build the binary; rung 1 (shipped streams cycle-identical); the S1-B control; layer census control. **A STOP gate, reviewed before R1 sim time is spent** | SR3 | no | ~2.3 h per run, parallel |
| SR5b | R1 chip TB, part 2 — the r1 streams, token-identical; the band verdict against the prediction | SR5a reviewed, SR4 | no | ~2.3 h per run, parallel |
| SR6 | host side: device-caps detection threaded into every validation, `--seq-rtl`, r1 pins, end-to-end mock selftests | SR2, SR4 | no | short |
| SR7 | R1 build: incremental → fallback ladder; sign-off or stop-back | SR1 verdict, SR3, SR5b, SR6 (**not** SR10) | no | 2–4 h, or ~11–12 h |
| SR7C | CONTINGENCY — MMCM compute clock (Q1). R1: only after SR7's ladder is exhausted, user informed first. R2: only by an explicit user ruling | SR7 exhausted / user ruling | no | a campaign |
| SR8 | R1 board session | SR7 signed off (or user waiver, Q9) | **yes** | a session |
| SR9 | docs at the R1 gate | SR8 | no | short |
| SR10 | the MIG's accepted periods (IP validation in a scratch project) + the DIMM-calibration route | — (light; may run beside a build on snoke) | no | ~1 h + ~1 h reading |
| SR-ISABITS | repair `evidence/qwen9b/g3/isa_bits.py`'s synthetic ATTN for the spilled KV (broken since 75598a9); rc 0 + a MEANINGFUL negative control. **Before SR11a** (the first task that changes layer-ARG encodings) | — | no | short |
| SR11a | R2 contract + validator + model running ranges (TDD); shipped streams still gate | SR4 | no | software + gate runs |
| SR11b | R2 pass (`--rtl r2`) + the r2 streams + their gates | SR11a | no | ~3 h/stream |
| SR12 | R2 RTL (seq_unit, seq_movers, matvec_chan, matvec_engine) + unit TBs | SR3, SR11a | no | ~1–2 h sim |
| SR13a | R2 chip TB: rung 1 on R2 RTL, r1 streams unchanged, r2 streams + band verdict, layer census control | SR12, SR11b, SR5b (its r1 cycles) | no | ~2.3 h per run |
| SR13b | host R2 capability: caps R2 required through the validator path; mislabelled / missing manifest refused | SR6, SR11a | no | short |
| SR14 | R2 build with the full drop order (UI cut ≤ 5 % only under SR10 + Q3) | SR7 closed (or waived), SR13a, SR13b; SR10 only for its UI-cut rung | no | 2–4 h, or ~11–12 h |
| SR15 | R2 board session | SR14 kept (signed off or waived) | **yes** | a session |
| SR16 | R3 decision from silicon (form (a) if taken) — not planned in detail | SR8 (+ SR15 or R2 dropped) | no | a doc |
| SR17 | docs at the round's close | SR15/SR16 | no | short |

SR2, SR10, SR11a/b and SR13b are software/doc or light tasks that may run while builds run; SR4 and SR6 may run beside SR3. Board tasks run alone.

---

### Task SR1 (= Task 0): step 0, the incremental-implementation probe — IN FLIGHT, do not wait for it

**Status:** dispatched concurrently with this plan (`.superpowers/sdd/2026-09-27-seq-rtl/task-SR1-brief.md`). Its commits so far: `45deebf` (`evidence/qwen9b/sr/sr_run.sh`, the help probe), `642bc7f` (`n001`, Vivado's own help for the incremental options), `1682074` (`synth/scripts/incr_impl.tcl` + `synth/scripts/launch_incr.sh`, project mode, `INCREMENTAL_CHECKPOINT` + its directive, auto-incremental off), `92c47e3` (`n002` preflight). This plan does not re-specify it; it records the acceptance SR7 and SR14 consume.

**Goal:** One incremental implementation of build_042_bm1's already-synthesised netlist against the shipped signoff checkpoint `synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper_postroute_physopt.dcp` (288,126,447 B, spec §4.3, `evidence/qwen9b/bm/BM1_T3_BUILD.md:688-696`), measuring the reuse fraction, whether `layer_0`'s shipped placement survives, and whether the result closes (spec §4.3 "Step 0").

**Files (SR1's):** `synth/scripts/incr_impl.tcl`, `synth/scripts/launch_incr.sh`, `evidence/qwen9b/sr/sr_run.sh`, `evidence/qwen9b/sr/n0NN_*.log`, evidence/qwen9b/sr/SR1_INCR_PROBE.md, out dir `synth/out_build_043_incr_probe/`. **No other task touches these.**

**Acceptance (measurable, all in SR1_INCR_PROBE.md):**
1. The Vivado property names / directives the incremental flow uses, **verified from Vivado's own help** (spec §4.3 and §6 item 5 said "from memory"), and the project-vs-non-project choice with its reason.
2. The reuse report: fraction of cells reused / re-placed / re-routed, with the `layer_0`, `seq_0` and `mvchan_0..3` hierarchy rows named.
3. Per-clock WNS / TNS / WHS for the six tracked clocks (Global Constraints), failing-endpoint counts, from fresh reports — beside the best BM1 roll (−0.124, `evidence/qwen9b/bm/n45_T3_spread2_score_ENDl.log:29`) and the ship (0.000, G5D §10).
4. The clock-root check on the routed checkpoint, DRC, the bitstream path/size/sha256 (NOT loaded).
5. A verdict **CLOSES / MISSES** against G5D §10's bar, and the fallback list of spec §4.3 stated, **not executed**.
6. The wall time of the run (the spec's 2–4 h is an estimate, `evidence/qwen9b/bm/BM1_T3_BUILD.md:743`).

**What it hands forward:** SR7 and SR14 invoke the same launcher with a different netlist; if SR1 MISSES with low reuse, the controller may rule that SR7 skips the incremental attempt and starts at the spread (step 5a) — with the reason recorded. If SR1 CLOSES, the controller may also ask the user whether build_042_bm1's incremental bitstream replaces the waived −0.124 roll as the measurement bitstream (Q9 is per bitstream — this plan does not presume it).

**Does NOT establish:** anything about R1/R2's netlists; a reproducible margin (one placement, `evidence/qwen9b/g5/G5D_TIMING.md:1337-1344`); board behaviour.

---

### Task SR2: ISA v2.3 — B17.0 SEQ_CAPS and B17.1 the FENCE mask; the hwmap constants; the validator's `caps=`

The contract first, as the state-spill plan did (its Task S1): write the encoding once, derive the reference and host copies from that text.

**Files:**
- Modify: `docs/SEQ_ISA.md` — line 1 header to v2.3; append `## B17` after §B16 (`docs/SEQ_ISA.md:1331-`, the file's last section)
- Modify: `sw/hwmap.py` — **the one definition**, beside `S_EMBLOG2` (`sw/hwmap.py:327`): `S_SEQ_CAPS = SB + 0x64`; `SEQ_CAPS_MAGIC = 0xFAB1CA`; `SEQ_CAP_BITS = {"R1": 1 << 0, "R2": 1 << 1, "R3": 1 << 2}`; `seq_caps_set(word) -> frozenset` (the empty set unless `word >> 8 == SEQ_CAPS_MAGIC`; unknown bits refused by name); `seq_caps_word(caps) -> int` (for mocks and the TB side file)  <!--cites:noquote-->
- Modify: `ref/seq_format.py` — uses the constants through its existing `import hwmap as HW` (`ref/seq_format.py:133`) — **no constant is defined here** (defining them here and importing into hwmap would be circular); `validate()` (`ref/seq_format.py:547`) and `validate_stream()` (`ref/seq_format.py:702`) gain `caps=frozenset()`; the FENCE/HALT clause (`ref/seq_format.py:688-690`) splits; disasm prints `FENCE mask=0x?` when non-zero  <!--cites:noquote-->
- Create: evidence/qwen9b/sr/sr2_isa_tdd.py, evidence/qwen9b/sr/SR2_ISA.md, logs `n200…`
- Test: evidence/qwen9b/sr/sr2_isa_tdd.py (RED then GREEN), boardfree selftests (unmoved or up); `evidence/qwen9b/g3/isa_bits.py` and its `--negative-control` are run and recorded, but are **out of scope** (fix round 2: broken since 75598a9 — see SR-ISABITS)

**Interfaces produced (exact names; SR3/SR4/SR6 consume them):**
- `SEQ_CAPS` word (SEQ `0x64`, read-only, writes ignored): **`{magic[31:8] = 24'hFAB1CA, 5'b0, r3[2], r2[1], r1[0]}`**. The magic is this plan's proposal (the spec fixes only "a fixed magic in the high bits and one bit per built feature", §1.4); SR2 writes it into B17.0 and it binds from that commit. `0xDEADC0DE`'s high 24 bits differ, so `seq_caps_set(0xDEADC0DE)` is the empty set.
- `validate(r, nrec=None, idx=None, shape_isa=None, caps=frozenset())`, `validate_stream(recs, allow_ext=True, shape_isa=None, caps=frozenset())`: without `"R1"` in `caps`, FENCE and HALT keep the all-zero rule (today's behaviour — every existing caller is unchanged); with `"R1"`, FENCE admits `target[3:0]` (any value, 0 = all) and still refuses `flags`, `imm32`, `addr_lo`, `len_or_addr_hi` and `target[15:4]` non-zero; HALT unchanged. A cap name outside `SEQ_CAP_BITS` raises. SR11a adds the R2 clauses under `"R2"`.

- [ ] **Step 1: B17.0 and B17.1 in `docs/SEQ_ISA.md`.** Header line 1 → `# SEQ ISA v2.3 (2026-09-27): the sequencer RTL round — SEQ_CAPS, the FENCE channel mask (B17)`, keeping the old line as the next comment line. B17's first line says the header was not bumped at v2.2 (§B16). Text: B17.0 the SEQ_CAPS word above, "HOST-ONLY, not reachable from any record", "the host validates every stream against the capability set decoded from the device's SEQ_CAPS, and only on a VERSION the caller named; a manifest's `caps` list is informational and must be a subset of the device's" (spec §1.4); B17.1 exactly spec §1.1's semantics: FENCE `target[3:0]` = channel mask, 0 = all four (today's meaning); every other field zero (err 0x06); F_SCAN still waits for the AXI-Lite write pipe in every case; a masked FENCE is still `mv_op 3` (B16's C5 counts it); **forward compatibility:** a non-zero mask on build_041/042 faults err 0x06 at the first masked FENCE, before any wrong result is consumed (spec §1.1). Reserve B17.2 and B17.3 headings with "written by SR11a / not taken" one-liners.
- [ ] **Step 2: RED.** evidence/qwen9b/sr/sr2_isa_tdd.py (committed before its first run): (a) `validate(FENCE target=0x5, caps={"R1"})` passes; (b) the same with `caps=frozenset()` refuses; (c) FENCE `target=0x10` refuses under both; (d) HALT `target=1` refuses under both; (e) FENCE `imm32=1` refuses under both; (f) `caps={"R9"}` raises; (g) `seq_caps_set(0xDEADC0DE) == frozenset()`, `seq_caps_set(0xFAB1CA01) == {"R1"}`, `seq_caps_set(0xFAB1CA03) == {"R1","R2"}`, `seq_caps_word({"R1"}) == 0xFAB1CA01`, and `HW.S_SEQ_CAPS - HW.SB == 0x64`; (h) the offset, magic and bit positions in B17.0's text (grepped out of `docs/SEQ_ISA.md`) equal hwmap's, so doc and code cannot drift; (i) `seq_format` defines no `SEQ_CAPS*` name of its own (the one-definition rule). Run on snoke: `bash evidence/qwen9b/sr/sr_run.sh n200_sr2_isa_tdd_RED.log python3 evidence/qwen9b/sr/sr2_isa_tdd.py` → expected FAIL on (a), (f), (g), (h).
- [ ] **Step 3: implement** the `hwmap.py` and `seq_format.py` changes. Every existing caller keeps its behaviour because the default `caps` is empty.
- [ ] **Step 4: GREEN + regressions.** n201_sr2_isa_tdd_GREEN.log (all cases PASS); n202_isa_bits.log (`evidence/qwen9b/g3/isa_bits.py`, rc 0) and n203_isa_bits_negctl.log (`--negative-control`, every perturbation REFUSED); n204_boardfree.log through `evidence/qwen2b/rd/rd_boardfree.sh` (the triple unmoved or up).
- [ ] **Step 5: gate doc + commit.** evidence/qwen9b/sr/SR2_ISA.md: the B17.0/B17.1 text by line, the SEQ_CAPS layout and the fact that its magic is the plan's choice, the one-definition rule, the RED/GREEN lines, the regressions, N1 recorded as folded. Commit `docs(SR2): SEQ_ISA v2.3 B17.0 SEQ_CAPS + B17.1 FENCE channel mask; hwmap SEQ_CAPS constants (one definition); seq_format caps=; TDD RED->GREEN` `-- docs/SEQ_ISA.md sw/hwmap.py ref/seq_format.py evidence/qwen9b/sr/sr2_isa_tdd.py evidence/qwen9b/sr/n20*.log evidence/qwen9b/sr/SR2_ISA.md`; then `spec_cites.py` LAST over SR2_ISA.md (n2NN_spec_cites.log, FAIL 0) and commit that log.

**Acceptance:** sr2_isa_tdd.py RED then GREEN on committed logs; boardfree triple unmoved or up; spec_cites FAIL 0. **isa_bits: out of scope — broken since 75598a9; negative control uninformative** (controller ruling, SR2 fix round 1; `evidence/qwen9b/sr/SR2_ISA.md` records the pre-SR2 control; the repair is Task SR-ISABITS).

**Does NOT establish:** that the RTL implements B17 (SR3); that any emitted stream uses it (SR4); that any host path passes the device's caps (SR6).

---

### Task SR3: R1 RTL — the FENCE channel mask and SEQ_CAPS in `seq_0`; the unit TB RED → GREEN; OOC counts

**Files:**
- Modify: `rtl/seq_unit.sv` — the header map (`rtl/seq_unit.sv:25-57`, add the `0x64 SEQ_CAPS` line); the FENCE/HALT validator arm (`rtl/seq_unit.sv:834-841`); `mv_fmask` declared beside `mv_op` (`rtl/seq_unit.sv:890`), reset with it (`rtl/seq_unit.sv:976`); the FENCE dispatch (`rtl/seq_unit.sv:1111-1116`); the `u_mov` port list (`rtl/seq_unit.sv:1514-1522`); the read mux (`rtl/seq_unit.sv:1635-1641`, a new `10'h019` arm)
- Modify: `rtl/seq_movers.sv` — header note under the FENCE poll path; port `cmd_fmask` after `cmd_nowait` (`rtl/seq_movers.sv:102`); `fmask_q` reset (`rtl/seq_movers.sv:609-614`), latched at S_IDLE (`rtl/seq_movers.sv:636-656`); F_SCAN (`rtl/seq_movers.sv:845-856`)
- Modify: `tb/scripts/gen_seq_unit_vectors.py` — its validator mirror (`tb/scripts/gen_seq_unit_vectors.py:399-409`) and executor (`tb/scripts/gen_seq_unit_vectors.py:306-320`) mask-aware; new directed builder `build_fmask`; new error vectors; a per-FENCE poll-expectation side file; a `caps.hex` side file carrying `HW.seq_caps_word(<the build's caps>)` (the TB's expected SEQ_CAPS — from hwmap, never re-typed)  <!--cites:noquote-->
- Modify: `tb/tb_seq_unit.sv` — per-channel STATUS-poll accounting bucketed by the DUT's current record index, checked against the side file; a host read of SEQ `0x64` compared with `caps.hex`
- Modify: `tb/Makefile` — `SEQ_ERRS` (`tb/Makefile:865`) gains `fmrsvd haltmask`; `SEQ_DIRECTED` (`tb/Makefile:875`) gains `fmask`
- Create: evidence/qwen9b/sr/SR3_R1_RTL.md, logs `n300…`

**RTL, by site (spec §1.1; estimated ~15 changed lines):**
- `rtl/seq_unit.sv` validator: `OP_FENCE: if ((r_flags != 8'd0) || (r_tgt[15:4] != 12'd0) || (r_imm != 32'd0) || (r_lo != 32'd0) || (r_hi != 32'd0)) begin v_bad=1; v_code=E_RSVD; end` and `OP_HALT:` keeps today's all-zero condition verbatim.
- `rtl/seq_unit.sv` dispatch: `OP_FENCE: begin mv_op <= 2'd3; mv_fmask <= r_tgt[3:0]; mv_cmd_valid <= 1'b1; ist <= I_MOVER; end`.
- `rtl/seq_unit.sv` read mux: `10'h019: s_axil_rdata <= SEQ_CAPS;` with `localparam logic [31:0] SEQ_CAPS = {24'hFAB1CA, 5'd0, 1'b0 /*r3*/, 1'b0 /*r2*/, 1'b1 /*r1*/};` beside `IDENT` (`rtl/seq_unit.sv:333`). No write decode (writes to `0x64` fall through as today). The literal is the RTL's copy of hwmap's value; the TB (below) is what ties them.  <!--cites:noquote-->
- `rtl/seq_movers.sv`: `input wire [3:0] cmd_fmask, // FENCE channel mask, 0 = all (SEQ_ISA B17.1)`; at S_IDLE `fmask_q <= (cmd_fmask == 4'd0) ? 4'hF : cmd_fmask;`; F_SCAN tests `chan_pend[fence_chan] && fmask_q[fence_chan]`. **F_SCAN still walks 0..3 one channel per cycle** — a mask-0 FENCE therefore takes exactly today's cycles (the basis of SR5a's cycle-identity rung). The poll-return path (`rtl/seq_movers.sv:750-758`) is unchanged.  <!--cites:noquote-->

- [ ] **Step 0: baseline OOC at the task's base commit, BEFORE any RTL edit** (clean tree): `ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm/evidence/qwen9b/g4 && nohup sh run_g4b_ooc.sh sr3_seq_base seq_unit > /dev/null 2>&1 &'` → `synth/out_ooc9b_sr3_seq_base/`. Capture its utilization lines into n300_ooc_seq_base.log when it lands.
- [ ] **Step 1: the vectors and the TB checks, RED against today's RTL.** In `gen_seq_unit_vectors.py`: (a) executor — FENCE clears `pend[c]` only for `c` in the mask (0 → all); (b) validator mirror — B17.1's rule (the generator validates with `SF.validate_stream(..., caps={"R1"})` at `tb/scripts/gen_seq_unit_vectors.py:812`); (c) `build_fmask`: no-wait MVGOs on channels 0, 1, 2; `FENCE mask=0b0010`; a MOVY on channel 1 (legal: drained); `FENCE mask=0b0101`; MOVYs on 0 and 2; a second no-wait MVGO on 3; `FENCE mask=0`; HALT — plus a case where a mask names a channel that is NOT pending (no poll, no hang) and one that skips a pending channel whose later mask-0 FENCE must poll it; (d) error vectors `fmrsvd` (FENCE `target=0x0010` → 0x06) and `haltmask` (HALT `target=0x0001` → 0x06), each after a legal record so the refusal cannot be an early halt (the `env0` pattern, `tb/scripts/gen_seq_unit_vectors.py:691-709`); (e) a side file `<prefix>.fpolls` listing, per FENCE record index, the set of channels it may poll and the set it must poll at least once; (f) `caps.hex` = `HW.seq_caps_word({"R1"})`. In `tb_seq_unit.sv`: count STATUS polls (`is_poll`, `tb/tb_seq_unit.sv:405`) per channel, bucketed by the DUT issue FSM's current record index (hierarchical read of `pc`); at HALT, `$fatal(1, …)` if any FENCE bucket polled a channel outside its may-set or skipped one in its must-set; print `TB_SEQ_FMASK PASS: <n> fences`; read SEQ `0x64` and `$fatal` unless it equals `caps.hex`. Run on snoke: `make -C tb tb_seq` through the wrapper → n301_tb_seq_RED.log. **Expected RED:** `seq_h_fmask` halts with err 0x06 at its first masked FENCE (`rtl/seq_unit.sv:834-841`) and the TB `$fatal`s; the SEQ_CAPS read returns `0xDEADC0DE` ≠ `caps.hex`; `fmrsvd`/`haltmask` already pass (today faults them too).  <!--cites:noquote-->
- [ ] **Step 2: the RTL edits above.**
- [ ] **Step 3: lint + GREEN, 4 seeds.** On snoke: `make -C tb lint_seq_unit` (n302_lint.log, zero `%Warning`); `make -C tb tb_seq_all` (n303_tb_seq_all_GREEN.log: `SEQ_SEEDS` = 1 2 3 4 at `tb/Makefile:858`, every `SEQ_ERRS`, `SEQ_MICRO`, `SEQ_DIRECTED` vector PASS, the guard, latency 0/8 and sideband variants PASS, `TB_SEQ_FMASK PASS`, the SEQ_CAPS read equal to hwmap's `0xFAB1CA01`). `make -C tb lint_seq_chip_9b` (n304_lint_chip.log) because the chip TB instantiates `seq_unit`.
- [ ] **Step 4: OOC counts.** `run_g4b_ooc.sh sr3_seq_r1 seq_unit` and, as the ladder's OOC rung control, `run_g4b_ooc.sh sr3_layer layer_chan` (both new out dirs). Logs n305_ooc_seq_r1.log, n306_ooc_layer.log.
- [ ] **Step 5: gate doc + commit.** evidence/qwen9b/sr/SR3_R1_RTL.md: the diff by site with line numbers after the edit; RED/GREEN lines; lint; the OOC table — `seq_unit` base vs R1 (LUT/FF/BRAM/DSP) beside BM1's `+187 LUT / +415 FF` (`evidence/qwen9b/bm/BM1_T3_BUILD.md:160`) for scale; `layer_chan` against 182 / 79 / 8 / 1840 (SR9: was 77 / 1838, the pre-T14A counts; `evidence/qwen9b/g5/G5C_RTL.md:773-777`). Commit `rtl(SR3): R1 FENCE channel mask (seq_unit validator+dispatch, seq_movers F_SCAN) + SEQ_CAPS at SEQ 0x64 checked against hwmap; tb_seq fmask vectors RED->GREEN x4` `-- rtl/seq_unit.sv rtl/seq_movers.sv tb/scripts/gen_seq_unit_vectors.py tb/tb_seq_unit.sv tb/Makefile evidence/qwen9b/sr/n30*.log evidence/qwen9b/sr/SR3_R1_RTL.md`; spec_cites LAST.

**Acceptance:**
1. `n301` RED on `seq_h_fmask` with err 0x06 and on the SEQ_CAPS read; `n303` GREEN on every vector, 4 seeds, plus `TB_SEQ_FMASK PASS`.
2. Lint: zero warnings on `lint_seq_unit` and `lint_seq_chip_9b`.
3. Every **existing** vector's `.wtr`/`.rtr` compare still passes unchanged (backward compatibility at unit level: existing streams carry FENCE target 0).
4. OOC: `layer_chan` exactly `OOC9B_URAM: 182`, RAMB36 79 / RAMB18 8, DSP 1840 (SR9: was 77 / 1838, pre-T14A; `evidence/qwen9b/g5/G5C_RTL.md:773-777`); `seq_unit` adds **no BRAM, URAM or DSP** (spec §1.1 adds none); its LUT/FF delta reported (no numeric bound is set — the spec states none).
5. SEQ_CAPS in sim equals `HW.seq_caps_word({"R1"})` = `0xFAB1CA01`.

**Does NOT establish:** chip-level cycle identity (SR5a); timing (SR7); any emitted R1 stream (SR4).

---

### Task SR4: R1 software — the reference model, the cost model and the pass emit masked fences (TDD)

**Files:**
- Modify: `ref/seq_model.py` — the FENCE arm (`ref/seq_model.py:1100-1102`) removes only the masked channels from `self.running` (mask 0 = all); the gate/validate path passes `caps` through (the stream's own needed caps — the model is a software gate, not a device)
- Modify: `ref/seq_cost.py` — a FENCE row's poll tail is `_tau(n)` over the **masked** pending group (`ref/seq_cost.py:339`, `ref/seq_cost.py:370`); the docstring records that sizes 1 and 3 are nearest-neighbour (`ref/seq_cost.py:68`)
- Modify: `ref/scripts/reorder_e4.py` — an `--rtl {r0,r1}` argument (r2 is SR11b's); at r1: schedule with OV1's per-channel fence (`evidence/qwen9b/ov/ov_census.py` `schedule(…, cfg["fence"]="perchan")`, `evidence/qwen9b/ov/ov_census.py:783-795`); `order_and_fences()` (`ref/scripts/reorder_e4.py:335-392`) emits `("FENCE", mask)` whose mask is exactly the channels of the unfenced MVGOs the next record's stream-edges need, and clears only those; `replay()` (`ref/scripts/reorder_e4.py:394`) models the masked drain; `assert_no_pending_hazard()` (`ref/scripts/reorder_e4.py:225`) becomes mask-aware; the output is validated with `caps={"R1"}`; `write_out()` (`ref/scripts/reorder_e4.py:840-876`) records `"seq_isa": "2.3"` and `"caps": ["R1"]` at r1 (informational; nothing new at r0)  <!--cites:noquote-->
- `evidence/qwen9b/ov/ov_census.py`: **no change** — spec §1.1 ("needs no model change for R1"); r1 imports it
- Create: evidence/qwen9b/sr/sr4_r1_tdd.py, evidence/qwen9b/sr/sr4_gate.sh (a copy of `evidence/qwen9b/ov/sv1_gate.sh` that passes `caps={"R1"}` and the `--rtl r1` streams), evidence/qwen9b/sr/SR4_R1_MODEL.md, logs `n400…`
- Test: sr4_r1_tdd.py, `reorder_e4.py --selftest` and its static selftest, `sw/chat_seq.py --selftest`, boardfree

- [ ] **Step 1: RED.** sr4_r1_tdd.py (committed first), on synthetic streams: (a) **the gate still catches the hazard under the new semantics** — no-wait MVGO ch0 and ch1, `FENCE mask=0b0010`, MOVX on ch0 → `RunningChannelError` (spec §1.1 "a masked FENCE that forgets a channel leaves it in the running set"); (b) the same with MVGO in place of MOVX, and MOVY; (c) `FENCE mask=0b0011` then MOVX ch0 → accepted; (d) mask 0 → identical model state to today's FENCE; (e) `assert_no_pending_hazard` raises `HazardError` on (a)'s record order; (f) at r1 on the synthetic segment `reorder_e4._synthetic()` the emitted fences carry masks, the replay makespan is ≤ r0's, and every emitted FENCE mask ⊆ the channels pending at that point; (g) at r0 the output is byte-identical to today's (the S1 pins, `sw/chat_seq.py` `REORDER_B_IMAGES`, regenerate unchanged); (h) the cost of a mask-{c} FENCE equals `_tau(1)`'s nearest-neighbour value. n400_sr4_tdd_RED.log → FAIL on (a)/(b)/(e)/(f)/(h) (today's model clears everything).
- [ ] **Step 2: implement.** The model refusal stays an explicit `raise RunningChannelError` (survives `python -O`, `evidence/qwen9b/ov/SV1_S1_VERIFY.md:289-293`).
- [ ] **Step 3: GREEN** n401_sr4_tdd_GREEN.log; `reorder_e4.py --selftest` + static selftest (`n402`); `sw/chat_seq.py --selftest` (`n403`, the reorder gates unchanged in substance); boardfree (`n404`).
- [ ] **Step 4: the four shipped streams still gate bit-exact with the refusals armed** (spec §4.1 rung 2): the model gate on `model_9b_s1..s4` at r0 → `SEQ GATE: PASS`, 2358/2358 checkpoints (`evidence/qwen9b/ov/SV1_S1_VERIFY.md:135`), logs `n405–n408`.
- [ ] **Step 5: the R1 streams.** `FABLE5_MODEL=9b FABLE5_RS_F=7` `reorder_e4.py --form B --rtl r1` on s1..s4 (the SV1 invocation, `evidence/qwen9b/ov/n32_reorder_s1_B.log`'s `=== cmd` line, plus `--rtl r1`) → `tb/scripts/w9/model_9b_s{1..4}_reordB_r1.e4.*` (gitignored, regenerable; **sha256 printed in the log** — SR5b re-checks it), `n410–n413`; each with the pass's hazard assert and OV1's postcheck GREEN and the printed makespan. Then sr4_gate.sh on each → 2358/2358, tokens IDENTICAL to the shipped artifact (`n414–n417`). Run concurrently on snoke (≈ 3 h each, as SV1's gates).
- [ ] **Step 6: gate doc + commit.** SR4_R1_MODEL.md: the model/pass/cost diffs by line; RED/GREEN; the four gates; per stream the number of FENCEs and the mask histogram; the pass's printed r1 makespan beside n120's R1 row (27,136,513 TB cycles, form B, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:17`). Commit by explicit paths (`ref/seq_model.py ref/seq_cost.py ref/scripts/reorder_e4.py evidence/qwen9b/sr/sr4_r1_tdd.py evidence/qwen9b/sr/sr4_gate.sh evidence/qwen9b/sr/n4*.log evidence/qwen9b/sr/SR4_R1_MODEL.md`); spec_cites LAST.

**Acceptance:** RED then GREEN on committed logs; every selftest GREEN; the four shipped streams 2358/2358 at r0; the four r1 streams 2358/2358 with tokens IDENTICAL and the hazard assert + postcheck GREEN; r0 output byte-identical to today's.

**Does NOT establish:** that the RTL executes the masked streams the way the model does (SR5b); any speed beyond the model's makespan.

---

### Task SR5a: R1 on the chip TB, part 1 — the binary, backward compatibility cycle-identical, the S1-B control. A STOP gate

Split by controller ruling: this half proves the new RTL runs every existing stream **exactly** as the ship does, and is reviewed before any R1 stream spends chip-TB time.

**Files:**
- Create: evidence/qwen9b/sr/sr_build.sh (copy of `evidence/qwen9b/ov/sv1_build.sh`: builds from a `git archive` snapshot of a named commit into `tb/obj_dir_seq_chip_sr<k>`; its identity check changed from "rtl/ equals the shipped 86c94d9" to "rtl/ and tb/*.sv[h] equal the named RTL commit's", refusing an existing obj_dir), evidence/qwen9b/sr/run_sr_chip.sh (copy of `evidence/qwen9b/ov/run_sv1_chip.sh`; the token record is still read from `evidence/qwen9b/s4/S4_REPLAY.md` under the shipped stem; its `--cycles-today` check extended with `--cycles-equal <N>` that FAILS on any difference), evidence/qwen9b/sr/SR5a_R1_COMPAT.md, logs `n500–n549`

- [ ] **Step 1: build the binary** from the SR3 commit: `sr_run.sh n500_build_sr5.log bash evidence/qwen9b/sr/sr_build.sh <SR3 commit>` → `tb/obj_dir_seq_chip_sr5/tb_seq_chip_9b_sr5`, sha256 printed. SR5b uses this binary unchanged.
- [ ] **Step 2: the runs, detached on snoke, in parallel, memory watched** (`evidence/qwen9b/g4/run_g4a_memwatch.sh`):
  - **rung 1, backward compatibility** (spec §4.1 item 1): the four shipped `model_9b_s1..s4` streams on the new RTL → `TB_SEQ_CHIP PASS`, tokens IDENTICAL, and **cycles identical** (`--cycles-equal`) to 196,706,821 / 196,707,670 / 196,707,670 / 196,706,833 (`evidence/qwen9b/ov/SV1_S1_VERIFY.md:146-148`, T from `evidence/qwen9b/s4/S4_REPLAY.md:398-401`) — `n510–n513`.
  - **the S1 control:** `model_9b_s1_reordB` on the new RTL → cycles identical to SV1's 171,731,320 (`evidence/qwen9b/ov/n53_chip_s1_reordB_control.log:51`) — `n514`.
  Wall ≈ 7,742–8,255 s per run (`evidence/qwen9b/ov/SV1_S1_VERIFY.md:67`).
- [ ] **Step 3: the layer census control** (spec §4.1 item 4; `layer_0` untouched): `evidence/qwen9b/g4/run_g4b_census.sh` on the new tree → bit-exact (`n520`).
- [ ] **Step 4: gate doc + commit + STOP for review.** SR5a_R1_COMPAT.md: the binary's identity, the five runs' cycles and tokens against their references, the census line. **Any cycle difference is a STOP to be explained** (a mask-0 FENCE walks the same F_SCAN, so a difference means the RTL changed something it should not have). Commit scripts, logs and doc by explicit paths; spec_cites LAST. The controller reviews before SR5b is dispatched.

**Acceptance:** 4/4 shipped streams PASS with tokens IDENTICAL and cycles identical to the S4 counts; the S1-B control identical to SV1's cycles; the layer census bit-exact.

**Does NOT establish:** that masked FENCEs behave on the chip TB (SR5b).

---

### Task SR5b: R1 on the chip TB, part 2 — the r1 streams token-identical, the round's first TB number

This is the round's first TB number against the model's 8.811 (spec §3.1; the TB-cycle form of that prediction is 27,136,513 cycles for the token-4 body window, form B, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:17`).

**Files:** evidence/qwen9b/sr/sr_chipvec.sh (copy of `evidence/qwen9b/ov/sv1_chipvec.sh`), evidence/qwen9b/sr/sr_derive.py (copy of `evidence/qwen9b/ov/sv1_derive.py`, retargeted), evidence/qwen9b/sr/SR5b_R1_CHIP.md, `NEXT_SESSION.md` (one line in §8), logs `n550–n599`

- [ ] **Step 1: the prediction and the bands, committed before any run lands** (n550_sr5_predictions.log, `sr_derive.py --predict`), stated so **every stream is judged**:
  - **s1 — the token-4 body window, the quantity SV1 and n120 use** (`evidence/qwen9b/ov/n120_sr0_clock_sens.log:12` defines it; the R1 row is `evidence/qwen9b/ov/n120_sr0_clock_sens.log:17`, the R1+R2 row `evidence/qwen9b/ov/n120_sr0_clock_sens.log:18`): *the model held* if s1's measured token-4 body window is within **±0.5 %** of 27,136,513 cycles; *held loosely, attribute* within ±2 %; outside ±2 % is a **STOP** before any build. **Why (plan criterion, D):** S1's model hit the TB to +0.043 % (`evidence/qwen9b/ov/SV1_S1_VERIFY.md:38-40`), but R1 adds masked groups of size 1 and 3 whose poll tails are nearest-neighbour estimates (`ref/seq_cost.py:68`), so a tenfold wider "held" band is the honest one; the loose band is where the gate doc must attribute the gap by class (from the s1 timeline) before SR7 launches.
  - **s2–s4 — the whole run:** each seed's whole-run cycles R1 / S1-B (SV1's 171,731,695 / 171,731,695 / 171,731,425, `evidence/qwen9b/ov/SV1_S1_VERIFY.md` §3 table) must be **< 1** and within **±0.5 %** of s1's own whole-run R1 / S1-B ratio (the four seeds run the same stream shape; SV1's four seeds' whole-run cycles agree to a few hundred cycles, same table), and R1 / shipped likewise within ±0.5 % of s1's. Outside ±0.5 % is attributed; outside ±2 % is a STOP.
- [ ] **Step 2: stream identity before use:** re-hash `tb/scripts/w9/model_9b_s{1..4}_reordB_r1.e4.*` and compare with the sha256s SR4 logged (`evidence/qwen9b/sr/n410–n413`) — any mismatch is a STOP (regenerate through SR4's recipe, never hand-edit) (`n551`).
- [ ] **Step 3: chip vectors** for the four r1 streams (sr_chipvec.sh, `n552–n555`): golden identical to the shipped golden except NREC/PC (the SV1 check, `evidence/qwen9b/ov/SV1_S1_VERIFY.md` §3).
- [ ] **Step 4: the runs**, detached on snoke, parallel, memory watched, on SR5a's binary: `model_9b_s{1..4}_reordB_r1` → PASS, tokens IDENTICAL (a token mismatch is a STOP with artifacts preserved), `n560–n563`; one timeline run on s1 (`--csv`, CSV gitignored, sha256 committed) `n564`.
- [ ] **Step 5: derive + verdict** n570_sr5_derive.log (sr_derive.py): per seed cycles, ms/token, ×shipped, ×S1-B; s1's token-4 body window against the prediction; s2–s4's ratios against s1's; the band verdict for every stream; per-class attribution from the timeline if any stream is outside ±0.5 %.
- [ ] **Step 6: gate doc + commit.** SR5b_R1_CHIP.md (the SV1 table shape). One line in `NEXT_SESSION.md` §8 item 3: "SR5b (date): R1 on the chip TB — tokens IDENTICAL 4/4, <verdict>, evidence/qwen9b/sr/SR5b_R1_CHIP.md". Commit the scripts, logs, doc and `NEXT_SESSION.md` by explicit paths; spec_cites LAST over the gate doc and `NEXT_SESSION.md`.

**Acceptance:** R1: 4/4 PASS, tokens IDENTICAL; the stream sha256s match SR4's; every stream judged against the band stated before the runs; the verdict recorded.

**Does NOT establish:** board speed (the model's 8.811 is board-scaled by OV1's uniform factor, spec §0); timing; context > 6 tokens / long KV (the chip TB's scenario shape).

---

### Task SR6: the host side for R1 — device capabilities threaded into every validation; the `--seq-rtl` level

**Files:**
- Modify: `sw/seq_run.py` — `Dev.seq_caps()` beside the BM1 feature detection (`sw/seq_run.py:1416-1427`): reads `HW.S_SEQ_CAPS`, returns `HW.seq_caps_set(word)` (the empty set on `0xDEADC0DE`); **every stream validation passes the device's caps**: the three `SF.validate_stream(...)` calls (`sw/seq_run.py:412`, `sw/seq_run.py:723`, `sw/seq_run.py:913`) take `caps=` from the open `Dev` (or, board-free, from an explicit `--caps` argument that defaults to the empty set — never from the manifest); a manifest `caps` list that is not a subset of the device's is refused by name before any DMA of the stream; the module docstring's contract (`sw/seq_run.py:17`) updated  <!--cites:noquote-->
- Modify: `sw/chat_seq.py` — `--seq-rtl {r0,r1}` (default r0; `$FABLE5_SEQ_RTL` likewise) threads the level into `resolve_reorder()` → `reorder_e4.reorder(…, rtl=…)`; the per-image r1 pins beside `REORDER_B_IMAGES` (`sw/chat_seq.py:638`), generated by a committed run; gates 3 and 4 (hazard assert on the three images, the B6 model gate) run the R1 model at r1; `open_board` reads the device's caps and the images are validated against them before any upload — the device-keyed caps must reach **chat_seq's own `validate_stream` sites** (`sw/chat_seq.py:480`, `sw/chat_seq.py:521`) as well as seq_run's  <!--cites:noquote-->
- Modify: `docs/USAGE.md` §3 — the `--seq-rtl` flag, one paragraph (SR9 extends it)
- Modify: `sw/serve.py` — `BoardBackend._args()` (the argparse-compatible namespace `ChatSession` reads) pins `seq_rtl` and any other new `args.*` read chat_seq gains (as SR2b pinned `reorder=None, reorder_check=False`: serve runs the shipped order until the user decides otherwise)
- Create: evidence/qwen9b/sr/sr6_host_tdd.py, evidence/qwen9b/sr/SR6_HOST.md, logs `n600…`

- [ ] **Step 1: RED** sr6_host_tdd.py — **end-to-end through the validator path, with mocks of the SEQ window** (the `n35` closed-gate + upload-tripwire pattern, `NEXT_SESSION.md` §3): (a) an r1 stream **loads** through `seq_run`'s real load path on a mock whose SEQ_CAPS reads `0xFAB1CA01`; (b) the same stream is **refused on a mock reading `0xDEADC0DE`**, by the validator (err names the masked FENCE record), with the upload tripwire untouched; (c) a shipped (r0) stream loads on both mocks; (d) an r1 stream whose manifest claims `caps: []` still refuses on `0xDEADC0DE` and still loads on `0xFAB1CA01` (the manifest is not the key); (e) a manifest claiming `caps: ["R2"]` on a `0xFAB1CA01` device is refused by name; (f) `chat_seq --seq-rtl r1` on the `0xDEADC0DE` mock refuses before any upload; (g) **the positive case:** `chat_seq --seq-rtl r1` **loads** on a `0xFAB1CA01` mock (boardless — the mock-device path, or the reorder-check path if it reaches `validate_stream`), its three images passing chat_seq's validation with the device's caps. → n600_RED.log (today's `seq_run` refuses (a) — the I3 defect this task fixes).
- [ ] **Step 2: implement; the r1 pins from a committed run** (n601_r1_pins.log, the `evidence/qwen9b/ov/n88_s1p_formB_pins.log` recipe at `--rtl r1`).
- [ ] **Step 3: GREEN** `n602`; `sw/seq_run.py --selftest` (`n603`), `sw/chat_seq.py --selftest` (`n604`), boardfree (`n605`, triple unmoved or up).
- [ ] **Step 3b: serve's namespace.** Pin `seq_rtl` (and any new `args.*` read chat_seq adds) in serve's `_args()`, and re-run the serve selftest (`sw/serve.py --selftest`, `n606`) — serve's coverage check is a single `need()` whose missing list can grow while the count stays 84/1, so read its line ("args namespace covers chat_seq's args.* reads" → ok), not just the count.
- [ ] **Step 4: gate doc + commit** (paths: `sw/seq_run.py sw/chat_seq.py sw/serve.py docs/USAGE.md` + own evidence); spec_cites LAST.

**Acceptance:** RED then GREEN; in every refused case the refusal happens before any DMA (upload tripwire untouched); an r1 stream loads on a mock R1 device; default behaviour (r0) byte-identical — the existing form-B pins regenerate unchanged; selftests GREEN.

**Does NOT establish:** that the board admits the new VERSION (its row is SR7's last step) or that SEQ_CAPS reads right on silicon (SR8).

---

### Task SR7: the R1 build — incremental first, then the fallback ladder in the spec's order; sign-off or stop-back

**Files:**
- Create: evidence/qwen9b/sr/SR7_R1_BUILD.md, logs `n700…`; out dirs `synth/out_build_044_r1` (create + synth + the default base roll), `synth/out_build_044_r1_incr` (the incremental run), and only if needed `synth/out_build_044_r1_ckr2_<D>` (spread) — every one new
- Modify (last step, only if the bitstream goes to the board): `sw/seq_run.py` `SEQ_VERSIONS` (`sw/seq_run.py:164-189`) gains the R1 row, "admitted only when named"; its selftest re-run; `NEXT_SESSION.md` §8 (one line)

**No UI cut in this task.** The user's Q3 answer allows a UI cut *to close R2*; an R1 netlist that misses on the UI clocks goes down the same ladder as any other miss and, at its end, to the user.

- [ ] **Step 1: preconditions** (n700_preflight.log, snoke): SR1's verdict read (SR1_INCR_PROBE.md §0) and `synth/scripts/launch_incr.sh`'s arguments; SR3–SR6 committed and SR5b's verdict "held" or "held loosely, attributed"; `git status` clean (VERSION = the launch hash, `synth/scripts/launch_build.sh:12`); no other Vivado job of this project running; disk space. The controller rules here whether to attempt the incremental step at all (if SR1's reuse was too low to matter, go to step 5a — the reason recorded in the gate doc).
- [ ] **Step 2: launch** `ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm && nohup bash evidence/qwen9b/sr/sr_run.sh n701_launch_build_044_r1.log synth/scripts/launch_build.sh build_044_r1 > /dev/null 2>&1 &'`; verify within 10 min (`n702`: pid alive, `CREATE_PROJECT_OK`, the VERSION hash printed). This also produces a default base roll (≈ 4 h 03 m for a base build, `evidence/qwen9b/bm/BM1_T3_BUILD.md:596-598`) — kept as one more data point.  <!--cites:noquote-->
- [ ] **Step 3: the incremental run** as soon as `synth_1` is complete: `synth/scripts/launch_incr.sh build_044_r1 build_044_r1_incr <directive> /home/cah/r2d2/code/fpga/fable5_llm/<reference dcp path> <incremental directive> /home/cah/r2d2/code/fpga/fable5_llm/synth/constraints/fable5_clockroot_9b.xdc` (SR1's launcher, with SR1's verified directive choices; **both file arguments ABSOLUTE** — the launcher cd's into the new out dir before Vivado runs, so a relative XDC or dcp path makes `synth/scripts/incr_impl.tcl` FATAL on a missing file after the rsync has already been paid for), reference = the shipped signoff checkpoint (spec §4.3), clock-root XDC implementation-only, the full recipe (post-place + post-route phys_opt AggressiveExplore, `synth/scripts/full_impl.tcl:33-37`), `report_incremental_reuse`. **Judgment option (controller's ruling):** if SR1 CLOSED, a second concurrent incremental run with SR1's routed checkpoint as the reference (it carries the BM1 counters, so `seq_0` reuse should be higher, spec §4.4) in `synth/out_build_044_r1_incr_bm1ref/`.  <!--cites:noquote-->
- [ ] **Step 4: score every landed run against G5D §10** (fresh reports; `n71x_score_<run>.log` via the BM1 scoring pattern `evidence/qwen9b/bm/bm1_roll_score.sh`): per-clock WNS/TNS/WHS for the six tracked clocks by name, failing endpoints, the reuse report, `seq_0`'s own worst slack beside +0.397 ship / +0.037 BM1 (`evidence/qwen9b/g5/G5D_TIMING.md:1031`, `evidence/qwen9b/bm/BM1_T3_BUILD.md:650`), and the exoneration check of `n57` on any miss (failing endpoints starting/ending in `seq_0`; `evidence/qwen9b/bm/n57_T3_fix1_exoneration_ENDl.log`'s method). A closing run then gets `evidence/qwen9b/g5/g5d_clockroot_check.tcl` on its routed checkpoint **before** `synth/scripts/final_verify.tcl` (`n72x`), DRC, the bitstream path/size/sha256 and the `.mmi`/`.bit`/`.dcp` timestamps from the same run. **CLOSES → step 6.**  <!--cites:noquote-->
- [ ] **Step 5: MISSES → the fallback ladder, in the spec's order (§4.3); each rung is a stop-and-report to the controller with numbers, never an automatic next launch; a rung is skipped only with a recorded reason in the gate doc:**
  - **(a) a four-directive spread with the clock-root XDC** — `TAG=ckr2 XDC=/home/cah/r2d2/code/fpga/fable5_llm/synth/constraints/fable5_clockroot_9b.xdc synth/scripts/launch_po2.sh build_044_r1 AltSpreadLogic_high AltSpreadLogic_medium ExtraNetDelay_high ExtraTimingOpt` (the recipe of `evidence/qwen9b/bm/BM1_T3_BUILD.md:44-50`; 7–8 h, `evidence/qwen9b/bm/BM1_T3_BUILD.md:596-598`); a second spread only on the controller's ruling (T3 §9's choice of directives);  <!--cites:noquote-->
  - **(b) the post-route phys_opt playbook** on the best roll (T3 §11; priced +0.000 twice, `evidence/qwen9b/g5/G5D_TIMING.md:1317-1318`);
  - **(c) the `layer_0` RTL fallbacks** — the ALU op-stage (spec §4.2, if `u_alu` is among the failing paths) or the attention output-gather round (`evidence/qwen9b/bm/BM1_T3_BUILD.md:795-798`, if `u_attn` is) — each a **separate spec'd RTL round** (it touches `layer_0` and loses the incremental premise); this plan stops back;
  - **(d′) a failing path rooted in `seq_0` — R1's own cone** (the exoneration check shows failing endpoints starting or ending in `seq_0`): an **R1 retiming fix** — a spec'd RTL change to the decode/F_SCAN cone, its own task with the SR3 ladder — **or the user decides**;
  - **(e) Q1's MMCM compute clock — Task SR7C**, only after (a)–(d′) are exhausted (or each skipped with its recorded reason), **with the user informed first**.
  **If the bar is still missed and the ladder is exhausted, the user decides** — and a waiver, if the user gives one, covers **this bitstream only** (Q9). A waiver request carries the exoneration numbers (0 failing endpoints in `seq_0` if that is what the check shows) and the model cost of not having R1.
- [ ] **Step 6: gate doc** SR7_R1_BUILD.md: §0 verdict (SIGNED OFF / WAIVED by the user on <date> / STOPPED at rung x); every run's table row; the reuse report; the clock-root and final_verify lines; the bitstream identity; NOT established. One line in `NEXT_SESSION.md` §8 item 3 with the verdict and the gate doc.
- [ ] **Step 7: admit the VERSION** (only for a signed-off or user-waived bitstream): `SEQ_VERSIONS` row `0x<hash>: (HW.SHAPE_ISA_9B, "build_044_r1_<run> (R1 FENCE mask + BM1 counters; admitted only when named)")`; `sw/seq_run.py --selftest` GREEN (`n78x`). Commit the logs, the gate doc, `NEXT_SESSION.md` and `sw/seq_run.py` by explicit paths; spec_cites LAST.

**Acceptance:** a bitstream that meets G5D §10 (WNS ≥ 0, WHS ≥ 0, 0 failing endpoints, all clocks), the clock-root check passed on its routed checkpoint before final_verify, final_verify clean, fresh-report provenance — **or** an explicit user ruling recorded in the ledger and the gate doc.

**Does NOT establish:** a reproducible margin (one placement); board behaviour; that R2 will close on the same placement.

---

### Task SR7C: CONTINGENCY — the MMCM compute-clock domain (Q1)

**Trigger, for R1:** SR7 step 5 (a)–(d′) exhausted, or each skipped with a recorded reason, with the numbers in SR7_R1_BUILD.md; **before any file changes, the controller tells the user** that the Q1 fallback is being taken, with the miss, the ladder's results and the cost below. **Trigger, for R2:** only an explicit user ruling after being informed (SR14). Q2's default then applies: **accept an aclk cut up to 5 %, ask beyond** (spec §7 Q2).

**What it is (spec §2.3):** an MMCM (clocking wizard) fed from `xdma_0/axi_aclk` (or a DIMM refclk), producing the compute clock for `seq_0`, `layer_0`, `mvchan_*/aclk` and `burst_smc`, with `axil_smc` and `axi_smc` doing clock conversion from the XDMA's master ports. Model value at a 5 % aclk cut: R1 8.579 (form B), S1 8.117, shipped 7.074 (spec §3.1, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:34-36`); break-even vs S1 at full clock is 9.57 % (`evidence/qwen9b/ov/n120_sr0_clock_sens.log:105`).

**Files (a design amendment is written FIRST, reviewed, then the implementation); logs `n1800–n1899`, gate doc evidence/qwen9b/sr/SR7C_CLOCK.md:**
- **Amend:** `docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md` — a dated amendment `A1 — the compute clock` in the existing spec, in the house amendment style — the touch list below with every site cited
- Modify (implementation, after the review): `synth/scripts/create_project.tcl` (the clock wizard; the SmartConnect clock ports; **the hard assertions that the state DMA runs at 250 MHz in the XDMA's own domain**, `synth/scripts/create_project.tcl:317-322` and `synth/scripts/create_project.tcl:576-583`, re-decided explicitly — they exist to keep SmartConnect from inferring a converter on that path); `synth/constraints/fable5_cdc.xdc:17-18` (false paths written against the name `axi_aclk`); `synth/constraints/fable5_clockroot_9b.xdc` (the compute clock needs its own root and its own SLR check, G5D §11); `csr_0`'s and the host path's crossing
- Test: the chip TB is single-clock — a CDC TB of the converted paths is designed in the amendment; the standing ladder at the new period; **a board step-time measurement at the new clock**, because spec §3's figures are a model

**Steps:** amendment + review → user ruling on the period → create_project change (dated) → OOC counts → full build (base + spread; the incremental flow does not survive a new clock tree, spec §2.3) → sign-off at the new period by the same G5D §10 bar at that period → the board session (SR8's form) with the extra step-time rung.

**Acceptance:** WNS ≥ 0 / WHS ≥ 0 / zero failing endpoints on every clock at the new period, the clock-root check for both roots, final_verify clean, and a board step time measured at that clock.

**Does NOT establish, even when done:** CDC latencies' effect on the model (spec §6 item 2); the MMCM's granularity was from memory (UG572, spec §6 item 6) until the amendment reads it from the IP.

---

### Task SR8: the R1 board session — one controlled session, token identity fail-closed, restore to build_041 at the end

**Precondition:** SR7 signed off, or the user's per-bitstream waiver recorded (Q9); SR6 committed; the R1 VERSION row committed (SR7 step 7); the controller's go; `sw/board_lock.py --status` free; hw_server running on snoke. **Nothing here runs without the controller.**

**Files:** evidence/qwen9b/sr/sr8_ident.py (copy of `evidence/qwen9b/bm/bm1_ident.py` plus the SEQ_CAPS read decoded through `HW.seq_caps_set`, printing `IDENT: PASS/FAIL` against a named expected VERSION, CALIB `0xF`, BM_IDENT and SEQ_CAPS word; it drives no SEQ window and does no DMA; committed before use), evidence/qwen9b/sr/sr8_board_table.py (copy of `evidence/qwen9b/bm/bm1_board_table.py`, committed before use), evidence/qwen9b/sr/SR8_R1_BOARD.md, logs `n800…`.

**The expect-version, per tool, for the whole session:** `sr8_ident.py --expect <hash>` (identity only); `sw/seq_run.py --expect-version <hash>` (stream runs); `FABLE5_SEQ_EXPECT_VERSION=<hash>` in the environment of `sw/chat_seq.py`, `evidence/qwen9b/bm/bm1_census.py` and `evidence/qwen9b/bm/bm1_chat511.sh` (they build `Dev()` themselves); on build_041 the variable is **unset** (its hash is the default). `sw/program_fpga.sh` checks no VERSION — sr8_ident.py right after it is the check.

**The RD9 rungs this session runs, by name** (`evidence/qwen9b/g6/RD9_GATE.md`): §2 the reprogram; §3 identity (VERSION off the silicon, CALIB, plus BM_IDENT and SEQ_CAPS); §5 (a) the weight pack per piece, readback-verified on upload; §7 the four-seed token lockstep against `evidence/qwen9b/g4/G4A_REPLAY.md` §4.1a (after `evidence/qwen9b/g6/g6_state.py --write-initial`); §8 chat, token identity by `--want-ids`; §10 step time by the counters. **Not run, and the gate doc says so:** §6 the state region bit-exact against `state_final.bin`, §8.7 long context (T < 512 only, `rtl/attn_core.sv:114`), §9 EMBLOG2.

- [ ] **Step 0: read-only preflight** (`n800`): lock status, `pgrep hw_server`, what is on the board (sr8_ident.py, no DMA), snoke uptime (a reboot since `NEXT_SESSION.md` §1 means a power-loss check first). **If the board is not on build_041, program build_041 first** (safe flow, `n801`) and read its identity.
- [ ] **Step 1: control on the shipped bitstream** (build_041, VERSION `0xc973c18a`): the chat511 session in form B (the default) through `evidence/qwen9b/bm/bm1_chat511.sh` with `BM1_WANT_IDS` set to the pinned reference so it fails closed on any token difference (`evidence/qwen9b/bm/bm1_chat511.sh` header, fix round 1 I2) — `n802`; compare to `n95` (lite 115.0934 ms, full 131.2454 ms, `NEXT_SESSION.md` §2 overlap table).
- [ ] **Step 2: program R1** `sw/program_fpga.sh <R1 .bit>` — one lock hold across remove → JTAG → rescan (`n803`: `PROGRAM_OK`, rescan finds `82:00.0 … 9038`); a non-zero exit is the only warning of a failed JTAG (`docs/USAGE.md` §2).
- [ ] **Step 3: identity** (`n804`, `sr8_ident.py --expect <R1 hash>`): VERSION = the R1 hash, **CALIB `0xF`**, `BM_IDENT 0xFAB1B301`, **SEQ_CAPS = `HW.seq_caps_word({"R1"})` = `0xFAB1CA01`**. **On any mismatch: NO DMA of any kind → `sw/program_fpga.sh` build_041 → sr8_ident.py on build_041 → record every value read → STOP** (the session ends; the controller decides).
- [ ] **Step 4: the RD9 §7 token lockstep and the bitstream-alone control on R1** (pack re-uploaded, readback-verified — 347 s cold / 29 s warm, `evidence/qwen9b/bm/BM1_BOARD_IDLE.md` §4 item 8): `g6_state.py --write-initial`, then `sw/seq_run.py --expect-version <R1 hash>` on `model_9b_s1..s4` (shipped order) → tokens identical to G4A §4.1a (`n805`); then S1 form B (r0 streams, mask 0) chat511 with `BM1_WANT_IDS` set (`--want-ids`, fail-closed) and `FABLE5_SEQ_EXPECT_VERSION=<R1 hash>`, counters on (`n806`); step time vs `n802` (it isolates the bitstream, the way BM1 §2 measured −0.0015 %).
- [ ] **Step 5: R1** — the same chat511 session at `--seq-rtl r1` (`n807`), counters on, `--want-ids` fail-closed, `FABLE5_SEQ_EXPECT_VERSION=<R1 hash>`. Plus the 6-token stream census on the r1 stream and its r0 control (`evidence/qwen9b/bm/bm1_census.py` stream mode, the `n72`/`n73` recipe) (`n808`, `n809`): the stream's ms/token is the figure spec §3.1's 8.811 tok/s is board-scaled to.
- [ ] **Step 6: restore build_041** (`n810` program, `n811` sr8_ident.py VERSION `0xc973c18a`, CALIB `0xF`), then a restore chat sanity with `--want-ids` and the variable unset (`n812`, the `n77` pattern) so the board is left serving the shipped default.
- [ ] **Step 7: table + gate doc** (`n813`, sr8_board_table.py): per launch step times, R1 vs S1-B on the same bitstream (lite/full, paired by position, sd), R1 vs build_041; the stream tok/s beside the model's 8.811 and its ratio; the C5 FENCE-wait share beside `n72`'s 41.96 % (`NEXT_SESSION.md` §2); tokens on every run; the RD9 rungs run and not run. Commit logs, scripts, doc; spec_cites LAST.

**Acceptance:** identity with VERSION/CALIB/SEQ_CAPS before any DMA; every run's tokens IDENTICAL to its reference (a difference ends the session: restore build_041, identity, report); the board restored to build_041 with identity + chat sanity; the measured R1 tok/s reported against the model with the ratio (a report, not a pass/fail — the model is not a gate).

**Does NOT establish:** more than one session per condition; contexts > 511 (`rtl/attn_core.sv:114`'s ceiling, spec §6 item 10); sign-off of a waived bitstream (a waiver is not a sign-off).

---

### Task SR9: docs at the R1 gate

**Files:** `NEXT_SESSION.md` (§1 what is on the board — re-derived from SR8's log timestamps; §3 the R1 bitstream row, its VERSION, its admission rule; §8 the round's status and the next decision; §9 item 10 marked done with the gate doc), `docs/USAGE.md` (§3 `--seq-rtl`, §6 which tool drives which bitstream), `docs/SEQ_ISA.md` (B17.1 "as built" line citing SR3_R1_RTL.md), logs `n900–n989`.

- [ ] `o3_cite_drift.py --plan` over every doc cited from the files above → `--fix` only on moved anchors → `--verify`; then the edits; then `spec_cites.py` LAST over `NEXT_SESSION.md`, `docs/USAGE.md`, `docs/SEQ_ISA.md` and this plan (`n9NN`, FAIL 0). Commit by explicit paths.

**Acceptance:** spec_cites FAIL 0 on the committed tree; every new number in NEXT_SESSION cites SR5a/SR5b/SR7/SR8.

---

### Task SR10: the MIG's accepted DDR4 periods, and the route to prove the DIMMs calibrate there (Q3) — before any R2 build depends on a UI cut

**Why:** the MIG declares `C0.DDR4_TimePeriod` as a free integer 10..5000 ps (`evidence/qwen9b/ov/n132_sr0_ip_defs.log:8`) and returned no allowed list (`evidence/qwen9b/ov/n131_sr0_ip_query.log:134`); whether any period other than 833 ps validates for the custom part and the 300 MHz refclk, and whether the DIMMs calibrate there, is UNVERIFIED (spec §6 item 7). Q3's ≤ 5 % cut is usable for R2 (SR14) only after this task. **SR7 does not depend on it.**

**Scheduling:** IP validation in a scratch project is light (no synthesis, no implementation); it may run on snoke beside a build.

**Files:** evidence/qwen9b/sr/sr10_mig_period.tcl, evidence/qwen9b/sr/SR10_MIG_PERIOD.md, logs `n1000…`; a scratch project under `synth/out_sr10_mig_probe/` (new; never build_041's project).

- [ ] **Step 1 (read-only on every existing project):** in a new scratch project for `xcvu9p-fsgd2104-2L-e`, instantiate `ddr4` with this design's configuration (the custom part CSV `synth/constraints/BLS4G4D240FSB.csv`, InputClockPeriod 3332, PhyClockRatio 4:1 — the values `n131` read) and, for 833 ps and a ladder of longer periods up to and including the 5 % UI-cut point (the script computes the period for each cut and prints it), `set_property` the period, run `validate_ip` / `generate_target {synthesis instantiation_template}`, and record per period: accepted or the error text, the generated UI clock period and MMCM settings from the generated XDC, and any change of refclk constraint. `n1000`.
- [ ] **Step 2: the calibration route — time-boxed to about one hour of reading.** A period the IP accepts is not a period the DIMMs calibrate at. Look for a **smaller buildable bitstream** that instantiates the four MIGs with this project's DDR4 configuration (first the stage-1 flow, `sw/stage1_hw_bringup.sh` and `evidence/stage1/`; then whether `synth/scripts/create_project.tcl` can build without `layer_0`) and state its build cost. **It does not build or touch the board.** **Default, if none is found in the time box:** the calibration proof is the **first rung of the UI-cut R2 bitstream's own board session** (SR15 step 3: CALIB `0xF`, then `sw/ddr_test.py`, before any weight upload; a failure is the identity-failure path — no DMA, restore build_041, STOP, and R2 at that period is dropped).
- [ ] **Step 3: gate doc + commit.** SR10_MIG_PERIOD.md: the accepted-period table, the UI frequencies they give, the model value of each at R1+R2 from spec §3.2 (only at grid points; no hand interpolation), the calibration route and its cost (or the default), NOT established (calibration itself). spec_cites LAST.

**Acceptance:** a committed table of periods the IP accepts / refuses, generated from Vivado's own validation, and a stated calibration route (found, or the default).

**Does NOT establish:** that the DIMMs calibrate at any new period; timing at that period.

---

### Task SR-ISABITS: repair isa_bits' synthetic ATTN for the spilled KV — rc 0 and a MEANINGFUL negative control (before SR11a)

**Why:** `evidence/qwen9b/g3/isa_bits.py` has not been rc 0 since 75598a9 (2026-09-04, the emitter's DDR state image and the SLD/SST schedule): its synthetic ATTN reads a KV slot the spilled-state emitter now requires to be warm, and dies on `ATTN: KV slot 0 is COLD (E_DMA_COLD)` (`evidence/qwen9b/sr/n209_isa_bits_baseline_32ce34d.log:46-49`, the pre-SR2 control). Its `--negative-control` is uninformative meanwhile: `negative_control` (`evidence/qwen9b/g3/isa_bits.py:936-952`) counts any perturbed run that returns False — or raises — as REFUSED, so every perturbation "passes" by hitting the same assert. SR11a is the first task that changes layer-ARG encodings, so the tool must be a working gate before it.

**Depends on:** nothing. **Log block:** `n1900–n1999` (Global Constraints).

**Files:** Modify `evidence/qwen9b/g3/isa_bits.py`; create evidence/qwen9b/sr/SR_ISABITS.md.

- [ ] **Step 1:** warm the KV slot the synthetic ATTN reads (the emitter's own warm path, not a bypass of the COLD assert) so the unperturbed run is rc 0 on the committed tree. `n1900`.
- [ ] **Step 2:** make the negative control meaningful: a perturbation counts as REFUSED only when it is refused by the check it targets (the unperturbed run must PASS first; a perturbed run that dies on an unrelated assert is a CONTROL FAILURE, named). `n1901`.
- [ ] **Step 3: gate doc + commit**; spec_cites LAST.

**Acceptance:** isa_bits rc 0; `--negative-control` PASS with every perturbation refused by its own check; a deliberately broken control (one perturbation made a no-op) FAILs.

**Does NOT establish:** anything about R2 encodings (SR11a).

---

### Task SR11a: R2 contract, validator and model — B17.2 and running ranges (TDD, gate first)

**Split by controller ruling (the cut is clean):** SR11a owns `docs/SEQ_ISA.md` B17.2, `ref/seq_format.py` and `ref/seq_model.py`; SR11b owns `ref/scripts/reorder_e4.py` and the streams. SR11b consumes SR11a's validator and model unchanged, and the two share no file.

**Files:**
- Modify: `docs/SEQ_ISA.md` B17.2 — spec §1.2's encoding table verbatim (MOVX `target[11:0]` = XWIN start word 0..3071, bank 1 = word 1536; MVGO SHAPE bit 29 = XBANK, bit 30 = RBANK; MOVY `target[15:4]` = RES start row), the range rules (start word + words ≤ 3072; start row + rows ≤ 4096; err 0x06) and the bank-legality rule (K ≤ 6144 for XBANK, nrows ≤ 2048 for RBANK); **forward: NOT fail-closed** on build_041/042 — admission is by the device's caps (B17.0)
- Modify: `ref/seq_format.py` — with `"R2"` in `caps`, admit the three fields with the range and legality refusals; without it, today's refusals stand (MOVY `target[15:4]` non-zero refused; SHAPE bits 29/30 set refused — the validator gains that check so an R2 stream cannot validate on an R1-only device); the SHAPE-spare assert in the model (`ref/seq_model.py:985-986`) admits bits 29/30 only under R2  <!--cites:noquote-->
- Modify: `ref/seq_model.py` — storage as the RTL keeps it: a 12,288-byte x_mem and a 4,096-row RES per channel (`ref/seq_model.py:923-947`, `ref/seq_model.py:1003`); MOVX writes at its start word; MVGO reads x from line 48·XBANK for K/128 lines and writes rows at 2048·RBANK; MOVY reads from its start row; **running ranges** per channel: MVGO refused on any pending stream (one engine); MOVX refused only if its word range overlaps the pending x range; MOVY only if its row range overlaps the pending RES range — every refusal an explicit `raise RunningChannelError` (spec §1.2)
- Create: evidence/qwen9b/sr/sr11a_r2_tdd.py, evidence/qwen9b/sr/SR11a_R2_MODEL.md, logs `n1100–n1149`

- [ ] **Step 1: RED** (spec §4.1 rung 2's synthetic hazards): bank-1 MOVX over a pending bank-1 read → refused; bank-1 MOVX while a bank-0 stream runs → admitted; MOVY over a pending RES range → refused; MOVY on the other half → admitted; XBANK with K = 12288 → refused by the validator; RBANK with nrows 2049 → refused; **an R2 record validated with `caps={"R1"}` → refused** (XBANK MVGO, MOVX start word 1536, MOVY start row 2048 each); with every bank bit and start word zero the model is exactly today's (bit-identical state on the synthetic stream). n1100_RED.log.
- [ ] **Step 2: implement; Step 3: GREEN** `n1101`; selftests (`chat_seq`, boardfree) `n1102–n1103`.
- [ ] **Step 4: the four shipped streams at r0 still 2358/2358 with the range refusals armed** (`n1105–n1108`).
- [ ] **Step 5: gate doc + commit** by explicit paths; spec_cites LAST.

**Acceptance:** RED then GREEN; the caps-keyed refusals hold; shipped streams unchanged at r0; the zero-bank model equals today's.

**Does NOT establish:** any emitted r2 stream (SR11b); the RTL's banks (SR12).

---

### Task SR11b: the R2 pass and the r2 streams

**Files:**
- Modify: `ref/scripts/reorder_e4.py` — `--rtl r2`: schedule with the census's depth-2 buffers and emit the bank the model assigned (MOVX target 0/1536, SHAPE bits 29/30, MOVY target[15:4] 0/2048); elision keyed by channel, source **and bank**; the model node records the bank per MOVY too (spec §1.2 "Emitter / pass" — the census lines it cites); output validated with `caps={"R1","R2"}`; manifest `caps: ["R1","R2"]`
- Modify: `evidence/qwen9b/ov/ov_census.py` — the census node records its bank **per MOVY** too (spec §1.2 "Emitter / pass"; today only MOVX/MVGO carry it, `evidence/qwen9b/ov/ov_census.py:727`, `evidence/qwen9b/ov/ov_census.py:755-756`), so the pass can emit MOVY target[15:4]; the census's own printed R2 makespan must not move (its r = 0 rows reproduced, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:16-19`). SR11a does not touch this file, so the split stays disjoint
- Create: evidence/qwen9b/sr/sr11b_pass_tdd.py, evidence/qwen9b/sr/SR11b_R2_STREAMS.md, logs `n1150–n1199`

- [ ] **Step 1: RED** — at r2 on `reorder_e4._synthetic()`: banks emitted, elision respects the bank, the replay makespan ≤ r1's, the hazard assert and SR11a's model accept the output; r0/r1 outputs byte-identical to SR4's. `n1150`.
- [ ] **Step 2: implement** — first the `evidence/qwen9b/ov/ov_census.py` per-MOVY bank field, then the census re-run on its committed inputs showing the R2 rows unchanged (`n1155`), then the pass; **GREEN** `n1151`; `reorder_e4.py --selftest` + static (`n1152`), `chat_seq --selftest` (`n1153`), boardfree (`n1154`).
- [ ] **Step 3: the r2 streams** `model_9b_s{1..4}_reordB_r2` generated (`n1160–n1163`, sha256 logged) and gated 2358/2358, tokens IDENTICAL (`n1164–n1167`); the pass's r2 makespan beside n120's R1+R2 row (26,146,927 TB cycles, `evidence/qwen9b/ov/n120_sr0_clock_sens.log:18`).
- [ ] **Step 4: gate doc + commit** by explicit paths; spec_cites LAST.

**Acceptance:** RED then GREEN; r2 streams gate 2358/2358 with tokens IDENTICAL; r0/r1 unchanged.

**Does NOT establish:** the chip TB (SR13a).

---

### Task SR12: R2 RTL — the bank bits in `seq_0` and the four `mvchan`s; unit TBs RED → GREEN

**Files (spec §1.2 "RTL", ~40 changed lines over four files):**
- `rtl/seq_unit.sv` — MOVY validator stops refusing `target[15:4]` (`rtl/seq_unit.sv:821`) and adds the start-row range check; MOVY dispatch (`rtl/seq_unit.sv:1102-1110`) passes `mv_row <= r_tgt[15:4]`; MOVX dispatch (`rtl/seq_unit.sv:1082-1092`) passes `mv_xword <= r_tgt[11:0]` with the start-word range check (err 0x06); `SEQ_CAPS` bit r2 set (the literal becomes `0xFAB1CA03`)  <!--cites:noquote-->
- `rtl/seq_movers.sv` — `cmd_row[11:0]`, `cmd_xword[11:0]` ports; MOVY loads `res_row_q` from the command instead of 0 (`rtl/seq_movers.sv:643`; its two uses already consume it, `rtl/seq_movers.sv:781`, `rtl/seq_movers.sv:916-917`); MOVX adds the start word to the XWIN burst base (`rtl/seq_movers.sv:674`), and the sim-only XWIN overflow `$error` includes it  <!--cites:noquote-->
- `rtl/matvec_chan.sv` — the SHAPE write (`rtl/matvec_chan.sv:341-347`) stores bits 29/30 in **`csr_static_xbank` / `csr_static_rbank`** (so the existing quasi-static false path covers them by name, `synth/constraints/fable5_cdc.xdc:14-15`), reset with the other statics (`rtl/matvec_chan.sv:322-323`); header (`rtl/matvec_chan.sv:18`); two new engine inputs
- `rtl/matvec_engine.sv` — **the bank is a reset VALUE of the bare registers, never an adder on their outputs**: `x_line`'s start and row-end assignments (`rtl/matvec_engine.sv:480`, `rtl/matvec_engine.sv:495`) load 48 when XBANK (only bits 5:4 of the constant change; the reset site `rtl/matvec_engine.sv:472` needs none); `row_in`'s start value (`rtl/matvec_engine.sv:481`) loads 2048 when RBANK; the sim-only envelope (`rtl/matvec_engine.sv:716-736`) gains `48 + ng − 1 ≤ 95` when XBANK
- TBs: `tb/tb_matvec.sv`, `tb/tb_matvec_chan.sv` (bank-1 cases: x at line 48, rows at 2048, a MOVX into bank 1 while a bank-0 stream runs — bit-exact); `tb/seq_stub_mvchan.sv` (banks + RES start row, its header `tb/seq_stub_mvchan.sv:30-40`); `tb/scripts/gen_seq_unit_vectors.py` + `tb/tb_seq_unit.sv` (MOVX start word, MOVY start row, the two range errors; **SR3's expected SEQ_CAPS changes from `HW.seq_caps_word({"R1"})` = `0xFAB1CA01` to `HW.seq_caps_word({"R1","R2"})` = `0xFAB1CA03`** — the `caps.hex` side file, never a re-typed literal); `tb/Makefile`  <!--cites:noquote-->
- Create: evidence/qwen9b/sr/SR12_R2_RTL.md, logs `n1200…`

- [ ] **Step 0:** baseline OOC `matvec_chan` at the base commit (`n1200`).
- [ ] **Step 1: RED** — the new unit vectors fail on today's RTL (MOVY start row faults 0x06; the bank-1 matvec results mismatch; SEQ_CAPS reads `0xFAB1CA01` ≠ the new expectation) `n1201`.
- [ ] **Step 2: RTL; Step 3: lint** (`lint_seq_unit`, the matvec lints, `lint_seq_chip_9b`) `n1202`; **GREEN ×4 seeds**: `tb_seq_all`, `tb_matvec`, `tb_matvec_chan` (their Makefile seed variables named in the log) `n1203–n1205`.
- [ ] **Step 4: OOC** `matvec_chan` and `seq_unit` (no new BRAM/URAM/DSP — "no new BRAM", spec §1.2) and `layer_chan` unchanged (182/79/8/1840; SR9: was 182/77/8/1838, pre-T14A, `evidence/qwen9b/g5/G5C_RTL.md:773-777`) `n1206–n1208`.
- [ ] **Step 5: gate doc + commit** by explicit paths; spec_cites LAST.

**Acceptance:** RED then GREEN ×4 seeds on every named TB; zero lint warnings; SEQ_CAPS equals `HW.seq_caps_word({"R1","R2"})`; the new registers are named `csr_static_*` (their false-path coverage is checked on the routed design in SR14); OOC: no new memory/DSP primitives, layer counts exact.

**Does NOT establish:** UI-clock timing (SR14 — the real risk is placement, spec §1.2).

---

### Task SR13a: R2 on the chip TB

**Files:** as SR5a/SR5b (a new `tb/obj_dir_seq_chip_sr13` from the SR12 commit via sr_build.sh), evidence/qwen9b/sr/SR13a_R2_CHIP.md, logs `n1300–n1349`.

- [ ] **Step 1: prediction and bands committed first** — s1's token-4 body window against 26,146,927 cycles (`evidence/qwen9b/ov/n120_sr0_clock_sens.log:18`) with SR5b's ±0.5 % / ±2 % bands; s2–s4 by whole-run ratio to SR5b's r1 cycles for the same seed, within ±0.5 % of s1's ratio, and < 1.
- [ ] **Step 2: rung 1 again on the R2 RTL** — shipped s1..s4 cycles identical to the S4 counts (`evidence/qwen9b/ov/SV1_S1_VERIFY.md:146-148`), tokens IDENTICAL; **and the r1 streams' cycles identical to SR5b's** (R2 must not move R1) — a STOP gate as SR5a.
- [ ] **Step 3: the layer census control** (`evidence/qwen9b/g4/run_g4b_census.sh`, bit-exact; `layer_0` untouched by R2).
- [ ] **Step 4: the r2 streams ×4** — sha256 re-checked against SR11b's logs first; PASS, tokens IDENTICAL; s1 timeline; derive + band verdict for every stream.
- [ ] **Step 5: gate doc + commit**; spec_cites LAST.

**Acceptance:** as SR5a + SR5b, at the R1+R2 prediction; the r1 streams' cycles unchanged by R2; the census bit-exact.

---

### Task SR13b: the host's R2 capability — caps R2 required through the validator path

**Files:** `sw/seq_run.py`, `sw/chat_seq.py` (`--seq-rtl r2`, the r2 per-image pins from a committed run), evidence/qwen9b/sr/sr13b_host_tdd.py, evidence/qwen9b/sr/SR13b_HOST.md, logs `n1350–n1399`. Shares no file with SR13a's sims.

- [ ] **Step 1: RED** — end-to-end through the validator path with SEQ-window mocks: an r2 stream **loads** on a `0xFAB1CA03` mock; is **refused on `0xFAB1CA01`** (R1-only — the not-fail-closed hazard of spec §1.2, caught by the device-keyed validation, not by the manifest) and on `0xDEADC0DE`; **a mislabelled manifest** (an r2 stream whose manifest says `caps: ["R1"]` or `seq_isa: "2.2"`) is still refused on `0xFAB1CA01`; **a missing manifest**: the same r2 stream with no manifest at all is **refused on a `0xFAB1CA01` mock** (no R2 cap) and **accepted on a `0xFAB1CA03` mock** — the validator decides from the records and the device's caps, never from the manifest; `chat_seq --seq-rtl r2` on `0xFAB1CA01` refuses before any upload. Upload tripwire untouched in every refusal. `n1350`.
- [ ] **Step 2: implement; GREEN** `n1351`; selftests + boardfree `n1352–n1354`.
- [ ] **Step 3: gate doc + commit**; spec_cites LAST.

**Acceptance:** every refusal case refused before any DMA; the r2 stream loads only on the R1+R2 mock.

---

### Task SR14: the R2 build — the full drop order; the UI cut only under SR10 + Q3

**Files:** evidence/qwen9b/sr/SR14_R2_BUILD.md, logs `n1400…`, out dirs `synth/out_build_045_r2*` (new); `sw/seq_run.py` `SEQ_VERSIONS` (the R2 row, last step, only for a kept bitstream).

**Steps 1–3 and 6–7** as SR7's (every `synth/scripts/launch_incr.sh` file argument ABSOLUTE, as SR7 step 3 says), with: the reference checkpoint for the incremental run = the R1 signed-off routed checkpoint if SR7 signed off (it carries R1's `seq_0` and the shipped mvchan placement), else the shipped signoff checkpoint — the controller rules at step 1.

- [ ] **Step 4: score** as SR7 step 4, **plus the false-path coverage check** on the routed checkpoint (`n14xx`): `get_cells -hierarchical -filter {NAME =~ */csr_static_xbank_reg* || NAME =~ */csr_static_rbank_reg*}` returns the eight expected register groups (two per `mvchan`), and `report_exceptions` shows them covered by the `csr_static_*` → `mmcm_clkout0*` false path (`synth/constraints/fable5_cdc.xdc:14-15`); `report_timing -from` those cells to the UI clocks reports no timed path. A register not covered is a STOP (fix the name, not the constraint).  <!--cites:noquote-->
- [ ] **Step 5: the order, on a miss — each rung a stop-and-report to the controller:**
  - **A miss on the UI clocks:** (1) the incremental run (step 3) → (2) the four-directive spread with the clock-root XDC (SR7 step 5a's recipe on `build_045_r2`) → (3) **the UI cut ≤ 5 %** (Q3) — **only if SR10 is green**: the MIG accepts the period (SR10 step 1) **and** a calibration route exists (SR10 step 2 — a small calibration bitstream already proven on the board, or the default: the UI-cut R2 bitstream is **kept only if SR15 step 3 proves calibration**); it is a new build (`CONFIG.C0.DDR4_TimePeriod` at `synth/scripts/create_project.tcl:168` changed in a committed, dated edit; a new VERSION); never a full grade (at DDR4-2133 R1+R2 is 8.598 < R1 at full 8.811, spec §3.2); **SR10's result (recorded by SR9, 2026-09-29): the only admissible cut is 877 ps = exactly 5.000 % (UI 285.114 MHz; 938 is refused, 937 is −11.11 %); validate_bd_design at 877 is unproven; the calibration route is the stage-1 design at `35d95a5` with the one-number period edit; `sw/hwmap.py`'s UI_CLK_HZ must become per-VERSION first (`evidence/qwen9b/sr/SR10_MIG_PERIOD.md` §0 items 2–5) — never exercised: SR14 closed at rung 1** → (4) **DROP R2, keep R1.** The drop rule (Q4): R2 is dropped only after the incremental run **and/or** the spread have also missed — a single UI miss is placement luck (spec §1.2) and never drops R2 by itself.
  - **A miss on `xdma_0_axi_aclk` on the R2 netlist:** the spread → **DROP R2 (keep R1), or the user decides.**
  - **SR7C (the compute clock) is NOT on R2's ladder** — only by an explicit user ruling after the controller has informed the user.
  - A waiver, if the user gives one, is this bitstream's own (Q9).

**Acceptance:** SR7's bar, or R2 recorded DROPPED with the incremental/spread evidence that justified it, or the user's ruling.

---

### Task SR15: the R2 board session

As SR8 (the same files pattern, `n1500…`, SR15_R2_BOARD.md), with:
- step 0/1: the control on **build_041** (program it first if the board is on anything else);
- program R2; **identity** with SEQ_CAPS = `HW.seq_caps_word({"R1","R2"})` = `0xFAB1CA03` and CALIB `0xF` — **and, if a UI cut was built, `sw/ddr_test.py` next, before any weight upload** (this is the DIMM-calibration proof of SR10's default route). **Any identity or calibration failure (VERSION, CALIB ≠ `0xF` — an expected risk at a UI cut — SEQ_CAPS, or `ddr_test`) → NO DMA of weights or streams → reprogram build_041 under the safe flow → identity → record → STOP**; a calibration failure at a cut period drops R2 at that period;
- the RD9 rungs as SR8; the bitstream-alone control (r0 / S1-B), the r1 session, then the r2 session, each `--want-ids` fail-closed with counters and `FABLE5_SEQ_EXPECT_VERSION=<R2 hash>`; the stream census against the model's 9.144 (spec §3.1) or, under a UI cut, the spec §3.2 figure at the grid point for that cut;
- **restore build_041, always**, identity, chat sanity; table; gate doc.

**Acceptance / NOT established:** as SR8.

---

### Task SR16: R3 — the decision from silicon (not planned in detail)

**Goal:** a one-document decision, evidence/qwen9b/sr/SR16_R3_DECISION.md, from SR8's and SR15's counters: the measured FENCE-wait and mover shares after R1(/R2) beside the model's R1+R2+R3 prediction (9.920 form B, 9.559 form A, spec §3.1; the least-proven model row, spec §6 item 4) and form (a)'s cost (≈ 45 BD nets per channel and one SLR crossing into SLR0, spec §1.3). If the user takes R3, **form (a), the direct x-push bus** (Q6), gets its own plan written from spec §1.3; this plan stops there. Logs `n1600…`.

---

### Task SR17: docs at the round's close

As SR9 for the R2 outcome and the R3 decision: `NEXT_SESSION.md` §1/§3/§8/§9 (items 10–12), `docs/USAGE.md`, `docs/SEQ_ISA.md` B17.2 as-built (or "not built: dropped at SR14"), the ledger pointer; cite-drift then spec_cites LAST, FAIL 0; commit by explicit paths. Logs `n1700…`.

---

## Open items for the user (non-blocking)

1. The SEQ_CAPS magic `0xFAB1CA` is this plan's choice (the spec fixed only its role); it binds at SR2's commit.
2. Whether SR1's incremental bitstream (if it closes) replaces the waived −0.124 roll as the measurement bitstream — a Q9-style ruling for that bitstream.
3. Whether an R1 bitstream that signs off becomes the resident default (and `--seq-rtl r1` the chat default at 9B `--nch 4`), the way S1D made form B the default — a separate decision after SR8. Until then every session restores build_041.

## Self-review

- **Spec coverage:** §1.1 → SR2 (ISA), SR3 (RTL, unit TB), SR4 (model, pass, cost), SR6 (host); §1.2 → SR11a, SR11b, SR12, SR13a, SR13b; §1.3 → SR16; §1.4 (v2.3, SEQ_CAPS, VERSION) → SR2, SR3, SR6, SR7 step 7, SR13b; §2.3 / D7 → SR7C (Q1) and SR10 + SR14 step 5 (Q3); §3's figures → the predictions in SR5b/SR13a and the board comparisons in SR8/SR15; §4.1 rungs 1–4 → SR4 step 4, SR5a, SR11a step 4, SR13a steps 2–3; §4.2 (ALU) → SR7 step 5c as a fallback, never first; §4.3 → SR1, SR7 step 3, SR14; §4.4 counters → Global Constraints + SR8/SR15; §4.5 order → the task map; §6 items 5–7 → SR1 acceptance 1, SR7C, SR10; §7 answers → the table at the top.
- **The brief's list:** 0 → SR1; 1 → SR3 (+ SR2); 2 → SR4, SR5a, SR5b, SR6; 3 → SR7, SR7C; 4 → SR8; 5 → SR10–SR15; 6 → SR16; 7 → SR9, SR17, the §8 lines at SR5b/SR7, and every task's gate doc.
- **SR2b (review of SR2):** SR6 files + step 3b (serve's `_args()` namespace pin, `seq_rtl`); new task SR-ISABITS (`n1900–n1999`, before SR11a); SR2's acceptance restated (isa_bits out of scope).
- **SR9 (the docs pass, 2026-09-29):** the `layer_chan` OOC acceptance 77/1838 → 182/79/8/1840 in Global Constraints, SR3 steps 5/acceptance and SR12 step 4 (the ledger's SR3 ruling, `evidence/qwen9b/g5/G5C_RTL.md:773-777`; the "n998" fix it was parked for never ran); SR14 step 5's UI-cut rung carries SR10's result. **The plan-fix log block `n990–n999` is closed** (n990–n997 used, n998/n999 never used); `n2000–n2099` became SR11c's block, so a later plan fix takes the next free block (`n2100…`) and says so. — **Fix round 1 (review of `5437f2b`):** I1 → SR7 (no UI cut; no SR10 dependency), Q table; I2 → SR7 step 5 (d′), "skipped only with a recorded reason"; I3/I8 → Global Constraints, SR2 `caps=`, SR6 (the three `validate_stream` sites), SR11a, SR13b; I4 → SR14 step 5; I5 → SR5b step 1, SR13a step 1; I6 → Global Constraints, SR8 step 3, SR15; I7 → SR14 step 4; I9 → SR2 (constants in hwmap; seq_format imports them); m1 → `launch_build.sh:12`; m2 → SR7C `n1800–n1899`; m3 → SR7C "Amend"; m4 → SR13a step 3; m5 → the six clock names; m6 → SR8 files, RD9 rungs, `--want-ids` in step 4, the expect-version table, step 0; m7 → SR15 restore; m8 → SR5b step 6, SR7 step 6; m9 → SR12's `caps.hex`; m10 → SR10 scheduling; splits → SR5a/SR5b, SR11a/SR11b (clean cut), SR13a/SR13b; pre-flight rulings → one CAPS definition, SR5b step 2 sha256 re-check, SR7 without SR10, restore target build_041.
- **Placeholders:** log numbers inside a block (`n71x`, `n78x`, `n9NN`, `n14xx`) are assigned consecutively by the implementer; the R1/R2 VERSION hashes are known only at launch; SR1's incremental directive choices are SR1's. Every other value is exact or cited.
