# S1 — the SEQ ISA v2.1 state-DMA extension: the contract, its two mirrors, and the census

Task S1 of `docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md`
(revision 2, base commit `e905cd3`). Spec:
`docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md` §5 and A1.

S1 writes the ISA down once, mirrors it in the reference and the host, and
builds the instrument that will tie all of it to the RTL. **The RTL half is
RED by design** — `rtl/layer_chan.sv` has no `OP_SLD` on this tree and Task S2
lands it — so the record S1 commits is a RED log with a GREEN ref/host/doc
half beside it and every perturbation CAUGHT.

Labels are the migration spec §0's: **M** measured off the tree, **S**
structural, **D** derived.

---

## 1. What landed

| step | where | what |
|---|---|---|
| 1 | `docs/SEQ_ISA.md:1257-1322` | section **B15**, appended after the second B14 (`docs/SEQ_ISA.md:1017`), and the header's version line (`docs/SEQ_ISA.md:1-2`) |
| 2 | `ref/seq_format.py:335-369`, `:702-748`, `:802-806`, `:854-861`, `:769-775` | the constants, `sdma_arg0`/`sdma_fields`/`layer_word`, the `validate_stream` envelope clause, the opcode names, the disasm arm, the CSR names |
| 3 | `sw/hwmap.py:220-229`, `:190-198`, `:540-565` | the five CSR mirrors, the re-purposed `L_LAYER` comment, the `STATE_*` block and `plan_state` |
| 4 | `evidence/qwen9b/s1/sdma_bits.py` (758 lines) | the census, RED on the RTL half |
| 5 | `evidence/qwen9b/s1/cite_regression.sh` | the citation-regression instrument (§6) |
| fix 1 | `evidence/qwen9b/s1/s2_contract_stub.sv`, `evidence/qwen9b/s1/rtl_contract_probe.sh` | the fixture carrying S2's eighteen anchors, and the probe that proves the census's RED structural (§4.2) |
| fix 1 | `evidence/qwen9b/s1/drift_plan_prerepair.sh` | reconstructs the pre-repair `--plan` verdict instead of remembering it (§6.1) |

### 1.1 B15 as landed (`docs/SEQ_ISA.md`)

| lines | section |
|---|---|
| `docs/SEQ_ISA.md:1257-1261` | the heading and the spec pointer; it states that the file carries two sections numbered B14 and that B15 follows the second |
| `docs/SEQ_ISA.md:1262-1282` | **B15.1** SLD/SST — `arg0={kind[12:11], slot[10], layer[9:5], head[4:0]}`, the kind/layer/head ranges, the three address laws and the three lengths |
| `docs/SEQ_ISA.md:1283-1291` | **B15.2** the LAYER CSR word and the KV slot tag |
| `docs/SEQ_ISA.md:1292-1301` | **B15.3** the five CSRs, and `busy_any` / `busy_cmp` / `cmd_cnt` / LCYC |
| `docs/SEQ_ISA.md:1302-1313` | **B15.4** the six error codes |
| `docs/SEQ_ISA.md:1314-1322` | **B15.5** ordering — the DMA lane, F1, F2, and what DNZ / CONVW sel 2 warm |

The header change is **in place, two lines, no line-count change**
(`docs/SEQ_ISA.md:1-2`), deliberately: 16 documents cite this file by line
and an inserted header line would have shifted every one of them. The
**v1.5 FROZEN TEXT block (`docs/SEQ_ISA.md:58-203`) is byte-identical to
`e905cd3`** — sha256 `1afd2b96…f48d63` on both sides (M).

---

## 2. The constant table — every value, and every source that names it

Read out of the three sources by `evidence/qwen9b/s1/sdma_bits.py`, not
transcribed: the doc is parsed out of B15, the reference is read from its
own module (the bit homes *probed* through `sdma_fields`, the LAYER homes
declared in `layer_word`'s docstring and required to contain what the
encoder packs), the host from `sw/hwmap`. `-` means that source does not
name the constant. Every row below is **M**, printed by
`evidence/qwen9b/s1/002_sdma_bits_refonly.log`.

| constant | ref | host | doc |
|---|---|---|---|
| `op_sld` / `op_sst` | 13 / 14 | - | 13 / 14 |
| `csr_sb_dn` / `sb_kv` / `sb_cv` | 0x64 / 0x68 / 0x6c | 0x64 / 0x68 / 0x6c | 0x64 / 0x68 / 0x6c |
| `csr_sdma` / `csr_sdma_cyc` | 0x70 / 0x74 | 0x70 / 0x74 | 0x70 / 0x74 |
| `csr_layer` | 0x30 | 0x30 | 0x30 |
| `arg0_kind` | [12:11] | - | [12:11] |
| `arg0_slot` | [10:10] | - | [10:10] |
| `arg0_layer` | [9:5] | - | [9:5] |
| `arg0_head` | [4:0] | - | [4:0] |
| `layer_dn_slot` / `kv_slot` / `cv_slot` | [1:0] / [4:3] / [13:12] | - | [1:0] / [4:3] / [13:12] |
| `layer_kv_layer` | [10:8] | - | [10:8] |
| `kind_dn` / `kv` / `cv` / reserved | 0 / 1 / 2 | - | 0 / 1 / 2 / 3 |
| `layer_max_dn` / `layer_max_cv` / `layer_max_kv` | 23 / 23 / 7 | - | 23 / 23 / 7 |
| `head_max_dn` / `head_max_cv` / `head_max_kv` | 0 / 0 / 7 | - | 0 / 0 / 7 |
| `err_e_env` / `e_layer` | 1 / 2 | - | 1 / 2 |
| `err_e_dma_base` / `range` / `axi` / `cold` | 0x10 / 0x11 / 0x12 / 0x13 | - | 0x10 / 0x11 / 0x12 / 0x13 |
| `shift_dn` / `shift_kv` / `shift_cv` | - | 20 / 21 / 17 | 20 / 21 / 17 |
| `shift_dn_head` / `shift_kv_exp` | - | 15 / 20 | 15 / 20 |
| `dn_blocks` / `kv_blocks` / `cv_blocks` | - | 768 / 64 / 24 | 768 / 64 / 24 |
| `dn_heads` | - | 32 | 32 |
| `t_max` | 4096 | 4096 | 4096 |

