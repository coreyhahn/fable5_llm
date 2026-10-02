#!/usr/bin/env python3
"""sr11b_r2_check.py — Task SR11b: an INDEPENDENT admission check of the
emitted r2 streams (ref/scripts/reorder_e4.py --rtl r2), separate from the
pass that wrote them.

    /home/cah/.venv/bin/python evidence/qwen9b/sr/sr11b_r2_check.py \
        model_9b_s1_reordB_r2 [model_9b_s2_reordB_r2 ...]

Per stem (tb/scripts/w9/<stem>.e4): the .seq's sha256 against its own
manifest; seq_format.validate_stream at caps {R1,R2} (must pass), at {R1}
and at {} (must be REFUSED — an R1 bitstream ignores MOVX target and drops
SHAPE 29/30, build_041/042 do both: R2 is NOT fail-closed, SEQ_ISA v2.3
B17.2); the pass's range-aware hazard assert; the bank fields by kind; the
manifest's informational seq_isa / caps.  Read-only; stdout only.  Run ON
SNOKE through evidence/qwen9b/sr/sr_run.sh.
"""
import collections
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for p in (os.path.join(REPO, "ref"), os.path.join(REPO, "ref", "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import seq_format as SF                      # noqa: E402
import reorder_e4 as RE                      # noqa: E402

W9 = os.path.join(REPO, "tb", "scripts", "w9")


def at(recs, caps):
    try:
        SF.validate_stream(recs, caps=frozenset(caps))
        return "VALID"
    except SF.SeqValidationError as e:
        return f"REFUSED ({str(e)[:90]})"


def parse(argv):
    caps, want, stems = "R1,R2", None, []
    it = iter(argv)
    for a in it:
        if a == "--caps":
            caps = next(it)
        elif a == "--want-manifest-caps":
            want = next(it)
        else:
            stems.append(a)
    cs = frozenset(x for x in caps.split(",") if x)
    ws = sorted(x for x in (want if want is not None else caps).split(",")
                if x)
    return cs, ws, stems


def r3_extra(recs, cs):
    """R3-5 ("flags, not copies"): `--caps R1,R2,R3` names the set the
    stream must be VALID at (default R1,R2 — today's checks and output,
    unchanged).  With a non-default set the stream must be REFUSED at EVERY
    proper subset of it, and, when R3 is in the set, the refusal at the set
    minus R3 must name the BROADCAST (B17.3: an r3 stream's bank fields alone
    would pass there).  `--want-manifest-caps` (default: the --caps list) is
    the manifest caps the check requires.  A broadcast MOVX is listed as
    "MOVX(bcast) word N".  -> ok."""
    import itertools
    ok = True
    for k in range(len(cs) - 1, -1, -1):
        for sub in itertools.combinations(sorted(cs), k):
            v = at(recs, sub)
            good = v.startswith("REFUSED")
            if "R3" in cs and frozenset(sub) == cs - {"R3"}:
                good &= "BROADCAST" in v
            print(f"    caps {{{','.join(sub)}}}: {v}"
                  f"{'' if good else '   <-- WANTED REFUSED'}")
            ok &= good
    return ok


def main():
    ok = True
    cs, want_caps, stems = parse(sys.argv[1:])
    default = cs == frozenset({"R1", "R2"})
    for stem in stems:
        pre = os.path.join(W9, stem + ".e4")
        stream = open(pre + ".seq", "rb").read()
        man = json.load(open(pre + ".seq.json"))
        sha = hashlib.sha256(stream).hexdigest()
        recs = SF.unpack_stream(stream)
        print(f"=== {stem}: {len(recs)} records, sha256 {sha} "
              f"({'= manifest' if sha == man['stream_sha256'] else 'MANIFEST MISMATCH'})")
        if default:
            v12, v1, v0 = at(recs, {"R1", "R2"}), at(recs, {"R1"}), at(recs, ())
            print(f"    caps {{R1,R2}}: {v12}")
            print(f"    caps {{R1}}   : {v1}")
            print(f"    caps {{}}     : {v0}")
        else:
            v12 = at(recs, cs)
            print(f"    caps {{{','.join(sorted(cs))}}} (VALID wanted): {v12}")
            v1 = v0 = "REFUSED" if r3_extra(recs, cs) else "NOT REFUSED"
        try:
            h = RE.assert_no_pending_hazard(recs, stem)
            hz = f"PASS (MOVX {h['MOVX']}, MVGO {h['MVGO']}, MOVY {h['MOVY']}, FENCE {h['FENCE']})"
            hok = True
        except RE.HazardError as e:
            hz, hok = f"FAIL {e}", False
        print(f"    range-aware hazard assert: {hz}")
        bk = collections.Counter()
        for r in recs:
            if r.opcode == SF.OP_MOVX:
                bk[f"MOVX{'(bcast)' if r.chan == SF.MOVX_BCAST else ''} word {r.target}"] += 1
            elif r.opcode == SF.OP_MVGO:
                bk[f"MVGO XBANK {(r.imm32 >> 29) & 1} RBANK {(r.imm32 >> 30) & 1}"] += 1
            elif r.opcode == SF.OP_MOVY:
                bk[f"MOVY row {r.target >> 4}"] += 1
            elif r.opcode == SF.OP_FENCE:
                bk[f"FENCE mask {r.target & 0xF:04b}"] += 1
        print("    fields: " + ", ".join(f"{k} x{v}" for k, v in sorted(bk.items())))
        print(f"    manifest (informational): seq_isa {man.get('seq_isa')}, "
              f"caps {man.get('caps')}, rtl {man['sv1_reorder'].get('rtl')}")
        good = (sha == man["stream_sha256"] and v12 == "VALID"
                and v1.startswith("REFUSED") and v0.startswith("REFUSED")
                and hok and man.get("caps") == want_caps)
        print(f"    -> {'PASS' if good else 'FAIL'}")
        ok &= good
    print("SR11B_R2_CHECK: " + ("PASS" if ok else "FAIL"))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
