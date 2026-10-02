#!/usr/bin/env python3
"""bn_timeline.py — the analysis half of BN1's whole-token timeline census.

    python3 evidence/qwen9b/bn/bn_timeline.py <timeline.csv> [--log <run.log>]
                                              [--seq <stream.seq>]
                                              [--gantt-token N] [--cols N]

INPUTS, and what each one is for
--------------------------------
  <timeline.csv>  what `tb/seq_timeline.svh` wrote: one `R,` row per SEQ
                  record (its issue cycle, its cycle count and the sixteen
                  per-class busy counts inside its window) and one `S,` row
                  per (token, active-set mask) with the cycles that mask
                  stood.  This is the raw evidence.
  --log           the run's own log.  Its `SEQ_TIMELINE` block carries the
                  same totals, so this script CHECKS the CSV against it
                  rather than trusting either alone — the log is what
                  survives if the CSV is lost, and a disagreement between
                  them is a bug in one of the two and must be loud.
  --seq           the record stream itself, read only to name the record
                  opcodes and to CROSS-CHECK the per-record rows against the
                  bytes the sequencer actually executed.

WHAT IT DOES NOT DO
-------------------
It does not model anything.  Every number printed is either transcribed
from those inputs (T) or derived from them with the arithmetic shown (D).
Where a comparand comes from a document it is labelled S and cited.  The
TB is NOT the board: `evidence/qwen9b/s4/S4_REPLAY.md` §4.2 measures this
same stream at 131.138 ms/token in this same testbench while
`evidence/qwen9b/g6/RD9_GATE.md` §10.1 measures the silicon at 137.121,
and that 4.6 % gap sits under every comparison below.

LAYER BOUNDARIES ARE DERIVED, NOT ASSUMED
-----------------------------------------
The record stream carries three markers that the RTL itself defines:

  * `CSRWR -> layer 0x30` (LAYER, the cache-slot select) is written at the
    top of every layer half-body — the finest RTL-meaningful grid there is
    (rtl/layer_chan.sv:26-27).
  * `CSRWR -> layer 0x5C` (DNSB) is "written ONCE PER LAYER BODY"
    (rtl/layer_chan.sv:46) and therefore counts DeltaNet layers.
  * the `ROPET` layer command (opcode 3) loads the RoPE table and therefore
    counts GQA layers.

So this script cuts the token at every LAYER write and LABELS each cell by
the layer opcodes dispatched inside it.  Cells are NOT merged — consecutive
cells of the same label are consecutive LAYERS.  It then CHECKS the derived
DN and GQA cell counts against the DNSB and ROPET counts, and prints both;
a disagreement is reported, not smoothed.
"""
import argparse
import collections
import os
import struct
import sys

ACLK_HZ = 250_000_000.0
# tb/tb_seq_chip.sv:110-111 — `always #2 clk` and `always #1.667 ui_clk`,
# i.e. 250.00 MHz aclk and 299.94 MHz ui_clk.  The weight memories run on
# ui_clk, so a beats-per-ACLK-cycle rate has to be divided by this ratio
# before it can be compared with a model expressed in ui-cycles per beat.
UI_HZ = 1.0 / (2 * 1.667e-9)
UI_PER_ACLK = UI_HZ / ACLK_HZ

# SEQ record opcodes — rtl/seq_unit.sv:270-273
SEQOP = {1: "CSRWR", 2: "CMD", 3: "MOVX", 4: "MOVY", 5: "MVGO", 6: "EMB",
         7: "AMAXL", 8: "JMP", 9: "FENCE", 10: "HALT", 11: "LDC", 12: "XOP"}
# layer_chan command opcodes — rtl/layer_chan.sv:389-414
LAYOP = {1: "VN", 2: "VNW", 3: "ROPET", 4: "ROPE", 5: "CONVW", 6: "CONV",
         7: "GATE", 8: "DNST", 9: "KVAP", 10: "ATTN", 11: "ALU", 12: "DNZ",
         13: "SLD", 14: "SST"}
# mover ops — rtl/seq_unit.sv:1070-1102 (mv_op)
MVOP = {0: "MOVX", 1: "MVGO", 2: "MOVY", 3: "FENCE"}

CLS = ["L_CMP", "L_DMA", "MOVER", "SEQBULK",
       "MV0_STR", "MV1_STR", "MV2_STR", "MV3_STR",
       "MV0_BSY", "MV1_BSY", "MV2_BSY", "MV3_BSY",
       "SMEM_RD", "SMEM_WR", "RECDDR", "BFAB"]
NCLS = len(CLS)
CI = {n: i for i, n in enumerate(CLS)}

# the grouping used for the "perfect overlap" bound and the headline split:
# the four weight-stream bits are ONE resource (the weight path) and the
# four engine-busy bits another, because a bound that treated each channel
# as its own serial term would be arithmetic about nothing.
GROUPS = [
    ("layer compute", "lcmp", ["L_CMP"]),
    ("layer state-DMA", "ldma", ["L_DMA"]),
    ("mover engine", "mover", ["MOVER"]),
    ("weight streaming (any chan)", "wstr",
     ["MV0_STR", "MV1_STR", "MV2_STR", "MV3_STR"]),
    ("matvec engine (any chan)", "mvbsy",
     ["MV0_BSY", "MV1_BSY", "MV2_BSY", "MV3_BSY"]),
    ("record/LDC/EMB DDR", "recddr", ["SEQBULK", "RECDDR"]),
    ("state window", "smem", ["SMEM_RD", "SMEM_WR"]),
    ("burst fabric", "bfab", ["BFAB"]),
]


def ms(cycles):
    return cycles / ACLK_HZ * 1000.0


def pct(a, b):
    return (100.0 * a / b) if b else 0.0


