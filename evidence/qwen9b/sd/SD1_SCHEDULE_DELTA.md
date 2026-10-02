# SD1: the `.txt` vs `.e4` schedule delta, and RD9's 9.9 %

Task SD1 closes the two loose ends the bottleneck census left open
(`evidence/qwen9b/bn/BN_CENSUS.md:1074-1081`, and §10.2 at
`evidence/qwen9b/bn/BN_CENSUS.md:871-885`). The first is **why** the
sequencer stream issues 1,376 fewer `ALU` and 768 more `VN` per token than
the host-driven script, and whether that difference is benign. The second is
whether that difference is the mechanism behind the board's 9.9 % compute-lane
delta (`evidence/qwen9b/g6/RD9_GATE.md:1518`), which the census attributed but
did not prove. This is an investigation only. No code, emitter or schedule
changed, and no simulation or board action was taken.

## 0. How to read every number below

* **E** = produced by a run in this directory. Every E cites the log line
  that printed it. Every log was written on snoke through
  `evidence/qwen9b/run.sh`, whose header records host, tree, command and the
  operating point (`=== rs_f: derived=7 (tag 9b)`) and whose footer records
  `=== rc:`. **D** = derived arithmetic. Every D was also computed on snoke by
  a script in this directory and is cited to the log line that printed it;
  nothing numeric ran on darthplagueis. **T** = transcribed from a log
  already on record elsewhere in the campaign. **S** = stated by a source or
  doc file, cited `path:line`.
* **The scripts** (all read-only; they write stdout only) are listed here.
  * `evidence/qwen9b/sd/sd1_common.py` decodes both streams with the repo's
    own decoders.
  * `evidence/qwen9b/sd/sd1_count.py` produces log 000, the counts and the
    derivation.
  * `evidence/qwen9b/sd/sd1_size.py` produces the sizing (log 003).
    * Log 001 is superseded because its census-table parser also matched
      the per-step rows, which added two junk rows to its table B and put
      that table's TOTAL difference 128 cycles off.
    * Log 002 is superseded by 003, which adds the per-key fit to section E.
    * Nothing else changed between them.
  * `evidence/qwen9b/sd/sd1_board.py` produces log 005, the board
    decomposition, and parses its inputs from the logs rather than retyping
    them.
  * `evidence/qwen9b/sd/sd1_bf_check.py` produces logs 006-009, the
    per-instance equivalence on four seeds. Log 004 is the same check's first
    s1 run, which gave identical results, before the prefix argument and the
    head list were added.
  * Fix round 1 adds these:
    * `evidence/qwen9b/sd/sd1_e1_gen.py` and `evidence/qwen9b/sd/sd1_e1_run.py`
      (committed ef8be9a, before use) produce E1 logs 012 and 013; log 011
      records the binary's provenance.
    * `evidence/qwen9b/sd/sd1_e1_analyze.py` (committed 1be6157, before use)
      produces log 014.
    * `evidence/qwen9b/sd/sd1_fix1_shares.py` produces logs 015 and 016.
      The two are identical. Both are stamped `+dirty`: the only
      uncommitted file at the time was this memo, mid-edit, which the
      script does not read. The memo cites 016.
* **Inputs are the shipped artifacts, and their hashes are checked.**
  * `tb/scripts/w9/model_9b_s1.e4.seq` hashes to the manifest's
    `stream_sha256` (`evidence/qwen9b/sd/000_count_streams.log:17-18`).
  * BN1's per-record chip timeline CSV (untracked for size) hashes to its
    committed `.sha256` (`evidence/qwen9b/sd/003_sizing_fix2.log:14-15`)
    before a row is read.
* **Tree stamps (fix round 1, Minor 7).** Logs 000-009 carry
  `=== tree: 89cccd3`: they ran BEFORE the scripts that produced them were
  committed (a478242, the same scripts byte for byte, apart from the
  prefix argument and head list added to sd1_bf_check.py before 006-009).
  Logs 011-014 (fix round 1) ran after their scripts were committed
  (ef8be9a, 1be6157) and carry those trees.
* **Labels are per NUMBER** (fix round 1, Minor 5): a section heading that
  says "This is D" covers the arithmetic; a number transcribed from an
  older campaign log inside it is marked T where it appears.
* **History is kept visible.** §3 below was written on existing logs and
  one fitted overhead; fix round 1 corrected its wording (§3.3, §3.5) and
  RAN the proposed experiment (§4); §6 gives the measured costs, which
  supersede every fitted or extrapolated figure in §3.
* **Doc version.** The brief names `docs/SEQ_ISA.md` v1.7. The file's header
  is v2.1, and it retains the v1.5 frozen text plus the v1.6/v1.7/v2.x
  addenda (`docs/SEQ_ISA.md:1-3`). The opcode semantics used below are the
  ones in that text.

---

## 1. The mapping: what replaces what, reconciled exactly

### 1.1 One emitter process writes both lists

This is **S**. `w9_9b_model_script` runs `ref/gen_model_script.py` once, and
`SEQ_EMIT` points it at the `.e4` prefix (`tb/Makefile:1410-1417`,
`tb/Makefile:1273-1275`). `gen_layer_script.Mach` writes the `.txt` records.
The opt-in observer `SeqEmitter` sees every command through `on_c`
(`ref/seq_format.py:1564-1582`) and writes the `.seq` records.

So the two lists are not two emitters that drifted. They are **one command
schedule plus four deliberate rewrites inside `SeqEmitter`**, each needed so
the sequencer can run with no host in the loop:

| # | the `.txt` command(s) | what the `.e4` issues instead | emitter code (S) |
|---|---|---|---|
| (a) | one ALU `SHIFT32`/`SHIFT32W` per ≤2048-row chunk of a matvec's host-relayed y32 (the `W32` record plus its dequant) | **no layer command**: MVGO ×4 (no-wait) + FENCE + MOVY ×4, with the MOVY doing the shift and the store | `ref/gen_layer_script.py:665-679` mutes the `W32`; fused path `ref/seq_format.py:2134-2161` (sub 1/9 → MOVY); `ref/seq_format.py:2072` |
| (b) | `SILU32` over the MLP gate in 2048-row chunks, 6 per layer | the same op re-chunked per channel: split_rows over 12,288 rows and 4 channels, times res_chunks of at most 2048 rows: 8 per layer | `ref/seq_format.py:2152-2161`, `ref/seq_format.py:1154-1177` |
| (c) | per DeltaNet head: `SHIFT32` by host-computed `k_h`, then `SCALE` by host-computed `m_q15` | `DYNQ16` (ALU sub 12, k to XRF[1]), then **VN mode 2 + ARG2[0] EPS-NORM** (k read from XRF[1]) | hint `ref/gen_layer_script.py:2036-2040`; rewrite `ref/seq_format.py:2210-2242` (DYNQ16 at `ref/seq_format.py:2223`, VN at `ref/seq_format.py:2235`) |
| (d) | per GQA layer: 16 `EMUL32` (one per head, `k_a` as a literal) | one `EMUL32` **probe** (k_a to XRF[2]) + one **real** `EMUL32`, each over all 16 × 256 elements | `ref/gen_layer_script.py:2146-2149`; `ref/seq_format.py:1661-1821` (probe/real at `ref/seq_format.py:1809-1818`) |

The profile that selects (c)'s VN form is `epsnorm`
(`ref/seq_format.py:1291-1303`), and the stream records profile epsnorm
and dyn_ka True (`evidence/qwen9b/sd/000_count_streams.log:20`).

### 1.2 The counts, recounted per token

These are **E**. Every `.txt` forward step carries the identical multiset of
9,429 commands, and every one of the `.e4`'s four written-out bodies carries
the identical 8,821. The fourth body is the TCNT_SEQ=3 loop body, so all six
tokens run that list (`evidence/qwen9b/sd/000_count_streams.log:24-38`).
Per token (`evidence/qwen9b/sd/000_count_streams.log:42-54`):

| | `.txt` | `.e4` | delta |
|---|---|---|---|
| `ALU` | 6,219 | 4,843 | **−1,376** |
| `VN` | 1,761 | 2,529 | **+768** |
| DNST / ROPE / ATTN / SLD / SST / VNW / KVAP / GATE / CONV / ROPET | 768 / 160 / 128 / 112 / 112 / 81 / 32 / 24 / 24 / 8 | identical | 0 |
| total | 9,429 | 8,821 | −608 |

The census's two rows are confirmed, and so is "everything else identical".
All 112 `SLD` and 112 `SST` per token are present on both sides. The census
log's 7 `SLD` and 217 "(none)" rows are CMD records labelled by the
*in-flight* layer op (`tb/seq_timeline.svh:347`), not a different count.

### 1.3 Derived from the geometry and the emitter rules, key by key

The derivation is **D** (`evidence/qwen9b/sd/000_count_streams.log:73-96`).
The geometry comes from `ref/layer_ref.py` (H 4096, FFN 12288, 24 DeltaNet +
8 GQA layers, LNH 32, NQ 16, NKV 4, HD 256; see
`evidence/qwen9b/sd/000_count_streams.log:19`). The `.txt` chunks at
CHUNK = 2048 (`ref/gen_layer_script.py:92`,
`ref/gen_layer_script.py:1756-1767`) and the `.e4` at CHUNK_ROWS = 2048 over
nch = 4 (`ref/seq_format.py:1211`).

| term | per layer | per token |
|---|---|---|
| (a) fused dequants removed, DeltaNet layer: in_qkv 4 + in_z 2 + in_b 1 + in_a 1 + out 2 + mlp.up (SHIFT32W) 6 + mlp.down 2 = **18** | −18 | |
| (a) fused dequants removed, GQA layer: q 4 + k 1 + v 1 + o 2 + up 6 + down 2 = **16** | −16 | −(24×18 + 8×16) = **−560** ALU |
| (b) SILU32 re-chunk, 6 → 8 per layer, 32 layers | +2 | **+64** ALU |
| (c) DN block-float: SHIFT32 → DYNQ16 (0), SCALE → VN EPS-NORM (−1 ALU, +1 VN), 24 × 32 heads | | **−768** ALU, **+768** VN |
| (d) attention: 16 EMUL32 → probe + real, 8 layers | −14 | **−112** ALU |
| (e) LM-head AMAX32: 122 chunks on both sides | 0 | 0 |
| **sum** | | **ALU −1,376, VN +768, total −608** |

It reconciles **EXACTLY**, including at the level of each
(sub-op, element count) key. The 13 keys whose counts differ match derived
against counted, all OK (`evidence/qwen9b/sd/000_count_streams.log:57-69`,
`evidence/qwen9b/sd/000_count_streams.log:83-96`). **768 = 24 × 32 is
confirmed**: it is the DeltaNet value-head count times the DN layers, and it
comes from rewrite (c) alone. The log states the sum as −560 + 64 − 768 − 112 + 0 = −1,376 (`evidence/qwen9b/sd/000_count_streams.log:80`).

### 1.4 One concrete example of each, by record number

The records are **E**.

