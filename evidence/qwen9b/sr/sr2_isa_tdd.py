#!/usr/bin/env python3
"""sr2_isa_tdd.py — Task SR2's test (the sequencer RTL round, plan
docs/superpowers/plans/2026-09-27-seq-rtl-round.md, Task SR2): SEQ_ISA v2.3
B17.0 (SEQ_CAPS at SEQ 0x64) and B17.1 (the FENCE channel mask), the ONE
definition of the SEQ_CAPS constants in sw/hwmap.py, and the validator's
device-keyed `caps=` admission in ref/seq_format.py.

Committed BEFORE its first run (RED), then run again after the
implementation (GREEN).  Run on snoke through the round's wrapper:

    bash evidence/qwen9b/sr/sr_run.sh n2NN_... \
        /home/cah/.venv/bin/python evidence/qwen9b/sr/sr2_isa_tdd.py

Cases (the plan's (a)..(i), plus (j) the controller's backward-compatibility
and stream-level refusal checks):
  (a) validate(FENCE target=0x5, caps={"R1"}) passes
  (b) the same FENCE with caps=frozenset() (explicit, and the default) refuses
  (c) FENCE target=0x10 refuses under both caps sets
  (d) HALT target=1 refuses under both
  (e) FENCE imm32=1 refuses under both
  (f) caps={"R9"} raises (ValueError naming R9) in validate and validate_stream
  (g) seq_caps_set(0xDEADC0DE) == set(); seq_caps_set(0xFAB1CA01) == {R1};
      seq_caps_set(0xFAB1CA03) == {R1,R2}; seq_caps_word({R1}) == 0xFAB1CA01;
      HW.S_SEQ_CAPS - HW.SB == 0x64; an unknown bit (0xFAB1CA08) is refused
      by name
  (h) the offset, magic and bit positions in docs/SEQ_ISA.md B17.0's table
      equal hwmap's (doc and code cannot drift)
  (i) ref/seq_format defines no SEQ_CAPS* / SEQ_CAP* / seq_caps* name of its
      own (the one-definition rule): not in its namespace, not assigned or
      def'd in its source
  (j) BACKWARD COMPATIBILITY on the shipped 9B template
      tb/scripts/w9/model_9b_s1.e4.seq (sha256 pinned in sw/chat_seq.py
      TEMPLATE4_BY_MODEL["9b"]): it validates at caps=∅ (default and
      explicit) and at caps={"R1"} with the same count, every FENCE in it
      carries target 0; a copy with ONE FENCE's target set to 0x5 is
      refused by validate_stream at caps=∅ and admitted at caps={"R1"}.

  (k) SR2 fix round 1 (review M5): hwmap.seq_caps_check("R1") -- a bare
      str -- raises ValueError saying caps must be a set of names.
      PREDICTION for fix round 1's RED (n212): (k) FAILS (today's code
      silently builds {"R","1"} and refuses it as "unknown SEQ capability 1,
      R", which does not name the str mistake), the other 38 PASS.

PREDICTION FOR THE RED RUN (written before it): the plan says RED fails on
(a), (f), (g), (h).  Because validate()/validate_stream() have no `caps`
keyword before the implementation, EVERY sub-check that passes `caps=`
raises TypeError at RED and is recorded FAIL — so (b), (c), (d), (e) and
the caps-passing half of (j) also FAIL at RED, while their default-call
sub-checks (today's rule) PASS.  (i) PASSES at RED (nothing is defined
anywhere yet).  GREEN: every case PASS.

Exit: 0 iff every sub-check passes; the last line is "SR2_ISA_TDD: PASS" or
"SR2_ISA_TDD: FAIL (n)".

--r3 (Task R3-1 of the R3 campaign, plan
docs/superpowers/plans/2026-09-29-r3-broadcast.md, Task R3-1; a FLAG, not a
copy — plan review I-5).  WITHOUT the flag the script runs exactly the 39
sub-checks above, unchanged, so SR2's committed logs stay reproducible.  WITH
it, the B17.3 group below runs AFTER them (the 39 are still run and counted):
  (r3a) B17.3's encoding rows are present and parse: MOVX flags[7:4] = 0xF is
        the broadcast; MOVX flags[7:4] 4..14 stay reserved err 0x05; MVGO
        flags[7:4] = 0xF stays err 0x05 (a broadcast is a MOVX only); MOVX
        flags[3:0] stays IND_NONE (err 0x02); MOVX target[11:0] is the start
        word for all four; and the doc's 0x05 / 0x02 equal the RTL's E_CHAN /
        E_IND (rtl/seq_unit.sv's localparam, parsed)
  (r3b) HW.SEQ_CAP_BITS["R3"] == 1 << 2, and B17.0's table row for bit 2
        names r3 and B17.3 — a CHARACTERISATION of hwmap and B17.0 (both
        already say so at the base; this ties them)
  (r3c) HW.seq_caps_word({R1,R2,R3}) == 0xFAB1CA07 and
        HW.seq_caps_set(0xFAB1CA07) == {R1,R2,R3} — a characterisation of hwmap
  (r3d) B17.3's stated SEQ_CAPS word equals (r3c)'s, and B17.3's stated
        admission set equals seq_caps_set of that word
  (r3e) B17.3 states the XPTR rule: a unicast MOVX writes its channel's XPTR
        to 0; a broadcast leaves all four XPTRs unchanged
  (r3f) B17.3 states the rest of the controller's addendum: the running rule
        per destination channel (a broadcast whose word range overlaps ANY
        channel's pending x range is INVALID; no RTL interlock), the same
        bank on all four, fail-closed forward compatibility citing the
        refusal at a65f87c:rtl/seq_unit.sv:798-800, the R3 RTL stated as R3-8's,
        and the AS BUILT status line (all three amended in place by R3-10)

PREDICTION FOR THE --r3 RED RUN (n2300, written before it, on the tree where
docs/SEQ_ISA.md's B17.3 is still the four-line reserved stub): the 39 SR2
sub-checks PASS; (r3a) FAILS on its five encoding rows (its "B17.3 section
exists" sub-check PASSES on the stub heading, and its E_CHAN / E_IND
RTL-parse sub-check PASSES); (r3b) and (r3c) PASS (characterisations); (r3d) and (r3e)
FAIL; (r3f) FAILS on every statement except the kept status line, which
PASSES.  Counts: the group is 18 sub-checks (r3a 7, r3b 1, r3c 2, r3d 2,
r3e 2, r3f 6), so RED prints 45 PASS, 12 FAIL (57), rc 1, cases failing
r3a r3d r3e r3f.  GREEN (n2301): 57 PASS, 0 FAIL.  Without the flag (n2302):
39 PASS, 0 FAIL — SR2's count.
"""
import hashlib
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "ref"))
sys.path.insert(0, os.path.join(ROOT, "sw"))

