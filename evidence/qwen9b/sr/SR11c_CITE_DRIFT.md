# SR11c — the round's citation drift, repaired in one owner's passes on a quiet tree

**Verdict.** Every line-number citation that this round's code edits moved has been re-pointed, digits only, by
five o3 drift passes and a proven pre-existing-stale pass. Each pass ran --plan, then the hand-check sheet, then
--fix, then --verify. Every --fix was checked mechanically as digits-only. The launcher's busy-source refusal is
tested end to end on a fake project (9 passed, 0 failed). spec_cites introduces no failure anywhere SR11c
touched. What cannot be proven is listed for SR9 (§8).

Dispatched on 72a4713 (task brief `.superpowers/sdd/2026-09-27-seq-rtl/task-SR11c-brief.md`, both addenda).
Every run was on snoke, through `evidence/qwen9b/sr/sr_run.sh`, with `/home/cah/.venv/bin/python`. The log block is
n2000–n2048. Nothing numeric ran on darthplagueis.

## 1. Method, and the judgment calls that shaped it

* **The wrapper** is `evidence/qwen9b/sr/sr11c_drift.sh`, committed before first use. It holds one o3 argument
  list per pass.
* **Documents are read at the PASS BASE (`--doc-base` = `--base`), not at HEAD.** The precedents read them at HEAD.
  At HEAD, a token written after the base in post-edit coordinates (for example SEQ_ISA §B17.2) is swept as if
  it were a base number. That makes it a silent REPAIR and a double shift. Read at the base, such a token is not
  in the sweep, so a rewrite of it can only show as COLLATERAL, which is hand-checked. This also enforces the
  first-commit-after-base exclusion by construction.