* **(c)**
  * The `.txt` has DN head 0 of the first DN layer, step 1, at lines 58,138
    (`SHIFT32` × 128, p0 = k_h) and 58,139 (`SCALE` × 128, p0 = m_q15)
    (`evidence/qwen9b/sd/000_count_streams.log:100-101`).
  * In the `.e4`, records 158-161 are the `DYNQ16` × 128 and records 162-165
    are the `VN` EPS-NORM × 128, with ARG2 = 3, i.e. EPS on and k from XRF[1]
    (`evidence/qwen9b/sd/000_count_streams.log:103-112`).
* **(a)**
  * The `.txt` line 20,498 is `SHIFT32` × 2048, the in_qkv matvec's first
    chunk, landing at 0x5420.
  * In the `.e4`, records 62-74 are MOVX ×4, MVGO ×4 (no-wait), FENCE, and
    MOVY ×4 into 0x5420 / 0x5c20 / 0x6420 / 0x6c20, with the shift
    `>> 11 − XRF[0]`. There is **no ALU command**
    (`evidence/qwen9b/sd/000_count_streams.log:114-128`).
* **(d)**
  * The `.txt` line 617,631 is the first attention `EMUL32` × 256, with
    k_a = 8 as a literal.
  * In the `.e4`, records 4715-4718 are the probe (ARG2 p0 = 0x40) and
    records 4719-4722 are the real pass (ARG2 + XRF[2]), each × 4096
    (`evidence/qwen9b/sd/000_count_streams.log:130-141`).
* **(b)**
  * In the `.e4`, records 1363-1366 are the first `SILU32` × 1024 chunk
    (`evidence/qwen9b/sd/000_count_streams.log:143-147`).

---

## 2. Is the difference benign?

### 2.1 What `ref/seq_model --gate` proves, and where it looks

This is **S** and **T**. The gate replays the `.txt` against a fresh model
and executes the `.seq` against another. It then requires four things
(`ref/seq_model.py:1384-1447`):

1. every `.txt` R record, sampled in the `.seq` replay at the same point, is
   bit-exact;
2. the final scratch is bit-exact outside the declared y32 staging windows;
3. the banked state and the DDR state region are bit-exact;
4. the token lists are identical.

On `model_9b_s1` it passed: 2,358/2,358 checkpoints ALL BIT-EXACT, scratch
CLEAN, state BIT-EXACT, tokens IDENTICAL. The `.txt` side ran 56,576
commands and the `.seq` side 52,928 (`evidence/qwen9b/s4/021_seqgate_model_s1.log:20-26`).
Seeds s2-s4 also passed, with 2,358/2,358 checkpoints bit-exact
(`evidence/qwen9b/g6/024_seqmodel_gate_s1to4.log:37`,
`evidence/qwen9b/g6/024_seqmodel_gate_s1to4.log:52`,
`evidence/qwen9b/g6/024_seqmodel_gate_s1to4.log:67`).

**What the gate does not look at.** Its checkpoints are wherever the
generator put an R record. For rewrite (c) that is the gated-norm output
region, which gets R(ON, 256) once per DN layer
(`ref/gen_layer_script.py:2044`). That covers **2 of 32 heads per DN layer
per step** (`evidence/qwen9b/sd/006_bf_check_s1.log:21`), plus the full
residual R(X0) at each layer's end. So the gate is a model-level proof on
these inputs. It is not a per-command proof.

### 2.2 The four rewrites, one at a time

| rewrite | semantics, from the source | on every instance of the four committed seeds | verdict |
|---|---|---|---|
| (a) fused dequant | SHIFT32 is clip16(rshr64s(pair, p0)) and SHIFT32W the clip32 form (`rtl/vec_alu.sv:15`, `rtl/vec_alu.sv:23`). MOVY is rshr64s + round-half-away, then clip16 in int16 mode or clip32 in pairs mode (`rtl/seq_movers.sv:467-479`, `docs/SEQ_ISA.md:375-384`). The MOVY immediate is p0 + e_x read as "minus XRF[0]", and XRF[0] = e_x (`ref/seq_format.py:2034-2046`). | covered by the gate only (2.1) | **ESTABLISHED by construction**: same formula, same shift, same elements |
| (b) SILU32 re-chunk | an elementwise op over the same element set, with only the chunk boundaries moved (`ref/seq_format.py:2152-2161`) | covered by the gate | **ESTABLISHED by construction** |
| (c1) SHIFT32(k_h) → DYNQ16 | DYNQ16 is bf_shift(max\|x\|, guard 0) then clip16(rshr64s) (`ref/layer_fixed.py:552-579`), and the host's k_h is the same bf_shift with BF_GUARD = 0 (`ref/layer_fixed.py:405`) | **4,608 of 4,608 heads per seed: same k, all 128 outputs equal** (E: `evidence/qwen9b/sd/006_bf_check_s1.log:16`, `evidence/qwen9b/sd/007_bf_check_s2.log:16`, `evidence/qwen9b/sd/008_bf_check_s3.log:16`, `evidence/qwen9b/sd/009_bf_check_s4.log:16`) | **ESTABLISHED**: identical by construction and on every instance |
| (c2) SCALE(m_q15) → VN EPS-NORM | **A different function.** The `.txt` immediate is float64 1/sqrt of the exact int32 sum of squares (`ref/layer_fixed.py:509-549`, `ref/layer_fixed.py:537`). EPS-NORM is an integer ROM-seeded rsqrt of the sum of squares of the **int16, post-shift** vector plus a shifted eps (`ref/layer_fixed.py:694-767`, `ref/layer_fixed.py:752`). The generators ship the float path (`ref/layer_fixed.py:413-423`, `ref/layer_fixed.py:1305`). | **NOT identical on every instance.** The outputs differ, by at most 1 LSB, on **2 / 5 / 1 / 4** of 4,608 heads for s1 / s2 / s3 / s4, and the integer scale differs from m_q15 by at most 1 (E: `evidence/qwen9b/sd/006_bf_check_s1.log:17-18`, `evidence/qwen9b/sd/007_bf_check_s2.log:17-18`, `evidence/qwen9b/sd/008_bf_check_s3.log:17-18`, `evidence/qwen9b/sd/009_bf_check_s4.log:17-18`). None of the differing heads is head 0 or 1, so the gate never compared one directly. That each was absorbed before the layer's R(X0) is an **inference (T+D)**, not an observation: the gate's R(X0, H) checkpoints (`ref/gen_layer_script.py:2052`, `ref/gen_layer_script.py:2162`) were all bit-exact (`evidence/qwen9b/s4/021_seqgate_model_s1.log:22`) in a gate that compares two REFERENCE-MODEL replays (ref vs ref, not RTL), and this check replays only the `.txt` side, so no differing head was ever followed forward on the `.e4` side. | **Command-level: REFUTED** as identical. **Model-level on these 4 seeds: ESTABLISHED.** **In general: NOT ESTABLISHED** |
| (d) attention probe + real | the probe latches attn_o_shift(max\|pair(a)·b\|) over all heads, which is the host's k_a definition; the real pass is the same op 8 with that shift (`rtl/vec_alu.sv:50-53`, `ref/seq_format.py:1661-1707`) | **48 of 48 blocks per seed: the host k_a equals the probe k_a** (E: `evidence/qwen9b/sd/006_bf_check_s1.log:19`, `evidence/qwen9b/sd/007_bf_check_s2.log:19`, `evidence/qwen9b/sd/008_bf_check_s3.log:19`, `evidence/qwen9b/sd/009_bf_check_s4.log:19`) | **ESTABLISHED** |

