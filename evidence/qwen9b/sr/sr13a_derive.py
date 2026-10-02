#!/usr/bin/env python3
"""sr13a_derive.py — Task SR13a: every derived number of Step 1 and Step 4.

A copy of evidence/qwen9b/sr/sr_derive.py (SR5b), retargeted from R1 to
R1+R2 (the r2 form-B streams of SR11b, SEQ_ISA v2.3 B17.2) on SR13a's
binary.  Reads committed logs only (SR11b's reorder logs n1165-n1168, SR5b's
and SR13a's chip-TB wrapper logs, the census timeline logs) plus, for the
per-class attribution, the gitignored timeline CSV of the s1 r2 run,
sha256-checked against the committed
evidence/qwen9b/sr/sr13a_timeline_model_9b_s1_reordB_r2.csv.sha256.
Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh:

    FABLE5_MODEL=9b python evidence/qwen9b/sr/sr13a_derive.py --predict
    FABLE5_MODEL=9b python evidence/qwen9b/sr/sr13a_derive.py

--predict (committed BEFORE any r2 chip run lands):
  * s1 — the token-4 body window (`SEQ_TIMELINE tcyc 4` of the timeline
    run) against SR11b's CORRECTED prediction 26,183,590 cyc (the ADDITIVE
    form, reorder_e4.predict(): lane 26,164,282 + the inherited CMD residual
    19,308; n1165:56, n1182), with its placement band 26,166,378-26,183,590
    (the one 17,212-cyc DMA stall absorbed by a FENCE wait or not; n1182).
    HELD within +-0.5 %; HELD LOOSELY (attribute by class, SR5b §7) within
    +-2 %; outside +-2 % a STOP.  The plan's 26,146,927 (n120:18, the census
    R1+R2 body replay = n1165:50) is printed beside it as the UNCORRECTED
    reference; it is not the band's centre.
  * s2..s4 — the whole run: r2 / R1 (SR5b's measured r1 cycles, same seed)
    must be < 1 and within +-0.5 % of s1's r2 / R1; r2 / shipped likewise.
  * informational (no band): SV1's whole-run method on the r2 segments'
    corrected predictions.

Default: measured cycles, ms/token, x shipped, x R1, the band verdicts,
board-scaled MODEL tok/s (OV1's uniform factor), and from the s1 CSV the
attribution by class: the model's per-record windows (reorder_e4.predict()
on the pass's own r2 schedule of the s1 body, required to reproduce
26,183,590, with the emitted body checked record by record against the r2
stream on disk) against the measured windows of token 4.

R3-9b addition, `--rtl r3` (plan Task R3-9b "Files"; flags, not copies,
I-5; the default `--rtl r2` runs the code above unchanged, so n1349g
reproduces).  The r3 form-B streams (R3-5) on R3-9a's binary (K=r3b):

    FABLE5_MODEL=9b FABLE5_RS_F=7 python evidence/qwen9b/sr/sr13a_derive.py \
        --rtl r3 [--pred-log n2900_r3_predictions.log] \
        [--base-window-log n1349e_sr13a_chip_s1_r2_timeline.log] \
        [--base-logs n1349a,n1349b,n1349c,n1349d] \
        [--chip-logs n3160,n3161,n3162,n3163] [--tl-log n3164]

  * the prediction and bands are READ from the committed prediction log
    (R3-7's n2900: P-A primary, P-B, P-C with its placement band, the s2..s4
    whole runs), never re-typed; the previous rung (the base) is r2 MEASURED:
    the s1 token-4 window (SEQ_TIMELINE tcyc 4 of --base-window-log) and the
    per-seed whole runs (CYCLES measured of --base-logs);
  * the class attribution rebuilds the pass's own schedule at r2 AND at r3,
    each required to reproduce its committed replay_mk / pred_mk (R3-5's
    n2720:49 / :59 for r3), each emitted body checked record by record
    against the stream on disk (FULL sha first), and measures both timeline
    CSVs (each sha256-checked against its committed .sha256): r3 measured
    against r3 model AND against R3-7's EXPECTED (= r2 measured + the
    model's r2->r3 delta, per class), the FENCE windows by the class drained
    (dn_out apart), the per-opcode lane work r2 -> r3, and the L_DMA busy
    cycles (where a DMA stall moves);
  * the ONE-WINDOW measurement: every r3 body MOVX (all broadcasts) against
    the r2 unicast MOVX of the same length, and R3-9a's fixed +19 cyc
    (n3145) applied to the 129 broadcasts.
"""
import argparse
import collections
import hashlib
import os
import re
import sys

SR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(SR, "..", "..", ".."))
HZ = 250_000_000.0
NTOK = 6
# T: evidence/qwen9b/s4/S4_REPLAY.md:398-401 (SV1_S1_VERIFY.md:146-148)
TODAY = {1: 196706821, 2: 196707670, 3: 196707670, 4: 196706833}
# T: SR5b's measured r1 cycles (n560:30 .. n563:30), = SR13a's rung 1
R1 = {1: 162967117, 2: 162965710, 3: 162965710, 4: 162967195}
R1_TOK4 = 27163998                         # T: n570:39, R1's token-4 window
SHIP_TOK4 = 32786868                       # T: n120:12 shipped body window
TB_MS, BOARD_MS = 131.138, 137.121          # OV1 uniform factor, as SR5b
SCALE = BOARD_MS / TB_MS
PRED_BODY = 26183590       # n1165:56 = n1182 (lane 26164282 + resid 19308)
PRED_LO = 26166378         # n1182: the 17,212-cyc stall absorbed
CENSUS_BODY = 26146927     # n120:18 = n1165:50 (uncorrected body replay)
HELD, LOOSE = 0.005, 0.02
REORD_LOG = {1: "n1165_reorder_s1_B_r2.log", 2: "n1166_reorder_s2_B_r2.log",
             3: "n1167_reorder_s3_B_r2.log", 4: "n1168_reorder_s4_B_r2.log"}
CHIP_LOG = {1: "n1349a", 2: "n1349b", 3: "n1349c", 4: "n1349d"}
TL_LOG = "n1349e"
LOOP = {1: 3, 2: 5, 3: 5, 4: 3}      # manifest loop_steps
CSV = os.path.join(REPO, "tb", "scripts", "w9",
                   "model_9b_s1_reordB_r2.timeline.csv")
CSV_SHA = os.path.join(SR, "sr13a_timeline_model_9b_s1_reordB_r2.csv.sha256")
R2_STREAM = os.path.join(REPO, "tb", "scripts", "w9",
                         "model_9b_s1_reordB_r2.e4.seq")
R2_SHA_S1 = ("117ed8b061d5662517d67f905ff1b590"
             "0520ba39eff680548e8af9a7efc17d19")   # n1165:58


def ms(c):
    return c / HZ * 1e3


def tps(c_per_tok):
    return 1000.0 / (ms(c_per_tok) * SCALE)


