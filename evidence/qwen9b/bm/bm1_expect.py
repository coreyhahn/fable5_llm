#!/usr/bin/env python3
"""bm1_expect.py — the BM1 counters' EXPECTED values, read out of the census.

Task BM1-T1 (spec docs/superpowers/specs/2026-09-24-board-idle-counters-design.md
§3.3 B/C).  Written BEFORE the RTL counters exist (TDD): the chip testbench
reads the counter block after HALT and, given `+bm_expect=<file>`, compares
every counter against the file this script writes and `$fatal`s on any
difference.  Nothing here is estimated: every value is a SUM of integers the
census printed, or an exact recount of the census's own CSV.

    bm1_expect.py <census log with a SEQ_TIMELINE block> [--csv <census CSV>]
                  [--csv-sha256 <file with the committed hash>] --out <expect>

Values (each a launch total over every segment, i.e. the whole busy_r window):

  PERF_CYC      SEQ_TIMELINE meta bcyc                (existing CSR 0x2C)
  BM_MV<c>      sum_t  class t 8+c  (MVc_BSY)
  BM_FENCE      sum_t  mvop  t 3
  BM_MOVX       sum_t  mvop  t 0                      (OV1's split)
  BM_MOVY       sum_t  mvop  t 2                      (OV1's split)
  BM_MVWORK     sum_t  mvop  t 0 + 1 + 2
  BM_IMOVER     sum_t  ist   t 17   (I_MOVER, rtl/seq_unit.sv istate_e)
  BM_STEPS      sum_t  opcyc t 6    (OP_EMB records latched)
  L_LCYC        sum_t  class t 0    (L_CMP; the layer's existing LCYC)
  BM_MVANY      CSV:   sum over S rows whose mask has any of bits 8..11
  CENSUS_I2     CSV:   sum over S rows with MOVER, no MVc_STR, any MVc_BSY
                (evidence/qwen9b/bn/bn1_fix1_checks.py's I-2 "mover work
                WHILE any matvec engine busy" — NOT the spec's C7 definition;
                the TB compares it with its own sampler, not with an RTL
                register, see the gate doc)

BM_MVWORK_ANY (spec C7) has NO census comparand in integer form (013 prints
a different quantity, above) and is not written here; the testbench checks it
exactly against its own negedge sampler.
"""
import argparse
import collections
import hashlib
import re
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--csv")
    ap.add_argument("--csv-sha256")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    cls = collections.Counter()      # (idx) -> cycles, summed over segments
    mvop = collections.Counter()
    ist = collections.Counter()
    opcnt = collections.Counter()
    meta = None
    nseg = set()
    rx = re.compile(r"^\s*SEQ_TIMELINE (\w+) (.*)$")
    for line in open(a.log):
        m = rx.match(line)
        if not m:
            continue
        kind, rest = m.group(1), m.group(2).split()
        if kind == "meta":
            meta = dict(kv.split("=") for kv in rest)
        elif kind == "class":            # class <t> <i> <name> <cyc>
            nseg.add(int(rest[0]))
            cls[int(rest[1])] += int(rest[3])
        elif kind == "mvop":             # mvop <t> <op> <cyc>
            mvop[int(rest[1])] += int(rest[2])
        elif kind == "ist":              # ist <t> <state> <cyc>
            ist[int(rest[1])] += int(rest[2])
        elif kind == "opcyc":            # opcyc <t> <op> <count> <cyc>
            opcnt[int(rest[1])] += int(rest[2])
    if meta is None:
        sys.exit("no SEQ_TIMELINE meta line in %s" % a.log)
    if int(meta["ntok"]) != len(nseg):
        sys.exit("meta ntok %s but %d segments carry class lines"
                 % (meta["ntok"], len(nseg)))

    out = []
    src = a.log

    def put(name, val, how):
        out.append((name, val, how))

    put("PERF_CYC", int(meta["bcyc"]), "meta bcyc")
    for c in range(4):
        put("BM_MV%d" % c, cls[8 + c], "sum class t %d (MV%d_BSY)" % (8 + c, c))
    put("BM_FENCE", mvop[3], "sum mvop t 3")
    put("BM_MOVX", mvop[0], "sum mvop t 0")
    put("BM_MOVY", mvop[2], "sum mvop t 2")
    put("BM_MVWORK", mvop[0] + mvop[1] + mvop[2], "sum mvop t 0+1+2")
    put("BM_IMOVER", ist[17], "sum ist t 17 (I_MOVER)")
    put("BM_STEPS", opcnt[6], "sum opcyc t 6 count (OP_EMB)")
    put("L_LCYC", cls[0], "sum class t 0 (L_CMP)")

    print("census log   %s" % src)
    print("segments     %d (meta ntok=%s), bcyc=%s" % (len(nseg), meta["ntok"],
                                                     meta["bcyc"]))
    print("mvop totals  MOVX %d  MVGO %d  MOVY %d  FENCE %d"
          % (mvop[0], mvop[1], mvop[2], mvop[3]))
    print("class 2 MOVER total %d ; FENCE+MVWORK %d  (identity D: must be equal)"
          % (cls[2], mvop[0] + mvop[1] + mvop[2] + mvop[3]))

    if a.csv:
        h = hashlib.sha256(open(a.csv, "rb").read()).hexdigest()
        print("csv          %s" % a.csv)
        print("csv sha256   %s" % h)
        if a.csv_sha256:
            want = open(a.csv_sha256).read().split()[0]
            print("committed    %s  (%s)" % (want, a.csv_sha256))
            if h != want:
                sys.exit("CSV sha256 DIFFERS from the committed hash — "
                         "refusing to derive anything from it")
            print("CSV sha256 IDENTICAL TO THE COMMITTED HASH")
        sig = collections.defaultdict(collections.Counter)
        end = False
        for line in open(a.csv):
            if line.startswith("S,"):
                _, t, mask, cyc = line.rstrip("\n").split(",")
                sig[int(t)][int(mask)] += int(cyc)
            elif line.startswith("#END"):
                end = True
        if not end:
            sys.exit("CSV has no #END marker")
        STR, BSY, MV = 0x00F0, 0x0F00, 0x0004
        mvany = sum(c for t in sig for m, c in sig[t].items() if m & BSY)
        i2 = sum(c for t in sig for m, c in sig[t].items()
                 if (m & MV) and not (m & STR) and (m & BSY))
        allcyc = sum(c for t in sig for c in sig[t].values())
        print("csv S rows   %d segments, %d cycles in all (bcyc %s)"
              % (len(sig), allcyc, meta["bcyc"]))
        if allcyc != int(meta["bcyc"]):
            sys.exit("CSV signature cycles %d != bcyc %s" % (allcyc, meta["bcyc"]))
        body = [t for t in sig if t != 0]
        n = len(body)
        mv_body = sum(c for t in body for m, c in sig[t].items() if m & BSY)
        i2_body = sum(c for t in body for m, c in sig[t].items()
                      if (m & MV) and not (m & STR) and (m & BSY))
        mv_seg0 = mvany - mv_body
        print("MVANY        %d  (segment 0: %d; tokens 1..%d mean %.1f)"
              % (mvany, mv_seg0, n, mv_body / n if n else 0.0))
        print("CENSUS_I2    %d  (tokens 1..%d mean %.1f)"
              % (i2, n, i2_body / n if n else 0.0))
        put("BM_MVANY", mvany, "csv: sum S rows with mask & 0x0F00")
        put("CENSUS_I2", i2, "csv: sum S rows MOVER & !STR & BSY (013 I-2)")

    with open(a.out, "w") as f:
        f.write("# BM1 expected counter values — written by "
                "evidence/qwen9b/bm/bm1_expect.py\n")
        f.write("# from %s%s\n" % (src, (" + " + a.csv) if a.csv else ""))
        for name, val, how in out:
            f.write("%s %d\n" % (name, val))
    print("--- expect file %s" % a.out)
    for name, val, how in out:
        print("  %-10s %12d   # %s" % (name, val, how))


if __name__ == "__main__":
    main()
