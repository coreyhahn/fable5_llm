#!/usr/bin/env python3
"""r3_predict.py — Task R3-7: the chip-TB PREDICTION for the r3 streams.

Written and committed BEFORE any r3 chip-TB run (R3-9a's Step 4 checks the
commit is an ancestor).  Reads committed logs only, plus (for the per-class
model and the one-window baseline) the gitignored streams and the r2
timeline CSV, each checked against its committed FULL sha256 first.
Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh:

    FABLE5_MODEL=9b FABLE5_RS_F=7 /home/cah/.venv/bin/python \
        evidence/qwen9b/sr/r3_predict.py [--r3-pins-log nNNNN_....log]

Why a new file and not `sr13a_derive.py --rtl r3` (flags, not copies, I-5):
the plan gives sr13a_derive.py's `--rtl r3` flag to R3-9b (the MEASURED
side, plan Task R3-9b "Files"), and this task's content differs: the
primary is the absolute-saving form anchored on the MEASURED r2 window
(P-A), with the census (P-B) and the pass's corrected r3 prediction (P-C)
beside it, the r2->r3 per-class model delta, the one-window baseline and the
chat-image formulas — none of which sr13a_derive computes.  Its helpers
(ms, tps, band, the shipped references, the uniform board factor) are
IMPORTED from sr13a_derive, not copied.  The per-class model rebuild below
is the model half of sr13a_derive.class_compare, parameterised by rtl.

The quantity: the s1 token-4 body window (`SEQ_TIMELINE tcyc 4`) of the r3
stream on the chip TB, as SR13a's.
"""
import argparse
import collections
import hashlib
import os
import re
import sys

SR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(SR, "..", "..", ".."))
sys.path.insert(0, SR)
import sr13a_derive as D                       # noqa: E402  (helpers only)

W9 = os.path.join(REPO, "tb", "scripts", "w9")
OV = os.path.join(REPO, "evidence", "qwen9b", "ov")
REORD = {"r2": {1: "n1165_reorder_s1_B_r2.log", 2: "n1166_reorder_s2_B_r2.log",
                3: "n1167_reorder_s3_B_r2.log", 4: "n1168_reorder_s4_B_r2.log"},
         "r3": {1: "n2720_r3_5_reorder_s1_B_r3.log",
                2: "n2721_r3_5_reorder_s2_B_r3.log",
                3: "n2722_r3_5_reorder_s3_B_r3.log",
                4: "n2723_r3_5_reorder_s4_B_r3.log"}}
R2_CHIP = {1: "n1349a_sr13a_chip_s1_r2.log", 2: "n1349b_sr13a_chip_s2_r2.log",
           3: "n1349c_sr13a_chip_s3_r2.log", 4: "n1349d_sr13a_chip_s4_r2.log"}
R2_TL = "n1349e_sr13a_chip_s1_r2_timeline.log"
R2_DERIVE = "n1349g_sr13a_derive.log"
SR11B_DERIVE = "n1182_sr11b_r2_derive.log"
CENSUS = "n1600_sr16_r3_census.log"
R34 = "n2606_r3_4_derive.log"
STREAM = {"r2": ("model_9b_s1_reordB_r2.e4.seq",
                 "117ed8b061d5662517d67f905ff1b5900520ba39eff680548e8af9a7efc17d19"),
          "r3": ("model_9b_s1_reordB_r3.e4.seq",
                 "3e77e57ca39452b987d3acea708c5daf40f6def43a9bf35524caf1d47e51d3ff")}
# the r2 / r3 s1 stream shas are the ones n1165:58 and n2720:61 wrote; checked
# below against those log lines, not only against these literals
STREAM_LOG_LINE = {"r2": ("n1165_reorder_s1_B_r2.log", 58),
                   "r3": ("n2720_r3_5_reorder_s1_B_r3.log", 61)}


def line(name, n, d=SR):
    return open(os.path.join(d, name)).read().split("\n")[n - 1]


def grab(pat, text, what, flags=re.M):
    m = re.search(pat, text, flags)
    if not m:
        raise SystemExit(f"R3_PREDICT: cannot read {what} ({pat!r})")
    return m


