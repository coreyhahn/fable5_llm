#!/usr/bin/env python3
"""g6_superlatives.py — check RD9_GATE.md's superlatives AND its derived
numbers against the committed logs.  A COPY of
evidence/qwen9b/s5/s5_superlatives.py (Task S5, itself a copy of Task 13's),
re-pointed at a BOARD gate instead of a placement campaign.

WHY THIS EXISTS.  Unchanged from S5: a false superlative slipped into the G5a
gate doc in FOUR successive rounds, twice inside the sentence written to
repair the previous one.  Re-reading does not catch it.

WHAT CHANGED FROM THE S5 COPY, and why it had to.
  * S5's "variants" are Vivado placements and its columns are WNS/TNS/fan-out
    slacks read out of `*_summary.log` / `*_family_run.log`.  **G6 has no
    placements.**  Its variants are BOARD RUNS and its columns are device
    time and token correctness, harvested from this directory's own run logs
    by the same "nothing is typed in" rule.
  * A board gate's risky claims are not mostly of the form "X is the best of
    N" — they are DERIVED PERCENTAGES ("the spread is 0.0101 %", "8.9 %
    faster", "34.1 % of the device time").  So this copy adds a SECOND half
    the S5 script has no need of: every derived quantity the doc states is
    RECOMPUTED here from the harvested numbers and compared with what the doc
    says, to the last digit the doc prints.
  * The negative control plants BOTH a false superlative and a false derived
    number, and requires the checker to catch both.

The METHOD, the markers, the QUOTED/SCOPED escape hatches and the
UNCHECKED-is-not-a-pass rule are byte-identical in behaviour to S5's.
"""
import argparse, json, os, re, sys

G6 = os.path.dirname(os.path.abspath(__file__))
DOC = os.path.join(G6, "RD9_GATE.md")

# ---------------------------------------------------------------- harvest
RUN_LOGS = {                       # label -> log file, for the run ranking
    "lay9b_s1":  "008_live_lay9b_s1_scratch65k.log",
    "tok9b":     "009_live_tok9b_4seeds.log",
    "model_s1":  "010_model_9b_s1_upload_and_run.log",
    "model_s2s3s4": "011_model_9b_s2s3s4.log",
    # 016 is the MISORDERED pack rung, and its step [1] is a full live run:
    # leaving it out would have made "every full-model run" a claim over a
    # set the harvester could not see.
    "pack_misordered": "016_weight_pack_and_contrived_miss.log",
    "pack":      "017_weight_pack_and_contrived_miss.log",
    "state":     "018_state_region_smem_golden.log",
    "census":    "020_perf_census_two_lanes.log",
    "restore":   "028_restore_9b_pack.log",
}
DEV_RX = re.compile(r"halted at pc=(\d+)/(\d+) in [\d.]+s wall / ([\d.]+) ms device")
CEN_RX = re.compile(r"S_PERF_CYC\s+(\d+) cycles = ([\d.]+) ms device")
CEN_NREC = re.compile(r"^---\s+\S+:\s+(\d+) records,")
TOK_RX = re.compile(r"^\s*tokens:?\s+(\[[^\]]*\])")
# A run is classified by the LENGTH OF ITS PROGRAM, not by a device-time
# band: the first cut used `10 < ms < 20` for the token smokes and swept in
# the ONE-LAYER smoke at 15.234 ms, which turned a 0.012 % spread into
# 6.9 %.  The record count is unambiguous and comes off the same line.
NREC = {4091: "lay9b", 2108: "tok9b", 158536: "model_s1s4",
        79289: "model_s2s3"}
S1_TOKENS = "[2614, 314, 279, 369, 11751, 13]"


def harvest(d):
    """Every device time and token list this directory's logs carry."""
    runs = []
    for label, fn in sorted(RUN_LOGS.items(), key=lambda kv: kv[1]):
        p = os.path.join(d, fn)
        if not os.path.exists(p):
            continue
        devs, toks, cen_nrec = [], [], None
        for line in open(p, errors="replace"):
            m = CEN_NREC.match(line)
            if m:
                cen_nrec = int(m.group(1))
            m = DEV_RX.search(line)
            if m:
                devs.append((int(m.group(2)), float(m.group(3))))
            m = CEN_RX.search(line)
            if m:
                devs.append((cen_nrec or 0, float(m.group(2))))
            m = TOK_RX.match(line)
            if m:
                toks.append(m.group(1))
        for i, (nrec, v) in enumerate(devs):
            runs.append({"log": fn, "label": label, "idx": i, "device_ms": v,
                         "nrec": nrec, "kind": NREC.get(nrec, "?"),
                         "tokens": toks[i] if i < len(toks) else None})
    return runs


