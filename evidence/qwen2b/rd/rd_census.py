#!/usr/bin/env python3
# O3 BOARD LOCK (2026-09-01): this script drives the board and does
# NOT take the shared lock (sw/board_lock.py) -- it predates the O3
# ruling and its logic is frozen R-d evidence, so it was not rewritten.
# It constructs sw/seq_run.Dev directly, which never locks.
# Take the lock around it by hand:
#     python3 sw/board_lock.py --tool <why> --exec -- <this script>
"""rd_census.py — the per-phase census of a sequencer run, on silicon.

`sw/tok_meter.py` cannot plan a 2B pack (its `plan_weights` is the
nch-independent one, so 1.94 GB collides with EMB_BASE — R-d follow-on), so
the census is taken on the PRODUCTION path instead, which is the better
measurement anyway:

  * `L_LCYC` is layer_chan's 32-bit busy-cycle accumulator at 250 MHz and
    is write-clearable — the same counter tok_meter reports as `t_layer`,
    so 0.8B numbers here are directly comparable with the 15.368 ms/token
    on record in evidence/qwen2b/rb/RB_GATE.md;
  * the sequencer's own PERF_CYC is the device total for the run;
  * each engine's PERF_CYC / PERF_BEATS latch its LAST MVGO, which is the
    per-channel symmetry probe R-b used.

Unlike tok_meter's serialized replay, a sequencer run OVERLAPS layer and
matvec work, so `t_layer` here is an occupancy, not a summand: the honest
derived quantity is layer-busy per token and its share of device time.

  usage: rd_census.py <prefix> [--four-chan] [--tag NAME]
"""
import json
import os
import subprocess
import sys

R = "/home/cah/r2d2/code/fpga/fable5_llm"
sys.path.insert(0, f"{R}/sw")

import hwmap as HW                                        # noqa: E402
import seq_run as SR                                      # noqa: E402

prefix = sys.argv[1]
tag = "run"
if "--tag" in sys.argv:
    tag = sys.argv[sys.argv.index("--tag") + 1]
four = "--four-chan" in sys.argv
ACLK = 250e6

dev = SR.Dev("/dev/xdma0", chan=0)
dev.wr(HW.L_LCYC, 0)
print(f"  LCYC cleared -> {dev.rd(HW.L_LCYC)}")

out = f"{R}/evidence/qwen2b/rd/census_{tag}.json"
cmd = [f"{R}/sw/.venv/bin/python", "-u", f"{R}/sw/seq_run.py",
       "--prefix", prefix, "--zero-scratch", "--out", out]
if four:
    cmd.append("--four-chan")
print(f"  run: {' '.join(cmd[3:])}")
p = subprocess.run(cmd, cwd=R, capture_output=True, text=True)
for line in p.stdout.splitlines():
    if any(k in line for k in ("halted at", "STATUS=", "perf:", "tokens:",
                               "TOKENS", "golden", "SEQ RUN", "EMBLOG2",
                               "scratch  ", "weights  ")):
        print("   |" + line)
if p.returncode != 0:
    print(p.stdout[-2000:], p.stderr[-2000:])
    raise SystemExit(f"seq_run failed rc={p.returncode}")

rep = json.load(open(out))
dev_ms = float(rep["run"]["device_ms"])
ntok = len(rep["run"]["tokens"])
cyc = int(rep["run"]["perf"]["cyc"])

lcyc = dev.rd(HW.L_LCYC)
lay_ms = lcyc / ACLK * 1e3
man, _mm = HW.load_weights_manifest(SR.derive_base(prefix))
wbytes = sum(int(m["nrows"]) * int(m["stride"]) for m in man.values())

print(f"\n=== census: {os.path.basename(prefix)}  ({ntok} tokens)")
print(f"  device            {dev_ms:.3f} ms   {cyc:,} cycles "
      f"({cyc / ACLK * 1e3:.3f} ms at {ACLK / 1e6:.0f} MHz)")
print(f"  per token         {dev_ms / ntok:.4f} ms  ->  "
      f"{1e3 * ntok / dev_ms:.3f} tok/s   (gate convention, device/ntok)")
pre = 8.671
print(f"  steady-state      {(dev_ms - pre) / ntok:.4f} ms  ->  "
      f"{1e3 * ntok / (dev_ms - pre):.3f} tok/s   "
      f"(device - {pre} ms session preamble)")
print(f"  LAYER busy        {lcyc:,} cycles = {lay_ms:.3f} ms  "
      f"({lay_ms / ntok:.4f} ms/token, {100 * lay_ms / dev_ms:.1f}% of device)")
print(f"  weight bytes/tok  {wbytes:,} B = {wbytes / 2**20:.1f} MiB "
      f"-> {wbytes * ntok / (dev_ms * 1e-3) / 1e9:.2f} GB/s aggregate over "
      f"the whole run")

print("  per-channel engine counters (each latches that engine's LAST MVGO):")
for c in range(4):
    b = HW.mv_base(c)
    shape = dev.rd(b + HW.R_SHAPE)
    beats = dev.rd(b + HW.R_PERF_BEATS)
    lo = dev.rd(b + HW.R_PERF_CYC_LO)
    hi = dev.rd(b + HW.R_PERF_CYC_HI)
    pc = (hi << 32) | lo
    print(f"    ch{c}  SHAPE {shape:#010x}  BEATS {beats:7d}  CYC {pc:9d}"
          + (f"  {100.0 * beats / pc:5.2f}% beats/cyc" if pc else ""))
print("CENSUS_OK")