**Ten values are named by ONE view only**, and the census prints every one
of them as `(one view only)` rather than hiding it, so an unmirrored value
cannot pass as a checked one. All ten are the doc's:

| value | why it is unmirrored |
|---|---|
| `kind_rsvd` 3 | consumed by §2.1's `kind 3 is the reserved code` check |
| `dn_rows` 4096, `dn_rows_per_head` 128, `dn_row_bytes` 256 | consumed by §2.1's DN block arithmetic (they must multiply out to `1<<shift_dn` and to a whole layer) |
| `cv_rows` 8192, `cv_row_bytes` 16 | consumed by §2.1's CV block arithmetic |
| `head_kvhead_hi` 2, `head_kvhead_lo` 1, `head_kv_hi` 0, `head_kv_lo` 0 | B15.1's KV head sub-split `{kvhead[2:1], kv[0]}`. The reference does not declare it: `sdma_arg0` takes a single 0..7 `head` and the split is the RTL's and the emitter's business at S2/S3. What IS tied is the value it implies — `head_max_kv` 7 — which the census derives from these homes and compares against the reference's own accepted maximum. |

**The RTL column is absent on this tree.** `rtl/layer_chan.sv:389-400`
declares layer opcodes 1..12 and stops; the census refuses at the first
missing symbol (§4). The census nevertheless HAS an RTL column for
**eighteen** anchors — the two opcodes, the five CSR word offsets, the six
error codes, the three address shifts `SDMA_SHIFT_DN/KV/CV`, and the ARG0
and LAYER field concats — and §4.2 proves that column works by running the
whole census against a fixture that carries them. The contract S2 must
satisfy is written out in the census's own header,
`evidence/qwen9b/s1/sdma_bits.py:42-71`, and is the plan's S2 localparam
bullet (`docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md:340`).
**When S2 lands, `shift_dn/shift_kv/shift_cv` and every `layer_*` row below
gain an RTL column**; until then the three address shifts and B15.2's LAYER
word are agreed by the host/reference and the doc alone, which is why the
RTL half is the half that is RED.

### 2.1 The arithmetic each document does on its own

Printed by the same log (M):

```
  ok   DN block 32x128x256 B == 1<<20
  ok   DN transfer 4096 rows == whole layer (spec A1.1)
  ok   DN head block == 1<<15
  ok   CV block 8192x16 B == 1<<17
  ok   kind 3 is the reserved code
  ok   the KV exponent side array is inside the KV block
  ok   layer_word packs dn_slot into bits [0] inside its declared [1:0]
  ok   layer_word packs kv_slot into bits [3] inside its declared [4:3]
  ok   layer_word packs cv_slot into bits [12] inside its declared [13:12]
  ok   layer_word packs kv_layer into bits [8, 9, 10] inside its declared [10:8]
  ok   plan_state(0) = {dn:0x0 kv:0x1800000 cv:0x9800000 end:0x9b00000}
  ok   every region base is 64 KiB aligned
  ok   the DN region is 24 MiB
  ok   the KV region is 128 MiB
  ok   the conv region is 3 MiB
```

The four `layer_word` lines are the one place where the reference cannot
prove a field width from its code: a slot is only ever 0 or 1, so bit 1 of
`dn_slot[1:0]` is never set by a legal call. B15.2 gives the RTL two bits so
it can REFUSE a slot above 1 (`E_LAYER`), so `layer_word`'s docstring
DECLARES the layout (`ref/seq_format.py:367`) and the census requires the
code to pack inside what the docstring declares. That is stated here
because it is the one **S** (structural) claim in an otherwise **M** table.

---

## 3. The reference and host mirrors

**`ref/seq_format.py`.** The constants sit directly after `LOFF_DNSB`
(`ref/seq_format.py:324`), where the plan put them:
`ref/seq_format.py:340-348` (offsets, CSR ids, opcodes, kinds, `ERR_CODE`
and its six scalars, `STATE_T_MAX`), the three packers at
`ref/seq_format.py:351`, `:362` and `:366`.

The envelope clause is in **`validate_stream`** (`ref/seq_format.py:702`),
not `validate` (`ref/seq_format.py:547`): ARG0..2 reach a layer command as
CSRWR records AHEAD of the CMD, and `validate` sees one record with no ARGs.
`validate_stream` therefore now tracks the last ARG0/ARG1/ARG2 write
(`ref/seq_format.py:721-728`) and applies B15.1's envelope at each CMD
(`ref/seq_format.py:731-747`). The clause is **unconditional**, unlike the
MVGO SHAPE clause it is modelled on (`ref/seq_format.py:650`, gated on
`shape_isa`): v2.1 streams are the only kind this tree's RTL decodes and the
frozen isa=1 artifacts carry no op 13/14 at all, so there is no generation to
gate on — said in the comment at `ref/seq_format.py:732-735` as the MVGO
clause says its own condition.

The loop variable was renamed `i` → `idx` in the same edit so the new
messages and the existing "PROPOSED opcode" message read the same index
name; the emitted text is unchanged.

`LOP_NAME` gains `13: "SLD", 14: "SST"` (`ref/seq_format.py:822-824`),
`disasm` prints `SLD k=DN slot=0 L=3` (with `kvhead=`/`kv=` on KV only)
at `ref/seq_format.py:854-861`, and `_csr_name` learns the five new CSRs
plus the previously unnamed `L_DNSB` (`ref/seq_format.py:769-775`).

