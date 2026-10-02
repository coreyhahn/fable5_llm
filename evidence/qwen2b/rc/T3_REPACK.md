# R-c Task 3 — the per-channel DDR weight repack (the V5 fit prerequisite)

**Claim.** `sw/hwmap.py:plan_weights` now packs weight images **per channel**
on request. With it, 2B **V5 (W8 everywhere)** occupies **464.8 MiB on the
busiest of four channels — 36.3 % of the 1,280 MiB window — FIT PASS**,
against 1,847.3 MiB (144.3 %, REFUSED) as the single nch-independent span
every pre-R-c artifact uses. The repack is **opt-in** (`SEQ_REPACK=1`); with
it off, the 0.8B `.e` and `.e4` streams regenerate **byte-identical**.

Logs here: `t3_locks_before.log` / `t3_locks_after.log` (`t3_locks.sh`),
`t3_audit_prod.log` (`t3_audit_prod.sh` + `t3_audit.py`), `t3_fit.log`,
`t3_goldens.log`, `t3_tb_seq.log`, `t3_sw_selftests.log`
(`t3_sw_selftests.sh`).

Files: `sw/hwmap.py`, `sw/layer_test.py`, `sw/seq_run.py`, `sw/chat_seq.py`,
`ref/seq_format.py`, `ref/seq_model.py`, `ref/seq_chat.py`,
`ref/scripts/bytes_per_token.py`, `tb/scripts/gen_seq_unit_vectors.py`,
`tb/scripts/gen_seq_chip_vectors.py`, `tb/scripts/gen_chat_i1_vectors.py`,
`tb/Makefile`, `docs/SEQ_ISA.md` (B14), `docs/USAGE.md`,
`docs/ARCHITECTURE.md`.

---

## 1. What the addressing was, and what it is now