**Two existing claims are wrong at the command level.**

1. The ISA doc says EPS-NORM was "proven 0-LSB-identical to the host float
   scale path on the equivalence soak" (`docs/SEQ_ISA.md:130-135`).
2. `ref/seq_model.py --selftest` reports "200/200 blocks bit-identical"
   (`evidence/qwen9b/s3/069_seq_model_selftest_committed.log:14`). That
   selftest draws uniform random int32 blocks (`ref/seq_model.py:1464-1491`).

`ref/layer_fixed.py`'s own 9B soak draws Gaussian head outputs, and it
reports "192/200 heads bit-identical, max |delta| 2 LSB" at the gated-norm
output (`evidence/qwen9b/g2/ref_selftests_g2c.log:526-527`). It asserts only
|delta| ≤ 4 (`ref/layer_fixed.py:1873`). The artifact-level check above
agrees with the soak, not with the ISA sentence. No doc was edited here.

**The verdict on "benign".** The two lists compute the **same model
outputs on the four committed seeds**. Every checkpoint is bit-exact, every
per-layer residual is bit-exact, and the tokens are identical. Rewrites (a),
(b), (c1) and (d) are identical by construction, and (c1) and (d) were also
checked on every instance. Rewrite (c2) is **not**. It is a deliberately different, integer
implementation of the DeltaNet gated-norm scale, and it disagrees by 1 LSB on
1 to 5 of the 4,608 head evaluations per committed seed, so far always
absorbed downstream (T+D inference from the gate's bit-exact R(X0)
checkpoints, as above). Whether that holds at other prompts, at long context,
or in perplexity is **NOT ESTABLISHED** (§5). For performance work the
consequence is simple: **the `.e4` is the schedule the silicon runs, and it
is the only one whose per-command costs matter**.

---

## 3. Sizing the 9.9 % from existing logs

### 3.1 The accounting identity, and the census's "opposite-sign term" found

This is **D**, from `evidence/qwen9b/sd/003_sizing_fix2.log:56-73`.

**The `.e4` side.** BN1's timeline gives every `.e4` CMD record its own
lane cycles. A CMD's window lasts until the layer command's busy clears
(`docs/SEQ_ISA.md:85`). The lane found *outside* CMD rows is 0.0 cycles, so
the per-command attribution is exact
(`evidence/qwen9b/sd/003_sizing_fix2.log:19`).

**The comparison per opcode.** Against the layer census of the same netlist
(`evidence/qwen9b/s4/census_t14a.txt:9-21`, draining, holds not in LCYC),
**every opcode except `ALU`, `VN` and `SLD` agrees to the cycle** (DNST,
CONV, VNW, ATTN, ROPE, KVAP, GATE, ROPET). The whole gap to the draining
census is −1,016,928 cycles = −4.068 ms, and it breaks down as:

* ALU −1,374,040
* VN +236,544
* SLD +120,568
* nothing else (0.0)

(`evidence/qwen9b/sd/003_sizing_fix2.log:69-70`.)

**That +120,568 is the opposite-sign term the census could not find.** It
is the F2 queue-full hold. The `.e4` lane charges it on its `SLD` records.
The 45.674 (**T**) comparand the census used has it **subtracted**, and is also
pre-14A (`evidence/qwen9b/bn/BN_CENSUS.md:879`). That is why ALU+VN
(−4.550 ms) "over-explained" a 4.064 ms gap
(`evidence/qwen9b/sd/003_sizing_fix2.log:73`).

