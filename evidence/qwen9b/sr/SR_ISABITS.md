# SR-ISABITS — isa_bits' synthetic ATTN on a warm KV slot, and a negative control that can fail

Task SR-ISABITS of the sequencer RTL round (plan `docs/superpowers/plans/2026-09-27-seq-rtl-round.md`).
Operating point `FABLE5_MODEL=9b` (RS_F derived, not exported) on every run; every run on snoke
through `evidence/qwen9b/sr/sr_run.sh`. No RTL, no build, no board.

**Verdict: GREEN.** `evidence/qwen9b/g3/isa_bits.py` is rc 0 on the committed tree a32f59e
(`evidence/qwen9b/sr/n1910_isa_bits_GREEN.log:53-54`); its `--negative-control` is PASS with
19 of 19 perturbations refused by their own check (`evidence/qwen9b/sr/n1911_isa_bits_negctl_GREEN.log:27-29`);
a deliberately broken control FAILs (`evidence/qwen9b/sr/n1912_isa_bits_negctl_broken_kvhead_FAIL.log:23-29`).
The warm/cold rule in `ref/gen_layer_script.py` is untouched (this task edits no file under `ref/`).

## 1. RED at HEAD (b6cf9bb)

| run | log | result |
|---|---|---|
| the gate | `evidence/qwen9b/sr/n1900_isa_bits_RED_HEAD.log:46-49` | **FAIL rc 1** — `ATTN: KV slot 0 is COLD (E_DMA_COLD)` in section 3 |
| `--negative-control` | `evidence/qwen9b/sr/n1901_isa_bits_negctl_RED_HEAD.log:26-27` | prints **PASS rc 0** although the unperturbed run fails |
| the same with every perturbation monkeypatched to a NO-OP | `evidence/qwen9b/sr/n1902_isa_bits_negctl_noop_RED_HEAD.log:31-37` | **still PASS rc 0** — the control is vacuous: a perturbation that changes nothing is "refused" by the COLD assert |

The cause is 75598a9 (2026-09-04, the emitter's DDR state image and SLD/SST schedule): every compute
command now asserts its cache slot is WARM (`ref/gen_layer_script.py:808-810`), and ATTN/KVAP also
assert the KV slot's tag names their kvhead (`ref/gen_layer_script.py:1341-1346`,
`ref/gen_layer_script.py:1248-1256`). isa_bits built a fresh `Mach`, all of whose slots are cold.
The same commit also silently broke section 3's T-reset check (hidden behind the COLD assert): the
S3 `SeqEmitter.on_treset` reads `self.attn` and sweeps all eight attention layers
(`ref/seq_format.py:1524-1530`), so the old two-record spy raised AttributeError once the
ATTN was repaired. (Seen first in the dirty-tree run n1903 — a dev run, not evidence; the evidence is the code cite above.)

## 2. The repair (commit a32f59e, `evidence/qwen9b/g3/isa_bits.py` only)

1. **Warm slots the emitter's way** (`make_mach`, `evidence/qwen9b/g3/isa_bits.py:422-454`). The
   synthetic Mach runs `sched_preamble` (`ref/gen_layer_script.py:1878-1895`; the call, `evidence/qwen9b/g3/isa_bits.py:443`)
   through the REAL `Mach.C` before the capture hook is installed: LAYER, SBASE, Treset, SLD DN 0,
   SLD CV 0, and both halves of attention layer 0's kvhead 0 into KV slot 0. `Mach.sld`
   (`ref/gen_layer_script.py:788-795`) sets the warm bit and the tag; isa_bits never writes
   `M.warm` or `M.tag`. DNST and CONV, which would have hit the same rule next, are warm by the
   same preamble.
