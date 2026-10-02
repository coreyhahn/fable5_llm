#!/usr/bin/env python3
"""g5d_superlatives.py — check every superlative in G5D_TIMING.md against the
committed logs.  A COPY of evidence/qwen9b/s5/s5_superlatives.py (Task S5),
which is itself a copy of evidence/qwen9b/g5/g5_superlatives.py (Task 13),
re-pointed at Task 14-B's IMPLEMENTATION ROLLS, Task 14-B's family names and
Task 14-B's gate doc.

WHY THIS EXISTS, unchanged from S5's copy.  A false superlative slipped into
the G5a gate doc in FOUR successive rounds, twice inside the sentence written
to repair the previous one.  Re-reading does not catch it: the numbers live in
the rows of a generated table and the claim lives in prose two hundred lines
away.  This is the script.

WHAT CHANGED FROM THE S5 COPY, and nothing else did:

  * THE VARIANTS ARE ROLLS, AND THEY ARE DISCOVERED, NOT LISTED.  S5 had three
    named out-of-context placements and hard-coded them.  Task 14-B's campaign
    is N implementation rolls whose count is not known when the script is
    written, so the roll set is read off the committed evidence directory:
    every file named `<nnn>_t14b_roll_<label>.txt` is one roll, and <label> is
    the label the gate doc's prose uses.  A roll with no committed summary file
    is INVISIBLE to this checker rather than guessed at — the same rule S5's
    "if a log is missing the column is absent, never guessed" states.

  * THE NUMBERS COME OUT OF A DESIGN TIMING SUMMARY, not out of an OOC
    harness's own markers.  Each roll file is a verbatim copy of that roll's
    `reports/timing_summary.rpt` header — the `Design Timing Summary` row
    (WNS / TNS / TNS-failing-endpoints / WHS / THS / THS-failing-endpoints)
    and the intra-clock table.  Nothing is typed in; the parser reads the same
    bytes a human reads.

  * THE COLUMNS.  wns / tns / ep / whs / hold_ep are the campaign's axes.  The
    six family columns keep S5's names (DN_SLOT / KV_SLOT / CV_SLOT / SDMA /
    ATTN_DSP / SCRATCH) and are read from `<nnn>_t14b_fam_<label>.log`, the
    committed output of evidence/qwen9b/g5/g5b_family_census.tcl.  S5's `buys`
    column and `sll` column are DROPPED: 14-B runs no same-directive
    write-fan-out pair and no per-SLR SLL report, so a column with no data
    would only print "(no data)" forever.

  * THE MARKER REGEX drops "of the three" and takes any "of the N rolls".

The METHOD, the markers, the QUOTED/SCOPED escape hatches and the negative
control are byte-identical in behaviour to S5's and to Task 13's.

  ./g5d_superlatives.py
  ./g5d_superlatives.py --negative-control
"""
import argparse, glob, os, re, sys

G5 = os.path.dirname(os.path.abspath(__file__))
DOC = os.path.join(G5, "G5D_TIMING.md")

ROLL_RE = re.compile(r"^\d{3}_t14b_roll_(?P<label>[A-Za-z0-9_.+-]+)\.txt$")
FAM_RE = re.compile(r"^\d{3}_t14b_fam_(?P<label>[A-Za-z0-9_.+-]+)\.log$")

# column -> (human name, "higher is better"?)
COLS = {
    "wns":     ("WNS", True),
    "tns":     ("TNS", True),
    "ep":      ("failing setup endpoints", False),
    "whs":     ("WHS", True),
    "hold_ep": ("failing hold endpoints", False),
    "dnw":     ("DN slot (DN_SLOT)", True),
    "kvw":     ("KV slot (KV_SLOT)", True),
    "conv":    ("conv slot (CV_SLOT)", True),
    "sdma":    ("state DMA engine (SDMA)", True),
    "attn":    ("attn DSP lanes (ATTN_DSP)", True),
    "scr":     ("scratchpad (SCRATCH)", True),
}

FAMCOL = {"DN_SLOT": "dnw", "KV_SLOT": "kvw", "CV_SLOT": "conv",
          "SDMA": "sdma", "ATTN_DSP": "attn", "SCRATCH": "scr"}


