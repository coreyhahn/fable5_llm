# G3.4 — `layer_chan` at 9B: the `int16` DN banking, `DN_PIPE = 2`, KV at NKVH = 4, NH = 32, CONV, EMBLOG2 13, and the synthesizable envelope

**Gate:** spec §4.1 W1′ (A1.1, A1.2, A1.7), §4.6 W6 walls 8–11 and 16,
§5.3 S8, §5.4 S9, §0b A2.1. Plan Task 10.
**Base:** `8138d66`. **Host:** snoke (Verilator 5.020), board untouched.

---

## 1. The claim

`rtl/layer_chan.sv` now carries the **9B geometry and nothing else**: 24
DeltaNet slots × 32 heads of `int16` DeltaNet state in **24 URAM banks, one
layer per bank**; 8 GQA slots × 4 kvheads of KV cache in **8 banks, one layer
per bank**; 24 conv banks of 8192; `NH = 32` in `gate_unit`; `EMBLOG2` reset
13; and every envelope guard that used to be `` `ifndef SYNTHESIS `` is now a
**hardware refusal**. The DN read/write path carries Track P's **`DN_PIPE = 2`**
register stages, and `rtl/dn_step.sv` leads its read address by the 6 cycles
that costs.

**928 URAM288 of 960 (96.7 %)** — 24 × 29 = 696 DN + 8 × 29 = 232 KV. That
arithmetic is **label S** (spec arithmetic on Track P's primitive counts);
**Task 12's OOC synthesis is what measures it** (spec A1.5: G4's OOC URAM
check moves 592 → 928). Nothing here was synthesized, placed or timed.

---

## 2. The DN banking map

### 2.1 The address, and why the cut falls where it does

One linear address, cut at the URAM depth:

<!--cites:noquote-->
```
  dn_lin_r = { dn_layer_r , dn_head , dn_rda }        (17 bits)
             \__ bank __/ \__ in-bank address (12) __/
```
*(shorthand for the three declarations, not a quotation.)*

At **LNH = 32** the `head + row` field is 5 + 7 = **exactly 12 bits**, which
is a URAM's depth, so the cut falls exactly on the slot boundary: one bank
holds exactly one layer's state and `DN_NB = 24 × 32 × 128 / 4096 = 24`.
`rtl/layer_chan.sv:317-322` derives it; `rtl/layer_chan.sv:583-590` forms it.

This **replaced** the shipped hand-split — bank `dn_layer_r[4:1]`, in-bank
`{dn_layer_r[0], head[3:0], row[6:0]}`, *"9 URAM banks, each holds two dn
slots via an in-bank MSB"*. **U4 is what licenses that**: with one geometry
the map no longer has to reduce bit-identically at LNH = 16, so it is laid
out for 9B alone (spec §4.1's amended address paragraph).

The KV array gets the same treatment (`rtl/layer_chan.sv:704-708`):  <!--cites:noquote-->

<!--cites:noquote-->
```
  kv_lin_r = { kv_layer_r , kvhead_r , at_kvaddr }    (15 bits)
             \__ bank __/ \__ in-bank address (12) __/
```
*(shorthand, as above.)*

At **NKVH = 4** the in-bank address is **full** with `{kvhead[1:0], k/v,
t[8:0]}` — which is spec §4.6 wall 9's *"the 12-bit in-bank URAM address has
no spare, so KV capacity per bank doubles or T halves"*, resolved by the
8-bank re-banking rather than by halving T. `T ≤ 512` is unchanged.

### 2.2 The URAM arithmetic — label **S**, measured by Task 12

| array | banks | rows × width | URAM288 per bank | total |
|---|---|---|---|---|
| DN state | **24** (one dn slot each) | 4096 × 2048 b | 29 | **696** |
| KV cache | **8** (one kv slot each) | 4096 × 2048 b | 29 | **232** |
| | | | | **928 of 960 (96.7 %)** |

29 per bank is Track P's measured primitive count for a 4096 × 2048 b array
(`PLACE_EXP.md`); 928 is the `wide` row Track P **placed**, spread
312/312/304 of 320 per SLR. **Three SLRs are mandatory** — 2 × 320 = 640 <
928 (A1.4).

`emem` (the KV exponent memory) is deliberately **outside** the URAM: it
carries no `ram_style` attribute, so it infers into BRAM/LUTRAM beside the
array. That is stated in the RTL comment at `rtl/layer_chan.sv:687-696` so
nobody later reads its absence from the 232 as an error.

**No int8 anything.** A1 ruled the container `int16`, so there is no
narrowing law, no `sat8`/`e_fixup` counter, no packed half-row, no
write-combining register in this RTL. The experiment file's `DN_EW` /
`DN_PACK` knobs are **absent here on purpose**.

---

## 3. `DN_PIPE = 2` — and its correspondence to what Track P placed

### 3.1 The structure

Two register stages on the per-group control/address/write-data **fan-out**
and two on the read **return**, so every long haul runs flop-to-flop:

* `dn_bsel_d[DN_SDEL]`, the bank-select delay line, `DN_SDEL = 2*DN_PIPE + 1`;
* per group: `dont_touch`'d `ra_p`/`wa_p`/`wd_p`/`w_p`/`bs_p` arrays of
  `DN_PIPE` entries;
* per group: a local `NB:1` mux into `rq_p[0]`, then `DN_PIPE` return
  registers, then a small `DN_GRP:1` mux into the OREG.

`DN_BPG = 8` groups the 24 banks onto the 3 SLRs; `DN_BPG = 1` measured
**worse** (−1.956 ns, 12,692 failing endpoints), so it is not a knob to turn.

`dont_touch` is mandatory — without it synthesis merges the identical
per-group fan-out registers back into one and the whole point is lost.

### 3.2 File:line correspondence to the experiment RTL

`synth/exp_uram/rtl/layer_chan.sv` is **NOT EDITED by this task**. The
shipping structure is the same generate, with the int8 branches removed:

| structure | shipping `rtl/layer_chan.sv` | experiment `synth/exp_uram/rtl/layer_chan.sv` |
|---|---|---|
| `DN_PIPE` parameter | `rtl/layer_chan.sv:210` | `synth/exp_uram/rtl/layer_chan.sv:232` |
| `DN_BPG` parameter | `rtl/layer_chan.sv:216` | `synth/exp_uram/rtl/layer_chan.sv:239` |
| `DN_SDEL` localparam | `rtl/layer_chan.sv:329` | `synth/exp_uram/rtl/layer_chan.sv:329` |
| bank-select delay line | `rtl/layer_chan.sv:602-606` | `synth/exp_uram/rtl/layer_chan.sv:633-637` |
| per-group return array | `rtl/layer_chan.sv:607` | `synth/exp_uram/rtl/layer_chan.sv:638` |
| `g_grp` generate | `rtl/layer_chan.sv:608` | `synth/exp_uram/rtl/layer_chan.sv:639` |
| `dont_touch`'d fan-out regs | `rtl/layer_chan.sv:609-613` | `synth/exp_uram/rtl/layer_chan.sv:640-644` |
| per-group bank array `g_dn` | `rtl/layer_chan.sv:628-635` | `synth/exp_uram/rtl/layer_chan.sv:660-667` |
| local mux + return regs | `rtl/layer_chan.sv:640-647` | `synth/exp_uram/rtl/layer_chan.sv:671-678` |
| group return assign | `rtl/layer_chan.sv:648` | `synth/exp_uram/rtl/layer_chan.sv:679` |
| final `DN_GRP:1` mux into the OREG | `rtl/layer_chan.sv:651-653` | `synth/exp_uram/rtl/layer_chan.sv:682-684` |

The differences are exactly three, all of them the absence of int8:
`DN_W` → the literal `2048`, `dn_wd_n`/`dn_w_n` → `dn_wd`/`dn_w`, and the
`DN_SH` half-select is gone. **The read/write path is otherwise line-for-line
the design Track P placed as `r3pipe2alt`.** Task 13 re-runs the experiment
on the shipping sources; if that re-run needs `-generic` names, the shipping
file exposes `DN_PIPE` and `DN_BPG` under the same names and the geometry
knobs are localparams at their 9B values (`rtl/layer_chan.sv:296-300`).

### 3.3 What `DN_PIPE = 2` does and does not buy

**Buys** (Track P, label **T**): the named 2048-bit DN bank-mux net goes
−1.848 → −0.162 ns at the Default directive and **MEETS at +0.097 ns** under
`AltSpreadLogic_medium`. **That MET carries the directive dependency and this
document states it every time it quotes the number.**

**Does not buy**: it does **not close the module** (−1.391 / −2,007.2 /
6,638 failing endpoints). The binding constraint is the **write-control
fan-out**, one logic level with 95.9 % route — *a placement signature, not a
structural one* — and **the pblock for it was never tried and can still
invalidate the target** (A1.3).

`DN_PIPE = 1` is not a cheaper option: **N = 1 does not close** (−0.339).

---

## 4. STEP 1′ — the `dn_step` read-latency DESIGN DECISION

> **This section exists to be reviewable on its own.** A reviewer may reject
> the latency choice here without rejecting anything in §2, §3, §5 or §6:
> the banking, the KV lockstep, the widths and the envelope do not depend on
> which of the two options ships, and the option is selected by ONE
> localparam (`rtl/layer_chan.sv:337` `DN_P2WAIT`).

### 4.1 The problem, exactly

`dn_step` reads the state memory once per row per pass — 256× per head. At
`DN_PIPE = 2` the read return is `2 + 2N = 6` cycles, so the address must
lead its use by **6**. Consumption is fixed at **two states after the loop
head** in both passes (`dec_p` latches leaving `P1_DECM`; `sf_row` latches
leaving `P2_OUT`), so a tail issue gives lead **2** whatever the loop length.

### 4.2 What was implemented — and it is TWO changes, not one

1. **The issue point moved from each loop's TAIL to each loop's HEAD.**
   `rtl/dn_step.sv:255` (in `P1_RD`) and `rtl/dn_step.sv:290` (in `P2_RD`)
   now carry the read-address issue that used to sit in `P1_KW` and `P2_QW`. The address
   is then held for a whole loop period, so the memory samples it at the
   right cycle **at both RLAT = 2 and RLAT = 6** — which is what lets one FSM
   serve both and lets this gate MEASURE the price instead of modelling it.
2. **`P1_PRE`** (`rtl/dn_step.sv:246-250`) holds RLAT minus 2, i.e. 4, cycles before
   pass 1's first read, because that read has no previous iteration to lead
   it — `IDLE` issues address 0 immediately before `P1_RD`. This is Track P's
   *"only pass 1's first read pays"*.
3. **`P2_WT`** (`rtl/dn_step.sv:293`) is **option (i)**, the wait state in
   pass 2's loop, selected by `P2_WAIT`. `layer_chan` derives it from the
   latency at `rtl/layer_chan.sv:337`.

### 4.3 The measurement — label **T**, in sim, 4 seeds each

`tb_dn_step` reports `DN_CYCLES` = start-pulse to `done`, per head. All four
vector seeds gave the **same** cycle count in every configuration (the FSM is
data-independent), and all four were **bit-exact against the same committed
goldens** in every configuration.

| build | RLAT | `P2_WAIT` | **cycles / head** | Δ vs control | log |
|---|---|---|---|---|---|
| control, unpipelined | 2 | 0 | **1798** | — | `232_tb_dn_step_rlat2_cycles.log` |
| **option (i) — SHIPPED** | 6 | **1** | **1930** | **+132 (+7.34 %)** | `231_tb_dn_step_pipe_rlat6_optI.log` |
| option (ii) — not shipped | 6 | 0 | **1802** | +4 (+0.22 %) | `233_tb_dn_step_pipe_rlat6_optII.log` |

> **All three numbers moved by +1 on the 14-A RTL — dated note 2026-09-10
> (#190, pre-ship tool chore; review m3).** This table is the ORIGIN of
> 1798 / 1930 / 1802 and they are correct AS MEASURED HERE, on this gate's
> tree. Task 14-A's `tb_dn_step` re-measurement makes them **1799 / 1931 /
> 1803** — one extra cycle per head in every configuration. The measurement
> and its logs are in `evidence/qwen9b/g5/G5C_RTL.md` §5.2 (`077`, `075`) and,
> for option (ii), `evidence/qwen9b/g4/089_dn_step_pipe_ii_t14a.log`; the
> comparator table in `evidence/qwen9b/g4/g4b_layer_term.py` carries the new
> values. Nothing here is renumbered: a reader of this table must simply add
> the +1 before comparing with anything post-14-A.

The +132 decomposes exactly as designed: **+128** for one extra state in
pass 2's 128-row loop, **+4** for `P1_PRE`.

**Track P's bound was "≈ +10 % on ~1300 cyc/head".** Measured against this
build's own base of 1798 it is **+7.34 %**. The ~1300 figure was the RTL
header's estimate; 1798 is what the FSM actually takes.

### 4.4 Option (ii) — the sketch, and its honest status

**It is a `dn_step` FSM change, not a `layer_chan` interface change.** The
contract is local: `dn_rdq` is driven once and consumed at exactly one port,
and `layer_chan`'s collection is a count-based handshake, not a latency-timed
one.

**And the sketch is now more than a sketch: it is `P2_WAIT = 0` at
`RLAT = 6`, i.e. deleting one state.** With the issue point at the loop head,
pass 2's five-state loop holds each address over
`[a_r − 4, a_r]` and the memory samples it at `a_r − 4`, which is inside that
window with nothing to spare. It was **built and run** — 4 seeds, bit-exact
against the same goldens, 1802 cycles/head (`tb_dn_step_pipe_ii`, log
`233_…optII.log`).

**This corrects Track P on a point of fact and the correction is recorded
rather than quietly used.** `PLACE_EXP.md` §5 says *"N=2 needs a lead of 6,
and pass 2's loop is only 5 states long, so it cannot be absorbed by moving
the issue point at all"*. Moving the issue point to the loop **head** — four
states earlier than the tail, not the two states §5 considered — yields lead
6 exactly. Track P's arithmetic stopped one state short.

**Status, stated as honestly as the brief demands:**

* functionally **proven in sim** at this gate (bit-exact, 4 seeds);
* **NOT proven to close**, because nothing in this task was synthesized,
  placed or routed. The hardware is identical between (i) and (ii) — the same
  banks, the same `dont_touch`'d pipeline, one fewer FSM state — so the
  timing risk is small, but *small* is an argument and Task 13 is the
  measurement;
* its margin is **zero cycles**. Option (i) carries one cycle of margin on
  pass 2's lead. That is what the 128 cycles/head buy.

### 4.5 Which was taken, and why

**Option (i) ships.** Reasons, in order:

1. The brief and spec §4.1 W1′(a) order it: *"Implement (i) first, because it
   is the one that is bounded and it unblocks Tasks 11–13"*, and *"an
   unmeasured restructure that removes a 10 % penalty is worth less than a
   measured wait state that does not"*.
2. Option (i) is the configuration every TB in §7 ran against, so it is the
   one with integration evidence behind it, not just a unit result.
3. Option (ii)'s lead is exact — zero cycles of margin. Taking it now would
   spend that margin before Task 13 has placed anything.

**What a reviewer is being asked to decide.** Option (ii) is a one-word
change (`rtl/layer_chan.sv:337`, `DN_P2WAIT` 1 → 0) worth **128 cycles per
head, ≈ 7.1 % of the DeltaNet step**, and it is functionally proven here.
A reviewer who judges that a zero-margin lead is acceptable given that both
options synthesize to the same hardware may take it, and nothing else in this
gate changes.

### 4.6 The two-run census handed to Task 12 (A1.6)

Task 12 owns the **layer term** — this gate measured `dn_step` alone, which
is the per-head recurrence and not the whole DNST command (vector preload,
the DNSB scalar loads, the 256-word collect) nor the layer body around it.
**The request:** run the layer-level cycle census twice on the shipping tree,
at `DN_PIPE = 2` (the default) and at `DN_PIPE = 0`
(`layer_chan #(.DN_PIPE(0))` — `dn_step`'s `RLAT` and `P2_WAIT` follow
automatically, `rtl/layer_chan.sv:331-337`), and difference the per-token
cycle counts. `tb_seq_layer` and `tb_layer_chan` both instantiate
`layer_chan` directly and both accept a parameter override. That difference,
not this section's 132, is what §10's perf band should be re-anchored on.