import hwmap as HW                                          # noqa: E402
import seq_format as SF                                     # noqa: E402

R1 = frozenset({"R1"})
NONE = frozenset()
_results = []


def check(case, name, fn):
    try:
        ok, detail = fn()
    except Exception as e:                                  # noqa: BLE001
        ok, detail = False, f"raised {type(e).__name__}: {e}"
    _results.append((case, ok))
    print(f"  ({case}) {'PASS' if ok else 'FAIL'}  {name}"
          + (f"  -- {detail}" if detail else ""))


def admits(r, **kw):
    SF.validate(r, **kw)
    return True, "admitted"


def refuses(r, **kw):
    try:
        SF.validate(r, **kw)
    except SF.SeqValidationError as e:
        return True, f"refused: {str(e).split('  [')[0]}"
    return False, "ADMITTED (must refuse)"


def raises_named(fn, token):
    try:
        fn()
    except SF.SeqValidationError:
        raise
    except ValueError as e:
        return (token in str(e)), f"ValueError: {e}"
    return False, "did not raise"


def fence(**kw):
    return SF.Rec(SF.OP_FENCE, **kw)


R3_WORD = 0xFAB1CA07          # the controller addendum's word, {R1,R2,R3}


def _b17_3():
    """docs/SEQ_ISA.md's B17.3 section: (raw text, whitespace-collapsed)."""
    txt = open(os.path.join(ROOT, "docs", "SEQ_ISA.md")).read()
    m = re.search(r"^### B17\.3 .*?(?=^#{1,3} |\Z)", txt, re.M | re.S)
    if not m:
        return None, None
    return m.group(0), " ".join(m.group(0).split())


