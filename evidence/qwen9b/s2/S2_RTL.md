# S2 — the layer's state in DDR: `state_dma`, the two-slot caches, the two lanes, the two fences

Task S2 of `docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md`
(revision 2, base commit `a51bc8e`). Spec:
`docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md` §3, §4,
§5 and amendment A1. ISA contract: `docs/SEQ_ISA.md` section B15, landed by S1.

S2 replaces G3.4's 928-URAM banked layer state with a **two-slot cache per
kind** behind the compute units' existing memory ports, a **512-bit AXI4
state-DMA engine** that moves whole blocks between DDR and a slot, a second
in-order **DMA lane** with the two hardware fences, and the CSRs and error
codes B15 specifies. `dn_step`'s FSM, the conv datapath and `attn_core`'s
arithmetic are untouched; the acceptance bar (a token-identical replay) is
S4's, and the layer family that regenerates its vectors through the emitter
(`tb_layer_chan`, `tb_layer_env`) is **re-run at S3**.

Labels are the migration spec §0's: **M** measured off the tree, **S**
structural, **D** derived, **T** measured in a tool.

---

## 1. What landed

| step | where | what |
|---|---|---|
| 1 | `tb/axi_ram_bfm.sv`, `tb/tb_layer_sdma.sv` | a RAM-backed 512-bit AXI4 slave and the directed gate, **RED first** (§7.1) |
| 2 | `rtl/state_dma.sv` (391 lines) | the transfer engine (§3) |
| 3 | `rtl/layer_chan.sv` | the caches, the lanes, the fences, the tags, the CSRs, the errors (§4, §5) |
| 3 | `rtl/attn_core.sv` | `T <= 4096` in all four places (§6) |
| 3 | `rtl/layer_chan_ipi.v`, `synth/scripts/create_project.tcl` | the `m_axis` bundle, the third SmartConnect port and its address pinning (§8) |
| 4 | `tb/Makefile:472-529` | `SDMA_SEEDS`, `tb_layer_sdma`, `tb_layer_sdma_nofence`, `lint_state_dma`, `lint_layer_chan`; `LAYER_RTL` gains `rtl/state_dma.sv` |
| fix | `tb/tb_attn_core.sv`, `tb/tb_layershim_c.sv` | two shipped unit gates S2's port/width changes broke, repaired (§9.3) |
| fix round 1 | `rtl/layer_chan.sv`, `rtl/state_dma.sv`, `rtl/layer_chan_ipi.v`, `tb/axi_ram_bfm.sv`, `tb/tb_layer_sdma.sv`, `docs/SEQ_ISA.md`, `synth/scripts/ooc_9b.tcl` | F2's stall-release hole, `kvhead_r`, the sticky code, the BFM seed, and eight minors (§12) |

Commits: `d15c52b` (step 1, RED), `ebcb056` (steps 2-3), `baa1db4` (the
wrapper and the block design), `eb245e6` (the queue-full hold and the two
testbench repairs), `8b93b6e` (one stale comment), `f1f897f` + `3b979a3` (the
round-1 gate doc and evidence), then fix round 1: `02db396` (the C1 RED) and
`a69fe1f` (the fixes). **The final evidence set is
`evidence/qwen9b/s2/016`-`024`, all on `a69fe1f`**; `001`-`015` are the
step-by-step record on the trees they name in their own headers.

---

## 2. The interface `state_dma` presents (S, from the plan's port list)

`rtl/state_dma.sv:42-71` is the port list as landed, verbatim from the brief:
one transfer at a time driven by `xfer_go`/`xfer_store`/`xfer_kind`/
`xfer_addr`/`xfer_rows`, answered by `xfer_busy`/`xfer_done`/`xfer_err`; a
slot side of `slot_addr`/`slot_wdata`/`slot_wexp`/`slot_we`/`slot_wexp_we`
into the slot and `slot_rdata`/`slot_rexp` back; and a 512-bit AXI4 master
`m_axis`. `MAX_OUT` is 8 bursts in flight and `FIFO_D` is 256 beats, as
`ddr_rd_streamer` sizes its own.

`AWSIZE`/`ARSIZE`, `AWBURST`/`ARBURST` and `AWID`/`ARID` are **not ports of
the core**: they are tied constant one level up, in `rtl/layer_chan_ipi.v:200-205`,
so the engine cannot drift out of step with the constants the fabric sees.

---

## 3. `rtl/state_dma.sv` — the transfer (M unless noted)

| what | where |
|---|---|
| the block sizes, the KV two-phase rule and the alignment argument | `rtl/state_dma.sv:1-37` |
| `KV_EXP_OFF`, the 1 MiB offset of the exponent side array | `rtl/state_dma.sv:74` |
| burst issue and retirement — one `a_out` update so an issue and a response in the same cycle cannot lose the increment | `rtl/state_dma.sv:227-246` |
| the beat FIFO, shared by both directions | `rtl/state_dma.sv:121-130` |
| LOAD: four beats into one 2048-bit row; one beat into four 16-B conv rows; one beat into 64 exponent bytes | `rtl/state_dma.sv:252-300` |
| STORE: the slot read pipeline (three edges of lead), the beat accumulator, the W channel | `rtl/state_dma.sv:302-360` |
| the `bw_idle` completion rule for a store | `rtl/state_dma.sv:355-359` |
| a zero-row transfer completes at once (B15.1) | `rtl/state_dma.sv:221-225` |
| phase advance: KV rows, then the exponent array | `rtl/state_dma.sv:362-386` |

**Two design decisions the brief left open.**

*The store's slot reads.* For DN and KV the engine reads the **same row four
times**, once per beat, and selects the beat's own 512-bit slice
(`rtl/state_dma.sv:323-328`). That costs nothing on a two-port URAM whose
other port is idle, and it removes an accumulator and its bypass hazard from
the store path entirely. Conv and the exponent array do accumulate, because
there four (or sixty-four) rows share one beat.