---

## 5. The width tables

### 5.1 KV — wall 9's lockstep, all six sites

| site | before | after |
|---|---|---|
| RTL field | a 2-bit ARG field latched into a 2-bit register, then narrowed by a 1-bit datapath slice | `rtl/layer_chan.sv:701` declares it `[KHB-1:0]` and it is **used whole**; the narrowing slice RETIRED |
| KV banking | 3 banks, a hand-split in-bank address with the slot's MSB on top | **8 banks**, `rtl/layer_chan.sv:704-708`: the linear address cut at bit 12 |
| `tcnt_bank` | `[6][2]` | **`[8][4]`** (`rtl/layer_chan.sv:367`) |
| KVAP write | `{kvhead_hw, rnd, tcnt[…][8:0]}` | `{kvhead_r, rnd, tcnt[…][8:0]}` |
| host CSR | TCNT (0x20) holds two counters | TCNT (0x20) kvheads 0/1 **+ new TCNT2 (0x60)** kvheads 2/3 (write `rtl/layer_chan.sv:933`, read `rtl/layer_chan.sv:989`); host mirror `sw/hwmap.py:182` |
| emitter twin | `KVH_HW_MAX = 1`, refuses kvh ≥ 2 | `KVH_HW_MAX = _KVH - 1 = 3` (`ref/gen_layer_script.py`), refusal message rewritten to name the banks that now exist |
| reference model | `[8][4]` since Task 3 | unchanged — the RTL caught up to it |

**Why TCNT2 rather than aliasing.** Four 10-bit counters do not fit one
32-bit word. Track P's experiment aliased them (`kh % 2`); this build does
not, because an aliased reset is exactly the silent divergence wall 9 is
about. The script format is unchanged: `ref/gen_layer_script.py`'s `Treset()`
still emits one `T 0` record and `tb/tb_layer_chan.sv` performs **two** CSR
writes on it.

**Mechanized, not asserted:** `evidence/qwen9b/g3/isa_bits.py` computes
`kvh_top = min(KVH_MAX, 2**ARG0_KVH_BITS - 1, KVH_HW_MAX)`, which was 1 at
G3.1 and is **3** now — so ARG0[1] is exercised end to end for the first
time. `246_isa_bits.log`: `ISA_BITS: PASS`.

### 5.2 NH, `dn_head`, GATE

| site | before | after |
|---|---|---|
| `gate_unit` `NH` | 16, **instantiated with no override**, so the parameter default was load-bearing | 32 at `rtl/gate_unit.sv:17`, and `layer_chan` now passes `.NH(LNH)` explicitly (`rtl/layer_chan.sv:491`) |
| `gate_unit` `w_addr` | 4 bits | `rtl/gate_unit.sv:34`, `HB` bits where `HB` is `$clog2` of `NH`; the head counter `h` widened by one bit so `h + 1 == NH` cannot wrap by luck at 32 |
| `dn_head` | `logic [4:0]` with `dn_head_hw = dn_head[3:0]` | `logic [HB-1:0]`, **used whole**; `dn_head_hw` RETIRED |
| GATE load counts | `13'd16` / `13'd32` / `13'd16` | `13'(LNH)` / `13'(2*LNH)` / `13'(LNH)` |
| GATE store bound | `gi[4]` select, `gi == 6'd31` | `gi[HB]` select, `gi == (GIW+1)'(2*LNH - 1)` — **64 words** |
| ARG field decode | `arg0[4:0]` / `arg0[1:0]` | **unchanged, deliberately literal** — the ISA field width is what `isa_bits.py` parses out of this file, and at this geometry `HB = 5` / `KHB = 2` so field and datapath are the same width; a mismatch is a lint WIDTHTRUNC, not a silent truncation |

