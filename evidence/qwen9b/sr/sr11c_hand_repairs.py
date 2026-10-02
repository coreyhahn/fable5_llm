#!/usr/bin/env python3
"""sr11c_hand_repairs.py — Task SR11c: every citation token the o3 drift
passes could not renumber (UNRESOLVED: the cited base line was REWRITTEN, so
there is no base->work map; HALF-MAPPED: a range with such an endpoint), and
every token a pass left to a human, re-pointed BY HAND after opening the
target.  The edits were made with the Edit tool (digits only); this list is
the whole decision, and --check is the residual proof the logs record:

  * the doc line now carries NEW and no longer carries OLD;
  * prints the pass-base text at OLD's endpoints beside the working-tree
    text at NEW's endpoints, so a reader sees what each cite moved to.

An entry with OLD == NEW is a HAND-CHECKED KEEP (the number is still right;
o3 reports it because a cited endpoint was rewritten in place).

Nothing numeric; reads git + files only.  Run on snoke via sr_run.sh.
  sr11c_hand_repairs.py --check [--pass NAME]
"""
import re
import subprocess
import sys

REPO = "/home/cah/r2d2/code/fpga/fable5_llm"
PLAN = "docs/superpowers/plans/2026-09-27-seq-rtl-round.md"
SPEC_SR = "docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md"
OV1 = "evidence/qwen9b/ov/OV1_DEPENDENCY_CENSUS.md"
# (pass, base, doc, doc line, OLD token, NEW token, why)
E = [
 # --- pass 2a (host9c, base 9c8e73b): cfbf90f / 3eb0728 rewrote these lines
 ("host9c", "9c8e73b", "evidence/qwen9b/sr/SR6_HOST.md", 40, "sw/seq_run.py:316-317", "sw/seq_run.py:412-414", "Artifacts: validate_stream (now + shape_isa, 2 lines) then manifest_caps_check"),
 ("host9c", "9c8e73b", "evidence/qwen9b/sr/SR6_HOST.md", 41, "sw/seq_run.py:624", "sw/seq_run.py:723", "relocate's validate_stream (now + shape_isa)"),
 ("host9c", "9c8e73b", "evidence/qwen9b/sr/SR6_HOST.md", 46, "sw/seq_run.py:3290", "sw/seq_run.py:3497", "art = Artifacts(... caps=caps, shape_isa=...)"),
 ("host9c", "9c8e73b", "evidence/qwen9b/sr/SR6_HOST.md", 46, "sw/seq_run.py:3334", "sw/seq_run.py:3548", "recs, rrep = relocate(... caps=caps, shape_isa=...)"),
 ("host9c", "9c8e73b", "evidence/qwen9b/sr/SR6_HOST.md", 53, "sw/chat_seq.py:477", "sw/chat_seq.py:480", "load_template's validate_stream (now + shape_isa)"),
 ("host9c", "9c8e73b", "evidence/qwen9b/sr/SR6_HOST.md", 53, "sw/chat_seq.py:518", "sw/chat_seq.py:521", "independent_step_images' validate_stream (now + shape_isa)"),
 ("host9c", "9c8e73b", "evidence/qwen9b/sr/SR6_HOST.md", 54, "sw/chat_seq.py:669-682", "sw/chat_seq.py:672-685", "SEQ_RTLS (now r0,r1,r2) .. REORDER_B_R1_PINS_LOG"),
 ("host9c", "9c8e73b", "evidence/qwen9b/sr/SR6_HOST.md", 63, "sw/chat_seq.py:6783", "sw/chat_seq.py:6879", "ap.add_argument(\"--seq-rtl\", ...) (metavar rewritten)"),
 ("host9c", "9c8e73b", "evidence/qwen9b/sr/SR6_HOST.md", 226, "sw/chat_seq.py:477", "sw/chat_seq.py:480", "the load_template validate site"),
 ("host9c", "9c8e73b", "evidence/qwen9b/sr/SR6_HOST.md", 226, "sw/chat_seq.py:518", "sw/chat_seq.py:521", "the independent_step_images validate site"),
 ("host9c", "9c8e73b", "evidence/qwen9b/sr/SR6_HOST.md", 38, "sw/seq_run.py:9-23", "sw/seq_run.py:9-23", "KEEP: steps 0-1 of the module contract still end 'same set.' on :23 (rewritten in place, continues to :32)"),
 ("host9c", "9c8e73b", PLAN, 59, "sw/seq_run.py:316", "sw/seq_run.py:412", "Artifacts' validate_stream"),
 ("host9c", "9c8e73b", PLAN, 59, "sw/seq_run.py:624", "sw/seq_run.py:723", "relocate's validate_stream"),
 ("host9c", "9c8e73b", PLAN, 275, "sw/seq_run.py:316", "sw/seq_run.py:412", "Artifacts' validate_stream"),
 ("host9c", "9c8e73b", PLAN, 275, "sw/seq_run.py:624", "sw/seq_run.py:723", "relocate's validate_stream"),
 ("host9c", "9c8e73b", PLAN, 276, "sw/chat_seq.py:477", "sw/chat_seq.py:480", "load_template's validate_stream"),
 ("host9c", "9c8e73b", PLAN, 276, "sw/chat_seq.py:518", "sw/chat_seq.py:521", "independent_step_images' validate_stream"),
 ("host9c", "9c8e73b", "evidence/qwen9b/g6/g6_longctx_lockstep.py", 26, "sw/chat_seq.py:2533-2537", "sw/chat_seq.py:2563-2570", "the Resident images dict (now inside try/except) .. the S1P form-B comment"),
 ("host9c", "9c8e73b", "evidence/qwen9b/g3/G3_1_ISA.md", 574, "sw/chat_seq.py:2534", "sw/chat_seq.py:2564", "\"lite\": Resident(... build_step(0, 0, \"lite\")) (re-indented)"),
 # --- pass 3a (model, base 7e64d05): SR4_R1_MODEL.md is EXCLUDED from o3's
 # --fix (its :27/:38 were hand re-aimed by SR11b to 615/1369, post-edit
 # coordinates, so o3 plans them as COLLATERAL that would move them again);
 # its nine o3 REPAIRs are applied here by hand, exactly as the plan (n2024)
 # maps them, plus its two tokens on rewritten lines
 ("model", "7e64d05", "evidence/qwen9b/sr/SR4_R1_MODEL.md", 28, "ref/seq_model.py:528", "ref/seq_model.py:682", "o3 REPAIR: self.caps = HW.seq_caps_check(caps)"),
 ("model", "7e64d05", "evidence/qwen9b/sr/SR4_R1_MODEL.md", 36, "ref/seq_model.py:783", "ref/seq_model.py:944", "o3 REPAIR: _movx's raise RunningChannelError("),
 ("model", "7e64d05", "evidence/qwen9b/sr/SR4_R1_MODEL.md", 37, "ref/seq_model.py:799", "ref/seq_model.py:961", "o3 REPAIR: _mvgo's raise RunningChannelError("),
 ("model", "7e64d05", "evidence/qwen9b/sr/SR4_R1_MODEL.md", 37, "ref/seq_model.py:852", "ref/seq_model.py:1035", "o3 REPAIR: _movy's raise RunningChannelError("),
 ("model", "7e64d05", "evidence/qwen9b/sr/SR4_R1_MODEL.md", 39, "ref/seq_model.py:1240", "ref/seq_model.py:1435", "o3 REPAIR: gate's SeqExec(... caps=caps).run"),
 ("model", "7e64d05", "evidence/qwen9b/sr/SR4_R1_MODEL.md", 40, "ref/seq_model.py:1835", "ref/seq_model.py:2096", "o3 REPAIR: the --seq help line"),
 ("model", "7e64d05", "evidence/qwen9b/sr/SR4_R1_MODEL.md", 43, "ref/seq_model.py:1667", "ref/seq_model.py:1887", "o3 REPAIR: selftest r1_movx_mask_skipped"),
 ("model", "7e64d05", "evidence/qwen9b/sr/SR4_R1_MODEL.md", 252, "ref/seq_model.py:1684", "ref/seq_model.py:1920", "o3 REPAIR: except RunningChannelError as e:"),
 ("model", "7e64d05", "evidence/qwen9b/sr/SR4_R1_MODEL.md", 253, "ref/seq_model.py:1689", "ref/seq_model.py:1925", "o3 REPAIR: got[name] = \"error\""),
 ("model", "7e64d05", "evidence/qwen9b/sr/SR4_R1_MODEL.md", 27, "ref/seq_model.py:615", "ref/seq_model.py:615", "KEEP: SR11b's hand re-aim, SeqExec's caps=frozenset() line (base :470)"),
 ("model", "7e64d05", "evidence/qwen9b/sr/SR4_R1_MODEL.md", 38, "ref/seq_model.py:1369", "ref/seq_model.py:1369", "KEEP: SR11b's hand re-aim, def gate(... caps=frozenset()) (base :1174)"),
 ("model", "7e64d05", "evidence/qwen9b/sr/SR4_R1_MODEL.md", 29, "ref/seq_model.py:873", "ref/seq_model.py:1063", "SF.validate(r, nrec=n, idx=pc, caps=self.caps, (now + shape_isa)"),
 ("model", "7e64d05", "evidence/qwen9b/sr/SR4_R1_MODEL.md", 32, "ref/seq_model.py:923-927", "ref/seq_model.py:1116-1122", "the FENCE arm: fmask .. the per-channel pop (was running -= {...})"),
 # --- pass 3a, the other documents' tokens on lines SR11a rewrote
 ("model", "7e64d05", "docs/QWEN35_NEXT_FEASIBILITY.md", 478, "ref/seq_model.py:504-510", "ref/seq_model.py:649-656", "SeqExec state init tcnt_seq .. res (xwin/res now XWinMem/ResMem)"),
 ("model", "7e64d05", "evidence/qwen9b/ov/SV1_S1_VERIFY.md", 110, "ref/seq_model.py:784", "ref/seq_model.py:945", "the MOVX refusal message (content successor; the SV1 pair is pre-existing stale, pass 4)"),
 ("model", "7e64d05", PLAN, 418, "ref/seq_model.py:769-785", "ref/seq_model.py:923-947", "base :769 (= work :923) .. the end of _movx's refusal (rewritten, now :947)"),
 ("model", "7e64d05", PLAN, 418, "ref/seq_model.py:833", "ref/seq_model.py:1003", "the MVGO no-MOVX check (assert -> if x8 is None: raise UnwrittenReadError)"),
 ("model", "7e64d05", "docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md", 277, "ref/seq_model.py:769-785", "ref/seq_model.py:923-947", "as the plan's :418"),
 ("model", "7e64d05", "docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md", 278, "ref/seq_model.py:833", "ref/seq_model.py:1003", "as the plan's :418"),
 ("model", "7e64d05", "docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md", 357, "ref/seq_model.py:769-785", "ref/seq_model.py:923-947", "_movx, as the plan's :418"),
 ("model", "7e64d05", "evidence/qwen9b/g3/G3_4_LAYER.md", 1167, "ref/seq_format.py:506-509", "ref/seq_format.py:506-509", "KEEP: the row's first column records where SEQ_ISA v1.5's pointers POINTED (history); its 'now' column is o3's"),
 ("model", "7e64d05", "sw/chat_seq.py", 2243, "ref/seq_model.py:456-595", "ref/seq_model.py:456-595", "KEEP (chat_seq.py excluded from the fix): 'The old docstring cited ...' quotes a past cite"),
 # --- pass 3b (rtl, base 2910d4d): SR12 (f4c1fb7, 2327d7a, 9ff3e7e) rewrote these lines
 ("rtl", "2910d4d", PLAN, 453, "rtl/seq_unit.sv:793", "rtl/seq_unit.sv:821", "MOVY target[15:4] check -> the v_movy_rsvd start-row check"),
 ("rtl", "2910d4d", PLAN, 454, "rtl/seq_movers.sv:628", "rtl/seq_movers.sv:643", "res_row_q <= 12'd0 -> res_row_q <= cmd_row"),
 ("rtl", "2910d4d", PLAN, 454, "rtl/seq_movers.sv:658", "rtl/seq_movers.sv:674", "the MOVX XWIN burst base (now + xword_q)"),
 ("rtl", "2910d4d", PLAN, 456, "rtl/matvec_engine.sv:455", "rtl/matvec_engine.sv:480", "x_line's start assignment (now XB_LINE under XBANK)"),
 ("rtl", "2910d4d", PLAN, 456, "rtl/matvec_engine.sv:470", "rtl/matvec_engine.sv:495", "x_line's row-end assignment"),
 ("rtl", "2910d4d", PLAN, 456, "rtl/matvec_engine.sv:456", "rtl/matvec_engine.sv:481", "row_in's start assignment (now RB_ROW under RBANK)"),
 ("rtl", "2910d4d", SPEC_SR, 104, "rtl/seq_unit.sv:787-793", "rtl/seq_unit.sv:813-821", "OP_MOVY validator arm (its target[15:4] line rewritten)"),
 ("rtl", "2910d4d", SPEC_SR, 106, "rtl/seq_movers.sv:658", "rtl/seq_movers.sv:674", "the MOVX XWIN burst base"),
 ("rtl", "2910d4d", SPEC_SR, 108, "rtl/seq_movers.sv:628", "rtl/seq_movers.sv:643", "res_row_q at MOVY dispatch"),
 ("rtl", "2910d4d", SPEC_SR, 112, "rtl/matvec_engine.sv:455", "rtl/matvec_engine.sv:480", "x_line start"),
 ("rtl", "2910d4d", SPEC_SR, 112, "rtl/matvec_engine.sv:470", "rtl/matvec_engine.sv:495", "x_line row end"),
 ("rtl", "2910d4d", SPEC_SR, 114, "rtl/matvec_engine.sv:456", "rtl/matvec_engine.sv:481", "row_in start"),
 ("rtl", "2910d4d", SPEC_SR, 210, "rtl/seq_unit.sv:793", "rtl/seq_unit.sv:821", "MOVY target[15:4]"),
 ("rtl", "2910d4d", SPEC_SR, 214, "rtl/seq_unit.sv:793", "rtl/seq_unit.sv:821", "MOVY target[15:4]"),
 ("rtl", "2910d4d", SPEC_SR, 220, "rtl/seq_movers.sv:628", "rtl/seq_movers.sv:643", "res_row_q"),
 ("rtl", "2910d4d", SPEC_SR, 222, "rtl/seq_movers.sv:658", "rtl/seq_movers.sv:674", "the XWIN burst base"),
 ("rtl", "2910d4d", SPEC_SR, 233, "rtl/matvec_engine.sv:455", "rtl/matvec_engine.sv:480", "x_line start"),
 ("rtl", "2910d4d", SPEC_SR, 234, "rtl/matvec_engine.sv:470", "rtl/matvec_engine.sv:495", "x_line row end"),
 ("rtl", "2910d4d", SPEC_SR, 236, "rtl/matvec_engine.sv:456", "rtl/matvec_engine.sv:481", "row_in start"),
 ("rtl", "2910d4d", OV1, 231, "rtl/seq_unit.sv:793-796", "rtl/seq_unit.sv:821-824", "by content (base 793 rewritten -> 821, 796 -> 824); PRE-EXISTING STALE: the FENCE decode is 834-837 (SR9)"),
 ("rtl", "2910d4d", OV1, 630, "rtl/seq_unit.sv:793-796", "rtl/seq_unit.sv:821-824", "as :231 (pre-existing stale, SR9)"),
 ("rtl", "2910d4d", OV1, 631, "rtl/seq_movers.sv:628", "rtl/seq_movers.sv:643", "res_row_q"),
 ("rtl", "2910d4d", OV1, 632, "rtl/matvec_engine.sv:455", "rtl/matvec_engine.sv:480", "x_line start"),
 ("rtl", "2910d4d", OV1, 632, "rtl/matvec_engine.sv:470", "rtl/matvec_engine.sv:495", "x_line row end"),
 ("rtl", "2910d4d", OV1, 632, "rtl/seq_movers.sv:652-658", "rtl/seq_movers.sv:668-674", "X_DRAIN .. the XWIN burst base"),
 ("rtl", "2910d4d", OV1, 633, "rtl/seq_movers.sv:652-658", "rtl/seq_movers.sv:668-674", "X_DRAIN .. the XWIN burst base"),
 ("rtl", "2910d4d", "ref/scripts/reorder_e4.py", 35, "rtl/seq_unit.sv:793-796", "rtl/seq_unit.sv:821-824", "as OV1 :231 (pre-existing stale, SR9)"),
 ("rtl", "2910d4d", "evidence/qwen9b/sr/SR3_R1_RTL.md", 28, "rtl/seq_unit.sv:335-336", "rtl/seq_unit.sv:338-339", "the SEQ_CAPS literal (r2 bit now 1; SR3's row records r2=0 at SR3)"),
 ("rtl", "2910d4d", "evidence/qwen9b/sr/SR3_R1_RTL.md", 32, "rtl/seq_unit.sv:947", "rtl/seq_unit.sv:977", "mv_fmask <= '0; (now + mv_xword/mv_row resets)"),
 ("rtl", "2910d4d", "docs/NVFP4_STUDY.md", 526, "rtl/matvec_engine.sv:224-227", "rtl/matvec_engine.sv:241-246", "the x_line comment ending 'the waived xline_q cone' (rewritten, 6 lines)"),
 ("rtl", "2910d4d", "evidence/qwen2b/rb/seq_isa_ref_sweep.txt", 62, "rtl/matvec_chan.sv:18-19", "rtl/matvec_chan.sv:18-20", "the SHAPE entry (now 2 lines) + the layout line"),
 ("rtl", "2910d4d", "evidence/qwen9b/g3/G3_3_MATVEC.md", 649, "rtl/matvec_chan.sv:18-32", "rtl/matvec_chan.sv:18-42", "the SHAPE header table through 'does not fit six bits'"),
 ("rtl", "2910d4d", "docs/SEQ_ISA.md", 634, "rtl/matvec_chan.sv:18-35", "rtl/matvec_chan.sv:18-45", "B9 heading: SHAPE .. the 0x24 XWIN line"),
 # --- fix round 1
 ("host96b", "966cbcf", "evidence/qwen9b/sr/SR11a_R2_MODEL.md", 261, "sw/seq_run.py:312", "sw/seq_run.py:365", "Artifacts.__init__ (3eb0728 rewrote the signature: + require_layout_key)"),
 ("host96b", "966cbcf", "evidence/qwen9b/sr/SR11a_R2_MODEL.md", 332, "sw/seq_run.py:121", "sw/seq_run.py:121", "KEEP (reverted after --fix): records the stale value n1149k found"),
 ("host96b", "966cbcf", "evidence/qwen9b/sr/SR11a_R2_MODEL.md", 333, "sw/seq_run.py:127", "sw/seq_run.py:127", "KEEP (reverted after --fix): what n1149l:14 listed"),
 ("fix1", "f4495c7", "evidence/qwen2b/rc/RC_GATE.md", 80, "sw/seq_run.py:1425", "sw/seq_run.py:1762", "I3 PROVEN (n2057): EMBLOG2 programming docstring"),
 ("fix1", "f4495c7", "evidence/qwen2b/rc/RC_GATE.md", 667, "sw/seq_run.py:1425", "sw/seq_run.py:1762", "I3 PROVEN (n2057)"),
 ("fix1", "6b5d940", "evidence/qwen2b/rc/RC_GATE.md", 765, "sw/seq_run.py:1425", "sw/seq_run.py:1762", "I3 PROVEN (n2057; born as the bare :1228 at 6b5d940)"),
 ("fix1", "7e64d05", "evidence/qwen9b/ov/SV1_S1_VERIFY.md", 111, "ref/seq_model.py:1010", "ref/seq_model.py:1035", "m7: _movy's raise RunningChannelError (1010 is MVGO's BEATS assert)"),
 ("fix1", "72a4713", "evidence/qwen9b/sr/SR6_HOST.md", 221, "sw/seq_run.py:1375", "sw/seq_run.py:1242", "m3: quotes tb/tb_seq_chip.sv's token as it reads (tb:88)"),
 ("fix1", "72a4713", "evidence/qwen_next/defect_a/demo_2b.py", 9, "ref/seq_chat.py:978-979", "ref/seq_chat.py:978-979", "m2 KEEP (reverted): the PRE-FIX reader, a past commit's code"),
 ("fix1", "72a4713", "evidence/qwen_next/defect_a/sibling_2b_probe.py", 5, "ref/seq_chat.py:1305-1308", "ref/seq_chat.py:1305-1308", "m2 KEEP (reverted): before the fix, a past commit's code"),
] + [("rtl", "2910d4d", d, n, "rtl/matvec_chan.sv:18", "rtl/matvec_chan.sv:18",
      "KEEP: the SHAPE register line, rewritten IN PLACE by SR12 (still :18)")
     for d, n in (("docs/QWEN35_2BOARD_FEASIBILITY.md", 414),
                  ("docs/QWEN35_2BOARD_FEASIBILITY.md", 1770),
                  ("docs/QWEN35_NEXT_FEASIBILITY.md", 505),
                  (PLAN, 455),
                  ("docs/superpowers/specs/2026-08-29-qwen35-9b-migration-design.md", 1550),
                  (SPEC_SR, 110),
                  ("evidence/qwen2b/q2/v4_v5/W8_SKETCH.md", 105),
                  ("evidence/qwen9b/g2/FINAL_BYTELOCK.md", 458),
                  ("evidence/qwen9b/g2/G2A_HOST.md", 520),
                  ("evidence/qwen9b/g2/G2A_HOST.md", 832),
                  ("evidence/qwen9b/g3/G3_3_MATVEC.md", 649),
                  (OV1, 631))]


