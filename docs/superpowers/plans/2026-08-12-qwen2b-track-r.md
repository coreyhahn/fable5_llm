# Qwen3.5-2B Track R (Geometry RTL) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Widen the hardware for H=2048/K=6144 (scratch 32K, VECNORM N=2048 + deadlock fix, MAX_NG=48, runtime EMB row size) so that one bitstream serves both models, gated by bit-exact frozen 0.8B replay and the full 0.8B HW ladder.

**Architecture:** Every change is geometry, not precision — the W4A8 wire format and all numerics are untouched. Widened scratch/engine addresses ride in ISA spare bits that are provably zero in every frozen 0.8B stream, so committed streams replay bit-exact; the emitter learns the new bits only for 2B streams. RTL first (Verilator TDD per unit), then one build + reroll spread, then the 0.8B ladder on hardware.

**Tech Stack:** SystemVerilog (`-Wall`-clean, Verilator 5.020, `--timing`), Verilator TBs in `tb/` (4 seeds), Vivado 2024.2 on snoke via `synth/scripts/launch_build.sh` / `launch_reroll.sh`, host tools in `sw/` (numpy venv).

**Spec:** `docs/superpowers/specs/2026-08-12-qwen35-2b-migration-design.md`

## Global Constraints

- NEVER read/grep/copy the pre-existing private implementation (the "answer key") (answer key) — hard rule.
- Branch `qwen2b`; commit at every green gate; evidence to `evidence/qwen2b/<stage>/`.
- Frozen 0.8B artifacts NEVER regenerate differently: `tb/scripts/layer_s*`, `token_s*`, `model_v2_s*`, `w3/`, `w4/` stay byte-identical, and `chat_seq.py`'s emitter hash lock (`sha256(model_v2_s1.e.seq) == a69864d2…`, nrec 60495, `docs/USAGE.md:629-633`) must keep holding.
- TB discipline: drive/sample at NEGEDGE only; `$fatal(1, ...)` for failures (never bare `$finish`); 4 seeds minimum; logs to `evidence/qwen2b/`.
- Heavy sims (model_v2, seq_chip, chat_i1) run ON SNOKE; never build/run one obj_dir from two machines at once.
- Assertion house style (no SVA): procedural checks in `` `ifndef SYNTHESIS `` guards, qualified by `rstn` + handshake, module-name-prefixed message, `$fatal(1,...)` for HW-contract breaks / `$error` for host misuse (pattern: `rtl/vec_alu.sv:758-768`).
- Vivado builds only on snoke, detached via launch scripts, fresh `out_<build>` per build, clock-sanity gate stays in build.tcl.
- Safe reprogram only: `sudo -n sw/pcie_helper.sh remove` → `sw/program_fpga.sh <bit>` → `sudo -n sw/pcie_helper.sh rescan`; JTAG volatile only; no DMA before CALIB=0xF.

**Cross-plan interfaces (with Track Q plan, `2026-08-12-qwen2b-track-q.md`):**
- Consumes Track Q Task 1 (`FABLE5_MODEL` / `ref/model_select.py`). Do not start Task 1 here until that exists.
- Task 2 here produces the re-normalized per-row mover costs that Track Q Task 10's tok/s column consumes.
- This plan ends at the R-b HW gate. Gate D (with Track Q's table) decides the post-D plan (R-c/R-d ± W8 engine mode), which is written then, not now.

---

### Task 1: R-a — scratch-map re-derivation + parameterized emitter, locked by the regen gate

**Files:**
- Modify: `ref/gen_layer_script.py`, `ref/gen_token_script.py` (slot plan), `ref/gen_model_script.py` — only where a 0.8B geometry number is hardcoded (audit first; most geometry already flows from `layer_ref` constants)
- Create: `docs/QWEN2B_SCRATCH_MAP.md`, `ref/scripts/regen_gate.sh`
- Test: the regen gate script.

**Interfaces:**
- Consumes: `ref/model_select.py` (Track Q Task 1).
- Produces: an emitter that, under `FABLE5_MODEL=2b`, plans scratch for H=2048 into ≤32,768 words; under default, emits byte-identical 0.8B artifacts. `docs/QWEN2B_SCRATCH_MAP.md` = the derived 2B map (consumed by Task 5's TB cases and the post-D plan).

- [ ] **Step 1: Write the regen gate FIRST (it must pass before and after every emitter edit)**

```bash
# ref/scripts/regen_gate.sh — 0.8B artifacts must regenerate byte-identical
set -e
cd "$(dirname "$0")/../../tb"
GOLD_SEQ_SHA=a69864d25b6b129a4d6c74b3c78dfcbedf1edce219d32cc05d05bc54f444aaf1  # docs/USAGE.md:629-633
TMP=$(mktemp -d)
cd ../ref
SEQ_EMIT=$TMP/model_v2_s1.e SEQ_PROFILE=epsnorm \
  ${MODELPY:-/home/cah/.venv/bin/python} gen_model_script.py $TMP/model_v2_s1.txt 1 3 --res-scale=8 --allow-clip
