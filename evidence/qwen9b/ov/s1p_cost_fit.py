#!/usr/bin/env python3
"""s1p_cost_fit.py — Task S1P: the MEASURED basis of ref/seq_cost.py.

    FABLE5_MODEL=9b python evidence/qwen9b/ov/s1p_cost_fit.py census
    FABLE5_MODEL=9b python evidence/qwen9b/ov/s1p_cost_fit.py fit

READ-ONLY.  It opens the shipped stream tb/scripts/w9/model_9b_s1.e4.seq
(sha-checked against its manifest) and BN1's per-record timeline CSV
evidence/qwen9b/bn/bn_timeline_model_9b_s1.csv (sha-checked against the
COMMITTED evidence/qwen9b/bn/bn_timeline_model_9b_s1.csv.sha256 by
ov_census.load_csv), builds OV1's node list for every token 1..6 with that
token's own windows (ov_census.build_nodes / stream_durations, unchanged —
so every quantity below is exactly what the reorder pass's scheduler
consumes: node dur with the ARG CSRWRs merged into their CMD, MVGO stream
busy S, FENCE poll tail tau), and prints

  census   per-class distributions of those quantities against the record
           features a static model may use (lengths, beats, command keys);
  fit      the per-class formulas, their coefficients and residuals, and a
           comparison with the table committed in ref/seq_cost.py.
"""
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "ref"))

import numpy as np                       # noqa: E402
import ov_census as OC                   # noqa: E402

SF, GLS = OC.SF, OC.GLS
TOKS = (1, 2, 3, 4, 5, 6)


def token_segments(recs):
    """token t (1..6) -> (lo, hi) static pcs; tokens 4..6 run the body."""
    embs = [i for i, r in enumerate(recs) if r.opcode == SF.OP_EMB]
    halt = len(recs) - 1
    seg = []
    for k, lo in enumerate(embs):
        hi = (embs[k + 1] - 1) if k + 1 < len(embs) else halt - 1
        seg.append((lo, hi))
    assert len(seg) == 4, seg
    return {1: seg[0], 2: seg[1], 3: seg[2], 4: seg[3], 5: seg[3], 6: seg[3]}


def cmd_args(recs, lo, hi):
    """pc -> (lop, a0, a1, a2, nargs) for every CMD of lo..hi."""
    arg = {SF.CSR_L_ARG0: 0, SF.CSR_L_ARG1: 0, SF.CSR_L_ARG2: 0}
    out = {}
    nargs = 0
    for pc in range(lo, hi + 1):
        r = recs[pc]
        if r.opcode == SF.OP_CSRWR and r.target in arg:
            arg[r.target] = r.imm32
            nargs += 1
        elif r.opcode == SF.OP_CMD:
            out[pc] = (r.imm32 & 0xFF, arg[SF.CSR_L_ARG0], arg[SF.CSR_L_ARG1],
                       arg[SF.CSR_L_ARG2], nargs)
            nargs = 0
    return out


