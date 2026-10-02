#!/usr/bin/env python3
"""sdma_bits.py — S1's census of the SEQ_ISA v2.1 state-DMA extension.

WHAT IT TIES.  `docs/SEQ_ISA.md` B15 is the contract; three implementations
mirror it — `rtl/layer_chan.sv` (Task S2), `ref/seq_format.py` and
`sw/hwmap.py` — and a constant written down four times is a constant that
drifts.  So every number is READ OUT of its source (parsed, or probed
through the function that owns it) and required equal, in the shape
`evidence/qwen9b/g3/isa_bits.py` established for the ARG encoding.

The three functions this file needs from that pattern — `grab()`
(:223, marker + regex, `SystemExit` naming a missing symbol),
`_apply_perturbation()` (:284, mutate the LOADED dict, not the source) and
`negative_control()` (:933, every perturbation must be refused) — are
COPIED here rather than imported: `isa_bits.py` is a 1,361-line gate for a
different encoding and importing it would drag its RTL generation detector
and its whole anchor table into S1's namespace.  `grab()` is three lines.

SIX DUTIES (plan Task S1 step 4, extended by fix round 1's I3):
  1. parse `rtl/layer_chan.sv` for OP_SLD/OP_SST, the five CSR WORD offsets
     (0x19..0x1D), the six err_code values, the THREE ADDRESS SHIFTS and the
     ARG0 and LAYER field slices — every one on a line carrying a
     `// SDMA_BITS: <NAME>` marker, so a missing symbol is a SystemExit
     naming it;
  2. import `ref.seq_format` and `sw.hwmap` and require equality of every
     constant (opcodes, byte offset == 4 x word offset, error codes,
     strides, T_MAX, the LAYER bit homes);
  3. parse `docs/SEQ_ISA.md` B15 and require its numbers to match too;
  4. round-trip 64 random (kind, slot, layer, head) through
     `sdma_arg0` -> `sdma_fields`, round-trip `layer_word`, and require
     `validate_stream()` to REFUSE the five out-of-envelope streams;
  5. `--perturb rtl|rtl-shift|rtl-layer|ref|host|doc` flips one constant in
     the in-memory copy of that view and must be CAUGHT;
  6. `--ref-only` skips the RTL half (and, with it, the three `rtl*`
     perturbations, which have nothing to flip).

RED BY DESIGN.  `rtl/layer_chan.sv` has no `OP_SLD` on this tree — Task S2
lands it — so the default run FAILS on the RTL half and that failure IS
S1's record.  `--ref-only` is the half S1 owns and it must be GREEN, with
every perturbation CAUGHT.

THE RTL CONTRACT S2 MUST SATISFY.  The plan's S2 localparam bullet
(`docs/superpowers/plans/2026-09-04-qwen35-9b-state-spill.md:340`) is the
authority; this is its parse shape.  A scalar anchor's value is read off
the marked line; a field anchor's slices are read off the WHOLE marked
line, so the concat may sit on either side of the marker:

    localparam logic [3:0] OP_SLD = 4'd13;           // SDMA_BITS: OP_SLD
    localparam logic [3:0] OP_SST = 4'd14;           // SDMA_BITS: OP_SST
    localparam logic [9:0] SB_DN_W = 10'h019;        // SDMA_BITS: CSR_SB_DN
    ... SB_KV_W 10'h01A, SB_CV_W 10'h01B, SDMA_W 10'h01C, SDMA_CYC_W 10'h01D
        (CSR_SB_KV, CSR_SB_CV, CSR_SDMA, CSR_SDMA_CYC)
    localparam logic [7:0] E_ENV = 8'h01;            // SDMA_BITS: ERR_E_ENV
    ... E_LAYER 8'h02, E_DMA_BASE 8'h10, E_DMA_RANGE 8'h11,
        E_DMA_AXI 8'h12, E_DMA_COLD 8'h13
    localparam int SDMA_SHIFT_DN = 20;               // SDMA_BITS: SHIFT_DN
    localparam int SDMA_SHIFT_KV = 21;               // SDMA_BITS: SHIFT_KV
    localparam int SDMA_SHIFT_CV = 17;               // SDMA_BITS: SHIFT_CV
    //   arg0 = {kind[12:11], slot[10], layer[9:5], head[4:0]}  // SDMA_BITS: ARG0_FIELDS
    10'h00C: begin  // SDMA_BITS: LAYER_FIELDS {cv_slot[13:12], kv_layer[10:8], kv_slot[4:3], dn_slot[1:0]}

A scalar's value is the first SIZED SystemVerilog literal on the marked
line (`4'd13`, `10'h019`, `8'h01`), else a plain `= <decimal>;` — the shift
localparams are unsized ints.  A CSR anchor's value is a WORD offset and is
multiplied by 4 before it meets the byte offsets the doc, the reference and
the host use — the standing hazard the plan names (the RTL decodes words,
everyone else decodes bytes).  The SHIFT and LAYER_FIELDS anchors exist
because without them the three address shifts and B15.2's LAYER word were
agreed only between the host/reference and the doc: the numbers the
hardware actually applies had no column (fix round 1, I3).

Labels (spec 0's evidence contract): every number printed is **M**
(measured off the tree) except the RED-case list, which is **S** (B15.1's
own envelope, restated as five streams).

USAGE
    python3 evidence/qwen9b/s1/sdma_bits.py               # the gate (RED until S2)
    python3 evidence/qwen9b/s1/sdma_bits.py --ref-only    # S1's half, GREEN
    python3 evidence/qwen9b/s1/sdma_bits.py --ref-only --control
    python3 evidence/qwen9b/s1/sdma_bits.py --ref-only --perturb ref
    SDMA_BITS_RTL=/path/to/synthetic.sv python3 evidence/qwen9b/s1/sdma_bits.py
        # point the RTL half at a file other than rtl/layer_chan.sv, so the
        # parse and the rtl* perturbations can be exercised BEFORE S2 lands
        # (fix round 1: the RED must be structural, not a broken parser)
"""