[ "$(sha256sum $TMP/model_v2_s1.e.seq | cut -d' ' -f1)" = "$GOLD_SEQ_SHA" ] || { echo REGEN_GATE_FAIL; exit 1; }
cmp $TMP/model_v2_s1.txt ../tb/scripts/model_v2_s1.txt || { echo REGEN_GATE_FAIL_TXT; exit 1; }
echo REGEN_GATE_PASS
rm -rf $TMP
```

Run it on the UNMODIFIED tree first: `bash ref/scripts/regen_gate.sh` → `REGEN_GATE_PASS` (needs HF 0.8B cache + ~950 MB scratch space; run on darthplagueis or snoke). If it fails on the unmodified tree, STOP — the environment differs from the one that built the frozen artifacts; debug that first.

- [ ] **Step 2: Audit for hardcoded 0.8B geometry**

```bash
grep -nE '16384|16383|15532|16266|0x3fff|0x4000\b|1024|3584' ref/gen_layer_script.py ref/gen_token_script.py ref/gen_model_script.py
```

Classify every hit: derives-from-`LR.H` (fine) vs hardcoded (fix to derive from `layer_ref` constants). Known 0.8B stream constants that must NOT change (they are frozen-stream facts, not code geometry): `sw/chat_seq.py` `X8_WORD=0x800`, `STG_WORD=0x1000`, `HEAD_TAIL=(15532,16266)` — those describe the committed 0.8B stream and are re-derived per-model by `derive_geometry()` at run time (`sw/chat_seq.py:586`); leave them.

- [ ] **Step 3: Derive the 2B scratch map**

Run the emitter's slot planner under `FABLE5_MODEL=2b` (script-gen only, no weights needed if possible — if `gen_layer_script` can plan without the checkpoint, do that; otherwise wait for the 2B download from Track Q Task 2). Write `docs/QWEN2B_SCRATCH_MAP.md`: every scratch region (x8 vector, staging, DN body tiles, MLP tiles, head tail) with start/size at H=2048, the two claims from feasibility re-verified (DN 19,424 words, MLP 24,576 words), total ≤ 32,768, and the collision-freedom argument. If a region exceeds 32K, STOP and escalate — that invalidates the R-b scratch sizing.

- [ ] **Step 4: Re-run the regen gate + commit**

`bash ref/scripts/regen_gate.sh` → `REGEN_GATE_PASS`.

```bash
git add ref/scripts/regen_gate.sh docs/QWEN2B_SCRATCH_MAP.md ref/gen_layer_script.py ref/gen_token_script.py ref/gen_model_script.py
git commit -m "ref(R-a): emitter parameterized for 2B scratch planning; 0.8B regen gate (emitter hash lock) green; 2B scratch map derived"
```

---

### Task 2: R-a — close the feasibility U-items (mover per-row costs; utilization; dn bank addr)

**Files:**
- Create: `evidence/qwen2b/ra/{MOVER_NORM.md, util_resident.md, dn_bank_verify.md}`

**Interfaces:**
- Consumes: `evidence/rung3/mover_bench_build032.json` (per-class `cyc_per_rec`: e.g. movy 2184.7, mvgo_head 30885.55, ldc 1618.87; `sw/mover_bench.py:12-19` class docs).
- Produces: per-ROW mover costs + 2B mover-bucket ms band → Track Q Task 10's tok/s model. Firmed SLR1 BRAM baseline for Task 8's timing risk assessment.

- [ ] **Step 1: Re-normalize mover costs per row**

For each mover class in `mover_bench_build032.json`, divide `cyc_per_rec` by the rows (or elements) that record moves at 0.8B geometry (from the record's donor `addr_lo`/`imm32` and the stream layout — donors are in `_donors.<class>`), then multiply by the 2B geometry counts (H 1024→2048 doubles MOVX/MOVY element counts; MVGO row counts scale per matvec shape; LDC record counts from the 2B stream plan). Cross-check: recompute the 0.8B mover bucket from the per-row numbers — it must land on the measured ~9 ms/token (nch=4, `docs/ARCHITECTURE.md:624-631`) within 15%; if it doesn't, the normalization is wrong — fix before publishing. Write `MOVER_NORM.md` with the math and the 2B band (replaces the feasibility study's 11-14 ms U band).

- [ ] **Step 2: Record the resident build's utilization (U-item already closed — document it)**

The resident reroll's placed report exists: `synth/out_build_033_rr_AltSpreadLogic_medium/proj/stage1.runs/impl_1/bd_wrapper_utilization_placed.rpt:395-397` — Block RAM Tile SLR0/1/2 = 25.5 / 505.5 / 29.5 (3.54% / 70.21% / 4.10%). Copy the relevant table into `evidence/qwen2b/ra/util_resident.md` with the +14 RAMB36 scratch-growth projection (505.5 → ~519.5 ≈ 72.2% SLR1) and one sentence on headroom.

- [ ] **Step 3: Verify the dn bank address expression**

Read the dn state memory addressing in `rtl/` (dn_mem / URAM banks in the DNST path) and confirm the feasibility claim that dn URAM state is geometry-invariant at 2B (16 heads, dk=dv=128 unchanged ⇒ addresses independent of H). Write the actual expression + one-paragraph argument into `dn_bank_verify.md`. If it is NOT invariant, flag it as new R-b scope immediately (plan amendment).

- [ ] **Step 4: Commit**

```bash
git add evidence/qwen2b/ra/
git commit -m "evidence(R-a): mover per-row costs re-normalized (2B band firmed), resident SLR1 BRAM 70.21% recorded, dn bank invariance verified"
```

---

### Task 3: R-b — VECNORM N=2048 + the nlog2 deadlock fix

> ### PRE-G3.3 ROWS, KEPT AS THE RECORD — dated note 2026-09-02 (Task 9)
>
> Rows here marked `<!--cites:noquote-->` quote **source that G3.3 DELETED**,
> not source that merely moved: the `cfg_w8` / `cfg_g64` ports and everything that selected on them, SHAPE bits 28 and 29, and the W8-envelope adder tree.  They are kept verbatim, because they
> are the record of what the pre-G3.3 tree said and the argument they support
> rests on them (§0: nothing is deleted or struck).  The exemption marker is
> used for exactly the reason §7.6 gives — *"an exemption is for source that
> no longer exists, not for a citation that has merely moved"* — and every
> citation that had merely MOVED was RENUMBERED instead, mechanically, by
> `evidence/qwen9b/o3/o3_cite_drift.py --base a08a90b`.
> **The post-G3.3 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_3_MATVEC.md` §11.1.**