TRACED FIRST (the plan's instruction). A per-record weight address is built
in exactly one place on each side:

| side | expression | file |
|---|---|---|
| emitter | `wbase = w["base"] + r0 * w["stride"]` | `ref/seq_format.py` `_mvgo` / `_mvgo_at` |
| host | `local = wbase_of[wid] + r0 * stride` | `sw/seq_run.py:plan_weight_split` |
| golden | `off = wbase - p["base"]; row = off // stride` | `ref/seq_model.py:DDRWeights._lookup` |

and `w["base"]` came from ONE cursor: `plan_weights` (a copy in
`sw/layer_test.py`, its twin `plan_weights_from_wids` in `seq_format`) walked
the wids in order adding `align(nrows*stride, WID_ALIGN)` — **no `nch`**. So
every channel reserved the WHOLE image and `SEQ_NCH=4` only chose which rows
of that reserved span each channel actually held. That is why V4_V5.md §5's
nch=4 column was bytes, not a fit.

R-c parameterizes that cursor and nothing else:

* `hwmap.plan_weights(man, wdir, nch, rows_of)` — `rows_of(wid, nrows)`
  returns the per-channel row counts; each channel advances its own cursor by
  `align(rows[c]*stride)`. `rows_of=None` (the default) is the old behaviour
  BIT FOR BIT: `rows=[nrows]*nch`, identical cursors, an int per wid.
* `seq_format.weight_pieces_at(...)` returns each piece's `row_off` — the row
  index **inside that channel's copy** — beside the global `r0`. Without the
  repack `row_off == r0`, which is why the frozen streams do not move.
* the ILV head needs exactly this: its channel rows are strided through the
  image (chunk j on channel j%nch), so no affine rebase can express it; its
  BYTES are contiguous from the channel's own base in interleave order.
* an image is placed at its FIRST MVGO (the per-channel row counts depend on
  the layout, which is pinned there), so the allocation order is wid order —
  and `_finalize` now RAISES, rather than noting, if the plan recomputed from
  the final wids disagrees with the one the records were built from.  No
  `.seq` is written in that case, because the MVGOs already encode the old
  addresses.

`sw/layer_test.py`'s duplicate `plan_weights` is **deleted** and re-exported
from `hwmap` (the pre-D review's "one authority" fold). `seq_run`,
`chat_seq`, `infer.py`, `tok_meter.py` all resolve to the same function.

## 2. The frozen-behaviour locks (before AND after)

`evidence/qwen2b/rc/t3_locks_before.log`, `t3_locks_after.log` (script:
`t3_locks.sh`, run on snoke).

| lock | what | sha256 | before | after |
|---|---|---|---|---|
| A | `regen_gate.sh` — 0.8B `.e` stream + `.txt` | `a69864d2…f444aaf1` | PASS | **PASS** |
| B | `SEQ_NCH=4` `.e4` stream, regenerated to a TEMP path | `e102e2df…6d8ac933` | PASS | **PASS** |
| B′ | …**and its `.seq.json`** — where the weight base map lives, OUTSIDE the sha256'd stream (review I4) | `cmp` identical, 74,015 B | — | **PASS** |

Both regenerate byte-identical after the repack, at nch=1 and nch=4, with
`SEQ_REPACK` unset.  (`t3_locks_after.log` is the run on the FINAL tree,
after the `_finalize` divergence check below was made fatal.) Lock B's gold is the committed
`tb/scripts/w4/model_v2_s1.e4.seq`; the frozen files were never overwritten
(regeneration goes to `mktemp -d`).

*Provenance note, recorded rather than smoothed over:* the BEFORE run's lock A
completed on the pristine tree; its lock B overlapped the first edits to
`ref/seq_format.py` by ~4 minutes of a 5-minute generator run. It passed, and
lock B's gold is a property of a committed file rather than of that run, so
the baseline stands — but the AFTER run is the load-bearing one and it ran
wholly on the finished tree.

## 3. The fit — with the real allocator

`ref/scripts/bytes_per_token.py --fit` walks **the shipped
`hwmap.plan_weights`** (not this file's re-implementation) and asserts every
channel top `< EMB_BASE`. Full log: `evidence/qwen2b/rc/t3_fit.log`.

| model / map | nch | pack | busiest channel | window | verdict |
|---|---|---|---|---|---|
| 2b `all:w8g128` (**V5**) | 4 | repack | **464.8 MiB** | 36.3 % | **FIT PASS** |
| 2b `all:w8g128` | 4 | nch-independent | 1,847.3 MiB | 144.3 % | FIT FAIL (refused) |
| 2b `all:w8g128` | 1 | — | 1,847.3 MiB | 144.3 % | FIT FAIL (refused) |
| 2b `all:w4g64gptq,gate_up:w8g128` | 4 | repack | 311.9 MiB | 24.4 % | FIT PASS |
| 0.8b `all:w4g128` (today) | 1 | — | 398.2 MiB | 31.1 % | FIT PASS |
| 0.8b `all:w8g128` | 4 | repack | 190.8 MiB | 14.9 % | FIT PASS |

V5 per channel: `0x2d0c4000 / 0x2cdac000 / 0x2cca4000 / 0x2cca4000` =
464.8 / 461.7 / 460.6 / 460.6 MiB. Matches V4_V5.md §5's ~465 MiB / 36 %.
The checker has teeth in BOTH directions: the overflow rows above are
`plan_weights` refusing the pack, reported (exit 1), not crashing.

**No EMB collision.** The 2B embedding table is 248,320 x 4,096 B = 970.0 MiB
at `EMB_BASE 0x6000_0000`, ending `0x9CA0_0000` — inside the 4 GiB channel and
above every weight top by construction (`top < EMB_BASE` is asserted per
channel). `sw/hwmap.py`'s map comment now says the 485 MiB figure is
0.8B-specific and records the 2B numbers (V4_V5.md §5's carried item).

Cross-check: `--fit` also compares against `packed_footprint`, the
INDEPENDENT re-implementation already in that file — **AGREES** on every row.

## 4. What proves the addresses — and what does NOT

**A CORRECTION, kept in place of the claim it replaces (R-c review C2).**
The first version of this file said the `.txt`-vs-`.seq` replay gate below
"proves the golden resolves each per-channel address back to the right global
rows". **That is false**, and the review demonstrated it by mutation: a
systematic +32 KiB shift of the whole pack PASSES the gate silently, and so
does forcing every interleaved chunk to packed row 0. Two reasons, both
structural:

* the gate is a CONSISTENCY check. The golden reads its plan out of the same
  `.seq.json` the stream was built with, so any placement that is
  self-consistent replays identically — an address map that is uniformly
  wrong is invisible to it.
* the ILV head's y32 lands in the emitter-declared **staging window**, which
  the gate excludes from its scratch comparison, and AMAX32 is a
  strictly-greater scan, so duplicated rows TIE rather than diverge. And in
  the runs originally cited, every ILV chunk happened to sit at packed row 0
  (one chunk per channel), so the rebasing arithmetic was never exercised at
  all.

What the gate DOES prove is still worth having: that the whole decode — every
CONTIG image's row mapping included, since their y32 lands in checked scratch
— is bit-identical to the host-driven `.txt` run under the repacked
addressing. It is a strong regression test and a weak placement test.

**The placement proof is (d): range EQUALITY plus mutation kills.**

**(a) End to end through the real emitter** — `gen_token_script.py` (random
weights, no checkpoint), `SEQ_NCH=4 SEQ_REPACK=1`, then `seq_model --gate`:

```
tok2_r4  (vocab 8192)  SEQ GATE: PASS   72/72 checkpoints bit-exact, TOKENS IDENTICAL
tok7k    (vocab 7000)  SEQ GATE: PASS   72/72 checkpoints bit-exact, TOKENS IDENTICAL
```

`tok7k`'s 7,000-row LM head splits 2048/2048/2048/**856** — an uneven ILV
split — and its four head MVGOs read

```
rec 1207: chan 0 WBASE 0x1053e000 -> packed row 0, 2048 rows   (global rows 0..2047)
rec 1208: chan 1 WBASE 0x1053e000 -> packed row 0, 2048 rows   (global 2048..4095)
rec 1209: chan 2 WBASE 0x1053e000 -> packed row 0, 2048 rows   (global 4096..6143)
rec 1210: chan 3 WBASE 0x1053e000 -> packed row 0,  856 rows   (global 6144..6999)
```

Every channel reads its own chunk at ITS OWN packed row 0 — which is exactly
why this run does not test the rebasing: `row_off` is 0 everywhere in it.
Read it as what it is: the emitter really does emit per-channel bases (the
same model without `SEQ_REPACK` puts those four at `0x114f6000 / 0x11616000 /
0x11736000 / 0x11856000`, global rows), busiest channel **24.81 MiB** against
the repack's **6.37 MiB** on 16 images, and the decode is unharmed.

**(b) RTL, 4 seeds** — `tb/scripts/gen_seq_unit_vectors.py:build_repack` adds
`seq_h_repack1..4` to `tb_seq`, one configuration per seed (nch 2/4/3/4,
chunk 16/16/32/8, ILV on a different image each time), every MVGO addressed
from the REAL allocator. The generator asserts the case is not vacuous (some
image's per-channel bases must differ by more than one `WID_ALIGN`).

```
SEQ PASS: scripts/seqvec/seq_h_repack1 (writes 1974, reads 3400, scratch 1096)
SEQ PASS: scripts/seqvec/seq_h_repack2 (writes 3089, reads 7332, scratch 1188)
SEQ PASS: scripts/seqvec/seq_h_repack3 (writes 2441, reads 5001, scratch 1161)
SEQ PASS: scripts/seqvec/seq_h_repack4 (writes 4019, reads 10905, scratch 1177)
make tb_seq: 23/23 vectors PASS
```

The stub seeds its RES from the WBASE, so a mangled address also moves the
MOVY'd scratch words — the `.exp` catches what the `.wtr` would.

**(c) Python goldens** — `ref/seq_model.py --selftest` gains
`selftest_repack`: two W8 images over nch=2 (one ILV), placed by the emitter's
allocator, DMA'd by `sw/seq_run.plan_weight_split` (the real host function),
executed as real MVGOs and compared against `w4a8_ref.matvec_y32_w8` on the
rows each piece is supposed to hold. Here `row_off != 0` does occur (the ILV
image gives a channel several chunks), and the negative controls are the
point:

```
REPACK (nch=2, 2 W8 images, 7 pieces): every piece's MVGO == matvec_y32_w8 on
its global rows; per-channel packs [5440, 5248] B vs one span 10688 B;
8 wrong-plan/wrong-channel lookups refused or diverted — PASS
```

**(d) THE PLACEMENT PROOF: range equality + mutation kills, at production
shape** (`t3_audit.py`, `t3_audit_prod.sh`, log `t3_audit_prod.log`).

Per channel, the byte ranges the HOST writes must be EXACTLY the ranges that
channel's engine reads. Containment ("every MVGO lands inside something the
host wrote") is not enough — a stream that reads one chunk of an interleaved
image over and over is contained, and that is precisely a broken rebasing —
so the merged range sets are compared for EQUALITY, which fails from both
sides. Run on the 187-image production artifact, both packs:

```
=== model_v2_s1.er        187 images, nch=4, repack=True
    tops 0x1645c000/0x16384000/0x1633c000/0x1633c000   (flat: 0x28e34000)
    chan 0..3: host spans == engine spans, 100.30 / 99.45 / 99.17 / 99.17 MiB
    RANGE EQUALITY: PASS  (3464 MVGOs resolved to global rows)
    wid 186 (ILV, 122 chunks of 2048): chunk j -> chan j%4, every row once: PASS
    mutation +32 KiB base shift                      KILLED
    mutation ILV chunks collapsed to packed row 0    KILLED
    mutation repacked image addressed by GLOBAL row  KILLED
=== model_v2_s1.e4        187 images, nch=4, repack=False   (the frozen one)
    ... same four per-channel byte counts, RANGE EQUALITY: PASS,
    mutations KILLED (the third does not apply to a one-span pack)
```

Three things fall out of that:

1. the ILV head's 122 chunks are checked in **GLOBAL row** terms (the audit
   resolves each MVGO through the host's own piece list), so `row_off != 0`
   IS exercised at production shape: chunk j -> channel j%4, every row
   covered exactly once, on a stream where a channel holds 30-31 chunks at
   packed rows 0, 2048, ... 61440;
2. the mutations that the replay gate passes silently are all KILLED here,
   including "a repacked image addressed by its GLOBAL row" — the exact bug
   the repack could have had;
3. the per-channel byte counts are IDENTICAL between the two packs
   (100.30/99.45/99.17/99.17 MiB). The repack changes WHERE the rows go, not
   WHICH rows a channel gets — which is the invariant Task 4's images depend
   on.

`sw/seq_run.audit_weight_ranges` + the three mutators are the same code the
selftest runs, so this is a permanent gate, not a one-off: `--selftest` now
runs the audit AND requires every applicable mutation to be killed, on every
artifact including a synthetic REPACKED one it builds for the purpose.

## 5. Test summary (all green)

| gate | result |
|---|---|
| `regen_gate.sh` (.e/.txt) | PASS, sha `a69864d2…` |
| `.e4` 4-chan regeneration | PASS, sha `e102e2df…` |
| `make seq_selftest` | 2,735 passed, 0 failed (was 2,574) — now includes a SYNTHETIC REPACKED artifact through the whole loop |
| `make serve_test` | 85 passed, 0 failed |
| `chat_seq.py --selftest` | 337 passed, 0 failed |
| `ref/seq_model.py --selftest` | W8 PASS + REPACK PASS |
| `bytes_per_token.py --selftest` | PASS |
| `make -C tb tb_seq` | 23/23 vectors PASS (incl. `repack1..4`) |
| `seq_model --gate` on repacked streams | 2/2 PASS (a consistency gate — see §4) |
| `t3_audit.py` at production shape (187 images, both packs) | RANGE EQUALITY PASS, 5/5 applicable mutations KILLED |

## 6. Contract notes for Task 4 / Task 6

* Emit with `SEQ_NCH=4 SEQ_REPACK=1`. `.seq.json` then carries
  `"weight_repack": true` and each `weights[wid]["base"]` is a LIST of nch
  channel-local addresses. ABSENT means false, as `"g"`/`"w8"` do.
* Hosts need no new flag: `sw/seq_run.plan_weights_for(manifest, wdir, meta)`
  reads it out of the stream. A plan and a meta that disagree are REFUSED by
  `plan_weight_split` and by `DDRWeights`, never inferred.
* `check_mvgo_targets` now resolves a repacked WBASE against the RECORD'S OWN
  channel — strictly stronger than the pre-R-c check, which ignored the
  channel because every channel held the same span.
* `DDRWeights.from_files` also verifies image file size == `nrows*stride`
  (T2's carried item): a W8 image paired with a W4 plan differs only in size,
  and would otherwise read half an image as a whole one.
* `sw/seq_run.audit_weight_ranges(recs, manifest, wbase_of, nch, wchans,
  meta)` is the check to run on the first repacked artifact: host-written
  spans == engine-read spans, per channel. `evidence/qwen2b/rc/t3_audit.py
  <prefix>` runs it plus the mutation kills on any artifact.
* `--selftest` builds its own synthetic repacked artifact
  (`write_synth_repack_artifact`) and runs the entire artifact loop over it,
  so the per-channel path is gated by `make seq_selftest` before any board
  work starts.
* The RTL is untouched. An address is an address; the engine reads its own
  channel.