**`sw/hwmap.py`.** The five mirrors sit after `L_DNSB`
(`sw/hwmap.py:220-229`) in the block's own comment style. `L_LAYER`'s
comment (`sw/hwmap.py:190-198`) now states BOTH words — v2.0's
`{kv_slot[10:8], dn_slot[4:0]}`, which is what today's RTL still decodes,
and B15.2's v2.1 word with a pointer to `ref/seq_format.layer_word()` and
to Task S2. The `STATE_*` block and `plan_state()` are at
`sw/hwmap.py:549-656`, beside `plan_weights` (`sw/hwmap.py:654`).

> **Re-anchored 2026-09-04, S3 fix round 1 (I2).** S3 grew this block:
> `plan_state_base` (`sw/hwmap.py:592`), its embedding-table guard, and
> `state_dn_witnesses` (`sw/hwmap.py:619`) sit between the `STATE_*`
> constants and `plan_state` now. The pointer above is to the WHOLE block;
> S1's own two functions are unmoved in substance.

---

## 4. The census: RED, GREEN, and the controls

`evidence/qwen9b/s1/sdma_bits.py`, function by function:
`grab` `evidence/qwen9b/s1/sdma_bits.py:206`;
`load_rtl` `evidence/qwen9b/s1/sdma_bits.py:225`;
`load_ref` `evidence/qwen9b/s1/sdma_bits.py:309`;
`load_host` `evidence/qwen9b/s1/sdma_bits.py:343`;
`load_doc` `evidence/qwen9b/s1/sdma_bits.py:384`;
`_apply_perturbation` `evidence/qwen9b/s1/sdma_bits.py:481`;
`census` `evidence/qwen9b/s1/sdma_bits.py:497`;
`internal` `evidence/qwen9b/s1/sdma_bits.py:521`;
`roundtrip` `evidence/qwen9b/s1/sdma_bits.py:591`;
`red_cases` `evidence/qwen9b/s1/sdma_bits.py:651`;
`control` `evidence/qwen9b/s1/sdma_bits.py:702`.
The RTL anchor table is `RTL_SCALARS` `evidence/qwen9b/s1/sdma_bits.py:172`
(fifteen scalars) and `RTL_FIELD_ANCHORS`
`evidence/qwen9b/s1/sdma_bits.py:200` (the two concats).
It copies three functions from `evidence/qwen9b/g3/isa_bits.py` rather than
importing them — `grab` `evidence/qwen9b/g3/isa_bits.py:223`,
`_apply_perturbation` `evidence/qwen9b/g3/isa_bits.py:284`,
`negative_control` `evidence/qwen9b/g3/isa_bits.py:936` — said in the header
at `evidence/qwen9b/s1/sdma_bits.py:11-17`, with the reason.

| log | command | last line | rc |
|---|---|---|---|
| `evidence/qwen9b/s1/001_sdma_bits_red.log` | `python3 evidence/qwen9b/s1/sdma_bits.py` | `SDMA_BITS: FAIL — rtl/layer_chan.sv has no OP_SLD` | **1 (RED, by design)** |
| `evidence/qwen9b/s1/002_sdma_bits_refonly.log` | `… --ref-only` | `SDMA_BITS(ref-only): PASS` | 0 |
| `evidence/qwen9b/s1/003_sdma_control.log` | `… --ref-only --control` | `SDMA_CONTROL(ref-only): PASS (the gate holds and every perturbation is CAUGHT)` | 0 |

The control log's body, verbatim
(`evidence/qwen9b/s1/003_sdma_control.log`):

```
(unperturbed) the census as it stands                              PASS
doc        docs/SEQ_ISA.md B15.3 moves SDMA_CYC to 0x78         CAUGHT
host       sw/hwmap.STATE_KV_STRIDE halves to 1 MiB             CAUGHT
ref        ref/seq_format.OP_L_SST becomes 15                   CAUGHT
```

Three more perturbations flip an RTL constant — `rtl` (`OP_SLD` → 12),
`rtl-shift` (`SDMA_SHIFT_KV` → 20, a 1 MiB KV stride) and `rtl-layer`
(the LAYER `kv_layer` field → `[10:4]`). None of them can run against
`rtl/layer_chan.sv` until S2 lands the anchors, so `--control` skips exactly
those three under `--ref-only` (`evidence/qwen9b/s1/sdma_bits.py:712-713`,
against the `RTL_PERTURBATIONS` set built at
`evidence/qwen9b/s1/sdma_bits.py:478`). §4.2 runs all six anyway, against a fixture.

### 4.1 The five RED cases, refused through `validate_stream()`

From `evidence/qwen9b/s1/002_sdma_bits_refonly.log`, each run as both an
SLD and an SST (ten refusals):

```
  SLD kind 3 (reserved)            arg0=0x1800 REFUSED (SLD kind 3 is reserved (B15.1))
  SLD DN head 1 (must be 0)        arg0=0x0001 REFUSED (SLD layer 0/head 1 outside kind 0's range (B15.1))
  SLD KV layer 8 (max 7)           arg0=0x0900 REFUSED (SLD layer 8/head 0 outside kind 1's range (B15.1))
  SLD CV head 1 (must be 0)        arg0=0x1001 REFUSED (SLD layer 0/head 1 outside kind 2's range (B15.1))
  SLD arg1 != 0 (reserved)         arg0=0x0000 REFUSED (SLD arg1/arg2 must be 0 (B15.1 reserved))
```

The DN case is **head 1**, not "head 32": head is a 5-bit field, so 32 is
not encodable and refusing it would be a tautology. The words are packed
from the census-agreed bit homes (`evidence/qwen9b/s1/sdma_bits.py:524`),
not from `sdma_arg0`, which asserts on exactly these values by design.