def loop_body(rtl, s):
    """(replay LOOP BODY, corrected LOOP BODY, [replay per seg], [corr per seg])
    from the pass's own committed log (n1165-n1168 / n2720-n2723)."""
    t = D.rd(REORD[rtl][s])
    rp = grab(r"^=== %s: replay makespan .* per segment: ([^;]+); LOOP BODY "
              r"(\d+) cyc" % rtl, t, f"{rtl} s{s} replay")
    cp = grab(r"^=== %s: CORRECTED prediction .* per segment: ([^;]+); LOOP "
              r"BODY (\d+) cyc \(lane (\d+) \+ CMD residual (\d+)" % rtl, t,
              f"{rtl} s{s} corrected")
    rs = [int(x) for x in re.findall(r"seg\d+ (\d+)", rp.group(1))]
    cs = [int(x) for x in re.findall(r"seg\d+ (\d+)", cp.group(1))]
    assert len(rs) == len(cs) and rs
    return {"replay": int(rp.group(2)), "pred": int(cp.group(2)),
            "lane": int(cp.group(3)), "resid": int(cp.group(4)),
            "rseg": rs, "cseg": cs}


def chip_cycles(name):
    return int(grab(r"CYCLES measured\s+(\d+)", D.rd(name), name).group(1))


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for ch in iter(lambda: f.read(1 << 24), b""):
            h.update(ch)
    return h.hexdigest()


def pct(a, b):
    return 100.0 * (a - b) / b