def show(ref, path):
    return subprocess.run(["git", "show", "%s:%s" % (ref, path)], cwd=REPO,
                          capture_output=True, text=True).stdout.split("\n")


def ends(tok):
    fn, rng = tok.strip("`").rsplit(":", 1)
    a, _, b = rng.partition("-")
    return fn, [int(a)] + ([int(b)] if b else [])


def check(only=None):
    bad = n = 0
    for p, base, d, ln, old, new, why in E:
        if only and p != only:
            continue
        n += 1
        with open("%s/%s" % (REPO, d), encoding="utf-8") as f:
            line = f.read().split("\n")[ln - 1]
        pat = lambda t: re.escape(t) + r"(?![0-9-])"
        o = len(re.findall(pat(old), line))
        k = len(re.findall(pat(new), line))
        ok = (k >= 1) and (o == 0 or old == new)
        bad += not ok
        print("%s [%s] %s:%d  %s -> %s   (%s)" % ("OK " if ok else "BAD", p, d,
              ln, old, new, why))
        fn, oe = ends(old)
        _, ne = ends(new)
        b = show(base, fn)
        with open("%s/%s" % (REPO, fn), encoding="utf-8") as f:
            w = f.read().split("\n")
        for x, y in zip(oe, ne):
            print("      %s %s:%d  %r" % (base, fn, x, b[x - 1].strip()[:80]))
            print("      work    %s:%d  %r" % (fn, y, w[y - 1].strip()[:80]))
    print("SR11C_HAND_REPAIRS %s: %d entr%s, %d bad"
          % ("PASS" if bad == 0 else "FAIL", n, "y" if n == 1 else "ies", bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    only = sys.argv[sys.argv.index("--pass") + 1] if "--pass" in sys.argv else None
    sys.exit(check(only))