def rd(name, d=SR):
    return open(os.path.join(d, name)).read()


def find(prefix, d=SR):
    m = [f for f in sorted(os.listdir(d)) if f.startswith(prefix + "_")
         and f.endswith(".log")]
    return m[0] if m else None


def segs(s):
    """[(orig program-order window, corrected prediction)] per segment."""
    t = rd(REORD_LOG[s])
    orig = [int(x) for x in re.findall(r"program order, measured: (\d+) cyc", t)]
    m = re.search(r"CORRECTED prediction .* per segment: ([^;]+);", t)
    pred = [int(x) for x in re.findall(r"seg\d+ (\d+)", m.group(1))]
    assert len(orig) == len(pred) and orig
    return list(zip(orig, pred))


def chip(prefix):
    f = find(prefix)
    if f is None:
        return None
    t = rd(f)
    m = re.search(r"CYCLES measured\s+(\d+)", t)
    return {"log": f, "cyc": int(m.group(1)) if m else None,
            "tok": "TOKENS IDENTICAL TO THE SHIPPED RECORD" in t,
            "pass": re.search(r"SR_CHIP \S+ \S+: PASS", t) is not None,
            "wall": (re.search(r"=== wall\s+(\d+)s", t) or [0, "0"])[1]}


def band(x):
    if abs(x) <= HELD:
        return "HELD (within +-0.5 %)"
    if abs(x) <= LOOSE:
        return "HELD LOOSELY (within +-2 %; ATTRIBUTE BY CLASS, SR5b §7)"
    return "OUTSIDE +-2 % — STOP"


def predictions():
    print("=== PREDICTIONS AND BANDS (written before any r2 chip run)")
    print(f"  s1 token-4 body window prediction {PRED_BODY} cyc = "
          f"{ms(PRED_BODY):.3f} ms (SR11b corrected, ADDITIVE form; "
          f"n1165:56, n1182)")
    print(f"  placement band (the 17,212-cyc DMA stall absorbed or not): "
          f"{PRED_LO} .. {PRED_BODY}")
    print(f"  uncorrected reference beside it: {CENSUS_BODY} cyc = "
          f"{ms(CENSUS_BODY):.3f} ms (n120:18 census R1+R2 = n1165:50); "
          f"corrected - census {PRED_BODY - CENSUS_BODY:+d}")
    print(f"  model: x shipped (body) {SHIP_TOK4 / PRED_BODY:.4f}; x R1 "
          f"measured window {R1_TOK4 / PRED_BODY:.4f}; board tok/s (MODEL) "
          f"{tps(PRED_BODY):.3f} (band to {tps(PRED_LO):.3f})")
    for nm, f in (("held  +-0.5 %", HELD), ("loose +-2 %  ", LOOSE)):
        print(f"  BAND {nm}: {PRED_BODY * (1 - f):.1f} .. "
              f"{PRED_BODY * (1 + f):.1f} cyc (+-{PRED_BODY * f:.1f})")
    print("  outside +-2 % = STOP; outside +-0.5 % inside +-2 % = attribute "
          "by class (SR5b §7) before calling it a miss")
    print("  s2..s4: whole-run r2/R1 < 1 and within +-0.5 % of s1's r2/R1; "
          "r2/shipped within +-0.5 % of s1's; outside +-0.5 % attribute, "
          "outside +-2 % STOP")
    print("  R1 whole-run references (T, SR5b n560-n563 = SR13a n1314-n1317): "
          + ", ".join(f"s{s} {R1[s]}" for s in R1))
    print("  shipped whole-run references (T, S4_REPLAY:398-401): "
          + ", ".join(f"s{s} {TODAY[s]}" for s in TODAY))
    print("  informational whole-run model (SV1's method on the r2 segments' "
          "corrected predictions; NO band):")
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
              f"r2/R1 {p / R1[s]:.5f}; r2/shipped {p / TODAY[s]:.5f}")
    return pred