64 random `(kind, slot, layer, head)` sets round-trip `sdma_arg0` →
`sdma_fields` and validate as legal streams, and all 64
`(dn, kv, cv, kv_layer)` combinations round-trip `layer_word` (seed
20260904).

---

### 4.2 The RED is STRUCTURAL, not a broken parser

A census that refuses `rtl/layer_chan.sv` because the anchors are missing
looks exactly like a census that would refuse them if they were present.
So the parser is exercised against
`evidence/qwen9b/s1/s2_contract_stub.sv` — a fixture with the eighteen
`// SDMA_BITS:` anchors the plan gives S2, B15's values, and no
synthesizable content at all — by
`evidence/qwen9b/s1/rtl_contract_probe.sh`, in three parts:

1. **POSITIVE.** `SDMA_BITS: PASS` with all four views populated, and all
   **six** perturbations CAUGHT, `rtl`/`rtl-shift`/`rtl-layer` included.
2. **NEGATIVE.** Each of the eighteen anchors deleted from a copy of the
   fixture in turn; every deletion must produce a `SystemExit` that NAMES
   the missing anchor. An anchor the parser silently skips would prove
   nothing, so all eighteen are shown load-bearing.
3. **THE TREE.** The same census against the real `rtl/layer_chan.sv` —
   S1's committed RED.

`evidence/qwen9b/s1/021_rtl_contract_probe.log`:

```
RTL_CONTRACT_PROBE: PASS (18 anchors each proved load-bearing; the stub is GREEN with every perturbation CAUGHT; the tree is RED)
```

The fixture is reached through the `SDMA_BITS_RTL` environment variable
(`evidence/qwen9b/s1/sdma_bits.py:97-99`); with it unset the census reads
`rtl/layer_chan.sv` and nothing about the committed RED changes.

## 5. The gates that must not move

| log | host | verdict |
|---|---|---|
| `evidence/qwen9b/s1/004_boardfree.log` | snoke | `BOARDFREE_PASS`, `SELFTEST_RCS seq=0 serve=0 chat=0`, **seq_run 2759 / serve 85 / chat_seq 356** |
| `evidence/qwen9b/s1/005_isa_bits_g3.log` | darthplagueis | `ISA_BITS: PASS` |

> **The boardfree counts are 2759/85/356, not the 2758/85/357 the plan
> names, and that was already true before S1.** The plan's Global
> Constraints and `evidence/qwen9b/o3/BOARD_LOCK.md:469` record the O3-era
> counts (`evidence/qwen9b/o3/62_boardfree_committed.log`, tree `77584e9`:
> 2758 / 85 / 357). G3.4 moved them: `evidence/qwen9b/g3/299_boardfree_r2_committed.log`
> (tree `20e1214`) and `evidence/qwen9b/g3/330_boardfree_r3_committed.log`
> (tree `6b1f24d`) both record **2759 / 85 / 356** — the same three numbers
> S1's own run reports. So the gate is UNMOVED, and the plan's expected
> number was stale. **The controller corrected it at `5d273cf`**: the
> Global Constraint now reads `BOARDFREE_PASS 2759/85/356` and names
> `evidence/qwen2b/rd/rd_boardfree.sh` as the runner
> (`docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md:41`), and
> S1's step-5 and S3's/S4's test lines follow it
> (`docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md:77`,
> `docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md:271`).

**The runner is `evidence/qwen2b/rd/rd_boardfree.sh`, not the plan's
`python3 sw/seq_run.py --selftest && python3 sw/chat_seq.py --selftest`.**
Two reasons, both measured: snoke's `python3` has no `numpy`
(`ModuleNotFoundError: No module named 'numpy'` on both scripts), and the
plan's pair omits `serve.py --selftest`, which is where the 85 comes from.
That script is the one that produced every `BOARDFREE_PASS` record
this campaign cites, and it selects `sw/.venv/bin/python` itself.

---

## 6. Citation drift — what S1 moved, what it repaired, and what it did not

S1 inserts ~84 lines into `ref/seq_format.py` and ~28 into `sw/hwmap.py` at
the anchors the plan names, so **every citation into those files below an
insertion moves**. This section is the honest accounting.

### 6.1 The measurement

`o3_cite_drift.py --base e905cd3 --edited
ref/seq_format.py,sw/hwmap.py,docs/SEQ_ISA.md --plan` was run **before** any
`--fix`, as the Global Constraints require. **Its verdict is
state-dependent and there are therefore two committed logs, not one**, and
this is the trap: a repaired citation stops being *stale* and becomes
*already correct*, so re-running `--plan` after a repair reports a smaller
REPAIR and a larger COLLATERAL for the same tree edits.

| log | the tree it describes | verdict |
|---|---|---|
| `evidence/qwen9b/s1/020_cite_drift_plan_prerepair.log` | S1's code edits, **every citing document unrepaired** | `TOTAL      REPAIR 109  COLLATERAL 5` / `O3_FIX_PLAN: UNSAFE — 5 of 114 rewrites …`, 18 citing files |
| `evidence/qwen9b/s1/006_cite_drift_plan.log` | after §6.2's repairs (the committed tree) | `TOTAL      REPAIR 94  COLLATERAL 20` / `20 of 114 rewrites …`, the same 18 files |

