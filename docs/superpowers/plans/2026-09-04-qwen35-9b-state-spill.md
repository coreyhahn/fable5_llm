# Qwen3.5-9B state spill (DDR-resident layer state, URAM caches) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision 2 (2026-09-04):** the independent plan review (BIND AFTER FIXES: 8 blocking, 15 major) is folded in. Its four spec-level rulings are the spec's amendment A1; the rest are in the tasks below. The review's anchor table verified every cited site that survives here.

**Goal:** Move the 9B layer's DeltaNet state, KV cache and conv weights/state out of URAM/BRAM into DDR behind a single sequencer-scheduled DMA engine and small two-slot caches, so the layer fits one SLR and closes timing at 250 MHz — with tokens bit-identical to Task 11's replay.

**Architecture:** `layer_chan` keeps the compute units' memory ports and puts two-slot caches behind them (DN 2 × 29 URAM, KV 2 × 58 URAM, conv 2 × 4 URAM), each slot owned by exactly one lane at a time and reached by the DMA through ownership muxes on the existing ports (spec A1.2). A new `state_dma` block with a 512-bit AXI4 master on the layer's 250 MHz clock moves whole blocks between DDR and the slots; two new layer commands, SLD and SST, scheduled by the emitter, run on a second in-order lane with two hardware fences. The reference model mirrors the DDR image and the slots; the chip-level TB's DDR model gains a write path; the host plans a state region beside the weight pack.

**Tech Stack:** SystemVerilog (Verilator 5.020 `-Wall`, sims on snoke), Python (uv venv `ref/.venv`; numpy; the ref/ fixed-point models), Vivado 2024.2 on snoke (OOC synth/place through the existing harnesses), the campaign's evidence tooling (`evidence/qwen9b/run.sh`, `spec_cites.py`, `evidence/qwen9b/o3/o3_cite_drift.py`, the `evidence/qwen9b/g3/isa_bits.py` pattern).

**Spec:** `docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md` (APPROVED 2026-09-04; amendment A1 at 3989e0e), amending `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md`. Where this plan and the spec disagree, the spec wins; where the spec is silent, the migration spec is the authority.

**Where this plan sits in the campaign:** it inserts Tasks S1–S5 between the migration plan's Task 13 (closed, `evidence/qwen9b/g5/G5A_FLOORPLAN.md`) and its Task 14 (the full build), which then runs as written on S5's floorplan. Tasks 15–16 stand. The task loop for S1–S5 is logged in this plan's own ledger (`.superpowers/sdd/2026-09-04-qwen35-9b-state-spill/progress.md`); campaign-level entries stay in the migration plan's.

## Global Constraints

Copied from the migration plan's Global Constraints and the spec's §1; every one binds every task here.

