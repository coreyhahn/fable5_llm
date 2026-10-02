#!/usr/bin/env python3
"""sr11b_model_correction.py — Task SR11b, the controller's addendum (from
SR5b, as CORRECTED after the SR5b review): re-fit the FENCE cost convention
BEFORE any R2 prediction.

    FABLE5_MODEL=9b /home/cah/.venv/bin/python \
        evidence/qwen9b/sr/sr11b_model_correction.py --fit
    FABLE5_MODEL=9b /home/cah/.venv/bin/python \
        evidence/qwen9b/sr/sr11b_model_correction.py --verify

Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh.  READ-ONLY over every
input; stdout only.

WHAT WAS WRONG (SR5b §4/§7, n570:79-98, n591:16-19).  The pass's replay
(ref/scripts/reorder_e4.replay) prices a FENCE as the wait for the
stream(s) it drains, ending tau after the last stream end, where tau is the
ORIGINAL 4-channel group's poll tail on BN1's CSV; the FENCE record itself
costs 0.  On the chip TB every FENCE record costs 23 cycles (981 zero-wait
FENCEs, min = max = 23, n570:80), and the single-channel tails are
over-priced (the 389 waiting FENCEs by 22,604 cyc net of their record cost,
class-dependent: DN dn_out about -9,525 over 96).  At R1's operating point
the two cancel; a stream with another mix would not.

THE CORRECTED CONVENTION (ref/seq_cost.py FENCE_REC / TAIL1 / CMD_RESID_FRAC,
priced by reorder_e4.predict):
  FENCE end = max(t, max over the drained streams (stream end + tail_k)) + 23
with tail_k fitted PER DRAINED CLASS k (the matvec class of the stream,
ov_census.segment_matvecs' label), and the inherited CMD contention residual
(+19,308 cyc = CMD_RESID_FRAC x the CMD+ARG work, n570:67) added to the
makespan.  Zero-wait FENCEs therefore cost exactly 23.

--fit   the tail per class from the MEASURED R1 run (n564's timeline CSV,
        gitignored, sha256-checked against the committed
        evidence/qwen9b/sr/sr5b_timeline_model_9b_s1_reordB_r1.csv.sha256):
        for every emitted FENCE of the s1 loop body that WAITED on the TB
        (window > 23), the effective tail is
            FENCE end - 23 - (drained MVGO's measured end + its MODEL S),
        i.e. what the model must add after its own stream end to land on
        the measured FENCE end.  Fitted on TOKENS 5 AND 6 (the body's other
        two executions); token 4 — the prediction target — is HELD OUT.
        The split of that tail into (measured S - model S) and the tail net
        of the measured S is printed as a diagnostic.
--verify the corrected model (the constants now in ref/seq_cost.py, through
        reorder_e4.predict) re-predicts the s1 token-4 body window against
        the measured 27,163,998 (n570:39), class by class beside the old
        model: zero-wait FENCEs, waiting FENCEs by drained class, the CMD
        residual — PLACED in lane time on the commands the TB measured
        it on (the FENCE convention judged alone) and ADDITIVE (the form
        every r2 prediction uses).
--diag  where the residual FENCE error sits: n1158 found the "CMD
        contention residual" is one DMA-queue stall on an SLD (+17,212 =
        17,251 - 39) that the reordered order incurs and the program-order
        windows do not carry, plus the KVAPs; the stalled SLD sits in the
        dn_out lane gaps and absorbs those FENCEs' waits.  No order-only
        rule places that stall (n1191).
"""
import argparse
import collections
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for p in (os.path.join(REPO, "ref"), os.path.join(REPO, "ref", "scripts"),
          os.path.join(REPO, "evidence", "qwen9b", "ov")):
    if p not in sys.path:
        sys.path.insert(0, p)

import seq_format as SF                      # noqa: E402
import reorder_e4 as RE                      # noqa: E402
import ov_census as OC                        # noqa: E402