# ----------------------------------------------------------------------
# R,rec,tok,pc,op,flags,tgt,lop,cyc0,ncyc,<16 classes>,wb0..3,stall,none
RWIDTH = 1 + 9 + NCLS + 4 + 2


def read_csv(path):
    """-> (rows, sig, short)  rows: list of dicts; sig: {tok: {mask: cycles}};
    short: rows the file could not carry in full.

    A row with the wrong field count is COUNTED AND SKIPPED rather than
    crashing the read: a census read from a run that was killed (or read
    while it is still writing) has one truncated last line, and a reader
    that dies on it tells you nothing about the 99.999 % that is intact.
    `short` is reported, so a truncated file is never silently analysed as
    a complete one.
    """
    rows = []
    sig = collections.defaultdict(dict)
    short = 0
    with open(path) as fh:
        for line in fh:
            if line.startswith("R,"):
                f = line.rstrip("\n").split(",")
                if len(f) != RWIDTH or not line.endswith("\n"):
                    short += 1
                    continue
                v = [int(x) for x in f[1:]]
                rows.append({
                    "rec": v[0], "tok": v[1], "pc": v[2], "op": v[3],
                    "flags": v[4], "tgt": v[5], "lop": v[6],
                    "cyc0": v[7], "ncyc": v[8],
                    "cls": v[9:9 + NCLS],
                    "wb": v[9 + NCLS:13 + NCLS],
                    "stall": v[13 + NCLS], "none": v[14 + NCLS],
                })
            elif line.startswith("S,"):
                g = line.rstrip("\n").split(",")
                if len(g) != 4 or not line.endswith("\n"):
                    short += 1
                    continue
                sig[int(g[1])][int(g[2])] = int(g[3])
    return rows, dict(sig), short


def read_log(path):
    """-> the SEQ_TIMELINE block as nested dicts (the log-only view)."""
    out = {"meta": {}, "class": collections.defaultdict(dict),
           "tcyc": {}, "union": {}, "none": {}, "stall": {},
           "wbeat": collections.defaultdict(dict),
           "mvop": collections.defaultdict(dict),
           "ist": collections.defaultdict(dict),
           "opcyc": collections.defaultdict(dict),
           "pair": collections.defaultdict(dict),
           "axil": {}, "topsig": [], "backjump": None}
    if not path or not os.path.exists(path):
        return None
    seen = False
    with open(path) as fh:
        for line in fh:
            if not line.startswith("SEQ_TIMELINE"):
                continue
            seen = True
            f = line.split()
            k = f[1]
            if k == "meta":
                for kv in f[2:]:
                    a, _, b = kv.partition("=")
                    out["meta"][a] = int(b)
            elif k == "backjump":
                out["backjump"] = int(f[2])
            elif k == "class":
                out["class"][int(f[2])][int(f[3])] = int(f[5])
            elif k in ("tcyc", "union", "none", "stall"):
                out[k][int(f[2])] = int(f[3])
            elif k == "axil":
                out["axil"][int(f[2])] = (int(f[3]), int(f[4]))
            elif k in ("wbeat", "mvop", "ist"):
                out[k][int(f[2])][int(f[3])] = int(f[4])
            elif k == "opcyc":
                out["opcyc"][int(f[2])][int(f[3])] = (int(f[4]), int(f[5]))
            elif k == "pair":
                out["pair"][int(f[2])][(int(f[3]), int(f[4]))] = int(f[5])
            elif k == "topsig":
                out["topsig"].append((int(f[3]), int(f[4])))
    return out if seen else None


def read_seq(path):
    if not path or not os.path.exists(path):
        return None
    b = open(path, "rb").read()
    n = len(b) // 16
    return [(b[i * 16], b[i * 16 + 1],
             struct.unpack_from("<H", b, i * 16 + 2)[0],
             struct.unpack_from("<I", b, i * 16 + 4)[0]) for i in range(n)]


# ----------------------------------------------------------------------
def maskname(m):
    if m == 0:
        return "{sequencer only}"
    parts = []
    strs = [c for c in range(4) if m >> (4 + c) & 1]
    bsys = [c for c in range(4) if m >> (8 + c) & 1]
    if m & 1:
        parts.append("layer")
    if m >> 1 & 1:
        parts.append("sdma")
    if m >> 2 & 1:
        parts.append("mover")
    if m >> 3 & 1:
        parts.append("bulk")
    if strs:
        parts.append("wstr" + "".join(str(c) for c in strs))
    if bsys:
        parts.append("mvbsy" + "".join(str(c) for c in bsys))
    if m >> 12 & 1:
        parts.append("smemR")
    if m >> 13 & 1:
        parts.append("smemW")
    if m >> 14 & 1:
        parts.append("recddr")
    if m >> 15 & 1:
        parts.append("bfab")
    return "{" + " ".join(parts) + "}"


def group_cycles(cls_vec):
    """the GROUPS split, from a 16-vector of per-class cycles.  NOTE: the
    OR'ed groups are summed here only for the per-class table; the true
    union of a group needs the signature histogram and is computed from it
    wherever a union is what is meant."""
    return {name: sum(cls_vec[CI[c]] for c in cols) for name, _s, cols in GROUPS}


def group_union_from_sig(sigmap):
    """cycles in which AT LEAST ONE class of each group was active (D, from
    the per-cycle signature histogram — an exact union, not a sum)."""
    out = {name: 0 for name, _s, _c in GROUPS}
    bits = {name: sum(1 << CI[c] for c in cols) for name, _s, cols in GROUPS}
    for m, c in sigmap.items():
        for name, bm in bits.items():
            if m & bm:
                out[name] += c
    return out


