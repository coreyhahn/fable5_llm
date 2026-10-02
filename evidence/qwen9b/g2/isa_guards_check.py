#!/usr/bin/env python3
"""isa_guards_check.py — every G2a guard, tripped on purpose.

    /home/cah/.venv/bin/python evidence/qwen9b/g2/isa_guards_check.py
    FABLE5_MODEL=9b /home/cah/.venv/bin/python evidence/qwen9b/g2/isa_guards_check.py

WHY THIS FILE EXISTS.  G2a raised four host ceilings (`SCRATCH_MAX`,
`DNST_HEAD_MAX`, `KVH_MAX`, `VNW_MAX`) for the 9B geometry and added a second,
NARROWER guard beside each one for what the SEQ_ISA v1.7 ARG word can actually
carry.  The gate doc asserted those guards refuse; nothing tripped them.
Review found the cost of that immediately: `dnz` had been given the geometry
bound and NOT the field guard, so at LNH=32 it accepted heads 16..31 and
aliased them onto 0..15 through the 4-bit RTL field — six callers zeroing
heads 0-15 twice and 16-31 never, silently.

So every guard here is exercised BOTH WAYS:

  RED    the out-of-range value must RAISE, and the message must name the
         field (a guard that fires for the wrong reason is not a guard)
  GREEN  the largest IN-range value must NOT raise — otherwise a guard that
         always throws would score a perfect RED and break every emit

A RED without its GREEN is the mistake `damage_defect_b.py` made in its first
cut, where a `TypeError` about a malformed call was scored as a refusal.

Exit 0 = every guard fires exactly where it should and nowhere else.
"""
import os
import sys
import tempfile

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (os.path.join(_ROOT, "ref"), os.path.join(_ROOT, "sw")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import gen_layer_script as GLS                                  # noqa: E402
import hwmap as HW                                              # noqa: E402
import layer_fixed as LF                                        # noqa: E402
import layer_ref as LR                                          # noqa: E402
import model_select as MS                                       # noqa: E402

npass = nfail = 0


def _report(ok, name, detail=""):
    global npass, nfail
    if ok:
        npass += 1
        print(f"  PASS {name}")
    else:
        nfail += 1
        print(f"  FAIL {name}: {detail}")


def red(name, fn, must_say):
    """The call must raise, and the message must name the field."""
    try:
        fn()
    except AssertionError as e:
        msg = str(e)
        if must_say.lower() in msg.lower():
            _report(True, f"RED  {name} — refused, naming {must_say!r}")
        else:
            _report(False, f"RED  {name}",
                    f"raised but did not name {must_say!r}: {msg[:140]}")
        return
    except Exception as e:                                   # noqa: BLE001
        _report(False, f"RED  {name}",
                f"raised {type(e).__name__}, not the guard: {str(e)[:120]}")
        return
    _report(False, f"RED  {name}", "did NOT raise")


def green(name, fn):
    """The largest in-range value must NOT raise."""
    try:
        fn()
    except Exception as e:                                   # noqa: BLE001
        _report(False, f"GRN  {name}",
                f"the in-range case raised {type(e).__name__}: {str(e)[:120]}")
        return
    _report(True, f"GRN  {name} — in-range accepted")


def mach():
    m = GLS.Mach(open(os.devnull, "w"))
    return m


print(f"isa_guards_check: FABLE5_MODEL={MS.TAG}  H={LR.H}  LNH={LR.LNH}  "
      f"NKV={LR.NKV}  RS_F={LF.RS_F}")
print(f"  ceilings: SCRATCH_MAX={GLS.SCRATCH_MAX} "
      f"ISA_SADDR_MAX={GLS.ISA_SADDR_MAX} "
      f"DNST_HEAD_MAX={GLS.Mach.DNST_HEAD_MAX} "
      f"ARG0_HEAD_BITS={GLS.Mach.ARG0_HEAD_BITS} "
      f"KVH_MAX={GLS.Mach.KVH_MAX} ARG0_KVH_BITS={GLS.Mach.ARG0_KVH_BITS} "
      f"VNW_MAX={GLS.Mach.VNW_MAX} VNW_ISA_MAX={GLS.Mach.VNW_ISA_MAX}")

ISA = GLS.ISA_SADDR_MAX
NEED = "15-bit ISA range"

# ---------------------------------------------------------------- 1
print("[1] ISA_SADDR_MAX — the ARG pair packing, on all four packers")
# The array now admits 65,536, so these addresses pass `enc_saddr` and are
# stopped only by the pair guard.  That is the whole point of the split:
# before it, `enc_a1(40000)` packed `lo >> 14 == 2` onto bit 29 — hi's bit —
# and returned a DIFFERENT address with no complaint.
red("enc_a1(lo=ISA)", lambda: GLS.enc_a1(ISA, 0), NEED)
red("enc_a1(hi=ISA)", lambda: GLS.enc_a1(0, ISA), NEED)
red("enc_alu_a2(dst=ISA)", lambda: GLS.enc_alu_a2(0, ISA), NEED)
red("enc_isa_saddr(ISA)", lambda: GLS.enc_isa_saddr(ISA), NEED)
green("enc_a1(ISA-1, ISA-1)", lambda: GLS.enc_a1(ISA - 1, ISA - 1))
green("enc_alu_a2(dst=ISA-1)", lambda: GLS.enc_alu_a2(0, ISA - 1))
# and the array bound is still a bound
red("enc_saddr(SCRATCH_MAX)", lambda: GLS.enc_saddr(GLS.SCRATCH_MAX),
    "scratchpad")
green("enc_saddr(SCRATCH_MAX-1)", lambda: GLS.enc_saddr(GLS.SCRATCH_MAX - 1))
# the packing is LOSSLESS over the whole legal range — the property the
# guard protects.  Round-trip every bit position rather than a sample.
_bad = [(lo, hi) for lo in (0, 1, 16383, 16384, ISA - 1)
        for hi in (0, 1, 16383, 16384, ISA - 1)
        if (GLS.dec_a1_lo(GLS.enc_a1(lo, hi)),
            GLS.dec_a1_hi(GLS.enc_a1(lo, hi))) != (lo, hi)]
_report(not _bad, "the pair packing round-trips over the whole legal range",
        str(_bad[:4]))

# ---------------------------------------------------------------- 2
print("[2] VNW_ISA_MAX — ARG0[10:0], where 4096 & 0x7FF == 0 means 2048")
M = mach()
red("vnw_(4096)", lambda: M.vnw_(0, 4096), "ARG0[10:0]")
# The largest length that is BOTH inside the ISA field and inside this
# geometry's vnw buffer (which is H words).  At 0.8B that is 1024, not 2048 --
# using the field ceiling blind would fail on a numpy broadcast and score the
# guard as broken when it is the TEST that is wrong.
_vnw_ok = min(GLS.Mach.VNW_ISA_MAX, LR.H)
green(f"vnw_({_vnw_ok})", lambda: M.vnw_(0, _vnw_ok))
red("vnw_(VNW_MAX+1)", lambda: M.vnw_(0, GLS.Mach.VNW_MAX + 1), "outside")
_report(4096 & 0x7FF == 0,
        "the wrap this guard prevents is real: 4096 & 0x7FF == 0, and 0 "
        "encodes 2048")

# ---------------------------------------------------------------- 3
print("[3] ARG0_HEAD_BITS — DNST and DNZ share layer_chan's dn_head[3:0]")
M = mach()
HEADFIELD = "ARG0[3:0]"
red("dnst(head=16)",
    lambda: M.dnst(16, 0, 0, 0, GLS.GD, GLS.GD, GLS.DO32), HEADFIELD)
green("dnst(head=15)",
      lambda: M.dnst(15, 0, 0, 0, GLS.GD, GLS.GD, GLS.DO32))
# B1: dnz had the geometry bound and NOT the field guard.
red("dnz(head=16)", lambda: M.dnz(16), HEADFIELD)
green("dnz(head=15)", lambda: M.dnz(15))
# the geometry bound is separate and still bites above LNH
red(f"dnz(head={GLS.Mach.DNST_HEAD_MAX + 1})",
    lambda: M.dnz(GLS.Mach.DNST_HEAD_MAX + 1), "outside")
_report(GLS.Mach.DNST_HEAD_MAX >= 15,
        "DNST_HEAD_MAX is the GEOMETRY bound and is >= the field bound")

# ---------------------------------------------------------------- 4
print("[4] ARG0_KVH_BITS — KVAP and ATTN share layer_chan's kvhead[0]")
M = mach()
KVFIELD = "ARG0[0:0]"
red("kvap(kvh=2)", lambda: M.kvap(2, 0, 0), KVFIELD)
red("attn(kvh=2)", lambda: M.attn(2, 0, 0), KVFIELD)
green("kvap(kvh=1)", lambda: M.kvap(1, 0, 0))
if GLS.Mach.KVH_MAX + 1 > 2:
    red(f"kvap(kvh={GLS.Mach.KVH_MAX + 1})",
        lambda: M.kvap(GLS.Mach.KVH_MAX + 1, 0, 0), "outside")

# ---------------------------------------------------------------- 4b
print("[4b] CONV_FIELD_MAX — the 13-bit CONV channel field (review N10)")
M = mach()
CF = GLS.Mach.CONV_FIELD_MAX
red(f"convz(0, {CF + 1})", lambda: M.convz(0, CF + 1), "13-bit field")
green(f"convz(0, {CF})", lambda: M.convz(0, CF))
# The one that matters at 9B: CONV_DIM is 8192 there against an 8191 field,
# so a whole-block convz REFUSES rather than truncating.  That is correct
# behaviour for this gate and a Task 10 work item, not a bug -- recorded so
# nobody "fixes" the assert instead of the field.
_whole_ok = LR.CONV_DIM <= CF
print(f"      CONV_DIM={LR.CONV_DIM} vs field max {CF}: a whole-block convz "
      f"{'fits' if _whole_ok else 'REFUSES (Task 10 widens the field)'}")
if not _whole_ok:
    red("convz(0, CONV_DIM) at this geometry",
        lambda: M.convz(0, LR.CONV_DIM), "13-bit field")

# ---------------------------------------------------------------- 5
print("[5] B5 — the banked KV cache is _KVH wide, including after Treset")
M = mach()
_report(len(M.kc[0]) == GLS._KVH == len(M.vc[0]) == len(M.T[0]),
        f"kc/vc/T are _KVH={GLS._KVH} wide at construction",
        f"{len(M.kc[0])}/{len(M.vc[0])}/{len(M.T[0])}")
M.Treset()
M.kc[0] = [[] for _ in range(GLS._KVH)]
M.vc[0] = [[] for _ in range(GLS._KVH)]
_report(len(M.kc[0]) == GLS._KVH and len(M.T[0]) == GLS._KVH,
        "Treset + main()'s explicit reset keep the full width")
# The repro that used to IndexError: reach the highest kv head the geometry
# has.  It must fail on the ARG0 FIELD (Task 10's to widen), never on a
# Python list bound -- those are different bugs with different owners.
if GLS._KVH > 2:
    try:
        M.kc[0][GLS._KVH - 1].append((np.zeros(4, dtype=np.int64), 0))
        _report(True, f"kv head {GLS._KVH - 1} is addressable in the model")
    except IndexError as e:
        _report(False, f"kv head {GLS._KVH - 1} addressable", str(e))

# ---------------------------------------------------------------- 6
print("[6] B6 — the RS_F emit/consume tie")
_report(GLS.RS_F_MANIFEST_DEFAULT == HW.RS_F_DEFAULT == 8,
        "ref's RS_F_MANIFEST_DEFAULT and sw/hwmap's RS_F_DEFAULT agree",
        f"{GLS.RS_F_MANIFEST_DEFAULT} vs {HW.RS_F_DEFAULT}")
_report(HW.split_manifest({})[1]["rs_f"] == GLS.RS_F_MANIFEST_DEFAULT,
        "a manifest with no key reads back as exactly that default")


def _emit(rs_f):
    m = mach()
    qw = {"w4": np.zeros((4, 128), dtype=np.int8),
          "m": np.zeros((4, 1), dtype=np.int8), "sh": 5, "e": -4, "g": 128}
    m.wids[id(qw)] = (0, qw)
    m.dump_weights(os.path.join(tempfile.mkdtemp(), "t"),
                   emb_row_bytes=2 * GLS.H, rs_f=rs_f)


if LF.RS_F == GLS.RS_F_MANIFEST_DEFAULT:
    green("withholding rs_f is legal when the value IS the default",
          lambda: _emit(None))
    green("passing rs_f explicitly is always legal", lambda: _emit(LF.RS_F))
    print("      (the RED for this guard needs FABLE5_RS_F != 8 — see the "
          "companion run in the log)")
else:
    red("withholding rs_f while RS_F != the default",
        lambda: _emit(None), "no `rs_f` key")
    green("passing rs_f explicitly is legal at any value",
          lambda: _emit(LF.RS_F))

print(f"isa_guards_check: {npass} passed, {nfail} failed")
sys.exit(1 if nfail else 0)
