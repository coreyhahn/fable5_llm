# G3.1 — the 16-bit scratch ISA (SEQ_ISA v2.0)

**Task 7 of the Qwen3.5-9B migration.  THIS IS WHERE THE BYTE-LOCK IS SPENT.**
Spec §4.3 (W3), §7.5 B, §7.6, §8 G3, §9 D-TBUNIT / D-CITE.

Evidence labels follow spec §0: **M** measured, **D** derived, **T** taken
from a cited source, **E** estimated, **S** structural.  Every numeric step
went through `evidence/qwen9b/run.sh` (host, date, tree sha + dirty flag,
cmd, interpreter probe, rc).

| # | log | what |
|---|---|---|
| 00 | `evidence/qwen9b/g3/00_boardfree_baseline.log` | the board-free gate BEFORE any change (snoke) |
| 01 | `evidence/qwen9b/g3/01_isa_bits_pre_v17.log` | `isa_bits.py` FIRST CUT, green on the v1.7 working tree |
| 02 | `evidence/qwen9b/g3/02_isa_bits_negcontrol_pre_v17.log` | its negative control, first cut |
| 03 | `evidence/qwen9b/g3/03_isa_bits_pristine_d2d774b.log` | **the COMMITTED script** against a pristine `git archive d2d774b` tree |
| 04 | `evidence/qwen9b/g3/04_isa_bits_negctl_pristine_d2d774b.log` | its negative control, same pristine tree |
| 05 | `evidence/qwen9b/g3/05_isa_bits_v20.log` | the committed script on the v2.0 tree |
| 06 | `evidence/qwen9b/g3/06_isa_bits_negctl_v20.log` | negative control on the v2.0 tree |
| 07 | `evidence/qwen9b/g3/07_isa_bits_dnstmap_v20.log` | the DNST layout-authority control (0.8B geometry) |
| 08 | `evidence/qwen9b/g3/08_isa_bits_dnstmap_v20_9b.log` | the same control forked at `FABLE5_MODEL=9b` (LNH=32) |
| 09 | `evidence/qwen9b/g3/09_isa_bits_v20_9b.log` | the whole checker at the 9B geometry |
| 10 | `evidence/qwen9b/g3/10_tb_suite.log` | the full Verilator target list, 4 seeds, snoke — SUPERSEDED by 13 |
| 11 | `evidence/qwen9b/g3/11_boardfree_v20.log` | the board-free gate AFTER (snoke) |
| 12 | `evidence/qwen9b/g3/12_spec_cites.log` | `spec_cites.py` on this gate doc, the plan, its own `--selftest`, and the spec |
| 13 | `evidence/qwen9b/g3/13_tb_suite_final.log` | the same, after the DNSB reset fix that re-reading log 10's diff prompted |
| 14 | `evidence/qwen9b/g3/14_boardfree_final.log` | **the gate run** of the board-free gate |
| 15 | `evidence/qwen9b/g3/15_isa_bits_final.log` | **the gate run** of the checker |
| 16 | `evidence/qwen9b/g3/16_tb_suite_gate.log` | the full target list, first-commit tree |
| 20 | `evidence/qwen9b/g3/20_cite_drift_check.log` | fix round 1: the citation-drift RED half, `--base d2d774b` |
| 21 | `evidence/qwen9b/g3/21_cite_drift_fix.log` | the renumbering, 330 citations in 43 documents |
| 22 | `evidence/qwen9b/g3/22_cite_drift_verify.log` | the GREEN half + the residual class it cannot fix |
| 23 | `evidence/qwen9b/g3/23_cite_drift_negctl_check.log` | `--check` negative control — CAUGHT |
| 24 | `evidence/qwen9b/g3/24_cite_drift_negctl_verify.log` | `--verify` negative control — CAUGHT |
| 25 | `evidence/qwen9b/g3/25_cite_drift_doccites.log` | the second drift class (citations INTO `docs/SEQ_ISA.md`) |
| 26 | `evidence/qwen9b/g3/26_cite_drift_doccites_verify.log` | its GREEN half — PASS |
| 27 | `evidence/qwen9b/g3/27_cite_drift_doccites_negctl.log` | its negative control — CAUGHT |
| 28 | `evidence/qwen9b/g3/28_spec_cites_selftest_regression.log` | the `spec_cites` selftest regression — every pinned count unchanged |
| 30-36 | `evidence/qwen9b/g3/30_isa_bits_v20_clean.log` … `evidence/qwen9b/g3/36_isa_bits_negctl_pristine_clean.log` | **on the COMMITTED tree `89bc9b0`**: the checker, both negative controls, the DNST-map control at 0.8B and 9B, and the whole checker at 9B, plus both pristine-tree runs |
| 37 | `evidence/qwen9b/g3/37_tb_suite_clean.log` | **the gate run** — 15 targets x 4 seeds, `tree: 89bc9b0`, no `+dirty` |
| 38 | `evidence/qwen9b/g3/38_boardfree_clean.log` | **the gate run** of the board-free gate, `tree: 89bc9b0` |
| 43 | `evidence/qwen9b/g3/43_spec_cites_clean.log` | **the gate run** of the citation gate on `ef438e6`: spec, plan, this doc, `docs/SEQ_ISA.md`, and the checker's own `--selftest` |
| 44 | `evidence/qwen9b/g3/44_spec_cites_selftest_regression_clean.log` | the pinned-count regression on `ef438e6` |
| 45 | `evidence/qwen9b/g3/45_cite_drift_verify_clean.log` | the drift `--verify` on `ef438e6` |
| 46 | `evidence/qwen9b/g3/46_cite_drift_doccites_verify_clean.log` | the `--doc-cites --verify` on `ef438e6` |
| 47 | `evidence/qwen9b/g3/47_spec_cites_final.log` | the citation gate re-run after §14a was written (`ef438e6+dirty`) |
| 48 | `evidence/qwen9b/g3/48_spec_cites_committed.log` | the same on the fully committed `b5ee593` |
| 50 | `evidence/qwen9b/g3/50_cite_drift_check_r2.log` | **fix round 2**: the drift `--check` with the new HALF-MAPPED class, `tree: 9231326` |
| 52 | `evidence/qwen9b/g3/52_cite_drift_negctl_check_r2.log` | `--check` negative control — CAUGHT |
| 53 | `evidence/qwen9b/g3/53_cite_drift_negctl_verify_r2.log` | `--verify` negative control — CAUGHT |
| 54 | `evidence/qwen9b/g3/54_cite_drift_range_control.log` | **the NEW `--range-control`** — PASS (§13.4) |
| 56 | `evidence/qwen9b/g3/56_cite_drift_verify_r2.log` | the drift `--verify`, `tree: 83ac699` |
| 57 | `evidence/qwen9b/g3/57_spec_cites_r2.log` | **the FINAL citation gate**, `tree: 83ac699` — all four documents FAIL 0, `SELFTEST: PASS` |
| 58 | `evidence/qwen9b/g3/58_spec_cites_selftest_regression_r2.log` | **the FINAL pinned-count regression**, `tree: 83ac699` |
| 59 | `evidence/qwen9b/g3/59_cite_drift_doccites_verify_r2.log` | the FINAL `--doc-cites --verify`, `tree: 83ac699` |
| 62 | `evidence/qwen9b/g3/62_cite_drift_check_r3.log` | **fix round 3**: the drift `--check`, `tree: f2a093e` |
| 63 | `evidence/qwen9b/g3/63_cite_drift_verify_r3.log` | the drift `--verify`, `tree: f2a093e` |
| 64 | `evidence/qwen9b/g3/64_cite_drift_range_control_r3.log` | `--range-control` **with the three out-of-range cases**, `tree: f2a093e` |
| 65, 66 | `evidence/qwen9b/g3/65_cite_drift_negctl_check_r3.log`, `evidence/qwen9b/g3/66_cite_drift_negctl_verify_r3.log` | both pre-existing negative controls — CAUGHT |
| 67 | `evidence/qwen9b/g3/67_cite_drift_doccites_verify_r3.log` | `--doc-cites --verify`, `tree: f2a093e` |
| 68 | `evidence/qwen9b/g3/68_spec_cites_r3.log` | **the FINAL citation gate**, `tree: f2a093e` — all four documents FAIL 0, `SELFTEST: PASS`, `SPEC_CITES_REGRESSION PASS` |
| 69 | `evidence/qwen9b/g3/69_seq_unit_vectors_bytelock.log` | the vector-generator byte-lock: **182 artifacts, 0 differing** over 4 seeds, `tree: f2a093e` |

**Interpreters, recorded because they differ per host (Standing hazards).**
`ref/.venv/bin/python` is a **dangling symlink on snoke** (`test -x` fails;
its interpreter lives under `~/.local/share/uv`, which is not NFS-shared) and
works on darthplagueis.  `/home/cah/.venv/bin/python` exists on snoke only.
`sw/.venv/bin/python -> /usr/bin/python3` works on both.  So: logs 01-09 ran
on **darthplagueis** under `ref/.venv/bin/python`; logs 00, 10, 11 ran on
**snoke**, the TB suite with `VECPY=GENPY=/home/cah/.venv/bin/python` (the
`tb/Makefile` `VECPY` autodetect falls back to the dangling path there,
which is what the override exists for).  `FABLE5_RS_F` was **not exported**
anywhere in this gate (plan A2.5).

---

## 1. The bit budget — M, read out of the RTL, not transcribed