# ---------------------------------------------------------------------------
def inputs():
    print("=== INPUTS (every one read back from a committed log line)")
    I = {}
    I["r2_meas"] = int(grab(r"^SEQ_TIMELINE tcyc 4 (\d+)", D.rd(R2_TL),
                            R2_TL).group(1))
    print(f"  T  r2 s1 token-4 body window MEASURED {I['r2_meas']}  "
          f"({R2_TL}:56: {line(R2_TL, 56).strip()!r})")
    I["lb"] = {rtl: {s: loop_body(rtl, s) for s in (1, 2, 3, 4)}
               for rtl in ("r2", "r3")}
    for rtl in ("r2", "r3"):
        b = I["lb"][rtl][1]
        print(f"  E  {rtl} s1 body: replay_mk {b['replay']}, pred_mk "
              f"{b['pred']} (lane {b['lane']} + resid {b['resid']})  "
              f"({REORD[rtl][1]})")
    I["r2_whole"] = {s: chip_cycles(R2_CHIP[s]) for s in (1, 2, 3, 4)}
    print("  T  r2 whole runs MEASURED (SR13a, line 30 of each): "
          + ", ".join(f"s{s} {I['r2_whole'][s]}" for s in (1, 2, 3, 4)))
    t = D.rd(SR11B_DERIVE)
    I["stall"] = int(grab(r"the (\d+)-cyc DMA stall", t, "stall").group(1))
    print(f"  T  SR11b's DMA stall (placement band width) {I['stall']} cyc "
          f"({SR11B_DERIVE}:28)")
    c = D.rd(CENSUS)
    I["cen_r2"] = int(grab(r"B:R2\s+makespan\s+(\d+)", c, "census R2").group(1))
    I["cen_r3"] = int(grab(r"B:R3\s+makespan\s+(\d+)", c, "census R3").group(1))
    I["cen_save"] = int(grab(r"SAVE B:R3\s+(\d+) cyc", c, "SAVE").group(1))
    m = grab(r"lane work removed (\d+) cyc.*lane idle change \+(\d+) cyc", c,
             "SAVE split")
    I["cen_removed"], I["cen_idle"] = int(m.group(1)), int(m.group(2))
    m = grab(r"live (\d+): (\d+) cyc", c, "live MOVX")
    I["live_n"], I["live_cyc"] = int(m.group(1)), int(m.group(2))
    m = grab(r"broadcast carriers \(first live MOVX\) (\d+): (\d+) cyc", c,
             "carriers")
    I["car_n"], I["car_cyc"] = int(m.group(1)), int(m.group(2))
    m = grab(r"SIBLINGS R3 zeroes: (\d+) MOVX, (\d+) cyc", c, "siblings")
    I["sib_n"], I["sib_cyc"] = int(m.group(1)), int(m.group(2))
    print(f"  E  census (n1600): R2 {I['cen_r2']} (:23), R3 {I['cen_r3']} "
          f"(:26), SAVE {I['cen_save']} = removed {I['cen_removed']} - idle "
          f"rise {I['cen_idle']} (:36); live MOVX {I['live_n']} / "
          f"{I['live_cyc']} (:17); carriers {I['car_n']} / {I['car_cyc']} "
          f"(:19); siblings {I['sib_n']} / {I['sib_cyc']} (:20)")
    r34 = D.rd(R34)
    I["r34_save"] = int(grab(r"NET saving per token\s+([\d,]+) cyc", r34,
                             "R3-4 NET").group(1).replace(",", ""))
    print(f"  D  R3-4 NET saving {I['r34_save']} ({R34}:24)")
    g = D.rd(R2_DERIVE)
    meas = {}
    for cls in ("CMD+ARG", "FENCE", "LDC", "MVGO", "EMB", "JMP", "MOVY",
                "CSRWR", "AMAXL", "XOP", "MOVX"):
        m = grab(r"^\s+%s\s+(\d+) \|\s+(\d+) \|\s+(\d+) \|" % re.escape(cls),
                 g, f"n1349g class {cls}")
        meas[cls] = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    I["r2_cls"] = meas
    m = grab(r"^\s+MOVX\s+(\d+) ->\s+(\d+) \(", g, "MOVX lane work")
    I["r2_movx_lane"] = int(m.group(2))
    print(f"  D  r2 token-4 measured by class (n1349g:69-81), MOVX lane work "
          f"{I['r2_movx_lane']} (n1349g:110)")
    # consistency, each must hold
    ok = True
    for nm, a, b in (
            ("r2 replay_mk = census R2 row", I["lb"]["r2"][1]["replay"],
             I["cen_r2"]),
            ("r3 replay_mk = census R3 row", I["lb"]["r3"][1]["replay"],
             I["cen_r3"]),
            ("census saving = R3-4 NET", I["cen_r2"] - I["cen_r3"],
             I["r34_save"]),
            ("census saving = n1600 SAVE", I["cen_r2"] - I["cen_r3"],
             I["cen_save"]),
            ("corrected saving = census saving",
             I["lb"]["r2"][1]["pred"] - I["lb"]["r3"][1]["pred"],
             I["cen_save"]),
            ("n1349g MOVX class measured = MOVX lane work",
             I["r2_cls"]["MOVX"][2], I["r2_movx_lane"]),
            ("r2 measured MOVX lane = census live MOVX", I["r2_movx_lane"],
             I["live_cyc"]),
            ("live = carriers + siblings", I["live_cyc"],
             I["car_cyc"] + I["sib_cyc"])):
        good = a == b
        ok &= good
        print(f"  [{'PASS' if good else 'FAIL'}] {nm}: {a} vs {b}")
    for rtl in ("r2", "r3"):
        nm, ln = STREAM_LOG_LINE[rtl]
        good = STREAM[rtl][1] in line(nm, ln)
        ok &= good
        print(f"  [{'PASS' if good else 'FAIL'}] {rtl} s1 stream sha "
              f"{STREAM[rtl][1][:16]} is the one {nm}:{ln} wrote")
    if not ok:
        raise SystemExit("R3_PREDICT: an input check FAILED")
    return I