W9 = os.path.join(REPO, "tb", "scripts", "w9")
SRC = os.path.join(W9, "model_9b_s1.e4")
R1_STREAM = os.path.join(W9, "model_9b_s1_reordB_r1.e4.seq")
R1_SHA = "4e11a2ae6872970ecb61e2bb37524b7bd863815e47df1fb9c3af2fbb3218cb28"  # n410:58
CSV = os.path.join(W9, "model_9b_s1_reordB_r1.timeline.csv")
CSV_SHA = os.path.join(HERE, "sr5b_timeline_model_9b_s1_reordB_r1.csv.sha256")
PRED_OLD = 27136513          # n570:61 (= SR4's replay, n410:49)
MEAS4 = 27163998             # n570:39
REC = 23                     # n570:80: min = max = 23 over 981 zero-wait
FIT_TOKS = (5, 6)
HOLD_TOK = 4
BSYC = 18                    # CSV column of MV0_BSY (the #COLS header)


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for ch in iter(lambda: f.read(1 << 24), b""):
            h.update(ch)
    return h.hexdigest()


def read_csv(path, toks):
    """-> {tok: {pc: (op, cyc0, ncyc, (bsy0..bsy3))}}"""
    rows = {t: {} for t in toks}
    with open(path) as f:
        for line in f:
            if not line.startswith("R,"):
                continue
            p = line.rstrip("\n").split(",")
            if len(p) != 32:
                continue
            t = int(p[2])
            if t not in rows:
                continue
            rows[t][int(p[3])] = (int(p[4]), int(p[8]), int(p[9]),
                                  tuple(int(x) for x in p[BSYC:BSYC + 4]))
    return rows


def model_r1_body():
    """The pass's own r1 schedule of the s1 body at BN1's CSV windows — the
    model SR4 predicted with (n410) and sr_derive reproduced (n570:61-63)."""
    recs = SF.unpack_stream(open(SRC + ".seq", "rb").read())
    _pro, sg, _h = RE.segments(recs)
    kb = [k for k, x in enumerate(sg) if x[2]]
    assert len(kb) == 1
    k = kb[0]
    lo, hi, _b = sg[k]
    rows = RE.Windows().rows_for(recs)(k, lo, hi)
    S = RE.schedule_segment(recs, lo, hi, rows, "B", "r1")
    order = RE.order_and_fences(S, "r1")
    rmk, _post, _st = RE.replay(S, order)
    print(f"  model: body {lo}..{hi}; replay of the emitted r1 order {rmk} "
          f"(SR4's prediction {PRED_OLD}: "
          f"{'REPRODUCED' if rmk == PRED_OLD else 'DIFFERS'})")
    if rmk != PRED_OLD:
        raise SystemExit("the r1 model does not reproduce SR4's prediction")
    items = RE.emit_segment(recs, S, order)
    got = sha_file(R1_STREAM)
    if got != R1_SHA:
        raise SystemExit(f"r1 stream sha {got[:16]} != {R1_SHA[:16]}")
    nrecs = SF.unpack_stream(open(R1_STREAM, "rb").read())
    jmp = [i for i, r in enumerate(nrecs) if r.opcode == SF.OP_JMP][0]
    blo = nrecs[jmp].imm32
    same = sum((r.opcode == SF.OP_JMP and nrecs[blo + j].opcode == SF.OP_JMP)
               or r.to_bytes() == nrecs[blo + j].to_bytes()
               for j, (_oi, r) in enumerate(items))
    print(f"  emitted body == the r1 stream's body {blo}..{jmp} (sha "
          f"{R1_SHA[:16]} MATCH): {same}/{len(items)} records identical")
    if same != len(items) or jmp - blo + 1 != len(items):
        raise SystemExit("emitted body differs from the r1 stream")
    return S, order, items, blo, jmp


def fence_walk(S, order, items, blo):
    """-> [(new pc of the FENCE, [drained MVGO node ids], old-model window)],
    {MVGO node id: new pc}; the old model = reorder_e4.replay's walk."""
    nodes = S["nodes"]
    tau = [S["groups"][n.grp]["tau"] if n.kind == "mvgo" else 0
           for n in nodes]
    node_of_pc = {n.pc: i for i, n in enumerate(nodes)}
    fpcs, mv_pc = [], {}
    for j, (oi, r) in enumerate(items):
        if r.opcode == SF.OP_FENCE:
            fpcs.append(blo + j)
        elif r.opcode == SF.OP_MVGO:
            mv_pc[node_of_pc[oi]] = blo + j
    t, pend, send, out = 0, [], {}, []
    for x in order:
        if RE.is_fence(x):
            fm = RE.fence_mask(x)
            sel = [m for m in pend if fm == 0 or (fm >> nodes[m].chan) & 1]
            t0 = t
            if sel:
                t = max(t, max(send[m] + tau[m] for m in sel))
            pend = [m for m in pend if m not in sel]
            out.append((sel, t - t0))
            continue
        t += nodes[x].dur
        if nodes[x].kind == "mvgo":
            send[x] = t + nodes[x].S
            pend.append(x)
    assert len(out) == len(fpcs)
    return [(fpcs[i], out[i][0], out[i][1]) for i in range(len(out))], mv_pc