`evidence/qwen9b/g3/isa_bits.py` parses the field slices out of
`rtl/layer_chan.sv` (the four pair wires, the `vec_alu` port map, the
dispatcher's per-opcode assignments, the CONV/CONVW FSM slices) and sums
them against the 96 bits ARG0..2 hold (**S**: three 32-bit CSRs).
**Log 30**, `tree: 89bc9b0` — the committed tree, after fix round 1
widened the kvhead field.  (Logs 05 and 12 were taken at `d2d774b+dirty` and
print the pre-fix `kvhead:1` / KVAP 38 / ATTN 33.  **Every number quoted in
this document is now taken from a log whose `=== tree` line carries a clean
sha**; the `+dirty` logs are kept as the record of the first cut and are
cited only where the text is about that first cut.):

```
command  ARG0  ARG1  ARG2  used  spare  fields
VN         14    32     4    50     46  vn_mode:2, vn_nlog2:4, vn_inf:4, vn_outf:4, vn_eps:1, vn_xrfk:3, a1_lo:16, a1_hi:16
VNW        13    16     0    29     67  vnw_n:13, a1_lo:16
ROPET       0    16     0    16     80  a1_lo:16
ROPE        0    32     0    32     64  a1_lo:16, a1_hi:16
CONVW      30    16     0    46     50  convw_sel:2, convw_first:14, convw_nch:14, a1_lo:16
CONV       28    32     0    60     36  conv_first:14, conv_nch:14, a1_lo:16, a1_hi:16
GATE       16    32    32    80     16  gate_dst:16, a1_lo:16, a1_hi:16, a2_lo:16, a2_hi:16
KVAP        7    32     0    39     57  kvhead:2, kv_expbias:5, a1_lo:16, a1_hi:16
ATTN        2    32     0    34     62  kvhead:2, a1_lo:16, a1_hi:16
ALU        19    32    32    83     13  alu_op:4, alu_len:14, alu_p0:17, alu_srca:16, alu_srcb:16, alu_dst:16
DNST        5    32    32    69     27  dn_head:5, a1_lo:16, a1_hi:16, a2_lo:16, a2_hi:16
DNZ         5     0     0     5     91  dn_head:5
```

**DNST's 101-of-96 problem and its 69-of-96 solution are both visible.**  Six
16-bit pointers plus a 5-bit head is 101; moving the two SCALAR pointers into
the DNSB CSR leaves 69 with 27 spare, exactly spec §4.3's number.  GATE's 16
spare and ALU's 13 also match the spec's table.  The same run on the
**pristine pre-G3 tree** (log 35, `tree: 89bc9b0`) prints DNST at
**94 used / 2 spare**, which
is spec §4.3's "94 of its 96 arg bits" — the checker reproduces the number
the spec argues from before the layout moves.

The budget also refuses two things a table cannot: any two fields of one
command claiming the same `argN[bit]`, and any field reaching past bit 31.

## 2. Emitter CEILINGS against the RTL SLICES that carry them — M

Added because neither the budget nor the round-trip sees it alone: the budget
only reads the RTL, and the round-trip can only exercise values the emitter
agrees to emit.  **A field the RTL decodes at 14 bits but the emitter refuses
at 13 is a self-contradictory ISA.**  Log 30 (`tree: 89bc9b0`), all rows
PASS:

`a1_lo/a1_hi/a2_lo/a2_hi/gate_dst/alu_srca/alu_srcb/alu_dst` 16 b ≥
`ISA_SADDR_MAX-1` = 65535; `vnw_n` 13 b ≥ `VNW_ISA_MAX` = 4096;
`conv_first/conv_nch/convw_first/convw_nch` 14 b ≥ `CONV_FIELD_MAX` = 16383;
`alu_len` 14 b ≥ `ALU_LEN_MAX` = 16383; `dn_head` 5 b ≥ 31;
`kvhead` 2 b ≥ 3; `kv_expbias` 5 b ≥ 31; and
`ref/seq_format.SeqEmitter.ALU_LEN_MAX` == `Mach.ALU_LEN_MAX` == 16383 (the
twin, which synthesizes ALU commands `Mach.alu` never sees).

**Which checkers moved here and which did not — the field/datapath split.**

| checker | was | now | why |
|---|---|---|---|
| `ISA_SADDR_MAX` | 32768 | **65536** | FIELD: ARG halves are 16 b |
| `ARG0_HEAD_BITS` | 4 | **5** | FIELD: `dn_head <= arg0[4:0]` |
| `CONV_FIELD_MAX` | 8191 | **16383** | FIELD: CONV/CONVW channel slices are 14 b |
| `ALU_LEN_MAX` (`Mach`) | 8191 | **16383** | FIELD: `cfg_len` is 14 b |
| `ALU_LEN_MAX` (`ref/seq_format.py`) | 8191 | **16383** | the twin, moved with it |
| `VNW_ISA_MAX` | 2048 (0 encoded 2048) | **4096** | FIELD: `ld_n <= arg0[12:0]`, no escape |
| `VNW_HW_MAX` | — | **2048 (NEW)** | DATAPATH: the vecnorm wbuf depth — **Task 8** |
| `VNW_MAX` | 4096 | 4096 | GEOMETRY (H) — unchanged |
| `ARG0_KVH_BITS` | 1 | **2** | FIELD: `kvhead_r <= arg0[1:0]` |
| `KVH_HW_MAX` | — | **1 (NEW)** | DATAPATH: the KV cache / TCNT banking is 2 deep — **Task 10** |
| `SCRATCH_MAX` | 65536 | 65536 | the ARRAY — unchanged (G2a set it) |
| `DNST_HEAD_MAX` / `KVH_MAX` | LNH−1 / NKV−1 | same | GEOMETRY — unchanged |

**ONE TAXONOMY, APPLIED THE SAME WAY EVERY TIME.**  Each row above is
exactly one of three kinds and the table says which:

* **FIELD** — what an ARG word can carry.  Every one of these is LIFTED here,
  because a field the RTL decodes at N bits and the emitter refuses at N−1 is
  a self-contradictory ISA.  `ISA_SADDR_MAX`, `ARG0_HEAD_BITS`,
  `CONV_FIELD_MAX`, both `ALU_LEN_MAX` twins, `VNW_ISA_MAX`, `ARG0_KVH_BITS`.
* **DATAPATH** — what the RTL behind the field can actually do.  These stay
  where the RTL is and each one NAMES ITS OWNING TASK: `VNW_HW_MAX` (the
  2048-deep vecnorm wbuf — Task 8) and `KVH_HW_MAX` (the 2-deep KV banking —
  Task 10), plus two that need no new name because the RTL guards them
  directly (the 6144-channel conv bank and the 16-head DN banking, both
  Task 10 / G4).
* **GEOMETRY** — what a model may ask for.  Unchanged by an ISA change:
  `VNW_MAX`, `DNST_HEAD_MAX`, `KVH_MAX`, and `SCRATCH_MAX` (the array).

**`VNW_HW_MAX` and `KVH_HW_MAX` are the two NEW names, and they exist for the
same reason.**  Lifting `VNW_ISA_MAX` to 4096, or `ARG0_KVH_BITS` to 2,
without them would have removed the only thing refusing a load the hardware
cannot perform; the refusal now names the DATAPATH and the task that owns it
instead of pretending to be a field.  The first cut of this gate got the
kvhead row wrong — it left `ARG0_KVH_BITS = 1` and called it DATAPATH, which
is the VNW treatment applied backwards, and §14 then counted it among the
field ceilings.  Both are corrected here.  The same shape appears in the RTL
as **five** sim-only `$fatal` envelope guards (§5).

## 3. Encoder ⇄ decoder equivalence — M, three implementations + two delegates

Spec §7.6 counts **five sites, three of them independent implementations** of
the pair layout.  The round-trip covers all five:

* **canonical emitter** — `ref/gen_layer_script.py` (`enc_a1`, `dec_a1_lo`,
  `dec_a1_hi`, `enc_alu_a0`, `enc_alu_a2`, `dec_alu_dst`, `dec_alu_len`,
  `dec_alu_p0`, `enc_isa_saddr`), driven through the REAL `Mach` emitters
  with `Mach.C` intercepted, so every emitter assert runs;
* **the RTL** — decoded from slices PARSED out of `rtl/layer_chan.sv`;
* **`sw/chat_seq.py`** — `_cmd_scratch`, whose returned scratch windows must
  start at the operand addresses;
* **`ref/seq_model.py`** — its open-coded DNST decode, exercised in place on
  the very words the emitter just produced;
* **`tb/scripts/gen_seq_layer_script.py`** — its hand-coded DNST packer, which
  must produce the SAME three words.

Addresses: the five boundaries `[0, 1, 32767, 32768, 65535]` (`ISA_SADDR_MAX`
= 65536) plus 24 seeded random ones; the small fields cycle through the TOP of
each slice on purpose.  **Result (log 30, `tree: 89bc9b0`):
`round-trips: 348 command
encodings x 29 address sets`, PASS.**  Same on the pristine pre-G3 tree at its
own boundaries `[0, 1, 16383, 16384, 32767]` (log 35), and at the **9B
geometry** (log 33, `FABLE5_MODEL=9b` in its own process because
`ref/model_select.py` freezes the tag at import).

**Known limit, stated rather than hidden:** ARG0[12] of the VNW count is not
exercised end to end, because the emitter refuses a count above `VNW_HW_MAX`
= 2048 until G3.2 widens the vecnorm datapath.  The ceiling check (§2) and the
negative control still catch a narrowed field.

## 4. NEGATIVE CONTROL 1 — perturb a field width, require a refusal

`isa_bits.py --negative-control` perturbs ONE field width at a time and
requires the whole checker to refuse each one.  **19 of 19 REFUSED on the
v2.0 tree (log 31) and 19 of 19 on the pristine pre-G3 tree (log 36), both
`tree: 89bc9b0`:**

```
a1_hi a1_lo a1_lo_wide a2_hi a2_lo a2_lo_wide alu_dst alu_len alu_p0
conv_first conv_nch convw_first convw_nch dn_head gate_dst kv_expbias
kvhead vn_nlog2 vnw_n
```

The two `*_wide` cases WIDEN a pair half so it overlaps its partner and are
caught by the budget's overlap check; the seventeen `narrow` cases are caught
by the ceiling check and/or the round-trip.  (`kvhead` joined the table at fix
round 1, with the field itself — §2.  The first cut of this section said 18,
from a run that predates it.)  The failures are specific, not
generic — e.g.

```
FAIL alu_len: the RTL slice is 13 b (max 8191) but the emitter's ALU_LEN_MAX is 16383
FAIL ALU RTL op/len @16383
FAIL dn_head: the RTL slice is 4 b (max 15) but the emitter's 2**ARG0_HEAD_BITS-1 is 31
FAIL DNST RTL head @31 / FAIL DNZ RTL head @31
```

**One perturbation is deliberately NOT in the table, and the reason is in the
source:** widening GATE's ARG0 dst into ARG0's genuinely spare bits is not a
defect — nothing else claims them and every emitted value still decodes — so
requiring a refusal there would be demanding a false positive.  Measured: the
checker stays silent on it.

**The checker also refused the first thing that actually changed.**  The
first v2.0 run's
first attempt failed with
`conv_first: pattern 'cw_ra <= (arg0\[[0-9:]+\]) \+ cvi;' not found` — the
RTL had gained an explicit width cast onto the narrower bank-address
register.  A missing anchor is a HARD FAILURE by construction, so the parser
cannot silently degrade into checking nothing.

## 5. NEGATIVE CONTROL 2 — the DNST layout-authority assert

Spec §4.3 S3 is explicit that the obvious mechanization is worthless: *"a
self-consistency assert ('the `a_dec` I emitted equals the `a_dec_base` I
programmed') passes while both sides are wrong"* and would have sailed through
the `GD + 16 + h` aliasing G2a fixed, because base and pointer derive from the
same literal.

**So the assert lives in `Mach.dnsb` and compares the base pair against the
WRITER** — `Mach.gate_dst`, the dst the GATE command that POPULATES beta|decay
actually carried.  `isa_bits.py --dnst-map` runs it (logs 32 and 34, both
`tree: 89bc9b0`):

| case | 0.8B (LNH=16) | 9B (LNH=32) |
|---|---|---|
| the tree's own map (`beta_base`, `decay_base`, GATE dst) | **ACCEPTED** (3136, 3152, 3136) | **ACCEPTED** (12384, 12416, 12384) |
| `decay_base` off by one | REFUSED | REFUSED |
| `decay_base` at the WALL-17 literal 16 rather than LNH | REFUSED | **REFUSED** — this is the real wall-17 shape, and only the 9B run makes it real |
| `beta_base` off by one | REFUSED | REFUSED |
| the beta\|decay split moved (halves swapped) | REFUSED | REFUSED |
| the GATE writer moved and the map did not | REFUSED | REFUSED |

A control that fires on a healthy layout proves nothing either, which is why
the healthy row is checked in the same run.

**Sequencing, which spec §4.3 says is not optional.**
`tb/scripts/gen_seq_layer_script.py`'s `m_gate` — the reference model this
assert is anchored to — was itself a §7.5-D defect, hard-coding
`np.zeros(32)`, `range(16)` and `out[16 + h]` for LNH=16.  **It was
generalized to `LR.LNH` FIRST**, with a length assert on its four inputs, and
the negative control above was run against the generalized version.

## 6. The RTL datapath envelope — five new sim-only guards

The ARG FIELDS are now v2.0's full width, but three datapaths behind them are
still pre-9B and G3.2/G3.4/G4 own widening them.  Until they do, an
out-of-envelope value must be LOUD rather than aliased, so
`rtl/layer_chan.sv` gained five `` `ifndef SYNTHESIS `` `$fatal`s on command
dispatch: DNST/DNZ head ≥ 16 (the DN banking is 16 heads), CONV and CONVW
reaching past the 6144-channel conv bank, VNW length above the 2048-deep
vecnorm wbuf, and KVAP/ATTN kvhead ≥ 2 (the KV cache and TCNT banking is 2
deep).  Their datapath slices are `dn_head_hw = dn_head[3:0]` and
`kvhead_hw = kvhead_r[0]`, named so the ISA field and the bank address are
never confused for each other.  **These are simulation gates, not silicon protection** — the
feasibility study's standing hazard (spec §2.10) is that almost every guard
here is sim-only.

## 7. The TB family-B census (spec §7.5 B) — a disposition per row

**Line numbers in the left column are the spec's, i.e. PRE-G3**, unless the
row says otherwise: this change moved almost every one of them, and rewriting
them to the post-G3 values would make the census unreadable against §7.5.
Where a post-G3 line is worth naming it is named explicitly.

| site | what it assumed | disposition |
|---|---|---|
| **`tb/tb_seq_unit.sv:967`** pre-G3, the golden-MEM comparison — **D-TBUNIT** | a 15-bit truncation INSIDE a checker, with no range guard at the parse site | **FIXED by copying tb_seq_chip.sv's fix, not re-inventing it**: a MAXMEM localparam of 65536 with MEMAW derived from it by clog2, the MEM parse site given both the count guard and the address-range guard, and the checker slice taken from MEMAW — derived, so only the one localparam ever moves again. Now at `tb/tb_seq_unit.sv:996` |
| `tb/tb_seq_unit.sv:553-563` + the read-channel twin `:569-573` | the 32767 scratch bound and the slot-6/7 layer-window test | **FIXED**: slots 8..11, bound `MAXMEM - 1`, `LAYB_BASE` localparam added |
| `tb/tb_seq_unit.sv:359`, `:773` (EMB row 2048 B) | the EMBLOG2 reset value every pre-R-b vector relies on | **NOT THIS TASK.**  It is spec §5.3's `EMB_ROW_LOG2`, which §7.5 E says "would move a golden if it landed here".  Left with the owning task |
| `tb/seq_stub_layer.sv:120`, `tb/seq_stub_layer.sv:122`, `tb/seq_stub_layer.sv:151`, `tb/seq_stub_layer.sv:279`, and the latent 14-bit increment at `tb/seq_stub_layer.sv:283` (these five did NOT move) | a 32768-word scratch model, three 15-bit address signals, and a 14-bit increment into a 15-bit register | **FIXED**: the model is 65536 words, sptr/rb_addr/wb_addr are 16 bits, the s_axib addresses 18, and all four pointer increments are 16-bit — the latent one included |
| `tb/tb_layershim_c.sv:50,56` `[16:0]` AXI byte address | one bit short at 16-bit | **FIXED**: `[17:0]`, and the two `17'(base*4)` casts with them |
| `tb/tb_layershim_c.sv:279-306`, `:335` — both `32768 - n` placements | the T3/T5 layout and the top-of-window bursts | **FIXED**: one `SCR_WORDS = 65536` localparam, every placement derived from it; case 0 pins the burst at the NEW top and case 1 at the OLD 32K top, so the R-b/G3.1 boundary is covered too |
| **`tb/tb_layershim_c.sv:406` and `tb/tb_layershim_c.sv:584`** (pre-G3 line numbers) | **A ROW THE CENSUS DID NOT LIST.** The T3 and T4 ALU kicks hand-packed ARG1 with a 14-bit shift and ARG2 with a 17-bit shift — a v1.7 layout written out by hand | **FIXED to 16-bit shifts on both.**  Found the expensive way: under v2.0 the ALU dst decoded as 8192, which is the victim region T3 checks for a blocked write, so the ADD scribbled over it and the failure printed as a landed blocked write — a wrong-command bug wearing a fabric bug's clothes |
| `tb/tb_seq_chip.sv:76`, its scratchpad-depth localparam | **the good example** — everything downstream derives from it | **FIXED**: one line, 32768 to 65536.  Its two MI address buses widened from 17 to 18 bits with the fabric |
| `tb/tb_vecalu_diff.sv:78-80`, the 15-bit new-side address buses against the frozen 14-bit legacy copy (now `tb/tb_vecalu_diff.sv:83-85`) | "the extra bit is always 0" | **FIXED to 16 bits, and the argument RESTATED**: the stimulus still stays inside the legacy's 16K range so the extra TWO bits are always 0, and the comment now says explicitly what the differential does NOT cover (lengths above 4095, addresses above 16383 — those are tb_vec_alu's directed cases).  Its new-side scratch model grew from two to four times MEMW so the array index width matches the port width; a narrower array truncates the address in simulation and would hide the aliasing this TB is blind to by construction |
| `tb/tb_vec_alu.sv:31`, `tb/tb_vec_alu.sv:33`, `tb/tb_vec_alu.sv:112`, `tb/tb_vec_alu.sv:126`, `tb/tb_vec_alu.sv:490`, `tb/tb_vec_alu.sv:516` (pre-G3 lines) — 15-bit cfg buses, a 32768-word scratch model, and the R-c long-length case | the 32K scratchpad and a destination parked at 16384 | **FIXED**: the cfg and port addresses are 16 bits, the scratch model is 65536 words, and the long-length case is re-based to 12288 elements (the 9B FFN) with its destination at 40960 — the TOP half of the 64K scratchpad, so the 16-bit address and the 14-bit length are exercised together |
| **`tb/tb_vec_alu.sv:29`**, the TB's own length bus (now `tb/tb_vec_alu.sv:33`) | **a new finding inside a listed file**: 13 bits, caps at 8191, breaks at FFN=12288 | **FIXED to 14 bits.**  Wall 3's TB twin; the DYNQ8 scan-reach case now plants its max at index 10000, past BOTH old truncation points, and compares against the 13-bit prefix (4096) rather than the 12-bit one (2048) |
| `tb/tb_burst_fabric.sv:320`, the layer window base (now `tb/tb_burst_fabric.sv:327`) | 128 KiB at slot 6, colliding with the next slot at 256 KiB | **FIXED to slot 8**, with a named byte address for the w=65535 word.  The mvchan base expression does NOT move — those windows are unchanged.  T3's decode-hole probe grew 3 holes to 6 (slot 5, R-b's own slot 6, slot 7, and 0xC_0000 just past the new window), so the fabric's decode-error count re-pins 6 to 12 |

