#!/usr/bin/env python3
"""g5_table.py — build G5a's per-variant table FROM the committed summary logs.

Every number in evidence/qwen9b/g5/G5A_FLOORPLAN.md's table is emitted by this
script out of `evidence/qwen9b/g5/<variant>_summary.log`, which
`synth/exp_uram/scripts/collect_evidence.sh` copies out of the (gitignored) run
directory.  The point is that the table cannot say more than the logs say: the
recurring defect of this campaign is prose that outruns its evidence, so the
table is generated rather than typed.

  python3 evidence/qwen9b/g5/g5_table.py [--dir evidence/qwen9b/g5] [variant ...]

A marker that is absent prints as `n/a`, never as a guess.
"""
import argparse, os, re, sys

ORDER = ["g5_v1a", "g5_v1b", "g5_v2", "g5_v2cr", "g5_v2alt", "g5_v3",
         "g5_v4a", "g5_v4b", "g5_v5", "g5_v5cr", "g5_v6"]
LABEL = {
    "g5_v1a":   ("1'a",  "no floorplan, Default"),
    "g5_v1b":   ("1'b",  "no floorplan, AltSpreadLogic_medium"),
    "g5_v2":    ("2'",   "per-group fan-out co-location, Default"),
    "g5_v2alt": ("2'alt","per-group fan-out co-location, AltSpreadLogic_medium"),
    "g5_v3":    ("3'",   "per-BANK fan-out co-location, DN_BPG=1, Default"),
    "g5_v4a":   ("4'a",  "DN array -> 3 SLRs (banks only), Default"),
    "g5_v4b":   ("4'b",  "4'a + layer_0 pblock, Default"),
    "g5_v2cr":  ("2'cr", "2' at CLOCK-REGION granularity, Default"),
    "g5_v5":    ("5'",   "KV array + its control regs into ONE SLR, Default"),
    "g5_v5cr":  ("5'cr", "5' + 2'cr's clock-region DN pins (the union), Default"),
    "g5_v6":    ("6'",   "2'cr + the conv BRAM banks and their control regs, Default"),
}

def parse(path, extra=()):
    """Read <v>_summary.log, then merge the FIN_/FAM_ marker streams that
    finish_reports.tcl and family_census.tcl produced from the SAME run's
    post_place.dcp.  A FIN_ value never overwrites an EXP_ one: where both
    exist they agree, and where only FIN_ exists it is because the run's own
    exp_ooc.tcl aborted on the two defects finish_reports.tcl's header names."""
    d, slr, pb, xdc = {}, {}, [], []
    fam, hist = [], []
    if not os.path.exists(path):
        return None
    for line in open(path, errors="replace"):
        line = line.rstrip("\n")
        m = re.match(r"^EXP_URAM_SLR (SLR\d+|\S+) (\d+)$", line)
        if m:
            slr[m.group(1)] = int(m.group(2)); continue
        m = re.match(r"^EXP_PBLOCK (\S+) cells=(\d+) range=\{(.*)\}$", line)
        if m:
            pb.append((m.group(1), int(m.group(2)), m.group(3))); continue
        m = re.match(r"^EXTRA_XDC: (\S+)", line)
        if m and m.group(1) != "none":
            xdc.append(os.path.basename(m.group(1))); continue
        m = re.match(r"^(EXP_[A-Z0-9_]+):?\s*(.*)$", line)
        if m:
            k, v = m.group(1), m.group(2).strip()
            d.setdefault(k, v)          # FIRST occurrence wins (run.log is tee'd twice)
    for xp in extra:
        if not os.path.exists(xp):
            continue
        for line in open(xp, errors="replace"):
            line = line.rstrip("\n")
            m = re.match(r"^FAM_ROW\s+(\S+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)", line)
            if m:
                fam.append(m.groups()); continue
            m = re.match(r"^FAM_HIST_ROW\s+(\S+)\s+(\d+)\s+(\S+)", line)
            if m:
                hist.append(m.groups()); continue
            m = re.match(r"^(FIN_[A-Z0-9_]+):?\s*(.*)$", line)
            if m:
                k, v = "EXP_" + m.group(1)[4:], m.group(2).strip()
                # EXP_ wins where it carries a real value.  Where the aborted
                # run recorded the literal "n/a" — the dn_rdq_n_reg defect
                # finish_reports.tcl's header names — the FIN_ value replaces
                # it, because "n/a" there is a WRONG answer, not a missing one.
                if k not in d or d[k] == "n/a":
                    d[k] = v
    d["_slr"], d["_pb"], d["_xdc"] = slr, pb, xdc
    d["_fam"], d["_hist"] = fam, hist
    return d

def ts(d, key):
    """pull one field out of the EXP_TIMING_SUMMARY marker"""
    m = re.search(key + r"=(-?[\d.]+)", d.get("EXP_TIMING_SUMMARY", ""))
    return m.group(1) if m else "n/a"