def class_keys(S):
    nodes, groups = S["nodes"], S["groups"]
    mvs, _lt = OC.segment_matvecs(nodes, groups)
    return {i: (mvs[n.mv]["lt"], mvs[n.mv]["cls"])
            for i, n in enumerate(nodes) if n.kind == "mvgo"}


def measure(S, fences, mv_pc, rows, keys):
    """Per emitted FENCE on one token's measured rows: (key, waited,
    window, effective tail vs model S, net tail vs measured S, S_meas -
    S_model of the stream that ends last, old group tau)."""
    nodes = S["nodes"]
    out = []
    for (fpc, sel, _mw) in fences:
        op, c0, w, _b = rows[fpc]
        assert op == SF.OP_FENCE, (fpc, op)
        e = c0 + w
        eff, net, ds = None, None, None
        if sel:
            ends_mod, ends_meas = [], []
            for m in sel:
                mpc = mv_pc[m]
                _o, mc0, mw, _mb = rows[mpc]
                ch = nodes[m].chan
                smeas = sum(rows[p][3][ch] for p in range(mpc, fpc + 1))
                ends_mod.append((mc0 + mw + nodes[m].S, m, smeas))
                ends_meas.append(mc0 + mw + smeas)
            em, mlast, smeas = max(ends_mod)
            eff = e - REC - em
            net = e - REC - max(ends_meas)
            ds = smeas - nodes[mlast].S
        key = keys[sel[-1]] if sel else ("-", "none")
        tau_old = max(S["groups"][nodes[m].grp]["tau"] for m in sel) \
            if sel else 0
        out.append((key, w > REC, w, eff, net, ds, tau_old))
    return out


def load():
    want = open(CSV_SHA).read().split()[0]
    got = sha_file(CSV)
    print(f"=== R1 timeline {CSV}\n    sha256 {got}  committed {want}  "
          f"{'MATCH' if got == want else 'MISMATCH'}")
    if got != want:
        raise SystemExit("timeline sha mismatch")
    S, order, items, blo, jmp = model_r1_body()
    fences, mv_pc = fence_walk(S, order, items, blo)
    keys = class_keys(S)
    rows = read_csv(CSV, (HOLD_TOK,) + FIT_TOKS)
    # the timeline splits tokens at the EMB, and the r1 pass hoisted five
    # body records above the body's EMB (SR5b §3, n571), so the LAST token
    # (6) lacks those five: every token must hold every FENCE and MVGO pc
    # and every pc between an MVGO and the FENCE that drains it; token 4
    # (the prediction target) must hold the whole body (n570:64)
    need_pcs = set()
    for (fpc, sel, _mw) in fences:
        for m in sel:
            need_pcs.update(range(mv_pc[m], fpc + 1))
        need_pcs.add(fpc)
    for t, R in rows.items():
        miss = [pc for pc in range(blo, jmp + 1) if pc not in R]
        bad = [pc for pc in miss if pc in need_pcs]
        print(f"    token {t}: {len(miss)} body pcs absent "
              f"{[(pc, SF.OP_NAME.get(nrec_op(items, blo, pc))) for pc in miss][:6]}"
              f"; of them FENCE/stream-window pcs: {len(bad)}")
        if bad or (t == HOLD_TOK and miss):
            raise SystemExit(f"token {t}: {len(miss)} body pcs missing")
    print(f"    body FENCEs {len(fences)}; tokens read "
          f"{sorted(rows)}: {[len(rows[t]) for t in sorted(rows)]} rows")
    return S, order, items, blo, jmp, fences, mv_pc, keys, rows


def nrec_op(items, blo, pc):
    return items[pc - blo][1].opcode


def mean(v):
    return sum(v) / len(v) if v else float("nan")