**Rows the census did not have, found and fixed here** (beyond the
`tb_layershim_c` ARG packing above):

* `tb/seq_burst_fabric.sv` — the 1x5 fabric MODEL decoded layer_0 as
  "slot 6 or 7" with `MAW = 17`.  Now slots 8..11 (`s_awaddr[19:18] == 2`)
  with `MAW = 18`, and the hole test widened to `[31:20]`/`[19]`.
* `tb/tb_seq_unit.sv`'s canonicalisers for burst writes and reads — they
  masked the window slot with a 3-bit mask, so an address at slot 8
  canonicalised to slot 0 and the very first LDC beat compared against 0x24
  instead of the layer SWIN address.  Now a 4-bit mask over slots 8..11.
* `rtl/seq_unit.sv`'s LDC/EMB scratch-window `$error` bound, 32768 -> 65536.
* `tb/tb_topk.sv` — two `17'd0` `s_axib` tie-offs and three hand-coded
  `<< 17` / `<< 14` ARG packings.
* `tb/tb_layer_chan.sv` — two `17'd0` tie-offs, plus the new `B` record.

**`tb/scripts/gen_seq_layer_script.py`'s high-half map re-derives at 16-bit.**
The block moved `0x6000 -> 0xE000`, which has BOTH new top bits set, so there
are now **two** fold-down sentinel images (`−0x8000` at 0x6000 and `−0x4000`
at 0xA000, with different patterns so a fold into the wrong image is still a
mismatch) and **two** for the top-of-scratch region.  `B_TOP` is the last 8
words of the **64K** scratchpad (0xFFF8), `B_TOPW` 0xFFF0.  Sentinel count
1296 -> **2592**.  The DNST probes are re-expressed through DNSB: each one
programs ONE half of the base pair high and the other low, which preserves the
asymmetry the R-b block was built around.  `m_gate` is generalized to LNH (§5).

**`tb/scripts/gen_seq_unit_vectors.py`'s ALU packer (spec §7.6 C) is
REWRITTEN, not widened.**  It was 14-bit with no bit-14 scatter at all, so the
live seq_unit vectors never named a scratch word above 16383.  It now calls
the canonical `enc_alu_a0`/`enc_a1`/`enc_alu_a2`, and **the gap it left is
CLOSED rather than moved**: a directed high-half case `alu_cmd(2, 12288,
0x0100, 0, 0, 0xF800)` (srca LOW / dst HIGH, and a length that uses the 14th
count bit) plus an `LDC` whose destination is `0xF000`, which is what drives
`seq_unit`'s `bulk_dst` and `seq_movers`' `scrbaddr`.  Its four `& 0x7FFF`
SPTR/MOVX/MOVY/LDC masks went to `& 0xFFFF`.

**Not mined:** `tb/scripts_scratch/` (pre-R-b, `SCR_WORDS = 16384`, not a
migration site and not a reference).

## 8. The Verilator suite — 4 seeds, snoke, one obj_dir per target

Log **16** (the gate run), `rc: 0`, **252 PASS lines, zero `FAIL` /
`%Error` / `%Warning` / `Fatal`**.  Logs 10 and 13 are the identical run at
two earlier states of the working tree, both green; the suite was re-run
each time self-review changed a source file (the two new DNSB registers were
missing from `layer_chan`'s CSR reset branch, where every other CSR is; and
`ref/seq_format.py`'s `_cmd` gained an assert that an XRF-INDIRECTED ARG2
carries no `p0[16]`, because v2.0 splits `cfg_p0` across ARG0[18] and
ARG2[15:0] and the runtime add reaches only ARG2 — a question v1.7, with the
whole 17-bit p0 in ARG2, could not raise).  Log 16 is the one this gate rests on:

| target | seeds / sweeps | result |
|---|---|---|
| `tb_seq` | 4 seeds + 7 error vectors + 6 micro + 4 repack | PASS |
| `tb_seq_guard` / `tb_seq_lat` / `tb_seq_sideband` / `tb_seq_burst` | the full vector set at LAT/BLAT sweeps | PASS |
| `tb_seq_offifo` | 3 depths x {axil, blat 0, blat 8} + 24 race runs + 8 stream races + depth self-test | **PASS** — see §9 |
| `tb_layershim_c` | 4 seeds, T1..T8 | PASS |
| `tb_bfab` | 4 seeds x blat {0,4,8} = 12 | PASS |
| `tb_vec_alu` | 4 seeds + the `+amaxlong` run | PASS |
| `tb_vecalu_diff` | 4 seeds read-first + 2 write-first/`+coll_fatal`/`+cfgscramble` | PASS |
| `tb_layer_chan` | 4 seeds | PASS — **see the re-base below** |
| `tb_seq_layer` | 4 seeds | PASS |
| `lint_seq`, `lint_seq_unit`, `lint_seq_burst` | `-Wall`, Verilator 5.020 | clean |

