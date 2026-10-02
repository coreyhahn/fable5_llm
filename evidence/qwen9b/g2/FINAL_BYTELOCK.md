# G2b — the final byte-lock pin

**VERDICT: PIN LANDED.** On 2026-08-31, at tree `c9d2a2f` (the commit G2a
closed on), the byte-lock ran green for the last time it will ever mean
anything, and the bytes it was protecting were recorded **with expected
values** so that a future run is a pass/fail comparison rather than a fresh
recording.

Gate: **G2b** · Plan: `docs/superpowers/plans/2026-08-29-qwen35-9b-migration.md:903-948`
(Task 4) · Spec: `docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md:2073-2095`
(§8 G2's sequencing box) · Host: **snoke** · No RTL, no synthesis, no board.

**Why this gate exists.** G2a proved every host generalization inert at 0.8B
and 2B — `BYTES_UNMOVED PASS`, `REGEN_GATE_PASS` at `a69864d2…`, on the
committed tree. G3 then spends that proof on purpose: the 16-bit ARG
re-encoding changes the emitted words at **every** geometry, so
`evidence/qwen2b/rc/t4_bytes_unmoved.sh` stops being runnable against the
tree, and this project deliberately keeps **no v1.7 emitter path**. Between
those two events there is exactly one moment when the frozen artifacts are
both *present* and *provable*. This is that moment, written down.

---

## 1. What ran, and what it said

All runs through `evidence/qwen9b/run.sh` (host, date, tree + dirty flag, cmd,
per-host `test -x` interpreter probe, `nproc --all`, thread pinning, rc), which
refuses to overwrite an existing log. `MODELPY=/home/cah/.venv/bin/python`
(**snoke: python 3.12.3, torch 2.12.0+cpu, safetensors 0.8.0**, probed with
`test -x` plus a live import — the plan's standing hazard about per-host
interpreters). `OMP_NUM_THREADS=8`, recorded in every header.

| # | run | log | result |
|---|---|---|---|
| 1 | `evidence/qwen2b/rc/t4_bytes_unmoved.sh` **SEED=1** | `t4_bytes_unmoved_g2b_s1.log` | **BYTES_UNMOVED PASS** |
| 2 | same, **SEED=2** | `t4_bytes_unmoved_g2b_s2.log` | **BYTES_UNMOVED PASS** |
| 3 | same, **SEED=3** | `t4_bytes_unmoved_g2b_s3.log` | **BYTES_UNMOVED PASS** |
| 4 | same, **SEED=4** | `t4_bytes_unmoved_g2b_s4.log` | **BYTES_UNMOVED PASS** |
| 5 | `ref/scripts/regen_gate.sh` | `regen_gate_g2b.log` | **REGEN_GATE_PASS**, `got = a69864d2…f444aaf1`, 60,495 records |
| 6 | `evidence/qwen2b/rc/t3_locks.sh` (lock A + lock B) | `t3_locks_g2b.log` | **REGEN_GATE_PASS** + **E4_LOCK_PASS**, `e4 got = e102e2df…d6e8ac933`, weight-plan JSON and model text both identical |
| 7 | `evidence/qwen2b/rd/rd_golden_shas.sh` | `rd_golden_shas_g2b.log` | **rc 0 — a RECORDING, see §5** |
| 8 | `evidence/qwen9b/g2/final_bytelock_pin.sh --selftest` | `final_bytelock_pin_selftest.log` | **PIN_SELFTEST PASS** (first revision, 1 negative control) |
| 9 | `evidence/qwen9b/g2/final_bytelock_pin.sh` | `final_bytelock_pin_g2b.log` | **FINAL_BYTELOCK_PIN PASS**, 54 rows ok, 0 bad (first revision) |
| 10 | `evidence/qwen9b/g2/final_bytelock_pin.sh --crosslock` | `final_bytelock_crosslock.log` | 19 of 54 rows independently corroborated — §4 |
| 11 | `evidence/qwen9b/g2/final_bytelock_pin.sh --selftest` | `final_bytelock_pin_selftest_final.log` | **PIN_SELFTEST PASS**, 2 negative controls CAUGHT (the committed script) |
| 12 | `evidence/qwen9b/g2/final_bytelock_pin.sh` | `final_bytelock_pin_final.log` | **FINAL_BYTELOCK_PIN PASS**, 54 rows ok, doc table in sync (the committed script) |
| 13 | `evidence/qwen9b/g2/final_bytelock_pin.sh` | `final_bytelock_pin_committed.log` | **FINAL_BYTELOCK_PIN PASS** on `f77b862`, no dirty flag |
| 14 | `evidence/qwen2b/rc/t4_bytes_unmoved.sh` **SEED=1** | `t4_bytes_unmoved_g2b_committed.log` | **BYTES_UNMOVED PASS** on `f77b862`, no dirty flag |
| 15 | `evidence/qwen9b/g2/spec_cites_selftest_regression.sh` | `spec_cites_selftest_regression_committed.log` | **SPEC_CITES_REGRESSION PASS** on `7bef84f` — §9a |
| 16 | `evidence/qwen9b/g2/final_bytelock_pin.sh` | `final_bytelock_pin_committed_r2.log` | **FINAL_BYTELOCK_PIN PASS** on `7bef84f`, doc table still in sync after the review edits |

**Runs 8 and 9 used an earlier revision of the pin and are kept because the
sequence is the evidence** — the same reason G2a kept its before/after logs.
That revision had the comparator and one negative control; the doc-sync check,
its negative control, and `--crosslock` were added afterwards, so **runs 11 and
12 are the ones taken with the script this gate commits** (§8 gives its
sha256). Nothing in the pinned table changed between them; runs 8/9 and 11/12
report the same 54 rows ok, 0 bad.

**Four seeds, and the seeds are not decoration.** `t4_bytes_unmoved.sh:21`
takes its gold from `tb/scripts/w5/lay2b_w8_s$SEED`, so each seed is a
different 2B one-layer artifact set — a different weight draw, a different
`.txt`, a different 15-image pack. Every G2a run of this gate used the default
`SEED=1` only. All four pass here, and §3's group C pins all four.

**Runs 5 and 6 are the last time a REGENERATION lock can be read.** After G3
neither reproduces these bytes, by design.

**What that certifies, scoped honestly (corrected at review).** For the 0.8B
`.e.seq` it really is *two independent mechanisms on the same day*: run 5
regenerates the stream from the checkpoint and compares it against a
**hard-coded constant** (`ref/scripts/regen_gate.sh:5`), which is the same
value §3 pins, so the emitter and the pin agree without either reading the
other. **Run 6's `.e4` half is NOT that**: `evidence/qwen2b/rc/t3_locks.sh:35`
computes its gold by hashing **the very file the pin hashes**, so a moved
`.e4.seq` moves both sides together and the lock stays green. Run 6 proves the
emitter still reproduces whatever is on disk; what corroborates the `.e4`
rows is §4's prior-record sweep, not this run. The general form of the point
is §2's: a lock whose gold lives on disk cannot detect the disk changing.

---

## 2. The pin, and why it is not `rd_golden_shas.sh`

The deliverable is `evidence/qwen9b/g2/final_bytelock_pin.sh`. It carries the
expected sha256 of every artifact in the frozen chains, **compares**, and exits
non-zero on any mismatch.

That distinction is the whole point of this gate, and it has a history in this
campaign. `evidence/qwen2b/rd/rd_golden_shas.sh` carries **no expected values
and makes no comparison**: it `ls`es and `sha256sum`s three `.chip` goldens and
counts their `MEM` lines, so it exits 0 on any tree and "passing" it is not
evidence of anything. `evidence/qwen_next/ladder/LADDER.md:618` already draws
the line correctly, reporting `t4_bytes_unmoved.sh` as **PASS** and
`rd_golden_shas.sh` as merely **rc 0**; the first version of `RD_GATE.md`'s
2026-08-29 note gave it gate semantics it does not have and was corrected the
same day (`evidence/qwen2b/rd/RD_GATE.md:636-643`). Its real value is
unchanged and is why it ran here as step 7: **it is how the golden bytes get
recorded**, and a recording is exactly what a pin needs as its input.

**Before this gate, the 0.8B/2B artifact chain had exactly ONE hard-coded
expected value in a runnable checker** — `ref/scripts/regen_gate.sh:5`'s
`GOLD_SEQ_SHA`. Measured, not assumed: a repo-wide sweep for assigned sha
constants returns that line plus four 9B goldens/corpora that belong to other
tracks (`evidence/qwen9b/g1/run_g1_{point,smoke}.sh`,
`evidence/qwen_next/ladder/run_ppl_point.sh`). Everything else compares against
**bytes on disk** — `t4_bytes_unmoved.sh` against its `$OLD` gold,
`evidence/qwen2b/rc/t3_locks.sh:35` reading `GOLD4` off the file it is checking,
`ref/scripts/regen_gate.sh:41` `cmp`ing the `.txt` against the committed copy —
or records values in a *document* that nothing executes
(`evidence/qwen2b/rc/RC_GATE.md:188-194`), or prints them next to a
non-comparing `EXPECT` heredoc (`evidence/qwen2b/rd/rd_2b_artifact_shas.sh`,
which exits 0 either way). **A lock whose gold lives on disk cannot detect the
disk changing.** That is the hole this pin closes, and §4 measures how wide it
was.

**The pin also checks this document.** §3's table is reprinted below because a
gate document has to be readable on its own — the whole point is that someone
finds it years from now. Two copies of a table is two things that can drift, so
they are tied mechanically rather than by care: the pin's default run compares
this document's copy against its own `expected()` and fails on any difference,
and `--selftest` proves that check fires by perturbing a temp copy of the
document. The copy lives between the `PIN TABLE BEGIN` and `PIN TABLE END`
HTML comments; edit it in one place and the gate goes red.

**Modes.** `--emit` prints a fresh measurement in the embedded format; it is
*not* a refresh button, because after G3 nothing regenerates these artifacts
and re-emitting over a mismatch destroys the only record there is.
`--selftest` is the negative control. `--crosslock` is §4.

---

## 3. The pin table — 54 rows, all `[D]`

Label **[D]** per the spec's §0 contract: computed by a committed script that
reproduces committed numbers first (19 of the 54 rows, §4). Every path below is
**.gitignored** — `.gitignore:23` covers `tb/scripts/w4/` and `.gitignore:27`
covers `tb/scripts/w5/` — so these hashes are the only in-repo record of the
bytes.

* **A** — the frozen 0.8B chain, what `build_034_po2_AltSpreadLogic_high`
  (`4f908df2`) was built from. 14 rows.
* **B** — the 2B W8 chain, what `build_035_fp2a_exc_po` (`54443b9f`, the
  resident bitstream now serving) was built from. 12 rows.
* **C** — the byte-lock's own gold, 4 seeds. 28 rows. It is here because the
  lock is only as good as its reference: if `tb/scripts/w5/lay2b_w8_s*.*` moved,
  `t4_bytes_unmoved.sh` would keep printing PASS against the moved bytes and
  nothing would notice.

The three `.chip` goldens `rd_golden_shas.sh` records are rows of A and B —
`model_v2_s1.e.chip`, `model_v2_s1.e4.chip`, `model_w8_2b_s1.e.chip` — and
agree with `evidence/qwen2b/rd/hw_47_golden_shas.log` to the digit. A
`(n=K)`-suffixed row is a digest over the per-file sha lines of a K-file image
set; see §6 for the one thing about that form that is not obvious.

<!-- PIN TABLE BEGIN -->
```text
# A — frozen 0.8B chain (build_034_po2_AltSpreadLogic_high)
a69864d25b6b129a4d6c74b3c78dfcbedf1edce219d32cc05d05bc54f444aaf1  tb/scripts/w4/model_v2_s1.e.seq
bc6869ba1179788c71f97922404f0a34e35b675e1d7ea2421473910a7055069d  tb/scripts/w4/model_v2_s1.e.seq.json
13bc65821b18194b7672c366894b2c2cd4ad6e2e966f12738b6d2faeeafcb6fb  tb/scripts/w4/model_v2_s1.e.seqdata.bin
7207d57bae31a7f99358f4d1b443d629ce42e610aaa046a9988ef5246189c1ec  tb/scripts/w4/model_v2_s1.e.chip
e102e2df0835097d0d622cd17109b9cbfea1ab4e78818bcddf3873ec6d8ac933  tb/scripts/w4/model_v2_s1.e4.seq
745456c8f2eb1ccb6942e7245a61a9b5a7f5a2948c756f3fec0a56cca1fd8aed  tb/scripts/w4/model_v2_s1.e4.seq.json
13bc65821b18194b7672c366894b2c2cd4ad6e2e966f12738b6d2faeeafcb6fb  tb/scripts/w4/model_v2_s1.e4.seqdata.bin
e5436b72e93c3ada85653060ca0ddf571a7b4f0a3a3d8504ab2db78bace2cdf3  tb/scripts/w4/model_v2_s1.e4.chip
57be703747c9f95dc28e8ab8c4dd98c9b495e727ac752c454cfb67ed964c0936  tb/scripts/w4/model_v2_s1.txt
973c94bdad73163775425bba017edd93e9fea4e268ef96ef222b5c53eca61453  tb/scripts/w4/model_v2_s1.emb.bin
087f0a0115c9951e8e14812f73de93e51c2526975548211f2a0543724fbd6aa9  tb/scripts/w4/model_v2_s1.weights.json
31fde284d61580d62b4aa0fc4b197b0d6f980b569e0fb7b421248efa53b764ee  tb/scripts/w4/model_v2_s1.wimg.bin
38234398cd217d8e5e64dae9f6b9fcfa2f1f6a63cc7a3f8cd27513ee570838d2(n=187)  tb/scripts/w4/model_v2_s1_w[N].bin
57be703747c9f95dc28e8ab8c4dd98c9b495e727ac752c454cfb67ed964c0936  tb/scripts/model_v2_s1.txt
# B — 2B W8 chain (build_035_fp2a_exc_po, the resident bitstream)
fa8d9349cf1d0aa618ab79e0a2565dd89adbb147b665cb49b582d83c95b05bcb  tb/scripts/w5/model_w8_2b_s1.e.seq
998ab2604d4ed44f396a78c292a3ddb40aaaf3244968e2f8b4b4ab58cb4cead8  tb/scripts/w5/model_w8_2b_s1.e.seq.json
e8d536ee95880ff399ff25ebad13b851486ea51cb32b6dd216125b6e87f8fc28  tb/scripts/w5/model_w8_2b_s1.e.seqdata.bin
15c39f54f75adcc3252d9fbfc35a91b3a8cda79fcb13a5a20fd0fa9711dd3fed  tb/scripts/w5/model_w8_2b_s1.e.chip
be2180584ce3ca8a03d8edb4c36bc31b9daa5333eb6cfb5cba90084b331c1255  tb/scripts/w5/model_w8_2b_s1.txt
b54db7a9fa6ba97fda253b00c7ed9a4a0afe7ba43b93b9b85c2aa3876963d3aa  tb/scripts/w5/model_w8_2b_s1.emb.bin
f4eb9b25cb07f357127272edbdf7b4f2b1471eb4ebd137729cb0bee117c672c3  tb/scripts/w5/model_w8_2b_s1.weights.json
d765e255ee0b9afde760a6c4d73b58793d4f0552f9d076a5b5a5632453b29c0b  tb/scripts/w5/model_w8_2b_s1.wimg0.bin
3ad2ff0aca12d352df094b5d3296b57733205280d88fb634b00d52d117c38779  tb/scripts/w5/model_w8_2b_s1.wimg1.bin
ce7d1b84e7a46545d468b26ec05f2b0b24b4c4a01c8895e1983b4697987bdd39  tb/scripts/w5/model_w8_2b_s1.wimg2.bin
f5bb0c7e69304bf9bc960260613265875cc5d1b7d6e0c7fc53653555410cd62a  tb/scripts/w5/model_w8_2b_s1.wimg3.bin
823396ccd46144e17f0f5401ad3143c984c0478277297f4b6da171c93d2cacaa(n=187)  tb/scripts/w5/model_w8_2b_s1_w[N].bin
# C — the byte-lock's own gold, 4 seeds (t4_bytes_unmoved.sh:21)
d416c57b7b37b2d6615d22481dde5213ad5fbe12d537bdeb5fe915196d07a556  tb/scripts/w5/lay2b_w8_s1.txt
0cad08f32ff22f0a1e0c5f0bf14aae8d8f9539ab9967d2d404180f939f7ddee1  tb/scripts/w5/lay2b_w8_s1.e.seq
6270ec0f948ca144fd905d425eb50e4470c959d9adb5945392d2f58a4f626998  tb/scripts/w5/lay2b_w8_s1.e.seq.json
91affc691347eb66dd2c5e8770ea30226bae5d38c71c98657b5a8a010fa04229  tb/scripts/w5/lay2b_w8_s1.e.seqdata.bin
2cbc8ee699663dbfc7fca0ec9be4fab9e6c88e1f669d13e76702dce6b084d4c9  tb/scripts/w5/lay2b_w8_s1.e.chip
a883081b3928bb99ca8a4504a79e36fae16f0746a98eab5638f74b72e362e1b0  tb/scripts/w5/lay2b_w8_s1.weights.json
b96ea68e92ba0e23a6213b217c2dfb73d892c2da6a20c3d755ba5be31651e995(n=15)  tb/scripts/w5/lay2b_w8_s1_w[N].bin
9097b19089f9c3ae1ba76a2ef61ce630c314f383393bb43f8da28c74162f3216  tb/scripts/w5/lay2b_w8_s2.txt
0cad08f32ff22f0a1e0c5f0bf14aae8d8f9539ab9967d2d404180f939f7ddee1  tb/scripts/w5/lay2b_w8_s2.e.seq
9e49ec617f738c5b6021ba6ac1a2febf45aeee3f76ac9449ff58c8af87724276  tb/scripts/w5/lay2b_w8_s2.e.seq.json
3135a943906f5c44894bb91aba08b0764720826077d676adc8ad4def735871da  tb/scripts/w5/lay2b_w8_s2.e.seqdata.bin
25d183e8a4aef7096e05292e3fc5fdda4bd04b043a8d7fe08eb63282d1e371f0  tb/scripts/w5/lay2b_w8_s2.e.chip
c5f449b2119ec4404f7fc69488a963c4e9ac8ef269a75f1fa08f9987f1207238  tb/scripts/w5/lay2b_w8_s2.weights.json
8fd36fbe33ab83ea7b84aaec4cd4c24d4cfbf20b7cc380fe997ff9cb57f31b58(n=15)  tb/scripts/w5/lay2b_w8_s2_w[N].bin
8a89ea704c86080eba67572d34bd5c3cd1ce0f64e2c066709d3c0c01b0e7a542  tb/scripts/w5/lay2b_w8_s3.txt
0cad08f32ff22f0a1e0c5f0bf14aae8d8f9539ab9967d2d404180f939f7ddee1  tb/scripts/w5/lay2b_w8_s3.e.seq
ae6210d4bcf2c4bbfba992948cd943126d52bcbc856e07fcfe71b858a33d0ff1  tb/scripts/w5/lay2b_w8_s3.e.seq.json
87a288e51946a6bc9d88d2e5f5071fdee7567b318085b1c00e868dc3ecc6d01c  tb/scripts/w5/lay2b_w8_s3.e.seqdata.bin
fa1399419b3d2ffbeb8f99da8de63e81e4d59e63a4a6680648167620eed97d46  tb/scripts/w5/lay2b_w8_s3.e.chip
91a251707a4e679f0c30e66db0d6594b0158aea242e546ca4d1db718767e2c0d  tb/scripts/w5/lay2b_w8_s3.weights.json
76dbf6355ac800a759023f5a4b1e222112bd83e19d3243cf29c67eafee472d3a(n=15)  tb/scripts/w5/lay2b_w8_s3_w[N].bin
f4c165573cd13dbeb118d919b10e97a99141066a9bc0623b6a947d7d327375dd  tb/scripts/w5/lay2b_w8_s4.txt
0cad08f32ff22f0a1e0c5f0bf14aae8d8f9539ab9967d2d404180f939f7ddee1  tb/scripts/w5/lay2b_w8_s4.e.seq
c1e290a05a49ea8dc03310c56e92104bded31fb3dbfc523b5c7222494ea088f9  tb/scripts/w5/lay2b_w8_s4.e.seq.json
9a23dd34fad910959be32841276d149ab98d3082d18b99d74490e294110e91b0  tb/scripts/w5/lay2b_w8_s4.e.seqdata.bin
bdc0bd827014070e81bb48589169966b28114db06e08a17b7b762e650820b6cd  tb/scripts/w5/lay2b_w8_s4.e.chip
c5d928234683533114ac7330bce81d1d0a5f0c093c47db072b510545a565213d  tb/scripts/w5/lay2b_w8_s4.weights.json
1c1cd810e49515ddd344faf1cc8627f19f7e33fdc36a426b76892844d3671d13(n=15)  tb/scripts/w5/lay2b_w8_s4_w[N].bin
```
<!-- PIN TABLE END -->

**Two rows that look like typos and are not.** `model_v2_s1.e.seqdata.bin` and
`model_v2_s1.e4.seqdata.bin` carry the same sha because the 1-chan and 4-chan
streams share one const blob — `evidence/rung4/agentC_artifacts.sha256:9-11`
says so in its own comment ("both streams share ONE weight pack / const blob").
And all four `lay2b_w8_s*.e.seq` rows are the same sha `0cad08f3…`: the record
stream does not depend on the weight seed, only the weights and the `.txt` do.
Neither is a copy-paste error; both were checked against the sizes and the
independent records.

---

## 4. How much of the pin is independently corroborated — 19 of 54, measured

`final_bytelock_pin.sh --crosslock` sweeps every expected sha (first 16 hex,
because some records keep only a prefix) against the committed tree with
`evidence/qwen9b/` excluded, so a hit is a record this campaign did not write.

| group | rows | corroborated | notable sources |
|---|---|---|---|
| A — 0.8B | 14 | **13** | `ref/scripts/regen_gate.sh:5`, `evidence/rung4/agentC_artifacts.sha256:3-11`, `evidence/rung1/seqrun_artifacts.sha256:2`, `evidence/qwen2b/rd/hw_47_golden_shas.log`, `evidence/qwen2b/rc/t3_locks_after.log`, `evidence/stage5/phase1a_model_v2_artifacts.sha256:4-190` |
| B — 2B | 12 | **7** | `evidence/qwen2b/rc/RC_GATE.md:188-194`, `evidence/qwen2b/rd/hw_47_golden_shas.log` |
| C — lock gold | 28 | **0** | — |
| **total** | **54** | **20** | |

> **A CORRECTION, and it is a correction to this gate's own sweep.** The table
> first read **12 / 7 / 0 = 19**, the number `--crosslock` prints, and review
> found it too low by one. `--crosslock` asks *"has this exact DIGEST been
> recorded before?"* — and for an image-set row that question is too narrow.
> The 0.8B 187-image set has no prior record of the pin's canonical digest,
> but it has a per-file record of **every member**:
> `evidence/stage5/phase1a_model_v2_artifacts.sha256:4-190` lists
> `model_v2_s1_w0.bin` … `w186.bin` individually, and all 187 are **byte-identical
> to the images on disk today** — measured, not inferred, by
> `evidence/qwen9b/g2/crosslock_setcheck.sh` (`187/187`). So group A is
> **13 / 14** and the total is **20 / 54**. The uncorroborated count is 34.
> The same script finds **no** per-file record for the 2B 187-image set, for
> any of the four lock-gold sets, or for any of the five `wimg*.bin`, so those
> rows stand exactly as `--crosslock` reported them.

**The 34 uncorroborated rows are the finding of this gate, and group C is the
sharp end of it.** `evidence/qwen2b/rc/t4_bytes_unmoved.sh` has been this
campaign's central inertness proof since R-c — Track L used it, G2a used it,
`LADDER.md:615` reports it — and **not one byte of its reference gold had a
sha256 recorded anywhere in the repo until now.** It compares against `$OLD` on
disk (`t4_bytes_unmoved.sh:21`), so a corrupted or regenerated gold would have
made every future PASS meaningless without a single symptom. The other six uncorroborated
rows are packed weight images and one image-set digest: `model_v2_s1.wimg.bin`,
the four 2B `wimg[0-3].bin`, and the 2B 187-image digest — **none of which has
a prior record in any form**, per-file or digested
(`evidence/qwen9b/g2/crosslock_setcheck.sh`). An earlier draft said the weight
images "were never hashed individually" and applied that to the 0.8B set as
well; that is wrong, and the correction above is why.

This does not weaken the 20; it measures what the pin adds. The corroborated
rows say the measurement is right. The uncorroborated ones say the pin was
necessary.

---

## 5. `rd_golden_shas.sh` — run, and read correctly

Step 7 ran it and it printed the three `.chip` shas and their `MEM`/`NREC`
counts: `model_w8_2b_s1.e.chip` MEM 16,384 NREC 68,503 PC 68,502 EMBLOG2 12;
`model_v2_s1.e4.chip` MEM 7,168 NREC 68,119 PC 68,118; `model_v2_s1.e.chip`
MEM 7,168 **NREC 60,495** PC 60,494 — the same 60,495 records
`regen_gate_g2b.log` emitted, from the other direction.

**Its rc 0 is not a result.** The script carries no expected values and makes
no comparison (`evidence/qwen2b/rd/rd_golden_shas.sh:16-18` is a bare
`sha256sum`), so it exits 0 on any tree. It is in this gate as a **recording**,
and its output is one of the sources §4 counts. The three values it printed
match §3's rows and `evidence/qwen2b/rd/hw_47_golden_shas.log` from 2026-08-25.

`evidence/qwen2b/rd/rd_golden_shas.sh:30-34`'s standing note — that the 2B
golden's mtime postdates the artifact set because R-c regenerated it when wall
8 was fixed — is still true and still the explanation for the one mtime in
these sets that looks out of order. **Two more mtimes in group A are out of
order and are recorded here rather than explained away**:
the 0.8B weights manifest is 2026-08-13, five days after the rest of the
`.e` set (2026-08-09), and the `.e4.*` files are 2026-08-11. Both are
consistent with the history — R-b rewrote the manifest format
(`evidence/qwen2b/rb/sw_selftests_new_manifest.log:5` records exactly the
`087f0a01…` this pin now expects) and the `.e4` stream was added later
(`evidence/rung4/agentC_artifacts.sha256:5-8`) — and the pin records the bytes
as they stand rather than asserting the set was written in one pass.

---

## 6. A defect found on the way: the 187-image list digest is locale-dependent

`b9e0851:evidence/qwen2b/rd/rd_2b_artifact_shas.sh:19` digests the image set as
`sha256sum ${P}_w*.bin | sha256sum`, i.e. **in shell glob order**, and shell
glob order is `LC_COLLATE`-dependent. Measured on snoke, 2026-08-31, same 187
files and same bytes:

| collation | order | digest |
|---|---|---|
| `LANG=en_US.UTF-8` (the login default) | `w0, w100, w101, …` | `c9e6d0a61bfda354…` |
| `LC_ALL=C` | `w0, w1, w10, w100, …` | `e6a1c0b5ff873fad…` |

`evidence/qwen2b/rc/RC_GATE.md:194` records the **en_US.UTF-8** value, and
neither that line nor the script says so. Anyone re-running it from a
C-locale shell — a cron job, a container, a different distro default — reads a
mismatch that is not one, on the artifact set that feeds the resident
bitstream.

**Disposition.** Nothing is edited in RC_GATE §2: its number is correct under
the collation it was taken with, and this gate does not rewrite the R-c
record. What changed is the pin: `final_bytelock_pin.sh`'s `list_sha` sorts the
per-file sha lines under `LC_ALL=C` before digesting, so its value is
independent of glob order and of the caller's locale both. That is why §3's
group-A/B image rows (`38234398…`, `823396cc…`) match neither number in the
table above — they are a third, canonical form, and the script says so at its
definition. **A pin may not have an ambient dependency.**

Carried to G3/G6 as a work item, not fixed here:
`evidence/qwen2b/rd/rd_2b_artifact_shas.sh` and
`RC_GATE.md:194` would both be clearer with the collation stated. It is a
documentation fix on a retired gate's record, so it is recorded rather than
done.

**CLOSED 2026-09-10 (#19, triage (b)13, pre-ship tool chore `aa9b1fe`) — the
work item above WAS taken, so this section's "not fixed here" is history.**
`evidence/qwen2b/rd/rd_2b_artifact_shas.sh` now digests the 187-image list
under `LC_ALL=C` with an explicit `sort`, so its value is a property of the
files and not of the caller's locale, and `RC_GATE.md` §2 gained the C-order
digest `e6a1c0b5…` **below** the original `en_US.UTF-8` one — the collation is
stated at both lines now, and the old record still reconciles. Measured on
snoke: `evidence/qwen9b/o3/84_artifact_shas_locale_RED.log`
(`LOCALE_DIGEST: SPLIT`, the two values) and
`evidence/qwen9b/o3/85_artifact_shas_locale_GREEN.log`
(`LOCALE_DIGEST: STABLE`, one digest under both locales). The `RC_GATE.md:194`
citation above is left as written: it names the row it was written about, and
the C-order value is the line below it.

---

## 7. The supersession notes

Per the plan's Step 2 and
`docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md:2077-2085`,
dated notes were appended to
both old gate documents — **appended, not edited**: the 2026-08-29 notes and
their corrections-of-corrections are left intact, and the new text sits after
them under its own dated heading.

* `evidence/qwen2b/rc/RC_GATE.md` — "DATED NOTE (2026-08-31) — the byte-lock is
  PINNED; the next thing that happens to it is retirement". Closes the
  2026-08-29 note's forward reference: that note said G2b "records the artifact
  sha256 set once more"; this one says it has, names the file, and states that
  the pin's expected values are what make it re-checkable.
* `evidence/qwen2b/rd/RD_GATE.md` — "DATED NOTE (2026-08-31) — the goldens are
  PINNED, and the recording/gate distinction now has a gate beside it".

Both say the same operative thing, in the words the plan asked for: after G3,
`evidence/qwen2b/rc/t4_bytes_unmoved.sh` stops being runnable against the tree
because the ARG re-encoding changes the emitted words at every geometry; **this
project does not keep a v1.7 emitter path**, so rebuilding 0.8B/2B artifacts
from the post-migration tree is **unsupported**; the artifacts already exist,
are pinned in `evidence/qwen9b/g2/FINAL_BYTELOCK.md`, and the bitstreams that
consume them are frozen. **Anyone who finds the byte-lock failing after G3
should read the note, not debug the script.**

---

## 8. Provenance, and one thing the wrapper cannot see

Every log header reads `=== tree: c9d2a2f` with **no `+dirty` flag**, and that
is worth one sentence of honesty rather than a clean-tree claim.
`evidence/qwen9b/run.sh:43` derives the flag from `git diff --quiet`, which
reports **tracked-file modifications only** — an **untracked new file does not
set it**. The pin script and this document were untracked for every run in §1,
so `c9d2a2f, not dirty` describes the tracked tree exactly and **says nothing
about the two files that produced those runs**. Same class as G1's finding that
the tree label is not the provenance handle; the handle is the source digest,
and the script this gate commits is

```
0eb099c9e7f38e2fa8b0590a49333e0b5b4bc4b9111e005324221bc849b0c736  evidence/qwen9b/g2/final_bytelock_pin.sh
```

**Runs 11 and 12 are the ones taken with that exact file**, and their logs
carry the same `c9d2a2f` label for the same reason. Runs 8 and 9 predate three
additions to it (§1). Nothing else in this gate was uncommitted.

**Runs 13 and 14 close the gap.** After the gate commit `f77b862` — the pin,
this document, the two supersession notes, the checker edit and all eleven
earlier logs — the pin and the byte-lock were run once more and their headers
read `=== tree: f77b862` with **no dirty flag and nothing untracked left**, so
for those two the label covers the whole tree including the script that
produced them. `FINAL_BYTELOCK_PIN PASS`, 54 rows ok, doc table in sync;
`BYTES_UNMOVED PASS`. They are in the follow-up commit, which is the only thing
in this gate that `f77b862` does not contain.

**Machines and rules.** Every numeric run on snoke (`nproc --all` 48,
`OMP_NUM_THREADS=8`). No `rtl/`, no `synth/`, no board — the board stays
serving the 2B on `build_035_fp2a_exc_po` until G6, untouched. Sweeps with
`/usr/bin/grep`. The commit is path-limited to named files;
`evidence/qwen9b/g2/` is a shared tree and was never named as a directory, and
neither was `evidence/qwen2b/` — see §10.

---

## 9. Checker state

`evidence/qwen_next/spec_cites.py` on this document: **`SPEC CITES: PASS`**
(**129 exist, 29 range, 0 quote** at the last edit — the counts are a property
of this document and move whenever it is edited, so a later run reporting
different totals is not drift; the `FAIL 0` is the claim). The plan and the
spec were not edited by this gate and were re-checked unchanged: **`SPEC CITES:
PASS` on both**, and `--selftest` **PASS** on both.

### 9a. `--selftest` was broken for this whole class of document — now fixed

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

**The first version of this section got the diagnosis wrong and it is corrected
here rather than quietly.** It said `--selftest` could not run against this
document because the perturbation constructor needs an `` `rtl/<name>.sv:N` ``
citation and *"this is a host-only gate — no RTL, by design"*. **Host-only is
not the trigger.** There were **two** asserts, and the second one is the one
that matters:

| # | assert | what it demanded | what actually triggers it |
|---|---|---|---|
| (a) | case (1)/(2) target | an `` `rtl/*.sv:N` `` citation | a document citing no RTL |
| (b) | case (3)/(4) target | a line carrying a cite **and a quotation of it** | a document with **zero QUOTE checks** |

`evidence/qwen9b/g2/G2A_HOST.md` cites `rtl/conv4_silu.sv:50`,
`rtl/matvec_chan.sv:18` and `rtl/seq_unit.sv:330` — it sails past (a) and  <!--cites:noquote-->
**still crashed at (b)**. And (b)'s trigger is the *normal* state of a document
written as lists and tables, because a `QUOTE` check only fires when the
quotation shares a markdown line with its citation. So the broken set was
"every zero-quote document", which is **exactly the set that most needs a
working negative control** — the blind-spot documents. Both gate docs this
campaign has written were in it.

**A third defect sat underneath both**, invisible until (a) and (b) were fixed:
`--selftest` copies the document to a temp dir, so `resolve()`'s
document's-own-directory fallback pointed at the temp dir and every
bare-filename cite stopped resolving. Measured on this document: **18 invented
`EXIST` failures**, i.e. the **positive** control failed too.

**Fixed at G2b's review round**, in `evidence/qwen_next/spec_cites.py`:
(a) the perturbation target is now any citation that resolves to an existing
file with an in-range line; (b) when no cite+quotation line exists, one is
**synthesized** from a real line of a really-cited file — and verified clean
*and verified to raise the QUOTE-check count* before it is perturbed, so a
mis-built synthesis fails loudly instead of making cases (3) and (4) vacuously
"CAUGHT"; (c) `resolve()` takes an explicit `docdir` and `--selftest` passes
the **original** document's directory.

> **The wrong fix for (c) was much worse than the bug, and it is on record as a
> measurement.** Making bare names "resolve" by adding an always-existing
> candidate (`os.devnull`) to `resolve()` does not relocate the lookup, it
> **disables** it: `evidence/qwen2b/rc/RC_GATE.md` drops from **FAIL 27 to
> FAIL 4**, suppressing 23 real failures. `evidence/qwen9b/g2/spec_cites_selftest_regression.sh`
> builds that variant and measures the degradation on every run, so the reason
> for the design cannot quietly rot into a comment.

**Regression, all in `evidence/qwen9b/g2/spec_cites_selftest_regression.log`:**
eight documents re-checked in normal mode against expected `FAIL` counts —
`RC_GATE.md` **27**, `RD_GATE.md` **8**, this document **0**, `G2A_HOST.md`
**0**, `D_TOL.md` **3**, `evidence/qwen9b/g1/RUNG_INT8_STATE.md` **2**, the spec **0**, the plan
**0** — every one **unchanged** from `c9d2a2f`, i.e. the repair moves nothing
in normal mode. (`D_TOL.md`'s 3 and `evidence/qwen9b/g1/RUNG_INT8_STATE.md`'s 2 are pre-existing
at `c9d2a2f`, are T2's and T1's documents, and are recorded here as untouched
rather than adopted.) Then `--selftest` **6/6 CAUGHT plus the positive control
on four documents**, two of which — this one and `G2A_HOST.md` — **could not be
selftested at all before**.

**This was retroactive, not just forward-looking.** Every `SPEC CITES: PASS`
this campaign has reported on a gate document was reported *without* a working
negative control behind it, because the control crashed. The PASSes stand — the
checker's normal mode was never broken, and the eight-document table above is
the evidence for that — but the assurance behind them was thinner than the
gate docs implied, and that is now fixed rather than restated.

**And `0 quote` means the whole document sits in the checker's blind spot.** A
`QUOTE` check fires only when the quotation shares a markdown line with its
citation; every citation here is either bare or on its own line, so **`EXIST`
and `RANGE` are all that ran**. That is exactly the class G2a shipped nine
wrong landmarks in, twice. So the cited lines were rendered beside their
sources and **read individually** — all 23 distinct `path:NNN` citations,
including every multi-line range — rather than trusted to a PASS.

**The PENDING set lost FOUR entries, not three — declared here because the
first version of this section declared only three.** `spec_cites.py`'s
`PENDING` listed `evidence/qwen9b/g2/FINAL_BYTELOCK.md` as a path a future gate
creates (cited from `evidence/qwen2b/rc/RC_GATE.md:1031`); this gate creates
it, so it is removed and the citation is `EXIST`-checked from now on. Removed
in the same edit:

| path | why it was stale | declared? |
|---|---|---|
| `evidence/qwen9b/g2/FINAL_BYTELOCK.md` | this gate creates it | yes, from the start |
| `evidence/qwen9b/g2/G2A_HOST.md` | live since `b2f1223` (T3) | yes, from the start |
| `evidence/qwen9b/g2/damage_defect_b.py` | live since `b2f1223` (T3) | yes, from the start |
| `evidence/qwen9b/g1/RUNG_INT8_STATE.md` | live since G1 (`cb12a59`) | **no — undeclared until this correction** |

**And the belief that made it undeclared was written down and was false.**
`evidence/qwen9b/g2/G2A_HOST.md:591` states that `evidence/qwen9b/g1/RUNG_INT8_STATE.md` *"was
already out of `PENDING`* (T1's review round did it)". It was not:
`git show c9d2a2f:evidence/qwen_next/spec_cites.py` still lists it. T1's review
round refreshed five markers and this was not among them. A dated correction is
appended to `evidence/qwen9b/g2/G2A_HOST.md`; the removal changes no count,
because all four paths exist, which is precisely why it could go unnoticed —
`PENDING` costs nothing visible until the day a path is deleted.

**RC_GATE.md / RD_GATE.md: the pre-existing failure count is 35, not 34.**
Measured today before any edit:
`./evidence/qwen_next/spec_cites.py evidence/qwen2b/rc/RC_GATE.md evidence/qwen2b/rd/RD_GATE.md`
reports `FAIL 35` — **30 EXIST + 4 QUOTE + 1 ORPHAN**. The spec's §8 G2 scope
note and the plan's Step 6(a) both carry **34**, which was correct when written;
the composition changed because G2a's B2 fix made the `ORPHAN` check actually
execute. **The sweep's number governs and the discrepancy is recorded**, per
the plan's own instruction for exactly this class. These are pre-existing
short-form citations this migration did not write, cleaning them is optional
follow-on work by the spec's own scope note, and **this gate's two appended
notes add none of them** — the count is unchanged at 35 after the edits, with
every path in the new text written out in full.

---

## 10. Deviation from the plan's commit block, stated

The plan's Task 4 Step 3 commit block ends `-- evidence/qwen9b/g2/FINAL_BYTELOCK.md
evidence/qwen2b/`. **The directory pathspec is not used.** The plan's own
Global Constraints allow a directory only where exactly one task in the plan
ever writes it, list the permitted cases (each task's `evidence/qwen9b/<gate>/`
and `synth/` for Tasks 13–14), and call anything else "exactly the 2026-08-25
near-miss ... forbidden". `evidence/qwen2b/` is not on that list. The named
files are committed instead. The constraint is binding on every task and the
block is a local slip, so the constraint wins; recorded rather than silently
diverged from.

`git diff --stat` on every file this gate touches was empty before the edits —
no other task is live, and the shared-file rule was checked rather than
assumed.

---

## 11. NOT ESTABLISHED

1. **The pin proves the bytes on THIS filesystem.** `tb/scripts/w{4,5}/` are
   gitignored and live on NFS only. A pin is not a backup: if the files are
   deleted, this document records what they were and **nothing can reproduce
   them after G3**. Whether they should be archived somewhere durable is a
   question this gate raises and does not answer.
2. **Group C's four seeds are the lock's gold, not four independent locks.**
   `t4_bytes_unmoved.sh` regenerates one seed per invocation; four passes are
   four artifact sets, not four samples of a random process. There is no
   run-to-run variance to report because there is none — the emitters are
   deterministic, which G1 measured directly (spread exactly zero).
3. **No 9B artifact is pinned and none exists.** Task 5 builds the 9B chain;
   Task 11 emits its streams. This gate is about what is being left behind.
4. **The `.chip` goldens' MEM/NREC counts are recorded, not re-verified.** No
   simulation ran in this gate; the counts come from
   `rd_golden_shas.sh`'s own `grep -c`, and the sim gates that consume those
   goldens are G4a's.
5. **`build_034` / `build_035` bitstream files are not pinned here.** The gate
   pins what they were built *from*. Their own shas are in the R-b/R-c/R-d
   records.
6. **The locale defect in `evidence/qwen2b/rd/rd_2b_artifact_shas.sh` was
   diagnosed, not fixed, IN THIS GATE**
   (§6), and `RC_GATE.md:194` recorded a value whose collation was unstated.
   **CLOSED 2026-09-10 (#19, pre-ship tool chore `aa9b1fe`):** the script
   pins `LC_ALL=C` and an explicit sort, and `evidence/qwen2b/rc/RC_GATE.md:195`
   carries the C-order digest directly below it, with its collation named in
   the row itself. RED/GREEN
   on snoke: `evidence/qwen9b/o3/84_artifact_shas_locale_RED.log` (SPLIT) and
   `evidence/qwen9b/o3/85_artifact_shas_locale_GREEN.log` (STABLE). This
   limit no longer stands.
7. **THE PIN IS NOT SET-COMPLETE, and that is a real limit on what a PASS
   means.** It hashes a **fixed list of paths and extensions** written out in
   `measure()`. A future `.e5` stream, a new sidecar, a second embedding table
   — anything added beside the pinned files — is invisible to it: every named
   row still matches and the pin still says PASS. The row-count check compares
   expected against measured, but **both sides come from the same list**, so it
   catches a one-sided edit to the pin, not a new file on disk. The only
   genuinely set-complete rows are the six `_w*.bin` image sets, whose `(n=K)`
   suffix means an added or removed image changes the value and fails the row.
   So: **PASS means "every pinned artifact is unchanged", never "the directory
   is unchanged".** Making it directory-complete would need a manifest of
   `tb/scripts/w4/` and `tb/scripts/w5/` plus a policy for the scratch files
   that legitimately appear there; not done, and named here so nobody reads
   more into a green run than it carries.

---

## 12. Evidence

| what | file |
|---|---|
| the pin | `evidence/qwen9b/g2/final_bytelock_pin.sh` |
| the pin run | `evidence/qwen9b/g2/final_bytelock_pin_g2b.log`, `evidence/qwen9b/g2/final_bytelock_pin_final.log`, `evidence/qwen9b/g2/final_bytelock_pin_committed.log`, `evidence/qwen9b/g2/final_bytelock_pin_committed_r2.log` |
| the pin's negative controls | `evidence/qwen9b/g2/final_bytelock_pin_selftest.log`, `evidence/qwen9b/g2/final_bytelock_pin_selftest_final.log` |
| the byte-lock, 4 seeds | `evidence/qwen9b/g2/t4_bytes_unmoved_g2b_s1.log` and its three siblings, plus `evidence/qwen9b/g2/t4_bytes_unmoved_g2b_committed.log` |
| the 0.8B regen lock | `evidence/qwen9b/g2/regen_gate_g2b.log` |
| the 0.8B `.e4` lock + weight plan | `evidence/qwen9b/g2/t3_locks_g2b.log` |
| the golden recording | `evidence/qwen9b/g2/rd_golden_shas_g2b.log` |
| the corroboration sweep | `evidence/qwen9b/g2/final_bytelock_crosslock.log` |
| its set-level second half (§4's correction) | `evidence/qwen9b/g2/crosslock_setcheck.sh`, `evidence/qwen9b/g2/crosslock_setcheck.log` |
| the `--selftest` repair and its regression | `evidence/qwen9b/g2/spec_cites_selftest_regression.sh`, `evidence/qwen9b/g2/spec_cites_selftest_regression.log`, `evidence/qwen9b/g2/spec_cites_selftest_regression_committed.log` |
| supersession notes | `evidence/qwen2b/rc/RC_GATE.md`, `evidence/qwen2b/rd/RD_GATE.md` (2026-08-31 sections) |

**G2b: COMPLETE**, in three commits — `f77b862` (the pin, this document, the
two supersession notes, the `PENDING` refresh, eleven logs), the follow-up
carrying the two clean-tree re-runs, and a review mini-round that repaired
`--selftest` (§9a), corrected §4's count and §9's PENDING declaration, and
added the two checks above. The
lock is green, the bytes are pinned with expected values, and the two old gate
docs now say what happens to it next. **Nothing in
G3 is blocked on this gate any longer — and nothing in G3 should land before
this commit exists.**
