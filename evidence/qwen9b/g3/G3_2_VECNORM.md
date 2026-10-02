# G3.2 — `vecnorm_unit` at N = 4096 (spec §4.2, W2)

**Task 8 of the Qwen3.5-9B migration.  Base tree `ec08638`.  Simulation
only — no synthesis, no board.**  Every number below is labelled
**M**(easured), **D**(erived), **T**(ranscribed from another gate),
**E**(stimate) or **S**(tated as an intent), and every numeric step went
through `evidence/qwen9b/run.sh`.

**The claim.** `rtl/vecnorm_unit.sv` now runs `cfg_nlog2 = 12`
(N = 4096, the 9B hidden size) bit-exactly against `layer_fixed`'s
`rmsnorm_fx` / `l2norm_fx`, on four seeds, with the N = 2048 (2B) set kept
as a regression and proven **byte-identical** to `ec08638`.  The
`VNW_HW_MAX` datapath twin G3.1 introduced is lifted 2048 → 4096, and both
sim-only envelope guards move up one power of two with it.

**Interpreter, per host — probed with `test -x`, never by name** (the plan's
standing hazard: `ref/.venv/bin/python` is a DANGLING SYMLINK on snoke):

| host | `/home/cah/.venv/bin/python` | `ref/.venv/bin/python` | used for |
|---|---|---|---|
| snoke | **exists** (numpy 2.4.6) | ABSENT | every Verilator target, both vector generators (`VECPY=`/`GENPY=`) |
| darthplagueis | ABSENT | **exists** | the citation set only (pure-python, no obj_dir) |

`FABLE5_RS_F` was **never exported** in any run (plan A2.5); every log's
provenance header records `FABLE5_RS_F=unset`.

---

## 1. The width table — M, read out of the post-change tree

Seven sites move.  "before" is `git show ec08638:<file>`; "after" is the
committed tree.

| # | site | before | after | why |
|---|---|---|---|---|
| 1 | `rtl/vecnorm_unit.sv:163` `logic [12:0] cnt, n_total;` | `[11:0]` | **13 b** | n_total = 1 << 12 = 4096 must be REPRESENTABLE.  A counter exactly as wide as the largest `n_log2` wraps to 0 — R-b's deadlock, one power of two up (§4) |
| 2 | `rtl/vecnorm_unit.sv:167` `oidx` | `[11:0]` | **13 b** | OUT's issue cursor is compared against n_total (`rtl/vecnorm_unit.sv:217`); a narrower cursor never reaches 4096 |
| 3 | `rtl/vecnorm_unit.sv:168` `ecnt` | `[11:0]` | **13 b** | OUT's retire cursor, compared against n_total (`rtl/vecnorm_unit.sv:412`) |
| 4 | `rtl/vecnorm_unit.sv:110-111` `xbuf [4096]` / `wbuf [4096]` | `[2048]` | **4096** | the element and weight stores themselves |
| 5 | `rtl/vecnorm_unit.sv:97` `input wire [11:0] w_waddr` | `[10:0]` | **12 b** | 4096 wbuf entries need a 12-bit write address; at 11 bits the top half of wbuf is unreachable |
| 6 | `rtl/layer_chan.sv:537` `logic [11:0] vn_waddr;` | `[10:0]` | **12 b** | the driver of site 5, and it must be as wide as the port |
| 7 | `rtl/vecnorm_unit.sv:432` `cfg_nlog2 >= 4'd13` | `>= 4'd12` | **≥ 13** | the sim-only envelope `$fatal`; the wrap it guards is now one power of two higher |

Three consequential edits ride with them, each a slice of a widened
counter and none of them a new decision:

| site | before | after |
|---|---|---|
| `rtl/vecnorm_unit.sv:285` `n_total <= 13'd1 << cfg_nlog2;` | `12'd1` | `13'd1` — the wrap site the `$fatal` guards, widened with `n_total` |
| `rtl/vecnorm_unit.sv:231-232` `xbuf[oidx[11:0]]` / `wbuf[oidx[11:0]]` | `oidx[10:0]` | 12-bit index into a 4096-deep array |
| `rtl/vecnorm_unit.sv:290` `xbuf[cnt[11:0]] <= s_data;` | `cnt[10:0]` | the FILL write port, same reason |
| `rtl/layer_chan.sv:1720` `vn_waddr <= ld_i[11:0];` | `ld_i[10:0]` | `ld_i` was already 13 b (G3.1); only the slice moved |

## 2. The two that do NOT move, argued in the RTL rather than left implicit

Both now carry a `DOES NOT WIDEN` comment beside the declaration, so the
next reader does not have to re-derive it — **D**, arithmetic, checked
against the measured runs:

* **`ss_acc` stays 48 b** — `rtl/vecnorm_unit.sv:164-166`.  **D, and it is
  an ARGUMENT, not a measurement.**  The bound is `N · 32767²`, reached
  only by an all-saturated vector.  Exactly: `32767² = 1 073 676 289`, so
  `2048 · 32767² = 2 198 889 039 872 < 2^41` and
  **`4096 · 32767² = 4 397 778 079 744 < 2^42`** — the 48-bit accumulator
  keeps **6 bits** of head room at N = 4096.  (The spec's `< 2^42` / "at
  4096 it is 2^43" and this RTL comment's `< 2^43` are the same claim
  stated one bit conservatively; the conclusion is unaffected, which is why
  neither was changed.)
  **Where the MEASURED coverage stops.**  The saturated pattern `X_SAT`
  (`16'h7FFF` / `16'h8000` alternating) is exercised on all four seeds —
  but only in `tb_vecnorm_diff`, which is capped by the frozen 1024-deep
  legacy twin: every seed prints `n_max=1024` in
  `evidence/qwen9b/g3/84_tb_suite.log`.  So **the worst case for `ss_acc`
  at N = 4096 is never simulated**; cases 7/8 run 4096 elements but from
  random / `layer_fixed`-scaled data, not from saturation.  The 6-bit
  margin above is the whole of the evidence, and it is arithmetic.
* **`rs_p` stays 6 b** — `rtl/vecnorm_unit.sv:175-177`.  It carries
  `2·in_f + n_log2`, at most `2·15 + 12 = 42`, and 6 bits hold 63.  The
  spec's own row says the same thing and is unchanged.
* **`cfg_nlog2` stays `[3:0]`** — `rtl/vecnorm_unit.sv:86`.  12 fits in
  four bits; widening it would have been a change with no consumer.  This
  is why the *guard*, not the port, is what moved.

## 3. The retired VNW escape and the lifted datapath twin — the taxonomy

**Task 7 (G3.1) already retired the escape.**  This gate did **not**
re-implement it, per the controller's ruling; it lifted the DATAPATH twin
that the escape's retirement left standing alone.  Stating both halves so
the record is one story:

| name | kind (G3_1_ISA §2) | at `ec08638` | after G3.2 | owner |
|---|---|---|---|---|
| `Mach.VNW_MAX` | **GEOMETRY** — what a model may ask for | 4096 | 4096 (unchanged) | H, the checkpoint |
| `Mach.VNW_ISA_MAX` | **FIELD** — what `ARG0[12:0]` can carry | 4096 (lifted at G3.1; `0` no longer encodes 2048) | 4096 (unchanged) | G3.1 / Task 7 |
| `Mach.VNW_HW_MAX` | **DATAPATH** — how deep `vecnorm_unit`'s wbuf actually IS | **2048** | **4096** | **G3.2 / this gate** |

`ref/gen_layer_script.py:953` `VNW_HW_MAX = 4096`, with the three-bound
comment at `ref/gen_layer_script.py:689-702` rewritten so it describes the
4096 state.  **The name is kept even though the three now coincide**: they
answer three different questions and a future geometry moves them
independently — collapsing them would delete the only place the split is
written down.  The emitter assert at `ref/gen_layer_script.py:710-714`
stays for the same reason; its message no longer promises a future task.

`ref/gen_layer_script.py:1395-1402`'s "WHAT STILL REFUSES" docstring named
`Mach.VNW_HW_MAX` as a live refusal owned by Task 8.  It is rewritten:
what still refuses is `Mach.ARG0_KVH_BITS` and the conv bank's channel
capacity (both Task 10).  **This is the one place a reader could otherwise
have been sent to a task that had already run.**

**Consequence worth naming.** With the FIELD max and the DATAPATH max both
at 4096, the emitter can no longer produce a VNW the RTL cannot execute —
`vnw_()`'s three asserts now fire only on a geometry above 4096.  The
`layer_chan` VNW `$fatal` (§4) is therefore reachable only from a
hand-written or corrupted stream, since `ARG0[12:0]` still holds up to
8191.  It stays for exactly that case.

