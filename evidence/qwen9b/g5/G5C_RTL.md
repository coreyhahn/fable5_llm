# G5C — the RTL round: the scratchpad cascade, `fx_silu`'s s2, and the two output muxes

Task 14-A (RTL round) of the migration plan's Task 14, base commit
`a553f18`, within the user's **option A** (2026-09-06) and the controller's
ruling of the same day: **one** RTL round carrying **A** (cap the scratchpad
BRAM cascade), **C** (split `fx_silu`'s s2), **D1** (split `attn_core`'s
output mux) and **D2** (split `dn_step`'s output mux).  The design note is
`.superpowers/sdd/2026-09-04-qwen35-9b-state-spill/task-14A-design-note.md`;
its measurements are the committed reports under `evidence/qwen9b/g5/06x`.

**This document is the RTL round only.**  It establishes that the four
changes are *functionally invisible* — the same bits, the same tokens — and
that the one thing they DO change is a counter: LCYC per CONV, per DNST and
per ATTN command, by exactly one cycle each.  **It establishes nothing about
timing**: no build was run, nothing was placed, and the note's WNS estimates
stay estimates until Task 14-B rebuilds.

Labels are the migration spec §0's: **M** measured off the tree, **S**
structural, **D** derived, **T** measured in a tool.

**Revision.**  This document was revised in **review round 1**
(`.superpowers/sdd/2026-09-04-qwen35-9b-state-spill/task-14A-review-round1.md`,
0 Critical / 4 Important / 9 Minor).  The round was **documentation only** —
no RTL was edited, nothing was simulated, no build was run, and every number
below is the number the same committed logs carried before.  What changed:
§3.1 declares the round's one new lint waiver (I-1); **§3.2's central
bit-exactness argument is CORRECTED — its old stated reason was false, the
shipped RTL was and is right (I-2)**; §7.3 attributes the +2 DSP and gains
the evidence file `101_t14a_ooc_hier_dsp.txt` (I-3); §10.8 discloses `099`'s
`FAIL` verdict and the drift pass's exclusion and hand repair (I-4); §10.9
and §10.10 ledger the two concerns as the review words them; and §5.1, §5.3,
§5.4, §5.6, §6.1, §9.3, §10.4 and §10.5 take the minor corrections m1-m9.
The verdict does not move.

---

## 0. Verdict

**GREEN, with two findings that are not this round's and are reported rather
than absorbed.**

| what the round owed | verdict |
|---|---|
| the four changes land, `-Wall` clean | **done** — A, C, D1, D2, one commit each, lint clean at every stage |
| stage A's attribute is honoured **on the netlist** | **YES** — `CASCADE_ORDER_B MIDDLE` goes from 20 to **absent**; 16 chains of 2 on both arrays, against a BASE control run of the same harness.  **A′ was not needed** |
| the arithmetic is unchanged | **bit-exact** at four levels: the unit TBs, `tb_layer_chan`'s 261,357 checks × 4 seeds, the census's **8,600,034 checks, errors=0**, and the replay |
| architecturally visible | **exactly three counters**: CONV, DNST and ATTN LCYC, +1 cycle each.  Nothing else in the census moved by one cycle |
| the S4 replay, token-identical, no re-emission | **TOKENS IDENTICAL TO G4A on 4 of 4 seeds** — and the four chip CYCLE counts are byte-identical to S4's too (§6.1), which is stronger than the brief expected |
| URAM stays 182 | **182** |
| the timing gain | **NOT ESTABLISHED** — no build was run; the note's estimate stands as an estimate |

**Two findings, neither caused by this round, both proven at BASE:**

* `make -C tb tb_seq_layer` does not build, and did not build at `a553f18`
  either — 25 `-Wall` warnings in `tb/seq_mem_file.sv` and
  `tb/tb_layer_chan.sv`, both testbench files (§5.4, control `076`).
  **Ledgered BROKEN, to be repaired rather than retired — §10.9.**
* `tb_layershim_c` fails on the final tree under the Makefile's
  `+verilator+rand+reset+2` and passed at BASE — and under **any**
  deterministic initial state the two trees behave identically, down to the
  per-seed word counts (§5.6, controls `079` and `093`).  The sensitivity is
  `layer_chan`'s local reset pipeline having no reset of its own; adding
  registers merely reshuffled which random value lands where.  **That missing
  reset is a real latent RTL defect, not a testbench quirk — inert on a
  bitstream, out of this round's scope, ledgered at §10.10.**

**The one architecturally visible change is three counters.**  CONV's LCYC
40,972 → 40,973, DNST's 2,958 → 2,959 (min == max), ATTN's 1,962/1,860/2,065
→ 1,963/1,861/2,066.  No CSR VALUE, no fence, no ISA field, no emitted
script, and — measured, not assumed — **no chip-level cycle count either**.

**Two counts moved that the design note predicted would not** (§7.3):
**BRAM 81.0 → 83.0 tiles** (+2 RAMB36, all of it `smem_b` going from 30
tiles in 5 chains of 6 to 32 in 16 chains of 2) and **DSP 1,838 → 1,840**
(`attn_core` +3, `dn_step` −1, `fx_silu` unchanged — Vivado re-inferring
existing adders in the `psum4` tree, not a new multiplier).
Against them, **LUT went DOWN 890** and **FF up 1,601**.

Commits `a553f18` → `c51960f` (A) → `407c619` (C) → `1699567` (D1) →
`1dd2889` (D2, **the final RTL**) → `96ae645` (citation drift) → `15ae991`
and `eb68454` (the ladder's logs) → this document → the `spec_cites` log
alone.

---

## 1. What changed — the four diffs, described

| # | file | the diff | latency | what the sequencer sees |
|---|---|---|---|---|
| **A** | `rtl/layer_chan.sv:503-504` | `(* cascade_height = 2 *)` prefixed to both scratch array declarations, **in place** — the file gains no line | **none** | **nothing** |
| **C** | `rtl/fx_silu.sv`, `rtl/conv4_silu.sv:5` | s2 split into s2a (`b − a`, the product, the round constant) and s2b (the shift and the add) | `fx_silu` 6 → **7**, `conv4_silu` 10 → **11** | CONV's LCYC **+1** |
| **D1** | `rtl/attn_core.sv` | the `acc → o_g4` 4 × 64:1 becomes a free-running 32 × 8:1 (`o_g8`) then 4 × 8:1 then the existing 4:1, plus an `O_FILL` state | drain **+1 cycle per command** | ATTN's LCYC **+1** |
| **D2** | `rtl/dn_step.sv` | the `o_acc → o_sel` 128:1 becomes a free-running 16 × 8:1 (`o_g8`) then a 16:1, plus an `O_FILL` state | drain **+1 cycle per command** | DNST's LCYC **+1** |

**No testbench was edited.**  §4.3 of the design note allows a TB that
carries an explicit latency constant to track it; none of the four does —
`tb_fx_silu` drains with `repeat (20)` (`tb/tb_fx_silu.sv:58`),
`tb_conv4_silu` with `repeat (24)` (`tb/tb_conv4_silu.sv:57`), and
`tb_dn_step` / `tb_attn_core` wait on the module's own `done`
(`tb/tb_dn_step.sv:144-151`, `tb/tb_attn_core.sv:105-112`).  No golden, no
check count and no compare was touched anywhere.

---

## 2. Stage A — the scratchpad cascade

### 2.1 The diff

```
(* cascade_height = 2 *) logic signed [15:0] smem_a [65536];
(* cascade_height = 2 *) logic signed [15:0] smem_b [65536];
```

`rtl/layer_chan.sv:503-504`, and **nothing else in the file**.  The two
attributes are prefixed to the existing declarations, so `rtl/layer_chan.sv` has
exactly as many lines after the change as before: **no citation into this
file moved**, which matters because the S5 round found that one added comment
line here cascaded into 228 citations.

### 2.2 Why an attribute and not a pipeline stage — the measurement, restated

The design note's §1.3 arc list is the whole argument, and it is **T**:
`evidence/qwen9b/g5/061_t14a_eto_probe_at_qdata.rpt:48-86` expands the worst
`at_qdata_reg` path into `1.070 + 6 × 0.210 + 0.117 = 2.447 ns` of RAMB36E2
**cell** delay plus `7 × 0.028 = 0.196 ns` of cascade net — 2.643 ns of a
3.980 ns data path — followed by **one LUT3 at 0.097 ns**.  A register placed
after that mux would sit *after* the 2.6 ns, not inside it.  `DOB_REG = 0`
on every scratchpad tile (`evidence/qwen9b/g5/064_t14a_eto_smem.log`), so the
launch is the array-read arc itself.

### 2.3 Zero latency ripple, and how that was checked rather than asserted

`cascade_height` changes how the tiles are chained, not when the data is
valid, so the array presents the same 1-cycle read it did before.  The
acceptance bar for that claim is not a reading of the source: it is **the
layer census, byte-for-byte against S4's** on every opcode whose read path
touches the scratchpad — VN, VNW, ROPET, ROPE, GATE, KVAP, ALU, SLD and SST
all unchanged to the cycle, and DNST's own `L_A/L_W/L_P` scratch feed
unchanged (§5.7).  A single moved cycle there would have been a RED, and
there is none.

What the attribute DOES move is the tile COUNT — `smem_b` goes from 30 tiles
to 32 because 16 chains of 2 is the only 2-deep tiling of the array — and
that is the +2 RAMB36 §7.3 reports rather than buries.

---

## 3. Stage C — `fx_silu`'s s2, split

### 3.1 The diff

`rtl/fx_silu.sv`: the single `always_ff` that computed `sig2` becomes two.

```
// s2a
    a2a <= a;                                   // a = {1'b0, pq[15:0]}
    t2a <= 27'(17'(b - a)) * 27'(lo1) + 27'sd256;
// s2b
    d = 27'(t2a >>> 9);
    sig2 <= 16'(a2a + 17'(d));
```

The old line was
`d = (27'(17'(b - a)) * 27'(lo1) + 27'sd256) >>> 9;` followed by
`sig2 <= 16'(a + 17'(d));`.  The expression is cut exactly at the `>>> 9`.

**A NEW LINT WAIVER — declared, because §5.1 says "no warning of any kind"
and that sentence is only true with this pragma in place.**  The declaration
of the new intermediate is wrapped:

```
    /* verilator lint_off UNUSEDSIGNAL */
    logic [26:0]        t2a;   // [8:0] discarded by s2b's >>> 9
    /* verilator lint_on UNUSEDSIGNAL */
```

`rtl/fx_silu.sv:84-86`.  **It is the ONLY new pragma anywhere in this
round**: `git diff a553f18..7c25f15 -- rtl/ | grep -E '^[+-].*lint_(off|on)'`
returns exactly this one added pair and nothing else (**M**).  `attn_core`'s
`o_g8` was placed INSIDE the file's pre-existing `UNUSEDSIGNAL` region
(`rtl/attn_core.sv:168-172`, which already wrapped `o_sel` and `o_g4`), and
`dn_step`'s `o_g8`/`og_i` need no waiver at all.

**Which bits, and why they are dead by construction.**  `t2a[8:0]` are
consumed by nothing: the only reader of `t2a` is s2b's `27'(t2a >>> 9)`,
which shifts them out, so Verilator's `UNUSEDSIGNAL` is a *correct* report
about a signal that is unused **by design** — the register exists to hold the
27-bit pattern across a clock edge, and the split point is the shift.  Vivado
sees the same thing independently and trims the register from the other end:
`088:10308` `Found unconnected internal register 'u_silu/t2a_reg' and it is
trimmed from '27' to '25' bits` — bits [26:25] never reach `sig2`, but by two
different routes: **[26] dies at the `17'(d)` truncation**, and **[25]
survives `17'(d)` and dies at the `16'()` on the sum** (§3.2 states this
correctly; this sentence attributed both bits to `17'(d)` until 2026-09-10).

**It is precedented and minimal.**  `d` — the variable `t2a` now feeds, and
the one that held this value before the split — carries the identical waiver
in the identical form further down the same file: `rtl/fx_silu.sv:102-104`
wraps `logic signed [26:0] d; // upper bits sign copies`, and has since this
module was written.  The new pair is
scoped to the single declaration, not to a block, a module or a file, so it
suppresses nothing else; no other warning class is waived anywhere in the
round.

### 3.2 Why it is bit-exact — and what the *reason* actually is

**The split is bit-exact because nothing about the arithmetic moved except
where the clock edge falls.**  Every operand keeps its width and its
signedness, and the two truncations that consume the shifted value —
`17'(d)` and the `16'()` on the sum — are character-identical to what was
there.  `t2a` is declared `logic [26:0]`, which is the faithful transcription
of the expression it holds: `lo1` is `logic [8:0]`, so `27'(lo1)` is
unsigned, so under the LRM the product and the sum with `27'sd256` after it
are unsigned, and the old `>>> 9` was applied to an unsigned value and was a
LOGICAL shift.  `t2a` therefore carries the identical 27-bit pattern the old
`d` was computed in, and s2b's `27'(t2a >>> 9)` reproduces the old `d` bit
for bit.

**A correction, and it matters more than the claim it replaces.**  An earlier
draft of this section said that declaring the intermediate `logic signed
[26:0]` — as a first sketch of this stage had it — would have made
`t2a >>> 9` an ARITHMETIC shift and "changed the value whenever the 27-bit
pattern had bit 26 set".  **That is false, and it is corrected here rather
than quietly dropped**, because a future round that trusts it would draw a
wrong conclusion about when splitting at a `>>>` is safe.  A signed `t2a`
would ALSO have been bit-identical: `sig2 <= 16'(a2a + 17'(d))` keeps only
`d[16:0] = t2a[25:9]`, and `t2a[25:9]` is the same under a logical and an
arithmetic right shift by 9 — the two forms differ **only** in `d[26:18]`,
every bit of which the `17'()` cast discards.  The signedness of the
intermediate is immaterial below bit 17, which is the whole of what survives.

**Derivation** (review round 1,
`.superpowers/sdd/2026-09-04-qwen35-9b-state-spill/task-14A-review-round1.md`
§I-2, **D**): the reviewer evaluated the old expression, the shipped unsigned
form and the signed counterfactual over the same **400,125** `(a, b, lo1)`
triples — every combination of {0, 1, 32767, 32768, 65535} ×
{0, 1, 255, 256, 511} plus 400,000 random — of which **199,782 had bit 26
set**: **0 mismatches for the unsigned form and 0 for the signed one**.  It
is a pure re-derivation of committed arithmetic in Python, not a simulation,
so there is no log to cite and none was produced.

**The question is doubly unreachable in the shipped design.**
`rtl/roms/sigmoid_pair_rom.hex` has **no** segment with `b < a` (0 of 256;
107 have `b == a`), so `b − a ≥ 0` and
`t2a ≤ 65535 × 511 + 256 = 33,488,641 < 2^25` — bit 26 is never set at all.
Vivado sees the same two bits die, from the OTHER end: `088:10308` trims
`u_silu/t2a_reg` from 27 to 25 bits.  **That is a CONNECTIVITY result, not a
value-range one** — the trim happens because nothing downstream reads those
bits, and it would happen whatever the ROM contained; it corroborates the
conclusion without re-measuring the premise.  *(Restated 2026-09-10: this
read as though the netlist confirmed the range argument.)*  No unit TB covers
a negative `b − a` because none can;
the equivalence above is structural and holds for it anyway.

**Keeping the unsigned declaration is still the right call** — it is the
faithful form — but the *reason* the split is safe is the truncation, not the
shift.

### 3.3 The consumers

`rtl/conv4_silu.sv:61` is the only instantiation of `fx_silu` in `rtl/`
(**M**, a grep of the tree); `vec_alu` has its own interpolation stages and
does not use this module.  `conv4_silu` is `in_valid`/`out_valid` handshaked
and carries no counter, so the only edit it needed is its latency comment
(`rtl/conv4_silu.sv:5`, in place).  `layer_chan`'s CONV drain is count-based
on `cv_ovalid` (`rtl/layer_chan.sv:1897`, `CV_D: if (cvj == arg0[27:14])`),
so it simply waits one cycle longer: **CONV's LCYC 40,972 → 40,973 and
nothing else.**

---

## 4. Stages D1 and D2 — the two output muxes, split

### 4.1 The shape both changes have, and why it costs ONE cycle and not 256

Both muxes sit in a **drain loop**, not in a pipeline: `attn_core` emits one
of 256 words every 4 cycles and `dn_step` one of 128 every 3, each cycle of
the loop being a state.  **Adding a mux level as a STATE would have cost one
cycle per WORD** — +256 on ATTN and +128 on DNST — which is not what the
design note's "+1 cycle on the count-based drain" means and would have shown
up in the census as a four-figure move.

So the new first level is **free-running**, not a state:

```
    always_ff @(posedge clk)                       // attn_core (32 groups)
        for (int h = 0; h < 32; h++) o_g8[h] <= signed'(acc[{5'(h), og_i}]);
```

`og_i` is a 3-bit register that LEADS `oi` by one emit iteration: it is set
to `oi[2:0] + 1` in `O_EMIT2`, so the gather for word *k+1* happens during the
cycle the loop is already spending waiting for `m_ready` on word *k*.  The
loop period is unchanged.  What the split does cost is the **fill**: at the
head of the drain `o_g8` holds nothing for `oi = 0`, so one new state,
`O_FILL`, primes it — **once per command**.

`O_FILL` is deliberate rather than incidental.  `og_i` happens to come back
to 0 after the previous command's last word, so the fill state could have been
omitted and the drain would still have been correct — *by accident of the
previous command's leftover register, and never after reset*.  One
unconditional cycle is the honest structure, and it is the cycle the census
and the ISA-visible LCYC both account for.

No enable is used on the gather.  The accumulators are stable for the whole
drain in both modules (`acc_en_r` is `st == P_SH3` and `aclr_r` is
`IDLE && start` in `rtl/attn_core.sv:203-204`; `oacc_en_r` is `st == P2_QM`
and `clr_r` is `IDLE` in `rtl/dn_step.sv:173-174`), and a state-decoded enable
across the lane arrays is the thing both modules' comments say was a timing
killer.

### 4.2 D1 — `rtl/attn_core.sv`

Before: `o_g4[g] <= acc[{2'(g), oi[5:0]}]` for `g` in 0..3 — **4 × 64:1 over
256 spread 40-bit accumulators**, then `o_sel <= o_g4[oi[7:6]]`.
Measured: 3 logic levels, **0.276 ns logic against 3.882 ns route**, 891
failing endpoints on the ETO artifact and 1,679 on po2 — the largest failing
family in the design (`evidence/qwen9b/g5/060_t14a_eto_cones.log:191`).

After: three levels.
`o_g8[h] = acc[h*8 + og_i]` (32 muxes over eight ADJACENT lanes each,
free-running) → `o_g4[g] = o_g8[g*8 + oi[5:3]]` (4 × 8:1, in `O_EMIT`) →
`o_sel = o_g4[oi[7:6]]` (4:1, in `O_EMITA`).

The index algebra is an identity, which is why the emitted words cannot move:
`o_g8[g*8 + oi[5:3]] = acc[(g*8 + oi[5:3])*8 + oi[2:0]] = acc[g*64 + oi[5:0]]`,
and `og_i == oi[2:0]` at every capture by construction.

### 4.3 D2 — `rtl/dn_step.sv`

Before: `o_sel <= o_acc[oi[6:0]]` — **one 128:1 mux**, 5 logic levels,
0.476 ns logic against 3.704 ns route
(`evidence/qwen9b/g5/060_t14a_eto_cones.log:191-219`, the `DN_LANE` row).

After: `o_g8[h] = o_acc[h*8 + og_i]` (16 × 8:1, free-running) → `o_sel =
o_g8[oi[6:3]]` (16:1, in `O_EMIT`).  Same identity:
`o_g8[oi[6:3]] = o_acc[oi[6:3]*8 + oi[2:0]] = o_acc[oi[6:0]]`.

### 4.4 What layer_chan sees — checked, not assumed

Both collections are count-based and both `done` pulses are unused:
`rtl/layer_chan.sv:606` and `:788` say so in the source, and the collector is
`D_RDY`/`D_HI` at `rtl/layer_chan.sv:1840-1866`, which counts `rcvd` to
`n_col` and then goes to `DONE_S`.  Neither drain's length is a constant
anywhere in `layer_chan`, in `rtl/seq_unit.sv` or in `docs/SEQ_ISA.md`:
**no fence moves, no CSR VALUE moves, no ISA field moves.**  The one thing
that moves is the LCYC accumulator (CSR 0x34, `docs/SEQ_ISA.md:521`), which
is a free-running busy counter with no specified value.

---

## 5. The verification ladder — what ran, where, and what it said

Every rung ran ON SNOKE through `bash evidence/qwen9b/run.sh`, so every log
carries its own `=== host: snoke`, `=== tree:` and `=== rc:`.  Nothing
numeric ran on darthplagueis and the board was not touched.

| # | log | tree | rung | rc |
|---|---|---|---|---|
| 070 | `evidence/qwen9b/g5/070_t14a_A_lint.log` | `c51960f` | `make -C tb lint_layer_chan` after stage A | 0 |
| 071 | `evidence/qwen9b/g5/071_t14a_A_tb_layer.log` | `c51960f` | `tb_layer_chan` (4 seeds) + `tb_seq_layer` | 0 for the wrapper; the `tb_seq_layer` arm is `rc=2`, §5.4 |
| 072 | `evidence/qwen9b/g5/072_t14a_A_tb_shim_sdma.log` | `c51960f` | `tb_layershim_c`, `tb_layer_sdma`, `tb_layer_sdma_nofence` (the RED control) | 0 |
| 073 | `evidence/qwen9b/g5/073_t14a_C_silu.log` | `407c619` | stage C: lint + `tb_fx_silu` + `tb_conv4_silu` | 0 |
| 074 | `evidence/qwen9b/g5/074_t14a_D1_attn.log` | `1699567` | stage D1: lint + `tb_attn_core` | 0 |
| 075 | `evidence/qwen9b/g5/075_t14a_D2_dn.log` | `1dd2889` | stage D2: lint + `tb_dn_step` + `tb_dn_step_pipe` | 0 |
| 076 | `evidence/qwen9b/g5/076_t14a_seqlayer_base_control.log` | `c51960f` | the `tb_seq_layer` RED **at BASE** (§5.4) | 0 |
| 077 | `evidence/qwen9b/g5/077_t14a_units_final_tree.log` | `1dd2889` | every unit gate again, on the FINAL tree, clean header | 0 |
| 078 | `evidence/qwen9b/g5/078_t14a_layerfam_final_tree.log` | `1dd2889` | the layer family again, on the FINAL tree | 0 for the wrapper; the `tb_layershim_c` arm is `rc=2`, §5.6 |
| 079 | `evidence/qwen9b/g5/079_t14a_layershim_randreset_probe.log` | `96ae645` | the `tb_layershim_c` seed sweep, both trees (§5.6) | 0 |
| 080 | `evidence/qwen9b/g5/080_t14a_census.log` | `1dd2889` | the census — **interrupted**, see §10.4 | — |
| 081 | `evidence/qwen9b/g5/081_t14a_census.log` | `96ae645` | the layer census, DRAINING mode (§5.7) | 0 |
| 085 | `evidence/qwen9b/g5/085_t14a_chip_build.log` | `1dd2889` | `tb_seq_chip_9b_build` | 0 |
| 086 | `evidence/qwen9b/g5/086_replay_t14a.log` | `1dd2889` | the chip replay — **wrapper interrupted**, see §6.2 | — |
| 087 | `evidence/qwen9b/g5/087_replay_t14a.log` | `15ae991` | the chip replay, 4 seeds (§6) | 0 |
| 088 | `evidence/qwen9b/g5/088_t14a_ooc_layer.log` | `1dd2889` | OOC synthesis of `layer_chan` (§7) | 0 |
| 089 | `evidence/qwen9b/g5/089_t14a_ooc_cascade.log` | `96ae645` | the cascade probe on the OOC netlist (§7.2) | 0 |
| 090 | `evidence/qwen9b/g5/090_t14a_ooc_BASE_control.log` | `96ae645` | the SAME OOC harness on BASE `a553f18` (§7.1) | 0 (its trailing cascade step hit `set -u` — redone as `091`) |
| 091 | `evidence/qwen9b/g5/091_t14a_ooc_BASE_cascade.log` | `96ae645` | the cascade probe on the BASE netlist | 0 |
| 092 | `evidence/qwen9b/g5/092_t14a_scratch_cascade_both.log` | `96ae645` | the cascade tally over BOTH netlists (§7.2) | 0 |
| 093 | `evidence/qwen9b/g5/093_t14a_layershim_randreset_control.log` | `96ae645` | the deterministic-init control (§5.6) | 0 |
| 095-099 | `evidence/qwen9b/g5/09{5,6,7,8,9}_t14a_cite_drift_*.log` | — | citation drift: plan, check, plan-with-exclusion, fix, verify | `095` **UNSAFE** (by design — it is why `097` exists), `097` `SAFE`, `098` `FIX APPLIED`, **`099` `O3_CITE_DRIFT VERIFY FAIL (2 problem(s))`, `rc: 1`** — §10.8 |

Trees: `c51960f` is stage A, `407c619` + C, `1699567` + D1, `1dd2889` + D2
(**the final RTL**), `96ae645` the citation-drift repair and `15ae991` the
evidence commit.  Nothing after `1dd2889` touches a line the tools read:
**`git diff 1dd2889 15ae991 -- rtl/ tb/` is empty**, so every rung in this
table ran against the same RTL and the same testbenches, whichever of the
three shas its header names.  `073`/`074`/`075` and `099` carry `+dirty` —
§5.5 for the first three (re-run clean as `077`), and `099` is a `--verify`
whose whole point is to run WITH the fix in the working tree.

### 5.1 Lint — `-Wall`, Verilator 5.020

`make -C tb lint_layer_chan` lints the whole `LAYER_RTL` list (all four
edited files plus `state_dma` and `layer_chan`) plus `tb/axi_ram_bfm.sv`, and it
is clean at every stage: `070` after A, and inside `073`, `074`, `075` and
`077` after C, D1 and D2.  **`(* cascade_height = 2 *)` is accepted silently**
— no warning of any kind — which is the first half of stage A's acceptance
(the second half is the netlist, §7.2).  `lint_state_dma` is clean too (077).

**"Clean" here means clean WITH ONE NEW WAIVER, declared in §3.1.**  Stage C
added a `/* verilator lint_off UNUSEDSIGNAL */` … `lint_on` pair around the
declaration of `t2a` (`rtl/fx_silu.sv:84-86`), scoped to that one signal,
because `t2a[8:0]` are shifted out by s2b and are unused by construction.  It
is the **only** new pragma in the round —
`git diff a553f18..7c25f15 -- rtl/ | grep -E '^[+-].*lint_(off|on)'` returns
exactly that one added pair — it matches the waiver the variable it replaces
has always carried (`rtl/fx_silu.sv:102-104`), and it suppresses no other
warning class anywhere.  **Without this clause the sentence above overstates
the result**, so it is stated here rather than left to §3.1 alone.

### 5.2 The unit gates, four seeds each, on the FINAL tree (`077`, tree `1dd2889`)

| TB | verdict, quoted | seeds |
|---|---|---|
| `tb_fx_silu` | `TB_FX_SILU PASS: 409 cases bit-exact (pipelined)` | 4 case files (`ref/gen_silu_cases.py` seeds 1-4) |
| `tb_conv4_silu` | `TB_CONV4_SILU PASS: 64 channels bit-exact` | 4 vector dirs |
| `tb_attn_core` | `TB_ATTN_CORE PASS: 256 outputs bit-exact (T=48)` | 4 vector dirs |
| `tb_dn_step` | `TB_DN_STEP PASS: 128 outputs + 16384 state entries bit-exact` | 4 vector dirs |

**And `tb_dn_step` measures the +1 directly, before the census ever runs.**
It prints the module's own start-to-done cost:

```
DN_CYCLES RLAT=2 P2W=0 cycles_per_head=1799
```

on all four seeds, against the committed baseline
`DN_CYCLES RLAT=2 P2W=0 cycles_per_head=1798`
(`evidence/qwen9b/s2/018_units_and_lints.log`, S2's committed unit sweep on
the shipping RLAT = 2 / P2_WAIT = 0 pair).  **1798 → 1799: exactly one cycle for
128 emitted words** — which is the whole design argument for the free-running
first mux level, measured rather than asserted.  `075`'s
`tb_dn_step_pipe` arm says the same at the other latency: `RLAT=6 P2W=1`
reads **1931** against the **1930** recorded in
`evidence/qwen9b/g3/297_tb_suite_r2_committed.log`.

### 5.3 The layer family (`071`, `072` and `078`)

`tb_layer_chan`, the emitter-driven layer gate, four seeds:
`TB_LAYER_CHAN PASS: 1465 cmds, 261357 checks bit-exact` on
scripts/layerv2_s1 … s4.txt — in `071` (tree `c51960f`) and again in `078`
(the final tree `1dd2889`).  **`tb_layershim_c` PASS on four seeds is `072`,
at `c51960f` — the STAGE-A tree, not the final one** (the burst window / SWIN
equality gate, the consumer with the tightest `sa_q` contract); **the same
target is `rc=2` on the final tree in `078`, under the Makefile's
`+verilator+rand+reset+2` — §5.6, which is where that PASS is qualified and
where the controls that explain it live.**  Do not read this line as a green
`tb_layershim_c` on the shipped RTL.
`tb_layer_sdma`: `TB_LAYER_SDMA PASS: 240 checks` on four seeds — **and its
RED control fires**, four times:

```
OK: the F1 bypass reads stale state and FAILS at seed 1 … 4
```

which is the proof that the SDMA gate can still fail.  Stage A's fences are
untouched and this shows it on a live fence rather than by reading the source.

### 5.4 ONE RUNG COULD NOT RUN, and it was already broken at BASE

`make -C tb tb_seq_layer` **fails to build**, in `071`, with 25 `-Wall`
warnings — `WIDTHTRUNC`/`WIDTHEXPAND` in `tb/seq_mem_file.sv:225-435` and
`UNUSEDPARAM` in `tb/tb_layer_chan.sv:165-176` — all in **testbench files
this round does not touch**.  The sibling target `tb_layer_chan` compiles the
same sources and PASSES because it passes `$(XLIB)` and lists
`tb/seq_mem_file.sv` as a file instead of taking it through the `include`.

It is not this round's breakage, and that is not an assertion:
`evidence/qwen9b/g5/076_t14a_seqlayer_base_control.log` runs the identical
verilator command **with BASE `a553f18`'s `rtl/`** — the log prints the two-line
diff that is the only difference — and gets
`%Error: Exiting due to 25 warning(s)`, the same 25.  **Reported as a
pre-existing defect for the final triage; not repaired here** (both files are
outside this round's commit block, and `tb_layer_chan` — 1,465 commands and
261,357 checks per seed against `tb_seq_layer`'s 19 and 5,280 — covers the
same DUT far more heavily and passes).

**One clause about that control's own echo, so nobody chases it.**  `076`'s
line reads
`=== BASE-rtl tb_seq_layer lint rc=1 (2 = the SAME pre-existing -Wall failure) ===`
— **the printed `rc=1` and the parenthetical `2` are not a contradiction and
neither is a typo.**  The control invokes `verilator` DIRECTLY, and verilator
exits **1**; the make target `tb_seq_layer` exits **2**, because make wraps
it.  The parenthetical names the make-level code the reader will have seen in
`071`.  The load-bearing number in both is the same: `Exiting due to
**25** warning(s)`, the count §5.4 quotes.

### 5.5 A provenance note on three `+dirty` headers

`073`, `074` and `075` carry `=== tree: <sha>+dirty` although each ran 7-9
seconds after its own path-limited commit and `git status` was clean on the
committing host.  The flag comes from run.sh's `git diff --quiet` on snoke
reading an index the other host had just rewritten; it is not a file.
**Rather than argue it, the same gates were re-run on the final tree**:
`077` covers lint, `tb_fx_silu`, `tb_conv4_silu`, `tb_attn_core` and
`tb_dn_step` in one log whose header reads a clean `=== tree: 1dd2889`, with
identical verdicts, and `078` does the same for the layer family.  Both hosts
report the tree clean now.
### 5.6 The second rung that went RED, and the control that explains it

`tb_layershim_c` PASSED four seeds on the stage-A tree (`072`) and **FAILED
on the final tree** (`078`):

```
[2000] %Fatal: vecnorm_unit.sv:433: Assertion failed in TOP.tb_layershim_c.dut.u_vn:
       vecnorm_unit: cfg_nlog2 13 unsupported (max 12, N=4096)
```

**Time 2000 is the first few cycles, before the testbench has driven
anything, and this TB never issues a VN command at all** (there is no `OP_VN`
in `tb/tb_layershim_c.sv`).  The Makefile runs it with
`+verilator+rand+reset+2` — random initial values for every unreset variable
— and `layer_chan`'s local reset pipeline `rstn_q`/`rstn_i`
(`rtl/layer_chan.sv:526-531`) carries **no reset of its own**, so a random 1
there un-resets the layer's dispatcher for a cycle while `aresetn` is still
low and it executes whatever the random `st`/`cmd_op`/`arg0` say.

**Two controls, and between them the question is closed.**

`evidence/qwen9b/g5/079_t14a_layershim_randreset_probe.log` sweeps the
VERILATOR randomisation seed over both trees, on binaries built from BASE
`a553f18` and from HEAD `1dd2889`:

| `+verilator+seed+` | BASE `a553f18` | HEAD `1dd2889` |
|---|---|---|
| **0** | **FAIL** — reason not captured (`079:72`) | **FAIL** — reason not captured (`079:91`) |
| 1 | FAIL — watchdog | FAIL — watchdog |
| 2 | FAIL — `layer_chan: kvhead_r 0 != slot tag kvhead 1` at `[2000]` | **the same, character for character** |
| 3 | FAIL — `layer_chan: kvhead_r 0 != slot tag kvhead 2` at `[2000]` | **the same** |
| 4, 5, 6, 7 | FAIL — watchdog | FAIL — watchdog |

**EIGHT of eight explicit seeds fail, and fail on BOTH trees.**  `vseed=0`
is a FAIL like the rest — the log's `FAIL:` field is empty for it only
because the probe harvests the reason with
`grep -m1 -E "%Fatal|Assertion"` and seed 0's abort printed neither before
the core dump (`079` records the `Aborted (core dumped)` for it on both
trees).  It must not be read as a pass.  This target passes only for the
narrow set of random values the DEFAULT seed happens to produce, and it
produced a benign set at BASE.

`evidence/qwen9b/g5/093_t14a_layershim_randreset_control.log` isolates it
completely — the same two binaries, the same four `+seed=` values, with the
uninitialised state forced DETERMINISTIC instead of random:

| init | BASE `a553f18` | HEAD `1dd2889` |
|---|---|---|
| `+verilator+rand+reset+0` (zeros) | **PASS ×4**, `T1 1428 w, T2 954 w …` | **PASS ×4, byte-identical counts per seed** |
| `+verilator+rand+reset+1` (ones) | FAIL ×4, `vec_alu.sv:770 … w/a scratch port col…` at `[2000]` | **the same failure, ×4** |

**Under every deterministic initial state the two trees behave identically**,
down to the per-seed word counts.  The RTL is not the discriminator; the
random-init stream is, and adding registers to `attn_core`, `dn_step` and
`fx_silu` shifts which random value lands in which variable.

**Reported as a finding, not repaired here.**  It is a latent robustness
defect — a target that runs `+verilator+rand+reset+2` against a design whose
local reset pipeline has no reset — and `rtl/layer_chan.sv`'s reset pipeline
is a timing-motivated structure this round has no mandate to change.  What
this round owes is proof that nothing FUNCTIONAL moved, and §5.2, §5.3, §5.7
and §6 are that proof: `tb_layer_chan` at 1,465 commands and 261,357 checks
per seed × 4, `tb_layer_sdma` with its RED control firing, all four unit TBs
bit-exact, the census's 8.6 M checks and a token-identical replay.
### 5.7 The layer census, DRAINING mode — the three +1 rows and nothing else

**M**, `evidence/qwen9b/g5/081_t14a_census.log`, snoke, tree `96ae645`
(whose `rtl/` is byte-identical to `1dd2889` — the intervening commit is the
citation-drift repair, and `git diff 1dd2889 96ae645 -- rtl/` is empty), the
S4 runner and the S4 model stream:

```
bash evidence/qwen9b/s4/run_s4_census.sh t14a scripts/w9/model_9b_s1.txt 0 \
     scripts/w9/model_9b_s1.emb.bin 4096 2000000
```

`NODRAIN` unset = draining mode, which is the mode that attributes
per-command cost.  The runner REFUSES to run with `rtl/` dirty, so this
number is claimed against a committed tree by construction.

**The header lines, unchanged from S4's:**

```
LAYER_CENSUS commands=56576 checks=8600034 errors=0
LAYER_CENSUS state_region base=380000000 len=9b00000 (S record),
             ddr beats r=2676800 w=2659968 miss=0, LAT=8 modelled
```

**8,600,034 checks, bit-exact, and the check count did not move.**

**The per-opcode table, beside S4's** (`evidence/qwen9b/s4/census_s4shipped.txt`
vs `evidence/qwen9b/s4/census_t14a.txt`):