def measured(pred):
    print("\n=== MEASURED (the chip-TB runs on SR13a's binary)")
    res = {}
    for s in (1, 2, 3, 4):
        c = chip(CHIP_LOG[s])
        if c is None or c["cyc"] is None:
            print(f"  s{s}: chip run: NOT YET")
            continue
        m = c["cyc"] / NTOK
        res[s] = c
        print(f"  s{s}: MEASURED {c['cyc']} cyc = {ms(m):.3f} ms/token; x "
              f"shipped {TODAY[s] / c['cyc']:.4f}; x R1 {R1[s] / c['cyc']:.4f};"
              f" r2/R1 {c['cyc'] / R1[s]:.6f}; r2/shipped "
              f"{c['cyc'] / TODAY[s]:.6f}; vs the informational whole-run "
              f"model {c['cyc'] - pred[s]:+d} cyc = "
              f"{100.0 * (c['cyc'] - pred[s]) / pred[s]:+.3f} %; tokens "
              f"{'IDENTICAL' if c['tok'] else 'DIFFER'}; runner "
              f"{'PASS' if c['pass'] else 'FAIL'}; wall {c['wall']} s; {c['log']}")
        print(f"  s{s}: board-scaled (uniform, MODEL) {ms(m) * SCALE:.3f} "
              f"ms/token = {tps(m):.3f} tok/s (shipped "
              f"{tps(TODAY[s] / NTOK):.3f}, R1 {tps(R1[s] / NTOK):.3f})")
    verdicts = {}
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
                 f"{'YES' if tlc == res[1]['cyc'] else 'NO'}" if 1 in res
                 else "")
              + f"; tokens {'IDENTICAL' if 'TOKENS IDENTICAL TO THE SHIPPED RECORD' in t else 'DIFFER'}")
        base = rd("003_timeline_model_9b_s1.log",
                  os.path.join(REPO, "evidence", "qwen9b", "bn"))
        r1t = rd("n564_sr5b_chip_s1_r1_timeline.log")
        ta = {int(a): int(b) for a, b in
              re.findall(r"^SEQ_TIMELINE tcyc (\d+) (\d+)", base, re.M)}
        tb = {int(a): int(b) for a, b in
              re.findall(r"^SEQ_TIMELINE tcyc (\d+) (\d+)", r1t, re.M)}
        print("  per token (cycles): shipped (BN1 003) / R1 (SR5b n564) / r2")
        for k in sorted(tcyc):
            if k in ta and k in tb:
                print(f"    token {k}: {ta[k]} / {tb[k]} / {tcyc[k]} = "
                      f"{ms(tcyc[k]):.3f} ms; x shipped {ta[k] / tcyc[k]:.4f}"
                      f"; x R1 {tb[k] / tcyc[k]:.4f}")
    if 4 in tcyc:
        d = (tcyc[4] - PRED_BODY) / PRED_BODY
        verdicts[1] = band(d)
        inpl = PRED_LO <= tcyc[4] <= PRED_BODY
        print(f"  s1 TOKEN-4 BODY WINDOW {tcyc[4]} cyc = {ms(tcyc[4]):.3f} ms "
              f"vs prediction {PRED_BODY}: {tcyc[4] - PRED_BODY:+d} cyc = "
              f"{100.0 * d:+.3f} % -> s1 {verdicts[1]}; inside the placement "
              f"band {PRED_LO}..{PRED_BODY}: {inpl}; vs the uncorrected "
              f"{CENSUS_BODY}: {tcyc[4] - CENSUS_BODY:+d} = "
              f"{100.0 * (tcyc[4] - CENSUS_BODY) / CENSUS_BODY:+.3f} %")
        print(f"  s1 token-4: x shipped body {SHIP_TOK4 / tcyc[4]:.4f}; x R1 "
              f"token-4 {R1_TOK4 / tcyc[4]:.4f}; board-scaled (MODEL) "
              f"{tps(tcyc[4]):.3f} tok/s vs the model's {tps(PRED_BODY):.3f}")
    else:
        print("  s1 token-4 body window: timeline run NOT YET")
    if 1 in res:
        r_b1 = res[1]["cyc"] / R1[1]
        r_t1 = res[1]["cyc"] / TODAY[1]
        print(f"\n=== s2..s4 whole-run ratios against s1's (r2/R1 {r_b1:.6f}"
              f", r2/shipped {r_t1:.6f})")
        for s in (2, 3, 4):
            if s not in res:
                print(f"  s{s}: NOT YET")
                continue
            rb = res[s]["cyc"] / R1[s]
            rt = res[s]["cyc"] / TODAY[s]
            db, dt = rb / r_b1 - 1, rt / r_t1 - 1
            below = rb < 1
            v = (band(max(abs(db), abs(dt))) if below
                 else "r2/R1 NOT < 1 — STOP")
            verdicts[s] = v
            print(f"  s{s}: r2/R1 {rb:.6f} (< 1: {below}; vs s1 {100 * db:+.4f}"
                  f" %); r2/shipped {rt:.6f} (vs s1 {100 * dt:+.4f} %) -> "
                  f"s{s} {v}")
    print("\n=== BAND VERDICT, every stream")
    for s in (1, 2, 3, 4):
        print(f"  s{s}: {verdicts.get(s, 'NOT YET')}")
    ok = [res[s]["tok"] and res[s]["pass"] for s in res]
    print(f"  tokens IDENTICAL and runner PASS: {sum(ok)}/{len(ok)} control runs")
    return tcyc


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
    OC, SF = RE.OC, RE.SF
    want = open(CSV_SHA).read().split()[0]
    got = sha_file(CSV)
    print(f"\n=== per-class attribution, token 4, s1 r2; CSV sha256 {got[:16]} "
          f"{'MATCH' if got == want else 'MISMATCH'} (committed {want[:16]})")
    assert got == want
    src = os.path.join(REPO, "tb", "scripts", "w9", "model_9b_s1.e4")
    recs = SF.unpack_stream(open(src + ".seq", "rb").read())
    _pro, sg, _h = RE.segments(recs)
    k = [i for i, x in enumerate(sg) if x[2]]
    assert len(k) == 1
    k = k[0]
    lo, hi, _b = sg[k]
    rows = RE.Windows().rows_for(recs)(k, lo, hi)
    S = RE.schedule_segment(recs, lo, hi, rows, "B", "r2")
    order = RE.order_and_fences(S, "r2")
    rmk, _post, _st = RE.replay(S, order)
    pmk, info = RE.predict(S, order)
    print(f"  model: body {lo}..{hi}; census replay {rmk} (= {CENSUS_BODY}: "
          f"{rmk == CENSUS_BODY}); corrected predict() {pmk} (= {PRED_BODY}: "
          f"{pmk == PRED_BODY}); lane {info['lane']}, residual "
          f"{info['cmd_resid']}")
    assert rmk == CENSUS_BODY and pmk == PRED_BODY
    nodes = S["nodes"]
    fwin = info["fence_windows"]
    # the FENCE drained sets, walked as predict() walks them
    pend, fence_sel = [], []
    for x in order:
        if RE.is_fence(x):
            fm = RE.fence_mask(x)
            sel = [m for m in pend if fm == 0 or (fm >> nodes[m].chan) & 1]
            pend = [m for m in pend if m not in sel]
            fence_sel.append((sel, fm))
            continue
        if nodes[x].kind == "mvgo":
            pend.append(x)
    lane_tail = info["lane"] - (sum(fwin) + sum(
        nodes[x].dur for x in order if not RE.is_fence(x)))
    items = RE.emit_segment(recs, S, order, "r2")
    assert sha_file(R2_STREAM) == R2_SHA_S1, "r2 s1 stream sha"
    nrecs = SF.unpack_stream(open(R2_STREAM, "rb").read())
    jmp = [i for i, r in enumerate(nrecs) if r.opcode == SF.OP_JMP][0]
    blo = nrecs[jmp].imm32
    assert jmp - blo + 1 == len(items), (jmp - blo + 1, len(items))
    same = sum((q.opcode == SF.OP_JMP) if r.opcode == SF.OP_JMP
               else (r.to_bytes() == q.to_bytes())
               for (_oi, r), q in zip(items, nrecs[blo:jmp + 1]))
    print(f"  emitted body == the r2 stream's body {blo}..{jmp}: {same}/"
          f"{len(items)} records identical (the JMP by opcode)")
    assert same == len(items)
    node_of_pc = {n.pc: i for i, n in enumerate(nodes)}
    argset = {nodes[a].pc for al in RE.arg_owner(nodes).values() for a in al}
    mwin, mcls, fk, fence_rec = [], [], 0, {}
    for j, (oi, r) in enumerate(items):
        if r.opcode == SF.OP_FENCE:
            mwin.append(fwin[fk])
            mcls.append("FENCE")
            fence_rec[blo + j] = fk
            fk += 1
            continue
        n = nodes[node_of_pc[oi]]
        if oi in argset:
            mwin.append(0)
            mcls.append("CMD+ARG")
        else:
            mwin.append(n.dur)
            mcls.append("CMD+ARG" if r.opcode == SF.OP_CMD
                        else OC.OPN.get(r.opcode, str(r.opcode)))
    assert fk == len(fwin)
    n4 = read_csv_tok(CSV, 4)
    miss = [pc for pc in range(blo, jmp + 1) if pc not in n4]
    assert not miss, f"{len(miss)} body pcs missing in token 4"
    meas, mod, cnt = (collections.Counter() for _ in range(3))
    for j in range(len(items)):
        pc = blo + j
        assert n4[pc][0] == items[j][1].opcode
        meas[mcls[j]] += n4[pc][2]
        mod[mcls[j]] += mwin[j]
        cnt[mcls[j]] += 1
    mod["(lane tail)"] += lane_tail
    mod["(CMD resid)"] += info["cmd_resid"]
    msum = sum(n4[pc][2] for pc in range(blo, jmp + 1))
    tot = sum(mod.values())
    print(f"  measured token 4: rows {msum}; SEQ_TIMELINE tcyc 4 = "
          f"{tcyc.get(4)} ({(tcyc.get(4) or 0) - msum:+d} = the launch edge)")
    print(f"  model total {tot} (= {PRED_BODY}: {tot == PRED_BODY}); measured "
          f"- model {msum - tot:+d} cyc")
    gap = msum - tot
    print("  BY CLASS (token 4): records | model | measured | measured - "
          "model | share of the gap")
    for c in sorted(set(meas) | set(mod), key=lambda c: -abs(meas[c] - mod[c])):
        dd = meas[c] - mod[c]
        print(f"    {c:12s} {cnt[c]:6d} | {mod[c]:9d} | {meas[c]:9d} | "
              f"{dd:+8d} = {100.0 * dd / PRED_BODY:+.4f} % | "
              + (f"{100.0 * dd / gap:+.1f} %" if gap else "-"))
    rec = SF_FENCE_REC = RE.SC.FENCE_REC
    zw = [pc for pc, i in fence_rec.items() if fwin[i] == rec]
    ww = [pc for pc, i in fence_rec.items() if fwin[i] != rec]
    zm = [n4[pc][2] for pc in zw]
    print(f"  FENCE records in the body: {len(fence_rec)}; single-channel "
          f"masks: {all(bin(fence_sel[i][1]).count('1') == 1 for i in fence_rec.values())}")
    if zm:
        print(f"    zero-wait in the model ({SF_FENCE_REC} cyc): {len(zw)}; "
              f"measured {sum(zm)} (min {min(zm)}, max {max(zm)}); measured - "
              f"model {sum(zm) - rec * len(zm):+d}")
    wm = sum(n4[pc][2] for pc in ww)
    wmod = sum(fwin[fence_rec[pc]] for pc in ww)
    print(f"    waiting in the model: {len(ww)}; model {wmod}, measured {wm}, "
          f"measured - model {wm - wmod:+d} ({(wm - wmod) / max(len(ww), 1):+.2f}"
          f" per FENCE)")
    mvs, _lt = OC.segment_matvecs(nodes, S["groups"])
    bym = collections.defaultdict(lambda: [0, 0, 0])
    for pc, i in fence_rec.items():
        sel = fence_sel[i][0]
        key = ((mvs[nodes[sel[-1]].mv]["lt"], mvs[nodes[sel[-1]].mv]["cls"])
               if sel else ("-", "none"))
        bym[key][0] += 1
        bym[key][1] += fwin[i]
        bym[key][2] += n4[pc][2]
    print("    FENCE windows by the class drained (n, model, measured, "
          "measured - model, cyc):")
    for key in sorted(bym, key=lambda k: -abs(bym[k][2] - bym[k][1])):
        n_, a, b = bym[key]
        print(f"      {key[0]:4s} {key[1]:9s} {n_:5d} {a:9d} {b:9d} {b - a:+8d}")
    # CMD windows by layer opcode: r2 measured vs R1 measured (SR5b CSV)
    r1_csv = os.path.join(REPO, "tb", "scripts", "w9",
                          "model_9b_s1_reordB_r1.timeline.csv")
    r1_want = open(os.path.join(
        SR, "sr5b_timeline_model_9b_s1_reordB_r1.csv.sha256")).read().split()[0]
    if os.path.exists(r1_csv) and sha_file(r1_csv) == r1_want:
        s4 = read_csv_tok(r1_csv, 4)
        rr = SF.unpack_stream(open(os.path.join(
            REPO, "tb", "scripts", "w9", "model_9b_s1_reordB_r1.e4.seq"),
            "rb").read())
        sj = [i for i, r in enumerate(rr) if r.opcode == SF.OP_JMP][0]
        sb = rr[sj].imm32
        a_op, b_op = collections.Counter(), collections.Counter()
        for pc in range(sb, sj + 1):
            a_op[OC.OPN.get(s4[pc][0])] += s4[pc][2]
        for pc in range(blo, jmp + 1):
            b_op[OC.OPN.get(n4[pc][0])] += n4[pc][2]
        print("  lane work by opcode, token 4 (cyc): R1 measured (SR5b CSV, "
              "sha MATCH) -> r2 measured (delta)")
        for o in sorted(set(a_op) | set(b_op), key=str):
            print(f"    {o!s:6s} {a_op[o]:10d} -> {b_op[o]:10d} "
                  f"({b_op[o] - a_op[o]:+d})")
    else:
        print("  (SR5b's R1 CSV absent or sha mismatch: no per-opcode R1 "
              "comparison)")