The first number is the size of the problem S1 created; the second is what
is left after §6.2. **The 15 that moved from REPAIR to COLLATERAL are 7 + 8**,
and the split is the per-file difference between the two logs rather than an
inference: `docs/SEQ_ISA.md` **7 → 0** — §6.2(a)'s eleven tool rewrites, less
the four whose base line S1 REWROTE rather than moved (§6.4), which stay
UNRESOLVED and never become COLLATERAL — and then §6.2(b)'s hand repairs,
**8** of them: the spec **21 → 16**, the migration plan **3 → 2**,
`evidence/qwen9b/g2/G2C_CHAIN.md` **3 → 2** and
`evidence/qwen9b/g3/G3_4_LAYER.md` **17 → 16**. 7 + 8 = 15 = 109 − 94.
*(Recounted 2026-09-10: this read "the 11 + 7 repairs of §6.2, less the
four", which is 14.)*

`evidence/qwen9b/s1/020_cite_drift_plan_prerepair.log` is produced by
`evidence/qwen9b/s1/drift_plan_prerepair.sh`, which **reconstructs the
pre-repair state rather than remembering it**: a throwaway `git worktree` at
`e905cd3` — every citing document exactly as it was — with only
`ref/seq_format.py` and `sw/hwmap.py` copied in from the working tree, which
is what moved the lines. `docs/SEQ_ISA.md` is deliberately left at `e905cd3`
there, because it is both an edited file and a citing document and its own
citations must be seen unrepaired; B15 is a pure append that names no line
of either code file, and the reconstruction reproducing 109/5 exactly is the
check on that.

### 6.2 What S1 repaired

**(a) `docs/SEQ_ISA.md`, by the tool.** The one citing document in S1's own
pathspec. `--fix --only-docs 'docs/SEQ_ISA\.md'` rewrote **11 citations**;
`evidence/qwen9b/s1/007_cite_drift_verify_seqisa.log` records
`relocated 11 citation(s) checked against the base content and the citing
documents`. Every rewritten line is in the AS-BUILT ADDENDA
(`docs/SEQ_ISA.md:235`, `:304`, `:328`, `:488`, `:693`, `:695`, `:716`) —
**none in the frozen v1.5 block**, whose sha256 is unchanged (§1.1).
*The `--fix` invocation itself was run before the logging discipline was
applied to it and has no log; the `--verify` log above is the reproducible
check of its result, and `git show <this commit>:docs/SEQ_ISA.md` carries
the outcome.*

**(b) Eight citations in four other documents, by hand.** These are the
ones `evidence/qwen_next/spec_cites.py` — the campaign's hard gate —
actually refuses, because they QUOTE a line S1 moved. **Eight is the drift
tool's count**, over the six rows below — two of which repair sibling
pointers inside one statement — and it is the per-file REPAIR reduction
between logs 020 and 006 (§6.1: 5 + 1 + 1 + 1):

| citing line | quotation | was | now |
|---|---|---|---|
| `docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md:109` | `RS_F_DEFAULT = 8` | `sw/hwmap.py:419` | `sw/hwmap.py:438` |
| `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md:239` | `RS_F_DEFAULT = 8` | `sw/hwmap.py:419` | `sw/hwmap.py:438` |
| `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md:2035` | `EMB_ROW_BYTES_DEFAULT` and its three sibling pointers in the same cell | `sw/hwmap.py:411` `sw/hwmap.py:308-319` `sw/hwmap.py:488` `sw/hwmap.py:497` | `sw/hwmap.py:430` `sw/hwmap.py:327-338` `sw/hwmap.py:507` `sw/hwmap.py:516` |
| `evidence/qwen9b/g2/G2C_CHAIN.md:1407` | `RS_F_DEFAULT = 8` | `sw/hwmap.py:419` | `sw/hwmap.py:438` |
| `evidence/qwen9b/g3/G3_4_LAYER.md:1091` | `CHUNK_ROWS = 2048` | `ref/seq_format.py:1127` | `ref/seq_format.py:1211` |
| `evidence/qwen9b/g3/G3_4_LAYER.md:1009-1010` | `on_treset`, `_csr_name`'s `L_TCNT2` (siblings of the same statement) | `ref/seq_format.py:1376` `ref/seq_format.py:703` | `ref/seq_format.py:1460` `ref/seq_format.py:773` |

The sibling pointers in the same statement were repaired with the flagged
one deliberately: the drift tool's own header warns that half-repairing a
citation list "turns one honest stale token into a token that is half
repaired and reads as if it were checked".

`evidence/qwen9b/g3/G3_4_LAYER.md:1168` and `:1500` also name
`ref/seq_format.py:1127` and were **left alone**: they are that document's
narrative record of what an earlier repair round set, not live pointers.

### 6.3 The proof that the repair is complete — and its instrument

`evidence/qwen9b/s1/cite_regression.sh` runs `spec_cites.py` over the 13
documents that cite the edited files, **both sides in one throwaway
worktree** at `e905cd3`: BEFORE is the base worktree untouched, AFTER is
that same worktree with S1's three edited files and four repaired documents
copied in. Both columns therefore share the same "tracked files only"
contamination, which cancels out of the delta — the point of the
instrument, and a real trap: the migration spec reports 0 failures in the
working tree and 19 in a worktree, so a working-tree AFTER against a
worktree BEFORE would have hidden every regression in it.

`evidence/qwen9b/s1/008_cite_regression.log`:

    S1_CITE_REGRESSION: NONE (0 new spec_cites failures)

Before the repairs the same instrument reported **5 new failures in 4
documents** (migration plan +1, migration spec +2, G2C_CHAIN +1,
G3_4_LAYER +1) — the RED that §6.2 closes.

### 6.4 What S1 did NOT repair, and why — now S3's Step 5′

**≈94 citations in 18 documents still name a pre-S1 line of
`ref/seq_format.py` or `sw/hwmap.py`.** They are in range and are not
quoted next to their citation, so `spec_cites.py` accepts them silently —
which is precisely the blind spot `evidence/qwen9b/o3/o3_cite_drift.py`
exists for. S1 did not
sweep them, for three reasons:

1. The tool refuses: `O3_FIX_PLAN: UNSAFE` with non-empty COLLATERAL, and
   its own docstring says such residue "must be repaired BY HAND (or the
   document `--exclude`d), never by another pass".
2. The 18 documents are outside S1's commit pathspec (the task's commit
   block names `docs/SEQ_ISA.md`, `ref/seq_format.py`, `sw/hwmap.py` and
   `evidence/qwen9b/s1/`); rewriting six other tasks' committed gate
   documents is not S1's to do unilaterally.