| op | count | S4 mean/min/max | T14A mean/min/max | Δ |
|---|---|---|---|---|
| 1 VN | 10,566 | 620 / 304 / 8,243 | **identical** | 0 |
| 2 VNW | 486 | 10,013 / 769 / 12,289 | **identical** | 0 |
| 3 ROPET | 48 | 385 / 385 / 385 | **identical** | 0 |
| 4 ROPE | 960 | 1,027 / 1,027 / 1,027 | **identical** | 0 |
| **6 CONV** | 144 | 40,972 / 40,972 / 40,972 | **40,973 / 40,973 / 40,973** | **+1** |
| 7 GATE | 144 | 1,315 / 1,315 / 1,315 | **identical** | 0 |
| **8 DNST** | 4,608 | 2,958 / 2,958 / 2,958 | **2,959 / 2,959 / 2,959** | **+1, min == max still** |
| 9 KVAP | 192 | 4,621 / 4,619 / 4,626 | **identical** | 0 |
| **10 ATTN** | 768 | 1,962 / 1,860 / 2,065 | **1,963 / 1,861 / 2,066** | **+1 on all three** |
| 11 ALU | 37,314 | 910 / 42 / 24,596 | **identical** | 0 |
| 13 SLD / 14 SST | 674 / 672 | 0 | **identical** | 0 |