# ===========================================================================
# R3-9b: --rtl r3 (the r3 form-B streams on R3-9a's binary).  Everything
# below runs only with --rtl r3; the r2 path above is untouched.
# ===========================================================================
R3_REORD = {1: "n2720_r3_5_reorder_s1_B_r3.log", 2: "n2721_r3_5_reorder_s2_B_r3.log",
            3: "n2722_r3_5_reorder_s3_B_r3.log", 4: "n2723_r3_5_reorder_s4_B_r3.log"}
R3_STREAM = os.path.join(REPO, "tb", "scripts", "w9",
                         "model_9b_s1_reordB_r3.e4.seq")
R3_CSV = os.path.join(REPO, "tb", "scripts", "w9",
                      "model_9b_s1_reordB_r3.timeline.csv")
R3_CSV_SHA = os.path.join(SR, "r3_9b_timeline_model_9b_s1_reordB_r3.csv.sha256")
R3_N3145 = "n3145_r3_9a_timeline_readers.log"      # the one-window +19
OPCOL = {"L_DMA": 11, "stall": 30}                  # CSV columns (#COLS)


def _grab(pat, text, what):
    m = re.search(pat, text, re.M)
    if not m:
        raise SystemExit(f"SR13A_DERIVE --rtl r3: cannot read {what} ({pat!r})")
    return m