2. **Change kvhead the schedule's way** (`_select_kvhead`, `evidence/qwen9b/g3/isa_bits.py:457-482`):
   one step of `sched_attn_layer` (`ref/gen_layer_script.py:1898-1915`) — kvhead k in slot k % 2, the
   slot's previous kvhead stored back by two SSTs, k's two halves loaded by two SLDs, LAYER pointed at
   the slot — with the capture hook lifted for the duration (`evidence/qwen9b/g3/isa_bits.py:470`).
   Called before every ATTN (kvhead 0) and every KVAP (kvhead 3 or 0, so ARG0[1] stays exercised).
3. **T-reset check updated to S3** (`evidence/qwen9b/g3/isa_bits.py:807-843`): for every attention
   layer a, a LAYER write selecting kv_layer a, TCNT = 0, TCNT2 = 0, then the program's LAYER word
   restored — 25 CSRWR, kv_layers 0..7 zeroed (`evidence/qwen9b/sr/n1910_isa_bits_GREEN.log:47`).
   This is stricter than the pre-S3 check, not looser.
4. **Strict negative control.** Every FAIL is recorded with the RTL fields it implicates (`_note`,
   `evidence/qwen9b/g3/isa_bits.py:343-348`; section 3 compares through a `chk` helper that names
   exactly the fields that did not round-trip); an assert that aborts a section is recorded as
   ASSERT; `run` refuses to return a verdict that disagrees with its record
   (`evidence/qwen9b/g3/isa_bits.py:1004-1007`). `_refusal_verdict`
   (`evidence/qwen9b/g3/isa_bits.py:1067-1087`): a perturbation of field F is **REFUSED only when a
   recorded FAIL implicates F**; an assert/exception is `CONTROL FAILURE — unrelated assert`; a
   refusal only by checks on other fields is `CONTROL FAILURE — refused only by checks on other
   fields`; nothing recorded is `ACCEPTED — CONTROL FAILED`. `negative_control`
   (`evidence/qwen9b/g3/isa_bits.py:1090-1134`) first requires the unperturbed run to PASS.
5. **The control of the control:** `--break-control FIELD` makes one perturbation a no-op
   (`BROKEN`, `evidence/qwen9b/g3/isa_bits.py:293`); `--cold-kv` skips the warm path
   (`COLD_KV`, `evidence/qwen9b/g3/isa_bits.py:419`), reproducing the pre-repair state.

## 3. GREEN on the committed tree a32f59e

| run | log | result |
|---|---|---|
| the gate | `evidence/qwen9b/sr/n1910_isa_bits_GREEN.log:46-54` | **PASS rc 0**, 348 command encodings x 29 address sets (the same count as the last PASS, `evidence/qwen9b/s2/019_isa_bits_green.log`, which ran at the 0.8B default) |
| `--negative-control` | `evidence/qwen9b/sr/n1911_isa_bits_negctl_GREEN.log:6-29` | baseline PASS; **19 of 19 refused by their own check**; PASS rc 0 |
| broken: `--break-control kvhead` | `evidence/qwen9b/sr/n1912_isa_bits_negctl_broken_kvhead_FAIL.log:23-29` | kvhead `ACCEPTED — CONTROL FAILED`; 18 of 19; **FAIL rc 1** |
| broken: `--break-control vnw_n` | `evidence/qwen9b/sr/n1913_isa_bits_negctl_broken_vnw_n_FAIL.log:25-29` | vnw_n `ACCEPTED — CONTROL FAILED`; **FAIL rc 1** |
| `--cold-kv` (the gate) | `evidence/qwen9b/sr/n1914_isa_bits_coldkv_FAIL.log:46-49` | the n1900 failure, reproduced: **FAIL rc 1** |
| `--negative-control --cold-kv` | `evidence/qwen9b/sr/n1915_isa_bits_negctl_coldkv_FAIL.log:6-72` | baseline FAIL; every perturbation `CONTROL FAILURE — unrelated assert: … COLD (E_DMA_COLD)`; 0 of 19; **FAIL rc 1** (at HEAD the same state printed PASS, n1901) |
| `--shape` / `--shape-control` / `--dnst-map` | `evidence/qwen9b/sr/n1916_isa_bits_shape.log`, `evidence/qwen9b/sr/n1917_isa_bits_shape_control.log`, `evidence/qwen9b/sr/n1918_isa_bits_dnst_map.log` | PASS rc 0 each — the other modes unmoved |

