#!/usr/bin/env python3
"""isa_bits.py — G3.1's mechanization of the layer_chan ARG encoding.

Three jobs, and the third is the one that matters (plan Task 7 step 1):

  1. BIT BUDGET.  For every command, the field widths are read OUT OF THE
     RTL (`rtl/layer_chan.sv`) — not transcribed — summed against the 96
     bits ARG0..2 hold, and printed with the spare.  DNST's 101-of-96
     problem and its 69-of-96 solution are both visible here.
  2. ENCODER <-> DECODER EQUIVALENCE over THREE independent implementations
     of the pair layout (spec 7.6): the canonical emitter
     (`ref/gen_layer_script.py`), `sw/chat_seq.py`'s decoder, and the RTL.
     Two further sites (`ref/seq_model.py`, `tb/scripts/gen_seq_layer_script.py`)
     delegate to the canonical helpers and are checked too, because they
     hand-code the DNST scatter.  Every command round-trips at boundary
     addresses and at random ones and all of them must agree.  Reading only
     the encoder and the RTL field list would prove nothing about the
     decoders.
  3. A NEGATIVE CONTROL.  `--negative-control` perturbs one field width at a
     time and requires this script to REFUSE each perturbation.  A checker
     that cannot fail proves nothing.  SR-ISABITS made it strict: the
     unperturbed run must PASS first, and a perturbation of field F counts
     as refused only when a recorded FAIL implicates F; an assert, an
     exception, or a refusal by checks on other fields is a CONTROL FAILURE.

USAGE
    python evidence/qwen9b/g3/isa_bits.py                 # the gate, rc 0 = PASS
    python evidence/qwen9b/g3/isa_bits.py --negative-control
    python evidence/qwen9b/g3/isa_bits.py --perturb a1_lo # one perturbation
    # the control of the control (both must exit rc 1):
    python evidence/qwen9b/g3/isa_bits.py --negative-control --break-control kvhead
    python evidence/qwen9b/g3/isa_bits.py --negative-control --cold-kv

WHY IT KNOWS TWO ISA GENERATIONS.  The plan requires this script to pass on
the PRE-G3 15-bit tree before the layout moves ("which is how you know the
harness itself is right").  So the RTL anchor table is tagged by generation
and the generation is DETECTED from the RTL (the DNSB CSR is v2's tell).
That is not a dual-encoding path in a production tool — the emitter and both
decoders in `ref/`/`sw/` have exactly one encoding at any commit; this
checker simply knows what it is looking at.

Labels (spec 0's evidence contract): every number this script prints is
**M** (measured off the tree) except the 96-bit container, which is **S**
(structural: three 32-bit ARG CSRs).
"""

import argparse
import io
import os
import random
import re
import sys

TOP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RTL = os.path.join(TOP, "rtl", "layer_chan.sv")

for _p in ("ref", "sw"):
    _d = os.path.join(TOP, _p)
    if _d not in sys.path:
        sys.path.insert(0, _d)


# ======================================================================
# 1. the SystemVerilog slice/concat evaluator
# ======================================================================
_SLICE = re.compile(r"^(arg[012]|dn_head|dnsb_dec|dnsb_beta)"
                    r"(?:\[(\d+)(?::(\d+))?\])?$")
_CONST = re.compile(r"^(\d+)'([bdh])([0-9a-fA-F_]+)$")


class Field:
    """One decoded ARG field: an ordered list of (source, hi, lo) parts.

    `source` is 'arg0'/'arg1'/'arg2' for ARG bits, '' for a literal, or a
    plain signal name (v2's DNSB halves).  MSB-first, exactly as the
    SystemVerilog concatenation reads.
    """

    def __init__(self, name, expr, parts):
        self.name = name
        self.expr = expr
        self.parts = parts

    @property
    def width(self):
        return sum(hi - lo + 1 for (_s, hi, lo) in self.parts)

    def arg_bits(self):
        """{(argword, bit)} this field occupies. Literals contribute none."""
        out = set()
        for (s, hi, lo) in self.parts:
            if s.startswith("arg"):
                out |= {(s, b) for b in range(lo, hi + 1)}
        return out

    def decode(self, a0, a1, a2, env=None):
        env = dict(env or {})
        env.update({"arg0": a0, "arg1": a1, "arg2": a2})
        v = 0
        for (s, hi, lo) in self.parts:
            w = hi - lo + 1
            if s == "":                      # literal, value carried in hi/lo
                raise AssertionError("literal parts are not decodable")
            src = env.get(s)
            if src is None:
                raise AssertionError(f"{self.name}: no value for {s!r}")
            v = (v << w) | ((src >> lo) & ((1 << w) - 1))
        return v

    def __repr__(self):
        return f"{self.name}={self.expr} ({self.width}b)"


def parse_expr(name, expr):
    """SV concat/slice/const -> Field.  Refuses anything it does not model."""
    e = expr.strip()
    if e.startswith("{") and e.endswith("}"):
        items = _split_concat(e[1:-1])
    else:
        items = [e]
    parts = []
    for it in items:
        it = it.strip()
        m = _CONST.match(it)
        if m:
            w = int(m.group(1))
            parts.append(("", w - 1, 0))     # a literal: width only
            continue
        m = _SLICE.match(it)
        if not m:
            raise AssertionError(
                f"{name}: cannot model the SystemVerilog expression {it!r} "
                f"(the RTL moved in a way this parser does not cover — that "
                f"is a finding, not a reason to widen the regex)")
        sig, hi, lo = m.group(1), m.group(2), m.group(3)
        if hi is None:
            parts.append((sig, 15, 0))       # a bare signal: width unknown
        elif lo is None:
            parts.append((sig, int(hi), int(hi)))
        else:
            parts.append((sig, int(hi), int(lo)))
    return Field(name, e, parts)


