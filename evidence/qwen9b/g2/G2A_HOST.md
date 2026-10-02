# G2a — the host chain generalized at 9B, and the byte-lock still holds

**Task 3 of `docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md`.
Host only: no RTL, no synthesis, no board.**
Spec: `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md` §7.1,
§7.3, §7.4, §7.5 E, §8 G2, §9 (D-B, D-TOK, D-STAGE, D-DEAD), and §4.4's
`RS_F` relocation.

---

## 0. Verdict

**PASS**, with the scope of "inert" stated precisely, because the headline is
narrower than it first reads.

**What is proven inert: the EMITTED ARTIFACT CHAIN and the host selftests.**
Every byte of the frozen 0.8B and 2B artifacts, and every `sw/` selftest.

**What is NOT inert, and it is a real behaviour change: `sw/tok_meter.py`'s DDR
LAYOUT.** D-TOK's fix moves that tool from the nch-independent pack to the
per-channel repack, so with `--four-chan` at 0.8B **186 of its 187 images get a
different channel-local base** and the pack top drops `0x28e34000` →
`0x16396000` — each channel now reserves only the rows it owns instead of the
whole image, 417,546,240 bytes reserved before against 104,423,424 after.
**Measured, and now backed by a committed log**: `tok_meter_layout_check.py`
plans the same committed manifest both ways and prints both numbers
(`tok_meter_layout.log`). The one image that does not move is the first
placed — both plans start it at `W_BASE`. (An earlier revision of this
paragraph carried the "(measured)" label with no log behind it; the number was
right and the attestation was missing, which is the `a9d06ca` class.) The *computation* is unchanged: every engine
still reads its own rows and `run_matvec` addresses them through the same
`wbase_chan(wid, i) + (r0 - cr0) * stride`. **The HAZARD is `--skip-upload`**:
a channel populated by the OLD layout and then read by this code — or the
reverse — reads the wrong bytes at the right addresses. Anyone who uploaded
with a pre-G2a `tok_meter` must re-upload, not `--skip-upload`. This tool needs
a board and the board is off-limits until T15, so **the new layout is not
exercised end to end here** (§9).

The gates:

| gate | before | after | log |
|---|---|---|---|
| `evidence/qwen2b/rc/t4_bytes_unmoved.sh` (2B W8 layer chain) | `BYTES_UNMOVED PASS` | **`BYTES_UNMOVED PASS`** | `t4_bytes_unmoved_before.log`, `t4_bytes_unmoved_committed.log` |
| `ref/scripts/regen_gate.sh` (0.8B model_v2_s1) | `REGEN_GATE_PASS`, sha `a69864d2…` | **`REGEN_GATE_PASS`, sha `a69864d2…`** | `regen_gate_before.log`, `regen_gate_committed.log` |
| `evidence/qwen2b/rd/rd_boardfree.sh` (`sw/` selftests) | `BOARDFREE_PASS` 2750/85/344 | **`BOARDFREE_PASS` 2753/85/349** | `sw_boardfree_before.log`, `sw_boardfree_committed.log` |
| defect-B regression, RED→GREEN | — | **RED rc 1 → GREEN rc 0**, `sw/infer.py` restored byte-identical | `damage_defect_b_red_green.log` |
| D-STAGE: does deriving the mask move a golden? | — | **IDENTICAL** on `.chip`, `.seq`, `.seqdata.bin` | `d_stage_check.log` |
| importing `SCRATCH_WORDS` (and its 32768 → 65536 move) into the seq_unit vector generator | — | **182 of 182 artifacts identical over 4 seeds** | `seq_unit_vectors_check.log` |
| every G2a guard, tripped RED **and** GREEN | — | **32/32 (33/33 at 9B), 0 failed** in four configurations | `evidence/qwen9b/g2/isa_guards_0.8b.log` and its `_2b` / `_9b` / `_rsf7` twins |
| `evidence/qwen_next/spec_cites.py` on the spec **and** the plan | — | **`SPEC CITES: PASS`** | §7 below |
| `--selftest` negative control on both documents | — | **`SELFTEST: PASS`**, **6/6 `CAUGHT`** (ORPHAN and AMBIG added) | §7 below |
| three-tag `ref/` selftest sweep (0.8b, 2b, 9b) | 21/21 exit 0 (`ref_selftests_dtol.log`, Task 2) | **`OVERALL exit 0`, 21/21, 0 FAIL** | `ref_selftests_g2a.log` |

**One byte DID move, and the byte-lock is what found it.** §3.2 has the whole
story: widening the DN/KV bank counts 18/6 → 24/8 changed the *clamped
companion slot* in the 0.8B stream's last `L` record, `L 00000511` →
`L 00000512`. The numerics were untouched — same 60,495 records, same argmax
per step, same generated text — and the change was semantically inert by the
generator's own documented argument. It still moved a byte at a geometry
nothing in this task was supposed to touch, `ref/scripts/regen_gate.sh`
returned
`REGEN_GATE_FAIL`, and the fix (clamp to the model's layer count, not the bank
depth) is both the frozen behaviour and the right rule at any geometry.
**That is the single most valuable thing this gate produced**, and no amount
of reading would have produced it.

**THE THREE HEADLINE GATES WERE RE-RUN ON THE COMMITTED TREE, CLEAN.** The
`_committed` logs above carry `=== tree: b2f1223` with **no `+dirty` flag** —
they are not "the tree as it happened to be while I was working", they are the
tree this gate ships. The earlier `_before` / `_after` / `_final` logs are kept
because the *sequence* is the evidence (§3.2 is a FAIL between two PASSes) and
deleting the middle of it would hide the finding.

**Interpreter, recorded once for the whole campaign** (plan Step 1): every
numeric and artifact-regenerating command in this gate ran on **snoke** with
`MODELPY=/home/cah/.venv/bin/python` — **Python 3.12.3, torch 2.12.0+cpu**,
safetensors 0.8.0. The three-tag sweep uses the ladder form
`uv run --no-project --with numpy --with torch --with transformers python`.
`ref/.venv/bin/python` is a **dangling symlink on snoke** and was not used.
darthplagueis was used only for editing, git and `spec_cites.py` (no
arithmetic), per its memtest exclusion.

---

## 1. What changed, by file

`ref/gen_layer_script.py`

* **The SCA tile map is now the layout authority.** Nine tiles, sized
  `max(32, LNH)` / `max(32, 2·LNH)` / `LDK` / `2·LDV` / `LDV`, accumulated into
  `SCA_TILE` and `SCA_SZ`. This is not this campaign's invention: it is the
  `fix_sca` branch of `evidence/qwen_next/feas/scratch_peak.py:49-60`, the
  allocator the feasibility study's 9B peak was computed with, and the
  emitter now reproduces it exactly.
* **`STG = SCA + max(1024, SCA_SZ)`**, the same expression the study used. The
  old `SCA + 1024` literal happened to exceed `SCA_SZ = 992`; at 1056 it would
  have parked the staging window on top of `NH`.
