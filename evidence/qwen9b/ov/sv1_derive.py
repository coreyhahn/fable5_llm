#!/usr/bin/env python3
"""sv1_derive.py — Task SV1: every derived number SV1_S1_VERIFY.md quotes.

Reads committed logs only (the chip-TB wrapper logs, the reorder logs, the
census timeline log) and prints one numbered-by-line result per quantity.
Run ON SNOKE through evidence/qwen9b/ov/ov_run.sh.

    python evidence/qwen9b/ov/sv1_derive.py
"""
import os
import re
import sys

OV = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(OV, "..", "..", ".."))
HZ = 250_000_000.0
NTOK = 6
TODAY = {1: 196706821, 2: 196707670, 3: 196707670, 4: 196706833}  # S4 031
TB_MS, BOARD_MS = 131.138, 137.121          # BN_CENSUS / RD9 (S)
SCALE = BOARD_MS / TB_MS
PRED_BODY = {"B": 28612019, "A": 29486120}   # OV1 n15:814 / :778 (E)
REORD_LOG = {"B": {1: "n32_reorder_s1_B.log", 2: "n34_reorder_s2_B.log",
                   3: "n35_reorder_s3_B.log", 4: "n36_reorder_s4_B.log"},
             "A": {1: "n37_reorder_s1_A.log", 2: "n38_reorder_s2_A.log",
                   3: "n39_reorder_s3_A.log", 4: "n40_reorder_s4_A.log"}}
CHIP_LOG = {"B": {1: "n53", 2: "n54", 3: "n55", 4: "n56"},
            "A": {1: "n62", 2: "n63", 3: "n64", 4: "n65"}}
LOOP = {1: 3, 2: 5, 3: 5, 4: 3}      # body iterations (manifest loop_steps)


def ms(c):
    return c / HZ * 1e3


def rd(name):
    return open(os.path.join(OV, name)).read()


def find(prefix):
    m = [f for f in sorted(os.listdir(OV)) if f.startswith(prefix + "_")
         and f.endswith(".log")]
    return m[0] if m else None


def segs(form, s):
    """[(orig window, emitted-order replay)] per segment, in order."""
    t = rd(REORD_LOG[form][s])
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
            "pass": re.search(r"SV1_CHIP \S+ \S+: PASS", t) is not None,
            "wall": (re.search(r"=== wall\s+(\d+)s", t) or [0, "0"])[1]}


