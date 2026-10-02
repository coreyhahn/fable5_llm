# R3-0 — the tooling the R3 build and board session run under

Task R3-0 of the R3 campaign (MOVX broadcast, form (a); plan
`docs/superpowers/plans/2026-09-29-r3-broadcast.md`, Task R3-0). It closes
four items of the round's ten-item tooling backlog (`NEXT_SESSION.md` §9 (f)
item 11, entries 3, 4, 6 and 8; `evidence/qwen9b/sr/SR17_ROUND_CLOSE.md` §5).
The backlog entry in `NEXT_SESSION.md` is marked DONE by R3-12, not by this
task.

**There was no board, no real project and no DMA.** Every test ran against
mocks, stubs, tripwires, scratch clones or a ONE-FLOP fake Vivado project.
Neither `sw/program_fpga.sh` nor `sw/pcie_helper.sh` touched the board, and
no launcher ran against a real design. Every run was on snoke through
`evidence/qwen9b/sr/sr_run.sh`, in log block n2200–n2299.

**Verdict.**
* **(i) `sw/program_fpga.sh --expect-sha256 <hex>` and `--check-only`.** Two
  checks now run inside the lock hold, before `[1/3] remove`. First, the bit
  file's sha256 must equal the named one: a mismatch exits 5. Second, for
  every caller, no ESTABLISHED client may be attached to hw_server port 3121:
  one attached exits 6. Nothing is removed either way.
* **(ii) The synth-only launch.** `SYNTH_ONLY=1 synth/scripts/launch_build.sh`
  passes build.tcl a second word `synth_only`. It stops after synth_1 and
  does not run impl_1 or write a bitstream. The resulting project is IDLE to
  `synth/scripts/proj_busy.sh`, and `synth/scripts/launch_incr.sh` accepts it.
* **(ii) The post-impl sanity block.** It is now two procs in
  `synth/scripts/postimpl_sanity.tcl`. build.tcl's printed lines and their
  order are the same as c5f255d's, and the procs also run read-only on a
  routed checkpoint.
* **(iii) `evidence/qwen9b/sr/r3_preflight.sh`.** It FAILS on a dirty tree,
  and every per-session value is an argument. The root and every board or
  lock probe, the interpreter included, can be overridden.
* **(iv) `evidence/qwen9b/g6/g6_state.py`.** It refuses with exit 4, before
  any DMA, unless the board's VERSION equals the VERSION `sw/seq_run.py`
  would expect.
* **Test-first.** Tests committed at `3368d06`. RED was **54 passed /
  83 failed**
  (`evidence/qwen9b/sr/n2200_r3_0_RED.log:454`). GREEN, on the clean tree
  `c2fdfb3`, was **137 passed / 0 failed**
  (`evidence/qwen9b/sr/n2214_r3_0_GREEN.log:882`).
* **No-flag behaviour unchanged**, shown by five checks (§4).
* **Regressions unchanged** (§5): seq_run 2840/0; boardfree 2840/0, 85/0,
  407/1 [22]; SR6 45/0; SR7 36/0; SR13b 42/0; SR11a fix2 12/0 and fix3 8/0;
  hwmap PASS; SR14 ident_expect 6/0; the launcher guard check 13/0.

## 1. What changed, by line

Commits: `0a85d3a` (i), `2e73bf5` (ii), `0fd3975` (iii), `ef778b7` (iv).

**(i) `sw/program_fpga.sh`** (and `docs/USAGE.md` §2)