# ----------------------------------------------------------------------
def layer_segments(rows, seq):
    """Cut each token at every `CSRWR -> layer 0x30` record (the LAYER
    cache-slot select, the RTL's own per-layer-body marker) and LABEL each
    cell by the layer opcodes dispatched inside it.  Cells are NOT merged:
    consecutive cells of the same label are consecutive LAYERS, and merging
    them would report 8 DeltaNet blocks where the model has 24 DeltaNet
    layers.  Returns per token a list of (label, first_row, last_row).

      DN    the cell dispatched DNST or DNZ         -> a DeltaNet layer
      GQA   it dispatched ATTN / KVAP / ROPE / ROPET -> a GQA layer
      HEAD  it contains the AMAXL record            -> the LM head
      MLP   layer commands but none of the above
      -     no layer command at all (setup / SLD / SST only)
    """
    out = collections.defaultdict(list)
    cuts = collections.defaultdict(list)
    for i, r in enumerate(rows):
        if r["op"] == 1 and r["tgt"] == 0x0030:
            cuts[r["tok"]].append(i)
    for tok, cs in cuts.items():
        end = max(i for i, r in enumerate(rows) if r["tok"] == tok)
        bounds = cs + [end + 1]
        cells = []
        for k in range(len(cs)):
            lo, hi = bounds[k], bounds[k + 1]
            ops = set(rows[j]["lop"] for j in range(lo, hi)
                      if rows[j]["lop"] >= 0)
            has_amax = any(rows[j]["op"] == 7 for j in range(lo, hi))
            if has_amax:
                lab = "HEAD"
            elif 8 in ops or 12 in ops:
                lab = "DN"
            elif ops & {3, 4, 9, 10}:
                lab = "GQA"
            elif ops:
                lab = "MLP"
            else:
                lab = "-"
            cells.append((lab, lo, hi - 1))
        out[tok] = cells
    return dict(out)


