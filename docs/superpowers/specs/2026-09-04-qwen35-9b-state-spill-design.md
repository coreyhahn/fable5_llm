# Qwen3.5-9B — layer state in DDR, caches in URAM: design amendment

**Status: APPROVED by the user 2026-09-04 (interactive; the DDR-clock question answered: the state path stays at 250 MHz, the weight-stream overlap is a separate later design). Amends
`docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md` — that spec
stays the authority for everything this file does not restate.**

## 0. The decision this amendment records

Task 13 (`evidence/qwen9b/g5/G5A_FLOORPLAN.md`) placed the shipping 9B
`layer_chan` out of context eleven ways. The floorplan technique closed each
URAM array on its own (DN write fan-out −1.141 → −0.001, KV write fan-out
−0.831 → +0.315) but the two placements cannot coexist at 928 of 960 URAM,
the conv block-RAM family does not yield because block RAM is contended with
the compute that reads it, and under the best floorplan the layer is
**WNS −0.554 at OOC** with four wire-dominated SLR-crossing families negative.
By the migration spec's own reading rule that is a definitive failure, and
Task 14's amendment forbids the full build on it.

**User decisions, 2026-09-04, interactive (in order):**

| # | decision |
|---|---|
| D1 | O1 re-opened at **option 3**: the DN state moves to DDR; URAM becomes a cache ("free up URAM for more tactical caching"). Options 1 (register the crossings), 2 (slower clock) and 3 (build anyway) were not taken. |
| D2 | **The KV cache moves to DDR as well** — "rearchitect this all at once". |
| D3 | Context length target **(b): T up to 4,096**, a per-kvhead KV cache; attention stays compute-bound. |
| D4 | **The conv weights and state move too** (24 block-RAM banks, 2.6 MiB). One mechanism for all three. |
| D5 | **Approach A**: sequencer-scheduled caches — one state DMA engine in the layer, caches behind the unchanged compute ports, two new layer opcodes, the emitter schedules prefetch and write-back, two hardware fences. Approaches B (an autonomous cache controller) and C (widen the mover fabric) declined. |

Design sections 1 and 2 (the memory map and caches; the DMA engine) were
approved in chat; sections 3–6 were written straight into this file at the
user's request.

**What this supersedes.** The migration spec's §4.1 W1 (the 24-bank int16 DN
array, A1's `DN_PIPE = 2` and its wait-state decision), §4.6 wall 9's URAM KV
banking, and §4.3's 24 conv block-RAM banks. Task 13's chosen floorplan
(`synth/constraints/fable5_floorplan_9b_dngrpcr.xdc`) is no longer the build's floorplan: the
layer it constrained no longer exists. Its clock-region technique and its
harness stay in the toolbox and are reused by the new structure gate (§10).
Nothing about the arithmetic, the fixed-point formats, the G1 fidelity
result, RS_F = 7, the W4 g128 wire format, the 16-bit scratch ISA, MAX_NG = 96
or the vecnorm width changes.

## 1. Goals, non-goals, invariants

**Goals.**
1. The 9B layer closes timing at 250 MHz with no waiver: it must fit inside
   one SLR with room to spare, so that no state access crosses an SLR.
2. Bit-exact tokens: the 9B stream Task 11 replayed (`evidence/qwen9b/g4/G4A_REPLAY.md`) must
   reproduce **token for token** on the new RTL. No arithmetic changes.
3. The context length ceiling rises from 512 to 4,096 without a second
   redesign.
4. One mechanism, one ISA extension, one reference-model change, one
   host-side artifact change, for all three state kinds.