**Files:**
- Modify: `rtl/vecnorm_unit.sv` (counters at `rtl/vecnorm_unit.sv:151`, buffers at `rtl/vecnorm_unit.sv:100-101`, index slices at `rtl/vecnorm_unit.sv:215-216` and `rtl/vecnorm_unit.sv:275`, the overflow line at `rtl/vecnorm_unit.sv:269`), `rtl/layer_chan.sv:1421` (`n_elems`)
- Test: `tb/tb_vecnorm.sv` (+ new N=2048 and deadlock cases), `tb/scripts/gen_seq_c_vectors.py` (N=2048 golden)

**Interfaces:**
- Produces: `vecnorm_unit` correct for N up to 2048 (`cfg_nlog2` ≤ 11), `$fatal` on `cfg_nlog2 ≥ 12`. No port changes — `cfg_nlog2` is already `[3:0]` (`rtl/vecnorm_unit.sv:77-84`).

- [ ] **Step 1: Write the failing test — the latent deadlock, demonstrated**

Add a directed case to `tb/tb_vecnorm.sv`: configure `cfg_nlog2=11`, feed 2048 elements, wrap in a cycle watchdog (~50k cycles) that `$fatal(1, "tb_vecnorm: nlog2=11 FILL never terminated")`. On TODAY's RTL this must fail via the watchdog — that reproduces the bug (`n_total <= 11'd1 << cfg_nlog2` wraps to 0 at `rtl/vecnorm_unit.sv:277`; the terminators at `rtl/vecnorm_unit.sv:277` and `rtl/vecnorm_unit.sv:396` never match). [corrected during execution (R-b, 2026-08-13): the wrap is real but FILL DOES terminate — `cnt+1` wraps in 11 bits exactly as `n_total` does, so :277 fires at cnt=2047 and the unit swallows all 2048 elements. The deadlock is in OUT: `issue = (oidx != n_total)` = (0 != 0) is false forever, so no address is ever issued and :396 is never reached. Measured: evidence/qwen2b/rb/red_nlog2_11_deadlock.log; mechanism recorded in docs/QWEN2B_FEASIBILITY.md.]

- [ ] **Step 2: Run it to verify it fails**

```bash
cd tb && make tb_vecnorm
```
Expected: the new case dies on the watchdog. (Existing cases still pass — they run N≤1024.)

- [ ] **Step 3: Widen**

In `rtl/vecnorm_unit.sv`:
- `:151` `logic [10:0] cnt, n_total;` → `logic [11:0]`; same for `oidx` (:153), `ecnt` (:154).
- `:269` `n_total <= 11'd1 << cfg_nlog2;` → `n_total <= 12'd1 << cfg_nlog2;`
- `:100-101` `xbuf [1024]` / `wbuf [1024]` → `[2048]`; index slices `oidx[9:0]` (:215-216) and `cnt[9:0]` (:275) → `[10:0]`.
- Header comment `:11` "N = 2^n_log2 <= 1024" → 2048.
- New guard, house style:

```systemverilog
`ifndef SYNTHESIS
    always_ff @(posedge clk) begin
        if (rstn && cfg_valid && cfg_nlog2 >= 4'd12)
            $fatal(1, "vecnorm_unit: cfg_nlog2 %0d unsupported (max 11, N=2048)", cfg_nlog2);
    end
`endif
```

(Use the module's actual config-strobe signal in place of `cfg_valid` — take it from the FILL-start condition at :269's enclosing block.) Check `eps_sh` (:117) and `rs_p` (:316) arithmetic still correct at nlog2=11.

In `rtl/layer_chan.sv:1421`: `n_elems <= 14'd1 << arg0[5:2];` → sized to `n_elems`'s new width from Task 5 (if Task 5 lands later, widen `n_elems` to `[14:0]` here with `15'd1 <<` — Verilator lint will arbitrate consistency).

