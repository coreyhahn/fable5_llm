# SR5a — R1 on the chip TB, part 1: backward compatibility cycle-identical, the S1-B control, the layer census

Task SR5a of `docs/superpowers/plans/2026-09-27-seq-rtl-round.md` (task table,
`docs/superpowers/plans/2026-09-27-seq-rtl-round.md:101`). It is a STOP gate.
Before any R1 stream spends chip-TB time, it proves that the R1 RTL runs every
shipped stream and the S1-B control **exactly** as the shipped RTL does
(reordA s1–s4 and reordB s2–s4 did not run). It made no RTL change, ran
no Vivado and took no board action. Every run was on snoke through
`evidence/qwen9b/sr/sr_run.sh`, and every log is in this task's block
`n500–n549`.

**Labels.** **E** = printed by a run of this task, cited to its log line.
**T** = transcribed from an earlier gate, cited to its source.

## Verdict

**GREEN on every acceptance item. There is nothing to STOP on.**

* **Rung 1, backward compatibility.** The four shipped streams `model_9b_s1..s4`
  run on the R1 binary with `TB_SEQ_CHIP PASS`, tokens IDENTICAL, and cycles
  **identical to the cycle** to S4's 196,706,821 / 196,707,670 / 196,707,670 /
  196,706,833 (§2).
* **The S1-B control.** `model_9b_s1_reordB` runs on the R1 binary in
  **171,731,320 cycles, equal to SV1's to the cycle**, with tokens IDENTICAL (§3).
* **The layer census control.** 56,576 commands and 8,600,034 checks, bit-exact.
  The per-opcode table is **byte-identical** to T14A's `evidence/qwen9b/s4/census_t14a.txt` (§4).

A mask-0 FENCE walks the same F_SCAN, one channel per cycle
(`docs/superpowers/plans/2026-09-27-seq-rtl-round.md:187`). This gate measures
that at the chip level: 5 of 5 streams, 0 cycles of difference.

## 1. The binary