def place_result(d):
    if "EXP_PLACE_OK" in d:
        m = re.match(r"\((\d+) s\)", d["EXP_PLACE_OK"])
        return "PLACED (%s s)" % (m.group(1) if m else "?")
    if "EXP_PLACE_FAILED" in d: return "PLACE FAILED"
    if "EXP_OPT_FAILED" in d:   return "OPT FAILED"
    return "INCOMPLETE"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="evidence/qwen9b/g5")
    ap.add_argument("variants", nargs="*", default=None)
    a = ap.parse_args()
    vs = a.variants or ORDER
    rows, missing = [], []
    data = {}
    for v in vs:
        d = parse(os.path.join(a.dir, v + "_summary.log"),
                  (os.path.join(a.dir, v + "_finish_run.log"),
                   os.path.join(a.dir, v + "_family_run.log")))
        if d is None:
            missing.append(v); continue
        data[v] = d

    print("| # | variant | URAM288 | place result | SLR span (SLR0/1/2) | DN mux slack | DN write fan-out | **KV write fan-out** | WNS | TNS | failing EP |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for v in vs:
        d = data.get(v)
        if d is None:
            print("| %s | %s | — | NOT RUN | — | — | — | — | — | — |" % (LABEL[v][0], LABEL[v][1])); continue
        slr = d["_slr"]
        span = "%s (%s)" % (d.get("EXP_URAM_SLR_SPAN", "n/a"),
                            "/".join(str(slr.get("SLR%d" % i, 0)) for i in range(3)))
        kvw = "n/a"
        for f in d["_fam"]:
            if f[0] == "KV_URAM_WRITE":
                kvw = f[2]; break
        print("| %s | %s | %s | %s | %s | %s | %s | **%s** | %s | %s | %s |" % (
            LABEL[v][0], LABEL[v][1],
            d.get("EXP_SYNTH_URAM", "n/a").split()[0] if d.get("EXP_SYNTH_URAM") else "n/a",
            place_result(d), span,
            d.get("EXP_DNMUX_WORST_SLACK", "n/a"),
            d.get("EXP_DNWRITE_WORST_SLACK", "n/a"), kvw,
            d.get("EXP_PLACED_WNS", "n/a"), ts(d, "TNS"), ts(d, "TNS_FAILING_EP")))

    print()
    print("Worst-path decomposition, per variant (the whole reading of this experiment")
    print("turns on `one logic level, ~96 % route`):")
    print()
    print("| # | write fan-out worst path | levels | datapath | logic | route | route % | SLR |")
    print("|---|---|---|---|---|---|---|---|")
    for v in vs:
        d = data.get(v)
        if d is None: continue
        dec = d.get("EXP_DNWRITE_DECOMP", "")
        g = dict(re.findall(r"(\w+)=([-\d.a-z/]+)", dec))
        print("| %s | `%s` -> `%s` | %s | %s | %s | %s | %s | %s |" % (
            LABEL[v][0],
            d.get("EXP_DNWRITE_START", "n/a"), d.get("EXP_DNWRITE_END", "n/a"),
            g.get("levels", "n/a"), g.get("datapath", "n/a"), g.get("logic", "n/a"),
            g.get("route", "n/a"), g.get("route_pct", "n/a"),
            d.get("EXP_DNWRITE_SLR", "n/a")))

    print()
    print("Structure, pblocks and the runs' own provenance:")
    print()
    print("| # | DN_BPG | directive | extra XDC | pblocks (cells) | group return | KV mux | WHS | sc_mem | opt s | place s |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for v in vs:
        d = data.get(v)
        if d is None: continue
        pbs = "; ".join("%s=%d" % (n, c) for n, c, _ in d["_pb"]) or "none"
        if len(d["_pb"]) > 4:
            pbs = "%d pblocks, %d..%d cells" % (len(d["_pb"]),
                   min(c for _, c, _ in d["_pb"]), max(c for _, c, _ in d["_pb"]))
        opt = re.match(r"\((\d+) s\)", d.get("EXP_OPT_OK", "")) 
        pl  = re.match(r"\((\d+) s\)", d.get("EXP_PLACE_OK", ""))
        print("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            LABEL[v][0], d.get("EXP_DN_BPG", "n/a"), d.get("EXP_DIRECTIVE", "n/a"),
            ", ".join(d["_xdc"]) or "none", pbs,
            d.get("EXP_DNGRP_WORST_SLACK", "n/a"), d.get("EXP_KVMUX_WORST_SLACK", "n/a"),
            d.get("EXP_PLACED_WHS", "n/a"), d.get("EXP_SC_MEM", "n/a"),
            opt.group(1) if opt else "n/a", pl.group(1) if pl else "n/a"))
    print()
    print("WHAT OWNS THE RESIDUAL — the worst setup path in each named family,")
    print("and the family histogram of the 200 worst setup paths in the design")
    print("(`synth/exp_uram/scripts/family_census.tcl`, off each run's own post_place.dcp):")
    for v in vs:
        d = data.get(v)
        if d is None or not d["_fam"]: continue
        print()
        print("**%s — %s**" % (LABEL[v][0], LABEL[v][1]))
        print()
        print("| family | endpoints | worst slack | levels | datapath | logic | route | route % | SLR | in the 200 worst |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        hd = {h[0]: h for h in d["_hist"]}
        for f in d["_fam"]:
            name, n, sl, lv, dp, lg, rt, pct, s0, s1 = f
            h = hd.get(name)
            print("| %s | %s | %s | %s | %s | %s | %s | %s | %s->%s | %s |" % (
                name, n, sl, lv, dp, lg, rt, pct, s0, s1,
                ("%s paths, worst %s" % (h[1], h[2])) if h else "—"))
    if missing:
        print()
        print("NO SUMMARY LOG (not run, or not yet collected): " + ", ".join(missing))

if __name__ == "__main__":
    sys.exit(main())