## 4. The two sim-only envelope guards, moved together

| guard | at `ec08638` | after G3.2 | message |
|---|---|---|---|
| `rtl/vecnorm_unit.sv:432` | `cfg_nlog2 >= 4'd12` → *"max 11, N=2048"* | `cfg_nlog2 >= 4'd13` | *"vecnorm_unit: cfg_nlog2 %0d unsupported (max 12, N=4096)"* |  <!--cites:noquote-->
| `rtl/layer_chan.sv:1880-1883` | `arg0[12:0] > 13'd2048` → *"exceeds the 2048-deep vecnorm wbuf (G3.2 widens it)"* | `arg0[12:0] > 13'd4096` | *"exceeds the 4096-deep vecnorm wbuf (G3.2 widened it from 2048)"* |  <!--cites:noquote-->

The block comments that frame them were rewritten too, because both
described the 2048 state and one of them promised the widening as future
work: `rtl/vecnorm_unit.sv:423-429` (the wrap-to-zero rationale, now at 13
bits) and `rtl/layer_chan.sv:1855-1863` (the G3.1 DATAPATH ENVELOPE header,
which now says the vecnorm wbuf has landed at its FINAL 9B depth while the
DN banking, the conv bank and the KV banking are still pre-9B).  The
`layer_chan` VNW opcode doc at `rtl/layer_chan.sv:145-150` and the VNW
decode comment at `rtl/layer_chan.sv:1567-1573` had the same defect and were
rewritten with them.  **So did the normative ISA reference**: `docs/SEQ_ISA.md`
B14.5 said the VNW datapath was unchanged at 2048 and now carries a dated
G3.2 amendment (§11.1a).  **These are simulation gates, not silicon
protection** — spec §2.10's standing hazard is unchanged by this gate.

## 5. The TB family census — spec §7.5 C, which §4.2 had no row for

Every site the spec's block C names, with its disposition.  **M** — the
line numbers on the right are the post-G3.2 tree.

| spec §7.5 C site (pre-G3.2) | what it was | disposition |
|---|---|---|
| `tb/tb_vecnorm.sv:40` `logic [10:0] w_waddr = 0;` | the TB's write-address driver | WIDENED → `tb/tb_vecnorm.sv:44`, `[11:0]`; the write itself at `tb/tb_vecnorm.sv:104`, `12'(i)` |  <!--cites:noquote-->
| `tb/tb_vecnorm.sv:57-59` `xv`/`wv`/`gv [2048]` | stimulus + golden arrays | WIDENED → `tb/tb_vecnorm.sv:61-63`, `[4096]` |  <!--cites:noquote-->
| `tb/tb_vecnorm.sv:9` (the header's cases-5/6 paragraph) | described the 2B geometry and R-b's 11-bit wrap | REWRITTEN → `tb/tb_vecnorm.sv:9-19`: cases 5/6 named as the KEPT regression, cases 7/8 as the 9B geometry, the wrap re-derived at 13 bits with R-b's discovery preserved |
| `tb/tb_vecnorm.sv:65-66` (the watchdog budget) | the 50k budget, justified against N=2048 | REWRITTEN → `tb/tb_vecnorm.sv:68-70`, justified against N=4096.  The budget itself is UNCHANGED at 50 000: the longest case is now ≈ 4096 preload + 4096 feed + 4096 drain + pipeline ≈ 12.4 k negedges (**D**), and no run tripped it |
| `tb/tb_vecnorm.sv:251-268` (cases 5/6) | the N=2048 pair | KEPT VERBATIM as the regression → `tb/tb_vecnorm.sv:255-266`, with a comment saying why; cases 7/8 ADDED at `tb/tb_vecnorm.sv:267-277` |
| `tb/tb_vecnorm_diff.sv:51` `logic [10:0] w_waddr` with its rationale at `:48-50` | 11 bits, fed `[9:0]` to the frozen 10-bit legacy port | WIDENED → `tb/tb_vecnorm_diff.sv:55`, `[11:0]`; rationale rewritten at `tb/tb_vecnorm_diff.sv:48-54` |  <!--cites:noquote-->
| `tb/scripts/gen_seq_c_vectors.py:233-241`, comment `:236` | the DELIBERATE N=2048 freeze | PARAMETERIZED, not moved → `tb/scripts/gen_seq_c_vectors.py:236`, `vecnorm_n_vectors(rng, out, n)`; called twice at `tb/scripts/gen_seq_c_vectors.py:281-282` |
| `tb/scripts/gen_seq_c_vectors.py:246-251` (the file names bake 2048 in) | `rms2048_*` / `l2n2048_*` literals | the names are now derived from `n` (`tb/scripts/gen_seq_c_vectors.py:254-260`), so the 2048 names are UNCHANGED and `rms4096_*` / `l2n4096_*` are new.  **The predicted rename ripple did not reach `tb/Makefile`** — the Makefile passes a `+seqdir=` DIRECTORY, never a file name; the only ripple was into `tb/tb_vecnorm.sv` |

**One thing the differential harness cannot do, stated rather than
implied.**  `tb_vecnorm_diff` diffs against `tb/legacy/vecnorm_legacy.sv`, a
FROZEN copy whose `xbuf`/`wbuf` are 1024 deep and whose `w_waddr` is 10 b.
It therefore still runs `n_log2 <= 10` only, exactly as before.  **There is
no legacy twin at N=2048 or N=4096**, so depths above 1024 are covered by
`tb_vecnorm` against the `layer_fixed` goldens, not differentially.  That
was already true at 2048; G3.2 does not change it, and the harness now says
so at `tb/tb_vecnorm_diff.sv:48-54`.

## 6. The 2048 regression, and the 4096 set — M

`tb/scripts/gen_seq_c_vectors.py` draws every case from **one** shared
`numpy` Generator consumed in order, so an insertion anywhere but the END
silently re-rolls everything after it.  The 4096 call is therefore appended
**after** the 2048 call (`tb/scripts/gen_seq_c_vectors.py:281-282`), and
that is proven, not asserted, by
`evidence/qwen9b/g3/g32_regression_2048.sh` — which regenerates the
`ec08638` generator out of git, runs the current one through the normal
`make seq_c_vectors` path, and `cmp`s every file the old one produced.

Log `evidence/qwen9b/g3/90_regression_2048_bytes.log`, host snoke:

```
G32_REGRESSION_2048: identical=32 differs=0 new4096=20
G32_REGRESSION_2048 PASS — the N=2048 regression is BYTE-IDENTICAL to
  ec08638 on all 4 seeds, and the N=4096 set is new and 4096 long