import argparse
import io
import os
import random
import re
import sys

TOP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RTL_REL = "rtl/layer_chan.sv"
DOC_REL = "docs/SEQ_ISA.md"
RTL = os.environ.get("SDMA_BITS_RTL") or os.path.join(TOP, RTL_REL)
if os.environ.get("SDMA_BITS_RTL"):
    RTL_REL = os.environ["SDMA_BITS_RTL"]
DOC = os.path.join(TOP, DOC_REL)

for _p in ("ref", "sw"):
    _d = os.path.join(TOP, _p)
    if _d not in sys.path:
        sys.path.insert(0, _d)

import seq_format as SF                                   # noqa: E402
import hwmap as HW                                        # noqa: E402


# ======================================================================
# 0. helpers
# ======================================================================
_LIT = re.compile(r"\b(\d+)'([bdh])([0-9a-fA-F_]+)")
_PLAIN = re.compile(r"=\s*(\d+)\s*;")
_SLICE = re.compile(r"\b([a-z_][a-z0-9_]*)\s*\[\s*(\d+)\s*(?::\s*(\d+)\s*)?\]")


def _lit(text, name, where):
    """The anchor's value on `text`, as an int.

    A SIZED SystemVerilog literal first (`4'd13`, `10'h019`, `8'h01`), then a
    plain decimal assignment (`= 20;`) — the shift localparams the plan gives
    S2 are `localparam int SDMA_SHIFT_DN = 20;`, an unsized int, and a parser
    that only knew sized literals would refuse them.
    """
    m = _LIT.search(text)
    if m:
        base = {"b": 2, "d": 10, "h": 16}[m.group(2)]
        return int(m.group(3).replace("_", ""), base)
    m = _PLAIN.search(text)
    if m:
        return int(m.group(1))
    raise SystemExit(f"SDMA_BITS: FAIL — {where} line for {name} carries "
                     f"no value: {text.strip()!r}")


def _slices(text):
    """{name: (hi, lo)} for every `name[hi:lo]` / `name[b]` on `text`."""
    out = {}
    for m in _SLICE.finditer(text):
        hi = int(m.group(2))
        lo = int(m.group(3)) if m.group(3) is not None else hi
        out[m.group(1)] = (hi, lo)
    return out


def _log2(v, name):
    assert v > 0 and (v & (v - 1)) == 0, f"{name} = {v} is not a power of two"
    return v.bit_length() - 1


def _bits(v):
    return {b for b in range(32) if v >> b & 1}


def _home(bitset, name):
    """(hi, lo) of a contiguous bit set."""
    assert bitset, f"{name}: no bits"
    hi, lo = max(bitset), min(bitset)
    assert bitset == set(range(lo, hi + 1)), f"{name}: {sorted(bitset)} is not contiguous"
    return hi, lo


# ======================================================================
# 1. the RTL view — parsed, and RED until Task S2
# ======================================================================
RTL_MARK = "// SDMA_BITS:"

# (view key, the marker symbol).  OP_SLD is FIRST so the RED message names
# the symbol the plan's expected line names.
RTL_SCALARS = [
    ("op_sld",        "OP_SLD"),
    ("op_sst",        "OP_SST"),
    ("csr_sb_dn",     "CSR_SB_DN"),
    ("csr_sb_kv",     "CSR_SB_KV"),
    ("csr_sb_cv",     "CSR_SB_CV"),
    ("csr_sdma",      "CSR_SDMA"),
    ("csr_sdma_cyc",  "CSR_SDMA_CYC"),
    ("err_e_env",     "ERR_E_ENV"),
    ("err_e_layer",   "ERR_E_LAYER"),
    ("err_e_dma_base", "ERR_E_DMA_BASE"),
    ("err_e_dma_range", "ERR_E_DMA_RANGE"),
    ("err_e_dma_axi", "ERR_E_DMA_AXI"),
    ("err_e_dma_cold", "ERR_E_DMA_COLD"),
    # The three ADDRESS SHIFTS the RTL hardcodes into its address adder.
    # Without these the shifts were a host<->doc agreement with no RTL
    # column, i.e. the one number the hardware actually applies went
    # unchecked (fix round 1, I3).
    ("shift_dn",      "SHIFT_DN"),
    ("shift_kv",      "SHIFT_KV"),
    ("shift_cv",      "SHIFT_CV"),
]
RTL_CSR_KEYS = ("csr_sb_dn", "csr_sb_kv", "csr_sb_cv", "csr_sdma", "csr_sdma_cyc")

