# R-b SIM GATE — the whole ladder on the widened RTL (2026-08-13)

Tree: `0636b7f` on branch `qwen2b`, **clean at every run** (`git status`
empty before the gate; only `evidence/qwen2b/rb/` added after). This is the
roll-up for Track R walls R3-R6 merged together — vecnorm N=2048 (`337ea78`),
MAX_NG 48 + generalized scale beats (`b11fb79`), scratch 32K words + 15-bit
ISA homes + layer burst window moved to 0x6_0000 (`824ea2e`, `f467004`),
EMBLOG2 runtime CSR (`6124508`, `52d5cab`). Each wall passed its own gates in
isolation; **this document is the interaction check** — every frozen 0.8B
stream and every widened-geometry directed case, on the final tree, in one
pass. RTL delta vs the pre-R-b base `6472f92`: 8 files, +378/-233.

**Seven of those eight files are covered here; the eighth is not simulatable.**
`rtl/layer_chan_ipi.v` is the Vivado IPI wrapper — its R-b change is the
`s_axib` port widening (`ADDR_WIDTH 16 → 17` in `X_INTERFACE_PARAMETER`,
`aw/araddr [15:0] → [16:0]`, i.e. one 64 KiB segment → one 128 KiB segment for
the 32768-word scratch). It appears in **no** `tb/` filelist and cannot: it
carries only `X_INTERFACE_INFO`/`X_INTERFACE_PARAMETER` metadata that Vivado
reads when it packages the block design. **This gate says nothing about it.**
Its verification is deferred to R8, which must confirm the block design's
`s_axib` port is 17 bits and that `assign_bd_address` places the window at
0x6_0000 with a 128 KiB range — a stale 16-bit BD port would silently truncate
scratch addresses above 16383 in hardware while every sim here stays green.

Hosts, per the Track R execution split. Unit + mid set on **darthplagueis**
(`evidence/qwen2b/rb/sim_units.log`); heavy set on **snoke**
(`sim_heavy.log`), launched detached with bounded-wait polling. Verilator
5.020 on both. Because `obj_dir_*` is NFS-shared, the four targets that share
`obj_dir_tb_layer` (`tb_layer_chan`, `tb_token`, `tb_chain`, `tb_token24`)
ran **first on darthplagueis** and released the directory to snoke through a
sentinel before snoke started `tb_model_v2_all`; the snoke script blocks on
that sentinel rather than assuming it. Non-overlap is measured, not asserted:
darthplagueis released at **18:33:41** and snoke's wait logged
**`released after 0s`** when it arrived at H4 ~18:44 — the directory was
already free. No obj_dir was ever open on two hosts.

Wall clock: local 18:09:43 → 18:37:12 (**27 min**), snoke 18:07:18 → 20:14:19
(**2 h 07 min**), overlapping. Both inside the Track R budget.

## Headline

**GREEN — 17 of 17 gate groups end green; 16 of them first time.** The
seventeenth is `regen_gate.sh`, which tripped once on darthplagueis and is
green on retry there (twice) and on snoke — a known host fault, dissected
below, not a property of this tree. The widened RTL replays every frozen
0.8B stream bit-exact, and the `w3` chip stream replays in **exactly
2,272,141 cycles** — the same figure **pre-R-b RTL produced for the same
stream** at rung 4, recorded in `evidence/rung4/gate_chip_nch1.log:76,84`
(commit `33d720e`, 2026-08-11). The geometry grew; 0.8B behavior did not move.

That historical log is the load-bearing anchor, because `tb/scripts/w3/` is
gitignored and H2 **overwrote** the 2026-08-08 files during this very run — so
H1's inputs are no longer on disk to re-check. The rung-4 log is independently
checkable and self-dating: it carries per-file RTL sha256s in its header, and
all three of `layer_chan.sv` / `seq_unit.sv` / `vecnorm_unit.sv` hash
**differently** there than on this tree (`986184e2…`/`92a5b08e…`/`d4b21b61…`
then, vs `85b398f2…`/`e135c5c2…`/`30613511…` now). Same stream, same cycle
count, provably different RTL.

## Gates (sim)

