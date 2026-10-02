#!/usr/bin/env python3
"""sr3_cycles.py — Task SR3 backward compatibility: CYCLE identity.

Compares, vector by vector, the tb_seq_unit issue-rate block printed by a
run on the BASE RTL (the RED log: sr3_tb_each.sh built from the base
commit's seq_unit.sv + seq_movers.sv) with the same vector's block in the
GREEN log (the SR3 RTL) — LAT=4 / SIDEBAND=0 builds only, the one both
logs have (the FIRST such block per vector — tb_seq_all's `tb_seq` pass;
tb_seq_guard re-runs seq_h_embrow at LAT=4 later in the same log).  The block is printed after every functional check and BEFORE
the SEQ_CAPS $fatal, so the base run prints it for every vector that did
not fault on the new semantics.

Compared per vector: cycles START->HALT, AXI-Lite writes, AXI-Lite reads,
STATUS polls among them, fetch-empty stall cycles, DDR beats.  Any
difference is a FAIL.  The two vector dirs are also checked to hold
byte-identical stream images (.ddr.hex), so the rows compare the same
stream.

    sr3_cycles.py <base_log> <green_log> <base_vec_dir> <green_vec_dir>
"""
import hashlib
import os
import re
import sys

R_SEQ = re.compile(r"^SEQ (\S+): (\d+) records, (\d+) cycles")
R_AXW = re.compile(r"^\s+axil writes (\d+)")
R_AXR = re.compile(r"^\s+axil reads\s+(\d+)\s+\(of which (\d+) were status polls\)")
R_FST = re.compile(r"^\s+fetch-empty stall cycles (\d+)\s+\(ddr beats (\d+)\)")
R_LAY = re.compile(r"LAT=(\d+) BLAT=(\d+) DDRLAT=(\d+) SIDEBAND=(\d+)")


def blocks(path):
    out, cur = {}, None
    for line in open(path, errors="replace"):
        m = R_SEQ.match(line)
        if m:
            cur = dict(vec=os.path.basename(m.group(1)), nrec=int(m.group(2)),
                       cyc=int(m.group(3)))
            continue
        if cur is None:
            continue
        if (m := R_AXW.match(line)):
            cur["axw"] = int(m.group(1))
        elif (m := R_AXR.match(line)):
            cur["axr"], cur["poll"] = int(m.group(1)), int(m.group(2))
        elif (m := R_FST.match(line)):
            cur["fst"], cur["beats"] = int(m.group(1)), int(m.group(2))
        elif (m := R_LAY.search(line)):
            key = (cur["vec"], int(m.group(1)), int(m.group(4)))
            # first block wins: tb_seq_all runs `tb_seq` FIRST; a later
            # LAT=4 block of the same vector is tb_seq_guard's
            # +define+SYNTHESIS re-run of seq_h_embrow (n311 stopped on it)
            if key not in out:
                out[key] = cur
            cur = None
    return out


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    base_log, green_log, bdir, gdir = sys.argv[1:5]
    b, g = blocks(base_log), blocks(green_log)
    keys = sorted(k for k in b if k[1] == 4 and k[2] == 0)
    fields = ("nrec", "cyc", "axw", "axr", "poll", "fst", "beats")
    nfail = 0
    print(f"{'vector':<18} " + " ".join(f"{f:>8}" for f in fields)
          + "  verdict")
    for k in keys:
        v = k[0]
        img = (sha(os.path.join(bdir, v + ".ddr.hex"))
               == sha(os.path.join(gdir, v + ".ddr.hex")))
        if k not in g:
            print(f"{v:<18} MISSING in green log")
            nfail += 1
            continue
        same = img and all(b[k].get(f) == g[k].get(f) for f in fields)
        nfail += 0 if same else 1
        print(f"{v:<18} " + " ".join(f"{b[k].get(f, -1):>8}" for f in fields)
              + ("  IDENTICAL" if same else
                 "  DIFFERS green=" + " ".join(str(g[k].get(f)) for f in fields)
                 + ("" if img else " (stream images differ)")))
    only_g = sorted(k[0] for k in g if k[1] == 4 and k[2] == 0 and k not in b)
    print(f"green-only (no base block: faulted on the base RTL): {only_g}")
    print(f"SR3 CYCLES: {len(keys)} vectors compared, "
          f"{len(keys) - nfail} identical, {nfail} differ")
    sys.exit(1 if nfail else 0)


if __name__ == "__main__":
    main()
