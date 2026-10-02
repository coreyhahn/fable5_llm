#!/usr/bin/env python3
"""sr5b_chat_compare.py — Task SR5b (the r1 chat-image rung): judge the
chip-TB runs of chat_seq's r1 step images against the shipped-order runs.

    python evidence/qwen9b/sr/sr5b_chat_compare.py c1 c2 c3 c4

A COPY of evidence/qwen9b/ov/s1t_compare.py (Task S1T), retargeted: the two
sides are `ship` and `r1` (sr5b_<tag>_{ship,r1}, vectors by
evidence/qwen9b/sr/sr5b_chat_vectors.py), both run on the SR5a binary
(tb/obj_dir_seq_chip_sr5, the R1 RTL) by evidence/qwen9b/sr/run_sr_chip.sh,
whose seed logs are evidence/qwen9b/sr/sr5_seed_sr5b_<tag>_<side>_control.log.
For every scenario tag it requires, as S1T did:
  * both runs `TB_SEQ_CHIP PASS` (every launch's end state == its golden);
  * the same number of launches, of the same kinds, in the same order;
  * the chip's OUT tokens IDENTICAL, launch by launch, r1 vs shipped
    (a full launch must emit a token on both sides).
Added for SR5b (printed; the first is REQUIRED):
  * the shipped side on the R1 RTL against S1T's shipped side on the shipped
    RTL (evidence/qwen9b/ov/seedlogs_s1t/s1t_<tag>_ship_control.log), launch by
    launch: cycles must be IDENTICAL (a masked-FENCE-free stream runs on
    the R1 RTL exactly as on the shipped RTL — SR5a's rung 1, per launch);
  * the r1 side against S1T's r0 form-B side (s1t_<tag>_B_control.log):
    the per-launch ratio r0-B / r1;
  * the r1 side against its own STATIC model makespan (n601: lite
    25,195,119, full 27,135,354 — this lineage's numbers, NOT n120's), as a
    percentage.  Informational: the plan sets no band on the chat images.
Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh.

R3-9b addition ("flags, not copies", plan review I-5; defaults = the
committed SR5b use, so n588 reproduces):
    python evidence/qwen9b/sr/sr5b_chat_compare.py c1 c2 c3 c4 \
        --seq-rtl r3 --k r3b --pred-log nNNNN_....log
  * the reordered side is `<level>` (vectors sr5b<level>_<tag>_{ship,<level>}
    by sr5b_chat_vectors.py --seq-rtl <level>), the seed logs
    sr<K>_seed_sr5b<level>_<tag>_<side>_control.log of run_sr_chip.sh K=<K>;
  * the shipped side must still equal S1T's cycles launch by launch;
  * the static model is the level's own (r3: n2801's replay 22,297,831 /
    24,087,146, read from that log);
  * with --pred-log (the committed chat-image prediction, r3_predict.py
    --r3-pins-log): per lite/full launch the PREDICTION = SR5b's measured r1
    cycles of the SAME scenario and launch (sr5_seed_sr5b_<tag>_r1_control.log)
    minus the r1 -> <level> static replay saving of that kind, judged with
    SR15's bands on the absolute form: |measured / predicted - 1| <= 0.5 %
    HELD, <= 2 % HELD LOOSELY, else OUTSIDE +-2 % (report before R3-10).
"""
import argparse
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
LOGDIR = os.path.join(ROOT, "evidence", "qwen9b", "sr")
S1TDIR = os.path.join(ROOT, "evidence", "qwen9b", "ov", "seedlogs_s1t")
STATIC_MK = {"lite": 25_195_119, "full": 27_135_354}   # n601:9, n601:15 (E)
SV1_B_TOK = 171_731_320 / 6          # T: SV1_S1_VERIFY.md §3, s1 form B
SHIP_TOK = 196_706_821 / 6           # T: SV1_S1_VERIFY.md §3 / S4_REPLAY:398
RX_TOK = re.compile(r"^\s*TOK\[(\d+)\] = [0-9a-f]+ \((\d+)\) == golden OK")
RX_L = re.compile(r"^SEQ-CHIP \S+ launch (\d+) \[(\w+)\]: (\d+) records, "
                  r"(\d+) cycles")
RX_P = re.compile(r"^TB_SEQ_CHIP PASS: \S+ \(launches (\d+), (\d+) cycles")