def discover(d):
    """label -> {roll: <path>, fam: <path>}, from the committed file names."""
    found = {}
    for fn in sorted(os.listdir(d)):
        m = ROLL_RE.match(fn)
        if m:
            found.setdefault(m.group("label"), {})["roll"] = os.path.join(d, fn)
            continue
        m = FAM_RE.match(fn)
        if m:
            found.setdefault(m.group("label"), {})["fam"] = os.path.join(d, fn)
    return found


# The Design Timing Summary data row: WNS TNS TNS-fail TNS-total WHS THS
# THS-fail THS-total [WPWS TPWS ...].  Vivado prints it as bare numbers on one
# line under a two-line header, so it is matched by SHAPE, not by position in
# the file: eight or more whitespace-separated numbers of which the 3rd, 4th,
# 7th and 8th are integers.
NUM = r"(-?\d+\.\d+|-?\d+|NA)"
SUMMARY_RE = re.compile(
    r"^\s*" + NUM + r"\s+" + NUM + r"\s+(\d+)\s+(\d+)\s+" + NUM + r"\s+" + NUM
    + r"\s+(\d+)\s+(\d+)\b")


def f(x):
    return None if x in (None, "NA") else float(x)


def read_roll(path):
    r = {}
    for line in open(path, errors="replace"):
        m = SUMMARY_RE.match(line)
        if m and "wns" not in r:
            r["wns"] = f(m.group(1))
            r["tns"] = f(m.group(2))
            r["ep"] = float(m.group(3))
            r["whs"] = f(m.group(5))
            r["hold_ep"] = float(m.group(7))
    return {k: v for k, v in r.items() if v is not None}


def read_fam(path):
    r = {}
    for line in open(path, errors="replace"):
        m = re.match(r"^FAM_ROW\s+(\S+)\s+\d+\s+(-?[\d.]+)", line)
        if m:
            col = FAMCOL.get(m.group(1))
            if col:
                r.setdefault(col, float(m.group(2)))
    return r


def rank(data, col):
    hi = COLS[col][1]
    have = [(v, d[col]) for v, d in data.items() if col in d]
    return sorted(have, key=lambda t: t[1], reverse=hi)


MARKERS = re.compile(
    r"\b(best|worst|only|most|fewest|lowest|highest)\b|×|\bof the (two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b",
    re.I)
CUE = [("dnw",     r"DN_SLOT|DN slot"),
       ("kvw",     r"KV_SLOT|KV slot"),
       ("conv",    r"CV_SLOT|conv slot|conv BRAM"),
       ("sdma",    r"SDMA|state DMA|u_dma"),
       ("scr",     r"SCRATCH|scratchpad"),
       ("attn",    r"ATTN_DSP|attn|u_attn"),
       ("tns",     r"\bTNS\b"),
       ("hold_ep", r"failing hold"),
       ("ep",      r"failing endpoint|failing setup|failing EP"),
       ("whs",     r"\bWHS\b|\bhold\b"),
       ("wns",     r"\bWNS\b|\bslack\b")]

QUOTED = "superlative-check: quoted"
SCOPED = "superlative-check: scoped"