**Against the like-for-like comparand.** That comparand is the census plus
the non-draining hold of 120,953, which gives 46.161 ms (**T**), RD9's own figure
(`evidence/qwen9b/g6/RD9_GATE.md:1604`). Against it the gap is
−1,137,881 cycles. **ALU+VN = −1,137,496 = 99.97 % of it.** The −385-cycle
remainder is exactly the hold difference
(`evidence/qwen9b/sd/003_sizing_fix2.log:71-72`).

### 3.2 The board's 9.9 %, decomposed — and what the zero residual is

This is **D**, from `evidence/qwen9b/sd/005_board_decomposition.log:13-20`.
The board's L_LCYC is 41.588 ms/token (**T**,
`evidence/qwen9b/g6/020_perf_census_two_lanes.log:28`) and the like-for-like
comparand is 46.161 ms/token (**T**, `evidence/qwen9b/g6/RD9_GATE.md:1604`).
Board − comparand is −4.573 ms = **−9.907 %** (**D**,
`evidence/qwen9b/sd/005_board_decomposition.log:16`). Its parts:

| part | cycles/token | share of the gap |
|---|---|---|
| ALU + VN rows (chip `.e4` − census `.txt`) | −1,137,496 (**D**) | 99.496 % (−9.857 pp) |
| hold difference (`.e4` SLD hold − census F2 hold) | −385 (**D**) | 0.034 % |
| board vs chip TB on the same `.e4` stream | −5,382.63 (**D**) | 0.471 % |
| residual | 0.00 | — |

**The 0.00 residual is an algebraic identity, not a finding** (fix round 1,
Important 2). The three parts are board − chip, chip − comparand restricted
to ALU+VN, and the rest of chip − comparand. They sum to board − comparand
by construction (`evidence/qwen9b/sd/sd1_board.py:43-50`).

**The finding in this table is the per-opcode agreement behind it** (§3.1):
* every opcode except ALU, VN and SLD agrees to the cycle between the chip
  `.e4` lane and census_t14a (`evidence/qwen9b/sd/003_sizing_fix2.log:56-68`);
* SLD matches S4's F2 hold to −385 cycles (`evidence/qwen9b/sd/003_sizing_fix2.log:72`).

So, on the existing logs, **the whole 9.9 % lies in the ALU and VN rows**.
Whether it is the list or a per-command cost difference is the next
question.

### 3.3 Is the ALU+VN row difference the list, or a per-command cost difference between instruments?

As first written, on existing logs only; fix round 1 corrected the wording.
§6 supersedes this section with measured costs.

* **VN: proven on existing logs.** This is **D**, from
  `evidence/qwen9b/sd/003_sizing_fix2.log:76-81`.
  * The `.txt`'s 1,761 VN commands fall into four keys: l2norm × 128,
    rmsnorm × 256, rmsnorm × 4096 and mode-1 × 4096.
  * Costed at the `.e4`'s measured per-key chip costs (304, 563, 8,243 and
    8,243 cycles, each min = max), they predict 1,092,819.0 cycles/token.
  * The census measured 1,092,819.0 (**T**,
    `evidence/qwen9b/s4/census_t14a.txt:9`), a difference of +0.0.
  * These are two independent measurements, so this is not circular. The
    VN row difference is exactly the 768 EPS-NORMs at 308 cycles
    (`evidence/qwen9b/sd/003_sizing_fix2.log:33`).
* **ALU: CONSISTENT WITH instrument-independent costs.** This was round 0's
  "EXACT"; the review showed it to be **circular** (fix round 1,
  Important 1). This is **D**, from
  `evidence/qwen9b/sd/003_sizing_fix2.log:84-112`.
  * The ALU keys common to both lists, at `.e4` chip costs, account for
    4,055,838.5 of the census's 5,661,438.5.
  * The six `.txt`-only keys carry the remaining 1,605,600, over 1,456
    commands with Σ II·n = 1,590,784 (II from `rtl/vec_alu.sv:83-86`).
  * That implies about 10.18 cycles of fixed overhead per command
    (`evidence/qwen9b/sd/003_sizing_fix2.log:91`). This is inside the 5-19
    the `.e4` measures directly for its single-pass ALU keys
    (`evidence/qwen9b/sd/003_sizing_fix2.log:92-108`).
  * Round 0 then "fitted" the overheads per key:
    * SHIFT32 +10, from the census ALU minimum of 42 at n = 32;
    * EMUL32 +12, borrowed from the `.e4`'s EMUL32 at n = 2048 and 4096;
    * SHIFT32W +10, **solved from the census ALU total**
      (`evidence/qwen9b/sd/sd1_size.py:240`,
      `evidence/qwen9b/sd/sd1_size.py:244`).
  * The "predicted 5,661,438.5 vs measured 5,661,438.5, EXACT"
    (`evidence/qwen9b/sd/003_sizing_fix2.log:112`) is therefore equal to
    that total **by construction**. It is not evidence.
  * **Three extrapolations**, all of which E1 replaces with measurements
    (Minor 3):
    1. SHIFT32's +10 was taken at n = 32 and applied to 1,088 commands at
       n = 128 / 1024 / 2048;
    2. EMUL32 × 256's +12 was borrowed from other sizes;
    3. SHIFT32W's +10 was solved.
  * The fitted terms were small against the gap:
    * the solved SHIFT32W term is 192 × 10 = 1,920 cycles = 0.00768 ms =
      **0.168 %** of |board − comparand|;
    * the whole inferred `.txt`-only fixed overhead is 14,816 cycles =
      0.05926 ms = **1.296 %**
      (`evidence/qwen9b/sd/016_fix1_shares_clean.log:14-15`).
* **What existing logs supported.** The whole 9.9 % lies in the ALU+VN
  rows. That this is the list rather than a per-command cost difference was
  **proven for VN** and **consistent-with for ALU**. §6 upgrades ALU to
  measured.

