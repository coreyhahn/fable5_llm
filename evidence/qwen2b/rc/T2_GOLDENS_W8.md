# R-c gate 2 — the Python goldens learn W8 (V5)

Task 2 of `docs/superpowers/plans/2026-08-16-qwen2b-v5-w8.md`. Stacked on
`d581268` (T1: the W8 engine mode + `matvec_y32_w8` + SHAPE bit 29).
Everything numeric ran on **snoke** (`/home/cah/venvs/fable5_np/bin/python`).

## The convention this gate fixes

The weight WIDTH travels exactly the way `g` already does: a manifest /
stream-plan entry carries **`"w8": true` only when set — ABSENT MEANS W4**.
Every reader is `bool(x.get("w8", False))`, so every committed
`.weights.json` and `.seq.json` keeps its meaning byte for byte. `ng` stays
the ng-UNIT count `K//128` in both widths; only `stride` moves
(`w4a8_ref.row_stride8`).

The quantized-dict key is **`"w8"`, not `"w4"`** — the type tag. An int8
code array read as nibbles decodes to garbage *silently*, so the only safe
design is a key the W4 readers do not recognise. `layer_fixed.qw_codes()` is
the single place that knows which key is which.

## Files

| log | what |
|---|---|
| `t2_01_red_selftests.log` | RED: the three selftests written before the implementation |
| `t2_02_green_guards.log` | GREEN + every frozen guard (A–F) |
| `t2_03_fidelity_w8_smoke_0p8b.log` | `fidelity_check --w8` runs end to end at 0.8B |

## RED, and why the middle one matters

```
<HEAD:ref/fidelity_check.py> --w8 → error: unrecognized arguments: --w8
ref/layer_fixed.py             → NameError: quant_linear_w8 is not defined
ref/seq_model.py --selftest    → AssertionError: image is 5440B, expected 17*192=3264
```

The third is not "function missing" — it is **the bug the feature exists to
prevent**: with SHAPE bit 29 ignored, a W8 image gets parsed with the W4 row
law. That is exactly the silent-corruption class the `"w8"` key, the
plan/SHAPE cross-check and `check_weight_plan`'s width comparison close.

## GREEN

`layer_fixed._w8_invariance` — 5 sections, each printing its own verdict:

* `quant_linear_w8` == `w4a8_ref.quantize_weights8` bit-for-bit (keys,
  dtypes, `e`, `sh`, `g`); `rowchunk=7` == one shot (the LM head's route).
* `matvec_fx`/`matvec_to` on a W8 dict == `matvec_y32_w8` by hand, 4 seeds ×
  3 shapes × g128/g64, while a W4 dict on the same call is still
  `matvec_y32`. W8 weight error beats the **MSE** W4 rule by **≥ 14.6×**.
* `quant_layer(w8=True)` → a W8 image behind **15/15** matvecs of both layer
  types; every non-matvec tensor bit-identical to the W4 layer's; 16 decode
  steps with `sat=0`.
* `w8=False` == the argument being ABSENT, at g128 and g64.
* `tighten_e` / `mse_scale=False` / a set `FABLE5_CALIB_STATS` are all
  **refused** (3/3), never ignored. V5 is plain W8; Track Q ruled
  GPTQ-on-W8 out of scope, so a calibrated-looking W8 run must not exist.

`seq_model.selftest_w8_mvgo` — one 17×256 W8 image, offered BOTH ways the
executor can see it (live `{"w8",…}` dict and real `pack_ddr_rows8` bytes
through `unpack_ddr_rows8`), driven by a 3-record stream whose SHAPE word
comes from `hwmap.shape_word(w8=True)`. Both == `matvec_y32_w8`. Then the
bit is proven **load-bearing**: the same image with a W4 SHAPE word, and
`w8|g64`, are both refused (2/2).

```
W8 MVGO (SHAPE 0x200111c2, 17x256, stride 320B): packed-DDR and live-dict
paths both == matvec_y32_w8 (|y|max 3297945), 2/2 wrong SHAPE words refused
```

`fidelity_check --w8 --res-scale 4 --ntok 4 --prompts 1` (0.8B, snoke):
head `e=-8 sh=9`, 24 layers in 10.1 s, **top1 6/7, rank median 0**. The
brief only required it to RUN; the 2B spot-check is Task 4's.

## Frozen guards — all green (verbatim in `t2_02_green_guards.log`)

| guard | result |
|---|---|
| `ref/w4a8_ref.py` selftest | **byte-identical** to HEAD's log (file untouched) |
| `ref/layer_fixed.py` selftest | **W4 sections byte-identical** — delete the 5 new `  w8:` lines and the log equals HEAD's exactly |
| `ref/seq_model.py --gate` on `w3/lay_s1.e` and `w3/tok2_s1.e` | **SEQ GATE: PASS** both; logs differ from HEAD only in the wall-clock seconds they print |
| `bash ref/scripts/regen_gate.sh` | **REGEN_GATE_PASS** (0.8B `.seq` sha256 `a69864d2…`, `.txt` byte-identical) |
| `cd sw && make seq_selftest` | 2574 passed, 0 failed (HEAD: 2570 — exactly +1 per prefix for the new "a W8 plan over W4 images is rejected" case) |
| `cd sw && make serve_test` | backend API PASS, 85 passed / 0 failed |
| `sw/hwmap.py` SHAPE selftest | PASS (`w8=0x2000d1e0`, spare [31:30] zero, w8+g64 refused) |