- [ ] **Step 4: N=2048 golden + all seeds green**

Extend `tb/scripts/gen_seq_c_vectors.py` to also emit an rmsnorm case at N=2048 (reference = the same numpy rmsnorm it already uses at N=1024, `tb/tb_vecnorm.sv:176-180` pattern), and make the deadlock case now expect COMPLETION with correct output. Run:

```bash
cd tb && make tb_vecnorm   # seeds 1-4 per tb/Makefile:266-269  <!--cites:noquote-->
```
Expected: all 4 seeds PASS incl. the two new cases. Lint: `make lint_...` equivalents — `verilator --lint-only -Wall --timing` must stay clean.

- [ ] **Step 5: Commit**

```bash
git add rtl/vecnorm_unit.sv rtl/layer_chan.sv tb/tb_vecnorm.sv tb/scripts/gen_seq_c_vectors.py
git commit -m "rtl(R-b): vecnorm N=2048; fix latent nlog2=11 wrap-to-zero deadlock (12-bit n_total) + fatal guard at nlog2>=12"
```

---

### Task 4: R-b — MAX_NG 48 (K=6144) + generalized scale beats + XWIN 1536

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

**Files:**
- Modify: `rtl/matvec_engine.sv` (:99 MAX_NG, :116 x_waddr, :132 NSCAL, :143-148 x_mem, :161-166 scale-beat logic, :331-332 acc banks), `rtl/matvec_chan.sv` (:203 xptr, :318 XPTR CSR, :407 queue field, :620 window fatal), `rtl/seq_movers.sv` (:169 XWIN_WORDS)
- Test: `tb/Makefile` (`NGSHAPES`/`V2SHAPES` additions), via `tb/scripts/gen_matvec_v2_vectors.py` (golden = `ref/w4a8_ref.py`, which ALREADY generalizes scale beats as `ceil(NG64/32)`)

**Interfaces:**
- Produces: engine correct for NG 1..48 (K ≤ 6144) in BOTH group modes. Wire format unchanged — the ref (`w4a8_ref.row_beats/pack_ddr_rows`) already defines the >2-scale-beat layout; the RTL catches up. `cfg_ng[5:0]` already holds 48 (`rtl/matvec_engine.sv:106`).  <!--cites:noquote-->

- [ ] **Step 1: Write the failing tests — K=6144 shapes vs the ref**

Add to `tb/Makefile` `NGSHAPES` (:73) new shapes: `n5:9:6144:6500` (NG=48, the wall) and `n6:21:4608:6600` (NG=36, mid) — same `name:nrows:K:seedbase` grammar as `n1:23:128:6100`. Also add a `V2SHAPES` shape at K=6144 so `tb_matvec_g64` covers g64 with 3 scale beats and MIXED-mode switching. Generate vectors (`make ng_vectors v2_vectors`) — the generator calls `w4a8_ref`, which packs `ceil(NG64/32)` scale beats already; verify the produced g64 K=6144 vector dir has 3 scale beats per row (inspect with `ref/.venv/bin/python -c "from w4a8_ref import row_beats; print(row_beats(6144,64), row_beats(6144,128))"` — expect (48+3, 48+2)).

- [ ] **Step 2: Run to verify they fail**

```bash
cd tb && make tb_matvec_ng tb_matvec_g64
```
Expected: new shapes FAIL/mismatch on today's RTL (MAX_NG=32 arrays overflow / scale-beat count wrong). Existing shapes still pass.

- [ ] **Step 3: Implement**

`rtl/matvec_engine.sv`:
- `:99` `parameter int MAX_NG = 48; // max groups/row (K <= 6144)`; NSCAL follows (:132, `2*MAX_NG` = 96).
- Activation buffer: `:143` `x_mem [32][MAX_NG]` grows; write decode `:146-148` bank=`x_waddr[4:0]`, line=`x_waddr[9:5]` → line needs 6 bits: `x_waddr` `[9:0]`→`[10:0]` (:116), line=`x_waddr[10:5]`.
- Scale beats, generalized from the hardcoded 2-max: today `two_scale_beats = cfg_g64 && (cfg_ng > 6'd16)` (:161). Replace with a count: g64 → `n_scale_beats = (cfg_ng + 6'd15) >> 4` (= ceil(2*ng/32): 1/2/3 for ng ≤16/≤32/≤48); g128 → `n_scale_beats = (cfg_ng + 6'd31) >> 5` (1 for ng≤32, 2 for 33..48). Rework `last_scale_g`/`is_scale_beat`/`scale_beat_idx` (:162-166) and the scale-bank ownership (:340-341 region) to index up to 3 beats; `r_last` (:397) and `mac_last_q` (:515) unchanged in form. NOTE: g128 mode grows a 2nd scale beat for the first time — mirror exactly what `w4a8_ref.pack_ddr_rows` (:192) emits; the TB-vs-ref gate is the arbiter.
- Accumulators `:331-332` size off MAX_NG automatically.