and the totals:

| | S4 | T14A | Δ |
|---|---|---|---|
| CONV total | 5,899,968 | **5,900,112** | +144 = 1 × 144 commands |
| DNST total | 13,630,464 | **13,635,072** | +4,608 = 1 × 4,608 |
| ATTN total | 1,507,200 | **1,507,968** | +768 = 1 × 768 |
| ATTN `excess` | 78,720 | **78,720** | **0** — a constant shift cancels in `total − n·min` |
| `TOTAL_BUSY_CYCLES` | 68,510,840 | **68,516,360** | **+5,520 = 144 + 4,608 + 768, exactly** |
| `TOTAL_SDMA_CYCLES` | 7,727,707 | **7,727,707** | 0 |
| per step 1-6 `busy_cyc` | 11,405,434 … 11,431,586 | **+920 each** | 24 CONV + 768 DNST + 128 ATTN per step |
| per step `sdma_cyc` | 1,280,480 … | **identical** | 0 |

**`diff census_s4shipped.txt census_t14a.txt` is those rows and nothing
else** — plus four lines the instrument gained after S4's shipped run
(§5.7a).  Every one of these numbers was PREDICTED before the run, from the
FSM structure alone, and the prediction table is §5.7b.

### 5.7a One honesty note on the comparand

`evidence/qwen9b/s4/census_s4shipped.txt` was written by the census TB as it stood at S4's
step 3; `evidence/qwen9b/g4/tb_layer_census.sv` then gained the non-draining
mode and the fence-hold counters at S4 fix round 1 (`48e5128`), and has not
changed since (`git log a553f18..HEAD -- evidence/qwen9b/g4/tb_layer_census.sv`
is empty — **this round did not touch the instrument**).  So the diff also
carries four ADDED reporting lines (`dispatch= DRAINING`,
`TOTAL_BUSY_ANY_CYCLES 76244067`, `TOTAL_F1_HOLD_CYCLES 0`,
`TOTAL_F2_HOLD_CYCLES 0`, `TOTAL_F2_FENCE_CYCLES 0`) that are the newer
instrument, not the design.

