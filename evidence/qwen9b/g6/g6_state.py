#!/usr/bin/env python3
"""g6_state.py — the DDR state region, written exactly and read back exactly.

    # put the artifact's INITIAL region image on the board, verbatim
    python3 evidence/qwen9b/g6/g6_state.py --prefix ... --write-initial

    # after a run: read the whole region back and hash it
    python3 evidence/qwen9b/g6/g6_state.py --prefix ... --readback

WHY THIS FILE EXISTS.  The amendment asks for the SILICON form of S4's
`SMEM` golden: "on silicon the state region's final image can be read back
and compared with the artifact's `state_final.bin` (`final_sha256`) after a
run".  A byte-for-byte comparison of the whole region needs the board to
start from the same place the reference did, and `sw/seq_run.upload_state`
deliberately does NOT put it there — it memsets the DN region and writes the
conv images but leaves the 128 MiB KV region alone, "which is 128 MiB of DMA
this host does not do", because the RTL never reads a KV row before it
writes it (TCNT = 0 after a session reset).  That is the right call for
every ordinary run and the wrong one for THIS check: `ref/seq_model`'s
`StateRegion` is zero-initialised across all 162,529,280 B, so
`state_final.bin` is zero everywhere the program did not write, while the
board's KV tail still holds whatever the previous tenant left.

So `--write-initial` writes `<base>.state.bin` VERBATIM — all three
sub-regions, KV included — and proves it landed by reading it back and
hashing it against the manifest's `state["sha256"]`.  After that the run
starts exactly where the reference started, and `--readback` can hash all
162,529,280 B against `final_sha256` with no carve-outs and no excuses.

Follow it with `sw/seq_run.py --skip-weights`, whose `upload_state(...,
csrs_only=True)` programs SB_DN/SB_KV/SB_CV and writes not one byte of the
region — so the image this tool placed is the image the program runs on.

BOARD SAFETY.  Never programs the FPGA, never touches flash, never runs
sudo, never calls pcie_helper.sh.  Same shared board lock as every other
tool; the SEQ CSR window is never touched (allow_seq=False).
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

CHUNK = 32 << 20


def region(art):
    st = art.state
    if st is None:
        raise SystemExit("this artifact declares no DDR state region")
    return (st["dn"] >> 32, st["dn"] & 0xFFFF_FFFF,
            st["end"] - st["dn"], st)


def write_initial(dev, art, log=print):
    chan, base, nby, st = region(art)
    path = art.base + ".state.bin"
    want = SR.verify_state_image(art)          # sha of the FILE vs manifest
    log(f"  image     {path} {os.path.getsize(path)} B, sha256 "
        f"{want[:32]} == manifest state['sha256'] [OK]")
    if os.path.getsize(path) != nby:
        raise SystemExit(f"{path} is {os.path.getsize(path)} B, the region "
                         f"is {nby} B")
    t0 = time.monotonic()
    with open(path, "rb") as f:
        off = 0
        while off < nby:
            b = f.read(min(CHUNK, nby - off))
            dev.dma_write_chan(chan, base + off, b)
            off += len(b)
    dt = time.monotonic() - t0
    log(f"  written   {nby / 2**20:.0f} MiB -> {st['dn']:#x} (chan {chan}) "
        f"in {dt:.1f} s — ALL THREE sub-regions, KV included")
    return want


def readback(dev, art, want_key, log=print):
    chan, base, nby, st = region(art)
    h = hashlib.sha256()
    t0 = time.monotonic()
    off = 0
    while off < nby:
        n = min(CHUNK, nby - off)
        h.update(dev.dma_read_chan(chan, base + off, n))
        off += n
    dt = time.monotonic() - t0
    got = h.hexdigest()
    want = st.get(want_key)
    log(f"  readback  {nby / 2**20:.0f} MiB of {st['dn']:#x}..{st['end']:#x} "
        f"(chan {chan}) in {dt:.1f} s ({nby / 2**20 / dt:.0f} MiB/s)")
    log(f"  on-chip   sha256 {got}")
    log(f"  artifact  {want_key} {want}")
    ok = (want is not None and got == want)
    log(f"  STATE {'BIT-EXACT' if ok else 'DIFFERS'} against "
        f"{os.path.basename(art.base)}"
        + (".state_final.bin" if want_key == "final_sha256" else ".state.bin"))
    return {"bytes": nby, "seconds": round(dt, 1), "sha256": got,
            "want": want, "ok": ok}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--base", default=None)
    ap.add_argument("--dev", default="/dev/xdma0")
    ap.add_argument("--chan", type=int, default=0)
    ap.add_argument("--write-initial", action="store_true")
    ap.add_argument("--readback", action="store_true",
                    help="hash the region against final_sha256")
    ap.add_argument("--readback-initial", action="store_true",
                    help="hash the region against sha256 (the INITIAL image)")
    ap.add_argument("--json", default=None)
    BL.add_lock_args(ap)
    a = ap.parse_args(argv)
    want = r3_expect_version()   # R3-0 (iv): exit 4 on an unknown name, before the lock
    try:
        lk = BL.from_args(a, tool="g6_state.py").acquire()
    except BL.BoardLockError as e:
        print("*** %s" % e)
        return 4

    art = SR.Artifacts(a.prefix, base=a.base)
    dev = SR.Dev(a.dev, chan=a.chan, allow_seq=False)
    print(f"--- board: MAGIC={dev.ident['magic']:#010x} "
          f"VERSION={dev.ident['version']:#010x} "
          f"CALIB={dev.ident['calib']:#x}")
    # R3-0 (iv): the resident bitstream must be the one named before ANY DMA
    if want not in SR.SEQ_VERSIONS or dev.ident["version"] != want:
        print(f"*** REFUSING the state-region DMA (exit 4): board VERSION "
              f"{dev.ident['version']:#010x} != expected {want:#010x} "
              f"({SR.SEQ_VERSIONS.get(want, (0, 'NOT in SEQ_VERSIONS'))[1]}); "
              f"name the resident bitstream with {SR.EXPECT_VERSION_ENV}=<hash>"
              f" (NEXT_SESSION.md §9 (f) rule 6).  Nothing written or read.")
        return 4
    st = art.state
    print(f"--- state region  DN {st['dn']:#x}  KV {st['kv']:#x}  "
          f"CV {st['cv']:#x}  END {st['end']:#x}  "
          f"({(st['end'] - st['dn']) / 2**20:.0f} MiB on DDR channel "
          f"{st['dn'] >> 32})")
    rep = {"prefix": a.prefix, "version": hex(dev.ident["version"]),
           "dn": hex(st["dn"]), "kv": hex(st["kv"]), "cv": hex(st["cv"]),
           "end": hex(st["end"])}
    ok = True
    if a.write_initial:
        rep["image_sha256"] = write_initial(dev, art)
        r = readback(dev, art, "sha256")
        rep["after_write"] = r
        ok = ok and r["ok"]
    if a.readback_initial:
        r = readback(dev, art, "sha256")
        rep["initial"] = r
        ok = ok and r["ok"]
    if a.readback:
        r = readback(dev, art, "final_sha256")
        rep["final"] = r
        ok = ok and r["ok"]
    if a.json:
        json.dump(rep, open(a.json, "w"), indent=1)
        print(f"  json -> {a.json}")
    del lk
    print("G6_STATE: " + ("OK" if ok else "FAIL"))
    return 0 if ok else 1


def r3_expect_version():
    """R3-0 (iv) (evidence/qwen9b/sr/R3_0_TOOLING.md): the VERSION this run
    expects on the board, resolved exactly as sw/seq_run.py resolves it for
    every SEQ-driving tool — SR.resolve_expect_version(): $FABLE5_SEQ_EXPECT_VERSION
    if set (it must name a SEQ_VERSIONS row), else the shipped build_041
    0xC973C18A.  main() refuses with exit 4 unless the board's VERSION equals
    it, after SR.Dev reads the identity and before the first DMA of either
    direction.  An unknown name is refused here (exit 4), before the lock and
    before the device is opened — Dev's own resolve would raise it too."""
    try:
        return SR.resolve_expect_version()
    except ValueError as e:
        print(f"*** REFUSING the state-region DMA (exit 4): {e}")
        raise SystemExit(4)


if __name__ == "__main__":
    raise SystemExit(main())