# ---------------------------------------------------------------------------
def headline(I):
    r2m = I["r2_meas"]
    r2, r3 = I["lb"]["r2"][1], I["lb"]["r3"][1]
    save_c = r2["pred"] - r3["pred"]
    save_r = r2["replay"] - r3["replay"]
    PA = r2m - save_c
    PB = r2m - save_r
    PC = r3["pred"]
    PC_lo = PC - I["stall"]
    off = (r2m - r2["pred"]) / r2["pred"]
    print("\n=== THE PREDICTION — s1 token-4 body window of the r3 stream on "
          "the chip TB (MODEL; every number from the lines above)")
    print(f"  P-A (PRIMARY, absolute, corrected-model saving): {r2m} - "
          f"({r2['pred']} - {r3['pred']} = {save_c}) = {PA} cyc = "
          f"{D.ms(PA):.3f} ms")
    print(f"  P-B (absolute, census saving): {r2m} - ({r2['replay']} - "
          f"{r3['replay']} = {save_r}) = {PB} cyc; P-B - P-A {PB - PA:+d}")
    print(f"  P-C (the pass's own corrected r3 prediction, SR13a's form): "
          f"{PC} cyc, placement band {PC_lo} .. {PC} (the {I['stall']}-cyc "
          f"DMA stall absorbed by a FENCE wait or not); P-C - P-A "
          f"{PC - PA:+d} = {pct(PC, PA):+.3f} % of P-A")
    print(f"  R2's offset carried: measured r2 - corrected r2 = "
          f"{r2m - r2['pred']:+d} cyc = {100 * off:+.4f} %; P-C + that "
          f"absolute offset = {PC + r2m - r2['pred']} (= P-A: "
          f"{PC + r2m - r2['pred'] == PA}); P-C x (1 {100 * off:+.4f} %) = "
          f"{PC * (1 + off):.0f}")
    rc = r2m * r3["pred"] / r2["pred"]
    rr = r2m * r3["replay"] / r2["replay"]
    print(f"  ratio forms (INFORMATIONAL, no band): {r2m} x {r3['pred']}/"
          f"{r2['pred']} = {rc:.0f} ({pct(rc, PA):+.3f} % vs P-A); census "
          f"ratio x{r2['replay'] / r3['replay']:.4f} -> {rr:.0f} "
          f"({pct(rr, PA):+.3f} % vs P-A)")
    print(f"  saving expected on the chip TB: {r2m - PA} cyc = "
          f"{D.ms(r2m - PA):.3f} ms/token (the 2,044,160 of R3-4 / R3-5, "
          f"in both conventions) — resting on the UNMEASURED one-window "
          f"pricing of a broadcast (R3-4); R3-9b is its first test")
    print("\n=== BANDS on P-A (SR5b's; |measured / P-A - 1|)")
    for nm, f in (("HELD  +-0.5 %", D.HELD), ("LOOSE +-2 %  ", D.LOOSE)):
        print(f"  {nm}: {PA * (1 - f):.1f} .. {PA * (1 + f):.1f} cyc "
              f"(+-{PA * f:.1f})")
    print(f"  as a measured SAVING (26,171,253 - measured): HELD "
          f"{r2m - PA * (1 + D.HELD):.0f} .. {r2m - PA * (1 - D.HELD):.0f}; "
          f"LOOSE {r2m - PA * (1 + D.LOOSE):.0f} .. "
          f"{r2m - PA * (1 - D.LOOSE):.0f} cyc")
    print(f"  one more / one fewer {I['stall']}-cyc DMA stall moves the window "
          f"{100 * I['stall'] / PA:.3f} % of P-A; the HELD band is "
          f"{PA * D.HELD / I['stall']:.1f} stalls wide each side")
    print("  inside +-0.5 %: HELD.  inside +-2 %: HELD LOOSELY — ATTRIBUTE "
          "BY CLASS (MOVX vs FENCE (dn_out apart) vs CMD) from the s1 r3 "
          "timeline BEFORE R3-10 launches.")
    print("  OUTSIDE +-2 %: STOP — the campaign stops before the full build "
          "(R3-10; no Vivado time) and the controller returns to the user.")
    print(f"  MODEL context: x shipped body {D.SHIP_TOK4 / PA:.4f}; x r2 "
          f"measured {r2m / PA:.4f}; board-scaled (OV1 uniform factor, "
          f"MODEL) {D.tps(PA):.3f} tok/s vs r2 measured-window "
          f"{D.tps(r2m):.3f}")
    return {"PA": PA, "PB": PB, "PC": PC, "save": save_c}