**And the three baselines are reproduced by the NEWER instrument on the OLD
RTL**, which closes the question: `evidence/qwen9b/s4/census_dr8.txt` —
post-fix instrument, draining, LAT 8, on the `lay9b_s1` stream — carries
`6 CONV … 40972`, `8 DNST … 2958` and `10 ATTN … min 1860`.  Same
instrument, old RTL: the old numbers.  Same instrument, new RTL: +1 on
exactly those three.

### 5.7b The predictions, made before the run

| row | S4 shipped | predicted | measured |
|---|---|---|---|
| CONV mean/min/max | 40,972 | 40,973 | **40,973** |
| DNST mean/min/max | 2,958 | 2,959 | **2,959** |
| ATTN mean / min / max | 1,962 / 1,860 / 2,065 | 1,963 / 1,861 / 2,066 | **1,963 / 1,861 / 2,066** |
| ATTN excess | 78,720 | unchanged | **78,720** |
| `TOTAL_BUSY_CYCLES` | 68,510,840 | 68,516,360 | **68,516,360** |
| per step busy_cyc | — | +920 | **+920 on all six** |
| everything else | — | byte-identical | **byte-identical** |

The design argument is `LCYC(cmd) = LCYC_old(cmd) + 1` for exactly three
opcodes, and the census is the whole model — 56,576 commands over six
forward steps and 32 layers — agreeing with it to the cycle.