* **`beta_base` / `decay_base` exported**, with a **layout-authority assert**
  that each tile's used extent fits its slot.
  **What that assert is, stated honestly** (review N2, then N4): the first cut
  was a tautology (`A16 + 2·LNH <= GD`, where `GD` is *defined* as that plus
  slack). The replacement is real but its DOMAIN is narrower than
  "layout-authority" suggests — swept over **LNH 1..64 × LDK 1..256 ×
  LDV 1..256, 4,194,304 combinations, it records ZERO violations**, because
  every slot is `max(floor, its own use)`. So it is a **table-consistency
  guard**: it fires when `_SCA_TILES`' size column desyncs from the use column,
  i.e. on a hand edit — demonstrated by shrinking the GD slot, which makes it
  fire at 9B and stay correctly silent at 0.8B. Worth having (the wall-17
  defect came from exactly such a hand-placed table) but **it is not a check on
  the geometry**, and the earlier wording that implied otherwise was the same
  overclaim N2 was raised about.
* **The wall-17 defect fixed**: `M.dnst(..., GD + 16 + h, GD + h, ...)` →
  `M.dnst(..., decay_base + h, beta_base + h, ...)`. The `16` was `LNH`; at
  LNH=32 every one of the 32 heads read the wrong word.
* **VREP**: `hk = h // LR.VREP`, and q/k indexed by the KEY head. Mirrors
  `ref/layer_ref.py:223-225`.
* **Banks 18/6/2 → 24/8/4**, defined once (`_DN_SLOTS`, `_KV_SLOTS`, `_KVH`).
* **`SCRATCH_MAX` 32768 → 65536**, and a **new, separate `ISA_SADDR_MAX =
  32768`** — see §2.
* **`require_supported_geometry` is now an ASSERTION of the new algebra**
  rather than a refusal on head counts (spec §7.1's stated intent).
* Per-op vector lengths derived (`LR.LDK`, `LR.LDV`, `LR.HD`, `LR.ROT`,
  `2·LR.LNH`), including the DN body's gate staging — see §3.1.
* `dump_weights` gains a **caller-gated `rs_f`** beside `emb_row_bytes`.

`ref/gen_token_script.py` — `DN_SLOTS, KV_SLOTS` imported from the one
definition; **`slot_plan`'s clamp re-based on the model's layer count** (§3.2).

`ref/gen_model_script.py` — passes `rs_f` only for a geometry outside
`BYTELOCKED_TAGS`.

`ref/debug_torch_diff.py` — the import-time refusal becomes an assertion; the
QKV reshape follows `np.repeat(..., VREP)`.

`ref/seq_chat.py` — `POS_COPIES` derived from the full-attention layer count,
`POS_WORDS` from `2·ROT`. `CONST_BYTES` stays pinned: it is the byte length of
the committed 0.8B const region, gated by `TEMPLATE_SHA256`, not geometry.

**ONE BEHAVIOUR CHANGE WORTH NAMING, because it is a new coupling rather than
a widening.** `POS_COPIES` used to be the constant 6 on both sides; it is now a
function of `FABLE5_MODEL`. Under an unset or `2b` selection — every way these
tools are run against the frozen bitstreams — it is still 6 and nothing moves,
which is what `BOARDFREE_PASS` shows. Under `FABLE5_MODEL=9b` with a 0.8B
artifact it becomes 8 and `derive_geometry`'s
`need(len(pl) == POS_COPIES)` now **refuses** instead of deriving a stride from
a count that does not match the stream. That is the better failure — driving a
0.8B artifact under a 9B geometry selection was never valid — but it is a
refusal that did not exist before, so it is recorded rather than discovered.

`ref/audit_ranges.py` — the 0.8B per-family layer-count LABELS derived
(`24 layers`, `48 tensors`, `6 GQA layers`, `18 layers`, `187 weight images`).
The counts were always right; only the printed names lied at 9B, which is a
G1 "not established" item closed here. The formula now reads
`8·N_DN + 7·N_GQA + 1` → **187 at 0.8B, 249 at 9B**, both matching the
committed and spec numbers.

`ref/layer_fixed.py` — comment only: `RS_F`'s two halves (emit side here,
consume side in the manifest) written out, with A1.8's ruling that 8 ships and
`rtl/conv4_silu.sv:50` is not touched.

`sw/hwmap.py` — `SCRATCH_WORDS` 32768 → **65536** with the coupling stated;
`_META_DEFAULTS` makes the meta-key filter and its defaults **one edit instead
of two**; `rs_f` added with default 8.

`sw/infer.py` — **defect B**: four literals → `LR.H`; the cosmetic
`"248320x1024"` derived; the adjacent `2048` fenced as what it is — the host
W32 injection chunk `ref/gen_layer_script.CHUNK`, **not** an ISA limit, which
is what an earlier revision of all three sites called it.

`sw/head_cache.py` — `RS_F` comes from the **manifest**, not a module
constant; `HeadSpec.rs_f`; the pinned `(248320, 1024, -4, 5, 128)` tuple
replaced by a manifest-derived shape plus a cross-check a manifest *cannot*
self-certify (head shape vs `.emb.bin` size on disk); the two `rs_f` scopes
documented at both sites.

`sw/seq_run.py` — the scratch-cover check derives a power-of-two range instead
of a hard pair; the synthetic fixture takes `emb_h` and `rs_f`; four new
manifest-split checks.

`sw/chat_seq.py` — `_HEAD_WID` on both geometry paths and read at the online
call; `POS_*` derived; `SPTR_MASK` 15 → 16 bits with the coupling stated;
`_cmd_scratch`/`scratch_accesses` take a geometry; `HEAD_LOGIT_EXP0` derived
from `HEAD_E + HEAD_SH - 15 - rs_f`; the head-spec refusal follows the
artifact's own `rs_f`.

**`X8_WORD/X8_LEN` and `STG_WORD/STG_LEN` — the disposition, stated because
the plan asks for it.** Both were **latent, not live**: the production paths
already read `self.geom[...]`. What changed is that `frozen_geometry()` now
carries `STG_WORD`/`STG_LEN` and `_HEAD_WID` too, so **the same key exists on
the nch=1 and nch=4 paths** and no consumer has to fall back to a module
literal to find them. The module constants stay, relabelled as what they are —
the frozen 0.8B fallback that `frozen_geometry()` is built from — and they
remain the literals selftest [17] pins the 0.8B layout against, which is that
check's whole purpose. The only readers still taking them implicitly are
`read_x8_eout`'s default arguments, reached only from the selftest.

`sw/tok_meter.py` — **D-TOK**: `plan_weights` gets `rows_of` matching the
layout this tool actually uploads; per-channel bases threaded through the
uploader and the engine driver; the `n*2` embedding stride asserted against
the manifest and against `EMBLOG2`.