def sentences(text):
    """Paragraph-join first, THEN split into sentences.  Verbatim from S5's
    copy: a sentence in this document routinely spans a line break, and
    splitting per line cuts the subject away from its claim.  Fenced code and
    table rows are skipped — a superlative inside a generated table is data,
    not a claim."""
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
        quoted = QUOTED in para
        scoped = SCOPED in para
        for snt in re.split(r"(?<=[.!?])\s+", para):
            if MARKERS.search(snt):
                out.append((ln, snt.strip(),
                            "quoted" if quoted else ("scoped" if scoped else None)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=G5)
    ap.add_argument("--doc", default=DOC)
    ap.add_argument("--negative-control", action="store_true")
    a = ap.parse_args()

    found = discover(a.dir)
    data = {}
    for label, paths in found.items():
        d = read_roll(paths["roll"]) if "roll" in paths else {}
        if "fam" in paths:
            d.update(read_fam(paths["fam"]))
        if d:
            data[label] = d
    order = sorted(data)
    print("G5DSUP_ROLLS: %d  (%s)" % (len(data), " ".join(order)))
    for label in order:
        print("G5DSUP_ROLL %-28s %s" % (label, " ".join(
            "%s=%s" % (k, data[label][k]) for k in sorted(data[label]))))
    print()
    print("G5DSUP_TABLE column                                    best        runner-up")
    ext = {}
    for col, (name, hi) in COLS.items():
        rk = rank(data, col)
        if not rk:
            print("G5DSUP_COL %-52s (no data)" % name)
            continue
        ext[col] = rk
        b = rk[0]
        s = rk[1] if len(rk) > 1 else (None, None)
        print("G5DSUP_COL %-52s %-22s %-10s %-22s %s"
              % (name, b[0], round(b[1], 4),
                 s[0] if s[0] else "-", round(s[1], 4) if s[0] else "-"))
    print()

    doc = open(a.doc, errors="replace").read()
    if a.negative_control:
        if "wns" not in ext or len(ext["wns"]) < 2:
            print("G5DSUP_CONTROL: CANNOT RUN — fewer than two rolls carry a WNS")
            return 1
        worst = ext["wns"][-1][0]
        doc += ("\n\nNEGATIVE CONTROL: %s has the best WNS of the rolls.\n" % worst)
        print("G5DSUP_CONTROL: planted 'best WNS' on %s, which is the WORST (%s)"
              % (worst, ext["wns"][-1][1]))

    fails, unchecked, quoted_n, scoped_n, checked = [], [], 0, 0, 0
    for ln, snt, mark in sentences(doc):
        if mark == "quoted":
            quoted_n += 1
            print("G5DSUP_QUOTED %s:%d  %s" % (os.path.basename(a.doc), ln, snt[:120]))
            continue
        if mark == "scoped":
            scoped_n += 1
            col = next((c for c, rx in CUE if re.search(rx, snt, re.I)), None)
            print("G5DSUP_SCOPED %s:%d  %s" % (os.path.basename(a.doc), ln, snt[:120]))
            if col and col in ext:
                print("    full ranking of %s: %s" % (COLS[col][0],
                      "  ".join("%s %s" % (v, round(x, 4)) for v, x in ext[col])))
            continue
        col = next((c for c, rx in CUE if re.search(rx, snt, re.I)), None)
        if col is None or col not in ext:
            unchecked.append((ln, snt))
            continue
        named = [v for v in order if
                 re.search(r"(?<![\w'])" + re.escape(v) + r"(?![\w'])", snt)]
        claims_best = re.search(r"\b(best|most|fewest|only|lowest|highest)\b", snt, re.I)
        if not named or not claims_best:
            unchecked.append((ln, snt))
            continue
        checked += 1
        holder = ext[col][0][0]
        if holder not in named:
            fails.append((ln, snt, COLS[col][0], holder, round(ext[col][0][1], 4),
                          ", ".join(named)))
    print("G5DSUP_CHECKED: %d superlative sentence(s) machine-checked" % checked)
    for ln, snt, colname, holder, val, named in fails:
        print("G5DSUP_FAIL %s:%d" % (os.path.basename(a.doc), ln))
        print("    %s" % snt[:160])
        print("    column %s: the extremum is %s (%s), the sentence names %s"
              % (colname, holder, val, named))
    print("G5DSUP_QUOTED_TOTAL: %d sentence(s) restating a superseded claim" % quoted_n)
    print("G5DSUP_SCOPED_TOTAL: %d sentence(s) true over a stated subset, printed beside the full ranking" % scoped_n)
    print("G5DSUP_UNCHECKED: %d sentence(s) the script cannot attribute" % len(unchecked))
    for ln, snt in unchecked:
        print("G5DSUP_UNCHECKED %s:%d  %s" % (os.path.basename(a.doc), ln, snt[:130]))

    if a.negative_control:
        if fails:
            print("G5DSUP_CONTROL: CAUGHT — the checker is live")
            return 0
        print("G5DSUP_CONTROL: NOT CAUGHT — the checker is inert, which is a defect")
        return 1
    if fails:
        print("G5DSUP: FAIL (%d)" % len(fails))
        return 1
    print("G5DSUP: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