---

## 6. The chip replay — token-identical, four seeds, NO re-emission

`tb/scripts/w9/model_9b_s1..s4` are **S4's emissions, untouched**: this round
wrote nothing into that directory, and the four `.e4.chip` goldens and
`.state.bin` images are the files S4 produced (`evidence/qwen9b/s4/S4_REPLAY.md` §2.2).
`evidence/qwen9b/g4/run_g4a_replay.sh` compares each seed's decoded tokens
against the sequence a **committed document** records —
`evidence/qwen9b/g4/G4A_REPLAY.md`, read by the script rather than retyped
into it, strict in both directions (no record and an ambiguous record both
FAIL; all four arms of that comparison were fired on real simulations in
`evidence/qwen9b/s4/010_tokens_ref_red.log`).

**That is the acceptance bar of this whole round.**  Twenty-four tokens over
four prompts and six forward steps through 32 real layers, with the DeltaNet
and attention output muxes re-shaped, `fx_silu` a cycle longer and the
scratchpad's BRAM chain re-chained to depth 2 — and not one token may move.

**M**, `evidence/qwen9b/g5/087_replay_t14a.log`, snoke, tree `15ae991`
(`rtl/` and `tb/` byte-identical to `1dd2889`), ONE binary
(`085_t14a_chip_build.log`, `tb_seq_chip_9b_build`, rc 0, built
`2026-09-07T00:06:34`), four processes launched together,
`LOGDIR=evidence/qwen9b/g5/seedlogs_t14a2_model_9b_s`, **2 h 25 min**
(`total wall 8699s for 4 seed(s) in parallel`), `rc: 0`, last lines

```
--- TOKENS IDENTICAL TO G4A on 4 of 4 seed(s)
G4A_REPLAY model_9b_s: ALL PASS
```

| seed | tokens measured | Task 11's record (`evidence/qwen9b/g4/G4A_REPLAY.md`) | verdict | cycles | S4's cycles |
|---|---|---|---|---|---|
| `model_9b_s1` | `[2614, 314, 279, 369, 11751, 13]` | the same | **IDENTICAL** | **196,706,821** | 196,706,821 |
| `model_9b_s2` | `[279, 264, 854, 11, 303, 264]` | the same | **IDENTICAL** | **196,707,670** | 196,707,670 |
| `model_9b_s3` | `[313, 430, 2510, 198, 1445, 27180]` | the same | **IDENTICAL** | **196,707,670** | 196,707,670 |
| `model_9b_s4` | `[11, 0, 271, 803, 369, 498]` | the same | **IDENTICAL** | **196,706,833** | 196,706,833 |

Every seed also carries `LAUNCH 0 PASS: … tokens 6, tcnt 8, scratch 36864,
smem 112`, `decerr 0 non-OK 0`, `weight beats 383606784 total across 4 chan
(miss 0)` and `ddr beats 448410 / 448413 (miss 0)` — **every one of them the
number S4 recorded**, and `DUT held in reset 0 times after t=0`.

### 6.1 The cycle counts did NOT move, and that is the finding, not an omission

The brief expected the replay's cycle counts to rise by the +1 per CONV,
DNST and ATTN command.  **They did not: all four are byte-identical to S4's**,
and so are the burst counters (`busy_wr 50006166`, `busy_rd 47368548`), the
DDR beats and the weight beats.

**Why — and this paragraph EXPLAINS a measured outcome; it does not measure
one.**  The zero delta is measured (four seed logs, byte-identical, diffed
rather than quoted, §6 and §6.2).  What follows is the mechanism the
implementer offers for it, and its two supports are citable: the LAT/WLAT
asymmetry below, and the unchanged throughput counters.  **Neither support
measures that the slack is ≥ 1 cycle at each of the 5,520 command
completions**, and nothing in this round does; that would need a per-command
probe in the chip TB, which is not this round's instrument.  Read the
paragraph as an account, and §6's table as the evidence.  The census attributes
+5,520 cycles over the whole six-step stream (§5.7) — **0.0028 %** of a
196.7 M-cycle replay — and the two rungs do not model the layer's state
window at the same speed.  `evidence/qwen9b/s4/run_s4_census.sh:17-21` says
it outright: the census's `LAT` defaults to **8**, and **40** "is what
`tb/tb_seq_chip.sv:436` gives the SAME window in the chip replay (`WLAT`,
`tb/tb_seq_chip.sv:69`)".  In the chip the layer's DNST/CONV/ATTN commands
therefore spend far longer waiting on state than they do in the census, and
a one-cycle change in the compute tail disappears into slack that was
already there.  The counters that stayed identical say the same thing from
the other side: **every throughput term of the replay — 383,606,784 weight
beats, 448,410/448,413 DDR beats, 108,762 write and 162,108 read bursts,
`busy_wr 50006166`, `busy_rd 47368548` — is unchanged**, so nothing about
what the chip moves or how long it takes to move it depends on this round.

**The two rungs are therefore doing different jobs and both are needed**: the
census reads `busy_cmp` per command directly and is the only instrument in
the ladder that CAN see a one-cycle change; the replay asks the only question
that matters to anything outside the layer — do the tokens move — and answers
no.

### 6.2 One provenance note, and a free reproducibility check

The replay ran twice.  The first run's four seeds completed and every one of
them printed `TB_SEQ_CHIP PASS` with the numbers in the table above
(`evidence/qwen9b/g5/seedlogs_t14a_model_9b_s/`), but the wrapper process was
killed before it aggregated its verdict, so
`evidence/qwen9b/g5/086_replay_t14a.log` has no `TOKENS` lines and no
`=== rc:`.  It is kept, because a log is never overwritten in this campaign
and its seed logs are real evidence.  **`087` is the complete run this
document cites**, on a fresh `LOGDIR`.

That accident bought a check nobody would have paid for: the two runs are
**byte-identical seed log for seed log** (every line but the artifact path),
so the 196.7 M-cycle replay of a 9 B model through this RTL is reproducible
to the cycle, twice, four seeds each.

