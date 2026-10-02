#!/usr/bin/env python3
"""sr_derive.py — Task SR5b: every derived number SR5b_R1_CHIP.md quotes.

A copy of evidence/qwen9b/ov/sv1_derive.py, retargeted from SV1's S1 (form B,
global FENCE) to R1 (form B, one masked FENCE per MVGO, SEQ_ISA v2.3 B17.1)
on the SR5a binary.  Reads committed logs only (SR4's reorder logs, SR5b's
chip-TB wrapper logs, the census timeline log) plus — for the per-class
attribution — the gitignored timeline CSV of the s1 R1 run, sha256-checked
against the committed evidence/qwen9b/sr/sr5b_timeline_model_9b_s1_reordB_r1.csv.sha256.
Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh:

    FABLE5_MODEL=9b python evidence/qwen9b/sr/sr_derive.py --predict
    FABLE5_MODEL=9b python evidence/qwen9b/sr/sr_derive.py

--predict (n550, committed BEFORE any chip run lands): the prediction and
the bands every stream is judged by (plan Task SR5b step 1):
  * s1 — the token-4 body window (n120's quantity, `SEQ_TIMELINE tcyc 4` of
    the timeline run) against 27,136,513 cyc (n120:17 = SR4's replay,
    n410:49): HELD within +-0.5 %, HELD LOOSELY (attribute by class) within
    +-2 %, outside +-2 % a STOP;
  * s2..s4 — the whole run: R1 / S1-B must be < 1 and within +-0.5 % of s1's
    own whole-run R1 / S1-B; R1 / shipped likewise within +-0.5 % of s1's.
    Outside +-0.5 % is attributed; outside +-2 % is a STOP.
  * informational (no band): SV1's whole-run prediction method applied to
    the r1 segments (sum of the replayed segments + LOOP x the body + the
    launch cycles no window holds).

Default (n570): the measured cycles, ms/token, x shipped, x S1-B, the band
verdict for every stream and, from the s1 timeline CSV, the attribution by
class: the model's per-record windows (OV1's replay of the EMITTED r1 body,
recomputed here by the pass's own functions and required to reproduce
27,136,513) against the measured per-record windows, record by record (the
emitted body IS the r1 stream's body, checked record by record), summed by
opcode class (FENCE / CMD incl. its ARG CSRWRs / MOVX / MVGO / MOVY /
other), and the FENCE class split into zero-wait FENCEs (the per-record
cost the model does not charge) and waiting FENCEs (the poll-tail error),
and by the matvec class of the stream each FENCE drains.
"""
import argparse
import collections
import hashlib
import os
import re
import sys

SR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(SR, "..", "..", ".."))
OV = os.path.join(REPO, "evidence", "qwen9b", "ov")
HZ = 250_000_000.0
NTOK = 6
# T: evidence/qwen9b/s4/S4_REPLAY.md:398-401 (SV1_S1_VERIFY.md §3)
TODAY = {1: 196706821, 2: 196707670, 3: 196707670, 4: 196706833}
# T: SV1_S1_VERIFY.md §3 table (n53-n56); s1 reproduced on the R1 binary by
# SR5a (evidence/qwen9b/sr/n514_chip_s1_reordB_control.log:31)
S1B = {1: 171731320, 2: 171731695, 3: 171731695, 4: 171731425}
TB_MS, BOARD_MS = 131.138, 137.121          # BN_CENSUS / RD9 (S), as SV1
SCALE = BOARD_MS / TB_MS
PRED_BODY = 27136513        # n120:17 (B:R1) = n410:49 (SR4's replay)
HELD, LOOSE = 0.005, 0.02
REORD_LOG = {1: "n410_reorder_s1_B_r1.log", 2: "n411_reorder_s2_B_r1.log",
             3: "n412_reorder_s3_B_r1.log", 4: "n413_reorder_s4_B_r1.log"}
CHIP_LOG = {1: "n560", 2: "n561", 3: "n562", 4: "n563"}
TL_LOG = "n564"
LOOP = {1: 3, 2: 5, 3: 5, 4: 3}      # body iterations (manifest loop_steps)
CSV = os.path.join(REPO, "tb", "scripts", "w9",
                   "model_9b_s1_reordB_r1.timeline.csv")
CSV_SHA = os.path.join(SR, "sr5b_timeline_model_9b_s1_reordB_r1.csv.sha256")
R1_STREAM = os.path.join(REPO, "tb", "scripts", "w9",
                         "model_9b_s1_reordB_r1.e4.seq")