```

**32 = 4 seeds × 8 files** — dynq16_cases.txt, probe8_cases.txt,
epsnorm_cases.txt and the six rms2048_* / l2n2048_* hex files under
`tb/vecseq/` —
**every file the pre-G3.2 generator emitted is byte-identical**, so the
DYNQ16 and EPS-NORM cases that `tb_vec_alu` and `tb_vecnorm` also consume
are untouched.  **20 = 4 seeds × 5 new files**, each checked to be absent
at `ec08638` and exactly 4096 lines long.

The new cases in `tb_vecnorm`:

| case | mode | N | `cfg_nlog2` | in_f / out_f | vectors |
|---|---|---|---|---|---|
| 7 | 2 (l2norm, no weights) | **4096** | **12** | 8 / 14 | `l2n4096_{x16,y16}.hex` |
| 8 | 0 (rmsnorm, 1+w) | **4096** | **12** | 8 / 8 | `rms4096_{x16,w14,y16}.hex` |

Case 8 preloads 4096 weights, so it **writes `wbuf[4095]`** — the entry an
11-bit `w_waddr` could not address — and then reads it back through the OUT
pipeline.  That is the site-5/6 widening under test, not just the counters.

## 7. The `+guardtest` string move, and why it does not pass for the wrong reason

`tb/Makefile`'s self-test deliberately requires the guard's OWN message as
well as a non-zero exit, so the expected string is part of the gate and had
to move with the guard:

| `tb/Makefile` | at `ec08638` | after G3.2 |
|---|---|---|
| `tb/Makefile:309` (the banner) | *"cfg_nlog2 >= 12 envelope guard MUST trip"* | *"cfg_nlog2 >= 13 …"* |
| `tb/Makefile:315` (the `case` arm) | `*"cfg_nlog2 12 unsupported"*` | `*"cfg_nlog2 13 unsupported"*` |
| `tb/Makefile:316` (the failure text) | `cfg_nlog2=12 did NOT trip …` | `cfg_nlog2=13 …` |
| `tb/Makefile:322` (the OK banner) | `… N=2048 nlog2=11 x2` | `… N=2048 nlog2=11 x2, N=4096 nlog2=12 x2` |

`tb/tb_vecnorm.sv:227` pokes `cfg_nlog2 = 4'd13` (was `4'd12`) and
`tb/tb_vecnorm.sv:233`'s miss message moved with it.

**The negative control — M, log
`evidence/qwen9b/g3/91_guardtest_message.log`.**  The raw `+guardtest` run,
captured on its own:

```
[34000] %Fatal: vecnorm_unit.sv:433: Assertion failed in TOP.tb_vecnorm.dut: vecnorm_unit: cfg_nlog2 13 unsupported (max 12, N=4096)
=== rc: 134
```

`/usr/bin/grep -c 'cfg_nlog2 13 unsupported'` on that log is **1** and
`/usr/bin/grep -c 'cfg_nlog2 12 unsupported'` is **0**.  So the old
Makefile string is **absent from the new output**: had the expected string
NOT been moved, the self-test would have printed `SELFTEST FAIL` and
`exit 1` — it could not have passed vacuously.

**The positive half is cases 7/8.**  `cfg_nlog2 = 12` is now LEGAL, and the
proof that the guard did not simply move to "always fires" is that the same
DUT runs 4096 elements to completion, bit-exactly, on four seeds.  A guard
that only refused would fail those cases.

## 8. The Verilator suite — 4 seeds, snoke, one obj_dir per target

One invocation of the full target list, through the provenance wrapper, on
snoke (Verilator 5.020, `-Wall`, `--timing`).  Log
`evidence/qwen9b/g3/84_tb_suite.log`, `=== rc: 0`:

| target | obj_dir | result |
|---|---|---|
| `tb_vecnorm` | `obj_dir_tb_vecnorm` | 4 seeds × 8 cases PASS + the envelope self-test.  Per seed: *"EPS-NORM: 68 cases bit-exact (k -14..17, scale_max 65535)"*, *"N=2048: l2norm + rmsnorm bit-exact (cfg_nlog2 = 11)"*, *"N=4096: l2norm + rmsnorm bit-exact (cfg_nlog2 = 12)"* |
| `tb_vecnorm_diff` | `obj_dir_tb_vecnorm_diff` | 4 seeds × 120 vectors bit-exact + **3 sabotage cases, all of which failed as required** (`+sabotage=1/2/3`) |
| `tb_layer_chan` | `obj_dir_tb_layer` | 4 seeds, *"752 cmds, 76941 checks bit-exact"* on `layerv2_s1..s4` |
| `lint_seq` | — | `vec_alu`, `vecnorm_unit` and `layer_chan` all `-Wall` clean, zero warnings |

**Output is pristine**: the only non-`PASS`/`OK` lines in the whole log are
Verilator's own `$finish` notices and the deliberate `Aborted (core
dumped)` from the `+guardtest` self-test.

**One host per obj_dir, and it was snoke for all four.**  No target was
built or run from darthplagueis during this gate; the only work done there
was the citation set, which touches no obj_dir.

## 9. Post-G3.2 landmarks for every PRE-G3.2 row

The spec's §4.2 box, the §7.5 C box and
`docs/QWEN35_NEXT_FEASIBILITY.md` §2.3's box all point here.  Every row
carries `<!--cites:noquote-->` for the same reason theirs do: the `was`
column quotes source this gate rewrote, deliberately, so the two states can
be read side by side.

| pre-G3.2 subject | was | now |  <!--cites:noquote-->
|---|---|---|  <!--cites:noquote-->
| the element counters | `rtl/vecnorm_unit.sv:159` `logic [11:0] cnt, n_total;` | `rtl/vecnorm_unit.sv:163`, `[12:0]` |  <!--cites:noquote-->
| the OUT cursors | `rtl/vecnorm_unit.sv:161-162` `oidx` / `ecnt` `[11:0]` | `rtl/vecnorm_unit.sv:167-168`, `[12:0]` |  <!--cites:noquote-->
| the sum-of-squares accumulator | `rtl/vecnorm_unit.sv:160` `logic [47:0] ss_acc;` with a trailing 2048 comment | `rtl/vecnorm_unit.sv:164-166`, unchanged at 48 b, with a `DOES NOT WIDEN` note above it |  <!--cites:noquote-->
| the rsqrt binary point | `rtl/vecnorm_unit.sv:169` `logic [5:0] rs_p;` | `rtl/vecnorm_unit.sv:175-177`, unchanged at 6 b, with its own `DOES NOT WIDEN` note |  <!--cites:noquote-->
| the element / weight stores | `rtl/vecnorm_unit.sv:106-107` `xbuf [2048]`, `wbuf [2048]` | `rtl/vecnorm_unit.sv:110-111`, `[4096]` |  <!--cites:noquote-->
| the weight write port | `rtl/vecnorm_unit.sv:93` `input wire [10:0] w_waddr,` (comment `:90-91`) | `rtl/vecnorm_unit.sv:97`, `[11:0]` (comment `rtl/vecnorm_unit.sv:94-95`) |  <!--cites:noquote-->
| the wrap site | `rtl/vecnorm_unit.sv:277` `n_total <= 12'd1 << cfg_nlog2;` | `rtl/vecnorm_unit.sv:285`, `13'd1` |  <!--cites:noquote-->
| the buffer read index | `rtl/vecnorm_unit.sv:223-224` `xbuf[oidx[10:0]]` | `rtl/vecnorm_unit.sv:231-232`, `oidx[11:0]` |  <!--cites:noquote-->
| the FILL write index | `rtl/vecnorm_unit.sv:282` `xbuf[cnt[10:0]]` | `rtl/vecnorm_unit.sv:290`, `cnt[11:0]` |  <!--cites:noquote-->
| the unit's envelope guard | `rtl/vecnorm_unit.sv:424-426`, `>= 4'd12`, *"max 11, N=2048"* | `rtl/vecnorm_unit.sv:432-434`, `>= 4'd13`, *"max 12, N=4096"* (block comment `rtl/vecnorm_unit.sv:423-429`) |  <!--cites:noquote-->
| the module header's N bound | `rtl/vecnorm_unit.sv:11-18` | `rtl/vecnorm_unit.sv:11-24` |  <!--cites:noquote-->
| the vecnorm weight address | `rtl/layer_chan.sv:537` `logic [10:0] vn_waddr;` | `rtl/layer_chan.sv:537`, `[11:0]` |  <!--cites:noquote-->
| the VNW preload write | `rtl/layer_chan.sv:1720` `vn_waddr <= ld_i[10:0];` | `rtl/layer_chan.sv:1720`, `ld_i[11:0]` |  <!--cites:noquote-->
| the VNW opcode doc | `rtl/layer_chan.sv:146-149` | `rtl/layer_chan.sv:146-150` |  <!--cites:noquote-->
| the VNW decode comment | `rtl/layer_chan.sv:1567-1573` | `rtl/layer_chan.sv:1567-1573` |  <!--cites:noquote-->
| the `layer_chan` VNW guard | `rtl/layer_chan.sv:1877-1879`, `> 13'd2048` | `rtl/layer_chan.sv:1880-1883`, `> 13'd4096` |  <!--cites:noquote-->
| the datapath twin | `ref/gen_layer_script.py:699` `VNW_HW_MAX = 2048` | `ref/gen_layer_script.py:703`, 4096 (comment `ref/gen_layer_script.py:689-702`) |  <!--cites:noquote-->
| the emitter's HW assert | `ref/gen_layer_script.py:706-709` | `ref/gen_layer_script.py:710-714` |  <!--cites:noquote-->
| "WHAT STILL REFUSES" | `ref/gen_layer_script.py:1393-1395` names `VNW_HW_MAX` | `ref/gen_layer_script.py:1395-1402`, which no longer does |  <!--cites:noquote-->
| the TB write-address driver | `tb/tb_vecnorm.sv:40` `logic [10:0] w_waddr = 0;` | `tb/tb_vecnorm.sv:44`, `[11:0]` |  <!--cites:noquote-->
| the TB arrays | `tb/tb_vecnorm.sv:57-59` `[2048]` | `tb/tb_vecnorm.sv:61-63`, `[4096]` |  <!--cites:noquote-->
| the TB header | `tb/tb_vecnorm.sv:9-15` | `tb/tb_vecnorm.sv:9-19` |  <!--cites:noquote-->
| the watchdog budget comment | `tb/tb_vecnorm.sv:65-66` | `tb/tb_vecnorm.sv:68-70` |  <!--cites:noquote-->
| the N=2048 case pair | `tb/tb_vecnorm.sv:251-260` | `tb/tb_vecnorm.sv:255-266` (unchanged calls), with the N=4096 pair at `tb/tb_vecnorm.sv:267-277` |  <!--cites:noquote-->
| the guardtest poke | `tb/tb_vecnorm.sv:223` `cfg_nlog2 = 4'd12` | `tb/tb_vecnorm.sv:227`, `4'd13` |  <!--cites:noquote-->
| the diff harness address | `tb/tb_vecnorm_diff.sv:48-51` | `tb/tb_vecnorm_diff.sv:48-55`, `[11:0]` |  <!--cites:noquote-->
| the N=2048 freeze | `tb/scripts/gen_seq_c_vectors.py:233-241` `def n2048_vectors` | `tb/scripts/gen_seq_c_vectors.py:236-262` `def vecnorm_n_vectors(rng, out, n)`, called at `tb/scripts/gen_seq_c_vectors.py:281-282` |  <!--cites:noquote-->
| the baked file names | `tb/scripts/gen_seq_c_vectors.py:234-239` | `tb/scripts/gen_seq_c_vectors.py:254-260`, derived from `n` |  <!--cites:noquote-->
| the Makefile guardtest string | `tb/Makefile:309`, `tb/Makefile:315-316` at 12 | `tb/Makefile:309`, `tb/Makefile:315-316` at 13 |  <!--cites:noquote-->

## 10. Citation drift — the class this gate caused, closed

Six of the seven files this gate edits are cited **by line** from the spec,
the plan and eight committed gate documents.  Mechanized, per the carried
rule, with base `ec08638`.

### 10.1 The sweep — M, log `evidence/qwen9b/g3/80_cite_drift_check.log`

```
files      7 edited files
citations  287 distinct (file, line) pairs
unmoved    196
O3_CITE_DRIFT CHECK FAIL (63 drifted, 28 unresolved, 0 missing, 4 half-mapped)
```

**Class A — 63 DRIFTED** (the source moved).  Disposition: RENUMBER,
never exempt.  `--fix` (log
`evidence/qwen9b/g3/81_cite_drift_fix.log`) applied **61 citations in 15
documents**: the spec, the plan, `docs/QWEN35_NEXT_FEASIBILITY.md`,
`docs/SEQ_ISA.md`, `docs/superpowers/plans/2026-08-12-qwen2b-track-r.md`,
`evidence/qwen2b/q2/v4/GPTQ.md`,
`evidence/qwen2b/rb/seq_isa_ref_sweep.txt`,
`evidence/qwen2b/rc/RC_GATE.md`, `evidence/qwen9b/g2/G2C_CHAIN.md`,
`evidence/qwen9b/g2/g2c_pack_fit.py`, `evidence/qwen9b/o3/BOARD_LOCK.md`,
`evidence/qwen_next/defect_a/defect_b_probe.py`,
`evidence/qwen_next/feas/layer_cmd_census.py`,
`evidence/qwen_next/feas/toks_model.py` and `ref/fidelity_check.py`.
**The other 2 are cited ONLY by `evidence/qwen9b/g3/G3_1_ISA.md`, which
the controller ruled frozen — see §11.**

**Class B — 28 UNRESOLVED** (the cited line was rewritten, so the
quotation names source that no longer exists).  Disposition: the spec's own
§7.6 precedent, exactly as G3.1 applied it — a **dated boxed note per
affected section**, `<!--cites:noquote-->` on each such line, and the
post-G3.2 landmark in §9 above.  **No spec text is deleted or struck (§0).**
Applied to spec §4.2 (7 rows), spec §7.5 block C and its
`gen_seq_c_vectors.py` row, and `docs/QWEN35_NEXT_FEASIBILITY.md` §2.3
(its own 6-row as-built table and the `n_total` quotation above it).

**A sub-class that is NOT class B, and the distinction is §7.6's own.**
Four citations of `rtl/vecnorm_unit.sv:277,323-325` are **pointers with no
quotation** whose claim — *"N exists only as a shift of `cfg_nlog2`"* — is
still true at the new lines.  §7.6 says an exemption *"is for source that
no longer exists, not for a citation that has merely moved"*, so those were
RENUMBERED to `:285,331-333` by hand and verified against the tree:
`ref/fidelity_check.py:1203`, `ref/fidelity_check.py:1220`,
`ref/layer_fixed.py:659`, `ref/layer_fixed.py:674` and
`evidence/qwen_next/ladder/LADDER.md:251`.  The same lines in the spec and
in the feasibility study **do** carry a quotation of the old text, and
those are class B.

**4 HALF-MAPPED ranges** — one endpoint rewritten, so the tool left the
whole token byte-identical (finding O3).  Dispositioned by hand:

| range | citer | disposition |
|---|---|---|
| `rtl/vecnorm_unit.sv:424-426` | the spec §4.2 | **class B** — it quotes the deleted `$fatal`, so the number stays as the record with `<!--cites:noquote-->`; the new range is `rtl/vecnorm_unit.sv:432-434` (§9) |
| `tb/tb_vecnorm.sv:251-268` | the spec §7.5 C | **class B** for the same reason; the new extent is `tb/tb_vecnorm.sv:255-288` (§9) |
| `rtl/layer_chan.sv:145-148` | `evidence/qwen9b/g3/G3_1_ISA.md:804` | **false positive** — that row is a RECORD of a G3.1 repair and deliberately prints the old range beside the new one (`→ rtl/layer_chan.sv:162-165`).  No action |
| `rtl/layer_chan.sv:149-151` | `evidence/qwen_next/feas/layer_cmd_census.py:61` | **no renumber needed** — it is a pointer at the opcode doc block, and after G3.2 lines 106-108 are still that block's VNW tail plus the ROPET line.  Verified by reading both trees |

### 10.2 `--verify` and the three negative controls — M

| run | log | result |
|---|---|---|
| `--verify` | `evidence/qwen9b/g3/82_cite_drift_verify.log` | **`relocated 61 citation(s) checked against the base content and the citing documents`**.  The 32 remaining complaints are the class-B set and the four half-mapped ranges — the same residue G3.1's own final verify carried (147 of it), and the reason the exit code is 1 |
| `--range-control` | `evidence/qwen9b/g3/85_cite_drift_range_control.log` | **`O3_RANGE_CONTROL: PASS`**, 0 problems — all seven cases, including both single-deleted-endpoint cases and the bare continuation |
| `--check --negative-control` | `evidence/qwen9b/g3/87_cite_drift_negctl_check.log` | **CAUGHT (295 reported)** |
| `--verify --negative-control` | `evidence/qwen9b/g3/88_cite_drift_negctl_verify.log` | **CAUGHT (63 complaints)** |

### 10.3 The OTHER drift class — citations INTO the documents this gate edited

Two documents changed line count: the spec (2532 → 2559) and
`docs/QWEN35_NEXT_FEASIBILITY.md` (1660 → 1673).  `--doc-cites` (log
`evidence/qwen9b/g3/83_cite_drift_doccites.log`) found **22 citations into
them, 4 unmoved, 18 drifted**.  All 17 real ones were hand-fixed in
`docs/superpowers/specs/…-design.md` (×3), the plan,
`evidence/qwen2b/rc/RC_GATE.md`, `evidence/qwen2b/rd/RD_GATE.md`,
`evidence/qwen9b/g2/D_TOL.md`, `evidence/qwen9b/g2/FINAL_BYTELOCK.md` (×2)
and `evidence/qwen9b/g2/G2C_CHAIN.md` (×3), each verified byte-identical to
the base line by `md5sum` before and after.  `--doc-cites --verify` (log
`evidence/qwen9b/g3/86_cite_drift_doccites_verify.log`) reports
**`relocated 18 citation(s) checked against the base content and the citing
files`** with **one** residual complaint:
`evidence/qwen9b/g2/spec_cites_selftest_regression.sh:59` "cites"
`…-design.md:0` — that is the pinned expected-FAIL-count column parsing as
a citation, the known artifact G3_1_ISA §13.2 names, not a real citation.
Its negative control (`evidence/qwen9b/g3/89_cite_drift_doccites_negctl.log`)
is **CAUGHT (18 reported)**.

### 10.4 `spec_cites.py` — measured per document, pre versus now

**The exclusion, spelled out so the columns are derivable.**  Each
`spec_cites` run ends with one `FAIL N` total and prints one classified
line per failure — `EXIST`, `RANGE`, `QUOTE`, `AMBIG` or `ORPHAN`.  The
columns below are **raw / EXIST / non-EXIST**, where non-EXIST = raw −
EXIST is the count of `RANGE`+`QUOTE`+`AMBIG`+`ORPHAN` lines, i.e. what
this gate can actually be blamed for.  `EXIST` is excluded on BOTH sides
because the *pre* column is measured inside a pristine
`git archive ec08638` tree, which has no gitignored evidence file and so
invents EXIST failures that say nothing about citations — G3_1_ISA §13.3's
own method, now shown rather than asserted.  Every triple is countable from
the two cited logs with
`grep -cE '  (QUOTE|RANGE|AMBIG|ORPHAN)  '` and `grep -c '  EXIST  '`
between the `===== <doc>` markers.

**pre** = `evidence/qwen9b/g3/96_spec_cites_pristine_ec08638.log` (it builds
the archive inside the recorded run); **now** =
`evidence/qwen9b/g3/114_spec_cites_r3.log`.

| document | pre raw / EXIST / **non-EXIST** | now raw / EXIST / **non-EXIST** | NEW |
|---|---:|---:|---:|
| `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md` | 19 / 19 / **0** | 0 / 0 / **0** | 0 |
| `docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md` | 4 / 4 / **0** | 0 / 0 / **0** | 0 |
| `evidence/qwen9b/g3/G3_2_VECNORM.md` (this document) | — | 0 / 0 / **0** | 0 |
| `evidence/qwen9b/g3/G3_1_ISA.md` | 0 / 0 / **0** | 0 / 0 / **0** | **0** — §11.3 |
| `docs/SEQ_ISA.md` | 0 / 0 / **0** | 0 / 0 / **0** | 0 |
| `docs/QWEN35_NEXT_FEASIBILITY.md` | 131 / 59 / **72** | 128 / 56 / **72** | **0** |
| `docs/superpowers/plans/2026-08-12-qwen2b-track-r.md` | 36 / 6 / **30** | 35 / 5 / **30** | 0 |
| `evidence/qwen_next/ladder/LADDER.md` | 6 / 1 / **5** | 6 / 1 / **5** | 0 |
| `evidence/qwen9b/g2/G2C_CHAIN.md` | 8 / 8 / **0** | 0 / 0 / **0** | 0 |
| `evidence/qwen9b/g2/D_TOL.md` | 7 / 4 / **3** | 3 / 0 / **3** | 0 |
| `evidence/qwen9b/g2/FINAL_BYTELOCK.md` | 0 / 0 / **0** | 0 / 0 / **0** | 0 |
| `evidence/qwen2b/rc/RC_GATE.md` | 27 / 23 / **4** | 27 / 23 / **4** | 0 |
| `evidence/qwen2b/rd/RD_GATE.md` | 8 / 7 / **1** | 8 / 7 / **1** | 0 |
| `evidence/qwen2b/q2/v4/GPTQ.md` | 6 / 2 / **4** | 6 / 2 / **4** | 0 |
| `evidence/qwen9b/o3/BOARD_LOCK.md` | 1 / 1 / **0** | 0 / 0 / **0** | 0 |

**Zero new non-EXIST failures anywhere**, including
`evidence/qwen9b/g3/G3_1_ISA.md` now that §11.3's citation maintenance has
landed.  The raw totals differ between the columns only because the working
tree HAS the gitignored evidence files the archive lacks; the `72 / 72` on
the feasibility study is the same figure G3.1 reported and is now visible
as `131 − 59` versus `128 − 56`.

*(Two earlier rounds of the same sweep are kept because dispositions were
decided against them: `evidence/qwen9b/g3/92_spec_cites.log`, whose one
extra spec failure was a bare `G3_2_VECNORM.md` with no directory in the
§7.5 note, and `evidence/qwen9b/g3/95_spec_cites_r2.log` /
`evidence/qwen9b/g3/108_spec_cites_clean.log`, which predate the review
round and still show `G3_1_ISA.md` at 2.)*

`--selftest` with the plan's path passed explicitly is
`evidence/qwen9b/g3/93_spec_cites_selftest.log` — **`SELFTEST: PASS`**.
`evidence/qwen9b/g2/spec_cites_selftest_regression.sh` is
`evidence/qwen9b/g3/94_spec_cites_selftest_regression.log` —
**`SPEC_CITES_REGRESSION PASS`**, with **every pinned count unmoved**:
RC_GATE 27, RD_GATE 8, FINAL_BYTELOCK 0, G2A_HOST 0, D_TOL 3,
RUNG_INT8_STATE 2, spec 0, plan 0; its own `--selftest` 6/6 CAUGHT on four
documents, and the counter-experiment still shows the `os.devnull` sentinel
suppressing 23 real RC_GATE failures.

### 10.5 The log inventory

| log | what |
|---|---|
| `evidence/qwen9b/g3/80_cite_drift_check.log` | the RED half: 63 drifted / 28 unresolved / 4 half-mapped |
| `evidence/qwen9b/g3/81_cite_drift_fix.log` | `--fix`, 61 citations in 15 documents |
| `evidence/qwen9b/g3/82_cite_drift_verify.log` | `--verify`, 61 relocated checked |
| `evidence/qwen9b/g3/83_cite_drift_doccites.log` | `--doc-cites`, 18 of 22 drifted |
| `evidence/qwen9b/g3/84_tb_suite.log` | the four Verilator targets, snoke, `rc: 0` |
| `evidence/qwen9b/g3/85_cite_drift_range_control.log` | `--range-control` PASS |
| `evidence/qwen9b/g3/86_cite_drift_doccites_verify.log` | `--doc-cites --verify`, 18 relocated checked |
| `evidence/qwen9b/g3/87_cite_drift_negctl_check.log` | check negative control CAUGHT |
| `evidence/qwen9b/g3/88_cite_drift_negctl_verify.log` | verify negative control CAUGHT |
| `evidence/qwen9b/g3/89_cite_drift_doccites_negctl.log` | doc-cites negative control CAUGHT |
| `evidence/qwen9b/g3/90_regression_2048_bytes.log` | the N=2048 byte-identity control, PASS |
| `evidence/qwen9b/g3/91_guardtest_message.log` | the raw `+guardtest` message, `rc: 134` |
| `evidence/qwen9b/g3/92_spec_cites.log` | `spec_cites`, round 1 |
| `evidence/qwen9b/g3/93_spec_cites_selftest.log` | `--selftest` PASS |
| `evidence/qwen9b/g3/94_spec_cites_selftest_regression.log` | the pinned-count regression PASS |
| `evidence/qwen9b/g3/95_spec_cites_r2.log` | `spec_cites`, final |
| `evidence/qwen9b/g3/96_spec_cites_pristine_ec08638.log` | the `ec08638` baseline for the *pre* column |
| `evidence/qwen9b/g3/97_*` … `112_*` | §12 — the committed-tree re-runs |
| `evidence/qwen9b/g3/113_cite_drift_fix_g3_1_isa.log` | **fix round 1** — the `G3_1_ISA.md`-scoped `--fix` (§11.3) |
| `evidence/qwen9b/g3/114_spec_cites_r3.log` | **fix round 1** — the per-document sweep §10.4's *now* column reads |
| `evidence/qwen9b/g3/115_*` … `118_*` | fix round 1, pre-restyle on `c0c3800` — the round that found §12.1's self-inflicted complaint |
| `evidence/qwen9b/g3/119_*` … `125_*` | **fix round 1, final** — §12.1, the whole citation set on `71f2953` |

**Names start at `80_` on purpose**: `00_`–`70_` belong to G3.1 and a
committed gate document cites them by line, so nothing here reuses one.

## 11. Deviations, declared

1. **Files touched beyond the brief's list.**  The brief names seven; the
   citation-drift rule the controller carried forward requires the citing
   documents to be repaired in the same change.  Added to the pathspec, by
   name: `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md`,
   `docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md`,
   `docs/QWEN35_NEXT_FEASIBILITY.md`, `docs/SEQ_ISA.md`,
   `docs/superpowers/plans/2026-08-12-qwen2b-track-r.md`,
   `ref/fidelity_check.py`, `ref/layer_fixed.py`,
   `evidence/qwen_next/ladder/LADDER.md`,
   `evidence/qwen_next/feas/layer_cmd_census.py`,
   `evidence/qwen_next/feas/toks_model.py`,
   `evidence/qwen_next/defect_a/defect_b_probe.py`,
   `evidence/qwen2b/q2/v4/GPTQ.md`,
   `evidence/qwen2b/rb/seq_isa_ref_sweep.txt`,
   `evidence/qwen2b/rc/RC_GATE.md`, `evidence/qwen2b/rd/RD_GATE.md`,
   `evidence/qwen9b/g2/G2C_CHAIN.md`, `evidence/qwen9b/g2/D_TOL.md`,
   `evidence/qwen9b/g2/FINAL_BYTELOCK.md`,
   `evidence/qwen9b/g2/g2c_pack_fit.py`,
   `evidence/qwen9b/o3/BOARD_LOCK.md`.  **Every one of these is a citation
   renumber or a §7.6 exemption marker, with ONE exception —
   `docs/SEQ_ISA.md`, which needed a substantive correction (§11.1a).  No
   behaviour changes anywhere in the list.**

   1a. **`docs/SEQ_ISA.md` B14.5 stated a falsehood about the datapath this
   gate landed** — found in review, not by me.  Its VNW bullet read *"The
   DATAPATH is unchanged: the vecnorm wbuf is still 2048 deep
   (`Mach.VNW_HW_MAX`) and a longer load still refuses — widening it to
   N=4096 is G3.2."*  **All three clauses are now wrong**, and this is the
   normative ISA reference: it names `Mach.VNW_HW_MAX` by symbol, and that
   symbol reads 4096 at `ref/gen_layer_script.py:703`.  It is the same
   send-a-reader-to-a-task-that-already-ran hazard fixed in
   `ref/gen_layer_script.py:1395-1402`, one file over, and this gate had
   already edited `docs/SEQ_ISA.md` (the `rtl/layer_chan.sv` renumber).
   Fixed the way that file keeps its history — the G3.1 sentence is
   retained verbatim as the record with a dated **AMENDED 2026-09-02**
   block beside it giving the 4096 datapath, the fact that neither side
   refuses 4096 any more, and the note that `layer_chan`'s VNW `$fatal` is
   now reachable only from a hand-built stream.  **The sweep the review
   asked for found two more sites**, both dispositioned:

   | site | what it asserted | disposition |
   |---|---|---|
   | B14.5's VNW bullet | the three false clauses above | CORRECTED — sentence kept, dated amendment added |
   | B12.4 *"VECNORM nlog2 CEILING … `n_log2 = 11` (n = 2048) … counter is 12 bits"* | the pre-G3.2 ceiling, as current | **NOT edited** — B12 carries `SUPERSEDED 2026-09-01 by B14 … RETAINED VERBATIM`, so it is history by construction.  B14.5's new amendment explicitly supersedes this note too, which is where a reader following the chain lands.  What B12.4 says next — *"there is NO command-decode range check"* — **still stands**: `layer_chan`'s five envelope guards cover DNST/DNZ head, CONV, CONVW, VNW length and KVAP/ATTN kvhead, and none of them looks at VN's `arg0[5:2]` |
   | B7's VNW paragraph (*"element COUNT = ARG0[10:0], and 0 ENCODES 2048 … `ld_n`/`ld_i` … both 11 bits"*) | the v1.7 field, as current — falsified by **G3.1**, inherited | POINTER ADDED, **line-count-neutral on purpose** (`docs/SEQ_ISA.md` is cited by line from the spec, the feasibility study and the 2B track-r plan, every one of those citations at a line below 810): the closing `(R-b, 2026-08-13.)` now continues on the same line with a dated `SUPERSEDED — READ B14.5` sentence |

   Nothing else in `docs/SEQ_ISA.md` asserts 2048 / `n_log2 = 11` / "still
   refuses" as CURRENT for VNW; the file's other `2048`s are EMB row bytes
   (B13), the H = 2048 geometry, and the `6144 & 0xFFF` wall-6 record.
2. **One new file:** `evidence/qwen9b/g3/g32_regression_2048.sh`, the
   byte-identity control for §6.  Written rather than run ad hoc so the
   claim is reproducible.
3. **`evidence/qwen9b/g3/G3_1_ISA.md` — citation maintenance only, under a
   controller ruling of 2026-09-02.**  The first cut of this gate left that
   document untouched and it went to **`spec_cites` FAIL 2** with ten stale
   citations.  The ruling: *"read it, do not edit it" was about CONTENT*,
   and the carried Task 6/7 rule renumbers citations in every committed
   gate document an editing task drifts.  The freeze is lifted for
   **citation maintenance ONLY** — no prose, number or conclusion changes.
   Applied, and the document is back to **FAIL 0**:

   | G3_1_ISA site | citation | what was done |
   |---|---|---|
   | §13.1 row 4 (`:744`) | `rtl/layer_chan.sv:537` beside `logic [10:0] vn_waddr;` | **CLASS B** — the source now reads `logic [11:0] vn_waddr;`, so the row keeps its text as the record and gained `<!--cites:noquote-->`.  This was one of the two QUOTE failures |
   | §13.1 row 5 (`:564`) | `ref/gen_layer_script.py:1511` | RENUMBERED → `ref/gen_layer_script.py:2019` (`M.dnst(h, QNS, KN, v_src, …)`) |
   | §13.1 row 6 (`:565`) | `ref/gen_layer_script.py:1494` | RENUMBERED → `ref/gen_layer_script.py:2002` (`for h in range(LR.LNH):`) — the other QUOTE failure; the drift was 8 lines, past `spec_cites`' ±6 tolerance |
   | §13.1 row 8 (`:567`) | `ref/gen_layer_script.py:817` | RENUMBERED → `ref/gen_layer_script.py:1075` (`KVH_MAX = _KVH - 1`; G3.4 moved it again) |
   | §15 `ALU_LEN_MAX` (emitter), *now* | `ref/gen_layer_script.py:1064` | RENUMBERED → `ref/gen_layer_script.py:1375` (`ALU_LEN_MAX = (1 << 14) - 1`) |
   | §15 the DNST emit line, *now* | `ref/gen_layer_script.py:967` | RENUMBERED → `ref/gen_layer_script.py:1224` (`self.C(8, head, …)`) |
   | §15 `ALU_LEN_MAX` (emitter), *was* | `ref/gen_layer_script.py:950` | **LEFT, and `--fix`'s move to `:955` was REVERTED.**  §15's *was* column holds **pre-G3.1** lines: `d2d774b:895` is `ALU_LEN_MAX = (1 << 13) - 1`, exactly what the row quotes.  Mapping it through `ec08638` is a false positive |  <!--cites:noquote-->
   | §15 the DNST emit line, *was* | `ref/gen_layer_script.py:847-848` | **LEFT, same revert, same reason**: `d2d774b:795-796` is the `((a_dec >> 14) << 30)` / `((a_beta >> 14) << 31)` hand-OR the row describes |  <!--cites:noquote-->
   | §13.4a row 12 (`:1150`) | `rtl/layer_chan.sv:145-148` | **LEFT** — a pre-G3.1 number the row prints deliberately beside its repaired form (`→ rtl/layer_chan.sv:162-165`); the HALF-MAPPED report on it is the same false positive |

   > **RE-ANCHORED 2026-09-10 (pre-ship documentation chore).**  The
   > right-hand *RENUMBERED →* column names **HEAD**, not the tree this
   > pass ran against; G3.4 and S3 moved five of these again, and three of
   > them were failing `spec_cites` on this document.  The values this pass
   > itself wrote were, in the row order above, `ref/gen_layer_script.py:1519`,
   > `ref/gen_layer_script.py:1502`, `ref/gen_layer_script.py:827`,
   > `ref/gen_layer_script.py:1069` and `ref/gen_layer_script.py:972`.
   > The two *was*-column
   > reverts and `§13.4a row 12` are deliberately LEFT and are untouched.

   **Mechanized, then dispositioned**, exactly as G3.1 did its own:
   `evidence/qwen9b/o3/o3_cite_drift.py --base ec08638 --only-docs
   'evidence/qwen9b/g3/G3_1_ISA\.md$' --fix` (log
   `evidence/qwen9b/g3/113_cite_drift_fix_g3_1_isa.log`, `FIXED 8
   citation(s) in 1 document(s)`), then the two *was*-column moves reverted
   by hand against `git show d2d774b:ref/gen_layer_script.py`.  **Six
   tokens moved, two were reverted, one exemption marker added, and not one
   line above the end of the document shifted** — the note recording all of
   this is appended as G3_1_ISA §16, after §14, so `G3_1_ISA.md:777` and
   every other citation into it still resolves.

   Three of that gate's statements are **superseded** by this one and are
   listed in its §16 rather than edited in place: its §2 taxonomy row
   *"`VNW_HW_MAX` — 2048 (NEW) … Task 8"*, its §6 *"VNW length above the
   2048-deep vecnorm wbuf"*, and its §14 bullets naming `VNW_HW_MAX` as a
   live refusal and `ARG0[12]` as unexercised.  §3 above carries the
   current values.

4. **Found, not fixed, and NOT caused by this gate:**
   `evidence/qwen9b/g2/G2C_CHAIN.md:427` cites
   `ref/gen_layer_script.py:695` for `Mach.CONV_FIELD_MAX`.  That was
   already wrong at `ec08638` — line 672 there is a `VNW_HW_MAX` comment,
   and `CONV_FIELD_MAX` was at `:737`, now `ref/gen_layer_script.py:766`.
   The drift tool surfaced it only because line 672's content changed.
   Repairing another gate's prose is beyond this brief; recorded here with
   the true line.

   **A SECOND one of exactly this shape, and this gate PROPAGATED it.**
   `docs/QWEN35_NEXT_FEASIBILITY.md:438` and `:477`, and spec §7.3 row 3,
   cite the emitter's `ALU_LEN_MAX` at what was
   `ref/gen_layer_script.py:705` and what `--fix` mechanically moved to
   `ref/gen_layer_script.py:709`.  **Both numbers are wrong and always
   were**: `ec08638`'s line 682 and today's `ref/gen_layer_script.py:709`
   are the same line — the VNW
   assert's message `f"SEQ_ISA v2.0 has NO 0-encodes-the-top escape, so 0
   is 0.")` — while `ALU_LEN_MAX` is at `ref/gen_layer_script.py:1069`.
   The renumber is faithful to the drift map and preserves the error; it
   does not create it.  **`spec_cites` can never catch this pair**: both
   rows carry `<!--cites:noquote-->`, so the quotation beside the citation
   is exempt.  Tabulated beside `evidence/qwen9b/g2/G2C_CHAIN.md:427`
   because it is the same
   class — an already-wrong citation into a file this gate edited:

   | citer | cites | is actually | true line today |
   |---|---|---|---|
   | `evidence/qwen9b/g2/G2C_CHAIN.md:427` | `ref/gen_layer_script.py:695` for `Mach.CONV_FIELD_MAX` | a `VNW_HW_MAX` comment | `ref/gen_layer_script.py:766` |
   | `docs/QWEN35_NEXT_FEASIBILITY.md:438` and `docs/QWEN35_NEXT_FEASIBILITY.md:477`, spec §7.3 row 3 | `ref/gen_layer_script.py:709` (before this gate's renumber, line 682 of the same file) for `Mach.ALU_LEN_MAX` | the VNW assert's message string | `ref/gen_layer_script.py:1069` |

   Likewise `evidence/qwen_next/feas/layer_cmd_census.py:63` still lists
   *"2 VNW n = arg0[10:0] (0 encodes 2048)"*, which **G3.1** falsified when
   it deleted the escape; it is inherited staleness, not new.

5. **Found, not fixed — an `RS_F` configuration trap in the vecnorm unit
   vectors, and this gate DOUBLED it.**  `tb/scripts/gen_seq_c_vectors.py`
   scales the rmsnorm stimulus and computes its golden at
   **`LF.RS_F`** (`tb/scripts/gen_seq_c_vectors.py:251`, `:253`), which
   `b9e0851:ref/layer_fixed.py:74` reads from the **environment**
   (`FABLE5_RS_F`, default 8).  `tb/tb_vecnorm.sv` hard-codes
   in_f = 8 for both rmsnorm cases — `tb/tb_vecnorm.sv:266`
   (case 6, N=2048) and `tb/tb_vecnorm.sv:279` (case 8, N=4096).  **With
   `FABLE5_RS_F=7` exported, the golden is computed at in_f = 7 and the DUT
   is driven at in_f = 8, so `rs_p` differs by 2 and the TB fails as a
   VALUE MISMATCH — for a configuration reason, with no message saying
   so.**  It was already true of case 6 before this gate; case 8 makes it
   two instances.  The l2norm cases are NOT exposed: they use `LF.QKV_F`
   and `LF.NRM_F` (`ref/layer_fixed.py:136-137`), which are plain literals.

   > **CLOSED 2026-09-02 by G3.4 (T10 fix round 3).** This "found, not
   > fixed" is fixed at the root: `tb/scripts/gen_seq_c_vectors.py:57` now
   > pins `RMS_VEC_F = 8` and the two sites above read it instead of
   > `LF.RS_F` (`tb/scripts/gen_seq_c_vectors.py:250-253`), so
   > `FABLE5_RS_F=7` no longer moves the golden out from under
   > `tb/tb_vecnorm.sv`'s `in_f = 8`. The pointers in the paragraph are the
   > post-G3.4 lines; they read lines 239 and 241 until this round, which is
   > this gate's own drift into another gate's document — the citation
   > moved when G3.4 rewrote the function, and G3.4 owed the renumber.
   **Recorded rather than fixed, and the reasoning is the point.**  The
   tempting one-liner — `assert LF.RS_F == 8` in the generator — would
   freeze the value **A2 adopted for 9B** (`RS_F = 7`) and turn a silent
   mismatch into a refusal to generate at all, which is worse.  The
   correct repair is for the generator to RECORD the `in_f` it used
   alongside the vectors and for `run_case` to consume it, i.e. a change to
   the vector-set contract across two files plus a Verilator re-run; it
   belongs to whoever first needs `RS_F`-scaled unit vectors.  Operationally
   the plan's A2.5 forbids exporting `FABLE5_RS_F` across two named scripts —
   `evidence/qwen2b/rc/t4_bytes_unmoved.sh` and `ref/scripts/regen_gate.sh` —
   and this gate applied the same rule to **every** run of its own:
   **every log in this gate records `FABLE5_RS_F=unset`** in its provenance
   header.  *(Narrowed 2026-09-10: this sentence read as though A2.5 itself
   forbade the export across these runs; A2.5 names only those two scripts.)*

## 12. The gate evidence, re-run on a COMMITTED tree

Everything in §6–§8 and §10 was first measured on the working tree; the same
runs were then repeated on the COMMITTED tree so the gate's evidence names a
clean sha rather than `+dirty`.  Two shas are involved and both are clean:
**`71336ab`** (this gate's commit) and **`5ee7005`** (a one-line follow-up that
removed a self-inflicted citation from the §4.2 box — see below).

| log | tree | result |
|---|---|---|
| `evidence/qwen9b/g3/97_tb_suite_committed.log` | **`71336ab`** | the four targets on snoke: `TB_VECNORM OK` (4 seeds, 8 cases, envelope self-test), `TB_VECNORM_DIFF OK` (4 seeds + 3 sabotage), `TB_LAYER_CHAN PASS` ×4 (752 cmds, 76 941 checks each), `lint_seq` silent.  `=== rc: 0` |
| `evidence/qwen9b/g3/98_regression_2048_committed.log` | **`5ee7005`** | `G32_REGRESSION_2048: identical=32 differs=0 new4096=20` → **PASS** |
| `evidence/qwen9b/g3/99_guardtest_committed.log` | **`5ee7005`** | the guard's own message, `=== rc: 134`; `grep -c` on that log is **1** for `cfg_nlog2 13 unsupported` and **0** for `cfg_nlog2 12 unsupported` |
| `evidence/qwen9b/g3/105_cite_drift_verify_clean.log` | **`5ee7005`** | `relocated 61 citation(s) checked`, 32 residual (the class-B + half-mapped set) |
| `evidence/qwen9b/g3/106_cite_drift_doccites_verify_clean.log` | **`5ee7005`** | `relocated 18 citation(s) checked`, 1 residual (the pinned-count artifact in `evidence/qwen9b/g2/spec_cites_selftest_regression.sh`) |
| `evidence/qwen9b/g3/107_cite_drift_range_control_clean.log` | **`5ee7005`** | `O3_RANGE_CONTROL: PASS` |
| `evidence/qwen9b/g3/108_spec_cites_clean.log` | **`5ee7005`** | the §10.4 table's *now* column, re-measured: spec 0, plan 0, this document 0, and every other count identical to `96_spec_cites_pristine_ec08638.log` except `G3_1_ISA.md` |
| `evidence/qwen9b/g3/109_spec_cites_selftest_regression_clean.log` | **`5ee7005`** | `SPEC_CITES_REGRESSION PASS`, every pinned count unmoved |
| `evidence/qwen9b/g3/110_isa_bits_post_g32.log` | **`5ee7005`** | see below |

**The round that found it.**  `evidence/qwen9b/g3/100_cite_drift_verify_committed.log`,
`101_cite_drift_doccites_verify_committed.log` and
`102_cite_drift_range_control_committed.log` are the first pass over the
committed `71336ab`; log 100 reported **34** problems rather than 32, and the
two extra were the spec "still citing" `rtl/vecnorm_unit.sv:323` and `:325`.
`103_cite_drift_verify_r2.log` is the confirmation on the fixed working tree
(back to 32) before that fix was committed.  They are kept because the
disposition below was decided against them.

**Why `5ee7005` exists.**  The §4.2 box's first draft explained the `rs_p`
renumber by printing the old range — *"now names `rtl/vecnorm_unit.sv:331-333`,
not"* the pre-G3.2 range — and `--verify` correctly read the pre-G3.2 numbers
as the spec **still citing** two rewritten lines (34 problems instead of 32).  The old range is
already in §9's landmark table, so the box points there instead.  The edit is
**line-count neutral on purpose**: the spec is cited by line from six other
documents and §10.3 had already renumbered every one of them.

**One check beyond the brief's target list.**
`evidence/qwen9b/g3/isa_bits.py` is Task 7's committed script and was run
**byte-unmodified**, under a new log name: `ISA_BITS: PASS`, with
`vnw_n 13 b >= VNW_ISA_MAX = 4096` in the ceiling table.  It matters because
its round-trip caps the count it emits at the
smaller of `Mach.VNW_ISA_MAX` and `Mach.VNW_HW_MAX`
(`evidence/qwen9b/g3/isa_bits.py:534-536`), which was 2048 and is now **4096** — so **`ARG0[12]` of the VNW count is now
exercised end to end**, closing the G3_1_ISA §14 bullet that said it would not
be until G3.2.  (**D**, from the script's own expression; the log records the
PASS, not the value.)  That script's own comment above that expression
**described the 2048 state until 2026-09-10**, when the pre-ship
documentation chore rewrote it (`evidence/qwen9b/g3/isa_bits.py:525-533`).
It was prose only — the behaviour is `getattr`-driven and was correct
throughout — and G3.2 recorded it in §11.4 rather than editing a script that
lived beside the gate document this task was told not to edit; the chore had
no such constraint.  This paragraph is left as the record of why G3.2 did
not fix it, with the outcome named.

### 12.1 Fix round 1 (review, 2026-09-02) — re-run again on `71f2953`

The review round changed `docs/SEQ_ISA.md` (§11.1a),
`evidence/qwen9b/g3/G3_1_ISA.md` (§11.3) and this document.  **No RTL, TB or
vector file was touched, so the Verilator suite is unchanged and was not
re-run**; §8's and §12's results stand on `71336ab` / `5ee7005`.  The
citation set was re-run in full on the committed tree:

| log | tree | result |
|---|---|---|
| `evidence/qwen9b/g3/119_cite_drift_check_r5.log` | `71f2953` | unchanged sweep: 63 drifted / 28 unresolved / 0 missing / 4 half-mapped |
| `evidence/qwen9b/g3/120_cite_drift_verify_r5.log` | `71f2953` | **`relocated 63 citation(s) checked`** — up from 61, because the ruling let `G3_1_ISA.md`'s two remaining class-A citations be renumbered.  **Class A is now closed at 63 of 63** |
| `evidence/qwen9b/g3/121_cite_drift_range_control_r5.log` | `71f2953` | `O3_RANGE_CONTROL: PASS`, 0 problems |
| `evidence/qwen9b/g3/122_cite_drift_doccites_verify_r5.log` | `71f2953` | `relocated 18 citation(s) checked`, 1 residual (the `evidence/qwen9b/g2/spec_cites_selftest_regression.sh` pinned-count artifact) |
| `evidence/qwen9b/g3/123_spec_cites_r5.log` | `71f2953` | the five documents the review named — the spec, the plan, this document, `evidence/qwen9b/g3/G3_1_ISA.md` and `docs/SEQ_ISA.md` — are **`FAIL 0` raw**, i.e. 0 EXIST and 0 non-EXIST.  Every other document's non-EXIST count equals its `ec08638` baseline (§10.4) |
| `evidence/qwen9b/g3/124_spec_cites_selftest_r5.log` | `71f2953` | `SELFTEST: PASS`, plan path passed explicitly |
| `evidence/qwen9b/g3/125_spec_cites_selftest_regression_r5.log` | `71f2953` | `SPEC_CITES_REGRESSION PASS`, every pinned count unmoved |

**What `--verify` still reports, and why every item is deliberate.**  Log
120 prints **42 `!` lines** under the tool's own headline of 38 problems
(its total counts some of the paired lines once):

* **28 UNRESOLVED** — the class-B set, dispositioned in §10.1 with
  `<!--cites:noquote-->` and the §9 landmark table.
* **4 HALF-MAPPED** — the ranges of §10.1's table.
* **10 lines covering 5 citations that are LEFT ON PURPOSE**: the spec's two
  class-B ranges kept as the record (`rtl/vecnorm_unit.sv:424-426` and
  `tb/tb_vecnorm.sv:251-268`, each printing a *does not cite the new* and a
  *still cites the old* line), and the **three pre-G3.1 tokens in
  `G3_1_ISA.md` §15's *was* columns** — its lines 895 and 795-796, which
  name `d2d774b` content and must not be mapped through `ec08638` (§11.3).

**One self-inflicted complaint was found by this very re-run and fixed.**
Log `evidence/qwen9b/g3/116_cite_drift_verify_r4.log` (tree `c0c3800`)
reported `G3_1_ISA.md` *still citing* five lines it had just renumbered —
because the §16 disposition table printed each OLD number in `path:NNN`
form while recording that it had moved.  That is the same class as the
spec's `rs_p` range at `5ee7005`.  The old numbers are prose now, and logs
119-125 are the clean re-run.  Logs
`evidence/qwen9b/g3/115_*` … `118_*` are kept as the record of the round
that found it.

## 13. What is NOT established by this gate

* **No synthesis, no timing, no board.**  `vecnorm_unit` sits on the layer
  critical path and this change doubles two BRAM-backed arrays and adds a
  bit to four counters and two address paths.  **Whether `cfg_nlog2 = 12`
  closes timing is a G4b/G5 question, not this gate's** — nothing here
  measures Fmax, LUT/BRAM utilisation, or placement.  The spec's §4.2
  sentence *"`vecnorm_unit` sits on the layer critical path"* stands
  unanswered.
* **`cfg_nlog2 = 12` is NOT exercised through `layer_chan`.**  `tb_vecnorm`
  drives the unit directly; `tb_layer_chan` replays a **2B** emission whose
  `H = 2048`, so every VN it issues is `nlog2 = 11` and every VNW is 2048.
  The `vn_waddr` widening is proven by `tb_vecnorm` case 8 writing
  `wbuf[4095]` **through the unit's own port**, and `layer_chan`'s driver
  of that port is proven only at 2048.  Closing that needs a 9B emission,
  which still stops at the Task 10 datapath walls.
* **Neither envelope `$fatal` is silicon protection.**  Both are
  `` `ifndef SYNTHESIS ``.  Spec §2.10's standing hazard — that almost
  every guard in this RTL is sim-only — is untouched.
* **The `layer_chan` VNW guard is now unreachable from the emitter.**  With
  `VNW_ISA_MAX == VNW_HW_MAX == 4096` the host refuses before the RTL can
  see an over-long load; the guard now only catches a hand-written or
  corrupted stream, where `ARG0[12:0]` can still carry up to 8191.  It has
  therefore **not been observed to fire** in any run of this gate.
* **N above 4096 is still refused, and H = 2560 is still impossible.**
  G3.2 widened the SHIFT; it did not add a length input.
  `layer_fixed`/`vecnorm_unit` still produce N only as `1 << cfg_nlog2`, so
  feasibility wall 2's non-power-of-two half (Qwen3.5-4B's H = 2560) stands
  exactly as written.
* **`synth/exp_uram/rtl/vecnorm_unit.sv` is NOT updated.**  It is a frozen
  OOC-experiment copy taken at `aa9c1efa`, whose own header names
  `rtl/vecnorm_unit.sv` as the source of truth.  It still carries the
  12-bit counters, the 2048 buffers and the `>= 4'd12` guard.  Any URAM
  experiment re-run for 9B must re-copy it; that belongs to G4/G5.
* **The 4096 vectors are RANDOM, not a checkpoint.**  `rms4096_*` /
  `l2n4096_*` are drawn from the same `numpy` recipes as the 1024/128/2048
  cases at `LF.RS_F = 8`.  They prove bit-exactness of the datapath at the
  new depth; they say nothing about 9B model quality.
* **`tb_token` / `tb_chain` / `tb_model_*` / `tb_seq_chip` were not run**
  and still cannot pass — their committed v1.7 artifacts were retired at
  G3.1 and this gate does not regenerate them.