---

## 7. The OOC rung — counts against a BASE control, and the cascade

### 7.1 The comparand is a BASE run of the SAME harness, not S5's log

S5's `evidence/qwen9b/s5/091_ooc_counts_g4b.log:16510-16533` is the shipped
comparand, but it was produced on a different tree, so a delta against it
mixes this round with everything between.  So the same harness was run a
second time on **BASE `a553f18`**, out of a detached `git worktree`, and it
reproduces S5's numbers **exactly**:
`evidence/qwen9b/g5/090_t14a_ooc_BASE_control.log` — `OOC9B_URAM: 182`,
`OOC9B_BRAM: RAMB36=77 RAMB18=8 tiles=81.0`, `OOC9B_DSP: 1838`,
`OOC9B_LUT: 114106 (logic 109610, memory 4496)`, `OOC9B_FF: 59836`,
`OOC9B_BRAM_SPLIT: scratch=62 conv=0 kvexp=4`.  **Every delta below is
therefore this round's.**

| count | BASE `a553f18` (`090`) | HEAD `1dd2889` (`088`) | Δ | |
|---|---|---|---|---|
| `OOC9B_URAM` | **182** | **182** | **0** | the escalation trigger did not fire |
| `OOC9B_URAM_SPLIT` | `dn=58 kv=116 cv=8 other=0` | identical | 0 | |
| `OOC9B_BRAM` | RAMB36 **77** / RAMB18 8 = **81.0** tiles | RAMB36 **79** / RAMB18 8 = **83.0** | **+2 RAMB36, +2.0 tiles** | **the note said unchanged — §7.3** |
| `OOC9B_BRAM_SPLIT` scratch | **62** | **64** | **+2** | all of the BRAM delta is the scratchpad |
| `OOC9B_DSP` | **1838** | **1840** | **+2** | |
| `OOC9B_LUT` | 114,106 (logic **109,610**) | 113,216 (logic **108,720**) | **−890, all logic** | the split muxes are CHEAPER |
| `OOC9B_FF` | **59,836** | **61,437** | **+1,601** | +2.7 % |
| `OOC9B_CARRY8` | 7,844 | 7,839 | −5 | |
| `OOC9B_SYNTH_S` | 874 s | 898 s | +24 s | |

**The FF delta, accounted for.**  Stage C adds 66 (`v2a` 1 + `x2a` 21 +
`a2a` 17 + `t2a` 27), D1 adds 32 × 40 + 3 = 1,283 and D2 16 × 40 + 3 = 643 —
1,992 by construction, against **1,601** measured.  Most of the 391
difference is Vivado trimming bits that reach nothing — `attn_core`'s
`o_sel` emits only `[31:0]`, which alone kills the top eight bits of the
32-word gather (256 FF) — and this document does not account for the
remaining 135 flops; it reports the measured number.  **The LUT count going
DOWN by 890 is the part worth noting**: three cheap mux levels cost less
logic than one 64:1 and one 128:1 did.

### 7.2 The cascade — the GREEN stage A exists for, as a controlled pair