`rtl/matvec_chan.sv`: `xptr` `[9:0]`→`[10:0]` (:203), XPTR CSR write (:318), x-queue waddr field 10→11 bits (:407 `xq_d[41:32]` — widen the queue packing consistently), XWIN window fatal bound 1024→1536 words (:620). `rtl/seq_movers.sv:190` `XWIN_WORDS = 1024` → `1536`.

- [ ] **Step 4: Full matvec suite green**

```bash
cd tb && make tb_matvec tb_matvec_ng tb_matvec_g64 tb_matvec_chan tb_matvec_chan_g64 tb_mvshim_b lint_matvec
```
Expected: all pass, 4 seeds each, incl. new K=6144/K=4608 shapes both modes; lint clean. Frozen-format regression: shape `c` (K=4096 NG=32, the old ceiling) must still pass — it proves g128 1-scale-beat behavior is bit-identical.

- [ ] **Step 5: Commit**

```bash
git add rtl/matvec_engine.sv rtl/matvec_chan.sv rtl/seq_movers.sv tb/Makefile tb/scripts/gen_matvec_v2_vectors.py
git commit -m "rtl(R-b): MAX_NG=48 (K<=6144); scale-beat count generalized (g64 up to 3, g128 up to 2) to match w4a8_ref; XWIN 1536 words"
```

---

### Task 5: R-b — scratch 16K→32K words (the blast radius task)

**Files:**
- Modify: `rtl/layer_chan.sv` (memories :254-255, every `[13:0]` addr signal — inventory in Step 2, ISA decode slices, SPTR :650, S6 shim :1337-1577 + guards :1738-1767), `rtl/seq_unit.sv` (mover addr slices at `rtl/seq_unit.sv:1014`, `rtl/seq_unit.sv:1029`, `rtl/seq_unit.sv:1049`, `rtl/seq_unit.sv:1064`; overflow literal at `rtl/seq_unit.sv:1214`), `rtl/seq_movers.sv` (:72 cmd_saddr, :170 SCR_WORDS, MVB window map), `sw/hwmap.py:180` (SCRATCH_WORDS), `docs/SEQ_ISA.md` (v1.6→v1.7: new high-bit field homes)
- Create: `ref/scripts/scan_spare_bits.py`
- Test: frozen replay suite + new high-address directed cases via `tb/tb_seq_layer` generator

**Interfaces:**
- Consumes: Task 1's 2B scratch map (proves ≤32K suffices).
- Produces: 15-bit scratch addressing everywhere; bit-14 of each ISA address field rides in a spare bit that is PROVEN zero across all frozen streams; `docs/SEQ_ISA.md` v1.7 documents every new bit home. Emitter (`ref/seq_format.py`/`gen_layer_script.py`) emits the high bits (zero for all 0.8B streams ⇒ regen gate unaffected).

- [ ] **Step 1: Prove the spare bits are spare — scan every frozen stream**

Write `ref/scripts/scan_spare_bits.py`: parse all committed layer command scripts (`tb/scripts/layer_s*.txt`, `token_s*.txt`, `model_v2_s*.txt`) and SEQ records (`tb/scripts/w3/*.seq`, `w4/*.e.seq`), OR-accumulate arg0/arg1/arg2 (and SEQ addr_lo/target) per opcode, print a per-opcode mask of bits that are EVER set. Output → `evidence/qwen2b/rb/spare_bits_report.txt`. The chosen bit-14 homes (next step) must all be 0 in this report — that is the back-compat proof, produced BEFORE any RTL decode changes.

- [ ] **Step 2: Fix the bit-14 assignment table (from the report + `rtl/layer_chan.sv:69-92` header)**

Planned homes (verify each against the scan; adjust only if the scan shows a conflict, and record the final table in SEQ_ISA v1.7):

| field (today) | bit-14 home |
|---|---|
| VN/DNST-style `src[13:0]` in arg1/arg2 | same word, bit 28 |
| VN/DNST-style `dst[27:14]` | same word, bit 29 |
| ALU `arg2 = {dst[30:17], p0[16:0]}` | bit 31 (the ONLY spare — `rtl/layer_chan.sv:907`) |
| ALU `cfg_srca/srcb = arg1[13:0]/[27:14]` | bits 28/29 |
| GATE `dst = arg0[13:0]` | bit 28 |
| GATE `ld_src = arg0[17:4]` | bit 18 IF spare per scan, else a spare in arg1 |
| FEED selects `arg0[31:18]` (:1081) | NO adjacent spare — home in that command's arg1/arg2 spare per scan (known-tight, decide from data) |
| SPTR CSR (:650) | `wdata_q[14:0]` directly (CSR, not a stream field) |
| SEQ MOVX/MOVY/EMB `addr_lo[13:0]` | `addr_lo[14]` (addr_lo is a full 32-bit field, 18 spare — `docs/SEQ_ISA.md:342-370`) |
| SEQ LDC `target[13:0]` | `target[14]` (16-bit field, 2 spare — `rtl/seq_unit.sv:1112`) |