def collect():
    recs, _man = OC.load_stream()
    rows = OC.load_csv(toks=TOKS)
    segs = token_segments(recs)
    data = []          # (tok, kind, feature-tuple, value)
    for t in TOKS:
        lo, hi = segs[t]
        R = rows[t]
        nodes = OC.build_nodes(recs, lo, hi, R)
        groups, leak = OC.stream_durations(nodes, R)
        ca = cmd_args(recs, lo, hi)
        for n in nodes:
            r = recs[n.pc]
            o = r.opcode
            if n.kind == "arg":
                continue
            if o == SF.OP_CMD:
                lop, a0, a1, a2, na = ca[n.pc]
                cls = R[n.pc][3]
                data.append((t, "CMD", (lop, a0, a1, a2, na,
                                        cls[0], cls[1]), n.dur))
            elif o == SF.OP_CSRWR:
                data.append((t, "CSRWR", (r.target, r.ind), n.dur))
            elif o == SF.OP_MOVX:
                data.append((t, "MOVX", (r.len_or_addr_hi & 0xFFFFFF, r.chan,
                                         r.addr_lo & 0xFFFF), n.dur))
            elif o == SF.OP_MOVY:
                data.append((t, "MOVY", (r.len_or_addr_hi & 0xFFFFFF,
                                         r.movy_mode, r.chan, r.ind), n.dur))
            elif o == SF.OP_MVGO:
                beats = (r.len_or_addr_hi >> 8) & 0xFFFFFF
                data.append((t, "MVGO", (beats, r.chan, n.nrows), n.dur))
                data.append((t, "STREAM", (beats, r.chan, n.nrows,
                                           len(groups[n.grp]["mvgos"])), n.S))
            elif o == SF.OP_FENCE:
                g = groups[n.grp]
                data.append((t, "FENCE", (len(g["mvgos"]),), n.dur))
                data.append((t, "TAU", (len(g["mvgos"]),
                                        tuple(sorted(nodes[m].chan
                                                     for m in g["mvgos"]))),
                             g["tau"]))
            elif o == SF.EXT_LDC:
                data.append((t, "LDC", (r.imm32 & 0xFFFFFF, r.ind), n.dur))
            elif o == SF.OP_EMB:
                data.append((t, "EMB", (r.len_or_addr_hi & 0xFFFFFF,), n.dur))
            else:
                data.append((t, SF.OP_NAME.get(o, str(o)), (), n.dur))
        print(f"=== token {t}: segment {lo}..{hi}, {len(nodes)} nodes, "
              f"{len(groups)} groups, leak {leak}, window sum "
              f"{sum(n.dur for n in nodes)}")
    return recs, data


def stats(v):
    v = np.asarray(v, dtype=np.float64)
    return (f"n {len(v):6d} mean {v.mean():11.2f} min {v.min():9.0f} "
            f"max {v.max():9.0f} sd {v.std():9.2f}")


def census_print(data):
    by = collections.defaultdict(list)
    for t, k, f, v in data:
        by[k].append((t, f, v))
    for k in sorted(by):
        print(f"\n##### {k}: {stats([v for _t, _f, v in by[k]])}")
    # CSRWR by (target, ind)
    g = collections.defaultdict(list)
    for t, f, v in by["CSRWR"]:
        g[f].append(v)
    print("\n--- CSRWR (non-ARG) by (target, ind)")
    for f in sorted(g):
        print(f"  {f[0]:#06x} ind {f[1]}: {stats(g[f])}")
    # CMD by key
    sys.path.insert(0, os.path.join(REPO, "evidence", "qwen9b", "sd"))
    import sd1_common as C
    g = collections.defaultdict(list)
    gl = collections.defaultdict(list)
    gd = collections.defaultdict(list)
    gn = collections.defaultdict(list)
    for t, f, v in by["CMD"]:
        lop, a0, a1, a2, na, lcmp, ldma = f
        key = C.key_of(lop, a0, a1, a2)
        if lop in (13, 14):
            kind, slot, _l, _h = SF.sdma_fields(a0)
            key = key + (kind,)
        if lop == 6:
            key = key + ((a0 >> 14) & 0x3FFF,)
        if lop == 10:
            key = key + (f"tok{t}",)
        g[key].append(v)
        gl[key].append(v - lcmp)
        gd[key].append(ldma)
        gn[key].append(na)
    print("\n--- CMD node dur by key (dur includes merged ARG CSRWRs); "
          "dur-L_CMP; L_DMA; nargs")
    for key in sorted(g, key=str):
        print(f"  {str(key):44s} {stats(g[key])} | dur-Lcmp mean "
              f"{np.mean(gl[key]):9.2f} min {min(gl[key]):6d} max "
              f"{max(gl[key]):6d} | L_DMA mean {np.mean(gd[key]):9.2f} | "
              f"nargs {sorted(set(gn[key]))}")
    for k, keyf in (("MOVX", lambda f: f[0]), ("MOVY", lambda f: (f[0], f[1])),
                    ("MVGO", lambda f: f[1]), ("STREAM", lambda f: (f[0], f[3])),
                    ("FENCE", lambda f: f[0]), ("TAU", lambda f: f[0]),
                    ("LDC", lambda f: (f[0], f[1])), ("EMB", lambda f: f[0])):
        g = collections.defaultdict(list)
        for t, f, v in by[k]:
            g[keyf(f)].append(v)
        print(f"\n--- {k} by feature")
        for key in sorted(g, key=str):
            print(f"  {str(key):24s} {stats(g[key])}")