# The two field-concat anchors: (marker symbol, key prefix, the field names).
# The slices are read off the WHOLE marked line, so the concat may sit on
# either side of the marker — the plan puts ARG0's in the header comment
# above the marker and LAYER's inside the marker itself.
RTL_FIELD_ANCHORS = [
    ("ARG0_FIELDS",  "arg0",  ("kind", "slot", "layer", "head")),
    ("LAYER_FIELDS", "layer", ("dn_slot", "kv_slot", "cv_slot", "kv_layer")),
]


def grab(lines, symbol):
    """The line carrying `// SDMA_BITS: <symbol>`.

    isa_bits.py's grab() (evidence/qwen9b/g3/isa_bits.py:223) in the shape
    this file needs: a MARKER, and a SystemExit that NAMES the symbol when
    the marker is absent — which is exactly S1's RED.
    """
    want = RTL_MARK + " " + symbol
    for ln in lines:
        i = ln.find(want)
        if i < 0:
            continue
        tail = ln[i + len(want):]
        if tail[:1] in ("", " ", "\n", "\t", "\r"):
            return ln
    sys.stdout.flush()
    raise SystemExit(f"SDMA_BITS: FAIL — {RTL_REL} has no {symbol}")


def load_rtl():
    with open(RTL, encoding="utf-8") as f:
        lines = f.read().splitlines()
    v = {}
    for key, sym in RTL_SCALARS:
        ln = grab(lines, sym)
        val = _lit(ln.split(RTL_MARK)[0], sym, RTL_REL)
        # The standing hazard: the RTL decodes CSRs by WORD offset, the doc,
        # the reference and the host by BYTE.  Convert here, once.
        v[key] = val * 4 if key in RTL_CSR_KEYS else val
    for sym, prefix, names in RTL_FIELD_ANCHORS:
        fields = _slices(grab(lines, sym))
        for f_ in names:
            if f_ not in fields:
                sys.stdout.flush()
                raise SystemExit(f"SDMA_BITS: FAIL — {RTL_REL} {sym} has "
                                 f"no {f_} slice")
            v[f"{prefix}_{f_}_hi"], v[f"{prefix}_{f_}_lo"] = fields[f_]
    return v


# ======================================================================
# 2. the reference view — probed through the functions that OWN the layout
# ======================================================================
def _ref_arg0_homes():
    """Bit -> field, read out of sdma_fields() one bit at a time."""
    names = ("kind", "slot", "layer", "head")
    seen = {n: set() for n in names}
    for b in range(32):
        got = SF.sdma_fields(1 << b)
        hot = [n for n, val in zip(names, got) if val]
        assert len(hot) <= 1, f"arg0 bit {b} decodes into {hot}"
        if hot:
            seen[hot[0]].add(b)
    return {n: _home(seen[n], n) for n in names}


LAYER_MAKERS = (("dn_slot", lambda x: SF.layer_word(x, 0, 0, 0), 1),
                ("kv_slot", lambda x: SF.layer_word(0, x, 0, 0), 1),
                ("cv_slot", lambda x: SF.layer_word(0, 0, x, 0), 1),
                ("kv_layer", lambda x: SF.layer_word(0, 0, 0, x), 7))


def _ref_layer_homes():
    """layer_word()'s DECLARED field homes, read out of its docstring.

    The encoder alone cannot prove a 2-bit slot field: `dn_slot` is only
    ever 0 or 1, so bit 1 of `dn_slot[1:0]` is never set by any legal
    call.  The width matters anyway — B15.2 gives the RTL two bits so it
    can REFUSE a slot above 1 (E_LAYER) — so the reference DECLARES the
    layout in its docstring and packs into it in code, and `internal()`
    below requires the code to land inside what the docstring declares.
    """
    homes = _slices(SF.layer_word.__doc__ or "")
    for name, _mk, _hi in LAYER_MAKERS:
        assert name in homes, (
            f"ref/seq_format.layer_word's docstring declares no {name} "
            f"field (B15.2)")
    return {n: homes[n] for n, _m, _h in LAYER_MAKERS}


def _ref_layer_reach():
    """{field: the bits the ENCODER actually sets at every legal value}."""
    out = {}
    for name, mk, hi_val in LAYER_MAKERS:
        bits = set()
        for val in range(1, hi_val + 1):
            bits |= _bits(mk(val))
        out[name] = bits
    return out


def _ref_max(fn, lo=0):
    """The largest value `fn` accepts, counting up from `lo`."""
    n = lo - 1
    for cand in range(lo, 64):
        try:
            fn(cand)
        except AssertionError:
            break
        n = cand
    return n