def jload(d, fn):
    p = os.path.join(d, fn)
    return json.load(open(p)) if os.path.exists(p) else None


# 6-step model programs only (the two smokes are 2-token / 0-token)
def model_runs(runs):
    return [r for r in runs if r["kind"] in ("model_s1s4", "model_s2s3")]


def spread_pct(vals):
    return (max(vals) - min(vals)) / min(vals) * 100.0


# --------------------------------------------------------- derived claims
def derived(d, runs):
    """(name, recomputed value, formatted as the doc prints it, why)."""
    out = []
    mr = model_runs(runs)
    s1 = [r["device_ms"] for r in mr
          if r["kind"] == "model_s1s4"
          and r["tokens"] in (None, S1_TOKENS)]
    if len(s1) >= 2:
        out.append(("seed-1 device spread", spread_pct(s1),
                    "%.4f" % spread_pct(s1),
                    "max/min over the %d seed-1 model runs" % len(s1)))
    out.append(("live full-model runs", float(len(mr)), "%d" % len(mr),
                "runs whose program is the 158,536- or 79,289-record model"))
    all_ms = [r["device_ms"] for r in mr]
    if len(all_ms) >= 2:
        out.append(("widest full-model spread", spread_pct(all_ms),
                    "%.4f" % spread_pct(all_ms),
                    "max/min over all %d full-model runs" % len(all_ms)))
    tok = [r["device_ms"] for r in runs if r["kind"] == "tok9b"]
    if len(tok) >= 2:
        out.append(("tok9b 4-seed device spread", spread_pct(tok),
                    "%.3f" % spread_pct(tok),
                    "max/min over the %d tok9b runs" % len(tok)))
    c = jload(d, "020_census.json")
    if c:
        ntok = c["ntok"]
        out.append(("gate tok/s", c["gate_tok_s"], "%.4f" % c["gate_tok_s"],
                    "%d / (%.3f/1000)" % (ntok, c["device_ms"])))
        out.append(("gate ms/token", c["gate_ms_per_tok"],
                    "%.4f" % c["gate_ms_per_tok"],
                    "%.3f / %d" % (c["device_ms"], ntok)))
        out.append(("steady tok/s", c["steady_tok_s"],
                    "%.4f" % c["steady_tok_s"], "1000 / %.4f" % c["steady_ms"]))
        lc = c["l_lcyc_ms"] / ntok
        sd = c["l_sdma_cyc_ms"] / ntok
        out.append(("L_LCYC ms/token", lc, "%.3f" % lc,
                    "%.3f ms / %d" % (c["l_lcyc_ms"], ntok)))
        out.append(("L_SDMA_CYC ms/token", sd, "%.3f" % sd,
                    "%.3f ms / %d" % (c["l_sdma_cyc_ms"], ntok)))
        share = (c["l_lcyc"] + c["l_sdma_cyc"]) / c["seq_perf_cyc"] * 100.0
        out.append(("lane sum, share of device", share, "%.1f" % share,
                    "(%d + %d) / %d" % (c["l_lcyc"], c["l_sdma_cyc"],
                                        c["seq_perf_cyc"])))
        out.append(("L_LCYC vs S4 45.674", (45.674 - lc) / 45.674 * 100.0,
                    "%.1f" % ((45.674 - lc) / 45.674 * 100.0),
                    "(45.674 - %.3f)/45.674" % lc))
        out.append(("L_LCYC vs Task12 46.079", (46.079 - lc) / 46.079 * 100.0,
                    "%.1f" % ((46.079 - lc) / 46.079 * 100.0),
                    "(46.079 - %.3f)/46.079" % lc))
        out.append(("L_SDMA vs modelled 5.133",
                    abs(5.133 - sd) / 5.133 * 100.0,
                    "%.2f" % (abs(5.133 - sd) / 5.133 * 100.0),
                    "|5.133 - %.3f|/5.133" % sd))
        out.append(("board vs S4 chip-TB 131.14",
                    (c["gate_ms_per_tok"] - 131.14) / 131.14 * 100.0,
                    "%.1f" % ((c["gate_ms_per_tok"] - 131.14) / 131.14 * 100.0),
                    "(%.4f - 131.14)/131.14" % c["gate_ms_per_tok"]))
        out.append(("above the 7.0 band top",
                    (c["gate_tok_s"] - 7.0) / 7.0 * 100.0,
                    "%.1f" % ((c["gate_tok_s"] - 7.0) / 7.0 * 100.0),
                    "(%.4f - 7.0)/7.0" % c["gate_tok_s"]))
    cl = jload(d, "025_clip.json")
    if cl:
        p = cl["clipped_total"] / cl["nonzero"] * 100.0
        out.append(("clipped, share of non-zero", p, "%.4f" % p,
                    "%d / %d" % (cl["clipped_total"], cl["nonzero"])))
    au = jload(d, "017_audit_clean.json")
    if au and au.get("audit"):
        a = au["audit"]
        r = a["bytes"] / 2**20 / a["seconds"]
        out.append(("whole-pack audit MiB/s", r, "%.0f" % r,
                    "%.0f MiB / %.1f s" % (a["bytes"] / 2**20, a["seconds"])))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=G6)
    ap.add_argument("--doc", default=DOC)
    ap.add_argument("--negative-control", action="store_true")
    a = ap.parse_args()

    runs = harvest(a.dir)
    mr = model_runs(runs)
    print("G6SUP_RUNS: %d device-time measurement(s) harvested from %d log(s)"
          % (len(runs), len({r["log"] for r in runs})))
    for r in sorted(runs, key=lambda r: r["device_ms"]):
        print("G6SUP_RUN %-46s #%d  %10.3f ms  %-11s %s"
              % (r["log"], r["idx"], r["device_ms"], r["kind"],
                 (r["tokens"] or "-")[:48]))
    print()
    if mr:
        fast = min(mr, key=lambda r: r["device_ms"])
        slow = max(mr, key=lambda r: r["device_ms"])
        print("G6SUP_EXT fastest 6-step model run: %s #%d  %.3f ms"
              % (fast["log"], fast["idx"], fast["device_ms"]))
        print("G6SUP_EXT slowest 6-step model run: %s #%d  %.3f ms"
              % (slow["log"], slow["idx"], slow["device_ms"]))
    print()

    dv = derived(a.dir, runs)
    print("G6SUP_DERIVED %-34s %14s   %s" % ("quantity", "recomputed", "from"))
    for name, val, fmt, why in dv:
        print("G6SUP_DERIVED %-34s %14s   %s" % (name, fmt, why))
    print("G6SUP_DERIVED_TOTAL: %d quantity(ies) recomputed from the logs"
          % len(dv))
    print()

    doc = open(a.doc, errors="replace").read()
    planted_num = None
    if a.negative_control:
        if not mr:
            print("G6SUP_CONTROL: no model runs harvested; cannot plant")
            return 1
        slow = max(mr, key=lambda r: r["device_ms"])
        doc += ("\n\nNEGATIVE CONTROL A: %s is the fastest 6-step model run "
                "of the eight.\n" % slow["log"])
        # a derived number that is false by construction
        name, val, fmt, why = dv[0]
        planted_num = ("NEGATIVE CONTROL B", name,
                       "%.4f" % (val * 2 + 1.0))
        doc += ("NEGATIVE CONTROL B: the %s is %s %%.\n"
                % (name, planted_num[2]))
        print("G6SUP_CONTROL: planted 'fastest' on %s, which is the SLOWEST "
              "(%.3f ms)" % (slow["log"], slow["device_ms"]))
        print("G6SUP_CONTROL: planted %s = %s %%, recomputed %s %%"
              % (name, planted_num[2], fmt))

    # ---- half 1: superlatives, S5's machinery ---------------------------
    MARKERS = re.compile(r"\b(best|worst|only|most|fewest|lowest|highest|"
                         r"fastest|slowest)\b|\bof the (two|three|four|six|"
                         r"eight|nine|ten)\b", re.I)
    QUOTED, SCOPED = "superlative-check: quoted", "superlative-check: scoped"

    def sentences(text):
        paras, cur, start, infence = [], [], 1, False
        for i, line in enumerate(text.split("\n"), 1):
            if line.startswith("```"):
                infence = not infence
                continue
            if infence or line.startswith("|"):
                continue
            if not line.strip():
                if cur:
                    paras.append((start, " ".join(cur)))
                    cur = []
                continue
            if not cur:
                start = i
            cur.append(line.strip())
        if cur:
            paras.append((start, " ".join(cur)))
        out = []
        for ln, para in paras:
            mark = ("quoted" if QUOTED in para else
                    ("scoped" if SCOPED in para else None))
            for snt in re.split(r"(?<=[.!?])\s+", para):
                if MARKERS.search(snt):
                    out.append((ln, snt.strip(), mark))
        return out

    fails, unchecked, quoted_n, scoped_n, checked = [], [], 0, 0, 0
    for ln, snt, mark in sentences(doc):
        if mark == "quoted":
            quoted_n += 1
            print("G6SUP_QUOTED %s:%d  %s"
                  % (os.path.basename(a.doc), ln, snt[:120]))
            continue
        if mark == "scoped":
            scoped_n += 1
            print("G6SUP_SCOPED %s:%d  %s"
                  % (os.path.basename(a.doc), ln, snt[:120]))
            continue
        # the only column this doc ranks between runs is device time
        if not re.search(r"fastest|slowest", snt, re.I) or not mr:
            unchecked.append((ln, snt))
            continue
        named = [r for r in mr if r["log"] in snt]
        if not named:
            unchecked.append((ln, snt))
            continue
        checked += 1
        want = (min(mr, key=lambda r: r["device_ms"])
                if re.search(r"fastest", snt, re.I)
                else max(mr, key=lambda r: r["device_ms"]))
        if want["log"] not in [r["log"] for r in named]:
            fails.append((ln, snt, "device time", want["log"],
                          round(want["device_ms"], 3),
                          ", ".join(sorted({r["log"] for r in named}))))

    # ---- half 2: every derived number, recomputed ------------------------
    numfails = []
    for name, val, fmt, why in dv:
        # find the doc's own statement of this quantity, if it makes one
        for m in re.finditer(re.escape(name).replace(r"\ ", r"\s+")
                             + r"[^.\n]{0,80}?(-?\d+\.\d+)", doc):
            got = m.group(1)
            if got != fmt:
                numfails.append((name, got, fmt, why))
        if planted_num and planted_num[1] == name:
            for m in re.finditer(r"NEGATIVE CONTROL B: the "
                                 + re.escape(name) + r" is (-?\d+\.\d+)", doc):
                if m.group(1) != fmt:
                    numfails.append((name + " (control B)", m.group(1),
                                     fmt, why))

    print("G6SUP_CHECKED: %d superlative sentence(s) machine-checked" % checked)
    for ln, snt, colname, holder, val, named in fails:
        print("G6SUP_FAIL %s:%d" % (os.path.basename(a.doc), ln))
        print("    %s" % snt[:160])
        print("    column %s: the extremum is %s (%s), the sentence names %s"
              % (colname, holder, val, named))
    for name, got, want, why in numfails:
        print("G6SUP_NUMFAIL %s: the doc says %s, recomputed %s (%s)"
              % (name, got, want, why))
    print("G6SUP_QUOTED_TOTAL: %d" % quoted_n)
    print("G6SUP_SCOPED_TOTAL: %d" % scoped_n)
    print("G6SUP_UNCHECKED: %d sentence(s) the script cannot attribute"
          % len(unchecked))
    for ln, snt in unchecked:
        print("G6SUP_UNCHECKED %s:%d  %s"
              % (os.path.basename(a.doc), ln, snt[:130]))

    if a.negative_control:
        if fails and numfails:
            print("G6SUP_CONTROL: CAUGHT BOTH — the checker is live")
            return 0
        print("G6SUP_CONTROL: NOT CAUGHT (%d superlative, %d numeric) — "
              "the checker is inert, which is a defect"
              % (len(fails), len(numfails)))
        return 1
    if fails or numfails:
        print("G6SUP: FAIL (%d superlative, %d numeric)"
              % (len(fails), len(numfails)))
        return 1
    print("G6SUP: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