# ---------------------------------------------------------------------------
def seeds(I, P):
    print("\n=== s2..s4 — the whole run, r3 / r2 (SR13a's measured r2 cycles, "
          "same seed) and r3 / shipped")
    print("  criterion: r3/r2 < 1 and within +-0.5 % of s1's r3/r2; r3/shipped "
          "within +-0.5 % of s1's; outside +-0.5 % attribute, outside +-2 % "
          "STOP")
    pred = {}
    for s in (1, 2, 3, 4):
        a, b = I["lb"]["r2"][s], I["lb"]["r3"][s]
        segsave = [x - y for x, y in zip(a["cseg"], b["cseg"])]
        rsave = [x - y for x, y in zip(a["rseg"], b["rseg"])]
        L = D.LOOP[s]
        tot = sum(segsave[:-1]) + L * segsave[-1]
        rtot = sum(rsave[:-1]) + L * rsave[-1]
        p = I["r2_whole"][s] - tot
        pred[s] = p
        print(f"  s{s}: per-segment saving corrected {segsave} (census "
              f"{rsave}); windows {len(segsave) - 1} + {L} x body; whole-run "
              f"saving {tot} (census {rtot}); PREDICTED r3 whole run "
              f"{I['r2_whole'][s]} - {tot} = {p} cyc = "
              f"{D.ms(p) / D.NTOK:.3f} ms/token; r3/r2 "
              f"{p / I['r2_whole'][s]:.6f}; r3/shipped {p / D.TODAY[s]:.6f}; "
              f"x shipped {D.TODAY[s] / p:.4f}")
    r1 = pred[1] / I["r2_whole"][1]
    t1 = pred[1] / D.TODAY[1]
    for s in (2, 3, 4):
        rb = pred[s] / I["r2_whole"][s]
        rt = pred[s] / D.TODAY[s]
        print(f"  s{s} vs s1 (predicted): r3/r2 {100 * (rb / r1 - 1):+.4f} %; "
              f"r3/shipped {100 * (rt / t1 - 1):+.4f} %")
    return pred


# ---------------------------------------------------------------------------
def model_classes(rtl):
    """The model half of sr13a_derive.class_compare, at `rtl`: rebuild the s1
    body schedule with the pass's own functions, require it to reproduce the
    committed replay_mk / pred_mk, check the emitted body against the stream
    on disk record by record, and return the model's windows by class."""
    sys.path.insert(0, os.path.join(REPO, "ref", "scripts"))
    sys.path.insert(0, os.path.join(REPO, "ref"))
    import reorder_e4 as RE
    OC, SF = RE.OC, RE.SF
    path = os.path.join(W9, STREAM[rtl][0])
    got = sha_file(path)
    assert got == STREAM[rtl][1], f"{rtl} stream sha {got}"
    recs = SF.unpack_stream(open(os.path.join(W9, "model_9b_s1.e4.seq"),
                                 "rb").read())
    _pro, sg, _h = RE.segments(recs)
    k = [i for i, x in enumerate(sg) if x[2]]
    assert len(k) == 1
    k = k[0]
    lo, hi, _b = sg[k]
    rows = RE.Windows().rows_for(recs)(k, lo, hi)
    S = RE.schedule_segment(recs, lo, hi, rows, "B", rtl)
    order = RE.order_and_fences(S, rtl)
    rmk, _post, _st = RE.replay(S, order)
    pmk, info = RE.predict(S, order)
    nodes = S["nodes"]
    fwin = info["fence_windows"]
    lane_tail = info["lane"] - (sum(fwin) + sum(
        nodes[x].dur for x in order if not RE.is_fence(x)))
    items = RE.emit_segment(recs, S, order, rtl)
    nrecs = SF.unpack_stream(open(path, "rb").read())
    jmp = [i for i, r in enumerate(nrecs) if r.opcode == SF.OP_JMP][0]
    blo = nrecs[jmp].imm32
    assert jmp - blo + 1 == len(items), (jmp - blo + 1, len(items))
    same = sum((q.opcode == SF.OP_JMP) if r.opcode == SF.OP_JMP
               else (r.to_bytes() == q.to_bytes())
               for (_oi, r), q in zip(items, nrecs[blo:jmp + 1]))
    assert same == len(items), (rtl, same, len(items))
    node_of_pc = {n.pc: i for i, n in enumerate(nodes)}
    argset = {nodes[a].pc for al in RE.arg_owner(nodes).values() for a in al}
    mod, cnt = collections.Counter(), collections.Counter()
    movx = []                       # (length, chan field, model window)
    fk = 0
    for j, (oi, r) in enumerate(items):
        if r.opcode == SF.OP_FENCE:
            mod["FENCE"] += fwin[fk]
            cnt["FENCE"] += 1
            fk += 1
            continue
        n = nodes[node_of_pc[oi]]
        if oi in argset:
            c, w = "CMD+ARG", 0
        else:
            c = ("CMD+ARG" if r.opcode == SF.OP_CMD
                 else OC.OPN.get(r.opcode, str(r.opcode)))
            w = n.dur
        mod[c] += w
        cnt[c] += 1
        if r.opcode == SF.OP_MOVX:
            movx.append((r.len_or_addr_hi & 0xFFFFFF, (r.flags >> 4) & 0xF, w))
    assert fk == len(fwin)
    mod["(lane tail)"] += lane_tail
    mod["(CMD resid)"] += info["cmd_resid"]
    return {"replay": rmk, "pred": pmk, "lane": info["lane"],
            "resid": info["cmd_resid"], "mod": mod, "cnt": cnt,
            "blo": blo, "jmp": jmp, "nitems": len(items), "same": same,
            "movx": movx, "sha": got}