def fit():
    S, order, items, blo, jmp, fences, mv_pc, keys, rows = load()
    per = {t: measure(S, fences, mv_pc, rows[t], keys) for t in rows}
    # the record cost, re-measured on every token
    for t in sorted(per):
        zw = [x[2] for x in per[t] if not x[1]]
        print(f"  token {t}: FENCEs not waiting on the TB {len(zw)}: window "
              f"min {min(zw)} max {max(zw)} (the record cost; REC = {REC})")
    print(f"\n=== THE FIT: effective single-channel tail per drained class, "
          f"over the FENCEs that WAITED on the TB, tokens {FIT_TOKS} "
          f"(token {HOLD_TOK} held out)")
    print("    key | n waited (fit) | tail = mean(FENCE end - 23 - (MVGO "
          "end + model S)) | of which mean(S_meas - S_model) | net tail "
          "(vs measured S) | old tau | token-4 in-sample tail (n)")
    by = collections.defaultdict(list)
    by4 = collections.defaultdict(list)
    allw = []
    for t in FIT_TOKS:
        for x in per[t]:
            if x[1] and x[3] is not None:
                by[x[0]].append(x)
                allw.append(x[3])
    for x in per[HOLD_TOK]:
        if x[1] and x[3] is not None:
            by4[x[0]].append(x)
    tail = {}
    for k in sorted(set(by) | set(by4)):
        v = by[k]
        if v:
            tail[k] = int(round(mean([x[3] for x in v])))
        v4 = by4[k]
        print(f"    {k[0]:4s} {k[1]:9s} | {len(v):4d} | "
              f"{mean([x[3] for x in v]):9.1f} | "
              f"{mean([x[5] for x in v]):9.1f} | "
              f"{mean([x[4] for x in v]):8.1f} | "
              f"{mean([x[6] for x in v]):6.1f} | "
              f"{mean([x[3] for x in v4]):9.1f} ({len(v4)})")
    dflt = int(round(mean(allw)))
    print(f"    pooled (every waited FENCE, tokens {FIT_TOKS}): n {len(allw)}, "
          f"tail {mean(allw):.1f} -> TAIL1_DEFAULT = {dflt}")
    print("\n=== constants for ref/seq_cost.py (transcribe; cite this log):")
    print(f"FENCE_REC = {REC}")
    print("TAIL1 = {")
    for k in sorted(tail):
        print(f"    {k!r}: {tail[k]},")
    print("}")
    print(f"TAIL1_DEFAULT = {dflt}")
    print("SR11B_MODEL_CORRECTION FIT: DONE")


def cmd_group(label):
    """A CMD node's label without its per-instance digits (DNSTh3 -> DNST,
    ALU.SHIFT32x2048 kept by sub-op and length)."""
    if label.startswith("DNST"):
        return "DNST"
    return label


def record_windows(S, items, blo, R):
    """Per emitted record j: (group, model window, measured window) with the
    ARG CSRWRs merged into their CMD on both sides (ov_census.build_nodes'
    convention) and FENCEs left out (group 'FENCE', model None)."""
    nodes = S["nodes"]
    node_of_pc = {n.pc: i for i, n in enumerate(nodes)}
    argset = {nodes[a].pc for al in RE.arg_owner(nodes).values() for a in al}
    out = []
    pend_meas = 0
    for j, (oi, r) in enumerate(items):
        w = R[blo + j][2]
        if r.opcode == SF.OP_FENCE:
            out.append(("FENCE", None, w))
            continue
        if oi in argset:
            pend_meas += w
            out.append(("ARG", 0, 0))
            continue
        n = nodes[node_of_pc[oi]]
        if r.opcode == SF.OP_CMD:
            out.append(("CMD " + cmd_group(n.label), n.dur, w + pend_meas))
            pend_meas = 0
        else:
            out.append((OC.OPN.get(r.opcode, str(r.opcode)), n.dur, w))
    return out


