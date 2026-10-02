# SR2 — ISA v2.3: B17.0 SEQ_CAPS, B17.1 the FENCE channel mask, the hwmap constants, the validator's `caps=`

Task SR2 of the sequencer RTL round (`docs/superpowers/plans/2026-09-27-seq-rtl-round.md`,
Task SR2). Contract and host/reference code only: **no RTL, no build, no board.**
Every run below is on snoke through `evidence/qwen9b/sr/sr_run.sh`, log block n200–n299.

## 1. The contract — `docs/SEQ_ISA.md` v2.3

| what | where |
|---|---|
| header line 1 bumped to v2.3; the old v2.1 line kept as line 2 | `docs/SEQ_ISA.md:1-2` |
| B17 heading; its first paragraph says the header was not bumped at v2.2 (§B16) | `docs/SEQ_ISA.md:1408-1411` |
| B17.0 SEQ_CAPS — the word, one row per bit | `docs/SEQ_ISA.md:1420-1427` |
| B17.0 read-only, HOST-ONLY, the magic is the plan's choice | `docs/SEQ_ISA.md:1429-1432` |
| B17.0 DECODE — empty unless the magic; unknown bit refused by name; 0xDEADC0DE = empty set | `docs/SEQ_ISA.md:1434-1440` |
| B17.0 ONE DEFINITION | `docs/SEQ_ISA.md:1442-1447` |
| B17.0 ADMISSION — device-keyed caps, only on a named VERSION; manifest caps informational, subset of the device's | `docs/SEQ_ISA.md:1449-1455` |
| B17.1 FENCE target[3:0] = mask, 0 = all; other fields zero (err 0x06); F_SCAN waits for wr_idle in every case; still mv_op 3 (B16's C5) | `docs/SEQ_ISA.md:1457-1468` |
| B17.1 CHANNEL BINDING — bit c = chan_pend[c] = the engine channel c of MVGO/MOVX/MOVY (fix round 1, I1) | `docs/SEQ_ISA.md:1469-1478` |
| B17.1 NO RTL INTERLOCK — a pending channel outside the mask stays pending; the model gate and the pass's hazard assert refuse such a stream (fix round 1, I1) | `docs/SEQ_ISA.md:1479-1487` |
| B17.1 HALT unchanged | `docs/SEQ_ISA.md:1488` |
| B17.1 validator rule (R1 in caps or not) | `docs/SEQ_ISA.md:1490-1492` |
| B17.1 forward compatibility — fail-closed at the first masked FENCE (err 0x06) | `docs/SEQ_ISA.md:1494-1496` |
| B17.2 reserved ("Written by Task SR11a"), B17.3 reserved ("Not taken", SR16) | `docs/SEQ_ISA.md:1498-1505` |

**The SEQ_CAPS layout** (SEQ 0x64, read-only, writes ignored):
`{magic[31:8] = 24'hFAB1CA, 5'b0, r3[2], r2[1], r1[0]}`. **The magic 0xFAB1CA is
the round plan's choice** — the spec fixes only a fixed magic in the high bits and
one bit per built feature (`docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md`
§1.4). It binds from this task's commits. Every pre-round bitstream reads
0xDEADC0DE there (the read mux default, `rtl/seq_unit.sv:1641`), whose high 24
bits are not the magic, so it decodes as the empty set.

## 2. The one definition — `sw/hwmap.py`

| name | where |
|---|---|
| `S_SEQ_CAPS` (SB + 0x64), beside `S_EMBLOG2` | `sw/hwmap.py:340` |
| `SEQ_CAPS_MAGIC` = 0xFAB1CA | `sw/hwmap.py:357` |
| `SEQ_CAP_BITS` = R1 bit 0, R2 bit 1, R3 bit 2 | `sw/hwmap.py:358-360` |
| `seq_caps_set(word)` → frozenset; empty unless the magic; unknown bit → ValueError naming the bit | `sw/hwmap.py:363` |
| `seq_caps_check(caps)` → frozenset; unknown name → ValueError naming it; a bare str refused explicitly (fix round 1, M5) (added: the one place the name check lives, used by `seq_format` and `seq_caps_word`) | `sw/hwmap.py:386` |
| `seq_caps_word(caps)` → the word (for mocks and the TB side file) | `sw/hwmap.py:404` |

`ref/seq_format.py` uses them only through its existing `import hwmap as HW`
(`ref/seq_format.py:133`) and defines no SEQ_CAPS name of its own — the test's
case (i) checks both its namespace and its source. hwmap never imports
seq_format.

## 3. The validator — `ref/seq_format.py`

* `validate(r, nrec=None, idx=None, shape_isa=None, caps=frozenset())` (`ref/seq_format.py:547`)
  and `validate_stream(recs, allow_ext=True, shape_isa=None, caps=frozenset())` (`ref/seq_format.py:720`);
  both normalise `caps` through `HW.seq_caps_check` (`ref/seq_format.py:568`, `ref/seq_format.py:732`),
  so a name outside `SEQ_CAP_BITS` raises ValueError before any record is judged.
* The FENCE/HALT clause is split (`ref/seq_format.py:696-708`): without "R1" the
  all-zero rule and its message are exactly today's; with "R1" FENCE admits
  target[3:0] only. HALT is unchanged under every caps set.
* `disasm` prints the mask for a non-zero target (`ref/seq_format.py:912-914`) —
  "FENCE mask=0x5" in the test's case (j); a mask-0 FENCE still prints "FENCE".
* Every existing caller passes no `caps`, so it gets the empty set = today's rules.

## 4. TDD — RED then GREEN

The test, `evidence/qwen9b/sr/sr2_isa_tdd.py`, was committed (bfabbfe) before its
first run. Its docstring states the RED prediction before the run: the plan's
(a) (f) (g) (h), plus every sub-check that passes `caps=` (TypeError: the keyword
did not exist), with the default-call sub-checks and (i) passing. Case (j) is
added beyond the plan's (a)–(i) for the controller's backward-compatibility
requirement: the shipped 9B template `tb/scripts/w9/model_9b_s1.e4.seq` (its
sha256 checked against the pin in `sw/chat_seq.py:571-573`) validates at the
default caps, at caps=∅ and at caps={R1} with the same count (158536); all 1372
of its FENCEs carry target 0; a copy with one FENCE's target set to 0x5 is
refused by `validate_stream` at caps=∅ and admitted at caps={R1}.

| log | tree | result |
|---|---|---|
| `evidence/qwen9b/sr/n200_sr2_isa_tdd_RED.log:45-47` | bfabbfe (clean) | **RED**: 10 PASS, 28 FAIL; cases failing a b c d e f g h j, (i) PASS; rc 1 — as predicted |
| `evidence/qwen9b/sr/n201_sr2_isa_tdd_GREEN.log:2-3` | cceb282**+dirty** | **VOID — NFS staleness**, see §6 |
| `evidence/qwen9b/sr/n205_sr2_isa_tdd_GREEN.log:45-47` | cceb282 (clean) | **GREEN**: 38 PASS, 0 FAIL; `SR2_ISA_TDD: PASS`; rc 0 |

GREEN's substance: (b) FENCE target=0x5 refused at caps=∅ (default and explicit);
(a) admitted at caps={R1}; (c)(d)(e) target=0x10, HALT target=1, imm32=1, flags,
addr_lo, len_or_addr_hi and target=0x8000 refused under R1; (f) caps={R9} raises
in both entry points; (g) `seq_caps_set` of 0xDEADC0DE / 0xFAB1CA01 / 0xFAB1CA03
= ∅ / {R1} / {R1,R2}, `seq_caps_word({R1})` = 0xFAB1CA01, offset 0x64, unknown
bit 3 refused by name; (h) B17.0's parsed offset, magic and bit positions equal
hwmap's (`evidence/qwen9b/sr/n205_sr2_isa_tdd_GREEN.log:34`); (j) backward
compatibility holds and the masked stream is refused at ∅ / admitted at {R1}
(`evidence/qwen9b/sr/n205_sr2_isa_tdd_GREEN.log:37-44`).

## 5. Regressions

| gate | log | result |
|---|---|---|
| `evidence/qwen9b/g3/isa_bits.py` (plan: rc 0) | `evidence/qwen9b/sr/n206_isa_bits.log:46-49` | **FAIL, rc 1** — `ATTN: KV slot 0 is COLD (E_DMA_COLD)` in its section 3 |
| the same, on the PRE-SR2 tree (git archive of 32ce34d) — the control | `evidence/qwen9b/sr/n209_isa_bits_baseline_32ce34d.log:46-49` | **the same FAIL, rc 1** — pre-existing, not SR2's |
| `isa_bits.py --negative-control` | `evidence/qwen9b/sr/n207_isa_bits_negctl.log:26-27` | prints PASS, rc 0 — **UNINFORMATIVE while the positive run fails**: the negative_control function counts any perturbed run that returns False as REFUSED (`evidence/qwen9b/g3/isa_bits.py:936-952`), and the UNPERTURBED run already returns False, so a perturbation is "refused" whether or not the checker detected it (fix round 1, M1) |
| boardfree, after SR2 | `evidence/qwen9b/sr/n208_boardfree.log:71` `:118` `:150-152` | seq_run 2810/0, serve 84/1, chat_seq 407/1; `BOARDFREE_FAIL` |
| boardfree, BEFORE SR2 (tree 4facb02) — the baseline | `evidence/qwen9b/sr/n290_sr2_boardfree_baseline_HEAD.log:71` `:118` `:150-152` | **identical**: 2810/0, 84/1, 407/1 |

* **Boardfree triple unmoved: 2810 / 84 / 407** before and after. Both non-zero
  failure counts are pre-existing: chat_seq's [22] case is the known test defect
  (`NEXT_SESSION.md:1129-1134`); serve's "backend API check" fails because its
  args namespace lacks `reorder`/`reorder_check` (the chat_seq `--reorder` flags
  of BM1-T4/S1D), visible at `evidence/qwen9b/sr/n290_sr2_boardfree_baseline_HEAD.log:115-118`.
* **isa_bits is not rc 0 on this tree, with or without SR2.** Its last committed PASS is
  `evidence/qwen9b/s2/019_isa_bits_green.log` (run 2026-09-04 19:56 on tree
  a69fe1f); the COLD assert comes from the state-DMA warm rule in
  `ref/gen_layer_script.py`, which the equivalence harness's synthetic ATTN does
  not satisfy. Corroboration that the failure predates SR2 (fix round 1, M2):
  `git log -S E_DMA_COLD -- ref/gen_layer_script.py` names one commit, **75598a9**
  (2026-09-04 21:16, "chain(S3 step 1-2): the emitter's DDR state image …"),
  after 019's PASS — and the n209 control on the pre-SR2 tree fails identically.
  SR2 touches neither file.
* **Acceptance restated (controller ruling, fix round 1):** isa_bits is **out of
  scope — broken since 75598a9 (2026-09-04); negative control uninformative; a
  separate task SR-ISABITS repairs it before SR11a.**

## 5b. Fix round 1 (review I1, M1, M2, M5)

* **I1** — B17.1 now binds mask bit c to channel c and states there is no RTL
  interlock (§1 table rows, `docs/SEQ_ISA.md:1469-1487`).
* **M1, M2** — §5 above.
* **M5** — `hwmap.seq_caps_check` refuses a bare str (`frozenset("R1")` would be a
  set of characters). TDD case (k), committed before its run:
  RED `evidence/qwen9b/sr/n212_sr2fix1_isa_tdd_RED.log:48-50` — (k) FAIL, the
  other 38 PASS, as its docstring predicted; GREEN
  `evidence/qwen9b/sr/n213_sr2fix1_isa_tdd_GREEN.log:47-49` — 39/39 PASS.
  The stamps read `+dirty`: n212 for `sw/serve.py` (SR2b's concurrent,
  uncommitted edit) and `docs/SEQ_ISA.md` (this round's then-uncommitted B17.1
  text), n213 for `sw/serve.py` only. The test imports neither `sw/serve.py` nor
  anything that imports it, and reads only SEQ_ISA's B17.0 table, which that
  B17.1 edit did not change. Boardfree was not
  re-run: the guard only fires on a str argument, no caller passes `caps` yet, and
  a run now would carry SR2b's `sw/serve.py` edit.

## 6. The void runs n201–n204 (NFS attribute staleness)

n201–n204 were launched on snoke seconds after the implementation commit cceb282
was made on darthplagueis. snoke's NFS client still served the pre-edit
`sw/hwmap.py` (and a torn view of `ref/seq_format.py`): the stamps read
`cceb282+dirty` with ` M ref/seq_format.py` / ` M sw/hwmap.py`
(`evidence/qwen9b/sr/n202_isa_bits.log:2-4`), and the boardfree run died on
`AttributeError: module 'hwmap' has no attribute 'seq_caps_check'`
(`evidence/qwen9b/sr/n204_boardfree.log:29`) — the new seq_format against the old
hwmap. They are committed as the record and cite nothing. Before n205–n209 the
md5 of `sw/hwmap.py`, `ref/seq_format.py` and the test were compared on both
hosts (identical) and snoke's `git status` was clean; n205–n208 stamp `cceb282`
clean.

## 7. Folded / deviations

* **Review minor N1** (the plan's ≤ 5 % UI-cut wording) was folded into the plan
  itself by the plan's own first doc touch (`docs/superpowers/plans/2026-09-27-seq-rtl-round.md:29`);
  it needs nothing in SR2's files. Recorded as folded.
* The interpreter is `/home/cah/.venv/bin/python`, not the plan's `python3`:
  snoke's system python3 has no numpy, which `ref/seq_format.py` imports.
* Commits are split (doc + test → RED log → implementation → logs + this doc)
  instead of the plan's single step-5 commit, so the test is committed before
  its RED run and GREEN runs on a clean committed tree.
* Log numbers: n200 RED; n201–n204 void; n205 GREEN, n206/n207 isa_bits,
  n208 boardfree, n209 the isa_bits control; n290 the boardfree baseline (run
  first, before any SR2 edit).
* `seq_caps_check` is a fifth hwmap name beyond the plan's four — the single
  home of the "unknown name refused by name" rule.
* The spec's §1.1 wording "under an explicit isa="2.3" argument" is superseded
  by the plan's device-keyed `caps=` (controller ruling); B17 states the caps form.

## 8. Does NOT establish

That the RTL implements B17 (SR3); that any emitted stream uses the mask (SR4);
that any host path passes the device's caps (SR6 — `sw/seq_run.py`'s three
`validate_stream` calls still pass none, i.e. the empty set, so an r1 stream is
refused on every bitstream today, which is the safe direction).
