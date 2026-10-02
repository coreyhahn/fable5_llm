#!/usr/bin/env python3
"""t4_producers.py — the R-c Task-4 producer gate (TDD: RED before GREEN).

Task 4 adds exactly two new PRODUCERS to the chain, and both of them were
left deliberately loud by Tasks 2/3 so that this file could watch them turn:

  A. `gen_layer_script.Mach.dump_weights` packing a **W8** image
     (`w4a8_ref.pack_ddr_rows8`) and tagging the manifest `"w8": true`.
     Before Task 4 it indexes `qw["w4"]` and dies with `KeyError: 'w4'`.

  B. `tb/scripts/gen_seq_chip_vectors.build_wimg` building **per-channel**
     `.wimg<c>.bin` region files for a REPACKED stream.  Before Task 4 it
     raises `SystemExit("... does not build yet")`.

Run it with `--red` on a pristine tree to record the two failures, and with
no flag afterwards to require the implemented behaviour.  Every check is a
property of the artifacts, not of a golden hash, so the file stays valid
when the 2B images are regenerated.

    python3 evidence/qwen2b/rc/t4_producers.py [--red]
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (os.path.join(_ROOT, "ref"), os.path.join(_ROOT, "sw"),
           os.path.join(_ROOT, "tb", "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import w4a8_ref as W                                          # noqa: E402
import hwmap as HW                                            # noqa: E402
import seq_format as SF                                       # noqa: E402

FAILED = []


def check(name, fn):
    try:
        fn()
        print(f"  PASS  {name}")
        return True
    except BaseException as e:                                 # noqa: BLE001
        import traceback
        print(f"  FAIL  {name}: {type(e).__name__}: {e}")
        traceback.print_exc()
        FAILED.append(name)
        return False


def expect_raises(name, exc, fn, needle=None):
    """RED mode: the call MUST still fail, with the documented failure."""
    try:
        fn()
    except exc as e:                                           # noqa: BLE001
        if needle is not None and needle not in str(e):
            print(f"  FAIL  {name}: raised {exc.__name__} but not about "
                  f"{needle!r}: {e}")
            FAILED.append(name)
            return
        print(f"  RED   {name}: {exc.__name__}: {str(e)[:80]}")
        return
    print(f"  FAIL  {name}: did NOT raise {exc.__name__} (already green?)")
    FAILED.append(name)


# ----------------------------------------------------------------------
# A. dump_weights, W8
# ----------------------------------------------------------------------
def _mk_qw(nrows, K, w8, seed):
    rs = np.random.default_rng(seed)
    Wf = rs.normal(0, 0.03, (nrows, K)).astype(np.float32)
    import layer_fixed as LF
    return LF.quant_linear_w8(Wf, g=128) if w8 else LF.quant_linear(Wf, g=128)


def _dump(d, entries):
    """Register `entries` in a Mach and dump; returns (prefix, manifest)."""
    import gen_layer_script as GL
    prefix = os.path.join(d, "t4")
    with open(prefix + ".txt", "w") as f:
        M = GL.Mach(f)
        for i, qw in enumerate(entries):
            M.wids[id(qw)] = (i, qw)
        n = M.dump_weights(prefix, emb_row_bytes=2 * 1024)
    assert n == len(entries), f"dump_weights returned {n}"
    man, meta = HW.load_weights_manifest(prefix)
    return prefix, man, meta


def t_dump_w8(d):
    q8 = _mk_qw(24, 256, True, 1)
    q4 = _mk_qw(16, 384, False, 2)
    prefix, man, meta = _dump(d, [q8, q4])

    # -- the W8 entry: tag, stride law, and a byte-exact round trip
    m8 = man["0"]
    assert m8.get("w8") is True, f"wid 0 manifest has no w8 tag: {m8}"
    assert m8["stride"] == W.row_stride8(256, 128), m8["stride"]
    assert m8["ng"] == 256 // 128, m8["ng"]     # ng UNITS in both widths
    assert m8["nbeats"] * 64 == m8["nrows"] * m8["stride"]
    img = open(os.path.join(d, m8["file"]), "rb").read()
    assert len(img) == 24 * m8["stride"], len(img)
    w8b, mb = W.unpack_ddr_rows8(img, 24, 256, g=128)
    assert (w8b == q8["w8"]).all(), "W8 codes did not round-trip"
    assert (mb == q8["m"]).all(), "W8 mantissas did not round-trip"

    # -- the W4 entry beside it is untouched, tag ABSENT (not false)
    m4 = man["1"]
    assert "w8" not in m4, f"a W4 manifest entry grew a w8 key: {m4}"
    assert m4["stride"] == W.row_stride(384, 128), m4["stride"]
    img4 = open(os.path.join(d, m4["file"]), "rb").read()
    w4b, m4b = W.unpack_ddr_rows(img4, 16, 384, g=128)
    assert (w4b == q4["w4"]).all() and (m4b == q4["m"]).all()

    # -- the manifest is plannable: hwmap re-derives the row law per width
    bases, top = HW.plan_weights(man, wdir=d)   # keyed by int wid
    assert bases[0] == HW.W_BASE, bases
    assert bases[1] == HW.W_BASE + -(-24 * m8["stride"] // HW.WID_ALIGN) \
        * HW.WID_ALIGN, bases
    assert top > HW.W_BASE
    assert meta["emb_row_bytes"] == 2048


def t_dump_w8_g64_refused(d):
    """W8 + g64 has no wire format — the packer must not invent one."""
    os.makedirs(os.path.join(d, "g64"), exist_ok=True)
    q = _mk_qw(8, 256, True, 3)
    q["g"] = 64
    try:
        _dump(os.path.join(d, "g64"), [q])
    except BaseException:                                      # noqa: BLE001
        return
    raise AssertionError("dump_weights accepted a W8 g=64 image")


def t_matvec_w8(d):
    """Mach.matvec dispatches on the weight KEY, and row-chunks identically."""
    import gen_layer_script as GL
    q8 = _mk_qw(40, 256, True, 4)
    rs = np.random.default_rng(9)
    x8 = rs.integers(-127, 128, 256).astype(np.int8)
    ref = np.asarray(W.matvec_y32_w8(q8["w8"], q8["m"], q8["sh"], x8, g=128),
                     dtype=np.int64)
    for rc in (None, 7):
        f = io.StringIO()
        M = GL.Mach(f)
        M.mem[0:256] = x8.astype(np.int64)
        y32, _ = M.matvec(q8, 0, 256, rowchunk=rc)
        assert (np.asarray(y32) == ref).all(), f"rowchunk={rc} mismatch"


# ----------------------------------------------------------------------
# B. build_wimg, per channel
# ----------------------------------------------------------------------
def _synth_repack(d, nch=4, chunk_rows=64):
    import seq_run as SR
    return SR.write_synth_repack_artifact(d, nch=nch, chunk_rows=chunk_rows)


def _fill_images(d, man):
    """The synthetic artifact's images are zero-filled; give every row a
    unique byte pattern so a misplaced row cannot compare equal by luck."""
    for wid, m in man.items():
        path = os.path.join(d, m["file"])
        n, st = int(m["nrows"]), int(m["stride"])
        rs = np.random.default_rng(1000 + int(wid))
        a = rs.integers(0, 256, (n, st), dtype=np.uint8)
        a[:, 0] = np.arange(n, dtype=np.uint16).astype(np.uint8)
        a.tofile(path)


def t_build_wimg_perchan(d):
    import gen_seq_chip_vectors as GV
    prefix = _synth_repack(d)
    base = os.path.join(d, "rp")
    man, _meta = HW.load_weights_manifest(base)
    _fill_images(d, man)
    meta = json.load(open(prefix + ".seq.json"))
    plan = {int(k): v for k, v in meta["weights"].items()}
    assert meta.get("weight_repack") is True
    wl = meta["weight_layout"]
    nch, depth = int(wl["nch"]), int(wl["chunk_rows"])

    tops = GV.build_wimg(base, plan, base + ".wimg.bin", meta=meta)
    assert isinstance(tops, (list, tuple)) and len(tops) == nch, \
        f"build_wimg returned {tops!r}, expected one top per channel"

    for c in range(nch):
        fn = f"{base}.wimg{c}.bin"
        assert os.path.exists(fn), f"missing {fn}"
    assert not os.path.exists(base + ".wimg.bin"), \
        "a flat .wimg.bin was written beside the per-channel ones"

    # every piece of every image must sit at that channel's own address
    blobs = [np.fromfile(f"{base}.wimg{c}.bin", dtype=np.uint8)
             for c in range(nch)]
    nchecked = 0
    for wid, p in sorted(plan.items()):
        src = np.fromfile(os.path.join(d, man[str(wid)]["file"]),
                          dtype=np.uint8).reshape(p["nrows"], p["stride"])
        layout = wl["by_wid"].get(str(wid), wl["default"])
        for (c, r0, npc, off) in SF.weight_pieces_at(p["nrows"], nch, layout,
                                                     depth, repack=True):
            o = p["base"][c] - HW.W_BASE + off * p["stride"]
            got = blobs[c][o:o + npc * p["stride"]]
            assert got.size == npc * p["stride"], \
                f"wid {wid} chan {c}: file too short at {o}"
            assert (got.reshape(npc, p["stride"]) == src[r0:r0 + npc]).all(), \
                f"wid {wid} chan {c}: rows {r0}..{r0 + npc} misplaced"
            nchecked += 1
    assert nchecked >= nch, nchecked

    # a byte NOT owned by channel c must not appear at c's own top-of-pack
    for c in range(nch):
        assert blobs[c].size == tops[c], (blobs[c].size, tops[c])
    print(f"        {nchecked} pieces verified across {nch} channels, "
          f"tops {[hex(t) for t in tops]}")


def t_build_wimg_perchan_red(d):
    """RED form: the pre-Task-4 signature (no `meta`) on a repacked plan."""
    import gen_seq_chip_vectors as GV
    prefix = _synth_repack(d)
    base = os.path.join(d, "rp")
    meta = json.load(open(prefix + ".seq.json"))
    plan = {int(k): v for k, v in meta["weights"].items()}
    GV.build_wimg(base, plan, base + ".wimg.bin")


def t_build_wimg_flat_unchanged(d):
    """The NON-repacked path still writes ONE flat region file, unchanged."""
    import gen_seq_chip_vectors as GV
    import seq_run as SR
    d2 = os.path.join(d, "flat")
    os.makedirs(d2, exist_ok=True)
    # same synthetic images, nch-INDEPENDENT plan (repack off)
    prefix = SR.write_synth_repack_artifact(d2, nch=4, chunk_rows=64)
    base = os.path.join(d2, "rp")
    man, _ = HW.load_weights_manifest(base)
    _fill_images(d2, man)
    flat = SF.plan_weights_from_wids(
        {f"w{w}": (int(w), {"w8" if man[w].get("w8") else "w4":
                            np.zeros((int(man[w]["nrows"]),
                                      int(man[w]["k"])), dtype=np.int8),
                            "m": np.zeros((int(man[w]["nrows"]),
                                           int(man[w]["k"]) // 128),
                                          dtype=np.int8),
                            "sh": 5, "g": 128}) for w in man},
        nch=1, repack=False)
    top = GV.build_wimg(base, flat, base + ".wimg.bin")
    assert isinstance(top, int), f"flat build_wimg returned {top!r}"
    blob = np.fromfile(base + ".wimg.bin", dtype=np.uint8)
    assert blob.size == top
    for wid, p in sorted(flat.items()):
        src = np.fromfile(os.path.join(d2, man[str(wid)]["file"]),
                          dtype=np.uint8)
        o = p["base"] - HW.W_BASE
        assert (blob[o:o + src.size] == src).all(), f"wid {wid} misplaced"


# ----------------------------------------------------------------------
def main():
    red = "--red" in sys.argv[1:]
    print(f"t4_producers.py  mode={'RED (pre-implementation)' if red else 'GREEN'}"
          f"  host={os.uname().nodename}")
    d = tempfile.mkdtemp(prefix="t4prod_")
    try:
        if red:
            print("A. dump_weights W8")
            expect_raises("dump_weights(W8) is KeyError-loud", KeyError,
                          lambda: t_dump_w8(d), needle="w4")
            print("B. build_wimg per-channel")
            expect_raises("build_wimg refuses a repacked stream", SystemExit,
                          lambda: t_build_wimg_perchan_red(d),
                          needle="PER-CHANNEL")
            print("C. gen_model_script --wq=w8")
            r = subprocess.run(
                [sys.executable, os.path.join(_ROOT, "ref",
                                              "gen_model_script.py"),
                 os.path.join(d, "x.txt"), "1", "1", "--wq=w8"],
                capture_output=True, text=True)
            if r.returncode != 0 and "unknown flags" in (r.stdout + r.stderr):
                print("  RED   gen_model_script rejects --wq=w8: "
                      + [ln for ln in (r.stdout + r.stderr).splitlines()
                         if "unknown flags" in ln][0].strip())
            else:
                print(f"  FAIL  gen_model_script --wq=w8 did not report an "
                      f"unknown flag (rc={r.returncode})")
                FAILED.append("wq red")
        else:
            print("A. dump_weights W8")
            check("W8 image packs + manifest tag + round trip",
                  lambda: t_dump_w8(d))
            check("W8 + g64 refused by the packer",
                  lambda: t_dump_w8_g64_refused(d))
            check("Mach.matvec dispatches W8 (rowchunk-identical)",
                  lambda: t_matvec_w8(d))
            print("B. build_wimg per-channel")
            check("repacked stream -> one region file per channel, rows exact",
                  lambda: t_build_wimg_perchan(d))
            check("non-repacked stream -> one flat region file, unchanged",
                  lambda: t_build_wimg_flat_unchanged(d))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if FAILED:
        print(f"\nFAILED: {FAILED}")
        raise SystemExit(1)
    print("\nT4_PRODUCERS " + ("RED OK (both producers still refuse)"
                               if red else "PASS"))


if __name__ == "__main__":
    main()