def r3_inputs(a):
    """Every r3 input READ from a committed log line (no re-typed number)."""
    C = {}
    t = rd(a.pred_log)
    m = _grab(r"^\s+P-A \(PRIMARY.*?\): (\d+) - \((\d+) - (\d+) = (\d+)\) = "
              r"(\d+) cyc", t, "P-A")
    C["base_tok4_pred"], C["r2_pmk"], C["r3_pmk"], C["save"], C["PA"] = (
        int(m.group(i)) for i in range(1, 6))
    m = _grab(r"^\s+P-B \(absolute, census saving\): (\d+) - \((\d+) - (\d+) "
              r"= (\d+)\) = (\d+) cyc", t, "P-B")
    C["r2_rmk"], C["r3_rmk"], C["PB"] = (int(m.group(2)), int(m.group(3)),
                                         int(m.group(5)))
    m = _grab(r"^\s+P-C .*?: (\d+) cyc, placement band (\d+) \.\. (\d+)", t,
              "P-C")
    C["PC"], C["PC_lo"], C["PC_hi"] = (int(m.group(i)) for i in (1, 2, 3))
    C["pred_whole"] = {int(s): int(v) for s, v in re.findall(
        r"^\s+s(\d): per-segment saving .*?PREDICTED r3 whole run \d+ - \d+ = "
        r"(\d+) cyc", t, re.M)}
    assert sorted(C["pred_whole"]) == [1, 2, 3, 4], C["pred_whole"]
    # the r3 replay_mk / pred_mk the pass wrote (R3-5): the model rebuild
    # must reproduce them
    t5 = rd(R3_REORD[1])
    m = _grab(r"^=== r3: replay makespan .*?LOOP BODY (\d+) cyc", t5, "n2720 replay")
    m2 = _grab(r"^=== r3: CORRECTED prediction .*?LOOP BODY (\d+) cyc", t5,
               "n2720 corrected")
    C["r3_rmk_pass"], C["r3_pmk_pass"] = int(m.group(1)), int(m2.group(1))
    assert C["r3_rmk_pass"] == C["r3_rmk"] and C["r3_pmk_pass"] == C["r3_pmk"]
    # the previous rung, MEASURED (r2): token-4 window and whole runs
    tb_ = rd(find(a.base_window_log) or a.base_window_log)
    C["base_tok4"] = int(_grab(r"^SEQ_TIMELINE tcyc 4 (\d+)", tb_,
                               "base tcyc 4").group(1))
    assert C["base_tok4"] == C["base_tok4_pred"], "P-A's base != the r2 window"
    C["base_tl"] = {int(x): int(y) for x, y in re.findall(
        r"^SEQ_TIMELINE tcyc (\d+) (\d+)", tb_, re.M)}
    C["base"] = {}
    for s, pre in zip((1, 2, 3, 4), a.base_logs.split(",")):
        c = chip(pre)
        assert c and c["cyc"], pre
        C["base"][s] = c["cyc"]
    for s in (1, 2, 3, 4):
        assert C["pred_whole"][s] == C["base"][s] - 6 * C["save"], s
    C["chip_logs"] = dict(zip((1, 2, 3, 4), a.chip_logs.split(",")))
    C["tl_log"] = a.tl_log
    t9 = rd(R3_N3145)
    C["extra"] = sorted({int(x) for x in re.findall(
        r"broadcast - unicast\D*?([+-]?\d+)", t9)})
    return C


def r3_predictions(a, C):
    print("=== R3 INPUTS AND BANDS (read from the committed prediction "
          f"{a.pred_log}, written before any r3 chip run)")
    print(f"  base (r2 MEASURED, previous rung): s1 token-4 window "
          f"{C['base_tok4']} cyc ({a.base_window_log}); whole runs "
          + ", ".join(f"s{s} {C['base'][s]}" for s in C["base"])
          + f" ({a.base_logs})")
    print(f"  P-A (PRIMARY) {C['PA']} cyc = {ms(C['PA']):.3f} ms = "
          f"{C['base_tok4']} - ({C['r2_pmk']} - {C['r3_pmk']} = {C['save']}); "
          f"P-B {C['PB']} (replay {C['r2_rmk']} -> {C['r3_rmk']}); P-C "
          f"{C['PC']}, placement band {C['PC_lo']} .. {C['PC_hi']}")
    print(f"  R3-5's pass wrote replay {C['r3_rmk_pass']} / corrected "
          f"{C['r3_pmk_pass']} ({R3_REORD[1]}): = the prediction's: True")
    for nm, f in (("held  +-0.5 %", HELD), ("loose +-2 %  ", LOOSE)):
        print(f"  BAND {nm}: {C['PA'] * (1 - f):.1f} .. "
              f"{C['PA'] * (1 + f):.1f} cyc (+-{C['PA'] * f:.1f})")
    print("  outside +-2 % = STOP (no R3-10, back to the user); outside "
          "+-0.5 % inside +-2 % = attribute by class before the verdict")
    print("  s2..s4 predicted whole runs (n2900): "
          + ", ".join(f"s{s} {C['pred_whole'][s]}" for s in (1, 2, 3, 4))
          + f" (= base - 6 x {C['save']}: True)")
    print(f"  the one-window fixed extra measured by R3-9a ({R3_N3145}): "
          f"{C['extra']} cyc per broadcast")