def load_ref():
    v = {
        "op_sld": SF.OP_L_SLD,
        "op_sst": SF.OP_L_SST,
        "csr_sb_dn": SF.LOFF_SB_DN,
        "csr_sb_kv": SF.LOFF_SB_KV,
        "csr_sb_cv": SF.LOFF_SB_CV,
        "csr_sdma": SF.LOFF_SDMA,
        "csr_sdma_cyc": SF.LOFF_SDMA_CYC,
        "csr_layer": SF.LOFF_LAYER,
        "kind_dn": SF.SDMA_KIND_DN,
        "kind_kv": SF.SDMA_KIND_KV,
        "kind_cv": SF.SDMA_KIND_CV,
        "t_max": SF.STATE_T_MAX,
        "layer_max_dn": _ref_max(lambda L: SF.sdma_arg0(SF.SDMA_KIND_DN, 0, L, 0)),
        "layer_max_cv": _ref_max(lambda L: SF.sdma_arg0(SF.SDMA_KIND_CV, 0, L, 0)),
        "layer_max_kv": _ref_max(lambda L: SF.sdma_arg0(SF.SDMA_KIND_KV, 0, L, 0)),
        "head_max_dn": _ref_max(lambda h: SF.sdma_arg0(SF.SDMA_KIND_DN, 0, 0, h)),
        "head_max_cv": _ref_max(lambda h: SF.sdma_arg0(SF.SDMA_KIND_CV, 0, 0, h)),
        "head_max_kv": _ref_max(lambda h: SF.sdma_arg0(SF.SDMA_KIND_KV, 0, 0, h)),
    }
    # the error table, by name, from the reference's own dict
    for code, name in SF.ERR_CODE.items():
        v["err_" + name.lower()] = code
    for f_, (hi, lo) in _ref_arg0_homes().items():
        v[f"arg0_{f_}_hi"], v[f"arg0_{f_}_lo"] = hi, lo
    for f_, (hi, lo) in _ref_layer_homes().items():
        v[f"layer_{f_}_hi"], v[f"layer_{f_}_lo"] = hi, lo
    return v


# ======================================================================
# 3. the host view
# ======================================================================
def load_host():
    return {
        "csr_sb_dn": HW.L_SB_DN - HW.LB,
        "csr_sb_kv": HW.L_SB_KV - HW.LB,
        "csr_sb_cv": HW.L_SB_CV - HW.LB,
        "csr_sdma": HW.L_SDMA - HW.LB,
        "csr_sdma_cyc": HW.L_SDMA_CYC - HW.LB,
        "csr_layer": HW.L_LAYER - HW.LB,
        "t_max": HW.STATE_T_MAX,
        "shift_dn": _log2(HW.STATE_DN_LAYER, "STATE_DN_LAYER"),
        "shift_kv": _log2(HW.STATE_KV_STRIDE, "STATE_KV_STRIDE"),
        "shift_cv": _log2(HW.STATE_CV_STRIDE, "STATE_CV_STRIDE"),
        "shift_dn_head": _log2(HW.STATE_DN_HEAD, "STATE_DN_HEAD"),
        "shift_kv_exp": _log2(HW.STATE_KV_EXP_OFF, "STATE_KV_EXP_OFF"),
        "dn_blocks": HW.STATE_DN_BLOCKS,
        "kv_blocks": HW.STATE_KV_BLOCKS,
        "cv_blocks": HW.STATE_CV_BLOCKS,
        "dn_heads": HW.STATE_DN_LAYER // HW.STATE_DN_HEAD,
    }


# ======================================================================
# 4. the document view — parsed out of docs/SEQ_ISA.md B15
# ======================================================================
def _b15(text):
    i = text.find("## B15. Layer state in DDR")
    if i < 0:
        raise SystemExit(f"SDMA_BITS: FAIL — {DOC_REL} has no section B15")
    return text[i:]


def _find(sec, pat, name, cast=int, base=10):
    m = re.search(pat, sec)
    if not m:
        raise SystemExit(f"SDMA_BITS: FAIL — {DOC_REL} B15 has no {name} "
                         f"(pattern {pat!r})")
    if cast is int:
        return int(m.group(1), base)
    return m.group(1)