def parse(path):
    launches, toks, passed = [], [], None
    for ln in open(path, errors="replace"):
        m = RX_TOK.match(ln)
        if m:
            toks.append(int(m.group(2)))
            continue
        m = RX_L.match(ln)
        if m:
            launches.append({"i": int(m.group(1)), "kind": m.group(2),
                             "nrec": int(m.group(3)),
                             "cyc": int(m.group(4)), "tok": toks})
            toks = []
            continue
        m = RX_P.match(ln)
        if m:
            passed = (int(m.group(1)), int(m.group(2)))
    return launches, passed


def band(x):
    if abs(x) <= 0.005:
        return "HELD"
    if abs(x) <= 0.02:
        return "HELD LOOSELY"
    return "OUTSIDE +-2 %"


def static_mk(lv):
    """{kind: static replay makespan} of the level's own pins log."""
    if lv == "r1":
        return dict(STATIC_MK)
    t = open(os.path.join(LOGDIR, "n2801_r3_6_pins.log")).read()
    out = {}
    for k in ("lite", "full"):
        m = re.search(r"^=== STATIC model, position 0, %s: .*?%s replay (\d+) "
                      r"cyc" % (k, lv), t, re.M)
        out[k] = int(m.group(1))
    return out


def pred_saving(path):
    """{kind: r1 -> level static replay saving} from r3_predict.py's log."""
    t = open(path if os.path.isabs(path) else os.path.join(LOGDIR, path)).read()
    out = {}
    for k in ("lite", "full"):
        m = re.search(r"^\s+%s: r2->r3 saving .*?CHIP TB P-chat (\d+)\.\.(\d+) "
                      r"cyc \(r1->r3 replay saving (\d+)\)" % k, t, re.M)
        out[k] = int(m.group(3))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tags", nargs="+")
    ap.add_argument("--seq-rtl", default="r1")
    ap.add_argument("--k", default="5", help="run_sr_chip.sh K of the runs")
    ap.add_argument("--pred-log", default=None)
    a = ap.parse_args()
    tags, lv = a.tags, a.seq_rtl
    fpre = "sr5b" if lv == "r1" else f"sr5b{lv}"
    smk = static_mk(lv)
    sav = pred_saving(a.pred_log) if a.pred_log else None
    if sav:
        print(f"  PREDICTION (committed, {os.path.basename(a.pred_log)}): per "
              f"launch = SR5b's measured r1 launch - the r1->{lv} static "
              f"replay saving: " + ", ".join(f"{k} {v:,d}" for k, v in sav.items()))
    ok = True
    agg = {}
    verd = []
    for tag in tags:
        side = {}
        for s in ("ship", lv):
            p = os.path.join(LOGDIR, f"sr{a.k}_seed_{fpre}_{tag}_{s}_control.log")
            side[s] = parse(p)
            L, P = side[s]
            print(f"  {tag} {s:4s}: {os.path.relpath(p, ROOT)}  "
                  f"{'PASS ' + str(P) if P else 'NO PASS LINE'}")
            ok &= P is not None and P[0] == len(L)
        r1L = None
        if lv != "r1":
            p = os.path.join(LOGDIR, f"sr5_seed_sr5b_{tag}_r1_control.log")
            r1L = parse(p)[0]
            print(f"  {tag} r1 (SR5b, measured): {os.path.relpath(p, ROOT)}")
        (Ls, Ps), (Lb, Pb) = side["ship"], side[lv]
        s1t = {}
        for s in ("ship", "B"):
            p = os.path.join(S1TDIR, f"s1t_{tag}_{s}_control.log")
            s1t[s] = parse(p)[0] if os.path.exists(p) else None
        if len(Ls) != len(Lb) or [x["kind"] for x in Ls] != [
                y["kind"] for y in Lb]:
            print(f"  {tag}: LAUNCH SEQUENCES DIFFER — FAIL")
            ok = False
            continue
        for j, (x, y) in enumerate(zip(Ls, Lb)):
            same = x["tok"] == y["tok"]
            if x["kind"] == "full" and not (x["tok"] and y["tok"]):
                print(f"    launch {x['i']} full: EMPTY token list "
                      f"(ship {x['tok']}, r1 {y['tok']}) — FAIL")
                same = False
            ok &= same
            r = x["cyc"] / y["cyc"]
            agg.setdefault(x["kind"], []).append((x["cyc"], y["cyc"]))
            extra = ""
            if s1t["ship"] is not None:
                z = s1t["ship"][j]
                eq = z["kind"] == x["kind"] and z["cyc"] == x["cyc"] \
                    and z["tok"] == x["tok"]
                ok &= eq
                extra += (f"; ship vs S1T ship {z['cyc']:,d}: "
                          f"{'IDENTICAL' if eq else 'DIFFER — FAIL'}")
            else:
                ok = False
                extra += "; S1T ship log MISSING — FAIL"
            if s1t["B"] is not None:
                zb = s1t["B"][j]
                extra += (f"; r0-B {zb['cyc']:,d} / r1 = x{zb['cyc'] / y['cyc']:.4f}")
            if x["kind"] in smk:
                mk = smk[x["kind"]]
                extra += (f"; {lv} vs static model {mk:,d}: "
                          f"{100.0 * (y['cyc'] - mk) / mk:+.3f} %")
            if r1L is not None:
                z1 = r1L[j]
                assert z1["kind"] == x["kind"]
                tk = z1["tok"] == y["tok"]
                ok &= tk
                extra += (f"; r1 (SR5b) {z1['cyc']:,d} -> {lv} saves "
                          f"{z1['cyc'] - y['cyc']:,d}, tokens vs r1 "
                          f"{'IDENTICAL' if tk else 'DIFFER — FAIL'}")
                if sav and x["kind"] in sav:
                    pr = z1["cyc"] - sav[x["kind"]]
                    d = (y["cyc"] - pr) / pr
                    verd.append((x["kind"], d))
                    extra += (f"; PREDICTED {pr:,d}: {y['cyc'] - pr:+,d} cyc "
                              f"= {100.0 * d:+.3f} % -> {band(d)}")
            print(f"    launch {x['i']} {x['kind']:8s} records "
                  f"{x['nrec']:6d} -> {y['nrec']:6d}  cycles "
                  f"{x['cyc']:11,d} -> {y['cyc']:11,d}  x{r:.4f}  tokens "
                  f"{x['tok']} vs {y['tok']} "
                  f"{'IDENTICAL' if same else 'DIFFER'}{extra}")
        if Ps and Pb:
            print(f"    total cycles {Ps[1]:,d} -> {Pb[1]:,d}  "
                  f"x{Ps[1] / Pb[1]:.4f}")
    print(f"--- per launch kind, over all scenarios (shipped -> {lv})")
    for k, v in agg.items():
        rs = [a / b for a, b in v]
        print(f"  {k:8s} n={len(v)}  shipped {min(a for a, _ in v):,d}.."
              f"{max(a for a, _ in v):,d}  {lv} {min(b for _, b in v):,d}.."
              f"{max(b for _, b in v):,d}  x{min(rs):.4f}..x{max(rs):.4f}")
        sa = max(a for a, _ in v) - min(a for a, _ in v)
        sb = max(b for _, b in v) - min(b for _, b in v)
        print(f"  {k:8s} spread: shipped {sa:,d} cyc "
              f"({sa / min(a for a, _ in v):.5%}), {lv} {sb:,d} cyc "
              f"({sb / min(b for _, b in v):.5%})")
    print(f"  SV1 template per token (T): shipped {SHIP_TOK:,.0f}, form B "
          f"{SV1_B_TOK:,.0f}, x{SHIP_TOK / SV1_B_TOK:.4f}")
    if verd:
        for k in ("lite", "full"):
            ds = [d for kk, d in verd if kk == k]
            if ds:
                w = max(ds, key=abs)
                print(f"  CHAT PREDICTION {k}: n={len(ds)} launches, measured "
                      f"vs predicted {100 * min(ds):+.3f} % .. "
                      f"{100 * max(ds):+.3f} %; worst {100 * w:+.3f} % -> "
                      f"{band(w)}")
        w = max((d for _k, d in verd), key=abs)
        print(f"  CHAT PREDICTION VERDICT ({len(verd)} launches): {band(w)} "
              f"(worst {100 * w:+.3f} %)")
    print(f"SR5B_CHAT_COMPARE: {'PASS' if ok else 'FAIL'} — {len(tags)} "
          f"scenario(s), tokens {'IDENTICAL' if ok else 'NOT all identical / runs failed'}"
          f"; shipped side == S1T's cycles launch by launch "
          f"{'YES' if ok else '(see above)'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