def _rtl_err(name):
    src = open(os.path.join(ROOT, "rtl", "seq_unit.sv")).read()
    m = re.search(rf"\b{name}\s*=\s*8'h([0-9A-Fa-f]+)", src)
    return int(m.group(1), 16) if m else None


def r3_cases():
    """Task R3-1: B17.3 (the MOVX broadcast) tied to hwmap and the RTL's
    error codes.  Run only with --r3."""
    print("R3-1 group (--r3) — B17.3 MOVX broadcast, SEQ_CAPS r3")
    sec, norm = _b17_3()

    def has_sec():
        return sec is not None, "" if sec else "no B17.3 in docs/SEQ_ISA.md"

    def row(pat, want_err=None):
        def f():
            if sec is None:
                return False, "no B17.3"
            m = re.search(pat, sec, re.M)
            if not m:
                return False, "row not found"
            if want_err is None:
                return True, m.group(0).strip()
            got = int(m.group(1), 16)
            return got == want_err, f"doc err {got:#04x} vs RTL {want_err}"
        return f

    def stated(pat, flags=re.I):
        def f():
            if norm is None:
                return False, "no B17.3"
            return (re.search(pat, norm, flags) is not None,
                    "" if re.search(pat, norm, flags) else "not stated")
        return f

    e_chan, e_ind = _rtl_err("E_CHAN"), _rtl_err("E_IND")
    check("r3a", "docs/SEQ_ISA.md has a B17.3 section", has_sec)
    check("r3a", "RTL E_CHAN == 0x05 and E_IND == 0x02 (rtl/seq_unit.sv "
          "localparam, parsed)",
          lambda: (e_chan == 0x05 and e_ind == 0x02,
                   f"E_CHAN {e_chan} E_IND {e_ind}"))
    check("r3a", "row: MOVX flags[7:4] = 0xF is the BROADCAST to channels "
          "0..3", row(r"^\s+MOVX flags\[7:4\]\s+record\s+0xF\s+"
                      r"BROADCAST to channels 0\.\.3"))
    check("r3a", "row: MOVX flags[7:4] 4..14 reserved, err == RTL E_CHAN",
          row(r"^\s+MOVX flags\[7:4\]\s+record\s+4\.\.14\s+reserved, "
              r"err 0x([0-9A-Fa-f]{2})", e_chan))
    check("r3a", "row: MVGO flags[7:4] = 0xF err == RTL E_CHAN, MOVX only",
          row(r"^\s+MVGO flags\[7:4\]\s+record\s+0xF\s+err "
              r"0x([0-9A-Fa-f]{2}): a broadcast is a MOVX only", e_chan))
    check("r3a", "row: MOVX flags[3:0] IND_NONE, indirection err == RTL "
          "E_IND", row(r"^\s+MOVX flags\[3:0\]\s+record\s+IND_NONE\s+"
                       r"indirection refused, err 0x([0-9A-Fa-f]{2})", e_ind))
    check("r3a", "row: MOVX target[11:0] = the XWIN start word for ALL FOUR "
          "channels", row(r"^\s+MOVX target\[11:0\]\s+record\s+start word\s+"
                          r"the XWIN start word for ALL FOUR channels"))

    # (r3b) characterisation: hwmap's bit and B17.0's row agree
    def b_bit():
        txt = open(os.path.join(ROOT, "docs", "SEQ_ISA.md")).read()
        m = re.search(r"^\s+bit 2\s+r3\s+R3 built: MOVX broadcast \(B17\.3\)",
                      txt, re.M)
        return (HW.SEQ_CAP_BITS.get("R3") == 1 << 2 and m is not None,
                f"hwmap R3 = {HW.SEQ_CAP_BITS.get('R3')}, B17.0 row "
                f"{'found' if m else 'MISSING'}")
    check("r3b", "HW.SEQ_CAP_BITS['R3'] == 1 << 2 and B17.0's bit-2 row "
          "names r3 / B17.3 (characterisation)", b_bit)

    # (r3c) characterisation of hwmap
    check("r3c", "seq_caps_word({R1,R2,R3}) == 0xFAB1CA07 (characterisation)",
          lambda: (HW.seq_caps_word({"R1", "R2", "R3"}) == R3_WORD,
                   f"{HW.seq_caps_word({'R1', 'R2', 'R3'}):#010x}"))
    check("r3c", "seq_caps_set(0xFAB1CA07) == {R1,R2,R3} (characterisation)",
          lambda: (HW.seq_caps_set(R3_WORD) == frozenset({"R1", "R2", "R3"}),
                   f"{sorted(HW.seq_caps_set(R3_WORD))}"))

    # (r3d) B17.3's stated word == hwmap's; its admission set == the decode
    def d_word():
        if norm is None:
            return False, "no B17.3"
        m = re.search(r"SEQ_CAPS word = 0x([0-9A-Fa-f]{8})", norm)
        if not m:
            return False, "no 'SEQ_CAPS word = 0x........' in B17.3"
        w = int(m.group(1), 16)
        return (w == HW.seq_caps_word({"R1", "R2", "R3"}),
                f"doc {w:#010x} vs hwmap "
                f"{HW.seq_caps_word({'R1', 'R2', 'R3'}):#010x}")
    check("r3d", "B17.3's stated SEQ_CAPS word == seq_caps_word({R1,R2,R3})",
          d_word)

    def d_adm():
        if norm is None:
            return False, "no B17.3"
        m = re.search(r"validated only when \{([^}]*)\} ⊆ caps", norm)
        mw = re.search(r"SEQ_CAPS word = 0x([0-9A-Fa-f]{8})", norm)
        if not m or not mw:
            return False, "admission set or word not stated"
        doc = frozenset(re.findall(r"R\d", m.group(1)))
        dec = HW.seq_caps_set(int(mw.group(1), 16))
        return doc == dec, f"doc {sorted(doc)} vs decode {sorted(dec)}"
    check("r3d", "B17.3's admission set == seq_caps_set(its stated word)",
          d_adm)

    # (r3e) the XPTR rule
    check("r3e", "B17.3: a unicast MOVX writes its channel's XPTR to 0",
          stated(r"a unicast MOVX writes its channel's XPTR to 0"))
    check("r3e", "B17.3: a broadcast leaves all four XPTRs unchanged",
          stated(r"a broadcast leaves all four XPTRs unchanged"))

    # (r3f) the rest of the addendum
    check("r3f", "B17.3: running rule per destination channel",
          stated(r"INVALID if, for ANY channel c, its word range overlaps "
                 r"channel c's pending x range", 0))
    check("r3f", "B17.3: no RTL interlock",
          stated(r"NO RTL INTERLOCK", 0))
    check("r3f", "B17.3: the same bank on all four channels",
          stated(r"the same bank on all four channels"))
    check("r3f", "B17.3: fail-closed, citing a65f87c:rtl/seq_unit.sv:798-800 (R3-10)",
          stated(r"FORWARD COMPATIBILITY — fail-closed\..*"
                 r"`a65f87c:rtl/seq_unit\.sv:798-800`", 0))
    check("r3f", "B17.3: the R3 RTL is R3-8's, rtl/ at 2e87459 == e4d8166 (R3-10)",
          stated(r"rtl/ at the build's launch tree 2e87459 is identical to R3-8's e4d8166"))
    check("r3f", "B17.3: the AS BUILT status line (R3-10; ruled A 2026-09-29)",
          stated(r"AS BUILT \(Task R3-10, 2026-10-01\): BUILT .*ruled A 2026-09-29", 0))