def load_doc():
    with open(DOC, encoding="utf-8") as f:
        sec = _b15(f.read())
    v = {
        "op_sld": _find(sec, r"op\s+(\d+)\s+SLD", "op SLD"),
        "op_sst": _find(sec, r"op\s+(\d+)\s+SST", "op SST"),
        "kind_dn": _find(sec, r"kind:\s*(\d+)\s*DN", "kind DN"),
        "kind_kv": _find(sec, r"kind:\s*\d+\s*DN,\s*(\d+)\s*KV", "kind KV"),
        "kind_cv": _find(sec, r"kind:\s*\d+\s*DN,\s*\d+\s*KV,\s*(\d+)\s*CV",
                         "kind CV"),
        "kind_rsvd": _find(sec, r"KV,\s*\d+\s*CV,\s*(\d+)\s*reserved",
                           "kind reserved"),
        "layer_max_dn": _find(sec, r"layer:\s*DN/CV\s*0\.\.(\d+)", "DN layer max"),
        "layer_max_kv": _find(sec, r"layer:\s*DN/CV\s*0\.\.\d+;\s*KV\s*0\.\.(\d+)",
                              "KV layer max"),
        "shift_dn": _find(sec, r"DN:\s*index\s*=\s*layer\s+shift\s*(\d+)", "DN shift"),
        "shift_kv": _find(sec, r"KV:\s*index\s*=.*?shift\s*(\d+)", "KV shift"),
        "shift_cv": _find(sec, r"CV:\s*index\s*=\s*layer\s+shift\s*(\d+)", "CV shift"),
        "shift_dn_head": _find(sec, r"head h at \+h<<(\d+)", "DN head shift"),
        "kv_exp_mib": _find(sec, r"exponent side array at \+(\d+) MiB",
                            "KV exponent offset"),
        "dn_heads": _find(sec, r"=\s*(\d+) heads x \d+ rows x \d+ B", "DN heads"),
        "dn_rows_per_head": _find(sec, r"=\s*\d+ heads x (\d+) rows x \d+ B",
                                  "DN rows/head"),
        "dn_row_bytes": _find(sec, r"=\s*\d+ heads x \d+ rows x (\d+) B",
                              "DN row bytes"),
        "dn_rows": _find(sec, r"Length: DN (\d+) rows", "DN rows"),
        "cv_rows": _find(sec, r"CV (\d+) rows x \d+ B", "CV rows"),
        "cv_row_bytes": _find(sec, r"CV \d+ rows x (\d+) B", "CV row bytes"),
        "t_max": _find(sec, r"a KV TCNT above (\d+)", "T_MAX"),
        "csr_layer": _find(sec, r"The LAYER CSR \(0x([0-9A-Fa-f]+)\)",
                           "LAYER CSR offset", base=16),
    }
    # B15.1's ARG0 field homes and B15.2's LAYER homes, from the concats
    a0 = _slices(_find(sec, r"arg0=\{([^}]*)\}", "ARG0 concat", cast=str))
    for f_ in ("kind", "slot", "layer", "head"):
        if f_ not in a0:
            raise SystemExit(f"SDMA_BITS: FAIL — {DOC_REL} B15.1 ARG0 concat "
                             f"has no {f_}")
        v[f"arg0_{f_}_hi"], v[f"arg0_{f_}_lo"] = a0[f_]
    lw = _slices(_find(sec, r"\n\s*\{18'b0,([^}]*)\}", "LAYER concat", cast=str))
    for f_ in ("dn_slot", "kv_slot", "cv_slot", "kv_layer"):
        if f_ not in lw:
            raise SystemExit(f"SDMA_BITS: FAIL — {DOC_REL} B15.2 LAYER concat "
                             f"has no {f_}")
        v[f"layer_{f_}_hi"], v[f"layer_{f_}_lo"] = lw[f_]
    # B15.1's head rule: DN and CV must be 0; KV is {kvhead[2:1], kv[0]}
    for kind in ("DN", "CV"):
        _find(sec, r"(" + kind + r") must be 0", f"{kind} head must be 0",
              cast=str)
        v["head_max_" + kind.lower()] = 0
    kvh = _slices(_find(sec, r"KV \{([^}]*)\}", "KV head concat", cast=str))
    for f_ in ("kvhead", "kv"):
        if f_ not in kvh:
            raise SystemExit(f"SDMA_BITS: FAIL — {DOC_REL} B15.1's KV head "
                             f"concat has no {f_}")
        v[f"head_{f_}_hi"], v[f"head_{f_}_lo"] = kvh[f_]
    v["head_max_kv"] = (1 << (v["head_kvhead_hi"] + 1)) - 1
    # B15.3's five byte offsets and B15.4's six error codes
    for key, name in (("csr_sb_dn", "SB_DN"), ("csr_sb_kv", "SB_KV"),
                      ("csr_sb_cv", "SB_CV"), ("csr_sdma", "SDMA"),
                      ("csr_sdma_cyc", "SDMA_CYC")):
        v[key] = _find(sec, r"0x([0-9A-Fa-f]{2})\s+" + name + r"\s", name,
                       base=16)
    for name in ("E_ENV", "E_LAYER", "E_DMA_BASE", "E_DMA_RANGE",
                 "E_DMA_AXI", "E_DMA_COLD"):
        v["err_" + name.lower()] = _find(
            sec, r"0x([0-9A-Fa-f]{2})\s+" + name + r"\s", name, base=16)
    v["shift_kv_exp"] = _log2(v.pop("kv_exp_mib") << 20, "KV exponent offset")
    v["layer_max_cv"] = v["layer_max_dn"]          # B15.1: "DN/CV 0..23"
    # blocks, derived from the doc's own ranges (24 DN/CV layers, 8x4x2 KV)
    v["dn_blocks"] = (v["layer_max_dn"] + 1) * v["dn_heads"]
    v["kv_blocks"] = (v["layer_max_kv"] + 1) * 4 * 2
    v["cv_blocks"] = v["layer_max_dn"] + 1
    return v


