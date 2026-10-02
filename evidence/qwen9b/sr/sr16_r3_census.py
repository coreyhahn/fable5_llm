#!/usr/bin/env python3
"""sr16_r3_census.py — Task SR16 (the R3 decision): what OV1's model says R3
removes, and how sensitive that is to the census's own caveat.  MODEL only;
no device, no RTL.  Run ON SNOKE via sr_run.sh with FABLE5_MODEL=9b:

    FABLE5_MODEL=9b bash evidence/qwen9b/sr/sr_run.sh <log> \
        /home/cah/.venv/bin/python evidence/qwen9b/sr/sr16_r3_census.py

It imports evidence/qwen9b/ov/sr0_clock_sens.py and, through it,
evidence/qwen9b/ov/ov_census.py UNCHANGED (the same stream, BN1 CSV, nodes,
edges, list scheduler and post-check that printed n120), at r = 0 (no clock
cut), and calls ov_census.schedule() directly with the per-channel-fence
config best_schedule() uses, so the stats (lane idle by binding reason) are
visible.  Variants, both forms:

  R2        R1+R2 (xdepth = rdepth = 2): must equal n120:18 / n120:24.
  R3        OV1's R3: the first live MOVX of each matvec keeps its window,
            its live siblings cost 0 and keep THEIR OWN dependencies
            (ov_census.py:1374-1388; sr0_clock_sens.Model.variant).  Must
            equal n120:19 / n120:25.
  R3buf     sr0's staging-buffer row: siblings cost a quarter window, own
            dependencies.  Must equal n120:20 / n120:26.
  R3lat     SENSITIVITY (new here, not a model change): form (a)'s lockstep
            push — the broadcast is ONE write of four XWINs, so the carrier
            (the first live MOVX) inherits every live sibling's done-edges
            and stream-edges (it waits on the LATEST of the four channels'
            readers, OV1_DEPENDENCY_CENSUS.md:771-773) and each sibling
            (cost 0) waits for the carrier.  Bank forcing is NOT modelled.

Per variant it prints the makespan, the lane work (sum of live windows), the
lane idle by binding reason, and the saving against R2.  It also prints the
live-MOVX census at R2 (count, window sum, live MOVX per matvec, the sibling
sum R3 zeroes).
"""
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OV = os.path.join(HERE, "..", "ov")
sys.path.insert(0, os.path.abspath(OV))

import sr0_clock_sens as CS      # noqa: E402  (unchanged)

OC = CS.OC
TBF = CS.TBF
EXPECT = {("B", "R2"): 26146927, ("B", "R3"): 24102767,
          ("B", "R3buf"): 24580127, ("A", "R2"): 27056949,
          ("A", "R3"): 25012789, ("A", "R3buf"): 25498597}   # n120:18-26
CFG = {"lanes": 1, "fence": "perchan", "elide": True, "hoist_guard": True,
       "prio": "bl"}                                  # best_schedule perchan
BAD = []


def ms(c):
    return CS.ms(c)


def live_movx(M, k):
    return [x for x in M.mvs[k]["movx"] if not M.nodes[x].redundant]


def run(M, form, tag):
    chain = "order" if form == "A" else "free"
    OC.build_edges(M.nodes, True, 2, 2, chain)
    saved = [n.dur for n in M.nodes]
    sib_sum = 0
    if tag != "R2":
        for k in range(len(M.mvs)):
            lv = live_movx(M, k)
            if not lv:
                continue
            f = lv[0]
            for s in lv[1:]:
                n = M.nodes[s]
                sib_sum += n.dur
                if tag == "R3buf":
                    n.dur = int(round(n.dur / 4))
                else:
                    n.dur = 0
                if tag == "R3lat":
                    fn = M.nodes[f]
                    for p, kind in list(n.preds.items()):
                        if p not in lv:
                            fn.preds.setdefault(p, "bcast-" + kind)
                    fn.sdeps |= set(n.sdeps)
                    n.preds[f] = "bcast"
    live = [n.kind not in ("fence", "arg") and not n.redundant
            for n in M.nodes]
    lane = sum(n.dur for i, n in enumerate(M.nodes) if live[i])
    try:
        mk, _st, _fi, _se, stt = OC.schedule(M.nodes, M.groups, CFG)
        err = None
    except AssertionError as e:            # a deadlock or a post-check hit
        mk, stt, err = None, None, repr(e)[:200]
    for n, d in zip(M.nodes, saved):
        n.dur = d
    return mk, lane, stt, sib_sum, err