| # | gate | host | result |
|---|---|---|---|
| L1 | `tb_layer_chan` 4 seeds | dp | PASS 707 cmds, 76,941 checks bit-exact each |
| L1 | `tb_token` 4 seeds | dp | PASS 728 cmds, 80,022 checks each |
| L1 | `tb_chain` (8 layers) 4 seeds | dp | PASS 3,660 cmds, 315,642 checks each |
| L1 | `tb_token24` (24 layers) 4 seeds | dp | PASS 11,001 cmds, 950,007 checks each |
| L2 | `lint_matvec` | dp | clean |
| L2 | `tb_vec_alu` 4 seeds + am_g wrap | dp | PASS 10 ops bit-exact |
| L2 | `tb_vecnorm` 4 seeds | dp | PASS — **N=2048 nlog2=11 x2** + envelope self-test |
| L2 | `tb_matvec` 4 seeds | dp | PASS (K=1024/3584/256/2048) |
| L2 | `tb_matvec_ng` | dp | PASS **NG 1..4 + 36 + 48** x {g128,g64} x 4 seeds + cfg_ng envelope self-test |
| L2 | `tb_matvec_g64` | dp | PASS incl. **K=6144 G64=1** (12 cases, 11 rows) |
| L2 | `tb_matvec_chan` + `_g64` | dp | PASS 10 shapes incl. **K=6144** |
| L2 | `tb_mvshim_b` | dp | OK 4 seeds (2 fast/2 slow ui_clk) + sabotage self-test |
| L2 | `tb_seq_layer` 4 seeds | dp | PASS 19 cmds, 3,696 checks each |
| L2 | `tb_layershim_c` 4 seeds | dp | PASS T1-T8 each |
| L2 | `tb_topk` 4 seeds | dp | PASS 19 cases, 545,631 elements, 288 AMAX checks + 5 self-tests |
| L2 | `tb_seq_all` (lint/seq/guard/lat/sideband) | dp | PASS — see directed rows below |
| L2 | `tb_seq_offifo` | dp | OK 3 depths x {axil, blat 0, blat 8} + 24 race + 8 stream races + depth self-test |
| L2 | `tb_bfab` + `tb_seq_burst` | dp | PASS 4 seeds x blat {0,4,8} + 4 E_AXI cases |
| L2 | `tb_ru2_diff` (differential vs frozen `tb/legacy/`) | dp | PASS `vecalu` 4 seeds + 2 strict + 4 self-tests; `vecnorm` 4 seeds x 120 vectors + 3 self-tests |
| L3 | `regen_gate.sh` (0.8B byte-identical) | dp x3 / snoke | **1 host-fault trip, 3 PASS** — see below |
| H1 | `tb_seq_chip` — frozen 2026-08-08 `w3` stream | snoke | PASS 2,272,141 cyc, tokens 3, tcnt 6 — **matches pre-R-b RTL exactly**, `evidence/rung4/gate_chip_nch1.log:76,84` |
| H2 | `tb_seq_chip_fast` — `w3` REGENERATED by the R-b emitter | snoke | PASS `lay_s1` 1,355,737 cyc; `tok2_s1` **2,272,141 cyc — identical to H1** |
| H3 | `chat_i1_gate` 2 scenarios | snoke | PASS `chat_i1` 4 launches / 31,380,028 cyc; `chat_i1b` 31,380,220 cyc |
| H4 | `tb_model_v2_all` 4 seeds, real 0.8B weights | snoke | PASS 22,350 cmds, **1,900,014 checks bit-exact** on each of s1-s4 |

141 `SEQ PASS` banners across the sequencer targets on darthplagueis.

### The directed cases the walls added (all inside `tb_seq_all`)

* **R5, 15-bit scratch homes** — `seq_h_hiaddr`: 16 records, 8,320 scratch
  words of which **8,192 sit above word 16383**; LDC/EMB/MOVX/MOVY all
  round-trip. Includes the **1,536-word XWIN MOVX** that closes the R4
  follow-on. `SEQ PASS (writes 12066, reads 12160, scratch 8320)`.
* **R5, burst window move** — `tb_bfab` **T2** proves the layer scratch
  window equals the AXI-Lite SWIN window both directions with **w=32767
  reachable**, and **T3** proves the **3 decode holes** (0x5_0000 is now one)
  answer DECERR with every beat returned/consumed.
* **R6, EMBLOG2** — `seq_h_embrow`: 7 records, 3,136 scratch words at
  **EMBLOG2=12 (4096 B rows)**. Guard control both ways: in an
  as-synthesized build (`+define+SYNTHESIS`) illegal writes of 7 and 14 are
  **rejected, register still 12**; in a normal build the same write is loud
  (`$error`) — `OK: illegal EMBLOG2 write is loud in simulation`.