*The W burst boundary.* Bursts are 16 beats aligned to the phase start, so
`WLAST` is a function of the beat counter alone
(`rtl/state_dma.sv:132-142`) — no burst-length queue between the AW issuer
and the W engine, and no way for the two to disagree.

`lint_state_dma` is clean at `-Wall --timing`
(`evidence/qwen9b/s2/008_units_and_lints.log`, §7.3).

---

## 4. The caches and their ownership muxes (spec §3, A1.2)

| kind | geometry | where |
|---|---|---|
| DN | `N_SLOT` slots of 4096 x 2048 b, addressed `{head[4:0], row[6:0]}` — 29 URAM each (S) | `rtl/layer_chan.sv:738-776` |
| KV | `N_SLOT` slots of 8192 x 2048 b addressed `{kv, t[11:0]}`, plus one 8192 x 8 b exponent memory per slot | `rtl/layer_chan.sv:804-848` |
| conv | `N_SLOT` slots of 8192 x 64 b weights **and** 8192 x 48 b state, kept separate so CONV's and CONVZ's state-only writes are unchanged | `rtl/layer_chan.sv:851-903` |

`N_SLOT` is 2 (`rtl/layer_chan.sv:382`).

### 4.1 The muxes are per (kind, SLOT), not per kind

This is the one place where the first implementation was **wrong and the
testbench caught it**. A per-kind mux — the reading the brief's phrase "the
compute side of every mux is exactly today's signal" also admits — hijacks
the *idle* slot's read address and select whenever the DMA owns the *other*
slot of that kind. B15.5 explicitly allows exactly that overlap ("a transfer
on one slot of a kind may be in flight while a compute command holds the
OTHER slot"), so the per-kind form corrupts a legal program. `tc_f2_other_slot`
(`tb/tb_layer_sdma.sv:840-862`) failed on it; the per-slot form is at
`rtl/layer_chan.sv:725-733` (the selects) and inside each generate block:
`rtl/layer_chan.sv:758-765`, `rtl/layer_chan.sv:821-829`,
`rtl/layer_chan.sv:874-884`.

The compute leg of every mux is exactly the pre-S2 signal. The DMA's read
**return** is its own output register per kind (`rtl/layer_chan.sv:771-776`
for DN, `rtl/layer_chan.sv:839-848` for KV, and `cw_q_p`/`cs_q_p` indexed by
`dma_slot` for conv, `rtl/layer_chan.sv:906-915`), so nothing the DMA does
reaches a compute unit's read path at all. The 3:1 select that picks the
kind for `slot_rdata` is off the compute path and stable for a whole
transfer; S5 measures it.

### 4.2 `dn_step` sees `RLAT = 2` again

The DN slot is one URAM read plus layer_chan's output register, so the
instantiation goes back to the pair that was always legal at latency 2:
`rtl/layer_chan.sv:626`. `rtl/dn_step.sv` is **byte-identical to `a51bc8e`**
(`git diff a51bc8e -- rtl/dn_step.sv` is empty).

**Cycle cost (T).** `tb_dn_step` at that pair reports
`DN_CYCLES RLAT=2 P2W=0 cycles_per_head=1798`, four seeds, bit-exact against
the same committed goldens (`evidence/qwen9b/s2/008_units_and_lints.log`).
G3.4 shipped 1930 cycles/head at read latency 6 with the pass-2 wait
state (`evidence/qwen9b/g3/G3_4_LAYER.md:194-195`, label T), so retiring the
pipelined SLR crossing **gives back 132 cycles per head, −6.84 %**, and with
it the `+128` pass-2 wait state and the `+4` `P1_PRE` entry cost that G3.4
priced.

---

## 5. The two lanes, the two fences, the CSRs

### 5.1 The DMA lane

`rtl/layer_chan.sv:2035-2072` declares it and `rtl/layer_chan.sv:2074-2150`
is its FSM: a four-entry in-order queue of `{store, kind, slot, layer, head}`,
one transfer in flight, `warm`/`kv_tag`/`sld_pend` per slot. The head entry's
address is B15.1's adder, applied with the three `SDMA_BITS: SHIFT_*`
localparams so the census reads the shift the hardware actually uses
(`rtl/layer_chan.sv:2060-2070`).

`busy_dma` is `dma_act | ~dq_empty` (`rtl/layer_chan.sv:2072`).

### 5.2 F1 — a compute command waits for the DMA on its slot

`rtl/layer_chan.sv:1344-1361`. A compute command stalls at dispatch while an
**SLD is queued or in flight** on its slot (spec §5.4 verbatim) **and** while
**any** transfer is in flight on its slot. The second clause is not in §5.4's
words and it is load-bearing: ownership is exclusive, so a compute command
overlapping an in-flight *store* on its own slot would tear the store and
read the DMA's addresses. A **queued** store does not stall compute — F2
holds that store instead, which is what keeps the second fence reachable
(§5.3).

The stall holds the command in `IDLE` with `busy_cmp` high and `cmd_pend` set
(`rtl/layer_chan.sv:1474-1480`): `busy_cmp` closes the CMD accept gate so the
ARG words cannot be rewritten under the waiting command, and LCYC counts the
stall, so any fence cost is visible in the layer-term census (spec §8.5).
`cmd_pend` is what keeps the command from *holding* its slot while it waits,
which is why F1 and F2 cannot deadlock against each other
(`cmp_holds = busy_cmp && !cmd_pend`, `rtl/layer_chan.sv:2067`).

`E_DMA_COLD` (`rtl/layer_chan.sv:1358-1361`) refuses a compute command on a
slot with no completed load since its last store. DNZ and CONVW sel 2 are
exempt — they write the slot and warm it (`rtl/layer_chan.sv:1341-1342`,
`rtl/layer_chan.sv:1512-1524`).

### 5.3 F2 — a transfer waits for the compute lane

`rtl/layer_chan.sv:2086-2095`. The transfer at the head of the queue waits
while a compute command **holds** its slot (`cmp_holds`,
`rtl/layer_chan.sv:2067`) **or claims it this cycle** (`cmp_claim`,
`rtl/layer_chan.sv:2079-2080`).

**The claim term is fix round 1's Critical (C1).** `cmp_holds` and the F1
stall condition are registered in *different* `always_ff` blocks, so on the
cycle F1 RELEASES a stalled compute command the DMA lane still read
`cmd_pend = 1`, concluded that nothing held the slot, and started the queued
transfer on that very slot — the dispatcher's third arm and the pop firing
together. `cmp_claim` is the third arm's own condition as a combinational
wire, with the slot taken from the **live** `layer_*` fields because
`*_slot_r` has not latched yet. It cannot deadlock: it is false while F1
stalls (so the queue still drains) and true only in the cycle a command
dispatches, and a dispatched command always terminates. The RED that found
it and the GREEN that closes it are §7.2's case 12.

**When F2 is reachable, and why the brief's shape for its test is not.** A1.4
fixes the CMD accept gate at `busy_cmp` (`rtl/layer_chan.sv:1063`) and
every command's ARG words must stay stable for its whole duration, so an
SLD/SST can only be *issued* while the compute lane is idle: the brief's
"DNST on slot 0, then SLD into slot 0" cannot be driven through the CSR
interface at all. What is reachable is a transfer that reaches the head of
the queue while a compute command is already running on its slot — a long DN
load ahead of it and a compute command started in between. `tc_f2_hold`
(`tb/tb_layer_sdma.sv:778-801`) builds exactly that, and counts the cycles F2
**actually held** the queued SST so the case cannot pass vacuously: **21,202
cycles** at seed 4 (`evidence/qwen9b/s2/006_tb_layer_sdma_green.log`).

### 5.4 `busy_cmp` / `busy_any` and the queue-full hold (spec A1.4)

`busy_cmp` (`rtl/layer_chan.sv:454`) is the compute lane's busy: the CMD
accept gate (`rtl/layer_chan.sv:1063`), LCYC's source
(`rtl/layer_chan.sv:1048`), the scratch-mux priority bit
(`rtl/layer_chan.sv:2208-2222`) and the burst shim's `core_busy`
(`rtl/layer_chan.sv:2183`). STATUS bit 0 is `busy_cmp | busy_dma`
(`rtl/layer_chan.sv:1138-1139`). `SDMA_CYC` counts `busy_dma`
(`rtl/layer_chan.sv:1049`).

**A hole the brief did not name, closed here.** The queue is four deep and
the accept gate is `busy_cmp`, so five SLD/SST records issued faster than one
transfer completes would have been *silently dropped* — the standing hazard
the plan names for CMD writes, in a new place. `rtl/layer_chan.sv:1441-1449`
**holds** the record at dispatch instead. `cmd_pend` keeps `cmp_holds` low
while it waits, so F2 still drains the queue and the hold cannot deadlock.
`tc_warm_and_busy` issues six SLDs, requires all six to retire, and requires
the hold to have **actually fired**: 19,691 cycles
(`tb/tb_layer_sdma.sv:1069-1089`).

### 5.5 The CSRs and the error codes

| CSR | write | read |
|---|---|---|
| `SB_DN` / `SB_KV` / `SB_CV` (word `0x19..0x1B`) | `rtl/layer_chan.sv:1105-1107` | `rtl/layer_chan.sv:1159-1161` |
| `SDMA` (word `0x1C`) | clears err — `rtl/layer_chan.sv:1108` | the B15.3 status word — `rtl/layer_chan.sv:1163-1164` |
| `SDMA_CYC` (word `0x1D`) | any write clears — `rtl/layer_chan.sv:1109` | `rtl/layer_chan.sv:1165` |
| `LAYER` (word `0x0C`), four fields | `rtl/layer_chan.sv:1093-1104` | `rtl/layer_chan.sv:1156-1158` |
| `TCNT` / `TCNT2`, 13 bits, indexed by `kv_layer` | `rtl/layer_chan.sv:1077-1088` | `rtl/layer_chan.sv:1149-1155` |

`err_op` stays the single STATUS bit and `sdma_err` carries B15.4's code
(`rtl/layer_chan.sv:454-455`). A **later refusal sets `err_op` but does not
overwrite a standing `E_DMA_AXI`** (fix round 1, I4:
`rtl/layer_chan.sv:1468-1477`, `rtl/layer_chan.sv:1528-1545`) — the sticky
code survives until the host writes SDMA, which is what B15.4 promises and
what `seq_unit` needs in order to halt on the real cause. The clear at dispatch is suppressed while the
code is `E_DMA_AXI` (`rtl/layer_chan.sv:1458`,
`rtl/layer_chan.sv:1485`), and the write to `SDMA` plus the DMA lane's
completion error are applied last, so they win over that clear
(`rtl/layer_chan.sv:2019-2030`).

Refusal order at a compute command's dispatch, one code each:
`E_LAYER` → `E_ENV` → `E_DMA_RANGE` → `E_DMA_COLD`
(`rtl/layer_chan.sv:1512-1524`). `cmd_env_bad` keeps its VN/VNW/CONV/CONVW
terms and loses the `layer_dn > N_DN-1` term, which a one-bit slot makes dead
(`rtl/layer_chan.sv:1305-1325`). `E_DMA_RANGE` on a compute command is CONVW
sel 0/1 (retired, spec §5.5) and a KVAP/ATTN kvhead that disagrees with the
slot's tag (`rtl/layer_chan.sv:1363-1373`). An SLD/SST's own envelope is
`rtl/layer_chan.sv:1375-1388`.

### 5.6 The slot tags (spec A1.3)

Each KV slot carries `{layer[2:0], kvhead[1:0]}` latched by the SLD that
filled it (`rtl/layer_chan.sv:2130-2139`). ATTN's `cfg_t`
(`rtl/layer_chan.sv:1598-1603`), KVAP's append address
(`rtl/layer_chan.sv:1976-1985`) and the `tcnt_inc` increment
(`rtl/layer_chan.sv:1128-1132`) all index the 8 x 4 append-counter array
through that tag (`rtl/layer_chan.sv:465`).
The KVAP write address is `{kv, t[11:0]}` into the slot — the kvhead is no
longer an address field anywhere.

The command's own kvhead field is latched at dispatch as before S2
(`rtl/layer_chan.sv:1514`, the line `evidence/qwen9b/g3/isa_bits.py` anchors;
fix round 1, I1) and it is **load-bearing**: the append counters are indexed
through it (`rtl/layer_chan.sv:1138`, `rtl/layer_chan.sv:2002`), and a
simulation check at the point of USE requires it to equal the slot tag's
kvhead (`rtl/layer_chan.sv:2281-2287`) — an equality that
`cmd_range_bad`'s refusal is precisely what guarantees.

---

## 6. `attn_core` at `T <= 4096` (spec A1.5)

All four homes move together, and nothing else moves:
`rtl/attn_core.sv:13` (the contract line), `rtl/attn_core.sv:37` and
`rtl/attn_core.sv:45` (`cfg_t`, `kv_addr` to 13 bits),
`rtl/attn_core.sv:76-78` (`sc_mem`/`es_mem` 4,096 deep with
`ram_style = "block"`, 4 RAMB36 each — S5 records them), and
`rtl/attn_core.sv:112` (`t, T`) with every compare and every `t[11:0]` slice.

`git diff a51bc8e -- rtl/attn_core.sv` contains **no arithmetic line**: it is
widths, memory depths, index slices and the header. The direct evidence is
`tb_attn_core`, whose golden is unchanged: 4 seeds, 256 outputs bit-exact
(`evidence/qwen9b/s2/008_units_and_lints.log`).

---

## 7. Evidence

Every log is under `evidence/qwen9b/s2/`, produced through
`evidence/qwen9b/run.sh`. Logs `001`-`015` are the step-by-step record on the
trees they name; **`016`-`024` are the final set, all on `a69fe1f`, clean**
(`024` on the commit that carries this document).

### 7.1 RED first (step 1)

| log | what it records |
|---|---|
| `evidence/qwen9b/s2/001_tb_layer_sdma_red.log` | the build fails: `rtl/state_dma.sv` does not exist |
| `evidence/qwen9b/s2/002_tb_layer_sdma_red_ports.log` | the same TB linted against the pre-S2 `layer_chan`: 31 errors — every `m_axis_*` pin not found, and no `busy_cmp`, `busy_dma`, `u_dma` or `SDMA_NOFENCE` |

The RED is **structural**, not a broken testbench: the same file is GREEN in
§7.2 once the RTL lands.

### 7.2 The directed gate, GREEN and its RED control

| log | command | verdict |
|---|---|---|
| `evidence/qwen9b/s2/016_tb_layer_sdma_green.log` | `make -C tb tb_layer_sdma SDMA_SEEDS='1 2 3 4'` | `TB_LAYER_SDMA PASS: 240 checks, seed N` for N = 1..4, rc 0 |
| `evidence/qwen9b/s2/017_tb_layer_sdma_nofence_red.log` | `make -C tb tb_layer_sdma_nofence SDMA_SEEDS='1 2 3 4'` | the `-GSDMA_NOFENCE=1` build FAILS `f1_stall` on all four seeds; the target reports `OK: the F1 bypass reads stale state and FAILS` x 4, rc 0 |

The four seeds really are four runs: `axi_ram_bfm` reads `+seed` and prints
the seed it is using at time 0 (fix round 1, I2), and the two fence counters
differ per seed — F2 held the queued SST for 21,213 / 21,248 / 21,282 /
21,300 cycles and the full queue held a record for 19,589 / 19,635 / 19,677 /
19,712 cycles. Before I2 the BFM ignored `+seed` and all four shared one
handshake pattern.

The RED control fires on exactly one check — case 4's compare against the
LOADED result — and reports `matched the LOADED result on 0 of 128 outputs`.

**The twelve cases**, all in `tb/tb_layer_sdma.sv`. The ownership invariant
— while a compute command is EXECUTING the DMA must never own the slot it
holds — is monitored for the **whole run and all three kinds**
(`tb/tb_layer_sdma.sv:179`, `tb/tb_layer_sdma.sv:207-219`), checked inside
cases 4 and 12 and again at the end of the run; before fix round 1 it was
armed only for DN and only inside case 4, which is how C1 survived.

| # | case | where | what it proves |
|---|---|---|---|
| 1 | `dn_roundtrip` | `tb/tb_layer_sdma.sv:507-571` | a 1 MiB DN block DDR → slot → DDR byte for byte (1024 AR bursts, 16384 R beats); then the same DNST on a head zeroed **by the DMA** and on one zeroed **by DNZ** gives identical outputs and identical stored state over all 4096 rows, while the LOADED state gives a different result |
| 2 | `kv_roundtrip` | `tb/tb_layer_sdma.sv:596-679` | T ∈ {0, 1, 1023, 4096}, K and V, rows **and** the exponent side array; at T = 0 no AXI transaction at all and `SDMA_CYC` < 200, and the slot's warmth is proved by ACCEPTANCE — a KVAP and then an ATTN on the tag's own kvhead RUN — before the tag refusal, so the tag check cannot mask a cold slot (fix round 1, M8: `tb/tb_layer_sdma.sv:641-667`) |
| 3 | `cv_roundtrip` | `tb/tb_layer_sdma.sv:682-709` | the 16-B conv row split across the weight and state memories and reassembled, 2048 beats |
| 4 | `f1_stall` | `tb/tb_layer_sdma.sv:712-734` | a DNST issued while its slot's SLD is in flight reads the LOADED state; the compute lane never executes while the DMA owns its slot |
| 5 | `f1_cold` | `tb/tb_layer_sdma.sv:737-763` | `E_DMA_COLD` on a slot with no completed load, in under 200 LCYC cycles (no unit started) — on **DNST, ATTN and CONV** (fix round 1, M8: `tb/tb_layer_sdma.sv:750-761`); the ATTN case names the kvhead the reset tag also carries, so the tag check cannot mask the cold refusal |
| 6 | `f2_hold` | `tb/tb_layer_sdma.sv:778-801` | an SST queued behind a long SLD, with a CONV holding its slot, does not start until the CONV ends — F2 held it 21,202 cycles at seed 4 in `evidence/qwen9b/s2/006_tb_layer_sdma_green.log` (§5.3). §10's 21,213 / 21,248 / 21,282 / 21,300 are the four seeds of the GATE run, `evidence/qwen9b/s2/016_tb_layer_sdma_green.log`: two runs, two logs, and each number now names its own |
| 7 | `f2_order` | `tb/tb_layer_sdma.sv:865-888` | SST then SLD of one slot: no read address is issued with a write response outstanding, and the slot round-trips through the store queued ahead of it |
| 8 | `f2_other_slot` | `tb/tb_layer_sdma.sv:840-862` | a DN slot-1 load in flight while a slot-0 DNST runs: 2,958 overlapping cycles, the DNST bit-identical to the un-overlapped one, and the concurrent load lands correctly in all 4096 rows |
| 9 | `last_blocks` | `tb/tb_layer_sdma.sv:891-931` | DN L23, KV L7 kvhead 3 V, CV L23 — each transfer's observed address span equals the computed block, and the last conv block ends exactly at `plan_state()`'s `end` |
| 10 | `e_base` / `e_range` / `e_layer` / `e_env` / `e_axi` | `tb/tb_layer_sdma.sv:934-1014` | every code on its own cause: `0x10`; `0x11` seven ways (kind 3, DN head 1, KV layer 8, CV head 1, arg1, arg2, TCNT 4097); `0x02`; `0x01`; `0x12` raised at completion, **sticky across the next compute dispatch AND across a later refusal** (fix round 1, I4: `tb/tb_layer_sdma.sv:1003-1013`), cleared by a write to SDMA |
| 12 | `f2_release` | `tb/tb_layer_sdma.sv:820-837` | **the C1 case**: queue `[SLD DN s0, SST DN s0]` and a DNST on DN s0, which F1 stalls and then releases in the cycle the SST reaches the head. RED against `3b979a3` (`evidence/qwen9b/s2/015_f2_release_red.log`: the DMA owned DN slot 0 on **2,958 cycles** while the released DNST ran), GREEN after |  <!--cites:noquote-->

> **CLASS B, dated note 2026-09-10.** Case 12's quotation of the queue —
> `[SLD DN s0, SST DN s0]` — is of the testbench as it stood when this row
> was written, and **that text no longer exists**: the C1 fix round rewrote
> the case's header comment, which now reads
> *"Queue = [SLD DN s0 (long), SST DN s0]"*. The post-fix landmark is
> `tb/tb_layer_sdma.sv:810`, in the comment block above `tc_f2_release`,
> which the cited range still opens at `tb/tb_layer_sdma.sv:820`. The row keeps its own words as the record of what it
> measured, under the campaign's rule that an exemption is for source
> that no longer exists rather than for a citation that has merely moved.
| 11 | `dnz_warms` / `convz_warms` / `busy_any` / queue depth | `tb/tb_layer_sdma.sv:1017-1090` | DNZ and CONVZ warm a cold slot; CONVW sel 0/1 refused `0x11`; STATUS bit 0 high during an SLD while the accept gate still takes the next one; `SDMA_CYC` counts and clears; six queued SLDs all retire and the queue-full hold fires |

### 7.3 The units and the lints

`evidence/qwen9b/s2/018_units_and_lints.log`,
`FABLE5_MODEL=9b FABLE5_RS_F=7`, rc 0, **zero `%Warning` and zero `%Error`**:

| target | marker | count |
|---|---|---|
| `tb_dn_step` | `TB_DN_STEP PASS` and `DN_CYCLES RLAT=2 P2W=0 cycles_per_head=1798` | 4 |
| `tb_gate_unit` | `TB_GATE_UNIT PASS` | 4 |
| `tb_conv4_silu` | `TB_CONV4_SILU PASS` | 4 |
| `tb_attn_core` | `TB_ATTN_CORE PASS` | 4 |
| `tb_layershim_c` | `TB_LAYERSHIM_C PASS` | 4 |
| `tb_seq` | `SEQ PASS` (4 seeds + 9 error paths + 6 micros + 6 directed) | 25 |
| `tb_seq_guard` | `SEQ PASS` x 2 and `OK: illegal EMBLOG2 write is loud in simulation` | 1 |
| `lint_layer_chan`, `lint_state_dma`, `lint_layershim_c`, `lint_seq_unit` | no output | — |

Beside them, `evidence/qwen9b/s2/019_isa_bits_green.log`: **`ISA_BITS: PASS`**.
G3's ARG-encoding census anchors `kvhead_r <= (.+?);`, which S2's first round
had deleted, so the instrument could not run at all; fix round 1's I1 restores
the latch and the census with it.

`tb_layer_chan` and `tb_layer_env` are **not** run here: S3 regenerates their
vectors (§9.1).

### 7.4 The census and its controls

| log | command | verdict |
|---|---|---|
| `evidence/qwen9b/s2/020_sdma_bits_green.log` | `python3 evidence/qwen9b/s1/sdma_bits.py` | `SDMA_BITS: PASS` |
| `evidence/qwen9b/s2/021_sdma_bits_control.log` | `python3 evidence/qwen9b/s1/sdma_bits.py --control` | `SDMA_CONTROL: PASS (the gate holds and every perturbation is CAUGHT)` |

The census prints no RTL path on PASS, so the citation is the command line
recorded in each log's `=== cmd:` header: neither run sets `SDMA_BITS_RTL`,
so the RTL half is `rtl/layer_chan.sv` on the committed tree (`=== tree:
a69fe1f`). Fix round 1 amended B15.1's TCNT sentence and added two sentences
to B15.4 (§12); the census parses numbers, not prose, and is still GREEN with
every perturbation CAUGHT. All six perturbations are CAUGHT, including the three that need
the RTL half: `rtl` (OP_SLD → 12), `rtl-shift` (`SDMA_SHIFT_KV` → 20) and
`rtl-layer` (the LAYER `kv_layer` field moved to `[10:4]`).

The eighteen anchors are copied verbatim from S1's fixture
(`evidence/qwen9b/s1/s2_contract_stub.sv`) into `rtl/layer_chan.sv:402-437`.

### 7.5 The retired-code sweep

`evidence/qwen9b/s2/022_retired_sweep.log`, rc 0. **Eight hits outside the
gitignored `tb/obj_dir_*` build copies, every one a comment** — which is what
the brief asked for — and no hit at all on `g_dnpipe` or `g_cv[`:

| hit | disposition |
|---|---|
| `rtl/layer_chan.sv:377`, `rtl/layer_chan.sv:741` | the S2 **retirement comments**, which name what went and why |
| `rtl/dn_step.sv:22` | a header comment explaining why `RLAT` is a parameter. `rtl/dn_step.sv` is an **invariant** of this task and is byte-identical to `a51bc8e`; the comment is history, not a live dependency |
| `tb/tb_dn_step.sv:6`, `:9`, `:53` | the same history in the TB that models the latency. `RLAT=2 P2W=0` is the configuration that now ships and is the target S2 runs |
| `synth/scripts/ooc_9b.tcl:21-27` | the usage comment, rewritten as a retirement note. Fix round 1 (M2) **removed the code**: there is no `-generic` left to append (`synth/scripts/ooc_9b.tcl:132`), and passing the retired third `tclarg` is now a hard error (`synth/scripts/ooc_9b.tcl:39-43`) rather than a generic Vivado would refuse deep inside `synth_design`. S5 keeps the rest of its edits to this file |

### 7.6 Citation drift

`evidence/qwen9b/s2/012_cite_drift_plan.log` (`--plan`, run **before** any
`--fix`, on the round-1 tree) and
`evidence/qwen9b/s2/023_cite_drift_check.log` (`--check`, on `a69fe1f`, over
all twelve files S2 has now edited):

```
O3_FIX_PLAN: UNSAFE — 11 of 285 rewrites would move a citation that is
already correct; repair the 274 stale one(s) BY HAND or --exclude the document
O3_CITE_DRIFT CHECK FAIL (237 drifted, 89 unresolved, 0 missing, 19 half-mapped)
```

**S2 runs no `--fix`, and that is a decision, not an omission.** Three
reasons, in order of weight:

1. **Ninety-one of the citations name lines that no longer exist.** The
   sweep's own examples, in PRE-S2 coordinates that this document
   deliberately does not write as citations: layer_chan line 210 was the
   `DN_PIPE` parameter, 337 was `DN_P2WAIT`, 322 was `KV_AW`, and attn_core
   line 69 was the 512-deep `sc_mem`. `--fix` never rewrites an
   unresolved line, and eighteen more tokens are half-mapped ranges it
   refuses whole. Renumbering the survivors around them would leave
   documents whose prose describes the 24-bank arrays pointing at cache-slot
   code — a citation that is *worse* than a stale one, and the failure mode
   `evidence/qwen9b/o3/o3_cite_drift.py`'s own header records ("both were rewritten OUT of
   citation form rather than maintained, because the code they name no longer
   exists").
2. **The pass is UNSAFE as a whole** (11 collateral rewrites), so the tool
   refuses it, and the safe subset would still be the renumbering of (1).
3. **The documents are not S2's to commit.** The plan's Global Constraints
   make every commit path-limited to the files the task names, and the 40
   citing documents belong to other tasks and closed gates —
   `evidence/qwen9b/g3/G3_4_LAYER.md` (53 citations),
   `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md` (43),
   `evidence/qwen9b/s1/S1_ISA.md` (1, S1's own).

One more tidy-up for S3, from the same class: `evidence/qwen_next/spec_cites.py`
still lists `rtl/state_dma.sv`, `tb/axi_ram_bfm.sv`, `tb/tb_layer_sdma.sv` and
S2's first evidence log as PENDING ("a future gate creates this"). They exist
now. PENDING does not fail the checker, and that file is not in S2's pathspec.

**Handed to S3's Step 5′**, with the two logs as the worklist: 237 drifted,
89 unresolved, 19 half-mapped, across the 40 documents `012` names. §7.5's
`synth/scripts/ooc_9b.tcl` action is CLOSED (fix round 1, M2). The one citation inside S2's own pathspec was
layer_chan's claim, then at line 335, that this file's geometry block is identical
to Track P's frozen experiment copy; that claim is now false and was
**withdrawn** rather than renumbered (`rtl/layer_chan.sv:331-347`).

---

## 8. The wrapper, the block design and the address map

`rtl/layer_chan_ipi.v:122-196` is the `m_axis` bundle with its
`X_INTERFACE_PARAMETER` (AXI4, 512-bit data, 34-bit address, ID width 1,
`MAX_BURST_LENGTH 16`), and `rtl/layer_chan_ipi.v:200-205` are the constant
ties. `BID`/`RID` are unread: the master issues a single ID, so responses are
in order by construction.

`synth/scripts/create_project.tcl:218-224` takes `axi_smc` to `NUM_SI {3}`;
`synth/scripts/create_project.tcl:323-328` connects `layer_0/m_axis` to
`axi_smc/S02_AXI` (the cell is created before this point and both are on
`xdma_0/axi_aclk`, which is already `axi_smc/aclk`, so no clock conversion
and no CDC); `synth/scripts/create_project.tcl:462-469` pins the four 4 GiB
`ddr4_$i` segments in the identical form `seq_0/m_axi` uses at
`synth/scripts/create_project.tcl:455-461`. Without that pinning the 34-bit
addresses the `SB_*` CSRs carry do not decode and every transfer would answer
DECERR.

**S2 runs no Vivado** — S5 does. This block was read twice against the
`seq_0/m_axi` form and is unexercised evidence until then (label S).

---

## 9. What S2 leaves for the tasks after it

### 9.1 S3 — the emitter, and the two layer-family testbenches

`tb/tb_layer_chan.sv` and `tb/tb_seq_chip.sv` instantiate `layer_chan` and
therefore **do not build on this tree**: both need the `m_axis` bundle
connected. Both are **S3's files** by the plan's own file table
(`docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md:61`), and S3's
step already says `u_layer.m_axis` connects to the chip TB's DDR model
(`docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md:416`). S2 did
not touch them: committing another task's file is exactly what the Global
Constraints forbid.

S3 also owns the emitter half the brief listed under S2's Files and its own
Step 3 then withdrew ("No emitter edit in S2"): `_DN_SLOTS`/`_KV_SLOTS`/
`_CV_SLOTS`, `layer()`'s four fields, the `convw` shim, `sld()`/`sst()` and
the schedule. `ref/gen_layer_script.py` is unchanged on this tree — and
therefore still prints the **v2.0** LAYER word, whose `dn_slot[4:0]` field
this RTL now decodes as `{kv_layer[10:8], …, dn_slot[1:0]}`. **Any stream
regenerated between S2 and S3 is mis-encoded and must not be trusted**, and
`tb_layer_chan` and `tb_seq_chip` do not build at all until S3 connects
`u_layer.m_axis`. Re-basing both is S3's first job.

### 9.2 S5 — what it measures, and one edit it needs

* the URAM/BRAM/DSP census on the new `rtl/` (expect DN 2 x 29 + KV 2 x 29 +
  conv 2 x 4, label S until measured);
* the DN and KV **write fan-out** through the new ownership muxes — spec A1.2
  WITHDREW §3's "no timing change on the compute side" and S5 measures it
  rather than assuming it;
* `attn_core`'s two score-class memories at 4,096 deep (4 RAMB36 each);
* the `synth/scripts/ooc_9b.tcl` `dn_pipe` argument (§7.5).

### 9.3 Deviations from the brief, and why

| the brief says | what landed | why |
|---|---|---|
| case 1 compares the DNST "against the same DNST run on the committed `tb_layer_chan` DNST vectors" | the DNST stimulus **is** those vectors, but the golden is the DMA-vs-DNZ cross-path equality plus differential sensitivity | `tb/vectors/*/dn_v.hex` is Q.S_F (`ref/gen_layer_vectors.py:135`), while the DNST command transports `v` as Q.QKV_F and shifts it left by 5 — the two live in different fixed-point domains, so `dn_o.hex` is not reachable through the layer command. `dn_step`'s arithmetic is gated bit-exactly by `tb_dn_step` anyway; what case 1 has to prove is that `dn_step` reads exactly the rows the DMA wrote, and it does that without a reference model. The controller's fix-round-1 ruling: ACCEPTED as S2's evidence, and the **value-level oracle for DNST-on-loaded-data is S3's SEQ gate**, bit-exact against `seq_model` |
| case 5: "`cmd_cnt` unchanged (refused before the doorbell)" | `cmd_cnt` **advances** on `E_DMA_COLD`, as on every other refusal in this file | `rtl/layer_chan.sv:1297` states the contract a refusal has always kept — "cmd_cnt still advances so a polling host is not hung" — and `seq_unit` halts on `err_op` only after it sees `cmd_cnt` increment. A refusal that does not advance it hangs the program instead of halting it. The case checks the err_op bit, the SDMA error byte reading 0x13, and that no unit started (under 200 LCYC cycles) |
| case 6: "DNST on slot 0 (long) then SLD into slot 0" | an SST queued behind a long SLD, with a CONV holding the SST's slot | unreachable as written: A1.4's accept gate plus ARG stability mean no SLD/SST can be issued while a compute command runs (§5.3) |
| case 4: "assert the DNST's `busy_cmp` rises only after `busy_dma` falls" | assert `st` leaves IDLE only after the DMA releases the slot | the fence stalls the command with `busy_cmp` already high — that is what closes the accept gate and makes LCYC count the stall (§5.2) |
| Files list `ref/gen_layer_script.py` | unchanged | the brief's own Step 3 says "No emitter edit in S2" and the commit block does not name it (§9.1) |
| Files list does not name `tb/tb_attn_core.sv`, `tb/tb_layershim_c.sv` | both edited | S2's port and width changes broke them, no task in the plan owns either, and both are shipped unit gates. `tb_attn_core` is also the direct evidence that the A1.5 widening changed no arithmetic (§6) |

---

## 10. The claims this document makes, and where each number comes from

| claim | label | source |
|---|---|---|
| 240 checks x 4 seeds GREEN | M | `evidence/qwen9b/s2/016_tb_layer_sdma_green.log` |
| the fence bypass FAILS x 4 seeds | M | `evidence/qwen9b/s2/017_tb_layer_sdma_nofence_red.log` |
| the C1 hole: 2,958 cycles of wrong ownership | M | `evidence/qwen9b/s2/015_f2_release_red.log` (on `3b979a3`) |
| F2 held a queued SST 21,213 / 21,248 / 21,282 / 21,300 cycles | M | `evidence/qwen9b/s2/016_tb_layer_sdma_green.log` |
| the lanes overlapped 2,958 cycles | M | `evidence/qwen9b/s2/016_tb_layer_sdma_green.log` |
| the queue-full hold fired 19,589 / 19,635 / 19,677 / 19,712 cycles | M | `evidence/qwen9b/s2/016_tb_layer_sdma_green.log` |
| DNST 1798 cycles/head at `RLAT = 2` | T | `evidence/qwen9b/s2/018_units_and_lints.log` |
| G3.4's 1930 cycles/head, at read latency 6 with the pass-2 wait state | T | `evidence/qwen9b/g3/G3_4_LAYER.md:194-195` |
| zero `%Warning` across every unit and lint | M | `evidence/qwen9b/s2/018_units_and_lints.log` |
| `ISA_BITS: PASS` (G3's census runs again) | M | `evidence/qwen9b/s2/019_isa_bits_green.log` |
| the census GREEN, six perturbations CAUGHT | M | `evidence/qwen9b/s2/020_sdma_bits_green.log`, `evidence/qwen9b/s2/021_sdma_bits_control.log` |
| the retired-code sweep's eight hits **outside the gitignored `tb/obj_dir_*` build copies**, all comments | M | `evidence/qwen9b/s2/022_retired_sweep.log` |
| 237 drifted / 89 unresolved / 19 half-mapped citations | M | `evidence/qwen9b/s2/023_cite_drift_check.log` |
| URAM 58 + 58 + 8 for the three caches | S | spec §3's table; S5 measures |
| the block design and its address map | S | unexercised until S5 runs Vivado (§8) |

---

## 11. `spec_cites.py`, LAST, on the committed tree

`evidence/qwen9b/s2/025_spec_cites_last.log`, run on the commit that carries
this document: **`SPEC CITES: PASS`**, FAIL 0 (172 exist, 106 range, 5 quote).
`evidence/qwen9b/s2/024_spec_cites_last.log` is the same run one commit
earlier, on `3704f77`; the commit that carried it mistyped that sha in its
message, and this line is the correction. (Round 1's
`evidence/qwen9b/s2/014_spec_cites_last.log` ran one commit early — fix round
1, M6.)
The **57** PENDING entries are `spec_cites.py`'s own forward-declaration list
from S1, which still names S2's new files as files a future gate creates;
PENDING does not fail, and that file belongs to no task here (§7.6).
*(Both counts recounted from the log itself on 2026-09-10: its summary line
reads `172 exist` and `pending 57`, where this section said 171 and 34.)*

---

## 12. Fix round 1 (2026-09-04) — one Critical, four Important, eight Minor

Base `3b979a3`. Every item below is closed on `a69fe1f`; the review's three
declared deviations were ACCEPTED (§9.3 carries the controller's rulings).

| item | what changed | where |
|---|---|---|
| **C1** *(Critical)* | F2's one-cycle stall-release hole: `cmp_claim`, the dispatcher's third-arm condition as a combinational wire with the slot from the live `layer_*` fields, OR'd per kind into `hd_f2` | `rtl/layer_chan.sv:2079-2095`; §5.3 |
| C1 test | case 12 `f2_release`, plus the ownership monitor armed for the whole run and all three kinds | `tb/tb_layer_sdma.sv:820-837`, `:179`, `:207-219` |
| **I1** | `kvhead_r <= arg0[1:0];` restored at dispatch — the line `evidence/qwen9b/g3/isa_bits.py` anchors — and made load-bearing: the append counters index through it, and a check at the point of use ties it to the slot tag | `rtl/layer_chan.sv:1514`, `rtl/layer_chan.sv:751`, `rtl/layer_chan.sv:1138`, `rtl/layer_chan.sv:2002`, `rtl/layer_chan.sv:2281-2287` |
| **I2** | `axi_ram_bfm` reads `+seed` and prints it at time 0; the TB prints it in the PASS line. The four seeds now produce different AXI timing, which §7.2's per-seed fence counters demonstrate | `tb/axi_ram_bfm.sv:83-96`, `tb/axi_ram_bfm.sv:104`, `tb/tb_layer_sdma.sv:1139` |
| **I3** | ruled NOT an S2 change; §9.1 now says a stream regenerated between S2 and S3 is mis-encoded and must not be trusted | §9.1 |
| **I4** | a later refusal sets `err_op` but no longer overwrites a standing `E_DMA_AXI`; case 10 checks it with a refused SLD | `rtl/layer_chan.sv:1468-1477`, `rtl/layer_chan.sv:1528-1545`, `tb/tb_layer_sdma.sv:1003-1013` |
| **M1** | `state_dma`'s `ph_rows` widened to 14 bits — a CV transfer is 8,192 rows, which 13 bits cannot hold; it worked only because the compare wrapped at exactly `CVD` | `rtl/state_dma.sv:88-91` |
| **M2** | the dead `-generic DN_PIPE` removed from the OOC harness; the retired third `tclarg` is now a hard error | `synth/scripts/ooc_9b.tcl:39-43`, `:125-132` |
| **M3** | the DDR model gains early/late `WLAST` and 1 KiB burst-alignment assertions — the alignment the engine's header claims and nothing checked | `tb/axi_ram_bfm.sv:266-281` |
| **M4** | B15.1 amended: TCNT is read when the transfer STARTS (the range check at dispatch uses the dispatch-time value), because the row a KVAP appends while the SST is queued must reach that SST | `docs/SEQ_ISA.md:1279-1283` |
| **M5** | DEFERRED by ruling: the end-to-end tie between case 9's transcribed constants and `plan_state()` is S3's `SMEM` golden |  |
| **M6** | `spec_cites` re-run LAST on this round's final commit | §11 |
| **M7** | the `UNUSEDSIGNAL` pragma narrowed to `BID`/`RID` | `rtl/layer_chan_ipi.v:159-162`, `rtl/layer_chan_ipi.v:183-186` |
| **M8** | at T = 0 the slot's warmth is proved by ACCEPTANCE (KVAP then ATTN) before the tag refusal, so the tag check cannot mask a cold slot; `E_DMA_COLD` now fires on ATTN and CONV as well as DNST | `tb/tb_layer_sdma.sv:641-667`, `tb/tb_layer_sdma.sv:750-761` |
| ruling (a) | B15.4 states that every refusal advances `cmd_cnt`, and that a later refusal does not overwrite a standing `E_DMA_AXI` | `docs/SEQ_ISA.md:1315-1319` |

**The second form of C1** the review names — two CMD writes two cycles apart —
this testbench cannot drive: an SLD/SST and a compute command need different
ARG0 words, and each AXI-Lite write is a full AW/W/B handshake, so `cmd_go`
pulses can never be closer than about ten cycles here. It is the same tie
between the same two `always_ff` blocks, and `cmp_claim` closes both.