def r3_measured(C):
    print("\n=== MEASURED (the r3 chip-TB runs on R3-9a's binary, K=r3b)")
    res = {}
    for s in (1, 2, 3, 4):
        c = chip(C["chip_logs"][s])
        if c is None or c["cyc"] is None:
            print(f"  s{s}: chip run: NOT YET")
            continue
        res[s] = c
        m = c["cyc"] / NTOK
        b = C["base"][s]
        p = C["pred_whole"][s]
        print(f"  s{s}: MEASURED {c['cyc']} cyc = {ms(m):.3f} ms/token; x "
              f"shipped {TODAY[s] / c['cyc']:.4f}; x r2 {b / c['cyc']:.4f}; x R1 "
              f"{R1[s] / c['cyc']:.4f}; r3/r2 {c['cyc'] / b:.6f}; r3/shipped "
              f"{c['cyc'] / TODAY[s]:.6f}; vs predicted {p}: {c['cyc'] - p:+d} "
              f"cyc = {100.0 * (c['cyc'] - p) / p:+.3f} %; whole-run saving vs "
              f"r2 {b - c['cyc']} (predicted {b - p}); tokens "
              f"{'IDENTICAL' if c['tok'] else 'DIFFER'}; runner "
              f"{'PASS' if c['pass'] else 'FAIL'}; wall {c['wall']} s; {c['log']}")
        print(f"  s{s}: board-scaled (uniform, MODEL) {ms(m) * SCALE:.3f} "
              f"ms/token = {tps(m):.3f} tok/s (shipped "
              f"{tps(TODAY[s] / NTOK):.3f}, r2 {tps(b / NTOK):.3f})")
    verdicts, tcyc = {}, {}
    tl = find(C["tl_log"])
    if tl:
        t = rd(tl)
        tcyc = {int(x): int(y) for x, y in
                re.findall(r"^SEQ_TIMELINE tcyc (\d+) (\d+)", t, re.M)}
        mt = re.search(r"CYCLES measured\s+(\d+)", t)
        tlc = int(mt.group(1)) if mt else None
        print(f"\n=== s1 timeline run {tl}: whole run {tlc} cyc"
              + (f"; = the control ({res[1]['cyc']}): "
                 f"{'YES' if tlc == res[1]['cyc'] else 'NO'}" if 1 in res
                 else "")
              + f"; tokens {'IDENTICAL' if 'TOKENS IDENTICAL TO THE SHIPPED RECORD' in t else 'DIFFER'}")
        ta = {int(x): int(y) for x, y in re.findall(
            r"^SEQ_TIMELINE tcyc (\d+) (\d+)",
            rd("003_timeline_model_9b_s1.log",
               os.path.join(REPO, "evidence", "qwen9b", "bn")), re.M)}
        print("  per token (cycles): shipped (BN1 003) / r2 (base) / r3")
        for k in sorted(tcyc):
            if k in ta and k in C["base_tl"]:
                print(f"    token {k}: {ta[k]} / {C['base_tl'][k]} / {tcyc[k]} "
                      f"= {ms(tcyc[k]):.3f} ms; x shipped {ta[k] / tcyc[k]:.4f}"
                      f"; x r2 {C['base_tl'][k] / tcyc[k]:.4f}; saving vs r2 "
                      f"{C['base_tl'][k] - tcyc[k]}")
    if 4 in tcyc:
        w = tcyc[4]
        d = (w - C["PA"]) / C["PA"]
        verdicts[1] = band(d)
        sv = C["base_tok4"] - w
        print(f"  s1 TOKEN-4 BODY WINDOW {w} cyc = {ms(w):.3f} ms vs P-A "
              f"{C['PA']}: {w - C['PA']:+d} cyc = {100.0 * d:+.3f} % -> s1 "
              f"{verdicts[1]}")
        print(f"  beside it: vs P-C {C['PC']} {w - C['PC']:+d} = "
              f"{100.0 * (w - C['PC']) / C['PC']:+.3f} % (inside the placement "
              f"band {C['PC_lo']}..{C['PC_hi']}: "
              f"{C['PC_lo'] <= w <= C['PC_hi']}); vs P-B {C['PB']} "
              f"{w - C['PB']:+d}")
        print(f"  THE MEASURED SAVING r2 -> r3, token 4: {C['base_tok4']} - {w} "
              f"= {sv} cyc = {ms(sv):.4f} ms/token vs the census / R3-4 "
              f"{C['save']} cyc = {ms(C['save']):.4f} ms ({100.0 * sv / C['save']:.2f} "
              f"%; {sv - C['save']:+d} cyc) and the corrected model's "
              f"{C['r2_pmk'] - C['r3_pmk']}")
        print(f"  s1 token-4: x r2 {C['base_tok4'] / w:.4f}; x shipped body "
              f"{SHIP_TOK4 / w:.4f}; x R1 token-4 {R1_TOK4 / w:.4f}; TB "
              f"{ms(w):.3f} ms/token; board-scaled (MODEL) {tps(w):.3f} tok/s "
              f"vs P-A's {tps(C['PA']):.3f} and r2 measured "
              f"{tps(C['base_tok4']):.3f}")
    else:
        print("  s1 token-4 body window: timeline run NOT YET")
    if 1 in res:
        b1 = res[1]["cyc"] / C["base"][1]
        t1 = res[1]["cyc"] / TODAY[1]
        print(f"\n=== s2..s4 whole-run ratios against s1's (r3/r2 {b1:.6f}, "
              f"r3/shipped {t1:.6f})")
        for s in (2, 3, 4):
            if s not in res:
                print(f"  s{s}: NOT YET")
                continue
            rb = res[s]["cyc"] / C["base"][s]
            rt = res[s]["cyc"] / TODAY[s]
            db, dt = rb / b1 - 1, rt / t1 - 1
            below = rb < 1
            v = (band(max(abs(db), abs(dt))) if below
                 else "r3/r2 NOT < 1 — STOP")
            verdicts[s] = v
            print(f"  s{s}: r3/r2 {rb:.6f} (< 1: {below}; vs s1 {100 * db:+.4f}"
                  f" %); r3/shipped {rt:.6f} (vs s1 {100 * dt:+.4f} %) -> "
                  f"s{s} {v}")
    print("\n=== BAND VERDICT, every stream")
    for s in (1, 2, 3, 4):
        print(f"  s{s}: {verdicts.get(s, 'NOT YET')}")
    ok = [res[s]["tok"] and res[s]["pass"] for s in res]
    print(f"  tokens IDENTICAL and runner PASS: {sum(ok)}/{len(ok)} control runs")
    return tcyc