* **The exclusion rule is applied mechanically** by `evidence/qwen9b/sr/sr11c_excl.py`, with every exclusion and
  its reason printed into the log. The rule has three parts:
  * a citing file whose first commit is not an ancestor of the base;
  * the standing list: the six gate docs, every drift wrapper and hand-repair script, the fix-round records,
    o3's docstring and `evidence/qwen9b/s3/S3_CHAIN.md`;
  * **all of tb/**, which is SR13a's territory, and SR13a's sr13a_* and n13* files.
* **The hand-check sheet** is `evidence/qwen9b/sr/sr11c_audit.py`. For every planned rewrite it prints:
  * its class;
  * whether the citing line is verbatim at the base;
  * the base content at the old line, and the work content at the proposed line.

  A REPAIR on a line not verbatim at the base is flagged SUSPECT.
* **Digits only** is checked by `evidence/qwen9b/sr/sr11c_digits_only.sh` before every commit. It requires the
  digit-stripped removed and added lines to be the same multiset, with equal line counts per file.
* **Hand repairs** are made with the Edit tool. The Edit tool is used for every document edit.
  `evidence/qwen9b/sr/sr11c_hand_repairs.py --check` is the residual proof: the new token is present, the old
  one is gone, and it prints the base text beside the work text. Its final run is 86 entries, 0 bad
  (`evidence/qwen9b/sr/n2038_sr11c_rtl_hand_check_final.log`).

### 1.1 The hole the brief's pass 2 did not name: SR11a fix 2 (cfbf90f)

cfbf90f (11:07) moved nearly every line of `sw/seq_run.py` (+4 at line 20, +13 by line 168, …), of `sw/chat_seq.py`
and of `ref/seq_chat.py`. Its drift was applied to NEXT_SESSION.md only
(`evidence/qwen9b/sr/n1149k_sr11af2_drift_fix_nextsession.log`). So every other document still named 9c8e73b
lines.

SR7 fix 1's pass (ea72c43, base 99c13ce) then mapped those 9c8e73b numbers through the 99c13ce map. For example,
SR6_HOST's parse_caps cite 3121 (parse_caps at 9c8e73b) became 3163, where nothing relevant sits. SR13b's base
966cbcf is later still.

**So pass 2 is split:**
* **2a:** base 9c8e73b for the three files. Its precondition is `evidence/qwen9b/sr/sr11c_undo_ea72c43.py`. It
  put back the seq_run numbers ea72c43 had written into 12 documents — 29 lines carrying 57 tokens — and only on
  lines verbatim at 9c8e73b.
  Check: `evidence/qwen9b/sr/n2006_sr11c_undo_ea72c43_check.log` (29 revert, 0 skip, 0 conflict). Apply:
  `evidence/qwen9b/sr/n2007_sr11c_undo_ea72c43_apply.log`.
* **2b:** base 966cbcf, for NEXT_SESSION.md alone. It is the only document in 966cbcf coordinates, having been
  re-aimed through cfbf90f by n1149k and through fa7f5df by ea72c43.

Nothing was shifted twice. The brief's pass 2 as written (966cbcf over every document) would have carried
cfbf90f's offset forever.

## 2. The passes

| pass | base | --plan (REPAIR / COLLATERAL) | --fix | hand | --verify |
|---|---|---|---|---|---|
| 1 `sw/hwmap.py` | 67181c6 (c8aef0e^) | 137 / 8 (`evidence/qwen9b/sr/n2001_sr11c_hwmap_plan.log`); audit 0 suspect (`evidence/qwen9b/sr/n2002_sr11c_hwmap_audit.log`); 8 cleared, SAFE (`evidence/qwen9b/sr/n2003_sr11c_hwmap_plan_allowed.log`) | 145 tokens in 29 files (`evidence/qwen9b/sr/n2004_sr11c_hwmap_fix.log`) | none | **PASS** (`evidence/qwen9b/sr/n2005_sr11c_hwmap_verify.log`) |
| 2a seq_run + chat_seq + seq_chat | 9c8e73b | 256 / 1 (`evidence/qwen9b/sr/n2008_sr11c_host9c_plan.log`); audit (`evidence/qwen9b/sr/n2009_sr11c_host9c_audit.log`); SAFE (`evidence/qwen9b/sr/n2010_sr11c_host9c_plan_allowed.log`) | 257 tokens in 38 files (`evidence/qwen9b/sr/n2011_sr11c_host9c_fix.log`) | 18 re-aims + 1 keep (`evidence/qwen9b/sr/n2016_sr11c_host9c_hand_check.log`) | lists only the 11 UNRESOLVED + 4 HALF-MAPPED (`evidence/qwen9b/sr/n2017_sr11c_host9c_verify_after_hand.log`); **PASS** with their 4 citers excluded (`evidence/qwen9b/sr/n2018_sr11c_host9c_verify_excl_hand.log`) |
| 2b seq_run + chat_seq | 966cbcf | 20 / 0, SAFE, NEXT_SESSION.md only (`evidence/qwen9b/sr/n2019_sr11c_host96_plan.log`, `evidence/qwen9b/sr/n2020_sr11c_host96_audit.log`) | 20 tokens (`evidence/qwen9b/sr/n2021_sr11c_host96_fix.log`) | none | **PASS** (`evidence/qwen9b/sr/n2022_sr11c_host96_verify.log`) |
| 3a seq_model + seq_format | 7e64d05 (d501068^) | 189 / 7 (`evidence/qwen9b/sr/n2023_sr11c_model_plan.log`, `evidence/qwen9b/sr/n2024_sr11c_model_audit.log`); SAFE with 4 cleared and 2 files excluded (`evidence/qwen9b/sr/n2025_sr11c_model_plan_allowed.log`) | 184 tokens in 27 files (`evidence/qwen9b/sr/n2026_sr11c_model_fix.log`) | 18 re-aims + 4 keeps (`evidence/qwen9b/sr/n2027_sr11c_model_hand_check.log`) | SR4 NOT excluded: lists only the 7 UNRESOLVED + 4 HALF-MAPPED (`evidence/qwen9b/sr/n2028_sr11c_model_verify.log`); **PASS** with their citers excluded (`evidence/qwen9b/sr/n2029_sr11c_model_verify_excl_hand.log`) |
| 3b the four RTL files | 2910d4d | 484 / 26 (`evidence/qwen9b/sr/n2030_sr11c_rtl_plan.log`, `evidence/qwen9b/sr/n2031_sr11c_rtl_audit.log`); 26 cleared, SAFE (`evidence/qwen9b/sr/n2032_sr11c_rtl_plan_allowed.log`) | 510 tokens in 51 files (`evidence/qwen9b/sr/n2033_sr11c_rtl_fix.log`) | 33 re-aims + 12 keeps (`evidence/qwen9b/sr/n2035_sr11c_rtl_hand_check.log`) | lists only the 11 UNRESOLVED + 7 HALF-MAPPED (`evidence/qwen9b/sr/n2036_sr11c_rtl_verify_after_hand.log`); **PASS** with their citers excluded (`evidence/qwen9b/sr/n2037_sr11c_rtl_verify_excl_hand.log`) |

Commits: d2514a0 (1), 5e20308 (2a), f6190bd (2b), 615db96 (3a), f25c955 (3b), e2ef302 (4).

* **Combined or separate.** Each distinct base is its own pass. Files sharing a base were combined in one
  invocation: the three host files in 2a, the two model files in 3a, the four RTL files in 3b. That way a bare
  continuation on a line naming two of them is AMBIG and untouched, rather than bound to one file.
* **SR11b's three files** (reorder_e4, seq_cost, ov_census since 99c13ce) were not re-run. Their hand re-aims were
  not undone: none of them is in any SR11c plan as a rewrite target. SR4_R1_MODEL's 615/1369 are handled in §3.
* **The RTL files changed in COMMENTS ONLY** (digit edits, no line count change). These are rtl/layer_chan.sv,
  rtl/matvec_engine.sv and rtl/state_dma.sv, plus synth/exp_uram/rtl/layer_chan.sv. There is no behaviour change,
  and any future build takes them.
* **Audit SUSPECTs.** Pass 2a flagged 7 and pass 3b flagged 30. Every one of them names a token present, with the
  same count, in the document at the base (checked per token). They are flagged only because an earlier pass
  today rewrote another cite on the same line.

## 3. COLLATERAL, each checked by hand and cleared by name

Every cleared token's reason is printed in its --plan / --fix log.

* **Pass 1 (8), each a number collision.** In each case the base content at the old line is the work content at
  the new line:
  * L_SDMA_CYC at 225 → 229;
  * the SHAPE_ISA_BY_VERSION dict 96-101 → 96-105 (four rows added inside it), ×4;
  * L_TCNT2 at 178 → 182, ×2;
  * SCRATCH_WORDS_BUILT at 288 → 292.
* **Pass 2a (1).** In the migration spec, `sw/chat_seq.py:1713` is in the "per-op vector lengths" row with its six
  siblings. The base line is blank, so the row was already stale. It is carried by content with its row, and
  listed for SR9.
* **Pass 3a (7).**
  * **Cleared (4):**
    * S1_ISA's seq_format 769-776 → 854-861, ×2: the LAYER decode block, a collision.
    * The migration spec's seq_model continuation 432-493 → 432-638, and its narrative range 424-543 → 424-697.
      Both were stale at the base, because _layer_cmd is at 635 there. They are carried by content and listed
      for SR9.
  * **Not moved (3), and their files excluded from --fix:**
    * `evidence/qwen9b/sr/SR4_R1_MODEL.md` :27/:38 name 615/1369. These are SR11b's hand re-aims (base 470/1174,
      the caps=frozenset() lines), and moving them again would break them. SR4's nine REPAIRs were applied by hand
      exactly as the plan maps them, and --verify n2028 checks them with SR4 not excluded.
    * `sw/chat_seq.py` line 2243 says "The old docstring cited …" — it quotes a past cite, so it is kept.
* **Pass 3b (26).** Every one is at the base, and its base content equals its proposed content.
  * 23 are collisions, or header ranges that SR12's inserts widened:
    * seq_unit 25-55, 19-56, 40-56 (×3), 49-53, 291-317, 320, 347;
    * matvec_chan 12-39, 545 (×2), 554;
    * seq_movers 190 (×2);
    * matvec_engine 179, 221, 247, 283 (×2), 527.
  * 3 were already stale in content at the base: matvec_engine 291 and 262 / 262-264, in G3_3's tables and the
    spec. They are carried by content and listed for SR9.

## 4. Hand repairs: the lines the edits rewrote

`evidence/qwen9b/sr/sr11c_hand_repairs.py` holds all 86 entries with their reasons. The categories:

* **2a.**
  * The validate_stream sites that gained shape_isa: seq_run 316/624/3290/3334 → 412/723/3497/3548, and chat_seq
    477/518 → 480/521.
  * SEQ_RTLS 669-682 → 672-685.
  * --seq-rtl 6783 → 6879.
  * The Resident dict 2533-2537 → 2563-2570, and 2534 → 2564.
  * seq_run 9-23 is kept: the module contract's steps 0-1 still end "same set." on 23.
* **3a.**
  * SR4 (above), plus 873 → 1063 and the FENCE arm 923-927 → 1116-1122.
  * _movx 769-785 → 923-947, the MVGO x check 833 → 1003, and SeqExec state 504-510 → 649-656.
  * The SV1 MOVX message 784 → 945, carried by content. The SV1 pair is stale anyway (§8).
  * Kept: G3_4's record of where SEQ_ISA v1.5 pointed (seq_format 506-509).
* **3b.**
  * seq_unit's MOVY target check 793 → 821, and its arm 787-793 → 813-821.
  * res_row_q 628 → 643.
  * The XWIN burst base 658 → 674, and X_DRAIN 652-658 → 668-674.
  * x_line and row_in start / row-end 455 / 470 / 456 → 480 / 495 / 481.
  * The x_line comment 224-227 → 241-246.
  * The SEQ_CAPS literal 335-336 → 338-339, and mv_fmask 947 → 977.
  * The SHAPE header table 18-19 / 18-32 / 18-35 → 18-20 / 18-42 / 18-45.
  * The SHAPE line `rtl/matvec_chan.sv:18` was rewritten in place, so it is **kept at 18** in all 12 citing
    documents.

## 5. B17.1 / B17.2 — where the RTL and model cites land

* **B17.1**, `docs/SEQ_ISA.md:1469-1486`. The channel binding is now `rtl/seq_movers.sv:255` (logic [3:0]
  chan_pend), set by a no-wait MVGO at `rtl/seq_movers.sv:729`, cleared at `rtl/seq_movers.sv:754`, and scanned
  by F_SCAN at `rtl/seq_movers.sv:846`. At 2910d4d these were 241 / 711 / 736 / 828, each moved by SR12's inserts.
  The model's RunningChannelError stays `ref/seq_model.py:455`, because nothing above it moved. The pass's
  hazard assert stays `ref/scripts/reorder_e4.py:225`, SR11b's re-aim, untouched.
* **B17.2**, `docs/SEQ_ISA.md:1519`. SR12 fix 1 wrote `rtl/matvec_chan.sv:18-31` in post-edit coordinates, and it
  is correct at HEAD: the SHAPE register comment, including the readback-is-0 sentence. The rtl pass left it
  untouched, because its start line was rewritten in place (map None). The section carries no other cite into
  the edited files.

## 6. Pass 4 — pre-existing stale cites the digit shifts preserved

* **The survey.** `evidence/qwen9b/sr/sr11c_stale_survey.sh` runs spec_cites over the 55 documents that cite the
  round's files by line. Before pass 4: EXIST 0, RANGE 0, QUOTE 68 (`evidence/qwen9b/sr/n2040_sr11c_stale_survey.log`).
* **The proof.** `evidence/qwen9b/sr/sr11c_prove_stale.py` proves a stale token in four steps:
  1. find the commit that introduced its quotation, or for the brief's no-quote list, its claim with a code
     anchor;
  2. require the quote or anchor within 6 lines of the cited number there (spec_cites' own criterion), so the
     token was right when written;
  3. map that number to HEAD with o3's own line map;
  4. require the quote or anchor within 6 lines at HEAD.

  38 were PROVEN (`evidence/qwen9b/sr/n2044_sr11c_prove_stale.log`). n2043's anchor for S1P_SHIP:100 could not
  match, because the comment says "nearer", and it was corrected. Among the proven:
  * the brief's example, `evidence/qwen2b/rc/t4_wall8_probe.py` EMBLOG2, 1425 → `sw/seq_run.py:1762`;
  * the plan's _tau pair → `ref/seq_cost.py:320` and `ref/seq_cost.py:351`;
  * `evidence/qwen9b/ov/S1P_SHIP.md` :99-101 → `ref/seq_cost.py:164`, `ref/seq_cost.py:183`, `ref/seq_cost.py:155`.
    These were right at their C0, b7f7014 (121 / 140 / 112 there), and drifted afterwards. So the SR11b re-review's
    "off at creation" reading does not hold for them;
  * G3_3's EXPECTED_SEQ_VERSION → `sw/seq_run.py:132`;
  * 30 quote-anchored cites.
* **The counts, reconciled (fix round 1, m1).** n2044's 38 PROVEN lines are 37 distinct tokens: RD9_GATE:3741's
  token is proven twice, once by each of its two quotes. 2 of the 37 were left as history (below), so 35 were
  applied, and 2 more tokens took their proven twin's map. That makes **37 digit edits in 14 documents**: 36 in
  e2ef302, whose message says 36, plus G3_1_ISA:562 in the same commit. Fix round 1 adds 3 proven (RC_GATE, §12).
* **Applied: 37 digit edits in 14 documents** (e2ef302), with the Edit tool.
  * Two proven tokens were deliberately left, because they are records of history:
    * S1_ISA:471's "HALF-MAPPED 729-730" is a report of what a past tool printed;
    * G3_4:1498's :330 records what the spec cited.
  * Two tokens took their proven twin's map: S1_ISA:471's "now at 802-804" and G3_1_ISA:562's 5060. Each has the
    same number, content and quote as a proven token.
* **Result.** n2045 finds 0 left to prove. The final survey has QUOTE 37, EXIST 0, RANGE 0
  (`evidence/qwen9b/sr/n2048_sr11c_stale_survey_final.log`). The survey covers only the round's files, and none of
  those remaining failures was introduced (§9).

## 7. The launch_incr busy-refusal test (SR7 re-review minor)

`evidence/qwen9b/sr/sr11c_launch_incr_busy.sh` works on a FAKE source only: a gitignored synth/out_sr11c_fakebusy_PID,
removed on exit, with an empty temp file as the reference dcp. The result is 9 passed, 0 failed, with no Vivado
launched (`evidence/qwen9b/sr/n2000_sr11c_launch_incr_busy.log`).

| case | mode | result |
|---|---|---|
| busy: a live pid on this host, no end marker | the real launch path, LAUNCH_INCR_CHECK_ONLY unset | rc 1, the FATAL "has a Vivado run in flight", no out dir |
| busy: queued impl_1 | check-only | rc 1, no out dir |
| CONTROL: the same fake made idle | check-only | rc 0, the CHECK_ONLY line, no out dir |

The control shows the refusal is the busy state, not an argument or path error. No real project was touched.

## 8. Listed for SR9 (not provable by o3; nothing here was edited)

* **The 37 QUOTE failures left** in n2048. The full list and the reason for each is in
  `evidence/qwen9b/sr/n2045_sr11c_prove_stale_after.log`. The reasons fall into five groups:
  * the quotation's introducing commit is not found (text edited since): 2BOARD 442/452/469/622/648/704/795 and
    NEXT 579;
  * born stale: NEXT 782, track-r plan 330, board-idle 152;
  * line rewritten since: NEXT 779, the migration spec 2035, G3_4 1284;
  * not uniquely found: the migration spec 371/1602;
  * ARCHITECTURE 118/187/418: the quote is not in any cited file.
* **No-quote tokens that are stale by reading but not provable**, with the likely target at HEAD for SR9 to
  confirm:
  * the plan :211's third token, the docstring "sizes 1 and 3": `ref/seq_cost.py:73-74`;
  * SV1_S1_VERIFY :109-110, the MOVX/MVGO refusals: `ref/seq_model.py:944` and `ref/seq_model.py:961`;
  * OV1 :231 and `ref/scripts/reorder_e4.py` :35, "every FENCE field must be zero": the FENCE decode, now
    `rtl/seq_unit.sv:834-837`. Its meaning changed with R1;
  * RD9_GATE :3043's region= argument: `ref/seq_model.py:615`;
  * the state-spill plan's gate() at 1272: `ref/seq_model.py:1369`;
  * the migration spec :1333's ng7 row: G3.3 deleted ng7;
  * the migration spec's per-op vector-length row (chat_seq ×7), its _layer_cmd row (`ref/seq_model.py:789`), and
    its :2618 narrative;
  * G3_3 :423/:810's seq_run 124/130: the version-hash lines, a twin of :441's proven 132;
  * G3_3 :184's continuations after the proven 235;
  * RD9_GATE :3741's dangling 558 after the proven 624.
* **Residue in excluded files.** These were not edited, by rule.
  * tb/ (SR13a's): tb/tb_seq_chip.sv 1 seq_run token (the known EMBLOG2 one), tb/scripts/gen_chat_i1_vectors.py
    1 model token, and tb/seq_stub_mvchan.sv 1 RTL token (`evidence/qwen9b/sr/n2047_sr11c_tb_residue.log`).
  * The standing-list gate docs and records (SR7_R1_BUILD, SR11a_R2_MODEL, SR11b/SR12/SR13b gate docs, sr13b_*,
    the hand-repair scripts) keep their as-written coordinates.
* **Not in scope and not checked:** citations INTO docs/SEQ_ISA.md, the o3 --doc-cites class, which the round's
  SEQ_ISA edits moved; and the bare seq_unit.sv:NNN pointers in SEQ_ISA without the rtl/ prefix, which are
  invisible to both tools. **The bare pointers were done in fix round 1**, in §12.

## 9. Doc gate

* **The baseline.** `evidence/qwen9b/sr/sr11c_spec_cites_baseline.sh` runs spec_cites over all 85 files SR11c
  touched, at 72a4713 and in the work tree: 314 FAIL keys at the base, 288 in work, and **INTRODUCED 0**
  (`evidence/qwen9b/sr/n2041_sr11c_spec_cites_baseline.log`). The final baseline, run after NEXT_SESSION's dated
  line on the committed tree, is n2051. NEXT_SESSION.md's new item 18 moves no line that any document cites:
  0 drifted of 26 (`evidence/qwen9b/sr/n2049_sr11c_doc_cites_nextsession.log`).
  * The 26 REPAIRED are SR12-broken quotes the rtl pass fixed: SR3_R1_RTL ×8, G3_3 ×7 and others.
  * The files with pre-existing FAILs cannot reach FAIL 0 without claim changes or unprovable re-aims, which is
    SR9's work. At n2051 there are 20 of them:
    * docs/superpowers/plans/2026-08-12-qwen2b-track-r.md, docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md
      and docs/superpowers/specs/2026-09-24-board-idle-counters-design.md;
    * docs/ARCHITECTURE.md, docs/QWEN35_2BOARD_FEASIBILITY.md and docs/QWEN35_NEXT_FEASIBILITY.md;
    * ref/scripts/bytes_per_token.py, ref/seq_chat.py and ref/seq_format.py;
    * evidence/qwen_next/feas/ddr_fit.py, evidence/qwen9b/g2/d_stage_check.py, evidence/qwen9b/g3/G3_3_MATVEC.md,
      evidence/qwen9b/g3/G3_4_LAYER.md, evidence/qwen9b/g6/g6_emblog2.py and evidence/qwen9b/g6/g6_longctx_lockstep.py;
    * evidence/qwen2b/q2/v4/GPTQ.md, evidence/qwen2b/q2/v4_v5/V4_V5.md, evidence/qwen2b/rc/RC_GATE.md and
      evidence/qwen2b/rc/TIMING_035.md;
    * evidence/qwen9b/sr/SR3_R1_RTL.md.

    Fix round 1's final list is n2064 (§12).
* **spec_cites LAST**, alone, on the committed tree. It covers this document, NEXT_SESSION.md, and every touched
  file that the baseline shows at zero FAIL keys. The log is n2052. n2050 is the precheck on the uncommitted
  doc.

## 10. Rule notes

* **One spec_cites dry run on snoke** (the gate doc before n2050) went unlogged. It was read-only and gave the same
  result that n2050 records.
* **Two no-op python3 invocations ran on darthplagueis.** One was an empty heredoc, the other a `-c print()`
  typed while building a sed line. Neither ran project code or arithmetic.
* **The Edit tool dropped one space** in a column-aligned txt line (seq_isa_ref_sweep.txt:62). The digits-only
  check caught it before the commit, and it was restored.
* **Pass 1's first commit** carried only its logs, because the pathspec was evaluated after git add. It was
  amended in place before any other commit: d2514a0.

## 11. Logs

| log | what |
|---|---|
| n2000 | launch_incr busy-refusal test, 9/0 |
| n2001–n2005 | pass 1: plan, audit, plan with the checked tokens cleared, fix, verify PASS |
| n2006–n2007 | undo of ea72c43's mis-mapped seq_run tokens: check, apply |
| n2008–n2018 | pass 2a: plan, audit, plan-allowed, fix, verify (n2012 before the hand repairs), hand checks n2013 / n2016 (n2013 predates the plan :276 entries), verifies n2014 / n2017 and excl-hand n2015 / n2018 |
| n2019–n2022 | pass 2b: plan, audit, fix, verify PASS |
| n2023–n2029 | pass 3a: plan, audit, plan-allowed, fix, hand check, verify, verify excl-hand PASS |
| n2030–n2038 | pass 3b: plan, audit, plan-allowed, fix, verify (n2034 before the hand repairs), hand check, verify, verify excl-hand PASS, final hand check 86/0 |
| n2040 / n2046 / n2048 | stale survey: before pass 4 / after / final |
| n2041 | spec_cites baseline over the 85 touched files, INTRODUCED 0 |
| n2042–n2045 | proofs (n2043 had the S1P:100 anchor that could not match; n2045 after the edits) |
| n2047 | tb/ residue per pass (read-only plans) |
| n2049 | citations into NEXT_SESSION.md after item 18: 0 drifted of 26 |
| n2050 | spec_cites precheck over this doc and NEXT_SESSION.md (dirty tree) |
| n2051 / n2052 | final baseline / spec_cites LAST |

SR13a committed e7802a3 (its own census logs) during this task. Its files are not SR11c's, and the baseline's file
list is taken from SR11c's own commits.

## 12. Fix round 1 (the task review: I1-I3, m1-m8)

Started at 77f8445. SR13a's r2 runs were in flight throughout, and no SR13a file was touched. Every edit was a
digit edit made with the Edit tool (or applied by the committed tool named for it), and each was checked by
`evidence/qwen9b/sr/sr11c_digits_only.sh`.

**I1.** `evidence/qwen9b/sr/n2047_sr11c_tb_residue.log` and `evidence/qwen9b/sr/n2048_sr11c_stale_survey_final.log`
are now committed (e54ca9b).

**I2: SEQ_ISA's bare RTL pointers — 24 pointer groups on 24 lines in fix round 1.** The table below merges 413 and
414 into one row. **Fix round 2 found four the hand-built list had missed** (§13), which makes 28 groups on 28 lines,
all PROVEN, and 0 left for SR9.
`evidence/qwen9b/sr/sr11c_bare_ptrs.py` (committed before first use) does the following:
* It takes each pointer's introducing commit (C0, 52d5cab / 9e1ee44 / 49f783f).
* It requires a code anchor at C0: within 2 lines for a single number, or inside a range.
* It maps with o3's line map to HEAD, and requires the anchor at HEAD.
* It keeps the bare form, so no rtl/ prefix is added.

n2053 was the first check. Some of its anchors did not match what the code says (for example DEAD_C0DE is written
with an underscore), and it is kept. n2054 is the proof and n2055 the apply. Every landing was opened (n2054
prints the C0 and HEAD text):

| SEQ_ISA line | claim | was | now (HEAD text) |
|---|---|---|---|
| 268 | reads outside the map return 0xDEADC0DE | 1420 | 1641 `else s_axil_rdata <= 32'hDEAD_C0DE;` |
| 277 | what a START does not clear | 905-913 | 1008-1016, I_IDLE start_req .. ist <= I_SYNC |
| 278 (fix round 2) | verified against the reset block (a continuation) | 856-876 | 958-979, if (!rstn) begin .. the last reset assignment (same span as at 9e1ee44; 980 is end else begin) |
| 291 | ABORT is CTRL bit 1 | 1218 | 1325, abort_req set from csr_wdata[1] |
| 295 | ABORT tested in I_FETCH | 925 and the continuation 924 | 1028 (if abort_req), 1027 (I_FETCH: begin) |
| 299 | STATUS bit layout | 1392-1393 | 1610-1611, the {err_code, of_ovf, of_cnt, …} readback |
| 314 | OF_DEPTH 64 | 318 | 387, localparam OF_DEPTH = 64 |
| 318 | the OUT FIFO pointers | 320-322 | 389-391, of_wp / of_rp / of_cnt |
| 324 | push when full sets of_ovf | 1161-1164 | 1268-1271 |
| 331 | csr_of_pop | 1406 | 1624 |
| 345 | the decode validator | 696-751 | 765-850, the validation block (SR3/SR12 grew it) |
| 349 | csr_addr | 826-832 | 928-934, function csr_addr .. endfunction |
| 361 | the ARG0/1/2 shadow | 964-968 | 1067-1071 |
| 373 | XWIN words = ceil(len/4) | 517 | 547, x_wwords |
| 383 | MOVY dequant, then clip | 437-449 | 467-479, the dequant comment block |
| 384 | the clip (continuation of 383) | 465-480 | 495-510, function clip_out |
| 391 | MVGO dispatch | 988-996 | 1093-1101, OP_MVGO: begin .. end |
| 413-414 | the JMP arm (a range split across two lines) | 1041- / 1053 | 1148- / 1160, OP_JMP: begin .. end |
| 426 | the indirection code | 844-847 | 946-949, ldc_base .. |
| 446 | the XRF index rule | 656-659 | 725-728, r_xrf4 .. xsel |
| 449 | xrf_rd | 335-339 | 404-408, function xrf_rd .. endfunction |
| 453 | the XOP write bound | 1055-1057 | 1162-1164, xrf write .. xrf_ovf |
| 461 | host XRF write decode | 1241-1242 | 1348-1349 |
| 467 | the XRF sideband | 107-111 and 820-823 | 120-124 (the XRF WRITERS comment) and 922-925 (cmd_wr_dynq8 ..) |
| 450 (fix round 2) | layer_chan.sv says XRF[3] is unsigned | 44-47 | layer_chan.sv 85-88, the XRF comment "XRF[3] (token id), which is UNSIGNED" |
| 597 (fix round 2) | TOPK-32 as verified | layer_chan.sv 556-580, 729-736, 747-748 | 953-977 (the TOPK-32 sibling-block comment and tk_fresh/tk_amax), 1179-1187 (the TK_* CSR reads), 1198-1199 (assign tk_ptr_we) |
| 602 (fix round 2) | the TOPK feed bundle | vec_alu.sv 425-426 | 433-434, topk_bun <= {…, am_g} |

**I3.** RC_GATE.md :80, :667 and :765 now read `sw/seq_run.py:1762`, EMBLOG2's programming docstring (bc822b7). All
three are PROVEN by `evidence/qwen9b/sr/n2057_sr11c_prove_stale_rcgate.log`:
* :80 and :667 from C0 f4495c7;
* :765 was born at 6b5d940 as the bare continuation :1228, which the tool cannot bind, so its C0 and N0 are given
  explicitly. 77584e9 later rewrote it to a full token that was already stale (1229).

n2056 is the first run, in which :765 was not provable.

**m1.** The counts are reconciled in §1.1 (29 lines carrying 57 tokens) and §6 (38 proven lines, 37 distinct, 37
edits).

**m2: REVERTED, and kept as history** (bc822b7):
* evidence/qwen_next/defect_a/demo_2b.py:9 is back to 978-979. It names the pre-fix reader, and the line is
  consistent again with its own continuation, 1213-1215.
* evidence/qwen_next/defect_a/sibling_2b_probe.py:5 is back to 1305-1308.

Both name a past commit's code, like sw/chat_seq.py:2243.

**m3.** SR6_HOST.md:221 quotes tb/tb_seq_chip.sv's comment token. It now reads 1242, which is what tb/tb_seq_chip.sv
:88 says. The tb token itself is stale (the EMBLOG2 docstring is `sw/seq_run.py:1762`) and is handed to SR9 / SR13a,
since tb/ is SR13a's.

**m6: pass 2c** (6eb8b38), which is sr11c_drift.sh host96b: base 966cbcf, over SR11a_R2_MODEL.md only, through
sr11c_excl.py --only.
* **The rule finds no other document.** Every file first committed in (9c8e73b, 966cbcf] that cites either file by
  line is a log.
* **Why base 966cbcf holds for this doc.** Its host cites were written at 6da0742, d89af35 and d9b25d5. For every
  line cited, those coordinates equal 966cbcf's, because 925d29d / fa7f5df moved only lines past 332 of seq_run
  and the 6da0742 lines cite seq_run 180 and chat_seq. ea72c43 never touched this doc, since it was excluded there.
* **The run.** n2058 plans REPAIR 17 / COLLATERAL 0, n2059 is the audit and n2060 the --fix.
* **Hand steps after the fix:**
  * The three record tokens on :332/:333 were reverted by hand: 121, the bare continuation 127 and 127, which are what n1149k and
    n1149l saw.
  * seq_run 312 → 365 (Artifacts.__init__, whose signature 3eb0728 rewrote) was re-aimed by hand.
* **The verify.** n2062 --verify lists exactly those: 2 kept tokens (4 lines) plus the UNRESOLVED 312. SR7_R1_BUILD.md
  has no host line cites, so it has no twin.

**m7.** SV1_S1_VERIFY.md:111, the MOVY refusal, 1010 → `ref/seq_model.py:1035`. 1010 is MVGO's BEATS assert, and
1035 is _movy's raise RunningChannelError, which was opened.

**m8.** The 20 files are named in §9.

**m4 and m5: recorded for SR9, not edited.**
* **m4.** Some digit edits were in live Python strings, not comments, for example ref/seq_chat.py:1062's f-string
  seq_model cite, and evidence-script prints. They are digits only with no logic change, and the one in seq_chat was
  already pre-existing stale.
* **m5.** Citations INTO docs/SEQ_ISA.md are partly stale, before and after this round: for example QWEN35_NEXT :436
  → 544 (the text is at 545), :334 → 828-837, and 2BOARD :731/:1778 → 1273-1281.

**Hand checks.** `evidence/qwen9b/sr/sr11c_hand_repairs.py` now has 96 entries, all OK
(`evidence/qwen9b/sr/n2061_sr11c_fix1_hand_check.log`).

**Doc gate.** The final baseline is n2064 and the LAST is n2065, alone, as the final commit; n2063 is the precheck.

| log | what |
|---|---|
| n2053 / n2054 / n2055 | bare pointers: first check (anchors as written, did not match), proof, apply |
| n2056 / n2057 | RC_GATE proof: without / with :765's explicit C0 |
| n2058–n2060, n2062 | pass 2c: plan, audit, fix, verify |
| n2061 | hand check, 96 entries, 0 bad |
| n2063 / n2064 / n2065 | spec_cites precheck / baseline / LAST |

## 13. Fix round 2 (the re-review: NEW-I1, NEW-m1..m3)

Started at fb1ea0e. SR13a's files were not touched.

* **NEW-I1.** SEQ_ISA:278 is the continuation "reset block at :856-876" of :277's pointer, and fix round 1's
  hand-built list had left it out. It is now in sr11c_bare_ptrs.py with anchor rstn. It is PROVEN from C0 9e1ee44:
  there, :856 is `if (!rstn) begin` and :876 is the last reset assignment. It maps to 958-979: `if (!rstn) begin`
  through the same last assignment, with `end else begin` at 980. The span is the same as when it was written.
* **NEW-m1.** The other bare RTL pointers in SEQ_ISA — layer_chan.sv :450 and :597, and vec_alu.sv :602, the only
  others — went through the same tool, with one anchor per range. All 4 are PROVEN, and each landing was opened
  (§12 table):
  * 44-47 → 85-88 (XRF[3] UNSIGNED), from C0 6472f92;
  * 556-580 / 729-736 / 747-748 → 953-977 / 1179-1187 / 1198-1199 (TOPK-32 block, TK_* reads, tk_ptr_we), from C0
    49f783f;
  * vec_alu 425-426 → 433-434 (topk_bun), from C0 6472f92.

  None is left for SR9.
* **NEW-m2.** The count reads "24 pointer groups on 24 lines" for fix round 1, and 28 groups on 28 lines with fix
  round 2 (§12; NEXT_SESSION item 18 is updated).
* **NEW-m3.** The tool's :295 label now says what the ISA sentence says: ABORT is tested at a record boundary, in
  I_FETCH. The anchor and landing were already right.
* **The tool** gained `--lines`, so a run touches only the named SEQ_ISA lines; fix round 1's entries are already
  applied. It was committed before first use. The logs are n2066 (proof, 4 PROVEN, 0 not provable) and n2067
  (apply, digits only).
* **Doc gate.** The precheck is n2068, the baseline over every SR11c-touched file is n2069, and the LAST, alone,
  is n2070.