Totals in the log: `SEQ PASS` 145, `TB_BURST_FABRIC PASS` 12,
`TB_LAYER_CHAN PASS` 8 (4 `layerv2_s*` + 4 `seqlayer_s*`),
`TB_LAYERSHIM_C PASS` 4, `TB_VEC_ALU PASS` 5, `TB_VECALU_DIFF PASS` 6,
`TB_SEQ_OFFIFO OK` 1.

`tb_layer_chan` reports `752 cmds, 76941 checks bit-exact` on every seed, and
it is the ONLY target that drives CONVW/CONVZ/CONV/KVAP/ATTN/ROPE/ROPET
against the real `layer_chan` — i.e. the widened channel fields and the DNSB
decode, end to end.

> **`tb_layer_chan` IS RE-BASED, AND THIS IS THE BYTE-LOCK BEING SPENT.**
> Its `tb/scripts/layer_s*.txt` set is COMMITTED pre-Phase-1A evidence whose
> `C` records carry v1.7 (in fact pre-R-b) ARG words: `C 5 4000000 ...` means
> `nch = 2048` under v1.7's `nch = arg0[27:15]` and `nch = 1024` under v2.0's
> `arg0[29:16]`, so the RTL now decodes them as DIFFERENT COMMANDS.  The
> `tb/Makefile` fence said they "must keep passing UNMODIFIED (nothing in the
> RTL changed)"; the RTL ISA HAS now changed, so that sentence is false and
> the files stay as the RECORD of what stage 3/4 ran, not as a live gate.
> The target now depends on `layer_v2_scripts`, which regenerates the same
> coverage with the CURRENT generator (random weights, no checkpoint, ~64 s
> for 4 seeds) into gitignored `tb/scripts/layerv2_s*.txt`.
>
> **THE TRADE, STATED SO IT IS NOT DISCOVERED LATER.**  `tb_layer_chan` used
> to gate the RTL against a FROZEN artifact produced by a DIFFERENT generation
> of the emitter; it now gates it against `layerv2_s*.txt` regenerated by the
> very `ref/gen_layer_script.py` this task rewrote.  A same-generator
> regression cannot catch an encoder and a decoder that are wrong in the same
> direction — that independence now rests entirely on
> `evidence/qwen9b/g3/isa_bits.py`, which decodes the RTL by PARSING it and
> never asks the emitter what the layout is (§1, §3).  Accepted under U4
> (there is no frozen stream to preserve); it just has to be said.
>
> **The same is true of every other target that replays a committed v1.7
> artifact — `tb_token`, `tb_chain`, `tb_model_*`, `tb_seq_chip` — and they
> are NOT re-based here.** They need the real checkpoint and belong to the
> task that regenerates the 9B artifact chain.  The `tb/Makefile` fence
> records this so the next person does not rediscover it in a sim log.

**`evidence/qwen2b/rc/t4_widen_gates.sh` was NOT used as the driver**, though
it is the right shape: its target list includes `tb_token`, which replays a
committed v1.7 artifact and cannot pass after this change.  The brief's own
target list was run instead, by name.

## 9. `tb_seq_offifo` — the test is GREEN and the WARNING is what was stale

The `tb/Makefile` printed, ahead of the directed push/pop race section, that
it *"FAILS on `rtl/seq_unit.sv` as of 2026-08-11 … PRE-EXISTING, also present
at HEAD"*.  **It is not present at HEAD, and the disposition is neither of
the two an earlier revision of the plan offered.**  Verified:

* the recorded fix's AFTER side is in the tree — `rtl/seq_unit.sv:1342`
  carries the unconditional `if (csr_of_pop) of_rp <= of_rp + 7'd1;` and
  `rtl/seq_unit.sv:1624` the conditional `csr_of_pop <= (of_cnt != 7'd0);`,
  both matching `evidence/rung4/S6_out_fifo_pop_race.patch`'s `+` lines;
* `git log ec4216d..HEAD -- rtl/seq_unit.sv` is **0 commits** (`ec4216d` is
  the R-b full-sim-gate commit);
* **it was RUN BY NAME** — `evidence/qwen2b/rc/t4_widen_gates.sh` does not
  include it, which is how a stale warning survives a whole campaign — and
  it is green: `TB_SEQ_OFFIFO OK: 3 depths x {axil, blat 0, blat 8} + 24 race
  runs + 8 stream races + depth self-test`.

**So the stale echo is DELETED and the patch is NOT re-applied** — force
applying it would revert the conditional strobe and REINTRODUCE the
token-loss race.  A comment in its place records the verification.

*Carried honestly:* all 32 race runs print `NOTE: no push/pop coincidence at
+ofphase=N (this run did not exercise the race)`.  That is **unchanged from
the recorded gate** — `evidence/rung4/gate_seq_offifo.log` contains the same
32 NOTEs — so it is a pre-existing property of the stimulus, not something
this change caused, and the race remains covered by the depth/overflow cases
rather than by a witnessed coincidence.

## 10. The board-free gate and the selftest re-pin

| | baseline (log 00) | after (log 14; log 11 is the identical earlier run) |
|---|---|---|
| `seq_run.py --selftest` | 2758 passed, 0 failed | **2758 passed, 0 failed** |
| `make serve_test` | 85 passed, 0 failed | **85 passed, 0 failed** |
| `chat_seq.py --selftest` | 357 passed, 0 failed | **356 passed, 0 failed** |
| verdict | BOARDFREE_PASS | **BOARDFREE_PASS** |

**Every check whose expected value moved, named:**

`chat_seq --selftest` **[17] S7 layout** is the only section affected, and
only its second half.  Measured, not assumed: the **eight head-tail checks
are UNCHANGED and still run**, because every one of them comes from RECORD
fields (`MOVX`/`MOVY` `addr_lo`), not from ARG words — a probe over the frozen
template decoded the head tail identically under both encodings (write starts
`{4096}`, max end `8192`, reads below STG `[(2048, 1024)]`).

The **three full-body checks** did not survive, and re-pinning them would have
been worse than deleting them:

* *"the LAST write into x8 in the whole body is the DYNQ8 at 15531"*
* *"no record at or after the lite cut writes x8 (S6 relies on it)"*
* *"the x8 producer really is an ALU DYNQ8 with dst = 0x800"*

They walk the whole full body with `scratch_accesses`, i.e. they DECODE THE
LAYER ARG WORDS of `tb/scripts/w4/model_v2_s1.e` — a SEQ_ISA v1.7 artifact
this tree can no longer speak (spec §8 G3: no v1.7 decoder path on main).
Measured on the frozen template: **3212 of 14740 body records decode
differently**, and `touch[-1]` moves 15531 -> 15448.  Re-pinning to 15448
would look like a proof and be one only of the decoder's self-consistency.

**Disposition — MOVED, not deleted.**  Two checks replace the three:

1. the template is pinned as a v1.7 artifact and the tree as v2.0 —
   `TEMPLATE_ISA_VERSION == 1 and SF.SEQ_ISA_VERSION == 2` (both new,
   single-valued constants with no behaviour attached);
2. **a v1.7 DNST is REFUSED rather than silently mis-decoded** — the decoder
   raises because a v1.7 stream carries no DNSB write, which is checked with
   `_refuses(...)` over the same record slice the retired checks walked.

The retired numbers are recorded HERE and reproduce on any pre-G3 checkout —
which is exactly where `build_034`/`build_035` are served from.  Net −1 on the
pass count (3 removed, 2 added), 357 -> 356.

**WHAT THIS COMMIT COSTS THE 0.8B AND 2B GEOMETRIES, in one paragraph.**
After G3.1, main's `sw/chat_seq.py` and `sw/serve.py` **cannot drive
`build_034` or `build_035`**.  Those bitstreams decode SEQ_ISA v1.7 and their
artifacts encode it; this tree emits and decodes v2.0 only, and there is no
v1.7 path on main by ruling (spec §8 G3, plan Task 4 step 2 — no dual-encoding
mode).  The 0.8B and 2B geometries therefore **stay served by their frozen
bitstreams from a PRE-G3 CHECKOUT** — the `grok46_llm/fable5` worktree — and
that is the intended, recorded consequence of spending the byte-lock here, not
a regression to fix.  `sw/serve.py` is UNCHANGED by this commit and is named
explicitly because a reader looking for the chat front end looks there first;
it imports `chat_seq`'s decoder and inherits the consequence rather than
carrying it.  `sw/chat_seq.TEMPLATE_ISA_VERSION` (1) and
`ref/seq_format.SEQ_ISA_VERSION` (2) are the two constants that say so in
code.