def detail(recs, tok=4):
    """Token `tok`: every VNW / SLD / SST / CONV / KVAP CMD and every CMD whose
    window exceeds its busy_cmp by more than 70 cycles, in program order,
    with the DMA-lane busy (L_DMA) it overlapped."""
    rows = OC.load_csv(toks=(tok,))[tok]
    lo, hi = token_segments(recs)[tok]
    ca = cmd_args(recs, lo, hi)
    for pc in range(lo, hi + 1):
        r = recs[pc]
        if r.opcode != SF.OP_CMD:
            continue
        lop, a0, a1, a2, na = ca[pc]
        op, c0, dur, cls = rows[pc]
        lcmp, ldma = cls[0], cls[1]
        interesting = lop in (2, 6, 9, 13, 14) or dur - lcmp > 70
        if not interesting:
            continue
        extra = ""
        if lop in (13, 14):
            kind, slot, layer, head = SF.sdma_fields(a0)
            extra = f"kind {kind} slot {slot} layer {layer} head {head}"
        elif lop == 2:
            extra = f"n {a0 & 0x1FFF}"
        print(f"  pc {pc:6d} cyc0 {c0:9d} lop {lop:2d} dur {dur:6d} "
              f"Lcmp {lcmp:6d} Ldma {ldma:6d} over {dur - lcmp:6d} {extra}")


# ======================================================================
# fit — the per-class formulas ref/seq_cost.py carries
# ======================================================================
ALU_NAME = {0: "DYNQ8", 1: "SHIFT32", 2: "SCALE", 3: "EMUL", 4: "ADD",
            5: "SILU16", 6: "SILU32", 7: "SIGM16", 8: "EMUL32",
            9: "SHIFT32W", 10: "AMAX32", 12: "DYNQ16"}
VN_NAME = {0: "rmsnorm0", 1: "rmsnorm1", 2: "l2norm", 3: "mode3"}
LOP_NAME = {1: "VN", 2: "VNW", 3: "ROPET", 4: "ROPE", 5: "CONVW",
            6: "CONV", 7: "GATE", 8: "DNST", 9: "KVAP", 10: "ATTN",
            11: "ALU", 12: "DNZ", 13: "SLD", 14: "SST"}


def fkey(lop, a0, a1, a2):
    """The fit's command key: sd1_common.key_of for ALU/VN (E1's keys),
    the size field for VNW/CONV, the bare name otherwise."""
    if lop == 11:
        sub = a0 & 0xF
        n = GLS.dec_alu_len(a0)
        p0 = GLS.dec_alu_p0(a0, a2)
        k = ("ALU", ALU_NAME.get(sub, f"sub{sub}"), n)
        if sub == 8 and (p0 & SF.ALU_PROBE_BIT) and p0 < (1 << 16):
            k = k + ("probe",)
        return k
    if lop == 1:
        mode = a0 & 0x3
        n = 1 << ((a0 >> 2) & 0xF)
        name = VN_NAME[mode]
        if mode == SF.VN_EPSNORM_MODE and (a2 & SF.VN_ARG2_EPS):
            name = "EPS-NORM"
        return ("VN", name, n)
    if lop == 2:
        return ("VNW", a0 & 0x1FFF)
    if lop == 6:
        return ("CONV", (a0 >> 14) & 0x3FFF)
    return (LOP_NAME.get(lop, f"op{lop}"),)


