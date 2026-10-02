# S3 — the emitter's schedule, the reference DDR image, the writable TB DDR model, the golden, the host plan

**Task:** S3 of `docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md`.
**Spec:** `docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md`
§2, §5, §6, §7, §8.1–8.3 and A1. **ISA:** `docs/SEQ_ISA.md` B15 (v2.1, S1).
**RTL:** S2's, `evidence/qwen9b/s2/S2_RTL.md`.

S1 wrote the ISA down; S2 built the RTL. S3 teaches the rest of the system
the same thing: the emitter schedules the transfers and models the DDR
image and the slots, the reference executor mirrors it *from its own code*,
the chip TB's DDR model gains a write path and the golden gains `SMEM`
checkpoints, the host plans the region, and the layer-family testbenches are
re-based onto v2.1.

---

## 0. What this gate says, and where each number comes from

**Every log named here is the LATEST run of that gate, on the committed
tree, on snoke.** The earlier runs are kept and §9's tables carry each
one's own tree; §9.3 is the script that reads those trees rather than
trusting this column.

| the claim | label | log, last line |
|---|---|---|
| the emitter refuses a compute command on a COLD slot | M | `001` RED → `049` GREEN (§2.1) |
| the retired preamble and the host's upload are the SAME BYTES | M | `050` `PREAMBLE_EQUIV: PASS`; control `004` `CAUGHT` |
| the schedule emits **224 SLD/SST per token** (spec A1.5(c)) | M | `073` `SDMA_CENSUS: PASS`, `per token [224, 224, 224]` |
| the emitter's `StateImage` and the reference's `StateRegion` agree byte for byte | M | the SEQ gate's `STATE BIT-EXACT` line (§5, `071`) |
| the eight smoke artifacts gate | M | `071` `G4A_SEQGATE: ALL PASS (8 artifact(s))`, tokens still G4a's |
| every kept artifact is emitted TWICE and byte-compared | M | `061` `EMIT_REPEAT: PASS` ×8; the gate's RED is `060` `EMIT2_RED: CAUGHT` |
| `tb_layer_chan` ×4 at v2.1, **261,357 checks — unmoved from G3.4** | M | `070` |
| `tb_layer_env` ×4, every envelope check fires | M | `070` |
| `tb_seq_chip` 9B smoke ×4, `smem 10` in every PASS line | M | `074` |
| the board-free triple, **2785 / 85 / 364** on the committed tree | M | `068` `BOARDFREE_PASS` |
| `ref/seq_model.py --selftest`, 21 STATE REGION checks with a 1/1 RED | M | `069` |
| every SLD/SST field at or inside its B15.1 ceiling; a forced kind 3 REFUSED | M | `072` `G4A_ENVELOPE: PASS` |
| the citation-drift pass S1 and S2 left open | M | §8.1c, `062`–`066` (`VERIFY FAIL 4`, all four the class-B `gen_model_script` set); §8.1c′, `081`–`084` re-applied and `089`–`091` verified after the `07eea51` restore discarded two of round 0's passes |
| every artifact's manifest names the sha256 of ITS state image | M | `088` `STATE_SHA: PASS — 8 match, 0 mismatch`, through `sw/seq_run.verify_state_image` on snoke |
| the layerv2 command delta accounted for exactly (1438 → 1465) | M | `048` `OPCODE_DELTA: PASS` |

---

## 1. What landed