def main():
    print(f"SCALE board/TB = {BOARD_MS}/{TB_MS} = {SCALE:.5f}")
    for form in ("B", "A"):
        print(f"\n=== form {form}")
        for s in (1, 2, 3, 4):
            sg = segs(form, s)
            # the stream runs every unrolled segment once and the body
            # LOOP[s] times; the body is the last segment
            orig = sum(o for o, _ in sg[:-1]) + LOOP[s] * sg[-1][0]
            new = sum(r for _, r in sg[:-1]) + LOOP[s] * sg[-1][1]
            over = TODAY[s] - orig      # launch/prologue cycles no window holds
            pred = new + over
            c = chip(CHIP_LOG[form][s])
            print(f"  s{s}: today {TODAY[s]} cyc = {ms(TODAY[s]) / NTOK:.3f} "
                  f"ms/token; model: token windows {orig}, outside {over}; "
                  f"PREDICTED whole run {pred} cyc = {ms(pred) / NTOK:.3f} "
                  f"ms/token (x{TODAY[s] / pred:.4f})")
            if c is None or c["cyc"] is None:
                print(f"  s{s}: chip run: NOT YET")
                continue
            m = ms(c["cyc"]) / NTOK
            print(f"  s{s}: MEASURED {c['cyc']} cyc = {m:.3f} ms/token "
                  f"(x{TODAY[s] / c['cyc']:.4f} vs today's same seed; "
                  f"vs 131.138: x{TB_MS / m:.4f}); measured - predicted "
                  f"{c['cyc'] - pred:+d} cyc = {100.0 * (c['cyc'] - pred) / pred:+.3f} %; "
                  f"saving measured {TODAY[s] - c['cyc']} vs predicted "
                  f"{TODAY[s] - pred} = {100.0 * (TODAY[s] - c['cyc']) / (TODAY[s] - pred):.1f} %"
                  f"; tokens {'IDENTICAL' if c['tok'] else 'DIFFER'}; "
                  f"runner {'PASS' if c['pass'] else 'FAIL'}; wall {c['wall']} s; {c['log']}")
            print(f"  s{s}: board-scaled {m * SCALE:.3f} ms/token = "
                  f"{1000.0 / (m * SCALE):.3f} tok/s (today "
                  f"{1000.0 / (ms(TODAY[s]) / NTOK * SCALE):.3f})")
    # --- the timeline run: token 4 directly against OV1's body schedule
    tl = find("n57")
    if tl:
        t = rd(tl)
        base = open(os.path.join(REPO, "evidence", "qwen9b", "bn",
                                 "003_timeline_model_9b_s1.log")).read()

        def tcyc(txt):
            return {int(a): int(b) for a, b in
                    re.findall(r"^SEQ_TIMELINE tcyc (\d+) (\d+)", txt, re.M)}

        def cls(txt, k):
            return {n: int(v) for n, v in re.findall(
                rf"^SEQ_TIMELINE class {k} \d+ (\S+) (\d+)", txt, re.M)}
        a, b = tcyc(base), tcyc(t)
        print("\n=== timeline s1 form B vs the census (per token, cycles)")
        for k in sorted(b):
            if k in a:
                print(f"  token {k}: today {a[k]} = {ms(a[k]):.3f} ms; S1 "
                      f"{b[k]} = {ms(b[k]):.3f} ms; x{a[k] / b[k]:.4f}")
        if 4 in b:
            p = PRED_BODY["B"]
            print(f"  token 4 vs OV1 form-B prediction {p} = {ms(p):.3f} ms: "
                  f"measured - predicted {b[4] - p:+d} cyc = "
                  f"{100.0 * (b[4] - p) / p:+.3f} %; saving measured "
                  f"{a[4] - b[4]} vs predicted {a[4] - p} = "
                  f"{100.0 * (a[4] - b[4]) / (a[4] - p):.1f} %")
        ca, cb = cls(base, 4), cls(t, 4)
        if cb:
            print("  token 4 per class (busy cycles; classes overlap): "
                  "today -> S1 (delta)")
            for n in ca:
                print(f"    {n:8s} {ca[n]:9d} -> {cb.get(n, 0):9d} "
                      f"({cb.get(n, 0) - ca[n]:+d} = "
                      f"{ms(cb.get(n, 0) - ca[n]):+.3f} ms)")




# ======================================================================
# per-class and per-opcode comparison, token 4, s1 form B (n57's CSV)
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