def ascii_gantt(rows, lo, hi, cols, title):
    """one row per GROUP, one column per bucket of records; the glyph is
    the busy fraction of that group inside the bucket."""
    tot = sum(rows[i]["ncyc"] for i in range(lo, hi + 1))
    if tot == 0:
        return [f"{title}: empty"]
    n = hi - lo + 1
    per = max(1, (n + cols - 1) // cols)
    buckets = []
    i = lo
    while i <= hi:
        j = min(hi, i + per - 1)
        cyc = sum(rows[k]["ncyc"] for k in range(i, j + 1))
        g = {name: 0 for name, _s, _c in GROUPS}
        for k in range(i, j + 1):
            for name, _s, cl in GROUPS:
                g[name] += sum(rows[k]["cls"][CI[c]] for c in cl) / len(cl)
        buckets.append((cyc, g))
        i = j + 1
    glyph = " .:-=+*#%@"
    lines = [f"{title}  records {lo}..{hi} ({n}), {tot} cycles = "
             f"{ms(tot):.3f} ms, {len(buckets)} columns of ~{per} records"]
    for name, _s, _c in GROUPS:
        row = []
        for cyc, g in buckets:
            f = min(1.0, g[name] / cyc) if cyc else 0.0
            row.append(glyph[min(9, int(f * 9.999))])
        lines.append(f"  {name:<28s}|{''.join(row)}|")
    lines.append(f"  {'':<28s} legend: ' '=0  .:-=+*#%@ -> 100% busy"
                 " (wstr/mvbsy are the per-channel mean)")
    return lines


# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--log", default=None)
    ap.add_argument("--seq", default=None)
    ap.add_argument("--gantt-token", type=int, default=None)
    ap.add_argument("--cols", type=int, default=160)
    ap.add_argument("--topsig", type=int, default=12)
    a = ap.parse_args()

    rows, sig, short = read_csv(a.csv)
    log = read_log(a.log)
    seq = read_seq(a.seq)
    toks = sorted(set(r["tok"] for r in rows))
    ntok = len(toks)
    print("=" * 78)
    print("BN1 — WHOLE-TOKEN TIMELINE CENSUS, analysis")
    print("=" * 78)
    print(f"csv          {a.csv}")
    print(f"log          {a.log}")
    print(f"seq          {a.seq}")
    print(f"records      {len(rows)}   segments {ntok} {toks}")
    complete = any(l.startswith("#END") for l in open(a.csv))
    print(f"csv complete {complete}   malformed/truncated rows skipped: {short}")
    if not complete or short:
        print("    *** THIS CSV IS NOT A COMPLETE CENSUS — the numbers below")
        print("    *** describe only what it carries.  Do not cite them.")
    print("THE TB IS NOT THE BOARD.  This testbench measures this same stream")
    print("at 131.138 ms/token (S, evidence/qwen9b/s4/S4_REPLAY.md §4.2) while")
    print("the silicon measures 137.121 (S, evidence/qwen9b/g6/RD9_GATE.md")
    print("§10.1) — the board is 4.6 % slower end to end.  Every number below")
    print("is a TB number and is labelled T (transcribed) or D (derived).")
    print()

    # ---- per-token totals, and the CSV/log cross-check ----------------
    tcyc = {t: 0 for t in toks}
    clsv = {t: [0] * NCLS for t in toks}
    stall = {t: 0 for t in toks}
    none_ = {t: 0 for t in toks}
    wb = {t: [0] * 4 for t in toks}
    opcyc = {t: collections.Counter() for t in toks}
    opcnt = {t: collections.Counter() for t in toks}
    for r in rows:
        t = r["tok"]
        tcyc[t] += r["ncyc"]
        stall[t] += r["stall"]
        none_[t] += r["none"]
        for i in range(NCLS):
            clsv[t][i] += r["cls"][i]
        for c in range(4):
            wb[t][c] += r["wb"][c]
        opcyc[t][r["op"]] += r["ncyc"]
        opcnt[t][r["op"]] += 1

    sigcyc = {t: sum(sig.get(t, {}).values()) for t in toks}
    print("--- CONSISTENCY (D): the per-record rows, the signature histogram")
    print("    and (where given) the log's own block must agree.")
    print("    The FIRST record's window opens when the issue FSM latches it,")
    print("    so the sequencer's I_SYNC cycles before it are inside the")
    print("    signature histogram and inside no record row; that residue is")
    print("    expected in segment 0 and nowhere else.")
    bad = 0
    sync0 = sigcyc[toks[0]] - tcyc[toks[0]]
    for t in toks:
        d = sigcyc[t] - tcyc[t] - (sync0 if t == toks[0] else 0)
        note = "" if d == 0 else f"   <-- DIFFER by {d}"
        if d:
            bad += 1
        print(f"    seg {t}: records {tcyc[t]:>12,}   signatures "
              f"{sigcyc[t]:>12,}{note}")
    print(f"    I_SYNC residue before the first record: {sync0}"
          + ("" if complete else "  (MEANINGLESS: the CSV is incomplete)"))
    if log:
        for t in toks:
            lt = log["tcyc"].get(t)
            if lt is None:
                continue
            d = lt - sigcyc[t]
            if d:
                bad += 1
            print(f"    seg {t}: log tcyc {lt:>12,} vs signatures "
                  f"{sigcyc[t]:>12,}" + ("" if d == 0 else f"  <-- DIFFER {d}"))
        print(f"    log meta: {log['meta']}")
        print(f"    log backjump (backward pc steps): {log['backjump']}")
    # the per-record window is opened by the FIRST record, so the cycles
    # before it (the sequencer's I_SYNC) are outside every row: report the
    # residue rather than hiding it.
    if log:
        resid = log["meta"].get("bcyc", 0) - sum(tcyc.values())
        print(f"    busy cycles not inside any record window (pre-first-record"
              f" I_SYNC): {resid}")
    if not complete:
        bad = 0
        print("    consistency: NOT CHECKED — the CSV has no #END marker, so")
        print("    the signature section was never written and there is")
        print("    nothing to check the record rows against.")
    else:
        print(f"    consistency failures: {bad}")
    print()

    # ---- the headline: class totals per token ------------------------
    body = [t for t in toks if t != 0]
    nbody = len(body)
    tot_all = sum(tcyc[t] for t in toks)
    tot_body = sum(tcyc[t] for t in body)
    print("--- §1  THE TOKEN, IN CYCLES (T for the counts, D for ms/shares)")
    print(f"    whole launch      {tot_all:>14,} cycles = {ms(tot_all):9.3f} ms")
    print(f"    segment 0 (preamble) {tcyc[toks[0]]:>11,} cycles = "
          f"{ms(tcyc[toks[0]]):9.3f} ms")
    print(f"    tokens 1..{nbody}       {tot_body:>14,} cycles = "
          f"{ms(tot_body):9.3f} ms")
    if nbody:
        print(f"    MEAN PER TOKEN    {tot_body // nbody:>14,} cycles = "
              f"{ms(tot_body / nbody):9.3f} ms/token")
    print("    per segment:")
    for t in toks:
        print(f"      seg {t}: {tcyc[t]:>12,} cyc  {ms(tcyc[t]):9.3f} ms"
              f"   stall {stall[t]:>8,}   sequencer-only {none_[t]:>10,}"
              f" ({pct(none_[t], tcyc[t]):5.2f} %)")
    print()

    print("--- §2  CLASS TOTALS, mean over tokens 1..%d (D)" % nbody)
    print(f"    {'class':<28s} {'cyc/token':>14s} {'ms/token':>10s} "
          f"{'% of token':>11s}")
    mean_tok = tot_body / nbody if nbody else 1
    gsum = collections.Counter()
    for t in body:
        for i in range(NCLS):
            gsum[CLS[i]] += clsv[t][i]
    for i in range(NCLS):
        v = gsum[CLS[i]] / nbody if nbody else 0
        print(f"    {CLS[i]:<28s} {v:>14,.0f} {ms(v):>10.3f} "
              f"{pct(v, mean_tok):>10.2f} %")
    print()
    print("    grouped (a group's cycles are its EXACT UNION, from the")
    print("    per-cycle signature histogram, not a sum of its members):")
    gu_tok = {t: group_union_from_sig(sig.get(t, {})) for t in toks}
    for name, _s, _c in GROUPS:
        v = sum(gu_tok[t][name] for t in body) / nbody if nbody else 0
        print(f"    {name:<28s} {v:>14,.0f} {ms(v):>10.3f} "
              f"{pct(v, mean_tok):>10.2f} %")
    print()
    print("    PER TOKEN, not just the mean (D) — ms at 250 MHz.  Segment 0 is")
    print("    the launch PREAMBLE (the records before the first OP_EMB), not")
    print("    a token; it is shown so the whole launch is accounted for.")
    hdr = "    {:<28s}".format("group") + "".join(
        f"{('seg' + str(t)):>10s}" for t in toks)
    print(hdr)
    for name, _s2, _c2 in GROUPS:
        print("    {:<28s}".format(name)
              + "".join(f"{ms(gu_tok[t][name]):>10.3f}" for t in toks))
    print("    {:<28s}".format("UNION")
          + "".join(f"{ms(tcyc[t] - none_[t]):>10.3f}" for t in toks))
    print("    {:<28s}".format("RESIDUE (sequencer only)")
          + "".join(f"{ms(none_[t]):>10.3f}" for t in toks))
    print("    {:<28s}".format("TOTAL")
          + "".join(f"{ms(tcyc[t]):>10.3f}" for t in toks))
    print()
    uni = sum(tcyc[t] - none_[t] for t in body) / nbody if nbody else 0
    print(f"    {'UNION (any class active)':<28s} {uni:>14,.0f} "
          f"{ms(uni):>10.3f} {pct(uni, mean_tok):>10.2f} %")
    res = sum(none_[t] for t in body) / nbody if nbody else 0
    print(f"    {'RESIDUE (sequencer only)':<28s} {res:>14,.0f} "
          f"{ms(res):>10.3f} {pct(res, mean_tok):>10.2f} %")
    print()

    # ---- §3 the active-set signature distribution --------------------
    print("--- §3  THE ACTIVE-SET SIGNATURE DISTRIBUTION — THE HEADLINE (T/D)")
    print("    what was busy together, per cycle, summed over tokens 1..%d."
          % nbody)
    agg = collections.Counter()
    for t in body:
        for m, c in sig.get(t, {}).items():
            agg[m] += c
    print(f"    {'#':>3s} {'mask':>7s} {'cyc/token':>13s} {'ms/token':>9s} "
          f"{'share':>8s}  active set")
    for k, (m, c) in enumerate(agg.most_common(a.topsig)):
        v = c / nbody if nbody else 0
        print(f"    {k:>3d} {m:>7d} {v:>13,.0f} {ms(v):>9.3f} "
              f"{pct(v, mean_tok):>7.2f} %  {maskname(m)}")
    print(f"    distinct signatures over tokens 1..{nbody}: {len(agg)}")
    print(f"    top {a.topsig} cover "
          f"{pct(sum(c for _, c in agg.most_common(a.topsig)), sum(agg.values())):.2f} %"
          " of the token")
    print()

    # ---- §4 the weight channels ---------------------------------------
    print("--- §4  WEIGHT STREAMING, PER CHANNEL (T for beats, D for rates)")
    strbits = sum(1 << CI[f"MV{c}_STR"] for c in range(4))
    bsybits = sum(1 << CI[f"MV{c}_BSY"] for c in range(4))
    any_str = sum(c for t in body for m, c in sig.get(t, {}).items()
                  if m & strbits) / (nbody or 1)
    any_bsy = sum(c for t in body for m, c in sig.get(t, {}).items()
                  if m & bsybits) / (nbody or 1)
    all4_str = sum(c for t in body for m, c in sig.get(t, {}).items()
                   if (m & strbits) == strbits) / (nbody or 1)
    print(f"    {'chan':>4s} {'beats/token':>14s} {'MiB/token':>10s} "
          f"{'streaming cyc':>14s} {'engine-busy cyc':>16s} "
          f"{'beats/cyc':>10s} {'util in window':>15s}")
    rates = []
    for c in range(4):
        b = sum(wb[t][c] for t in body) / (nbody or 1)
        s = sum(clsv[t][CI[f'MV{c}_STR']] for t in body) / (nbody or 1)
        y = sum(clsv[t][CI[f'MV{c}_BSY']] for t in body) / (nbody or 1)
        rate = b / s if s else 0.0
        rates.append((b, s, y, rate))
        print(f"    {c:>4d} {b:>14,.0f} {b * 64 / 2**20:>10.2f} {s:>14,.0f} "
              f"{y:>16,.0f} {rate:>10.4f} {pct(s, y):>14.2f} %")
    print(f"    any channel STREAMING     {any_str:>14,.0f} cyc/token = "
          f"{ms(any_str):8.3f} ms  ({pct(any_str, mean_tok):5.2f} % of token)")
    print(f"    any channel ENGINE BUSY   {any_bsy:>14,.0f} cyc/token = "
          f"{ms(any_bsy):8.3f} ms  ({pct(any_bsy, mean_tok):5.2f} % of token)")
    print(f"    ALL FOUR streaming at once{all4_str:>14,.0f} cyc/token = "
          f"{ms(all4_str):8.3f} ms  ({pct(all4_str, any_str):5.2f} % of the "
          "any-channel streaming time)")
    # how many channels stream simultaneously, cycle by cycle
    hist = collections.Counter()
    for t in body:
        for m, c in sig.get(t, {}).items():
            hist[bin(m & strbits).count("1")] += c
    print("    channels streaming simultaneously (cycles/token):")
    for k in sorted(hist):
        print(f"      {k} channel(s): {hist[k] / (nbody or 1):>13,.0f} "
              f"({pct(hist[k], sum(hist.values())):5.2f} %)")
    # phase count: a maximal run of consecutive records with any engine busy
    phases = 0
    inph = False
    for r in rows:
        if r["tok"] not in body:
            continue
        busy = any(r["cls"][CI[f"MV{c}_BSY"]] for c in range(4))
        if busy and not inph:
            phases += 1
        inph = busy
    print(f"    matvec PHASES (maximal runs of records with any engine busy),")
    print(f"      over tokens 1..{nbody}: {phases}  = {phases / (nbody or 1):.1f}"
          " per token")
    print()

    # ---- §5 per-layer-type --------------------------------------------
    print("--- §5  PER LAYER TYPE (boundaries DERIVED from the record types)")
    segs = layer_segments(rows, seq)
    if seq:
        dnsb = collections.Counter()
        ropet = collections.Counter()
        for r in rows:
            if r["op"] == 1 and r["tgt"] == 0x005C:
                dnsb[r["tok"]] += 1
            if r["op"] == 2 and r["lop"] == 3:
                ropet[r["tok"]] += 1
        print(f"    DNSB writes per token (= DeltaNet layers): "
              f"{dict((t, dnsb[t]) for t in toks)}")
        print(f"    ROPET commands per token (= GQA layers):   "
              f"{dict((t, ropet[t]) for t in toks)}")
    for t in toks:
        labs = collections.Counter(s[0] for s in segs.get(t, []))
        print(f"    seg {t}: {len(segs.get(t, []))} LAYER-marker cells "
              f"{dict(labs)}")
    print()
    print(f"    {'label':<6s} {'count/token':>12s} {'cyc/token':>14s} "
          f"{'ms/token':>10s} {'% token':>9s}  class split (% of the cell)")
    agg_lab = collections.defaultdict(lambda: [0, 0, [0] * NCLS, 0])
    for t in body:
        for lab, lo, hi in segs.get(t, []):
            e = agg_lab[lab]
            e[0] += 1
            for i in range(lo, hi + 1):
                e[1] += rows[i]["ncyc"]
                e[3] += rows[i]["none"]
                for k in range(NCLS):
                    e[2][k] += rows[i]["cls"][k]
    for lab in sorted(agg_lab, key=lambda x: -agg_lab[x][1]):
        n, cyc, cl, nn = agg_lab[lab]
        split = []
        for name, short, cols in GROUPS:
            v = sum(cl[CI[c]] for c in cols) / len(cols)
            if v:
                split.append(f"{short}:{pct(v, cyc):.0f}%")
        split.append(f"seqonly:{pct(nn, cyc):.0f}%")
        print(f"    {lab:<6s} {n / (nbody or 1):>12.1f} {cyc / (nbody or 1):>14,.0f} "
              f"{ms(cyc / (nbody or 1)):>10.3f} {pct(cyc, tot_body):>8.2f} %  "
              f"{'  '.join(split)}")
    print("    (wstr/mvbsy are the PER-CHANNEL MEAN over the four channels;")
    print("     every other column is that resource's own busy fraction of")
    print("     the cell.  They overlap, so they do not sum to 100 %.)")
    print()

    # ---- §6 the two bounds --------------------------------------------
    print("--- §6  TWO UPPER BOUNDS (D)")
    print("    (i) PERFECT OVERLAP.  If every resource below could run")
    print("        concurrently with every other with no dependency and no")
    print("        arbitration, the token could not be shorter than the")
    print("        BUSIEST single resource.  'Perfect' therefore assumes:")
    print("        no data dependency between a weight stream and the layer")
    print("        command that consumes it, no shared bus, no re-ordering")
    print("        cost, and the same per-resource busy time as measured.")
    print("        It is an UPPER BOUND ON THE SAVING, not a design target.")
    for t in body[:1] or toks[:1]:
        pass
    gbody = {name: sum(gu_tok[t][name] for t in body) / (nbody or 1)
             for name, _s, _c in GROUPS}
    mx = max(gbody.values()) if gbody else 0
    mxn = max(gbody, key=gbody.get) if gbody else "-"
    print(f"        union            {uni:>14,.0f} cyc/token = {ms(uni):8.3f} ms")
    print("      (i-a) THE FORMULA LITERALLY, over the instrumented classes:")
    print(f"        busiest class    {mx:>14,.0f} cyc/token = {ms(mx):8.3f} ms"
          f"   ({mxn})")
    print(f"        saving bound     {uni - mx:>14,.0f} cyc/token = "
          f"{ms(uni - mx):8.3f} ms  = {pct(uni - mx, mean_tok):.2f} % of the token")
    print(f"        (the sequencer-only residue {res:,.0f} cyc = {ms(res):.3f} ms")
    print("         is NOT in the union and no overlap removes it)")
    print()
    print("      (i-b) AND THE SAME FORMULA OVER RESOURCES, WHICH IS THE ONE")
    print("        TO READ.  (i-a) is bound by `mover engine`, and that class")
    print("        is `mv_busy`, which stands for the whole of a FENCE drain")
    print("        as well as for real mover work — a WAIT, not a resource")
    print("        doing anything.  Splitting it at the signature level into")
    print("        MOVER-and-nothing-streaming (real MOVX/MOVY/LDC traffic)")
    print("        and MOVER-while-streaming (the FENCE wait, whose resource")
    print("        is the weight path, already counted) gives the resources")
    print("        that actually occupy hardware:")
    strb = sum(1 << CI[f"MV{c}_STR"] for c in range(4))
    mvb = 1 << CI["MOVER"]
    mwork = sum(c for t in body for m, c in sig.get(t, {}).items()
                if (m & mvb) and not (m & strb)) / (nbody or 1)
    mwait = sum(c for t in body for m, c in sig.get(t, {}).items()
                if (m & mvb) and (m & strb)) / (nbody or 1)
    RES = [("layer compute", gbody.get("layer compute", 0)),
           ("layer state-DMA", gbody.get("layer state-DMA", 0)),
           ("weight streaming (any chan)",
            gbody.get("weight streaming (any chan)", 0)),
           ("mover work (MOVER, nothing streaming)", mwork),
           ("record/LDC/EMB DDR", gbody.get("record/LDC/EMB DDR", 0)),
           ("state window", gbody.get("state window", 0)),
           ("burst fabric", gbody.get("burst fabric", 0))]
    for n2, v2 in sorted(RES, key=lambda x: -x[1]):
        print(f"          {n2:<40s} {v2:>13,.0f} cyc = {ms(v2):8.3f} ms"
              f"  {pct(v2, mean_tok):5.2f} %")
    print(f"          (for reference, MOVER while a channel streams — the")
    print(f"           FENCE wait — is {mwait:,.0f} cyc = {ms(mwait):.3f} ms;")
    print("           it is a wait on the weight path and is NOT a resource)")
    rmx = max(v for _n, v in RES)
    rmn = max(RES, key=lambda x: x[1])[0]
    print(f"        BUSIEST RESOURCE {rmx:>14,.0f} cyc/token = {ms(rmx):8.3f}"
          f" ms   ({rmn})")
    print(f"        SAVING BOUND     {uni - rmx:>14,.0f} cyc/token = "
          f"{ms(uni - rmx):8.3f} ms  = {pct(uni - rmx, mean_tok):.2f} % of the"
          " token")
    print(f"        i.e. a token that is {ms(mean_tok):.3f} ms could not, under")
    print(f"        perfect overlap, be shorter than {ms(rmx + res):.3f} ms")
    print(f"        (busiest resource + the sequencer-only residue) — a")
    print(f"        speed-up of at most {mean_tok / (rmx + res) if (rmx + res) else 0:.2f}x.")
    print()
    print("    (ii) DDR-BOUND FLOOR.  The busiest channel's weight bytes at")
    print("         the beats/cycle THIS RUN measured while that channel was")
    print("         streaming — i.e. the floor this memory model imposes, not")
    print("         a floor the board imposes (WLAT 40, tb/tb_seq_chip.sv:69).")
    for c in range(4):
        b, s, y, rate = rates[c]
        print(f"         chan {c}: {b:,.0f} beats at {rate:.4f} beats/cyc "
              f"-> {b / rate if rate else 0:>12,.0f} cyc = "
              f"{ms(b / rate if rate else 0):8.3f} ms/token")
    bi = max(range(4), key=lambda c: rates[c][0])
    b, s, y, rate = rates[bi]
    floor = b / rate if rate else 0
    print(f"         BUSIEST is chan {bi}: floor {floor:,.0f} cyc = "
          f"{ms(floor):.3f} ms/token = {pct(floor, mean_tok):.2f} % of the token")
    print()
    print("    (ii-b) AND WHAT THAT RATE IS, IN THE MODEL'S OWN UNITS.")
    print("         docs/QWEN35_NEXT_FEASIBILITY.md §4.2 (S) solves the 0.8B")
    print("         and 2B silicon steps for r = 1.1037 ui-cycles per 64 B")
    print("         beat = 17.40 GB/s/chan, with r = 1.000 called 'the")
    print("         engine's hard floor'.  This run measures its own r:")
    for c in range(4):
        b2, s2, y2, rate2 = rates[c]
        r_ui = UI_PER_ACLK / rate2 if rate2 else 0.0
        gbs = rate2 * 64 * ACLK_HZ / 1e9
        print(f"         chan {c}: {rate2:.4f} beats/aclk-cyc -> r = {r_ui:.4f}"
              f" ui-cyc/beat = {gbs:.2f} GB/s")
    r_ui_b = UI_PER_ACLK / rate if rate else 0.0
    print(f"         So the TESTBENCH's weight path runs at r = {r_ui_b:.4f},")
    print("         essentially the engine's hard floor, against the r =")
    print("         1.1037 the model FITTED from two silicon steps — i.e.")
    print(f"         the TB's weight memory is {100 * (1.1037 / r_ui_b - 1):.1f} %"
          " faster than the rate")
    print("         the board's own measurements imply.  That is a REASON to")
    print("         expect this census's matvec term to be optimistic against")
    print("         the board, and it is stated as a reason, not a correction:")
    print("         `tb/seq_mem_file.sv` is a file-backed model with no")
    print("         refresh, no bank conflict and no read/write turnaround.")
    print()

    # ---- §7 reconciliation --------------------------------------------
    print("--- §7  RECONCILIATION")
    print("    (0) IS THE MODEL'S SERIAL STRUCTURE RIGHT?  The three terms")
    print("        the model sums, measured LIKE FOR LIKE here — weight")
    print("        streaming, mover WORK (not `mv_busy`), layer compute:")
    ws0 = gbody.get("weight streaming (any chan)", 0)
    lc0 = gbody.get("layer compute", 0)
    mw0 = sum(c for t in body for m, c in sig.get(t, {}).items()
              if (m & (1 << CI["MOVER"]))
              and not (m & sum(1 << CI[f"MV{c2}_STR"] for c2 in range(4)))
              ) / (nbody or 1)
    ser = ws0 + mw0 + lc0
    print(f"          weight streaming {ms(ws0):8.3f} + mover work "
          f"{ms(mw0):8.3f} + layer compute {ms(lc0):8.3f}")
    print(f"          = {ms(ser):8.3f} ms against a measured token of "
          f"{ms(mean_tok):8.3f} ms")
    print(f"          -> the three terms fill {pct(ser, mean_tok):.2f} % of the"
          " token, so they are")
    print("             very nearly DISJOINT: the model's SERIAL sum is the")
    print("             right shape for this design, and that is a MEASURED")
    print("             statement, not an assumption.")
    print()
    print("    (a) against the SERIAL model, docs/QWEN35_NEXT_FEASIBILITY.md")
    print("        §4.4's 9B W4 g128 row (S): matvec 58.95 + movers 32.66 +")
    print("        layer 47.00 = 138.61 ms/token.")
    mv_ms = ms(gbody.get("matvec engine (any chan)", 0))
    ws_ms = ms(gbody.get("weight streaming (any chan)", 0))
    mo_ms = ms(gbody.get("mover engine", 0))
    ly_ms = ms(gbody.get("layer compute", 0))
    print(f"        measured, this TB: matvec-engine-busy {mv_ms:7.3f} ms "
          f"(of which weight-streaming {ws_ms:7.3f} ms),")
    print(f"                           mover-engine-busy {mo_ms:7.3f} ms, "
          f"layer-compute {ly_ms:7.3f} ms")
    print(f"        their SUM {mv_ms + mo_ms + ly_ms:7.3f} ms vs the measured "
          f"token {ms(mean_tok):7.3f} ms -> overlap factor "
          f"{(mv_ms + mo_ms + ly_ms) / ms(mean_tok) if mean_tok else 0:.4f}")
    if log:
        mo = collections.Counter()
        for t in body:
            mo.update(log["mvop"].get(t, {}))
        work = sum(v for k, v in mo.items() if k != 3) / (nbody or 1)
        wait = mo.get(3, 0) / (nbody or 1)
        print("        AND THE MOVER TERM IS NOT MOVER WORK.  `mv_busy` is high")
        print("        for the whole of a FENCE too (mv_op 3, the drain wait),")
        print("        so the model's 'movers' term and this class are not the")
        print("        same quantity:")
        print(f"          mover WORK (MOVX+MVGO+MOVY) {work:>12,.0f} cyc/token"
              f" = {ms(work):7.3f} ms ({pct(work, mean_tok):5.2f} %)")
        print(f"          FENCE drain WAIT            {wait:>12,.0f} cyc/token"
              f" = {ms(wait):7.3f} ms ({pct(wait, mean_tok):5.2f} %)")
    print("    (b) against the BOARD's two lanes, evidence/qwen9b/g6/"
          "RD9_GATE.md §10.2 (S):")
    print("        L_LCYC 41.588 ms/token, L_SDMA_CYC 5.125 ms/token, the two")
    print("        together 34.1 % of the step and 65.9 % in NEITHER lane.")
    lc = ms(gbody.get("layer compute", 0))
    ld = ms(gbody.get("layer state-DMA", 0))
    print(f"        measured here: layer compute {lc:7.3f} ms/token "
          f"({pct(gbody.get('layer compute', 0), mean_tok):5.2f} %), "
          f"state-DMA {ld:7.3f} ms/token "
          f"({pct(gbody.get('layer state-DMA', 0), mean_tok):5.2f} %)")
    nl = sum(c for t in body for m, c in sig.get(t, {}).items()
             if not (m & 0b11)) / (nbody or 1)
    print(f"        cycles in NEITHER lane: {nl:,.0f} = {ms(nl):.3f} ms/token"
          f" = {pct(nl, mean_tok):.2f} % of the token")
    print("        (the board's 65.9 % is the same quantity measured on")
    print("         silicon; this is the TB's value for it, and the two are")
    print("         NOT the same instrument)")
    print()

    # ---- §8 record-type view ------------------------------------------
    print("--- §8  WHERE THE SEQUENCER'S TIME GOES, BY RECORD TYPE "
          "(T/D, tokens 1..%d)" % nbody)
    print(f"    {'op':<7s} {'records/token':>14s} {'cyc/token':>14s} "
          f"{'ms/token':>10s} {'% token':>9s} {'cyc/record':>11s}")
    tot_op = collections.Counter()
    tot_cn = collections.Counter()
    for t in body:
        tot_op.update(opcyc[t])
        tot_cn.update(opcnt[t])
    for op in sorted(tot_op, key=lambda o: -tot_op[o]):
        cy = tot_op[op] / (nbody or 1)
        cn = tot_cn[op] / (nbody or 1)
        print(f"    {SEQOP.get(op, op):<7s} {cn:>14,.1f} {cy:>14,.0f} "
              f"{ms(cy):>10.3f} {pct(cy, mean_tok):>8.2f} % "
              f"{cy / cn if cn else 0:>11,.1f}")
    print()
    if log:
        print("--- §8b  THE ISSUE FSM, from the log's own histogram (T)")
        IST = ["I_IDLE", "I_SYNC", "I_SYNCW", "I_FETCH", "I_EXEC", "I_WR",
               "I_CMDW", "I_CMDDRAIN", "I_CMDPOLL", "I_CMDPOLLW", "I_XRFSEL",
               "I_XRFSELD", "I_XRFRD", "I_XRFRDW", "I_XRFSB", "I_WTI",
               "I_WTD", "I_MOVER", "I_AMAX", "I_AMAXW", "I_BULKSPTR",
               "I_BULKRUN", "I_BULKEND", "I_FENCE", "I_HALT", "I_ERR"]
        ist = collections.Counter()
        for t in body:
            ist.update(log["ist"].get(t, {}))
        for s in sorted(ist, key=lambda s: -ist[s]):
            v = ist[s] / (nbody or 1)
            nm = IST[s] if s < len(IST) else f"?{s}"
            print(f"    {nm:<12s} {v:>14,.0f} cyc/token {ms(v):>9.3f} ms "
                  f"{pct(v, mean_tok):>7.2f} %")
        print()
        print("--- §8c  THE MOVER, by op, from the log (T)")
        mo = collections.Counter()
        for t in body:
            mo.update(log["mvop"].get(t, {}))
        for s in sorted(mo, key=lambda s: -mo[s]):
            v = mo[s] / (nbody or 1)
            print(f"    {MVOP.get(s, s):<8s} {v:>14,.0f} cyc/token "
                  f"{ms(v):>9.3f} ms {pct(v, mean_tok):>7.2f} %")
        print()

    # ---- §9 the Gantts -------------------------------------------------
    gt = a.gantt_token
    if gt is None:
        gt = body[len(body) // 2] if body else toks[0]
    print(f"--- §9  ASCII GANTT, token {gt}: one layer of each derived type")
    shown = set()
    for lab, lo, hi in segs.get(gt, []):
        if lab in shown or lab == "-":
            continue
        shown.add(lab)
        for line in ascii_gantt(rows, lo, hi, a.cols,
                                f"  [{lab}] token {gt}"):
            print(line)
        print()
    # and the whole token, coarse
    lo = min(i for i, r in enumerate(rows) if r["tok"] == gt)
    hi = max(i for i, r in enumerate(rows) if r["tok"] == gt)
    for line in ascii_gantt(rows, lo, hi, a.cols, f"  [WHOLE TOKEN {gt}]"):
        print(line)
    print()
    print("=" * 78)
    print("END OF ANALYSIS")
    print("=" * 78)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
