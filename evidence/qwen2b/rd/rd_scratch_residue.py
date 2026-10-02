#!/usr/bin/env python3
"""rd_scratch_residue.py — is the 2B golden's 63-word scratch delta a
COMPUTATION error, or stale scratch the run never writes?

PROVENANCE, stated plainly (review round 1): this script was WRITTEN after
the two dumps were taken (mtimes: dumps 23:52:24 and 23:53:10, this file
23:53:37), and `hw_20` had already printed the first eight disputed
addresses.  So the honest claim is not "predicted before the data existed"
but "three checks, each of which could have falsified the residue
explanation, whose reference inputs are independent of the dumps": the two
staging windows come from the artifacts' own committed `.seq.json`
(2026-08-22, two days before the run), and the A-vs-B comparison and the
mirror were not visible in any earlier output.

The three checks:

  * every disputed word lies OUTSIDE the 2B stream's own y32 staging
    window and INSIDE the 0.8B stream's — i.e. it is a word the previous
    model used as scratch and the 2B model never touches;
  * dump A (taken after a 0.8B run) and dump B (taken after the 2B run
    that followed it) hold BIT-IDENTICAL values at those words — the 2B
    run did not write them;
  * every other checked word in dump B equals the 2B golden.

If all three hold, the mismatch is host-model residue (the simulator's
scratch is zero-initialised; the FPGA's is not), not silicon arithmetic.
"""
import json
import sys

import numpy as np

R = "/home/cah/r2d2/code/fpga/fable5_llm"
A = np.load(f"{R}/evidence/qwen2b/rd/scratch_A_08b_nch4.npy")
B = np.load(f"{R}/evidence/qwen2b/rd/scratch_B_2b.npy")
print(f"dump A (post-0.8B nch=4): {A.shape} {A.dtype}")
print(f"dump B (post-2B)        : {B.shape} {B.dtype}")

meta8 = json.load(open(f"{R}/tb/scripts/w4/model_v2_s1.e4.seq.json"))
meta2 = json.load(open(f"{R}/tb/scripts/w5/model_w8_2b_s1.e.seq.json"))
st8 = meta8["staging_words"]
st2 = meta2["staging_words"]
print(f"0.8B staging words: {[(hex(a), hex(b)) for a, b in st8]}")
print(f"2B   staging words: {[(hex(a), hex(b)) for a, b in st2]}")


def golden_mem(path):
    """The MEM lines of a .chip golden -> {addr: word}."""
    out = {}
    for line in open(path):
        f = line.split()
        if f and f[0] == "MEM":
            out[int(f[1], 16)] = int(f[2], 16)
    return out


g2 = golden_mem(f"{R}/tb/scripts/w5/model_w8_2b_s1.e.chip")
print(f"2B golden .chip: {len(g2)} checked scratch words")

bad = sorted(a for a, w in g2.items() if int(B[a]) != w)
print(f"\ndump B vs the 2B golden: {len(bad)} differing words of {len(g2)}")
print(f"  address span: {hex(min(bad))} .. {hex(max(bad))}"
      if bad else "  (none)")


def inside(addr, runs):
    return any(lo <= addr < hi for lo, hi in runs)


in2 = [a for a in bad if inside(a, st2)]
in8 = [a for a in bad if inside(a, st8)]
print(f"  inside the 2B stream's OWN staging window : {len(in2)} of {len(bad)}")
print(f"  inside the 0.8B stream's staging window   : {len(in8)} of {len(bad)}")

same = [a for a in bad if int(A[a]) == int(B[a])]
print(f"  values IDENTICAL in dump A and dump B     : {len(same)} of {len(bad)}"
      "   <- the 2B run never wrote them")

print("\n  first 8 disputed words   addr   dumpA   dumpB   golden")
for a in bad[:8]:
    print(f"    {a:#06x}   {int(A[a]):#06x}  {int(B[a]):#06x}  {g2[a]:#06x}")

# The other direction, from the same pair of dumps: the words the 0.8B
# golden flagged after the 2B ran are words the 2B WROTE and the 0.8B
# does not, i.e. the mirror image of the same mechanism.
g8 = golden_mem(f"{R}/tb/scripts/w4/model_v2_s1.e4.chip")
bad8 = sorted(a for a, w in g8.items() if int(A[a]) != w)
print(f"\nmirror check — dump A vs the 0.8B golden: {len(bad8)} differing "
      f"of {len(g8)}   (the run itself is hw_21a)")
if bad8:
    print(f"  span {hex(min(bad8))} .. {hex(max(bad8))}; "
          f"inside 0.8B's own staging: "
          f"{sum(1 for a in bad8 if inside(a, st8))}; "
          f"inside the 2B's staging: "
          f"{sum(1 for a in bad8 if inside(a, st2))}")
    # Staging membership does NOT identify these as the 2B's leftovers —
    # they are outside BOTH windows.  What identifies them is the 2B
    # golden's own expectations: if the board holds exactly what the 2B
    # golden says the 2B run should have written there, then the 2B wrote
    # them and the 0.8B stream does not overwrite them.
    inb = [a for a in bad8 if a in g2]
    nz = [a for a in inb if g2[a] != 0]
    eq = [a for a in nz if int(A[a]) == g2[a]]
    print(f"  in the 2B golden's checked set: {len(inb)} of {len(bad8)}; "
          f"the 2B golden expects NON-ZERO at {len(nz)}; "
          f"the board holds EXACTLY the 2B golden's value at "
          f"{len(eq)} of {len(nz)}")
    for a in bad8[:4]:
        print(f"    {a:#06x}  0.8B golden wants {g8[a]:#06x}  "
              f"2B golden wants {g2.get(a, 0):#06x}  board holds "
              f"{int(A[a]):#06x}")

ok = (bad and not in2 and len(in8) == len(bad) and len(same) == len(bad)
      and bool(bad8) and all(int(A[a]) == g2.get(a) for a in bad8 if a in g2))
print("\nRESIDUE_PROVEN" if ok else "\nRESIDUE_NOT_PROVEN")
sys.exit(0 if ok else 1)