# ======================================================================
# 5. the perturbations — the control, applied to the LOADED view
# ======================================================================
PERTURBATIONS = {
    "rtl":       ("rtl", "op_sld", 12,
                  "the RTL's OP_SLD becomes 12 (an occupied opcode)"),
    "rtl-shift": ("rtl", "shift_kv", 20,
                  "the RTL's SDMA_SHIFT_KV becomes 20 (a 1 MiB KV stride)"),
    "rtl-layer": ("rtl", "layer_kv_layer_lo", 4,
                  "the RTL's LAYER kv_layer field moves to [10:4]"),
    "ref":       ("ref", "op_sst", 15, "ref/seq_format.OP_L_SST becomes 15"),
    "host":      ("host", "shift_kv", 20,
                  "sw/hwmap.STATE_KV_STRIDE halves to 1 MiB"),
    "doc":       ("doc", "csr_sdma_cyc", 0x78,
                  "docs/SEQ_ISA.md B15.3 moves SDMA_CYC to 0x78"),
}
# The perturbations that need the RTL view, so --ref-only skips exactly them.
RTL_PERTURBATIONS = tuple(k for k, p in PERTURBATIONS.items() if p[0] == "rtl")


def _apply_perturbation(views, which):
    """isa_bits.py:284's shape: mutate the LOADED view, never the source."""
    if which not in PERTURBATIONS:
        raise SystemExit(f"unknown perturbation {which!r}; choose from "
                         + ", ".join(sorted(PERTURBATIONS)))
    view, key, val, _txt = PERTURBATIONS[which]
    if view not in views:
        raise SystemExit(f"--perturb {which} needs the {view} view "
                         f"(it is skipped in this mode)")
    assert key in views[view], f"{view} view has no {key}"
    views[view][key] = val


# ======================================================================
# 6. the census
# ======================================================================
def census(views, out):
    """Every key defined by more than one view must agree everywhere."""
    keys = sorted({k for v in views.values() for k in v})
    ok = True
    out.write(f"{'constant':22s} " + " ".join(f"{n:>10s}" for n in views) + "\n")
    for k in keys:
        have = {n: v[k] for n, v in views.items() if k in v}
        vals = set(have.values())
        cells = " ".join(f"{_fmt(have[n]):>10s}" if n in have else f"{'-':>10s}"
                         for n in views)
        if len(vals) > 1:
            ok = False
            out.write(f"{k:22s} {cells}   MISMATCH\n")
        elif len(have) < 2:
            out.write(f"{k:22s} {cells}   (one view only)\n")
        else:
            out.write(f"{k:22s} {cells}\n")
    return ok


def _fmt(v):
    return f"{v:#x}" if isinstance(v, int) and v >= 16 else str(v)


def internal(views, out):
    """The doc's own arithmetic, and the host's, must close."""
    ok = True

    def need(cond, msg):
        nonlocal ok
        out.write(f"  {'ok  ' if cond else 'FAIL'} {msg}\n")
        ok = ok and bool(cond)

    d = views.get("doc")
    if d:
        need(d["dn_heads"] * d["dn_rows_per_head"] * d["dn_row_bytes"]
             == 1 << d["shift_dn"],
             f"DN block {d['dn_heads']}x{d['dn_rows_per_head']}x"
             f"{d['dn_row_bytes']} B == 1<<{d['shift_dn']}")
        need(d["dn_rows"] == d["dn_heads"] * d["dn_rows_per_head"],
             f"DN transfer {d['dn_rows']} rows == whole layer (spec A1.1)")
        need(d["dn_rows_per_head"] * d["dn_row_bytes"] == 1 << d["shift_dn_head"],
             f"DN head block == 1<<{d['shift_dn_head']}")
        need(d["cv_rows"] * d["cv_row_bytes"] == 1 << d["shift_cv"],
             f"CV block {d['cv_rows']}x{d['cv_row_bytes']} B == 1<<{d['shift_cv']}")
        need(d["kind_rsvd"] == 3, "kind 3 is the reserved code")
        need((1 << d["shift_kv_exp"]) < (1 << d["shift_kv"]),
             "the KV exponent side array is inside the KV block")
    r = views.get("ref")
    if r:
        reach = _ref_layer_reach()
        for name, _mk, _hi in LAYER_MAKERS:
            hi, lo = r[f"layer_{name}_hi"], r[f"layer_{name}_lo"]
            declared = set(range(lo, hi + 1))
            need(reach[name] <= declared and min(reach[name]) == lo,
                 f"layer_word packs {name} into bits "
                 f"{sorted(reach[name])} inside its declared [{hi}:{lo}]")
    h = views.get("host")
    if h:
        st = HW.plan_state(0)
        need(st["dn"] == 0 and st["kv"] == HW.STATE_DN_BLOCKS * HW.STATE_DN_HEAD
             and st["cv"] == st["kv"] + HW.STATE_KV_BLOCKS * HW.STATE_KV_STRIDE
             and st["end"] == st["cv"] + HW.STATE_CV_BLOCKS * HW.STATE_CV_STRIDE,
             f"plan_state(0) = {{dn:{st['dn']:#x} kv:{st['kv']:#x} "
             f"cv:{st['cv']:#x} end:{st['end']:#x}}}")
        need(all(a % HW.STATE_BASE_UNIT == 0 for a in st.values()),
             f"every region base is {HW.STATE_BASE_UNIT >> 10} KiB aligned")
        need(HW.STATE_DN_BLOCKS * HW.STATE_DN_HEAD == 24 << 20,
             "the DN region is 24 MiB")
        need(HW.STATE_KV_BLOCKS * HW.STATE_KV_STRIDE == 128 << 20,
             "the KV region is 128 MiB")
        need(HW.STATE_CV_BLOCKS * HW.STATE_CV_STRIDE == 3 << 20,
             "the conv region is 3 MiB")
    return ok


