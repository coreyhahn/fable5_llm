# Qwen3.5-9B migration — design spec (2026-08-29)

Approved design for moving the accelerator from Qwen3.5-2B to **Qwen3.5-9B at
W4 g128 + GPTQ**, on a **9B-only bitstream**.

Inputs, all committed, all assumed here and restated only where a number drives
a decision:

* `docs/QWEN35_NEXT_FEASIBILITY.md` — the wall census (§2, 17 rows), the DDR fit
  (§3), the throughput model (§4), the decision table (§7). Final at `aa9c1ef`
  plus Track F/P dated notes; three review rounds.
* `evidence/qwen_next/ladder/LADDER.md` + `CHECKPOINT_VERIFY.md` — Track L: the
  geometry proven against the tensors, the quality ladder measured at 9B, the
  `ref/` walls fixed, the 9B residual-rail sweep.
* `evidence/qwen_next/place_exp/PLACE_EXP.md` — Track P: the URAM placement
  experiment, the write-fan-out finding, the int8 packing mechanism.
* `evidence/qwen_next/defect_a/` + `CORRECTIONS.md` — Track F.
* `evidence/qwen2b/` — the 2B migration's wall series and its R-a…R-d rungs.
  The playbook for what a geometry migration actually hits. **Only walls 6, 7
  and 8 of that series were ever written down**; 1–5 lived in session context
  that was never persisted, and no pre-gate-D ledger for them exists on disk.
  Where this spec refers to them it says *reconstructed*. See the numbering note
  in §0.
* `.superpowers/sdd/2026-08-25-qwen-next-derisking/progress.md` — **the
  DE-RISKING ledger**, and the record of every user decision below. Wherever
  this document says "the ledger" or cites a bare `progress.md`, it means THIS
  file; `ALIAS` in `evidence/qwen_next/spec_cites.py` resolves the short form
  to it, so every `progress.md:NNN` here is range-checked against it.

  > **TWO LEDGERS EXIST AND THEY SHARE A FILENAME.** The other is
  > `.superpowers/sdd/2026-08-29-qwen35-9b-migration/progress.md` — **the
  > MIGRATION ledger**, this campaign's own task log, which §0a and every gate
  > doc cite. A reviewer who followed "the ledger" to the de-risking file
  > looking for a G2 incident record found nothing there, which is how the
  > ambiguity was caught (`evidence/qwen9b/g2/D_TOL.md` §8.3). Rule for this
  > document: **name both by full path, never by "the ledger" alone.**
  > **BOTH ARE LOCAL-ONLY** — `.superpowers/sdd/.gitignore` ignores them, so a
  > reader who cloned this repo has neither. The committed equivalents are the
  > gate documents under `evidence/qwen9b/`.

> **RETIRED CITATIONS — dated supersession note, 2026-09-10.**
> `tb/scripts/gen_seq_vectors.py` was **deleted on 2026-08-31 at G2a**: §7.5
> records the confirmation that nothing invoked it, and the D-DEAD row of §9
> records the decision. **Fifteen citations to that file survive in the body
> of this document** — in §5.3, §7.4, §7.5 (eleven, ten of them in one
> row), §7.6 and §9 — and they are kept **deliberately** (the checker reports
> sixteen; the sixteenth is the naming of the file in this note). They are the record of what the
> dead near-copy contained at the moment it was deleted, so **their line
> numbers are the DELETED file's and resolve against nothing in the working
> tree**. The checker at `evidence/qwen_next/spec_cites.py` reports them as
> retired instead of failing them, and asks for exactly this note. **No live
> argument in this document rests on any of them**; the vector generator that
> survives, and that every claim about masks and scratch widths should be read
> against, is `tb/scripts/gen_seq_unit_vectors.py`.

The model for this document's structure and binding style is
`docs/superpowers/specs/2026-08-12-qwen35-2b-migration-design.md`.

---

## 0. How to read the labels

Same contract as the feasibility study's §0, extended by one row:

| label | means |
|---|---|
| **M** | measured on this board, cited to a gate log |
| **D** | computed by a committed script that reproduces a committed number before it computes a new one |
| **T** | measured by the **toolchain** — a Vivado `synth_design` / `place_design` result on real RTL and the real part. Stronger than **D**, not **M** |
| **E** | extrapolated past every measurement |
| **S** | **this document's own arithmetic** on cited primary numbers. Not measured, not derived by a committed script. **Every S carries the gate that will measure it** — if a claim below is **S** and has no gate named beside it, that is a defect in this spec |

> **Numbering note — "wall N" is ambiguous in this repo, and this spec is
> explicit about which scheme it means.** Two coexist. The **2B campaign's**
> series is referenced in committed source with the rung as its qualifier —
> `tb/tb_seq_chip.sv:87` and `:803-806` say *"R-c wall 8"*,
> `ref/gen_token_script.py:142` *"the ones wall 8 lived behind"* — and only 6, 7
> and 8 of it were ever documented. The **feasibility study's** series is the
> 17-row census of `docs/QWEN35_NEXT_FEASIBILITY.md` §2.1, and it too has reached
> committed source, in **error messages**: `ref/layer_fixed.py:675` raises
> *"This is feasibility-study wall 2 (§2.3) reaching the "* and
> `ref/fidelity_check.py:1206` says
> *"feasibility-study wall 2 (§2.3) reaching the host reference model"*, while
> `ref/fidelity_check.py:1223` names the document outright. **The two schemes share small integers and mean different things**
> — "wall 8" is the EMB row stride in one and the conv banks in the other. The
> only thing keeping them apart is the qualifier, so: **in this document, an
> unqualified "wall N" always means the feasibility study's 17-row scheme**, and
> every reference to the 2B campaign's is written as "R-b/R-c wall N" or as "the
> walls-7/8 class". Anyone grepping either series should qualify the search.

**Every `file:line` in this document is checked by a script, not by hand.**
`evidence/qwen_next/spec_cites.py` resolves every citation against the tree,
range-checks it, verifies that quoted source text really sits near the line it is
attributed to, and refuses a bare `:NNN` continuation on any line naming more
than one file. It carries a four-case **negative control** (`--selftest`): a line
number past EOF, a nonexistent path, a real quotation moved away from its cite,
and a fabricated quotation — each of which it must reject, plus a positive
control on the unperturbed document.

That exists because **hand-sweeping this document failed twice**. Review found
drifted citations after the first sweep, and again after the fix round that was
correcting them — the second time including five bare `:NNN` continuations that
had silently bound to the wrong file. The checker found all five. §8 G2 makes
running it a gate.

Where the primary sources carry a stale citation, the true line is given and the
stale one is named in §9's **D-CITE** row rather than corrected silently.
**Sweep with `/usr/bin/grep`**: the shell's `grep` here is `ugrep`, which honours
`.gitignore` and will silently skip gitignored trees.

---

## 0a. AMENDMENT A1 (2026-08-31) — G1 CLOSED, THE CONTAINER IS int16

> **Read this before §4.1, §6, §8, §10 and §12. Nothing below it has been
> deleted or rewritten; every superseded statement is left in place with a
> dated block beside it, per this document's own §0 discipline.**

**USER RULING at the G1 STOP, 2026-08-31, interactive: OPTION B — the DeltaNet
state stays `int16`.** The per-row/L1 law reached MARGINAL and its ratification
was **declined**. Recorded in the campaign ledger
`.superpowers/sdd/2026-08-29-qwen35-9b-migration/progress.md`
(**LOCAL-ONLY — `.superpowers/sdd/.gitignore` ignores it, so a reader who
cloned this repo will not find it**; the committed equivalents are
`evidence/qwen9b/g1/RUNG_INT8_STATE.md` and `evidence/qwen9b/g2/D_TOL.md`).

**What G1 measured, in three waves, host-only, no RTL** (gate doc
`evidence/qwen9b/g1/RUNG_INT8_STATE.md`, sections §5, §11, §12 — cited by
**section, not line**, because that document is still being appended to):

| container | top-1 /108 | rank max | top-5 | verdict |
|---|---|---|---|---|
| `int16` — the baseline, and now the shipped container | **95** | **5** | **3.69** | reproduces `LADDER.md` §4 exactly |
| `int8:6` global, best of eight `k` | 72 | 214 | 2.81 | **FAIL** |
| `int8h` per-head exponent | 83 | 211 | 2.95 | **FAIL** |
| `int8e` per-row exponent (L1) | 94 | 13 | 3.56 | **MARGINAL** — declined |
| `int8e` + `RS_F = 7` | 89 | 18 | — | rejected; the O5 rider condition fails |

**The consequences, each carried into the section that owns it:**

| # | consequence | where |
|---|---|---|
| A1.1 | **S1 is superseded by S1′**: DN state `int16`, **928 URAM** (24 banks × 29 + 232 KV), `DN_PIPE = 2` read-path pipelining. | §1.2, §4.1 |
| A1.2 | **The `dn_step` read-latency price becomes an explicit RTL-phase design decision** — wait state (≈ +10 %) versus the two-outstanding restructure — assigned to the task that implements it, and **reviewed, not silently chosen**. | §4.1 |
| A1.3 | **The write-control fan-out pblock becomes G5a's CRITICAL experiment.** It is the binding path and it was never tried. **It can still invalidate the target.** | §6.2, §8 G5a, §12 |
| A1.4 | 928 URAM **cannot** fit two SLRs (2 × 320 = 640 < 928). **Three SLRs are mandatory**, not a placer accident. | §6.2, §6.3 |
| A1.5 | **G4's OOC URAM check moves 592 → 928.** | §8 G4 |
| A1.6 | **Perf re-anchors down.** ≈ 6.5 tok/s class at the wait-state price; ≈ 7.0 if the restructure lands. | §10 |
| A1.7 | **The L1 per-row law stays in `ref/` as measured evidence, UNSHIPPED.** Its `sat8`/`e_fixup` counters guard nothing that ships and remain as diagnostics. | §4.1 |
| ~~A1.8~~ | ~~**`RS_F` stays 8.** The rider is container-dependent and **unmeasured under `int16`** — a cheap, genuinely open measurement.~~ **SUPERSEDED 2026-09-01 by A2: the measurement was taken and `RS_F = 7` is ADOPTED.** The container-dependence claim was right and is what makes the reversal legitimate rather than a flip-flop. | §0b, §4.4 |
| A1.9 | **The gate-port clamp is option-independent** and travels into the RTL phase unchanged: **60 of 768 DN heads have their decay changed by the production clamp.** New register row **D-GATEPORT**. | §9 |

**Two measured facts travel with the ruling and bind whatever is built:** the
container **must ROUND** (truncation at the same geometry cost 2 of 6 top-1 and
took rank max from 1 to 22,683), and **run-to-run spread is exactly zero** —
every repeat in all three waves was byte-identical over the whole report body,
so no number in the table above is draw noise.

---

## 0b. AMENDMENT A2 (2026-09-01) — `RS_F = 7` IS THE 9B OPERATING POINT

> **Supersedes A1.8 in full.** A1.8 said *"`RS_F` stays 8"* and recorded the
> value under the shipped `int16` container as unmeasured. **It has now been
> measured, and the answer reverses the disposition.**

**USER RULING 2026-09-01: `RS_F = 7` (Q8.7) is ADOPTED for 9B.** Evidence:
`evidence/qwen9b/g2/G2C_CHAIN.md` §7 (cited by **section, not line** — T5's
closure is being written concurrently).

**The measurement, at the container that ships**, single-variable by
construction (same quantizer source digest, both weight caches HIT, and
`--wq-cache-verify` re-quantized a layer live under `RS_F = 7` and found it
byte-identical to the cache — so `RS_F` demonstrably does not reach the
quantizer):

| quantity | `RS_F = 8` | **`RS_F = 7`** | Δ |
|---|---|---|---|
| top-1 | 95/108 | **98/108** | **+3** |
| rank median / max | 0.0 / 5 | 0.0 / **5** | **unchanged** |
| top-5 overlap | 3.69 | **3.69** | **unchanged** |
| residual clips | **23** | **0** | **−23** |
| `\|x\|max` | **32767** — pinned on the rail | **29916** | off the rail |
| `S_F` saturation | 4392 | 4170 | −222 |
| free-run text | coherent ×4 | coherent ×4 | — |

The int16-dequant headroom improves with it on every matvec row: the 4096×12288
and 4096×4096 rows go to **zero** clips, and the 12288×4096 row — the dominant
clip site the ladder identified as *a property of the geometry, not the format*
— falls 10,897 → 10,816.

**Why this is a ratification and not a new judgement.** The ratified **O5**
condition is *take Q8.7 only if it removes residual clipping WITHOUT costing
top-1*. Under `int16` it removes the clipping **completely** and top-1 goes
**up**, with rank max and top-5 overlap unmoved. The condition is met on its
face, and the rider was always the user's to take.

**The sign is container-dependent, which is why the earlier rejections stand
unretracted** — all three measurements now exist and they do not agree:

| container | top-1 `8 → 7` | rank max | disposition |
|---|---|---|---|
| `int8:6` global (G1 wave 1) | 72 → 73 | 214 → 335 worse | neutral on top-1, worse on rank |
| `int8e` per-row (G1 wave 3) | 94 → **89** | 13 → 18 worse | **rejected** |
| **`int16` — ships** | 95 → **98** | 5 → 5 | **ADOPTED** |

**Confirmed by repeat.** Run `b` was launched after the first point landed, an
independent process, digest re-checked equal *before* launch. `diff` over the
report body returns **one line — the `--json-out` path**. Run-to-run spread on
this configuration is **exactly zero**, as at every granularity G1 tested. The
+3 is not draw noise. *(G2C_CHAIN §7.4's closing bullet still reads "It is one
point. No repeat was run" — that bullet predates §7.3 and is superseded by it
within that document; this spec cites §7.3.)*

### A2 — the work set, and most of it is already done