### 3.4 Per rewrite: where the 4.550 ms comes from

These are **D** and were fitted in round 0
(`evidence/qwen9b/sd/003_sizing_fix2.log:121-126`). They are **re-derived
on E1's measured costs with the identical result**
(`evidence/qwen9b/sd/016_fix1_shares_clean.log:16-20`). + means the `.e4`
costs more.

| rewrite | cycles/token | ms/token |
|---|---|---|
| (a) 560 fused dequants removed, MOVY does the shift | **−1,432,544** | **−5.7302** |
| (b) SILU32 re-chunked (192 → 256 commands) | +1,216 | +0.0049 |
| (c) DN block-float: `.e4` DYNQ16 + EPS-NORM vs `.txt` SHIFT32 + SCALE | **+229,632** | **+0.9185** |
| (d) attention: `.e4` probe + real vs `.txt` 16 × EMUL32 × 256 | **+64,200** | **+0.2568** |
| **sum** | **−1,137,496** | |

**There are opposite-sign terms inside the schedule difference too.**
* The `.e4`'s block-float pair costs more: DYNQ16 at 269 cycles is a
  two-pass op, and EPS-NORM costs 308. The `.txt` pair is SHIFT32 × 128 at
  138 plus SCALE × 128 at 140 (**E**, measured,
  `evidence/qwen9b/sd/014_e1_analysis.log:29` for SHIFT32 and
  `evidence/qwen9b/sd/014_e1_analysis.log:26` for SCALE, and see §6).
* The attention double pass runs 2 × 4096 elements at II 2 against
  16 × 256.
* So (b), (c) and (d) are all positive. The saving is **entirely** rewrite
  (a).

**The census's 76 % estimate was biased low** because it priced the removed
commands at the mean ALU cost of 910 cycles (**T**,
`evidence/qwen9b/bn/BN_CENSUS.md:878`;
`evidence/qwen9b/sd/003_sizing_fix2.log:127`). The removed commands are
mostly 2048- and 4096-element dequants.

### 3.5 What existing logs settled, and what they did not (as corrected in fix round 1)

* **Settled on existing evidence:**
  * the exact count reconciliation (§1);
  * the opposite-sign term (the SLD hold, charged on one side and
    subtracted on the other);
  * the per-opcode agreement: only ALU, VN and SLD differ;
  * VN per-command costs identical across instruments.
* **Not settled on existing evidence:**
  * the `.txt`-only ALU per-command costs, which were inferred, one of them
    solved from the very total it was then said to predict;
  * the decomposition's "residual 0.00", which is an identity.
* E1 (§6) measures the costs and defines a residual that can be non-zero.

---

## 4. The decisive experiment — proposed in round 0, RUN in fix round 1

In round 0 this section proposed E1 and stopped. The user then said GO:
"Run the proposed follow up. lets get some measured data."

The proposal as it stood:
* a per-key cost probe on the existing Task 14-A draining census binary
  `tb/obj_dir_tb_layer_census_t14a_lat8`;
* one tiny `.txt` script per key, whose census row is that key's cost;
* the `.txt`-only keys, the `.e4`-only keys and controls, at 4 seeds;
* no change to RTL, the TB, the emitter or any schedule;
* an estimated ~10 minutes of snoke wall time.

As run:
* **all 27** ALU and VN keys of both lists were covered, not 12;
* 4 seeds × 4 instances per key;
* 108/108 runs PASS;
* the whole run, including the 108 census replays, took **19 seconds** of snoke wall time (`evidence/qwen9b/sd/013_e1_run.log:2`, 04:51:49, to `evidence/qwen9b/sd/013_e1_run.log:126`, 04:52:08).

The alternatives remain as costed in round 0:
* an `xlat` / `dyn_ka=0` re-emission plus chip replay costs a two-emission
  build (the GPTQ pass alone is 2 h 55 min, `tb/Makefile:1406-1408`) and a
  2 h 25 min replay (`evidence/qwen9b/g5/G5C_RTL.md:680-682`), and it still
  cannot isolate (a);
* the `.txt` cannot drive the chip TB.

Results: §6.

---

## 5. What this memo does NOT establish

1. **That EPS-NORM ≡ SCALE in general.**
   * At the command level it is not: it differs by 1 LSB on 1-5 heads per
     4,608 on the committed seeds, measured at the **SCALE / EPS-NORM
     output** (§2.2).
   * The synthetic soak's "max 2 LSB" (`evidence/qwen9b/g2/ref_selftests_g2c.log:527`)
     is measured at a **different point**, after the norm_w op-3 multiply
     (Minor 6). Its SCALE-output figure is "worst out delta 1 LSB"
     (`evidence/qwen9b/g2/ref_selftests_g2c.log:526`).
   * Its effect on perplexity, long context, or any prompt beyond the four
     committed seeds is not measured. `ref/fidelity_check.py`'s `seqnorm`
     mode would size it.
2. **The DYNQ8 cost on real data, per command.** DYNQ8 is the only key whose
   cost depends on the data (§6). E1 used synthetic data, and its DYNQ8
   means differ from the chip's real-data means by +2.78 and −0.23 cycles
   (`evidence/qwen9b/sd/014_e1_analysis.log:19-20`). DYNQ8 has equal counts
   in both lists, so this cancels in every difference.
3. **Anything about the board beyond L_LCYC.** The board figure is RD9's.
   Nothing here touched the board, and the board-vs-chip term is taken from
   existing logs.