| what | where |
|---|---|
| the new flags and the client refusal, documented in the header | `sw/program_fpga.sh:39-53` |
| the argument loop consumes option VALUES in both spellings, space and `=`. A value that is not 64 hex digits, a missing value, or more than one positional exits 2, before the lock. Upper-case hex is folded to lower case | `sw/program_fpga.sh:54-82` |
| the lock re-exec passes the ORIGINAL argv. The loop now shifts its arguments, so passing them on as before would lose them | `sw/program_fpga.sh:93-94` |
| inside the lock, after the EXIT trap (with NEED_RESCAN still 0) and before `[1/3] remove`: it prints the bitfile and the expected hash, runs sha256sum (`FATAL: sha256 mismatch`, exit 5; an unreadable file also exits 5), then runs the `ss` client check (`FATAL: a client is attached to hw_server`, exit 6; if `ss` itself fails, that is also exit 6), then `--check-only` exits 0 | `sw/program_fpga.sh:127-158` |
| `[1/3] remove`, unchanged, follows | `sw/program_fpga.sh:160-161` |
| the operator's guide | `docs/USAGE.md` §2, the paragraph "Name the file you mean" |

**(ii) the synth-only launch and the sanity procs**

| what | where |
|---|---|
| the optional second word `synth_only`; any other word is FATAL | `synth/scripts/build.tcl:13-22` |
| the sanity procs are sourced with -notrace inside `must`, so a missing file is a FATAL before any run | `synth/scripts/build.tcl:30` |
| after synth_1 reaches 100 %: print SYNTH_OK and the synth_1 checkpoint, close the project, exit 0. There is no `launch_runs impl_1` | `synth/scripts/build.tcl:42-47` |
| site 1, the clock gate: now a proc call | `synth/scripts/build.tcl:60` |
| site 2, the PCIE_LOC / GT_LOC print: now a proc call | `synth/scripts/build.tcl:75` |
| `postimpl_clock_gate`: site 1's block verbatim, reporting to the report directory it is given | `synth/scripts/postimpl_sanity.tcl:23-36` |
| `postimpl_loc_print`: site 2's block verbatim | `synth/scripts/postimpl_sanity.tcl:40-46` |
| SYNTH_ONLY: 1 passes the word; unset or 0 passes the same argv as before; any other value is refused with exit 2, before the out dir exists | `synth/scripts/launch_build.sh:18-26` |
| build.tcl gets the argument array | `synth/scripts/launch_build.sh:43` |
| synth-only mode: require the anchored SYNTH_OK line, print SYNTH DONE, exit 0 | `synth/scripts/launch_build.sh:45-49` |

`synth/scripts/launch_build.sh:12` (VERSION) and
`synth/scripts/launch_build.sh:14-17` (the out-dir refusal) did not move.
Those are the launcher's most-cited lines (31 and 27 citations).

**(iii) `evidence/qwen9b/sr/r3_preflight.sh`** (new;
`evidence/qwen9b/sr/sr15_preflight.sh` is not edited)