def diag():
    """Where the dn_out FENCE error comes from: per FENCE of each drained
    class, the lane gap from the drained MVGO's end to the FENCE's start,
    model vs measured (token 4), and the per-record-group window deltas
    inside those gaps; then the CMD+ARG residual by command group over the
    whole body, on tokens 4, 5, 6 (model: BN1's CSV windows of the SAME
    token; the r1 CSV measured)."""
    S, order, items, blo, jmp, fences, mv_pc, keys, rows = load()
    nodes = S["nodes"]
    recs = SF.unpack_stream(open(SRC + ".seq", "rb").read())
    _pro, sg, _h = RE.segments(recs)
    lo, hi, _b = [x for x in sg if x[2]][0]
    bn = OC.load_csv(toks=(4, 5, 6))
    print("\n=== CMD+ARG residual by command group, measured (r1 CSV) - "
          "model (BN1 CSV, the same token), s1 body")
    node_of_pc = {n.pc: i for i, n in enumerate(nodes)}
    for t in (4, 5, 6):
        R = rows[t]
        B = bn[t]
        # the model window of token t: re-merge BN1's token-t rows
        mw = {}
        pend = 0
        for pc in range(lo, hi + 1):
            n = nodes[node_of_pc[pc]]
            if n.kind == "arg":
                pend += B[pc][2]
            elif n.op == SF.OP_CMD:
                mw[pc] = B[pc][2] + pend
                pend = 0
        grp = collections.defaultdict(lambda: [0, 0, 0])
        pend_meas = 0
        argset = {nodes[a].pc for al in RE.arg_owner(nodes).values()
                  for a in al}
        for j, (oi, r) in enumerate(items):
            if blo + j not in R:
                continue
            w = R[blo + j][2]
            if oi in argset:
                pend_meas += w
            elif r.opcode == SF.OP_CMD:
                g = cmd_group(nodes[node_of_pc[oi]].label)
                grp[g][0] += 1
                grp[g][1] += mw[oi]
                grp[g][2] += w + pend_meas
                pend_meas = 0
        tot = [sum(v[i] for v in grp.values()) for i in range(3)]
        print(f"  token {t}: {tot[0]} CMDs, model {tot[1]}, measured "
              f"{tot[2]}, measured - model {tot[2] - tot[1]:+d}")
        for g in sorted(grp, key=lambda g: -abs(grp[g][2] - grp[g][1]))[:12]:
            n_, a, b = grp[g]
            print(f"      {g:28s} n {n_:5d}  {b - a:+8d}  ({(b - a) / n_:+.1f}"
                  f" per command)")
    print("\n=== token 4: the lane gap MVGO end -> FENCE start, by drained "
          "class (sum over the class's FENCEs; model = the old replay)")
    R = rows[HOLD_TOK]
    win = record_windows(S, items, blo, R)
    # model lane times per emitted record (the old replay)
    tau = [S["groups"][n.grp]["tau"] if n.kind == "mvgo" else 0
           for n in nodes]
    t, pend, send = 0, [], {}
    mstart = []
    k = 0
    fin_by_pos = {}
    for x in order:
        if RE.is_fence(x):
            fm = RE.fence_mask(x)
            sel = [m for m in pend if fm == 0 or (fm >> nodes[m].chan) & 1]
            mstart.append(t)
            if sel:
                t = max(t, max(send[m] + tau[m] for m in sel))
            pend = [m for m in pend if m not in sel]
            continue
        t += nodes[x].dur
        if nodes[x].kind == "mvgo":
            send[x] = t + nodes[x].S
            pend.append(x)
            fin_by_pos[x] = t
    by = collections.defaultdict(lambda: collections.Counter())
    for i, (fpc, sel, mw) in enumerate(fences):
        if not sel:
            continue
        key = keys[sel[-1]]
        m = max(sel, key=lambda q: mv_pc[q])
        mpc = mv_pc[m]
        gap_model = mstart[i] - fin_by_pos[m]
        gap_meas = R[fpc][1] - (R[mpc][1] + R[mpc][2])
        c = by[key]
        c["n"] += 1
        c["gap_model"] += gap_model
        c["gap_meas"] += gap_meas
        c["fence_model"] += mw
        c["fence_meas"] += R[fpc][2]
        for j in range(mpc - blo + 1, fpc - blo):
            g, a, b = win[j]
            if a is not None:
                c["d:" + g] += b - a
    for key in sorted(by, key=lambda k: -abs(by[k]["fence_meas"]
                                             - by[k]["fence_model"])):
        c = by[key]
        ds = sorted(((k2[2:], v) for k2, v in c.items()
                     if k2.startswith("d:") and v), key=lambda kv: -abs(kv[1]))
        print(f"  {key[0]:4s} {key[1]:9s} n {c['n']:4d}: FENCE meas - model "
              f"{c['fence_meas'] - c['fence_model']:+7d}; gap meas - model "
              f"{c['gap_meas'] - c['gap_model']:+7d}; inside the gaps: "
              + ", ".join(f"{g} {v:+d}" for g, v in ds[:5]))
    # the DMA-queue stall: seq_cost's rule (the 6th DMA command of a run of
    # consecutive DMA CMDs waits, SDMA_STALL; a compute CMD resets the run)
    # evaluated in PROGRAM order (what BN1's windows carry) and in the
    # EMITTED order (what the TB ran), beside the measured windows
    import seq_cost as SC
    DMA = (SF.OP_L_SLD, SF.OP_L_SST)
    prog, burst = {}, 0
    for pc in range(lo, hi + 1):
        r = recs[pc]
        if r.opcode == SF.OP_CMD:
            burst = burst + 1 if (r.imm32 & 0xFF) in DMA else 0
            prog[pc] = burst
    print(f"\n=== the DMA queue (seq_cost: DMA_QDEPTH {SC.DMA_QDEPTH}, stall "
          f"{SC.SDMA_STALL}, enqueue {SC.SDMA}), token 4: every SLD/SST whose "
          f"burst position or window differs between program and emitted "
          f"order / model and measured")
    R = rows[HOLD_TOK]
    burst = 0
    npm = nem = nmeas = 0
    pend_meas = 0
    argset = {nodes[a].pc for al in RE.arg_owner(nodes).values() for a in al}
    for j, (oi, r) in enumerate(items):
        w = R[blo + j][2]
        if oi in argset:
            pend_meas += w
            continue
        if r.opcode != SF.OP_CMD:
            continue
        lop = r.imm32 & 0xFF
        burst = burst + 1 if lop in DMA else 0
        wm = w + pend_meas
        pend_meas = 0
        if lop not in DMA:
            continue
        n = nodes[node_of_pc[oi]]
        sp, se = prog[oi] >= SC.DMA_QDEPTH, burst >= SC.DMA_QDEPTH
        sm = wm >= SC.SDMA_STALL // 2
        npm += sp
        nem += se
        nmeas += sm
        if sp != se or sm != sp or wm != n.dur:
            print(f"    new pc {blo + j} (old {oi}) {n.label}: program-order "
                  f"burst {prog[oi]} (stall {sp}), emitted burst {burst} "
                  f"(stall {se}); model window {n.dur}, measured {wm}")
    print(f"  stalls: program-order rule {npm}, emitted-order rule {nem}, "
          f"measured (window >= {SC.SDMA_STALL // 2}) {nmeas}")
    # rule candidates on MEASURED timing: which DMA enqueues stall?
    #   strict: the 6th DMA CMD with only its ARG CSRWRs between it and
    #           the previous DMA CMD (any other record resets the run);
    #   queue(X): one transfer in flight, each X cycles; an enqueue stalls
    #           when QDEPTH-1 = 5 transfers are still outstanding at its
    #           start (completion_i = max(enqueue end_i, completion_i-1) + X)
    def dma_seq(seq):
        """seq: [(rec, cyc0, ncyc)] in issue order -> [(start, end,
        strict burst, measured stall)] per DMA CMD."""
        out, burst, gap_ok = [], 0, True
        for (r, c0, w) in seq:
            if r.opcode == SF.OP_CSRWR and r.target in RE.ARG_CSRS:
                continue
            if r.opcode == SF.OP_CMD and (r.imm32 & 0xFF) in DMA:
                burst = burst + 1 if gap_ok else 1
                out.append((c0, c0 + w, burst, w >= SC.SDMA_STALL // 2))
                gap_ok = True
            else:
                burst = 0
                gap_ok = False
        return out

    def queue_pred(dm, X):
        comp, pred = [], []
        for (c0, c1, _b, _m) in dm:
            outst = [c for c in comp if c > c0]
            pred.append(len(outst) >= SC.DMA_QDEPTH - 1)
            comp.append(max(c1, comp[-1] if comp else 0) + X)
        return pred
    bnrecs = [(recs[pc], bn[4][pc][1], bn[4][pc][2])
              for pc in range(lo, hi + 1)]
    r1seq = [(r, R[blo + j][1], R[blo + j][2])
             for j, (_oi, r) in enumerate(items)]
    for name, seq in (("shipped order, BN1 token 4", bnrecs),
                      ("r1 emitted order, TB token 4", r1seq)):
        dm = dma_seq(seq)
        meas = [m for (_a, _b, _c, m) in dm]
        strict = [b >= SC.DMA_QDEPTH for (_a, _b, b, _m) in dm]
        good = [X for X in range(2000, 60001, 50)
                if queue_pred(dm, X) == meas]
        print(f"  {name}: {len(dm)} DMA CMDs, measured stalls {sum(meas)}; "
              f"strict-consecutive rule {sum(strict)} (match "
              f"{strict == meas}); queue(X) matches every enqueue for X in "
              + (f"[{min(good)}, {max(good)}] ({len(good)} of the 50-cycle "
                 f"grid)" if good else "NONE of 2000..60000"))
        if name.startswith("r1"):
            q = queue_pred(dm, SC.SDMA_STALL + 4 * SC.SDMA)
            print(f"    queue(X = SDMA_STALL + 4*SDMA = "
                  f"{SC.SDMA_STALL + 4 * SC.SDMA}) predicts {sum(q)} stalls, "
                  f"match {q == meas}")
    print("SR11B_MODEL_CORRECTION DIAG: DONE")


def cmd_residual_placed(S, items, blo, R):
    """{CMD node index: measured - model window} on token R (ARGs merged on
    both sides): the inherited CMD residual PLACED on the commands it was
    measured on (n1158: one DMA-queue stall on an SLD, +17,212, and the
    KVAPs), for reorder_e4.predict's cmd_extra."""
    nodes = S["nodes"]
    node_of_pc = {n.pc: i for i, n in enumerate(nodes)}
    argset = {nodes[a].pc for al in RE.arg_owner(nodes).values() for a in al}
    out, pend = {}, 0
    for j, (oi, r) in enumerate(items):
        w = R[blo + j][2]
        if oi in argset:
            pend += w
        elif r.opcode == SF.OP_CMD:
            i = node_of_pc[oi]
            d = w + pend - nodes[i].dur
            pend = 0
            if d:
                out[i] = d
    return out


def attribution(S, order, fences, keys, R4, cmd_extra):
    pmk, info = RE.predict(S, order, cmd_extra=cmd_extra)
    pw = info["fence_windows"]
    assert len(pw) == len(fences)
    zw = [(pw[i], R4[f[0]][2]) for i, f in enumerate(fences) if pw[i] == REC]
    by = collections.defaultdict(lambda: [0, 0, 0, 0])
    for i, (fpc, sel, mw) in enumerate(fences):
        k = keys[sel[-1]] if sel else ("-", "none")
        by[k][0] += 1
        by[k][1] += pw[i]
        by[k][2] += R4[fpc][2]
        by[k][3] += mw
    return {"pred": pmk, "lane": info["lane"],
            "cmd_resid": (info["cmd_resid"] if cmd_extra is None
                          else sum(cmd_extra.values())),
            "zero_wait": (len(zw), sum(a for a, _b in zw),
                          sum(b for _a, b in zw)),
            "fence_pred": sum(pw),
            "fence_meas": sum(R4[f[0]][2] for f in fences),
            "fence_old": sum(f[2] for f in fences),
            "by_class": {k: (v[0], v[1], v[2]) for k, v in by.items()},
            "by_class_old": {k: v[3] for k, v in by.items()}}


def reprediction(verbose=False):
    """The corrected model (ref/seq_cost.py through reorder_e4.predict) on
    the s1 r1 body, against the measured token 4.  Two readings of the
    inherited CMD residual (controller: keep +19,308):
      PLACED   — in lane time on the commands the TB measured it on (the
                 SLD DMA-queue stall and the KVAPs, n1158); the FENCE
                 convention is then judged alone, class by class.  This is
                 the top-level dict.  IN-SAMPLE on the 19,308 part: the
                 placement is token 4's OWN measured CMD windows (R4 below)
                 — a DIAGNOSTIC (the TDD's (f2)), not a prediction.
      ADDITIVE — CMD_RESID_FRAC x the CMD work added to the makespan, the
                 form every r2 prediction uses (no measured placement
                 exists for an r2 order); res["additive"], the TDD's GATE
                 (f1).
    res["before"]: SR4's convention (replay(); a FENCE record costs 0)
    on the same measured token — the negative control of (f1).
    Sign convention everywhere: model − measured."""
    import seq_cost as SC
    S, order, items, blo, jmp, fences, mv_pc, keys, rows = load()
    R4 = rows[HOLD_TOK]
    msum = sum(R4[pc][2] for pc in range(blo, jmp + 1))
    placed = cmd_residual_placed(S, items, blo, R4)
    res = attribution(S, order, fences, keys, R4, placed)
    res["meas"] = msum
    res["placed"] = sorted((S["nodes"][i].label, d)
                           for i, d in placed.items())
    res["additive"] = attribution(S, order, fences, keys, R4, None)
    zb = [(f[2], R4[f[0]][2]) for f in fences if f[2] == 0]
    res["before"] = {"pred": PRED_OLD,
                     "zero_wait": (len(zb), sum(a for a, _b in zb),
                                   sum(b for _a, b in zb))}
    if verbose:
        print(f"\n=== MODEL CORRECTION, s1 token-4 body window (measured "
              f"{msum} = n570:39's {MEAS4}: "
              f"{'MATCH' if msum == MEAS4 else 'DIFFERS'})")
        print(f"  constants: FENCE_REC {SC.FENCE_REC}; TAIL1 {SC.TAIL1}; "
              f"TAIL1_DEFAULT {SC.TAIL1_DEFAULT}; CMD_RESID_FRAC "
              f"{SC.CMD_RESID_FRAC:.9f}")
        agg = collections.Counter()
        for lab, d in res["placed"]:
            agg["DNST" if lab.startswith("DNST") else lab] += d
        print(f"  the inherited CMD residual, measured per command (token 4):"
              f" {len(placed)} commands, total {sum(placed.values()):+d}: "
              + ", ".join(f"{k} {v:+d}" for k, v in agg.most_common()))
        d_old = PRED_OLD - msum
        print(f"  BEFORE (SR4's convention, n570:61): {PRED_OLD} cyc, model -"
              f" measured {d_old:+d} = {100.0 * d_old / msum:+.3f} %")
        n, a, b = res["before"]["zero_wait"]
        print(f"  BEFORE, zero-wait FENCEs: {n} priced {a} vs measured {b} "
              f"({a - b:+d}: the record cost it does not charge)")
        for name, pr in (("AFTER, residual ADDITIVE (the r2 form; THE GATE, "
                          "TDD f1)", res["additive"]),
                         ("AFTER, residual PLACED in lane time (IN-SAMPLE "
                          "DIAGNOSTIC, TDD f2: token 4's own CMD windows)",
                          res)):
            d_new = pr["pred"] - msum
            print(f"  {name}: {pr['pred']} cyc (lane {pr['lane']}, CMD "
                  f"residual {pr['cmd_resid']:+d}), model - measured "
                  f"{d_new:+d} = {100.0 * d_new / msum:+.3f} %  -> "
                  f"{'WITHIN' if abs(d_new) <= 0.005 * msum else 'OUTSIDE'}"
                  f" +-0.5 %")
            print("    FENCE class (cycles): model BEFORE | model AFTER | "
                  "measured | AFTER - measured")
            print(f"      all FENCEs ({len(fences)}) {pr['fence_old']:9d} | "
                  f"{pr['fence_pred']:9d} | {pr['fence_meas']:9d} | "
                  f"{pr['fence_pred'] - pr['fence_meas']:+d}")
            n, a, b = pr["zero_wait"]
            print(f"      zero-wait in the corrected model: {n} FENCEs, {a} "
                  f"vs measured {b} ({a - b:+d})")
            print("      by drained class (n | BEFORE | AFTER | measured | "
                  "BEFORE - meas | AFTER - meas):")
            for k in sorted(pr["by_class"], key=lambda k: -abs(
                    pr["by_class"][k][2] - pr["by_class_old"][k])):
                n, a, b = pr["by_class"][k]
                o = pr["by_class_old"][k]
                print(f"        {k[0]:4s} {k[1]:9s} {n:5d} | {o:9d} | {a:9d}"
                      f" | {b:9d} | {o - b:+8d} | {a - b:+8d}")
        print("  every non-FENCE, non-CMD window is the old model's (BN1's "
              "CSV): LDC/MVGO/EMB -729 (n570:69-71) is left")
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--diag", action="store_true",
                    help="where the residual FENCE error sits (lane gaps, "
                         "CMD groups)")
    a = ap.parse_args()
    print(f"=== sr11b_model_correction.py  FABLE5_MODEL="
          f"{os.environ.get('FABLE5_MODEL')}")
    if a.fit:
        fit()
    if a.diag:
        diag()
    if a.verify:
        r = reprediction(verbose=True)
        ok = all(abs(x["pred"] - r["meas"]) <= 0.005 * r["meas"]
                 for x in (r, r["additive"]))
        print("SR11B_MODEL_CORRECTION VERIFY: " + ("PASS" if ok else "FAIL"))
        raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
