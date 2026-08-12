#!/usr/bin/env python3
"""Stage-1 DDR4 integrity test for BCU-1525 (run on snoke).

Reference model: for (seed, channel), the byte stream is
numpy.random.Generator(PCG64(seed*16+channel)) bytes — regenerated
independently for write and for compare, so the comparison is bit-exact
against a deterministic reference, not against a copy of what we wrote.

Per the charter, hardware acceptance = at least 4 seeds, each run twice,
without reprogramming, every channel, bit-exact.

Usage (on snoke):
  ./ddr_test.py --quick          # 64 MiB/channel smoke test
  ./ddr_test.py                  # full 4 GiB x 4 channels x 4 seeds x 2 runs
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import numpy as np

CH_BASE = [0x0_0000_0000, 0x1_0000_0000, 0x2_0000_0000, 0x3_0000_0000]
CH_SIZE = 4 << 30          # 4 GiB per channel
CHUNK = 64 << 20           # 64 MiB DMA chunks

# CSR map (AXI-Lite BAR, /dev/xdma0_user)
R_MAGIC, R_VERSION, R_SCRATCH, R_CALIB = 0x00, 0x04, 0x08, 0x0C
MAGIC_EXPECT = 0xFAB1E001


def csr_read(fd, addr):
    return int.from_bytes(os.pread(fd, 4, addr), "little")


def csr_write(fd, addr, val):
    os.pwrite(fd, int(val).to_bytes(4, "little"), addr)


def gen_chunks(seed, ch, size):
    """Reference byte stream for (seed, channel), yielded in CHUNK pieces."""
    rng = np.random.Generator(np.random.PCG64(seed * 16 + ch))
    left = size
    while left > 0:
        n = min(CHUNK, left)
        yield rng.integers(0, 256, n, dtype=np.uint8).tobytes()
        left -= n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", default="/dev/xdma0")
    ap.add_argument("--seeds", type=lambda s: [int(x, 0) for x in s.split(",")],
                    default=[0xC0FFEE01, 0xC0FFEE02, 0xC0FFEE03, 0xC0FFEE04])
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--channels", type=lambda s: [int(x) for x in s.split(",")],
                    default=[0, 1, 2, 3])
    ap.add_argument("--size", type=int, default=CH_SIZE, help="bytes per channel")
    ap.add_argument("--quick", action="store_true", help="64 MiB per channel")
    ap.add_argument("--evidence", default=None, help="evidence output dir")
    args = ap.parse_args()
    size = (64 << 20) if args.quick else args.size

    user_fd = os.open(f"{args.dev}_user", os.O_RDWR)
    h2c_fd = os.open(f"{args.dev}_h2c_0", os.O_WRONLY)
    c2h_fd = os.open(f"{args.dev}_c2h_0", os.O_RDONLY)

    log = {
        "utc": datetime.now(timezone.utc).isoformat(),
        "git": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip(),
        "seeds": [hex(s) for s in args.seeds], "runs": args.runs,
        "channels": args.channels, "bytes_per_channel": size,
        "results": [], "pass": True,
    }

    # --- preconditions: CSR sane, all channels calibrated (NEVER DMA before
    # calibration: an uncalibrated MIG stalls the AXI read and wedges the DMA)
    magic = csr_read(user_fd, R_MAGIC)
    version = csr_read(user_fd, R_VERSION)
    calib = csr_read(user_fd, R_CALIB)
    print(f"MAGIC={magic:08x} VERSION={version:08x} CALIB={calib:x}")
    log["magic"], log["version"], log["calib"] = (
        f"{magic:08x}", f"{version:08x}", f"{calib:x}")
    if magic != MAGIC_EXPECT:
        sys.exit(f"FATAL: MAGIC {magic:08x} != {MAGIC_EXPECT:08x} — wrong/old design loaded")
    need = sum(1 << c for c in args.channels)
    if (calib & need) != need:
        sys.exit(f"FATAL: DDR4 calib={calib:04b}, need channels {args.channels} — refusing to DMA")
    # scratch sanity
    csr_write(user_fd, R_SCRATCH, 0xA5A5_5A5A)
    rb = csr_read(user_fd, R_SCRATCH)
    if rb != 0xA5A5_5A5A:
        sys.exit(f"FATAL: scratch readback {rb:08x}")

    for run in range(args.runs):
        for seed in args.seeds:
            for ch in args.channels:
                base = CH_BASE[ch]
                # write reference stream
                t0 = time.monotonic()
                off, h_w = 0, hashlib.sha256()
                for chunk in gen_chunks(seed, ch, size):
                    h_w.update(chunk)
                    n = os.pwrite(h2c_fd, chunk, base + off)
                    assert n == len(chunk), f"short write {n}"
                    off += n
                t_w = time.monotonic() - t0
                # read back and compare bit-exact vs regenerated reference
                t0 = time.monotonic()
                off, errs, first_errs = 0, 0, []
                for chunk in gen_chunks(seed, ch, size):
                    got = os.pread(c2h_fd, len(chunk), base + off)
                    assert len(got) == len(chunk), f"short read {len(got)}"
                    if got != chunk:
                        a = np.frombuffer(got, dtype=np.uint8)
                        b = np.frombuffer(chunk, dtype=np.uint8)
                        bad = np.nonzero(a != b)[0]
                        errs += len(bad)
                        for i in bad[:8]:
                            first_errs.append({"addr": hex(base + off + int(i)),
                                               "got": int(a[i]), "exp": int(b[i])})
                    off += len(chunk)
                t_r = time.monotonic() - t0
                res = {
                    "run": run, "seed": hex(seed), "ch": ch,
                    "sha256": h_w.hexdigest()[:16],
                    "write_MBps": round(size / t_w / 1e6, 1),
                    "read_MBps": round(size / t_r / 1e6, 1),
                    "byte_errors": errs,
                }
                if errs:
                    res["first_errors"] = first_errs[:16]
                    log["pass"] = False
                log["results"].append(res)
                status = "OK " if errs == 0 else "FAIL"
                print(f"[{status}] run{run} seed={seed:#x} ch{ch}: "
                      f"W {res['write_MBps']} MB/s, R {res['read_MBps']} MB/s, "
                      f"errors={errs}", flush=True)

    print("PASS" if log["pass"] else "FAIL")
    if args.evidence:
        os.makedirs(args.evidence, exist_ok=True)
        fn = os.path.join(args.evidence,
                          f"ddr_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(fn, "w") as f:
            json.dump(log, f, indent=1)
        print(f"evidence: {fn}")
    sys.exit(0 if log["pass"] else 1)


if __name__ == "__main__":
    main()