| file | what changed |
|---|---|
| `ref/gen_layer_script.py` | `_DN_SLOTS = _KV_SLOTS = _CV_SLOTS = 2`; `_DN_LAYERS`/`_KV_LAYERS` (the DDR image's extent); `StateImage`; `Mach`'s two-slot arrays, `img`, `warm`, `slot_id`, `tag`, `state_plan`; `layer(dn, kv, cv=0, kv_layer=0)`; `sbase()`; `sld()`/`sst()`/`_require_warm()`/`_require_tag()`/`_sdma_copy()`; `Treset()` over all eight attention layers; `seed_conv()`; `dump_state()`; the `sched_*` schedule helpers; `attn_token`'s §6.2 loop and its image-based block-float peek; `main`'s v2.1 preamble |
| `ref/seq_format.py` | `on_layer` four fields; `on_sbase`; `on_treset` sweeps eight layers; the gated-attention double pass buffers a MIXED block and replays it in program order |
| `ref/seq_model.py` | `StateRegion` (the second, independent implementation); ops 13/14; the B15.2 LAYER decode; 13-bit TCNT indexed by `kv_layer`; the SB_* cross-check; `snapshot`/`diff_state` over slots, tags and warm bits; `gate()`'s `STATE` line |
| `ref/gen_model_script.py`, `ref/gen_token_script.py`, `ref/gen_chain_script.py`, `ref/seq_chat.py`, `sw/infer.py` | the seven `layer()` call sites, and the §6 schedule around each layer body |
| `tb/seq_mem_file.sv` | the AXI4 write channel over one RAM-overlay window, `win_fnv` |
| `tb/tb_seq_chip.sv` | `u_layer.m_axis` → `u_smem`; the `SBASE`/`SMEM` golden and its check; `smem N` in the PASS line |
| `tb/tb_layer_chan.sv` | `m_axis` → `u_smem`; the `S` record; `run_dnbank` retired; `run_envtest` at v2.1 |
| `tb/scripts/gen_seq_chip_vectors.py` | the region, the `SBASE` header and one `SMEM` record per stored block |
| `tb/Makefile` | `tb_layer_dnbank` retired; `tb/seq_mem_file.sv` in the two layer-family targets; `+state=` |
| `sw/hwmap.py` | `plan_state_base`, `STATE_MIN_BASE`, the two non-scalar manifest keys |
| `sw/seq_run.py` | `upload_state`, `seq_check_state_bases` |
| `sw/chat_seq.py` | one residency witness per conv image; the session-reset DN memset; the v2.1 template anchor |
| `sw/tok_meter.py` | `state_bytes_per_token(T)`, label D |
| `evidence/qwen9b/g4/g4a_envelope.py` | the `--sdma` half |

### 1.1 The commands the schedule adds and retires, in one place

| SEQ_ISA v2.0 | v2.1, S3 |
|---|---|
| `CONVW sel 0/1` — 120 per token, staging conv weights through scratch | RETIRED (spec §5.5). The taps arrive by `SLD`; the emitter keeps a callable `convw` shim for the pre-G3 (frozen-model) paths and only the RTL refuses sel 0/1 |
| 768 `DNZ` in the preamble | RETIRED (spec §6.4). The host memsets the DN region. `DNZ` survives for TESTS and WARMS the slot it zeroes |
| `LAYER` = a bank pair `{kv_slot[2:0], dn_slot[4:0]}` | `{cv_slot[13:12], kv_layer[10:8], kv_slot[4:3], dn_slot[1:0]}` — CACHE slots, plus the attention layer whose TCNT pair the CSRs address |
| `T 0` = one kv_slot's `_KVH` counters | ALL `_KV_LAYERS × _KVH`, expanded by the SEQ emitter into 8 LAYER + 16 TCNT/TCNT2 writes (A1.3) |
| — | `SLD`/`SST` (ops 13/14), 224 per token |
| — | the `.txt` record `S <sb_dn> <sb_kv> <sb_cv> <units>`, three CSRWRs in the `.seq` (B15.3) |

---

### 1.2 What this gate did NOT change

No arithmetic. `dn_step`, `attn_core`, the conv datapath and every ALU op
are untouched by S3, and the compute commands emit exactly the ARG words
they emitted at v2.0 — what moved is WHERE the state they read lives.
`rtl/` is S2's and is byte-identical to `07eea51` here. The 0.8B/2B frozen
artifacts are not regenerated.

---

## 2. The emitter's model (spec §6.5)

### 2.1 The RED, for the right reason

`evidence/qwen9b/s3/cold_red.py` is five statements against `Mach`: a LAYER
select, the DNSB base pair every DNST needs, and one DNST on a DN cache slot
no SLD ever loaded. Re-running a generator is NOT this RED — its own
preamble calls `convw` and the first failure would be that.

```
evidence/qwen9b/s3/001_emitter_cold_red.log   tree 07eea51, rc 1
  cold_red: layer() takes two arguments on this tree (pre-S3)
  COLD_RED: RED — DNST on a COLD DN slot 0 was ACCEPTED; the emitter has no
  E_DMA_COLD fence
```

On S3's tree the same script prints
`COLD_RED: GREEN — DNST: DN slot 0 is COLD (E_DMA_COLD)` and exits 0 (§9's
committed-tree run, `030`).

### 2.2 The two implementations, and why they are two

| | the EMITTER's | the REFERENCE's |
|---|---|---|
| class | `ref/gen_layer_script.StateImage` + `Mach._sdma_copy` | `ref/seq_model.StateRegion` |
| representation | a dict of per-block `uint8` arrays, keyed `(kind, layer, head)` | ONE flat byte array over `[dn, end)`, addressed by absolute DDR address |
| where the layout comes from | B15.1 + `LR`'s geometry | `docs/SEQ_ISA.md` B15.1 + `sw/hwmap.STATE_*` |
| shares code with the other | **nothing** | **nothing** |

That is deliberate (spec §6.5): the SEQ gate compares the image the emitter
ended with against the region the executor ended with, and a shared
serialiser would make that comparison vacuous. The comparison is the
`STATE` line of §5.

### 2.3 The fences the emitter carries

* `_require_warm(kind, slot, what)` — the twin of `E_DMA_COLD` (B15.4).
  `dnst`, `kvap`, `attn` and `conv` call it FIRST, before any other refusal.
* `_require_tag(kvh, what)` — the twin of the KV slot tag check (A1.3):
  `KVAP`/`ATTN` must name the kvhead the slot's tag carries.
* `dnz` and `convz` WARM the slot they write (spec §5.5), so they stay legal
  on a cold slot and remain what the directed tests use.
* `sst` asserts the slot holds the block the command names. **Deviation
  from the brief's literal code:** for KV the identity is `(layer, kvhead)`,
  not `(layer, head)`, because the K and V halves of one kvhead are two
  commands that fill and drain the SAME slot — keying on `head` would make
  the SST of the K half claim the slot held another block. That is exactly
  what the hardware's `kv_tag = {layer[2:0], kvhead[1:0]}` says (A1.3), and
  `Mach._blk_id` is the one place the emitter says it.

---

## 3. The retired preamble, and the proof it is equivalent

Spec §6.4 deletes the 768 DNZ and the 120 CONVW from the steady-state
program: the host writes zeros to the DN region and the conv images to the
conv region during upload. (The two numbers are 24 DeltaNet layers × 32
heads and 24 × 5 op-5 commands — 4 CONVW chunks over `CONV_DIM = 8192` at
2,048 channels each, plus the CONVZ. `023` measures exactly those 5 and 32
per layer in the one-layer script.) `evidence/qwen9b/s3/preamble_equiv.py` is the
guard on that claim, and it compares BYTES, not intentions:

* **OLD** — a `Mach` whose conv slot is filled by the retired preamble
  itself (`W(STG, taps)` + 4 × `convw` + `convz`) and whose DN slot is
  zeroed by 32 `dnz`, then serialised into a DDR block through the store
  side of `_sdma_copy`.
* **NEW** — the block `seed_conv` puts in the image, which is what
  `dump_state` writes to `<prefix>.state.bin` and `<prefix>_cv<L>.bin` and
  what `sw/seq_run.upload_state` uploads; and, for DN, the host's zero fill.

```
evidence/qwen9b/s3/003_preamble_equiv.log      rc 0
  OK  conv block L=0 (CONVW+CONVZ vs seed_conv): 131072 bytes identical
  OK  DN block   L=0 (32 x DNZ vs the host's zero fill): 1048576 bytes identical
  ... L=1, L=2 the same
  PREAMBLE_EQUIV: PASS
```

**Its negative control fires**, which is what makes the PASS worth having —
one flipped weight-tap byte and one DN state word:

```
evidence/qwen9b/s3/004_preamble_equiv_perturb.log   rc 0
  FAIL conv block L=2 ...: 1 of 131072 bytes differ, first at 7 (4 vs 5)
  FAIL DN block   L=2 ...: 1 of 1048576 bytes differ, first at 768 (0 vs 1)
  PREAMBLE_EQUIV --perturb: CAUGHT
```

---

## 4. The schedule, and the 224-per-token census

`ref/gen_layer_script.py` carries spec §6.1–§6.3 in five functions, in ONE
place, because five generators emit them:

| function | spec | what it emits |
|---|---|---|
| `sched_preamble(M, layer_types)` | §6.4 | `LAYER`, `sbase()` (the three region bases), `Treset()` (all 8 × 4 counters), `SLD DN 0`, `SLD CV 0`, and the first attention layer's kvhead 0 **only when no DeltaNet layer precedes it** |
| `sched_dn_pair(M, L, n_dn, a_next)` | §6.1 | `SST DN (L-1)%2 L-1`, `SLD DN (L+1)%2 L+1`, and the two KV prefetches when the NEXT layer is an attention layer |
| `sched_cv_pair(M, L, n_dn)` | §6.3 | the same pair for the conv block |
| `sched_attn_layer(M, A, nkv, dn, cv, body)` | §6.2 | per kvhead: prefetch h+1 into the other slot, `LAYER kv_slot = h%2`, `body(h)` (the KVAP and the four query heads), then the two SSTs |
| `sched_token_end(M, n_dn)` | §6.1, last sentence | `SST DN/CV` of the last layer and `SLD DN/CV` of layer 0 for the next token |

**The census — M**, and it runs the REAL schedule functions against a
counting stub, so it measures the code rather than restating the spec:

```
evidence/qwen9b/s3/022_sdma_census.log     rc 0
  SDMA census — FABLE5_MODEL=9b, 32 layers (24 DeltaNet + 8 full-attention), NKV=4
    preamble               DN 1+0 KV 0+0 CV 1+0   total 2
    3 tokens               DN 72+72 KV 192+192 CV 72+72   total 672
    per token              [224, 224, 224]   (spec A1.5(c) expects 224)
  SDMA_CENSUS: PASS (0 problem(s))
```

**224 = DN 24+24 + conv 24+24 + KV 64+64**, and the KV 128 is the 16
prefetches the DN layers emit plus 8 × (6 + 8) — exactly A1.5(c)'s split.
The preamble adds two SLDs and nothing else.

### 4.1 Two places where the ISA and the emitter had to meet

1. **The gated-attention double pass had to learn the schedule.**
   `ref/seq_format._emit_attn_block` re-emits the buffered ATTN/SIGM16/EMUL32
   block in a different order so that `k_a` can be computed on chip
   (SEQ_ISA v1.3). Spec §6.2 interleaves a `LAYER` write, an SLD pair, a
   KVAP and an SST pair AMONG the heads, and with two KV slots the four
   kvheads are never resident at once — so a reorder that put all sixteen
   ATTNs together would run them all under the last `LAYER` value. The
   buffer is now MIXED and is replayed **in program order**, with only the
   SIGM16s hoisted (they read the q_proj gate halves and touch no layer
   state) and only the EMUL32s replaced (by the probe/real pair). The
   ATTN destinations are still rewritten to the contiguous `AO32ALL` slots,
   which is what the probe needs. Measured: `tok9b_s*` still reports
   `loop 2 steps (looped) STRUCTURALLY SAFE` and the same tokens G4a
   recorded (§5).
2. **The block-float peek had to read the image.** `attn_token` must
   evaluate every query head before it emits the first command, and the row
   `KVAP` is about to append is not appended yet. `Mach.attn_peek_img`
   reads the DDR image and adds that pending row; after the SLD the slot
   holds exactly the image's bytes, so the peek computes what the emitted
   ATTN will. `_attn_acc` was split so the SAME arithmetic serves both.

---

### 4.2 The TB's DDR model, and the `SMEM` golden (spec §8.3)

`tb/seq_mem_file.sv` was READ-ONLY (`araddr … rvalid`, no AW/W/B — the
plan's own standing hazard), so an RTL store in a chip-level sim had nothing
to talk to. It gains an AXI4 **write channel over ONE window**
`[win_base, win_base + win_len)`:

* the window's INITIAL contents come from `<prefix>.state.bin`, opened once
  and read at `addr - win_base`; the beats the run WRITES live in an
  associative overlay on top of it. It is a copy-on-write model, so it
  costs what the run stores, not the 155 MiB the region spans;
* a WRITE outside the window is a `$fatal`.  A READ outside it is not —
  it falls through to the file regions and, in an instance with none, is
  served as zeros — so it is COUNTED on `n_miss`, and both testbenches
  check that count at the end of the run and fail on it
  (`tb/tb_seq_chip.sv`, `tb/tb_layer_chan.sv`; S3 fix round 1, M2). That
  is what makes the separation from the weight images checked rather than
  assumed;
* `win_base` / `win_len` are PORTS, not parameters: the region's address
  belongs to the artifact. `tb_seq_chip` drives them from the `.chip`
  golden's `SBASE` header, `tb_layer_chan` from the script's `S` record.
* `win_fnv(addr, len)` is FNV-1a 64 over the window bytes, the identical
  arithmetic `tb/scripts/gen_seq_chip_vectors.fnv1a64` runs in Python.
  **The hash is the transport; byte equality is the check** — a golden that
  carried 155 MiB of bytes would be unreadable.

The golden grammar, per launch, one record per block the launch STORED:

```
SBASE <sb_dn> <sb_kv> <sb_cv> <units>      (64 KiB units; a file header)
SMEM  <hex addr> <hex len> <hex fnv1a64>   (one per stored block)
```

`tb_seq_chip` checks every `SMEM` at end of launch and reports the count in
the PASS line (`smem N`), beside `tcnt` and `scratch`.

---

## 5. The reference, and the `STATE` line

`ref/seq_model.StateRegion.load(prefix)` reads `<prefix>.state.bin` and the
manifest's `state` plan; `SeqExec._layer_cmd` runs ops 13/14 through it;
`TxtReplay` gets its own region, so the two replays are independent.
`gate()` then makes TWO comparisons and says so:

* `.txt` vs `.seq` — the same lockstep every other check in that function is;
* `.seq` vs **the emitter's final image**, `<base>.state_final.bin`, written
  by `StateImage` — the two independent implementations of B15.1.

The RED, on a re-emitted `lay9b_s1` before the model executed anything:

```
evidence/qwen9b/s3/002_seqmodel_sld_red.log   rc 1
  seq_format.SeqValidationError: unknown layer_chan opcode 13
  G4A_SEQGATE: FAIL
```

and GREEN, per artifact (§7.1):

```
  BANKED   BIT-EXACT (conv/S/KV/TCNT/EOUT/AMAX)
  STATE    BIT-EXACT (10 block(s) stored; .txt vs .seq vs the emitter's StateImage)
  TOKENS   IDENTICAL  [2380, 6362]
SEQ GATE: PASS
```

---

### 5.1 The host (spec §7)

| tool | what S3 added |
|---|---|
| `sw/hwmap.py` | `STATE_MIN_BASE`, `plan_state_base(nch)`, and the two NON-SCALAR manifest keys (`state`, `conv_images`) — they cannot live in `_META_DEFAULTS`, whose values go through `int()`, so `split_manifest` answers `None` for a pre-S3 manifest |
| `sw/seq_run.py` | `upload_state(dev, art)` — the DN region memset (`dma_write_chan`, the existing H2C path), one write per conv image with a readback, and the three base CSRs — and `seq_check_state_bases(dev, art)`, which refuses to launch on a ZERO or a DISAGREEING readback. Spec §7.2's two "never"s, one function each |
| `sw/chat_seq.py` | one residency WITNESS per conv image (the conv blocks are the only part of the region the host uploads, so the only part a host-side hash can hold); a conv miss invalidates the pack exactly as a weight or embedding miss does (R-d rule (b) is about what a miss PROVES); and `Session.reset_state_region()` — the session reset's DN memset — runs before the preamble image |
| `sw/tok_meter.py` | `state_bytes_per_token(T)`, label D: `2·24·1 MiB + 2·24·128 KiB + 2·8·4·2·(T·256 + 64·⌈T/64⌉)` = **70 MiB at T = 512, 182 MiB at T = 4,096** |

---

## 6. The artifacts, the region, and who names its address

`ref/gen_layer_script.Mach.dump_state` writes, beside the weight images:

| file | what |
|---|---|
| `<prefix>.state.bin` | the region's INITIAL image — DN zero, KV zero, conv blocks holding the taps. Written SPARSE (155 MiB apparent, ~1 MiB on disk). The chip TB maps it behind its write window; `StateRegion.load` reads it; the host uploads from it |
| `<prefix>.state_final.bin` | the emitter's FINAL image, for the gate's `STATE` comparison |
| `<prefix>_cv<L>.bin` | one 128 KiB conv image per DeltaNet layer — what the host actually uploads (spec §7.1); DN is a memset and KV is never read before it is written |
| manifest `state` | `plan_state(...)` plus `sha256` (the initial image) and `final_sha256` |
| manifest `conv_images` | `[{layer, file, bytes}, …]` |

**WHERE the region sits — a deviation from the brief, recorded.** The brief
says "the first 64 KiB-aligned address above the pack on the emptiest
channel". What landed is `sw/hwmap.plan_state_base(nch)` = **the LAST
channel at `STATE_MIN_BASE` (2 GiB into it)**, and it is a deviation with
three reasons:

1. It is above the pack — `plan_weights` ASSERTS the pack ends below
   `EMB_BASE` (0x6000_0000) on every channel — **and** above the 485 MiB
   embedding table, which the brief's rule does not account for and which
   shares channel 0.
2. It is a function of the stream's CHANNEL COUNT alone, so the emitter,
   the reference model, the chip TB and the host name the same address
   without any of them re-deriving the weight pack. That is what lets the
   PROGRAM carry the three base CSR writes (below), which is what makes a
   replay self-contained.
3. 155 MiB at 2 GiB into a 4 GiB channel leaves the pack its whole span.

**The program carries the bases.** `sched_preamble` emits `Mach.sbase()`,
which prints the `.txt` record `S <sb_dn> <sb_kv> <sb_cv> <units>` (all in
64 KiB units) and three CSRWRs into the `.seq`. The host still writes them
from the manifest before the first launch and refuses to launch on a zero or
disagreeing readback (`sw/seq_run.seq_check_state_bases`, spec §7.2), and
`ref/seq_model` CHECKS a program-written base against the manifest's plan
rather than ignoring it. `tb_layer_chan` reads the same record; the chip
TB reads the `SBASE` header of the `.chip` golden.

---

## 7. The gates

### 7.1 The eight smoke artifacts — `SEQ GATE: PASS` with `STATE BIT-EXACT`

The set is the one `evidence/qwen9b/g4/G4A_REPLAY.md` §4.1 names: the four
layer seeds and the four token seeds, re-emitted at `FABLE5_MODEL=9b
FABLE5_RS_F=7` by `make -C tb w9_9b_smoke_scripts w9_9b_tok_smoke_scripts`
(`MODELPY=VECPY=/home/cah/.venv/bin/python` on snoke — the repo's
`ref/.venv` is a dangling symlink there).

**M**, `evidence/qwen9b/s3/053_seqgate_smokes_committed.log`, tree
`a0ad071` clean, on snoke, rc 0, last line
**`G4A_SEQGATE: ALL PASS (8 artifact(s))`** (`032` is the round-0 run at
`d0e4ae9`; both agree line for line). Every one of
the eight reports:

```
  BANKED   BIT-EXACT (conv/S/KV/TCNT/EOUT/AMAX)
  STATE    BIT-EXACT (10 block(s) stored; .txt vs .seq vs the emitter's StateImage)
```

and the four token artifacts reproduce **the token streams G4a recorded**
(`evidence/qwen9b/g4/G4A_REPLAY.md` §4.1), unchanged by the ISA:

| artifact | tokens, G4a | tokens, S3 |
|---|---|---|
| `tok9b_s1` | `[2380, 6362]` | `[2380, 6362]` |
| `tok9b_s2` | `[5290, 4397]` | `[5290, 4397]` |
| `tok9b_s3` | `[1235, 4971]` | `[1235, 4971]` |
| `tok9b_s4` | `[5591, 703]` | `[5591, 703]` |

That is the campaign's acceptance bar — the token-identical replay — at the
smoke's scale, and it is the first evidence for it: the schedule, the
two-slot caches, the DDR round trips and the retired preamble change WHERE
the state lives and change no token.

**10 blocks stored per artifact**: DN layer 0, conv layer 0, and the eight
KV blocks of attention layer 0 (4 kvheads x K/V).

### 7.2 The layer family at v2.1

**M**, `evidence/qwen9b/s3/047_layer_family_committed.log` — the
COMMITTED-tree run (fix round 1, I1; `006` ran at `28c89e4+dirty`, before
`c34d093` committed 380 lines of `tb/tb_layer_chan.sv` and before `7c821a9`
changed the emitter). rc 0, on snoke, at `FABLE5_MODEL=9b FABLE5_RS_F=7`,
`LAYERV2_SEEDS="1 2 3 4"`, `GENPY=/home/cah/.venv/bin/python` (the repo's
`ref/.venv` is a dangling symlink there):

```
TB_LAYER_CHAN PASS: 1465 cmds, 261357 checks bit-exact (scripts/layerv2_s1.txt)   ... s2, s3, s4
TB_LAYER_ENV PASS: every envelope check fired                                     x4
```

and now with the state model's own counter beside it, `state: … 0 unmapped`
(fix round 1, M2).

**261,357 checks — the SAME NUMBER G3.4 measured**
(`evidence/qwen9b/g3/G3_4_LAYER.md`, `TB_LAYER_CHAN PASS: 1438 cmds,
261357 checks bit-exact ×4`). The check count could not move: the R and E
records come from `dn_token`/`attn_token`, which S3 does not touch, and the
commands S3 retired emitted none. **The COMMAND count did move, 1438 →
1465, and it is accounted for exactly** —
`evidence/qwen9b/s3/048_opcode_delta_committed.log` re-emits the pre-S3
script from a copy of the generator at `07eea51` and histograms both. Both
emissions run **on snoke** and the script is committed
(`evidence/qwen9b/s3/opcode_delta.sh`), which `023` was not — it ran a
here-document at `c34d093+dirty` with the pre-S3 emission on darthplagueis
(fix round 1, I1 and C1):

| opcode | pre-S3 | S3 |
|---|---|---|
| 5 CONVW/CONVZ | **5** (4 CONVW chunks over `CONV_DIM = 8192` + 1 CONVZ) | 0 |
| 12 DNZ | **32** | 0 |
| 13 SLD | 0 | **34** |
| 14 SST | 0 | **30** |
| 6 CONV / 8 DNST / 9 KVAP / 10 ATTN | 3 / 96 / 12 / 48 | unchanged |

`1438 − 37 + 64 = 1465`, and the script asserts it:
`OPCODE_DELTA: PASS (1438 -> 1465 accounted for exactly)`. The DNZ-heavy
and CONVW cases are gone; the
DNST / ATTN / CONV / GATE / VN / VNW / ROPE / ALU cases are untouched, which
is why the golden count is unmoved.

**`tb_layer_env` was re-based, not merely re-run.** Two families moved with
the ISA: the `dn_slot 24 has no bank` cases are gone with the banks, and
their replacement is B15.2's `E_LAYER` — a LAYER slot field ABOVE 1 names a
cache slot that does not exist — with one case per field (dn, kv, cv); and
CONVW sel 0/1 is RETIRED (B15.5), so the two cases that used to be legal are
now refusals and CONVW sel 2 (CONVZ) carries the legal half. Every check
still FIRES, which is the property the target exists for:

```
  ENV REFUSED (err_op=1) as required: CONVW sel 0 (weight load) is RETIRED
  ENV REFUSED (err_op=1) as required: CONVW sel 1 (state load) is RETIRED
  ENV REFUSED (err_op=1) as required: DNZ at dn_slot 2 (E_LAYER)
  ENV REFUSED (err_op=1) as required: DNST at dn_slot 2 (E_LAYER)
  ENV REFUSED (err_op=1) as required: ATTN at kv_slot 2 (E_LAYER)
  ENV REFUSED (err_op=1) as required: CONV at cv_slot 2 (E_LAYER)
```

**`tb_layer_dnbank` is RETIRED**, with `run_dnbank`. It proved that the 24
DN banks, the 8 KV banks and the 24 conv banks were INDEPENDENT and that
every one of them really stored; there is no bank array left to prove
independent. The property moved to the DDR image — where
`ref/seq_model.StateRegion` and the SEQ gate's `STATE` comparison hold it —
and to `tb/tb_layer_sdma.sv` (S2), which round-trips a block of every kind
through the real DMA. Both retirements carry a comment naming S3 and the
spec section.

### 7.3 `tb_seq_chip` 9B smoke

**M**, `evidence/qwen9b/s3/052_tb_seq_chip_committed.log`, tree `a0ad071`
clean, on snoke, rc 0 (`033` is the round-0 run at `d0e4ae9`; both agree).
Four seeds, four launches:

```
LAUNCH 0 PASS: [-] pc 4090, tokens 0, tcnt 8, scratch 36864, smem 10        x4
  state: 55344 read beats, 36976 write beats, 0 unmapped                    x4
TB_SEQ_CHIP PASS: scripts/w9/lay9b_s<n>.e4 (launches 1, 3644824 cycles ...) x4
```

**`smem 10`** is the whole chain closing: the emitter scheduled the
transfers, `ref/seq_model.StateRegion` executed them and hashed the ten
blocks the run stored, and `rtl/state_dma` moved the same bytes through
`tb/seq_mem_file`'s new write window — FNV-1a 64, computed in Python and in
SystemVerilog, equal.

**`0 unmapped`** is the check S3 added in review: every one of the 55,344
read beats and 36,976 write beats landed INSIDE
`[win_base, win_base + win_len)`. An address the DMA computed outside the
region would have been served as zeros before; it is now a counted miss AND
a `$fatal`.

**3,644,824 cycles** against G4a rung A's **3,782,887** for the same
artifact shape (`evidence/qwen9b/g4/G4A_REPLAY.md` §5.1) — **138,063 fewer,
3.6 %**. The retired CONVW/DNZ preamble is most of it. This is one seed of
a one-layer smoke and is NOT the layer-term measurement (that is S4's
census); it is recorded because it moves in the direction spec §9 predicted
and by a plausible amount, not as a claim about the model.

### 7.4 The boardfree triple

```
evidence/qwen9b/s3/007_boardfree.log    rc 0
  seq_run selftest: 2759 passed, 0 failed
  serve selftest: 85 passed, 0 failed
  chat_seq selftest: 356 passed, 0 failed
  SELFTEST_RCS seq=0 serve=0 chat=0
  BOARDFREE_PASS
```

**2759 / 85 / 356 at round 0 — unmoved** from G3.4 and from S1.

**Fix round 2 measures the new triple on the COMMITTED tree**:
`evidence/qwen9b/s3/068_boardfree_committed_r2.log`, on snoke, tree
`297060a` clean, rc 0 —

```
  seq_run selftest: 2785 passed, 0 failed
  serve selftest: 85 passed, 0 failed
  chat_seq selftest: 364 passed, 0 failed
  SELFTEST_RCS seq=0 serve=0 chat=0
  BOARDFREE_PASS
```

**2785 / 85 / 364.** (Round 1 quoted that triple from
`041_boardfree_fix1.log`, which ran at `bcedefb+dirty` two minutes before
the fix commit and whose `chat_seq` `[21]` block had not landed — it says
`2785 / 85 / 356`. The number was right for `seq_run` and wrong for
`chat_seq`, and it traced to no log; fix round 2, I7.)

**`ref/seq_model.py --selftest` on the committed tree**, which had never
run in committed evidence:
`evidence/qwen9b/s3/069_seq_model_selftest_committed.log`, on snoke, tree
`297060a`, rc 0 — `STATE REGION (21 checks): … the 3/3 range refusals, and
the STATE verdict's 1/1 RED (a missing emitter image is NOT bit-exact) —
PASS`, beside the pre-existing DYNQ16 / EPS-NORM / W8 MVGO / REPACK blocks. The +26 and +8 are the tests item I7 asked for and
nothing else: `sw/seq_run.py`'s new `--- S3: the DDR state region` block
(the plan, I4's three refusals, the DN witnesses, `tok_meter`'s label-D law,
and the CSR/DMA paths against a fake device) and `sw/chat_seq.py`'s new
`[21]` block (the conv witnesses, the session memset and its readback).
**The pin catches a BROKEN frozen path, not a new test** — that is the
round's own ruling — and no pre-existing check moved: `serve` is unmoved at
85 and every one of the 2,759 and 356 that existed before still passes.

One `sw/seq_run.py`
check moved WITH the code it checks and is stated here rather than left to
be noticed: "every MANIFEST_META_KEY has a default" now reads
`set(MANIFEST_META_KEYS) == set(_META_DEFAULTS) | set(MANIFEST_STATE_KEYS)
== set(split_manifest({})[1]) and split_manifest({})[1]["state"] is None`. The
property is the one it always was — every meta key is answered by
`split_manifest`, so no consumer has to know which manifest generation it is
reading — and the check count is the same.

### 7.5 The SLD/SST envelope

**M**, `evidence/qwen9b/s3/054_envelope_sdma_committed.log`, tree
`a0ad071` clean, on snoke, rc 0,
**`G4A_ENVELOPE: PASS (0 problem(s))`** over all eight artifacts (`034` is
the round-0 run). Per
artifact, per kind, every field AT OR INSIDE its B15.1 ceiling — and the
`layer` maxima say plainly that a smoke artifact exercises only layer 0,
which is why the 224-per-token census (§4) is measured on the SCHEDULE and
not on these streams:

```
  SDMA      44 SLD/SST records (24 SLD, 20 SST)              [the four lay9b]
  SDMA      kind DN n=5     slot max 0/1  layer max 0/23  head max 0/0
  SDMA      kind KV n=34    slot max 1/1  layer max 0/7   head max 7/7
  SDMA      kind CV n=5     slot max 0/1  layer max 0/23  head max 0/0
  SDMA RED  rec 29 forced to kind 3 -> REFUSED: rec 32: SLD kind 3 is reserved (B15.1)
```

(the four `tok9b` carry 22 records, 12 SLD + 10 SST). The KV `head max 7/7`
is the ceiling exactly: `{kvhead[1:0], kv}` reaches 7 at kvhead 3, V. **The
RED fires on every artifact**, which is what keeps the GREEN from being a
clause that never ran. The MVGO half is unchanged and still reports
`MAX ng 96 of MAX_NG 96 — EXACTLY at the ceiling`.

---

## 8. Step 5′ — the citation-drift pass S1 and S2 left open

S1 left ≈ 94 citations stale in 18 documents (`evidence/qwen9b/s1/S1_ISA.md`
§6.4) and S2 left 237 drifted / 89 unresolved / 19 half-mapped across 40
(`evidence/qwen9b/s2/S2_RTL.md` §7.6); neither ran a `--fix`, because the
tool refused both as UNSAFE. S3 edits the same two files S1 did and adds
fifteen of its own, so the pass is done ONCE here, after S3's own edits, in
**three passes at three bases over three DISJOINT edited sets** — which is
what makes each line map exact.

| # | edited set | base | `--plan` | with exclusions | `--fix` | `--verify` |
|---|---|---|---|---|---|---|
| 1 | `ref/seq_format.py`, `sw/hwmap.py` (S1's + S3's edits) | `e905cd3` | `010`: REPAIR 90 / COLLATERAL 22 → **UNSAFE** | `011`: 47 / 0 → **SAFE** | `012`: **91 citations in 11 documents** | `013`: **VERIFY PASS (0 problems)** |
| 2 | S2's ten RTL/TB/synth files | `a51bc8e` | `018`: 263 / 12 → **UNSAFE** | `019`: **SAFE** | `020`: **212 citations in 25 documents** | `021`: VERIFY FAIL (32) |
| 3 | S3's fifteen own files | `07eea51` | `014`: 501 / 19 → **UNSAFE** | `015`: 214 / 0 → **SAFE** | `016`: **376 citations in 35 documents** | `017`: VERIFY FAIL (47) |

**679 citations repaired.** The exclusion lists are exactly the documents
whose `--plan` reported non-zero COLLATERAL — i.e. the documents a previous
pass had already repaired by hand, which is S1's §6.4 rule generalised and
applied mechanically rather than from a remembered list. For pass 1 the two
lists COINCIDE: the seven documents with collateral are S1's five plus the
two its reviewer added (`docs/ARCHITECTURE.md` and this plan), which is the
cross-check that the rule and the list say the same thing.

### 8.1 What is left, and why it cannot be renumbered

Pass 1 verifies clean. Passes 2 and 3 leave **79 entries, every one in the
same class**: the cited line names code S2 or S3 **DELETED** — the DN/KV/conv
bank arrays, `DN_PIPE`, the 24-bank conv memories, the CONVW preamble loop,
the 768 `dnz`, `run_dnbank`, `tb_layer_dnbank`. `--fix` never rewrites an
unresolved line and must not: a citation renumbered onto unrelated code is
worse than a stale one (`evidence/qwen9b/g3/G3_4_LAYER.md` §15.5, and the
tool's own header records the same failure).

**The class-B repairs S3 made** (keep the base number and the quotation, add
a dated note naming the successor):

| document | what |
|---|---|
| `docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md` | ONE dated note at the head of Task S3, with a successor table covering all **36** of its unresolved coordinates — they are this task's own instruction coordinates and are pre-S3 by construction |
| `ref/gen_layer_script.py` (`dnz`'s six-caller comment) | the five caller coordinates kept, with a note that the 768-DNZ preamble is retired and every caller is now `sched_preamble` |
| `ref/seq_chat.py`, `sw/infer.py` | the `ref/gen_model_script.py:589-595` and `ref/gen_model_script.py:590-595` ranges kept, with a note that the range also covered the retired preamble and naming the surviving half |

**The rest, listed by name** — 40 entries whose citers belong to other
tasks' closed gates, left at their base numbers with no note, because
writing a class-B note into another gate's document is that gate's call:

> **THAT CALL WAS MADE AT SHIP TIME — dated note 2026-09-10 (pre-ship
> documentation chore).**  The 40 split cleanly by whether a checker can
> see them.  The ones that carry a QUOTATION of the deleted source are the
> ones `evidence/qwen_next/spec_cites.py` fails, and each has now been
> dispositioned **in its own gate's document**, by that document's own
> rule — a dated class-B note naming the post-S2/S3 landmark, or a
> re-anchor where the construct merely moved:
> `evidence/qwen9b/g3/G3_4_LAYER.md`, `evidence/qwen9b/g4/G4B_STRUCT.md`,
> `evidence/qwen9b/s2/S2_RTL.md` and `evidence/qwen9b/g2/G2C_CHAIN.md`.
> The remainder carry **no quotation**, so no checker fails them and a note
> would add nothing a reader of this table does not already have: they stay
> at their base numbers, and this section is where they are enumerated.
> Nothing in the paragraph above is retracted — S3 was right not to write
> into another gate's document mid-campaign; the ship is when it gets done.

| citer | unresolved | which base |
|---|---|---|
| `evidence/qwen9b/g3/G3_4_LAYER.md` | 7 + 1 | S2, S3 |
| `evidence/qwen9b/g5/G5A_FLOORPLAN.md` | 6 | S2 |
| `evidence/qwen9b/g4/G4B_STRUCT.md` | 6 | S2 |
| `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md` | 6 + 4 | S2, S3 |
| `evidence/qwen9b/g2/G2C_CHAIN.md` | 3 | S3 |
| `docs/QWEN35_NEXT_FEASIBILITY.md` | 1 + 2 | S2, S3 |
| `evidence/qwen9b/g4/G4A_REPLAY.md` | 1 + 2 | S2, S3 |
| `evidence/qwen9b/g4/{tb_layer_census.sv, run_g4b_census.sh, g4b_layer_term.py}` | 1 each | S2 |
| `evidence/qwen9b/g3/G3_2_VECNORM.md`, `evidence/qwen9b/g1/RUNG_INT8_STATE.md`, `evidence/qwen2b/rb/seq_isa_ref_sweep.txt`, `evidence/qwen_next/feas/resource_budget.py`, `evidence/qwen9b/g2/G2A_HOST.md`, `evidence/qwen9b/g2/g2c_pack_fit.py`, `docs/SEQ_ISA.md`, `docs/superpowers/plans/2026-08-12-qwen2b-track-r.md` | 1 each | S2, S3 |
| `rtl/layer_chan.sv` (two of its own comments) | 2 | S2 |
| `synth/exp_uram/scripts/exp_ooc.tcl` | 3 | S2 — **deliberately left**, see below |

### 8.1a One drift edit did NOT ride in the drift commit

`f3f4dec` is the citations-only commit, and the state-spill plan is NOT in
it: pass 3's `--fix` renumbered that document too, and those renumbers rode
in `7c821a9` beside S3's own class-B note, because the plan was in that
commit's pathspec for the note. Stated because a reader diffing `f3f4dec`
for "every citation this pass moved" would come up one document short
(fix round 1, M7).

### 8.1c Fix round 2 re-ran it AGAIN, at the base the plan names

**Round 1's re-anchor used the wrong base and cemented the error.** It ran
at `f3f4dec`, but `7c821a9` had inserted the 8-line `dnz` comment BEFORE
`f3f4dec` — so at that base the citations were already stale, the tool
preserved the 8-line shift, and its `VERIFY PASS (0)` was vacuous. Worse,
three citations that were ALREADY wrong at `07eea51` were RELOCATED onto
new, unrelated code.

The pass is redone at the base the plan's Global Constraints name,
**`07eea51`**, and the mechanical half is scoped to what a mechanical pass
can honestly own:

1. **The 18 documents whose ONLY change since `07eea51` is citation
   numbers** were restored with `git checkout 07eea51 -- <doc>` (the test
   is mechanical: the texts are equal once every `:\d+` is normalised) and
   the pass re-run over them at `07eea51`:
   `064` `--plan` **SAFE**, `065` `--fix`, `066` `--verify` **FAIL 4** —
   and all four are the class-B `ref/gen_model_script.py:590/595/596/597`
   set, the retired CONVW/DNZ preamble, which `--fix` must not renumber.
2. **The documents with real content changes are EXCLUDED** from the
   mechanical pass and their named-wrong sites are hand-repaired (below).
   A `--fix` cannot serve them: their citations are in post-round-1
   coordinates, so a second base-`07eea51` map would double-shift.
3. `062_cite_drift_verify_at_07eea51.log` is the MEASUREMENT that motivated
   the scoping: `--verify` at `07eea51` over the whole set, before any
   repair, reports **739 problems** — that is the size of "the working
   documents do not carry `07eea51`→HEAD numbers", and it is why the
   round-1 claim of a clean bulk verify was wrong.

**The sixteen sites the review named, with their true lines at HEAD:**

| citer | named | the true site |
|---|---|---|
| `evidence/qwen9b/g2/g2c_pack_fit.py` (13 citations) | lines in `ref/gen_layer_script.py` that had become the wrong ones | **twelve** of the thirteen were restored + re-fixed at `07eea51` and each names the `matvec` call it describes — `ref/gen_layer_script.py:1945` for `in_qkv`, `ref/gen_layer_script.py:1947` for `in_z`, `ref/gen_layer_script.py:1949` for `in_b`, `ref/gen_layer_script.py:1951` for `in_a`, `ref/gen_layer_script.py:2047` for `out`, `ref/gen_layer_script.py:2068` / `ref/gen_layer_script.py:2070` / `ref/gen_layer_script.py:2072` for q/k/v_proj, `ref/gen_layer_script.py:2154` for `o_proj`, `ref/gen_layer_script.py:2174` for `gate`, `ref/gen_layer_script.py:2176` for `up`, `ref/gen_layer_script.py:2188` for `down`.  The **thirteenth**, the LM head at `evidence/qwen9b/g2/g2c_pack_fit.py:95`, pointed into the OTHER emitter and the drift pass never touched it: it named `ref/gen_model_script.py:596`, a comment, and was already wrong at `07eea51`.  Fix round 3 hand-repaired it to `ref/gen_model_script.py:634`, `y32, _ = M.matvec(qw_head, X8, H, rowchunk=ROWCHUNK)` — so the sentence holds for all thirteen only from §8.1c onward (see `O2`). |
| `evidence/qwen_next/feas/toks_model.py` (2 citations) | a line that had moved | restored + re-fixed: **`ref/gen_layer_script.py:2002`**, the per-head emit loop |
| `evidence/qwen_next/feas/layer_cmd_census.py` (2 citations) | the same line | hand-repaired: **`ref/gen_layer_script.py:2002`** |
| `ref/scripts/bytes_per_token.py:145` | `ref/seq_format.py:1849` (a round-1 relocation onto unrelated code) | hand-repaired: **`ref/seq_format.py:2014`** `layout = LAYOUT_ILV if amax` |
| `docs/superpowers/plans/2026-08-12-qwen2b-track-r.md:67` | `sw/chat_seq.py:441-462` (a round-1 relocation) | hand-repaired: **`sw/chat_seq.py:579`** `def derive_geometry` |
| `docs/QWEN35_NEXT_FEASIBILITY.md` (3 citations) | `ref/gen_layer_script.py:502` (a round-1 relocation) | hand-repaired: **`ref/gen_layer_script.py:918`** `assert (1 << nlog2) == n` |

**The count, corrected.** Round 0 repaired 679 and round 1 repaired 343,
but round 1's were computed at the wrong base, so **"1,022 repaired" is
withdrawn**. What this gate can claim, and what the logs show, is: 679 at
round 0 (`012`/`016`/`020`, `013` verified clean), the round-1 pass
superseded, and round 2's re-anchor at `07eea51` over the 18
citations-only documents (`065`) with `066` `VERIFY FAIL 4`, all four the
class-B `gen_model_script` set, plus the six hand repairs above.

### 8.1c′ Fix round 3 — what the `07eea51` RESTORE cost, and the repair

**Disclose first: the restore in §8.1c was not free, and round 2 did not say
so.** `git checkout 07eea51 -- <doc>` returns a document to its `07eea51`
text. For the 18 restored documents that discarded round 0's *earlier*
passes — pass 1 at base `e905cd3` (S1's files) and pass 2 at base `a51bc8e`
(S2's RTL) — because those repairs live in the working text, not in
`07eea51`. Re-anchoring at `07eea51` cannot bring them back: the tool maps
`07eea51 → HEAD`, and a citation that was already correct in `e905cd3` or
`a51bc8e` coordinates is not on that map. **Six citations that were right
at `05b0d70` are wrong at HEAD as a result**, with the code they name
unmoved:

| citer | HEAD said (wrong) | the true site, and its text |
|---|---|---|
| `evidence/qwen_next/feas/toks_model.py:59` | `ref/seq_format.py:1042` | **`ref/seq_format.py:1126`** `CHUNK_ROWS = 2048` |
| `evidence/qwen_next/feas/toks_model.py:232` | `rtl/layer_chan.sv:1209` | **`rtl/layer_chan.sv:1513`** `dn_head <= arg0[4:0];` |
| `evidence/qwen9b/g5/G5A_FLOORPLAN.md:1014` | `rtl/layer_chan.sv:508` | **`rtl/layer_chan.sv:613`** `logic [2047:0] dn_rdq, dn_wrd;` |
| `evidence/qwen9b/g4/tb_layer_census.sv:7` | `rtl/layer_chan.sv:26` | **`rtl/layer_chan.sv:28`** `0x34 LCYC R cycles elapsed while busy==1` |
| `evidence/qwen_next/feas/resource_budget.py:215` | `rtl/layer_chan.sv:1534` | **`rtl/layer_chan.sv:1870`** `if (cvi == arg0[27:14]) st <= CV_D;` |
| `evidence/qwen_next/feas/resource_budget.py:216` | `rtl/layer_chan.sv:1581` | **`rtl/layer_chan.sv:1917`** `if (wi + 1'b1 == arg0[29:16]) st <= DONE_S;` |

Two consequences the round-2 tree also carried: `evidence/qwen9b/s1/S1_ISA.md`
records the `:1042 → :1126` repair the tree no longer had, and
`evidence/qwen_next/feas/layer_cmd_census.py:26`, which names
`rtl/layer_chan.sv:1513`, was out of step with its sibling
`evidence/qwen_next/feas/toks_model.py:232`, which named line 1209, again.

**The repair, per base, over the restored set only.** The 18 are the 14 the
normalisation test still finds changed (`080`, `evidence/qwen9b/s3/cite_scope.py`)
plus the four it cannot see because they are byte-identical to `07eea51` —
`evidence/qwen9b/g4/tb_layer_census.sv`, `evidence/qwen9b/g5/G5A_FLOORPLAN.md`,
`evidence/qwen9b/o3/BOARD_LOCK.md`, `evidence/qwen_next/feas/resource_budget.py`.
Being identical to the base IS the regression: round 2 restored them and the
`07eea51` pass found nothing to move.

| log | base | what it did |
|---|---|---|
| `evidence/qwen9b/s3/081_cite_drift_plan_e905cd3_18.log` | `e905cd3` | `--plan`: REPAIR 46 / COLLATERAL 62 → **UNSAFE in bulk**; only `evidence/qwen_next/feas/toks_model.py` was SAFE |
| `evidence/qwen9b/s3/082_cite_drift_fix_e905cd3_18.log` | `e905cd3` | `--fix` on that one file: **FIXED 1** |
| `evidence/qwen9b/s3/083_cite_drift_plan_a51bc8e_18.log` | `a51bc8e` | `--plan` over S2's RTL set |
| `evidence/qwen9b/s3/084_cite_drift_fix_a51bc8e_18.log` | `a51bc8e` | **FIXED 15 in 5 documents** |

**Then every one of the 16 mechanical changes was checked against the text it
quotes, and EIGHT were reverted.** A base-relative map is only valid for a
citation written in THAT base's coordinates; these documents also hold
citations already in HEAD coordinates (round 2 had just re-anchored them) and
citations PINNED to an older tree, and the map shifts both off their target.
The eight, and what they are now:

| was, after the mechanical pass | restored to | why |
|---|---|---|
| `evidence/qwen2b/rc/RC_GATE.md`, line 935 of `rtl/layer_chan.sv` | **`0455999:rtl/layer_chan.sv:545`** + `0455999:rtl/vec_alu.sv:104` | `.cfg_len(arg0[15:4])` died at `1adc5c4`; the RC bug is a historical narrative, so it is pinned to the tree that carries it |
| `evidence/qwen_next/feas/resource_budget.py`, lines 562 / 628 / 563 of `rtl/layer_chan.sv` | **`8138d66:rtl/layer_chan.sv:457`**, **`8138d66:rtl/layer_chan.sv:522`**, **`8138d66:rtl/layer_chan.sv:458`** | `gd < 9`, `gk < 3`, the 2048-b DN row — the 2B as-built, retired by G3.4 |
| `evidence/qwen_next/feas/resource_budget.py`, `8138d66:rtl/layer_chan.sv:1027` | **`8138d66:rtl/layer_chan.sv:882`** | an already-PINNED citation the map shifted anyway |
| `evidence/qwen_next/feas/resource_budget.py`, lines 1508 / 1583 of `rtl/layer_chan.sv` | **`d2d774b:rtl/layer_chan.sv:1204`** and **`d2d774b:rtl/layer_chan.sv:1251`** | the 13-bit CONV quotations; Task 10 called these "the 8138d66 line numbers" — they are not, they are `8ef57a8^`'s, and they are now pinned there |
| `evidence/qwen_next/feas/toks_model.py`, line 1036 of `rtl/layer_chan.sv` | **`d2d774b:rtl/layer_chan.sv:891`** | the pre-G3.1 `dn_head` assignment, same misattribution, same fix |

**Eight** were right and stand, including the six the review named — 8 + 8 =
the 16. *(This paragraph said SEVEN reverted and nine standing until
2026-09-10; the table above lists eight in its left column, restored to the
nine pinned coordinates on its right.)* While the
lines were open, the **bare `:NNN` continuations** on them were spelled out
at their true sites — `lcyc` declared at `rtl/layer_chan.sv:475` and
incremented at `rtl/layer_chan.sv:1055`, `dn_rdq` assigned at
`rtl/layer_chan.sv:781`, the second `DONE_S` at `rtl/layer_chan.sv:1933`,
`rtl/dn_step.sv:1` and `rtl/dn_step.sv:13-14`.

**Six correct hand repairs rode in the same commit and were not disclosed
until 2026-09-10.**  Neither file is in the mechanical pass's `fixed` list
(`082` and `084` name only `evidence/qwen2b/rc/RC_GATE.md`,
`evidence/qwen9b/g4/tb_layer_census.sv`,
`evidence/qwen9b/g5/G5A_FLOORPLAN.md`,
`evidence/qwen_next/feas/resource_budget.py` and
`evidence/qwen_next/feas/toks_model.py`), so these were typed, and a
declared-block campaign has to say so:

| document | was | is |
|---|---|---|
| `docs/SEQ_ISA.md` B7 heading | `rtl/layer_chan.sv:12-31` | `rtl/layer_chan.sv:12-33` |
| `docs/SEQ_ISA.md` B7 opcode line | lines 85-116 of the same file, named without a directory | `rtl/layer_chan.sv:140-185`, with the path written in *(this row said 140-157 until 2026-09-10; `bedac96`, three commits later in the same chore, extended the end to 185 — the opcode list runs to `12 DNZ` — and this cell is corrected to what the document now carries)* |
| `docs/SEQ_ISA.md` B12.1 heading | `rtl/layer_chan.sv:69-116` | `rtl/layer_chan.sv:120-157` |
| `evidence/qwen_next/feas/addrmap_options.py` EMB base | `sw/hwmap.py:387` | `sw/hwmap.py:481` |
| `evidence/qwen_next/feas/addrmap_options.py` the abort message | `sw/hwmap.py:645` | `sw/hwmap.py:749` |
| `evidence/qwen_next/feas/addrmap_options.py` the EMBLOG2 bounds print | `sw/hwmap.py:272` | `sw/hwmap.py:338` |

All six name the same construct before and after; none is class B.

**Four more in `evidence/qwen9b/g5/G5A_FLOORPLAN.md` and two elsewhere were
PINNED, not re-anchored** (`0455a20`): `a51bc8e:rtl/layer_chan.sv:337`
(`DN_P2WAIT`), `a51bc8e:rtl/layer_chan.sv:521` (the `dn_step`
instantiation), `a51bc8e:rtl/layer_chan.sv:640-643` (`g_lmux`),
`a51bc8e:rtl/layer_chan.sv:712-724` (the KV write fan-out),
`a51bc8e:rtl/attn_core.sv:69` (`sc_mem [512]`) and
`a51bc8e:rtl/attn_core.sv:13` (`T <= 512`, now `T <= 4096`). G5a MEASURED
that RTL; S2's two-slot rewrite deleted those lines, so re-anchoring would
repoint a measurement at code it never ran against.
`evidence/qwen9b/g4/tb_layer_census.sv`'s `DN_P2WAIT` citation is pinned for
the same reason, with the retirement
recorded next to it (`rtl/layer_chan.sv:377`, literals at
`rtl/layer_chan.sv:627`).

**`--verify` at each of the three bases, on the repaired tree** (`0455a20`;
the commit after it adds `sha:` prefixes and prose only, which the tool
ignores):

| log | base | global | naming one of the 18 |
|---|---|---|---|
| `evidence/qwen9b/s3/089_cite_drift_verify_e905cd3_final.log` | `e905cd3` | `VERIFY FAIL 115` | **1**: `sw/hwmap.py:230`, cited by `evidence/qwen9b/o3/BOARD_LOCK.md` |
| `evidence/qwen9b/s3/090_cite_drift_verify_a51bc8e_final.log` | `a51bc8e` | `VERIFY FAIL 418` | **10**, **8** of them PINNED citations (the tool reads the path after the `sha:` prefix and reports it as drifted, which is exactly what a pin means): `rtl/attn_core.sv:13`, `rtl/attn_core.sv:69`, `rtl/layer_chan.sv:337`, `rtl/layer_chan.sv:521`, `rtl/layer_chan.sv:640`, `rtl/layer_chan.sv:643`, `rtl/layer_chan.sv:712` and the half-mapped `rtl/layer_chan.sv:712-724`. The other **two are not pins** — `rtl/layer_chan.sv:69` and the half-mapped `rtl/layer_chan.sv:69-116`, both `docs/SEQ_ISA.md`'s citation of the in-RTL ISA copy, which is class B at its base number |
| `evidence/qwen9b/s3/091_cite_drift_verify_07eea51_final.log` | `07eea51` | `VERIFY FAIL 652` | **3**: `ref/gen_model_script.py:596`, attributed to `evidence/qwen9b/g2/g2c_pack_fit.py` because the citer list is built at `--doc-base` — at HEAD that file names `ref/gen_model_script.py:634` — plus `ref/gen_layer_script.py:1116` and `tb/tb_seq_chip.sv:88`, both cited by `evidence/qwen9b/o3/BOARD_LOCK.md` |

*(The right-hand column read 0 / 10 / 1 and "every one of them a PINNED
citation" until 2026-09-10. Recounted by grepping the three logs' `!` lines
for the eighteen restored documents: it is 1 / 10 / 3, and the pin claim
holds for 8 of the 10.)*

The global counts are the campaign-wide residue §8.1 is about and are NOT
this task's to clear; what is this task's is the column on the right.

**The count, corrected again.** "679 citations repaired" was round 0's number
and it no longer describes HEAD: the `07eea51` restore discarded an unmeasured
part of it, round 2's `065` re-fixed 425 at that base, and round 3 fixed 16
mechanically, reverted 8, and pinned 9 by hand. **What holds at HEAD is what
`089`/`090`/`091` show**, and no aggregate "repaired" number is claimed.

### 8.1b Fix round 1 re-ran the pass, because the output had gone stale

`7c821a9` inserted an 8-line class-B comment into `ref/gen_layer_script.py`
AFTER the `--fix`/`--verify` runs, and this round's own edits moved nine
files further, so 39 citations below the insertion point named the wrong
line. The pass was re-run at base **`f3f4dec`** — the tree the first pass
PRODUCED — over exactly the files changed since, so the line map covers the
insertions and nothing else:

| | |
|---|---|
| `042` `--plan` | REPAIR 365 / COLLATERAL 20 → **UNSAFE** |
| `043` `--plan`, six documents excluded | **SAFE** |
| `044` `--fix` | **343 relocated** |
| `045` `--verify` | FAIL 1 — `sw/hwmap.py:564` (I4 rewrote that docstring) cited by `evidence/qwen9b/s1/S1_ISA.md` |
| hand repair | class B: the citation re-anchored to the whole `STATE_*` block, with a dated note naming `plan_state_base` and `state_dn_witnesses` |
| `046` `--verify` | **`O3_CITE_DRIFT VERIFY PASS (0 problem(s))`** |

~~**1,022 citations repaired across the two rounds** (679 + 343).~~
**WITHDRAWN by fix round 2** — round 1's 343 were computed at a base at
which the shift already existed; §8.1c states what the logs show instead.

### 8.2 One `--fix` was REVERTED, on purpose

The pass-2 `--fix` renumbered a citation inside **`synth/exp_uram/rtl/layer_chan.sv`**
and two inside `synth/exp_uram/scripts/`. The plan's standing hazards say
that tree is **not refreshed** and that G5A already reverted such a refresh
as UNSAFE for citation drift
(`evidence/qwen9b/g5/G5A_FLOORPLAN.md`). Worse, the renumber was
half-done — the comment reads "BIT-IDENTICAL to `rtl/layer_chan.sv:554-559`
and a second range left at its old numbers", and S2's rewrite makes the
CLAIM false whichever numbers it
carries. **`git checkout -- synth/exp_uram/` was run**, so that tree is
byte-identical to `07eea51`, and its three stale citations are listed above
rather than repaired.

### 8.3 `spec_cites.py`'s PENDING set, pruned

S2's §7.6 handed over one more tidy-up: `evidence/qwen_next/spec_cites.py`
still listed `rtl/state_dma.sv`, `tb/axi_ram_bfm.sv`, `tb/tb_layer_sdma.sv`,
S2's gate doc and its first log, and four S3 paths, as PENDING ("a future
gate creates this"). They exist. PENDING is checked BEFORE EXIST, so a
stale entry lets a typo in the path — or a deletion of the file — pass
silently on every document that cites it; the nine landed paths are out.

---

## 9. On the committed tree

**Corrected 2026-09-04, fix round 1 (I1).** The first cut of this sentence
claimed every gate below ran on a clean committed tree, and for five of them
it was FALSE: `006` (the layer family) ran at `28c89e4+dirty`, `023` (the
opcode delta) at `c34d093+dirty`, and `030`/`031`/`036` at `f3f4dec+dirty`
(there the dirt was `027`'s own tail). All five were RE-RUN in the fix
round, on snoke, and §9.2 carries them. Every number in this document is
read from the actual last line of the log named beside it.

| log | tree | what | verdict |
|---|---|---|---|
| `030_cold_red_green.log` | `f3f4dec+dirty` | `cold_red.py`, the RED script | `COLD_RED: GREEN`, rc 0 — re-run as `049` |
| `031_preamble_equiv.log` | `f3f4dec+dirty` | the preamble equivalence | `PREAMBLE_EQUIV: PASS` — re-run as `050` |
| `032_seqgate_smokes.log` | **`d0e4ae9` clean** | `ref/seq_model --gate` on the eight smoke artifacts | §7.1 |
| `033_tb_seq_chip_9b_smoke.log` | **`d0e4ae9` clean** | the chip replay, 4 seeds | §7.3 |
| `034_envelope_sdma.log` | **`d0e4ae9` clean** | the MVGO + SLD/SST envelopes on the eight | §7.5 |
| `035_boardfree.log` | **`d0e4ae9` clean** | the board-free triple | §7.4 — superseded by `041` |
| `036_sdma_census.log` | `f3f4dec+dirty` | the 224-per-token census | §4 — re-run as `051` |
| `037_spec_cites.log` | `4b0db6e` clean | `spec_cites.py` — the FIRST run | `SPEC CITES: FAIL`, 20 (§9.1) |
| `038_spec_cites.log` | `7ddc81f` clean | the same, after the twenty repairs | **`SPEC CITES: PASS`, FAIL 0** |

### 9.2 Fix round 1 — the re-runs, and the host of every log

**C1's host question, answered from the logs.** All 31 of the round-0 logs
carry `=== host: darthplagueis`, because `evidence/qwen9b/run.sh` runs where
it is invoked. What matters is what the WRAPPED COMMAND did, and the logs
split cleanly in two:

| the command | ran where | which logs |
|---|---|---|
| `ssh snoke …` — the wrapper is local, the WORK is on snoke | **snoke** | `006`, `027`, `032`, `033`, `034`, `041`, `047`–`051` |
| a local interpreter — numeric work on darthplagueis | darthplagueis | `001`–`005`, `007`, `022`, `023`, `030`, `031`, `035`, `036` |
| pure text (the drift tool, `spec_cites`) — no arithmetic | darthplagueis | `010`–`021`, `037`, `038`, `042`–`046` |

**Every artifact any gate consumed was emitted on snoke.** The eight smoke
artifacts came from `ssh snoke … make w9_9b_smoke_scripts
w9_9b_tok_smoke_scripts`, the four `layerv2_s*` from `ssh snoke … make
tb_layer_chan`, and every `.chip` golden from the same snoke recipes.
`ref/.venv/bin/python` — which S3's three aborted runs invoked — is a
DANGLING SYMLINK on snoke, so those three cannot have run there.

**The ten-run experiment — `040_emit_repeat_snoke_x10.log`, host snoke,
rc 0:**

```
  .txt              1 distinct sha over 10 run(s)   2fab6e5d042c3cbb…
  .e4.seq           1 distinct sha over 10 run(s)   b6ba7d8dcbadd11d…
  .e4.seqdata.bin   1 distinct sha over 10 run(s)   bfbc0c00bfcdccf6…
  .state_final.bin  1 distinct sha over 10 run(s)   ca6e6e7f1fb21d4e…
  --- against the reference emission tb/scripts/w9/lay9b_s1
  .txt / .e4.seq / .e4.seqdata.bin / .state_final.bin   ALL IDENTICAL
  EMIT_REPEAT: PASS 10 identical emission(s)
```

Ten sequential emissions of the same artifact on snoke agree with each
other **and with the artifacts the gates consumed**, which is the evidence
that the emission is reproducible on that host.

**But the artifacts WERE re-emitted, for a different reason** (fix round 2,
the new Important). Fix round 1's M6 changed `state["sha256"]` from a
digest of the emitter's keys to a digest of `<prefix>.state.bin`'s BYTES —
so **every artifact emitted before that change carries a manifest key that
`sw/seq_run.verify_state_image` would refuse** — the smoke seed 1
manifest said `d2b48091…` while its region image's bytes hash to something
else. (The artifacts are gitignored build products under `tb/scripts/w9/`,
so they are named in prose, not cited.) The eight smoke
artifacts were re-emitted on snoke under the now-WIRED emit-twice gate
(§9.4), which is also that gate's proof on real artifacts, and every gate
that consumes them was re-run. **`model_9b_s1`'s manifest is still stale
and is S4's**: S4 re-emits the model set, and `w9_9b_model_script` now runs
under the same gate.

| log | tree | what | verdict |
|---|---|---|---|
| `040_emit_repeat_snoke_x10.log` | `bcedefb` clean | ten emissions on snoke | **`EMIT_REPEAT: PASS 10 identical emission(s)`**, all four shas identical to the committed artifacts |
| `041_boardfree_fix1.log` | `bcedefb+dirty` | the board-free triple, on snoke | **`BOARDFREE_PASS` 2785 / 85 / 364** |
| `042`–`046` | HEAD | the drift pass re-run at base `f3f4dec` | 343 relocated, one hand repair, **`VERIFY PASS (0 problem(s))`** |
| `047_layer_family_committed.log` | committed | `tb_layer_chan` + `tb_layer_env` ×4, on snoke | §7.2 |
| `048_opcode_delta_committed.log` | committed | the layerv2 opcode delta, both emissions on snoke | **`OPCODE_DELTA: PASS (1438 -> 1465 accounted for exactly)`** |
| `049_cold_red_green_committed.log` | committed | `cold_red.py`, on snoke | `COLD_RED: GREEN` |
| `050_preamble_equiv_committed.log` | committed | the preamble equivalence, on snoke | `PREAMBLE_EQUIV: PASS` |
| `051_sdma_census_committed.log` | committed | the census, BOTH halves, on snoke | **`SDMA_CENSUS: PASS`**, `per token [224, 224, 224]`, and the STREAM half on all eight artifacts (M4) |
| `052_tb_seq_chip_committed.log` | `a0ad071` clean | the chip replay ×4, on snoke | §7.3 |
| `053_seqgate_smokes_committed.log` | `a0ad071` clean | the SEQ gate on the eight, on snoke | **`G4A_SEQGATE: ALL PASS (8 artifact(s))`**, every one `STATE BIT-EXACT (10 blocks)` |
| `054_envelope_sdma_committed.log` | `a0ad071` clean | the envelopes, on snoke | **`G4A_ENVELOPE: PASS (0 problem(s))`** |
| `055_spec_cites_fix1.log` | committed | `spec_cites.py`, **LAST** | §9.1 |

**`040`–`041` and `047`–`054` ran on snoke**; `042`–`046` and `055` are the
drift tool and `spec_cites`, which read text and compute nothing. No
arithmetic in this round ran on darthplagueis.

### 9.4 The re-emitted smoke set, under the wired gate

`evidence/qwen9b/s3/061_smoke_reemit_gated.log` — `make -C tb
w9_9b_smoke_scripts w9_9b_tok_smoke_scripts` on snoke, with
`W9_EMIT2 = 1`, so each of the eight artifacts was emitted, emitted AGAIN
into `scripts/w9/emit2/`, and accepted only after all four shas matched.

```
evidence/qwen9b/s3/061_smoke_reemit_gated.log   snoke, rc 0
  EMIT_REPEAT: PASS 1 identical emission(s)      x8
```

and the manifests are consistent with their images again. That was prose
in fix round 2; `evidence/qwen9b/s3/088_state_sha_manifest.log` is the run,
on snoke, over all eight artifacts, through
`sw/seq_run.verify_state_image` itself — the same refusal the host makes
before it writes a byte (spec 7.2). It prints BOTH digests per artifact:
for `lay9b_s1` the manifest's `state.sha256` and the sha256 of its
162,529,280-byte `.state.bin` are both
`36969da490db28c48693f0b9c50dd72ca8fedb40b5a2cb33605ff41b42054854`, where
the pre-M6 manifest said `d2b48091…`; the verdict line is
**`STATE_SHA: PASS — 8 match, 0 mismatch, 0 without a region`**. (The
artifacts are gitignored build products, so those paths are not citations.)
The four seeds give four distinct digests and `lay9b_sN` / `tok9b_sN` share
one per seed, which is the region's initial contents being a function of
the seed alone.

**Every gate that consumes the set, re-run on the committed tree, on
snoke:**

| log | what | verdict |
|---|---|---|
| `070_layer_family_r2.log` | `tb_layer_chan` + `tb_layer_env` ×4 | **`TB_LAYER_CHAN PASS: 1465 cmds, 261357 checks bit-exact` ×4**, **`TB_LAYER_ENV PASS` ×4** |
| `071_seqgate_smokes_r2.log` | the SEQ gate on the eight | **`G4A_SEQGATE: ALL PASS (8 artifact(s))`**, every one `STATE BIT-EXACT (10 blocks)`, tokens `[2380, 6362]` / `[5290, 4397]` / `[1235, 4971]` / `[5591, 703]` — **still G4a's** |
| `072_envelope_sdma_r2.log` | the envelopes | **`G4A_ENVELOPE: PASS (0 problem(s))`** |
| `073_sdma_census_r2.log` | the census, both halves | **`SDMA_CENSUS: PASS`**, `per token [224, 224, 224]` |
| `074_tb_seq_chip_r2.log` | the chip replay ×4 | **`TB_SEQ_CHIP PASS` ×4**, `smem 10` and `0 unmapped` in every launch |

**No number moved across the re-emission.** The same 261,357 checks, the
same 3,644,824 cycles, the same ten SMEM blocks per launch, the same
tokens — one manifest key changed and nothing else.

### 9.3 The tree column is CHECKED, not typed

Two cells of the table above were wrong in fix round 1 (`037` said
`7ddc81f`, its header says `4b0db6e`; `040` said `+dirty`, its header says
clean) — a table of 40-odd hand-copied shas is exactly the artefact that
goes stale. `evidence/qwen9b/s3/log_trees.sh` is five lines that read every
log's own `=== tree:` header, and
`evidence/qwen9b/s3/067_log_trees.log` is its output; the tables above are
read from it. Anyone can re-run it and diff.

The working runs that produced the same verdicts on a dirty tree are kept
beside them (`001`–`028`); where this document quotes a number it names the
log the number is read from.

### 9.1 `spec_cites.py`, LAST

`evidence/qwen_next/spec_cites.py` is run **LAST**, on the committed tree,
over every spec, plan and gate document this task edited:

```
evidence/qwen_next/spec_cites.py \
    evidence/qwen9b/s3/S3_CHAIN.md \
    docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md
```

`037_spec_cites.log` was the FIRST run and it FAILED with 20 problems; the
run that stands is `038_spec_cites.log`. Both are committed, because the
first one is the interesting one:

* **Four of the twenty were INHERITED** — the plan's two standing hazards
  about the layer CSR decoder and about `attn_core`'s T ceiling quote
  `case (awaddr_q)`, `sc_mem [512]`, `es_mem [512]` and
  `logic [9:0] t, T` beside pre-S2 line numbers. Measured, not
  assumed: `spec_cites.py` on the plan at `6522972` (the commit before
  S3's first) reports the same four. S3 repaired them — the successors
  really are the same four places, widened by S2 (spec A1.5), so this is a
  class-A repair with the quotations re-read, which is what
  `evidence/qwen9b/g3/G3_4_LAYER.md` §15.5 asks for when the code survived.
* **Nine were S3's own class-B table** in the plan's Task S3 head: it
  QUOTES the retired code (`_DN_SLOTS = 24`, `layer(dn_slot, kv_slot)`)
  beside the base numbers, on purpose. Those rows now carry the plan's own
  `<!--cites:noquote-->` marker, which is exactly what that marker is for.
* **Seven were this document's own** bare basenames, plus two BARE
  CONTINUATIONS — one on a line naming three files, one on a line naming
  none. Both are now written as full paths. The drift tool's own header
  warns about exactly that form, and S3 wrote two of them anyway.

```
evidence/qwen9b/s3/038_spec_cites.log
  S3_CHAIN.md                              SPEC CITES: PASS   (FAIL 0)
  2026-09-04-qwen35-9b-state-spill.md      FAIL 0
```

**Fix round 1, LAST, tree `6279103` clean** —
`evidence/qwen9b/s3/055_spec_cites_fix1.log`, now including
`evidence/qwen9b/s1/S1_ISA.md` (§8.1b's hand repair edited it):

```
checked: 710 exist, 328 range, 11 quote | pending 11 | retired 0 |
         noquote 37 | FAIL 0
SPEC CITES: PASS
```

**Fix round 2, LAST** — `evidence/qwen9b/s3/075_spec_cites_r2.log` at
`efd1cdd` and, on the round's final commit,
`evidence/qwen9b/s3/077_spec_cites_r2_final.log` at `7b3be17`:

```
checked: 753 exist, 348 range, 13 quote | pending 11 | retired 0 |
         noquote 37 | FAIL 0
SPEC CITES: PASS
```

It found two defects in THIS document first, both of the class §8.1c is
about: three bare continuations on lines naming two files (the AMBIG form
the drift tool's own header warns about), and a quotation no cited line
carries. Both were fixed before the run above.

**Two documents fix round 2 hand-repaired are NOT clean, and were not clean
before S3** — `evidence/qwen9b/s3/092_spec_cites_r3_prior_docs.log`
measures that rather than asserting it:
`docs/superpowers/plans/2026-08-12-qwen2b-track-r.md` and
`docs/QWEN35_NEXT_FEASIBILITY.md` report

```
checked: 405 exist, 184 range, 53 quote  |  pending 0  |  retired 1  |  noquote 20  |  FAIL 161
```

at HEAD against `checked: 393 exist … FAIL 164` at `07eea51`, the tree S3
started from. (`evidence/qwen9b/s3/076_spec_cites_r2_prior_docs.log` made
the same measurement in round 2 but piped it through `tail -2`, so the
`checked:` lines were in the command, not the log; `092` re-runs it
untailed. The exist count rises because round 3 spelled out a slash-joined
list of five citations in the plan.) They are campaign-wide documents
citing the whole tree; S3 touched five citations in them and left them
three better than it found them. Repairing the rest is not this task's,
and claiming they pass would be false.

---

## 10. Deviations from the task text, recorded

| the brief / spec says | what landed | why |
|---|---|---|
| `sst` asserts `slot_id[kind][slot] == (layer, head)` | for KV it asserts `(layer, head >> 1)` | the K and V halves of one kvhead are two commands on ONE slot, so keying on `head` makes the K-half SST claim the slot holds another block. It is the hardware's own `kv_tag = {layer[2:0], kvhead[1:0]}` (A1.3). §2.3 |
| the state base is "the first 64 KiB-aligned address above the pack on the emptiest channel" | `plan_state_base(nch)` = the LAST channel at `STATE_MIN_BASE` (2 GiB in) | above the pack AND above the 485 MiB embedding table the brief's rule does not account for, and derived from the channel count alone so four independent readers name the same address. §6 |
| `tb/scripts/gen_seq_chip_vectors.py` "writes `<prefix>.state.bin`" | the EMITTER writes `<base>.state.bin`; the vector generator READS it and writes only the `SBASE`/`SMEM` golden | the initial image is what the HOST uploads, so it belongs to the artifact, not to a TB-only tool; one file, one writer |
| the write window goes on "the 512-bit per-channel instance of the state channel" | its own 512-bit instance, `u_smem` | a single AXI4 slave cannot serve two masters without an arbiter the TB does not need. The separation is CHECKED, not assumed: `seq_mem_file` `$fatal`s on any access outside the window, and the weight instances keep `win_len = 0` |
| the preamble emits "the first attention layer's kvhead 0 K/V" unconditionally (spec §6.4) | only when no DeltaNet layer precedes it in the stack | otherwise that layer's own §6.1 pair emits the same SLD and the preamble's is redundant. It is also what makes the per-token census exactly 224 |
| `dump_state` gated on `BYTELOCKED_TAGS`, as `rs_f` is | NOT gated | the v2.1 schedule is unconditional, so a stream at ANY geometry carries SLD/SST and is unreplayable without a region. The frozen artifacts are not regenerated and their byte-lock was already spent by G3.1 (`evidence/qwen9b/g4/G4A_REPLAY.md` §10.6) |
| — | `ref/seq_format._emit_attn_block` was rewritten | §4.1(1): spec §6.2 and the v1.3 double pass could not both stand as they were |
| — | `attn_token`'s block-float peek reads the DDR image | §4.1(2): with two KV slots the four kvheads are never resident at once |
| — | the PROGRAM writes SB_DN/SB_KV/SB_CV | §6: it makes a replay self-contained, and the host's own write and its zero-readback refusal (spec §7.2) are unchanged |

### 10.1 One thing this gate does NOT prove

`ref/scripts/regen_gate.sh` and `evidence/qwen2b/rc/t3_locks.sh` were not
run. Both compare a re-emitted 0.8B artifact against a frozen v1.7 gold and
**G3.1 spent that byte-lock** — this tree emits v2.1 now — which
`evidence/qwen9b/g4/G4A_REPLAY.md` §10.6 already records as the intended
state. What IS unmoved, and is measured here, is the boardfree triple
(§7.4). The 0.8B/2B geometries are served by their frozen
`build_034`/`build_035` bitstreams from a pre-G3 checkout.

### 10.2 The emitter aborted nondeterministically, and the host is why

**Corrected 2026-09-04, fix round 1 (C1). The first cut of this section
called it "a transient this gate could not reproduce" and blamed a stale
`.pyc`. Both were wrong, and the review refuted them.**

**WHAT HAPPENS.** `ref/gen_layer_script.py`'s emission aborts inside
`ref/w4a8_ref.matvec_y32`'s

```
    acc = (w4.reshape(N, NG, g).astype(np.int64)
           * x8.astype(np.int64).reshape(1, NG, g)).sum(axis=2)
    assert np.abs(acc).max() < (1 << 31)
```

The reviewer measured the failing value: **`true + 2^33`**. That is
arithmetically impossible for this expression — `w4` is int4 and `x8` is
int8, so a group of 128 terms cannot exceed `128 × 8 × 127 = 130,048`, and
the observed maximum on a good run is 123,904. A single HIGH BIT appears in
a 400 MB int64 temporary. The reviewer also measured the decisive fact:
**the same pure-integer expression on the same arrays returned different
values one call apart, inside one process**, and six successful runs were
byte-identical to each other.

**WHERE IT HAPPENS, measured.** Every failing run — S3's three and the
reviewer's three-in-nine — ran on **darthplagueis**. For S3's three the
evidence is the command itself: all three invoked
`ref/.venv/bin/python`, which is a **dangling symlink on snoke** (the
plan's standing hazard says so) and therefore cannot have run there. The
host table in the fix-round report lists all 31 logs.

**WHY THAT MATTERS.** The campaign's Global Constraints ban darthplagueis
from numeric compute, in those words, because *"it produced wrong
arithmetic eight times"* (the migration spec §11) and the memtest soak
follow-on has been open since 2026-08-16. A wrong high bit in a large
int64 temporary is that defect class exactly. An assert that FIRES is the
lucky case; the same corruption below the assert's threshold is a silently
wrong artifact, which is the one thing a bit-exactness campaign cannot
have.

**WHAT WAS DONE ABOUT IT, and it is not an argument.**

1. **The committed artifacts were emitted on snoke** — `make -C tb
   w9_9b_smoke_scripts w9_9b_tok_smoke_scripts` and `make tb_layer_chan`
   both ran through `ssh snoke`. §9.2 has the per-log host table.
2. **Ten sequential emissions on snoke, same seed, distinct prefixes**, and
   their shas compared with each other AND with the committed artifacts —
   §9.2.
3. **The gate exists now, whatever the cause — and since fix round 2 it is
   WIRED, not advisory.** `evidence/qwen9b/s3/emit_repeat.sh` emits an
   artifact and refuses unless the `.txt`, the `.seq`, the `.seqdata.bin`
   and the state image agree byte for byte with a reference emission. The
   three KEPT-ARTIFACT targets — `w9_9b_smoke_scripts`,
   `w9_9b_tok_smoke_scripts` and `w9_9b_model_script` — now emit the
   artifact, emit it AGAIN into `$(EMIT2_DIR)` and compare, and FAIL on any
   difference; **S4's four model emits run under that**. The gate's own RED
   is committed (`060_emit2_red.log`, `make w9_9b_emit2_red`): with the
   second emission's seed perturbed the comparison refuses it —
   `EMIT2_RED: CAUGHT`. Reproducing an emission is a gate now, not a
   habit, and it is a gate that has been seen to fail.
4. **`StateImage.get`'s allocation churn is gone** (fix round 1, M3): it
   used `setdefault`, whose default argument is EVALUATED, so it allocated
   a fresh block on every HIT — a 2 MiB KV array per SLD, per SST and per
   block-float peek. That is not the cause (the failure predates the class
   on the same host) but it is a large, pointless int64 allocation rate in
   exactly the arena the corruption appears in, and it is the kind of thing
   a reader would rightly ask about.

**What this section does NOT claim.** It does not prove the host is at
fault: proving that needs the memtest soak, which is open and is not this
task's. It states what was measured, which host it was measured on, which
constraint that host violates, and the gate that now stands between the
defect and a kept artifact.

## 11. Handoffs

**To S4 (the 9B replay, token-identical).**

1. **The emitter interfaces S4 consumes**: `GLS.sld(kind, slot, layer, head=0)`
   / `.sst(...)`; `StateImage.blocks[(kind, layer, head)] -> np.ndarray`
   (uint8, one B15.1 block: DN a whole layer, KV per (layer, kvhead, K|V),
   CV per layer); the schedule helpers `sched_kv_prefetch`, `sched_preamble`,
   `sched_dn_pair`, `sched_cv_pair`, `sched_attn_layer`, `sched_token_end`;
   `seq_model.StateRegion.load(prefix)` / `.blocks` / `.addr_of`; the
   manifest keys `state: {dn, kv, cv, end, sha256, final_sha256}` and
   `conv_images: [{layer, file, bytes}]`; and the golden grammar
   `SMEM <hex addr> <hex len> <fnv1a64>` beside `SBASE <dn> <kv> <cv> <units>`.
2. **The model set is S4's to emit** — this gate emitted the SMOKE set only.
   `make -C tb w9_9b_model_script` is unchanged in its command line; what
   changed is that the artifact now also carries `<base>.state.bin`,
   `<base>.state_final.bin` and 24 `<base>_cv<L>.bin`. The two `.bin`
   region images are SPARSE (155 MiB apparent, a few MiB on disk); if S4
   copies them, copy sparsely.
3. **Two costs S4 should budget.** `tb/scripts/gen_seq_chip_vectors.py` hashes every
   stored block in pure Python (FNV-1a is sequential); at the smoke's
   ~17 MiB that is seconds, at a whole model's region it is minutes. And
   `tb_seq_chip`'s `win_fnv` does the same in the TB, once per launch.
4. **`state_bytes_per_token(T)`** (`sw/tok_meter.py`, label D) is 70 MiB at
   T = 512 and 182 MiB at T = 4,096. The spec's §9 "≈ 50 MiB at T = 512"
   is LOW and is corrected by that function: it counted the DN traffic once
   per layer rather than once each way and left the conv pair out.

**To S5 (structure and timing).** Nothing here changes `rtl/`.
`synth/exp_uram/` is byte-identical to `07eea51` (§8.2).

---

## Correction (S4 fix round 1, 2026-09-05): the emit-twice gate this gate wired could NOT fire on the MODEL target

**Appended, nothing above it moved.** §10 item 3 says the three
KEPT-ARTIFACT targets — `w9_9b_smoke_scripts`, `w9_9b_tok_smoke_scripts` and
`w9_9b_model_script` — "now emit the artifact, emit it AGAIN into
`$(EMIT2_DIR)` and compare, and FAIL on any difference; **S4's four model
emits run under that**". **That was true of the two SMOKE targets and NOT of
`w9_9b_model_script`.** S4's review established it three ways, and all three
are facts about files, not opinions:

1. **The 9B model emitter exits NON-ZERO BY DESIGN.**
   `ref/gen_model_script.py:711-721` reaches a `raise SystemExit(` when the
   runtime range audit fails and `--allow-clip` is not passed — which this
   campaign deliberately never passes — so the interpreter exits 1. The
   artifacts are written anyway, by `ref/seq_format._finalize`'s atexit hook.
2. **make abandoned the recipe at that line.** The emitter was a plain
   recipe line in `tb/Makefile` — no `-` prefix, no `|| true` — so the
   `if [ "$(W9_EMIT2)" = 1 ]` block below it was never reached.
   `evidence/qwen9b/s4/001_emit_9b_s1.log:102` is the proof:
   `make: *** [Makefile:1355: w9_9b_model_script] Error 1` names the
   EMITTER's line, not the block's.
3. **Even if reached, this gate would have refused the artifact.**
   `evidence/qwen9b/s3/emit_repeat.sh` treated any non-zero emitter rc as
   `run i ABORTED` and FAILED, and it discarded the emitter's stdout, so it
   could not have inspected the audit line even if it had wanted to.

**Where the fix is.** S4 fix round 1 repairs both files. `tb/Makefile`'s
recipe now captures the emitter's rc and reaches the emit-twice block on
rc 0, or on a non-zero rc **only** with the audit line, the finalizer's
`SEQ: … records … -> ` line and no traceback or assertion — the contract
`evidence/qwen9b/s4/emit_model_gated.sh` already implemented — and the target
still exits with the emitter's rc afterwards (`tb/Makefile:1409-1439`, the
block at `tb/Makefile:1431-1438`). `evidence/qwen9b/s3/emit_repeat.sh`
carries the same contract and keeps each run's output in `<prefix>.emit.log`
instead of discarding it. Both halves are proved to fire BOTH ways at shim
scale — one GREEN and three REDs, no GPTQ — by
`evidence/qwen9b/s4/emit2_gate_red.sh`; and the SMOKE path, which this gate's
own numbers depend on, was re-run once afterwards to show it still passes.

**What stood in the meantime, and it is not nothing.** The four 9B model
streams were NOT emitted ungated. `evidence/qwen9b/s4/emit_model_gated.sh`
ran the same make target twice with only `W9_BASE` different and compared
S3's four files **plus** `.state.bin`, the .e4.seq.json metadata,
`.emb.bin`, the .weights.json manifest (prefix-normalised) and the 249
weight images by content
digest — a strictly LARGER set than the four this gate compares — and all
four seeds returned `EMIT_GATED s<n>: PASS`. The model artifacts this
campaign replays are proved; what was inert was the wiring, and it is not
inert now.
