# Qwen3.5-9B Migration Implementation Plan — the 9B-only bitstream

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Qwen3.5-9B at **W4 g128 + GPTQ** on a **9B-only** bitstream —
**int16** DeltaNet state at 928 URAM with `DN_PIPE = 2` (amended 2026-08-31 —
the goal originally read *int8 DeltaNet state*; G1 measured it and the user
declined), 16-bit scratch ISA, `vecnorm` at N=4096, `MAX_NG = 96`,
W8 and g64 stripped — through the seven-gate ladder G1…G7, ending with the
`qwen9b` → `main` merge after the board gate passes.

**Architecture:** The de-risking phase already measured the three things that
could have killed this: the quality ladder says W4 g128+GPTQ is free
(`evidence/qwen_next/ladder/LADDER.md`), the placement experiment measured every
DN-state container (`evidence/qwen_next/place_exp/PLACE_EXP.md`),
and the host-model defects were found and either fixed or catalogued
(`evidence/qwen_next/defect_a/CORRECTIONS.md`). What remained was one unmeasured
quantity — the fidelity cost of an int8 state — so **G1 measured it first,
host-only, and stopped back to the user**. *(Amended 2026-08-31: it stopped
three times and the answer was no. The container is `int16` at 928 URAM; the
unresolved obstacle is now a placement constraint, not a fidelity question —
see AMENDMENT A1 and Task 13.)* Everything downstream is the 2B campaign's shape run bigger:
generalize the host chain while its byte-lock still proves inertness, spend the
byte-lock once on the ISA re-encoding, widen the RTL, replay the whole model in
sim, floorplan before building, build, bring up, merge.

**Tech Stack:** SystemVerilog (Verilator 5.020, `-Wall --timing`), Python numpy
reference models plus torch for goldens/GPTQ, Vivado 2024.2 on snoke, BCU-1525
(xcvu9p-fsgd2104-2L-e) via the CHARTER safe JTAG flow.

**Spec:** `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md`
at `8105e74` — fully review-closed, every decision user-ratified. **The spec
wins on any conflict with this plan.** Decision trail:
`.superpowers/sdd/2026-08-25-qwen-next-derisking/progress.md` (U1–U5 at
`progress.md:116-117`, O2/O3/O5 at `progress.md:119`). House model for task
structure: `docs/superpowers/plans/2026-08-16-qwen2b-v5-w8.md`.

---

## AMENDMENT A1 (2026-08-31) — G1 CLOSED, THE CONTAINER IS int16

> **Read this before Tasks 10, 12, 13 and 14. Nothing below has been deleted;
> superseded instructions carry a dated block and the amended instruction sits
> beside them.** Spec side: `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md`
> §0a, which this mirrors and which wins on any conflict.

**USER RULING at the G1 STOP, 2026-08-31: OPTION B — the DeltaNet state stays
`int16`.** Per-row/L1 reached MARGINAL (94/108, rank max 13) and its
ratification was **declined**. Gate doc: `evidence/qwen9b/g1/RUNG_INT8_STATE.md`
(cited by **section, not line** — it is still being appended to). Campaign
ledger: `.superpowers/sdd/2026-08-29-qwen35-9b-migration/progress.md`
(**LOCAL-ONLY**, gitignored — a fresh clone will not have it).

**Task status after G1:**

| task | status |
|---|---|
| **1 (G1)** | **CLOSED — FAIL, three waves, ruling taken.** Not re-run. |
| **2 (D-TOL)** | **CLOSED.** Bound `3e-02` → `8e-02`; the ruling was *the bound was wrong and NOT geometry-tuned*, which is neither answer this plan offered. |
| **3–16** | **OPEN.** Tasks 10, 12, 13, 14 are amended below. |

**What changes, and where:**

| # | change | task |
|---|---|---|
| A1.1 | DN state is **`int16`, 928 URAM** (24 banks × 29 + 232 KV), **one layer per bank**, with **`DN_PIPE = 2`** read-path pipelining. | **10** |
| A1.2 | The `dn_step` read-latency price is an **explicit, reviewed RTL-phase design decision** — wait state (≈ +10 %) vs the two-outstanding restructure. New step with its own review gate. | **10** |
| A1.3 | **The write-fan-out pblock is G5a's CRITICAL experiment and it can invalidate the target.** | **13** |
| A1.4 | 928 URAM **cannot** fit two SLRs. **Three SLRs are mandatory.** | **13, 14** |
| A1.5 | OOC URAM check **592 → 928**; also check FF +≈ 24.7 K, LUT and URAM unchanged by the pipelining. | **12** |
| ~~A1.6~~ | ~~Perf re-anchors to **≈ 6.5 – 7.0 tok/s**, headline ≈ 6.5.~~ G4b's cycle census measured the wait state itself — **SUPERSEDED 2026-09-03 by A3: it is +0.86 %, and §10's 6.98 – 7.47 band is restored.** | **12, 15** |
| A1.7 | The L1 per-row law stays in `ref/` as **measured evidence, unshipped**; its `sat8`/`e_fixup` counters become diagnostics that guard nothing shipping. | **10** |
| ~~A1.8~~ | ~~**`RS_F` stays 8.**~~ **SUPERSEDED 2026-09-01 by A2 — measured, and `RS_F = 7` is ADOPTED.** | **5, 10** |
| A1.9 | The **gate-port clamp** is option-independent and travels into the RTL phase: 60/768 DN heads have their decay changed. New spec register row **D-GATEPORT**. | **10, 15** |

**Two measured facts bind whatever gets built:** the container **must ROUND**
(under `int16` it already does — the law reduces to `clip16`), and **run-to-run
spread is exactly zero**, so none of G1's numbers are draw noise.

## AMENDMENT A2 (2026-09-01) — `RS_F = 7` ADOPTED

> **Supersedes A1.8.** Spec side: §0b, which wins on any conflict.

**USER RULING 2026-09-01: `RS_F = 7` (Q8.7) is the 9B operating point.**
Measured at the shipped `int16` container by Task 5's Step 4′ and recorded in
`evidence/qwen9b/g2/G2C_CHAIN.md` §7 (by **section, not line** — T5's closure
is being written concurrently): residual clips **23 → 0**, `|x|max` off the
32,767 rail at **29916**, top-1 **95 → 98**, **rank max 5 and top-5 3.69 both
unmoved**, free-run coherent on all four prompts, and the confirming repeat
**byte-identical** — `diff` over the report body returns one line, the json
path. The ratified **O5** condition (*remove the clipping without costing
top-1*) is met.

| # | change | task |
|---|---|---|
| A2.1 | **`rtl/conv4_silu.sv:50`'s baked shift `9 → 8`** (`RS_F + CW_F − 12` = 7 + 13 − 12). **A1.8 struck this file from Task 10's Files as foreclosed; A2 puts it back.** | **10** |
| A2.2 | The 9B manifest carries **`rs_f: 7`** — same caller-gated mechanism, new value. | **5** |
| A2.3 | **The host census is ALREADY DISCHARGED. Do NOT re-literalise it** — see the box below. | **3** (verify only) |
| A2.4 | Stale *"`RS_F` stays 8"* prose in `ref/layer_fixed.py` and `sw/chat_seq.py` comments. | whichever task next edits each file |
| A2.5 | **`FABLE5_RS_F` is a process-global env knob, not tag-selected.** Operational rule + a flagged root fix. | **3**, and every task running both an emission and a byte-lock check |

> ### A2.3 — the instruction "`HEAD_LOGIT_EXP0` −22 → −21" MUST NOT be applied
>
> G2a did not leave these as literals. It made them **derived**, and the
> derivation already yields −21 at a 9B manifest with no edit:
> `sw/chat_seq.py:353` is the **missing-key default** and −22 is correct for it
> (every 0.8B/2B artifact has no key); `sw/chat_seq.py:2658` is the live path
> and reads `spec.rs_f`; `sw/chat_seq.py:5035` already asserts the −21 case;
> `sw/hwmap.py:503`'s `RS_F_DEFAULT = 8` is the missing-key default and moving
> it would silently re-scale every pre-G2a artifact's logits by two; `rs_f` is
> already in `MANIFEST_META_KEYS`; and the two-keys-one-name collision is
> already documented at `sw/head_cache.py:107`.
> **The host work set is empty — verify these five, do not edit them.**

