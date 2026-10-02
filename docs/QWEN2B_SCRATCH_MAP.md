# Qwen3.5-2B scratch map (Track R, task R-a) — derived 2026-08-12

**Verdict: FITS.** Peak scratch word touched at H=2048/FFN=6144 is
**25,600** of the 32,768-word budget — 7,168 words (21.9%) spare. No region
exceeds 32K, so the R-b scratch sizing (16K -> 32K, ~+14 RAMB36) stands.

The map is no longer a table of literals. `ref/gen_layer_script.py` now
derives every region base and size from the `FABLE5_MODEL`-selected
geometry in `ref/layer_ref.py`, and `scratch_map()` returns the whole
table. Both tables below are printed **by that function**, not transcribed:

```bash
cd ref && FABLE5_MODEL=2b ./.venv/bin/python -c \
  "import gen_layer_script as G; [print(k, v) for k, v in G.scratch_map().items()]"
```

## Why only two numbers move

2B is a pure width scale-up. Comparing the two committed configs
(`ref/qwen3_5_0.8b_config.json` vs `ref/qwen3_5_2b_config.json`), the ONLY
fields that differ are `hidden_size` 1024->2048 and `intermediate_size`
3584->6144. Everything the scratch map is sized by is otherwise identical:

| quantity | 0.8B | 2B |
|---|---|---|
| `H` hidden | 1024 | **2048** |
| `FFN` intermediate | 3584 | **6144** |
| `CONV_DIM` = 2·LKD+LVD | 6144 | 6144 |
| `LKD` / `LVD` | 2048 / 2048 | 2048 / 2048 |
| `LNH` / `LDK` / `LDV` | 16 / 128 / 128 | 16 / 128 / 128 |
| `NQ` / `NKV` / `HD` | 8 / 2 / 256 | 8 / 2 / 256 |
| layers (DN / GQA) | 24 (18 / 6) | 24 (18 / 6) |
| vocab | 248,320 | 248,320 |

So every DeltaNet-side and attention-side tile keeps its size; only the
residual/norm/int8 vectors (H) and the MLP tiles (FFN) grow.

## Derived quantities

```
STGCH = 2 * min(CHUNK, H)        # words one y32 chunk of an H-row matvec needs
                                 # (CHUNK = 2048 int32 host injection chunk)
      = 2048 @ 0.8B              # = 4096 @ 2B   <-- the staging window grows
X0  = 0            XN  = H       X8  = 2*H
SCA = 3*H          (992 words of H-independent DeltaNet scalars, padded to 1024)
STG = SCA + 1024   STG_SZ = LVD + STGCH
BIG = STG + STG_SZ               # base of the per-body big tiles
```

## The map at H=2048, FFN=6144 (2B)

| region | base | size | end | note |
|---|---|---|---|---|
| `X0` residual | 0 | 2048 | 2048 | live end-to-end |
| `XN` normed | 2048 | 2048 | 4096 | transient, per norm |
| `X8` int8 act | 4096 | 2048 | 6144 | transient, per matvec group |
| `SCA` DN scalars | 6144 | 992 | 7136 | B16/A16/GD/QN/QNS/KN/DO32/OH/NH |
| `STG` staging | 7168 | 6144 | 13312 | W/W32 window + out-proj x8 |
| **DN body** | | | | |
| `DN.QKV` | 13312 | 6144 | 19456 | conv q\|k\|v, 16-bit |
| `DN.Z16` | 19456 | 2048 | **21504** | z branch — DN peak |
| `DN.ON` | 2048 | 2048 | 4096 | gated outputs, overlays `XN` |
| `DN.OUTSTG` | 9216 | 4096 | 13312 | out-proj y32 stage |
| `DN.OUTDST` | 13312 | 2048 | 15360 | residual delta, overlays dead `QKV` |
| **ATTN body** | | | | |
| `AT.QG` | 13312 | 4096 | 17408 | q_proj out = q \| gate |
| `AT.K16` | 17408 | 512 | 17920 | k_proj out |
| `AT.V16` | 17920 | 512 | 18432 | v_proj out |
| `AT.QR` | 18432 | 2048 | 20480 | roped q |
| `AT.KR` | 20480 | 512 | 20992 | roped k |
| `AT.AO32` | 7168 | 512 | 7680 | ATTN out (int32) |
| `AT.OG` | 7680 | 256 | 7936 | sigmoid gate |
| `AT.GATED` | 7936 | 2048 | 9984 | gated heads |
| `AT.GX8` | 10048 | 2048 | 12096 | o_proj int8 input |
| `AT.OSTG` | 15360 | 4096 | 19456 | o_proj y32 stage |
| `AT.ODST` | 21504 | 2048 | **23552** | residual delta — ATTN peak |
| **MLP body** | | | | |
| `ML.GP` | 7168 | 12288 | 19456 | gate\|up int32 pairs |
| `ML.SG` | 19456 | 6144 | **25600** | silu(gate) — MLP peak |
| `ML.DSTG` | 19456 | 4096 | 23552 | down y32 stage (reuses `SG`) |
| `ML.DDST` | 23552 | 2048 | 25600 | residual delta |
| **head tail** | | | | |
| `HD.LNF` | 7168 | 2048 | 9216 | final-norm weight staging |
| `HD.AMAX` | 7168 | 4096 | 11264 | argmax y32 chunks |