def _split_concat(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return out


# ======================================================================
# 2. the RTL anchor table
# ======================================================================
# Every entry is (field, marker, pattern).  `marker` is a literal string the
# search starts AFTER (so a pattern that appears twice is disambiguated by
# the block it lives in); "" means search the whole file.  The pattern has
# exactly one capture group: the SystemVerilog expression.
ANCHORS_COMMON = [
    ("a1_lo",       "", r"wire\s*\[[0-9:]+\]\s*a1_src\s*=\s*(.+?);"),
    ("a1_hi",       "", r"wire\s*\[[0-9:]+\]\s*a1_dst\s*=\s*(.+?);"),
    ("a2_lo",       "", r"wire\s*\[[0-9:]+\]\s*a2_src\s*=\s*(.+?);"),
    ("a2_hi",       "", r"wire\s*\[[0-9:]+\]\s*a2_dst\s*=\s*(.+?);"),
    ("kv_expbias",  "", r"wire\s*\[[0-9:]+\]\s*kv_expbias\s*=\s*(.+?);"),
    ("vn_mode",     "", r"\.cfg_mode\((.+?)\)"),
    ("vn_nlog2",    "", r"\.cfg_nlog2\((.+?)\)"),
    ("vn_inf",      "", r"\.cfg_inf\((.+?)\)"),
    ("vn_outf",     "", r"\.cfg_outf\((.+?)\)"),
    ("vn_eps",      "", r"\.cfg_eps\((.+?)\)"),
    ("vn_xrfk",     "", r"xrf\[(arg2\[[0-9:]+\])\]"),
    ("alu_op",      "", r"\.cfg_op\((.+?)\),"),
    ("alu_len",     "", r"\.cfg_len\((.+?)\)"),
    ("alu_p0",      "", r"\.cfg_p0\(signed'\((.+?)\)\)"),
    ("alu_srca",    "", r"\.cfg_srca\((.+?)\),"),
    ("alu_srcb",    "", r"\.cfg_srcb\((.+?)\),"),
    ("alu_dst",     "", r"\.cfg_dst\((.+?)\),"),
    ("vnw_n",       "", r"ld_tgt <= LT_VNW; ld_n <= (.+?);"),
    ("gate_dst",    "", r"dst_r <= (arg0\[[0-9:]+\]);"),
    ("dn_head",     "", r"dn_head <= (.+?);"),
    ("kvhead",      "", r"kvhead_r <= (.+?);"),
    ("conv_nch",    "", r"if \(cvi == (arg0\[[0-9:]+\])\)"),
    # the assignment may carry an explicit width cast onto the (narrower)
    # bank address register — the FIELD is what is captured either way
    ("conv_first",  "", r"cw_ra <= (?:\d+'\()?(arg0\[[0-9:]+\]) \+ cvi"),
    ("convw_first", "", r"cw_wa <= (?:\d+'\()?(arg0\[[0-9:]+\]) \+ wi"),
    ("convw_nch",   "", r"if \(wi \+ 1'b1 == (arg0\[[0-9:]+\])\)"),
    ("convw_sel",   "", r"st <= \((arg0\[[0-9:]+\]) == 2'd2\) \? CZ_W"),
]

# v1 = SEQ_ISA v1.7 (R-b): the DNST scalar pointers live in ARG0 with their
# top bit scattered into ARG1[30]/[31].
ANCHORS_V1 = [
    ("dnst_a_dec",  "OP_DNST: begin",  r"ld_src <= (.+?);"),
    ("dnst_a_beta", "LT_DDEC: begin",  r"ld_src <= (.+?);"),
]
# v2 = SEQ_ISA v2.0 (G3.1): the two scalar pointers come from the DNSB CSR
# as base+head, so they are NOT ARG fields at all.  What IS checked is that
# the RTL forms them from the CSR halves.
ANCHORS_V2 = [
    ("dnsb_dec_base",  "", r"dnsb_dec\s*<=\s*wdata_q\[(\d+:\d+)\]"),
    ("dnsb_beta_base", "", r"dnsb_beta\s*<=\s*wdata_q\[(\d+:\d+)\]"),
]


def rtl_generation(src):
    """v1 (R-b bit-scatter) or v2 (clean pairs + DNSB), read off the RTL."""
    has_dnsb = re.search(r"\bdnsb_dec\b", src) is not None
    has_scatter = re.search(r"ld_src <= \{arg1\[3[01]\], arg0\[", src) is not None
    if has_dnsb and not has_scatter:
        return 2
    if has_scatter and not has_dnsb:
        return 1
    raise AssertionError(
        "rtl/layer_chan.sv is neither cleanly v1.7 nor cleanly v2.0 "
        f"(dnsb={has_dnsb}, arg-scatter={has_scatter}) — a half-landed "
        "re-encoding is exactly what this script exists to refuse")


def grab(src, marker, pattern, name):
    start = 0
    if marker:
        i = src.find(marker)
        if i < 0:
            raise AssertionError(f"{name}: marker {marker!r} not in {RTL}")
        start = i + len(marker)
    m = re.search(pattern, src[start:])
    if not m:
        raise AssertionError(f"{name}: pattern {pattern!r} not found in {RTL}"
                             + (f" after {marker!r}" if marker else ""))
    return m.group(1)


def load_rtl_fields(perturb=None):
    with open(RTL) as f:
        src = f.read()
    gen = rtl_generation(src)
    fields = {}
    for (name, marker, pat) in ANCHORS_COMMON + (ANCHORS_V1 if gen == 1
                                                 else ANCHORS_V2):
        expr = grab(src, marker, pat, name)
        if gen == 2 and name.startswith("dnsb_"):
            hi, lo = (int(x) for x in expr.split(":"))
            fields[name] = Field(name, f"wdata_q[{expr}]", [("", hi, lo)])
            continue
        fields[name] = parse_expr(name, expr)
    if perturb:
        _apply_perturbation(fields, perturb)
    return gen, fields


# The perturbations the negative control runs.  Each one is a single-field
# width change of the kind a careless edit makes; every one MUST be refused.
PERTURBATIONS = {
    "a1_lo":        "narrow ARG1's low address half by one bit",
    "a1_hi":        "narrow ARG1's high address half by one bit",
    "a2_lo":        "narrow ARG2's low address half by one bit",
    "a2_hi":        "narrow ARG2's high address half by one bit",
    "alu_dst":      "narrow the ALU ARG2 dst field by one bit",
    "alu_len":      "narrow the ALU length field by one bit",
    "alu_p0":       "narrow the ALU p0 field by one bit",
    "dn_head":      "narrow the DNST/DNZ head field by one bit",
    "gate_dst":     "narrow the GATE ARG0 dst field by one bit",
    "vnw_n":        "narrow the VNW count field by one bit",
    "conv_nch":     "narrow the CONV channel-count field by one bit",
    "conv_first":   "narrow the CONV first-channel field by one bit",
    "convw_nch":    "narrow the CONVW channel-count field by one bit",
    "convw_first":  "narrow the CONVW first-channel field by one bit",
    "kv_expbias":   "narrow the KVAP expbias field by one bit",
    "vn_nlog2":     "narrow the VN nlog2 field by one bit",
    "kvhead":       "narrow the KVAP/ATTN kvhead field by one bit",
    "a1_lo_wide":   "WIDEN ARG1's low half by one bit (it then overlaps hi)",
    "a2_lo_wide":   "WIDEN ARG2's low half by one bit (it then overlaps hi)",
}
# NOT in the table, deliberately: widening GATE's ARG0 dst into ARG0's spare
# bits is NOT a defect — nothing else claims them and every emitted value
# still decodes — so a control that required it to be refused would be
# demanding a false positive.  Measured: the checker stays silent on it.


# SR-ISABITS: `--break-control NAME` makes perturbation NAME a NO-OP (the
# field is left exactly as the RTL has it), so the negative control can be
# shown to FAIL when one of its perturbations proves nothing.
BROKEN = set()


def _apply_perturbation(fields, which):
    if which not in PERTURBATIONS:
        raise SystemExit(f"unknown perturbation {which!r}; choose from "
                         + ", ".join(sorted(PERTURBATIONS)))
    if which in BROKEN:
        return
    widen = which.endswith("_wide")
    key = which[:-5] if widen else which
    f = fields[key]
    parts = list(f.parts)
    # touch the LAST (least-significant) part, which is the contiguous slice
    s, hi, lo = parts[-1]
    parts[-1] = (s, hi + 1, lo) if widen else (s, hi - 1, lo)
    fields[key] = Field(f.name, f.expr + f"  [PERTURBED:{which}]", parts)


# ======================================================================
# 3. the bit budget
# ======================================================================
ARG_BITS = 96                       # S: three 32-bit ARG CSRs

CMD_FIELDS = {
    "VN":    ["vn_mode", "vn_nlog2", "vn_inf", "vn_outf", "vn_eps",
              "vn_xrfk", "a1_lo", "a1_hi"],
    "VNW":   ["vnw_n", "a1_lo"],
    "ROPET": ["a1_lo"],
    "ROPE":  ["a1_lo", "a1_hi"],
    "CONVW": ["convw_sel", "convw_first", "convw_nch", "a1_lo"],
    "CONV":  ["conv_first", "conv_nch", "a1_lo", "a1_hi"],
    "GATE":  ["gate_dst", "a1_lo", "a1_hi", "a2_lo", "a2_hi"],
    "KVAP":  ["kvhead", "kv_expbias", "a1_lo", "a1_hi"],
    "ATTN":  ["kvhead", "a1_lo", "a1_hi"],
    "ALU":   ["alu_op", "alu_len", "alu_p0", "alu_srca", "alu_srcb",
              "alu_dst"],
    "DNST":  ["dn_head", "a1_lo", "a1_hi", "a2_lo", "a2_hi"],
    "DNZ":   ["dn_head"],
}
CMD_FIELDS_V1_EXTRA = {"DNST": ["dnst_a_dec", "dnst_a_beta"]}


# SR-ISABITS: every FAIL is also RECORDED with the RTL fields it implicates,
# so the negative control can require that a perturbation of field F is
# refused BY A CHECK ON F -- not by whatever else happens to fail (before
# SR-ISABITS it counted any False, and the unperturbed run's own COLD-slot
# assert "refused" every perturbation).  A FAIL that decodes no RTL field
# (a chat_seq decode, a constant tie) is recorded with an empty tuple; an
# assert/exception that aborts a section is recorded as ASSERT.
ASSERT = "<assert>"
_FAILS = []


def _note(fields, msg):
    _FAILS.append((tuple(fields), msg))


def bit_budget(gen, fields, out):
    """Per command: the union of ARG bits its fields occupy, and the spare.

    Also refuses any command whose fields OVERLAP inside one ARG word — the
    failure mode the R-b bit-scatter made easy and the pair layout removes.
    """
    ok = True
    out.write(f"{'command':7s} {'ARG0':>5s} {'ARG1':>5s} {'ARG2':>5s} "
              f"{'used':>5s} {'spare':>6s}  fields\n")
    for cmd, names in CMD_FIELDS.items():
        names = list(names) + (CMD_FIELDS_V1_EXTRA.get(cmd, []) if gen == 1
                               else [])
        per = {"arg0": set(), "arg1": set(), "arg2": set()}
        seen = {}
        for n in names:
            f = fields[n]
            for (w, b) in f.arg_bits():
                if (w, b) in seen and seen[(w, b)] != n:
                    out.write(f"  FAIL {cmd}: {n} and {seen[(w, b)]} both "
                              f"claim {w}[{b}]\n")
                    _note((n, seen[(w, b)]), f"bit budget {cmd}: {n} and "
                          f"{seen[(w, b)]} both claim {w}[{b}]")
                    ok = False
                seen[(w, b)] = n
                per[w].add(b)
        used = sum(len(v) for v in per.values())
        spare = ARG_BITS - used
        flag = "" if spare >= 0 else "   <-- OVER"
        if spare < 0:
            _note(names, f"bit budget {cmd}: {used} of {ARG_BITS} bits")
            ok = False
        out.write(f"{cmd:7s} {len(per['arg0']):5d} {len(per['arg1']):5d} "
                  f"{len(per['arg2']):5d} {used:5d} {spare:6d}  "
                  + ", ".join(f"{n}:{fields[n].width}" for n in names)
                  + flag + "\n")
        for w in ("arg0", "arg1", "arg2"):
            top = max(per[w]) if per[w] else -1
            if top >= 32:
                out.write(f"  FAIL {cmd}: {w} bit {top} is outside a 32-bit "
                          f"CSR\n")
                _note([n for n in names
                       if any(x[0] == w and x[1] >= 32
                              for x in fields[n].arg_bits())],
                      f"bit budget {cmd}: {w} bit {top} outside 32 bits")
                ok = False
    return ok


# ======================================================================
# 4. the three-way equivalence
# ======================================================================
class _Captured(Exception):
    pass


def _capture(M, fn, *a, **kw):
    """Run one canonical emitter and return its (op, arg0, arg1, arg2)."""
    try:
        fn(*a, **kw)
    except _Captured as e:
        return e.args[0]
    raise AssertionError(f"{fn.__name__} did not emit a C record")


# SR-ISABITS: the control of the control.  `--cold-kv` skips the warm path
# below and so reproduces the pre-repair failure (every perturbed run dies on
# the COLD assert); the strict negative control must then name each one a
# CONTROL FAILURE rather than a refusal.
COLD_KV = False


def make_mach(GLS):
    """A Mach whose C records are CAPTURED, with its cache slots WARMED.

    SR-ISABITS.  Since 75598a9 (the state spill, spec 3/6.5) every compute
    command on a cache slot asserts the slot is WARM -- the emitter's twin of
    the RTL's E_DMA_COLD (`Mach._require_warm`) -- and ATTN/KVAP also assert
    the KV slot's TAG names their kvhead (`Mach._require_tag`, E_DMA_RANGE).
    The synthetic commands below used to run on a fresh Mach, whose slots
    are all COLD, so section 3 died at its first ATTN.  The repair warms the
    slots THE WAY THE EMITTER DOES, not by writing `M.warm`: the session
    preamble `sched_preamble` (LAYER, SBASE, Treset, SLD DN 0, SLD CV 0 and,
    because the synthetic stack starts with a full-attention layer, both
    halves of attention layer 0's kvhead 0 into KV slot 0).  Those SLD
    records go to the discarded buffer through the REAL `Mach.C`; only after
    the preamble is `C` replaced by the capture hook.  The COLD rule itself
    is untouched and still armed: `_select_kvhead` moves between kvheads
    with the emitter's own SST/SLD pairs (`sched_attn_layer`'s step).
    """
    buf = io.StringIO()
    M = GLS.Mach(buf)
    if not COLD_KV:
        GLS.sched_preamble(M, ["full_attention"])

    def cap(op, a0, a1, a2):
        assert 0 <= a0 < (1 << 32) and 0 <= a1 < (1 << 32) \
            and 0 <= a2 < (1 << 32), \
            f"emitted ARG outside 32 bits: {a0:#x} {a1:#x} {a2:#x}"
        raise _Captured((op, a0, a1, a2))

    M.C = cap
    M._isa_cap = cap
    M._isa_kvswaps = 0                        # SST pairs by _select_kvhead
    return M


def _select_kvhead(GLS, M, kvh, A=0):
    """Make kvhead `kvh` of attention layer `A` the CURRENT, WARM KV slot.

    One step of `sched_attn_layer` (spec 6.2): kvhead k lives in slot k % 2;
    if that slot does not already hold (A, k), store back whatever it holds
    (both halves, as the schedule does) and load k's two halves, then point
    LAYER at the slot.  The SLD/SST records run through the REAL `Mach.C`
    (the capture hook is lifted for the duration), so the slot's warm bit
    and tag are set by `Mach.sld` itself.  Under `--cold-kv` nothing is
    loaded and ATTN/KVAP meet a COLD slot, as before the repair."""
    if COLD_KV:
        return
    slot = kvh % 2
    del M.C                                   # the class's real emitter
    try:
        if not (M.warm[GLS.K_KV][slot] and M.tag[slot] == (A, kvh)):
            if M.warm[GLS.K_KV][slot]:
                la, old = M.tag[slot]
                M._isa_kvswaps += 1           # the store branch ran
                M.sst(GLS.K_KV, slot, la, old << 1)
                M.sst(GLS.K_KV, slot, la, (old << 1) | 1)
            M.sld(GLS.K_KV, slot, A, kvh << 1)
            M.sld(GLS.K_KV, slot, A, (kvh << 1) | 1)
        M.layer(0, slot, 0, A)
    finally:
        M.C = M._isa_cap


def rtl_pair(fields, which, a0, a1, a2, env=None):
    return fields[which].decode(a0, a1, a2, env)


def start_addrs(windows):
    return [a for (a, _n) in windows]


def field_ceilings(gen, fields, GLS, SF, out):
    """Every emitter CEILING against the RTL SLICE that has to carry it.

    A field the RTL decodes at 14 bits but the emitter refuses at 13 is a
    self-contradictory ISA, and neither the bit budget nor the round-trip
    sees it on its own: the budget only reads the RTL, and the round-trip
    can only exercise values the emitter agrees to emit.  This is the check
    that couples the two.  A field WIDER than its ceiling is fine (GATE's
    ARG0 has spare); a field NARROWER than it is the defect.
    """
    ok = True
    M = GLS.Mach
    A = GLS.ISA_SADDR_MAX - 1
    # VNW under v1.7 emitted its top count (2048) as a literal that
    # TRUNCATED to 0 on purpose — 0 encoded 2048 — so the largest FIELD
    # VALUE it had to carry was 2047.  v2.0 deleted the escape and the field
    # carries the count directly.
    vnw_cap = M.VNW_ISA_MAX if gen == 2 else M.VNW_ISA_MAX - 1
    rows = [
        ("a1_lo", "ISA_SADDR_MAX-1", A), ("a1_hi", "ISA_SADDR_MAX-1", A),
        ("a2_lo", "ISA_SADDR_MAX-1", A), ("a2_hi", "ISA_SADDR_MAX-1", A),
        ("gate_dst", "ISA_SADDR_MAX-1", A),
        ("alu_srca", "ISA_SADDR_MAX-1", A),
        ("alu_srcb", "ISA_SADDR_MAX-1", A),
        ("alu_dst", "ISA_SADDR_MAX-1", A),
        ("vnw_n", "VNW_ISA_MAX", vnw_cap),
        ("conv_first", "CONV_FIELD_MAX", M.CONV_FIELD_MAX),
        ("conv_nch", "CONV_FIELD_MAX", M.CONV_FIELD_MAX),
        ("convw_first", "CONV_FIELD_MAX", M.CONV_FIELD_MAX),
        ("convw_nch", "CONV_FIELD_MAX", M.CONV_FIELD_MAX),
        ("alu_len", "ALU_LEN_MAX", M.ALU_LEN_MAX),
        ("dn_head", "2**ARG0_HEAD_BITS-1", (1 << M.ARG0_HEAD_BITS) - 1),
        ("kvhead", "2**ARG0_KVH_BITS-1", (1 << M.ARG0_KVH_BITS) - 1),
        ("kv_expbias", "KVAP_EXPB_MAX", M.KVAP_EXPB_MAX),
    ]
    for (fname, cname, cap) in rows:
        w = fields[fname].width
        if cap > (1 << w) - 1:
            out.write(f"  FAIL {fname}: the RTL slice is {w} b (max "
                      f"{(1 << w) - 1}) but the emitter's {cname} is {cap}\n")
            _note((fname,), f"ceiling {fname}: {w} b < {cname} = {cap}")
            ok = False
        else:
            out.write(f"  {fname:12s} {w:2d} b  >= {cname} = {cap}\n")
    # the ALU length ceiling has a TWIN in ref/seq_format.py, which
    # synthesizes ALU commands the Mach emitter never sees.  Two copies of a
    # constant is a constant that will disagree.
    if SF.SeqEmitter.ALU_LEN_MAX != M.ALU_LEN_MAX:
        out.write(f"  FAIL seq_format.SeqEmitter.ALU_LEN_MAX = "
                  f"{SF.SeqEmitter.ALU_LEN_MAX} but Mach.ALU_LEN_MAX = "
                  f"{M.ALU_LEN_MAX}\n")
        _note((), "ALU_LEN_MAX twins disagree")
        ok = False
    else:
        out.write(f"  ALU_LEN_MAX twins agree: "
                  f"{SF.SeqEmitter.ALU_LEN_MAX}\n")
    return ok


def equivalence(gen, fields, GLS, CS, SM, GSL, out, seed=20260901):
    """Round-trip every command through emitter, RTL slices and both decoders.

    THREE independent implementations (spec 7.6): the canonical emitter, the
    RTL, and `sw/chat_seq.py`.  Two delegating sites are checked as well —
    `ref/seq_model.py`'s executor and `tb/scripts/gen_seq_layer_script.py`'s
    DNST packer — because they hand-code the parts the helpers do not cover.
    """
    ok = True
    rng = random.Random(seed)
    MAXA = GLS.ISA_SADDR_MAX
    bounds = [0, 1, MAXA // 2 - 1, MAXA // 2, MAXA - 1]
    addrs = bounds + [rng.randrange(MAXA) for _ in range(24)]
    g = CS.GEOM
    LNH, LDK, LDV, HD = g["LNH"], g["LDK"], g["LDV"], g["HD"]
    M = make_mach(GLS)
    nchk = 0

    def fail(msg, flds=()):
        nonlocal ok
        out.write("  FAIL " + msg + "\n")
        _note(flds, msg)
        ok = False

    def chk(label, want, a0, a1, a2, env=None):
        """Decode each RTL field in `want` from the emitted words; FAIL
        naming exactly the fields that do not round-trip."""
        got = {k: rtl_pair(fields, k, a0, a1, a2, env) for k in want}
        bad = [k for k in want if got[k] != want[k]]
        if bad:
            fail(f"{label}: RTL decoded {got} want {want}", bad)

    def pick(i, k):
        return addrs[(i * 7 + k * 13) % len(addrs)]

    out.write(f"boundary addresses: {bounds}  (ISA_SADDR_MAX={MAXA})\n")
    out.write(f"random addresses:   {len(addrs) - len(bounds)} @ seed {seed}\n")

    for i, base in enumerate(addrs):
        src, dst = base, pick(i, 1)
        s2, d2 = pick(i, 2), pick(i, 3)

        # VN's small ARG0 fields, driven to the TOP of each slice
        nlog2 = [15, 0, 4, i % 16][i % 4]
        vinf = [15, 0, 5, (i * 3) % 16][i % 4]
        voutf = [15, 0, 6, (i * 5) % 16][i % 4]
        vmode = i % 3

        # ---- the PAIR, through every command that carries one ----------
        for name, emit, dec in (
            ("VN", lambda: M.vn(vmode, 1 << nlog2, vinf, voutf, src, dst),
             None),
            ("ROPE",  lambda: M.rope(src, dst), None),
            ("ATTN",  lambda: M.attn(0, src, dst), None),   # kvh: see KVAP
        ):
            if name == "ATTN":
                _select_kvhead(GLS, M, 0)     # SR-ISABITS: a WARM slot
            _op, a0, a1, a2 = _capture(M, emit)
            if name == "VN":
                chk("VN arg0 fields",
                    {"vn_mode": vmode, "vn_nlog2": nlog2, "vn_inf": vinf,
                     "vn_outf": voutf}, a0, a1, a2)
            nchk += 1
            chk(f"{name} pair", {"a1_lo": src, "a1_hi": dst}, a0, a1, a2)
            lop = {"VN": 1, "ROPE": 4, "ATTN": 10}[name]
            R, W = CS._cmd_scratch(lop, a0, a1, a2, g=g)
            if start_addrs(R) != [src] or start_addrs(W) != [dst]:
                fail(f"{name} chat_seq @({src},{dst}) -> {R} {W}")

        # ---- VNW / ROPET: lo only --------------------------------------
        # cycle the count through the TOP of its field.
        # The FIELD carries 4096 (13 bits) and, since G3.2, SO DOES THE
        # DATAPATH: the vecnorm wbuf is 4096 deep, vn_waddr is 12 bits, and
        # VNW_HW_MAX is 4096, so the largest count this round-trip can EMIT
        # is the full field.  ARG0[12] IS exercised end to end now -- G3.2
        # measured it.
        # SR-ISABITS fix round 1: this ROUND TRIP CANNOT SEE A FIELD NARROWED
        # TO 12 BITS.  4096 in a 12-bit field encodes as 0, and 0 decodes as
        # the full field (1 << 12) = 4096 again; every other count cycled
        # here fits 12 bits.  The ONLY guard against a narrowed vnw_n is the
        # section-2 ceiling row ("vnw_n", "VNW_ISA_MAX", ...) in
        # field_ceilings -- the negative control's vnw_n row is refused by
        # that row alone (evidence/qwen9b/sr/n1911).  Do not relax it.
        # (These six lines described the pre-G3.2 state until 2026-09-10;
        # the BEHAVIOUR was already right, because the bound is read through
        # getattr rather than hard-coded.)
        vnw_top = min(GLS.Mach.VNW_ISA_MAX,
                      getattr(GLS.Mach, "VNW_HW_MAX", GLS.Mach.VNW_ISA_MAX))
        vnw_n = [vnw_top, vnw_top - 1, 1, 1 + (i * 97) % vnw_top][i % 4]
        for name, lop, emit in (
            ("VNW",   2, lambda: M.vnw_(src, vnw_n)),
            ("ROPET", 3, lambda: M.ropet(src)),
        ):
            _op, a0, a1, a2 = _capture(M, emit)
            nchk += 1
            chk(f"{name} src", {"a1_lo": src}, a0, a1, a2)
            R, W = CS._cmd_scratch(lop, a0, a1, a2, g=g)
            if start_addrs(R) != [src] or W:
                fail(f"{name} chat_seq @{src} -> {R} {W}")
            if name == "VNW":
                w = fields["vnw_n"].width
                raw = rtl_pair(fields, "vnw_n", a0, a1, a2)
                # 0 ENCODES the full field (SEQ_ISA B7): decode it that way.
                # Consequence: this compare is blind to a 12-bit narrowing
                # (see above); field_ceilings' vnw_n row is the guard.
                if (raw or (1 << w)) != vnw_n:
                    fail(f"VNW RTL count @{vnw_n} -> field {raw} in {w} b "
                         f"= {raw or (1 << w)}", ("vnw_n",))

        # ---- CONV / CONVW: the channel fields share ARG0 with nothing ---
        # the TOP of each field is exercised on purpose (i % 3 == 0)
        cmax = GLS.Mach.CONV_FIELD_MAX
        nch = cmax if i % 3 == 0 else 1 + (i * 613) % cmax
        first = cmax if i % 3 == 1 else (i * 37) % (cmax + 1)
        _op, a0, a1, a2 = _capture(M, lambda: M.conv(first, nch, src, dst))
        nchk += 1
        chk("CONV fields", {"conv_first": first, "conv_nch": nch},
            a0, a1, a2)
        chk("CONV pair", {"a1_lo": src, "a1_hi": dst}, a0, a1, a2)
        R, W = CS._cmd_scratch(6, a0, a1, a2, g=g)
        if R != [(src, nch)] or W != [(dst, nch)]:
            fail(f"CONV chat_seq @({src},{dst},{nch}) -> {R} {W}")

        _op, a0, a1, a2 = _capture(M, lambda: M.convw(first, nch, src))
        nchk += 1
        chk("CONVW fields", {"convw_first": first, "convw_nch": nch,
                             "convw_sel": 0}, a0, a1, a2)
        chk("CONVW src", {"a1_lo": src}, a0, a1, a2)
        R, W = CS._cmd_scratch(5, a0, a1, a2, g=g)
        if R != [(src, 4 * nch)] or W:
            fail(f"CONVW chat_seq @({src},{nch}) -> {R} {W}")

        # ---- GATE: five addresses, ARG0 + two pairs ---------------------
        gd = pick(i, 4)
        _op, a0, a1, a2 = _capture(M, lambda: M.gate(src, dst, s2, d2, gd))
        nchk += 1
        chk("GATE dst", {"gate_dst": gd}, a0, a1, a2)
        chk("GATE pairs", {"a1_lo": src, "a1_hi": dst, "a2_lo": s2,
                           "a2_hi": d2}, a0, a1, a2)
        R, W = CS._cmd_scratch(7, a0, a1, a2, g=g)
        if R != [(src, LNH), (dst, LNH), (s2, 2 * LNH), (d2, LNH)] \
                or W != [(gd, 2 * LNH)]:
            fail(f"GATE chat_seq -> {R} {W}")

        # ---- KVAP -------------------------------------------------------
        expb = [GLS.Mach.KVAP_EXPB_MAX, 0, 5, GLS.Mach.KVAP_EXPB_MAX - 1][i % 4]
        # G3.4 LANDED THE 4-HEAD KV BANKING, so KVH_HW_MAX is 3 and this
        # min() now returns 3: ARG0[1] IS exercised end to end, which it was
        # not at G3.1 (the note that used to stand here said so).  The min()
        # is kept rather than replaced by KVH_MAX because it is what makes
        # the check honest at any FUTURE geometry where the three bounds
        # separate again.
        kvh_top = min(GLS.Mach.KVH_MAX,
                      (1 << GLS.Mach.ARG0_KVH_BITS) - 1,
                      getattr(GLS.Mach, "KVH_HW_MAX", 0))
        kvh = [kvh_top, 0, kvh_top, 0][i % 4]
        _select_kvhead(GLS, M, kvh)           # SR-ISABITS: warm + tagged
        _op, a0, a1, a2 = _capture(M, lambda: M.kvap(kvh, src, dst, expb))
        nchk += 1
        chk("KVAP arg0 fields", {"kv_expbias": expb, "kvhead": kvh},
            a0, a1, a2)
        R, W = CS._cmd_scratch(9, a0, a1, a2, g=g)
        if R != [(src, HD), (dst, HD)] or W:
            fail(f"KVAP chat_seq -> {R} {W}")
        # SR-ISABITS fix round 1: kvheads 3 and 0 live in DIFFERENT slots,
        # so alternating them never evicts anything and _select_kvhead's
        # SST "store old" branch would never run.  Moving kvhead 1 into
        # slot 1 (evicting 3) here, and 3 back at the next KVAP, exercises
        # it.  Emits no captured command: the encoding count is unchanged.
        if i % 4 == 1:
            _select_kvhead(GLS, M, 1)

        # ---- ALU: the relocated p0 bit and the moved dst -----------------
        n = [GLS.Mach.ALU_LEN_MAX, GLS.Mach.ALU_LEN_MAX - 1, 1,
             1 + (i * 991) % GLS.Mach.ALU_LEN_MAX][i % 4]
        p0 = [(1 << 17) - 1, 1 << 16, 0, (i * 9973) % (1 << 17)][i % 4]
        _op, a0, a1, a2 = _capture(M, lambda: M.alu(3, n, p0, src, dst, gd))
        nchk += 1
        chk("ALU op/len", {"alu_op": 3, "alu_len": n}, a0, a1, a2)
        chk("ALU addresses", {"alu_srca": src, "alu_srcb": dst,
                              "alu_dst": gd}, a0, a1, a2)
        chk("ALU p0", {"alu_p0": p0}, a0, a1, a2)
        R, W = CS._cmd_scratch(11, a0, a1, a2, g=g)
        if R != [(src, n), (dst, n)] or W != [(gd, n)]:
            fail(f"ALU chat_seq -> {R} {W}")
        # ALU's own pair must be the SAME slices the shared pair wires use
        if fields["alu_srca"].arg_bits() != fields["a1_lo"].arg_bits() or \
                fields["alu_srcb"].arg_bits() != fields["a1_hi"].arg_bits():
            fail("vec_alu's cfg_srca/cfg_srcb do not use the a1_src/a1_dst "
                 "slices — two pair layouts in one file",
                 [x for (k, j) in (("alu_srca", "a1_lo"),
                                   ("alu_srcb", "a1_hi"))
                  if fields[k].arg_bits() != fields[j].arg_bits()
                  for x in (k, j)])

        # ---- DNST: head, two pairs, and the two scalar pointers ---------
        hmax = min(GLS.Mach.DNST_HEAD_MAX, (1 << GLS.Mach.ARG0_HEAD_BITS) - 1)
        head = [hmax, 0, hmax - 1, i % (hmax + 1)][i % 4]
        a_dec = GLS.decay_base + head
        a_beta = GLS.beta_base + head
        if gen == 2:
            M.dnsb(GLS.beta_base, GLS.decay_base)
        _op, a0, a1, a2 = _capture(
            M, lambda: M.dnst(head, src, dst, s2, a_dec, a_beta, d2))
        nchk += 1
        chk("DNST head", {"dn_head": head}, a0, a1, a2)
        chk("DNST pairs", {"a1_lo": src, "a1_hi": dst, "a2_lo": s2,
                           "a2_hi": d2}, a0, a1, a2)
        if gen == 1:
            chk("DNST scalar pointers", {"dnst_a_dec": a_dec,
                                         "dnst_a_beta": a_beta}, a0, a1, a2)
        dnsb = None if gen == 1 else \
            ((GLS.decay_base << 16) | GLS.beta_base)
        R, W = (CS._cmd_scratch(8, a0, a1, a2, g=g) if gen == 1
                else CS._cmd_scratch(8, a0, a1, a2, g=g, dnsb=dnsb))
        want_R = [(src, LDK), (dst, LDK), (s2, LDV), (a_dec, 1), (a_beta, 1)]
        if R != want_R or W != [(d2, 2 * LDV)]:
            fail(f"DNST chat_seq -> {R} {W} want {want_R} [({d2},{2 * LDV})]")

        # ---- DNZ: the SAME head slice DNST uses -------------------------
        _op, z0, z1, z2 = _capture(M, lambda: M.dnz(head))
        nchk += 1
        chk("DNZ head", {"dn_head": head}, z0, z1, z2)
        if (z1, z2) != (0, 0):
            fail(f"DNZ ARG1/ARG2 not zero: {z1:#x} {z2:#x}")

        # ---- the two DELEGATING sites (spec 7.6 B) ----------------------
        # ref/seq_model.py's executor: decode the very words just emitted and
        # require the operands back.
        got = _seq_model_dnst(SM, gen, a0, a1, a2, dnsb)
        if got != (head, src, dst, s2, a_dec, a_beta, d2):
            fail(f"DNST ref/seq_model.py -> {got}")
        # tb/scripts/gen_seq_layer_script.py's DNST packer must produce the
        # SAME words the canonical emitter did.
        got = _tb_dnst(GSL, head, src, dst, s2, a_dec, a_beta, d2)
        if got != (8, a0, a1, a2):
            fail(f"DNST tb packer -> {tuple(hex(x) for x in got)} "
                 f"want {(8, hex(a0), hex(a1), hex(a2))}")

    out.write(f"round-trips: {nchk} command encodings x "
              f"{len(addrs)} address sets\n")
    out.write(f"KV slot evictions (SST pairs by _select_kvhead): "
              f"{M._isa_kvswaps}\n")
    if not COLD_KV and M._isa_kvswaps == 0:
        fail("_select_kvhead's store branch never ran")

    # ---- G3.4 wall-9, the EMITTER half: the SEQ program's T reset ------
    # rtl/layer_chan.sv banks FOUR append counters per kv_slot and the CSR
    # word holds two, so a SEQ program that resets T must write TCNT (0x20)
    # AND TCNT2 (0x60).  Writing only the first leaves kvheads 2/3 holding
    # a stale count while the reference model zeroes all four -- divergence,
    # not an error, which is exactly what spec 4.6 wall 9 is about.  This
    # exercises the hook in place rather than asserting its source.
    import seq_format as _SF

    # SR-ISABITS: since 75598a9 (S3, spec A1.3) `tcnt_bank` is indexed by
    # ATTENTION LAYER, so the reset is, for EVERY attention layer a, a LAYER
    # write selecting kv_layer a followed by TCNT = 0 and TCNT2 = 0, and then
    # the program's LAYER word restored.  The spy carries the two emitter
    # attributes the hook now reads (no open attention block; a LAYER word).
    class _TResetSpy(object):
        attn = None
        layer_word_q = 0x5A5A

        def __init__(self):
            self.recs = []

        def _csrwr(self, csr, val, ind=0, xrf=0):
            self.recs.append((csr, val))

    spy = _TResetSpy()
    _SF.SeqEmitter.on_treset(spy)
    nkvl = GLS._KV_LAYERS
    want = []
    for a in range(nkvl):
        want += [(_SF.CSR_L_LAYER, _SF.layer_word(0, 0, 0, a)),
                 (_SF.CSR_L_TCNT, 0), (_SF.CSR_L_TCNT2, 0)]
    want.append((_SF.CSR_L_LAYER, _TResetSpy.layer_word_q))
    zeroed = sorted({(r[1] >> 8) & 7 for r, n1, n2 in
                     zip(spy.recs, spy.recs[1:], spy.recs[2:])
                     if r[0] == _SF.CSR_L_LAYER
                     and n1 == (_SF.CSR_L_TCNT, 0)
                     and n2 == (_SF.CSR_L_TCNT2, 0)})
    out.write(f"SEQ T reset: {len(spy.recs)} CSRWR = {nkvl} x (LAYER "
              f"kv_layer a, TCNT 0x{_SF.CSR_L_TCNT:x} = 0, TCNT2 "
              f"0x{_SF.CSR_L_TCNT2:x} = 0) + LAYER restored; kv_layers "
              f"zeroed {zeroed}\n")
    if spy.recs != want or zeroed != list(range(nkvl)):
        fail(f"SeqEmitter.on_treset emitted "
             f"{[(hex(c), hex(v)) for c, v in spy.recs]}, want "
             f"{[(hex(c), hex(v)) for c, v in want]} (all {4} kvhead "
             f"counters of all {nkvl} attention layers must be zeroed)")
    if _SF.LOFF_TCNT2 != 0x60:
        fail(f"ref/seq_format LOFF_TCNT2 = {_SF.LOFF_TCNT2:#x}, "
             f"but rtl/layer_chan.sv decodes TCNT2 at 0x60")
    if "L_TCNT2" not in _SF._csr_name(_SF.CSR_L_TCNT2):
        fail("ref/seq_format disasm does not name L_TCNT2")

    # ---- G3.4 S9: the MVGO SHAPE envelope, ALL FOUR COPIES TIED --------
    # `MAX_NG` is stated in four places and the RTL cannot consume another
    # module's parameter without a package (which would mean editing
    # rtl/matvec_engine.sv, closed by G3.3).  So the tie is MECHANIZED
    # here instead of asserted in a comment: all four are READ FROM their
    # own source -- the two RTL copies by regex over the file, the two
    # Python ones by IMPORTING the module and reading the live value, which
    # is the stronger of the two and the reason the wording matters -- and
    # required equal, with the perturbation control below to prove this
    # check can fail.
    #   rtl/matvec_engine.sv   the engine's own MAX_NG -- the authority
    #   rtl/seq_unit.sv        MVGO_MAX_NG, the run-side refusal
    #   sw/hwmap.py            SHAPE_MAX_NG[2], the emit-side refusal
    #   ref/seq_format.py      MVGO_MAX_NG, the reference validator
    import hwmap as _HW
    ng_src = {
        "rtl/matvec_engine.sv": _rtl_int(
            "rtl/matvec_engine.sv", r"parameter int MAX_NG\s*=\s*(\d+)"),
        "rtl/seq_unit.sv": _rtl_int(
            "rtl/seq_unit.sv", r"localparam int MVGO_MAX_NG = (\d+);"),
        "sw/hwmap.py": int(_HW.SHAPE_MAX_NG[_HW.SHAPE_ISA_9B]),
        "ref/seq_format.py": int(_SF.MVGO_MAX_NG),
    }
    rtl_ng = ng_src["rtl/matvec_engine.sv"]
    out.write("MAX_NG tie: " + "  ".join(f"{k}={v}" for k, v in ng_src.items())
              + "\n")
    if len(set(ng_src.values())) != 1:
        fail(f"MAX_NG copies disagree: {ng_src}")
    # the perturbation control: a checker that cannot fail proves nothing
    _pert = dict(ng_src)
    _pert["rtl/seq_unit.sv"] = rtl_ng + 1
    if len(set(_pert.values())) == 1:
        fail("MAX_NG tie: the perturbation control did NOT diverge")
    out.write(f"MAX_NG tie: perturbation control CAUGHT "
              f"(seq_unit {rtl_ng} -> {rtl_ng + 1} diverges)\n")
    if _SF.SHAPE_ISA_9B != _HW.SHAPE_ISA_9B:
        fail(f"SHAPE_ISA_9B: ref/seq_format.py {_SF.SHAPE_ISA_9B} vs "
             f"sw/hwmap.py {_HW.SHAPE_ISA_9B}")

    # ---- G3.4 I2 residual: the TB's EMBLOG2 mirror --------------------
    # tb/tb_layer_chan.sv derives EMB_N_MAX from TB_EMBLOG2_MAX, which is a
    # MIRROR of rtl/seq_unit.sv's EMBLOG2_MAX.  The TB's own elaboration
    # assert cannot see the RTL, so the mirror is tied here.
    tb_e = _rtl_int("tb/tb_layer_chan.sv",
                    r"localparam int TB_EMBLOG2_MAX = (\d+);")
    rtl_e = _rtl_int("rtl/seq_unit.sv",
                     r"EMBLOG2_MIN = 5'd\d+, EMBLOG2_MAX = 5'd(\d+);")
    if tb_e != rtl_e:
        fail(f"TB_EMBLOG2_MAX: tb/tb_layer_chan.sv {tb_e} vs "
             f"rtl/seq_unit.sv EMBLOG2_MAX {rtl_e}")
    out.write(f"EMBLOG2_MAX tie: tb/tb_layer_chan.sv {tb_e} == "
              f"rtl/seq_unit.sv {rtl_e}, so EMB_N_MAX = "
              f"{(1 << tb_e) // 2} is the row the hardware can name\n")
    for bad_ng in (0, rtl_ng + 1):
        r = _SF.Rec(_SF.OP_MVGO, 0, 0, (bad_ng << 22) | (24 << 6), 0, 0)
        try:
            _SF.validate(r, shape_isa=_SF.SHAPE_ISA_9B)
        except _SF.SeqValidationError:
            pass
        else:
            fail(f"ref/seq_format.validate ACCEPTED MVGO ng {bad_ng}")
        # ...and it must NOT fire when the layout was not stated: a frozen
        # build_034/build_035 artifact is a legitimate isa=1 stream whose
        # `ng` lives in bits [5:0], and sw/seq_run.py's and
        # sw/chat_seq.py's artifact checks validate exactly those.
        _SF.validate(r)
    for good_ng in (1, rtl_ng):
        r = _SF.Rec(_SF.OP_MVGO, 0, 0, (good_ng << 22) | (24 << 6), 0, 0)
        _SF.validate(r, shape_isa=_SF.SHAPE_ISA_9B)
    out.write(f"MVGO ng: 0 and {rtl_ng + 1} REFUSED at isa=2, 1 and "
              f"{rtl_ng} accepted, and NEITHER refused when the layout is "
              f"unstated (frozen isa=1 artifacts)\n")
    return ok


def _rtl_int(path, pat):
    """Read one integer literal out of an RTL file by regex."""
    src = open(os.path.join(TOP, path)).read()
    m = re.search(pat, src)
    if not m:
        raise SystemExit(f"isa_bits: {pat!r} not found in {path}")
    return int(m.group(1))


def _seq_model_dnst(SM, gen, a0, a1, a2, dnsb):
    """ref/seq_model.py's open-coded DNST decode, exercised in place."""
    calls = []

    class _Spy:
        def dnst(self, *a):
            calls.append(a)

        def __getattr__(self, k):
            return lambda *a, **kw: None

    ex = SM.SeqExec.__new__(SM.SeqExec)
    ex.M = _Spy()
    ex.args = [a0, a1, a2]
    ex.issued = 0
    ex.xrf = [0] * 8
    if gen == 2:
        ex.dnsb = dnsb
    ex._layer_cmd(8)
    return calls[0] if calls else None


def _tb_dnst(GSL, *a):
    """tb/scripts/gen_seq_layer_script.py's hand-coded DNST packer."""
    buf = io.StringIO()
    GSL.dnst(buf, *a)
    line = buf.getvalue().strip().split()
    assert line and line[0] == "C", f"tb DNST emitted {buf.getvalue()!r}"
    return tuple(int(x, 16) for x in line[1:5])


# ======================================================================
# 5. driver
# ======================================================================
def run(perturb=None, out=sys.stdout, seed=20260901):
    import gen_layer_script as GLS
    import seq_format as SF
    import seq_model as SM
    import chat_seq as CS
    sys.path.insert(0, os.path.join(TOP, "tb", "scripts"))
    import gen_seq_layer_script as GSL

    del _FAILS[:]
    gen, fields = load_rtl_fields(perturb)
    out.write(f"=== isa_bits: rtl/layer_chan.sv is SEQ_ISA v{gen}.x, "
              f"ISA_SADDR_MAX={GLS.ISA_SADDR_MAX}, "
              f"SCRATCH_MAX={GLS.SCRATCH_MAX}\n")
    if perturb:
        out.write(f"=== NEGATIVE CONTROL: {perturb} — "
                  f"{PERTURBATIONS[perturb]}\n")
    out.write("\n--- 1. bit budget (M: widths read out of the RTL; "
              "S: 96 = three 32-bit ARG CSRs) ---\n")
    ok1 = bit_budget(gen, fields, out)
    out.write("\n--- 2. emitter CEILINGS vs the RTL SLICES that carry them "
              "---\n")
    try:
        ok2 = field_ceilings(gen, fields, GLS, SF, out)
    except AssertionError as e:
        out.write(f"  FAIL (assert) {e}\n")
        _note((ASSERT,), f"section 2 aborted by an assert: {e}")
        ok2 = False
    out.write("\n--- 3. encoder <-> decoder equivalence, three independent "
              "implementations ---\n")
    try:
        ok3 = equivalence(gen, fields, GLS, CS, SM, GSL, out, seed=seed)
    except AssertionError as e:
        out.write(f"  FAIL (assert) {e}\n")
        _note((ASSERT,), f"section 3 aborted by an assert: {e}")
        ok3 = False
    ok = ok1 and ok2 and ok3
    if ok != (not _FAILS):
        # every FAIL path records itself; a disagreement is a bug HERE
        raise AssertionError(f"isa_bits: verdict {ok} but {len(_FAILS)} "
                             f"recorded FAILs — a FAIL path is unrecorded")
    out.write("\nISA_BITS: " + ("PASS" if ok else "FAIL") + "\n")
    return ok


def dnst_map_control(out=sys.stdout):
    """The DNST-assert negative control (spec 4.3 S3 / plan step 2).

    Perturb the SCA TILE MAP and require `Mach.dnsb`'s layout-authority
    assert to fire.  This is the control the spec asks for by name: a
    self-consistency assert would PASS under this perturbation, because the
    pointer and its base move together — only a check against the WRITER
    (the GATE command's dst) can see it.
    """
    import gen_layer_script as GLS
    import layer_ref as LR
    ok = True

    def emit(beta_base, decay_base, gate_dst):
        M = GLS.Mach(io.StringIO())
        M.gate(0, 0, 0, 0, gate_dst)
        M.dnsb(beta_base, decay_base)
        return M

    # 1. the tree's own map must be accepted (the control must not fire on
    #    a healthy layout, or it proves nothing either)
    try:
        emit(GLS.beta_base, GLS.decay_base, GLS.GD)
        out.write(f"  healthy map (beta_base={GLS.beta_base}, "
                  f"decay_base={GLS.decay_base}, GATE dst={GLS.GD}, "
                  f"LNH={LR.LNH}): ACCEPTED\n")
    except AssertionError as e:
        out.write(f"  FAIL healthy map REFUSED: {e}\n")
        ok = False

    # 2. every perturbation of the map must FIRE
    cases = [
        ("decay_base off by one", GLS.beta_base, GLS.decay_base + 1, GLS.GD),
        ("decay_base at the WALL-17 literal 16 rather than LNH",
         GLS.beta_base, GLS.beta_base + 16 + (0 if LR.LNH != 16 else 1),
         GLS.GD),
        ("beta_base off by one", GLS.beta_base + 1, GLS.decay_base, GLS.GD),
        ("the beta|decay split moved (halves swapped)",
         GLS.decay_base, GLS.beta_base, GLS.GD),
        ("the GATE writer moved and the map did not",
         GLS.beta_base, GLS.decay_base, GLS.GD + 2 * LR.LNH),
    ]
    for (name, bb, db, gd) in cases:
        try:
            emit(bb, db, gd)
            out.write(f"  {name:56s} ACCEPTED — CONTROL FAILED\n")
            ok = False
        except AssertionError:
            out.write(f"  {name:56s} REFUSED\n")
    out.write("\nDNST_MAP_CONTROL: "
              + ("PASS (healthy accepted, every perturbation refused)"
                 if ok else "FAIL") + "\n")
    return ok


def _refusal_verdict(key, fails, exc):
    """Classify one perturbed run (SR-ISABITS).

    REFUSED only when a recorded FAIL implicates the perturbed field `key`
    itself; a run aborted by an assert or exception is a CONTROL FAILURE
    whatever else it recorded (part of the gate never ran, so the refusal
    is not attributable), and so is a run refused only by checks on OTHER
    fields.  Returns (refused: bool, text)."""
    if exc is not None:
        return False, f"CONTROL FAILURE — died on {exc}"
    asserts = [m for (f, m) in fails if ASSERT in f]
    if asserts:
        return False, f"CONTROL FAILURE — unrelated assert: {asserts[0]}"
    own = [m for (f, m) in fails if key in f]
    if own:
        return True, (f"REFUSED by its own check ({len(own)} FAIL on "
                      f"{key}; first: {own[0][:70]})")
    if fails:
        return False, (f"CONTROL FAILURE — refused only by checks on other "
                       f"fields: {sorted({x for f, _m in fails for x in f})}")
    return False, "ACCEPTED — CONTROL FAILED"


def negative_control(out=sys.stdout):
    """Every perturbation must be refused BY ITS OWN CHECK (SR-ISABITS).

    Step 0: the UNPERTURBED run must PASS, or no refusal means anything
    (before SR-ISABITS it failed on a COLD KV slot and this control still
    printed PASS).  Then each perturbation of field F counts as REFUSED only
    if a recorded FAIL implicates F (`_refusal_verdict`)."""
    base = io.StringIO()
    try:
        base_ok = run(out=base)
    except Exception as e:                                # noqa: BLE001
        base_ok = False
        base.write(f"  (died with {type(e).__name__}: {e})\n")
    out.write("baseline (unperturbed)" + " " * 46
              + ("PASS\n" if base_ok else "FAIL — the control is "
                 "uninformative on this tree\n"))
    if not base_ok:
        out.write(base.getvalue())
    bad, nref = [], 0
    for name in sorted(PERTURBATIONS):
        buf = io.StringIO()
        exc = None
        try:
            run(perturb=name, out=buf)
        except Exception as e:                            # noqa: BLE001
            exc = f"{type(e).__name__}: {e}"
        key = name[:-5] if name.endswith("_wide") else name
        refused, text = _refusal_verdict(key, list(_FAILS), exc)
        out.write(f"{name:12s} {PERTURBATIONS[name]:55s} {text}\n")
        if refused:
            nref += 1
        else:
            bad.append(name)
    good = base_ok and not bad
    out.write(f"\nrefused by their own check: {nref} of {len(PERTURBATIONS)}"
              + (f"; broken (no-op) perturbations: {sorted(BROKEN)}"
                 if BROKEN else "") + "\n")
    out.write("NEGATIVE_CONTROL: "
              + ("PASS (baseline PASS; every perturbation refused by its own "
                 "check)" if good
                 else "FAIL — " + ("baseline did not PASS; " if not base_ok
                                   else "")
                 + (f"not refused by their own check: {bad}" if bad
                    else "")) + "\n")
    return good


# ======================================================================
# 6. G3.3 — the matvec_chan SHAPE word, across every implementation
# ======================================================================
# THE SAME SHAPE AS THE ARG PROOF ABOVE.  The SHAPE word is written down
# independently in six places, so the only honest check is a round trip
# through all of them at the same values:
#
#   * `sw/hwmap.shape_word`             the PRODUCER, and it is VERSIONED
#                                       (isa=1 = build_034/build_035,
#                                        isa=2 = this tree)
#   * `rtl/matvec_chan.sv`              the consumer, PARSED out of the
#                                       CSR write case and the readback
#                                       concat, never transcribed
#   * `ref/seq_format.disasm`           the disassembler
#   * `ref/seq_model.SeqExec._mvgo`     the golden executor, driven through
#                                       a capturing DDRWeights so the real
#                                       decode runs
#   * `tb/tb_matvec_chan.sv`            the TB twin, PARSED out of its
#                                       `wr32(12'h014, {...})` concat
#   * `tb/seq_stub_mvchan.sv`           the SEQ stub, which must keep the
#                                       word OPAQUE (a structural check:
#                                       if it ever starts decoding fields,
#                                       this refuses until it is listed)
#
# `--shape-control` narrows or widens one RTL field at a time and requires
# the round trip to refuse each one, which is what makes the agreement
# above evidence rather than a tautology.
MVCHAN_RTL = os.path.join(TOP, "rtl", "matvec_chan.sv")
MVCHAN_TB = os.path.join(TOP, "tb", "tb_matvec_chan.sv")
MVCHAN_STUB = os.path.join(TOP, "tb", "seq_stub_mvchan.sv")

SHAPE_FIELDS = ("ng", "nrows", "sh")

SHAPE_PERTURBATIONS = {
    "ng":       "narrow the RTL SHAPE ng slice by one bit",
    "nrows":    "narrow the RTL SHAPE nrows slice by one bit",
    "sh":       "narrow the RTL SHAPE sh slice by one bit",
    "ng_wide":  "WIDEN the RTL SHAPE ng slice by one bit (into a spare)",
    "sh_wide":  "WIDEN the RTL SHAPE sh slice by one bit (it then overlaps "
                "nrows)",
}

# SR12 (SEQ_ISA v2.3 B17.2): the R2 rows' perturbations — each moves ONE
# parsed RTL anchor by one bit / one unit, and section 7 must refuse it by
# the row that owns that anchor.  They ride in SHAPE_PERTURBATIONS so
# `--shape-control` walks them with the rest.
R2_PERTURBATIONS = {
    "movx_word": "narrow the RTL MOVX start-word slice by one bit",
    "movy_row":  "narrow the RTL MOVY start-row slice by one bit (lo + 1)",
    "xbank_bit": "move the RTL XBANK SHAPE bit down by one (29 -> 28)",
    "rbank_bit": "move the RTL RBANK SHAPE bit up by one (30 -> 31)",
    "xb_line":   "the engine's XBANK start line one lower (48 -> 47)",
    "rb_row":    "the engine's RBANK start row one lower (2048 -> 2047)",
}
SHAPE_PERTURBATIONS.update(R2_PERTURBATIONS)


def _shape_slices_from_concat(text, names):
    """(hi, lo) per field from a SystemVerilog concat, RIGHT to LEFT.

    `names` maps a regex that identifies a concat member to a field name;
    a member that matches nothing is treated as a filler of its literal
    width.  Members are `N'(expr)` casts, `N'b0`/`N'd0` literals or bare
    identifiers with a declared width supplied by the caller.
    """
    body = text[text.index("{") + 1:text.rindex("}")]
    parts, depth, cur = [], 0, ""
    for ch in body:
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    out, lo = {}, 0
    for member in reversed(parts):
        m = re.match(r"^(\d+)'", member)
        if not m:
            raise AssertionError(
                f"SHAPE concat member {member!r} has no explicit width — "
                "this checker refuses to guess one")
        w = int(m.group(1))
        for pat, name in names.items():
            if re.search(pat, member):
                out[name] = (lo + w - 1, lo)
                break
        lo += w
    if lo != 32:
        raise AssertionError(f"SHAPE concat is {lo} bits, not 32: {text!r}")
    missing = [n for n in SHAPE_FIELDS if n not in out]
    if missing:
        raise AssertionError(f"SHAPE concat {text!r} names no {missing}")
    return out, lo


def load_shape_rtl(perturb=None):
    """The SHAPE field slices, READ OUT OF rtl/matvec_chan.sv.

    Two independent readings inside the same file — the CSR WRITE case
    (what the engine actually latches) and the READBACK concat (what the
    host reads back) — and they must agree.  A design that decoded and
    reported different bits would pass either one alone.
    """
    src = open(MVCHAN_RTL).read()
    i = src.find("10'h005: begin")
    if i < 0:
        raise AssertionError(f"{MVCHAN_RTL}: no SHAPE (0x14) CSR write case")
    seg = src[i:i + 800]
    wr = {}
    for f in SHAPE_FIELDS:
        m = re.search(r"csr_static_%s\s*<= wdata_q\[(\d+):(\d+)\];" % f, seg)
        if not m:
            raise AssertionError(
                f"{MVCHAN_RTL}: SHAPE write case does not latch "
                f"csr_static_{f} from a wdata_q slice")
        wr[f] = (int(m.group(1)), int(m.group(2)))
    # the registers must be at least as wide as the slices they latch
    decl = {}
    for f, pat in (("ng", r"logic \[(\d+):0\]\s+csr_static_ng;"),
                   ("sh", r"logic \[(\d+):0\]\s+csr_static_sh;"),
                   ("nrows", r"logic \[(\d+):0\]\s+csr_static_nrows;")):
        m = re.search(pat, src)
        if not m:
            raise AssertionError(f"{MVCHAN_RTL}: no csr_static_{f} declaration")
        decl[f] = int(m.group(1)) + 1
    j = src.find("10'h005: s_axil_rdata <=")
    if j < 0:
        raise AssertionError(f"{MVCHAN_RTL}: no SHAPE readback case")
    rbtxt = src[j:src.index(";", j)]
    rb, _ = _shape_slices_from_concat(
        rbtxt.replace("csr_static_ng", "%d'(csr_static_ng)" % decl["ng"])
             .replace("csr_static_nrows", "%d'(csr_static_nrows)" % decl["nrows"])
             .replace("csr_static_sh", "%d'(csr_static_sh)" % decl["sh"]),
        {r"csr_static_ng": "ng", r"csr_static_nrows": "nrows",
         r"csr_static_sh": "sh"})
    if rb != wr:
        raise AssertionError(
            f"{MVCHAN_RTL}: the SHAPE write case decodes {wr} but the "
            f"readback reports {rb} — the two must be the same word")
    for f in SHAPE_FIELDS:
        w = wr[f][0] - wr[f][1] + 1
        if decl[f] < w:
            raise AssertionError(
                f"{MVCHAN_RTL}: csr_static_{f} is {decl[f]} b but latches a "
                f"{w}-bit slice")
    if perturb and perturb not in R2_PERTURBATIONS:
        widen = perturb.endswith("_wide")
        key = perturb[:-5] if widen else perturb
        if key not in SHAPE_FIELDS:
            raise SystemExit(f"unknown SHAPE perturbation {perturb!r}")
        hi, lo = wr[key]
        wr[key] = (hi + 1, lo) if widen else (hi - 1, lo)
    return wr


def load_shape_tb():
    """The SHAPE slices as tb/tb_matvec_chan.sv composes them."""
    src = open(MVCHAN_TB).read()
    m = re.search(r"wr32\(12'h014, (\{[^;]*?\})\);", src, re.S)
    if not m:
        raise AssertionError(f"{MVCHAN_TB}: no SHAPE (0x14) CSR write")
    sl, _ = _shape_slices_from_concat(
        m.group(1), {r"\bNG\b": "ng", r"\bNROWS\b": "nrows",
                     r"\bSH\b": "sh"})
    return sl


def check_shape_stub(out):
    """tb/seq_stub_mvchan.sv must keep SHAPE OPAQUE."""
    src = open(MVCHAN_STUB).read()
    ok = re.search(r"10'h005: shape\s*<= wdata_q;", src) is not None
    fields = re.search(r"shape\s*\[\d+:\d+\]", src) is not None
    out.write(f"  {'seq_stub_mvchan.sv':28s} SHAPE stored WHOLE: "
              f"{'yes' if ok else 'NO'}; decodes fields: "
              f"{'YES — it is now a 7th implementation and must be listed here' if fields else 'no'}\n")
    return ok and not fields


def _seq_model_shape(SM, HW, word, isa):
    """Run ref/seq_model.SeqExec._mvgo's REAL decode and capture it."""
    import numpy as np
    import seq_format as SF

    class _W(object):
        def matvec(self, wbase, nrows, sh, ng, g, x8, w8=False, chan=0):
            raise _Captured((ng, nrows, sh, g, w8))

    rec = SF.Rec(SF.OP_MVGO, flags=0, target=0, imm32=word,
                 addr_lo=HW.W_BASE & 0xFFFFFFFF,
                 len_or_addr_hi=((1 << 8) | ((HW.W_BASE >> 32) & 0xFF)))
    ex = SM.SeqExec([rec, SF.Rec(SF.OP_HALT)], b"", _W(), isa=isa)
    ex.xwin[0] = np.zeros(4, dtype=np.int8)
    try:
        ex._mvgo(rec)
    except _Captured as c:
        return c.args[0][:3]
    raise AssertionError("seq_model._mvgo did not reach the matvec call")


def _seq_format_shape(SF, word):
    """Parse ref/seq_format.disasm's own rendering of the SHAPE word."""
    rec = SF.Rec(SF.OP_MVGO, flags=0, target=0, imm32=word,
                 addr_lo=0, len_or_addr_hi=(1 << 8))
    txt = SF.disasm(rec, 0)
    m = re.search(r"ng=(\d+) nrows=(\d+) sh=(\d+)", txt)
    if not m:
        raise AssertionError(f"seq_format.disasm SHAPE render changed: {txt}")
    return tuple(int(x) for x in m.groups())


SW_DIR = os.path.join(TOP, "sw")


def check_shape_producers(out):
    """EVERY live CSR write of R_SHAPE must go through `hwmap.shape_word`.

    G3.3 fix round 1: `sw/matvec_test.py` hand-rolled the packing
    (`(N << 12) | (sh << 6) | ng`) and so was invisible to the round trip
    above — it would have silently mis-driven the 9B bitstream.  "One
    packer, every producer in lockstep" is only a contract if something
    checks it, so this walks `sw/` and requires each `R_SHAPE` write to name
    `shape_word` within its own statement.
    """
    ok = True
    found = 0
    for fn in sorted(os.listdir(SW_DIR)):
        if not fn.endswith(".py"):
            continue
        path = os.path.join(SW_DIR, fn)
        lines = open(path).read().split("\n")
        for i, ln in enumerate(lines):
            if not re.search(r"\bwr\(.*\bR_SHAPE\b", ln):
                continue
            found += 1
            stmt = " ".join(lines[i:i + 3])
            good = "shape_word(" in stmt
            isa = "isa=" in stmt
            out.write(f"  {fn}:{i + 1:<5d} R_SHAPE write -> "
                      f"{'shape_word' if good else 'HAND-ROLLED'}"
                      f"{'' if isa else '  (NO isa= ARGUMENT)'}\n")
            ok &= good and isa
    if not found:
        out.write("  FAIL: no R_SHAPE writes found at all — the sweep is "
                  "broken, not the tree\n")
        ok = False
    else:
        out.write(f"  {found} live R_SHAPE producer(s) in sw/, all through "
                  f"the one packer: {'yes' if ok else 'NO'}\n")
    return ok


def shape_roundtrip(out=sys.stdout, perturb=None, seed=20260902):
    """The six-way SHAPE round trip.  Returns True on agreement."""
    import hwmap as HW
    import seq_format as SF
    import seq_model as SM

    ok = True
    rtl = load_shape_rtl(perturb)
    tb = load_shape_tb()
    out.write("  field   rtl/matvec_chan.sv   tb/tb_matvec_chan.sv   width\n")
    for f in SHAPE_FIELDS:
        hi, lo = rtl[f]
        thi, tlo = tb[f]
        agree = (hi, lo) == (thi, tlo)
        out.write(f"  {f:6s}  [{hi:2d}:{lo:2d}]{'':13s}[{thi:2d}:{tlo:2d}]"
                  f"{'':15s}{hi - lo + 1:2d} b"
                  f"{'' if agree else '   <-- TB TWIN DISAGREES'}\n")
        ok &= agree
    if perturb:
        out.write(f"  (PERTURBED: {perturb} — {SHAPE_PERTURBATIONS[perturb]})\n")
    # the three fields must tile the low bits with no overlap and leave the
    # spare bits the spec pins
    bits = []
    for f in SHAPE_FIELDS:
        bits += list(range(rtl[f][1], rtl[f][0] + 1))
    if len(bits) != len(set(bits)):
        out.write("  FAIL: the RTL SHAPE fields OVERLAP\n")
        ok = False
    spare = 32 - len(set(bits))
    out.write(f"  spare bits: {spare} (spec 5.2 pins THREE)\n")
    if spare != 3:
        out.write("  FAIL: the spec's constraint is three spare bits\n")
        ok = False

    def unpack_rtl(w):
        return tuple(((w >> rtl[f][1]) & ((1 << (rtl[f][0] - rtl[f][1] + 1)) - 1))
                     for f in SHAPE_FIELDS)

    rng = random.Random(seed)
    # BOUNDARY values first, then seeded random ones
    ngs = [1, 32, 64, 96]
    nrs = [0, 1, 65535]
    shs = [0, 63]
    cases = [(ng, nr, sh) for ng in ngs for nr in nrs for sh in shs]
    cases += [(rng.randrange(1, 97), rng.randrange(0, 65536),
               rng.randrange(0, 64)) for _ in range(64)]
    nrt = 0
    for (ng, nr, sh) in cases:
        w = HW.shape_word(nr, sh, ng)
        got = unpack_rtl(w)
        if got != (ng, nr, sh):
            out.write(f"  FAIL rtl decode of {w:#010x}: {got} != {(ng, nr, sh)}\n")
            ok = False
            break
        if _seq_format_shape(SF, w) != (ng, nr, sh):
            out.write(f"  FAIL seq_format.disasm of {w:#010x}\n")
            ok = False
            break
        if _seq_model_shape(SM, HW, w, HW.SHAPE_ISA) != (ng, nr, sh):
            out.write(f"  FAIL seq_model._mvgo of {w:#010x}\n")
            ok = False
            break
        if (w >> 29) != 0:
            out.write(f"  FAIL {w:#010x} sets a spare bit\n")
            ok = False
            break
        nrt += 1
    out.write(f"  isa=2 round-trips: {nrt} of {len(cases)} value sets "
              f"(ng {ngs} x nrows {nrs} x sh {shs} + 64 seeded random) "
              f"through hwmap -> {{rtl slice, seq_format, seq_model}}\n")

    # ---- isa=1, the layout build_034/build_035 decode -------------------
    # There is no RTL to parse for it any more, so the anchors are the
    # PINNED words read off the four live SHAPE registers
    # (evidence/qwen2b/rd/RD_GATE.md:238) and seq_model's isa=1 decoder.
    pinned = {(2048, 10, 16, True): 0x20800290,
              (512, 10, 16, True): 0x20200290,
              (2048, 5, 8, False): 0x00800148,
              (512, 5, 8, False): 0x00200148}
    n1 = 0
    for (nr, sh, ng, w8), want in pinned.items():
        w = HW.shape_word(nr, sh, ng, g=128, w8=w8, isa=HW.SHAPE_ISA_PRE_G3)
        if w != want:
            out.write(f"  FAIL isa=1 pinned word {w:#010x} != {want:#010x}\n")
            ok = False
            continue
        if _seq_model_shape(SM, HW, w, HW.SHAPE_ISA_PRE_G3) != (ng, nr, sh):
            out.write(f"  FAIL isa=1 seq_model decode of {w:#010x}\n")
            ok = False
            continue
        n1 += 1
    for ng in (1, 32, 48):
        for nr in (0, 1, 65535):
            for sh in (0, 63):
                w = HW.shape_word(nr, sh, ng, isa=HW.SHAPE_ISA_PRE_G3)
                if _seq_model_shape(SM, HW, w, HW.SHAPE_ISA_PRE_G3) != (ng, nr, sh):
                    out.write(f"  FAIL isa=1 round-trip at "
                              f"ng={ng} nrows={nr} sh={sh}\n")
                    ok = False
                n1 += 1
    out.write(f"  isa=1 round-trips: {n1} value sets (4 PINNED to "
              f"RD_GATE.md:238 + ng 1/32/48 x nrows 0/1/65535 x sh 0/63) "
              f"through hwmap -> seq_model\n")
    # THE TWO LAYOUTS MUST DIFFER, or versioning bought nothing
    if HW.shape_word(13, 7, 32) == HW.shape_word(13, 7, 32,
                                                 isa=HW.SHAPE_ISA_PRE_G3):
        out.write("  FAIL: isa=1 and isa=2 pack the same word\n")
        ok = False
    ok &= check_shape_stub(out)
    ok &= check_shape_producers(out)
    out.write("\n  -- 7. SR12: the B17.2 (R2) record fields --\n")
    ok &= r2_rows(out, perturb)
    out.write("\nSHAPE_BITS: " + ("PASS" if ok else "FAIL") + "\n")
    return ok


# ======================================================================
# 7. SR12 — the B17.2 (R2) record fields, RTL against the host side
# ======================================================================
# SEQ_ISA v2.3 B17.2 gives three record fields a meaning the R2 RTL decodes
# (docs/SEQ_ISA.md, the B17.2 encoding table):
#
#   MOVX target[11:0]  the XWIN start WORD          rtl/seq_unit.sv mv_xword
#   MVGO SHAPE 29 / 30 XBANK / RBANK                rtl/matvec_chan.sv
#                      (x from line 48, rows at      csr_static_xbank/_rbank,
#                       2048 + r)                    rtl/matvec_engine.sv
#                                                    XB_LINE / RB_ROW
#   MOVY target[15:4]  the RES start ROW            rtl/seq_unit.sv mv_row
#
# Same method as sections 3 and 6: the RTL side is PARSED out of the files
# (never transcribed), the host side is DERIVED from ref/seq_format.validate
# BEHAVIOUR (which bits of the record draw its B17.2 range / bank message)
# and exercised through ref/seq_model.SeqExec and the unit-TB golden twin
# (tb/scripts/gen_seq_unit_vectors.Model), and every row must agree.
SEQ_UNIT_RTL = os.path.join(TOP, "rtl", "seq_unit.sv")
SEQ_MOVERS_RTL = os.path.join(TOP, "rtl", "seq_movers.sv")
MV_ENGINE_RTL = os.path.join(TOP, "rtl", "matvec_engine.sv")
GEN_SEQ_UNIT = os.path.join(TOP, "tb", "scripts")


def _r2_host_field(SF, op, msg, full_len):
    """The target bits whose setting (alone, at a full-window length) draws
    ref/seq_format.validate's B17.2 range refusal `msg` at caps {R1,R2}."""
    bits = []
    for b in range(16):
        r = SF.Rec(op, flags=0, target=(1 << b), imm32=0, addr_lo=0,
                   len_or_addr_hi=full_len)
        try:
            SF.validate(r, caps=frozenset({"R1", "R2"}))
        except SF.SeqValidationError as e:
            if msg in str(e):
                bits.append(b)
    return (max(bits), min(bits)) if bits else None


def _r2_shape_bit(SF, HW, msg, **over):
    """The SHAPE bit (29..31) whose setting draws the validator's bank
    refusal `msg` on an otherwise-legal word made illegal only for a bank."""
    got = []
    base = HW.shape_word(over.get("nrows", 8), 0, over.get("ng", 8))
    for b in (29, 30, 31):
        r = SF.Rec(SF.OP_MVGO, flags=0, target=0, imm32=base | (1 << b),
                   addr_lo=0, len_or_addr_hi=(1 << 8))
        try:
            SF.validate(r, shape_isa=SF.SHAPE_ISA_9B,
                        caps=frozenset({"R1", "R2"}))
        except SF.SeqValidationError as e:
            if msg in str(e):
                got.append(b)
    return got[0] if len(got) == 1 else None


def r2_rows(out=sys.stdout, perturb=None):
    """SR12: the B17.2 rows.  Returns True on agreement."""
    import numpy as np
    import hwmap as HW
    import seq_format as SF
    import seq_model as SM
    if GEN_SEQ_UNIT not in sys.path:
        sys.path.insert(0, GEN_SEQ_UNIT)
    import gen_seq_unit_vectors as GSU

    ok = True

    def row(name, good, detail):
        nonlocal ok
        out.write(f"  {name:34s} {'ok  ' if good else 'FAIL'} {detail}\n")
        ok &= bool(good)

    su = open(SEQ_UNIT_RTL).read()
    mv = open(SEQ_MOVERS_RTL).read()
    ch = open(MVCHAN_RTL).read()
    en = open(MV_ENGINE_RTL).read()

    def slice_of(src, pat):
        m = re.search(pat, src)
        return (int(m.group(1)), int(m.group(2))) if m else None

    # ---- the RTL anchors (None = the RTL does not decode the field) ----
    rtl_word = slice_of(su, r"mv_xword\s*<=\s*r_tgt\[(\d+):(\d+)\];")
    rtl_row = slice_of(su, r"mv_row\s*<=\s*r_tgt\[(\d+):(\d+)\];")
    i = ch.find("10'h005: begin")
    seg = ch[i:i + 1200] if i >= 0 else ""
    mx = re.search(r"csr_static_xbank\s*<=\s*wdata_q\[(\d+)\];", seg)
    mr = re.search(r"csr_static_rbank\s*<=\s*wdata_q\[(\d+)\];", seg)
    rtl_xb = int(mx.group(1)) if mx else None
    rtl_rb = int(mr.group(1)) if mr else None
    ml = re.search(r"localparam\s+logic\s+\[6:0\]\s+XB_LINE\s*=\s*7'd(\d+);",
                   en)
    mrr = re.search(r"localparam\s+logic\s+\[ROW_W-1:0\]\s+RB_ROW\s*=\s*"
                    r"ROW_W'\((\d+)\);", en)
    xb_line = int(ml.group(1)) if ml else None
    rb_row = int(mrr.group(1)) if mrr else None
    mw = re.search(r"localparam\s+int\s+R2_XWIN_WORDS\s*=\s*(\d+);", su)
    mrs = re.search(r"localparam\s+int\s+R2_RES_ROWS\s*=\s*(\d+);", su)
    su_words = int(mw.group(1)) if mw else None
    su_rows = int(mrs.group(1)) if mrs else None

    if perturb == "movx_word" and rtl_word:
        rtl_word = (rtl_word[0] - 1, rtl_word[1])
    if perturb == "movy_row" and rtl_row:
        rtl_row = (rtl_row[0], rtl_row[1] + 1)
    if perturb == "xbank_bit" and rtl_xb is not None:
        rtl_xb -= 1
    if perturb == "rbank_bit" and rtl_rb is not None:
        rtl_rb += 1
    if perturb == "xb_line" and xb_line is not None:
        xb_line -= 1
    if perturb == "rb_row" and rb_row is not None:
        rb_row -= 1

    # ---- the host side, derived from the validator's behaviour ---------
    host_word = _r2_host_field(SF, SF.OP_MOVX, "MOVX XWIN range",
                               4 * SF.XWIN_WORDS)
    host_row = _r2_host_field(SF, SF.OP_MOVY, "MOVY RES range", SF.RES_ROWS)
    host_xb = _r2_shape_bit(SF, HW, "MVGO XBANK", ng=SF.XBANK_LINE + 1)
    host_rb = _r2_shape_bit(SF, HW, "MVGO RBANK", nrows=SF.RBANK_ROW + 1)

    # ---- R2-1: MOVX start word -----------------------------------------
    row("MOVX start word: RTL mv_xword", rtl_word == host_word,
        f"rtl/seq_unit.sv r_tgt{list(rtl_word) if rtl_word else ' NOT DECODED'}"
        f" vs seq_format.validate's range field {list(host_word) if host_word else None}"
        f" (MOVX_WORD_MASK {SF.MOVX_WORD_MASK:#06x})")
    row("MOVX: burst base carries the word",
        re.search(r"MVB_XWIN\s*\+\s*\{\d+'d0,\s*xword_q,\s*2'b00\}", mv)
        is not None,
        "rtl/seq_movers.sv XWIN burst base = MVB_XWIN + 4 * start word")
    row("MOVX window: RTL R2_XWIN_WORDS", su_words == SF.XWIN_WORDS,
        f"{su_words} vs seq_format.XWIN_WORDS {SF.XWIN_WORDS}")
    # the executor and the golden twin put a MOVX at its start word
    good = True
    for w0 in (0, 1, SF.XBANK_WORD - 1, SF.XBANK_WORD, SF.XWIN_WORDS - 1):
        r = SF.Rec(SF.OP_MOVX, flags=0, target=w0, imm32=0, addr_lo=0,
                   len_or_addr_hi=4)
        ex = SM.SeqExec([r, SF.Rec(SF.OP_HALT)], b"", None,
                        caps=frozenset({"R1", "R2"}))
        ex._movx(r)
        m = GSU.Model(b"\0" * 64, np.zeros((8, 4096), dtype="<i2"))
        m.movx(r)
        good &= (4 * w0 in ex.xwin.vec.get(0, {})
                 and m.xwa[-1] == ("X", 0, w0, 1))
    row("MOVX: seq_model + TB golden twin", good,
        "SeqExec._movx writes x_mem at 4*w0 and Model.movx lists window w0, "
        "w0 in {0, 1, 1535, 1536, 3071}")

    # ---- R2-2: SHAPE bits 29 / 30 --------------------------------------
    row("SHAPE XBANK: RTL csr_static_xbank", rtl_xb is not None
        and rtl_xb == host_xb and (1 << rtl_xb) == SF.SHAPE_XBANK,
        f"wdata_q[{rtl_xb}] vs the validator's XBANK bit {host_xb} "
        f"(SHAPE_XBANK {SF.SHAPE_XBANK:#010x})")
    row("SHAPE RBANK: RTL csr_static_rbank", rtl_rb is not None
        and rtl_rb == host_rb and (1 << rtl_rb) == SF.SHAPE_RBANK,
        f"wdata_q[{rtl_rb}] vs the validator's RBANK bit {host_rb} "
        f"(SHAPE_RBANK {SF.SHAPE_RBANK:#010x})")
    row("SHAPE bit 31: dropped by the RTL",
        seg != "" and re.search(r"wdata_q\[31", seg) is None,
        "no wdata_q[31] in the SHAPE write case (spare, B17.2)")
    tbsrc = open(MVCHAN_TB).read()
    mtb = re.search(r"wr32\(12'h014, (\{[^;]*?\})\);", tbsrc, re.S)
    tbsl = {}
    if mtb:
        try:
            tbsl, _ = _shape_slices_from_concat(
                mtb.group(1), {r"\bNG\b": "ng", r"\bNROWS\b": "nrows",
                               r"\bSH\b": "sh", r"\bXB\b": "xbank",
                               r"\bRB\b": "rbank"})
        except AssertionError as e:
            out.write(f"  (TB SHAPE concat: {e})\n")
    row("SHAPE banks: tb/tb_matvec_chan.sv twin",
        tbsl.get("xbank") == (29, 29) and tbsl.get("rbank") == (30, 30)
        and rtl_xb == 29 and rtl_rb == 30,
        f"TB XB {tbsl.get('xbank')} RB {tbsl.get('rbank')}")
    row("XBANK start line: engine XB_LINE", xb_line == SF.XBANK_LINE
        and xb_line is not None
        and len(re.findall(r"x_line\s*<=\s*cfg_xbank\s*\?\s*XB_LINE\s*:"
                           r"\s*7'd0;", en)) == 2,
        f"{xb_line} vs seq_format.XBANK_LINE {SF.XBANK_LINE} (loaded at the "
        f"start AND at every row end)")
    row("RBANK start row: engine RB_ROW", rb_row == SF.RBANK_ROW
        and rb_row is not None
        and len(re.findall(r"row_in\s*<=\s*cfg_rbank\s*\?\s*RB_ROW\s*:", en))
        == 1,
        f"{rb_row} vs seq_format.RBANK_ROW {SF.RBANK_ROW}")

    class _W(object):
        def __init__(self):
            self.x8 = None

        def matvec(self, wbase, nrows, sh, ng, g, x8, w8=False, chan=0):
            self.x8 = np.array(x8)
            return np.zeros(nrows, dtype=np.int64)

        def _lookup(self, wbase, chan):
            return 0, 0, {"stride": 64}, None

    good = True
    for xb in (0, 1):
        for rb in (0, 1):
            W = _W()
            word = HW.shape_word(1, 0, 1) | (xb << 29) | (rb << 30)
            r = SF.Rec(SF.OP_MVGO, flags=0, target=1, imm32=word,
                       addr_lo=HW.W_BASE & 0xFFFFFFFF,
                       len_or_addr_hi=((1 << 8) | ((HW.W_BASE >> 32) & 0xFF)))
            ex = SM.SeqExec([r, SF.Rec(SF.OP_HALT)], b"", W,
                            caps=frozenset({"R1", "R2"}))
            # a different, in-range int8 vector per bank (-64..63 / -128..-1)
            xv = (np.arange(128) - 64 * (1 + xb)).astype(np.int8)
            ex.xwin.write(0, SF.XBANK_WORD * xb, xv)
            ex._mvgo(r)
            m = GSU.Model(b"\0" * 64, np.zeros((8, 4096), dtype="<i2"))
            m.mvgo(r)
            good &= (np.array_equal(W.x8, xv)
                     and ex.res.seg[0][-1][0] == SF.RBANK_ROW * rb
                     and ex.running[0][0] == SF.XBANK_WORD * xb
                     and m.pend[0][0] == SF.XBANK_WORD * xb
                     and m.pend[0][2] == SF.RBANK_ROW * rb)
    row("SHAPE banks: seq_model + TB golden twin", good,
        "SeqExec._mvgo reads x at 1536*XBANK, writes rows at 2048*RBANK; "
        "both running ranges start there")

    # ---- R2-3: MOVY start row ------------------------------------------
    row("MOVY start row: RTL mv_row", rtl_row == host_row,
        f"rtl/seq_unit.sv r_tgt{list(rtl_row) if rtl_row else ' NOT DECODED'}"
        f" vs seq_format.validate's range field {list(host_row) if host_row else None}")
    row("MOVY: movers load res_row_q from it",
        re.search(r"res_row_q\s*<=\s*cmd_row;", mv) is not None,
        "rtl/seq_movers.sv res_row_q <= cmd_row (was 12'd0)")
    row("MOVY window: RTL R2_RES_ROWS", su_rows == SF.RES_ROWS,
        f"{su_rows} vs seq_format.RES_ROWS {SF.RES_ROWS}")
    good = True
    for row0 in (0, 1, SF.RBANK_ROW - 1, SF.RBANK_ROW, SF.RES_ROWS - 1):
        r = SF.Rec(SF.OP_MOVY, flags=(SF.MOVY_INT16 << 4),
                   target=(row0 << 4), imm32=0, addr_lo=0x100,
                   len_or_addr_hi=1)
        ex = SM.SeqExec([r, SF.Rec(SF.OP_HALT)], b"", None,
                        caps=frozenset({"R1", "R2"}))
        y = np.arange(SF.RES_ROWS, dtype=np.int64) % 30000
        ex.res.write(0, 0, y)
        ex._movy(r)
        m = GSU.Model(b"\0" * 64, np.zeros((8, 4096), dtype="<i2"))
        m.movy(r)
        good &= (int(ex.M.mem[0x100]) == int(y[row0])
                 and m.xwa[-1] == ("Y", 0, row0, 1)
                 and (GSU.MV(0) + GSU.MV_RESPTR, row0) in m.wtr)
    row("MOVY: seq_model + TB golden twin", good,
        "SeqExec._movy reads RES row r0, Model.movy lists window r0 and "
        "writes RES_PTR = r0, r0 in {0, 1, 2047, 2048, 4095}")
    if perturb in R2_PERTURBATIONS:
        out.write(f"  (PERTURBED: {perturb} — {R2_PERTURBATIONS[perturb]})\n")
    out.write(f"  R2_ROWS: {'PASS' if ok else 'FAIL'}\n")
    return ok


def shape_control(out=sys.stdout):
    """Perturb one SHAPE field width at a time; every one must be refused."""
    bad = []
    for name in sorted(SHAPE_PERTURBATIONS):
        buf = io.StringIO()
        try:
            passed = shape_roundtrip(out=buf, perturb=name)
        except Exception as e:                            # noqa: BLE001
            passed = False
            buf.write(f"  (refused with {type(e).__name__}: {e})\n")
        verdict = "REFUSED" if not passed else "ACCEPTED — CONTROL FAILED"
        out.write(f"{name:10s} {SHAPE_PERTURBATIONS[name]:58s} {verdict}\n")
        if passed:
            bad.append(name)
            out.write(buf.getvalue())
    out.write("\nSHAPE_CONTROL: "
              + ("PASS (every perturbation refused)" if not bad
                 else f"FAIL — accepted {bad}") + "\n")
    return not bad


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--negative-control", action="store_true",
                    help="perturb each field width in turn; every one must "
                         "be refused")
    ap.add_argument("--perturb", metavar="FIELD",
                    help="run ONE perturbation (expected to FAIL)")
    ap.add_argument("--dnst-map", action="store_true",
                    help="the DNST layout-authority control: perturb the SCA "
                         "tile map and require Mach.dnsb's assert to fire")
    ap.add_argument("--shape", action="store_true",
                    help="G3.3: the matvec_chan SHAPE word across all six "
                         "implementations, both isa layouts")
    ap.add_argument("--shape-control", action="store_true",
                    help="perturb each SHAPE field width in turn; every one "
                         "must be refused")
    ap.add_argument("--shape-perturb", metavar="FIELD",
                    help="run ONE SHAPE perturbation (expected to FAIL)")
    ap.add_argument("--break-control", metavar="FIELD", action="append",
                    default=[],
                    help="SR-ISABITS control of the control: make this "
                         "perturbation a NO-OP; --negative-control must "
                         "then FAIL")
    ap.add_argument("--cold-kv", action="store_true",
                    help="SR-ISABITS control of the control: skip the "
                         "KV/DN/CV warm path (the pre-repair state); the "
                         "gate and --negative-control must then FAIL")
    ap.add_argument("--seed", type=int, default=20260901)
    a = ap.parse_args()
    global COLD_KV
    COLD_KV = a.cold_kv
    for b in a.break_control:
        if b not in PERTURBATIONS:
            raise SystemExit(f"unknown perturbation {b!r}")
        BROKEN.add(b)
    if a.shape_control:
        sys.exit(0 if shape_control() else 1)
    if a.shape or a.shape_perturb:
        sys.exit(0 if shape_roundtrip(perturb=a.shape_perturb) else 1)
    if a.dnst_map:
        sys.exit(0 if dnst_map_control() else 1)
    if a.negative_control:
        sys.exit(0 if negative_control() else 1)
    sys.exit(0 if run(perturb=a.perturb, seed=a.seed) else 1)


if __name__ == "__main__":
    main()
