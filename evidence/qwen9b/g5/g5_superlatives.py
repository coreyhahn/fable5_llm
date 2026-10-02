#!/usr/bin/env python3
"""g5_superlatives.py — check every superlative in G5A_FLOORPLAN.md against the
committed logs.

WHY THIS EXISTS.  A false superlative slipped into the G5a gate doc in FOUR
successive rounds, twice inside the sentence written to repair the previous
one.  Re-reading does not catch it: the numbers live in eleven rows of a
generated table and the claim lives in prose two hundred lines away.  Round 2's
report called its check "mechanised" when it was in fact prose in a report.
This is the script.

METHOD.
  * The numbers come from the SAME committed logs `g5_table.py` reads —
    `<variant>_summary.log`, `<variant>_finish_run*.log`, `<variant>_family_run.log`.
    Nothing is typed in.  If a log is missing the column is absent, never
    guessed.
  * For each column it computes the EXTREMUM and the RUNNER-UP across all
    variants, so a claim of the form "best / only / N× better" has something to
    be checked against.
  * It then reads the gate doc, finds every sentence carrying a superlative
    marker, and for each one decides which column it is about and whether the
    variant it names really holds the extremum.  Disagreement is a FAIL and the
    script exits non-zero.
  * Sentences it cannot attribute to a column print as UNCHECKED — they are not
    silently passed.  The doc should be rewritten into a checkable form, or the
    report must list them as hand-verified with the number.

  --negative-control plants a false superlative in an IN-MEMORY copy of the
  document text -- nothing is written to disk, and `tempfile` is imported but
  unused -- and
  requires the checker to CATCH it; if the control passes, the checker is inert
  and the script exits non-zero.
"""
import argparse, os, re, sys, tempfile

G5 = os.path.dirname(os.path.abspath(__file__))
DOC = os.path.join(G5, "G5A_FLOORPLAN.md")

ORDER = ["g5_v1a", "g5_v1b", "g5_v2", "g5_v2cr", "g5_v2alt", "g5_v3",
         "g5_v4a", "g5_v4b", "g5_v5", "g5_v5cr", "g5_v6"]
LABEL = {"g5_v1a": "1'a", "g5_v1b": "1'b", "g5_v2": "2'", "g5_v2cr": "2'cr",
         "g5_v2alt": "2'alt", "g5_v3": "3'", "g5_v4a": "4'a", "g5_v4b": "4'b",
         "g5_v5": "5'", "g5_v5cr": "5'cr", "g5_v6": "6'"}
# which unconstrained run each variant's "buys" delta is measured against
BASELINE = {v: ("g5_v1b" if v in ("g5_v1b", "g5_v2alt") else "g5_v1a") for v in ORDER}

# column -> (human name, "higher is better"?)
COLS = {
    "wns":   ("WNS", True),
    "tns":   ("TNS", True),
    "ep":    ("failing endpoints", False),
    "dnw":   ("DN write fan-out, absolute", True),
    "buys":  ("DN write fan-out gain vs own same-directive baseline", True),
    "kvw":   ("KV write fan-out", True),
    "conv":  ("conv BRAM write", True),
    "attn":  ("attn DSP lanes", True),
    "sll":   ("SLR crossings (SLLs)", False),
}