```
PEAK_DN = 21504   PEAK_ATTN = 23552   PEAK_MLP = 25600
PEAK    = 25600  <=  SCRATCH = 32768        (7168 words spare)
```

## The same map at H=1024, FFN=3584 (0.8B) — unchanged, byte for byte

| region | base | size | end |
|---|---|---|---|
| `X0` / `XN` / `X8` | 0 / 1024 / 2048 | 1024 each | 3072 |
| `SCA` DN scalars | 3072 | 992 | 4064 |
| `STG` staging | 4096 | 4096 | 8192 |
| `DN.QKV` / `DN.Z16` | 8192 / 14336 | 6144 / 2048 | **16384** |
| `DN.OUTSTG` / `DN.OUTDST` | 6144 / 8192 | 2048 / 1024 | 8192 / 9216 |
| `AT.QG`/`K16`/`V16`/`QR`/`KR` | 8192/12288/12800/13312/15360 | 4096/512/512/2048/512 | **15872** |
| `AT.AO32`/`OG`/`GATED`/`GX8` | 4096/4608/4864/6976 | 512/256/2048/2048 | 9024 |
| `AT.OSTG` / `AT.ODST` | 9216 / 12288 | 2048 / 1024 | 11264 / 13312 |
| `ML.GP` / `ML.SG` | 4096 / 11264 | 7168 / 3584 | **14848** |
| `ML.DSTG` / `ML.DDST` | 11264 / 13312 | 2048 / 1024 | 13312 / 14336 |
| `HD.LNF` / `HD.AMAX` | 4096 / 4096 | 1024 / 4096 | 5120 / 8192 |

```
PEAK_DN = 16384   PEAK_ATTN = 15872   PEAK_MLP = 14848
PEAK    = 16384  ==  SCRATCH = 16384        (exactly full, as before)
```

Every one of these values is asserted at import time against the frozen
literal it replaced (`_LEGACY_MAP` in `ref/gen_layer_script.py`), so a
refactor that moves a 0.8B address fails on import, before the regen gate
even runs.

**One derivation, three views.** The region algebra lives exactly once, in
the module-level constants (`DN_QKV`, `AT_OSTG`, `ML_SG`, …). The emitting
bodies alias those names, `scratch_map()` reports them without re-deriving
anything, and `PEAK_DN`/`PEAK_ATTN`/`PEAK_MLP` are computed from them. Two
further import-time asserts keep the views honest:

```python
assert max(b + s for b, s, _ in scratch_map().values()) == PEAK
assert PEAK <= SCRATCH
```

## Feasibility claims, re-verified

`docs/QWEN2B_FEASIBILITY.md:22-26` claimed "DN body tiles to exactly
16,384 today; at H=2048 DN needs 19,424, MLP 24,576".

| claim | status | as derived |
|---|---|---|
| DN tiles to exactly 16,384 today | **CONFIRMED** | `PEAK_DN` = 16,384 at 0.8B, measured and derived |
| DN needs 19,424 at H=2048 | **corrected to 21,504** (+2,080) | see below |
| MLP needs 24,576 at H=2048 | **corrected to 25,600** (+1,024) | see below |
| total <= 32,768 | **CONFIRMED** | peak 25,600, 7,168 spare |

Both feasibility numbers were tight-packing *lower bounds* computed from
the tile sizes alone. **The two deltas have different causes**, and only
one of them involves the staging window. Neither threatens the 32K budget.

**DN: 19,424 -> 21,504 (+2,080) = +2,048 staging, +32 pad.**
The study's figure is exactly `3H + 992 + 4096 + CONV_DIM + LVD` = 19,424.
Two of its terms move:

- *+2,048, the staging window.* `STG_SZ = LVD + STGCH`, and a y32
  injection chunk of an H-row matvec occupies `STGCH = 2*min(2048,H)`
  words — 2,048 at H=1024 but **4,096** at H=2048. So the window goes
  4,096 -> 6,144, and `BIG` (hence every DN tile) shifts up by 2,048.
  The study assumed the 0.8B window.
- *+32, the `SCA` pad.* `SCA` holds 992 words but `STG = SCA + 1024`. The
  pad is what lands `STG` on the frozen 4,096 at 0.8B, so byte-identity
  requires it. The study summed the raw 992.

**MLP: 24,576 -> 25,600 (+1,024) = the `SCA` pad, and nothing else.**
The MLP peak is `SG`'s end:

```
PEAK_MLP = max(ML_SG + FFN, ML_DDST + H) = max(STG + 3*FFN, STG + 2*FFN + STGCH + H)
```

The dominant term `STG + 3*FFN` **contains no staging term at all** — the
staging-window growth above does not enter the MLP peak. The study's
24,576 is `3H + 3*FFN`, i.e. it based `GP` at `3H`; `GP` actually starts at
`STG = 3H + 1024`. The whole delta is that 1,024-word pad. (Recomputing
with the study's `STGCH = 2048` still gives 25,600, confirming the peak is
staging-independent.)