def classes(I, P):
    print("\n=== PER-CLASS EXPECTATION, token 4, s1 (the attribution's "
          "reference; MODEL)")
    M = {}
    for rtl in ("r2", "r3"):
        m = model_classes(rtl)
        want = I["lb"][rtl][1]
        ok = m["replay"] == want["replay"] and m["pred"] == want["pred"]
        print(f"  {rtl}: stream sha {m['sha'][:16]} MATCH; model rebuilt: "
              f"replay {m['replay']} (= {want['replay']}: "
              f"{m['replay'] == want['replay']}), predict() {m['pred']} (= "
              f"{want['pred']}: {m['pred'] == want['pred']}); lane "
              f"{m['lane']} + resid {m['resid']}; emitted body == the stream's "
              f"body {m['blo']}..{m['jmp']}: {m['same']}/{m['nitems']}")
        assert ok
        assert sum(m["mod"].values()) == m["pred"]
        M[rtl] = m
    meas = {c: v[2] for c, v in I["r2_cls"].items()}
    print("  class | r2 model | r3 model | model delta | r2 MEASURED "
          "(n1349g) | r3 EXPECTED = r2 measured + delta")
    keys = sorted(set(M["r2"]["mod"]) | set(M["r3"]["mod"]),
                  key=lambda c: -abs(M["r3"]["mod"][c] - M["r2"]["mod"][c]))
    te = 0
    for c in keys:
        a, b = M["r2"]["mod"][c], M["r3"]["mod"][c]
        mm = meas.get(c, 0)
        e = mm + (b - a)
        te += e
        print(f"    {c:12s} n {M['r2']['cnt'][c]:5d}->{M['r3']['cnt'][c]:5d} "
              f"| {a:9d} | {b:9d} | {b - a:+9d} | {mm:9d} | {e:9d}")
    assert sum(meas.values()) == I["r2_meas"], "n1349g classes != window"
    print(f"  sum of the expected classes {te} (= P-A {P['PA']}: "
          f"{te == P['PA']}; the additive residual's measured 0 carried)")
    d = {c: M["r3"]["mod"][c] - M["r2"]["mod"][c] for c in keys}
    print(f"  model delta: MOVX {d.get('MOVX', 0):+d}, FENCE "
          f"{d.get('FENCE', 0):+d}, every other class "
          f"{sum(v for c, v in d.items() if c not in ('MOVX', 'FENCE')):+d}; "
          f"census: siblings removed -{I['sib_cyc']}, lane idle "
          f"+{I['cen_idle']} (n1600:36)")
    return M