def main():
    M = CS.Model()
    print("\n=== live-MOVX census at R2 (form B edges, elision on)")
    OC.build_edges(M.nodes, True, 2, 2, "free")
    allx = [i for i, n in enumerate(M.nodes) if n.kind == "movx"]
    red = [i for i in allx if M.nodes[i].redundant]
    lvx = [i for i in allx if not M.nodes[i].redundant]
    sz = collections.Counter()
    sib_n = sib_c = first_c = 0
    for k in range(len(M.mvs)):
        lv = live_movx(M, k)
        sz[len(lv)] += 1
        if lv:
            first_c += M.nodes[lv[0]].dur
            sib_n += len(lv) - 1
            sib_c += sum(M.nodes[s].dur for s in lv[1:])
    tot = sum(M.nodes[i].dur for i in allx)
    rs = sum(M.nodes[i].dur for i in red)
    lsum = sum(M.nodes[i].dur for i in lvx)
    print(f"  MOVX records {len(allx)}: window sum {tot} cyc = {ms(tot):.3f} ms TB")
    print(f"  redundant (elided) {len(red)}: {rs} cyc = {ms(rs):.3f} ms TB "
          f"(OV1 n06:29: 480 of 996, 2023680)")
    print(f"  live {len(lvx)}: {lsum} cyc = {ms(lsum):.3f} ms TB")
    print(f"  matvecs {len(M.mvs)}; live MOVX per matvec: "
          + ", ".join(f"{a} x{b}" for a, b in sorted(sz.items())))
    print(f"  broadcast carriers (first live MOVX) {sum(b for a, b in sz.items() if a)}: "
          f"{first_c} cyc = {ms(first_c):.3f} ms TB")
    print(f"  SIBLINGS R3 zeroes: {sib_n} MOVX, {sib_c} cyc = {ms(sib_c):.3f} ms TB "
          f"= {100.0 * sib_c / lsum:.2f} % of live MOVX window")

    res = {}
    for form in ("B", "A"):
        print(f"\n=== form {form}: per-channel FENCE, one lane, elision, r = 0 (TB cycles)")
        for tag in ("R2", "R3", "R3buf", "R3lat"):
            mk, lane, stt, sib, err = run(M, form, tag)
            if err:
                print(f"  {form}:{tag:6s} FAILED: {err}")
                BAD.append((form, tag, err))
                continue
            res[(form, tag)] = (mk, lane, stt)
            idle = stt["idle"]
            exp = EXPECT.get((form, tag))
            chk = ("" if exp is None else
                   f"  n120 {exp} {'MATCH' if exp == mk else 'DIFFER'}")
            if exp is not None and exp != mk:
                BAD.append((form, tag, mk, exp))
            bms = ms(mk) * TBF
            print(f"  {form}:{tag:6s} makespan {mk:9d} cyc = {ms(mk):8.3f} ms TB; "
                  f"board-scaled (uniform, MODEL) {bms:8.3f} ms = {1000.0 / bms:6.3f} tok/s{chk}")
            print(f"      lane work {lane} cyc = {ms(lane):.3f} ms; lane idle "
                  + ", ".join(f"{k} {v} cyc = {ms(v):.3f} ms" for k, v in sorted(idle.items()))
                  + f"; idle total {sum(idle.values())}; tail {mk - lane - sum(idle.values())}")
            print(f"      post-check {stt['post'][0]} edges + {stt['post'][1]} checks, 0 violations")
        r2 = res.get((form, "R2"))
        if not r2:
            continue
        print(f"  --- form {form}: against R2")
        for tag in ("R3", "R3buf", "R3lat"):
            if (form, tag) not in res:
                continue
            mk, lane, stt = res[(form, tag)]
            dl = r2[1] - lane
            di = sum(stt["idle"].values()) - sum(r2[2]["idle"].values())
            dst = stt["idle"].get("stream", 0) - r2[2]["idle"].get("stream", 0)
            print(f"  SAVE {form}:{tag:6s} {r2[0] - mk:8d} cyc = {ms(r2[0] - mk):.3f} ms TB/token; "
                  f"x{r2[0] / mk:.4f} vs R2; lane work removed {dl} cyc = {ms(dl):.3f} ms; "
                  f"lane idle change {di:+d} cyc = {ms(di):+.3f} ms (on stream {dst:+d} = {ms(dst):+.3f} ms)")
        for tag in ("R2", "R3", "R3buf", "R3lat"):
            if (form, tag) not in res:
                continue
            mk, lane, stt = res[(form, tag)]
            s = stt["idle"].get("stream", 0)
            print(f"  SHARE {form}:{tag:6s} lane idle on stream {100.0 * s / mk:.2f} % of makespan; "
                  f"lane work {100.0 * lane / mk:.2f} %")
    if BAD:
        print("SR16_R3_CENSUS: FAIL", BAD)
        sys.exit(1)
    print("SR16_R3_CENSUS: DONE")


if __name__ == "__main__":
    main()