## 4. Judgment calls and findings

* **Log block.** SR3c already committed `n1980–n1989` inside this task's block (commits 1a1c394,
  8878f0c, 1cccc51). This task used `n1900–n1918` and `n1920–n1921` (spec_cites; n1920 FAIL 1, a quote of the call cited against the callee, kept as the record), and left
  `n1980–n1989` alone.
* **Scope.** The brief names the KV slot; the same preamble warms the DN and CV slots, which DNST and
  CONV needed next. The stale T-reset spy (§1) had to be updated to reach rc 0; the check was made
  stricter.
* **`--cold-kv` skips the whole preamble** (DN/CV included), which is what the tree did before the
  repair. The name follows the failure it reproduces.
* **VNW narrowing is caught only by the ceiling check**, not by the round trip: the `vnw_n` row has
  1 FAIL, `ceiling vnw_n: 12 b < VNW_ISA_MAX = 4096` (`evidence/qwen9b/sr/n1911_isa_bits_negctl_GREEN.log:25`).
  Because 0 encodes the full field, 4096 in a 12-bit field decodes back to 4096, and the other
  cycled counts (4095, 1, ...) fit 12 bits. The ceiling check targets that field, so this counts as
  "its own check". Fix round 1 rewrote the two VNW comments to say so and to point at the ceiling
  row (`evidence/qwen9b/g3/isa_bits.py:628-634`, the row itself `evidence/qwen9b/g3/isa_bits.py:518`),
  so SR11a is not misled into relaxing it.
* **Many first refusals come from section 2 (ceilings) before section 3 runs.** The strict rule
  still requires the whole run to finish with no assert, so section 3 did run on every perturbed
  tree; the per-row count includes its FAILs.
* **`shape_control` keeps the old loose classification** (any exception counts as refused). Its
  baseline (`--shape`) passes, so it is not vacuous today; it was not in this task's scope.
* HEAD moved during the task (SR5a commits b6cf9bb … 2bdab07); none of them touched a file this task edits.

* **9B only.** The last PASS, 019, ran with FABLE5_MODEL unset (the 0.8B default); that
  unset-model run was deliberately NOT repeated here (the plan's 9B-only rule).

## 4b. Fix round 1 (review minors)

* **M1** — the VNW comments now state the round trip is blind to a 12-bit narrowing and name the
  section-2 ceiling row as the only guard (above).
* **M2** — the n1903 dev log is relabelled "dev run, not evidence" (§1); the finding rests on
  `ref/seq_format.py:1524-1530`.
* **M3** — `_select_kvhead`'s SST store branch (`evidence/qwen9b/g3/isa_bits.py:473-477`) never ran
  under KVAP kvheads {3, 0} (different slots). Chosen fix: EXERCISE it — after every i % 4 == 1 KVAP
  a kvhead-1 slot step (`evidence/qwen9b/g3/isa_bits.py:717-723`) evicts kvhead 3 from slot 1, and
  the next KVAP evicts kvhead 1. It emits no captured command, so the encoding count is unchanged:
  348 x 29 and 14 evictions, with a FAIL if the count is ever 0
  (`evidence/qwen9b/sr/n1922_isa_bits_GREEN_fix1.log:50-59`); the control is still PASS 19 of 19
  (`evidence/qwen9b/sr/n1923_isa_bits_negctl_GREEN_fix1.log:10-33`). Both ran on 9ffa974 with
  isa_bits.py committed; the +dirty stamp is SR5b's in-flight files (a tb/scripts generator
  isa_bits does not import, and three untracked sr/ scripts), none an input to this run.
* **M4** — the 9B-only line above.

## 5. Does NOT establish

Anything about the R2 encodings (SR11a). isa_bits reads the ARG layout of `rtl/layer_chan.sv` as it
stands today.