# ---------------------------------------------------------------------------
def one_window(I, M):
    print("\n=== THE ONE-WINDOW ASSUMPTION, stated for measurement "
          "(REPORTED, NOT BANDED)")
    print("  assumption (R3-4; spec §1.3 (a)): a broadcast MOVX costs ONE "
          "unicast MOVX window of its length; its three siblings cost 0")
    print("  measure (R3-9a coverage (5), R3-9b s1 timeline): mean broadcast "
          "MOVX window / mean unicast MOVX window of the SAME length on "
          "SR13a's r2 timeline; expected 1.00 + the broadcast's fixed extra "
          "(three more closing STATUS reads, R3-8's X_STATW walk)")
    csv = D.CSV
    want = open(D.CSV_SHA).read().split()[0]
    if not os.path.exists(csv):
        print(f"  r2 timeline CSV ABSENT — regenerate by the n1349e recipe "
              f"and check sha {want[:16]} before R3-9b reads it")
        return
    got = sha_file(csv)
    print(f"  r2 timeline CSV sha256 {got[:16]} "
          f"{'MATCH' if got == want else 'MISMATCH'} (committed {want[:16]})")
    if got != want:
        raise SystemExit("R3_PREDICT: r2 CSV sha MISMATCH")
    n4 = D.read_csv_tok(csv, 4)
    blo, jmp = M["r2"]["blo"], M["r2"]["jmp"]
    import reorder_e4 as RE
    SF = RE.SF
    nrecs = SF.unpack_stream(open(os.path.join(W9, STREAM["r2"][0]),
                                  "rb").read())
    bylen = collections.defaultdict(list)
    for pc in range(blo, jmp + 1):
        r = nrecs[pc]
        if r.opcode == SF.OP_MOVX:
            assert n4[pc][0] == SF.OP_MOVX
            bylen[r.len_or_addr_hi & 0xFFFFFF].append(n4[pc][2])
    r3len = collections.Counter(ln for ln, ch, _w in M["r3"]["movx"])
    r3mod = collections.defaultdict(int)
    for ln, ch, w in M["r3"]["movx"]:
        assert ch == 0xF, f"an r3 body MOVX not a broadcast (chan {ch})"
        r3mod[ln] += w
    print("  r2 token-4 unicast MOVX by length (the denominator): len | n | "
          "mean measured | min | max || r3 broadcasts of that len | model "
          "window each | expected broadcast lane work (r2 mean x n)")
    exp = 0
    tot_n = 0
    for ln in sorted(bylen):
        w = bylen[ln]
        mean = sum(w) / len(w)
        nb = r3len.get(ln, 0)
        e = mean * nb
        exp += e
        tot_n += len(w)
        print(f"    {ln:6d} | {len(w):4d} | {mean:10.2f} | {min(w):6d} | "
              f"{max(w):6d} || {nb:4d} | "
              f"{(r3mod[ln] / nb if nb else 0):9.1f} | {e:10.1f}")
    assert set(r3len) <= set(bylen), "an r3 broadcast length has no r2 unicast"
    print(f"  r2 live MOVX {tot_n} (= census live {I['live_n']}: "
          f"{tot_n == I['live_n']}); r3 broadcasts {sum(r3len.values())} "
          f"(= carriers {I['car_n']}: {sum(r3len.values()) == I['car_n']})")
    print(f"  THE MOVX CLASS, token 4: r2 measured {I['r2_movx_lane']} -> "
          f"r3 expected {exp:.0f} at exactly one window "
          f"({100 * exp / I['r2_movx_lane']:.2f} % of r2, i.e. a fall of "
          f"{I['r2_movx_lane'] - exp:.0f} = "
          f"{100 * (1 - exp / I['r2_movx_lane']):.2f} %: the {I['sib_n']} "
          f"siblings of {I['live_n']}) + {I['car_n']} x the fixed extra "
          f"(unmeasured; R3-9a measures it)")


# ---------------------------------------------------------------------------
def pins(path):
    """{kind: (replay, corrected)} from an sr13b_r2_pins.py log."""
    t = open(path).read()
    out = {}
    for kind in ("lite", "full"):
        m = re.search(r"^--- r\d %s: .*?\n.*?\n\s+.*?replay (\d+) cyc.*?"
                      r"corrected prediction (\d+) cyc" % kind, t, re.M | re.S)
        if m:
            out[kind] = (int(m.group(1)), int(m.group(2)))
    return out