def read_variant(d, v):
    """Every number from the committed logs; None where a log is absent."""
    r = {}
    def scan(fn, pats):
        p = os.path.join(d, fn)
        if not os.path.exists(p):
            return
        for line in open(p, errors="replace"):
            for key, rx in pats.items():
                m = re.match(rx, line)
                if m and key not in r:
                    r[key] = float(m.group(1))
    for fn in (v + "_summary.log", v + "_finish_run.log",
               v + "_finish_run2.log", v + "_finish_run3.log"):
        scan(fn, {
            "wns":  r"^(?:EXP|FIN)_PLACED_WNS:\s*(-?[\d.]+)",
            "dnw":  r"^(?:EXP|FIN)_DNWRITE_WORST_SLACK:\s*(-?[\d.]+)",
            "kvw":  r"^FIN_KVWRITE_WORST_SLACK:\s*(-?[\d.]+)",
            "tns":  r"^(?:EXP|FIN)_TIMING_SUMMARY:.*?\bTNS=(-?[\d.]+)",
            "ep":   r"^(?:EXP|FIN)_TIMING_SUMMARY:.*?\bTNS_FAILING_EP=(\d+)",
        })
    # the family census carries conv and attn
    p = os.path.join(d, v + "_family_run.log")
    if os.path.exists(p):
        for line in open(p, errors="replace"):
            m = re.match(r"^FAM_ROW\s+(\S+)\s+\d+\s+(-?[\d.]+)", line)
            if m:
                fam, val = m.group(1), float(m.group(2))
                if fam == "CONV_BRAM":
                    r.setdefault("conv", val)
                elif fam == "ATTN_DSP":
                    r.setdefault("attn", val)
                elif fam == "KV_URAM_WRITE":
                    r.setdefault("kvw", val)
                elif fam == "DN_URAM_WRITE":
                    r.setdefault("dnw", val)
    # SLLs come out of the per-SLR utilization report
    p = os.path.join(d, v + "_util_placed_slr.rpt")
    if os.path.exists(p):
        for line in open(p, errors="replace"):
            m = re.match(r"\|\s*Total SLLs Used\s*\|\s*(\d+)", line)
            if m:
                r.setdefault("sll", float(m.group(1)))
    return r

def rank(data, col):
    hi = COLS[col][1]
    have = [(v, d[col]) for v, d in data.items() if col in d]
    if col == "buys":
        have = []
        for v, d in data.items():
            b = BASELINE[v]
            if v != b and "dnw" in d and b in data and "dnw" in data[b]:
                have.append((v, d["dnw"] - data[b]["dnw"]))
    return sorted(have, key=lambda t: t[1], reverse=hi)

MARKERS = re.compile(r"\b(best|worst|only|most|fewest|lowest|highest)\b|×|\bof the (seven|nine|ten|eleven)\b", re.I)
# which column a sentence is about, by the words around it
CUE = [("buys", r"buys|gain vs|vs 1'a|vs its own baseline|\+1\.\d"),
       ("dnw",  r"DN write|write fan-out|write-fan-out|fan-out number"),
       ("kvw",  r"KV write"),
       ("conv", r"conv BRAM"),
       ("attn", r"attn|u_attn"),
       ("tns",  r"\bTNS\b"),
       ("ep",   r"failing endpoint|failing EP"),
       ("wns",  r"\bWNS\b"),
       ("sll",  r"\bSLL|crossings\b")]

QUOTED = "superlative-check: quoted"
SCOPED = "superlative-check: scoped"