`tb/scripts/gen_seq_unit_vectors.py` — `SCRATCH_WORDS` imported; its own stale
self-name (it still called itself by the deleted file's name) corrected.
The import is **not** a no-op — the value it now reads moved 32,768 → 65,536 —
so its inertness is measured, not assumed: **182 of 182 artifacts byte-identical
across 4 seeds** (`seq_unit_vectors_check.py`). It sizes only the behavioural
scratchpad model, and no vector can name a word above 32,767 while the ISA is
15-bit.

`tb/scripts/gen_chat_i1_vectors.py` — **D-STAGE**, derived from `GLS.SCRATCH`
(§3.3).

`tb/scripts/gen_seq_vectors.py` — **DELETED** (D-DEAD).

`evidence/qwen_next/spec_cites.py` — `RETIRED` set, an **`ORPHAN`** check, and
the stale `ALIAS` entry dropped (§7).

### 1a. The census, one row at a time

The plan asks for "a disposition per row". Spec §7.1 (Track L's refusals) and
§7.4 (the rest of `sw/`), in their own order. **`g2a_census.sh` re-runs the
mechanical half of this table on demand**; `g2a_census.log` is the current
output.

**§7.1 — Track L's refusals → generalizations**

| row | disposition |
|---|---|
| the QKV head loop (`for h in range(LR.LNH)`, `q_src`, `k_src`) | **DONE** — `hk = h // LR.VREP`; q/k indexed by the KEY head |
| `require_supported_geometry` | **DONE** — now asserts the VREP algebra and the `LKD = LNKH·LDK` / `LVD = LNH·LDV` identity; still REFUSES on bank overflow, now including `NKV > _KVH` |
| the `cw`/`cs`/`S` banks 18 → 24, `kc`/`vc`/`T` `[6][2]` → `[8][4]` | **DONE** — `_DN_SLOTS`/`_KV_SLOTS`/`_KVH`, one definition, imported by `gen_token_script` |
| the `dn_slot`/`kv_slot` assert | **DONE** — bounds are the constants, not literals |
| **the `DNST` decay pointer `GD + 16 + h`** | **DONE** — `decay_base + h`, with a table-consistency assert behind it (see §1; it guards hand edits to the tile map, not geometry) |
| `KVH_MAX = (1 << 1) - 1` and its two asserts | **SPLIT, not lifted** — `KVH_MAX = _KVH - 1` is the geometry bound; `ARG0_KVH_BITS = 1` still refuses kvh ≥ 2. Task 10 lifts it |
| `assert (1 << nlog2) == n` | **KEPT**, unchanged — it is the non-power-of-two `H` guard and must survive |
| `assert 1 <= n <= 2048` | **SPLIT, not lifted** — `VNW_MAX = 4096` is the geometry bound; `VNW_ISA_MAX = 2048` is ARG0[10:0]. A 4096-word rmsnorm still REFUSES; Task 8 lifts it |
| `ref/debug_torch_diff.py` refuses at import | **DONE** — assertion + `np.repeat(..., VREP)` reshape |
| `DN_SLOTS, KV_SLOTS = 18, 6` in `gen_token_script` | **DONE** — imported, not re-declared; and `slot_plan`'s clamp re-based (§3.2) |
| the SCA tiles on 32-word strides, `SCA_SZ` 992 → 1056 | **DONE** — the tile map is the layout authority; `STG` moves with it |
| `SCRATCH_MAX = 32768` → 65,536 | **SPLIT, not lifted** — the array is 65,536; `ISA_SADDR_MAX = 32768` still refuses any address above 32,767. Task 7 lifts it |
| `DNST_HEAD_MAX = (1 << 4) - 1` → `(1<<5)-1` | **SPLIT, not lifted** — `ARG0_HEAD_BITS = 4` still refuses head ≥ 16, for `dnz` as well as `dnst` (review B1). Task 7 lifts it |

**§7.4 — the rest of `sw/`**

| row | disposition |
|---|---|
| `HEAD_WID = 186` used online | **DONE** — `_HEAD_WID` on both geometry paths; the online call reads it |
| `X8_WORD, X8_LEN` (latent) | **DONE** — see the note above; both are session keys now |
| `sw/head_cache.py`'s `== (248320, 1024, -4, 5, 128)` | **DONE** — derived, and replaced by a check a manifest cannot self-certify |
| `SCRATCH_WORDS = 32768` + the live duplicate | **DONE** — 65,536, one definition, imported; inertness measured over 4 seeds |
| `EMB_ROW_BYTES_DEFAULT` and the 0.8B comments | **DONE** — joined by `RS_F_DEFAULT` under one `_META_DEFAULTS` |
| `cover in (16384, SCRATCH_WORDS)` | **DONE** — a derived power-of-two range; the old form had already stopped accepting 32768 |
| the 2048 B / H=1024 fixtures and mapping tests | **DONE** — `emb_h` parameterizes the fixture; the mapping test gains the 9B row (8192 → 13, the CSR's top) |
| the three `& 0x7FFF` SPTR masks | **DONE** — `SPTR_MASK = 0xFFFF`, with the coupling stated; the fourth `0x7FFF` is the GATE dst ISA field and stays |
| `POS_STRIDE = 1536` / `POS_COPIES = 6` and ten reinforcements | **DONE** — derived on both sides; the ten reinforcements are prose/labels and now read correctly at any geometry |
| the per-op vector lengths in the scratch decoder | **DONE** — `_cmd_scratch` takes a geometry |
| **D-TOK** — `tok_meter` cannot plan a pack | **DONE** — `rows_of`, per-channel bases, and the stride coincidence turned into two asserts. **Not exercised end to end: it needs a board** (§9) |

**Explicitly NOT done, because the spec rejected them** (§5.6): stripping
`ref/model_select.py` or the multi-geometry host tables (it would delete tests,
not code), and making `EMBLOG2` a compile-time constant. And `nch < 4` is not a
simplification — nch=1 stays valuable as a bring-up rung.

---

## 2. Two ceilings that were one name, and why that matters

The plan says raising `SCRATCH_MAX` to 65,536 is "correct and inert" and that
"the emitter will still refuse a 9B layer body at `enc_saddr`'s pair packing".
**As written it would not have refused — it would have corrupted.**
`enc_a1` packs an address PAIR as `(lo & 0x3FFF) | ((hi & 0x3FFF) << 14) |
((lo >> 14) << 28) | ((hi >> 14) << 29)`. At `lo = 40000`, `lo >> 14` is 2 and
`2 << 28` lands on bit 29 — `hi`'s bit. The address would come back as a
different address, silently.

So the two ceilings are now two names, and every packer checks the right one:

| name | is | value | checked by |
|---|---|---|---|
| `SCRATCH_MAX` | the scratch ARRAY depth (§4.3 S4) | 65,536 | `enc_saddr` |
| `ISA_SADDR_MAX` | what an ARG word can CARRY (SEQ_ISA v1.7) | 32,768 | `enc_isa_saddr`, used by `enc_a1` / `enc_alu_a2` / GATE dst / DNST pointers |
| `Mach.DNST_HEAD_MAX` | the GEOMETRY bound, LNH−1 | 31 | `dnst` |
| `Mach.ARG0_HEAD_BITS` | the ARG0 head FIELD | 4 | `dnst`, naming Task 7 |
| `Mach.KVH_MAX` | the GEOMETRY bound, NKV−1 | 3 | `kvap` / `attn` |
| `Mach.ARG0_KVH_BITS` | the ARG0 kvhead FIELD | 1 | `_kvh_isa`, naming Task 10 |
| `Mach.VNW_MAX` | what a GEOMETRY may ask for (H) | 4096 | `vnw_` |
| `Mach.VNW_ISA_MAX` | what ARG0[10:0] can carry | 2048 | `vnw_`, naming Task 8 |

The same shape appears three more times and each one was a live
silent-wrong-answer at 9B, not a style point:

* **VNW.** `4096 & 0x7FF == 0`, and 0 *encodes* 2048 — so a 9B rmsnorm would
  have normalised over **half** the vector and said nothing. Wall 3's shape.
* **DNST head.** `head` sits in `arg0[3:0]` with `a_dec` at `[17:4]`; head 16
  would not merely truncate, it would corrupt the pointer. The pre-existing
  assert said so; raising `DNST_HEAD_MAX` alone would have removed the only
  thing enforcing it.
* **KVAP/ATTN kvhead.** The RTL decodes `arg0[0]` only, so kvh 2..3 corrupts
  nothing — it selects the **wrong bank**, which is worse.

**The same "widened host constant is not a widened hardware field" note is
carried at `sw/hwmap.SCRATCH_WORDS` and `sw/chat_seq.SPTR_MASK`**, which the
plan asks for explicitly and which is the reason both are safe to land now.

---

## 3. What the gates caught that reading did not

### 3.1 The DN gate staging collides at LNH=32 — not in any census

`dn_token` staged `A_q15` (2·LNH words) at `STG`, `dt_bias` (LNH) at
`STG + 32`, and `norm_w` at `NW = STG + 64`. At LNH=16 that is 32 | 16 | pad.
At LNH=32 it is 64 words of `A_q15` **on top of** the dt_bias tile, and 96
words of A+dt **on top of** `norm_w`. Now `DTB = STG + 2·LNH` and
`NW = STG + max(64, 3·LNH)`, with an assert that they do not overlap; `max(64,
…)` keeps the as-built 0.8B/2B offsets exactly. **Neither §7.1 nor §7.4 lists
these**, and they are a silent-wrong-answer at 9B.

### 3.2 The bank widening moved a 0.8B byte — the byte-lock's whole point

`gen_token_script.slot_plan` clamps the layer's **unused companion** slot into
range so the `L` record always carries concrete slots, and its docstring
argues (correctly) that the clamped value is inert because a layer only ever
touches the bank of its own kind. It clamped to `DN_SLOTS - 1`. When
`DN_SLOTS` went 18 → 24, the 0.8B stream's last full-attention layer began
emitting `L 00000512` instead of `L 00000511`.

* **What did not change**: 60,495 records, `argmax per step=[561, 314, 279,
  369, 279, 6511]`, `generated=[369, 279, 6511] decoded=' is the capital'`.
  The stream computes the same thing.
* **What did**: the emitted sha, `a69864d2…` → `8bc5faac…`, and
  `REGEN_GATE_FAIL` (`regen_gate_after.log`). The `.txt` differed at byte
  2,216,965, line 442,811 — one `L` record.
* **The fix**: clamp to the count of slots **this model uses**
  (`min(dn, n_dn - 1)`), which is 17 at 0.8B/2B — byte-identical — and 23 at
  4B/9B. The bank depth stays the separate, larger bound the assert checks.
  `regen_gate_after2.log`: `got = a69864d2…`, `REGEN_GATE_PASS`.

**This is the finding of the gate.** A change that was semantically inert by a
correct argument was not byte-inert, and only running the lock showed it.

### 3.3 D-STAGE derives from the MODEL's scratch depth, not the hardware's

Spec §9's D-STAGE row says to derive the mask "from `SCRATCH_WORDS` in
`sw/hwmap.py`". Doing that does not merely change the golden — it **dies**:
`IndexError: index 16384 is out of bounds for axis 0 with size 16384`. The
mask indexes `L["mem"]`, which is `gen_layer_script.Mach.mem`, depth
`GLS.SCRATCH` — the EMITTER's power-of-two scratch depth for this geometry
(16384 at 0.8B). `sw/hwmap.SCRATCH_WORDS` is the HARDWARE array, which this
gate moved to 65,536. The sibling that already had it right is
`ref/seq_model.py:1345`, which uses `GLS.SCRATCH`.

`evidence/qwen9b/g2/d_stage_check.py` runs the real generator twice, changing
only `GLS.SCRATCH` (forced 16384 vs derived), and compares:
`.chip` `6e8a4487…` **IDENTICAL**, `.seq` `0b240a8a…` **IDENTICAL**,
`.seqdata.bin` `7591dd21…` **IDENTICAL**. **D_STAGE PASS.**

*Not a comparison against the on-disk `tb/scripts/w4/chat_i1.chip`*
(`5028231207f443c7`): that is a gitignored build artifact from 2026-08-13
predating R-c/R-d chain changes, so it differs for unrelated reasons. The
controlled A/B is the test; the on-disk sha is printed for the record.

---

## 4. Defect B, and a damage test that was wrong first

`evidence/qwen9b/g2/damage_defect_b.py` proves three things, at 0.8b, 2b and
9b (`evidence/qwen9b/g2/damage_defect_b_0.8b.log` and its `_2b` / `_9b` twins, all rc 0):

1. **The fix is in**, by **AST inspection** of `sw/infer.py`'s `step()` — not
   grep, so a `1024` in a comment can neither pass nor fail it. It also pins
   that the adjacent `2048` AMAX32 chunk **must remain** a literal: a "fix"
   that parameterized it would be wrong.
2. **The damage is detectable.** At 2B: DYNQ8 exponent 3 vs 3, **1006 of the
   leading 1024 words change (98.2 %)**, max |diff| 28, and **nothing raises**.
   At 9B: 1007/1024 = 98.3 %, max |diff| 29.

   > **THESE ARE NOT TRACK F's NUMBERS, AND THE DIFFERENCE IS RECORDED RATHER
   > THAN SMOOTHED** (plan Step 6b: a count carried forward from a report is
   > exactly the kind of claim to diff-verify). Spec §7.3 and
   > `evidence/qwen_next/defect_a/CORRECTIONS.md` C2 report **99.6 % changed,
   > max |diff| 99**; this file measures **98.2 %, max |diff| 28** on the same
   > defect at the same geometry. **Neither is wrong — they are different
   > residuals.** The damage is a function of how unevenly the two halves are
   > scaled, and CORRECTIONS.md says so itself: an i.i.d.-uniform residual
   > gives max |diff| 1, which is why a single sample is not evidence. This
   > file draws its own uneven residual from `default_rng(7)` (halves at
   > ±4000 and ±200); Track F used a different one. **What replicates is the
   > SHAPE — near-total corruption of the leading half, silently — and that is
   > what the regression tests.** The absolute figures do not transfer between
   > residuals and neither document should be quoted as if they do. At 0.8B the "damage" is the
   identity and the test **says so** rather than pretending to detect
   something.
3. **The fourth line still raises**, `ValueError: cannot reshape array of size
   1024 into shape (1,16,128)`.

**Two things this file got wrong before it was right, both recorded because
the second is the more instructive:**

* It called `LF.rmsnorm_fx` with the wrong arity and died.
* Worse: check [3] **passed for the wrong reason**. `matvec_y32` was called
  with the wrong number of arguments and the resulting `TypeError` was scored
  as a refusal. A damage test that cannot tell a real failure from a broken
  call is not a test. It now runs a **CONTROL first** — the same call at the
  true width must SUCCEED — and requires the refusal to be something other
  than a `TypeError`.

**RED→GREEN, on record** (`damage_defect_b_red_green.log`, driven by
`evidence/qwen9b/g2/damage_defect_b_red.py`): the four literals are put back
into `sw/infer.py`, the regression returns **rc 1** (6 passed, 1 failed), the
file is restored and its **sha256 verified byte-identical**, and the
regression returns **rc 0** (7 passed).

---

## 5. `RS_F` becomes model-selected — the plumbing, not a value change

**A1.8 is respected exactly: `RS_F` stays 8 and no RTL literal moves.** What
lands is the mechanism §4.4 calls for, on its own merits — it removes a global
constant that 0.8B/2B and 9B would otherwise have to share.

* **Emit side** — `FABLE5_RS_F` chooses the value a generator bakes in.
* **Manifest** — `Mach.dump_weights(prefix, emb_row_bytes=None, rs_f=None)`.
  **Caller-gated, following `emb_row_bytes`, not value-gated like `g`/`w8`**,
  and the reason is measured: `t4_bytes_unmoved.sh` byte-compares the
  weights manifest, and the gold 2B manifest carries **no** non-wid key at all,
  so an unconditional `rs_f` fails the lock. `gen_model_script` passes it only
  for a tag outside `BYTELOCKED_TAGS = ("0.8b", "2b")`.
* **Consume side** — `sw/hwmap.split_manifest` returns it (default 8);
  `sw/head_cache.HeadSpec.rs_f` carries it; `logit_exp` uses it;
  `sw/chat_seq`'s head-spec refusal compares against
  `head_logit_exp0(spec.rs_f)`, so at `rs_f = 7` the expectation moves to −21
  by itself instead of three sites saying −22.
* **The name collision is a LABELLED trap, not a rename.** `sw/head_cache.py`
  already emitted `"rs_f"` inside its per-image cache sidecar. The two scopes
  are disjoint — artifact metadata vs cache-validity metadata — and they hold
  the same quantity, so renaming one would make the sidecar key stop matching
  the manifest key it derives from. **Both sites now document both scopes**;
  that is the disposition, and it is stated here because the plan asks which
  was done.
* New coverage: four `split_manifest` checks in `sw/seq_run.py`'s selftest
  (default-when-absent, override, meta-is-not-a-wid, every meta key has a
  default) and three in `sw/head_cache.py`'s.

---

## 6. The three-tag `ref/` selftest sweep

`ref_selftests_g2a.log`, produced by the committed
`evidence/qwen9b/g2/run_ref_selftests_9b.sh` with `LOG=` overridden so Task 2's
cited log is not destroyed.

**RESULT: `OVERALL exit 0`. 21 of 21 invocations exit 0, 18 `SELFTEST PASS`
lines, zero `SELFTEST FAIL` — the identical shape to Task 2's committed
baseline** (`ref_selftests_dtol.log`: also 21/21, also 18, also zero). The
`attn softmax+pv` row reads `2.666e-02` / `3.288e-02` / `3.918e-02` against
`8e-02` at 0.8b / 2b / 9b, and 9B's `LAYER_FIXED SELFTEST PASS` is the one this
gate had to keep: G2a touched `ref/layer_fixed.py` only in comments, so a
change here would have meant something unintended.

**PROVENANCE, and why the tree label is not the handle.** The log header reads
`=== tree: 78cea11+dirty(ref)` because the sweep was launched before the
commit. **The `ref/` CONTENT it ran against is exactly the committed content**,
and the runner proves it rather than asserting it: the `=== md5:` line records
`ref/layer_fixed.py 0a283c01…`, `ref/fixedpoint.py ea56f7a3…`,
`ref/w4a8_ref.py cd42ad17…`, `ref/layer_ref.py f19c2cdf…`, and all four match
`git show b2f1223:<file> | md5sum`. This is the same argument G1's review round
settled: the tree label is not the provenance handle, the source digest is.
`OMP_NUM_THREADS=3`, pinned and recorded in the header.

**A first attempt was discarded rather than labelled.** A "before" sweep was
launched at 06:20 and its 0.8b/2b modules completed on the pre-edit tree, but
its 9b modules started at 06:29 — *after* editing had begun — so its 9b rows
read a half-edited `ref/`. It returned `OVERALL exit 0`, which would have been
comfortable and wrong to publish. It was deleted; it never entered a commit.
**The pre-G2a baseline is Task 2's committed `ref_selftests_dtol.log`**
(21/21 invocations exit 0 at 0.8b/2b/9b, `OVERALL exit 0`), which is exactly
the same sweep on the tree this task started from.

---

## 7. `spec_cites.py`: a new check, and what it found

> ### PRE-G3.3 ROWS, KEPT AS THE RECORD — dated note 2026-09-02 (Task 9)
>
> Rows here marked `<!--cites:noquote-->` quote **source that G3.3 DELETED**,
> not source that merely moved: the `cfg_w8` / `cfg_g64` ports and everything that selected on them, SHAPE bits 28 and 29, and the W8-envelope adder tree.  They are kept verbatim, because they
> are the record of what the pre-G3.3 tree said and the argument they support
> rests on them (§0: nothing is deleted or struck).  The exemption marker is
> used for exactly the reason §7.6 gives — *"an exemption is for source that
> no longer exists, not for a citation that has merely moved"* — and every
> citation that had merely MOVED was RENUMBERED instead, mechanically, by
> `evidence/qwen9b/o3/o3_cite_drift.py --base a08a90b`.
> **The post-G3.3 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_3_MATVEC.md` §11.1.**

**`SPEC CITES: PASS`** on the spec and on the plan; **`SELFTEST: PASS`** on
both, 4/4 negative controls `CAUGHT` and the positive control clean.

**`RETIRED`, beside `PENDING`.** Deleting the dead generator
breaks eighteen citations. They are now reported as `RETIRED` — a listed set,
so a typo cannot hide behind it — and the stale `ALIAS` short form was dropped
so a bare short form can no longer resolve to something else.

**`ORPHAN`, a new check, and it is the one that earned its keep.** A bare
`` `:NNN` `` continuation on a line that names **no** file inherits nothing:
the convention only reaches back within one markdown line, so the cite bound
to nothing, was skipped entirely, and **neither its range nor any quotation
beside it was ever checked**. That is worse than `AMBIG` — `AMBIG` picks the
wrong file loudly, `ORPHAN` checks nothing silently.

**31 orphan lines carrying 52 citations** were sitting in the spec (0 in the
plan). Every one was written out in full. Doing so activated the `QUOTE` check
on them and produced **7 failures**, of which **3 were pre-existing and had
been invisible since the day they were written**:

| # | site | what it was | pre-existing? |
|---|---|---|---|
| 1 | spec:703 | a code span that **wraps a markdown line**, so the prose after the closing backtick was scored as a quotation | **yes** — a checker artifact, fixed by unwrapping |
| 2 | spec:1187 | the SHAPE word quoted on the line that cites `:340`, while it lives at `rtl/matvec_chan.sv:18` cited on the line *above* | **yes** |  <!--cites:noquote-->
| 3 | spec:1218 | `EMBLOG2_MIN/MAX` quoted a line away from the `rtl/seq_unit.sv:330` that carries it | **yes** |
| 4 | spec:746 | the DNST scalar-pointer derivation — G2a moved the line and changed the form | no, this task |
| 5 | spec:1135 | `KVH_MAX = (1 << 1) - 1` — G2a split it into two bounds | no |
| 6 | spec:1646 | `enc_saddr`'s message — G2a split `SCRATCH_MAX` from `ISA_SADDR_MAX` | no |
| 7 | plan:736/739 | `sw/chat_seq.py:231`/`:232` drifted | no |

All seven fixed. The four caused by this task carry **dated supersession
notes** giving the pre-G2a form and the post-G2a landmark, in the house style.

**AND IT CAUGHT ONE MORE, AFTER THE FIRST COMMIT.** `b2f1223` shipped the spec
with a drifted citation: the §3.2 `slot_plan` fix added ~20 lines to
`ref/gen_token_script.py` **after** the spec had last been checked, moving
`spec:62`'s quotation *"the ones wall 8 lived behind"* from
`ref/gen_token_script.py:122` to `ref/gen_token_script.py:145`.
Re-running the checker on the committed tree found it, and it is fixed in
`c366b3a`. Two things worth saying rather than quietly fixing: **the miss was
mine** — the rule is to re-check after the last edit, not after the last edit I
remembered — and **the fix swept up two more drifts of the same cause that the
checker could NOT see**, because they carry no quotation and stayed in range:
the untied-head regression landmark `ref/gen_token_script.py:157-162` (truly
`ref/gen_token_script.py:184-188`), and both slot-count rows in the spec,
cited at line 79 and truly at `ref/gen_token_script.py:84`. That is the blind
spot §8 G2 names, demonstrated live, on this gate's own edits.

> **AND THE CHECKER CAUGHT THREE MORE IN THIS VERY DOCUMENT** once the ORPHAN
> branch was made reachable (review B2): the three lines above each carried a
> bare `` `:NNN` `` with no file named on the line. They were invisible for
> exactly the reason the spec's 31 were. Fixed, and named here because a
> checker finding defects in the document that announces the checker is the
> strongest evidence it works.

**TWO CORRECTIONS TO THIS DOCUMENT'S OWN PROVENANCE, disclosed here rather
than only in commit messages** (review N13/N14). (a) §7 named `bfb85dd` for
the citation-drift fix — **a sha written into the document before `git commit`
had produced one, i.e. fabricated**; the real commit is `c366b3a`, corrected
in `cdee139`. (b) `evidence/qwen_next/spec_cites.py`'s `RETIRED` entry said
"deleted in the same commit" without naming it; it now names **`b2f1223`**, so
`git show b2f1223 --stat` is the audit trail rather than a claim.

**A NOTE ON THE FORENSIC CLAIMS IN §3.2 AND §3.3** (review N15). The
byte-for-byte narratives there — `L 00000511` → `L 00000512`, the `.txt`
differing at byte 2,216,965 / line 442,811, the `IndexError` at
`gen_chat_i1_vectors` — were read off runs made during this gate. **Two of the
three have a committed log** (`regen_gate_after.log` carries the failing sha
`8bc5faac…`; `d_stage_check.log` carries the A/B). **The byte offset and the
`L`-record diff do not** — they came from an interactive `cmp`/`diff` on a
scratch regeneration that was not captured. They are reproducible from the
committed artifacts (`ref/scripts/regen_gate.sh` against
`tb/scripts/model_v2_s1.txt`) but they are **not attested by a log in this
directory**, and are stated here as recollection-grade rather than
evidence-grade.

**`<!--cites:noquote-->` on 26 rows, and what it does and does not mean.** The
§7.1 / §7.4 / §7.3 / §7.5 tables are a *pre-migration* census; their quoted
source text has moved or no longer exists. Each such row now carries the
checker's own exemption marker, and each SECTION carries a dated **LANDED**
banner saying so. **`EXIST` and `RANGE` still run on every one of them** —
only the quotation is exempt. Anyone using those tables as a to-do list is
reading a closed one, and the banner says that too.

**THE CHECKER'S REAL BLIND SPOT, restated because this gate kept walking into
it.** A `QUOTE` check fires only when the quotation shares a **markdown line**
with its citation. A citation on a line of its own — every entry in a
multi-line list, most table cells naming a symbol in prose — is range-checked
and nothing more. §7.6 A's nine landmarks were **uniformly 19 lines wrong** and
passed `SPEC CITES: PASS` twice, including the pass that accompanied a note
claiming they had been "re-derived from the file". **"Run the checker last"
does not cover this class**; only reading the cited line does. Every landmark
in this round was read back off the file before it was written.

**`PENDING` maintenance:** `evidence/qwen9b/g1/RUNG_INT8_STATE.md` was already out of `PENDING`
(T1's review round did it); this gate added `G2A_HOST.md` and
`damage_defect_b.py`'s entries are now live paths and reported as `PENDING`
only because the set is left in place deliberately — see the comment in
`evidence/qwen_next/spec_cites.py`, which explains why leaving a landed entry
costs a silent `EXIST`.

---

## 8. Documentation work items (plan Step 6)

**(a) The 34 gate-doc short-forms — DISPOSITION: NOT DONE, and the spec's own
scope note says it need not be.** `./evidence/qwen_next/spec_cites.py
evidence/qwen2b/rc/RC_GATE.md evidence/qwen2b/rd/RD_GATE.md` still reports
them. **These are pre-existing and this migration did not write them** (spec
§8 G2's scope note: "cleaning those is optional follow-on work, not a G2
requirement"). This gate spent its citation budget on the **31 orphan
continuations in the spec**, which were silently unchecked rather than merely
unresolved, and on the seven real failures de-orphaning surfaced. Recorded as
open rather than quietly dropped.

**(b) The 17 spec prose residuals — DISPOSITION: PARTIALLY SUPERSEDED, and the
count is not carried forward.** The plan asks to *produce* the enumeration
rather than trust the number. What this gate produced instead is a **mechanical
enumeration of a strictly larger and better-defined class**: the 31 ORPHAN
lines, every one of which was in the checker's blind spot *by construction*
rather than by judgement, plus the 7 failures they were hiding. The
right-file/in-range/no-quotation class the item names remains open, and **the
count of 17 is not repeated here** — it came from a review report and this
gate did not verify it, which is exactly what the plan says to do with such a
number.

---

## 9. NOT ESTABLISHED

1. **No 9B stream was emitted, and none can be yet.** `SCRATCH_MAX = 65536`
   does not make a 9B layer body emittable: `enc_isa_saddr`, `ARG0_HEAD_BITS`,
   `VNW_ISA_MAX` and `ALU_LEN_MAX` all refuse first. That is expected (Task 11
   emits the streams, not Task 5) and it is why the 9B geometry in this gate is
   proven only by import-time asserts, the SCA/PEAK arithmetic and the `ref/`
   selftests — **not** by a generated artifact.
2. **The 9B SCA map is checked against the study's allocator, not against
   hardware.** `SCA_SZ = 1056`, tiles `0/32/96/160/288/416/544/800/928`, and
   `PEAK = 50,208` reproduce `evidence/qwen_next/feas/scratch_peak.py` exactly
   — which is agreement between two implementations of the same algebra, not a
   measurement. G4's OOC run is where scratch depth becomes **T**.
3. **`sw/tok_meter.py`'s repack is not exercised end to end.** The tool needs a
   board and the board is off-limits until T15. What is proven is that it now
   asks `plan_weights` for the layout it actually uploads; what is not proven
   is a DMA. G6 step 7 should still be able to fall back to
   `evidence/qwen2b/rd/rd_census.py`, as spec §9's D-TOK row says.
4. **The untied 9B head is NOT in this gate.** `ref/gen_model_script.py:500`,
   `ref/seq_chat.py:1372`, `sw/infer.py:696-697`, `ref/audit_ranges.py:493` and
   `ref/calib_stats.py`'s `HEAD_KEY` hook all still assume a tied head. That is
   **Task 5's Step 1** by the plan's own assignment, and touching it here would
   have been doing another task's work. `ref/calib_stats.py` is in this task's
   file list for that reason and **needed no G2a change**; it is not in the
   commit.
5. **`RS_F = 7` under `int16` is still unmeasured** (A1.8). This gate lands the
   plumbing; the value is 8.
6. **The RTL twins of every widened host bound are untouched**, by design:
   ARG field widths (Task 7), `vecnorm_unit` at N=4096 (Task 8), the
   `layer_chan` bank depth and the kvhead slice (Task 10). Every widened host
   constant carries a comment naming its owning task.

---

## 9a. UNCOVERED SURFACE — what this gate did NOT execute

Stated as a limitation of the gate, not of the code, because "the selftests
pass" is a claim about the surface the selftests reach.

* **`sw/tok_meter.py`: 0 % executed.** Every line changed for D-TOK — the
  `rows_of` plan, the per-channel `wbase_chan`, the reworked `active` tuples,
  the two new embedding-stride asserts — needs a board. Nothing here ran it.
  Its layout change is *measured* (§0: 186/187 images move) but its DMA path
  is unexecuted, and the `--four-chan` + `--skip-upload` combination is the
  hazard to watch at G6.
* **`sw/infer.py`'s `step()`: not executed.** Defect B's fix is proven by AST
  inspection and by re-running the numeric core standalone; the real `step()`
  needs a board. The `dnz` fix (B1) is on that same path — its six callers are
  covered by `isa_guards_check.py` at the emitter, not end to end.
* **The 2B paths generally.** `evidence/qwen2b/rd/rd_boardfree.sh` runs at an **unset**
  `FABLE5_MODEL`, i.e. 0.8B. The 2B geometry is exercised by the byte-lock
  (`t4_bytes_unmoved.sh`) and the three-tag `ref/` sweep, but **no `sw/`
  selftest runs at `FABLE5_MODEL=2b`**, so the `sw/` changes are proven inert
  at 0.8B and by inspection at 2B.
* **9B `sw/` paths: unreachable by construction.** No 9B artifact exists, so
  every 9B host path is proven only by import-time asserts and
  `isa_guards_check.py`'s synthetic calls.
* **`sw/chat_seq.py`'s `attach_sampling` head block: not executed.** The
  `HC.open_head` call and the `rs_f` refusal beside it are reached only when
  `need_head` is true — `self.verify_head or (want and offline and not
  fixture)`. Selftest [16] sets `sv.head = _FakeHead(...)` **directly**, so it
  exercises the head CONSUMER and never the block that opens one and checks
  its dequant exponent against the manifest. That block is where B6's
  consume-side lands, so B6 is proven at the emitter
  (`isa_guards_check.py`) and by `split_manifest`/`HeadSpec` unit checks, and
  **not** through the path that would run on a board.
* **The `SCRATCH_WORDS` board callers — FIXED THIS ROUND, and previously
  uncovered.** `layer_read_scratch`'s three live call sites (including
  `verify_chip_golden`) and `layer_zero_scratch`'s three took the host
  constant, which G2a doubled. All now take `SCRATCH_WORDS_BUILT`. None of
  them is executed here — they need a board — so the fix is proven by
  inspection and by the selftests' fake device, not by a device read.
* **The RTL twins of every widened bound: untouched by design**, and therefore
  unverified against real hardware behaviour. That is Tasks 7/8/10.

---

## 10. Handed forward

* **`tb/scripts/gen_chat_i1_vectors.py:191`** writes the per-launch TCNT
  golden from `M.T[s][0]` and `M.T[s][1]` only — a hard **2** KV heads. Inert at 0.8B/2B (NKV=2) and now a latent
  truncation at NKV=4, since `Mach.T` carries 4. Changing it changes the
  `.chip` FORMAT, so it belongs beside the TB that reads it → **G3**.
* **Four in-tree comments still name the deleted generator**:
  `tb/Makefile:289`, `tb/scripts/gen_seq_c_vectors.py:5`, `tb/tb_vec_alu.sv:3`,
  `tb/tb_vecnorm.sv:5`. None is an invocation — the deletion is safe — but each
  is now a dangling reference. They are in files this task must not touch;
  **G3 opens all four** for the width work and owns them under D-CITE.
  (`tb/scripts/gen_seq_unit_vectors.py`'s three were self-references to its own
  pre-rename name and were fixed here.)
  *(Updated 2026-09-10, pre-ship documentation chore fix round — this bullet is
  G2a's record, and the pre-ship chore closed the item it hands forward. All
  four comments now carry a dated note that the generator was DELETED at
  `b2f1223`, so none of them is a dangling reference any more; and the
  line-count-neutral rewrite moved the dead name one line down in THREE of the
  four. At HEAD it is at `tb/scripts/gen_seq_c_vectors.py:7`,
  `tb/tb_vec_alu.sv:4` and `tb/tb_vecnorm.sv:6` — and
  `tb/scripts/gen_seq_c_vectors.py:5` now names the LIVE
  `tb/scripts/gen_seq_unit_vectors.py` instead. Only `tb/Makefile:289` still
  reads as this bullet describes. The four line numbers above are left at
  G2a's coordinates as the record of what G2a measured.)*
* **`chat_seq.py --selftest` has no `make` target.** `sw/Makefile` exposes only
  `seq_selftest` and `serve_test`; the umbrella suite that nests
  `head_cache._selftest` is invoked by hand, and its recipe exists only as
  prose in `sw/chat_seq.py:101`. Pre-existing; `evidence/qwen2b/rd/rd_boardfree.sh` runs all three,
  which is why this gate caught nothing late.
* **`ref/gen_layer_script.py`'s `M.R(..., 256)` readbacks** are debug reads
  whose LENGTH is emitted into the `.txt`. They are deliberately **not**
  derived: changing one moves bytes. Listed so nobody "fixes" them.
* **The 34 short-forms in `RC_GATE.md`/`RD_GATE.md`** (§8a) remain open.
* **`verify_chip_golden`'s wrapped-duplicate comparison is worth an explicit
  check before G6.** It reads the scratchpad once and indexes it by the
  golden's addresses. Now that the host's `SCRATCH_WORDS` (65,536) is twice
  the built array (32,768), a golden address in `[32768, 65536)` would, on the
  read path, either fall off the end of a `SCRATCH_WORDS_BUILT`-sized read or —
  if some future read wraps rather than truncates — compare word `a` against
  word `a - 32768` and **pass**. No 0.8B/2B golden reaches that range, so
  nothing is wrong today, and this round's fix (read at `SCRATCH_WORDS_BUILT`)
  makes the out-of-range case an IndexError rather than a silent wrap. **G6
  should assert `max(golden["mem"]) < SCRATCH_WORDS_BUILT` explicitly** rather
  than rely on that, because "it raises" is a property of numpy indexing, not
  a check anyone wrote.
* **`slot_plan`'s clamp now diverges from the old one below 24 layers** (N8).
  It clamps to `n_dn - 1` where it used to clamp to `_DN_SLOTS - 1`; those
  agree at 18 DN (0.8B/2B) and at 24 (4B/9B) but differ for any model with
  fewer DeltaNet layers — a 4-DN model would clamp to 3 rather than 23.
  **Latent**: every in-repo caller passes a full 24- or 32-layer type list.
  Recorded because the new rule is the right one and the divergence is real.
* **The TCNT golden's shape is a 2-KV-head format** (N9).
  `tb/scripts/gen_chat_i1_vectors.py:191` writes `T` from `M.T[s][0]` and
  `[1]` only. G2a widened `Mach.T` to `_KVH`, so at NKV=4 the golden would
  silently drop heads 2-3. **Changing it changes the `.chip` FORMAT**, and its
  consumer sizes the field on the TB side — `tb/tb_seq_chip.sv`'s `exp_tcnt0`
  is a 2-entry array. **Both halves are G3's**, and they must move together:
  widening the generator without the TB gives a golden the TB cannot parse.
* **The misattribution history, for whoever writes G3's citations** (N20): the
  §7.5/§7.6 line numbers in the spec have now drifted three separate times in
  this campaign — once from Track L's edits, once from G2a's `slot_plan` fix,
  once from G2a's own review-round fixes. The lesson is mechanical, not moral:
  **re-run `evidence/qwen_next/spec_cites.py` as the LAST action before every
  commit that touches source**, not as a step somewhere in the middle. Three of
  this gate's four post-hoc corrections were line drift caused by a later edit
  in the same wave.

---

## 11. Evidence in this directory

| file | what |
|---|---|
| `G2A_HOST.md` | this document |
| `evidence/qwen9b/g2/t4_bytes_unmoved_before.log` and its `_after` / `_final` twins | the 2B byte-lock, before / mid / final |
| `regen_gate_before.log` | 0.8B baseline, `a69864d2…` |
| `regen_gate_after.log` | **the FAIL** — `8bc5faac…`, the `L` record |
| `regen_gate_after2.log` | after the `slot_plan` fix, `a69864d2…` |
| `evidence/qwen9b/g2/sw_boardfree_before.log` and its `_after` / `_final` twins | `sw/` selftests |
| `evidence/qwen9b/g2/damage_defect_b.py` + one log per tag | the defect-B regression |
| `damage_defect_b_red.py` + `damage_defect_b_red_green.log` | its RED→GREEN control |
| `evidence/qwen9b/g2/isa_guards_check.py` + four logs | every ISA/geometry guard, RED and GREEN |
| `d_stage_check.py` + `.log` | D-STAGE A/B |
| `seq_unit_vectors_check.py` + `.log` | the seq_unit vector A/B, 4 seeds |
| `g2a_census.sh` + `.log` | the literal-census closure sweep, rerunnable |
| `ref_selftests_g2a.log` | the three-tag sweep |

Every log is produced through `evidence/qwen9b/run.sh` (host, date, tree + dirty
flag, cmd, per-host `test -x` venv probe, `nproc --all`, thread pinning, rc),
which refuses to overwrite an existing log.

---

## DATED CORRECTION (2026-08-31, added by G2b) — two claims in this document about `spec_cites.py`

> ### PRE-G3.3 ROWS, KEPT AS THE RECORD — dated note 2026-09-02 (Task 9)
>
> Rows here marked `<!--cites:noquote-->` quote **source that G3.3 DELETED**,
> not source that merely moved: the `cfg_w8` / `cfg_g64` ports and everything that selected on them, SHAPE bits 28 and 29, and the W8-envelope adder tree.  They are kept verbatim, because they
> are the record of what the pre-G3.3 tree said and the argument they support
> rests on them (§0: nothing is deleted or struck).  The exemption marker is
> used for exactly the reason §7.6 gives — *"an exemption is for source that
> no longer exists, not for a citation that has merely moved"* — and every
> citation that had merely MOVED was RENUMBERED instead, mechanically, by
> `evidence/qwen9b/o3/o3_cite_drift.py --base a08a90b`.
> **The post-G3.3 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_3_MATVEC.md` §11.1.**

Appended rather than edited, per this campaign's own discipline. Nothing above
is changed; both items below correct statements made above.

**1. The `PENDING` maintenance paragraph is WRONG about
`evidence/qwen9b/g1/RUNG_INT8_STATE.md`.** It states that path *"was already
out of `PENDING`"* and credits T1's review round. It was not out:
`git show c9d2a2f:evidence/qwen_next/spec_cites.py` — the tree this document
was committed against — still lists it. T1's review round refreshed five
markers and this was not among them. **G2b removed it**, along with this
document's own entry and `evidence/qwen9b/g2/damage_defect_b.py`'s, and
declares all four removals in `evidence/qwen9b/g2/FINAL_BYTELOCK.md` §9. No
reported count moves either way, because every one of the four paths exists —
which is exactly why a stale `PENDING` entry survives unnoticed until the day
someone deletes the file it names.

**2. This document could not be `--selftest`ed when it claimed the checker was
sound, and neither could any zero-quote gate doc.** The paragraph above about
the QUOTE blind spot is correct and its lesson stands. What was not known when
it was written is that `--selftest` **crashed** on this document:
`evidence/qwen_next/spec_cites.py` asserted that the document under test
carries a line holding both a citation and a quotation of it, and a zero-quote
document carries none by definition. This document cites `rtl/conv4_silu.sv:50`,
`rtl/matvec_chan.sv:18` and `rtl/seq_unit.sv:330`, so it passed the *first*  <!--cites:noquote-->
assert and still died at the second — **the trigger is zero-quote, not
host-only**, and G2b's first write-up of it got that wrong too before review
corrected both.

Consequence, stated plainly: **every `SPEC CITES: PASS` this document reports
was reported without a working negative control behind it.** The passes stand —
normal mode was never broken, and G2b re-checked this document at `FAIL 0`,
identical to `c9d2a2f` — but the assurance was thinner than this document
implied. Repaired at G2b: `--selftest` now derives its perturbation targets
from the document, synthesizes a verified cite+quotation line when there is
none, and resolves bare-filename cites against the *original* directory. **This
document now runs 6/6 CAUGHT plus its positive control**
(`evidence/qwen9b/g2/spec_cites_selftest_regression.log`).