# ======================================================================
# 7. the round trips and the RED cases
# ======================================================================
def _raw_arg0(homes, kind, slot, layer, head):
    """Pack ARG0 from the CENSUS-AGREED bit homes, so an out-of-envelope
    value the emitter refuses to build can still be handed to the
    validator.  `sdma_arg0` asserts; that is the point of the RED cases."""
    return ((kind << homes["kind"]) | (slot << homes["slot"])
            | (layer << homes["layer"]) | (head << homes["head"]))


def _stream(a0, op, a1=0, a2=0):
    return [SF.Rec(SF.OP_CSRWR, target=SF.CSR_L_ARG0, imm32=a0),
            SF.Rec(SF.OP_CSRWR, target=SF.CSR_L_ARG1, imm32=a1),
            SF.Rec(SF.OP_CSRWR, target=SF.CSR_L_ARG2, imm32=a2),
            SF.Rec(SF.OP_CMD, target=SF.CSR_L_CMD, imm32=op)]


def roundtrip(out, seed, homes):
    ok = True
    rng = random.Random(seed)
    n = 0
    for _ in range(64):
        kind = rng.choice([SF.SDMA_KIND_DN, SF.SDMA_KIND_KV, SF.SDMA_KIND_CV])
        slot = rng.randint(0, 1)
        layer = rng.randint(0, 7 if kind == SF.SDMA_KIND_KV else 23)
        head = rng.randint(0, 7) if kind == SF.SDMA_KIND_KV else 0
        a0 = SF.sdma_arg0(kind, slot, layer, head)
        got = SF.sdma_fields(a0)
        if got != (kind, slot, layer, head):
            out.write(f"  FAIL sdma round-trip {(kind, slot, layer, head)} "
                      f"-> {a0:#x} -> {got}\n")
            ok = False
        if a0 != _raw_arg0(homes, kind, slot, layer, head):
            out.write(f"  FAIL sdma_arg0 {a0:#x} disagrees with the "
                      f"census bit homes\n")
            ok = False
        # every SLD/SST built by the emitter must PASS the validator
        for op in (SF.OP_L_SLD, SF.OP_L_SST):
            try:
                SF.validate_stream(_stream(a0, op))
            except SF.SeqValidationError as e:
                out.write(f"  FAIL validate_stream refused a legal "
                          f"{('SLD', 'SST')[op - SF.OP_L_SLD]}: {e}\n")
                ok = False
        n += 1
    out.write(f"  sdma_arg0 <-> sdma_fields: {n} random (kind, slot, layer, "
              f"head) sets round-tripped, seed {seed}\n")
    m = 0
    for dn in (0, 1):
        for kv in (0, 1):
            for cv in (0, 1):
                for kvl in range(8):
                    w = SF.layer_word(dn, kv, cv, kvl)
                    fields = {"dn_slot": dn, "kv_slot": kv, "cv_slot": cv,
                              "kv_layer": kvl}
                    for name, val in fields.items():
                        lo = homes[name]
                        wide = homes.get(name + "_w", 1)
                        if (w >> lo) & ((1 << wide) - 1) != val:
                            out.write(f"  FAIL layer_word {fields} -> {w:#x}: "
                                      f"{name} does not read back\n")
                            ok = False
                    m += 1
    out.write(f"  layer_word: {m} (dn, kv, cv, kv_layer) sets round-tripped "
              f"through the census bit homes\n")
    return ok


RED_CASES = [
    ("kind 3 (reserved)",          dict(kind=3, slot=0, layer=0, head=0)),
    ("DN head 1 (must be 0)",      dict(kind=0, slot=0, layer=0, head=1)),
    ("KV layer 8 (max 7)",         dict(kind=1, slot=0, layer=8, head=0)),
    ("CV head 1 (must be 0)",      dict(kind=2, slot=0, layer=0, head=1)),
    ("arg1 != 0 (reserved)",       dict(kind=0, slot=0, layer=0, head=0, a1=1)),
]