| item | value | cite |
|---|---|---|
| named RTL commit | `5c369c2`, the SR3 green-gate commit ("rtl(SR3): R1 FENCE channel mask …") | **E**, `evidence/qwen9b/sr/n500_build_sr5.log:7` |
| RTL delta vs the shipped 86c94d9 | `rtl/seq_unit.sv` +147, `rtl/seq_movers.sv` +16/−, `rtl/matvec_chan.sv` +11, the two IPI wrappers, and the TBs | **E**, `evidence/qwen9b/sr/n500_build_sr5.log:7-17` |
| RTL delta 5c369c2 → HEAD at build time | `rtl/layer_chan.sv` 2 lines and `rtl/state_dma.sv` 4 lines, **comments only** (SR3c's citation re-point, 1a1c394) | **E**, `evidence/qwen9b/sr/n500_build_sr5.log:18-21` |
| identity | 63 rtl/ + tb/*.sv[h] files in the `git archive` snapshot, each byte-identical to 5c369c2's blob | **E**, `evidence/qwen9b/sr/n500_build_sr5.log:22` |
| binary | `tb/obj_dir_seq_chip_sr5/tb_seq_chip_9b_sr5`, sha256 **f7b64e5a1c39503371db0cee64ceedb363b56a4cc7e8d2fadb9b31c7acc0353e** | **E**, `evidence/qwen9b/sr/n500_build_sr5.log:71` |
| recipe | the census recipe `tb_seq_chip_9b_tl_build` with `TL_MDIR`/`TL_BIN` (`evidence/qwen9b/sr/sr_build.sh:76`), as SV1's; -Wall clean (the build completed) | **E**, `evidence/qwen9b/sr/n500_build_sr5.log:69` |

**SR5b uses this binary unchanged.** Every run below prints the same sha256 on
its line 7 (for example `evidence/qwen9b/sr/n514_chip_s1_reordB_control.log:7`).

**The scripts.** `evidence/qwen9b/sr/sr_build.sh` is a copy of
`evidence/qwen9b/ov/sv1_build.sh`. Its identity check changed from "rtl/ equals
the shipped 86c94d9" to "rtl/ and tb/*.sv[h] in the snapshot equal the named
commit's blobs". It also checks the file list, prints both deltas for the
record, and refuses an existing obj_dir.
`evidence/qwen9b/sr/run_sr_chip.sh` is a copy of
`evidence/qwen9b/ov/run_sv1_chip.sh` with `--cycles-equal <N>` added
(`evidence/qwen9b/sr/run_sr_chip.sh:45`), which FAILS on any difference
(`evidence/qwen9b/sr/run_sr_chip.sh:179`).

**The runner's acceptance logic was checked first**, by judging a committed
BM1 control seed log with no simulation (`DRYLOG`):
* GREEN: right cycles, right record → PASS (**E**,
  `evidence/qwen9b/sr/n504_runner_dry_GREEN.log:38`);
* RED: reference off by one cycle → `CYCLES DIFFER … delta -1` and FAIL (**E**,
  `evidence/qwen9b/sr/n505_runner_dry_RED_cycles.log:32`,
  `evidence/qwen9b/sr/n505_runner_dry_RED_cycles.log:38`);
* RED: the wrong token record → `TOKENS DIFFER` and FAIL (**E**,
  `evidence/qwen9b/sr/n506_runner_dry_RED_tokens.log:35`,
  `evidence/qwen9b/sr/n506_runner_dry_RED_tokens.log:38`).

## 2. Rung 1 — the four shipped streams on the R1 RTL

Scope: every shipped stream and the S1-B control (§3); reordA s1–s4 and
reordB s2–s4 did not run on the R1 binary.

Streams: the gitignored, regenerable `tb/scripts/w9/model_9b_s{1..4}.e4.*`.
Each `.seq` sha256 printed by the run (line 8 of each log) equals the one
SR4's r0 gate printed for the same stream (**T**,
`evidence/qwen9b/sr/n405_gate_shipped_s1_r0.log:7`,
`evidence/qwen9b/sr/n406_gate_shipped_s2_r0.log:7`,
`evidence/qwen9b/sr/n407_gate_shipped_s3_r0.log:7`,
`evidence/qwen9b/sr/n408_gate_shipped_s4_r0.log:7`).

| seed | .seq sha256 | TB_SEQ_CHIP | cycles (R1 RTL) | reference (S4) | Δ | tokens | wall | verdict |
|---|---|---|---|---|---|---|---|---|
| s1 | 9760899d… (`evidence/qwen9b/sr/n510_chip_s1_compat.log:8`) | PASS (`evidence/qwen9b/sr/n510_chip_s1_compat.log:29`) | **196,706,821** (`evidence/qwen9b/sr/n510_chip_s1_compat.log:31`) | 196,706,821 | **0** | IDENTICAL (`evidence/qwen9b/sr/n510_chip_s1_compat.log:34`) | 8,806 s | PASS (`evidence/qwen9b/sr/n510_chip_s1_compat.log:37`) |
| s2 | dae58734… (`evidence/qwen9b/sr/n511_chip_s2_compat.log:8`) | PASS (`evidence/qwen9b/sr/n511_chip_s2_compat.log:29`) | **196,707,670** (`evidence/qwen9b/sr/n511_chip_s2_compat.log:31`) | 196,707,670 | **0** | IDENTICAL (`evidence/qwen9b/sr/n511_chip_s2_compat.log:34`) | 8,834 s | PASS (`evidence/qwen9b/sr/n511_chip_s2_compat.log:37`) |
| s3 | 8dfad7db… (`evidence/qwen9b/sr/n512_chip_s3_compat.log:8`) | PASS (`evidence/qwen9b/sr/n512_chip_s3_compat.log:29`) | **196,707,670** (`evidence/qwen9b/sr/n512_chip_s3_compat.log:31`) | 196,707,670 | **0** | IDENTICAL (`evidence/qwen9b/sr/n512_chip_s3_compat.log:34`) | 8,689 s | PASS (`evidence/qwen9b/sr/n512_chip_s3_compat.log:37`) |
| s4 | 3483d82a… (`evidence/qwen9b/sr/n513_chip_s4_compat.log:8`) | PASS (`evidence/qwen9b/sr/n513_chip_s4_compat.log:29`) | **196,706,833** (`evidence/qwen9b/sr/n513_chip_s4_compat.log:31`) | 196,706,833 | **0** | IDENTICAL (`evidence/qwen9b/sr/n513_chip_s4_compat.log:34`) | 8,969 s | PASS (`evidence/qwen9b/sr/n513_chip_s4_compat.log:37`) |

References: S4's cycles and token records (**T**,
`evidence/qwen9b/s4/S4_REPLAY.md:398-401`), as SV1 quotes them (**T**,
`evidence/qwen9b/ov/SV1_S1_VERIFY.md:146-148`). The runner reads the token
record out of `evidence/qwen9b/s4/S4_REPLAY.md` itself; the matched record is
printed on line 33 of each log. Wall times are on line 14. `TB_SEQ_CHIP PASS`
also compares the full architectural end state against the stream's golden
`.chip` (scratch, XRF, TCNT, the 112 state blocks), as in every earlier chip
replay.

## 3. The S1 control — the shipped reorder, form B, on the R1 RTL

| stream | .seq / .chip sha256 | cycles (R1 RTL) | reference (SV1, shipped RTL) | Δ | tokens | wall | verdict |
|---|---|---|---|---|---|---|---|
| `model_9b_s1_reordB` | 57ec3051… / 34b0b553… (`evidence/qwen9b/sr/n514_chip_s1_reordB_control.log:8`); = SV1's (**T**, `evidence/qwen9b/ov/n53_chip_s1_reordB_control.log:29`) | **171,731,320** (`evidence/qwen9b/sr/n514_chip_s1_reordB_control.log:31`) | 171,731,320 (**T**, `evidence/qwen9b/ov/n53_chip_s1_reordB_control.log:51`) | **0** | IDENTICAL to the shipped s1 record (`evidence/qwen9b/sr/n514_chip_s1_reordB_control.log:34`) | 7,934 s | PASS (`evidence/qwen9b/sr/n514_chip_s1_reordB_control.log:37`) |

The stream defers 200 fences per token (**T**,
`evidence/qwen9b/ov/n32_reorder_s1_B.log:44`), and it runs on the new RTL in exactly the
cycles it ran on the old RTL. Every FENCE in it is mask 0, and every one drains
all four channels as before (inferred from the stream format and the cycle
identity, not observed FENCE by FENCE).

## 4. The layer census control

`layer_0` is untouched by R1. The census is the control that shows it:

* **Bit-exact.** `TB_LAYER_CENSUS PASS: 56576 cmds, 8600034 checks bit-exact`
  (**E**, `evidence/qwen9b/sr/n520_layer_census_sr5.log:76`); the header line
  reads `commands=56576 checks=8600034 errors=0` (**E**,
  `evidence/qwen9b/sr/n520_layer_census_sr5.log:40`). This is the check count
  T14A reported (**T**, `evidence/qwen9b/g5/081_t14a_census.log:23`,
  `evidence/qwen9b/g5/081_t14a_census.log:59`).
* **The whole per-opcode table is byte-identical to T14A's.** Both
  `evidence/qwen9b/s4/census_sr5.txt` and `evidence/qwen9b/s4/census_t14a.txt`
  have sha256 98b9451c…, and `cmp` agrees (**E**,
  `evidence/qwen9b/sr/n521_census_table_vs_t14a.log:9`). Every per-opcode
  count, mean, min and max and every per-step total is unchanged. The layer
  sources changed since T14A's 1dd2889 only in comments (re-pointed citation
  line numbers in `rtl/layer_chan.sv`, `rtl/state_dma.sv` and the census TB;
  the stat is printed by the same log).
* Wall 3,835 s (**E**, `evidence/qwen9b/sr/n520_layer_census_sr5.log:78`).

## 5. Parallelism and memory

The five chip runs, the census and the memory watcher ran in parallel, beside
SR1's detached Vivado job. At launch there was 213 GiB available. The five chip
processes peaked at **0.327 GiB total RSS** (**E**,
`evidence/qwen9b/sr/n515_memwatch_sr5.log:47`).

## 6. Judgment calls and deviations, each recorded

1. **Built from 5c369c2, not HEAD.** The brief says "from the SR3 commit". HEAD's
   rtl/ differs from it in comments only (§1). The chip binary is therefore the
   SR3 RTL exactly. Any later build of HEAD's tree carries the same logic.
2. **The census runner.** The plan names `evidence/qwen9b/g4/run_g4b_census.sh`.
   That script is SUPERSEDED and refuses to run
   (`evidence/qwen9b/g4/run_g4b_census.sh:52`). Its own banner names
   `evidence/qwen9b/s4/run_s4_census.sh` instead. I ran that, with G5C's exact
   invocation (the command line of `evidence/qwen9b/g5/081_t14a_census.log:4`),
   in draining mode at LAT=8.
   * The census builds from the working tree's rtl/, not from a snapshot. Its
     guard refuses a dirty rtl/, and the tree was 2f5b213 with rtl/ clean
     (**E**, `evidence/qwen9b/sr/n520_layer_census_sr5.log:2`).
   * None of SR3's edited files are in the census's layer file list.
3. **The census table lands in `evidence/qwen9b/s4/`.** The S4 runner hard-codes
   `census_<cfg>.txt` beside itself. `evidence/qwen9b/s4/census_sr5.txt` is a
   declared one-file extension of this task's commit block, as G5C's was
   (`evidence/qwen9b/g5/G5C_RTL.md:999`).
4. **Seed logs are flat files** `evidence/qwen9b/sr/sr5_seed_<stream>_control.log`,
   not a `seedlogs_` directory. `sr_run.sh` excludes only untracked `*.log`
   files directly under `evidence/qwen9b/sr/` from its dirty stamp, so a
   directory would have stamped every parallel sibling run +dirty.
5. **`sr_build.sh` takes an optional task number** `[k]` (default 5), so later
   tasks can reuse it for `obj_dir_seq_chip_sr<k>`.
6. **n501–n503 are failed attempts, kept.** `DRYLOG` was given as a relative
   path, and the runner `cd`s into `tb/` before copying it. The copy failed,
   so all three judged an empty log. n504–n506 are the same checks with an
   absolute path. n501/n502 are also stamped +dirty by another task's
   in-flight `ref/seq_model.py` edit, which is not an input to any chip run.
7. **spec_cites.** The first run, n530, found FAIL 1: a bare file name census_t14a.txt
   in the verdict, which it read as a path. That is repaired, and the run of
   record is n531, LAST and alone on the committed tree.
8. **The shipped streams' `.chip` goldens have no earlier committed sha256.**
   The ones measured here are on line 8 of n510–n513. The `.seq` hashes match
   SR4's (§2), and the reordB `.seq` and `.chip` match SV1's (§3).

## 7. What this does NOT establish

* That a **masked** FENCE behaves on the chip TB. No r1 stream was run; that is
  SR5b, after this gate is reviewed.
* Timing, OOC counts or any board behaviour of the R1 netlist (SR7 onward).
* **Caveats.** The binary is built from 5c369c2, whose delta to HEAD at build
  time is comment-only (§1); there was one TB build; and
  `evidence/qwen9b/s4/census_sr5.txt` is a declared one-file extension of
  this task's commit block under `evidence/qwen9b/s4/` (§6 item 3).

## 8. Logs

| log | what |
|---|---|
| `evidence/qwen9b/sr/n500_build_sr5.log` | the binary |
| `evidence/qwen9b/sr/n501_runner_dry_GREEN.log`, `evidence/qwen9b/sr/n502_runner_dry_RED_cycles.log`, `evidence/qwen9b/sr/n503_runner_dry_RED_tokens.log` | failed attempts (relative DRYLOG), kept |
| `evidence/qwen9b/sr/n504_runner_dry_GREEN.log`, `evidence/qwen9b/sr/n505_runner_dry_RED_cycles.log`, `evidence/qwen9b/sr/n506_runner_dry_RED_tokens.log` | runner acceptance GREEN / RED / RED |
| `evidence/qwen9b/sr/n510_chip_s1_compat.log` … `evidence/qwen9b/sr/n513_chip_s4_compat.log` | rung 1 |
| `evidence/qwen9b/sr/n514_chip_s1_reordB_control.log` | the S1-B control |
| `evidence/qwen9b/sr/n515_memwatch_sr5.log` | memory |
| `evidence/qwen9b/sr/n520_layer_census_sr5.log`, `evidence/qwen9b/sr/n521_census_table_vs_t14a.log` | the layer census control |
| `evidence/qwen9b/sr/sr5_seed_model_9b_s1_control.log` (and s2/s3/s4, s1_reordB) | the simulators' own stdout |