- [ ] **Step 3: Write the failing test — a >16K-word stream**

Extend the `tb_seq_layer` generator (`tb/Makefile:228` `seq_layer_scripts`, regenerable by design) to emit a directed script that round-trips data through scratch words 16384..32767 (VN + ALU + GATE ops with bit-14 set per the table), golden from `ref/layer_fixed.py` ops. Run `make tb_seq_layer` → FAIL on today's RTL (address wraps into low scratch, data mismatch).

- [ ] **Step 4: Widen the RTL**

- `rtl/layer_chan.sv`: `smem_a/smem_b [16384]` → `[32768]` (:254-255); ALL `[13:0]` scratch signals → `[14:0]` (inventory from the fact sheet: sptr :228, hw_addr :238, sa/sb_addr :256, sw_addr :258, alu_aa/ba/wa :511, eng_sa/eng_swa :766-767, fi/ci/f_ai :771-773, n_elems :777 (+ its `<<` at :862 → `15'd1`), ld_src :780, dst_r/src2_r :800, bw_addr/br_addr :1337-1548, wa_ptr :1577). Decode slices grow per the Step-2 table (`{arg1[28], arg1[13:0]}` composition style).
- `vec_alu` port widths follow (`cfg_srca/srcb/dst` and its internal `[13:0]`s — `rtl/vec_alu.sv` scratch ports; extend its collision `$fatal` guards' address widths :758-768).
- S6 burst shim: word index `awaddr[15:2]` → `awaddr[16:2]` (128 KiB aperture), bound checks `> 15'd16383` → `> 16'd32767` (:1738-1757 and matching read side); audit the s_axib/mover-bus window map (`rtl/seq_movers.sv` `MVB_*` localparams, :165-170) so the doubled scratch span doesn't overlap the next window — renumber internal MVB bases if needed and mirror in `sw/hwmap.py` + `docs/SEQ_ISA.md`.
- `rtl/seq_unit.sv`: `mv_saddr <= r_lo[14:0]` (:966), MOVY (:981), `bulk_dst` (:1001, :1016 with `r_tgt[14:0]`), overflow literal `32'd16384` → `32'd32768` (:1163).
- `rtl/seq_movers.sv`: `cmd_saddr [14:0]` (:72), `SCR_WORDS = 32768` (:170), window `$error` bounds (:637-643, :745-752).
- `sw/hwmap.py:180` `SCRATCH_WORDS = 32768` — but ONLY if sw reads it for bounds (it describes RTL geometry); grep sw/ for `SCRATCH_WORDS` consumers and update bounds checks coherently.
- Emitter: `ref/seq_format.py` + `gen_layer_script.py` encode bit-14 per the table (a helper `enc_saddr(a)` asserting `a < 32768`).

- [ ] **Step 5: The full back-compat + new-capability gate**

```bash
cd tb
make tb_vec_alu tb_vecnorm tb_layer_chan tb_token tb_seq_layer tb_ru2_diff    # unit + frozen short set
make chain_scripts tb_chain && make token24_scripts tb_token24                # regenerated mid set
ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm/tb && make tb_model_v2_all tb_seq_chip && make chat_i1_gate CHAT_PY=/home/cah/.venv/bin/python'
bash ref/scripts/regen_gate.sh
```

Expected: every frozen script replays bit-exact (layer_s*, token_s*, model_v2_s1..s4, w3 seq_chip, w4 chat_i1 — all UNMODIFIED files), the new >16K directed case passes, regen gate still `REGEN_GATE_PASS` (emitter emits zeros in the new bits for 0.8B). Lint clean across touched modules. Budget: model_v2_all + chat_i1 on snoke ≈ 1-2 h.

- [ ] **Step 6: SEQ_ISA v1.7 + commit**

Update `docs/SEQ_ISA.md` header to v1.7: the bit-14 table, SPTR width, SCR_WORDS 32768, S6 aperture 128 KiB, MVB map changes. Update the `rtl/layer_chan.sv:69-92` ISA header comment to match.

```bash
git add rtl/ ref/seq_format.py ref/gen_layer_script.py ref/scripts/scan_spare_bits.py sw/hwmap.py docs/SEQ_ISA.md tb/ evidence/qwen2b/rb/spare_bits_report.txt
git commit -m "rtl(R-b): scratch 32K words, 15-bit addressing via proven-spare ISA bits; frozen 0.8B replay bit-exact; SEQ_ISA v1.7"
```

---

### Task 6: R-b — EMB row size becomes runtime (log2 CSR)

**Files:**
- Modify: `rtl/seq_unit.sv` (:278 localparam → CSR-backed reg, :828-829 the address expression; CSR decode in the SEQ block), `docs/SEQ_ISA.md` (new CSR), `ref/gen_model_script.py` (manifest field), `sw/seq_run.py` + `sw/chat_seq.py` (write CSR at bring-up; row size from manifest, replacing the `//2048` at `chat_seq.py:2101`)
- Test: `tb/tb_layer_chan.sv` EMB path (`EMB_ROW_B` localparams :103-105) + a seq_unit EMB directed case

**Interfaces:**
- Produces: SEQ CSR `EMBLOG2` (reset value 11 = today's 2048 B — one bitstream serves both models), address math `emb_a = base + (token << EMBLOG2)`. Manifest key `"emb_row_bytes"` in `<prefix>.weights.json`. sw writes the CSR before the first EMB record.

- [ ] **Step 1: Failing test**

Add a `tb_seq` (seq_unit vectors, `tb/scripts/gen_seq_unit_vectors.py`) directed EMB case with row size 4096 (write the new CSR, expect `emb_a = base + token*4096`). FAIL on today's RTL (constant 2048; CSR write to the new address is ignored → wrong fetch address detected by the checker).

- [ ] **Step 2: Implement RTL**

Replace `localparam int EMB_ROW_BYTES = 2048` (`rtl/seq_unit.sv:288`) with a register `logic [4:0] emb_row_log2;` reset to `5'd11`, written by a new SEQ CSR (pick the next free offset in the SEQ block per `docs/SEQ_ISA.md` — the CSR map at `rtl/seq_unit.sv:24-43`; readback included). Address expression (:828-829) becomes:

```systemverilog
wire [ADDR_W-1:0] emb_a = ADDR_W'({r_tgt, r_imm})
                        + (ADDR_W'(xrf[3]) << emb_row_log2);
```

(shift replaces the `* EMB_ROW_BYTES` multiply — row sizes are powers of two: 2048/4096). Guard, house style: `$error` if `emb_row_log2 < 5'd8 || > 5'd13` on CSR write (host misuse class).

- [ ] **Step 3: Plumb sw + manifest**

`gen_model_script.py`: write `"emb_row_bytes": 2*LR.H` into the weights manifest. `sw/seq_run.py` upload/setup path + `sw/chat_seq.py`: read it (default 2048 when absent — old artifacts), replace the literal at `chat_seq.py:2101` (`os.path.getsize(s.embf) // row_bytes`), write the CSR during bring-up before any EMB record. `sw/hwmap.py`: add the CSR offset constant.

- [ ] **Step 4: Green + regen + selftests**

```bash
cd tb && make tb_seq_all tb_layer_chan tb_token
bash ref/scripts/regen_gate.sh              # manifest gains a key — the .e.seq/.txt stay byte-identical (gate proves it)
cd ../sw && make seq_selftest serve_test    # 0-board selftests absorb the manifest/CSR plumbing
```
Note: the manifest JSON gains a key, which changes `<prefix>.weights.json` — that file is regenerable, NOT part of the frozen byte-identical set (the gate checks `.txt` + `.e.seq` only); confirm `chat_seq --selftest` still passes with both old (key-absent) and new manifests.

- [ ] **Step 5: Commit**

```bash
git add rtl/seq_unit.sv docs/SEQ_ISA.md ref/gen_model_script.py sw/seq_run.py sw/chat_seq.py sw/hwmap.py tb/
git commit -m "rtl+sw(R-b): EMB row size runtime CSR (EMBLOG2, reset=11) — one bitstream serves 0.8B and 2B"
```

---

### Task 7: R-b sim gate — the whole ladder, one roll-up

**Files:**
- Create: `evidence/qwen2b/rb/SIM_GATE.md` + logs

**Interfaces:**
- Consumes: Tasks 3-6 all merged on `qwen2b`.
- Produces: the committed sim evidence that R-b RTL is a strict superset of today's behavior. Precondition for Task 8 (no build until this is green).

- [ ] **Step 1: Full regression, clean tree, both machines**

```bash
cd tb && make tb_vec_alu tb_vecnorm tb_matvec tb_matvec_ng tb_matvec_g64 tb_matvec_chan tb_matvec_chan_g64 tb_mvshim_b tb_layer_chan tb_token tb_seq_layer tb_layershim_c tb_topk tb_seq_all tb_seq_offifo tb_ru2_diff 2>&1 | tee ../evidence/qwen2b/rb/sim_units.log
make chain_scripts tb_chain && make token24_scripts tb_token24 2>&1 | tee -a ../evidence/qwen2b/rb/sim_units.log
ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm/tb && make tb_model_v2_all tb_seq_chip tb_seq_chip_fast && make chat_i1_gate CHAT_PY=/home/cah/.venv/bin/python' 2>&1 | tee ../evidence/qwen2b/rb/sim_heavy.log
bash ref/scripts/regen_gate.sh 2>&1 | tee -a evidence/qwen2b/rb/sim_units.log
```

All 4-seed sets, all frozen streams unmodified, all green. Any red: fix via systematic-debugging before proceeding — never rerun until green without understanding.

- [ ] **Step 2: Write SIM_GATE.md (gate-doc house style: provenance, gates list, follow-ons) + commit**

```bash
git add evidence/qwen2b/rb/
git commit -m "evidence(R-b): full sim gate green — widened RTL replays every frozen 0.8B stream bit-exact + new-geometry directed cases"
```

---

### Task 8: R-b build + reroll spread + timing gate

**Files:**
- Create: `synth/out_build_034*/` (Vivado outputs, not committed), `evidence/qwen2b/rb/TIMING.md`

**Interfaces:**
- Consumes: Task 7 green.
- Produces: a routed bitstream with WNS ≥ 0 and the utilization delta vs build_033. VERSION CSR = the build commit's short hash.

- [ ] **Step 1: Confirm next build number + launch on snoke (detached)**

```bash
ls /home/cah/r2d2/code/fpga/fable5_llm/synth/ | grep -E '^out_build_[0-9]+' | sort | tail -3   # expect 033 highest → this is build_034
ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm/synth/scripts && nohup ./launch_build.sh build_034 > launch_build_034.out 2>&1 &'
```

~3h10m (build_033 measured). Monitor: `tail synth/out_build_034/build_run.log`; gates in-flow: `CLOCK_GATE_OK`, `BUILD_OK` (`synth/scripts/build.tcl:34-48,70-72`).

- [ ] **Step 2: Reroll spread (placer non-determinism policy)**

Per the timing-closure playbook (memory + `docs/` history: reroll spread then post-route phys_opt closed −0.091→0.000):

```bash
ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm/synth/scripts && nohup ./launch_reroll.sh build_034 AltSpreadLogic_medium Explore ExtraTimingOpt SSI_SpreadLogic_high > launch_reroll_034.out 2>&1 &'
```

(4 parallel jobs, ~3.5 h; synth reused.) Then `grep '^TIMING:' synth/out_build_034_rr_*/reroll.log`. Invoke the `fpga-timing-closure` skill if the best roll is < 0: census the failing paths, iterate — budget is the spec's top-ranked risk, do not silently accept negative WNS.

- [ ] **Step 3: Record + pick**

`evidence/qwen2b/rb/TIMING.md`: table of directive → WNS/WHS, the chosen roll, utilization delta from the chosen roll's `bd_wrapper_utilization_placed.rpt` (SLR1 BRAM expected ≈ 519.5 tiles / ~72%; compare vs the 70.21% baseline from Task 2), netlist hash. Report WNS before/after vs build_033's +0.009 baseline. Commit.

```bash
git add evidence/qwen2b/rb/TIMING.md synth/scripts/launch_build_034.out synth/scripts/launch_reroll_034.out
git commit -m "synth(R-b): build_034 + reroll spread — WNS <value>, SLR1 BRAM <value>%"
```

---

### Task 9: R-b HW gate — the 0.8B ladder must reproduce on the widened bitstream

**Files:**
- Create: `evidence/qwen2b/rb/RB_GATE.md` + logs/JSONs

**Interfaces:**
- Consumes: Task 8's chosen bitstream.
- Produces: the R-b exit gate; the board's resident bitstream becomes build_034_rr_<best>. Gate D convenes after this + Track Q Task 10.

- [ ] **Step 1: Reprogram (safe flow, exact order)**

```bash
cd /home/cah/r2d2/code/fpga/fable5_llm
sudo -n $PWD/sw/pcie_helper.sh remove
./sw/program_fpga.sh synth/out_build_034_rr_<best>/proj/stage1.runs/impl_1/bd_wrapper.bit
sudo -n $PWD/sw/pcie_helper.sh rescan
```

Verify VERSION CSR == build_034's commit hash and CALIB == 0xF (`docs/USAGE.md:62-73`) BEFORE any DMA.

- [ ] **Step 2: The ladder, in order (all commands run on snoke, `sw/` venv)**

```bash
cd /home/cah/r2d2/code/fpga/fable5_llm/sw
make seq_selftest && make serve_test                      # board-free sanity first
make seq_dry_run                                          # upload + readback, no SEQ CSRs
make seq_run  && make seq_run4                            # device ms/token vs build_033's 46.46 / 32.94
.venv/bin/python chat_seq.py --verify --ntok 8            # lockstep vs ref/seq_model, 0 mismatch
make chat4_canned                                         # B1 greedy regression (argmax vs expect_tokens)
.venv/bin/python chat_seq.py --nch 4 --temp 0.8 --seed 4242 --ntok 24   # x2, identical; then --seed 4243 differs
make tok_meter4                                           # sustained tok/s vs 30.4
```

Pass = every gate reproduces build_033's numbers (tokens bit-exact, tok/s within run-to-run noise). 4 seeds where seeded. The EMBLOG2 CSR stays at reset (11) throughout — this ladder is pure 0.8B.

- [ ] **Step 3: RB_GATE.md (house gate-doc format: provenance para, headline table, gates sim+HW, follow-ons) + commit + convene gate D**

```bash
git add evidence/qwen2b/rb/
git commit -m "evidence(R-b): HW gate — widened bitstream reproduces the full 0.8B ladder (30.4 tok/s, lockstep, sampled chat)"
```

Then: assemble the gate-D one-pager (this gate + Track Q's decision table) and STOP for the user's operating-point decision. The post-D plan (R-c/R-d ± W8 mode) is written after that.