def class_compare():
    import collections
    import hashlib
    sys.path.insert(0, OV)
    import ov_census as OC
    SF = OC.SF
    new_csv = os.path.join(REPO, "tb", "scripts", "w9",
                           "model_9b_s1_reordB.timeline.csv")
    want = open(os.path.join(OV, "sv1_timeline_model_9b_s1_reordB.csv.sha256")
                ).read().split()[0]
    h = hashlib.sha256()
    with open(new_csv, "rb") as f:
        for ch in iter(lambda: f.read(1 << 24), b""):
            h.update(ch)
    print(f"\n=== per-class comparison, token 4, s1 form B; S1 CSV sha256 "
          f"{'MATCH' if h.hexdigest() == want else 'MISMATCH'}")
    assert h.hexdigest() == want
    recs, _man = OC.load_stream()
    lo, hi = OC.body_range(recs)
    r4 = OC.load_csv(toks=(4,))[4]
    nodes = OC.build_nodes(recs, lo, hi, r4)
    groups, _ = OC.stream_durations(nodes, r4)
    mvs, _ = OC.segment_matvecs(nodes, groups)
    key = {}
    for n in nodes:
        if n.kind == "mvgo":
            r = recs[n.pc]
            mv = mvs[n.mv]
            key[r.to_bytes()] = (mv["lt"], mv["cls"])
    # today: FENCE windows by the class of the group they drain
    today = collections.Counter()
    for g in groups:
        mv = mvs[g["mv"]]
        today[(mv["lt"], mv["cls"])] += g["fwin"]
    # S1 measured: walk the reordered body statically; a FENCE's window is
    # charged to the class of the LAST-issued pending MVGO it drains
    nrecs = SF.unpack_stream(open(os.path.join(
        REPO, "tb", "scripts", "w9", "model_9b_s1_reordB.e4.seq"), "rb").read())
    jmp = [i for i, r in enumerate(nrecs) if r.opcode == SF.OP_JMP][0]
    blo = nrecs[jmp].imm32
    n4 = read_csv_tok(new_csv, 4)
    miss = [pc for pc in range(blo, jmp + 1) if pc not in n4]
    assert not miss, f"{len(miss)} body pcs missing in token 4"
    meas = collections.Counter()
    last = None
    op_new = collections.Counter()
    for pc in range(blo, jmp + 1):
        r = nrecs[pc]
        assert n4[pc][0] == r.opcode
        op_new[SF.OP_NAME[r.opcode]] += n4[pc][2]
        if r.opcode == SF.OP_MVGO:
            last = key[r.to_bytes()]
        elif r.opcode == SF.OP_FENCE:
            meas[last] += n4[pc][2]
    op_old = collections.Counter()
    for pc in range(lo, hi + 1):
        op_old[SF.OP_NAME[recs[pc].opcode]] += r4[pc][2]
    # OV1's model, S1 form B column (n15)
    t = rd("n15_all_fix2.log")
    blk = t.split("D2 sensitivity, form B")[1].split("ALL")[0]
    model = {}
    for m in re.finditer(r"^\s+(DN|GQA|HEAD)\s+(\S+)\s+([\d.]+)\s+([\d.]+)"
                         r"\s+([\d.]+)", blk, re.M):
        model[(m.group(1), m.group(2))] = float(m.group(5))
    # fix round 1 (M-S2): the model's TOTAL is n15's own ALL row (computed
    # there at full precision), not a sum of its 3-decimal class cells
    allrow = re.search(r"^\s+ALL\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)",
                       t.split("D2 sensitivity, form B")[1], re.M)
    model_all = float(allrow.group(3))
    print("  class            today(E)  model S1  meas S1 | recovered: "
          "model   measured   (ms/token; exposed stream wait = FENCE windows)")
    tt = tm = tmo = 0.0
    for k in sorted(today, key=lambda k: (["DN", "GQA", "HEAD"].index(k[0]),
                                          k[1])):
        a, b, mo = ms(today[k]), ms(meas.get(k, 0)), model.get(k, float("nan"))
        tt += a
        tm += b
        tmo += mo
        print(f"  {k[0]:4s} {k[1]:9s} {a:9.3f} {mo:9.3f} {b:8.3f} | "
              f"{a - mo:9.3f} {a - b:10.3f}")
    print(f"  ALL            {tt:9.3f} {model_all:9.3f} {tm:8.3f} | "
          f"{tt - model_all:9.3f} {tt - tm:10.3f}   (model ALL = n15's own "
          f"total; the sum of its rounded class cells is {tmo:.3f})")
    print(f"  measured S1 fence wait - model S1: {tm - model_all:+.3f} ms")
    print("  lane work by opcode, token 4 (ms): today -> S1 measured (delta);"
          " the model holds every non-FENCE window fixed")
    for o in sorted(set(op_old) | set(op_new)):
        print(f"    {o:6s} {ms(op_old[o]):9.3f} -> {ms(op_new[o]):9.3f} "
              f"({ms(op_new[o] - op_old[o]):+.3f})")
    s_old = sum(v for k, v in op_old.items() if k != "FENCE")
    s_new = sum(v for k, v in op_new.items() if k != "FENCE")
    print(f"    non-FENCE lane work: {ms(s_old):.3f} -> {ms(s_new):.3f} ms "
          f"({ms(s_new - s_old):+.3f})")


if __name__ == "__main__":
    main()
    if find("n57"):
        class_compare()