4. **Whether the `.e4`'s costlier rewrites (c) and (d), +0.9185 and
   +0.2568 ms/token, could be cheapened.** That is a design question for the
   tokens-per-second direction.
5. **One seed on the model-cost side.** The chip timeline and the
   model-scale census are `model_9b_s1`. The equivalence side (§2.2) and E1
   (§6) ran four seeds.

---

## 6. E1: measured per-key costs (fix round 1)

### 6.1 The instrument, tied to a committed tree

This is **E**, from `evidence/qwen9b/sd/011_e1_binary_provenance.log`.
* **The binary.** It is
  `tb/obj_dir_tb_layer_census_t14a_lat8/tb_layer_census_t14a_lat8`, with
  sha256 b347604a…bbebd (`evidence/qwen9b/sd/011_e1_binary_provenance.log:14`),
  built 2026-09-07 00:05:26.
* **The build.** `evidence/qwen9b/g5/080_t14a_census.log` built it at tree
  1dd2889, which is clean, not +dirty (**T**,
  `evidence/qwen9b/g5/080_t14a_census.log:3`). That commit is the last
  `rtl/` commit, 2026-09-07 00:04:00
  (`evidence/qwen9b/sd/011_e1_binary_provenance.log:34-38`).
* **Nothing it was built from has changed.** All 15 sources in the binary's
  own Verilator file list (the 13 `rtl/` files, `tb/seq_mem_file.sv` and
  `evidence/qwen9b/g4/tb_layer_census.sv`) show an **empty diff** from
  1dd2889 to HEAD (`evidence/qwen9b/sd/011_e1_binary_provenance.log:36-37`).
* **It is the census_t14a instrument.** The same binary measured
  `evidence/qwen9b/s4/census_t14a.txt`, the source of the 46.161 comparand
  (**T**: `evidence/qwen9b/g5/081_t14a_census.log:12-15` re-entered the build without recompiling, and `evidence/qwen9b/g5/081_t14a_census.log:16` and `evidence/qwen9b/g5/081_t14a_census.log:61` ran it and wrote that table).
* **Nothing was rebuilt; no obj_dir was written.** It ran on snoke only.

### 6.2 The probe

* **The scripts.** `evidence/qwen9b/sd/sd1_e1_gen.py` (committed ef8be9a,
  before use) writes one script per (seed, key): 27 keys (22 ALU + 5 VN,
  every key of both lists) × 4 seeds.
  * Each script holds 4 instances of one key, on data seeded
    `default_rng(seed·1000 + key)`.
  * The scripts are produced by `Mach` itself, so every command is followed
    by an R/E/A bit-exact check. DYNQ16, EPS-NORM and the op-8 probe are
    raw C records, modelled with `ref/layer_fixed.py`'s specs.
  * The 108 scripts were written to snoke's local `/tmp/sd1_e1` and are not
    committed. Their sha256 are listed in
    `evidence/qwen9b/sd/012_e1_generate.log:13-120`, and they regenerate
    deterministically.
* **The runner.** `evidence/qwen9b/sd/sd1_e1_run.py` runs the binary as
  `evidence/qwen9b/s4/run_s4_census.sh` does: cwd `tb/`, draining,
  +state=scripts/w9/model_9b_s1. It reads the census's own per-opcode row.
* **The result: 108/108 PASS, with a row**
  (`evidence/qwen9b/sd/013_e1_run.log:14-15`,
  `evidence/qwen9b/sd/013_e1_run.log:124`). So every probe was also
  bit-exact against the model, including the first RTL execution of
  EPS-NORM and DYNQ16 in this instrument.

### 6.3 The measured table

These are **E**, cycles of busy_cmp per command
(`evidence/qwen9b/sd/014_e1_analysis.log:13-41`). "chip" is the `.e4`
timeline's real-data mean (**D**, `evidence/qwen9b/sd/003_sizing_fix2.log:21-50`).

| key | s1 | s2 | s3 | s4 | mean | spread (min–max) | chip | E1 − chip |
|---|---|---|---|---|---|---|---|---|
| **SHIFT32 × 2048** (`.txt`-only) | 2058 | 2058 | 2058 | 2058 | **2058** | 0 | — | — |
| **SHIFT32 × 1024** (`.txt`-only) | 1034 | 1034 | 1034 | 1034 | **1034** | 0 | — | — |
| **SHIFT32 × 128** (`.txt`-only) | 138 | 138 | 138 | 138 | **138** | 0 | — | — |
| **SHIFT32 × 32** (`.txt`-only) | 42 | 42 | 42 | 42 | **42** | 0 | — | — |
| **SHIFT32W × 2048** (`.txt`-only) | 4106 | 4106 | 4106 | 4106 | **4106** | 0 | — | — |
| **EMUL32 × 256** (`.txt`-only) | 524 | 524 | 524 | 524 | **524** | 0 | — | — |
| DYNQ16 × 128 (`.e4`-only) | 269 | 269 | 269 | 269 | 269 | 0 | 269.0 | +0.00 |
| EMUL32 × 4096 probe (`.e4`-only) | 8205 | 8205 | 8205 | 8205 | 8205 | 0 | 8205.0 | +0.00 |
| EMUL32 × 4096 (`.e4`-only) | 8204 | 8204 | 8204 | 8204 | 8204 | 0 | 8204.0 | +0.00 |
| SILU32 × 1024 (`.e4`-only) | 1043 | 1043 | 1043 | 1043 | 1043 | 0 | 1043.0 | +0.00 |
| VN EPS-NORM × 128 (`.e4`-only) | 308 | 308 | 308 | 308 | 308 | 0 | 308.0 | +0.00 |
| DYNQ8 × 12288 (common) | 24595.25 | 24594.00 | 24595.25 | 24593.00 | 24594.38 | 24590–24598 | 24591.6 | +2.78 |
| DYNQ8 × 4096 (common) | 8210.75 | 8209.75 | 8210.50 | 8210.50 | 8210.38 | 8207–8213 | 8210.6 | −0.23 |
| the other 14 common keys (ADD, AMAX32 × 2, EMUL, EMUL32 × 2048, SCALE × 2, SIGM16, SILU16, SILU32 × 2048, VN l2norm, VN rmsnorm0 × 2, VN rmsnorm1) | — | — | — | — | = chip | 0 | | **+0.00 each** |