* **R4, MAX_NG 48** — `tb_matvec_ng` now sweeps **NG 36 and 48** alongside
  1..4, and `tb_matvec_g64` carries **K=6144 at g64 (3 scale beats)**, the
  first shape needing three.
* **R3, N=2048** — `tb_vecnorm` runs the nlog2=11 case twice and the
  `cfg_nlog2>=12` envelope guard self-test trips with its own message.

### The one RED, and why it is not this tree

`regen_gate.sh` tripped **once** on darthplagueis at 18:35:52 with

    ref/w4a8_ref.py:161  assert np.abs(acc).max() < (1 << 31)
    via gen_model_script.py:509  (LM head)

Re-run on the same host and tree: **REGEN_GATE_PASS**. Third run: PASS.
Authoritative cross-host run on **snoke** (python 3.12.3, torch 2.12.0+cpu vs
darthplagueis' 3.13.9 / 2.6.0+cu124): **PASS**, frozen sha
`a69864d2…` matched, `argmax per step=[561,314,279,369,279,6511]`,
`FABLE5_CALIB_STATS=<unset>` recorded in every header.

This is **instance 7 of an already-documented host fault**, not a regression:

* `evidence/qwen2b/q2/v3/V3.md` §6 records six trips in one day, of which
  trips **1 and 6 are this exact signature** — same gate, same 0.8B model,
  same salience-OFF path, same `gen_model_script.py:509` LM-head call site,
  same "retry ⇒ PASS".
* V3.md §6 proves the guard **cannot fire on correct arithmetic**: `acc` is a
  sum of `g` products of two int8 arrays, so `|acc| <= g*128*128` — for the
  LM head's `w4_group=128` that ceiling is **2,097,152, about 1000x below
  2^31**, *for any operand content whatsoever*. No data, no `res_scale`, and
  no quantizer rule can make this assertion trip legitimately.
* The failing run was bit-identical to the passing runs up to the fault:
  step 0 printed `argmax= 561`, matching all three green runs, before a
  single int64 reduction returned an impossible value.

Both outcomes are recorded per the Track R instruction:
`sim_units.log` (the trip), `regen_gate_rerun_darthplagueis.log`,
`regen_gate_rerun2_darthplagueis.log`, `regen_gate_snoke.log` (authoritative).

`regen_gate.sh` now also **echoes the computed sha next to the gold one**
before comparing, so future PASS logs are self-certifying instead of asking
the reader to trust that the comparison ran on the hash it claims.
`regen_gate_snoke_selfcert.log` is that script re-run on snoke after the
change — `gold` and `got` both print `a69864d2…`, `REGEN_GATE_PASS`.

## Frozen-stream integrity

`git status --porcelain` was **empty before the gate** and shows **only the
new `evidence/qwen2b/rb/` logs after**. This is a real check, not a
formality: `make tb_matvec` **regenerates the tracked `tb/vec_s1..s4`
vectors in place**, and `git diff --stat` over them is **empty** — they
regenerated byte-identical under the R-b tree. The other tracked golden sets
(`tb/vectors/`, the committed `tb/scripts/*.txt`) are read-only here and are
likewise untouched. No frozen stream was modified by this gate.

## Follow-ons

* **The darthplagueis arithmetic fault is now blocking-adjacent.** V3.md §6
  already asked for a memtest / under-load int64 soak before the next long
  numeric campaign; this gate is the 7th trip and the 3rd on the frozen 0.8B
  salience-OFF path. Until that soak runs, **snoke is the authoritative host
  for any numeric reference run**, and any darthplagueis numeric RED must be
  re-run cross-host before it is believed.
* `tb_seq_chip` / `chat_i1_gate` are single-stream gates by construction (not
  4-seed); the 4-seed obligation is carried by `tb_model_v2_all` and the unit
  set. Unchanged from rung 4, restated here so it is not mistaken for a gap.
* The `w3` chip artifacts are regenerated by `tb_seq_chip_fast`, so H1's
  "frozen 2026-08-08 stream" check is only reproducible **before** H2 runs in
  a fresh tree. If that ordering ever matters again, snapshot `w3` first — or
  better, commit the `.e.seq` sha alongside the gate so the anchor does not
  depend on an unrelated older log surviving.
* **R8 must check the block design's `s_axib` port width** (17 bits) and the
  0x6_0000 / 128 KiB address assignment. `rtl/layer_chan_ipi.v` is the one
  R-b-changed file with zero sim coverage; see the provenance note above.