def _class_data(rtl, csv, csv_sha, stream):
    """The pass's own s1 body schedule at `rtl` (reorder_e4), its per-record
    model windows and classes, the emitted body checked against `stream`, and
    the measured token-4 rows of `csv` (sha-checked)."""
    sys.path.insert(0, os.path.join(REPO, "ref", "scripts"))
    sys.path.insert(0, os.path.join(REPO, "ref"))
    import reorder_e4 as RE
    OC, SF = RE.OC, RE.SF
    want = open(csv_sha).read().split()[0]
    got = sha_file(csv)
    assert got == want, f"{csv}: sha {got} != committed {want}"
    src = os.path.join(REPO, "tb", "scripts", "w9", "model_9b_s1.e4")
    recs = SF.unpack_stream(open(src + ".seq", "rb").read())
    _pro, sg, _h = RE.segments(recs)
    k = [i for i, x in enumerate(sg) if x[2]]
    assert len(k) == 1
    lo, hi, _b = sg[k[0]]
    rows = RE.Windows().rows_for(recs)(k[0], lo, hi)
    S = RE.schedule_segment(recs, lo, hi, rows, "B", rtl)
    order = RE.order_and_fences(S, rtl)
    rmk, _post, _st = RE.replay(S, order)
    pmk, info = RE.predict(S, order)
    nodes = S["nodes"]
    fwin = info["fence_windows"]
    pend, fence_sel = [], []
    for x in order:
        if RE.is_fence(x):
            fm = RE.fence_mask(x)
            sel = [m_ for m_ in pend if fm == 0 or (fm >> nodes[m_].chan) & 1]
            pend = [m_ for m_ in pend if m_ not in sel]
            fence_sel.append((sel, fm))
            continue
        if nodes[x].kind == "mvgo":
            pend.append(x)
    lane_tail = info["lane"] - (sum(fwin) + sum(
        nodes[x].dur for x in order if not RE.is_fence(x)))
    items = RE.emit_segment(recs, S, order, rtl)
    ssha = sha_file(stream)
    nrecs = SF.unpack_stream(open(stream, "rb").read())
    jmp = [i for i, r in enumerate(nrecs) if r.opcode == SF.OP_JMP][0]
    blo = nrecs[jmp].imm32
    assert jmp - blo + 1 == len(items), (jmp - blo + 1, len(items))
    same = sum((q.opcode == SF.OP_JMP) if r.opcode == SF.OP_JMP
               else (r.to_bytes() == q.to_bytes())
               for (_oi, r), q in zip(items, nrecs[blo:jmp + 1]))
    assert same == len(items), (rtl, same, len(items))
    node_of_pc = {n.pc: i for i, n in enumerate(nodes)}
    argset = {nodes[a_].pc for al in RE.arg_owner(nodes).values() for a_ in al}
    n4 = read_csv_tok(csv, 4)
    raw = {}
    with open(csv) as f:
        for line in f:
            if line.startswith("R,"):
                q = line.rstrip("\n").split(",")
                if len(q) == 32 and int(q[2]) == 4:
                    raw[int(q[3])] = q
    miss = [pc for pc in range(blo, jmp + 1) if pc not in n4]
    assert not miss, f"{len(miss)} body pcs missing in token 4"
    mod, meas, cnt = (collections.Counter() for _ in range(3))
    col = {c: collections.Counter() for c in OPCOL}
    fence_rec, movx, fk = {}, [], 0
    for j, (oi, r) in enumerate(items):
        pc = blo + j
        assert n4[pc][0] == r.opcode
        if r.opcode == SF.OP_FENCE:
            c, w = "FENCE", fwin[fk]
            fence_rec[pc] = fk
            fk += 1
        else:
            n = nodes[node_of_pc[oi]]
            if oi in argset:
                c, w = "CMD+ARG", 0
            else:
                c = ("CMD+ARG" if r.opcode == SF.OP_CMD
                     else OC.OPN.get(r.opcode, str(r.opcode)))
                w = n.dur
        mod[c] += w
        meas[c] += n4[pc][2]
        cnt[c] += 1
        for cc, ix in OPCOL.items():
            col[cc][c] += int(raw[pc][ix])
        if r.opcode == SF.OP_MOVX:
            movx.append((r.len_or_addr_hi & 0xFFFFFF, (r.flags >> 4) & 0xF,
                         n4[pc][2], w, pc))
    assert fk == len(fwin)
    mod["(lane tail)"] += lane_tail
    mod["(CMD resid)"] += info["cmd_resid"]
    mvs, _lt = OC.segment_matvecs(nodes, S["groups"])
    bym = collections.defaultdict(lambda: [0, 0, 0])
    for pc, i in fence_rec.items():
        sel = fence_sel[i][0]
        key = ((mvs[nodes[sel[-1]].mv]["lt"], mvs[nodes[sel[-1]].mv]["cls"])
               if sel else ("-", "none"))
        bym[key][0] += 1
        bym[key][1] += fwin[i]
        bym[key][2] += n4[pc][2]
    byop = collections.Counter()
    for pc in range(blo, jmp + 1):
        byop[OC.OPN.get(n4[pc][0])] += n4[pc][2]
    return {"rmk": rmk, "pmk": pmk, "lane": info["lane"],
            "resid": info["cmd_resid"], "mod": mod, "meas": meas, "cnt": cnt,
            "col": col, "bym": bym, "byop": byop, "movx": movx,
            "blo": blo, "jmp": jmp, "same": same, "nitems": len(items),
            "csv_sha": got, "stream_sha": ssha,
            "msum": sum(n4[pc][2] for pc in range(blo, jmp + 1)),
            "fence_zero": sum(1 for i in fence_rec.values()
                              if fwin[i] == RE.SC.FENCE_REC)}