The second term is a red herring worth naming, because it *looks* like it
should matter: the down-projection stage and its residual delta end at
`STG + 2*FFN + STGCH + H`, which at 2B is **exactly** 25,600 too — the two
terms tie because `STGCH + H == FFN` (4,096 + 2,048 == 6,144) at this
geometry. So `DDST` contributes nothing to the peak. At 0.8B there is no
tie (`STGCH + H` = 3,072 < `FFN` = 3,584) and `SG`'s end dominates outright
at 14,848.

`PEAK_DN`/`PEAK_ATTN`/`PEAK_MLP` are computed in
`ref/gen_layer_script.py`, so these figures cannot drift from the emitter.

## Collision freedom

**Non-overlapping by construction.** Within a single body, the tiles
listed above are disjoint except for the deliberate reuses in the next
paragraph. `X0` (the residual stream) is the only region live across the
whole token, and it occupies `[0, H)` — below every body tile, which all
start at `XN` or above. `SCA` is live only inside the DeltaNet head loop
and is disjoint from `STG` and from every big tile.

**Deliberate reuses, each into a provably dead region.** The emitter
overlays six regions; in every case the overlaid tile has already been
consumed by the command immediately preceding:

| overlay | onto | dead because |
|---|---|---|
| `DN.ON` (gated outputs) | `XN` | `XN` was consumed by the DYNQ8 into `X8` before the first matvec |
| `DN.OUTDST` (residual delta) | `DN.QKV` | `QKV` was consumed head-by-head by the `DNST` loop, which has ended |
| `AT.OSTG` (o_proj stage) | `AT.QG`,`K16`,`V16`,`QR` | `QG`/`QR` consumed by the per-head `ATTN`+gate loop; `K16`/`V16` consumed by the rope loop and `KVAP` |
| `ML.GP` (gate/up pairs) | `STG`, then the whole big block | the layer body has finished; `mlp_block` is the last phase before the residual add |
| `ML.DSTG` (down stage) | `ML.SG` | `SG` (silu(gate)) was consumed by the `EMUL32` that produced `GP` |
| `HD.AMAX` | `STG` | head tail runs after the last layer; staging holds nothing live |

Two overlays that exist at 0.8B **disappear** at 2B, which is a
strict improvement: `AT.GX8` (0.8B: 6,976..9,023) spills past the 0.8B
staging window into `AT.QG`; at 2B it is 10,048..12,095, fully inside the
larger staging window. Likewise `DN.OUTSTG` exactly fills the window at
both geometries by construction (`STG + LVD + STGCH == BIG`).

**Verified empirically, not just argued.** Two independent checks:

- *Self-check.* `dn_token` and `attn_token` assert the residual after
  every token against an independent `layer_fixed.layer_decode_fx` run.
  Any collision that clobbered a live value would corrupt the residual and
  abort generation. This passes at 2B for 4 seeds x 3 tokens x both body
  types, and for a full 24-layer / 187-image model-shaped run.
- *High-water probe.* An instrumented `Mach.mem` (ndarray subclass
  recording every slice bound read or written) reports the peak word
  actually touched. Measured == derived at both geometries: 16,384 @ 0.8B
  and 25,600 @ 2B, over 4 seeds. Evidence:
  `evidence/qwen2b/ra/scratch_probe.log`.

## Downstream consequences for R-b (RTL)

Flagged here because the map surfaces them; none is in R-a's scope.

1. **Command field packing must widen 14 -> 15 bits.** `Mach.C` packs two
   scratch addresses per 32-bit argument (`src | (dst << 14)` in `vn`,
   `rope`, `conv`, `alu`). At 32K scratch an address needs 15 bits.
   Widening to `src | (dst << 15)` costs 30 of 32 bits — it fits, and the
   feasibility note that "addr_lo has spare bits" is confirmed.
   **Exception to check:** `dnst` packs `head | (a_dec << 4) | (a_beta << 18)`
   = 4+14+14 = exactly 32 bits. At 15-bit addresses that is 34 bits and
   **overflows**. It happens to be safe at 2B because `a_dec`/`a_beta`
   point into `SCA` (6,208 / 6,224), still under 16,384 — but R-b must
   either keep those two fields at 14 bits with an assert, or re-pack.
2. **`alu` is already exactly full**: `(p0 & 0x1FFFF) | (dst << 17)` =
   17+15 = 32 bits at a 15-bit `dst`. No spare.
3. **VECNORM N must reach 2048** (`nlog2` = 11), including the
   `n_total <= 11'd1 << cfg_nlog2` overflow already flagged in
   `docs/QWEN2B_FEASIBILITY.md:26-28`.
4. **`MAX_NG` must reach 48** for the K=6144 down-projection.
5. **`SCRATCH` is a power of two derived from `PEAK`** in the emitter
   (`1 << max(14, (PEAK-1).bit_length())`), so it reports 16,384 at 0.8B
   and 32,768 at 2B without a manual switch. R-b's RTL parameter should be
   driven from the same number.