3. A single clean campaign-level pass at one base is strictly better than a
   partial one: partial repairs create exactly the COLLATERAL that makes the
   next pass unsafe.

**The controller has assigned this pass**: it is now S3's Step 5′,
`docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md:506`, which
reads `evidence/qwen9b/s1/006_cite_drift_plan.log` directly.

**What that pass must know.** Any `--fix` at base `e905cd3` must
`--exclude` the documents S1 already repaired, or it will double-shift them:

    docs/SEQ_ISA.md                                              (11, by --fix)
    docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md     (1, by hand)
    docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md (5, by hand)
    evidence/qwen9b/g2/G2C_CHAIN.md                              (1, by hand)
    evidence/qwen9b/g3/G3_4_LAYER.md                             (3, by hand)

`evidence/qwen9b/s1/007_cite_drift_verify_seqisa.log` ends
`O3_CITE_DRIFT VERIFY FAIL (5 problem(s))`. All five are lines whose
CONTENT S1 rewrote rather than moved, so the line map cannot resolve them.
**All five are UNRESOLVED**; the log prints a SIXTH line, the HALF-MAPPED
range `ref/seq_format.py:729-730`, and the tool does **not** count it —
`FAIL (5 problem(s))` is the UNRESOLVED count alone, and HALF-MAPPED has no
counter of its own. *(Restated 2026-09-10: this said "four UNRESOLVED and
one HALF-MAPPED", which mis-composes the five and credits the tool with a
class it does not tally.)*

| entry | what it is |
|---|---|
| UNRESOLVED `docs/SEQ_ISA.md:693`, `docs/SEQ_ISA.md:695` | the two v1.5 reserved-field rulings, whose embedded `ref/seq_format.py` numbers §6.2(a)'s `--fix` renumbered; cited by `evidence/qwen9b/g3/G3_4_LAYER.md` |
| UNRESOLVED `ref/seq_format.py:703` | inside `validate_stream`, rewritten by the envelope clause; the same document's pointer, repaired by hand to `ref/seq_format.py:773` in §6.2(b) |
| UNRESOLVED `sw/hwmap.py:190` | `L_LAYER`, whose comment S1 rewrote; it is the state-spill plan's own instruction coordinate for this task |
| UNRESOLVED `ref/seq_format.py:730` | the `LOP_NAME` dict's last line, which S1 rewrote to add the two new opcode names; the state-spill plan's own coordinate. This is the fifth of the five, and the END endpoint of the HALF-MAPPED range below |
| **HALF-MAPPED `ref/seq_format.py:729-730`** (printed, NOT counted in the five) | the `LOP_NAME` dict, the state-spill plan's instruction coordinate for step 2. Its END endpoint is gone (S1 rewrote line 645 to add `13: "SLD", 14: "SST"`), so the tool leaves the WHOLE range alone by its all-or-nothing range rule. The dict is now at `ref/seq_format.py:822-824`. |

None of the five is a `spec_cites` failure (§6.3), and four of them are the
state-spill plan's or `evidence/qwen9b/g3/G3_4_LAYER.md`'s own coordinates
for this very task.

---

## 7. Deviations from the task text, recorded

1. **The boardfree runner and its counts** — §5.
   `evidence/qwen2b/rd/rd_boardfree.sh` instead of
   the plan's two-command pair; 2759/85/356 instead of 2758/85/357, unmoved
   and shown to be pre-existing.
2. **`kv_layer[10:8]`, not the `kv_layer[6:4]` spec A1.3 carried when S1
   started.** The plan's revision 2 — the later document, and the one that
   gives B15.2's word in full — writes `[10:8]`, which is where `kv_slot`
   lived under v2.0 and which leaves `kv_slot[4:3]` room below; `[6:4]`
   would have overlapped it. B15.2, `ref/seq_format.layer_word` and
   `sw/hwmap.L_LAYER`'s comment all use `[10:8]`, and **S2 must too**. The
   spec was corrected concurrently, while S1 was running, and now reads
   `kv_layer[10:8]`
   (`docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md:497`) —
   so this deviation is closed; it is recorded because S1's mirrors were
   written against the plan, not the spec's then-current text.
3. **The header version line is an in-place rewrite of
   `docs/SEQ_ISA.md:1-2`**, not an inserted line — §1.1.
4. **`--perturb rtl` is defined but unreachable** until S2 — §4.
5. **The `--fix` pass on `docs/SEQ_ISA.md` has no log of its own** — §6.2(a).

---

## 8. spec_cites, LAST

Run on the committed tree, on `docs/SEQ_ISA.md` and on this document — §9's
last row. The four documents §6.2(b) repaired are checked there too, and
`evidence/qwen9b/g2/spec_cites_selftest_regression.sh` (the checker's own
pinned regression over eight documents) is run beside them because S1's
repairs touch two of the eight.

---

## 9. On the committed tree

Every log below **but `016`** carries `=== tree: 0836ff9` with no `+dirty`
flag; `evidence/qwen9b/s1/016_spec_cites_last.log:3` reads
`=== tree: 0836ff9+dirty` and the last note in this section says why.
`0836ff9` is S1's third commit; the two before it are `ff5e87b` (the ISA,
the mirrors, the census and the §1-§8 gate doc) and `fd8ab55` (§6.2's
citation repairs).