def sentences(text):
    """Paragraph-join first, THEN split into sentences.

    A sentence in this document routinely spans a line break, and splitting
    per line cuts the subject away from its claim — which made an early run of
    this checker blame the wrong variant.  Fenced code and table rows are
    skipped: a superlative inside a generated table is data, not a claim.
    A paragraph carrying `superlative-check: quoted` is reported as QUOTED, for
    prose that deliberately restates a superseded false claim in order to
    correct it.  One carrying `superlative-check: scoped` is reported as SCOPED
    together with the FULL ranking of its column, for a claim that is true over
    a stated subset the script has no way to know about (e.g. "of the
    constrained variants") — SCOPED is not a pass, it is a claim printed beside
    the numbers so a reader can check it in one place."""
    paras, cur, start, infence = [], [], 1, False
    for i, line in enumerate(text.split("\n"), 1):
        if line.startswith("```"):
            infence = not infence; continue
        if infence or line.startswith("|"):
            continue
        if not line.strip():
            if cur: paras.append((start, " ".join(cur))); cur = []
            continue
        if not cur: start = i
        cur.append(line.strip())
    if cur: paras.append((start, " ".join(cur)))
    out = []
    for ln, para in paras:
        quoted = QUOTED in para
        scoped = SCOPED in para
        for snt in re.split(r"(?<=[.!?])\s+", para):
            if MARKERS.search(snt):
                out.append((ln, snt.strip(), "quoted" if quoted else
                            ("scoped" if scoped else None)))
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=G5)
    ap.add_argument("--doc", default=DOC)
    ap.add_argument("--negative-control", action="store_true")
    a = ap.parse_args()

    data = {v: read_variant(a.dir, v) for v in ORDER}
    data = {v: d for v, d in data.items() if d}
    print("G5SUP_VARIANTS: %d  (%s)" % (len(data), " ".join(LABEL[v] for v in data)))
    print()
    print("G5SUP_TABLE column                                    best        runner-up")
    ext = {}
    for col, (name, hi) in COLS.items():
        rk = rank(data, col)
        if not rk:
            print("G5SUP_COL %-52s (no data)" % name); continue
        ext[col] = rk
        b, s = rk[0], (rk[1] if len(rk) > 1 else (None, None))
        print("G5SUP_COL %-52s %-6s %-9s %-6s %s"
              % (name, LABEL[b[0]], round(b[1], 4),
                 LABEL[s[0]] if s[0] else "-", round(s[1], 4) if s[0] else "-"))
    print()

    doc = open(a.doc, errors="replace").read()
    if a.negative_control:
        # plant a claim that is false by construction: award the WNS best to the
        # variant that actually has the WORST WNS.
        worst = ext["wns"][-1][0]
        doc += ("\n\nNEGATIVE CONTROL: %s has the best WNS of the eleven.\n"
                % LABEL[worst])
        print("G5SUP_CONTROL: planted 'best WNS' on %s, which is the WORST (%s)"
              % (LABEL[worst], ext["wns"][-1][1]))

    fails, unchecked, quoted_n, scoped_n, checked = [], [], 0, 0, 0
    for ln, snt, mark in sentences(doc):
        if mark == "quoted":
            quoted_n += 1
            print("G5SUP_QUOTED %s:%d  %s" % (os.path.basename(a.doc), ln, snt[:120]))
            continue
        if mark == "scoped":
            scoped_n += 1
            col = next((c for c, rx in CUE if re.search(rx, snt, re.I)), None)
            print("G5SUP_SCOPED %s:%d  %s" % (os.path.basename(a.doc), ln, snt[:120]))
            if col and col in ext:
                print("    full ranking of %s: %s" % (COLS[col][0],
                      "  ".join("%s %s" % (LABEL[v], round(x, 4)) for v, x in ext[col])))
            continue
        col = next((c for c, rx in CUE if re.search(rx, snt, re.I)), None)
        if col is None or col not in ext:
            unchecked.append((ln, snt)); continue
        named = [v for v in ORDER if v in data and
                 re.search(r"(?<![\w'])" + re.escape(LABEL[v]) + r"(?![\w'])", snt)]
        claims_best = re.search(r"\b(best|most|fewest|only|lowest|highest)\b", snt, re.I)
        if not named or not claims_best:
            unchecked.append((ln, snt)); continue
        checked += 1
        holder = ext[col][0][0]
        if holder not in named:
            fails.append((ln, snt, COLS[col][0], LABEL[holder], round(ext[col][0][1], 4),
                          ", ".join(LABEL[v] for v in named)))
    print("G5SUP_CHECKED: %d superlative sentence(s) machine-checked" % checked)
    for ln, snt, colname, holder, val, named in fails:
        print("G5SUP_FAIL %s:%d" % (os.path.basename(a.doc), ln))
        print("    %s" % snt[:160])
        print("    column %s: the extremum is %s (%s), the sentence names %s"
              % (colname, holder, val, named))
    print("G5SUP_QUOTED_TOTAL: %d sentence(s) restating a superseded claim" % quoted_n)
    print("G5SUP_SCOPED_TOTAL: %d sentence(s) true over a stated subset, printed beside the full ranking" % scoped_n)
    print("G5SUP_UNCHECKED: %d sentence(s) the script cannot attribute" % len(unchecked))
    for ln, snt in unchecked:
        print("G5SUP_UNCHECKED %s:%d  %s" % (os.path.basename(a.doc), ln, snt[:130]))

    if a.negative_control:
        if fails:
            print("G5SUP_CONTROL: CAUGHT — the checker is live")
            return 0
        print("G5SUP_CONTROL: NOT CAUGHT — the checker is inert, which is a defect")
        return 1
    if fails:
        print("G5SUP: FAIL (%d)" % len(fails)); return 1
    print("G5SUP: PASS"); return 0

if __name__ == "__main__":
    sys.exit(main())