**Non-goals.** Using the freed URAM (≈ 740 URAM288) for anything — it stays
free (D1's "tactical caching" is deferred to a later decision). Speeding up
`attn_core`'s per-row cost (§9 prices why that matters at T = 4K). Prefill or
batching. Streaming attention straight from DDR for T > 4,096.

**Invariants carried from the migration spec.** One clock in custom RTL
(the DMA master lives on `aclk`; the SmartConnect fabric does the domain
crossing as it does for the host path). The board is untouched until G6. Every
gate has a committed doc and 4-seed evidence. Measured, not modelled, with
the M/D/T/E/S labels. Commits path-limited, never `--amend`.

## 2. The DDR state region

One contiguous region per model image, planned by the host exactly like the
weight pack (`sw/hwmap.py` plan → manifest), named by three **64 KiB-granular
base CSRs** in the layer (§5.3), placed on any channel with free space —
channel 3 has ≈ 3 GB above its 975 MiB of weights (`evidence/qwen9b/g2/G2C_CHAIN.md` §5); the
hardware takes full 34-bit addresses, so the channel is the planner's choice,
not the RTL's.

| kind | blocks | block content | block stride | region |
|---|---|---|---|---|
| **DN** | 24 layers × 32 heads = 768 | 128 rows × 256 B (the int16 Q2.13 state, row = dk) | 32 KiB (`<< 15`) | 24 MiB |
| **KV** | 8 attention layers × 4 kvheads × {K, V} = 64 | rows 0 … T−1 × 256 B (int8 + the row's exponent kept apart), then at block offset 1 MiB the **exponent side array**, T × 1 B | 2 MiB (`<< 21`) | 128 MiB |
| **Conv** | 24 layers | 8,192 rows × 16 B: bits [63:0] the four weight taps, [111:64] the three state words, [127:112] zero | 128 KiB (`<< 17`) | 3 MiB |

**Addressing in hardware** is `base[kind] + (index << shift)` with the index
formed from the command's fields (§5.1); no multiplier, no table. The KV
stride is 2 MiB rather than the 1.06 MiB the data needs so that it stays a
shift; 128 MiB of DDR is nothing on a 4 GiB channel.

**Only valid rows move.** DN and conv blocks are fixed-size. A KV block's
length is `TCNT[layer][kvhead]` rows, read from the layer's own append
counters (which stay in the layer, widened to 13 bits), plus the matching
exponent bytes rounded up to one 64 B beat.

**Initial contents.** The host writes the region as part of the model
upload: conv weight taps from the artifact (the pack gains a `conv` image per
layer — §7), state words zero, DN blocks zero, KV blocks are never read before
they are written (TCNT = 0 after a session reset). The preamble's 768 DNZ and
120 CONVW commands are retired from the steady-state program (§6.4).

**Session reset** is a host-side memset of the DN region plus the TCNT reset
the program already does (`ref/seq_format.py` `on_treset`), so a fresh chat
context costs a 24 MiB DMA write, ≈ 2 ms.

## 3. The caches

All three keep the memory ports their compute units have today, so
`dn_step`, `attn_core` and the conv datapath do not change. Each cache has
**two slots**; the emitter ping-pongs them.

| kind | slot | slots | URAM288 | port A (compute, as today) | port B (DMA) |
|---|---|---|---|---|---|
| **DN** | one layer's 32 heads: 4,096 rows × 2048 b | 2 | 2 × 29 = 58 | `dn_step` row port, 7-bit row within the head selected by the command; `RLAT` as shipped | 2048-bit row read/write at the DMA's row index |
| **KV** | K and V for one kvhead at T ≤ 4,096: 8,192 rows × 2048 b, plus an exponent memory 8,192 × 8 b (block RAM, 2 tiles) | 2 | 2 × 58 = 116 | `attn_core` `kv_addr` widened 10 → 13 bits `{bank, t[11:0]}`, `cfg_t` 10 → 13; KVAP append at `{kv, tcnt}` | same |
| **Conv** | one layer: 8,192 rows × 112 b | 2 | 2 × 4 = 8 | the CONV read (weights + state) and CONVZ/CONV state write, unchanged widths | 112-bit row read/write |

**Totals.** URAM 182 of 960 (was 928). Block RAM ≈ 90 tiles (was 690): the
scratchpad, the attention score memory, the vecnorm buffer, the KV exponent
memories. DSP unchanged (1,836). The layer fits one SLR (320 URAM, 720 block
RAM tiles, 2,280 DSP) with headroom on every resource.

**Slot ownership.** A slot is owned by exactly one lane — compute or DMA — at
any moment (§5.4). That is why port A stays with the compute unit exactly as
today and port B is the DMA's: the two never touch a slot at the same time,
so there is no arbitration and no timing change on the compute side.

**Why 29 URAMs is the floor.** A 2048-bit row needs 29 URAM288s side by side
(72 b each); 29 URAMs hold 4,096 rows, which is 32 heads of DN state or 4,096
KV rows. A smaller DN cache is not possible without changing the row format,
and the row format is `dn_step`'s port.

## 4. The state DMA engine

**One engine, `state_dma`, inside `layer_chan`,** with a 512-bit AXI4
read/write master `m_axis` on `aclk`, connected as a third slave port of the
central `axi_smc` (the SmartConnect that carries the host's 16 GiB view of
all four channels and already converts into each MIG's `ui_clk`). Peak
16 GB/s at 250 MHz; INC bursts of 16 beats (1 KiB); up to 8 bursts
outstanding, with a 256-beat FIFO like `ddr_rd_streamer`'s. The sequencer's
own 128-bit `m_axi` on the same SmartConnect is the precedent for a
second master there.

**Row assembly.** A 2048-bit row is exactly four 512-bit beats; a load
assembles four beats into one port-B write, a store splits one port-B read
into four beats. Conv rows are 16 B, four per beat. The KV exponent side array
is a second, short transfer inside the same SLD/SST (T bytes at block offset
1 MiB → the slot's exponent memory).

**One transfer at a time,** taken in order from the DMA lane's queue (§5.4).
A load is complete when its last beat is written into the slot; a store is
complete when every write response has been collected (the same "bw_idle"
discipline `seq_movers` uses for its burst writes). The engine keeps one
`busy` and one `done` per queued transfer so the fences can name them.

**Errors,** all sticky in the existing `err_op`/STATUS mechanism, refusing
the record before it starts where they can be known in advance: a base CSR
of zero for the kind requested (`E_DMA_BASE`), a KV length above 4,096 or a
block index outside the kind's range (`E_DMA_RANGE`), an AXI SLVERR/DECERR
on any beat (`E_DMA_AXI`, raised at completion), and a compute command that
names a slot with no completed load since its last store (`E_DMA_COLD`, the
lost-update guard of §7.2).

**Budget (label S, measured by the census gate of §10).** A DN layer stores
and loads 1 MiB each: 2 × 64 µs against ≈ 397 µs of DNST compute per layer.
A KV kvhead at T = 4,096 loads 2 MiB in 128 µs against ≈ 2.7 ms of attention
compute for its four query heads (§9). A conv layer loads 128 KiB in 8 µs
against 164 µs. One slot of lookahead hides all of it.

## 5. The ISA extension and the layer's control

### 5.1 Two new layer commands

Layer command opcodes are a 4-bit field (`docs/SEQ_ISA.md`, layer commands
1..12 today; 13 and 14 are free, 0 and 15 stay reserved).

| op | name | ARG0 | ARG1 | ARG2 | effect |
|---|---|---|---|---|---|
| 13 | **SLD** | `{kind[1:0], slot[0], layer[4:0], head[4:0]}` (head = DN head 0..31, or `{kvhead[1:0], kv[0]}` for KV, or 0 for conv) | 0 | 0 | queue a load of block (kind, layer, head) into slot `slot` of that kind |
| 14 | **SST** | the same fields | 0 | 0 | queue a store of slot `slot` to block (kind, layer, head) |

`kind` = 0 DN, 1 KV, 2 conv, 3 reserved (refused, `E_DMA_RANGE`). ARG1/ARG2
are zero and refused otherwise, so the fields have room to grow (a row range
for SST is the one optimisation this spec names and does not take, §9).

### 5.2 The LAYER CSR's slots become cache slots

Today `LAYER` selects a DN bank (`dn_slot`, 0..23) and a KV bank (`kv_slot`,
0..7) — the physical layer's own memory. Now it selects the **cache slot**
each compute command reads: `dn_slot` ∈ {0, 1}, `kv_slot` ∈ {0, 1}, and a new
`cv_slot` ∈ {0, 1} in the same word. The DN slot's head is still the DNST
command's own field; the KV slot's kvhead identity is whatever was loaded
into it. The **layer identity** lives only in the SLD/SST commands: the
compute units never see a layer number, which is the whole point — the
hardware no longer indexes 24 banks, it reads a slot. `TCNT` stays indexed by
(attention layer, kvhead) as today, because KVAP must append at the right
position and SST must know the length; those counters are 8 × 4 × 13 bits.

### 5.3 New CSRs

| offset | name | contents |
|---|---|---|
| 0x64 | `SB_DN` | DN region base, in 64 KiB units (bits [17:0] of `addr >> 16`; 34-bit addresses) |
| 0x68 | `SB_KV` | KV region base, same units |
| 0x6C | `SB_CV` | conv region base, same units |
| 0x70 | `SDMA` | R: `{busy[31], queued[30:28], last_kind[27:26], last_slot[25], err[7:0]}` — the DMA lane's status word for the host and the TB |

The host mirror is `sw/hwmap.py`; the reference's is `ref/seq_format.py`;
the census tool (`evidence/qwen9b/g3/isa_bits.py`) ties the three, as it
does for every other field.

### 5.4 Two lanes, two fences, one ordering rule

The layer's command FSM today executes one command at a time. It gains a
**DMA lane**: SLD and SST records are dispatched into an in-order queue
(depth 4) executed by `state_dma`, and the FSM proceeds to the next record
without waiting. Compute commands run on the compute lane in program order
as today. `STATUS.busy` is the OR of the two lanes; LCYC counts busy cycles
of either, so the census instrument (§10) still measures the layer term.

The only two rules that cross the lanes are enforced in hardware:

- **F1 (load before use).** A compute command whose slot (per its kind) has
  an SLD queued or in flight stalls at dispatch until that load completes.
  A compute command on a slot that has had **no** completed load since the
  slot's last SST — a cold slot — is refused with `E_DMA_COLD` (this is the
  lost-update guard: the emitter must never compute on a slot it has stored
  and not reloaded). Every slot comes out of reset cold, so the first compute
  command of a session on any slot needs an SLD (or, in tests, a DNZ/CONVZ,
  which warm the slot they write) ahead of it.
- **F2 (exclusive slot).** An SLD or SST on a slot stalls at the head of the
  DMA queue while a compute command holds that slot, and an SLD stalls until
  every SST queued ahead of it on the same slot has completed.

The DMA queue is in order, so an SST followed by an SLD of the same slot is
correct by construction. Two SLDs on different slots may overlap only in the
queue, never in flight (§4: one transfer at a time). The emitter's schedule
(§6) is written so that F1 and F2 never actually stall in the steady state;
the stall is correctness, not performance.

### 5.5 Retired and changed commands

- **DNZ** (zero DN state for a head) now zeroes the head's rows in the slot
  the LAYER CSR names and warms that slot (it counts as a load for F1); it is
  used only by tests. The steady-state program does not zero anything: the
  host writes the region.
- **CONVW sel 0/1** (load conv weights/state from scratch) is retired: conv
  blocks arrive by SLD. **CONVW sel 2 / CONVZ** (zero state) zeroes the state
  words of the current conv slot, tests only.
- **KVAP** appends at `{kv, TCNT}` into the current KV slot **and increments
  TCNT**; the row reaches DDR at the slot's next SST (§6.3).
- Every other command is unchanged in encoding and behaviour.

## 6. The emitter's schedule (`ref/gen_layer_script.py`)

The program already knows the whole token; the schedule is a fixed pattern
per layer kind, emitted by the same functions that emit the compute commands.
Two slots per kind; the slot for layer *L* is `L mod 2`.

### 6.1 A DN layer *L* (24 per token)

```
SST  DN  slot (L-1)%2  layer L-1      # write back the previous layer (if L > 0 in this token)
SLD  DN  slot (L+1)%2  layer L+1      # prefetch the next DN layer (if any)
LAYER dn_slot = L%2
DNST head 0 … DNST head 31           # compute on slot L%2 (loaded one layer ago)
```

The first DN layer of a token loads itself at the end of the previous token
(the last DN layer's SST/SLD pair names layer 0 of the next token); the very
first token of a session loads slot 0 explicitly in the preamble. Order
inside the pair matters: the SST of L−1 must precede the SLD of L+1 into the
same slot, and the queue keeps it.

### 6.2 An attention layer (8 per token)

```
for kvhead h in 0..3:
    SLD KV slot (h+1)%2 (layer, h+1, K) ; SLD KV slot (h+1)%2 (layer, h+1, V)     # prefetch next kvhead (h < 3)
    LAYER kv_slot = h%2
    KVAP kvhead h            # append this token's K/V row into the slot, TCNT++
    ATTN ×4 (query heads 4h..4h+3)
    SST KV slot h%2 (layer, h, K) ; SST KV slot h%2 (layer, h, V)                 # write back TCNT rows
```

The first kvhead of an attention layer is prefetched during the preceding
DN layers (the DN layer's pair gains the two KV SLDs when the next layer is
an attention layer). KVAP writes the new row into the slot **before** the
ATTNs, exactly as today, so attention sees position T−1; the SST then carries
the appended row to DDR. Storing all TCNT rows rather than one is 2 MiB per
kvhead per token at T = 4K — 128 µs against 2.7 ms of attention — and keeps
SST to one form; a row-range SST is the named optimisation (§9).

### 6.3 Conv (one per layer, 24 per token)

```
SST  CV slot (L-1)%2  layer L-1       # write back the previous layer's state
SLD  CV slot (L+1)%2  layer L+1       # prefetch weights + state of the next
LAYER cv_slot = L%2
CONV …                                # as today, on the slot
```

### 6.4 The preamble and session reset

The preamble no longer emits 768 DNZ and 120 CONVW (2,655,096 cycles at the
first close, `evidence/qwen9b/g4/G4B_STRUCT.md` §5.1): the host writes zeros to the DN region
and the conv images into the conv region during upload. The preamble emits
the TCNT resets and the first SLDs (DN layer 0, conv layer 0, and the first
attention layer's kvhead 0 K/V). A session reset is the same plus the DN
memset, done by the host tool (`sw/chat_seq.py`) before the session's first
launch.

### 6.5 The emitter model, in lockstep

`gen_layer_script.py`'s model of the layer state (`LF` state dicts:
`state["S"]`, `cache["k"]/["v"]`, the conv state) is split into a **DDR
image** (one array per block, indexed by (kind, layer, head)) and **slot
arrays** (two per kind). SLD copies image → slot, SST copies slot → image,
compute runs on the slot, and every compute command asserts that its slot is
warm (loaded since its last store) — the reference twin of `E_DMA_COLD`. The
`.chip` golden gains the DDR image's blocks as checkpoints (§8.3).

## 7. Host side

**7.1 The artifact pack** gains a `state` plan next to the weights plan:
three regions with their bases (64 KiB aligned), the conv images (24 × 128 KiB,
weights in [63:0], zeros elsewhere), and the sizes. `sw/hwmap.py` writes the
three base CSRs after upload and before the first launch; `sw/seq_run.py`
and `sw/chat_seq.py` audit the region like they audit the weights (a
witness read of the conv images, a zero check of DN). `sw/tok_meter.py`'s
byte-per-token accounting adds the state traffic (label D from the plan).

**7.2 The two things the host must never do**: launch a program whose base
CSRs are zero (the RTL refuses with `E_DMA_BASE`), and reuse a program across
a model switch without re-planning the region (the manifest carries the
region's sha like the weight pieces).

## 8. Verification

**8.1 Bit-exactness is the acceptance bar.** The 9B stream set Task 11
emitted (`tb/scripts/w9`, shas in `evidence/qwen9b/g4/G4A_REPLAY.md` §2) is re-emitted with the
new schedule and replayed through the chip-level sim at 4 seeds; the token
sequence must equal Task 11's, and `seq_model --gate` must be bit-exact at
every checkpoint. The reference lockstep (`seq_model` vs `layer_fixed`) is
unchanged in what it compares — the values are the same bits in a different
place.

**8.2 Directed tests, RED first** (`tb/tb_layer_chan.sv` and a new
a new testbench tb_layer_sdma.sv with its own obj_dir), each with a negative control:
- F1: a DNST/ATTN/CONV on a slot whose SLD is in flight stalls and then
  computes on the loaded data (the RED control: bypass the fence in a
  `-G`-selected variant and observe stale data).
- F1 cold: a compute command on a stored-not-reloaded slot is refused with
  `E_DMA_COLD` before the doorbell.
- F2: an SLD into a slot a compute command holds waits; an SST → SLD pair on
  one slot orders correctly; an SLD → SST of different slots does not
  reorder.
- Row round trip: SLD then SST of each kind reproduces the block byte for
  byte through the DDR model, including the KV exponent side array and a KV
  block at T = 1, T = 4,096, and an odd T.
- Errors: each `E_DMA_*` fires on its cause and only its cause; STATUS/SDMA
  read back what the TB expects.
- The `evidence/qwen9b/g3/isa_bits.py` census ties the SLD/SST field layouts, the three base
  CSRs and the `E_DMA_*` codes across RTL, reference, host and disassembler,
  with its perturbation controls.

**8.3 The TB's DDR model** (`tb/seq_mem_file.sv`) is read-only today. It
gains an AXI4 write channel over a RAM-backed state region (the file-backed
weight and embedding images stay read-only), and the `.chip` golden gains
`SMEM` records checked against the DDR model's state region at the end of
each launch, so a store that never happened, or happened to the wrong block,
is caught by the golden, not only by the token compare.

**8.4 Structure and timing gates**, reusing Task 12's and Task 13's
harnesses without change: OOC synthesis on the new `rtl/` (expect URAM 182,
block RAM ≈ 90, DSP 1,836 — label T), then OOC placement of the whole layer
inside one SLR (a single soft pblock; the clock-region technique held in
reserve), read by the same rule as before: OOC failure is definitive, success
is necessary. Then Task 14 as written.

**8.5 The layer-term census** (`evidence/qwen9b/g4/tb_layer_census.sv`, Task 12) runs on the new
stream: the layer term is expected to move by the DMA commands' dispatch cost
only (≈ 160 SLD/SST per token, a few cycles each) with every prefetch hidden;
any stall F1/F2 actually takes is visible in LCYC and must be attributed.

## 9. Throughput and timing expectations (label E unless stated)

- **Layer term:** unchanged to within the DMA dispatch overhead (< 0.1 %)
  if the schedule hides every transfer, which §4's budget says it does with
  margin. The preamble shrinks by ≈ 2.6 M cycles (the retired DNZ/CONVW).
- **Timing:** the layer's 928 → 182 URAM and 690 → ≈ 90 block RAM put the
  whole block inside one SLR; the three families Task 13 measured (DN write
  fan-out, KV write fan-out, conv block-RAM write) were all SLR crossings and
  cease to exist as such. This is the design's purpose, and §8.4 measures it
  rather than assuming it.
- **DDR traffic:** ≈ 50 MiB/token at T = 512 (DN 48 + conv 6 + KV small),
  rising to ≈ 180 MiB/token at T = 4,096 (the KV stores dominate), against
  ≈ 3.9 GiB/token of weights — under 5 % at the ceiling, on one channel.
- **Attention at long context — a fact this design does not change.** Task
  12's six-step census measured `attn_core` at **41 cycles per KV row per
  ATTN command** (`evidence/qwen9b/g4/G4B_STRUCT.md` §5.4a: +5,230 cycles per token-step over
  128 commands). At T = 4,096 that is ≈ 168 K cycles per command, ≈ 87 ms
  per token for attention alone on today's 137.7 ms token. The cache and DDR
  path are not the limit (128 µs of transfer per 2.7 ms of compute); the
  compute is, and it was already first on the project's next-options list.
  This spec sizes the state path for T = 4K; making attention fast at T = 4K
  is a separate design.
- **Named, not taken:** a row-range SST for KV (store only the appended row)
  would cut the KV traffic ≈ 4,000×; at T = 4K it saves 64 MiB per token of
  a nearly free resource, so it waits for a measurement that says it matters.

## 10. What changes in the campaign plan

The migration plan's Tasks 14–16 stand. Between Task 13 and Task 14 the plan
gains the tasks below (the implementation plan details them; this is the
shape):

| new task | delivers | gate |
|---|---|---|
| **S1 — ISA and docs** | `docs/SEQ_ISA.md` v2.1 (SLD/SST, LAYER slots, the four CSRs, error codes), `ref/seq_format.py` + `sw/hwmap.py` + the disassembler in lockstep, `evidence/qwen9b/g3/isa_bits.py` census extended | census PASS with controls |
| **S2 — RTL** | `state_dma` + the two-lane FSM + the three two-slot caches in `layer_chan`, `attn_core` at 13-bit T, retired DN_PIPE/banks/conv banks; `tb_layer_sdma` + `tb_layer_chan` directed tests, RED first | 4 seeds, all fences and errors proven both ways |
| **S3 — emitter, reference, host** | the schedule in `gen_layer_script.py`, the DDR image + slots model, the `.chip` `SMEM` records, the writable TB DDR model, the pack's state plan and conv images, the host CSR writes and audits | `seq_model --gate` bit-exact; boardfree gates unmoved |
| **S4 — the 9B replay** | the stream set re-emitted, chip replay at 4 seeds token-identical to `evidence/qwen9b/g4/G4A_REPLAY.md`, the layer-term census with the DMA cost attributed | tokens identical; layer term within the stated envelope |
| **S5 — structure and placement** | OOC counts on the new RTL; the one-SLR placement experiment with Task 13's harness; the floorplan XDC Task 14 starts from | URAM/BRAM/DSP as predicted; OOC WNS inside the playbook's reach or a stop-back |
| then **Task 14** | the full build and closure, as written | WNS ≥ 0, WHS ≥ 0, no waiver |

Task 13's gate doc stays as the record of why; its XDC candidates are kept in
`synth/constraints/` marked superseded. Task 10's DN_PIPE evidence stays as the
record of a design that was built, verified and retired.

## 11. Decisions this spec makes on its own, and the ones it leaves open

**Made here** (each reversible, each stated so the plan can be reviewed
against it): the DMA master joins the central `axi_smc` rather than one
channel's `smc_ch` (full 34-bit addressing, no channel choice in RTL);
two slots per kind (double buffering is the minimum that hides a transfer and
the schedule never needs a third); KV stride 2 MiB; conv rows padded to 16 B;
the KV exponent side array at 1 MiB into the block; `E_DMA_COLD` as a hardware
refusal rather than an emitter-only assert (the RTL is the last line, as with
the MVGO envelope); DNZ/CONVZ kept as slot-level test commands rather than
removed from the ISA.

**Left to the user, non-blocking:** what the freed ≈ 740 URAMs are for (D1's
"tactical caching"); whether T = 4,096 is the ceiling to build the address
fields for or a stop on the way to the streaming design; the channel the host
planner puts the region on (default: the emptiest weight channel).

## 12. Risks

1. **The one-SLR placement is asserted from resource counts, not measured
   until S5.** 1,836 DSP of 2,280 (80 %) and ≈ 110 K LUTs are the tight
   resources of a one-SLR layer; the matvec channels and the sequencer take
   their own SLRs today. S5 is the gate, and its stop-back is the same fork
   as Task 13's.
2. **The two-lane FSM is new control logic in the file that has been closed
   twice.** Its hazards are exactly the F1/F2 rules, tested RED first;
   nothing else in the FSM changes.
3. **The TB DDR model's write path and the golden's `SMEM` records are new
   verification infrastructure**; a bug there is a false PASS. The row
   round-trip test and the token compare are independent of each other, and
   the token compare against Task 11's record is the arbiter.
4. **Host-side state planning is one more thing that can silently mismatch
   a bitstream** (the class RD_GATE §4 found three of). The manifest sha and
   the base-CSR audit are the guards; the RTL refuses zero bases.
5. **Long-context attention is slow for a reason this design does not
   touch** (§9). A user who expects T = 4K at today's tokens per second will
   not get it from this change alone.

## A1. Amendment (2026-09-04, from the plan review) — four ambiguities resolved

The independent plan review found four places where this spec could be read
two ways or claimed something the RTL cannot provide. The controller resolved
them as follows; each is consistent with the approved design's intent and is
reversible by the user.

**A1.1 A DN transfer moves a whole layer.** §2's table describes the DN region
as 768 blocks of 32 KiB laid out by `(layer × 32 + head)`, and §4/§6 budget
and schedule ONE transfer of 1 MiB per DN layer. Those agree only if an SLD or
SST of kind DN moves the layer's 32 contiguous head blocks — 4,096 rows — at
`SB_DN << 16 + (layer << 20)`. That is the rule: the DN `head` field must be
0 (refused otherwise, `E_DMA_RANGE`); the per-head block layout stays as the
description of what lands where.

**A1.2 The caches have ownership muxes, not a spare port.** Each URAM has two
ports and each compute unit already uses both (a read and a write of
different rows in the same cycle: `dn_step` `s_rdaddr`/`s_wraddr`, KVAP's
`kv_ra_f`/`kv_wa_f`, conv's `cw_ra`/`cw_wa`). The DMA therefore shares the
ports through a 2:1 mux on read address, write address, write data and write
enable, selected by the slot's owner — which §5.4 already makes exclusive.
The claim in §3 that there is "no timing change on the compute side" is
WITHDRAWN: the mux sits on the DN and KV write fan-out, the family Task 13
measured, and S5 measures it rather than assumes it. The conv slot keeps two
memories (weights 64 b, state 48 b) so the state-only writes stay as they
are; the DMA assembles and splits the 16-B DDR row across the two.

**A1.3 TCNT keeps its attention-layer index through a slot tag.** With LAYER
carrying cache slots, the 32 append counters need their layer index from
somewhere. Each KV slot carries a hardware tag `{layer[2:0], kvhead[1:0]}`
latched by the SLD that filled it; KVAP and ATTN index `tcnt_bank` through
the tag of the slot LAYER names, and refuse (`E_DMA_RANGE`) if the command's
own kvhead field disagrees with the tag. Host and program access to TCNT/TCNT2
is indexed by a new LAYER field `kv_layer[10:8]` (0..7; the word is `{cv_slot[13:12], kv_layer[10:8], kv_slot[4:3], dn_slot[1:0]}`, B15.2 — corrected 2026-09-04 from a `[6:4]` that overlapped `kv_slot`), so the preamble
resets all 32 counters with eight LAYER writes and sixteen TCNT/TCNT2 writes.
A zero-length KV SLD (TCNT = 0, the first transfer of every session) warms the
slot and sets its tag.

**A1.4 Two busy signals, one accept gate.** The layer's CMD write is accepted
only while the compute lane is idle (`busy_cmp`, today's `busy`); the DMA lane
never blocks it. STATUS bit 0 reports `busy_any = busy_cmp | busy_dma`;
`cmd_cnt` increments when an SLD/SST is ENQUEUED; LCYC counts `busy_cmp`
cycles only, so the layer-term census keeps its meaning, and a new CSR
`SDMA_CYC` (0x74, R, cleared by any write) counts `busy_dma` cycles so S4 can
attribute the DMA lane separately. `E_DMA_AXI` sets `err_op` at completion
and stays set, with `SDMA.err`, until the host writes SDMA; the next compute
dispatch does not clear it (the program halts, as it should).

**A1.5 Three smaller corrections.** (a) `attn_core` has a second 512-deep
memory, `es_mem`, and a 10-bit `t, T` pair beside `sc_mem` and `kv_addr`; all
widen together, and the two score-class memories are 4 RAMB36 each at 4,096
deep. (b) The KV exponent memories are two (one per slot). (c) The SLD/SST
count per token is ≈ 224 (DN 48, CV 48, KV 128 incl. the 16 prefetches the DN
layers emit), not ≈ 160.

## A2. Amendment (2026-09-05, from Task S5's fix round 1) — the two rows S5 measured

S5 synthesized the state-spill layer out of context for the first time, so §3's
cache table stops being a prediction and becomes something that has been read
off a netlist. Two of its numbers were wrong and one of its rows was right in a
way the RTL did not yet implement. **§3 is left byte-untouched on purpose** —
every citation into it, and every quotation of it in S1–S5's gate docs, keeps
its line; this amendment is where the corrections live.

**A2.1 The KV exponent memories measure 4 RAMB36, two per slot — not "2
tiles".** §3's KV row says "plus an exponent memory 8,192 × 8 b (block RAM, 2
tiles)"; A1.5 (b) had already corrected the COUNT of those memories to two, one
per slot. The measurement is **2 RAMB36 each, 4 in all**: 8,192 × 8 b does not
fit one RAMB36, so each slot's memory is two tiles deep and two slots cost
four. Measured in `evidence/qwen9b/s5/092_mem_census.log` (the `KV_slot_emem`
row) and independently in `evidence/qwen9b/s5/091_ooc_counts_g4b.log` (the
`OOC9B_BRAM_SPLIT` marker's `kvexp` field).

**A2.2 The block RAM total is 81 tiles, where §3 predicted "≈ 90".** Measured:
77 RAMB36 + 8 RAMB18 = **81.0 tiles of 720 in one SLR (11 %)**, made up of the
scratchpad 62, the KV exponent memories 4, `attn_core` 7 RAMB36 + 3 RAMB18, and
`vecnorm_unit`/`gate_unit`/`vec_alu`/`conv4_silu` 4 RAMB36 + 5 RAMB18. Both OOC
harnesses report the same figure — `evidence/qwen9b/s5/090_ooc_counts_exp.log`
and `evidence/qwen9b/s5/091_ooc_counts_g4b.log` — and the per-memory census
`evidence/qwen9b/s5/092_mem_census.log` names every one of the 77 + 8 cells
with nothing unaccounted for. §3's URAM total holds as written: **182** of 960.
Its DSP total does not: §3 says "DSP unchanged (1,836)" and the measurement is
**1,838**, **+2** — the tool re-inferring a boundary adder, which
`evidence/qwen9b/s5/S5_STRUCT.md` §2.3 attributes and which the same ±1 wobble
produced between Task 12's own two runs. No arithmetic changed; the amendment
records the measured figure so that §3's 1,836 is read as the prediction it
was.

**A2.3 The conv slots ARE in URAM, as §3's table says — and S5's first count is
why anyone knows the RTL agrees.** That count read URAM288 **174**, eight
short, because `rtl/layer_chan.sv` declared the conv weight and state memories
with no `ram_style` attribute while the DN and KV slot memories carried
`(* ram_style = "ultra" *)`, so Vivado inferred 51 block-RAM tiles for them
instead. The spec was not amended to follow the tool: the attribute was added,
and the re-count is 182 with the conv pair at 2 + 2 URAM288 per slot. The RED,
the fix and the re-count are in `evidence/qwen9b/s5/S5_STRUCT.md` §7 and in the
fix round's report, `.superpowers/sdd/2026-09-04-qwen35-9b-state-spill/task-S5-fix1-report.md`.

Nothing else in this specification changes.