def lsq(x, y):
    """y = a + b*x, least squares; -> (a, b, residuals)."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    A = np.vstack([np.ones_like(x), x]).T
    (a, b), *_ = np.linalg.lstsq(A, y, rcond=None)
    return float(a), float(b), y - (a + b * x)


def rq(res):
    res = np.asarray(res, dtype=np.float64)
    return (f"resid max|.| {np.abs(res).max():8.2f}  rms "
            f"{np.sqrt((res ** 2).mean()):8.3f}  sum {res.sum():+10.1f}")


def dma_burst_index(recs, lo, hi):
    """pc -> 1-based position of an SLD/SST CMD in its run of consecutive
    DMA commands (a run ends at any non-DMA layer CMD)."""
    arg0 = 0
    k = 0
    out = {}
    for pc in range(lo, hi + 1):
        r = recs[pc]
        if r.opcode == SF.OP_CMD:
            lop = r.imm32 & 0xFF
            if lop in (SF.OP_L_SLD, SF.OP_L_SST):
                k += 1
                out[pc] = k
            else:
                k = 0
    return out


def fit(recs, data):
    T = {}
    by = collections.defaultdict(list)
    for t, k, f, v in data:
        by[k].append((t, f, v))
    E1 = parse_e1()
    print("\n=== CMD: node window (ARG CSRWRs merged) per key")
    cmd = collections.defaultdict(list)
    segs = token_segments(recs)
    bidx = {t: dma_burst_index(recs, *segs[t]) for t in TOKS}
    # the burst index needs the pc: re-walk the CMD pcs in the order data
    # was collected (build_nodes order == program order)
    pcs = {}
    for t in TOKS:
        lo, hi = segs[t]
        pcs[t] = [pc for pc in range(lo, hi + 1)
                  if recs[pc].opcode == SF.OP_CMD]
    it = {t: iter(pcs[t]) for t in TOKS}
    for t, f, v in by["CMD"]:
        pc = next(it[t])
        lop, a0, a1, a2, na, lcmp, ldma = f
        cmd[fkey(lop, a0, a1, a2)].append((t, pc, v, lcmp, na))
    ovh, fixed = {}, {}
    for key in sorted(cmd, key=str):
        v = cmd[key]
        durs = [d for (_t, _pc, d, _l, _n) in v]
        if key[0] in ("ALU", "VN"):
            o = [d - l for (_t, _pc, d, l, _n) in v]
            ovh[key] = int(round(float(np.mean(o))))
            e1 = E1.get(key)
            lc = float(np.mean([l for (_t, _pc, _d, l, _n) in v]))
            pred = [(e1 if e1 is not None else lc) + ovh[key]] * len(v)
            print(f"  {str(key):40s} n {len(v):5d}  E1 busy "
                  f"{e1 if e1 is not None else 'ABSENT':>8}  chip L_CMP mean "
                  f"{lc:9.2f}  overhead (node - L_CMP) mean "
                  f"{np.mean(o):7.2f} -> {ovh[key]}  static "
                  f"{pred[0]:.0f}  {rq(np.array(durs) - np.array(pred))}")
        elif key[0] == "ATTN":
            a, b, res = lsq([t - 1 for (t, *_r) in v], durs)
            T["ATTN"] = (int(round(a)), int(round(b)))
            print(f"  {str(key):40s} n {len(v):5d}  dur = a + b*pos (pos = "
                  f"token - 1): a {a:.3f} b {b:.3f}  {rq(res)}")
        elif key[0] == "VNW":
            o = [d - (3 * key[1] + 1) for (_t, _pc, d, _l, _n) in v]
            lc = [l - (3 * key[1] + 1) for (_t, _pc, _d, l, _n) in v]
            ovh[key] = int(round(float(np.mean(o))))
            print(f"  {str(key):40s} n {len(v):5d}  L_CMP - (3n+1): "
                  f"min {min(lc)} max {max(lc)};  node - (3n+1) mean "
                  f"{np.mean(o):.2f} -> {ovh[key]}  "
                  f"{rq(np.array(o) - ovh[key])}")
        elif key[0] in ("SLD", "SST"):
            bi = [bidx[t][pc] for (t, pc, *_r) in v]
            base = [d for d, b in zip(durs, bi) if b < DMA_QDEPTH_FIT]
            stall = [d for d, b in zip(durs, bi) if b >= DMA_QDEPTH_FIT]
            T[key[0]] = int(round(float(np.mean(base))))
            print(f"  {str(key):40s} n {len(v):5d}  burst index "
                  f"{collections.Counter(bi)};  base (index < "
                  f"{DMA_QDEPTH_FIT}) {stats(base)}")
            if stall:
                T[key[0] + "_STALL"] = int(round(float(np.mean(stall))))
                print(f"  {'':40s}            stall (index >= "
                      f"{DMA_QDEPTH_FIT}) {stats(stall)}")
            print(f"  {'':40s}            other: index >= {DMA_QDEPTH_FIT} "
                  f"with a short window "
                  f"{sum(1 for x in stall if x < 1000)}, index < "
                  f"{DMA_QDEPTH_FIT} with a long one "
                  f"{sum(1 for x in base if x >= 1000)}")
        else:
            fixed[key] = int(round(float(np.mean(durs))))
            print(f"  {str(key):40s} n {len(v):5d}  {stats(durs)} -> "
                  f"{fixed[key]}  {rq(np.array(durs) - fixed[key])}")
    T["CMD_OVH"] = ovh
    T["CMD_FIXED"] = fixed
    vals = sorted(o for k, o in ovh.items() if k[0] == "ALU")
    T["CMD_OVH_DEFAULT"] = vals[len(vals) // 2]
    print(f"  overhead for an E1 key absent from the stream: the median of "
          f"the measured ALU overheads {vals} -> {T['CMD_OVH_DEFAULT']}")

    print("\n=== movers / streams / bulk")
    x = [f[0] for (_t, f, _v) in by["MOVX"]]
    y = [v for (_t, _f, v) in by["MOVX"]]
    a, b, res = lsq(x, y)
    T["MOVX"] = (round(a, 4), round(b, 6))
    print(f"  MOVX   dur = a + b*len: a {a:.4f} b {b:.6f}  lens "
          f"{sorted(set(x))}  {rq(res)}")
    for mode in (0, 1):
        sel = [(f[0], v) for (_t, f, v) in by["MOVY"] if f[1] == mode]
        a, b, res = lsq([s[0] for s in sel], [s[1] for s in sel])
        T[f"MOVY{mode}"] = (round(a, 4), round(b, 6))
        print(f"  MOVY mode {mode} ({'pairs32' if mode == 0 else 'int16'}) "
              f"dur = a + b*len: a {a:.4f} b {b:.6f}  lens "
              f"{sorted(set(s[0] for s in sel))}  {rq(res)}")
    sel = [(f[0], v) for (_t, f, v) in by["STREAM"]]
    a, b, res = lsq([s[0] for s in sel], [s[1] for s in sel])
    T["STREAM"] = (round(a, 4), round(b, 6))
    print(f"  STREAM S (engine-busy, MVGO..FENCE) = a + b*beats: a {a:.4f} "
          f"b {b:.6f} (= {1.0 / b:.4f} beats/cycle)  beats "
          f"{sorted(set(s[0] for s in sel))}  {rq(res)}")
    y = [v for (_t, _f, v) in by["MVGO"]]
    T["MVGO"] = int(round(float(np.mean(y))))
    print(f"  MVGO   issue window {stats(y)} -> {T['MVGO']}  "
          f"{rq(np.array(y) - T['MVGO'])}")
    for ng in (2, 4):
        y = [v for (_t, f, v) in by["TAU"] if f[0] == ng]
        T[f"TAU{ng}"] = int(round(float(np.mean(y))))
        print(f"  TAU    FENCE poll tail, {ng}-stream groups {stats(y)} -> "
              f"{T[f'TAU{ng}']}  {rq(np.array(y) - T[f'TAU{ng}'])}")
    sel = [(f[0], v) for (_t, f, v) in by["LDC"]]
    a, b, res = lsq([s[0] for s in sel], [s[1] for s in sel])
    T["LDC"] = (round(a, 4), round(b, 6))
    print(f"  LDC    dur = a + b*count: a {a:.4f} b {b:.6f}  counts "
          f"{sorted(set(s[0] for s in sel))}  {rq(res)}")
    for k in ("EMB", "XOP*", "AMAXL", "JMP"):
        y = [v for (_t, _f, v) in by[k]]
        if k == "JMP":
            y = [v for (t, _f, v) in by[k] if t in (4, 5)]   # taken
        T[k.rstrip("*")] = int(round(float(np.mean(y))))
        print(f"  {k:6s} {stats(y)} -> {T[k.rstrip('*')]}  "
              f"{rq(np.array(y) - T[k.rstrip('*')])}")
    g = collections.defaultdict(list)
    for (_t, f, v) in by["CSRWR"]:
        g[f[0]].append(v)
    T["CSRWR"] = {k: int(round(float(np.mean(v)))) for k, v in g.items()}
    print(f"  CSRWR  by target: " + ", ".join(
        f"{k:#06x}: {stats(v)}" for k, v in sorted(g.items())))
    return T


DMA_QDEPTH_FIT = 6     # the 6th DMA command of a run is the one that stalls


def parse_e1():
    """E1's per-key busy_cmp mean (evidence/qwen9b/sd/014_e1_analysis.log)."""
    import re
    out = {}
    p = os.path.join(REPO, "evidence", "qwen9b", "sd", "014_e1_analysis.log")
    for line in open(p):
        m = re.match(r"^\s+(ALU|VN)\|(\S+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)"
                     r"\s+([\d.]+)\s+([\d.]+)\s", line)
        if not m:
            continue
        parts = m.group(2).split("|")
        key = (m.group(1), parts[0], int(parts[1])) + tuple(parts[2:])
        out[key] = float(m.group(7))
    return out