| log | command | verdict | rc |
|---|---|---|---|
| `evidence/qwen9b/s1/010_sdma_bits_red_committed.log` | `python3 evidence/qwen9b/s1/sdma_bits.py` | `SDMA_BITS: FAIL — rtl/layer_chan.sv has no OP_SLD` | **1, RED by design** |
| `evidence/qwen9b/s1/011_sdma_bits_refonly_committed.log` | `python3 evidence/qwen9b/s1/sdma_bits.py --ref-only` | `SDMA_BITS(ref-only): PASS` | 0 |
| `evidence/qwen9b/s1/012_sdma_control_committed.log` | `python3 evidence/qwen9b/s1/sdma_bits.py --ref-only --control` | `SDMA_CONTROL(ref-only): PASS (the gate holds and every perturbation is CAUGHT)` | 0 |
| `evidence/qwen9b/s1/013_boardfree_committed.log` | snoke, `bash evidence/qwen2b/rd/rd_boardfree.sh` | `BOARDFREE_PASS`, `SELFTEST_RCS seq=0 serve=0 chat=0`, **2759 / 85 / 356** | 0 |
| `evidence/qwen9b/s1/014_isa_bits_g3_committed.log` | `ref/.venv/bin/python evidence/qwen9b/g3/isa_bits.py` | `ISA_BITS: PASS` | 0 |
| `evidence/qwen9b/s1/015_cite_regression_committed.log` | `bash evidence/qwen9b/s1/cite_regression.sh` | `S1_CITE_REGRESSION: NONE (0 new spec_cites failures)` | 0 |
| `evidence/qwen9b/s1/016_spec_cites_last.log` | `spec_cites.py` over the six documents S1 touched, then the pinned regression | see below | 0 |

The §1-§8 logs (`evidence/qwen9b/s1/001_sdma_bits_red.log` through
`evidence/qwen9b/s1/008_cite_regression.log`) were produced on the DIRTY
working tree that became `ff5e87b`/`fd8ab55`; what was dirty is exactly the
eight files those two commits carry. Every one of them is reproduced above
on the clean tree with the same verdict.

`evidence/qwen9b/s1/016_spec_cites_last.log` reads, in full:

```
docs/SEQ_ISA.md                                                  SPEC CITES: PASS
evidence/qwen9b/s1/S1_ISA.md                                     SPEC CITES: PASS
docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md         SPEC CITES: PASS
docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md  SPEC CITES: PASS
evidence/qwen9b/g2/G2C_CHAIN.md                                  SPEC CITES: FAIL
evidence/qwen9b/g3/G3_4_LAYER.md                                 SPEC CITES: PASS

SPEC_CITES_REGRESSION PASS
```

**`evidence/qwen9b/g2/G2C_CHAIN.md`'s FAIL is 2 failures, both
PRE-EXISTING and neither S1's**: `evidence/qwen9b/g2/G2C_CHAIN.md:1352` and
`evidence/qwen9b/g2/G2C_CHAIN.md:1361` quote
`pre = rshr64(64'(acc1), 9); // RS_F + CW_F - 12 = 9` against
`rtl/conv4_silu.sv:50`, where that text is not found. The same two are
reported at `e905cd3` (`evidence/qwen9b/s1/015_cite_regression_committed.log`,
before column `FAIL 10` / after column `FAIL 10`), and S1's whole diff to
that document is the single line
`evidence/qwen9b/g2/G2C_CHAIN.md:1407`. S1 raised the count to 3 and put it
back to 2; it did not create the 2 and does not fix them.
*(Updated 2026-09-10, pre-ship documentation chore fix round — two
corrections, neither of them a re-measurement. (i) The two sites above read
1343 and 1352 when S1 wrote them; `2bade57` inserted a nine-line class-B note
above the pair, so they are the 1352 and 1361 written here now. (ii) **G2C's
FAIL is 0 at HEAD, measured 2026-09-10** — the pre-ship documentation chore
closed both of these quotations with the checker's noquote exemption. The
"FAIL is 2" this paragraph reports stands as the record of what S1 measured at
`e905cd3`, not as the state today.)*

**One honest residue.** `evidence/qwen9b/s1/016_spec_cites_last.log` is run
with this section already written, so its tree line reads
`0836ff9+dirty` and the single dirty file is this gate doc — the section
you are reading. Nothing else is modified; the recursion has to stop
somewhere and it stops here, said out loud rather than hidden.

---

## 10. Fix round 1 (FIX_BASE `14c52d3`)

The task review approved S1 and left three Important items and four
same-line minors. What changed, and where:

| item | change | where |
|---|---|---|
| **I1** — §6.1 quoted a `--plan` verdict no committed log carried | the pre-repair verdict is now RECONSTRUCTED, not remembered: `evidence/qwen9b/s1/drift_plan_prerepair.sh` rebuilds the state in a throwaway worktree at `e905cd3` and reproduces `REPAIR 109 COLLATERAL 5` / `5 of 114` exactly. §6.1 now carries BOTH logs with the tree each describes, and says why the two differ | §6.1; `evidence/qwen9b/s1/020_cite_drift_plan_prerepair.log` |
| **I2** — an unlogged "measured with edits reverted" claim | the sentence is deleted; the conclusion rests on `evidence/qwen9b/g3/299_boardfree_r2_committed.log` and `evidence/qwen9b/g3/330_boardfree_r3_committed.log`, which are committed | §5 |
| **I3** — the census tied neither the address shifts nor B15.2's LAYER word to the RTL | five new RTL anchors — `SHIFT_DN`, `SHIFT_KV`, `SHIFT_CV` and the `LAYER_FIELDS` concat (and `_lit` learned the unsized `= 20;` form the shift localparams use) — plus two new perturbations, `rtl-shift` and `rtl-layer`. Eighteen anchors now, and §4.2's probe proves every one load-bearing | `evidence/qwen9b/s1/sdma_bits.py:172-204`, `:464-479`; §2, §4, §4.2 |
| minor 4 | all **ten** `(one view only)` rows are named, with what each is for | §2 |
| minor 5 | "no `+dirty` flag" now says "every log but `016`" | §9 |
| minor 7 | the sixth `--verify` line, the HALF-MAPPED `ref/seq_format.py:729-730`, is named with what it is | §6.4 |
| minor 11 | the PENDING prune is exercised: `spec_cites.py` on the one document citing S1's two landed paths reports them under EXIST, not PENDING | `evidence/qwen9b/s1/025_spec_cites_pending_prune.log` |

