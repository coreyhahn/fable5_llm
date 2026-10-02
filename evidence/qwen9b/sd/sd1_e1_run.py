#!/usr/bin/env python3
"""sd1_e1_run.py — Task SD1 fix round 1, E1: run the per-key census probes.

  FABLE5_MODEL=9b python evidence/qwen9b/sd/sd1_e1_run.py <scriptdir> [jobs]

For every s<seed>_<key>.txt that sd1_e1_gen.py wrote into <scriptdir>, runs
the EXISTING Task 14-A layer-census binary
    tb/obj_dir_tb_layer_census_t14a_lat8/tb_layer_census_t14a_lat8
exactly the way evidence/qwen9b/s4/run_s4_census.sh runs it (cwd tb/,
+script, +state=scripts/w9/model_9b_s1, draining dispatch — the census's own
default and the mode census_t14a.txt was measured in), and prints, per
(seed, key), the census's own per-opcode row for that key's command:
count, total, mean, min, max of busy_cmp per command, plus its PASS line.
Nothing is built; no obj_dir is written; stdout only.
"""
import concurrent.futures as cf
import glob
import hashlib
import os
import re
import subprocess
import sys

import sd1_common as C

BIN = os.path.join(C.REPO, "tb", "obj_dir_tb_layer_census_t14a_lat8",
                   "tb_layer_census_t14a_lat8")
ROW = re.compile(r"^LAYER_CENSUS\s+(\d+)\s+([A-Z][A-Z0-9]*)\s+(\d+)\s+(\d+)"
                 r"\s+(\d+)\s+(\d+)\s+(\d+)")


def run(path):
    base = os.path.basename(path)[:-4]
    seed = int(base.split("_")[0][1:])
    key = base.split("_", 1)[1]
    p = subprocess.run([BIN, f"+script={path}", "+state=scripts/w9/model_9b_s1",
                        "+watchdog_ms=600000"], cwd=os.path.join(C.REPO, "tb"),
                       capture_output=True, text=True, timeout=540)
    rows, verdict = {}, "NO-VERDICT"
    for line in p.stdout.splitlines():
        m = ROW.match(line)
        if m and m.group(2) not in rows:
            rows[m.group(2)] = tuple(int(m.group(i)) for i in (3, 4, 5, 6, 7))
        if line.startswith("TB_LAYER_CENSUS"):
            verdict = line.strip()
    return seed, key, p.returncode, rows, verdict


def main():
    d = sys.argv[1]
    jobs = int(sys.argv[2]) if len(sys.argv) > 2 else 16
    h = hashlib.sha256(open(BIN, "rb").read()).hexdigest()
    print(f"E1RUN binary {BIN}\nE1RUN binary sha256 {h}")
    paths = sorted(glob.glob(os.path.join(d, "s*_*.txt")))
    print(f"E1RUN {len(paths)} scripts, {jobs} in parallel")
    with cf.ThreadPoolExecutor(jobs) as ex:
        res = list(ex.map(run, paths))
    bad = 0
    for seed, key, rc, rows, verdict in sorted(res, key=lambda r: (r[1], r[0])):
        cmd = key.split("_")[0]                 # ALU or VN: the row to read
        r = rows.get(cmd)
        ok = rc == 0 and verdict.startswith("TB_LAYER_CENSUS PASS") and r
        bad += 0 if ok else 1
        if r:
            print(f"E1 seed={seed} key={key.replace('_', '|')} row={cmd} "
                  f"count={r[0]} total={r[1]} mean={r[2]} min={r[3]} "
                  f"max={r[4]} rc={rc} | {verdict}")
        else:
            print(f"E1 seed={seed} key={key} NO ROW rc={rc} | {verdict}")
    print(f"E1RUN: {len(res) - bad}/{len(res)} runs PASS with a row")


if __name__ == "__main__":
    main()