def compare_table(T):
    """The fitted table against ref/seq_cost.py's committed constants."""
    import seq_cost as SC
    pairs = [("CMD_OVH", T["CMD_OVH"], SC.CMD_OVH),
             ("CMD_OVH_DEFAULT", T["CMD_OVH_DEFAULT"], SC.CMD_OVH_DEFAULT),
             ("CMD_FIXED", T["CMD_FIXED"], SC.CMD_FIXED),
             ("ATTN", T["ATTN"], SC.ATTN),
             ("SDMA", (T["SLD"], T["SST"]), (SC.SDMA, SC.SDMA)),
             ("SDMA_STALL", T["SLD_STALL"], SC.SDMA_STALL),
             ("MOVX", T["MOVX"], SC.MOVX),
             ("MOVY pairs32", T["MOVY0"], SC.MOVY[SF.MOVY_PAIRS32]),
             ("MOVY int16", T["MOVY1"], SC.MOVY[SF.MOVY_INT16]),
             ("LDC", T["LDC"], SC.LDC),
             ("EMB", T["EMB"], SC.EMB[4096]),
             ("MVGO", T["MVGO"], SC.MVGO),
             ("STREAM", T["STREAM"], SC.STREAM),
             ("TAU", {2: T["TAU2"], 4: T["TAU4"]}, SC.TAU),
             ("XOP/AMAXL/JMP", (T["XOP"], T["AMAXL"], T["JMP"]),
              (SC.XOP, SC.AMAXL, SC.JMP))]
    bad = 0
    print("\n=== the fitted table vs ref/seq_cost.py")
    for name, fitv, tab in pairs:
        same = fitv == tab
        bad += not same
        print(f"  {name:16s} {'MATCH' if same else 'DIFFER'}"
              + ("" if same else f"  fit {fitv!r}  table {tab!r}"))
    e1 = parse_e1()
    for k, v in SC.E1_BUSY.items():
        same = int(round(e1[k])) == v
        bad += not same
        if not same:
            print(f"  E1 {k}: log {e1[k]} table {v} DIFFER")
    print(f"  E1_BUSY: {len(SC.E1_BUSY)} keys vs the E1 log "
          f"({len(e1)} keys): "
          + ("MATCH" if set(e1) == set(SC.E1_BUSY) else "KEY SETS DIFFER"))
    bad += set(e1) != set(SC.E1_BUSY)
    print(f"  TABLE {'MATCHES' if not bad else 'DIFFERS FROM'} THE FIT "
          f"({bad} differences)")
    return bad