def r3_class_compare(C, tcyc):
    print("\n=== per-class attribution, token 4, s1 r3 (r2 rebuilt beside it)")
    D2 = _class_data("r2", CSV, CSV_SHA, R2_STREAM)
    D3 = _class_data("r3", R3_CSV, R3_CSV_SHA, R3_STREAM)
    assert D2["stream_sha"] == R2_SHA_S1
    t5 = rd(R3_REORD[1])
    _grab(r"^=== wrote tb/scripts/w9/model_9b_s1_reordB_r3\.e4\.seq sha256 %s$"
          % D3["stream_sha"], t5, "the r3 s1 stream sha as R3-5 wrote it")
    for nm, Dx, rmk, pmk in (("r2", D2, C["r2_rmk"], C["r2_pmk"]),
                             ("r3", D3, C["r3_rmk"], C["r3_pmk"])):
        print(f"  {nm}: CSV sha256 {Dx['csv_sha'][:16]} MATCH; stream sha "
              f"{Dx['stream_sha'][:16]} MATCH; model rebuilt: replay {Dx['rmk']}"
              f" (= {rmk}: {Dx['rmk'] == rmk}), predict() {Dx['pmk']} (= {pmk}: "
              f"{Dx['pmk'] == pmk}); lane {Dx['lane']} + resid {Dx['resid']}; "
              f"emitted body == the stream's body {Dx['blo']}..{Dx['jmp']}: "
              f"{Dx['same']}/{Dx['nitems']}; measured token-4 rows {Dx['msum']}")
        assert Dx["rmk"] == rmk and Dx["pmk"] == pmk
        assert sum(Dx["mod"].values()) == pmk
    assert D2["msum"] == C["base_tok4"], (D2["msum"], C["base_tok4"])
    print(f"  r3 measured rows {D3['msum']}; SEQ_TIMELINE tcyc 4 = "
          f"{tcyc.get(4)} ({(tcyc.get(4) or 0) - D3['msum']:+d} = the launch "
          f"edge); r3 measured - r3 model {D3['msum'] - D3['pmk']:+d}; r3 "
          f"measured - P-A {D3['msum'] - C['PA']:+d}")
    keys = sorted(set(D2["mod"]) | set(D3["mod"]) | set(D3["meas"]),
                  key=lambda c: -abs(D3["meas"][c] - (D2["meas"][c] + D3["mod"][c]
                                                      - D2["mod"][c])))
    gap = D3["msum"] - C["PA"]
    print("  BY CLASS (token 4): n r2->r3 | r2 MEASURED | model delta | r3 "
          "EXPECTED (R3-7) | r3 MEASURED | measured - expected (% of P-A) | "
          "share of the gap | r3 model | measured - model")
    te = 0
    for c in keys:
        dlt = D3["mod"][c] - D2["mod"][c]
        e = D2["meas"][c] + dlt
        te += e
        dd = D3["meas"][c] - e
        print(f"    {c:12s} {D2['cnt'][c]:5d}->{D3['cnt'][c]:5d} | "
              f"{D2['meas'][c]:9d} | {dlt:+9d} | {e:9d} | {D3['meas'][c]:9d} | "
              f"{dd:+8d} ({100.0 * dd / C['PA']:+.4f} %) | "
              + (f"{100.0 * dd / gap:+.1f} %" if gap else "-")
              + f" | {D3['mod'][c]:9d} | {D3['meas'][c] - D3['mod'][c]:+8d}")
    print(f"  sum of r3 EXPECTED {te} (= P-A {C['PA']}: {te == C['PA']})")
    print(f"  FENCE: zero-wait in the model r2 {D2['fence_zero']} / r3 "
          f"{D3['fence_zero']}")
    print("  FENCE windows by the class drained (n | r2 measured | r3 model | "
          "r3 measured | r3 measured - r2 measured | r3 measured - model):")
    ks = set(D2["bym"]) | set(D3["bym"])
    for key in sorted(ks, key=lambda k_: -abs(D3["bym"][k_][2] - D2["bym"][k_][2])):
        n2, _a2, b2 = D2["bym"][key]
        n3, a3, b3 = D3["bym"][key]
        print(f"      {key[0]:4s} {key[1]:9s} {n2:4d}->{n3:4d} | {b2:9d} | "
              f"{a3:9d} | {b3:9d} | {b3 - b2:+8d} | {b3 - a3:+8d}")
    dn2, dn3 = D2["bym"][("DN", "dn_out")], D3["bym"][("DN", "dn_out")]
    print(f"  dn_out APART: r2 measured {dn2[2]}, r3 model {dn3[1]}, r3 "
          f"measured {dn3[2]} (r3 - r2 {dn3[2] - dn2[2]:+d}; r3 - model "
          f"{dn3[2] - dn3[1]:+d}); FENCE without dn_out: r2 "
          f"{D2['meas']['FENCE'] - dn2[2]}, r3 {D3['meas']['FENCE'] - dn3[2]}")
    print("  lane work by opcode, token 4 (cyc): r2 measured -> r3 measured "
          "(delta)")
    for o in sorted(set(D2["byop"]) | set(D3["byop"]), key=str):
        print(f"    {o!s:6s} {D2['byop'][o]:10d} -> {D3['byop'][o]:10d} "
              f"({D3['byop'][o] - D2['byop'][o]:+d})")
    print("  where a DMA stall moves: L_DMA-busy cycles and fetch-empty stall "
          "cycles inside each class's windows, token 4 (r2 -> r3):")
    for cc in OPCOL:
        a2, a3 = sum(D2["col"][cc].values()), sum(D3["col"][cc].values())
        top = sorted(set(D2["col"][cc]) | set(D3["col"][cc]),
                     key=lambda c: -abs(D3["col"][cc][c] - D2["col"][cc][c]))[:4]
        print(f"    {cc:6s} total {a2} -> {a3} ({a3 - a2:+d}); by class: "
              + "; ".join(f"{c} {D2['col'][cc][c]} -> {D3['col'][cc][c]}"
                          for c in top))
    # ---- the one-window measurement
    print("\n=== THE ONE-WINDOW MEASUREMENT (the broadcast's price; R3-4's "
          "untested assumption)")
    u = collections.defaultdict(list)
    for ln, ch, w, _m, _pc in D2["movx"]:
        u[ln].append(w)
    bl = collections.defaultdict(list)
    for ln, ch, w, _m, _pc in D3["movx"]:
        assert ch == 0xF, f"an r3 body MOVX is not a broadcast (chan {ch})"
        bl[ln].append(w)
    xs = C["extra"]
    fx = xs[0] if len(xs) == 1 else None
    print(f"  r3 body MOVX: {sum(len(v) for v in bl.values())}, every one a "
          f"broadcast (chan 0xF); r2 body MOVX: {sum(len(v) for v in u.values())}"
          f" unicast; R3-9a's fixed extra {xs} cyc")
    print("  len | r2 unicast n, mean (min..max) | r3 broadcast n, mean "
          "(min..max) | broadcast - unicast mean | ratio | vs +19")
    tot = 0
    for ln in sorted(set(u) | set(bl)):
        a_, b_ = u.get(ln, []), bl.get(ln, [])
        if not b_:
            continue
        ma = sum(a_) / len(a_)
        mb = sum(b_) / len(b_)
        tot += sum(b_)
        print(f"    {ln:6d} | {len(a_):4d} {ma:10.2f} ({min(a_)}..{max(a_)}) | "
              f"{len(b_):4d} {mb:10.2f} ({min(b_)}..{max(b_)}) | "
              f"{mb - ma:+9.2f} | {mb / ma:.5f} | "
              + (f"{mb - ma - fx:+.2f} beyond +{fx}" if fx is not None else "-"))
    nb = sum(len(v) for v in bl.values())
    exp1 = sum(sum(u[ln]) / len(u[ln]) * len(bl[ln]) for ln in bl)
    print(f"  THE MOVX CLASS, token 4: r2 measured {sum(sum(v) for v in u.values())}"
          f" -> r3 measured {tot}; at exactly one window {exp1:.0f}; + {nb} x "
          f"{fx} = {exp1 + nb * (fx or 0):.0f}; measured - (one window + the "
          f"fixed extra) {tot - exp1 - nb * (fx or 0):+.0f} cyc = "
          f"{100.0 * (tot - exp1 - nb * (fx or 0)) / C['PA']:+.4f} % of P-A; the "
          f"fixed term alone {nb * (fx or 0)} cyc/token = "
          f"{100.0 * nb * (fx or 0) / C['PA']:.4f} % of P-A")


def main_r3(a):
    if os.environ.get("FABLE5_MODEL") != "9b" or \
            os.environ.get("FABLE5_RS_F") != "7":
        raise SystemExit("SR13A_DERIVE --rtl r3: FABLE5_MODEL=9b "
                         "FABLE5_RS_F=7 required (the operating point)")
    print(f"=== operating point FABLE5_MODEL={os.environ['FABLE5_MODEL']} "
          f"FABLE5_RS_F={os.environ['FABLE5_RS_F']}")
    C = r3_inputs(a)
    r3_predictions(a, C)
    if a.predict:
        print("SR13A_DERIVE --rtl r3: INPUTS READ")
        return
    tcyc = r3_measured(C)
    if os.path.exists(R3_CSV_SHA) and 4 in tcyc:
        r3_class_compare(C, tcyc)
    print("SR13A_DERIVE --rtl r3: DONE")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--predict", action="store_true")
    ap.add_argument("--rtl", default="r2", choices=("r2", "r3"),
                    help="r2 = SR13a's committed use (n1349g); r3 = R3-9b")
    ap.add_argument("--pred-log", default="n2900_r3_predictions.log")
    ap.add_argument("--base-window-log",
                    default="n1349e_sr13a_chip_s1_r2_timeline.log")
    ap.add_argument("--base-logs", default="n1349a,n1349b,n1349c,n1349d")
    ap.add_argument("--chip-logs", default="n3160,n3161,n3162,n3163")
    ap.add_argument("--tl-log", default="n3164")
    a = ap.parse_args()
    if a.rtl == "r3":
        main_r3(a)
        return
    pred = predictions()
    if a.predict:
        print("SR13A_DERIVE: PREDICTIONS WRITTEN")
        return
    tcyc = measured(pred)
    if os.path.exists(CSV_SHA) and 4 in tcyc:
        class_compare(tcyc)
    print("SR13A_DERIVE: DONE")


if __name__ == "__main__":
    main()