**`evidence/qwen2b/rc/t4_bytes_unmoved.sh` is RETIRED BY DESIGN.**  It asserts
that emitted artifact bytes have not moved; G3.1 is where the byte-lock is
SPENT, so it must now fail and that is the intended outcome, not a
regression.  The pin it was protecting is recorded in
`evidence/qwen9b/g2/FINAL_BYTELOCK.md` (Task 4's), which stays as the record
of what the 0.8B/2B artifacts contain.  Nothing in this tree runs it.

## 11. Carried forward from G2c, not re-measured

**The LM head's packed W4 g128 footprint is 524,451,840 B = 500.2 MiB at
wid 248**, `LAYOUT_ILV`, `chunk_rows` 2048, base `0x452b0000` on every channel
under the nch=4 repack.  **(T** — `evidence/qwen9b/g2/G2C_CHAIN.md`'s handoff
to Task 7, which says to carry this number forward rather than measure it
twice.**)**

## 12. Nothing — the numbering skips it, deliberately

This gate document ran §11 straight into §13.  Nothing was ever written as
§12 and nothing cites it; the gap is a numbering artefact of the first cut.
It is recorded here rather than closed by renumbering, because §13, §13.1 —
§13.5, §14, §14a and §15 are cited **by section number** from other gate
documents, from `docs/QWEN35_NEXT_FEASIBILITY.md` and from the migration
spec, and a renumber would silently break every one of those pointers for
the sake of a cosmetic.  *(Added 2026-09-10, pre-ship documentation chore.)*

## 13. `spec_cites.py` — the citation drift this task caused, closed

**The first cut of this section said "FAIL, 19 QUOTE failures". That was
wrong: the cited log prints `FAIL 24`, and its own echo header repeated the
wrong number.** Both are corrected here and every one of the 24 is
re-classified and dispositioned. Source of truth:
`evidence/qwen9b/g3/12_spec_cites.log:173`.

**Measured, not assumed:** on the PRE-G3 sources the same document is
`FAIL 0` (651 exist / 477 range / 66 quote). Every one of the 24 is a
citation into a file this task edited.

### 13.1 The 24, re-classified

**Class A — the source MOVED** (*"present … but NOT within 6 lines"*).
Disposition: **RENUMBER, never exempt** — the spec's own §7.6 says an
exemption *"is for source that no longer exists, not for a citation that has
merely moved"*. Mechanized, not hand-edited:
`evidence/qwen9b/o3/o3_cite_drift.py --base d2d774b`.

| # | spec line | quotation | cited (was → now, re-anchored to HEAD) | disposition |
|---|---|---|---|---|
| 1 | spec line 216 | `HEAD_LOGIT_EXP0 = head_logit_exp0()` | 321 → `sw/chat_seq.py:360` | RENUMBERED (A2.3 site; text unchanged — §13.5) |
| 2 | spec line 219 | `want_exp0 = head_logit_exp0(self.head.spec.rs_f)` | 2217 → `sw/chat_seq.py:3233` | RENUMBERED (A2.3) |
| 3 | spec line 222 | `head_logit_exp0(7) == HEAD_LOGIT_EXP0 + 1` | 4282 → `sw/chat_seq.py:5483` | RENUMBERED (A2.3) |
| 4 | spec line 786 | `logic [10:0] vn_waddr;` | 314 → `rtl/layer_chan.sv:537` | RENUMBERED; the quotation is also stale in CONTENT — G3.2 widened the counter and the line now reads `logic [11:0] vn_waddr;` |  <!--cites:noquote-->
| 5 | spec line 874 | `M.dnst(h, QNS, KN, v_src, …)` | 1330 → `ref/gen_layer_script.py:2019` | RENUMBERED |
| 6 | spec line 895 | `for h in range(LR.LNH):` | 1313 → `ref/gen_layer_script.py:2002` | RENUMBERED |
| 7 | spec line 1081 | `logic signed [15:0]` | 280 → `rtl/layer_chan.sv:503-504` | RENUMBERED |
| 8 | spec line 1325 | `KVH_MAX = _KVH - 1` | 726 → `ref/gen_layer_script.py:1075` | RENUMBERED (G3.4 moved it again) |

> **RE-ANCHORED 2026-09-10 (pre-ship documentation chore).** The `now` column
> names **HEAD**, not the tree this G3.1 pass ran against: every one of the
> eight moved again at G3.2, G3.4 or S3, and six of them were failing
> `spec_cites` on this document. The values the G3.1 pass itself wrote, kept
> here as the record of what it did, were
> `sw/chat_seq.py:353`, `sw/chat_seq.py:2564` and `sw/chat_seq.py:4944` for
> rows 1-3;
> `rtl/layer_chan.sv:432` for row 4 and `rtl/layer_chan.sv:398-399` for row 7;
> and `ref/gen_layer_script.py:1491`, `ref/gen_layer_script.py:1474` and
> `ref/gen_layer_script.py:799` for rows 5, 6 and 8.

**Class B — the source was DELETED** (*"not found in any cited file"*).
Disposition: the spec's own precedent — a **dated boxed note per affected
section** saying the rows are PRE-G3.1 and kept as the record,
`<!--cites:noquote-->` on each such row, and the **post-G3.1 landmark named in
§15 below**, which is where a reader goes instead. **No spec text is deleted
or struck (§0).**  The `quotation` column below is exempted for the same
reason the spec rows are — it quotes the deleted source on purpose.

| # | spec line | quotation | post-G3.1 landmark (§15) |  <!--cites:noquote-->
|---|---|---|---|
| 9 | spec line 789 | `ld_n <= arg0[10:0]` | `rtl/layer_chan.sv:1242` |  <!--cites:noquote-->
| 10 | spec line 807 | `logic [14:0] sa_addr, sb_addr;` | `rtl/layer_chan.sv:400` |  <!--cites:noquote-->
| 11 | spec line 809 | `SCR_WORDS = 32768` | `rtl/seq_movers.sv:199` |  <!--cites:noquote-->
| 12 | spec line 1313 | `input wire [12:0] cfg_len` | `rtl/vec_alu.sv:112` |  <!--cites:noquote-->
| 13 | spec line 1313 | `.cfg_len(arg0[16:4])` | `rtl/layer_chan.sv:797` |  <!--cites:noquote-->
| 14 | spec line 1314 | `logic kvhead_r;` | `rtl/layer_chan.sv:513` |  <!--cites:noquote-->
| 15 | spec line 1314 | `kvhead_r <= arg0[0];` | `rtl/layer_chan.sv:1210` |  <!--cites:noquote-->
| 16 | spec line 1316 | `if (cvi == arg0[25:13])` | `rtl/layer_chan.sv:1534` |  <!--cites:noquote-->
| 17 | spec line 1832 | `u_layer.smem[exp_mem_a[i][14:0]]` | `tb/tb_seq_unit.sv:997` |  <!--cites:noquote-->
| 18 | spec line 1835 | `smem [32768]` | `tb/seq_stub_layer.sv:121` |  <!--cites:noquote-->
| 19 | spec line 1835 | `sptr <= sptr + 14'd1;` | `tb/seq_stub_layer.sv:284` |  <!--cites:noquote-->
| 20 | spec line 1838 | `MAXMEM = 32768` | `tb/tb_seq_chip.sv:76` |  <!--cites:noquote-->
| 21 | spec line 1842 | `LAYBASE = 6 << 16` | `tb/tb_burst_fabric.sv:327` |  <!--cites:noquote-->
| 22 | spec line 1885 | `B_TOP = 0x7FF8` | `tb/scripts/gen_seq_layer_script.py:115` |  <!--cites:noquote-->
| 23 | spec line 1885 | *"the LAST 8 words of the 32K scratchpad"* | `tb/scripts/gen_seq_layer_script.py:101-115` |  <!--cites:noquote-->
| 24 | spec line 1974 | `.cfg_dst({arg2[31], arg2[30:17]})` | `rtl/layer_chan.sv:801` |  <!--cites:noquote-->

**Rows 14 and 15 CHANGED CLASS during this fix round**, and that is worth
naming rather than smoothing over: log 12 classified them as A (moved),
because at that point `kvhead_r` was still `logic kvhead_r;` /
`kvhead_r <= arg0[0];`. Fix round 1 widened the kvhead FIELD to two bits (§2,
R1), which DELETED both lines, so they are class B in the final disposition.
**Class A therefore lands at 8 and class B at 16**, from log 12's 10 / 14.

### 13.2 The mechanism, and its two negative controls

`evidence/qwen9b/o3/o3_cite_drift.py` builds a `difflib` old→new line map
per edited file and
sweeps the citations from the **committed** document tree, never the working
one — which is what makes `--verify` reproducible after `--fix`. It was
written for Task 6 and hard-coded that task's twelve `sw/` files; it takes
`--edited <paths>` now, so G3.1 could pass its own 26-file set without
changing what T6's default does.

| run | log | result |
|---|---|---|
| `--check` (RED) | 20 | `CHECK FAIL (330 drifted, 122 unresolved, 0 missing)` over **525** distinct (file, line) citations |
| `--fix` | 21 | `FIXED 330 citation(s) in 43 document(s)` |
| `--verify` (GREEN) | 22 | `relocated 330 citation(s) checked against the base content and the citing documents`; residual below |
| `--check --negative-control` | 23 | **CAUGHT** (525 reported) |
| `--verify --negative-control` | 24 | **CAUGHT** (331 complaints) |
| `--doc-cites` (RED) | 25 | 18 citations INTO `docs/SEQ_ISA.md` (950 → 1168 lines) drifted |
| `--doc-cites --verify` | 26 | **PASS (0 problems)** |
| `--doc-cites --verify --negative-control` | 27 | **CAUGHT** (18 complaints) |

**The two bullets below are counted from log 45** (`tree: ef438e6`), not from
log 22 in the table above — log 22 was taken at `8ef57a8+dirty` (`d2d774b`
is its `--base`, not its tree), before the
hand repairs, and reports 10 and 0 for these two classes rather than 13 and 1.
Log 22 is kept as the record of the `--fix` run itself.

**The residual `--verify` reports, named rather than hidden** — it exits
non-zero and the two classes are why:

* **122 UNRESOLVED** — the cited LINE was rewritten or deleted. That is class
  B by definition: no renumbering can fix a citation whose subject no longer
  exists, and re-pointing it at the post-G3.1 line would make the citing
  sentence assert something false about its own subject. The 16 that carry a
  QUOTATION are the ones `spec_cites` fails on and they are dispositioned in
  §13.1; the rest carry no quotation, so `spec_cites` does not fail them and
  they read as what they are — line references into pre-G3 source inside
  documents describing the pre-G3 state.
* **13 "does not cite"** — citations this task had ALREADY replaced by hand
  with SYMBOL references (`ref/gen_layer_script.py`'s module-level `X8`,
  `Mach.alu` op 10, …) precisely because every line in that file moved. The
  tool reports that the base document's number is gone; it is gone on
  purpose, and a symbol citation cannot drift.
* **1 of a third class — `still cites the OLD ref/gen_layer_script.py:369`,
  and it is a FALSE POSITIVE.**  `ref/gen_layer_script.py:359-369` is
  `enc_saddr`'s real post-G3.1 span, so the document names 368 for a reason that has nothing to do with
  the base's 368; the tool sees only that a base number it wanted retired is
  still present on the page.  Named here rather than "fixed", because
  renumbering a correct citation to satisfy a checker is the defect this
  whole finding is about.

### 13.3 The result, measured per document

`spec_cites.py`, comparing QUOTE/RANGE/AMBIG/ORPHAN failures on the pre-G3
sources against the fixed tree (EXIST failures are excluded from the
comparison: the pristine `git archive` tree lacks gitignored evidence files
and invents them):

| document | pre | now | NEW |
|---|---:|---:|---:|
| `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md` | 0 | **0** | 0 |
| `docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md` | 0 | **0** | 0 |
| `evidence/qwen9b/g3/G3_1_ISA.md` | — | **0** | 0 |
| `docs/SEQ_ISA.md` | 0 | **0** | 0 |
| `docs/QWEN35_NEXT_FEASIBILITY.md` | 72 | 72 | **0** (see below) |
| `docs/superpowers/plans/2026-08-12-qwen2b-track-r.md` | 30 | 30 | **0** |
| `evidence/qwen2b/rc/RC_GATE.md` | 4 | 4 | **0** |
| `evidence/qwen2b/rd/RD_GATE.md` | 1 | 1 | **0** |
| `docs/ARCHITECTURE.md` | 5 | 5 | **0** |
| `docs/USAGE.md` | 3 | 3 | **0** |
| `evidence/qwen_next/place_exp/PLACE_EXP.md` | 6 | 6 | **0** |
| `evidence/qwen9b/g1/RUNG_INT8_STATE.md` | 2 | 2 | **0** |
| `evidence/qwen2b/q2/v4/GPTQ.md` | 4 | 4 | **0** |
| `evidence/qwen2b/ra/util_resident.md`, `…/dn_bank_verify.md`, `…/q2/v4_v5/V4_V5.md`, `…/plans/2026-08-16-qwen2b-v5-w8.md`, `NEXT_SESSION.md` | 1/1/0/0/1 | same | **0** |
| `evidence/qwen9b/g2/G2C_CHAIN.md`, `…/G2A_HOST.md`, `…/FINAL_BYTELOCK.md`, `evidence/qwen9b/o3/BOARD_LOCK.md`, `evidence/qwen_next/defect_a/CORRECTIONS.md` | 0 | **0** | 0 |

**Zero new failures anywhere**, and `FAIL 0` on the three R2 names.

> **CORRECTION 2026-09-02 (fix round 2).**  The first cut of this table
> reported `docs/QWEN35_NEXT_FEASIBILITY.md` as 26 → 26 and called it
> *"identical to pre-G3"*.  **That comparison used a narrower failure filter
> (QUOTE/RANGE only) than the rest of the table (QUOTE/RANGE/AMBIG/ORPHAN),
> and the honest number is 72 → 81: NINE new class-B QUOTE failures, created
> by G3.1 deleting the v1.7 source that study quotes** — the **two** 15-bit
> scratch arrays, `ld_n <= arg0[10:0]`, the 13-bit `cfg_len`, the two CONV/CONVW
> channel compares, `n_elems <= 15'd1 << arg0[5:2]`, `dn_head <= arg0[3:0]`
> and, added by fix round 1's kvhead widening, `logic kvhead_r;`.  They are
> given the SAME class-B treatment the spec's rows got — a dated boxed note
> at the head of that study, `<!--cites:noquote-->` on each of the nine rows,
> and the post-G3.1 landmark in §15 — which takes it back to **72 → 72,
> NEW = 0**.  The one row the diff still shows is the same pre-existing
> failure with its embedded numbers renumbered
> (`rtl/layer_chan.sv:484,:891` → `:420,:891`).  Every other row of this
> table was measured with the wider filter and is unaffected.
`evidence/qwen9b/g2/spec_cites_selftest_regression.sh` (log 28) is
`SPEC_CITES_REGRESSION PASS` with every pinned count unchanged — RC_GATE 27,
RD_GATE 8, FINAL_BYTELOCK 0, G2A_HOST 0, D_TOL 3, RUNG_INT8_STATE 2, spec 0,
plan 0 — and its own `--selftest` 6/6 CAUGHT on four documents.

**Two defects the `--fix` INTRODUCED and this round repaired**, because an
automated renumberer maps a range's two ends independently: **NINE INVERTED
RANGES** — six in spec §7.6 A's landmark list into `ref/gen_layer_script.py`
(the start mapped past the end, e.g. 384 to 375), one in §7.6 D into
`ref/seq_format.py`, one in §7.6 E into `rtl/layer_chan.sv`, and one in the
plan into `synth/scripts/create_project.tcl` — and one COLLAPSED range where
both ends mapped to the same line. **All ten** were re-derived by hand against
the post-G3.1 source and are listed in §15.  (The first cut of this paragraph
said "seven … All eight" while listing nine; the three numbers agree now.)

### 13.4 A defect IN THE TOOL, found by the re-review and fixed at the root

`o3_cite_drift.py --fix` produced **half-mapped ranges**: one endpoint
renumbered to its post-G3.1 line, the other left at its pre-G3 number, **in
one token**. Twenty-five ranges were exposed to it. **Fourteen** were known
to be damaged when this section was first written; §13.4a's line-by-line
enumeration found **three more** (its rows 20, 24 and 25), so **seventeen**
landed damaged across the spec, the plan, two gate documents and one RTL
comment.

**ROOT CAUSE, one line:** `na = m.get(a) or a` mapped an endpoint when the
line map had it and **silently kept the base number when the map returned
None** — i.e. when that line had been REWRITTEN OR DELETED. The docstring's
claim that *"Both endpoints are mapped now"* (a fix from Task 6's own review)
held only when both endpoints survived. `spec_cites.py` cannot see it —
`RANGE` passes on any in-file number — so it survived a `FAIL 0`.

**FIXED AT THE ROOT, not at the residue.** A new `_map_range` returns
`(None, None)` if EITHER endpoint is unresolved; `rewrite_doc` then leaves
the token **byte-identical**; and `classify` reports it as a named
`HALF-MAPPED` class naming both endpoints, their base text and where each one
went, so a human repairs it against `git show <base>:<file>`. Ranges are
recorded as ranges by `sweep` — previously each endpoint was a separate
`(file, line)` citation, which is why the pairing was invisible.

**ITS OWN NEGATIVE CONTROL, `--range-control`**, **seven** synthetic cases
against `rewrite_doc` on a hand-built map: both endpoints live → **must** be
rewritten; END deleted → untouched; START deleted → untouched; a bare
continuation with a deleted endpoint → untouched; and the three
OUT-OF-RANGE-ENDPOINT cases round 3 added (finding O3). The first case is
what makes the others mean anything — a rewriter that refused everything
would pass them vacuously. Regressing `_map_range` to the old
`m.get(x) or x` makes the control report `FAIL (2 problem(s))`, which is the
measurement that it can fail. *(This paragraph said four cases and FAIL 3
until 2026-09-10; §14a's run table and log 64 both read seven and FAIL 2.)*

`evidence/qwen9b/o3/BOARD_LOCK.md` is **not** edited: Task 6's gate logs are
frozen and were correct for the tree they ran on. The tool change is recorded
here instead, by that gate's own ruling.

**What `--verify` reports after the repair, and why it is not zero.**
Log 63 (`tree: f2a093e`, the final round-3 run): **330 relocations
content-checked**, then three named residual classes.

| class | n | what it is |
|---|---:|---|
| `HALF-MAPPED` | 25 | ranges the new rule REFUSED to touch. This is the fix working: they are reported, not rewritten. Seventeen of them had already been damaged by the old `--fix` and are repaired by hand (§13.4 above); the other eight were never written to a document in a damaged form, so there is nothing to repair. |
| `UNRESOLVED` | 122 | the cited LINE was rewritten — class B by definition (§13.2). |
| "does not cite" / "still cites the OLD" | 25 | **the ASYMPTOTE of a base-swept checker, not a defect.** Every hand repair of a citation whose target line was rewritten makes the base's number disappear from the page, which is exactly what the tool then reports. Log 63 splits the 25 as **19 "does not cite" + 6 "still cites the OLD"**, and the six are composed like this: **five** are round 3's deliberate class-B base retentions, kept at their base numbers because the source they quote is gone (§13.4a rows 20 and 24) — `tb/scripts/gen_seq_layer_script.py:83`, `tb/scripts/gen_seq_unit_vectors.py:517`, `tb/scripts/gen_seq_unit_vectors.py:520`, `tb/scripts/gen_seq_unit_vectors.py:524` and `tb/tb_seq_unit.sv:559` — and the **sixth** is the same shape from the other direction and is a FALSE POSITIVE: `ref/gen_layer_script.py:359-369` is `enc_saddr`'s real post-G3.1 span, so the document names 368 for its own reason. Renumbering a correct citation to satisfy a checker is the defect this whole finding is about. *(Composition restated from log 63 on 2026-09-10; this cell said "Two are the same shape … and are FALSE POSITIVES" while naming one.)* |

`--doc-cites --verify` (log 67) is **39 relocated and content-checked,
4 residual** —
the three spec ranges whose START line had its own inner citations renumbered
(so the tool cannot text-match a row that is otherwise the same one), and the
`<document>:0` expected-FAIL-count column in
`evidence/qwen9b/g2/spec_cites_selftest_regression.sh`, which parses as a
citation. That script is left byte-identical, as its own contract requires.

### 13.4a Every one of the 25 exposed ranges, with a disposition

The claim the first cut of this section made — *"25 exposed, 14 damaged, all
repaired; the other eleven were never written to a document in a damaged
form"* — **was false for three of them** (rows 20, 24 and 25 below): they were
bare `` `:A-B` `` continuations that the old `--fix` DID half-rewrite, and no
hand repair had touched them. All 25 are enumerated here from
`evidence/qwen9b/g3/50_cite_drift_check_r2.log:923-1022`, so the count is
checkable rather than asserted.

| # | exposed range (base `d2d774b`) | citing document | disposition |
|---:|---|---|---|
| 1 | `ref/gen_layer_script.py:316-320` — the layout comment | spec §7.6 A | REPAIRED (round 1) → `ref/gen_layer_script.py:318-342` |
| 2 | `ref/gen_layer_script.py:372-376` — `enc_a1` | spec §7.6 A | REPAIRED (round 1) → `ref/gen_layer_script.py:385-388` |
| 3 | `ref/gen_layer_script.py:379-380` — `dec_a1_lo` | spec §7.6 A | REPAIRED (round 1) → `ref/gen_layer_script.py:391-392` |
| 4 | `ref/gen_layer_script.py:383-384` — `dec_a1_hi` | spec §7.6 A | REPAIRED (round 1) → `ref/gen_layer_script.py:395-396` |
| 5 | `ref/gen_layer_script.py:387-390` — `enc_alu_a2` | spec §7.6 A | REPAIRED (round 1) → `ref/gen_layer_script.py:399-407` |
| 6 | `ref/gen_layer_script.py:393-394` — `dec_alu_dst` | spec §7.6 A | REPAIRED (round 1) → `ref/gen_layer_script.py:415-416` |
| 7 | `ref/seq_format.py:137-138` — the helper import | spec §7.6 D | REPAIRED (round 1) → `ref/seq_format.py:140-142` |
| 8 | `ref/seq_format.py:822-837` — `disasm`'s ALU/VN decoders | spec §7.6 D | REPAIRED (round 2) → `ref/seq_format.py:838-853` |
| 9 | `ref/seq_format.py:2157-2181` — the DN block-float rewriter | spec §7.6 D | REPAIRED (round 2) → `ref/seq_format.py:2194-2222` |
| 10 | `rtl/layer_chan.sv:16-18` — the SPTR/SWIN register-map rows | `sw/chat_seq.py` | **UNDAMAGED, VERIFIED**: the old `--fix` wrote `16-18`, byte-identical to the base token, and both lines still name the SPTR and SWIN rows |
| 11 | `rtl/layer_chan.sv:74-112` — the in-RTL ISA copy | spec §7.6 E | REPAIRED (round 2) → `rtl/layer_chan.sv:79-134` |
| 12 | `rtl/layer_chan.sv:104-107` — the DNST command doc | spec §4.3 | REPAIRED (round 2) → `rtl/layer_chan.sv:121-124` |
| 13 | `rtl/layer_chan.sv:341-342` — `sptr` / `cmd_cnt` | `evidence/qwen2b/ra/util_resident.md` | REPAIRED (round 2) → `rtl/layer_chan.sv:359-360` |
| 14 | `rtl/layer_chan.sv:416-420` — the DN bank wires | `synth/exp_uram/rtl/layer_chan.sv` | REPAIRED (round 2) → `rtl/layer_chan.sv:449-454` |
| 15 | `rtl/layer_chan.sv:1033-1039` — the ARG pair wires | spec §7.6 E | REPAIRED (round 1) → `rtl/layer_chan.sv:1096-1104` |
| 16 | `rtl/seq_movers.sv:14-17` — the layer-window alignment note | spec §4.3, `docs/QWEN35_NEXT_FEASIBILITY.md` | REPAIRED (round 2) → `rtl/seq_movers.sv:14-23` |
| 17 | `sw/chat_seq.py:236-304` — claimed to be `SeqLock` | plan | REPAIRED (round 2) → `sw/chat_seq.py:367-386`. **The base citation was ALREADY WRONG at `d2d774b`** (`SeqLock` was at 335 there); the half-map exposed it |
| 18 | `synth/scripts/create_project.tcl:462-466` — the provenance comment | plan | REPAIRED (round 2) → `synth/scripts/create_project.tcl:464-478` |
| 19 | `synth/scripts/create_project.tcl:467-468` — the `seq_axib_map` entry | plan | REPAIRED (round 1) → `synth/scripts/create_project.tcl:479-480` |
| 20 | `tb/scripts/gen_seq_layer_script.py:68-83` — the aliasing-sentinel rationale | spec §7.5 E | **REPAIRED (round 3)** — a bare continuation the old `--fix` wrote as `:68-88`. **CLASS B**: base :68's text was deleted, and the row's two sibling ranges (`:96-114`, `:72-73`) are already at base numbers under the row's `noquote`, so the base numbers are restored and §15 names the post-G3.1 span `tb/scripts/gen_seq_layer_script.py:69-88` |
| 21 | `tb/scripts/gen_seq_layer_script.py:182-193` — `m_gate` | spec §7.5 D | REPAIRED (round 2) → `tb/scripts/gen_seq_layer_script.py:206-227` |
| 22 | `tb/tb_seq_chip.sv:76-86` — `MAXMEM` .. `MEMAW` | spec §7.5 B, plan | **UNDAMAGED, VERIFIED**: the old `--fix` wrote `76-86`, byte-identical to the base token, and both lines still name `MAXMEM` and `MEMAW` |
| 23 | `tb/tb_seq_unit.sv:553-563` — the burst AW window bound | spec §7.5 B | REPAIRED (round 2) → `tb/tb_seq_unit.sv:585-596` |
| 24 | `tb/tb_seq_unit.sv:555-563` — inside the parenthetical recording an earlier revision's citation | spec §7.5 B | **REPAIRED (round 3)** — a bare continuation the old `--fix` wrote as `:555-596`. **CLASS B / historical**: the sentence records what an EARLIER REVISION cited, so the base numbers are restored and the row is `noquote`'d |
| 25 | `tb/tb_seq_unit.sv:569-573` — the read-channel twin | spec §7.5 B | **REPAIRED (round 3)** — a bare continuation the old `--fix` wrote as `:569-607`, a LIVE WRONG POINTER (HEAD :519 is `take_w(...)` in a different always block). Now `tb/tb_seq_unit.sv:602-607`, the real twin |

**Totals: 23 repaired (9 in round 1, 11 in round 2, 3 in round 3), 2
undamaged and verified — 25 rows in all — and 2 of the repairs given the
class-B treatment rather than a renumber (rows 20 and 24; row 25 was a live
wrong pointer and got a real one).**  *(Recounted from the table above on
2026-09-10: the first cut of this paragraph said 6/11/3 = 20 repaired and 3
class B, which neither summed to 25 nor matched the dispositions.)* The three round-3 rows are the ones the first cut
of this section got wrong, and they were bare continuations in every case —
the citation form `spec_cites.py` is weakest on and the one a
`git grep` for a full `path:NNN` token does not find.

### 13.5 The A2.3 verification, which is NOT the citation drift

Three of the 24 (rows 1–3) are the spec's A2.3 sites, and their TEXT is
unchanged — only their line moved. `git diff sw/chat_seq.py` shows no `+`/`-`
line touching `HEAD_LOGIT_EXP0`, `head_logit_exp0`, `RS_F_DEFAULT` or
`MANIFEST_META_KEYS`; `sw/hwmap.RS_F_DEFAULT` is still 8; and
`head_logit_exp0(7) == HEAD_LOGIT_EXP0 + 1` still passes inside
`chat_seq --selftest` [18]. **The host work set for A2 is empty and stayed
empty.**

## 14a. The gate evidence, re-run on a COMMITTED tree

Logs 05-28 were produced at `tree: d2d774b+dirty` — the working tree, before
the first commit. **Every gate in this document was re-run after the commits
landed, on a tree with no `+dirty` flag**, and those are the runs it rests on:

| gate | log | tree | result |
|---|---|---|---|
| the checker | 30 | `89bc9b0` | `ISA_BITS: PASS`, 348 round-trips x 29 address sets |
| its field-width negative control | 31 | `89bc9b0` | **19/19 REFUSED** (18 + the new `kvhead`) |
| the DNST-map control, 0.8B | 32 | `89bc9b0` | healthy ACCEPTED, 5/5 REFUSED |
| the checker at 9B | 33 | `89bc9b0` | `ISA_BITS: PASS` |
| the DNST-map control at 9B | 34 | `89bc9b0` | healthy ACCEPTED, 5/5 REFUSED (LNH=32 makes the wall-17 row real) |
| the checker on the pristine PRE-G3 tree | 35 | `89bc9b0` | `ISA_BITS: PASS` |
| its negative control there | 36 | `89bc9b0` | **19/19 REFUSED** |
| the 15-target x 4-seed suite | 37 | `89bc9b0` | `rc: 0`, **252 PASS, zero FAIL / %Error / %Warning / Fatal** |
| the board-free gate | 38 | `89bc9b0` | `BOARDFREE_PASS`; seq 2758/0, serve 85/0, chat_seq **356**/0 |
| the citation gate | 43 | `ef438e6` | spec, plan, this doc and `docs/SEQ_ISA.md` all **FAIL 0**; `SELFTEST: PASS` |
| the pinned-count regression | 44 | `ef438e6` | `SPEC_CITES_REGRESSION PASS`, every pinned document unmoved |
| the drift `--verify` | 45 | `ef438e6` | 330 relocations content-checked; residual 122 UNRESOLVED + 14, both classes named in §13.2 |
| the `--doc-cites --verify` | 46 | `ef438e6` | 32 of 33 relocated and content-checked; 4 residual, named below |
| the citation gate, re-run after §14a was written | 47 | `ef438e6`+dirty | the same four documents; recorded as `+dirty` because §14a was still uncommitted |
| the citation gate | 48 | `b5ee593` | the same four documents plus the pinned-count regression: all **FAIL 0**, `SELFTEST: PASS`, `SPEC_CITES_REGRESSION PASS` |
| **fix round 3** — the drift `--check` / `--verify` | 62, 63 | `f2a093e` | `CHECK FAIL (330 drifted, 122 unresolved, 0 missing, 25 half-mapped)`; `--verify` content-checks all 330 relocations |
| `--range-control` **with the out-of-range cases** | 64 | `f2a093e` | **PASS** (7 cases; regressing `_map_range` makes it FAIL 2) |
| both pre-existing negative controls | 65, 66 | `f2a093e` | **CAUGHT** |
| `--doc-cites --verify` | 67 | `f2a093e` | 39 relocated and content-checked, 4 residual |
| the citation gate, **FINAL** | 68 | `f2a093e` | all four documents **FAIL 0**, `SELFTEST: PASS`, `SPEC_CITES_REGRESSION PASS` |
| the vector-generator byte-lock | 69 | `f2a093e` | **182 artifacts, 0 differing** over 4 seeds — the round-2/3 edit to `tb/scripts/gen_seq_unit_vectors.py` is comment-only, which is why no Verilator re-run is implied |
| **fix round 2** — the drift `--check` (RED) | 50 | `9231326` | `CHECK FAIL (330 drifted, 122 unresolved, 0 missing, 25 half-mapped)` — the half-mapped class is new and is the O3 fix reporting |
| its two pre-existing negative controls | 52, 53 | `9231326` | both **CAUGHT** (553 reported / 331 complaints) |
| **the NEW `--range-control`** | 54 | `9231326` | **PASS** — a half-mapped range is never rewritten (§13.4) |
| the drift `--verify` | 56 | `83ac699` | 330 relocations content-checked; residual composed above |
| the citation gate, **FINAL** | 57 | `83ac699` | spec, plan, this doc and `docs/SEQ_ISA.md` all **FAIL 0**; `SELFTEST: PASS` |
| the pinned-count regression, **FINAL** | 58 | `83ac699` | `SPEC_CITES_REGRESSION PASS`, every pinned document unmoved |
| `--doc-cites --verify`, **FINAL** | 59 | `83ac699` | 39 relocated and content-checked; the same 4 residual |


**The `--doc-cites` residual, named rather than hidden.** Three of the four
are one range: `evidence/qwen2b/rc/RC_GATE.md`,
`evidence/qwen2b/rd/RD_GATE.md` and `evidence/qwen9b/g2/FINAL_BYTELOCK.md`
all cite the same spec range whose START line had its own embedded citations renumbered by
this round's `--fix`, so the tool cannot text-match it although the ROW is the
same one — the ranges were re-pointed at that row by hand. The fourth is a
false positive: `evidence/qwen9b/g2/spec_cites_selftest_regression.sh`
line 47 carries a
`<document>:0` expected-FAIL-count column that parses as a citation. **That
script is left byte-identical**, as its own contract requires, and log 44
confirms every pinned count is unchanged.

## 15. Post-G3.1 landmarks for every PRE-G3.1 row

The spec's class-B rows (§13.1) quote source this task deleted and carry
`<!--cites:noquote-->` with a dated boxed note. **This is where a reader goes
for the current line.**  Every row carries `<!--cites:noquote-->` for the same
reason the spec's rows do: the `was` column quotes SEQ_ISA v1.7 source this
task deleted, deliberately, so the two states can be read side by side.

| pre-G3.1 subject | was | now |  <!--cites:noquote-->
|---|---|---|
| the scratch arrays | `rtl/layer_chan.sv:371-372` `logic signed [15:0] smem_a [32768];` | `rtl/layer_chan.sv:398-399`, `[65536]` |  <!--cites:noquote-->
| the scratch address signals | `rtl/layer_chan.sv:373` `logic [14:0] sa_addr, sb_addr;` | `rtl/layer_chan.sv:400`, `[15:0]` |  <!--cites:noquote-->
| the ARG pair wires | `rtl/layer_chan.sv:1040-1043` `{arg1[28], arg1[13:0]}` … | `rtl/layer_chan.sv:1101-1104`, `arg1[15:0]` / `arg1[31:16]` |  <!--cites:noquote-->
| the in-RTL ISA copy | `rtl/layer_chan.sv:74-112`, `:1033-1039` | `rtl/layer_chan.sv:79-134`, `rtl/layer_chan.sv:1096-1104` |  <!--cites:noquote-->
| VNW's count decode | `rtl/layer_chan.sv:1165` `ld_n <= arg0[10:0]` | `rtl/layer_chan.sv:1242`, `arg0[12:0]` |  <!--cites:noquote-->
| the ALU length wiring | `rtl/layer_chan.sv:552` `.cfg_len(arg0[16:4])` | `rtl/layer_chan.sv:797`, `arg0[17:4]` |  <!--cites:noquote-->
| the ALU dst wiring | `rtl/layer_chan.sv:747` `.cfg_dst({arg2[31], arg2[30:17]})` | `rtl/layer_chan.sv:801`, `arg2[31:16]` |  <!--cites:noquote-->
| `cfg_len`'s port | `rtl/vec_alu.sv:112` `[12:0]` | `rtl/vec_alu.sv:112`, `[13:0]` |  <!--cites:noquote-->
| the CONV channel compare | `rtl/layer_chan.sv:1467` `if (cvi == arg0[25:13])` | `rtl/layer_chan.sv:1534`, `arg0[27:14]` |  <!--cites:noquote-->
| the CONVW channel compare | `rtl/layer_chan.sv:1514`, `:1530` `arg0[27:15]` | `rtl/layer_chan.sv:1581`, `rtl/layer_chan.sv:1597`, `arg0[29:16]` |  <!--cites:noquote-->
| `kvhead_r`'s declaration | `rtl/layer_chan.sv:658` `logic kvhead_r;` | `rtl/layer_chan.sv:513`, `logic [1:0]`, with `kvhead_hw` beside it |  <!--cites:noquote-->
| `kvhead_r`'s latch | `rtl/layer_chan.sv:1095` `kvhead_r <= arg0[0];` | `rtl/layer_chan.sv:1210`, `arg0[1:0]` |  <!--cites:noquote-->
| `dn_head`'s latch | `rtl/layer_chan.sv:1094` `dn_head <= arg0[3:0];` | `rtl/layer_chan.sv:1209`, `arg0[4:0]`, with `dn_head_hw` beside it |  <!--cites:noquote-->
| the mover scratch bound | `rtl/seq_movers.sv:190` `SCR_WORDS = 32768` | `rtl/seq_movers.sv:199`, 65536 |  <!--cites:noquote-->
| the canonical helpers | `ref/gen_layer_script.py:346-394` | `ref/gen_layer_script.py:359-426` (`enc_alu_a0`/`dec_alu_len`/`dec_alu_p0` are new) |  <!--cites:noquote-->
| `ALU_LEN_MAX` (emitter) | `ref/gen_layer_script.py:922` 8191 | `ref/gen_layer_script.py:1041`, 16383 |  <!--cites:noquote-->
| `ALU_LEN_MAX` (the twin) | `ref/seq_format.py:1411` 8191 | `ref/seq_format.py:1428`, 16383 |  <!--cites:noquote-->
| the helper import | `ref/seq_format.py:137-138` | `ref/seq_format.py:140-142` |  <!--cites:noquote-->
| the DNST emit line | `ref/gen_layer_script.py:819-820`, hand-ORs bits 30/31 | `ref/gen_layer_script.py:944`, `self.C(8, head, …)` — the scatter is GONE |  <!--cites:noquote-->
| the golden-MEM checker | `tb/tb_seq_unit.sv:967` `[14:0]` | `tb/tb_seq_unit.sv:997`, `[MEMAW-1:0]`, with the guard at `tb/tb_seq_unit.sv:99` |  <!--cites:noquote-->
| the stub scratch | `tb/seq_stub_layer.sv:120` `smem [32768]` | `tb/seq_stub_layer.sv:121`, `[65536]` |  <!--cites:noquote-->
| the stub SPTR increment | `tb/seq_stub_layer.sv:283` `sptr + 14'd1` | `tb/seq_stub_layer.sv:284`, `16'd1` |  <!--cites:noquote-->
| the chip TB depth | `tb/tb_seq_chip.sv:76` `MAXMEM = 32768` | `tb/tb_seq_chip.sv:76`, 65536 |  <!--cites:noquote-->
| the burst-fabric layer base | `tb/tb_burst_fabric.sv:320` `LAYBASE = 6 << 16` | `tb/tb_burst_fabric.sv:327`, `8 << 16` |  <!--cites:noquote-->
| the high-half map | `tb/scripts/gen_seq_layer_script.py:96-114`, `B_TOP = 0x7FF8` | `tb/scripts/gen_seq_layer_script.py:101-115`, `B_TOP = 0xFFF8`, block at `0xE000` |  <!--cites:noquote-->
| the block-design map | `synth/scripts/create_project.tcl:467-468`, `:483-492` | `synth/scripts/create_project.tcl:479-480`, `synth/scripts/create_project.tcl:496-505` |  <!--cites:noquote-->
| **the seq_unit vectors' ALU packer** — spec §7.5 E and §7.6 C quote its 14-bit body, which G3.1 DELETED | `tb/scripts/gen_seq_unit_vectors.py:549-551` and `:547-554` as the spec writes them.  **Those numbers were ALREADY STALE at `d2d774b`**, where they name `csr_layer_w`/`xop`; the packer itself was at `tb/scripts/gen_seq_unit_vectors.py:558-565` there | `tb/scripts/gen_seq_unit_vectors.py:560-574`, the whole `alu_cmd`; its three packing lines are `tb/scripts/gen_seq_unit_vectors.py:569-571`, now `enc_alu_a0` / `enc_a1` / `enc_alu_a2` calls |  <!--cites:noquote-->
| the seq_unit burst-window READ twin | `tb/tb_seq_unit.sv:569-573` | `tb/tb_seq_unit.sv:602-607` |  <!--cites:noquote-->
| the hi-half aliasing-sentinel rationale | `tb/scripts/gen_seq_layer_script.py:68-83` | `tb/scripts/gen_seq_layer_script.py:69-88` (the block's prose start to its closing separator) |  <!--cites:noquote-->
| the KV banking block `synth/exp_uram` mirrors | `rtl/layer_chan.sv:464-471` | `rtl/layer_chan.sv:498-518` |  <!--cites:noquote-->

## 14. What is NOT established by this gate

* **No synthesis, no timing, no board.**  The 65,536-word scratchpad doubles
  the BRAM the array asks for and the +28 RAMB36 / 41.0 % device figure is
  spec §2.7's **D**, not something this gate measured.  Per-SLR BRAM is a G5
  floorplan input.
* **`synth/scripts/create_project.tcl` is edited but NOT exercised.**  Its
  three coupled edits (the `seq_axib_map` offset, the per-slave range
  expectation that `exit 1`s, and the provenance comment) are read by Vivado
  only.  The equivalent map in the SIM fabric model is exercised
  (`tb_bfab` T3 now probes the enlarged hole), but a build is the only thing
  that proves the TCL.
* **The 9B stream still does not emit, and the reason is now purely
  DATAPATH.**  G2c's correction stands: the first wall an emission hits is
  `Mach.CONV_FIELD_MAX`, with `Mach.ARG0_HEAD_BITS` one line behind it.
  **All FOUR field ceilings G2c named are lifted here** — `ISA_SADDR_MAX`,
  `ARG0_HEAD_BITS`, `CONV_FIELD_MAX` and `ALU_LEN_MAX` — and so are
  `VNW_ISA_MAX` and `ARG0_KVH_BITS`.  What still refuses is the DATAPATH
  half of each split, and each one names its owner: **`VNW_HW_MAX` (2048,
  Task 8)** and **`KVH_HW_MAX` (1, Task 10)**, plus the two the RTL guards
  directly — the 6144-channel conv bank and the 16-head DN banking (Task 10 /
  G4).  `ARG0_KVH_BITS` is NOT among the refusals: it is a FIELD and it is
  lifted, exactly like `VNW_ISA_MAX` (§2's taxonomy).  **Landing the 16-bit
  ISA does not by itself unblock 9B emission** — it removes every field
  ceiling and leaves the refusals naming the DATAPATH and its owning task.
* **Two widened FIELDS are not exercised end to end, and will not be until
  their datapath lands.**  `ARG0[12]` of the VNW count (the emitter refuses a
  count above `VNW_HW_MAX` = 2048 — Task 8) and **`ARG0[1]` of the KVAP/ATTN
  kvhead** (the emitter refuses `kvh >= 2` above `KVH_HW_MAX` = 1 — Task 10).
  Both are stated in `evidence/qwen9b/g3/isa_bits.py` beside the round-trip
  that caps them, and both are still caught by the ceiling check (§2) and by
  the negative control if the RTL slice narrows.
* **The DNSB CSR is proven in simulation only** (`tb_layer_chan` 4 seeds,
  `tb_seq_layer` 4 seeds).  No silicon has executed a v2.0 stream.
* **`tb_token` / `tb_chain` / `tb_model_*` / `tb_seq_chip` are not run and
  cannot pass** until their committed v1.7 artifacts are regenerated (§8).
* **D-GATEPORT is untouched** and travels on: 60 of 768 DN heads still have
  their decay changed by the production clamp (spec §9), which is a property
  of the checkpoint against frozen `gate_unit` ports and is option- and
  ISA-independent.

---------------------------------------------------------------------
## 16. G3.2 CITATION MAINTENANCE — 2026-09-02 (Task 8)
---------------------------------------------------------------------

> **Appended at the END on purpose: not one line above this point moved, so
> every `G3_1_ISA.md:NNN` citation elsewhere still resolves.  NO prose,
> number, table cell of substance or conclusion of this gate was changed —
> only citation line numbers, and one exemption marker.**

G3.2 (`evidence/qwen9b/g3/G3_2_VECNORM.md`) edited
`rtl/vecnorm_unit.sv`, `rtl/layer_chan.sv`, `ref/gen_layer_script.py` and
three TB files, which moved lines this document cites.  Closed the same way
Tasks 6 and 7 closed theirs — mechanically, by
`evidence/qwen9b/o3/o3_cite_drift.py --base ec08638` (log
`evidence/qwen9b/g3/113_cite_drift_fix_g3_1_isa.log`), then dispositioned:

| where | citation | disposition |  <!--cites:noquote-->
|---|---|---|  <!--cites:noquote-->
| §13.1 row 4 | `rtl/layer_chan.sv:432` beside `logic [10:0] vn_waddr;` | **CLASS B** — G3.2 widened it to `logic [11:0] vn_waddr;`, so the quotation names source that no longer exists.  The row keeps its text as the record and carries `<!--cites:noquote-->`; the post-G3.2 line is in `G3_2_VECNORM.md` §9 |  <!--cites:noquote-->
| §13.1 row 5 | that row's `ref/gen_layer_script.py` line, 1456 | RENUMBERED → `ref/gen_layer_script.py:1491` |  <!--cites:noquote-->
| §13.1 row 6 | that row's `ref/gen_layer_script.py` line, 1439 | RENUMBERED → `ref/gen_layer_script.py:1474` |  <!--cites:noquote-->
| §13.1 row 8 | that row's `ref/gen_layer_script.py` line, 770 | RENUMBERED → `ref/gen_layer_script.py:775` |  <!--cites:noquote-->
| §15 `ALU_LEN_MAX` (emitter), *now* column | that column's `ref/gen_layer_script.py` line, 1009 | RENUMBERED → `ref/gen_layer_script.py:1041` |  <!--cites:noquote-->
| §15 the DNST emit line, *now* column | that column's `ref/gen_layer_script.py` line, 912 | RENUMBERED → `ref/gen_layer_script.py:944` |  <!--cites:noquote-->
| §15 `ALU_LEN_MAX` (emitter), *was* column | its line 895, which §15 still prints | **LEFT** — `--fix` moved it to line 900 and that was REVERTED.  §15's *was* column is a **pre-G3.1** line: `d2d774b:895` is `ALU_LEN_MAX = (1 << 13) - 1`, which is what the row quotes.  Mapping it through `ec08638` is a false positive |  <!--cites:noquote-->
| §15 the DNST emit line, *was* column | its lines 795-796, which §15 still prints | **LEFT** for the same reason, same revert: `d2d774b:795-796` is the `((a_dec >> 14) << 30)` / `((a_beta >> 14) << 31)` hand-OR the row describes |  <!--cites:noquote-->
| §13.4a row 12 | `rtl/layer_chan.sv:104-107` | **LEFT** — a pre-G3.1 number the row prints deliberately beside the repaired one (`→ rtl/layer_chan.sv:121-124`).  `--verify` reports it as HALF-MAPPED; that is the same false positive |  <!--cites:noquote-->

**Three statements of this gate are now SUPERSEDED by G3.2** and are listed
here rather than edited in place, because they were true when written:
§2's taxonomy row *"`VNW_HW_MAX` — 2048 (NEW) — DATAPATH … Task 8"*
(**now 4096**), §6's *"VNW length above the 2048-deep vecnorm wbuf"*
(**now 4096-deep**), and §14's two bullets naming `VNW_HW_MAX` as a live
refusal and `ARG0[12]` as not exercised end to end (**it is: G3.2's
`evidence/qwen9b/g3/110_isa_bits_post_g32.log`**).  The current values are
in `G3_2_VECNORM.md` §3.