`tb/tb_gate_unit.sv` got the **`NH` parameter** the brief asked for rather
than ten edited literals — including the 4-bit `w_addr` that would have
failed *silently* at 32 heads. Its default stays 16 because the committed
vectors are the 16-head set; the 32-head width is exercised on the real
`gate_unit` through `layer_chan` (§7's `+dnbank` GATE case).

### 5.3 CONV, and the retired wrap escape

| site | before | after |
|---|---|---|
| conv banks | `18 × 6144` | **`N_DN × CVD` = 24 × 8192** (`rtl/layer_chan.sv:757-758`) |
| bank address regs | 13 bits | **13 bits, unchanged** — 8192 *is* 13 bits of address; what moved is the depth behind them |
| `cvi` / `cvj` / `wi` | already 14 b (Task 7) | unchanged |
| CONVW wrap escape | **Task 7 already removed the 13-bit form.** At 13 bits `wi + 1` wrapped at `wi = 8191`, so a field value of 0 *accidentally* encoded 8192. Widening `wi` and the field to 14 bits at Task 7 removed that wrap | G3.4 finishes it: `nch == 0` means **zero** and is **REFUSED** on both sides — the emitter's 1-or-more assert in `ref/gen_layer_script.py`'s `_conv_fields`, which Task 7 had already put in place, and, new here, the **hardware** envelope (`rtl/layer_chan.sv:1131`) |

So the brief's *"retire the CONVW wrap escape … with an emitter assert in its
place"* was **half-done by Task 7** (the width move and the emitter assert)
and is finished here by the hardware refusal. Recorded as asked rather than
re-done.

### 5.4 EMBLOG2 (S8)

| site | before | after |
|---|---|---|
| `rtl/seq_unit.sv` | `EMBLOG2_RST = 5'd11` | **`5'd13`**; `EMBLOG2_MIN/MAX = 8/13` unchanged, the CSR **stays runtime** |
| `sw/hwmap.py` | `SEQ_EMBLOG2_RST = 11` | **13**, and `EMB_ROW_BYTES_DEFAULT = 1 << SEQ_EMBLOG2_RST` moves with it, 2048 → **8192** |
| `tb/scripts/gen_seq_unit_vectors.py` | `EMB_ROW_LOG2 = 11` | **13**, and the five EMB tables are now sized `EMB_ROW_BYTES // 2` instead of a bare `1024` |
| `tb/tb_seq_unit.sv` | `exp_emblog2 = 11` default | **13** |
| `tb_seq_guard` `+emblog2bad=` | 7 and 14 | **unchanged** — they bracket the legal RANGE [8,13], which did not move; what moved is the reset |

**`EMB_ROW_BYTES_DEFAULT` moving is by design and is the point of the
change.** It is the value for a manifest with **no** `emb_row_bytes` key,
i.e. a pre-R-b artifact; every R-b-and-later artifact carries the key, so the
default is unreachable for anything this build serves. Moving it converts the
census's live bug class — *a site that never learned to program EMBLOG2 from
the artifact silently addresses the wrong row* — into **right by default**.
A pre-R-b artifact replayed here would need its manifest regenerated, which
SEQ_ISA v2.0 requires of it anyway.

`tb/tb_layer_chan.sv`'s `EMB_N_MAX` **is no longer a literal at all**
(fix round 1, finding I2). It was the bare `4096`, exactly the 9B ceiling,
fitting with **zero margin — by luck, not by construction**. It is DERIVED
now from the ceiling the hardware can name: `TB_EMBLOG2_MAX = 13` mirrors
`rtl/seq_unit.sv`'s `EMBLOG2_MAX` and `EMB_N_MAX = (1 << TB_EMBLOG2_MAX)/2`.
An **elaboration assert** requires `2 * EMB_N_MAX == (1 << TB_EMBLOG2_MAX)`,
which is what turns the coincidence into a contract: it fires if anyone
re-literalises `EMB_N_MAX` or moves the mirror without the buffer. The two
runtime bounds that were already there — `+embn=` rejected outside
`[1, EMB_N_MAX]`, and an `M` record whose `n` disagrees with the programmed
row being fatal — are unchanged.

---

## 6. S9 — the synthesizable envelope

Every one of these was `` `ifndef SYNTHESIS `` before, i.e. it protected the
simulator and nothing on silicon. **U4 is what makes the hard check cheap:
with one geometry there is exactly one legal envelope, so a comparator cannot
false-fire on a legacy config.** Cost: a handful of comparators read only at
`cmd_go`, off the datapath (`rtl/layer_chan.sv:1131`, refusal at `rtl/layer_chan.sv:1216`).

Reporting uses the **existing** `err_op`/STATUS mechanism unchanged: the
command is refused before any unit starts or any bank address forms,
`cmd_cnt` still advances so a polling host is not hung, `STATUS[1]` reads
`err_op`, and `seq_unit` halts the program on it with `err_code 0x10`.
**`err_op`'s lifetime was not changed** — it is latched until the next
command dispatch, which is what `seq_unit`'s contract and every TB in the set
are written against. That is a deliberate narrowing of "sticky"; see §10.

| check | where | proven to fire |
|---|---|---|
| VN `nlog2 > 12` | `layer_chan`, VN dispatch | ✅ `+envtest` |
| VNW `len > 4096` | `layer_chan` | ✅ |
| VNW `len == 0` (0 means 0) | `layer_chan` | ✅ |
| CONV `first + nch > 8192` | `layer_chan` | ✅ |
| CONV `nch == 0` | `layer_chan` | ✅ (via CONVW; CONV `nch == 0` is a benign no-op and is refused for symmetry) |
| CONVW `first + nch > 8192` | `layer_chan` | ✅ |
| CONVW `nch == 0` — the retired escape | `layer_chan` | ✅ |
| `dn_slot > 23` on DNST/DNZ/CONV/CONVW | `layer_chan` | ✅ |
| out-of-window `s_axib` burst → **SLVERR** | `layer_axib_shim` (`rtl/layer_chan.sv:1954`, `:1976`) | structural: `aw_win_bad`/`ar_win_bad` feed the SAME `wblk`/`werr`/`rblk` path a busy-engine burst takes, which `tb_layershim_c` T3 exercises (256 SLVERR beats). The two sim-only `$fatal`s that used to abort on this are **retired**, because a condition the hardware now answers correctly must be observable in sim, not fatal in it |
| MVGO SHAPE `ng` outside `1..96` | `rtl/seq_unit.sv`'s validator, `E_ENV = 0x0D`, at the MVGO dispatch (fix round 1, finding I1) | ✅ `seq_e_env0` / `seq_e_env97`, each with a **legal** MVGO ahead of it in the same stream |

`kv_slot` needs no check: `LAYER` carries three bits and `N_KV = 8`, so every
value it can hold is legal. DNST/DNZ `head` needs none either: the field is
five bits and all 32 heads now exist.

### 6.1 The `cfg_ng` envelope — TWO LINES OF DEFENCE, both live

`cfg_ng` is decoded in `rtl/matvec_engine.sv`, whose own `1..MAX_NG` guard
is still `` `ifndef SYNTHESIS `` and whose file G3.3 closed. The check
therefore lands where the spec's own words put it — at the **MVGO
dispatch**, because MVGO's `imm32` **is** the SHAPE word:

| line | where | covers |
|---|---|---|
| **EMIT** | `sw/hwmap.shape_word` refuses `ng` outside `1..MAX_NG` per layout (G3.3's folded minor) | every host that packs a SHAPE word or writes the CSR directly |
| **RUN** | `rtl/seq_unit.sv`'s validator refuses the MVGO record with `E_ENV = 0x0D` before the doorbell, on the existing `err_op`/STATUS mechanism | a stream the sequencer is HANDED — the case no host packer sees |

`ref/seq_format.validate` carries the **identical** clause: a hardware
validator stricter than its golden is the encoder/decoder mismatch §7.6's
mechanization exists to prevent. `evidence/qwen9b/g3/isa_bits.py` reads
`MVGO_MAX_NG` out of **both** sources and requires them equal, then trips
the reference validator RED at `ng` 0 and 97 and GREEN at 1 and 96
(`MVGO ng envelope: 1..96, RTL and reference agree`).

Landing it required one lockstep edit, and it is a defect the check found:
the **seven hand-written MVGO SHAPE immediates** in
`tb/scripts/gen_seq_unit_vectors.py` were **isa=1** words, whose `ng` sits
in bits `[5:0]`; under the v2.0 layout this RTL decodes they all read
`ng = 0`. They are packed by the one packer now, at the (nrows, sh, ng)
triples the old constants meant — so the streams are the same streams with
a SHAPE word that is true.

**Both halves.** The fire-in-sim half is `+envtest`, §7. The
**none-fires-on-the-9B-stream** half is **Task 11's**, on the real stream —
it is not established here and is listed in §10.

---

## 7. The testbenches

### 7.1 What each TB replays, and at which `FABLE5_MODEL` / `RS_F`

| target | DUT | geometry | `RS_F` its goldens carry | seeds |
|---|---|---|---|---|
| `tb_dn_step` | `dn_step` RLAT 2 | committed `tb/vectors/s*` (`dn_*`) — **RS_F-independent** | n/a | 4 |
| `tb_dn_step_pipe` | `dn_step` RLAT 6, `P2_WAIT 1` | same goldens | n/a | 4 |
| `tb_dn_step_pipe_ii` | `dn_step` RLAT 6, `P2_WAIT 0` | same goldens | n/a | 4 |
| `tb_gate_unit` | `gate_unit` NH=16 | committed `gate_*` vectors — RS_F-independent | n/a | 4 |
| `tb_conv4_silu` | `conv4_silu` | committed `conv_*` vectors, **REGENERATED at `FABLE5_RS_F=7`** | **7** | 4 |
| `tb_layer_dnbank` | real `layer_chan` | directed, no golden file | n/a | 4 |
| `tb_layer_env` | real `layer_chan` | directed, no golden file | n/a | 4 |
| `tb_layer_chan` | real `layer_chan` | `layerv2_s*` generated at `FABLE5_MODEL=9b` | **7** | 4 |
| `tb_seq_layer` | real `layer_chan` | `seqlayer_s*` generated at `FABLE5_MODEL=9b` | **7** | 4 |
| `tb_layershim_c` | real `layer_chan` | directed burst gate | n/a | 4 |
| `tb_seq` / `tb_seq_guard` | `seq_unit` + movers | `seq_*` vectors at `EMB_ROW_LOG2 = 13` | n/a | per target |
| `lint_seq`, `lint_seq_unit` | — | — | — | — |

**Deferred to Task 11, and why:** `tb_token` and `tb_chain` are in the
brief's Test list but `tb/Makefile` records that **G3.1 retired them** as
replayable SEQ_ISA v1.7 streams; re-basing them needs the real 9B checkpoint
and belongs to the task that regenerates the 9B artifact chain. They were
**not** re-based here and **not** run.

### 7.2 The `RS_F = 7` RED → GREEN on the one RTL literal A2.1 moves

`rtl/conv4_silu.sv:54`'s baked shift is RS_F + CW_F − 12 = 7 + 13 − 12 = **8**;
it was 9. The covering TB was re-run at the new shift, **not assumed inert**:

* the four `conv_win.hex` / `conv_y.hex` vector pairs were regenerated at
  `FABLE5_RS_F=7`;
* **RED** — the same TB against the **pre-G3.4 `rtl/conv4_silu.sv` (shift 9)**
  and those goldens fails on all four seeds, e.g.
  `FAIL [0]: got 00ac want 0165`, rc 134 ×4;
* **GREEN** — shift 8: `TB_CONV4_SILU PASS: 64 channels bit-exact` ×4
  (`238_tb_conv4_silu_rsf7_green.log`).

**A whole-set regeneration at `FABLE5_RS_F=7` moves EXACTLY those eight
files** and nothing else — verified by regenerating the whole set at both
values into a scratch tree and comparing (the RS_F=8 regeneration is
byte-identical to the committed set; the RS_F=7 one differs only in
`conv_win`/`conv_y`).

That verification required closing **Task 8's declared residual**, which A2.1
had just made live: `tb/tb_vecnorm.sv` drives `cfg_inf`/`cfg_outf` as the
literal `4'd8` on every rmsnorm case, while the vectors were generated at
`LF.RS_F` — so at RS_F = 7 the rmsnorm vectors would have stopped matching
their own TB. It is closed **at the root, in the generators**: `RMS_VEC_F = 8`
in `ref/gen_layer_vectors.py` and `tb/scripts/gen_seq_c_vectors.py` makes the
rmsnorm vector fraction a stated TB contract instead of a silent coupling to
a knob. **It is byte-identical at the default RS_F**, which is why the
RS_F=8 regeneration reproduced the committed set exactly.

### 7.3 Step 1's regression: the shipped `tb_dn_step` cases are bit-identical

Before any new case was added, the four committed `tb_dn_step` vector cases
were replayed on the reworked FSM at `RLAT = 2`:
`TB_DN_STEP PASS: 128 outputs + 16384 state entries bit-exact` ×4
(`230_tb_dn_step_regression_rlat2.log`). **At `int16` the container law is
exactly `clip16`, which the shipped RTL already does, so the state VALUES do
not change and that is the regression that matters.** They are equally
bit-exact at `RLAT = 6` under both `P2_WAIT` settings (§4.3).

`tb/tb_dn_step.sv`'s `16384 = 128 × 128` is one head's DN state and survives
LNH = 32 — it is per-head. Untouched, as the brief asks.

### 7.4 The directed banking cases — RED → GREEN

**Where they live, and why not in `tb_dn_step`.** The brief asks for directed
`dn_slot` 18…23 / `head` 16…31 cases in `tb_dn_step`. `dn_step`'s ports carry
**no slot and no head** — the banking is entirely in `layer_chan`, and the
TB's memory model is a flat 128-row array. Putting slot/head cases there
would mean re-implementing the DUT's addressing inside the TB, which proves
nothing. They are therefore directed modes on the **real `layer_chan`**
(`tb/tb_layer_chan.sv +dnbank`), which is where the banking is. Recorded as a
deviation, §9.

They need **no reference model**: every case asserts that two things which
must be INDEPENDENT produce identical results from identical inputs, plus —
the half that catches a store that is not there at all — that a second step
from the same inputs **advances**.

**GREEN** (`237_tb_layer_dnbank_green.log`, and again in the committed-tree
suite):

```
  OK DN state (slot 0, head 16) independent: 512 words identical
  OK DN state (slot 0, head 31) independent: 512 words identical
  OK DN state (slot 17, head 15) independent: 512 words identical
  OK DN state (slot 18, head 0) independent: 512 words identical
  OK DN state (slot 23, head 31) independent: 512 words identical
  OK DN state (slot 23, head 16) independent: 512 words identical
  OK KV cache (slot 0, kvh 1|2|3) independent: 512 words identical
  OK KV cache (slot 6, kvh 0|1|2|3) independent: 512 words identical
  OK KV cache (slot 7, kvh 0|1|2|3) independent: 512 words identical
  OK conv slot 0  ch 8188..8191 matches slot 0 ch 0..3: 4 words identical
  OK conv slot 23 ch 8188..8191 matches slot 0 ch 0..3: 4 words identical
  OK GATE wrote exactly 64 words (2 x LNH = 32 heads)
TB_LAYER_DNBANK PASS: DN 24x32, KV 8x4, conv 24x8192
```

**RED** — `evidence/qwen9b/g3/g34_red_control.sh`, log
`243_red_control_pre_g34.log`, the SAME testbench against the pre-G3.4 RTL:

* **RED-a**, the committed `8138d66` tree unmodified: `+dnbank` dies in the
  pre-G3.4 `` `ifndef SYNTHESIS `` guard at `rtl/layer_chan.sv:1531` (DNST head
  ≥ 16), rc 134; `+envtest` dies inside **`vecnorm_unit`'s own** sim-only
  guard, `vecnorm_unit: cfg_nlog2 13 unsupported (max 12, N=4096)`, rc 134 —
  which is precisely §6's point: today that is a simulator abort and on
  silicon it is nothing at all.
* **RED-b**, the same tree with that sim-only block stripped, so the
  **aliasing itself** shows rather than the refusal:

```
  FAIL DN state (slot 0, head 16) independent: 226 of 512 words differ
  FAIL DN store (slot 18, head 0)  did not ADVANCE: step 2 == step 1
  FAIL DN store (slot 23, head 31) did not ADVANCE: step 2 == step 1
  FAIL DN store (slot 23, head 16) did not ADVANCE: step 2 == step 1
  FAIL TCNT  slot 0: kvh0=2 kvh1=2, want 1/1
  FAIL TCNT2 slot 0: kvh2=222 kvh3=685, want 1/1
  FAIL KV cache (slot 6, kvh 0..3) independent: 254 of 512 words differ
```

Read that as the map of what was wrong: head 16 aliased head 0; dn_slots
18/23 addressed banks that did not exist so their writes went nowhere and a
second step re-read zeros; kvheads 2/3 shared kvheads 0/1's append counters
(hence 2 instead of 1) and TCNT2 did not exist at all (hence garbage);
kv_slots 6/7 read a bank that was not there.

### 7.5 The envelope, fired both ways in sim

`tb_layer_env` (`235_tb_layer_env_green.log`), 4 seeds, every line an
observed refusal:

```
  ENV REFUSED (err_op=1) as required: VN nlog2 13 > 12
  ENV REFUSED (err_op=1) as required: VNW len 4097 > 4096
  ENV REFUSED (err_op=1) as required: VNW len 0 refused
  ENV REFUSED (err_op=1) as required: CONV 8190+4 > 8192
  ENV REFUSED (err_op=1) as required: CONVW 8190+4 > 8192
  ENV REFUSED (err_op=1) as required: CONVW nch 0 refused (the retired wrap escape)
  ENV REFUSED (err_op=1) as required: DNZ at dn_slot 24 (no bank)
  ENV REFUSED (err_op=1) as required: DNST at dn_slot 24 (no bank)
  ENV REFUSED (err_op=1) as required: CONV at dn_slot 24 (no bank)
TB_LAYER_ENV PASS: every envelope check fired
```

Each refusal is paired with the **legal** neighbour (nlog2 12, len 4096,
`8188+4`, dn_slot 23 head 31) which must NOT be refused, and the run ends
with a real command that still executes and a scratch readback proving a
refused command touched nothing.

### 7.6 Suite results

Working-tree run (the committed-tree re-run is §13):

| target | result |
|---|---|
| `tb_dn_step` | `TB_DN_STEP PASS: 128 outputs + 16384 state entries bit-exact` ×4 |
| `tb_dn_step_pipe` | same, ×4, at the shipped latency |
| `tb_dn_step_pipe_ii` | same, ×4 (option (ii), not shipped) |
| `tb_gate_unit` | `TB_GATE_UNIT PASS: 16 heads beta+decay bit-exact` ×4 |
| `tb_conv4_silu` | `TB_CONV4_SILU PASS: 64 channels bit-exact` ×4 |
| `tb_layer_dnbank` | `TB_LAYER_DNBANK PASS: DN 24x32, KV 8x4, conv 24x8192` ×4 |
| `tb_layer_env` | `TB_LAYER_ENV PASS: every envelope check fired` ×4 |
| **`tb_layer_chan`** | **`TB_LAYER_CHAN PASS: 1438 cmds, 261357 checks bit-exact` ×4**, at `FABLE5_MODEL=9b` and `FABLE5_RS_F=7` |
| **`tb_seq_layer`** | **`TB_LAYER_CHAN PASS: 19 cmds, 5280 checks bit-exact` ×4**, same geometry |
| `tb_layershim_c` | `TB_LAYERSHIM_C PASS` ×4 (not in the brief's list; run because G3.4 edits the shim) |
| `tb_seq` | `SEQ PASS` on every vector |
| `tb_seq_guard` | PASS, `OK: illegal EMBLOG2 write is loud in simulation` |
| `lint_seq`, `lint_seq_unit` | clean, `-Wall`, 5.020 |

**`tb_layer_chan` is the integration proof this gate rests on**: the whole
9B layer body — VN at nlog2 12, CONV over 8192 channels, GATE at 32 heads,
DNST at 32 heads through the 24-bank `DN_PIPE = 2` array, KVAP/ATTN at 4
kvheads, ALU at len 12288 — replayed against `ref/layer_fixed.py` and
compared **bit-exactly**, 261,357 checks per seed, on the shipping
configuration. That is the same harness and the same reference the 0.8B/2B
builds were gated on; only the geometry moved.

**Two generators had to be fixed to get here, and both were broken BEFORE
this task** — see §9 items 6 and 7.

---

## 8. Citation drift and the checker

`evidence/qwen9b/o3/o3_cite_drift.py --base 8138d66 --doc-base 8138d66`
over 21 edited files:

| pass | result | log |
|---|---|---|
| `--check` (RED) | **FAIL: 432 drifted, 63 unresolved, 0 missing, 14 half-mapped** | `240_cite_drift_check.log` |
| `--fix` | **432 citations in 52 documents** | `241_cite_drift_fix.log` |
| `--verify` | **FAIL, 97: 32 class A + 65 class-B UNRESOLVED** — the row said "class A clean"; corrected 2026-09-02, §16.8 | `242_cite_drift_verify.log` |

**Class A** (the citation moved) was renumbered mechanically. **Class B** (the
cited source was rewritten or deleted) was given §7.6's precedent treatment —
a dated `PRE-G3.4 ROWS, KEPT AS THE RECORD` box in each affected section plus
`<!--cites:noquote-->` on the rows whose quotation no longer exists — and is
tabulated in §11.1. The boxes were added **before** `--fix`, and this
document's own citations are written in the **final** tree's coordinates,
after the last `--fix`; `--fix` was never run over it.

**`--fix` also renumbered one comment inside
`synth/exp_uram/rtl/layer_chan.sv`, and that was REVERTED**: the brief
forbids editing the experiment file, Task 13 re-runs it, and the renumber was
in any case a half-fix (it moved `rtl/dn_step.sv:198` and left `rtl/dn_step.sv:251`). The stale citation
there belongs to Task 13.

---

## 9. Deviations, declared

1. **The directed slot/head cases are in `tb_layer_chan`, not `tb_dn_step`**
   — `dn_step` has no slot or head port. §7.4.
2. **`tb_token` / `tb_chain` were not run and not re-based** — G3.1 retired
   them; Task 11 owns them. §7.1.
3. **A new CSR, TCNT2 at layer 0x60**, rather than aliasing four counters
   onto two fields. §5.1.
4. **A `dn_step` parameter pair (`RLAT`, `P2_WAIT`) and a `DN_PIPE`
   parameter on `layer_chan`** — required by the Step 1′ ruling, which asks
   for the cycle cost MEASURED at `DN_PIPE` 0 and 2 rather than modelled.
   The shipping defaults are 2 / 6 / 1.
5. **Files touched outside the brief's list**, each for a reason the change
   itself created:
   * `sw/seq_run.py` — its board-free selftest pinned the EMBLOG2 reset;
     re-pinned (§12 names the moved check).
   * `ref/seq_chat.py`, `ref/layer_fixed.py` — docstring/comment blocks that
     stated the old default and the superseded A1.8 disposition (A2.4).
   * `ref/gen_layer_vectors.py`, `tb/scripts/gen_seq_c_vectors.py` —
     `RMS_VEC_F`, closing Task 8's residual at the root (§7.2).
   * `ref/gen_layer_script.py` `main()` — value-gated `rs_f=` on the
     manifest, without which no TB script can be generated at
     `FABLE5_RS_F=7` (A2.5's trap, hit for real).
   * `tb/vectors/s{1..4}/conv_{win,y}.hex` — the eight regenerated goldens.
   * `docs/ARCHITECTURE.md`, `docs/SEQ_ISA.md` — the comment sweep, §11.
   * `evidence/qwen_next/spec_cites.py` — `G3_4_LAYER.md` out of `PENDING`.
   * `evidence/qwen9b/g3/g34_red_control.sh` — new, the RED control.
   * `tb/scripts/gen_seq_layer_script.py` — see item 8.
6. **`tb_seq` and `tb_seq_guard` were ALREADY BROKEN at `8138d66`.**
   `tb/scripts/gen_seq_unit_vectors.py`'s `build_repack` called
   `sw/hwmap.py`'s `shape_word` with `w8=True`, which **G3.3 made an
   assertion error** when it stripped the W8 engine mode — so the entire
   `seq_unit` vector set could not be generated and neither target could
   run. Verified on a clean extract of the base commit, not inferred.
   Fixed here by dropping the argument: that vector exercises the REPACK
   ADDRESS BOOKKEEPING and the SHAPE word is an opaque payload to its DUT
   (nothing in `seq_unit` or `seq_movers` decodes the mode). Fixed rather
   than deferred because **`tb_seq_guard` is what proves the EMBLOG2 move**,
   and a gate cannot lean on a target that cannot start.
7. **A2.5's trap was hit for real, and the fix is value-gated.**
   `ref/gen_layer_script.py`'s `main()` called `dump_weights(prefix)` with
   no `rs_f=`, so at `FABLE5_RS_F=7` it hit the manifest refusal and **no TB
   script could be generated at all**. It now passes `rs_f=` **only when the
   value differs from `RS_F_MANIFEST_DEFAULT`**, so the RS_F = 8 emission —
   which `evidence/qwen2b/rc/t4_bytes_unmoved.sh` calls — is byte-identical,
   and A2.5's operational rule (do not export `FABLE5_RS_F` across that
   script or `ref/scripts/regen_gate.sh`) still stands.
8. **`tb/scripts/gen_seq_layer_script.py`'s hi-half GATE tiles re-spaced.**
   That file carried a **deliberate assert naming G3.4**: *"the hi-half GATE
   tiles are laid out for LNH<=16 … re-space B_HIG/B_HIA/B_HIAC (the 32-head
   geometry is G3.4)"*. Done: GATE dst 2·LNH, src_a LNH, src_A 2·LNH now fit
   at 32 heads, the DNST tiles below moved up 0x80, and the assert was
   **extended** to cover the LOW-half tiles it did not check. The spacing is
   a superset of the LNH = 16 one, so the file still emits at 0.8B/2B.

---

## 10. What is NOT established here

* **Placement, timing, routing, resources — nothing.** No synthesis was run.
  The 928 URAM is **label S**, arithmetic; **Task 12's OOC run measures it**
  (A1.5). The `+0.097 ns` MET is **Track P's**, on the experiment RTL, under
  `AltSpreadLogic_medium`, and it does **not** close the module.
* **The write-control fan-out pblock was never tried and can still
  invalidate the target** (A1.3). No floorplanning was attempted here; that
  is Task 13's CRITICAL experiment.
* **The layer-term cycle cost.** §4.3 measured `dn_step` alone. The DNST
  command and the layer body around it are Task 12's two-run census, §4.6.
* **The none-fires half of S9.** Every envelope check is proven to FIRE on a
  deliberately out-of-envelope command. That **none of them fires on the 9B
  stream** is Task 11's, on the real stream.
* ~~**S9's `cfg_ng` bullet is NOT DONE**~~ — **SUPERSEDED 2026-09-02 by
  fix round 1, finding I1: it is BUILT**, §6.1. The withdrawal that stood
  here is kept below as the record, because every factual claim in it was
  true and they are exactly why the fix needed three files rather than one;
  what was wrong was the conclusion — the answer is to make the vectors and
  the reference say what they mean, not to drop the check.
  *(kept as the record:)*
  as a refusal in `seq_unit`'s ISA validator (a new `E_ENV`) on the MVGO
  SHAPE immediate, because `cfg_ng` is decoded in `rtl/matvec_engine.sv`
  whose own guard is `` `ifndef SYNTHESIS `` and whose file is closed to
  this task. **It was withdrawn on evidence:** it made `tb_seq` fail with
  `err_code 13` on the committed vector set, because every hand-written MVGO
  SHAPE immediate in `tb/scripts/gen_seq_unit_vectors.py` (`0x0001_8008`,
  `0x0000_4004`, `0x0080_8020`, `0x0001_8030`) is an **isa=1** word whose
  `ng` sits in bits [5:0], not [28:22] — an opaque don't-care to `seq_unit`
  and `seq_movers`, neither of which decodes the mode. Three things follow
  and all three are the reason not to force it: the check would validate a
  payload the block does not own; it would make the RTL validator
  **stricter than `ref/seq_format.validate`**, the encoder/decoder mismatch
  G3's mechanization exists to prevent; and satisfying it would mean editing
  the vectors to fit the code. The EMIT side is already guarded —
  `sw/hwmap.shape_word` refuses `ng` outside `1..MAX_NG` per layout (G3.3's
  folded minor). ~~Handed to the task that next opens `rtl/matvec_*.sv`.~~ **`matvec_engine`'s own `$fatal` STAYS sim-only** — that file is closed, and with both lines of defence in place nothing reaches it.
* **A side finding for Task 11:** those MVGO SHAPE immediates in the seq
  vector set are **stale isa=1 constants**. Benign here (nothing in this
  TB's DUT decodes them) but they are not what a v2.0 stream carries.
* **`err_op` is not more sticky than it was.** S9 says "sticky error bits";
  `err_op` is latched until the next command dispatch and `seq_unit` halts on
  it. Widening that lifetime would change a contract every TB in the set is
  written against, so it was left alone deliberately rather than by omission.
* ~~**`ref/seq_format.py`'s layer preamble writes only `CSR_L_TCNT`.**~~
  **FIXED at fix round 1, finding I3** — it is the emitter half of wall 9's
  "all six sites or none", and this gate is what created the asymmetry.
  `SeqEmitter.on_treset` emits **two** CSRWRs now (`CSR_L_TCNT` and the new
  `CSR_L_TCNT2` at layer 0x60) and the disassembler names `L_TCNT2`. Both
  halves are proven: `isa_bits.py` exercises the hook in place
  (`SEQ T reset: 2 CSRWR [('0x20', 0), ('0x60', 0)]`) and `tb_layer_dnbank`
  resets T **from a non-zero state** at three kv_slots and requires all four
  counters to read 0.
* **`tb_vecnorm` cases 6 and 8** replay `rms2048`/`rms4096` vectors; those
  generators are now pinned (§7.2) so they are safe, but `tb_vecnorm` itself
  was not run at this gate.
* **Nothing touched the board.** The 2B is serving from `build_035`.

---

## 11. The comment sweep

Every hit of *9 banks / 3 KV banks / 16 heads / `[6][2]` / 4-bit `dn_head` /
1-bit `kvhead` / 18 × 6144 / EMBLOG2 11 / "shift 9" / int8-as-current*, in
the files this task edited and in `docs/ARCHITECTURE.md` and
`docs/SEQ_ISA.md`, with its disposition.

| file:site | said | disposition |
|---|---|---|
| `rtl/layer_chan.sv` header, layer banking | "18 DeltaNet dn slots 0..17, 6 GQA kv slots 0..5 … dn_slot 18..31 and kv_slot 6..7 are host errors (no RTL guard)" | **REWRITTEN** — 24/8, and the slot check is now a hardware refusal |
| `rtl/layer_chan.sv` header, CONV | "the conv BANKS are still 6144 deep … EXECUTABLE is G3.4" | **REWRITTEN** — 24 × 8192, executable |
| `rtl/layer_chan.sv` header, ATTN | "kvhead_hw = kvhead_r[0] and the sim envelope guard refuses kvh >= 2 until G3.4" | **REWRITTEN** |
| `rtl/layer_chan.sv` header, TCNT | two counters | **AMENDED** — TCNT2 named |
| `rtl/layer_chan.sv` DN block | "9 URAM banks, each holds two dn slots via an in-bank MSB" | **REWRITTEN**, with the old map named as what was replaced |
| `rtl/layer_chan.sv` KV block | "3 URAM banks … 2 kvheads x 2 banks" | **REWRITTEN** |
| `rtl/layer_chan.sv` conv block | "18 BRAM banks", "18:1 mux" ×3 | **REWRITTEN** — 24 banks, `N_DN:1` |
| `rtl/layer_chan.sv` envelope block | the whole G3.1 `$fatal` list | **DELETED**, replaced by a dated note saying what each guard became |
| `rtl/dn_step.sv` header | "2-cycle read latency" | **AMENDED** — the RLAT header block |
| `rtl/gate_unit.sv` header | "(16 heads, serial)" | **REWRITTEN** — NH heads, NH = 32 at 9B |
| `rtl/seq_unit.sv` | "reset 11 (2048 B)", "2048 B row until told else" | **REWRITTEN** — 13 / 8192 B |
| `rtl/conv4_silu.sv` | "RS_F + CW_F - 12 = 9" | **REWRITTEN** — = 8, with A2.1 named |
| `sw/hwmap.py` S_EMBLOG2 / `EMB_ROW_BYTES_DEFAULT` | "Reset 11 = 2048 B = H 1024", "2048 B = H 1024" | **REWRITTEN**, with why the default moving is by design |
| `sw/seq_run.py` docstring + 3 selftest checks | "the reset value (2048 B, H 1024)", "defaults to 2048 B rows", "goes back to the 2048 B row", "still runs the 2048 B geometry" | **REWRITTEN** to derive from `SEQ_EMBLOG2_RST`; one check ADDED (§12) |
| `ref/seq_chat.py:1031` | "still answers 2048" | **REWRITTEN** |
| `ref/layer_fixed.py` RS_F block | "A1.8 leaves that literal ALONE — RS_F stays 8, so Task 10 does not touch rtl/conv4_silu.sv" | **REWRITTEN** — A2.4 discharged, and A2.5's env-knob trap restated |
| `ref/gen_layer_script.py` KVH block | "the BANKS are still two deep", "Widening the DATAPATH to NKV=4 is Task 10" | **REWRITTEN** |
| `ref/gen_layer_script.py` CONV block | "making 8192 channels EXECUTABLE in the conv bank is Task 10" | **REWRITTEN**, and the retired escape recorded |
| `tb/tb_gate_unit.sv` | "(16 heads)" and ten `16` literals | **PARAMETERIZED** |
| `tb/scripts/gen_seq_unit_vectors.py` | "11 is the RESET value = today's 2048 B row" | **REWRITTEN** |
| `tb/tb_seq_unit.sv` | "11 (2048 B) is the reset value" | **REWRITTEN** |
| `docs/ARCHITECTURE.md` banking table + `gate_unit` row | 9 / 3 / 18 banks, "for 16 heads" | **REWRITTEN**, with a dated `PRE-G3.4 BANKING, KEPT AS THE RECORD` box carrying what build_034/035 hold |
| `docs/ARCHITECTURE.md:453` "DeltaNet layers 16 key heads … CONV_DIM = 6144" | — | **LEFT** — a 0.8B **model-facts** row, not an RTL row |
| `docs/SEQ_ISA.md` B14.5 CONV/head/kvhead bullets | "banks are still 6144 deep", "still built for 16 heads", "still TWO heads deep" | **REWRITTEN** |
| `docs/SEQ_ISA.md` EMBLOG2 ×5 (`:50`, the two CSR maps, the EMB address note, B13's RESET bullet, the DEADC0DE note) | "reset 11 (2048 B)", "fixed 2048 B row" | **REWRITTEN**, with v1.7's sentence kept as the record |
| `synth/exp_uram/rtl/layer_chan.sv` banner + int8 knobs | the whole experiment file | **UNTOUCHED by design** (the one `--fix` renumber reverted) |

### 11.1 The post-G3.4 landmark for the class-B citations

Rows marked `<!--cites:noquote-->` under the new `PRE-G3.4 ROWS` boxes in
§4.1, §4.6, §5.3 and §5.4 of the spec, in `docs/SEQ_ISA.md` B14.5 and in
`docs/ARCHITECTURE.md`'s banking table quote source this gate rewrote. Where
each went:

| the pre-G3.4 source a document quotes | where the equivalent is now |
|---|---|
| the `[6][2]` `tcnt_bank` declaration | `rtl/layer_chan.sv:466`, `[N_KV][NKVH]` = `[8][4]` |
| the `layer_dn` / `layer_kv` declarations | `rtl/layer_chan.sv:368-369`, now `[LDB-1:0]` / `[KVB-1:0]` |
| the 9-bank DN comment and its 9-iteration generate | `rtl/layer_chan.sv:527-537` (comment) and `rtl/layer_chan.sv:608-650` (the `g_grp` generate) |
| the hand-split in-bank read address and its bank select | `rtl/layer_chan.sv:583-590` |
| the 4-bit `dn_head_hw` datapath slice | **GONE** — `dn_head` is used whole, `rtl/layer_chan.sv:546` |
| the 1-bit `kvhead_hw` datapath slice | **GONE** — `kvhead_r` is used whole, `rtl/layer_chan.sv:701` |
| the 3-bank KV comment and its 3-iteration generate | `rtl/layer_chan.sv:686-714` |
| the 18-iteration conv generate and its 6144-deep arrays | `rtl/layer_chan.sv:757-758`, `N_DN` / `CVD` |
| the `gate_unit` instantiation with no `NH` override | `rtl/layer_chan.sv:491`, `.NH(LNH)` |
| `gate_unit`'s 16-head default and 4-bit `w_addr` | `rtl/gate_unit.sv:17` / `rtl/gate_unit.sv:34` |
| the G3.1 `` `ifndef SYNTHESIS `` envelope block | **GONE** — the checks are `rtl/layer_chan.sv:1131` and the refusal `rtl/layer_chan.sv:1216` |
| the loop-tail read-address issue | `rtl/dn_step.sv:255` (`P1_RD`) and `rtl/dn_step.sv:290` (`P2_RD`) |
| the `EMBLOG2_RST` reset value 11 | `rtl/seq_unit.sv:346`, now 13 |
| the generator's `EMB_ROW_LOG2` of 11 | `tb/scripts/gen_seq_unit_vectors.py:91`, now 13 |
| `conv4_silu`'s baked shift of 9 | `rtl/conv4_silu.sv:54`, now 8 |
| the ten bare `16` literals in `tb/tb_gate_unit.sv` | `tb/tb_gate_unit.sv:12`, one `NH` parameter |

---

## 12. Host regression floor, and the counts that moved

`evidence/qwen2b/rd/rd_boardfree.sh`, snoke (`244_boardfree.log`):

```
  seq_run selftest: 2759 passed, 0 failed
  backend API check: PASS
  serve selftest:     85 passed, 0 failed
  chat_seq selftest: 356 passed, 0 failed
BOARDFREE_PASS
```

**ONE count moved: `seq_run` 2758 → 2759, and it moved because a check was
ADDED, not because one changed answer.** The moved checks, named:

| check | before | after |
|---|---|---|
| "an old manifest defaults to **2048 B rows**" | text named the literal; the comparison was already against `EMB_ROW_BYTES_DEFAULT` | **renamed** to "defaults to the CSR reset row size" — same comparison, no longer a lie |
| "EMBLOG2 goes back to the **2048 B** row" | wrote 2048, expected `SEQ_EMBLOG2_RST` — which was 11, so it passed by coincidence of the two being equal | **re-pointed**: writes `1 << SEQ_EMBLOG2_RST` and expects `SEQ_EMBLOG2_RST`, i.e. it tests what it says |
| — | — | **ADDED**: "EMBLOG2 still takes the 2048 B row (the CSR stays RUNTIME)" — expects 11 for a 2048 B artifact, which is the half the re-pointing above would otherwise have stopped covering. **This is the +1.** |
| "a pre-R-b bitstream still runs the **2048 B** geometry" | passed 2048 to a device with no EMBLOG2 CSR; at reset 13 that raises instead of logging | **re-pointed** to `1 << SEQ_EMBLOG2_RST`, which is the case the branch is for |

`serve` 85 and `chat_seq` 356 are **unmoved** — 2759/85/356 against G3.3's
2758/85/356.

Other host gates:

| gate | result | log |
|---|---|---|
| `sw/hwmap.py --selftest` | PASS, every pinned SHAPE word unmoved | `245_hwmap_selftest.log` |
| `evidence/qwen9b/g3/isa_bits.py` at `FABLE5_MODEL=9b` | `ISA_BITS: PASS`, `kvhead 2 b >= 2**ARG0_KVH_BITS-1 = 3`, `dn_head 5 b >= 31` | `246_isa_bits.log` |
| `spec_cites.py` over the gate doc, the spec, the plan, `docs/SEQ_ISA.md`, `docs/ARCHITECTURE.md` and the three earlier G3 gate docs | **FAIL 0** on all except `docs/ARCHITECTURE.md`, whose 39 are **pre-existing and unmoved** (verified against the same run on a `8138d66` extract) | `247_spec_cites.log` |
| `spec_cites.py --selftest` on the plan | 6/6 CAUGHT | `248_spec_cites_selftest.log` |
| `evidence/qwen9b/g2/spec_cites_selftest_regression.sh` | **SPEC_CITES_REGRESSION PASS**, with ONE pin re-pinned | `250_…_r2.log` |

**The re-pinned count, named:** `evidence/qwen9b/g1/RUNG_INT8_STATE.md`
2 → **1**. One of its two pre-existing failures was a QUOTE whose citation
had **already** drifted before this campaign (`bbda679:ref/layer_fixed.py:2526`,
then `bbda679:ref/layer_fixed.py:2540` after the mechanical renumber, while
the quoted line is `bbda679:ref/layer_fixed.py:2555`).
G3.4 edited that file, so it fixed the pointer rather than leave a
known-wrong one behind. What remains is the ORPHAN bare continuation at
`evidence/qwen9b/g1/RUNG_INT8_STATE.md:823`, untouched. The count is LOWER,
not different in kind, and the change is recorded in the regression script's
own comment.
*(Corrected 2026-09-10, pre-ship tool chore fix round 2, re-review I-A: the
three coordinates above are PINNED to `bbda679`, the G3.4 gate commit, because
the sentence is about the G3.4 TREE and a citation left live tracks whatever
tree it is renumbered onto. They read 2526 / 2540 / 2555 at `bbda679` and
still at `b9e0851`, 2566 / 2580 / 2595 at `a4a1f68` (`b1cff80`'s drift pass,
+40) and 2586 / 2600 / 2615 at `bddd092` (this chore's own pass, +20 for the
rider block) — that last triple names no tree the sentence is about. Each
pinned number was read off the gate commit itself, with
`git show bbda679:ref/layer_fixed.py` piped through `sed -n`. At HEAD the same
three source lines are `ref/layer_fixed.py:2586`, `:2600` and `:2615`, which is
where a reader who wants TODAY's file should look, and
`evidence/qwen9b/g1/RUNG_INT8_STATE.md:156` states that HEAD coordinate for the
quoted call.)*
*(Updated 2026-09-10, pre-ship documentation chore fix round: "untouched" is
no longer true. That ORPHAN was repaired by the pre-ship chore — HEAD's
`evidence/qwen9b/g1/RUNG_INT8_STATE.md:823` is a full sha-pinned citation, so
the pointer above still lands on the right line and the right subject, but the
document's FAIL is now 0 and the regression script's pinned expectation for it
was re-pinned 1 → 0 by the pre-ship tool chore. The sentence above stands as
G3.4's record of what it re-pinned.)*

---

## 13. Logs

| # | log | what |
|---|---|---|
| 230 | `230_tb_dn_step_regression_rlat2.log` | Step 1's regression: the shipped cases bit-identical on the reworked FSM |
| 231 | `231_tb_dn_step_pipe_rlat6_optI.log` | option (i), 1930 cyc/head |
| 232 | `232_tb_dn_step_rlat2_cycles.log` | the control, 1798 cyc/head |
| 233 | `233_tb_dn_step_pipe_rlat6_optII.log` | option (ii), 1802 cyc/head |
| 235 | `235_tb_layer_env_green.log` | every envelope check fires |
| 237 | `237_tb_layer_dnbank_green.log` | the banking, GREEN |
| 238 | `238_tb_conv4_silu_rsf7_green.log` | the RS_F = 7 GREEN half |
| 240 | `240_cite_drift_check.log` | the drift RED |
| 241 | `241_cite_drift_fix.log` | 432 citations in 52 documents |
| 242 | `242_cite_drift_verify.log` | **`VERIFY FAIL (97)`** — 32 class A + 65 class-B UNRESOLVED; this row said "the class-A GREEN" until 2026-09-02 (§16.8) |
| 243 | `243_red_control_pre_g34.log` | the banking + envelope RED, on the pre-G3.4 RTL |
| 244 | `244_boardfree.log` | `BOARDFREE_PASS` 2759/85/356 |
| 245 | `245_hwmap_selftest.log` | `sw/hwmap.py --selftest` |
| 246 | `246_isa_bits.log` | `ISA_BITS: PASS` at 9B |
| 247 | `247_spec_cites.log` | the checker over eight documents |
| 248 | `248_spec_cites_selftest.log` | 6/6 CAUGHT |
| 250 | `250_spec_cites_selftest_regression_r2.log` | `SPEC_CITES_REGRESSION PASS` |

*(234, 236, 239, 249 are superseded first attempts kept by the wrapper's
never-overwrite rule: 234 and 236 predate the directed modes' `$finish`
tidy-up, 239 was skipped, and 249 is the regression run that named the pin
this gate then re-pinned.)*

The committed-tree re-run is logged from **`251_`** and is the evidence the
gate is claimed on — see the commit (b) message.

---

## 14. THE COMMITTED-TREE RE-RUN — the evidence this gate is claimed on

Everything above was produced on the working tree. The suite, the RED
control, the host floor and the whole citation set were then re-run on the
**COMMITTED tree `bbda679`**, clean — every log's provenance header reads
`=== tree: bbda679`, with no `+dirty`.

| log | what | result |
|---|---|---|
| `251_tb_suite_committed.log` | `tb_dn_step`, `tb_dn_step_pipe`, `tb_dn_step_pipe_ii`, `tb_gate_unit`, `tb_conv4_silu`, `tb_layer_dnbank`, `tb_layer_env`, `tb_layershim_c`, `lint_seq`, `lint_seq_unit`, all at `FABLE5_RS_F=7` | **rc 0 on every target, 32 PASS markers** |
| `252_tb_layer_9b_committed.log` | `tb_layer_chan` + `tb_seq_layer` at `FABLE5_MODEL=9b`, `FABLE5_RS_F=7` | **`TB_LAYER_CHAN PASS: 1438 cmds, 261357 checks bit-exact` ×4** and **`19 cmds, 5280 checks bit-exact` ×4**, rc 0 |
| `253_tb_seq_committed.log` | `tb_seq` + `tb_seq_guard` | rc 0, 25 PASS markers, `OK: illegal EMBLOG2 write is loud in simulation` |
| `254_red_control_committed.log` | the RED control against `8138d66` | RED-a `dnbank`/`envtest` **rc 134** (the pre-G3.4 sim guards), RED-b `dnbank` **rc 134** with `TB_LAYER_DNBANK FAIL: 58`, RED-b `envtest` rc 134 |
| `255_boardfree_committed.log` | `evidence/qwen2b/rd/rd_boardfree.sh` | **`BOARDFREE_PASS` — 2759 / 85 / 356** |
| `256_hwmap_selftest_committed.log` | `sw/hwmap.py --selftest` | PASS |
| `257_isa_bits_committed.log` | `isa_bits.py` at `FABLE5_MODEL=9b` | **`ISA_BITS: PASS`** |
| `258_spec_cites_committed.log` | the checker over eight documents | **FAIL 0** on the gate doc, the spec, the plan, `docs/SEQ_ISA.md` and all three earlier G3 gate docs; `docs/ARCHITECTURE.md` **39, pre-existing and unmoved** |
| `259_spec_cites_selftest_committed.log` | `--selftest` on the plan | **SELFTEST: PASS** 6/6 CAUGHT |
| `260_spec_cites_regression_committed.log` | the pinned-count regression | **SPEC_CITES_REGRESSION PASS** |
| `261_cite_drift_verify_committed.log` | `--verify` | **FAIL, 122: 57 class A** (40 printed) **+ 65 UNRESOLVED**, the latter all class B and covered by §11.1 — the "class A clean" half was invented; corrected 2026-09-02, §16.8 |
| `262_cite_drift_negctl_committed.log` | `--check --negative-control` | **CAUGHT (602 reported)** — the checker can fail |
| `263_cite_drift_rangectl_committed.log` | `--range-control` | **PASS — a half-mapped range is never rewritten (0 problems)** |

**32 + 8 + 25 = 65 PASS markers** across the three suite logs, every target
rc 0, every log on a clean `bbda679`.

---

## 15. FIX ROUND 1 (2026-09-02) — review verdict `Spec ❌ / Needs fixes`

The core was **ACCEPTED**: the reviewer diffed the `DN_PIPE` block to zero
differences against `synth/exp_uram/rtl/layer_chan.sv:619-685` (modulo the
int8-variant renames), checked the `DN_SDEL` indices and the address cut,
re-derived both latency options from the FSM, and **accepts option (i) as
shipped** — confirming §4.4's correction to Track P and adding the reason it
matters: option (ii) lands `RLAT = 6` on the **first valid cycle**, zero
margin, which is exactly why (i) ships before anything is placed.

Three Important findings, two plan-mandated, and seven same-line minors.

### 15.1 I1 — S9's `cfg_ng` envelope: BUILT, in lockstep across three files

Placement ruled by the controller: **at the MVGO dispatch**, the spec's own
words. What changed:

| file:line | change |
|---|---|
| `rtl/seq_unit.sv:293-319` | the withdrawal comment REPLACED by the check's rationale, ending in the `MVGO_MAX_NG` localparam at `rtl/seq_unit.sv:320`. It is **not** "consumed" from `matvec_engine` — RTL cannot take another module's parameter without a package and `matvec_engine` is closed, so the four copies are **tied by `isa_bits.py`** (§16.4) |
| `rtl/seq_unit.sv:291`, `rtl/seq_unit.sv:66` | `E_ENV` back in the error-code space, and the header's err_code map row |
| `rtl/seq_unit.sv:790-794` | the clause: an MVGO whose SHAPE `ng` field is 0 or above 96 sets `v_bad` with `E_ENV` |
| `ref/seq_format.py:465` | `MVGO_MAX_NG`, the reference's single copy, with `SHAPE_ISA_9B` beside it at `ref/seq_format.py:476` |
| `ref/seq_format.py:483`, `ref/seq_format.py:569`, `ref/seq_format.py:656` | the two validator entry points gain a `shape_isa` keyword, and the **identical** clause sits under it |
| `tb/scripts/gen_seq_unit_vectors.py:812` | the vector generator STATES the v2.0 layout on its freshly emitted streams |
| `tb/scripts/gen_seq_unit_vectors.py:94-105` | the `_shape` helper at `tb/scripts/gen_seq_unit_vectors.py:104`, and the **seven** hand-written immediates re-encoded through it at the (nrows, sh, ng) triples the isa=1 constants meant: (24,0,8)×2, (4,0,4), (2056,0,32)×2, (24,0,48)×2 |
| `tb/scripts/gen_seq_unit_vectors.py:370-379` | the TB model's `validate()` mirror, so the golden `err` matches |
| `tb/scripts/gen_seq_unit_vectors.py:691-784` | `seq_e_env0` / `seq_e_env97`, each with a **legal MVGO ahead of it in the same stream** so a refusal cannot be confused with an early halt |
| `tb/Makefile:803` | `SEQ_ERRS` gains `env0 env97` |
| `evidence/qwen9b/g3/isa_bits.py:726-794` | ties **all four** `MAX_NG` copies (§16.4), ties the TB's `EMBLOG2_MAX` mirror, and trips the reference validator RED at `ng` 0/97 and GREEN at 1/96 — and requires it NOT to fire when the layout is unstated |
| the spec's §5.4 bullet | a dated note recording the site, the reason it is not in `matvec_engine`, and both lines of defence |

`rtl/matvec_engine.sv:716`'s guard **stays sim-only** — that file is closed,
and with the emit line (`sw/hwmap.shape_word`) and the run line
(`seq_unit`) both live, nothing reaches it.

### 15.2 I2 — `EMB_N_MAX` is derived, with an elaboration assert

`tb/tb_layer_chan.sv:346-368`. The bare `4096` is gone: `TB_EMBLOG2_MAX` (`tb/tb_layer_chan.sv:359`)
mirrors `rtl/seq_unit.sv`'s `EMBLOG2_MAX` and `EMB_N_MAX` is derived from
it, with an `initial` assert on `2 * EMB_N_MAX == (1 << TB_EMBLOG2_MAX)`.
§5.4 rewritten; the omission had been declared nowhere and now is.

### 15.3 I3 — the SEQ program's T reset zeroes all four counters

`ref/seq_format.py` joined the pathspec: `LOFF_TCNT2` at
`ref/seq_format.py:320` and `CSR_L_TCNT2` at `ref/seq_format.py:332`,
`SeqEmitter.on_treset` (`ref/seq_format.py:1460`) emits **two** CSRWRs, and
`_csr_name` names `L_TCNT2` at `ref/seq_format.py:773`. Proven twice: `isa_bits.py` exercises the hook in place
(`SEQ T reset: 2 CSRWR [('0x20', 0), ('0x60', 0)]`), and
`tb_layer_dnbank` resets T **from a non-zero state** (one KVAP per kvhead
has already run) at kv_slots 0, 6 and 7 and requires all four counters to
read 0 — `OK T reset slot N: all 4 kvhead counters zeroed`.

### 15.4 Minors

| # | file:line | fix |
|---|---|---|
| M1 | `rtl/layer_chan.sv:364` | the CSR-map authority said TCNT2 was at 0x64; it is **0x60**, as `rtl/layer_chan.sv:21`, `rtl/layer_chan.sv:933` and `sw/hwmap.py:182` all already said |
| M2 | `tb/tb_seq_unit.sv:371-375`, `sw/chat_seq.py:2198-2200` | two "EMBLOG2 11 / absent = 2048" comments this gate's own change had falsified. §11's row for `tb/tb_seq_unit.sv` was true only of its CSR-write block (`tb/tb_seq_unit.sv:810-814`); `sw/chat_seq.py` was not in the sweep table at all — it is now |
| M3 | `evidence/qwen_next/feas/layer_cmd_census.py:13`, `evidence/qwen_next/feas/toks_model.py:223`, `evidence/qwen_next/feas/resource_budget.py:196-216` | three citations were mechanically renumbered as **class A** although the QUOTED TEXT changed. Given the class-B treatment: the pre-G3.4 quotation is kept with its `8138d66` line number and a dated note names the post-G3.4 site. See §15.5 |
| M4 | `tb/Makefile:457-469` | `tb_layer_env` gets `obj_dir_tb_layerenv`; it shared `obj_dir_tb_layerbank` with `tb_layer_dnbank`, so `make -j` on both collided — the hazard the brief called out |
| M7 | `sw/hwmap.py:242-253` | the comment promised G3.4 would raise `SCRATCH_WORDS_BUILT`. Not raising it was correct and the comment now says why: no bitstream carrying the 65,536-word RTL exists, and the task that ships one (G6) raises it |
| M9 | `rtl/dn_step.sv:127-134`, `rtl/dn_step.sv:247-248` | `pre_i` was a loose four-bit vector; its width is derived from `PRE_N` now (a `PRE_W` localparam) and the compare uses it, so a future `RLAT` cannot silently overflow the counter |

M5, M6 and M8 are deferred to the final review by the controller's ruling.

### 15.5 The drift residual — a class this round adds to §11.1

M3 is a **pattern**, not three instances: `o3_cite_drift.py --fix` renumbers
a citation whenever the OLD line maps to a NEW one, and a line whose text
was rewritten in place maps cleanly. So a citation into a **rewritten**
line is renumbered as class A and silently starts quoting something the
source no longer says. `spec_cites.py` catches that when the citer is in
its checked set; these three are `.py` files that are not.

**The rule this gate adopts, and hands on:** after `--fix`, every renumbered
citation whose citer is OUTSIDE `spec_cites.py`'s set must have its
quotation re-read against the new line. Where the text changed, revert to
class B — keep the **base** number with the quotation and add a dated note
naming the post-G3.4 site, as the three files above now do.

> **CORRECTED 2026-09-02 (fix round 2, O1).** Round 1's first cut of these
> three notes got the class-B treatment half right and two facts wrong, and
> both are worth stating because they are the failure modes of the rule
> above.
>
> 1. **The numbers kept were not base numbers.** They were the round's own
>    class-A renumbers — layer_chan lines 1094, 1467 and 1514. The base is
>    `8138d66`, where the three citations read layer_chan lines **891,
>    1204 and 1251**, which is what they read again now. Restoring a citation
>    to class B means restoring the NUMBER as well as the quotation; a
>    quotation kept beside a renumbered pointer is the worst of both.
> 2. **The change was attributed to the wrong gate.** `git log -S` on each
>    quotation lands on **`8ef57a8` (G3.1)**, not G3.4:
>    `dn_head <= arg0[3:0]`, `cvi == arg0[25:13]` and
>    `wi + 1'b1 == arg0[27:15]` all died when G3.1 widened the ARG
>    **fields**, and `8138d66:rtl/layer_chan.sv:882` already reads
>    `logic [13:0] cvi, cvj;`. So these citations were **already stale at
>    the tree G3.4 started from** — drift this gate INHERITED, not drift it
>    caused. What G3.4 changed is the *banking and the counters* behind
>    those fields (32-head DN banking; conv 18 × 6144 → 24 × 8192 with
>    `nch == 0` refused), which is why the post-G3.4 sites are still the
>    right forward pointer.
>
> The lesson generalises: **`--fix` will happily renumber a citation that
> was already wrong**, and the renumber makes it look freshly checked. A
> class-B repair has to start from `git show <base>:<citer>`, not from the
> working tree.

| citer | quotation, at its base (`8138d66`) number | when the quotation died | post-G3.4 site |
|---|---|---|---|
| `evidence/qwen_next/feas/layer_cmd_census.py:13` | `rtl/layer_chan.sv:891` `dn_head <= arg0[3:0];` | `8ef57a8` (G3.1) | `rtl/layer_chan.sv:1209`, `arg0[4:0]` |
| `evidence/qwen_next/feas/toks_model.py:223` | same | `8ef57a8` (G3.1) | same |
| `evidence/qwen_next/feas/resource_budget.py:213` | the 13-bit CONV count compare at `rtl/layer_chan.sv:1204` | `8ef57a8` (G3.1) | `rtl/layer_chan.sv:1534`, 14-bit |
| `evidence/qwen_next/feas/resource_budget.py:214` | the 13-bit CONVW count compare at `rtl/layer_chan.sv:1251` | `8ef57a8` (G3.1) | `rtl/layer_chan.sv:1581` and `rtl/layer_chan.sv:1597`, 14-bit |

*(`evidence/qwen_next/feas/toks_model.py:330` carries the same base
layer_chan line 891 as a bare continuation; `--fix` left it alone, so it was
right all along and is
now consistent with the two full tokens above it.)*

**A FIFTH of the same family, found by the `--verify` that round 1 never
ran (O2).** `evidence/qwen_next/feas/toks_model.py:59` sourced its chunk
constant to line 951 of the reference format module, and at `8138d66` line
951 was the `res_chunks` docstring — the constant itself was 41 lines
below, at line 992. The pointer was wrong before this gate existed, and two
`--fix` passes tracked the wrong line faithfully (951 → 982 → 1001), each
renumber making it look freshly checked. It now names
`ref/seq_format.py:1234` — `CHUNK_ROWS = 2048`.
**A renumber cannot repair a pointer that names the wrong line**, so the
citer is `--exclude`d from the pass (§16.3) exactly as this gate document
is, and the tool prints it as EXCLUDED. **That exclusion is PER PASS, not a
property of the file:** at the next round's base the hand-repaired pointer
*is* the base coordinate, so `evidence/qwen_next/feas/toks_model.py`
rejoins the pass and must not be carried on an exclusion list it no longer
needs.

### 15.6 The fix round's committed-tree re-run

Round 1 landed in two commits, `89b2d7d` (the three findings + six minors)
and `0a15dbb` (the follow-on the board-free gate forced, plus the round's
first evidence batch). Two evidence sweeps, both on a clean tree:

**`89b2d7d`, logs 266-277** — every TB target rc 0 (32 + 27 PASS markers),
`tb_layer_chan` **1438 cmds / 261,357 checks bit-exact ×4** and
`tb_seq_layer` **19 / 5,280 ×4** at `FABLE5_MODEL=9b`, `make -j2` on the two
directed targets rc 0 (M4), `ISA_BITS: PASS`, `spec_cites` FAIL 0 except
`docs/ARCHITECTURE.md`'s pre-existing 39, `SELFTEST: PASS`,
`SPEC_CITES_REGRESSION PASS`, drift negative control **CAUGHT**,
`O3_RANGE_CONTROL: PASS`. **And `269_boardfree_r1_committed.log` reads
`BOARDFREE_FAIL`** — the gate doing its job, §6.1.

**`0a15dbb`, logs 278-288** — the same set after the layout fix:

| log | result |
|---|---|
| `278_tb_suite_r1b_committed.log` | **59 PASS markers**, rc 0 on all twelve targets, `make -j2 rc=0` |
| `279_boardfree_r1b_committed.log` | **`BOARDFREE_PASS` — 2759 / 85 / 356**, unmoved |
| `280_hwmap_selftest_r1b_committed.log` | PASS |
| `281_isa_bits_r1b_committed.log` | `ISA_BITS: PASS`, with `SEQ T reset: 2 CSRWR [('0x20', 0), ('0x60', 0)]` and the MVGO envelope asserted **both** ways |
| `282_spec_cites_r1b_committed.log` | **FAIL 0** on the gate doc, spec, plan, `docs/SEQ_ISA.md` and the three earlier G3 gate docs; `docs/ARCHITECTURE.md` unmoved at 39 |
| `283`/`284` | `SELFTEST: PASS` 6/6 · `SPEC_CITES_REGRESSION PASS` |
| `285`/`286`/`287` | `--verify` **FAIL, 56 problems** — read the log, not this row as it first stood (§16.2) · negative control **CAUGHT (501)** · `--range-control PASS` |
| `288_tb_layer_9b_r1b_committed.log` | **`TB_LAYER_CHAN PASS: 1438 cmds, 261357 checks bit-exact` ×4** and **`19 cmds, 5280 checks` ×4** at `FABLE5_MODEL=9b`, `FABLE5_RS_F=7` |

> **CORRECTED 2026-09-02 (fix round 2, O2 — the full account is §16.2).** The `285` row above said
> "`--verify` class A clean / 5 class-B UNRESOLVED" and
> `285_cite_drift_verify_r1b_committed.log:68` ends
> **`O3_CITE_DRIFT VERIFY FAIL (56 problem(s))`**, 40 of them class A. The
> row is corrected in place rather than deleted, because what it got wrong
> is the failure mode this whole section exists to catch: **a log was cited
> for a conclusion it does not carry.** The 56 were real and had one cause —
> `0a15dbb` added 29 lines to `ref/seq_format.py` **after** round 1's
> `--fix` pass ran, so every citation the pass had just repaired was stale
> again by the length of that edit, and no second pass ran. Round 2 ran one
> (`294_cite_drift_fix_r2.log`, base `89b2d7d`) and then the `--verify` that
> round 1 owed (`295_cite_drift_verify_r2.log`): **PASS, 0 problems.**

## 16. FIX ROUND 2 (2026-09-02) — the three open findings, and one thing the round's own first attempt got wrong

Round 1's code was re-reviewed independently and no functional problem was
found in the RTL, the reference, the TBs or the Makefile. What round 2
fixes is **the evidence and the drift machinery** — and one over-reach that
the round's own first attempt introduced and this one takes back out.

### 16.1 O1 — M3 was PARTIAL

§15.5 carries the correction and the table. In one line: the numbers round
1 "kept" were its own class-A renumbers, not base numbers, and the
quotations died at **`8ef57a8` (G3.1)**, not at G3.4. The three notes now
carry the true `8138d66` numbers (`rtl/layer_chan.sv` 891 / 1204 / 1251,
each checked with `git show 8138d66:rtl/layer_chan.sv`), name G3.1, and say
that this is drift the gate **inherited**.

### 16.2 O2 — the `--verify` that was never run

`285_cite_drift_verify_r1b_committed.log:68` ends
**`O3_CITE_DRIFT VERIFY FAIL (56 problem(s))`**; §15.6's row for it claimed
"class A clean". The row is corrected in place, in §15.6. What the 56 were,
and what each needed:

| residue | cause | resolution |
|---|---|---|
| 50 class-A "does not cite ⟨new line⟩" / "still cites the OLD" | `0a15dbb` added 29 lines to `ref/seq_format.py` **after** round 1's `--fix` ran, so every citation that pass had just repaired was stale again by exactly that edit | one more pass, base `89b2d7d` — `294_cite_drift_fix_r2.log`, 96 citations in 27 documents — then `295_cite_drift_verify_r2.log`: **PASS, 0 problems** |
| SEQ_ISA.md's two v1.5 reserved-field rulings, at `docs/SEQ_ISA.md:693` and `docs/SEQ_ISA.md:695`, pointing into `ref/seq_format.py:506-509` | the same 29-line shift, on the two v1.5 reserved-field rulings | now `ref/seq_format.py:548-549` (MVGO target) and `ref/seq_format.py:550-551` (MOVX target), and both were re-read against the source, not just renumbered |
| `evidence/qwen_next/feas/toks_model.py:59`, pointing into `ref/seq_format.py:1067` | **not a shift at all**: the pointer named the wrong line at `8138d66` too, and two passes tracked it faithfully | repaired by hand to `ref/seq_format.py:1127`, the `CHUNK_ROWS = 2048` line; the citer is `--exclude`d so no pass can renumber a hand-repair. §15.5's fifth box |
| 5 UNRESOLVED + 1 MISSING (and 2 HALF-MAPPED, reported but not counted) | citations into lines round 1 rewrote; four of them are §15.5's class-B repairs, whose citer is this document | class B, listed in §15.5; this document is `--exclude`d and its pointers are written by hand in final coordinates |

**Read the count, not the printed lines.** The tool prints `bad[:40]` and
totals `len(bad) + len(unresolved) + len(missing)`, so `285`'s 56 is
**50 class-A + 5 UNRESOLVED + 1 MISSING**, of which only the first 40
class-A lines appear in the log. "40 of them class A" — the reading the
review recorded — is what the truncation looks like from outside.

**The rule this adds to §15.5's:** a `--verify` is not a formality after a
`--fix` — it is the only thing that reads the WORKING tree. `--check` reads
the citing documents at `--doc-base`, so its output does not move when the
pass lands; quoting a `--check` (or a `--fix`) as proof that the tree is
clean is quoting the wrong log.

### 16.3 O3 — the double-shifted pointers, and the tool's two new guards

Round 1's `--fix` pass listed `evidence/qwen9b/g3/G3_4_LAYER.md` among the
rewritten documents, so §15 — written **during** the round, in the final
tree's coordinates — was mapped base→work a second time and twelve pointers
came out wrong. Every one is repaired by hand, in final coordinates, and
re-read against the file it names; §16.6 is that checklist.

The root cause is now the tool's problem, not the operator's.
`evidence/qwen9b/o3/o3_cite_drift.py` gains:

| flag | what it does |
|---|---|
| `--exclude DOC` (repeatable) | keeps a citing document OUT of a `--fix` pass **and out of the `--verify` that follows it**. Paths are repo-relative and compared exactly, so a typo excludes nothing rather than everything, and every skipped document is printed as `EXCLUDED`. Two documents use it this round: this gate doc (written in final coordinates) and `evidence/qwen_next/feas/toks_model.py` (a hand-repaired pointer a renumber would undo). |
| `--exclude-control` | its NEGATIVE CONTROL, in **three** halves and over **every** document the round excluded: (1) without the flag the document IS in the pass's plan — otherwise the exclusion would pass vacuously; (2) with it the document is NOT in the plan, so `apply_fix`, which writes the plan and nothing else, leaves it byte-identical, while the rest of the pass still has 28 documents to rewrite; (3) an `--exclude` path naming no citer changes the plan not at all. |

Both halves of the control ask `fix_plan()`, **the same function
`apply_fix` writes out** — the first attempt's control re-read the victim
off disk and compared it with itself, which is true by construction.

**And a second defect of the same family, found while re-running the pass
and now mechanized.** `--fix` is a base→work RENUMBER and is **not
idempotent**: `sweep()` reads the citing documents at `--doc-base`, so the
drift list does not shrink once the pass has landed, and a second pass maps
already-fixed numbers a second time — O3's double-shift applied to every
document instead of one. Measured, at base `89b2d7d`: a second pass moved
the MOVX-reject pointer in `docs/SEQ_ISA.md` from `ref/seq_format.py:550-551`
to lines 541-542, which are nowhere near the reject it names. **`--fix` now asks `--verify` first
and REFUSES when the pass has already landed**
(`296_cite_drift_second_fix_refused_r2.log`, rc 2, nothing written). It
catches the fully-applied case, which is the one an operator re-runs by
hand; a HALF-applied tree still verifies dirty and is still the operator's
problem, because `rewrite_doc` renumbers a whole document at once.

### 16.4 The `MAX_NG` tie and the `EMBLOG2_MAX` mirror (same-function minors)

`MAX_NG` is stated in four places and RTL cannot consume another module's
parameter without a package, which would mean editing
`rtl/matvec_engine.sv` (closed at G3.3). So the tie is **mechanized** in
`evidence/qwen9b/g3/isa_bits.py:726-794`, which PARSES all four out of
their own source and requires them equal, with a perturbation control; the
same block ties the TB's `EMBLOG2_MAX` mirror, which closes I2's residual
(the TB's own assert is the local half, buffer vs mirror):

```
MAX_NG tie: rtl/matvec_engine.sv=96  rtl/seq_unit.sv=96  sw/hwmap.py=96  ref/seq_format.py=96
MAX_NG tie: perturbation control CAUGHT (seq_unit 96 -> 97 diverges)
EMBLOG2_MAX tie: tb/tb_layer_chan.sv 13 == rtl/seq_unit.sv 13, so EMB_N_MAX = 4096 is the row the hardware can name
```

`rtl/seq_unit.sv:307-319`'s comment and §15.1's table cell now say **tied by
`isa_bits`**, not "consumed"; `tb/tb_layer_chan.sv:355-359` says the same
about its mirror.

**The third half of that minor — "time-0 `initial`, not elaboration" — is
answered by moving the check OUT of the TB rather than by strengthening
it.** The TB's `initial` assert is a tautology of the line above it (it
re-derives `EMB_N_MAX` from `TB_EMBLOG2_MAX`) and it can only catch a
future re-literalisation of the buffer; the thing it could never check is
the one that matters, whether the mirror still equals the RTL, because a
testbench cannot see another module's localparam. `isa_bits.py` checks that
**statically, out of both sources, with no simulation at all**, so it does
not need the TB to elaborate — where a time-0 `initial` needs a full run.
**Correction 2026-09-02 (round 3, m7): it does not "fire under
`--lint-only` and in every evidence sweep" either.** Nothing in a Makefile
or a `.sh` invokes `evidence/qwen9b/g3/isa_bits.py`; it is OPERATOR-RUN, once
per gate, and its evidence is the log (`301_isa_bits_r2_committed.log`, and
round 3's own isa_bits log in §17.5). Wiring it into a target is a real
improvement and is NOT done here — it would put a `FABLE5_MODEL=9b` Python
gate in the path of every `make -C tb`, which is a decision for the task
that owns `tb/Makefile`. The `initial` stays as the local half.

### 16.5 The reference clause reaches the stream builders — and the rule is "the layout belongs to the ARTIFACT"

The ruling was that every v2.0 stream builder pass `SHAPE_ISA_9B`. Applied
literally it fails, and it failed twice, the same way:

* **Round 1** made `ref/seq_format.validate`'s clause unconditional and
  `269_boardfree_r1_committed.log` read `BOARDFREE_FAIL` — `sw/seq_run.py`
  and `sw/chat_seq.py` validate the **frozen** `build_034`/`build_035`
  artifacts, which are legitimately isa=1.
* **Round 2's first attempt** then stated `SHAPE_ISA_9B` unconditionally in
  `tb/scripts/gen_seq_chip_vectors.py`, calling it a builder. It is not:
  it **loads** a `<prefix>.seq`, and `tb/Makefile:1000`'s `seq_chip_vectors`
  target points it at `scripts/w3` — the frozen set. The refusal is
  reproducible and is check 2 of
  `evidence/qwen9b/g3/g34_shape_isa_paths.py`, which now runs it on **both**
  frozen artifacts because they refuse at different records and a number
  without its artifact is an overclaim (round 3, m5): `w3/lay_s1.e` at
  **rec 108** and `w3/tok2_s1.e` — `tb/Makefile:979`'s default `SEQP`, i.e.
  what `make -C tb seq_chip_vectors` would actually have hit — at **rec
  112**, both `MVGO SHAPE ng 0 outside the engine envelope 1..96
  (imm32=0x00010148)`. That form is gone.

**The rule, one line: a tool that LOADS a stream takes the layout from the
artifact's own seq metadata; a tool that BUILDS one states it.**

| site | kind | layout from |
|---|---|---|
| `ref/seq_chat.py:380` `Templates.shape_isa` → the four `validate_stream` calls in `TurnCompiler` | loads | the template artifact's own seq metadata; absent = not stated |
| `ref/seq_chat.py:952` `split_stream`'s new `shape_isa` keyword | neither — it is handed a stream | its CALLER (both callers today split the committed isa=1 bytes and pass nothing) |
| `ref/seq_model.py:1345` `gate()` | loads | `meta.get("shape_isa")` — the artifact it is replaying |
| `tb/scripts/gen_seq_chip_vectors.py:267` | loads | `meta.get("shape_isa")` — same rule, same reason |
| `tb/scripts/gen_seq_unit_vectors.py:812` | **builds**, in memory, with this tree's emitter | **states `SHAPE_ISA_9B`** |

**The declared gap, and why it is not a hole.** The key that turns the
check on for the three loaders is a `shape_isa` key in an artifact's seq
metadata, and **no emitter writes it yet** — `0 of 13` artifact metas
declare it. Adding it means touching the emitted metadata of byte-locked
tags, which is A2.5's territory and Task 11's file. Meanwhile the 9B
**emit** path is not unchecked: `sw/hwmap.shape_word` asserts
`1 <= ng <= SHAPE_MAX_NG[isa]` for **every** word it packs, in both
layouts, so a stream this tree emits cannot carry an out-of-envelope `ng`
at all; `rtl/seq_unit.sv` refuses one unconditionally on the run side; and
`ref/seq_format.validate` arms itself the moment an artifact declares its
layout. `evidence/qwen9b/g3/g34_shape_isa_paths.py` is the committed proof
of all five of those statements, with the RED control that makes check 1
mean something.

### 16.6 The pointers this round moved, and how they were checked

O3's twelve double-shifted pointers were repaired by the round's first
attempt. Re-reading them found a **second generation** of the same defect,
and it is worth naming because it is the cost of hand-repairing a live
document: the first attempt wrote §15's pointers in the coordinates of the
tree *as it then was*, and then went on editing the files those pointers
name — `rtl/seq_unit.sv` gained seven comment lines, `evidence/qwen9b/g3/isa_bits.py`
forty, `ref/seq_chat.py` thirty-three — so eight of them were stale again by
the end of the round. **A hand-repaired pointer is only correct as of the
last edit to the file it names**, which is why this checklist is the last
thing done before the commit and is re-run after it.

| pointer, as round 2 found it | now | what is there |
|---|---|---|
| `ref/seq_chat.py:998` | `ref/seq_chat.py:1031` | the `EMB_ROW_BYTES_DEFAULT` caveat §11 says was rewritten |
| `rtl/seq_unit.sv:322` | `rtl/seq_unit.sv:357` | `localparam logic [4:0] EMBLOG2_RST = 5'd13;` — §11's landmark now names the DEFINITION, not the comment above it |
| `evidence/qwen9b/g3/isa_bits.py:718-789` | `evidence/qwen9b/g3/isa_bits.py:726-794` | the whole `MAX_NG` / `EMBLOG2_MAX` / RED-GREEN block |
| `ref/seq_model.py:1294` | `ref/seq_model.py:1345` | `SF.validate_stream(recs, shape_isa=meta.get("shape_isa"))` |
| `tb/scripts/gen_seq_chip_vectors.py:263` | `tb/scripts/gen_seq_chip_vectors.py:267` | the same line, after §16.5's correction |
| `evidence/qwen_next/feas/resource_budget.py:196-214` | `:196-216` | the class-B note plus **both** of its bracket prints |
| `evidence/qwen_next/feas/toks_model.py:326` | `:330` | the bare continuation of the class-B base number, after the note above it grew |
| `tb/tb_layer_chan.sv:352-359` | `:355-359` | the mirror's own comment, not the sentence before it |

**How every pointer in §15 and §16 was checked:** each citation naming a
file in the round's pathspec was resolved against the working tree and the
line printed beside it, and each was read. `evidence/qwen_next/spec_cites.py`
is the mechanized half — it re-checks every quotation and requires every
span to exist — and reports **FAIL 0** on this document. Four pointers are
deliberately NOT in final coordinates and say so where they stand: §15.5's
class-B table (base `8138d66` numbers, with the quotation) and §16.2's
residue table (the stale numbers it is reporting).

### 16.7 The round's committed-tree re-run

Round 2 lands in two commits: **`20e1214`** (the findings, the minors, the
tool and the documents) and the evidence commit that carries this section.
Logs `292`-`296` are the drift pass itself, run on the working tree because
a `--fix` pass by definition dirties it. Everything else is re-run on the
clean tree and every header reads `tree: 20e1214` — **with one exception
that is named rather than hidden**: `298` started while this section was
being written, so its header reads `20e1214+dirty` and the only file in
that diff is this document. Rather than ask anyone to take that on trust,
the pair was re-run once the tree was clean again as **`311`**, which is
the row that counts; `298` is kept because a passing run is not evidence to
delete, and the two agree exactly.

| log | result |
|---|---|
| `292_cite_drift_check_r2.log` | the pass, stated: 96 drifted / 4 unresolved / 0 missing / 0 half-mapped at base `89b2d7d` |
| `293_cite_drift_exclude_control_r2.log` | `O3_EXCLUDE_CONTROL: PASS` — **both** excluded documents controlled, three halves each |
| `294_cite_drift_fix_r2.log` | **96 citations in 27 documents**, two `EXCLUDED` |
| `295_cite_drift_verify_r2.log` | **`VERIFY PASS (0 problems)`** — the verify O2 is about |
| `296_cite_drift_second_fix_refused_r2.log` | a second `--fix` **REFUSED**, rc 2, nothing written |
| `297_tb_suite_r2_committed.log` | twelve targets, **rc 0 on every one, 59 PASS markers**, `make -j2` on the two directed Mdirs rc 0 (M4) |
| `311_tb_layer_9b_r2_clean.log` (and `298`, `+dirty` as above) | **`TB_LAYER_CHAN PASS: 1438 cmds, 261357 checks bit-exact` ×4** and **`19 cmds, 5280 checks` ×4** at `FABLE5_MODEL=9b`, `FABLE5_RS_F=7` — the whole 9B layer body against `ref/layer_fixed.py`, unmoved from round 1 |
| `299_boardfree_r2_committed.log` | **`BOARDFREE_PASS` — 2759 / 85 / 356**, unmoved |
| `300_hwmap_selftest_r2_committed.log` | `HWMAP SHAPE_WORD SELFTEST PASS` |
| `301_isa_bits_r2_committed.log` | `ISA_BITS: PASS`, with the four-way `MAX_NG` tie, its perturbation control **CAUGHT**, the `EMBLOG2_MAX` tie, `SEQ T reset: 2 CSRWR`, and the MVGO envelope asserted **both** ways |
| `302_shape_isa_paths_r2_committed.log` | `SHAPE_ISA_PATHS: PASS` — GREEN, RED, ARMING, the four sites and the emit-path assert |
| `303_spec_cites_r2_committed.log` | **FAIL 0** on the gate doc, the spec, the plan, `docs/SEQ_ISA.md` and the three earlier G3 gate docs; `docs/ARCHITECTURE.md`'s 39 are pre-existing and unmoved |
| `304`/`305` | `SELFTEST: PASS` 6/6 · `SPEC_CITES_REGRESSION PASS` |
| `306`/`307`/`308`/`309`/`310` | `--verify` **PASS (0)** · `--exclude-control` **PASS** · verify negative control **CAUGHT (96)** · `--range-control PASS` · the second `--fix` **REFUSED** on the clean tree, which stayed clean |
| `312_py_compile_r2_committed.log` | `PY_COMPILE: PASS` over the three feas `.py` files (M3's covering test) and the seven other Python files this round edited |
| `313_spec_cites_r2_final.log` | this document re-checked **after** this section was written — necessarily `+dirty`, because the section describes the logs it is listed in: `SPEC CITES: PASS`, **FAIL 0**, 370 exist / 167 range / 8 quote |

### 16.8 O2's defect again, twice, in this gate's OWN round-0 rows — found, measured, and handed on

Correcting §15.6's row for `285` made the obvious next question unavoidable:
**are the other `--verify` rows in this document true?** They are not.
**THREE** more said it — §7's row, §11's row and §13's log index, all over a
log that ends `VERIFY FAIL`. Round 2 found and corrected two of them and
missed the third, which round 3's re-review caught (m2) and which is
corrected at `evidence/qwen9b/g3/G3_4_LAYER.md:891`. That is the finding
inside the finding: **a claim repeated in three places is corrected in
three places, and "I fixed the two I found" is not the same sentence.**

| row | what the log actually ends with | the true breakdown |
|---|---|---|
| §7's `--verify` row, `242_cite_drift_verify.log` | `O3_CITE_DRIFT VERIFY FAIL (97 problem(s))` | **32 class A** + 65 UNRESOLVED (+ 15 HALF-MAPPED, reported but not counted) |
| §11's row for `261_cite_drift_verify_committed.log` | `O3_CITE_DRIFT VERIFY FAIL (122 problem(s))` | **57 class A** (40 printed — the `bad[:40]` cap) + 65 UNRESOLVED (+ 15 HALF-MAPPED) |

Both rows are corrected in place where they stand. The class-B part of each
("65 UNRESOLVED, all covered by §11.1") was true; **"class A clean" was
not**, and that half was invented rather than read.

**How much of it is still live, measured rather than guessed.**
`314_cite_drift_verify_g34base_r2.log` re-runs that same verify — base
`8138d66`, the round-0 `--edited` list, on the tree as it stands now:
**`VERIFY FAIL (138 problem(s))`**, 40 class A printed, 68 UNRESOLVED, 16
HALF-MAPPED. *(**Round 3 correction:** that measurement puts all 21 files
on ONE base, which is the mixing this very section warns about — it reads
every `b1`/`b2` citation, already written in a later pass's coordinates, as
stale. Measured per base over its own set the residue is **29 + 4 + 7**,
and §17 is the account. The gap was real; 138 was not its size.)* So this is
**round-0 drift that rounds 1 and 2 never touched**,
not something either fix round caused, and it is spread over ~20 citing
documents (`evidence/qwen9b/g3/G3_1_ISA.md` 6,
`docs/QWEN35_NEXT_FEASIBILITY.md` 5,
`evidence/qwen_next/feas/resource_budget.py` 4, the spec 4, …). A typical
one: `docs/SEQ_ISA.md`'s `rtl/layer_chan.sv:85-116` and
`rtl/layer_chan.sv:69-116` are ranges whose END should now be 119 — three
lines short of the opcode list they mean to cover.

**And it must NOT be fixed by running `--fix --base 8138d66`.** That is the
trap this round's own guard does not catch. Citations into the files rounds
1 and 2 edited (`rtl/seq_unit.sv`, `ref/seq_chat.py`, `ref/seq_format.py`,
`tb/tb_layer_chan.sv`, `evidence/qwen9b/g3/isa_bits.py`) are already in
WORK coordinates, while citations into the files only round 0 edited
(`rtl/layer_chan.sv`, `rtl/dn_step.sv`, `tb/Makefile`, …) are still in
`8138d66` coordinates. **The tree is in MIXED coordinates**, and a single
base cannot be right for both halves: a `--fix` at `8138d66` would repair
the second half and double-shift the first. `--verify` reports dirty either
way, so the `--fix` refusal guard (§16.3) will not stop it.

**What would resolve it**, stated for whoever takes it: one pass per base
over disjoint `--edited` sets — `8138d66` for the files rounds 1 and 2 did
not touch, and nothing for the rest, since `295`/`306` already show that
half clean at base `89b2d7d` — each with the documents that are already
correct `--exclude`d, and each followed by its own `--verify`. It is a
task-sized job with a real chance of making things worse if done in a
hurry, which is why round 2 measured it and stopped rather than starting it
at the end of a fix round.

Evidence for this section: `314_cite_drift_verify_g34base_r2.log` (the
measurement, on the committed tree `7dad426`) and
`315_spec_cites_r2_final2.log` (`SPEC CITES: PASS`, FAIL 0, this document
re-checked after the section was written).

## 17. FIX ROUND 3 (2026-09-02) — §16.8's residue, measured properly, repaired by hand, and the tool taught to refuse the pass that would have made it worse

Round 2 handed on "**138 problems** at base `8138d66`" as the largest open
item (§16.8). Round 3 owes that number a proper measurement, and the first
result is that **the number was itself an artifact of the mixed coordinates
it was warning about.**

### 17.1 The partition, derived from the commits

`--edited` sets are per-BASE, and which base a citation is written in
depends on which pass last touched it. Deriving that from
`git log --name-only` over each round's commits, not by guessing:

| set | files | the base their citations are written in |
|---|---|---|
| **(a)** — round 0 only | `docs/ARCHITECTURE.md`, `docs/SEQ_ISA.md`, `ref/gen_layer_script.py`, `ref/gen_layer_vectors.py`, `ref/layer_fixed.py`, `rtl/conv4_silu.sv`, `rtl/gate_unit.sv`, `sw/seq_run.py`, `tb/scripts/gen_seq_c_vectors.py`, `tb/tb_dn_step.sv`, `tb/tb_gate_unit.sv` | `8138d66` |
| **(b1)** — round 1 also | `rtl/dn_step.sv`, `rtl/layer_chan.sv`, `sw/hwmap.py`, `tb/Makefile`, `tb/tb_seq_unit.sv` | `50faf01` |
| **(b2)** — round 2 also | `evidence/qwen9b/g3/isa_bits.py`, `ref/seq_chat.py`, `rtl/seq_unit.sv`, `tb/scripts/gen_seq_unit_vectors.py`, `tb/tb_layer_chan.sv` | `89b2d7d` |

**§16.8 said "set (b)"; there are two of them**, because rounds 1 and 2 ran
at different bases and round 2 did not re-map the five files it never
edited. A single "set (b) at `89b2d7d`" would have measured `b1` in the
wrong coordinates — the same mistake one level down.

Measured per base, over its own set: **set (a) 29 problems, `b1` 4, `b2` 7**
— not 138. The 138 came from measuring all 21 files at one base, which
reads every `b1`/`b2` citation (already in later coordinates) as stale.
**The gap was real; its size was not.**

### 17.2 The pass §16.8 prescribed would have destroyed 250 citations, and the tool now says so before you run it

§16.8's step 2 was "ONE `--fix` at base `8138d66` over set (a)". Asked to
produce that pass's diff first, it comes back:

```
TOTAL      REPAIR 0  COLLATERAL 250
O3_FIX_PLAN: UNSAFE — 250 of 250 rewrites would move a citation that is
already correct; repair the 0 stale one(s) BY HAND or --exclude the document
```

**Zero repairs.** Every stale citation in set (a) is either a HALF-MAPPED
range (which `--fix` refuses to touch by design) or a pointer that was
wrong at the base too (which a renumber cannot fix), while 250 correct
pointers — `b9e0851:ref/layer_fixed.py:74` (the `FABLE5_RS_F` read),
`ref/gen_layer_script.py:2002` `for h in range(LR.LNH):`, 28 documents'
worth — would have been moved onto unrelated lines. The partition removes
the drift BETWEEN rounds; it does nothing about the mixing WITHIN one,
where a base's own earlier pass already fixed most citations and left the
rest.

So the tool gained `--plan`: a dry run that splits what a `--fix` would
rewrite into **REPAIR** (the document still names the OLD line — exactly
what `--verify` complains about) and **COLLATERAL** (it already names the
right line and the pass would move it again), and exits non-zero when
COLLATERAL is not empty. `REPAIR` is computed with `--verify`'s own test,
including its relocated-onto exemption, so the two numbers can be compared
without interpretation. **Ask `--plan` before every `--fix` at a base some
pass has already run.** With `--fix`'s idempotence guard (§16.3) that is
now two questions the tool answers instead of the operator remembering.

### 17.3 What was actually repaired, by hand, each verified against the file it names

| citation | was | is | why a pass could not do it |
|---|---|---|---|
| `evidence/qwen_next/feas/layer_cmd_census.py:28`, `evidence/qwen_next/feas/toks_model.py:232` and its print | `ref/gen_layer_script.py:1435-1442` for `for h in range(LR.LNH):` | `ref/gen_layer_script.py:1994` | those lines are the `_aud` ALU-audit block; the pointer named the wrong text at `8138d66` too, where it read lines 1074-1081 of the same block and two passes tracked it faithfully |
| `docs/SEQ_ISA.md:694` | `rtl/seq_unit.sv:782-796` "does not look at MOVX target" | `rtl/seq_unit.sv:787-795` | the range bracketed the `OP_CMD` arm as well; already wrong at `89b2d7d` |
| `docs/SEQ_ISA.md:712` | `rtl/seq_unit.sv:818` for the JMP bound | `rtl/seq_unit.sv:817` | line 782 is the arm's `end`; the fault is on 781 |
| the spec, two sites | `rtl/seq_unit.sv:330` `EMBLOG2_MIN = 5'd8, EMBLOG2_MAX = 5'd13` | `rtl/seq_unit.sv:358` | `:330` is the comment above the localparam |
| `evidence/qwen9b/g3/G3_2_VECNORM.md:620` | `tb/scripts/gen_seq_c_vectors.py:239` and line 241 | `tb/scripts/gen_seq_c_vectors.py:251` and line 253, plus a dated **CLOSED** box | G3.2's "found, not fixed" `RS_F` trap that **G3.4 fixed at the root** (`RMS_VEC_F`); T10 moved the lines and owed the renumber |
| `ref/scripts/bytes_per_token.py:106` (m3) | `ref/seq_format.py:1086` for `CHUNK_ROWS` | `ref/seq_format.py:1127` | the sibling of `evidence/qwen_next/feas/toks_model.py:59`; round 2 repaired one instance and did not sweep. Swept now: those two are the only citers of that constant |
| `docs/HISTORY.md:638`, `evidence/qwen_next/defect_a/damage_test.py:48` (m4) | `ref/seq_chat.py:993/936/1213/1214/1215` — first element renumbered, rest left | prose naming `2a50cac^` and its line numbers, **out of citation form** | the numbers are pre-`2a50cac` coordinates on purpose ("verbatim, as they were"); the code they name does not exist, so there is nothing to renumber TO |

### 17.4 The residue that stays, every entry named

`--verify` at base `8138d66` over set (a) reports **34**; not one of them is
a wrong pointer in the tree, and they are listed here rather than hidden
behind the `bad[:40]` print cap.  The `#` column sums to it:
16 + 2 + 1 + 2 + 1 + 2 + 6 + 4 = 34, the HALF-MAPPED range in row six being
reported in its own class rather than in the 34.  *(Recounted 2026-09-10;
the seventh row read 5 while naming six entries.)*

| # | entry | class | disposition |
|---|---|---|---|
| 16 | `tb/tb_gate_unit.sv:1,14,16,17,26,31,47,48,51,52,55,56,59,60,73,84` cited by the spec | dead quotation | the spec's §8 census **D — the NH=16 family**, a record of where the sixteen literals WERE; G3.4 parameterized the file, so they are gone. Dated note added at the census block |
| 2 | `rtl/gate_unit.sv:13` and `rtl/gate_unit.sv:27`, the 16-head parameter and the 4-bit `w_addr` port, cited by the spec and by `docs/QWEN35_NEXT_FEASIBILITY.md` | dead quotation | same census, same note |
| 1 | `rtl/conv4_silu.sv:50` cited by 7 documents | dead quotation | A2.1: the shift itself is at `rtl/conv4_silu.sv:54` and is 8 now, not 9; `rtl/conv4_silu.sv:50` is the COMMENT above it, so the seven documents' pointer names the right file and the right block and the QUOTATION is historical.  *(Corrected 2026-09-10: this cell said the line at `:50` still held the shift.)* |
| 2 | `ref/layer_fixed.py:58` and `ref/layer_fixed.py:60`, cited by `evidence/qwen9b/g2/G2C_CHAIN.md` and `evidence/qwen9b/g1/RUNG_INT8_STATE.md` | dead quotation | A2.4's stale-prose block, rewritten by G3.4 |
| 1 | `ref/gen_layer_script.py:1051`, the wall-9 `KVH_MAX` line, cited by the spec and by G3.1's and G3.2's gate docs | dead quotation | G3.4 moved and rewrote it; G3.1's gate doc already records the successor |
| 2 (+1 HALF-MAPPED, counted in that class and not in the 34) | `tb/scripts/gen_seq_c_vectors.py:239` and `tb/scripts/gen_seq_c_vectors.py:241`, and the HALF-MAPPED range `tb/scripts/gen_seq_c_vectors.py:234-239`, cited by the spec and by G3.2's gate doc | dead quotation / half-mapped | G3.2's before/after tables: the LEFT column is deliberately the pre-G3.2 site.  A `noquote` marker already marks them **there**, in G3.2's gate doc |
| 6 | the two `evidence/qwen_next/feas` scripts reported as not citing `ref/gen_layer_script.py:1435` and `ref/gen_layer_script.py:1442`; `evidence/qwen9b/g1/RUNG_INT8_STATE.md` as not citing `ref/layer_fixed.py:2600`; `G3_2_VECNORM.md` as still citing the old `tb/scripts/gen_seq_c_vectors.py:250` | **checker asymptote** | each is a citation repaired BY HAND to the line that holds the text — `ref/gen_layer_script.py:1994`, `ref/layer_fixed.py:2615`, `tb/scripts/gen_seq_c_vectors.py:251-253` — which is not the line the base→work map points at. G3.1's own gate doc named this class first: the asymptote of a base-swept checker, not a defect |
| 4 | the spec and G3.2's gate doc on `tb/scripts/gen_seq_c_vectors.py:234` versus the map's `tb/scripts/gen_seq_c_vectors.py:245` | asymptote + half-mapped | the before-column above |

`b1` adds 4: the experiment file `synth/exp_uram/rtl/layer_chan.sv` still
citing `rtl/dn_step.sv:193` — **the file this task must not edit**; the
half-mapped `sw/hwmap.py:178-244` and its dead endpoint
`sw/hwmap.py:244`, both cited by `docs/ARCHITECTURE.md`, which is out of
scope and stays that way; and `tb/tb_seq_unit.sv:372`, round 1's M2 comment
rewrite. `b2` reports 21, of which 14 are this document — always
`--exclude`d, because it is written in final coordinates — and the other
**7 are every one of this round's own hand repairs** (§17.3). That is the
asymptote again, and the clearest possible statement of what it costs: a
repair that makes a pointer true makes the checker complain.

**A base-swept checker cannot recognise a hand repair.** Its expectation is
"the document names the map's image of the old line"; a repair names the
line that holds the TEXT. Where those differ — a pointer wrong at the base,
or a deliberately historical one — the checker reports a problem forever.
The three `--verify` runs are therefore given **twice**: once in full, as
the enumeration above, and once with the boxed citers `--exclude`d, which
prints `PASS` and prints the exclusion list with it. The second is not
stronger than the first; it is the first with these rows removed, and the
exclusion list is part of the evidence, not a way of hiding it.

**Not built, and named for whoever wants it:** a per-citation marker (the
shape of `spec_cites.py`'s `<!--cites:noquote-->`) saying *this pointer is
hand-verified, do not expect the map's image* would let `--verify` pass
without excluding whole documents. It is the right end state and it is a
new way to silence a checker, so it wants its own round and its own
control, not the last hour of this one.

### 17.5 Round 3's committed-tree evidence

Round 3 lands in two commits: **`6b1f24d`** (the hand repairs, the `--plan`
mode, the seven minors and §17) and the evidence commit that carries this
section. Every log below has `tree: 6b1f24d` — **no `--fix` ran this round,
so nothing had to be run on a dirty tree.**

| log | result |
|---|---|
| `317_plan_seta_8138d66_r3.log` | **`O3_FIX_PLAN: UNSAFE — 253 of 254 rewrites would move a citation that is already correct`**. The one it calls a REPAIR is `tb/scripts/gen_seq_c_vectors.py:250-253` in G3.2's gate doc — **this round's own hand repair**, which the pass would "fix" onto lines 262-267, i.e. the diagnostic's own REPAIR class is not proof a rewrite is right, only that `--verify` complains. Before the repairs the same run read REPAIR 0 / COLLATERAL 250 |
| `318_verify_seta_8138d66_full_r3.log` | `VERIFY FAIL (34)` — the enumeration of §17.4, in full, nothing hidden |
| `319_verify_seta_8138d66_boxed_r3.log` | **`VERIFY PASS (0)`** with the thirteen boxed citers `--exclude`d and printed |
| `320_exclude_control_seta_r3.log` | `O3_EXCLUDE_CONTROL: PASS` — **10 of the 13** excluded documents controlled in three halves, 27 others still in the pass.  The other three (`evidence/qwen9b/g3/G3_4_LAYER.md`, `evidence/qwen9b/g2/FINAL_BYTELOCK.md`, `evidence/qwen9b/g2/G2A_HOST.md`) the log itself marks *not a document this pass would rewrite — not controllable here*: excluding them is vacuous and the control says so.  *(Restated from the log on 2026-09-10; this cell said "every excluded document".)* |
| `321_verify_setb1_50faf01_full_r3.log` | `VERIFY FAIL (5)`: the experiment file, two `docs/ARCHITECTURE.md` entries, round 1's M2 comment, and this document quoting the experiment file's dead `dn_step` pointer in §17.4 |
| `322_verify_setb1_50faf01_boxed_r3.log` | **`VERIFY PASS (0)`** |
| `323_verify_setb2_89b2d7d_full_r3.log` | `VERIFY FAIL (21)` — the gate doc plus the seven this round's own repairs created (§17.4) |
| `324_verify_setb2_89b2d7d_boxed_r3.log` | **`VERIFY PASS (0)`** |
| `325_cite_drift_rangectl_r3.log` | `O3_RANGE_CONTROL: PASS` |
| `326_spec_cites_r3_committed.log` | **FAIL 0** on this document (467 exist / 217 range / 11 quote), the spec, the plan, `docs/SEQ_ISA.md` and the three earlier G3 gate docs; `docs/ARCHITECTURE.md`'s 39 pre-existing and unmoved |
| `327_shape_isa_paths_r3_committed.log` | `SHAPE_ISA_PATHS: PASS` — GREEN/RED/ARMING on **both** frozen artifacts, refusing at rec 108 and rec 112 (m5) |
| `328_shape_isa_paths_no_artifact_r3.log` | the m6 control: the same script in a sandbox with no `tb/scripts/w3` prints `SHAPE_ISA_PATHS: NO_ARTIFACT` and **exits 2** |
| `329_isa_bits_r3_committed.log` | `ISA_BITS: PASS`, the four-way `MAX_NG` tie and its perturbation control CAUGHT, the `EMBLOG2_MAX` tie |
| `330_boardfree_r3_committed.log` | **`BOARDFREE_PASS` — 2759 / 85 / 356**, unmoved |
| `331_py_compile_r3_committed.log` | `PY_COMPILE: PASS` over the twelve Python files this round touched or depends on |

**No `.sv` file and nothing under `rtl/` changed**, so no Verilator target's
inputs moved and the TB suite was not re-run — §16.7's `297`/`311` remain
this gate's TB evidence. The one file under `tb/` that changed is
`tb/scripts/gen_seq_chip_vectors.py`, by one comment (m5's overclaim); no
lint target covers a vector generator, and `331` compiles it.