R1_SHA_S1 = ("4e11a2ae6872970ecb61e2bb37524b7b"
             "d863815e47df1fb9c3af2fbb3218cb28")   # n410:51


def ms(c):
    return c / HZ * 1e3


def rd(name, d=SR):
    return open(os.path.join(d, name)).read()


def find(prefix, d=SR):
    m = [f for f in sorted(os.listdir(d)) if f.startswith(prefix + "_")
         and f.endswith(".log")]
    return m[0] if m else None


def segs(s):
    """[(orig window, emitted-order replay)] per segment, in order."""
    t = rd(REORD_LOG[s])
    orig = [int(x) for x in re.findall(r"program order, measured: (\d+) cyc", t)]
    rep = [int(x) for x in re.findall(r"replay of the EMITTED order: (\d+) cyc", t)]
    assert len(orig) == len(rep) and orig
    return list(zip(orig, rep))


def chip(prefix):
    f = find(prefix)
    if f is None:
        return None
    t = rd(f)
    m = re.search(r"CYCLES measured\s+(\d+)", t)
    return {"log": f, "cyc": int(m.group(1)) if m else None,
            "tok": "TOKENS IDENTICAL TO THE SHIPPED RECORD" in t,
            "pass": re.search(r"SR_CHIP \S+ \S+: PASS", t) is not None,
            "wall": (re.search(r"=== wall\s+(\d+)s", t) or [0, "0"])[1],
            "text": t}


def band(x):
    """|x| as a fraction -> the verdict word."""
    if abs(x) <= HELD:
        return "HELD (within +-0.5 %)"
    if abs(x) <= LOOSE:
        return "HELD LOOSELY (within +-2 %; ATTRIBUTE BY CLASS)"
    return "OUTSIDE +-2 % — STOP"


def predictions():
    lo_h, hi_h = PRED_BODY * (1 - HELD), PRED_BODY * (1 + HELD)
    lo_l, hi_l = PRED_BODY * (1 - LOOSE), PRED_BODY * (1 + LOOSE)
    print("=== PREDICTIONS AND BANDS (written before any SR5b chip run)")
    print(f"  s1 token-4 body window prediction {PRED_BODY} cyc = "
          f"{ms(PRED_BODY):.3f} ms (n120:17 B:R1; SR4 replay n410:49)")
    print(f"  model board tok/s at that window: 1000 / ({ms(PRED_BODY):.3f} "
          f"x {SCALE:.5f}) = {1000.0 / (ms(PRED_BODY) * SCALE):.3f} "
          f"(n120's GRID B:R1 r=0 uni 8.811)")
    print(f"  BAND held  +-0.5 %: {lo_h:.1f} .. {hi_h:.1f} cyc "
          f"(+-{PRED_BODY * HELD:.1f})")
    print(f"  BAND loose +-2 %  : {lo_l:.1f} .. {hi_l:.1f} cyc "
          f"(+-{PRED_BODY * LOOSE:.1f}); outside = STOP before any build")
    print("  s2..s4: whole-run R1/S1-B < 1 and within +-0.5 % of s1's "
          "R1/S1-B; R1/shipped within +-0.5 % of s1's R1/shipped; outside "
          "+-0.5 % attribute, outside +-2 % STOP")
    print("  S1-B whole-run references (T, SV1 §3): " + ", ".join(
        f"s{s} {S1B[s]}" for s in S1B))
    print("  shipped whole-run references (T, S4_REPLAY:398-401): " + ", ".join(
        f"s{s} {TODAY[s]}" for s in TODAY))
    print("  informational whole-run model (SV1's method on the r1 "
          "segments; NO band):")
    pred = {}
    for s in (1, 2, 3, 4):
        sg = segs(s)
        orig = sum(o for o, _ in sg[:-1]) + LOOP[s] * sg[-1][0]
        new = sum(r for _, r in sg[:-1]) + LOOP[s] * sg[-1][1]
        over = TODAY[s] - orig
        p = new + over
        pred[s] = p
        print(f"    s{s}: segments {sg}; body x{LOOP[s]}; token windows "
              f"{orig}, outside {over}; PREDICTED whole run {p} cyc = "
              f"{ms(p) / NTOK:.3f} ms/token; x shipped {TODAY[s] / p:.4f}; "
              f"R1/S1-B {p / S1B[s]:.5f}; R1/shipped {p / TODAY[s]:.5f}")
    return pred