def chat(I, r3pins):
    print("\n=== THE r3 CHAT IMAGES (R3-9b Step 4 on the chip TB; R3-11 P1' "
          "on the board) — the absolute form, static makespans at position 0")
    r1 = {}
    t = D.rd("n601_r1_pins.log")
    for kind in ("lite", "full"):
        m = grab(r"^--- r1 %s: .*?\n.*?replay (\d+) cyc" % kind, t,
                 f"n601 {kind}", re.M | re.S)
        r1[kind] = int(m.group(1))
    r2 = pins(os.path.join(SR, "n1351_sr13b_r2_pins.log"))
    g = D.rd("n588_sr5b_chat_compare.log")
    r1m = {}
    for kind in ("lite", "full"):
        m = grab(r"^\s+%s\s+n=8\s+shipped [\d,]+\.\.[\d,]+\s+r1 ([\d,]+)\.\."
                 r"([\d,]+)" % kind, g, f"n588 {kind}")
        r1m[kind] = (int(m.group(1).replace(",", "")),
                     int(m.group(2).replace(",", "")))
    print("  inputs: r1 static replay (n601:9/15) "
          + ", ".join(f"{k} {r1[k]}" for k in r1)
          + "; r2 static replay / corrected (n1351:9/15) "
          + ", ".join(f"{k} {r2[k][0]} / {r2[k][1]}" for k in r2)
          + "; r1 chip-TB MEASURED per launch (SR5b n588:41/43) "
          + ", ".join(f"{k} {r1m[k][0]}..{r1m[k][1]}" for k in r1m))
    print("  BOARD (R3-11 P1', the plan's formula): n1508 (r2 board, per "
          "image) - (r2 corrected static - r3 corrected static) per image "
          "kind; the numbers are R3-11's n3300")
    print("  CHIP TB (R3-9b Step 4): no r2 chat image ever ran on the chip TB "
          "(SR15 §4), so the measured previous rung is SR5b's r1: "
          "P-chat(kind) = n588 r1 measured - (r1 static replay - r3 static "
          "replay), both sides the same static model; with the r2 step "
          "shown: r1->r2 replay saving + r2->r3")
    for k in ("lite", "full"):
        print(f"    {k}: r1->r2 replay saving {r1[k] - r2[k][0]} cyc; the "
              f"implied r2 chip-TB image (never measured) "
              f"{r1m[k][0] - (r1[k] - r2[k][0])}..{r1m[k][1] - (r1[k] - r2[k][0])}")
    if not r3pins:
        print("  r3 static makespans: PENDING — R3-6's r3 pins "
              "(sr13b_r2_pins.py --rtl r3) are not committed at this run; the "
              "number is left for R3-9b's brief (formula and inputs above)")
        return
    r3 = pins(r3pins)
    print(f"  r3 static replay / corrected ({os.path.basename(r3pins)}) "
          + ", ".join(f"{k} {r3[k][0]} / {r3[k][1]}" for k in r3))
    for k in ("lite", "full"):
        sv_c = r2[k][1] - r3[k][1]
        sv_r = r2[k][0] - r3[k][0]
        sv1 = r1[k] - r3[k][0]
        print(f"    {k}: r2->r3 saving corrected {sv_c} cyc = "
              f"{D.ms(sv_c):.4f} ms (replay {sv_r}); CHIP TB P-chat "
              f"{r1m[k][0] - sv1}..{r1m[k][1] - sv1} cyc (r1->r3 replay "
              f"saving {sv1}); BOARD P1' = n1508 - {D.ms(sv_c):.4f} ms")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--r3-pins-log", default=None,
                    help="R3-6's committed sr13b_r2_pins.py --rtl r3 log")
    a = ap.parse_args()
    if os.environ.get("FABLE5_MODEL") != "9b":
        raise SystemExit("R3_PREDICT: FABLE5_MODEL=9b required")
    I = inputs()
    P = headline(I)
    seeds(I, P)
    M = classes(I, P)
    one_window(I, M)
    chat(I, a.r3_pins_log)
    print(f"\nR3_PREDICT: PREDICTIONS WRITTEN — P-A {P['PA']} cyc (HELD "
          f"+-0.5 %, LOOSE +-2 %, outside +-2 % STOP before R3-10)")


if __name__ == "__main__":
    main()