Two things the round did NOT change: the ISA (`docs/SEQ_ISA.md` B15 is
untouched) and the two mirrors (`ref/seq_format.py`, `sw/hwmap.py` are
untouched). Every edit is inside `evidence/qwen9b/s1/`.

### 10.1 The round's logs

Produced on the fix-round working tree (`6522972+dirty`; what was dirty is
exactly the files this round's commit carries), then re-run on the committed
tree in §10.2.

| log | verdict |
|---|---|
| `evidence/qwen9b/s1/020_cite_drift_plan_prerepair.log` | `TOTAL      REPAIR 109  COLLATERAL 5`, 18 citing files — the pre-repair verdict, reconstructed |
| `evidence/qwen9b/s1/021_rtl_contract_probe.log` | `RTL_CONTRACT_PROBE: PASS (18 anchors each proved load-bearing; the stub is GREEN with every perturbation CAUGHT; the tree is RED)` |
| `evidence/qwen9b/s1/022_sdma_bits_red_fix1.log` | `SDMA_BITS: FAIL — rtl/layer_chan.sv has no OP_SLD`, rc 1 — the RED, unchanged |
| `evidence/qwen9b/s1/023_sdma_bits_refonly_fix1.log` | `SDMA_BITS(ref-only): PASS` |
| `evidence/qwen9b/s1/024_sdma_control_fix1.log` | `SDMA_CONTROL(ref-only): PASS (the gate holds and every perturbation is CAUGHT)` |
| `evidence/qwen9b/s1/025_spec_cites_pending_prune.log` | `SPEC CITES: PASS` on the state-spill plan, `pending 30` — and **no** entry for `evidence/qwen9b/s1/sdma_bits.py` or `evidence/qwen9b/s1/S1_ISA.md`, which the plan cites eleven times and which now go through EXIST |
| `evidence/qwen9b/s1/026_isa_bits_g3_fix1.log` | `ISA_BITS: PASS` |
| `evidence/qwen9b/s1/027_boardfree_fix1.log` | snoke, `BOARDFREE_PASS`, **2759 / 85 / 356** |
| `evidence/qwen9b/s1/028_cite_regression_fix1.log` | `S1_CITE_REGRESSION: NONE (0 new spec_cites failures)` |

### 10.2 On the committed tree

Every log below carries `=== tree: a65dcab` with **no `+dirty` flag**
(`a65dcab` is fix round 1's commit), except `038`, which is run with this
subsection already written and says so on its own line.

| log | command | verdict | rc |
|---|---|---|---|
| `evidence/qwen9b/s1/030_sdma_bits_red_fix1_committed.log` | `python3 evidence/qwen9b/s1/sdma_bits.py` | `SDMA_BITS: FAIL — rtl/layer_chan.sv has no OP_SLD` | **1, RED by design** |
| `evidence/qwen9b/s1/031_sdma_bits_refonly_fix1_committed.log` | `… --ref-only` | `SDMA_BITS(ref-only): PASS` | 0 |
| `evidence/qwen9b/s1/032_sdma_control_fix1_committed.log` | `… --ref-only --control` | `SDMA_CONTROL(ref-only): PASS (the gate holds and every perturbation is CAUGHT)` | 0 |
| `evidence/qwen9b/s1/033_rtl_contract_probe_committed.log` | `bash evidence/qwen9b/s1/rtl_contract_probe.sh` | `RTL_CONTRACT_PROBE: PASS (18 anchors each proved load-bearing; the stub is GREEN with every perturbation CAUGHT; the tree is RED)` | 0 |
| `evidence/qwen9b/s1/034_cite_drift_plan_prerepair_committed.log` | `bash evidence/qwen9b/s1/drift_plan_prerepair.sh` | `TOTAL      REPAIR 109  COLLATERAL 5` / `O3_FIX_PLAN: UNSAFE — 5 of 114 rewrites …` | 0 (the wrapper's; the tool's own rc 1 is printed in the log) |
| `evidence/qwen9b/s1/035_isa_bits_g3_fix1_committed.log` | `ref/.venv/bin/python evidence/qwen9b/g3/isa_bits.py` | `ISA_BITS: PASS` | 0 |
| `evidence/qwen9b/s1/036_boardfree_fix1_committed.log` | snoke, `bash evidence/qwen2b/rd/rd_boardfree.sh` | `BOARDFREE_PASS`, **2759 / 85 / 356** | 0 |
| `evidence/qwen9b/s1/037_cite_regression_fix1_committed.log` | `bash evidence/qwen9b/s1/cite_regression.sh` | `S1_CITE_REGRESSION: NONE (0 new spec_cites failures)` | 0 |
| `evidence/qwen9b/s1/038_spec_cites_last_fix1.log` | spec_cites over the six documents S1 touched, then the pinned regression | see below | 0 |

The `--ref-only` control's body on the committed tree
(`evidence/qwen9b/s1/032_sdma_control_fix1_committed.log`) is unchanged from
§4: the three `rtl*` perturbations are skipped because that mode does not
load the RTL view, and all three are exercised instead by `033`'s probe,
against the fixture.

**spec_cites, LAST** (`evidence/qwen9b/s1/038_spec_cites_last_fix1.log`):
the same six documents and the same pinned regression as `016`, with the
same verdicts — `evidence/qwen9b/g2/G2C_CHAIN.md`'s FAIL is still the two
pre-existing `rtl/conv4_silu.sv:50` quotations §9 names, and nothing this
round touched can reach them. `038` is run with §10.2 present, so its tree
line reads `a65dcab+dirty` and the single dirty file is this gate doc.