def measured(pred):
    print("\n=== MEASURED (the chip-TB runs on the SR5a binary)")
    res = {}
    for s in (1, 2, 3, 4):
        c = chip(CHIP_LOG[s])
        if c is None or c["cyc"] is None:
            print(f"  s{s}: chip run: NOT YET")
            continue
        m = ms(c["cyc"]) / NTOK
        res[s] = c
        print(f"  s{s}: MEASURED {c['cyc']} cyc = {m:.3f} ms/token; x shipped "
              f"{TODAY[s] / c['cyc']:.4f}; x S1-B {S1B[s] / c['cyc']:.4f}; "
              f"R1/S1-B {c['cyc'] / S1B[s]:.5f}; R1/shipped "
              f"{c['cyc'] / TODAY[s]:.5f}; vs the informational whole-run "
              f"model {c['cyc'] - pred[s]:+d} cyc = "
              f"{100.0 * (c['cyc'] - pred[s]) / pred[s]:+.3f} %; tokens "
              f"{'IDENTICAL' if c['tok'] else 'DIFFER'}; runner "
              f"{'PASS' if c['pass'] else 'FAIL'}; wall {c['wall']} s; {c['log']}")
        print(f"  s{s}: board-scaled (uniform assumption, MODEL) "
              f"{m * SCALE:.3f} ms/token = {1000.0 / (m * SCALE):.3f} tok/s "
              f"(shipped {1000.0 / (ms(TODAY[s]) / NTOK * SCALE):.3f}, S1-B "
              f"{1000.0 / (ms(S1B[s]) / NTOK * SCALE):.3f})")
    verdicts = {}
    # --- s1: the token-4 body window (timeline run)
    tl = find(TL_LOG)
    tcyc = {}
    if tl:
        t = rd(tl)
        tcyc = {int(a): int(b) for a, b in
                re.findall(r"^SEQ_TIMELINE tcyc (\d+) (\d+)", t, re.M)}
        mt = re.search(r"CYCLES measured\s+(\d+)", t)
        tlc = int(mt.group(1)) if mt else None
        print(f"\n=== s1 timeline run {tl}: whole run {tlc} cyc"
              + (f"; = the control ({res[1]['cyc']}): "
                 f"{'YES' if tlc == res[1]['cyc'] else 'NO'}"
                 if 1 in res else "")
              + f"; tokens {'IDENTICAL' if 'TOKENS IDENTICAL TO THE SHIPPED RECORD' in t else 'DIFFER'}"
              + f"; runner {'PASS' if re.search(r'SR_CHIP \S+ \S+: PASS', t) else 'FAIL'}")
        base = rd("003_timeline_model_9b_s1.log",
                  os.path.join(REPO, "evidence", "qwen9b", "bn"))
        sv1 = rd("n57_chip_s1_reordB_timeline.log", OV)
        ta = {int(a): int(b) for a, b in
              re.findall(r"^SEQ_TIMELINE tcyc (\d+) (\d+)", base, re.M)}
        tb = {int(a): int(b) for a, b in
              re.findall(r"^SEQ_TIMELINE tcyc (\d+) (\d+)", sv1, re.M)}
        print("  per token (cycles): shipped (BN1 003) / S1-B (SV1 n57) / R1")
        for k in sorted(tcyc):
            if k in ta and k in tb:
                print(f"    token {k}: {ta[k]} / {tb[k]} / {tcyc[k]} = "
                      f"{ms(tcyc[k]):.3f} ms; x shipped {ta[k] / tcyc[k]:.4f}"
                      f"; x S1-B {tb[k] / tcyc[k]:.4f}")
    if 4 in tcyc:
        d = (tcyc[4] - PRED_BODY) / PRED_BODY
        verdicts[1] = band(d)
        print(f"  s1 TOKEN-4 BODY WINDOW {tcyc[4]} cyc = {ms(tcyc[4]):.3f} ms "
              f"vs prediction {PRED_BODY}: {tcyc[4] - PRED_BODY:+d} cyc = "
              f"{100.0 * d:+.3f} % -> s1 {verdicts[1]}")
        print(f"  s1 token-4 board-scaled (MODEL) {1000.0 / (ms(tcyc[4]) * SCALE):.3f}"
              f" tok/s vs the model's 8.811")
    else:
        print("  s1 token-4 body window: timeline run NOT YET")
    # --- s2..s4: whole-run ratios against s1's
    if 1 in res:
        r_b1 = res[1]["cyc"] / S1B[1]
        r_t1 = res[1]["cyc"] / TODAY[1]
        print(f"\n=== s2..s4 whole-run ratios against s1's (R1/S1-B {r_b1:.6f}"
              f", R1/shipped {r_t1:.6f})")
        for s in (2, 3, 4):
            if s not in res:
                print(f"  s{s}: NOT YET")
                continue
            rb = res[s]["cyc"] / S1B[s]
            rt = res[s]["cyc"] / TODAY[s]
            db, dt = rb / r_b1 - 1, rt / r_t1 - 1
            vb, vt = band(db), band(dt)
            below = rb < 1
            worst = max(abs(db), abs(dt))
            v = band(worst) if below else "R1/S1-B NOT < 1 — STOP"
            verdicts[s] = v
            print(f"  s{s}: R1/S1-B {rb:.6f} (< 1: {below}; vs s1 {100 * db:+.4f} %"
                  f" -> {vb}); R1/shipped {rt:.6f} (vs s1 {100 * dt:+.4f} % -> "
                  f"{vt}) -> s{s} {v}")
    print("\n=== BAND VERDICT, every stream")
    for s in (1, 2, 3, 4):
        print(f"  s{s}: {verdicts.get(s, 'NOT YET')}")
    toks = [res[s]["tok"] and res[s]["pass"] for s in res]
    print(f"  tokens IDENTICAL and runner PASS: {sum(toks)}/{len(toks)} "
          f"control runs")
    return tcyc


