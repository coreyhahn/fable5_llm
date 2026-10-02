#!/usr/bin/env python3
"""t3_audit.py — the R-c weight-address audit at PRODUCTION shape.

    t3_audit.py <seq-prefix> [<seq-prefix> ...]

For each artifact: plan the pack the way the stream says it was packed
(`sw/seq_run.plan_weights_for`), then require that on EVERY channel the byte
ranges the host writes are EXACTLY the ranges that channel's engine reads
(`sw/seq_run.audit_weight_ranges`) — and that the same audit FAILS on three
mutated copies of the stream.

WHY EQUALITY, AND WHY MUTATIONS.  The R-c review showed that the `.txt`-vs-
`.seq` replay gate does NOT prove per-channel weight placement: a systematic
base shift passes it silently, and so does forcing every interleaved chunk to
packed row 0 (the LM head's y32 lives in the excluded staging window and
AMAX32 is strictly-greater, so duplicated rows tie instead of diverging).
A containment check ("every MVGO lands inside something the host wrote") does
not see the second one either.  Range EQUALITY plus a mutation kill does, and
the same functions run inside `seq_run.py --selftest` on every artifact, so
this file is the production-shape instance of a permanent gate, not a
one-off.

Exit 0 only if every artifact audits clean AND every applicable mutation is
killed.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (os.path.join(_REPO, "sw"), os.path.join(_REPO, "ref")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import seq_format as SF                                        # noqa: E402
import seq_run as SR                                           # noqa: E402

MUTATIONS = (("+32 KiB base shift", SR._mut_shift),
             ("ILV chunks collapsed to packed row 0", SR._mut_ilv_zero),
             ("repacked image addressed by GLOBAL row", SR._mut_global_row))


def audit(prefix):
    art = SR.Artifacts(prefix)
    meta = art.meta
    nch = int(meta.get("nch", 1))
    wchans = list(range(nch)) if nch > 1 else [int(meta.get("chan", 0))]
    wbase_of, wtop = SR.plan_weights_for(art.manifest, art.wdir, meta)
    rep = SR.is_repacked(meta)
    print(f"=== {prefix}")
    print(f"    {len(art.manifest)} images, {art.nrec} records, nch={nch}, "
          f"repack={rep}, tops {SR.fmt_top(wtop)}")
    SR.check_weight_plan(meta, wbase_of, art.manifest)
    n = SR.check_mvgo_targets(art.recs, wbase_of, art.manifest, meta)
    print(f"    stream plan == host pack, {n} MVGO WBASEs row-aligned "
          f"inside a packed image on their OWN channel")
    a = SR.audit_weight_ranges(art.recs, art.manifest, wbase_of, nch,
                               wchans, meta)
    for c in a["chans"]:
        print(f"    chan {c}: host spans == engine spans, "
              f"{a['host_bytes'][c] / 2**20:8.2f} MiB")
    ok = a["ok"] and len(a["rows"]) == a["mvgo"]
    print(f"    RANGE EQUALITY: {'PASS' if ok else 'FAIL ' + str(a['mismatch'])}"
          f"  ({a['mvgo']} MVGOs resolved to global rows)")
    # the ILV images, in GLOBAL row terms (what a repack must preserve)
    wl = meta.get("weight_layout") or {}
    depth = int(wl.get("chunk_rows", SF.CHUNK_ROWS))
    for w in sorted(wl.get("ilv_wids", [])):
        hs = sorted({(h["chan"], h["row"]) for h in a["rows"]
                     if h["wid"] == w})
        ilv_ok = (hs and all(c == (row // depth) % nch for (c, row) in hs)
                  and sorted(r for _c, r in hs)
                  == [j * depth for j in range(len(hs))])
        ok &= bool(ilv_ok)
        print(f"    wid {w} (ILV, {len(hs)} chunks of {depth}): chunk j -> "
              f"chan j%{nch}, every row once: "
              f"{'PASS' if ilv_ok else 'FAIL'}   first {hs[:4]}")
    for name, mut in MUTATIONS:
        bad = mut(art.recs, art.manifest, wbase_of, nch, wchans, meta)
        if bad is None:
            print(f"    mutation {name:<42s} n/a for this stream")
            continue
        killed = not SR.audit_weight_ranges(bad, art.manifest, wbase_of, nch,
                                            wchans, meta)["ok"]
        ok &= killed
        print(f"    mutation {name:<42s} "
              f"{'KILLED' if killed else 'SURVIVED — AUDIT IS BLIND'}")
    return ok


def main(argv):
    if not argv:
        raise SystemExit(__doc__.strip().splitlines()[2])
    ok = True
    for p in argv:
        ok &= audit(p)
        print()
    print("T3 AUDIT PASS" if ok else "T3 AUDIT FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