| # | item | owner |
|---|---|---|
| A2.1 | **`rtl/conv4_silu.sv:50`'s baked shift `9 → 8`.** It is the one RTL literal that is not format-agnostic: `RS_F + CW_F − 12` = 7 + 13 − 12 = **8**. **A1.8 removed this file from the RTL task's Files as foreclosed; A2 puts it back.** | §4.1 W1′, G3.4 |
| A2.2 | **The 9B manifest carries `rs_f: 7`**, value-gated exactly as today: byte-locked tags still withhold the key, non-byte-locked tags still pass it. **No mechanism changes — only the value 9B passes.** | §4.4, G2c |
| A2.3 | **The host census is ALREADY DISCHARGED and must NOT be re-literalised** — see the box below. | — |
| A2.4 | `b9e0851:ref/layer_fixed.py:74`'s comment block and `sw/chat_seq.py`'s G2a commentary cite A1.8 for *"`RS_F` stays 8"*. Stale prose, in files their owning tasks touch anyway. | G3.4 / the task that next edits each file. **CLOSED 2026-09-10 (#26, pre-ship tool chore, `28fac0b`):** the block was rewritten where it stands — `RS_F` is DERIVED from `MS.TAG` (`RS_F_BY_TAG`) and a disagreeing `FABLE5_RS_F` is refused by name; the citation above is PINNED to `b9e0851`, the tree the finding was made on. |

> ### A2.3 — READ THIS BEFORE EDITING ANY HOST CONSTANT
>
> **The instruction "change `HEAD_LOGIT_EXP0` from −22 to −21" would be WRONG,
> and applying it would break the byte-locked geometries.** G2a did not leave
> these as literals to be re-pointed; it made them **derived**, and the
> derivation already produces −21 at `rs_f = 7` with no edit at all:
>
> * `sw/chat_seq.py:360` `HEAD_LOGIT_EXP0 = head_logit_exp0()          # -22 at the shipped rs_f = 8`
>   is the value for a manifest **with no `rs_f` key**. Every 0.8B/2B artifact
>   has no key, so **−22 is correct and must stay.**
> * `sw/chat_seq.py:3233` `want_exp0 = head_logit_exp0(self.head.spec.rs_f)`
>   is the live path. It reads the manifest and lands on −21 at a 9B artifact
>   **by itself**.
> * `sw/chat_seq.py:5483` already asserts `head_logit_exp0(7) == HEAD_LOGIT_EXP0 + 1`.
>   The −21 case is already under test.
> * `sw/hwmap.py:503` `RS_F_DEFAULT = 8` is the *missing-key* default, not the
>   shipped value. **Moving it to 7 would silently re-scale every pre-G2a
>   artifact's logits by a factor of two.**
> * `rs_f` is already registered in `MANIFEST_META_KEYS`, and the
>   two-keys-one-name collision this spec's M6 census flagged is already
>   documented at `sw/head_cache.py:107`.
>
> **So the host work set for A2 is EMPTY.** What the owning task does is
> *verify* the five sites above are unchanged and that the 9B path lands on
> −21 through the manifest — not edit them.

> ### A2.5 — THE ONE REAL HAZARD, AND IT IS NOT THE ONE THAT WAS FLAGGED
>
> **The emit-side guard is tag-scoped and coexists correctly with 9B at 7.**
> `ref/gen_model_script.py:657` withholds the key for
> `BYTELOCKED_TAGS = ("0.8b", "2b")` and passes it otherwise, so a 9B emission
> takes `ref/gen_layer_script.py:1294`'s write branch and never reaches the
> refusal at `ref/gen_layer_script.py:1311`. **Verified, not assumed.**
>
> **But `RS_F` itself is NOT model-selected in fact.** `b9e0851:ref/layer_fixed.py:74`
> reads `RS_F = int(os.environ.get("FABLE5_RS_F", "8") or "8")` — a
> **process-global env knob**, while §4.4 and the code's own comments call it
> *model-selected*. The tag-scoping lives entirely in the caller. Consequence,
> now that 9B emission requires `FABLE5_RS_F=7`: **a process that exports it
> and then emits a byte-locked tag hits the `rs_f is None` branch and trips the
> refusal.** That is the guard working — it prevents a silent 2× logit error —
> but it means **`evidence/qwen2b/rc/t4_bytes_unmoved.sh` and
> `ref/scripts/regen_gate.sh` must not be run with `FABLE5_RS_F` exported**,
> and the failure is an assert in an emitter rather than an obvious message
> about environment.
>
> **Flagged to the owning task rather than fixed here**: deriving `RS_F` from
> `MS.TAG` with the env as an override would make the name true and remove the
> trap at the root. Until then the operational rule is the one above, and it
> belongs in the gate docs of every task that runs both an emission and a
> byte-lock check.
>
> **CLOSED 2026-09-10 (#26, pre-ship tool chore, `28fac0b`). THE ROOT FIX WAS
> TAKEN, so both paragraphs above are HISTORY, not the operational rule.**
> `RS_F` is derived from the model tag: `ref/layer_fixed.py`'s `RS_F_BY_TAG`
> maps 0.8b/2b/4b to 8 and 9b to 7, and `FABLE5_RS_F` is now an override that
> must AGREE with the tag's value or is REFUSED BY NAME at import. So the
> sentence *"`RS_F` itself is NOT model-selected in fact"* no longer
> describes the tree, and the trap it names is gone at the root: a
> process that exports `FABLE5_RS_F` and then emits a byte-locked tag gets a
> message naming the tag and the two values, not an assert inside an emitter.
> The one deliberate escape, `FABLE5_RS_F_RIDER=1`, exists for the
> measurement scripts that sweep the rider and since 2026-09-10 it prints one
> line on stderr whenever it fires (review I-2). Evidence:
> `evidence/qwen9b/s3/095_rs_f_enforced_GREEN.log` (env unset → 23 files
> byte-identical to the committed 9B smoke set; `FABLE5_RS_F=8` refused,
> no artifact written) and `evidence/qwen9b/s3/096_rs_f_law_sweep.log` (the
> law at all four tags, agree accepted, disagree refused, `LAYER_FIXED
> SELFTEST PASS`). The citations in this box stay PINNED to `b9e0851`.

---

## 1. Decisions

### 1.1 Made by the user, and NOT re-opened by this spec

| # | decision | when / where |
|---|---|---|
| U1 | **Target = Qwen3.5-9B.** | 2026-08-29, ledger `progress.md:116-117` |
| U2 | **Quantization = W4 g128 + GPTQ** — the shipped wire format. W8 declined: it buys one token in 108 for 1.86× the bytes (`LADDER.md` §4). | same |
| U3 | **First executable gate = the int8-DN-state fidelity rung, with a STOP back to the user if it disappoints.** | same |
| U4 | **THE PROJECT IS 9B-ONLY. The one-bitstream-serves-all-models contract is DROPPED.** Optimize for 9B; exploit the freedom. | 2026-08-29, in-session, recorded at `progress.md:117`; see §3 |
| U5 | **AMENDED 2026-08-31 (A1.1): D3's option 2 was tested at G1 and NOT taken — the shipped container is option 1, `int16` at 928 URAM.** The de-risking record below is unchanged and correct as of when it was written; it is the reason G1 existed, not a statement about what ships. From de-risking: **D3** = int8 DN state banking (Track P option 2) — closed at `progress.md:111`; the *mandatory-lines* list that carries it into the migration is **D1's**, at `:116-117`, not D3's. **D4** is moot at 9B — emb rows are 8192 B = 2^13, clean. | `progress.md:111`, `:116-117` |

### 1.2 Made by this spec, with reasons

| # | decision | §ent |
|---|---|---|
| ~~S1~~ | ~~int8 DN state in the **592-naive** form (12 banks × 30 URAM288 + 232 KV), with 580-write-combined as the named fallback. The **state-quantization law** is chosen by G1, not by this spec; the structure was synthesized but never placed, so **G5a places it**.~~ **SUPERSEDED 2026-08-31 by S1′ (A1.1). G1 measured every int8 law this spec named and the user declined all of them.** The text stands as the record of what was proposed and why. | §4.1 |
| **S1′** | **DN state `int16`, 928 URAM** — 24 banks × 29 URAM288 + 232 KV, the `wide` variant Track P placed — **with `DN_PIPE = 2` read-path pipelining**. The state-quantization law is no longer a spec choice: G1 measured it and the user ruled. **The structure was placed by Track P but never routed and never floorplanned, so G5a's write-fan-out pblock is now the critical experiment and it can still invalidate the target.** | §4.1, §6.2 |
| S2 | **Residual container: saturation accepted at int16 Q7.8.** The rail is not widened. G1 additionally measures the free binary-point move `RS_F 8 → 7`. **AMENDED 2026-09-01 (A2): the container is int16 **Q8.7**, and the acceptance argument is materially STRONGER than when S2 was written — the rail is no longer saturated at all.** S2 accepted a rail that clipped 23 times with `\|x\|max` pinned at 32767; at `RS_F = 7` it clips **zero** times and `\|x\|max` is 29916. The width decision (do not widen) is unchanged; what changed is that the fragility caveat S2 carried is now much smaller — see §4.4. | §4.4, §0b |
| S3 | **16-bit scratch addressing with a clean 16+16 re-encoding** — the R-b bit-scatter is deleted, not extended. DNST gets relief by moving its two scalar pointers to a per-body CSR base pair. | §4.3 |
| S4 | **Scratch = 65,536 words, fully backed. NO MLP chunking.** | §4.3 |
| S5 | **Strip W8 mode from the 9B RTL.** −5,826 LUTs and −497 CARRY8 per channel, ×4. | §5.1 |
| S6 | **Strip g64 mode from the 9B RTL.** Frees SHAPE bit 28, removes the scale-beat generality the g64 cadence would need at ng=96. | §5.2 |
| S7 | **`MAX_NG = 96`, `cfg_ng` 7 b, XWIN 3072 words / 12 KiB, `xptr`/`wb_ptr` 12 b**, plus seven 6-bit ng-unit indices. The g128 scale-beat fields stay at 2 bits — confirmed. `g_cnt` and `wbeats` do **not** widen once W8 is stripped. | §4.5 |
| S8 | **EMBLOG2 reset moves 11 → 13.** | §5.3 |
| S9 | **Synthesizable envelope checks** on scratch address, `cfg_ng` and `cfg_nlog2` — newly cheap because there is exactly one legal envelope. | §5.4 |
| S10 | **A 9B-native floorplan is a first-class deliverable, gated by an OOC pblock experiment before the full build.** | §6 |

### 1.3 Genuinely open — for the user

| # | open | why it is open |
|---|---|---|
| **O1** | ~~**The G1 STOP.**~~ **CLOSED 2026-08-31 (A1). It fired exactly as written, three times.** The rung failed under the global law, failed under per-head, and reached MARGINAL under per-row; the user declined the MARGINAL ratification and **took option 1 — the int16 state at 928 URAM with `DN_PIPE = 2`**. Option 3 (DDR spill) and abandoning were not taken and are not re-opened here. The original text: *if the int8-DN-state rung fails its bar under both candidate laws, the fork is Track P option 1 versus option 3 versus abandoning; the spec cannot pre-decide it.* **What survives O1 is not a decision but a risk**: option 1's floorplan problem was never attempted, and §6.2 now owns it. | `PLACE_EXP.md` §4, `progress.md:111`; ruling in `evidence/qwen9b/g1/RUNG_INT8_STATE.md` §9 |
| **O2** | **Confirm the g64 strip (S6).** It forecloses, without an RTL re-add, ever measuring on hardware whether `w4g64gptq`'s 0.35 pp of float PPL survives into the fixed-point datapath at 9B — a gap `LADDER.md` §6.4 names explicitly and prices at ~7.0 h of host time. This spec judges the byte argument decisive; the user may not. | `LADDER.md` §6.4 |
| **O3** | **Board-lock convention for the shared BCU-1525.** Open since R-b and now sharper: after this ships there are **two** live bitstreams for one board and `sw/.seq.lock` is per-checkout. | `docs/HISTORY.md:700-702`, `:857-858` |
| **O4** | **Conditional: may the 9B floorplan pblock `layer_0`?** The 2B campaign's T5 lesson is "never" (constraining it in any form cost ~1 ns). Track P's binding path is a write fan-out whose 95.9 %-route signature says placement constraint is the fix. §6 resolves this by measurement first; if the OOC experiment says a `layer_0` pblock is required, the fork returns to the user. | `docs/HISTORY.md:806-807`, `PLACE_EXP.md` §3.8, §5.11 |
| **O5** | **Ratify S2 — the residual container is ACCEPTED SATURATED, not widened.** `progress.md:116` carries "residual container (S-knob exhausted at S=1)" as a D1-**mandatory** line, i.e. as a change to be made. §4.4 answers it with a measurement and a refusal to widen. The evidence is good (95/108 *with* the rail saturated, against the 90/108 that shipped) and the cost of the alternative is larger than everything else in this campaign — **but the user must see the caveat that comes with it**: `LADDER.md` §6.3 says to treat those numbers as **upper bounds** on what today's int16 Q7.8 residual delivers at H=4096, "not as clean measurements", because they were taken with the container saturated at `|x|max 32767`. Accepting the rail means accepting a **fragile** operating point: a shift in the activation distribution tips more clips, and nothing measures how much margin there is — but the user ruled on a same-shaped quality-versus-cost tradeoff in this same session when declining W8, and should ratify this one rather than find it in a gate doc. | `progress.md:116`, `LADDER.md` §4, §6.3 |

---

## 2. The geometry contract

`evidence/qwen_next/ladder/checkpoint_verify.py` runs against the real tensors
of revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a` and passes with **zero
deviations** (`CHECKPOINT_VERIFY.md`, verdict at :13-16). This is the contract;
nothing downstream may derive these from `config.json`.

**But "asserted against the tensors" is not true of every row, and the proof
column says which is which.** The script asserts shapes, counts and parameter
totals, and it asserts `vocab_size`/`head_dim` as fields (`evidence/qwen_next/ladder/checkpoint_verify.py:45`, `evidence/qwen_next/ladder/checkpoint_verify.py:63`, `evidence/qwen_next/ladder/checkpoint_verify.py:145`).
Three qualifications: the §3 geometry fields are read from `text_config` — i.e.
from `config.json` — and only *some* of them have an independent tensor proof
(`CONV_DIM` does, spectacularly: `2·LKD + LVD == in_qkv.shape[0] == 8192`); the
`emb`/`lm_head` **rms values are printed, not checked** (`evidence/qwen_next/ladder/checkpoint_verify.py:203-205`), while what
*is* checked is the distinctness that matters (`np.array_equal == False`, plus
the separate raw-byte sha256s); and **`EMBLOG2` is not a checkpoint quantity at
all** — it is derived host-side from `2·H` by `sw/hwmap.py:371-380`.

| symbol | value | proof |
|---|---|---|
| `H` (`hidden_size`) | **4096** | `CHECKPOINT_VERIFY.md` §3 `LR.H` |
| `FFN` (`intermediate_size`) | **12288** | §4 ("9B is the same with H 2560 → 4096 and FFN 9216 → 12288") |
| layers | **32 = 24 DeltaNet + 8 GQA** | §3 ("the 24/8 layer split confirmed at both targets") |
| `LNH` — DeltaNet **value** heads | **32** | §3 |
| `LNKH` — DeltaNet **key** heads | **16** | §3 |
| `VREP = LNH / LNKH` | **2** — value head *h* reads key head `h // VREP` | §9 table, `ref/layer_ref.py` |
| `LDK = LDV` | **128** | §3, `rtl/dn_step.sv:50-51` |
| `LKD = LNKH·LDK` | **2048** | §3 |
| `LVD = LNH·LDV` | **4096** | §3 |
| `CONV_DIM = 2·LKD + LVD` | **8192** | §3, **proven by the tensor**: `2·LKD + LVD == in_qkv.shape[0] == 8192` |
| `NQ` (attention query heads) | **16** | feasibility §1.1 (`q_proj` [8192,4096] = 2·NQ·HD) |
| `NKV` (`num_key_value_heads`) | **4** | §3 / feasibility §1 census (`k_proj` [1024,4096] = NKV·HD) |
| `head_dim` | **256** | feasibility §1 census table |
| `vocab_size` | **248,320** | §2 / feasibility §1 |
| LM head | **UNTIED**, `lm_head.weight` [248320, 4096], 1,017,118,720 params, **top-level** prefix | §5 — proven distinct from `emb` by an array comparison **and** two different raw-byte sha256s, as `CHECKPOINT_VERIFY.md:159` records. *(The rms pair 0.015476 vs 0.013466 is printed alongside by `evidence/qwen_next/ladder/checkpoint_verify.py:203-205` and is illustration — the distinctness proof does not rest on it.)* |
| `EMBLOG2` | **13** (row = 2·H = 8192 B) — exactly at `EMBLOG2_MAX` | **derived, not from the checkpoint**: `2·H` via `sw/hwmap.py:371-380`; ceiling at `rtl/seq_unit.sv:347` `EMBLOG2_MIN = 5'd8, EMBLOG2_MAX = 5'd13`; feasibility §2.6 |
| checkpoint | 19,306,310,880 B = 17.980 GiB, **4 shards** | §1 |
| loadable text total | **8,953,803,264** params (7,936,684,544 text + 1,017,118,720 head) | §2 |

Two consequences the rest of this document leans on:

* **9B is the *dangerous* geometry because it is well-behaved.** H=4096 is a
  power of two, so it sails past every guard that stops 4B and lands in code
  that produces a wrong answer rather than an exception (`LADDER.md` §5b). Track
  L installed refusals — `require_supported_geometry()` on `LNH != LNKH` and on
  DN/KV slot overflow — precisely so nobody could score a silently-wrong 9B
  number. **This migration's job is to replace those refusals with
  generalizations, and every one of them is a work item in §7.**
* The vision tower (333 t, 456,010,480 p) and the MTP head (15 t, 243,290,624 p)
  are present and **shipped-unused**, filtered by `load_layer()`'s
  `model.language_model.` prefix exactly as at 2B (`CHECKPOINT_VERIFY.md` §2).

---

## 3. THE ONE-BITSTREAM CONTRACT IS RETIRED

**USER DECISION U4 (2026-08-29): the project is 9B-only. One bitstream serving
0.8B, 2B and 9B is no longer a requirement.** Recorded in the ledger. Future
sessions must not resurrect it by habit — it was a standing contract from the
2B campaign (`docs/superpowers/specs/2026-08-12-qwen35-2b-migration-design.md`
§R-b item 4, "EMB_ROW_BYTES becomes a runtime CSR so **one bitstream serves both
models**") and every reflex in this repo points at it.

### 3.1 What that removes

**The frozen-replay back-compat gate is GONE.** The 2B campaign's central
regression net — "every frozen 0.8B stream replays **bit-exact** on the widened
RTL in sim, 4 seeds" — does not apply to this build. It was never going to
survive contact with U5 anyway, and it is worth saying why, because it is the
single most load-bearing consequence of U4:

> The DeltaNet state is `int16 Q2.13` (`ref/layer_fixed.py:39`, `S_F = 13`).
> **Narrowing it to int8 changes the numerics of the recurrence.** The 0.8B and
> 2B frozen streams were produced against an int16 state, so they cannot replay
> bit-exact on an int8-state machine. Under the old contract the only way out
> was a **dual-width DN state array** — arithmetically available (the 2B int16
> state is 75,497,472 bits and the 9B int8 provisioning is 100,663,296 bits, so
> the smaller fits inside the larger with 9 of 12 banks used) — at the cost of a
> width mux in exactly the read path Track P measured as timing-critical.
> **U4 deletes that mux before it is built.** The array is int8-only.

> **AMENDED 2026-08-31 (A1.1). The array is `int16`-only, and this box's
> conclusion survives its premise.** The frozen-replay gate is still gone —
> U4 deleted it, not the container choice — but the *reason* stated above no
> longer applies: with an int16 state the 0.8B/2B streams would not diverge on
> the recurrence's numerics. What still stops a bit-exact replay is everything
> else this migration does to the datapath (§4.2's `vecnorm` width, §4.3's ISA
> re-encoding, §4.5's `MAX_NG`, §5.1's W8 strip). **The dual-width mux is still
> not built** — there is only one width now, so there is nothing to mux — and
> the read path Track P measured is the one that ships, with `DN_PIPE = 2`
> registers added to it (§4.1). The arithmetic quoted above stands as written:
> the 2B int16 state is 75,497,472 bits and the 9B int16 provisioning is
> 201,326,592 bits, i.e. **24 banks, not 12**, which is where 928 URAM comes
> from.

Also removed: any obligation to keep the R-b 15-bit bit-scatter encoding
replayable (§4.3), to keep the shipped 9-bank/3-bank DN/KV address expression
bit-identical (§4.1), to keep W8 mode in the engine (§5.1), or to keep g64
(§5.2).

### 3.2 What that does NOT change

The 0.8B and 2B models **stay served, by their existing bitstreams**:
`build_034_po2_AltSpreadLogic_high` (`4f908df2`) and
`build_035_fp2a_exc_po` (`54443b9f`, the resident one, currently holding the 2B
W8 weight pack). Their frozen locks, goldens and gate docs stay in-repo and stay
valid **for those configurations**. They are not a gate on this build, and this
build's RTL is not required to reproduce them.

**Operational consequence, stated honestly:** serving 0.8B or 2B after the 9B
ships requires a **bitstream swap plus a full weight re-upload**. The weight
re-upload was already true (`docs/HISTORY.md:687-688`: "A model switch is a FULL
weight re-upload — one pack fits DDR at a time"). The **bitstream swap is new**,
and it goes through the CHARTER safety rails every time:
`sudo -n sw/pcie_helper.sh remove` → `sw/program_fpga.sh` (JTAG, volatile) →
`sudo -n sw/pcie_helper.sh rescan`. It is a ~2-minute operation, not a rebuild.
It also sharpens **O3** — two live bitstreams, one board, no shared lock.

### 3.3 Host-side scope, which is narrower than the RTL scope

`ref/` and `sw/` still serve the old bitstreams. **Stripping W8 and g64 from the
RTL does not strip them from the host.** `ref/w4a8_ref.py`'s W8 section,
`matvec_y32_w8`, `sw/hwmap.py`'s `w8` plumbing and `ref/model_select.py`'s
four-entry `MODELS` table all stay. `model_select` in particular is a
**regression asset** — Track F's `--selftest` runs `emb_geometry_selftest()` once
per MODELS entry in its own interpreter (`progress.md:11`) — and it costs the
board nothing. This spec deliberately does **not** strip it; that is a hunted
simplification, rejected with a reason (§5.6).

---

## 4. RTL work items

Ordered by gate, not by size. **W1 is the only one that runs before anything
else is committed to.**

### 4.1 W1 — DN state banking, and the G1 fidelity rung

> ### PRE-G3.4 ROWS, KEPT AS THE RECORD — dated note 2026-09-02 (Task 10)
>
> Rows in this section that name a `rtl/layer_chan.sv`, `rtl/dn_step.sv`,
> `rtl/gate_unit.sv`, `rtl/seq_unit.sv`, `tb/tb_gate_unit.sv` or
> `sw/hwmap.py` line quote **source that G3.4 REWROTE or DELETED**, not
> source that merely moved: the 9-bank / 3-bank hand-split DN and KV
> expressions, the 4-bit `dn_head_hw` and 1-bit `kvhead_hw` datapath
> slices, `gate_unit`'s `NH = 16` and its 4-bit `w_addr`, the 18 × 6144
> conv banks, `EMBLOG2_RST = 5'd11`, `conv4_silu`'s shift 9 and the whole
> `` `ifndef SYNTHESIS `` datapath-envelope block.  They are kept
> verbatim, because they are the record of what the pre-G3.4 tree said and
> the argument this section makes rests on them (§0: nothing is deleted or
> struck).  Every citation that had merely MOVED was RENUMBERED instead,
> mechanically, by `evidence/qwen9b/o3/o3_cite_drift.py --base 8138d66`.
> **The post-G3.4 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_4_LAYER.md` §11.1.**

> ## SUPERSESSION 2026-08-31 (A1.1, A1.2, A1.3, A1.7) — W1 IS int16 AT 928 URAM
>
> **G1 ran, three waves, and the user ruled OPTION B.** Everything below this
> block up to §4.2 is the **int8** design and the rung that tested it. It is
> **kept, not rewritten**, because it is the record of what was proposed, what
> was measured, and why the measurement went the way it did. **What ships is
> defined here.**
>
> ### W1′ — the shipped structure
>
> **`int16` DeltaNet state, 24 banks + 8 KV banks, 928 URAM288 of 960** — the
> `wide` row of the table below, which Track P **placed** (spread 312/312/304
> of 320 per SLR). Per-bank arithmetic: 24 × 29 = 696 DN + 232 KV = **928**.
> The int8 rows below (592 / 580) describe a container this build does not
> ship.
>
> **`DN_PIPE = 2` read-path pipelining is part of the structure, not an
> option.** Two register stages on the per-group control/address/write-data
> fan-out **and** two on the read-data return, so every long haul runs
> flop-to-flop. Read latency 2 → 2 + 2N = 6; write latency +2. Cost is
> **flip-flops only**: LUTs unchanged at ~109.5 K, FF 54,276 → 78,948, i.e.
> **≈ 1 % of the device's 2,364,480**, and **URAM stays exactly 928**
> (`PLACE_EXP.md` §3.7).
>
> **What that buys, and the dependency it carries.** The named 2048-bit DN
> bank-mux net goes −1.848 → −0.162 at N=2 at the Default directive, and
> **MEETS at +0.097 ns** under `AltSpreadLogic_medium` — Track P's `r3pipe2alt`
> (`PLACE_EXP.md` §3.8). **The MET carries that directive dependency and this
> spec states it every time it quotes the number.** §3.6 measured ~0.5 ns of
> free directive spread, so the directive is worth as much here as the
> pipelining.
>
> **What it does NOT buy: `DN_PIPE = 2` does not close the module** (−1.391 /
> −2,007.2 / 6,638 EP), and per-bank fan-out (`DN_BPG = 1`) is **worse**
> (−1.956 / 12,692 EP). **The binding constraint is the write-control fan-out**,
> whose worst path is **one logic level with 95.9 % route** — *"a placement
> signature, not a structural one"*. See A1.3 and §6.2: **the pblock was never
> tried, and it can still invalidate this target.**
>
> ### W1′(a) — the `dn_step` read-latency price is an RTL-PHASE DESIGN DECISION
>
> **This spec does not choose between the two options, and it must not be
> chosen silently by whoever writes the RTL.** `PLACE_EXP.md` §5 item 14 is
> explicit that *"the N=2 latency price is not designed, only bounded"* —
> *"an upper bound and an admission, not an implementation"*.
>
> `dn_step` reads the state memory **once per row per pass**, 256× per head
> (`rtl/dn_step.sv:226`, `:261`). At `DN_PIPE = 2` the read needs an address
> **lead of 6**. Pass 1 can buy lead 4 for free by issuing `s_rdaddr` in
> `P1_DEC` instead of the loop tail; **pass 2's five-state loop cannot provide
> lead 6 at any issue point.** So:
>
> | option | price | status |
> |---|---|---|
> | **(i) a wait state** in pass 2's loop | **≈ +10 % throughput** | bounded by Track P, not designed |
> | **(ii) a two-outstanding restructure** — two reads in flight so lead 6 exists without stalling | **unpriced**; would remove the +10 % | **nobody has written it or shown that it closes** |
>
> **Decision point: the task that implements `layer_chan`'s DN banking owns
> this choice, and it is REVIEWED, not silently taken.** The implementation
> plan assigns it a step of its own with its own review gate. Option (i) is the
> default only in the sense that it is the one that is bounded; picking it
> without having costed (ii) is exactly the silent choice this block forbids.
> **`DN_PIPE = 1` is not a third option**: its price is the ~0.15 % that an
> earlier revision of this spec quoted, but **N = 1 does not close** (−0.339),
> so the cheap number and the closing build are different builds.
>
> ### W1′(b) — what G1 leaves behind, and where it lives
>
> * **The L1 per-row law is MEASURED and UNSHIPPED.** `int8e` scored **94/108,
>   rank max 13, top-5 3.56 — MARGINAL**, one token below the `int16` container
>   it would have replaced, missing PASS on rank max alone. Per-head scored
>   83/108, global-`k` 72/108. The law stays in `ref/layer_fixed.py` behind
>   `FABLE5_DN_STATE` as committed evidence — **it is not on any shipping
>   path**, and the RTL mirrors `int16`, i.e. `clip16`, under which the law is
>   the identity. Evidence: `evidence/qwen9b/g1/RUNG_INT8_STATE.md` §11, §12.
> * **The `sat8` and `e_fixup` counters stay.** They were built to make an int8
>   container's saturation visible and they now **guard nothing that ships**.
>   Kept as available diagnostics — they cost nothing under `int16`, where they
>   never fire — and named here so nobody later reads their silence as evidence
>   about the shipped container.
> * **The container must ROUND.** Truncation at the same geometry cost 2 of 6
>   top-1 and took rank max from 1 to 22,683. Under `int16` the law reduces to
>   `clip16`, which is what the shipped generators already do, so this is a
>   constraint on any future re-opening rather than on this build.
> * ~~**`RS_F` stays 8** — see §4.4's amendment (A1.8).~~ **SUPERSEDED
>   2026-09-01 (A2): `RS_F = 7` is the 9B operating point, so this task DOES
>   touch `rtl/conv4_silu.sv:50` — its baked shift goes 9 → 8. See §0b.**
> * **The gate-port clamp travels unchanged** — see §9's new **D-GATEPORT** row
>   (A1.9). It is a property of the checkpoint against the frozen `gate_unit`
>   ports, not of the state container, so option B inherits it in full.

**Evidence.** Track P measured this live (`PLACE_EXP.md`, label **T**):

| variant | URAM288 | placed | DN mux slack | WNS | TNS | failing EP |
|---|---|---|---|---|---|---|
| `base` (as built, 9+3 banks) | 348 | OK | +0.211 MET | −0.145 | −1.2 | 16 |
| `wide` (int16, 24+8 banks) | **928** | OK | **−1.848** | −2.103 | −12,945.8 | 27,287 |
| `int8u` (int8, unpacked 24 banks) | 592 | OK | −0.613 | −0.846 | −2,272.2 | 8,167 |
| `int8p` (int8, packed 12 banks + write combiner) | **580** | OK | −0.259 | −0.594 | −117.4 | 1,025 |
| `int8p_alt` (same, `AltSpreadLogic_medium`) | 580 | OK | **+0.033 MET** | **−0.119** | **−2.7** | **48** |
| `int8naive` (int8, packed 12 banks, naive partial write) | **592** | **synth only** | — | — | — | — |

**S1 — the spec picks `int8naive`'s structure (592), not `int8p`'s (580).**
Reasons, all from `PLACE_EXP.md` §3.1 and §3.5, which is where Track P itself
lands:

1. The naive 1024-bit partial write of a 2048-bit URAM row **does not fall out
   of URAM** — `EXP_SYNTH_DN_NONURAM_CELLS: 0`. The earlier claim that it would
   was wrong, and running it is what caught that. Vivado maps each written half
   to its own 15-URAM slice (`ceil(1024/72) = 15`), so a bank costs 30 instead
   of 29: 12 × 30 = 360 DN + 232 KV = **592**.
2. So the write-combining register buys **12 URAM (592 → 580, 2 %)** and nothing
   else. It is an optimization, **not** an enabling requirement.
3. `int8naive` gets **the same 12-bank read mux** as `int8p` — 2 logic levels,
   no MUXF7, the same depth as the shipped 9-bank design — which `PLACE_EXP.md`
   §3.4 identifies as the axis that actually matters.
4. The combiner's legality rests on `dn_step` driving `s_wraddr` **per-pass
   ascending with an even-start / odd-end flush guarantee**
   (`rtl/dn_step.sv:262`, `:297`; LDK = 128 even). That is a real correctness
   obligation at command boundaries (DNZ, partial rows, back-to-back commands)
   that `PLACE_EXP.md` §5.5 explicitly lists as **unproven**. 12 URAM of 960 is
   not worth buying a new proof obligation.

**S1 carries a measured gap, and it is named:** `int8naive` was synthesized but
**never placed** (`PLACE_EXP.md` §5.13). Its timing is unknown and the claim that
it should time like `int8p` is reasoning, not measurement. **G5a variant 1
places it** (§6.2) — G4's OOC run confirms only the *count*. If it does not close
where `int8p` did, the fallback is `int8p` + the combiner, and the combiner's
boundary proof becomes a work item.

> **THE SHIPPED MAP, AMENDED 2026-08-31 (A1.1).** The paragraph below derives
> the **int8** 12-bank map. At `int16` the arithmetic is the one this spec's own
> parenthetical already names: 24 slots × 32 heads × 128 rows = **98,304 rows of
> 2048 b = 24 banks of 4096 — ONE LAYER PER BANK**, because at LNH = 32 the
> `head + row` field is exactly 12 bits and fills a URAM's depth exactly. That
> is Track P's `wide` structure and it is what the RTL implements. The KV array
> is unchanged either way: `{kv_slot, kvhead, k/v, t[8:0]}` → 8 banks at
> NKVH = 4, **232 URAM**. 24 × 29 + 232 = **928**.

**Address structure.** Track P's linear address `{dn_slot, head, row}` cut at the
URAM depth replaces the shipped hand-split
`{dn_layer_r[0], head[3:0], row[6:0]}` in-bank with `dn_layer_r[4:1]` as bank
(`rtl/layer_chan.sv:535-563`, whose own comment reads *"9 URAM banks, each holds
two dn slots via an in-bank MSB"*). **The packing ratio, correctly:** at int8 the
9B state is 24 slots × 32 heads × 128 rows = 98,304 rows of 1024 b, i.e. 49,152
URAM rows of 2048 b, i.e. **12 banks of 4096 — two layers per bank**, exactly the
shipped two-slots-per-bank structure. *(An earlier revision of this paragraph
said one layer per bank; that is the **int16** case, which is where Track P's
"at LNH=32 the head+row field is exactly 12 bits, so one bank holds exactly one
layer and the bank count becomes 24" belongs. Both are true of different
variants and this spec builds the int8 one.)* ~~builds the int8 one~~ —
**superseded 2026-08-31 (A1.1): this spec builds the `int16` one, i.e. the
24-bank / one-layer-per-bank map the box above states; the parenthetical's
description of which variant is which remains correct.** **U4 means this no longer has to
reduce bit-identically to the shipped expression at default parameters** — it may
be laid out for 9B alone.

The KV array gets the same treatment: `{kv_slot, kvhead, k/v, t[8:0]}` → 8 banks
at NKVH=4, 232 URAM, unchanged in structure. **Note where its exponent memory
lives**, because §4.1's L1 leans on it: `rtl/layer_chan.sv:713-714` carries the
`(* ram_style = "ultra" *)` attribute on `mem [4096]` **only** — `emem [4096]` has
no attribute and is therefore inferred **outside** the URAM array, in BRAM/LUTRAM
beside it. It is URAM-free because it is not in the URAM, not because it fits in
the row.

#### G1 — the int8-DN-state fidelity rung. THE FIRST EXECUTABLE GATE.

> **CLOSED 2026-08-31 (A1). RAN AS SPECIFIED; THE ANSWER WAS NO.** This
> sub-section is the gate's *design*, kept intact because the gate executed it
> and because several of its provisions earned their keep on the day:
> **(d)'s two-tool mandate** caught a port failure that `audit_ranges` alone
> reported as a PASS; **(c)'s repeat run** turned the bar's premise from an
> argument into a measurement (spread exactly zero); and **the Cost
> paragraph's first task** — establish that the quantized-weight artifacts are
> independent of the state law — saved ≈ 45 h of snoke across eighteen runs.
> The bar itself was never reached: the best law scored 94/108 against ≥ 93 but
> missed rank max ≤ 8 at 13, and the user declined to ratify the MARGINAL.
> **Outcome and full tables: `evidence/qwen9b/g1/RUNG_INT8_STATE.md`.**
> Nothing in this sub-section is an instruction any longer.

Nothing else in this spec is built until G1 returns. **Host only: no RTL, no
board, no synthesis.** Runs on snoke.

**(a) The law goes in `ref/` first.** `ref/layer_fixed.py` carries the DeltaNet
state as `int16 Q2.13` (`ref/layer_fixed.py:39`, with its own measured note *"|S|max 0.76, rms
0.009 → 74 LSB rms, range ±4"*). Add a parameterized state-narrowing law applied
**after every state update**, so the host model is bit-exact against what the RTL
would hold. Two candidate laws, measured in this order:

* **L0 — plain narrowing.** `S8 = sat8(rshr_round(S16, k))`, `k` a config
  constant. This is what Track P's experiment RTL sketched, except that the
  experiment truncated with **no rounding** (`PLACE_EXP.md` §5.1) — the law here
  rounds, and the rung measures truncation as a cheap second point only to
  record what *not* to build. Sweep `k` the way Track L swept `res_scale`: six
  teacher-forced steps per setting (`fidelity_9b_w8_SMOKE*.log` is the model),
  then the full run at the winner. **Two things about that model must change,
  and they are the reason it is a model and not a template:** Track L's sweep ran
  **W8 on a single prompt** (`LADDER.md` §4, *"Six teacher-forced steps per
  setting, W8, same prompt"*) while the point this build ships is **W4+GPTQ**, so
  the smoke here runs at `w4g128gptq`; and a six-step single-prompt smoke selects
  `k`, it does not score it — the score is the full 168-step run on all four
  prompts.
  *Prior, stated because it is discouraging and should be:* at `S_F = 13` the
  int16 rail already saturates **4,392 times** over 168 steps at 9B W4+GPTQ
  (`LADDER.md` §4, `s_sat`), so headroom at the top is already spent; and a
  plain narrowing that keeps the ±4 range gives Q2.5, i.e. 0.03125 resolution
  against a measured rms of 0.009. **L0 may well fail. That is what the rung is
  for.**
* **L1 — int8 mantissa with a per-row power-of-two exponent.** Only if L0
  fails. This is **not a new invention**: the KV cache in the adjacent URAM bank
  is *already* "int8 with per-vector power-of-2 exponent"
  (`ref/layer_fixed.py:19`, `KVC_F = 6` at `:44`), and the RTL bank that holds
  it already carries `logic [7:0] emem [4096];` beside the data
  (`rtl/layer_chan.sv:714`).
  **(S) — the URAM arithmetic, restated under S1's actual structure**, because an
  earlier revision computed it under the wrong one. S1 is the **split-row**
  `int8naive` map: each 2048-bit bank row is two independently-written 1024-bit
  halves, and Vivado maps each half to its own `ceil(1024/72) = 15`-URAM slice,
  30 per bank. Adding an 8-bit exponent per state row makes each half 1032 bits,
  and `2 × ceil(1032/72) = 2 × 15 = 30` — **unchanged**. So an in-row exponent is
  URAM-free *provided* the exponent sits inside its own half-row rather than
  straddling the half boundary, which is a bit-layout obligation, not a free
  lunch. **And the cheaper road is the one the KV bank already takes**: put the
  exponent in a separate `emem`-style array outside the URAM (see the address
  paragraph above), which costs BRAM and a second port and no URAM at all.
  *Both roads are spec arithmetic on Track P's primitive counts, not a synthesis
  result.* **Gate: G4 re-runs the OOC synthesis with whichever exponent structure
  L1 picks and confirms 592, or L1's URAM price is re-opened.** L1 is materially
  more RTL than what Track P placed, so **escalating to L1 is itself a STOP-back
  item** (§ below).

**(b) The measurement.** `ref/fidelity_check.py` at 9B, `w4g128gptq`, `S=1`, the
committed four prompts, 27 steps each = **108 teacher-forced**, `--free-ntok 12`
→ 168 total steps, teacher-forced against the committed golden
`golden_bf16_9b.npz` sha256 `4fd0616bae5086b8e449901740355a9f192b33ae1c9d18eafc160c0987408fd3`
(`LADDER.md` §1). Identical harness, identical golden, identical prompts as the
baseline, so the comparison is single-variable.

**The baseline this is scored against** (`LADDER.md` §4, measured, committed):

| | 9B W4 g128+GPTQ, int16 state, S=1 |
|---|---|
| top-1 | **95 / 108** |
| rank median / max | 0 / **5** |
| top-5 overlap | **3.69** |
| \|residual\|max (rail 32768) | 32767 |
| residual clips | 23 / 168 steps |
| `S_F` saturation | 4,392 |

**(c) The bar.**

First, how much a one-token difference is worth here. **(S)** The datapath is
integer, the golden is frozen and committed by sha, the prompts are fixed, and
the only variable is the state law — so a *re-run of one configuration* should
reproduce exactly. **That is an argument, not a measurement, and it is this
document's, not Track L's.** `LADDER.md` §6.8 says something narrower and it is
worth quoting rather than paraphrasing: each point ran once, so **no run-to-run
spread was measured at any point**, and "with thread counts pinned at 6 the known
1e-8-relative cross-run band applies". A 1e-8-relative band on the logits cannot
plausibly move a top-1 count, but *cannot plausibly* is not *did not*.
**Gate: G1 measures it** — the winning `k` is re-run once, in a fresh process, and
the two runs must agree on all six reported quantities. If they do not, the bar
below is re-derived against the observed spread before anything is concluded.
This costs one 168-step run (3.79 h) and it buys the only thing that makes a
93-vs-92 threshold meaningful.

| band | criterion | action |
|---|---|---|
| **PASS** | top-1 ≥ **93/108** and rank max ≤ **8** and top-5 ≥ **3.50** and free-run text coherent on all four prompts | proceed to G2 |
| **MARGINAL** | top-1 **90–92** or rank max **9–16**, text still coherent | **STOP-back** with the numbers; the user decides |
| **FAIL** | top-1 < 90, or rank max > 16, or any free-run degeneration | **STOP-back**, O1 fork |

**Why 93, corrected.** An earlier revision justified this threshold as "no more
than three tokens, i.e. 3× the W8→W4 step" — which yields **92**, not 93, and
contradicted its own table. **The bar stays at 93 and the rationale is fixed**,
because the bar is the load-bearing number and the arithmetic behind it was the
error: 93/108 is **at most two tokens** below the int16 baseline of 95, i.e. **2×
the one-token W8→W4 step the user already accepted under U2**. Two rather than
three is deliberate — 93 leaves a clear three-token margin above the 90 that
shipped, so PASS means "comfortably better than the last thing that worked" and
the 90–92 band is where the user, not the spec, decides. Why 90 as the floor of
MARGINAL: **90/108 is the 2B W8 point that shipped** (`LADDER.md` §4) and
produced coherent chat on silicon (`RD_GATE.md`), so it is the repo's own
demonstrated-shippable level.

**(d) The second axis, mandatory** — and **not** `audit_ranges` alone, because on
the one port that matters most it is blind. The feasibility study (§6 item 5) and
`PLACE_EXP.md` §4 both require the int8 state to be range-scored, and
`ref/audit_ranges.py` is the tool for the state itself. But the `Av` gate port —
§2.7's own stated reason to expect the int8 state to cost something, and the port
the 2B audit found already running **1 of 288 heads over its rail** — must come
from somewhere else. `ref/audit_ranges.py:81-82` says so **in its own text**: the
pre-clamp truth "is recorded in `qd[\"gate_sat\"]` (which this script does not
read) and is measured by `evidence/qwen2b/q2/audit/gate_port_probe.py`", because
`layer_fixed.quant_deltanet` saturates `dt_bias` and `A` into their ports before
returning them, so `audit_ranges` reports `0 / N` out of range and a max pinned
exactly at the rail **even if the checkpoint exceeds the port**
(`docs/QWEN2B_QUANT_STUDY.md:501`, `:526-527`;
`evidence/qwen2b/q2/audit/audit_log.txt:39`). So G1(d) is **two tools**:
`audit_ranges` for the state, and `qd["gate_sat"]` via `gate_port_probe.py` for
the gate port, both at 9B.

**(e) The free rider — `RS_F 8 → 7`.** See §4.4. It rides on the same runs.

**(f) The STOP protocol.** G1 stops back to the user, with the full table and no
recommendation attached to a MARGINAL, in any of these cases:

1. L0 lands MARGINAL or FAIL at every `k`.
2. L0 fails and the rung would have to escalate to L1 — because L1 is a bigger
   RTL change than the one Track P placed, and U3's STOP exists to catch exactly
   that kind of scope growth before it is spent.
3. Either range tool of (d) reports a saturation class the fidelity harness does
   not see — including a `gate_sat` result that the fidelity top-1 does not
   reflect.
4. The repeat run of (c) does not reproduce, i.e. the bar's premise fails.

At a STOP the report carries: the measured table, both range-tool outputs, the
O1 fork with Track P's own prices attached (option 1 = 928 URAM + `DN_PIPE=2`,
≈ +10 % throughput or an unpriced two-outstanding restructure, floorplan
untried; option 3 = DDR spill, 0.6 % of 9B W8 traffic but a large new RTL path),
and nothing else. **No RTL is written before G1 returns PASS.**

**Cost.** From Track L's measured rates: a full 9B W4+GPTQ fidelity point is
**6.99 h** (load 42.6 s + head 1,309.5 + config 23,826.4 s), of which the 168
steps are **81.13 s/step = 3.79 h** (`LADDER.md` §7, §4). A six-step smoke is
~8 min. Budget: **one quantization pass + one smoke sweep + one or two full
points ≈ 12–15 h of snoke**, dominated by whether the quantized-weight artifacts
can be cached across state-law settings — they are independent of the state law,
so they should be, and **the first task of G1 is to establish that they are**
rather than to pay 6.99 h per point.

### 4.2 W2 — `vecnorm_unit` at N = 4096

> ### PRE-G3.2 ROWS, KEPT AS THE RECORD — dated note 2026-09-02 (Task 8)
>
> **G3.2 LANDED THE WIDENING THIS SECTION SPECIFIES.**  Rows below marked
> `<!--cites:noquote-->` quote the **pre-G3.2 source that G3.2 REWROTE** —
> the 12-bit counters, the 2048-deep `xbuf`/`wbuf`, the 11-bit `w_waddr` /
> `vn_waddr` and the `cfg_nlog2 >= 4'd12` guard — not source that merely
> moved.  They are kept verbatim, because they are the record of what the
> tree said when this section was written and the whole argument rests on
> the *as built* column (§0: nothing is deleted or struck).  The exemption
> marker is used for exactly the reason §7.6 gives — *"an exemption is for
> source that no longer exists, not for a citation that has merely moved"*
> — and every citation that had merely MOVED was RENUMBERED instead,
> mechanically, by `evidence/qwen9b/o3/o3_cite_drift.py --base ec08638`
> (which is why the `rs_p` sentence below now names
> `rtl/vecnorm_unit.sv:331-333`; its old number is in the landmark table).
> **The post-G3.2 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_2_VECNORM.md` §9.**

**Evidence.** `LADDER.md` §4 item 2 makes this a *mandatory* 9B RTL line and
notes that the host reference model **cannot see it**, because `layer_fixed`
mirrors the *shift*, not the *width*. Feasibility §2.3 owns and prices it.

Verified against the tree today:

| site | as built | needed | verified |
|---|---|---|---|
| `rtl/vecnorm_unit.sv:159` `logic [11:0] cnt, n_total;` — comment *"12 bits: n_total = 2048 must FIT"* | 12 b | **13 b** | exact |  <!--cites:noquote-->
| `rtl/vecnorm_unit.sv:161` `logic [11:0] oidx;` (and `:162` `ecnt`) | 12 b | **13 b** | exact |  <!--cites:noquote-->
| `rtl/vecnorm_unit.sv:106-107` `xbuf [2048]`, `wbuf [2048]` | 2048 | **4096** | study |  <!--cites:noquote-->
| `rtl/vecnorm_unit.sv:93` `input wire [10:0] w_waddr` | 11 b | **12 b** | study |  <!--cites:noquote-->
| `rtl/layer_chan.sv:537` `logic [10:0] vn_waddr;` | 11 b | **12 b** | study |  <!--cites:noquote-->
| `rtl/vecnorm_unit.sv:424-426` `$fatal(… cfg_nlog2 >= 4'd12 …, "max 11, N=2048")` | guard at ≥12 | **guard at ≥13** | exact |  <!--cites:noquote-->
| `rtl/vecnorm_unit.sv:277` `n_total <= 12'd1 << cfg_nlog2;` — the wrap site the `$fatal` guards | | widen with `n_total` | exact |  <!--cites:noquote-->
| `rtl/layer_chan.sv:1413` `ld_n <= arg0[10:0]` (VNW count, 0 encodes 2048) | 11 b | **13 b, and the escape encoding is RETIRED** — 13 bits represent 4096 directly (max 8191), so `0` should mean 0 and be refused, not mean 4096. Keeping a legacy escape that the width no longer needs is how `:1850`/`:1866`'s accidental CONV wrap became load-bearing (§4.6 wall 11). Emitter assert replaces it | study §2.3 + spec |  <!--cites:noquote-->

Two that do **not** move, and the study's arithmetic on them is accepted:
`ss_acc` is 48 b (`2048·32767² < 2^42`; at 4096 it is 2^43, still fine) and
`rs_p` is 6 b, which holds `nlog2 = 12` — verified: `rtl/vecnorm_unit.sv:331-333`
folds `cfg_nlog2` into the rsqrt binary point as a shift and `rs_p` is
`logic [5:0]`. `cfg_nlog2` itself is `[3:0]` and 12 fits; it does **not** widen.

**This is the same widening R-b performed once** (1024 → 2048, including the
`n_total` wrap-to-zero deadlock it uncovered). Precedented, costed, not free.
`vecnorm_unit` sits on the layer critical path.

### 4.3 W3 — 16-bit scratch addressing, the ISA re-encoding, and the scratch array

> ### PRE-G3.1 ROWS, KEPT AS THE RECORD — dated note 2026-09-01 (Task 7)
>
> Rows in this section marked `<!--cites:noquote-->` quote **SEQ_ISA v1.7
> source that G3.1 DELETED**, not source that merely moved.  They are kept
> verbatim, because they are the record of what the pre-G3 tree said and the
> argument this section makes rests on them (§0: nothing is deleted or
> struck).  The exemption marker is used for exactly the reason §7.6 gives —
> *"an exemption is for source that no longer exists, not for a citation that
> has merely moved"* — and every citation that had merely MOVED was
> RENUMBERED instead, mechanically, by
> `evidence/qwen9b/o3/o3_cite_drift.py --base d2d774b`.
> **The post-G3.1 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_1_ISA.md` §15.**

#### The problem

The scratchpad today is **32,768 words** — `rtl/layer_chan.sv:476-477`
`logic signed [15:0] smem_a [32768];` / `smem_b [32768]` — with **15-bit**
addressing throughout (`rtl/layer_chan.sv:478` `logic [14:0] sa_addr, sb_addr;`). *(The nearby  <!--cites:noquote-->
comment at `rtl/layer_chan.sv:331` still says "16K x 16" and is stale; the arrays are 32768 deep.
`rtl/seq_movers.sv:190` `SCR_WORDS = 32768` is correct.)*  <!--cites:noquote-->

The 9B scratch peaks (**D**, feasibility §2.2, from `scratch_peak.py`, which
reproduces the committed 0.8B and 2B maps exactly before evaluating anything):

| body | 0.8B | 2B | **9B** |
|---|---|---|---|
| `PEAK_DN` | 16,384 | 21,504 | **33,824** |
| `PEAK_ATTN` | 15,872 | 23,552 | **37,920** |
| `PEAK_MLP` | 14,848 | 25,600 | **50,208** |
| **PEAK** | 16,384 | 25,600 | **50,208** |
| vs 32,768 | +16,384 | +7,168 | **−17,440** |

**All three bodies are over.** A two-way MLP chunk lands at 33,824, over by
1,056; a three-way chunk fits the MLP at 29,728 — but `PEAK_ATTN` 37,920 and
`PEAK_DN` 33,824 bust independently of any MLP chunking. So the 16-bit address
is mandatory — and **in the study's own hedged form**, which is worth keeping:
§7.2 says the ISA is "**effectively** mandatory" and §2.2 that 9B
"**realistically** wants" it. The hedge is real, because a sufficiently
aggressive re-tiling of the DN and ATTN bodies is not *proven* impossible; it is
simply not a design anyone has, and the exercise would re-open the allocator
whose numbers the study had to correct twice. This spec treats it as mandatory
and records that it is a judgement.

And the address has nowhere to go. R-b's 15th bit had a spare in every arg word;
**the 16th does not.** DNST's ARG0 is 32 bits exactly full — verified in RTL:
`rtl/layer_chan.sv:162-165` documents
`arg0={a_beta[13:0]@31:18,a_dec[13:0]@17:4,head[3:0]},`
and `rtl/layer_chan.sv:1275` / `rtl/layer_chan.sv:1192-1193` read it that way; ARG1's
last two spares are already spent on `a_dec[14]`/`a_beta[14]`. Today DNST uses
**94 of its 96 arg bits** — only `ARG2[31:30]` are free (verified: `rtl/layer_chan.sv:163`
`arg2={dst,src_v}` in the pair layout, bits 28/29 for the high bits).

#### S3 — the re-encoding, and why it is *simpler* than what it replaces

U4 removes the reason the bit-scatter existed. The R-b encoding —
`ARG1 = {hi[14]@29, lo[14]@28, hi[13:0]@27:14, lo[13:0]@13:0}`
(`rtl/layer_chan.sv:119-120`) — exists **solely** so that every frozen pre-R-b
stream, whose addresses are all < 16384, emits zeros in the borrowed bits and
replays bit-identically. With no frozen stream to preserve, the pair layout
becomes the obvious one:

> **`ARG1 = {hi[31:16], lo[15:0]}`. Same for `ARG2` where a command needs a
> second pair. No scattered bits anywhere.**

The whole command set fits under that rule, with one exception and one
relocation. **(S)** — the bit budgets below are this document's arithmetic on
the verified field list at `rtl/layer_chan.sv:140-186`; **G3 mechanizes it**
(§7).

| command | 16-bit encoding | fits? |
|---|---|---|
| VN | ARG0 `{…, nlog2[3:0], mode[1:0]}`; ARG1 `{dst, src}`; ARG2 xrf/eps | yes |
| VNW | ARG0 `ld_n[12:0]`, **no escape encoding** — 13 bits hold 4096 directly; ARG1 `{–, src}` | yes |
| ROPET / ROPE | ARG1 `{dst, src}` | yes |
| CONVW | ARG0 `{nch[13:0], first[13:0], sel[1:0]}` = 30 b; ARG1 `{–, src}` | yes |
| CONV | ARG0 `{nch[13:0], first[13:0]}` = 28 b; ARG1 `{dst, src}` | yes |
| GATE | ARG0 `{–, dst[15:0]}`; ARG1 `{src_a, src_b}`; ARG2 `{src_dt, src_A}` | yes, 16 spare |
| KVAP | ARG0 `{expbias[4:0], kvhead[1:0]}`; ARG1 `{src_v, src_k}` | yes |
| ATTN | ARG0 `kvhead[1:0]`; ARG1 `{dst, src_q}` | yes |
| **ALU**<!--cites:noquote--> | ARG0 `{spare[31:19], p0[16]@18, len[13:0]@17:4, aop[3:0]}`; ARG1 `{srcb, srca}`; ARG2 `{dst[15:0], p0[15:0]}` | yes — **one relocation**: `p0` is 17 b (`rtl/layer_chan.sv:744` `.cfg_p0(signed'(arg2[16:0]))`), so its top bit moves into ARG0's spare, which feasibility §2.4 proved is spare over **293,768** ALU dispatches |
| **DNST** | 6 scratch pointers × 16 + `head[4:0]` = **101 bits of 96** | **NO — over by 5** |

**DNST is the only command that does not fit, and the fix is to stop putting its
two scalar pointers in the arg words at all.** They are not general addresses.
Verified at the emitter: `ref/gen_layer_script.py:2019` emits

```python
M.dnst(h, QNS, KN, v_src, decay_base + h, beta_base + h, DO32)
```

> *(**Amended 2026-08-31 at G2a.** This block read
> `M.dnst(h, QNS, KN, v_src, GD + 16 + h, GD + h, DO32)` at
> `ref/gen_layer_script.py:1169` when the section was written, and the
> argument below turns on the SHAPE of those two pointers, not on their
> spelling. G2a fixed the wall-17 defect in that very line — the literal `16`
> was `LNH` — by making the SCA tile map the layout authority and exporting
> `beta_base` / `decay_base`. **The property this section needs is unchanged
> and is now explicit rather than incidental**: both pointers are still
> affine in the head index with stride 1 from a per-body base, which is
> exactly what lets §4.3 replace them with a base plus an implied stride.
> A first pass at this correction silenced the stale quotation with
> `<!--cites:noquote-->` instead of fixing it, which is why the marker is
> gone: an exemption is for source that no longer exists, not for a citation
> that has merely moved.)*

inside `for h in range(LR.LNH):` (`ref/gen_layer_script.py:2002`) — so the two
scalar pointers are **both affine in the head index with stride 1**, from a
per-body base. *(**Superseded 2026-08-31 at G2a**, and only in FORM: the
pointers read `a_dec = GD + 16 + h` / `a_beta = GD + h` from a base
`GD = SCA + 64` when this was written; G2a made the SCA tile map the layout
authority, so they are now `decay_base + h` / `beta_base + h` with
`decay_base = GD + LR.LNH` — see `ref/gen_layer_script.py:160-161`. The
affine-with-stride-1 property §4.3 derives its scalar-pointer base from is
unchanged, which is the whole point of the change: at LNH=32 the literal 16
was the wrong stride.)*  <!--cites:noquote-->
vector pointers are head-*independent* constants in the same call; only `src_v`
moves.

> **But that line is itself a wall-17 defect, and this spec was quoting it as
> proof without saying so.** `GD` is the **beta|decay** tile, `2·LNH` words wide
> (`ref/gen_layer_script.py:119`): betas at `GD + 0 … GD + LNH − 1`, decays at
> `GD + LNH …`. The `16` in `GD + 16 + h` **is `LNH`**, hard-coded. At **LNH=32**
> the decay half starts at `GD + 32`, so `GD + 16 + h` sweeps `GD+16 … GD+47`
> while the decays live at `GD+32 … GD+63`. **Every one of the 32 heads reads the
> wrong word**, not merely some: heads 0-15 land in the *beta* half, and heads
> 16-31 land in the decay half but **off by 16** — head 16 reads decay 0. *(An
> earlier revision of this box said "for `h = 0…15`", which understates the bug
> by half.)* It is a *silent wrong-value* bug of exactly the class §2 warns about
> ("9B is the dangerous geometry because it is well-behaved").
> **Correct form: `a_dec = GD + LR.LNH + h`.** Added to §7.1's census as a
> mandatory fix; the affine *structure* of the encoding below is unaffected —
> only the base is — but the fix must land before the base is read off the
> emitter.

So:

* **New layer CSR `DNSB` = `{a_dec_base[31:16], a_beta_base[15:0]}`**, written
  once per layer body by the movers (one CSRWR record per body, not per
  command), from which the hardware forms `a_dec = a_dec_base + head` and
  `a_beta = a_beta_base + head`. Two 16-bit adds with a 5-bit addend, in the
  DNST decode — off the lane datapath, read once per command.
* **DNST becomes** ARG0 `{spare[31:5], head[4:0]}`; ARG1 `{src_k, src_q}`;
  ARG2 `{dst, src_v}` — **69 of 96 bits, 27 spare**.
* **The coupling is mechanized — and the obvious mechanization is worthless, so
  it is specified precisely.** A self-consistency assert ("the `a_dec` I emitted
  equals the `a_dec_base + h` I programmed") **passes while both sides are
  wrong**: it would have sailed straight through the `GD + 16 + h` aliasing
  above, because the base and the pointer derive from the same literal. **The
  assert must check against the LAYOUT AUTHORITY**, not against itself — i.e.
  against the tile writer that *populates* beta and decay, in the pattern
  `tb/scripts/gen_seq_layer_script.py:206-227`'s `m_gate` makes explicit ("16
  sigmoid betas then 16 exp(-softplus) decays" into one `2·LNH` array). Concretely:
  the SCA tile map exports `beta_base`, `decay_base` and `LNH` as the single
  source of truth; `GATE`'s writer and `DNST`'s pointer both read them; and the
  assert requires `a_dec == decay_base + h` **with `decay_base` obtained from the
  map, not recomputed at the call site**. A perturbation of the map must make the
  assert fire — that is G3's negative control.
  **Sequencing, and it is not optional:** the authority named above,
  `tb/scripts/gen_seq_layer_script.py:206-227`'s `m_gate`, is **itself a §7.5-D
  defect site** — it hard-codes `np.zeros(32)`, `range(16)` and `out[16 + h]` for
  LNH=16. An assert anchored to an un-generalized authority would ratify the very
  layout it is meant to police. **So `m_gate` is generalized to LNH first, in the
  same G3 change and before the assert is switched on**, and the negative control
  is run against the generalized version. The site's *existing* assert shows
  the failure mode is already understood: it warns that an over-range head "would
  also carry into `a_dec` at `arg0[17:4]` and corrupt the pointer, not just the
  head" (`ref/gen_layer_script.py:624-627`).
* **Named fallback** if the affine relation ever has to be broken: a **fourth
  arg word** (`ARG3` at a free `layer_chan` CSR offset, mirrored in
  `rtl/seq_unit.sv`'s ARG shadow at `:1057-1061`). Cost is one extra CSRWR record
  per DNST command — 768 DNST/token at 9B (`f16`'s census structure: 24 DN
  layers × 32 heads) ≈ **6 KiB/token** against 3.9 GB/token of weights. Cheap,
  mechanical, and strictly larger a change than the affine map; taken only if
  needed.

Also moving with the address width, from feasibility §2.2: every internal
address signal in `layer_chan` (`sptr`, `hw_addr`, `sa/sb/sw_addr`,
`eng_sa/eng_swa`, `ld_src`, `dst_r`, `src2_r`, `alu_aa/ba/wa`, `bw_addr/br_addr`,
`wa_ptr`) and `rtl/vec_alu.sv:114-116`'s `cfg_srca/cfg_srcb/cfg_dst` go
[14:0] → [15:0]; SPTR (CSR 0x14) becomes `wdata[15:0]`; `seq_movers`'
`SCR_WORDS` and `cmd_saddr` follow; and **`LAYB_BASE` (`rtl/seq_unit.sv:169`,
`32'h0006_0000`) moves to a 256 KiB-aligned slot**, because the AXI segment
becomes exactly 256 KiB and must be range-aligned
(`rtl/seq_movers.sv:14-23`). `layer_chan`'s `s_axib` address grows 17 → 18 bits
and the IPI wrapper's `ADDR_WIDTH` with it.

#### S4 — the array is 65,536 words, fully backed, and there is no MLP chunking

Two candidate sizings:

| | array | BRAM (S, on §2.7's +28 tiles per 32K) | MLP chunking | unbacked hole |
|---|---|---|---|---|
| A | **65,536 words** | +28 RAMB36 over today; device **886.5 / 2,160 = 41.0 %** (**D**, §2.7) | **none needed** | **none** — the 16-bit address space is fully backed |
| B | 53,248 words (52K) | ~+17 RAMB36 | none needed | 12,288 words unbacked |
| C | 40,960 words (40K) | ~+7 RAMB36 | **3-way, mandatory** | 24,576 words unbacked |

**A is chosen.** Reasons in order of weight:

1. **It removes the 3-way MLP chunking work item entirely.** Chunking is not
   cheap and is not safe: `PEAK_MLP = max(ML_SG + FFN, ML_DDST + H)`
   (`ref/gen_layer_script.py:131`) has two terms and chunking shrinks the first
   twice as fast as the second, so the down-stage takes over as the peak —
   `docs/QWEN2B_SCRATCH_MAP.md:158-177` sets out that two-term structure and
   shows the terms **tie exactly at 2B** because `STGCH + H == FFN`; the phrase
   "chunking destroys the domination condition" is **not in that file** — it is
   `evidence/qwen_next/feas/scratch_peak.py:228`, quoted by feasibility §2.2 at
   `docs/QWEN35_NEXT_FEASIBILITY.md:351-352`, which attributes it to SCRATCH_MAP. *(An earlier revision of this
   spec inherited that mis-attribution; the warning is real, the quotation marks
   were pointed at the wrong file.)* And the feasibility study's own chunking
   numbers were **wrong twice** before `f03` corrected them (§2.2: "not the
   10,208 an earlier revision claimed", "not the '992 spare' the earlier revision
   reported"). A work item with that error history, removed for ~10 RAMB36 of
   2,160, is a good trade.
   *Carry the study's own warning with it:* `PEAK_DN` 33,824 equals the two-way
   MLP peak exactly, and feasibility §2.2 says plainly that this "is a
   coincidence of the arithmetic and not a shared cause" — so neither number
   moves the other.
2. **It removes the unbacked-hole hazard**, which is not hypothetical here: the
   study's standing hazard note (§2.10) is that "almost every envelope guard in
   the RTL is `` `ifndef SYNTHESIS `` sim-only… on silicon an out-of-envelope
   command wraps, aliases, or hangs — it does not report." A fully backed
   address space has no out-of-envelope scratch address to guard.
3. **BRAM is not the wall.** §2.7 costs the full 65,536-word array at 886.5 of
   2,160 tiles (**41.0 %**) device-wide *including* the conv bank growth, and
   the study's own verdict on that figure is "BRAM is not the wall."

**And the peak these three reasons rest on is the allocator's algebra, not a
probe.** Feasibility §6 item 4 says `scratch_peak.py` mirrors
`ref/gen_layer_script.py`'s allocation line-for-line and reproduces the committed
0.8B and 2B maps exactly, and that the empirical high-water probe **was not
re-run** for the new geometries. **But the probe is not missing, and an earlier
revision of this section said it was.** `evidence/qwen2b/ra/scratch_probe.log`
**is committed** (5,139 B, in `git ls-files`) and records
`MEASURED PEAK=16384  DERIVED PEAK=16384` at 0.8B and
`MEASURED PEAK=25600  DERIVED PEAK=25600  SCRATCH=32768  headroom=7168` at 2B.
What was never committed is only the driver (`probe_map` .py, which exists at no path in the tree) — and that is
**reproduced verbatim in the log's own appendix** (`evidence/qwen2b/ra/scratch_probe.log:27`). So re-running the
probe at 9B is **cheap**: lift the appendix, run it under `FABLE5_MODEL=9b`,
compare. **G2 does exactly that** and records `MEASURED` beside `DERIVED`; if
they disagree, the array size is re-derived before G3 freezes it. Sizing to
65,536 rather than to 50,208 + ε remains a deliberate hedge — 15,328 words of
margin over a derived number — but it is a hedge against re-tiling, not against
an unavailable measurement.

> **S4 supersedes one line of the ledger's mandatory list.** `progress.md:116`
> records D1's mandatory RTL lines as including "**3-way MLP scratch
> chunking**". That entry was written when the scratch array was assumed to stay
> at a size that forced chunking. **S4 removes the work item, not the
> requirement it served** — the 9B unchunked peak of 50,208 words is *inside*
> the 65,536-word array, so the MLP does not need chunking to fit. Nothing about
> the geometry changed; the container did. Stated here explicitly so nobody
> reconciles the two documents by re-adding the chunker.

**Watch item, carried honestly:** the 2B spec flagged SLR1 BRAM at 70.2 %
post-widening as "the top timing risk", and this doubles the scratch again.
**Per-SLR BRAM is a G5 floorplan input, not a device-total question** (§6).

### 4.4 W4 — the residual container

**The measurement** (`LADDER.md` §4, the committed `res_scale` sweep, six
teacher-forced steps per setting):

| S | top-1 | \|x\|max | residual clips |
|---|---|---|---|
| 4 — the 2B RULED default | 4/6 | 32768 (rail) | 84 |
| 2 | 6/6 | 32768 (rail) | 22 |
| **1 — no rescale at all** | **6/6** | 32767 | **1** |

**At H=4096 the raw residual reaches the Q7.8 rail with no rescale applied at
all, so no power-of-two `res_scale` removes the clipping.** The full 168-step
runs at S=1 still clip **30** (W8) / **23** (W4+GPTQ). The knob has run out; the
2B campaign's S=8 → S=4 re-ruling does not continue.

#### S2 — saturation is accepted. The rail is not widened.

The argument, in the order it should be read:

1. **The measured fidelity was taken *with* the rail saturated, and it is
   good.** 95/108 top-1, rank max 5, top-5 3.69, at `|x|max 32767`. That is
   **better than the 2B W8 point that shipped** (90/108, rank max 37) and
   produced coherent chat on silicon. These are not projections of a
   hypothetical unsaturated machine; they are the machine.
2. **Saturation is bounded and sign-preserving**, not wrapping —
   `rtl/fx_pkg.sv:31` `if (v < -64'sd32768) return -16'sd32768;`.
3. **The other clip site is a geometry property, not a container property.**
   The dominant int16-dequant clip is the 12288×4096 FFN matvec: 10,897 of 132 M
   at W4+GPTQ vs 11,240 at W8 — **0.008 %** — and `LADDER.md` §4 says explicitly
   it "is a property of the geometry, not of the weight format". Widening the
   residual would not change it.
4. **Widening is the largest single change anyone has proposed in this
   campaign.** The residual lives in the int16 scratch rail
   (`rtl/layer_chan.sv:503-504`, `logic signed [15:0]`), so a wider container
   means: doubling the scratch **again** on top of §4.3's doubling, re-opening
   `vec_alu`, `vecnorm_unit`, the movers, the DYNQ8 exponent path, the 16-bit
   `SWIN` CSR, and every emitter. That is strictly larger than the 16-bit
   scratch ISA, which is already this campaign's XL item.
5. **U4 does not change this.** The cost above is intrinsic to the datapath
   width; it was never a back-compatibility cost.

**Carried caveat, in the honest form Track L used:** `LADDER.md` §6.3 says treat
the 95/108 as an upper bound on what today's int16 Q7.8 residual delivers at
H=4096, "not as clean measurements", because the container is at its limit. The
correct reading is **fragile, not wrong** — a shift in the activation
distribution tips more clips. G6's board census records the clip counters so the
fragility is observed, not assumed.

> **S2 supersedes a ledger-mandatory line, and it goes back to the user as O5.**
> `progress.md:116` records D1's mandatory RTL lines as including "**residual
> container (S-knob exhausted at S=1)**" — i.e. the container was ruled a
> mandatory *change*. S2 answers that line with **"measured, and the answer is to
> accept the rail"**, which is a different disposition from the one the ledger
> records, taken on evidence the ledger line predates. Given the same S4 treatment
> here so the two documents cannot be reconciled by silently re-adding a wider
> rail — **and surfaced as O5**, because the user ruled on a same-shaped
> quality-versus-cost tradeoff in this same session (declining W8) and should be the one
> to ratify this one rather than discover it in a gate doc.

#### The free rider U4 unlocks: `RS_F 8 → 7`

The residual's **binary point** is not the residual's **width**. `RS_F = 8`
(`ref/layer_fixed.py:36`, int16 Q7.8) is a **module-level frozen constant**
re-exported to the emitters (`ref/gen_layer_script.py:41`) and mirrored in `sw/`
(`sw/head_cache.py:105`, asserted at `sw/head_cache.py:638-639` and `sw/chat_seq.py:4941-4942`) — **the RTL
is format-agnostic and takes the binary point as a runtime shift.** The one
exception is `rtl/conv4_silu.sv:3` / `:50`, which bakes the shift as a literal 9 — `rtl/conv4_silu.sv:50`
`pre = rshr64(64'(acc1), 9);          // RS_F + CW_F - 12 = 9`. So moving to **Q8.7** buys one bit of top-end headroom for
one bit at the bottom, at a cost of **one RTL literal and a set of host
constants**.

> **But it is GLOBAL today, and that is a conflict this spec has to resolve
> rather than step over.** `RS_F` is one module-level name shared by every
> geometry, so moving it to 7 changes **every emitted byte at 0.8B and 2B as
> well**, and §8 G2 asserts that `evidence/qwen2b/rc/t4_bytes_unmoved.sh` still
> regenerates the 2B artifact set byte-for-byte. Those two statements cannot both
> hold. **Resolution: `RS_F` becomes model-selected, not global** — so 0.8B/2B
> keep `RS_F = 8` and keep their byte-lock while 9B may take 7. The mechanism is
> NOT the `H`/`FFN` shape (those are verbatim HF `text_config` fields; no config
> JSON carries a repo-local format knob): the precedent is **`res_scale`** — a
> generator choice carried as a CLI flag (`ref/gen_model_script.py:401-406`) and
> written into the manifest, the way `emb_row_bytes` travels (§5.3). `RS_F` rides
> the same path: chosen at emit time, recorded in the manifest, consumed from it
> by the host. The census gains the two hard-coded consumers that must then read
> it from the manifest: the `RS_F` asserts at `sw/head_cache.py:105` /
> `sw/head_cache.py:638-639` and `sw/chat_seq.py:4941-4942`. It is small, and it removes
> the conflict at the root instead of arbitrating it. §8 G2a/G3 carry the
> sequencing.

Under the old contract this was unthinkable — it moves every frozen stream.
Under U4, with `RS_F` per-model, it is a one-line experiment. **It rides on G1**:
measure `RS_F ∈ {8, 7}` at 9B on the same six-step smoke, and if Q8.7 removes the
clipping without costing top-1, take it. If it costs top-1, do not. Either way
the answer is recorded rather than assumed.

> **AMENDED 2026-08-31 (A1.8) — `RS_F` STAYS 8, and the reason is that the
> rider turned out to be CONTAINER-DEPENDENT.** The rider ran twice and the two
> results disagree in sign, which is the finding:
>
> | container it was measured on | clipping | `|x|max` | top-1 | rank max |
> |---|---|---|---|---|
> | `int8:6` global (a law that FAILED) | 15 → **0** | 32767 → 27,692 | 72 → **73** | 214 → 335 |
> | `int8e` per-row (the law option A would have shipped) | 23 → **0** | 32,767 → 28,863 | 94 → **89** | 13 → **18** |
>
> At the global container it looked free, and this spec's decision table read
> *take it*. At per-row it **costs five tokens and worsens rank max**, so the
> ratified O5 condition — *take Q8.7 only if it removes the clipping WITHOUT
> costing top-1* — **rejects it**. The generalisation from the global row does
> not transfer, and the run that refuted it also refuted the hypothesis behind
> it: removing every clip did not fix rank max, so the per-row container's rank
> behaviour came from **state quantization, not from the residual container**.
>
> **Its sign under `int16` — the container that actually ships — cannot be
> inferred from either row and is UNMEASURED.** That is a genuinely open
> question, not a formality, and it is **cheap**: `RS_F` is an env knob, not a
> source edit, so it does not move the quantizer digest and runs on the warm
> cache at **≈ 3.8 h** for one 168-step point. **The shipped value is 8 until
> something measures otherwise**; §8 G2c may take the measurement if the user
> wants it, and if it is not taken, the gate doc says so rather than implying
> the question was settled.
>
> **What does NOT change:** the one RTL literal the move would touch is still
> `rtl/conv4_silu.sv:50`, and `RS_F` still becomes model-selected via the
> manifest (that relocation is a G2a work item on its own merits — it removes a
> global constant that 0.8B/2B and 9B would otherwise have to share).

> ## SUPERSEDED 2026-09-01 (A2) — THE MEASUREMENT WAS TAKEN AND `RS_F = 7` IS ADOPTED
>
> The block above is right about everything except its disposition, and it is
> worth saying which parts survive, because they are what make the reversal
> sound rather than arbitrary:
>
> * **"Its sign under `int16` cannot be inferred from either row" — CORRECT,
>   and it is exactly why the two earlier rejections stand unretracted.** The
>   sign is container-dependent: neutral at global, −5 top-1 at per-row,
>   **+3 top-1 at `int16`**. Three containers, three answers.
> * **"It is cheap: an env knob, not a source edit" — CORRECT and demonstrated.**
>   The measurement cost 3.9 h on a warm cache against the ≈ 3.8 h priced,
>   the quantizer digest did not move, both caches HIT, and
>   `--wq-cache-verify` proved byte-identity under the new value.
> * **"The shipped value is 8 until something measures otherwise"** — something
>   measured otherwise. **`RS_F = 7`.**
>
> **The full result and the ratification argument are in §0b.** The headline:
> residual clips **23 → 0**, `|x|max` off the 32,767 rail at **29916**, top-1
> **95 → 98**, rank max and top-5 overlap **unmoved**, repeat byte-identical.
> The ratified **O5** condition — *remove the clipping without costing top-1* —
> is met.
>
> **What this changes downstream**, all of it small and most of it already
> built (§0b's A2 table): `rtl/conv4_silu.sv:50`'s baked shift **9 → 8**, which
> §4.1 W1′ now owns; the 9B manifest carrying `rs_f: 7` through the existing
> caller-gated path; and **nothing on the host**, because G2a made those
> constants derived rather than literal — see §0b's A2.3 box before touching
> any of them, because re-literalising `HEAD_LOGIT_EXP0` to −21 would break
> every byte-locked artifact.
>
> **One caveat the adoption carries, and it is not a blocker.** 98/108 is the
> **fixed-point fidelity axis** — 108 teacher-forced steps over four prompts,
> with run-to-run spread measured at exactly zero. It is **not** a corpus-scale
> result: nothing has scored `RS_F ∈ {8, 7}` over the pinned 24,528-position
> corpus. And the float ladder cannot supply that number in the form a reader
> would expect — `ref/perplexity_eval.py` measures **weight damage only, with
> float compute**, and touches `RS_F` at exactly one place, the int16
> embedding-table round trip (`ref/perplexity_eval.py:474`, documented at
> `ref/perplexity_eval.py:329`). A PPL point at 7 would therefore price the
> **embedding rounding**, not the residual rail. §8 G4 carries widening the
> fidelity measurement as an available run; it is not a gate.

### 4.5 W5 — `MAX_NG = 96`, the SHAPE field, the scale beats, and the XWIN aperture

> ### PRE-G3.3 ROWS, KEPT AS THE RECORD — dated note 2026-09-02 (Task 9)
>
> Rows here marked `<!--cites:noquote-->` quote **source that G3.3 DELETED**,
> not source that merely moved: the 6-bit `cfg_ng` / `x_line` / `g_q…g5_q` / `r_g` declarations, the `wbeats` and `ng7` wires, the 1536-word `x_mem`, and the 6 KiB XWIN decode with its 11-bit pointers, together with the `cfg_w8` / `cfg_g64` ports and everything that selected on them, SHAPE bits 28 and 29, and the W8-envelope adder tree.  They are kept verbatim, because they
> are the record of what the pre-G3.3 tree said and the argument they support
> rests on them (§0: nothing is deleted or struck).  The exemption marker is
> used for exactly the reason §7.6 gives — *"an exemption is for source that
> no longer exists, not for a citation that has merely moved"* — and every
> citation that had merely MOVED was RENUMBERED instead, mechanically, by
> `evidence/qwen9b/o3/o3_cite_drift.py --base a08a90b`.
> **The post-G3.3 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_3_MATVEC.md` §11.1.**

`down_proj` has `K = FFN = 12288`, so `ng = K/128 = 96` — which overflows the
6-bit SHAPE field (max 63) before storage is even considered. The design
documented this cliff when W8 was added
(`rtl/matvec_engine.sv:10-13`: *"redefining ng as the W8 beat count would need  <!--cites:noquote-->
96 > 63 at K = 6144 and overflow the 6-bit SHAPE field"*). At FFN 12288 the
natural `ng` **is** 96 and there is no encoding trick left.

Verified sites:

| site | today | needed | verified |
|---|---|---|---|
| `rtl/matvec_engine.sv:209` `parameter int MAX_NG = 48, // max groups/row (K <= 6144)` | 48 | **96** | exact |  <!--cites:noquote-->
| `rtl/matvec_engine.sv:216` `input wire [5:0] cfg_ng,` | 6 b | **7 b** | exact |  <!--cites:noquote-->
| `rtl/matvec_engine.sv:219` `x_mem [32][MAX_NG]` | 1536 words | **3072** | exact |
| `rtl/matvec_engine.sv:547-548` `logic signed [20:0] acc_bank_lo [2][MAX_NG];` and its `_hi` twin | 48 | 96 | exact |  <!--cites:noquote-->
| `rtl/matvec_engine.sv:273` `x_waddr[10:5]` line index | 64 addressable / 48 backed | **96 lines → 12 b** | study |  <!--cites:noquote-->
| `rtl/matvec_engine.sv:291` `logic [5:0] x_line;` | 6 b | **7 b** | exact |  <!--cites:noquote-->
| `rtl/matvec_engine.sv:361` `g_q`, `:405` `g1_q`, `:450` `g2_q`, `:468` `g3_q`, `:489` `g4_q`, `:522` `g5_q` — the ng-unit index travelling with each pipeline stage, all `logic [5:0]` and all commented *"0..NG-1 <= 47"* | 6 b ×6 | **7 b ×6** | exact |  <!--cites:noquote-->
| `rtl/matvec_engine.sv:619` `r_g` retire index | 6 b | **7 b** | study |  <!--cites:noquote-->
| `rtl/matvec_engine.sv:311` `wire [6:0] ng7 = {1'b0, cfg_ng};` | 7 b | **8 b**, or deleted with `cfg_ng` already 7 b | exact |  <!--cites:noquote-->
| `rtl/matvec_engine.sv:633-634` `sc_idx_a/b` — the NSCAL:1 scales mux fed directly by `r_g` (*"Do not add logic between them"*) | 7 b, `cfg_g64`-selected | **7 b, g64 branch deleted** (§5.2); widens with `r_g` | exact |  <!--cites:noquote-->
| `rtl/matvec_chan.sv:571` and `rtl/seq_movers.sv:195` `XWIN_WORDS` | 1536 | **3072** | exact; `rtl/matvec_chan.sv:566-568` documents the 6 KiB window |  <!--cites:noquote-->
| `rtl/matvec_chan.sv:613-614` the XWIN decode | 6 KiB | **12 KiB** | exact |  <!--cites:noquote-->
| `rtl/matvec_chan.sv:573` `wb_ptr`, `:230` `xptr` | 11 b | **12 b** | exact |  <!--cites:noquote-->
| `rtl/matvec_engine.sv:716-719` the `cfg_ng` envelope `$fatal` | sim-only | keep, and see §5.4 | exact |

> **Two rows an earlier revision had wrong, and both were W8 arithmetic in a
> build that strips W8.** It listed `g_cnt` (`rtl/matvec_engine.sv:281-283`) going 7 b → 8 b "because  <!--cites:noquote-->
> 2·96+2 = 194", and `wbeats` (`rtl/matvec_engine.sv:294`) going 7 b → 8 b. Both are artefacts of  <!--cites:noquote-->
> the W8 beat doubling this spec deletes in §5.1. In **W4 only**, `wbeats` *is*
> `cfg_ng` — the signal exists solely as the `cfg_w8 ? {cfg_ng,1'b0} :
> {1'b0,cfg_ng}` mux and goes away with the mode — and `g_cnt` runs
> `0 … wbeats + n_scale_beats − 1 = 96 + 3 − 1 = 98`, which **fits the existing
> 7 bits** (max 127). **Neither widens.** The RTL's own comment *"7 bits:
> 2*MAX_NG + 2 = 98 at MAX_NG = 48"* is a W8 statement and should be re-derived,
> not scaled.

**The XWIN aperture belongs INSIDE this wall's table, not outside it** — which is
the study's own framing, arrived at by correcting itself. Feasibility §2.5 says
an earlier revision claimed the aperture "does have room" on the grounds that the
64 KiB per-channel stride is not the constraint; the correction is that **the
*decode* is**, and so "the row belongs in the table above, not outside it".
*(An earlier revision of this spec flattened that into "the item most easily
missed", which loses the point: it was not overlooked, it was reasoned about and
got wrong.)* `rtl/matvec_chan.sv:613-614` hard-wires exactly 6 KiB:  <!--cites:noquote-->

```systemverilog
wb_win <= (s_axib_awaddr[15:13] == 3'b010)
          && (s_axib_awaddr[12:11] != 2'b11);
```

which admits `0x4000…0x57FF` and nothing above it, with `wb_ptr <=
s_axib_awaddr[12:2]` on the same line. At `MAX_NG = 96`, XWIN is **3072 words =
12 KiB**, which overflows the decode *and* both pointers. So `matvec_chan`'s AXI
decode widens too — in the same timing-sensitive block as everything else in
this wall. TB twin: `tb/seq_stub_mvchan.sv:118` `logic [10:0] xptr;` (§7.5).  <!--cites:noquote-->

**Scale beats — CONFIRMED, and more precisely than the study stated it.**
`rtl/matvec_engine.sv:312-313`:  <!--cites:noquote-->

```systemverilog
wire [1:0] n_scale_beats = cfg_g64 ? 2'((ng7 + 7'd15) >> 4)
                                   : 2'((ng7 + 7'd31) >> 5);
```

with `scale_beat_idx` at `rtl/matvec_engine.sv:320` likewise two bits. At the **g128** cadence  <!--cites:noquote-->
`n_scale_beats = ceil(ng/32)`, and the 9B row shapes are `K ∈ {4096, 8192,
12288}` → **`ng ∈ {32, 64, 96}` → `n_scale_beats ∈ {1, 2, 3}`** and
`scale_beat_idx ∈ {0, 1, 2}`. **Both fit two bits at every 9B row.** *(This is
the confirmation the brief asked for; the source is feasibility **§2.5**, not
Track P — Track P is the placement experiment and does not have a §2.5.)*

**And GPTQ needs no cadence change.** Track L's recommended point is
`w4g128gptq`: "identical wire format, identical b/w, identical bytes/token as
the shipped W4" (`LADDER.md` §0.2), asserted to the byte in all seven classes at
all four geometries by `bytes_per_token.py --selftest` section E-bis
(`LADDER.md` §5b). The feasibility study's warning that *"GPTQ costs the board
nothing, true at 2B, is not true at 4B/9B"* (§2.5, §4.4) applies **only to the
g64 cadence**, which this build does not carry (§5.2). At g128 + GPTQ the board
cost is **zero**.

**Timing.** `matvec_engine` owned build_034's worst 22 endpoints (24 of 50,
`docs/QWEN2B_QUANT_STUDY.md` §1.1) and build_035 closed at WNS 0.000 with zero
margin. This wall re-opens that block, and it is a bigger change than the W8
mode was. §5.1 is the countervailing item: **the same block gets 5,826 LUTs per
channel *smaller* at the same time.**

### 4.6 W6 — the remaining walls, at W4

> ### PRE-G3.1 ROWS, KEPT AS THE RECORD — dated note 2026-09-01 (Task 7)
>
> Rows in this section marked `<!--cites:noquote-->` quote **SEQ_ISA v1.7
> source that G3.1 DELETED**, not source that merely moved.  They are kept
> verbatim, because they are the record of what the pre-G3 tree said and the
> argument this section makes rests on them (§0: nothing is deleted or
> struck).  The exemption marker is used for exactly the reason §7.6 gives —
> *"an exemption is for source that no longer exists, not for a citation that
> has merely moved"* — and every citation that had merely MOVED was
> RENUMBERED instead, mechanically, by
> `evidence/qwen9b/o3/o3_cite_drift.py --base d2d774b`.
> **The post-G3.1 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_1_ISA.md` §15.**

### 4.6 W6 — the remaining walls, at W4

> ### PRE-G3.4 ROWS, KEPT AS THE RECORD — dated note 2026-09-02 (Task 10)
>
> Rows in this section that name a `rtl/layer_chan.sv`, `rtl/dn_step.sv`,
> `rtl/gate_unit.sv`, `rtl/seq_unit.sv`, `tb/tb_gate_unit.sv` or
> `sw/hwmap.py` line quote **source that G3.4 REWROTE or DELETED**, not
> source that merely moved: the 9-bank / 3-bank hand-split DN and KV
> expressions, the 4-bit `dn_head_hw` and 1-bit `kvhead_hw` datapath
> slices, `gate_unit`'s `NH = 16` and its 4-bit `w_addr`, the 18 × 6144
> conv banks, `EMBLOG2_RST = 5'd11`, `conv4_silu`'s shift 9 and the whole
> `` `ifndef SYNTHESIS `` datapath-envelope block.  They are kept
> verbatim, because they are the record of what the pre-G3.4 tree said and
> the argument this section makes rests on them (§0: nothing is deleted or
> struck).  Every citation that had merely MOVED was RENUMBERED instead,
> mechanically, by `evidence/qwen9b/o3/o3_cite_drift.py --base 8138d66`.
> **The post-G3.4 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_4_LAYER.md` §11.1.**

Walls the census lists (§2.1) that are still live at 9B on the W4 path, each

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
with its verified citation:

| wall | site | change |
|---|---|---|
| **3** ALU `cfg_len` (the 2B campaign's R-b wall-6 redux) | `rtl/vec_alu.sv:112` `input wire [12:0] cfg_len`, wired at `rtl/layer_chan.sv:757` `.cfg_len(arg0[16:4])`; mirrored `ref/gen_layer_script.py:696`, `ref/seq_format.py:1324` | 13 → **14 b** (`arg0[17:4]`, max 16383). FFN 12288 exceeds 8191 and the failure mode is **silent truncation** — the 2B burned this once at 12 bits. `arg0[17]` proven spare over **293,768** ALU dispatches in the reproducible committed scope (feasibility §2.4). ~16 sites; `tb/legacy/vec_alu_legacy.sv` stays frozen |  <!--cites:noquote-->
| **9** `kvhead` | `rtl/layer_chan.sv:786` `logic kvhead_r;`, `:1276` `kvhead_r <= arg0[0];`, KV write address `rtl/layer_chan.sv:1931-1932` inside an 11-bit `kv_waddr` (`rtl/layer_chan.sv:603`), in-bank 12-bit at `rtl/layer_chan.sv:787`, append counters at `rtl/layer_chan.sv:329`, and the structural statement at `rtl/layer_chan.sv:572` *"2 kvheads x 2 banks x 512 x 2048b"* | 1 → **2 b**, `tcnt_bank` → `[8][4]`. The 12-bit in-bank URAM address has no spare, so **KV capacity per bank doubles or T halves** — resolved by §4.1's 8-bank re-banking. **See the field-width trap below** |  <!--cites:noquote-->
| **10** `dn_head` / `gate_unit` NH | `rtl/layer_chan.sv:610` declares it and `rtl/layer_chan.sv:1275` `dn_head <= arg0[3:0];` latches it; `rtl/gate_unit.sv:13` `parameter int NH = 16,`, instantiated with no `NH` override at `rtl/layer_chan.sv:501-502`, `w_addr` 4-bit at `rtl/gate_unit.sv:27`; 16/32/16 literals at `rtl/layer_chan.sv:1432`, `rtl/layer_chan.sv:1703`, `rtl/layer_chan.sv:1708`, `rtl/layer_chan.sv:1713`; 32-element store bound `rtl/layer_chan.sv:1568` | 4 → **5 b**, **NH = 32**. Host twin: `ref/gen_layer_script.py:579` `DNST_HEAD_MAX = (1 << 4) - 1` |  <!--cites:noquote-->
| **11** CONV `cvi` count | `rtl/layer_chan.sv:1803` `if (cvi == arg0[25:13])` compares **before** incrementing and genuinely cannot express 8192 — **this one is the wall**. `rtl/layer_chan.sv:1850` and `rtl/layer_chan.sv:1866` (the CONVW twin) compare `wi + 1` in 13-bit arithmetic, so at `wi = 8191` the sum wraps to 0 and a field value of **0 already encodes 8192** — an unspent escape, the same trick `ref/gen_layer_script.py:512-516` documents for VNW | widen `cvi` to **14 bits**, which represents 8192 directly (max 16383) — **and retire the CONVW wrap escape with it**, for the same reason §4.3 retires VNW's: an escape encoding that the width no longer needs is a trap, and this one is *accidental* rather than designed. `0` should mean 0 and be refused. Emitter assert replaces it |  <!--cites:noquote-->
| **8/16** conv banks | `rtl/layer_chan.sv:566-568` `for (gc = 0; gc < 18; gc++) … wm [6144]`, `sm [6144]` | **24 banks × 8192**. BRAM, costed inside §2.7's 886.5 tiles |

> **The (feasibility-study) wall-9 field-width trap, and it is shaped like the
> 2B campaign's R-b wall 6.** The host reads
> **four** bits of `kvhead` where the RTL reads **one**: `ref/seq_model.py:629-630`
> `M.kvap(a0 & 0xF, …)` and `ref/seq_format.py:1586-1587`
> `{"kvh": c_at[1] & 0xF, …}`, against `rtl/layer_chan.sv:1276`
> `kvhead_r <= arg0[0];`. **That is dead width today, not a live bug**, because
> the emitter refuses first: `ref/gen_layer_script.py:1075` `KVH_MAX = _KVH - 1`
> with `Mach._kvh_isa` asserts at `ref/gen_layer_script.py:1251` (KVAP) and
> `ref/gen_layer_script.py:1344` (ATTN).
> *(**Amended 2026-08-31 at G2a.** The guard read `KVH_MAX = (1 << 1) - 1`
> when this was written — one bound doing two jobs. G2a split it: `KVH_MAX` is
> now the GEOMETRY bound (`NKV - 1`, so 3 at 4B/9B) and `ARG0_KVH_BITS = 1` is
> what the ARG word can carry, asserted separately by `_kvh_isa` with a message
> naming this wall. The refusal below is therefore still live and still
> specific — it just no longer conflates "this model has 4 KV heads" with
> "this ISA can name 2".)*
> **At NKV=4 it stops being dead**, and the failure mode if the guards
> are relaxed without the RTL is **silent**: `arg0[0]` truncates, so kvheads 2
> and 3 alias onto banks 0 and 1 and share their append counters, while the
> reference model faithfully models four independent caches. Divergence, not an
> error. So this row is a **lockstep** change — `KVH_MAX`, both asserts, the RTL
> field, `tcnt_bank`, the KV banking, and the reference model's own storage
> (`ref/gen_layer_script.py:284-286` sizes `kc`/`vc`/`T` as exactly `[6][2]`) all
> move together, and G3's encoder-vs-decoder mechanization (§7.6) is what proves
> they did. This is the same shape as the ALU-count hole feasibility §2.4 flags
> at `sw/chat_seq.py:1749`, where the host already decodes 14 bits against a
> narrower hardware field and is benign "only because both emitters refuse".

**Not on this build's list, because U2 chose W4:** everything in the census that
is W8-specific. See §5.1.

**Verified safe at 9B, no change** (feasibility §2.5, accepted): `ROW_W = 16`
row counters; the 48-bit row accumulator `p_acc` (the RTL's own note at
`rtl/matvec_engine.sv:126` gives 44 b at K=6144, so ≈45 b of 48 at K=12288 —  <!--cites:noquote-->
the study's arithmetic on the RTL's figure, not a measurement, and **G4's
`audit_ranges`/sim is where it is checked**); the 4096-row RES window; and the
18-bit AMAX index (vocab 248,320 of 262,144 — 13,824 spare).

---

## 5. Optimizing for 9B — the simplifications U4 enables

Hunted deliberately, with savings attached. Two are large, three are small, two
were hunted and **rejected**.

### 5.1 S5 — strip W8 engine mode. −23,304 LUTs device-wide.

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

**Evidence, measured OOC on the real part** (`evidence/qwen2b/rc/TIMING_035.md`
§8a, one `matvec_chan` = engine + streamer + shim, out-of-context):

| resource | 034 (W4) | 035 (W8) | delta |
|---|---|---|---|
| **CLB LUTs** | 14,023 | **19,849** | **+5,826 (+41.5 %)** |
| — LUT as Logic | 10,318 | 16,143 | +5,825 (+56.5 %) |
| **CARRY8** | 772 | **1,269** | **+497 (+64.4 %)** |
| CLB Registers | 10,590 | 11,924 | +1,334 (+12.6 %) |
| LUTRAM / BRAM / DSP | — | — | **0 / 0 / 0** |

> "**The W8 lane array costs +5,826 LUTs per channel, ×4 channels = +23,304 LUTs
> device-wide.** All of it is `LUT as Logic` + `CARRY8`."

That block is the proximate cause of build_035's placement crisis, and
TIMING_035 §9's remediation list names this exact structure as option **(e)**:
*"Revert the operating point. V4/V4gptq needs no W8 lane array at all."* **Read
that correctly**: §9(e) was a proposal to reopen the **2B's** gate-D pick in
order to escape the 2B's timing crisis, and it was **not taken** — the 2B shipped
V5 W8. U2 is an independent **9B** format decision taken on quality-per-byte
grounds in this same session, not an acceptance of §9(e). What the two share is the
structure they land on, and therefore the number: **§8a's measurement is what
prices the saving, and it prices it exactly.**

What goes, in `rtl/matvec_engine.sv` and `rtl/matvec_chan.sv`: the `cfg_w8` port
(`rtl/matvec_engine.sv:221`), the 8-bit operand mux and the widened adder tree  <!--cites:noquote-->
(`rtl/matvec_engine.sv:424-427`) and the stage widths tabulated at  <!--cites:noquote-->
`rtl/matvec_engine.sv:101-119`, the half-beat toggle  <!--cites:noquote-->
(`rtl/matvec_engine.sv:294` `wbeats`, `rtl/matvec_engine.sv:297` `w8_phase`,  <!--cites:noquote-->
`rtl/matvec_engine.sv:365` `ph_q`, `rtl/matvec_engine.sv:383`), and SHAPE bit 29  <!--cites:noquote-->
(`rtl/matvec_chan.sv:18` `{2'b0, w8[29], g64[28], nrows[27:12], sh[11:6], ng[5:0]}`,  <!--cites:noquote-->
decoded at `rtl/matvec_chan.sv:340` `csr_static_w8 <= wdata_q[29];`).  <!--cites:noquote-->
Also retired: the open follow-on "W8 CSR-decode
range checks" (`docs/HISTORY.md:781`) becomes moot.  <!--cites:noquote-->

**Host-side W8 stays** (§3.3) — `build_035` still serves the 2B in W8 and needs
its host model. The strip is RTL-only.

### 5.2 S6 — strip g64 mode. SHAPE bit 28 freed, scale-beat generality removed.

`n_scale_beats` is 2 bits, and at ng=96 the **g64** cadence needs 6 — it
overflows (feasibility §2.5). Keeping g64 therefore is **not free**: it costs a
3-bit `n_scale_beats`/`scale_beat_idx` pair inside the block §4.5 is already
re-opening, and a wider `last_scale_g` with it.

The spec strips it, on U2's own logic: g64 costs **124 MB/token** at 9B
(4,215,799,808 − 4,091,805,696 bytes, `LADDER.md` §2) for **0.35 pp** of float
PPL, where the user has just declined W8 — a 2.51 pp step — on a byte argument.
Stripping frees SHAPE bit 28 as well as bit 29, so `cfg_ng` widens into bit 30
with **three** spare bits left, not one.

`sw/hwmap.py:150` and `:528`'s `assert not (w8 and g == 64)` become vacuous for
this build and stay (they still guard the old bitstreams' host path).

**This is O2.** It forecloses `LADDER.md` §6.4's named gap — nobody has measured
whether g64+GPTQ's 0.35 pp survives into fixed point at 9B — without an RTL
re-add. The spec judges the byte frontier decisive and flags the foreclosure for
the user rather than burying it.

### 5.3 S8 — EMBLOG2 reset 11 → 13

> ### PRE-G3.4 ROWS, KEPT AS THE RECORD — dated note 2026-09-02 (Task 10)
>
> Rows below marked `<!--cites:noquote-->` quote **source that G3.4
> REWROTE or DELETED**, not source that merely moved: the 9-bank /
> 3-bank hand-split DN and KV expressions, the 4-bit `dn_head_hw` and
> 1-bit `kvhead_hw` datapath slices, `gate_unit`'s `NH = 16` and its
> 4-bit `w_addr`, the 18 × 6144 conv banks, `EMBLOG2_RST = 5'd11` and
> the vector generator's `EMB_ROW_LOG2 = 11`, `conv4_silu`'s shift 9,
> and the whole `` `ifndef SYNTHESIS `` datapath-envelope block.  They
> are kept verbatim, because they are the record of what the pre-G3.4
> tree said and the argument they support rests on them (§0: nothing is
> deleted or struck).  The exemption marker is used for exactly the
> reason §7.6 gives — *"an exemption is for source that no longer
> exists, not for a citation that has merely moved"* — and every
> citation that had merely MOVED was RENUMBERED instead, mechanically,
> by `evidence/qwen9b/o3/o3_cite_drift.py --base 8138d66`.
> **The post-G3.4 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_4_LAYER.md` §11.1.**


The CSR **stays runtime**: `rtl/seq_unit.sv:346` `EMBLOG2_RST = 5'd13` and  <!--cites:noquote-->
`rtl/seq_unit.sv:347` `EMBLOG2_MIN = 5'd8, EMBLOG2_MAX = 5'd13`;
register at `rtl/seq_unit.sv:356`, used in the pure
barrel shift at `rtl/seq_unit.sv:933-934`, range-rejected with `$error` at `rtl/seq_unit.sv:1329-1333`. Cost of
keeping it is a 5-bit register and a shift — nothing. But the **reset value** is
a genuine 9B-only win. *(**Citation note, 2026-09-10.** The three pointers above are
re-anchored to HEAD. The reset value read `5'd11` when this section was written; the
9B change argued for here has landed, which is why the same line now reads `5'd13`.)*

The 2B campaign's R-c wall-8 lesson is that the BFM and TB must program EMBLOG2
**from the artifact**, and the census still holds a live site that never learned
it: `tb/scripts/gen_seq_unit_vectors.py:81-83` `EMB_ROW_LOG2 = 11` — "the TB set  <!--cites:noquote-->
only ever proves EMBLOG2 11" (feasibility §2.10; feasibility's own citation for
this named the dead near-copy `tb/scripts/gen_seq_vectors.py:62`, which §7.5 E
DELETED at G2a on 2026-08-31 —
the live sibling above is where the fix lands). Moving the reset to **13**
converts that class of bug from *silently addressing the wrong row* into
*right by default*.

Belt and braces, both required at G3/G6: the emitter writes `emb_row_bytes` into
the manifest (`ref/gen_model_script.py:618`) and the host programs EMBLOG2 from
it via `sw/hwmap.seq_emb_log2` (`sw/hwmap.py:371-380`); **and** `seq_run`/`chat_seq` must
read the CSR back and refuse a mismatch against the manifest. The R-d record
already shows this working at 2B ("EMBLOG2 12 written+read back",
`docs/HISTORY.md:749`).

### 5.4 S9 — synthesizable envelope checks

> ### PRE-G3.4 ROWS, KEPT AS THE RECORD — dated note 2026-09-02 (Task 10)
>
> Rows in this section that name a `rtl/layer_chan.sv`, `rtl/dn_step.sv`,
> `rtl/gate_unit.sv`, `rtl/seq_unit.sv`, `tb/tb_gate_unit.sv` or
> `sw/hwmap.py` line quote **source that G3.4 REWROTE or DELETED**, not
> source that merely moved: the 9-bank / 3-bank hand-split DN and KV
> expressions, the 4-bit `dn_head_hw` and 1-bit `kvhead_hw` datapath
> slices, `gate_unit`'s `NH = 16` and its 4-bit `w_addr`, the 18 × 6144
> conv banks, `EMBLOG2_RST = 5'd11`, `conv4_silu`'s shift 9 and the whole
> `` `ifndef SYNTHESIS `` datapath-envelope block.  They are kept
> verbatim, because they are the record of what the pre-G3.4 tree said and
> the argument this section makes rests on them (§0: nothing is deleted or
> struck).  Every citation that had merely MOVED was RENUMBERED instead,
> mechanically, by `evidence/qwen9b/o3/o3_cite_drift.py --base 8138d66`.
> **The post-G3.4 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_4_LAYER.md` §11.1.**

> ### PRE-G3.3 ROWS, KEPT AS THE RECORD — dated note 2026-09-02 (Task 9)
>
> Rows here marked `<!--cites:noquote-->` quote **source that G3.3 DELETED**,
> not source that merely moved: the 6-bit `cfg_ng` / `x_line` / `g_q…g5_q` / `r_g` declarations, the `wbeats` and `ng7` wires, the 1536-word `x_mem`, and the 6 KiB XWIN decode with its 11-bit pointers.  They are kept verbatim, because they
> are the record of what the pre-G3.3 tree said and the argument they support
> rests on them (§0: nothing is deleted or struck).  The exemption marker is
> used for exactly the reason §7.6 gives — *"an exemption is for source that
> no longer exists, not for a citation that has merely moved"* — and every
> citation that had merely MOVED was RENUMBERED instead, mechanically, by
> `evidence/qwen9b/o3/o3_cite_drift.py --base a08a90b`.
> **The post-G3.3 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_3_MATVEC.md` §11.1.**

The study's standing hazard (§2.10): *"almost every envelope guard in the RTL is
`` `ifndef SYNTHESIS `` sim-only. There are no hardware range checks on scratch
windows, `cfg_ng` or `cfg_nlog2`. On silicon an out-of-envelope command wraps,
aliases, or hangs — it does not report."* Verified: `rtl/vecnorm_unit.sv:430`
and `rtl/matvec_engine.sv:716` are both `` `ifndef SYNTHESIS ``.

**With one geometry there is exactly one legal envelope**, so a hard check is
cheap and — this is the part U4 unlocks — **cannot false-fire on a legacy
config**. Under the old contract a synthesizable check would have had to admit
every geometry the bitstream served. Add, as sticky error bits in the existing
STATUS/`err_op` mechanism (`rtl/layer_chan.sv` already has `err_op`):

* `cfg_nlog2 > 12` → error, command refused;
* `cfg_ng` outside `1..96` → error, MVGO refused;
  > **Dated note 2026-09-02 (G3.4, Task 10) — WHERE THIS LANDED, and why
  > it is not in `matvec_engine`.** `cfg_ng` is decoded in
  > `rtl/matvec_engine.sv`, but that file was closed by G3.3 and its own
  > `1..MAX_NG` guard is still `` `ifndef SYNTHESIS ``. The check is
  > therefore at the **MVGO dispatch**, which is where the spec's own
  > words put it ("MVGO refused"): `rtl/seq_unit.sv`'s one-cycle validator
  > refuses the record with a new `err_code E_ENV = 0x0D` before the
  > doorbell, on the existing `err_op`/STATUS mechanism. MVGO's `imm32`
  > **is** the SHAPE word, so the validator can see `ng[28:22]`.
  > **Two lines of defence, both live:** `sw/hwmap.shape_word` refuses
  > `ng` outside `1..MAX_NG` on the EMIT side (G3.3's folded minor, which
  > covers every host that packs a SHAPE word or writes the CSR directly),
  > and this refuses a stream the sequencer is handed — the case no host
  > packer sees. `ref/seq_format.validate` carries the **identical**
  > clause, because a hardware validator stricter than its golden is the
  > encoder/decoder mismatch §7.6's mechanization exists to prevent, and
  > `evidence/qwen9b/g3/isa_bits.py` reads both bounds out of their own
  > source and requires them equal. Landing it also required the seven
  > hand-written MVGO SHAPE immediates in
  > `tb/scripts/gen_seq_unit_vectors.py` to be re-encoded through the one
  > packer: they were **isa=1** words, whose `ng` sits in bits `[5:0]`,
  > and they all decoded to `ng = 0` under the v2.0 layout this RTL
  > reads. Fires-in-sim: `seq_e_env0` / `seq_e_env97`, each with a legal
  > MVGO ahead of it in the same stream. Gate:
  > `evidence/qwen9b/g3/G3_4_LAYER.md` §6.
* an out-of-window `s_axib` scratch burst → SLVERR, the way `matvec_chan`
  already answers an out-of-XWIN write (`rtl/matvec_chan.sv:614`  <!--cites:noquote-->
  `s_axib_bresp <= wb_win ? 2'b00 : 2'b10;`).

Cost: a handful of comparators off the datapath. Value: the 2B campaign's
hardest bugs were the host model of the chip, and every one of them was silent.

### 5.5 Smaller items enabled

* **No dual-width DN state mux** (§3.1) — the read path Track P measured stays
  exactly the structure Track P measured.
  > **AMENDED 2026-08-31 (A1.1).** Still true, and now trivially so: at
  > `int16` there is only one width, so there is nothing to mux. What the read
  > path *does* gain is **`DN_PIPE = 2`'s register stages** (§4.1) — the
  > structure Track P measured **plus** the pipelining Track P measured on it,
  > not a third thing.
* **The DN/KV address expressions are laid out for 9B alone** (§4.1) rather than
  being constrained to reduce bit-identically at LNH=16.
* **The ISA loses the bit-scatter** (§4.3) — a readability and
  verification win, not just an encoding one.
* **`SCA_SZ` 992 → 1056** with 64-word tile strides (feasibility §2.9, wall 15:
  at LNH=32 `A16` needs 64 words in a 32-word slot and overruns `GD`, which
  overruns `QN`) — sized for 32 heads, with no 16-head layout to preserve.

### 5.6 Hunted and REJECTED, with reasons

* **Strip `model_select` / the multi-geometry host tables.** Rejected. `ref/`
  and `sw/` still serve the old bitstreams (§3.3), and `model_select.MODELS` is
  the spine of Track F's per-geometry `--selftest` matrix — a regression asset
  that costs the board nothing. Removing it would delete tests, not code.
* **Make EMBLOG2 a compile-time constant.** Rejected. The runtime CSR costs a
  5-bit register; making it constant saves nothing measurable and deletes the
  R-b infrastructure the TB set exercises. *(An earlier revision said "~60
  sites"; that figure has no source and is withdrawn — §7.5's census is the
  count that exists.)* §5.3 takes the
  reset-value win instead, which is where the actual bug class lives.
* **Reduce `nch` below 4.** Not considered a simplification: it trades away
  throughput directly, and nch=1 remains valuable as a bring-up rung (the 2B
  campaign used it).

---

## 6. Floorplan and timing

### 6.1 What Track P leaves on the table

At the int8 geometry, `int8p_alt` reached **WNS −0.119 / TNS −2.7 / 48 failing
endpoints** — "the same order as the as-built control's 16" — under
`AltSpreadLogic_medium`, with the named DN bank-mux path **MET at +0.033**. That
is in the band this project's playbook has closed before (census → reroll spread
→ phys_opt closed −0.091 → 0.000 in one pass).

> **AMENDED 2026-08-31 (A1.1, A1.3) — THIS PARAGRAPH DESCRIBES A GEOMETRY THIS
> BUILD NO LONGER SHIPS, AND THE int16 STARTING POINT IS MUCH WORSE.** At
> `int16` + `DN_PIPE = 2` the module sits at **WNS −1.391 / TNS −2,007.2 /
> 6,638 failing endpoints** (Default) or **−1.539 / −3,252.2 / 6,406**
> (`AltSpreadLogic_medium`, which is the directive that MEETs the read path).
> That is **an order of magnitude outside** the band the playbook has closed,
> and it is **not** a "census → reroll → phys_opt" problem: the binding path is
> **one logic level with 95.9 % route**, which no amount of re-rolling moves.
> **The whole of option B rests on a placement constraint nobody has tried.**
> §6.2 is therefore no longer a de-risking experiment — it is the experiment the
> target depends on.

But **nothing was routed, anywhere** (`PLACE_EXP.md` §5.12), everything was
out-of-context (§5.3 — "a failure here is definitive, a success here is necessary
but not sufficient"), **no floorplan was tried** (§5.4, §5.11), and directive
spread is sampled once, not characterised (§5.8) — one directive change moved
WNS by 0.475 ns.

The unresolved structure is the **write-control fan-out**: at the full wide
geometry its worst path is one logic level with **95.9 % route** between a
dedicated register and the single bank it drives. `dont_touch` stops synthesis
merging the fan-out copies but nothing *places* them. **That is a placement
signature, and the fix is a placement constraint.**

### 6.2 S10 — the floorplan is a deliverable, and it is measured before it is built

Two facts point in opposite directions and both are real:

* the 2B campaign's T5 lesson — **constraining `layer_0` in any form cost ~1 ns**
  (variants B/C: −1.078, −1.148); build_035 closed only by pblocking the four
  mvchans and leaving `layer_0` alone (`docs/HISTORY.md:806-807`);
* Track P's write fan-out needs exactly the constraint T5 forbids.

They are not actually in contradiction: **T5 was measured on a design where
`layer_0` was not the binding block.** At 580/592 URAM across two or three SLRs
it is. The lesson is re-openable *with evidence*, and this spec resolves it by
producing that evidence cheaply, before any full build:

> **AMENDED 2026-08-31 (A1.4): read that as 928 URAM across THREE SLRs**, which
> makes the point harder, not softer — `layer_0` is not merely the binding block
> now, it occupies 96.7 % of the device's URAM and spans every SLR by
> arithmetic. And "cheaply" no longer describes the stakes: the experiment is
> cheap in machine time and **decisive** in outcome (A1.3).

**G5a — the OOC floorplan experiment.** Extend Track P's existing vehicle
(`synth/exp_uram/`, `launch_exp.sh`, `exp_ooc.tcl`) with pblocks. Same flow,
same part, same 4.000 ns, fresh out dir per variant, on snoke. Variants:

1. `int8naive` at the Default and `AltSpreadLogic_medium` directives — the S1
   structure, which Track P synthesized but **never placed**;
2. the same, with the DN state and KV arrays pinned into **two** SLRs — Track P
   §3.4 makes this arithmetically available (it states it for `int8p` as
   348 + 232 = 580 ≤ 640; **under S1's 592 the sum is 360 + 232 = 592 ≤ 640**,
   so it still holds) and says it was not tried;
3. the same, with each write-fan-out register set pinned into its bank's clock
   region — `PLACE_EXP.md` §5.11's identified next experiment.

> ## SUPERSESSION 2026-08-31 (A1.3, A1.4) — THE VARIANT LIST IS REPLACED, AND ITS STATUS CHANGES
>
> **Variant 2 above is arithmetically IMPOSSIBLE at `int16` and must not be
> attempted.** 928 URAM against 320 per SLR needs **three** SLRs — 2 × 320 =
> 640 < 928 — so the two-SLR pinning that was available at 592 is gone. Track P
> measured the `wide` spread at **312/312/304 of 320**, i.e. 96.7 % occupancy
> across all three. Variant 1 tested a structure this build no longer ships.
>
> **G5a is no longer "the last cheap thing before the first build". It is the
> experiment the target depends on, and it can END the target.** Say that
> plainly to whoever runs it: if no placement constraint closes the
> write-control fan-out, **option B does not close**, and the campaign goes back
> to the user with O1 re-opened at option 3 (DDR spill) or D (abandon) — the two
> the 2026-08-31 ruling did not take.
>
> **The replacement variants**, same flow, same part, same 4.000 ns, fresh out
> dir per variant, four concurrent, on snoke:
>
> | # | variant | what it establishes |
> |---|---|---|
> | **1′** | `wide` + `DN_PIPE = 2` at Default **and** at `AltSpreadLogic_medium` — Track P's `r2widepipe2` / `r3pipe2alt` re-run **on the shipping RTL** rather than on the experiment copy | reproduces the **+0.097 MET** read path on the real design, or does not. If it does not, the directive dependency was doing more work than the pipelining and everything downstream re-prices. |
> | **2′** | **THE CRITICAL ONE — the write-fan-out pblock.** Each per-group fan-out register set (`DN_BPG = 8`, three groups) pinned into the clock region of the banks it drives, on top of 1′ | this is the only structure anyone has proposed for the binding path. **If it does not move −1.391, option B has no known route to closure.** |
> | **3′** | the same pblock at `DN_BPG = 1` (per-bank fan-out) | per-bank was **worse** unconstrained (−1.956); the hypothesis is that it is worse *only* because nothing placed the copies, so constraining it is the direct test of that hypothesis. |
> | **4′** | a three-SLR floorplan for the DN array itself — 8 banks per SLR — with and without a `layer_0` pblock | this is where **O4** is decided, and A1.4 means the DN array spans all three SLRs whatever else happens. |
>
> **Read every result with Track P's own rule** (§2.1): OOC is `layer_chan`
> alone on the whole VU9P. A failure here is definitive; a success is necessary
> and not sufficient. Nothing has been routed, anywhere, at any geometry.

Runtimes from Track P's own record: synth 12–25 min, `opt_design` 6–8 min,
`place_design` 33–45 min per variant, four concurrent. **This is hours, not
build cycles**, and it is the last thing that runs before the first full build.

**If (3) shows a `layer_0` pblock is required, that returns to the user as O4**,
with the OOC number beside T5's in-context −1 ns.

### 6.3 What the full build inherits

* ~~**`layer_0` gets 12+8 URAM banks instead of 9+3** — 592 device URAM against
  today's 348 — and the DN state is int8, i.e. it lives in two SLRs by the
  arithmetic, three by the unconstrained placer.~~
  **SUPERSEDED 2026-08-31 (A1.1, A1.4): `layer_0` gets 24+8 URAM banks instead
  of 9+3 — 928 device URAM of 960 (96.7 %) against today's 348 — the DN state is
  `int16`, and it lives in THREE SLRs by arithmetic, not by placer choice.**
  Track P's measured spread is 312/312/304 of 320. Add `DN_PIPE = 2`'s
  ≈ 24.7 K flip-flops (≈ 1 % of the device) and no LUT change.
* **Each `matvec_chan` gets ~5,826 LUTs and 497 CARRY8 smaller** (§5.1), in the
  block that owned build_034's worst endpoints. Floorplan A's four soft pblocks
  (`synth/constraints/fable5_floorplan_a.xdc`) may become easier or unnecessary;
  they are the starting point, not the answer.
* **`matvec_engine` and `matvec_chan` re-open for MAX_NG=96** (§4.5) —
  simultaneously growing (x_mem 1536 → 3072 words, wider counters) and shrinking
  (§5.1). Net direction is **unknown and is a G4 synthesis output**, not a
  prediction this spec makes.
* **Scratch BRAM doubles** (§4.3). Per-SLR BRAM is a floorplan input.
* **Timing method is the house playbook, unchanged**: census → reroll spread →
  post-route phys_opt; 3–4 parallel builds with different placement directives
  when near margin; reuse the synth checkpoint; never pblock GT/Aurora; check
  DSP capacity per SLR before constraining anything holding `layer_0`'s 1,838
  DSPs.
* **Expect a multi-roll spread.** `docs/HISTORY.md:793-801`: seven rolls on
  build_035's floorplan spanned −0.004 … −0.428 and **no roll ever measured
  0.000**. Budget accordingly.

---

## 7. Host and artifact chain

### 7.1 What Track L already did, and what it deliberately did not

**Done, on main, in `ref/`** (`LADDER.md` §5, `CHECKPOINT_VERIFY.md` §9):
multi-shard `SafeTensors` + `find_checkpoints()` (9B = 4 shards);
`checkpoint_is_tied()` taking the **tensor** as ground truth and refusing any
flag/file disagreement, with head and embedding lookup separated everywhere
(`CkptSource.head()`, `head_f` vs `emb_f`); `LNKH`/`VREP` with value head *h*
reading key head `h // VREP` in `layer_ref`, `layer_fixed`,
`fidelity_check.blockprobe` and `bytes_per_token`; `w4g128gptq` as a scored
quant with its byte-identity asserted; `4b`/`9b` tags in `model_select`.

**Deliberately NOT done — these are refusals, and turning them into
generalizations is this migration's work** (`LADDER.md` §5b):

> **LANDED 2026-08-31 at G2a** (Task 3; gate doc `evidence/qwen9b/g2/G2A_HOST.md`).
> **Every row of the table below is DONE**, and the byte-lock proves it was
> inert at the frozen geometries: `evidence/qwen2b/rc/t4_bytes_unmoved.sh`
> returns `BYTES_UNMOVED PASS` and `ref/scripts/regen_gate.sh` returns
> `REGEN_GATE_PASS` on the post-change tree.
>
> **The citations below are PRE-G2a and are kept as the record of what
> changed.** The paths and line numbers still resolve, but the quoted source
> text has moved or no longer exists, so each row carries
> `<!--cites:noquote-->`: `evidence/qwen_next/spec_cites.py` range-checks the
> citation and does not re-check a quotation of deleted source. **The post-G2a
> landmarks are named in the gate doc, which the checker does read.** Anyone
> using this table as a to-do list is reading a closed one.

| site | what it does at 9B today | this migration |
|---|---|---|
| `ref/gen_layer_script.py:1162` `for h in range(LR.LNH):` with `ref/gen_layer_script.py:1163` `q_src = QKV + h * LR.LDK` and `ref/gen_layer_script.py:1164` `k_src = QKV + LR.LKD + h * LR.LDK` | the packed QKV block is q then k then v with `LKD = LNKH*LDK`, so **every h at or above 16 reads the K region as Q and V as K, silently**. Guarded by `require_supported_geometry`, defined at `ref/gen_layer_script.py:1065`, refusing on unequal head counts at `ref/gen_layer_script.py:1091-1092` and on slot overflow at `ref/gen_layer_script.py:1108` | **generalize** with `VREP`; the guard becomes an assertion of the new algebra. *(The study cites this as ":~1010"; the true lines are **1015-1018**, and the file's own docstring self-citation at `:1068-1090` is stale the same way.)* |  <!--cites:noquote-->
| `ref/gen_layer_script.py:281` `self.cw = np.zeros((18, LR.CONV_DIM, 4), dtype=I64)` and its two siblings at `ref/gen_layer_script.py:282-283`; `ref/gen_layer_script.py:470` `assert 0 <= dn_slot < 18 and 0 <= kv_slot < 6` | 24 DN + 8 KV slots overflow | **24 / 8**. `:284-286` sizes the KV caches `kc`/`vc`/`T` as exactly `[6][2]` — **→ `[8][4]`**, in lockstep with wall 9 (§4.6) |  <!--cites:noquote-->
| **`ref/gen_layer_script.py:1491`** — ~~`M.dnst(h, QNS, KN, v_src, GD + 16 + h, GD + h, DO32)`~~ **LANDED at G2a**  <!--cites:noquote--> | the `16` **is `LNH`**. At LNH=32 the decays live at `GD+32 … GD+63` but `GD + 16 + h` sweeps `GD+16 … GD+47`, so **all 32 heads read the wrong word** — heads 0-15 from the beta half, heads 16-31 off by 16 — and **silently** | **`decay_base + h` / `beta_base + h`, exported by the SCA tile map.** A live wall-17 defect at 9B, found while writing §4.3, which quotes this line. **It landed at G2a on 2026-08-31, before §4.3's scalar-pointer base was derived from it**, which is the sequencing this row required |  <!--cites:noquote-->
| `ref/gen_layer_script.py:581` `KVH_MAX = (1 << 1) - 1`; asserts `:656-658` (KVAP) and `:712-714` (ATTN) | refuse `kvh >= 2`, which is what keeps the 4-bit host decode harmless today | **lockstep** with the RTL field, `tcnt_bank` and the KV banking — see §4.6's wall-9 trap box |  <!--cites:noquote-->
| `ref/gen_layer_script.py:494` `assert (1 << nlog2) == n` | passes at 4096 | keep; it is the guard that catches a non-pow2 H. *(study cites `:493` — true line **457**)* |  <!--cites:noquote-->
| `ref/gen_layer_script.py:514` `assert 1 <= n <= 2048` | **fails at 4096** | → 4096. *(study cites `:513` — true line **477**)* |  <!--cites:noquote-->
| `ref/debug_torch_diff.py:~115` | refuses at import | generalize |
| `ref/gen_token_script.py:84` `DN_SLOTS, KV_SLOTS = 18, 6` | wrong | **24 / 8** |  <!--cites:noquote-->
| `ref/gen_layer_script.py:84-93` SCA tiles on 32-word strides | `A16` overruns `GD` at LNH=32 | 64-word strides, `SCA_SZ` 992 → **1056** |
| `ref/gen_layer_script.py:223` `SCRATCH_MAX = 32768` | | **65,536** (§4.3) |  <!--cites:noquote-->
| `ref/gen_layer_script.py:579` `DNST_HEAD_MAX = (1 << 4) - 1` | | **(1<<5)-1** |  <!--cites:noquote-->

### 7.2 The 9B artifact chain

* **Multi-shard load + untied head, host side.** `ref/` is done; the **~6
  producer sites** that assume a tied head still take one variable assignment
  each (feasibility §2.9): `ref/gen_model_script.py:499`,
  `ref/seq_chat.py:1262-1265` *(pre-fix line numbers — see the citation-rot
  warning; current landmarks are in feasibility §2.10)*, `sw/infer.py:695-696`,
  `ref/audit_ranges.py:493`, plus the `isinstance` filter in
  `ref/calib_stats.py:276-283` where an untied `nn.Linear` head collides with
  `HEAD_KEY`. **Two of the study's six are already done and must come out of the
  tally**: `ref/perplexity_eval.py` and `ref/fidelity_check.py` got
  `CkptSource.head()` and the `head_f`/`emb_f` split from Track L
  (`CHECKPOINT_VERIFY.md` §9), so citing `perplexity_eval.py:635` as remaining
  work — as an earlier revision of this spec did — is wrong. **Four sites
  remain.** **No RTL, no new wid, no new DDR region.** Regression already
  exists: `ref/gen_token_script.py:177-181` draws head and table as two
  independent random matrices and every `token_s*` TB runs that untied pair
  through the whole chain.
* **GPTQ at scale.** Measured at 9B: **40.23 min** (183.5 s load + 2,230.1 s
  pass) at **8 threads**, against 19.1 priced — 2.11× over (`LADDER.md` §7). The
  Hessian npz is **24.06 GiB** (one float32 K×K per input *site*, 129 sites, FFN
  sites at K=12288) and lands on the **21 TB NFS pool**, not snoke's local 458 GB
  — disk was never a constraint. Built once, amortized. Calibration corpus is
  `ref/ppl_corpus_calib.txt`, **disjoint** from the pinned eval slice, and the
  gain is genuine generalization — but GPTQ is calibration-dependent by
  construction (`LADDER.md` §6.7) and a deployment far from this corpus sees
  less.
* **Per-channel repack, and it fits.** `plan_weights` (`sw/hwmap.py:464`) with
  R-c's `rows_of` per-channel repack, at 9B W4 g128: **249 images**,
  **4,091,805,696 bytes/token** (3,902.2 MiB), **busiest channel 978.6 MiB =
  76.5 % of the 1,280 MiB window — PASS** (feasibility §3, **D**, and the tool
  reproduces the committed 2B W8 row exactly before computing anything new).
  **No `EMB_BASE` change is needed at W4.** The zero-slack embedding-channel
  problem §3.2 documents is a **W8-only** problem and this build does not have
  it. **(S)** Channel-0 total: 256 (W_BASE) + 978.6 + 1,940.0 = 3,174.6 of
  4,096 MiB — this document's addition of three `f04` outputs, not an `f04`
  output itself. **Gate: G2's `plan_weights` fit run records the real per-channel
  tops**, and that is the number the gate doc carries.
* **Two big images, and they are separate objects.** The embedding table is
  **248,320 × 4096 × 2 B = 2,034,237,440 B = 1,940.0 MiB**, flat int16, at
  `EMB_BASE` on channel 0 (feasibility §3.1; the byte figure cross-checks
  `CORRECTIONS.md` C1's table). The LM head is **1,017,118,720 params**, a
  *different tensor* at 9B, quantized separately and packed chunk-interleaved
  into the weight pack at `W_BASE` — a different file, region, layout and
  hardware read path (feasibility §2.9). **(S)** its packed W4 g128 footprint is
  a `plan_weights` output, not a number this spec invents; **G3 records it.**
* **EMBLOG2 13, programmed from the artifact** — §5.3, and the BFM/TB sites in
  §7.5.
* **Chat template must be re-derived.** `chat_template.jinja` and
  `tokenizer_config.json` **differ** 0.8B/2B vs 4B/9B — a 12-line diff over 3 of
  154 lines that **inverts the `enable_thinking` default**: 0.8B/2B emit a closed
  `<think>\n\n</think>\n\n` unless asked for thinking; 4B/9B emit an **open
  `<think>\n`** unless asked *not* to (feasibility §1.4). The host-side
  id-spliced template (`docs/INSTRUCT_SPEC.md`, `ref/seq_chat.py`) is rebuilt and
  the `ntok >= 24` UX guidance re-derived. **The tokenizing files
  (`tokenizer.json`, `vocab.json`, `merges.txt`) are byte-identical across all
  four models**, so the pinned PPL corpus and its 24,528 positions carry over
  unchanged.

### 7.3 Defect B — IN SCOPE, fixed in this migration

> **FIXED 2026-08-31 at G2a** (Task 3). All four literals are `LR.H`, the
> cosmetic log text at `sw/infer.py:718` with them, and the regression is
> committed at `evidence/qwen9b/g2/damage_defect_b.py` — it puts the literals
> back and requires the failure, at 2b and 9b. The four sites are now
> `sw/infer.py:814-817` and `sw/infer.py:819`; the block quoted below is the
> PRE-FIX text and carries `<!--cites:noquote-->` for that reason.

`sw/infer.py:798-802`, verified exact today:  <!--cites:noquote-->

```python
        M.vnw_(STG, 1024)
        M.vn(1, 1024, RS_F, RS_F, X0, XN)
        M.alu(0, 1024, 0, XN, 0, X8)
        # full-vocab LM head + chunked on-chip argmax
        y32, _ = M.matvec(self.qw_head, X8, 1024, rowchunk=ROWCHUNK)
```

Four hard `1024` literals where `LR.H` belongs, on the **online `step()` path**.
Track F measured the severity rather than reasoning about it: `matvec_y32` and
`matvec_y32_w8` do both raise at `n_in`=1024 on an H-wide head — **but the crash
is where it stops, not where it starts.** The three lines before it run silently
on half the residual, and because RMSNorm's denominator is a mean over the words
it is *told* about, they corrupt even the words they do write: measured at 2B on
an unevenly-split residual, the DYNQ8 exponent **shifts** and **99.6 % of the
leading half changes, max |diff| 99** (`CORRECTIONS.md` C2; an i.i.d.-uniform
residual gives max |diff| 1, which is why a single sample is not evidence).

Fix: `LR.H` at all four sites, following the already-parameterized template at
`ref/gen_model_script.py:590-595`. Also in the same pass:
`sw/infer.py:718`'s cosmetic literal log text `"248320x1024"`. *(For the record:
the reshape itself is at `sw/infer.py:713` and already uses `LR.H` correctly —
the ledger's "reshape crash" refers to the one inside `matvec_y32`.)*
**Regression**: a deliberate-damage test in the Track F style — put the literals
back, watch it fail — committed beside the fix.

### 7.4 The rest of `sw/`

> **LANDED 2026-08-31 at G2a** (Task 3; gate doc `evidence/qwen9b/g2/G2A_HOST.md`).
> **Every row of the table below is DONE**, and the byte-lock proves it was
> inert at the frozen geometries: `evidence/qwen2b/rc/t4_bytes_unmoved.sh`
> returns `BYTES_UNMOVED PASS` and `ref/scripts/regen_gate.sh` returns
> `REGEN_GATE_PASS` on the post-change tree.
>
> **The citations below are PRE-G2a and are kept as the record of what
> changed.** The paths and line numbers still resolve, but the quoted source
> text has moved or no longer exists, so each row carries
> `<!--cites:noquote-->`: `evidence/qwen_next/spec_cites.py` range-checks the
> citation and does not re-check a quotation of deleted source. **The post-G2a
> landmarks are named in the gate doc, which the checker does read.** Anyone
> using this table as a to-do list is reading a closed one.

| site | verified | change |
|---|---|---|
| `sw/chat_seq.py:237` `HEAD_WID = 186`, used at `:2350` | exact | at 32 layers the head is a **different wid** (249 images). `:592` already derives it correctly into `g["_HEAD_WID"]`; the online call must use the derived value |  <!--cites:noquote-->
| `sw/chat_seq.py:231` `X8_WORD, X8_LEN = 0x800, 1024` | exact | **latent, not live** — every in-repo caller passes session-derived `geom["X8_WORD"]/["X8_LEN"]` (`progress.md:14`). Move it anyway; a latent literal at a new geometry is the R-c wall-8 class |  <!--cites:noquote-->
| `sw/head_cache.py:667-669` `== (248320, 1024, -4, 5, 128)` | exact | LOUD, `--selftest`-only, and `spec.k` is available. Derive |  <!--cites:noquote-->
| `sw/hwmap.py:215` `SCRATCH_WORDS = 32768` | exact — **the canonical definition**; `sw/seq_run.py:92` imports it, but `tb/scripts/gen_seq_unit_vectors.py:83` duplicates the literal (so does the dead `tb/scripts/gen_seq_vectors.py`, which is deleted rather than fixed — §7.5 E) | → 65,536 in one place, and the live duplicate becomes an import |  <!--cites:noquote-->
| `sw/hwmap.py:430` `EMB_ROW_BYTES_DEFAULT = 1 << SEQ_EMBLOG2_RST` | exact | follows S8's reset move; it is by design for pre-R-b manifests and unreachable for a 9B artifact, whose manifest carries the key. Related comments at `sw/hwmap.py:327-338`, `sw/hwmap.py:507` and `sw/hwmap.py:516` |
| `sw/seq_run.py:2359` `cover in (16384, SCRATCH_WORDS)` | exact | a **hard-coded pair**, not the "WHOLE power-of-two scratchpad" check its own comment at `:2354-2355` claims. Any third size fails the selftest *even when correct* — derive it |  <!--cites:noquote-->
| `sw/seq_run.py:773` `man["emb_row_bytes"] = 2048`; `:1477-1478` the back-compat docstring; `:2491-2497`, `:2507-2512` | exact | fixtures and mapping tests pinned at 2048 B / H=1024. The *mechanism* is manifest-driven (`:1470`); only the fallback and the fixtures are pinned |  <!--cites:noquote-->
| `sw/chat_seq.py:1673`, `:1788`, `:4698` `& 0x7FFF` (SPTR) | exact | 15-bit SPTR → 16-bit |
| **`sw/chat_seq.py:181-182` `POS_STRIDE = 1536` / `POS_COPIES = 6`** | exact — *"6 GQA layers share one table per pos"* | **a real 9B item that no earlier census caught.** This 1536 is rope-table bytes per position, **not** the mvchan XWIN 1536, and it moves with the GQA layer count (6 → **8**) and `NKV`. Reinforced at `:26`, `:35`, `:175`, `:607`, `:834-836`, `:2637`, `:3696`, `:3770`, `:4017`, `:6067` |  <!--cites:noquote-->
| `sw/chat_seq.py` per-op vector lengths `sw/chat_seq.py:1724`, `sw/chat_seq.py:1726`, `sw/chat_seq.py:1736`, `sw/chat_seq.py:1739`, `sw/chat_seq.py:1742`, `sw/chat_seq.py:1744`, `sw/chat_seq.py:1746` | exact | `128`/`256`/`16`/`32` — head-dim and NH=16 constants inside the scratch-footprint decoder |
| `sw/head_cache.py:667-669` `== (248320, 1024, -4, 5, 128)` | exact | LOUD, `--selftest`-only, and `spec.k` is available. Derive |  <!--cites:noquote-->
| **`sw/tok_meter.py`** | **corrected** — an earlier revision of this row said "no 2B-specific pack planning exists". That is wrong in effect: `sw/tok_meter.py:274` calls `plan_weights` with **no `rows_of`**, i.e. the nch-independent path, which `RD_GATE.md:599-605` records as follow-on 3 — ***"`sw/tok_meter.py` cannot plan a 2B pack"***, it "collides with `EMB_BASE` and aborts before any DMA" | it cannot plan a **9B** pack either, for the same reason. Teach it the repack (`hwmap`/`seq_run` learned it at T3; `tok_meter` was not on that list), **or** G6 uses `evidence/qwen2b/rd/rd_census.py` as R-d did. Also: the docstring at `sw/tok_meter.py:41-43` carries 2B head arithmetic, and `sw/tok_meter.py:514-515` fetches an embedding row at a `n*2` stride rather than a shift by EMBLOG2 — at 9B `2*H = 8192` **is** the power of two so they agree, but that coincidence should become an assert |

### 7.5 TBs and vector generators (feasibility-study wall 17 — the 2B campaign's walls-7/8 class)

> ### PRE-G3.3 ROWS, KEPT AS THE RECORD — dated note 2026-09-02 (Task 9)
>
> Rows here marked `<!--cites:noquote-->` quote **source that G3.3 DELETED**,
> not source that merely moved: the TB twins' 1536-word `MAXX`/`NX`, their 11-bit `x_waddr`/`xptr` and the `0x4000-0x57FF` window maps.  They are kept verbatim, because they
> are the record of what the pre-G3.3 tree said and the argument they support
> rests on them (§0: nothing is deleted or struck).  The exemption marker is
> used for exactly the reason §7.6 gives — *"an exemption is for source that
> no longer exists, not for a citation that has merely moved"* — and every
> citation that had merely MOVED was RENUMBERED instead, mechanically, by
> `evidence/qwen9b/o3/o3_cite_drift.py --base a08a90b`.
> **The post-G3.3 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_3_MATVEC.md` §11.1.**

The 2B campaign's hardest bugs were the host model of the chip. **An earlier
revision of this section named five sites and presented them as a census; a full
sweep of `tb/` and `sw/` finds twenty-six files.** Every line below is verified
against the tree.

**A — the XWIN / `MAX_NG` family** (§4.5): `tb/tb_matvec.sv:66` `MAXX = 1536`;  <!--cites:noquote-->
`tb/tb_matvec_chan.sv:14` `MAXX = 1536` **and `:206-207`'s `% 2048`, which  <!--cites:noquote-->
encodes the 11-bit XPTR** (commented at `:202`); `tb/tb_mvshim_b.sv:43` `NX = 1536` (also `tb/tb_mvshim_b.sv:19` and  <!--cites:noquote-->
`tb/tb_mvshim_b.sv:589`); `tb/mvshim_b_stubs.sv:54` declares an 11-bit `x_waddr` port.  <!--cites:noquote-->
`tb/seq_stub_mvchan.sv:118` `logic [10:0] xptr;`, with its window map  <!--cites:noquote-->
commented at `tb/seq_stub_mvchan.sv:33`, `tb/seq_stub_mvchan.sv:38` and  <!--cites:noquote-->
`tb/seq_stub_mvchan.sv:48`. All → 3072 words / 12-bit pointers.  <!--cites:noquote-->

> ### PRE-G3.1 ROWS, KEPT AS THE RECORD — dated note 2026-09-01 (Task 7)
>
> Rows in this section marked `<!--cites:noquote-->` quote **SEQ_ISA v1.7
> source that G3.1 DELETED**, not source that merely moved.  They are kept
> verbatim, because they are the record of what the pre-G3 tree said and the
> argument this section makes rests on them (§0: nothing is deleted or
> struck).  The exemption marker is used for exactly the reason §7.6 gives —
> *"an exemption is for source that no longer exists, not for a citation that
> has merely moved"* — and every citation that had merely MOVED was
> RENUMBERED instead, mechanically, by
> `evidence/qwen9b/o3/o3_cite_drift.py --base d2d774b`.
> **The post-G3.1 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_1_ISA.md` §15.**

**B — the 15-bit scratch family** (§4.3), and it is the largest:

| site | what it assumes |
|---|---|
| **`tb/tb_seq_unit.sv:967`** `u_layer.smem[exp_mem_a[i][14:0]]` | **the highest-value item in this census.** A 15-bit truncation **inside a checker**, with **no range guard at the parse site** (`tb/tb_seq_unit.sv:457-473`). At 16-bit addressing every golden address ≥ 32768 aliases down by 32K and the checker compares the wrong word — **a silent pass, not a failure.** It is an *unfixed instance of an already-diagnosed bug*: `tb/tb_seq_chip.sv:76-86` documents the fix, `tb/tb_seq_chip.sv:614-616` implements the parse guard and `tb/tb_seq_chip.sv:923` the derived slice. **Copy that fix; do not re-invent it.** |  <!--cites:noquote-->
| `tb/tb_seq_unit.sv:585-596` and the read-channel twin `:602-607` | `32'd32767` scratch bound *and* the `0x4000-0x57FF` XWIN test. *(An earlier revision cited `:555-563` and missed both the comment head and the read twin — those are the PRE-G3.1 numbers and are kept as the record of what it cited.)* |  <!--cites:noquote-->
| `tb/tb_seq_unit.sv:372`, `:811` | EMB row 2048 B is the reset value every pre-R-b vector relies on. **DONE 2026-09-02 (G3.4, comment sweep + fix round 1 M2): the reset is 13 / 8192 B and both comments say so** — the text quoted at `:372` no longer exists |  <!--cites:noquote-->
| `tb/seq_stub_layer.sv:120`, `:122`, `:151`, `:279` | `smem [32768]`, three 15-bit address signals. Latent oddity one line away at `:283`: `sptr <= sptr + 14'd1;`, a 14-bit increment into a 15-bit register |  <!--cites:noquote-->
| `tb/tb_layershim_c.sv:50`, `:56` | `[16:0]` AXI byte address = 128 KiB = 32768 words — one bit short at 16-bit |
| `tb/tb_layershim_c.sv:304-331`, `:360` | the T3/T5 layout and both `32768 - n` top-of-window burst placements |
| `tb/tb_seq_chip.sv:76` `MAXMEM = 32768` | **the good example** — everything downstream is derived from it (`:86` `MEMAW`), so only this line moves |  <!--cites:noquote-->
| `tb/tb_vecalu_diff.sv:78-80` | 15-bit `n_*` vs the frozen 14-bit legacy copy; the differential's "the extra bit is always 0" argument needs restating at 16 |
| `tb/tb_vec_alu.sv:31`, `:33`, `:112`, `:126`, `:490`, `:516` | 15-bit `cfg_*`, `mem [32768]`, and the R-c long-length case that deliberately parks `LD = 16384` in the high half |
| **`tb/tb_vec_alu.sv:29`** `cfg_len` 13-bit | **a new finding inside a listed file**: the TB's own `cfg_len` caps at 8191 and **breaks at FFN=12288**. It is wall 3's TB twin and §4.6 did not name it |
| `tb/tb_burst_fabric.sv:320` `LAYBASE = 6 << 16` | 128 KiB. At 65,536 words = 256 KiB this **collides with the next slot**, and the `mvbase` expression at `tb/tb_burst_fabric.sv:320-321` has no room — the TB-side confirmation of §4.3's `LAYB_BASE` re-alignment |  <!--cites:noquote-->

> **PRE-G3.2 LINES, KEPT AS THE RECORD — dated note 2026-09-02 (Task 8).**
> Block **C** below and the `tb/scripts/gen_seq_c_vectors.py` row of the
> table above quote source **G3.2 REWROTE** (the 11-bit `w_waddr`, the 2048
> arrays, the N=2048 case block and the `n2048_vectors` generator), so they
> carry `<!--cites:noquote-->` under the same §7.6 rule the §4.2 box states.
> **The post-G3.2 landmark for each is in
> `evidence/qwen9b/g3/G3_2_VECNORM.md` §9.**  The census this block asked
> for was performed: `evidence/qwen9b/g3/G3_2_VECNORM.md` §5.

**C — the N=2048 vecnorm family** (§4.2), which §4.2 had no TB row for at all:  <!--cites:noquote-->
`tb/tb_vecnorm.sv:40` `logic [10:0] w_waddr = 0;` and `tb/tb_vecnorm.sv:57`  <!--cites:noquote-->
`logic [15:0] xv [2048];` with its `wv`/`gv` twins at `tb/tb_vecnorm.sv:58-59`  <!--cites:noquote-->
(also `tb/tb_vecnorm.sv:9`, `tb/tb_vecnorm.sv:65-66`, and cases 5/6 at  <!--cites:noquote-->
`tb/tb_vecnorm.sv:251-268`); and  <!--cites:noquote-->
`tb/tb_vecnorm_diff.sv:51` `logic [10:0] w_waddr` with its rationale at `:48-50`.  <!--cites:noquote-->

**D — the NH=16 family** (§4.6), which §4.6 had no TB row for either. **There is
no `NH` parameter anywhere in `tb/` or `sw/`** — the 16 is a bare literal in
every one of these: `tb/tb_gate_unit.sv:1`, `:14` (`logic [3:0] w_addr`, the one  <!--cites:noquote-->
that fails **silently** at LNH=32 rather than by array bound), `tb/tb_gate_unit.sv:16-17`,
`tb/tb_gate_unit.sv:26-31`, `tb/tb_gate_unit.sv:47-48`, `tb/tb_gate_unit.sv:51-52`, `tb/tb_gate_unit.sv:55-56`, `tb/tb_gate_unit.sv:59-60`, `tb/tb_gate_unit.sv:73`, `tb/tb_gate_unit.sv:84`; and
`tb/scripts/gen_seq_layer_script.py:206-227` `m_gate`, a reference model with
`np.zeros(32)`, `range(16)` and `out[16 + h]`.

> **DISCHARGED 2026-09-02 by G3.4 (T10 fix round 3).** Family D is done:
> `rtl/gate_unit.sv` takes `NH = 32` with `w_addr` widened to `[HB-1:0]`,
> and `tb/tb_gate_unit.sv` took an `NH` parameter instead of the ten
> literals. **The `tb/tb_gate_unit.sv` and `rtl/gate_unit.sv` line numbers
> above are this census's own, at `8138d66`, and the text they quote no
> longer exists** — they are kept as the record of what was found, which is
> what a census is. `evidence/qwen9b/g3/G3_4_LAYER.md` §17.4 lists them as
> class-B residue by name; the drift gate excludes this document at base
> `8138d66` for exactly these rows.

**E — the vector generators.**

> **PARTIALLY LANDED 2026-08-31 at G2a** (Task 3), and only the two rows that
> are NOT testbench-width work: `tb/scripts/gen_seq_vectors.py` is **DELETED**
> (D-DEAD, confirmed unreferenced first — `tb/Makefile` names it in one
> comment, `tb/Makefile:289`, and never invokes it), and
> `tb/scripts/gen_seq_unit_vectors.py`'s duplicated `SCRATCH_WORDS` is now an
> import from `sw/hwmap.py`. **The rest of this table is G3's**, beside the
> RTL it mirrors — including that file's `EMB_ROW_LOG2 = 11`, which is §5.3's
> and would move a golden if it landed here.
>
> **The deletion leaves citations behind, and they are handled rather than
> hidden.** `evidence/qwen_next/spec_cites.py` gained a `RETIRED` set beside
> `PENDING`: a citation to a deleted path is reported as `RETIRED`, not as a
> failure, and the stale `ALIAS` short form was dropped in the same commit so
> a bare short form of it can no longer resolve to something else. Every
> citation to it in this document and in
> `docs/QWEN35_NEXT_FEASIBILITY.md:790` now carries a dated note saying the
> file is gone.

| site | verified | change |
|---|---|---|
| `tb/scripts/gen_seq_unit_vectors.py:80-83` | `EMB_ROW_LOG2 = 11` at **`:80`** (an earlier revision cited `:81-83` and excluded the line that matters; `:82` is blank), `SCRATCH_WORDS = 32768` at `:83` | 13 / 65,536, and import `SCRATCH_WORDS` rather than duplicating it |  <!--cites:noquote-->
| `tb/scripts/gen_seq_unit_vectors.py:549-551` | its ALU packer is still **14-bit** — no bit-14 scatter at all | so the live seq_unit vectors **never exercise a high-half ALU address**. At 16-bit, rewrite (§7.6 C) |  <!--cites:noquote-->
| **`tb/scripts/gen_seq_vectors.py`** | **DEAD — and DELETED 2026-08-31 at G2a; the line numbers in this row are of the deleted file, kept as the record.** `tb/Makefile` mentions it **only in a comment at `tb/Makefile:289`** and never invokes it; it is a stale near-copy of `tb/scripts/gen_seq_unit_vectors.py` still carrying pre-R-b 14-bit masks (`tb/scripts/gen_seq_vectors.py:188`, `tb/scripts/gen_seq_vectors.py:191`, `tb/scripts/gen_seq_vectors.py:319`, `tb/scripts/gen_seq_vectors.py:334`, `tb/scripts/gen_seq_vectors.py:354`, `tb/scripts/gen_seq_vectors.py:394`, `tb/scripts/gen_seq_vectors.py:402`, packer `tb/scripts/gen_seq_vectors.py:425-427`) | **Confirm dead and delete — do not migrate it.** An earlier revision of this spec listed `tb/scripts/gen_seq_vectors.py:62`'s `EMB_ROW_BYTES = 2048` as a work item in two places, which would have sent someone to fix a file no test runs. `docs/QWEN35_NEXT_FEASIBILITY.md:790` cites it the same way |
| **`tb/scripts/gen_chat_i1_vectors.py:298`** `stage = np.zeros(16384, dtype=bool)` | exact | **wrong TODAY, against the existing 32K scratchpad** — the staging mask is half the hardware's, so `keep = np.nonzero(~stage)[0]` (`tb/scripts/gen_chat_i1_vectors.py:301`) can never name a word ≥ 16384 and any staging window in the upper half is silently dropped from the golden. **Independent of this migration**; see §9 D-STAGE |  <!--cites:noquote-->
| `tb/scripts/gen_seq_layer_script.py:96-114` | the high-half map, `B_TOP = 0x7FF8` (*"the LAST 8 words of the 32K scratchpad"*) with fold-down images at `− 0x4000`; bit-home map at `:72-73`; aliasing-sentinel rationale `:68-83` | every one is a 15-bit/32768 assumption; all re-derive at 16-bit |  <!--cites:noquote-->
| `tb/scripts/gen_seq_c_vectors.py` | **checked, and it is NOT a defect** — the only geometry literal is a **deliberate** N=2048 freeze (`tb/scripts/gen_seq_c_vectors.py:233-241`, locked by its own comment at `tb/scripts/gen_seq_c_vectors.py:236`: *"N is HARD-CODED 2048, not LR.H"*), because these are unit vectors for `vecnorm_unit`'s `n_log2 = 11` geometry | keep the 2048 set as a regression **and add a 4096 set**; note the filenames bake 2048 in (`tb/scripts/gen_seq_c_vectors.py:234-239`), so a rename ripples into `tb/tb_vecnorm.sv` and the Makefile |  <!--cites:noquote-->
| `tb/scripts/gen_seq_chip_vectors.py:77` (the PRE-G4a line, kept as the record — see the note), `tb/scripts/gen_seq_chip_vectors.py:303` | the 2048-row LM-head interleave | re-derive from the artifact. **DONE 2026-09-03 (G4a): it was ALREADY manifest-driven and is now VERIFIED.** `build_wimg` took the interleave depth from the artifact's own layout key, never from a constant (`tb/scripts/gen_seq_chip_vectors.py:115`); what was missing was any check that the depth the artifact declares is the one its ADDRESSES were built from, and `verify_plan` supplies it — it re-derives every image base from the manifest plus that layout and requires all 249 to reproduce the bases the stream's MVGO records encode (measured: they do). The `:77` docstring that named 2048 as a constant is rewritten, so that line number does NOT renumber and is kept as the pre-fix coordinate. Post-fix site: G4a's gate document, section 3.3 |
| `tb/tb_layer_chan.sv:421` `EMB_N_MAX = 4096` (the pre-fix line), `tb/tb_layer_chan.sv:466-467` | exact | **exactly at the 9B ceiling** — it fits with zero margin and must be asserted rather than left as a coincidence. **DONE 2026-09-02 (G3.4 fix round 1): the literal is GONE** — `EMB_N_MAX` is derived from `TB_EMBLOG2_MAX`, which mirrors `rtl/seq_unit.sv`'s `EMBLOG2_MAX`, with an elaboration assert. The quotation above is the pre-fix text, kept as the record; post-fix site `evidence/qwen9b/g3/G3_4_LAYER.md` §15.2 |  <!--cites:noquote-->
| `tb/tb_dn_step.sv:75-76` and `tb/tb_dn_step.sv:166` | 16384 = 128 x 128, i.e. one head's DN state | **survives LNH=32** (it is per-head); it moves only if `head_dim` does. Listed so nobody "fixes" it |
| `ref/gen_token_script.py:84` `DN_SLOTS, KV_SLOTS = 18, 6` | exact | **24 / 8** |  <!--cites:noquote-->

**Do not mine `tb/scripts_scratch/`.** `tb/scripts_scratch/d/rtl_fix/seq_movers.sv:170`
carries `SCR_WORDS = 16384` — the **pre-R-b** value, in a scratch tree. It is not
a migration site and it is not a reference.

### 7.6 The ISA re-encoding's blast radius — the implementation census

§4.3's re-encoding is the change with the widest reach in this migration, and a
bit-budget script that checked only the RTL and the emitter would prove nothing
about the rest. **Counted precisely, because an earlier revision said "five
independent implementations" and that is not what the tree holds:** the pair
layout is implemented *independently* in **three** places — the canonical
emitter, `sw/chat_seq.py`'s decoder, and the RTL — while two further sites
delegate to the canonical helpers and hand-code only the DNST bit-30/31 scatter.
**Five sites need an edit; three of them are independent implementations.** That
distinction matters for G3: an encoder-vs-decoder equivalence check has three
things to reconcile, not five. Every line below is verified.

> ### PRE-G3.1 ROWS, KEPT AS THE RECORD — dated note 2026-09-01 (Task 7)
>
> Rows in this section marked `<!--cites:noquote-->` quote **SEQ_ISA v1.7
> source that G3.1 DELETED**, not source that merely moved.  They are kept
> verbatim, because they are the record of what the pre-G3 tree said and the
> argument this section makes rests on them (§0: nothing is deleted or
> struck).  The exemption marker is used for exactly the reason §7.6 gives —
> *"an exemption is for source that no longer exists, not for a citation that
> has merely moved"* — and every citation that had merely MOVED was
> RENUMBERED instead, mechanically, by
> `evidence/qwen9b/o3/o3_cite_drift.py --base d2d774b`.
> **The post-G3.1 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_1_ISA.md` §15.**

**A — the canonical implementation.** `ref/gen_layer_script.py`:
`enc_saddr` `ref/gen_layer_script.py:359-369`,
`enc_isa_saddr` `ref/gen_layer_script.py:371-382`,
`enc_a1` `ref/gen_layer_script.py:385-388`,
`dec_a1_lo` `ref/gen_layer_script.py:391-392`,
`dec_a1_hi` `ref/gen_layer_script.py:395-396`,
`enc_alu_a2` `ref/gen_layer_script.py:399-407`,
`dec_alu_dst` `ref/gen_layer_script.py:415-416`;
layout comment `ref/gen_layer_script.py:318-342`;
DNST hand-ORs bits 30/31 at `ref/gen_layer_script.py:944`.  <!--cites:noquote-->

> ### RENUMBERED AND PARTLY SUPERSEDED 2026-09-01 at G3.1 (Task 7)
>
> **The LANDMARKS above are the post-G3.1 ones; the DESCRIPTIONS beside two
> of them are PRE-G3.1 and kept as the record of what changed** (§0: nothing
> is deleted or struck).  SEQ_ISA v2.0 deleted the bit-scatter, so
> `enc_a1`/`dec_a1_lo`/`dec_a1_hi` now pack `{hi[31:16], lo[15:0]}` with no
> borrowed bits, `enc_alu_a2` packs `{dst[31:16], p0[15:0]}` and gained the
> partner `enc_alu_a0` (the relocated `p0[16]`, `ref/gen_layer_script.py:409`)
> plus `dec_alu_len` (`ref/gen_layer_script.py:419`) and `dec_alu_p0`
> (`ref/gen_layer_script.py:423`); and **"DNST hand-ORs
> bits 30/31" no longer happens at all** — the two scalar pointers moved to
> the DNSB CSR, so DNST's emit line is a plain `self.C(8, head, …)`.  The
> post-G3.1 landmark for every row of §7.6 is tabulated in
> `evidence/qwen9b/g3/G3_1_ISA.md` §15.

> *(**Amended 2026-08-31 at G2a**, then **corrected again at the review's
> second pass**. **RETRACTION**: the previous revision of this note claimed the
> landmarks "were re-derived from the file rather than adjusted by hand". They
> were not — all nine were uniformly 19 lines low, which is the signature of a
> stale batch, and the claim of having re-derived them was the least accurate
> sentence in the section. They are re-derived now, and the reason the checker
> never objected is stated in §8 G2's limitation list: none of these nine
> citations carries a quotation on its own line, so `QUOTE` never fires and
> `RANGE` is satisfied by any in-file number. `enc_saddr`'s assert used to name *"the
> 15-bit ISA range 0..32767"* and range-check `SCRATCH_MAX`. G2a split the two
> ceilings that one name was conflating: `SCRATCH_MAX` is now the scratch
> ARRAY depth, 65,536 (§4.3 S4), checked by `enc_saddr`, while what an ARG word
> can CARRY is `ISA_SADDR_MAX = 32768`, checked by the new `enc_isa_saddr`,
> whose message still names the 15-bit ISA range and refuses a 9B layer body
> until this section's re-encoding lands. **Raising the array ceiling alone
> would not have refused a 9B address — it would have CORRUPTED one**:
> `enc_a1` packs a PAIR, so `lo = 40000` puts `lo >> 14 == 2` onto bit 29,
> `hi`'s bit. `evidence/qwen9b/g2/isa_guards_check.py` trips every one of
> these guards RED and GREEN.)*

**B — independent re-implementations of the same bit layout.** Each needs its own
matching edit; none of them imports the helpers.

| site | what it re-implements |
|---|---|
| `sw/chat_seq.py:1709-1713` `_lo`/`_hi` inside `_cmd_scratch` (`:1698`) | the whole pair unpack, plus DNST bits 30/31 at `:1740-1741` and ALU `dst[14]`→bit 31 at `:1750`. **Its docstring at `:1701-1702` already cites stale line ranges** for the two files it mirrors — the rot this spec's §9 D-CITE row is about |
| `ref/seq_model.py:608-609` | DNST bits 30/31, open-coded inside the reference executor `_layer_cmd` (`:424`, dispatch `:432-638`) |
| `rtl/layer_chan.sv:1221-1224` | `a1_src`/`a1_dst`/`a2_src`/`a2_dst`; plus `:871-872` for `vec_alu`, `:1192-1193` (DNST `a_dec`), `:1723-1724` (DNST `a_beta`), `:1434` (GATE dst) |
| `tb/scripts/gen_seq_layer_script.py:158-161` | imports the helpers at `:43` but hand-ORs the DNST ARG0 pack and bits 30/31 itself; layout commentary at `:156`, `:244`, `:315`, `:321` |

**C — a LEGACY packer that never learned the 15th bit**, and it matters because
it is the vector generator whose output a live TB replays:
`tb/scripts/gen_seq_unit_vectors.py:547-554` — `:550`
`a1 = (srca & 0x3FFF) | ((srcb & 0x3FFF) << 14)` and `tb/scripts/gen_seq_unit_vectors.py:551`, still 14-bit, with  <!--cites:noquote-->
no bit-14 scatter at all. At 16-bit addressing this does not merely need
widening — **it encodes a layout that will no longer exist.**  <!--cites:noquote-->
*(An earlier revision listed a second file here,
`tb/scripts/gen_seq_vectors.py:423-430`, which carried byte-for-byte the same
packer. That file was **dead** — §7.5 E and §9's D-DEAD — and **G2a DELETED it
on 2026-08-31** rather than migrating it. It is therefore **out of G3's
mechanization scope**; listing it both as "delete" and as "a packer that
matters" was a contradiction an earlier fix round removed. The line reference
above no longer resolves and is kept only as the record of what was deleted —
`evidence/qwen_next/spec_cites.py` reports it as `RETIRED`.)*

> **Post-G3.1 landmark, dated note 2026-09-10 (pre-ship tool chore, review
> m11).** The three coordinates in the paragraph above are marked
> `<!--cites:noquote-->` under §7.6's own rule, and they are stale in MEANING
> as well as in wording: G3.1 rewrote that packer onto `GLS.enc_a1`, so those
> lines of `tb/scripts/gen_seq_unit_vectors.py` carry no 14-bit `a1` pack at
> all. *(Corrected 2026-09-10, fix round 2, re-review m12: this note named
> `xop()` for all three coordinates, which is true of one of them.
> At HEAD `tb/scripts/gen_seq_unit_vectors.py:550-551` are the body of
> `csr_layer_w`, and only `tb/scripts/gen_seq_unit_vectors.py:554` is `xop`'s
> own def line; `tb/scripts/gen_seq_unit_vectors.py:547-554` spans both.
> The row this note sends the reader to states it exactly —
> `evidence/qwen9b/g3/G3_1_ISA.md:925`.)* Nothing is
> renumbered here — a marked row is
> kept verbatim as the record of what the pre-G3 tree said. Per the dated
> note that opens this section, **the post-G3.1 landmark for this row is
> tabulated in `evidence/qwen9b/g3/G3_1_ISA.md` §15**, which is where a
> reader who wants today's code should go.

**D — the crack-and-rebuild site.** `ref/seq_format.py` is **not** a fourth
independent implementation, and an earlier revision of this spec implied it was:
it imports the canonical helpers at `ref/seq_format.py:140-142`. It is nonetheless the largest
consumer, with ~35 sites that open ARG words and rebuild them — the peephole
emitter `_cmd` at `ref/seq_format.py:1343` (ARG CSRWRs `ref/seq_format.py:1366-1368`), `ALU_LEN_MAX` at `ref/seq_format.py:1324`,
the `disasm` decoders at `ref/seq_format.py:762-777`, the attention block at `ref/seq_format.py:1575-1587`, the DN
block-float rewriter at `ref/seq_format.py:2038-2066`. *(An earlier revision claimed one of these was a latent inconsistency — that
`ref/seq_format.py:1655` re-packs an ALU `a2` as `(new_p0 & 0x1FFFF) | (dst <<  <!--cites:noquote-->
17)` and thereby drops `dst[14]`. **That was fabricated and is withdrawn.**
`rtl/layer_chan.sv:873` reads `.cfg_dst({arg2[31], arg2[30:17]})` — a  <!--cites:noquote-->
**contiguous** `[31:17]` field — so `dst << 17` places `dst[14]` on bit 31 by
construction. The two encodings agree over the full range; there is no
inconsistency to fix.)*

**E — the normative docs.** `docs/SEQ_ISA.md:804` states the pair layout and
`docs/SEQ_ISA.md:810-826` is the per-op bit-14 table — **note the 767, not 766**:
the last row is ALU's `dst`, `ARG2 = {dst[30:17],p0[16:0]}` with `dst[14]` on bit
31, which is exactly the row §7.6 D's withdrawn claim turned on, so a range that
stops at 766 omits the one line a reader would need. SEQ records at
`docs/SEQ_ISA.md:846-848`; the DNST ARG0 note at `docs/SEQ_ISA.md:828-837`; and
the in-RTL copy at `rtl/layer_chan.sv:120-175` and `rtl/layer_chan.sv:1277-1285`.

**Consequence for G3**: the mechanization must cover A, B, C and D — encoder and
every decoder — not the RTL field list and one packer. §8 G3 carries that.

---

## 8. The gates ladder

Sim → build → board, in the house style. **The 2B spec's R-b gate "every frozen
0.8B stream replays bit-exact on the widened RTL" is deleted by U4** (§3.1) and
the ladder is numbered fresh; there is no earlier numbering for these gates to be
renumbered from. Every gate produces a committed gate doc under
`evidence/qwen9b/<gate>/`, 4 seeds minimum on every TB/HW run, and a commit.

### G1 — the int8-DN-state fidelity rung. **STOP-BACK GATE.** — **CLOSED 2026-08-31: the STOP fired, the container is `int16` (A1).**
Host only, snoke. Fully specified in §4.1. Passes on top-1 ≥ 93/108 with the
rank/top-5/text conditions, a reproducing repeat run, and clean output from
**both** range tools (`audit_ranges` for the state, `gate_port_probe`/`gate_sat`
for the `Av` port); stops back to the user otherwise. The 9B-only
`RS_F 8 → 7` probe rides along (§4.4). **No RTL is written until this returns
PASS.** Deliverable: `evidence/qwen9b/g1/RUNG_INT8_STATE.md` +
`fixed_9b_w4g128gptq_int8_*.{json,log}` + both range-tool outputs + the launchers.

### G2 — the `ref/` chain generalized at 9B. **THE BYTE-LOCK IS CHECKED HERE, AND THEN IT IS SPENT.**

> **Exactly one change in this spec spends the byte-lock, and it is not in this
> gate.** An earlier revision of this box asserted that *two* did — the §4.3 ARG
> re-encoding and the §4.4 `RS_F` rider — and then, four lines later, said `RS_F`
> was inert. Both cannot be true. **The correct account:**
>
> * **`RS_F` does NOT spend it.** §4.4 makes `RS_F` *model-selected*; 0.8B and 2B
>   keep 8 and their emitted bytes do not move. Only the 9B value may differ, and
>   9B has no byte-lock to break. Inert, and it belongs in G2.
> * **The §4.3 ARG re-encoding DOES spend it**, unavoidably: it changes the
>   emitted ARG words at *every* geometry. That is the whole conflict, and it
>   lives in **G3**, not here.
>
> So the sequencing is:
>
> * **G2a — the lock holds, and is checked.** Everything in this gate is a
>   *host-side geometry generalization* (`VREP`, DN/KV slots, SCA strides, the
>   `sw/` literal census of §7.4) plus defect B plus the `RS_F` relocation.
>   **None of it touches the ARG layout.** All of it is supposed to be inert at
>   0.8B/2B, and `evidence/qwen2b/rc/t4_bytes_unmoved.sh` is exactly the tool
>   that proves it — the same use Track L put it to (`LADDER.md` §5b: *"the real
>   regression test, since a guard that perturbed the emitters would move
>   bytes"*). **It must pass.**
>   **Note what is NOT in G2, and why**: §7.5's TB census (families A–D) is not
>   host generalization — those are the *testbench twins* of the RTL width
>   changes §4.2/§4.5/§4.6 own, and editing a TB to expect a 16-bit address
>   before the RTL has one would break the suite, not preserve it. **§7.5 belongs
>   to G3**, beside the RTL it mirrors. An earlier revision scoped it into G2 and
>   thereby made G2's own inertness claim false.
> * **G2b — the final pin.** Immediately after G2a passes and **before** any G3
>   change lands, run it once more and **record the resulting artifact sha256 set
>   into `evidence/qwen9b/g2/FINAL_BYTELOCK.md`**. That set is thereafter the
>   record of what `build_034`/`build_035` were built from.
> * **G3 retires the lock.** The ARG re-encoding lands and
>   `evidence/qwen2b/rc/t4_bytes_unmoved.sh` stops being runnable against the
>   tree. **This spec does not keep a v1.7 emitter path**: rebuilding 0.8B/2B
>   artifacts from the post-migration tree is declared **unsupported**, because
>   those artifacts already exist, are pinned by G2b, and the bitstreams that
>   consume them are frozen. Keeping a second encoder alive to preserve a
>   regression for models this project no longer develops would re-import exactly
>   the multi-geometry cost U4 removed. Dated supersession notes land in
>   `evidence/qwen2b/rc/RC_GATE.md` and `evidence/qwen2b/rd/RD_GATE.md`.
>
> **And `rd_golden_shas.sh` is not part of this story at all.** It `ls`es and
> `sha256sum`s three `.chip` goldens and counts their MEM lines; it carries **no
> expected values and makes no comparison**, so it exits 0 regardless and
> "passing" it means nothing. It is a **recording**, not a gate — the distinction
> `LADDER.md:615` already draws when it reports `t4_bytes_unmoved` as **PASS**
> and `rd_golden_shas` merely as **rc 0**. An earlier revision of this box, and
> the first version of the `RD_GATE.md` note, both gave it gate semantics it does
> not have. Its real value is unchanged and worth keeping: it is how the golden
> bytes get *recorded*, which is what G2b needs.
>
> Anyone who finds `evidence/qwen2b/rc/t4_bytes_unmoved.sh` failing after G3
> should read this box, not debug it.

Turn Track L's refusals into generalizations (§7.1), fix defect B (§7.3), close
the `sw/` literal census (§7.4), and relocate `RS_F` (§4.4). Gates, in order:

* every `ref/` selftest exits 0 at **0.8b, 2b and 9b** — the current baseline is
  13 of 14 at 0.8b/2b, and the one failure was the pre-existing 2b
  `layer_fixed attn softmax+pv rel=3.288e-02` (§9), which had to be **owned
  before this gate could be read**. **OWNED AND CLOSED 2026-08-29 (D-TOL,
  Task 2): the BOUND was wrong and wrong at every geometry, `3e-02` → `8e-02`;
  the 2B `layer_fixed` selftest passes on `main` for the first time and the
  three-tag sweep is 21/21 exit 0 at 0.8b/2b/9b**
  (`evidence/qwen9b/g2/D_TOL.md`, `evidence/qwen9b/g2/ref_selftests_dtol.log`);
* **G2a's byte-lock** and **G2b's final pin**, per the box above;
* **`evidence/qwen_next/spec_cites.py` runs clean on this spec, and its
  `--selftest` negative control passes.** This exists because the spec's
  citations were hand-swept twice and review found drift **both** times — the
  second time in the prose that was correcting the first. The checker resolves
  every `file:line`, range-checks it, verifies quoted source text sits near the
  line it is attributed to, and refuses a bare `:NNN` continuation on any line
  naming more than one file (the defect class that produced five wrong bindings
  in one revision). It is a **gate on the document**, run before every commit
  that touches it. **Known blind spot, stated so PASS is read correctly**: a
  citation that is right-file, in-range, and carries no quotation can still
  point at the wrong line — the checker cannot see that class (two such
  survived a clean run in this spec's own review), so `SPEC CITES: PASS` is
  necessary, not sufficient; semantic spot-checks remain review work.
  **And the blind spot is wider than "carries no quotation" makes it sound:
  a `QUOTE` check fires only when the quotation shares a MARKDOWN LINE with
  its citation.** A citation on a line of its own — which is every entry in a
  multi-line list, and most table cells that name a symbol in prose — is
  range-checked and nothing more. G2a shipped nine such citations in §7.6 A
  that were uniformly 19 lines wrong and passed clean, twice. **"Run the
  checker last" does not cover this class**, because the checker was never
  going to object; only reading the cited line does. *Scope note:* it currently reports 34 pre-existing short-form
  citations in `evidence/qwen2b/rc/RC_GATE.md` and
  `evidence/qwen2b/rd/RD_GATE.md` that this migration did not write; cleaning
  those is optional follow-on work, not a G2 requirement;
* the 9B golden chain builds end to end: bf16 torch golden, quantized W4 g128 +
  GPTQ image set, SEQ streams, `plan_weights` fit recorded with the busiest-channel
  numbers, both range tools clean or waivered with evidence;
* the fidelity harness at 9B reproduces G1's numbers through the *emitted*
  chain, not just the reference model.

### G3 — the RTL, the ISA, and the golden decoders
Implement §4.2–§4.6 and §5.1–§5.4. **This is where the byte-lock is spent**
(G2b). Gates:

* full Verilator TB suite clean, `-Wall`, 5.020, 4 seeds; heavy sims on snoke,
  one `obj_dir_<name>` each, never two hosts on one obj_dir;
* **the ISA re-encoding is mechanized, not asserted**, and its scope is **the
  RTL field list, the emitter packers, AND every golden decoder** — §7.6's
  census names **five sites: three independent implementations** of the pair
  layout (the `gen_layer_script` encoder, `sw/chat_seq.py`'s decoder, and the
  RTL itself) **plus two that delegate to the helpers but hand-code the DNST
  bit-30/31 scatter**, and a bit-budget script that reads only the encoder and
  the RTL would prove nothing about the decoders or the hand-coded scatters.
  The script must show every command fits its arg words *and* that
  encoder and decoders agree, with a **negative control** (perturb one field
  width, watch it refuse) in the style Track L's review round established
  (`LADDER.md` §5b);
* the DNST scalar-pointer assert fires on a perturbed SCA layout **and** on a
  layout whose beta/decay split moves (§4.3);
* the synthesizable envelope checks (§5.4) are proven to fire in sim and proven
  **not** to fire on the 9B stream;
* `docs/SEQ_ISA.md` updated to v2.0 with the new pair layout — and the old
  15-bit tables retained, marked as `build_034`/`build_035`'s ISA, because those
  bitstreams still run.

### G4 — full-9B sim replay, and the OOC structure gates
* `seq_model` / `layer_fixed` lockstep across a full 9B token, then a multi-token
  run, bit-exact against the emitted chain;
* torch-golden lockstep in sim;
* **OOC synthesis on the real RTL**: URAM count = ~~**592** as §4.1 predicts~~
  **928 as §4.1's W1′ requires (A1.5)** — 24 × 29 = 696 DN + 232 KV — BRAM
  against §4.3's figure, and the four-`matvec_chan` LUT delta against §5.1's
  −5,826/channel. **Also check what `DN_PIPE = 2` is supposed to cost and
  nothing more**: FF up by ≈ 24.7 K (≈ 1 % of the device), **LUT unchanged**,
  **URAM unchanged at 928**. A LUT or URAM move here means the pipelining was
  not implemented as Track P implemented it. **This closes the COUNT half only**
  — Track P placed `wide` and got 928, so a disagreement would be news; the
  **timing half is G5a's**, not here;
* `p_acc` headroom at K=12288 checked rather than argued (§4.6);
* **the layer-term cycle census, which the study names as its own cheap
  closure.** Feasibility §6 item 1 says the layer term "has no measurement", that
  its coefficient is a two-point fit intercept, and — the part worth acting on —
  that "closing it properly means a `dn_step`/`layer_chan` simulation at LNH=32,
  **which needs only Verilator — no board, no synthesis**." §10's 33.9 % layer
  share is the single largest modelled unknown in this build, and it can be
  measured here for the cost of a sim. **Run it before G5**: count cycles per
  DNST at LNH=32 against the RTL's own ~1300/head, and record the measured layer
  term beside the modelled 47.00 ms. If they disagree materially, §10's band is
  re-derived **before** a build is spent on the assumption.

### G5 — timing
* **G5a — the OOC floorplan experiment** (§6.2), before any full build.
  > **AMENDED 2026-08-31 (A1.3).** G5a's variant list is replaced (§6.2's
  > supersession block) and **its status changes from de-risking to
  > load-bearing**: the write-control fan-out pblock is the only proposed route
  > to closing the binding path, and **if it does not close, option B has no
  > known route and the target goes back to the user** with O1 re-opened at
  > option 3 or D. G5a is now a gate that can fail the campaign, not just a
  > measurement that informs G5b.
* **G5b — the full build**, on snoke via `synth/scripts/launch_build.sh`, fresh
  `synth/out_build_<n>/` per roll, clock-sanity gate intact. Multi-roll spread
  with different placement directives; census → reroll → phys_opt per the
  playbook. Report WNS/TNS before and after every change. Gate doc records the
  per-SLR URAM/BRAM/DSP census, the endpoint census, and every waiver decision
  with the user.
  **Pass criterion, stated so the gate can be failed:** WNS ≥ 0.000 and WHS ≥
  0.000 on all clocks with **zero failing endpoints**, no waiver — i.e. what
  build_035 achieved, which is the standard this project set for itself and the
  first bitstream in its history that needed no waiver. **A negative WNS is not
  a pass and is not this agent's to accept**: build_035's own record is that
  waiving −0.004 was declined by the user (`docs/HISTORY.md:791-792`), so any
  proposal to ship negative goes back to the user as an escalation with the
  endpoint census attached, exactly as `TIMING_035.md` §9 and §12 did. Expect
  this to take several rolls: seven rolls on build_035's floorplan spanned
  −0.004 … −0.428 and **no roll ever measured 0.000** (§6.3).

### G6 — board bring-up
Safe reprogram flow every time: `sudo -n sw/pcie_helper.sh remove` →
`sw/program_fpga.sh` (JTAG, **volatile only, never flash**) →
`sudo -n sw/pcie_helper.sh rescan`. **No DMA before CSR CALIB = 0xF.**
There is **no 0.8B/2B back-compat ladder on this bitstream** (U4) — the ladder is
9B from the first token:

1. CSR identity: MAGIC, VERSION = the new netlist hash, CALIB 0xF, UPTIME;
2. `seq_run --dry-run`, then nch=1, then nch=4;
3. **weight upload**: ~3,902 MiB of W4 g128+GPTQ weights + the 1,940.0 MiB
   embedding table, **readback-verified per PIECE, not per channel** — RD_GATE
   §4.2's lesson, where a whole session ran on a 61.3 MiB-stale LM head and
   answered with the wrong token, silently, because the residency probe took one
   witness per image per *channel* and the head is chunk-interleaved. **Carry
   RD_GATE's second fix too**: a miss re-uploads the **whole pack** — a branch
   that is *selftest-proven only*, because on hardware every miss set was already
   all-187 and it never fired (`docs/HISTORY.md:767-770`), so 9B is the first
   real chance to exercise it. **And take RD_GATE follow-on 2 while here**:
   replace the witness sample with the **whole-pack hash** (`evidence/qwen2b/rd/rd_residency_audit.py`
   reads 1,847 MiB in ~3 s at 2B; at 9B's ~5.8 GiB budget ~10 s), which retires
   the sampling question outright — §4.2 measured the witness sample at roughly
   one detection per three damaged pieces;
4. EMBLOG2 13 written **and read back** (§5.3);
5. lockstep vs `seq_model` — golden state checks, 0 mismatches;
6. `chat_seq --verify`, then greedy chat, then sampled chat with 4 seeds
   (seed-deterministic ×2 identical, seed-sensitive on a different seed);
7. **perf census**: measured tok/s against §10's modelled 7.21, the per-channel
   matvec spread, the `L_LCYC` layer term — reported **measured, not modelled**;
8. the residual clip counters recorded on-chip, so §4.4's fragility is observed.

### G7 — merge and ship
Branch `qwen9b` off `main`, in-place; commit at every green gate. **The merge
happens HERE, at G7, gated on G6 having passed** — the 2B campaign's shape,
where gate D authorized the merge but it was held until R-d passed on silicon
(`docs/HISTORY.md:772-773`, `:811-813`). *(An earlier revision of this line said
"merge at G6", which contradicted its own heading; G6 is the precondition, G7 is
the act.)* `git merge --ff-only`, and **STOP if `main` moved**. Deliverables: gate
docs, the follow-on list, and `NEXT_SESSION.md` rewritten to the new resident
state — **including the two-bitstream operational note of §3.2 and the board-lock
ruling O3.**

---

## 9. Known-defect register, carried into this migration

> ### PRE-G3.3 ROWS, KEPT AS THE RECORD — dated note 2026-09-02 (Task 9)
>
> Rows here marked `<!--cites:noquote-->` quote **source that G3.3 DELETED**,
> not source that merely moved: the 6-bit `cfg_ng` / `x_line` / `g_q…g5_q` / `r_g` declarations, the `wbeats` and `ng7` wires, the 1536-word `x_mem`, and the 6 KiB XWIN decode with its 11-bit pointers.  They are kept verbatim, because they
> are the record of what the pre-G3.3 tree said and the argument they support
> rests on them (§0: nothing is deleted or struck).  The exemption marker is
> used for exactly the reason §7.6 gives — *"an exemption is for source that
> no longer exists, not for a citation that has merely moved"* — and every
> citation that had merely MOVED was RENUMBERED instead, mechanically, by
> `evidence/qwen9b/o3/o3_cite_drift.py --base a08a90b`.
> **The post-G3.3 landmark for every row so marked is tabulated in
> `evidence/qwen9b/g3/G3_3_MATVEC.md` §11.1.**

Each row has an owner-gate. A row without one is a bug in this spec.

| # | defect | status | owner |
|---|---|---|---|
| **D-B** | `sw/infer.py:798-802` — four hard `1024`s on the **online** `step()` path; silently wrong for three lines, then crashes. Severity measured, not reasoned (`CORRECTIONS.md` C2) | **CLOSED 2026-08-31 at G2a** | **G2 — DONE** (§7.3). All four are `LR.H`; the four sites are now `sw/infer.py:814-817` and `sw/infer.py:819`. Regression `evidence/qwen9b/g2/damage_defect_b.py` puts the literals back and requires the failure, run at 2b and 9b |
| **D-TOL** | `FABLE5_MODEL=2b ref/layer_fixed.py` fails `attn softmax+pv rel=3.288e-02` against a `3e-02` bound. **PRE-EXISTING on committed main** — a pristine `git archive HEAD ref` tree reproduces the identical value (`head_baseline_layer_fixed_2b.log`), so Track L's diff is exonerated. ~~A 0.8B-tuned bound the 2B geometry overshoots by **9.6 %**, failing silently until Track L noticed~~ **CORRECTED 2026-08-31 — see the block below the table** | **CLOSED 2026-08-29 at G2 (Task 2).** Bound `3e-02` → **`8e-02`** | **G2 — DONE.** Gate doc `evidence/qwen9b/g2/D_TOL.md`; evidence commit `f3da761`, review round `a971813`. The code was ruled RIGHT and must not be touched: the per-term round into `Q.QKV_F` that dominates the error is a line-for-line mirror of shipped silicon over the reachable domain |

> **D-TOL CORRECTION (2026-08-31, from the G2 ruling).** The row above framed
> this as *"a 0.8B-tuned bound the 2B geometry overshoots by 9.6 %"*, and
> §4.3's `ref/layer_fixed.py` prose repeated it. **That framing is DISPROVEN,
> and it points a reader at the wrong fix** — someone following it reaches for
> a per-geometry bound, which Task 2 showed to be a fiction.
>
> **There is no 9.6 % geometry overshoot.** The quantity `rel` bounds is
> **geometry-independent**: `T` and `HD` are 48 and 256 at 0.8B, 2B, 4B *and*
> 9B, the block indexes ONE head, and `NQ`/`NKV`/`LNH`/`LNKH` never enter it.
> The only coupling to `H` is **not an input to the block at all** — it is an
> offset into a shared RNG stream: the `rmsnorm1p` check twelve lines above
> draws `2*LR.H` normals from the same `default_rng(21)`, so `2.666e-02` at
> 0.8B and `3.288e-02` at 2B are **the same computation on two different
> draws**. A zero-degree-of-freedom replay that varies nothing but `H`
> reproduces both committed values to every printed digit and predicted the 9B
> value `3.918e-02` before it was run
> (`evidence/qwen9b/g2/dtol_probe.py`, `evidence/qwen9b/g2/dtol_probe.log`).
>
> **What was actually wrong was the BOUND, and it was wrong everywhere.**
> Measured over 40,000 draws of the identical block: mean `3.3030e-02`,
> sd `6.681e-03`, max `6.749e-02`, and **`P(rel >= 3e-02) = 0.6626`** — the old
> bound sat at the 34th percentile of the thing it was bounding and
> false-failed two runs in three. `8e-02` was chosen from a measured
> detection/false-failure table over five deliberate-damage classes, and the
> gate doc records what it does NOT catch (a one-bit PV-accumulator narrowing,
> 7.5 %, whose damaged distribution overlaps the healthy one) rather than
> claiming a coverage it does not have.
>
> **Two consequences for anyone reading this row later.** The old bound would
> have blocked 9B on arrival — that 9B selftest run contains exactly two `FAIL`
> lines, this check and the summary it causes, and every other check passes at
> 9B untouched. And `T = 48` is the selftest's own literal, not a context
> length: `rel` is linear in `T`, so this bound is a statement about `T = 48`
> and no gate doc should quote it as an attention-error bound at a real
> context. `evidence/qwen_next/ladder/LADDER.md:404` / `:462` and
> `evidence/qwen_next/ladder/CHECKPOINT_VERIFY.md:240` carry the same
> superseded framing; they are Track L's committed evidence and were accurate
> when written, so they are named here rather than edited.
| **D-TOK** | **UPGRADED from cosmetic to blocking.** `sw/tok_meter.py:330` calls `plan_weights(man, wdir)` **without `rows_of`** — the nch-independent path — so `RD_GATE.md:599-605` records as follow-on 3 that it ***"cannot plan a 2B pack"***: it "collides with `EMB_BASE` and aborts before any DMA". At 9B's 3,902 MiB it cannot plan the pack either. Secondary: the docstring at `sw/tok_meter.py:41-43` carries 2B head arithmetic; `sw/tok_meter.py:514-515` uses an `n*2` embedding stride that agrees with a shift by EMBLOG2 at 9B only by coincidence | **CLOSED 2026-08-31 at G2a** | **G2 — DONE.** Taught it the repack (`hwmap`/`seq_run` learned it at T3; `tok_meter` was not on that list) and turn the stride coincidence into an assert. **G6 step 7 must not depend on it**: until it is fixed the census comes from `evidence/qwen2b/rd/rd_census.py`, exactly as R-d did. *(**Citation note, 2026-09-10.** The first column's pointers are re-anchored to HEAD and now name the POST-fix file: `sw/tok_meter.py:330` is the single-channel branch that still calls `plan_weights(man, wdir)` unchanged, `sw/tok_meter.py:328` is the repacking call this row asked for, and the embedding stride is an assert rather than a coincidence. The defect this row describes is the pre-G2a file's; the line numbers are HEAD's.)* |
| **D-STAGE** | **`tb/scripts/gen_chat_i1_vectors.py:298` `stage = np.zeros(16384, dtype=bool)` is a stale duplicated constant.** It is **correct today at the 0.8B default** this generator runs at — an earlier revision of this row called it "wrong TODAY against the 32,768-word scratchpad", which overstates it, and the harm it does is **under-coverage, not a false pass**: the `keep` computation at `tb/scripts/gen_chat_i1_vectors.py:301` simply cannot name a word at or above 16384, so a staging window in the upper half would go unchecked rather than mis-checked. The defect is that the number is a bare literal where its siblings derive theirs from `SCRATCH_WORDS` in `sw/hwmap.py:215` | **CLOSED 2026-08-31 at G2a** | **G2 — DONE.** Derived from `sw/hwmap.py`'s `SCRATCH_WORDS` at `tb/scripts/gen_chat_i1_vectors.py:305`; whether deriving it moved an i1 golden is measured, not assumed, and recorded in `evidence/qwen9b/g2/G2A_HOST.md` |  <!--cites:noquote-->
| **D-TBUNIT** | **`tb/tb_seq_unit.sv:967`** truncates the golden MEM address to 15 bits **inside a checker**, with no range guard at the parse site (`tb/tb_seq_unit.sv:457-473`). At 16-bit addressing an out-of-range golden address aliases down by 32K and the checker **silently compares the wrong word**. It is an unfixed instance of a bug already diagnosed and fixed in its sibling — `tb/tb_seq_chip.sv:76-86` documents it, `tb/tb_seq_chip.sv:614-616` guards the parse, `tb/tb_seq_chip.sv:923` derives the slice | open | **G3** — copy `tb_seq_chip.sv`'s fix; do not re-invent it |
| **D-DEAD** | **`tb/scripts/gen_seq_vectors.py` appears to be dead code** — `tb/Makefile` references it only in a comment (`tb/Makefile:289`) and never invokes it; it is a stale near-copy of the live `tb/scripts/gen_seq_unit_vectors.py`, still carrying pre-R-b 14-bit masks. `docs/QWEN35_NEXT_FEASIBILITY.md:790` lists it as a migration site, and an earlier revision of **this** spec did too — which would have sent someone to migrate a file no test runs | **CLOSED 2026-08-31 at G2a — DELETED** | **G2 — DONE.** Confirmed unreferenced first (one comment in `tb/Makefile`, no invocation), then deleted. `evidence/qwen_next/spec_cites.py` gained a `RETIRED` set so citations to it report as retired rather than failing, and its `ALIAS` short form was dropped |
| **D-N7** | `ref/load_qwen35.py:411` `head = emb.copy() if tied else st.get(head_key)` — `SafeTensors.get` already returns a fresh copy, so the tied branch allocates a **second** full float32 table (0.95 GiB at 0.8B, 2.03 GB at 2B), defeating the deliberate frees at `ref/gen_model_script.py:524` and `ref/seq_chat.py:1375`. **9B is untied and pays nothing** | recorded, deliberately not fixed | **Not this migration.** The one-word fix (`head = emb`) is safe only after auditing every `load_model` caller in `ref/`, `sw/` and `tb/scripts/` for in-place mutation; aliasing without that audit trades a memory cost for a **silent correctness bug**. Noted at the site with its price. Carried forward |
| **D-LOCK** | Board-lock convention for the shared BCU-1525 — two worktrees, one board, `sw/.seq.lock` is per-checkout. Now sharper: two live bitstreams | open since R-b | **O3** — needs a user ruling; written up at **G7** |
| **D-GATEPORT** | **ADDED 2026-08-31 (A1.9). The checkpoint's DeltaNet gate values exceed the frozen `gate_unit` ports, and the production clamp silently changes what 60 of 768 heads compute.** Measured at G1 by `evidence/qwen2b/q2/audit/gate_port_probe.py` (forked to run at 9B's four shards): **max `A` = 76.9957 against a port of [0, 8); max \|`dt_bias`\| = 18.5 against ±8; 49/768 heads out of uint18 Q15 and 12/768 out of int16 Q12 before the clamp; and 60/768 heads have their DECAY CHANGED by it** — worst `L12 h18` 0.13895 → 0.81458, a head that has stopped forgetting. The 2B audit found **1 of 288**. **It is OPTION-INDEPENDENT**: it is a property of the checkpoint against frozen ports, not of the state container, so the int16 ruling does not touch it. On the same checkpoint minutes apart, `ref/audit_ranges.py` reported this port **PASS** three times — one tool would have given it a clean bill of health, which is why §4.1(d) required two. **Unpriced at scored resolution**: one 168-step `--diag gateport` point (≈ 7 h) is what would price it | open, **carried into the RTL phase** | **G3/G4** — the ports are `rtl/gate_unit.sv`'s and this build re-opens that module for NH = 32 (§4.6 wall 10), so widening `A`/`dt_bias` is cheapest there if it is done at all. **G6 must record it either way**: a decay clamp that changes 60 heads is a standing property of the shipped machine and belongs in the board gate doc, not only in G1's |
| **D-CITE** | **Stale citations, enumerated rather than silently corrected** — the promise this spec's preamble makes, now backed by `evidence/qwen_next/spec_cites.py`. *In the primary sources:* `ref/gen_layer_script.py:493` is truly `ref/gen_layer_script.py:494`; `ref/gen_layer_script.py:513` is truly `ref/gen_layer_script.py:514`; the `q_src` loop cited as `~1010` is `ref/gen_layer_script.py:1162-1165`. *In the code:* `ref/gen_layer_script.py:1068-1090`'s docstring self-cites; `sw/chat_seq.py:1701-1702` cites `ref/seq_model.py:303-415` for a dispatcher now at `ref/seq_model.py:424-697`, and `ref/gen_layer_script.py:265-499` for helpers now at `ref/gen_layer_script.py:492-824`; `rtl/layer_chan.sv:331`'s "16K x 16" comment (the arrays are `[32768]`); `rtl/matvec_engine.sv:262` points at "matvec_chan.sv:531-535" where the XWIN SLVERR is at `rtl/matvec_chan.sv:613-614` and `rtl/matvec_chan.sv:614`; `rtl/matvec_engine.sv:265`'s "(:747)" where the `cfg_ng` assert is at `rtl/matvec_engine.sv:716-719`. **And the ones this spec itself got wrong and now names:** `GD` is at `ref/gen_layer_script.py:87`, where an earlier revision cited line 81; `ref/gen_layer_script.py:131` and `ref/gen_layer_script.py:223` were cited as 118 and 210; and **five bare `:NNN` continuations bound to the wrong file** on lines naming more than one — the defect class `spec_cites.py`'s AMBIG check now refuses outright | found | **G3** — fix every in-tree comment while touching those files; the primary sources' own are left as-is with this row as the record. *(`ref/load_qwen35.py:367`'s stale "24-layer" docstring was on this list and is **fixed in this commit**, so it is off it.)* |  <!--cites:noquote-->

---

## 10. Perf expectation

**Modelled: 7.21 tok/s at nch=4, steady state** (`E`, feasibility §4.4, W4 g128
row) — step **138.61 ms** = matvec 58.95 + movers 32.66 + layer 47.00. Band at
the ±10 % layer allowance: **6.98 – 7.47**. That is **0.44×** the 2B's measured
16.52 tok/s. Time split: matvec 42.5 %, movers 23.6 %, layer 33.9 %.

**Every softness of that model, stated up front so the gate docs do not have to
re-derive them:**

1. The whole of §4 is labelled **E**.
2. `(r, m) = (1.1037, 0.9117)` are **exactly determined** by two nch=4
   equations, so the model has **no residual at its own calibration points and
   cannot be validated by them**.
3. **The one out-of-sample test FAILS.** nch=1, which nothing was fitted to:
   predicted 45.776 ms against **measured 45.018** = **+1.7 %** (or +3.1 % at
   `m = 1.000`). The counters are sound — they reproduce MOVER_NORM's nch=1
   busiest beats **exactly** (6,522,432) and its mover total to 0.2 % — so **the
   miss is in the model, not the census.**
4. **The r-bracket validation is RETRACTED.** Re-anchored on R-d's 15.128 ms
   layer term, MOVER_NORM's bracket becomes `r ≤ 1.0851`, and this model's
   `r = 1.1037` sits **1.7 % outside it**.
5. **The layer coefficient is a fit intercept, not a measured cost.** Both
   calibration points share DeltaNet geometry, so the head-indexed term (77.1 %
   at 0.8B) is *whatever is left* after the width term explains 0.8B→2B.
   **Nothing measured the DeltaNet contribution directly.** What *is*
   primary-source is its **scaling law**: one `dn_step` instance
   (`rtl/layer_chan.sv:525`), one head per command (`:1275`), ~1300 cycles/head
   (`rtl/dn_step.sv:13-14`), and a real-stream census of 288 DNST/token =
   18 × 16 → **768 = 24 × 32 at 9B, a 2.667× serial increase.** The DNST
   commands alone are 12.8 % of the intercept.
6. **The ±10 % layer allowance is an assumption, not a derivation.**
7. The optimistic layer bracket an earlier revision carried is **retracted
   outright** — the lane array is already fully occupied at 128 lanes across
   LDK=128, so 32 heads have no idle width to hide in.
8. The CSRWR/CMD mover terms are **scaled by image count, not counted** — ~0.9
   ms, flagged.
9. Prior calibration ran **3.7 % hot** on the 2B layer ratio (projected
   +23.1 %, silicon measured +18.7 %). **Not labelled (S)**, because (S) means
   *this* document's arithmetic and this is the feasibility study's — but it is
   arithmetic, not a measurement, and the study says so: `RD_GATE.md` §3 states the miss as **−3.6 % on
   the ratio** (1.1872 / 1.2314), and the reciprocal 1.2314 / 1.1872 = 1.0372 is
   "this document's arithmetic on those two numbers" (feasibility §4.3). Carried
   with the same label here.
10. The DDR-rate uncertainty is **not** what dominates; the layer term is.
11. **7.21 tok/s is DECODE ONLY. Prefill was never modelled** (feasibility §6
    item 7), and at these step times a batched-prefill rung "becomes much more
    valuable than it was at 2B, and that is unquantified". Any user-facing
    latency number — first-token, or a chat turn — is **not** this figure, and
    G6 must not present it as one.

**Two things this build changes that the model does not know about**, and both
are unmodelled in the same direction — unknown:

* the int8 DN state (§4.1) changes the state memory, not the recurrence's cycle
  count, so it should be neutral on the layer term;
* stripping W8 (§5.1) does not change the W4 datapath's throughput at all — it
  is a LUT and timing item.

> ## RE-ANCHORED 2026-08-31 (A1.6) — THE FIRST BULLET IS SUPERSEDED AND THE HEADLINE MOVES DOWN
>
> **The first bullet described the int8 container.** The `int16` container is
> not neutral on the layer term, because `DN_PIPE = 2` buys its timing with
> read latency and §4.1's W1′(a) has to pay for that latency in `dn_step`.
>
> **(S) — this document's arithmetic on Track P's bound, and it carries its
> gate.** The modelled step is 138.61 ms = matvec 58.95 + movers 32.66 + layer
> 47.00, giving 7.21 tok/s. Track P bounds option (i)'s wait state at
> **≈ +10 %**, and does not say ≈ +10 % *of what*, so both readings are given
> rather than one being picked:
>
> | reading | step | tok/s | comment |
> |---|---|---|---|
> | +10 % on the **whole step** (conservative) | 152.47 ms | **6.56** | the "≈ 6.5 class" |
> | +10 % on the **layer term only** (47.00 → 51.70) | 143.31 ms | **6.98** | the wait state is a `dn_step` cost, and `dn_step` is inside the layer term |
> | option (ii), the two-outstanding restructure | 138.61 ms | **7.21** | no wait state — but nobody has written it or shown it closes |
>
> **So the expectation is ≈ 6.5 – 7.0 tok/s, headline ≈ 6.5**, and it becomes
> ≈ 7.2 only if the restructure is designed and closes. **Every softness the
> eleven items above list still applies on top of this** — the model fails its
> only out-of-sample test at +1.7 %, its `r`-bracket validation is retracted,
> its layer coefficient is a fit intercept and not a measured cost, and it is
> **decode-only**. This re-anchor multiplies a soft number; it does not firm it.
>
> **Gate: G4b's Verilator cycle census measures this directly and before a build
> is spent on it.** That census already had to count cycles per DNST at
> LNH = 32; it now also has to count them **with and without the wait state**,
> which is the same simulation run twice. That turns the ≈ +10 % from Track P's
> bound into this build's measurement, and it is the input to W1′(a)'s design
> decision rather than an after-the-fact check on it.

**Measured-not-modelled discipline for the gate docs**, which is the house rule
and the one Track L's review round enforced hardest: G6 reports **measured**
tok/s, against the model as a *comparison*, never as a substitute. Every rung is
stated against its own basis (RD_GATE §1 is the model for this). If the measured
number lands outside 6.98–7.47, the gate doc says so and attributes it — it does
not re-fit the model to the measurement and call it agreement.

---

## 11. Sequencing, logistics, effort

* **Branch** `qwen9b` off `main`, in-place in this project dir. Commit at every
  green gate, **path-limited** (`git commit -- <paths>`) — the orchestrator
  near-miss on 2026-08-25 swept another track's staged files into a commit
  (`progress.md:32`); never trust the index.
* **Machines.** Vivado builds and heavy Verilator sims on **snoke**; G1's
  quantization and fidelity work also on snoke (it is where every Track L number
  was taken, and thread counts must be **pinned and recorded**). Lighter host
  work may go to kyloren/fn2187/darthvader over NFS. **darthplagueis stays out of
  numeric compute** until it passes a memtest soak — it produced wrong arithmetic
  eight times.
* **Board.** Stays serving 2B on `build_035` until G6. **The 9B bitstream does
  not touch the board before G5b closes.**
* **First moves.** (1) G1, and nothing else — it is a STOP gate and the whole
  plan is downstream of it. (2) In parallel, and only because it is host-only
  and zero-risk: own **D-TOL** (§9), which blocks G2's readability. Nothing else
  starts.
* **Effort.** Feasibility §7.3 puts the 9B at **≈ 3–4×** the 2B campaign
  (directional, from counted `file:line` sites, not from an implementation). The
  2B was planned at "3-4 rungs, 5-7 build cycles" and executed as four rungs.
  This spec's shape is 7 gates; expect **6–10 build cycles**, and expect a
  multi-roll spread on every one of them (§6.3). §5.1's −23,304 LUTs is the only
  thing in this campaign pushing timing the *easy* way, and it is real.

## 12. Risks, ranked

1. ~~**The int8 DN state's fidelity.**~~ **RETIRED 2026-08-31 (A1) — MEASURED,
   and it is why the container changed.** G1 scored every law this spec named:
   global-`k` 72/108, per-head 83/108, per-row 94/108 MARGINAL. The risk was
   real and it materialised. **What replaces it as risk #1 is risk 3 below**,
   which the ruling promoted from a floorplan worry to the thing the target
   rests on.
2. ~~**Timing at 592 URAM**~~ **Timing at 928 URAM (96.7 % of the device),
   in-context and routed.** Track P's numbers are OOC and post-place; **nothing
   was routed, anywhere, at any geometry**. At `int16` + `DN_PIPE = 2` the
   starting point is **WNS −1.391 / 6,638 failing endpoints**, an order of
   magnitude outside the band this project's playbook has closed — and §5.1's
   −23,304 LUT saving does not help a path that is 95.9 % route in a block that
   is not LUT-bound. **Three SLRs are mandatory** (A1.4), so every DN access
   crosses at least one SLR boundary by construction.
3. **THE WRITE-CONTROL FAN-OUT — now risk #1 in substance.** Binding in every
   wide variant at both groupings, one logic level and ~96 % route, **floorplan
   untried**, and the fix collides with the 2B campaign's T5 lesson (**O4**).
   Under the 2026-08-31 ruling this is no longer one risk among several: it is
   the **only** unresolved obstacle between the chosen container and a
   bitstream, and **G5a can end the campaign on it** (A1.3). If it does not
   close, O1 re-opens at option 3 (DDR spill, a large new RTL path) or D.
4. **`matvec_engine`/`matvec_chan` re-opening** for MAX_NG=96 and the XWIN
   decode, in the block that owned build_034's worst endpoints, on a design that
   closed at exactly 0.000.
5. **The ISA re-encoding's blast radius, now counted.** §7.6 finds **five
   independent implementations** of the ARG layout, two stale legacy packers, and
   ~35 crack-and-rebuild sites in `ref/seq_format.py` alone — plus the sequencer's
   ARG shadow, `docs/SEQ_ISA.md`, and the in-RTL table. It also **spends** the
   0.8B/2B host byte-lock (§8 G2), which is the project's best regression net.
   Mitigation is G3's encoder-vs-**decoders** mechanization and G2b's final pin,
   not care.
6. **The residual rail's fragility.** Accepted, not solved (§4.4). A shift in
   the activation distribution tips more clips, and the measurement was taken at
   the rail.
7. **Model risk on tok/s.** §10 items 2–4: the throughput model fails its only
   out-of-sample test and sits outside its own re-anchored bracket, and item 11:
   it is **decode-only**. The *comparison* claims are sounder than the absolute
   ones. Partly mitigable before a build is spent — G4's Verilator cycle census
   at LNH=32 measures the largest unknown (§8 G4).
8. **Census risk, and it is the one this fix round exposed.** Two sections of
   this spec presented samples as censuses and were wrong by a factor of five
   (§7.5: five sites named, twenty-six found) and by a whole class (§7.6: five
   independent ISA implementations, of which the spec had named one). The
   corrected censuses are in the tree now, but the *lesson* is that at this
   geometry the host model of the chip is where the bugs are — exactly the 2B
   campaign's finding — and a literal that nobody has grepped for is the default
   state, not the exception.