- **NEVER read/grep/copy the pre-existing private implementation (the "answer key")**, its git history, or auto-memory entries about it.
- **Commit at every green gate, path-limited:** `git commit -m "…" -- <paths>`; message first, paths after `--`; a new file needs `git add <path>` first. **The pathspec names FILES**, except a directory that exactly one task in this plan writes: each task's own `evidence/qwen9b/s<N>/`. Shared trees (`rtl/`, `ref/`, `sw/`, `tb/`, `docs/`, `synth/`, every other `evidence/` directory) are never a directory pathspec. Before committing any file another task also names — this plan's overlaps are `tb/Makefile` (S2, S3), `ref/seq_format.py` and `sw/hwmap.py` (S1, S3) — run `git diff --stat <file>` and never commit another task's work. Never `--amend`.
- **Every gate produces a committed gate doc under `evidence/qwen9b/s<N>/`**, 4 seeds minimum on every TB run, and a commit. Logs through the provenance wrapper `bash evidence/qwen9b/run.sh <log-name> <cmd> [args...]` (host, date, tree sha + dirty flag, cmd, venv, rc); final logs say `tree: <sha>` clean unless the gate doc declares what was dirty. Never re-run a committed evidence script in place when a gate doc cites its log by line — new logs get new names.
- **Board safety:** the board stays serving the 2B on `build_035_fp2a_exc_po` until G6. Nothing in this plan touches it.
- **Machines:** heavy Verilator sims and every Vivado run on **snoke** (`ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm && …'`, detached for long runs, bounded polling); one `obj_dir_<name>` per testbench, never two hosts on one obj_dir; Verilator 5.020, `-Wall`; darthplagueis stays out of numeric compute. Snoke-side Python: `uv run --no-project --with torch --with transformers --with numpy python` where torch is needed; `ref/.venv/bin/python` is a dangling symlink on snoke.
- **The seed variables are the Makefile's own** — `LAYERV2_SEEDS` (`tb/Makefile:648`), `SEQ_SEEDS` (`tb/Makefile:799`), `V2SEEDS` (`tb/Makefile:81`), `SEQSEEDS` (`tb/Makefile:293`), `TOPK_SEEDS` (`tb/Makefile:523`), `W9_SEEDS` (`tb/Makefile:1311`, the 9B chip targets); `tb_layer_env` hardcodes `for s in 1 2 3 4` (`tb/Makefile:466`); a generic `SEEDS=` is read by nothing. Every command below names the variable its target reads, or relies on the default and says so.
- **Sweep with `/usr/bin/grep`** (the shell's `grep` is `ugrep` and honours `.gitignore`).
- **`evidence/qwen_next/spec_cites.py` gates every spec, plan and gate doc** this plan edits (run it LAST, on the committed tree); `evidence/qwen9b/o3/o3_cite_drift.py --plan` before any `--fix`, `--exclude` your own gate doc, `--verify` after; slash-joined citation lists are unparsed — write ranges.
- **Measured, not modelled; labels M/D/T/E/S** as the migration spec §0 defines them; every S names the gate that measures it.
- **The spec's invariants:** no arithmetic changes anywhere; one clock in custom RTL (`aclk`); `dn_step`'s FSM, the conv datapath and `attn_core`'s arithmetic are not edited; the acceptance bar is the token-identical replay of Task 11's stream set.
- **`ref/model_select.py` freezes `FABLE5_MODEL` at import**: one process is one geometry. The operating point is `FABLE5_MODEL=9b FABLE5_RS_F=7`; A2.5's rule — **CLOSED 2026-09-10 by #26** and now ENFORCED by the module rather than advised here (a disagreeing `FABLE5_RS_F` is refused by name; the announced rider is the one escape) — **said** never export `FABLE5_RS_F` across `ref/scripts/regen_gate.sh` or `evidence/qwen2b/rc/t4_bytes_unmoved.sh`, and that is still what to do.

### Standing hazards this plan inherits

- The layer's CSR write decoder (`rtl/layer_chan.sv:1066-1120`, `case (awaddr_q)`) and the STATUS read mux (`rtl/layer_chan.sv:1145`) address CSRs by **word** offset (`10'h008` = byte 0x20); the ISA doc and the host mirror address them by **byte**. Every new CSR is written in both units in both places, and S1's census ties them.  *(re-anchored 2026-09-04 by S3's Step 5' drift pass; S2 rewrote this file and `--fix` could not renumber a citation whose quotation the pass has to keep checking.)*
- `rtl/layer_chan.sv:915-918`: a CMD write is accepted only `if (!busy)` and is otherwise SILENTLY DROPPED; `rtl/layer_chan.sv:908` counts LCYC while `busy`. Spec A1.4 splits `busy_cmp` (the accept gate and LCYC's source) from `busy_any` (the STATUS bit) for exactly this reason.
- `tb/seq_mem_file.sv` is a **read-only** AXI4 slave (`araddr … rvalid`, ports from `tb/seq_mem_file.sv:83`; no AW/W/B). S3 adds the write path; until then any RTL store in a chip-level sim is undriven. `tb/tb_seq_chip.sv` instantiates it twice: at `DATA_W` 128 (`tb/tb_seq_chip.sv:303`, the sequencer's fetch path) and at `DATA_W` 512 per DDR channel (`tb/tb_seq_chip.sv:387`); the state window lives in the 512-bit instance of the channel the host planner chose.
- `ref/gen_layer_script.py:307-308` `_DN_SLOTS = 24`, `_KV_SLOTS = 8` size the model's banked state and are asserted at `ref/gen_layer_script.py:310-311`; `ref/gen_token_script.py:68` and `ref/gen_token_script.py:84` import both; `M.convw(...)` is called from `ref/gen_chain_script.py:108`, `ref/gen_layer_script.py:1705` (the `layerv2_s*` generator `tb_layer_chan` depends on), `ref/gen_token_script.py:198` and `ref/seq_chat.py:1424` (on the `sw/chat_seq.py --selftest` path). The emitter's `convw()` therefore stays callable: it models the load into the slot's weight memory and warms the slot; only the RTL refuses sel 0/1.  <!--cites:noquote-->
- `attn_core`'s T ceiling lives in four places, and S2 WIDENED all four together (spec A1.5): `cfg_t`/`kv_addr` (`rtl/attn_core.sv:37`, `rtl/attn_core.sv:45`), `sc_mem [4096]` and `es_mem [4096]` (`rtl/attn_core.sv:77-78`), `logic [12:0] t, T` (`rtl/attn_core.sv:112`, `T <= cfg_t` at `rtl/attn_core.sv:280`), and the header contract (`rtl/attn_core.sv:16`). Widening any subset is a silent wrap.  *(re-anchored 2026-09-04 by S3's Step 5' drift pass: the pre-S2 numbers named 512-deep memories and a 10-bit `t, T` that no longer exist, so the citations are moved AND their quotations re-read — the class-A repair `evidence/qwen9b/g3/G3_4_LAYER.md` §15.5 asks for when the successor really is the same thing.)*
- `docs/SEQ_ISA.md` has two sections numbered B14 (`docs/SEQ_ISA.md:959` the weight DDR pack, `docs/SEQ_ISA.md:1017` the 16-bit scratch addressing); the append point for B15 is after the second, at the file's end.
- The 2B/0.8B artifacts and their byte-locks are **not** regenerated by this plan: the new ISA is v2.1 and the frozen streams stay frozen (Task 7's ruling: no v1.7 emitter/decoder). `ref/scripts/regen_gate.sh` and the boardfree selftests must remain unmoved at **`BOARDFREE_PASS 2759/85/356`** — the count since G3.4 — **except that new selftests may move it UP** (controller ruling at S3's fix round: the pin catches a BROKEN frozen path, not added tests; S3 adds selftests; the triple a task quotes must be the one its COMMITTED boardfree log's last lines show on a clean tree, never a reported figure — the controller pinned S3's reported 2785/85/364 here before any log carried it, and that was wrong; the S3 fix round 2 measures it) (`evidence/qwen9b/g3/G3_4_LAYER.md` §15.6 and every later gate; `evidence/qwen9b/o3/BOARD_LOCK.md` records the pre-G3.4 2758/85/357). Run them through `evidence/qwen2b/rd/rd_boardfree.sh` (snoke's `python3` has no numpy; the wrapper knows the interpreter and includes `serve.py --selftest`).
- `synth/exp_uram/rtl/` is **not** refreshed: Task 13 re-pointed the experiment vehicle at the shipping `rtl/` (`synth/exp_uram/scripts/exp_ooc.tcl:75` `set Rtl "$RepoRoot/rtl"`) and reverted a refresh as UNSAFE for citation drift (`evidence/qwen9b/g5/G5A_FLOORPLAN.md:113-126`). S5 edits the harness's scripts, never the copy.

---

## File structure

| file | responsibility | task |
|---|---|---|
| `docs/SEQ_ISA.md` (new section B15, v2.1) | SLD/SST encodings, LAYER slot + kv_layer semantics, the five CSRs, every `err_code` | S1 |
| `ref/seq_format.py` | the CSR offsets, opcode names, the SLD/SST validate clause (in `validate_stream`), disasm, `on_layer` with four fields | S1 (constants, packers, validate, disasm) / S3 (`on_layer`, TCNT packing) |
| `sw/hwmap.py` | the CSR mirror, the state-region constants, `plan_state()` | S1 |
| `evidence/qwen9b/s1/sdma_bits.py` | the field/CSR/error census tying RTL ↔ ref ↔ host ↔ ISA doc, with perturbation controls; RED on the RTL half until S2 | S1 |
| `rtl/state_dma.sv` (new) | the 512-bit AXI4 R/W master, row assembly, one transfer at a time, the 256-beat FIFO, `E_DMA_AXI` | S2 |
| `rtl/layer_chan.sv` | the three two-slot caches with ownership muxes, the DMA lane + queue, F1/F2, the slot tags, `busy_cmp/busy_any`, `E_DMA_*`, the CSRs, the retired banks | S2 |
| `rtl/attn_core.sv` | 13-bit `cfg_t`/`kv_addr`/`t`/`T`, `sc_mem`/`es_mem` 4,096 deep | S2 |
| `rtl/layer_chan_ipi.v`, `synth/scripts/create_project.tcl` | the `m_axis` bundle; the third SmartConnect port and its 4 × 4 GiB address pinning | S2 |
| `tb/axi_ram_bfm.sv` (new), `tb/tb_layer_sdma.sv` (new), `tb/Makefile` | a RAM-backed AXI4 R/W slave; the directed RED-first DMA/fence/error TB with its own obj_dir; `lint_state_dma`; `LAYER_RTL` gains `rtl/state_dma.sv` | S2 |
| `ref/gen_layer_script.py`, `ref/gen_model_script.py`, `ref/gen_token_script.py`, `ref/gen_chain_script.py`, `ref/seq_chat.py`, `sw/infer.py` | the DDR image + slot model, `layer()` with four fields and its seven call sites, the `convw` shim, `sld()`/`sst()`, the schedule, the preamble, the conv-image seeding | S3 |
| `ref/seq_model.py`, `ref/seq_format.py` | SLD/SST execution against a state-region image; `--gate` compares it; `on_layer` four fields; TCNT 13-bit packing | S3 |
| `tb/seq_mem_file.sv`, `tb/tb_seq_chip.sv`, `tb/scripts/gen_seq_chip_vectors.py`, `tb/tb_layer_chan.sv`, `tb/Makefile` | the AXI4 write window; `SMEM` golden records; the layer family regenerated at v2.1; `tb_layer_dnbank` retired | S3 |
| `sw/hwmap.py`, `sw/seq_run.py`, `sw/chat_seq.py`, `sw/tok_meter.py` | the state plan in the manifest, base-CSR writes, audits, session memset, bytes/token | S3 |
| `evidence/qwen9b/s4/` | the 9B re-emission, chip replay, census, envelope | S4 |
| `synth/constraints/fable5_floorplan_9b_1slr.xdc` (new), `synth/exp_uram/scripts/exp_ooc.tcl`, `evidence/qwen9b/s5/` | OOC counts and the one-SLR placement on the re-pointed harness | S5 |

---

### Task S1: the ISA extension — encodings, reference, host mirror, and the census (RED against today's RTL)

The mechanisation comes first, as it did for G3.1 (`docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md`, Task 7 Step 1): the encodings are written down once, the reference and host copies derive from that text, and a census tool ties them to the RTL — failing RED until Task S2 lands the RTL half.

**Files:**
- Modify: `docs/SEQ_ISA.md` (append section B15 after the second B14, `docs/SEQ_ISA.md:1017-`; bump the header's version line to v2.1)
- Modify: `ref/seq_format.py:320-333` (CSR offsets), `ref/seq_format.py:729-730` (the opcode-name dict), `ref/seq_format.py:656-669` (`validate_stream`, where ARG0..2 are tracked — NOT `validate()` at `ref/seq_format.py:483`, which sees one record and no ARGs), `ref/seq_format.py:748` (disasm)
- Modify: `sw/hwmap.py:179-210` (the layer CSR mirror; `L_TCNT` is `sw/hwmap.py:179`, `L_TCNT2` `sw/hwmap.py:182`, `L_LAYER` `sw/hwmap.py:190`, `L_DNSB` `sw/hwmap.py:210`), a new `STATE_*` block and `plan_state()` beside `plan_weights` (`sw/hwmap.py:522`)  <!--cites:noquote-->
- Create: `evidence/qwen9b/s1/sdma_bits.py`, `evidence/qwen9b/s1/S1_ISA.md`
- Test: `evidence/qwen9b/s1/sdma_bits.py` (RED on `rtl/` today; `--ref-only` GREEN; `--perturb` CAUGHT), `sw/seq_run.py --selftest`, `sw/chat_seq.py --selftest` (boardfree, unmoved at 2759/85/356), `evidence/qwen9b/g3/isa_bits.py` (unmoved)

**Interfaces:**
- Consumes: the layer command opcode space (`rtl/layer_chan.sv:339-350`, 1..12 used), the LAYER CSR (`rtl/layer_chan.sv:25`, `sw/hwmap.py:190`, `ref/seq_format.py:321`), TCNT/TCNT2 (`sw/hwmap.py:179`, `sw/hwmap.py:182`).
- Produces, for S2/S3 (exact names):
  - `ref/seq_format.py`: `OP_L_SLD = 13`, `OP_L_SST = 14`; `LOFF_SB_DN = 0x64`, `LOFF_SB_KV = 0x68`, `LOFF_SB_CV = 0x6C`, `LOFF_SDMA = 0x70`, `LOFF_SDMA_CYC = 0x74`; `CSR_L_SB_DN`, `CSR_L_SB_KV`, `CSR_L_SB_CV`, `CSR_L_SDMA`, `CSR_L_SDMA_CYC`; `SDMA_KIND_DN, SDMA_KIND_KV, SDMA_KIND_CV = 0, 1, 2`; `sdma_arg0(kind, slot, layer, head) -> int`; `sdma_fields(arg0) -> (kind, slot, layer, head)`; `layer_word(dn_slot, kv_slot, cv_slot, kv_layer) -> int`; the error-code table `ERR_CODE = {0x01: "E_ENV", 0x02: "E_LAYER", 0x10: "E_DMA_BASE", 0x11: "E_DMA_RANGE", 0x12: "E_DMA_AXI", 0x13: "E_DMA_COLD"}`; `STATE_T_MAX = 4096`.
  - `sw/hwmap.py`: `L_SB_DN, L_SB_KV, L_SB_CV, L_SDMA, L_SDMA_CYC`; `STATE_DN_LAYER = 1 << 20` (a whole layer, 4,096 rows), `STATE_DN_HEAD = 1 << 15` (the layout unit), `STATE_KV_STRIDE = 1 << 21`, `STATE_CV_STRIDE = 1 << 17`, `STATE_KV_EXP_OFF = 1 << 20`, `STATE_DN_BLOCKS = 24 * 32`, `STATE_KV_BLOCKS = 8 * 4 * 2`, `STATE_CV_BLOCKS = 24`, `STATE_T_MAX = 4096`, `STATE_BASE_UNIT = 1 << 16`; `plan_state(base) -> dict(dn=, kv=, cv=, end=)` with every base 64 KiB aligned.
  - The LAYER CSR's new word is B15.2's; the RTL latches the full fields and refuses a slot value above 1 (`E_LAYER`).

- [ ] **Step 1: write B15 in `docs/SEQ_ISA.md`** — the contract, before any code

Append after the second B14 (`docs/SEQ_ISA.md:1017-`, the file's last section — the file has two sections numbered B14, `docs/SEQ_ISA.md:959` and `docs/SEQ_ISA.md:1017`; say so in B15's first line), and change the header's version line to `v2.1 (2026-09-04): layer state in DDR — SLD/SST, cache slots, SB_*/SDMA CSRs`. The section text:  <!--cites:noquote-->

```markdown
## B15. Layer state in DDR — the v2.1 extension (2026-09-04)

Spec: docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md §5 and A1.
(This file carries two sections numbered B14; B15 follows the second.)

### B15.1 Two new layer commands

  op 13 SLD   arg0={kind[12:11], slot[10], layer[9:5], head[4:0]}  arg1=0  arg2=0
  op 14 SST   the same fields
  kind: 0 DN, 1 KV, 2 CV, 3 reserved (refused, E_DMA_RANGE)
  slot: 0/1 (the cache slot of that kind)
  layer: DN/CV 0..23; KV 0..7 (the attention layer index)
  head:  DN must be 0 (a DN transfer moves the WHOLE layer, spec A1.1);
         KV {kvhead[2:1], kv[0]} (kv 0=K 1=V); CV must be 0
  arg1/arg2 must be 0 (refused otherwise, E_DMA_RANGE) — reserved for a row range.

  DDR address = SB_<kind> << 16  +  (index << shift)
     DN: index = layer                   shift 20  (1 MiB = 32 heads x 128 rows x 256 B,
                                                    laid out head-major: head h at +h<<15)
     KV: index = (layer*4 + kvhead)*2 + kv   shift 21  (2 MiB blocks; exponent side array at +1 MiB)
     CV: index = layer                   shift 17  (128 KiB blocks, rows padded to 16 B:
                                                    [63:0] weights, [111:64] state, [127:112] 0)
  Length: DN 4096 rows x 256 B; CV 8192 rows x 16 B; KV TCNT[layer][kvhead] rows x 256 B
          + TCNT exponent bytes (rounded up to 64 B), TCNT read at dispatch.
          A KV SLD with TCNT = 0 moves nothing, warms the slot and sets its tag.

### B15.2 The LAYER CSR (0x30) selects CACHE SLOTS and the attention layer
  {18'b0, cv_slot[13:12], 1'b0, kv_layer[10:8], 3'b0, kv_slot[4:3], 1'b0, dn_slot[1:0]}
  dn_slot / kv_slot / cv_slot: 0 or 1 (2-bit fields; a value above 1 is refused at the
  next compute command, E_LAYER).  kv_layer: 0..7, the attention layer whose TCNT/TCNT2
  CSRs the host or program reads and writes.  Each KV slot carries a hardware TAG
  {layer[2:0], kvhead[1:0]} latched by the SLD that filled it; KVAP and ATTN index the
  append counters through the tag of the slot kv_slot names, and refuse (E_DMA_RANGE)
  when the command's own kvhead field differs from the tag's.

### B15.3 New CSRs (byte offsets; the RTL decodes word offsets 0x19..0x1D)
  0x64 SB_DN     RW  DN region base >> 16   (18 bits used)
  0x68 SB_KV     RW  KV region base >> 16
  0x6C SB_CV     RW  conv region base >> 16
  0x70 SDMA      RW  R: {busy_dma[31], queued[30:28], last_kind[27:26], last_slot[25], 17'b0, err[7:0]}
                     W: any write clears err (and err_op if it was set by E_DMA_AXI)
  0x74 SDMA_CYC  R   cycles while busy_dma; ANY write clears it (LCYC's twin for the DMA lane)
  STATUS (0x04) bit 0 is busy_any = busy_cmp | busy_dma; the CMD accept gate is busy_cmp
  alone; cmd_cnt increments when an SLD/SST is ENQUEUED; LCYC counts busy_cmp cycles only.

### B15.4 Error codes — STATUS.err_op set; SDMA.err carries the code
  (a different namespace from seq_unit's err_code: these are the LAYER's)
  0x01 E_ENV        a compute command's field envelope refused (the S9 checks, rtl/layer_chan.sv cmd_env_bad)
  0x02 E_LAYER      a LAYER slot field above 1 at a compute command's dispatch
  0x10 E_DMA_BASE   SB_<kind> is 0 at dispatch of an SLD/SST
  0x11 E_DMA_RANGE  kind 3; layer/head outside the kind's range; DN or CV head != 0; arg1/arg2 != 0;
                    a KV TCNT above 4096; a KVAP/ATTN kvhead that differs from the slot's tag
  0x12 E_DMA_AXI    any SLVERR/DECERR on the transfer — raised at completion, STICKY with err_op
                    until the host writes SDMA (the next compute dispatch does NOT clear it)
  0x13 E_DMA_COLD   a compute command names a slot with no completed load (or DNZ/CONVZ)
                    since the slot's last SST, or since reset

### B15.5 Ordering
  SLD/SST run on the DMA lane, in program order among themselves, one transfer in
  flight. F1: a compute command whose slot has an SLD queued or in flight waits.
  F2: an SLD/SST on a slot waits while a compute command holds it; an SLD waits
  for every earlier SST on the same slot. A transfer on one slot of a kind may be in
  flight while a compute command holds the OTHER slot of that kind.
  DNZ zeroes head rows in the LAYER-selected DN slot and warms it; CONVW sel 2
  zeroes the state words of the LAYER-selected CV slot and warms it; CONVW sel 0/1
  are refused by the RTL (E_DMA_RANGE) — conv blocks arrive by SLD.
```

- [ ] **Step 2: the reference constants and packers in `ref/seq_format.py`**  <!--cites:noquote-->

After `LOFF_DNSB = 0x5C` (`ref/seq_format.py:324`) add:  <!--cites:noquote-->

```python
# v2.1 (B15): layer state in DDR
LOFF_SB_DN, LOFF_SB_KV, LOFF_SB_CV, LOFF_SDMA, LOFF_SDMA_CYC = 0x64, 0x68, 0x6C, 0x70, 0x74
CSR_L_SB_DN, CSR_L_SB_KV = csr_layer(LOFF_SB_DN), csr_layer(LOFF_SB_KV)
CSR_L_SB_CV, CSR_L_SDMA, CSR_L_SDMA_CYC = csr_layer(LOFF_SB_CV), csr_layer(LOFF_SDMA), csr_layer(LOFF_SDMA_CYC)
OP_L_SLD, OP_L_SST = 13, 14
SDMA_KIND_DN, SDMA_KIND_KV, SDMA_KIND_CV = 0, 1, 2
ERR_CODE = {0x01: "E_ENV", 0x02: "E_LAYER", 0x10: "E_DMA_BASE", 0x11: "E_DMA_RANGE",
            0x12: "E_DMA_AXI", 0x13: "E_DMA_COLD"}
E_ENV, E_LAYER, E_DMA_BASE, E_DMA_RANGE, E_DMA_AXI, E_DMA_COLD = 0x01, 0x02, 0x10, 0x11, 0x12, 0x13
STATE_T_MAX = 4096

def sdma_arg0(kind, slot, layer, head):
    """B15.1: {kind[12:11], slot[10], layer[9:5], head[4:0]}."""
    assert kind in (SDMA_KIND_DN, SDMA_KIND_KV, SDMA_KIND_CV), kind
    assert slot in (0, 1), slot
    lmax = 7 if kind == SDMA_KIND_KV else 23
    assert 0 <= layer <= lmax, (kind, layer)
    hmax = {SDMA_KIND_DN: 0, SDMA_KIND_KV: 7, SDMA_KIND_CV: 0}[kind]
    assert 0 <= head <= hmax, (kind, head)
    return (kind << 11) | (slot << 10) | (layer << 5) | head

def sdma_fields(arg0):
    return (arg0 >> 11) & 3, (arg0 >> 10) & 1, (arg0 >> 5) & 31, arg0 & 31

def layer_word(dn_slot, kv_slot, cv_slot, kv_layer):
    """B15.2: {cv_slot[13:12], kv_layer[10:8], kv_slot[4:3], dn_slot[1:0]}."""
    assert dn_slot in (0, 1) and kv_slot in (0, 1) and cv_slot in (0, 1) and 0 <= kv_layer <= 7
    return (cv_slot << 12) | (kv_layer << 8) | (kv_slot << 3) | dn_slot
```

Extend the opcode-name dict (`ref/seq_format.py:729-730`) with `13: "SLD", 14: "SST"`. The validate clause goes in **`validate_stream()`** (`ref/seq_format.py:656-669`), which tracks the ARG0..2 CSR writes ahead of each CMD record — `validate()` at `ref/seq_format.py:483` sees one record and has no ARGs. In the same form the MVGO envelope clause uses (`SeqValidationError`, the record index in the message):  <!--cites:noquote-->

```python
        if op in (OP_L_SLD, OP_L_SST):
            kind, slot, layer, head = sdma_fields(a0)
            name = "SLD" if op == OP_L_SLD else "SST"
            if kind == 3:
                raise SeqValidationError(f"rec {idx}: {name} kind 3 is reserved (B15.1)")
            lmax = 7 if kind == SDMA_KIND_KV else 23
            hmax = {SDMA_KIND_DN: 0, SDMA_KIND_KV: 7, SDMA_KIND_CV: 0}[kind]
            if layer > lmax or head > hmax:
                raise SeqValidationError(
                    f"rec {idx}: {name} layer {layer}/head {head} outside kind {kind}'s range (B15.1)")
            if a1 != 0 or a2 != 0:
                raise SeqValidationError(f"rec {idx}: {name} arg1/arg2 must be 0 (B15.1 reserved)")
```
The clause is unconditional (v2.1 streams are the only kind this tree's RTL decodes; the frozen isa=1 artifacts carry no op 13/14 — say so in the comment as the MVGO clause's comment does). `disasm()` (`ref/seq_format.py:748`) prints `SLD k=DN slot=0 L=3` style text using `sdma_fields`.  <!--cites:noquote-->

- [ ] **Step 3: the host mirror in `sw/hwmap.py`**  <!--cites:noquote-->

After `L_DNSB` (`sw/hwmap.py:210`), in the block's own comment style:  <!--cites:noquote-->

```python
L_SB_DN    = LB + 0x64    # RW DN state region base >> 16   (B15.3)
L_SB_KV    = LB + 0x68    # RW KV region base >> 16
L_SB_CV    = LB + 0x6C    # RW conv region base >> 16
L_SDMA     = LB + 0x70    # RW R: {busy_dma, queued[2:0], last_kind[1:0], last_slot, err[7:0]}; W clears err
L_SDMA_CYC = LB + 0x74    # R  busy_dma cycles; any write clears

STATE_BASE_UNIT   = 1 << 16
STATE_DN_LAYER    = 1 << 20          # one DN transfer: 32 heads x 128 rows x 256 B (spec A1.1)
STATE_DN_HEAD     = 1 << 15          # the layout unit inside a layer block
STATE_KV_STRIDE   = 1 << 21          # 2 MiB per (layer, kvhead, K|V)
STATE_KV_EXP_OFF  = 1 << 20          # exponent side array inside the block
STATE_CV_STRIDE   = 1 << 17          # 8192 rows x 16 B
STATE_DN_BLOCKS, STATE_KV_BLOCKS, STATE_CV_BLOCKS = 24 * 32, 8 * 4 * 2, 24
STATE_T_MAX       = 4096

def plan_state(base):
    """Lay the three regions out from `base` (64 KiB aligned), B15.1 order."""
    assert base % STATE_BASE_UNIT == 0, hex(base)
    dn = base
    kv = dn + STATE_DN_BLOCKS * STATE_DN_HEAD             # 24 MiB
    cv = kv + STATE_KV_BLOCKS * STATE_KV_STRIDE           # 128 MiB
    end = cv + STATE_CV_BLOCKS * STATE_CV_STRIDE          # 3 MiB
    for a in (dn, kv, cv):
        assert a % STATE_BASE_UNIT == 0
    return dict(dn=dn, kv=kv, cv=cv, end=end)
```

- [ ] **Step 4: the census tool `evidence/qwen9b/s1/sdma_bits.py`, RED against today's RTL**

Model it on `evidence/qwen9b/g3/isa_bits.py` (`grab()` at `evidence/qwen9b/g3/isa_bits.py:223`, `load_rtl_fields()` at `evidence/qwen9b/g3/isa_bits.py:237`, `_apply_perturbation()` at `evidence/qwen9b/g3/isa_bits.py:284`, `negative_control()` at `evidence/qwen9b/g3/isa_bits.py:936`). It must:  <!--cites:noquote-->
1. parse from `rtl/layer_chan.sv` the localparams `OP_SLD`, `OP_SST`, the five CSR word offsets (`10'h019..10'h01D`), every `err_code` value (0x01, 0x02, 0x10..0x13) and the ARG0 field slices `{kind[12:11], slot[10], layer[9:5], head[4:0]}` from the header comment — each line carrying a `// SDMA_BITS:` marker, so a missing symbol is a `SystemExit` naming it;
2. import `ref.seq_format` and `sw.hwmap` and require equality of every constant (opcodes, byte offset == 4 × word offset, error codes, strides, T_MAX, the LAYER bit homes);
3. parse `docs/SEQ_ISA.md` B15 and require its numbers match too;
4. round-trip 64 random `(kind, slot, layer, head)` through `sdma_arg0` → `sdma_fields`, round-trip `layer_word`, and refuse the RED cases through `validate_stream()` — kind 3; **DN head 1** (encodable, and must be refused since DN head must be 0 — "DN head 32" is not encodable in a 5-bit field and would be a tautology); KV layer 8; CV head 1; arg1 ≠ 0;
5. `--perturb rtl|ref|host|doc` flips one constant in an in-memory copy and must be CAUGHT;
6. `--ref-only` skips the RTL half (S1 is GREEN on ref/host/doc; the RTL half is RED until S2).

Run (repo root; darthplagueis is fine — no numerics):

```
bash evidence/qwen9b/run.sh evidence/qwen9b/s1/001_sdma_bits_red.log python3 evidence/qwen9b/s1/sdma_bits.py
```
Expected: `SDMA_BITS: FAIL — rtl/layer_chan.sv has no OP_SLD` (RED, the RTL half), rc 1 — commit that log as the RED record.
```
bash evidence/qwen9b/run.sh evidence/qwen9b/s1/002_sdma_bits_refonly.log python3 evidence/qwen9b/s1/sdma_bits.py --ref-only
```
Expected: `SDMA_BITS(ref-only): PASS`, and `--ref-only --perturb ref` → `CAUGHT`.

- [ ] **Step 5: the boardfree gates are unmoved**

```
ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm && bash evidence/qwen9b/run.sh evidence/qwen9b/s1/003_boardfree.log sh evidence/qwen2b/rd/rd_boardfree.sh'
bash evidence/qwen9b/run.sh evidence/qwen9b/s1/004_isa_bits_g3.log python3 evidence/qwen9b/g3/isa_bits.py
```
Expected: `BOARDFREE_PASS 2759/85/356` and `ISA_BITS: PASS` — the frozen streams carry no SLD/SST and the v2.0 checks still hold.

- [ ] **Step 6: gate doc + commit**

`evidence/qwen9b/s1/S1_ISA.md`: the B15 text as landed (quoted by line), the constant table with the three sources beside each value, the RED/GREEN/CAUGHT logs, the boardfree counts, `spec_cites` on the doc and on `docs/SEQ_ISA.md` LAST.

```bash
git add docs/SEQ_ISA.md ref/seq_format.py sw/hwmap.py evidence/qwen9b/s1
git commit -m "isa(S1): SEQ ISA v2.1 B15 — SLD/SST, cache-slot + kv_layer LAYER word, SB_*/SDMA/SDMA_CYC CSRs, the layer err_code table; reference + host mirrors; sdma_bits census RED on the RTL half, GREEN ref-only with controls" \
  -- docs/SEQ_ISA.md ref/seq_format.py sw/hwmap.py evidence/qwen9b/s1
```

---

### Task S2: the RTL — `state_dma`, the caches, the two lanes, the fences; the unit TB RED first

S2's green gate is self-contained: `tb_layer_sdma` drives the layer from the TB with no generated stream, plus the lints and the TBs that do not depend on the emitter. The layer family that regenerates its vectors through `ref/gen_layer_script.py` (`tb_layer_chan`, `tb_layer_env`) is re-run at **S3**, after the emitter learns the schedule — a task reviewer can approve S2's RTL without S3's emitter, and reject S3's chain without touching S2.

**Files:**
- Create: `rtl/state_dma.sv`, `tb/axi_ram_bfm.sv`, `tb/tb_layer_sdma.sv`
- Modify: `rtl/layer_chan.sv` — header CSR map (`rtl/layer_chan.sv:12-53`), opcode localparams (`rtl/layer_chan.sv:339-350`), the DN banks and `DN_PIPE` (`rtl/layer_chan.sv:195-214`, `rtl/layer_chan.sv:507-590`, `g_dnpipe0`/`g_dnpipeN` at `rtl/layer_chan.sv:569-655`), the KV banks (`rtl/layer_chan.sv:684-727`), the conv banks (`rtl/layer_chan.sv:729-777`), the envelope check `cmd_env_bad` (`rtl/layer_chan.sv:1129-1150`), the CSR write decoder (`rtl/layer_chan.sv:914-950`), the STATUS mux (`rtl/layer_chan.sv:974`) and the busy/LCYC logic (`rtl/layer_chan.sv:908`, `rtl/layer_chan.sv:915-918`), the dispatcher (`rtl/layer_chan.sv:1193-1300`), the KVAP write (`rtl/layer_chan.sv:1655-1672`; `tcnt_bank` widths at `rtl/layer_chan.sv:367`; the TCNT read-back at `rtl/layer_chan.sv:988-996`; the counter increment `tcnt_inc` at `rtl/layer_chan.sv:966-968` — the sixth TCNT site; ATTN's `at_cfg_t` at `rtl/layer_chan.sv:1288`), the conv read/write sites (`rtl/layer_chan.sv:1533-1596`, the `dn_layer_r` selects at `rtl/layer_chan.sv:765-766` and `rtl/layer_chan.sv:775-776`)
- Modify: `rtl/attn_core.sv:13` (the `T <= 512` contract), `rtl/attn_core.sv:29`, `rtl/attn_core.sv:37` (`cfg_t`, `kv_addr` to 13 bits), `rtl/attn_core.sv:69-70` (`sc_mem`, `es_mem` to 4,096), `rtl/attn_core.sv:104` (`t, T` to 13 bits), `rtl/attn_core.sv:272` and every other `t`/`T` compare
- Modify: `rtl/layer_chan_ipi.v` (the `m_axis` bundle after the `s_axib` bundle, `rtl/layer_chan_ipi.v:62-119`; the constant ties), `synth/scripts/create_project.tcl:223` (`NUM_SI {3}`), after `synth/scripts/create_project.tcl:281` (connect `layer_0/m_axis` → `axi_smc/S02_AXI`), and the address map: pin `layer_0/m_axis` to the four 4 GiB DDR segments exactly as `seq_0/m_axi` is pinned at `synth/scripts/create_project.tcl:449-456` (pattern; `mvchan_$i/m_axi` at `synth/scripts/create_project.tcl:411-416`)
- Modify: `ref/gen_layer_script.py:307-311` (`_DN_SLOTS = _KV_SLOTS = _CV_SLOTS = 2`, the assert), `ref/gen_layer_script.py:640-647` (`layer()` gains `cv_slot`, `kv_layer` and prints `layer_word`), the `convw` shim (`ref/gen_layer_script.py:1018`): the model still loads the slot's weights and warms it (only the RTL refuses sel 0/1) — this is the minimum so every existing generator keeps running; the schedule and `sld()/sst()` are S3's  <!--cites:noquote-->
- Modify: `tb/Makefile` (targets `tb_layer_sdma` with `obj_dir_tb_layersdma`, `tb_layer_sdma_nofence` (the same TB built with `-G SDMA_NOFENCE=1`, its own `obj_dir_tb_layersdma_nf`), `lint_state_dma`, and a real `lint_layer_chan` (`verilator --lint-only -Wall --timing` over `$(LAYER_RTL)`) — the existing `lint` target at `tb/Makefile:27-28` lints only `rtl/csr_block.sv`; `LAYER_RTL` gains `rtl/state_dma.sv` — it is used at `tb/Makefile:451`, `tb/Makefile:465`, `tb/Makefile:475`, `tb/Makefile:493`)
- Test: `tb_layer_sdma` (new, 4 seeds via its own `SDMA_SEEDS`) and its `nofence` RED build, `tb_dn_step`, `tb_gate_unit`, `tb_conv4_silu`, `tb_seq`, `tb_seq_guard` (the seed variables they read), `lint_layer_chan` (new), `lint_state_dma`, `lint_seq_unit`, `evidence/qwen9b/s1/sdma_bits.py` (now GREEN)

**Interfaces:**
- Consumes S1's names — every value copied from B15, never re-derived.
- Produces for S3/S4: the `m_axis` port names below; the `SDMA`/`SDMA_CYC` bit layouts as B15.3; `tcnt_bank [8][4]` of 13 bits indexed by the slot tag; `attn_core` `cfg_t[12:0]`; the DDR row formats of B15.1; the `-G SDMA_NOFENCE=1` build knob (F1 bypass, TB only; the default 0 is what ships).

`rtl/state_dma.sv` ports (the whole interface; the implementation is an issue FSM that walks a transfer as 1 KiB INC bursts through a 256-beat FIFO, and a data path that assembles/splits rows):  <!--cites:noquote-->

```systemverilog
module state_dma #(
    parameter int MAX_OUT = 8,             // bursts in flight
    parameter int FIFO_D  = 256            // beats, like ddr_rd_streamer
) (
    input  wire         aclk,
    input  wire         aresetn,
    // one transfer at a time, from layer_chan's DMA lane
    input  wire         xfer_go,           // pulse; fields sampled with it
    input  wire         xfer_store,        // 0 = SLD (DDR -> slot), 1 = SST (slot -> DDR)
    input  wire [1:0]   xfer_kind,         // 0 DN, 1 KV, 2 CV
    input  wire [33:0]  xfer_addr,         // block base, computed by layer_chan
    input  wire [13:0]  xfer_rows,         // rows to move: DN 4096, CV 8192, KV TCNT (0..4096)
    output logic        xfer_busy,
    output logic        xfer_done,         // one-cycle pulse, after the last B response on a store
    output logic        xfer_err,          // SLVERR/DECERR seen (E_DMA_AXI); sticky until the next xfer_go
    // the slot side (layer_chan muxes the owning slot's ports behind these)
    output logic [12:0] slot_addr,         // row index within the slot
    output logic [2047:0] slot_wdata,      // DN/KV row; CV: {16'b0, state[47:0], weights[63:0]} in [127:0]
    output logic [7:0]  slot_wexp,         // KV exponent byte for slot_addr (side-array phase)
    output logic        slot_we,
    output logic        slot_wexp_we,
    input  wire [2047:0] slot_rdata,       // valid 2 cycles after slot_addr (the URAM's registered read)
    input  wire [7:0]   slot_rexp,
    // AXI4 master, 512-bit; size/burst/id are tied constant in layer_chan_ipi.v
    output logic [33:0] m_axis_awaddr, output logic [7:0] m_axis_awlen, output logic m_axis_awvalid, input wire m_axis_awready,
    output logic [511:0] m_axis_wdata,  output logic [63:0] m_axis_wstrb, output logic m_axis_wlast, output logic m_axis_wvalid, input wire m_axis_wready,
    input  wire [1:0]   m_axis_bresp,   input  wire m_axis_bvalid, output logic m_axis_bready,
    output logic [33:0] m_axis_araddr, output logic [7:0] m_axis_arlen, output logic m_axis_arvalid, input wire m_axis_arready,
    input  wire [511:0] m_axis_rdata,  input  wire [1:0] m_axis_rresp, input wire m_axis_rlast, input wire m_axis_rvalid, output logic m_axis_rready
);
```
A KV transfer is two phases: `rows × 4` beats of row data, then `ceil(rows / 64)` beats of exponent bytes at `xfer_addr + STATE_KV_EXP_OFF` (`rows = 0` skips both and completes at once). A CV transfer packs four 16-B rows per beat; `layer_chan` splits `slot_wdata[127:0]` into the slot's weight memory (`[63:0]`) and state memory (`[111:64]`) — the two memories stay separate (spec A1.2).

`rtl/layer_chan.sv` additions, by site:  <!--cites:noquote-->
- Header (`rtl/layer_chan.sv:12-53`): the five CSR lines, the LAYER word, and the `err_code` table from B15, verbatim, each localparam line later marked `// SDMA_BITS:`.
- Localparams after `OP_DNZ` (`rtl/layer_chan.sv:350`): `OP_SLD = 4'd13`, `OP_SST = 4'd14`; `E_ENV = 8'h01 … E_DMA_COLD = 8'h13`; `SB_DN_W = 10'h019 … SDMA_CYC_W = 10'h01D`; and, so the census ties what S2 hardcodes into the address adder and the LAYER decode: `SDMA_SHIFT_DN = 20`, `SDMA_SHIFT_KV = 21`, `SDMA_SHIFT_CV = 17` (each `// SDMA_BITS: SHIFT_*`) and a `// SDMA_BITS: LAYER_FIELDS {cv_slot[13:12], kv_layer[10:8], kv_slot[4:3], dn_slot[1:0]}` marker on the LAYER decode — the marker forms S1's fix round adds to `evidence/qwen9b/s1/sdma_bits.py`'s contract block.  <!--cites:noquote-->
- **Caches with ownership muxes (spec A1.2).** Replace `g_dnpipe0/g_dnpipeN` and the `g_dn` bank array with `g_dnslot[2]` — each `(* ram_style = "ultra" *) logic [2047:0] mem [4096]`, addressed `{head[4:0], row[6:0]}`; replace `g_kv[8]` with `g_kvslot[2]` (`mem [8192]` + `emem [8192]`, addressed `{kv, t[11:0]}`); replace `g_cv[24]` with `g_cvslot[2]`, each keeping the two memories `wm [8192]` (64 b) and `sm [8192]` (48 b) so `CV_P`'s and `CZ_W`'s state-only writes (`rtl/layer_chan.sv:1555-1557`, `rtl/layer_chan.sv:1592-1596`) and `CW_P`'s (`rtl/layer_chan.sv:1566-1590`) stay as they are. Every slot's read address, write address, write data and write enable go through a 2:1 mux selected by `owner[kind][slot]` (compute or DMA); the compute side of each mux is exactly today's signal (`dn_ra_f`/`dn_wa_f`/`dn_wd` at `rtl/layer_chan.sv:580-583`, `kv_ra_f`/`kv_wa_f`/`kv_wrow` at `rtl/layer_chan.sv:714-721`, `cw_ra`/`cs_ra`/`cw_wa`/`cs_wa` at `rtl/layer_chan.sv:759-766`). The DN read return keeps its OREG (`rtl/layer_chan.sv:586`), so `dn_step` sees `RLAT = 2` — instantiate it `.RLAT(2), .P2_WAIT(0)` (the legal pair at latency 2, `rtl/dn_step.sv:41-43`; the FSM is unchanged). `DN_PIPE`, `DN_RLAT`, `DN_P2WAIT`, `DN_SDEL`, `DN_BPG`, `dn_layer_r`'s bank role and `N_DN`'s bank role are deleted; the conv slot select `cv_slot_r` (1 bit, from LAYER) replaces `dn_layer_r` at `rtl/layer_chan.sv:765-766` and `rtl/layer_chan.sv:775-776`.  <!--cites:noquote-->
- **Slot state.** Per kind, per slot: `warm`, `owner`, `dma_pending`; per KV slot a tag `{layer[2:0], kvhead[1:0]}` written by the SLD that fills it (spec A1.3). The DMA lane: a 4-entry queue of `{store, kind, slot, layer, head}` written at dispatch of OP_SLD/OP_SST; a small FSM pops it, checks F2, computes `xfer_addr = {sb[kind], 16'b0} + (index << shift)` and `xfer_rows` (KV: `tcnt_bank[layer][kvhead]`), pulses `xfer_go`, waits `xfer_done`, then sets `warm` (load) or clears it (store) and the tag.
- **Dispatcher** (`IDLE: if (cmd_go)`, `rtl/layer_chan.sv:1193`): before the existing `case (cmd_op)`, (a) the DMA-lane branch — `OP_SLD/OP_SST` enqueue (refusing on `E_DMA_BASE`/`E_DMA_RANGE`, incrementing `cmd_cnt`, and NOT setting `busy_cmp`); (b) the LAYER field check (`E_LAYER`); (c) F1 for compute commands (`OP_DNST/OP_DNZ` use the DN slot, `OP_KVAP/OP_ATTN` the KV slot with the tag check, `OP_CONV/OP_CONVW` the CV slot): stall while `dma_pending[slot]`, refuse `E_DMA_COLD` when `!warm[slot]`, set `owner` to compute for the command's duration and release it with `busy_cmp`.  <!--cites:noquote-->
- **busy and LCYC (spec A1.4).** Rename today's `busy` to `busy_cmp` at the accept gate (`rtl/layer_chan.sv:915-918`) and at LCYC (`rtl/layer_chan.sv:908`); `busy_any = busy_cmp | busy_dma` in the STATUS word (`rtl/layer_chan.sv:974`); `sdma_cyc` counts `busy_dma`.  <!--cites:noquote-->
- **CSRs.** Write decoder cases `10'h019..10'h01B` → `sb_dn/sb_kv/sb_cv` (18 bits), `10'h01C` → clear `sdma_err` (and `err_op` if it was set by `E_DMA_AXI`), `10'h01D` → clear `sdma_cyc`; STATUS mux `10'h01C` → the SDMA word, `10'h01D` → `sdma_cyc`; `10'h00C` LAYER latches `dn_slot[1:0]`, `kv_slot[4:3]`, `kv_layer[10:8]`, `cv_slot[13:12]` (`rtl/layer_chan.sv:944-947` today latches `[LDB-1:0]` and `[8 +: KVB]`); TCNT/TCNT2 CSR writes and reads index `tcnt_bank[kv_layer]` (today `tcnt_bank[layer_kv]` at `rtl/layer_chan.sv:929-932`, `rtl/layer_chan.sv:940-941`, `rtl/layer_chan.sv:988-996`); `at_cfg_t` (`rtl/layer_chan.sv:1288`), the KVAP address (`rtl/layer_chan.sv:1662-1672`) and the `tcnt_inc` increment (`rtl/layer_chan.sv:966-968`) index `tcnt_bank[tag.layer][tag.kvhead]` of the slot `kv_slot` names.  <!--cites:noquote-->
- `tcnt_bank` (`rtl/layer_chan.sv:367`) `[9:0]` → `[12:0]`; the KVAP write address `{kvhead_r, rnd, tcnt[8:0]}` (`rtl/layer_chan.sv:1662-1663`) → `{rnd, tcnt[11:0]}` into the slot; TCNT/TCNT2 CSR fields to 13 bits (`{3'b0, T1[12:0], 3'b0, T0[12:0]}`, B15 states the packing; S3 changes the host and reference packers).  <!--cites:noquote-->
- `cmd_env_bad` (`rtl/layer_chan.sv:1129-1150`): the `layer_dn > N_DN-1` term is dead with a 1-bit slot; it becomes the `E_LAYER` check (any slot field > 1) and keeps the CONV/CONVW envelope terms, now reporting `E_ENV`.  <!--cites:noquote-->
- `err_op` (`rtl/layer_chan.sv:14`, cleared at every dispatch at `rtl/layer_chan.sv:1197`): stays the single STATUS bit; `err_code[7:0]` is set with every refusal and reported in `SDMA.err`; the clear at dispatch is suppressed while `sdma_err == E_DMA_AXI` (spec A1.4).  <!--cites:noquote-->

- [ ] **Step 1: `tb/axi_ram_bfm.sv` and `tb/tb_layer_sdma.sv`, RED against today's `layer_chan`**

The BFM is a 512-bit AXI4 slave over `logic [511:0] mem [DEPTH]` with random `awready/arready/rvalid` gaps from `+seed`, INC bursts to 16 beats, and a `+err_at=<addr>` plusarg that returns SLVERR on one burst (the `E_DMA_AXI` test). The TB instantiates `layer_chan` + the BFM, copies `tb/tb_layer_chan.sv`'s `wr32`/`rd32`/`dcmd` tasks (`tb/tb_layer_chan.sv:118`, `tb/tb_layer_chan.sv:130`, `tb/tb_layer_chan.sv:194` — the TB families never share a file), and runs, per seed, these directed cases with `$fatal(1, …)` on any miss and a `TB_LAYER_SDMA PASS: <n> checks` marker:  <!--cites:noquote-->

1. `dn_roundtrip`: fill DDR layer block 3 (32 heads) with a seeded pattern → `SB_DN` CSR → SLD DN slot 0 L3 → wait `SDMA.busy_dma == 0` → SST from slot 0 → compare the BFM's 1 MiB block byte for byte; then a DNST on slot 0 head 17 and compare its output against the same DNST run on the committed `tb_layer_chan` DNST vectors under `tb/vectors/`.
2. `kv_roundtrip` at T ∈ {**0**, 1, 1023, 4096}: LAYER `kv_layer` = A, write TCNT/TCNT2, SLD K and V into slot 1 (tag A, kvhead h), SST both, compare rows AND the exponent side array; at T = 0 confirm the slot is warm and tagged with nothing moved (`SDMA_CYC` small, no AXI transaction on the BFM).
3. `cv_roundtrip`: the 16-B rows through the two memories.
4. `f1_stall`: issue SLD then immediately DNST on the same slot; assert the DNST's `busy_cmp` rises only after `busy_dma` falls, and its result equals case 1's. **Its negative control is a second build with `-G SDMA_NOFENCE=1`** (a TB-only knob that bypasses F1): the same sequence must then read stale data and FAIL the compare — the RED that proves the fence (spec §8.2).
5. `f1_cold`: DNST on slot 1 with no SLD → `STATUS.err_op` and `SDMA.err == 0x13`, and `cmd_cnt` unchanged (refused before the doorbell).
6. `f2_hold`: DNST on slot 0 (long) then SLD into slot 0 → `u_dma.xfer_go` observed only after the DNST's `busy_cmp` falls.
7. `f2_order`: SST slot 0 then SLD slot 0 → the BFM sees the writes complete before the first read address.
8. `f2_other_slot`: DNST holding DN slot 0 while an SLD into DN slot 1 proceeds (the transfer completes before the DNST ends) — the per-slot scope of F2 and "one transfer in flight" together.
9. `last_blocks`: SLD/SST at DN layer 23, KV layer 7 kvhead 3 V, CV layer 23 — the address arithmetic's top edge, checked against `plan_state()`'s `end`.
10. `e_base`: SLD with `SB_DN == 0` → `0x10`; `e_range`: kind 3, DN head 1, KV layer 8, CV head 1, `arg1 = 1`, TCNT 4097, a KVAP whose kvhead ≠ the slot tag → `0x11` each; `e_layer`: LAYER with `dn_slot = 2` then DNST → `0x02`; `e_axi`: `+err_at` inside a block → `0x12` at completion, sticky across a following compute dispatch, cleared by a write to SDMA.
11. `dnz_warms`: DNZ on a cold slot then DNST → accepted; `convz_warms` likewise; `busy_any`: STATUS bit 0 set during an SLD while `cmd_cnt` still advances for a following SLD (the accept gate is `busy_cmp`).

Run on snoke, 4 seeds:
```
ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm/tb && make tb_layer_sdma SDMA_SEEDS="1 2 3 4"'
```
Expected before the RTL lands: the Verilator build FAILS on the missing `m_axis_*` ports / `OP_SLD` — commit the build log as `evidence/qwen9b/s2/001_tb_layer_sdma_red.log`.

- [ ] **Step 2: `rtl/state_dma.sv`**, then `lint_state_dma` clean at `-Wall`

Implement the port list above. The issue FSM: `IDLE → (load) AR_ISSUE ↔ R_DRAIN → EXP_AR (KV only) → DONE`, `(store) SLOT_RD → W_ISSUE ↔ B_WAIT → EXP_W (KV) → DONE`; a burst counter caps outstanding at `MAX_OUT`; the read data lands in a `FIFO_D`-beat FIFO before assembly; `xfer_done` on a store pulses only when the B count equals the AW count (the `seq_movers` "bw_idle" rule, `rtl/seq_movers.sv:62-66`). Row assembly: a 4-beat shift register into `slot_wdata`, `slot_we` on the fourth beat; on store, `slot_addr` is issued 2 cycles ahead of the beat that consumes `slot_rdata`.

- [ ] **Step 3: `rtl/layer_chan.sv` — the caches, lanes, fences, CSRs; `rtl/attn_core.sv` widened; the wrapper, the BD and its address map; the emitter shim**

Edit the sites listed under Files. In `rtl/attn_core.sv`: the header contract (`rtl/attn_core.sv:13`) to `T <= 4096`; `cfg_t [12:0]`, `kv_addr [12:0]` = `{bank, t[11:0]}`; `sc_mem [4096]` and `es_mem [4096]` with `(* ram_style = "block" *)` (each 4 RAMB36 at 4,096 deep — S5 records them); `logic [12:0] t, T;` (`rtl/attn_core.sv:104`) and every compare; the arithmetic per row untouched (the invariant). `rtl/layer_chan_ipi.v`: the `m_axis` bundle with the constant `awsize/arsize = 3'b110`, `awburst/arburst = 2'b01`, `awid/arid = 0` ties. `synth/scripts/create_project.tcl`: `NUM_SI {3}` at `synth/scripts/create_project.tcl:223`; after `synth/scripts/create_project.tcl:281`, `must {connect_bd_intf_net [get_bd_intf_pins layer_0/m_axis] [get_bd_intf_pins axi_smc/S02_AXI]}` (the central SmartConnect's `aclk` is already `xdma_0/axi_aclk`, `synth/scripts/create_project.tcl:225`); and in the address-assignment section pin `layer_0/m_axis` to `ddr4_$i` at `$i * 0x100000000`, 4 GiB each, in the exact form used for `seq_0/m_axi` (`synth/scripts/create_project.tcl:449-456`) — without it the 34-bit addresses the CSRs carry do not decode. No emitter edit in S2.  <!--cites:noquote-->

- [ ] **Step 4: GREEN — `tb_layer_sdma` 4 seeds (and the `-G SDMA_NOFENCE=1` RED), the lints, the emitter-independent TBs**

```
ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm/tb && make tb_layer_sdma SDMA_SEEDS="1 2 3 4" && make tb_layer_sdma_nofence SDMA_SEEDS="1" ; FABLE5_MODEL=9b FABLE5_RS_F=7 make tb_dn_step tb_gate_unit tb_conv4_silu tb_seq tb_seq_guard lint_layer_chan lint_state_dma lint_seq_unit'
```
Expected: `TB_LAYER_SDMA PASS` ×4; the `nofence` build FAILS on `f1_stall`'s compare (the RED, committed); every other target's PASS marker at its default seeds (name them in the log); zero `%Warning`. `tb_layer_chan` and `tb_layer_env` are NOT run here — S3 regenerates their vectors.

- [ ] **Step 5: the census GREEN, the RED controls, the retired-code sweep**

```
bash evidence/qwen9b/run.sh evidence/qwen9b/s2/0NN_sdma_bits_green.log python3 evidence/qwen9b/s1/sdma_bits.py
bash evidence/qwen9b/run.sh evidence/qwen9b/s2/0NN_sdma_bits_perturb_rtl.log python3 evidence/qwen9b/s1/sdma_bits.py --perturb rtl
/usr/bin/grep -rn "DN_PIPE\|DN_P2WAIT\|DN_BPG\|g_dnpipe\|g_cv\[" rtl/ tb/ synth/scripts/ --include=*.sv --include=*.v --include=*.tcl
```
Expected: PASS; CAUGHT; the sweep hits only comments that say "retired (S2)" and `synth/exp_uram/` (the experiment scripts, edited by S5).

- [ ] **Step 6: gate doc + commit**

`evidence/qwen9b/s2/S2_RTL.md`: the port list as landed, the cache geometry and the ownership muxes by line, the two lanes and fences by line, every RED/GREEN log, the DNST cycle count at `RLAT = 2` from `tb_dn_step`'s cycle marker beside G3.4's 1,930 (`evidence/qwen9b/g3/G3_4_LAYER.md:194-195`, label T), the `attn_core` widening, the retired code list, the lint results, and the statement that the layer family re-runs at S3.  <!--cites:noquote-->

```bash
git add rtl/state_dma.sv tb/axi_ram_bfm.sv tb/tb_layer_sdma.sv evidence/qwen9b/s2
git commit -m "rtl(S2): layer state in DDR — state_dma (512-bit AXI4 R/W master on aclk), two-slot DN/KV/CV caches with ownership muxes, the DMA lane with F1/F2, slot tags, busy_cmp/busy_any, E_* codes, SB_*/SDMA/SDMA_CYC CSRs, attn_core at T<=4096; DN_PIPE and the 24/8/24 banks retired; tb_layer_sdma RED->GREEN x4 with the nofence control" \
  -- rtl/state_dma.sv rtl/layer_chan.sv rtl/attn_core.sv rtl/layer_chan_ipi.v \
     tb/axi_ram_bfm.sv tb/tb_layer_sdma.sv tb/Makefile \
     synth/scripts/create_project.tcl evidence/qwen9b/s2
```

---

### Task S3: the emitter schedule, the reference DDR image, the writable TB DDR model, the golden, the host plan, and the layer family re-run

> **CLASS B, 2026-09-04 (S3's Step 5' drift pass, base `07eea51`).** The
> coordinates in this task's **Files** list below are PRE-S3 instruction
> coordinates and are kept at their base numbers on purpose. S3's own
> `--fix` renumbered every one that MOVED; what is left names code S3
> **retired**, so there is nothing to renumber to and a renumber would be
> worse than a stale number (`evidence/qwen9b/g3/G3_4_LAYER.md` §15.5).
> The successor sites, once each:
>
> | this list names | what it was | the successor |
> |---|---|---|
> | `ref/gen_layer_script.py:307-311` | `_DN_SLOTS = 24`, `_KV_SLOTS = 8` and their assert | the cache-slot block (`_DN_SLOTS = _KV_SLOTS = _CV_SLOTS = 2`) plus `_DN_LAYERS`/`_KV_LAYERS`, the DDR image's extent |  <!--cites:noquote-->
> | `ref/gen_layer_script.py:447-467` | the banked `cw`/`cs`/`S`/`kc`/`vc`/`T` arrays | `Mach.__init__`'s two-slot arrays, `self.img`, `self.warm`, `self.slot_id`, `self.tag` |  <!--cites:noquote-->
> | `ref/gen_layer_script.py:635`, `:640-647` | `Treset` on one kv_slot, `layer(dn_slot, kv_slot)` | `Treset` over all eight attention layers, `layer(dn, kv, cv=0, kv_layer=0)` |  <!--cites:noquote-->
> | `ref/gen_layer_script.py:775-789` | `convw`/`convz`/`conv` on `dn_slot` | the same three on `cv_slot`, with `_require_warm` on `conv` and the `convw` shim's own note |  <!--cites:noquote-->
> | `ref/gen_layer_script.py:1705` | `main`'s CONVW preamble | `seed_conv` + `sched_preamble` |  <!--cites:noquote-->
> | `ref/gen_model_script.py:587-600`, `ref/gen_token_script.py:198`, `ref/gen_token_script.py:201`, `ref/gen_chain_script.py:108`, `ref/gen_chain_script.py:111`, `ref/seq_chat.py:1419`, `ref/seq_chat.py:1424`, `sw/infer.py:766` | the CONVW loop and the 768 `dnz` of the static preamble | `M.seed_conv(...)` + `GLS.sched_preamble(...)` in each of the five generators (spec §6.4; the bytes are proved equal by `evidence/qwen9b/s3/preamble_equiv.py`) |  <!--cites:noquote-->
> | `tb/tb_layer_chan.sv:191`, `tb/Makefile:447-465` | `run_dnbank` and the `tb_layer_dnbank` target | RETIRED with the banks they proved; the property moved to the DDR image (the SEQ gate's `STATE` compare) and to `tb/tb_layer_sdma.sv` |  <!--cites:noquote-->
>
> Every other document whose citations S3's edits moved was repaired by
> `--fix` and re-checked by `--verify`; the ones left UNRESOLVED are listed
> by name in `evidence/qwen9b/s3/S3_CHAIN.md`.

**Files:**
- Modify: `ref/gen_layer_script.py:307-311` (`_DN_SLOTS = _KV_SLOTS = _CV_SLOTS = 2`, the assert), `ref/gen_layer_script.py:640-647` (`layer(dn_slot, kv_slot, cv_slot=0, kv_layer=0)` — the two new fields default so two-argument callers still run — printing `SF.layer_word(...)` at `ref/gen_layer_script.py:647`), `ref/gen_layer_script.py:447-467` (the state containers), `ref/gen_layer_script.py:635` (the T reset), `ref/gen_layer_script.py:775-789` (`convw`/`convz`/`conv` on slots), `ref/gen_layer_script.py:1195` (`dnst`), `ref/gen_layer_script.py:1248` (`kvap`), `ref/gen_layer_script.py:1341` (`attn`), `ref/gen_layer_script.py:1441` (`dnz`); new `sld()`/`sst()`, `_require_warm()`, a `StateImage` class; `ref/gen_token_script.py:68` and `ref/gen_token_script.py:84` (imports the new slot counts), `ref/gen_token_script.py:191`, `ref/gen_token_script.py:213` (two-argument `layer()` calls with bank indices) and `ref/gen_token_script.py:198` (`convw`); the other `layer()` callers with bank indices — `ref/gen_chain_script.py:101`, `ref/gen_chain_script.py:118`, `ref/seq_chat.py:1417`, `ref/seq_chat.py:1436`, `sw/infer.py:766`, `sw/infer.py:796` — each rewritten to the slot form (`L % 2`, with `kv_layer` = the attention layer) where the path is a live 9B path, or annotated as a pre-G3 (frozen-model) path per G3.3's tools-valid convention where it is not; the boardfree selftests must stay unmoved either way, which the gate proves  <!--cites:noquote-->
- Modify: `ref/gen_model_script.py:587-600` (the preamble: `M.layer` at `ref/gen_model_script.py:587`, `M.Treset()` at `ref/gen_model_script.py:589`, the CONVW loop `ref/gen_model_script.py:591-594`, `convz` `ref/gen_model_script.py:595`, the `dnz` loop `ref/gen_model_script.py:596-597`), the per-layer loop (the §6 schedule around the DN/attention/conv emission)
- Modify: `ref/seq_model.py` (a `StateRegion` class beside `DDRWeights` at `ref/seq_model.py:305`; SLD/SST execution in `__call__` at `ref/seq_model.py:1264`; `gate()` at `ref/seq_model.py:1272` compares the region image at the end of the stream), `ref/seq_format.py:1373-1389` (as of e905cd3 — S1 inserts above; re-anchor) (`on_layer(dn_slot, kv_slot, cv_slot, kv_layer)`; `on_treset` loops the eight attention layers; the TCNT/TCNT2 13-bit packing)  <!--cites:noquote-->
- Modify: `tb/seq_mem_file.sv:57-` (the AXI4 write channel over a RAM-backed window `[SBASE, SBASE+SLEN)` initialised from `<prefix>.state.bin`; reads inside the window from the RAM, outside from the files; writes outside the window `$fatal`), `tb/tb_seq_chip.sv:387` (the 512-bit per-channel instance of the state channel gains the write port and the window; `u_layer.m_axis` connects there; the `SMEM` golden check at end of launch), `tb/scripts/gen_seq_chip_vectors.py:361-389` (`SMEM <hex addr> <hex len> <hash>` records per touched block; write `<prefix>.state.bin`)  <!--cites:noquote-->
- Modify: `tb/tb_layer_chan.sv` (retire `run_dnbank` at `tb/tb_layer_chan.sv:191`; the LAYER writes use `layer_word`), `tb/Makefile` (retire `tb_layer_dnbank`, `tb/Makefile:447-455`; `tb_layer_env` and `tb_layer_chan` regenerate at v2.1)
- Modify: `sw/hwmap.py:432-` (line numbers as of e905cd3 — S1 inserts above them; re-anchor from `git show` before editing) (`load_weights_manifest` learns the `state` plan; the manifest writer emits it and the conv images; TCNT packing), `sw/seq_run.py` (write `L_SB_*` after upload; refuse to launch with any zero), `sw/chat_seq.py` (session reset = DN region memset via the existing H2C path + the TCNT reset; audit witnesses of the conv images), `sw/tok_meter.py` (state bytes per token, label D)
- Test: `ref/seq_model.py --gate` on the re-emitted 9B smoke artifacts (the set `evidence/qwen9b/g4/G4A_REPLAY.md` §2 names; target `w9_9b_smoke_scripts`, `tb/Makefile:1244`); `tb_layer_chan` and `tb_layer_env` at `FABLE5_MODEL=9b FABLE5_RS_F=7` (`LAYERV2_SEEDS`, 4 seeds); `tb_seq_chip` smoke at 4 seeds (`W9_SEEDS`); `sw/seq_run.py --selftest`, `sw/chat_seq.py --selftest` (boardfree, unmoved at 2759/85/356); `evidence/qwen9b/g4/g4a_envelope.py` extended to SLD/SST

**Interfaces:**
- Consumes S1's names (`OP_L_SLD`, `sdma_arg0`, `layer_word`, `STATE_*`, `plan_state`) and S2's row formats, TCNT widths and slot tags.
- Produces for S4: `GLS.sld(kind, slot, layer, head=0)` / `.sst(...)`; `StateImage.blocks[(kind, layer, head)] -> np.ndarray` (uint8 bytes of one layout block: DN per head, KV per (layer, kvhead, kv), CV per layer); the manifest keys `state: {dn, kv, cv, end, sha256}` and `conv_images: [24 × file]`; `seq_model.StateRegion` with `.load(prefix)` / `.blocks`; the `SMEM` record grammar `SMEM <hex addr> <hex len> <fnv1a64>` (FNV-1a 64-bit over the bytes, computed identically in Python and in the TB — the hash is the transport, byte equality the check).

- [ ] **Step 1: the emitter model — RED first, for the right reason**  <!--cites:noquote-->

Replace the banked containers (`ref/gen_layer_script.py:462-467`) with two cache slots per kind and a DDR image:  <!--cites:noquote-->

```python
class StateImage(object):
    """The DDR state region as the emitter models it: one uint8 block per (kind, layer, head)."""
    def __init__(self):
        self.blocks = {}                             # (kind, layer, head) -> np.ndarray uint8
    def get(self, key, nbytes):
        return self.blocks.setdefault(key, np.zeros(nbytes, dtype=np.uint8))
```
and in `__init__` (`ref/gen_layer_script.py:508`): `self.S = np.zeros((2, LR.LNH, LR.LDK, LR.LDV), I64)`, `self.kc/self.vc` two slots × one kvhead each, `self.T = [[0]*_KVH for _ in range(8)]` indexed by ATTENTION LAYER (as the hardware's `tcnt_bank` is), `self.cw/self.cs` two slots, `self.img = StateImage()`, per kind per slot `self.warm = {k: [False, False]}`, `self.slot_id = {k: [None, None]}` and, for KV, `self.tag = [None, None]`. **Seed the conv images:** `StateImage` blocks `(CV, L, 0)` are initialised from the same per-layer conv weights the old preamble's CONVW loaded (`ref/gen_model_script.py:591-594`'s source), state words zero — this is what the host uploads (Step 4) and what makes the retired preamble equivalent.  <!--cites:noquote-->

```python
    def sld(self, kind, slot, layer, head=0):
        self.C(13, SF.sdma_arg0(kind, slot, layer, head), 0, 0)
        self._sdma_copy(kind, slot, layer, head, to_slot=True)
        self.warm[kind][slot] = True; self.slot_id[kind][slot] = (layer, head)
        if kind == SF.SDMA_KIND_KV: self.tag[slot] = (layer, head >> 1)
    def sst(self, kind, slot, layer, head=0):
        self.C(14, SF.sdma_arg0(kind, slot, layer, head), 0, 0)
        assert self.slot_id[kind][slot] == (layer, head), "SST of a slot holding another block"
        self._sdma_copy(kind, slot, layer, head, to_slot=False)
        self.warm[kind][slot] = False
    def _require_warm(self, kind, slot, what):
        assert self.warm[kind][slot], f"{what}: {['DN','KV','CV'][kind]} slot {slot} is COLD (E_DMA_COLD)"
```
`_sdma_copy` serialises/deserialises exactly the DDR row formats of B15.1 (DN: the whole layer, 32 × 128 rows × 128 int16 little-endian; KV: `T[layer][kvhead]` rows × 256 B then the exponent bytes at +1 MiB; CV: 8,192 × 16 B). `dnst()`, `kvap()`, `attn()`, `conv()` call `_require_warm` first and index `self.S[slot]`, `self.kc[slot]`, `self.cw[slot]`; `kvap()`/`attn()` also assert `self.tag[slot][1] == kvh` (the hardware's tag check); `convw(sel 0/1)` keeps loading the slot (S2's shim) and `convz`/`dnz` warm their slot; the T reset (`ref/gen_layer_script.py:635`) becomes a loop over the eight attention layers.  <!--cites:noquote-->

**The RED, for the right reason:** a five-line script in `evidence/qwen9b/s3/cold_red.py` that constructs a `GLS`, calls `layer(0, 0, 0, 0)` and then `dnst(0, …)` with no SLD — it must raise `DNST: DN slot 0 is COLD (E_DMA_COLD)`. (Re-running a whole generator is not the RED: its own preamble calls `convw`, and the failure would be that, not the fence.) Commit the log as `evidence/qwen9b/s3/001_emitter_cold_red.log`.

- [ ] **Step 2: the schedule in `ref/gen_model_script.py`**  <!--cites:noquote-->

At the per-layer loop, emit spec §6.1–§6.3 literally (DN layers `L` over 0..23, attention layers `A` over 0..7, conv per DN layer):

```python
def dn_layer(M, L, nxt_is_attn, A_next):
    if L > 0:            M.sst(SF.SDMA_KIND_DN, (L-1) % 2, L-1)
    if L < 23:           M.sld(SF.SDMA_KIND_DN, (L+1) % 2, L+1)
    if nxt_is_attn:      # the first kvhead of the coming attention layer, both halves
        M.sld(SF.SDMA_KIND_KV, 0, A_next, 0); M.sld(SF.SDMA_KIND_KV, 0, A_next, 1)
    M.layer(dn_slot=L % 2, kv_slot=M.kv_slot, cv_slot=L % 2, kv_layer=M.kv_layer)
    for h in range(32): M.dnst(h, ...)          # unchanged arguments
def attn_layer(M, A):
    for h in range(4):
        if h < 3:
            M.sld(SF.SDMA_KIND_KV, (h+1) % 2, A, (h+1) << 1); M.sld(SF.SDMA_KIND_KV, (h+1) % 2, A, ((h+1) << 1) | 1)
        M.layer(dn_slot=M.dn_slot, kv_slot=h % 2, cv_slot=M.cv_slot, kv_layer=A)
        M.kvap(h, ...); [M.attn(h, q, ...) for q in range(4*h, 4*h+4)]
        M.sst(SF.SDMA_KIND_KV, h % 2, A, h << 1); M.sst(SF.SDMA_KIND_KV, h % 2, A, (h << 1) | 1)
def conv_block(M, L):
    if L > 0:  M.sst(SF.SDMA_KIND_CV, (L-1) % 2, L-1)
    if L < 23: M.sld(SF.SDMA_KIND_CV, (L+1) % 2, L+1)
    M.conv(...)
```
The preamble (`ref/gen_model_script.py:587-600`): keep `M.layer` (now with four fields) and the T reset (which `on_treset` expands to eight LAYER writes and sixteen TCNT/TCNT2 writes); delete the CONVW weight loop and the 768 `dnz`; add `M.sld(DN, 0, 0)`, `M.sld(CV, 0, 0)`, and the first attention layer's kvhead-0 K/V. The end of the token: `M.sst(DN, 1, 23)`, `M.sst(CV, 1, 23)`, then `M.sld(DN, 0, 0)`, `M.sld(CV, 0, 0)` for the next token (§6.1's last sentence). Per-token census this yields: DN 48, CV 48, KV 128 (16 prefetches from the DN layers + 8 × (6 + 8)) = **224 SLD/SST** (spec A1.5(c)).  <!--cites:noquote-->

**The equivalence check:** `evidence/qwen9b/s3/preamble_equiv.py` builds the old-style initial state (the pre-S3 emitter's preamble: `convw` loads, `convz`, 768 `dnz`) and the new `StateImage`'s initial blocks, and asserts byte equality per block after the same serialisation — the cheapest guard on the whole "retired preamble" claim. Its log is committed.

- [ ] **Step 3: `seq_model.StateRegion` and the writable TB DDR model, RED first**  <!--cites:noquote-->

`ref/seq_model.py`: beside `DDRWeights` (`ref/seq_model.py:305`), a `StateRegion(prefix)` that loads `<prefix>.state.bin` + the manifest's `state` plan, and whose `sld(kind, slot, layer, head)`/`sst(...)` do the same byte copies as the emitter (the two are independent implementations — that is the lockstep). `__call__` (`ref/seq_model.py:1264`) executes ops 13/14 through it; `gate()` (`ref/seq_model.py:1272`) compares, at the end, every block the stream stored against the emitter's `StateImage` dumped into the golden (`SMEM` records). RED: run `--gate` on a re-emitted `lay9b_s1` BEFORE the model executes SLD/SST → `SF.SeqValidationError: unknown layer_chan opcode 13` (`ref/seq_model.py:861`); commit the log.  <!--cites:noquote-->

`tb/seq_mem_file.sv`: add the write channel over a RAM window; `tb/tb_seq_chip.sv:387`'s per-channel 512-bit instance for the planner's state channel gets the window parameters from the vector generator; `u_layer.m_axis_*` connect there; at end of launch each `SMEM` record is checked (FNV-1a 64 over the window bytes at `<addr>..<addr+len>`, computed in the TB). `tb/tb_layer_chan.sv` and `tb/Makefile`: `run_dnbank` and `tb_layer_dnbank` retired with a comment naming S3; LAYER writes go through `layer_word`.  <!--cites:noquote-->

- [ ] **Step 4: the host plan and the artifact**  <!--cites:noquote-->

`sw/hwmap.py`: the manifest gains `"state": plan_state(base)` with `base` = the first 64 KiB-aligned address above the pack on the emptiest channel (`plan_weights` already knows per-channel tops), plus `"state_sha256"` over the initial image and `"conv_images": [...]` (24 files written by the artifact emitter from the same conv weights `StateImage` seeds, in the B15.1 16-B row format); the TCNT/TCNT2 packers to 13 bits. `sw/seq_run.py`: after the upload, write `L_SB_DN/KV/CV` (= base >> 16), memset the DN region to zero through the existing H2C path, upload the conv images, and refuse to launch if a readback of any `L_SB_*` is zero. `sw/chat_seq.py`: session reset = the memset + the TCNT reset it already does (now eight layers); the residency probe gains one witness per conv image. `sw/tok_meter.py`: `state_bytes_per_token(T)` = `2·24·1 MiB + 2·24·128 KiB + 2·8·4·2·(T·256 + 64·ceil(T/64))` (label D; ≈ 70 MiB at T = 512, ≈ 182 MiB at T = 4,096 — the spec's §9 "≈ 50 MiB" was low and is corrected by this number).

- [ ] **Step 5: GREEN — the smoke artifacts through the whole chain, and the layer family at v2.1**

On snoke, `FABLE5_MODEL=9b FABLE5_RS_F=7`: re-emit the smoke set (`make -C tb w9_9b_smoke_scripts`), then:
```
bash evidence/qwen9b/run.sh evidence/qwen9b/s3/0NN_seqgate_smokes.log sh evidence/qwen9b/g4/run_g4a_seqgate.sh <the smoke list>
ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm/tb && FABLE5_MODEL=9b FABLE5_RS_F=7 make tb_layer_chan tb_layer_env LAYERV2_SEEDS="1 2 3 4" && make seq_chip_vectors_9b && make tb_seq_chip_9b_smoke W9_SEEDS="1 2 3 4"'
bash evidence/qwen9b/run.sh evidence/qwen9b/s3/0NN_boardfree.log sh evidence/qwen2b/rd/rd_boardfree.sh
bash evidence/qwen9b/run.sh evidence/qwen9b/s3/0NN_envelope.log python3 evidence/qwen9b/g4/g4a_envelope.py --sdma <the smoke list>
```
(`seq_chip_vectors_9b` is at `tb/Makefile:1289`; the 9B smoke chip target's name is whatever the Makefile carries at S3's tree — use it and say so.) Expected: `SEQ GATE: PASS` on every smoke artifact with `STATE BIT-EXACT`; `TB_LAYER_CHAN PASS` ×4 (state the check count beside G3.4's 261,357 — the DNZ-heavy cases move, the DNST/ATTN/CONV cases do not); `TB_LAYER_ENV PASS` ×4; `TB_SEQ_CHIP PASS` ×4 with `smem N` in the PASS line; `BOARDFREE_PASS 2759/85/356` unmoved; the envelope tool reports every SLD/SST field at or inside its B15 ceiling, with a RED (a forced kind 3) REFUSED.

- [ ] **Step 5′: the citation-drift pass S1 left open**

S1's insertions into `ref/seq_format.py` and `sw/hwmap.py` shifted lines that ≈ 94 citations in 18 documents name (S1's gate doc §6.4 lists them and the five documents a `--fix` at base `e905cd3` must `--exclude`); the tool refused a blanket `--fix` as UNSAFE. S3 inserts into the same two files again, so the pass is done ONCE here, after S3's own edits: `--plan` per disjoint edited set, `--fix` only where SAFE, hand repair of the rest at the citation level, `--verify` at each base, the documents listed by name in the gate doc.

- [ ] **Step 6: gate doc + commit**

`evidence/qwen9b/s3/S3_CHAIN.md`: the schedule as emitted (the 224-per-token census, and what the preamble adds), the two independent state models named by file:line, the `SMEM` grammar, the manifest keys, the equivalence check, every RED/GREEN log, the layer-family counts beside G3.4's.

```bash
git add evidence/qwen9b/s3
git commit -m "chain(S3): the emitter schedules SLD/SST (DDR image + cache slots + tags, cold-slot asserts, conv images seeded, preamble equivalence proven), seq_model executes them against a StateRegion, the TB DDR model gains a write window and the golden SMEM records, the host plans the state region and writes SB_* — smoke artifacts SEQ GATE PASS + STATE BIT-EXACT, layer family x4 at v2.1, tb_seq_chip smoke x4, boardfree unmoved" \
  -- ref/gen_layer_script.py ref/gen_model_script.py ref/gen_token_script.py ref/gen_chain_script.py ref/seq_chat.py sw/infer.py ref/seq_model.py ref/seq_format.py \
     tb/seq_mem_file.sv tb/tb_seq_chip.sv tb/tb_layer_chan.sv tb/scripts/gen_seq_chip_vectors.py tb/Makefile \
     sw/hwmap.py sw/seq_run.py sw/chat_seq.py sw/tok_meter.py \
     evidence/qwen9b/g4/g4a_envelope.py evidence/qwen9b/s3
```

---

### Task S4: the 9B replay on the new design — token-identical, and the layer term measured

**Files:**
- Create: `evidence/qwen9b/s4/S4_REPLAY.md`, the logs
- Modify: `evidence/qwen9b/g4/run_g4a_replay.sh` (a `--tokens-ref` argument comparing the decoded tokens to `evidence/qwen9b/g4/G4A_REPLAY.md`'s record; otherwise unchanged), `evidence/qwen9b/g4/tb_layer_census.sv` (the SLD/SST opcodes in its per-opcode table; it reads LCYC, which is `busy_cmp` cycles, and additionally reads `SDMA_CYC` for the DMA lane)
- Test: `ref/seq_model.py --gate` on the full model (`model_9b_s1..s4`), `tb_seq_chip` full model at 4 seeds, `tb_layer_census` six steps

**Interfaces:**
- Consumes: S3's chain and the stream set; Task 11's token record (`evidence/qwen9b/g4/G4A_REPLAY.md` §4.1a: the six tokens per seed) and cycle counts; Task 12's layer term (`evidence/qwen9b/g4/G4B_STRUCT.md:23` 46.079 ms mean, `evidence/qwen9b/g4/G4B_STRUCT.md:913` DNST 3,090 cycles/command).
- Produces for S5/Task 14: the new stream set's shas, the token-identity verdict, the measured layer term and DNST cycles at `RLAT = 2` beside Task 12's, the SLD/SST dispatch cost per token, the DMA lane's `SDMA_CYC` per token, and the count of F1/F2 stalls actually taken (visible as compute-lane cycles spent waiting at dispatch — the census infers them from per-command cycles above the command's known cost and says so).

- [ ] **Step 1: re-emit the 9B model streams (four seeds) and gate them**

```
ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm && bash evidence/qwen9b/run.sh evidence/qwen9b/s4/001_emit_9b_s1.log sh -c "cd ref && FABLE5_MODEL=9b FABLE5_RS_F=7 SEQ_PROFILE=epsnorm SEQ_NCH=4 SEQ_REPACK=1 <the exact command line evidence/qwen9b/g4/G4A_REPLAY.md §7 records> ../tb/scripts/w9/model_9b_s1.txt"'
```
then s2..s4 concurrently (≈ 3 h each, as Task 11 measured), then `evidence/qwen9b/g4/run_g4a_seqgate.sh` over the four → `SEQ GATE: PASS` ×4 with `2358/2358` checkpoints and `STATE BIT-EXACT`.

- [ ] **Step 2: the full-model chip replay, 4 seeds in parallel, token-identical**

```
ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm/tb && make seq_chip_vectors_9b && cd ../evidence/qwen9b/g4 && sh run_g4a_replay.sh model_9b_s --seeds 4 --tokens-ref G4A_REPLAY.md'
```
Expected: `TB_SEQ_CHIP PASS` ×4, `tokens 6` each, `TOKENS IDENTICAL TO G4A` ×4, `smem` count > 0, `miss 0`; wall clock and memory recorded (`evidence/qwen9b/g4/run_g4a_memwatch.sh`). **A token mismatch is a STOP with the artifacts preserved** — report BLOCKED with the first divergent checkpoint from `--gate`; the controller dispatches a debugging round.

- [ ] **Step 3: the layer-term census**

```
ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm/evidence/qwen9b/g4 && sh run_g4b_census.sh shipped6 ../../../tb/scripts/w9/model_9b_s1 +stopm=7'
```
Expected: `TB_LAYER_CENSUS PASS` bit-exact; the per-opcode table has SLD (13) and SST (14) rows whose LCYC cost is their dispatch only (the transfer runs on the DMA lane and is counted in `SDMA_CYC`, reported beside); DNST mean cycles at `RLAT = 2` (expected ≈ 1,798 + the command overhead beside Task 12's 3,090 at `RLAT = 6` — label T when measured); the per-step layer term beside 46.079 ms; any F1/F2 stall shows as per-command cycles above the known cost and is attributed by command.

- [ ] **Step 4: gate doc + commit**

`evidence/qwen9b/s4/S4_REPLAY.md`: shas of the four streams, the gate lines, the four token sequences beside Task 11's, the census table with the SLD/SST rows, `SDMA_CYC` per token, the stall attribution, the layer term with its label, the not-established list (nothing placed; nothing on the board).

```bash
git add evidence/qwen9b/s4
git commit -m "gate(S4): the 9B model on the DDR-state design — SEQ GATE PASS x4 with STATE BIT-EXACT, chip replay 4 seeds TOKEN-IDENTICAL to G4A, layer term measured with the SLD/SST dispatch cost, SDMA_CYC and F1/F2 stalls attributed" \
  -- evidence/qwen9b/g4/run_g4a_replay.sh evidence/qwen9b/g4/tb_layer_census.sv evidence/qwen9b/s4
```

---

### Task S5: structure and placement — OOC counts and the one-SLR floorplan

**Files:**
- Create: `synth/constraints/fable5_floorplan_9b_1slr.xdc`, `evidence/qwen9b/s5/S5_STRUCT.md`, `evidence/qwen9b/s5/s5_superlatives.py`, the logs and report sections
- Modify: `synth/exp_uram/scripts/exp_ooc.tcl` — the file list (`synth/exp_uram/scripts/exp_ooc.tcl:164-165`) gains `rtl/state_dma.sv`; the `-generic DN_PIPE`/`DN_BPG` passes go (S2 deleted both parameters); the URAM prediction becomes `2*29 + 2*58 + 2*4 = 182`; `GeomExpect` (`synth/exp_uram/scripts/exp_ooc.tcl:141`) and the positional argument list (`DN_PIPE` and `DN_BPG` removed) follow; `synth/exp_uram/scripts/launch_exp.sh`'s `-tclargs` line follows the TCL. **`synth/exp_uram/rtl/` is NOT touched** (see Standing hazards): the vehicle reads the shipping `rtl/` (`synth/exp_uram/scripts/exp_ooc.tcl:75`).  <!--cites:noquote--> *(Repaired at S5's close, 2026-09-05. The coordinates this entry used to carry for the generics pass, the prediction, the argument list and `launch_exp.sh`'s `-tclargs` line — `exp_ooc.tcl` lines 157-158, 88-90, 96 and 42-47, and `launch_exp.sh` line 61, all as of commit e16a3ec — named the lines S5 was INSTRUCTED to DELETE, so `evidence/qwen9b/o3/o3_cite_drift.py` reported them UNRESOLVED and correctly refused to renumber them. They are rewritten OUT of citation form rather than pointed at whatever now occupies those numbers; `git show e16a3ec:synth/exp_uram/scripts/exp_ooc.tcl` is the file they described. The file-list range moved 129-130 -> 164-165 and IS renumbered: both endpoints still exist, `state_dma` having joined the second one.)*
- Modify: the eight Task-13 XDCs `synth/constraints/fable5_floorplan_9b_dngrp.xdc`, `synth/constraints/fable5_floorplan_9b_dngrpcr.xdc`, `synth/constraints/fable5_floorplan_9b_dnbank.xdc`, `synth/constraints/fable5_floorplan_9b_dnslr.xdc`, `synth/constraints/fable5_floorplan_9b_kvslr.xdc`, `synth/constraints/fable5_floorplan_9b_combo.xdc`, `synth/constraints/fable5_floorplan_9b_convcr.xdc`, `synth/constraints/fable5_floorplan_9b_layer0.xdc` (a `SUPERSEDED 2026-09-04 (state spill)` banner line, comment only)
- Test: `synth/scripts/ooc_9b.tcl` per module (`evidence/qwen9b/g4/run_g4b_ooc.sh`), the placement experiment (`synth/exp_uram/scripts/launch_exp.sh`), `synth/exp_uram/scripts/family_census.tcl` and `synth/exp_uram/scripts/finish_reports.tcl` from Task 13

**Interfaces:**
- Consumes: S2's RTL; Task 12's harness and baselines (`evidence/qwen9b/g4/G4B_STRUCT.md:149-155`, `evidence/qwen9b/g4/G4B_STRUCT.md:182-191`: URAM 928, block RAM 690, DSP 1,836, LUT 110,367, FF 79,078); Task 13's harness, reading rule and thresholds (`evidence/qwen9b/g5/G5A_FLOORPLAN.md` §0.1).
- Produces for Task 14: the floorplan XDC the full build starts from (the one-SLR pblock, in the `bd_i/layer_0` form), the OOC row for it, the fan-out measurement the ownership muxes demand (spec A1.2), and the STOP-or-go verdict.

- [ ] **Step 1: OOC synthesis counts on the new `rtl/`**

```
ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm/evidence/qwen9b/g4 && sh run_g4b_ooc.sh s5_layer layer_chan'
```
Expected (label T when read from `evidence/qwen9b/s5/ooc_s5_layer_util_synth.rpt`): URAM288 **182** (58 + 116 + 8) — any other number STOPS the task (the cache geometry is the design); block RAM ≈ 90 tiles (the scratch 57, `sc_mem` 4, `es_mem` 4, the two KV exponent memories, the rest named); DSP 1,836; LUT and FF reported beside Task 12's with the delta attributed (the retired `DN_PIPE` FFs ≈ −24.6 K; the DMA engine and the ownership muxes).

- [ ] **Step 2: the one-SLR placement, and the mux's cost measured**

`synth/constraints/fable5_floorplan_9b_1slr.xdc` (OOC form, with the `bd_i/layer_0` rewrite stated in its header as Task 13's XDCs do): one SOFT pblock over `CLOCKREGION_X0Y5:CLOCKREGION_X5Y9` (SLR1, where two of the four MIGs sit — `synth/constraints/fable5_floorplan_a.xdc:20-24`) holding every cell of `layer_chan`. Run it at Default and `AltSpreadLogic_medium` with Task 13's launcher (its new argument order) plus one unconstrained baseline, all concurrent (three runs, ≈ 1 h). Collect with `synth/exp_uram/scripts/collect_evidence.sh`, `synth/exp_uram/scripts/finish_reports.tcl`, `synth/exp_uram/scripts/family_census.tcl` (its families now: `DN_SLOT`, `KV_SLOT`, `CV_SLOT`, `SDMA`, `ATTN_DSP`, `SCRATCH`; the `DN_SLOT`/`KV_SLOT` write-fan-out rows are the ownership-mux measurement spec A1.2 requires — report them against Task 13's −0.001 / −0.368 under 2′cr).

Expected: the whole layer placed inside SLR1 (`*_uram_slr_census.rpt`: SLR1 = 182, others 0; block RAM and DSP per SLR from `*_util_placed_slr.rpt`); WNS reported against Task 13's −0.554 and the playbook's reach (≈ −0.1 to −0.3 closes at the full build with `phys_opt`). **Reading rule, stated before the numbers:** OOC failure is definitive; OOC success is necessary, not sufficient. **STOP-back:** if the one-SLR layer is outside the playbook's reach at OOC, report BLOCKED with the per-family table and the worst path decomposition — the fork is the user's (the spec's §12 risk 1).

- [ ] **Step 3: supersession banners and the superlative check**

Add the `SUPERSEDED` comment line to the eight Task-13 XDCs (comment only). Copy `evidence/qwen9b/g5/g5_superlatives.py` to `evidence/qwen9b/s5/s5_superlatives.py`, pointed at the S5 logs and the S5 gate doc, and run it with its negative control before the gate doc is committed — the class recurred four times in Task 13.

- [ ] **Step 4: gate doc + commit**

`evidence/qwen9b/s5/S5_STRUCT.md`: the reading rule first; the counts table against Task 12; the placement rows (baseline, 1slr Default, 1slr AltSpread) with URAM/BRAM/DSP per SLR, WNS/TNS/failing endpoints, the worst family and its decomposition, the DN/KV write fan-out rows against 2′cr; the chosen XDC or the stop-back; the not-established list (nothing routed; nothing in context; directive spread sampled).

```bash
git add synth/constraints/fable5_floorplan_9b_1slr.xdc evidence/qwen9b/s5
git commit -m "gate(S5): the DDR-state layer synthesized OOC (URAM 182, BRAM ~90) and placed inside ONE SLR with the ownership-mux fan-out measured; floorplan for Task 14 chosen or the stop-back reported; Task 13's eight XDCs marked superseded" \
  -- synth/constraints/fable5_floorplan_9b_1slr.xdc \
     synth/constraints/fable5_floorplan_9b_dngrp.xdc synth/constraints/fable5_floorplan_9b_dngrpcr.xdc \
     synth/constraints/fable5_floorplan_9b_dnbank.xdc synth/constraints/fable5_floorplan_9b_dnslr.xdc \
     synth/constraints/fable5_floorplan_9b_kvslr.xdc synth/constraints/fable5_floorplan_9b_combo.xdc \
     synth/constraints/fable5_floorplan_9b_convcr.xdc synth/constraints/fable5_floorplan_9b_layer0.xdc \
     synth/exp_uram/scripts/exp_ooc.tcl synth/exp_uram/scripts/launch_exp.sh evidence/qwen9b/s5
```

---

## Then: the migration plan's Task 14

Task 14 (`docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md`, "G5b — the full build and timing closure") runs as written, with these substitutions its dispatch carries: the floorplan is `synth/constraints/fable5_floorplan_9b_1slr.xdc` in its `bd_i/layer_0` form (not Task 13's); `synth/scripts/create_project.tcl` already carries the third SmartConnect port and its address map (S2); the OOC starting point is S5's number, not −1.391; the netlist confidence is S4's token-identical replay.

## Open items for the user (non-blocking)

1. The ≈ 740 freed URAMs — the spec's §11 leaves their use open.
2. Whether T = 4,096 is the ceiling or a step toward streaming attention.
3. The channel the host planner places the region on (default: the emptiest weight channel).
4. The row-range SST optimisation (spec §9) — not built; measured need first.

## Self-review (done while writing revision 2)

- **Spec coverage:** §2 → S1 (constants) + S3 (plan, images); §3 with A1.2 → S2; §4 → S2; §5.1–5.5 with A1.1/A1.3/A1.4 → S1 + S2; §6 → S3; §7 → S3; §8.1 → S4; §8.2–8.3 → S2 + S3 (incl. the F1 bypass control, T = 0, the other-slot and last-block cases); §8.4 → S5; §8.5 → S4 (LCYC = `busy_cmp`, `SDMA_CYC` beside it); §9's expectations → S4/S5 measure them (the KV traffic number corrected in S3 Step 4); §10 → the task set; §11's made decisions are each pinned to a task above.
- **Review items folded:** B1 (A1.1, S1/S3), B2 (A1.2, S2/S5), B3 (A1.3, S1/S2/S3), B4 (A1.4, S2/S4), B5 (S2), B6 (the S2/S3 boundary), B7 (the `convw` shim, `gen_token_script.py` listed), B8 (`xfer_rows[13:0]`), M1–M15 and the minors (sites corrected: `gate()` at `ref/seq_model.py:1272`, the RED string, the census 224, the bytes formula, the err-code table, the two B14s, eight XDCs, `LAYER_RTL`, the 512-bit instance, the FIFO, `L_TCNT` at `sw/hwmap.py:179`, the compatibility claim dropped, the overlaps named, `tb/Makefile` edited by S3).  <!--cites:noquote-->
- **Placeholders:** the census log numbers are written `0NN` where the sequence is not yet known — the implementer numbers them consecutively; every other value is exact.
- **Type consistency:** `sdma_arg0/sdma_fields/layer_word` (S1) are what S2's TB and S3's `sld()/sst()/layer()` call; `StateImage.blocks` keys `(kind, layer, head)` match `StateRegion`'s; the `SMEM` grammar is one string in S3 Step 3 and S4 consumes it through the TB unchanged; `tcnt_bank` 13 bits indexed by the tag (S2) matches `STATE_T_MAX = 4096` (S1), `cfg_t[12:0]` and `self.T[8][4]` (S3).
