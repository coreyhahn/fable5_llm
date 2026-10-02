#!/usr/bin/env python3
"""g6_residency.py — the WHOLE-PACK residency audit, and the contrived miss.

    # read every resident byte back and compare
    python3 evidence/qwen9b/g6/g6_residency.py --prefix tb/scripts/w9/model_9b_s1.e4 --audit

    # damage exactly one piece, inside the witness window, and say so
    python3 evidence/qwen9b/g6/g6_residency.py --prefix ... --corrupt-wid 248

    # put that one piece back
    python3 evidence/qwen9b/g6/g6_residency.py --prefix ... --repair-wid 248

WHY THIS FILE EXISTS.  `sw/chat_seq.py:1086-1093` says it in its own words:
the witness probe SAMPLES — 4 KiB of a piece that can be megabytes, ~0.19 %
— and R-d measured the hit rate at roughly ONE DETECTION PER THREE DAMAGED
PIECES (`evidence/qwen2b/rd/RD_GATE.md` §4.2, where a session ran on a
61.3 MiB-stale LM head and answered with the wrong token).  RD_GATE
follow-on 2 asks for that sample to be REPLACED by a whole-pack hash rather
than made finer.  `--audit` is that hash: it reads back every byte the host
wrote — every weight PIECE where its own channel holds it, the embedding
table, and every conv image of the DDR state region — compares each piece
against the artifact, and folds all of them into one pack digest.  It is a
measurement, not a sample: there is no offset for damage to hide at.

`--corrupt-wid` is the OTHER half the plan asks for.  `reupload_set`'s
whole-pack escalation branch is SELFTEST-PROVEN ONLY — "on hardware every
observed miss set has been all-187, which makes the branch a no-op there
and unproven" (`sw/chat_seq.py:1194-1196`).  9B is the first real chance to
fire it, and the plan says to contrive that deliberately rather than hope
for it.  So this writes a known pattern over ONE piece of ONE image, AT THE
OFFSET `chat_seq._witness` PROBES, so the probe must see it; the audit then
sees it too, from a different direction and with no sampling.

BOARD SAFETY.  Never programs the FPGA, never touches flash, never runs
sudo, never calls pcie_helper.sh.  It takes the same shared board lock every
other tool takes.  `--corrupt-wid` REFUSES without --i-mean-it, prints
exactly what it wrote and where, and `--repair-wid` restores the piece from
the artifact and re-verifies it.
"""
import argparse
import hashlib
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
for _p in (os.path.join(_ROOT, "sw"), os.path.join(_ROOT, "ref")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import board_lock as BL                                        # noqa: E402
import hwmap as HW                                             # noqa: E402
import seq_run as SR                                           # noqa: E402
from chat_seq import (_witness, WITNESS_BYTES,                  # noqa: E402
                      build_residency_manifest, probe_residency,
                      reupload_set)

CHUNK = 32 << 20          # readback granularity


def _pieces(art, plan):
    """Every host-written range, as (kind, name, chan, addr, path, off, len).

    The weight pieces are `plan_weight_split`'s — the SAME placement the
    stream's MVGO WBASEs point at, so a board holding these weights under a
    different placement reads as absent, which is the point.
    """
    wbase_of, _ = SR.plan_weights_for(art.manifest, art.wdir, art.meta)
    splits = SR.plan_weight_split(art.manifest, wbase_of, plan["nch"],
                                  plan["weight_chans"], art.meta)
    out = []
    for s in splits:
        m = art.manifest[str(s["wid"])]
        out.append(("weight", f"{m['file']}@c{s['chan']}r{s['r0']}",
                    s["chan"], s["local_addr"],
                    os.path.join(art.wdir, m["file"]),
                    s["byte_off"], s["byte_len"], s["wid"]))
    st = art.state
    if st is not None:
        chan = st["cv"] >> 32
        for ci in (art.conv_images or []):
            out.append(("conv", f"conv[L{ci['layer']}]", chan,
                        (st["cv"] & 0xFFFF_FFFF)
                        + int(ci["layer"]) * HW.STATE_CV_STRIDE,
                        os.path.join(art.wdir, ci["file"]), 0,
                        int(ci["bytes"]), -2))
    if art.embf:
        out.append(("emb", "embedding", None, plan["emb_base"], art.embf, 0,
                    os.path.getsize(art.embf), -1))
    return out


def audit(dev, pieces, log=print):
    """Read EVERY host-written byte back; per-piece verdict + one pack sha."""
    pack_want = hashlib.sha256()
    pack_got = hashlib.sha256()
    bad, nby, t0 = [], 0, time.monotonic()
    for kind, name, chan, addr, path, off, ln, wid in pieces:
        hw, hg = hashlib.sha256(), hashlib.sha256()
        with open(path, "rb") as f:
            f.seek(off)
            done = 0
            while done < ln:
                n = min(CHUNK, ln - done)
                want = f.read(n)
                got = (dev.dma_read(addr + done, n) if chan is None
                       else dev.dma_read_chan(chan, addr + done, n))
                hw.update(want)
                hg.update(got)
                pack_want.update(want)
                pack_got.update(got)
                done += n
                nby += n
        if hw.digest() != hg.digest():
            bad.append({"kind": kind, "name": name, "wid": wid,
                        "chan": chan, "addr": addr, "bytes": ln,
                        "want": hw.hexdigest()[:16], "got": hg.hexdigest()[:16]})
    dt = time.monotonic() - t0
    nw = sum(1 for p in pieces if p[0] == "weight")
    nc = sum(1 for p in pieces if p[0] == "conv")
    ne = sum(1 for p in pieces if p[0] == "emb")
    log(f"  WHOLE-PACK AUDIT  {len(pieces)} pieces ({nw} weight + {nc} conv "
        f"+ {ne} emb), {nby / 2**20:.0f} MiB read back in {dt:.1f} s "
        f"({nby / 2**20 / dt:.0f} MiB/s)")
    log(f"  pack sha256 want  {pack_want.hexdigest()}")
    log(f"  pack sha256 got   {pack_got.hexdigest()}")
    ok = pack_want.digest() == pack_got.digest()
    log(f"  PACK {'IDENTICAL' if ok else 'DIFFERS'}   "
        f"{len(bad)} piece(s) MISS of {len(pieces)}")
    for b in bad[:16]:
        log(f"    ! {b['kind']} {b['name']} chan={b['chan']} "
            f"addr={b['addr']:#x} {b['bytes']} B: want {b['want']} "
            f"got {b['got']}")
    return {"pieces": len(pieces), "bytes": nby, "seconds": round(dt, 1),
            "pack_sha256_want": pack_want.hexdigest(),
            "pack_sha256_got": pack_got.hexdigest(),
            "identical": ok, "miss": bad}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--base", default=None)
    ap.add_argument("--dev", default="/dev/xdma0")
    ap.add_argument("--chan", type=int, default=0)
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--witness-probe", action="store_true",
                    help="drive chat_seq's OWN R-d witness sampler and its "
                         "reupload_set escalation against this board")
    ap.add_argument("--corrupt-wid", type=int, default=None,
                    help="damage ONE piece of this image, at the offset "
                         "chat_seq._witness probes")
    ap.add_argument("--repair-wid", type=int, default=None,
                    help="rewrite every piece of this image from the "
                         "artifact and verify it")
    ap.add_argument("--i-mean-it", action="store_true")
    ap.add_argument("--json", default=None)
    BL.add_lock_args(ap)
    a = ap.parse_args(argv)

    try:
        lk = BL.from_args(a, tool="g6_residency.py").acquire()
    except BL.BoardLockError as e:
        print("*** %s" % e)
        return 4

    art = SR.Artifacts(a.prefix, base=a.base)
    plan = SR.plan_ddr(art.meta, len(art.stream), len(art.blob), chan=a.chan)
    dev = SR.Dev(a.dev, chan=a.chan, allow_seq=False)
    print(f"--- board: MAGIC={dev.ident['magic']:#010x} "
          f"VERSION={dev.ident['version']:#010x} "
          f"CALIB={dev.ident['calib']:#x}")
    pieces = _pieces(art, plan)
    rep = {"prefix": a.prefix, "version": hex(dev.ident["version"])}

    if a.corrupt_wid is not None:
        if not a.i_mean_it:
            print("REFUSING --corrupt-wid without --i-mean-it")
            return 2
        cand = [p for p in pieces if p[7] == a.corrupt_wid]
        if not cand:
            print(f"no piece with wid {a.corrupt_wid}")
            return 2
        kind, name, chan, addr, path, off, ln, wid = cand[0]
        o, n = _witness(ln)
        pat = b"G6-CONTRIVED-MISS-" + bytes(f"{wid:04d}".encode())
        blob = (pat * (n // len(pat) + 1))[:n]
        before = (dev.dma_read(addr + o, n) if chan is None
                  else dev.dma_read_chan(chan, addr + o, n))
        if chan is None:
            dev.dma_write(addr + o, blob)
        else:
            dev.dma_write_chan(chan, addr + o, blob)
        print(f"  CONTRIVED MISS: wrote {n} B of {pat!r} over "
              f"{kind} {name} at chan={chan} addr={addr + o:#x} "
              f"(piece byte offset {o} of {ln}) — this is EXACTLY the block "
              f"chat_seq._witness({ln}) probes, so the sampling probe cannot "
              f"miss it")
        print(f"  the bytes that were there: sha256 "
              f"{hashlib.sha256(before).hexdigest()[:32]}")
        rep["corrupt"] = {"wid": wid, "name": name, "chan": chan,
                          "addr": hex(addr + o), "bytes": n,
                          "prior_sha256": hashlib.sha256(before).hexdigest()}

    if a.repair_wid is not None:
        n = 0
        for kind, name, chan, addr, path, off, ln, wid in pieces:
            if wid != a.repair_wid:
                continue
            with open(path, "rb") as f:
                f.seek(off)
                data = f.read(ln)
            if chan is None:
                dev.dma_write(addr, data)
                dev.dma_verify(addr, data, tag=name)
            else:
                dev.dma_write_chan(chan, addr, data)
                dev.dma_verify_chan(chan, addr, data, tag=name)
            n += 1
        print(f"  REPAIRED wid {a.repair_wid}: {n} piece(s) rewritten from "
              f"the artifact and read back")
        rep["repair"] = {"wid": a.repair_wid, "pieces": n}

    if a.witness_probe:
        # sw/chat_seq.py cannot run a 9B SESSION -- its templates are byte
        # slices of the 0.8B/2B artifact tb/scripts/w4/model_v2_s1.e with a
        # frozen sha256 and hard-coded record indices (TEMPLATE_NREC 60495 vs
        # this stream's 158,536).  Its RESIDENCY half has no such dependency:
        # build_residency_manifest / probe_residency / reupload_set take the
        # manifest, the split placement and the state plan and nothing else.
        # So the R-d sampler and the whole-pack escalation branch are driven
        # HERE, at 9B, against the real board -- which is what
        # sw/chat_seq.py:1194-1196 says had never happened on hardware.
        wbase_of, _ = SR.plan_weights_for(art.manifest, art.wdir, art.meta)
        splits = SR.plan_weight_split(art.manifest, wbase_of, plan["nch"],
                                      plan["weight_chans"], art.meta)
        wit = build_residency_manifest(
            art.manifest, art.wdir, wbase_of, art.embf, plan["emb_base"],
            splits=splits, state=art.state, conv_images=art.conv_images)
        bad = probe_residency(dev, wit)
        badw, bade, n_sel = reupload_set(bad, art.manifest)
        if n_sel is None:
            print("  reupload_set  nothing missed — no upload needed")
        else:
            print(f"  reupload_set  {n_sel} image(s) missed a witness; the "
                  f"R-d rule escalates to ALL {len(badw)} image(s)"
                  + (" + the embedding" if bade else "")
                  + " — a miss means the pack is not ours to trust")
        for w in bad[:8]:
            print(f"    ! MISS {w['kind']} {w['name']} chan={w['chan']} "
                  f"addr={w['addr']:#x}")
        rep["witness"] = {"blocks": len(wit), "miss": len(bad),
                          "miss_names": [w["name"] for w in bad[:8]],
                          "n_selective": n_sel,
                          "n_escalated": len(badw),
                          "embedding_too": bool(bade)}
    if a.audit:
        rep["audit"] = audit(dev, pieces)
    if a.json:
        json.dump(rep, open(a.json, "w"), indent=1)
        print(f"  json -> {a.json}")
    del lk
    if a.audit and not rep["audit"]["identical"]:
        print("G6_RESIDENCY: PACK DIFFERS")
        return 1
    print("G6_RESIDENCY: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