def red_cases(out, homes):
    """Each of B15.1's five envelope violations must be REFUSED."""
    ok = True
    for name, case in RED_CASES:
        kw = dict(case)
        a1 = kw.pop("a1", 0)
        a0 = _raw_arg0(homes, **kw)
        for op, opname in ((SF.OP_L_SLD, "SLD"), (SF.OP_L_SST, "SST")):
            try:
                SF.validate_stream(_stream(a0, op, a1=a1))
                out.write(f"  {opname} {name:28s} arg0={a0:#06x} "
                          f"ACCEPTED — CONTROL FAILED\n")
                ok = False
            except SF.SeqValidationError as e:
                out.write(f"  {opname} {name:28s} arg0={a0:#06x} REFUSED "
                          f"({str(e).split(': ', 1)[-1]})\n")
    return ok


# ======================================================================
# 8. the run
# ======================================================================
def run(ref_only=False, perturb=None, seed=20260904, out=sys.stdout):
    tag = "SDMA_BITS(ref-only)" if ref_only else "SDMA_BITS"
    views = {}
    if not ref_only:
        views["rtl"] = load_rtl()
    views["ref"] = load_ref()
    views["host"] = load_host()
    views["doc"] = load_doc()
    if perturb:
        _apply_perturbation(views, perturb)
        out.write(f"PERTURBED {perturb}: {PERTURBATIONS[perturb][3]}\n\n")
    out.write("== 1/3 the census: every constant, every view that names it\n")
    ok = census(views, out)
    out.write("\n== 2/3 the arithmetic each document does on its own\n")
    ok &= internal(views, out)
    # the bit homes the round trips pack against: the census has just
    # required every view to agree, so any of them is THE layout.
    ref = views["ref"]
    homes = {f: ref[f"arg0_{f}_lo"] for f in ("kind", "slot", "layer", "head")}
    for f_ in ("dn_slot", "kv_slot", "cv_slot", "kv_layer"):
        homes[f_] = ref[f"layer_{f_}_lo"]
        homes[f_ + "_w"] = ref[f"layer_{f_}_hi"] - ref[f"layer_{f_}_lo"] + 1
    out.write("\n== 3/3 the round trips, and B15.1's envelope refused\n")
    ok &= roundtrip(out, seed, homes)
    ok &= red_cases(out, homes)
    out.write(f"\n{tag}: " + ("PASS" if ok else "FAIL") + "\n")
    return ok


def control(ref_only, seed, out=sys.stdout):
    """The instrument's own control: unperturbed PASSES, and every
    perturbation of every loaded view is CAUGHT.  A census that cannot
    fail proves nothing (isa_bits.py:933)."""
    buf = io.StringIO()
    base = run(ref_only=ref_only, seed=seed, out=buf)
    out.write(f"{'(unperturbed)':10s} {'the census as it stands':52s} "
              + ("PASS\n" if base else "FAIL — the gate itself is RED\n"))
    if not base:
        out.write(buf.getvalue())
    names = [n for n in sorted(PERTURBATIONS)
             if not (ref_only and n in RTL_PERTURBATIONS)]
    bad = []
    for name in names:
        b = io.StringIO()
        try:
            passed = run(ref_only=ref_only, perturb=name, seed=seed, out=b)
        except SystemExit as e:                            # noqa: PERF203
            passed = False
            b.write(f"  (refused with SystemExit: {e})\n")
        out.write(f"{name:10s} {PERTURBATIONS[name][3]:52s} "
                  + ("CAUGHT\n" if not passed else "MISSED — CONTROL FAILED\n"))
        if passed:
            bad.append(name)
            out.write(b.getvalue())
    tag = "SDMA_CONTROL(ref-only)" if ref_only else "SDMA_CONTROL"
    ok = base and not bad
    out.write(f"\n{tag}: " + ("PASS (the gate holds and every perturbation "
                              "is CAUGHT)" if ok
                              else f"FAIL — base={base} missed={bad}") + "\n")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ref-only", action="store_true",
                    help="skip the RTL half (RED until Task S2 lands it)")
    ap.add_argument("--perturb", metavar="VIEW", choices=sorted(PERTURBATIONS),
                    help="flip one constant in that view; expected CAUGHT "
                         "(rc 0 means the control fired)")
    ap.add_argument("--control", action="store_true",
                    help="the unperturbed run plus every perturbation")
    ap.add_argument("--seed", type=int, default=20260904)
    a = ap.parse_args()
    if a.control:
        sys.exit(0 if control(a.ref_only, a.seed) else 1)
    if a.perturb:
        caught = not run(ref_only=a.ref_only, perturb=a.perturb, seed=a.seed)
        tag = "SDMA_BITS(ref-only)" if a.ref_only else "SDMA_BITS"
        print(f"{tag}, perturb={a.perturb}: "
              + ("CAUGHT" if caught else "MISSED — CONTROL FAILED"))
        sys.exit(0 if caught else 1)
    sys.exit(0 if run(ref_only=a.ref_only, seed=a.seed) else 1)


if __name__ == "__main__":
    main()