* **The three extrapolations, measured.** The round-0 fit was right on
  every one:
  * SHIFT32 = n + 10 at all four sizes;
  * SHIFT32W = 2n + 10;
  * EMUL32 × 256 = 2n + 12 = 524.
* **Deterministic.** Every key except DYNQ8 has zero spread across 16
  samples. DYNQ8's cost depends on the data (its exponent search), so it
  varies by a few cycles.
* **One cost table.** Every key present on both instruments costs the same
  on both to the cycle, except DYNQ8.

### 6.4 The ALU row and the 9.9 %, on measured costs only — no fitted parameter anywhere

This is **D**, from `evidence/qwen9b/sd/014_e1_analysis.log:43-72`.

**Each list at E1 costs, against the instrument that ran it:**

| row | list | at E1 costs | measured | residual |
|---|---|---|---|---|
| ALU | `.txt` (census) | 5,661,508.38 | 5,661,438.50 (**T**) | **−69.88** |
| ALU | `.e4` (chip) | 4,287,468.38 | 4,287,398.50 | **−69.88** |
| VN | `.txt` (census) | 1,092,819.00 | 1,092,819.00 (**T**) | +0.00 |
| VN | `.e4` (chip) | 1,329,363.00 | 1,329,363.00 | +0.00 |

* **The ALU residuals are real, non-zero, and identical on both sides.**
  They come only from the two data-dependent DYNQ8 keys, the only keys
  where E1 ≠ chip (`evidence/qwen9b/sd/014_e1_analysis.log:19-20`).
* DYNQ8 has equal counts in both lists (DYNQ8 is absent from the keys whose counts differ,
  `evidence/qwen9b/sd/000_count_streams.log:55-70`; the `.e4` counts, 97 and 32 per token, are at
  `evidence/qwen9b/sd/003_sizing_fix2.log:24` and `evidence/qwen9b/sd/003_sizing_fix2.log:26`),
  so the residual cancels in the difference.

**The list difference priced at E1 costs.** Σ over the 13 differing keys
of Δcount × E1 cost is **−1,137,496.00 cycles = −4.5500 ms**
(`evidence/qwen9b/sd/014_e1_analysis.log:48-63`). The measured ALU+VN row
difference, chip `.e4` minus census `.txt`, is also −1,137,496.00.
**Measured − Σ = +0.00** (`evidence/qwen9b/sd/014_e1_analysis.log:64`).

This zero is **not** constructed:
* Σ uses only E1's measured per-key costs and the recounted lists;
* the row difference comes from two other measurements, the chip timeline
  and census_t14a.

**The 9.9 %.** The residual is defined so it can be non-zero:
residual = (board − comparand) − Σ − SLD-hold term.

| term | cycles/token | share of board − comparand (−1,143,263.63 = −9.907 %) |
|---|---|---|
| Σ, the E1-priced command-list difference | −1,137,496.00 | **99.496 %** |
| SLD-hold term (`.e4` SLD 120,568 − census F2 120,953) | −385.00 | 0.034 % |
| **RESIDUAL (D: a difference of measurements)** | **−5,382.63 = −0.0215 ms** | **0.471 %** |

(`evidence/qwen9b/sd/014_e1_analysis.log:67-72`.)

**All of the residual is board − chip lane** (−5,382.63). Its value is
exactly board − chip lane from existing logs (the board counter and BN1's
chip timeline) and carries **no E1 information**; E1 enters only through Σ.
It is the testbench-vs-silicon difference BN §10.2 already carried, stated
two ways (**D**, both computed in
`evidence/qwen9b/sd/018_fix2_board_chip_pct.log:16-17`):
5,382.63 / 10,402,465.30 cycles = **0.0517 %** of the chip lane, and BN's
(41.610 − 41.588) / 41.588 = **0.0529 %** from rounded ms, which BN prints
as 0.053 % (`evidence/qwen9b/bn/BN_CENSUS.md:830`). The chip-side
residual (lane − comparand − Σ − SLD term) measures **+0.00**
(`evidence/qwen9b/sd/014_e1_analysis.log:72`).

### 6.5 Verdict

**On measured per-key costs, with no fitted parameter, the command-list
difference explains the 9.9 %.**
* One per-command cost table, measured on the census instrument and equal
  to the chip's on every shared key except the data-dependent DYNQ8,
  reproduces both instruments' ALU and VN rows to within the DYNQ8 data
  term.
* Priced on that table, the four `SeqEmitter` rewrites account for
  **99.496 %** of the board's −9.907 %.
* The SLD-hold term accounts for 0.034 %.
* The remaining **0.471 %** is the silicon-vs-TB difference on the same
  stream, which this experiment does not address.
* The mechanism is therefore **ESTABLISHED**: the sequencer's schedule
  issues cheaper work, (a) −5.730 ms partly offset by (c) +0.919 ms and
  (d) +0.257 ms. It is not a draining artefact, a memory-model effect or a
  silicon effect.
