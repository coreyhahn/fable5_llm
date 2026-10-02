#!/usr/bin/env python3
# O3 BOARD LOCK (2026-09-01): this script drives the board and does
# NOT take the shared lock (sw/board_lock.py) -- it predates the O3
# ruling and its logic is frozen R-d evidence, so it was not rewritten.
# It constructs sw/seq_run.Dev directly, which never locks.
# Take the lock around it by hand:
#     python3 sw/board_lock.py --tool <why> --exec -- <this script>
"""rd_residency_audit.py — what is ACTUALLY resident, vs what the witness
probe believes.

`chat_seq` skips its weight upload when `probe_residency` finds every
witness block intact.  R-d hit a case where that probe said "0 MISS" on a
board whose weight pack was a MIXTURE of two models, and the session then
ran to completion against the wrong bytes.  This audit reads the WHOLE pack
back and compares it to the artifact's files, alongside the very same
witness probe, so the size of the blind spot is measured rather than
argued.

  usage: rd_residency_audit.py <prefix> [--full]
         (--full reads every byte of every piece; without it, witnesses only)
"""
import hashlib
import sys

R = "/home/cah/r2d2/code/fpga/fable5_llm"
sys.path.insert(0, f"{R}/ref")
sys.path.insert(0, f"{R}/sw")

import chat_seq as CS                                     # noqa: E402
import hwmap as HW                                        # noqa: E402
import seq_run as SR                                      # noqa: E402

prefix = sys.argv[1]
full = "--full" in sys.argv
base = SR.derive_base(prefix)
art = SR.Artifacts(prefix)
meta = art.meta
wdir = SR.os.path.dirname(SR.os.path.abspath(base)) or "."
manifest, mmeta = HW.load_weights_manifest(base)
wbase_of, wtop = SR.plan_weights_for(manifest, wdir, meta)
nch = max(1, int(meta.get("nch", 1)))
splits = SR.plan_weight_split(manifest, wbase_of, nch, list(range(nch)), meta)
embf = base + ".emb.bin"

dev = SR.Dev("/dev/xdma0", chan=0)
print(f"artifact {SR.os.path.basename(prefix)}  nch={meta.get('nch', 1)} "
      f"repack={bool(meta.get('weight_repack'))}  "
      f"{len(manifest)} images, {len(splits)} pieces")

wit = CS.build_residency_manifest(manifest, wdir, wbase_of, embf,
                                  HW.EMB_BASE, splits=splits)
bad = CS.probe_residency(dev, wit)
print(f"WITNESS PROBE: {len(bad)} MISS of {len(wit)} "
      f"-> chat_seq would {'RE-UPLOAD' if bad else 'SKIP THE UPLOAD'}")
for w in bad[:6]:
    print(f"    miss {w['name']} @ {w['addr']:#x}")

if not full:
    sys.exit(0)

print("\nFULL COMPARE — every byte of every piece, vs the artifact files")
fh = {}
dmg_pieces, dmg_bytes, tot_bytes = 0, 0, 0
dmg_wids, lo_addr, hi_addr = set(), None, None
for s in sorted(splits, key=lambda s: (s["chan"], s["local_addr"])):
    m = manifest[str(s["wid"])] if str(s["wid"]) in manifest \
        else manifest[s["wid"]]
    p = SR.os.path.join(wdir, m["file"])
    f = fh.get(p) or fh.setdefault(p, open(p, "rb"))
    f.seek(s["byte_off"])
    want = f.read(s["byte_len"])
    got = dev.dma_read_chan(s["chan"], s["local_addr"], s["byte_len"])
    tot_bytes += len(want)
    if got != want:
        dmg_pieces += 1
        dmg_wids.add(int(s["wid"]))
        n = sum(1 for i in range(0, len(want), 4096)
                if got[i:i + 4096] != want[i:i + 4096]) * 4096
        dmg_bytes += n
        a0, a1 = s["local_addr"], s["local_addr"] + s["byte_len"]
        lo_addr = a0 if lo_addr is None else min(lo_addr, a0)
        hi_addr = a1 if hi_addr is None else max(hi_addr, a1)

print(f"  pieces damaged : {dmg_pieces} of {len(splits)}")
print(f"  images touched : {len(dmg_wids)} of {len(manifest)}"
      + (f"  (wid {min(dmg_wids)}..{max(dmg_wids)})" if dmg_wids else ""))
print(f"  bytes damaged  : {dmg_bytes / 2**20:.1f} MiB of "
      f"{tot_bytes / 2**20:.1f} MiB ({100.0 * dmg_bytes / max(1, tot_bytes):.1f}%)")
if lo_addr is not None:
    print(f"  address range  : {lo_addr:#x} .. {hi_addr:#x} (channel-local)")

n = 8
sz = SR.os.path.getsize(embf)
ebad = 0
with open(embf, "rb") as f:
    for i in range(n):
        off = ((sz - 4096) * i // (n - 1)) & ~0xFFF
        f.seek(off)
        if dev.dma_read(HW.EMB_BASE + off, 4096) != f.read(4096):
            ebad += 1
print(f"  embedding      : {ebad} of {n} sampled 4 KiB blocks differ")
print("RESIDENT_CLEAN" if not dmg_pieces and not ebad else "RESIDENT_MIXED")
sys.exit(0 if not dmg_pieces and not ebad else 2)
