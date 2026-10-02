#!/usr/bin/env python3
"""r3_5_derive.py — Task R3-5: the r3 streams' numbers beside the census and
SR11b's r2 pair, every figure READ from a committed log (the file and line
printed) and every difference computed HERE (no arithmetic by hand).  Run ON
SNOKE through evidence/qwen9b/sr/sr_run.sh.

  per stream (n2720-n2723): the LOOP BODY replay_mk (census convention) and
  pred_mk (SR11b's corrected convention, reorder_e4.predict), the broadcast
  / siblings-merged / forced / unicast-left counts per segment;
  against: the census R3 row 24,102,767 (n1600_sr16_r3_census.log:26), the
  census carriers / siblings (n1600:18-20), SR11b's r2 pair 26,146,927 /
  26,183,590 (n1165_reorder_s1_B_r2.log:50, :56), R3-4's census saving
  2,044,160 (n2606_r3_4_derive.log:24).
"""
import os
import re

SR = os.path.dirname(os.path.abspath(__file__))


def grab(fn, pat, grp=1):
    path = os.path.join(SR, fn)
    for no, line in enumerate(open(path), 1):
        m = re.search(pat, line)
        if m:
            return int(m.group(grp).replace(",", "")), f"{fn}:{no}"
    raise SystemExit(f"no match for {pat!r} in {fn}")


def allgrab(fn, pat):
    path = os.path.join(SR, fn)
    out = []
    for no, line in enumerate(open(path), 1):
        m = re.search(pat, line)
        if m:
            out.append((tuple(int(g) for g in m.groups()), f"{fn}:{no}"))
    return out


def main():
    cen, cen_at = grab("n1600_sr16_r3_census.log", r"B:R3\s+makespan\s+(\d+)")
    car, car_at = grab("n1600_sr16_r3_census.log",
                       r"broadcast carriers \(first live MOVX\) (\d+)")
    sib, sib_at = grab("n1600_sr16_r3_census.log",
                       r"SIBLINGS R3 zeroes: (\d+) MOVX")
    r2r, r2r_at = grab("n1165_reorder_s1_B_r2.log",
                       r"=== r2: replay makespan.*LOOP BODY (\d+) cyc")
    r2p, r2p_at = grab("n1165_reorder_s1_B_r2.log",
                       r"=== r2: CORRECTED.*LOOP BODY (\d+) cyc")
    sav4, sav4_at = grab("n2606_r3_4_derive.log",
                         r"NET saving per token\s+([\d,]+) cyc")
    print(f"census R3 row (form B, token-4 windows): {cen}  [{cen_at}]")
    print(f"census carriers {car}, siblings zeroed {sib} per token  "
          f"[{car_at}, {sib_at}]")
    print(f"SR11b r2 body: replay {r2r} [{r2r_at}], corrected {r2p} "
          f"[{r2p_at}]")
    print(f"R3-4 census saving: {sav4}  [{sav4_at}]")
    ok = True
    for k in (1, 2, 3, 4):
        fn = f"n272{k - 1}_r3_5_reorder_s{k}_B_r3.log"
        rr, rr_at = grab(fn, r"=== r3: replay makespan.*LOOP BODY (\d+) cyc")
        pp, pp_at = grab(fn, r"=== r3: CORRECTED.*LOOP BODY (\d+) cyc")
        sh, sh_at = None, None
        for no, line in enumerate(open(os.path.join(SR, fn)), 1):
            m = re.search(r"=== wrote \S+\.seq sha256 ([0-9a-f]{64})", line)
            if m:
                sh, sh_at = m.group(1), f"{fn}:{no}"
        segs = allgrab(fn, r"=== r3: seg(\d+) broadcasts (\d+) \(siblings "
                           r"merged (\d+)\), FORCED (\d+), unicast-left "
                           r"groups (\d+) \(MOVX (\d+)\)")
        print(f"--- s{k}: sha256 {sh}  [{sh_at}]")
        for (g, at) in segs:
            s, b, m, f, ug, um = g
            match = (b == car and m == sib and f == 0 and ug == 0 and um == 0)
            ok &= match
            print(f"    seg{s}: broadcasts {b} (census {car}: "
                  f"{b - car:+d}), siblings merged {m} (census {sib}: "
                  f"{m - sib:+d}), forced {f}, unicast-left {ug} groups / "
                  f"{um} MOVX -> {'AS THE CENSUS' if match else 'DIFFERS'}"
                  f"  [{at}]")
        print(f"    LOOP BODY replay_mk {rr} [{rr_at}]: vs census R3 "
              f"{rr - cen:+d}; vs r2 replay {rr - r2r:+d} (saving "
              f"{r2r - rr}, census convention; R3-4's {sav4}: "
              f"{(r2r - rr) - sav4:+d})")
        print(f"    LOOP BODY pred_mk   {pp} [{pp_at}]: vs r2 corrected "
              f"{pp - r2p:+d} (saving {r2p - pp}, corrected convention; "
              f"minus the census-convention saving {(r2p - pp) - (r2r - rr):+d});"
              f" pred - replay {pp - rr:+d} (r2's {r2p - r2r:+d})")
        ok &= rr == cen
    print("R3_5_DERIVE: " + ("PASS (every segment 129 / 387 / 0 / 0; every "
                             "body replay = the census R3 row)"
                             if ok else "DIFFERS (see above)"))


if __name__ == "__main__":
    main()