The design note's risk 5 is explicit that an ignored attribute is the failure
class this campaign has been bitten by, and that the implementer must assert
the result **on the netlist**.  `evidence/qwen9b/g5/092_t14a_scratch_cascade_both.log`
runs one read-only instrument (`evidence/qwen9b/g5/g5c_scratch_cascade.tcl`,
new, which uses `synth/scripts/ooc_9b.tcl:237`'s own scratch selector) over BOTH
post-synthesis netlists:

| array | BASE `a553f18` | HEAD `1dd2889` |
|---|---|---|
| `smem_a` | 32 cells, `CASCADE_ORDER_B` **NONE = 32** (not cascaded at OOC) | 32 cells, **FIRST = 16, LAST = 16** |
| `smem_b` | 30 cells, **FIRST = 5, MIDDLE = 20, LAST = 5** (5 chains of 6) | 32 cells, **FIRST = 16, LAST = 16** |

**`MIDDLE` is GONE: 16 chains of exactly 2 on both arrays.**  That is
`cascade_height = 2`, honoured, measured on the netlist rather than read off
the source — and it is the whole of stage A's acceptance at this rung.
**Stage A′ (explicit 16 × 4096 banking) was NOT needed and was not taken.**

**One asymmetry, stated because it would otherwise mislead.**  At OOC the
BASE tool did not cascade `smem_a` at all (`NONE = 32`) and cascaded only
`smem_b`.  IN CONTEXT it cascades both: `evidence/qwen9b/g5/064_t14a_eto_smem.log`
reads `FIRST 5 / MIDDLE 20 / LAST 5` for `smem_a` AND `smem_b` on the routed
ETO checkpoint, and the failing `at_qdata` path launches from
`smem_a_reg_bram_*`.  So the OOC BASE run understates the problem; what it
establishes is the only thing this rung is for — that the attribute is
obeyed, on both arrays, deterministically.

It also explains the +2 BRAM exactly: `smem_b` goes from **30** tiles in
5 chains of 6 to **32** in 16 chains of 2, because 16 × 2 is the only
tiling of a 2-deep cascade that covers the array.  `+2` RAMB36 out of the
device's 2,160 (and of a design using 83).

`evidence/qwen9b/g5/089_t14a_ooc_cascade.log` is the design note's own
instrument (`g5b_t14a_smem_cascade.tcl`) on the HEAD netlist and says the
same thing (`SMC_CASCADE_B smem_a FIRST = 16 / LAST = 16`, no MIDDLE); its
three `SMC_CONE` probes report `pins=0` because their patterns are
context-scoped (`*u_core/dn_vdata_reg*`) and the OOC top **is** `layer_chan`.
`evidence/qwen9b/g5/091_t14a_ooc_BASE_cascade.log` is the same instrument on
the BASE netlist (`smem_b FIRST 5 / MIDDLE 20 / LAST 5`).

### 7.3 Two counts the design note said would not move — reported, not buried

The note's risk 3 predicted **BRAM 77/8 unchanged** and **DSP 1838 unchanged
or ±1**.  Measured: **BRAM +2 RAMB36 (81.0 → 83.0 tiles)** and **DSP +2
(1,838 → 1,840)**.  Neither is an escalation trigger (URAM is the count the
brief named, and it did not move), and both are small against the device —
83 BRAM tiles of 2,160, 1,840 DSP of 6,840.

**The BRAM +2 is attributed in §7.2** (`smem_b` 30 tiles → 32).  **The DSP +2
is attributed here**, because a count reported without a cause is the thing
this campaign's rule exists to prevent.

**It is `attn_core`, not `fx_silu`.**  `evidence/qwen9b/g5/101_t14a_ooc_hier_dsp.txt`
is the evidence file for this paragraph: it copies the
`report_utilization -hierarchical` "Utilization by Hierarchy" sections out of
the two gitignored OOC out dirs and differences the DSP column, and it
reproduces the review's independent derivation from the two committed logs.
Two rows move and only two:

| instance / module | BASE-equivalent | HEAD `1dd2889` | Δ |
|---|---|---|---|
| `layer_chan` (top) | **1,838** | **1,840** | **+2** |
| `u_attn` / `attn_core` | 526 | **529** | **+3** (all in `attn_core` proper; `u_recip` is 4 both ways) |
| `u_dn` / `dn_step` | 1,280 | **1,279** | **−1** |
| `u_conv` / `conv4_silu` | 7 | 7 | **0** — and `u_silu` / `fx_silu` is **3 both ways** |
| `u_alu`, `u_gate`, `u_rope`, `u_vn`, `u_topk`, `u_axib`, `u_dma` | — | — | **0** |

**Stage C costs zero DSPs.**  The only thing that changes in `fx_silu` is the
name Vivado gives the interpolation multiply: `090:10233`
`DSP Report: Generating DSP u_silu/sig23, operation Mode is: A*B''.` becomes
`088:10325` `… Generating DSP u_silu/t2a1, operation Mode is: A*B''.` — one
DSP, same mode, with `u_silu/m3_reg` and `u_silu/m4_reg` present and
unchanged on both sides.  The change of name is the split: the multiply is
now captured by the register `t2a` instead of by `sig2`.

**What the +2 actually is: a synthesis re-inference of adders that were
already there.**  Vivado's DSP-inference tally over the two logs goes from
**1,843** generated at BASE to **1,848** at HEAD (+5, of which 3 are absorbed
again, netting +2).  The moving sites are `attn_core`'s `psum4` adder tree —
`Generating DSP g_ps4[i].psum4_reg[i]` goes from **2** sites (i = 0, 7) to
**6** (i = 0, 4, 17, 32, 34, 50), `p_4_out` 8 → 10 and `p_1_out` 384 → 383.
`g_ps4` is `rtl/attn_core.sv:227-231`, the 64 sums-of-4 — D1's own module,
but **not D1's own logic**: this round added no arithmetic operator anywhere,
D1 and D2 add mux levels and registers and C moves a clock edge.  **The +2 is
not a designed multiplier**; it is the note's risk 3 ("if Vivado's DSP
re-inference wobbles") firing at the smallest scale it could.

**One honest gap in the evidence file, stated there and here.**  The BASE
control's own hierarchical report is gone: `090` ran out of the detached
worktree of §10.6, and that worktree was removed when the round closed.  The
comparand in `101` is therefore S5's OOC run of the same harness
(`synth/out_ooc9b_s5fix_layer`, `evidence/qwen9b/s5/091_ooc_counts_g4b.log`,
tree `5cb1899`), admissible because **every** aggregate counter it reports —
URAM 182, RAMB36 77 / RAMB18 8, DSP 1,838, LUT 114,106 (logic 109,610,
memory 4,496), FF 59,836, CARRY8 7,844 — is byte-identical to `090`'s.  That
is a match on the table's top row, not a proof about its inner rows; the
independent check is §D of `101`, which is the actual BASE and HEAD logs.
**For Task 14-B: capture the OOC run's hierarchical utilization report into
`evidence/` at the time of the run**, so the next round's attribution needs
no reconstruction.

**Carry the number to 14-B for the floorplan.**  S5 recorded the layer at
**1,838 of SLR1's 2,280 DSPs = 80.61 %**; **1,840 is 80.70 %**.  The one-SLR
floorplan's DSP headroom was **442** slices and is now **440** — this round
spent 2 of it.

### 7.4 What the OOC rung does NOT say

`SMC_WNS: 0.483` (HEAD) and `0.333` (BASE) appear in those logs.  **They are
not a timing result and must not be quoted as one**: out of context,
unplaced, on a 4.000 ns clock the harness writes only so the run is not
unconstrained, with `HD.CLK_SRC` unset (Vivado warns about exactly this in
both logs).  The timing question belongs to Task 14-B.

---

## 8. NOT ESTABLISHED by this gate

1. **No timing number.** Nothing was placed and nothing was routed on this
   RTL.  Every WNS figure in the design note — the −1.0 … −1.3 ns on the
   scratchpad cones, `CONV_SILU_M3` "from −0.238 to roughly +1.4", the value
   of splitting a 128:1 or a 4 × 64:1 mux — is an **estimate**, and this
   round leaves it one.  The OOC rung (§7) is a **counts and netlist-property**
   run: out of context, unplaced, on a 4.000 ns constraint written only so
   the run is not unconstrained.
2. **The cascade GREEN is the SYNTHESIS property, not the routed one.**
   §7 reports `CASCADE_ORDER_B` off the OOC netlist.  The design note's other
   half of that GREEN — `Logic Levels: … RAMB36E2=1` on the
   `dn_vdata`/`at_qdata`/`s_axil_rdata` probe paths — needs a placed and
   routed IN-CONTEXT design and is Task 14-B's to produce.
3. **The residual is untouched.** The design note §7 named what these four
   changes do not fix: the design WNS on `mmcm_clkout0_3` (300 MHz,
   `mvchan_2`'s `xline_q0` CE cone, a DIRECTIVE choice worth +0.009 on the
   `AltSpreadLogic_high` family), the `seq rec → pc/CE` and `u_dma f_wp →
   fmem` families, and the systemic `aclk` clock-skew term.  None of them is
   in this round's set.
4. **The 9B model artifacts were NOT re-emitted** and this round says nothing
   about the emitter.  The census and the replay both ran against S4's
   `tb/scripts/w9/model_9b_s*` byte-for-byte, which is the point of the
   token-identity bar.
5. **One stream, one operating point.** The census is `model_9b_s1` at
   `LAT = 8` in draining mode, as S4's was; the fence-hold behaviour S4
   measured with `NODRAIN=1` was not re-measured, because nothing in this
   round touches a fence.

---

## 9. Handoffs to Task 14-B

1. **Rebuild on this RTL.**  The controller's ruling puts 14-B on the
   `AltSpreadLogic_high` directive family (the design note's stage E: the
   same netlist probed **+0.009** on `xline_q0*/CE` there against −0.130 on
   `ExtraTimingOpt`, `evidence/qwen9b/g5/062_t14a_po2_cones.log:356` and
   `060_t14a_eto_cones.log:219`), with the clock-skew experiment as the
   constraint-side arm.
2. **Re-run the two Task 14-A instruments on the rebuilt checkpoint.**
   `evidence/qwen9b/g5/g5b_t14a_cone_census.tcl` and
   `g5b_t14a_smem_cascade.tcl` were written for exactly this comparison and
   their ETO/po2 outputs are the comparands.  The two questions are whether
   the four cones left the failing set and what the residual is made of now.
3. **The LCYC change is host-visible.**  `sw/cycle_census.py` and anything
   that has memorised a per-command cycle count reads +1 on CONV, DNST and
   ATTN.  Nothing in `ref/` models cycles (`ref/seq_model.py:745`), so no
   reference or emitted script moves.
   **One committed SCRIPT holds such a number and is named here rather than
   left to the generic clause**: `b9e0851:evidence/qwen9b/g4/g4b_layer_term.py:42`
   hard-codes `T10 = {"control RLAT=2 P2_WAIT=0": 1798,` — the per-head
   `tb_dn_step` figure from `evidence/qwen9b/g3/G3_4_LAYER.md` §4.3, now
   **1799** on this RTL (`077`, §5.2).  Its sibling entry
   `"option (i)  RLAT=6 P2_WAIT=1": 1930` at
   `b9e0851:evidence/qwen9b/g4/g4b_layer_term.py:43` is now **1931** (`075`).
   It was not edited in THIS round — it is an S-stage analysis script outside
   the commit block and nothing in the ladder runs it — so whoever next ran it
   would have read a stale baseline.
   **DONE 2026-09-10 (#190, pre-ship tool chore):** both constants WERE
   updated, and option (ii) — the configuration 14-A never re-ran — was
   RE-MEASURED at 1803 (`evidence/qwen9b/g4/089_dn_step_pipe_ii_t14a.log`).
   The two citations above are PINNED to `b9e0851` because they quote the
   values as they stood.  Nothing is left for a later runner to update.
   `sw/cycle_census.py:32` only READS LCYC and needs nothing.
4. **If Vivado's `cascade_height` is honoured but the widened bank mux costs
   more than the cascade saved**, the note's `cascade_height = 4` middle
   point is the measured fallback and needs no RTL restructuring — one
   character in two lines.

---

## 10. Deviations declared

1. **`tb_seq_layer` did not run** — it does not build at BASE either
   (§5.4, control `076`).  Reported for the final triage; not repaired,
   because `tb/seq_mem_file.sv` and `tb/tb_layer_chan.sv` are outside this
   round's commit block and the sibling target that covers the same DUT far
   more heavily passes.  **Its disposition — BROKEN, to be repaired rather
   than retired — is item 9.**
2. **`tb_layershim_c` is RED on the final tree under the Makefile's
   `+verilator+rand+reset+2`** and GREEN at BASE — proven in §5.6 to be the
   random-init stream and not this ROUND's doing, with both trees behaving
   identically under every deterministic initial state.  Reported, not
   repaired.  **What it is — a real missing reset in `rtl/layer_chan.sv`,
   latent and inert on a bitstream — is item 10.**
3. **The census table lands in `evidence/qwen9b/s4/`, not `g5/`** — the S4
   runner hard-codes `$SCRIPT_DIR/census_<cfg>.txt`
   (`evidence/qwen9b/s4/run_s4_census.sh:101`), and this round does not edit
   that committed runner.  `evidence/qwen9b/s4/census_t14a.txt` is therefore
   a **declared one-file extension** of the commit block: a new file, created
   by an existing committed script, touching nothing.
4. **`080_t14a_census.log` is an incomplete log, and it left NO artifact.**
   The first census run was killed by its launcher.  **`080` produced no
   table**: its 39 lines end at the `=== run t14a: +script=… +census=…` line,
   with no census output and no verdict, and the table at
   `evidence/qwen9b/s4/census_t14a.txt` is the file **`081`** wrote — the
   runner hard-codes that path (`evidence/qwen9b/s4/run_s4_census.sh:101`)
   and `081` overwrote whatever `080` may have started.  An earlier draft of
   this item claimed "both produced the same table"; **that claim has no
   artifact behind it and is withdrawn.**  `080` is kept rather than deleted
   (logs are never overwritten in this campaign) and `081` is the complete
   run this document cites.  The analogous claim on the replay side IS
   evidenced and stands: `086`'s and `087`'s four seed logs exist and are
   byte-identical (§6.2).
5. **The citation-drift pass edited eleven files outside the RTL block**
   (four documents, four gate documents, `ref/layer_fixed.py`,
   `synth/exp_uram/rtl/layer_chan.sv`).  That is what "citation drift for
   every edited file" requires; every rewrite is in place and no document's
   line count changed.
   **The `synth/exp_uram/` copies are a FROZEN experiment snapshot and only
   the citation was repaired in them.**  `synth/exp_uram/rtl/layer_chan.sv`
   was touched by `96ae645` because it carries a **citation** into `rtl/`
   that drifted; its sibling `synth/exp_uram/rtl/conv4_silu.sv:15` still
   reads `latency = 4 + fx_silu(6) = 10` — the pre-stage-C number — and
   **that is left stale deliberately.**  Those files say so themselves
   (`synth/exp_uram/rtl/conv4_silu.sv:1-10`: "EXPERIMENT COPY — NOT MIGRATION
   RTL … Source of truth stays `rtl/conv4_silu.sv` … Copied from
   `rtl/conv4_silu.sv` @ git `aa9c1efa`"); the directory exists to answer one
   placement question and is not functionally verified, so a comment
   describing the file it was copied from is correct **as a snapshot** and
   would become a lie if updated to this round's number.  The round touched
   one file there and not the other because the two edits are different
   kinds: a stale cross-file citation is drift and gets repaired; a stale
   in-file comment inside a frozen copy is the snapshot working as intended.
   **No `synth/exp_uram/` file is a source of truth for anything in this
   gate.**
6. **A detached `git worktree` at `a553f18`** was created under
   `/home/cah/r2d2/code/fpga/fable5_t14a_base` to produce the BASE OOC
   control (§7.1) and the BASE `tb_layershim_c` binary (§5.6).  It is
   outside the repository and is removed when this round closes; nothing in
   it is committed.
7. **Two new files under `g5/`**: `g5c_scratch_cascade.tcl` (the read-only
   cascade tally, §7.2) and this document.  No existing `g5/` file was
   edited — `G5B_TIMING.md` cites the 06x instruments by name and they are
   byte-untouched.  Review round 1's fix adds a third,
   `101_t14a_ooc_hier_dsp.txt` (§7.3), which is a COPY of two gitignored
   reports plus a tally of two committed logs — no run.

8. **`099`'s verdict line reads FAIL, and the drift pass took an exclusion
   plus a hand repair.**  Both are disclosed here because the campaign's rule
   is that every committed log's own verdict line is stated, and a verdict
   that is not a clean PASS is called out even when the residual is harmless.

   **(a) The verdict.**  `evidence/qwen9b/g5/099_t14a_cite_drift_verify.log`
   ends `O3_CITE_DRIFT VERIFY FAIL (2 problem(s))`, `=== rc: 1`.  The two
   problems are `! UNRESOLVED rtl/layer_chan.sv:503` and
   `rtl/layer_chan.sv:504`, both "cited by
   `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md`".
   **They are benign, and are being LEFT rather than repaired.**  The
   citation is at that spec's `:1130` and reads ``(`rtl/layer_chan.sv:503-504`,
   `logic signed [15:0]`)``.  Stage A **prefixed** `(* cascade_height = 2 *)`
   to those two declarations, so their CONTENT changed while their LINE
   NUMBERS did not move (§2.1: the file gains no line).  The checker anchors
   on whole-line content, so a changed line at an unchanged number is
   reported `UNRESOLVED`; the citation itself is still correct — 503-504 are
   still the right lines and the quoted fragment `logic signed [15:0]` still
   appears on both.  Nothing to repair: rewriting the spec's line numbers
   would make them wrong.  **This is a known false-positive class of the
   instrument, not a residual defect in the tree**, and the same reasoning is
   in `96ae645`'s commit message.

   **(b) The exclusion and the hand repair.**  `095` came back
   `O3_FIX_PLAN: UNSAFE — 1 of 40 rewrites would move a citation that is
   already correct`, because `evidence/qwen9b/g2/D_TOL.md` cites BOTH
   `rtl/attn_core.sv:211` and `:213-218` and `:211` relocates ONTO `:213`, so
   a textual `--fix` over that document could double-shift the range.
   `evidence/qwen9b/g2/D_TOL.md` was therefore `--exclude`'d from `097`
   (`SAFE`, REPAIR 33 COLLATERAL 0) and from `098`'s `--fix`, and **its SEVEN
   citations were repaired BY HAND** against `096`'s `--check` mapping.  What was repaired,
   exactly — all of them `rtl/attn_core.sv`, all in `96ae645`:
   `:211 → :213`, `:213-218 → :215-220`, `:222 → :224`, `:432 → :457`,
   `:436 → :461`, `:437 → :462`, `:173 → :175`.  The file's line count did
   not change (`git show --numstat 96ae645 -- evidence/qwen9b/g2/D_TOL.md`
   is `7	7` — 7 lines rewritten in place, 7 out; this said 14 and 14 until
   2026-09-10).  §10.5's row named the
   pass as "plan-with-exclusion" without naming the document or the hand
   repair; it is named here.

9. **`tb_seq_layer` is BROKEN, and is ledgered as broken — not retired.**
   §5.4 has the evidence; this item records the disposition.  The failure is
   **25 `-Wall` warnings in TESTBENCH FILES ONLY** —
   `WIDTHTRUNC`/`WIDTHEXPAND` in `tb/seq_mem_file.sv:225-435` and
   `UNUSEDPARAM` in `tb/tb_layer_chan.sv:165-176` (**sixteen unused localparams
   on eight lines**, counted in `071`, which names every one; the range read
   seven lines starting at 170 until 2026-09-10) — and `076` reproduces the
   identical 25 with BASE `a553f18`'s `rtl/` substituted file-for-file, so it
   is **pre-existing and not this round's**.  The target is real and reachable
   (`tb/Makefile:529-530`) and `071` runs it, but **nothing in the campaign's
   ladder depends on it**: it is not a prerequisite of any other target, and
   the sibling `tb_layer_chan` compiles the same DUT and passes 1,465
   commands / 261,357 checks per seed against `tb_seq_layer`'s much smaller
   stimulus.  **It should be REPAIRED, not deleted** — retiring a build target
   because it fails lint removes a check instead of fixing one, and the fix is
   cheap (**sixteen** unused localparams on eight lines — `071` names every
   one — plus the `$(XLIB)` / file-list difference
   the sibling target already gets right).  *(The estimate said six until
   2026-09-10; it is 2.7× that.)*  Correctly out of this round's
   commit block; carried to the final triage.

10. **The `tb_layershim_c` RED is a REAL LATENT RTL DEFECT — a missing reset —
    not a testbench quirk.**  §5.6 proves it is not this round's (both trees
    behave identically under every deterministic initial state, and 8 of 8
    explicit random seeds fail on both), and the implementer's phrase "a
    pre-existing random-init sensitivity" is true but could be read as
    blaming the TB.  **It is the RTL.**  `rtl/layer_chan.sv:526-531` declares
    `(* keep = "true" *) logic rstn_q, rstn_i;` in an `always_ff` with **no
    reset of its own**, so a randomised 1 there releases the layer's
    dispatcher for a cycle while `aresetn` is still low and it executes a
    random `st`/`cmd_op`/`arg0`.  The signature is diagnostic: the failure is
    at `[2000]`, before the TB drives anything, and it is
    `vecnorm_unit: cfg_nlog2 13 unsupported` in a TB that never issues a VN
    command.  **On a bitstream the defect is inert** — Xilinx FFs power up at
    0, so `rstn_i = 0` holds the layer in reset — which is why it has never
    been seen on hardware and why it is not an escalation.  **Out of this
    round's scope**: the local reset pipeline is a `build_020` timing
    structure and adding a reset to it is an RTL change with its own timing
    consequence, needing its own round.  Ledgered as latent, RTL, missing
    reset.

---

## 11. The claims this document makes, and where each number comes from

| claim | label | source |
|---|---|---|
| `(* cascade_height = 2 *)` is accepted by Verilator 5.020 with no warning | M | `070`, `073`, `074`, `075`, `077` — `lint_layer_chan rc=0` |
| the round adds exactly ONE lint waiver, `UNUSEDSIGNAL` on `t2a` alone | M | `git diff a553f18..7c25f15 -- rtl/` — one added `lint_off`/`lint_on` pair, `rtl/fx_silu.sv:84-86` (§3.1, §5.1) |
| the s2 split is bit-exact BECAUSE the truncations are unchanged — and would have been under a signed `t2a` too | D | review round 1 §I-2: 400,125 `(a, b, lo1)` triples, 199,782 with bit 26 set, 0 mismatches either way (§3.2; a Python re-derivation, no log) |
| the cascade is 2 deep on the synthesised netlist (`MIDDLE` gone) | T | `092`, `089` |
| the same instrument on BASE shows `smem_b` FIRST 5 / MIDDLE 20 / LAST 5 | T | `092`, `091` |
| URAM 182 unchanged | T | `088` vs `090` |
| BRAM +2 RAMB36 (81.0 → 83.0 tiles), all of it `smem_b` 30 → 32 | T | `088`/`090` `OOC9B_BRAM_SPLIT`, explained by `092` |
| DSP 1,838 → 1,840; LUT −890 logic; FF +1,601 | T | `088` vs `090` |
| the +2 DSP is `attn_core` +3 / `dn_step` −1, `fx_silu` unchanged — a `psum4` re-inference, not a new multiplier | T | `101_t14a_ooc_hier_dsp.txt` (the two hierarchical reports) and the `DSP Report` tallies in `088` / `090` (§7.3) |
| `099` ended `O3_CITE_DRIFT VERIFY FAIL (2 problem(s))`, both residuals benign | M | `evidence/qwen9b/g5/099_t14a_cite_drift_verify.log:22`; the two residuals are the migration spec's line 1130 citing `rtl/layer_chan.sv:503-504`, whose lines did not move (§10.8) |
| `fx_silu` is bit-exact after the split | M | `077` `TB_FX_SILU PASS: 409 cases bit-exact` ×4 |
| `dn_step` costs exactly one more cycle per head | M | `077` `DN_CYCLES … 1799` vs the recorded 1798 |
| the layer is bit-exact at 261,357 checks per seed | M | `077`/`078` `TB_LAYER_CHAN PASS: 1465 cmds, 261357 checks` ×4 |
| the F1 fence still fails when bypassed | M | `078` `OK: the F1 bypass reads stale state and FAILS` ×4 |
| CONV/DNST/ATTN each cost exactly +1 cycle per command and nothing else moved | M | `081` and `evidence/qwen9b/s4/census_t14a.txt` beside `evidence/qwen9b/s4/census_s4shipped.txt` |
| the tokens are identical to Task 11's record on 4 of 4 seeds | M | `087` (and the interrupted `086`'s four seed logs, independently) |
| the chip cycle counts did NOT move | M | `087` seed logs vs `evidence/qwen9b/s4/S4_REPLAY.md` §4.2 |
| `tb_seq_layer` was already broken at BASE | M | `076` |
| `tb_layershim_c`'s RED is the random-init stream, not the RTL | M | `079`, `093` |
| the timing gain | **NOT ESTABLISHED** | the design note's estimate; Task 14-B measures it |

---

## 12. `spec_cites.py`, LAST, on the committed tree

The final commit of this round holds **only** the `spec_cites.py` log, run on
the tree of the commit immediately preceding it, so what the checker read is
exactly what shipped.  `PENDING` needed no prune: the set at
`evidence/qwen_next/spec_cites.py:109-197` holds only
`evidence/qwen9b/g6/RD9_GATE.md` (Task 15's), and this document is a live
path by the time the checker runs.