def main(r3=False):
    print("SR2 ISA TDD — B17.0 SEQ_CAPS, B17.1 FENCE mask, hwmap constants, "
          "seq_format caps=")

    # (a)
    check("a", "FENCE target=0x5 admitted at caps={R1}",
          lambda: admits(fence(target=0x5), caps=R1))
    # (b)
    check("b", "FENCE target=0x5 refused at the default caps (today's rule)",
          lambda: refuses(fence(target=0x5)))
    check("b", "FENCE target=0x5 refused at caps=frozenset()",
          lambda: refuses(fence(target=0x5), caps=NONE))
    # (c)(d)(e)
    for case, what, rec in (
            ("c", "FENCE target=0x10", fence(target=0x10)),
            ("d", "HALT target=1", SF.Rec(SF.OP_HALT, target=1)),
            ("e", "FENCE imm32=1", fence(imm32=1))):
        check(case, f"{what} refused at the default caps",
              lambda rec=rec: refuses(rec))
        check(case, f"{what} refused at caps=frozenset()",
              lambda rec=rec: refuses(rec, caps=NONE))
        check(case, f"{what} refused at caps={{R1}}",
              lambda rec=rec: refuses(rec, caps=R1))
    # (e') the other reserved FENCE fields under R1 (B17.1 "every other
    # field zero")
    for what, rec in (("flags=1", fence(flags=1)),
                      ("addr_lo=1", fence(addr_lo=1)),
                      ("len_or_addr_hi=1", fence(len_or_addr_hi=1)),
                      ("target=0x8000", fence(target=0x8000))):
        check("e", f"FENCE {what} refused at caps={{R1}}",
              lambda rec=rec: refuses(rec, caps=R1))
    check("e", "FENCE target=0 (mask 0 = all) admitted at caps={R1}",
          lambda: admits(fence(), caps=R1))
    check("e", "FENCE target=0 admitted at the default caps",
          lambda: admits(fence()))
    # (f)
    check("f", "validate(caps={R9}) raises ValueError naming R9",
          lambda: raises_named(lambda: SF.validate(fence(), caps={"R9"}),
                               "R9"))
    check("f", "validate_stream(caps={R9}) raises ValueError naming R9",
          lambda: raises_named(lambda: SF.validate_stream(
              [fence(), SF.Rec(SF.OP_HALT)], caps={"R9"}), "R9"))

    # (g)
    def g_set():
        got = (HW.seq_caps_set(0xDEADC0DE), HW.seq_caps_set(0xFAB1CA01),
               HW.seq_caps_set(0xFAB1CA03), HW.seq_caps_set(0xFAB1CA00))
        want = (frozenset(), frozenset({"R1"}), frozenset({"R1", "R2"}),
                frozenset())
        ok = got == want and all(isinstance(x, frozenset) for x in got)
        return ok, f"got {[sorted(x) for x in got]}"
    check("g", "seq_caps_set(0xDEADC0DE / 0xFAB1CA01 / 0xFAB1CA03 / "
          "0xFAB1CA00)", g_set)
    check("g", "seq_caps_word({R1}) == 0xFAB1CA01",
          lambda: (HW.seq_caps_word({"R1"}) == 0xFAB1CA01,
                   f"{HW.seq_caps_word({'R1'}):#010x}"))
    check("g", "seq_caps_word(set()) == 0xFAB1CA00 and round-trips "
          "every subset",
          lambda: (HW.seq_caps_word(set()) == 0xFAB1CA00 and all(
              HW.seq_caps_set(HW.seq_caps_word(s)) == frozenset(s)
              for s in ({"R1"}, {"R2"}, {"R3"}, {"R1", "R2"},
                        {"R1", "R2", "R3"})), ""))
    check("g", "HW.S_SEQ_CAPS - HW.SB == 0x64",
          lambda: (HW.S_SEQ_CAPS - HW.SB == 0x64,
                   f"{HW.S_SEQ_CAPS - HW.SB:#x}"))
    check("g", "SEQ_CAPS_MAGIC == 0xFAB1CA and SEQ_CAP_BITS == "
          "{R1:1, R2:2, R3:4}",
          lambda: (HW.SEQ_CAPS_MAGIC == 0xFAB1CA and HW.SEQ_CAP_BITS ==
                   {"R1": 1, "R2": 2, "R3": 4}, ""))
    check("g", "seq_caps_set(0xFAB1CA08) refuses the unknown bit by name",
          lambda: raises_named(lambda: HW.seq_caps_set(0xFAB1CA08), "bit 3"))
    check("g", "seq_caps_word({R9}) refuses by name",
          lambda: raises_named(lambda: HW.seq_caps_word({"R9"}), "R9"))

    # (k) SR2 fix round 1 (review M5): a bare str is not a set of names --
    # frozenset("R1") would silently be {"R", "1"}.  Refused explicitly by
    # hwmap.seq_caps_check, and so by validate()/validate_stream().
    check("k", "seq_caps_check('R1') refuses a bare str (ValueError "
          "naming 'set of names')",
          lambda: raises_named(lambda: HW.seq_caps_check("R1"),
                               "set of names"))

    # (h) doc <-> code
    def h_doc():
        txt = open(os.path.join(ROOT, "docs", "SEQ_ISA.md")).read()
        m = re.search(r"^### B17\.0 .*?(?=^### B17\.1 )", txt, re.M | re.S)
        if not m:
            return False, "no B17.0 section in docs/SEQ_ISA.md"
        sec = m.group(0)
        row = re.search(r"^\s+0x([0-9A-Fa-f]+) SEQ_CAPS\s+R\s+(\{.*\})\s*$",
                        sec, re.M)
        if not row:
            return False, "no '0xNN SEQ_CAPS  R  {...}' row in B17.0"
        off = int(row.group(1), 16)
        lay = row.group(2)
        mg = re.search(r"magic\[31:8\] = 24'h([0-9A-Fa-f]+)", lay)
        bits = {f"R{n}": 1 << int(b)
                for n, b in re.findall(r"r(\d)\[(\d)\]", lay)}
        rows = {f"R{n}": 1 << int(b) for b, n in
                re.findall(r"^\s+bit (\d)\s+r(\d)\s", sec, re.M)}
        mg2 = re.search(r"bits 31:8\s+the magic 0x([0-9A-Fa-f]+)", sec)
        doc = (off, int(mg.group(1), 16) if mg else None, bits, rows,
               int(mg2.group(1), 16) if mg2 else None)
        code = (HW.S_SEQ_CAPS - HW.SB, HW.SEQ_CAPS_MAGIC, HW.SEQ_CAP_BITS,
                HW.SEQ_CAP_BITS, HW.SEQ_CAPS_MAGIC)
        return doc == code, f"doc {doc} vs hwmap {code}"
    check("h", "B17.0's offset, magic and bit positions == hwmap's", h_doc)

    # (i) one definition
    def i_onedef():
        pat = re.compile(r"^(SEQ_CAPS|SEQ_CAP_|seq_caps)")
        names = [n for n in vars(SF) if pat.match(n)]
        src = open(SF.__file__).read()
        defs = re.findall(r"^\s*(?:def\s+(seq_caps\w*)|(SEQ_CAPS?\w*)\s*=)",
                          src, re.M)
        return (not names and not defs), f"namespace {names}, source {defs}"
    check("i", "ref/seq_format defines no SEQ_CAPS* name of its own",
          i_onedef)

    # (j) backward compatibility on the shipped 9B template + stream-level
    # refusal of a masked FENCE
    path = os.path.join(ROOT, "tb", "scripts", "w9", "model_9b_s1.e4.seq")
    sha_pin = ("9760899df53b3b4216d517d042a1dd7c9477b4f0"
               "cb7e6639320a5fd6d480719b")      # sw/chat_seq.py 9b entry
    blob = open(path, "rb").read()
    sha = hashlib.sha256(blob).hexdigest()
    check("j", f"shipped 9B template sha256 == the chat_seq pin "
          f"({sha[:16]}...)", lambda: (sha == sha_pin, sha))
    recs = SF.unpack_stream(blob)
    fences = [i for i, r in enumerate(recs) if r.opcode == SF.OP_FENCE]
    check("j", f"every FENCE in the shipped template carries target 0 "
          f"({len(fences)} FENCEs)",
          lambda: (len(fences) > 0 and all(recs[i].target == 0
                                           for i in fences), ""))
    nrec = len(recs)
    check("j", f"shipped template validates at the default caps "
          f"({nrec} records)",
          lambda: (SF.validate_stream(recs, shape_isa=SF.SHAPE_ISA_9B)
                   == nrec, ""))
    check("j", "shipped template validates at caps=frozenset(), same count",
          lambda: (SF.validate_stream(recs, shape_isa=SF.SHAPE_ISA_9B,
                                      caps=NONE) == nrec, ""))
    check("j", "shipped template validates at caps={R1}, same count",
          lambda: (SF.validate_stream(recs, shape_isa=SF.SHAPE_ISA_9B,
                                      caps=R1) == nrec, ""))
    mut = list(recs)
    k = fences[0]
    mut[k] = SF.Rec(SF.OP_FENCE, target=0x5)

    def j_refuse(**kw):
        try:
            SF.validate_stream(mut, shape_isa=SF.SHAPE_ISA_9B, **kw)
        except SF.SeqValidationError as e:
            return (f"rec {k}:" in str(e)), f"refused: {str(e)[:90]}"
        return False, "ADMITTED (must refuse)"
    check("j", f"template with FENCE rec {k} target=0x5 REFUSED at the "
          f"default caps", lambda: j_refuse())
    check("j", f"template with FENCE rec {k} target=0x5 REFUSED at "
          f"caps=frozenset()", lambda: j_refuse(caps=NONE))
    check("j", f"template with FENCE rec {k} target=0x5 ADMITTED at "
          f"caps={{R1}}",
          lambda: (SF.validate_stream(mut, shape_isa=SF.SHAPE_ISA_9B,
                                      caps=R1) == nrec, ""))
    check("j", "disasm prints 'FENCE mask=0x5' for the masked FENCE and "
          "plain 'FENCE' for mask 0",
          lambda: (SF.disasm(mut[k]).strip() == "FENCE mask=0x5"
                   and SF.disasm(recs[k]).strip() == "FENCE",
                   f"{SF.disasm(mut[k])!r} / {SF.disasm(recs[k])!r}"))

    if r3:
        r3_cases()

    nfail = sum(1 for _c, ok in _results if not ok)
    cases = sorted({c for c, _ in _results})
    bad = sorted({c for c, ok in _results if not ok})
    print(f"sub-checks: {len(_results) - nfail} PASS, {nfail} FAIL; "
          f"cases FAILING: {bad if bad else 'none'} of {cases}")
    print("SR2_ISA_TDD: PASS" if nfail == 0 else f"SR2_ISA_TDD: FAIL ({nfail})")
    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    _ap.add_argument("--r3", action="store_true",
                     help="also run Task R3-1's B17.3 group (default off: "
                          "SR2's committed cases only)")
    sys.exit(main(r3=_ap.parse_args().r3))