# ======================================================================
# per-class attribution, token 4, s1 R1 (n564's CSV)
# ======================================================================
def read_csv_tok(path, tok):
    rows = {}
    with open(path) as f:
        for line in f:
            if not line.startswith("R,"):
                continue
            p = line.rstrip("\n").split(",")
            if len(p) != 32 or int(p[2]) != tok:
                continue
            rows[int(p[3])] = (int(p[4]), int(p[8]), int(p[9]))
    return rows


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for ch in iter(lambda: f.read(1 << 24), b""):
            h.update(ch)
    return h.hexdigest()


def class_compare(tcyc):
    sys.path.insert(0, os.path.join(REPO, "ref", "scripts"))
    sys.path.insert(0, os.path.join(REPO, "ref"))
    import reorder_e4 as RE
    OC = RE.OC
    SF = RE.SF
    want = open(CSV_SHA).read().split()[0]
    got = sha_file(CSV)
    print(f"\n=== per-class attribution, token 4, s1 R1; CSV sha256 {got[:16]} "
          f"{'MATCH' if got == want else 'MISMATCH'} (committed {want[:16]})")
    assert got == want
    # the MODEL: the pass's own schedule of the s1 INPUT body at r1 with
    # BN1's CSV windows — the replay SR4 printed (n410:49)
    src = os.path.join(REPO, "tb", "scripts", "w9", "model_9b_s1.e4")
    recs = SF.unpack_stream(open(src + ".seq", "rb").read())
    _pro, sg, _h = RE.segments(recs)
    kb = [k for k, x in enumerate(sg) if x[2]]
    assert len(kb) == 1
    k = kb[0]
    lo, hi, _b = sg[k]
    rows = RE.Windows().rows_for(recs)(k, lo, hi)
    S = RE.schedule_segment(recs, lo, hi, rows, "B", "r1")
    order = RE.order_and_fences(S, "r1")
    rmk, _post, _st = RE.replay(S, order)
    print(f"  model: body {lo}..{hi}; replay of the emitted r1 order {rmk} cyc"
          f" (prediction {PRED_BODY}: {'REPRODUCED' if rmk == PRED_BODY else 'DIFFERS'})")
    assert rmk == PRED_BODY
    nodes = S["nodes"]
    groups = S["groups"]
    mvs, _lt = OC.segment_matvecs(nodes, groups)
    tau = [groups[n.grp]["tau"] if n.kind == "mvgo" else 0 for n in nodes]
    # walk the order exactly as RE.replay does, recording each FENCE's wait
    # and the MVGO(s) it drains
    t = 0
    pend = []
    send = {}
    fence_info = []            # per emitted FENCE: (wait, [drained nodes], mask)
    for x in order:
        if RE.is_fence(x):
            fm = RE.fence_mask(x)
            sel = [m for m in pend if fm == 0 or (fm >> nodes[m].chan) & 1]
            t0 = t
            if sel:
                t = max(t, max(send[m] + tau[m] for m in sel))
            pend = [m for m in pend if m not in sel]
            fence_info.append((t - t0, sel, fm))
            continue
        n = nodes[x]
        t += n.dur
        if n.kind == "mvgo":
            send[x] = t + n.S
            pend.append(x)
    tail = max(t, max((send[i] + tau[i] for i in send), default=0)) - t
    print(f"  model walk: lane end {t}, tail after the last record {tail}, "
          f"makespan {t + tail} ({'= replay' if t + tail == rmk else 'MISMATCH'})")
    assert t + tail == rmk
    # the emitted body, record by record, against the r1 stream on disk
    items = RE.emit_segment(recs, S, order)
    assert sha_file(R1_STREAM) == R1_SHA_S1, "r1 s1 stream sha"
    nrecs = SF.unpack_stream(open(R1_STREAM, "rb").read())
    jmp = [i for i, r in enumerate(nrecs) if r.opcode == SF.OP_JMP][0]
    blo = nrecs[jmp].imm32
    assert jmp - blo + 1 == len(items), (jmp - blo + 1, len(items))
    same = 0
    for j, (_oi, r) in enumerate(items):
        q = nrecs[blo + j]
        if r.opcode == SF.OP_JMP:
            same += q.opcode == SF.OP_JMP
        else:
            same += r.to_bytes() == q.to_bytes()
    print(f"  emitted body == the r1 stream's body {blo}..{jmp}: {same}/"
          f"{len(items)} records identical (the JMP by opcode; its target "
          f"is remapped)")
    assert same == len(items)
    # model window per emitted record
    node_of_pc = {n.pc: i for i, n in enumerate(nodes)}
    argset = {nodes[a].pc for al in RE.arg_owner(nodes).values() for a in al}
    mwin, mcls, fk = [], [], 0
    fence_rec = {}             # new pc -> fence_info index
    for j, (oi, r) in enumerate(items):
        if r.opcode == SF.OP_FENCE:
            mwin.append(fence_info[fk][0])
            mcls.append("FENCE")
            fence_rec[blo + j] = fk
            fk += 1
            continue
        n = nodes[node_of_pc[oi]]
        if oi in argset:
            mwin.append(0)                 # merged into its CMD's window
            mcls.append("CMD+ARG")
        else:
            mwin.append(n.dur)
            mcls.append("CMD+ARG" if r.opcode == SF.OP_CMD
                        else OC.OPN.get(r.opcode, str(r.opcode)))
    assert fk == len(fence_info)
    # measured windows, token 4
    n4 = read_csv_tok(CSV, 4)
    miss = [pc for pc in range(blo, jmp + 1) if pc not in n4]
    assert not miss, f"{len(miss)} body pcs missing in token 4"
    meas_cls = collections.Counter()
    mod_cls = collections.Counter()
    cnt_cls = collections.Counter()
    for j in range(len(items)):
        pc = blo + j
        assert n4[pc][0] == items[j][1].opcode
        meas_cls[mcls[j]] += n4[pc][2]
        mod_cls[mcls[j]] += mwin[j]
        cnt_cls[mcls[j]] += 1
    mod_cls["(tail)"] += tail
    msum = sum(n4[pc][2] for pc in range(blo, jmp + 1))
    print(f"  measured token 4: sum of per-record windows {msum} cyc; "
          f"SEQ_TIMELINE tcyc 4 = {tcyc.get(4)}; difference "
          f"{(tcyc.get(4) or 0) - msum:+d} (the launch/record edge the rows "
          f"do not hold)")
    print(f"  model total {sum(mod_cls.values())} (= {PRED_BODY}); measured "
          f"rows {msum}; measured - model {msum - sum(mod_cls.values()):+d} "
          f"cyc")
    print("  BY CLASS (token 4, cycles): records | model | measured | "
          "measured - model | share of the gap")
    gap = msum - sum(mod_cls.values())
    for c in sorted(set(meas_cls) | set(mod_cls),
                    key=lambda c: -abs(meas_cls[c] - mod_cls[c])):
        dd = meas_cls[c] - mod_cls[c]
        print(f"    {c:8s} {cnt_cls[c]:6d} | {mod_cls[c]:9d} | "
              f"{meas_cls[c]:9d} | {dd:+8d} = {ms(dd):+.4f} ms = "
              f"{100.0 * dd / PRED_BODY:+.4f} % of the prediction | "
              + (f"{100.0 * dd / gap:+.1f} %" if gap else "-"))
    # the FENCE class, split
    zw = [pc for pc, i in fence_rec.items() if fence_info[i][0] == 0]
    ww = [pc for pc, i in fence_rec.items() if fence_info[i][0] > 0]
    zm = [n4[pc][2] for pc in zw]
    print(f"  FENCE records in the body: {len(fence_rec)} (x 4 tokens = "
          f"{4 * len(fence_rec)} + the unrolled segments; the stream carries "
          f"5480 by the pass's hazard line in n410); masks single-channel: "
          f"{all(bin(fence_info[i][2]).count('1') == 1 for i in fence_rec.values())}")
    if zm:
        hist = collections.Counter(zm)
        print(f"    zero-wait in the model: {len(zw)} FENCEs; measured "
              f"window sum {sum(zm)} = mean {sum(zm) / len(zm):.2f} cyc/record "
              f"(min {min(zm)}, max {max(zm)}); most common "
              f"{hist.most_common(5)}  <- the per-record cost the model does "
              f"not charge")
    wm = sum(n4[pc][2] for pc in ww)
    wmod = sum(fence_info[fence_rec[pc]][0] for pc in ww)
    print(f"    waiting in the model: {len(ww)} FENCEs; model wait {wmod}, "
          f"measured {wm}, measured - model {wm - wmod:+d} cyc "
          f"(= {(wm - wmod) / max(len(ww), 1):+.2f} cyc/FENCE)  <- the "
          f"single-channel poll-tail error (+ that FENCE's own record cost)")
    # by the matvec class of the stream each FENCE drains
    bym = collections.defaultdict(lambda: [0, 0, 0])
    for pc, i in fence_rec.items():
        sel = fence_info[i][1]
        if sel:
            mv = mvs[nodes[sel[-1]].mv]
            key = (mv["lt"], mv["cls"])
        else:
            key = ("-", "none")
        bym[key][0] += 1
        bym[key][1] += fence_info[i][0]
        bym[key][2] += n4[pc][2]
    print("    FENCE windows by the class of the stream drained "
          "(n, model, measured, measured - model; ms):")
    for key in sorted(bym, key=lambda k: -abs(bym[k][2] - bym[k][1])):
        n_, a, b = bym[key]
        print(f"      {key[0]:4s} {key[1]:9s} {n_:5d} {ms(a):8.3f} {ms(b):8.3f} "
              f"{ms(b - a):+8.4f}")
    # the CMD class: lane work per opcode, R1 measured vs S1-B measured (SV1)
    sv1_csv = os.path.join(REPO, "tb", "scripts", "w9",
                           "model_9b_s1_reordB.timeline.csv")
    sv1_want = open(os.path.join(OV, "sv1_timeline_model_9b_s1_reordB.csv.sha256")
                    ).read().split()[0]
    if os.path.exists(sv1_csv) and sha_file(sv1_csv) == sv1_want:
        s4 = read_csv_tok(sv1_csv, 4)
        srecs = SF.unpack_stream(open(os.path.join(
            REPO, "tb", "scripts", "w9", "model_9b_s1_reordB.e4.seq"),
            "rb").read())
        sj = [i for i, r in enumerate(srecs) if r.opcode == SF.OP_JMP][0]
        sb = srecs[sj].imm32
        a_op, b_op = collections.Counter(), collections.Counter()
        for pc in range(sb, sj + 1):
            a_op[OC.OPN.get(s4[pc][0])] += s4[pc][2]
        for pc in range(blo, jmp + 1):
            b_op[OC.OPN.get(n4[pc][0])] += n4[pc][2]
        print("  lane work by opcode, token 4 (ms): S1-B measured (SV1 CSV, "
              "sha MATCH) -> R1 measured (delta)")
        for o in sorted(set(a_op) | set(b_op)):
            print(f"    {o:6s} {ms(a_op[o]):9.3f} -> {ms(b_op[o]):9.3f} "
                  f"({ms(b_op[o] - a_op[o]):+.4f})")
    else:
        print("  (SV1's S1-B CSV absent or sha mismatch: no S1-B per-opcode "
              "comparison)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--predict", action="store_true",
                    help="print the predictions and bands only")
    a = ap.parse_args()
    pred = predictions()
    if a.predict:
        print("SR_DERIVE: PREDICTIONS WRITTEN")
        return
    tcyc = measured(pred)
    if os.path.exists(CSV_SHA) and 4 in tcyc:
        class_compare(tcyc)
    print("SR_DERIVE: DONE")


if __name__ == "__main__":
    main()