def residuals(recs):
    """Per token: OV1's nodes built from the CSV and from ref/seq_cost.py's
    static rows (the segment priced at position token-1), compared node by
    node — window, stream S, poll tail tau — and summed."""
    import seq_cost as SC
    rows = OC.load_csv(toks=TOKS)
    segs = token_segments(recs)
    print("\n=== static rows vs the CSV, node by node (static - CSV)")
    tot = collections.defaultdict(lambda: [0, 0, 0, 0])
    for t in TOKS:
        lo, hi = segs[t]
        Rc = rows[t]
        Rs = SC.cost_of_segment(recs, lo, hi, t - 1)
        nc = OC.build_nodes(recs, lo, hi, Rc)
        gc, _ = OC.stream_durations(nc, Rc)
        ns = OC.build_nodes(recs, lo, hi, Rs)
        gs, _ = OC.stream_durations(ns, Rs)
        per = collections.defaultdict(lambda: [0, 0, 0, 0])
        for a, b in zip(nc, ns):
            assert a.pc == b.pc
            if a.kind == "arg":
                continue
            k = SF.OP_NAME.get(a.op, str(a.op))
            if a.kind == "fence":
                continue
            d = b.dur - a.dur
            per[k][0] += 1
            per[k][1] += d
            per[k][2] += abs(d)
            per[k][3] = max(per[k][3], abs(d))
            if a.kind == "mvgo":
                d = b.S - a.S
                per["STREAM"][0] += 1
                per["STREAM"][1] += d
                per["STREAM"][2] += abs(d)
                per["STREAM"][3] = max(per["STREAM"][3], abs(d))
        for x, y in zip(gc, gs):
            d = y["tau"] - x["tau"]
            per["TAU"][0] += 1
            per["TAU"][1] += d
            per["TAU"][2] += abs(d)
            per["TAU"][3] = max(per["TAU"][3], abs(d))
        ws = sum(Rs[pc][2] for pc in range(lo, hi + 1))
        wc = sum(Rc[pc][2] for pc in range(lo, hi + 1))
        v0c, _ = OC.today_replay(nc, gc)
        v0s, _ = OC.today_replay(ns, gs)
        print(f"  token {t} (pos {t - 1}): window sum CSV {wc} static {ws} "
              f"(static - CSV {ws - wc:+d} = "
              f"{100.0 * (ws - wc) / wc:+.4f} %);  V0 replay CSV {v0c} "
              f"static {v0s} ({100.0 * (v0s - v0c) / v0c:+.4f} %)")
        for k in sorted(per):
            v = per[k]
            for i in range(3):
                tot[k][i] += v[i]
            tot[k][3] = max(tot[k][3], v[3])
    print("  per class over tokens 1..6 (n, signed sum, sum |d|, max |d| "
          "in cycles; STREAM = MVGO S, TAU = per group):")
    for k in sorted(tot):
        n, s, a, m = tot[k]
        print(f"    {k:8s} n {n:6d}  signed {s:+9d}  |sum| {a:9d}  "
              f"max {m:6d}  mean|d| {a / max(n, 1):8.3f}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "census"
    if mode == "detail":
        recs, _man = OC.load_stream()
        detail(recs, int(sys.argv[2]) if len(sys.argv) > 2 else 4)
        return
    recs, data = collect()
    if mode == "census":
        census_print(data)
    elif mode == "fit":
        T = fit(recs, data)
        print("\n=== THE FITTED TABLE")
        for k in sorted(T):
            print(f"  {k}: {T[k]!r}")
        bad = compare_table(T)
        residuals(recs)
        if bad:
            raise SystemExit(1)
    else:
        raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    main()