| what | where |
|---|---|
| header: the changes from sr15, the probe variables with their defaults (sr15's commands), and the usage | `evidence/qwen9b/sr/r3_preflight.sh:1-45` |
| the per-session defaults: build_041's path, size and sha, identity c973c18a, session-log prefix n33 | `evidence/qwen9b/sr/r3_preflight.sh:47-56` |
| every value is validated before anything runs: each sha is a FULL 64-hex value, sizes are byte counts, VERSIONs are 8 hex digits | `evidence/qwen9b/sr/r3_preflight.sh:84-95` |
| the probes: each is DEFAULT or OVERRIDE, and PF_PY is overridable too (the controller addendum: a tripwire python on PATH cannot intercept an absolute interpreter) | `evidence/qwen9b/sr/r3_preflight.sh:99-113` |
| the probe table printed at [0] | `evidence/qwen9b/sr/r3_preflight.sh:119-120` |
| the identity read (PASS still requires build_041's identity unless another is named) | `evidence/qwen9b/sr/r3_preflight.sh:143-144` |
| **the clean-tree check**: any modified or untracked entry FAILS, naming the tree and the entries; the only exclusion is the session's own untracked n33NN logs | `evidence/qwen9b/sr/r3_preflight.sh:198-206` |

**(iv) `evidence/qwen9b/g6/g6_state.py`**

| what | where |
|---|---|
| main's blank line 126 now resolves the expected VERSION. The helper refuses an unknown name with exit 4 before the lock and before the device is opened | `evidence/qwen9b/g6/g6_state.py:126` |
| the Dev line, unmoved (cited ten times across the documents, the plan included) | `evidence/qwen9b/g6/g6_state.py:134` |
| after the board print and before any DMA: exit 4 unless the board's VERSION equals the expected one | `evidence/qwen9b/g6/g6_state.py:138-145` |
| `r3_expect_version()` calls `SR.resolve_expect_version()` (`sw/seq_run.py:236`): the environment variable if set, else the shipped 0xC973C18A | `evidence/qwen9b/g6/g6_state.py:176-189` |

## 2. The tests and the tripwires

`evidence/qwen9b/sr/r3_tool_tdd.sh` (cases (a)…(e), plus the (n0) control)
and `evidence/qwen9b/sr/r3_g6state_tdd.py` (case (f)) were committed at
`3368d06`, before any implementation. The one-flop fake project is
`evidence/qwen9b/sr/r3_synthonly_probe.tcl`. Each file's header lists its
cases and its RED prediction.

* **program_fpga cases.** PATH's first entry holds tripwire stubs for `sudo`
  and `vivado`: each records its argv and exits 97. It also holds a stub
  `ss`, scripted to report either no client or one ESTABLISHED :3121 client.
  The harness first asserts that `command -v` resolves each name to its stub
  (`evidence/qwen9b/sr/n2214_r3_0_GREEN.log:8-11`). `FABLE5_BOARD_LOCK` is a
  scratch file, and every case runs under strace. A case fails if strace
  shows the real `.fable5_board.lock` opened or `sw/pcie_helper.sh`
  exec'd. It must show the scratch lock opened, which proves the checks ran
  inside a lock hold. The script sources the real settings64.sh only after
  `[1/3] remove`, and the stub sudo fails that step, so no case can reach
  the real vivado. `--jtag-only` is never run.
* **Vivado cases.** These run the real Vivado on the one-flop project only.
  The project has a 4.000 ns clock on a clock-capable pair and constrained
  IO, as the addendum asks. Two things run on it:
  * the direct build.tcl `synth_only` run in
    `synth/out_r3_synthonly_probe_<tag>/`;
  * four scratch roots under its `roots/`. Each is a git-initialised copy of
    the launcher and build.tcl, with the probe standing in as
    create_project.tcl. The `old_noflag` root carries c5f255d's launcher and
    build.tcl, the baseline for the no-flag comparison.
* **Pre-flight cases.** `--root` points at a `git clone --shared` of the
  repo. Every probe variable points at a logging stub, including a scripted
  build_041 identity. PF_PY and PATH carry a tripwire python, which fails
  any call naming sr8_ident, xdma or board_lock and passes everything else
  to the shipped venv. strace must show no openat of a `/dev/xdma*` node, no
  sr8_ident.py, and no exec of the real lspci / lsmod / ss / pgrep
  (`evidence/qwen9b/sr/n2214_r3_0_GREEN.log:412-419`).
* **g6_state cases.** They use SR6's mock pattern: the real `Dev` with a
  scripted identity, and tripwires on every write and DMA method. `os.open`
  is guarded against any xdma path, the lock is a scratch file, and each case
  runs in its own child process. A refusal counts only when g6_state's own
  "REFUSING the state-region DMA" line is printed, because a board-lock
  refusal also exits 4.

## 3. RED and GREEN

| case | RED n2200 | GREEN n2214 |
|---|---|---|
| (H) harness stubs first | 3 / 0 | 3 / 0 |
| (a) wrong sha → exit 5 | 3 / 4 | 7 / 0 |
| (a′) value binding, malformed values | 6 / 18 | 24 / 0 |
| (b) client → exit 6 | 3 / 4 | 7 / 0 |
| (b′) wrong sha and a client → 5 | 4 / 2 | 6 / 0 |
| (b″) no flag, a client → 6 | 3 / 2 | 5 / 0 |
| (c) --check-only | 3 / 5 | 8 / 0 |
| (n0) no-flag control | 6 / 0 | 6 / 0 |
| (c′) the factored sanity block | 8 / 3 | 11 / 0 |
| (d) synth-only | 8 / 12 | 20 / 0 |
| (e) pre-flight | 2 / 26 | 28 / 0 |
| (f) g6_state | 5 / 7 | 12 / 0 |
| **total** | **54 / 83** | **137 / 0** |

Sources: `evidence/qwen9b/sr/n2200_r3_0_RED.log:442-454` and
`evidence/qwen9b/sr/n2214_r3_0_GREEN.log:870-882` (passed / failed).

**RED as predicted.** In RED, every behaviour check of (a)…(c), (c′), (d),
(e), and f1, f4, f5 and f6 failed.
* c5f255d's argument loop took the hex as the bitfile, and every
  program_fpga case walked into the stub sudo's `remove` and `rescan`. The
  tripwire recorded the dangerous path without touching anything real.
* c5f255d's build.tcl ignored `synth_only`: impl_1 ran and wrote a .bit.
* In f4 the unknown name raised ValueError out of Dev's own resolve, not
  exit 4.

The checks that passed in RED are the harness's own safety sub-checks (the
real lock never opened, pcie_helper.sh never exec'd), (n0), and (c′)'s
comparisons, where both roots ran c5f255d code. So did (d)'s checks that
synth_1 finished, that the project was PROJ_IDLE and that launch_incr
accepted it; all three pass after a full run too. f2 and f3 passed as
well. These are the passes the header predicted.

**GREEN highlights (n2214):**
* build.tcl's printed lines and their order are IDENTICAL to c5f255d's
  (`evidence/qwen9b/sr/n2214_r3_0_GREEN.log:243`), and so is the launcher's
  build.log (`evidence/qwen9b/sr/n2214_r3_0_GREEN.log:246`).
* The procs, run READ-ONLY on the routed checkpoint, print the build's
  CLOCK_GATE_OK line and write the same no-clock report body
  (`evidence/qwen9b/sr/n2214_r3_0_GREEN.log:304-305`).
* The synth-only project shows impl_1 "Not started", a synth_1 PROGRESS of
  100 %, PROJ_IDLE, and launch_incr accepting it
  (`evidence/qwen9b/sr/n2214_r3_0_GREEN.log:312-323`).
* SYNTH_ONLY=yes is refused with exit 2
  (`evidence/qwen9b/sr/n2214_r3_0_GREEN.log:332`).
* A dirty clone FAILS, naming the tree and the file
  (`evidence/qwen9b/sr/n2214_r3_0_GREEN.log:619-620`).
* g6_state: f1 through f6 behave as specified
  (`evidence/qwen9b/sr/n2214_r3_0_GREEN.log:857-867`).

**Recorded by case (c′), not a defect.** The one-flop project has no
PCIE4 or GTYE4 cell. So `postimpl_loc_print` runs and prints empty lists,
both before and after the change. The PCIE_LOC and GT_LOC lines are first
exercised on a real netlist at R3-10.

**The Vivado command trace.** The '# ' command-trace lines that differ from
c5f255d's are logged in `evidence/qwen9b/sr/n2214_r3_0_GREEN.log:259-301`,
with Vivado's own session-header lines left out. They are exactly the
factored blocks, the new argument parse and the synth_only branch.

## 4. No-flag behaviour

1. **program_fpga, no flag (n0).** It reaches `[1/3] remove` as before. The
   stub sudo received exactly the `remove` and then the trap's `rescan`, and
   vivado was never reached
   (`evidence/qwen9b/sr/n2214_r3_0_GREEN.log:159-175`). The default path
   prints two new lines, `=== [0/3] bitfile: …` and the "no client
   attached" line. It also refuses an attached :3121 client, on every
   caller, as the plan directs (b″); the controller addendum records this
   as FYI.
2. **The launcher and build.tcl, no flag (c′).** The launcher passes build.tcl
   the one word, as before. The printed lines, the build.log and the no-clock
   report are identical to c5f255d's.
3. **The existing launcher guard (SR7's n757).** It ran unchanged:
   `evidence/qwen9b/sr/sr7f1_guard_check.sh` gave 13 / 0
   (`evidence/qwen9b/sr/n2224_r3_0_guard_check_noflag.log:38`), as at
   `evidence/qwen9b/sr/n757_SR7fix1_guard_check.log:38`. It ran proj_busy
   and `LAUNCH_INCR_CHECK_ONLY=1` read-only, and launched nothing.
4. **g6_state with no variable on build_041 (f3)** proceeds to the write
   as before.
5. **`evidence/qwen9b/sr/sr15_preflight.sh`** is not edited. Its outputs
   are unchanged by construction; the new pre-flight is a separate file.

## 5. Regressions

| run | this task | baseline |
|---|---|---|
| `sw/seq_run.py --selftest` | 2840 / 0 (`evidence/qwen9b/sr/n2215_r3_0_seq_run_selftest.log:55`) | 2840 / 0 (`evidence/qwen9b/sr/n1722_sr17ff_seq_run_selftest.log:55`) |
| boardfree: serve | 85 / 0 (`evidence/qwen9b/sr/n2216_r3_0_boardfree.log:107`) | 85 / 0 (`evidence/qwen9b/sr/n1725_sr17ff_boardfree.log:107`) |
| boardfree: chat_seq | 407 / 1, the [22] baseline (`evidence/qwen9b/sr/n2216_r3_0_boardfree.log:138`) | 407 / 1 (`evidence/qwen9b/sr/n1723_sr17ff_chat_seq_selftest.log:35`) |
| SR6 host TDD | 45 / 0 (`evidence/qwen9b/sr/n2217_r3_0_sr6_host_tdd.log:133`) | 45 / 0 (`evidence/qwen9b/sr/n1450_SR14f1_sr6_host_tdd.log:133`) |
| SR7 host TDD | 36 / 0 (`evidence/qwen9b/sr/n2218_r3_0_sr7_host_tdd.log:55`) | 36 / 0 (`evidence/qwen9b/sr/n1451_SR14f1_sr7_host_tdd.log:50`) |
| SR13b host TDD | 42 / 0 (`evidence/qwen9b/sr/n2219_r3_0_sr13b_host_tdd.log:122`) | 42 / 0 (`evidence/qwen9b/sr/n1452_SR14f1_sr13b_host_tdd.log:117`) |
| SR11a fix2 / fix3 | 12 / 0, 8 / 0 (`evidence/qwen9b/sr/n2220_r3_0_sr11afix2_tdd.log:62`, `evidence/qwen9b/sr/n2221_r3_0_sr11afix3_tdd.log:31`) | 12 / 0, 8 / 0 (`evidence/qwen9b/sr/n1453_SR14f1_sr11afix2_tdd.log:62`, `evidence/qwen9b/sr/n1454_SR14f1_sr11afix3_tdd.log:31`) |
| hwmap selftest | PASS (`evidence/qwen9b/sr/n2222_r3_0_hwmap_selftest.log:7`) | PASS |
| SR14 ident_expect | 6 / 0 (`evidence/qwen9b/sr/n2223_r3_0_sr14_ident_expect.log:68`) | 6 / 0 (`evidence/qwen9b/sr/n1443_SR14_ident_expect.log:68`) |
| bash -n / py_compile on every edited script | OK (`evidence/qwen9b/sr/n2204_r3_0_bash_n.log`) | — |

**Tree stamps.**
* n2214–n2217 ran on the clean tree `c2fdfb3`, and n2220–n2221 on the
  clean tree `213ade7`.
* n2218–n2219 and n2222–n2224 carry `+dirty`. In every case the dirty
  entries are OTHER tasks' in-flight edits: R3-3/R3-4's plan and doc edits,
  and R3-2's `r3_2_gate_compare.sh`. Each log lists them, and none is an
  input of those runs.
* R3-0's own files were all committed before either round.
* The host TDDs ran at `FABLE5_MODEL=9b FABLE5_RS_F=7`, their operating
  point, as SR14f1 ran them.

## 6. Judgment calls

1. **No-drift placement where the citations are dense, clean code
   elsewhere.**
   * g6_state.py: lines 1–137 did not move. The resolve replaced main's
     blank line 126, and its helper sits after main.
   * launch_build.sh: lines 1–17 did not move.
   * program_fpga.sh and build.tcl were restructured where the plan says to
     change them, so their historical citations drifted: in
     `sw/program_fpga.sh`, old lines 52–95 moved by +31 and old line 96 on
     by +64, and build.tcl's blocks became proc calls. Those documents' citations were verified at their
     own bases, and the drift base is per document. This task edits none of
     those documents.
2. **Two refusal points in g6_state.** The brief places the check after Dev.
   But Dev's own resolve raises ValueError on an unknown name before any
   later line could run. So the name is resolved first, and refused with
   exit 4 before the lock and before the device is opened. The VERSION
   comparison sits after Dev and before any DMA, and covers `--readback`
   too (f6).
3. **build.tcl refuses an unknown second word.** Before this change, extra
   words were silently ignored; nobody passed any.
4. **program_fpga's default path prints two `=== [0/3]` lines**, and an
   `ss` failure refuses with exit 6 (fail closed). The line-for-line claim
   is about build.tcl's lines; program_fpga's default change is the one the
   plan mandates.
5. **The probe directories are named `synth/out_r3_synthonly_probe_<tag>`**
   (n2200, n2201, n2214, plus two harness debug runs, dbg1 and dbg2),
   rather than one `synth/out_r3_synthonly_probe/`. The brief's single
   directory cannot be reused per run, and
   `synth/scripts/launch_incr.sh:12` finds the source project by its build name under synth/. All are
   gitignored and one-flop; none holds a real design.
6. **The superseded first round, n2201–n2213.**
   * **n2201** (GREEN 137/0) and **n2202–n2203** carry `+dirty` on
     g6_state.py. That was snoke's stale NFS view of a file committed
     seconds earlier from darthplagueis: snoke's own `git status` was clean
     moments later. Later commits of this task were made on snoke.
   * **n2206 and n2208** ran the SR6 and SR13b host TDDs without their
     required `FABLE5_MODEL=9b`, and failed their setup checks on that alone.
   * All of these are committed and superseded by n2214–n2224.
7. **The session-log exclusion is the prefix `n33`** (R3-11's block), and
   the flag `--session-log-prefix` changes it.

## 7. What is NOT established

* **A real JTAG programming with `--expect-sha256`.** Only the refusals and
  `--check-only` ran. The positive path, where the sha matches, there is no
  client, and remove → JTAG → rescan runs, is first run in R3-11 step 2. The
  script sources settings64.sh, which puts the real vivado first on PATH, so
  a stub cannot stand in for that step.
* **The g6_state check on silicon.** Only the mock ran; its first real use is
  R3-11.
* **r3_preflight.sh's DEFAULT probe commands.** Every test overrode them. They
  are sr15's commands (`evidence/qwen9b/sr/sr15_preflight.sh:28-49`) as
  strings, first run in R3-11's pre-flight.
* **A full-design synth-only project feeding `synth/scripts/launch_incr.sh`
  end to end.** Only the argument and source check ran here; the full use is
  R3-10 steps 2–3.
* **PCIE_LOC and GT_LOC on a real netlist.** The one-flop project has no
  such cells (§3).
* **`synth/scripts/launch_po2.sh` on a synth-only project.** It was not
  exercised (plan review m16).

## 8. Citation drift: reported, not fixed

`evidence/qwen9b/sr/r3_2_drift.sh` ran in `--plan` and `--check` mode with
R3-2's flags: base `d6f7fa6`, the parent of the four implementation commits;
the four edited files; and this document excluded. Results:
`evidence/qwen9b/sr/n2230_r3_0_drift_plan.log:14` and
`evidence/qwen9b/sr/n2231_r3_0_drift_check.log:62`. The check found
13 drifted, 5 unresolved and 3 half-mapped citations into the two
restructured files.

The citing documents are:
* the R3 plan itself (the lines Task R3-0 was told to change);
* `evidence/qwen9b/g6/RD9_GATE.md`;
* `evidence/qwen9b/o3/BOARD_LOCK.md`;
* `evidence/qwen9b/bm/BM1_T3_BUILD.md`;
* `evidence/qwen2b/rb/TIMING.md`;
* `evidence/qwen_next/place_exp/PLACE_EXP.md`;
* the 2B track-R plan;
* two TCL comments, in `synth/scripts/ooc_9b.tcl` and
  `synth/exp_uram/scripts/exp_ooc.tcl`.

The drift and its effect:
* The unresolved and half-mapped tokens are the rewritten argument loop and
  the two blocks that moved into `synth/scripts/postimpl_sanity.tcl`. They
  have no line-for-line image, so they need a hand repair, not `--fix`.
* Every such document's citations were verified at its own base (the drift
  base is per document), so they describe the code as it stood then.
* None of these documents is edited by this task. The R3 plan is the
  controller's. So this task makes no `--fix`, and the list goes to the
  controller for R3-12's cite sweep.
* g6_state.py's citations (:69, :70, :124, :134) and launch_build.sh's
  (:11, :12, :14-17) did not move.

### 8.1 Fix round 1: the SAFE digits-only repair was applied

The task review (I1) asked for the SAFE plan to be applied, not just
reported, because two of its pointers are read by R3-11's operator.

* **The re-plan.** At doc-base `a65f87c` it was unchanged: REPAIR 7,
  COLLATERAL 0 (`evidence/qwen9b/sr/n2241_r3_0f1_drift_plan.log:14-15`).
* **`--fix` rewrote those 7 tokens and nothing else.** The diff is 6 lines
  in 4 documents. The tool's own count is "FIXED 27 citation(s)", the same
  27 that `--verify` relocates
  (`evidence/qwen9b/sr/n2242_r3_0f1_drift_fix.log:18`). Committed at
  `ce2532c`:
  * RD9_GATE.md §13: the trap pointer 94 → 125, and the "RESIDENT BITSTREAM
    IS NOW UNKNOWN" block 122-129 → 186-193 (now
    `sw/program_fpga.sh:125` and `sw/program_fpga.sh:186-193`);
  * BOARD_LOCK.md: the `--check-inherited` line 60 → 91
    (`sw/program_fpga.sh:91`);
  * BM1_T3_BUILD.md: the report_timing_summary line 50 → 62
    (`synth/scripts/build.tcl:62`);
  * the R3 plan: program_fpga.sh 59-64 → 90-95 and 96-105 → 160-169, and
    build.tcl 20-27 → 37-50 (`synth/scripts/build.tcl:37-50`).
* **`--verify`** at the pre-fix doc-base `a65f87c` read 49 citations and
  relocated 27 (`evidence/qwen9b/sr/n2244_r3_0f1_drift_verify.log:10`,
  `evidence/qwen9b/sr/n2244_r3_0f1_drift_verify.log:25`). Its verdict is
  FAIL, 17 problems (`evidence/qwen9b/sr/n2244_r3_0f1_drift_verify.log:35`),
  and every one of them is one of the §8.2 tokens:
  * each of the 3 HALF-MAPPED ranges and the 5 UNRESOLVED lines is
    reported;
  * each half-mapped range's START endpoint (build.tcl line 34 or 61) also
    shows as "still cites the OLD", once per citing document.

  No problem touches a repaired token.
* **A mis-invocation, kept.** n2243 ran `--verify` with the POST-fix commit
  as doc-base, a wrong use that double-maps the repaired tokens. It is
  superseded by n2244.

### 8.2 For R3-12: the tokens left for hand repair

These have no line-for-line image in the new files, so `--fix` never
rewrites them. None is read by R3-10 or R3-11. Each needs a hand repair,
with the target taken from the file at the repair commit.

| # | citing doc:line | token | kind | likely target now |
|---|---|---|---|---|
| 1 | `docs/superpowers/plans/2026-09-29-r3-broadcast.md:128` | `sw/program_fpga.sh:43-51` (the old argument loop) | UNRESOLVED (:43 and :51 rewritten) | `sw/program_fpga.sh:54-82` (the new loop and its validation) — or keep it as a historical "before" pointer with a dated note, since the text describes the pre-R3-0 loop |
| 2 | `docs/superpowers/plans/2026-09-29-r3-broadcast.md:130` | `synth/scripts/build.tcl:34-48` (sanity site 1) | HALF-MAPPED (:48 gone) | the call `synth/scripts/build.tcl:57-60`; the body `synth/scripts/postimpl_sanity.tcl:18-36` |
| 3 | `docs/superpowers/plans/2026-09-29-r3-broadcast.md:130` | `synth/scripts/build.tcl:61-66` (sanity site 2) | HALF-MAPPED (:66 gone) | the call `synth/scripts/build.tcl:73-75`; the body `synth/scripts/postimpl_sanity.tcl:38-46` |
| 4 | `docs/superpowers/plans/2026-08-12-qwen2b-track-r.md:406` | `synth/scripts/build.tcl:34-48` | HALF-MAPPED (:48 gone) | as #2 |
| 5 | `evidence/qwen_next/place_exp/PLACE_EXP.md:127` | `synth/scripts/build.tcl:34-42` (the gate through CLOCK_GATE_OK) | HALF-MAPPED (:42 gone) | `synth/scripts/postimpl_sanity.tcl:19-29` (called from `synth/scripts/build.tcl:60`) |
| 6 | `synth/scripts/ooc_9b.tcl:113` (a comment) | `synth/scripts/build.tcl:34-42` | HALF-MAPPED (:42 gone) | as #5 |
| 7 | `synth/exp_uram/scripts/exp_ooc.tcl:171` (a comment) | `synth/scripts/build.tcl:34-42` | HALF-MAPPED (:42 gone) | as #5 |
| 8 | `evidence/qwen2b/rb/TIMING.md:565` | `synth/scripts/build.tcl:42` (the CLOCK_GATE_OK puts) | UNRESOLVED | `synth/scripts/postimpl_sanity.tcl:29`; the "after `wait_on_run impl_1`" point is `synth/scripts/build.tcl:60` |

o3 counts these as 5 UNRESOLVED lines (program_fpga.sh :43 and :51;
build.tcl :42, :48 and :66) and 3 HALF-MAPPED ranges (build.tcl :34-42,
:34-48 and :61-66). The 8 rows above are those same tokens, one row per
place they are cited. Two of the files are TCL scripts, so repairing them
touches `synth/`, and that edit is R3-12's to schedule.

## 9. Log index

| log | what | status |
|---|---|---|
| n2200 | RED, 54 / 83 | used |
| n2201 | GREEN 137 / 0, stale-NFS +dirty stamp | superseded by n2214 |
| n2202–n2213 | first-round regressions (n2206 and n2208 without FABLE5_MODEL) | superseded by n2215–n2224, except n2204 bash -n (used) |
| n2214 | GREEN 137 / 0, clean `c2fdfb3` | used |
| n2215–n2224 | regressions and the no-flag guard check | used |
| n2230 / n2231 | o3 cite drift `--plan` / `--check` for the edited files | reported (§8) |
| n2241 / n2242 | fix round 1: the o3 `--plan` (SAFE, REPAIR 7) and the `--fix` | used (§8.1) |
| n2243 | `--verify` with the post-fix doc-base (a wrong use) | superseded by n2244 |
| n2244 | `--verify` at doc-base `a65f87c`: 49 citations, 27 relocated; its 17 problems are all §8.2's tokens | used (§8.1) |
| n2245 | spec_cites LAST over this document and the four repaired documents | the fix-round gate |
| n2240 | spec_cites LAST over this document and `docs/USAGE.md` | the gate |