> ### A2.5 — the coexistence hazard, verified rather than assumed
>
> **The emit guard IS tag-scoped and 9B-at-7 coexists correctly.**
> `ref/gen_model_script.py:666` withholds the key for
> `BYTELOCKED_TAGS = ("0.8b", "2b")` and passes it otherwise, so 9B takes
> `ref/gen_layer_script.py:1604`'s write branch and never reaches the refusal at
> `ref/gen_layer_script.py:1621`.
>
> **But `RS_F` is not model-selected in fact.** `b9e0851:ref/layer_fixed.py:74` reads it
> from the environment, process-globally, while the spec and the code's own
> comments call it model-selected — the tag-scoping is entirely in the caller.
> **CLOSED 2026-09-10 (#26, pre-ship tool chore).** It IS model-selected now:
> `ref/layer_fixed.py` derives `RS_F` from `MS.TAG` and refuses a disagreeing
> `FABLE5_RS_F`. The citation above is PINNED to `b9e0851`, the tree the
> sentence describes.
> So **a process that exports `FABLE5_RS_F=7` and then emits a byte-locked tag
> trips the refusal.** That is the guard working (it prevents a silent 2× logit
> error), but the operational rule follows and belongs in every gate doc that
> runs both: **do not export `FABLE5_RS_F` across
> `evidence/qwen2b/rc/t4_bytes_unmoved.sh` or `ref/scripts/regen_gate.sh`.**
> Root fix, flagged not taken: derive `RS_F` from `MS.TAG` with the env as an
> override, which makes the name true.

## AMENDMENT A3 (2026-09-03) — A1.6's re-anchor is RETIRED, MEASURED

> **Supersedes A1.6's perf row.** Evidence: `evidence/qwen9b/g4/G4B_STRUCT.md`
> §5.4a–§5.5, log `evidence/qwen9b/g4/084_layer_term_6step.log`.

A1.6 re-anchored to **≈ 6.5 – 7.0 tok/s** on Track P's *"≈ +10 %"* bound for the
pass-2 wait state. **G4b measured it: +0.86 %** (98,304 cyc/token). The bound was
right about the *recurrence* (Task 10: +7.34 % of `dn_step`); A1.6 applied it to
the *layer term*, and `dn_step` is 62 % of the DNST command while DNST is 20.6 %
of the term.

**Measured layer term**, six forward steps of the real 9B stream, shipping
config: step 1 **46.027 ms**, step 6 **46.132**, **mean 46.079** vs the modelled
**47.00 (E)** — **2.0 % below**. In §10's step with `matvec 58.95` + `movers
32.66` unchanged (**E**): **7.263 tok/s**.

**§10's ORIGINAL band 6.98 – 7.47 is restored** and ≈ 6.5 – 7.0 retired.
**Task 10's option (i) stands, no two-outstanding restructure needed**: option
(ii) measures 7.286 vs 7.265 at the same step — **0.29 %** — for a change with
zero cycles of margin (G3.4 §4.4). **Still (E)**: only the layer term is
measured; decode-only; simulation, not silicon.

---

**One rule carried forward from Task 2's finding, now binding on every task:**
before committing any file another live task also names, run
`git diff --stat <that file>`; if it carries another task's uncommitted work, do
**not** commit that path. A file pathspec is not a defence against a shared
dirty worktree — it is the sweep mechanism.

---

## Global Constraints

Copied from the spec's hard rules. Every one of these is binding on every task.

- **NEVER read/grep/copy the pre-existing private implementation (the "answer key")**, its
  git history, or auto-memory entries about it (CLAUDE.md).
- **Branch `qwen9b` off `main`, in-place in this project dir. Commit at every
  green gate, path-limited** — the orchestrator near-miss on 2026-08-25 swept
  another track's staged files into a commit; **never trust the index.** The
  working form is `git commit -m "…" -- <paths>`: everything after `--` is a
  pathspec, so the message must come first. A new file still needs an explicit
  `git add <that path>` before it can be named in the pathspec.
  **The pathspec names FILES, not directories** — every commit block below is
  written out that way — with one permitted exception: a directory is allowed
  only where **exactly one task in this plan ever writes it** (each task's own
  `evidence/qwen9b/<gate>/`, and `synth/` for Tasks 13–14, which are strictly
  sequential). Anywhere two tasks share a tree — `ref/`, `sw/`, `tb/`,
  `evidence/qwen9b/g2/`, `evidence/qwen9b/g3/` — a directory pathspec is exactly
  the 2026-08-25 near-miss and is forbidden. Never `--amend`; commits stack
  (spec §11).
- **Every gate produces a committed gate doc under `evidence/qwen9b/<gate>/`,
  4 seeds minimum on every TB/HW run, and a commit** (spec §8 preamble).
- **Board safety, every time:** `sudo -n sw/pcie_helper.sh remove` →
  `sw/program_fpga.sh` (JTAG, **volatile only, never flash**) →
  `sudo -n sw/pcie_helper.sh rescan`. **No DMA before CSR CALIB = 0xF**
  (spec §8 G6, CHARTER).
- **The board stays serving the 2B on `build_035_fp2a_exc_po` until G6. The 9B
  bitstream does not touch the board before G5b closes** (spec §11).
- **Machines.** Vivado builds and heavy Verilator sims on **snoke**; G1's
  quantization and fidelity work also on snoke, with **thread counts pinned and
  recorded**. Lighter host work may go to kyloren/fn2187/darthvader over NFS.
  **darthplagueis stays out of numeric compute** until it passes a memtest soak —
  it produced wrong arithmetic eight times (spec §11).
- **One `obj_dir_<name>` per testbench, and never two hosts on one obj_dir**
  (spec §8 G3). Verilator 5.020, `-Wall`, 4 seeds.
- **Sweep with `/usr/bin/grep`** — the shell's `grep` here is `ugrep`, which
  honours `.gitignore` and will silently skip gitignored trees (spec §0).
- **`evidence/qwen_next/spec_cites.py` is a gate on any spec or gate document
  this campaign edits, including THIS PLAN**, and its `--selftest` negative
  control must pass. Run it before every commit that touches such a document.
  **Four limitations, so PASS is read correctly** — it is *necessary, not
  sufficient* (spec §8 G2):
  (a) a citation that is right-file, in-range and carries **no quotation** can
  still point at the wrong line, and the checker cannot see that class;
  (b) an identifier shorter than `MIN_QUOTE = 12` characters is treated as prose
  rather than as a quotation, so a short symbol beside a cite is never
  cross-checked — which is how a cite that named a *comment* line instead of the
  assignment beneath it survived a clean run in this plan's own review;
  (c) `--selftest` with no argument perturbs **the spec only**, so a negative
  control on this plan must pass the plan's path explicitly;
  (d) the `ALIAS` short-form map is a convention, not a derivation — a wrong
  target in it makes a short form fail `EXIST` (one such was found and fixed
  while writing this plan). **Semantic spot-checks remain review work**, and the
  cheap mechanical form of that check is to render every `path:NNN` and every
  bare `:NNN` continuation beside the source line it names, and read them.
- **Measured, not modelled.** Gate docs report measured numbers against the
  model as a *comparison*, never as a substitute; if a measurement lands outside
  a modelled band the gate doc says so and attributes it — it does not re-fit the
  model to the measurement and call it agreement (spec §10).
- **Labels.** The spec's §0 contract carries over: **M** measured on this board,
  **D** computed by a committed script that reproduces a committed number first,
  **T** toolchain-measured on real RTL and the real part, **E** extrapolated,
  **S** the document's own arithmetic. Every **S** in a gate doc names the gate
  that will measure it.
- **Evidence wrappers.** Every numeric/hardware step runs through a provenance
  wrapper in the R-c/R-d style (host, date, tree sha + dirty flag, cmd, venv, rc)
  — Task 1 creates `evidence/qwen9b/run.sh` for this campaign and every later
  task uses it.
- **Never re-run a committed evidence script in place when a gate doc cites its
  log by line.** Track L destroyed evidence exactly that way; the fix is an
  overridable output path. New logs get new names.

### Standing hazards this plan inherits

- `evidence/qwen_next/ladder/run_fidelity.sh` writes
  `evidence/qwen_next/ladder/fixed_<tag>_<point>.{json,log}` — **Track L's
  committed evidence**. G1 must not run it unmodified at 9B; Task 1 forks it.
- **The interpreter answer is per host, and the only safe test is `test -x`.**
  `ref/.venv/bin/python` is a symlink into `$HOME/.local/share/uv/python/…`;
  home directories are host-local (only `r2d2/code/` is NFS), so it resolves on
  darthplagueis and is a **dangling symlink on snoke** — the path is there, the
  interpreter it names is not. Conversely `/home/cah/.venv/bin/python`, which
  `evidence/qwen2b/rc/t4_bytes_unmoved.sh` takes as its `MODELPY` default,
  **exists on snoke with torch 2.12.0+cpu** and is absent on darthplagueis (all
  four facts verified 2026-08-29). So: probe with `test -x` plus an
  `import torch, safetensors` check before every gate, record the interpreter
  and its version in the gate doc, and never carry a "python X does/does not
  exist" claim across hosts. The ladder scripts side-step the question entirely
  with `uv run --no-project --with torch --with transformers --with numpy python`;
  every snoke-side numeric command in this plan uses that form.
- `ref/model_select.py` freezes `FABLE5_MODEL` at import. One process is one
  geometry, always; multi-geometry checks fork a subprocess per tag.

---

## Task map

| # | gate | what | may run in parallel with |
|---|---|---|---|
| 1 | **G1** | int8-DN-state fidelity rung — **STOP-BACK** · **CLOSED 2026-08-31: FAIL, container = `int16` (A1)** | 2 |
| 2 | G2 | D-TOL: own the 2b `layer_fixed` tolerance · **CLOSED: bound `3e-02` → `8e-02`, not geometry-tuned** | 1 |
| 3 | **G2a** | host generalizations, inert at 0.8B/2B; byte-lock PASS | — |
| 4 | **G2b** | the final byte-lock pin | — |
| 5 | G2c | the 9B artifact chain: goldens, GPTQ at scale, images, fit | 6 |
| 6 | **O3** | the shared board flock, mechanized | 5, 7–14 |
| 7 | G3.1 | the 16-bit scratch ISA — RTL, emitter, every decoder | — |
| 8 | G3.2 | `vecnorm_unit` at N = 4096 | 9 |
| 9 | G3.3 | `matvec` at MAX_NG=96 + XWIN 12 KiB, W8 and g64 stripped | 8 |
| 10 | G3.4 | `layer_chan` geometry: **int16** DN banking + `DN_PIPE=2`, KV, NH=32, CONV, envelopes | — |
| 11 | G4a | 9B SEQ streams + full-model sim replay | — |
| 12 | G4b | OOC structure gates + the layer-term cycle census | — |
| 13 | G5a | the OOC floorplan experiment (**O4 fork**) | — |
| 14 | G5b | the full build and timing closure | — |
| 15 | G6 | board bring-up | — |
| 16 | G7 | merge and ship | — |

**Nothing in tasks 3–16 starts until Task 1 returns PASS.** Task 2 is the only
work authorized alongside Task 1 (spec §11 "First moves").

> **The one parallel pair shares a file, and it is the file G1's verdict rests
> on.** Tasks 1 and 2 both modify `ref/layer_fixed.py`, and Task 2 is explicitly
> authorized to change the *code* rather than the bound if that is where the
> defect is. A code change under G1's feet destroys its single-variable
> premise — the whole point of the repeat run in Task 1 Step 4 — at the
> campaign's one STOP gate. **Rule: if Task 2's ruling touches the numeric path
> (anything other than the tolerance constant and its derivation comment), it
> does not land until Task 1's measurement runs have completed; if it lands
> anyway, Task 1's full point and its repeat are re-run on the post-fix tree
> before the verdict is read.** Both tasks commit **named files only**, never a
> directory that could sweep the other's work — the 2026-08-25 near-miss rule.

**Before Task 1:** create the branch, in-place in this project dir, off the
commit the spec binds to.

```bash
cd /home/cah/r2d2/code/fpga/fable5_llm
git status --porcelain          # must be empty
git checkout -b qwen9b main
mkdir -p evidence/qwen9b/{g1,g2,g3,g4,g5,g6,o3}
```

The board is serving the 2B from `build_035_fp2a_exc_po` and another worktree
shares it; nothing in Tasks 1–14 touches it.

---

### Task 1: G1 — the int8-DN-state fidelity rung. **STOP-BACK GATE.** — **CLOSED 2026-08-31**

> **EXECUTED IN THREE WAVES; THE STOP FIRED EACH TIME; THE USER RULED `int16`
> (A1).** This task is kept verbatim as the instruction that was executed —
> nothing below is an instruction any longer. Results:
> global-`k` **72/108**, per-head **83/108**, per-row **94/108 MARGINAL**,
> `int16` baseline **95/108**; the `RS_F = 7` rider rejected at per-row.
> Several provisions earned their keep: the two-tool mandate in Step 6 caught a
> gate-port failure `audit_ranges` alone reported as PASS, Step 4's repeat run
> measured spread at exactly zero, and Step 1's cache saved ≈ 45 h.
> Full record: `evidence/qwen9b/g1/RUNG_INT8_STATE.md` (by section — still being
> appended to).

Host only, snoke. No RTL, no board, no synthesis. This is the first executable
gate and **no RTL is written until it returns PASS** (spec §4.1, §8 G1).

**Files:**
- Modify: `ref/layer_fixed.py` (the parameterized state-narrowing law + the
  `RS_F` runtime knob), `ref/fidelity_check.py` (carry the state-law and `RS_F`
  configuration into the SUMMARY row and the json)
- Create: `evidence/qwen9b/run.sh` (the campaign's provenance wrapper),
  `evidence/qwen9b/g1/run_g1_smoke.sh`, `evidence/qwen9b/g1/run_g1_point.sh`,
  `evidence/qwen9b/g1/RUNG_INT8_STATE.md`
- Test: `ref/layer_fixed.py`'s own selftest at 0.8b/2b/9b; the smoke sweep; the
  full 168-step points; `ref/audit_ranges.py`;
  `evidence/qwen2b/q2/audit/gate_port_probe.py`

**Interfaces:**
- Consumes: the 9B golden `evidence/qwen_next/ladder/golden_bf16_9b.npz` —
  **on disk but NOT committed**: `.gitignore:39` ignores
  `evidence/qwen_next/ladder/golden_bf16_*.npz` as a regenerable cache, and
  `git ls-files` does not list it. What **is** committed is its sha256,
  `4fd0616bae5086b8e449901740355a9f192b33ae1c9d18eafc160c0987408fd3`, recorded
  in `evidence/qwen_next/ladder/LADDER.md`. **Hash it before use and rebuild it
  if the hash fails or the file is gone** — the same mechanism Task 5 Step 2
  spells out; the golden is a cache with a pinned hash, not an artifact. The
  Hessian `ref/calib_stats_9b_h.npz` is gitignored the same way, sha in
  `evidence/qwen_next/ladder/calib_9b.log`. The four committed prompt seeds
  `1,2,3,4`; the baseline row of spec §4.1(b).
- Produces, and every later task reads these from the gate doc rather than
  re-deriving them:
  - **`FABLE5_DN_STATE`** — the state-law selector, read once at
    `ref/layer_fixed.py` import, exactly as `FABLE5_CALIB_MODE` is.
    Grammar: `int16` (default — today's behaviour, byte-identical),
    `int8:<k>` (L0, round-to-nearest), `int8t:<k>` (L0 truncating, the
    record-what-not-to-build point), `int8e` (L1, int8 mantissa + per-row
    power-of-two exponent). Unset behaves exactly as `int16`.
  - **`FABLE5_RS_F`** — integer override of the residual binary point, default
    `8`. Unset behaves exactly as today. G2a replaces this env knob with a
    manifest key; the env form exists only so G1 can measure the rider before a
    9B manifest exists.
  - **`LF.dn_state_narrow(S16)`** — the law itself, applied **after every state
    update** in `layer_fixed`'s DeltaNet recurrence, so the host model is
    bit-exact against what the RTL would hold. Task 10 mirrors this function in
    `rtl/dn_step.sv`/`rtl/layer_chan.sv`; **this function is the law and the RTL
    mirrors it, never the reverse.**
  - The **chosen law** (`int8:<k>` or `int8e`) and the **chosen `RS_F`** (8 or 7),
    recorded as the two headline lines of `evidence/qwen9b/g1/RUNG_INT8_STATE.md`.

- [ ] **Step 1: the provenance wrapper, and prove the weight cache is state-law-independent**

Create `evidence/qwen9b/run.sh` in the style of the R-c/R-d wrappers: `cd` to
the repo root, emit `=== host: / date: / tree: <short sha>[+dirty] / cmd: / venv:`,
run `"$@"`, then `=== rc: $?` and `=== end:`, teeing to
`evidence/qwen9b/<log-name>`. Every command below runs through it.

Then the cost question the spec makes G1's *first* task (§4.1 Cost): the
quantized-weight artifacts are independent of the state law, so they must be
built once and reused across settings rather than paying 6.99 h per point.
Establish that mechanically, not by assertion: run two six-step smokes at
different `k` and show the quantizer output is reused — compare the
per-configuration wall time of the second against the first, and assert in the
harness that the weight-quantization stage is entered exactly once per process.
If it is not, add the cache before spending a single full point.

- [ ] **Step 2: the law goes in `ref/`, defaulting to today's behaviour (RED then GREEN)**

Add the selector to `ref/layer_fixed.py`, beside the frozen-format constants
`RS_F` / `S_F` / `KVC_F`, which is where a container decision belongs and where
the next reader will look for it:

```python
# FABLE5_DN_STATE selects the DeltaNet state container.  Read ONCE at import,
# like FABLE5_CALIB_MODE, so a process is one law for its whole life.
#   int16        the shipped Q2.13 container (default; byte-identical)
#   int8:<k>     S8 = sat8(rshr_round(S16, k))        -> Q2.(13-k)
#   int8t:<k>    S8 = sat8(S16 >> k)   truncating     -> the negative point
#   int8e        int8 mantissa + per-row power-of-two exponent (L1)
```

Write the failing selftest first, in `layer_fixed`'s `_selftest`: for each `k`
in the sweep, `dn_state_narrow` must (a) round to nearest rather than truncate,
proven by a vector whose truncated and rounded results differ; (b) saturate
symmetrically at ±127 rather than wrap, proven at `S16 = ±32767`; (c) be exactly
the identity under `int16`; (d) be idempotent — narrowing an already-narrowed
state changes nothing. Run it, watch it fail, implement, watch it pass.

Then prove inertness at the two frozen geometries — one interpreter per tag,
because `model_select` freezes `FABLE5_MODEL` at import:

```bash
cd /home/cah/r2d2/code/fpga/fable5_llm
for T in 0.8b 2b; do
  FABLE5_MODEL=$T OMP_NUM_THREADS=3 nice -n 15 \
    $HOME/.local/bin/uv run --no-project --with torch --with transformers \
    --with numpy python ref/layer_fixed.py
done
```

`0.8b` must print `LAYER_FIXED SELFTEST PASS`. **`2b` is expected to fail on
`attn softmax+pv rel=3.288e-02` and only on that** — it is pre-existing on
committed main and Task 2 owns it; any *other* 2b failure is this task's
regression and stops the step.

- [ ] **Step 3: measure the 9B state range, then centre the `k` sweep on it**

The prior in the spec is that plain narrowing keeping the ±4 range gives Q2.5 at
0.03125 resolution against a measured rms of 0.009 — but that rms and the
`|S|max 0.76` beside it are the note carried at `ref/layer_fixed.py:39`, taken
at the shipped geometry, **not at 9B**. Measure first.

Run one int16 six-step smoke at 9B with the audit counters on, and read
`s_absmax`, `s_sat` and `s_writes` out of it. Then pick the sweep: `k` is a
right shift, so the represented ceiling is `127 · 2^-(13-k)` and the resolution
is `2^-(13-k)`. Sweep the four `k` whose ceilings bracket the measured
`|S|max` — as a starting point `k ∈ {5, 6, 7, 8}`, whose ceilings are
0.496 / 0.992 / 1.984 / 3.969 and whose resolutions are 0.0039 / 0.0078 /
0.0156 / 0.0312. **Report all four regardless of which wins**, and report the
per-`k` state-saturation count beside the top-1, because a `k` that wins on
top-1 while saturating hard is the fragile answer and the gate doc must say so.

**Then measure `int8t` once, at the winning `k`.** The spec requires it: Track
P's experiment RTL truncated with no rounding, and the rung "measures truncation
as a cheap second point only to record what *not* to build". One six-step smoke.
A unit selftest proving rounding differs from truncation is not that
measurement.

The smoke, six teacher-forced steps on one prompt, at `w4g128gptq` — **not** at
W8, which is what Track L's `res_scale` sweep used and is not the point this
build ships:

```bash
FABLE5_MODEL=9b FABLE5_DN_STATE=int8:6 \
FABLE5_CALIB_STATS=ref/calib_stats_9b_h.npz FABLE5_CALIB_MODE=gptq \
OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 nice -n 10 \
  $HOME/.local/bin/uv run --no-project --with torch --with transformers --with numpy \
  python -u ref/fidelity_check.py --wire-group 128 --prompts 1 --ntok 3 \
    --no-freerun --res-scale 1 \
    --cache evidence/qwen_next/ladder/golden_bf16_9b.npz \
    --json-out evidence/qwen9b/g1/smoke_int8_k6.json
```

`--ntok 3` is six teacher-forced steps; `--ntok 24` is the 27-per-prompt × 4 =
108 the full point needs. Wrap the whole sweep in
`evidence/qwen9b/g1/run_g1_smoke.sh <law>` so the pinning, the golden path and
the output naming cannot drift between settings. **~8 min per setting.**

- [ ] **Step 4: the full point at the winner, and the repeat run that makes the bar mean something**

Fork `evidence/qwen_next/ladder/run_fidelity.sh` into
`evidence/qwen9b/g1/run_g1_point.sh <law> <rs_f> <run-tag>`, writing to
`evidence/qwen9b/g1/fixed_9b_w4g128gptq_<law>_rsf<rs_f>_<run-tag>.{json,log}`.
**Do not run the ladder script in place** — it writes Track L's committed
`fixed_9b_*` artifacts.

The point is: 9B, `w4g128gptq`, `S=1`, prompts `1,2,3,4`, `--ntok 24`,
`--free-ntok 12` → 108 teacher-forced + 60 free = 168 steps, teacher-forced
against the committed golden. Identical harness, identical golden, identical
prompts as the baseline, so the comparison is single-variable. **3.79 h.**

Then the repeat: re-run the winning configuration **once, in a fresh process**,
and require the two runs to agree on **all seven** reported quantities — top-1,
rank median, rank max, top-5 overlap, `|x|max`, clips, `S_F` saturation. *(The
spec says "six"; the committed SUMMARY row has seven columns and the baseline
row quotes seven values. Seven is what is checked, and the discrepancy goes in
the gate doc rather than being resolved by dropping one.)* This costs
one 168-step run and it buys the only thing that makes a 93-vs-92 threshold
meaningful. **If the two runs disagree, the bar is re-derived against the
observed spread before anything is concluded** — and that is STOP-back case 4.

- [ ] **Step 5: the `RS_F 8 → 7` free rider**

Ride it on the same runs (spec §4.4). Measure `RS_F ∈ {8, 7}` at 9B on the
six-step smoke at the winning law; if Q8.7 removes residual clipping without
costing top-1, take it; if it costs top-1, do not. Either way the answer is
recorded rather than assumed, and the recorded value is what Task 3 writes into
the manifest and Task 10 bakes into `rtl/conv4_silu.sv`'s literal shift.

Note the one RTL literal this touches before anyone assumes the RTL is
format-agnostic: `rtl/conv4_silu.sv:50` `pre = rshr64(64'(acc1), 9);` with its  <!--cites:noquote-->
own derivation comment. Everything else takes the binary point as a runtime
shift.

- [ ] **Step 6: the second axis — BOTH range tools, because `audit_ranges` is blind on the port that matters**

Two tools, not one (spec §4.1(d)). `ref/audit_ranges.py` scores the state
itself. The `Av` gate port must come from `qd["gate_sat"]` via
`evidence/qwen2b/q2/audit/gate_port_probe.py`, because
`layer_fixed.quant_deltanet` saturates `dt_bias` and `A` into their ports before
returning them, so `audit_ranges` reports `0 / N` out of range and a max pinned
exactly at the rail **even if the checkpoint exceeds the port**. The 2B audit
found 1 of 288 heads already over its rail; 9B has 24 DN layers × 32 heads.

Run both at 9B, through the wrapper, and record both outputs verbatim in the
gate doc. **A saturation class either tool reports that the fidelity top-1 does
not reflect is STOP-back case 3.**

- [ ] **Step 7: the verdict, the gate doc, and the STOP protocol**

Score against the bar (spec §4.1(c)), against the int16 baseline of 95/108,
rank max 5, top-5 3.69, `|x|max` 32767, 23 clips, `S_F` sat 4,392:

| band | criterion | action |
|---|---|---|
| **PASS** | top-1 ≥ **93/108** and rank max ≤ **8** and top-5 ≥ **3.50** and free-run text coherent on all four prompts | proceed to Task 3 |
| **MARGINAL** | top-1 **90–92** or rank max **9–16**, text still coherent | **STOP-BACK** |
| **FAIL** | top-1 < 90, or rank max > 16, or any free-run degeneration | **STOP-BACK**, O1 fork |

**THE STOP PROTOCOL IS NOT ADVISORY.** On MARGINAL, on FAIL, on either range
tool reporting a class the fidelity harness does not see, on the repeat run not
reproducing, or on L0 failing such that the rung would have to escalate to L1 —
**the orchestrator prompts the user and ALL WORK HALTS.** No RTL, no further
tasks, no recommendation attached to a MARGINAL. The report carries exactly:
the measured table, both range-tool outputs, and the O1 fork with Track P's own
prices attached (option 1 = 928 URAM + `DN_PIPE=2`, ≈ +10 % throughput or an
unpriced two-outstanding restructure, floorplan untried; option 3 = DDR spill,
0.6 % of 9B W8 traffic but a large new RTL path). Nothing else.

**Escalating to L1 is itself a STOP-back item** — it is materially more RTL than
what Track P placed, and U3's STOP exists to catch exactly that scope growth
before it is spent. If the user authorizes L1, the exponent structure it picks
re-opens the URAM price and Task 12's OOC run must re-confirm 592.
*(Amended 2026-08-31: L1 was authorized, measured, and its MARGINAL declined —
so this branch never executed. Task 12 re-confirms **928**, not 592: A1.5.)*

`evidence/qwen9b/g1/RUNG_INT8_STATE.md`: provenance (host, tree sha, thread
pinning, golden sha256, corpus/prompt provenance), the four-`k` table with
saturation counts beside top-1, the winner, the repeat-run agreement, the
`RS_F` rider result, both range-tool outputs, the verdict against the bar, and
the not-established list. Commit path-limited.

```bash
git commit -m "gate(G1): int8 DN state fidelity rung — law in ref/, k sweep, full point + repeat, RS_F rider, both range tools" \
  -- ref/layer_fixed.py ref/fidelity_check.py \
     evidence/qwen9b/run.sh evidence/qwen9b/g1/
```

---

### Task 2: D-TOL — own the 2b `layer_fixed` tolerance — **CLOSED 2026-08-29**

> **RULING: the bound was wrong, and NOT geometry-tuned — neither of the two
> answers this task offered.** `3e-02` → **`8e-02`**, one constant plus its
> derivation. The plan's hypothesis (*a 0.8B-tuned tolerance that legitimately
> loosens with geometry*) is **false**: the two values are the same computation
> on two different draws of a shared `default_rng(21)` stream, and the 9B value
> was derived with zero free parameters before it was confirmed. 21/21 selftest
> invocations exit 0 at 0.8b/2b/9b. Gate doc `evidence/qwen9b/g2/D_TOL.md`.
> **Handed back for a later pass**: the PV block is transcribed three times, and
> the spec's D-TOL row still describes a "9.6 % geometry overshoot" that does
> not exist — **Task 3 owns that correction** (the spec is in Task 3's Files,
> not this task's, and not this amendment's).

Host only, snoke or any NFS host. **This is the ONLY work authorized alongside
Task 1** (spec §11 "First moves"): it is host-only, zero-risk, and it blocks
G2's readability. It is a G2-owned defect (spec §9 D-TOL) executed early.

**Files:**
- Modify: `ref/layer_fixed.py` (the `attn softmax+pv` bound, or the code behind
  it — the task is to decide *which*)
- Create: `evidence/qwen9b/g2/D_TOL.md`
- Test: the 14-invocation `ref/` selftest sweep at 0.8b and 2b, plus 9b

**Interfaces:**
- Consumes: `evidence/qwen_next/ladder/head_baseline_layer_fixed_2b.log` — the
  proof that the failure is pre-existing on committed main, reproduced from a
  pristine `git archive HEAD ref` tree.
- Produces: an all-green `ref/` selftest sweep at **0.8b, 2b and 9b**, which is
  the precondition for reading Task 3's gate. Any per-geometry bound is
  published as a derivation, not a number.

- [ ] **Step 1: reproduce, then decide which side is wrong**

Reproduce the failure and confirm it is bit-identical to the committed baseline
value `rel=3.288e-02` against the `3e-02` bound — a 0.8B-tuned bound the 2B
geometry overshoots by 9.6 %.

Then answer the question the spec asks and does not answer: **is the bound wrong
or is the code wrong?** Score it at all three geometries this campaign cares
about — 0.8b, 2b, 9b — and at the head counts that differ (`LNH`/`LNKH`,
`NQ`/`NKV`), because a bound that scales with head count is a different fix from
a bound that was simply set too tight. **A per-geometry bound is acceptable only
with the derivation written down**; a bare loosened constant is not.

- [ ] **Step 2: fix, and prove the fix does not move bytes**

Land the decision. Then re-run the sweep, one interpreter per tag:

```bash
LOG=evidence/qwen9b/g2/ref_selftests_dtol.log \
  bash evidence/qwen_next/ladder/run_ref_selftests.sh
```

**Override `LOG`.** The default target is
`evidence/qwen_next/ladder/ref_selftests.log`, whose `:515` and `:541` LADDER.md
§6.10 cites by line, and the script truncates its log. Track L destroyed that
evidence once already.

Extend the sweep to `9b` as a third tag in this campaign's own copy of the
runner (the ladder's runner is Track L's committed evidence; fork it to
`evidence/qwen9b/g2/run_ref_selftests_9b.sh` rather than editing it). Target:
**every invocation exits 0 at all three tags.**

- [ ] **Step 3: gate note + commit**

`evidence/qwen9b/g2/D_TOL.md`: the reproduction, the derivation, the decision
with its reason, the before/after sweep results at three tags, and — because
this changes a *tolerance*, which is a claim about what "correct" means — an
explicit statement of what the new bound does and does not admit.

```bash
git commit -m "fix(G2/D-TOL): own the 2b layer_fixed attn softmax+pv bound — derivation, three-geometry sweep green" \
  -- ref/layer_fixed.py \
     evidence/qwen9b/g2/D_TOL.md evidence/qwen9b/g2/run_ref_selftests_9b.sh \
     evidence/qwen9b/g2/ref_selftests_dtol.log
```

---

### Task 3: G2a — the host chain generalized at 9B, and the byte-lock still holds

**PRECONDITION: Task 1 returned PASS.** Host only. Everything in this task is
supposed to be **inert at 0.8B and 2B**, and
`evidence/qwen2b/rc/t4_bytes_unmoved.sh` is exactly the tool that proves it —
the same use Track L put it to. **It must pass.**

**Nothing here touches the ARG layout.** The ISA re-encoding is Task 7 and it is
what spends the byte-lock. §7.5's TB census is *not* in this task either — those
are the testbench twins of RTL width changes that do not exist yet, and editing
a TB to expect a 16-bit address before the RTL has one would break the suite,
not preserve it.

**Files:**
- Modify: `ref/gen_layer_script.py` (the refusals → generalizations),
  `ref/gen_token_script.py`, `ref/gen_model_script.py`, `ref/debug_torch_diff.py`,
  `ref/layer_fixed.py` (`RS_F` from the manifest), `ref/seq_chat.py`,
  `ref/audit_ranges.py`, `ref/calib_stats.py`, `sw/infer.py` (defect B),
  `sw/hwmap.py`, `sw/seq_run.py`, `sw/chat_seq.py`, `sw/head_cache.py`,
  `sw/tok_meter.py` (D-TOK), `tb/scripts/gen_chat_i1_vectors.py` (D-STAGE),
  `tb/scripts/gen_seq_unit_vectors.py` (import `SCRATCH_WORDS`, do not duplicate
  it), `evidence/qwen_next/spec_cites.py` (the retirement set),
  `docs/QWEN35_NEXT_FEASIBILITY.md` and the spec (the dated D-DEAD supersession
  notes)
- Delete: `tb/scripts/gen_seq_vectors.py` (D-DEAD)
- Create: `evidence/qwen9b/g2/G2A_HOST.md`
- Test: the three-tag `ref/` selftest sweep; `t4_bytes_unmoved.sh`;
  `make -C sw seq_selftest serve_test`; `sw/chat_seq.py --selftest`;
  the deliberate-damage regressions

**Interfaces:**
- Consumes: Task 1's `RS_F` decision and state law; Task 2's green sweep.
- Produces, consumed by Tasks 5, 7, 10, 11, 15:
  - `ref/gen_layer_script.py` generalized to `VREP`: value head *h* reads key
    head `h // VREP`, with `require_supported_geometry` becoming an assertion of
    the new algebra rather than a refusal.
  - **DN/KV slots 24 / 8** everywhere: the `cw` array and its two siblings, the
    `dn_slot`/`kv_slot` assert, the KV caches `kc`/`vc`/`T` sized `[8][4]`,
    and `gen_token_script`'s `DN_SLOTS, KV_SLOTS`.
  - **The SCA tile map is the layout authority**, exporting `beta_base`,
    `decay_base` and `LNH` as the single source of truth for both the `GATE`
    writer and the `DNST` pointer. **The LNH=32 map is not this plan's
    invention, and it is not a committed layout either** — it is the output of
    the `fix_sca` branch of
    `evidence/qwen_next/feas/scratch_peak.py`, the script the study's 9B peak
    was computed with, and the emitter must reproduce it exactly:
    `B16 @ +0` (`max(32, LNH)` = 32 w), `A16 @ +32` (`max(32, 2·LNH)` = 64 w),
    `GD @ +96` (64 w), `QN @ +160`, `QNS @ +288`, `KN @ +416` (LDK each),
    `DO32 @ +544` (2·LDV = 256 w), `OH @ +800`, `NH @ +928` (LDV each) —
    **`SCA_SZ = 1056`**, which is the spec's number. The spec's phrase
    "64-word tile strides" means A16 and GD; B16 keeps a 32-word slot because
    LNH=32 fills it exactly. Any other arrangement must still total 1056.
  - **`STG` moves with it.** The emitter's `STG = SCA + 1024` is a literal that
    happens to exceed today's `SCA_SZ` of 992; at 1056 it **collides**. The
    authority already models the fix — `STG = SCA + max(1024, SCA_SZ)` — and
    the study's 50,208-word 9B peak was computed with it, so the emitter must
    adopt the same expression or its map and the derived peak disagree.
  - **Both are inert at LNH=16, which is why they belong in this gate.**
    Evaluate the parameterized map at LNH=16 and it returns the as-built
    offsets 0/32/64/96/224/352/480/736/864 with `SCA_SZ = 992`, and
    `max(1024, 992) = 1024` is the as-built `STG` literal — byte-identical, and
    the byte-lock is what proves it rather than this paragraph.
  - `beta_base = GD`, `decay_base = GD + LNH`. Task 7 reads both from the map.
  - > **AMENDED 2026-09-01 (A2.2).** The mechanism below is unchanged and
    >   landed correctly; only the **value** 9B passes has moved. `rs_f` is
    >   withheld for `BYTELOCKED_TAGS` and passed otherwise, so the byte-lock
    >   logic is untouched — but **9B now genuinely emits a non-default key,
    >   `rs_f: 7`**, where before it emitted the default 8. The emit-side
    >   refusal this task built (`ref/gen_layer_script.py:1621`, which fires
    >   when the key is dropped while `RS_F != 8`) is **verified to coexist**:
    >   9B passes the key and never reaches that branch. **What this task must
    >   now also carry is A2.5's operational rule** — `FABLE5_RS_F` is
    >   process-global (`b9e0851:ref/layer_fixed.py:74`), so exporting it across a
    >   byte-locked emission trips the refusal (CLOSED 2026-09-10: the root
    >   fix WAS taken — `RS_F` is derived from `MS.TAG` and a disagreeing
    >   export is refused at import, so the hazard is now a named error).
    >   Put that in the gate doc, and
    >   record whether the root fix (derive `RS_F` from `MS.TAG`) was taken or
    >   flagged.
  - **The manifest gains `rs_f`**, written by the emitter the way
    `emb_row_bytes` is and consumed by the host from it. `RS_F` is thereafter
    **model-selected, not global**: 0.8B/2B keep 8 and keep their byte-lock;
    9B may take 7.
    **Its precedent is `emb_row_bytes`, which is CALLER-gated, not the
    value-gated `g`/`w8`** — and the distinction is the file's own: `g` is
    emitted when `!= 128` and `w8` when true, but `emb_row_bytes`, "the ONE
    non-wid key this file may carry", is emitted **only when the caller passes
    it**. `rs_f` is a non-wid key, so it follows `emb_row_bytes`: the emitter
    passes it only when it is writing a 9B artifact. Either gating preserves
    byte-identity; take the one the docstring already documents, and update that
    docstring, which currently says "the ONE non-wid key". This is not a style
    preference: `evidence/qwen2b/rc/t4_bytes_unmoved.sh` byte-compares the
    weights manifest (normalising only the image-filename prefix), and the gold
    2B manifest carries no non-wid key at all, so an unconditional `rs_f` fails
    Step 7's `BYTES_UNMOVED PASS`.
  - `plan_weights(man, wdir=None, nch=1, rows_of=None)` unchanged in signature,
    but `sw/tok_meter.py` now calls it with `rows_of` (D-TOK).

- [ ] **Step 1: the byte-lock baseline, BEFORE any edit**

Run it first, so the "it still passes" claim at the end has something to be
compared against, and record the log:

```bash
export MODELPY=<a torch-capable interpreter — see below>
bash evidence/qwen9b/run.sh g2/t4_bytes_unmoved_before.log \
  bash evidence/qwen2b/rc/t4_bytes_unmoved.sh
```

**`MODELPY` must be set explicitly and recorded.** The script's default is a
hard `/home/cah/.venv/bin/python` with **no fallback**, and that path does not
exist on this host (verified 2026-08-29); it regenerates a 2B artifact set, so
it needs torch and safetensors. `ref/scripts/regen_gate.sh` falls back to
`command -v python3` and this one does not. Establish one torch-capable
interpreter for the whole campaign — a `uv venv` created once, or the system
`python3` where it already carries torch — verify it imports torch, and record
the path and version in the gate doc. Every later invocation of both scripts
uses it.

Expect `BYTES_UNMOVED PASS`. Also capture `bash ref/scripts/regen_gate.sh` →
`REGEN_GATE_PASS` (hash lock `a69864d2…`, nrec 60495) as the second frozen
anchor. If either is red before the task starts, STOP — the baseline is broken
and this task cannot prove anything.

- [ ] **Step 2: turn Track L's refusals into generalizations**

Work the §7.1 census. Each of these is a live silent-wrong-answer site at 9B,
not a stylistic cleanup:

- the QKV head loop — the packed block is q then k then v with `LKD = LNKH·LDK`,
  so today **every h at or above 16 reads the K region as Q and V as K,
  silently**. Generalize with `VREP`.
- **the `DNST` decay pointer**, which is a live wall-17 defect this spec found
  while quoting the line as proof: the literal `16` **is `LNH`**. At LNH=32 the
  decays live at `GD+32 … GD+63` but the emitted pointer sweeps `GD+16 … GD+47`,
  so **all 32 heads read the wrong word** — heads 0-15 from the beta half,
  heads 16-31 off by 16. Correct form: `GD + LR.LNH + h`. **This must land
  before Task 7 derives the scalar-pointer base from that call site.**
- DN/KV slot sizing 18/6 → 24/8, and the KV caches `[6][2]` → `[8][4]` — the
  latter in lockstep with `KVH_MAX` and, later, the RTL field (Task 10).
- **the SCA tile map and `STG` together.** `SCA_SZ` 992 → 1056 alone is a
  silent aliasing bug: `NH` then occupies `SCA+928 … SCA+1055` while the
  emitter's `STG = SCA + 1024` literal parks the staging window on top of it.
  Land `STG = SCA + max(1024, SCA_SZ)` in the same edit — the form the study's
  allocator already uses and computed the 50,208-word peak with. Leaving the
  literal gives an aliased map and a peak of 50,176.
- `SCRATCH_MAX` → 65,536; `DNST_HEAD_MAX` → `(1<<5)-1`;
  `assert 1 <= n <= 2048` → 4096, keeping `assert (1 << nlog2) == n`, which is
  the guard that catches a non-power-of-two `H` and must survive.
- `ref/debug_torch_diff.py` — refuses at import today; generalize.

**`SCRATCH_MAX = 65536` alone does not make a 9B stream emittable** — the ARG
words still cannot carry a 16-bit address until Task 7. Raising it here is
correct and inert (no 0.8B/2B address is affected), but the emitter will still
refuse a 9B layer body at `enc_saddr`'s pair packing. That is expected and is
the reason Task 11, not Task 5, emits the streams.

- [ ] **Step 3: defect B, and its deliberate-damage regression**

Four hard `1024` literals where `LR.H` belongs, on the **online `step()` path**
of `sw/infer.py`. The crash at the matvec is where it stops, not where it
starts: the three lines before it run silently on half the residual, and because
RMSNorm's denominator is a mean over the words it is *told* about, they corrupt
even the words they do write — measured at 2B on an unevenly-split residual, the
DYNQ8 exponent shifts and 99.6 % of the leading half changes, max |diff| 99.

Fix all four to `LR.H`, following the already-parameterized template in
`ref/gen_model_script.py`. Fix `sw/infer.py:719`'s cosmetic literal log text in
the same pass. **Commit a deliberate-damage test beside the fix in the Track F
style** — put the literals back, watch it fail — under
`evidence/qwen9b/g2/damage_defect_b.py`, and run it at 2b and 9b.

- [ ] **Step 4: close the `sw/` literal census**

Work spec §7.4 row by row. The ones that are more than a widening:

- `sw/chat_seq.py`'s `HEAD_WID = 186` — at 32 layers the head is a **different
  wid** (249 images). The correct derivation already exists in the same file and
  lands in `g["_HEAD_WID"]`; the online call must use the derived value.
- **`sw/chat_seq.py:181-182`** `POS_STRIDE` / `POS_COPIES` — rope-table bytes
  per position and the GQA layer count, **not** the mvchan XWIN 1536 they look
  like. Moves with the GQA layer count 6 → 8 and with `NKV`. Reinforced at ten
  further sites listed in the spec; sweep them all with `/usr/bin/grep`.
- `sw/seq_run.py:2461`'s hard-coded scratch-cover pair, which its own comment
  claims is a "WHOLE power-of-two scratchpad" check and is not — derive it. And
  in the same file, the fixtures and mapping tests pinned at 2048 B / H=1024 at
  `sw/seq_run.py:780`, `:1593-1594`, `:2593-2599` and `:2609-2614`: the
  *mechanism* is already manifest-driven, so only the fallback and the fixtures
  are pinned, and only those move.
- `sw/chat_seq.py:314`'s `X8_WORD, X8_LEN` — **latent, not live**, because every
  in-repo caller passes session-derived geometry. **Move it anyway**: a latent
  literal at a new geometry is the R-c wall-8 class. Take its neighbour
  `STG_WORD, STG_LEN` at `sw/chat_seq.py:315` with it, which the spec's census does not list
  and which has the same shape.
  *(**Line numbers amended 2026-08-31 at G2a and again 2026-09-01 at G3.1**, each of which moved them: the pair was at `sw/chat_seq.py:231-232` when this plan was written, at `:307-308` after G2a and at `:314-315` on the tree this amendment was added to (2026-09-05). The disposition is unchanged — both are now session-geometry keys carried on the nch=1 path too, and the module constants remain as the frozen 0.8B fallback selftest [17] pins against.)*
- `sw/chat_seq.py`'s per-op vector lengths at `sw/chat_seq.py:1782`, `:1784`,
  `sw/chat_seq.py:1794`, `sw/chat_seq.py:1797`, `sw/chat_seq.py:1800`,
  `sw/chat_seq.py:1802`, `:1804` — `128`/`256`/`16`/`32` head-dim and
  NH=16 constants **inside a live scratch-footprint decoder**, which is wrong at
  LNH=32 rather than merely stale. Derive them from the geometry.
- `sw/hwmap.py:215`'s `SCRATCH_WORDS` becomes the single definition and the live
  duplicate in `tb/scripts/gen_seq_unit_vectors.py` becomes an import.
> **AMENDED 2026-09-01 (A2.3) — THIS CENSUS IS DISCHARGED BY DERIVATION, AND
> `RS_F = 7` DOES NOT RE-OPEN IT.** The bullets below were written when these
> sites were literals. This task's answer was to make them **derived**, and
> that answer is what makes the 2026-09-01 adoption a no-op on the host: the
> live path already reads `spec.rs_f` and lands on −21 at a 9B artifact by
> itself. **Do not now "update" `HEAD_LOGIT_EXP0` to −21** — it is the
> missing-key default, every 0.8B/2B artifact has no key, and −22 is correct
> for it. The task that revisits this **verifies** the five sites named in A2.3
> and changes none of them.

- The **three** hard-coded `RS_F` consumers the spec names —
  `sw/head_cache.py:105`, `sw/head_cache.py:638-639` and `sw/chat_seq.py:5032-5033` —
  read it from the manifest instead. `sw/head_cache.py`'s selftest tuple is
  derived from `spec` in the same pass. **And three sites the spec's census does
  not name, all of which break at `RS_F = 7`:**
  - `sw/chat_seq.py:238`, whose own comment derives the constant from
    `e=-4, sh=5, RS_F=8`. At `RS_F = 7` the correct value is **−21**, so
    **derive it** instead of carrying it. Three sites move with it: the literal
    assert at `sw/chat_seq.py:4453`; the head-spec comparison at
    `sw/chat_seq.py:2529`; and the one that already writes the algebra out at
    `sw/chat_seq.py:5032-5033`. Make that last form the definition and delete the
    literal.
  - **`sw/hwmap.py:356` `MANIFEST_META_KEYS`** must gain `rs_f`, and
    `split_manifest`'s `meta` dict must default it to **8**. Without both, a
    top-level `rs_f` key is handed to every caller as if it were a **wid** — the
    exact failure `emb_row_bytes` needed that split to avoid.
  - **The name collides and must be disambiguated.** `sw/head_cache.py:291`
    already emits `"rs_f"` **inside the per-image spec dict**, and
    `sw/head_cache.py:444` lists it among the per-image keys. A top-level
    manifest `rs_f` and a per-image `rs_f` in the same tree is a trap; pick
    distinct names or document the two scopes at both sites, and say which was
    done.
- The three SPTR masks in `sw/chat_seq.py` go 15-bit → 16-bit. **This is inert
  and stays inert until Task 7**: the RTL's SPTR field is still 15 bits at this
  gate, no 9B stream exists yet, and every 0.8B/2B address is below 32768. Land
  it here because the spec's census puts it here, and note the coupling so
  nobody reads a widened host mask as a widened hardware field.
- **D-TOK**: `sw/tok_meter.py` calls `plan_weights` with no `rows_of`, i.e. the
  nch-independent path, which cannot plan a 2B pack and cannot plan a 9B pack
  either — it collides with `EMB_BASE` and aborts before any DMA. Teach it the
  repack. Also turn `sw/tok_meter.py:544-545`'s `n*2` embedding stride into an
  assert against the EMBLOG2 shift: at 9B `2·H = 8192` **is** the power of two so
  they agree, and that coincidence must not be load-bearing.

**Two things in this area were hunted as simplifications and REJECTED by the
spec — do not do them.** Stripping `ref/model_select.py` or the multi-geometry
host tables: rejected, because `ref/` and `sw/` still serve the old bitstreams
and `model_select.MODELS` is the spine of Track F's per-geometry `--selftest`
matrix — **removing it would delete tests, not code.** Making EMBLOG2 a
compile-time constant: rejected, because the runtime CSR costs a 5-bit register
and making it constant deletes the R-b infrastructure the TB set exercises;
Task 10 takes the reset-value win instead, which is where the bug class lives.

One more that is **not** on the list and must not be treated as one: reducing
`nch` below 4 is not a simplification — it trades away throughput directly, and
nch=1 stays valuable as a bring-up rung.

- [ ] **Step 5: D-STAGE, D-DEAD, and the checker consequence D-DEAD carries**

**D-STAGE**: `tb/scripts/gen_chat_i1_vectors.py:298`'s staging mask is a bare
literal where its siblings derive theirs. It is *correct today* at the 0.8B
default and the harm is under-coverage, not a false pass — the `keep`
computation simply cannot name a word at or above 16384. Derive it from
`sw/hwmap.py`'s `SCRATCH_WORDS`, and **record whether deriving it changes any
committed i1 golden. It should not at 0.8B, which is the point of checking.**

**D-DEAD**: confirm `tb/scripts/gen_seq_vectors.py` is unreferenced — the
Makefile mentions it only in a comment and never invokes it — then **delete it
rather than migrating it.** If it turns out to be live, that discovery is itself
the finding and it goes to the user.

**And deleting it breaks the G2 spec-cites gate, which is a real consequence and
not a detail.** The spec cites eight lines of that file, and
`evidence/qwen_next/spec_cites.py` carries it in `ALIAS`; after the deletion
every one of those citations fails `EXIST`. Fix it the way `PENDING` is fixed —
deliberately, so a typo cannot hide:

- add a `RETIRED` set to `evidence/qwen_next/spec_cites.py` beside `PENDING`,
  containing `tb/scripts/gen_seq_vectors.py` with the commit that deleted it in
  a comment;
- report a citation to a retired path as `RETIRED`, not as a failure, in the
  same shape `PENDING` is reported;
- drop the stale `ALIAS` entry;
- re-run `./evidence/qwen_next/spec_cites.py` against the spec **and** this plan
  and require `SPEC CITES: PASS`, then re-run `--selftest` and require every
  negative control to be `CAUGHT`.

Also fix the three dangling citations the deletion leaves elsewhere:
`docs/QWEN35_NEXT_FEASIBILITY.md:790` lists the file as a migration site, and the
spec names it in §7.5 E and §7.6 C. Add dated supersession notes rather than
silently editing, in the house style.

- [ ] **Step 6: the documentation-accuracy work item**

The ledger folds two accuracy tails into this gate. Neither blocks the gate
verdict — the spec's own scope note calls the gate-doc cleanup optional
follow-on work — but both are work items and their disposition is recorded.

**(a) The 34 gate-doc short-forms.** Verified today:
`./evidence/qwen_next/spec_cites.py evidence/qwen2b/rc/RC_GATE.md evidence/qwen2b/rd/RD_GATE.md`
reports `FAIL 34` — short names the checker cannot resolve (layer_chan.sv,
regen_gate.sh, scan_spare_bits.py, audit_ranges_2b_report.md, …) plus one
genuine QUOTE miss. Resolve each by writing the full path in the gate doc, or
by adding the name to `ALIAS` where it is a real repo-wide convention. Target:
those two documents pass. **These are pre-existing and this migration did not
write them** — say so in the gate doc rather than implying they were introduced.

**(b) The 17 spec prose residuals.** The ledger records the count and no
enumeration exists on disk. So the first action is to *produce* the enumeration:
sweep the spec's prose claims against their primary sources in the class the
checker is structurally blind to — right-file, in-range, no quotation, wrong
line — and publish a numbered list with a disposition per item. **If the sweep
finds a different number, the sweep's number governs and the discrepancy is
recorded**, because a count carried forward from a review report is exactly the
kind of claim this campaign's review meta-note says to diff-verify rather than
trust.

- [ ] **Step 7: prove inertness, then commit**

The whole point of this task is that none of it moved a byte at the old
geometries:

```bash
bash evidence/qwen9b/run.sh g2/t4_bytes_unmoved_after.log \
  bash evidence/qwen2b/rc/t4_bytes_unmoved.sh
bash evidence/qwen9b/run.sh g2/regen_gate_after.log \
  bash ref/scripts/regen_gate.sh
bash evidence/qwen9b/run.sh g2/sw_boardfree.log \
  bash evidence/qwen2b/rd/rd_boardfree.sh
```

Required: `BYTES_UNMOVED PASS`, `REGEN_GATE_PASS`, `BOARDFREE_PASS`, the
three-tag `ref/` selftest sweep all-green (0.8b, 2b, 9b), the damage tests
failing on damaged code and passing on fixed code, and `SPEC CITES: PASS` on
the spec and this plan.

`evidence/qwen9b/g2/G2A_HOST.md`: the census with a disposition per row, the
before/after byte-lock logs, the damage-test outputs, the doc-accuracy
disposition, and the not-established list.

```bash
git commit -m "gate(G2a): host chain generalized at 9B — VREP, 24/8 slots, SCA at LNH=32, model-selected RS_F, defect B, sw/ literal census, D-STAGE, D-DEAD; 0.8B/2B bytes unmoved" \
  -- ref/gen_layer_script.py ref/gen_token_script.py ref/gen_model_script.py \
     ref/debug_torch_diff.py ref/layer_fixed.py ref/seq_chat.py \
     ref/audit_ranges.py ref/calib_stats.py \
     sw/infer.py sw/hwmap.py sw/seq_run.py sw/chat_seq.py sw/head_cache.py \
     sw/tok_meter.py \
     tb/scripts/gen_chat_i1_vectors.py tb/scripts/gen_seq_unit_vectors.py \
     tb/scripts/gen_seq_vectors.py \
     evidence/qwen_next/spec_cites.py \
     docs/QWEN35_NEXT_FEASIBILITY.md \
     docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md \
     evidence/qwen9b/g2/G2A_HOST.md evidence/qwen9b/g2/damage_defect_b.py
```

---

### Task 4: G2b — the final byte-lock pin

Small, and load-bearing out of proportion to its size. It runs **immediately
after Task 3 passes and before any Task 7 change lands**, because Task 7 spends
the lock permanently.

**Files:**
- Create: `evidence/qwen9b/g2/FINAL_BYTELOCK.md`
- Modify: `evidence/qwen2b/rc/RC_GATE.md`, `evidence/qwen2b/rd/RD_GATE.md`
  (dated supersession notes)

**Interfaces:**
- Consumes: Task 3's green tree.
- Produces: **the sha256 set of the 0.8B and 2B artifacts as they stand at this
  commit** — thereafter the record of what `build_034` and `build_035` were
  built from. Nothing downstream regenerates them.

- [ ] **Step 1: run the lock once more and record the shas**

Run `evidence/qwen2b/rc/t4_bytes_unmoved.sh` a final time and record its PASS.
Then record the artifact sha256 set — the frozen 0.8B chain
(`tb/scripts/w4/model_v2_s1.e*` and its weight images, hash lock `a69864d2…`,
nrec 60495), the 2B W8 chain (`tb/scripts/w5/model_w8_2b_s1.e*`), and the three
`.chip` goldens via `evidence/qwen2b/rd/rd_golden_shas.sh`.

**Read `rd_golden_shas.sh` correctly**: it carries no expected values and makes
no comparison, so it exits 0 regardless and "passing" it means nothing. It is a
**recording**, not a gate — which is exactly what this step needs it for.

- [ ] **Step 2: write the supersession notes into the old gate docs**

Dated notes in `RC_GATE.md` and `RD_GATE.md` saying: after G3,
`evidence/qwen2b/rc/t4_bytes_unmoved.sh` stops being runnable against the tree,
because the ARG re-encoding changes the emitted ARG words at every geometry.
**This project does not keep a v1.7 emitter path**: rebuilding 0.8B/2B artifacts
from the post-migration tree is declared **unsupported** — those artifacts
already exist, are pinned here, and the bitstreams that consume them are frozen.
Anyone who finds the byte-lock failing after G3 should read the note, not debug
the script.

- [ ] **Step 3: commit**

```bash
git commit -m "gate(G2b): final byte-lock pin — 0.8B/2B artifact sha256 set recorded; supersession notes in RC/RD gate docs" \
  -- evidence/qwen9b/g2/FINAL_BYTELOCK.md evidence/qwen2b/
```

---

### Task 5: G2c — the 9B artifact chain: goldens, GPTQ at scale, images, fit

Host only, snoke, heavy. This builds everything in the 9B chain that **does not
need the 16-bit ISA**. The SEQ streams are Task 11's, for a reason stated below.

**Files:**
- Modify: `ref/gen_model_script.py` (9B geometry paths, untied head, manifest
  `rs_f`), `ref/load_qwen35.py` and `ref/calib_stats.py` (the untied-head sites)
- Create: `evidence/qwen9b/g2/G2C_CHAIN.md`, `evidence/qwen9b/g2/run_g2c_*.sh`
- Test: `plan_weights` fit; both range tools; the fidelity harness re-run
  through the emitted artifacts

**Interfaces:**
- Consumes: Task 3's generalized emitters; Task 1's `RS_F` and state law.
- **Two of the listed products already exist and are Task 1's inputs — REUSE
  them, do not rebuild them.** Neither is committed — both are gitignored
  regenerable caches with **pinned sha256s**, which is what makes reuse safe and
  hashing mandatory. The 9B bf16 golden is on disk at
  `evidence/qwen_next/ladder/golden_bf16_9b.npz` with its sha256 in
  `evidence/qwen_next/ladder/LADDER.md`, and the 24.06 GiB Hessian is on disk
  with its sha256 in
  `evidence/qwen_next/ladder/calib_9b.log`. Verify both by hash against those
  records first; **rebuild only if a hash fails or the file is gone**, and say
  which happened. Rebuilding a matching artifact costs 40 min and buys nothing.
- Produces (regenerable, **not committed** — sha manifest in the gate doc):
  - the 9B bf16 torch golden — on disk, **gitignored by `.gitignore:39`** as a
    regenerable cache with its sha256 pinned in `LADDER.md`;
    **verified, not rebuilt** (above);
  - `ref/calib_stats_9b_h.npz`, the 24.06 GiB Hessian, on the 21 TB NFS pool —
    **verified, not rebuilt** (above);
  - the quantized **W4 g128 + GPTQ** image set — **249 images**,
    **4,091,805,696 bytes/token** (3,902.2 MiB);
  - the flat int16 embedding table, **248,320 × 4096 × 2 B = 2,034,237,440 B =
    1,940.0 MiB**, at `EMB_BASE` on channel 0;
  - the LM head as a **separate tensor**, quantized separately and packed
    chunk-interleaved into the weight pack at `W_BASE`. Its packed W4 g128
    footprint is a `plan_weights` output, not a number anyone invents; the spec
    assigns *recording* it to G3, but the number exists here, so **record it in
    this gate doc and carry it forward into Task 7's** rather than measuring it
    twice;
  - the per-channel `plan_weights` fit, with the **real** per-channel tops
    recorded — the projection is busiest channel 978.6 MiB = 76.5 % of the
    1,280 MiB window;
  - the re-derived chat template.

- [ ] **Step 1: the untied-head producer sites — four, not six**

Two of the study's six are already done and must come out of the tally:
`ref/perplexity_eval.py` and `ref/fidelity_check.py` got `CkptSource.head()`
and the `head_f`/`emb_f` split from Track L. **Four sites remain**: the emitter,
`ref/seq_chat.py`, `sw/infer.py`, `ref/audit_ranges.py`, plus the `isinstance`
filter in `ref/calib_stats.py` where an untied `nn.Linear` head collides with
`HEAD_KEY`. Each takes one variable assignment. **No RTL, no new wid, no new DDR
region.**

The regression already exists and must be run: `ref/gen_token_script.py` draws
head and table as two independent random matrices and every `token_s*` TB runs
that untied pair through the whole chain.

- [ ] **Step 2: the torch golden and GPTQ at scale**

Hash-check the golden and the Hessian against their committed records first,
and skip this step's compute entirely if both match — which is the expected
outcome, since Track L built them and G1 has just used them. The rest of this
step applies only when a rebuild is actually required.

Measured at 9B, for that case: **40.23 min** (183.5 s load
+ 2,230.1 s pass) at **8 threads**, against 19.1 priced — 2.11× over. Built
once, amortized. The calibration corpus is `ref/ppl_corpus_calib.txt`, **disjoint
from the pinned eval slice** by construction, and `calib_stats` refuses the eval
corpus by filename unless explicitly overridden — do not override it.

The Hessian is one float32 K×K per input *site*, 129 sites, FFN sites at
K=12288 → **24.06 GiB**. It lands on the NFS pool, not snoke's local 458 GB.
Record its sha256 (the tool prints it as its last line) in the gate doc; the npz
itself is gitignored and is deleted once the points that need it are scored.

Carry the caveat: **GPTQ is calibration-dependent by construction and a
deployment far from this corpus sees less.**

- [ ] **Step 3: emit the image set and record the fit**

Emit at 9B with the ratified operating point — `--wq=w4`, `--w4-group=128`,
GPTQ via the calib env pair, `--res-scale=1`, and **`FABLE5_RS_F=7`
(A2.2 — the adopted 9B operating point, superseding "Task 1's `RS_F`", which
was 8)**, so the manifest carries `rs_f: 7`. **Do not export that variable
beyond the 9B emission** — A2.5. If the
runtime range audit trips on clips, record and evaluate before reaching for
`--allow-clip`; a new clip class is a `DONE_WITH_CONCERNS` report, not a flag.

Then the fit. **`plan_weights` with `rows_of` is the per-channel repack**, and
the assertion that matters is inside it: every channel's top must be below
`EMB_BASE`. Record the **real** per-channel tops — the gate doc carries the
measured numbers, not the projection. **No `EMB_BASE` change is needed at W4**;
the zero-slack embedding-channel problem is a W8-only problem and this build
does not have it.

Channel 0 is the one to watch, and its total is this plan's addition of three
figures rather than a tool output: 256 MiB (`W_BASE`) + 978.6 + 1,940.0 =
3,174.6 of 4,096 MiB **(S)**. **This step is the gate that measures it.**

- [ ] **Step 4: both range tools, and the fidelity harness through the emitted chain**

Run `ref/audit_ranges.py` and `gate_port_probe.py` at 9B against the *emitted*
artifacts and require clean, or a waiver with evidence. Then re-run the fidelity
harness at 9B and require it to **reproduce Task 1's numbers through the emitted
chain, not just through the reference model** — same golden, same prompts, same
`--ntok 24 --free-ntok 12`. A divergence here means the emitter and the model
disagree, and that is a stop, not a note.

- [ ] **Step 4′: OPTIONAL — `RS_F = 7` under `int16` (A1.8)** — **DONE 2026-09-01; the answer was TAKE IT**

> **EXECUTED, and the ruling came back ADOPT (A2).** The step ran exactly as
> written — on explicit instruction, deciding nothing itself, going back to the
> user because the ratified O5 condition was met. Result at the shipped
> container: clips **23 → 0**, `|x|max` **32767 → 29916** (off the rail), top-1
> **95 → 98**, **rank max 5 and top-5 3.69 unmoved**, coherent text ×4, and a
> confirming repeat whose `diff` over the report body returns **one line**.
> Single-variable by construction: same quantizer digest, both caches HIT, and
> `--wq-cache-verify` byte-identical under the new value — `RS_F` demonstrably
> does not reach the quantizer.
> **Consequence for this task: Step 3 now emits with `FABLE5_RS_F=7` and the
> manifest carries `rs_f: 7`.** Nothing below is an instruction any longer.

*(The step as written, kept as the record of what was asked and why:)*

**`RS_F` stays 8 and this step does not change that.** G1 measured the rider
twice and the two results disagree in **sign**: at the global `int8:6` container
it was free (top-1 72 → 73), at the per-row container it cost five tokens
(94 → 89) and worsened rank max (13 → 18). **Its sign under `int16` — the
container that actually ships — cannot be inferred from either and is
unmeasured.**

It is cheap: `RS_F` is an env knob, not a source edit, so it does not move the
quantizer digest and runs on the **warm** cache — **≈ 3.8 h** for one 168-step
point at `FABLE5_DN_STATE=int16 FABLE5_RS_F=7`, against the `int16` baseline of
95/108, rank max 5, top-5 3.69, 23 clips.

**Take it only on an explicit instruction.** If it is not taken, the gate doc
**says the question is open** rather than implying it was settled — and if it is
taken and Q8.7 removes the clipping at no top-1 cost, that is a ratified-O5
condition met and it goes back to the user before anything acts on it, because
it moves `rtl/conv4_silu.sv:50` and a set of host constants that Task 10 has
otherwise been told not to touch.

- [ ] **Step 5: re-derive the chat template**

`chat_template.jinja` and `tokenizer_config.json` **differ** between 0.8B/2B and
4B/9B — a 12-line diff over 3 of 154 lines that **inverts the `enable_thinking`
default**: 0.8B/2B emit a closed `<think>\n\n</think>\n\n` unless asked for
thinking; 4B/9B emit an **open `<think>\n`** unless asked *not* to. Rebuild the
host-side id-spliced template and re-derive the `ntok >= 24` UX guidance.

The **tokenizing** files are byte-identical across all four models, so the
pinned PPL corpus and its 24,528 positions carry over unchanged. Say which is
which in the gate doc; the two facts are routinely conflated.

- [ ] **Step 6: gate doc + commit**

`evidence/qwen9b/g2/G2C_CHAIN.md`: provenance, artifact shas, the **measured**
per-channel fit table, both range-tool outputs, the fidelity reproduction, the
template diff and its UX consequence, and the explicit note that **the SEQ
streams are not in this gate** — a 9B layer body peaks at 50,208 scratch words
against a 32,768-word 15-bit ISA ceiling, so the streams cannot be emitted until
Task 7 lands the 16-bit encoding. Task 11 emits them.

```bash
git commit -m "gate(G2c): 9B artifact chain — untied head producers, GPTQ at scale, 249-image W4 g128 pack, measured per-channel fit, both range tools, template re-derived" \
  -- ref/gen_model_script.py ref/load_qwen35.py ref/calib_stats.py \
     ref/seq_chat.py ref/audit_ranges.py sw/infer.py \
     evidence/qwen9b/g2/G2C_CHAIN.md evidence/qwen9b/g2/run_g2c_emit.sh \
     evidence/qwen9b/g2/run_g2c_fit.sh
```

---

### Task 6: O3 — the shared board flock, mechanized

**PARALLEL-SAFE.** Touches only `sw/`, `docs/` and `evidence/qwen9b/o3/`. It may
be executed at any point from Task 3 onward. **Task 15 is BLOCKED until this is
green** — per O3 the lock must exist before any tool programs or DMAs the board.

The user ruled O3 on 2026-08-29: **shared flock, mechanized — a single
NFS-visible lock file, holder identity, taken by every tool that programs or
DMAs the board.**

**Files:**
- Create: `sw/board_lock.py`, `evidence/qwen9b/o3/BOARD_LOCK.md`
- Modify: `sw/chat_seq.py`, `sw/serve.py`, `sw/cycle_census.py` (adopt the shared
  path), `sw/seq_run.py`, `sw/infer.py`, `sw/tok_meter.py`, `sw/mover_bench.py`,
  `sw/layer_test.py`, `sw/matvec_test.py`, `sw/ddr_test.py` (take it for the
  first time), `sw/program_fpga.sh`, `docs/USAGE.md`, `docs/ARCHITECTURE.md`
- Test: a two-process contention test; a two-worktree contention test; every
  adopting tool's own selftest

**Interfaces:**
- Consumes: the existing `SeqLock` implementation in `sw/chat_seq.py:367-386` —
  `flock(LOCK_EX|LOCK_NB)` on a file whose first 256 bytes name the holder,
  written as `pid <pid> <tool> <ISO ts>` and truncated on release. **This is the
  design; it is the path that is wrong, not the mechanism.**
- Produces:
  - `sw/board_lock.py` exposing `BoardLock(path=BOARD_LOCK_PATH, tool=...)` with
    `acquire()` / `release()` / context-manager semantics and the same
    holder-identity contract, plus `BOARD_LOCK_PATH` resolved in this order:
    `$FABLE5_BOARD_LOCK`, else a repo-independent NFS-visible default under the
    shared tree (**not** under any one checkout's `sw/`).
  - `sw/chat_seq.SeqLock` becomes a thin alias so no caller breaks.
  - Every board-touching tool holds it, and `sw/program_fpga.sh` holds it across
    the whole remove → JTAG → rescan sequence.

- [ ] **Step 1: write the contention test FIRST (RED)**

Before moving anything: a test that starts two processes against the intended
shared path from **two different working directories** and requires the second to
be refused with the first's identity in the message. On today's tree it passes
trivially within one checkout and **fails across checkouts**, which is exactly
the defect — `sw/.seq.lock` is per-checkout, so it does not exclude the other
worktree's tools. There are two checkouts on this machine today.

Capture the RED. This is the whole point of O3 and it must be demonstrated, not
described.

- [ ] **Step 2: the shared path, and the NFS question answered explicitly**

`flock` over NFS works on modern Linux NFSv4 but is worth proving rather than
assuming: add a startup probe that acquires and releases the lock once and
records the filesystem type, reusing the existing `_fstype` helper in
`sw/head_cache.py` (note its polarity is the opposite — it *refuses* NFS for the
head cache, and this code *requires* it to work). **If the probe cannot
demonstrate mutual exclusion across two hosts, that is a finding and it goes to
the user**, with the fallback being a lock on snoke's local filesystem plus a
rule that only snoke touches the board.

Pick the default path so it is visible from every checkout and from every host
that can reach the board, and record the choice with its reason.

- [ ] **Step 3: every board-touching tool takes it**

Today only `sw/chat_seq.py`, `sw/serve.py` and `sw/cycle_census.py` lock.
`sw/infer.py`, `sw/seq_run.py`, `sw/tok_meter.py`, `sw/mover_bench.py`,
`sw/layer_test.py`, `sw/matvec_test.py` and `sw/ddr_test.py` do not — and
`mover_bench` clobbers stream images with no lock at all. Add the lock to each,
with a `--no-lock` escape that must be passed explicitly and is logged loudly.

`sw/program_fpga.sh` is the important one: **the reprogram sequence must hold
the lock from before `pcie_helper.sh remove` until after `rescan`**, because
that is the window in which the device disappears from under any other user.

Update `docs/USAGE.md` §5's takes/does-not-take table, which is currently
accurate and will otherwise become wrong, and close the follow-on rows in
`docs/ARCHITECTURE.md` and `docs/HISTORY.md`.

- [ ] **Step 4: GREEN + gate doc + commit**

The Step-1 test now passes across checkouts. Every adopting tool's selftest
stays green (`make -C sw seq_selftest serve_test`, `chat_seq.py --selftest`,
including its existing lock selftest block). The board is **not** touched by
this task.

`evidence/qwen9b/o3/BOARD_LOCK.md`: the RED capture, the path decision with its
reason, the NFS probe result, the adoption table, the two-worktree
demonstration, **and the `--no-lock` escape written out by name** — which tools
accept it, what it logs, and the standing rule that it is for a human who has
confirmed sole use of the board, never for a script working around a stuck lock.
An escape hatch that lives only in `--help` is an escape hatch nobody audits.

```bash
git commit -m "sw(O3): shared board flock — single NFS-visible lock, holder identity, taken by every board-touching tool and by the reprogram sequence" \
  -- sw/board_lock.py sw/chat_seq.py sw/serve.py sw/cycle_census.py \
     sw/seq_run.py sw/infer.py sw/tok_meter.py sw/mover_bench.py \
     sw/layer_test.py sw/matvec_test.py sw/ddr_test.py sw/program_fpga.sh \
     docs/USAGE.md docs/ARCHITECTURE.md docs/HISTORY.md \
     evidence/qwen9b/o3/
```

---

### Task 7: G3.1 — the 16-bit scratch ISA: RTL, emitter, and every decoder

**THIS IS WHERE THE BYTE-LOCK IS SPENT.** Task 4 must have pinned it first.
This is the change with the widest reach in the migration and the one whose
census this campaign already got wrong once, so the mechanization — not care —
is the mitigation.

**Files:**
- Modify RTL: `rtl/layer_chan.sv` (the ARG decode, the scratch arrays, every
  internal address signal, SPTR, the `s_axib` window, the new DNSB CSR),
  `rtl/vec_alu.sv`, `rtl/seq_movers.sv`, `rtl/seq_unit.sv` (`LAYB_BASE`, the ARG
  shadow), the IPI wrapper's `ADDR_WIDTH`, and
  **`synth/scripts/create_project.tcl`** — the block design hard-codes the
  `m_axib` map and **exits 1 on any range it does not expect**, so a widened
  window that skips this file fails the build rather than the sim
- Modify host: `ref/gen_layer_script.py` (the canonical encoder),
  `ref/seq_model.py`, `ref/seq_format.py`, `sw/chat_seq.py`,
  `tb/scripts/gen_seq_layer_script.py`, `tb/scripts/gen_seq_unit_vectors.py`
- Modify TBs (spec §7.5 family B + D-TBUNIT): `tb/tb_seq_unit.sv`,
  `tb/seq_stub_layer.sv`, `tb/tb_layershim_c.sv`, `tb/tb_seq_chip.sv`,
  `tb/tb_vecalu_diff.sv`, `tb/tb_vec_alu.sv`, `tb/tb_burst_fabric.sv`
- Modify docs: `docs/SEQ_ISA.md` → v2.0
- Create: `evidence/qwen9b/g3/isa_bits.py`, `evidence/qwen9b/g3/G3_1_ISA.md`
- Test: `make -C tb tb_seq tb_seq_guard tb_seq_lat tb_seq_sideband tb_seq_burst
  tb_layershim_c tb_bfab tb_vec_alu tb_vecalu_diff tb_layer_chan tb_seq_layer
  lint_seq lint_seq_unit lint_seq_burst`, plus `evidence/qwen9b/g3/isa_bits.py` and its negative
  control

**Interfaces — the ISA contract every other task reads:**

- **The pair layout, everywhere, with no exceptions:**
  `ARG1 = {hi[31:16], lo[15:0]}`, and the same for `ARG2` where a command needs
  a second pair. **No scattered bits anywhere.** The R-b 15-bit bit-scatter is
  deleted, not extended.
- **Per-command arg words** (spec §4.3's table; `evidence/qwen9b/g3/isa_bits.py` proves each fits):
  - `VN` — ARG0 `{…, nlog2[3:0], mode[1:0]}`; ARG1 `{dst, src}`; ARG2 xrf/eps
  - `VNW` — ARG0 `ld_n[12:0]`, **no escape encoding**: 13 bits hold 4096
    directly, so `0` means 0 and is refused by an emitter assert
  - `ROPET` / `ROPE` — ARG1 `{dst, src}`
  - `CONVW` — ARG0 `{nch[13:0], first[13:0], sel[1:0]}`; ARG1 `{–, src}`
  - `CONV` — ARG0 `{nch[13:0], first[13:0]}`; ARG1 `{dst, src}`
  - `GATE` — ARG0 `{–, dst[15:0]}`; ARG1 `{src_a, src_b}`; ARG2 `{src_dt, src_A}`
  - `KVAP` — ARG0 `{expbias[4:0], kvhead[1:0]}`; ARG1 `{src_v, src_k}`
  - `ATTN` — ARG0 `kvhead[1:0]`; ARG1 `{dst, src_q}`
  - `ALU` — ARG0 `{spare[31:19], p0[16]@18, len[13:0]@17:4, aop[3:0]}`;
    ARG1 `{srcb, srca}`; ARG2 `{dst[31:16], p0[15:0]}`. **One relocation**:
    `p0` is 17 bits, so its top bit moves into ARG0's spare — a bit proven spare
    over 293,768 ALU dispatches. `cfg_len` grows 13 → **14 b** with it (wall 3).
  - `DNST` — ARG0 `{spare[31:5], head[4:0]}`; ARG1 `{src_k, src_q}`;
    ARG2 `{dst, src_v}` — **69 of 96 bits, 27 spare**
- **New layer CSR `DNSB` at byte offset `0x5C`** — the next free word in
  `layer_chan`'s decode (`awaddr[11:2] == 10'h017`; `0x58 TK_IDX` is the last
  one used today). Layout `{a_dec_base[31:16], a_beta_base[15:0]}`, written
  **once per layer body** by one CSRWR record, not once per command. CSRWR
  target word `0x005C` — `t[15:12] == 0` routes to `LAYER_BASE + t[7:0]`, which
  is already legal in the sequencer's target validation. Hardware forms
  `a_dec = a_dec_base + head` and `a_beta = a_beta_base + head`: two 16-bit adds
  with a 5-bit addend, in the DNST decode, off the lane datapath.
- **`SPTR` (layer CSR `0x14`) takes `wdata[15:0]`.** Every internal address
  signal in `layer_chan` — `sptr`, `hw_addr`, `sa/sb/sw_addr`, `eng_sa/eng_swa`,
  `ld_src`, `dst_r`, `src2_r`, `alu_aa/ba/wa`, `bw_addr/br_addr`, `wa_ptr` — and
  `vec_alu`'s `cfg_srca`/`cfg_srcb`/`cfg_dst` go `[14:0]` → `[15:0]`.
- **The scratch arrays become `[65536]`** (S4: fully backed, no MLP chunking,
  no unbacked hole). `seq_movers`' `SCR_WORDS` and `cmd_saddr` follow.
- **`LAYB_BASE` moves `32'h0006_0000` → `32'h0008_0000`.** The AXI segment
  becomes exactly 256 KiB and must be range-aligned; `0x60000` is not
  256 KiB-aligned and `0x80000` is. The burst map becomes: mvchan `c` at
  `(c+1) << 16` (unchanged), layer_0 at `8 << 16` covering `0x80000–0xBFFFF`,
  and the decode hole grows to `0x50000–0x7FFFF`. `layer_chan`'s `s_axib`
  address grows 17 → **18 bits** and the IPI wrapper's `ADDR_WIDTH` with it.
  **Three coupled edits in `synth/scripts/create_project.tcl`, all required,
  because the block design hard-codes this map and FATALs on any range it does
  not expect:** the `seq_axib_map` entry for `layer_0`
  (`synth/scripts/create_project.tcl:479-480`) moves to
  `0x80000`; the per-slave range expectation
  (`synth/scripts/create_project.tcl:496-505`), which asserted 131072
  / `"128K"` for `layer_0` and `exit 1`s otherwise, becomes 262144 / `"256K"`;
  and the R-b provenance comment naming the mirrors
  (`synth/scripts/create_project.tcl:464-478`) gains the dated
  9B note. The two-pass parking still works — `layer_0` is index 4, parked at
  `0x840000`, which is 256 KiB-aligned and clear of the four 64 KiB mvchan
  parking slots ending at `0x83FFFF`.
  `tb/tb_burst_fabric.sv`'s `LAYBASE` follows; its `mvbase` expression does
  **not**, because the mvchan windows do not move. That TB is the confirmation
  of this re-alignment, not an afterthought.
- **The layout authority** from Task 3: `beta_base`, `decay_base`, `LNH` come
  from the SCA tile map, and the DNSB values the emitter programs are
  `a_beta_base = beta_base`, `a_dec_base = decay_base`.
- **Named fallback, if the affine relation ever has to be broken:** a **fourth
  arg word** — `ARG3` at a free `layer_chan` CSR offset (`0x60`, the next word
  after DNSB), mirrored in `rtl/seq_unit.sv`'s ARG shadow. Cost is one extra
  CSRWR record per DNST command — 768 DNST/token at 9B ≈ 6 KiB/token against
  3.9 GB/token of weights. Cheap, mechanical, and strictly larger a change than
  the affine map; **taken only if needed**, and not built speculatively.

- [ ] **Step 1: the mechanization FIRST, red against today's tree**

Write `evidence/qwen9b/g3/isa_bits.py` before touching an encoder. It must do
three things, and the third is the one that matters:

1. **Bit budget** — for every command, sum the field widths against 96 arg bits
   and print the spare, so `DNST`'s 101-of-96 problem and its 69-of-96 solution
   are both visible.
2. **Encoder ↔ decoder equivalence** — the pair layout is implemented
   *independently* in **three** places: the canonical emitter, `sw/chat_seq.py`'s
   decoder, and the RTL. **Five sites need an edit; three of them are
   independent implementations** — the other two delegate to the canonical
   helpers and hand-code only the DNST bit-30/31 scatter. The script must round-
   trip every command through **all three**, at boundary addresses (0, 1, 32767,
   32768, 65535) and at random ones, and require agreement. Reading only the
   encoder and the RTL field list would prove nothing about the decoders.
   Extract the RTL's field slices by parsing `rtl/layer_chan.sv`, in the AST
   style Track L's `E-pre` check established — not by transcribing them.
3. **A negative control** — perturb one field width and require the script to
   refuse. A checker that cannot fail proves nothing.

Run it against today's 15-bit tree: it must PASS on the old layout, which is how
you know the harness itself is right before the layout moves.

- [ ] **Step 2: generalize `m_gate` BEFORE switching on the layout assert**

`tb/scripts/gen_seq_layer_script.py`'s `m_gate` is the layout authority the
DNST assert will be anchored to — and it is itself a family-D defect,
hard-coding `np.zeros(32)`, `range(16)` and `out[16 + h]` for LNH=16. **An
assert anchored to an un-generalized authority would ratify the very layout it
is meant to police.** Generalize it to `LNH` first, in this same change, and run
the negative control against the generalized version.

The DNST assert then requires `a_dec == decay_base + h` **with `decay_base`
obtained from the map, not recomputed at the call site**. A self-consistency
assert — "the `a_dec` I emitted equals the `a_dec_base + h` I programmed" —
**passes while both sides are wrong**; it would have sailed straight through the
`GD + 16 + h` aliasing Task 3 fixed, because base and pointer derive from the
same literal. G3's negative control is a perturbation of the map that must make
the assert fire.

- [ ] **Step 3: land the encoding — RTL, emitter, decoders, in one change**

The five sites move together or the tree is broken between them. Rewrite the
canonical helpers (`enc_saddr`, `enc_a1`, `dec_a1_lo`, `dec_a1_hi`,
`enc_alu_a2`, `dec_alu_dst`, and `dnst`'s hand-OR of bits 30/31), the two
delegating sites' hand-coded scatters, `sw/chat_seq.py`'s `_lo`/`_hi` unpack and
its DNST/ALU special cases, and the RTL's `a1_src`/`a1_dst`/`a2_src`/`a2_dst`
plus the `vec_alu`, DNST and GATE wirings.

`ref/seq_format.py` is **not** a fourth independent implementation — it imports
the canonical helpers — but it is the largest consumer, with ~35 sites that open
ARG words and rebuild them: the peephole emitter, `ALU_LEN_MAX`, the `disasm`
decoders, the attention block, and the DN block-float rewriter. Sweep it with
`/usr/bin/grep` and fix every one; `evidence/qwen9b/g3/isa_bits.py`'s round-trip must cover it.

`tb/scripts/gen_seq_unit_vectors.py`'s ALU packer is still **14-bit** with no
bit-14 scatter at all, so the live seq_unit vectors never exercise a high-half
ALU address. At 16-bit it does not need widening — **it encodes a layout that
will no longer exist.** Rewrite it, and add a directed high-half case so the
gap it left is closed rather than moved.

- [ ] **Step 4: the TB family-B census, and the checker bug inside a checker**

Work spec §7.5 B. The highest-value item is **`tb/tb_seq_unit.sv:967`**, which
truncates the golden MEM address to 15 bits **inside a checker**, with no range
guard at the parse site. At 16-bit addressing every golden address ≥ 32768
aliases down by 32K and the checker compares the wrong word — **a silent pass,
not a failure.** It is an unfixed instance of a bug already diagnosed and fixed
in its sibling: `tb/tb_seq_chip.sv:76-86` documents it, `:707-709` implements the
parse guard and `tb/tb_seq_chip.sv:1039` the derived slice. **Copy that fix; do not re-invent it.**

The rest of the family: the `32'd32767` scratch bound and the XWIN test in the
same file plus its read-channel twin; `tb/seq_stub_layer.sv`'s `smem [32768]`
and three 15-bit address signals, and the latent 14-bit increment into a 15-bit
register one line away; `tb/tb_layershim_c.sv`'s `[16:0]` AXI byte address —
one bit short at 16-bit — and both `32768 - n` top-of-window burst placements;
`tb/tb_vecalu_diff.sv`'s 15-bit `n_*` against the frozen 14-bit legacy copy,
whose "the extra bit is always 0" argument needs restating at 16;
`tb/tb_vec_alu.sv`'s 15-bit `cfg_*`, `mem [32768]` and the R-c long-length case
that deliberately parks `LD = 16384` in the high half — and **`tb/tb_vec_alu.sv:29`'s
13-bit `cfg_len`, which caps at 8191 and breaks at FFN=12288**: it is wall 3's
TB twin and the spec's §4.6 did not name it.

`tb/tb_seq_chip.sv:76`'s `MAXMEM` is the good example — everything downstream is
derived from it, so only that line moves. `tb/scripts/gen_seq_layer_script.py`'s
high-half map, its `B_TOP` "last 8 words of the 32K scratchpad", the fold-down
images and the aliasing-sentinel rationale all re-derive at 16-bit.

**Do not mine `tb/scripts_scratch/`.** It carries a pre-R-b `SCR_WORDS = 16384`
in a scratch tree; it is not a migration site and not a reference.

- [ ] **Step 5: `docs/SEQ_ISA.md` v2.0, and keep the old tables**

New pair layout, the DNST/DNSB note, the per-op table, the SEQ records, and the
in-RTL copy in `rtl/layer_chan.sv`'s header. **Retain the old 15-bit tables,
marked as `build_034`/`build_035`'s ISA, because those bitstreams still run.**
Fix the in-tree stale comments listed under D-CITE **that live in this task's
files**: the "16K x 16" scratch comment (the arrays are 32768 deep today and
65536 after this task), `ref/gen_layer_script.py`'s stale docstring self-cite,
and `sw/chat_seq.py`'s docstring citing a dispatcher and a helper range that
have both moved. **The two `rtl/matvec_engine.sv` pointers that name wrong lines
belong to Task 9**, which rewrites that file; fixing them here would edit a file
this task does not own.

- [ ] **Step 6: GREEN, and retire a stale warning that is not a red**

Run the suite. `evidence/qwen2b/rc/t4_widen_gates.sh` is the existing driver for
the widening classes and is the right shape to reuse; on snoke pass the
interpreter overrides, because `ref/.venv/bin/python` is a **dangling symlink**
there (Standing hazards).

**`tb_seq_offifo`: the test is GREEN, and the WARNING is what is stale.** The
Makefile still prints, ahead of the directed push/pop race section, that it
"FAILS on `rtl/seq_unit.sv` as of 2026-08-11 … PRE-EXISTING, also present at
HEAD". **It is not present at HEAD.** The recorded fix's *after*-side is in the
tree: `rtl/seq_unit.sv:1342` carries the unconditional `of_rp` advance and
`rtl/seq_unit.sv:1503` the conditional pop strobe, both matching
`evidence/rung4/S6_out_fifo_pop_race.patch`; `git log ec4216d..HEAD --
rtl/seq_unit.sv` is **zero commits**, and `ec4216d` is the R-b full-sim-gate
commit (verified 2026-08-29).

So the disposition is neither of the two an earlier revision of this plan
offered. **Run it, confirm green, then delete the stale echo.** Do *not* "land
the recorded fix" — it is landed, and force-applying the patch would revert the
conditional strobe and **reintroduce the token-loss race**. Do *not* exclude it
— it passes. **Invoke it by name**: `evidence/qwen2b/rc/t4_widen_gates.sh` runs
`tb_vec_alu tb_vecnorm tb_ru2_diff tb_layer_chan tb_token tb_seq_layer` and does
**not** include `tb_seq_offifo`, so leaning on that driver would leave it unrun
— which is how a stale warning survives a whole campaign. Record the green run
and the deleted echo in the gate doc.

- [ ] **Step 7: gate doc + commit**

`evidence/qwen9b/g3/G3_1_ISA.md`: the bit budget with spare per command, the
three-way equivalence result and its negative control, the DNST-assert negative
control, the family-B census with a disposition per row, the `tb_seq_offifo`
disposition, and the statement that `evidence/qwen2b/rc/t4_bytes_unmoved.sh` is
now **retired by design** with a pointer to Task 4's pin.

```bash
git commit -m "gate(G3.1): 16-bit scratch ISA — clean 16+16 pairs, DNSB CSR base pair, 65536-word scratch, LAYB_BASE realigned; encoder/decoder equivalence mechanized with negative controls" \
  -- rtl/layer_chan.sv rtl/vec_alu.sv rtl/seq_movers.sv rtl/seq_unit.sv \
     synth/scripts/create_project.tcl \
     ref/gen_layer_script.py ref/seq_model.py ref/seq_format.py \
     sw/chat_seq.py \
     tb/tb_seq_unit.sv tb/seq_stub_layer.sv tb/tb_layershim_c.sv \
     tb/tb_seq_chip.sv tb/tb_vecalu_diff.sv tb/tb_vec_alu.sv \
     tb/tb_burst_fabric.sv tb/Makefile \
     tb/scripts/gen_seq_layer_script.py tb/scripts/gen_seq_unit_vectors.py \
     docs/SEQ_ISA.md \
     evidence/qwen9b/g3/isa_bits.py evidence/qwen9b/g3/G3_1_ISA.md
```

---

### Task 8: G3.2 — `vecnorm_unit` at N = 4096

Small, self-contained, its own test cycle. **May run in parallel with Task 9 —
with one shared file.** The RTL, the TBs and the obj_dirs are disjoint, but both
tasks edit `tb/Makefile` (this one adds the 4096 vector set and moves
`tb_vecnorm`'s `+guardtest` expected string; Task 9 retires the W8/g64 targets
and moves `tb_matvec_ng`'s), and both write into `evidence/qwen9b/g3/`. Sequence
the two `tb/Makefile` edits, or run the tasks serially — do not let two agents
write it at once — and give each task its **own** gate-doc filename inside `g3/`
so the pathspecs never overlap.

**The same hazard runs through `sw/`, and it is why every pathspec in this plan
names files rather than directories.** `sw/chat_seq.py` is touched by Tasks 6, 7
and 9; `sw/infer.py`, `sw/tok_meter.py` and `sw/seq_run.py` by Tasks 3, 6 and 9.
Task 6 is the parallel-safe one, so **Task 6 rebases onto whichever of those has
landed and never commits a `sw/` directory pathspec** — the 2026-08-25 near-miss
was exactly a directory pathspec sweeping another track's staged files. It is the same widening R-b performed
once, 1024 → 2048, including the `n_total` wrap-to-zero deadlock that widening
uncovered — precedented, costed, not free. `vecnorm_unit` sits on the layer
critical path.

**Files:**
- Modify: `rtl/vecnorm_unit.sv`, `rtl/layer_chan.sv` (the `vn_waddr` port and the
  VNW count latch), `ref/gen_layer_script.py` (**the emitter assert that replaces
  the retired VNW escape — this lands in the same change as the RTL deletion, or
  the escape is retired with nothing in its place**), `tb/tb_vecnorm.sv`,
  `tb/tb_vecnorm_diff.sv`, `tb/scripts/gen_seq_c_vectors.py`, `tb/Makefile`
  (the 4096 vector set)
- Test: `make -C tb tb_vecnorm tb_vecnorm_diff tb_layer_chan lint_seq`

**Interfaces:**
- Consumes: Task 7's ARG layout — `VNW`'s count is `ARG0[12:0]` with **no escape
  encoding**.
- Produces: `cfg_nlog2 = 12` legal; `xbuf`/`wbuf` 4096 deep; `w_waddr` 12 b.
  Consumed by Task 10's envelope check (`cfg_nlog2 > 12` → sticky error) and by
  Task 11's streams.

- [ ] **Step 1: widen, exactly at the verified sites**

The counters `cnt`/`n_total` and `oidx`/`ecnt` go 12 → **13 b** — the comment
beside them says "12 bits: n_total = 2048 must FIT" and it is the wrap site the
`$fatal` guards. `xbuf`/`wbuf` go 2048 → **4096**. `vecnorm_unit`'s `w_waddr`
input and `layer_chan`'s `vn_waddr` go 11 → **12 b**. The guard that reads
"max 11, N=2048" moves from `>= 12` to `>= 13`, and `n_total <= 12'd1 << cfg_nlog2`
widens with `n_total`.

Two that do **not** move, and the study's arithmetic on them is accepted:
`ss_acc` is 48 b (at 4096 the bound is 2^43, still fine) and `rs_p` is 6 b,
which holds `nlog2 = 12`. `cfg_nlog2` itself is `[3:0]` and 12 fits; it does
**not** widen.

- [ ] **Step 2: retire the VNW escape, with an emitter assert in its place**

At 13 bits, 4096 is representable directly (max 8191), so `0` should mean 0 and
be **refused**, not mean 4096. Keeping a legacy escape the width no longer needs
is exactly how the accidental CONV wrap became load-bearing (Task 10 retires
that one for the same reason). Delete the escape in `layer_chan`'s VNW latch and
add the emitter assert that replaces it.

- [ ] **Step 3: the TB family, which §4.2 had no row for at all**

`tb/tb_vecnorm.sv`'s 11-bit `w_waddr` and its `xv`/`wv`/`gv` arrays at 2048,
its cases 5/6, and `tb/tb_vecnorm_diff.sv`'s 11-bit `w_waddr` with its rationale
comment — all move.

`tb/scripts/gen_seq_c_vectors.py` is **checked and is NOT a defect**: its only
geometry literal is a *deliberate* N=2048 freeze, locked by its own comment
because these are unit vectors for the `n_log2 = 11` geometry. **Keep the 2048
set as a regression and ADD a 4096 set.** The filenames bake 2048 in, so a
rename ripples into `tb/tb_vecnorm.sv` and the Makefile — plan for that rather
than discovering it.

- [ ] **Step 4: GREEN + commit**

`make -C tb tb_vecnorm` runs 4 seeds and then a `+guardtest` that must print the
unsupported-`nlog2` message and exit non-zero — **that guardtest's expected
string moves with the guard** and must be updated in the Makefile, or it will
pass for the wrong reason. `tb_vecnorm_diff` runs 4 seeds plus three sabotage
cases that must all fail.

```bash
git commit -m "gate(G3.2): vecnorm_unit at N=4096 — 13-bit counters, 4096 buffers, 12-bit w_waddr, VNW escape retired; 2048 regression kept, 4096 set added" \
  -- rtl/vecnorm_unit.sv rtl/layer_chan.sv ref/gen_layer_script.py \
     tb/tb_vecnorm.sv tb/tb_vecnorm_diff.sv tb/scripts/gen_seq_c_vectors.py \
     tb/Makefile evidence/qwen9b/g3/G3_2_VECNORM.md
```

---

### Task 9: G3.3 — `matvec` at MAX_NG = 96 and XWIN 12 KiB, with W8 and g64 stripped

> ### PRE-G3.3 ROWS, KEPT AS THE RECORD — dated note 2026-09-02 (Task 9)
>
> Rows here marked `<!--cites:noquote-->` quote **source that G3.3 DELETED**,
> not source that merely moved: the 6-bit `cfg_ng` / `x_line` / `g_q…g5_q` / `r_g` declarations, the `wbeats` and `ng7` wires, the 1536-word `x_mem`, and the 6 KiB XWIN decode with its 11-bit pointers, together with the `cfg_w8` / `cfg_g64` ports and everything that selected on them, SHAPE bits 28 and 29, and the W8-envelope adder tree.  They are kept verbatim, because they
> are the record of what the pre-G3.3 tree said and the argument they support
> rests on them (§0: nothing is deleted or struck).  The exemption marker is
> used for exactly the reason §7.6 gives — *"an exemption is for source that
> no longer exists, not for a citation that has merely moved"* — and every
> citation that had merely MOVED was RENUMBERED instead, mechanically, by
> `evidence/qwen9b/o3/o3_cite_drift.py --base a08a90b`.
> **The post-G3.3 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_3_MATVEC.md` §11.1.**

One coherent block with one test cycle: the same module grows for `ng=96` and
shrinks by the whole W8 lane array at the same time. **May run in parallel with
Task 8.**

This re-opens the block that owned build_034's worst 22 endpoints and that
build_035 closed at exactly 0.000. The countervailing item is in the same task:
**−5,826 LUTs and −497 CARRY8 per channel, ×4 = −23,304 LUTs device-wide**,
measured OOC on the real part.

**Files:**
- Modify: `rtl/matvec_engine.sv`, `rtl/matvec_chan.sv`, **`rtl/seq_movers.sv`**
  (its own `XWIN_WORDS` copy and the burst guard that reads it — the constant is
  declared in *two* RTL files and both must move), `sw/hwmap.py` (`shape_word`,
  its new `isa` parameter and its selftest), `sw/infer.py`, `sw/layer_test.py`,
  `sw/tok_meter.py`, `sw/seq_run.py` (the five `shape_word` callers),
  `ref/seq_format.py` (the SHAPE disasm), `sw/chat_seq.py` (the SHAPE decoder),
  `tb/tb_matvec.sv`,
  `tb/tb_matvec_chan.sv`, `tb/tb_mvshim_b.sv`, `tb/mvshim_b_stubs.sv`,
  `tb/seq_stub_mvchan.sv`, `tb/scripts/gen_matvec_v2_vectors.py`, `tb/Makefile`
- Test: `make -C tb tb_matvec tb_matvec_ng tb_matvec_chan tb_mvshim_b
  lint_matvec lint_mvshim_b`

**Interfaces:**
- Produces the **new SHAPE word**, and every producer and consumer moves in
  lockstep — `sw/hwmap.shape_word`, `rtl/matvec_chan.sv`'s decode and its header
  table, `ref/seq_format.py`'s disassembler, `sw/chat_seq.py`'s decoder,
  `tb/seq_stub_mvchan.sv`, and the vector generators:

  > **`SHAPE = {spare[31:29], ng[28:22], nrows[21:6], sh[5:0]}`** — contiguous,
  > three spare bits, no scattered field. Stripping W8 and g64 frees bits 28 and
  > 29; `ng` needs a seventh bit and the spec's constraint is that **three spare
  > bits remain**, which this satisfies while honouring the same
  > no-scattered-bits principle the ARG re-encoding adopts. The alternative —
  > leave `nrows`/`sh`/`ng[5:0]` in place and put `ng[6]` on the freed **bit
  > 28** — is the fallback if the contiguous repack turns out to cost anything
  > in `matvec_chan`'s decode. Note that bit 28 is not the spec's bit 30 either,
  > so **neither option matches §5.2's literal wording**; see the deviation note
  > below rather than reading the fallback as the compliant one.
  >
  > **`shape_word` is a RUNTIME CSR producer, not only a stream emitter, and
  > repacking it breaks the host's ability to drive `build_034`/`build_035`.**
  > Three tools write the packed word straight to hardware —
  > `sw/infer.py:238`, `sw/layer_test.py:124` and `sw/tok_meter.py:385`, each a  <!--cites:noquote-->
  > `wr(<base> + R_SHAPE, shape_word(...))` against a live BAR — and two more
  > put it into a stream record (`sw/seq_run.py:805`, `ref/seq_format.py`).
  > Spec §3.3 says `ref/` and `sw/` **still serve the old bitstreams**, and
  > Task 16 promises a ~2-minute bitstream swap; an unversioned repack makes
  > both false. **Resolution, and both halves are required:**
  >
  > 1. **Version the packer.** `shape_word(nrows, sh, ng, g=128, w8=False,
  >    isa=2)` — `isa=1` packs the `build_034`/`build_035` layout
  >    (`{2'b0, w8[29], g64[28], nrows[27:12], sh[11:6], ng[5:0]}`), `isa=2` the
  >    9B one. The three direct-CSR callers pass the ISA of the bitstream they
  >    are driving, derived from the `VERSION` CSR they already read and check.
  >    `_selftest_shape_word` gains an `isa=1` case pinned to the committed
  >    literals `0x20800290` / `0x20200290` from `RD_GATE.md`, so a future edit
  >    cannot silently move the old layout.
  > 2. **Declare what is still not served.** Versioning SHAPE does not rescue
  >    everything: Task 7's ARG re-encoding rewrites `sw/chat_seq.py`'s decoder,
  >    so `chat_seq` cannot read a pre-G3 stream whatever SHAPE does. **Pinned
  >    `.e`/`.seq` streams are unaffected** — the SHAPE word travels inside the
  >    record as data. Task 9's gate doc and Task 16's `NEXT_SESSION.md` note
  >    must therefore state, by name, which host tools remain valid against
  >    `build_034`/`build_035` from the post-migration tree and which require a
  >    pre-G3 tag. Do not leave a reader to infer it from §3.3.
  >
  > **Stated plainly because it is a deviation:** the spec's §5.2 sentence is
  > "`cfg_ng` widens into **bit 30** with three spare bits left". Neither option
  > here puts `ng`'s seventh bit on bit 30. What the spec's *constraint* pins is
  > the spare-bit count, and both options leave exactly three; the bit position
  > is not otherwise derived anywhere in the spec. If the user reads §5.2 as
  > pinning bit 30, say so and the field moves — the arithmetic is unaffected.

- Produces `cfg_ng` at **7 b**, `MAX_NG = 96`, `x_mem [32][96]`, XWIN
  **3072 words / 12 KiB**, `xptr`/`wb_ptr` at 12 b.
- The new XWIN decode, replacing the hard-wired 6 KiB one:

  > `wb_win` admits `0x4000…0x6FFF` — `awaddr[15:14] == 2'b01 &&
  > awaddr[13:12] != 2'b11` — with `wb_ptr <= awaddr[13:2]`, 12 bits, words
  > 0…3071. The mvchan window is 64 KiB per channel with RES reads at
  > `0x0000–0x3FFF`, so 12 KiB of XWIN fits with the SLVERR behaviour unchanged.

- [ ] **Step 1: strip W8 and g64 first, and prove W4 is bit-identical**

Do the subtraction before the addition — the block is easier to widen once the
lane array is gone, and a W4-unchanged proof is cheapest against today's vectors.

Out of `rtl/matvec_engine.sv` and `rtl/matvec_chan.sv`: the `cfg_w8` port, the
8-bit operand mux and the widened adder tree with the stage widths tabulated in
the header, the half-beat toggle (`wbeats`, `w8_phase`, `ph_q`), and SHAPE bit
29 with its decode. Out with g64: SHAPE bit 28, the `cfg_g64` scale-beat branch,
and the `cfg_g64`-selected mux feeding `sc_idx_a/b` — the NSCAL:1 scales mux
whose comment says "Do not add logic between them", which now simply widens with
`r_g`.

**Two rows an earlier spec revision had wrong, and both were W8 arithmetic in a
build that strips W8**: `g_cnt` and `wbeats` do **not** widen. In W4 only,
`wbeats` *is* `cfg_ng` — the signal exists solely as the `cfg_w8` mux and goes
away with the mode — and `g_cnt` runs `0 … 96 + 3 − 1 = 98`, which fits the
existing 7 bits. The RTL's own comment deriving 7 bits from `2*MAX_NG + 2` is a
W8 statement and must be **re-derived, not scaled**.

Then prove W4 unchanged: `make -C tb tb_matvec tb_matvec_ng tb_matvec_chan
tb_mvshim_b` against today's committed W4 vector sets, bit-identical.

**This step deletes tests, and that is recorded, not hidden.** `tb_matvec_w8`,
`tb_matvec_g64`, `tb_matvec_chan_w8` and `tb_matvec_chan_g64`, their shape lists
(`W8SHAPES`, the g64 dirs) and their generator flags test modes that no longer
exist in this bitstream. Delete the targets and the vector families, and record
in the gate doc **exactly which targets and which vector families were retired
and why** — the host-side W8 law stays (`ref/w4a8_ref.py`, `matvec_y32_w8`,
`sw/hwmap`'s `w8` plumbing) because `build_035` still serves the 2B in W8, and
`sw/hwmap.py`'s `assert not (w8 and g == 64)` becomes vacuous for this build and
**stays**, guarding the old bitstreams' host path.

Also retired by this step: the open follow-on "W8 CSR-decode range checks"
becomes moot. Close it in `NEXT_SESSION.md` rather than leaving it to rot.

- [ ] **Step 2: widen to MAX_NG = 96 at the verified sites**

`MAX_NG` 48 → **96** (the parameter's own comment says "K <= 6144" and must be
re-derived to K ≤ 12288); `cfg_ng` 6 → **7 b**; `x_mem` 1536 → **3072 words**;
`acc_bank_lo`/`_hi` 48 → 96; the `x_waddr` line index to **12 b** for 96 backed
lines; `x_line` 6 → **7 b**; **six** ng-unit indices travelling with the
pipeline stages (`g_q`, `g1_q`, `g2_q`, `g3_q`, `g4_q`, `g5_q`), all `logic [5:0]`
and all commented "0..NG-1 <= 47", go to **7 b**; the `r_g` retire index goes to
**7 b**; and `ng7` either widens to 8 b or is deleted outright now that `cfg_ng`
is already 7 b.

**Scale beats are confirmed and do not widen.** At the g128 cadence
`n_scale_beats = ceil(ng/32)`, and the 9B row shapes are `K ∈ {4096, 8192,
12288}` → `ng ∈ {32, 64, 96}` → `n_scale_beats ∈ {1, 2, 3}` and
`scale_beat_idx ∈ {0, 1, 2}`. **Both fit two bits at every 9B row.** This is
also why g64 had to go: at ng=96 the g64 cadence needs 6 bits and overflows.

**And GPTQ needs no cadence change at all** — `w4g128gptq` is an identical wire
format with identical bytes/token, asserted to the byte in all seven classes at
all four geometries. The study's warning that GPTQ costs the board something at
9B applies **only to the g64 cadence**, which this build does not carry. At
g128 + GPTQ the board cost is **zero**.

**Fix the two D-CITE comments that live in this file while it is open** (Task 7
deliberately left them here): the pointer that names matvec_chan.sv:531-535
for an XWIN SLVERR that is at `rtl/matvec_chan.sv:613-614` and  <!--cites:noquote-->
`rtl/matvec_chan.sv:614`, and the one that says "(:747)" for a `cfg_ng` assert  <!--cites:noquote-->
that is at `rtl/matvec_engine.sv:716-719`. Both targets move again in this task,
so the comments must be re-derived rather than merely corrected.

**Verified safe at 9B and deliberately NOT changed — listed so nobody widens
them for symmetry:** the 16-bit row counters; the 48-bit row accumulator
`p_acc` (Task 12 checks its headroom rather than arguing it); the 4096-row RES
window; and the 18-bit AMAX index, where vocab 248,320 of 262,144 leaves 13,824
spare.

- [ ] **Step 3: the XWIN aperture, which belongs inside this wall**

The aperture is not an afterthought — the feasibility study reasoned about it,
got it wrong, and corrected itself: the 64 KiB per-channel stride is not the
constraint, **the decode is**. Widen `XWIN_WORDS` in both `matvec_chan` and
`seq_movers`, the decode, and both pointers, per the Interfaces block above.

TB twins (spec §7.5 A): `tb/tb_matvec.sv`'s and `tb/tb_matvec_chan.sv`'s
`MAXX = 1536` — and the latter's `% 2048`, which **encodes the 11-bit XPTR** and
is commented as such; `tb/tb_mvshim_b.sv`'s `NX = 1536` at three sites;
`tb/mvshim_b_stubs.sv`'s 11-bit `x_waddr` port; and `tb/seq_stub_mvchan.sv`'s
11-bit `xptr` with its window map commented at three places. All → 3072 words
and 12-bit pointers.

- [ ] **Step 4: new vector shapes at the 9B row geometry**

`tb/scripts/gen_matvec_v2_vectors.py` gains 9B shapes exercising `ng ∈ {32, 64,
96}` — `K ∈ {4096, 8192, 12288}` — including the `down_proj` row at
`K = FFN = 12288` that is the whole reason `MAX_NG` moves. Keep the existing
frozen W4 shapes as the unchanged-behaviour regression. Add a `+guardtest`-style
case proving `cfg_ng = 97` is refused, mirroring the existing `cfg_ng 49
unsupported` self-test that `tb_matvec_ng` already runs — **that self-test's
expected string moves with `MAX_NG` and must be updated in the Makefile.**

- [ ] **Step 5: GREEN + commit**

Four seeds on every target, `-Wall` clean, lint clean.

```bash
git commit -m "gate(G3.3): matvec at MAX_NG=96 + XWIN 12 KiB, W8 and g64 stripped — new contiguous SHAPE, -5826 LUT/-497 CARRY8 per channel; W4 bit-identical on the frozen shapes" \
  -- rtl/matvec_engine.sv rtl/matvec_chan.sv rtl/seq_movers.sv \
     sw/hwmap.py sw/infer.py sw/layer_test.py sw/tok_meter.py sw/seq_run.py \
     sw/chat_seq.py ref/seq_format.py \
     tb/tb_matvec.sv tb/tb_matvec_chan.sv tb/tb_mvshim_b.sv \
     tb/mvshim_b_stubs.sv tb/seq_stub_mvchan.sv \
     tb/scripts/gen_matvec_v2_vectors.py tb/Makefile \
     NEXT_SESSION.md evidence/qwen9b/g3/G3_3_MATVEC.md
```

---

### Task 10: G3.4 — `layer_chan` geometry: **int16** DN banking + `DN_PIPE = 2`, KV, NH = 32, CONV, envelopes

The layer's own geometry, including **W1's RTL** — the structure G1 measured the
fidelity of and G5a will place. Note that the spec's G3 line reads
"Implement §4.2–§4.6 and §5.1–§5.4", which omits §4.1; W1's RTL nonetheless
belongs here,
because G4's OOC gate checks its URAM count and G5a places it.

**Files:**
- Modify: `rtl/layer_chan.sv` (the 24-bank int16 DN array **and** `DN_PIPE`'s
  register stages), `rtl/dn_step.sv` (**the read-address lead, not a narrowing
  law** — see A1.2's design decision), `rtl/gate_unit.sv`, `rtl/seq_unit.sv`
  (EMBLOG2 reset), ~~`rtl/conv4_silu.sv` (only if Task 1 chose `RS_F = 7`)~~
  ~~**`rtl/conv4_silu.sv` is NOT touched — A1.8, `RS_F` stays 8**~~
  **RE-ADDED 2026-09-01 (A2.1): `rtl/conv4_silu.sv` IS touched — its baked
  shift goes `9 → 8`.** A1.8 struck it as foreclosed and A2 reverses that;
  `RS_F + CW_F − 12` = 7 + 13 − 12 = 8. The host expression beside it already
  reads the constant, so **only the RTL literal moves** — and the TB that
  covers `conv4_silu` must be re-run at the new shift, not assumed inert,
  `sw/hwmap.py` (`SEQ_EMBLOG2_RST`, the host
  mirror of that reset), `ref/gen_layer_script.py` (`KVH_MAX` and its two
  asserts; the emitter assert replacing the retired CONVW escape),
  `tb/tb_gate_unit.sv`, `tb/tb_layer_chan.sv`, `tb/tb_dn_step.sv`,
  `tb/tb_seq_unit.sv` (**three** EMBLOG2 sites, and the one that matters is the
  assignment, not the comment above it: the declaration at
  `tb/tb_seq_unit.sv:375`, the reset value at `tb/tb_seq_unit.sv:412`, and the
  CSR write at `tb/tb_seq_unit.sv:815` — all exercised by
  `tb_seq`/`tb_seq_guard`), `tb/scripts/gen_seq_unit_vectors.py`,
  `evidence/qwen9b/g3/isa_bits.py` (extended to the `kvhead[1:0]` field)
- Create: `evidence/qwen9b/g3/G3_4_LAYER.md`
- Test: `make -C tb tb_dn_step tb_gate_unit tb_layer_chan tb_seq_layer tb_seq
  tb_seq_guard tb_token tb_chain lint_seq lint_seq_unit`

**Interfaces:**

> ## SUPERSEDED 2026-08-31 (A1.1, A1.2, A1.7) — THE CONTAINER IS `int16`
>
> The original Consumes/Produces text is kept below the line for the record.
> **What this task builds is defined here.**
>
> - **Consumes: nothing from Task 1's law.** G1 measured every int8 law and the
>   user declined all of them. `ref/layer_fixed.py`'s `FABLE5_DN_STATE` stays as
>   committed evidence, defaulting to `int16`, **under which the law is exactly
>   `clip16`** — i.e. the shipped generators' existing behaviour, byte-identical.
>   The RTL mirrors `int16`. TB-vs-ref bit-exactness is still the arbiter, and
>   at `int16` the reference it checks against is the one already on main.
> - **Produces the `int16` DN state banking, which must reduce to exactly the
>   structure Track P PLACED as `wide`:**
>   - 24 slots × 32 heads × 128 rows = **98,304 rows of 2048 b = 24 banks of
>     4096 — ONE LAYER PER BANK**, because at LNH = 32 the `head + row` field is
>     exactly 12 bits and fills a URAM's depth exactly.
>   - **24 × 29 = 696 DN + 232 KV = 928 URAM288 of 960 (96.7 %).** No partial
>     writes, no write-combining register, no split-row layout — every one of
>     those was an int8 device and none of them applies.
>   - Address `{dn_slot, head, row}` cut at the URAM depth, replacing the shipped
>     hand-split in-bank expression. **U4 means this no longer has to reduce
>     bit-identically at LNH=16** — lay it out for 9B alone.
> - **Produces `DN_PIPE = 2`**, and it is part of the structure rather than a
>   tuning knob: two register stages on the per-group control/address/write-data
>   fan-out **and** two on the read return. Read latency 2 → **6**; write latency
>   +2. Cost is **flip-flops only** — LUT unchanged, **URAM unchanged at 928**,
>   FF +≈ 24.7 K (≈ 1 % of the device). The reference implementation exists and
>   must be followed rather than reinvented: `synth/exp_uram/rtl/layer_chan.sv`
>   carries the `DN_PIPE` / `DN_BPG` parameters and the `dont_touch`'d per-group
>   register arrays; Task 13 re-runs it, so **the shipping RTL and the
>   experiment RTL must stay structurally identical or G5a measures a different
>   design from the one that ships.**
> - **Produces a REVIEWED decision on the `dn_step` read latency** — Step 1′
>   below. Consumed by Task 12 (which measures its cycle cost) and by §10's
>   perf band.
> - **Does NOT produce**: any int8 narrowing in the RTL, any `sat8`/`e_fixup`
>   hardware counter. ~~any `RS_F = 7` literal change~~ — **superseded
>   2026-09-01 (A2.1): it DOES produce exactly one, `rtl/conv4_silu.sv:50`'s
>   shift 9 → 8, and nothing else on the `RS_F` axis.** In particular it does
>   **not** touch a host constant: A2.3.

*(Superseded, kept as the record of the int8 design:)*

- ~~Consumes: **Task 1's chosen state law**, mirrored from `LF.dn_state_narrow`.~~
- ~~Produces the **int8 DN state banking** reducing to `int8naive`: 12 banks of
  4096, two layers per bank, 12 × 30 = 360 DN + 232 KV = **592**; the naive
  1024-bit partial write stays in URAM (`ceil(1024/72) = 15` per half); the
  write-combining register buys 12 URAM and is an optimization, not an enabling
  requirement; named fallback `int8p` + the combiner if Task 13 showed
  `int8naive` did not place.~~
- Produces `NKVH = 4` KV banking: `{kv_slot, kvhead, k/v, t[8:0]}` → **8 banks,
  232 URAM**, structure unchanged.
- Produces `NH = 32` in `gate_unit`, `dn_head` at 5 b, `kvhead` at 2 b,
  `tcnt_bank` `[8][4]`, `cvi` at 14 b, conv banks **24 × 8192**.
- Produces `EMBLOG2_RST = 5'd13`; the CSR **stays runtime**, `MIN 8 / MAX 13`.

- [ ] **Step 1: the `int16` DN banking at 24 banks — RED against the ref first**

> **AMENDED 2026-08-31 (A1.1).** The superseded step wrote an int8 narrowing law
> into the state path and required a TB case that FAILED on today's int16 RTL.
> There is no narrowing law any more. What is new is the **geometry**: 9 banks →
> 24, two slots per bank → one layer per bank, and `LNH` 16 → 32.

Write the TB case before the RTL. `tb_dn_step` gets directed cases at
**`dn_slot` 18…23 and `head` 16…31** — the slots and heads that do not exist
today — whose goldens come from `ref/layer_fixed.py` at its **default `int16`**
container, and they must FAIL on today's 9-bank RTL by addressing a bank that is
not there. Then implement the 24-bank map and watch them pass, 4 seeds.

**The state VALUES do not change and that is the regression that matters.** At
`int16` the container law is exactly `clip16`, which the shipped RTL already
does, so a `dn_slot` < 18 / `head` < 16 case must be **bit-identical** to
today's. Run the existing `tb_dn_step` cases unchanged and require exactly that
before adding any new case — if a shipped case moves, the banking edit has
touched the arithmetic and the geometry work stops until it is explained.

`tb/tb_dn_step.sv`'s `16384 = 128 × 128` is one head's DN state and **survives
LNH=32** — it is per-head and moves only if `head_dim` does. It is listed here
so nobody "fixes" it.

- [ ] **Step 1′: `DN_PIPE = 2`, and the `dn_step` read-latency DESIGN DECISION — REVIEWED, NOT SILENTLY TAKEN**

**This step exists because the spec forbids choosing this silently** (§4.1
W1′(a), A1.2). It has its own review gate: **the decision is written down, with
its measurement, and reviewed BEFORE the implementation that depends on it is
finished.**

**(a) Land the pipelining, structurally identical to what Track P placed.** Two
register stages on the per-group control/address/write-data fan-out and two on
the read return. The reference implementation is committed and must be followed,
not reinvented: `synth/exp_uram/rtl/layer_chan.sv` carries
`parameter int DN_PIPE = 0,` and `parameter int DN_BPG = 8` with the bank-select
delay line `localparam int DN_SDEL = 2 * DN_PIPE + 1;   // bank-select delay line`,
and the per-group registers are `dont_touch`'d arrays inside its `g_grp`
generate block. **If the shipping RTL and the experiment RTL diverge
structurally, Task 13 measures a design that is not the one being built** —
which is the whole reason Task 13 re-runs it on the shipping sources.

**(b) The problem, stated exactly.** `dn_step` reads the state memory once per
row per pass — 256× per head — and issues the next address in the **loop tail**:
`rtl/dn_step.sv:226` for pass 1 and `rtl/dn_step.sv:261` for pass 2, both
`s_rdaddr <= row[6:0] + 1'b1;`. At `DN_PIPE = 2` the read return is
`2 + 2N = 6` cycles, so the issue must lead the use by **6**. Pass 1's loop is
six states (`P1_RD → P1_W → P1_DECM → P1_DEC → P1_KM → P1_KW`) and can buy lead
4 for free by issuing in `P1_DEC` instead of the tail. **Pass 2's loop is five
states** (`P2_RD → P2_M → P2_OUT → P2_QM → P2_QW`) and **cannot provide lead 6
at any issue point.**

**(c) The two options, and neither is pre-chosen here:**

| option | mechanism | price | status |
|---|---|---|---|
| **(i) wait state** | one extra state in pass 2's loop | **≈ +10 % throughput**, Track P's bound | bounded, not designed |
| **(ii) two-outstanding** | two reads in flight so lead 6 exists without stalling | removes the +10 % | **unwritten, unshown to close** |

`DN_PIPE = 1` is **not** a third option: its ~0.15 % price is real but **N = 1
does not close** (−0.339), so the cheap number and the closing build are
different builds.

**(d) Measure before choosing.** Implement (i) first, because it is the one that
is bounded and it unblocks Tasks 11–13. Then, **before** this task's gate doc is
written, hand Task 12 the two-run cycle census (A1.6) so the ≈ +10 % becomes
this build's own number rather than Track P's bound — and sketch (ii) far enough
to say whether it is a `dn_step` FSM change or a `layer_chan` interface change.

**(e) The review gate.** The gate doc carries: the measured cycle cost of (i),
the sketch and honest status of (ii), which was taken, and **why**. A reviewer
must be able to reject the choice without rejecting the banking. **If (ii) is
taken, it does not ship until it is shown to close in Task 13's flow** — an
unmeasured restructure that removes a 10 % penalty is worth less than a measured
wait state that does not.

- [ ] **Step 2: the wall-9 KV lockstep — all six sites or none**

The host reads **four** bits of `kvhead` where the RTL reads **one**. That is
dead width today, not a live bug, because the emitter refuses first
(`KVH_MAX = (1 << 1) - 1` with asserts on both KVAP and ATTN). **At NKV=4 it
stops being dead, and the failure mode if the guards are relaxed without the RTL
is silent**: `arg0[0]` truncates, kvheads 2 and 3 alias onto banks 0 and 1 and
share their append counters, while the reference model faithfully models four
independent caches. **Divergence, not an error.**

So this is a lockstep change across `KVH_MAX`, both emitter asserts, the RTL
field, `tcnt_bank`, the KV banking, and the reference model's `[6][2]` → `[8][4]`
storage (the latter landed in Task 3). Task 7's encoder-vs-decoder mechanization
is what proves they moved together — extend `evidence/qwen9b/g3/isa_bits.py` to cover the
`kvhead[1:0]` field rather than adding a new script.

- [ ] **Step 3: NH = 32, CONV, and the conv banks**

`gate_unit`'s `NH` parameter goes to 32 and `w_addr` to 5 b — it is instantiated
with **no `NH` override** today, so the parameter default is load-bearing.
`dn_head` goes 4 → 5 b at its declaration and its ARG0 latch, and the 16/32/16
literals scattered through `layer_chan`'s DNST/GATE handling plus the 32-element
store bound all move.

**CONV `cvi` is the wall**: the comparison happens *before* the increment and
genuinely cannot express 8192. Widen `cvi` to **14 bits**, which represents 8192
directly, **and retire the CONVW wrap escape with it**: the two CONVW compare
sites do `wi + 1` in 13-bit arithmetic, so at `wi = 8191` the sum wraps to 0 and
a field value of 0 *already* encodes 8192 — an **accidental** escape rather than
a designed one. `0` should mean 0 and be refused, with an emitter assert in its
place, for exactly the reason Task 8 retires VNW's.

Conv banks go to **24 × 8192**, costed inside the study's BRAM figure.

`tb/tb_gate_unit.sv` is family D and there is **no `NH` parameter anywhere in
`tb/` or `sw/`** — the 16 is a bare literal at ten sites in that file, including
a 4-bit `w_addr` that fails **silently** at LNH=32 rather than by array bound.
Introduce the parameter rather than editing ten literals.

- [ ] **Step 4: EMBLOG2 reset 13, and the belt-and-braces readback**

`EMBLOG2_RST` 11 → **13**, and `sw/hwmap.py`'s `SEQ_EMBLOG2_RST` moves with it,
**in this task and not in Task 3** — it is a host mirror of an RTL reset value,
and `EMB_ROW_BYTES_DEFAULT` is derived from it. That default is by design for
pre-R-b manifests and is unreachable for a 9B artifact, whose manifest carries
the key; moving it before the RTL moves would make the mirror lie.

The runtime CSR stays; it costs a 5-bit register and
a shift, and making it constant would delete the R-b infrastructure the TB set
exercises. The reset move is the win: the census still holds a live site that
never learned to program EMBLOG2 from the artifact
(`tb/scripts/gen_seq_unit_vectors.py`'s `EMB_ROW_LOG2 = 11` — "the TB set only
ever proves EMBLOG2 11"), and moving the reset to 13 converts that bug class
from *silently addressing the wrong row* into *right by default*. Fix the live
generator site too; the dead near-copy the feasibility study cited for this was
deleted in Task 3.

Both halves are required at this gate and at G6: the emitter writes
`emb_row_bytes` into the manifest and the host programs EMBLOG2 from it via
`sw/hwmap.seq_emb_log2`; **and** `seq_run`/`chat_seq` read the CSR back and
refuse a mismatch against the manifest. `tb_seq_guard`'s `+emblog2bad=` cases
bracket the legal range and must be re-pointed at the new reset.

`tb/tb_layer_chan.sv`'s `EMB_N_MAX = 4096` is **exactly at the 9B ceiling** — it
fits with zero margin. Turn that coincidence into an assert rather than leaving
it as luck.

- [ ] **Step 5: S9 — synthesizable envelope checks, which U4 is what makes cheap**

The standing hazard is that almost every envelope guard in the RTL is
`` `ifndef SYNTHESIS `` sim-only, so on silicon an out-of-envelope command wraps,
aliases, or hangs — it does not report. **With one geometry there is exactly one
legal envelope**, so a hard check is cheap and cannot false-fire on a legacy
config. Add, as sticky error bits in the existing `err_op`/STATUS mechanism:
`cfg_nlog2 > 12` → error, command refused; `cfg_ng` outside `1..96` → error,
MVGO refused; an out-of-window `s_axib` scratch burst → SLVERR, the way
`matvec_chan` already answers an out-of-XWIN write.

Cost: a handful of comparators off the datapath. **Prove them both ways** — that
each fires in sim on a deliberately out-of-envelope command, and that **none of
them fires on the 9B stream** (the latter at Task 11, on the real stream).

- [ ] **Step 6: GREEN + gate doc + commit**

Four seeds everywhere; lint clean; the layer and token TBs green. Note the
obj_dir collision hazard: `tb_layer_chan`, `tb_token`, `tb_chain`, `tb_token24`
and `tb_model_v2_*` all share one obj_dir and cannot run concurrently — sequence
them, or give this task its own `MVDIR`-style override.

```bash
git commit -m "gate(G3.4): layer_chan at 9B — int16 DN state (24 banks, one layer per bank, 928 URAM) + DN_PIPE=2 with the reviewed dn_step latency decision, 8-bank KV at NKVH=4, NH=32, cvi 14b + escape retired, 24 conv banks, EMBLOG2 reset 13, synthesizable envelope checks" \
  -- rtl/layer_chan.sv rtl/dn_step.sv rtl/gate_unit.sv rtl/seq_unit.sv \
     rtl/conv4_silu.sv ref/gen_layer_script.py sw/hwmap.py \
     tb/tb_gate_unit.sv tb/tb_layer_chan.sv tb/tb_dn_step.sv \
     tb/tb_seq_unit.sv tb/scripts/gen_seq_unit_vectors.py tb/Makefile \
     evidence/qwen9b/g3/isa_bits.py evidence/qwen9b/g3/G3_4_LAYER.md
```

---

### Task 11: G4a — the 9B SEQ streams and the full-model sim replay

The first time the whole 9B model runs anywhere. **This task emits the SEQ
streams that Task 5 could not**: a 9B layer body peaks at 50,208 scratch words
against the 15-bit ISA's 32,768-word ceiling, so the streams were not emittable
until Task 7 landed the 16-bit encoding. Task 5's gate doc says so; this one
closes it.

**Files:**
- Modify: `tb/Makefile` (9B chip targets with their own obj_dirs),
  `tb/scripts/gen_seq_chip_vectors.py` (the LM-head interleave re-derived from
  the artifact rather than the 2048-row constant)
- Create: the 9B stream set (regenerable, **not committed**; shas in the gate
  doc), `evidence/qwen9b/g4/G4A_REPLAY.md`
- Test: `ref/seq_model.py --gate`; the chip-level TB at 9B, 4 seeds;
  torch-golden lockstep

**Interfaces:**
- Consumes: Task 5's image set and manifest; Tasks 7–10's RTL and ISA.
- Produces: `<prefix>.txt` / `.e` / `.e4` 9B streams with the new ARG encoding,
  the DNSB CSRWR per layer body, the new SHAPE words, and `emb_row_bytes` 8192
  in the manifest. Consumed by Task 14's netlist confidence and Task 15's upload.

- [ ] **Step 1: emit, and re-run the scratch high-water probe at 9B**

Emit the 9B streams. Then close the one measurement S4's sizing rests on: the
peak is the **allocator's algebra**, and the empirical high-water probe was
never re-run for the new geometry. The probe is not missing —
`evidence/qwen2b/ra/scratch_probe.log` is committed and records
`MEASURED PEAK` beside `DERIVED PEAK` at 0.8B and 2B. What was never committed
is only the driver, and it is **reproduced verbatim in the log's own appendix**.
Lift the appendix into a scratch file, run it under `FABLE5_MODEL=9b`, and
record `MEASURED` beside `DERIVED`. **If they disagree, the array size is
re-derived before anything else in this task is read** — the expectation is
`DERIVED PEAK = 50208` inside a 65,536-word array with 15,328 words of margin.

- [ ] **Step 2: the reference lockstep**

`ref/seq_model.py --gate <9B prefix>` must print `SEQ GATE: PASS` — every
checkpoint bit-exact between the emitted stream and the reference executor. Then
`seq_model` / `layer_fixed` lockstep across a full 9B token, then a multi-token
run.

Any mismatch is a **STOP with the artifacts preserved**, not a retry: this is
the arbiter that says the emitter, the executor and the fixed-point model agree,
and the 2B campaign's hardest bugs were exactly here.

- [ ] **Step 3: the chip-level replay in Verilator, on snoke**

The full-model sim. Build with its own `-GNMV` and its **own obj_dir** — never
reuse `obj_dir_tb_seq_chip`; the 2B W8 run has its own and this needs a third.
Run 4 seeds as separate processes against one binary with different `+seq=`
arguments, on snoke.

**Budget this honestly.** The 2B W8 chip run carries a watchdog of 172,800,000
in the Makefile — the largest in the tree — and 9B is a bigger model again.
Start with the one-layer smoke, then the two-token stream, then the full run;
poll bounded and record wall-clock per rung so Task 14's scheduling has a real
number.

Prove Task 10's envelope checks **do not fire** on this stream. That is the
other half of their proof and it can only be done here.

- [ ] **Step 3′: AVAILABLE, NOT A GATE — widen the `RS_F = 7` fidelity evidence (A2)**

`RS_F = 7` was adopted on **98/108 over four prompts and 108 teacher-forced
steps**, with run-to-run spread measured at exactly zero and a byte-identical
repeat. That is a strong number on a **narrow** sample, and the gate doc should
say which it is rather than letting 98/108 read as a corpus-scale result.

**The corpus-scale version does not exist in the form a reader expects, and
that is a property of the tools, not an oversight.** `ref/perplexity_eval.py`
measures **weight damage only, with float compute**; it touches `RS_F` at
exactly one place — the int16 embedding-table round trip
(`ref/perplexity_eval.py:474`, documented at `ref/perplexity_eval.py:329`) — so
a PPL point at 7 would price the **embedding rounding**, not the residual rail
the adoption is about. Do not run one and present it as confirmation.

**What is actually available here**, on an explicit instruction and on the warm
cache: re-run the fidelity harness at more prompts or more steps **through the
emitted chain this task produces**, which is also the only place `RS_F = 7` has
been exercised end-to-end rather than in the reference model. **If it is not
run, say so in the gate doc** — the adoption rests on the narrow sample and the
reader is entitled to know its width.

- [ ] **Step 4: torch-golden lockstep**

Replay against the bf16 torch golden in sim, closing the loop from checkpoint to
RTL. Record the token sequence and compare it against Task 5's fidelity run.

- [ ] **Step 5: gate doc + commit**

`evidence/qwen9b/g4/G4A_REPLAY.md`: stream shas, the scratch probe's
MEASURED-vs-DERIVED line, the lockstep results, the chip replay with its
wall-clock, the envelope-check non-firing proof, and the torch-golden
comparison.

```bash
git commit -m "gate(G4a): 9B streams emitted and replayed — seq_model lockstep bit-exact, chip-level sim 4 seeds, torch golden matched, scratch probe MEASURED at 9B" \
  -- tb/Makefile tb/scripts/gen_seq_chip_vectors.py \
     evidence/qwen9b/g4/G4A_REPLAY.md
```

---

### Task 12: G4b — the OOC structure gates and the layer-term cycle census

Two independent measurements that both have to happen before a build cycle is
spent. Separate from Task 11 because a reviewer can reject either without the
other.

**Files:**
- Create: `synth/scripts/ooc_9b.tcl` (an OOC harness for the **real** `rtl/`, in
  `synth/exp_uram/scripts/exp_ooc.tcl`'s shape), `evidence/qwen9b/g4/G4B_STRUCT.md`
- Test: OOC `synth_design` per module; a Verilator cycle census

**Interfaces:**
- Consumes: Tasks 7–10's RTL.
- Produces: the URAM/BRAM/LUT structure numbers G5a and G5b start from, and a
  **measured** layer term that either confirms or re-derives the modelled 47.00 ms.

- [ ] **Step 1: OOC synthesis on the real RTL**

Not the experiment copy — the shipping `rtl/`. Part `xcvu9p-fsgd2104-2L-e`,
`-mode out_of_context`, 4.000 ns, one out dir per module, on snoke. Report:

- ~~**URAM = 592**~~ **URAM = 928** for `layer_chan` (A1.5) — 24 × 29 = 696 DN
  + 232 KV — with the DN array's non-URAM cell count at **zero**. Track P
  **placed** `wide` and got 928, so a disagreement here is news and stops the
  task. **Also check what `DN_PIPE = 2` is supposed to cost and nothing more:
  FF up by ≈ 24.7 K (≈ 1 % of the device), LUT unchanged, URAM unchanged.** A
  LUT or URAM move means the pipelining was not built the way Track P built it,
  and Task 13 would then be measuring a different design. **This closes the
  COUNT half only** — the timing half is Task 13's.
- **BRAM** against §4.3's figure — the full 65,536-word scratch array costs
  +28 RAMB36 over today and the device total lands at 886.5 of 2,160 tiles
  (41.0 %) including the conv-bank growth.
- **The four-`matvec_chan` LUT delta** against §5.1's −5,826 per channel. Net
  direction for that block is **unknown and is this measurement's output**, not
  a prediction — it grows for `MAX_NG=96` and shrinks for the W8 strip at the
  same time.

Method note worth carrying from Track P: filtering cells **by** an SLR object
silently returns nothing; map each placed site to its SLR instead.

- [ ] **Step 2: `p_acc` headroom checked rather than argued**

The 48-bit row accumulator: the RTL's own note gives 44 b at K=6144, so ≈45 b of
48 at K=12288 — the study's arithmetic on the RTL's figure, **not a
measurement**. Check it, with `ref/audit_ranges.py` at 9B and with the real
9B stream in sim, and record the observed maximum against the 48-bit container.

- [ ] **Step 3: the layer-term cycle census — the study's own cheap closure**

The feasibility study says the layer term "has no measurement", that its
coefficient is a two-point fit intercept, and — the part worth acting on — that
closing it properly means a `dn_step`/`layer_chan` simulation at LNH=32,
**which needs only Verilator: no board, no synthesis**. The 33.9 % layer share
is the single largest modelled unknown in this build.

Count cycles per DNST at LNH=32 against the RTL's own ~1300/head, over the real
9B stream, and record the **measured** layer term beside the modelled 47.00 ms.
The scaling law that *is* primary-source: one `dn_step` instance, one head per
command, ~1300 cycles/head, and a real-stream census of 288 DNST/token at 2B
→ **768 = 24 × 32 at 9B, a 2.667× serial increase**; the DNST commands alone are
12.8 % of the intercept.

**If the measurement disagrees materially with the model, §10's band is
re-derived HERE, before a build is spent on the assumption** — and the gate doc
says so rather than re-fitting the model to the measurement.

> **AMENDED 2026-08-31 (A1.6) — the band moved, and this census now measures the
> thing that moved it.** The band is no longer 6.98–7.47: with `DN_PIPE = 2`'s
> latency priced by Task 10's option (i), the spec's re-anchor gives **≈ 6.5 –
> 7.0 tok/s, headline ≈ 6.56** (+10 % on the whole step) or **6.98** (+10 % on
> the layer term alone), against 7.21 if the two-outstanding restructure lands.
> **Run the census TWICE — with and without the wait state — on the same
> stream.** It is the same simulation run twice, it turns Track P's ≈ +10 %
> bound into this build's own number, and it is the input Task 10's design
> decision (Step 1′) is reviewed against. Report the DNST cycle count per head
> both ways beside the ~1300/head the RTL's own comment gives.

- [ ] **Step 4: gate doc + commit**

```bash
git commit -m "gate(G4b): OOC structure gates on the real RTL (URAM 928 + DN_PIPE=2 FF delta, BRAM, mvchan LUT delta), p_acc headroom measured, layer-term cycle census at LNH=32 with and without the wait state" \
  -- synth/scripts/ooc_9b.tcl evidence/qwen9b/g4/G4B_STRUCT.md
```

---

### Task 13: G5a — the OOC floorplan experiment. **THE CRITICAL EXPERIMENT.**

> ## AMENDED 2026-08-31 (A1.3, A1.4) — THIS TASK CAN END THE CAMPAIGN
>
> Under the `int16` ruling this is **no longer "the last cheap thing before the
> first build"**. The write-control fan-out is the binding path, the pblock is
> the **only** structure anyone has proposed for it, and **nobody has tried it**.
>
> **If no placement constraint closes the write fan-out, option B has no known
> route to closure.** That is not a timing setback to be re-rolled: the worst
> path is **one logic level with 95.9 % route**, which re-rolling does not move.
> The escalation is not "try harder" — it is **back to the user with O1
> re-opened at option 3 (DDR spill, a large new RTL path) or D (abandon)**, the
> two branches the 2026-08-31 ruling did not take.
>
> **Say this to whoever runs the task, before they run it**, so a negative
> result is reported as the finding it is rather than buried as a bad day.
>
> **And the starting point is much worse than the superseded text implies.** At
> `int16` + `DN_PIPE = 2` the module is **WNS −1.391 / TNS −2,007.2 / 6,638
> failing endpoints** (Default), or −1.539 / −3,252.2 / 6,406 under
> `AltSpreadLogic_medium` — the directive that MEETs the read path. That is an
> order of magnitude outside the band this project's playbook has closed.

**Hours, not build cycles**, and it is the last thing that runs before the first
full build. It exists because two facts point in opposite directions and both
are real: the 2B campaign's T5 lesson is that constraining `layer_0` in **any**
form cost ~1 ns (variants B/C: −1.078, −1.148, and build_035 closed only by
pblocking the four mvchans and leaving `layer_0` alone), while Track P's binding
path is a write fan-out whose 95.9 %-route signature says a placement constraint
is the fix.

They are not actually in contradiction: **the 2B campaign's T5 was measured on a
design where `layer_0` was not the binding block.** ~~At 592 URAM across two or
three SLRs it is.~~ **At 928 URAM across THREE SLRs it is, and by arithmetic
rather than by placer choice (A1.4): 2 × 320 = 640 < 928, and Track P's measured
`wide` spread is 312/312/304 of 320.** The lesson is re-openable *with
evidence*, and this task produces that evidence cheaply in machine time — but
**decisively** in outcome.

**Files:**
- Modify: `synth/exp_uram/scripts/exp_ooc.tcl` and `synth/exp_uram/scripts/launch_exp.sh` (pblock
  support), and refresh `synth/exp_uram/rtl/` from the shipping `rtl/`
- Create: `synth/constraints/fable5_floorplan_9b_*.xdc` candidates — **derived
  from `synth/constraints/fable5_floorplan_a.xdc`, the campaign winner, which
  the spec calls "the starting point, not the answer"**; its four soft mvchan
  pblocks and its deliberate absence of a `layer_0` pblock are the baseline
  every variant is measured against
- Create: `evidence/qwen9b/g5/G5A_FLOORPLAN.md`
- Test: three variants × directives, `place_design` only

**Interfaces:**
- Consumes: Task 12's confirmed **928** URAM and its `DN_PIPE = 2` FF delta
  (A1.5); Task 10's `layer_chan`, which must be **structurally identical** to
  `synth/exp_uram/rtl/layer_chan.sv`'s `DN_PIPE`/`DN_BPG` implementation or this
  task measures a different design from the one that ships.
- Produces **one of three outcomes, and all three are legitimate results**:
  (a) the floorplan XDC Task 14 starts from; (b) an **O4 escalation** — the
  conditional `layer_0` pblock question going back to the user; or (c) **a
  target-invalidating negative**: no constraint closes the write fan-out, so
  option B has no known route and O1 re-opens at option 3 or D (A1.3).

- [ ] **Step 1: re-point the experiment vehicle at the real RTL, and add pblocks**

Track P's vehicle is a *copy* of `rtl/` with an EXPERIMENT banner, deliberately
unverified. Now that the shipping RTL has the **`int16` 24-bank banking and
`DN_PIPE = 2`** (amended 2026-08-31, A1.1), refresh the copy
from `rtl/` (or point the TCL at `rtl/` directly and say so) — **and record which
was done**, because "a success here is necessary but not sufficient" only holds
if the thing measured is the thing that will be built.

`synth/exp_uram/scripts/exp_ooc.tcl` has no pblock support today; add an optional extra-XDC argument in
`synth/scripts/full_impl.tcl`'s style (`add_files -fileset constrs_1`, implementation-only) so
the pblock is data, not code. Keep the `EXP_`-prefixed marker convention — the
collector and summary.txt depend on it. Note that `synth/exp_uram/scripts/exp_ooc.tcl` passes
parameters as `-generic`, not `-G`, and that `synth/exp_uram/scripts/launch_exp.sh`'s usage comment
omits `DN_PIPE`; the positional order that governs is the assignment line, not
the comment.

- [ ] **Step 2: the variants**

> **SUPERSEDED 2026-08-31 (A1.3, A1.4).** The three variants below are the int8
> list. **Variant 2 is arithmetically IMPOSSIBLE at `int16`** — 928 URAM needs
> three SLRs — and variant 1 tested a structure this build no longer ships.
> **Run the four replacements instead**; the superseded list is kept because
> variant 3's reasoning is the one that survives and is now the critical path.
>
> | # | variant | `launch_exp.sh` arguments | what it establishes |
> |---|---|---|---|
> | **1′** | `wide` + `DN_PIPE = 2`, Default **and** `AltSpreadLogic_medium` | `32 24 8 4 8192 16 0 2 1` and the same with `AltSpreadLogic_medium` appended | reproduces Track P's **+0.097 MET** read path **on the shipping RTL**, or does not. If it does not, the directive was doing more work than the pipelining and everything downstream re-prices. |
> | **2′** | **THE CRITICAL ONE** — 1′ plus a pblock pinning each per-group fan-out register set (`DN_BPG = 8`, three groups) into the clock region of the banks it drives | 1′'s arguments plus the new pblock XDC | the only proposed structure for the binding path. **If it does not move −1.391, option B has no known route to closure.** |
> | **3′** | the same pblock at per-bank fan-out | `32 24 8 4 8192 16 0 2 1 Default 1` plus the pblock XDC | per-bank was **worse** unconstrained (−1.956); the hypothesis is that it is worse *only* because nothing placed the copies, and this is the direct test. |
> | **4′** | a three-SLR floorplan for the DN array itself — 8 banks per SLR — with and without a `layer_0` pblock | 1′'s arguments plus the floorplan XDC | where **O4** is decided. A1.4 means the array spans all three SLRs whatever else happens. |
>
> The positional order that governs is the assignment line in
> `synth/exp_uram/scripts/launch_exp.sh`, not its usage comment: variant, LNH,
> N_DN, N_KV, NKVH, CVD, DN_EW, DN_PACK, DN_PIPE, place, then optional directive
> and `DN_BPG`. `DN_EW = 16` is what selects the int16 container; the int8 runs
> used 8.

*(Superseded, kept for variant 3's reasoning:)*

1. **`int8naive` at Default and at `AltSpreadLogic_medium`** — the S1 structure,
   which Track P synthesized but **never placed**. This is the measurement that
   closes S1's named gap.
2. **The same, with the DN state and KV arrays pinned into two SLRs.** Track P
   states this is arithmetically available for `int8p` as 348 + 232 = 580 ≤ 640;
   **under S1's 592 the sum is 360 + 232 = 592 ≤ 640**, so it still holds — and
   it says it was not tried.
3. **The same, with each write-fan-out register set pinned into its bank's clock
   region** — Track P's own identified next experiment. The unresolved structure
   is the write-control fan-out: at the full wide geometry its worst path is one
   logic level with 95.9 % route between a dedicated register and the single bank
   it drives. `dont_touch` stops synthesis merging the fan-out copies but nothing
   *places* them. **That is a placement signature and the fix is a placement
   constraint.**

Runtimes from Track P's own record: synth 12–25 min, `opt_design` 6–8 min,
`place_design` 33–45 min per variant.

**Read the results with Track P's own rule**: OOC is `layer_chan` alone on the
whole VU9P — no XDMA/PCIe/GT, no four MIGs, no `matvec_chan`s, no `seq_unit`, no
device-level pblocks. A failure here is definitive; a success here is necessary
but not sufficient. All timing is post-place, pre-route, pre-`phys_opt`. And
directive spread is sampled, not characterised — one directive change moved WNS
by 0.475 ns in Track P's own runs, so every number carries that uncertainty.

- [ ] **Step 3: the O4 fork — and the second, larger fork the amendment adds**

**If a `layer_0` pblock is required, STOP and return it to the user as O4**,
with the OOC number beside the 2B campaign's T5 in-context −1 ns. The
orchestrator prompts; work halts on the build. This is a conditional user
decision, not an engineering judgement this plan can pre-make.

> **AMENDED 2026-08-31 (A1.3) — there is now a SECOND stop, and it is bigger
> than O4.** O4 asks *which* constraint. The new one asks whether any constraint
> works at all.
>
> **If none of 2′, 3′ or 4′ moves the write-control fan-out materially off
> −1.391, STOP and report a target-invalidating negative.** The orchestrator
> prompts the user with: the per-variant table, the worst path with its
> logic-level and route-percentage decomposition, and **O1 re-opened at option 3
> (DDR spill — 0.6 % of traffic, a large new RTL path, unpriced) or D
> (abandon)**. Do **not** proceed to Task 14 on the assumption that a full-build
> placer will find what an OOC placer with an explicit constraint could not:
> OOC is the *optimistic* context (`layer_chan` alone on the whole part), so a
> failure here is definitive by Track P's own reading rule.
>
> **A partial result is a result.** If 2′ moves −1.391 to, say, −0.4, that is
> not closure but it is a direction, and it belongs in the report with the
> remaining gap named — the house playbook has closed −0.091 in one `phys_opt`
> pass but has never been asked to close −1.4.

Whatever the answer, respect the standing rules: never pblock GT/Aurora (fixed
physical sites), never pblock the MIGs, and check DSP capacity per SLR before
constraining anything holding `layer_0`'s 1,838 DSPs. Per-SLR BRAM is a
floorplan input, not a device-total question — the 2B spec flagged SLR1 BRAM at
70.2 % post-widening as its top timing risk and this build doubles the scratch
again.

- [ ] **Step 4: gate doc + commit**

`evidence/qwen9b/g5/G5A_FLOORPLAN.md`: the per-variant table (URAM, place
result, SLR span, DN mux slack, write fan-out slack, WNS, TNS, failing
endpoints), the reading rule stated **before** the numbers, the chosen XDC, and
the not-established list. Collect reports with the existing collector, which
already copies the timing summary whole — a 200-line cutoff once truncated a
cited block two lines short.

```bash
git commit -m "gate(G5a): OOC floorplan experiment — int16 wide + DN_PIPE=2 placed at two directives, write-fanout clock-region pblock (the critical experiment), per-bank variant, three-SLR DN floorplan; 9B floorplan candidate chosen or target-invalidating negative reported" \
  -- synth/exp_uram/scripts/ synth/exp_uram/rtl/ synth/constraints/ \
     evidence/qwen9b/g5/G5A_FLOORPLAN.md
```

---

### Task 14: G5b — the full build and timing closure

> **AMENDED 2026-09-05 (the state spill, S1–S5) — WHAT THIS BUILD INHERITS
> IS NOT WHAT THE 2026-08-31 AMENDMENT DESCRIBED. Read this block first; where
> it contradicts the block above or the steps below, this block wins.**
>
> * **The layer no longer carries the 928-URAM bank array.** S2 retired it:
>   DN state, the KV cache (T ≤ 4,096) and the conv weights/state live in DDR
>   behind two-slot URAM caches — **182 URAM288** (DN 2×29, KV 2×58, conv 2×4;
>   spec `docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md`
>   §3) — and a 512-bit AXI4 master `rtl/state_dma.sv` (`layer_0/m_axis`) on
>   the 250 MHz layer clock into the central SmartConnect as its third slave
>   (`synth/scripts/create_project.tcl` NUM_SI 3, `layer_0/m_axis` →
>   `axi_smc/S02_AXI`, pinned to the four DDR segments). `DN_PIPE` and `DN_BPG`
>   no longer exist.
> * **S5 placed the whole layer inside SLR1 at OOC and it MET post-place**
>   (`evidence/qwen9b/s5/S5_STRUCT.md`): pblock `CLOCKREGION_X0Y5:CLOCKREGION_X5Y9`,
>   soft, 0 SLLs, WNS +0.030 (Default) / +0.034 (`AltSpreadLogic_medium`),
>   TNS 0.000, zero failing setup endpoints, hold clean; SLR1 holds URAM
>   182/320, **DSP 1,838/2,280 (80.6 % — the tight resource)**, BRAM 81/720.
>   The DN/KV write fan-out that owned Task 13's worst path is positive under
>   the ownership muxes — DN **+0.208**, KV **+0.120** on the `1slr` run (§4.4).
>   **Reading rule (S5 §0): OOC success is necessary, not sufficient** — this
>   build is where it is tested in context, routed, beside XDMA, the four MIGs
>   and the mvchans. **The residual owner changes with the floorplan, and
>   neither owner is a write path** (§4.4): under `1slr` the design's WNS is
>   `OTHER` — a DSP-to-DSP accumulation inside `dn_step`, 79.2 % route, a
>   logic-depth path no floorplan addresses; under `1slr-alt` it is `ATTN_DSP`
>   at +0.034, the compute READ out of the KV slot into the attention
>   multipliers, 54.4 % route. `SDMA`, the family Task 13 did not have,
>   **gained margin on this netlist — +0.203 / +0.087, where round 1's
>   174-URAM netlist had +0.001 / +0.006** — still the family to watch once
>   context is added, but no longer sitting on zero. Expect `ATTN_DSP`, that
>   `dn_step` accumulation and `SDMA` first in the in-context census.
> * **The floorplan this build starts from** is S5's
>   `synth/constraints/fable5_floorplan_9b_1slr.xdc` in its **in-context form**,
>   which the file's own header states in full: one pblock over the single
>   hierarchical cell `bd_i/layer_0`, same range, same softness, and NOTHING
>   else changed. Write that pblock — and only it — as a NEW file
>   `synth/constraints/fable5_floorplan_9b_1slr_ctx.xdc` (the OOC file stays
>   byte-untouched — S5's byte-lock pins it). Do NOT copy
>   `synth/constraints/fable5_floorplan_a.xdc`'s four mvchan pblocks into it: it is
>   the 2B campaign winner the 1slr XDC was derived from and it stays
>   byte-untouched too. **Pass BOTH, in order:**
>   `XDC="synth/constraints/fable5_floorplan_a.xdc synth/constraints/fable5_floorplan_9b_1slr_ctx.xdc"`
>   to `synth/scripts/launch_po2.sh` — its `${XDC:-}` is unquoted
>   (`synth/scripts/launch_po2.sh:27`), and `synth/scripts/full_impl.tcl` takes argv 2 onward
>   as a LIST and applies each with `add_files -fileset constrs_1` +
>   `USED_IN_SYNTHESIS false` (`synth/scripts/full_impl.tcl:11-14`, `:21-30`).
>   That list exists precisely so the winning geometry is LAYERED ON rather
>   than merged into an edited copy. Task 13's eight
>   `fable5_floorplan_9b_*.xdc` are SUPERSEDED (banner-ed) and match zero cells
>   on this design — do not use them.
> * **The netlist confidence a build cycle is spent on** is S4, not Tasks 11/12:
>   the whole 9B model on this RTL decodes Task 11's tokens on 4 of 4 seeds
>   (`evidence/qwen9b/s4/S4_REPLAY.md`), the compute-lane layer term 45.674
>   ms/token, the DMA lane MODELLED at 5.133 ms/token (LAT 8) — **not a board
>   figure; nothing in this task may quote it as one**. The build's RTL is the
>   tree at S5's close (the `ram_style = "ultra"` attribute on the conv slots is
>   part of it — the 174-URAM count without it is S5's RED).
> * **The pass criterion does not change**: WNS ≥ 0.000 and WHS ≥ 0.000 on all
>   clocks, zero failing endpoints, no waiver; any proposal to ship negative
>   goes to the user. The `VERSION` CSR = the netlist's commit sha, as before.
> * **New in the census**: `synth/scripts/slr_census.tcl` must show all 182 URAM in SLR1 and
>   the DSP per SLR; `synth/scripts/floorplan_check.tcl` the one layer pblock; the endpoint
>   owner classes now include `layer_0/…/u_dma` (the state DMA) and the
>   `ATTN_DSP` family — report them beside `matvec_engine`, `layer_0`, `seq_0`.
>   The 250 MHz clock-sanity gate (`CLOCK_GATE_OK`) and the `WHS_GATE:` line
>   apply unchanged.
> * **Build numbering**: `build_036` is the first roll of THIS design (no
>   build_036 exists — `synth/out_build_035*` are the last). One out dir per
>   roll, never reused. Vivado on snoke only.

> **AMENDED 2026-08-31 (A1.1, A1.3, A1.4) — WHAT THIS BUILD INHERITS IS HARDER
> THAN THE PLAN ASSUMED.**
>
> * **`layer_0` carries 24 + 8 URAM banks — 928 of 960 device URAM (96.7 %) —
>   spanning all THREE SLRs by arithmetic**, not by placer choice. Every DN
>   state access crosses at least one SLR boundary by construction.
> * **Plus `DN_PIPE = 2`'s ≈ 24.7 K flip-flops** (≈ 1 % of the device), with
>   **no LUT change** — so §5.1's −23,304 LUT saving is still real and still
>   does not help the binding path, which is 95.9 % route in a block that is not
>   LUT-bound.
> * **The OOC starting point is WNS −1.391 / 6,638 failing endpoints**, an order
>   of magnitude outside the band this project has closed before. **Do not open
>   this task on the assumption that the usual spread-and-`phys_opt` recipe
>   closes it** — Task 13 must have produced a floorplan that moved that number
>   first. If Task 13 reported a target-invalidating negative, **this task does
>   not start**.
> * **The pass criterion does NOT relax.** WNS ≥ 0.000 and WHS ≥ 0.000 with zero
>   failing endpoints and no waiver, exactly as before. A harder starting point
>   is a reason to expect more rolls, not a reason to lower the bar — and any
>   proposal to ship negative still goes to the user as an escalation.
> * **The MET that Task 13 relies on carries a directive dependency**
>   (`AltSpreadLogic_medium`). Carry that into the spread: the directive that
>   MEETs the read path and the directive that is best overall may not be the
>   same one, and the census has to say which was which.

**Files:**
- Create: `synth/out_build_036*/` (not committed), `evidence/qwen9b/g5/G5B_TIMING.md`
- Modify: `synth/constraints/` (the chosen 9B floorplan)
- Test: the full implementation flow, then the census and verification TCL

**Interfaces:**
- Consumes: Task 13's floorplan **and its verdict — this task does not start on
  a target-invalidating negative** (A1.3); the RTL from Tasks 7–10; Task 11's
  replay and Task 12's structure numbers (**928 URAM**, the `DN_PIPE = 2` FF
  delta, the two-way cycle census) as the netlist confidence a build cycle is
  spent on.
- Produces: a routed bitstream and its `VERSION` = the netlist's commit sha,
  consumed by Task 15.

- [ ] **Step 1: the first roll, with the full recipe from the start**

`synth/scripts/launch_build.sh build_036`, detached on snoke. It must emit
`CREATE_PROJECT_OK` then `BUILD_OK`, and it carries the **250 MHz clock-sanity
gate** that exists only in `synth/scripts/build.tcl` — added after the unconstrained-refclk
incident. `synth/scripts/full_impl.tcl` does **not** re-run it, so re-impl rolls inherit rather
than re-check it; the first roll is where that gate is actually exercised, and
its `CLOCK_GATE_OK` line goes in the gate doc.

- [ ] **Step 2: the spread, full recipe, three to four directives**

Use `synth/scripts/launch_po2.sh` with `TAG=` and `XDC=` — it copies the project with
`rsync -a`, **never `cp -a`** (a documented NFS hang), runs `synth/scripts/full_impl.tcl` per
directive in parallel, and greps `TIMING:` per roll. `synth/scripts/full_impl.tcl` enables
**both** `PHYS_OPT_DESIGN` and `POST_ROUTE_PHYS_OPT_DESIGN`; the phys_opt-less
`synth/scripts/reroll_impl.tcl` flow leaves +0.040…+0.100 ns on the table and is retained only
for reproducing old rolls. `AltSpreadLogic_high` won build_034 and build_035 and
is the first directive to try.

**Expect a multi-roll spread**: seven rolls on build_035's floorplan spanned
−0.004 … −0.428 and **no roll ever measured 0.000**. Budget accordingly; §11
prices this campaign at 6–10 build cycles.

Watch `WHS_GATE:` — `synth/scripts/full_impl.tcl` prints `NEGATIVE` and **does not fail the
run**, by design. A negative hold is a stop for a human, not a warning to scroll
past.

- [ ] **Step 3: census, then closure, and report WNS/TNS before and after every change**

Census the best roll with `census_035.tcl <roll_dir>` — the generalized
successor that takes the roll directory as an argument; the older
`synth/scripts/census_034_shipped.tcl` hardcodes its path and is not for new
rolls. Then run the two that **already exist and need no writing**:
`synth/scripts/slr_census.tcl` for the per-SLR URAM/BRAM/DSP picture and
`synth/scripts/floorplan_check.tcl` for the pblock report.

Then the house playbook, in order: census → reroll spread → post-route
`phys_opt`. The 2B campaign closed −0.091 → 0.000 in one `phys_opt` pass from
this position. On multi-SLR parts, placer non-determinism is ±3 ns between runs
on identical netlists, so run 3–4 in parallel and reuse the synth checkpoint.

**Report the three 034/035 endpoint owner classes explicitly** — `matvec_engine`,
`layer_0`, `seq_0` MOV — and say for each whether this build closed it, kept it,
or worsened it. This build rewrote all three.

- [ ] **Step 4: the pass criterion, stated so the gate can be failed**

**WNS ≥ 0.000 and WHS ≥ 0.000 on all clocks with zero failing endpoints, no
waiver** — i.e. what build_035 achieved, which is the standard this project set
for itself and the first bitstream in its history that needed no waiver.

**A negative WNS is not a pass and is not this agent's to accept.** build_035's
own record is that waiving −0.004 was **declined by the user**. Any proposal to
ship negative goes back to the user as an escalation with the endpoint census
attached — the orchestrator prompts, work halts.

Run `synth/scripts/final_verify.tcl` on the chosen checkpoint and record its `FV_*` markers,
including the per-mvchan worst slack, as the shipping evidence.

- [ ] **Step 5: gate doc + commit**

`evidence/qwen9b/g5/G5B_TIMING.md`: the campaign table (roll, directive, XDC,
WNS, WHS, failing endpoints), the endpoint census with owner tally, the per-SLR
resource census, the utilization delta against build_035, every waiver decision
with the user, and the `BITSTREAM:` path with its size and mtime.

```bash
git commit -m "gate(G5b): build_036 routed and closed — WNS/WHS >= 0, zero failing endpoints, no waiver; per-SLR census and endpoint owner tally recorded" \
  -- synth/constraints/ evidence/qwen9b/g5/G5B_TIMING.md
```

---

### Task 15: G6 — board bring-up

> **AMENDED 2026-09-08 (the state spill, S1–S5, and Tasks 14/14-A/14-B).
> Where this block contradicts the steps below, it wins.**
>
> * **The bitstream is Task 14-B's** (`evidence/qwen9b/g5/G5D_TIMING.md`):
>   `synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper.bit`
>   (53,074,589 B, 2026-09-07 20:46:01), **VERSION `c973c18a`** — the
>   pipelined netlist of Task 14-A (`evidence/qwen9b/g5/G5C_RTL.md`), closed at WNS 0.000 /
>   WHS +0.001, **zero failing endpoints design-wide** (0 setup of 1,319,855,
>   0 hold of 1,316,719, 0 pulse-width of 392,523 — that count, not the six
>   clocks the campaign tracks by name, is what carries "all clocks";
>   `evidence/qwen9b/g5/G5D_TIMING.md` §10 says so in as many words), no waiver, with no
>   pblock and the clock-root constraint `synth/constraints/fable5_clockroot_9b.xdc`.
>   **The margin is zero and it was produced once.** Task 15's rungs are the
>   first evidence of whether a zero-margin closure runs at speed: any
>   lockstep mismatch, any `E_*` halt, any clip counter that Task 12's census
>   did not predict, is reported as such — not debugged past — with the
>   temperature and the run length recorded. Task 14-B's watch items: the
>   layer's clock root at `X2Y2` is valid only while the placer keeps
>   `layer_0` in SLR0; the 300 MHz `xline_q0` CE cone in the matvec channels
>   owned the FIRST campaign's design WNS under `ExtraTimingOpt` and is closed
>   on the `AltSpreadLogic_high` family (worst +0.014, `evidence/qwen9b/g5/G5D_TIMING.md` §4.7);
>   and the layer families still negative on the unconstrained roll the clock
>   root then closed were **`ATTN_DSP`** (which owned the WNS at −0.156), the
>   **DN/KV/CV caches** and **`u_dn`** — `SDMA` was already closed there at
>   **+0.143** (§4.8).
>
> * **The layer state now lives in DDR and the host uploads it.** The
>   artifact carries `<base>.state.bin` (the initial DN/KV/conv region image,
>   SPARSE on disk), `<base>.state_final.bin` and 24 `<base>_cv<L>.bin` conv
>   images; the manifest's `state: {dn, kv, cv, end, sha256, final_sha256}`
>   names the region (`sw/hwmap.plan_state`, placed after the weights and the
>   embedding by `plan_state_base(nch)`), and `conv_images: [{layer, file,
>   bytes}]`. `sw/seq_run.upload_state(dev, art)` does the DN region memset,
>   one write per conv image WITH readback, and programs the three base CSRs
>   `SB_DN`/`SB_KV`/`SB_CV` (64 KiB units, `sw/hwmap.py:225-227`);
>   `seq_check_state_bases` refuses a run whose bases are unset — the RTL
>   would answer `E_DMA_BASE` at the first SLD/SST and halt (SEQ ISA v2.1
>   B15.4). `verify_state_image(art)` checks the image against the manifest's
>   sha256 BEFORE anything is written. **The rung order therefore becomes:**
>   identity (MAGIC, VERSION, **CALIB = 0xF**, UPTIME) → dry → nch=1/4 →
>   weights per-piece verified → **state upload, conv images readback-verified,
>   the three SB_* CSRs read back** → EMBLOG2 → lockstep → chat. No DMA of any
>   kind before CALIB = 0xF; the state region is DMA'd like the weights.
> * **Residency now includes the conv images.** `sw/chat_seq.py` holds one
>   witness per conv image (the only part of the region the host wrote, so the
>   only part a host hash can hold); a conv miss invalidates the whole pack
>   exactly as a weight miss does. The whole-pack-hash replacement Step 3 asks
>   for covers the conv images too.
> * **Lockstep has a new line.** `ref/seq_model.py --gate` prints
>   `STATE BIT-EXACT (<n> block(s) stored; …)` beside the checkpoint line;
>   on silicon the state region's final image can be read back and compared
>   with the artifact's `state_final.bin` (`final_sha256`) after a run — do it
>   once, at the lockstep rung, and record the verdict; that is the on-chip
>   form of S4's `SMEM` golden.
> * **The layer term on silicon has TWO lanes now.** `L_LCYC` (compute lane,
>   `busy_cmp`) beside `L_SDMA_CYC` (the DMA lane, `sw/hwmap.py:229`; any write
>   clears). Report both per token. The comparands: S4's chip-TB whole-model
>   **131.14 ms/token** (6 tokens, TB memory models WLAT 40 / DDRLAT 32 — the
>   only whole-model figure, and NOT a board figure), the compute-lane
>   **45.674 ms/token** (S4 §5.3.1, like-for-like with Task 12's 46.079), and
>   the DMA lane's MODELLED 5.133 ms/token (LAT 8), which the board number
>   REPLACES — never add the modelled figure to anything. Task 12's cycle
>   census remains the better comparand than any tok/s model; the §10 band
>   (≈ 6.5–7.0 tok/s) was derived for the URAM-resident design with
>   `DN_PIPE = 2` and does not carry over as a target — report the measured
>   number and attribute it. DDR traffic per token is
>   `sw/tok_meter.state_bytes_per_token(T)`: 70 MiB at T = 512, 182 MiB at
>   T = 4,096 (label D) — say which channel(s) the region occupies.
> * **One new rung — long context.** T is now ≤ 4,096 —
>   `docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md` §0 D3
>   and §1 goal 3, **not** its §5, which is the ISA extension and states no
>   ceiling. **The old design's on-chip limit was 512**: the same goal 3 reads
>   "the context length ceiling rises from 512 to 4,096", and the RTL bound it
>   retires is the `T <= 512` in `rtl/attn_core.sv` that
>   `evidence/qwen9b/s3/S3_CHAIN.md` pins to the pre-spill tree.
>   Run one prompt longer than 512, lockstep-verified against `seq_model` (at S4's
>   chip-TB **131.14 ms/token** — a TB figure, not a board one — prefill is
>   minutes; the reference in Python is slower — budget it), and record the KV
>   region traffic. Prefill is DECODE-rate here (no batched prefill exists —
>   Step 6's caveat stands).
> * **Rollback** is build_035's bitstream (the 2B design, known good) — it
>   proves the board alive, not the 9B; its weights and address map differ.
> * **The version constants**: `sw/seq_run.py EXPECTED_SEQ_VERSION` and
>   `sw/infer.py EXPECT_VERSION` = Task 14-B's shipping netlist sha,
>   **`0xc973c18a`** (both still read `0x54443B9F`, build_035's);
>   `docs/USAGE.md` and `docs/ARCHITECTURE.md` gain the state-region rows (the
>   three SB_* CSRs, the region layout, the upload step) beside the
>   resident-bitstream rows.
> * **Board etiquette unchanged**: the shared flock, the readback TEED, the
>   safe reprogram flow only (`sudo -n sw/pcie_helper.sh remove` →
>   `sw/program_fpga.sh` JTAG volatile → `sudo -n sw/pcie_helper.sh rescan`),
>   never flash.

**PRECONDITIONS: Task 14 green, and Task 6's shared flock green.** The lock must
exist before any tool programs or DMAs the board — two live bitstreams now share
one BCU-1525.

**There is no 0.8B/2B back-compat ladder on this bitstream** (U4). The ladder is
9B from the first token.

**Files:**
- Modify: `sw/seq_run.py` (`EXPECTED_SEQ_VERSION`), `sw/infer.py`
  (`EXPECT_VERSION`), `docs/USAGE.md`, `docs/ARCHITECTURE.md`, `NEXT_SESSION.md`
- Create: `evidence/qwen9b/g6/RD9_GATE.md` + the run logs
- Test: the eight-rung ladder below

**Interfaces:**
- Consumes: Task 14's bitstream and its `VERSION`; Task 5's images and embedding;
  Task 11's streams; Task 3's repack-aware `plan_weights` and `tok_meter`.
- Produces: the measured tok/s, the layer term on silicon, and the residual clip
  counters that make §4.4's fragility **observed rather than assumed**.

- [ ] **Step 1: etiquette, then the safe reprogram**

Take the shared lock. Record which VERSION was resident before — **tee the
readback this time**; R-b's attribution of the previously resident bitstream is
`UNCONFIRMED` on record precisely because a readback was never teed. Check for
other board users across **both** worktrees.

Then the flow, and only this flow: `sudo -n sw/pcie_helper.sh remove` →
`sw/program_fpga.sh <bitstream>` (JTAG, **volatile only, never flash**) →
`sudo -n sw/pcie_helper.sh rescan`. Rollback target is build_035's bitstream,
known-good and on record.

- [ ] **Step 2: identity, then the dry rungs**

CSR identity first: MAGIC, `VERSION` = the new netlist hash, **CALIB = 0xF**,
UPTIME. **No DMA before CALIB is 0xF.** Then `seq_run --dry-run`, then nch=1,
then nch=4.

- [ ] **Step 3: the weight upload, readback-verified PER PIECE**

~3,902 MiB of W4 g128+GPTQ weights plus the 1,940.0 MiB embedding table.
**Readback-verified per PIECE, not per channel** — RD_GATE §4.2's lesson, where
a whole session ran on a 61.3 MiB-stale LM head and answered with the wrong
token, silently, because the residency probe took one witness per image per
*channel* and the head is chunk-interleaved.

**Carry RD_GATE's second fix too**: a miss re-uploads the **whole pack**. That
branch is *selftest-proven only* — on hardware every miss set was already
all-187 and it never fired — so 9B is the first real chance to exercise it.
Contrive that exercise deliberately rather than hoping for it.

**And take RD_GATE follow-on 2 while here**: replace the witness sample with the
**whole-pack hash**, which retires the sampling question outright. The residency
audit reads 1,847 MiB in ~3 s at 2B; at 9B's ~5.8 GiB budget ~10 s. §4.2
measured the witness sample at roughly one detection per three damaged pieces —
that is the number this replaces.

- [ ] **Step 4: EMBLOG2 13, written and read back**

Write it and read it back, and refuse a mismatch against the manifest. The R-d
record already shows this working at 2B ("EMBLOG2 12 written+read back").

- [ ] **Step 5: lockstep, then chat**

Lockstep against `seq_model` — golden state checks, **0 mismatches**. Then
`chat_seq --verify`, then greedy chat, then sampled chat with **4 seeds**:
seed-deterministic × 2 identical, seed-sensitive on a different seed.

The chat template is **not** the 2B's — it was re-derived at Task 5 because
4B/9B invert the `enable_thinking` default, emitting an **open** `<think>\n`
unless asked not to. Verify the template on-device output matches what Task 5
derived, and apply the re-derived `ntok >= 24` guidance.

- [ ] **Step 6: the perf census, measured**

Report **measured** tok/s against §10's re-anchored model — **≈ 6.5 – 7.0,
headline ≈ 6.56** (A1.6), not the 7.21 / 6.98–7.47 this plan carried before the
`int16` ruling; 7.21 is what the machine would do with **no** `DN_PIPE = 2`
latency price, i.e. only if Task 10 took the two-outstanding restructure and it
closed. **Compare against Task 12's measured wait-state cycle cost first** —
that is this build's own number and it is a better comparand than either
modelled figure. Report the
per-channel matvec spread, and the `L_LCYC` layer term. Record both
conventions — gate (`device/ntok`) and steady-state — as the R8-era ruling
requires.

**The modelled figure is DECODE ONLY. Prefill was never modelled**, and at these step
times a batched-prefill rung becomes much more valuable than it was at 2B, and
that is unquantified. **Any user-facing latency number — first-token, or a chat
turn — is not this figure, and this gate must not present it as one.**

D-TOK's disposition decides the tool: `sw/tok_meter.py` learned the repack at
Task 3, so use it; **if that fix is not in, the census comes from
`evidence/qwen2b/rd/rd_census.py`, exactly as R-d did** — this step must not
block on `tok_meter`.

If the measured number lands outside the band, **say so and attribute it**. The
model fails its only out-of-sample test (+1.7 % at nch=1), its r-bracket
validation is retracted, and its layer coefficient is a fit intercept, not a
measured cost. Task 12's cycle census is the better comparand; use it.

- [ ] **Step 7: the residual clip counters, on chip**

Record them, so §4.4's accepted fragility is **observed**. The rail is accepted
saturated: 95/108 top-1 was measured *with* the container at `|x|max 32767`,
which is better than the 90/108 that shipped at 2B and produced coherent chat on
silicon — but Track L's honest reading is that those are **upper bounds** on what
today's int16 Q7.8 residual delivers at H=4096, not clean measurements. Fragile,
not wrong. This is the first observation of it on hardware and the gate doc
carries it as such.

- [ ] **Step 8: gate doc, docs, commit**

`evidence/qwen9b/g6/RD9_GATE.md` in the house style, with each rung stated
against **its own basis** rather than one bound: the reprogram record with the
teed readback, the residency audit, the lockstep and chat transcripts, the perf
table in both conventions, the clip counters, and the watch-item disposition for
every class Task 14's census flagged. Update the resident-bitstream rows in
`docs/USAGE.md`, `docs/ARCHITECTURE.md` and `NEXT_SESSION.md`, and the two
version constants in `sw/`.

```bash
git commit -m "gate(G6): 9B on silicon — build_036 resident, 5.8 GiB uploaded and per-piece verified, EMBLOG2 13, lockstep 0 mismatch, chat coherent, measured tok/s and clip counters recorded" \
  -- sw/seq_run.py sw/infer.py docs/USAGE.md docs/ARCHITECTURE.md \
     NEXT_SESSION.md evidence/qwen9b/g6/
```

---

### Task 16: G7 — merge and ship

**The merge happens HERE, gated on Task 15 having passed** — the 2B campaign's
shape, where the decision authorized the merge but it was held until the gate
passed on silicon.

**Files:**
- Modify: `NEXT_SESSION.md` (rewritten, not appended)
- No new files; no code changes

**Interfaces:**
- Consumes: every gate doc under `evidence/qwen9b/`, all committed; Task 15's
  green board gate; Task 6's shipped lock path.
- Produces: `main` fast-forwarded to the G6 gate commit, and a `NEXT_SESSION.md`
  that a cold-resuming session can act on without reading this plan.

- [ ] **Step 1: preconditions**

Task 15's gate doc committed, tree clean, every gate doc under
`evidence/qwen9b/` present and committed. `git merge-base main qwen9b` ==
`main`'s HEAD — still a fast-forward. **STOP if `main` moved**: the orchestrator
prompts the user and the rebase-or-merge question is theirs, not this plan's.

- [ ] **Step 2: the merge**

`git checkout main && git merge --ff-only qwen9b && git checkout qwen9b`, then
verify `git log main -1` is the G6 gate commit.

- [ ] **Step 3: `NEXT_SESSION.md` rewritten to the new resident state**

Not appended — **rewritten**, per the spec's deliverable. It must carry:

- the resident bitstream, its VERSION, and the 9B pack that is loaded;
- **the two-bitstream operational note**: 0.8B and 2B stay served by
  `build_034_po2_AltSpreadLogic_high` and `build_035_fp2a_exc_po`, and serving
  either after the 9B ships requires a **bitstream swap plus a full weight
  re-upload**. The re-upload was already true — one pack fits DDR at a time. The
  **swap is new**, it goes through the CHARTER rails every time, and it is a
  ~2-minute operation, not a rebuild;
- **the board-lock ruling O3** as shipped, with the lock path;
- the statement that rebuilding 0.8B/2B artifacts from this tree is
  **unsupported**, with the pointer to Task 4's pin;
- **which host tools still drive the old bitstreams, by name** — the other half
  of Task 9's SHAPE-versioning decision. `shape_word`'s `isa=1` path keeps the
  direct-CSR tools working; `sw/chat_seq.py`'s ARG decoder does not survive
  Task 7, so reading a pre-G3 stream needs a pre-G3 tag. Pinned `.e`/`.seq`
  streams are unaffected because the SHAPE word travels inside the record.
  Spec §3.3 promises `ref/` and `sw/` still serve the old bitstreams; this line
  is where that promise is made precise instead of assumed;
- the follow-on list, including anything Tasks 1–15 parked, D-N7 (carried
  forward, deliberately not fixed — the one-word fix is safe only after auditing
  every `load_model` caller for in-place mutation, and aliasing without that
  audit trades a memory cost for a silent correctness bug), and the prefill rung
  §10 item 11 makes newly valuable.

```bash
git commit -m "docs(G7): post-merge state — 9B resident on build_036, two-bitstream operational note, O3 lock ruling, follow-on list" \
  -- NEXT_SESSION.md
```

---

## Open items for the user

These are named here rather than left to be discovered mid-execution. None
blocks starting Task 1.

1. ~~**The G1 STOP (O1) is live by construction.**~~ **CLOSED 2026-08-31: it
   halted the campaign three times and the user took option 1 (`int16`).** The
   fork's other branches — option 3 (DDR spill) and D (abandon) — were **not**
   taken and are **not closed**: Task 13 can re-open them (A1.3). What replaces
   this as the live user-facing risk is open item 10 below.
2. **O4 may return at Task 13** if the write-fan-out fix requires a `layer_0`
   pblock, against the 2B campaign's T5 "never".
3. **The spec's G2 lists "SEQ streams" in the golden chain, and they cannot be
   emitted there.** A 9B layer body peaks at 50,208 scratch words against the
   15-bit ISA's 32,768-word ceiling, so the emitter refuses until Task 7 lands
   the 16-bit encoding. This plan moves that one bullet to Task 11 and leaves
   the rest of G2's chain in Task 5. Flagged because it is a deviation from the
   spec's own gate list, forced by the spec's own arithmetic.
4. **`tb_seq_offifo` is NOT a second pre-existing red — the warning about it
   is stale, and an earlier revision of this plan believed the warning.** The
   recorded fix landed before `ec4216d`; `rtl/seq_unit.sv` has not moved since;
   the Makefile still announces a failure that cannot occur. Task 7 runs it,
   confirms green and deletes the echo. Recorded here because a plan that had
   proposed "land the recorded fix" would have **reintroduced** the race, and
   because `evidence/qwen2b/rc/t4_widen_gates.sh` does not run this target — so
   the stale claim was never going to be disproved by the usual driver.
5. **Stripping W8 and g64 deletes testbench targets and vector families.** That
   is the direct consequence of S5/S6 and U4; the gate doc records exactly what
   was retired. If the user wants those modes measurable again later, the RTL
   comes back — there is no re-add path in this plan, which is what O2 already
   ratified.
6. **The 17 spec prose residuals are a count without an enumeration.** The
   ledger records the number; nothing on disk lists them. Task 3 produces the
   enumeration and the count may move.
7. **Two G3 requirements are executed at G4, and both are declared rather than
   quiet.** The spec's G3 asks that the synthesizable envelope checks be proven
   "not to fire on the 9B stream" — that proof needs the stream, which Task 11
   emits, so Task 10 proves the firing half and Task 11 proves the non-firing
   half. And the spec assigns *recording* the LM head's packed footprint to G3,
   while the number is produced by Task 5's fit; this plan records it at Task 5
   and carries it forward rather than re-measuring.
8. **The SHAPE repack does not put `ng`'s seventh bit on bit 30**, which is the
   bit the spec's §5.2 sentence names. What the spec constrains numerically is
   "three spare bits left", and both options in Task 9 leave exactly three. If
   §5.2 is meant to pin the position, the field moves; the arithmetic does not.
9. **The spec's G3 line reads "Implement §4.2–§4.6 and §5.1–§5.4" — it omits
   §4.1 and nothing else.** W1's
   RTL — the DN banking itself, `int16` at 928 URAM since the 2026-08-31 ruling
   — has no gate in that sentence, yet G4's OOC gate checks its URAM count and
   G5a places it. This plan puts it in Task 10.
   Flagged as a gap in the spec's gate list, not a disagreement with it.
10. **THE LIVE ONE, and it replaces open item 1: Task 13 can invalidate the
    target.** The `int16` container's binding path is the write-control fan-out
    at **one logic level and 95.9 % route**, the fix is a placement constraint,
    and **nobody has ever tried it**. If it does not close, option B has no known
    route and O1 re-opens at option 3 (DDR spill) or D (abandon). **This is the
    single largest risk in the campaign now** — larger than the ISA blast radius,
    larger than `matvec` re-opening — because it is the only one that can end it.
11. ~~**`RS_F` under `int16` is unmeasured, and it is cheap.**~~ **CLOSED
    2026-09-01: measured, and `RS_F = 7` ADOPTED (A2).** Clips 23 → 0, top-1
    95 → 98, rank max and top-5 unmoved, repeat byte-identical. The
    container-dependence this item asserted was correct and is why the two
    earlier rejections stand. **What replaces it as open** is narrower and is
    not a blocker: 98/108 is a **four-prompt, 108-step fidelity** number, not a
    corpus-scale one, and the float ladder cannot supply the corpus-scale
    version in the form a reader expects — `ref/perplexity_eval.py` measures
    weight damage with float compute and touches `RS_F` only through the int16
    embedding-table round trip (`ref/perplexity_eval.py:474`), so a PPL point
    at 7 would price the embedding rounding, not the residual rail. Widening
    the fidelity measurement is available at G4 (Task 11) and is not a gate.
12. **`FABLE5_RS_F` is a process-global env knob, not tag-selected (A2.5).**
    The emit guard is tag-scoped via its caller and 9B-at-7 coexists correctly
    — verified — but exporting the variable across a byte-locked emission trips
    an emitter assert. Operational rule until the root fix lands: **do not
    export it across `evidence/qwen2b/rc/t4_bytes_unmoved.sh` or
    `ref/scripts/regen_gate.sh`.** The root fix
    (derive from `MS.TAG`, env as override) is flagged, not taken.
12. **The gate-port clamp changes what 60 of 768 DN heads compute, and every
    branch inherits it** (A1.9, spec **D-GATEPORT**). It is unpriced at scored
    resolution (≈ 7 h to price) and it is a property of the checkpoint against
    frozen `gate_unit` ports, not of anything this migration chose. Task 10
    re-opens `gate_unit` for NH = 32 anyway, so widening `A` / `dt_bias` is
    cheapest there **if** the user wants it fixed rather than recorded.
13. **The `dn_step` latency choice is a real design decision with an unpriced
    branch.** Option (ii), the two-outstanding restructure, would recover ≈ 10 %
    of throughput and **nobody has written it or shown that it closes**. Task 10
    Step 1′ reviews the choice; if (ii) is wanted, it needs its own budget.
14. **Found while planning, and not named in the spec: `STG = SCA + 1024` is a
    literal that collides at LNH=32.** `SCA_SZ` goes 992 → 1056 per §5.5, and
    the emitter parks the staging window 1024 words above `SCA`, so at 1056 the
    staging window lands on top of the `NH` tile — silently. The study's own
    allocator already models the fix as `max(1024, SCA_SZ)` and computed the
    50,208-word 9B peak with it, so the emitter and the peak disagree until the
    literal moves (an unfixed emitter gives 50,176 and an aliased map). Task 3
    owns it; it is inert at LNH=16.

